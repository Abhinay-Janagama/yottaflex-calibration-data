"""Step 7: break a LABELLED sample of the clean data and write the answer key (ground truth)."""
import copy
import csv
import json
import random
from datetime import datetime, time, timedelta
from pathlib import Path

from src import ids
from src.config import ANOMALY_COUNTS, N_OPERATORS, SEED
from src.usage import _segments, _shift, _unavailable

# ---------- The four anomaly types and the decision a good checker should reach ----------
DUE_DATE = "DUE_DATE_INCONSISTENT_WITH_PLAN"
EXPIRED_USE = "EXPIRED_USE_WITHOUT_EXCEPTION"
CERT_MISMATCH = "CERTIFICATE_ASSET_MISMATCH"
NO_IMPACT = "FAILED_CALIBRATION_WITHOUT_IMPACT_ASSESSMENT"

DECISIONS = {
    DUE_DATE: "FLAG_AND_RECOMPUTE_DUE_DATE",
    EXPIRED_USE: "FLAG_PROHIBITED_USE",
    CERT_MISMATCH: "REJECT_CERTIFICATE",
    NO_IMPACT: "CREATE_IMPACT_ASSESSMENT",
}
GT_FIELDS = ["anomaly_id", "anomaly_type", "table_name", "record_id",
             "asset_id", "expected_decision", "reason"]
DUE_DATE_SHIFTS = (-30, -14, -7, 7, 14, 30)      # days wrong; never 0


# ---------- Helpers ----------
def _pick(rng, pool, n):
    """Choose up to n items from a pool, in a repeatable way."""
    pool = sorted(pool)
    return sorted(rng.sample(pool, min(n, len(pool))))


def _label(rows, a_type, table, record_id, asset_id, reason):
    rows.append({
        "anomaly_id": None, "anomaly_type": a_type, "table_name": table,
        "record_id": record_id, "asset_id": asset_id,
        "expected_decision": DECISIONS[a_type], "reason": reason,
    })


def _prohibited_days(assets, plans, chains, ext_until):
    """Every (asset, day) where a use would be PROHIBITED: overdue, plan blocks, no extension,
    and the tool is on the shelf. Built from the CLEAN calibration history."""
    cands = []
    for aid in sorted(chains):
        plan = plans[assets[aid]["plan_id"]]
        if not plan["block_if_overdue"]:
            continue
        chain = chains[aid]
        segs = _segments(chain)
        off = _unavailable(chain)
        for i, seg in enumerate(segs):
            due = seg["due"]
            if due is None:
                continue
            last = segs[i + 1]["start"] - timedelta(days=1) if i + 1 < len(segs) else None
            first = max(seg["start"], due + timedelta(days=plan["grace_days"] + 1))
            until = ext_until.get((aid, due.isoformat()))
            if until is not None:
                first = max(first, until + timedelta(days=1))
            if last is None:
                from src.config import SIM_END
                last = SIM_END
            day = first
            while day <= last:
                if not any(s <= day <= e for s, e in off):
                    cands.append((aid, day, seg["cal_id"], due))
                day += timedelta(days=1)
    return cands


