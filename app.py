# app.py — Tutor Class Attendance Register 2026 (restored + WhatsApp + downloads)
# Tabs: Scan • Today • Grades • History • Tracking • Manage
# Features:
# - Barcode scan: IN/OUT log + marks attendance "1" for the day
# - Today: present/absent + downloads + trend
# - Grades: % per grade + download combined report
# - History: view any date column + download
# - Tracking: per learner sessions/present/absent/% + download
# - Manage: edit learner data, assign barcode, add date columns, NEXT SATURDAY
# - WhatsApp: test sending + optional auto-send Saturday 09:00 (while app is running)

import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import altair as alt
import requests
import base64

def gh_headers():
    return {
        "Authorization": f"token {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json"
    }

def gh_get_file(path):
    repo = st.secrets["GITHUB_REPO"]
    branch = st.secrets.get("GITHUB_BRANCH", "main")
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers=gh_headers())
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]

def gh_update_file(path, new_content, message):
    repo = st.secrets["GITHUB_REPO"]
    branch = st.secrets.get("GITHUB_BRANCH", "main")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    # get current SHA
    _, sha = gh_get_file(path)

    payload = {
        "message": message,
        "content": base64.b64encode(new_content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": branch
    }
    r = requests.put(url, headers=gh_headers(), json=payload)
    r.raise_for_status()
    return r.json()


# ------------------ CONFIG ------------------
APP_TZ = os.environ.get("APP_TIMEZONE", "Africa/Johannesburg")  # you can set in Streamlit Secrets
TZ = ZoneInfo(APP_TZ)

CSV_DEFAULT = "attendance_clean.csv"

# WhatsApp recipients (E.164 with +countrycode, no spaces). Example South Africa: +27...
WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

# Auto-send rule (Saturday 09:00 local time)
SEND_DAY_WEEKDAY = 5          # Saturday (Mon=0 ... Sun=6)
SEND_AFTER_TIME = dtime(9, 0) # 09:00
SEND_WINDOW_HOURS = 12        # send allowed between 09:00 and 21:00

# Grade capacity default (used for percentage benchmarks)
DEFAULT_GRADE_CAPACITY = 20

# ------------------ OPTIONAL TWILIO IMPORT ------------------
try:
    from twilio.rest import Client
except Exception:
    Client = None


# ------------------ UTILITIES ------------------
def now_local() -> datetime:
    return datetime.now(TZ)

def today_col_label() -> str:
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    return f"{day}-{mon}"

def today_labels():
    """Return (date_col_label, date_str, time_str, timestamp_iso)."""
    n = now_local()
    day = str(int(n.strftime("%d")))
    mon = n.strftime("%b")
    date_col = f"{day}-{mon}"           # columns like 21-Jan
    date_str = n.strftime("%Y-%m-%d")   # logs like 2026-01-21
    time_str = n.strftime("%H:%M:%S")
    ts = n.isoformat(timespec="seconds")
    return date_col, date_str, time_str, ts

def is_saturday_class_day() -> bool:
    return now_local().weekday() == 5

def next_saturday_from(base: datetime | None = None) -> str:
    base = base or now_local()
    days_ahead = (5 - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    dt = base + timedelta(days=days_ahead)
    return f"{int(dt.strftime('%d'))}-{dt.strftime('%b')}"

def _norm(code: str) -> str:
    s = str(code).strip()
    s = s.lstrip("0")
    return s if s != "" else "0"

@contextmanager
def file_guard(path: Path):
    attempts, last_err = 6, None
    for _ in range(attempts):
        try:
            yield
            return
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    if last_err:
        raise last_err

from io import StringIO

def load_sheet_from_github(filename="attendance_clean.csv"):
    content, sha = gh_get_file(filename)
    df = pd.read_csv(StringIO(content), dtype=str).fillna("")
    return df, sha


def save_sheet_to_github(df, filename="attendance_clean.csv"):
    csv_text = df.to_csv(index=False)
    gh_update_file(
        filename,
        csv_text,
        message=f"Update {filename} from Streamlit app"
    )

def ensure_date_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = ""

def ensure_today_column(df: pd.DataFrame) -> str:
    col = today_col_label()
    ensure_date_column(df, col)
    return col

def label_for_row(r: pd.Series) -> str:
    name = str(r.get("Name", "")).strip()
    surname = str(r.get("Surname", "")).strip()
    return (name + " " + surname).strip() or str(r.get("Barcode", "")).strip()

def get_date_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        parts = c.split("-")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2:
            cols.append(c)

    def _key(x):
        try:
            # parse day-month without year (sort by day-of-year)
            return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except Exception:
            return 999

    return sorted(cols, key=_key)

def unique_sorted(series: pd.Series):
    vals = sorted([v for v in series.astype(str).unique() if v.strip() != "" and v != "nan"])
    return ["(All)"] + vals

def get_present_absent(df: pd.DataFrame, date_col: str, grade=None, area=None):
    if date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    filt = pd.Series([True] * len(df))
    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)
    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)

    subset = df[filt].copy()
    present = subset[subset[date_col].astype(str) == "1"]
    absent = subset[subset[date_col].astype(str) != "1"]
    return present, absent


