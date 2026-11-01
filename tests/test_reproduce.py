import copy

from src.reproduce import compare_runs, reproduce


def test_reproduce_starter_is_identical_and_cleans_up(tmp_path):
    result = reproduce("starter", work=tmp_path)
    assert result["identical"] is True
    assert result["row_counts_match"] and result["checksums_match"]
    assert all(f["match"] for f in result["files"].values())
    assert (tmp_path / "reproducibility_starter.md").is_file()
    assert (tmp_path / "reproducibility_starter.json").is_file()
    assert not (tmp_path / "starter_run_a").exists()
    assert not (tmp_path / "starter_run_b").exists()


def test_comparison_notices_a_difference():
    a = {"row_counts": {"asset": 100}, "checksums": {"csv/asset.csv": "aaa", "csv/supplier.csv": "bbb"}}
    assert compare_runs(a, copy.deepcopy(a))["identical"]

    changed = copy.deepcopy(a)
    changed["checksums"]["csv/asset.csv"] = "zzz"
    assert not compare_runs(a, changed)["checksums_match"]

    fewer = copy.deepcopy(a)
    fewer["row_counts"]["asset"] = 99
    assert not compare_runs(a, fewer)["row_counts_match"]

    missing = copy.deepcopy(a)
    del missing["checksums"]["csv/supplier.csv"]
    assert not compare_runs(a, missing)["identical"]