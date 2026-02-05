# db.py
import sqlite3
from pathlib import Path
import pandas as pd

# ------------------ UTIL ------------------

def norm_barcode(b) -> str:
    """Normalize barcode for matching (strip spaces and leading zeros)."""
    if b is None:
        return ""
    s = str(b).strip()
    s = s.lstrip("0")
    return s or "0"

def _connect(db_path: Path):
    """Connect to SQLite; ensure folder exists."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path), check_same_thread=False)

def _normalize_learner_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure learners dataframe always has these columns:
    Barcode, Name, Surname, Grade, Area, Date Of Birth
    """
    if df is None or df.empty:
        # Return empty with required columns
        return pd.DataFrame(columns=["Barcode","Name","Surname","Grade","Area","Date Of Birth"])

    df = df.copy()
    # Normalize column names (case-insensitive matching)
    lower_map = {c.lower().strip(): c for c in df.columns}

    def pick(*candidates):
        for cand in candidates:
            key = cand.lower()
            if key in lower_map:
                return lower_map[key]
        return None

    rename = {}

    # Standard fields
    c = pick("barcode")
    if c: rename[c] = "Barcode"

    c = pick("name")
    if c: rename[c] = "Name"

    c = pick("surname", "last name", "lastname")
    if c: rename[c] = "Surname"

    c = pick("grade")
    if c: rename[c] = "Grade"

    c = pick("area")
    if c: rename[c] = "Area"

    # DOB variants
    c = pick("date of birth", "date_of_birth", "date_of_birth ", "dob", "birthdate", "birth date", "date_of_birth")
    if c:
        rename[c] = "Date Of Birth"
    elif "date_of_birth" in lower_map:
        rename[lower_map["date_of_birth"]] = "Date Of Birth"
    elif "date_of_birth " in lower_map:
        rename[lower_map["date_of_birth "]] = "Date Of Birth"
    elif "date_of_birth" not in lower_map and "date_of_birth" not in df.columns and "Date_Of_Birth" in df.columns:
        rename["Date_Of_Birth"] = "Date Of Birth"
    elif "Date_Of_Birth" in df.columns:
        rename["Date_Of_Birth"] = "Date Of Birth"

    if rename:
        df = df.rename(columns=rename)

    # Ensure required columns exist
    for c in ["Barcode", "Name", "Surname", "Grade", "Area", "Date Of Birth"]:
        if c not in df.columns:
            df[c] = ""

    # Force string type
    df = df.fillna("").astype(str)

    # Normalize barcode values
    df["Barcode"] = df["Barcode"].apply(norm_barcode)

    return df[["Barcode","Name","Surname","Grade","Area","Date Of Birth"]]


# ------------------ INIT DB ------------------

def init_db(db_path: Path):
    """Create required tables if they don't exist (does NOT delete data)."""
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
    """Return learners table as a clean DataFrame with 'Date Of Birth' column."""
    con = _connect(db_path)
    try:
        df = pd.read_sql("SELECT * FROM learners", con)
    finally:
        con.close()

    if df.empty:
        return pd.DataFrame(columns=["Barcode","Name","Surname","Grade","Area","Date Of Birth"])

    # DB uses Date_Of_Birth
    if "Date_Of_Birth" in df.columns:
        df = df.rename(columns={"Date_Of_Birth": "Date Of Birth"})

    return _normalize_learner_columns(df)

def replace_learners_from_df(db_path: Path, df: pd.DataFrame):
    """
    Replace ALL learners with the rows in df.
    Note: This does NOT delete attendance table. It only replaces learners table.
    """
    df = _normalize_learner_columns(df)

    con = _connect(db_path)
    cur = con.cursor()

    # Replace learners entirely
    cur.execute("DELETE FROM learners")

    for _, r in df.iterrows():
        bc = norm_barcode(r.get("Barcode", ""))
        if not bc.strip():
            continue

        cur.execute("""
            INSERT OR REPLACE INTO learners
            (Barcode, Name, Surname, Grade, Area, Date_Of_Birth)
            VALUES (?,?,?,?,?,?)
        """, (
            bc,
            str(r.get("Name", "")).strip(),
            str(r.get("Surname", "")).strip(),
            str(r.get("Grade", "")).strip(),
            str(r.get("Area", "")).strip(),
            str(r.get("Date Of Birth", "")).strip(),
        ))

    con.commit()
    con.close()

