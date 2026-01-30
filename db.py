# db.py — SQLite backend for Tutor Class Attendance Register 2026

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd

# ------------------ HELPERS ------------------

def _connect(db_path: Path):
    return sqlite3.connect(str(db_path), check_same_thread=False)

def norm_barcode(x: str) -> str:
    x = str(x or "").strip()
    if not x:
        return ""
    # keep only visible chars
    return x.replace("\n","").replace("\r","").strip()

# ------------------ INIT ------------------

def init_db(db_path: Path):
    con = _connect(db_path)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS learners (
        barcode TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        surname TEXT NOT NULL,
        grade TEXT,
        area TEXT,
        dob TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        barcode TEXT NOT NULL,
        date_col TEXT NOT NULL,  -- e.g. 30-Jan
        present INTEGER NOT NULL DEFAULT 0,
        ts_iso TEXT,
        PRIMARY KEY (barcode, date_col),
        FOREIGN KEY (barcode) REFERENCES learners(barcode)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inout_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        action TEXT NOT NULL,    -- IN or OUT
        ts_iso TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send (
        date_str TEXT PRIMARY KEY,  -- yyyy-mm-dd
        sent_ts TEXT
    )
    """)

    con.commit()
    con.close()

# ------------------ AUTO SEND ------------------

def ensure_auto_send_table(db_path: Path):
    # already created in init_db, but keep for compatibility
    init_db(db_path)

def already_sent_today(db_path: Path, date_str: str) -> bool:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM auto_send WHERE date_str = ?", (date_str,))
    r = cur.fetchone()
    con.close()
    return r is not None

def mark_sent_today(db_path: Path, date_str: str, ts_iso: str):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO auto_send(date_str, sent_ts) VALUES (?,?)", (date_str, ts_iso))
    con.commit()
    con.close()

# ------------------ LEARNERS ------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    con = _connect(db_path)
    df = pd.read_sql_query("SELECT name as Name, surname as Surname, barcode as Barcode, grade as Grade, area as Area, dob as 'Date Of Birth' FROM learners ORDER BY grade, surname, name", con)
    con.close()
    return df

def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("DELETE FROM learners")
    con.commit()

    rows = []
    for _, r in df.iterrows():
        rows.append((
            norm_barcode(r.get("Barcode","")),
            str(r.get("Name","")).strip(),
            str(r.get("Surname","")).strip(),
            str(r.get("Grade","")).strip(),
            str(r.get("Area","")).strip(),
            str(r.get("Date Of Birth","")).strip()
        ))
    cur.executemany("INSERT OR REPLACE INTO learners(barcode,name,surname,grade,area,dob) VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()

def upsert_learner(db_path: Path, name: str, surname: str, barcode: str, grade: str="", area: str="", dob: str=""):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO learners(barcode,name,surname,grade,area,dob)
        VALUES (?,?,?,?,?,?)
    """, (norm_barcode(barcode), name, surname, grade, area, dob))
    con.commit()
    con.close()

def delete_learner_by_barcode(db_path: Path, barcode: str):
    b = norm_barcode(barcode)
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("DELETE FROM attendance WHERE barcode = ?", (b,))
    cur.execute("DELETE FROM inout_log WHERE barcode = ?", (b,))
    cur.execute("DELETE FROM learners WHERE barcode = ?", (b,))
    con.commit()
    con.close()

# ------------------ ATTENDANCE ------------------

def add_class_date(db_path: Path, date_col: str):
    # no schema change needed; just ensures future marks can happen
    # (kept for compatibility)
    return

def insert_present_mark(db_path: Path, barcode: str, date_col: str) -> str:
    """
    Marks present=1 for (barcode,date_col). Returns learner full name if barcode exists, else ''.
    """
    b = norm_barcode(barcode)
    con = _connect(db_path)
    cur = con.cursor()

    cur.execute("SELECT name, surname FROM learners WHERE barcode = ?", (b,))
    row = cur.fetchone()
    if not row:
        con.close()
        return ""

    name, surname = row
    ts = datetime.now().isoformat(timespec="seconds")

    cur.execute("""
        INSERT OR REPLACE INTO attendance(barcode,date_col,present,ts_iso)
        VALUES (?,?,1,?)
    """, (b, date_col, ts))

    con.commit()
    con.close()
    return f"{name} {surname}".strip()

