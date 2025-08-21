import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.title("📚 Tutor Class Attendance Register 2025")

attendance_path = "Attendance.csv"
today = datetime.today().strftime('%-d-%b')  # e.g., 21-Aug

# --- HELPER FUNCTIONS ---
def load_data():
    if os.path.exists(attendance_path):
        return pd.read_csv(attendance_path)
    else:
        return pd.DataFrame(columns=["ID", "Name", "Grade"])

def save_data(df):
    df.to_csv(attendance_path, index=False)

def mark_present(df, student_id):
    if today not in df.columns:
        df[today] = ""
    df.loc[df['ID'] == student_id, today] = "Present"
    return df

# --- LOAD DATA ---
df = load_data()

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📷 Scan", "📅 Today", "📊 Tracking", "🛠️ Manage"])

# --- TAB 1: SCAN ---
with tab1:
    st.header("📷 Scan to Mark Attendance")
    scanned_id = st.text_input("Scan or Enter Student ID")

    if scanned_id:
        if scanned_id in df["ID"].astype(str).values:
            df = mark_present(df, scanned_id)
            save_data(df)
            st.success(f"Marked Present for ID: {scanned_id}")
        else:
            st.error("Student ID not found.")

# --- TAB 2: TODAY ---
with tab2:
    st.header(f"📅 Attendance for Today ({today})")
    if today in df.columns:
        present_students = df[df[today] == "Present"][["ID", "Name", "Grade"]]
        st.metric("✅ Present Today", len(present_students))
        st.dataframe(present_students)
    else:
        st.warning(f"No attendance has been recorded yet for today ({today}).")

# --- TAB 3: TRACKING ---
with tab3:
    st.header("📊 Attendance Tracking Summary")

    if df.empty:
        st.info("No attendance data yet.")
    else:
        attendance_columns = df.columns[3:]
        df['Total'] = (df[attendance_columns] == "Present").sum(axis=1)
        df['Possible'] = len(attendance_columns)
        df['% Attendance'] = (df['Total'] / df['Possible'] * 100).fillna(0).round(1)
        st.dataframe(df[["ID", "Name", "Grade", "% Attendance"]])

        st.subheader("🎯 Grade Level Attendance")
        grade_summary = df.groupby("Grade")["% Attendance"].mean().round(1).reset_index()
        st.dataframe(grade_summary.rename(columns={"% Attendance": "Avg Attendance %"}))

# --- TAB 4: MANAGE ---
with tab4:
    st.header("🛠️ Manage Students & Attendance")

    manage_option = st.selectbox("Choose Action", ["Add Student", "Delete Student", "Edit Attendance"])

    if manage_option == "Add Student":
        with st.form("add_form"):
            new_id = st.text_input("Student ID")
            new_name = st.text_input("Name")
            new_grade = st.selectbox("Grade", ["5", "6", "7"])
            submitted = st.form_submit_button("Add Student")
            if submitted:
                if new_id in df["ID"].astype(str).values:
                    st.error("Student ID already exists.")
                else:
                    df.loc[len(df)] = [new_id, new_name, new_grade] + [""] * (len(df.columns) - 3)
                    save_data(df)
                    st.success("Student added.")

    elif manage_option == "Delete Student":
        delete_id = st.selectbox("Select Student ID", df["ID"].astype(str))
        if st.button("Delete"):
            df = df[df["ID"].astype(str) != delete_id]
            save_data(df)
            st.success(f"Deleted Student ID: {delete_id}")

    elif manage_option == "Edit Attendance":
        if not df.empty:
            row_index = st.number_input("Enter row number to edit (starting from 0)", min_value=0, max_value=len(df) - 1, step=1)
            if st.button("Clear Attendance"):
                df.iloc[row_index, 3:] = ""
                save_data(df)
                st.success("Attendance cleared for selected row.")
            st.dataframe(df.iloc[[row_index]])
        else:
            st.warning("No data to edit.")
