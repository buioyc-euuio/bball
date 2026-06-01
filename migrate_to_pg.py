#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性把本地 bball.db 搬到雲端 Postgres。

用法:
    DATABASE_URL='postgres://...sslmode=require' python3 migrate_to_pg.py

- 完整保留每場的 confirmed 旗標、隊伍總得分、原圖、裁判、備註、個人得分。
- 以 sid upsert; 重跑只會覆蓋同一場, 不會重複。
- 完全唯讀本地 bball.db, 不修改/不刪除正本。
"""
import os, json, sqlite3, sys

if not os.environ.get("DATABASE_URL"):
    sys.exit("請先設定 DATABASE_URL 環境變數 (Neon 連線字串)。")

import server   # 有 DATABASE_URL → server 進入 Postgres 模式
assert server.PG, "server 未進入 Postgres 模式, 請確認 DATABASE_URL 已設定。"

SQLITE = server.DB

def read_sqlite():
    if not os.path.exists(SQLITE):
        sys.exit(f"找不到本地資料庫: {SQLITE}")
    s = sqlite3.connect(SQLITE)
    s.row_factory = sqlite3.Row
    roster = [(r["name"], r["ord"]) for r in s.execute("SELECT name, ord FROM players ORDER BY ord")]
    games = s.execute("SELECT * FROM games ORDER BY page, idx_on_page, id").fetchall()
    out = []
    for g in games:
        lines = s.execute("SELECT * FROM stat_lines WHERE game_id=? ORDER BY col", (g["id"],)).fetchall()
        players = []
        for ln in lines:
            marks = json.loads(ln["marks"] or "{}")
            stats = {}
            for k in server.STAT_KEYS:
                v = ln[k]
                stats[k] = {"v": "" if v is None else v, "m": bool(marks.get(k))}
            players.append({
                "team": ln["team"], "name": ln["name"] or "", "fname": bool(ln["name_uncertain"]),
                "group": ln["grp"] or "", "stats": stats,
                "conflict": bool(ln["conflict"]), "maybe3": bool(ln["maybe3"]),
                "note": ln["note"] or "",
            })
        out.append({
            "sid": g["sid"], "no": g["no"], "venue": g["venue"] or "", "date": g["date"] or "",
            "img": g["img"], "players": players,
            "totalA": "" if g["total_a"] is None else g["total_a"],
            "totalB": "" if g["total_b"] is None else g["total_b"],
            "refMain": g["ref_main"] or "", "refAsst": g["ref_asst"] or "", "refScorer": g["ref_scorer"] or "",
            "fmain": bool(g["fmain"]), "fasst": bool(g["fasst"]), "fscorer": bool(g["fscorer"]),
            "fno": bool(g["fno"]), "fvenue": bool(g["fvenue"]), "note": g["note"] or "",
            "_confirmed": int(g["confirmed"] or 0),
        })
    s.close()
    return roster, out

def main():
    roster, sheets = read_sqlite()
    server.init_db()
    c = server.conn()
    for name, ordv in roster:
        server.ensure_player(c, name, ordv)
    conf = draft = 0
    for sh in sheets:
        cflag = sh.pop("_confirmed")
        server.upsert_sheet(c, sh, confirmed=cflag, autototal=False)
        if cflag:
            conf += 1
        else:
            draft += 1
    c.commit(); c.close()
    print(f"已搬遷到 Postgres: 共 {len(sheets)} 場 (已確認 {conf}、草稿 {draft})、名單 {len(roster)} 人。")

if __name__ == "__main__":
    main()
