"""
parser.py — auto-detect and parse the three spreadsheet formats.

detect_source_type()   → "powerbi" | "moodle" | "excel"
parse_powerbi_sheet()  → ParseResult (wide: student_id | name | 1CWK40 | ...)
parse_moodle_sheet()   → ParseResult (wide: student_id | name | 1CWK40 | ...)
parse_excel_sheet()    → ParseResult (wide: student_id | name | 1CWK40 | ...)
"""

import re
import pandas as pd
from dataclasses import dataclass
from core.loader import LoadResult, MMU_EMAIL_RE, MMU_ID_RE, detect_header_row

# Matches assessment IDs like 1CWK40, 2EXAM60, 1CWK20, 2CWK80
ASSESSMENT_ID_RE = re.compile(r'\d[A-Z]{2,6}\d{2,3}')

# Moodle column header pattern:
#   "Coursework: 1CWK40 - ..." or "Quiz: 1CWK40 - ..."
# We keep only "(Real)" columns and skip "(Reassessment)"
MOODLE_COL_RE = re.compile(
    r'(?:Coursework|Quiz|Assignment):\s*(\d[A-Z]{2,6}\d{2,3})',
    re.IGNORECASE,
)


@dataclass
class ParseResult:
    df: pd.DataFrame | None        # wide: student_id | student_name | <aid> ...
    assessment_ids: list[str]      # e.g. ['1CWK40', '2EXAM60']
    source_type: str               # "excel" | "powerbi" | "moodle"
    success: bool
    error: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_source_type(load_result: LoadResult) -> str:
    """
    Inspect the raw DataFrame and return one of:
      "powerbi"  — contains 'MMU ID', 'ASSESSMENT ID', 'GRADE' columns
      "moodle"   — row 0 contains 'Username' and Coursework/Quiz columns
      "excel"    — contains MMU email addresses (@stu.mmu.ac.uk) in data rows
    """
    if not load_result.success or load_result.df is None:
        return "unknown"

    df = load_result.df

    # Check for Power BI fixed headers anywhere in first 5 rows
    for i in range(min(5, len(df))):
        row_vals = [str(v).strip() for v in df.iloc[i]]
        if "MMU ID" in row_vals and "ASSESSMENT ID" in row_vals and "GRADE" in row_vals:
            return "powerbi"

    # Check for Moodle: row 0 has 'Username' and at least one Coursework/Quiz col
    if len(df) > 0:
        row0 = [str(v).strip() for v in df.iloc[0]]
        has_username = "Username" in row0
        has_coursework = any(MOODLE_COL_RE.search(v) for v in row0)
        if has_username and has_coursework:
            return "moodle"

    # Fall back to Excel (MMU email pattern in data)
    for i, row in df.iterrows():
        for val in row:
            if MMU_EMAIL_RE.search(str(val)):
                return "excel"

    return "excel"   # best guess if nothing else matched


