"""Offline unit tests: python -m unittest discover -s tests -v.
No QQ account, AstrBot server, or internet required.
"""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from astrbot_plugin_peer_context_guard.core import (
    parse_session_rules, parse_roster, session_config, has_keyword, PeerStore)


def fake_astrbot():
    def mk(name, parent=False):
        m = types.ModuleType(name)
        if parent:
            m.__path__ = []
        sys.modules[name] = m
        return m
    api = mk("astrbot", True)
    mod = mk("astrbot.api", True)
    events = mk("astrbot.api.event")
    provider = mk("astrbot.api.provider")
    stars = mk("astrbot.api.star")
    comps = mk("astrbot.api.message_components")
    mk("astrbot.core", True)
    mk("astrbot.core.agent", True)
    messages = mk("astrbot.core.agent.message")
    mk("astrbot.core.utils", True)
    paths = mk("astrbot.core.utils.astrbot_path")
    mk("astrbot.core.star", True)
    mk("astrbot.core.star.filter", True)
    commands = mk("astrbot.core.star.filter.command")
    groups = mk("astrbot.core.star.filter.command_group")
    commands.CommandFilter = type("CommandFilter", (), {})
    groups.CommandGroupFilter = type("CommandGroupFilter", (), {})

    class Log:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
    mod.logger = Log()
    mod.AstrBotConfig = dict
    class Event: pass
    events.AstrMessageEvent = Event
    class Filter:
        class EventMessageType:
            GROUP_MESSAGE = 1
        @staticmethod
        def event_message_type(*args, **kwargs): return lambda f: f
        @staticmethod
        def on_llm_request(*args, **kwargs): return lambda f: f
        @staticmethod
        def after_message_sent(*args, **kwargs): return lambda f: f
    events.filter = Filter
    class ProviderRequest:
        def __init__(self): self.extra_user_content_parts = []
    provider.ProviderRequest = ProviderRequest
    class Star:
        def __init__(self, ctx, config=None): self.context = ctx
    stars.Context = object
    stars.Star = Star
    class Plain:
        def __init__(self, text): self.text=text
    class At:
        def __init__(self, qq): self.qq=qq
    comps.Plain = Plain
    comps.At = At
    class TextPart:
        def __init__(self, text): self.text=text; self.temp=False
        def mark_as_temp(self): self.temp=True; return self
    messages.TextPart=TextPart
    paths.get_astrbot_plugin_data_path=lambda: tempfile.gettempdir()
    paths.get_astrbot_config_path=lambda: tempfile.gettempdir()
    return Event, Plain, At, ProviderRequest


class CoreTest(unittest.TestCase):
    def test_roster_ids_names_aliases(self):
        roster=parse_roster(["1000000003|机器人C|别名C1,伍", "abc|Fake", "1000000003|机器人C", "1000000004|机器人B|别名B1"])
        self.assertEqual(roster["1000000003"]["name"], "机器人C")
        self.assertEqual(roster["1000000003"]["aliases"], ["别名C1","伍"])
        self.assertEqual(len(roster),2)

    def test_sessions_exact_and_all(self):
        raw=[{"platform_id":"bot-a", "group_id":"*", "bot_name":"机器人A", "wake_regex":"机器人A", "bots":["1000000003|机器人B|小B"]},
             {"platform_id":"bot-a", "group_id":"123456789", "bot_name":"机器人A测试", "wake_regex":"(机器人A|小A)", "bots":["1000000003|别名B2|机器人B", "1000000005|机器人C"]},
             {"platform_id":"bot-b", "group_id":"*", "bot_name":"机器人B", "wake_regex":"机器人B"}]
        rules=parse_session_rules(raw)
        a=session_config(rules,"bot-a","123456789")
        self.assertEqual(a["bots"]["1000000003"]["name"], "别名B2")
        self.assertTrue(has_keyword(a, "你好小A呀"))
        self.assertFalse(has_keyword(a,"机器人B你好"))
        self.assertEqual(session_config(rules,"bot-a","234567890")["bots"]["1000000003"]["name"],"机器人B")
        self.assertEqual(session_config(rules,"bot-b","123456789")["bot_name"],"机器人B")
        self.assertIsNone(session_config(rules,"qq-c","123456789"))

    def test_invalid_regex_and_empty_pattern(self):
        invalid=parse_session_rules([{"platform_id":"bot-a", "group_id":"*", "wake_regex":"("}])
        self.assertFalse(has_keyword(invalid[0],"anything"))
        empty=parse_session_rules([{"platform_id":"bot-a", "group_id":"*", "wake_regex":".*"}])
        self.assertFalse(has_keyword(empty[0], "HELLO"))

    def test_sqlite_save_dedup_scope_and_recall_alias(self):
        with tempfile.TemporaryDirectory() as d:
            store=PeerStore(Path(d)/"history.sqlite3")
            store.append("bot-a","123456789","1000000003","原名","我是机器人C，说过天气晴朗", "msg-1")
            store.append("bot-a","123456789","1000000003","原名","我是机器人C，说过天气晴朗", "msg-1")
            store.append("bot-b","123456789","1000000003","原名","另一机器人平台的历史", "msg-2")
            self.assertEqual(store.count("bot-a","123456789"),1)
            self.assertEqual(store.count("bot-a","234567890"),0)
            rows=store.recall("bot-a","123456789","请问别名C1以前说过什么",bot_directory=parse_roster(["1000000003|机器人C|别名C1"]))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["sender"], "机器人C")
            store.close()


