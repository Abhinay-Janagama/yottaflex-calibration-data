"""Step 6: production-use events (the heaviest step).
Every status is CALCULATED from the asset's calibration windows (rules R2 and R3)."""
import random
from bisect import bisect_right
from datetime import datetime, time, timedelta
from itertools import accumulate

from src import ids
from src.config import (
    SEED,
    SIM_START,
    SIM_END,
    get_scale,
    P_EMERGENCY_EXTENSION,
    INTERLOCK_LINES,
    WEEKEND_FACTOR,
    USE_WEIGHT_BY_CRITICALITY,
    N_OPERATORS,
)
from src.workflow import END_OF_YEAR

HOURS = list(range(24))
HOUR_WEIGHTS = [0.25] * 6 + [1.0] * 16 + [0.25] * 2     # busy 06:00-21:59, quiet at night
HOUR_CUM = list(accumulate(HOUR_WEIGHTS))
N_DAYS = (SIM_END - SIM_START).days + 1
EXTENSION_REASONS = (
    "Awaiting calibration lab slot",
    "Critical production batch in progress",
    "Calibration supplier delay",
    "Spare instrument not available",
)


# ---------- Helpers ----------
def _shift(hour):
    if 6 <= hour < 14:
        return "A"
    if 14 <= hour < 22:
        return "B"
    return "C"


def _segments(chain):
    """The tool's 'report card periods' in 2026.
    Segment 0 = the due date inherited from 2025. Every PASS starts a new segment the next day."""
    if not chain:
        return [{"start": SIM_START, "due": None, "cal_id": None}]
    segs = [{"start": SIM_START, "due": chain[0]["previous_due_date"], "cal_id": None}]
    for e in chain:
        if e["result"] == "PASS":
            segs.append({
                "start": e["calibration_date"] + timedelta(days=1),
                "due": e["next_due_date"],
                "cal_id": e["calibration_id"],
            })
    return segs


def _unavailable(chain):
    """Day ranges when the tool cannot be used: calibration days and quarantine (FAIL -> next PASS)."""
    ranges = []
    quarantine_from = None
    for e in chain:
        d = e["calibration_date"]
        if e["result"] == "FAIL":
            if quarantine_from is None:
                quarantine_from = d
        else:
            if quarantine_from is not None:
                ranges.append((quarantine_from, d))
                quarantine_from = None
            else:
                ranges.append((d, d))
    if quarantine_from is not None:
        ranges.append((quarantine_from, SIM_END))
    return ranges


def _available(profile, day):
    for start, end in profile["off"]:
        if start <= day <= end:
            return False
    return True


def _segment_at(profile, day):
    return profile["segs"][bisect_right(profile["starts"], day) - 1]


# ---------- Emergency extensions ----------
def _extensions(rng, profiles):
    """Some overdue periods get a signed emergency extension. Returns (pairs, audit rows)."""
    pairs, rows = [], []
    for asset_id in sorted(profiles):
        p = profiles[asset_id]
        plan = p["plan"]
        if not plan["block_if_overdue"] or plan["max_extension_days"] == 0:
            continue
        segs = p["segs"]
        for i, seg in enumerate(segs):
            if seg["due"] is None:
                continue
            if i + 1 < len(segs):
                end_excl = segs[i + 1]["start"] - timedelta(days=1)    # the PASS day itself
            else:
                end_excl = SIM_END + timedelta(days=1)
            overdue_start = seg["due"] + timedelta(days=plan["grace_days"] + 1)
            if overdue_start >= end_excl:
                continue                                               # never became overdue
            if rng.random() >= P_EMERGENCY_EXTENSION:
                continue
            days = rng.randint(1, plan["max_extension_days"])
            until = seg["due"] + timedelta(days=plan["grace_days"] + days)
            if until < SIM_START:
                continue
            granted = datetime.combine(max(overdue_start, SIM_START), time(7, 0))
            reason = rng.choice(EXTENSION_REASONS)

            seg["extension_until"] = until
            seg["extension_granted"] = granted
            pairs.append((asset_id, seg))
            rows.append({
                "audit_id": None, "entity_type": "ASSET", "entity_id": asset_id,
                "event_type": "EMERGENCY_EXTENSION",
                "old_value": seg["due"].isoformat(), "new_value": until.isoformat(),
                "extension_until": until, "actor_role": "QUALITY_ENGINEER",
                "timestamp": granted, "reason": reason,
            })
    return pairs, rows


def _merge_audit(base, extra):
    """Add the new logbook lines, sort by time, renumber. Inputs are NOT changed."""
    rows = sorted(base + extra,
                  key=lambda r: (r["timestamp"], r["entity_id"], r["event_type"], r["new_value"]))
    return [{**r, "audit_id": ids.audit_id(i)} for i, r in enumerate(rows, start=1)]


# ---------- The guard: rule R3 ----------
def _classify(profile, seg, used_at):
    day = used_at.date()
    due = seg["due"]
    out = {"calibration_in_force": seg["cal_id"], "due_date_at_use": due,
           "days_overdue": 0, "use_status": "VALID", "is_prohibited": False, "exception_ref": None}
    if due is None:
        return out
    plan = profile["plan"]
    effective = due + timedelta(days=plan["grace_days"])
    if day <= effective:
        return out

    out["days_overdue"] = (day - effective).days
    until = seg.get("extension_until")
    if not plan["block_if_overdue"]:
        out["use_status"] = "OVERDUE_ALLOWED"
    elif until is not None and used_at >= seg["extension_granted"] and day <= until:
        out["use_status"] = "OVERDUE_WITH_EXCEPTION"
        out["exception_ref"] = seg["exception_ref"]
    elif profile["asset"]["production_line"] in INTERLOCK_LINES:
        out["use_status"] = "BLOCKED"
    else:
        out["use_status"] = "VIOLATION"
        out["is_prohibited"] = True
    return out