# ══════════════════════════════════════════════════════════════════════════════
# PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def parse_powerbi_sheet(load_result: LoadResult) -> ParseResult:
    """
    Power BI Marks Transfer Report — long format.
    Header row detected by scanning for 'MMU ID'.
    Pivots to wide format: student_id | student_name | 1CWK40 | 2EXAM60 | ...
    """
    if not load_result.success:
        return ParseResult(df=None, assessment_ids=[], source_type="powerbi",
                           success=False, error=load_result.error)

    df = load_result.df

    header_row = _find_row_with_value(df, "MMU ID")
    if header_row is None:
        return ParseResult(df=None, assessment_ids=[], source_type="powerbi",
                           success=False,
                           error="Could not find 'MMU ID' column in Power BI file.")

    df.columns = [str(v).strip() for v in df.iloc[header_row]]
    df = df.iloc[header_row + 1:].copy()
    df.reset_index(drop=True, inplace=True)

    required = {"MMU ID", "ASSESSMENT ID", "GRADE"}
    missing  = required - set(df.columns)
    if missing:
        return ParseResult(df=None, assessment_ids=[], source_type="powerbi",
                           success=False,
                           error=f"Power BI file missing columns: {missing}")

    df["MMU ID"]        = df["MMU ID"].astype(str).str.strip()
    df["ASSESSMENT ID"] = df["ASSESSMENT ID"].astype(str).str.strip()
    df["GRADE"]         = df["GRADE"].astype(str).str.strip()
    df = df[df["MMU ID"].str.match(r'^\d{8}$')]

    has_name       = "STUDENT NAME" in df.columns
    assessment_ids = sorted(df["ASSESSMENT ID"].unique().tolist())

    wide: dict[str, dict] = {}
    for _, row in df.iterrows():
        sid = row["MMU ID"]
        if sid not in wide:
            wide[sid] = {"student_id": sid,
                         "student_name": str(row.get("STUDENT NAME", "—")).strip()
                         if has_name else "—"}
        aid   = row["ASSESSMENT ID"]
        grade = row["GRADE"]
        wide[sid][aid] = grade if grade not in ("nan", "", "-") else ""

    out = pd.DataFrame(list(wide.values()))
    for aid in assessment_ids:
        if aid not in out.columns:
            out[aid] = ""

    return ParseResult(df=out, assessment_ids=assessment_ids,
                       source_type="powerbi", success=True)


def parse_moodle_sheet(load_result: LoadResult) -> ParseResult:
    """
    Moodle gradebook export (.ods).
    Row 0 is the header. Columns of interest:
      - 'Username'  → student_id (8-digit extracted from email)
      - 'First name' + 'Last name' → student_name
      - 'Coursework: <AID> - ... (Real)' → grade  (skip Reassessment columns)
    """
    if not load_result.success:
        return ParseResult(df=None, assessment_ids=[], source_type="moodle",
                           success=False, error=load_result.error)

    df = load_result.df

    # Row 0 is the header
    df.columns = [str(v).strip() for v in df.iloc[0]]
    df = df.iloc[1:].copy()
    df.reset_index(drop=True, inplace=True)

    if "Username" not in df.columns:
        return ParseResult(df=None, assessment_ids=[], source_type="moodle",
                           success=False,
                           error="Could not find 'Username' column in Moodle file.")

    # Extract assessment columns: match Coursework/Quiz pattern, skip Reassessment
    assessment_col_map: dict[str, str] = {}   # assessment_id → original column name
    for col in df.columns:
        if "(Reassessment)" in col:
            continue
        m = MOODLE_COL_RE.search(col)
        if m and "(Real)" in col:
            aid = m.group(1).strip()
            assessment_col_map[aid] = col

    if not assessment_col_map:
        return ParseResult(df=None, assessment_ids=[], source_type="moodle",
                           success=False,
                           error="No assessment columns found in Moodle file "
                                 "(expected 'Coursework: <ID> - ... (Real)').")

    # Build output rows
    rows = []
    for _, row in df.iterrows():
        raw_id = str(row.get("Username", "")).strip()
        m = MMU_ID_RE.search(raw_id)
        if not m:
            continue
        sid = m.group(0)

        fname = str(row.get("First name", "")).strip()
        lname = str(row.get("Last name",  "")).strip()
        name  = f"{fname} {lname}".strip() or "—"

        entry = {"student_id": sid, "student_name": name}
        for aid, col in assessment_col_map.items():
            raw = str(row.get(col, "")).strip()
            entry[aid] = raw if raw not in ("nan", "", "-") else ""

        rows.append(entry)

    out = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["student_id", "student_name"] + list(assessment_col_map.keys()))

    return ParseResult(df=out, assessment_ids=list(assessment_col_map.keys()),
                       source_type="moodle", success=True)


