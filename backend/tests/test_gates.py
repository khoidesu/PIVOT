"""Hard gate (DRAFT 5.1, điều kiện qua Ngày 2): loại đúng xe thiếu tải / sai hàng / trễ giờ; thiếu input → UNKNOWN."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.matching import gates


@pytest.fixture()
def world(seeded):
    with SessionLocal() as s:
        params = s.execute(select(m.AssumptionSet)).scalars().first().params
        ships = {x.code: x for x in s.execute(select(m.Shipment)).scalars()}
        veh = {x.plate: x for x in s.execute(select(m.Vehicle)).scalars()}
        wins = {w.vehicle_id: w for w in s.execute(select(m.AvailabilityWindow)).scalars()}
        slots = list(s.execute(select(m.Slot).order_by(m.Slot.start_at)).scalars())
        yield {"params": params, "ships": ships, "veh": veh, "wins": wins, "slots": slots, "now": datetime.now(timezone.utc)}


def run(w, lot, plate, slot_idx=10):
    v = w["veh"][plate]
    return gates.evaluate(w["ships"][lot], v, w["wins"][v.id], w["slots"][slot_idx], w["now"], w["params"])


def codes(verdict):
    return {r.reason_code for r in verdict.rejections}


def test_good_match_passes_all_gates(world):
    v = run(world, "LOT-A-001", "51C-100.01")
    assert v.status == "PASS" and not v.rejections
    assert v.rule_version == "rules-v1"


def test_undersized_vehicle_is_rejected(world):
    v = run(world, "LOT-A-003", "51C-100.05")  # 20t vào xe 8t
    assert v.status == "FAIL" and gates.CAPACITY_EXCEEDED in codes(v)


def test_wrong_cargo_type_is_rejected(world):
    assert gates.CARGO_INCOMPATIBLE in codes(run(world, "LOT-A-005", "51C-100.01"))  # hàng lạnh vào xe khô
    assert gates.CARGO_INCOMPATIBLE in codes(run(world, "LOT-A-001", "51C-100.07"))  # hàng khô vào xe lạnh


def test_late_vehicle_misses_pickup_window(world):
    v = run(world, "LOT-A-006", "51C-100.09")  # xe rảnh sau deadline của lô
    assert v.status == "FAIL" and gates.PICKUP_WINDOW_MISSED in codes(v)


def test_cutoff_risk(world):
    assert gates.CUTOFF_RISK in codes(run(world, "LOT-A-008", "51C-100.01"))


def test_stale_position_is_rejected(world):
    assert gates.DATA_STALE in codes(run(world, "LOT-A-001", "51C-100.08"))


def test_offline_vehicle_unavailable(world):
    assert gates.VEHICLE_UNAVAILABLE in codes(run(world, "LOT-A-001", "51C-100.10"))


def test_full_slot_rejected(world):
    full = next(i for i, sl in enumerate(world["slots"]) if sl.remaining == 0)
    assert gates.SLOT_FULL in codes(run(world, "LOT-A-001", "51C-100.01", slot_idx=full))


def test_missing_required_field_is_unknown_never_pass(world):
    v = run(world, "LOT-A-007", "51C-100.01")  # lô thiếu trọng lượng/thể tích
    assert v.status == "UNKNOWN"
    cap = next(r for r in v.results if r.gate == "capacity")
    assert cap.status == "UNKNOWN" and "shipment.weight_kg" in cap.detail["missing"]


def test_fail_takes_precedence_over_unknown(world):
    v = run(world, "LOT-A-007", "51C-100.07")  # thiếu dữ liệu nhưng sai loại hàng chắc chắn
    assert v.status == "FAIL"


def test_no_slot_is_unknown(world):
    w = world
    veh = w["veh"]["51C-100.01"]
    v = gates.evaluate(w["ships"]["LOT-A-001"], veh, w["wins"][veh.id], None, w["now"], w["params"])
    assert v.status == "UNKNOWN"
