"""Step 8: the checker robot.
It reads the TABLES only (never the answer key): structure checks + four detectors."""
import re
import sqlite3
from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, timedelta

from src import ids
from src.config import INTERLOCK_LINES, SIM_END, SIM_START
from src.inject import CERT_MISMATCH, DUE_DATE, EXPIRED_USE, NO_IMPACT
from src.workflow import END_OF_YEAR

# Parents first, children after (this is also the load order for SQLite)
TABLES = ["supplier", "instrument_type", "calibration_plan", "asset", "calibration_event",
          "certificate", "work_order", "audit_record", "alert", "production_use"]
PK = {
    "supplier": "supplier_id", "instrument_type": "instrument_type_id",
    "calibration_plan": "plan_id", "asset": "asset_id", "calibration_event": "calibration_id",
    "certificate": "certificate_id", "work_order": "work_order_id", "audit_record": "audit_id",
    "alert": "alert_id", "production_use": "use_id",
}

LEVELS = {"LOW", "MEDIUM", "HIGH"}
RESULTS = {"PASS", "FAIL"}
ROLES = {"PLANT_OPERATOR", "MAINTENANCE_ENGINEER", "QUALITY_ENGINEER",
         "PRODUCTION_PLANNER", "OT_IT_ADMIN"}
ENUMS = {
    "instrument_type": {"measurement_unit": {"bar", "degC", "mm", "kg", "V", "A", "Nm", "pH"},
                        "default_criticality": LEVELS},
    "calibration_plan": {"interval_days": {30, 90, 180, 365}, "grace_days": {0, 7, 14}},
    "asset": {"production_line": {f"LINE-{n:02d}" for n in range(1, 13)}, "criticality": LEVELS,
              "current_status": {"ACTIVE", "QUARANTINED", "OUT_OF_SERVICE", "RETIRED"}},
    "calibration_event": {"result": RESULTS},
    "certificate": {"result": RESULTS, "status": {"ISSUED", "REVOKED"}},
    "work_order": {"work_type": {"ROUTINE_CALIBRATION", "CORRECTIVE_ACTION", "IMPACT_ASSESSMENT"},
                   "status": {"OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"},
                   "priority": LEVELS,
                   "assigned_role": {"MAINTENANCE_ENGINEER", "QUALITY_ENGINEER", "PRODUCTION_PLANNER"}},
    "alert": {"alert_type": {"CALIBRATION_OVERDUE", "CALIBRATION_FAILED",
                             "PROHIBITED_USE", "CERTIFICATE_MISSING"},
              "severity": {"LOW", "MEDIUM", "HIGH", "CRITICAL"},
              "status": {"OPEN", "ACKNOWLEDGED", "RESOLVED"}},
    "audit_record": {"entity_type": {"ASSET", "CALIBRATION", "WORKORDER", "CERTIFICATE"},
                     "event_type": {"ASSET_STATUS_CHANGE", "EMERGENCY_EXTENSION",
                                    "WO_STATUS_CHANGE", "CERTIFICATE_ISSUED"},
                     "actor_role": ROLES},
    "production_use": {"use_status": {"VALID", "OVERDUE_ALLOWED", "OVERDUE_WITH_EXCEPTION",
                                      "BLOCKED", "VIOLATION"}},
}
OPERATOR_RE = re.compile(r"^OP-\d{4}$")
BATCH_RE = re.compile(r"^BATCH-\d{6}$")

