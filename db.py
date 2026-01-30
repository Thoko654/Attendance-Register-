# db.py — Tutor Class Attendance Register 2026 (SQLite backend)

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd


# ---------------------------- helpers ----------------------------

def _connect(db_path: Path):
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")

def norm_barcode(code: str) -> str:
    if code is None:
        return ""
    code = str(code).strip()
    # remove common scanner suffixes/newlines
    code = code.replace("\n", "").replace("\r", "").strip()
    return code


# ---------------------------- schema ----------------------------

def init_db(db_path: Path):
    """Create tables if missing and migrate older learner schemas safely."""
    conn = _connect(db_path)
    cur = conn.cursor()

    # learners
    cur.execute("""
        CREATE TABLE IF NOT EXISTS learners (
            barcode TEXT PRIMARY KEY,
            name    TEXT,
            surname TEXT,
            grade   TEXT,
            area    TEXT,
            dob     TEXT
        );
    """)

    # class_dates: stores date_col like "30-Jan"
    cur.execute("""
        CREATE TABLE IF NOT EXISTS class_dates (
            date_col TEXT PRIMARY KEY,
            date_iso TEXT,
            created_ts TEXT
        );
    """)

    # attendance: one row per barcode per date_col
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT,
            date_col TEXT,
            date_iso TEXT,
            present INTEGER DEFAULT 1,
            ts TEXT,
            UNIQUE(barcode, date_col),
            FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
        );
    """)

    # inout log: optional, for IN/OUT tracking
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT,
            action TEXT,
            ts TEXT
        );
    """)

    conn.commit()

    # ---- migration: if learners table existed with different column names
    # We will detect columns and try to map them.
    cols = [r[1] for r in cur.execute("PRAGMA table_info(learners);").fetchall()]
    # If an older DB had "Surname" instead of "surname", etc. (rare but possible)
    # SQLite is case-insensitive for column names in many contexts, but not always safe.
    # We'll ensure required columns exist.
    required = ["barcode", "name", "surname", "grade", "area", "dob"]
    for c in required:
        if c not in cols:
            try:
                cur.execute(f"ALTER TABLE learners ADD COLUMN {c} TEXT;")
            except Exception:
                pass

    conn.commit()
    conn.close()


# ---------------------------- auto-send log ----------------------------

def ensure_auto_send_table(db_path: Path):
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_send_log (
            date_iso TEXT PRIMARY KEY,
            sent_ts  TEXT
        );
    """)
    conn.commit()
    conn.close()

def already_sent_today(db_path: Path, date_iso: str) -> bool:
    ensure_auto_send_table(db_path)
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE date_iso=? LIMIT 1;", (date_iso,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok

def mark_sent_today(db_path: Path, date_iso: str, sent_ts: str):
    ensure_auto_send_table(db_path)
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log(date_iso, sent_ts) VALUES(?, ?);",
        (date_iso, sent_ts),
    )
    conn.commit()
    conn.close()


# ---------------------------- learners ----------------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    conn = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            barcode AS Barcode,
            name    AS Name,
            surname AS Surname,
            grade   AS Grade,
            area    AS Area,
            dob     AS "Date Of Birth"
        FROM learners
        ORDER BY surname, name;
        """,
        conn
    )
    conn.close()
    return df

