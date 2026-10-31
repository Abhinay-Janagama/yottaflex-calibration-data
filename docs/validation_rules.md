# Validation rules (src/validate.py)

The validator reads only the tables (never ground_truth) and loads them into SQLite with foreign keys ON.

| Brief requirement | Check | What it verifies |
|---|---|---|
| Primary-key uniqueness | keys | SQLite PRIMARY KEY / UNIQUE constraints (also serial numbers, one certificate per calibration, one use per asset per second) |
| ID conventions | id_formats | Regex per table, asset embedded in CAL- IDs, CERT- = "CERT-" + calibration_id, USE- = asset + timestamp |
| Foreign-key integrity | keys, references | SQLite FKs, plus plan/type match, event/certificate pointing back, polymorphic pointers (audit entity_id, alert related_record_id) |
| Allowed enums | enums | Every enum column in the data dictionary |
| Required / conditional fields | field_rules | Required fields, ranges, "only if" rules (extension fields, completed_at, exception_ref, is_prohibited) |
| Date ordering | date_order | Certificate after calibration, work order after calibration, alerts after their trigger, chronological gap-free ID counters |
| Arithmetic reconciliation | arithmetic | result vs tolerance, days_late, tolerance_applied, certificate vs event, downtime_hours, certificates + gaps = events |
| Lifecycle transitions | timeline, audit_trail, followups | R2 due-date chain, FAIL re-test window, unbroken audit chains, asset.current_status = last logbook entry, R4 follow-ups, R7 no use on calibration day or while quarantined |
| Use status derived correctly | use_status | Rule R3 recomputed for every use |
| Duplicate checks | duplicates | Same-day calibrations, duplicate certificates, serials, work orders, alerts, uses, logbook lines |

## Detectors (find the injected edge cases without the answer key)
| Anomaly | Detector |
|---|---|
| DUE_DATE_INCONSISTENT_WITH_PLAN | next_due_date <> calibration_date + plan.interval_days (SQL) |
| EXPIRED_USE_WITHOUT_EXCEPTION | use recorded VALID, but R3 recomputation gives BLOCKED or VIOLATION |
| CERTIFICATE_ASSET_MISMATCH | certificate.asset_id <> calibration_event.asset_id (SQL join) |
| FAILED_CALIBRATION_WITHOUT_IMPACT_ASSESSMENT | FAIL event with no IMPACT_ASSESSMENT work order (SQL NOT EXISTS) |

Acceptance criteria covered: due dates calculated correctly (detector A, arithmetic), prohibited uses flagged (detector D, followups), certificates and events reconcile (references, arithmetic, detector B), impact assessment exists for failed calibration (detector C).