import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

# 📍 CSV file path
csv_path = "Student_Attendance.csv"

# 📥 Load sheet
@st.cache_data
def load_sheet():
    return pd.read_csv(csv_path, dtype=str).fillna("")

# 💾 Save sheet
def save_sheet(df, path):
    df.to_csv(path, index=False)

# ✅ Mark present
def mark_present(barcode, path):
    df = load_sheet()
    today = datetime.now().strftime("%-d-%b")
    if today not in df.columns:
        df[today] = ""
    match = df["Barcode"] == barcode
    if match.any():
        df.loc[match, today] = "1"
        save_sheet(df, path)
        return True, f"✅ Marked: {df.loc[match, 'Name'].values[0]} {df.loc[match, 'Surname'].values[0]}"
    else:
        return False, "❌ Barcode not found"

# 🧾 Load base data
df = load_sheet()
today_col = datetime.now().strftime("%-d-%b")

# ============ APP INTERFACE ============ #
tabs = st.tabs(["📅 Today", "📷 Scan", "📈 Tracking", "🕓 History"])

# --------------------------------------- #
# 📅 TODAY TAB
# --------------------------------------- #
with tabs[0]:
    st.markdown("## 📅 Today's Attendance")
    if today_col not in df.columns:
        df[today_col] = ""
    present = df[df[today_col] == "1"]
    absent = df[df[today_col] != "1"]

    st.metric("✅ Present", len(present))
    st.metric("❌ Absent", len(absent))

    # 🧮 Attendance by Grade %
    st.markdown("### 📊 Attendance % by Grade (Expected: 20 learners)")
    if "Grade" in df.columns:
        grade_counts = df.groupby("Grade")[today_col].apply(lambda x: (x == "1").sum())
        for grade, count in grade_counts.items():
            pct = round((count / 20) * 100, 1)
            st.markdown(f"- **Grade {grade}**: {count}/20 present — {pct}%")

    # 👀 Show students
    with st.expander("📖 Full Class List"):
        st.dataframe(df[["Barcode", "Name", "Surname", today_col]], use_container_width=True)

# --------------------------------------- #
# 📷 SCAN TAB
# --------------------------------------- #
with tabs[1]:
    st.markdown("## 📷 Scan Barcode")
    with st.form(key="scan_form", clear_on_submit=True):
        scan = st.text_input("Scan barcode here", key="scan_box", label_visibility="collapsed")
        submitted = st.form_submit_button("Mark Present")
        if submitted and scan:
            ok, msg = mark_present(scan, csv_path)
            st.success(msg) if ok else st.error(msg)
            st.experimental_rerun()

# --------------------------------------- #
# 📈 TRACKING TAB
# --------------------------------------- #
with tabs[2]:
    st.markdown("## 📈 Attendance Tracking Summary")

    attendance_cols = [col for col in df.columns if "-" in col]
    metrics = df[["Name", "Surname", "Grade"]].copy()
    metrics["Sessions"] = len(attendance_cols)
    metrics["Present"] = df[attendance_cols].apply(lambda x: (x == "1").sum(), axis=1)
    metrics["Attendance %"] = (metrics["Present"] / metrics["Sessions"]) * 100
    metrics["Streak"] = df[attendance_cols].apply(lambda row: len(row[::-1].take_while(lambda x: x == "1")), axis=1)

    # ⚠️ Add flag for <70%
    metrics["Flag <70%"] = metrics["Attendance %"].apply(lambda x: "⚠️ Below 70%" if x < 70 else "")

    st.dataframe(metrics, use_container_width=True)

# --------------------------------------- #
# 🕓 HISTORY TAB
# --------------------------------------- #
with tabs[3]:
    st.markdown("## 🕓 Edit Attendance History")

    editable_cols = ["Barcode", "Name", "Surname"] + attendance_cols
    edited = st.experimental_data_editor(df[editable_cols], num_rows="dynamic", use_container_width=True)

    if st.button("💾 Save edits"):
        for col in editable_cols:
            df[col] = edited[col]
        save_sheet(df, csv_path)
        st.success("✅ Changes saved to file.")
