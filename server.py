#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""籃球攻守紀錄 — 本地校對/彙整服務 (純 Python 標準庫, 零安裝)

啟動: python3 server.py  (或雙擊 start.command)
資料永遠住在 bball.db, 與前端 HTML 完全脫鉤; 換前端不會掉資料。
"""
import os, re, json, sqlite3, base64, webbrowser, threading, time, hashlib, contextlib, base64 as _b64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "bball.db")
SEED_JSON = os.path.join(HERE, "辨識DB.json")
PORT = int(os.environ.get("PORT", 8770))

# 雲端模式: 有 DATABASE_URL 就用 Postgres(雲端唯一正本), 否則用本地 SQLite(本機開發/辨識)。
DATABASE_URL = os.environ.get("DATABASE_URL")
PG = bool(DATABASE_URL)
HOST = os.environ.get("HOST", "0.0.0.0" if PG else "127.0.0.1")
# 登入保護: 設了 APP_PASS 才啟用 HTTP Basic(雲端必設; 本地留空不影響)。
APP_USER = os.environ.get("APP_USER", "")
APP_PASS = os.environ.get("APP_PASS", "")
if PG:
    import psycopg
    from psycopg.rows import dict_row

# 每位球員各自的欄位(不含總得分; 總得分改為隊伍級, 存在 games.total_a/total_b)
STAT_KEYS = ["pts", "foul", "tfoul", "ast", "oreb", "dreb", "stl"]

# 多班級: 既有(單班時代)資料一律歸到這個預設班, 之後可在 UI 改名。
DEFAULT_KLASS = "女籃3對3"

# ---------------------------------------------------------------- DB layer
def conn():
    """單次連線(給一次性腳本: migrate/import/build 用)。伺服器熱路徑請改用 db()。"""
    if PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

# 雲端模式: 用連線池, 避免每個 HTTP request 都重新撥接遠端 Neon(這是「點一下很慢」的主因)。
_pool = None
def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=4,
                               kwargs={"row_factory": dict_row}, open=False)
        _pool.open()
    return _pool

@contextlib.contextmanager
def db():
    """伺服器熱路徑統一入口: PG 走連線池(重複使用連線), 本地走單次 SQLite 連線。"""
    if PG:
        with _get_pool().connection() as c:
            yield c
    else:
        c = conn()
        try:
            yield c
        finally:
            c.close()

def q(sql):
    """SQLite 用 ?, Postgres 用 %s。其餘 SQL 兩邊通用。"""
    return sql.replace("?", "%s") if PG else sql

def ensure_player(c, name, ordv):
    """INSERT OR IGNORE 的跨方言版本。"""
    if PG:
        c.execute("INSERT INTO players(name, ord) VALUES(%s,%s) ON CONFLICT (name) DO NOTHING", (name, ordv))
    else:
        c.execute("INSERT OR IGNORE INTO players(name, ord) VALUES(?,?)", (name, ordv))

BACKUP_DIR = os.path.join(HERE, "backups")

def backup_db(keep=40):
    """啟動時把現有 bball.db 複製一份到 backups/, 永不刪原檔。保留最近 keep 份。
    Postgres 模式下不適用(請用 pg_dump 備份), 直接略過。"""
    if PG or not os.path.exists(DB):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    import shutil
    dst = os.path.join(BACKUP_DIR, "bball-" + time.strftime("%Y%m%d-%H%M%S") + ".db")
    if not os.path.exists(dst):
        shutil.copy2(DB, dst)
    baks = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bball-") and f.endswith(".db"))
    for old in baks[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def init_db():
    c = conn()
    pk = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    blob = "BYTEA" if PG else "BLOB"
    stmts = [
        "CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY, ord INTEGER)",
        f"""CREATE TABLE IF NOT EXISTS games(
          id {pk},
          sid TEXT UNIQUE,
          no TEXT, venue TEXT, date TEXT,
          ref_main TEXT, ref_asst TEXT, ref_scorer TEXT,
          page INTEGER, idx_on_page INTEGER,
          fno INTEGER DEFAULT 0, fvenue INTEGER DEFAULT 0,
          fmain INTEGER DEFAULT 0, fasst INTEGER DEFAULT 0, fscorer INTEGER DEFAULT 0,
          note TEXT, img TEXT,
          total_a INTEGER, total_b INTEGER,
          confirmed INTEGER DEFAULT 0,
          updated TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS stat_lines(
          id {pk},
          game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
          team TEXT, col INTEGER,
          name TEXT, name_uncertain INTEGER DEFAULT 0, grp TEXT,
          pts INTEGER, foul INTEGER, tfoul INTEGER, ast INTEGER,
          oreb INTEGER, dreb INTEGER, stl INTEGER, total INTEGER,
          points INTEGER,
          conflict INTEGER DEFAULT 0, maybe3 INTEGER DEFAULT 0,
          marks TEXT, note TEXT
        )""",
        # ── 多班級新增表 (additive, 不動既有表) ──
        # classes: 每個班一列。archived=1 表示「已結束/封存」(隱藏但不刪資料)。
        f"""CREATE TABLE IF NOT EXISTS classes(
          id {pk},
          name TEXT UNIQUE,
          created TEXT,
          archived INTEGER DEFAULT 0
        )""",
        # roster: 各班名單(取代全域 players)。同名可在不同班各存一份。
        f"""CREATE TABLE IF NOT EXISTS roster(
          id {pk},
          klass TEXT, name TEXT, ord INTEGER
        )""",
        # uploads: 助教上傳的攻守記錄表 PDF 收件匣。data 存原始位元組(雲端正本)。
        f"""CREATE TABLE IF NOT EXISTS uploads(
          id {pk},
          klass TEXT, filename TEXT, mime TEXT,
          data {blob},
          status TEXT DEFAULT '待辨識',
          uploaded_at TEXT, note TEXT
        )""",
    ]
    for s in stmts:
        c.execute(s)
    # 既有資料庫補欄位 (additive, 安全)
    for col in ("total_a", "total_b"):
        if PG:
            c.execute(f"ALTER TABLE games ADD COLUMN IF NOT EXISTS {col} INTEGER")
        else:
            try:
                c.execute(f"ALTER TABLE games ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass
    # games 補班別欄
    if PG:
        c.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS klass TEXT")
    else:
        try:
            c.execute("ALTER TABLE games ADD COLUMN klass TEXT")
        except sqlite3.OperationalError:
            pass
    # games 補來源欄: 'ai'=AI辨識草稿(需逐格驗證) / 'manual'=助教傳統手動登記。
    if PG:
        c.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'ai'")
    else:
        try:
            c.execute("ALTER TABLE games ADD COLUMN source TEXT DEFAULT 'ai'")
        except sqlite3.OperationalError:
            pass
    # roster 同班不重名
    if PG:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS roster_klass_name ON roster(klass, name)")
    else:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS roster_klass_name ON roster(klass, name)")
    c.commit()
    migrate_to_classes(c)
    c.commit()
    c.close()

def migrate_to_classes(c):
    """把單班時代的資料一次性歸到 DEFAULT_KLASS, 冪等可重跑:
       1. 確保 DEFAULT_KLASS 這個班存在。
       2. 既有 games.klass 為 NULL 的, 補成 DEFAULT_KLASS。
       3. 把全域 players 名單複製進 roster(DEFAULT_KLASS)。
       完全 additive — 不刪 players、不動 stat_lines。"""
    # 還沒有任何班別資料才需要遷移(避免重跑覆寫使用者後來改的班名)
    has_klass = c.execute("SELECT COUNT(*) AS n FROM games WHERE klass IS NOT NULL AND klass<>''").fetchone()["n"]
    n_games = c.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
    n_classes = c.execute("SELECT COUNT(*) AS n FROM classes").fetchone()["n"]
    # 有 games 但都還沒分班 → 視為待遷移的舊資料庫
    if n_games and not has_klass:
        _ensure_class(c, DEFAULT_KLASS)
        c.execute(q("UPDATE games SET klass=? WHERE klass IS NULL OR klass=''"), (DEFAULT_KLASS,))
        rows = c.execute("SELECT name, ord FROM players ORDER BY ord").fetchall()
        for r in rows:
            _add_roster(c, DEFAULT_KLASS, r["name"], r["ord"])
        print(f"  已遷移舊資料 → 班級「{DEFAULT_KLASS}」: {n_games} 場、{len(rows)} 位名單")
    elif n_classes == 0 and n_games == 0:
        # 全新空庫: 不建任何班, 等使用者自己新增。
        pass

def _ensure_class(c, name):
    if PG:
        c.execute("INSERT INTO classes(name, created, archived) VALUES(%s,%s,0) ON CONFLICT (name) DO NOTHING",
                  (name, now()))
    else:
        c.execute("INSERT OR IGNORE INTO classes(name, created, archived) VALUES(?,?,0)", (name, now()))

def _add_roster(c, klass, name, ordv):
    if not (name or "").strip():
        return
    if PG:
        c.execute("INSERT INTO roster(klass,name,ord) VALUES(%s,%s,%s) ON CONFLICT (klass,name) DO NOTHING",
                  (klass, name, ordv))
    else:
        c.execute("INSERT OR IGNORE INTO roster(klass,name,ord) VALUES(?,?,?)", (klass, name, ordv))

def seed_if_empty():
    c = conn()
    n = c.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
    if n:
        c.close()
        return
    if not os.path.exists(SEED_JSON):
        c.close()
        return
    data = json.load(open(SEED_JSON, encoding="utf-8"))
    roster = data.get("roster", [])
    _ensure_class(c, DEFAULT_KLASS)
    for i, name in enumerate(roster):
        ensure_player(c, name, i)      # 保留全域 players(向後相容)
        _add_roster(c, DEFAULT_KLASS, name, i)
    for sheet in data.get("sheets", []):
        upsert_sheet(c, sheet, confirmed=0, autototal=True, klass=DEFAULT_KLASS)
    c.commit()
    c.close()
    print(f"  已灌入種子: {len(data.get('sheets', []))} 場草稿、{len(roster)} 位名單 → 班級「{DEFAULT_KLASS}」")

def _i(v):
    """空字串/None -> None, 否則 int"""
    if v == "" or v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def parse_sid_page(sid):
    # 容許班別前綴(如 "女籃3對3-u5-p1s2"), 用 search 從尾端抓 p<頁>s<張>。
    m = re.search(r"p(\d+)s(\d+)", sid or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

def upsert_sheet(c, s, confirmed=None, autototal=False, klass=None, source=None):
    """寫入一場草稿(metadata + stat_lines)。confirmed=None 表沿用既有值。
    autototal=True 時(辨識/種子)隊伍總得分若空白則自動帶入三人加總;
    前端存檔(autototal=False)則完全照前端送來的值, 空白就存 NULL, 確保前後端一致。
    klass 有給就寫入班別(沿用既有時不要動到別的班)。"""
    sid = s["sid"]
    if klass is None:
        klass = s.get("klass")  # 也接受 sheet dict 內帶 klass
    src = source if source is not None else s.get("source")   # 'ai' / 'manual'
    page, idx = parse_sid_page(sid)
    row = c.execute(q("SELECT id, confirmed, img, source FROM games WHERE sid=?"), (sid,)).fetchone()
    # 鐵則: AI 辨識(source='ai')永不覆蓋助教手動登記的既有列。
    if row and (row["source"] == "manual") and (src == "ai"):
        return row["id"]
    img = s.get("img")
    if img is None and row:
        img = row["img"]  # 不要被前端覆寫掉圖片
    keep_conf = row["confirmed"] if row else 0
    conf = keep_conf if confirmed is None else (1 if confirmed else 0)
    core = (
        str(s.get("no", "")), s.get("venue", ""), s.get("date", ""),
        s.get("refMain", ""), s.get("refAsst", ""), s.get("refScorer", ""),
        int(bool(s.get("fno"))), int(bool(s.get("fvenue"))),
        int(bool(s.get("fmain"))), int(bool(s.get("fasst"))), int(bool(s.get("fscorer"))),
        s.get("note", ""), img, conf, now(),
    )
    if row:
        gid = row["id"]
        c.execute(q("""UPDATE games SET no=?, venue=?, date=?, ref_main=?, ref_asst=?, ref_scorer=?,
                     fno=?, fvenue=?, fmain=?, fasst=?, fscorer=?, note=?, img=?, confirmed=?, updated=?
                     WHERE id=?"""),
                  core + (gid,))
        c.execute(q("DELETE FROM stat_lines WHERE game_id=?"), (gid,))
    else:
        ins = q("""INSERT INTO games
            (no,venue,date,ref_main,ref_asst,ref_scorer,fno,fvenue,fmain,fasst,fscorer,
             note,img,confirmed,updated,sid,page,idx_on_page)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""")
        params = core + (sid, page, idx)
        if PG:
            gid = c.execute(ins + " RETURNING id", params).fetchone()["id"]
        else:
            gid = c.execute(ins, params).lastrowid
    team_pts = {"A": 0, "B": 0}
    for col, p in enumerate(s.get("players", []), start=1):
        st = p.get("stats", {})
        def sv(k):
            return _i((st.get(k) or {}).get("v", ""))
        marks = {k: bool((st.get(k) or {}).get("m")) for k in STAT_KEYS}
        pts = sv("pts")                 # 個人得分(正字筆數)
        points = pts                    # 彙整以個人得分為準
        team = p.get("team", "")
        if team in team_pts:
            team_pts[team] += pts or 0
        c.execute(q("""INSERT INTO stat_lines
            (game_id,team,col,name,name_uncertain,grp,pts,foul,tfoul,ast,oreb,dreb,stl,total,points,
             conflict,maybe3,marks,note)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
            (gid, team, col, p.get("name", ""), int(bool(p.get("fname"))),
             p.get("group", ""), pts, sv("foul"), sv("tfoul"), sv("ast"),
             sv("oreb"), sv("dreb"), sv("stl"), None, points,
             0, int(bool(p.get("maybe3"))),
             json.dumps(marks), p.get("note", "")))
    # 隊伍總得分
    ta = _i(s.get("totalA"))
    tb = _i(s.get("totalB"))
    if autototal:
        if ta is None:
            ta = team_pts["A"]
        if tb is None:
            tb = team_pts["B"]
    c.execute(q("UPDATE games SET total_a=?, total_b=? WHERE id=?"), (ta, tb, gid))
    if klass:
        c.execute(q("UPDATE games SET klass=? WHERE id=?"), (klass, gid))
    if src:
        c.execute(q("UPDATE games SET source=? WHERE id=?"), (src, gid))
    return gid