# ------------------ IN/OUT LOG ------------------
def load_log(log_path: Path) -> pd.DataFrame:
    if not log_path.exists():
        return pd.DataFrame(columns=["Timestamp","Date","Time","Barcode","Name","Surname","Action"])
    with file_guard(log_path):
        df = pd.read_csv(log_path, dtype=str).fillna("")
    for col in ["Timestamp","Date","Time","Barcode","Name","Surname","Action"]:
        if col not in df.columns:
            df[col] = ""
    return df

def save_log(df: pd.DataFrame, log_path: Path):
    with file_guard(log_path):
        df.to_csv(log_path, index=False)

def determine_next_action(log_df: pd.DataFrame, barcode: str, date_str: str) -> str:
    norm_b = _norm(barcode)
    today_rows = log_df[
        (log_df["Date"] == date_str) &
        (log_df["Barcode"].astype(str).apply(_norm) == norm_b)
    ]
    if today_rows.empty:
        return "IN"
    last_action = today_rows.iloc[-1]["Action"].upper()
    return "OUT" if last_action == "IN" else "IN"

def get_currently_in(log_df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    if log_df.empty:
        return pd.DataFrame(columns=["Barcode","Name","Surname"])
    today = log_df[log_df["Date"] == date_str].copy()
    if today.empty:
        return pd.DataFrame(columns=["Barcode","Name","Surname"])
    today = today.sort_values(by=["Barcode","Timestamp"])
    last_actions = today.groupby("Barcode").tail(1)
    current_in = last_actions[last_actions["Action"].str.upper() == "IN"]
    return current_in[["Barcode","Name","Surname"]].reset_index(drop=True)

def mark_scan_in_out(barcode: str, csv_path: Path, log_path: Path) -> tuple[bool, str]:
    barcode = str(barcode).strip()
    if not barcode:
        return False, "Empty scan."
    if not csv_path.exists():
        return False, f"Cannot find {csv_path.name}."

    df = load_sheet(csv_path)
    log_df = load_log(log_path)

    date_col, date_str, time_str, ts = today_labels()
    ensure_date_column(df, date_col)

    matches = df.index[df["Barcode"].apply(_norm) == _norm(barcode)].tolist()
    if not matches:
        return False, (
            "Barcode not found in sheet. "
            "Add this barcode to the correct learner in the Manage tab."
        )

    action = determine_next_action(log_df, barcode, date_str)

    msgs = []
    for idx in matches:
        # mark attendance for today
        if str(df.at[idx, date_col]).strip() != "1":
            df.at[idx, date_col] = "1"

        who = label_for_row(df.loc[idx])
        row_barcode = str(df.at[idx, "Barcode"]).strip()

        new_row = {
            "Timestamp": ts,
            "Date": date_str,
            "Time": time_str,
            "Barcode": row_barcode,
            "Name": str(df.at[idx, "Name"]),
            "Surname": str(df.at[idx, "Surname"]),
            "Action": action,
        }
        log_df = pd.concat([log_df, pd.DataFrame([new_row])], ignore_index=True)
        msgs.append(f"{who} [{row_barcode}] marked {action} at {time_str} ({date_str}).")

    save_sheet(df, csv_path)
    save_log(log_df, log_path)

    current_in = get_currently_in(log_df, date_str)
    msgs.append("")
    msgs.append(f"Currently IN today ({date_str}): {len(current_in)}")
    for _, r in current_in.iterrows():
        who = (str(r["Name"]).strip() + " " + str(r["Surname"]).strip()).strip()
        if not who:
            who = f"[{r['Barcode']}]"
        msgs.append(f"  • {who} [{r['Barcode']}]")

    return True, "\n".join(msgs)


# ------------------ TRACKING ------------------
def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Sessions","Present","Absent","Attendance %","Last present"])

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
        "Sessions": sessions,
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present,
        "Grade": df.get("Grade", ""),
        "Area": df.get("Area", ""),
    })
    return result.sort_values(by=["Attendance %","Name","Surname"], ascending=[False,True,True]).reset_index(drop=True)


