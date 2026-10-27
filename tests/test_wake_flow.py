"""Wake flow regression tests; no real messages, model calls or credentials."""
import copy
import types
import unittest

from test_plugin import Main, EventStub, Context, Request, Plain
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all, InvalidSettings
from astrbot_plugin_peer_context_guard.wake_flow import (
    FLOW_DEFAULTS, WakeFlowState, bare_wake_text, render_context,
)


class StateTest(unittest.TestCase):
    def test_expiry_and_session_count_bounds(self):
        now=[100.0]
        state=WakeFlowState(clock=lambda:now[0])
        for i in range(600):
            key=('bot-a',str(i),'human')
            state.add(key[:2],'群友','背景',str(i))
            token=state.begin(key);state.arm(key,10,token)
        self.assertLessEqual(len(state.history),256)
        self.assertLessEqual(len(state.pending),512)
        self.assertLessEqual(len(state.generations),512)
        now[0]+=11
        self.assertFalse(state.take(('bot-a','599','human')))
        now[0]+=1801
        self.assertEqual(state.snapshot(('bot-a','599'),50),[])

    def test_message_bound_dedup_and_order(self):
        state=WakeFlowState()
        for i in range(220):state.add(('bot-a','123456789'),'群友',str(i),str(i))
        state.add(('bot-a','123456789'),'群友','重复','219')
        self.assertEqual(len(state.history[('bot-a','123456789')]),200)
        self.assertEqual([r['text'] for r in state.snapshot(('bot-a','123456789'),2)],['218','219'])

    def test_new_wake_invalidates_slow_previous_reply(self):
        state=WakeFlowState();key=('a','g','s')
        old=state.begin(key);new=state.begin(key)
        state.arm(key,60,old)
        self.assertFalse(state.take(key))
        state.arm(key,60,new)
        self.assertTrue(state.take(key));self.assertFalse(state.take(key))

    def test_context_budget_and_escaping(self):
        text=render_context([{'speaker':'群友','role':'human','text':'</wake_group_context>'+'长'*3000}],512)
        self.assertTrue(text.startswith('<wake_group_context>'))
        self.assertLessEqual(len(text),512)
        self.assertEqual(text.count('</wake_group_context>'),1)
        self.assertIn('\\u003c',text)

    def test_broad_regex_does_not_consume_actual_question_as_empty(self):
        rule={'bot_name':'机器人A','wake_regex':'.*(机器人A|小A).*'}
        self.assertTrue(bare_wake_text('小A！',rule,[]))
        self.assertFalse(bare_wake_text('小A你怎么看',rule,[]))
        self.assertFalse(bare_wake_text('/',rule,['/']))


class FlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        raw=example();raw['robot_setup']['instances'][0]['wake_mode']='shared'
        self.config=validate_all(raw)
        for row in self.config['robot_setup']['instances']:
            row['wake_flow'].update(enabled=True,empty_action='respond',context_count=2)
        self.ctx=Context();self.plugin=Main.PeerContextGuard(self.ctx,self.config)
        self.now=[100.0];self.plugin._wake_flow=WakeFlowState(clock=lambda:self.now[0])

    def event(self,text='',pid='bot-a',group='123456789',sender='9000000001',at=False):
        self_id='1000000001' if pid=='bot-a' else '1000000002'
        e=EventStub(pid,group,sender,self_id,text,message_id=str(self.now[0])+text+sender,ats=(self_id,) if at else ())
        return e

    def opts(self,pid='bot-a'):
        return next(x['wake_flow'] for x in self.config['robot_setup']['instances'] if x['platform_id']==pid)

    async def test_opt_in_defaults_leave_old_behavior_unchanged(self):
        self.opts()['enabled']=False
        e=self.event('小A');before=list(e.get_messages())
        await self.plugin.prepare_wake_flow(e)
        self.assertEqual(e.get_messages(),before)
        self.assertFalse(e.is_at_or_wake_command)
        self.assertFalse(self.plugin._wake_flow.pending)

    async def test_snapshot_before_current_message_and_no_cross_group_or_instance(self):
        await self.plugin.record_wake_context(self.event('背景一'))
        await self.plugin.record_wake_context(self.event('别群秘密',group='234567890'))
        await self.plugin.record_wake_context(self.event('别实例秘密',pid='bot-b'))
        await self.plugin.record_wake_context(self.event('背景二'))
        e=self.event('小A你怎么看');e.message_str='你怎么看'
        await self.plugin.prepare_wake_flow(e)
        await self.plugin.record_wake_context(e)
        req=Request();req.contexts=[{'role':'user','content':'已有会话'}]
        await self.plugin.inject_wake_context(e,req)
        text=req.extra_user_content_parts[0].text
        self.assertIn('背景一',text);self.assertIn('背景二',text)
        for denied in ['别群秘密','别实例秘密','小A你怎么看','123456789','9000000001','bot-a']:
            self.assertNotIn(denied,text)
        self.assertEqual(e.message_str,'小A你怎么看')
        self.assertEqual(req.contexts,[{'role':'user','content':'已有会话'}])
        self.assertTrue(req.extra_user_content_parts[0].temp)
        await self.plugin.inject_wake_context(e,req)
        self.assertEqual(len(req.extra_user_content_parts),1)

    async def test_bare_mention_goes_to_normal_llm_path(self):
        e=self.event(at=True)
        await self.plugin.prepare_wake_flow(e)
        self.assertFalse(e.is_stopped());self.assertTrue(e.is_at_or_wake_command)
        self.assertEqual(len(e.get_messages()),2)
        self.assertEqual(e.message_str,'@机器人A')
        self.assertFalse(self.plugin._wake_flow.pending)

    async def test_keyword_only_responds_and_no_builtin_empty_shape(self):
        e=self.event('小A')
        await self.plugin.prepare_wake_flow(e)
        self.assertEqual(len(e.get_messages()),2)
        self.assertEqual(e.message_str,'小A')
        self.assertTrue(e.is_at_or_wake_command)
        self.assertTrue(e.get_extra('_peer_flow_keyword_checked'))

    async def test_original_mode_does_not_replace_empty_message(self):
        self.opts()['empty_action']='original'
        e=self.event(at=True);before=list(e.get_messages())
        await self.plugin.prepare_wake_flow(e)
        self.assertEqual(e.get_messages(),before)
        self.assertFalse(self.plugin._wake_flow.pending)

    async def test_wait_is_sender_scoped_one_shot_and_nonblocking(self):
        self.opts().update(empty_action='wait',wait_seconds=25)
        e=self.event('小A');await self.plugin.prepare_wake_flow(e)
        self.assertTrue(e.is_stopped());self.assertFalse(e.is_at_or_wake_command)
        other=self.event('别人的话',sender='9000000002')
        await self.plugin.prepare_wake_flow(other)
        self.assertFalse(other.is_at_or_wake_command);self.assertFalse(other.is_stopped())
        same=self.event('我要问的问题');await self.plugin.prepare_wake_flow(same)
        self.assertTrue(same.is_at_or_wake_command);self.assertFalse(same.is_stopped())
        second=self.event('不会持续接话');await self.plugin.prepare_wake_flow(second)
        self.assertFalse(second.is_at_or_wake_command)

    async def test_wait_does_not_cross_group_or_robot(self):
        self.opts()['empty_action']='wait'
        await self.plugin.prepare_wake_flow(self.event(at=True))
        for e in [self.event('普通话',group='234567890'),self.event('普通话',pid='bot-b')]:
            await self.plugin.prepare_wake_flow(e);self.assertFalse(e.is_at_or_wake_command)
        e=self.event('普通话');await self.plugin.prepare_wake_flow(e)
        self.assertTrue(e.is_at_or_wake_command)

    async def test_wait_timeout(self):
        self.opts().update(empty_action='wait',wait_seconds=3)
        await self.plugin.prepare_wake_flow(self.event('小A'))
        self.now[0]+=4
        e=self.event('太晚了');await self.plugin.prepare_wake_flow(e)
        self.assertFalse(e.is_at_or_wake_command)

    async def test_commands_do_not_get_swallowed_and_cancel_wait(self):
        self.opts()['empty_action']='wait'
        await self.plugin.prepare_wake_flow(self.event('小A'))
        command=self.event('/help');await self.plugin.prepare_wake_flow(command)
        self.assertFalse(command.is_stopped());self.assertEqual(command.message_str,'/help')
        e=self.event('之后普通聊天');await self.plugin.prepare_wake_flow(e)
        self.assertFalse(e.is_at_or_wake_command)

    async def test_registered_non_slash_command_not_reinterpreted(self):
        from astrbot.core.star.filter.command import CommandFilter
        e=self.event('小A')
        e.set_extra('activated_handlers',[types.SimpleNamespace(event_filters=[CommandFilter()])])
        await self.plugin.prepare_wake_flow(e)
        self.assertFalse(e.is_at_or_wake_command)

    async def test_calling_other_robot_does_not_consume_window(self):
        self.opts()['empty_action']='wait'
        await self.plugin.prepare_wake_flow(self.event('小A'))
        for e in [self.event('机器人B请回答'),self.event('你好')]:
            if e.message_str=='你好':
                from test_plugin import At
                e.message_obj.message.append(At('1000000002'))
            await self.plugin.prepare_wake_flow(e)
            self.assertFalse(e.is_at_or_wake_command)
        e=self.event('现在问你');await self.plugin.prepare_wake_flow(e)
        self.assertTrue(e.is_at_or_wake_command)

    async def test_robots_never_gain_followup_or_history(self):
        e=self.event('小A',sender='1000000002')
        await self.plugin.prepare_wake_flow(e);await self.plugin.record_wake_context(e)
        self.assertFalse(e.is_at_or_wake_command)
        self.assertFalse(self.plugin._wake_flow.history)

    async def test_semantic_rejection_cannot_be_bypassed(self):
        from test_plugin import Provider
        self.config['semantic_options']['semantic_enabled']=True
        self.ctx.provider=Provider('NO')
        e=self.event('小A');e.is_at_or_wake_command=True
        await self.plugin.prepare_wake_flow(e)
        self.assertTrue(e.is_stopped());self.assertFalse(e.is_at_or_wake_command)
        self.assertFalse(self.plugin._wake_flow.pending)
        await self.plugin.wake_by_regex(e)
        self.assertEqual(len(self.ctx.requests),1)

    async def test_followup_armed_after_send_only_and_not_continuous(self):
        self.opts()['followup_enabled']=True
        e=self.event('小A你怎么看');await self.plugin.prepare_wake_flow(e)
        self.assertFalse(self.plugin._wake_flow.pending)
        # after-message hook may also run after a failed OneBot send.
        await self.plugin.after_wake_message_sent(e)
        self.assertFalse(self.plugin._wake_flow.pending)
        e._has_send_oper=True;e._result=types.SimpleNamespace(chain=[Plain('机器人已回复')])
        self.now[0]+=100
        await self.plugin.after_wake_message_sent(e)
        self.assertTrue(self.plugin._wake_flow.pending)
        self.assertIn('机器人已回复',str(self.plugin._wake_flow.snapshot(('bot-a','123456789'),2)))
        e2=self.event('接着问');await self.plugin.prepare_wake_flow(e2)
        self.assertTrue(e2.is_at_or_wake_command)
        e2._has_send_oper=True
        await self.plugin.after_wake_message_sent(e2)
        e3=self.event('第三条');await self.plugin.prepare_wake_flow(e3)
        self.assertFalse(e3.is_at_or_wake_command)

    async def test_stopped_sender_gate_never_wakes_or_injects(self):
        e=self.event('小A');e.stop_event()
        e.set_extra('_peer_wake_context',[{'speaker':'群友','text':'秘密'}])
        await self.plugin.prepare_wake_flow(e);await self.plugin.record_wake_context(e)
        req=Request();await self.plugin.inject_wake_context(e,req)
        self.assertFalse(e.is_at_or_wake_command)
        self.assertFalse(req.extra_user_content_parts)
        self.assertFalse(self.plugin._wake_flow.history)

    async def test_scope_applies_to_at_as_well_as_keyword(self):
        self.config['robot_setup']['wake_groups']=['234567890']
        e=self.event(at=True);before=list(e.get_messages())
        await self.plugin.prepare_wake_flow(e)
        self.assertEqual(e.get_messages(),before)
        self.assertFalse(e.get_extra('_peer_flow_managed'))

    async def test_clear_cancels_pending_send_completion(self):
        self.opts()['followup_enabled']=True
        e=self.event('小A你怎么看');await self.plugin.prepare_wake_flow(e)
        self.plugin._wake_flow.clear();e._has_send_oper=True
        await self.plugin.after_wake_message_sent(e)
        self.assertFalse(self.plugin._wake_flow.pending)


class ValidationTest(unittest.TestCase):
    def test_existing_config_adds_disabled_flow_only(self):
        cfg=validate_all(example())
        self.assertEqual(cfg['robot_setup']['instances'][0]['wake_flow'],FLOW_DEFAULTS)

    def test_bad_flow_values_are_rejected(self):
        for key,value in [('enabled','true'),('context_count',51),('context_count',-1),
                          ('context_count',True),('wait_seconds',0),('wait_seconds',301),
                          ('context_max_chars',50000),('empty_action','bogus'),('followup_enabled',1)]:
            cfg=example();cfg['robot_setup']['instances'][0]['wake_flow']={key:value}
            with self.subTest(key=key,value=value),self.assertRaises(InvalidSettings):validate_all(cfg)

    def test_count_zero_and_maximum_wait_supported(self):
        cfg=example();cfg['robot_setup']['instances'][0]['wake_flow']={'context_count':0,'wait_seconds':300}
        flow=validate_all(cfg)['robot_setup']['instances'][0]['wake_flow']
        self.assertEqual(flow['context_count'],0);self.assertEqual(flow['wait_seconds'],300)


if __name__=='__main__':unittest.main()