# ---------- The SQLite schema (PK, UNIQUE and FK are enforced by the database itself) ----------
SCHEMA = """
CREATE TABLE supplier (
  supplier_id TEXT PRIMARY KEY, supplier_name TEXT NOT NULL UNIQUE, country TEXT NOT NULL,
  is_accredited INTEGER NOT NULL, accreditation_standard TEXT, avg_turnaround_days INTEGER NOT NULL);
CREATE TABLE instrument_type (
  instrument_type_id TEXT PRIMARY KEY, type_name TEXT NOT NULL UNIQUE, measurement_unit TEXT NOT NULL,
  range_min REAL NOT NULL, range_max REAL NOT NULL, tolerance REAL NOT NULL,
  default_criticality TEXT NOT NULL);
CREATE TABLE calibration_plan (
  plan_id TEXT PRIMARY KEY,
  instrument_type_id TEXT NOT NULL REFERENCES instrument_type(instrument_type_id),
  interval_days INTEGER NOT NULL, grace_days INTEGER NOT NULL, block_if_overdue INTEGER NOT NULL,
  requires_certificate INTEGER NOT NULL, max_extension_days INTEGER NOT NULL);
CREATE TABLE asset (
  asset_id TEXT PRIMARY KEY,
  instrument_type_id TEXT NOT NULL REFERENCES instrument_type(instrument_type_id),
  plan_id TEXT NOT NULL REFERENCES calibration_plan(plan_id),
  serial_number TEXT NOT NULL UNIQUE, production_line TEXT NOT NULL, install_date TEXT NOT NULL,
  criticality TEXT NOT NULL, current_status TEXT NOT NULL);
CREATE TABLE calibration_event (
  calibration_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES asset(asset_id),
  plan_id TEXT NOT NULL REFERENCES calibration_plan(plan_id),
  supplier_id TEXT NOT NULL REFERENCES supplier(supplier_id),
  calibration_date TEXT NOT NULL, previous_due_date TEXT, days_late INTEGER NOT NULL,
  measured_error REAL NOT NULL, tolerance_applied REAL NOT NULL, result TEXT NOT NULL,
  next_due_date TEXT NOT NULL, certificate_id TEXT UNIQUE);
CREATE TABLE certificate (
  certificate_id TEXT PRIMARY KEY,
  calibration_id TEXT NOT NULL UNIQUE REFERENCES calibration_event(calibration_id),
  asset_id TEXT NOT NULL REFERENCES asset(asset_id),
  supplier_id TEXT NOT NULL REFERENCES supplier(supplier_id),
  issue_date TEXT NOT NULL, valid_until TEXT NOT NULL, result TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE work_order (
  work_order_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES asset(asset_id),
  work_type TEXT NOT NULL,
  source_calibration_id TEXT REFERENCES calibration_event(calibration_id),
  status TEXT NOT NULL, priority TEXT NOT NULL, assigned_role TEXT NOT NULL,
  created_at TEXT NOT NULL, completed_at TEXT, downtime_hours REAL NOT NULL);
CREATE TABLE audit_record (
  audit_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL, old_value TEXT, new_value TEXT NOT NULL, extension_until TEXT,
  actor_role TEXT NOT NULL, timestamp TEXT NOT NULL, reason TEXT);
CREATE TABLE alert (
  alert_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES asset(asset_id),
  alert_type TEXT NOT NULL, severity TEXT NOT NULL, related_record_id TEXT NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE production_use (
  use_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES asset(asset_id),
  used_at TEXT NOT NULL, operator_code TEXT NOT NULL, batch_id TEXT NOT NULL,
  calibration_in_force TEXT REFERENCES calibration_event(calibration_id),
  due_date_at_use TEXT, days_overdue INTEGER NOT NULL, use_status TEXT NOT NULL,
  is_prohibited INTEGER NOT NULL, exception_ref TEXT REFERENCES audit_record(audit_id),
  UNIQUE (asset_id, used_at));
"""


# ---------- Loading into SQLite ----------
def _db(value):
    """Python value -> something SQLite stores (bool before int; datetime before date)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def load_sqlite(tables):
    """Load every table with foreign keys ON. Rows the database REJECTS are reported."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    problems = []
    for table in TABLES:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        rows = [[_db(r[c]) for c in cols] for r in tables[table]]
        try:
            conn.executemany(sql, rows)
        except sqlite3.IntegrityError:
            conn.rollback()                      # slow path: find the exact bad rows
            for row, original in zip(rows, tables[table]):
                try:
                    conn.execute(sql, row)
                except sqlite3.IntegrityError as exc:
                    problems.append((original[PK[table]], f"{table}: {exc}"))
        conn.commit()
    for table, rowid, parent, _ in conn.execute("PRAGMA foreign_key_check"):
        problems.append((f"{table} rowid {rowid}", f"points to a missing row in {parent}"))
    return conn, problems


def _build_index(t):
    chains = {}
    for e in t["calibration_event"]:
        chains.setdefault(e["asset_id"], []).append(e)
    for chain in chains.values():
        chain.sort(key=lambda e: e["calibration_date"])
    return {
        "asset": {a["asset_id"]: a for a in t["asset"]},
        "plan": {p["plan_id"]: p for p in t["calibration_plan"]},
        "itype": {x["instrument_type_id"]: x for x in t["instrument_type"]},
        "event": {e["calibration_id"]: e for e in t["calibration_event"]},
        "cert": {c["certificate_id"]: c for c in t["certificate"]},
        "wo": {w["work_order_id"]: w for w in t["work_order"]},
        "use": {u["use_id"]: u for u in t["production_use"]},
        "chains": chains,
    }


