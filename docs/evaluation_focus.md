# Evaluation focus: where each point is demonstrated

| Brief's evaluation point | Evidence in this project |
|---|---|
| (a) Realistic distributions and meaningful variation | `validation_summary.md`: Calibration, Production use and Realism sections (FAIL rate, late rate, days-late spread, weighted intervals and criticality, weekday and daytime pattern, late tools failing more than on-time tools) |
| (b) Consistent IDs and valid joins | Validator checks `keys`, `id_formats`, `references` (SQLite foreign keys ON) |
| (c) Dependency and lifecycle consistency | Validator checks `timeline`, `audit_trail`, `followups`; parents generated before children |
| (d) Correct derived values and reconciliation | Validator checks `arithmetic`, `use_status`; every derived field is computed from source records |
| (e) Normal, boundary, failure and exception coverage | Coverage table in `validation_summary.md` (normal, boundary, failure, exception scenarios with counts) |
| (f) Separate ground truth | `ground_truth.csv` / `.json`; validator takes only tables; detectors scored with precision and recall |
| (g) Fixed-seed reproducibility, documentation, lawful provenance | Step 10 checksums, README, `docs/`, source manifest (fully synthetic, no external data) |