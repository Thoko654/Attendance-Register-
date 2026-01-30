# db.py — Tutor Class Attendance Register 2026 (SQLite)
# Includes: init + auto-migration, learners, attendance, in/out log, wide sheet, auto-send log

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd


# ------------------ CONNECTION ------------------

def _connect(db_path: Path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------ NORMALIZE ------------------

def norm_barcode(x: str) -> str:
    return str(x or "").strip()


# ------------------ INIT + MIGRATION ------------------

def init_db(db_path: Path):
    """
    Creates required tables and auto-migrates older schemas:
    - attendance.label -> attendance.date_label
    - attendance.date  -> attendance.date_iso
    - auto_send_log.label -> auto_send_log.date_iso
    """
    conn = _connect(db_path)
    cur = conn.cursor()

    # learners
    cur.execute("""
    CREATE TABLE IF NOT EXISTS learners (
        barcode TEXT PRIMARY KEY,
        name TEXT,
        surname TEXT,
        grade TEXT,
        area TEXT,
        dob TEXT
    )
    """)

    # attendance
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        date_label TEXT NOT NULL,
        date_iso TEXT NOT NULL,
        present INTEGER NOT NULL DEFAULT 0,
        ts_iso TEXT,
        UNIQUE(barcode, date_label),
        FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
    )
    """)

    # in/out
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inout_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        action TEXT NOT NULL,            -- 'IN' or 'OUT'
        ts_iso TEXT NOT NULL,
        date_iso TEXT NOT NULL,
        time_str TEXT NOT NULL
    )
    """)

    # auto send log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        date_iso TEXT PRIMARY KEY,
        ts_iso TEXT NOT NULL
    )
    """)

    conn.commit()

    # ---------- MIGRATIONS ----------
    def _cols(table: str):
        return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]

    # attendance.label -> date_label
    cols_att = _cols("attendance")
    if "label" in cols_att and "date_label" not in cols_att:
        try:
            cur.execute("ALTER TABLE attendance RENAME COLUMN label TO date_label")
            conn.commit()
        except Exception:
            pass

    # attendance.date -> date_iso
    cols_att = _cols("attendance")
    if "date" in cols_att and "date_iso" not in cols_att:
        try:
            cur.execute("ALTER TABLE attendance RENAME COLUMN date TO date_iso")
            conn.commit()
        except Exception:
            pass

    # auto_send_log.label -> date_iso
    cols_send = _cols("auto_send_log")
    if "label" in cols_send and "date_iso" not in cols_send:
        try:
            cur.execute("ALTER TABLE auto_send_log RENAME COLUMN label TO date_iso")
            conn.commit()
        except Exception:
            pass

    conn.close()


def ensure_auto_send_table(db_path: Path):
    # kept for compatibility (init_db already creates it)
    conn = _connect(db_path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        date_iso TEXT PRIMARY KEY,
        ts_iso TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()


# ------------------ AUTO SEND LOG ------------------

def already_sent_today(db_path: Path, date_iso: str) -> bool:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE date_iso = ? LIMIT 1", (date_iso,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_sent_today(db_path: Path, date_iso: str, ts_iso: str):
    conn = _connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO auto_send_log(date_iso, ts_iso) VALUES (?, ?)",
        (date_iso, ts_iso),
    )
    conn.commit()
    conn.close()


# ------------------ LEARNERS ------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    conn = _connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            name AS "Name",
            surname AS "Surname",
            barcode AS "Barcode",
            grade AS "Grade",
            area AS "Area",
            dob AS "Date Of Birth"
        FROM learners
        ORDER BY grade, name, surname
    """, conn)
    conn.close()
    return df.fillna("").astype(str)


