import streamlit as st
import pandas as pd
import os
from datetime import datetime

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")
CSV_FILE = "attendance.csv"

# -----------------------------
# Load Data
# -----------------------------
@st.cache_data
def load_data():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)
    else:
        return pd.DataFrame()

def save_data(df):
    df.to_csv(CSV_FILE, index=False)

# -----------------------------
# UI: Upload Attendance CSV
# -----------------------------
st.title("📋 Tutor Class Attendance Register 2025")

uploaded_file = st.file_uploader("📁 Upload attendance register CSV file", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    save_data(df)
    st.success("✅ File uploaded and loaded successfully!")
else:
    df = load_data()
    if df.empty:
        st.warning("⚠️ No attendance file found. Please upload a CSV file to proceed.")

# -----------------------------
# Show Data
# -----------------------------
if not df.empty:
    st.subheader("📊 Attendance Data")
    st.dataframe(df)

    # Example summary stats
    if 'Name' in df.columns:
        st.markdown(f"**👨‍🎓 Total Students:** {df['Name'].nunique()}")

# -----------------------------
# Placeholder for additional features
# -----------------------------
    st.subheader("📌 More Features Coming Soon!")
    st.markdown("- Automatic attendance marking via barcode")
    st.markdown("- Per-grade monthly attendance %")
    st.markdown("- Edit attendance history")
    st.markdown("- Check 70% threshold compliance")

