# Copyright 2017 The Forseti Security Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Rules Engine and Rules tests."""

import mock
import unittest

from google.cloud.security.auditor import condition_parser
from google.cloud.security.auditor import rules_engine
from google.cloud.security.auditor import rules_config_validator
from google.cloud.security.auditor.rules import rule
from google.cloud.security.common.gcp_type import project as project_resource
from tests.auditor.test_data import test_auditor_data
from tests.unittest_utils import ForsetiTestCase


class RulesEngineTest(ForsetiTestCase):
    """RulesEngineTest."""

    def setUp(self):
        """Setup."""
        pass

    @mock.patch.object(
        rules_config_validator.RulesConfigValidator, 'validate')
    def test_setup(self, mock_rules_validate):
        """Test setup()."""
        fake_rules_path = '/fake/path/rules.yaml'
        rules_eng = rules_engine.RulesEngine(fake_rules_path)
        mock_rules_validate.return_value = test_auditor_data.FAKE_RULES_CONFIG1
        expected_rules = [
            rule.Rule.create_rule(r)
            for r in test_auditor_data.FAKE_RULES_CONFIG1.get('rules', [])]

        rules_eng.setup()

        self.assertEquals(expected_rules, rules_eng.rules)
        self.assertEquals(fake_rules_path, rules_eng.rules_config_path)

    @mock.patch.object(rule.Rule, 'audit', autospec=True)
    def test_evaluate_rules(self, mock_rule_audit):
        """Test evaluate_rules() returns expected results."""
        fake_rules_path = '/fake/path/rules.yaml'
        rules_eng = rules_engine.RulesEngine(fake_rules_path)
        rules_eng.rules = [
            rule.Rule.create_rule(r)
            for r in test_auditor_data.FAKE_RULES_CONFIG1['rules']]

        fake_project = project_resource.Project('proj1', 1111)
        fake_result = rule.RuleResult(
            rule_id=rules_eng.rules[0].rule_id,
            resource=fake_project,
            result=True,
            metadata={})
        expected_results = [fake_result]
        mock_rule_audit.side_effect = [
            fake_result,
            None
        ]
        actual_results = rules_eng.evaluate_rules(fake_project)
        self.assertEquals(expected_results, actual_results)


class RulesTest(ForsetiTestCase):
    """RulesTest."""

    def test_create_rule_works(self):
        """Test create_rule() works."""
        fake_rule_def = test_auditor_data.FAKE_RULES_CONFIG1['rules'][0]
        new_rule = rule.Rule.create_rule(fake_rule_def)
        self.assertEquals(fake_rule_def['type'], new_rule.type)

    def test_create_rule_fails(self):
        """Test create_rule() fails on nonexistent rule type."""
        fake_invalid_rule_def = test_auditor_data.FAKE_INVALID_RULES_CONFIG1['rules'][0]
        with self.assertRaises(rule.InvalidRuleTypeError):
            new_rule = rule.Rule.create_rule(fake_invalid_rule_def)

    @mock.patch('google.cloud.security.auditor.condition_parser.ConditionParser', autospec=True)
    def test_audit(self, mock_condition_parser_class):
        """Test audit()."""
        mock_cond_parser = mock_condition_parser_class.return_value
        fake_project = project_resource.Project('proj1', 1111)
        test_rule = rule.Rule.create_rule(
            test_auditor_data.FAKE_RULES_CONFIG1['rules'][0])
        mock_cond_parser.eval_filter.return_value = True
        actual_result = test_rule.audit(fake_project)
        expected_result = rule.RuleResult(
            rule_id=test_rule.rule_id,
            resource=fake_project,
            result=True,
            metadata={})
        mock_cond_parser.eval_filter.assert_called_with(test_rule.condition)
        self.assertEquals(expected_result, actual_result)


if __name__ == '__main__':
    unittest.main()