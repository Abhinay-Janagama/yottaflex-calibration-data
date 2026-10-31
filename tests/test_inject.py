import copy
import csv
import json
from collections import Counter
from datetime import timedelta

import pytest

from src import ids
from src.events import build_calibrations
from src.inject import (CERT_MISMATCH, DUE_DATE, EXPIRED_USE, GT_FIELDS, NO_IMPACT,
                        inject_edge_cases, write_ground_truth)
from src.masters import build_masters
from src.usage import build_usage
from src.workflow import build_workflow

TYPES = (DUE_DATE, EXPIRED_USE, CERT_MISMATCH, NO_IMPACT)


def run(name):
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    wf = build_workflow(masters, events, certs)
    usage = build_usage(masters, events, wf, name)
    inj = inject_edge_cases(masters, events, certs, wf["work_order"], usage["alert"],
                            usage["audit_record"], usage["production_use"], name)
    return masters, events, certs, wf, usage, inj


@pytest.fixture(scope="module")
def world():
    return run("starter")


def flagged(inj, a_type):
    return {r["record_id"] for r in inj["ground_truth"] if r["anomaly_type"] == a_type}


def test_ground_truth_shape_and_coverage(world):
    gt = world[5]["ground_truth"]
    counts = Counter(r["anomaly_type"] for r in gt)
    for t in TYPES:
        assert 1 <= counts[t] <= 5, t
    assert set(counts) == set(TYPES)
    gt_ids = [r["anomaly_id"] for r in gt]
    assert len(gt_ids) == len(set(gt_ids))
    assert gt_ids == [ids.ground_truth_id(i) for i in range(1, len(gt) + 1)]
    assert len({(r["anomaly_type"], r["record_id"]) for r in gt}) == len(gt)
    for r in gt:
        assert list(r) == GT_FIELDS
        assert all(isinstance(v, str) and v for v in r.values())


def test_inputs_are_not_mutated(world):
    m, events, certs, wf, usage, _ = world
    args = (events, certs, wf["work_order"], usage["alert"], usage["audit_record"], usage["production_use"])
    before = copy.deepcopy(args)
    inject_edge_cases(m, *args, "starter")
    assert before == args


def test_due_date_anomalies(world):
    m, events, _, _, _, inj = world
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    bad = flagged(inj, DUE_DATE)
    certs = {c["certificate_id"]: c for c in inj["certificate"]}
    for e in inj["calibration_event"]:
        expected = e["calibration_date"] + timedelta(days=plans[e["plan_id"]]["interval_days"])
        if e["calibration_id"] in bad:
            assert e["next_due_date"] != expected
        else:
            assert e["next_due_date"] == expected
        if e["certificate_id"] is not None:
            assert certs[e["certificate_id"]]["valid_until"] == e["next_due_date"]


def test_expired_use_anomalies(world):
    m, _, _, _, usage, inj = world
    assets = {a["asset_id"]: a for a in m["asset"]}
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    uses = {u["use_id"]: u for u in inj["production_use"]}
    alerted = {a["related_record_id"] for a in inj["alert"] if a["alert_type"] == "PROHIBITED_USE"}
    cal_days = {(e["asset_id"], e["calibration_date"]) for e in inj["calibration_event"]}
    extensions = [r for r in inj["audit_record"] if r["event_type"] == "EMERGENCY_EXTENSION"]

    for use_id in flagged(inj, EXPIRED_USE):
        u = uses[use_id]
        plan = plans[assets[u["asset_id"]]["plan_id"]]
        day, due = u["used_at"].date(), u["due_date_at_use"]
        grace = timedelta(days=plan["grace_days"])
        assert plan["block_if_overdue"]
        assert day > due + grace                                   # really expired
        assert not [x for x in extensions if x["entity_id"] == u["asset_id"]
                    and x["old_value"] == due.isoformat() and x["extension_until"] >= day]
        assert (u["use_status"], u["is_prohibited"], u["exception_ref"]) == ("VALID", False, None)
        assert u["days_overdue"] == (day - (due + grace)).days
        assert use_id not in alerted                               # nobody was told
        assert (u["asset_id"], day) not in cal_days

    all_uses = inj["production_use"]
    assert len(all_uses) == len(usage["production_use"])
    assert len({u["use_id"] for u in all_uses}) == len(all_uses)
    assert [(u["used_at"], u["asset_id"]) for u in all_uses] == sorted((u["used_at"], u["asset_id"]) for u in all_uses)
    assert all(ids.PATTERNS["use_id"].match(u["use_id"]) for u in all_uses)


