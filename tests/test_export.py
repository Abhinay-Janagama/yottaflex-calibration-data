import csv
import json
import sqlite3
from datetime import date, datetime

import pytest

from src.export import _csv, _json, _sql, checksum_folder
from src.generate import generate, main
from src.validate import PK, TABLES


@pytest.fixture(scope="module")
def starter_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("starter") / "data"
    info = generate("starter", out_dir=out)
    return out, info


def test_all_expected_files_exist(starter_out):
    out, _ = starter_out
    for t in TABLES:
        assert (out / "csv" / f"{t}.csv").is_file()
        assert (out / "json" / f"{t}.json").is_file()
    for rel in ("sql/schema.sql", "sql/seed.sql", "ground_truth/ground_truth.csv",
                "ground_truth/ground_truth.json", "reports/validation_summary.md",
                "reports/metrics.json", "dataset_manifest.json", "source_manifest.json",
                "checksums.sha256"):
        assert (out / rel).is_file(), rel


def test_csv_and_json_agree_with_the_row_counts(starter_out):
    out, info = starter_out
    for t in TABLES:
        with open(out / "csv" / f"{t}.csv", newline="", encoding="utf-8") as f:
            csv_keys = [row[PK[t]] for row in csv.DictReader(f)]
        json_rows = json.loads((out / "json" / f"{t}.json").read_text(encoding="utf-8"))
        assert len(csv_keys) == len(json_rows) == info["row_counts"][t]
        assert csv_keys == [r[PK[t]] for r in json_rows]
        assert len(set(csv_keys)) == len(csv_keys)
    assert info["row_counts"]["production_use"] == 5000


def test_seed_sql_loads_into_sqlite_with_valid_foreign_keys(starter_out):
    out, info = starter_out
    conn = sqlite3.connect(":memory:")
    conn.executescript((out / "sql" / "seed.sql").read_text(encoding="utf-8"))
    for t in TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == info["row_counts"][t]
    assert list(conn.execute("PRAGMA foreign_key_check")) == []
    conn.close()


def test_ground_truth_is_separate_and_never_leaks(starter_out):
    out, info = starter_out
    assert sorted(p.name for p in (out / "ground_truth").iterdir()) == [
        "ground_truth.csv", "ground_truth.json"]
    assert info["row_counts"]["ground_truth"] > 0
    banned = ("anomaly_type", "expected_decision", "DUE_DATE_INCONSISTENT",
              "EXPIRED_USE_WITHOUT", "CERTIFICATE_ASSET_MISMATCH", "FAILED_CALIBRATION_WITHOUT")
    for folder in ("csv", "json", "sql"):
        for p in (out / folder).iterdir():
            text = p.read_text(encoding="utf-8")
            for word in banned:
                assert word not in text, (p.name, word)


def test_checksum_file_matches_the_files(starter_out):
    out, info = starter_out
    lines = (out / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    listed = {name: digest for digest, name in (line.split("  ", 1) for line in lines)}
    assert listed == checksum_folder(out) == info["checksums"]
    assert "checksums.sha256" not in listed
    assert "ground_truth/ground_truth.csv" in listed and "csv/asset.csv" in listed


def test_no_carriage_returns_anywhere(starter_out):
    out, _ = starter_out
    for p in out.rglob("*"):
        if p.is_file():
            assert b"\r" not in p.read_bytes(), p.name


def test_value_formats():
    assert _csv(None) == "" and _csv(True) == "true" and _csv(False) == "false"
    assert _csv(date(2026, 3, 15)) == "2026-03-15"
    assert _csv(datetime(2026, 3, 15, 8, 15, 30)) == "2026-03-15T08:15:30"
    assert _json(datetime(2026, 3, 15, 8, 15, 30)) == "2026-03-15T08:15:30" and _json(None) is None
    assert _sql("O'Brien") == "'O''Brien'" and _sql(None) == "NULL"
    assert _sql(True) == "1" and _sql(False) == "0" and _sql(2.5) == "2.5" and _sql(7) == "7"
    assert _sql(date(2026, 3, 15)) == "'2026-03-15'"


def test_refuses_to_wipe_a_folder_it_did_not_create(tmp_path):
    folder = tmp_path / "precious"
    folder.mkdir()
    (folder / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError):
        generate("starter", out_dir=folder)
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_same_seed_gives_identical_files_and_can_overwrite_itself(tmp_path):
    a = generate("starter", out_dir=tmp_path / "a")
    b = generate("starter", out_dir=tmp_path / "b")
    assert a == b
    assert checksum_folder(tmp_path / "a") == checksum_folder(tmp_path / "b")
    again = generate("starter", out_dir=tmp_path / "a")          # replaces its own old output
    assert again == a


def test_command_line_entry_point(tmp_path):
    main(["--scale", "starter", "--out", str(tmp_path / "cli")])
    assert (tmp_path / "cli" / "checksums.sha256").is_file()