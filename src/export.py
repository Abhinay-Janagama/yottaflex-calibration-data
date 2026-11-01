"""Step 10: write the dataset to disk as CSV, JSON and SQL, plus manifests and checksums.
No timestamps and no machine-specific paths are written, so two runs give identical bytes."""
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from src.validate import SCHEMA, TABLES

SQL_BATCH = 500
CHECKSUM_FILE = "checksums.sha256"


# ---------- Column order comes from the SQL schema (one source of truth) ----------
def table_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    cols = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in TABLES}
    conn.close()
    return cols


# ---------- Turning Python values into text (one converter per format) ----------
def _csv(v):
    if v is None:
        return ""                                   # empty cell = NULL
    if isinstance(v, bool):                         # bool BEFORE int (True is also 1)
        return "true" if v else "false"
    if isinstance(v, (datetime, date)):             # datetime BEFORE date
        return v.isoformat()
    return v


def _json(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v                                        # None -> null, bool -> true/false


def _sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (datetime, date)):
        v = v.isoformat()
    return "'" + str(v).replace("'", "''") + "'"    # a quote inside text is doubled


# ---------- Writers ----------
def write_csv(rows, columns, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for r in rows:
            writer.writerow([_csv(r[c]) for c in columns])


def write_json(rows, columns, path):
    """One record per line inside a JSON array: valid JSON, small, easy to diff."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps({c: _json(r[c]) for c in columns}) for r in rows))
        f.write("\n]\n")


def write_sql(tables, columns, folder):
    folder = Path(folder)
    with open(folder / "schema.sql", "w", encoding="utf-8", newline="\n") as f:
        f.write(SCHEMA.strip() + "\n")
    with open(folder / "seed.sql", "w", encoding="utf-8", newline="\n") as f:
        f.write("-- Synthetic calibration-management seed data. Load into SQLite: sqlite3 db < seed.sql\n")
        f.write("PRAGMA foreign_keys = ON;\n")
        f.write(SCHEMA.strip() + "\n\nBEGIN TRANSACTION;\n")
        for t in TABLES:                            # parents first, children after
            cols = columns[t]
            head = f"INSERT INTO {t} ({', '.join(cols)}) VALUES\n"
            rows = tables[t]
            for i in range(0, len(rows), SQL_BATCH):
                chunk = rows[i:i + SQL_BATCH]
                f.write(head + ",\n".join(
                    "(" + ", ".join(_sql(r[c]) for c in cols) + ")" for r in chunk) + ";\n")
        f.write("COMMIT;\n")


def write_json_file(data, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


# ---------- Fingerprints ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def checksum_folder(folder):
    """{relative/path: sha256} for every file, except the checksum file itself."""
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): sha256_file(p)
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.name != CHECKSUM_FILE}


# ---------- The function everyone calls ----------
def export_all(tables, truth, out_dir, scale_name, seed, result):
    """Writes csv/, json/, sql/, the manifests and (LAST) the checksums.
    reports/ and ground_truth/ are written by the caller BEFORE this runs."""
    out = Path(out_dir)
    for sub in ("csv", "json", "sql"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    columns = table_columns()

    for t in TABLES:
        write_csv(tables[t], columns[t], out / "csv" / f"{t}.csv")
        write_json(tables[t], columns[t], out / "json" / f"{t}.json")
    write_sql(tables, columns, out / "sql")

    row_counts = {t: len(tables[t]) for t in TABLES}
    row_counts["ground_truth"] = len(truth)

    write_json_file({
        "project": "YottaFlex AI candidate project: calibration management, synthetic data",
        "scale": scale_name,
        "seed": seed,
        "generator_command": f"python -m src.generate --scale {scale_name} --seed {seed} --out data/{scale_name}",
        "row_counts": row_counts,
        "injected_anomalies": dict(sorted(Counter(r["anomaly_type"] for r in truth).items())),
        "validation_passed": result["all_passed"],
        "conventions": {
            "csv": "UTF-8, LF line endings, header row, empty cell = NULL, booleans true/false, ISO dates and timestamps",
            "json": "array of records, one per line, null for NULL",
            "sql": "SQLite; seed.sql contains the schema, PRAGMA foreign_keys = ON and batched INSERTs",
        },
    }, out / "dataset_manifest.json")

    write_json_file({
        "external_data_used": False,
        "sources": [],
        "provenance": "Fully synthetic. Every record is produced by this repository's generator "
                      "from a fixed seed. No personal, confidential or third-party data was used.",
        "public_reference_data": "none; the schema was designed from the problem statement only",
        "licence_note": "No external datasets, so no third-party licence or attribution is required.",
    }, out / "source_manifest.json")

    checksums = checksum_folder(out)
    with open(out / CHECKSUM_FILE, "w", encoding="utf-8", newline="\n") as f:
        for name, digest in checksums.items():
            f.write(f"{digest}  {name}\n")
    return {"row_counts": row_counts, "checksums": checksums}