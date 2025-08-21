# Tutor Class Attendance Register 2025 — Streamlit App

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
import time

CSV_DEFAULT = "attendance_clean.csv"

# ---------- Utilities ----------
def today_col_label():
    return datetime.now().strftime("%d-%b").lstrip("0")

def _norm(code: str) -> str:
    return str(code).strip().lstrip("0") or "0"

@contextmanager
def file_guard(path: Path):
    for _ in range(6):
        try:
            yield
            return
        except Exception:
            time.sleep(0.2)

def load_sheet(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame()
    with file_guard(csv_path):
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    for col in ["Barcode", "Name", "Surname"]:
        if col not in df.columns:
            df[col] = ""
    return df

def save_sheet(df: pd.DataFrame, csv_path: Path):
    with file_guard(csv_path):
        df.to_csv(csv_path, index=False)

def ensure_date_column(df: pd.DataFrame, col: str):
    if col not in df.columns:
        df[col] = ""

def ensure_today_column(df: pd.DataFrame) -> str:
    col = today_col_label()
    ensure_date_column(df, col)
    return col

def label_for_row(r: pd.Series) -> str:
    return f"{r.get('Name','').strip()} {r.get('Surname','').strip()}".strip()

def get_date_columns(df: pd.DataFrame):
    return sorted([
        c for c in df.columns
        if "-" in c and c.split("-")[0].isdigit()
    ], key=lambda x: datetime.strptime(x, "%d-%b").timetuple().tm_yday)

def mark_present(barcode: str, csv_path: Path):
    if not barcode.strip():
        return False, "Empty scan."
    df = load_sheet(csv_path)
    if df.empty:
        return False, "Attendance sheet is empty or not found."
    today_col = ensure_today_column(df)
    matches = df.index[df["Barcode"].apply(_norm) == _norm(barcode)].tolist()
    if not matches:
        return False, "Student ID not found."
    msg = []
    for i in matches:
        name = label_for_row(df.loc[i]) or f"[{df.at[i,'Barcode']}]"
        if str(df.at[i, today_col]).strip() == "1":
            msg.append(f"ℹ️ {name} already marked.")
        else:
            df.at[i, today_col] = "1"
            msg.append(f"✅ {name} marked PRESENT.")
    save_sheet(df, csv_path)
    return True, "\n".join(msg)

def get_present_absent(df, date_col, grade=None, area=None):
    if date_col not in df.columns:
        return df.iloc[0:0], df.copy()
    filt = pd.Series([True]*len(df))
    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)
    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)
    subset = df[filt].copy()
    return subset[subset[date_col] == "1"], subset[subset[date_col] != "1"]

def unique_sorted(series):
    vals = sorted([v for v in series.astype(str).unique() if v.strip()])
    return ["(All)"] + vals

# ---------- Tracking ----------
def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Present","Absent","Attendance %","Last present"])
    present_mat = df[date_cols].applymap(lambda x: 1 if x.strip() == "1" else 0)
    total_sessions = len(date_cols)
    present_counts = present_mat.sum(axis=1)
    absent_counts = total_sessions - present_counts
    pct = (present_counts / total_sessions * 100).round(1)
    last_present = [
        date_cols[max([i for i, val in enumerate(row) if val == 1])] if any(row) else "—"
        for row in present_mat.values.tolist()
    ]
    return pd.DataFrame({
        "Name": df.get("Name",""),
        "Surname": df.get("Surname",""),
        "Barcode": df.get("Barcode",""),
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present
    })

# ---------- UI ----------
st.set_page_config("Tutor Class Attendance Register 2025", "✅", layout="wide")

st.markdown("""
    <style>
    .app-title {font-size: 28px; font-weight: bold;}
    .stat-card {padding: 10px 14px; border: 1px solid #eee; border-radius: 10px;}
    </style>
""", unsafe_allow_html=True)

st.title("📚 Tutor Class Attendance Register 2025")

with st.sidebar:
    csv_path_str = st.text_input("CSV file path", CSV_DEFAULT)
    csv_path = Path(csv_path_str).expanduser()

tabs = st.tabs(["📷 Scan", "📅 Today", "📈 Tracking", "🛠 Manage"])

# ---------- Tab 1: Scan ----------
with tabs[0]:
    st.header("📸 Scan to Mark Attendance")
    scan = st.text_input("Scan or Enter Student ID", key="scan_id")
    if st.button("Mark Present"):
        if scan:
            ok, msg = mark_present(scan, csv_path)
            st.success(msg) if ok else st.error(msg)
            st.session_state.scan_id = ""

# ---------- Tab 2: Today ----------
with tabs[1]:
    st.header(f"📅 Attendance for Today ({today_col_label()})")
    df = load_sheet(csv_path)
    if df.empty:
        st.warning("No attendance has been recorded yet for today.")
    else:
        col = ensure_today_column(df)
        present, absent = get_present_absent(df, col)
        st.markdown(f"✅ Present: **{len(present)}** | ❌ Absent: **{len(absent)}**")
        st.dataframe(present[["Name","Surname","Barcode"]])
        st.download_button("📥 Download Present", present.to_csv(index=False), "present.csv")

# ---------- Tab 3: Tracking ----------
with tabs[2]:
    st.header("📊 Attendance Tracking Summary")
    df = load_sheet(csv_path)
    if df.empty or not get_date_columns(df):
        st.info("No attendance data yet.")
    else:
        summary = compute_tracking(df)
        st.dataframe(summary, use_container_width=True)
        st.download_button("📥 Download Tracking CSV", summary.to_csv(index=False), "tracking.csv")

# ---------- Tab 4: Manage ----------
with tabs[3]:
    st.header("🛠 Manage Students & Attendance")
    df = load_sheet(csv_path)
    action = st.selectbox("Choose Action", ["Add Student", "Edit Student", "Delete Student"])
    if action == "Add Student":
        sid = st.text_input("Student ID")
        name = st.text_input("Name")
        grade = st.text_input("Grade")
        if st.button("Add"):
            new_row = pd.DataFrame({"Barcode":[sid], "Name":[name], "Grade":[grade]})
            df = pd.concat([df, new_row], ignore_index=True)
            save_sheet(df, csv_path)
            st.success("Student added.")
    elif action == "Edit Student":
        sid = st.text_input("Enter Student ID to Edit")
        match = df[df["Barcode"] == sid]
        if not match.empty:
            name = st.text_input("New Name", match.iloc[0]["Name"])
            grade = st.text_input("New Grade", match.iloc[0].get("Grade", ""))
            if st.button("Save Changes"):
                df.loc[df["Barcode"] == sid, "Name"] = name
                df.loc[df["Barcode"] == sid, "Grade"] = grade
                save_sheet(df, csv_path)
                st.success("Student updated.")
        else:
            st.warning("Student not found.")
    elif action == "Delete Student":
        sid = st.text_input("Enter Student ID to Delete")
        if st.button("Delete"):
            df = df[df["Barcode"] != sid]
            save_sheet(df, csv_path)
            st.success("Student deleted.")
