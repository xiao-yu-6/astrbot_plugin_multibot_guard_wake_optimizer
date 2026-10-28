"""Local review regressions missing from the supplied v0.7.6 test suite."""
import asyncio
import json
import unittest

from test_plugin import Main, Context, EventStub
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings
from astrbot_plugin_peer_context_guard.patrol import PatrolScheduler
from astrbot_plugin_peer_context_guard.semantic_judge import parse_semantic_reply, parse_participation_reply


class ReviewSettingsTest(unittest.TestCase):
    def test_multiline_personas_roundtrip(self):
        raw=example()
        raw['semantic_options']['judge_persona']='谨慎判断\r\n不打断别人'
        raw['robot_setup']['instances'][0]['semantic_persona']='擅长调试\n简短参与'
        result=validate_all(raw)
        self.assertEqual(result['semantic_options']['judge_persona'],'谨慎判断\n不打断别人')
        self.assertEqual(result['robot_setup']['instances'][0]['semantic_persona'],'擅长调试\n简短参与')

    def test_persona_control_characters_still_rejected(self):
        raw=example();raw['semantic_options']['judge_persona']='hello\0world'
        with self.assertRaises(InvalidSettings):validate_all(raw)


class ReviewParserTest(unittest.TestCase):
    def test_nested_valid_decision_cannot_rescue_invalid_outer(self):
        self.assertFalse(parse_semantic_reply('{"should_reply":"no","extra":{"should_reply":true,"target":"self"}}'))
        self.assertFalse(parse_semantic_reply('{broken: {"should_reply":true,"target":"self"}}'))
        nested={'extra':{'should_reply':True,'is_questioned':False,'is_interesting':True,
                         'reason':'helpful','addressed_to':'group'}}
        self.assertFalse(parse_participation_reply(json.dumps(nested)))

    def test_duplicate_fields_fail_closed(self):
        self.assertFalse(parse_semantic_reply('{"should_reply":false,"should_reply":true,"target":"self"}'))

    def test_invalid_field_types_never_raise(self):
        decision={'should_reply':True,'is_questioned':False,'is_interesting':True,
                  'reason':{},'addressed_to':'group'}
        self.assertFalse(parse_participation_reply(json.dumps(decision)))


class ReviewPatrolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg=validate_all(example())
        self.cfg['semantic_options'].update(semantic_enabled=True,semantic_mode='semantic_only')
        self.plugin=Main.PeerContextGuard(Context(),self.cfg)

    async def asyncTearDown(self):
        self.plugin._patrol.clear()

    async def test_early_hook_never_archives_pre_gate_human(self):
        event=EventStub('bot-a','123456789','9000000001','1000000001','private-blocked-message')
        await self.plugin.prepare_wake_flow(event)
        event.stop_event()  # A later Sender Gate rejects this human.
        await self.plugin.wake_by_regex(event)
        self.assertFalse(self.plugin._wake_flow.snapshot(('bot-a','123456789'),8))

    async def test_bare_native_prefix_bypasses_builtin_empty_shape_only(self):
        event=EventStub('bot-a','123456789','9000000001','1000000001','小A')
        event.message_str='';event.is_at_or_wake_command=True
        await self.plugin.prepare_wake_flow(event)
        self.assertEqual(len(event.get_messages()),2)
        self.assertFalse(event.is_at_or_wake_command)
        self.assertEqual(event.message_str,'小A')
        self.assertFalse(event.is_stopped())

    async def test_true_at_and_commands_are_not_rewritten_by_patrol(self):
        for event in [EventStub('bot-a','123456789','9000000001','1000000001','/help'),
                      EventStub('bot-a','123456789','9000000001','1000000001','',ats=('1000000001',))]:
            original=list(event.get_messages())
            await self.plugin.prepare_wake_flow(event)
            self.assertEqual(event.get_messages(),original)

    async def test_cancel_after_timer_grants_turn_releases_reservation(self):
        scheduler=PatrolScheduler();key=('bot-a','123456789')
        task=asyncio.create_task(scheduler.wait_for_turn(key,30))
        await asyncio.sleep(0)
        window=scheduler._windows.pop(key)
        window.task.cancel()
        scheduler._busy.add(key)
        window.future.set_result(True)
        # Reproduces cancellation after the timer reserves the group but before
        # the waiting message task resumes to run its try/finally classifier.
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertNotIn(key,scheduler._busy)
        self.assertTrue(await scheduler.wait_for_turn(key,.01))
        scheduler.finish(key,0)


if __name__=='__main__':unittest.main()
