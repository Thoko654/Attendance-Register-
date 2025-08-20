import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

# ================================
# 📥 Upload and Load CSV
# ================================
st.title("📋 Tutor Class Attendance Register 2025")

uploaded_file = st.file_uploader("📁 Upload attendance register CSV file", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.success("✅ File uploaded and loaded successfully!")
    
    # Identify the date columns automatically (e.g. '7-Jun', '14-Jun' etc.)
    date_columns = [col for col in df.columns if '-' in col and any(char.isdigit() for char in col)]
    
    # ================================
    # ✏️ Edit Attendance
    # ================================
    st.header("📊 Attendance Data")
    edited_df = st.data_editor(df, num_rows="dynamic", key="attendance_editor")

    # ================================
    # 📷 Scan Barcode to Mark Attendance
    # ================================
    st.subheader("📸 Scan Student ID to Mark as Present")
    scanned_id = st.text_input("Scan or Enter Student ID Number")

    if scanned_id:
        today = datetime.today().strftime('%-d-%b')
        if today not in edited_df.columns:
            edited_df[today] = ""
        matched_rows = edited_df['ID'].astype(str) == scanned_id
        if matched_rows.any():
            edited_df.loc[matched_rows, today] = "Present"
            st.success(f"✅ Student ID {scanned_id} marked as Present for {today}")
        else:
            st.warning(f"⚠️ Student ID {scanned_id} not found.")

    # ================================
    # 📈 Monthly Attendance Summary
    # ================================
    st.header("📅 Monthly Attendance % Per Student")
    if date_columns:
        attendance_percent = edited_df[date_columns].apply(lambda row: (row == 'Present').sum() / len(date_columns) * 100, axis=1)
        edited_df["Monthly %"] = attendance_percent.round(2)
        st.dataframe(edited_df[["ID", "Name", "Surname", "Grade", "Monthly %"]])

    # ================================
    # 🧮 Grade-wise Attendance Analysis
    # ================================
    st.header("🎓 Grade-wise Attendance Summary")
    if 'Grade' in edited_df.columns:
        grade_summary = edited_df.groupby("Grade")["Monthly %"].mean().reset_index()
        grade_summary.rename(columns={"Monthly %": "Average Attendance %"}, inplace=True)
        st.dataframe(grade_summary)

    # ================================
    # 💾 Save Edited CSV
    # ================================
    st.download_button(
        label="💾 Download Updated CSV",
        data=edited_df.to_csv(index=False).encode('utf-8'),
        file_name="Updated_Attendance.csv",
        mime="text/csv"
    )
else:
    st.info("📌 Please upload a CSV file to begin.")
