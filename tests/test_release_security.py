"""Regression checks for released artifact security/privacy properties."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from test_plugin import Main, EventStub, Context, Request
from test_linked import example
from astrbot_plugin_peer_context_guard.core import (
    PeerStore, has_keyword, parse_session_rules,
)
from astrbot_plugin_peer_context_guard.settings import validate_all
from astrbot_plugin_peer_context_guard.config_storage import ManagedConfig

class RegexSecurityTest(unittest.TestCase):
    def test_pathological_nested_quantifier_is_bounded(self):
        # This hangs stdlib re on some machines, but regex times out.
        rules=parse_session_rules([{'platform_id':'bot-a','group_id':'*','wake_regex':'(a+)+$'}])
        now=time.monotonic()
        self.assertFalse(has_keyword(rules[0], 'a'*600+'!'))
        self.assertLess(time.monotonic()-now,1.0)

    def test_normal_chinese_regex_still_matches(self):
        rules=parse_session_rules([{'platform_id':'bot-a','group_id':'*','wake_regex':'(机器人A|小A)'}])
        self.assertTrue(has_keyword(rules[0], '我想问一下小A这个问题'))

class PeerHistoryPrivacyTest(unittest.TestCase):
    def test_removed_peer_no_longer_in_model_history(self):
        with tempfile.TemporaryDirectory() as temp:
            store=PeerStore(Path(temp)/'peers.sqlite3')
            store.append('bot-a','123456789','1000000003','机器人C','机器人C透露的历史内容','note-1')
            self.assertTrue(store.recall('bot-a','123456789','机器人C',bot_directory={
                '1000000003':{'name':'机器人C','aliases':[]} }))
            self.assertFalse(store.recall('bot-a','123456789','机器人C',bot_directory={}))
            self.assertFalse(store.recall('bot-a','123456789','机器人C',bot_directory={
                '1000000002':{'name':'机器人B','aliases':[]} }))
            # Explicit deletion from UI does not secretly purge history storage.
            self.assertEqual(store.count('bot-a','123456789'),1)
            if os.name=='posix':
                self.assertEqual(os.stat(Path(temp)/'peers.sqlite3').st_mode & 0o777,0o600)
            store.close()

class ModelPrivacyTest(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_prompt_does_not_include_directory_numeric_ids(self):
        config=validate_all(example())
        config['semantic_options']['semantic_enabled']=True
        config['semantic_options']['semantic_mode']='regex_then_semantic'
        ctx=Context()
        captured=[]
        class CapturingProvider:
            async def text_chat(self, **kwargs):
                captured.append(kwargs['prompt'])
                return type('Resp', (), {'completion_text':'YES'})()
        ctx.provider=CapturingProvider()
        plugin=Main.PeerContextGuard(ctx,config)
        event=EventStub('bot-a','123456789','9000000001','1000000001','机器人A你觉得呢')
        self.assertTrue(await plugin._semantic_yes(event,plugin._rule(event),'机器人A你觉得呢'))
        prompt=captured[0]
        for secret_id in ('123456789','1000000001','1000000002','1000000003','bot-a'):
            self.assertNotIn(secret_id,prompt)

    async def test_llm_history_injection_does_not_emit_numeric_identity_metadata(self):
        config=validate_all(example())
        ctx=Context()
        plugin=Main.PeerContextGuard(ctx,config)
        with tempfile.TemporaryDirectory() as temp:
            plugin.store=PeerStore(Path(temp)/'history.sqlite3')
            plugin.store.append('bot-a','123456789','1000000003','机器人C','今天我说了天气很好','msg-1')
            event=EventStub('bot-a','123456789','9000000001','1000000001','请问机器人C说过什么')
            request=Request()
            await plugin.inject_peer_history(event,request)
            self.assertEqual(len(request.extra_user_content_parts),1)
            message=request.extra_user_content_parts[0].text
            self.assertIn('今天我说了天气很好',message)
            for secret_id in ('123456789','1000000001','1000000002','1000000003','bot-a'):
                self.assertNotIn(secret_id,message)
            plugin.store.close()

class FilesystemProtectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_saved_settings_are_private_on_posix(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=ManagedConfig('audit-test',data_root=Path(temp),legacy_config_root=Path(temp)/'legacy')
            await cfg.save_config_async(replace_config=validate_all(cfg))
            if os.name=='posix':
                self.assertEqual(os.stat(cfg.path).st_mode & 0o777,0o600)
                self.assertEqual(os.stat(cfg.store_dir).st_mode & 0o777,0o700)

if __name__=='__main__':
    unittest.main()
