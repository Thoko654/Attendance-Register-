import streamlit as st
import pandas as pd
import datetime

# Title
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.title("📘 Tutor Class Attendance Register 2025")

# Load CSV
csv_path = st.sidebar.text_input("CSV file path", "attendance_clean.csv")
try:
    df = pd.read_csv(csv_path)
except FileNotFoundError:
    st.error("CSV file not found. Please check the file path.")
    st.stop()

# Auto-detect date columns (weekly attendance)
weekly_cols = [col for col in df.columns if "-" in col or "/" in col or "Jun" in col or "Jul" in col]

# --- Tabs ---
tab = st.sidebar.radio("Choose tab", ["Scan", "Today", "History", "Tracking", "Manage"])

# --- Scan Tab ---
if tab == "Scan":
    st.subheader("📷 Scan to Mark Attendance")
    barcode_input = st.text_input("Scan or Enter Barcode", "")
    today = datetime.datetime.today().strftime("%-d-%b")

    if barcode_input:
        if today not in df.columns:
            df[today] = ""

        if barcode_input in df["Barcode"].astype(str).values:
            df.loc[df["Barcode"].astype(str) == barcode_input, today] = 1
            st.success(f"Attendance marked for Barcode {barcode_input} on {today}")
            df.to_csv(csv_path, index=False)
        else:
            st.error("Barcode not found.")

# --- Today Tab ---
elif tab == "Today":
    st.subheader("📅 Attendance for Today")
    today = datetime.datetime.today().strftime("%-d-%b")
    if today not in df.columns:
        st.info("No attendance marked for today yet.")
    else:
        st.dataframe(df[["Barcode", "Name", "Grade", today]])

# --- History Tab ---
elif tab == "History":
    st.subheader("📊 Attendance History")
    st.dataframe(df[["Barcode", "Name", "Grade"] + weekly_cols])

# --- Tracking Tab ---
elif tab == "Tracking":
    st.subheader("📈 Attendance Tracking")

    try:
        tracking_data = df[['Barcode', 'Name', 'Grade'] + weekly_cols].copy()
        tracking_data['Total Present'] = tracking_data[weekly_cols].sum(axis=1)
        tracking_data['Attendance %'] = (tracking_data['Total Present'] / len(weekly_cols) * 100).round(2)

        st.dataframe(tracking_data)
    except KeyError as e:
        st.error(f"Missing column: {e}")

# --- Manage Tab ---
elif tab == "Manage":
    st.subheader("🛠️ Manage Student Records")
    st.dataframe(df)

    if st.button("Save Changes"):
        df.to_csv(csv_path, index=False)
        st.success("Changes saved to CSV.")
