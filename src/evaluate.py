"""Step 9: dataset statistics ("evaluation metrics").
Every number is computed from the TABLES. The answer key is used only to score the
detectors and to count the injected cases. It never changes a statistic."""
import json
import statistics
from collections import Counter
from datetime import timedelta
from pathlib import Path

from src.config import SEED
from src.inject import CERT_MISMATCH, DUE_DATE, EXPIRED_USE, NO_IMPACT
from src.validate import all_passed, format_report, score_findings, validate_all


# ---------- Small helpers ----------
def _rate(part, whole):
    return round(part / whole, 4) if whole else 0.0


def _counts(counter):
    return dict(sorted(counter.items()))


def _shares(counter, total):
    return {k: _rate(v, total) for k, v in sorted(counter.items())}


def _percentile(values, p):
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def _spread(values):
    return {"min": min(values), "mean": round(statistics.mean(values), 2), "max": max(values)}


# ---------- 1. Calibration events ----------
def calibration_metrics(t):
    events = t["calibration_event"]
    plans = {p["plan_id"]: p for p in t["calibration_plan"]}
    n = len(events)
    late = [e for e in events if e["days_late"] > 0]
    on_time = [e for e in events if e["days_late"] == 0]
    late_days = [e["days_late"] for e in late]
    gaps = sum(e["certificate_id"] is None for e in events)
    per_asset = Counter(e["asset_id"] for e in events)
    by_interval = Counter(plans[e["plan_id"]]["interval_days"] for e in events)

    def fail_rate(rows):
        return _rate(sum(e["result"] == "FAIL" for e in rows), len(rows))

    return {
        "events": n,
        "fail_rate": fail_rate(events),
        "fail_rate_on_time": fail_rate(on_time),
        "fail_rate_late": fail_rate(late),
        "late_rate": _rate(len(late), n),
        "late_beyond_grace_rate": _rate(
            sum(e["days_late"] > plans[e["plan_id"]]["grace_days"] for e in events), n),
        "days_late_mean": round(statistics.mean(late_days), 1) if late_days else 0.0,
        "days_late_p50": _percentile(late_days, 50),
        "days_late_p90": _percentile(late_days, 90),
        "days_late_max": max(late_days) if late_days else 0,
        "certificates_issued": n - gaps,
        "certificate_gap_rate": _rate(gaps, n),
        "boundary_cases_exactly_at_tolerance": sum(
            abs(e["measured_error"]) == e["tolerance_applied"] for e in events),
        "events_per_asset": _spread([per_asset.get(a["asset_id"], 0) for a in t["asset"]]),
        "events_by_interval_days": {f"{k}_days": v for k, v in sorted(by_interval.items())},
    }


# ---------- 2. Production use ----------
def usage_metrics(t):
    uses = t["production_use"]
    n = len(uses)
    assets = {a["asset_id"]: a for a in t["asset"]}
    status = Counter(u["use_status"] for u in uses)
    overdue_days = [u["days_overdue"] for u in uses if u["days_overdue"] > 0]
    per_asset = Counter(u["asset_id"] for u in uses)
    assets_by_crit = Counter(a["criticality"] for a in t["asset"])
    uses_by_crit = Counter(assets[u["asset_id"]]["criticality"] for u in uses)
    weekend = sum(u["used_at"].weekday() >= 5 for u in uses)
    night = sum(u["used_at"].hour < 6 or u["used_at"].hour >= 22 for u in uses)
    blocking_overdue = (status["OVERDUE_WITH_EXCEPTION"] + status["BLOCKED"] + status["VIOLATION"])

    return {
        "uses": n,
        "status_counts": _counts(status),
        "status_shares": _shares(status, n),
        "overdue_rate": _rate(len(overdue_days), n),
        "days_overdue_p50": _percentile(overdue_days, 50),
        "days_overdue_max": max(overdue_days) if overdue_days else 0,
        "extension_cover_rate_of_blocked_overdue_uses": _rate(
            status["OVERDUE_WITH_EXCEPTION"], blocking_overdue),
        "weekend_share": _rate(weekend, n),
        "night_share": _rate(night, n),
        "uses_per_asset": _spread([per_asset.get(a["asset_id"], 0) for a in t["asset"]]),
        "assets_never_used": len(t["asset"]) - len(per_asset),
        "uses_per_asset_by_criticality": {
            c: round(uses_by_crit[c] / assets_by_crit[c], 1) for c in sorted(assets_by_crit)},
        "uses_by_line": _counts(Counter(assets[u["asset_id"]]["production_line"] for u in uses)),
    }


