"""CLI: `python -m app.sandbox.run --n 100 --seed 42 --out ../docs/SANDBOX_REPORT.md [--json x.json] [--csv x.csv]` (không cần server/DB)."""
import argparse
import csv
import json
import sys
from pathlib import Path

from . import run_sandbox

NAMES = {"random": "chọn ngẫu nhiên (kỳ vọng)", "nearest": "xe gần nhất", "first": "xe đầu danh sách"}
PROFILE_VI = {"dense": "đô thị dày", "sparse": "thưa", "peak": "giờ cao điểm"}
MET = (("km", "Km chạy rỗng", "km", 1), ("cost_vnd", "Chi phí chạy rỗng", "VND", 0), ("min_to_pickup", "Phút tới điểm lấy", "phút", 1), ("min_to_icd", "Phút tới ICD", "phút", 1))


def _f(x: float, d: int = 1) -> str:
    return f"{x:,.{d}f}"


def to_markdown(r: dict) -> str:
    m, s = r["meta"], r["summary"]
    L = [f"# Sandbox mô phỏng lợi ích — {m['n']} trường hợp (seed {m['seed']})", "",
         "> **MÔ PHỎNG — không phải lợi ích đã xác minh.** Dữ liệu do nhóm tự sinh (phân phối tự định nghĩa), chạy đúng đường code thật của hệ thống "
         "(hard gate + MatchScore + ETA luật). Kết quả chỉ chứng minh **cách tính và hướng tác động**, không chứng minh độ lớn ngoài đời thật (DRAFT 6.2).", "",
         f"- Phiên bản: `{m['rule_version']}` · giả định `{m['assumption_version']}` · hồ sơ `{m['profile']}` · sinh lúc {m['generated_at']}",
         f"- Khả thi: **{s['n_feasible']}/{s['n_cases']}** ca ({s['n_infeasible']} ca không có xe nào qua hard gate — được đếm riêng, **không ép ghép**); "
         f"trung bình {s['pass_gate_mean']:.1f} xe qua hard gate mỗi ca.", ""]
    if not s["n_feasible"]:
        return "\n".join(L)
    t = s["top1_mean"]
    L += ["## 1. Xe điểm cao nhất (top-1) — kết quả trung bình", "",
          "| Chỉ số | Giá trị |", "|---|---|"]
    L += [f"| {lab} | {_f(t[k], d)} {u} |" for k, lab, u, d in MET]
    L += [f"| Trễ hạn lấy hàng (thực tế mô phỏng) | {t['late_pickup']*100:.1f}% |", f"| Trễ cut-off (thực tế mô phỏng) | {t['late_cutoff']*100:.1f}% |",
          f"| Cờ cảnh báo cut-off P90 của hệ thống | {t['cutoff_flag']*100:.1f}% |", ""]
    b = s["vs_static_baseline"]
    L += [f"So với baseline tĩnh của hành lang (38 km chạy rỗng): tiết kiệm trung bình **{_f(b['km_saved_mean'])} km ≈ {_f(b['cost_saved_vnd_mean'], 0)} VND/chuyến**; "
          f"top-1 tốt hơn baseline ở {b['share_better_than_baseline']*100:.0f}% số ca. *(Baseline 38 km là giả định cấu hình, không phải đo thực; "
          "mô hình nhà xe giả định mọi xe rảnh đậu trong bán kính 5 km quanh điểm lấy hàng, nên phần lớn chênh lệch này đến từ chính giả định đó — "
          "đừng đọc nó như lợi ích của riêng việc chọn xe điểm cao nhất; so sánh có ý nghĩa là mục 2.)*", "",
          "## 2. Top-1 so với cách chọn khác (chênh lệch cặp; DƯƠNG = top-1 tốt hơn)", "",
          "Mỗi dòng: chênh lệch trung bình [khoảng tin cậy 95% bootstrap] · tỷ lệ ca top-1 không tệ hơn.", ""]
    for alt, name in NAMES.items():
        v = s["vs"][alt]
        L += [f"### vs {name}", "", "| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |", "|---|---|---|---|---|"]
        for k, lab, u, d in MET:
            x = v["saving"][k]
            L.append(f"| {lab} ({u}) | {_f(x['mean'], d)} [{_f(x['ci95'][0], d)}; {_f(x['ci95'][1], d)}] | {_f(x['median'], d)} | {_f(x['p10'], d)} – {_f(x['p90'], d)} | {x['win_rate']*100:.0f}% |")
        rd = v["rate_diff"]
        L += ["", f"Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng {rd['late_pickup']*100:+.1f} điểm %, cut-off {rd['late_cutoff']*100:+.1f} điểm %.", ""]
    L += ["## 3. Giá trị của hard gate", "",
          f"Nếu chọn xe đầu danh sách **không qua hard gate**: {s['invalid_without_gate']['first_in_list_rate']*100:.0f}% số ca rơi vào xe không đủ điều kiện "
          f"(quá tải / sai loại hàng / trễ giờ / dữ liệu cũ / offline); trung bình {s['invalid_without_gate']['mean_share_of_fleet_failing_gate']*100:.0f}% đội xe không đạt.", "",
          "## 4. Độ nhạy theo hồ sơ", "", "| Hồ sơ | Ca khả thi | km top-1 | Tiết kiệm km vs ngẫu nhiên | Tiết kiệm phút tới ICD vs ngẫu nhiên |", "|---|---|---|---|---|"]
    for p, blk in s["by_profile"].items():
        if blk["n_feasible"]:
            sv = blk["vs"]["random"]["saving"]
            L.append(f"| {PROFILE_VI.get(p, p)} | {blk['n_feasible']}/{blk['n_cases']} | {_f(blk['top1_mean']['km'])} | {_f(sv['km']['mean'])} | {_f(sv['min_to_icd']['mean'])} |")
    L += ["", f"Top-1 trùng xe gần nhất ở {s['top1_is_nearest_share']*100:.0f}% số ca; khi không trùng, top-1 chạy rỗng **nhiều km hơn** xe gần nhất "
          "(điểm cân bằng độ vừa tải + dư thời gian + km) nhưng tới ICD sớm hơn — xem mục 2.", "",
          "## 5. Giới hạn (đọc kỹ)", "",
          "- Mô hình nhà xe: mỗi nhà xe có MỘT bãi trong bán kính 5 km quanh điểm lấy hàng và xe rảnh luôn ở đó — nên các xe vốn đã gần nhau và mức tiết kiệm km giữa các cách chọn nhỏ; lợi ích lớn hơn nếu đội xe thật rải rộng hơn.",
          "- Phân phối lô/đội xe/bãi/khung rảnh, tỷ lệ xe quá hạn/offline, nhiễu thời gian đều do nhóm đặt — đổi giả định sẽ đổi con số. Hồ sơ `peak` và `sparse` cho thấy độ nhạy.",
          "- 'Thực tế' = ETA luật × nhiễu mô phỏng (cùng phân phối với lịch sử ETA mô phỏng), tách khỏi dự báo; vẫn chưa phải đo từ chuyến thật.",
          "- Tỷ lệ trễ hạn rất thấp ở mọi cách chọn vì hạn lấy hàng/cut-off trong kịch bản khá rộng; lợi ích chính hiện ở **km rỗng, chi phí, và phút tới ICD**.",
          "- Chi phí = km rỗng × đơn giá cấu hình (14.000 VND/km); chưa gồm chi phí chờ, phạt trễ, nhiên liệu theo tải.",
          "- Không ghi vào sổ lợi ích thật; không thay thế việc xác minh độc lập bằng số đo từ chuyến hoàn tất.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sandbox mô phỏng lợi ích chọn xe điểm cao nhất")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--profile", default="mixed", choices=["mixed", "dense", "sparse", "peak"])
    ap.add_argument("--out", help="ghi báo cáo markdown")
    ap.add_argument("--json", help="ghi toàn bộ kết quả JSON")
    ap.add_argument("--csv", help="ghi từng ca (CSV phẳng)")
    a = ap.parse_args(argv)
    r = run_sandbox(a.n, a.seed, profile=a.profile)
    md = to_markdown(r)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if a.csv:
        flat = []
        for c in r["cases"]:
            row = {k: v for k, v in c.items() if not isinstance(v, dict)}
            for strat in ("top1", "nearest", "first", "random"):
                row.update({f"{strat}_{k}": v for k, v in (c.get(strat) or {}).items()})
            flat.append(row)
        keys = sorted({k for r_ in flat for k in r_})
        with open(a.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(flat)
    sys.stdout.reconfigure(encoding="utf-8")
    print(md if not a.out else f"Đã ghi {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
