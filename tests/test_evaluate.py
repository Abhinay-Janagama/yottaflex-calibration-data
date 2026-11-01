import json
from collections import Counter
import pytest
from src.config import get_scale
from src.evaluate import evaluate_dataset, render_markdown, write_reports
from src.generate import build_dataset

@pytest.fixture(scope="module")
def starter():
    tables, truth = build_dataset("starter")
    result, text = evaluate_dataset(tables, truth)
    return tables, truth, result, text


def test_volume_and_rates_match_an_independent_recount(starter):
    tables, _, result, _ = starter
    scale = get_scale("starter")
    assert result["volume"]["asset"] == scale.n_assets
    assert result["volume"]["calibration_event"] == scale.n_calibrations
    assert result["volume"]["production_use"] == scale.n_uses

    events, uses = tables["calibration_event"], tables["production_use"]
    n = len(events)
    fails = sum(e["result"] == "FAIL" for e in events)
    assert result["calibration"]["fail_rate"] == round(fails / n, 4)
    assert result["calibration"]["late_rate"] == round(sum(e["days_late"] > 0 for e in events) / n, 4)
    assert result["calibration"]["certificate_gap_rate"] == round(
        sum(e["certificate_id"] is None for e in events) / n, 4)
    assert result["usage"]["status_counts"] == dict(sorted(Counter(u["use_status"] for u in uses).items()))
    assert result["workflow"]["work_orders_by_type"]["CORRECTIVE_ACTION"] == fails


def test_status_shares_add_up(starter):
    _, _, result, _ = starter
    usage = result["usage"]
    assert sum(usage["status_counts"].values()) == get_scale("starter").n_uses
    assert abs(sum(usage["status_shares"].values()) - 1) < 0.001


def test_metrics_do_not_depend_on_the_answer_key(starter):
    tables, _, result, _ = starter
    blind, _ = evaluate_dataset(tables, [])
    for key in ("volume", "calibration", "usage", "workflow", "realism"):
        assert blind[key] == result[key]


def test_clean_baseline_evaluates_clean():
    tables, truth = build_dataset("starter", inject=False)
    result, _ = evaluate_dataset(tables, truth)
    assert result["all_passed"]
    assert all(s["found"] == 0 for s in result["detection"])
    assert all(c["violations"] == 0 for c in result["structure"])


def test_injected_dataset_is_fully_detected(starter):
    _, _, result, _ = starter
    assert result["all_passed"]
    assert len(result["detection"]) == 4
    for s in result["detection"]:
        assert s["truth"] >= 1
        assert (s["false_positives"], s["false_negatives"]) == (0, 0)


def test_result_is_json_serializable_and_deterministic(starter):
    tables, truth, result, _ = starter
    json.dumps(result)
    again, _ = evaluate_dataset(build_dataset("starter")[0], truth)
    assert again == result


def test_markdown_report_and_files(starter, tmp_path):
    _, _, result, text = starter
    md = render_markdown(result, "starter", text)
    for heading in ("# Validation summary", "## Calibration", "## Production use", "## Coverage",
                    "## Realism", "## Anomaly detection"):
        assert heading in md
    assert md == render_markdown(result, "starter", text)
    md_path, json_path = write_reports(result, md, tmp_path)
    assert md_path.read_text(encoding="utf-8") == md
    assert json.loads(json_path.read_text(encoding="utf-8")) == json.loads(json.dumps(result))


def test_coverage_table_shape(starter):
    _, _, result, _ = starter
    rows = result["coverage"]
    assert {r["category"] for r in rows} == {"Normal", "Boundary", "Failure", "Exception"}
    for r in rows:
        assert set(r) == {"category", "scenario", "count", "covered"}
        assert r["covered"] == (r["count"] > 0)
    injected = [r for r in rows if r["scenario"].startswith("Injected anomaly")]
    assert len(injected) == 4


def test_full_scale_realism_and_coverage():
    tables, truth = build_dataset("full")
    result, _ = evaluate_dataset(tables, truth)
    assert result["volume"]["asset"] == 2000
    assert result["volume"]["calibration_event"] == 5000
    assert result["volume"]["production_use"] == 100_000
    assert [c["scenario"] for c in result["coverage"] if not c["covered"]] == []
    assert [c["check"] for c in result["realism"] if not c["ok"]] == []
    assert result["all_passed"]