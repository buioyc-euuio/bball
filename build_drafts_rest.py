#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把第 4/6/7/8/9/10/11/12 頁剩餘場次灌成草稿 (confirmed=0)，含每張切圖。
重複執行不會重覆 (依 sid upsert)。已確認(confirmed=1)的場次不會被覆寫。

注意：第 7–12 頁原稿筆跡較淡/潦草，姓名與得分辨識信心偏低，
故大多姓名標為 fname=True(待確認)、個人得分留空，只填可讀的隊伍總得分，
請老師務必對照每張附圖逐欄核對。"""
import base64, fitz
import server

PDF = "攻守記錄表掃描檔.pdf"
doc = fitz.open(PDF)

# 各頁旋轉與分割帶。直式頁 3 張；page4 橫式需 rot270；page12 橫式 rot0 只有 2 張。
BANDS3 = {1: (0.00, 0.325), 2: (0.305, 0.655), 3: (0.635, 0.975)}
BANDS2 = {1: (0.00, 0.52), 2: (0.47, 1.00)}
PAGE_CFG = {
    4:  dict(rot=270, bands=BANDS3),
    6:  dict(rot=0,   bands=BANDS3),
    7:  dict(rot=0,   bands=BANDS3),
    8:  dict(rot=0,   bands=BANDS3),
    9:  dict(rot=0,   bands=BANDS3),
    10: dict(rot=0,   bands=BANDS3),
    11: dict(rot=0,   bands=BANDS3),
    12: dict(rot=0,   bands=BANDS2),
}

def crop_b64(page, slot, zoom=200/72):
    p = doc[page-1]
    cfg = PAGE_CFG[page]
    p.set_rotation(cfg["rot"])
    r = p.rect
    y0, y1 = cfg["bands"][slot]
    clip = fitz.Rect(0, r.height*y0, r.width, r.height*y1)
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    b64 = "data:image/jpeg;base64," + base64.b64encode(pix.tobytes("jpeg")).decode()
    p.set_rotation(0)
    return b64

EMPTY = lambda: {"v": "", "m": False}
def P(team, name, pts=None, fname=True, marks=None):
    """pts = 該球員個人得分(正字筆數)，多半留空；隊伍總得分由 sheet 的 totalA/B 帶入。"""
    st = {k: EMPTY() for k in server.STAT_KEYS}
    if pts is not None:
        st["pts"] = {"v": pts, "m": True}
    for k, v in (marks or {}).items():
        st[k] = {"v": v, "m": True}
    return {"team": team, "name": name, "fname": fname, "group": "",
            "stats": st, "conflict": False, "maybe3": False, "note": ""}

def ref(name, uncertain=True):
    return name, uncertain

LOW = "本頁(7–12)筆跡較淡，姓名/得分辨識信心低，請對照原圖逐欄核對。"

# total=隊伍總得分(下方「總得分」列)，None 表示讀不出。
SHEETS = [
 # ---- 第 7 頁 ----
 dict(sid="p7s1", page=7, slot=1, no=10, venue="乙", totalA=None, totalB=None,
      A=[P("A",""), P("A","邱璟晏"), P("A","呂安芊")],
      B=[P("B","顏貝宸"), P("B","楊文岩"), P("B","羅翊菲")],
      refs=[ref("黃韻文"), ref(""), ref("池旻柔")], note=LOW),
 dict(sid="p7s2", page=7, slot=2, no=13, venue="甲", totalA=2, totalB=4,
      A=[P("A","歐陽吉鸞"), P("A","楊濰瑄"), P("A","陳慧妮")],
      B=[P("B","吳焄綺"), P("B","蔡宜臻"), P("B","許竹瑩")],
      refs=[ref("李珮綺"), ref("駱舒涵"), ref("林以昕")], note=LOW),
 dict(sid="p7s3", page=7, slot=3, no=11, venue="甲", totalA=4, totalB=8,
      A=[P("A","林芯妮"), P("A","涂菲倢"), P("A","張雅安")],
      B=[P("B","羅翊菲"), P("B","顏貝宸"), P("B","楊文岩")],
      refs=[ref("吳焄綺"), ref("許竹瑩"), ref("蔡宜臻")], note=LOW),
 # ---- 第 8 頁 ----
 dict(sid="p8s1", page=8, slot=1, no=9, venue="乙", totalA=2, totalB=0,
      A=[P("A","池旻柔"), P("A","李珮綺"), P("A","方佩榮")],
      B=[P("B","許竹瑩"), P("B","陳慧妮"), P("B","陳喬妤")],
      refs=[ref("鄭伃涵"), ref("余沛晨"), ref("")], note=LOW),
 dict(sid="p8s2", page=8, slot=2, no=8, venue="乙", totalA=6, totalB=4,
      A=[P("A","李珮綺"), P("A","林以昕"), P("A","駱舒涵")],
      B=[P("B","邱璟晏"), P("B","蔡棠茹"), P("B","陳品璇")],
      refs=[ref("楊文岩"), ref("顏貝宸"), ref("")], note=LOW),
 dict(sid="p8s3", page=8, slot=3, no=2, venue="乙", totalA=None, totalB=None,
      A=[P("A","楊文岩"), P("A","鄭伃涵"), P("A","顏貝宸")],
      B=[P("B","邱璟晏"), P("B","蔡棠茹"), P("B","陳品璇")],
      refs=[ref("涂菲倢"), ref("李心瑤"), ref("林芯妮")], note=LOW),
 # ---- 第 9 頁 ----
 dict(sid="p9s1", page=9, slot=1, no=4, venue="乙", totalA=2, totalB=6,
      A=[P("A","余沛晨"), P("A","陳慧妮"), P("A","駱舒涵")],
      B=[P("B","張雅安"), P("B","陳芊靜"), P("B","涂菲倢")],
      refs=[ref("駱舒涵"), ref(""), ref("蔡棠茹")], note=LOW),
 dict(sid="p9s2", page=9, slot=2, no=1, venue="甲", totalA=0, totalB=0,
      A=[P("A","李栢健"), P("A","李心瑤"), P("A","林芯妮")],
      B=[P("B","涂菲倢"), P("B","黃韻文"), P("B","何莉妍")],
      refs=[ref("陳慧芝"), ref(""), ref("")],
      note="A隊第①欄姓名疑似名單外，請補；"+LOW),
 dict(sid="p9s3", page=9, slot=3, no=6, venue="乙", totalA=6, totalB=2,
      A=[P("A","方佩榮"), P("A","池旻柔"), P("A","何莉妍")],
      B=[P("B","楊文岩"), P("B","羅翊菲"), P("B","顏貝宸")],
      refs=[ref(""), ref(""), ref("")], note=LOW),
 # ---- 第 10 頁 ----
 dict(sid="p10s1", page=10, slot=1, no=8, venue="甲", totalA=6, totalB=0,
      A=[P("A","陳喬妤"), P("A","鄭伃涵"), P("A","余沛晨")],
      B=[P("B","方佩榮"), P("B","呂豫新"), P("B","陳慧妮")],
      refs=[ref("楊文岩"), ref(""), ref("池旻柔")], note=LOW),
 dict(sid="p10s2", page=10, slot=2, no=2, venue="甲", totalA=2, totalB=None,
      A=[P("A","方佩榮"), P("A","池旻柔"), P("A","何莉妍")],
      B=[P("B","方佩榮"), P("B","呂豫新"), P("B","陳慧妮")],
      refs=[ref(""), ref("李心瑤"), ref("張雅安")],
      note="兩隊疑有同名球員，請特別核對；"+LOW),
 dict(sid="p10s3", page=10, slot=3, no=4, venue="甲", totalA=2, totalB=4,
      A=[P("A","歐陽吉鸞"), P("A","毛國鳳"), P("A","楊濰瑄")],
      B=[P("B","楊喬安"), P("B","張楷寧"), P("B","余沛晨")],
      refs=[ref("吉芸箴"), ref("張妤丞"), ref("陳慧芝")], note=LOW),
 # ---- 第 11 頁 ----
 dict(sid="p11s1", page=11, slot=1, no=6, venue="甲", totalA=0, totalB=4,
      A=[P("A","陳品璇"), P("A","駱舒涵"), P("A","呂安芊")],
      B=[P("B","邱璟晏"), P("B","蔡棠茹"), P("B","陳品璇")],
      refs=[ref("余沛晨"), ref("陳慧芝"), ref("")], note=LOW),
 dict(sid="p11s2", page=11, slot=2, no=7, venue="乙", totalA=18, totalB=6,
      A=[P("A","張楷寧"), P("A","楊喬安"), P("A","林芯妮")],
      B=[P("B",""), P("B",""), P("B","")],
      refs=[ref("陳慧芝"), ref("吉芸箴"), ref("張妤丞")],
      note="B隊三位姓名未能辨識，請補；"+LOW),
 dict(sid="p11s3", page=11, slot=3, no=4, venue="", totalA=None, totalB=None,
      A=[P("A","余沛晨"), P("A","呂安芊"), P("A","駱舒涵")],
      B=[P("B",""), P("B",""), P("B","")],
      refs=[ref("鄭仕涵"), ref("余沛晨"), ref("陳喬妤")],
      note="表頭場次/場地與B隊姓名不清，請補；"+LOW),
 # ---- 第 4 頁 (橫式, rot270) ----
 dict(sid="p4s1", page=4, slot=1, no=24, venue="甲", totalA=0, totalB=13,
      A=[P("A","池旻柔"), P("A","黃韻文"), P("A","楊欣妍")],
      B=[P("B","鄭仕涵"), P("B","陳喬妤"), P("B","蔡宜臻")],
      refs=[ref("吉芸箴"), ref("張妤丞"), ref("陳慧芝")], note=LOW),
 dict(sid="p4s2", page=4, slot=2, no=15, venue="甲", totalA=8, totalB=2,
      A=[P("A","余沛晨"), P("A","陳喬妤"), P("A","鄭伃涵")],
      B=[P("B","吉芸箴"), P("B","陳慧芝"), P("B","張妤丞")],
      refs=[ref("陳品璇"), ref("呂安芊"), ref("邱璟晏")], note=LOW),
 dict(sid="p4s3", page=4, slot=3, no=15, venue="乙", totalA=8, totalB=4,
      A=[P("A","駱舒涵"), P("A","李珮綺"), P("A","林以昕")],
      B=[P("B","林芯妮"), P("B","李心瑤"), P("B","涂菲倢")],
      refs=[ref("蔡宜臻"), ref("吳焄綺"), ref("許竹瑩")], note=LOW),
 # ---- 第 6 頁 (補 s2,s3) ----
 dict(sid="p6s2", page=6, slot=2, no=11, venue="甲", totalA=None, totalB=None,
      A=[P("A","駱舒涵"), P("A","李珮綺"), P("A","林以昕")],
      B=[P("B","池旻柔"), P("B","楊欣妍"), P("B","黃韻文")],
      refs=[ref("陳品璇"), ref("張楷寧"), ref("呂豫新")], note=LOW),
 dict(sid="p6s3", page=6, slot=3, no=11, venue="乙", totalA=8, totalB=10,
      A=[P("A","林芯妮"), P("A","涂菲倢"), P("A","張雅安")],
      B=[P("B","陳慧芝"), P("B","張妤丞"), P("B","吉芸箴")],
      refs=[ref("許竹瑩"), ref("蔡宜臻"), ref("吳焄綺")], note=LOW),
 # ---- 第 12 頁 (橫式 rot0, 只有 2 張) ----
 dict(sid="p12s1", page=12, slot=1, no=3, venue="乙", totalA=0, totalB=10,
      A=[P("A","駱舒涵"), P("A","李珮綺"), P("A","林以昕")],
      B=[P("B","楊喬安",4), P("B","張楷寧"), P("B","陳芊靜",6)],
      refs=[ref("楊文岩"), ref("羅翊菲"), ref("顏貝宸")], note=LOW),
 dict(sid="p12s2", page=12, slot=2, no=5, venue="乙", totalA=0, totalB=10,
      A=[P("A","李珮綺"), P("A","林芯妮"), P("A","李心瑤")],
      B=[P("B","呂豫新"), P("B","方佩榮"), P("B","陳慧妮")],
      refs=[ref("陳喬妤"), ref("張楷寧"), ref("張妤丞")], note=LOW),
]

def main():
    server.init_db()
    c = server.conn()
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
            "totalA": "" if s.get("totalA") is None else s["totalA"],
            "totalB": "" if s.get("totalB") is None else s["totalB"],
            "refMain": rm[0], "refAsst": ra[0], "refScorer": rs[0],
            "fmain": rm[1], "fasst": ra[1], "fscorer": rs[1],
            "fno": False, "fvenue": (s["venue"] == ""), "note": s["note"],
        }
        server.upsert_sheet(c, sheet, confirmed=0, autototal=True)
        inserted += 1
    c.commit(); c.close()
    print(f"灌入/更新 {inserted} 張草稿，跳過已確認 {skipped} 張。")

if __name__ == "__main__":
    main()
