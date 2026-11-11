#!/bin/sh
# Đẩy mã lên một Hugging Face Space (Docker). Dùng: deploy/hf/push_space.sh <tai-khoan>/<ten-space>
# Khi git hỏi mật khẩu: nhập HF ACCESS TOKEN (quyền Write) — tự gõ ở terminal, đừng dán vào chat/commit.
# DRY_RUN=1 chỉ dựng thư mục tạm để kiểm tra, không push.
set -e
SPACE="$1"
[ -n "$SPACE" ] || [ -n "$DRY_RUN" ] || { echo "Dùng: $0 <tai-khoan>/<ten-space>"; exit 1; }
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${STAGE_DIR:-$(mktemp -d)}"
rm -rf "$OUT" && mkdir -p "$OUT"
cd "$ROOT"
git archive HEAD Dockerfile backend frontend deploy/entrypoint.sh | tar -x -C "$OUT"
cp deploy/hf/README.md "$OUT/README.md"
# Space không đặt biến PORT: cố định cổng 7860 ngay trong Dockerfile của bản đẩy lên Space
sed -i.bak 's#^ENV PIVOT_STATIC_DIR=\(.*\)#ENV PORT=7860 PIVOT_ALLOW_FRAMING=true PIVOT_STATIC_DIR=\1#' "$OUT/Dockerfile" && rm "$OUT/Dockerfile.bak"
grep -q "PORT=7860" "$OUT/Dockerfile" || { echo "Không chèn được PORT=7860"; exit 1; }
echo "Đã dựng: $OUT"
[ -z "$DRY_RUN" ] || exit 0
cd "$OUT" && git init -q -b main && git add -A && git commit -q -m "Deploy LOGECTION" \
  && git push -f "https://huggingface.co/spaces/$SPACE" main
echo "Xong. Theo dõi build ở https://huggingface.co/spaces/$SPACE (tab Logs)."
