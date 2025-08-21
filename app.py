import streamlit as st
import pandas as pd
import datetime
import base64

# ---------- CONFIGURATION ----------
CSV_PATH = "Attendance_Register.csv"
EXPECTED_PER_GRADE = 20
SATURDAYS_PER_MONTH = 4
MIN_ATTENDANCE_PERCENT = 70

# ---------- LOAD DATA ----------
@st.cache_data
def load_data():
    try:
        df = pd.read_csv(CSV_PATH)
        df['Grade'] = df['Grade'].astype(str)
        return df
    except FileNotFoundError:
        st.error("Attendance CSV file not found.")
        return pd.DataFrame()

df = load_data()

# ---------- UPDATE FUNCTIONS ----------
def mark_attendance(student_id, date):
    if date not in df.columns:
        df[date] = ''
    df.loc[df['ID'] == student_id, date] = 'Present'
    df.to_csv(CSV_PATH, index=False)

def calculate_attendance_percent(row):
    present_count = sum(1 for v in row[5:] if v == 'Present')
    total_sessions = len(row[5:])
    return round((present_count / total_sessions) * 100, 1) if total_sessions else 0

def get_grade_summary(df):
    summary = {}
    for grade in sorted(df['Grade'].unique()):
        students = df[df['Grade'] == grade]
        average = students.apply(calculate_attendance_percent, axis=1).mean()
        summary[grade] = round(average, 1)
    return summary

# ---------- TABS ----------
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
tab1, tab2, tab3, tab4 = st.tabs(["📷 Scan", "📅 Today", "📊 Tracking", "🛠 Manage"])

# ---------- SCAN TAB ----------
with tab1:
    st.header("📷 Scan to Mark Attendance")
    barcode = st.text_input("Scan or Enter Student ID")

    today = datetime.date.today().strftime('%-d-%b')  # e.g., "21-Aug"

    if barcode:
        if barcode in df['ID'].values:
            mark_attendance(barcode, today)
            student = df[df['ID'] == barcode].iloc[0]
            st.success(f"{student['Name']} marked present for {today}.")
        else:
            st.error("Student ID not found.")

# ---------- TODAY TAB ----------
with tab2:
    st.header(f"📅 Attendance for Today: {today}")

    if today not in df.columns:
        df[today] = ''

    present_students = df[df[today] == 'Present'][['ID', 'Name', 'Grade']]
    st.write(f"✅ Present Students: {len(present_students)}")
    st.dataframe(present_students, use_container_width=True)

# ---------- TRACKING TAB ----------
with tab3:
    st.header("📊 Attendance Tracking")
    tracking_df = df.copy()
    tracking_df['% Attendance'] = tracking_df.apply(calculate_attendance_percent, axis=1)
    tracking_df['Status'] = tracking_df['% Attendance'].apply(lambda x: '✔️ Met' if x >= MIN_ATTENDANCE_PERCENT else '❌ Below')
    st.dataframe(tracking_df[['ID', 'Name', 'Grade', '% Attendance', 'Status']], use_container_width=True)

    st.subheader("📈 Average Attendance per Grade")
    grade_summary = get_grade_summary(df)
    st.write(pd.DataFrame(grade_summary.items(), columns=['Grade', 'Average Attendance %']))

# ---------- MANAGE TAB ----------
with tab4:
    st.header("🛠 Manage Students & Edit Attendance")

    view = st.radio("Select view", ["Edit Attendance", "View All Students"])

    if view == "Edit Attendance":
        if not df.empty:
            row_index = st.number_input("Enter row number to edit (starting from 0)", min_value=0, max_value=len(df)-1, step=1)
            student_row = df.iloc[row_index]
            st.write(f"Editing: {student_row['Name']} (ID: {student_row['ID']})")

            dates = df.columns[5:]
            attendance_vals = []

            for date in dates:
                val = st.selectbox(f"{date}", options=['', 'Present'], index=['', 'Present'].index(student_row[date]) if student_row[date] in ['Present', ''] else 0)
                attendance_vals.append(val)

            if st.button("💾 Save Changes"):
                for idx, date in enumerate(dates):
                    df.at[row_index, date] = attendance_vals[idx]
                df.to_csv(CSV_PATH, index=False)
                st.success("Attendance updated.")
        else:
            st.warning("No student records available.")

    elif view == "View All Students":
        st.dataframe(df[['ID', 'Name', 'Grade']], use_container_width=True)

# ---------- DOWNLOAD ----------
st.sidebar.header("⬇️ Export Data")
def get_csv_download_link(df):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="Attendance_Register.csv">Download CSV</a>'

st.sidebar.markdown(get_csv_download_link(df), unsafe_allow_html=True)
