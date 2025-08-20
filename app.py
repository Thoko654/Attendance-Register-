import streamlit as st
import pandas as pd
from datetime import datetime
import os

# ========= Config =========
FILE_PATH = "C:/Users/tcsa0/OneDrive/Documents/Attendance Tracker/Attendance.csv"
st.set_page_config(page_title="Tutor Class Attendance Register 2025", layout="wide")

# ========= Load Data =========
@st.cache_data(show_spinner=False)
def load_data():
    return pd.read_csv(FILE_PATH)

def save_data(df):
    df.to_csv(FILE_PATH, index=False)

df = load_data()

# ========= Today's Date Column =========
today = datetime.today().strftime('%-d-%b')  # e.g., 20-Aug
if today not in df.columns:
    df[today] = ""

# ========= Title =========
st.title("📚 Tutor Class Attendance Register 2025")

# ========= Barcode Scanner =========
st.subheader("📷 Scan Student Barcode")
barcode_input = st.text_input("Scan barcode here")

if barcode_input:
    if barcode_input in df["Barcode"].astype(str).values:
        idx = df[df["Barcode"].astype(str) == barcode_input].index[0]
        df.at[idx, today] = 1
        save_data(df)
        st.success(f"✅ Attendance marked for: {df.at[idx, 'Name']} {df.at[idx, 'Surname']}")
    else:
        st.error("❌ Barcode not found!")

# ========= Editable Table =========
st.subheader("📝 Edit Attendance Table")
edited_df = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    key="editable_table"
)

# ========= Save Button =========
if st.button("💾 Save Changes"):
    save_data(edited_df)
    st.success("✅ Changes saved successfully!")

