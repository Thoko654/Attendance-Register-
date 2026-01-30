# app.py — Tutor Class Attendance Register 2026 (SQLite version)
# Tabs: Scan • Today • Grades • History • Tracking • Manage

import os
import base64
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import altair as alt
import requests

from db import (
    init_db,
    ensure_auto_send_table,      # ✅ make sure this exists in db.py
    get_wide_sheet,
    already_sent_today,          # (db.py)
    mark_sent_today,             # (db.py)
    get_learners_df,
    replace_learners_from_df,
    delete_learner_by_barcode,
    add_class_date,
    insert_present_mark,
    append_inout_log,
    determine_next_action,
    get_currently_in,
    norm_barcode,
    seed_learners_from_csv_if_empty,
)

# ------------------ CONFIG ------------------

APP_TZ = os.environ.get("APP_TIMEZONE", "Africa/Johannesburg")
TZ = ZoneInfo(APP_TZ)

DB_DEFAULT = "app.db"
DB_PATH = Path(os.environ.get("DB_PATH", DB_DEFAULT))

# WhatsApp recipients (E.164 format)
WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

# Auto-send schedule
SEND_DAY_WEEKDAY = 5           # Saturday
SEND_AFTER_TIME = dtime(9, 0)  # 09:00

# Grade capacity default
DEFAULT_GRADE_CAPACITY = 15

# Backup file for permanent restore
BACKUP_LEARNERS_CSV = "learners_backup.csv"

# Meta WhatsApp Cloud API (use Streamlit Secrets or env vars)
META_WA_TOKEN = (st.secrets.get("META_WA_TOKEN", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = (st.secrets.get("META_WA_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = (st.secrets.get("META_WA_API_VERSION", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_API_VERSION", "v22.0").strip()


# ------------------ TIME / LABEL UTILITIES ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_col_label() -> str:
    n = now_local()
    day = str(int(n.strftime("%d")))   # removes leading zero
    mon = n.strftime("%b")
    return f"{day}-{mon}"

def today_labels():
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_col = f"{day}-{mon}"
    date_str = n.strftime("%Y-%m-%d")
    time_str = n.strftime("%H:%M:%S")
    ts = n.isoformat(timespec="seconds")
    return date_col, date_str, time_str, ts

def get_date_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        parts = str(c).split("-")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2:
            cols.append(c)

    def _key(x: str):
        try:
            return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except Exception:
            return 999

    return sorted(cols, key=_key)

def get_present_absent(df: pd.DataFrame, date_col: str, grade=None, area=None):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        empty = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        return empty.iloc[0:0].copy(), empty

    if date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    filt = pd.Series(True, index=df.index)

    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)
    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)

    subset = df.loc[filt].copy()

    present = subset[subset[date_col].astype(str).str.strip() == "1"]
    absent = subset[subset[date_col].astype(str).str.strip() != "1"]
    return present, absent


# ------------------ ✅ PERMANENT DATA (BACKUP + RESTORE) ------------------

def save_learners_backup(df_learners: pd.DataFrame):
    """Save a permanent backup learners CSV (works even when SQLite resets)."""
    try:
        df_learners.to_csv(BACKUP_LEARNERS_CSV, index=False)
    except Exception:
        pass

def restore_learners_if_db_empty(db_path: Path):
    """If DB is empty, restore learners from backup CSV."""
    try:
        current = get_learners_df(db_path).fillna("").astype(str)
        if len(current) > 0:
            return

        backup_path = Path(BACKUP_LEARNERS_CSV)
        if not backup_path.exists():
            return

        backup_df = pd.read_csv(backup_path).fillna("").astype(str)
        required = ["Name", "Surname", "Barcode"]
        if not all(c in backup_df.columns for c in required):
            return
        if len(backup_df) == 0:
            return

        for c in ["Grade", "Area", "Date Of Birth"]:
            if c not in backup_df.columns:
                backup_df[c] = ""

        backup_df = backup_df[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]].copy()
        backup_df["Barcode"] = backup_df["Barcode"].astype(str).str.strip()
        backup_df = backup_df[backup_df["Barcode"] != ""].reset_index(drop=True)

        replace_learners_from_df(db_path, backup_df)
    except Exception:
        pass


# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=[
            "Name", "Surname", "Barcode", "Sessions", "Present", "Absent",
            "Attendance %", "Last present", "Grade", "Area"
        ])

    present_mat = df[date_cols].applymap(lambda x: 1 if str(x).strip() == "1" else 0)
    sessions = len(date_cols)
    present_counts = present_mat.sum(axis=1)
    absent_counts = sessions - present_counts
    pct = (present_counts / sessions * 100).round(1)

    last_present = []
    for _, row in present_mat.iterrows():
        idxs = [j for j, v in enumerate(row.tolist()) if v == 1]
        last_present.append(date_cols[max(idxs)] if idxs else "—")

    result = pd.DataFrame({
        "Name": df.get("Name", ""),
        "Surname": df.get("Surname", ""),
        "Barcode": df.get("Barcode", ""),
        "Grade": df.get("Grade", ""),
        "Area": df.get("Area", ""),
        "Sessions": sessions,
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present,
    })

    return result.sort_values(
        by=["Attendance %", "Name", "Surname"],
        ascending=[False, True, True]
    ).reset_index(drop=True)


# ------------------ BIRTHDAYS ------------------

def parse_dob(dob_str: str):
    dob_str = str(dob_str).strip()
    if not dob_str:
        return None
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(dob_str, fmt).date()
        except ValueError:
            continue
    return None

def get_birthdays_for_week(df: pd.DataFrame, today=None):
    if "Date Of Birth" not in df.columns:
        return []
    if today is None:
        today = now_local().date()

    week_start = today - timedelta(days=6)
    upcoming_end = today + timedelta(days=7)

    results = []
    for _, r in df.iterrows():
        dob = parse_dob(r.get("Date Of Birth", ""))
        if not dob:
            continue

        try:
            birthday_this_year = dob.replace(year=today.year)
        except ValueError:
            continue

        if birthday_this_year == today:
            kind = "today"
        elif week_start <= birthday_this_year < today:
            kind = "belated"
        elif today < birthday_this_year <= upcoming_end:
            kind = "upcoming"
        else:
            continue

        results.append({
            "Name": str(r.get("Name", "")),
            "Surname": str(r.get("Surname", "")),
            "Grade": str(r.get("Grade", "")),
            "Barcode": str(r.get("Barcode", "")),
            "DOB": str(r.get("Date Of Birth", "")),
            "Kind": kind,
        })
    return results

def build_birthday_message(birthdays: list[dict]) -> str:
    if not birthdays:
        return "No birthdays this week or in the next 7 days."

    lines = ["🎂 Tutor Class Birthdays (this week)"]
    for b in birthdays:
        full_name = f"{b['Name']} {b['Surname']}".strip()
        grade = b.get("Grade", "").strip()
        label = "🎉 Today" if b["Kind"] == "today" else ("🎂 Belated" if b["Kind"] == "belated" else "🎁 Upcoming")
        extra = f" (Grade {grade})" if grade else ""
        lines.append(f"{label}: {full_name}{extra} — DOB {b['DOB']}")
    return "\n".join(lines)


# ------------------ WHATSAPP (META CLOUD API) ------------------

def _normalize_e164(n: str) -> str:
    """Expect E.164 like +2767xxxxxxx. Removes 'whatsapp:' if user passed Twilio-style."""
    n = str(n).strip()
    if n.startswith("whatsapp:"):
        n = n.replace("whatsapp:", "").strip()
    return n

def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    """Send WhatsApp messages using Meta WhatsApp Cloud API (test mode requires approved recipients)."""
    token = META_WA_TOKEN
    phone_number_id = META_WA_PHONE_NUMBER_ID
    api_version = META_WA_API_VERSION or "v22.0"

    if not token or not phone_number_id:
        return False, "Missing META_WA_TOKEN / META_WA_PHONE_NUMBER_ID."

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    sent_any = False
    results = []

    for n in to_numbers:
        to_e164 = _normalize_e164(n)
        if not to_e164:
            continue

        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "text",
            "text": {"body": body},
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            data = r.json() if r.content else {}

            if r.status_code in (200, 201):
                sent_any = True
                msg_id = ""
                if isinstance(data, dict):
                    msgs = data.get("messages", [])
                    if msgs and isinstance(msgs, list) and isinstance(msgs[0], dict):
                        msg_id = msgs[0].get("id", "")
                results.append(f"{to_e164}: SENT (id {msg_id})" if msg_id else f"{to_e164}: SENT")
            else:
                err = data.get("error", {}) if isinstance(data, dict) else {}
                emsg = err.get("message", str(data))
                ecode = err.get("code", "")
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code} code {ecode} - {emsg})")

        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    if sent_any:
        return True, " | ".join(results)

    return False, " | ".join(results) if results else "No recipients."


