# db.py
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd

# ------------------ UTIL ------------------

def norm_barcode(b):
    if b is None:
        return ""
    s = str(b).strip()
    s = s.lstrip("0")  # normalize leading zeros
    return s or "0"

def _connect(db_path: Path):
    return sqlite3.connect(str(db_path), check_same_thread=False)

# ------------------ INIT DB ------------------

def init_db(db_path: Path):
    con = _connect(db_path)
    cur = con.cursor()

    # Learners
    cur.execute("""
    CREATE TABLE IF NOT EXISTS learners (
        Barcode TEXT PRIMARY KEY,
        Name TEXT,
        Surname TEXT,
        Grade TEXT,
        Area TEXT,
        Date_Of_Birth TEXT
    )
    """)

    # Attendance marks (wide logic handled in code)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        Barcode TEXT,
        Date_Label TEXT,
        Date_Str TEXT,
        Time_Str TEXT,
        Mark TEXT
    )
    """)

    # IN / OUT log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inout_log (
        ts_iso TEXT,
        date_str TEXT,
        time_str TEXT,
        barcode TEXT,
        name TEXT,
        surname TEXT,
        action TEXT
    )
    """)

    # Auto-send log (WhatsApp)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        send_date TEXT PRIMARY KEY,
        sent_at TEXT
    )
    """)

    con.commit()
    con.close()

# ------------------ LEARNERS ------------------

def get_learners_df(db_path: Path) -> pd.DataFrame:
    con = _connect(db_path)
    df = pd.read_sql("SELECT * FROM learners", con)
    con.close()

    if not df.empty:
        df = df.rename(columns={"Date_Of_Birth": "Date Of Birth"})
    return df

def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("DELETE FROM learners")

    for _, r in df.iterrows():
        cur.execute("""
        INSERT INTO learners (Barcode, Name, Surname, Grade, Area, Date_Of_Birth)
        VALUES (?,?,?,?,?,?)
        """, (
            norm_barcode(r["Barcode"]),
            r.get("Name",""),
            r.get("Surname",""),
            r.get("Grade",""),
            r.get("Area",""),
            r.get("Date Of Birth","")
        ))

    con.commit()
    con.close()

def delete_learner_by_barcode(db_path: Path, barcode: str) -> int:
    con = _connect(db_path)
    cur = con.cursor()
    nb = norm_barcode(barcode)
    cur.execute("DELETE FROM learners WHERE Barcode = ?", (nb,))
    count = cur.rowcount
    con.commit()
    con.close()
    return count

# ------------------ ATTENDANCE ------------------

def add_class_date(db_path: Path, date_label: str):
    # No-op: attendance rows created on scan
    return

def insert_present_mark(db_path: Path, date_label, date_str, time_str, barcode):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO attendance (Barcode, Date_Label, Date_Str, Time_Str, Mark)
    VALUES (?,?,?,?,?)
    """, (norm_barcode(barcode), date_label, date_str, time_str, "1"))
    con.commit()
    con.close()

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    learners = get_learners_df(db_path)
    if learners.empty:
        return learners

    con = _connect(db_path)
    att = pd.read_sql("SELECT * FROM attendance", con)
    con.close()

    if att.empty:
        return learners

    wide = att.pivot_table(
        index="Barcode",
        columns="Date_Label",
        values="Mark",
        aggfunc="last"
    ).reset_index()

    df = learners.merge(wide, on="Barcode", how="left")
    return df.fillna("")

# ------------------ IN / OUT LOGIC ------------------

def append_inout_log(db_path, ts_iso, date_str, time_str, barcode, name, surname, action):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
    INSERT INTO inout_log
    VALUES (?,?,?,?,?,?)
    """, (ts_iso, date_str, time_str, norm_barcode(barcode), name, surname, action))
    con.commit()
    con.close()

def determine_next_action(db_path: Path, barcode: str, date_str: str) -> str:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
    SELECT action FROM inout_log
    WHERE barcode = ? AND date_str = ?
    ORDER BY ts_iso DESC LIMIT 1
    """, (norm_barcode(barcode), date_str))
    row = cur.fetchone()
    con.close()

    if row is None:
        return "IN"
    return "OUT" if row[0] == "IN" else "IN"

def get_currently_in(db_path: Path, date_str: str) -> pd.DataFrame:
    con = _connect(db_path)
    df = pd.read_sql("""
    SELECT * FROM inout_log
    WHERE date_str = ?
    ORDER BY ts_iso
    """, con, params=(date_str,))
    con.close()

    if df.empty:
        return df

    latest = df.sort_values("ts_iso").groupby("barcode").tail(1)
    return latest[latest["action"] == "IN"][["barcode","name","surname"]].rename(
        columns={"barcode":"Barcode","name":"Name","surname":"Surname"}
    )

# ------------------ AUTO SEND ------------------

def ensure_auto_send_table(db_path: Path):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_send_log (
        send_date TEXT PRIMARY KEY,
        sent_at TEXT
    )
    """)
    con.commit()
    con.close()

# ------------------ CSV SEED ------------------

def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str):
    df = get_learners_df(db_path)
    if not df.empty:
        return

    p = Path(csv_path)
    if not p.exists():
        return

    csv_df = pd.read_csv(p).fillna("").astype(str)
    csv_df.columns = [c.strip() for c in csv_df.columns]

    required = ["Name","Surname","Barcode"]
    if not all(c in csv_df.columns for c in required):
        return

    for c in ["Grade","Area","Date Of Birth"]:
        if c not in csv_df.columns:
            csv_df[c] = ""

    csv_df = csv_df[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]]
    replace_learners_from_df(db_path, csv_df)