def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def sheet_to_dict(g, lines):
    players = []
    for ln in lines:
        marks = json.loads(ln["marks"] or "{}")
        stats = {}
        for k in STAT_KEYS:
            v = ln[k]
            stats[k] = {"v": "" if v is None else v, "m": bool(marks.get(k))}
        players.append({
            "team": ln["team"], "name": ln["name"] or "", "fname": bool(ln["name_uncertain"]),
            "group": ln["grp"] or "", "stats": stats,
            "conflict": bool(ln["conflict"]), "maybe3": bool(ln["maybe3"]),
            "note": ln["note"] or "",
        })
    no = g["no"]
    return {
        "sid": g["sid"], "img": f"/img/{g['sid']}",
        "no": "" if no in (None, "None", "") else no,
        "venue": g["venue"] or "", "date": g["date"] or "",
        "fno": bool(g["fno"]), "fvenue": bool(g["fvenue"]),
        "totalA": "" if g["total_a"] is None else g["total_a"],
        "totalB": "" if g["total_b"] is None else g["total_b"],
        "players": players,
        "refMain": g["ref_main"] or "", "refAsst": g["ref_asst"] or "", "refScorer": g["ref_scorer"] or "",
        "fmain": bool(g["fmain"]), "fasst": bool(g["fasst"]), "fscorer": bool(g["fscorer"]),
        "note": g["note"] or "", "done": bool(g["confirmed"]),
        "source": g["source"] or "ai", "hasImg": bool(g["img"]),
    }

