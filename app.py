import streamlit as st
import pandas as pd
from datetime import datetime

# ====================================================
# CONFIGURATION
# ====================================================
CSV_FILE = "Attendance Tracker/Student_Attendance.csv"  # Ensure this path is correct

# ====================================================
# DATA LOADING
# ====================================================
@st.cache_data
def load_data():
    return pd.read_csv(CSV_FILE)

# ====================================================
# SAVE CHANGES
# ====================================================
def save_data(df):
    df.to_csv(CSV_FILE, index=False)

# ====================================================
# APP LAYOUT
# ====================================================
st.set_page_config("📋 Tutor Class Attendance Register 2025", layout="wide")
st.title("📋 Tutor Class Attendance Register 2025")

df = load_data()

# ====================================================
# 📆 Today's Date
# ====================================================
today = datetime.now().strftime('%-d-%b')  # e.g., '20-Aug'
if today not in df.columns:
    df[today] = ""

# ====================================================
# 🎯 Barcode Scanner Input
# ====================================================
st.subheader("📷 Scan Student Barcode")
barcode = st.text_input("Scan or enter student barcode", max_chars=10)

if barcode:
    if barcode in df['Barcode'].astype(str).values:
        idx = df[df['Barcode'].astype(str) == barcode].index[0]
        df.at[idx, today] = "1"  # Mark as present
        save_data(df)
        st.success(f"✅ Marked Present: {df.at[idx, 'Name']} {df.at[idx, 'Surname']}")
    else:
        st.error("❌ Barcode not found in records.")

# ====================================================
# 🖊️ Manual Editing
# ====================================================
st.subheader("📅 Manual Attendance Edit")
edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
if st.button("💾 Save Manual Changes"):
    save_data(edited_df)
    st.success("✅ Changes saved!")

# ====================================================
# 📊 Attendance Summary
# ====================================================
st.subheader("📊 Attendance Summary")

def calculate_attendance(df):
    attendance_cols = df.columns[8:]  # Assuming first 8 columns are metadata
    df["Days Present"] = df[attendance_cols].apply(lambda row: (row == "1").sum(), axis=1)
    df["Total Days"] = len(attendance_cols)
    df["% Attendance"] = (df["Days Present"] / df["Total Days"] * 100).round(1)
    return df[["Name", "Surname", "Grade", "Area", "Days Present", "Total Days", "% Attendance"]]

summary_df = calculate_attendance(df)
st.dataframe(summary_df)

