"""Hiệu năng ghép (CLAUDE.md mục 8 / DRAFT bảng 5): P95 < 2 giây cho 20 xe × 50 lô (loại thời gian gọi API ngoài)."""
import statistics
import time
import uuid

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from tests.conftest import auth


def _scale_up(vehicles_total=20, lots_total=50):
    with SessionLocal() as s:
        veh = list(s.execute(select(m.Vehicle)).scalars())
        for i in range(vehicles_total - len(veh)):
            src = veh[i % len(veh)]
            v = m.Vehicle(tenant_id=src.tenant_id, plate=f"51C-200.{i:02d}", cargo_types=src.cargo_types, capacity_kg=src.capacity_kg,
                          capacity_m3=src.capacity_m3, status="available", position_updated_at=src.position_updated_at)
            s.add(v)
            s.flush()
            w = s.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == src.id)).scalars().first()
            s.add(m.AvailabilityWindow(vehicle_id=v.id, location_id=w.location_id, free_from=w.free_from, free_to=w.free_to))
        lots = list(s.execute(select(m.Shipment).where(m.Shipment.code.like("LOT-A-%"))).scalars())
        for i in range(lots_total - len(lots)):
            src = lots[i % len(lots)]
            s.add(m.Shipment(tenant_id=src.tenant_id, code=f"LOT-A-P{i:03d}", cargo_type=src.cargo_type, weight_kg=src.weight_kg,
                             volume_m3=src.volume_m3, origin_location_id=src.origin_location_id, dest_location_id=src.dest_location_id,
                             ready_at=src.ready_at, pickup_deadline=src.pickup_deadline, cutoff_at=src.cutoff_at, data_updated_at=src.data_updated_at))
        s.commit()
        return [x.id for x in s.execute(select(m.Shipment).where(m.Shipment.code.like("LOT-A-%"))).scalars()][:lots_total]


def test_match_p95_under_two_seconds_for_20_vehicles_and_50_lots(client):
    lot_ids = _scale_up()
    assert len(lot_ids) == 50
    with SessionLocal() as s:
        assert s.execute(select(m.Vehicle)).scalars().all().__len__() == 20
    times = []
    for lid in lot_ids:
        t0 = time.perf_counter()
        r = client.post("/v1/match-runs", json={"shipment_id": str(lid)}, headers=auth("shipper_a"))
        times.append(time.perf_counter() - t0)
        assert r.status_code == 200 and r.json()["evaluated_vehicles"] == 20
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    print(f"\nmatch-run 20 xe x 50 lô: p50={statistics.median(times)*1000:.0f}ms p95={p95*1000:.0f}ms max={times[-1]*1000:.0f}ms")
    assert p95 < 2.0
