import threading
import time

from nodes.store_tuples.store import TupleStore


def test_a_second_store_on_the_same_file_writes_from_another_thread_beside_the_first(tmp_path):
    """2026-09-08: the execution worker writes its journal and records through its own connection
    while the loop's connection keeps writing evaluations. WAL and the 30 s busy timeout make the
    two writers take turns; one connection is never used by two threads."""
    path = tmp_path / "t.sqlite"
    main = TupleStore(path, enforce_volume=False)
    worker = TupleStore(path, enforce_volume=False, check_same_thread=False, isolation_level="IMMEDIATE")
    main.con.execute("CREATE TABLE IF NOT EXISTS t(x)"); main.con.commit()
    errors = []

    def run():
        try:
            for i in range(200):
                worker.con.execute("SELECT COUNT(*) FROM t").fetchone()     # a read, then a write (journal.pending's shape)
                worker.con.execute("INSERT INTO t(x) VALUES(?)", (i,))
                worker.con.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    th = threading.Thread(target=run); th.start()
    for i in range(200):
        main.con.execute("INSERT INTO t(x) VALUES(?)", (-i,))
        main.con.commit()
    th.join()
    assert errors == []
    assert main.con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 400, "both writers' rows are visible to the loop's connection"


def test_the_worker_waits_for_a_transaction_the_loop_holds_open_instead_of_failing(tmp_path):
    """BEGIN IMMEDIATE puts the wait through the busy handler: a write behind the loop's open
    transaction waits for it (the 30 s timeout), never 'database is locked' at once."""
    path = tmp_path / "t.sqlite"
    main = TupleStore(path, enforce_volume=False)
    worker = TupleStore(path, enforce_volume=False, check_same_thread=False, isolation_level="IMMEDIATE")
    main.con.execute("CREATE TABLE IF NOT EXISTS t(x)"); main.con.commit()
    main.con.execute("INSERT INTO t(x) VALUES(1)")            # the loop's transaction stays open...
    got = {}

    def run():
        t0 = time.monotonic()
        try:
            worker.con.execute("SELECT COUNT(*) FROM t").fetchone()
            worker.con.execute("INSERT INTO t(x) VALUES(2)")
            worker.con.commit()
            got["ok"] = time.monotonic() - t0
        except Exception as exc:  # noqa: BLE001
            got["err"] = exc
    th = threading.Thread(target=run); th.start()
    time.sleep(0.5)
    main.con.commit()                                          # ...for half a second
    th.join(timeout=10)
    assert "err" not in got, got
    assert got["ok"] >= 0.4, "the worker waited for the loop's commit"
    assert main.con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
