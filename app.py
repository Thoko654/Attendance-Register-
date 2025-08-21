# app.py — Updated Streamlit Attendance App for 4 Sessions Per Month
# ✅ Streaks and Session tracking removed
# ✅ Attendance % now based on 4 Saturdays

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
import time

CSV_DEFAULT = "attendance_clean.csv"

# --- Utility Functions ---
def today_col_label():
    now = datetime.now()
    return f"{int(now.strftime('%d'))}-{now.strftime('%b')}"

def _norm(code):
    return str(code).strip().lstrip("0") or "0"

@contextmanager
def file_guard(path):
    for _ in range(6):
        try:
            yield
            return
        except Exception:
            time.sleep(0.2)
    raise FileNotFoundError(path)

def load_sheet(path):
    with file_guard(path):
        df = pd.read_csv(path, dtype=str).fillna("")
    if "Barcode" not in df.columns: df.insert(1, "Barcode", "")
    if "Name" not in df.columns: df["Name"] = ""
    if "Surname" not in df.columns: df["Surname"] = ""
    return df

def save_sheet(df, path):
    with file_guard(path):
        df.to_csv(path, index=False)

def ensure_today_column(df):
    col = today_col_label()
    if col not in df.columns:
        df[col] = ""
    return col

def get_date_columns(df):
    def _key(x):
        try: return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except: return 999
    return sorted([c for c in df.columns if '-' in c and c.split('-')[0].isdigit()], key=_key)

def mark_present(barcode, path):
    if not barcode.strip(): return False, "Empty scan."
    if not path.exists(): return False, f"Cannot find {path.name}."

    df = load_sheet(path)
    today_col = ensure_today_column(df)
    matches = df.index[df["Barcode"].apply(_norm) == _norm(barcode)].tolist()

    if not matches:
        return False, "Barcode not found. Add it via Manage tab."

    updated = False
    msgs = []
    for i in matches:
        who = f"{df.at[i, 'Name']} {df.at[i, 'Surname']}".strip() or f"[{df.at[i,'Barcode']}]"
        if str(df.at[i, today_col]).strip() == "1":
            msgs.append(f"ℹ️ {who} is already marked present.")
        else:
            df.at[i, today_col] = "1"
            msgs.append(f"✅ {who} marked PRESENT.")
            updated = True

    if updated:
        save_sheet(df, path)
    return True, "\n".join(msgs)

def get_present_absent(df, date_col, grade=None, area=None):
    filt = pd.Series([True] * len(df))
    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)
    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)
    
    df = df[filt]
    present = df[df[date_col].astype(str) == "1"]
    absent = df[df[date_col].astype(str) != "1"]
    return present, absent

def compute_tracking(df):
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Present","Absent","Attendance %"])

    present_mat = df[date_cols].applymap(lambda x: 1 if str(x).strip() == "1" else 0)
    present_counts = present_mat.sum(axis=1)
    absent_counts = 4 - present_counts
    pct = (present_counts / 4 * 100).clip(upper=100).round(1)

    return pd.DataFrame({
        "Name": df.get("Name", ""),
        "Surname": df.get("Surname", ""),
        "Barcode": df.get("Barcode", ""),
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
    }).sort_values(by=["Attendance %", "Name", "Surname"], ascending=[False, True, True]).reset_index(drop=True)

def unique_sorted(series):
    return ["(All)"] + sorted(v for v in series.astype(str).unique() if v.strip() and v != "nan")

# --- Streamlit UI Config ---
st.set_page_config("Tutor Class Attendance Register 2025", "✅", layout="wide")

st.markdown("""
    <style>
    .app-title {font-size: 30px; font-weight: 800; margin-bottom: 0.25rem;}
    .app-sub {color: #666; margin-top: 0;}
    .stat-card {padding: 12px 16px; border: 1px solid #eee; border-radius: 12px;}
    </style>
""", unsafe_allow_html=True)

left, right = st.columns([3, 2])
with left:
    st.markdown('<div class="app-title">✅ Tutor Class Attendance Register 2025</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="app-sub">Today: <b>{today_col_label()}</b></p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Settings")
    csv_path = Path(st.text_input("CSV file path", CSV_DEFAULT)).expanduser()

tabs = st.tabs(["📷 Scan", "📅 Today", "📚 History", "📈 Tracking", "🛠 Manage"])

# ... 👇 Continue with tabs[0] to tabs[4] same as in your code, just change compute_tracking usage and displayed columns accordingly
# Inside Tracking tab:

with tabs[3]:
    st.subheader("Tracking (per student)")
    if not csv_path.exists():
        st.info("CSV not found.")
    else:
        df = load_sheet(csv_path)
        date_cols = get_date_columns(df)
        if not date_cols:
            st.info("No attendance dates yet.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            grade_sel = fc1.selectbox("Filter by Grade", unique_sorted(df["Grade"]) if "Grade" in df.columns else ["(All)"])
            area_sel = fc2.selectbox("Filter by Area", unique_sorted(df["Area"]) if "Area" in df.columns else ["(All)"])
            search = fc3.text_input("Search name/barcode")

            subset = df.copy()
            if grade_sel != "(All)":
                subset = subset[subset["Grade"].astype(str) == str(grade_sel)]
            if area_sel != "(All)":
                subset = subset[subset["Area"].astype(str) == str(area_sel)]
            if search.strip():
                q = search.lower().strip()
                subset = subset[subset.apply(lambda r: q in str(r.get("Name","")).lower() or q in str(r.get("Surname","")).lower() or q in str(r.get("Barcode","")).lower(), axis=1)]

            metrics = compute_tracking(subset)
            st.write(f"Total learners: **{len(metrics)}**  |  Sessions counted: **{min(len(date_cols), 4)}**")
            st.dataframe(metrics[["Name", "Surname", "Barcode", "Present", "Absent", "Attendance %"]], use_container_width=True, height=480)

            if not metrics.empty:
                st.download_button(
                    "Download tracking report (CSV)",
                    data=metrics.to_csv(index=False).encode("utf-8"),
                    file_name="attendance_tracking_report.csv",
                    mime="text/csv",
                    use_container_width=True
                )
