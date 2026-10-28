"""Regression cases for archive cancellation, ingress and status accuracy."""
import asyncio
import threading
import tempfile
import time
import unittest
from types import ModuleType
from unittest.mock import patch

from test_plugin import Main, Context, EventStub
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all
from astrbot_plugin_peer_context_guard.archive_worker import ArchiveWriter, ArchiveRow


class ArchiveCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_close_still_joins_worker(self):
        entered, release = threading.Event(), threading.Event()
        class Store:
            writes = 0
            def append(self, *args):
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('Test write was not released')
                self.writes += 1
                return True
        store = Store()
        writer = ArchiveWriter(store, 2)
        writer.start()
        row = ArchiveRow('bot-a', '123456789', '1000000002', 'B', 'text', None, 20)
        writer.enqueue(row)
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        self.assertTrue(entered.is_set())
        closing = asyncio.create_task(writer.close(drain_timeout=.001))
        await asyncio.sleep(.005)
        closing.cancel()
        await asyncio.sleep(.005)
        self.assertFalse(closing.done(), 'Cancellation must not abandon the writer')
        self.assertTrue(writer.stats()['in_flight'])
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.assertEqual(store.writes, 1)
        self.assertEqual(writer.saved, 1)
        self.assertFalse(writer.stats()['in_flight'])
        self.assertFalse(writer.stats()['running'])
        await writer.close()

    async def test_concurrent_close_drains_once(self):
        class Store:
            n = 0
            def append(self, *args):
                self.n += 1
                return True
        store = Store()
        writer = ArchiveWriter(store, 4)
        writer.start()
        for i in range(3):
            writer.enqueue(ArchiveRow('bot-a', '123456789', '1000000002', 'B', 'x', str(i), 20))
        await asyncio.gather(writer.close(), writer.close())
        self.assertEqual(store.n, 3)
        self.assertEqual(writer.queue._unfinished_tasks, 0)
        self.assertEqual(writer.saved, 3)


class GuardAndStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_payload_is_bounded_before_enqueue(self):
        plugin = Main.PeerContextGuard(Context(), validate_all(example()))
        class Collector:
            dropped = 0
            def __init__(self):
                self.rows = []
            def enqueue(self, row):
                self.rows.append(row)
                return True
        plugin._archive_writer = Collector()
        plugin.store = object()
        long_message = 'x' * 200000
        event = EventStub('bot-a', '123456789', '1000000003', '1000000001', long_message)
        self.assertTrue(plugin._process_incoming(event))
        self.assertTrue(event.stopped)
        self.assertEqual(plugin._archive_writer.rows[0].content, long_message[:1500])
        empty = EventStub('bot-a', '123456789', '1000000003', '1000000001', '   ')
        self.assertTrue(plugin._process_incoming(empty))
        self.assertTrue(empty.stopped)
        self.assertEqual(len(plugin._archive_writer.rows), 1)

    async def test_initialized_queue_never_waits_for_slow_archive(self):
        entered, release = threading.Event(), threading.Event()
        plugin = Main.PeerContextGuard(Context(), validate_all(example()))
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(Main, 'get_astrbot_plugin_data_path', return_value=temp):
                await plugin.initialize()
            def slow_append(*args):
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('Test writer not released')
                return True
            try:
                with patch.object(plugin.store, 'append', side_effect=slow_append):
                    bot = lambda: EventStub('bot-a', '123456789', '1000000003', '1000000001', 'hello')
                    plugin.context.q.put_nowait(bot())
                    for _ in range(100):
                        if entered.is_set():
                            break
                        await asyncio.sleep(.002)
                    self.assertTrue(entered.is_set())
                    start = time.monotonic()
                    # Fill the bounded buffer while the real worker is blocked.
                    for _ in range(1025):
                        e = bot()
                        plugin.context.q.put_nowait(e)
                        self.assertTrue(e.stopped)
                    human = EventStub('bot-a', '123456789', '9000000001', '1000000001', 'hello')
                    plugin.context.q.put_nowait(human)
                    self.assertLess(time.monotonic() - start, .5)
                    self.assertEqual(plugin.context.q.events, [human])
                    self.assertGreater(plugin._archive_writer.dropped, 0)
                    release.set()
                    await plugin._archive_writer.close(drain_timeout=0)
            finally:
                release.set()
                await plugin.terminate()

    async def test_archive_preparation_failure_cannot_weaken_guard(self):
        plugin = Main.PeerContextGuard(Context(), validate_all(example()))
        event = EventStub('bot-a', '123456789', '1000000003', '1000000001', 'hello')
        with patch.object(plugin, '_archive_bot_event', side_effect=RuntimeError('simulated')):
            self.assertTrue(plugin._process_incoming(event))
        self.assertTrue(event.stopped)
        self.assertEqual(plugin._blocked_events, 1)

    async def test_cooldown_count_excludes_expired_entries(self):
        plugin = Main.PeerContextGuard(Context(), validate_all(example()))
        plugin._patrol._clock = lambda: 100
        plugin._patrol._cooldown = {('bot-a', '123456789'): 99, ('bot-b', '123456789'): 110}
        web = ModuleType('astrbot.api.web')
        web.json_response = lambda obj: obj
        with patch.dict('sys.modules', {'astrbot.api.web': web}):
            status = await plugin.web_get_status()
        self.assertEqual(status['cooldown_groups'], 1)
        self.assertNotIn('123456789', str(status))


if __name__ == '__main__':
    unittest.main()
