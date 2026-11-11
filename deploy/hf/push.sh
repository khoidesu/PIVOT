#!/bin/sh
# Đẩy bản hiện tại lên một Hugging Face Space (SDK Docker). Chạy từ thư mục gốc repo:
#   deploy/hf/push.sh <hf-username>/<space-name>
# Cần đã đăng nhập git với Hugging Face (token ghi — nhập khi git hỏi, KHÔNG dán vào chat hay lưu vào mã).
set -e
SPACE="${1:?usage: deploy/hf/push.sh <hf-username>/<space-name>}"
TMP="$(mktemp -d)"
git archive HEAD | tar -x -C "$TMP"
rm -rf "$TMP/docs" "$TMP/DRAFT.md"           # tài liệu/PDF nặng không cần cho image
cp deploy/hf/README.md "$TMP/README.md"      # README của Space cần khối cấu hình ở đầu file
cd "$TMP"
git init -q -b main && git add -A && git commit -q -m "Deploy LOGECTION to Hugging Face Space"
git push --force "https://huggingface.co/spaces/$SPACE" main
echo "Đã đẩy. Đặt Variables/Secrets trong Space → Settings (xem docs/DEPLOY.md, mục Hugging Face)."