# ---------- 3. Work orders, downtime, alerts, logbook ----------
def workflow_metrics(t):
    wos = t["work_order"]
    corrective = [w for w in wos if w["work_type"] == "CORRECTIVE_ACTION"]
    impact = [w for w in wos if w["work_type"] == "IMPACT_ASSESSMENT"]
    types = Counter(w["work_type"] for w in wos)
    return {
        "work_orders_by_type": _counts(types),
        "work_orders_by_status": _counts(Counter(w["status"] for w in wos)),
        "downtime_hours_total": round(sum(w["downtime_hours"] for w in wos), 1),
        "downtime_hours_by_type": {
            ty: round(sum(w["downtime_hours"] for w in wos if w["work_type"] == ty), 1)
            for ty in sorted(types)},
        "corrective_downtime_hours_mean": round(
            statistics.mean(w["downtime_hours"] for w in corrective), 1) if corrective else 0.0,
        "repairs_unfinished_at_year_end": sum(w["status"] != "COMPLETED" for w in corrective),
        "impact_assessments_unfinished_at_year_end": sum(w["status"] != "COMPLETED" for w in impact),
        "alerts_by_type": _counts(Counter(a["alert_type"] for a in t["alert"])),
        "alerts_by_severity": _counts(Counter(a["severity"] for a in t["alert"])),
        "alerts_by_status": _counts(Counter(a["status"] for a in t["alert"])),
        "audit_records_by_event_type": _counts(Counter(r["event_type"] for r in t["audit_record"])),
        "final_asset_status": _counts(Counter(a["current_status"] for a in t["asset"])),
    }


# ---------- 4. Coverage: normal, boundary, failure, exception ----------
def coverage(t, truth):
    events, uses = t["calibration_event"], t["production_use"]
    assets = {a["asset_id"]: a for a in t["asset"]}
    plans = {p["plan_id"]: p for p in t["calibration_plan"]}
    status = Counter(u["use_status"] for u in uses)

    last_valid_day = in_grace = overdue_by_one = 0
    for u in uses:
        due = u["due_date_at_use"]
        if due is None:
            continue
        grace = plans[assets[u["asset_id"]]["plan_id"]]["grace_days"]
        day = u["used_at"].date()
        if day == due + timedelta(days=grace):
            last_valid_day += 1                      # the very last day it is still valid
        if grace > 0 and due < day <= due + timedelta(days=grace):
            in_grace += 1                            # after the due date, but inside grace
        if u["days_overdue"] == 1:
            overdue_by_one += 1                      # the first day it is overdue

    rows = []

    def add(category, scenario, count):
        rows.append({"category": category, "scenario": scenario,
                     "count": count, "covered": count > 0})

    corrective = [w for w in t["work_order"] if w["work_type"] == "CORRECTIVE_ACTION"]
    add("Normal", "Calibration passed on time", sum(e["result"] == "PASS" and e["days_late"] == 0 for e in events))
    add("Normal", "Calibration with a certificate issued", sum(e["certificate_id"] is not None for e in events))
    add("Normal", "Use inside the valid window (VALID)", status["VALID"])

    add("Boundary", "Measured error exactly at the tolerance (must PASS)",
        sum(abs(e["measured_error"]) == e["tolerance_applied"] for e in events))
    add("Boundary", "Use on the last valid day (due date + grace)", last_valid_day)
    add("Boundary", "Use after the due date but inside the grace period", in_grace)
    add("Boundary", "Use overdue by exactly 1 day", overdue_by_one)

    add("Failure", "Calibration FAILED", sum(e["result"] == "FAIL" for e in events))
    add("Failure", "Corrective-action work order with downtime", sum(w["downtime_hours"] > 0 for w in corrective))
    add("Failure", "Repair still unfinished at year end", sum(w["status"] != "COMPLETED" for w in corrective))
    add("Failure", "Asset still QUARANTINED at year end", sum(a["current_status"] == "QUARANTINED" for a in t["asset"]))
    add("Failure", "Certificate gap (calibration without certificate)", sum(e["certificate_id"] is None for e in events))

    add("Exception", "Overdue use allowed by plan policy (OVERDUE_ALLOWED)", status["OVERDUE_ALLOWED"])
    add("Exception", "Overdue use covered by emergency extension", status["OVERDUE_WITH_EXCEPTION"])
    add("Exception", "Overdue use stopped by the interlock (BLOCKED)", status["BLOCKED"])
    add("Exception", "Prohibited use that went ahead (VIOLATION)", status["VIOLATION"])
    add("Exception", "Emergency extension recorded in the logbook",
        sum(r["event_type"] == "EMERGENCY_EXTENSION" for r in t["audit_record"]))
    if truth:
        injected = Counter(r["anomaly_type"] for r in truth)
        for a_type in (DUE_DATE, EXPIRED_USE, CERT_MISMATCH, NO_IMPACT):
            add("Exception", f"Injected anomaly: {a_type}", injected[a_type])
    return rows


