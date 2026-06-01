#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把第 2/3/5/6 頁辨識結果灌成草稿 (confirmed=0)，含每張切圖。
重複執行不會重覆 (依 sid upsert)。已確認(confirmed=1)的場次不會被覆寫。"""
import base64, fitz
import server

PDF = "攻守記錄表掃描檔.pdf"
doc = fitz.open(PDF)

# 每張表在該頁的 y 範圍(含表頭場次列)
BANDS = {1: (0.00, 0.325), 2: (0.305, 0.655), 3: (0.635, 0.975)}

def crop_b64(page, slot, zoom=200/72):
    p = doc[page-1]; r = p.rect
    y0, y1 = BANDS[slot]
    clip = fitz.Rect(0, r.height*y0, r.width, r.height*y1)
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    return "data:image/jpeg;base64," + base64.b64encode(pix.tobytes("jpeg")).decode()

EMPTY = lambda: {"v": "", "m": False}
def P(team, name, pts=None, fname=False, marks=None):
    """pts = 該球員個人得分(正字筆數)。隊伍總得分由 server 自動以三人加總帶入。"""
    st = {k: EMPTY() for k in server.STAT_KEYS}
    if pts is not None:
        st["pts"] = {"v": pts, "m": True}
    for k, v in (marks or {}).items():
        st[k] = {"v": v, "m": True}
    return {"team": team, "name": name, "fname": fname, "group": "",
            "stats": st, "conflict": False, "maybe3": False, "note": ""}

def ref(name, uncertain):
    return name, uncertain

NOTE_FAINT = "犯規/助攻/籃板等劃記較淡，辨識僅填總得分與正字，細項請對照原圖補。"

# pts = 各球員個人得分(正字筆數)；隊伍總得分由 server 以三人加總自動帶入。
SHEETS = [
 dict(sid="p2s1", page=2, slot=1, no=22, venue="乙",
      A=[P("A","楊文岩",6), P("A","顏貝宸",5), P("A","羅翊菲")],
      B=[P("B","張妤丞",4), P("B","陳慧芝"), P("B","吉芸箴")],
      refs=[ref("林以昕",False), ref("陳品璇",True), ref("蔡棠茹",True)], note=NOTE_FAINT),
 dict(sid="p2s2", page=2, slot=2, no=22, venue="甲",
      A=[P("A","歐陽吉鸞",0), P("A","楊濰瑄"), P("A","毛國鳳")],
      B=[P("B","池旻柔",2), P("B","楊欣妍"), P("B","陳芊靜")],
      refs=[ref("涂菲倢",False), ref("李心瑤",False), ref("林芯妮",False)], note=NOTE_FAINT),
 dict(sid="p2s3", page=2, slot=3, no=21, venue="甲",
      A=[P("A","呂安芊",10), P("A","陳慧妮",10), P("A","何莉妍")],
      B=[P("B","駱舒涵",5), P("B","李珮綺"), P("B","林以昕")],
      refs=[ref("呂豫新",True), ref("陳慧芝",True), ref("張雅安",True)], note=NOTE_FAINT),
 dict(sid="p3s1", page=3, slot=1, no=21, venue="乙",
      A=[P("A","張楷寧",11,fname=True), P("A","劉士嫙",2), P("A","楊喬安")],
      B=[P("B","余沛晨"), P("B","陳喬妤",10), P("B","鄭伃涵")],
      refs=[ref("蔡棠茹",True), ref("許竹瑩",True), ref("吳焄綺",True)], note=NOTE_FAINT),
 dict(sid="p3s2", page=3, slot=2, no=20, venue="乙",
      A=[P("A","吳焄綺",9), P("A","蔡宜臻",10), P("A","許竹瑩")],
      B=[P("B","涂菲倢",3), P("B","李心瑤",4), P("B","林芯妮")],
      refs=[ref("鄭伃涵",False), ref("余沛晨",False), ref("陳喬妤",False)], note=NOTE_FAINT),
 dict(sid="p3s3", page=3, slot=3, no=24, venue="乙",
      A=[P("A","呂安芊",10), P("A","陳芊靜",11), P("A","張雅安")],
      B=[P("B","張楷寧",11), P("B","楊喬安",2), P("B","劉士嫙")],
      refs=[ref("毛國鳳",False), ref("歐陽吉鸞",False), ref("楊濰瑄",True)], note=NOTE_FAINT),
 dict(sid="p5s1", page=5, slot=1, no=14, venue="乙",
      A=[P("A","劉士嫙",17), P("A","陳品璇",3), P("A","張楷寧")],
      B=[P("B","",5,fname=True), P("B","池旻柔",2), P("B","楊欣妍")],
      refs=[ref("鄭伃涵",False), ref("余沛晨",False), ref("陳喬妤",False)],
      note="左側B隊第①欄姓名看不清，請補；"+NOTE_FAINT),
 dict(sid="p5s2", page=5, slot=2, no=14, venue="甲",
      A=[P("A","陳芊靜",10), P("A","呂安芊",2), P("A","駱舒涵")],
      B=[P("B","方佩榮",8), P("B","呂豫新",4), P("B","陳慧妮")],
      refs=[ref("鄭伃涵",True), ref("林以昕",False), ref("李珮綺",False)], note=NOTE_FAINT),
 dict(sid="p5s3", page=5, slot=3, no=12, venue="乙",
      A=[P("A","陳喬妤",6), P("A","余沛晨",10), P("A","鄭伃涵")],
      B=[P("B","羅翊菲",6), P("B","顏貝宸",4), P("B","楊文岩")],
      refs=[ref("陳品璇",True), ref("呂安芊",False), ref("邱璟晏",True)], note=NOTE_FAINT),
 dict(sid="p6s1", page=6, slot=1, no=12, venue="甲",
      A=[P("A","歐陽吉鸞",9), P("A","毛國鳳"), P("A","楊濰瑄",fname=True)],
      B=[P("B","方佩榮",8), P("B","呂豫新",10), P("B","陳慧妮")],
      refs=[ref("林芯妮",False), ref("李心瑤",False), ref("涂菲倢",False)],
      note="表頭有藍筆註記(疑機動/替補)；"+NOTE_FAINT),
]

def main():
    server.init_db()
    c = server.conn()
    # 確保名單存在
    for i, n in enumerate(server.json.load(open(server.SEED_JSON, encoding="utf-8"))["roster"]):
        server.ensure_player(c, n, i)
    inserted = skipped = 0
    for s in SHEETS:
        row = c.execute(server.q("SELECT confirmed FROM games WHERE sid=?"), (s["sid"],)).fetchone()
        if row and row["confirmed"]:
            skipped += 1
            continue
        rm, ra, rs = s["refs"]
        sheet = {
            "sid": s["sid"], "no": s["no"], "venue": s["venue"], "date": "",
            "img": crop_b64(s["page"], s["slot"]),
            "players": s["A"] + s["B"],
            "refMain": rm[0], "refAsst": ra[0], "refScorer": rs[0],
            "fmain": rm[1], "fasst": ra[1], "fscorer": rs[1],
            "fno": False, "fvenue": False, "note": s["note"],
        }
        server.upsert_sheet(c, sheet, confirmed=0, autototal=True)
        inserted += 1
    c.commit(); c.close()
    print(f"灌入/更新 {inserted} 張草稿，跳過已確認 {skipped} 張。")

if __name__ == "__main__":
    main()
