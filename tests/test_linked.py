"""Offline validation and linked-config runtime tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_peer_context_guard.core import (
    build_rules_from_setup, session_config, has_keyword, explicit_local_bot_ids
)
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings


def example():
    return {
        'robot_setup': {
            'enabled': True, 'wake_enabled': True, 'wake_groups': [],
            'instances': [
                {'instance_label': '机器人A', 'platform_id': 'bot-a', 'bot_name': '机器人A', 'self_qq': '1000000001',
                 'keyword_enabled': True, 'wake_mode': 'per_group', 'wake_regex': '(机器人A|小A)'},
                {'instance_label': '机器人B', 'platform_id': 'bot-b', 'bot_name': '机器人B', 'self_qq': '1000000002',
                 'keyword_enabled': True, 'wake_mode': 'shared', 'wake_regex': '机器人B'},
            ],
            'groups': [{'group_label': '示例群A', 'group_id': '123456789'},
                       {'group_label': '示例群B', 'group_id': '234567890'}],
            'group_sessions': [{
                'session_label': '机器人A测试', 'platform_id': 'bot-a', 'group_id': '123456789',
                'keyword_enabled': True, 'use_custom_wake_regex': True,
                'wake_regex': '(A助手|机器人A)', 'block_bot_replies': True,
                'bots': ['1000000002|机器人B|小B', '1000000003|机器人C|别名C2,别名C3'],
            }]
        },
        'guard_options': {'bot_guard_enabled': True, 'gate_groups': [], 'inject_enabled': True,
                          'recent_count': 6, 'related_count': 8, 'recall_search_limit': 5000,
                          'max_inject_chars': 2400, 'max_saved_per_group': 10000, 'verbose_log': False},
        'semantic_options': {'semantic_enabled': False, 'semantic_provider_id': '', 'semantic_timeout_seconds': 20},
    }


class LinkedConfigTest(unittest.TestCase):
    def test_validated_group_and_instance_registry(self):
        result = validate_all(example())
        self.assertEqual(len(result['robot_setup']['groups']), 2)
        self.assertEqual(len(result['robot_setup']['instances']), 2)
        self.assertEqual(len(result['robot_setup']['group_sessions']), 1)

    def test_group_override_and_platform_default(self):
        s = example()['robot_setup']
        rules = build_rules_from_setup(s)
        a = session_config(rules, 'bot-a', '123456789')
        self.assertTrue(has_keyword(a, '你好，A助手'))
        self.assertFalse(has_keyword(a, '小A早上好'))
        b = session_config(rules, 'bot-a', '234567890')
        self.assertTrue(has_keyword(b, '小A早上好'))
        self.assertEqual(b['bots'], {})
        self.assertEqual(session_config(rules,'bot-b','123456789')['bot_name'], '机器人B')
        self.assertEqual(set(a['bots']), {'1000000002','1000000003'})
        self.assertEqual(explicit_local_bot_ids(s), {'1000000001','1000000002'})

    def test_shared_mode_ignores_group_regex(self):
        s=example()['robot_setup']
        s['instances'][0]['wake_mode']='shared'
        rules=build_rules_from_setup(s)
        a=session_config(rules,'bot-a','123456789')
        self.assertTrue(has_keyword(a,'小A你好'))
        self.assertFalse(has_keyword(a,'A助手你好'))

    def test_disable_specific_group_keeps_others(self):
        s=example()['robot_setup']
        s['group_sessions'][0]['keyword_enabled']=False
        rules=build_rules_from_setup(s)
        self.assertFalse(has_keyword(session_config(rules,'bot-a','123456789'),'机器人A你好'))
        self.assertTrue(has_keyword(session_config(rules,'bot-a','234567890'),'机器人A你好'))

    def test_prevent_invalid_dropdown_targets(self):
        s=example();s['robot_setup']['group_sessions'][0]['group_id']='9000000001'
        with self.assertRaises(InvalidSettings):validate_all(s)
        s=example();s['robot_setup']['group_sessions'][0]['platform_id']='qq-not-found'
        with self.assertRaises(InvalidSettings):validate_all(s)

    def test_reject_duplicate_references(self):
        s=example();s['robot_setup']['groups'].append(s['robot_setup']['groups'][0].copy())
        with self.assertRaises(InvalidSettings):validate_all(s)
        s=example();s['robot_setup']['group_sessions'].append(s['robot_setup']['group_sessions'][0].copy())
        with self.assertRaises(InvalidSettings):validate_all(s)

    def test_reject_duplicate_bot_in_a_group(self):
        s=example();s['robot_setup']['group_sessions'][0]['bots'].append('1000000002|改名|鱼')
        with self.assertRaises(InvalidSettings):validate_all(s)

    def test_fail_closed_invalid_regex(self):
        s=example();s['robot_setup']['instances'][0]['wake_regex']='.*'
        with self.assertRaises(InvalidSettings):validate_all(s)
        s=example();s['robot_setup']['group_sessions'][0]['wake_regex']='('
        with self.assertRaises(InvalidSettings):validate_all(s)

    def test_empty_scope_means_all_groups(self):
        s=validate_all(example())
        self.assertEqual(s['robot_setup']['wake_groups'],[])
        self.assertEqual(s['guard_options']['gate_groups'],[])
        s['robot_setup']['wake_groups']=['123456789']
        s['guard_options']['gate_groups']=['123456789']
        self.assertEqual(validate_all(s)['robot_setup']['wake_groups'], ['123456789'])


if __name__ == '__main__':
    unittest.main()

class LegacyMigrationTest(unittest.TestCase):
    def test_import_old_group_entries_and_wildcard_roster(self):
        from astrbot_plugin_peer_context_guard.settings import get_current_sections
        x=example()
        x['robot_setup']['_linked_active']=False
        x['robot_setup']['group_sessions']=[]
        x['session_rules']=[
            {'platform_id':'bot-a','group_id':'*','bot_name':'机器人A','wake_regex':'(机器人A|小A)',
             'bots':['1000000003|第三方机器人|阿三']},
            {'platform_id':'bot-a','group_id':'123456789','bot_name':'机器人A','wake_regex':'机器人A',
             'bots':['1000000002|机器人B|小B']},
        ]
        imported=get_current_sections(x)
        sessions=imported['robot_setup']['group_sessions']
        chosen=next(y for y in sessions if y['platform_id']=='bot-a' and y['group_id']=='123456789')
        self.assertIn('1000000003|第三方机器人|阿三',chosen['bots'])
        self.assertIn('1000000002|机器人B|小B',chosen['bots'])
        self.assertTrue(chosen['use_custom_wake_regex'])
        self.assertFalse(imported['robot_setup']['_linked_active'])
        validate_all(imported)

class NewRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_updated_configuration_changes_behavior(self):
        # test_plugin installs minimal AstrBot API mocks for offline event tests
        from test_plugin import Main, EventStub, Context
        ctx = Context()
        config = example()
        config['robot_setup']['_linked_active'] = True
        instance=Main.PeerContextGuard(ctx, config)
        event = EventStub('bot-a','123456789','9000000001','1000000001','A助手你好')
        await instance.wake_by_regex(event)
        self.assertTrue(event.is_at_or_wake_command)
        event2 = EventStub('bot-a','234567890','9000000001','1000000001','A助手你好')
        await instance.wake_by_regex(event2)
        self.assertFalse(event2.is_at_or_wake_command)
        config['robot_setup']['instances'][0]['wake_mode']='shared'
        event3 = EventStub('bot-a','123456789','9000000001','1000000001','小A你好')
        await instance.wake_by_regex(event3)
        self.assertTrue(event3.is_at_or_wake_command)
        peer=EventStub('bot-a','123456789','1000000002','1000000001','小A你好')
        self.assertTrue(instance._process_incoming(peer))
        self.assertTrue(peer.stopped)
