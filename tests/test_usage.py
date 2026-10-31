import copy
import re
from collections import Counter
from datetime import date, timedelta

from src import ids
from src.config import INTERLOCK_LINES, SIM_END, SIM_START, get_scale
from src.events import build_calibrations
from src.masters import build_masters
from src.usage import _shift, build_usage
from src.workflow import build_workflow


def make(name="starter"):
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    wf = build_workflow(masters, events, certs)
    return masters, events, wf, build_usage(masters, events, wf, name)


def chains_of(events):
    chains = {}
    for e in events:
        chains.setdefault(e["asset_id"], []).append(e)
    return chains


def test_use_ids_and_basic_fields():
    m, _, _, out = make()
    uses = out["production_use"]
    assets = {a["asset_id"] for a in m["asset"]}
    assert len(uses) == get_scale("starter").n_uses
    use_ids = [u["use_id"] for u in uses]
    assert len(use_ids) == len(set(use_ids))
    stamps = [(u["used_at"], u["asset_id"]) for u in uses]
    assert stamps == sorted(stamps)
    for u in uses:
        assert ids.PATTERNS["use_id"].match(u["use_id"])
        assert u["use_id"] == ids.use_id(u["asset_id"], u["used_at"])
        assert u["asset_id"] in assets
        assert SIM_START <= u["used_at"].date() <= SIM_END
        assert re.match(r"^OP-\d{4}$", u["operator_code"])
        assert u["days_overdue"] >= 0


def test_calibration_in_force_is_the_latest_pass():
    _, events, _, out = make()
    cal_ids = {e["calibration_id"] for e in events}
    chains = chains_of(events)
    for u in out["production_use"]:
        chain = chains.get(u["asset_id"], [])
        day = u["used_at"].date()
        best = None
        for e in chain:
            if e["result"] == "PASS" and e["calibration_date"] <= day:
                best = e
        if best is not None:
            assert u["calibration_in_force"] == best["calibration_id"]
            assert u["due_date_at_use"] == best["next_due_date"]
        else:
            assert u["calibration_in_force"] is None
            assert u["due_date_at_use"] == (chain[0]["previous_due_date"] if chain else None)
        if u["calibration_in_force"] is not None:
            assert u["calibration_in_force"] in cal_ids


def test_rule_r3_status_is_derived_from_rules():
    m, _, _, out = make()
    assets = {a["asset_id"]: a for a in m["asset"]}
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    exts = {}
    for r in out["audit_record"]:
        if r["event_type"] == "EMERGENCY_EXTENSION":
            exts.setdefault(r["entity_id"], []).append(r)

    for u in out["production_use"]:
        a = assets[u["asset_id"]]
        plan = plans[a["plan_id"]]
        day = u["used_at"].date()
        due = u["due_date_at_use"]
        if due is None or day <= due + timedelta(days=plan["grace_days"]):
            expected = ("VALID", 0, None)
        else:
            overdue = (day - (due + timedelta(days=plan["grace_days"]))).days
            if not plan["block_if_overdue"]:
                expected = ("OVERDUE_ALLOWED", overdue, None)
            else:
                covering = [r for r in exts.get(a["asset_id"], [])
                            if r["old_value"] == due.isoformat()
                            and r["timestamp"] <= u["used_at"]
                            and day <= r["extension_until"]]
                if covering:
                    expected = ("OVERDUE_WITH_EXCEPTION", overdue, covering[0]["audit_id"])
                elif a["production_line"] in INTERLOCK_LINES:
                    expected = ("BLOCKED", overdue, None)
                else:
                    expected = ("VIOLATION", overdue, None)
        assert (u["use_status"], u["days_overdue"], u["exception_ref"]) == expected
        assert u["is_prohibited"] == (u["use_status"] == "VIOLATION")


def test_no_use_on_calibration_days_or_while_quarantined():
    _, events, _, out = make()
    cal_days = {(e["asset_id"], e["calibration_date"]) for e in events}
    changes = {}
    for r in out["audit_record"]:
        if r["entity_type"] == "ASSET" and r["event_type"] == "ASSET_STATUS_CHANGE":
            changes.setdefault(r["entity_id"], []).append((r["timestamp"], r["new_value"]))
    for u in out["production_use"]:
        assert (u["asset_id"], u["used_at"].date()) not in cal_days
        status = "ACTIVE"
        for ts, new in sorted(changes[u["asset_id"]]):
            if ts <= u["used_at"]:
                status = new
        assert status == "ACTIVE"