# ---------- The function everyone calls ----------
def inject_edge_cases(masters, events, certificates, work_orders, alerts, audit_records, uses,
                      scale_name="starter", seed=SEED):
    n = ANOMALY_COUNTS[scale_name]
    rng = random.Random(f"{seed}-inject")            # its own dice

    assets = {a["asset_id"]: a for a in masters["asset"]}
    plans = {p["plan_id"]: p for p in masters["calibration_plan"]}

    # Work on COPIES. The clean data is never touched.
    ev = copy.deepcopy(events)
    certs = copy.deepcopy(certificates)
    wos = copy.deepcopy(work_orders)
    audit = copy.deepcopy(audit_records)
    us = copy.deepcopy(uses)
    al = copy.deepcopy(alerts)

    cal_by_id = {e["calibration_id"]: e for e in ev}
    cert_by_cal = {c["calibration_id"]: c for c in certs}
    cert_by_id = {c["certificate_id"]: c for c in certs}
    truth, taken = [], set()          # taken = calibrations that already carry one anomaly

    # ===== Type 4: failed calibration, impact assessment missing =====
    fail_ids = [e["calibration_id"] for e in events if e["result"] == "FAIL"]
    t4 = _pick(rng, fail_ids, n)
    taken.update(t4)
    impact_wo = {w["source_calibration_id"]: w["work_order_id"]
                 for w in wos if w["work_type"] == "IMPACT_ASSESSMENT"}
    removed_wo = {impact_wo[c] for c in t4}
    for cid in t4:
        e = cal_by_id[cid]
        _label(truth, NO_IMPACT, "calibration_event", cid, e["asset_id"],
               f"{cid} FAILED (error {e['measured_error']}, tolerance {e['tolerance_applied']}) "
               f"but no IMPACT_ASSESSMENT work order exists for it")

    # ===== Type 1: due date inconsistent with the plan =====
    referenced = {u["calibration_in_force"] for u in uses if u["calibration_in_force"]}
    last_of_asset = {}
    for e in events:
        last_of_asset[e["asset_id"]] = e["calibration_id"]
    ext_until = {(r["entity_id"], r["old_value"]): r["extension_until"]
                 for r in audit_records if r["event_type"] == "EMERGENCY_EXTENSION"}
    t1_pool = [
        e["calibration_id"] for e in events
        if e["calibration_id"] not in taken
        and (e["asset_id"], e["next_due_date"].isoformat()) not in ext_until
        and (e["result"] == "FAIL"
             or (last_of_asset[e["asset_id"]] == e["calibration_id"]
                 and e["calibration_id"] not in referenced))
    ]
    t1 = _pick(rng, t1_pool, n)
    taken.update(t1)
    for cid in t1:
        e = cal_by_id[cid]
        interval = plans[e["plan_id"]]["interval_days"]
        correct = e["calibration_date"] + timedelta(days=interval)
        e["next_due_date"] = correct + timedelta(days=rng.choice(DUE_DATE_SHIFTS))
        if e["certificate_id"] is not None:
            cert_by_id[e["certificate_id"]]["valid_until"] = e["next_due_date"]
        _label(truth, DUE_DATE, "calibration_event", cid, e["asset_id"],
               f"next_due_date {e['next_due_date']} but calibration_date {e['calibration_date']} "
               f"+ plan interval {interval} days = {correct}")

    # ===== Type 3: certificate refers to another asset =====
    t3 = _pick(rng, [c["calibration_id"] for c in certs if c["calibration_id"] not in taken], n)
    taken.update(t3)
    asset_ids = sorted(assets)
    for cid in t3:
        c = cert_by_cal[cid]
        true_asset = c["asset_id"]
        c["asset_id"] = rng.choice([a for a in asset_ids if a != true_asset])
        _label(truth, CERT_MISMATCH, "certificate", c["certificate_id"], true_asset,
               f"certificate says asset {c['asset_id']} but calibration {cid} belongs to {true_asset}")

    # ===== Type 2: expired tool used, no exception, and NOT flagged =====
    chains = {}
    for e in events:
        chains.setdefault(e["asset_id"], []).append(e)
    cands = [c for c in _prohibited_days(assets, plans, chains, ext_until) if c[2] not in taken]
    picks = rng.sample(cands, min(n, len(cands)))

    existing = {(u["asset_id"], u["used_at"]) for u in us}
    key_to_batch = {}
    for u in us:
        key = (assets[u["asset_id"]]["production_line"], u["used_at"].date(), _shift(u["used_at"].hour))
        key_to_batch.setdefault(key, u["batch_id"])
    next_batch = max(int(u["batch_id"].split("-")[-1]) for u in us) + 1

    new_uses = []
    for aid, day, cal_id, due in picks:
        while True:
            moment = datetime.combine(day, time(rng.randint(6, 21), rng.randrange(60), rng.randrange(60)))
            if (aid, moment) not in existing:
                break
        existing.add((aid, moment))
        grace = plans[assets[aid]["plan_id"]]["grace_days"]
        overdue = (day - (due + timedelta(days=grace))).days
        key = (assets[aid]["production_line"], day, _shift(moment.hour))
        if key not in key_to_batch:
            key_to_batch[key] = ids.batch_id(next_batch)
            next_batch += 1
        row = {
            "use_id": ids.use_id(aid, moment), "asset_id": aid, "used_at": moment,
            "operator_code": ids.operator_code(rng.randint(1, N_OPERATORS)),
            "batch_id": key_to_batch[key],
            "calibration_in_force": cal_id, "due_date_at_use": due, "days_overdue": overdue,
            "use_status": "VALID", "is_prohibited": False, "exception_ref": None,   # the mistake
        }
        new_uses.append(row)
        _label(truth, EXPIRED_USE, "production_use", row["use_id"], aid,
               f"used {overdue} day(s) after due {due} + grace {grace}; plan blocks overdue use and "
               f"no extension covers it, yet the row says VALID and no alert was raised")

    # keep the total at exactly n_uses: drop the same number of ordinary VALID uses
    valid_ids = sorted(u["use_id"] for u in us if u["use_status"] == "VALID")
    drop = set(rng.sample(valid_ids, len(new_uses)))
    us = [u for u in us if u["use_id"] not in drop] + new_uses
    us.sort(key=lambda u: (u["used_at"], u["asset_id"]))

    # ===== Apply type 4: remove the work orders, then renumber so there is no ID gap =====
    wos = [w for w in wos if w["work_order_id"] not in removed_wo]
    wo_map = {}
    for i, w in enumerate(wos, start=1):
        wo_map[w["work_order_id"]] = ids.work_order_id(i)
        w["work_order_id"] = wo_map[w["work_order_id"]]

    kept = []
    for r in audit:
        if r["entity_type"] == "WORKORDER":
            if r["entity_id"] in removed_wo:
                continue                                  # a ticket never created has no logbook lines
            r["entity_id"] = wo_map[r["entity_id"]]
        kept.append(r)
    audit_map = {}
    for i, r in enumerate(kept, start=1):
        audit_map[r["audit_id"]] = ids.audit_id(i)
        r["audit_id"] = audit_map[r["audit_id"]]
    for u in us:
        if u["exception_ref"] is not None:
            u["exception_ref"] = audit_map[u["exception_ref"]]

    # ===== The answer key =====
    truth.sort(key=lambda r: (r["anomaly_type"], r["record_id"]))
    for i, r in enumerate(truth, start=1):
        r["anomaly_id"] = ids.ground_truth_id(i)

    return {
        "calibration_event": ev, "certificate": certs, "work_order": wos, "alert": al,
        "audit_record": kept, "production_use": us, "ground_truth": truth,
    }


