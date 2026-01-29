# app.py — Tutor Class Attendance Register 2026 (SQLite version)
# Tabs: Scan • Today • Grades • History • Tracking • Manage

import os
import json
import base64
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import altair as alt

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
    seed_learners_from_csv_if_empty,   # ✅ ADD THIS
)

# ✅ Auto-send setup (runs after db_path exists)
#ensure_auto_send_table(db_path)

def should_auto_send(now: datetime) -> bool:
    # Saturday only
    if now.weekday() != SEND_DAY_WEEKDAY:
        return False
    # After 09:00 only
    return now.time() >= SEND_AFTER_TIME

# ✅ Auto-send birthdays
try:
    now = now_local()
    date_col, date_str, _, ts_iso = today_labels()

    if (not already_sent_today(db_path, date_str)) and should_auto_send(now):
        df_now = load_wide_sheet(db_path)
        birthdays = get_birthdays_for_week(df_now)
        msg = build_birthday_message(birthdays)

        ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)

        if ok:
            mark_sent_today(db_path, date_str, ts_iso)
            st.sidebar.success("✅ Auto WhatsApp sent today")
        else:
            st.sidebar.warning(f"⚠️ Auto WhatsApp failed: {info}")

except Exception as e:
    st.sidebar.warning(f"⚠️ Auto send error: {e}")


# ------------------ AUTO SEND (Meta WhatsApp) ------------------
# Runs whenever someone opens/refreshes the app.
# Sends once per day (stored in SQLite).
import sqlite3
from datetime import time as dtime
from db import ensure_auto_send_table
ensure_auto_send_table(db_path)


