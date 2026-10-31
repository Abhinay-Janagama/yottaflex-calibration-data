# Assumptions
1. Simulation window is 2026-01-01 to 2026-12-31. All assets were installed before 2026.
2. IDs not specified by the brief (Supplier, InstrumentType, Plan, Alert, Audit) use my own formats: SUP-001, ITYPE-001, PLAN-001, ALT-2026-000001, AUD-000001.
3. The CAL counter is global and chronological (1 = earliest calibration of 2026).
4. Each asset has an inherited due date on 2026-01-01 (between 20 days overdue and one interval ahead).
5. Calibration result is derived: PASS if |measured_error| <= tolerance, else FAIL. Errors are normally distributed, with a wider spread for late calibrations.
6. 1% of measurements are placed exactly on the tolerance limit (boundary cases, which PASS).
7. A FAIL does not move the due date. A re-test happens 3-14 days later.
8. About 2% of calibration events have no certificate (certificate gaps).
9. Emergency extensions are AuditRecord rows. Impact assessments are WorkOrder rows.
10. All data is synthetic. No external data was used.

11. Every calibration that is not a re-test gets a ROUTINE_CALIBRATION work order, created 06:00 on the calibration day and completed 4-9 hours later.
12. A FAIL creates one CORRECTIVE_ACTION work order (created 17:00) and one IMPACT_ASSESSMENT work order (created 18:00). The repair finishes before the re-test. If no re-test happens in 2026, the repair stays IN_PROGRESS and the asset stays QUARANTINED.
13. downtime_hours = hours from created_at to completed_at (or to 2026-12-31 23:59:59 if still open). Impact assessments have 0 downtime.
14. Alerts: CALIBRATION_OVERDUE when a scheduled (non re-test) calibration is later than the plan's grace_days. CALIBRATION_FAILED for every FAIL. CERTIFICATE_MISSING only when the plan requires a certificate.
15. Each asset gets an initial ASSET_STATUS_CHANGE audit record (empty -> ACTIVE) on its install date. Asset.current_status is derived from the latest status-change audit record.
16. Work orders, alerts and audit records are numbered after sorting by time, so IDs are chronological. Emergency-extension audit records (Step 6) continue the AUD- numbering.