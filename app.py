import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path

# ---------- CONFIG ----------
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
CSV_FILE = "attendance_clean.csv"

# ---------- HELPERS ----------
def today_label():
    return datetime.now().strftime("%d-%b")

def load_data(file_path=CSV_FILE):
    path = Path(file_path)
    if path.exists():
        df = pd.read_csv(path, dtype=str).fillna("")
    else:
        df = pd.DataFrame()
    return df

def save_data(df, file_path=CSV_FILE):
    df.to_csv(file_path, index=False)

def ensure_today_column(df):
    today = today_label()
    if today not in df.columns:
        df[today] = ""
    return today

def normalize_code(code):
    return str(code).strip().lstrip("0") or "0"

def label_row(row):
    return f"{row.get('Name','')} {row.get('Surname','')}"

def get_date_columns(df):
    cols = []
    for c in df.columns:
        parts = c.split("-")
        if len(parts) == 2 and parts[0].isdigit():
            cols.append(c)
    return sorted(cols, key=lambda x: datetime.strptime(x, "%d-%b").timetuple().tm_yday)

# ---------- MARKING ----------
def mark_present(barcode, df):
    barcode = normalize_code(barcode)
    today = ensure_today_column(df)
    match = df[df['Barcode'].apply(normalize_code) == barcode]
    if match.empty:
        return False, "❌ Barcode not found in register."
    
    index = match.index[0]
    name = label_row(df.loc[index])
    if df.at[index, today] == "1":
        return False, f"ℹ️ {name} already marked present today."
    df.at[index, today] = "1"
    save_data(df)
    return True, f"✅ {name} marked PRESENT for {today}."

# ---------- FILE UPLOAD ----------
with st.sidebar:
    st.header("📁 Upload attendance register CSV file")
    uploaded = st.file_uploader("Upload attendance register", type=["csv"])
    if uploaded:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
        save_data(df)
        st.success("✅ File uploaded and loaded successfully!")

# ---------- LOAD CSV ----------
df = load_data()
today = today_label()
if not df.empty:
    ensure_today_column(df)

# ---------- PAGE TITLE ----------
st.markdown(f"<h1>✅ Tutor Class Attendance Register 2025</h1>", unsafe_allow_html=True)
st.markdown(f"Today: <b>{today}</b>", unsafe_allow_html=True)

# ---------- TABS ----------
tabs = st.tabs(["📷 Scan", "📅 Today", "📚 History", "📈 Tracking", "🛠 Manage"])

# ---------- SCAN ----------
with tabs[0]:
    st.subheader("📷 Scan Attendance")
    barcode = st.text_input("Scan Barcode:", key="scan_input", label_visibility="collapsed")
    if st.button("Mark Present"):
        if barcode:
            success, msg = mark_present(barcode, df)
            st.success(msg) if success else st.error(msg)

# ---------- TODAY ----------
with tabs[1]:
    st.subheader(f"📅 Attendance for Today: {today}")
    if today not in df.columns:
        st.warning("No attendance marked for today yet.")
    else:
        present = df[df[today] == "1"]
        absent = df[df[today] != "1"]
        total = len(present) + len(absent)

        st.write(f"**Registered:** {total}  |  **Present:** {len(present)}  |  **Absent:** {len(absent)}")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Present")
            st.dataframe(present[["Name", "Surname", "Barcode", today]], use_container_width=True)
        with c2:
            st.markdown("#### Absent")
            st.dataframe(absent[["Name", "Surname", "Barcode"]], use_container_width=True)

# ---------- HISTORY ----------
with tabs[2]:
    st.subheader("📚 History")
    dates = get_date_columns(df)
    if dates:
        selected = st.selectbox("Select date", reversed(dates))
        hist_present = df[df[selected] == "1"]
        hist_absent = df[df[selected] != "1"]
        st.write(f"**Present:** {len(hist_present)} | **Absent:** {len(hist_absent)}")

        st.dataframe(df[["Name", "Surname", "Barcode", selected]], use_container_width=True)
    else:
        st.info("No attendance history found.")

# ---------- TRACKING ----------
with tabs[3]:
    st.subheader("📈 Tracking (per student)")
    dates = get_date_columns(df)
    if not dates:
        st.info("No sessions found yet.")
    else:
        present_matrix = df[dates].applymap(lambda x: 1 if x.strip() == "1" else 0)
        df["Sessions"] = len(dates)
        df["Present"] = present_matrix.sum(axis=1)
        df["Absent"] = df["Sessions"] - df["Present"]
        df["Attendance %"] = (df["Present"] / df["Sessions"] * 100).round(1)

        # Last Present Date
        def last_present(row):
            indexes = [i for i, v in enumerate(row) if v == 1]
            return dates[max(indexes)] if indexes else "—"

        df["Last present"] = present_matrix.apply(last_present, axis=1)

        # Streaks
        def streaks(row):
            lst = row.tolist()
            longest = cur = 0
            for v in lst:
                if v == 1:
                    cur += 1
                    longest = max(longest, cur)
                else:
                    cur = 0
            current = 0
            for v in reversed(lst):
                if v == 1:
                    current += 1
                else:
                    break
            return pd.Series([current, longest])
        
        df[["Current streak", "Longest streak"]] = present_matrix.apply(streaks, axis=1)

        st.dataframe(df[["Name", "Surname", "Barcode", "Sessions", "Present", "Absent",
                         "Attendance %", "Last present", "Current streak", "Longest streak"]],
                     use_container_width=True)

# ---------- MANAGE ----------
with tabs[4]:
    st.subheader("🛠 Manage Learners / Barcodes")

    with st.expander("🔍 Search Learners"):
        search = st.text_input("Search by name, surname or barcode")
        if search:
            search_lower = search.lower().strip()
            filtered = df[df.apply(lambda row: search_lower in str(row["Name"]).lower() 
                                   or search_lower in str(row["Surname"]).lower()
                                   or search_lower in str(row["Barcode"]).lower(), axis=1)]
            st.dataframe(filtered[["Name", "Surname", "Barcode"]], use_container_width=True)
        else:
            st.dataframe(df[["Name", "Surname", "Barcode"]], use_container_width=True)

    st.markdown("---")
    st.markdown("### ✍️ Assign Barcode")
    col1, col2, col3 = st.columns(3)
    with col1:
        name = st.text_input("Name")
    with col2:
        surname = st.text_input("Surname")
    with col3:
        barcode = st.text_input("Barcode")

    if st.button("Save Barcode"):
        mask = (df["Name"].str.strip().str.lower() == name.strip().lower()) & \
               (df["Surname"].str.strip().str.lower() == surname.strip().lower())
        idx = df.index[mask]
        if idx.any():
            df.loc[idx, "Barcode"] = barcode
            save_data(df)
            st.success("✅ Barcode saved!")
        else:
            st.error("❌ Learner not found.")

    st.markdown("---")
    new_col = st.text_input("Add new date column (e.g. 25-Aug)")
    if st.button("Add Date"):
        if new_col.strip():
            df[new_col] = ""
            save_data(df)
            st.success(f"✅ Added new column: {new_col}")
