"""CLI ETA Sandbox: in 3 bảng (quét độ trôi · lưới kịch bản · sức khoẻ tín hiệu) mà KHÔNG cần bật server/DB.
  python -m app.eta_sandbox_cli [--only drift|scenarios|signals] [--fresh]
`signals` gọi mạng thật (OSRM/Open-Meteo, Mapbox nếu có PIVOT_MAPBOX_TOKEN); đặt PIVOT_SIGNALS_ENABLED=false để tắt. Dữ liệu ML là lịch sử MÔ PHỎNG."""
import sys

from .eta import sandbox


def table(headers: list[str], rows: list[list]) -> str:
    cells = [[("—" if c is None else str(c)) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    line = lambda r: "  ".join(c.ljust(w[i]) for i, c in enumerate(r))  # noqa: E731
    return "\n".join([line(headers), "  ".join("-" * x for x in w), *(line(r) for r in cells)])


def drift_table(rows: list[dict]) -> str:
    out = table(["drift", "kết quả", "MAE luật", "MAE ML", "cải thiện %", "phủ P90 ML", "lý do"],
                [[r["drift"], "DÙNG ML" if r["promoted"] else "hạ về luật", r["mae_rule"], r["mae_ml"], r["improvement_pct"], r["p90_coverage_ml"], r["reason"]] for r in rows])
    first = next((r["drift"] for r in rows if not r["promoted"]), None)
    return out + (f"\n→ hạ về luật từ drift = {first}" if first is not None else "\n→ không có mức drift nào làm mô hình bị hạ về luật")


def scenario_table(rows: list[dict]) -> str:
    return table(["khung giờ", "giờ đi", "luật P50", "luật P90", "ML P50", "ML P90", "đang dùng"],
                 [[r["band"], f'{r["depart_hour"]}h', r["rule_p50"], r["rule_p90"], r["ml_p50"], r["ml_p90"], r["used"]] for r in rows]) + "\n(đơn vị: phút trung chuyển; ML trên lịch sử mô phỏng)"


def signals_table(d: dict) -> str:
    if not d["enabled"]:
        return "tín hiệu thật đang TẮT (PIVOT_SIGNALS_ENABLED=false): osrm, weather, mapbox = disabled"
    rows = [["osrm", d["osrm"]["status"], d["osrm"].get("latency_ms"), f'{d["osrm"].get("distance_km")} km / {d["osrm"].get("duration_min")} phút' if d["osrm"]["status"] == "ok" else d["osrm"].get("error")],
            ["weather", d["weather"]["status"], d["weather"].get("latency_ms"), f'mưa {d["weather"].get("precip_mm_h")} mm/h' if d["weather"]["status"] == "ok" else d["weather"].get("error")],
            ["mapbox", d["mapbox"]["status"], d["mapbox"].get("latency_ms"), f'{d["mapbox"].get("live_min")} / {d["mapbox"].get("typical_min")} phút' if d["mapbox"]["status"] == "ok" else d["mapbox"].get("error")]]
    return table(["nguồn", "trạng thái", "ms", "chi tiết"], rows)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    only = argv[argv.index("--only") + 1] if "--only" in argv and argv.index("--only") + 1 < len(argv) else None
    fresh = "--fresh" in argv
    if only not in (None, "drift", "scenarios", "signals"):
        print("dùng: python -m app.eta_sandbox_cli [--only drift|scenarios|signals] [--fresh]")
        return 2
    if only in (None, "drift"):
        print("\n== 1. Quét độ trôi (ML mô phỏng; trạng thái mô hình được khôi phục sau khi chạy) ==")
        print(drift_table(sandbox.sweep_drift()))
    if only in (None, "scenarios"):
        print("\n== 2. Lưới kịch bản theo khung giờ ==")
        print(scenario_table(sandbox.scenario_matrix()))
    if only in (None, "signals"):
        print("\n== 3. Sức khoẻ tín hiệu thật (điểm mẫu cố định, vị trí xe vẫn là MÔ PHỎNG) ==")
        print(signals_table(sandbox.signals_health_check(fresh=fresh)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
