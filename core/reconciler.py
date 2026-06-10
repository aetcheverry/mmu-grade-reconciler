import pandas as pd
from dataclasses import dataclass, field

FLAG_GRADE_MISMATCH = "GRADE MISMATCH"
FLAG_MISSING_PREFIX = "MISSING IN"


@dataclass
class ReconcileResult:
    mismatches: pd.DataFrame        # grade mismatches only (students present in both)
    missing_students: pd.DataFrame  # students absent from one or more sources
    total_compared: int
    total_missing_powerbi: int
    total_missing_other: int
    total_grade_mismatches: int
    label_powerbi: str
    label_other: str
    assessment_ids: list[str] = field(default_factory=list)
    _skipped_assessments: list[str] = field(default_factory=list)

    @property
    def has_discrepancies(self) -> bool:
        return not self.mismatches.empty

    @property
    def has_missing(self) -> bool:
        return not self.missing_students.empty

    @property
    def summary(self) -> str:
        parts = []
        if self.total_grade_mismatches:
            parts.append(f"{self.total_grade_mismatches} grade mismatch(es)")
        if self.total_missing_other:
            parts.append(f"{self.total_missing_other} student(s) missing "
                         f"in {self.label_other}")
        if self.total_missing_powerbi:
            parts.append(f"{self.total_missing_powerbi} student(s) missing "
                         f"in {self.label_powerbi}")
        if not parts:
            return (f"✅  All grades match and all students are present in "
                    f"both {self.label_powerbi} and {self.label_other}.")
        return "⚠️  " + ", ".join(parts) + "."


# ══════════════════════════════════════════════════════════════════════════════
# TWO-WAY RECONCILIATION
# ══════════════════════════════════════════════════════════════════════════════

def reconcile(parse_powerbi, parse_other,
              label_powerbi: str, label_other: str) -> ReconcileResult:
    """
    Compare Power BI ParseResult against one other source (Excel or Moodle).

    Grade mismatches  → mismatches DataFrame
    Missing students  → missing_students DataFrame

    mismatches columns:
        MMU ID | Student Name | Assessment | <pb> Grade | <other> Grade | Discrepancy

    missing_students columns:
        MMU ID | Student Name | Missing In
    """
    df_pb  = parse_powerbi.df.copy()
    df_oth = parse_other.df.copy()

    pb_aids     = parse_powerbi.assessment_ids
    oth_aids    = set(parse_other.assessment_ids)
    valid_ids   = [aid for aid in pb_aids if aid in oth_aids]
    skipped_ids = [aid for aid in pb_aids if aid not in oth_aids]

    col_pb  = f"{label_powerbi} Grade"
    col_oth = f"{label_other} Grade"

    if "student_name" not in df_oth.columns:
        df_oth["student_name"] = "—"

    merged = df_pb[["student_id", "student_name"] + valid_ids].merge(
        df_oth[["student_id", "student_name"] + valid_ids],
        on="student_id",
        how="outer",
        suffixes=("_pb", "_oth"),
        indicator=True,
    )

    mismatch_rows = []
    missing_rows  = []
    total_missing_pb  = 0
    total_missing_oth = 0
    total_mismatches  = 0

    for _, row in merged.iterrows():
        sid        = row["student_id"]
        merge_side = row["_merge"]
        name       = _coalesce(row.get("student_name_pb"),
                               row.get("student_name_oth"),
                               row.get("student_name"))

        if merge_side == "left_only":
            total_missing_oth += 1
            missing_rows.append({
                "MMU ID":       sid,
                "Student Name": name,
                "Missing In":   label_other,
            })

        elif merge_side == "right_only":
            total_missing_pb += 1
            missing_rows.append({
                "MMU ID":       sid,
                "Student Name": name,
                "Missing In":   label_powerbi,
            })

        else:
            for aid in valid_ids:
                grade_pb  = _coalesce(row.get(f"{aid}_pb"))
                grade_oth = _coalesce(row.get(f"{aid}_oth"))
                if _grades_differ(grade_pb, grade_oth):
                    total_mismatches += 1
                    mismatch_rows.append({
                        "MMU ID":       sid,
                        "Student Name": name,
                        "Assessment":   aid,
                        col_pb:         grade_pb,
                        col_oth:        grade_oth,
                        "Discrepancy":  FLAG_GRADE_MISMATCH,
                    })

    mismatch_cols = ["MMU ID", "Student Name", "Assessment",
                     col_pb, col_oth, "Discrepancy"]
    missing_cols  = ["MMU ID", "Student Name", "Missing In"]

    mismatches       = (pd.DataFrame(mismatch_rows) if mismatch_rows
                        else pd.DataFrame(columns=mismatch_cols))
    missing_students = (pd.DataFrame(missing_rows) if missing_rows
                        else pd.DataFrame(columns=missing_cols))

    return ReconcileResult(
        mismatches=mismatches,
        missing_students=missing_students,
        total_compared=int((merged["_merge"] == "both").sum()),
        total_missing_powerbi=total_missing_pb,
        total_missing_other=total_missing_oth,
        total_grade_mismatches=total_mismatches,
        label_powerbi=label_powerbi,
        label_other=label_other,
        assessment_ids=valid_ids,
        _skipped_assessments=skipped_ids,
    )


# ══════════════════════════════════════════════════════════════════════════════
# THREE-WAY RECONCILIATION
# ══════════════════════════════════════════════════════════════════════════════

