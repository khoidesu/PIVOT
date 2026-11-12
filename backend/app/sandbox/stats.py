"""Thống kê trung thực cho sandbox: chênh lệch cặp (chiến lược khác − top-1), khoảng tin cậy bootstrap, tỷ lệ thắng, theo hồ sơ."""
import numpy as np

METRICS = ("km", "cost_vnd", "min_to_pickup", "min_to_icd")  # càng thấp càng tốt
RATES = ("late_pickup", "late_cutoff", "cutoff_flag")  # tỷ lệ (0/1 theo ca; kỳ vọng với random)
ALTS = ("random", "nearest", "first")
EPS = 1e-9
BOOT = 2000


def _pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q))


def _paired(diffs: np.ndarray, seed: int) -> dict:
    """diff = (chiến lược khác) − (top-1); DƯƠNG = top-1 tốt hơn (vì mọi chỉ số đều 'càng thấp càng tốt')."""
    rng = np.random.default_rng(seed)
    boots = diffs[rng.integers(0, len(diffs), size=(BOOT, len(diffs)))].mean(axis=1)
    return {"mean": float(diffs.mean()), "median": float(np.median(diffs)), "p10": _pct(diffs, 10), "p90": _pct(diffs, 90),
            "ci95": [_pct(boots, 2.5), _pct(boots, 97.5)], "win_rate": float((diffs >= -EPS).mean()), "strict_win_rate": float((diffs > EPS).mean())}


def _block(cases: list[dict], seed: int) -> dict:
    ok = [c for c in cases if c["feasible"]]
    out = {"n_cases": len(cases), "n_feasible": len(ok), "n_infeasible": len(cases) - len(ok)}
    if not ok:
        return out
    top = {m: np.array([c["top1"][m] for c in ok]) for m in (*METRICS, *RATES)}
    out["top1_mean"] = {m: float(top[m].mean()) for m in (*METRICS, *RATES)}
    out["vs"] = {}
    for alt in ALTS:
        a = {m: np.array([c[alt][m] for c in ok]) for m in (*METRICS, *RATES)}
        out["vs"][alt] = {"mean": {m: float(a[m].mean()) for m in (*METRICS, *RATES)},
                          "saving": {m: _paired(a[m] - top[m], seed + k) for k, m in enumerate(METRICS)},
                          "rate_diff": {m: float(a[m].mean() - top[m].mean()) for m in RATES}}
    base_km = np.array([c["static_baseline_km"] for c in ok])
    base_cost = np.array([c["static_baseline_cost_vnd"] for c in ok])
    out["vs_static_baseline"] = {"km_saved_mean": float((base_km - top["km"]).mean()), "cost_saved_vnd_mean": float((base_cost - top["cost_vnd"]).mean()),
                                 "share_better_than_baseline": float((top["km"] < base_km).mean())}
    out["top1_is_nearest_share"] = float(np.mean([c["top1_plate"] == c["nearest_plate"] for c in ok]))
    out["pass_gate_mean"] = float(np.mean([c["n_passed"] for c in ok]))
    return out


def summarize(cases: list[dict], seed: int) -> dict:
    s = _block(cases, seed)
    s["invalid_without_gate"] = {"first_in_list_rate": float(np.mean([c["first_ungated_invalid"] for c in cases])),
                                 "mean_share_of_fleet_failing_gate": float(np.mean([c["share_fleet_failing_gate"] for c in cases]))}
    s["by_profile"] = {p: _block([c for c in cases if c["profile"] == p], seed + 100) for p in sorted({c["profile"] for c in cases})}
    return s
