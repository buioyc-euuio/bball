#!/bin/bash
# 雙擊這個檔案即可啟動「籃球攻守紀錄」本地服務。
# 第一次若 macOS 阻擋, 對檔案按右鍵 → 打開 → 打開。
cd "$(dirname "$0")" || exit 1
echo "正在啟動籃球攻守紀錄系統…"
python3 server.py
echo ""
echo "服務已結束, 可關閉此視窗。"
