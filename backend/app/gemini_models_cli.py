"""Kiểm tra khoá Gemini trong backend/.env và liệt kê các mô hình khoá đó gọi được (generateContent). KHÔNG in khoá.

    cd backend && .venv/bin/python -m app.gemini_models_cli [--try]

--try: gửi thêm MỘT yêu cầu rất nhỏ tới mô hình đang cấu hình cho tin nhắn và cho ảnh để chắc khoá chạy được (tốn 1–2 lượt).
"""
import sys

import httpx

from .config import settings


def main(argv: list[str]) -> int:
    key = settings.gemini_api_key
    if not key:
        print("Chưa có PIVOT_GEMINI_API_KEY trong backend/.env.")
        return 2
    print(f"Khoá: có (…{key[-4:]}) · tin nhắn: {settings.gemini_model} · ảnh/PDF scan: {settings.gemini_vision_model or settings.gemini_model}")
    try:
        r = httpx.get(f"{settings.gemini_url}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=20)
    except httpx.HTTPError as e:
        print(f"Không gọi được Google: {type(e).__name__}")
        return 1
    if r.status_code != 200:
        print(f"Google trả {r.status_code}: {r.text[:300]}")
        return 1
    names = sorted(m["name"].removeprefix("models/") for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []))
    print(f"\n{len(names)} mô hình gọi được:")
    for n in names:
        tag = " ← tin nhắn" if n == settings.gemini_model else ""
        tag += " ← ảnh" if n == (settings.gemini_vision_model or settings.gemini_model) else ""
        print(f"  {n}{tag}")
    for want in {settings.gemini_model, settings.gemini_vision_model or settings.gemini_model}:
        if want not in names:
            print(f"\n! '{want}' KHÔNG có trong danh sách — đổi PIVOT_GEMINI_MODEL / PIVOT_GEMINI_VISION_MODEL trong backend/.env.")
    if "--try" in argv:
        for model in dict.fromkeys([settings.gemini_model, settings.gemini_vision_model or settings.gemini_model]):
            body = {"contents": [{"role": "user", "parts": [{"text": "Trả lời đúng một từ: OK"}]}], "generationConfig": {"maxOutputTokens": 8}}
            try:
                rr = httpx.post(f"{settings.gemini_url}/models/{model}:generateContent", json=body, headers={"x-goog-api-key": key}, timeout=60)
                print(f"\nThử {model}: HTTP {rr.status_code}" + ("" if rr.status_code == 200 else f" — {rr.text[:200]}"))
            except httpx.HTTPError as e:
                print(f"\nThử {model}: lỗi {type(e).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
