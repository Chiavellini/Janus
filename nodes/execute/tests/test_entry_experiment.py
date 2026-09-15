from nodes.execute.entry_experiment import (
    ASSIGNMENT_ALGORITHM,
    F23_ASSIGNMENT_ALGORITHM,
    F23_CAPS,
    F23_OPERATOR_STATEMENT,
    F23_SPEC_PATH,
    F22_CAPS,
    F22_OPERATOR_STATEMENT,
    F22_SPEC_PATH,
    OUTCOME_TAXONOMY,
    assign_entry_arm,
    assignment_from_record,
    classify_outcome,
    first_three_fills_reconciled,
    f22_activation,
    f23_activation,
    assign_f23_entry_arm,
)


def _activation_state(root, **experiment_overrides):
    import hashlib

    spec = root / F22_SPEC_PATH
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("registered: F22\\n", encoding="utf-8")
    experiment = {
        "row_id": "F22",
        "spec_path": F22_SPEC_PATH,
        "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "assignment_algorithm": ASSIGNMENT_ALGORITHM,
    }
    experiment.update(experiment_overrides)
    return {
        "experiment": experiment,
        "mode": "LIMITED_LIVE",
        "operator_statement": F22_OPERATOR_STATEMENT,
        "caps": dict(F22_CAPS),
    }


def test_f22_activation_requires_exact_signed_spec_and_operator_authority(tmp_path):
    state = _activation_state(tmp_path)
    enabled, detail = f22_activation(root=tmp_path, state=state)
    assert enabled and "matches preregistration" in detail

    for field, value in (
        ("row_id", "F21"),
        ("spec_path", "research/other/spec.yaml"),
        ("spec_sha256", "0" * 64),
        ("assignment_algorithm", "janus:f22:entry-arm:v0"),
    ):
        changed = _activation_state(tmp_path, **{field: value})
        enabled, detail = f22_activation(root=tmp_path, state=changed)
        assert not enabled, (field, detail)

    changed = _activation_state(tmp_path)
    changed["operator_statement"] = F22_OPERATOR_STATEMENT + " "
    assert not f22_activation(root=tmp_path, state=changed)[0]
    changed = _activation_state(tmp_path)
    changed["caps"] = {**F22_CAPS, "day_notional_usd": 500.01}
    assert not f22_activation(root=tmp_path, state=changed)[0]


def test_f22_is_default_disabled_without_explicit_signed_experiment(tmp_path):
    spec = tmp_path / F22_SPEC_PATH
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("registered: F22\\n", encoding="utf-8")
    for state in ({}, {"operator_statement": F22_OPERATOR_STATEMENT, "caps": dict(F22_CAPS)}):
        enabled, detail = f22_activation(root=tmp_path, state=state)
        assert not enabled
        assert "experiment" in detail


def _checkpoint_store():
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.executescript("""
      CREATE TABLE f22_decisions(
        id INTEGER PRIMARY KEY, event_id TEXT, forward_row_id TEXT,
        assignment_algorithm TEXT, digest TEXT, arm TEXT, execution_id TEXT,
        selected_quantity REAL
      );
      CREATE TABLE executions(
        execution_id TEXT PRIMARY KEY, opportunity_id TEXT, event_id TEXT,
        league TEXT, mode TEXT, state TEXT, released INTEGER,
        first_filled REAL, started_utc REAL, quantity REAL
      );
      CREATE TABLE execution_settlements(
        execution_id TEXT, opportunity_id TEXT, event_id TEXT, league TEXT,
        mode TEXT, released INTEGER, kind TEXT, hedged_contracts REAL,
        unhedged_contracts REAL, realized_usd REAL, cover_usd REAL,
        directional_usd REAL
      );
    """)
    return type("Store", (), {"con": con})()


def _insert_fill(store, i, *, complete=True, identity=True, economics=True):
    exid = f"ex-{i}"
    opp, event, league, mode = f"opp-{i}", f"event-{i}", "mlb", "LIMITED_LIVE"
    assignment = assign_entry_arm(event)
    store.con.execute(
        "INSERT INTO f22_decisions VALUES(?,?,?,?,?,?,?,?)",
        (i, event, "F22", assignment.algorithm, assignment.digest, assignment.arm, exid, 10.0))
    store.con.execute(
        "INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?)",
        (exid, opp, event, league, mode, "RECONCILED" if complete else "HEDGED",
         int(complete), 10.0, float(i), 10.0))
    if complete:
        if not identity:
            event = "other-event"
        hedged = 10.0 if economics else None
        unhedged = 0.0 if economics else 1.0
        realized = 0.25 if economics else None
        cover = 0.25 if economics else None
        directional = 0.0 if economics else None
        store.con.execute(
            "INSERT INTO execution_settlements VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (exid, opp, event, league, mode, 1, "COVER", hedged, unhedged,
             realized, cover, directional))


def test_first_three_fills_reconciliation_checkpoint(tmp_path):
    store = _checkpoint_store()
    ok, detail = first_three_fills_reconciled(store)
    assert ok and "0 of first three F22 fills observed" in detail
    _insert_fill(store, 1)
    _insert_fill(store, 2)
    assert first_three_fills_reconciled(store)[0]

    _insert_fill(store, 3, complete=False)
    ok, detail = first_three_fills_reconciled(store)
    assert not ok and "not released RECONCILED" in detail

    # Once the first three are authoritatively settled, a later fill may still be in-flight;
    # requiring it here would turn the warm-up guard into a permanent one-fill-at-a-time throttle.
    store = _checkpoint_store()
    for i in (1, 2, 3):
        _insert_fill(store, i)
    _insert_fill(store, 4, complete=False)
    assert first_three_fills_reconciled(store) == (True, "first three F22 fills are authoritatively reconciled")


