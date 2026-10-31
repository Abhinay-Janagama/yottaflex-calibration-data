from collections import Counter
from src import ids
from src.events import build_calibrations
from src.masters import build_masters
from src.workflow import END_OF_YEAR, apply_final_status, build_workflow

ROLES = {"PLANT_OPERATOR", "MAINTENANCE_ENGINEER", "QUALITY_ENGINEER",
         "PRODUCTION_PLANNER", "OT_IT_ADMIN"}

def make(name="starter"):
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    return masters, events, certs, build_workflow(masters, events, certs)


def retest_ids(events):
    by_asset = {}
    for e in events:
        by_asset.setdefault(e["asset_id"], []).append(e)
    out = set()
    for chain in by_asset.values():
        for prev, cur in zip(chain, chain[1:]):
            if prev["result"] == "FAIL":
                out.add(cur["calibration_id"])
    return out


def test_work_order_ids_unique_well_formed_and_chronological():
    _, _, _, wf = make()
    wos = wf["work_order"]
    wo_ids = [w["work_order_id"] for w in wos]
    assert len(wo_ids) == len(set(wo_ids))
    assert all(ids.PATTERNS["work_order_id"].match(i) for i in wo_ids)
    assert [int(i.split("-")[-1]) for i in wo_ids] == list(range(1, len(wos) + 1))
    created = [w["created_at"] for w in wos]
    assert created == sorted(created)


