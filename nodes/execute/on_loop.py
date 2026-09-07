"""Run a synchronous object's methods on the event loop's thread when called from a worker.

The tuple store has ONE sqlite connection, opened on the loop thread (`nodes/store_tuples`), and
the execution machine (`nodes/execute/coordinator.py`) writes through it between venue round
trips. Until 2026-09-07 the whole machine ran on the socket loop: every real cover blocked frame
reading for its balance calls, POSTs and settle polling (0.2-10 s), the loop probe then declared
a STALL, and the clearance refused the next cover CLOCK_UNHEALTHY -- four stalls of 6-11 s on
the Mexico box, one of them across a 13 % print. The machine now runs in a worker thread with
its store-touching collaborators wrapped in `OnLoop`: a call from the worker is queued to the
loop with `call_soon_threadsafe` and waited for; a call from the loop thread runs directly, so
paper modes and the tests, which never leave the loop, are unchanged.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


def on_loop_thread(loop: asyncio.AbstractEventLoop | None) -> bool:
    """True when the caller is the thread running `loop` (or there is no loop to defer to)."""
    if loop is None:
        return True
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False


class OnLoop:
    """A proxy: attribute reads pass through; a method called off the loop thread runs ON it."""

    def __init__(self, target: Any, loop: asyncio.AbstractEventLoop | None = None):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "loop", loop)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "loop":
            object.__setattr__(self, name, value)
        else:
            setattr(self._target, name, value)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            loop = self.loop
            if on_loop_thread(loop):
                return attr(*args, **kwargs)
            fut: concurrent.futures.Future = concurrent.futures.Future()

            def run() -> None:
                try:
                    fut.set_result(attr(*args, **kwargs))
                except BaseException as exc:  # noqa: BLE001 -- the worker gets the exception, the loop keeps going
                    fut.set_exception(exc)

            loop.call_soon_threadsafe(run)
            return fut.result()

        return call
