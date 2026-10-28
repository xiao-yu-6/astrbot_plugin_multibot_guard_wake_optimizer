"""Regression tests: deleting linked records must persist and never resurrect."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import test_plugin  # AstrBot test stubs
from astrbot_plugin_peer_context_guard.config_storage import ManagedConfig, empty_defaults
from astrbot_plugin_peer_context_guard.settings import validate_all, get_current_sections
from astrbot_plugin_peer_context_guard.core import build_rules_from_setup, session_config, parse_roster
from test_linked import example


class DeletionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(example())

    def test_remove_bot_from_roster(self):
        self.data['robot_setup']['group_sessions'][0]['bots'].clear()
        clean = validate_all(self.data)
        self.assertEqual(clean['robot_setup']['group_sessions'][0]['bots'], [])
        found = session_config(build_rules_from_setup(clean['robot_setup']), 'bot-a','123456789')
        self.assertEqual(found['bots'], {})

    def test_remove_session_keep_group_and_instance(self):
        self.data['robot_setup']['group_sessions'].clear()
        clean=validate_all(self.data)['robot_setup']
        self.assertEqual(clean['group_sessions'], [])
        self.assertTrue(clean['instances'])
        self.assertTrue(clean['groups'])
        self.assertTrue(clean['_linked_active'])

    def test_remove_instance_cascade_and_keep_other(self):
        setup=self.data['robot_setup']
        setup['group_sessions'].append({'platform_id':'bot-b','group_id':'123456789', 'keyword_enabled':True,'block_bot_replies':True,'use_custom_wake_regex':False,'wake_regex':'','bots':[]})
        setup['instances']=[row for row in setup['instances'] if row['platform_id']!='bot-a']
        setup['group_sessions']=[row for row in setup['group_sessions'] if row['platform_id']!='bot-a']
        clean=validate_all(self.data)['robot_setup']
        self.assertEqual([x['platform_id'] for x in clean['instances']],['bot-b'])
        self.assertEqual([x['platform_id'] for x in clean['group_sessions']],['bot-b'])

    def test_remove_group_cascade_and_scope_cleanup(self):
        setup=self.data['robot_setup']
        setup['group_sessions']=[x for x in setup['group_sessions'] if x['group_id']!='123456789']
        setup['groups']=[x for x in setup['groups'] if x['group_id']!='123456789']
        setup['wake_groups']=[x for x in setup['wake_groups'] if x!='123456789']
        self.data['guard_options']['gate_groups']=[x for x in self.data['guard_options']['gate_groups'] if x!='123456789']
        clean=validate_all(self.data)
        self.assertEqual(clean['robot_setup']['group_sessions'],[])
        self.assertEqual(clean['robot_setup']['wake_groups'],[])
        self.assertEqual(clean['guard_options']['gate_groups'],[])

    def test_remove_all_instances_will_not_resurrect_legacy_rules(self):
        self.data['session_rules']=[{'platform_id':'bot-a','group_id':'*','wake_regex':'机器人A'}]
        self.data['robot_setup'].update({'_linked_active':True,'instances':[],'groups':[],'group_sessions':[]})
        clean=validate_all(self.data)
        self.assertEqual(clean['robot_setup']['instances'],[])
        self.assertEqual(build_rules_from_setup(clean['robot_setup']),[])
        self.assertNotIn('session_rules',clean)
        self.assertEqual(get_current_sections({**clean,'session_rules':self.data['session_rules']})['robot_setup']['instances'],[])


class PersistedDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_deletions_survive_new_config_instance(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            original=ManagedConfig('deletion_test',data_root=root/'data',legacy_config_root=root/'legacy')
            configured=validate_all(copy.deepcopy(example()))
            await original.save_config_async(replace_config=configured)
            first_reload=ManagedConfig('deletion_test',data_root=root/'data',legacy_config_root=root/'legacy')
            self.assertTrue(first_reload['robot_setup']['group_sessions'])
            # Removing every object and saving is a legitimate user action.
            edited=copy.deepcopy(first_reload)
            edited['robot_setup']['instances']=[]
            edited['robot_setup']['groups']=[]
            edited['robot_setup']['group_sessions']=[]
            edited['robot_setup']['wake_groups']=[]
            edited['guard_options']['gate_groups']=[]
            normalized=validate_all(edited)
            await first_reload.save_config_async(replace_config=normalized)
            second_reload=ManagedConfig('deletion_test',data_root=root/'data',legacy_config_root=root/'legacy')
            self.assertEqual(second_reload['robot_setup']['instances'],[])
            self.assertEqual(second_reload['robot_setup']['groups'],[])
            self.assertEqual(second_reload['robot_setup']['group_sessions'],[])
            self.assertTrue(second_reload['robot_setup']['_linked_active'])
            self.assertEqual(json.loads(second_reload.path.read_text(encoding='utf8'))['robot_setup']['group_sessions'],[])

    async def test_deleted_records_not_restored_by_legacy_file(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);legacy=root/'legacy';legacy.mkdir()
            preexisting=copy.deepcopy(example());preexisting['session_rules']=[{'platform_id':'bot-a','group_id':'*','wake_regex':'旧规则'}]
            legacy_file=legacy/'deletion_test_config.json'
            legacy_file.write_text(json.dumps(preexisting,ensure_ascii=False),encoding='utf8')
            cfg=ManagedConfig('deletion_test',data_root=root/'data',legacy_config_root=legacy)
            self.assertFalse(cfg['robot_setup']['enabled'])
            clean=validate_all(cfg)
            clean['robot_setup'].update({'instances':[],'groups':[],'group_sessions':[],'wake_groups':[]})
            clean['guard_options']['gate_groups']=[]
            await cfg.save_config_async(replace_config=validate_all(clean))
            again=ManagedConfig('deletion_test',data_root=root/'data',legacy_config_root=legacy)
            self.assertEqual(again['robot_setup']['instances'],[])
            self.assertNotIn('session_rules',again)
            self.assertTrue(legacy_file.exists())  # backup retained, not applied

if __name__=='__main__':unittest.main()
