"""Sandbox mô phỏng lợi ích: xác định, không ghi DB, dùng đúng đường code thật, thống kê khớp tính tay, phân quyền."""
import numpy as np
import pytest
from sqlalchemy import func, select

from app import fleet
from app import models as m
from app.db import SessionLocal
from app.matching import gates, score
from app.matching import service as matching_service
from app.models import Base
from app.sandbox import engine, run_sandbox, scenarios, stats
from app.sandbox import run as sandbox_cli
from app.seed import ASSUMPTIONS_V1
from tests.conftest import auth

P = ASSUMPTIONS_V1


def strip(r):  # bỏ trường thời gian sinh để so sánh
    return {"summary": r["summary"], "cases": r["cases"], "meta": {k: v for k, v in r["meta"].items() if k != "generated_at"}}


# ---------------------------------------------------------------- xác định + đường code thật
def test_same_seed_gives_identical_results_and_a_different_seed_differs():
    a, b, c = run_sandbox(40, 7, P), run_sandbox(40, 7, P), run_sandbox(40, 8, P)
    assert strip(a) == strip(b)
    assert strip(a) != strip(c)


def test_sandbox_and_the_real_matcher_share_one_function():
    assert engine.evaluate_candidates is matching_service.evaluate_candidates          # không có công thức thứ hai
    import inspect
    assert "evaluate_candidates(" in inspect.getsource(matching_service.run_match)      # bộ ghép thật cũng đi qua đó


def test_chosen_vehicle_always_passes_the_hard_gate_and_is_the_top_ranked():
    for i in range(60):
        sc = scenarios.make_scenario(i, 11)
        passed, rejected, needs, scored = matching_service.evaluate_candidates(
            sc["shipment"], sc["vehicles"], sc["windows"], sc["slots"], set(), sc["now"], P, sc["locs"])
        if not scored:
            continue
        top = scored[0]
        assert top["verdict"].status == "PASS" and all(r.status == "PASS" for r in top["verdict"].results)
        assert top["scored"].score == max(e["scored"].score for e in scored)
        # xe bị loại không bao giờ được chấm điểm
        assert {e["vehicle"].id for e in scored} == {e["vehicle"].id for e in passed}
        assert not ({e["vehicle"].id for e in rejected + needs} & {e["vehicle"].id for e in scored})


def test_infeasible_cases_are_counted_not_forced():
    r = run_sandbox(100, 42, P)
    bad = [c for c in r["cases"] if not c["feasible"]]
    assert bad and r["summary"]["n_infeasible"] == len(bad) and r["summary"]["n_feasible"] == 100 - len(bad)
    assert all("top1" not in c for c in bad)                                              # không ép ghép


def test_hard_gate_has_visible_value_in_the_summary():
    s = run_sandbox(100, 42, P)["summary"]
    assert s["invalid_without_gate"]["first_in_list_rate"] > 0.2                            # chọn bừa không gate hay rơi vào xe không đủ điều kiện


# ---------------------------------------------------------------- khớp tính tay
def test_random_strategy_mean_km_matches_an_independent_hand_computation():
    sc = scenarios.make_scenario(3, 42)
    row = engine.run_scenario(sc, P)
    assert row["feasible"]
    passed, _r, _n, _s = matching_service.evaluate_candidates(sc["shipment"], sc["vehicles"], sc["windows"], sc["slots"], set(), sc["now"], P, sc["locs"])
    origin = sc["locs"][sc["shipment"].origin_location_id]
    kms = []
    for e in passed:
        y = sc["locs"][e["window"].location_id]
        kms.append(round(score.haversine_km(y.lat, y.lng, origin.lat, origin.lng) * 1.3, 1))   # tính lại độc lập từ toạ độ
    assert row["random"]["km"] == pytest.approx(np.mean(kms)) and row["top1"]["km"] in kms
    assert row["random"]["cost_vnd"] == pytest.approx(np.mean(kms) * P["cost_per_km_vnd"])


def test_paired_statistics_on_a_tiny_known_sample():
    out = stats._paired(np.array([1.0, 2.0, 3.0]), 0)
    assert out["mean"] == 2.0 and out["median"] == 2.0 and out["win_rate"] == 1.0 and out["strict_win_rate"] == 1.0
    assert 1.0 <= out["ci95"][0] <= 2.0 <= out["ci95"][1] <= 3.0
    mixed = stats._paired(np.array([-1.0, 0.0, 1.0, 2.0]), 0)
    assert mixed["win_rate"] == 0.75 and mixed["strict_win_rate"] == 0.5                      # "không tệ hơn" gồm cả hoà


