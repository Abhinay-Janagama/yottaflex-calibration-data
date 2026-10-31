"""Central settings for the generator. Change numbers HERE, nowhere else."""
from dataclasses import dataclass
from datetime import date

#The secret starting number for the random dice
SEED = 20261022
#The year we are pretending to simulate
SIM_START = date(2026, 1, 1)
SIM_END = date(2026, 12, 31)
YEAR = 2026

@dataclass(frozen=True)
class Scale:
    """How BIG the dataset is. Same code, different sizes."""
    name: str
    n_suppliers: int
    n_instrument_types: int
    n_assets: int
    n_calibrations: int
    n_uses: int

SCALES = {
    # small and fast: for testing while you build
    "starter": Scale("starter", 8, 10, 100, 250, 5_000),
    # the real thing the challenge asks for
    "full": Scale("full", 20, 15, 2_000, 5_000, 100_000),
}


# ---- Probabilities (how often things happen) ----
# These are only the "dice odds". The OUTCOMES (PASS/FAIL, VALID/VIOLATION)
# are still calculated from rules, not picked from these numbers.
INTERVAL_WEIGHTS = {30: 0.05, 90: 0.20, 180: 0.35, 365: 0.40}
GRACE_WEIGHTS = {0: 0.5, 7: 0.3, 14: 0.2}
CRITICALITY_WEIGHTS = {"LOW": 0.5, "MEDIUM": 0.35, "HIGH": 0.15}

P_BLOCK_IF_OVERDUE = 0.70       # 70% of plans forbid use when overdue
P_LATE_CALIBRATION = 0.15       # 15% of calibrations happen after the due date
P_CERTIFICATE_GAP = 0.02        # 2% of calibration events get no certificate
P_REQUIRES_CERTIFICATE = 0.90   # 90% of plans demand a certificate
P_EMERGENCY_EXTENSION = 0.30    # share of overdue periods that get an extension
ERR_SD_ON_TIME = 0.50           # measurement "wobble" for on-time calibrations (x tolerance)
ERR_SD_LATE = 0.70              # bigger wobble when the calibration was late
P_BOUNDARY_ERROR = 0.01         # 1% of measurements land exactly ON the tolerance limit
# How many labelled bad records to inject per anomaly type (Step 7)
ANOMALY_COUNTS = {
    "starter": 5,
    "full": 40,
}

def get_scale(name: str) -> Scale:
    """Look up a scale by name, with a friendly error."""
    if name not in SCALES:
        raise ValueError(f"Unknown scale '{name}'. Choose from {sorted(SCALES)}")
    return SCALES[name]