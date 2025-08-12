# attendance_scanner.py
# Scan-IN only attendance updater for "attendance_clean.csv"
# - Uses Barcode as the key
# - Auto-creates today's date column (e.g., "12-Aug")
# - Prevents duplicate marks for the same day

import pandas as pd
from datetime import datetime
from pathlib import Path

CSV_PATH = "attendance_clean.csv"   # keep this file in the same folder as this script


# ---------- Helpers ----------
def today_col_label() -> str:
    """Return today's column label in the format 'D-Mon' (e.g., '12-Aug')."""
    now = datetime.now()
    day = str(int(now.strftime("%d")))   # remove leading zero
    mon = now.strftime("%b")             # Jan, Feb, Mar...
    return f"{day}-{mon}"

def load_sheet(path: str = CSV_PATH) -> pd.DataFrame:
    """Load the attendance sheet as strings (empty string instead of NaN)."""
    df = pd.read_csv(path, dtype=str).fillna("")
    # Ensure mandatory columns exist
    if "Barcode" not in df.columns:
        # Insert after the first column if possible, otherwise at end
        insert_at = 1 if len(df.columns) > 0 else 0
        df.insert(insert_at, "Barcode", "")
    if "Name" not in df.columns:
        df["Name"] = ""
    if "Surname" not in df.columns:
        df["Surname"] = ""
    return df

def save_sheet(df: pd.DataFrame, path: str = CSV_PATH) -> None:
    df.to_csv(path, index=False)

def ensure_today_column(df: pd.DataFrame) -> str:
    """Make sure today's date column exists, create if needed, and return its name."""
    col = today_col_label()
    if col not in df.columns:
        df[col] = ""  # add at the end
    return col

def label_for_row(r: pd.Series) -> str:
    name = str(r.get("Name", "")).strip()
    surname = str(r.get("Surname", "")).strip()
    full = (name + " " + surname).strip()
    return full if full else ""

# ---------- Core ----------
def mark_present(barcode: str) -> None:
    """Mark a single barcode present for today."""
    barcode = str(barcode).strip()
    if not barcode:
        print("❌ Empty scan ignored.")
        return

    if not Path(CSV_PATH).exists():
        print(f"❌ Cannot find {CSV_PATH}. Put it next to this script.")
        return

    df = load_sheet()
    today_col = ensure_today_column(df)

    # Find matching rows by barcode
    matches = df.index[df["Barcode"].astype(str) == barcode].tolist()

    if not matches:
        # Not found -> guide user to add the barcode into the CSV first
        print("❌ Barcode not found in the sheet.")
        print("   Tip: Open attendance_clean.csv and paste this code into the 'Barcode' column for the correct student.")
        return

    if len(matches) > 1:
        print(f"⚠️ Warning: {len(matches)} rows share the same barcode. All will be marked.")
        print("   (Consider ensuring barcodes are unique per student.)")

    marked_count = 0
    for i in matches:
        already = str(df.at[i, today_col]).strip() == "1"
        if already:
            who = label_for_row(df.loc[i])
            who = f"{who} [{barcode}]" if who else f"[{barcode}]"
            print(f"ℹ️ {who} is already marked PRESENT for {today_col}.")
        else:
            df.at[i, today_col] = "1"
            marked_count += 1

    if marked_count > 0:
        save_sheet(df)
        # Echo each newly marked row
        for i in matches:
            if str(df.at[i, today_col]).strip() == "1":
                who = label_for_row(df.loc[i])
                who = f"{who} [{barcode}]" if who else f"[{barcode}]"
                print(f"✅ {who} marked PRESENT for {today_col}.")

def show_today_list() -> None:
    """Print a quick list of who is present today."""
    if not Path(CSV_PATH).exists():
        print(f"❌ Cannot find {CSV_PATH}.")
        return

    df = load_sheet()
    col = today_col_label()
    if col not in df.columns:
        print(f"No scans yet for {col}.")
        return

    present = df[df[col].astype(str) == "1"].copy()
    # Try sorting by Name/Surname if present
    sort_cols = [c for c in ["Name", "Surname"] if c in present.columns]
    if sort_cols:
        present = present.sort_values(by=sort_cols, na_position="last")

    total = len(present)
    print(f"\n📋 Attendance for {col}: {total}")
    if total == 0:
        print("  (No scans yet)")
        return

    for _, r in present.iterrows():
        who = label_for_row(r)
        code = str(r.get("Barcode", "")).strip()
        if who:
            print(f"  - {who}  [{code}]")
        else:
            print(f"  - [{code}]")

# ---------- CLI Loop ----------
if __name__ == "__main__":
    print("📌 Scan barcodes to mark attendance (IN only). Press CTRL+C to stop.")
    print(f"   Using sheet: {CSV_PATH}")
    try:
        while True:
            code = input("Scan Code: ").strip()
            if code:
                mark_present(code)
    except KeyboardInterrupt:
        print("\n🛑 Stopped scanning.")
        show_today_list()
