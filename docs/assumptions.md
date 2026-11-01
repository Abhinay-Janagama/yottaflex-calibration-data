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
17. Production uses are sampled by asset (critical assets are used more), weekday-heavy, with 06:00-22:00 busier than night. The status of every use is then derived from the asset's calibration windows (R2/R3), never assigned randomly.
18. An asset is not used on its calibration days or while quarantined (FAIL until the next PASS).
19. An asset with no 2026 calibration event is assumed valid all year (its next calibration falls after 2026-12-31).
20. Overdue use on a plan with block_if_overdue = true is BLOCKED on lines with an interlock (LINE-01..LINE-08) and a VIOLATION on the others. A BLOCKED attempt is still recorded as a use event.
21. About 30% of overdue periods on plans with max_extension_days > 0 get an EMERGENCY_EXTENSION audit record (entity_type = ASSET) signed at 07:00 on the first overdue day. extension_until = due + grace_days + 1..max_extension_days.
22. After merging the extension records, AUD- and ALT- IDs are renumbered in time order. PROHIBITED_USE alerts are raised for every VIOLATION, 10 minutes after the use.
23. batch_id = one batch per production line, per day, per shift (A 06-14, B 14-22, C 22-06).
24. Edge cases are injected into a COPY of the clean data. ANOMALY_COUNTS gives how many per type (starter 5, full 40). Each anomaly hits a different calibration, and counts may be lower if fewer safe candidates exist.
25. DUE_DATE_INCONSISTENT_WITH_PLAN: next_due_date is moved by -30, -14, -7, +7, +14 or +30 days. The certificate's valid_until follows, so only the plan disagrees. Candidates are FAIL events or a tool's last PASS that no use refers to, so no unlabelled side effects appear.
26. EXPIRED_USE_WITHOUT_EXCEPTION: an extra use on a day when the tool is overdue, the plan blocks use, no extension covers it and the tool is on the shelf. The row wrongly says VALID, is_prohibited = false and no alert exists, but due_date_at_use and days_overdue show the truth. The same number of ordinary VALID uses is removed, so the total stays exactly 100,000.
27. Baseline VIOLATION rows are NOT anomalies. They are correctly flagged by the system (R3) and have PROHIBITED_USE alerts.
28. CERTIFICATE_ASSET_MISMATCH: certificate.asset_id is replaced by a different, real asset.
29. FAILED_CALIBRATION_WITHOUT_IMPACT_ASSESSMENT: the IMPACT_ASSESSMENT work order and its logbook lines are removed (a ticket never created leaves no history). WO- and AUD- IDs are renumbered and exception_ref is remapped, so no ID gaps give the anomaly away.
30. ground_truth.csv/json is a separate file with no link back from the input tables.
31. The validator receives only the tables. ground_truth is used afterwards, only to score the detectors (precision and recall per anomaly type).
32. event.certificate_id and certificate.calibration_id point at each other, so SQLite enforces only certificate.calibration_id as a foreign key. The other direction is checked in Python.
33. Structure checks must pass even on the injected data, because the four injected anomalies are business-logic errors, not structural ones. The detectors must find exactly the injected anomalies: precision = recall = 1.0.
34. On the clean baseline (before injection) the validator finds zero violations and zero anomalies. This shows the detectors raise no false alarms.
35. The R3 check recomputes use status independently from the calibration history, plan, extensions and line interlock, and ignores the stored use_status.
36. Evaluation metrics are computed from the generated tables only. ground_truth is used only to score the detectors (precision and recall) and to count injected cases in the coverage table.
37. "Late" means calibration_date later than the due date in force (days_late > 0). Re-tests after a FAIL count as late if they fall after that due date.
38. Realism checks use sanity bands chosen by the author, not measured from a real plant: FAIL rate 3-12%, late rate 5-40%, certificate gaps above 0% and at most 6%, VALID uses above 90%, VIOLATION uses below 2%, weekday uses above 85%, HIGH-criticality assets used more than LOW, at least 3 calibration intervals, all 12 production lines used, at most 5% of assets never used.
39. Boundary scenarios: error exactly at tolerance (PASS), use on the last valid day (due + grace), use inside the grace period, use overdue by exactly 1 day.
40. The report (validation_summary.md and metrics.json) contains no timestamps, so regenerating with the same seed gives identical bytes.