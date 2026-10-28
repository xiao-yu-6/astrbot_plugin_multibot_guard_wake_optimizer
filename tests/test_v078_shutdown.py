"""Refined async archive regression: shutdown must join an in-flight SQLite call."""
import asyncio
import time
import unittest

from astrbot_plugin_peer_context_guard.archive_worker import ArchiveRow, ArchiveWriter


class SlowDatabase:
    def __init__(self, delay=0.06):
        self.delay = delay
        self.open = True
        self.writes = 0
        self.used_after_close = False

    def append(self, *_args):
        if not self.open:
            self.used_after_close = True
        time.sleep(self.delay)
        if not self.open:
            self.used_after_close = True
        self.writes += 1
        return True

    def close(self):
        self.open = False


def row(i):
    return ArchiveRow('bot-a', '123456789', '1000000002', '机器人B',
                      'test', str(i), 100)


class ArchiveShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_joins_inflight_thread_even_on_timeout(self):
        db = SlowDatabase()
        writer = ArchiveWriter(db, queue_size=2)
        writer.start()
        self.assertTrue(writer.enqueue(row(1)))
        self.assertTrue(writer.enqueue(row(2)))
        # Wait for worker to start without waiting for it to complete.
        for _ in range(100):
            if writer._active:
                break
            await asyncio.sleep(.001)
        self.assertTrue(writer._active)
        await writer.close(drain_timeout=.001)
        db.close()
        self.assertFalse(db.used_after_close)
        self.assertFalse(writer.stats()['running'])
        self.assertFalse(writer.stats()['in_flight'])
        self.assertEqual(writer.queue.qsize(), 0)
        self.assertEqual(writer.queue._unfinished_tasks, 0)
        self.assertEqual(writer.saved + writer.dropped, 2)
        self.assertFalse(writer.enqueue(row(3)))

    async def test_close_without_timeout_flushes_and_is_idempotent(self):
        db = SlowDatabase(delay=.001)
        writer = ArchiveWriter(db, queue_size=4)
        writer.start()
        self.assertTrue(writer.enqueue(row(1)))
        self.assertTrue(writer.enqueue(row(2)))
        await writer.close(drain_timeout=2)
        await writer.close(drain_timeout=2)
        db.close()
        self.assertEqual(writer.saved, 2)
        self.assertEqual(writer.dropped, 0)

    async def test_archive_failure_does_not_kill_worker(self):
        class Failing:
            def __init__(self): self.calls = 0
            def append(self, *_args):
                self.calls += 1
                if self.calls == 1:
                    raise OSError('test failure')
                return True
        db = Failing()
        writer = ArchiveWriter(db, queue_size=4)
        writer.start()
        self.assertTrue(writer.enqueue(row(1)))
        self.assertTrue(writer.enqueue(row(2)))
        await writer.close()
        self.assertEqual(db.calls, 2)
        self.assertEqual(writer.failed, 1)
        self.assertEqual(writer.saved, 1)


if __name__ == '__main__':
    unittest.main()