# ------------------ BIRTHDAYS ------------------
def parse_dob(dob_str: str):
    dob_str = dob_str.strip()
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
        dob = parse_dob(str(r.get("Date Of Birth", "")))
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
        if b["Kind"] == "today":
            label = "🎉 Today"
        elif b["Kind"] == "belated":
            label = "🎂 Belated"
        else:
            label = "🎁 Upcoming"
        extra = f" (Grade {grade})" if grade else ""
        lines.append(f"{label}: {full_name}{extra} — DOB {b['DOB']}")
    return "\n".join(lines)


# ------------------ WHATSAPP (TWILIO) ------------------
def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    """
    Uses Streamlit Secrets/Env:
      TWILIO_ACCOUNT_SID
      TWILIO_AUTH_TOKEN
      TWILIO_WHATSAPP_FROM   (example: whatsapp:+14155238886)
    """
    if Client is None:
        return False, "Twilio library not installed. Add 'twilio' to requirements.txt."

    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    wa_from = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # like: whatsapp:+1415...

    if not sid or not token or not wa_from:
        return False, "Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM."

    client = Client(sid, token)

    sent_any = False
    errors = []
    for n in to_numbers:
        n = n.strip()
        if not n:
            continue
        try:
            client.messages.create(
                from_=wa_from,
                to=f"whatsapp:{n}",
                body=body
            )
            sent_any = True
        except Exception as e:
            errors.append(f"{n}: {e}")

    if sent_any and not errors:
        return True, "Sent successfully."
    if sent_any and errors:
        return True, "Sent to some numbers, but failed for: " + " | ".join(errors)
    return False, "Failed: " + " | ".join(errors) if errors else "Failed (unknown)."

def should_send_now() -> bool:
    n = now_local()
    if n.weekday() != SEND_DAY_WEEKDAY:
        return False
    if n.time() < SEND_AFTER_TIME:
        return False
    end_time = (datetime.combine(n.date(), SEND_AFTER_TIME, tzinfo=TZ) + timedelta(hours=SEND_WINDOW_HOURS)).time()
    if n.time() > end_time:
        return False
    return True

def sent_state_path(base_csv: Path) -> Path:
    # store state near the CSV so it persists on the app filesystem
    return base_csv.with_name(".whatsapp_sent_state.json")

def already_sent_today(base_csv: Path) -> bool:
    p = sent_state_path(base_csv)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("date") == now_local().strftime("%Y-%m-%d")
    except Exception:
        return False

def mark_sent_today(base_csv: Path):
    p = sent_state_path(base_csv)
    data = {"date": now_local().strftime("%Y-%m-%d"), "ts": now_local().isoformat(timespec="seconds")}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------ GRADES EXPORT ------------------
def build_grades_export(df: pd.DataFrame, date_sel: str, grades: list[str], grade_capacity: int):
    summary_rows = []
    for g in grades:
        mask_grade = df["Grade"].astype(str) == g
        if date_sel in df.columns:
            present_in_grade = (df.loc[mask_grade, date_sel].astype(str) == "1").sum()
        else:
            present_in_grade = 0

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
    learners["Grade"] = learners.get("Grade", "").astype(str)
    learners["Name"] = learners.get("Name", "").astype(str)
    learners["Surname"] = learners.get("Surname", "").astype(str)
    learners["Barcode"] = learners.get("Barcode", "").astype(str)

    if date_sel in learners.columns:
        learners["Status"] = learners[date_sel].astype(str).apply(lambda x: "Present" if x.strip() == "1" else "Absent")
    else:
        learners["Status"] = "Absent"

    learners_export = learners[["Date","Grade","Name","Surname","Barcode","Status"]].copy()
    learners_export.insert(0, "Section", "LEARNERS")

    export_cols = ["Section","Date","Grade","Capacity (fixed)","Present","Absent (vs capacity)","Attendance %","Name","Surname","Barcode","Status"]
    for c in export_cols:
        if c not in learners_export.columns:
            learners_export[c] = ""
    learners_export = learners_export[export_cols]

    combined_export_df = pd.concat([summary_df[export_cols], learners_export], ignore_index=True)
    return summary_df.drop(columns=["Section","Name","Surname","Barcode","Status"]), combined_export_df