def ensure_auto_send_table(db_path: Path):
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_send_log (
            send_date TEXT PRIMARY KEY,
            sent_at   TEXT
        )
    """)
    con.commit()
    con.close()

def already_sent_today(db_path: Path, date_str: str) -> bool:
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("SELECT 1 FROM auto_send_log WHERE send_date = ?", (date_str,))
    row = cur.fetchone()
    con.close()
    return bool(row)

def mark_sent_today(db_path: Path, date_str: str, ts_iso: str):
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO auto_send_log(send_date, sent_at) VALUES (?,?)",
        (date_str, ts_iso)
    )
    con.commit()
    con.close()

def should_auto_send(now: datetime) -> bool:
    # Saturday only (5) + after 09:00
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

# ✅ ALWAYS create the table at startup
ensure_auto_send_table(db_path)

try:
    now = now_local()
    _, date_str, _, ts_iso = today_labels()

    if (not already_sent_today(db_path, date_str)) and should_auto_send(now):
        df_now = load_wide_sheet(db_path)
        birthdays = get_birthdays_for_week(df_now)

        if birthdays:
            msg = build_birthday_message(birthdays)

            # ✅ Send to ALL recipients in the list
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





# ------------------ CONFIG ------------------
APP_TZ = os.environ.get("APP_TIMEZONE", "Africa/Johannesburg")
TZ = ZoneInfo(APP_TZ)

DB_DEFAULT = "app.db"

# Recipients (E.164 format)
WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

# Auto-send schedule (if you use it)
SEND_DAY_WEEKDAY = 5          # Saturday
SEND_AFTER_TIME = dtime(9, 0) # 09:00
SEND_WINDOW_HOURS = 12

# Grade capacity default
DEFAULT_GRADE_CAPACITY = 15

# Backup file for permanent restore
BACKUP_LEARNERS_CSV = "learners_backup.csv"

# ------------------ META WHATSAPP CLOUD API ------------------
# Put these in Streamlit secrets (recommended) or environment variables:
# META_WA_TOKEN
# META_WA_PHONE_NUMBER_ID
# (optional) META_WA_API_VERSION (default v22.0)
META_WA_TOKEN = os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = os.environ.get("META_WA_API_VERSION", "v22.0").strip()



# ------------------ UTILITIES ------------------
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

def is_saturday_class_day() -> bool:
    return now_local().weekday() == 5

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
    vals = sorted([v for v in series.astype(str).unique() if v.strip() != "" and v != "nan"])
    return ["(All)"] + vals

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

    if date_col not in subset.columns:
        return subset.iloc[0:0].copy(), subset

    present = subset[subset[date_col].astype(str).str.strip() == "1"]
    absent = subset[subset[date_col].astype(str).str.strip() != "1"]
    return present, absent


# ------------------ ✅ PERMANENT DATA (BACKUP + RESTORE) ------------------
def save_learners_backup(df_learners: pd.DataFrame):
    """
    Save a permanent backup learners CSV (works even when SQLite resets).
    """
    try:
        df_learners.to_csv(BACKUP_LEARNERS_CSV, index=False)
    except Exception:
        pass

def restore_learners_if_db_empty(db_path: Path):
    """
    If DB is empty (common after Streamlit restart), restore learners from backup CSV.
    """
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
            "Name","Surname","Barcode","Sessions","Present","Absent","Attendance %","Last present","Grade","Area"
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
    return result.sort_values(by=["Attendance %","Name","Surname"], ascending=[False,True,True]).reset_index(drop=True)


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
        grade = b.get("Grade", "")
        label = "🎉 Today" if b["Kind"] == "today" else ("🎂 Belated" if b["Kind"] == "belated" else "🎁 Upcoming")
        extra = f" (Grade {grade})" if grade else ""
        lines.append(f"{label}: {full_name}{extra} — DOB {b['DOB']}")
    return "\n".join(lines)


# ------------------ WHATSAPP (META CLOUD API) ------------------
import os
import requests

def _normalize_e164(n: str) -> str:
    """
    Expect E.164 like +2767xxxxxxx
    Removes 'whatsapp:' if user passed Twilio-style.
    """
    n = str(n).strip()
    if n.startswith("whatsapp:"):
        n = n.replace("whatsapp:", "").strip()
    return n

def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    """
    Sends WhatsApp messages using Meta WhatsApp Cloud API.
    Works in TEST mode ONLY for numbers you've added as test recipients.
    """
    token = os.environ.get("META_WA_TOKEN", "").strip()
    phone_number_id = os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()

    if not token or not phone_number_id:
        return False, "Missing META_WA_TOKEN / META_WA_PHONE_NUMBER_ID."

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
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
                # Meta returns something like: {"messages":[{"id":"wamid..."}]}
                msg_id = ""
                if isinstance(data, dict):
                    msgs = data.get("messages", [])
                    if msgs and isinstance(msgs, list) and isinstance(msgs[0], dict):
                        msg_id = msgs[0].get("id", "")
                results.append(f"{to_e164}: SENT (id {msg_id})" if msg_id else f"{to_e164}: SENT")
            else:
                # Meta error format usually: {"error":{"message":"...","type":"...","code":...}}
                err = data.get("error", {}) if isinstance(data, dict) else {}
                emsg = err.get("message", str(data))
                ecode = err.get("code", "")
                results.append(f"{to_e164}: FAILED (HTTP {r.status_code} code {ecode} - {emsg})")

        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    if sent_any:
        return True, " | ".join(results)
    return False, " | ".join(results) if results else "No recipients."


# ------------------ GRADES EXPORT ------------------
def build_grades_export(df: pd.DataFrame, date_sel: str, grades: list[str], grade_capacity: int):
    summary_rows = []
    for g in grades:
        mask_grade = df["Grade"].astype(str) == g if "Grade" in df.columns else pd.Series(False, index=df.index)
        present_in_grade = (df.loc[mask_grade, date_sel].astype(str) == "1").sum() if date_sel in df.columns else 0
        pct = (present_in_grade / grade_capacity * 100) if grade_capacity else 0.0
        absent_vs_cap = max(0, grade_capacity - int(present_in_grade))

        summary_rows.append({
            "Section": "SUMMARY",
            "Date": date_sel,
            "Grade": g,
            "Capacity (fixed)": int(grade_capacity),
            "Present": int(present_in_grade),
            "Absent (vs capacity)": int(absent_vs_cap),
            "Attendance %": round(pct, 1),
            "Name": "",
            "Surname": "",
            "Barcode": "",
            "Status": "",
        })

    summary_df = pd.DataFrame(summary_rows)

    learners = df.copy()
    learners["Date"] = date_sel
    if date_sel in learners.columns:
        learners["Status"] = learners[date_sel].astype(str).apply(lambda x: "Present" if x.strip() == "1" else "Absent")
    else:
        learners["Status"] = "Absent"

    learners_export = (
        learners[["Date","Grade","Name","Surname","Barcode","Status"]].copy()
        if all(c in learners.columns for c in ["Date","Grade","Name","Surname","Barcode","Status"])
        else pd.DataFrame(columns=["Date","Grade","Name","Surname","Barcode","Status"])
    )
    learners_export.insert(0, "Section", "LEARNERS")

    export_cols = ["Section","Date","Grade","Capacity (fixed)","Present","Absent (vs capacity)","Attendance %","Name","Surname","Barcode","Status"]
    for c in export_cols:
        if c not in learners_export.columns:
            learners_export[c] = ""
    learners_export = learners_export[export_cols]

    combined_export_df = pd.concat([summary_df[export_cols], learners_export], ignore_index=True)
    return summary_df.drop(columns=["Section","Name","Surname","Barcode","Status"]), combined_export_df


# ------------------ DB LOAD ------------------
def load_wide_sheet(db_path: Path) -> pd.DataFrame:
    return get_wide_sheet(db_path)


# ------------------ UI ------------------
st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"]  { 
    font-size: 17px !important;
}
main .block-container { padding-top: 1rem; }
h1 { font-size: 2.2rem !important; }
h2 { font-size: 2.0rem !important; }
h3 { font-size: 1.6rem !important; }

.section-card {
    background: #ffffff;
    padding: 18px 22px;
    border-radius: 16px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
    margin-bottom: 1.2rem;
}
.stat-card {
    padding: 14px 18px;
    border: 1px solid #eee;
    border-radius: 14px;
    background: #fafafa;
}
.kpi {
    font-size: 34px !important;
    font-weight: 800;
}
button[data-baseweb="tab"] {
    font-size: 16px !important;
    padding-top: 10px !important;
    padding-bottom: 10px !important;
}
input, textarea {
    font-size: 16px !important;
}
.manage-card {
    background: #ffffff;
    padding: 16px 18px;
    border-radius: 14px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 6px 16px rgba(15,23,42,0.04);
    margin-bottom: 14px;
}
.manage-title {
    margin: 0 0 8px 0;
    font-size: 17px !important;
    font-weight: 800;
}
.small-help {
    color:#667085;
    font-size: 14px !important;
    margin-top: -6px;
}
</style>
""", unsafe_allow_html=True)