def get_sheets(klass=None, source=None):
    """klass 有給就只回該班的場次; source 有給('ai'/'manual')再依來源過濾; 皆 None 回全部。"""
    with db() as c:
        conds, params = [], []
        if klass:
            conds.append("klass=?"); params.append(klass)
        if source:
            conds.append("source=?"); params.append(source)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        gs = c.execute(q("SELECT * FROM games" + where + " ORDER BY page, idx_on_page, id"),
                       tuple(params)).fetchall()
        all_lines = c.execute("SELECT * FROM stat_lines ORDER BY game_id, col").fetchall()
    by_game = {}
    for ln in all_lines:
        by_game.setdefault(ln["game_id"], []).append(ln)
    gids = {g["id"] for g in gs}
    return [sheet_to_dict(g, by_game.get(g["id"], [])) for g in gs if g["id"] in gids]

def get_roster(klass=None):
    """klass 有給回該班名單(roster 表); None 時退回全域 players(向後相容)。"""
    with db() as c:
        if klass:
            return [row["name"] for row in
                    c.execute(q("SELECT name FROM roster WHERE klass=? ORDER BY ord"), (klass,))]
        return [row["name"] for row in c.execute("SELECT name FROM players ORDER BY ord")]

def get_img(sid):
    """回傳 (mime, blob, etag)。etag 供瀏覽器快取比對(304)。"""
    with db() as c:
        row = c.execute(q("SELECT img FROM games WHERE sid=?"), (sid,)).fetchone()
    if not row or not row["img"]:
        return None, None, None
    uri = row["img"]
    m = re.match(r"data:([^;,]+)[^,]*,(.*)", uri, re.S)
    if not m:
        return None, None, None
    mime, b64 = m.group(1), m.group(2)
    try:
        blob = base64.b64decode(b64)
    except Exception:
        return None, None, None
    etag = '"' + hashlib.md5(b64.encode("ascii", "ignore")).hexdigest()[:16] + '"'
    return mime, blob, etag

