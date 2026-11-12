"""Bộ sinh dữ liệu ETA mô phỏng (docs/ETA_DATASET_SPEC.md): tái lập, chia theo thời gian, không rò rỉ, khớp khung giờ của baseline.py."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from app import eta_data_gen as g
from app.eta import baseline
from app.seed import ASSUMPTIONS_V1

TPD = 6  # ~1.6k dòng: đủ cho test, chạy nhanh


@pytest.fixture(scope="module")
def rows():
    return g.generate(TPD)


def test_generation_is_deterministic():
    assert g.generate(TPD) == g.generate(TPD)


def test_columns_types_and_ranges(rows):
    assert list(rows[0]) == g.COLUMNS
    assert [r["trip_id"] for r in rows] == list(range(1, len(rows) + 1))
    for r in rows:
        assert all(v is not None and v == v for v in r.values())                      # không NaN/None
        assert g.PARAMS["distance_clip_km"][0] <= r["distance_km"] <= g.PARAMS["distance_clip_km"][1]
        assert 0 <= r["hour"] <= 23 and 0 <= r["weekday"] <= 6 and r["is_weekend"] == int(r["weekday"] >= 5)
        assert r["rain_mm_h"] >= 0 and 0 <= r["wind_kmh"] <= 60 and r["actual_transit_min"] >= 10
        assert r["route_id"] in g.ROUTES and r["vehicle_class"] in g.VEHICLES
        assert r["rule_dist_p90_min"] > r["rule_dist_min"] > 0


def test_rows_are_time_ordered_and_split_by_time_not_shuffled(rows):
    ts = [datetime.fromisoformat(r["depart_at"]) for r in rows]
    assert ts == sorted(ts) and all(t.utcoffset().total_seconds() == 7 * 3600 for t in ts)
    order = {"train": 0, "calib": 1, "test": 2}
    seq = [order[r["split"]] for r in rows]
    assert seq == sorted(seq) and set(seq) == {0, 1, 2}                                  # mỗi tập là một khoảng liền, đúng thứ tự thời gian
    assert all(datetime.fromisoformat(r["depart_at"]).date() < g.CALIB_FROM for r in rows if r["split"] == "train")
    assert all(datetime.fromisoformat(r["depart_at"]).date() >= g.TEST_FROM for r in rows if r["split"] == "test")


def test_band_matches_the_production_baseline_definition(rows):
    for r in rows[:400]:
        t = datetime.fromisoformat(r["depart_at"])
        assert baseline.band_for(t, ASSUMPTIONS_V1) == r["band"]                         # cùng định nghĩa khung giờ với app/eta/baseline.py


def test_baseline_median_uses_train_only_no_leakage(rows):
    train = [r for r in rows if r["split"] == "train"]
    for r in rows[::37]:
        grp = [x["actual_transit_min"] for x in train if x["route_id"] == r["route_id"] and x["band"] == r["band"]]
        assert r["baseline_median_min"] == round(float(np.median(grp)), 1)


def test_schema_has_no_leaky_features_and_one_hot_layout_is_consistent():
    s = g.schema("x", 1)
    base = set(s["numeric_features"]) | set(s["categorical_features"])
    assert not (base & set(s["forbidden_as_features"]))
    assert not ({"actual_transit_min", "gate_queue_min", "had_incident", "scenario_tag", "split"} & base)
    assert len(s["input_order"]) == 12 and s["input_order"][:7] == g.NUMERIC
    assert s["input_order"][7:] == ["route_id=KCN_A_ICD", "route_id=KCN_B_ICD", "vehicle_class=heavy", "vehicle_class=medium", "vehicle_class=light"]
    assert set(s["forbidden_as_features"]) <= set(g.COLUMNS) and set(s["numeric_features"]) <= set(g.COLUMNS)


def test_drift_only_in_test_period_and_can_be_switched_off(rows):
    assert {r["scenario_tag"] for r in rows if r["split"] != "test"} <= {"normal", "incident"}
    assert any(r["scenario_tag"] == "drift" for r in rows if r["split"] == "test")
    assert not any(r["scenario_tag"] == "drift" for r in g.generate(TPD, drift=False))
    slow, flat = g.generate(TPD)[-300:], g.generate(TPD, drift=False)[-300:]
    assert np.mean([r["actual_transit_min"] for r in slow]) > np.mean([r["actual_transit_min"] for r in flat])


def test_label_median_is_calibrated_near_the_systems_90_minute_assumption():
    big = g.generate(20)
    near = [r["actual_transit_min"] for r in big if 25 <= r["distance_km"] <= 27 and r["band"] == "normal" and r["split"] == "train"]
    assert 80 <= float(np.median(near)) <= 100


def test_write_all_creates_the_four_files_and_hashes_match(tmp_path: Path):
    info = g.write_all(tmp_path, TPD)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ETA_TRAINING_GUIDE.md", "eta_generator_params.json", "eta_schema.json", "eta_trips.csv"]
    sch = json.loads((tmp_path / "eta_schema.json").read_text(encoding="utf-8"))
    assert sch["csv_sha256"] == info["sha256"] == hashlib.sha256((tmp_path / "eta_trips.csv").read_bytes()).hexdigest()
    assert sch["rows"] == len((tmp_path / "eta_trips.csv").read_text(encoding="utf-8").strip().splitlines()) - 1
    assert sch["is_simulated"] is True


def test_cli_prints_a_summary(tmp_path, capsys):
    assert g.main(["--out", str(tmp_path), "--trips-per-day", "4", "--no-drift"]) == 0
    out = capsys.readouterr().out
    assert "chuyến" in out and "không có drift" in out and (tmp_path / "eta_trips.csv").exists()


def test_kaggle_notebook_is_valid_and_every_code_cell_compiles():
    nb_path = Path(__file__).resolve().parents[2] / "data" / "eta" / "eta_train_kaggle.ipynb"
    if not nb_path.exists():
        pytest.skip("notebook chưa được tạo")
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4 and len(nb["cells"]) >= 10
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    compile(src, "eta_train_kaggle.ipynb", "exec")                                       # lỗi cú pháp sẽ bị bắt ở đây
    for must in ("torch.onnx.export", "eta_model.onnx", "eta_model_card.json", "FORBIDDEN", "p90_offset"):
        assert must in src