# ---------- Picking WHEN each use happens ----------
def _pick_moment(rng):
    while True:
        day = SIM_START + timedelta(days=rng.randrange(N_DAYS))
        if day.weekday() < 5 or rng.random() < WEEKEND_FACTOR:
            break
    hour = rng.choices(HOURS, cum_weights=HOUR_CUM, k=1)[0]
    return datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)))


def _uses(rng, profiles, n_uses):
    aid_list = sorted(profiles)
    cum = list(accumulate(
        USE_WEIGHT_BY_CRITICALITY[profiles[a]["asset"]["criticality"]] for a in aid_list))

    seen, raw = set(), []
    while len(raw) < n_uses:
        aid = rng.choices(aid_list, cum_weights=cum, k=1)[0]
        moment = _pick_moment(rng)
        if not _available(profiles[aid], moment.date()):
            continue                                   # tool was away: try again
        if (aid, moment) in seen:
            continue                                   # same tool, same second: try again
        seen.add((aid, moment))
        raw.append((moment, aid))
    raw.sort()                                         # time order, then asset

    uses, batch_numbers, batch_counter = [], {}, ids.Counter()
    for moment, aid in raw:
        p = profiles[aid]
        day = moment.date()
        verdict = _classify(p, _segment_at(p, day), moment)

        key = (p["asset"]["production_line"], day, _shift(moment.hour))
        if key not in batch_numbers:
            batch_numbers[key] = batch_counter.next()

        uses.append({
            "use_id": ids.use_id(aid, moment),
            "asset_id": aid,
            "used_at": moment,
            "operator_code": ids.operator_code(rng.randint(1, N_OPERATORS)),
            "batch_id": ids.batch_id(batch_numbers[key]),
            **verdict,
        })
    return uses


# ---------- Alerts for prohibited uses ----------
def _merge_alerts(base, uses, assets):
    extra = []
    for u in uses:
        if u["is_prohibited"]:
            crit = assets[u["asset_id"]]["criticality"]
            extra.append({
                "alert_id": None, "asset_id": u["asset_id"], "alert_type": "PROHIBITED_USE",
                "severity": "CRITICAL" if crit == "HIGH" else "HIGH",
                "related_record_id": u["use_id"],
                "created_at": min(u["used_at"] + timedelta(minutes=10), END_OF_YEAR),
                "status": "OPEN",
            })
    rows = sorted(base + extra,
                  key=lambda a: (a["created_at"], a["related_record_id"], a["alert_type"]))
    return [{**a, "alert_id": ids.alert_id(i)} for i, a in enumerate(rows, start=1)]


# ---------- The function everyone calls ----------
def build_usage(masters: dict, events: list, workflow: dict,
                scale_name: str = "starter", seed: int = SEED) -> dict:
    scale = get_scale(scale_name)
    assets = {a["asset_id"]: a for a in masters["asset"]}
    plans = {p["plan_id"]: p for p in masters["calibration_plan"]}

    chains = {}
    for e in events:
        chains.setdefault(e["asset_id"], []).append(e)

    profiles = {}
    for aid in sorted(assets):
        chain = chains.get(aid, [])
        segs = _segments(chain)
        profiles[aid] = {
            "asset": assets[aid], "plan": plans[assets[aid]["plan_id"]],
            "segs": segs, "starts": [s["start"] for s in segs], "off": _unavailable(chain),
        }

    # 1) emergency extensions -> merged into the logbook -> each segment learns its AUD- id
    pairs, ext_rows = _extensions(random.Random(f"{seed}-extensions"), profiles)
    audit = _merge_audit(workflow["audit_record"], ext_rows)
    ext_ids = {(r["entity_id"], r["timestamp"]): r["audit_id"]
               for r in audit if r["event_type"] == "EMERGENCY_EXTENSION"}
    for asset_id, seg in pairs:
        seg["exception_ref"] = ext_ids[(asset_id, seg["extension_granted"])]

    # 2) the 100,000 uses, each judged by the guard
    uses = _uses(random.Random(f"{seed}-usage"), profiles, scale.n_uses)

    # 3) alarm bells for prohibited uses
    alerts = _merge_alerts(workflow["alert"], uses, assets)
    return {"production_use": uses, "audit_record": audit, "alert": alerts}


if __name__ == "__main__":
    import sys
    from collections import Counter
    from src.events import build_calibrations
    from src.masters import build_masters
    from src.workflow import build_workflow

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    wf = build_workflow(masters, events, certs)
    out = build_usage(masters, events, wf, name)
    uses = out["production_use"]

    print(f"Scale: {name}")
    print(f"  production uses : {len(uses)}")
    for status, n in sorted(Counter(u["use_status"] for u in uses).items()):
        print(f"    {status:24s} {n:>7}  ({n / len(uses):.2%})")
    ext = sum(r["event_type"] == "EMERGENCY_EXTENSION" for r in out["audit_record"])
    print(f"  emergency extensions : {ext}")
    print(f"  audit records (merged): {len(out['audit_record'])}")
    print(f"  alerts (merged)       : {len(out['alert'])}")
    print(f"  first use : {uses[0]}")