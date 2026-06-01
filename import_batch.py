#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用辨識匯入器 — 未來每有新比賽, 複製這支改 BATCH 與 SHEETS 即可。

設計重點(可擴充性):
  1) sid 自動加 BATCH 前綴 (例: '2026q2' → sid='2026q2-p1s1'), 永不與舊批次衝突。
  2) 圖片吃「任意圖檔路徑」(手機拍照/掃描/PDF 裁切皆可), 不綁死特定 PDF 版面。
  3) 連線目標由 DATABASE_URL 決定: 不設=本地 SQLite, 設了=雲端 Postgres。
  4) upsert by sid 且永遠跳過 confirmed=1 → 不會動到你/組員已校對確認的資料。
  5) 可重複跑, 不會重複新增。

用法:
  本地測:   python3 import_batch.py
  推雲端:   DATABASE_URL='postgres://...sslmode=require' python3 import_batch.py
"""
import base64, os, sys
import server

# ── 改這裡 ──────────────────────────────────────────────────────
BATCH = "2026q2"          # 這批比賽的代號(英數/連字號), 會變成 sid 前綴
IMG_DIR = "cuts"          # 圖檔所在資料夾
# ────────────────────────────────────────────────────────────────

EMPTY = lambda: {"v": "", "m": False}
def P(team, name, pts=None, fname=True, marks=None):
    st = {k: EMPTY() for k in server.STAT_KEYS}
    if pts is not None:
        st["pts"] = {"v": pts, "m": True}
    for k, v in (marks or {}).items():
        st[k] = {"v": v, "m": True}
    return {"team": team, "name": name, "fname": fname, "group": "",
            "stats": st, "conflict": False, "maybe3": False, "note": ""}

def ref(name, uncertain=True):
    return name, uncertain

def img_b64(path):
    """把圖檔讀成 data-URI。找不到檔就回 None(該場無圖, 仍可灌文字)。"""
    full = path if os.path.isabs(path) else os.path.join(server.HERE, path)
    if not os.path.exists(full):
        print(f"  ⚠ 找不到圖檔: {full}(此場將無圖)")
        return None
    ext = os.path.splitext(full)[1].lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(full, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()

# ── 每場一筆。sid 用「短碼」即可, 前綴會自動補上。img 給圖檔名(相對 IMG_DIR)。
#    totalA/totalB = 隊伍總得分(讀得出就填, 讀不出留 None)。
SHEETS = [
    # 範例(照抄改值):
    # dict(sid="p1s1", no=1, venue="甲", img="newgame_01.jpg", totalA=10, totalB=8,
    #      A=[P("A","王小明",6), P("A","李大華"), P("A","陳美麗")],
    #      B=[P("B","張三",4),   P("B","李四"),   P("B","王五")],
    #      refs=[ref("林老師", False), ref("黃同學"), ref("吳同學")],
    #      note="辨識草稿, 請對照原圖核對。"),
]

def main():
    target = "雲端 Postgres" if server.PG else f"本地 SQLite ({server.DB})"
    print(f"匯入目標 → {target}")
    if not SHEETS:
        sys.exit("SHEETS 是空的, 請先填入這批要辨識的場次。")
    server.init_db()
    c = server.conn()
    for i, n in enumerate(server.json.load(open(server.SEED_JSON, encoding="utf-8")).get("roster", [])):
        server.ensure_player(c, n, i)
    inserted = skipped = 0
    for s in SHEETS:
        sid = f"{BATCH}-{s['sid']}"
        row = c.execute(server.q("SELECT confirmed FROM games WHERE sid=?"), (sid,)).fetchone()
        if row and row["confirmed"]:
            skipped += 1
            continue
        rm, ra, rs = s["refs"]
        sheet = {
            "sid": sid, "no": s.get("no", ""), "venue": s.get("venue", ""), "date": s.get("date", ""),
            "img": img_b64(os.path.join(IMG_DIR, s["img"])) if s.get("img") else None,
            "players": s["A"] + s["B"],
            "totalA": "" if s.get("totalA") is None else s["totalA"],
            "totalB": "" if s.get("totalB") is None else s["totalB"],
            "refMain": rm[0], "refAsst": ra[0], "refScorer": rs[0],
            "fmain": rm[1], "fasst": ra[1], "fscorer": rs[1],
            "fno": False, "fvenue": (s.get("venue", "") == ""), "note": s.get("note", ""),
        }
        server.upsert_sheet(c, sheet, confirmed=0, autototal=True)
        inserted += 1
    c.commit(); c.close()
    print(f"完成: 灌入/更新 {inserted} 場(batch={BATCH}), 跳過已確認 {skipped} 場。")

if __name__ == "__main__":
    main()
