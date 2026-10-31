import copy
import inspect
from datetime import timedelta

import pytest

from src.generate import build_dataset
from src.inject import CERT_MISMATCH, DUE_DATE, EXPIRED_USE, NO_IMPACT
from src.validate import STRUCTURAL, all_passed, score_findings, validate_all

TYPES = {DUE_DATE, EXPIRED_USE, CERT_MISMATCH, NO_IMPACT}


def by_key(report):
    return {c["key"]: c["violations"] for c in report["checks"]}


@pytest.fixture(scope="module")
def starter():
    tables, truth = build_dataset("starter")
    return tables, truth, validate_all(tables)


def test_clean_baseline_is_perfect():
    """No false alarms: before injection the robot must find NOTHING."""
    tables, truth = build_dataset("starter", inject=False)
    assert truth == []
    report = validate_all(tables)
    assert all(not v for v in by_key(report).values())
    assert all(not f for f in report["findings"].values())


def test_injected_data_passes_every_structural_check(starter):
    _, _, report = starter
    assert len(report["checks"]) == 1 + len(STRUCTURAL)
    for key, violations in by_key(report).items():
        assert violations == [], (key, violations[:3])


def test_detectors_match_ground_truth_exactly(starter):
    _, truth, report = starter
    scores = score_findings(report["findings"], truth)
    assert {s["anomaly_type"] for s in scores} == TYPES
    for s in scores:
        assert s["truth"] >= 1
        assert (s["false_positives"], s["false_negatives"]) == (0, 0), s
        assert s["precision"] == 1.0 and s["recall"] == 1.0
    assert all_passed(report, scores)


def test_catches_duplicate_primary_key(starter):
    t = copy.deepcopy(starter[0])
    t["supplier"].append(dict(t["supplier"][0]))
    assert by_key(validate_all(t))["keys"]


def test_catches_dangling_foreign_key(starter):
    t = copy.deepcopy(starter[0])
    t["calibration_event"][0]["supplier_id"] = "SUP-999"
    keys = by_key(validate_all(t))["keys"]
    assert any("FOREIGN KEY" in message for _, message in keys)


def test_catches_bad_enum_value(starter):
    t = copy.deepcopy(starter[0])
    t["calibration_event"][0]["result"] = "MAYBE"
    assert by_key(validate_all(t))["enums"]


def test_catches_arithmetic_error(starter):
    t = copy.deepcopy(starter[0])
    t["certificate"][0]["valid_until"] += timedelta(days=1)
    assert by_key(validate_all(t))["arithmetic"]


def test_catches_broken_audit_chain(starter):
    t = copy.deepcopy(starter[0])
    row = next(r for r in t["audit_record"] if r["event_type"] == "ASSET_STATUS_CHANGE")
    row["old_value"] = "WRONG"
    assert by_key(validate_all(t))["audit_trail"]


def test_catches_wrong_use_fields(starter):
    t = copy.deepcopy(starter[0])
    use = next(u for u in t["production_use"] if u["use_status"] == "VALID")
    use["days_overdue"] = 5
    assert by_key(validate_all(t))["use_status"]


def test_same_seed_same_report(starter):
    assert validate_all(build_dataset("starter")[0]) == starter[2]


def test_validator_never_receives_the_answer_key():
    assert list(inspect.signature(validate_all).parameters) == ["tables"]


def test_full_scale_validation():
    tables, truth = build_dataset("full")
    assert len(tables["asset"]) == 2000
    assert len(tables["calibration_event"]) == 5000
    assert len(tables["production_use"]) == 100_000
    report = validate_all(tables)
    scores = score_findings(report["findings"], truth)
    assert all_passed(report, scores)
    assert {s["anomaly_type"]: s["found"] for s in scores} == {t: 40 for t in TYPES}