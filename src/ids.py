"""The ONLY place where IDs are built. Never type an ID by hand elsewhere."""
import re
from datetime import datetime

from src.config import YEAR


# ---------- Builders ----------
def supplier_id(n: int) -> str:
    return f"SUP-{n:03d}"                      # SUP-001


def instrument_type_id(n: int) -> str:
    return f"ITYPE-{n:03d}"                    # ITYPE-001


def plan_id(n: int) -> str:
    return f"PLAN-{n:03d}"                     # PLAN-001


def asset_id(n: int) -> str:
    return f"AST-{n:06d}"                      # AST-000001


def calibration_id(asset: str, n: int, year: int = YEAR) -> str:
    return f"CAL-{asset}-{year}-{n:06d}"       # CAL-AST-000001-2026-000001


def certificate_id(calibration: str) -> str:
    return f"CERT-{calibration}"               # CERT-CAL-AST-000001-2026-000001


def work_order_id(n: int, year: int = YEAR) -> str:
    return f"WO-{year}-{n:06d}"                # WO-2026-000001


def use_id(asset: str, when: datetime) -> str:
    return f"USE-{asset}-{when:%Y%m%dT%H%M%S}"  # USE-AST-000001-20260315T081530


def alert_id(n: int, year: int = YEAR) -> str:
    return f"ALT-{year}-{n:06d}"               # ALT-2026-000001


def audit_id(n: int) -> str:
    return f"AUD-{n:06d}"                      # AUD-000001


def batch_id(n: int) -> str:
    return f"BATCH-{n:06d}"                    # BATCH-000001


def operator_code(n: int) -> str:
    return f"OP-{n:04d}"                       # OP-0001

def ground_truth_id(n: int) -> str:
    return f"GT-{n:04d}"                       # GT-0001
'''---------- Counter ----------'''
class Counter:
    """A ticket machine: gives 1, 2, 3, ... and never repeats."""

    def __init__(self, start: int = 1):
        self._next = start

    def next(self) -> int:
        value = self._next
        self._next += 1
        return value

# ---------- Patterns (the validator will use these in Step 8) ----------
PATTERNS = {
    "supplier_id": re.compile(r"^SUP-\d{3}$"),
    "instrument_type_id": re.compile(r"^ITYPE-\d{3}$"),
    "plan_id": re.compile(r"^PLAN-\d{3}$"),
    "asset_id": re.compile(r"^AST-\d{6}$"),
    "calibration_id": re.compile(r"^CAL-AST-\d{6}-2026-\d{6}$"),
    "certificate_id": re.compile(r"^CERT-CAL-AST-\d{6}-2026-\d{6}$"),
    "work_order_id": re.compile(r"^WO-2026-\d{6}$"),
    "use_id": re.compile(r"^USE-AST-\d{6}-\d{8}T\d{6}$"),
    "alert_id": re.compile(r"^ALT-2026-\d{6}$"),
    "audit_id": re.compile(r"^AUD-\d{6}$"),
}


def asset_from_calibration_id(cal_id: str) -> str:
    """Pull the asset out of a calibration ID: CAL-AST-000001-2026-000001 -> AST-000001."""
    return cal_id.split("-")[1] + "-" + cal_id.split("-")[2]