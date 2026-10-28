"""Focused tests of Angel Heart-inspired semantic gate; no real LLM request."""
import json
import types
import unittest

from test_plugin import Main, Context, EventStub, Provider
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings
from astrbot_plugin_peer_context_guard.semantic_judge import (
    parse_semantic_reply, build_semantic_request, SYSTEM_PROMPT,
)


class SemanticParserTest(unittest.TestCase):
    def test_structured_positive_only_for_current_target(self):
        self.assertTrue(parse_semantic_reply('{"should_reply":true,"target":"self"}'))
        self.assertTrue(parse_semantic_reply('```json\n{"should_reply":true,"target":"self"}\n```'))
        self.assertTrue(parse_semantic_reply('<think>考虑是否被叫到</think>\n{"should_reply":true,"target":"self"}'))

    def test_mentions_other_and_uncertainty_never_wake(self):
        for target in ['other','mention','unclear']:
            self.assertFalse(parse_semantic_reply(json.dumps({'should_reply':True,'target':target})))
            self.assertFalse(parse_semantic_reply(json.dumps({'should_reply':False,'target':target})))
        self.assertFalse(parse_semantic_reply('{"should_reply":false,"target":"self"}'))

    def test_invalid_output_and_prompt_echo_fail_closed(self):
        for raw in [None, '', 'Yes, the user asks about the bot',
                    'NO but yes', '```json\n{"should_reply": "true", "target": "self"}\n```',
                    '{"should_reply":1,"target":"self"}',
                    '{"should_reply":true}',
                    '{"should_reply":true,"target":"other"}',
                    'blah {"should_reply":true,"target":"self"} and {"should_reply":false,"target":"other"}',
                    '{"should_reply":true,"target":"self"}'*500]:
            self.assertFalse(parse_semantic_reply(raw), raw)
        self.assertTrue(parse_semantic_reply('YES'))  # Backward compatibility only.
        self.assertFalse(parse_semantic_reply('NO'))

    def test_payload_is_bounded_and_isolated(self):
        out = build_semantic_request(
            target_name='机器人A',matched_alias='小A',
            other_bots=[{'name':'机器人B','aliases':['小B']}],
            message='请问小A' * 500,
            recent_messages=[{'speaker':'群友','text':'测试' * 500,'role':'human'} for _ in range(30)],
        )
        data = json.loads(out)
        self.assertEqual(data['current_bot'],'机器人A')
        self.assertEqual(data['matched_wake_word'],'小A')
        self.assertEqual(data['other_bots'][0]['name'],'机器人B')
        self.assertEqual(len(data['recent_context_untrusted']),8)
        self.assertLessEqual(len(data['latest_message_untrusted']),1000)
        self.assertLessEqual(len(data['recent_context_untrusted'][0]['text']),300)
        self.assertNotIn('123456789',out)
        self.assertIn('不确定时选 unclear',SYSTEM_PROMPT)


class SemanticEndToEndOfflineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cfg=validate_all(example())
        cfg['semantic_options']['semantic_enabled']=True
        cfg['semantic_options']['semantic_mode']='regex_then_semantic'
        cfg['semantic_options']['semantic_context_count']=3
        cfg['robot_setup']['instances'][0]['wake_flow']['enabled']=False
        self.cfg=cfg
        self.ctx=Context()
        self.plugin=Main.PeerContextGuard(self.ctx,self.cfg)

    def event(self,text,group='123456789',pid='bot-a',sender='9000000001'):
        return EventStub(pid,group,sender,'1000000001',text)

    async def test_json_accept_and_reject_without_changing_native_commands(self):
        self.ctx.provider=Provider('{"should_reply":false,"target":"mention"}')
        a=self.event('我觉得A助手昨天说的不错')
        await self.plugin.wake_by_regex(a)
        self.assertFalse(a.is_at_or_wake_command)
        self.ctx.provider=Provider('{"should_reply":true,"target":"self"}')
        b=self.event('A助手，你怎么理解这句话')
        await self.plugin.wake_by_regex(b)
        self.assertTrue(b.is_at_or_wake_command)
        self.assertFalse(b.is_stopped())
        c=self.event('/help A助手')
        await self.plugin.wake_by_regex(c)
        self.assertFalse(c.is_at_or_wake_command)

    async def test_only_current_session_context_and_no_qq_numbers(self):
        # Uses a capturing spy provider rather than hardcoded YES.
        class Spy(Provider):
            def __init__(self):
                super().__init__('{"should_reply":true,"target":"self"}')
                self.calls=[]
            async def text_chat(self, **kw):
                self.calls.append(kw)
                return types.SimpleNamespace(completion_text=self.answer)
        spy=Spy()
        self.ctx.provider=spy
        # Custom follow-up flow disabled, but semantic lookback must still work.
        await self.plugin.record_wake_context(self.event('今天群友讨论了作业'))
        await self.plugin.record_wake_context(self.event('另一个群的秘密',group='234567890'))
        await self.plugin.record_wake_context(self.event('其他实例的秘密',pid='bot-b'))
        await self.plugin.wake_by_regex(self.event('A助手，你有什么看法？'))
        request=spy.calls[0]
        data=json.loads(request['prompt'])
        text=json.dumps(data,ensure_ascii=False)
        self.assertIn('今天群友讨论了作业', text)
        self.assertNotIn('另一个群的秘密', text)
        self.assertNotIn('其他实例的秘密', text)
        self.assertNotIn('9000000001', text)
        self.assertNotIn('123456789', text)
        self.assertEqual(data['matched_wake_word'], 'A助手')
        self.assertEqual(len(data['recent_context_untrusted']),1)
        self.assertIn(SYSTEM_PROMPT,request['system_prompt'])
        self.assertFalse(request['persist'])

    async def test_semantic_disabled_causes_no_extra_model_call(self):
        self.cfg['semantic_options']['semantic_enabled']=False
        self.cfg['semantic_options']['semantic_mode']='regex_only'
        await self.plugin.wake_by_regex(self.event('A助手你好'))
        self.assertEqual(self.ctx.requests,[])

    async def test_error_is_fail_closed_even_with_framework_prefix(self):
        self.ctx.provider=Provider('some answer YES or NO')
        event=self.event('A助手今天如何')
        event.is_at_or_wake_command=True
        await self.plugin.wake_by_regex(event)
        self.assertTrue(event.is_stopped())
        self.assertFalse(event.is_at_or_wake_command)

    def test_context_count_validation(self):
        raw=example();raw['semantic_options']['semantic_context_count']=0
        self.assertEqual(validate_all(raw)['semantic_options']['semantic_context_count'],0)
        raw['semantic_options']['semantic_context_count']=9
        with self.assertRaises(InvalidSettings):validate_all(raw)
        raw['semantic_options']['semantic_context_count']=''
        self.assertEqual(validate_all(raw)['semantic_options']['semantic_context_count'],4)


if __name__ == '__main__':
    unittest.main()
