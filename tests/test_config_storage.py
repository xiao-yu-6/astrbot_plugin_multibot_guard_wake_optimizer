"""Tests for no-native-schema and standalone config migration/atomic updates."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import test_plugin  # stub AstrBot modules before import of the actual plugin
from astrbot_plugin_peer_context_guard.config_storage import ManagedConfig, empty_defaults
from astrbot_plugin_peer_context_guard.settings import validate_all


class StandaloneConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_install_has_no_accidental_wake_rules(self):
        with tempfile.TemporaryDirectory() as root:
            a=ManagedConfig('peer_guard_test', data_root=Path(root)/'data',legacy_config_root=Path(root)/'legacy')
            self.assertEqual(a['robot_setup']['instances'], [])
            self.assertEqual(a['robot_setup']['group_sessions'], [])
            self.assertTrue(a['robot_setup']['_linked_active'])
            self.assertFalse(a['robot_setup']['enabled'])  # installation defaults to OFF
            self.assertFalse(a.path.exists())

    async def test_old_config_is_read_and_not_overwritten_on_upgrade(self):
        with tempfile.TemporaryDirectory() as root:
            legacy_dir=Path(root)/'legacy';legacy_dir.mkdir()
            legacy=legacy_dir/'peer_guard_test_config.json'
            former=copy.deepcopy(empty_defaults())
            former['robot_setup']['enabled']=True  # legacy plugin was enabled before upgrade
            former['robot_setup']['instances']=[{'__template_key':'instance','platform_id':'bot-a',
              'instance_label':'机器人A','bot_name':'机器人A','self_qq':'',
              'keyword_enabled':True,'wake_mode':'shared','wake_regex':'机器人A'}]
            before=json.dumps(former,ensure_ascii=False)
            legacy.write_text(before,encoding='utf-8')
            a=ManagedConfig('peer_guard_test',data_root=Path(root)/'data',legacy_config_root=legacy_dir)
            self.assertEqual(a['robot_setup']['instances'][0]['platform_id'],'bot-a')
            self.assertFalse(a['robot_setup']['enabled'])  # import never auto-activates
            self.assertFalse(a.path.exists())
            normalized=validate_all(copy.deepcopy(a))
            normalized['robot_setup']['instances'][0]['wake_regex']='(机器人A|小A)'
            self.assertTrue(await a.save_config_async(replace_config=normalized))
            self.assertEqual(legacy.read_text('utf8'),before)
            self.assertFalse(a['robot_setup']['enabled'])
            b=ManagedConfig('peer_guard_test',data_root=Path(root)/'data',legacy_config_root=legacy_dir)
            self.assertEqual(b['robot_setup']['instances'][0]['wake_regex'],'(机器人A|小A)')
            self.assertEqual(json.loads(a.path.read_text('utf8'))['robot_setup']['instances'][0]['platform_id'],'bot-a')
            self.assertFalse(list(a.store_dir.glob('.settings-*.tmp')))

    async def test_corrupt_new_config_never_silently_resets_to_old(self):
        with tempfile.TemporaryDirectory() as root:
            d=Path(root)/'data'/'peer_guard_test';d.mkdir(parents=True)
            (d/'settings.json').write_text('{BROKEN',encoding='utf8')
            ld=Path(root)/'legacy';ld.mkdir()
            (ld/'peer_guard_test_config.json').write_text(json.dumps(empty_defaults()),encoding='utf8')
            with self.assertRaises(json.JSONDecodeError):
                ManagedConfig('peer_guard_test',data_root=Path(root)/'data',legacy_config_root=ld)

    async def test_updating_config_drops_stale_legacy_keys(self):
        with tempfile.TemporaryDirectory() as root:
            d=Path(root)/'legacy';d.mkdir()
            old=copy.deepcopy(empty_defaults())
            old['session_rules']=[{'platform_id':'bot-a','group_id':'*'}]
            (d/'peer_guard_test_config.json').write_text(json.dumps(old),encoding='utf8')
            obj=ManagedConfig('peer_guard_test',data_root=Path(root)/'data',legacy_config_root=d)
            self.assertIn('session_rules',obj)
            data=validate_all(copy.deepcopy(empty_defaults()))
            await obj.save_config_async(replace_config=data)
            self.assertNotIn('session_rules',obj)
            self.assertNotIn('session_rules',json.loads(obj.path.read_text('utf8')))

    async def test_unconfigured_runtime_rule_safely_absent(self):
        with tempfile.TemporaryDirectory() as root:
            from test_plugin import Main, EventStub, Context
            c=ManagedConfig('peer_guard_test',data_root=Path(root)/'data',legacy_config_root=Path(root)/'legacy')
            plugin=Main.PeerContextGuard(Context(),c)
            evt=EventStub('bot-a','123456789','9000000001','1000000003','机器人A你好')
            self.assertIsNone(plugin._rule(evt))
            await plugin.wake_by_regex(evt)
            self.assertFalse(evt.is_at_or_wake_command)

    def test_native_schema_is_absent(self):
        plugin_root=Path(__file__).resolve().parents[1]
        self.assertFalse((plugin_root/'_conf_schema.json').exists())
        self.assertTrue((plugin_root/'views/settings/index.html').is_file())
