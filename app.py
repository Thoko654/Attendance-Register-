# app.py — Tutor Class Attendance Register 2026
# Stable + Persist-safe (GitHub Storage) + Meta WhatsApp Cloud API + downloads
# Tabs: Scan • Today • Grades • History • Tracking • Manage

import os
import json
import time
import base64
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta, time as dtime
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import altair as alt
import requests


# ------------------ SECRETS / ENV ------------------
def get_secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then env vars."""
    try:
        if key in st.secrets:
            return str(st.secrets.get(key, default))
    except Exception:
        pass
    return str(os.environ.get(key, default))


# ------------------ CONFIG ------------------
APP_TZ = get_secret("APP_TIMEZONE", "Africa/Johannesburg")
TZ = ZoneInfo(APP_TZ)

CSV_DEFAULT = "attendance_clean.csv"

WHATSAPP_RECIPIENTS = [
    "+27836280453",
    "+27672291308",
]

SEND_DAY_WEEKDAY = 5          # Saturday
SEND_AFTER_TIME = dtime(9, 0) # 09:00
SEND_WINDOW_HOURS = 12

DEFAULT_GRADE_CAPACITY = 15

# Meta WhatsApp Cloud API (from Streamlit secrets / environment variables)
META_WA_TOKEN = get_secret("META_WA_TOKEN", "")
META_WA_API_VERSION = get_secret("META_WA_API_VERSION", "v22.0")
META_WA_PHONE_NUMBER_ID = get_secret("META_WA_PHONE_NUMBER_ID", "")

# ✅ FIX 1: GitHub default paths must match your repo (you have files in ROOT, not /data)
GITHUB_BRANCH = get_secret("GITHUB_BRANCH", "main")
GITHUB_FILE_PATH = get_secret("GITHUB_FILE_PATH", "attendance_clean.csv")
GITHUB_LOG_PATH = get_secret("GITHUB_LOG_PATH", "attendance_log.csv")
GITHUB_SENTSTATE_PATH = get_secret("GITHUB_SENTSTATE_PATH", "whatsapp_sent_state.json")


# ------------------ GITHUB STORAGE HELPERS ------------------
def gh_enabled() -> bool:
    return bool(get_secret("GITHUB_TOKEN") and get_secret("GITHUB_REPO"))

def gh_headers():
    return {
        "Authorization": f"Bearer {get_secret('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
    }

def gh_api_url(path: str) -> str:
    repo = get_secret("GITHUB_REPO")
    return f"https://api.github.com/repos/{repo}/contents/{path}"

def gh_read_text(path: str, branch: str) -> tuple[str, str]:
    """Return (text, sha). If missing, return ("", "")."""
    r = requests.get(gh_api_url(path), headers=gh_headers(), params={"ref": branch}, timeout=30)
    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    if r.status_code == 404:
        return "", ""
    raise RuntimeError(f"GitHub read failed {r.status_code}: {r.text}")

def gh_write_text(path: str, branch: str, text: str, sha: str | None, message: str):
    payload = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(gh_api_url(path), headers=gh_headers(), json=payload, timeout=30)
    if r.status_code in (200, 201):
        return

    # If SHA conflict (file changed), re-read latest SHA and retry once
    if r.status_code == 409:
        latest_text, latest_sha = gh_read_text(path, branch)
        payload["sha"] = latest_sha if latest_sha else None
        payload["content"] = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        r2 = requests.put(gh_api_url(path), headers=gh_headers(), json=payload, timeout=30)
        if r2.status_code in (200, 201):
            return
        raise RuntimeError(f"GitHub write retry failed {r2.status_code}: {r2.text}")

    raise RuntimeError(f"GitHub write failed {r.status_code}: {r.text}")


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

def _norm_phone(num: str) -> str:
    return "".join([c for c in str(num).strip() if c.isdigit()])

@contextmanager
def file_guard(_path: Path):
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


def ensure_base_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["Barcode", "Name", "Surname", "Grade", "Area"]:
        if col not in df.columns:
            df[col] = ""
    cols = list(df.columns)
    if "Barcode" in cols:
        cols.insert(0, cols.pop(cols.index("Barcode")))
        df = df[cols]
    return df

def create_empty_csv(csv_path: Path):
    df = pd.DataFrame(columns=["Barcode", "Name", "Surname", "Grade", "Area", "Date Of Birth"])
    with file_guard(csv_path):
        df.to_csv(csv_path, index=False)

def load_sheet(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        create_empty_csv(csv_path)
    with file_guard(csv_path):
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    return ensure_base_columns(df)

def save_sheet(df: pd.DataFrame, csv_path: Path):
    df = df.fillna("").astype(str)
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

def get_present_absent(df, date_col, grade=None, area=None):
    # Safety: if the date column does not exist, create it
    if date_col not in df.columns:
        df[date_col] = ""

    filt = pd.Series([True] * len(df))

    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)

    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)

    subset = df[filt].copy()

    present = subset[subset[date_col].astype(str) == "1"]
    absent = subset[subset[date_col].astype(str) != "1"]

    return present, absent

# ------------------ STORAGE: SHEET + LOG + SENT STATE ------------------
def load_sheet_from_storage() -> pd.DataFrame:
    # If GitHub enabled, load from GitHub
    if gh_enabled():
        text, sha = gh_read_text(GITHUB_FILE_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_sheet"] = sha

        if not text.strip():
            empty = "Barcode,Name,Surname,Grade,Area,Date Of Birth\n"
            gh_write_text(
                GITHUB_FILE_PATH, GITHUB_BRANCH, empty, sha=None,
                message=f"Create {GITHUB_FILE_PATH}"
            )
            text, sha = gh_read_text(GITHUB_FILE_PATH, GITHUB_BRANCH)
            st.session_state["_gh_sha_sheet"] = sha

        
        df = pd.read_csv(StringIO(text), dtype=str).fillna("")
df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
return ensure_base_columns(df)


    # fallback local
    csv_path = Path(CSV_DEFAULT)
    return load_sheet(csv_path)

def save_sheet_to_storage(df: pd.DataFrame):
    df = df.fillna("").astype(str)

    if gh_enabled():
        text = df.to_csv(index=False)
        sha = st.session_state.get("_gh_sha_sheet", "")
        gh_write_text(
            GITHUB_FILE_PATH, GITHUB_BRANCH, text, sha=sha or None,
            message=f"Update {GITHUB_FILE_PATH}"
        )
        _, new_sha = gh_read_text(GITHUB_FILE_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_sheet"] = new_sha
        return

    # fallback local
    save_sheet(df, Path(CSV_DEFAULT))

def load_log_from_storage() -> pd.DataFrame:
    columns = ["Timestamp","Date","Time","Barcode","Name","Surname","Action"]

    if gh_enabled():
        text, sha = gh_read_text(GITHUB_LOG_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_log"] = sha

        if not text.strip():
            empty = ",".join(columns) + "\n"
            gh_write_text(
                GITHUB_LOG_PATH, GITHUB_BRANCH, empty, sha=None,
                message=f"Create {GITHUB_LOG_PATH}"
            )
            text, sha = gh_read_text(GITHUB_LOG_PATH, GITHUB_BRANCH)
            st.session_state["_gh_sha_log"] = sha

        df = pd.read_csv(StringIO(text), dtype=str).fillna("")
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        return df[columns]

    # fallback local
    log_path = Path(CSV_DEFAULT).with_name("attendance_log.csv")
    if not log_path.exists():
        return pd.DataFrame(columns=columns)
    with file_guard(log_path):
        df = pd.read_csv(log_path, dtype=str).fillna("")
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    return df[columns]

def save_log_to_storage(df: pd.DataFrame):
    df = df.fillna("").astype(str)

    if gh_enabled():
        text = df.to_csv(index=False)
        sha = st.session_state.get("_gh_sha_log", "")
        gh_write_text(
            GITHUB_LOG_PATH, GITHUB_BRANCH, text, sha=sha or None,
            message=f"Update {GITHUB_LOG_PATH}"
        )
        _, new_sha = gh_read_text(GITHUB_LOG_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_log"] = new_sha
        return

    # fallback local
    log_path = Path(CSV_DEFAULT).with_name("attendance_log.csv")
    with file_guard(log_path):
        df.to_csv(log_path, index=False)

def already_sent_today_storage() -> bool:
    if gh_enabled():
        text, sha = gh_read_text(GITHUB_SENTSTATE_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_sent"] = sha
        if not text.strip():
            return False
        try:
            data = json.loads(text)
            return data.get("date") == now_local().strftime("%Y-%m-%d")
        except Exception:
            return False

    # fallback local
    p = Path(CSV_DEFAULT).with_name(".whatsapp_sent_state.json")
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("date") == now_local().strftime("%Y-%m-%d")
    except Exception:
        return False

def mark_sent_today_storage():
    payload = {
        "date": now_local().strftime("%Y-%m-%d"),
        "ts": now_local().isoformat(timespec="seconds")
    }
    if gh_enabled():
        text = json.dumps(payload, indent=2)
        sha = st.session_state.get("_gh_sha_sent", "")
        gh_write_text(
            GITHUB_SENTSTATE_PATH, GITHUB_BRANCH, text, sha=sha or None,
            message=f"Update {GITHUB_SENTSTATE_PATH}"
        )
        _, new_sha = gh_read_text(GITHUB_SENTSTATE_PATH, GITHUB_BRANCH)
        st.session_state["_gh_sha_sent"] = new_sha
        return

    # fallback local
    p = Path(CSV_DEFAULT).with_name(".whatsapp_sent_state.json")
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ------------------ IN/OUT LOG LOGIC ------------------
def determine_next_action(log_df: pd.DataFrame, barcode: str, date_str: str) -> str:
    norm_b = _norm(barcode)
    today_rows = log_df[
        (log_df["Date"] == date_str) &
        (log_df["Barcode"].astype(str).apply(_norm) == norm_b)
    ]
    if today_rows.empty:
        return "IN"
    last_action = str(today_rows.iloc[-1]["Action"]).upper()
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

def mark_scan_in_out(barcode: str) -> tuple[bool, str]:
    barcode = str(barcode).strip()
    if not barcode:
        return False, "Empty scan."

    df = load_sheet_from_storage()
    log_df = load_log_from_storage()

    date_col, date_str, time_str, ts = today_labels()
    ensure_date_column(df, date_col)

    matches = df.index[df["Barcode"].apply(_norm) == _norm(barcode)].tolist()
    if not matches:
        return False, "Barcode not found. Add it to the correct learner in Manage."

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

    save_sheet_to_storage(df)
    save_log_to_storage(log_df)

    current_in = get_currently_in(log_df, date_str)
    msgs.append("")
    msgs.append(f"Currently IN today ({date_str}): {len(current_in)}")
    for _, r in current_in.iterrows():
        who2 = (str(r["Name"]).strip() + " " + str(r["Surname"]).strip()).strip() or f"[{r['Barcode']}]"
        msgs.append(f"  • {who2} [{r['Barcode']}]")

    return True, "\n".join(msgs)


# ------------------ TRACKING ------------------
def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Sessions","Present","Absent","Attendance %","Last present","Grade","Area"])

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
def meta_send_whatsapp_text(to_number: str, body: str) -> tuple[bool, str]:
    if not META_WA_TOKEN or not META_WA_PHONE_NUMBER_ID:
        return False, "Missing META_WA_TOKEN or META_WA_PHONE_NUMBER_ID (check Streamlit secrets)."

    to_clean = _norm_phone(to_number)
    if not to_clean:
        return False, f"Invalid recipient number: {to_number}"

    url = f"https://graph.facebook.com/{META_WA_API_VERSION}/{META_WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WA_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "text",
        "text": {"body": body, "preview_url": False},
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            return True, "Sent successfully."
        try:
            return False, f"Meta API error {r.status_code}: {r.json()}"
        except Exception:
            return False, f"Meta API error {r.status_code}: {r.text}"
    except Exception as e:
        return False, f"Request failed: {e}"

def send_whatsapp_message(to_numbers: list[str], body: str) -> tuple[bool, str]:
    sent_any = False
    errors = []
    for n in to_numbers:
        ok, info = meta_send_whatsapp_text(n, body)
        if ok:
            sent_any = True
        else:
            errors.append(f"{n}: {info}")

    if sent_any and not errors:
        return True, "Sent successfully."
    if sent_any and errors:
        return True, "Sent to some numbers; failed for: " + " | ".join(errors)
    return False, "Failed: " + (" | ".join(errors) if errors else "unknown")

def should_send_now() -> bool:
    n = now_local()
    if n.weekday() != SEND_DAY_WEEKDAY:
        return False
    if n.time() < SEND_AFTER_TIME:
        return False
    end_time = (datetime.combine(n.date(), SEND_AFTER_TIME, tzinfo=TZ) + timedelta(hours=SEND_WINDOW_HOURS)).time()
    return n.time() <= end_time


# ------------------ GRADES EXPORT ------------------
def build_grades_export(df: pd.DataFrame, date_sel: str, grades: list[str], grade_capacity: int):
    summary_rows = []
    for g in grades:
        mask_grade = df["Grade"].astype(str) == g
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

st.markdown("""
<style>
main .block-container { padding-top: 0.8rem; padding-bottom: 1.5rem; }
.stTabs [data-baseweb="tab-list"] { gap: 10px; }