def reconcile_three(parse_powerbi, parse_a, parse_b,
                    label_pb: str, label_a: str, label_b: str) -> ReconcileResult:
    """
    Three-way comparison: Power BI vs two other sources (e.g. Excel + Moodle).

    Key behaviour:
    - A student missing from one source is reported in the missing table.
    - Grade mismatches are reported for ALL students present in at least
      Power BI + one other source — a student absent from source B is still
      compared between Power BI and source A.

    mismatches columns:
        MMU ID | Student Name | Assessment |
        <pb> Grade | <a> Grade | <b> Grade | Discrepancy

    missing_students columns:
        MMU ID | Student Name | Missing In
    """
    df_pb = parse_powerbi.df.copy()
    df_a  = parse_a.df.copy()
    df_b  = parse_b.df.copy()

    for df in (df_a, df_b):
        if "student_name" not in df.columns:
            df["student_name"] = "—"

    pb_aids   = parse_powerbi.assessment_ids
    a_aids    = set(parse_a.assessment_ids)
    b_aids    = set(parse_b.assessment_ids)

    # Assessments comparable across all three
    valid_ids = [aid for aid in pb_aids if aid in a_aids or aid in b_aids]

    col_pb = f"{label_pb} Grade"
    col_a  = f"{label_a} Grade"
    col_b  = f"{label_b} Grade"

    # Build per-student lookup dictionaries for fast access
    pb_ids = set(df_pb["student_id"])
    a_ids  = set(df_a["student_id"])
    b_ids  = set(df_b["student_id"])
    all_ids = pb_ids | a_ids | b_ids

    pb_idx = df_pb.set_index("student_id")
    a_idx  = df_a.set_index("student_id")
    b_idx  = df_b.set_index("student_id")

    mismatch_rows = []
    missing_rows  = []
    total_mismatches  = 0
    total_missing_pb  = 0
    total_missing_oth = 0

    for sid in sorted(all_ids):
        in_pb = sid in pb_ids
        in_a  = sid in a_ids
        in_b  = sid in b_ids

        # Resolve name from whichever source has it
        name = "—"
        for idx in (pb_idx, a_idx, b_idx):
            if sid in idx.index:
                n = _coalesce(idx.loc[sid, "student_name"]
                              if "student_name" in idx.columns else "—")
                if n != "—":
                    name = n
                    break

        # Record missing entries
        absent = []
        if not in_pb: absent.append(label_pb)
        if not in_a:  absent.append(label_a)
        if not in_b:  absent.append(label_b)

        if not in_pb:
            total_missing_pb += 1
        if not in_a or not in_b:
            total_missing_oth += 1

        if absent:
            missing_rows.append({
                "MMU ID":       sid,
                "Student Name": name,
                "Missing In":   ", ".join(absent),
            })

        # Grade comparison — run for any student in Power BI + at least one other
        # This ensures a student missing from Moodle is still compared between
        # Power BI and Excel, and vice versa.
        if not in_pb:
            continue   # can't compare grades without a Power BI reference

        pb_row = pb_idx.loc[sid]

        for aid in valid_ids:
            grade_pb = _get_grade(pb_row, aid)

            # Get grade from A if available, else "—"
            grade_a = _get_grade(a_idx.loc[sid], aid) if in_a else "—"

            # Get grade from B if available, else "—"
            grade_b = _get_grade(b_idx.loc[sid], aid) if in_b else "—"

            # Compare Power BI vs A (if A is present)
            pb_vs_a = _grades_differ(grade_pb, grade_a) if in_a else False
            # Compare Power BI vs B (if B is present)
            pb_vs_b = _grades_differ(grade_pb, grade_b) if in_b else False
            # Compare A vs B (only if both present)
            a_vs_b  = _grades_differ(grade_a, grade_b) if (in_a and in_b) else False

            if pb_vs_a or pb_vs_b or a_vs_b:
                total_mismatches += 1
                mismatch_rows.append({
                    "MMU ID":       sid,
                    "Student Name": name,
                    "Assessment":   aid,
                    col_pb:         grade_pb,
                    col_a:          grade_a,
                    col_b:          grade_b,
                    "Discrepancy":  FLAG_GRADE_MISMATCH,
                })

    mismatch_cols = ["MMU ID", "Student Name", "Assessment",
                     col_pb, col_a, col_b, "Discrepancy"]
    missing_cols  = ["MMU ID", "Student Name", "Missing In"]

    mismatches       = (pd.DataFrame(mismatch_rows) if mismatch_rows
                        else pd.DataFrame(columns=mismatch_cols))
    missing_students = (pd.DataFrame(missing_rows) if missing_rows
                        else pd.DataFrame(columns=missing_cols))

    return ReconcileResult(
        mismatches=mismatches,
        missing_students=missing_students,
        total_compared=len(pb_ids & a_ids & b_ids),
        total_missing_powerbi=total_missing_pb,
        total_missing_other=total_missing_oth,
        total_grade_mismatches=total_mismatches,
        label_powerbi=label_pb,
        label_other=f"{label_a} & {label_b}",
        assessment_ids=valid_ids,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_grade(row, aid: str) -> str:
    """Safely retrieve a grade value from an indexed row."""
    try:
        val = row[aid] if aid in row.index else "—"
    except Exception:
        val = "—"
    return _coalesce(val)


def _coalesce(*values) -> str:
    for v in values:
        if v is not None and str(v).strip().lower() not in ("nan", "none", "", "—", "-"):
            return str(v).strip()
    return "—"


def _grades_differ(a: str, b: str) -> bool:
    if a == "—" or b == "—":
        return False
    return a.strip().lower() != b.strip().lower()