Event, Plain, At, Request = fake_astrbot()
Main = importlib.import_module('astrbot_plugin_peer_context_guard.main')

class EventStub(Event):
    def __init__(self, instance, group, sender, self_id, msg, message_id='m-1', ats=()):
        self.instance=instance;self.group=group;self.sender=sender;self.self_id=self_id
        self.message_str=msg;self._parts=[Plain(msg)]+[At(a) for a in ats]
        self.stopped=False;self.is_at_or_wake_command=False;self.is_wake=False
        self.unified_msg_origin=f'{instance}:GroupMessage:{group}'
        self._extra = {}
        self._result = None
        self.message_obj=types.SimpleNamespace(message_id=message_id,
               message=self._parts,
               raw_message={"message": [{"type":"at","data":{"qq":qq}} for qq in ats]})
    def get_platform_name(self): return 'aiocqhttp'
    def get_platform_id(self): return self.instance
    def get_group_id(self): return self.group
    def get_self_id(self): return self.self_id
    def get_sender_id(self): return self.sender
    def get_sender_name(self): return '真实昵称'
    def get_messages(self): return self.message_obj.message
    def get_extra(self, key, default=None): return self._extra.get(key, default)
    def set_extra(self, key, value): self._extra[key]=value
    def get_result(self): return self._result
    def stop_event(self): self.stopped=True
    def is_stopped(self): return self.stopped

class Queue:
    def __init__(self): self.events=[]
    def put_nowait(self,item): self.events.append(item)

class Provider:
    def __init__(self, answer): self.answer=answer
    async def text_chat(self, **kw): return types.SimpleNamespace(completion_text=self.answer)

class Context:
    def __init__(self): self.q=Queue();self.provider=Provider('YES');self.requests=[]
    def get_event_queue(self): return self.q
    async def get_using_provider_async(self, umo): self.requests.append(umo);return self.provider
    def get_provider_by_id(self, provider_id): return self.provider
    def get_config(self, umo=None): return {"wake_prefix": ["/", "机器人A", "小A", "机器人B"]}


class MainTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ctx=Context()
        self.cfg={"enabled":True,"bot_guard_enabled":True,"wake_enabled":True,
                  "wake_groups":[],"gate_groups":[],"inject_enabled":True,
                  "session_rules":[
                    {"__template_key":"session","platform_id":"bot-a","group_id":"*","bot_name":"机器人A","wake_regex":"(机器人A|小A)","block_bot_replies":True,"bots":["1000000003|机器人B|小B","1000000007|其他机器人|机器人C"]},
                    {"__template_key":"session","platform_id":"bot-b","group_id":"*","bot_name":"机器人B","wake_regex":"机器人B","block_bot_replies":True,"bots":["1000000006|机器人A|小A","1000000007|其他机器人|机器人C"]}],
                  "semantic_enabled":False}
        self.plugin=Main.PeerContextGuard(self.ctx,self.cfg)
        self.plugin.store=PeerStore(Path(self.temp.name)/'peer.sqlite3')
    def tearDown(self):
        self.plugin.store.close();self.temp.cleanup()

    def test_empty_group_filters_are_all(self):
        self.assertTrue(self.plugin._in_scope([],"123456789"))
        self.assertTrue(self.plugin._in_scope([],"234567890"))
        self.assertFalse(self.plugin._in_scope(["123456789"],"234567890"))

    def test_robot_dropped_at_queue_then_archived(self):
        evt=EventStub('bot-a','123456789','1000000003','1000000006','机器人A你怎么看')
        self.assertTrue(self.plugin._process_incoming(evt))
        self.assertTrue(evt.stopped)
        self.assertEqual(self.plugin.store.count('bot-a','123456789'),1)
        self.assertEqual(self.plugin.store.count('bot-a','234567890'),0)

    def test_third_party_robot_is_also_blocked(self):
        evt=EventStub('bot-b','123456789','1000000007','1000000003','机器人B，快出来')
        self.assertTrue(self.plugin._process_incoming(evt))

    def test_human_allowed_and_self_known(self):
        evt=EventStub('bot-a','123456789','9000000001','1000000006','机器人A你好')
        self.assertFalse(self.plugin._process_incoming(evt))
        self.assertFalse(evt.stopped)

    def test_disable_guard_for_one_session(self):
        self.cfg['session_rules'][0]['block_bot_replies']=False
        evt=EventStub('bot-a','123456789','1000000003','1000000006','机器人A你好')
        self.assertFalse(self.plugin._process_incoming(evt))
        self.assertFalse(evt.stopped)
        self.assertEqual(self.plugin.store.count('bot-a','123456789'),0)
        evt2=EventStub('bot-b','123456789','1000000006','1000000003','机器人B你好')
        # bot-b still separately protected
        self.assertTrue(self.plugin._process_incoming(evt2))

    async def test_wake_by_regex_each_instance(self):
        a=EventStub('bot-a','123456789','9000000001','1000000006','有人知道机器人A在吗')
        await self.plugin.wake_by_regex(a)
        self.assertTrue(a.is_at_or_wake_command)
        b=EventStub('bot-b','123456789','9000000001','1000000003','有人知道机器人A在吗')
        await self.plugin.wake_by_regex(b)
        self.assertFalse(b.is_at_or_wake_command)
        c=EventStub('bot-b','234567890','9000000001','1000000003','你好机器人B')
        await self.plugin.wake_by_regex(c)
        self.assertTrue(c.is_at_or_wake_command)

    async def test_wake_whitelist_and_non_matching(self):
        self.cfg['wake_groups']=['123456789']
        e=EventStub('bot-a','234567890','9000000001','1000000006','机器人A你好')
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_at_or_wake_command)
        f=EventStub('bot-a','123456789','9000000001','1000000006','天气真好')
        await self.plugin.wake_by_regex(f)
        self.assertFalse(f.is_at_or_wake_command)

    async def test_command_and_other_at_are_not_reinterpreted(self):
        command=EventStub('bot-a','123456789','9000000001','1000000006','/help 机器人A')
        await self.plugin.wake_by_regex(command)
        self.assertFalse(command.is_at_or_wake_command)
        at_other=EventStub('bot-a','123456789','9000000001','1000000006','机器人A',ats=['1000000007'])
        await self.plugin.wake_by_regex(at_other)
        self.assertFalse(at_other.is_at_or_wake_command)

    async def test_semantic_no_and_yes_default_session_provider(self):
        self.cfg['semantic_enabled']=True
        self.ctx.provider.answer='NO'
        a=EventStub('bot-a','123456789','9000000001','1000000006','机器人A说的挺好')
        await self.plugin.wake_by_regex(a)
        self.assertFalse(a.is_at_or_wake_command)
        a.is_at_or_wake_command=True
        await self.plugin.wake_by_regex(a)
        self.assertTrue(a.stopped)
        self.ctx.provider.answer='YES'
        b=EventStub('bot-a','123456789','9000000001','1000000006','机器人A你好')
        await self.plugin.wake_by_regex(b)
        self.assertTrue(b.is_at_or_wake_command)
        self.assertIn('bot-a:GroupMessage:123456789',self.ctx.requests)

    async def test_history_injection_readonly_and_current_group_only(self):
        bot=EventStub('bot-a','123456789','1000000003','1000000006','我觉得蓝色很好看')
        self.plugin._process_incoming(bot)
        human=EventStub('bot-a','123456789','9000000001','1000000006','机器人A，机器人B刚刚说了什么')
        req=Request()
        await self.plugin.inject_peer_history(human,req)
        self.assertEqual(len(req.extra_user_content_parts),1)
        part=req.extra_user_content_parts[0]
        self.assertTrue(part.temp)
        self.assertIn('我觉得蓝色很好看',part.text)
        self.assertIn('机器人B',part.text)
        other_group=EventStub('bot-a','234567890','9000000001','1000000006','机器人A，别名B2说了什么')
        otherreq=Request()
        await self.plugin.inject_peer_history(other_group,otherreq)
        self.assertNotIn('我觉得蓝色很好看', ''.join(p.text for p in otherreq.extra_user_content_parts))

    async def test_queue_wrapper_and_terminate_restore_original(self):
        old_store=self.plugin.store
        self.plugin.store=None
        old_store.close()
        from unittest.mock import patch as patch_obj
        with patch_obj.object(Main, "get_astrbot_plugin_data_path", return_value=self.temp.name):
            await self.plugin.initialize()
            human=EventStub('bot-a','123456789','9000000001','1000000006','你好')
            bot=EventStub('bot-a','123456789','1000000003','1000000006','机器人A你好')
            self.ctx.q.put_nowait(human)
            self.ctx.q.put_nowait(bot)
            self.assertEqual(len(self.ctx.q.events), 1)
            self.assertTrue(bot.stopped)
            self.assertEqual(self.plugin.store.count('bot-a','123456789'), 1)
            await self.plugin.terminate()
            self.assertNotIn('put_nowait', vars(self.ctx.q))
            self.ctx.q.put_nowait(bot)
            self.assertEqual(len(self.ctx.q.events), 2)
        self.plugin.store=PeerStore(Path(self.temp.name)/'tear_down.sqlite3')

    async def test_secondary_guard_blocks_robot_even_if_queue_bypassed(self):
        bot=EventStub('bot-a','123456789','1000000003','1000000006','机器人A')
        req=Request()
        await self.plugin.secondary_pre_llm_guard(bot,req)
        self.assertTrue(bot.stopped)


if __name__ == '__main__': unittest.main()
