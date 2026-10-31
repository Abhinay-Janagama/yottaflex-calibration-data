"""Step 3: master (parent) tables. Made FIRST because everything else points to them."""
import random
from datetime import date, timedelta

from src import ids
from src.config import (
    SEED,
    get_scale,
    INTERVAL_WEIGHTS,
    GRACE_WEIGHTS,
    CRITICALITY_WEIGHTS,
    P_BLOCK_IF_OVERDUE,
    P_REQUIRES_CERTIFICATE,
)

# ---------- Fixed lists (the "menu" we pick from) ----------
SUPPLIER_NAMES = [
    "Precision Cal Labs Pune", "Metro Metrology Chennai", "Apex Calibration Services",
    "Nordic Test and Cal", "Sigma Standards Lab", "Delta Measure Works",
    "Accura Calibration Hyderabad", "Titan Gauge Labs", "Vertex Metrology",
    "Prime Cal Mumbai", "Alpha Instruments Lab", "Zenith Calibration Co",
    "Orion Test Services", "Bharat Metrology Centre", "Summit Cal Partners",
    "Kite Measurement Labs", "Lumen Standards Institute", "Quantum Cal Bengaluru",
    "Ridge Instrument Services", "Polar Precision Labs",
]
COUNTRIES = ["IN", "IN", "IN", "IN", "DE", "US", "GB", "JP", "SG"]  # mostly India

# (type_name, unit, range_min, range_max, tolerance, default_criticality)
INSTRUMENT_CATALOG = [
    ("Pressure Gauge",          "bar",  0,     100,   0.5,   "HIGH"),
    ("Thermocouple",            "degC", 0,     1200,  2.0,   "HIGH"),
    ("Digital Thermometer",     "degC", -50,   300,   0.5,   "MEDIUM"),
    ("Vernier Caliper",         "mm",   0,     300,   0.03,  "LOW"),
    ("Micrometer",              "mm",   0,     100,   0.005, "MEDIUM"),
    ("Torque Wrench",           "Nm",   5,     500,   2.0,   "HIGH"),
    ("Load Cell",               "kg",   0,     5000,  1.0,   "HIGH"),
    ("Weighing Scale",          "kg",   0,     300,   0.1,   "MEDIUM"),
    ("Digital Multimeter",      "V",    0,     1000,  0.5,   "LOW"),
    ("Clamp Meter",             "A",    0,     600,   1.0,   "LOW"),
    ("pH Meter",                "pH",   0,     14,    0.05,  "MEDIUM"),
    ("Pressure Transmitter",    "bar",  0,     250,   0.25,  "HIGH"),
    ("Dial Indicator",          "mm",   0,     25,    0.01,  "LOW"),
    ("Temperature Transmitter", "degC", -100,  500,   1.0,   "MEDIUM"),
    ("Torque Transducer",       "Nm",   0,     1000,  1.0,   "HIGH"),
]

PRODUCTION_LINES = [f"LINE-{n:02d}" for n in range(1, 13)]   # LINE-01 ... LINE-12
INSTALL_START = date(2019, 1, 1)
INSTALL_END = date(2025, 12, 31)    # installed BEFORE 2026, so every tool exists all year


# ---------- Helper ----------
def _weighted(rng, weights: dict):
    """Pick one key from a {value: weight} dictionary using OUR dice."""
    return rng.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


# ---------- 1. Suppliers ----------
def make_suppliers(rng, n):
    assert n <= len(SUPPLIER_NAMES), "Add more names to SUPPLIER_NAMES"
    rows = []
    for i in range(1, n + 1):
        accredited = rng.random() < 0.80
        rows.append({
            "supplier_id": ids.supplier_id(i),
            "supplier_name": SUPPLIER_NAMES[i - 1],
            "country": rng.choice(COUNTRIES),
            "is_accredited": accredited,
            "accreditation_standard": "ISO17025" if accredited else None,
            "avg_turnaround_days": rng.randint(2, 21),
        })
    return rows


