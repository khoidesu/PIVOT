"""Chạy bộ tệp DEMO (demo_docs/ocr) qua ĐÚNG đường xử lý của API (/v1/intake/drafts/file) và chấm theo đáp án.

    cd backend && .venv/bin/python -m app.intake_file_eval_cli [rule|hybrid] [--only 05] [--verbose] [--dir ../demo_docs/ocr]

  rule    (mặc định) không gọi mạng: chạy nhóm PDF có chữ + nhóm bị từ chối; bỏ qua PDF scan/ảnh (cần Gemini).
  hybrid  gọi Gemini THẬT (cần PIVOT_GEMINI_API_KEY trong backend/.env): PDF có chữ đi luật + Gemini bổ sung; PDF scan/ảnh do Gemini đọc.
          Không qua giới hạn lượt của API, nhưng VẪN tốn hạn mức của khoá (6 lượt ảnh + vài lượt văn bản mỗi lần chạy).

Chấm từng trường: ĐÚNG · THIẾU (để trống) · SAI (có giá trị nhưng khác đáp án — kể cả điền khi tài liệu không có).
Một tệp ĐẠT khi: mã HTTP/mã lỗi, loại nguồn, số trang, các cờ (chèn lệnh, nhiều lô, không phải yêu cầu…) đúng và KHÔNG có ô SAI.
THIẾU không làm trượt (hệ thống được phép không chắc → người dùng điền), nhưng được đếm để so độ phủ giữa rule và hybrid.
Thời điểm tham chiếu lấy từ đáp án (12/11/2026 10:00 giờ VN) để kết quả không đổi theo ngày chạy.
"""
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import settings
from .intake.extractor import FIELDS, build_extractor, build_image_extractor
from .intake.files import FileIntakeError, draft_from_file

# 4 địa điểm mô phỏng của seed; id = tên để so trực tiếp với đáp án
LOCS = [{"id": n, "name": n, "kind": k} for n, k in (("KCN Sóng Thần (mô phỏng)", "industrial_zone"), ("KCN VSIP I (mô phỏng)", "industrial_zone"),
                                                       ("Depot Thủ Đức (mô phỏng)", "depot"), ("ICD Cảng C (mô phỏng)", "icd"))]
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "demo_docs" / "ocr"


@dataclass
class Result:
    file: str
    group: str
    skipped: str | None = None
    problems: list[str] = field(default_factory=list)   # vi phạm kỳ vọng (mã lỗi, cờ, loại nguồn…)
    cells: dict[str, str] = field(default_factory=dict)  # trường → ok | missing | wrong
    draft: dict | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.skipped is None and not self.problems and "wrong" not in self.cells.values()

    def count(self, kind: str) -> int:
        return sum(v == kind for v in self.cells.values())


def _same(exp, got) -> bool:
    if exp is None or got is None:
        return exp is None and got is None
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        try:
            return abs(float(got) - float(exp)) < 0.5
        except (TypeError, ValueError):
            return False
    if isinstance(exp, str) and len(exp) >= 16 and exp[4] == "-" and exp[10] == "T":  # mốc giờ: so theo thời điểm, không theo chuỗi
        try:
            return datetime.fromisoformat(str(got)) == datetime.fromisoformat(exp)
        except ValueError:
            return False
    return str(got).strip().casefold() == str(exp).strip().casefold()


def grade_cell(exp, got) -> str:
    options = exp if isinstance(exp, list) else [exp]
    if any(_same(o, got) for o in options):
        return "ok"
    return "missing" if got is None else "wrong"


