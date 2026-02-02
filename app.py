# app.py — Tutor Class Attendance Register 2026 (SQLite version)

import os
import base64
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import requests

from db import (
    init_db,
    get_wide_sheet,
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
    ensure_auto_send_table,
    already_sent_today,
    mark_sent_today,
)

# ------------------ CONFIG ------------------

APP_TZ = os.environ.get("APP_TIMEZONE", "Africa/Johannesburg")
TZ = ZoneInfo(APP_TZ)

DB_DEFAULT = os.environ.get("DB_DEFAULT", "app.db")

WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

SEND_DAY_WEEKDAY = 5          # Saturday
SEND_AFTER_TIME = dtime(9, 0) # 09:00
DEFAULT_GRADE_CAPACITY = 15

BACKUP_LEARNERS_CSV = "learners_backup.csv"

META_WA_TOKEN = os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = os.environ.get("META_WA_API_VERSION", "v22.0").strip()

# ------------------ UTILITIES ------------------

def now_local() -> datetime:
    return datetime.now(TZ)

def today_labels():
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_col = f"{day}-{mon}"
    date_str = n.strftime("%Y-%m-%d")
    time_str = n.strftime("%H:%M:%S")
    ts = n.isoformat(timespec="seconds")
    return date_col, date_str, time_str, ts

def today_col_label() -> str:
    return today_labels()[0]

def is_saturday_class_day() -> bool:
    return now_local().weekday() == 5

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def label_for_row(r: pd.Series) -> str:
    name = str(r.get("Name", "")).strip()
    surname = str(r.get("Surname", "")).strip()
    return (name + " " + surname).strip() or str(r.get("Barcode", "")).strip()

def get_date_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        parts = str(c).split("-")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2:
            cols.append(c)

    def _key(x):
        try:
            return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except Exception:
            return 999

    return sorted(cols, key=_key)

def unique_sorted(series: pd.Series):
    vals = sorted([v for v in series.astype(str).unique() if v.strip() and v != "nan"])
    return ["(All)"] + vals

# ------------------ PERMANENT BACKUP ------------------

def save_learners_backup(df_learners: pd.DataFrame):
    try:
        df_learners.to_csv(BACKUP_LEARNERS_CSV, index=False)
    except Exception:
        pass

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
        grade = b.get("Grade", "")
        label = "🎉 Today" if b["Kind"] == "today" else ("🎂 Belated" if b["Kind"] == "belated" else "🎁 Upcoming")
        extra = f" (Grade {grade})" if grade else ""
        lines.append(f"{label}: {full_name}{extra} — DOB {b['DOB']}")
    return "\n".join(lines)

# ------------------ WHATSAPP (META CLOUD) ------------------

def _normalize_e164(n: str) -> str:
    n = str(n).strip()
    if n.startswith("whatsapp:"):
        n = n.replace("whatsapp:", "").strip()
    return n

def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    if not META_WA_TOKEN or not META_WA_PHONE_NUMBER_ID:
        return False, "Missing META_WA_TOKEN / META_WA_PHONE_NUMBER_ID."

    url = f"https://graph.facebook.com/{META_WA_API_VERSION}/{META_WA_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {META_WA_TOKEN}", "Content-Type": "application/json"}

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
                emsg = err.get("message", str(data))
                ecode = err.get("code", "")
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code} code {ecode} - {emsg})")

        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    return (True, " | ".join(results)) if sent_any else (False, " | ".join(results))

# ------------------ EXPORT (GRADES) ------------------

def build_grades_export(df: pd.DataFrame, date_sel: str, grades: list[str], grade_capacity: int):
    summary_rows = []
    for g in grades:
        mask = df["Grade"].astype(str) == g if "Grade" in df.columns else pd.Series(False, index=df.index)
        present = (df.loc[mask, date_sel].astype(str).str.strip() == "1").sum() if date_sel in df.columns else 0
        pct = (present / grade_capacity * 100) if grade_capacity else 0.0
        absent_vs_cap = max(0, grade_capacity - int(present))

        summary_rows.append({
            "Section": "SUMMARY",
            "Date": date_sel,
            "Grade": g,
            "Capacity (fixed)": int(grade_capacity),
            "Present": int(present),
            "Absent (vs capacity)": int(absent_vs_cap),
            "Attendance %": round(pct, 1),
        })

    summary_df = pd.DataFrame(summary_rows)

    learners = df.copy()
    learners["Section"] = "LEARNERS"
    learners["Date"] = date_sel

    if date_sel in learners.columns:
        learners["Status"] = learners[date_sel].astype(str).apply(lambda x: "Present" if x.strip() == "1" else "Absent")
    else:
        learners["Status"] = "Absent"

    learners_export = learners[["Section","Date","Grade","Name","Surname","Barcode","Status"]].copy()

    combined_export_df = pd.concat([summary_df, learners_export], ignore_index=True)
    return summary_df.drop(columns=["Section"]), combined_export_df

# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    date_cols = get_date_columns(df)
    sessions = len(date_cols)

    base_cols = ["Name", "Surname", "Barcode", "Grade", "Area"]
    for c in base_cols:
        if c not in df.columns:
            df[c] = ""

    rows = []
    for _, r in df.iterrows():
        present = 0
        last_present = ""

        for d in date_cols:
            if str(r.get(d, "")).strip() == "1":
                present += 1
                last_present = d

        absent = sessions - present
        pct = (present / sessions * 100) if sessions else 0.0

        rows.append({
            "Name": str(r.get("Name", "")).strip(),
            "Surname": str(r.get("Surname", "")).strip(),
            "Barcode": str(r.get("Barcode", "")).strip(),
            "Grade": str(r.get("Grade", "")).strip(),
            "Area": str(r.get("Area", "")).strip(),
            "Sessions": sessions,
            "Present": present,
            "Absent": absent,
            "Attendance %": round(pct, 1),
            "Last present": last_present,
        })

    out = pd.DataFrame(rows)
    return out.sort_values(["Grade", "Surname", "Name"], na_position="last")

# ------------------ DB LOAD ------------------

def load_wide_sheet(db_path: Path) -> pd.DataFrame:
    return get_wide_sheet(db_path)

# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"]  { font-size: 17px !important; }
main .block-container { padding-top: 1rem; }
button[data-baseweb="tab"] { font-size: 16px !important; padding-top: 10px !important; padding-bottom: 10px !important; }
.section-card { background:#fff; padding:18px 22px; border-radius:16px; border:1px solid #e5e7eb; box-shadow:0 8px 20px rgba(15,23,42,0.04); margin-bottom: 1.2rem; }
.stat-card { padding:14px 18px; border:1px solid #eee; border-radius:14px; background:#fafafa; }
.kpi { font-size:34px !important; font-weight:800; }
</style>
""", unsafe_allow_html=True)

# ------------------ HEADER ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(f"""
<div style="text-align:center; margin: 0.25rem 0 0.8rem 0;">
  {("<img src='data:image/png;base64," + logo_b64 + "' width='120' style='margin-bottom: 8px;'/>") if logo_b64 else ""}
  <h2 style="margin: 0.2rem 0; font-size: 2.2rem; font-weight: 800;">
    Tutor Class Attendance Register 2026
  </h2>
  <p style="margin:0; color:#666; font-size:14px;">
    Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b>
  </p>
</div>
""", unsafe_allow_html=True)

# ------------------ SIDEBAR ------------------

with st.sidebar:
    st.header("Settings")

    db_path_str = st.text_input("Database file path", DB_DEFAULT)
    db_path = Path(db_path_str).expanduser()

    init_db(db_path)
    ensure_auto_send_table(db_path)

    # 🔍 DEBUG: show real DB location
    st.write("Working folder:", Path.cwd())
    st.write("DB full path:", db_path.resolve())

    # 🔍 DEBUG: check DB contents
    import sqlite3
    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM learners")
        learners_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM attendance")
        attendance_count = cur.fetchone()[0]
        con.close()

        st.write("Learners in DB:", learners_count)
        st.write("Attendance marks in DB:", attendance_count)
    except Exception as e:
        st.error(f"DB check failed: {e}")

    # (leave the rest of your sidebar code below)


# ------------------ AUTO SEND BIRTHDAYS ------------------

try:
    now = now_local()
    _, date_str, _, ts_iso = today_labels()

    if (not already_sent_today(db_path, date_str)) and should_auto_send(now):
        df_now = get_learners_df(db_path).fillna("").astype(str)  # ✅ learners only
        birthdays = get_birthdays_for_week(df_now)

        if birthdays:
            msg = build_birthday_message(birthdays)
            ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)

            if ok:
                mark_sent_today(db_path, date_str, ts_iso)
                st.sidebar.success("✅ Auto WhatsApp sent today")
            else:
                st.sidebar.warning(f"⚠️ Auto WhatsApp failed: {info}")
        else:
            st.sidebar.info("No birthdays to send today.")
except Exception as e:
    st.sidebar.warning(f"⚠️ Auto send error: {e}")

# ------------------ TABS ------------------

tabs = st.tabs(["📷 Scan", "📅 Today", "🏫 Grades", "📚 History", "📈 Tracking", "🛠 Manage"])

# ------------------ SCAN TAB ------------------

with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    date_col, date_str, time_str, ts_iso = today_labels()
    add_class_date(db_path, date_col)

    df_scan = load_wide_sheet(db_path)
    if date_col not in df_scan.columns:
        df_scan[date_col] = ""

    total_learners = len(df_scan)
    present_today = (df_scan[date_col].astype(str).str.strip() == "1").sum() if total_learners else 0
    absent_today = total_learners - present_today

    st.subheader("📊 Today")
    k1, k2, k3 = st.columns(3)
    k1.markdown(f'<div class="stat-card"><b>Total learners</b><div class="kpi">{total_learners}</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="stat-card"><b>Present today</b><div class="kpi">{present_today}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="stat-card"><b>Absent today</b><div class="kpi">{absent_today}</div></div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("📷 Scan learner")

    def mark_scan_in_out(barcode: str) -> tuple[bool, str]:
        barcode = str(barcode).strip()
        if not barcode:
            return False, "Empty scan."

        df = load_wide_sheet(db_path)
        if df.empty or "Barcode" not in df.columns:
            return False, "No learners in database yet. Add learners in Manage tab first."

        matches = df.index[df["Barcode"].astype(str).apply(norm_barcode) == norm_barcode(barcode)].tolist()
        if not matches:
            return False, "Barcode not found. Add it to the correct learner in Manage."

        date_label, dstr, tstr, ts = today_labels()
        add_class_date(db_path, date_label)

        msgs = []
        for idx in matches:
            row = df.loc[idx]
            real_barcode = str(row.get("Barcode", "")).strip()
            action = determine_next_action(db_path, real_barcode, dstr)

            insert_present_mark(db_path, date_label, dstr, tstr, real_barcode)

            append_inout_log(
                db_path=db_path,
                ts_iso=ts,
                date_str=dstr,
                time_str=tstr,
                barcode=real_barcode,
                name=str(row.get("Name", "")),
                surname=str(row.get("Surname", "")),
                action=action
            )

            msgs.append(f"{label_for_row(row)} [{real_barcode}] marked {action} at {tstr} ({dstr}).")

        current_in = get_currently_in(db_path, dstr)
        msgs.append("")
        msgs.append(f"Currently IN today ({dstr}): {len(current_in)}")
        return True, "\n".join(msgs)

    def handle_scan():
        scan_value = st.session_state.get("scan_box", "").strip()
        if not scan_value:
            return

        if not is_saturday_class_day():
            st.session_state["scan_feedback"] = ("error", "Today is not a class day. Scans are only allowed on Saturdays.")
        else:
            ok, msg = mark_scan_in_out(scan_value)
            st.session_state["scan_feedback"] = ("ok" if ok else "error", msg)

        st.session_state["scan_box"] = ""

    st.text_input("Scan barcode", key="scan_box", on_change=handle_scan, placeholder="Focus here and scan…")

    fb = st.session_state.pop("scan_feedback", None)
    if fb:
        status, msg = fb
        (st.success if status == "ok" else st.error)(msg)

    st.divider()
    current_in = get_currently_in(db_path, date_str)
    st.subheader(f"🟢 Currently IN today ({date_str})")
    st.dataframe(current_in if not current_in.empty else pd.DataFrame(), use_container_width=True, height=260)

    st.markdown('</div>', unsafe_allow_html=True)

# ------------------ TODAY TAB ------------------

with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    today_col, _, _, _ = today_labels()
    st.subheader(f"Today's Attendance — {today_col}")

    df_learners = get_learners_df(db_path).fillna("").astype(str)  # ✅ learners source
    birthdays = get_birthdays_for_week(df_learners)

    if birthdays:
        st.markdown("### 🎂 Birthdays around this week")
        for b in birthdays:
            full_name = f"{b['Name']} {b['Surname']}".strip()
            grade = b.get("Grade", "")
            tag = "🎉 Happy Birthday" if b["Kind"] == "today" else ("🎂 Belated" if b["Kind"] == "belated" else "🎁 Upcoming")
            extra = f" (Grade {grade})" if grade else ""
            st.write(f"{tag}: {full_name}{extra} — DOB: {b['DOB']}")
    else:
        st.caption("No birthdays this week or in the next 7 days.")

    st.markdown('</div>', unsafe_allow_html=True)

# ------------------ GRADES TAB ------------------

with tabs[2]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Grade Attendance by Saturday")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet. Scan at least 1 learner to create the first class date.")
    else:
        date_sel = st.selectbox("Choose a Saturday", list(reversed(date_cols)), key="grade_date")
        grades = ["5", "6", "7", "8"]

        summary_df, combined_export_df = build_grades_export(
            df=df,
            date_sel=date_sel,
            grades=grades,
            grade_capacity=int(grade_capacity)
        )

        # KPI cards
        k_cols = st.columns(len(grades))
        for i, g in enumerate(grades):
            row = summary_df[summary_df["Grade"].astype(str) == g].iloc[0]
            pct_str = f"{float(row['Attendance %']):.1f}%"
            with k_cols[i]:
                st.markdown(
                    f'<div class="stat-card"><b>Grade {g}</b>'
                    f'<div class="kpi">{pct_str}</div>'
                    f'<div style="font-size:12px;color:#555;">Present: {int(row["Present"])} / {int(grade_capacity)}</div></div>',
                    unsafe_allow_html=True,
                )

        st.markdown(f"**Summary for {date_sel}**")
        st.dataframe(summary_df, use_container_width=True, height=220)

        learners_view = combined_export_df[combined_export_df["Section"] == "LEARNERS"][["Date","Grade","Name","Surname","Barcode","Status"]]
        st.markdown(f"**Learner list for {date_sel} (all grades)**")
        st.dataframe(learners_view, use_container_width=True, height=360)

        st.download_button(
            "Download FULL grade report (Summary + Learners) — ONE CSV",
            data=combined_export_df.to_csv(index=False).encode("utf-8"),
            file_name=f"grade_report_{date_sel}.csv",
            mime="text/csv",
            use_container_width=True,
            key="grades_dl_full"
        )

    st.markdown('</div>', unsafe_allow_html=True)

# ------------------ HISTORY TAB ------------------

with tabs[3]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("History")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet.")
    else:
        date_sel = st.selectbox("Choose a date", list(reversed(date_cols)))
        view = df[["Name","Surname","Barcode","Grade","Area"]].copy()
        view["Status"] = df[date_sel].astype(str).apply(lambda x: "Present" if str(x).strip() == "1" else "Absent")
        st.dataframe(view, use_container_width=True)
        st.download_button(
            "Download this date (CSV)",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_{date_sel}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)

# ------------------ TRACKING TAB ------------------

with tabs[4]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Tracking (per learner)")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet. Scan at least 1 learner on a Saturday.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            grade_sel = st.selectbox(
                "Filter by Grade",
                unique_sorted(df["Grade"]) if "Grade" in df.columns else ["(All)"],
                key="track_grade"
            )
        with fc2:
            area_sel = st.selectbox(
                "Filter by Area",
                unique_sorted(df["Area"]) if "Area" in df.columns else ["(All)"],
                key="track_area"
            )
        with fc3:
            search = st.text_input("Search name/barcode", key="track_search")

        subset = df.copy()

        if grade_sel != "(All)" and "Grade" in subset.columns:
            subset = subset[subset["Grade"].astype(str) == str(grade_sel)]
        if area_sel != "(All)" and "Area" in subset.columns:
            subset = subset[subset["Area"].astype(str) == str(area_sel)]

        if search.strip():
            q = search.strip().lower()
            subset = subset[subset.apply(
                lambda r: q in str(r.get("Name", "")).lower()
                or q in str(r.get("Surname", "")).lower()
                or q in str(r.get("Barcode", "")).lower(),
                axis=1
            )]

        metrics = compute_tracking(subset) if len(subset) else pd.DataFrame()

        st.write(f"Total learners: **{len(metrics)}**  |  Sessions counted: **{len(date_cols)}**")

        if not metrics.empty:
            show_cols = ["Name","Surname","Barcode","Grade","Area","Sessions","Present","Absent","Attendance %","Last present"]
            st.dataframe(metrics[show_cols], use_container_width=True, height=420)

            st.download_button(
                "Download tracking report (CSV)",
                data=metrics[show_cols].to_csv(index=False).encode("utf-8"),
                file_name="attendance_tracking_report.csv",
                mime="text/csv",
                use_container_width=True,
                key="track_dl"
            )

    st.markdown('</div>', unsafe_allow_html=True)

# ------------------ MANAGE TAB ------------------

with tabs[5]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Manage Learners / Barcodes")

    df = get_learners_df(db_path).fillna("").astype(str)
    if "Date Of Birth" not in df.columns:
        df["Date Of Birth"] = ""

    st.markdown("### ✅ Current learners")
    st.dataframe(df, use_container_width=True, height=320)

    st.divider()
    st.markdown("### ➕ Add a new learner")
    c1, c2, c3 = st.columns(3)
    with c1:
        new_name = st.text_input("Name", key="new_name")
        new_surname = st.text_input("Surname", key="new_surname")
    with c2:
        new_barcode = st.text_input("Barcode", key="new_barcode")
        new_grade = st.text_input("Grade", key="new_grade")
    with c3:
        new_area = st.text_input("Area", key="new_area")
        new_dob = st.text_input("Date Of Birth (e.g. 31-Jan-13)", key="new_dob")

    if st.button("Add learner", use_container_width=True):
        if not new_barcode.strip():
            st.error("Barcode is required.")
        else:
            df2 = df.copy()
            df2.loc[len(df2)] = {
                "Barcode": new_barcode.strip(),
                "Name": new_name.strip(),
                "Surname": new_surname.strip(),
                "Grade": new_grade.strip(),
                "Area": new_area.strip(),
                "Date Of Birth": new_dob.strip(),
            }
            replace_learners_from_df(db_path, df2)
            st.success("✅ Learner added. Refreshing…")
            st.rerun()

    st.divider()
    st.markdown("### 🗑 Delete learner by barcode")
    del_code = st.text_input("Barcode to delete", key="del_code")
    if st.button("Delete learner", use_container_width=True):
        if not del_code.strip():
            st.error("Enter a barcode.")
        else:
            n = delete_learner_by_barcode(db_path, del_code.strip())
            if n:
                st.success(f"✅ Deleted {n} learner(s). Refreshing…")
                st.rerun()
            else:
                st.warning("Barcode not found.")

    st.divider()
    st.markdown("### 📤 Import / Replace learners from CSV (attendance_clean.csv format)")
    st.caption("Upload CSV with columns: Name, Surname, Barcode, Grade, Area, Date Of Birth")
    up = st.file_uploader("Upload CSV", type=["csv"], key="csv_up")
    if up is not None:
        try:
            imp = pd.read_csv(up).fillna("").astype(str)
            imp.columns = [c.strip() for c in imp.columns]
            required = ["Name", "Surname", "Barcode"]
            if not all(c in imp.columns for c in required):
                st.error("CSV missing required columns: Name, Surname, Barcode")
            else:
                for c in ["Grade", "Area", "Date Of Birth"]:
                    if c not in imp.columns:
                        imp[c] = ""
                imp = imp[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]]
                st.dataframe(imp.head(20), use_container_width=True)
                if st.button("REPLACE database learners with this CSV", type="primary", use_container_width=True):
                    replace_learners_from_df(db_path, imp)
                    st.success("✅ Imported successfully. Refreshing…")
                    st.rerun()
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.divider()
    st.markdown("### 💬 WhatsApp Test (manual send)")
    test_msg = st.text_area("Message", value="Test message from Tutor Class Attendance Register ✅", height=100)
    test_to = st.text_input("Send to (single number in +27... format)", value=WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "")

    if st.button("Send WhatsApp test now", use_container_width=True):
        ok, info = send_whatsapp_message([test_to], test_msg)
        if ok:
            st.success(f"✅ Sent. {info}")
        else:
            st.error(f"❌ Failed. {info}")

    st.markdown('</div>', unsafe_allow_html=True)