# ---------- 5. Realism checks (ranges are documented assumptions) ----------
def realism_checks(t, cal, use):
    checks = []

    def add(name, value, expected, ok):
        checks.append({"check": name, "value": value, "expected": expected, "ok": bool(ok)})

    per_crit = use["uses_per_asset_by_criticality"]
    add("Calibration FAIL rate", cal["fail_rate"], "3% to 12%", 0.03 <= cal["fail_rate"] <= 0.12)
    add("Late calibration rate", cal["late_rate"], "5% to 40%", 0.05 <= cal["late_rate"] <= 0.40)
    add("Certificate gap rate", cal["certificate_gap_rate"], "above 0% and at most 6%",
        0 < cal["certificate_gap_rate"] <= 0.06)
    add("Late tools fail more than on-time tools",
        f"{cal['fail_rate_late']} vs {cal['fail_rate_on_time']}", "late > on-time",
        cal["fail_rate_late"] > cal["fail_rate_on_time"])
    add("At least 3 different calibration intervals in use", len(cal["events_by_interval_days"]),
        "3 or more", len(cal["events_by_interval_days"]) >= 3)
    add("VALID share of production uses", use["status_shares"].get("VALID", 0.0), "above 90%",
        use["status_shares"].get("VALID", 0.0) > 0.90)
    add("VIOLATION share of production uses", use["status_shares"].get("VIOLATION", 0.0), "below 2%",
        use["status_shares"].get("VIOLATION", 0.0) < 0.02)
    add("Weekday share of production uses", round(1 - use["weekend_share"], 4), "above 85%",
        1 - use["weekend_share"] > 0.85)
    add("Critical assets are used more than low-criticality ones",
        f"HIGH {per_crit.get('HIGH', 0)} vs LOW {per_crit.get('LOW', 0)} uses per asset",
        "HIGH > LOW", per_crit.get("HIGH", 0) > per_crit.get("LOW", 0))
    add("Every production line has uses", len(use["uses_by_line"]), "12 lines", len(use["uses_by_line"]) == 12)
    add("Assets that were never used", use["assets_never_used"], "at most 5% of assets",
        use["assets_never_used"] <= 0.05 * len(t["asset"]))
    return checks


# ---------- The function everyone calls ----------
def evaluate_dataset(tables, truth):
    """Returns (result dict, plain-text validator output). `truth` is used only for scoring."""
    report = validate_all(tables)
    scores = score_findings(report["findings"], truth)
    cal, use, wf = calibration_metrics(tables), usage_metrics(tables), workflow_metrics(tables)
    result = {
        "volume": {name: len(rows) for name, rows in tables.items()},
        "calibration": cal,
        "usage": use,
        "workflow": wf,
        "coverage": coverage(tables, truth),
        "realism": realism_checks(tables, cal, use),
        "detection": scores,
        "structure": [{"check": c["name"], "violations": len(c["violations"])} for c in report["checks"]],
        "all_passed": all_passed(report, scores),
    }
    return result, format_report(report, scores, "")


