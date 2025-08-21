import streamlit as st
import pandas as pd
from datetime import datetime
import os

# Title
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.title("📚 Tutor Class Attendance Register 2025")

# Initialize session state
if "scan_id" not in st.session_state:
    st.session_state.scan_id = ""

# Load CSV
csv_file_path = st.sidebar.text_input("CSV file path", "attendance_clean.csv")

@st.cache_data
def load_data(path):
    if os.path.exists(path):
        return pd.read_csv(path)
    else:
        st.warning("CSV file not found.")
        return pd.DataFrame()

df = load_data(csv_file_path)

# Auto-detect attendance columns (dates)
attendance_columns = [col for col in df.columns if "-" in col]

# === Tabs ===
tab1, tab2, tab3, tab4 = st.tabs(["📷 Scan", "🗓️ Today", "📊 Tracking", "🛠️ Manage"])

# ============ TAB 1: Scan ============
with tab1:
    st.subheader("📷 Scan Student ID")

    scanned_id = st.text_input("Scan or enter student ID", st.session_state.scan_id)
    if st.button("Mark Present"):
        today = datetime.today().strftime('%-d-%b')
        if today not in df.columns:
            df[today] = ""
        if scanned_id in df['Student ID'].astype(str).values:
            df.loc[df['Student ID'].astype(str) == scanned_id, today] = "Present"
            st.success(f"✅ {df.loc[df['Student ID'].astype(str) == scanned_id, 'Name'].values[0]} marked PRESENT.")
            df.to_csv(csv_file_path, index=False)
        else:
            st.error("❌ Student ID not found.")

# ============ TAB 2: Today ============
with tab2:
    st.subheader("🗓️ Today's Attendance")
    today = datetime.today().strftime('%-d-%b')
    if today not in df.columns:
        df[today] = ""
    present_today = df[df[today] == "Present"]
    st.metric("✅ Present", len(present_today))
    st.metric("❌ Absent", len(df) - len(present_today))
    st.dataframe(present_today[['Student ID', 'Name', today]])

# ============ TAB 3: Tracking ============
with tab3:
    st.subheader("📊 Attendance Tracking Summary")
    month = datetime.today().strftime('%b')
    monthly_cols = [col for col in attendance_columns if month in col]
    if monthly_cols:
        df['Attendance %'] = df[monthly_cols].apply(lambda row: round((row == 'Present').sum() / len(monthly_cols) * 100, 2), axis=1)
        grade_attendance = df.groupby('Grade')['Attendance %'].mean().round(2).reset_index()
        st.dataframe(df[['Student ID', 'Name', 'Grade', 'Attendance %']])
        st.bar_chart(grade_attendance.set_index('Grade'))

# ============ TAB 4: Manage ============
with tab4:
    st.subheader("🛠️ Manage Student Records")

    if st.checkbox("Add New Student"):
        with st.form("AddStudent"):
            new_id = st.text_input("Student ID")
            new_name = st.text_input("Name")
            new_grade = st.selectbox("Grade", [5, 6, 7])
            submitted = st.form_submit_button("Add")
            if submitted:
                if new_id in df['Student ID'].astype(str).values:
                    st.warning("Student ID already exists.")
                else:
                    new_row = {'Student ID': new_id, 'Name': new_name, 'Grade': new_grade}
                    for col in attendance_columns:
                        new_row[col] = ""
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    df.to_csv(csv_file_path, index=False)
                    st.success("Student added.")

    if st.checkbox("Delete Student"):
        student_to_delete = st.selectbox("Select Student", df['Name'])
        if st.button("Delete"):
            df = df[df['Name'] != student_to_delete]
            df.to_csv(csv_file_path, index=False)
            st.success("Student deleted.")

    if st.checkbox("Edit Student"):
        edit_id = st.selectbox("Select Student ID", df['Student ID'].astype(str))
        selected = df[df['Student ID'].astype(str) == edit_id]
        if not selected.empty:
            with st.form("EditStudent"):
                new_name = st.text_input("New Name", selected['Name'].values[0])
                new_grade = st.selectbox("New Grade", [5, 6, 7], index=[5, 6, 7].index(int(selected['Grade'].values[0])))
                submitted = st.form_submit_button("Update")
                if submitted:
                    df.loc[df['Student ID'].astype(str) == edit_id, 'Name'] = new_name
                    df.loc[df['Student ID'].astype(str) == edit_id, 'Grade'] = new_grade
                    df.to_csv(csv_file_path, index=False)
                    st.success("Student updated.")
