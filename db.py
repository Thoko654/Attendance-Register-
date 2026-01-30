# db.py — SQLite backend for Tutor Class Attendance Register

import sqlite3
from pathlib import Path
import pandas as pd
from typing import List, Optional, Dict


# ================== HELPERS ==================

def norm_barcode(code: str) -> str:
    s = str(code).strip()
    s = s.lstrip("0")
    return s if s != "" else "0"


def get_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]  # col name is index 1


# ================== WHATSAPP TABLES + MIGRATION ==================

def ensure_whatsapp_tables(db_path: Path):
    """
    Creates tables required for WhatsApp:
    1) whatsapp_recipients: stores who should receive messages
    2) auto_send_log: stores per-recipient-per-day send log using a unique key
       key format: YYYY-MM-DD|+2783....
    Also migrates older auto_send_log schema if found.
    """
    db_path = Path(db_path)
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # --- recipients table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_recipients (
            phone TEXT PRIMARY KEY,     -- E.164 format e.g. +2783...
            label TEXT,                 -- optional: "Thoko", "Cathy"
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # --- auto_send_log table (new schema) ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_send_log (
            key TEXT PRIMARY KEY,       -- e.g. "2026-01-29|+27836280453"
            sent_at TEXT
        )
    """)

    # --- Migration: if old schema exists, try to migrate ---
    try:
        cols = _table_columns(con, "auto_send_log")
        if "send_date" in cols and "key" not in cols:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auto_send_log_v2 (
                    key TEXT PRIMARY KEY,
                    sent_at TEXT
                )
            """)
            cur.execute("""
                INSERT OR IGNORE INTO auto_send_log_v2(key, sent_at)
                SELECT send_date || '|ALL', sent_at
                FROM auto_send_log
            """)
            cur.execute("DROP TABLE auto_send_log")
            cur.execute("ALTER TABLE auto_send_log_v2 RENAME TO auto_send_log")
    except Exception:
        pass

    con.commit()
    con.close()


def add_whatsapp_recipient(db_path: Path, phone: str, label: str = "", active: int = 1):
    phone = str(phone).strip()
    if not phone:
        return
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("""
        INSERT INTO whatsapp_recipients(phone, label, active)
        VALUES (?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            label=excluded.label,
            active=excluded.active
    """, (phone, label.strip(), int(active)))
    con.commit()
    con.close()


def remove_whatsapp_recipient(db_path: Path, phone: str) -> int:
    phone = str(phone).strip()
    if not phone:
        return 0
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("DELETE FROM whatsapp_recipients WHERE phone = ?", (phone,))
    deleted = cur.rowcount
    con.commit()
    con.close()
    return deleted


def set_whatsapp_recipient_active(db_path: Path, phone: str, active: int) -> int:
    phone = str(phone).strip()
    if not phone:
        return 0
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("UPDATE whatsapp_recipients SET active=? WHERE phone=?", (int(active), phone))
    updated = cur.rowcount
    con.commit()
    con.close()
    return updated


def get_whatsapp_recipients(db_path: Path, only_active: bool = True) -> List[str]:
    con = sqlite3.connect(str(db_path))
    if only_active:
        df = pd.read_sql("SELECT phone FROM whatsapp_recipients WHERE active=1 ORDER BY phone", con)
    else:
        df = pd.read_sql("SELECT phone FROM whatsapp_recipients ORDER BY phone", con)
    con.close()
    return [str(x).strip() for x in df["phone"].tolist() if str(x).strip()]


def _send_key(date_str: str, phone: str) -> str:
    return f"{date_str}|{phone}"


def already_sent_today_for_recipient(db_path: Path, date_str: str, phone: str) -> bool:
    key = _send_key(date_str, str(phone).strip())
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE key = ?", (key,))
    row = cur.fetchone()
    con.close()
    return bool(row)


def mark_sent_today_for_recipient(db_path: Path, date_str: str, phone: str, ts_iso: str):
    key = _send_key(date_str, str(phone).strip())
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log(key, sent_at) VALUES (?, ?)",
        (key, ts_iso)
    )
    con.commit()
    con.close()


# ================== DB INIT + MIGRATIONS ==================

def init_db(db_path: Path):
    db_path = Path(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()

    # learners = your main registry
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

    # dates = optional list of class dates
    cur.execute("""
    CREATE TABLE IF NOT EXISTS class_dates (
        date_label TEXT PRIMARY KEY
    )
    """)

    # attendance marks (Present/Absent). We store only present marks.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_label TEXT NOT NULL,   -- e.g. 22-Jan
        date_str   TEXT NOT NULL,   -- e.g. 2026-01-22
        time_str   TEXT NOT NULL,   -- e.g. 09:30:10
        barcode    TEXT NOT NULL,
        present    INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
    )
    """)

    # prevent duplicate present mark per learner+date_label
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_unique
        ON attendance_marks(date_label, barcode, present)
    """)

    # IN/OUT log
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

    # Helpful indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inout_date_barcode ON inout_log(date_str, barcode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inout_ts ON inout_log(ts_iso)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_marks_date ON attendance_marks(date_str)")

    conn.commit()
    conn.close()

    # Ensure WhatsApp tables exist too
    ensure_whatsapp_tables(db_path)