def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    """Replace entire learner list from a dataframe with required columns."""
    if df is None or df.empty:
        return
    df = df.copy()

    # normalize
    for col in ["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]:
        if col not in df.columns:
            df[col] = ""

    df["Barcode"] = df["Barcode"].astype(str).map(norm_barcode)
    df = df[df["Barcode"] != ""].drop_duplicates(subset=["Barcode"])

    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners;")
    conn.commit()

    rows = []
    for _, r in df.iterrows():
        rows.append((
            str(r.get("Barcode", "")).strip(),
            str(r.get("Name", "")).strip(),
            str(r.get("Surname", "")).strip(),
            str(r.get("Grade", "")).strip(),
            str(r.get("Area", "")).strip(),
            str(r.get("Date Of Birth", "")).strip(),
        ))

    cur.executemany(
        "INSERT OR REPLACE INTO learners(barcode,name,surname,grade,area,dob) VALUES(?,?,?,?,?,?);",
        rows
    )
    conn.commit()
    conn.close()

def delete_learner_by_barcode(db_path: Path, barcode: str):
    barcode = norm_barcode(barcode)
    if not barcode:
        return
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners WHERE barcode=?;", (barcode,))
    conn.commit()
    conn.close()

def seed_learners_from_csv_if_empty(db_path: Path, seed_csv: str = "learners.csv"):
    """
    Optional seed: if learners table is empty and learners.csv exists, load it.
    Expected columns: Name, Surname, Barcode, Grade, Area, Date Of Birth
    """
    try:
        conn = _connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM learners;")
        n = int(cur.fetchone()[0])
        conn.close()
        if n > 0:
            return

        p = Path(seed_csv)
        if not p.exists():
            return

        df = pd.read_csv(p).fillna("")
        replace_learners_from_df(db_path, df)
    except Exception:
        return


# ---------------------------- class dates + attendance ----------------------------

def add_class_date(db_path: Path, date_col: str, date_iso: str):
    date_col = str(date_col).strip()
    date_iso = str(date_iso).strip()
    if not date_col:
        return
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO class_dates(date_col, date_iso, created_ts) VALUES(?,?,?);",
        (date_col, date_iso, _now_iso())
    )
    conn.commit()
    conn.close()

def insert_present_mark(db_path: Path, barcode: str, date_col: str, date_iso: str, ts: str = None):
    barcode = norm_barcode(barcode)
    if not barcode or not date_col:
        return False, "Empty barcode/date"
    ts = ts or _now_iso()

    # Ensure learner exists
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM learners WHERE barcode=? LIMIT 1;", (barcode,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Barcode not found in learners."

    add_class_date(db_path, date_col, date_iso)

    cur.execute(
        """
        INSERT OR REPLACE INTO attendance(barcode, date_col, date_iso, present, ts)
        VALUES(?,?,?,?,?);
        """,
        (barcode, date_col, date_iso, 1, ts)
    )
    conn.commit()
    conn.close()
    return True, "Marked present."

def append_inout_log(db_path: Path, barcode: str, action: str, ts: str = None):
    barcode = norm_barcode(barcode)
    action = str(action).strip().upper()
    if action not in ("IN", "OUT"):
        return
    ts = ts or _now_iso()
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO inout_log(barcode, action, ts) VALUES(?,?,?);",
        (barcode, action, ts)
    )
    conn.commit()
    conn.close()

def get_currently_in(db_path: Path):
    """
    Returns a set of barcodes that are currently IN (last action is IN).
    """
    conn = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT barcode, action, MAX(ts) as max_ts
        FROM inout_log
        GROUP BY barcode;
        """,
        conn
    )
    conn.close()
    if df.empty:
        return set()
    df["action"] = df["action"].astype(str).str.upper()
    return set(df[df["action"] == "IN"]["barcode"].astype(str).tolist())

def determine_next_action(db_path: Path, barcode: str) -> str:
    barcode = norm_barcode(barcode)
    if not barcode:
        return "IN"
    currently_in = get_currently_in(db_path)
    return "OUT" if barcode in currently_in else "IN"


# ---------------------------- wide sheet (for UI) ----------------------------

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """
    Return a wide attendance sheet:
    columns: Name, Surname, Barcode, Grade, Area, Date Of Birth, then date columns like '30-Jan'
    value '1' = present
    """
    learners = get_learners_df(db_path).fillna("")
    if learners.empty:
        return learners

    conn = _connect(db_path)
    marks = pd.read_sql_query(
        "SELECT barcode, date_col, present FROM attendance;",
        conn
    )
    conn.close()

    if marks.empty:
        return learners

    marks["present"] = marks["present"].apply(lambda x: "1" if int(x) == 1 else "")
    pivot = marks.pivot_table(index="barcode", columns="date_col", values="present", aggfunc="max").fillna("")

    pivot.reset_index(inplace=True)
    pivot.rename(columns={"barcode": "Barcode"}, inplace=True)

    out = learners.merge(pivot, on="Barcode", how="left").fillna("")
    return out
