#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雲端 Postgres 備份 (pg_dump 包一層)。

用法:
    DATABASE_URL='postgres://...sslmode=require' python3 backup_pg.py

會在 backups/ 產生 bball-pg-YYYYmmdd-HHMMSS.sql.gz, 保留最近 40 份。
需先安裝 PostgreSQL client (pg_dump): brew install libpq  或  brew install postgresql
可掛到 GitHub Actions 每日排程, 或本機 cron。
"""
import os, sys, time, gzip, subprocess, shutil

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("請先設定 DATABASE_URL。")
if not shutil.which("pg_dump"):
    sys.exit("找不到 pg_dump, 請先安裝: brew install libpq (並把它加進 PATH)。")

HERE = os.path.dirname(os.path.abspath(__file__))
BK = os.path.join(HERE, "backups")
os.makedirs(BK, exist_ok=True)
dst = os.path.join(BK, "bball-pg-" + time.strftime("%Y%m%d-%H%M%S") + ".sql.gz")

dump = subprocess.run(["pg_dump", "--no-owner", "--no-privileges", url],
                      capture_output=True)
if dump.returncode != 0:
    sys.exit("pg_dump 失敗: " + dump.stderr.decode("utf-8", "replace"))
with gzip.open(dst, "wb") as f:
    f.write(dump.stdout)

baks = sorted(f for f in os.listdir(BK) if f.startswith("bball-pg-") and f.endswith(".sql.gz"))
for old in baks[:-40]:
    try:
        os.remove(os.path.join(BK, old))
    except OSError:
        pass
print("已備份雲端資料庫 →", dst, f"({os.path.getsize(dst)//1024} KB)")
