# db.py — Tutor Class Attendance Register 2026 (SQLite)
# Provides ALL functions used by app.py

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd


# ------------------ DB CONNECTION ------------------

def _connect(db_path: Path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ------------------ INIT / TABLES ------------------

def init_db(db_path: Path):
    """Create all required tables if missing."""
    conn = _connect(db_path)
    cur = conn.cursor()

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        date_label TEXT NOT NULL,        -- e.g. "30-Jan"
        date_iso TEXT NOT NULL,          -- e.g. "2026-01-30"
        present INTEGER NOT NULL DEFAULT 0,
        ts_iso TEXT,
        UNIQUE(barcode, date_label),
        FOREIGN KEY(barcode) REFERENCES learners(barcode) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inout_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        action TEXT NOT NULL,            -- "IN" or "OUT"
        ts_iso TEXT NOT NULL,            -- iso timestamp
        date_iso TEXT NOT NULL,          -- YYYY-MM-DD
        time_str TEXT NOT NULL           -- HH:MM:SS
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        date_iso TEXT PRIMARY KEY,
        ts_iso TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def ensure_auto_send_table(db_path: Path):
    """Kept for compatibility (init_db already creates it)."""
    init_db(db_path)


# ------------------ HELPERS ------------------

def norm_barcode(x: str) -> str:
    x = "" if x is None else str(x)
    x = x.strip().replace(" ", "")
    return x.upper()


def _safe_str(x) -> str:
    return "" if x is None else str(x).strip()


# ------------------ LEARNERS CRUD ------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    init_db(db_path)
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
        ORDER BY Grade, Name, Surname
    """, conn)
    conn.close()
    return df.fillna("")


def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    init_db(db_path)
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute("DELETE FROM learners")
    conn.commit()

    rows = []
    for _, r in df.iterrows():
        bc = norm_barcode(r.get("Barcode", ""))
        if not bc:
            continue
        rows.append((
            bc,
            _safe_str(r.get("Name", "")),
            _safe_str(r.get("Surname", "")),
            _safe_str(r.get("Grade", "")),
            _safe_str(r.get("Area", "")),
            _safe_str(r.get("Date Of Birth", "")),
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO learners(barcode, name, surname, grade, area, dob)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()


def delete_learner_by_barcode(db_path: Path, barcode: str):
    init_db(db_path)
    bc = norm_barcode(barcode)
    if not bc:
        return
    conn = _connect(db_path)
    conn.execute("DELETE FROM learners WHERE barcode = ?", (bc,))
    conn.commit()
    conn.close()


# ------------------ ATTENDANCE ------------------

def add_class_date(db_path: Path, date_label: str, date_iso: str):
    """Ensure every learner has a row for this date (present defaults to 0)."""
    init_db(db_path)
    conn = _connect(db_path)
    cur = conn.cursor()

    learners = pd.read_sql_query("SELECT barcode FROM learners", conn)["barcode"].tolist()
    rows = [(bc, date_label, date_iso) for bc in learners]

    cur.executemany("""
        INSERT OR IGNORE INTO attendance(barcode, date_label, date_iso, present)
        VALUES (?, ?, ?, 0)
    """, rows)

    conn.commit()
    conn.close()


def insert_present_mark(db_path: Path, barcode: str, date_label: str, date_iso: str, ts_iso: str):
    """Mark learner present=1 for that date (UPSERT)."""
    init_db(db_path)
    bc = norm_barcode(barcode)
    if not bc:
        return

    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO attendance(barcode, date_label, date_iso, present, ts_iso)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(barcode, date_label)
        DO UPDATE SET present=1, date_iso=excluded.date_iso, ts_iso=excluded.ts_iso
    """, (bc, date_label, date_iso, ts_iso))

    conn.commit()
    conn.close()