# =====================================================================
#  STRUCTURE CHECKS: each returns a list of (record_id, message). Empty list = PASS.
# =====================================================================
def check_id_formats(t, ix, conn):
    bad = []
    for table in TABLES:
        pk = PK[table]
        for r in t[table]:
            if not ids.PATTERNS[pk].match(r[pk]):
                bad.append((r[pk], f"{table}.{pk} has the wrong shape"))
    for e in t["calibration_event"]:
        if ids.asset_from_calibration_id(e["calibration_id"]) != e["asset_id"]:
            bad.append((e["calibration_id"], "asset inside the calibration ID differs from asset_id"))
    for c in t["certificate"]:
        if c["certificate_id"] != ids.certificate_id(c["calibration_id"]):
            bad.append((c["certificate_id"], "certificate_id is not CERT-<calibration_id>"))
    for u in t["production_use"]:
        if u["use_id"] != ids.use_id(u["asset_id"], u["used_at"]):
            bad.append((u["use_id"], "use_id does not match asset_id and used_at"))
    return bad


def check_references(t, ix, conn):
    """Cross-table consistency, and the 'polymorphic' pointers that SQL foreign keys cannot cover."""
    bad = []
    for a in t["asset"]:
        if ix["plan"][a["plan_id"]]["instrument_type_id"] != a["instrument_type_id"]:
            bad.append((a["asset_id"], "plan belongs to a different instrument type"))
    for e in t["calibration_event"]:
        if e["plan_id"] != ix["asset"][e["asset_id"]]["plan_id"]:
            bad.append((e["calibration_id"], "event plan differs from the asset's plan"))
        if e["certificate_id"] is not None:
            c = ix["cert"].get(e["certificate_id"])
            if c is None or c["calibration_id"] != e["calibration_id"]:
                bad.append((e["calibration_id"], "certificate_id does not point to a certificate that points back"))
    for c in t["certificate"]:
        e = ix["event"][c["calibration_id"]]
        if e["certificate_id"] != c["certificate_id"]:
            bad.append((c["certificate_id"], "the event does not point back to this certificate"))
        if c["supplier_id"] != e["supplier_id"]:
            bad.append((c["certificate_id"], "certificate supplier differs from the event's supplier"))
    for w in t["work_order"]:
        if w["asset_id"] != ix["event"][w["source_calibration_id"]]["asset_id"]:
            bad.append((w["work_order_id"], "work order asset differs from its source calibration's asset"))
    entity_tables = {"ASSET": ix["asset"], "CERTIFICATE": ix["cert"],
                     "WORKORDER": ix["wo"], "CALIBRATION": ix["event"]}
    for r in t["audit_record"]:
        if r["entity_id"] not in entity_tables[r["entity_type"]]:
            bad.append((r["audit_id"], f"entity_id {r['entity_id']} does not exist in {r['entity_type']}"))
    for a in t["alert"]:
        target = ix["use"] if a["alert_type"] == "PROHIBITED_USE" else ix["event"]
        record = target.get(a["related_record_id"])
        if record is None:
            bad.append((a["alert_id"], f"related record {a['related_record_id']} does not exist"))
        elif record["asset_id"] != a["asset_id"]:
            bad.append((a["alert_id"], "alert asset differs from the related record's asset"))
    return bad


def check_enums(t, ix, conn):
    bad = []
    for table, columns in ENUMS.items():
        for r in t[table]:
            for col, allowed in columns.items():
                if r[col] not in allowed:
                    bad.append((r[PK[table]], f"{table}.{col} = {r[col]!r} is not an allowed value"))
    return bad


