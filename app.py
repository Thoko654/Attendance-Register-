import streamlit as st
import pandas as pd
from datetime import datetime
import os

# =========================
# Config & Constants
# =========================
st.set_page_config(page_title="📸 Student Attendance Register", layout="centered")
STUDENT_FILE = "Student_records.csv"
ATTENDANCE_FILE = "Attendance_log.csv"
TODAY = datetime.today().strftime('%Y-%m-%d')

# =========================
# Load Student Records
# =========================
def load_students():
    if os.path.exists(STUDENT_FILE):
        return pd.read_csv(STUDENT_FILE, dtype=str)
    else:
        st.error(f"❌ File '{STUDENT_FILE}' not found.")
        return pd.DataFrame()

def save_attendance_log(df):
    df.to_csv(ATTENDANCE_FILE, index=False)

# =========================
# Attendance Logging
# =========================
def mark_attendance(student_id):
    if student_id not in students['Student ID'].values:
        st.warning("⚠️ Student not found!")
        return
    
    name = students.loc[students['Student ID'] == student_id, 'Name'].values[0]
    grade = students.loc[students['Student ID'] == student_id, 'Grade'].values[0]
    
    # Check if already marked today
    if not attendance_df[(attendance_df['Student ID'] == student_id) & (attendance_df['Date'] == TODAY)].empty:
        st.info("✅ Already marked present today.")
    else:
        new_row = pd.DataFrame([{
            'Student ID': student_id,
            'Name': name,
            'Grade': grade,
            'Date': TODAY,
            'Status': 'Present'
        }])
        updated_df = pd.concat([attendance_df, new_row], ignore_index=True)
        save_attendance_log(updated_df)
        st.success(f"🟢 {name} marked present!")

# =========================
# Load Attendance Log
# =========================
def load_attendance_log():
    if os.path.exists(ATTENDANCE_FILE):
        return pd.read_csv(ATTENDANCE_FILE, dtype=str)
    else:
        return pd.DataFrame(columns=['Student ID', 'Name', 'Grade', 'Date', 'Status'])

# =========================
# Calculate Attendance Summary
# =========================
def calculate_summary():
    df = attendance_df.copy()
    df['Date'] = pd.to_datetime(df['Date'])
    df = df[df['Status'] == 'Present']

    # Monthly Attendance per student
    this_month = df[df['Date'].dt.strftime('%Y-%m') == datetime.today().strftime('%Y-%m')]
    student_summary = this_month.groupby(['Student ID', 'Name', 'Grade']).size().reset_index(name='Days Present')
    student_summary['Attendance %'] = (student_summary['Days Present'] / df['Date'].dt.day.max()) * 100

    # Grade attendance
    grade_summary = student_summary.groupby('Grade').agg({'Student ID': 'count', 'Days Present': 'sum'}).reset_index()
    grade_summary['Attendance %'] = (grade_summary['Days Present'] / (20 * df['Date'].dt.day.max())) * 100

    return student_summary, grade_summary

# =========================
# App UI
# =========================
st.title("📸 Student Attendance Register")

students = load_students()
attendance_df = load_attendance_log()

st.subheader("✨ Scan or Enter Barcode Below")
barcode = st.text_input("📷 Scan/Enter Student Barcode", key="barcode_input")

if barcode:
    mark_attendance(barcode.strip())
    st.experimental_rerun()

with st.expander("📊 Show Full Attendance Table"):
    st.dataframe(attendance_df.sort_values(by="Date", ascending=False), use_container_width=True)

# =========================
# Attendance Summary
# =========================
st.subheader("📈 Attendance Analytics")

if not attendance_df.empty:
    student_summary, grade_summary = calculate_summary()
    
    st.markdown("#### 👨‍🎓 Monthly Attendance per Student")
    st.dataframe(student_summary, use_container_width=True)

    st.markdown("#### 🏫 Grade-wise Attendance Percentage")
    st.dataframe(grade_summary, use_container_width=True)
else:
    st.info("📌 No attendance data available yet.")