def test_emergency_extensions_follow_the_plan_policy():
    m, _, _, out = make()
    assets = {a["asset_id"]: a for a in m["asset"]}
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    for r in out["audit_record"]:
        if r["event_type"] != "EMERGENCY_EXTENSION":
            assert r["extension_until"] is None
            continue
        assert r["entity_type"] == "ASSET"
        plan = plans[assets[r["entity_id"]]["plan_id"]]
        assert plan["block_if_overdue"] and plan["max_extension_days"] > 0
        due = date.fromisoformat(r["old_value"])
        assert r["new_value"] == r["extension_until"].isoformat()
        grace_end = due + timedelta(days=plan["grace_days"])
        assert grace_end < r["extension_until"] <= grace_end + timedelta(days=plan["max_extension_days"])
        assert r["reason"]
        assert SIM_START <= r["timestamp"].date() <= SIM_END


def test_exception_refs_point_to_real_extensions():
    _, _, _, out = make()
    audit = {r["audit_id"]: r for r in out["audit_record"]}
    for u in out["production_use"]:
        if u["use_status"] == "OVERDUE_WITH_EXCEPTION":
            r = audit[u["exception_ref"]]
            assert r["event_type"] == "EMERGENCY_EXTENSION"
            assert r["entity_id"] == u["asset_id"]
            assert r["timestamp"] <= u["used_at"]
            assert u["used_at"].date() <= r["extension_until"]
        else:
            assert u["exception_ref"] is None


def test_merged_audit_numbering_and_alert_numbering():
    _, _, wf, out = make()
    audits = out["audit_record"]
    extras = [r for r in audits if r["event_type"] == "EMERGENCY_EXTENSION"]
    assert len(audits) == len(wf["audit_record"]) + len(extras)
    assert [int(r["audit_id"].split("-")[-1]) for r in audits] == list(range(1, len(audits) + 1))
    assert all(ids.PATTERNS["audit_id"].match(r["audit_id"]) for r in audits)
    stamps = [r["timestamp"] for r in audits]
    assert stamps == sorted(stamps)

    alerts = out["alert"]
    new = [a for a in alerts if a["alert_type"] == "PROHIBITED_USE"]
    assert len(alerts) == len(wf["alert"]) + len(new)
    assert [int(a["alert_id"].split("-")[-1]) for a in alerts] == list(range(1, len(alerts) + 1))
    assert all(ids.PATTERNS["alert_id"].match(a["alert_id"]) for a in alerts)
    created = [a["created_at"] for a in alerts]
    assert created == sorted(created)


def test_prohibited_uses_raise_alerts():
    _, _, _, out = make()
    violations = {u["use_id"]: u for u in out["production_use"] if u["is_prohibited"]}
    alerts = [a for a in out["alert"] if a["alert_type"] == "PROHIBITED_USE"]
    assert len(alerts) == len(violations)
    assert {a["related_record_id"] for a in alerts} == set(violations)
    for a in alerts:
        u = violations[a["related_record_id"]]
        assert a["asset_id"] == u["asset_id"]
        assert a["created_at"] >= u["used_at"]
        assert a["severity"] in {"HIGH", "CRITICAL"}
        assert a["status"] == "OPEN"


def test_batches_are_derived_from_line_day_and_shift():
    m, _, _, out = make()
    lines = {a["asset_id"]: a["production_line"] for a in m["asset"]}
    groups, top = {}, 0
    for u in out["production_use"]:
        assert re.match(r"^BATCH-\d{6}$", u["batch_id"])
        n = int(u["batch_id"].split("-")[-1])
        assert n <= top + 1                      # numbered in order of first appearance
        top = max(top, n)
        key = (lines[u["asset_id"]], u["used_at"].date(), _shift(u["used_at"].hour))
        groups.setdefault(u["batch_id"], set()).add(key)
    assert all(len(keys) == 1 for keys in groups.values())


def test_inputs_are_not_mutated():
    masters = build_masters("starter")
    events, certs = build_calibrations(masters, "starter")
    wf = build_workflow(masters, events, certs)
    before = copy.deepcopy(wf)
    build_usage(masters, events, wf, "starter")
    assert wf == before


def test_same_seed_same_usage():
    assert make()[3] == make()[3]


def test_full_scale_sanity():
    _, _, _, out = make("full")
    uses = out["production_use"]
    assert len(uses) == 100_000
    assert len({u["use_id"] for u in uses}) == 100_000
    counts = Counter(u["use_status"] for u in uses)
    assert counts["VALID"] / len(uses) > 0.90
    for status in ("OVERDUE_ALLOWED", "OVERDUE_WITH_EXCEPTION", "BLOCKED", "VIOLATION"):
        assert counts[status] > 0, status