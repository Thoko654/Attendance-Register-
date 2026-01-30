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
    ensure_auto_send_table,
    get_wide_sheet,
    already_sent_today,
    mark_sent_today,
    get_learners_df,
    replace_learners_from_df,
    delete_learner_by_barcode,
    upsert_learner,
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
WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

# Auto-send schedule (Saturday after 09:00)
SEND_DAY_WEEKDAY = 5
SEND_AFTER_TIME = dtime(9, 0)

# Grade capacity default (for % benchmark)
DEFAULT_GRADE_CAPACITY = 20

# Backup file for learners restore
BACKUP_LEARNERS_CSV = "learners_backup.csv"

# Meta WhatsApp Cloud API (secrets or env)
META_WA_TOKEN = (st.secrets.get("META_WA_TOKEN", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = (st.secrets.get("META_WA_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = (st.secrets.get("META_WA_API_VERSION", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_API_VERSION", "v22.0").strip()

# ------------------ TIME UTILS ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_col_label() -> str:
    n = now_local()
    day = str(int(n.strftime("%d")))
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

def get_present_absent(df: pd.DataFrame, date_col: str, grade=None):
    if df is None or df.empty:
        return df.iloc[0:0].copy(), df.copy()

    if date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    sub = df.copy()
    if grade and "Grade" in sub.columns:
        sub = sub[sub["Grade"].astype(str) == str(grade)].copy()

    present = sub[sub[date_col].astype(str).str.strip() == "1"].copy()
    absent = sub[sub[date_col].astype(str).str.strip() != "1"].copy()
    return present, absent

# ------------------ BACKUP / RESTORE ------------------

def save_learners_backup(df_learners: pd.DataFrame):
    try:
        df_learners.to_csv(BACKUP_LEARNERS_CSV, index=False)
    except Exception:
        pass

def restore_learners_if_db_empty():
    try:
        current = get_learners_df(DB_PATH).fillna("").astype(str)
        if len(current) > 0:
            return

        b = Path(BACKUP_LEARNERS_CSV)
        if not b.exists():
            return

        backup_df = pd.read_csv(b).fillna("").astype(str)
        req = ["Name", "Surname", "Barcode"]
        if not all(c in backup_df.columns for c in req):
            return
        if len(backup_df) == 0:
            return

        for c in ["Grade", "Area", "Date Of Birth"]:
            if c not in backup_df.columns:
                backup_df[c] = ""

        backup_df = backup_df[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]].copy()
        backup_df["Barcode"] = backup_df["Barcode"].astype(str).str.strip()
        backup_df = backup_df[backup_df["Barcode"] != ""].reset_index(drop=True)

        replace_learners_from_df(DB_PATH, backup_df)
    except Exception:
        pass

# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Grade","Present","Absent","Attendance %","Last present"])

    mat = df[date_cols].applymap(lambda x: 1 if str(x).strip() == "1" else 0)
    sessions = len(date_cols)
    present_counts = mat.sum(axis=1)
    absent_counts = sessions - present_counts
    pct = (present_counts / sessions * 100).round(1)

    last_present = []
    for _, row in mat.iterrows():
        idxs = [i for i,v in enumerate(row.tolist()) if v == 1]
        last_present.append(date_cols[max(idxs)] if idxs else "—")

    out = pd.DataFrame({
        "Name": df.get("Name",""),
        "Surname": df.get("Surname",""),
        "Barcode": df.get("Barcode",""),
        "Grade": df.get("Grade",""),
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present
    })
    return out.sort_values(["Attendance %","Name"], ascending=[False, True]).reset_index(drop=True)

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
    if "Date Of Birth" not in df.columns or df.empty:
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
            bday = dob.replace(year=today.year)
        except ValueError:
            continue

        if bday == today:
            kind = "today"
        elif week_start <= bday < today:
            kind = "belated"
        elif today < bday <= upcoming_end:
            kind = "upcoming"
        else:
            continue

        results.append({
            "Name": str(r.get("Name","")),
            "Surname": str(r.get("Surname","")),
            "Grade": str(r.get("Grade","")),
            "DOB": str(r.get("Date Of Birth","")),
            "Kind": kind
        })
    return results

def build_birthday_message(birthdays: list[dict]) -> str:
    if not birthdays:
        return "No birthdays this week or in the next 7 days."
    lines = ["🎂 Tutor Class Birthdays (this week)"]
    for b in birthdays:
        full = f"{b['Name']} {b['Surname']}".strip()
        g = b.get("Grade","").strip()
        label = "🎉 Today" if b["Kind"] == "today" else ("🎂 Belated" if b["Kind"] == "belated" else "🎁 Upcoming")
        extra = f" (Grade {g})" if g else ""
        lines.append(f"{label}: {full}{extra} — DOB {b['DOB']}")
    return "\n".join(lines)

# ------------------ WHATSAPP SEND ------------------

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
                results.append(f"{to_e164}: SENT")
            else:
                err = data.get("error", {}) if isinstance(data, dict) else {}
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code} - {err.get('message','')})")
        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    return (True, " | ".join(results)) if sent_any else (False, " | ".join(results) if results else "No recipients.")

