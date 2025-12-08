# attendance_inout_scanner.py
# Scan IN / OUT attendance system with daily presence + scan log.
#
# Files:
#   - attendance_clean.csv : main register (Name, Surname, Barcode, Grade, Area, date columns like "7-Dec")
#   - attendance_log.csv   : scan log (created automatically)

import pandas as pd
from datetime import datetime
from pathlib import Path

SHEET_PATH = Path("attendance_clean.csv")
LOG_PATH   = Path("attendance_log.csv")

# ---------- Helpers ----------

def today_labels():
    """Return (date_col_label, date_str, time_str, timestamp)."""
    now = datetime.now()
    # For the sheet column (e.g. "7-Dec")
    day = str(int(now.strftime("%d")))
    mon = now.strftime("%b")
    date_col = f"{day}-{mon}"

    # For the log file
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    ts = now.isoformat(timespec="seconds")
    return date_col, date_str, time_str, ts

def _norm(code: str) -> str:
    """Normalize barcode so 0001 and 1 are treated the same."""
    s = str(code).strip()
    s = s.lstrip("0")
    return s if s != "" else "0"

def load_sheet() -> pd.DataFrame:
    if not SHEET_PATH.exists():
        raise FileNotFoundError(f"Cannot find {SHEET_PATH.name}. Put it next to this script.")
    df = pd.read_csv(SHEET_PATH, dtype=str).fillna("")
    # Make sure these columns exist
    if "Barcode" not in df.columns:
        df.insert(1, "Barcode", "")
    if "Name" not in df.columns:
        df["Name"] = ""
    if "Surname" not in df.columns:
        df["Surname"] = ""
    return df

def save_sheet(df: pd.DataFrame) -> None:
    df.to_csv(SHEET_PATH, index=False)

def ensure_today_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = ""

def label_for_row(r: pd.Series) -> str:
    name = str(r.get("Name", "")).strip()
    surname = str(r.get("Surname", "")).strip()
    full = (name + " " + surname).strip()
    return full if full else str(r.get("Barcode", "")).strip()

def load_log() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=["Timestamp", "Date", "Time", "Barcode", "Name", "Surname", "Action"])
    df = pd.read_csv(LOG_PATH, dtype=str).fillna("")
    # Ensure columns exist
    for col in ["Timestamp", "Date", "Time", "Barcode", "Name", "Surname", "Action"]:
        if col not in df.columns:
            df[col] = ""
    return df

def save_log(df: pd.DataFrame) -> None:
    df.to_csv(LOG_PATH, index=False)

def determine_next_action(log_df: pd.DataFrame, barcode: str, date_str: str) -> str:
    """Based on today’s log for this barcode, decide IN or OUT."""
    norm_b = _norm(barcode)
    today_rows = log_df[
        (log_df["Date"] == date_str) &
        (log_df["Barcode"].astype(str).apply(_norm) == norm_b)
    ]
    if today_rows.empty:
        # First scan today -> IN
        return "IN"
    last_action = today_rows.iloc[-1]["Action"].upper()
    if last_action == "IN":
        return "OUT"
    else:
        return "IN"

def get_currently_in(log_df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """Who is currently IN today (last action today is IN)."""
    if log_df.empty:
        return pd.DataFrame(columns=["Barcode", "Name", "Surname"])
    today = log_df[log_df["Date"] == date_str].copy()
    if today.empty:
        return pd.DataFrame(columns=["Barcode", "Name", "Surname"])
    # Sort by time to get last action per barcode
    today = today.sort_values(by=["Barcode", "Timestamp"])
    last_actions = today.groupby("Barcode").tail(1)
    current_in = last_actions[last_actions["Action"].str.upper() == "IN"]
    return current_in[["Barcode", "Name", "Surname"]].reset_index(drop=True)

# ---------- Core scan logic ----------

def process_scan(barcode: str) -> None:
    barcode = str(barcode).strip()
    if not barcode:
        print("❌ Empty scan ignored.")
        return

    if not SHEET_PATH.exists():
        print(f"❌ Cannot find {SHEET_PATH.name}. Put it next to this script.")
        return

    # Load main sheet & log
    df = load_sheet()
    log_df = load_log()

    date_col, date_str, time_str, ts = today_labels()

    # Make sure today's column exists in main sheet
    ensure_today_column(df, date_col)

    # Find learner(s) with this barcode
    matches = df.index[df["Barcode"].astype(str).apply(_norm) == _norm(barcode)].tolist()
    if not matches:
        print("❌ Barcode not found in attendance_clean.csv.")
        print("   Tip: add this barcode into the 'Barcode' column for the correct learner.")
        return

    if len(matches) > 1:
        print(f"⚠️ Warning: {len(matches)} learners share this barcode. All will be logged.")

    # Decide IN or OUT based on log
    action = determine_next_action(log_df, barcode, date_str)

    for idx in matches:
        # Mark present for the day (first time only; never remove presence)
        if str(df.at[idx, date_col]).strip() != "1":
            df.at[idx, date_col] = "1"

        who = label_for_row(df.loc[idx])
        row_barcode = str(df.at[idx, "Barcode"]).strip()

        # Add log entry
        new_row = {
            "Timestamp": ts,
            "Date": date_str,
            "Time": time_str,
            "Barcode": row_barcode,
            "Name": str(df.at[idx, "Name"]),
            "Surname": str(df.at[idx, "Surname"]),
            "Action": action,
        }
        log_df = pd.concat([log_df, pd.DataFrame([new_row])], ignore_index=True)

        print(f"✅ {who} [{row_barcode}] marked {action} at {time_str} ({date_str}).")

    # Save changes
    save_sheet(df)
    save_log(log_df)

    # Show who is currently IN after this scan
    current_in = get_currently_in(log_df, date_str)
    print(f"\n📋 Currently IN today ({date_str}): {len(current_in)}")
    for _, r in current_in.iterrows():
        who = (str(r["Name"]).strip() + " " + str(r["Surname"]).strip()).strip()
        if not who:
            who = f"[{r['Barcode']}]"
        print(f"  - {who} [{r['Barcode']}]")
    print("-" * 40)

# ---------- Main loop ----------

if __name__ == "__main__":
    print("📌 IN/OUT Attendance Scanner")
    print(f"Using main sheet: {SHEET_PATH}")
    print(f"Using log file : {LOG_PATH}")
    print("First scan today = IN, next scan = OUT, then IN again, etc.")
    print("Press CTRL+C to stop.\n")

    try:
        while True:
            code = input("Scan code: ").strip()
            if code:
                process_scan(code)
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")