def check_field_rules(t, ix, conn):
    """Required fields, ranges and 'only if' rules from the data dictionary."""
    bad = []

    def no(record_id, message):
        bad.append((record_id, message))

    for s in t["supplier"]:
        if s["is_accredited"] != (s["accreditation_standard"] == "ISO17025"):
            no(s["supplier_id"], "accreditation_standard must be ISO17025 exactly when accredited")
        if not 1 <= s["avg_turnaround_days"] <= 30:
            no(s["supplier_id"], "avg_turnaround_days outside 1..30")
    for x in t["instrument_type"]:
        if not x["range_min"] < x["range_max"]:
            no(x["instrument_type_id"], "range_min must be below range_max")
        if not x["tolerance"] > 0:
            no(x["instrument_type_id"], "tolerance must be above 0")
    for p in t["calibration_plan"]:
        if not 0 <= p["max_extension_days"] <= 30:
            no(p["plan_id"], "max_extension_days outside 0..30")
        if not p["block_if_overdue"] and p["max_extension_days"] != 0:
            no(p["plan_id"], "a plan that does not block cannot allow extensions")
    for a in t["asset"]:
        if a["install_date"] > SIM_END:
            no(a["asset_id"], "installed after the simulation window")
    for e in t["calibration_event"]:
        if not SIM_START <= e["calibration_date"] <= SIM_END:
            no(e["calibration_id"], "calibration_date outside the simulation window")
        if e["days_late"] < 0 or e["tolerance_applied"] <= 0:
            no(e["calibration_id"], "days_late must be >= 0 and tolerance_applied > 0")
    for w in t["work_order"]:
        if (w["status"] == "COMPLETED") != (w["completed_at"] is not None):
            no(w["work_order_id"], "completed_at must be filled exactly when status is COMPLETED")
        if w["downtime_hours"] < 0:
            no(w["work_order_id"], "downtime_hours below 0")
        if w["source_calibration_id"] is None:
            no(w["work_order_id"], "source_calibration_id is missing")
    for r in t["audit_record"]:
        is_extension = r["event_type"] == "EMERGENCY_EXTENSION"
        if not r["new_value"]:
            no(r["audit_id"], "new_value is empty")
        if is_extension and (r["extension_until"] is None or not r["reason"]):
            no(r["audit_id"], "an emergency extension needs extension_until and a reason")
        if not is_extension and r["extension_until"] is not None:
            no(r["audit_id"], "extension_until is only allowed on EMERGENCY_EXTENSION")
        if is_extension:
            plan = ix["plan"][ix["asset"][r["entity_id"]]["plan_id"]]
            grace_end = date.fromisoformat(r["old_value"]) + timedelta(days=plan["grace_days"])
            limit = grace_end + timedelta(days=plan["max_extension_days"])
            if not (plan["block_if_overdue"] and grace_end < r["extension_until"] <= limit):
                no(r["audit_id"], "extension is outside what the plan allows")
    for u in t["production_use"]:
        if not SIM_START <= u["used_at"].date() <= SIM_END:
            no(u["use_id"], "used_at outside the simulation window")
        if u["days_overdue"] < 0:
            no(u["use_id"], "days_overdue below 0")
        if (u["exception_ref"] is not None) != (u["use_status"] == "OVERDUE_WITH_EXCEPTION"):
            no(u["use_id"], "exception_ref must be filled exactly for OVERDUE_WITH_EXCEPTION")
        if u["is_prohibited"] != (u["use_status"] == "VIOLATION"):
            no(u["use_id"], "is_prohibited must be true exactly for VIOLATION")
        if not OPERATOR_RE.match(u["operator_code"]) or not BATCH_RE.match(u["batch_id"]):
            no(u["use_id"], "operator_code or batch_id has the wrong shape")
    return bad


def check_date_order(t, ix, conn):
    bad = []
    for c in t["certificate"]:
        if c["issue_date"] < ix["event"][c["calibration_id"]]["calibration_date"]:
            bad.append((c["certificate_id"], "certificate issued before the calibration happened"))
    for w in t["work_order"]:
        if w["created_at"].date() < ix["event"][w["source_calibration_id"]]["calibration_date"]:
            bad.append((w["work_order_id"], "work order created before its calibration"))
        if w["completed_at"] is not None and w["completed_at"] < w["created_at"]:
            bad.append((w["work_order_id"], "completed before it was created"))
    for a in t["alert"]:
        if a["alert_type"] == "PROHIBITED_USE":
            too_early = a["created_at"] < ix["use"][a["related_record_id"]]["used_at"]
        else:
            too_early = a["created_at"].date() < ix["event"][a["related_record_id"]]["calibration_date"]
        if too_early:
            bad.append((a["alert_id"], "alert raised before the record that triggered it"))
    for table, field in (("calibration_event", "calibration_date"), ("work_order", "created_at"),
                         ("alert", "created_at"), ("audit_record", "timestamp")):
        pk = PK[table]
        rows = sorted(t[table], key=lambda r: int(r[pk].split("-")[-1]))
        if [int(r[pk].split("-")[-1]) for r in rows] != list(range(1, len(rows) + 1)):
            bad.append((table, "ID counters have gaps or repeats"))
        for prev, cur in zip(rows, rows[1:]):
            if cur[field] < prev[field]:
                bad.append((cur[pk], f"{table} IDs are not in time order"))
    return bad