# ================== SEED / IMPORT FROM CSV ==================

def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str = "attendance_clean.csv") -> int:
    """
    If learners table is empty, import learners from a CSV file.
    Returns number of imported rows.
    Safe: will NOT overwrite learners if DB already has learners.
    """
    try:
        existing = get_learners_df(db_path)
        if existing is not None and len(existing) > 0:
            return 0
    except Exception:
        return 0

    p = Path(csv_path)
    if not p.exists():
        return 0

    df = pd.read_csv(p, dtype=str).fillna("")

    needed = ["Barcode", "Name", "Surname", "Grade", "Area", "Date Of Birth"]
    for c in needed:
        if c not in df.columns:
            df[c] = ""

    learners_df = df[needed].copy()

    learners_df["Barcode"] = learners_df["Barcode"].astype(str).str.strip()
    learners_df = learners_df[learners_df["Barcode"] != ""]
    learners_df = learners_df.drop_duplicates(subset=["Barcode"]).reset_index(drop=True)

    replace_learners_from_df(db_path, learners_df)
    return len(learners_df)


# ================== LEARNERS CRUD ==================

def upsert_learner(db_path: Path, row: dict):
    conn = get_conn(db_path)
    cur = conn.cursor()

    barcode = str(row.get("Barcode", "")).strip()
    if not barcode:
        conn.close()
        return

    bnorm = norm_barcode(barcode)

    cur.execute("""
    INSERT INTO learners (barcode, barcode_norm, name, surname, grade, area, dob)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(barcode) DO UPDATE SET
        barcode_norm=excluded.barcode_norm,
        name=excluded.name,
        surname=excluded.surname,
        grade=excluded.grade,
        area=excluded.area,
        dob=excluded.dob
    """, (
        barcode,
        bnorm,
        str(row.get("Name", "")).strip(),
        str(row.get("Surname", "")).strip(),
        str(row.get("Grade", "")).strip(),
        str(row.get("Area", "")).strip(),
        str(row.get("Date Of Birth", "")).strip(),
    ))

    conn.commit()
    conn.close()