def compute_summary(klass=None):
    """回傳 14 欄統計總表 (僅計 confirmed=1 的場次)。klass 有給就只計該班。"""
    with db() as c:
        if klass:
            roster = [row["name"] for row in
                      c.execute(q("SELECT name FROM roster WHERE klass=? ORDER BY ord"), (klass,))]
            games = c.execute(q("SELECT * FROM games WHERE confirmed=1 AND klass=?"), (klass,)).fetchall()
        else:
            roster = [row["name"] for row in c.execute("SELECT name FROM players ORDER BY ord")]
            games = c.execute("SELECT * FROM games WHERE confirmed=1").fetchall()
        gids = {g["id"] for g in games}
        all_lines = c.execute("SELECT * FROM stat_lines").fetchall()
    order = {n: i for i, n in enumerate(roster)}
    by_game = {}
    for ln in all_lines:
        if ln["game_id"] in gids:
            by_game.setdefault(ln["game_id"], []).append(ln)
    agg = {}
    def slot(name):
        if name not in agg:
            agg[name] = dict(games=0, win=0, loss=0, pts=0, ast=0, stl=0,
                             dreb=0, oreb=0, foul=0, ref_main=0, ref_asst=0, ref_scorer=0)
        return agg[name]
    for g in games:
        lines = by_game.get(g["id"], [])
        ta, tb = g["total_a"], g["total_b"]
        if ta is None and tb is None:  # 後備: 由個人得分加總
            ta = sum(ln["points"] or 0 for ln in lines if ln["team"] == "A")
            tb = sum(ln["points"] or 0 for ln in lines if ln["team"] == "B")
        team_pts = {"A": ta or 0, "B": tb or 0}
        for ln in lines:
            nm = (ln["name"] or "").strip()
            if not nm:
                continue
            s = slot(nm)
            s["games"] += 1
            s["pts"] += ln["points"] or 0
            s["ast"] += ln["ast"] or 0
            s["stl"] += ln["stl"] or 0
            s["dreb"] += ln["dreb"] or 0
            s["oreb"] += ln["oreb"] or 0
            s["foul"] += ln["foul"] or 0
            mine, other = team_pts.get(ln["team"], 0), team_pts.get("B" if ln["team"] == "A" else "A", 0)
            if mine > other:
                s["win"] += 1
            elif mine < other:
                s["loss"] += 1
        for col, key in (("ref_main", "ref_main"), ("ref_asst", "ref_asst"), ("ref_scorer", "ref_scorer")):
            nm = (g[col] or "").strip()
            if nm:
                slot(nm)[key] += 1
    names = list(roster) + [n for n in agg if n not in order]
    rows = []
    for i, nm in enumerate(names, start=1):
        s = agg.get(nm, dict(games=0, win=0, loss=0, pts=0, ast=0, stl=0,
                             dreb=0, oreb=0, foul=0, ref_main=0, ref_asst=0, ref_scorer=0))
        rows.append({
            "序號": i, "姓名": nm, "完賽場數": s["games"], "勝場次": s["win"], "負場次": s["loss"],
            "總得分": s["pts"], "助攻": s["ast"], "抄截": s["stl"], "防守籃板": s["dreb"],
            "進攻籃板": s["oreb"], "犯規": s["foul"], "擔任主裁判": s["ref_main"],
            "擔任副裁判": s["ref_asst"], "擔任紀錄": s["ref_scorer"],
        })
    return rows

