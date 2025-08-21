import streamlit as st
import pandas as pd
import datetime
import base64
import hashlib

# ---------- CONFIG ----------
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

# ---------- GLOBALS ----------
CSV_FILE = "attendance_clean.csv"
PASSWORD_FILE = "credentials.csv"

# ---------- HELPER FUNCTIONS ----------
@st.cache_data
def load_data():
    return pd.read_csv(CSV_FILE)

@st.cache_data
def load_credentials():
    return pd.read_csv(PASSWORD_FILE)

def save_data(df):
    df.to_csv(CSV_FILE, index=False)

def save_credentials(df):
    df.to_csv(PASSWORD_FILE, index=False)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    users = load_credentials()
    hashed_pw = hash_password(password)
    user = users[(users['username'] == username) & (users['password'] == hashed_pw)]
    if not user.empty:
        return user.iloc[0]['role']
    return None

# ---------- LOGIN ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.role = None
    st.session_state.username = None

if not st.session_state.authenticated:
    st.title("🔐 Login to Attendance System")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        role = authenticate_user(username, password)
        if role:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.role = role
            st.success("Login successful!")
            st.rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

# ---------- LOAD DATA ----------
df = load_data()
today = datetime.date.today().strftime("%-d-%b")

# ---------- SIDEBAR ----------
st.sidebar.title("Select Page")
page = st.sidebar.radio("Select Page", ["Scan", "Today", "History", "Tracking", "Manage"])

# ---------- SCAN ----------
if page == "Scan":
    st.title("📷 Scan Student Attendance")
    scanned_name = st.text_input("Scan barcode / Enter name")
    if st.button("Mark Present"):
        if scanned_name in df["Name"].values:
            df.loc[df["Name"] == scanned_name, today] = "Present"
            save_data(df)
            st.success(f"{scanned_name} marked as present for {today}")
        else:
            st.error("Student not found!")

# ---------- TODAY ----------
elif page == "Today":
    st.title(f"📅 Attendance for Today: {today}")
    if today not in df.columns:
        df[today] = ""
        save_data(df)
    st.dataframe(df[["Name", "Grade", today]])

# ---------- HISTORY ----------
elif page == "History":
    st.title("📜 Attendance History")
    st.dataframe(df)

# ---------- TRACKING ----------
elif page == "Tracking":
    st.title("📊 Attendance Tracking")
    attendance_cols = df.columns[3:]
    summary = pd.DataFrame()
    summary["Name"] = df["Name"]
    summary["Grade"] = df["Grade"]
    summary["Total Present"] = df[attendance_cols].apply(lambda row: (row == "Present").sum(), axis=1)
    summary["% Attendance"] = (summary["Total Present"] / len(attendance_cols) * 100).round(1)
    st.dataframe(summary)

# ---------- MANAGE ----------
elif page == "Manage":
    st.title("⚙️ Manage Students")
    st.subheader("Add New Student")
    with st.form("add_student"):
        name = st.text_input("Name")
        grade = st.selectbox("Grade", [5, 6, 7])
        submitted = st.form_submit_button("Add Student")
        if submitted:
            new_row = {"Name": name, "Grade": grade}
            for col in df.columns[2:]:
                new_row[col] = ""
            df = df.append(new_row, ignore_index=True)
            save_data(df)
            st.success("Student added!")

    st.subheader("Delete Student")
    student_to_delete = st.selectbox("Select Student", df["Name"])
    if st.button("Delete"):
        df = df[df["Name"] != student_to_delete]
        save_data(df)
        st.success("Student deleted")

    # Admin-only section
    if st.session_state.role == "admin":
        st.subheader("Admin: Reset Password")
        users = load_credentials()
        user_to_reset = st.selectbox("Select user", users["username"])
        new_pw = st.text_input("New password", type="password")
        if st.button("Reset Password"):
            users.loc[users["username"] == user_to_reset, "password"] = hash_password(new_pw)
            save_credentials(users)
            st.success("Password reset successfully.")

