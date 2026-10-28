"""Bounded, non-blocking SQLite history archival.

Incoming messages are filtered synchronously by sender QQ before they reach
AstrBot's queue. Historical records are best effort: enqueue never waits for
SQLite, and a full archive buffer never lets a blocked bot message through.

A dedicated single-thread executor is used so shutdown can wait for an
in-flight SQLite call to finish before the database connection is closed.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from astrbot.api import logger


@dataclass(frozen=True)
class ArchiveRow:
    platform_id: str
    group_id: str
    sender_id: str
    name: str
    content: str
    message_id: str | None
    limit: int


class ArchiveWriter:
    def __init__(self, store, queue_size: int = 1024):
        self.store = store
        self.queue: asyncio.Queue[ArchiveRow] = asyncio.Queue(maxsize=queue_size)
        self.task: asyncio.Task | None = None
        self._executor: ThreadPoolExecutor | None = None
        self.saved = 0
        self.failed = 0
        self.dropped = 0
        self.accepted = 0
        self.closed = False
        self._active = False
        self._close_task: asyncio.Task | None = None

    def start(self):
        if self.closed:
            raise RuntimeError('Cannot restart closed archive writer')
        if self.task is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='peer-archive')
            self.task = asyncio.create_task(self._run(), name='peer-bot-archive')

    def enqueue(self, row: ArchiveRow) -> bool:
        if self.closed or self.task is None or self.task.done():
            self.dropped += 1
            return False
        try:
            self.queue.put_nowait(row)
            self.accepted += 1
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False

    def _write(self, item: ArchiveRow):
        """Executed inside the owned worker thread; also tracks late completion.

        The asyncio consumer can be cancelled during shutdown but the thread
        may still finish a write. Track its outcome in the thread instead of
        losing a successful result when the asyncio Future is cancelled.
        """
        try:
            written = self.store.append(item.platform_id, item.group_id,
                                        item.sender_id, item.name, item.content,
                                        item.message_id, item.limit)
            if written:
                self.saved += 1
        except Exception as exc:
            self.failed += 1
            logger.warning('[peer-context] archive write failed (%s)', type(exc).__name__)
        finally:
            self._active = False

    async def _run(self):
        while True:
            item = await self.queue.get()
            self._active = True
            try:
                # Cancelling the consumer must not cancel a submitted write
                # before its worker starts, or accepted rows escape accounting.
                await asyncio.shield(asyncio.get_running_loop().run_in_executor(
                    self._executor, self._write, item))
            finally:
                self.queue.task_done()

    async def close(self, drain_timeout: float = 5):
        """Stop accepting writes; drain what fits the deadline, then join I/O.

        Shutdown of the dedicated executor is awaited *before* store.close(),
        so an in-flight write cannot access an already closed SQLite handle.
        """
        self.closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(drain_timeout))
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                # A plugin reload can itself be cancelled. Finish owned I/O
                # before propagating cancellation to the plugin terminator.
                cancelled = True
        self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _close(self, drain_timeout: float):
        task = self.task
        if task is not None:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=max(0, drain_timeout))
            except asyncio.TimeoutError:
                logger.warning('[peer-context] archive shutdown exceeded grace period; pending=%d', self.queue.qsize())
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.task = None
        executor, self._executor = self._executor, None
        if executor is not None:
            # Awaiting executor completion matters: cancelling an awaited
            # run_in_executor future does not stop the underlying thread.
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=False)
        # Records that never started are best-effort archival losses.
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
            self.dropped += 1

    def stats(self):
        return {'queued': self.queue.qsize(), 'capacity': self.queue.maxsize,
                'accepted': self.accepted, 'written': self.saved,
                'failed': self.failed, 'dropped': self.dropped,
                'in_flight': self._active,
                'running': bool(self.task is not None and not self.task.done())}