def check_arithmetic(t, ix, conn):
    bad = []
    for e in t["calibration_event"]:
        tol = ix["itype"][ix["asset"][e["asset_id"]]["instrument_type_id"]]["tolerance"]
        if e["tolerance_applied"] != tol:
            bad.append((e["calibration_id"], "tolerance_applied differs from the instrument type"))
        if e["result"] != ("PASS" if abs(e["measured_error"]) <= e["tolerance_applied"] else "FAIL"):
            bad.append((e["calibration_id"], "result does not follow from measured_error vs tolerance"))
        if e["days_late"] != max(0, (e["calibration_date"] - e["previous_due_date"]).days):
            bad.append((e["calibration_id"], "days_late does not follow from the dates"))
    for c in t["certificate"]:
        e = ix["event"][c["calibration_id"]]
        if c["valid_until"] != e["next_due_date"]:
            bad.append((c["certificate_id"], "valid_until differs from the event's next_due_date"))
        if c["result"] != e["result"]:
            bad.append((c["certificate_id"], "certificate result differs from the event result"))
    for w in t["work_order"]:
        if w["work_type"] == "IMPACT_ASSESSMENT":
            expected = 0.0
        else:
            end = w["completed_at"] if w["completed_at"] is not None else END_OF_YEAR
            expected = round((end - w["created_at"]).total_seconds() / 3600, 1)
        if w["downtime_hours"] != expected:
            bad.append((w["work_order_id"], f"downtime_hours should be {expected}"))
    gaps = sum(e["certificate_id"] is None for e in t["calibration_event"])
    if len(t["certificate"]) + gaps != len(t["calibration_event"]):
        bad.append(("calibration_event", "certificates + certificate gaps do not add up to the events"))
    return bad


def check_calibration_timeline(t, ix, conn):
    """Rule R2: only a PASS moves the due date. A FAIL is re-tested 3-14 days later."""
    bad = []
    for aid, chain in ix["chains"].items():
        in_force = chain[0]["previous_due_date"]
        for e in chain:
            if e["previous_due_date"] != in_force:
                bad.append((e["calibration_id"], "previous_due_date is not the due date in force"))
            if e["result"] == "PASS":
                in_force = e["next_due_date"]
        for cur, nxt in zip(chain, chain[1:]):
            gap = (nxt["calibration_date"] - cur["calibration_date"]).days
            if cur["result"] == "FAIL" and not 3 <= gap <= 14:
                bad.append((cur["calibration_id"], "failed calibration not re-tested within 3-14 days"))
    return bad


def check_audit_trail(t, ix, conn):
    """Rule R6: history is never overwritten. Every chain starts empty and has no skipped step."""
    bad = []
    chains = {}
    for r in sorted(t["audit_record"], key=lambda r: r["audit_id"]):
        if r["event_type"] != "EMERGENCY_EXTENSION":
            chains.setdefault((r["entity_type"], r["entity_id"], r["event_type"]), []).append(r)
    for (etype, eid, _), rows in chains.items():
        if rows[0]["old_value"] is not None:
            bad.append((rows[0]["audit_id"], f"{etype} {eid}: first record must have an empty old_value"))
        for prev, cur in zip(rows, rows[1:]):
            if cur["old_value"] != prev["new_value"] or cur["timestamp"] < prev["timestamp"]:
                bad.append((cur["audit_id"], f"{etype} {eid}: history chain is broken"))
    for a in t["asset"]:
        rows = chains.get(("ASSET", a["asset_id"], "ASSET_STATUS_CHANGE"))
        if not rows:
            bad.append((a["asset_id"], "asset has no status history"))
        elif rows[-1]["new_value"] != a["current_status"]:
            bad.append((a["asset_id"], "current_status differs from the last logbook entry"))
    for c in t["certificate"]:
        if ("CERTIFICATE", c["certificate_id"], "CERTIFICATE_ISSUED") not in chains:
            bad.append((c["certificate_id"], "certificate has no logbook entry"))
    for w in t["work_order"]:
        rows = chains.get(("WORKORDER", w["work_order_id"], "WO_STATUS_CHANGE"))
        if not rows or rows[-1]["new_value"] != w["status"]:
            bad.append((w["work_order_id"], "work order status differs from its logbook history"))
    return bad