def append_inout_log(db_path: Path, barcode: str, action: str, ts_iso: str):
    b = norm_barcode(barcode)
    action = str(action).strip().upper()
    if action not in ("IN","OUT"):
        action = "IN"
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("INSERT INTO inout_log(barcode,action,ts_iso) VALUES (?,?,?)", (b, action, ts_iso))
    con.commit()
    con.close()

def determine_next_action(db_path: Path, barcode: str) -> str:
    """
    If last action was IN -> next is OUT, else next is IN.
    """
    b = norm_barcode(barcode)
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT action FROM inout_log WHERE barcode = ? ORDER BY id DESC LIMIT 1", (b,))
    r = cur.fetchone()
    con.close()

    if not r:
        return "IN"
    return "OUT" if r[0] == "IN" else "IN"

def get_currently_in(db_path: Path) -> pd.DataFrame:
    """
    Compute currently IN: last log action == IN
    """
    con = _connect(db_path)
    # last action per barcode
    df = pd.read_sql_query("""
        SELECT l.name as Name, l.surname as Surname, l.grade as Grade, l.barcode as Barcode,
               x.action as LastAction, x.ts_iso as LastTime
        FROM learners l
        LEFT JOIN (
            SELECT barcode, action, ts_iso
            FROM inout_log
            WHERE id IN (
                SELECT MAX(id) FROM inout_log GROUP BY barcode
            )
        ) x ON x.barcode = l.barcode
        WHERE x.action = 'IN'
        ORDER BY l.grade, l.surname, l.name
    """, con)
    con.close()
    return df

# ------------------ WIDE SHEET (JOIN) ------------------

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """
    Returns a wide dataframe:
    Name, Surname, Barcode, Grade, Area, Date Of Birth, then each date_col as 1/blank
    """
    con = _connect(db_path)

    learners = pd.read_sql_query("""
        SELECT name as Name, surname as Surname, barcode as Barcode, grade as Grade, area as Area, dob as 'Date Of Birth'
        FROM learners
        ORDER BY grade, surname, name
    """, con)

    if learners.empty:
        con.close()
        return learners

    att = pd.read_sql_query("""
        SELECT barcode as Barcode, date_col as DateCol, present as Present
        FROM attendance
    """, con)

    con.close()

    if att.empty:
        return learners

    pivot = att.pivot_table(index="Barcode", columns="DateCol", values="Present", aggfunc="max").reset_index()
    pivot = pivot.fillna("")

    # Convert 1.0 -> "1", blanks keep blank
    for c in pivot.columns:
        if c == "Barcode":
            continue
        pivot[c] = pivot[c].apply(lambda x: "1" if str(x).strip() in ("1","1.0") else "")

    out = learners.merge(pivot, on="Barcode", how="left").fillna("")
    return out

# ------------------ SEED ------------------

def seed_learners_from_csv_if_empty(db_path: Path, seed_csv: str="learners.csv"):
    """
    If learners table empty and learners.csv exists, seed it.
    """
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM learners")
    n = cur.fetchone()[0]
    con.close()

    if n > 0:
        return

    p = Path(seed_csv)
    if not p.exists():
        return

    df = pd.read_csv(p).fillna("").astype(str)
    if not {"Name","Surname","Barcode"}.issubset(df.columns):
        return

    for col in ["Grade","Area","Date Of Birth"]:
        if col not in df.columns:
            df[col] = ""

    df = df[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]].copy()
    df["Barcode"] = df["Barcode"].astype(str).str.strip()
    df = df[df["Barcode"] != ""].reset_index(drop=True)

    replace_learners_from_df(db_path, df)