def evaluate(path: Path, exp: dict, text_extractor, read_images, reader_name: str) -> Result:
    res = Result(file=exp["file"], group=exp["group"])
    want = exp["expect"]
    now = datetime.fromisoformat(exp["reference_time"])
    try:
        draft, _ = draft_from_file(path.read_bytes(), now, LOCS, text_extractor=text_extractor, read_images=read_images,
                                   reader_name=reader_name, cfg=settings)
        status = 200
    except FileIntakeError as e:
        draft, status, res.error = None, e.status, e.code
    https = want["http"] if isinstance(want["http"], list) else [want["http"]]
    if status not in https:
        res.problems.append(f"HTTP {status}{' ' + res.error if res.error else ''} (cần {want['http']})")
    if want.get("error_code") and res.error != want["error_code"]:
        res.problems.append(f"mã lỗi {res.error} (cần {want['error_code']})")
    res.draft = draft
    if draft is None:
        return res
    src = draft["source"]
    if want.get("source_kind") and src.get("kind") != want["source_kind"]:
        res.problems.append(f"nguồn {src.get('kind')} (cần {want['source_kind']})")
    if want.get("pages") and src.get("pages") != want["pages"]:
        res.problems.append(f"{src.get('pages')} trang (cần {want['pages']})")
    for flag, val in (want.get("flags") or {}).items():
        if bool(draft.get(flag)) != val:
            res.problems.append(f"cờ {flag}={draft.get(flag)} (cần {val})")
    for flag in ("suspicious_instructions", "multiple_shipments"):  # cờ không được kỳ vọng thì không được bật
        if flag not in (want.get("flags") or {}) and draft.get(flag):
            res.problems.append(f"cờ {flag} bật nhầm")
    for name, code in (want.get("notes") or {}).items():
        if code not in draft["fields"][name]["notes"]:
            res.problems.append(f"{name} thiếu ghi chú {code}")
    for name in FIELDS:
        f = draft["fields"][name]
        res.cells[name] = grade_cell(exp["expected_fields"][name], f["value"])
        if want.get("all_need_review") and f["value"] is not None and f["status"] != "needs_review":
            res.problems.append(f"{name} phải ở trạng thái cần xem lại")
    return res


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    mode = args[0] if args and args[0] in ("rule", "hybrid") else "rule"
    verbose = "--verbose" in argv
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    root = Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else DEFAULT_DIR
    if mode == "hybrid" and not settings.gemini_api_key:
        print("Chế độ hybrid cần PIVOT_GEMINI_API_KEY (đặt trong backend/.env). Xem demo_docs/ocr/README.md.")
        return 2
    settings.intake_extractor = mode
    gemini = None
    if mode == "hybrid":
        gemini = build_image_extractor(settings)
    print(f"Bộ tệp: {root}\nChế độ: {mode}" + (f" · đọc ảnh: {gemini.name}" if gemini else " · đọc ảnh: TẮT (bỏ qua PDF scan/ảnh)"))
    results: list[Result] = []
    for ef in sorted((root / "expected").glob("*.json")):
        exp = json.loads(ef.read_text(encoding="utf-8"))
        if only and not exp["file"].startswith(only):
            continue
        if exp["needs_gemini"] and gemini is None:
            results.append(Result(file=exp["file"], group=exp["group"], skipped="cần Gemini"))
            continue
        text_ex = build_extractor(settings, f"eval-{exp['file']}")
        if gemini:
            gemini.used_model = gemini.model
        r = evaluate(root / "files" / exp["file"], exp, text_ex, (lambda imgs: gemini.extract_images(imgs, datetime.fromisoformat(exp["reference_time"]), LOCS)) if gemini else None,
                     gemini.name if gemini else "")
        results.append(r)
        if r.draft:
            by = r.draft["extractor"]["name"] + (f" ({r.draft['extractor']['note']})" if r.draft["extractor"].get("note") else "")
            if gemini and exp["needs_gemini"] and gemini.used_model != gemini.model:
                by += f" → trả lời bởi dự phòng {gemini.used_model}"
        else:
            by = r.error or ""
        mark = "ĐẠT " if r.passed else "TRƯỢT"
        cells = f"đúng {r.count('ok')}/10 · thiếu {r.count('missing')} · SAI {r.count('wrong')}" if r.cells else ""
        print(f"\n{mark} {r.file:<36} [{r.group}] {by}  {cells}")
        for p in r.problems:
            print(f"      ! {p}")
        if r.draft and (verbose or not r.passed):
            for name in FIELDS:
                f = r.draft["fields"][name]
                tag = {"ok": "đúng", "missing": "thiếu", "wrong": "SAI"}[r.cells[name]]
                print(f"      {tag:5} {name:16} {_fmt(f['display']):34} cần {_fmt(exp['expected_fields'][name])!s:34} | {f['status']} {[n for n in f['notes'] if n != 'MISSING']}")
    for r in results:
        if r.skipped:
            print(f"BỎ QUA {r.file:<35} ({r.skipped})")
    ran = [r for r in results if not r.skipped]
    cells = [c for r in ran for c in r.cells.values()]
    print(f"\nTổng: {sum(r.passed for r in ran)}/{len(ran)} tệp đạt · ô đúng {cells.count('ok')}/{len(cells)} · thiếu {cells.count('missing')} · SAI {cells.count('wrong')}"
          + (f" · bỏ qua {len(results) - len(ran)}" if len(results) > len(ran) else ""))
    return 0 if all(r.passed for r in ran) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