# ------------------ AUTO SEND ------------------

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def run_auto_send():
    ensure_auto_send_table(DB_PATH)
    now = now_local()
    _, date_str, _, ts_iso = today_labels()

    if not should_auto_send(now):
        return
    if already_sent_today(DB_PATH, date_str):
        return

    df = get_wide_sheet(DB_PATH)
    birthdays = get_birthdays_for_week(df)

    # Mark sent even if no birthdays (prevents repeated checks)
    if not birthdays:
        mark_sent_today(DB_PATH, date_str, ts_iso)
        return

    msg = build_birthday_message(birthdays)
    ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
    if ok:
        mark_sent_today(DB_PATH, date_str, ts_iso)
        st.sidebar.success("✅ Birthday WhatsApp auto-sent")
    else:
        st.sidebar.warning(f"⚠️ Auto-send failed: {info}")

# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

# Center header + stronger text visibility
st.markdown(
    """
    <style>
      .card {
        padding: 14px 16px;
        border: 1px solid #eee;
        border-radius: 14px;
        background: #fff;
        text-align: center;
      }
      .title {
        margin: 0.2rem 0;
        font-size: 2.25rem;
        font-weight: 800;
        color: #111;
      }
      .meta {
        margin:0;
        color:#444;
        font-size:14px;
        font-weight: 600;
      }
      .small-help { font-size: 13px; color: #666; line-height: 1.4; }
      .scanbox input { font-size: 22px !important; font-weight: 700 !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------ INIT DB ------------------

init_db(DB_PATH)
restore_learners_if_db_empty()
seed_learners_from_csv_if_empty(DB_PATH)

try:
    run_auto_send()
except Exception as e:
    st.sidebar.warning(f"⚠️ Auto-send error: {e}")

# ------------------ HEADER ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(
    f"""
    <div class="card">
      {"<img src='data:image/png;base64," + logo_b64 + "' width='110' style='margin-bottom: 8px;'/>" if logo_b64 else ""}
      <div class="title">Tutor Class Attendance Register 2026</div>
      <p class="meta">
        Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b> · DB: <b>{DB_PATH.name}</b>
      </p>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")

# ------------------ SIDEBAR TEST ------------------

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
    test_to = st.text_input("Test recipient number (E.164)", value=default_to)
    test_msg = st.text_area("Message", value="Hello! Test from Tutor Class Attendance ✅")

    if st.button("Send Test WhatsApp", use_container_width=True):
        ok, info = send_whatsapp_message([test_to], test_msg)
        st.success(info) if ok else st.error(info)

# ------------------ DATA LOAD ------------------

df_wide = get_wide_sheet(DB_PATH)
learners_df = get_learners_df(DB_PATH)

date_col, date_str, time_str, ts_iso = today_labels()

# ------------------ TABS ------------------

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])