def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """Return learners + attendance pivoted into date columns (like your old CSV layout)."""
    init_db(db_path)
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
    """, conn).fillna("")

    att = pd.read_sql_query("""
        SELECT barcode, date_label, present
        FROM attendance
    """, conn).fillna("")

    conn.close()

    if learners.empty:
        return learners

    if att.empty:
        return learners

    att["barcode"] = att["barcode"].astype(str).map(norm_barcode)
    pivot = att.pivot_table(index="barcode", columns="date_label", values="present", aggfunc="max", fill_value=0)
    pivot = pivot.reset_index().rename(columns={"barcode": "Barcode"})

    merged = learners.copy()
    merged["Barcode"] = merged["Barcode"].astype(str).map(norm_barcode)
    out = merged.merge(pivot, on="Barcode", how="left").fillna("")
    return out


# ------------------ IN/OUT LOG ------------------

def append_inout_log(db_path: Path, barcode: str, action: str, ts_iso: str, date_iso: str, time_str: str):
    init_db(db_path)
    bc = norm_barcode(barcode)
    if not bc:
        return
    action = "IN" if str(action).upper().strip() == "IN" else "OUT"

    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO inout_log(barcode, action, ts_iso, date_iso, time_str)
        VALUES (?, ?, ?, ?, ?)
    """, (bc, action, ts_iso, date_iso, time_str))
    conn.commit()
    conn.close()


def get_currently_in(db_path: Path) -> pd.DataFrame:
    """Learners whose latest log action is IN."""
    init_db(db_path)
    conn = _connect(db_path)

    logs = pd.read_sql_query("""
        SELECT barcode, action, ts_iso
        FROM inout_log
    """, conn)

    learners = pd.read_sql_query("""
        SELECT
            barcode AS "Barcode",
            name AS "Name",
            surname AS "Surname",
            grade AS "Grade",
            area AS "Area"
        FROM learners
    """, conn).fillna("")

    conn.close()

    if logs.empty:
        return learners.iloc[0:0].copy()

    logs["barcode"] = logs["barcode"].astype(str).map(norm_barcode)
    logs = logs.sort_values("ts_iso").groupby("barcode").tail(1)

    currently_in_barcodes = logs.loc[logs["action"] == "IN", "barcode"].tolist()
    if not currently_in_barcodes:
        return learners.iloc[0:0].copy()

    learners["Barcode"] = learners["Barcode"].astype(str).map(norm_barcode)
    out = learners[learners["Barcode"].isin(currently_in_barcodes)].copy()
    return out.sort_values(["Grade", "Name", "Surname"]).reset_index(drop=True)


def determine_next_action(db_path: Path, barcode: str) -> str:
    """If currently IN -> next is OUT, else next is IN."""
    bc = norm_barcode(barcode)
    if not bc:
        return "IN"
    df_in = get_currently_in(db_path)
    if not df_in.empty and bc in df_in["Barcode"].astype(str).tolist():
        return "OUT"
    return "IN"


# ------------------ AUTO SEND LOG ------------------

def already_sent_today(db_path: Path, date_iso: str) -> bool:
    init_db(db_path)
    conn = _connect(db_path)
    row = conn.execute("SELECT date_iso FROM auto_send_log WHERE date_iso = ?", (date_iso,)).fetchone()
    conn.close()
    return row is not None


def mark_sent_today(db_path: Path, date_iso: str, ts_iso: str):
    init_db(db_path)
    conn = _connect(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO auto_send_log(date_iso, ts_iso)
        VALUES (?, ?)
    """, (date_iso, ts_iso))
    conn.commit()
    conn.close()


# ------------------ OPTIONAL SEED ------------------

def seed_learners_from_csv_if_empty(db_path: Path, seed_file: str = "learners_seed.csv"):
    """
    Optional: if learners table is empty and seed CSV exists, load it.
    CSV must have columns: Name, Surname, Barcode, Grade, Area, Date Of Birth
    """
    init_db(db_path)
    conn = _connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM learners").fetchone()[0]
    conn.close()
    if n > 0:
        return

    p = Path(seed_file)
    if not p.exists():
        return

    df = pd.read_csv(p).fillna("").astype(str)
    needed = {"Name", "Surname", "Barcode"}
    if not needed.issubset(set(df.columns)):
        return

    for c in ["Grade", "Area", "Date Of Birth"]:
        if c not in df.columns:
            df[c] = ""

    df = df[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]].copy()
    replace_learners_from_df(db_path, df)
