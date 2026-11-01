"""Step 10: regenerate twice with the same seed, then compare row counts and SHA-256 checksums.
    python -m src.reproduce --scale full"""
import argparse
import shutil
from pathlib import Path

from src.config import SCALES, SEED
from src.export import write_json_file
from src.generate import generate


def compare_runs(a, b):
    """a and b are the dicts returned by generate()."""
    names = sorted(set(a["checksums"]) | set(b["checksums"]))
    files = {}
    for name in names:
        left, right = a["checksums"].get(name), b["checksums"].get(name)
        files[name] = {"run_a": left, "run_b": right, "match": left is not None and left == right}
    counts_match = a["row_counts"] == b["row_counts"]
    checksums_match = all(f["match"] for f in files.values())
    return {"row_counts_match": counts_match, "checksums_match": checksums_match,
            "identical": counts_match and checksums_match, "files": files}


def render_report(result):
    verdict = "IDENTICAL: the dataset is reproducible" if result["identical"] else "DIFFERENT: not reproducible"
    lines = [
        "# Reproducibility report", "",
        f"Scale: `{result['scale']}` | Seed: `{result['seed']}` | Result: **{verdict}**", "",
        f"Command, run twice into two separate folders: "
        f"`python -m src.generate --scale {result['scale']} --seed {result['seed']}`", "",
        "## Row counts", "",
        "| table | rows run A | rows run B | match |", "|---|---|---|---|",
    ]
    for name, n in result["row_counts"].items():
        lines.append(f"| {name} | {n} | {n} | yes |" if result["row_counts_match"]
                     else f"| {name} | {n} | see JSON | check |")
    lines += ["", "## SHA-256 checksums", "",
              "| file | run A | run B | match |", "|---|---|---|---|"]
    for name, f in result["files"].items():
        lines.append(f"| {name} | `{f['run_a']}` | `{f['run_b']}` | {'yes' if f['match'] else 'NO'} |")
    return "\n".join(lines) + "\n"


def reproduce(scale_name="full", seed=SEED, work="repro", keep=False):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    folders, infos = [], []
    for label in ("a", "b"):
        folder = work / f"{scale_name}_run_{label}"
        infos.append(generate(scale_name, seed, folder))
        folders.append(folder)

    result = {"scale": scale_name, "seed": seed, "row_counts": infos[0]["row_counts"],
              **compare_runs(infos[0], infos[1])}
    write_json_file(result, work / f"reproducibility_{scale_name}.json")
    with open(work / f"reproducibility_{scale_name}.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(render_report(result))
    if not keep:                                   # the big folders are not needed any more
        for folder in folders:
            shutil.rmtree(folder)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prove the generator is reproducible.")
    parser.add_argument("--scale", choices=sorted(SCALES), default="full")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--keep", action="store_true", help="keep the two generated folders")
    args = parser.parse_args(argv)

    result = reproduce(args.scale, args.seed, keep=args.keep)
    matched = sum(f["match"] for f in result["files"].values())
    print(f"Scale: {args.scale}   seed: {args.seed}")
    print(f"  row counts match : {result['row_counts_match']}")
    print(f"  files compared   : {len(result['files'])}   identical: {matched}")
    print(f"  RESULT           : {'IDENTICAL, reproducible' if result['identical'] else 'DIFFERENT'}")
    print(f"  report           : repro/reproducibility_{args.scale}.md")


if __name__ == "__main__":
    main()