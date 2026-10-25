"""Regression coverage for user-visible blank/optional-field semantics (v0.5.2)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings
from astrbot_plugin_peer_context_guard.core import (
    parse_roster, build_rules_from_setup, session_config, has_keyword
)
from test_linked import example


class BlankFieldAudit(unittest.TestCase):
    def cfg(self):
        return copy.deepcopy(example())

    def test_alias_empty_string_is_accepted(self):
        for row in ('1000000003|机器人C', '1000000003|机器人C|',
                    '1000000003|机器人C|  ', '1000000003|机器人C|,，;；'):
            with self.subTest(row=row):
                v=self.cfg()
                v['robot_setup']['group_sessions'][0]['bots']=[row]
                out=validate_all(v)['robot_setup']['group_sessions'][0]['bots']
                self.assertEqual(out, ['1000000003|机器人C'])
                self.assertEqual(parse_roster(out)['1000000003']['aliases'], [])

    def test_all_blank_bot_entry_is_ignored_on_save(self):
        for row in ('', ' ', '||', ' | | ', '\t||\t'):
            with self.subTest(row=row):
                v=self.cfg()
                v['robot_setup']['group_sessions'][0]['bots'].append(row)
                result=validate_all(v)
                self.assertEqual(len(result['robot_setup']['group_sessions'][0]['bots']),2)

    def test_partial_bot_entry_fails_not_ignored(self):
        for row in ('1000000003||', '|助手|别名', '1000000003|', 'abc|机器人', '1000000003|  |别名', '1000000003|机器人|别名|非法'):
            with self.subTest(row=row):
                v=self.cfg()
                v['robot_setup']['group_sessions'][0]['bots']=[row]
                with self.assertRaises(InvalidSettings):validate_all(v)

    def test_duplicate_id_never_silently_ignored(self):
        v=self.cfg()
        v['robot_setup']['group_sessions'][0]['bots']=['1000000003|机器人','1000000003|别名不同']
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_own_qq_not_allowed_in_other_bot_roster(self):
        v=self.cfg()
        v['robot_setup']['group_sessions'][0]['bots']=['1000000001|机器人A']
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_no_alias_recall_does_not_require_one(self):
        self.assertEqual(parse_roster(['1000000003|助手'])['1000000003']['aliases'],[])

    def test_empty_optional_instance_id_and_labels(self):
        v=self.cfg()
        v['robot_setup']['instances'][0]['self_qq']=''
        v['robot_setup']['instances'][0]['bot_name']=''
        v['robot_setup']['instances'][0]['instance_label']=''
        v['robot_setup']['groups'][0]['group_label']=''
        v['robot_setup']['group_sessions'][0]['session_label']=''
        out=validate_all(v)['robot_setup']
        self.assertEqual(out['instances'][0]['bot_name'],'bot-a')
        self.assertEqual(out['instances'][0]['instance_label'],'bot-a')
        self.assertEqual(out['groups'][0]['group_label'],'123456789')
        self.assertNotIn('session_label',out['group_sessions'][0])  # title is dynamically derived from base-table names

    def test_missing_required_platform_id_fails(self):
        v=self.cfg();v['robot_setup']['instances'][0]['platform_id']=''
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_missing_required_group_id_fails(self):
        v=self.cfg();v['robot_setup']['groups'][0]['group_id']=''
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_missing_required_session_target_fails(self):
        for target in ('platform_id','group_id'):
            with self.subTest(target=target):
                v=self.cfg();v['robot_setup']['group_sessions'][0][target]=''
                with self.assertRaises(InvalidSettings):validate_all(v)

    def test_empty_instance_wake_regex_disables_keyword(self):
        v=self.cfg()
        v['robot_setup']['instances'][0]['wake_regex']=''
        v['robot_setup']['group_sessions'][0]['use_custom_wake_regex']=False
        out=validate_all(v)
        rule=session_config(build_rules_from_setup(out['robot_setup']),'bot-a','123456789')
        self.assertFalse(has_keyword(rule,'机器人A你好'))

    def test_empty_custom_regex_disallowed_with_switch_on(self):
        v=self.cfg();v['robot_setup']['group_sessions'][0]['wake_regex']=''
        with self.assertRaises(InvalidSettings):validate_all(v)
        v['robot_setup']['group_sessions'][0]['use_custom_wake_regex']=False
        validate_all(v)

    def test_empty_roster_valid(self):
        v=self.cfg();v['robot_setup']['group_sessions'][0]['bots']=[]
        self.assertEqual(validate_all(v)['robot_setup']['group_sessions'][0]['bots'],[])

    def test_empty_group_scope_wildcard(self):
        v=self.cfg();v['robot_setup']['wake_groups']=[];v['guard_options']['gate_groups']=[]
        out=validate_all(v)
        self.assertEqual(out['robot_setup']['wake_groups'],[])
        self.assertEqual(out['guard_options']['gate_groups'],[])

    def test_blank_native_scope_row_normalizes_to_empty(self):
        v=self.cfg();v['robot_setup']['wake_groups']=[' ', ''];v['guard_options']['gate_groups']=['']
        out=validate_all(v)
        self.assertEqual(out['robot_setup']['wake_groups'],[])
        self.assertEqual(out['guard_options']['gate_groups'],[])

    def test_empty_session_list_valid_and_defaults_remain(self):
        v=self.cfg();v['robot_setup']['group_sessions']=[]
        out=validate_all(v)
        self.assertEqual(out['robot_setup']['group_sessions'],[])
        self.assertTrue(has_keyword(session_config(build_rules_from_setup(out['robot_setup']),'bot-a','123456789'),'机器人A你好'))

    def test_empty_instances_list_valid_but_no_rules(self):
        v=self.cfg();v['robot_setup']['instances']=[];v['robot_setup']['group_sessions']=[]
        out=validate_all(v)
        self.assertEqual(build_rules_from_setup(out['robot_setup']),[])

    def test_empty_groups_list_valid_with_no_sessions(self):
        v=self.cfg();v['robot_setup']['groups']=[];v['robot_setup']['group_sessions']=[]
        self.assertEqual(validate_all(v)['robot_setup']['groups'],[])

    def test_optional_provider_id_uses_current_model(self):
        v=self.cfg();v['semantic_options']['semantic_provider_id']=''
        self.assertEqual(validate_all(v)['semantic_options']['semantic_provider_id'],'')

    def test_empty_numbers_use_documented_defaults(self):
        v=self.cfg()
        defaults={'recent_count':6,'related_count':8,'recall_search_limit':5000,'max_inject_chars':2400,'max_saved_per_group':10000}
        for key in defaults:v['guard_options'][key]=''
        v['semantic_options']['semantic_timeout_seconds']=''
        out=validate_all(v)
        for key,num in defaults.items():self.assertEqual(out['guard_options'][key],num)
        self.assertEqual(out['semantic_options']['semantic_timeout_seconds'],20)

    def test_invalid_numbers_fail_instead_of_defaulting(self):
        for field in ('recent_count','related_count','recall_search_limit','max_inject_chars','max_saved_per_group'):
            v=self.cfg();v['guard_options'][field]='abc'
            with self.assertRaises(InvalidSettings):validate_all(v)
        v=self.cfg();v['semantic_options']['semantic_timeout_seconds']='nan'
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_flags_are_boolean_only(self):
        v=self.cfg();v['guard_options']['bot_guard_enabled']=''
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_extra_separator_or_too_long_alias_rejected(self):
        v=self.cfg();v['robot_setup']['group_sessions'][0]['bots']=['1000000003|机器人|'+('A'*49)]
        with self.assertRaises(InvalidSettings):validate_all(v)
        v=self.cfg();v['robot_setup']['group_sessions'][0]['bots']=['1000000003|机器人|' + ','.join(f'a{i}' for i in range(13))]
        with self.assertRaises(InvalidSettings):validate_all(v)

    def test_empty_malformed_roster_type_fails(self):
        v=self.cfg();v['robot_setup']['group_sessions'][0]['bots']=None
        with self.assertRaises(InvalidSettings):validate_all(v)


if __name__=='__main__': unittest.main()

class LegacyEmptyRegistrySafety(unittest.TestCase):
    def test_linked_empty_registry_never_restores_legacy_rules(self):
        from test_plugin import Main, EventStub, Context
        cfg=example()
        cfg['session_rules']=[{'platform_id':'bot-a','group_id':'*',
            'bot_name':'机器人A','wake_regex':'(机器人A|小A)',
            'bots':['1000000003|旧记录'], 'keyword_enabled':True}]
        cfg['robot_setup']['_linked_active']=True
        cfg['robot_setup']['instances']=[]
        cfg['robot_setup']['group_sessions']=[]
        obj=Main.PeerContextGuard(Context(), cfg)
        evt=EventStub('bot-a','123456789','1000000008','1000000001','机器人A你好')
        self.assertIsNone(obj._rule(evt))
