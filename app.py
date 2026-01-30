# app.py — Tutor Class Attendance Register 2026 (SQLite)
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
    ensure_auto_send_table,
    get_wide_sheet,
    already_sent_today,
    mark_sent_today,
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

# WhatsApp recipients (E.164)
WHATSAPP_RECIPIENTS = ["+27836280453", "+27672291308"]

# Auto-send schedule
SEND_DAY_WEEKDAY = 5           # Saturday
SEND_AFTER_TIME = dtime(9, 0)  # 09:00

DEFAULT_GRADE_CAPACITY = 20    # used for grade % benchmark
BACKUP_LEARNERS_CSV = "learners_backup.csv"

META_WA_TOKEN = (st.secrets.get("META_WA_TOKEN", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = (st.secrets.get("META_WA_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = (st.secrets.get("META_WA_API_VERSION", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_API_VERSION", "v22.0").strip()

# ------------------ TIME ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_labels():
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_label = f"{day}-{mon}"          # e.g. 30-Jan
    date_iso = n.strftime("%Y-%m-%d")    # e.g. 2026-01-30
    time_str = n.strftime("%H:%M:%S")
    ts_iso = n.isoformat(timespec="seconds")
    return date_label, date_iso, time_str, ts_iso

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

# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if df is None or df.empty or not date_cols:
        return pd.DataFrame(columns=[
            "Name", "Surname", "Barcode", "Grade", "Area",
            "Sessions", "Present", "Absent", "Attendance %", "Last present"
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

    return result.sort_values(by=["Attendance %", "Name", "Surname"], ascending=[False, True, True]).reset_index(drop=True)

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
    if df is None or df.empty or "Date Of Birth" not in df.columns:
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
    n = str(n).strip()
    if n.startswith("whatsapp:"):
        n = n.replace("whatsapp:", "").strip()
    return n

def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    token = META_WA_TOKEN
    phone_number_id = META_WA_PHONE_NUMBER_ID
    api_version = META_WA_API_VERSION or "v22.0"

    if not token or not phone_number_id:
        return False, "Missing META_WA_TOKEN / META_WA_PHONE_NUMBER_ID."

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    sent_any = False
    results = []

    for n in to_numbers:
        to_e164 = _normalize_e164(n)
        if not to_e164:
            continue

        payload = {"messaging_product": "whatsapp", "to": to_e164, "type": "text", "text": {"body": body}}

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            data = r.json() if r.content else {}

            if r.status_code in (200, 201):
                sent_any = True
                results.append(f"{to_e164}: SENT")
            else:
                err = data.get("error", {}) if isinstance(data, dict) else {}
                emsg = err.get("message", str(data))
                ecode = err.get("code", "")
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code} code {ecode} - {emsg})")
        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    return (True, " | ".join(results)) if sent_any else (False, " | ".join(results) if results else "No recipients.")

# ------------------ AUTO SEND ------------------

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def run_auto_send(db_path: Path):
    ensure_auto_send_table(db_path)
    now = now_local()
    date_label, date_iso, _, ts_iso = today_labels()

    if not should_auto_send(now):
        return
    if already_sent_today(db_path, date_iso):
        return

    df = get_wide_sheet(db_path)
    birthdays = get_birthdays_for_week(df)
    msg = build_birthday_message(birthdays)

    ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
    if ok:
        mark_sent_today(db_path, date_iso, ts_iso)
        st.sidebar.success("✅ Birthday WhatsApp auto-sent today")
    else:
        st.sidebar.warning(f"⚠️ Auto-send failed: {info}")

# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown("""
<style>
.center-wrap { text-align: center; }
.title { font-size: 42px; font-weight: 800; margin: 6px 0 0 0; color: #111; }
.sub { font-size: 14px; color: #555; margin: 6px 0 10px 0; }
.card { padding: 18px 18px; border: 1px solid #eee; border-radius: 16px; background: #fff; }
.small-help { font-size: 13px; color: #666; line-height: 1.4; }
</style>
""", unsafe_allow_html=True)

# ------------------ DB INIT / SEED ------------------

init_db(DB_PATH)
seed_learners_from_csv_if_empty(DB_PATH)

# Run auto-send safely
try:
    run_auto_send(DB_PATH)
except Exception as e:
    st.sidebar.warning(f"⚠️ Auto-send error: {e}")

# ------------------ HEADER (CENTERED) ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

date_label, date_iso, time_str, ts_iso = today_labels()

st.markdown(
    f"""
    <div class="card center-wrap">
      {"<img src='data:image/png;base64," + logo_b64 + "' width='140' style='margin-bottom:10px;'/>" if logo_b64 else ""}
      <div class="title">Tutor Class Attendance Register 2026</div>
      <div class="sub">
        Today: <b>{date_label}</b> · Timezone: <b>{APP_TZ}</b> · DB: <b>{DB_PATH.name}</b>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")

# ------------------ SIDEBAR (WHATSAPP TEST) ------------------

with st.sidebar.expander("📩 WhatsApp Connection Test (Meta)", expanded=False):
    st.markdown("""<div class="small-help">
    Send a test message using Meta WhatsApp Cloud API.<br>
    <b>Note:</b> In Meta test mode, the recipient must be added as a test number.
    </div>""", unsafe_allow_html=True)

    default_to = WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "+27..."
    test_to = st.text_input("Test recipient number (E.164)", value=default_to)
    test_msg = st.text_area("Message", value="Hello! Test message from Tutor Class Attendance ✅")
    if st.button("Send Test WhatsApp", use_container_width=True):
        ok, info = send_whatsapp_message([test_to], test_msg)
        (st.success if ok else st.error)(info)

# ------------------ UI HELPERS ------------------

def safe_present_absent(df: pd.DataFrame, date_col: str, grade: str | None = None):
    if df is None or df.empty:
        return df.iloc[0:0].copy(), df.iloc[0:0].copy()
    if date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    temp = df.copy()
    if grade and "Grade" in temp.columns:
        temp = temp[temp["Grade"].astype(str) == str(grade)]

    present = temp[temp[date_col].astype(str).str.strip() == "1"].copy()
    absent = temp[temp[date_col].astype(str).str.strip() != "1"].copy()
    return present, absent

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# ------------------ SCAN HANDLER (AUTO SUBMIT) ------------------

def handle_scan_submit():
    code = st.session_state.get("scan_code", "")
    bc = norm_barcode(code)
    if not bc:
        return

    learners = get_learners_df(DB_PATH)
    if learners.empty or bc not in learners["Barcode"].astype(str).map(norm_barcode).tolist():
        st.session_state["scan_status"] = f"❌ Barcode not found: {bc}"
        st.session_state["scan_code"] = ""
        return

    date_label, date_iso, time_str, ts_iso = today_labels()

    # Ensure date exists for everyone (optional but helpful)
    add_class_date(DB_PATH, date_label, date_iso)

    # Mark present
    insert_present_mark(DB_PATH, bc, date_label, date_iso, ts_iso)

    # IN/OUT
    action = determine_next_action(DB_PATH, bc)
    append_inout_log(DB_PATH, bc, action, ts_iso, date_iso, time_str)

    row = learners[learners["Barcode"].astype(str).map(norm_barcode) == bc].iloc[0]
    full_name = f"{row.get('Name','')} {row.get('Surname','')}".strip()
    st.session_state["scan_status"] = f"✅ {full_name} marked PRESENT ({action})"
    st.session_state["scan_code"] = ""  # clear input for next scan

# ------------------ TABS ------------------

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])

# -------- Scan --------
with tabs[0]:
    st.subheader("Scan (Auto-submit)")

    st.text_input(
        "Scan or type barcode here",
        key="scan_code",
        placeholder="Scan barcode...",
        on_change=handle_scan_submit,
    )

    status = st.session_state.get("scan_status", "")
    if status:
        st.info(status)

    st.write("### Currently IN (Today)")
    try:
        df_in = get_currently_in(DB_PATH)
        if df_in.empty:
            st.caption("No one is currently IN.")
        else:
            st.dataframe(df_in, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Database error in Currently IN: {e}")

# -------- Today --------
with tabs[1]:
    st.subheader("Today")

    df = get_wide_sheet(DB_PATH)
    date_cols = get_date_columns(df)
    today_col = date_label

    if df.empty:
        st.warning("No learners found. Add learners in Manage tab first.")
    elif today_col not in df.columns:
        st.warning("No attendance marks for today yet. Scan learners first.")
        st.dataframe(df[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]], use_container_width=True, hide_index=True)
    else:
        present, absent = safe_present_absent(df, today_col)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total learners", len(df))
        c2.metric("Present today", len(present))
        c3.metric("Absent today", len(absent))

        st.write("#### Present")
        st.dataframe(present, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Present (CSV)",
            data=to_csv_bytes(present),
            file_name=f"present_{date_label}.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.write("#### Absent")
        st.dataframe(absent, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Absent (CSV)",
            data=to_csv_bytes(absent),
            file_name=f"absent_{date_label}.csv",
            mime="text/csv",
            use_container_width=True
        )

# -------- Grades --------
with tabs[2]:
    st.subheader("Grades")

    df = get_wide_sheet(DB_PATH)
    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        date_cols = get_date_columns(df)
        if not date_cols:
            st.warning("No attendance marks yet (no date columns). Scan learners first.")
        else:
            chosen_date = st.selectbox("Select date", options=date_cols, index=len(date_cols)-1)

            grades = sorted([g for g in df["Grade"].astype(str).unique().tolist() if g.strip() != ""])
            if not grades:
                st.warning("No grades assigned yet. Update Grade values in Manage tab.")
            else:
                summary_rows = []
                for g in grades:
                    g_df = df[df["Grade"].astype(str) == str(g)].copy()
                    total = len(g_df)
                    present = 0
                    if chosen_date in g_df.columns:
                        present = (g_df[chosen_date].astype(str).str.strip() == "1").sum()
                    pct = round((present / total * 100), 1) if total else 0.0

                    # Optional benchmark capacity %
                    bench_pct = round((total / DEFAULT_GRADE_CAPACITY * 100), 1) if DEFAULT_GRADE_CAPACITY else 0.0

                    summary_rows.append({
                        "Grade": g,
                        "Learners": total,
                        "Present": present,
                        "Attendance %": pct,
                        "Capacity benchmark (20) %": bench_pct
                    })

                summary = pd.DataFrame(summary_rows).sort_values("Grade").reset_index(drop=True)
                st.write("### Grade Attendance Summary")
                st.dataframe(summary, use_container_width=True, hide_index=True)

                st.download_button(
                    "⬇️ Download Grade Summary (CSV)",
                    data=to_csv_bytes(summary),
                    file_name=f"grade_summary_{chosen_date}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

                st.write("### Download Full Attendance Sheet (wide)")
                st.download_button(
                    "⬇️ Download Wide Sheet (CSV)",
                    data=to_csv_bytes(df),
                    file_name=f"attendance_wide.csv",
                    mime="text/csv",
                    use_container_width=True
                )

# -------- History --------
with tabs[3]:
    st.subheader("History")

    df = get_wide_sheet(DB_PATH)
    if df.empty:
        st.warning("No learners yet.")
    else:
        date_cols = get_date_columns(df)
        if not date_cols:
            st.warning("No attendance marks yet. Scan learners first.")
        else:
            chosen_date = st.selectbox("Select a date column", options=date_cols, index=len(date_cols)-1)
            grade_filter = st.selectbox("Filter by grade (optional)", options=["(All)"] + sorted(df["Grade"].astype(str).unique().tolist()))

            g = None if grade_filter == "(All)" else grade_filter
            present, absent = safe_present_absent(df, chosen_date, grade=g)

            st.write("#### Present")
            st.dataframe(present, use_container_width=True, hide_index=True)

            st.write("#### Absent")
            st.dataframe(absent, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download History (Present+Absent CSV)",
                data=to_csv_bytes(pd.concat([present.assign(Status="Present"), absent.assign(Status="Absent")], ignore_index=True)),
                file_name=f"history_{chosen_date}.csv",
                mime="text/csv",
                use_container_width=True
            )

# -------- Tracking --------
with tabs[4]:
    st.subheader("Tracking")

    df = get_wide_sheet(DB_PATH)
    if df.empty:
        st.warning("No learners yet.")
    else:
        track = compute_tracking(df)
        st.dataframe(track, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Tracking (CSV)",
            data=to_csv_bytes(track),
            file_name="tracking.csv",
            mime="text/csv",
            use_container_width=True
        )

# -------- Manage --------
with tabs[5]:
    st.subheader("Manage Learners")

    st.write("### Add learner")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    name = c1.text_input("Name")
    surname = c2.text_input("Surname")
    barcode = c3.text_input("Barcode")
    grade = c4.text_input("Grade")
    area = c5.text_input("Area")
    dob = c6.text_input("Date Of Birth")

    if st.button("➕ Add / Update learner", use_container_width=True):
        df_learn = get_learners_df(DB_PATH)
        new_row = pd.DataFrame([{
            "Name": name, "Surname": surname, "Barcode": barcode,
            "Grade": grade, "Area": area, "Date Of Birth": dob
        }])
        if df_learn.empty:
            df_out = new_row
        else:
            df_out = pd.concat([df_learn, new_row], ignore_index=True)

        # Deduplicate by barcode (last wins)
        df_out["Barcode"] = df_out["Barcode"].astype(str).map(norm_barcode)
        df_out = df_out[df_out["Barcode"] != ""].drop_duplicates(subset=["Barcode"], keep="last")

        replace_learners_from_df(DB_PATH, df_out)
        st.success("Saved.")

    st.write("### Delete learner")
    del_bc = st.text_input("Barcode to delete")
    if st.button("🗑️ Delete", use_container_width=True):
        delete_learner_by_barcode(DB_PATH, del_bc)
        st.success("Deleted (if barcode existed).")

    st.write("### Learners list")
    learners = get_learners_df(DB_PATH)
    st.dataframe(learners, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download Learners (CSV)",
        data=to_csv_bytes(learners),
        file_name="learners.csv",
        mime="text/csv",
        use_container_width=True
    )

    st.write("### Bulk upload learners CSV")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            df_up = pd.read_csv(up).fillna("").astype(str)
            needed = {"Name", "Surname", "Barcode"}
            if not needed.issubset(set(df_up.columns)):
                st.error("CSV must contain at least: Name, Surname, Barcode")
            else:
                for c in ["Grade", "Area", "Date Of Birth"]:
                    if c not in df_up.columns:
                        df_up[c] = ""
                df_up = df_up[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]].copy()
                replace_learners_from_df(DB_PATH, df_up)
                st.success("Uploaded & replaced learners.")
        except Exception as e:
            st.error(f"Upload failed: {e}")
