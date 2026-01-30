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

WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

SEND_DAY_WEEKDAY = 5           # Saturday
SEND_AFTER_TIME = dtime(9, 0)  # 09:00

BACKUP_LEARNERS_CSV = "learners_backup.csv"

META_WA_TOKEN = (st.secrets.get("META_WA_TOKEN", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = (st.secrets.get("META_WA_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = (st.secrets.get("META_WA_API_VERSION", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_API_VERSION", "v22.0").strip()


# ------------------ TIME HELPERS ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_labels():
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_col = f"{day}-{mon}"
    date_iso = n.strftime("%Y-%m-%d")
    ts_iso = n.isoformat(timespec="seconds")
    return date_col, date_iso, ts_iso

def get_date_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        parts = str(c).split("-")
        if len(parts) == 2 and parts[0].isdigit():
            cols.append(c)

    def _key(x: str):
        try:
            return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except Exception:
            return 999

    return sorted(cols, key=_key)


# ------------------ BACKUP / RESTORE LEARNERS ------------------

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
        backup_path = Path(BACKUP_LEARNERS_CSV)
        if not backup_path.exists():
            return
        backup_df = pd.read_csv(backup_path).fillna("").astype(str)
        required = ["Name", "Surname", "Barcode"]
        if not all(c in backup_df.columns for c in required):
            return
        for c in ["Grade", "Area", "Date Of Birth"]:
            if c not in backup_df.columns:
                backup_df[c] = ""
        backup_df = backup_df[["Name","Surname","Barcode","Grade","Area","Date Of Birth"]].copy()
        backup_df["Barcode"] = backup_df["Barcode"].astype(str).map(norm_barcode)
        backup_df = backup_df[backup_df["Barcode"] != ""].reset_index(drop=True)
        replace_learners_from_df(DB_PATH, backup_df)
    except Exception:
        pass


# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Grade","Area","Present","Absent","Attendance %","Last present"])

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
        "Name": df.get("Name",""),
        "Surname": df.get("Surname",""),
        "Barcode": df.get("Barcode",""),
        "Grade": df.get("Grade",""),
        "Area": df.get("Area",""),
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present
    })

    return result.sort_values(["Grade","Attendance %","Name"], ascending=[True,False,True]).reset_index(drop=True)


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
            "Name": str(r.get("Name","")),
            "Surname": str(r.get("Surname","")),
            "Grade": str(r.get("Grade","")),
            "DOB": str(r.get("Date Of Birth","")),
            "Kind": kind,
        })
    return results

def build_birthday_message(birthdays: list[dict]) -> str:
    if not birthdays:
        return "No birthdays this week or in the next 7 days."

    lines = ["🎂 Tutor Class Birthdays (this week)"]
    for b in birthdays:
        full_name = f"{b['Name']} {b['Surname']}".strip()
        grade = b.get("Grade","").strip()
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
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code}) {err.get('message','')}")
        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    return (True, " | ".join(results)) if sent_any else (False, " | ".join(results) if results else "No recipients.")


# ------------------ AUTO SEND (BIRTHDAYS) ------------------

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def run_auto_send():
    ensure_auto_send_table(DB_PATH)

    now = now_local()
    _, date_iso, ts_iso = today_labels()

    if not should_auto_send(now):
        return
    if already_sent_today(DB_PATH, date_iso):
        return

    df_now = get_wide_sheet(DB_PATH)
    birthdays = get_birthdays_for_week(df_now)

    # mark sent even if none (so it won't keep retrying)
    if not birthdays:
        mark_sent_today(DB_PATH, date_iso, ts_iso)
        return

    msg = build_birthday_message(birthdays)
    ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
    if ok:
        mark_sent_today(DB_PATH, date_iso, ts_iso)
        st.sidebar.success("✅ Auto WhatsApp sent today")
    else:
        st.sidebar.warning(f"⚠️ Auto WhatsApp failed: {info}")


# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown(
    """
    <style>
      .center-title { text-align: center; font-size: 2.2rem; font-weight: 700; margin: 0.1rem 0 0.3rem 0; color: #111; }
      .center-sub { text-align: center; font-size: 0.95rem; color: #555; margin-bottom: 0.8rem; }
      .card { padding: 14px 16px; border: 1px solid #eee; border-radius: 14px; background: #fff; }
      .small-help { font-size: 13px; color: #666; line-height: 1.4; }
      /* Make tab labels clearer */
      button[data-baseweb="tab"] { font-size: 15px !important; }
    </style>
    """,
    unsafe_allow_html=True
)


# ------------------ DB INIT / RESTORE / SEED ------------------

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

date_col, date_iso, ts_iso = today_labels()

