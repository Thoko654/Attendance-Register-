# db.py — SQLite backend for Tutor Class Attendance Register

import sqlite3
from pathlib import Path
import pandas as pd

def ensure_auto_send_table(db_path: Path):
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_send_log (
            send_date TEXT PRIMARY KEY,
            sent_at   TEXT
        )
    """)
    con.commit()
    con.close()



# ------------------ HELPERS ------------------
def norm_barcode(code: str) -> str:
    s = str(code).strip()
    # remove leading zeros so 0001 == 1
    s = s.lstrip("0")
    return s if s != "" else "0"


def get_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------ DB INIT ------------------
def init_db(db_path: Path):
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

    # dates = optional list of class dates (so you can add future Saturdays)
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

    # IN/OUT log (same as your attendance_log.csv but in DB)
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


# ------------------ SEED / IMPORT FROM CSV ------------------
def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str = "attendance_clean.csv") -> int:
    """
    If learners table is empty, import learners from a CSV file.
    Returns number of imported rows.
    Safe: will NOT overwrite learners if DB already has learners.
    """
    # if DB already has learners, do nothing
    try:
        existing = get_learners_df(db_path)
        if existing is not None and len(existing) > 0:
            return 0
    except Exception:
        # if query fails for some reason, don't seed
        return 0

    p = Path(csv_path)
    if not p.exists():
        return 0

    df = pd.read_csv(p, dtype=str).fillna("")

    # Your CSV has: Barcode, Name, Surname, Grade, Area, Date Of Birth
    # It may also have extra columns - ignore them safely.
    needed = ["Barcode", "Name", "Surname", "Grade", "Area", "Date Of Birth"]
    for c in needed:
        if c not in df.columns:
            df[c] = ""

    learners_df = df[needed].copy()

    # Clean barcode + drop blanks + deduplicate
    learners_df["Barcode"] = learners_df["Barcode"].astype(str).str.strip()
    learners_df = learners_df[learners_df["Barcode"] != ""]
    learners_df = learners_df.drop_duplicates(subset=["Barcode"]).reset_index(drop=True)

    replace_learners_from_df(db_path, learners_df)
    return len(learners_df)


# ------------------ LEARNERS CRUD ------------------
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
    # Replace learners table from a dataframe (used by Manage → Save changes)
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


# ------------------ DATES ------------------
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


# ------------------ DATAFRAMES ------------------
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
    """
    Returns a dataframe like your old CSV:
    Barcode, Name, Surname, Grade, Area, Date Of Birth, plus date columns like 22-Jan
    """
    learners = get_learners_df(db_path)

    conn = get_conn(db_path)
    marks = pd.read_sql("""
        SELECT date_label, barcode, present
        FROM attendance_marks
        WHERE present = 1
    """, conn)
    conn.close()

    # include all dates (future dates too)
    all_dates = set(get_all_class_dates(db_path))
    if not marks.empty:
        all_dates |= set(marks["date_label"].astype(str).tolist())

    # pivot present marks
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

    # ensure date columns exist in df even if empty
    for d in sorted(all_dates, key=str):
        if d not in wide.columns:
            wide[d] = ""

    wide = wide.fillna("").astype(str)
    return wide


# ------------------ ATTENDANCE + LOGS ------------------
def insert_present_mark(db_path: Path, date_label: str, date_str: str, time_str: str, barcode: str):
    conn = get_conn(db_path)
    cur = conn.cursor()

    # store the date label as a known class date
    cur.execute("INSERT OR IGNORE INTO class_dates(date_label) VALUES (?)", (date_label,))

    # avoid duplicate present mark for same learner + date
    cur.execute("""
        SELECT 1 FROM attendance_marks
        WHERE date_label=? AND barcode=? AND present=1
        LIMIT 1
    """, (date_label, barcode))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute("""
            INSERT INTO attendance_marks (date_label, date_str, time_str, barcode, present)
            VALUES (?, ?, ?, ?, 1)
        """, (date_label, date_str, time_str, barcode))

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



