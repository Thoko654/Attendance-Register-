import streamlit as st
import pandas as pd
import datetime

st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

st.title("📚 Tutor Class Attendance Register 2025")

# File uploader / CSV path
csv_file = st.sidebar.text_input("CSV file path", value="attendance_clean.csv")

# Load data
@st.cache_data
def load_data(file_path):
    df = pd.read_csv(file_path)
    df.fillna("", inplace=True)
    return df

try:
    df = load_data(csv_file)
except FileNotFoundError:
    st.error("CSV file not found. Please check the file path.")
    st.stop()

# Get today's column name
today = datetime.datetime.today().strftime('%-d-%b')  # e.g. '21-Aug'

# Ensure today's column exists
if today not in df.columns:
    df[today] = ""  # Add blank column for today

# 🧪 Scan Tab (auto-mark present using barcode or dropdown)
def scan_tab():
    st.subheader("🔍 Scan Student")
    student_id = st.text_input("Scan or Enter Student ID").strip()
    if st.button("Mark Present"):
        if student_id in df['Student ID'].astype(str).values:
            df.loc[df['Student ID'].astype(str) == student_id, today] = "Present"
            df.to_csv(csv_file, index=False)
            st.success(f"Attendance marked for ID: {student_id}")
        else:
            st.error("Student ID not found.")

# 📆 Today Tab (view today's attendance)
def today_tab():
    st.subheader("📅 Today's Attendance")
    if today in df.columns:
        present_today = df[df[today] == "Present"]
        if not present_today.empty:
            st.dataframe(present_today[['Student ID', 'Name', today]])
        else:
            st.info("No attendance marked for today yet.")
    else:
        st.warning(f"Column for today ({today}) is missing.")

# 📊 Tracking Tab
def tracking_tab():
    st.subheader("📊 Attendance Tracking")
    weekly_cols = [col for col in df.columns if "-" in col and col not in ['Student ID', 'Name', 'Grade']]
    tracking_data = df[['Student ID', 'Name', 'Grade'] + weekly_cols].copy()

    for col in weekly_cols:
        tracking_data[col] = tracking_data[col].apply(lambda x: 1 if x == "Present" else 0)

    tracking_data['Total'] = tracking_data[weekly_cols].sum(axis=1)
    tracking_data['% Attendance'] = (tracking_data['Total'] / len(weekly_cols) * 100).round(1)
    st.dataframe(tracking_data[['Student ID', 'Name', 'Grade', '% Attendance']])

# ⚙️ Manage Tab (manual editing)
def manage_tab():
    st.subheader("🛠️ Manage Students")
    st.dataframe(df)

# Main tab layout
tabs = st.tabs(["Scan", "Today", "Tracking", "Manage"])
with tabs[0]:
    scan_tab()
with tabs[1]:
    today_tab()
with tabs[2]:
    tracking_tab()
with tabs[3]:
    manage_tab()
