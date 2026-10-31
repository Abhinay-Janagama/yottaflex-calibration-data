import random
from datetime import datetime
from src import ids
from src.config import SEED

def test_id_formats():
    assert ids.asset_id(1) == "AST-000001"
    assert ids.calibration_id("AST-000001", 1) == "CAL-AST-000001-2026-000001"
    assert ids.certificate_id("CAL-AST-000001-2026-000001") == "CERT-CAL-AST-000001-2026-000001"
    assert ids.work_order_id(1) == "WO-2026-000001"
    assert ids.use_id("AST-000001", datetime(2026, 3, 15, 8, 15, 30)) == "USE-AST-000001-20260315T081530"


def test_all_ids_match_their_patterns():
    samples = {
        "supplier_id": ids.supplier_id(7),
        "instrument_type_id": ids.instrument_type_id(3),
        "plan_id": ids.plan_id(12),
        "asset_id": ids.asset_id(1999),
        "calibration_id": ids.calibration_id("AST-000042", 4321),
        "certificate_id": ids.certificate_id(ids.calibration_id("AST-000042", 4321)),
        "work_order_id": ids.work_order_id(55),
        "use_id": ids.use_id("AST-000042", datetime(2026, 12, 31, 23, 59, 59)),
        "alert_id": ids.alert_id(9),
        "audit_id": ids.audit_id(100),
    }
    for name, value in samples.items():
        assert ids.PATTERNS[name].match(value), f"{name} -> {value} has the wrong shape"

def test_counter_counts_up():
    c = ids.Counter()
    assert [c.next(), c.next(), c.next()] == [1, 2, 3]

def test_asset_extracted_from_calibration_id():
    assert ids.asset_from_calibration_id("CAL-AST-000042-2026-000007") == "AST-000042"

def test_same_seed_gives_same_numbers():
    """The 'special dice' test: same seed, same rolls."""
    a = random.Random(SEED)
    b = random.Random(SEED)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]