# ---------- 2. Instrument types ----------
def make_instrument_types(n):
    assert n <= len(INSTRUMENT_CATALOG), "Add more entries to INSTRUMENT_CATALOG"
    rows = []
    for i, (name, unit, rmin, rmax, tol, crit) in enumerate(INSTRUMENT_CATALOG[:n], start=1):
        rows.append({
            "instrument_type_id": ids.instrument_type_id(i),
            "type_name": name,
            "measurement_unit": unit,
            "range_min": float(rmin),
            "range_max": float(rmax),
            "tolerance": tol,
            "default_criticality": crit,
        })
    return rows


# ---------- 3. Calibration plans (2 per type, different intervals) ----------
def make_plans(rng, types):
    counter = ids.Counter()
    rows = []
    for t in types:
        first = _weighted(rng, INTERVAL_WEIGHTS)
        second = first
        while second == first:                       # make sure the 2 plans differ
            second = _weighted(rng, INTERVAL_WEIGHTS)

        for interval in (first, second):
            block = rng.random() < P_BLOCK_IF_OVERDUE
            rows.append({
                "plan_id": ids.plan_id(counter.next()),
                "instrument_type_id": t["instrument_type_id"],
                "interval_days": interval,
                "grace_days": _weighted(rng, GRACE_WEIGHTS),
                "block_if_overdue": block,
                "requires_certificate": rng.random() < P_REQUIRES_CERTIFICATE,
                # only plans that BLOCK can allow emergency extensions
                "max_extension_days": rng.choice([0, 7, 14, 30]) if block else 0,
            })
    return rows


# ---------- 4. Assets (the actual instruments) ----------
def make_assets(rng, n, types, plans):
    plans_by_type = {}
    for p in plans:                                   # plans are already in fixed order
        plans_by_type.setdefault(p["instrument_type_id"], []).append(p)

    # earlier types (pressure gauges...) are more common than later ones
    type_weights = [1 / (i + 1) ** 0.5 for i in range(len(types))]
    span_days = (INSTALL_END - INSTALL_START).days
    used_serials = set()
    rows = []

    for i in range(1, n + 1):
        t = rng.choices(types, weights=type_weights, k=1)[0]
        plan = rng.choice(plans_by_type[t["instrument_type_id"]])

        serial = f"SN-{rng.randrange(10**8):08d}"
        while serial in used_serials:                 # serial numbers must be unique
            serial = f"SN-{rng.randrange(10**8):08d}"
        used_serials.add(serial)

        # 70% keep the type's default criticality, 30% differ
        if rng.random() < 0.70:
            criticality = t["default_criticality"]
        else:
            criticality = _weighted(rng, CRITICALITY_WEIGHTS)

        rows.append({
            "asset_id": ids.asset_id(i),
            "instrument_type_id": t["instrument_type_id"],
            "plan_id": plan["plan_id"],
            "serial_number": serial,
            "production_line": rng.choice(PRODUCTION_LINES),
            "install_date": INSTALL_START + timedelta(days=rng.randint(0, span_days)),
            "criticality": criticality,
            "current_status": "ACTIVE",   # later steps update this from AuditRecords
        })
    return rows


# ---------- The one function everyone calls ----------
def build_masters(scale_name: str = "starter", seed: int = SEED) -> dict:
    scale = get_scale(scale_name)
    rng = random.Random(seed)                         # ONE dice for everything

    suppliers = make_suppliers(rng, scale.n_suppliers)
    types = make_instrument_types(scale.n_instrument_types)
    plans = make_plans(rng, types)
    assets = make_assets(rng, scale.n_assets, types, plans)

    return {
        "supplier": suppliers,
        "instrument_type": types,
        "calibration_plan": plans,
        "asset": assets,
    }


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "starter"
    data = build_masters(name)
    print(f"Scale: {name}")
    for table, rows in data.items():
        print(f"  {table:18s} {len(rows):>6} rows   first row -> {rows[0]}")