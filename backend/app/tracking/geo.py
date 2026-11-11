"""Hình học tuyến cho Tracking (mô phỏng). Đường đi là đường nội suy giữa các địa điểm thật trong DB, KHÔNG phải đường bộ thật."""
from math import asin, cos, radians, sin, sqrt

Point = tuple[float, float]  # (lat, lng)
PER_LEG = 10


def haversine_km(a: Point, b: Point) -> float:
    r = 6371.0
    dlat, dlng = radians(b[0] - a[0]), radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(radians(a[0])) * cos(radians(b[0])) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(h))


def _leg(a: Point, b: Point, n: int, bend: float) -> list[Point]:
    """Nội suy a→b (không gồm a); `bend` tạo độ cong nhẹ để tuyến trông như đường thật."""
    out = []
    for i in range(1, n + 1):
        t = i / n
        lat, lng = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        off = bend * sin(3.14159 * t)
        out.append((lat + off * (b[1] - a[1]), lng - off * (b[0] - a[0])))
    out[-1] = b
    return out


def build_route(start: Point, pickup: Point, dest: Point) -> tuple[list[Point], int]:
    """Trả (các điểm, chỉ số điểm lấy hàng). Xe: vị trí đầu → điểm lấy → ICD."""
    pts: list[Point] = [start]
    if haversine_km(start, pickup) > 0.05:
        pts += _leg(start, pickup, PER_LEG, 0.05)
    pickup_idx = len(pts) - 1
    pts += _leg(pickup, dest, PER_LEG, -0.06)
    return pts, pickup_idx


def cumulative(pts: list[Point]) -> list[float]:
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + haversine_km(a, b))
    return cum


def point_at(pts: list[Point], cum: list[float], km: float) -> Point:
    km = max(0.0, min(km, cum[-1]))
    for i in range(1, len(cum)):
        if km <= cum[i]:
            seg = cum[i] - cum[i - 1]
            t = 0.0 if seg == 0 else (km - cum[i - 1]) / seg
            a, b = pts[i - 1], pts[i]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return pts[-1]


def project(pts: list[Point], cum: list[float], p: Point) -> float:
    """Quãng đường dọc tuyến (km) của điểm gần p nhất (xấp xỉ phẳng — đủ cho vài chục km)."""
    best, best_d = 0.0, float("inf")
    kx = cos(radians(p[0])) * 111.32
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        ax, ay, bx, by = a[1] * kx, a[0] * 110.57, b[1] * kx, b[0] * 110.57
        px, py = p[1] * kx, p[0] * 110.57
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        d = (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2
        if d < best_d:
            best_d, best = d, cum[i - 1] + t * (cum[i] - cum[i - 1])
    return best


MILESTONES = ("AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE")


def derive_milestones(along_km: float, pickup_km: float, total_km: float, r_pickup: float, r_gate: float,
                      reached: set[str]) -> list[str]:
    """Mốc mới đạt được theo quãng đường dọc tuyến (bền vững cả khi vị trí 'nhảy' qua vùng geofence). Đúng thứ tự, mỗi mốc một lần."""
    new = []
    if "AT_PICKUP" not in reached and along_km >= pickup_km - r_pickup:
        new.append("AT_PICKUP")
    if "DEPARTED_PICKUP" not in reached and along_km > pickup_km + r_pickup:
        new.append("DEPARTED_PICKUP")
    if "AT_ICD_GATE" not in reached and along_km >= total_km - r_gate:
        new.append("AT_ICD_GATE")
    return new