SUMMARY_COLS = ["序號", "姓名", "完賽場數", "勝場次", "負場次", "總得分", "助攻", "抄截",
                "防守籃板", "進攻籃板", "犯規", "擔任主裁判", "擔任副裁判", "擔任紀錄"]

# ---------------------------------------------------------------- 班級 / 名單 / 收件匣 資料層
def list_classes(include_archived=False):
    """回每個班的概況: 名單人數、場次數、待辨識/待校對數。"""
    with db() as c:
        if include_archived:
            cls = c.execute("SELECT * FROM classes ORDER BY archived, id").fetchall()
        else:
            cls = c.execute("SELECT * FROM classes WHERE archived=0 ORDER BY id").fetchall()
        out = []
        for k in cls:
            nm = k["name"]
            roster_n = c.execute(q("SELECT COUNT(*) AS n FROM roster WHERE klass=?"), (nm,)).fetchone()["n"]
            games_n = c.execute(q("SELECT COUNT(*) AS n FROM games WHERE klass=?"), (nm,)).fetchone()["n"]
            conf_n = c.execute(q("SELECT COUNT(*) AS n FROM games WHERE klass=? AND confirmed=1"), (nm,)).fetchone()["n"]
            pend_up = c.execute(q("SELECT COUNT(*) AS n FROM uploads WHERE klass=? AND status='待辨識'"), (nm,)).fetchone()["n"]
            out.append({
                "id": k["id"], "name": nm, "archived": bool(k["archived"]),
                "roster": roster_n, "games": games_n, "confirmed": conf_n,
                "todo": games_n - conf_n, "pending_uploads": pend_up,
            })
    return out