# ------------------ AUTO SEND (BIRTHDAYS) ------------------

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def load_wide_sheet(db_path: Path) -> pd.DataFrame:
    return get_wide_sheet(db_path)

def run_auto_send(db_path: Path):
    """
    Runs once per day:
    - Saturday after 09:00
    - Sends birthday message if birthdays exist
    - Marks as sent to prevent repeats
    """
    ensure_auto_send_table(db_path)

    now = now_local()
    _, date_str, _, ts_iso = today_labels()

    if not should_auto_send(now):
        return
    if already_sent_today(db_path, date_str):
        return

    df_now = load_wide_sheet(db_path)
    birthdays = get_birthdays_for_week(df_now)

    # If no birthdays, still mark as sent to stop repeated checks that day
    if not birthdays:
        mark_sent_today(db_path, date_str, ts_iso)
        return

    msg = build_birthday_message(birthdays)
    ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
    if ok:
        mark_sent_today(db_path, date_str, ts_iso)
        st.sidebar.success("✅ Auto WhatsApp sent today")
    else:
        st.sidebar.warning(f"⚠️ Auto WhatsApp failed: {info}")


# ------------------ PAGE SETUP ------------------

st.set_page_config(
    page_title="Tutor Class Attendance Register 2026",
    page_icon="✅",
    layout="wide"
)

st.markdown(
    """
    <style>
      .small-help { font-size: 13px; color: #666; line-height: 1.4; }
      .card { padding: 12px 14px; border: 1px solid #eee; border-radius: 12px; background: #fff; }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------ DB INIT / SEED / RESTORE ------------------

init_db(DB_PATH)
restore_learners_if_db_empty(DB_PATH)
seed_learners_from_csv_if_empty(DB_PATH)  # if you use a seed CSV in db.py

# Run auto-send safely (only triggers when schedule matches)
try:
    run_auto_send(DB_PATH)
except Exception as e:
    st.sidebar.warning(f"⚠️ Auto-send error: {e}")


# ------------------ HEADER ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(
    f"""
    <div class="card">
      {"<img src='data:image/png;base64," + logo_b64 + "' width='130' style='margin-bottom: 6px;'/>" if logo_b64 else ""}
      <h2 style="margin: 0.2rem 0; font-size: 2.2rem;">Tutor Class Attendance Register 2026</h2>
      <p style="margin:0; color:#666; font-size:14px;">
        Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b> · DB: <b>{DB_PATH.name}</b>
      </p>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")

# ------------------ SIDEBAR: WHATSAPP TEST ------------------

with st.sidebar.expander("📩 WhatsApp Connection Test (Meta)", expanded=False):
    st.markdown(
        """
        <div class="small-help">
          Send a test message using Meta WhatsApp Cloud API.<br>
          <b>Note:</b> In Meta test mode, the recipient must be added as a test number.
        </div>
        """,
        unsafe_allow_html=True
    )

    default_to = WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "+27..."
    test_to = st.text_input("Test recipient number (E.164 format)", value=default_to)
    test_msg = st.text_area("Message", value="Hello! This is a test message from the Tutor Class Attendance app ✅")

    if st.button("Send Test WhatsApp", use_container_width=True):
        ok, info = send_whatsapp_message([test_to], test_msg)
        if ok:
            st.success(info)
        else:
            st.error(info)

# ------------------ TABS (PLACEHOLDER) ------------------
# Keep your existing tab content below.
# If you paste your current Scan/Today/Grades/History/Tracking/Manage sections,
# I can merge them into this cleaned structure without breaking anything.

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])

with tabs[0]:
    st.subheader("Scan")
    st.info("Paste your Scan tab code here (scanner -> insert_present_mark / in-out log).")

with tabs[1]:
    st.subheader("Today")
    st.info("Paste your Today tab code here.")

with tabs[2]:
    st.subheader("Grades")
    st.info("Paste your Grades tab code here.")

with tabs[3]:
    st.subheader("History")
    st.info("Paste your History tab code here.")

with tabs[4]:
    st.subheader("Tracking")
    st.info("Paste your Tracking tab code here.")

with tabs[5]:
    st.subheader("Manage")
    st.info("Paste your Manage tab code here.")
