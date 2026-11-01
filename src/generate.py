"""Builds the whole dataset. One command:
    python -m src.generate --scale full --seed 20261022 --out data/full"""
import argparse
import shutil
from pathlib import Path

from src.config import SCALES, SEED
from src.evaluate import evaluate_dataset, render_markdown, write_reports
from src.events import build_calibrations
from src.export import export_all
from src.inject import inject_edge_cases, write_ground_truth
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


def _prepare(out_dir):
    """Make an empty output folder. Only a folder WE made earlier may be replaced."""
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        if not (out / "dataset_manifest.json").is_file():
            raise ValueError(f"'{out}' is not empty and was not created by this generator; "
                             "choose another --out folder")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def generate(scale_name: str = "full", seed: int = SEED, out_dir=None):
    """Build, validate, evaluate and export. Returns {"row_counts", "checksums"}."""
    out = _prepare(out_dir or Path("data") / scale_name)
    tables, truth = build_dataset(scale_name, seed)
    result, text = evaluate_dataset(tables, truth)
    write_reports(result, render_markdown(result, scale_name, text), out / "reports")
    write_ground_truth(truth, out / "ground_truth")          # a SEPARATE folder
    return export_all(tables, truth, out, scale_name, seed, result)   # writes checksums LAST


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the synthetic calibration dataset.")
    parser.add_argument("--scale", choices=sorted(SCALES), default="full")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=None, help="output folder (default: data/<scale>)")
    args = parser.parse_args(argv)

    out = args.out or f"data/{args.scale}"
    info = generate(args.scale, args.seed, out)
    print(f"Scale: {args.scale}   seed: {args.seed}")
    print(f"Wrote: {out}")
    for name, n in info["row_counts"].items():
        print(f"  {name:18s} {n:>8} rows")
    print(f"  files fingerprinted: {len(info['checksums'])}   (see {out}/checksums.sha256)")


if __name__ == "__main__":
    main()