def test_certificate_asset_anomalies(world):
    m, _, _, _, _, inj = world
    asset_ids = {a["asset_id"] for a in m["asset"]}
    bad = flagged(inj, CERT_MISMATCH)
    for c in inj["certificate"]:
        embedded = ids.asset_from_calibration_id(c["calibration_id"])
        assert c["asset_id"] in asset_ids                          # a real asset, just the wrong one
        if c["certificate_id"] in bad:
            assert c["asset_id"] != embedded
        else:
            assert c["asset_id"] == embedded


def test_missing_impact_assessment_anomalies(world):
    _, events, _, _, _, inj = world
    bad = flagged(inj, NO_IMPACT)
    impact = Counter(w["source_calibration_id"] for w in inj["work_order"] if w["work_type"] == "IMPACT_ASSESSMENT")
    corrective = Counter(w["source_calibration_id"] for w in inj["work_order"] if w["work_type"] == "CORRECTIVE_ACTION")
    for e in events:
        cid = e["calibration_id"]
        if e["result"] == "FAIL":
            assert corrective[cid] == 1
            assert impact[cid] == (0 if cid in bad else 1)
        else:
            assert impact[cid] == 0
    assert bad <= {e["calibration_id"] for e in events if e["result"] == "FAIL"}

    # no ID gaps, no dangling pointers after the clean-up
    wo_ids = [w["work_order_id"] for w in inj["work_order"]]
    assert [int(i.split("-")[-1]) for i in wo_ids] == list(range(1, len(wo_ids) + 1))
    audit = inj["audit_record"]
    assert [int(r["audit_id"].split("-")[-1]) for r in audit] == list(range(1, len(audit) + 1))
    assert all(r["entity_id"] in set(wo_ids) for r in audit if r["entity_type"] == "WORKORDER")
    by_id = {r["audit_id"]: r for r in audit}
    for u in inj["production_use"]:
        if u["exception_ref"] is not None:
            r = by_id[u["exception_ref"]]
            assert r["event_type"] == "EMERGENCY_EXTENSION" and r["entity_id"] == u["asset_id"]


def test_everything_else_is_untouched(world):
    _, events, certs, wf, usage, inj = world
    assert inj["alert"] == usage["alert"]
    assert len(inj["calibration_event"]) == len(events)
    assert len(inj["certificate"]) == len(certs)
    assert len(inj["work_order"]) == len(wf["work_order"]) - len(flagged(inj, NO_IMPACT))
    assert len(inj["audit_record"]) <= len(usage["audit_record"])
    changed_events = flagged(inj, DUE_DATE)
    for old, new in zip(events, inj["calibration_event"]):
        if old["calibration_id"] not in changed_events:
            assert old == new
    touched_certs = flagged(inj, CERT_MISMATCH) | {"CERT-" + c for c in changed_events}
    for old, new in zip(certs, inj["certificate"]):
        if old["certificate_id"] not in touched_certs:
            assert old == new


def test_ground_truth_files_and_no_leak(world, tmp_path):
    inj = world[5]
    csv_path, json_path = write_ground_truth(inj["ground_truth"], tmp_path)
    with open(csv_path, newline="", encoding="utf-8") as f:
        assert list(csv.DictReader(f)) == inj["ground_truth"]
    with open(json_path, encoding="utf-8") as f:
        assert json.load(f) == inj["ground_truth"]
    leak = {"anomaly_id", "anomaly_type", "expected_decision"}
    for table in ("calibration_event", "certificate", "work_order", "alert", "audit_record", "production_use"):
        assert leak.isdisjoint(inj[table][0])


def test_same_seed_same_injection(world):
    assert run("starter")[5] == world[5]


def test_full_scale_counts():
    _, _, _, _, usage, inj = run("full")
    counts = Counter(r["anomaly_type"] for r in inj["ground_truth"])
    assert all(counts[t] == 40 for t in TYPES), counts
    assert len(inj["production_use"]) == len(usage["production_use"]) == 100_000
    assert len({u["use_id"] for u in inj["production_use"]}) == 100_000