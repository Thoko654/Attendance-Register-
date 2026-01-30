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
SEND_DAY_WEEKDAY = 5           # Saturday (Mon=0 ... Sun=6)
SEND_AFTER_TIME = dtime(9, 0)  # 09:00

# Grade capacity benchmark (you said you want % per grade)
DEFAULT_GRADE_BENCHMARK = 20

# Meta WhatsApp Cloud API (use Streamlit Secrets or env vars)
META_WA_TOKEN = (st.secrets.get("META_WA_TOKEN", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_TOKEN", "").strip()
META_WA_PHONE_NUMBER_ID = (st.secrets.get("META_WA_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
META_WA_API_VERSION = (st.secrets.get("META_WA_API_VERSION", "") if hasattr(st, "secrets") else "").strip() or os.environ.get("META_WA_API_VERSION", "v22.0").strip()


# ------------------ TIME / LABEL UTILITIES ------------------

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
        return df.iloc[0:0].copy(), df.iloc[0:0].copy()

    if date_col not in df.columns:
        # no marks yet
        return df.iloc[0:0].copy(), df.copy()

    subset = df.copy()
    if grade and "Grade" in subset.columns:
        subset = subset[subset["Grade"].astype(str) == str(grade)]

    present = subset[subset[date_col].astype(str).str.strip() == "1"].copy()
    absent = subset[subset[date_col].astype(str).str.strip() != "1"].copy()
    return present, absent


# ------------------ TRACKING ------------------

def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if df is None or df.empty:
        return pd.DataFrame()

    base_cols = ["Name", "Surname", "Barcode", "Grade", "Area"]
    for c in base_cols:
        if c not in df.columns:
            df[c] = ""

    if not date_cols:
        out = df[base_cols].copy()
        out["Sessions"] = 0
        out["Present"] = 0
        out["Absent"] = 0
        out["Attendance %"] = 0.0
        out["Last present"] = "—"
        return out

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
        "Name": df["Name"],
        "Surname": df["Surname"],
        "Barcode": df["Barcode"],
        "Grade": df["Grade"],
        "Area": df["Area"],
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
                results.append(f"{to_e164}: FAILED ({r.status_code}) {emsg}")

        except Exception as e:
            results.append(f"{to_e164}: FAILED ({e})")

    if sent_any:
        return True, " | ".join(results)
    return False, " | ".join(results) if results else "No recipients."


# ------------------ BIRTHDAYS (simple: uses DOB column) ------------------

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


# ------------------ AUTO SEND (BIRTHDAYS) ------------------

def should_auto_send(now: datetime) -> bool:
    return (now.weekday() == SEND_DAY_WEEKDAY) and (now.time() >= SEND_AFTER_TIME)

def run_auto_send(db_path: Path):
    """
    IMPORTANT: Streamlit Cloud does NOT run in the background.
    This auto-send only runs when the app is opened/refreshed after the scheduled time.
    """
    ensure_auto_send_table(db_path)

    now = now_local()
    _, date_str, _, ts_iso = today_labels()

    if not should_auto_send(now):
        return
    if already_sent_today(db_path, date_str):
        return

    df_now = get_wide_sheet(db_path)
    birthdays = get_birthdays_for_week(df_now)

    msg = build_birthday_message(birthdays)
    ok, info = send_whatsapp_message(WHATSAPP_RECIPIENTS, msg)
    if ok:
        mark_sent_today(db_path, date_str, ts_iso)
        st.sidebar.success("✅ Auto WhatsApp sent today")
    else:
        st.sidebar.warning(f"⚠️ Auto WhatsApp failed: {info}")


# ------------------ PAGE SETUP ------------------

st.set_page_config(page_title="Tutor Class Attendance Register 2026", page_icon="✅", layout="wide")

st.markdown(
    """
    <style>
      .center-card { padding: 14px 18px; border: 1px solid #eee; border-radius: 14px; background: #fff; text-align: center; }
      .title { margin: 0; font-size: 40px; font-weight: 800; color: #111; }
      .subtitle { margin: 6px 0 0; font-size: 14px; color: #555; }
      .small-help { font-size: 13px; color: #666; line-height: 1.4; }
      .scanbox input { font-size: 22px !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------ DB INIT ------------------

init_db(DB_PATH)
seed_learners_from_csv_if_empty(DB_PATH)

try:
    run_auto_send(DB_PATH)
except Exception as e:
    st.sidebar.warning(f"⚠️ Auto-send error: {e}")


# ------------------ HEADER (CENTERED) ------------------

logo_b64 = ""
if Path("tzu_chi_logo.png").exists():
    logo_b64 = base64.b64encode(Path("tzu_chi_logo.png").read_bytes()).decode("utf-8")

st.markdown(
    f"""
    <div class="center-card">
      {"<img src='data:image/png;base64," + logo_b64 + "' width='120' style='display:block;margin:0 auto 10px auto;'/>" if logo_b64 else ""}
      <h1 class="title">Tutor Class Attendance Register 2026</h1>
      <p class="subtitle">
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


# ------------------ AUTO SCAN HANDLER ------------------

def handle_scan():
    code = norm_barcode(st.session_state.get("scan_input", ""))
    st.session_state["scan_input"] = ""  # clear immediately

    if not code:
        return

    date_col, date_iso, _, ts = today_labels()

    # mark attendance
    ok, msg = insert_present_mark(DB_PATH, code, date_col, date_iso, ts)

    if not ok:
        st.session_state["scan_status"] = f"❌ {msg}"
        return

    # IN/OUT toggle
    action = determine_next_action(DB_PATH, code)
    append_inout_log(DB_PATH, code, action, ts)

    st.session_state["scan_status"] = f"✅ {code} marked Present + {action}"


# ------------------ TABS ------------------

tabs = st.tabs(["Scan", "Today", "Grades", "History", "Tracking", "Manage"])

# ---- (0) Scan
with tabs[0]:
    st.subheader("Scan")
    st.caption("Scan the barcode → it auto-submits and marks Present. It also toggles IN/OUT automatically.")

    st.markdown("<div class='scanbox'>", unsafe_allow_html=True)
    st.text_input(
        "Scan or type barcode here",
        key="scan_input",
        on_change=handle_scan,
        placeholder="Scan barcode…"
    )
    st.markdown("</div>", unsafe_allow_html=True)

    status = st.session_state.get("scan_status", "")
    if status:
        st.info(status)

    df = get_wide_sheet(DB_PATH)
    currently_in = get_currently_in(DB_PATH)

    st.markdown("### Currently IN (Today)")
    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        in_df = df[df["Barcode"].astype(str).isin(currently_in)][["Name", "Surname", "Grade", "Barcode"]].copy()
        if in_df.empty:
            st.write("None")
        else:
            st.dataframe(in_df, use_container_width=True, hide_index=True)

# ---- (1) Today
with tabs[1]:
    st.subheader("Today")
    df = get_wide_sheet(DB_PATH)
    date_col, _, _, _ = today_labels()

    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        present, absent = get_present_absent(df, date_col)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total learners", len(df))
        c2.metric("Present today", len(present))
        pct = (len(present) / len(df) * 100) if len(df) else 0
        c3.metric("Attendance %", f"{pct:.1f}%")

        st.markdown("### Present")
        st.dataframe(present[["Name", "Surname", "Grade", "Barcode"]], use_container_width=True, hide_index=True)

        st.markdown("### Absent")
        st.dataframe(absent[["Name", "Surname", "Grade", "Barcode"]], use_container_width=True, hide_index=True)

        # Download today's attendance list
        today_export = df[["Name", "Surname", "Grade", "Barcode"]].copy()
        if date_col in df.columns:
            today_export["Present"] = df[date_col].apply(lambda x: "Yes" if str(x).strip() == "1" else "No")
        else:
            today_export["Present"] = "No"
        csv_bytes = today_export.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download Today Attendance (CSV)",
            data=csv_bytes,
            file_name=f"attendance_today_{date_col}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ---- (2) Grades
with tabs[2]:
    st.subheader("Grades")
    df = get_wide_sheet(DB_PATH)
    date_col, _, _, _ = today_labels()

    benchmark = st.number_input("Grade benchmark (learners per grade)", min_value=1, value=DEFAULT_GRADE_BENCHMARK)

    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        if "Grade" not in df.columns:
            df["Grade"] = ""

        grades = sorted([g for g in df["Grade"].astype(str).unique().tolist() if g.strip() != ""])
        if not grades:
            st.warning("No grades found. Please add Grade values in Manage tab.")
        else:
            rows = []
            for g in grades:
                gdf = df[df["Grade"].astype(str) == str(g)]
                present, _ = get_present_absent(df, date_col, grade=g)
                total = len(gdf)
                pres = len(present)
                pct_total = (pres / total * 100) if total else 0
                pct_bench = (pres / benchmark * 100) if benchmark else 0
                rows.append({
                    "Grade": g,
                    "Learners in DB": total,
                    "Present today": pres,
                    "Attendance % (of grade)": round(pct_total, 1),
                    "Attendance % (of benchmark)": round(pct_bench, 1),
                })

            summary = pd.DataFrame(rows).sort_values(by="Grade")
            st.dataframe(summary, use_container_width=True, hide_index=True)

            # Download per grade + full
            st.markdown("### Downloads")
            g_pick = st.selectbox("Choose grade to download", options=grades)

            gdf = df[df["Grade"].astype(str) == str(g_pick)].copy()
            out = gdf[["Name", "Surname", "Grade", "Barcode"]].copy()
            if date_col in gdf.columns:
                out["Present"] = gdf[date_col].apply(lambda x: "Yes" if str(x).strip() == "1" else "No")
            else:
                out["Present"] = "No"

            st.download_button(
                f"⬇️ Download Grade {g_pick} Today (CSV)",
                data=out.to_csv(index=False).encode("utf-8"),
                file_name=f"grade_{g_pick}_today_{date_col}.csv",
                mime="text/csv",
                use_container_width=True
            )

            st.download_button(
                "⬇️ Download Full Attendance Wide Sheet (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="attendance_wide_sheet.csv",
                mime="text/csv",
                use_container_width=True
            )

# ---- (3) History
with tabs[3]:
    st.subheader("History")
    df = get_wide_sheet(DB_PATH)
    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        date_cols = get_date_columns(df)
        if not date_cols:
            st.info("No attendance marks yet (no date columns). Scan learners first.")
        else:
            sel = st.selectbox("Select date", options=date_cols, index=len(date_cols) - 1)
            present, absent = get_present_absent(df, sel)

            st.markdown(f"### {sel} — Present ({len(present)})")
            st.dataframe(present[["Name", "Surname", "Grade", "Barcode"]], use_container_width=True, hide_index=True)

            st.markdown(f"### {sel} — Absent ({len(absent)})")
            st.dataframe(absent[["Name", "Surname", "Grade", "Barcode"]], use_container_width=True, hide_index=True)

# ---- (4) Tracking
with tabs[4]:
    st.subheader("Tracking")
    df = get_wide_sheet(DB_PATH)
    if df.empty:
        st.warning("No learners yet. Add learners in Manage tab.")
    else:
        track = compute_tracking(df)
        st.dataframe(track, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ Download Tracking (CSV)",
            data=track.to_csv(index=False).encode("utf-8"),
            file_name="tracking.csv",
            mime="text/csv",
            use_container_width=True
        )

# ---- (5) Manage
with tabs[5]:
    st.subheader("Manage Learners")

    # show learners
    learners = get_learners_df(DB_PATH).fillna("")
    st.dataframe(learners, use_container_width=True, hide_index=True)

    st.markdown("### Add / Update learner")
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Name")
    surname = c2.text_input("Surname")
    barcode = c3.text_input("Barcode")

    c4, c5, c6 = st.columns(3)
    grade = c4.text_input("Grade")
    area = c5.text_input("Area")
    dob = c6.text_input("Date Of Birth (optional)")

    if st.button("Save learner", use_container_width=True):
        df_new = learners.copy()
        new_row = pd.DataFrame([{
            "Name": name, "Surname": surname, "Barcode": barcode,
            "Grade": grade, "Area": area, "Date Of Birth": dob
        }])
        df_new = pd.concat([df_new, new_row], ignore_index=True)
        replace_learners_from_df(DB_PATH, df_new)
        st.success("Saved. Refreshing…")
        st.rerun()

    st.markdown("### Delete learner")
    del_code = st.text_input("Barcode to delete", key="del_barcode")
    if st.button("Delete", use_container_width=True):
        delete_learner_by_barcode(DB_PATH, del_code)
        st.success("Deleted. Refreshing…")
        st.rerun()

    st.markdown("### Upload learners CSV (replace all)")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            df_up = pd.read_csv(up).fillna("")
            replace_learners_from_df(DB_PATH, df_up)
            st.success("Uploaded and replaced learners. Refreshing…")
            st.rerun()
        except Exception as e:
            st.error(f"Upload error: {e}")