# ---------- HEADER ----------
logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(f"""
<div style="text-align:center; margin: 0.25rem 0 0.8rem 0;">
    {"<img src='data:image/png;base64," + logo_b64 + "' width='130' style='margin-bottom: 6px;'/>" if logo_b64 else ""}
    <h2 style="margin: 0.2rem 0; font-size: 2.2rem;">Tutor Class Attendance Register 2026</h2>
    <p style="margin:0; color:#666; font-size:14px;">
        Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b>
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="
    margin: 0 auto 0.9rem auto;
    max-width: 820px;
    padding: 8px 16px;
    border-radius: 999px;
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    text-align: center;
    font-size: 13px;
    color: #555;
">
📷 <b>Saturday Tutor Class</b> · Scan barcodes to mark <b>IN / OUT</b> and track attendance.
</div>
""", unsafe_allow_html=True)

# ---------- SIDEBAR ----------
with st.sidebar:
    st.header("Settings")
    if Path("tzu_chi_logo.png").exists():
        st.image("tzu_chi_logo.png", use_container_width=True)

    db_path_str = st.text_input("Database file path", DB_DEFAULT, key="path_input")
    db_path = Path(db_path_str).expanduser()

    init_db(db_path)
    ensure_auto_send_table(db_path)

    # ✅ Restore learners if DB is empty (seeds from attendance_clean.csv)
    try:
        seed_learners_from_csv_if_empty(db_path, "attendance_clean.csv")
    except Exception as e:
        st.warning(f"Auto-restore failed: {e}")

    st.markdown("### Grade capacity (benchmark)")
    grade_capacity = st.number_input(
        "Capacity per grade",
        min_value=1, max_value=200,
        value=DEFAULT_GRADE_CAPACITY, step=1
    )

    st.markdown("### WhatsApp Recipients")
    st.write(WHATSAPP_RECIPIENTS)

