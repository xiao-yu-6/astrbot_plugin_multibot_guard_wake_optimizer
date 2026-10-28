"""Patrol scheduling is *not* per-message classification."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock
from test_plugin import Main, EventStub, Context
from test_linked import example
from astrbot_plugin_peer_context_guard.patrol import PatrolScheduler
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings


def yes():
    return json.dumps({"should_reply":True,"is_questioned":False,
                       "is_interesting":True,"reason":"helpful",
                       "addressed_to":"group","reply_strategy":"简短回答"})

class PatrolSchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_message_waits_for_window(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        task=asyncio.create_task(s.wait_for_turn(key,.04))
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertTrue(await task)
        s.finish(key,0)

    async def test_new_message_replaces_old_and_single_dispatch(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        a=asyncio.create_task(s.wait_for_turn(key,.05))
        await asyncio.sleep(.01)
        b=asyncio.create_task(s.wait_for_turn(key,.05))
        self.assertFalse(await a)
        self.assertTrue(await b)
        s.finish(key,0)

    async def test_window_anchor_not_extended_by_spam(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        a=asyncio.create_task(s.wait_for_turn(key,.08))
        await asyncio.sleep(.05)
        b=asyncio.create_task(s.wait_for_turn(key,.08))
        t=asyncio.get_running_loop().time()
        self.assertFalse(await a)
        self.assertTrue(await b)
        self.assertLess(asyncio.get_running_loop().time()-t,.065)
        s.finish(key,0)

    async def test_cooldown_and_group_isolation(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        self.assertTrue(await s.wait_for_turn(key,.01))
        self.assertFalse(await s.wait_for_turn(key,.01))  # singleflight
        s.finish(key,.15)
        self.assertFalse(await s.wait_for_turn(key,.01))
        self.assertTrue(await s.wait_for_turn(('bot-b','123456789'),.01))
        s.finish(('bot-b','123456789'),0)
        self.assertTrue(await s.wait_for_turn(('bot-a','234567890'),.01))
        s.finish(('bot-a','234567890'),0)

    async def test_min_messages_prevents_model_call(self):
        s=PatrolScheduler()
        self.assertFalse(await s.wait_for_turn(('bot-a','123456789'),.01,2))

    async def test_clear_unblocks_pending(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        task=asyncio.create_task(s.wait_for_turn(key,30))
        await asyncio.sleep(.01)
        s.clear()
        self.assertFalse(await task)
        self.assertEqual(s._windows,{})

    async def test_canceled_latest_no_stuck_group(self):
        s=PatrolScheduler();key=('bot-a','123456789')
        task=asyncio.create_task(s.wait_for_turn(key,30))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertNotIn(key,s._windows)
        self.assertTrue(await s.wait_for_turn(key,.01))
        s.finish(key,0)

class PatrolIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg=validate_all(example())
        self.cfg['semantic_options'].update(semantic_mode='semantic_only',patrol_interval_seconds=2,patrol_cooldown_seconds=45,patrol_min_messages=1)
        self.ctx=Context()
        self.plugin=Main.PeerContextGuard(self.ctx,self.cfg)
        self.calls=0
        async def fake_semantic(event, rule, msg, *, semantic_only=False):
            self.calls += 1
            return True
        self.plugin._semantic_yes=fake_semantic
    async def asyncTearDown(self):
        self.plugin._patrol.clear()
    def evt(self, text, mid, sender='9000000001',group='123456789'):
        return EventStub('bot-a',group,sender,'1000000001',text,message_id=mid)

    async def test_batch_one_judge_and_human_history(self):
        self.cfg['semantic_options']['patrol_interval_seconds']=2
        # Inject short timer for test, not changing config validation bounds.
        original=self.plugin._patrol.wait_for_turn
        async def fast(key, delay, min_count=1):
            return await original(key,.045,min_count)
        self.plugin._patrol.wait_for_turn=fast
        one=self.evt('我遇到Python问题','p1')
        two=self.evt('可以一起看看报错吗？','p2')
        await self.plugin.prepare_wake_flow(one)
        await self.plugin.prepare_wake_flow(two)
        a=asyncio.create_task(self.plugin.wake_by_regex(one))
        await asyncio.sleep(.01)
        b=asyncio.create_task(self.plugin.wake_by_regex(two))
        await asyncio.gather(a,b)
        self.assertFalse(one.is_wake)
        self.assertTrue(two.is_wake)
        self.assertEqual(self.calls,1)
        self.assertTrue(two.get_extra('_peer_patrol_context'))

    async def test_no_model_for_registered_bot_even_patrol_mode(self):
        e=self.evt('请回答', 'botsend', sender='1000000003')
        await self.plugin.prepare_wake_flow(e)
        await self.plugin.wake_by_regex(e)
        self.assertEqual(self.calls,0)
        self.assertFalse(e.is_wake)

    async def test_unchanged_regular_regex_no_wait(self):
        self.cfg['semantic_options']['semantic_mode']='regex_only'
        e=self.evt('机器人A你好','regex')
        await self.plugin.wake_by_regex(e)
        self.assertTrue(e.is_wake)
        self.assertEqual(self.calls,0)

class PatrolConfigTest(unittest.TestCase):
    def test_defaults_and_bounds(self):
        s=validate_all(example())['semantic_options']
        self.assertEqual((s['patrol_interval_seconds'],s['patrol_cooldown_seconds'],s['patrol_min_messages']),(15,45,1))
        for key, val in [('patrol_interval_seconds',1),('patrol_cooldown_seconds',-1),('patrol_min_messages',21)]:
            data=example();data['semantic_options'][key]=val
            with self.assertRaises(InvalidSettings):validate_all(data)

if __name__=='__main__':unittest.main()