def create_class(name):
    name = (name or "").strip()
    if not name:
        return False, "班級名稱不能空白"
    with db() as c:
        exists = c.execute(q("SELECT 1 FROM classes WHERE name=?"), (name,)).fetchone()
        if exists:
            return False, "已有同名班級"
        _ensure_class(c, name)
        c.commit()
    return True, "已新增班級"

def rename_class(old, new):
    old, new = (old or "").strip(), (new or "").strip()
    if not new:
        return False, "新名稱不能空白"
    with db() as c:
        if not c.execute(q("SELECT 1 FROM classes WHERE name=?"), (old,)).fetchone():
            return False, "找不到原班級"
        if old != new and c.execute(q("SELECT 1 FROM classes WHERE name=?"), (new,)).fetchone():
            return False, "新名稱已被其他班級使用"
        # 班別是用「名字」當外鍵, 改名要連動 games / roster / uploads。
        c.execute(q("UPDATE classes SET name=? WHERE name=?"), (new, old))
        c.execute(q("UPDATE games   SET klass=? WHERE klass=?"), (new, old))
        c.execute(q("UPDATE roster  SET klass=? WHERE klass=?"), (new, old))
        c.execute(q("UPDATE uploads SET klass=? WHERE klass=?"), (new, old))
        c.commit()
    return True, "已改名"

def archive_class(name, archived=True):
    """封存/取消封存(隱藏但保留所有資料)。這是 UI「刪除」的安全預設。"""
    with db() as c:
        if not c.execute(q("SELECT 1 FROM classes WHERE name=?"), (name,)).fetchone():
            return False, "找不到班級"
        c.execute(q("UPDATE classes SET archived=? WHERE name=?"), (1 if archived else 0, name))
        c.commit()
    return True, ("已封存" if archived else "已取消封存")

def set_roster(klass, names):
    """整批覆寫某班名單(去空白、去重、保留順序)。"""
    seen, clean = set(), []
    for nm in names:
        nm = (nm or "").strip()
        if nm and nm not in seen:
            seen.add(nm); clean.append(nm)
    with db() as c:
        _ensure_class(c, klass)
        c.execute(q("DELETE FROM roster WHERE klass=?"), (klass,))
        for i, nm in enumerate(clean):
            _add_roster(c, klass, nm, i)
            ensure_player(c, nm, i)   # 同步進全域 players, 讓既有彙整/下拉也認得
        c.commit()
    return len(clean)

def add_upload(klass, filename, mime, data):
    with db() as c:
        ins = q("""INSERT INTO uploads(klass,filename,mime,data,status,uploaded_at)
                   VALUES(?,?,?,?, '待辨識', ?)""")
        params = (klass, filename, mime, data, now())
        if PG:
            uid = c.execute(ins + " RETURNING id", params).fetchone()["id"]
        else:
            uid = c.execute(ins, params).lastrowid
        c.commit()
    return uid