# ============ TAB 1: SCAN (AUTO SUBMIT) ============
with tabs[0]:
    st.subheader("Scan")

    if learners_df.empty:
        st.warning("No learners found. Please add learners in Manage tab first.")
    else:
        # ensure today's column exists
        add_class_date(DB_PATH, date_col)

        if "last_scan_msg" not in st.session_state:
            st.session_state["last_scan_msg"] = ""

        def handle_scan():
            raw = st.session_state.get("scan_input", "")
            bc = norm_barcode(raw)
            if not bc:
                return

            # Mark present + IN/OUT logic
            name = insert_present_mark(DB_PATH, bc, date_col)
            action = determine_next_action(DB_PATH, bc)  # "IN" or "OUT"
            append_inout_log(DB_PATH, bc, action, ts_iso)

            # clear input and show message
            st.session_state["scan_input"] = ""
            if name:
                st.session_state["last_scan_msg"] = f"✅ {name} marked Present + {action}"
            else:
                st.session_state["last_scan_msg"] = f"⚠️ Barcode not found: {bc}"

        st.markdown("<div class='scanbox'>", unsafe_allow_html=True)
        st.text_input(
            "Scan or type barcode (auto submits)",
            key="scan_input",
            on_change=handle_scan,
            placeholder="Scan here…",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state["last_scan_msg"]:
            st.info(st.session_state["last_scan_msg"])

        st.markdown("### Currently IN (Today)")
        in_df = get_currently_in(DB_PATH)
        if in_df.empty:
            st.write("No one is currently IN.")
        else:
            st.dataframe(in_df, use_container_width=True)

# ============ TAB 2: TODAY ============
with tabs[1]:
    st.subheader("Today")

    if df_wide.empty:
        st.warning("No data yet. Add learners first.")
    else:
        add_class_date(DB_PATH, date_col)
        df_today = get_wide_sheet(DB_PATH)
        present, absent = get_present_absent(df_today, date_col)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"### Present ({len(present)})")
            st.dataframe(present[["Name","Surname","Grade","Barcode"]], use_container_width=True)
        with c2:
            st.markdown(f"### Absent ({len(absent)})")
            st.dataframe(absent[["Name","Surname","Grade","Barcode"]], use_container_width=True)

        # downloads
        st.markdown("### Download Today")
        today_export = df_today[["Name","Surname","Grade","Barcode",date_col]].copy()
        csv_bytes = today_export.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Today CSV", data=csv_bytes, file_name=f"today_{date_col}.csv", mime="text/csv")

# ============ TAB 3: GRADES ============
with tabs[2]:
    st.subheader("Grades")

    if df_wide.empty:
        st.warning("No learners found. Add learners first.")
    else:
        add_class_date(DB_PATH, date_col)
        df = get_wide_sheet(DB_PATH)
        date_cols = get_date_columns(df)

        if not date_cols:
            st.info("No attendance marks yet (no date columns). Scan learners first.")
        else:
            # grade attendance % based on DEFAULT_GRADE_CAPACITY benchmark
            latest = date_cols[-1]
            df["_present"] = df[latest].astype(str).str.strip().eq("1").astype(int)

            grade_summary = (
                df.groupby("Grade", dropna=False)["_present"]
                  .agg(Present="sum", Learners="count")
                  .reset_index()
            )
            grade_summary["Benchmark"] = DEFAULT_GRADE_CAPACITY
            grade_summary["Attendance % (of learners)"] = (grade_summary["Present"] / grade_summary["Learners"] * 100).round(1)
            grade_summary["Grade Capacity % (of benchmark)"] = (grade_summary["Learners"] / DEFAULT_GRADE_CAPACITY * 100).round(1)

            st.markdown(f"### Grade Summary (Latest Date: **{latest}**)")
            st.dataframe(grade_summary, use_container_width=True)

            # chart
            chart = alt.Chart(grade_summary).mark_bar().encode(
                x="Grade:N",
                y="Attendance % (of learners):Q",
                tooltip=["Grade","Present","Learners","Attendance % (of learners)"]
            ).properties(height=320)
            st.altair_chart(chart, use_container_width=True)

            # downloads
            st.markdown("### Downloads")
            full_csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download Full Attendance CSV", data=full_csv, file_name="attendance_full.csv", mime="text/csv")

            sum_csv = grade_summary.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download Grade Summary CSV", data=sum_csv, file_name=f"grade_summary_{latest}.csv", mime="text/csv")

