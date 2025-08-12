# app.py — Streamlit attendance app (IN only, barcode as key)
# Tabs: Scan • Today • History • Tracking • Manage

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
import time

CSV_DEFAULT = "attendance_clean.csv"

# ---------- Utilities ----------
def today_col_label() -> str:
    now = datetime.now()
    day = str(int(now.strftime("%d")))  # no leading zero
    mon = now.strftime("%b")            # Jan, Feb, ...
    return f"{day}-{mon}"

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
    if "Barcode" not in df.columns: df.insert(1, "Barcode", "")
    if "Name" not in df.columns:    df["Name"] = ""
    if "Surname" not in df.columns: df["Surname"] = ""
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
    return (name + " " + surname).strip()

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

def mark_present(barcode: str, csv_path: Path) -> tuple[bool, str]:
    if not barcode.strip():
        return False, "Empty scan."
    if not csv_path.exists():
        return False, f"Cannot find {csv_path.name}."

    df = load_sheet(csv_path)
    today_col = ensure_today_column(df)

    matches = df.index[df["Barcode"].apply(_norm) == _norm(barcode)].tolist()
    if not matches:
        return False, ("Barcode not found in sheet. "
                       "Add this code to the 'Barcode' column for the correct learner (Manage tab).")

    updated_any = False
    msgs = []
    for i in matches:
        who = label_for_row(df.loc[i]) or f"[{df.at[i,'Barcode']}]"
        if str(df.at[i, today_col]).strip() == "1":
            msgs.append(f"ℹ️ {who} is already present for {today_col}.")
        else:
            df.at[i, today_col] = "1"
            updated_any = True
            msgs.append(f"✅ {who} marked PRESENT for {today_col}.")

    if updated_any:
        save_sheet(df, csv_path)
    return True, "\n".join(msgs)

def get_present_absent(df: pd.DataFrame, date_col: str, grade=None, area=None):
    if date_col not in df.columns:
        return df.iloc[0:0].copy(), df.copy()

    filt = pd.Series([True]*len(df))
    if grade and "Grade" in df.columns:
        filt &= df["Grade"].astype(str) == str(grade)
    if area and "Area" in df.columns:
        filt &= df["Area"].astype(str) == str(area)

    subset = df[filt].copy()
    present = subset[subset[date_col].astype(str) == "1"]
    absent  = subset[subset[date_col].astype(str) != "1"]
    return present, absent

def unique_sorted(series):
    vals = sorted([v for v in series.astype(str).unique() if v.strip() != "" and v != "nan"])
    return ["(All)"] + vals

# ---------- Tracking helpers ----------
def compute_tracking(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = get_date_columns(df)
    if not date_cols:
        return pd.DataFrame(columns=["Name","Surname","Barcode","Sessions","Present","Absent","Attendance %","Last present","Current streak","Longest streak"])

    present_mat = df[date_cols].applymap(lambda x: 1 if str(x).strip() == "1" else 0)

    sessions = len(date_cols)
    present_counts = present_mat.sum(axis=1)
    absent_counts = sessions - present_counts
    pct = (present_counts / sessions * 100).round(1)

    # Last present date
    last_present = []
    for _, row in present_mat.iterrows():
        idxs = [j for j, v in enumerate(row.tolist()) if v == 1]
        last_present.append(date_cols[max(idxs)] if idxs else "—")

    # Streaks
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
        "Name": df.get("Name",""),
        "Surname": df.get("Surname",""),
        "Barcode": df.get("Barcode",""),
        "Sessions": sessions,
        "Present": present_counts,
        "Absent": absent_counts,
        "Attendance %": pct,
        "Last present": last_present,
        "Current streak": current_streak,
        "Longest streak": longest_streak
    })
    return result.sort_values(by=["Attendance %","Name","Surname"], ascending=[False, True, True]).reset_index(drop=True)

# ---------- UI ----------
st.set_page_config(page_title="Tutor Class Attendance Register 2025", page_icon="✅", layout="wide")

