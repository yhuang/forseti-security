# Copyright 2017 The Forseti Security Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Forseti Server installer."""

from __future__ import print_function
import os
import random

from forseti_installer import ForsetiInstaller
from util import constants
from util import files
from util import gcloud
from util import utils


class ForsetiServerInstaller(ForsetiInstaller):
    """Forseti server installer."""

    gsuite_service_acct_email = None
    has_roles_script = False
    setup_explain = True
    enable_write_access = True
    resource_root_id = None
    access_target = None
    target_id = None
    user_can_grant_roles = True

    def __init__(self, config, previous_installer=None):
        """Init.

        Args:
            config (ServerConfig): The configuration object.
            previous_installer (ForsetiInstaller): The previous ran installer,
                we can get the installer environment information from it.
        """
        super(ForsetiServerInstaller, self).__init__(config,
                                                     previous_installer)

    def preflight_checks(self):
        """Pre-flight checks for server instance."""

        super(ForsetiServerInstaller, self).preflight_checks()
        self.config.generate_cloudsql_instance()
        self.get_email_settings()
        gcloud.enable_apis(self.config.dry_run)
        self.determine_access_target()
        print('Forseti will be granted write access and required roles to: '
              '{}'.format(self.resource_root_id))

    def deploy(self, deployment_tpl_path, conf_file_path, bucket_name):
        """Deploy Forseti using the deployment template.
        Grant access to service account.

        Args:
            deployment_tpl_path (str): Deployment template path.
            conf_file_path (str): Configuration file path.
            bucket_name (str): Name of the GCS bucket.

        Returns:
            bool: Whether or not the deployment was successful.
            str: Deployment name.
        """
        success, deployment_name = super(ForsetiServerInstaller, self).deploy(
            deployment_tpl_path, conf_file_path, bucket_name)

        if success:
            # Fill in the default values for all the rule files
            default_rule_values = self.get_rule_default_values()
            files.update_rule_files(default_rule_values,
                                    constants.RULES_DIR_PATH)

            print('Copying the default Forseti rules to:\n\t{}'.format(
                os.path.join(bucket_name, 'rules')))

            # Copy the rule directory to the GCS bucket.
            files.copy_file_to_destination(
                constants.RULES_DIR_PATH, bucket_name,
                is_directory=True, dry_run=self.config.dry_run)

            self.has_roles_script = gcloud.grant_server_svc_acct_roles(
                self.enable_write_access,
                self.access_target,
                self.target_id,
                self.project_id,
                self.gcp_service_acct_email,
                self.user_can_grant_roles)

            # Waiting for VM to be initialized.
            instance_name = 'forseti-{}-vm-{}'.format(
                self.config.installation_type,
                self.config.identifier)
            self.wait_until_vm_initialized(instance_name)

            # Create firewall rules.
            self.create_firewall_rules()

        return success, deployment_name

    def create_firewall_rules(self):
        """Create firewall rules for Forseti server instance."""
        # Rule to block out all the ingress traffic.
        gcloud.create_firewall_rule(
            self.format_firewall_rule_name('forseti-server-deny-all'),
            [self.gcp_service_acct_email],
            constants.FirewallRuleAction.DENY,
            ['icmp', 'udp', 'tcp'],
            constants.FirewallRuleDirection.INGRESS,
            1,
            self.config.vpc_host_network)

        # Rule to open only port tcp:50051 within the
        # internal network (ip-ranges - 10.128.0.0/9).
        gcloud.create_firewall_rule(
            self.format_firewall_rule_name('forseti-server-allow-grpc'),
            [self.gcp_service_acct_email],
            constants.FirewallRuleAction.ALLOW,
            ['tcp:50051'],
            constants.FirewallRuleDirection.INGRESS,
            0,
            self.config.vpc_host_network,
            '10.128.0.0/9')

        # Create firewall rule to open only port tcp:22 (ssh)
        # to all the external traffics from the internet.
        gcloud.create_firewall_rule(
            self.format_firewall_rule_name(
                'forseti-server-allow-ssh-external'),
            [self.gcp_service_acct_email],
            constants.FirewallRuleAction.ALLOW,
            ['tcp:22'],
            constants.FirewallRuleDirection.INGRESS,
            0,
            self.config.vpc_host_network,
            '0.0.0.0/0')


    def format_firewall_rule_name(self, rule_name):
        """Format firewall rule name.

        Args:
            rule_name (str): Name of the firewall rule.

        Returns:
            str: Firewall rule name.
        """
        return '{}-{}'.format(rule_name, self.config.identifier)

    def get_deployment_values(self):
        """Get deployment values.

        Returns:
            dict: A dictionary of values needed to generate
                the forseti deployment template.
        """
        bucket_name = self.generate_bucket_name()
        return {
            'CLOUDSQL_REGION': self.config.cloudsql_region,
            'CLOUDSQL_INSTANCE_NAME': self.config.cloudsql_instance,
            'FORSETI_BUCKET': bucket_name[len('gs://'):],
            'BUCKET_LOCATION': self.config.bucket_location,
            'GCP_SERVER_SERVICE_ACCOUNT': self.gcp_service_acct_email,
            'FORSETI_SERVER_REGION': self.config.cloudsql_region,
            'FORSETI_SERVER_ZONE': self.config.cloudsql_region + '-c',
            'VPC_HOST_PROJECT_ID': self.config.vpc_host_project_id,
            'VPC_HOST_NETWORK': self.config.vpc_host_network,
            'VPC_HOST_SUBNETWORK': self.config.vpc_host_subnetwork,
            'FORSETI_VERSION': self.version,
            'RAND_MINUTE': random.randint(0, 59)
        }

    def get_configuration_values(self):
        """Get configuration values.

        Returns:
            dict: A dictionary of values needed to generate
                the forseti configuration file.
        """
        bucket_name = self.generate_bucket_name()
        return {
            'EMAIL_RECIPIENT': self.config.notification_recipient_email,
            'EMAIL_SENDER': self.config.notification_sender_email,
            'SENDGRID_API_KEY': self.config.sendgrid_api_key,
            'FORSETI_BUCKET': bucket_name[len('gs://'):],
            'DOMAIN_SUPER_ADMIN_EMAIL': self.config.gsuite_superadmin_email,
            'ROOT_RESOURCE_ID': self.resource_root_id,
        }

    def get_rule_default_values(self):
        """Get rule default values.

        Returns:
            dict: A dictionary of default values.
        """
        organization_id = self.resource_root_id.split('/')[-1]
        domain = gcloud.get_domain_from_organization_id(organization_id)
        return {
            'ORGANIZATION_ID': organization_id,
            'DOMAIN': domain
        }

    def determine_access_target(self):
        """Determine where to enable Forseti access.

        Allow only org level access since IAM explain
        requires org level access.
        """
        utils.print_banner('Forseti Installation Configuration')

        if not self.config.advanced_mode:
            self.access_target = constants.RESOURCE_TYPES[0]
            self.target_id = self.organization_id

        while not self.target_id:
            if self.setup_explain:
                # If user wants to setup Explain, they must setup
                # access on an organization.
                choice_index = 1
            else:
                try:
                    print(constants.MESSAGE_FORSETI_CONFIGURATION_ACCESS_LEVEL)
                    for (i, choice) in enumerate(constants.RESOURCE_TYPES):
                        print('[%s] %s' % (i+1, choice))
                    choice_input = raw_input(
                        constants.QUESTION_FORSETI_CONFIGURATION_ACCESS_LEVEL
                    ).strip()
                    choice_index = int(choice_input)
                except ValueError:
                    print('Invalid choice, try again.')
                    continue

            if choice_index and choice_index <= len(constants.RESOURCE_TYPES):
                self.access_target = constants.RESOURCE_TYPES[choice_index-1]
                if self.access_target == 'organization':
                    self.target_id = gcloud.choose_organization()
                elif self.access_target == 'folder':
                    self.target_id = gcloud.choose_folder(self.organization_id)
                else:
                    self.target_id = gcloud.choose_project()

        self.resource_root_id = utils.format_resource_id(
            '%ss' % self.access_target, self.target_id)

    def get_email_settings(self):
        """Ask user for specific install values."""
        utils.print_banner('Configuring GSuite Admin Information')
        print(constants.MESSAGE_ASK_GSUITE_SUPERADMIN_EMAIL)
        self.config.gsuite_superadmin_email = raw_input(
            constants.QUESTION_GSUITE_SUPERADMIN_EMAIL).strip()

        if self.config.skip_sendgrid_config:
            print(constants.MESSAGE_SKIP_SENDGRID_API_KEY)
            return

        utils.print_banner('Configuring Forseti Email Settings')
        if not self.config.sendgrid_api_key:
            # Ask for SendGrid API Key.
            print(constants.MESSAGE_ASK_SENDGRID_API_KEY)
            self.config.sendgrid_api_key = raw_input(
                constants.QUESTION_SENDGRID_API_KEY).strip()
        if self.config.sendgrid_api_key:
            if not self.config.notification_sender_email:
                self.config.notification_sender_email = (
                    constants.NOTIFICATION_SENDER_EMAIL)

            # Ask for notification recipient email.
            if not self.config.notification_recipient_email:
                self.config.notification_recipient_email = raw_input(
                    constants.QUESTION_NOTIFICATION_RECIPIENT_EMAIL).strip()

    def post_install_instructions(self, deploy_success,
                                  forseti_conf_path, bucket_name):
        """Show post-install instructions.

        For example: link for deployment manager dashboard and
        link to go to G Suite service account and enable DWD.

        Args:
            deploy_success (bool): Whether deployment was successful
            forseti_conf_path (str): Forseti configuration file path
            bucket_name (str): Name of the GCS bucket

        Returns:
            ForsetiInstructions: Forseti instructions.
        """
        instructions = (
            super(ForsetiServerInstaller, self).post_install_instructions(
                deploy_success, forseti_conf_path, bucket_name))

        instructions.other_messages.append(
            constants.MESSAGE_ENABLE_GSUITE_GROUP_INSTRUCTIONS)

        if self.has_roles_script:
            instructions.other_messages.append(
                constants.MESSAGE_HAS_ROLE_SCRIPT)

        if not self.config.sendgrid_api_key:
            instructions.other_messages.append(
                constants.MESSAGE_FORSETI_SENDGRID_INSTRUCTIONS)

        instructions.other_messages.append(constants.MESSAGE_RUN_FREQUENCY)

        return instructions

    @staticmethod
    def _get_gcs_path(resources):
        """Get gcs path from resources.

        Args:
            resources (list): List of resources under the notifier section in
                the forseti_config_server.yaml file.
        Returns:
            str: The gcs path.
        """
        for resource in resources:
            notifiers = resource['notifiers']
            for notifier in notifiers:
                if notifier['name'] == 'gcs_violations':
                    return notifier['configuration']['gcs_path']
        return ''
