import asyncio
import threading

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


def test_without_a_loop_every_call_is_direct():
    st = Store()
    px = OnLoop(st)
    assert px.write(4) == 4 and st.threads == [threading.get_ident()]