.section-card{
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  margin-bottom: 12px;
}
.stat-card{
  padding: 12px 14px;
  border: 1px solid #eef2f7;
  border-radius: 14px;
  background: #fbfdff;
}
.kpi{
  font-size: 30px;
  font-weight: 800;
  line-height: 1.1;
  margin-top: 4px;
}
</style>
""", unsafe_allow_html=True)

def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ✅ FIX 2: Your repo file is named "tzu_chi_logo.png" (not "tzu_chi_logo.png")
LOGO_FILE = "tzu_chi_logo.png"

# --- Center Header Card ---
st.markdown('<div class="section-card">', unsafe_allow_html=True)

logo_html = ""
if Path(LOGO_FILE).exists():
    b64 = img_to_base64(LOGO_FILE)
    logo_html = f"""
    <div style="display:flex; justify-content:center; align-items:center; margin-top:6px;">
        <img src="data:image/png;base64,{b64}" style="width:170px; height:auto;" />
    </div>
    """

st.markdown(
    f"""
    {logo_html}
    <div style="text-align:center; margin-top:10px;">
      <div style="font-size:46px; font-weight:900; line-height:1.05;">
        Tutor Class Attendance Register 2026
      </div>
      <div style="margin-top:10px; font-size:16px; color:#6b7280;">
        Today: <b>{today_col_label()}</b> · Timezone: <b>{APP_TZ}</b>
      </div>
      <div style="
        margin: 12px auto 4px auto;
        max-width: 980px;
        padding: 10px 18px;
        border-radius: 999px;
        background: #f5f7fa;
        border: 1px solid #e4e7ec;
        font-size: 15px;
        color: #374151;
      ">
        📌 Scan learner barcodes to mark <b>IN / OUT</b> and track participation over time.
      </div>
    </div>
    """,
    unsafe_allow_html=True
)
st.markdown("</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("Settings")
    if Path(LOGO_FILE).exists():
        st.image(LOGO_FILE, use_container_width=True)

    st.markdown("### Storage Mode")
    if gh_enabled():
        st.success("GitHub storage ✅")
        st.caption(f"Repo: {get_secret('GITHUB_REPO')}")
        st.caption(f"Branch: {GITHUB_BRANCH}")
        st.caption(f"Sheet: {GITHUB_FILE_PATH}")
        st.caption(f"Log: {GITHUB_LOG_PATH}")
    else:
        st.warning("Local storage (may reset on redeploy) ⚠️")
        st.caption("Add GitHub secrets to make data persistent.")

    st.markdown("### Grade capacity (benchmark)")
    grade_capacity = st.number_input(
        "Capacity per grade",
        min_value=1, max_value=200,
        value=DEFAULT_GRADE_CAPACITY,
        step=1
    )

    st.markdown("### WhatsApp Recipients")
    st.write(WHATSAPP_RECIPIENTS)

    st.markdown("### Meta WhatsApp Status")
    if META_WA_TOKEN and META_WA_PHONE_NUMBER_ID:
        st.success("Meta WhatsApp configured ✅")
    else:
        st.warning("Meta WhatsApp missing token/phone ID")


tabs = st.tabs(["📷 Scan", "📅 Today", "🏫 Grades", "📚 History", "📈 Tracking", "🛠 Manage"])

# (Everything else below stays exactly the same as your original code.)
# ✅ Keep the rest of your file unchanged from here onward.



# ------------------ AUTO-SEND (Birthdays) ------------------
try:
    df_auto = load_sheet_from_storage()
    birthdays = get_birthdays_for_week(df_auto)
    if birthdays and should_send_now() and not already_sent_today_storage():
        msg = build_birthday_message(birthdays)
        ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
        if ok:
            mark_sent_today_storage()
            st.toast("WhatsApp birthday summary sent ✅", icon="✅")
        else:
            st.sidebar.warning(f"Auto WhatsApp not sent: {info}")
except Exception:
    pass


# ------------------ Scan Tab ------------------
with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)

    df_scan = load_sheet_from_storage()
    today_col_scan = ensure_today_column(df_scan)
    save_sheet_to_storage(df_scan)

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
            ok, msg = mark_scan_in_out(scan_value)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
        st.session_state["scan_box"] = ""

    st.text_input("Focus here and scan…", key="scan_box", label_visibility="collapsed", on_change=handle_scan)

    log_df = load_log_from_storage()
    _, date_str, _, _ = today_labels()
    current_in = get_currently_in(log_df, date_str)
    st.markdown(f"### Currently IN today ({date_str})")
    if not current_in.empty:
        st.dataframe(current_in, use_container_width=True, height=260)
    else:
        st.caption("No one is currently IN.")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Today Tab ------------------
with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader(f"Today's Attendance — {today_col_label()}")

    df = load_sheet_from_storage()
    today_col = ensure_today_column(df)
    save_sheet_to_storage(df)

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
        grade_sel = st.selectbox("Filter by Grade", unique_sorted(df["Grade"]), key="today_grade")
    with fc2:
        area_sel = st.selectbox("Filter by Area", unique_sorted(df["Area"]), key="today_area")

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
        st.dataframe(present[cols].sort_values(by=["Name","Surname"]), use_container_width=True, height=360)
    with cB:
        st.markdown("**Absent**")
        cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in absent.columns]
        st.dataframe(absent[cols].sort_values(by=["Name","Surname"]), use_container_width=True, height=360)

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

    df = load_sheet_from_storage()
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

        st.download_button("Download FULL grade report (Summary + Learners) — ONE CSV",
                           data=combined_export_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"grade_report_{date_sel}.csv",
                           mime="text/csv", use_container_width=True, key="grades_dl_full")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ History Tab ------------------
with tabs[3]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("History")

    df = load_sheet_from_storage()
    date_cols = get_date_columns(df)
    if not date_cols:
        st.info("No attendance dates yet.")
    else:
        date_sel = st.selectbox("Choose a date", list(reversed(date_cols)), key="history_date")
        cols = [c for c in ["Name","Surname","Barcode","Grade","Area",date_sel] if c in df.columns]
        view = df[cols].copy()
        view["Status"] = df[date_sel].astype(str).apply(lambda x: "Present" if x.strip() == "1" else "Absent")
        view = view.drop(columns=[date_sel])

        st.dataframe(view.sort_values(by=["Status","Name","Surname"]), use_container_width=True, height=420)
        st.download_button("Download this date (CSV)", data=view.to_csv(index=False).encode("utf-8"),
                           file_name=f"attendance_{date_sel}.csv", mime="text/csv", use_container_width=True, key="history_dl")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Tracking Tab ------------------
with tabs[4]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Tracking (per learner)")

    df = load_sheet_from_storage()
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
            st.download_button("Download tracking report (CSV)", data=metrics[show_cols].to_csv(index=False).encode("utf-8"),
                               file_name="attendance_tracking_report.csv", mime="text/csv", use_container_width=True, key="track_dl")

    st.markdown('</div>', unsafe_allow_html=True)


# ------------------ Manage Tab ------------------
with tabs[5]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Manage")

    df = load_sheet_from_storage()
    if "Date Of Birth" not in df.columns:
        df["Date Of Birth"] = ""

    st.markdown("## Learner list (editable)")
    editable_cols = ["Name","Surname","Barcode","Grade","Area","Date Of Birth"]
    edited = st.data_editor(
        df[editable_cols],
        use_container_width=True,
        num_rows="dynamic",
        key="data_editor_manage"
    )

    if st.button("💾 Save changes (table)", use_container_width=True):
        for c in editable_cols:
            df[c] = edited[c].astype(str)
        save_sheet_to_storage(df)
        st.success("Saved ✅")
        st.rerun()

    st.divider()

    st.markdown("## Manage learners")
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown("### ➕ Add a new learner")
        with st.form("add_learner_form", clear_on_submit=True):
            name = st.text_input("Name")
            surname = st.text_input("Surname")
            barcode = st.text_input("Barcode")
            grade = st.text_input("Grade (e.g., 5)")
            area = st.text_input("Area")
            dob = st.text_input("Date Of Birth (optional)", help="Formats: 12-Jan-2012 or 12/01/2012 or 2012-01-12")
            submitted = st.form_submit_button("Add learner ✅")

        if submitted:
            barcode_clean = str(barcode).strip()
            if not name.strip() or not barcode_clean:
                st.error("Name and Barcode are required.")
            else:
                exists = df["Barcode"].astype(str).apply(_norm).eq(_norm(barcode_clean)).any()
                if exists:
                    st.error("This barcode already exists. Use the table to edit the existing learner.")
                else:
                    new_row = {
                        "Barcode": barcode_clean,
                        "Name": str(name).strip(),
                        "Surname": str(surname).strip(),
                        "Grade": str(grade).strip(),
                        "Area": str(area).strip(),
                        "Date Of Birth": str(dob).strip(),
                    }
                    for c in df.columns:
                        if c not in new_row:
                            new_row[c] = ""
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    save_sheet_to_storage(df)
                    st.success("Learner added ✅")
                    st.rerun()

    with c2:
        st.markdown("### 🗑 Delete a learner")
        delete_mode = st.radio("Delete by", ["Barcode", "Name"], horizontal=True, key="del_mode")

        if delete_mode == "Barcode":
            options = sorted([b for b in df["Barcode"].astype(str).unique() if b.strip() != ""])
            pick = st.selectbox("Select Barcode to delete", ["(Select)"] + options)
            if st.button("Delete selected learner", type="primary", use_container_width=True):
                if pick == "(Select)":
                    st.error("Please select a barcode.")
                else:
                    before = len(df)
                    df = df[df["Barcode"].astype(str).apply(_norm) != _norm(pick)].copy()
                    after = len(df)
                    save_sheet_to_storage(df)
                    st.success(f"Deleted {before - after} record(s) ✅")
                    st.rerun()
        else:
            names = df.apply(lambda r: f"{str(r.get('Name','')).strip()} {str(r.get('Surname','')).strip()}  [{str(r.get('Barcode','')).strip()}]", axis=1).tolist()
            pick = st.selectbox("Select learner to delete", ["(Select)"] + names)
            if st.button("Delete selected learner", type="primary", use_container_width=True):
                if pick == "(Select)":
                    st.error("Please select a learner.")
                else:
                    try:
                        b = pick.split("[", 1)[1].split("]", 1)[0]
                    except Exception:
                        b = ""
                    if not b:
                        st.error("Could not read barcode from selection.")
                    else:
                        before = len(df)
                        df = df[df["Barcode"].astype(str).apply(_norm) != _norm(b)].copy()
                        after = len(df)
                        save_sheet_to_storage(df)
                        st.success(f"Deleted {before - after} record(s) ✅")
                        st.rerun()

    st.divider()

    st.markdown("## Dates")
    colA, colB, colC = st.columns([3, 2, 2])
    with colA:
        new_date = st.text_input("New date label (e.g., 19-Aug)", key="manage_newdate")
    with colB:
        if st.button("Add date column", use_container_width=True):
            if new_date.strip():
                ensure_date_column(df, new_date.strip())
                save_sheet_to_storage(df)
                st.success(f"Added column {new_date.strip()} ✅")
                st.rerun()
            else:
                st.error("Please enter a date label.")
    with colC:
        if st.button("➕ Add NEXT SATURDAY", use_container_width=True):
            ns = next_saturday_from()
            if ns in df.columns:
                st.info(f"{ns} already exists.")
            else:
                ensure_date_column(df, ns)
                save_sheet_to_storage(df)
                st.success(f"Added column {ns} ✅")
                st.rerun()

    st.divider()

    with st.expander("📩 WhatsApp Test (Meta Cloud API)", expanded=False):
        st.caption("Uses META_WA_TOKEN + META_WA_PHONE_NUMBER_ID from Streamlit secrets.")
        test_to = st.text_input("Test recipient number (E.164)", value=WHATSAPP_RECIPIENTS[0] if WHATSAPP_RECIPIENTS else "+27...")
        test_msg = st.text_area("Message", value="Hello! This is a test message from the Tutor Class Attendance app ✅")
        if st.button("Send Test WhatsApp", use_container_width=True):
            ok, info = send_whatsapp_message([test_to], test_msg)
            if ok:
                st.success(info)
            else:
                st.error(info)

    st.markdown('</div>', unsafe_allow_html=True)


st.markdown(
    """
    <hr style="margin-top:2rem; margin-bottom:0.5rem;">
    <p style="text-align:center; font-size:12px; color:#9ca3af;">
        “Walk each step steadily, and you will not lose your way.” – Jing Si Aphorism
    </p>
    """,
    unsafe_allow_html=True,
)




