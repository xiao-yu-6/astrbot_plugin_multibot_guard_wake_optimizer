"""Per-group, message-triggered bounded patrol window, inspired by Angel Heart.

The patrol never sends messages. It only chooses exactly one live AstrBot
human message event per window to ask a separate classifier; all older events
fall through without awakening. The normal AstrBot pipeline does the reply.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Callable


@dataclass
class _Window:
    future: asyncio.Future
    task: asyncio.Task
    count: int = 1


class PatrolScheduler:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._windows: dict[tuple[str, str], _Window] = {}
        self._busy: set[tuple[str, str]] = set()
        self._cooldown: dict[tuple[str, str], float] = {}
        self.generation = 0

    async def wait_for_turn(self, key: tuple[str, str], interval: float,
                            minimum_messages: int = 1) -> bool:
        """Coalesce group events; only latest arrival may run one patrol.

        The timer is anchored to the FIRST message, not extended by every
        new message, so busy chats cannot starve the patrol indefinitely.
        """
        if key in self._busy or self._clock() < self._cooldown.get(key, 0.0):
            return False
        generation = self.generation
        current = self._windows.get(key)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        if current is not None:
            # Previous event no longer owns the conversation snapshot.
            if not current.future.done():
                current.future.set_result(False)
            current.future = future
            current.count += 1
        else:
            # Bound outstanding group windows. Fail closed on excess groups.
            if len(self._windows) + len(self._busy) >= 256:
                return False
            token = self.generation
            async def release():
                try:
                    await asyncio.sleep(max(0.01, float(interval)))
                    window = self._windows.pop(key, None)
                    if window is None or token != self.generation:
                        return
                    eligible = window.count >= minimum_messages and key not in self._busy
                    if eligible:
                        self._busy.add(key)
                    if not window.future.done():
                        window.future.set_result(eligible)
                except asyncio.CancelledError:
                    return
            task = asyncio.create_task(release())
            self._windows[key] = _Window(future=future, task=task)
        try:
            return bool(await future)
        except asyncio.CancelledError:
            # If the newest event is cancelled, cancel this whole window;
            # otherwise a timer could leave this group permanently busy.
            window = self._windows.get(key)
            if window is not None and window.future is future:
                self._windows.pop(key, None)
                window.task.cancel()
            elif (generation == self.generation and future.done()
                  and not future.cancelled() and future.result() is True):
                # The timer can reserve this group immediately BEFORE the
                # awaiting event task is canceled, after popping its window.
                self._busy.discard(key)
            if not future.done():
                future.set_result(False)
            raise

    def finish(self, key: tuple[str, str], cooldown: float) -> None:
        self._busy.discard(key)
        if cooldown > 0:
            self._cooldown[key] = self._clock() + float(cooldown)
        else:
            self._cooldown.pop(key, None)
        # Keep memory bounded even if many different groups rotate.
        if len(self._cooldown) > 512:
            for old in list(self._cooldown)[:len(self._cooldown) - 512]:
                self._cooldown.pop(old, None)

    def clear(self) -> None:
        self.generation += 1
        for record in self._windows.values():
            if not record.future.done():
                record.future.set_result(False)
            record.task.cancel()
        self._windows.clear()
        self._busy.clear()
        self._cooldown.clear()
