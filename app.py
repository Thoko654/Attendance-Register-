# app.py — Streamlit Attendance (beautiful edition, with IN/OUT + logo)
# Tabs: Scan • Today • Grades • History • Tracking • Manage
# Birthday reminders via WhatsApp (Twilio WhatsApp API) — SAFE VERSION

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from contextlib import contextmanager
import time
import altair as alt
import os

# ✅ Twilio WhatsApp (SAFE IMPORT — app won't crash if not installed)
try:
    from twilio.rest import Client
except Exception:
    Client = None

CSV_DEFAULT = "attendance_clean.csv"

# ✅ WhatsApp recipients (must include country code, no spaces)
# Example South Africa: +27...
WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

# WhatsApp send rules
SEND_DAY_WEEKDAY = 5            # Saturday (Mon=0 ... Sun=6)
SEND_AFTER_TIME = dtime(9, 0)   # 09:00
SEND_WINDOW_HOURS = 12          # Only send between 09:00 and 21:00 (safety window)


# ---------- Utilities ----------
def today_col_label() -> str:
    now = datetime.now()
    day = str(int(now.strftime("%d")))  # no leading zero
    mon = now.strftime("%b")
    return f"{day}-{mon}"

def today_labels():
    """Return (date_col_label, date_str, time_str, timestamp)."""
    now = datetime.now()
    day = str(int(now.strftime("%d")))
    mon = now.strftime("%b")
    date_col = f"{day}-{mon}"           # for sheet columns
    date_str = now.strftime("%Y-%m-%d") # for logs
    time_str = now.strftime("%H:%M:%S")
    ts = now.isoformat(timespec="seconds")
    return date_col, date_str, time_str, ts

def is_saturday_class_day() -> bool:
    return datetime.now().weekday() == 5

def next_saturday_from(last_dt: datetime | None = None) -> str:
    base = last_dt or datetime.now()
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

def load_sheet(csv_path: Path) -> pd.DataFrame:
    with file_guard(csv_path):
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "Barcode" not in df.columns:
        df.insert(1, "Barcode", "")
    if "Name" not in df.columns:
        df["Name"] = ""
    if "Surname" not in df.columns:
        df["Surname"] = ""
    return df

def save_sheet(df: pd.DataFrame, csv_path: Path):
    with file_guard(csv_path):
        df.to_csv(csv_path, index=False)

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
            return datetime.strptime(x, "%d-%b").timetuple().tm_yday
        except Exception:
            return 999

    return sorted(cols, key=_key)

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

def unique_sorted(series):
    vals = sorted([v for v in series.astype(str).unique() if v.strip() != "" and v != "nan"])
    return ["(All)"] + vals


# ---------- IN/OUT log helpers ----------
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
            "Add this code to the 'Barcode' column for the correct learner (Manage tab)."
        )

    action = determine_next_action(log_df, barcode, date_str)

    msgs = []
    for idx in matches:
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


