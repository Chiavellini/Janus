import threading

from nodes.store_tuples.store import TupleStore


def test_a_second_store_on_the_same_file_writes_from_another_thread_beside_the_first(tmp_path):
    """2026-09-08: the execution worker writes its journal and records through its own connection
    while the loop's connection keeps writing evaluations. WAL and the 30 s busy timeout make the
    two writers take turns; one connection is never used by two threads."""
    path = tmp_path / "t.sqlite"
    main = TupleStore(path, enforce_volume=False)
    worker = TupleStore(path, enforce_volume=False, check_same_thread=False)
    main.con.execute("CREATE TABLE IF NOT EXISTS t(x)"); main.con.commit()
    errors = []

    def run():
        try:
            for i in range(200):
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