st.divider()
tabs = st.tabs(["📷 Scan", "📅 Today", "🏫 Grades", "📚 History", "📈 Tracking", "🛠 Manage"])


# ------------------ Scan Tab ------------------
with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    today_label, date_str, time_str, ts_iso = today_labels()
    add_class_date(db_path, today_label)

    df_scan = load_wide_sheet(db_path)
    if today_label not in df_scan.columns:
        df_scan[today_label] = ""

    total_learners = len(df_scan)
    present_today = (df_scan[today_label].astype(str).str.strip() == "1").sum() if total_learners else 0
    absent_today = total_learners - present_today

    st.subheader("📊 Today ")
    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(f'<div class="stat-card"><b>Total learners</b><div class="kpi">{total_learners}</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="stat-card"><b>Present today</b><div class="kpi">{present_today}</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="stat-card"><b>Absent today</b><div class="kpi">{absent_today}</div></div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("📷 Scan learner")

    def mark_scan_in_out_sqlite(barcode: str) -> tuple[bool, str]:
        barcode = str(barcode).strip()
        if not barcode:
            return False, "Empty scan."

        df = load_wide_sheet(db_path)
        if df.empty or "Barcode" not in df.columns:
            return False, "No learners in database yet. Add learners in Manage tab first."

        matches = df.index[df["Barcode"].astype(str).apply(norm_barcode) == norm_barcode(barcode)].tolist()
        if not matches:
            return False, "Barcode not found. Add it to the correct learner in Manage."

        date_label, date_str2, time_str2, ts_iso2 = today_labels()
        add_class_date(db_path, date_label)

        msgs = []
        for idx in matches:
            row = df.loc[idx]
            real_barcode = str(row.get("Barcode", "")).strip()
            action = determine_next_action(db_path, real_barcode, date_str2)

            insert_present_mark(db_path, date_label, date_str2, time_str2, real_barcode)

            append_inout_log(
                db_path=db_path,
                ts_iso=ts_iso2,
                date_str=date_str2,
                time_str=time_str2,
                barcode=real_barcode,
                name=str(row.get("Name", "")),
                surname=str(row.get("Surname", "")),
                action=action
            )

            who = label_for_row(row)
            msgs.append(f"{who} [{real_barcode}] marked {action} at {time_str2} ({date_str2}).")

        current_in = get_currently_in(db_path, date_str2)
        msgs.append("")
        msgs.append(f"Currently IN today ({date_str2}): {len(current_in)}")
        for _, r in current_in.iterrows():
            who2 = (str(r["Name"]).strip() + " " + str(r["Surname"]).strip()).strip() or f"[{r['Barcode']}]"
            msgs.append(f"  • {who2} [{r['Barcode']}]")

        return True, "\n".join(msgs)

    def handle_scan():
        scan_value = st.session_state.get("scan_box", "").strip()
        if not scan_value:
            return

        if not is_saturday_class_day():
            st.session_state["scan_feedback"] = ("error", "Today is not a class day. Scans are only allowed on Saturdays.")
        else:
            ok, msg = mark_scan_in_out_sqlite(scan_value)
            st.session_state["scan_feedback"] = ("ok" if ok else "error", msg)

        st.session_state["scan_box"] = ""

    st.text_input("Focus here and scan…", key="scan_box", label_visibility="collapsed", on_change=handle_scan)

    fb = st.session_state.pop("scan_feedback", None)
    if fb:
        status, msg = fb
        (st.success if status == "ok" else st.error)(msg)

    st.divider()
    _, date_str_now, _, _ = today_labels()
    current_in = get_currently_in(db_path, date_str_now)

    st.subheader(f"🟢 Currently IN today ({date_str_now})")
    if current_in.empty:
        st.caption("No one is currently IN.")
    else:
        st.dataframe(current_in, use_container_width=True, height=260)

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Today Tab ------------------
with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    today_col, _, _, _ = today_labels()
    st.subheader(f"Today's Attendance — {today_col}")

    add_class_date(db_path, today_col)
    df = load_wide_sheet(db_path)

    if today_col not in df.columns:
        df[today_col] = ""

    birthdays = get_birthdays_for_week(df)
    if birthdays:
        st.markdown("### 🎂 Birthdays around this week")
        for b in birthdays:
            full_name = f"{b['Name']} {b['Surname']}".strip()
            grade = b.get("Grade", "")
            msg = "🎉 **Happy Birthday**" if b["Kind"] == "today" else ("🎂 **Happy belated birthday**" if b["Kind"] == "belated" else "🎁 **Upcoming birthday**")
            extra = f" (Grade {grade})" if grade else ""
            st.markdown(f"- {msg}, {full_name}{extra} – DOB: {b['DOB']}")
    else:
        st.caption("No birthdays this week or in the next 7 days.")

    st.divider()

    fc1, fc2 = st.columns(2)
    with fc1:
        grade_sel = st.selectbox("Filter by Grade", unique_sorted(df["Grade"]) if "Grade" in df.columns else ["(All)"], key="today_grade")
    with fc2:
        area_sel = st.selectbox("Filter by Area", unique_sorted(df["Area"]) if "Area" in df.columns else ["(All)"], key="today_area")

    grade_val = None if grade_sel == "(All)" else grade_sel
    area_val = None if area_sel == "(All)" else area_sel

    present, absent = get_present_absent(df, today_col, grade_val, area_val)

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(f'<div class="stat-card"><b>Registered</b><div class="kpi">{len(present)+len(absent)}</div></div>', unsafe_allow_html=True)
    with s2:
        st.markdown(f'<div class="stat-card"><b>Present</b><div class="kpi">{len(present)}</div></div>', unsafe_allow_html=True)
    with s3:
        st.markdown(f'<div class="stat-card"><b>Absent</b><div class="kpi">{len(absent)}</div></div>', unsafe_allow_html=True)

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Present**")
        cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in present.columns]
        st.dataframe(present[cols].sort_values(by=["Name","Surname"]) if len(present) else present[cols], use_container_width=True, height=360)
    with cB:
        st.markdown("**Absent**")
        cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in absent.columns]
        st.dataframe(absent[cols].sort_values(by=["Name","Surname"]) if len(absent) else absent[cols], use_container_width=True, height=360)

    date_cols = get_date_columns(df)
    if date_cols:
        trend = pd.DataFrame({"Date": date_cols, "Present": [(df[c].astype(str).str.strip() == "1").sum() for c in date_cols]})
        st.markdown("**Attendance Trend**")
        chart = alt.Chart(trend).mark_line(point=True).encode(
            x=alt.X("Date:N", sort=None),
            y="Present:Q",
            tooltip=["Date", "Present"],
        ).properties(height=220)
        st.altair_chart(chart, use_container_width=True)

    exp1, exp2 = st.columns(2)
    exp1.download_button("Download today's PRESENT (CSV)", data=present.to_csv(index=False).encode("utf-8"),
                         file_name=f"present_{today_col}.csv", mime="text/csv", use_container_width=True, key="today_dl_present")
    exp2.download_button("Download today's ABSENT (CSV)", data=absent.to_csv(index=False).encode("utf-8"),
                         file_name=f"absent_{today_col}.csv", mime="text/csv", use_container_width=True, key="today_dl_absent")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Grades Tab ------------------
