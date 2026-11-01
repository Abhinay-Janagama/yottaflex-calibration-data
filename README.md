# Calibration Management: Synthetic Data Generator

A reproducible generator of synthetic data for a manufacturing **instrument calibration** workflow: scheduling calibrations, managing certificates, and preventing the use of overdue instruments where policy requires.

Built for the YottaFlex AI candidate project (72-hour challenge). **Everything is synthetic.** No external, personal or confidential data is used.

- Fixed seed: `20261022`
- Same code builds a small `starter` dataset and the `full` dataset
- 10 related tables, a separate ground-truth answer key, a validator, evaluation metrics, and a reproducibility proof

---

## 1. Quick start

Requirements: Python 3.11 or newer (developed and tested on 3.13). The generator uses only the standard library. `pytest` is needed only for the tests.

```bash
git clone https://github.com/<<Abhinay-Janagama>>/yottaflex-calibration-data.git
cd yottaflex-calibration-data

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Build the full dataset (2,000 assets, 5,000 calibrations, 100,000 uses): about 1 minute
python -m src.generate --scale full --seed 20261022 --out data/full

# Prove reproducibility: builds the dataset twice and compares checksums (2-4 minutes)
python -m src.reproduce --scale full

# Run the tests (89 tests, 1-3 minutes)
python -m pytest -q
```

A small, fast dataset for experiments: `python -m src.generate --scale starter` (100 assets, 250 calibrations, 5,000 uses).

The generator refuses to overwrite a folder it did not create itself (it looks for `dataset_manifest.json`).

---

## 2. What the data represents

Factories use measuring instruments (pressure gauges, thermocouples, torque wrenches...). Each instrument must be **calibrated** on a schedule, and each calibration produces a **certificate**. An overdue instrument must not be used where the plan says so, unless an **emergency extension** was approved. A **failed** calibration needs a corrective action and an impact assessment.

| Table | Meaning |
|---|---|
| Supplier | Calibration labs |
| InstrumentType | Kind of instrument: unit, range, tolerance |
| CalibrationPlan | Interval, grace days, block-if-overdue policy, extension limit |
| Asset | An individual instrument (`AST-000001`) |
| CalibrationEvent | One calibration with measured error and PASS/FAIL result |
| Certificate | One per completed calibration (a few are deliberately missing) |
| WorkOrder | Routine calibration, corrective action, impact assessment |
| ProductionUse | One use of an instrument, with a derived validity status |
| Alert | Overdue, failed, certificate missing, prohibited use |
| AuditRecord | Append-only log of status changes and emergency extensions |

Actors represented: plant operator, maintenance/quality engineer, production planner, OT/IT administrator (as fake role codes and operator codes, never real people).

Full field-level definitions: [`docs/data_dictionary.md`](docs/data_dictionary.md).

---

## 3. Business rules (all outcomes are derived, never random)

| Rule | Statement |
|---|---|
| R1 | `next_due_date = calibration_date + plan.interval_days` |
| R2 | An asset is valid from its latest **PASS** until `next_due_date + grace_days` (+ approved extension). A FAIL does **not** move the due date |
| R3 | A use is `VALID`, `OVERDUE_ALLOWED`, `OVERDUE_WITH_EXCEPTION`, `BLOCKED` or `VIOLATION`, calculated from the calibration history, plan policy, extensions and line interlock |
| R3b | On lines with an interlock (LINE-01..08) an overdue use is `BLOCKED`. On the others it goes ahead as a `VIOLATION` |
| R4 | A FAIL creates a corrective-action work order (with downtime), an impact-assessment work order, an alert, and a QUARANTINED status change |
| R5 | Each completed calibration gets `CERT-<calibration_id>`. A missing one is a certificate gap |
| R6 | History is never overwritten. Status changes are new AuditRecord rows |
| R7 | An asset is never used on a calibration day or while quarantined |
| R8 | Edge cases are injected **after** the clean baseline, and every one is listed in the ground truth |
| R9 | A prohibited use is overdue + plan blocks + no covering extension |

`result` is PASS when `abs(measured_error) <= tolerance`, otherwise FAIL. Boundary cases exactly on the tolerance are included and PASS. Details: [`docs/rules.md`](docs/rules.md).

### ID conventions

`AST-000001` | `CAL-<asset-id>-2026-000001` | `CERT-<calibration-id>` | `WO-2026-000001` | `USE-<asset-id>-<timestamp>`

I added `SUP-001`, `ITYPE-001`, `PLAN-001`, `ALT-2026-000001`, `AUD-000001`, `BATCH-000001`, `GT-0001`, because the brief did not specify them. Counters are zero-padded and assigned after sorting by time, so IDs are chronological.

