# db.py
import sqlite3
from pathlib import Path
import pandas as pd

# ------------------ UTIL ------------------

def norm_barcode(b) -> str:
    if b is None:
        return ""
    s = str(b).strip()
    s = s.lstrip("0")  # normalize leading zeros
    return s or "0"

def _connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path), check_same_thread=False)

# ------------------ INIT DB ------------------

def init_db(db_path: Path):
    con = _connect(db_path)
    cur = con.cursor()

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        Barcode TEXT,
        Date_Label TEXT,
        Date_Str TEXT,
        Time_Str TEXT,
        Mark TEXT
    )
    """)

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

    if df.empty:
        return df

    lower = {c.lower(): c for c in df.columns}
    rename = {}

    # barcode
    if "barcode" in lower:
        rename[lower["barcode"]] = "Barcode"
    elif "barcode_norm" in lower:
        rename[lower["barcode_norm"]] = "Barcode"

    # names
    if "name" in lower:
        rename[lower["name"]] = "Name"
    if "surname" in lower:
        rename[lower["surname"]] = "Surname"
    if "grade" in lower:
        rename[lower["grade"]] = "Grade"
    if "area" in lower:
        rename[lower["area"]] = "Area"

    # dob variants
    if "date_of_birth" in lower:
        rename[lower["date_of_birth"]] = "Date Of Birth"
    elif "date_of_birth" in lower:
        rename[lower["date_of_birth"]] = "Date Of Birth"
    elif "date_of_birth" in lower:
        rename[lower["date_of_birth"]] = "Date Of Birth"
    elif "dob" in lower:
        rename[lower["dob"]] = "Date Of Birth"
    elif "date_of_birth" not in lower and "Date_Of_Birth" in df.columns:
        rename["Date_Of_Birth"] = "Date Of Birth"

    if rename:
        df = df.rename(columns=rename)

    # ensure required columns always exist
    for c in ["Barcode", "Name", "Surname", "Grade", "Area", "Date Of Birth"]:
        if c not in df.columns:
            df[c] = ""

    return df


# ------------------ ATTENDANCE ------------------

def add_class_date(db_path: Path, date_label: str):
    # No-op (attendance date becomes a column when scans exist)
    return

def insert_present_mark(db_path: Path, date_label: str, date_str: str, time_str: str, barcode: str):
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
        return learners.fillna("")

    wide = att.pivot_table(
        index="Barcode",
        columns="Date_Label",
        values="Mark",
        aggfunc="last"
    ).reset_index()

    df = learners.merge(wide, on="Barcode", how="left")
    return df.fillna("")

# ------------------ IN / OUT LOGIC ------------------

def append_inout_log(db_path: Path, ts_iso: str, date_str: str, time_str: str,
                     barcode: str, name: str, surname: str, action: str):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO inout_log (ts_iso, date_str, time_str, barcode, name, surname, action)
        VALUES (?,?,?,?,?,?,?)
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
    current = latest[latest["action"] == "IN"][["barcode", "name", "surname"]].copy()
    return current.rename(columns={"barcode": "Barcode", "name": "Name", "surname": "Surname"})

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
def already_sent_today(db_path: Path, date_str: str) -> bool:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE send_date = ?", (date_str,))
    row = cur.fetchone()
    con.close()
    return bool(row)

def mark_sent_today(db_path: Path, date_str: str, ts_iso: str):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log(send_date, sent_at) VALUES (?, ?)",
        (date_str, ts_iso),
    )
    con.commit()
    con.close()


# ------------------ CSV SEED ------------------

def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str):
    existing = get_learners_df(db_path)
    if not existing.empty:
        return

    p = Path(csv_path)
    if not p.exists():
        return

    csv_df = pd.read_csv(p).fillna("").astype(str)
    csv_df.columns = [c.strip() for c in csv_df.columns]

    required = ["Name", "Surname", "Barcode"]
    if not all(c in csv_df.columns for c in required):
        return

    for c in ["Grade", "Area", "Date Of Birth"]:
        if c not in csv_df.columns:
            csv_df[c] = ""

    csv_df = csv_df[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]]
    replace_learners_from_df(db_path, csv_df)