with tabs[2]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Grade Attendance by Saturday")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet.")
    else:
        date_sel = st.selectbox("Choose a Saturday", list(reversed(date_cols)), key="grade_date")
        grades = ["5", "6", "7", "8"]

        summary_df, combined_export_df = build_grades_export(df=df, date_sel=date_sel, grades=grades, grade_capacity=int(grade_capacity))

        k_cols = st.columns(len(grades))
        for i, g in enumerate(grades):
            row = summary_df[summary_df["Grade"].astype(str) == g].iloc[0]
            pct_str = f"{float(row['Attendance %']):.1f}%"
            with k_cols[i]:
                st.markdown(
                    f'<div class="stat-card"><b>Grade {g}</b><div class="kpi">{pct_str}</div>'
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


# ------------------ History Tab ------------------
with tabs[3]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("History")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet.")
    else:
        date_sel = st.selectbox("Choose a date", list(reversed(date_cols)), key="history_date")
        cols = [c for c in ["Name","Surname","Barcode","Grade","Area",date_sel] if c in df.columns]
        view = df[cols].copy()

        if date_sel in view.columns:
            view["Status"] = view[date_sel].astype(str).apply(lambda x: "Present" if str(x).strip() == "1" else "Absent")
            view = view.drop(columns=[date_sel])
        else:
            view["Status"] = "Absent"

        st.dataframe(view.sort_values(by=["Status","Name","Surname"], ascending=[True, True, True]), use_container_width=True, height=420)
        st.download_button(
            "Download this date (CSV)",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_{date_sel}.csv",
            mime="text/csv",
            use_container_width=True,
            key="history_dl"
        )

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Tracking Tab ------------------
with tabs[4]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Tracking (per learner)")

    df = load_wide_sheet(db_path)
    date_cols = get_date_columns(df)

    if not date_cols:
        st.info("No attendance dates yet.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            grade_sel = st.selectbox("Filter by Grade", unique_sorted(df["Grade"]) if "Grade" in df.columns else ["(All)"], key="track_grade")
        with fc2:
            area_sel = st.selectbox("Filter by Area", unique_sorted(df["Area"]) if "Area" in df.columns else ["(All)"], key="track_area")
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
                lambda r: q in str(r.get("Name","")).lower()
                or q in str(r.get("Surname","")).lower()
                or q in str(r.get("Barcode","")).lower(),
                axis=1
            )]

        metrics = compute_tracking(subset) if len(subset) else pd.DataFrame()
        st.write(f"Total learners: **{len(metrics)}**  |  Sessions counted: **{len(date_cols)}**")

        if not metrics.empty:
            show_cols = ["Name","Surname","Barcode","Grade","Area","Sessions","Present","Absent","Attendance %","Last present"]
            show_cols = [c for c in show_cols if c in metrics.columns]
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