st.markdown(
    f"""
    <div class="card">
      <div style="display:flex; justify-content:center; margin-bottom:6px;">
        {"<img src='data:image/png;base64," + logo_b64 + "' width='120'/>" if logo_b64 else ""}
      </div>
      <div class="center-title">Tutor Class Attendance Register 2026</div>
      <div class="center-sub">
        Today: <b>{date_col}</b> · Timezone: <b>{APP_TZ}</b> · DB: <b>{DB_PATH.name}</b>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")


# ------------------ SIDEBAR (OPTIONAL) ------------------

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
    test_msg = st.text_area("Message", value="Hello! Test message from Tutor Class Attendance ✅")
    if st.button("Send Test WhatsApp", use_container_width=True):
        ok, info = send_whatsapp_message([test_to], test_msg)
        st.success(info) if ok else st.error(info)


# ------------------ LOAD DATA ------------------

def load_wide():
    return get_wide_sheet(DB_PATH)

df = load_wide()
date_cols = get_date_columns(df)


# ------------------ TABS ------------------

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])


# ========== TAB 1: SCAN (AUTO SUBMIT) ==========

def handle_scan():
    raw = st.session_state.get("scan_input", "")
    code = norm_barcode(raw)
    if not code:
        return

    # Ensure today's class date exists
    add_class_date(DB_PATH, date_iso, date_col)

    # Mark present
    insert_present_mark(DB_PATH, date_iso, code, present=1, ts_iso=ts_iso)

    # IN/OUT toggle
    action = determine_next_action(DB_PATH, date_iso, code)
    append_inout_log(DB_PATH, date_iso, code, action=action, ts_iso=ts_iso)

    st.session_state["last_scan"] = f"✅ {code} marked Present + {action}"
    st.session_state["scan_input"] = ""  # clear for next scan

with tabs[0]:
    st.subheader("Scan (Auto Submit)")
    st.caption("Scan a barcode (or type it). It will submit automatically.")

    st.text_input(
        "Scan or type barcode here",
        key="scan_input",
        placeholder="Scan barcode...",
        on_change=handle_scan,
    )

    if st.session_state.get("last_scan"):
        st.success(st.session_state["last_scan"])

    st.divider()

    st.subheader("Currently IN (Today)")
    try:
        currently_in = get_currently_in(DB_PATH, date_iso)
        if currently_in.empty:
            st.info("No one is currently IN yet.")
        else:
            st.dataframe(currently_in, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Currently IN error: {e}")


# ========== TAB 2: TODAY ==========

with tabs[1]:
    st.subheader("Today")

    df_today = load_wide()
    if df_today.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        if date_col not in df_today.columns:
            st.info("No attendance marks yet for today. Scan learners first.")
        else:
            total = len(df_today)
            present = (df_today[date_col].astype(str).str.strip() == "1").sum()
            absent = total - present
            pct = round((present / total * 100), 1) if total else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Learners", total)
            c2.metric("Present", int(present))
            c3.metric("Absent", int(absent))
            c4.metric("Attendance %", f"{pct}%")

            present_df = df_today[df_today[date_col].astype(str).str.strip() == "1"][["Name","Surname","Barcode","Grade","Area"]]
            absent_df = df_today[df_today[date_col].astype(str).str.strip() != "1"][["Name","Surname","Barcode","Grade","Area"]]

            st.write("")
            st.subheader("Present List")
            st.dataframe(present_df, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download Present (CSV)",
                present_df.to_csv(index=False).encode("utf-8"),
                file_name=f"present_{date_iso}.csv",
                mime="text/csv",
                use_container_width=True
            )

            st.write("")
            st.subheader("Absent List")
            st.dataframe(absent_df, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download Absent (CSV)",
                absent_df.to_csv(index=False).encode("utf-8"),
                file_name=f"absent_{date_iso}.csv",
                mime="text/csv",
                use_container_width=True
            )


# ========== TAB 3: GRADES (PERCENT PER GRADE + DOWNLOADS) ==========

with tabs[2]:
    st.subheader("Grades")

    df_g = load_wide()
    if df_g.empty:
        st.warning("No learners yet.")
    else:
        # Choose which date to analyze
        chosen_date = st.selectbox("Choose a date", options=[date_col] + [c for c in date_cols if c != date_col] if date_cols else [date_col])

        if chosen_date not in df_g.columns:
            st.info("No attendance data for that date yet.")
        else:
            df_g["__present__"] = df_g[chosen_date].astype(str).str.strip().eq("1").astype(int)
            df_g["Grade"] = df_g["Grade"].astype(str)

            summary = (
                df_g.groupby("Grade", dropna=False)
                .agg(
                    Total=("Barcode","count"),
                    Present=("__present__","sum"),
                )
                .reset_index()
            )
            summary["Attendance %"] = (summary["Present"] / summary["Total"] * 100).round(1)

            st.dataframe(summary, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download Grade Summary (CSV)",
                summary.to_csv(index=False).encode("utf-8"),
                file_name=f"grade_summary_{chosen_date}.csv",
                mime="text/csv",
                use_container_width=True
            )

            st.divider()

            st.subheader("Download Full Attendance Sheet (with % per learner)")
            tracking = compute_tracking(df_g.drop(columns=["__present__"], errors="ignore"))
            st.dataframe(tracking, use_container_width=True, hide_index=True)

            st.download_button(
                "⬇️ Download Full Tracking (CSV)",
                tracking.to_csv(index=False).encode("utf-8"),
                file_name="tracking_all.csv",
                mime="text/csv",
                use_container_width=True
            )


# ========== TAB 4: HISTORY (EDIT MARKS) ==========

with tabs[3]:
    st.subheader("History (Edit attendance)")

    df_h = load_wide()
    if df_h.empty:
        st.warning("No learners yet.")
    else:
        if not date_cols and date_col not in df_h.columns:
            st.info("No attendance dates yet. Scan first.")
        else:
            options = date_cols if date_cols else [date_col]
            selected = st.selectbox("Select date to view/edit", options=options, index=(options.index(date_col) if date_col in options else 0))

            if selected not in df_h.columns:
                st.info("No attendance data for this date yet.")
            else:
                edit_df = df_h[["Barcode","Name","Surname","Grade","Area", selected]].copy()
                edit_df.rename(columns={selected: "Present (1=Yes)"}, inplace=True)
                edit_df["Present (1=Yes)"] = edit_df["Present (1=Yes)"].astype(str).str.strip().apply(lambda x: "1" if x == "1" else "")

                edited = st.data_editor(edit_df, use_container_width=True, hide_index=True, num_rows="fixed")

                if st.button("💾 Save Changes", use_container_width=True):
                    # Save: update attendance marks for that date
                    # Convert label -> we need date_iso. We’ll map by re-adding session using today's iso only if today.
                    # Practical approach: Only allow editing for today’s real ISO date.
                    # If you want editing for any date, we must store label->iso mapping.
                    if selected != date_col:
                        st.error("Editing past dates needs a label->ISO mapping. For now, edit only today's date.")
                    else:
                        add_class_date(DB_PATH, date_iso, date_col)
                        for _, r in edited.iterrows():
                            b = norm_barcode(r["Barcode"])
                            present_val = 1 if str(r["Present (1=Yes)"]).strip() == "1" else 0
                            insert_present_mark(DB_PATH, date_iso, b, present=present_val, ts_iso=ts_iso)
                        st.success("Saved.")


# ========== TAB 5: TRACKING (ATTENDANCE % PER LEARNER) ==========

with tabs[4]:
    st.subheader("Tracking")

    df_t = load_wide()
    if df_t.empty:
        st.warning("No learners yet.")
    else:
        tracking = compute_tracking(df_t)
        st.dataframe(tracking, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Tracking (CSV)",
            tracking.to_csv(index=False).encode("utf-8"),
            file_name="tracking.csv",
            mime="text/csv",
            use_container_width=True
        )


# ========== TAB 6: MANAGE (ADD/EDIT/DELETE + BACKUP) ==========

with tabs[5]:
    st.subheader("Manage Learners")

    df_m = get_learners_df(DB_PATH).fillna("").astype(str)

    st.write("### Edit Learners")
    edited = st.data_editor(df_m, use_container_width=True, hide_index=True, num_rows="dynamic")

    colA, colB = st.columns(2)
    with colA:
        if st.button("💾 Save Learners Changes", use_container_width=True):
            try:
                replace_learners_from_df(DB_PATH, edited)
                save_learners_backup(edited)
                st.success("Learners saved + backed up.")
                st.rerun()
            except Exception as e:
                st.error(f"Save error: {e}")

    with colB:
        if st.button("⬇️ Download Learners (CSV)", use_container_width=True):
            st.download_button(
                "Download",
                edited.to_csv(index=False).encode("utf-8"),
                file_name="learners.csv",
                mime="text/csv",
                use_container_width=True
            )

    st.divider()

    st.write("### Delete Learner")
    del_code = st.text_input("Barcode to delete", placeholder="Scan or type barcode...")
    if st.button("🗑️ Delete", use_container_width=True):
        delete_learner_by_barcode(DB_PATH, del_code)
        st.success("Deleted.")
        st.rerun()