def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute("DELETE FROM learners")

    for _, r in df.iterrows():
        barcode = str(r.get("Barcode", "")).strip()
        if not barcode:
            continue

        cur.execute("""
        INSERT INTO learners (barcode, barcode_norm, name, surname, grade, area, dob)
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
    barcode = str(barcode).strip()
    if not barcode:
        return 0

    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners WHERE barcode_norm = ?", (norm_barcode(barcode),))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_learner_by_barcode(db_path: Path, barcode: str) -> Optional[Dict[str, str]]:
    """
    Returns learner dict by matching barcode_norm so scans like 0001 == 1.
    """
    bn = norm_barcode(barcode)
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT barcode AS Barcode, name AS Name, surname AS Surname,
               grade AS Grade, area AS Area, dob AS "Date Of Birth"
        FROM learners
        WHERE barcode_norm = ?
        LIMIT 1
    """, (bn,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ================== DATES ==================

def add_class_date(db_path: Path, date_label: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO class_dates(date_label) VALUES (?)", (date_label.strip(),))
    conn.commit()
    conn.close()


def get_all_class_dates(db_path: Path) -> list[str]:
    conn = get_conn(db_path)
    df = pd.read_sql("SELECT date_label FROM class_dates", conn)
    conn.close()
    return [str(x).strip() for x in df["date_label"].tolist() if str(x).strip()]


# ================== DATAFRAMES ==================

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


def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    learners = get_learners_df(db_path)

    conn = get_conn(db_path)
    marks = pd.read_sql("""
        SELECT date_label, barcode, present
        FROM attendance_marks
        WHERE present = 1
    """, conn)
    conn.close()

    all_dates = set(get_all_class_dates(db_path))
    if not marks.empty:
        all_dates |= set(marks["date_label"].astype(str).tolist())

    if marks.empty:
        wide = learners.copy()
    else:
        marks = marks.copy()
        marks["val"] = "1"
        pv = marks.pivot_table(
            index="barcode",
            columns="date_label",
            values="val",
            aggfunc="last",
            fill_value=""
        )
        pv.reset_index(inplace=True)
        pv.rename(columns={"barcode": "Barcode"}, inplace=True)
        wide = learners.merge(pv, on="Barcode", how="left")

    for d in sorted(all_dates, key=str):
        if d not in wide.columns:
            wide[d] = ""

    return wide.fillna("").astype(str)


def get_present_today_df(db_path: Path, date_str: str) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT DISTINCT
            l.barcode AS Barcode,
            l.name AS Name,
            l.surname AS Surname,
            l.grade AS Grade
        FROM attendance_marks m
        JOIN learners l ON l.barcode = m.barcode
        WHERE m.date_str = ? AND m.present = 1
        ORDER BY l.surname, l.name
    """, conn, params=(date_str,))
    conn.close()
    return df.fillna("").astype(str)


def get_grade_summary_for_month(db_path: Path, month_prefix: str) -> pd.DataFrame:
    """
    month_prefix example: "2026-01" (YYYY-MM)
    Attendance percent = present_count / expected_sessions_in_month
    expected_sessions_in_month = number of unique date_str in that month found in attendance_marks or class_dates labels not stored as date_str
    We will use attendance_marks distinct date_str count for that month as "sessions so far".
    """
    conn = get_conn(db_path)
    # sessions recorded this month
    sessions_df = pd.read_sql("""
        SELECT COUNT(DISTINCT date_str) AS sessions
        FROM attendance_marks
        WHERE date_str LIKE ?
    """, conn, params=(month_prefix + "%",))
    sessions = int(sessions_df.iloc[0]["sessions"]) if not sessions_df.empty else 0
    sessions = max(sessions, 1)  # avoid division by zero

    df = pd.read_sql("""
        SELECT
            l.grade AS Grade,
            COUNT(DISTINCT l.barcode) AS Learners,
            COUNT(DISTINCT m.barcode || '|' || m.date_str) AS PresentMarks
        FROM learners l
        LEFT JOIN attendance_marks m
          ON m.barcode = l.barcode
         AND m.present = 1
         AND m.date_str LIKE ?
        GROUP BY l.grade
        ORDER BY l.grade
    """, conn, params=(month_prefix + "%",))
    conn.close()

    if df.empty:
        return pd.DataFrame(columns=["Grade", "Learners", "PresentMarks", "Sessions", "AvgAttendance%"])

    df["Sessions"] = sessions
    # average attendance per learner across sessions (rough)
    df["AvgAttendance%"] = ((df["PresentMarks"] / (df["Learners"].replace(0, 1) * sessions)) * 100).round(1)
    return df.fillna("").astype(str)


# ================== ATTENDANCE + LOGS ==================

def insert_present_mark(db_path: Path, date_label: str, date_str: str, time_str: str, barcode: str):
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO class_dates(date_label) VALUES (?)", (date_label,))

    # unique index prevents duplicates
    try:
        cur.execute("""
            INSERT INTO attendance_marks (date_label, date_str, time_str, barcode, present)
            VALUES (?, ?, ?, ?, 1)
        """, (date_label, date_str, time_str, barcode))
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()


def append_inout_log(db_path: Path, ts_iso: str, date_str: str, time_str: str, barcode: str, name: str, surname: str, action: str):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inout_log (ts_iso, date_str, time_str, barcode, name, surname, action)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ts_iso, date_str, time_str, barcode, name, surname, action))
    conn.commit()
    conn.close()


def get_inout_log(db_path: Path) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT ts_iso AS Timestamp, date_str AS Date, time_str AS Time,
               barcode AS Barcode, name AS Name, surname AS Surname, action AS Action
        FROM inout_log
        ORDER BY ts_iso
    """, conn)
    conn.close()
    return df.fillna("").astype(str)


def get_inout_log_for_date(db_path: Path, date_str: str) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT ts_iso AS Timestamp, time_str AS Time,
               barcode AS Barcode, name AS Name, surname AS Surname, action AS Action
        FROM inout_log
        WHERE date_str = ?
        ORDER BY ts_iso
    """, conn, params=(date_str,))
    conn.close()
    return df.fillna("").astype(str)


def determine_next_action(db_path: Path, barcode: str, date_str: str) -> str:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT action FROM inout_log
        WHERE date_str=? AND barcode=?
        ORDER BY ts_iso DESC
        LIMIT 1
    """, (date_str, barcode))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return "IN"

    last_action = str(row["action"]).upper()
    return "OUT" if last_action == "IN" else "IN"


def get_currently_in(db_path: Path, date_str: str) -> pd.DataFrame:
    conn = get_conn(db_path)
    df = pd.read_sql("""
        SELECT Barcode, Name, Surname
        FROM (
            SELECT barcode AS Barcode, name AS Name, surname AS Surname,
                   action AS Action,
                   ROW_NUMBER() OVER (PARTITION BY barcode ORDER BY ts_iso DESC) AS rn
            FROM inout_log
            WHERE date_str=?
        ) t
        WHERE rn=1 AND UPPER(Action)='IN'
        ORDER BY Surname, Name
    """, conn, params=(date_str,))
    conn.close()
    return df.fillna("").astype(str)