# ------------------ Manage Tab ------------------
with tabs[5]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Manage Learners / Barcodes")
    st.caption("Use this section to import, edit, remove learners, and test WhatsApp sending.")

    # Always read from DB
    df = get_learners_df(db_path).fillna("").astype(str)
    if "Date Of Birth" not in df.columns:
        df["Date Of Birth"] = ""

    # ------------------ IMPORT CSV ------------------
    st.markdown('<div class="manage-card">', unsafe_allow_html=True)
    st.markdown('<p class="manage-title">📥 Bulk Import (CSV)</p>', unsafe_allow_html=True)
    st.markdown('<div class="small-help">Upload a CSV to replace all learners or merge updates by barcode.</div>', unsafe_allow_html=True)

    csv_file = st.file_uploader("Upload a learners CSV", type=["csv"], key="import_csv_manage")

    def _normalize_cols(import_df: pd.DataFrame) -> pd.DataFrame:
        import_df = import_df.copy()
        import_df.columns = [str(c).strip() for c in import_df.columns]
        mappings = {
            "barcode": "Barcode", "bar code": "Barcode", "id": "Barcode", "student id": "Barcode",
            "name": "Name", "first name": "Name", "firstname": "Name",
            "surname": "Surname", "last name": "Surname", "lastname": "Surname",
            "grade": "Grade", "class": "Grade",
            "area": "Area", "location": "Area",
            "date of birth": "Date Of Birth", "dob": "Date Of Birth", "birthdate": "Date Of Birth", "birthday": "Date Of Birth",
        }
        import_df.rename(columns={c: mappings.get(c.lower(), c) for c in import_df.columns}, inplace=True)
        return import_df

    import_mode = st.radio(
        "Import mode",
        ["Replace ALL learners (recommended for first upload)", "Merge (add/update by barcode)"],
        horizontal=False,
        key="import_mode",
    )

    if csv_file is not None:
        try:
            import_df = pd.read_csv(csv_file).fillna("").astype(str)
            import_df = _normalize_cols(import_df)

            required = ["Barcode", "Name", "Surname"]
            missing = [c for c in required if c not in import_df.columns]
            if missing:
                st.error(f"CSV is missing required columns: {missing}")
            else:
                for c in ["Grade", "Area", "Date Of Birth"]:
                    if c not in import_df.columns:
                        import_df[c] = ""

                import_df = import_df[["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]].copy()
                import_df["Barcode"] = import_df["Barcode"].astype(str).str.strip()
                import_df = import_df[import_df["Barcode"] != ""].reset_index(drop=True)

                import_df["_bnorm"] = import_df["Barcode"].astype(str).apply(norm_barcode)
                import_df = import_df.drop_duplicates(subset=["_bnorm"], keep="first").drop(columns=["_bnorm"])

                if len(import_df) == 0:
                    st.error("No valid rows found (all barcodes empty).")
                else:
                    if import_mode.startswith("Replace"):
                        replace_learners_from_df(db_path, import_df)
                        save_learners_backup(import_df)  # ✅ backup
                        st.success(f"Replaced learners with {len(import_df)} rows ✅")
                    else:
                        current = get_learners_df(db_path).fillna("").astype(str)
                        if len(current) == 0:
                            merged = import_df
                        else:
                            current["_bnorm"] = current["Barcode"].astype(str).apply(norm_barcode)
                            import_df["_bnorm"] = import_df["Barcode"].astype(str).apply(norm_barcode)

                            current = current.set_index("_bnorm")
                            import_df = import_df.set_index("_bnorm")

                            current.update(import_df)
                            merged = pd.concat([current, import_df[~import_df.index.isin(current.index)]], axis=0)
                            merged = merged.reset_index(drop=True).drop(columns=["_bnorm"], errors="ignore")

                        replace_learners_from_df(db_path, merged)
                        save_learners_backup(merged)  # ✅ backup
                        st.success(f"Merged {len(import_df)} rows into DB ✅")

                    st.rerun()
        except Exception as e:
            st.error(f"Failed to import CSV: {e}")

    st.markdown("</div>", unsafe_allow_html=True)

    # Reload after import
    df = get_learners_df(db_path).fillna("").astype(str)
    if "Date Of Birth" not in df.columns:
        df["Date Of Birth"] = ""

    # ------------------ EDIT (TOGGLE BUTTON) ------------------
    st.markdown('<div class="manage-card">', unsafe_allow_html=True)
    st.markdown('<p class="manage-title">✏️ Edit Learners</p>', unsafe_allow_html=True)
    st.markdown('<div class="small-help">Click <b>Edit mode</b> to show the editable table. Turn it off to hide it.</div>', unsafe_allow_html=True)

    if "edit_mode" not in st.session_state:
        st.session_state["edit_mode"] = False

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("✏️ Edit mode", use_container_width=True):
            st.session_state["edit_mode"] = not st.session_state["edit_mode"]
    with b2:
        st.info("Edit mode: ✅ ON" if st.session_state["edit_mode"] else "Edit mode: ❌ OFF")

    if st.session_state["edit_mode"]:
        editable_cols = ["Name", "Surname", "Barcode", "Grade", "Area", "Date Of Birth"]
        view_df = df.copy().reset_index(drop=True)
        view_df.insert(0, "RowID", range(len(view_df)))

        edited = st.data_editor(
            view_df[["RowID"] + editable_cols],
            use_container_width=True,
            num_rows="dynamic",
            key="data_editor_manage",
        )

        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("💾 Save changes", use_container_width=True):
                edited_clean = edited.drop(columns=["RowID"]).fillna("").astype(str)
                edited_clean = edited_clean[~(
                    (edited_clean["Name"].str.strip() == "") &
                    (edited_clean["Surname"].str.strip() == "") &
                    (edited_clean["Barcode"].str.strip() == "")
                )].reset_index(drop=True)

                if (edited_clean["Barcode"].astype(str).str.strip() == "").any():
                    st.error("Every learner must have a Barcode. Please fill in missing barcodes.")
                else:
                    bnorms = edited_clean["Barcode"].astype(str).apply(norm_barcode)
                    if bnorms.duplicated().any():
                        st.error("Duplicate barcode detected (same barcode / leading zeros). Fix duplicates before saving.")
                    else:
                        replace_learners_from_df(db_path, edited_clean)
                        save_learners_backup(edited_clean)  # ✅ backup
                        st.success("Saved ✅")
                        st.session_state["edit_mode"] = False
                        st.rerun()

        with c2:
            if st.button("🔄 Cancel / Hide table", use_container_width=True):
                st.session_state["edit_mode"] = False
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # ------------------ QUICK DELETE ------------------
    st.markdown('<div class="manage-card">', unsafe_allow_html=True)
    st.markdown('<p class="manage-title">🗑 Remove Learner</p>', unsafe_allow_html=True)
    st.markdown('<div class="small-help">Enter a barcode and confirm before deleting.</div>', unsafe_allow_html=True)

    del_barcode = st.text_input("Enter barcode", key="del_barcode")
    confirm = st.checkbox("Confirm delete", key="confirm_del_barcode")

    if st.button("Delete ❌", use_container_width=True, disabled=not confirm):
        deleted = delete_learner_by_barcode(db_path, del_barcode.strip())
        if deleted == 0:
            st.error("Barcode not found.")
        else:
            df_after = get_learners_df(db_path).fillna("").astype(str)
            save_learners_backup(df_after)  # ✅ refresh backup
            st.success(f"Deleted {deleted} learner(s) ✅")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ------------------ WhatsApp test (Meta) ------------------
st.markdown('<div class="manage-card">', unsafe_allow_html=True)
st.markdown('<p class="manage-title">📩 WhatsApp Connection Test (Meta)</p>', unsafe_allow_html=True)
st.markdown(
    '<div class="small-help">'
    'Send a test message using Meta WhatsApp Cloud API.<br>'
    '<b>Note:</b> The recipient number must be added as a test number in Meta.'
    '</div>',
    unsafe_allow_html=True
)

test_to = st.text_input(
    "Test recipient number (E.164 format)",
    value=WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "+27..."
)

test_msg = st.text_area(
    "Message",
    value="Hello! This is a test message from the Tutor Class Attendance app ✅"
)

if st.button("Send Test WhatsApp", use_container_width=True):
    ok, info = send_whatsapp_message([test_to], test_msg)
    if ok:
        st.success(info)
    else:
        st.error(info)

st.markdown("</div>", unsafe_allow_html=True)