def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    df = df.copy().fillna("").astype(str)
    # Normalize columns
    df.columns = [c.strip() for c in df.columns]
    need = ["Name", "Surname", "Barcode"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Missing column: {c}")

    for c in ["Grade", "Area", "Date Of Birth"]:
        if c not in df.columns:
            df[c] = ""

    df["Barcode"] = df["Barcode"].map(norm_barcode)
    df = df[df["Barcode"] != ""].drop_duplicates(subset=["Barcode"]).reset_index(drop=True)

    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners")
    conn.commit()

    cur.executemany("""
        INSERT INTO learners(barcode, name, surname, grade, area, dob)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (r["Barcode"], r["Name"], r["Surname"], r["Grade"], r["Area"], r["Date Of Birth"])
        for _, r in df.iterrows()
    ])
    conn.commit()
    conn.close()


def delete_learner_by_barcode(db_path: Path, barcode: str) -> bool:
    barcode = norm_barcode(barcode)
    if not barcode:
        return False
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM learners WHERE barcode = ?", (barcode,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def seed_learners_from_csv_if_empty(db_path: Path, seed_csv: str = "learners_seed.csv"):
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM learners")
    n = cur.fetchone()[0]
    conn.close()

    if n > 0:
        return

    p = Path(seed_csv)
    if not p.exists():
        return

    df = pd.read_csv(p).fillna("").astype(str)
    replace_learners_from_df(db_path, df)


# ------------------ ATTENDANCE ------------------

def _attendance_colnames(conn) -> dict:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(attendance)").fetchall()]
    date_label_col = "date_label" if "date_label" in cols else ("label" if "label" in cols else "date_label")
    date_iso_col = "date_iso" if "date_iso" in cols else ("date" if "date" in cols else "date_iso")
    return {"date_label": date_label_col, "date_iso": date_iso_col}


def add_class_date(db_path: Path, date_label: str, date_iso: str):
    # Not required for pivot-based view; kept for compatibility.
    # (If you want, you could pre-create rows here, but we do it on scan.)
    return


def insert_present_mark(db_path: Path, barcode: str, date_label: str, date_iso: str, ts_iso: str):
    barcode = norm_barcode(barcode)
    if not barcode:
        return

    conn = _connect(db_path)
    cols = _attendance_colnames(conn)
    dl = cols["date_label"]
    di = cols["date_iso"]

    conn.execute(f"""
        INSERT INTO attendance(barcode, {dl}, {di}, present, ts_iso)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(barcode, {dl}) DO UPDATE SET
            present = 1,
            ts_iso = excluded.ts_iso,
            {di} = excluded.{di}
    """, (barcode, date_label, date_iso, ts_iso))
    conn.commit()
    conn.close()


# ------------------ IN/OUT LOG ------------------

def append_inout_log(db_path: Path, barcode: str, action: str, ts_iso: str, date_iso: str, time_str: str):
    barcode = norm_barcode(barcode)
    action = str(action).strip().upper()
    if action not in ("IN", "OUT"):
        return

    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO inout_log(barcode, action, ts_iso, date_iso, time_str)
        VALUES (?, ?, ?, ?, ?)
    """, (barcode, action, ts_iso, date_iso, time_str))
    conn.commit()
    conn.close()


def get_currently_in(db_path: Path, date_iso: str) -> pd.DataFrame:
    """
    Return learners whose LAST action today is IN (and not OUT after).
    """
    conn = _connect(db_path)

    df = pd.read_sql_query("""
        SELECT l.name AS Name, l.surname AS Surname, l.grade AS Grade, l.area AS Area,
               x.barcode AS Barcode, x.action AS Action, x.time_str AS Time
        FROM inout_log x
        JOIN (
            SELECT barcode, MAX(id) AS max_id
            FROM inout_log
            WHERE date_iso = ?
            GROUP BY barcode
        ) last ON last.barcode = x.barcode AND last.max_id = x.id
        LEFT JOIN learners l ON l.barcode = x.barcode
        WHERE x.date_iso = ?
        ORDER BY l.grade, l.name, l.surname
    """, conn, params=(date_iso, date_iso)).fillna("").astype(str)

    conn.close()

    if df.empty:
        return df

    return df[df["Action"] == "IN"].reset_index(drop=True)


def determine_next_action(db_path: Path, barcode: str, date_iso: str) -> str:
    barcode = norm_barcode(barcode)
    if not barcode:
        return "IN"

    conn = _connect(db_path)
    df = pd.read_sql_query("""
        SELECT action
        FROM inout_log
        WHERE barcode = ? AND date_iso = ?
        ORDER BY id DESC
        LIMIT 1
    """, conn, params=(barcode, date_iso))
    conn.close()

    if df.empty:
        return "IN"
    last = str(df.iloc[0]["action"]).upper()
    return "OUT" if last == "IN" else "IN"


# ------------------ WIDE SHEET (learners + date columns) ------------------

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """
    Returns wide dataframe:
    Name, Surname, Barcode, Grade, Area, Date Of Birth, [date_label columns...]
    """
    conn = _connect(db_path)
    cols = _attendance_colnames(conn)
    dl = cols["date_label"]

    learners = pd.read_sql_query("""
        SELECT
            name AS "Name",
            surname AS "Surname",
            barcode AS "Barcode",
            grade AS "Grade",
            area AS "Area",
            dob AS "Date Of Birth"
        FROM learners
        ORDER BY grade, name, surname
    """, conn).fillna("").astype(str)

    if learners.empty:
        conn.close()
        return learners

    att = pd.read_sql_query(f"""
        SELECT barcode, {dl} AS date_label, present
        FROM attendance
    """, conn).fillna("")

    conn.close()

    if att.empty:
        return learners

    # Ensure only 0/1
    att["present"] = att["present"].apply(lambda x: "1" if str(x).strip() in ("1", "True", "true") else "")

    wide = att.pivot_table(index="barcode", columns="date_label", values="present", aggfunc="max").reset_index()
    out = learners.merge(wide, how="left", left_on="Barcode", right_on="barcode").drop(columns=["barcode"])
    out = out.fillna("")
    return out
