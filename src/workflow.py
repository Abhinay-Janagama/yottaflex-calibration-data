"""Step 5: work orders, downtime, alerts and audit records (all DERIVED from calibration events)."""
import random
from datetime import datetime, time, timedelta
from src import ids
from src.config import SEED, SIM_END

END_OF_YEAR = datetime.combine(SIM_END, time(23, 59, 59))
RAISE_PRIORITY = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "HIGH"}

# ---------- Small helpers ----------
def _at(day, hour):
    """A date + an hour of the day -> a timestamp."""
    return datetime.combine(day, time(hour, 0))


def _hours(start, end):
    return round((end - start).total_seconds() / 3600, 1)


def _chains(events):
    """Group events by asset, and find which events are RE-TESTS (they follow a FAIL)."""
    by_asset = {}
    for e in events:                       # events are already in time order
        by_asset.setdefault(e["asset_id"], []).append(e)
    retests = set()
    for chain in by_asset.values():
        for prev, cur in zip(chain, chain[1:]):
            if prev["result"] == "FAIL":
                retests.add(cur["calibration_id"])
    return by_asset, retests


def _overdue_severity(days_late):
    if days_late > 30:
        return "HIGH"
    if days_late > 14:
        return "MEDIUM"
    return "LOW"


# ---------- Work orders ----------
def _wo(work_type, e, priority, role, status, created, completed):
    # ONE downtime rule for everything: hours from created to completed
    # (or to the end of the year if still not completed). Impact assessments have none.
    if work_type == "IMPACT_ASSESSMENT":
        downtime = 0.0
    else:
        end = completed if completed is not None else END_OF_YEAR
        downtime = _hours(created, end)
    return {
        "work_order_id": None,             # filled in after sorting
        "asset_id": e["asset_id"],
        "work_type": work_type,
        "source_calibration_id": e["calibration_id"],
        "status": status,
        "priority": priority,
        "assigned_role": role,
        "created_at": created,
        "completed_at": completed,
        "downtime_hours": downtime,
    }


def _work_orders(rng, by_asset, retests, assets):
    drafts = []
    for asset_id in sorted(by_asset):
        crit = assets[asset_id]["criticality"]
        chain = by_asset[asset_id]
        for i, e in enumerate(chain):
            day = e["calibration_date"]
            retest = chain[i + 1] if i + 1 < len(chain) else None

            # (a) every calibration that is NOT a re-test has a routine job ticket
            if e["calibration_id"] not in retests:
                created = _at(day, 6)
                done = created + timedelta(hours=rng.randint(4, 9))
                drafts.append(_wo("ROUTINE_CALIBRATION", e, crit,
                                  "MAINTENANCE_ENGINEER", "COMPLETED", created, done))

            # (b) a FAIL creates the repair ticket AND the impact-assessment ticket (rule R4)
            if e["result"] == "FAIL":
                created = _at(day, 17)
                if retest is not None:
                    gap = (retest["calibration_date"] - day).days      # 3..14 days
                    repair_days = rng.randint(1, gap - 1)
                    done = created + timedelta(days=repair_days, hours=rng.randint(0, 4))
                    status = "COMPLETED"
                else:                                                  # no re-test this year
                    done, status = None, "IN_PROGRESS"
                drafts.append(_wo("CORRECTIVE_ACTION", e, RAISE_PRIORITY[crit],
                                  "MAINTENANCE_ENGINEER", status, created, done))

                created = _at(day, 18)
                done = created + timedelta(days=rng.randint(1, 10))
                if done > END_OF_YEAR:                                 # not finished before year end
                    done, status = None, "OPEN"
                else:
                    status = "COMPLETED"
                drafts.append(_wo("IMPACT_ASSESSMENT", e, RAISE_PRIORITY[crit],
                                  "QUALITY_ENGINEER", status, created, done))

    # time order first, THEN hand out IDs (global + chronological, like CAL)
    drafts.sort(key=lambda w: (w["created_at"], w["asset_id"], w["work_type"]))
    counter = ids.Counter()
    for w in drafts:
        w["work_order_id"] = ids.work_order_id(counter.next())
    return drafts


# ---------- Alerts ----------
def _alerts(events, retests, assets, plans, suppliers, work_orders):
    corrective_done = {
        w["source_calibration_id"]: w["status"] == "COMPLETED"
        for w in work_orders if w["work_type"] == "CORRECTIVE_ACTION"
    }
    last_morning = datetime.combine(SIM_END, time(9, 0))
    drafts = []

    def add(e, kind, severity, created, status):
        drafts.append({
            "alert_id": None, "asset_id": e["asset_id"], "alert_type": kind,
            "severity": severity, "related_record_id": e["calibration_id"],
            "created_at": created, "status": status,
        })

    for e in events:
        asset = assets[e["asset_id"]]
        plan = plans[e["plan_id"]]
        day = e["calibration_date"]

        # late beyond the grace period (re-tests don't count: they are not "scheduled")
        if e["calibration_id"] not in retests and e["days_late"] > plan["grace_days"]:
            add(e, "CALIBRATION_OVERDUE", _overdue_severity(e["days_late"]), _at(day, 16), "RESOLVED")

        if e["result"] == "FAIL":
            severity = "CRITICAL" if asset["criticality"] == "HIGH" else "HIGH"
            status = "RESOLVED" if corrective_done.get(e["calibration_id"]) else "ACKNOWLEDGED"
            add(e, "CALIBRATION_FAILED", severity, _at(day, 16), status)

        # missing certificate is only a problem when the plan REQUIRES one
        if e["certificate_id"] is None and plan["requires_certificate"]:
            wait = suppliers[e["supplier_id"]]["avg_turnaround_days"] + 1
            created = min(_at(day + timedelta(days=wait), 9), last_morning)
            add(e, "CERTIFICATE_MISSING", "MEDIUM", created, "OPEN")

    drafts.sort(key=lambda a: (a["created_at"], a["related_record_id"], a["alert_type"]))
    counter = ids.Counter()
    for a in drafts:
        a["alert_id"] = ids.alert_id(counter.next())
    return drafts


