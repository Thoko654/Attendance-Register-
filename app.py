import streamlit as st
import pandas as pd
import datetime

st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

st.markdown("## ✅ Tutor Class Attendance Register 2025")
today = datetime.date.today()
st.markdown(f"Today: **{today.strftime('%d-%b')}**")

# Session state keys
if "df" not in st.session_state:
    st.session_state.df = None
if "file_name" not in st.session_state:
    st.session_state.file_name = None

# CSV Upload
st.sidebar.header("📁 Upload attendance register CSV file")
uploaded_file = st.sidebar.file_uploader("Upload attendance register", type="csv")

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file)
        st.session_state.df = df.copy()
        st.session_state.file_name = uploaded_file.name
        st.success("✅ File uploaded and loaded successfully!")
    except Exception as e:
        st.error(f"❌ Error loading CSV file: {e}")

# Main tabs
if st.session_state.df is not None:
    df = st.session_state.df
    tabs = st.tabs(["📷 Scan", "📅 Today", "📖 History", "📊 Tracking", "🛠️ Manage"])

    # --- SCAN TAB ---
    with tabs[0]:
        st.subheader("📷 Scan Attendance")
        barcode = st.text_input("Scan barcode here:")
        if st.button("Mark Present"):
            match = df[df['Barcode'] == barcode]
            if not match.empty:
                df.at[match.index[0], today.strftime("%-d-%b")] = "Present"
                st.success(f"{match.iloc[0]['Name']} marked as Present.")
            else:
                st.error("❌ Student not found.")

    # --- TODAY TAB ---
    with tabs[1]:
        st.subheader(f"📅 Attendance for Today: {today.strftime('%d-%b')}")
        date_col = today.strftime("%-d-%b")
        if date_col in df.columns:
            present_df = df[df[date_col] == "Present"]
            absent_df = df[df[date_col] != "Present"]
            col1, col2 = st.columns(2)
            with col1:
                st.success(f"🟢 Present: {len(present_df)}")
                st.dataframe(present_df[['Name', 'Surname', 'Grade', 'Barcode']])
            with col2:
                st.error(f"🔴 Absent: {len(absent_df)}")
                st.dataframe(absent_df[['Name', 'Surname', 'Grade', 'Barcode']])
        else:
            st.warning("No attendance marked for today yet.")

    # --- HISTORY TAB ---
    with tabs[2]:
        st.subheader("📖 Attendance History")
        attendance_cols = [col for col in df.columns if "-" in col]
        selected_date = st.selectbox("Select a date to view:", attendance_cols[::-1])
        if selected_date:
            present = df[df[selected_date] == "Present"]
            absent = df[df[selected_date] != "Present"]
            st.markdown(f"#### 🟢 Present ({len(present)})")
            st.dataframe(present[['Name', 'Surname', 'Grade', 'Barcode']])
            st.markdown(f"#### 🔴 Absent ({len(absent)})")
            st.dataframe(absent[['Name', 'Surname', 'Grade', 'Barcode']])

    # --- TRACKING TAB ---
    with tabs[3]:
        st.subheader("📊 Attendance Tracking")
        attendance_cols = [col for col in df.columns if "-" in col]
        if not attendance_cols:
            st.warning("No attendance data available.")
        else:
            tracking = df[['Name', 'Surname', 'Barcode']].copy()
            tracking["Present"] = df[attendance_cols].apply(lambda x: (x == "Present").sum(), axis=1)
            tracking["Absent"] = df[attendance_cols].apply(lambda x: (x != "Present").sum(), axis=1)
            tracking["Attendance %"] = (tracking["Present"] / (tracking["Present"] + tracking["Absent"])) * 100
            tracking["Attendance %"] = tracking["Attendance %"].round(1)
            tracking["Last present"] = df[attendance_cols].apply(
                lambda row: next((col for col in reversed(attendance_cols) if row[col] == "Present"), "N/A"), axis=1)
            st.dataframe(tracking)

    # --- MANAGE TAB ---
    with tabs[4]:
        st.subheader("🛠️ Manage Student List")
        editable_cols = ['Name', 'Surname', 'Barcode', 'Grade', 'Area']
        try:
            edited_df = st.data_editor(df[editable_cols], num_rows="dynamic", key="editable_students")
            for col in editable_cols:
                df[col] = edited_df[col]
        except Exception as e:
            st.error(f"Error editing data: {e}")

        st.markdown("### ➕ Add or Update Barcode")
        new_barcode = st.text_input("Enter barcode")
        student_name = st.text_input("Student name to update barcode for")
        if st.button("Update Barcode"):
            match = df[df['Name'].str.lower() == student_name.lower()]
            if not match.empty:
                df.at[match.index[0], 'Barcode'] = new_barcode
                st.success(f"Updated barcode for {student_name}")
            else:
                st.error("Student not found")

        # Add today's column if missing
        if today.strftime("%-d-%b") not in df.columns:
            df[today.strftime("%-d-%b")] = ""

    # Update session state
    st.session_state.df = df

else:
    st.info("📤 Please upload the attendance CSV file to begin.")
