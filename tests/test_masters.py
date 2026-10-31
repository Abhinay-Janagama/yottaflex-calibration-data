from src.masters import build_masters
from src import ids


def data():
    return build_masters("starter")


def test_row_counts():
    d = data()
    assert len(d["supplier"]) == 8
    assert len(d["instrument_type"]) == 10
    assert len(d["calibration_plan"]) == 20      # 2 per type
    assert len(d["asset"]) == 100


def test_primary_keys_are_unique_and_well_formed():
    d = data()
    for table, key, pattern in [
        ("supplier", "supplier_id", "supplier_id"),
        ("instrument_type", "instrument_type_id", "instrument_type_id"),
        ("calibration_plan", "plan_id", "plan_id"),
        ("asset", "asset_id", "asset_id"),
    ]:
        values = [r[key] for r in d[table]]
        assert len(values) == len(set(values)), f"{table} has duplicate IDs"
        assert all(ids.PATTERNS[pattern].match(v) for v in values)


def test_serial_numbers_unique():
    serials = [a["serial_number"] for a in data()["asset"]]
    assert len(serials) == len(set(serials))


def test_foreign_keys_resolve_and_plan_type_matches_asset_type():
    d = data()
    type_ids = {t["instrument_type_id"] for t in d["instrument_type"]}
    plans = {p["plan_id"]: p for p in d["calibration_plan"]}
    for p in d["calibration_plan"]:
        assert p["instrument_type_id"] in type_ids
    for a in d["asset"]:
        assert a["instrument_type_id"] in type_ids
        assert a["plan_id"] in plans
        assert plans[a["plan_id"]]["instrument_type_id"] == a["instrument_type_id"]


def test_value_rules():
    d = data()
    for t in d["instrument_type"]:
        assert t["range_min"] < t["range_max"]
        assert t["tolerance"] > 0
    for p in d["calibration_plan"]:
        assert p["interval_days"] in (30, 90, 180, 365)
        assert p["grace_days"] in (0, 7, 14)
        if not p["block_if_overdue"]:
            assert p["max_extension_days"] == 0
    for s in d["supplier"]:
        if s["is_accredited"]:
            assert s["accreditation_standard"] == "ISO17025"


def test_two_plans_per_type_have_different_intervals():
    d = data()
    by_type = {}
    for p in d["calibration_plan"]:
        by_type.setdefault(p["instrument_type_id"], []).append(p["interval_days"])
    for intervals in by_type.values():
        assert len(intervals) == 2 and intervals[0] != intervals[1]


def test_same_seed_same_data_and_different_seed_different_data():
    assert build_masters("starter") == build_masters("starter")
    assert build_masters("starter", seed=1) != build_masters("starter", seed=2)