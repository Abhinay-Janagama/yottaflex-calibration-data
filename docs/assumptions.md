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