def test_work_order_links_dates_and_downtime():
    m, events, _, wf = make()
    assets = {a["asset_id"] for a in m["asset"]}
    cals = {e["calibration_id"]: e for e in events}
    for w in wf["work_order"]:
        assert w["work_type"] in {"ROUTINE_CALIBRATION", "CORRECTIVE_ACTION", "IMPACT_ASSESSMENT"}
        assert w["status"] in {"OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
        assert w["priority"] in {"LOW", "MEDIUM", "HIGH"}
        assert w["assigned_role"] in ROLES
        assert w["asset_id"] in assets
        src = cals[w["source_calibration_id"]]
        assert w["asset_id"] == src["asset_id"]
        assert w["created_at"].date() >= src["calibration_date"]
        assert (w["status"] == "COMPLETED") == (w["completed_at"] is not None)
        if w["completed_at"] is not None:
            assert w["completed_at"] >= w["created_at"]
        assert w["downtime_hours"] >= 0
        if w["work_type"] == "IMPACT_ASSESSMENT":
            assert w["downtime_hours"] == 0
        else:
            end = w["completed_at"] if w["completed_at"] is not None else END_OF_YEAR
            assert w["downtime_hours"] == round((end - w["created_at"]).total_seconds() / 3600, 1)


def test_routine_work_orders_match_scheduled_calibrations():
    _, events, _, wf = make()
    retests = retest_ids(events)
    routine = {w["source_calibration_id"] for w in wf["work_order"]
               if w["work_type"] == "ROUTINE_CALIBRATION"}
    assert routine == {e["calibration_id"] for e in events if e["calibration_id"] not in retests}


def test_rule_r4_failed_calibration_gets_corrective_and_impact_work_orders():
    _, events, _, wf = make()
    for e in events:
        types = [w["work_type"] for w in wf["work_order"]
                 if w["source_calibration_id"] == e["calibration_id"]]
        if e["result"] == "FAIL":
            assert types.count("CORRECTIVE_ACTION") == 1
            assert types.count("IMPACT_ASSESSMENT") == 1
        else:
            assert "CORRECTIVE_ACTION" not in types and "IMPACT_ASSESSMENT" not in types


def test_failed_calibration_alert_exists_for_every_fail():
    _, events, _, wf = make()
    failed_alerts = [a["related_record_id"] for a in wf["alert"] if a["alert_type"] == "CALIBRATION_FAILED"]
    assert len(failed_alerts) == len(set(failed_alerts))
    assert set(failed_alerts) == {e["calibration_id"] for e in events if e["result"] == "FAIL"}


def test_alert_rules_ids_and_timing():
    m, events, _, wf = make()
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    cals = {e["calibration_id"]: e for e in events}
    retests = retest_ids(events)
    alerts = wf["alert"]

    alert_ids = [a["alert_id"] for a in alerts]
    assert len(alert_ids) == len(set(alert_ids))
    assert all(ids.PATTERNS["alert_id"].match(i) for i in alert_ids)
    assert [int(i.split("-")[-1]) for i in alert_ids] == list(range(1, len(alerts) + 1))
    assert [a["created_at"] for a in alerts] == sorted(a["created_at"] for a in alerts)

    pairs = [(a["alert_type"], a["related_record_id"]) for a in alerts]
    assert len(pairs) == len(set(pairs))

    got = {}
    for a in alerts:
        src = cals[a["related_record_id"]]
        assert a["asset_id"] == src["asset_id"]
        assert a["created_at"].date() >= src["calibration_date"]
        assert a["alert_type"] in {"CALIBRATION_OVERDUE", "CALIBRATION_FAILED", "CERTIFICATE_MISSING"}
        assert a["severity"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert a["status"] in {"OPEN", "ACKNOWLEDGED", "RESOLVED"}
        got.setdefault(a["alert_type"], set()).add(a["related_record_id"])

    expected_overdue = {e["calibration_id"] for e in events
                        if e["calibration_id"] not in retests
                        and e["days_late"] > plans[e["plan_id"]]["grace_days"]}
    expected_missing = {e["calibration_id"] for e in events
                        if e["certificate_id"] is None and plans[e["plan_id"]]["requires_certificate"]}
    assert got.get("CALIBRATION_OVERDUE", set()) == expected_overdue
    assert got.get("CERTIFICATE_MISSING", set()) == expected_missing


def test_audit_ids_unique_well_formed_and_numbered():
    _, _, _, wf = make()
    audits = wf["audit_record"]
    audit_ids = [r["audit_id"] for r in audits]
    assert len(audit_ids) == len(set(audit_ids))
    assert all(ids.PATTERNS["audit_id"].match(i) for i in audit_ids)
    assert [int(i.split("-")[-1]) for i in audit_ids] == list(range(1, len(audits) + 1))


def test_audit_history_is_a_valid_unbroken_chain():
    m, events, certs, wf = make()
    exists = {
        "ASSET": {a["asset_id"] for a in m["asset"]},
        "CERTIFICATE": {c["certificate_id"] for c in certs},
        "WORKORDER": {w["work_order_id"] for w in wf["work_order"]},
    }
    history = {}
    for r in wf["audit_record"]:
        assert r["entity_id"] in exists[r["entity_type"]]
        assert r["actor_role"] in ROLES
        assert r["new_value"]
        history.setdefault((r["entity_type"], r["entity_id"]), []).append(r)

    for rows in history.values():                     # rows are in audit_id order
        assert rows[0]["old_value"] is None           # first record has no old value
        for prev, cur in zip(rows, rows[1:]):
            assert cur["old_value"] == prev["new_value"]   # nothing is skipped or overwritten
            assert cur["timestamp"] >= prev["timestamp"]

    # every certificate and every work order has a logbook entry
    assert {k[1] for k in history if k[0] == "CERTIFICATE"} == exists["CERTIFICATE"]
    assert {k[1] for k in history if k[0] == "WORKORDER"} == exists["WORKORDER"]


def test_final_asset_status_comes_from_the_logbook():
    m, events, _, wf = make()
    final = {a["asset_id"]: a["current_status"] for a in apply_final_status(m["asset"], wf["audit_record"])}
    last_result = {}
    for e in events:
        last_result[e["asset_id"]] = e["result"]
    for asset_id, status in final.items():
        assert status in {"ACTIVE", "QUARANTINED"}
        assert status == ("QUARANTINED" if last_result.get(asset_id) == "FAIL" else "ACTIVE")


def test_same_seed_same_workflow():
    assert make()[3] == make()[3]

def test_full_scale_sanity():
    _, events, _, wf = make("full")
    fails = sum(e["result"] == "FAIL" for e in events)
    kinds = Counter(w["work_type"] for w in wf["work_order"])
    assert kinds["CORRECTIVE_ACTION"] == fails
    assert kinds["IMPACT_ASSESSMENT"] == fails
    assert kinds["ROUTINE_CALIBRATION"] == len(events) - len(retest_ids(events))
    assert len(wf["alert"]) > 0
    audit_ids = [r["audit_id"] for r in wf["audit_record"]]
    assert len(audit_ids) == len(set(audit_ids))