def add_or_update_learner(db_path: Path, barcode: str, name: str, surname: str,
                          grade: str = "", area: str = "", dob: str = "") -> None:
    """Insert or update one learner (by barcode)."""
    bc = norm_barcode(barcode)
    if not bc.strip():
        return

    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO learners (Barcode, Name, Surname, Grade, Area, Date_Of_Birth)
        VALUES (?,?,?,?,?,?)
    """, (bc, name.strip(), surname.strip(), str(grade).strip(), str(area).strip(), str(dob).strip()))
    con.commit()
    con.close()

def delete_learner_by_barcode(db_path: Path, barcode: str) -> int:
    """Delete learner by barcode. Returns number deleted."""
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
    """No-op: dates appear when attendance rows exist."""
    return

def insert_present_mark(db_path: Path, date_label: str, date_str: str, time_str: str, barcode: str):
    """Insert attendance mark '1' for a barcode and a date label."""
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO attendance (Barcode, Date_Label, Date_Str, Time_Str, Mark)
        VALUES (?,?,?,?,?)
    """, (norm_barcode(barcode), str(date_label), str(date_str), str(time_str), "1"))
    con.commit()
    con.close()

def get_wide_sheet(db_path: Path) -> pd.DataFrame:
    """
    Join learners with attendance pivot (wide format).
    Columns: Barcode, Name, Surname, Grade, Area, Date Of Birth, plus date columns like '3-Feb'
    """
    learners = get_learners_df(db_path)
    if learners.empty:
        return learners

    con = _connect(db_path)
    try:
        att = pd.read_sql("SELECT * FROM attendance", con)
    finally:
        con.close()

    if att.empty:
        return learners.fillna("")

    att = att.fillna("").astype(str)
    # Normalize barcode in attendance too
    if "Barcode" in att.columns:
        att["Barcode"] = att["Barcode"].apply(norm_barcode)

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
    """Toggle IN/OUT for the same learner on the same date."""
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("""
        SELECT action FROM inout_log
        WHERE barcode = ? AND date_str = ?
        ORDER BY ts_iso DESC LIMIT 1
    """, (norm_barcode(barcode), str(date_str)))
    row = cur.fetchone()
    con.close()

    if row is None:
        return "IN"
    return "OUT" if row[0] == "IN" else "IN"

def get_currently_in(db_path: Path, date_str: str) -> pd.DataFrame:
    """Return learners who are currently IN for a given date."""
    con = _connect(db_path)
    try:
        df = pd.read_sql("""
            SELECT * FROM inout_log
            WHERE date_str = ?
            ORDER BY ts_iso
        """, con, params=(str(date_str),))
    finally:
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
    cur.execute("SELECT 1 FROM auto_send_log WHERE send_date = ?", (str(date_str),))
    row = cur.fetchone()
    con.close()
    return bool(row)

def mark_sent_today(db_path: Path, date_str: str, ts_iso: str):
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log(send_date, sent_at) VALUES (?, ?)",
        (str(date_str), str(ts_iso)),
    )
    con.commit()
    con.close()


# ------------------ CSV SEED ------------------

def seed_learners_from_csv_if_empty(db_path: Path, csv_path: str):
    """
    If learners table is empty, seed from CSV.
    CSV required: Name, Surname, Barcode
    Optional: Grade, Area, Date Of Birth
    """
    existing = get_learners_df(db_path)
    if not existing.empty:
        return

    p = Path(csv_path)
    if not p.exists():
        return

    csv_df = pd.read_csv(p).fillna("").astype(str)
    csv_df.columns = [c.strip() for c in csv_df.columns]

    # Accept 'Date_Of_Birth' from CSV too
    if "Date_Of_Birth" in csv_df.columns and "Date Of Birth" not in csv_df.columns:
        csv_df = csv_df.rename(columns={"Date_Of_Birth": "Date Of Birth"})

    required = ["Name", "Surname", "Barcode"]
    if not all(c in csv_df.columns for c in required):
        return

    for c in ["Grade", "Area", "Date Of Birth"]:
        if c not in csv_df.columns:
            csv_df[c] = ""

    csv_df = csv_df[["Barcode","Name","Surname","Grade","Area","Date Of Birth"]]
    replace_learners_from_df(db_path, csv_df)

