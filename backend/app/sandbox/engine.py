"""Chạy sandbox: mỗi kịch bản → `evaluate_candidates` (hard gate + MatchScore thật) → so sánh xe điểm cao nhất với các cách chọn khác.

Chiến lược so sánh (đều CHỈ trong các xe đã qua hard gate, trừ mục "không gate"):
  top1    — xe điểm cao nhất (hệ thống đề xuất)
  random  — chọn ngẫu nhiên: lấy KỲ VỌNG trên mọi xe đạt (không phụ thuộc may rủi của một lần bốc)
  nearest — xe gần điểm lấy nhất theo km (heuristic thủ công thường gặp)
  first   — xe đầu danh sách theo biển số (không tối ưu gì)
  ungated — xe đầu danh sách KHÔNG qua hard gate: đo tỷ lệ chọn phải xe không đủ điều kiện (giá trị của hard gate)
"Thực tế" = ETA luật + nhiễu mô phỏng độc lập với dự báo (cùng phân phối với lịch sử ETA ML mô phỏng) — không chấm bài bằng chính dự báo.
"""
from datetime import datetime, timedelta

from ..eta import baseline, ml
from ..matching import gates
from ..matching.service import evaluate_candidates
from . import scenarios, stats


def default_params() -> dict:
    from ..seed import ASSUMPTIONS_V1
    return ASSUMPTIONS_V1


def _outcome(cand: dict, sc: dict, params: dict) -> dict:
    """Kết quả 'thực tế' của việc chọn một ứng viên (km, tiền, phút, trễ hạn)."""
    ship, now, win = sc["shipment"], sc["now"], cand["window"]
    km = float(cand["scored"].deadhead_km)  # cùng deadhead_km mà MatchScore dùng
    n_dead, n_transit = sc["noise"][cand["vehicle"].id]
    local = now.astimezone(scenarios.TZ)
    mult = ml._band_mult(local.hour) * (1 + 0.18 * ml.sim_weather(local.timetuple().tm_yday, local.hour))  # cùng hệ số khung giờ/mưa như lịch sử ETA mô phỏng
    dead_min = km / params["eta"]["live_speed_kmh_fallback"] * 60 * mult * max(1 + n_dead, 0.3)
    start = max(win.free_from, now)
    at_pickup = max(start + timedelta(minutes=dead_min), ship.ready_at)
    transit = params["transit_minutes"] * mult * max(1 + ml.NOISE_SIGMA * n_transit, 0.3)
    at_icd = at_pickup + timedelta(minutes=transit + params["handling_minutes"])
    eta = baseline.build(gates.pickup_eta(win, ship, now, params), now, params, ship.cutoff_at)  # dự báo của hệ thống (độc lập với 'thực tế')
    return {"km": km, "cost_vnd": km * params["cost_per_km_vnd"],
            "min_to_pickup": (at_pickup - now).total_seconds() / 60, "min_to_icd": (at_icd - now).total_seconds() / 60,
            "late_pickup": float(at_pickup > ship.pickup_deadline or at_pickup > win.free_to), "late_cutoff": float(at_icd > ship.cutoff_at),
            "cutoff_flag": float(bool(eta.get("cutoff_risk_p90")))}


def _mean(rows: list[dict]) -> dict:
    return {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}


def run_scenario(sc: dict, params: dict) -> dict:
    """Một kịch bản. Không khả thi (không xe nào qua hard gate) → ghi nhận, KHÔNG ép ghép."""
    passed, rejected, needs, scored = evaluate_candidates(sc["shipment"], sc["vehicles"], sc["windows"], sc["slots"], set(), sc["now"], params, sc["locs"])
    row = {"i": sc["i"], "profile": sc["profile"], "n_vehicles": len(sc["vehicles"]), "n_passed": len(passed),
           "n_failed": len(rejected) + len(needs), "feasible": bool(scored)}
    passed_ids = {e["vehicle"].id for e in passed}
    row["first_ungated_invalid"] = bool(sc["vehicles"]) and sc["vehicles"][0].id not in passed_ids
    row["share_fleet_failing_gate"] = round((len(rejected) + len(needs)) / max(len(sc["vehicles"]), 1), 3)
    if not scored:
        return row
    outcomes = {id(e): _outcome(e, sc, params) for e in scored}
    top, nearest = scored[0], min(scored, key=lambda e: (e["scored"].deadhead_km, e["vehicle"].plate))
    first = min(scored, key=lambda e: e["vehicle"].plate)
    row.update({
        "top1_plate": top["vehicle"].plate, "top1_score": top["scored"].score, "nearest_plate": nearest["vehicle"].plate, "first_plate": first["vehicle"].plate,
        "top1": outcomes[id(top)], "nearest": outcomes[id(nearest)], "first": outcomes[id(first)], "random": _mean(list(outcomes.values())),
        "static_baseline_km": float(params["empty_km_baseline"]), "static_baseline_cost_vnd": params["empty_km_baseline"] * params["cost_per_km_vnd"],
    })
    return row


def run_sandbox(n: int = 100, seed: int = 42, params: dict | None = None, profile: str = "mixed", assumption_version: str | None = None) -> dict:
    """Chạy `n` kịch bản xác định. Không ghi DB. Trả {meta, summary, cases}."""
    if not 1 <= n <= 1000:
        raise ValueError("n must be between 1 and 1000")
    params = params or default_params()
    cases = [run_scenario(scenarios.make_scenario(i, seed, profile), params) for i in range(n)]
    return {"meta": {"n": n, "seed": seed, "profile": profile, "assumption_version": assumption_version or "assume-v2",
                     "rule_version": params["rule_version"], "generated_at": datetime.now().astimezone().isoformat(), "is_simulated": True,
                     "label": "MÔ PHỎNG — không phải lợi ích đã xác minh",
                     "method": "evaluate_candidates (hard gate + MatchScore) + baseline ETA; 'thực tế' = ETA luật × nhiễu mô phỏng"},
            "summary": stats.summarize(cases, seed), "cases": cases}
