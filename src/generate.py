"""Builds the WHOLE dataset in memory. (Step 9 adds the command line, export and checksums.)"""
from src.config import SEED
from src.events import build_calibrations
from src.inject import inject_edge_cases
from src.masters import build_masters
from src.usage import build_usage
from src.workflow import apply_final_status, build_workflow

CHANGED_BY_INJECTION = ("calibration_event", "certificate", "work_order",
                        "alert", "audit_record", "production_use")


def build_dataset(scale_name: str = "starter", seed: int = SEED, inject: bool = True):
    """Returns (tables, ground_truth). With inject=False you get the CLEAN baseline and []."""
    masters = build_masters(scale_name, seed)
    events, certs = build_calibrations(masters, scale_name, seed)
    wf = build_workflow(masters, events, certs, seed)
    usage = build_usage(masters, events, wf, scale_name, seed)

    if inject:
        out = inject_edge_cases(masters, events, certs, wf["work_order"], usage["alert"],
                                usage["audit_record"], usage["production_use"], scale_name, seed)
        body = {name: out[name] for name in CHANGED_BY_INJECTION}
        truth = out["ground_truth"]
    else:
        body = {
            "calibration_event": events, "certificate": certs,
            "work_order": wf["work_order"], "alert": usage["alert"],
            "audit_record": usage["audit_record"], "production_use": usage["production_use"],
        }
        truth = []

    tables = {
        "supplier": masters["supplier"],
        "instrument_type": masters["instrument_type"],
        "calibration_plan": masters["calibration_plan"],
        # current_status is READ from the logbook, never edited by hand (rule R6)
        "asset": apply_final_status(masters["asset"], body["audit_record"]),
        **body,
    }
    return tables, truth