# ------------------ UI ------------------
st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown(
    """
<style>
.stat-card {padding: 12px 16px; border: 1px solid #eee; border-radius: 12px; background: #fafafa;}
.kpi {font-size: 28px; font-weight: 700;}
body { background-color: #f3f4f6; }
main .block-container { padding-top: 1.5rem; }
.section-card {
    background: #ffffff;
    padding: 18px 22px;
    border-radius: 16px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
    margin-bottom: 1.2rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# Header logo
logo_col1, logo_col2, logo_col3 = st.columns([3, 2, 3])
with logo_col2:
    if Path("tzu_chi_logo.png").exists():
        st.image("tzu_chi_logo.png", width=200)

st.markdown("<h1 style='text-align:center; margin-bottom:-5px;'>Tutor Class Attendance Register 2026</h1>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align:center; color:#666;'>Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b></p>", unsafe_allow_html=True)

st.markdown(
    """
    <div style="
        margin: 0 auto 1.5rem auto;
        max-width: 900px;
        padding: 10px 18px;
        border-radius: 999px;
        background: #f5f7fa;
        border: 1px solid #e4e7ec;
        text-align: center;
        font-size: 14px;
        color: #555;
    ">
        📚 <b>Saturday Tutor Class Attendance</b> · Scan learner barcodes to mark
        <b>IN / OUT</b> and track participation over time.
    </div>
    """,
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.header("Settings")
    if Path("tzu_chi_logo.png").exists():
        st.image("tzu_chi_logo.png", use_container_width=True)

    csv_path_str = st.text_input("CSV file path", CSV_DEFAULT, key="path_input")
    csv_path = Path(csv_path_str).expanduser()
    log_path = csv_path.with_name("attendance_log.csv")

    st.caption("Tip: keep the CSV in a shared OneDrive/Drive folder for team use.")

    st.markdown("### Grade capacity (benchmark)")
    grade_capacity = st.number_input("Capacity per grade", min_value=1, max_value=200, value=DEFAULT_GRADE_CAPACITY, step=1)

    st.markdown("### WhatsApp Recipients")
    st.caption("Use full numbers with country code, e.g. +2781...")
    st.write(WHATSAPP_RECIPIENTS)

tabs = st.tabs(["📷 Scan", "📅 Today", "🏫 Grades", "📚 History", "📈 Tracking", "🛠 Manage"])


# ------------------ AUTO-SEND (runs when app is running) ------------------
if csv_path.exists():
    try:
        df_auto = load_sheet(csv_path)
        birthdays = get_birthdays_for_week(df_auto)
        if birthdays and should_send_now() and not already_sent_today(csv_path):
            msg = build_birthday_message(birthdays)
            ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
            if ok:
                mark_sent_today(csv_path)
                st.toast("WhatsApp birthday summary sent ✅", icon="✅")
            else:
                # don't spam errors in the UI; show small warning
                st.sidebar.warning(f"Auto WhatsApp not sent: {info}")
    except Exception:
        pass


# ------------------ Scan Tab ------------------
with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    if csv_path.exists():
        df_scan = load_sheet(csv_path)
        today_col_scan = ensure_today_column(df_scan)
        total_learners = len(df_scan)
        present_today = (df_scan[today_col_scan].astype(str) == "1").sum()
        absent_today = total_learners - present_today

        k1, k2, k3 = st.columns(3)
        with k1:
            st.markdown(f'<div class="stat-card"><b>Total learners</b><div class="kpi">{total_learners}</div></div>', unsafe_allow_html=True)
        with k2:
            st.markdown(f'<div class="stat-card"><b>Present today</b><div class="kpi">{present_today}</div></div>', unsafe_allow_html=True)
        with k3:
            st.markdown(f'<div class="stat-card"><b>Absent today</b><div class="kpi">{absent_today}</div></div>', unsafe_allow_html=True)

    st.subheader("Scan")

    def handle_scan():
        scan_value = st.session_state.get("scan_box", "").strip()
        if not scan_value:
            return

        if not is_saturday_class_day():
            st.error("Today is not a class day. Scans are only allowed on Saturdays.")
        else:
            ok, msg = mark_scan_in_out(scan_value, csv_path, log_path)
            if ok:
                st.success(msg)
                st.toast("Scan recorded ✅", icon="✅")
            else:
                st.error(msg)

        st.session_state["scan_box"] = ""

    st.text_input(
        "Focus here and scan…",
        value=st.session_state.get("scan_box", ""),
        key="scan_box",
        label_visibility="collapsed",
        on_change=handle_scan,
    )

    c1, c2 = st.columns([1, 4])
    with c1:
        st.caption("Click in the box once, then scan each learner’s barcode.")
    with c2:
        st.caption("Class day is Saturday only. First scan = IN, next scan = OUT, then IN again, etc.")

    if csv_path.exists():
        log_df = load_log(log_path)
        _, date_str, _, _ = today_labels()
        current_in = get_currently_in(log_df, date_str)
        st.markdown(f"### Currently IN today ({date_str})")
        if current_in.empty:
            st.caption("No one is currently IN.")
        else:
            st.dataframe(current_in, use_container_width=True, height=260)

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Today Tab ------------------
with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    st.subheader(f"Today's Attendance — {today_col_label()}")

    if not csv_path.exists():
        st.info("CSV not found yet. Set the path in the sidebar.")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        df = load_sheet(csv_path)
        today_col = ensure_today_column(df)

        # Birthdays section (kept, but does NOT replace attendance)
        birthdays = get_birthdays_for_week(df)
        if birthdays:
            st.markdown("### 🎂 Birthdays around this week")
            for b in birthdays:
                full_name = f"{b['Name']} {b['Surname']}".strip()
                grade = b.get("Grade", "")
                if b["Kind"] == "today":
                    msg = "🎉 **Happy Birthday**"
                elif b["Kind"] == "belated":
                    msg = "🎂 **Happy belated birthday**"
                else:
                    msg = "🎁 **Upcoming birthday**"
                extra = f" (Grade {grade})" if grade else ""
                st.markdown(f"- {msg}, {full_name}{extra} – DOB: {b['DOB']}")
        else:
            st.caption("No birthdays this week or in the next 7 days.")

        st.divider()

        # Filters
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            grade_sel = st.selectbox("Filter by Grade", unique_sorted(df["Grade"]), key="today_grade")
        with fc2:
            area_sel = st.selectbox("Filter by Area", unique_sorted(df["Area"]), key="today_area")
        with fc3:
            pass

        grade_val = None if grade_sel == "(All)" else grade_sel
        area_val = None if area_sel == "(All)" else area_sel

        present, absent = get_present_absent(df, today_col, grade_val, area_val)

        total = len(present) + len(absent)
        s1, s2, s3 = st.columns(3)
        with s1:
            st.markdown(f'<div class="stat-card"><b>Registered</b><div class="kpi">{total}</div></div>', unsafe_allow_html=True)
        with s2:
            st.markdown(f'<div class="stat-card"><b>Present</b><div class="kpi">{len(present)}</div></div>', unsafe_allow_html=True)
        with s3:
            st.markdown(f'<div class="stat-card"><b>Absent</b><div class="kpi">{len(absent)}</div></div>', unsafe_allow_html=True)

        st.write("")
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Present**")
            cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in present.columns]
            st.dataframe(present[cols].sort_values(by=["Name","Surname"]), use_container_width=True, height=360)
        with cB:
            st.markdown("**Absent**")
            cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in absent.columns]
            st.dataframe(absent[cols].sort_values(by=["Name","Surname"]), use_container_width=True, height=360)

        # Trend
        date_cols = get_date_columns(df)
        if date_cols:
            trend = pd.DataFrame({"Date": date_cols, "Present": [(df[c].astype(str) == "1").sum() for c in date_cols]})
            st.markdown("**Attendance Trend**")
            chart = alt.Chart(trend).mark_line(point=True).encode(
                x=alt.X("Date:N", sort=None),
                y="Present:Q",
                tooltip=["Date", "Present"],
            ).properties(height=220)
            st.altair_chart(chart, use_container_width=True)

        # Downloads
        exp1, exp2 = st.columns(2)
        if not present.empty:
            exp1.download_button(
                "Download today's PRESENT (CSV)",
                data=present.to_csv(index=False).encode("utf-8"),
                file_name=f"present_{today_col}.csv",
                mime="text/csv",
                use_container_width=True,
                key="today_dl_present",
            )
        if not absent.empty:
            exp2.download_button(
                "Download today's ABSENT (CSV)",
                data=absent.to_csv(index=False).encode("utf-8"),
                file_name=f"absent_{today_col}.csv",
                mime="text/csv",
                use_container_width=True,
                key="today_dl_absent",
            )

        st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Grades Tab ------------------
with tabs[2]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    st.subheader("Grade Attendance by Saturday")

    if not csv_path.exists():
        st.info("CSV not found.")
    else:
        df = load_sheet(csv_path)
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
                present_in_grade = int(row["Present"])
                with k_cols[i]:
                    st.markdown(
                        f'''
                        <div class="stat-card">
                            <b>Grade {g}</b>
                            <div class="kpi">{pct_str}</div>
                            <div style="font-size:12px;color:#555;">
                                Present: {present_in_grade} / {int(grade_capacity)}
                            </div>
                        </div>
                        ''',
                        unsafe_allow_html=True,
                    )

            st.write("")
            st.markdown(f"**Summary for {date_sel}**")
            st.dataframe(summary_df, use_container_width=True, height=220)

            learners_view = combined_export_df[combined_export_df["Section"] == "LEARNERS"].copy()
            learners_view = learners_view[["Date","Grade","Name","Surname","Barcode","Status"]]
            st.write("")
            st.markdown(f"**Learner list for {date_sel} (all grades)**")
            st.dataframe(learners_view, use_container_width=True, height=360)

            st.download_button(
                "Download FULL grade report (Summary + Learners) — ONE CSV",
                data=combined_export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"grade_report_{date_sel}.csv",
                mime="text/csv",
                use_container_width=True,
                key="grades_dl_full",
            )
            st.caption("Tip: Filter the 'Section' column in Excel/Sheets to view SUMMARY or LEARNERS.")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ History Tab ------------------
with tabs[3]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("History")

    if not csv_path.exists():
        st.info("CSV not found.")
    else:
        df = load_sheet(csv_path)
        date_cols = get_date_columns(df)

        if not date_cols:
            st.info("No attendance dates yet.")
        else:
            date_sel = st.selectbox("Choose a date", list(reversed(date_cols)), key="history_date")
            present, absent = get_present_absent(df, date_sel)
            st.write(f"**Present:** {len(present)}  |  **Absent:** {len(absent)}")

            cols = [c for c in ["Name","Surname","Barcode","Grade","Area",date_sel] if c in df.columns]
            view = df[cols].copy()
            if date_sel in view.columns:
                view["Status"] = view[date_sel].astype(str).apply(lambda x: "Present" if x.strip() == "1" else "Absent")
                view = view.drop(columns=[date_sel])

            st.dataframe(view.sort_values(by=["Status","Name","Surname"]), use_container_width=True, height=420)

            st.download_button(
                "Download this date (CSV)",
                data=view.to_csv(index=False).encode("utf-8"),
                file_name=f"attendance_{date_sel}.csv",
                mime="text/csv",
                use_container_width=True,
                key="history_dl",
            )

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Tracking Tab ------------------
with tabs[4]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Tracking (per learner)")

    if not csv_path.exists():
        st.info("CSV not found.")
    else:
        df = load_sheet(csv_path)
        date_cols = get_date_columns(df)

        if not date_cols:
            st.info("No attendance dates yet.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                grade_sel = st.selectbox("Filter by Grade", unique_sorted(df["Grade"]), key="track_grade")
            with fc2:
                area_sel = st.selectbox("Filter by Area", unique_sorted(df["Area"]), key="track_area")
            with fc3:
                search = st.text_input("Search name/barcode", key="track_search")

            subset = df.copy()
            if grade_sel != "(All)":
                subset = subset[subset["Grade"].astype(str) == str(grade_sel)]
            if area_sel != "(All)":
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
                st.dataframe(metrics[show_cols], use_container_width=True, height=420)

                st.download_button(
                    "Download tracking report (CSV)",
                    data=metrics[show_cols].to_csv(index=False).encode("utf-8"),
                    file_name="attendance_tracking_report.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="track_dl",
                )
            else:
                st.info("No learners after filters/search.")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Manage Tab ------------------
with tabs[5]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Manage Learners / Barcodes")

    if not csv_path.exists():
        st.info("CSV not found.")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        df = load_sheet(csv_path)

        st.markdown("### Learner list (editable)")
        st.caption("You can edit directly and click Save. Keep Barcode as text to preserve leading zeros.")
        editable_cols = [c for c in ["Name","Surname","Barcode","Grade","Area","Date Of Birth"] if c in df.columns]
        if "Date Of Birth" not in df.columns:
            # optional DOB column if you want birthdays
            df["Date Of Birth"] = ""
            editable_cols.append("Date Of Birth")

        edited = st.data_editor(
            df[editable_cols],
            use_container_width=True,
            num_rows="dynamic",
            key="data_editor_manage",
        )

        csave1, csave2 = st.columns([1, 3])
        with csave1:
            if st.button("💾 Save changes", use_container_width=True):
                # merge back into df
                for c in editable_cols:
                    df[c] = edited[c].astype(str)
                save_sheet(df, csv_path)
                st.success("Saved ✅")
                st.rerun()
        with csave2:
            st.caption("Tip: If you add new learners, make sure they have Name/Surname (Barcode can be added later).")

        st.divider()

        st.markdown("### Assign / Update a Barcode (quick tool)")
        c1, c2, c3 = st.columns(3)
        with c1:
            name_in = st.text_input("Name", key="manage_name")
        with c2:
            surname_in = st.text_input("Surname", key="manage_surname")
        with c3:
            barcode_in = st.text_input("Barcode (keep leading zeros)", key="manage_barcode")

        if st.button("Save barcode to matching learner", key="manage_save"):
            mask = (df["Name"].astype(str).str.strip().str.lower() == name_in.strip().lower()) & \
                   (df["Surname"].astype(str).str.strip().str.lower() == surname_in.strip().lower())
            idx = df.index[mask].tolist()
            if not idx:
                st.error("Learner not found. Check spelling.")
            else:
                df.loc[idx, "Barcode"] = barcode_in.strip()
                save_sheet(df, csv_path)
                st.success("Saved ✅")
                st.rerun()

        st.divider()

        st.markdown("### Dates")
        colA, colB = st.columns([2, 1])
        with colA:
            new_date = st.text_input("New date label (e.g., 19-Aug)", key="manage_newdate")
        with colB:
            if st.button("Add date column", key="manage_adddate"):
                if new_date.strip():
                    ensure_date_column(df, new_date.strip())
                    save_sheet(df, csv_path)
                    st.success(f"Added column {new_date.strip()} ✅")
                    st.rerun()

        if st.button("➕ Add NEXT SATURDAY column", key="manage_next_sat"):
            ns = next_saturday_from()
            if ns in df.columns:
                st.info(f"{ns} already exists.")
            else:
                ensure_date_column(df, ns)
                save_sheet(df, csv_path)
                st.success(f"Added column {ns} ✅")
                st.rerun()

        st.divider()

        # WhatsApp Test (kept, but not replacing Manage)
        with st.expander("📩 WhatsApp Test (Twilio)", expanded=True):
            st.caption("Use this to confirm sending works.")

            if Client is None:
                st.warning("Twilio is not installed. Add `twilio` to requirements.txt.")
            else:
                test_to = st.text_input("Test recipient number (E.164)", value=WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "+27...", key="wa_test_to")
                test_msg = st.text_area("Message", value="Hello! This is a test message from the Tutor Class Attendance app ✅", key="wa_test_msg")

                if st.button("Send Test WhatsApp", key="wa_test_send"):
                    ok, info = send_whatsapp_message([test_to], test_msg)
                    if ok:
                        st.success(info)
                    else:
                        st.error(info)
                        st.info(
                            "If you see 403 / 'Unable to create record':\n"
                            "- You might still be on Twilio WhatsApp Sandbox\n"
                            "- The recipient must JOIN the sandbox first\n"
                            "- Or your WhatsApp Sender is not approved for production yet."
                        )

        st.markdown('</div>', unsafe_allow_html=True)


# Footer
st.markdown(
    """
    <hr style="margin-top:2rem; margin-bottom:0.5rem;">
    <p style="text-align:center; font-size:12px; color:#9ca3af;">
        “Walk each step steadily, and you will not lose your way.” – Jing Si Aphorism
    </p>
    """,
    unsafe_allow_html=True,
)