---

## 4. Pipeline

```
masters.py    Supplier -> InstrumentType -> CalibrationPlan -> Asset     (parents first)
events.py     CalibrationEvent + Certificate                              (timeline per asset)
workflow.py   WorkOrder, Alert, AuditRecord                               (derived from events)
usage.py      Emergency extensions + 100,000 ProductionUse                (status derived by R3)
inject.py     4 labelled edge cases on a COPY + ground_truth              (after the clean baseline)
validate.py   SQLite (foreign keys ON) + structure checks + 4 detectors
evaluate.py   Statistics, coverage, realism checks, validation_summary.md
export.py     CSV / JSON / SQL + manifests + SHA-256 checksums
generate.py   One command that runs everything
reproduce.py  Runs the generator twice and compares checksums
```

---

## 5. Edge cases and ground truth

Four labelled anomaly types are injected (40 of each in the full dataset, 5 in starter):

| Anomaly | What is wrong |
|---|---|
| `DUE_DATE_INCONSISTENT_WITH_PLAN` | `next_due_date` disagrees with calibration date + plan interval |
| `EXPIRED_USE_WITHOUT_EXCEPTION` | Overdue use on a blocking plan with no extension, recorded as `VALID` with no alert |
| `CERTIFICATE_ASSET_MISMATCH` | The certificate refers to a different asset |
| `FAILED_CALIBRATION_WITHOUT_IMPACT_ASSESSMENT` | A FAIL with no impact-assessment work order |

The answer key is written to its own folder, `ground_truth/ground_truth.csv` and `.json`. No input table has a label column. The validator takes only the tables as input. A test confirms this.

Baseline `VIOLATION` rows are **not** anomalies. They are correctly flagged by the system and have alerts.

---

## 6. Output layout

```
data/full/
  csv/            10 tables as CSV
  json/           10 tables as JSON
  sql/            schema.sql, seed.sql (SQLite, foreign keys ON)
  ground_truth/   ground_truth.csv, ground_truth.json  (separate answer key)
  reports/        validation_summary.md, metrics.json
  dataset_manifest.json   scale, seed, command, row counts
  source_manifest.json    provenance: fully synthetic
  checksums.sha256        SHA-256 of every other file
```

Conventions: UTF-8, LF line endings, header row, empty cell = NULL, booleans `true`/`false`, ISO dates and timestamps. Load the SQL with `sqlite3 calibration.db < data/full/sql/seed.sql`.

---

## 7. Validation summary

Produced by `python -m src.generate` and stored in [`data/full/reports/validation_summary.md`](data/full/reports/validation_summary.md).

**Structure checks** (SQLite primary/unique/foreign keys, ID formats, enums, required fields, date order, arithmetic reconciliation, lifecycle chains, follow-ups, rule R3 recomputed, duplicates): **12 of 12 pass with 0 violations**. Mapping to the brief: [`docs/validation_rules.md`](docs/validation_rules.md).

**Detectors vs ground truth** (detectors never see the answer key):

| Anomaly | Truth | Found | False positives | False negatives |
|---|---|---|---|---|
| DUE_DATE_INCONSISTENT_WITH_PLAN | 40 | 40 | 0 | 0 |
| EXPIRED_USE_WITHOUT_EXCEPTION | 40 | 40 | 0 | 0 |
| CERTIFICATE_ASSET_MISMATCH | 40 | 40 | 0 | 0 |
| FAILED_CALIBRATION_WITHOUT_IMPACT_ASSESSMENT | 40 | 40 | 0 | 0 |

On the **clean baseline** (before injection) the validator finds nothing, so the detectors raise no false alarms.

**Key distributions (full scale):**

| Metric | Value |
|---|---|
| Calibration FAIL rate | 8.0% (late calibrations fail more than on-time ones: 16.4% vs 5.3%) |
| Late calibration rate | 24.9% |
| Certificate gap rate | 2.1% |
| Use status: VALID / OVERDUE_ALLOWED / OVERDUE_WITH_EXCEPTION / BLOCKED / VIOLATION |96,935 / 807 / 69 / 1,600 / 589 |
| Emergency extensions recorded |109|
| Coverage of normal, boundary, failure, exception scenarios | 21 of 21 present |
| Realism checks | 11 of 11 pass |

How each evaluation point of the brief is demonstrated: [`docs/evaluation_focus.md`](docs/evaluation_focus.md).

---

## 8. Reproducibility

`python -m src.reproduce --scale full` builds the dataset twice into separate folders and compares row counts and the SHA-256 checksum of every file. Result: IDENTICAL. The report is saved as [`repro/reproducibility_full.md`](repro/reproducibility_full.md).

