"""Step 4: calibration events and certificates (the heart of the project)."""
import random
from datetime import timedelta
from src import ids
from src.config import (
    SEED,
    SIM_START,
    SIM_END,
    get_scale,
    P_LATE_CALIBRATION,
    P_CERTIFICATE_GAP,
    ERR_SD_ON_TIME,
    ERR_SD_LATE,
    P_BOUNDARY_ERROR,
)

MAX_ATTEMPTS = 60

# ---------- Small helpers ----------
def _pick_date(rng, due, interval, attempt):
    """When does the tool ACTUALLY get checked, compared to its due date?"""
    if rng.random() < P_LATE_CALIBRATION:
        # late: usually a few days, sometimes many (never more than 90)
        offset = min(int(rng.expovariate(1 / 15)) + 1, 90)
    else:
        # on time or a bit early
        offset = -rng.randint(0, min(10 + 2 * attempt, interval // 3))
    return due + timedelta(days=offset)


def _measure(rng, tolerance, days_late):
    """The doctor's measurement: how wrong is the tool?"""
    if rng.random() < P_BOUNDARY_ERROR:
        return tolerance * rng.choice([-1, 1])        # exactly on the limit -> PASS
    wobble = ERR_SD_LATE if days_late > 0 else ERR_SD_ON_TIME
    return round(rng.gauss(0, tolerance * wobble), 5)

# ---------- One tool's diary ----------
def _timeline(rng, asset, plan, tolerance, attempt):
    interval = plan["interval_days"]

    # The due date the tool already had on 1 Jan 2026 (inherited from 2025)
    due = SIM_START + timedelta(days=rng.randint(-20, interval - 1))
    cal_date = _pick_date(rng, due, interval, attempt)
    if cal_date < SIM_START:                      # was already overdue on 1 Jan
        cal_date = SIM_START + timedelta(days=rng.randint(0, 10))

    events = []
    while cal_date <= SIM_END:
        days_late = max(0, (cal_date - due).days)
        error = _measure(rng, tolerance, days_late)
        result = "PASS" if abs(error) <= tolerance else "FAIL"   # DERIVED, not random
        next_due = cal_date + timedelta(days=interval)           # Rule R1

        events.append({
            "asset_id": asset["asset_id"],
            "plan_id": plan["plan_id"],
            "calibration_date": cal_date,
            "previous_due_date": due,
            "days_late": days_late,
            "measured_error": error,
            "tolerance_applied": tolerance,
            "result": result,
            "next_due_date": next_due,
        })

        if result == "PASS":
            due = next_due                         # only a PASS moves the due date (R2)
            cal_date = _pick_date(rng, due, interval, attempt)
        else:
            cal_date = cal_date + timedelta(days=rng.randint(3, 14))   # re-test after repair
    return events

# ---------- The function everyone calls ----------
def build_calibrations(masters: dict, scale_name: str = "starter", seed: int = SEED):
    scale = get_scale(scale_name)
    target = scale.n_calibrations
    types = {t["instrument_type_id"]: t for t in masters["instrument_type"]}
    plans = {p["plan_id"]: p for p in masters["calibration_plan"]}
    suppliers = masters["supplier"]
    assets = masters["asset"]

    # 1) Build every tool's diary. If we end up with too FEW events, try again
    #    with tools being checked a little earlier. (Same seed -> same result.)
    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}-calibration-{attempt}")
        chains = {}
        for a in assets:
            plan = plans[a["plan_id"]]
            tolerance = types[a["instrument_type_id"]]["tolerance"]
            chains[a["asset_id"]] = _timeline(rng, a, plan, tolerance, attempt)
        total = sum(len(c) for c in chains.values())
        if total >= target:
            break
    else:
        raise RuntimeError("Could not reach the target number of calibrations")

    # 2) Too MANY? Remove the LAST event of randomly chosen tools (history stays valid).
    while total > target:
        candidates = [aid for aid in sorted(chains) if len(chains[aid]) >= 2]
        chains[rng.choice(candidates)].pop()
        total -= 1

    # 3) Put everything in time order, then hand out IDs 1, 2, 3 ... (global + chronological)
    flat = [e for aid in sorted(chains) for e in chains[aid]]
    flat.sort(key=lambda e: (e["calibration_date"], e["asset_id"]))

    counter = ids.Counter()
    events, certificates = [], []
    for e in flat:
        cal_id = ids.calibration_id(e["asset_id"], counter.next())
        supplier = rng.choice(suppliers)
        has_gap = rng.random() < P_CERTIFICATE_GAP     # the report card got lost

        cert_id = None
        if not has_gap:
            cert_id = ids.certificate_id(cal_id)
            certificates.append({
                "certificate_id": cert_id,
                "calibration_id": cal_id,
                "asset_id": e["asset_id"],
                "supplier_id": supplier["supplier_id"],
                "issue_date": e["calibration_date"]
                + timedelta(days=rng.randint(0, supplier["avg_turnaround_days"])),
                "valid_until": e["next_due_date"],
                "result": e["result"],
                "status": "ISSUED",
            })

        events.append({
            "calibration_id": cal_id,
            "asset_id": e["asset_id"],
            "plan_id": e["plan_id"],
            "supplier_id": supplier["supplier_id"],
            "calibration_date": e["calibration_date"],
            "previous_due_date": e["previous_due_date"],
            "days_late": e["days_late"],
            "measured_error": e["measured_error"],
            "tolerance_applied": e["tolerance_applied"],
            "result": e["result"],
            "next_due_date": e["next_due_date"],
            "certificate_id": cert_id,
        })
    return events, certificates

if __name__ == "__main__":
    import sys
    from src.masters import build_masters

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    events, certs = build_calibrations(build_masters(name), name)
    n = len(events)
    fails = sum(e["result"] == "FAIL" for e in events)
    late = sum(e["days_late"] > 0 for e in events)
    print(f"Scale: {name}")
    print(f"  calibration events : {n}")
    print(f"  certificates       : {len(certs)}  (gaps: {n - len(certs)})")
    print(f"  FAIL rate          : {fails / n:.1%}")
    print(f"  late rate          : {late / n:.1%}")
    print(f"  first event        : {events[0]}")