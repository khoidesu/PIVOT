"""Chạy bộ tin nhắn mẫu qua bộ trích xuất và in từng trường (trạng thái, giá trị, trích đoạn, ghi chú) — để kiểm tra bằng mắt.

    cd backend && PYTHONPATH=. .venv/bin/python -m app.intake_eval_cli [rule|hybrid] [tệp] [--quiet]

Mặc định: chế độ `rule` (không gọi mạng), tệp `../data/mock_zalo_messages.txt`. `hybrid` gọi Gemini THẬT (cần PIVOT_GEMINI_API_KEY, tốn lượt).
Địa điểm là 4 địa điểm mô phỏng của seed; tin nhắc địa điểm khác (Cát Lái, Tân Bình…) sẽ ra "thiếu" — đúng thiết kế. Thời điểm tham chiếu cố định 12/11/2026 10:00 giờ VN."""
import re
import sys
from datetime import datetime, timezone

from .config import settings
from .intake.extractor import build_extractor
from .intake.service import build_draft

LOCS = [{"id": "1", "name": "KCN Sóng Thần (mô phỏng)", "kind": "industrial_zone"}, {"id": "2", "name": "KCN VSIP I (mô phỏng)", "kind": "industrial_zone"},
        {"id": "3", "name": "ICD Cảng C (mô phỏng)", "kind": "icd"}, {"id": "4", "name": "Depot Thủ Đức (mô phỏng)", "kind": "industrial_zone"}]
NOW = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    mode = args[0] if args and args[0] in ("rule", "hybrid") else "rule"
    path = next((a for a in args if a not in ("rule", "hybrid")), "../data/mock_zalo_messages.txt")
    quiet = "--quiet" in argv
    settings.intake_extractor = mode
    msgs = re.findall(r'\[(\d+)\]\n"(.*?)"\n', open(path, encoding="utf-8").read(), re.S)
    for n, text in msgs:
        ex = build_extractor(settings, f"cli{n}")
        d = build_draft(text, NOW, LOCS, ex)
        flags = [k for k in ("suspicious_instructions", "multiple_shipments") if d.get(k)] + ([] if d.get("looks_like_request", True) else ["NOT_A_REQUEST"])
        print(f"\n[{n}] {ex.name}{' note=' + d['extractor']['note'] if d['extractor'].get('note') else ''} flags={flags}\n  {text[:120]}")
        for k, v in d["fields"].items():
            if quiet and v["value"] is None and not [x for x in v["notes"] if x != "MISSING"]:
                continue
            print(f"    {k:16} {v['status']:12} {str(v.get('display')):30} | {(v.get('source') or {}).get('quote')} {[x for x in v['notes'] if x != 'MISSING']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
