import asyncio
import concurrent.futures
import threading
import time

from nodes.execute.on_loop import OnLoop, on_loop_thread


class Store:
    def __init__(self):
        self.threads = []
        self.rows = 0

    def write(self, n):
        self.threads.append(threading.get_ident())
        self.rows += n
        return self.rows

    def boom(self):
        raise ValueError("refused")


def test_a_call_from_a_worker_thread_runs_on_the_loop_thread_and_a_call_on_the_loop_runs_directly():
    async def main():
        loop = asyncio.get_running_loop()
        st = Store()
        px = OnLoop(st, loop)
        assert on_loop_thread(loop)
        assert px.write(1) == 1                                   # on the loop: direct
        # from a worker: queued to the loop, awaited, the result comes back
        got = await asyncio.to_thread(px.write, 2)
        assert got == 3 and st.rows == 3
        assert set(st.threads) == {threading.get_ident()}, "every write ran on the loop's thread"
        # exceptions cross back to the caller, and the loop is still alive
        try:
            await asyncio.to_thread(px.boom)
        except ValueError as exc:
            assert "refused" in str(exc)
        else:
            raise AssertionError("the exception must reach the worker")
        assert px.rows == 3, "attribute reads pass through"
        px.rows = 9
        assert st.rows == 9, "attribute writes reach the target"
    asyncio.run(main())


def test_a_nowait_method_is_queued_in_order_and_its_exception_is_said_not_raised(capsys):
    async def main():
        loop = asyncio.get_running_loop()
        st = Store()
        px = OnLoop(st, loop, nowait={"write", "boom"})
        def worker():
            assert px.write(1) is None and px.write(2) is None      # queued, no wait
            assert px.boom() is None
            return threading.get_ident()
        wt = await asyncio.to_thread(worker)
        await asyncio.sleep(0)                                      # the queued calls run on the loop
        await asyncio.sleep(0)
        assert st.rows == 3 and set(st.threads) == {threading.get_ident()} and wt != threading.get_ident()
        out = capsys.readouterr().out
        assert "boom refused off the loop: ValueError" in out
    asyncio.run(main())


def test_nowait_finalizer_runs_after_success_and_failure_without_escaping_the_loop():
    async def main():
        loop = asyncio.get_running_loop()
        st = Store()
        finished = []
        errors = []
        px = OnLoop(st, loop, nowait={"write", "boom"}, after_call=finished.append,
                    on_error=errors.append)
        await asyncio.to_thread(px.write, 2)
        await asyncio.to_thread(px.boom)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert finished[0] is None and isinstance(finished[1], ValueError)
        assert len(errors) == 1 and isinstance(errors[0], ValueError)
    asyncio.run(main())


def test_without_a_loop_every_call_is_direct():
    st = Store()
    px = OnLoop(st)
    assert px.write(4) == 4 and st.threads == [threading.get_ident()]


def test_worker_wait_for_a_stalled_loop_is_deadline_bounded():
    async def main():
        px = OnLoop(Store(), asyncio.get_running_loop())
        result = []
        def worker():
            try:
                px.write(1, _timeout_s=0.01)
            except Exception as exc:  # expected boundary
                result.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)  # deliberately stall the event loop past the worker's authority
        thread.join()
        await asyncio.sleep(0)
        assert len(result) == 1 and isinstance(result[0], concurrent.futures.TimeoutError)
    asyncio.run(main())