def check_followups(t, ix, conn):
    """R4 (corrective work order + alert for every FAIL), prohibited-use alerts, and R7."""
    bad = []
    corrective = Counter(w["source_calibration_id"] for w in t["work_order"]
                         if w["work_type"] == "CORRECTIVE_ACTION")
    impact = Counter(w["source_calibration_id"] for w in t["work_order"]
                     if w["work_type"] == "IMPACT_ASSESSMENT")
    failed_alerts = Counter(a["related_record_id"] for a in t["alert"]
                            if a["alert_type"] == "CALIBRATION_FAILED")
    for e in t["calibration_event"]:
        cid, failed = e["calibration_id"], e["result"] == "FAIL"
        if corrective[cid] != (1 if failed else 0):
            bad.append((cid, "wrong number of CORRECTIVE_ACTION work orders"))
        if failed_alerts[cid] != (1 if failed else 0):
            bad.append((cid, "wrong number of CALIBRATION_FAILED alerts"))
        if impact[cid] > 1 or (impact[cid] and not failed):
            bad.append((cid, "unexpected IMPACT_ASSESSMENT work order"))
        # NOTE: a FAIL with NO impact assessment is NOT checked here. It is detector C.

    prohibited = {u["use_id"] for u in t["production_use"] if u["is_prohibited"]}
    alerted = {a["related_record_id"] for a in t["alert"] if a["alert_type"] == "PROHIBITED_USE"}
    for use_id in sorted(prohibited ^ alerted):
        bad.append((use_id, "prohibited use and PROHIBITED_USE alert do not match"))

    cal_days = {(e["asset_id"], e["calibration_date"]) for e in t["calibration_event"]}
    history = {}
    for r in sorted(t["audit_record"], key=lambda r: r["audit_id"]):
        if r["entity_type"] == "ASSET" and r["event_type"] == "ASSET_STATUS_CHANGE":
            times, states = history.setdefault(r["entity_id"], ([], []))
            times.append(r["timestamp"])
            states.append(r["new_value"])
    for u in t["production_use"]:
        if (u["asset_id"], u["used_at"].date()) in cal_days:
            bad.append((u["use_id"], "used on its calibration day"))
        times, states = history[u["asset_id"]]
        i = bisect_right(times, u["used_at"]) - 1
        if i < 0 or states[i] != "ACTIVE":
            bad.append((u["use_id"], "used while not ACTIVE (quarantined)"))
    return bad


# ---------- Rule R3, recomputed from scratch ----------
def _expected_use(u, ix, extensions):
    asset = ix["asset"][u["asset_id"]]
    plan = ix["plan"][asset["plan_id"]]
    chain = ix["chains"].get(u["asset_id"], [])
    day = u["used_at"].date()

    best = None                                    # latest PASS on or before the day of use
    for e in chain:
        if e["calibration_date"] > day:
            break
        if e["result"] == "PASS":
            best = e
    if best is not None:
        in_force, due = best["calibration_id"], best["next_due_date"]
    else:
        in_force, due = None, (chain[0]["previous_due_date"] if chain else None)

    out = {"calibration_in_force": in_force, "due_date_at_use": due, "days_overdue": 0,
           "use_status": "VALID", "is_prohibited": False, "exception_ref": None}
    if due is None:
        return out
    effective = due + timedelta(days=plan["grace_days"])
    if day <= effective:
        return out
    out["days_overdue"] = (day - effective).days
    if not plan["block_if_overdue"]:
        out["use_status"] = "OVERDUE_ALLOWED"
        return out
    for x in extensions.get(u["asset_id"], []):
        if x["old_value"] == due.isoformat() and x["timestamp"] <= u["used_at"] and day <= x["extension_until"]:
            out["use_status"] = "OVERDUE_WITH_EXCEPTION"
            out["exception_ref"] = x["audit_id"]
            return out
    if asset["production_line"] in INTERLOCK_LINES:
        out["use_status"] = "BLOCKED"
    else:
        out["use_status"] = "VIOLATION"
        out["is_prohibited"] = True
    return out