# ---------- Audit records (the logbook: only ever ADDED to) ----------
def _audit(entity_type, entity_id, event_type, old, new, when, role, reason=None):
    return {
        "audit_id": None, "entity_type": entity_type, "entity_id": entity_id,
        "event_type": event_type, "old_value": old, "new_value": new,
        "extension_until": None, "actor_role": role, "timestamp": when, "reason": reason,
    }


def _audit_records(assets, by_asset, certificates, work_orders):
    rows = []

    # every asset is REGISTERED as ACTIVE on its install date (so history starts clean)
    for a in assets.values():
        rows.append(_audit("ASSET", a["asset_id"], "ASSET_STATUS_CHANGE", None, "ACTIVE",
                           _at(a["install_date"], 0), "OT_IT_ADMIN", "Asset registered"))

    # asset status moves: FAIL -> QUARANTINED, then a PASS releases it -> ACTIVE
    for asset_id in sorted(by_asset):
        status = "ACTIVE"
        for e in by_asset[asset_id]:
            when = _at(e["calibration_date"], 16)
            if e["result"] == "FAIL" and status == "ACTIVE":
                rows.append(_audit("ASSET", asset_id, "ASSET_STATUS_CHANGE", "ACTIVE", "QUARANTINED",
                                   when, "QUALITY_ENGINEER", f"Failed calibration {e['calibration_id']}"))
                status = "QUARANTINED"
            elif e["result"] == "PASS" and status == "QUARANTINED":
                rows.append(_audit("ASSET", asset_id, "ASSET_STATUS_CHANGE", "QUARANTINED", "ACTIVE",
                                   when, "QUALITY_ENGINEER", f"Re-test passed {e['calibration_id']}"))
                status = "ACTIVE"

    # certificates
    for c in certificates:
        rows.append(_audit("CERTIFICATE", c["certificate_id"], "CERTIFICATE_ISSUED", None, "ISSUED",
                           _at(c["issue_date"], 10), "QUALITY_ENGINEER"))

    # work-order life: OPEN -> IN_PROGRESS -> COMPLETED
    for w in work_orders:
        wid, role = w["work_order_id"], w["assigned_role"]
        creator = "PRODUCTION_PLANNER" if w["work_type"] == "ROUTINE_CALIBRATION" else "QUALITY_ENGINEER"
        rows.append(_audit("WORKORDER", wid, "WO_STATUS_CHANGE", None, "OPEN",
                           w["created_at"], creator, "Work order created"))
        if w["status"] in ("IN_PROGRESS", "COMPLETED"):
            rows.append(_audit("WORKORDER", wid, "WO_STATUS_CHANGE", "OPEN", "IN_PROGRESS",
                               w["created_at"] + timedelta(hours=1), role))
        if w["status"] == "COMPLETED":
            rows.append(_audit("WORKORDER", wid, "WO_STATUS_CHANGE", "IN_PROGRESS", "COMPLETED",
                               w["completed_at"], role))

    rows.sort(key=lambda r: (r["timestamp"], r["entity_id"], r["event_type"], r["new_value"]))
    counter = ids.Counter()
    for r in rows:
        r["audit_id"] = ids.audit_id(counter.next())
    return rows


# ---------- The function everyone calls ----------
def build_workflow(masters: dict, events: list, certificates: list, seed: int = SEED) -> dict:
    rng = random.Random(f"{seed}-workflow")
    assets = {a["asset_id"]: a for a in masters["asset"]}
    plans = {p["plan_id"]: p for p in masters["calibration_plan"]}
    suppliers = {s["supplier_id"]: s for s in masters["supplier"]}

    by_asset, retests = _chains(events)
    work_orders = _work_orders(rng, by_asset, retests, assets)
    alerts = _alerts(events, retests, assets, plans, suppliers, work_orders)
    audits = _audit_records(assets, by_asset, certificates, work_orders)
    return {"work_order": work_orders, "alert": alerts, "audit_record": audits}


def apply_final_status(assets: list, audit_records: list) -> list:
    """Asset.current_status = the LAST status change in the logbook (history is not overwritten)."""
    latest = {}
    for r in sorted(audit_records, key=lambda r: (r["timestamp"], r["audit_id"])):
        if r["entity_type"] == "ASSET" and r["event_type"] == "ASSET_STATUS_CHANGE":
            latest[r["entity_id"]] = r["new_value"]
    return [{**a, "current_status": latest.get(a["asset_id"], a["current_status"])} for a in assets]


if __name__ == "__main__":
    import sys
    from collections import Counter

    from src.events import build_calibrations
    from src.masters import build_masters

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    masters = build_masters(name)
    events, certs = build_calibrations(masters, name)
    wf = build_workflow(masters, events, certs)
    print(f"Scale: {name}   (calibration events: {len(events)})")
    for table, rows in wf.items():
        print(f"  {table:13s} {len(rows):>6} rows")
    print("  work orders by type :", dict(sorted(Counter(w["work_type"] for w in wf["work_order"]).items())))
    print("  alerts by type      :", dict(sorted(Counter(a["alert_type"] for a in wf["alert"]).items())))
    print("  audit by event type :", dict(sorted(Counter(r["event_type"] for r in wf["audit_record"]).items())))
    final = apply_final_status(masters["asset"], wf["audit_record"])
    print("  final asset status  :", dict(sorted(Counter(a["current_status"] for a in final).items())))