Why it works: one seeded random generator per step, no clock or UUIDs, sorted iteration, fixed row order, LF line endings, and no timestamps or machine paths inside any output file.

---

## 9. Testing

`python -m pytest -q` runs 89 tests covering IDs, master data, calibration rules (R1, R2), work orders and audit chains (R4, R6), use status (R3), anomaly injection, the validator (including tests that **deliberately break the data** to confirm the validator notices), metrics, export formats, SQL loading, and reproducibility.

How I know the solution works: independent recomputation in the tests, the SQLite foreign-key check, detectors scoring precision and recall of 1.0 against a separate answer key, and byte-identical regeneration.

---

## 10. Assumptions

The full list is in [`docs/assumptions.md`](docs/assumptions.md). The most important ones:

- Simulation window 2026-01-01 to 2026-12-31. All assets are installed before 2026 and carry an inherited due date.
- Probabilities (late 15%, certificate gap 2%, extension 30%...) are my own assumptions and are not measured from a real plant.
- A FAIL does not move the due date. A re-test follows 3 to 14 days later.
- Emergency extensions are stored as AuditRecord rows. Impact assessments are WorkOrder rows.
- Overdue use on a blocking plan is `BLOCKED` on lines with an interlock and a `VIOLATION` elsewhere. A blocked attempt still counts as a use event.
- Injected anomalies replace some ordinary VALID uses, so the use count stays exactly 100,000.

---

## 11. Limitations and known deviations

- **Synthetic distributions are assumptions.** Realism checks use sanity bands I chose, not real plant statistics.
- **The generator and validator share the same business rules**, written by the same author. They catch inconsistencies, but they cannot prove the rules themselves match a real quality system.
- **Only four anomaly types** are injected, as required. Other failure modes (for example revoked certificates) are not modelled.
- **Some allowed values are defined but unused:** certificate status `REVOKED`, asset statuses `OUT_OF_SERVICE` and `RETIRED`, audit entity type `CALIBRATION`.
- Alerts of type `CALIBRATION_OVERDUE` and `CERTIFICATE_MISSING` are raised only under the rules in `docs/assumptions.md`.
- SQL output targets SQLite. Other databases may need small syntax changes.
- Reproducibility was tested on Python 3.13 on Windows. Other Python versions should behave the same, but I have not verified this.
- There is no UI and no hosted demo, because the brief did not require them.
- The 30-day calibration interval is allowed by the schema but does not occur in the full dataset at seed 20261022 (no plan received it).

---

## 12. Data provenance and licence

No external data is used (`data/full/source_manifest.json`). Supplier names and operator codes are invented, and any resemblance to real organisations is coincidental. No personal or confidential information is present, so no third-party licence or attribution applies.

---

## 13. AI usage disclosure

All prompts I sent are in [`prompts/PROMPT_LOG.md`](prompts/PROMPT_LOG.md).

**Tool:** Claude (claude.ai chat).

**Where AI accelerated my work**
- Breaking the problem statement into steps and a 72-hour plan
- Drafting the data dictionary, the architecture and the business rules
- Drafting the Python modules (`masters`, `events`, `workflow`, `usage`, `inject`, `validate`, `evaluate`, `export`, `generate`, `reproduce`), the test suites and the documentation

**Where I relied on it heavily**
- The first drafts of every source file and test file were written by Claude, and I typed or pasted them into the project step by step.
- I relied on AI for the first drafts of all code and tests, and I did not write the generator logic from scratch.

**What I personally reviewed, changed and validated**
- Set up the repository and ran every command and test suite after each step (89 tests passing).
- Debugged real problems along the way: a missing config constant (`ImportError`), code pasted into the wrong file, an indentation bug that closed a file too early in `write_ground_truth`, and a half-written output folder left by a crashed run.
- Read the generated reports, `ground_truth` and the reproducibility report, and checked that the numbers made sense.
- Learned and can explain the core design: seeded randomness, derived outcomes, parents-before-children generation, anomaly injection into a copy, blind detectors scored against a separate answer key, and checksum comparison.
- I read the generated reports and ground truth, checked that counts matched the brief (2,000 / 5,000 / 100,000), and fixed the errors I hit while running the code.

I used AI as an accelerator, and I take ownership of the submission and can walk through every module.

---

## 14. Repository map

```
src/       generator, validator, evaluator, exporter, reproducibility command
tests/     89 automated tests
docs/      data_dictionary.md, rules.md, assumptions.md, validation_rules.md, evaluation_focus.md
prompts/   PROMPT_LOG.md (all prompts sent to AI tools)
data/full/ generated dataset (CSV, JSON, SQL, ground truth, reports, checksums)
repro/     reproducibility reports
```
