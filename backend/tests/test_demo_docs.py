"""Bộ tệp DEMO (demo_docs/ocr) phải luôn chạy đúng — không gọi mạng thật.

  - PDF có chữ + tệp bị từ chối: chạy thật qua bộ luật; mọi kỳ vọng (mã lỗi, cờ, loại nguồn) đúng và KHÔNG có ô nào SAI.
  - PDF scan + ảnh: thay Gemini bằng bộ đọc giả chỉ trả lại CHỮ GỐC của tài liệu (không trả trường nào) → kiểm tra đường
    "vẽ trang / gửi ảnh → bản phiên âm → luật bù trường → mọi trường cần xem lại" và đáp án khớp với tệp.
"""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.intake.extractor import RuleExtractor
from app.intake_file_eval_cli import DEFAULT_DIR, evaluate

EXPECTED = sorted((DEFAULT_DIR / "expected").glob("*.json"))
pytestmark = pytest.mark.skipif(not EXPECTED, reason="chưa có bộ tệp demo_docs/ocr")


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_every_expected_file_exists_and_names_match():
    files = sorted(x.name for x in (DEFAULT_DIR / "files").iterdir() if x.is_file())
    assert files == sorted(_load(p)["file"] for p in EXPECTED) and len(files) == 17


@pytest.mark.parametrize("path", EXPECTED, ids=lambda p: p.stem)
def test_demo_file(path, monkeypatch):
    monkeypatch.setattr(settings, "intake_extractor", "rule")
    exp = _load(path)
    seen = []

    def fake_reader(images):  # "Gemini" chỉ chép lại chữ của tài liệu, không tự điền trường nào
        seen.append(images)
        return {}, exp["ground_truth_text"]

    r = evaluate(DEFAULT_DIR / "files" / exp["file"], exp, RuleExtractor(), fake_reader, "gemini:fake")
    assert r.passed, (r.problems, {k: v for k, v in r.cells.items() if v != "ok"})
    if exp["group"] in ("pdf_text", "rejected"):
        assert seen == []                                        # PDF có chữ / tệp bị từ chối: không gửi gì ra ngoài
    else:
        assert len(seen) == 1 and all(m == "image/jpeg" or m.startswith("image/") for _, m in seen[0])
        if exp["group"] == "pdf_scan":
            assert all(b.startswith(b"\xff\xd8\xff") for b, _ in seen[0])   # trang PDF scan được vẽ thành JPEG trước khi gửi


def test_rule_parser_fills_the_complete_slips():
    """Phiếu đầy đủ có nhãn: bộ luật một mình phải ra đủ 10/10 (không cần Gemini)."""
    for name in ("01_pdf_phieu_dat_xe", "06_pdf_hang_lanh_2_trang", "07_pdf_chen_lenh"):
        exp = _load(DEFAULT_DIR / "expected" / f"{name}.json")
        r = evaluate(DEFAULT_DIR / "files" / exp["file"], exp, RuleExtractor(), None, "")
        assert r.count("ok") == 10, (name, r.cells)
