import streamlit as st
import pandas as pd
import datetime
import os

CSV_PATH = "AttendanceRegister.csv"

# Load and preprocess CSV
@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(CSV_PATH)
    df["Barcode"] = df["Barcode"].apply(lambda x: f"{int(x):04d}")
    return df

def save_data(df):
    df.to_csv(CSV_PATH, index=False)

def format_attendance(val):
    if pd.isna(val):
        return "—"
    elif str(val).strip() == "1":
        return "✅"
    elif str(val).strip() == "0":
        return "❌"
    return str(val)

# App title
st.title("📘 Tutor Class Attendance Register 2025")

# Sidebar
tab = st.sidebar.radio("Navigation", ["Scan", "Today", "History", "Tracking", "Manage"])

df = load_data()
today_str = datetime.date.today().strftime("%-d-%b")  # e.g., 21-Aug

# ------------------ SCAN ------------------
if tab == "Scan":
    st.header("🔍 Scan Student Barcode")
    scanned = st.text_input("Scan or Enter Barcode")
    if scanned:
        barcode = f"{int(scanned):04d}"
        if barcode in df["Barcode"].values:
            idx = df[df["Barcode"] == barcode].index[0]
            df.at[idx, today_str] = 1
            save_data(df)
            st.success(f"✅ Marked Present: {df.at[idx, 'Name']} (Barcode {barcode})")
        else:
            st.error("❌ Barcode not found.")

# ------------------ TODAY ------------------
elif tab == "Today":
    st.header(f"🗓️ Attendance Today – {today_str}")
    if today_str not in df.columns:
        df[today_str] = ""
    temp = df[["Name", "Surname", "Grade", today_str]].copy()
    temp[today_str] = temp[today_str].apply(format_attendance)
    st.dataframe(temp)

# ------------------ HISTORY ------------------
elif tab == "History":
    st.header("📚 Attendance History")
    hist_df = df.copy()
    attendance_cols = hist_df.columns[9:]
    for col in attendance_cols:
        hist_df[col] = hist_df[col].apply(format_attendance)
    st.dataframe(hist_df)

# ------------------ TRACKING ------------------
elif tab == "Tracking":
    st.header("📈 Attendance Tracking")
    temp = df.copy()
    attendance_cols = temp.columns[9:]
    total_sessions = len(attendance_cols)
    temp["Present Count"] = temp[attendance_cols].apply(lambda row: sum([1 for x in row if x == 1 or x == '1']), axis=1)
    temp["% Attendance"] = (temp["Present Count"] / total_sessions * 100).round(1)

    # Grade tracking (assuming 20 per grade as benchmark)
    grades = sorted(temp["Grade"].unique())
    st.subheader("📊 Student Attendance %")
    st.dataframe(temp[["Name", "Surname", "Grade", "% Attendance"]])

    st.subheader("📊 Grade Attendance Summary")
    for g in grades:
        sub = temp[temp["Grade"] == g]
        avg = sub["% Attendance"].mean()
        st.markdown(f"**Grade {g}:** Average Attendance: `{avg:.1f}%`")

# ------------------ MANAGE ------------------
elif tab == "Manage":
    st.header("⚙️ Manage Student Records")

    action = st.radio("Action", ["Add Student", "Edit Student", "Delete Student"])

    if action == "Add Student":
        with st.form("Add Form"):
            name = st.text_input("Name")
            surname = st.text_input("Surname")
            grade = st.selectbox("Grade", [5, 6, 7])
            barcode = st.text_input("Barcode (4-digit number)")
            submit = st.form_submit_button("➕ Add Student")
            if submit:
                new_row = {
                    "Name": name,
                    "Surname": surname,
                    "Gender": "",
                    "Age": "",
                    "School": "",
                    "Grade": grade,
                    "Contact": "",
                    "Barcode": f"{int(barcode):04d}"
                }
                for col in df.columns[9:]:
                    new_row[col] = ""
                df.loc[len(df)] = new_row
                save_data(df)
                st.success("✅ Student added successfully!")

    elif action == "Edit Student":
        selected = st.selectbox("Select Student", df["Name"] + " " + df["Surname"])
        idx = df[df["Name"] + " " + df["Surname"] == selected].index[0]
        with st.form("Edit Form"):
            name = st.text_input("Name", df.at[idx, "Name"])
            surname = st.text_input("Surname", df.at[idx, "Surname"])
            grade = st.selectbox("Grade", [5, 6, 7], index=[5,6,7].index(int(df.at[idx, "Grade"])))
            submit = st.form_submit_button("💾 Save Changes")
            if submit:
                df.at[idx, "Name"] = name
                df.at[idx, "Surname"] = surname
                df.at[idx, "Grade"] = grade
                save_data(df)
                st.success("✅ Student updated!")

    elif action == "Delete Student":
        selected = st.selectbox("Select Student to Delete", df["Name"] + " " + df["Surname"])
        if st.button("❌ Confirm Delete"):
            df = df[~((df["Name"] + " " + df["Surname"]) == selected)]
            save_data(df)
            st.success("🗑️ Student deleted.")