# ---------- Writing the report ----------
def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
    return "\n".join(lines)


def _flatten(d, prefix=""):
    out = []
    for key, value in d.items():
        if isinstance(value, dict):
            out += _flatten(value, f"{prefix}{key}.")
        else:
            out.append((f"{prefix}{key}", value))
    return out


def _kv(d):
    return _md_table(["metric", "value"], _flatten(d))


def render_markdown(result, scale_name, validation_text):
    verdict = "ALL CHECKS PASSED" if result["all_passed"] else "PROBLEMS FOUND"
    parts = [
        "# Validation summary", "",
        f"Scale: `{scale_name}` | Seed: `{SEED}` | Result: **{verdict}**", "",
        "Generated by `python -m src.evaluate`. Every number is computed from the generated tables. "
        "The answer key (ground truth) is used only to score the anomaly detectors and to count injected cases.", "",
        "## Dataset volume", "", _kv(result["volume"]), "",
        "## Calibration events", "", _kv(result["calibration"]), "",
        "## Production use", "", _kv(result["usage"]), "",
        "## Workflow, downtime and alerts", "", _kv(result["workflow"]), "",
        "## Coverage of normal, boundary, failure and exception cases", "",
        _md_table(["category", "scenario", "count", "covered"],
                  [(c["category"], c["scenario"], c["count"], "yes" if c["covered"] else "NO")
                   for c in result["coverage"]]), "",
        "## Realism checks", "",
        _md_table(["check", "value", "expected", "result"],
                  [(c["check"], c["value"], c["expected"], "PASS" if c["ok"] else "FAIL")
                   for c in result["realism"]]), "",
        "## Anomaly detection (scored against ground truth)", "",
        _md_table(["anomaly type", "truth", "found", "TP", "FP", "FN", "precision", "recall"],
                  [(s["anomaly_type"], s["truth"], s["found"], s["true_positives"],
                    s["false_positives"], s["false_negatives"],
                    f"{s['precision']:.2f}", f"{s['recall']:.2f}") for s in result["detection"]]), "",
        "## Structure checks", "",
        _md_table(["check", "violations", "result"],
                  [(c["check"], c["violations"], "PASS" if c["violations"] == 0 else "FAIL")
                   for c in result["structure"]]), "",
        "## Full validator output", "", "```", validation_text, "```",
    ]
    return "\n".join(parts) + "\n"


def write_reports(result, markdown, folder):
    """validation_summary.md (for people) and metrics.json (for programs). LF line endings."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    md_path, json_path = folder / "validation_summary.md", folder / "metrics.json"
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown)
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    return md_path, json_path


if __name__ == "__main__":
    import sys

    from src.generate import build_dataset

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    tables, truth = build_dataset(name)
    result, text = evaluate_dataset(tables, truth)
    md_path, json_path = write_reports(result, render_markdown(result, name, text),
                                       Path("data") / f"preview_{name}")

    cal, use = result["calibration"], result["usage"]
    print(f"Scale: {name}")
    print(f"  calibration events : {cal['events']}   FAIL {cal['fail_rate']:.1%}   "
          f"late {cal['late_rate']:.1%}   certificate gaps {cal['certificate_gap_rate']:.1%}")
    print(f"  production uses    : {use['uses']}   statuses {use['status_counts']}")
    covered = sum(c["covered"] for c in result["coverage"])
    print(f"  coverage           : {covered} of {len(result['coverage'])} scenarios present")
    for c in result["coverage"]:
        if not c["covered"]:
            print(f"      missing: [{c['category']}] {c['scenario']}")
    ok = sum(c["ok"] for c in result["realism"])
    print(f"  realism checks     : {ok} of {len(result['realism'])} passed")
    for c in result["realism"]:
        if not c["ok"]:
            print(f"      failed : {c['check']} (value {c['value']}, expected {c['expected']})")
    for s in result["detection"]:
        print(f"  detector {s['anomaly_type']:46s} precision {s['precision']:.2f}  recall {s['recall']:.2f}")
    print(f"  overall            : {'ALL CHECKS PASSED' if result['all_passed'] else 'PROBLEMS FOUND'}")
    print(f"  written: {md_path}")
    print(f"  written: {json_path}")