# ---------- Tracking helpers ----------
def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=[
            "Name","Surname","Barcode","Sessions","Present","Absent","Attendance %",
            "Last present","Current streak","Longest streak"
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

    def streaks(lst):
        longest = cur = 0
        for v in lst:
            if v == 1:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
        cur_now = 0
        for v in reversed(lst):
            if v == 1:
                cur_now += 1
            else:
                break
        return cur_now, longest

    current_streak, longest_streak = [], []
    for i in range(len(df)):
        cur, lng = streaks(present_mat.iloc[i].tolist())
        current_streak.append(cur)
        longest_streak.append(lng)

    result = pd.DataFrame({
        "Name": df.get("Name", ""),
        "Surname": df.get("Surname", ""),
        "Barcode": df.get("Barcode", ""),
        "Sessions": sessions,
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present,
        "Current streak": current_streak,
        "Longest streak": longest_streak,
    })
    return result.sort_values(by=["Attendance %","Name","Surname"], ascending=[False,True,True]).reset_index(drop=True)


# ---------- Birthday helpers ----------
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

def get_birthdays_for_week(df: pd.DataFrame, today: datetime | None = None):
    if "Date Of Birth" not in df.columns:
        return []
    if today is None:
        today = datetime.now().date()

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


# ---------- WhatsApp (Twilio) ----------
def send_whatsapp_message(to_numbers: list[str], body: str) -> bool:
    """
    Uses env vars (Streamlit Secrets):
      TWILIO_ACCOUNT_SID
      TWILIO_AUTH_TOKEN
      TWILIO_WHATSAPP_FROM   (example: whatsapp:+14155238886)
    """
    if Client is None:
        st.error("Twilio is not installed. Add 'twilio' to requirements.txt and redeploy.")
        return False

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    wa_from = os.environ.get("TWILIO_WHATSAPP_FROM")  # like: whatsapp:+1415...

    if not sid or not token or not wa_from:
        st.error("Missing Twilio secrets: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM")
        return False

    client = Client(sid, token)

    ok_any = False
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
            ok_any = True
        except Exception as e:
            st.error(f"Failed to send WhatsApp to {n}: {e}")

    return ok_any


def should_send_now() -> bool:
    """Saturday after 09:00 (and within a safe window)."""
    now = datetime.now()
    if now.weekday() != SEND_DAY_WEEKDAY:
        return False
    if now.time() < SEND_AFTER_TIME:
        return False
    end_time = (datetime.combine(now.date(), SEND_AFTER_TIME) + timedelta(hours=SEND_WINDOW_HOURS)).time()
    if now.time() > end_time:
        return False
    return True


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


# ---------- Grades report helper ----------
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


# ---------- Look & Feel ----------
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
    st.image("tzu_chi_logo.png", width=200)

st.markdown("<h1 style='text-align:center; margin-bottom:-5px;'>Tutor Class Attendance Register 2026</h1>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align:center; color:#666;'>Today: <b>{today_col_label()}</b></p>", unsafe_allow_html=True)

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
    st.image("tzu_chi_logo.png", use_column_width=True)
    csv_path_str = st.text_input("CSV file path", CSV_DEFAULT, key="path_input")
    csv_path = Path(csv_path_str).expanduser()
    log_path = csv_path.with_name("attendance_log.csv")
    st.caption("Keep this CSV in a shared OneDrive/Drive folder for team use.")

    st.markdown("### 🎂 WhatsApp Recipients")
    st.caption("Use full numbers with country code, e.g. +2781...")
    st.write(WHATSAPP_RECIPIENTS)

    st.markdown("### ✅ WhatsApp Status")
    if Client is None:
        st.error("Twilio not installed (add to requirements.txt).")
    else:
        st.success("Twilio installed ✅")

tabs = st.tabs(["📷 Scan", "📅 Today", "🏫 Grades", "📚 History", "📈 Tracking", "🛠 Manage"])


# ---------- Scan Tab ----------
with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    if csv_path.exists():
        df_scan = load_sheet(csv_path)
        today_col_scan = today_col_label()
        ensure_today_column(df_scan)
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


# ---------- Today Tab ----------
with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    st.subheader(f"Today's Attendance — {today_col_label()}")
    df = load_sheet(csv_path) if csv_path.exists() else pd.DataFrame()
    today_col = today_col_label()

    if not df.empty:
        ensure_today_column(df)

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

        # ✅ Auto-send WhatsApp once per day (ONLY while app is running/open)
        if birthdays and should_send_now():
            today_str = datetime.now().strftime("%Y-%m-%d")
            already_sent_for = st.session_state.get("birthday_whatsapp_sent_for")
            if already_sent_for != today_str:
                msg = build_birthday_message(birthdays)
                ok = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
                if ok:
                    st.success("Automatic WhatsApp birthday summary sent ✅")
                    st.session_state["birthday_whatsapp_sent_for"] = today_str

    else:
        st.info("CSV not found yet. Set the path in the sidebar.")

    st.markdown('</div>', unsafe_allow_html=True)


# ---------- Manage Tab (Test WhatsApp) ----------
with tabs[5]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Manage + WhatsApp Test")

    st.markdown("### 📩 Send a TEST WhatsApp message")
    st.caption("This is the best way to confirm it works.")

    test_to = st.text_input("Test recipient number", value=WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "")
    test_msg = st.text_area("Message", value="Hello! This is a test message from the Tutor Class Attendance app ✅")

    if st.button("Send Test WhatsApp"):
        ok = send_whatsapp_message([test_to], test_msg)
        if ok:
            st.success("✅ Sent! Check the phone WhatsApp.")
        else:
            st.error("❌ Not sent. Check the error message above.")

    st.markdown('</div>', unsafe_allow_html=True)


# ---------- Footer ----------
st.markdown(
    """
    <hr style="margin-top:2rem; margin-bottom:0.5rem;">
    <p style="text-align:center; font-size:12px; color:#9ca3af;">
        “Walk each step steadily, and you will not lose your way.” – Jing Si Aphorism
    </p>
    """,
    unsafe_allow_html=True,
)