def parse_excel_sheet(load_result: LoadResult) -> ParseResult:
    """
    Teacher's own Excel spreadsheet.
    Scans for the header row by finding MMU email addresses (@stu.mmu.ac.uk).
    Detects assessment ID columns (e.g. 1CWK40) from the rows above the data.
    """
    if not load_result.success:
        return ParseResult(df=None, assessment_ids=[], source_type="excel",
                           success=False, error=load_result.error)

    df = load_result.df

    data_start = detect_header_row(df, MMU_EMAIL_RE)
    if data_start is None:
        return ParseResult(df=None, assessment_ids=[], source_type="excel",
                           success=False,
                           error="Could not find MMU student IDs "
                                 "(expected format: 12345678@stu.mmu.ac.uk).")

    # Scan rows above data for assessment ID labels
    assessment_col_map: dict[str, int] = {}
    for row_idx in range(data_start - 1, -1, -1):
        for col_idx, val in enumerate(df.iloc[row_idx]):
            m = ASSESSMENT_ID_RE.fullmatch(str(val).strip())
            if m:
                assessment_col_map[m.group(0)] = col_idx
        if assessment_col_map:
            break

    if not assessment_col_map:
        return ParseResult(df=None, assessment_ids=[], source_type="excel",
                           success=False,
                           error="Could not find assessment ID columns "
                                 "(expected labels like 1CWK40, 2EXAM60).")

    id_col   = _find_id_col(df, data_start)
    if id_col is None:
        return ParseResult(df=None, assessment_ids=[], source_type="excel",
                           success=False,
                           error="Could not find the student ID column.")

    name_cols = _find_name_cols(df, data_start, id_col)

    rows = []
    for _, row in df.iloc[data_start:].iterrows():
        raw_id = str(row[id_col]).strip()
        m = MMU_ID_RE.search(raw_id)
        if not m:
            continue
        sid = m.group(0)

        name_parts = [str(row[c]).strip() for c in name_cols
                      if str(row[c]).strip() not in ("nan", "")]
        name = " ".join(name_parts) or "—"

        entry = {"student_id": sid, "student_name": name}
        for aid, col_idx in assessment_col_map.items():
            raw = str(row[col_idx]).strip()
            entry[aid] = raw if raw not in ("nan", "") else ""

        rows.append(entry)

    out = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["student_id", "student_name"] + list(assessment_col_map.keys()))

    return ParseResult(df=out, assessment_ids=list(assessment_col_map.keys()),
                       source_type="excel", success=True)


def auto_parse(load_result: LoadResult) -> ParseResult:
    """Detect source type and dispatch to the appropriate parser."""
    src = detect_source_type(load_result)
    if src == "powerbi":
        return parse_powerbi_sheet(load_result)
    if src == "moodle":
        return parse_moodle_sheet(load_result)
    return parse_excel_sheet(load_result)


# ── Private helpers ────────────────────────────────────────────────────────────

def _find_row_with_value(df: pd.DataFrame, value: str) -> int | None:
    for i, row in df.iterrows():
        if any(str(v).strip() == value for v in row):
            return i
    return None


def _find_id_col(df: pd.DataFrame, data_start: int) -> int | None:
    for row_idx in range(data_start - 1, -1, -1):
        for col_idx, val in enumerate(df.iloc[row_idx]):
            if str(val).strip().upper() == "MMU ID":
                return col_idx
    for col_idx, val in enumerate(df.iloc[data_start]):
        if MMU_EMAIL_RE.search(str(val)):
            return col_idx
    return None


def _find_name_cols(df: pd.DataFrame, data_start: int, id_col: int) -> list[int]:
    name_cols = []
    for row_idx in range(data_start - 1, -1, -1):
        for col_idx, val in enumerate(df.iloc[row_idx]):
            label = str(val).strip().upper()
            if label in ("FAMILY NAME", "NAME") and col_idx != id_col:
                name_cols.append((label, col_idx))
        if name_cols:
            break
    ordered = sorted(name_cols, key=lambda x: (x[0] != "FAMILY NAME", x[1]))
    return [c for _, c in ordered]