def list_uploads(klass=None, status=None):
    sql = "SELECT id, klass, filename, mime, status, uploaded_at FROM uploads"
    where, params = [], []
    if klass:
        where.append("klass=?"); params.append(klass)
    if status:
        where.append("status=?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with db() as c:
        return [dict(r) for r in c.execute(q(sql), tuple(params))]

def get_upload_file(uid):
    with db() as c:
        row = c.execute(q("SELECT filename, mime, data FROM uploads WHERE id=?"), (uid,)).fetchone()
    if not row or row["data"] is None:
        return None, None, None
    return row["mime"] or "application/pdf", bytes(row["data"]), row["filename"]

def delete_upload(uid):
    with db() as c:
        c.execute(q("DELETE FROM uploads WHERE id=?"), (uid,))
        c.commit()
    return True

def delete_sheet(sid):
    """刪一場(連同 stat_lines 級聯)。安全限制: 只允許刪 source='manual' 的場,
       避免手動模式誤刪到 AI 卡片。"""
    with db() as c:
        row = c.execute(q("SELECT id, source FROM games WHERE sid=?"), (sid,)).fetchone()
        if not row:
            return False, "找不到此場"
        if (row["source"] or "ai") != "manual":
            return False, "只能刪除手動登記的場次"
        c.execute(q("DELETE FROM stat_lines WHERE game_id=?"), (row["id"],))
        c.execute(q("DELETE FROM games WHERE id=?"), (row["id"],))
        c.commit()
    return True, "已刪除"

# ---------------------------------------------------------------- HTTP layer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        """設了 APP_PASS 才檢查。未通過則回 401 並要求登入。"""
        if not APP_PASS:
            return True
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                user, _, pw = _b64.b64decode(hdr[6:]).decode("utf-8").partition(":")
                if user == APP_USER and pw == APP_PASS:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="bball"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name, ctype):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def _qs(self):
        """取 URL query 參數(單值)。"""
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        if not self._authed():
            return
        p = unquote(urlparse(self.path).path)   # 解碼中文路徑(/校對 /上傳 /使用教學)
        qs = self._qs()
        klass = qs.get("klass") or None
        # ── 頁面 ──
        if p in ("/", "/index.html", "/班級"):
            return self._file("班級.html", "text/html; charset=utf-8")
        if p in ("/校對", "/sheet", "/校對.html"):
            return self._file("校對.html", "text/html; charset=utf-8")
        if p in ("/summary", "/summary.html", "/總表"):
            return self._file("統計總表.html", "text/html; charset=utf-8")
        if p in ("/upload", "/上傳", "/上傳.html"):
            return self._file("上傳.html", "text/html; charset=utf-8")
        if p in ("/手動登記", "/manual", "/手動登記.html"):
            return self._file("手動登記.html", "text/html; charset=utf-8")
        if p in ("/help", "/使用教學", "/使用教學.html"):
            return self._file("使用教學.html", "text/html; charset=utf-8")
        # ── API ──
        if p == "/api/classes":
            return self._send(200, list_classes(include_archived=bool(qs.get("all"))))
        if p == "/api/roster":
            return self._send(200, get_roster(klass))
        if p == "/api/sheets":
            return self._send(200, {"klass": klass, "roster": get_roster(klass),
                                    "sheets": get_sheets(klass, qs.get("source"))})
        if p == "/api/summary":
            return self._send(200, {"klass": klass, "cols": SUMMARY_COLS, "rows": compute_summary(klass)})
        if p == "/api/summary.csv":
            rows = compute_summary(klass)
            lines = [",".join(SUMMARY_COLS)]
            for r in rows:
                lines.append(",".join(str(r[c]) for c in SUMMARY_COLS))
            csv = "﻿" + "\r\n".join(lines)
            return self._send(200, csv, "text/csv; charset=utf-8")
        if p == "/api/export":
            return self._send(200, {"klass": klass, "roster": get_roster(klass), "sheets": get_sheets(klass)})
        if p == "/api/uploads":
            return self._send(200, list_uploads(klass, qs.get("status")))
        if p.startswith("/api/upload/") and p.endswith("/file"):
            try:
                uid = int(p[len("/api/upload/"):-len("/file")])
            except ValueError:
                return self._send(404, {"error": "bad id"})
            mime, blob, fname = get_upload_file(uid)
            if blob is None:
                return self._send(404, {"error": "no file"})
            return self._send(200, blob, mime, headers={
                "Cache-Control": "private, max-age=3600",
                "Content-Disposition": f'inline; filename="{uid}.pdf"',
            })
        if p.startswith("/img/"):
            sid = p[len("/img/"):]   # p 已整段 unquote, 不再重複解碼
            mime, blob, etag = get_img(sid)
            if blob is None:
                return self._send(404, {"error": "no image"})
            # 圖片可長快取(每場圖固定不變), 重訪分頁就不再重新下載 → 載入瞬間完成。
            if etag and self.headers.get("If-None-Match", "") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._send(200, blob, mime, headers={
                "Cache-Control": "public, max-age=86400",
                "ETag": etag or "",
            })
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._send(400, {"error": "bad json"})
        if p in ("/api/save", "/api/confirm"):
            confirmed = 1 if p == "/api/confirm" else None
            with db() as c:
                upsert_sheet(c, body, confirmed=confirmed, klass=body.get("klass"), source=body.get("source"))
                c.commit()
            return self._send(200, {"ok": True, "sid": body.get("sid"), "confirmed": bool(confirmed)})
        # ── 班級管理 ──
        if p == "/api/class/create":
            ok, msg = create_class(body.get("name", ""))
            return self._send(200 if ok else 400, {"ok": ok, "msg": msg})
        if p == "/api/class/rename":
            ok, msg = rename_class(body.get("old", ""), body.get("new", ""))
            return self._send(200 if ok else 400, {"ok": ok, "msg": msg})
        if p == "/api/class/archive":
            ok, msg = archive_class(body.get("name", ""), bool(body.get("archived", True)))
            return self._send(200 if ok else 400, {"ok": ok, "msg": msg})
        # ── 名單 ──
        if p == "/api/roster/set":
            klass = (body.get("klass") or "").strip()
            if not klass:
                return self._send(400, {"ok": False, "msg": "缺少班級"})
            names = body.get("names")
            if names is None:  # 也接受整段文字(換行/逗號/空白分隔)
                names = re.split(r"[\n,、\s]+", body.get("text", ""))
            n = set_roster(klass, names)
            return self._send(200, {"ok": True, "count": n})
        # ── 收件匣 ──
        if p == "/api/upload":
            klass = (body.get("klass") or "").strip()
            if not klass:
                return self._send(400, {"ok": False, "msg": "缺少班級"})
            raw_data = body.get("data", "")          # 接受 data-URI 或純 base64
            m = re.match(r"data:([^;,]+)[^,]*,(.*)", raw_data, re.S)
            if m:
                mime, b64 = m.group(1), m.group(2)
            else:
                mime, b64 = body.get("mime", "application/pdf"), raw_data
            try:
                blob = base64.b64decode(b64)
            except Exception:
                return self._send(400, {"ok": False, "msg": "檔案解碼失敗"})
            if not blob:
                return self._send(400, {"ok": False, "msg": "空檔案"})
            uid = add_upload(klass, body.get("filename", "upload.pdf"), mime, blob)
            return self._send(200, {"ok": True, "id": uid})
        if p == "/api/upload/delete":
            delete_upload(int(body.get("id")))
            return self._send(200, {"ok": True})
        if p == "/api/sheet/delete":
            ok, msg = delete_sheet(body.get("sid", ""))
            return self._send(200 if ok else 400, {"ok": ok, "msg": msg})
        return self._send(404, {"error": "not found"})


def main():
    backup_db()          # 啟動先備份正本, 永不刪 bball.db (PG 模式自動略過)
    init_db()
    seed_if_empty()
    backend = "Postgres(雲端)" if PG else f"SQLite ({DB})"
    print("=" * 52)
    print("  籃球攻守紀錄 — 服務已啟動")
    print(f"  後端:   {backend}")
    print(f"  監聽:   http://{HOST}:{PORT}/")
    print(f"  登入:   {'已啟用 (APP_USER/APP_PASS)' if APP_PASS else '未啟用 (本地)'}")
    print("  關閉: Ctrl+C")
    print("=" * 52)
    if not PG:           # 只有本地才自動開瀏覽器
        url = f"http://localhost:{PORT}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已關閉。")
    finally:
        if _pool is not None:
            _pool.close()


if __name__ == "__main__":
    main()
