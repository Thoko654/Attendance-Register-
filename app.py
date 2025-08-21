import streamlit as st
import pandas as pd
import datetime

# ---------- CONFIG ---------- #
DATA_FILE = "attendance_clean.csv"
GRADE_BENCHMARK = 20
MIN_ATTENDANCE_PERCENT = 70

# ---------- LOAD / SAVE ---------- #
@st.cache_data
def load_data():
    return pd.read_csv(DATA_FILE)

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

# ---------- SCAN LOGIC ---------- #
def mark_attendance(df, student_name):
    today = datetime.date.today().strftime("%-d-%b")
    if today not in df.columns:
        df[today] = ""
    df.loc[df["Name"] == student_name, today] = "Present"
    return df

# ---------- SIDEBAR ---------- #
st.sidebar.title("Select Page")
page = st.sidebar.radio("Select Page", ["Scan", "Today", "History", "Tracking", "Manage"])

# ---------- PAGE: SCAN ---------- #
if page == "Scan":
    st.title("📷 Scan Barcode")
    st.write("Scan student barcode to mark them present.")
    df = load_data()
    name = st.text_input("Scan Barcode or Enter Name")
    if name and name in df["Name"].values:
        df = mark_attendance(df, name)
        save_data(df)
        st.success(f"{name} marked present.")
    elif name:
        st.error("Student not found.")

# ---------- PAGE: TODAY ---------- #
elif page == "Today":
    st.title("📅 Today's Attendance")
    df = load_data()
    today = datetime.date.today().strftime("%-d-%b")
    if today not in df.columns:
        st.warning("No attendance marked today.")
    else:
        present_df = df[df[today] == "Present"]
        st.write(f"✅ Total Present: {len(present_df)}")
        st.dataframe(present_df[["Name", "Surname", "Grade"]])

# ---------- PAGE: HISTORY ---------- #
elif page == "History":
    st.title("📚 Attendance History")
    df = load_data()
    st.dataframe(df)

# ---------- PAGE: TRACKING ---------- #
elif page == "Tracking":
    st.title("📈 Attendance Tracking")
    df = load_data()
    attendance_cols = df.columns[4:]
    student_attendance = []

    for _, row in df.iterrows():
        total = len(attendance_cols)
        present = sum([1 for day in attendance_cols if row[day] == "Present"])
        percent = round((present / total) * 100) if total > 0 else 0
        student_attendance.append({
            "Name": row["Name"],
            "Surname": row["Surname"],
            "Grade": row["Grade"],
            "Attendance %": percent,
            "Status": "✅" if percent >= MIN_ATTENDANCE_PERCENT else "❌"
        })

    st.dataframe(pd.DataFrame(student_attendance))

    st.subheader("📊 Grade Attendance Overview")
    for grade in sorted(df["Grade"].unique()):
        grade_df = df[df["Grade"] == grade]
        total = len(grade_df)
        passing = 0
        for _, row in grade_df.iterrows():
            present = sum([1 for col in attendance_cols if row[col] == "Present"])
            percent = round((present / len(attendance_cols)) * 100) if attendance_cols.any() else 0
            if percent >= MIN_ATTENDANCE_PERCENT:
                passing += 1
        attendance_rate = round((passing / GRADE_BENCHMARK) * 100)
        st.write(f"**Grade {grade}**: {attendance_rate}% met 70% requirement")

# ---------- PAGE: MANAGE ---------- #
elif page == "Manage":
    st.title("⚙️ Manage Students")
    df = load_data()

    st.subheader("📝 Add Student")
    with st.form("add_form"):
        name = st.text_input("Name")
        surname = st.text_input("Surname")
        grade = st.selectbox("Grade", ["5", "6", "7"])
        submitted = st.form_submit_button("Add Student")
        if submitted and name and surname:
            new_row = pd.DataFrame([[name, surname, grade, name]], columns=df.columns[:4])
            df = pd.concat([df, new_row], ignore_index=True)
            save_data(df)
            st.success(f"Student {name} added.")

    st.subheader("🗑️ Delete Student")
    student_to_delete = st.selectbox("Select student", df["Name"] + " " + df["Surname"])
    if st.button("Delete Student"):
        name, surname = student_to_delete.split(" ", 1)
        df = df[~((df["Name"] == name) & (df["Surname"] == surname))]
        save_data(df)
        st.success(f"Deleted {student_to_delete}")

    st.subheader("📂 Download Data")
    st.download_button("Download CSV", df.to_csv(index=False), "attendance_backup.csv", "text/csv")
