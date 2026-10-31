from src import ids
from src.config import SIM_START, SIM_END, get_scale
from src.events import build_calibrations
from src.masters import build_masters

def make(name="starter"):
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    return masters, events, certs

def by_asset(events):
    groups = {}
    for e in events:
        groups.setdefault(e["asset_id"], []).append(e)
    return groups

def test_exact_event_count():
    _, events, _ = make()
    assert len(events) == get_scale("starter").n_calibrations

def test_ids_unique_well_formed_and_chronological():
    _, events, _ = make()
    cal_ids = [e["calibration_id"] for e in events]
    assert len(cal_ids) == len(set(cal_ids))
    for e in events:
        assert ids.PATTERNS["calibration_id"].match(e["calibration_id"])
        assert ids.asset_from_calibration_id(e["calibration_id"]) == e["asset_id"]
    numbers = [int(c.split("-")[-1]) for c in cal_ids]
    assert numbers == list(range(1, len(events) + 1))
    dates = [e["calibration_date"] for e in events]
    assert dates == sorted(dates)

def test_foreign_keys_resolve():
    m, events, _ = make()
    assets = {a["asset_id"]: a for a in m["asset"]}
    suppliers = {s["supplier_id"] for s in m["supplier"]}
    for e in events:
        assert e["asset_id"] in assets
        assert e["supplier_id"] in suppliers
        assert e["plan_id"] == assets[e["asset_id"]]["plan_id"]


def test_rule_r1_due_dates_are_correct():
    m, events, _ = make()
    plans = {p["plan_id"]: p for p in m["calibration_plan"]}
    for e in events:
        interval = plans[e["plan_id"]]["interval_days"]
        assert (e["next_due_date"] - e["calibration_date"]).days == interval

def test_results_and_days_late_are_derived():
    m, events, _ = make()
    assets = {a["asset_id"]: a for a in m["asset"]}
    types = {t["instrument_type_id"]: t for t in m["instrument_type"]}
    for e in events:
        tol = types[assets[e["asset_id"]]["instrument_type_id"]]["tolerance"]
        assert e["tolerance_applied"] == tol
        expected = "PASS" if abs(e["measured_error"]) <= tol else "FAIL"
        assert e["result"] == expected
        late = max(0, (e["calibration_date"] - e["previous_due_date"]).days)
        assert e["days_late"] == late

def test_certificates_reconcile_with_events():
    _, events, certs = make()
    cert_by_id = {c["certificate_id"]: c for c in certs}
    assert len(cert_by_id) == len(certs)
    gaps = 0
    for e in events:
        if e["certificate_id"] is None:
            gaps += 1
            continue
        c = cert_by_id[e["certificate_id"]]
        assert c["certificate_id"] == "CERT-" + e["calibration_id"]
        assert c["calibration_id"] == e["calibration_id"]
        assert c["asset_id"] == e["asset_id"]
        assert c["supplier_id"] == e["supplier_id"]
        assert c["result"] == e["result"]
        assert c["valid_until"] == e["next_due_date"]
        assert c["issue_date"] >= e["calibration_date"]
        assert c["status"] == "ISSUED"
    assert len(certs) + gaps == len(events)

def test_timeline_dates_are_ordered_and_inside_the_year():
    _, events, _ = make()
    for evs in by_asset(events).values():
        dates = [e["calibration_date"] for e in evs]
        assert dates == sorted(dates) and len(dates) == len(set(dates))
        assert all(SIM_START <= d <= SIM_END for d in dates)

def test_previous_due_date_follows_last_pass():
    """Rule R2: only a PASS moves the due date forward."""
    _, events, _ = make()
    for evs in by_asset(events).values():
        in_force = evs[0]["previous_due_date"]
        for e in evs:
            assert e["previous_due_date"] == in_force
            if e["result"] == "PASS":
                in_force = e["next_due_date"]

def test_failed_calibration_is_retested_within_3_to_14_days():
    _, events, _ = make()
    for evs in by_asset(events).values():
        for cur, nxt in zip(evs, evs[1:]):
            if cur["result"] == "FAIL":
                gap = (nxt["calibration_date"] - cur["calibration_date"]).days
                assert 3 <= gap <= 14

def test_same_seed_same_events():
    assert make()[1:] == make()[1:]

def test_full_scale_numbers():
    _, events, certs = make("full")
    n = len(events)
    assert n == 5000
    fail_rate = sum(e["result"] == "FAIL" for e in events) / n
    late_rate = sum(e["days_late"] > 0 for e in events) / n
    gaps = n - len(certs)
    assert 0.03 <= fail_rate <= 0.12
    assert 0.05 <= late_rate <= 0.40
    assert 0 < gaps < 0.06 * n