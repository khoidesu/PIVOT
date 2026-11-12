"""Sandbox MÔ PHỎNG lợi ích của việc chọn xe điểm cao nhất (không ghi DB thật, không ghi benefit_ledger).

Chạy ĐÚNG đường code thật: `matching.service.evaluate_candidates` (hard gate + MatchScore + tie-break) và `eta.baseline`.
Dữ liệu do nhóm tự sinh → chỉ chứng minh pipeline và hướng tác động, KHÔNG chứng minh độ lớn ngoài đời thật (DRAFT 6.2).
"""
from .engine import run_sandbox  # noqa: F401