# ============ TAB 4: HISTORY ============
with tabs[3]:
    st.subheader("History")

    if df_wide.empty:
        st.warning("No data yet.")
    else:
        df = get_wide_sheet(DB_PATH)
        date_cols = get_date_columns(df)

        if not date_cols:
            st.info("No attendance marks yet.")
        else:
            selected = st.selectbox("Select a date", options=list(reversed(date_cols)))
            present, absent = get_present_absent(df, selected)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"### Present ({len(present)})")
                st.dataframe(present[["Name","Surname","Grade","Barcode"]], use_container_width=True)
            with c2:
                st.markdown(f"### Absent ({len(absent)})")
                st.dataframe(absent[["Name","Surname","Grade","Barcode"]], use_container_width=True)

            # download for that date
            export = df[["Name","Surname","Grade","Barcode",selected]].copy()
            st.download_button(
                f"⬇️ Download {selected} CSV",
                data=export.to_csv(index=False).encode("utf-8"),
                file_name=f"attendance_{selected}.csv",
                mime="text/csv"
            )

# ============ TAB 5: TRACKING ============
with tabs[4]:
    st.subheader("Tracking")

    if df_wide.empty:
        st.warning("No learners found.")
    else:
        df = get_wide_sheet(DB_PATH)
        date_cols = get_date_columns(df)
        if not date_cols:
            st.info("No attendance marks yet.")
        else:
            track = compute_tracking(df)
            st.dataframe(track, use_container_width=True)

            st.download_button(
                "⬇️ Download Tracking CSV",
                data=track.to_csv(index=False).encode("utf-8"),
                file_name="tracking.csv",
                mime="text/csv"
            )

# ============ TAB 6: MANAGE ============
with tabs[5]:
    st.subheader("Manage Learners")

    st.markdown("### Add / Update Learner")
    c1, c2, c3 = st.columns(3)
    with c1:
        name = st.text_input("Name")
    with c2:
        surname = st.text_input("Surname")
    with c3:
        barcode = st.text_input("Barcode")

    c4, c5, c6 = st.columns(3)
    with c4:
        grade = st.text_input("Grade (e.g. 5, 6, 7)")
    with c5:
        area = st.text_input("Area (optional)")
    with c6:
        dob = st.text_input("Date Of Birth (optional)")

    if st.button("Save Learner", use_container_width=True):
        bc = norm_barcode(barcode)
        if not bc or not name.strip() or not surname.strip():
            st.error("Name, Surname, and Barcode are required.")
        else:
            upsert_learner(DB_PATH, name.strip(), surname.strip(), bc, grade.strip(), area.strip(), dob.strip())
            st.success("✅ Saved.")
            # backup after changes
            save_learners_backup(get_learners_df(DB_PATH))
            st.rerun()

    st.markdown("---")
    st.markdown("### Current Learners")

    learners_df = get_learners_df(DB_PATH)
    if learners_df.empty:
        st.info("No learners yet.")
    else:
        st.dataframe(learners_df, use_container_width=True)

        del_bc = st.text_input("Delete learner by Barcode", key="del_bc")
        if st.button("Delete", use_container_width=True):
            b = norm_barcode(del_bc)
            if not b:
                st.error("Enter a barcode.")
            else:
                delete_learner_by_barcode(DB_PATH, b)
                save_learners_backup(get_learners_df(DB_PATH))
                st.success("✅ Deleted.")
                st.rerun()

    st.markdown("---")
    st.markdown("### Upload Learners CSV (Replace All)")
    st.caption("CSV columns required: Name, Surname, Barcode. Optional: Grade, Area, Date Of Birth")

    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded is not None:
        try:
            df_new = pd.read_csv(uploaded).fillna("").astype(str)
            needed = {"Name","Surname","Barcode"}
            if not needed.issubset(set(df_new.columns)):
                st.error("CSV missing required columns.")
            else:
                for col in ["Grade","Area","Date Of Birth"]:
                    if col not in df_new.columns:
                        df_new[col] = ""
                df_new = df_new[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]].copy()
                df_new["Barcode"] = df_new["Barcode"].astype(str).str.strip()
                df_new = df_new[df_new["Barcode"] != ""].reset_index(drop=True)

                if st.button("Replace Learners Now", use_container_width=True):
                    replace_learners_from_df(DB_PATH, df_new)
                    save_learners_backup(get_learners_df(DB_PATH))
                    st.success("✅ Learners replaced.")
                    st.rerun()
        except Exception as e:
            st.error(f"Upload error: {e}")

