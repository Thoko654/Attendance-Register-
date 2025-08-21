import streamlit as st
import pandas as pd
import datetime
import os

DATA_PATH = 'attendance_data.csv'

def load_data():
    if os.path.exists(DATA_PATH):
        return pd.read_csv(DATA_PATH)
    else:
        return pd.DataFrame(columns=["Name", "Surname", "Barcode", "Grade", "Area"])

def save_data(df):
    df.to_csv(DATA_PATH, index=False)

def get_today_col():
    today = datetime.datetime.now().strftime('%-d-%b')
    return today

def mark_attendance(barcode):
    df = load_data()
    today_col = get_today_col()

    if today_col not in df.columns:
        df[today_col] = ""

    if barcode in df['Barcode'].values:
        df.loc[df['Barcode'] == barcode, today_col] = "Present"
        save_data(df)
        student = df[df['Barcode'] == barcode].iloc[0]
        return f"✅ Marked Present: {student['Name']} {student['Surname']}"
    else:
        return "❌ Student not found."

def calculate_attendance(df):
    attendance_cols = [col for col in df.columns if '-' in col]
    present_count = df[attendance_cols].apply(lambda row: (row == 'Present').sum(), axis=1)
    total_sessions = len(attendance_cols)
    attendance_percent = (present_count / total_sessions * 100).round(2) if total_sessions > 0 else 0
    last_present = df[attendance_cols].apply(lambda row: row[row == 'Present'].last_valid_index(), axis=1)
    df['Present'] = present_count
    df['Absent'] = total_sessions - present_count
    df['Attendance %'] = attendance_percent
    df['Last present'] = last_present
    return df

st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.markdown("## ✅ Tutor Class Attendance Register 2025")
st.write(f"Today: **{get_today_col()}**")

tabs = st.tabs(["📷 Scan", "📅 Today", "📜 History", "📊 Tracking", "🛠️ Manage"])

# 📷 Scan Tab
with tabs[0]:
    st.subheader("📷 Scan Student Barcode")
    barcode = st.text_input("Scan or Enter Student Barcode")
    if barcode:
        message = mark_attendance(barcode.strip())
        st.success(message)

# 📅 Today Tab
with tabs[1]:
    st.subheader("📅 Today’s Attendance")
    df = load_data()
    today_col = get_today_col()
    if today_col not in df.columns:
        df[today_col] = ""
    st.dataframe(df[["Name", "Surname", "Grade", "Area", "Barcode", today_col]])

# 📜 History Tab
with tabs[2]:
    st.subheader("📜 Attendance History")
    df = load_data()
    editable_df = st.data_editor(df, num_rows="dynamic", key="history_edit")
    if st.button("💾 Save History Changes"):
        save_data(editable_df)
        st.success("✅ Changes saved!")

# 📊 Tracking Tab
with tabs[3]:
    st.subheader("📊 Attendance Tracking")
    df = load_data()
    df = calculate_attendance(df)
    display_df = df[["Name", "Surname", "Barcode", "Present", "Absent", "Attendance %", "Last present"]]
    st.dataframe(display_df)

# 🛠️ Manage Tab
with tabs[4]:
    st.subheader("🛠️ Manage Students")
    df = load_data()

    # Add new student
    with st.expander("➕ Add New Student"):
        with st.form("add_student_form"):
            name = st.text_input("Name")
            surname = st.text_input("Surname")
            barcode = st.text_input("Barcode")
            grade = st.selectbox("Grade", ["5", "6", "7"])
            area = st.text_input("Area")
            submitted = st.form_submit_button("Add Student")
            if submitted:
                new_student = pd.DataFrame([[name, surname, barcode, grade, area]], columns=["Name", "Surname", "Barcode", "Grade", "Area"])
                updated_df = pd.concat([df, new_student], ignore_index=True)
                save_data(updated_df)
                st.success(f"✅ {name} {surname} added.")

    # Delete student
    with st.expander("🗑️ Delete Student"):
        barcodes = df['Barcode'].tolist()
        selected_barcode = st.selectbox("Select Barcode", barcodes)
        if st.button("Delete"):
            updated_df = df[df['Barcode'] != selected_barcode]
            save_data(updated_df)
            st.success("✅ Student deleted.")

    # Edit student data
    with st.expander("✏️ Edit Student Details"):
        row_index = st.number_input("Enter row number to edit (starting from 0)", min_value=0, max_value=len(df) - 1, step=1)
        selected_row = df.iloc[row_index]
        name = st.text_input("Name", value=selected_row["Name"], key="edit_name")
        surname = st.text_input("Surname", value=selected_row["Surname"], key="edit_surname")
        barcode = st.text_input("Barcode", value=selected_row["Barcode"], key="edit_barcode")
        grade = st.text_input("Grade", value=str(selected_row["Grade"]), key="edit_grade")
        area = st.text_input("Area", value=selected_row["Area"], key="edit_area")
        if st.button("Save edits"):
            df.at[row_index, "Name"] = name
            df.at[row_index, "Surname"] = surname
            df.at[row_index, "Barcode"] = barcode
            df.at[row_index, "Grade"] = grade
            df.at[row_index, "Area"] = area
            save_data(df)
            st.success("✅ Changes saved!")