def test_savings_are_positive_on_average_against_random_and_first():
    s = run_sandbox(100, 42, P)["summary"]
    for alt in ("random", "first"):
        km = s["vs"][alt]["saving"]["km"]
        assert km["mean"] > 0 and km["ci95"][0] > 0                                       # khoảng tin cậy 95% nằm hẳn phía dương


def test_nearest_vehicle_can_beat_top1_on_km_and_the_report_says_so():
    s = run_sandbox(100, 42, P)["summary"]
    assert s["vs"]["nearest"]["saving"]["km"]["mean"] < 0                                     # trung thực: top-1 không phải lúc nào cũng gần nhất
    md = sandbox_cli.to_markdown(run_sandbox(100, 42, P))
    assert "xe gần nhất" in md and "MÔ PHỎNG" in md and "Giới hạn" in md


# ---------------------------------------------------------------- toạ độ khớp DB seed
def test_scenario_coordinates_match_the_seeded_locations(client):
    with SessionLocal() as s:
        by_name = {x.name: x for x in s.execute(select(m.Location)).scalars()}
    want = {"Depot Thủ Đức (mô phỏng)": ("depot", "yard"), "KCN Sóng Thần (mô phỏng)": ("kcn1",), "KCN VSIP I (mô phỏng)": ("kcn2",), "ICD Cảng C (mô phỏng)": ("icd",)}
    world = {x.name: x for x in scenarios.world()["locs"].values()}
    for name, (key, *_k) in want.items():
        assert (by_name[name].lat, by_name[name].lng) == (world[key].lat, world[key].lng), name
    for key, name, lat, lng in fleet.YARDS:
        assert (by_name[name].lat, by_name[name].lng) == (lat, lng) == (world[key.removeprefix("yard-")].lat, world[key.removeprefix("yard-")].lng)


# ---------------------------------------------------------------- API + không ghi DB + phân quyền
def counts():
    with SessionLocal() as s:
        return {t.name: s.execute(select(func.count()).select_from(t)).scalar_one() for t in Base.metadata.sorted_tables}


def test_endpoints_never_write_to_the_real_tables(client):
    before = counts()
    assert client.get("/v1/benefits/sandbox/latest", headers=auth("shipper_a")).status_code == 200
    r = client.post("/v1/benefits/sandbox/run", json={"n": 50, "seed": 5}, headers=auth("dispatch"))
    assert r.status_code == 200
    assert counts() == before                                                              # kể cả benefit_ledger
    assert before["benefit_ledger"] == 0 or counts()["benefit_ledger"] == before["benefit_ledger"]


def test_only_the_dispatcher_can_run_but_anyone_can_read_the_latest(client):
    for user in ("shipper_a", "carrier_b", "node_c"):
        assert client.post("/v1/benefits/sandbox/run", json={}, headers=auth(user)).status_code == 403
    assert client.post("/v1/benefits/sandbox/run", json={"n": 301}, headers=auth("dispatch")).status_code == 422
    r = client.post("/v1/benefits/sandbox/run", json={"n": 30, "seed": 3}, headers=auth("dispatch")).json()
    assert r["meta"]["is_simulated"] is True and "MÔ PHỎNG" in r["meta"]["label"] and r["meta"]["n"] == 30
    latest = client.get("/v1/benefits/sandbox/latest", headers=auth("carrier_b")).json()
    assert latest["meta"]["seed"] == 3 and latest["summary"] == r["summary"]


def test_real_benefit_routes_still_work_next_to_the_sandbox_routes(client):
    assert client.get("/v1/benefits", headers=auth("shipper_a")).status_code == 200
    assert client.get("/v1/benefits/00000000-0000-0000-0000-000000000000", headers=auth("shipper_a")).status_code == 404   # không bị nuốt thành sandbox


def test_cli_writes_the_report_and_csv(tmp_path):
    out, csv = tmp_path / "r.md", tmp_path / "c.csv"
    assert sandbox_cli.main(["--n", "20", "--seed", "1", "--out", str(out), "--csv", str(csv)]) == 0
    assert "MÔ PHỎNG" in out.read_text(encoding="utf-8") and len(csv.read_text(encoding="utf-8").splitlines()) == 21
