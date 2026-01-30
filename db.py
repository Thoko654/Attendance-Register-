# db.py — Tutor Class Attendance Register 2026 (SQLite)
# Provides DB functions used by app.py

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd


# ------------------ HELPERS ------------------

def norm_barcode(x: str) -> str:
    """Normalize barcode: strip, remove spaces, keep as string."""
    if x is None:
        return ""
    return str(x).strip().replace(" ", "")


def _connect(db_path: Path):
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------ INIT / TABLES ------------------

def init_db(db_path: Path):
    db_path = Path(db_path)
    conn = _connect(db_path)
    cur = conn.cursor()

    # Learners master list
    cur.execute("""
    CREATE TABLE IF NOT EXISTS learners (
        barcode TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        surname TEXT NOT NULL DEFAULT '',
        grade TEXT NOT NULL DEFAULT '',
        area TEXT NOT NULL DEFAULT '',
        dob TEXT NOT NULL DEFAULT ''
    );
    """)

    # Class dates (sessions)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS class_dates (
        date_iso TEXT PRIMARY KEY,     -- YYYY-MM-DD
        label TEXT NOT NULL DEFAULT '' -- e.g. 30-Jan
    );
    """)

    # Attendance marks (present=1)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_iso TEXT NOT NULL,
        barcode TEXT NOT NULL,
        present INTEGER NOT NULL DEFAULT 1,
        ts_iso TEXT NOT NULL DEFAULT '',
        UNIQUE(date_iso, barcode),
        FOREIGN KEY(date_iso) REFERENCES class_dates(date_iso) ON DELETE CASCADE,
        FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
    );
    """)

    # In/Out log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inout_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_iso TEXT NOT NULL,
        barcode TEXT NOT NULL,
        action TEXT NOT NULL,          -- 'IN' or 'OUT'
        ts_iso TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
    );
    """)

    # Auto-send log (WhatsApp birthday)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        date_iso TEXT PRIMARY KEY,
        sent_ts_iso TEXT NOT NULL DEFAULT ''
    );
    """)

    conn.commit()
    conn.close()


def ensure_auto_send_table(db_path: Path):
    # already created in init_db, but keep to match imports
    init_db(db_path)


# ------------------ AUTO SEND LOG ------------------

def already_sent_today(db_path: Path, date_iso: str) -> bool:
    conn = _connect(db_path)
    df = pd.read_sql_query(
        "SELECT date_iso FROM auto_send_log WHERE date_iso = ?",
        conn,
        params=(date_iso,)
    )
    conn.close()
    return len(df) > 0


def mark_sent_today(db_path: Path, date_iso: str, ts_iso: str):
    conn = _connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO auto_send_log(date_iso, sent_ts_iso) VALUES (?, ?)",
        (date_iso, ts_iso)
    )
    conn.commit()
    conn.close()


# ------------------ LEARNERS CRUD ------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    conn = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
          name AS "Name",
          surname AS "Surname",
          barcode AS "Barcode",
          grade AS "Grade",
          area AS "Area",
          dob AS "Date Of Birth"
        FROM learners
        ORDER BY grade, name, surname
        """,
        conn
    )
    conn.close()
    return df


def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    """Replace the learners table using dataframe columns:
       Name, Surname, Barcode, Grade, Area, Date Of Birth
    """
    df = df.copy()
    df["Barcode"] = df["Barcode"].astype(str).map(norm_barcode)
    df = df[df["Barcode"] != ""].reset_index(drop=True)

    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners;")

    rows = []
    for _, r in df.iterrows():
        rows.append((
            norm_barcode(r.get("Barcode", "")),
            str(r.get("Name", "")),
            str(r.get("Surname", "")),
            str(r.get("Grade", "")),
            str(r.get("Area", "")),
            str(r.get("Date Of Birth", "")),
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO learners(barcode, name, surname, grade, area, dob)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()


def delete_learner_by_barcode(db_path: Path, barcode: str):
    barcode = norm_barcode(barcode)
    if not barcode:
        return
    conn = _connect(db_path)
    conn.execute("DELETE FROM learners WHERE barcode = ?", (barcode,))
    conn.commit()
    conn.close()


# ------------------ CLASS DATES ------------------

def add_class_date(db_path: Path, date_iso: str, label: str):
    conn = _connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO class_dates(date_iso, label) VALUES (?, ?)",
        (date_iso, label)
    )
    conn.commit()
    conn.close()


# ------------------ ATTENDANCE ------------------

def insert_present_mark(db_path: Path, date_iso: str, barcode: str, present: int = 1, ts_iso: str = ""):
    barcode = norm_barcode(barcode)
    if not barcode:
        return
    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO attendance_marks(date_iso, barcode, present, ts_iso)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date_iso, barcode)
        DO UPDATE SET present=excluded.present, ts_iso=excluded.ts_iso
    """, (date_iso, barcode, int(present), ts_iso))
    conn.commit()
    conn.close()


def set_present_bulk(db_path: Path, date_iso: str, barcode_list: list[str], present: int, ts_iso: str = ""):
    conn = _connect(db_path)
    cur = conn.cursor()
    for b in barcode_list:
        b = norm_barcode(b)
        if not b:
            continue
        cur.execute("""
            INSERT INTO attendance_marks(date_iso, barcode, present, ts_iso)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date_iso, barcode)
            DO UPDATE SET present=excluded.present, ts_iso=excluded.ts_iso
        """, (date_iso, b, int(present), ts_iso))
    conn.commit()
    conn.close()