def write_ground_truth(rows, folder):
    """Write ground_truth.csv and ground_truth.json (a SEPARATE place from the input tables)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = folder / "ground_truth.csv", folder / "ground_truth.json"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")
    return csv_path, json_path


if __name__ == "__main__":
    import sys
    from collections import Counter

    from src.events import build_calibrations
    from src.masters import build_masters
    from src.usage import build_usage
    from src.workflow import build_workflow

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    wf = build_workflow(masters, events, certs)
    usage = build_usage(masters, events, wf, name)
    inj = inject_edge_cases(masters, events, certs, wf["work_order"], usage["alert"],
                            usage["audit_record"], usage["production_use"], name)

    print(f"Scale: {name}   (requested per type: {ANOMALY_COUNTS[name]})")
    for a_type, k in sorted(Counter(r["anomaly_type"] for r in inj["ground_truth"]).items()):
        print(f"  {a_type:46s} {k:>4}")
    print(f"  production uses (must stay the same): {len(usage['production_use'])} -> {len(inj['production_use'])}")
    print(f"  work orders: {len(wf['work_order'])} -> {len(inj['work_order'])}")
    print(f"  audit records: {len(usage['audit_record'])} -> {len(inj['audit_record'])}")
    csv_path, _ = write_ground_truth(inj["ground_truth"], Path("data") / f"preview_{name}")
    print(f"  answer key written to: {csv_path}")
    print(f"  first answer-key row: {inj['ground_truth'][0]}")