def _expected_all(t, ix):
    if "expected" not in ix:                       # compute once, reuse (100,000 uses)
        extensions = {}
        for r in sorted(t["audit_record"], key=lambda r: r["audit_id"]):
            if r["event_type"] == "EMERGENCY_EXTENSION":
                extensions.setdefault(r["entity_id"], []).append(r)
        ix["expected"] = {u["use_id"]: _expected_use(u, ix, extensions) for u in t["production_use"]}
    return ix["expected"]


def _missed_prohibition(u, expected):
    """The row says VALID, but the rules say the use was prohibited (BLOCKED or VIOLATION)."""
    return u["use_status"] == "VALID" and expected["use_status"] in ("BLOCKED", "VIOLATION")


def check_use_status(t, ix, conn):
    bad = []
    expected = _expected_all(t, ix)
    for u in t["production_use"]:
        exp = expected[u["use_id"]]
        if {k: u[k] for k in exp} != exp and not _missed_prohibition(u, exp):
            bad.append((u["use_id"], f"stored fields differ from the R3 recomputation ({exp['use_status']})"))
    return bad


def check_duplicates(t, ix, conn):
    bad = []

    def dups(rows, key, label):
        counts = Counter(key(r) for r in rows)
        return [(str(k), f"{label}: {n} copies") for k, n in counts.items() if n > 1]

    bad += dups(t["calibration_event"], lambda e: (e["asset_id"], e["calibration_date"]), "calibration on the same day")
    bad += dups(t["certificate"], lambda c: c["calibration_id"], "two certificates for one calibration")
    bad += dups(t["asset"], lambda a: a["serial_number"], "serial number")
    bad += dups(t["work_order"], lambda w: (w["source_calibration_id"], w["work_type"]), "work order of the same type")
    bad += dups(t["alert"], lambda a: (a["alert_type"], a["related_record_id"]), "same alert twice")
    bad += dups(t["production_use"], lambda u: (u["asset_id"], u["used_at"]), "same asset used twice at the same second")
    bad += dups(t["audit_record"], lambda r: (r["entity_type"], r["entity_id"], r["event_type"],
                                              r["old_value"], r["new_value"], r["timestamp"]), "identical logbook line")
    return bad


# =====================================================================
#  DETECTORS: one per planted mistake. They find them WITHOUT the answer key.
# =====================================================================
def detect_due_date(t, ix, conn):
    """A: next_due_date must equal calibration_date + plan interval (rule R1)."""
    sql = """
        SELECT e.calibration_id, e.next_due_date, date(e.calibration_date, '+' || p.interval_days || ' days')
        FROM calibration_event e JOIN calibration_plan p ON p.plan_id = e.plan_id
        WHERE date(e.calibration_date, '+' || p.interval_days || ' days') <> e.next_due_date
        ORDER BY 1"""
    return [(cid, f"next_due_date {got} but calibration_date + plan interval = {want}")
            for cid, got, want in conn.execute(sql)]


def detect_expired_uses(t, ix, conn):
    """D: the use row says VALID, but recomputing rule R3 says it was prohibited."""
    expected = _expected_all(t, ix)
    return [(u["use_id"], f"recorded VALID but the rules say {expected[u['use_id']]['use_status']}")
            for u in t["production_use"] if _missed_prohibition(u, expected[u["use_id"]])]


def detect_certificate_asset(t, ix, conn):
    """B: a certificate's asset must be the asset of the calibration it certifies."""
    sql = """
        SELECT c.certificate_id, c.asset_id, e.asset_id
        FROM certificate c JOIN calibration_event e ON e.calibration_id = c.calibration_id
        WHERE c.asset_id <> e.asset_id ORDER BY 1"""
    return [(cid, f"certificate says {wrong} but the calibration belongs to {right}")
            for cid, wrong, right in conn.execute(sql)]


def detect_missing_impact(t, ix, conn):
    """C: every FAILED calibration needs an IMPACT_ASSESSMENT work order."""
    sql = """
        SELECT e.calibration_id FROM calibration_event e
        WHERE e.result = 'FAIL' AND NOT EXISTS (
            SELECT 1 FROM work_order w
            WHERE w.source_calibration_id = e.calibration_id AND w.work_type = 'IMPACT_ASSESSMENT')
        ORDER BY 1"""
    return [(cid, "FAILED calibration without an IMPACT_ASSESSMENT work order")
            for (cid,) in conn.execute(sql)]