def test_first_three_exact_complete_fills_pass_and_identity_or_economics_mismatch_blocks():
    for kwargs, fragment in (
        ({"identity": False}, "identity/terminality mismatch"),
        ({"economics": False}, "economics incomplete"),
    ):
        store = _checkpoint_store()
        for i in (1, 2):
            _insert_fill(store, i)
        _insert_fill(store, 3, **kwargs)
        ok, detail = first_three_fills_reconciled(store)
        assert not ok and fragment in detail

    store = _checkpoint_store()
    for i in (1, 2, 3):
        _insert_fill(store, i)
    assert first_three_fills_reconciled(store) == (True, "first three F22 fills are authoritatively reconciled")


def test_first_three_checkpoint_rejects_duplicate_execution_and_cross_event_identity():
    store = _checkpoint_store()
    for i in (1, 2, 3):
        _insert_fill(store, i)
    store.con.execute(
        "INSERT INTO f22_decisions SELECT 99,event_id,forward_row_id,assignment_algorithm,digest,arm,execution_id,selected_quantity "
        "FROM f22_decisions WHERE id=1")
    ok, detail = first_three_fills_reconciled(store)
    assert not ok and "linked by 2 decisions" in detail

    store = _checkpoint_store()
    for i in (1, 2, 3):
        _insert_fill(store, i)
    store.con.execute("UPDATE f22_decisions SET event_id='other' WHERE id=3")
    ok, detail = first_three_fills_reconciled(store)
    assert not ok and ("assignment" in detail or "identity mismatch" in detail)


def test_first_three_allows_explicit_no_wire_without_execution_lineage():
    store = _checkpoint_store()
    store.con.execute("ALTER TABLE f22_decisions ADD COLUMN outcome TEXT")
    store.con.execute(
        "INSERT INTO f22_decisions(id,event_id,forward_row_id,assignment_algorithm,digest,arm,execution_id,selected_quantity,outcome) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (1, "refused", "F22", ASSIGNMENT_ALGORITHM, assign_entry_arm("refused").digest,
         assign_entry_arm("refused").arm, None, 10.0, "local_or_risk_refused_no_wire"))
    ok, detail = first_three_fills_reconciled(store)
    assert ok and "0 of first three F22 fills" in detail


def test_assignment_uses_registered_exact_bytes_and_stable_vectors():
    # The NUL separator is part of the registered input, not a formatting detail.
    a = assign_entry_arm("event-1")
    assert a.digest == "14b34be029f83e7ca0eca865b7cb3b94d5aae26a41aaa45fd583a6e4b91bde07"
    assert a.arm == "maker"
    assert a.algorithm == ASSIGNMENT_ALGORITHM
    assert assign_entry_arm("event-1") == a
    assert assign_entry_arm("event-1").arm == a.arm
    assert assign_entry_arm("event-2").digest != a.digest


def test_assignment_record_round_trips_and_rejects_mutation():
    a = assign_entry_arm("espn:nfl:401872928")
    record = a.as_record({"stake_usd": 30, "max_contracts": 25})
    assert record["forward_row_id"] == "F22"
    assert record["active_caps"] == {"stake_usd": 30.0, "max_contracts": 25.0}
    assert assignment_from_record(record) == a
    record["arm"] = "maker" if a.arm == "taker" else "taker"
    try:
        assignment_from_record(record)
    except ValueError:
        pass
    else:
        raise AssertionError("a persisted arm mutation must fail closed")


def test_outcome_taxonomy_does_not_collapse_unknown_or_zero_fill():
    assert classify_outcome(wire=False) == "local_or_risk_refused_no_wire"
    assert classify_outcome(wire=True, provider_state="REJECTED") == "provider_rejected_no_position"
    assert classify_outcome(wire=True, provider_state="UNFILLED") == "accepted_terminal_zero_fill"
    assert classify_outcome(wire=True, provider_state="UNCONFIRMED") == "unknown_provider_state"
    assert classify_outcome(wire=True, provider_state="FILLED", filled_contracts=2, requested_contracts=5) == "accepted_partial_fill"
    assert set(OUTCOME_TAXONOMY) == {
        "local_or_risk_refused_no_wire", "provider_rejected_no_position", "accepted_terminal_zero_fill",
        "accepted_partial_fill", "accepted_full_fill", "unknown_provider_state", "role_violation",
        "persistence_or_reconciliation_failure",
    }


def test_f23_activation_and_assignment_are_independent_from_f22(tmp_path):
    import hashlib
    spec = tmp_path / F23_SPEC_PATH
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("registered: F23\n", encoding="utf-8")
    state = {
        "experiment": {"row_id": "F23", "spec_path": F23_SPEC_PATH,
                       "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                       "assignment_algorithm": F23_ASSIGNMENT_ALGORITHM},
        "mode": "LIMITED_LIVE", "operator_statement": F23_OPERATOR_STATEMENT,
        "caps": dict(F23_CAPS),
    }
    assert f23_activation(root=tmp_path, state=state)[0]
    f22, f23 = assign_entry_arm("event-1"), assign_f23_entry_arm("event-1")
    assert f22.forward_row_id == "F22" and f23.forward_row_id == "F23"
    assert f22.algorithm != f23.algorithm and f22.digest != f23.digest
    assert f23 == assign_f23_entry_arm("event-1")