st.markdown(
    """
    <style>
    .app-title {font-size: 30px; font-weight: 800; margin-bottom: 0.25rem;}
    .app-sub  {color: #666; margin-top: 0;}
    .stat-card {padding: 12px 16px; border: 1px solid #eee; border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True
)

left, right = st.columns([3,2])
with left:
    st.markdown('<div class="app-title">✅ Tutor Class Attendance Register 2025</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="app-sub">Today: <b>{today_col_label()}</b></p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Settings")
    csv_path_str = st.text_input("CSV file path", CSV_DEFAULT, key="path_input")
    csv_path = Path(csv_path_str).expanduser()
    st.caption("Tip: keep this CSV in a shared OneDrive/Drive folder for team use.")

tabs = st.tabs(["📷 Scan", "📅 Today", "📚 History", "📈 Tracking", "🛠 Manage"])

# ---------- Scan Tab ----------
with tabs[0]:
    st.subheader("Scan")
    scan = st.text_input("Focus here and scan…", value="", key="scan_box", label_visibility="collapsed")
    c1, c2 = st.columns([1,4])
    with c1:
        if st.button("Mark Present", use_container_width=True, key="scan_btn"):
            if scan:
                ok, msg = mark_present(scan, csv_path)
                st.success(msg) if ok else st.error(msg)
                st.session_state.scan_box = ""  # clear input
                st.experimental_rerun()
    with c2:
        st.caption("Scanners should send an **Enter/Return** after each scan (most do by default).")

# ---------- Today Tab ----------
with tabs[1]:
    st.subheader(f"Today's Attendance — {today_col_label()}")
    df = load_sheet(csv_path) if csv_path.exists() else pd.DataFrame()
    today_col = today_col_label()
    if not df.empty:
        ensure_today_column(df)

        fc1, fc2, _ = st.columns(3)
        with fc1:
            grade_sel = st.selectbox(
                "Filter by Grade",
                unique_sorted(df["Grade"]) if "Grade" in df.columns else ["(All)"],
                key="today_grade"
            )
        with fc2:
            area_sel = st.selectbox(
                "Filter by Area",
                unique_sorted(df["Area"]) if "Area" in df.columns else ["(All)"],
                key="today_area"
            )

        grade_val = None if grade_sel == "(All)" else grade_sel
        area_val = None if area_sel == "(All)" else area_sel

        present, absent = get_present_absent(df, today_col, grade_val, area_val)

        s1, s2, s3 = st.columns(3)
        with s1:
            st.markdown(f'<div class="stat-card"><b>Registered</b><br>{len(present)+len(absent)}</div>', unsafe_allow_html=True)
        with s2:
            st.markdown(f'<div class="stat-card"><b>Present</b><br>{len(present)}</div>', unsafe_allow_html=True)
        with s3:
            st.markdown(f'<div class="stat-card"><b>Absent</b><br>{len(absent)}</div>', unsafe_allow_html=True)

        st.write("")
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Present**")
            cols = [c for c in ["Name","Surname","Barcode",today_col,"Grade","Area"] if c in present.columns]
            st.dataframe(present[cols], use_container_width=True, height=360)
        with cB:
            st.markdown("**Absent**")
            cols = [c for c in ["Name","Surname","Barcode","Grade","Area"] if c in absent.columns]
            st.dataframe(absent[cols], use_container_width=True, height=360)

        exp1, exp2 = st.columns(2)
        if not present.empty:
            exp1.download_button(
                "Download today's PRESENT (CSV)",
                data=present.to_csv(index=False).encode("utf-8"),
                file_name=f"present_{today_col}.csv",
                mime="text/csv",
                use_container_width=True,
                key="today_dl_present"
            )
        if not absent.empty:
            exp2.download_button(
                "Download today's ABSENT (CSV)",
                data=absent.to_csv(index=False).encode("utf-8"),
                file_name=f"absent_{today_col}.csv",
                mime="text/csv",
                use_container_width=True,
                key="today_dl_absent"
            )
    else:
        st.info("CSV not found yet. Set the path in the sidebar.")

# ---------- History Tab ----------
with tabs[2]:
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
            cols = [c for c in ["Name","Surname","Barcode",date_sel,"Grade","Area"] if c in df.columns]
            st.dataframe(df[cols].sort_values(by=["Name","Surname"]), use_container_width=True, height=420)
            st.download_button(
                "Download this date (CSV)",
                data=df[[c for c in ["Name","Surname","Barcode",date_sel,"Grade","Area"] if c in df.columns]].to_csv(index=False).encode("utf-8"),
                file_name=f"attendance_{date_sel}.csv",
                mime="text/csv",
                use_container_width=True,
                key="history_dl"
            )

# ---------- Tracking Tab ----------
with tabs[3]:
    st.subheader("Tracking (per student)")
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
                subset = subset[
                    subset.apply(lambda r: q in str(r.get("Name","")).lower()
                                          or q in str(r.get("Surname","")).lower()
                                          or q in str(r.get("Barcode","")).lower(), axis=1)
                ]

            metrics = compute_tracking(subset) if len(subset) else pd.DataFrame()
            st.write(f"Total learners: **{len(metrics)}**  |  Sessions counted: **{len(date_cols)}**")
            st.dataframe(metrics, use_container_width=True, height=480)

            if not metrics.empty:
                st.download_button(
                    "Download tracking report (CSV)",
                    data=metrics.to_csv(index=False).encode("utf-8"),
                    file_name="attendance_tracking_report.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="track_dl"
                )

# ---------- Manage Tab ----------
with tabs[4]:
    st.subheader("Manage Learners / Barcodes")
    if not csv_path.exists():
        st.info("CSV not found.")
    else:
        df = load_sheet(csv_path)

        q = st.text_input("Search by name or barcode", key="manage_search")
        if q:
            ql = q.lower().strip()
            hits = df[
                df.apply(lambda r:
                         ql in str(r.get("Name","")).lower()
                         or ql in str(r.get("Surname","")).lower()
                         or ql in str(r.get("Barcode","")).lower(), axis=1)
            ]
        else:
            hits = df

        st.dataframe(
            hits[["Name","Surname","Barcode","Grade","Area"] if "Grade" in df.columns and "Area" in df.columns else ["Name","Surname","Barcode"]],
            use_container_width=True, height=300
        )

        st.markdown("---")
        st.markdown("**Assign / Update a Barcode**")
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
                st.success("Saved. (Tip: in Excel, set Barcode column to Text to keep leading zeros.)")
                st.experimental_rerun()

        st.markdown("---")
        st.markdown("**Create a new date column manually (optional)**")
        new_date = st.text_input("New date label (e.g., 19-Aug)", key="manage_newdate")
        if st.button("Add date column", key="manage_adddate"):
            if new_date.strip():
                ensure_date_column(df, new_date.strip())
                save_sheet(df, csv_path)
                st.success(f"Added column {new_date.strip()}.")
                st.experimental_rerun()
