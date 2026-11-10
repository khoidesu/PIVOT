"""CLI: chạy 6 kịch bản demo trên API đang chạy và in báo cáo.  python -m app.demo.run_scenarios [http://127.0.0.1:8000]"""
import sys
import time

import httpx

from .scenarios import SCENARIOS, run_scenario


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    failed = 0
    for sid, _ in SCENARIOS:
        t0 = time.time()
        res = run_scenario(sid, lambda: httpx.Client(base_url=base, timeout=30))
        print(f"\n[{'PASS' if res['passed'] else 'FAIL'}] {sid}  ({time.time() - t0:.1f}s)")
        for s in res["steps"]:
            print(f"   {'✓' if s['ok'] else '✗'} {s['label']}" + (f"  — {s['detail']}" if s["detail"] else ""))
        failed += 0 if res["passed"] else 1
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} kịch bản đạt")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
