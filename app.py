import streamlit as st
import pandas as pd
import datetime
import hashlib
import base64

# Load data
@st.cache_data
def load_data():
    return pd.read_csv("attendance.csv")

def save_data(df):
    df.to_csv("attendance.csv", index=False)

# Utility functions
def get_month_name(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%d-%b").strftime("%B")
    except:
        return "Unknown"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_attendance_columns(df):
    return [col for col in df.columns if "-" in col and col[0].isdigit()]

# App
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.title("📘 Tutor Class Attendance Register 2025")

menu = st.sidebar.radio("Select Page", ["Scan", "Today", "History", "Tracking", "Manage"])

df = load_data()
attendance_cols = get_attendance_columns(df)

# ========== SCAN TAB ==========
if menu == "Scan":
    st.header("📷 Scan Barcode")
    scanned_name = st.text_input("Scan Barcode or Enter Student Name")
    if scanned_name:
        today = datetime.datetime.now().strftime("%d-%b")
        if today not in df.columns:
            df[today] = ""
        matched = df[df["Name"] + " " + df["Surname"] == scanned_name]
        if not matched.empty:
            df.loc[matched.index, today] = "Present"
            save_data(df)
            st.success(f"{scanned_name} marked as Present on {today}")
        else:
            st.error("Student not found.")

# ========== TODAY TAB ==========
elif menu == "Today":
    st.header("📅 Mark Today's Attendance")
    today = datetime.datetime.now().strftime("%d-%b")
    if today not in df.columns:
        df[today] = ""
    for i, row in df.iterrows():
        status = st.selectbox(
            f"{row['Name']} {row['Surname']} - Grade {row['Grade']}",
            ["", "Present", "Absent", "Late", "Excused"],
            key=f"status_{i}"
        )
        if status:
            df.at[i, today] = status
    if st.button("✅ Save Attendance"):
        save_data(df)
        st.success("Today's attendance saved.")

# ========== HISTORY TAB ==========
elif menu == "History":
    st.header("📅 Edit Attendance History")
    dates = attendance_cols
    selected_date = st.selectbox("Choose Date to Edit:", dates)
    for i, row in df.iterrows():
        key = f"{row['Name']}_{selected_date}"
        new_status = st.selectbox(
            f"{row['Name']} {row['Surname']} - {selected_date}",
            ["", "Present", "Absent", "Late", "Excused"],
            index=["", "Present", "Absent", "Late", "Excused"].index(row.get(selected_date, "")) if row.get(selected_date) in ["Present", "Absent", "Late", "Excused"] else 0,
            key=key
        )
        df.at[i, selected_date] = new_status
    if st.button("💾 Save Changes"):
        save_data(df)
        st.success("History updated successfully.")

# ========== TRACKING TAB ==========
elif menu == "Tracking":
    st.header("📊 Attendance Tracking")

    attendance_counts = []
    for i, row in df.iterrows():
        present = sum([1 for d in attendance_cols if row.get(d) == "Present"])
        percentage = (present / len(attendance_cols)) * 100 if attendance_cols else 0
        attendance_counts.append({
            "Name": f"{row['Name']} {row['Surname']}",
            "Grade": row["Grade"],
            "Area": row["Area"],
            "Attendance (%)": round(percentage, 2)
        })

    summary_df = pd.DataFrame(attendance_counts)

    st.subheader("📈 Grade-wise Summary")
    grade_summary = summary_df.groupby("Grade").agg(
        Total_Students=("Name", "count"),
        Passed=("Attendance (%)", lambda x: (x >= 70).sum()),
        Failed=("Attendance (%)", lambda x: (x < 70).sum()),
        Avg_Attendance=("Attendance (%)", "mean")
    ).reset_index()
    st.dataframe(grade_summary, use_container_width=True)

    st.subheader("🙋 Individual Performance")
    st.dataframe(summary_df.sort_values(by="Grade"), use_container_width=True)

# ========== MANAGE TAB ==========
elif menu == "Manage":
    st.header("⚙️ Manage Students")
    for i, row in df.iterrows():
        st.subheader(f"Student #{i+1}")
        df.at[i, "Name"] = st.text_input(f"Name {i}", row["Name"])
        df.at[i, "Surname"] = st.text_input(f"Surname {i}", row["Surname"])
        df.at[i, "Grade"] = st.selectbox(f"Grade {i}", [5, 6, 7], index=[5, 6, 7].index(int(row["Grade"])))
        df.at[i, "Area"] = st.text_input(f"Area {i}", row["Area"])
    if st.button("💾 Save All"):
        save_data(df)
        st.success("All student data updated.")

# ========== DOWNLOAD ==========
st.sidebar.header("💾 Download")
csv = df.to_csv(index=False)
b64 = base64.b64encode(csv.encode()).decode()
href = f'<a href="data:file/csv;base64,{b64}" download="updated_attendance.csv">Download Updated CSV</a>'
st.sidebar.markdown(href, unsafe_allow_html=True)
