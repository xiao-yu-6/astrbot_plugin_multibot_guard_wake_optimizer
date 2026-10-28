"""v0.7.8 regression: large rule tables, async archival, status and wrapper lifetime."""
import asyncio
import copy
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import sys

from test_plugin import Main, Context, EventStub
from test_linked import example
from astrbot_plugin_peer_context_guard.core import SessionRuleIndex, build_rules_from_setup
from astrbot_plugin_peer_context_guard.settings import validate_all
from astrbot_plugin_peer_context_guard.archive_worker import ArchiveWriter, ArchiveRow
from astrbot_plugin_peer_context_guard.config_storage import ManagedConfig


class RuleIndexTests(unittest.TestCase):
    def test_thousand_group_sessions_are_not_truncated(self):
        data=example()
        setup=data['robot_setup']
        setup['instances']=[{'platform_id':f'bot-{i}','wake_regex':f'TOKEN{i}',
                             'bot_name':f'机器人{i}','wake_mode':'per_group',
                             'keyword_enabled':True} for i in range(5)]
        setup['groups']=[{'group_id':str(500000000+i),'group_label':f'群{i}'} for i in range(200)]
        setup['group_sessions']=[{'platform_id':f'bot-{i}','group_id':str(500000000+j),
                                  'bots':[],'use_custom_wake_regex':False} for i in range(5) for j in range(200)]
        clean=validate_all(data)
        index=SessionRuleIndex(build_rules_from_setup(clean['robot_setup']))
        self.assertEqual(len(index.rules),1005)
        self.assertEqual(index.get('bot-4', '500000199')['wake_regex'], 'TOKEN4')
        self.assertEqual(index.get('bot-0', '500000199')['wake_regex'], 'TOKEN0')
        self.assertIsNone(index.get('bot-6','500000199'))

    def test_index_exact_group_precedence(self):
        clean=validate_all(example())
        indexed=SessionRuleIndex(build_rules_from_setup(clean['robot_setup']))
        rule=indexed.get('bot-a','123456789')
        self.assertEqual(rule['wake_regex'],'(A助手|机器人A)')
        self.assertIn('1000000003',rule['bots'])
        self.assertEqual(indexed.get('bot-a','234567890')['bots'],{})


class ArchiveWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonblocking_queue_and_backpressure(self):
        class SlowStore:
            def __init__(self):self.items=[]
            def append(self,*args):time.sleep(.03);self.items.append(args);return True
        slow=SlowStore()
        writer=ArchiveWriter(slow,queue_size=1);writer.start()
        row=ArchiveRow('bot-a','123456789','1000000002','机器人B','hello','id',100)
        t=time.monotonic()
        self.assertTrue(writer.enqueue(row))
        self.assertFalse(writer.enqueue(row))
        self.assertLess(time.monotonic()-t,.02,'Ingress must not wait for SQLite')
        await writer.queue.join()
        self.assertEqual(writer.stats()['written'],1)
        self.assertEqual(writer.stats()['dropped'],1)
        await writer.close()

    async def test_archive_flush_and_reject_after_close(self):
        class Store:
            def __init__(self):self.n=0
            def append(self,*args):self.n+=1;return True
        store=Store();w=ArchiveWriter(store,4);w.start()
        row=ArchiveRow('bot-a','123456789','1000000002','B','x',None,20)
        self.assertTrue(w.enqueue(row))
        await w.close()
        self.assertEqual(store.n,1)
        self.assertFalse(w.enqueue(row))


class StatusAndLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_is_aggregated_without_identifiers(self):
        cfg=validate_all(example())
        plugin=Main.PeerContextGuard(Context(),cfg)
        from types import ModuleType
        api=ModuleType('astrbot.api.web');api.json_response=lambda o:o
        with patch.dict(sys.modules, {'astrbot.api.web':api}):
            status=await plugin.web_get_status()
        self.assertEqual(status['instances'],2)
        self.assertEqual(status['groups'],2)
        self.assertEqual(status['sessions'],1)
        self.assertEqual(status['roster_entries'],2)
        self.assertEqual(status['semantic_mode'],'regex_only')
        self.assertNotIn('1000000002',str(status))
        self.assertNotIn('123456789',str(status))

    async def test_upstream_wrapper_survives_terminate(self):
        cfg=validate_all(example());ctx=Context()
        plugin=Main.PeerContextGuard(ctx,cfg)
        with tempfile.TemporaryDirectory() as d:
            with patch.object(Main, 'get_astrbot_plugin_data_path', return_value=d):
                await plugin.initialize()
                original_wrapper=ctx.q.put_nowait
                def other_plugin_wrapper(item):return original_wrapper(item)
                ctx.q.put_nowait=other_plugin_wrapper
                await plugin.terminate()
                self.assertIs(ctx.q.put_nowait,other_plugin_wrapper)
                e=EventStub('bot-a','123456789','1000000003','1000000001','你好')
                ctx.q.put_nowait(e)
                self.assertFalse(e.stopped)
                self.assertEqual(len(ctx.q.events),1)

    async def test_managed_config_index_refresh_after_save(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=ManagedConfig('test-v078',data_root=d,legacy_config_root=d)
            clean=validate_all(example())
            await cfg.save_config_async(clean)
            plugin=Main.PeerContextGuard(Context(),cfg)
            e=EventStub('bot-a','123456789','9000000001','1000000001','hi')
            self.assertEqual(plugin._rule(e)['wake_regex'],'(A助手|机器人A)')
            clean2=copy.deepcopy(clean)
            clean2['robot_setup']['group_sessions'][0]['wake_regex']='新的群专用词'
            await cfg.save_config_async(clean2)
            plugin._refresh_rule_index()
            self.assertEqual(plugin._rule(e)['wake_regex'],'新的群专用词')


if __name__=='__main__':unittest.main()
