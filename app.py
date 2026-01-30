# app.py — Tutor Class Attendance Register 2026 (SQLite version)
# Tabs: Scan • Today • Grades • History • Tracking • Manage

import os
import base64
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

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

DB_DEFAULT = "app_v2.db"

DB_PATH = Path(os.environ.get("DB_PATH", DB_DEFAULT))

WHATSAPP_RECIPIENTS = ["+27836280453", "+27672291308"]

SEND_DAY_WEEKDAY = 5           # Saturday
SEND_AFTER_TIME = dtime(9, 0)  # 09:00

DEFAULT_GRADE_CAPACITY = 15
BACKUP_LEARNERS_CSV = "learners_backup.csv"

# ------------------ TIME HELPERS ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_labels():
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_label = f"{day}-{mon}"
    date_iso = n.strftime("%Y-%m-%d")
    time_str = n.strftime("%H:%M:%S")
    ts_iso = n.isoformat(timespec="seconds")
    return date_label, date_iso, time_str, ts_iso

def today_col_label() -> str:
    return today_labels()[0]

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

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=[
            "Name","Surname","Barcode","Grade","Area",
            "Sessions","Present","Absent","Attendance %","Last present"
        ])

    mat = df[date_cols].applymap(lambda x: 1 if str(x).strip() == "1" else 0)
    sessions = len(date_cols)
    present = mat.sum(axis=1)
    absent = sessions - present
    pct = (present / sessions * 100).round(1)

    last_present = []
    for _, row in mat.iterrows():
        idxs = [i for i,v in enumerate(row.tolist()) if v == 1]
        last_present.append(date_cols[max(idxs)] if idxs else "—")

    out = pd.DataFrame({
        "Name": df.get("Name",""),
        "Surname": df.get("Surname",""),
        "Barcode": df.get("Barcode",""),
        "Grade": df.get("Grade",""),
        "Area": df.get("Area",""),
        "Sessions": sessions,
        "Present": present,
        "Absent": absent,
        "Attendance %": pct,
        "Last present": last_present,
    })
    return out.sort_values(["Attendance %","Name","Surname"], ascending=[False,True,True]).reset_index(drop=True)

def get_present_absent(df: pd.DataFrame, date_col: str, grade=None):
    if df.empty or date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    filt = pd.Series(True, index=df.index)
    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)

    subset = df.loc[filt].copy()
    present = subset[subset[date_col].astype(str).str.strip() == "1"].copy()
    absent = subset[subset[date_col].astype(str).str.strip() != "1"].copy()
    return present, absent

# ------------------ AUTO SEND (BIRTHDAYS) ------------------
# (kept minimal here – your message sending code can be plugged back)
def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def run_auto_send(db_path: Path):
    # This prevents crashes; you can plug back WhatsApp sending later
    ensure_auto_send_table(db_path)
    _, date_iso, _, ts_iso = today_labels()

    if not should_auto_send(now_local()):
        return
    if already_sent_today(db_path, date_iso):
        return

    # Mark as sent (so it doesn’t repeat)
    mark_sent_today(db_path, date_iso, ts_iso)

# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown("""
<style>
/* Center title + make it readable */
.header-wrap {text-align:center; padding:14px 10px; border:1px solid #eee; border-radius:14px; background:#fff;}
.header-title {font-size:40px; font-weight:800; margin:6px 0; color:#111;}
.header-sub {font-size:14px; color:#444; margin:0;}
.small-help {font-size:13px; color:#666;}
/* Make tabs text clearer */
.stTabs [data-baseweb="tab"] {font-size:18px; font-weight:700;}
</style>
""", unsafe_allow_html=True)

# ------------------ DB INIT ------------------

init_db(DB_PATH)
seed_learners_from_csv_if_empty(DB_PATH)

# run auto send safely
try:
    run_auto_send(DB_PATH)
except Exception:
    pass

# ------------------ HEADER ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(f"""
<div class="header-wrap">
  {("<img src='data:image/png;base64," + logo_b64 + "' width='110' style='display:block;margin:0 auto 6px auto;'/>") if logo_b64 else ""}
  <div class="header-title">Tutor Class Attendance Register 2026</div>
  <p class="header-sub">Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b> · DB: <b>{DB_PATH.name}</b></p>
</div>
""", unsafe_allow_html=True)

st.write("")

# ------------------ LOAD WIDE SHEET ------------------

def load_sheet():
    df = get_wide_sheet(DB_PATH).fillna("").astype(str)
    return df

df = load_sheet()
date_cols = get_date_columns(df)

# ------------------ TABS ------------------

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])

# ================== TAB: SCAN ==================
with tabs[0]:
    st.subheader("Scan")

    date_label, date_iso, time_str, ts_iso = today_labels()

    # Show who is currently IN
    st.markdown("### Currently IN (Today)")
    try:
        cur_in = get_currently_in(DB_PATH, date_iso).fillna("").astype(str)
    except Exception:
        cur_in = pd.DataFrame(columns=["Name","Surname","Grade","Area","Barcode","Action","Time"])
    st.dataframe(cur_in, use_container_width=True, hide_index=True)

    st.markdown("---")

    st.markdown("### Scan or type barcode (auto-submit)")

    if "scan_value" not in st.session_state:
        st.session_state.scan_value = ""

    if "scan_status" not in st.session_state:
        st.session_state.scan_status = ""

    def process_scan():
        code = norm_barcode(st.session_state.scan_value)
        if not code:
            return

        # Ensure learner exists
        learners = get_learners_df(DB_PATH)
        known = code in learners["Barcode"].astype(str).tolist()

        if not known:
            st.session_state.scan_status = f"❌ Barcode not found: {code}"
            st.session_state.scan_value = ""
            return

        # Decide IN/OUT
        next_action = determine_next_action(DB_PATH, code, date_iso)

        # Always mark attendance present when scanned (IN or OUT)
        insert_present_mark(DB_PATH, code, date_label, date_iso, ts_iso)

        # Log IN/OUT action
        append_inout_log(DB_PATH, code, next_action, ts_iso, date_iso, time_str)

        st.session_state.scan_status = f"✅ {code} marked Present + {next_action}"
        st.session_state.scan_value = ""

    st.text_input(
        "Barcode",
        key="scan_value",
        placeholder="Scan barcode...",
        on_change=process_scan,
        label_visibility="collapsed"
    )

    if st.session_state.scan_status:
        st.info(st.session_state.scan_status)

    st.caption("Tip: Most barcode scanners send ENTER automatically — this triggers auto-submit.")

# ================== TAB: TODAY ==================
with tabs[1]:
    st.subheader("Today")

    date_label, date_iso, _, _ = today_labels()
    df = load_sheet()
    date_cols = get_date_columns(df)

    if date_label not in df.columns:
        st.warning("No attendance marks for today yet. Please scan learners first.")
    else:
        present, absent = get_present_absent(df, date_label)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"### Present ({len(present)})")
            st.dataframe(present[["Name","Surname","Grade","Area","Barcode",date_label]], use_container_width=True, hide_index=True)
        with c2:
            st.markdown(f"### Absent ({len(absent)})")
            st.dataframe(absent[["Name","Surname","Grade","Area","Barcode",date_label]], use_container_width=True, hide_index=True)

        # Download today
        today_export = df[["Name","Surname","Grade","Area","Barcode",date_label]].copy()
        st.download_button(
            "⬇️ Download Today's Attendance (CSV)",
            data=today_export.to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_{date_iso}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ================== TAB: GRADES ==================
with tabs[2]:
    st.subheader("Grades")

    df = load_sheet()
    date_cols = get_date_columns(df)

    if not date_cols:
        st.warning("No attendance marks yet (no date columns). Scan learners first.")
    else:
        selected_date = st.selectbox("Select date", options=list(reversed(date_cols)))
        grades = sorted([g for g in df["Grade"].astype(str).unique() if g.strip() != ""])

        summary_rows = []
        for g in grades:
            present, absent = get_present_absent(df, selected_date, grade=g)
            total = len(present) + len(absent)
            pct = round((len(present) / total * 100), 1) if total else 0.0
            summary_rows.append({
                "Grade": g,
                "Total Learners": total,
                "Present": len(present),
                "Absent": len(absent),
                "Attendance %": pct
            })

        summary = pd.DataFrame(summary_rows).sort_values("Grade").reset_index(drop=True)
        st.markdown("### Attendance % per Grade")
        st.dataframe(summary, use_container_width=True, hide_index=True)

        # Download grade summary
        st.download_button(
            "⬇️ Download Grade Summary (CSV)",
            data=summary.to_csv(index=False).encode("utf-8"),
            file_name=f"grade_summary_{selected_date}.csv",
            mime="text/csv",
            use_container_width=True
        )

        # Download full attendance for that date
        export = df[["Name","Surname","Grade","Area","Barcode",selected_date]].copy()
        st.download_button(
            "⬇️ Download Attendance for Selected Date (CSV)",
            data=export.to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_{selected_date}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ================== TAB: HISTORY ==================
with tabs[3]:
    st.subheader("History")

    df = load_sheet()
    date_cols = get_date_columns(df)

    if not date_cols:
        st.warning("No attendance history yet.")
    else:
        selected_date = st.selectbox("Choose a date to view", options=list(reversed(date_cols)), key="hist_date")
        present, absent = get_present_absent(df, selected_date)

        st.markdown(f"### Date: {selected_date}")
        st.write(f"Present: **{len(present)}** | Absent: **{len(absent)}**")

        st.dataframe(df[["Name","Surname","Grade","Area","Barcode",selected_date]], use_container_width=True, hide_index=True)

# ================== TAB: TRACKING ==================
with tabs[4]:
    st.subheader("Tracking")

    df = load_sheet()
    date_cols = get_date_columns(df)

    if not date_cols:
        st.warning("No tracking data yet (no date columns).")
    else:
        tracking = compute_tracking(df)
        st.dataframe(tracking, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Tracking Report (CSV)",
            data=tracking.to_csv(index=False).encode("utf-8"),
            file_name="tracking_report.csv",
            mime="text/csv",
            use_container_width=True
        )

# ================== TAB: MANAGE ==================
with tabs[5]:
    st.subheader("Manage Learners")

    st.markdown("### Current Learners")
    learners = get_learners_df(DB_PATH)
    edited = st.data_editor(learners, use_container_width=True, num_rows="dynamic")

    c1, c2 = st.columns(2)

    with c1:
        if st.button("💾 Save Learners", use_container_width=True):
            try:
                replace_learners_from_df(DB_PATH, edited)
                st.success("Saved learners ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with c2:
        del_code = st.text_input("Delete by Barcode", value="")
        if st.button("🗑️ Delete Learner", use_container_width=True):
            ok = delete_learner_by_barcode(DB_PATH, del_code)
            if ok:
                st.success("Deleted ✅")
                st.rerun()
            else:
                st.warning("Barcode not found.")

    st.markdown("---")
    st.markdown("### Upload Learners CSV (replace all)")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            df_up = pd.read_csv(up).fillna("").astype(str)
            replace_learners_from_df(DB_PATH, df_up)
            st.success("Uploaded + replaced learners ✅")
            st.rerun()
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.download_button(
        "⬇️ Download Learners (CSV)",
        data=learners.to_csv(index=False).encode("utf-8"),
        file_name="learners.csv",
        mime="text/csv",
        use_container_width=True
    )

    st.markdown("---")
    st.markdown("### Download Full Attendance Sheet (wide)")
    wide = load_sheet()
    st.download_button(
        "⬇️ Download Full Wide Sheet (CSV)",
        data=wide.to_csv(index=False).encode("utf-8"),
        file_name="attendance_wide_sheet.csv",
        mime="text/csv",
        use_container_width=True
    )