STRUCTURAL = [
    ("id_formats", "ID formats and embedded references", check_id_formats),
    ("references", "Cross-table references and consistency", check_references),
    ("enums", "Allowed values (enums)", check_enums),
    ("field_rules", "Required fields, ranges and conditional rules", check_field_rules),
    ("date_order", "Date ordering and chronological IDs", check_date_order),
    ("arithmetic", "Derived values and arithmetic reconciliation", check_arithmetic),
    ("timeline", "Calibration timeline lifecycle (R2)", check_calibration_timeline),
    ("audit_trail", "Audit-trail lifecycle (R6)", check_audit_trail),
    ("followups", "Failure and prohibited-use follow-ups (R4, R7)", check_followups),
    ("use_status", "Use status recomputed from rule R3", check_use_status),
    ("duplicates", "Duplicate records", check_duplicates),
]
DETECTORS = {
    DUE_DATE: detect_due_date,
    EXPIRED_USE: detect_expired_uses,
    CERT_MISMATCH: detect_certificate_asset,
    NO_IMPACT: detect_missing_impact,
}


# =====================================================================
#  Running everything, scoring, printing
# =====================================================================
def _run(fn, t, ix, conn):
    try:
        return fn(t, ix, conn)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        return [("-", f"check could not run (broken references?): {exc!r}")]


def validate_all(tables):
    """Takes ONLY the tables. The answer key is not a parameter, so it cannot leak in."""
    ix = _build_index(tables)
    conn, problems = load_sqlite(tables)
    checks = [{"key": "keys", "violations": problems,
               "name": "Primary keys, unique keys, foreign keys (SQLite, enforcement ON)"}]
    for key, name, fn in STRUCTURAL:
        checks.append({"key": key, "name": name, "violations": _run(fn, tables, ix, conn)})
    findings = {a_type: _run(fn, tables, ix, conn) for a_type, fn in DETECTORS.items()}
    conn.close()
    return {"checks": checks, "findings": findings}


def score_findings(findings, ground_truth):
    """Compare what the detectors found with the answer key: precision and recall per type."""
    rows = []
    for a_type in sorted(findings):
        found = {record_id for record_id, _ in findings[a_type]}
        truth = {r["record_id"] for r in ground_truth if r["anomaly_type"] == a_type}
        tp, fp, fn = len(found & truth), len(found - truth), len(truth - found)
        rows.append({
            "anomaly_type": a_type, "truth": len(truth), "found": len(found),
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else 1.0,
            "recall": tp / (tp + fn) if tp + fn else 1.0,
        })
    return rows


def all_passed(report, scores=None):
    structure_ok = all(not c["violations"] for c in report["checks"])
    detectors_ok = scores is None or all(
        s["false_positives"] == 0 and s["false_negatives"] == 0 for s in scores)
    return structure_ok and detectors_ok


def format_report(report, scores=None, title=""):
    lines = [f"VALIDATION SUMMARY {title}".rstrip(), ""]
    for c in report["checks"]:
        n = len(c["violations"])
        lines.append(f"[{'PASS' if n == 0 else 'FAIL'}] {c['name']}: {n} violation(s)")
        for record_id, message in c["violations"][:3]:
            lines.append(f"         e.g. {record_id}: {message}")
    lines += ["", "Anomalies detected from the tables alone (answer key NOT used):"]
    for a_type, found in sorted(report["findings"].items()):
        lines.append(f"  {a_type:46s} {len(found):>5}")
    if scores:
        lines += ["", "Compared with ground truth:",
                  f"  {'anomaly type':46s} {'truth':>5} {'found':>5} {'TP':>4} {'FP':>4} {'FN':>4} {'prec':>6} {'recall':>6}"]
        for s in scores:
            lines.append(f"  {s['anomaly_type']:46s} {s['truth']:>5} {s['found']:>5} {s['true_positives']:>4} "
                         f"{s['false_positives']:>4} {s['false_negatives']:>4} {s['precision']:>6.2f} {s['recall']:>6.2f}")
    lines += ["", "RESULT: " + ("ALL CHECKS PASSED, detectors match ground truth exactly"
                                if all_passed(report, scores) else "PROBLEMS FOUND")]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    from src.generate import build_dataset

    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    tables, truth = build_dataset(name)
    report = validate_all(tables)
    print(format_report(report, score_findings(report["findings"], truth), f"(scale: {name})"))