import streamlit as st
import pandas as pd
import datetime
import re

# Load CSV
df = pd.read_csv("attendance_clean.csv")

# App title
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
st.title("📚 Tutor Class Attendance Register 2025")

# Sidebar navigation
tabs = ["Scan", "Today", "History", "Tracking", "Manage"]
selected_tab = st.sidebar.radio("Select Page", tabs)

# Get today’s date column label
today = datetime.date.today().strftime("%-d-%b")

# Ensure today’s column exists
if today not in df.columns:
    df[today] = ""

# -------------- TAB: SCAN --------------
if selected_tab == "Scan":
    st.subheader("📸 Scan Student Barcode")
    barcode_input = st.text_input("Scan or Enter Barcode:")
    if st.button("Mark Present"):
        if barcode_input:
            if barcode_input in df["Barcode"].astype(str).values:
                idx = df[df["Barcode"].astype(str) == barcode_input].index[0]
                df.at[idx, today] = 1
                st.success(f"Marked {df.at[idx, 'Name']} {df.at[idx, 'Surname']} as Present for {today}.")
            else:
                st.error("⚠️ Barcode not found.")
        else:
            st.warning("Please enter a barcode.")

# -------------- TAB: TODAY --------------
elif selected_tab == "Today":
    st.subheader(f"🗓️ Attendance for {today}")
    st.dataframe(df[["Name", "Surname", "Grade", "Area", today]])

# -------------- TAB: HISTORY --------------
elif selected_tab == "History":
    st.subheader("📅 Edit Attendance History")
    weekly_cols = [col for col in df.columns if re.match(r"\d{1,2}-[A-Za-z]{3,}", col)]
    edit_col = st.selectbox("Choose Date to Edit:", weekly_cols)
    for i in df.index:
        new_value = st.selectbox(f"{df.at[i, 'Name']} {df.at[i, 'Surname']} - {edit_col}", ["", 1], index=1 if str(df.at[i, edit_col]) == "1" else 0, key=f"{i}_{edit_col}")
        df.at[i, edit_col] = new_value
    st.success("✅ You can save changes using the download below.")

# -------------- TAB: TRACKING --------------
elif selected_tab == "Tracking":
    st.subheader("📊 Attendance Tracking")

    weekly_cols = [col for col in df.columns if re.match(r"\d{1,2}-[A-Za-z]{3,}", col)]

    # Clean attendance data
    attendance_numeric = df[weekly_cols].replace(['None', None, 'P.H', '', ' '], 0).apply(pd.to_numeric, errors='coerce').fillna(0)

    # Add Total Present
    df['Total Present'] = attendance_numeric.sum(axis=1).astype(int)

    # Calculate Attendance %
    total_sessions = len(weekly_cols)
    df['Attendance %'] = ((df['Total Present'] / total_sessions) * 100).round(1)

    # Status (Pass/Fail)
    df['Status'] = df['Attendance %'].apply(lambda x: '✅ Pass' if x >= 70 else '❌ Below 70%')

    # Grade Summary
    st.markdown("### 📈 Grade-wise Summary")
    grade_summary = df.groupby('Grade').agg(
        Total_Students=('Name', 'count'),
        Passed=('Status', lambda x: (x == '✅ Pass').sum()),
        Failed=('Status', lambda x: (x == '❌ Below 70%').sum()),
        Avg_Attendance=('Attendance %', 'mean')
    ).round(1).reset_index()
    st.dataframe(grade_summary)

    # Display individual
    st.markdown("### 👩‍🎓 Individual Performance")
    display_df = df.copy()
    display_df[weekly_cols] = display_df[weekly_cols].replace('None', '').replace(None, '')
    st.dataframe(display_df[['Name', 'Grade', 'Total Present', 'Attendance %', 'Status']])

# -------------- TAB: MANAGE --------------
elif selected_tab == "Manage":
    st.subheader("⚙️ Manage Students")

    for i in df.index:
        st.markdown(f"#### Student #{i+1}")
        df.at[i, "Name"] = st.text_input(f"Name {i}", df.at[i, "Name"])
        df.at[i, "Surname"] = st.text_input(f"Surname {i}", df.at[i, "Surname"])
        df.at[i, "Grade"] = st.selectbox(f"Grade {i}", [5, 6, 7], index=[5, 6, 7].index(int(df.at[i, "Grade"])))
        df.at[i, "Area"] = st.text_input(f"Area {i}", df.at[i, "Area"])

# -------- Download updated CSV --------
st.sidebar.markdown("### 💾 Download")
st.sidebar.download_button("Download Updated CSV", data=df.to_csv(index=False).encode('utf-8'), file_name="attendance_clean.csv", mime="text/csv")
