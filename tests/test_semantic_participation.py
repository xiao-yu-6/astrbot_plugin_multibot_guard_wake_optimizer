"""Additional offline tests for optional Angel Heart-like participation mode."""
import json
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
import tempfile
from test_plugin import Main, EventStub, Context, Provider
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all
from astrbot_plugin_peer_context_guard.core import PeerStore
from astrbot_plugin_peer_context_guard.semantic_judge import (
    parse_participation_reply, parse_semantic_reply, build_semantic_request,
    PARTICIPATION_SYSTEM_PROMPT, SYSTEM_PROMPT, semantic_mode)


def decision(reason='none', addressed_to='unclear', should_reply=False,
             questioned=False, interesting=False):
    return json.dumps({'should_reply': should_reply, 'reason': reason,
                       'is_questioned':questioned, 'is_interesting':interesting,
                       'addressed_to':addressed_to, 'reply_strategy':'简短回复'},ensure_ascii=False)


class ParticipationDecisionTest(unittest.TestCase):
    def test_direct_and_followup_positive(self):
        for r in ('direct','followup'):
            self.assertTrue(parse_participation_reply(decision(r,'self',True,True,False)))

    def test_helpful_group_question_without_name_positive(self):
        self.assertTrue(parse_participation_reply(decision('helpful','group',True,False,True)))

    def test_only_name_mentioned_not_causal(self):
        self.assertFalse(parse_participation_reply(decision('none','unclear',False,False,False)))
        self.assertFalse(parse_participation_reply(decision('helpful','other',True,False,True)))

    def test_invalid_bool_and_inconsistent_rejected(self):
        examples=[
            '{"should_reply":"true","reason":"helpful","is_questioned":false,"is_interesting":true,"addressed_to":"group"}',
            decision('helpful','group',True,False,False),
            decision('direct','self',True,False,True),
            decision('none','group',True,True,True),
            decision('none','unclear',False,False,True),
            'YES','NO','', '{"should_reply":true}',
            decision('helpful','group',True,False,True)+decision('none','unclear'),
        ]
        for text in examples:self.assertFalse(parse_participation_reply(text),text)

    def test_structured_with_fences_accepted(self):
        self.assertTrue(parse_participation_reply('```json\n'+decision('helpful','group',True,False,True)+'\n```'))

    def test_receiver_mode_unchanged(self):
        self.assertTrue(parse_semantic_reply('{"should_reply":true,"target":"self"}'))
        self.assertFalse(parse_semantic_reply(decision('helpful','group',True,False,True)))

    def test_mode_migration_from_boolean(self):
        self.assertEqual(semantic_mode({'semantic_enabled':True}),'regex_then_semantic')
        self.assertEqual(semantic_mode({'semantic_enabled':False}),'regex_only')

    def test_prompt_bounds_and_distinct_task(self):
        s=build_semantic_request(target_name='机器人A',matched_alias='',other_bots=[{'name':'机器人B','aliases':[]}],
               message='群聊求助' *500,recent_messages=[{'speaker':'群友','text':'历史'*400} for _ in range(30)],
               semantic_only=True,bot_persona='懂Python' *300,
               peer_messages=[{'sender':'机器人B','text':'我建议先运行测试'}])
        p=json.loads(s)
        self.assertEqual(p['judgement_mode'],'patrol_participation')
        self.assertIn('懂Python',p['current_bot_persona'])
        self.assertEqual(p['peer_context_untrusted'][0]['role'],'peer_bot')
        self.assertLessEqual(len(p['latest_message_untrusted']),1000)
        self.assertLessEqual(len(p['current_bot_persona']),1200)
        self.assertEqual(len(p['recent_context_untrusted']),8)
        self.assertIn('有具体信息增益',PARTICIPATION_SYSTEM_PROMPT)
        self.assertIn('不确定时选 unclear',SYSTEM_PROMPT)

class ParticipationRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg=validate_all(example())
        self.cfg['semantic_options']['semantic_mode']='semantic_only'
        self.cfg['semantic_options']['judge_persona']='保持简洁，少抢话'
        self.cfg['robot_setup']['instances'][0]['semantic_persona']='耐心的Python编程助手'
        self.ctx=Context()
        self.plugin=Main.PeerContextGuard(self.ctx,self.cfg)
        # These pre-existing tests isolate LLM policy and guards, not the timer.
        self.plugin._patrol.wait_for_turn = AsyncMock(return_value=True)
    def event(self, text='这段Python代码怎么修？',sender='9000000001',group='123456789',ats=()):
        return EventStub('bot-a',group,sender,'1000000001',text,ats=ats)
    async def test_no_regex_helpful_participation_and_persona(self):
        class Spy(Provider):
            def __init__(self):
                super().__init__(decision('helpful','group',True,False,True));self.calls=[]
            async def text_chat(self,**kw):
                self.calls.append(kw);return types.SimpleNamespace(completion_text=self.answer)
        spy=Spy();self.ctx.provider=spy
        e=self.event()
        await self.plugin.wake_by_regex(e)
        self.assertTrue(e.is_at_or_wake_command)
        self.assertTrue(e.is_wake)
        self.assertEqual(len(spy.calls),1)
        q=json.loads(spy.calls[0]['prompt'])
        self.assertEqual(q['judgement_mode'],'patrol_participation')
        self.assertIn('耐心的Python编程助手', q['current_bot_persona'])
        self.assertIn('保持简洁，少抢话',spy.calls[0]['system_prompt'])
        self.assertIn(PARTICIPATION_SYSTEM_PROMPT,spy.calls[0]['system_prompt'])
        self.assertNotIn('123456789',spy.calls[0]['prompt'])
        self.assertFalse(spy.calls[0]['persist'])
    async def test_no_reply_on_ordinary_chat(self):
        self.ctx.provider=Provider(decision('none','unclear'))
        e=self.event('今天吃啥？')
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_wake)
    async def test_human_speaks_to_other_robot_is_not_judged(self):
        e=self.event('机器人B，你来回答',ats=('1000000002',))
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_wake)
        self.assertEqual(self.ctx.requests,[])
    async def test_other_bot_sender_dropped_before_semantic(self):
        self.ctx.provider=Provider(decision('helpful','group',True,False,True))
        e=self.event(sender='1000000002')
        self.assertTrue(self.plugin._guard_applies(e,self.plugin._rule(e)))
        self.assertTrue(self.plugin._process_incoming(e))
        self.assertTrue(e.is_stopped())
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_wake)
        self.assertEqual(self.ctx.requests,[])
    async def test_bad_response_fails_closed(self):
        self.ctx.provider=Provider('YES')
        e=self.event()
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_wake)
    async def test_regex_review_never_proactively_answers(self):
        self.cfg['semantic_options']['semantic_mode']='regex_then_semantic'
        self.ctx.provider=Provider(decision('helpful','group',True,False,True))
        e=self.event()
        await self.plugin.wake_by_regex(e)
        self.assertFalse(e.is_wake)
        self.assertEqual(self.ctx.requests,[])
    async def test_no_followup_bypass_on_rejected_participation(self):
        self.cfg['robot_setup']['instances'][0]['wake_flow']={'enabled':True,'empty_action':'original',
                  'followup_enabled':True,'context_count':6,'context_max_chars':4000,'wait_seconds':60}
        self.ctx.provider=Provider(decision('none','unclear'))
        e=self.event()
        self.plugin._wake_flow.arm(self.plugin._flow_key(e),60,self.plugin._wake_flow.begin(self.plugin._flow_key(e)))
        await self.plugin.prepare_wake_flow(e)
        self.assertFalse(e.is_wake)
        self.assertFalse(e.is_at_or_wake_command)
    async def test_peer_history_scoped_and_bot_ids_not_transmitted(self):
        self.cfg['semantic_options']['semantic_context_count']=3
        with tempfile.TemporaryDirectory() as d:
            self.plugin.store=PeerStore(Path(d)/'p.sqlite')
            self.plugin.store.append('bot-a','123456789','1000000003','机器人C','我有提议', 'm-1')
            self.plugin.store.append('bot-a','234567890','1000000003','机器人C','别的群秘密', 'm-2')
            class Spy(Provider):
                def __init__(self):super().__init__(decision('helpful','group',True,False,True));self.calls=[]
                async def text_chat(self,**kw):self.calls.append(kw);return types.SimpleNamespace(completion_text=self.answer)
            self.ctx.provider=spy=Spy()
            await self.plugin.wake_by_regex(self.event())
            p=spy.calls[0]['prompt']
            self.assertIn('我有提议',p)
            self.assertNotIn('别的群秘密',p)
            self.assertNotIn('1000000003',p)
            self.plugin.store.close();self.plugin.store=None

if __name__ == '__main__':unittest.main()