# ------------------ IN/OUT ------------------

def append_inout_log(db_path: Path, date_iso: str, barcode: str, action: str, ts_iso: str = ""):
    barcode = norm_barcode(barcode)
    if not barcode:
        return
    action = str(action).upper().strip()
    if action not in ("IN", "OUT"):
        return
    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO inout_log(date_iso, barcode, action, ts_iso)
        VALUES (?, ?, ?, ?)
    """, (date_iso, barcode, action, ts_iso))
    conn.commit()
    conn.close()


def get_last_inout_action(db_path: Path, date_iso: str, barcode: str) -> str:
    barcode = norm_barcode(barcode)
    if not barcode:
        return ""
    conn = _connect(db_path)
    df = pd.read_sql_query("""
        SELECT action
        FROM inout_log
        WHERE date_iso = ? AND barcode = ?
        ORDER BY id DESC
        LIMIT 1
    """, conn, params=(date_iso, barcode))
    conn.close()
    if df.empty:
        return ""
    return str(df.iloc[0]["action"])


def determine_next_action(db_path: Path, date_iso: str, barcode: str) -> str:
    """If last action today was IN -> next should be OUT, else IN."""
    last = get_last_inout_action(db_path, date_iso, barcode)
    if last == "IN":
        return "OUT"
    return "IN"


def get_currently_in(db_path: Path, date_iso: str) -> pd.DataFrame:
    """
    Return learners whose last action today is IN (not OUT).
    This function is the one that was crashing in your logs — now safe.
    """
    conn = _connect(db_path)

    # last action per barcode for today
    df = pd.read_sql_query("""
        WITH last_actions AS (
            SELECT l.barcode,
                   MAX(io.id) AS last_id
            FROM learners l
            LEFT JOIN inout_log io
              ON io.barcode = l.barcode AND io.date_iso = ?
            GROUP BY l.barcode
        )
        SELECT
          le.name AS "Name",
          le.surname AS "Surname",
          le.grade AS "Grade",
          le.area AS "Area",
          le.barcode AS "Barcode",
          io.action AS "Action",
          io.ts_iso AS "Time"
        FROM last_actions la
        JOIN learners le ON le.barcode = la.barcode
        LEFT JOIN inout_log io ON io.id = la.last_id
        WHERE io.action = 'IN'
        ORDER BY le.grade, le.name, le.surname
    """, conn, params=(date_iso,))

    conn.close()
    return df


# ------------------ WIDE SHEET (Pivot) ------------------

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """
    Returns a dataframe like:
    Name | Surname | Barcode | Grade | Area | Date Of Birth | 30-Jan | 06-Feb | ...
    Value: "1" if present else ""
    """
    conn = _connect(db_path)

    learners = pd.read_sql_query("""
        SELECT
          name AS "Name",
          surname AS "Surname",
          barcode AS "Barcode",
          grade AS "Grade",
          area AS "Area",
          dob AS "Date Of Birth"
        FROM learners
    """, conn)

    dates = pd.read_sql_query("""
        SELECT date_iso, label
        FROM class_dates
        ORDER BY date_iso
    """, conn)

    marks = pd.read_sql_query("""
        SELECT
          am.date_iso,
          cd.label,
          am.barcode,
          am.present
        FROM attendance_marks am
        JOIN class_dates cd ON cd.date_iso = am.date_iso
    """, conn)

    conn.close()

    if learners.empty:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Grade","Area","Date Of Birth"])

    # Build pivot
    if marks.empty or dates.empty:
        return learners.sort_values(["Grade","Name","Surname"]).reset_index(drop=True)

    marks["present"] = marks["present"].apply(lambda x: "1" if int(x) == 1 else "")
    pivot = marks.pivot_table(
        index="barcode",
        columns="label",
        values="present",
        aggfunc="max",
        fill_value=""
    ).reset_index().rename(columns={"barcode":"Barcode"})

    out = learners.merge(pivot, on="Barcode", how="left")

    # Ensure all date columns exist even if no marks yet
    for _, r in dates.iterrows():
        lbl = r["label"]
        if lbl not in out.columns:
            out[lbl] = ""

    fixed_cols = ["Name","Surname","Barcode","Grade","Area","Date Of Birth"]
    date_cols = [c for c in out.columns if c not in fixed_cols]
    out = out[fixed_cols + date_cols]

    return out.sort_values(["Grade","Name","Surname"]).reset_index(drop=True)


# ------------------ SEEDING ------------------

def seed_learners_from_csv_if_empty(db_path: Path, seed_csv: str = "learners.csv"):
    """
    Optional: if learners table empty AND learners.csv exists, import it.
    CSV should have columns: Name,Surname,Barcode,Grade,Area,Date Of Birth
    """
    db_path = Path(db_path)
    if not Path(seed_csv).exists():
        return

    current = get_learners_df(db_path)
    if len(current) > 0:
        return

    df = pd.read_csv(seed_csv).fillna("").astype(str)
    needed = ["Name","Surname","Barcode"]
    if not all(c in df.columns for c in needed):
        return

    for c in ["Grade","Area","Date Of Birth"]:
        if c not in df.columns:
            df[c] = ""

    df = df[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]]
    replace_learners_from_df(db_path, df)
