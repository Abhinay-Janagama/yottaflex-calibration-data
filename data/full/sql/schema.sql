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
