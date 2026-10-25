"""Model picker regression tests: only configured chat models, no secrets."""
import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

# Other test module registers AstrBot stubs for isolated integration tests.
from test_plugin import fake_astrbot, Context, Main

class GoodProvider:
    def __init__(self, key, model):
        self._meta = types.SimpleNamespace(id=key, model=model)
        self.provider_config = {'api_key':'not-for-ui', 'base_url':'https://secret.example.invalid'}
    def meta(self): return self._meta

class BadProvider:
    def meta(self): raise RuntimeError('metadata failure')

class ProviderOptionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx=Context()
        self.p=Main.PeerContextGuard(self.ctx,{'robot_setup':{'enabled':False}})
        self.ctx.get_all_providers=lambda: [
          GoodProvider('demo-provider/fast-chat', 'fast-chat'),
          GoodProvider('demo-provider/local-chat', 'local-chat'),
          GoodProvider('demo-provider/local-chat', 'duplicate'),
          BadProvider(),
          GoodProvider('', 'invalid')]

    def test_only_unique_models_metadata_sorted_and_no_secrets(self):
        got=self.p._chat_provider_options()
        self.assertEqual([e['id'] for e in got],['demo-provider/fast-chat','demo-provider/local-chat'])
        self.assertIn('fast-chat',got[0]['label'])
        self.assertNotIn('api_key',str(got))
        self.assertNotIn('secret.example',str(got))

    async def test_list_endpoint(self):
        web=types.ModuleType('astrbot.api.web')
        web.json_response=lambda obj: {'status':'ok','data':obj}
        web.error_response=lambda msg,status_code: {'status':'error','message':msg,'http_status':status_code}
        with patch.dict(sys.modules,{'astrbot.api.web':web}):
            result=await self.p.web_list_chat_providers()
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['data']['providers']),2)

    async def test_list_endpoint_error_never_exposes_secrets(self):
        def fail(): raise RuntimeError('credentials=secret')
        self.ctx.get_all_providers=fail
        web=types.ModuleType('astrbot.api.web')
        web.json_response=lambda obj: obj
        web.error_response=lambda msg,status_code: {'status':'error','message':msg,'http_status':status_code}
        with patch.dict(sys.modules,{'astrbot.api.web':web}):
            res=await self.p.web_list_chat_providers()
        self.assertEqual(res['http_status'],503)
        self.assertNotIn('secret',res['message'])

    def test_frontend_defaults_and_refresh(self):
        path=Path(__file__).resolve().parents[1]/'views/settings/app.js'
        source=path.read_text('utf-8')
        self.assertIn("bridge.apiGet('models/list')",source)
        self.assertIn('跟随当前会话模型（推荐默认）',source)
        self.assertIn("case 'refresh-providers'",source)
        self.assertIn('已保存但当前不可用',source)
        self.assertNotIn("field('semantic_options.semantic_provider_id'",source)

if __name__=='__main__': unittest.main()
