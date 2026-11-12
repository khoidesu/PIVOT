"""Sinh kịch bản MÔ PHỎNG xác định (seed cố định): 1 lô + đội xe + slot ICD + nhiễu 'thực tế' dùng chung cho mọi lựa chọn.

Đối tượng là SimpleNamespace có đúng các thuộc tính mà hard gate / MatchScore đọc — không cần DB.
Nhiễu "thực tế" (common random numbers): mỗi xe một cặp nhiễu cố định, mọi chiến lược chọn dùng chung → chênh lệch chỉ đến từ việc CHỌN xe nào.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import numpy as np

from .. import fleet

TZ = timezone(timedelta(hours=7))  # giờ vận hành (khớp assume-v2: tz_offset_hours = 7)
DAY = datetime(2026, 11, 11, tzinfo=TZ)
_NS = uuid.UUID("6f1c6c1e-0000-4000-8000-00000000c003")
NODE_ORG = uuid.uuid5(_NS, "node")
PROFILES = ("dense", "sparse", "peak")

# toạ độ trùng địa điểm seed (test đối chiếu với DB seed): điểm lấy hàng, ICD, bãi
ZONES = (("kcn1", 10.90, 106.74), ("kcn2", 10.92, 106.72))
ICD = ("icd", 10.85, 106.80)
YARDS = (("depot", 10.87, 106.77), *((k.removeprefix("yard-"), lat, lng) for k, _n, lat, lng in fleet.YARDS))

# hồ sơ kịch bản: số xe, trọng số bãi (depot, hiep-binh, long-binh, an-phu), giờ bắt đầu (giờ vận hành), độ rộng hạn lấy hàng, tỷ lệ vị trí tươi
CFG = {
    "dense": dict(n_veh=(14, 21), yard_w=(0.4, 0.2, 0.2, 0.2), hour=10.0, slack=(90, 300), cutoff_extra=(180, 480), fresh=0.85),
    "sparse": dict(n_veh=(8, 11), yard_w=(0.1, 0.1, 0.4, 0.4), hour=14.0, slack=(60, 200), cutoff_extra=(150, 420), fresh=0.75),
    "peak": dict(n_veh=(12, 19), yard_w=(0.25, 0.25, 0.25, 0.25), hour=7.5, slack=(45, 150), cutoff_extra=(130, 300), fresh=0.85),
}


def _loc(key: str, lat: float, lng: float, kind: str) -> NS:
    return NS(id=uuid.uuid5(_NS, key), name=key, kind=kind, lat=lat, lng=lng)


def world() -> dict:
    locs = {x.id: x for x in [_loc(k, a, b, "industrial_zone") for k, a, b in ZONES] + [_loc(ICD[0], ICD[1], ICD[2], "icd")]
            + [_loc(k, a, b, "yard") for k, a, b in YARDS]}
    return {"locs": locs, "zones": [uuid.uuid5(_NS, k) for k, *_ in ZONES], "icd": uuid.uuid5(_NS, ICD[0]), "yards": [uuid.uuid5(_NS, k) for k, *_ in YARDS]}


def _uuid(rng: np.random.Generator) -> uuid.UUID:
    return uuid.UUID(int=int(rng.integers(1, 2**62)) << 32 | int(rng.integers(1, 2**31)))


def profile_for(i: int, profile: str) -> str:
    """`mixed`: lần lượt dense / sparse / peak (≈ 1/3 mỗi loại); còn lại: một hồ sơ cố định."""
    return PROFILES[i % 3] if profile == "mixed" else profile


def make_scenario(i: int, seed: int, profile: str = "mixed") -> dict:
    prof = profile_for(i, profile)
    cfg = CFG[prof]
    rng = np.random.default_rng(np.random.SeedSequence([seed, i]))
    w = world()
    now = DAY + timedelta(hours=cfg["hour"], minutes=float(rng.uniform(0, 20)))
    ready = now + timedelta(minutes=float(rng.uniform(0, 90)))
    deadline = ready + timedelta(minutes=float(rng.uniform(*cfg["slack"])))
    cutoff = deadline + timedelta(minutes=float(rng.uniform(*cfg["cutoff_extra"])))
    kg = float(rng.choice([6000, 9000, 12000, 15000, 18000, 21000], p=[0.1, 0.2, 0.25, 0.2, 0.15, 0.1]))
    cold = bool(rng.random() < 0.1)
    ship = NS(id=_uuid(rng), cargo_type="cold" if cold else "dry", weight_kg=kg, volume_m3=round(kg / 400 * float(rng.uniform(0.9, 1.3)), 1),
              ready_at=ready, pickup_deadline=deadline, cutoff_at=cutoff, data_updated_at=now - timedelta(minutes=5),
              origin_location_id=w["zones"][int(rng.integers(0, len(w["zones"])))], dest_location_id=w["icd"])
    vehicles, windows, noise = [], {}, {}
    for j in range(int(rng.integers(cfg["n_veh"][0], cfg["n_veh"][1]))):
        cap = float(rng.choice([10000, 16000, 24000]))
        v = NS(id=_uuid(rng), plate=f"SIM-{i:03d}-{j:02d}", cargo_types=["cold"] if rng.random() < 0.12 else ["dry"], capacity_kg=cap,
               capacity_m3=round(cap / 400 * 1.4, 1), status="offline" if rng.random() < 0.08 else "available",
               position_updated_at=now - timedelta(minutes=float(rng.uniform(0, 4) if rng.random() < cfg["fresh"] else rng.uniform(6, 40))))
        free_from = now + timedelta(minutes=float(rng.uniform(-60, 90)))
        windows[v.id] = NS(vehicle_id=v.id, location_id=w["yards"][int(rng.choice(len(w["yards"]), p=cfg["yard_w"]))],
                           free_from=free_from, free_to=free_from + timedelta(hours=float(rng.uniform(3, 10))))
        noise[v.id] = (float(rng.normal(0, 0.15)), float(rng.normal(0, 1.0)))  # (nhiễu thời gian chạy rỗng, hệ số nhiễu trung chuyển)
        vehicles.append(v)
    vehicles.sort(key=lambda v: v.plate)
    slots = []
    for k in range(10):
        start = now + timedelta(minutes=30 + 30 * k)
        cap = int(rng.integers(2, 5))
        slots.append(NS(id=_uuid(rng), node_org_id=NODE_ORG, location_id=w["icd"], start_at=start, end_at=start + timedelta(minutes=30),
                        capacity=cap, remaining=0 if rng.random() < 0.15 else cap, source="mock"))
    return {"i": i, "profile": prof, "now": now, "shipment": ship, "vehicles": vehicles, "windows": windows, "slots": slots, "locs": w["locs"], "noise": noise}
