import streamlit as st
import pandas as pd
from datetime import datetime
import os

# ====== CONFIG ======
st.set_page_config(page_title="📋 Attendance Register", layout="centered")
CSV_FILE = "Student_records.csv"

# ====== HELPER FUNCTION ======
@st.cache_data
def load_data():
    try:
        df = pd.read_csv(CSV_FILE, dtype=str).fillna("")
    except FileNotFoundError:
        st.error(f"❌ File '{CSV_FILE}' not found.")
        st.stop()
    return df

def save_data(df):
    df.to_csv(CSV_FILE, index=False)

def mark_attendance(df, barcode):
    today = datetime.today().strftime('%d-%b')  # e.g., '20-Aug'
    if today not in df.columns:
        df[today] = ""

    match = df["Barcode"] == barcode
    if match.any():
        df.loc[match, today] = "1"
        name = df.loc[match, "Name"].values[0]
        st.success(f"✅ Marked present: {name}")
    else:
        st.error("❌ Barcode not found.")
    return df

# ====== MAIN UI ======
st.title("📸 Student Attendance Register")

df = load_data()

st.markdown("### ✨ Scan or Enter Barcode Below")
barcode_input = st.text_input("📷 Scan/Enter Student Barcode", max_chars=20)

if st.button("✅ Mark as Present"):
    if barcode_input:
        df = mark_attendance(df, barcode_input)
        save_data(df)
    else:
        st.warning("Please scan or enter a barcode.")

# ====== Show Table ======
with st.expander("📊 Show Full Attendance Table"):
    st.dataframe(df)

