# db.py — SQLite backend for Tutor Class Attendance Register 2026

import sqlite3
from pathlib import Path
import pandas as pd


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# =========================================================
# AUTO SEND TABLE (once per day)
# =========================================================

def ensure_auto_send_table(db_path: Path):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_send_log (
            send_date TEXT PRIMARY KEY,
            sent_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def already_sent_today(db_path: Path, date_str: str) -> bool:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE send_date = ?", (date_str,))
    row = cur.fetchone()
    conn.close()
    return bool(row)

def mark_sent_today(db_path: Path, date_str: str, ts_iso: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log (send_date, sent_at) VALUES (?, ?)",
        (date_str, ts_iso)
    )
    conn.commit()
    conn.close()


# =========================================================
# HELPERS
# =========================================================

def norm_barcode(code: str) -> str:
    s = str(code).strip().lstrip("0")
    return s if s else "0"


# =========================================================
# INIT DB
# =========================================================

def init_db(db_path: Path):
    conn = get_conn(db_path)
    cur = conn.cursor()

    # Learners
    cur.execute("""
        CREATE TABLE IF NOT EXISTS learners (
            barcode TEXT PRIMARY KEY,
            barcode_norm TEXT UNIQUE,
            name TEXT,
            surname TEXT,
            grade TEXT,
            area TEXT,
            dob TEXT
        )
    """)

    # Class dates
    cur.execute("""
        CREATE TABLE IF NOT EXISTS class_dates (
            date_label TEXT PRIMARY KEY
        )
    """)

    # Attendance marks (present only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_label TEXT NOT NULL,
            date_str TEXT NOT NULL,
            time_str TEXT NOT NULL,
            barcode TEXT NOT NULL,
            present INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
        )
    """)

    # IN / OUT log
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_iso TEXT NOT NULL,
            date_str TEXT NOT NULL,
            time_str TEXT NOT NULL,
            barcode TEXT NOT NULL,
            name TEXT,
            surname TEXT,
            action TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    ensure_auto_send_table(db_path)


# =========================================================
# LEARNERS
# =========================================================

def get_learners_df(db_path: Path) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT
            barcode AS Barcode,
            name AS Name,
            surname AS Surname,
            grade AS Grade,
            area AS Area,
            dob AS "Date Of Birth"
        FROM learners
        ORDER BY surname, name
    """, conn)
    conn.close()
    return df.fillna("").astype(str)

def get_learner_by_barcode(db_path: Path, barcode: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            barcode AS Barcode,
            name AS Name,
            surname AS Surname,
            grade AS Grade,
            area AS Area,
            dob AS "Date Of Birth"
        FROM learners
        WHERE barcode_norm = ?
        LIMIT 1
    """, (norm_barcode(barcode),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners")

    for _, r in df.iterrows():
        barcode = str(r.get("Barcode", "")).strip()
        if not barcode:
            continue
        cur.execute("""
            INSERT INTO learners
            (barcode, barcode_norm, name, surname, grade, area, dob)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            barcode,
            norm_barcode(barcode),
            str(r.get("Name", "")).strip(),
            str(r.get("Surname", "")).strip(),
            str(r.get("Grade", "")).strip(),
            str(r.get("Area", "")).strip(),
            str(r.get("Date Of Birth", "")).strip(),
        ))

    conn.commit()
    conn.close()

def delete_learner_by_barcode(db_path: Path, barcode: str) -> int:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM learners WHERE barcode_norm = ?",
        (norm_barcode(barcode),)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# =========================================================
# CLASS DATES
# =========================================================

def add_class_date(db_path: Path, date_label: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO class_dates (date_label) VALUES (?)",
        (date_label.strip(),)
    )
    conn.commit()
    conn.close()

def get_all_class_dates(db_path: Path) -> list[str]:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date_label FROM class_dates", conn)
    conn.close()
    return df["date_label"].astype(str).tolist()


# =========================================================
# ATTENDANCE
# =========================================================

def insert_present_mark(db_path: Path, date_label: str, date_str: str, time_str: str, barcode: str):
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO class_dates (date_label) VALUES (?)", (date_label,))

    cur.execute("""
        SELECT 1 FROM attendance_marks
        WHERE date_label = ? AND barcode = ? AND present = 1
    """, (date_label, barcode))

    if cur.fetchone() is None:
        cur.execute("""
            INSERT INTO attendance_marks
            (date_label, date_str, time_str, barcode, present)
            VALUES (?, ?, ?, ?, 1)
        """, (date_label, date_str, time_str, barcode))

    conn.commit()
    conn.close()


# =========================================================
# IN / OUT LOG
# =========================================================

def append_inout_log(db_path: Path, ts_iso: str, date_str: str, time_str: str,
                     barcode: str, name: str, surname: str, action: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inout_log
        (ts_iso, date_str, time_str, barcode, name, surname, action)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ts_iso, date_str, time_str, barcode, name, surname, action))
    conn.commit()
    conn.close()

def determine_next_action(db_path: Path, barcode: str, date_str: str) -> str:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT action FROM inout_log
        WHERE barcode = ? AND date_str = ?
        ORDER BY ts_iso DESC
        LIMIT 1
    """, (barcode, date_str))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return "IN"
    return "OUT" if row["action"].upper() == "IN" else "IN"

def get_currently_in(db_path: Path, date_str: str) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT Barcode, Name, Surname FROM (
            SELECT
                barcode AS Barcode,
                name AS Name,
                surname AS Surname,
                action,
                ROW_NUMBER() OVER (
                    PARTITION BY barcode
                    ORDER BY ts_iso DESC
                ) AS rn
            FROM inout_log
            WHERE date_str = ?
        )
        WHERE rn = 1 AND UPPER(action) = 'IN'
        ORDER BY Surname, Name
    """, conn, params=(date_str,))
    conn.close()
    return df.fillna("").astype(str)


# =========================================================
# WIDE SHEET (for UI)
# =========================================================

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    learners = get_learners_df(db_path)

    conn = get_conn(db_path)
    marks = pd.read_sql("""
        SELECT date_label, barcode, present
        FROM attendance_marks
        WHERE present = 1
    """, conn)
    conn.close()

    if marks.empty:
        return learners

    marks["val"] = "1"
    pivot = marks.pivot_table(
        index="barcode",
        columns="date_label",
        values="val",
        aggfunc="last",
        fill_value=""
    ).reset_index().rename(columns={"barcode": "Barcode"})

    wide = learners.merge(pivot, on="Barcode", how="left")
    return wide.fillna("").astype(str)


# =========================================================
# SEED (OPTIONAL)
# =========================================================

def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str = "attendance_clean.csv") -> int:
    try:
        if len(get_learners_df(db_path)) > 0:
            return 0
    except Exception:
        return 0

    p = Path(csv_path)
    if not p.exists():
        return 0

    df = pd.read_csv(p, dtype=str).fillna("")
    required = ["Barcode", "Name", "Surname"]
    if not all(c in df.columns for c in required):
        return 0

    replace_learners_from_df(db_path, df)
    return len(df)
