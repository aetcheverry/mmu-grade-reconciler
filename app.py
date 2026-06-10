import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from io import BytesIO

from core.loader import load_spreadsheet, LoadResult
from core.parser import auto_parse, ParseResult
from core.reconciler import reconcile, reconcile_three, ReconcileResult

# ── Palette ────────────────────────────────────────────────────────────────────
C_BG       = "#f8f9fb"
C_PANEL    = "#ffffff"
C_BORDER   = "#e0e0e0"
C_NAVY     = "#1a237e"
C_NAVY_LT  = "#283593"
C_GREEN_BG = "#e8f5e9"
C_GREEN_FG = "#2e7d32"
C_AMBER_BG = "#fff8e1"
C_AMBER_FG = "#e65100"
C_RED_BG   = "#fce4ec"
C_RED_FG   = "#c62828"
C_MUTED    = "#9e9e9e"
C_TEXT     = "#212121"

FONT_BODY  = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_HEAD  = ("Segoe UI", 11, "bold")
FONT_LABEL = ("Segoe UI", 8, "bold")

SOURCE_LABELS = {
    "powerbi": "Power BI",
    "excel":   "Excel",
    "moodle":  "Moodle",
}
BADGE_STYLES = {
    "powerbi": ("#e3f2fd", "#1565c0"),
    "excel":   ("#e8f5e9", "#2e7d32"),
    "moodle":  ("#fff3e0", "#e65100"),
    "unknown": ("#f5f5f5", "#757575"),
}


# ══════════════════════════════════════════════════════════════════════════════
# REUSABLE WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class SectionLabel(tk.Label):
    def __init__(self, parent, text, **kw):
        super().__init__(parent, text=text.upper(),
                         font=FONT_LABEL, fg=C_MUTED, bg=C_BG, anchor="w", **kw)


class Card(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_PANEL,
                         highlightbackground=C_BORDER, highlightthickness=1,
                         padx=14, pady=10, **kw)


class PrimaryButton(tk.Button):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_NAVY, fg="white",
                         activebackground=C_NAVY_LT, activeforeground="white",
                         relief="flat", font=FONT_BOLD, cursor="hand2",
                         padx=16, pady=6, **kw)


class SecondaryButton(tk.Button):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_PANEL, fg=C_NAVY,
                         activebackground="#e8eaf6", relief="flat",
                         font=FONT_BODY, cursor="hand2",
                         highlightbackground=C_BORDER, highlightthickness=1,
                         padx=14, pady=5, **kw)


class Badge(tk.Label):
    def __init__(self, parent, source_type: str, **kw):
        bg, fg = BADGE_STYLES.get(source_type, BADGE_STYLES["unknown"])
        label  = SOURCE_LABELS.get(source_type, source_type.title())
        super().__init__(parent, text=label, bg=bg, fg=fg,
                         font=FONT_LABEL, padx=8, pady=2, **kw)


def _apply_treeview_style(style: ttk.Style):
    """Apply consistent Treeview styling. Called once; safe to call multiple times."""
    style.theme_use("clam")
    style.configure("Grades.Treeview",
                    background=C_PANEL, fieldbackground=C_PANEL,
                    foreground=C_TEXT, rowheight=28,
                    font=FONT_BODY, borderwidth=0)
    style.configure("Grades.Treeview.Heading",
                    background="#37474f", foreground="white",
                    font=FONT_BOLD, relief="flat", padding=(6, 4))
    style.map("Grades.Treeview.Heading",
              background=[("active", "#546e7a"), ("pressed", "#263238")],
              foreground=[("active", "white"),   ("pressed", "white")])
    style.map("Grades.Treeview",
              background=[("selected", "#bbdefb")],
              foreground=[("selected", C_TEXT)])

    style.configure("Missing.Treeview",
                    background=C_PANEL, fieldbackground=C_PANEL,
                    foreground=C_TEXT, rowheight=28,
                    font=FONT_BODY, borderwidth=0)
    style.configure("Missing.Treeview.Heading",
                    background="#4e342e", foreground="white",
                    font=FONT_BOLD, relief="flat", padding=(6, 4))
    style.map("Missing.Treeview.Heading",
              background=[("active", "#6d4c41"), ("pressed", "#3e2723")],
              foreground=[("active", "white"),   ("pressed", "white")])
    style.map("Missing.Treeview",
              background=[("selected", "#ffccbc")],
              foreground=[("selected", C_TEXT)])


def _make_treeview(parent: tk.Frame, df, tv_style: str,
                   col_widths: dict, row_tag_fn=None) -> ttk.Treeview:
    """Build a scrollable Treeview inside parent and return it."""
    cols = list(df.columns)
    vsb  = ttk.Scrollbar(parent, orient="vertical")
    hsb  = ttk.Scrollbar(parent, orient="horizontal")
    tree = ttk.Treeview(parent, columns=cols, show="headings",
                        style=tv_style,
                        yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    vsb.config(command=tree.yview)
    hsb.config(command=tree.xview)

    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=col_widths.get(c, 130), anchor="center", minwidth=70)

    for _, row in df.iterrows():
        tag = row_tag_fn(row) if row_tag_fn else ""
        tree.insert("", "end", values=[str(row[c]) for c in cols],
                    tags=(tag,) if tag else ())

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0,  column=1, sticky="ns")
    hsb.grid(row=1,  column=0, sticky="ew")
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    return tree


class ResultTable(tk.Frame):
    """Grade-mismatch table + separate missing-students table."""
    def __init__(self, parent, result: ReconcileResult, **kw):
        super().__init__(parent, bg=C_BG, **kw)
        _apply_treeview_style(ttk.Style())
        self._build(result)

    def _build(self, result: ReconcileResult):
        # ── Summary banner ─────────────────────────────────────────────────
        all_ok = not result.has_discrepancies and not result.has_missing
        if all_ok:
            tk.Label(self, text="✅  All grades match and all students are present.",
                     font=FONT_BOLD, bg=C_GREEN_BG, fg=C_GREEN_FG,
                     padx=12, pady=8, anchor="w").pack(fill="x", pady=(0, 6))
            return

        tk.Label(self, text=f"⚠️  {result.summary}",
                 font=FONT_BOLD, bg=C_AMBER_BG, fg=C_AMBER_FG,
                 padx=12, pady=8, anchor="w",
                 wraplength=900, justify="left").pack(fill="x", pady=(0, 8))

        # ── Grade mismatches ───────────────────────────────────────────────
        if result.has_discrepancies:
            tk.Label(self, text="Grade mismatches",
                     font=FONT_BOLD, fg=C_NAVY, bg=C_BG,
                     anchor="w").pack(fill="x", pady=(0, 2))

            frame_m = tk.Frame(self, bg=C_BG)
            frame_m.pack(fill="both", expand=True, pady=(0, 10))

            col_w = {"MMU ID": 100, "Student Name": 160,
                     "Assessment": 110, "Discrepancy": 190}
            tree = _make_treeview(frame_m, result.mismatches,
                                  "Grades.Treeview", col_w,
                                  row_tag_fn=lambda r: "mismatch")
            tree.tag_configure("mismatch",
                               background=C_AMBER_BG, foreground=C_AMBER_FG)

        # ── Missing students ───────────────────────────────────────────────
        if result.has_missing:
            tk.Label(self, text="Missing students",
                     font=FONT_BOLD, fg=C_NAVY, bg=C_BG,
                     anchor="w").pack(fill="x", pady=(0, 2))

            frame_s = tk.Frame(self, bg=C_BG)
            frame_s.pack(fill="both", expand=True)

            col_w = {"MMU ID": 100, "Student Name": 200, "Missing In": 200}
            tree = _make_treeview(frame_s, result.missing_students,
                                  "Missing.Treeview", col_w,
                                  row_tag_fn=lambda r: "missing")
            tree.tag_configure("missing",
                               background=C_RED_BG, foreground=C_RED_FG)


# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD SLOT WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class UploadSlot(tk.Frame):
    """
    A self-contained upload card. Shows file name and detected source type
    after a file is loaded. Calls on_loaded(slot) when a file is ready.
    """
    def __init__(self, parent, title: str, subtitle: str,
                 on_loaded, optional: bool = False, **kw):
        super().__init__(parent, bg=C_PANEL,
                         highlightbackground=C_BORDER, highlightthickness=1,
                         padx=14, pady=10, **kw)
        self.on_loaded   = on_loaded
        self.optional    = optional
        self.parse_result: ParseResult | None = None

        # Title row
        title_str = title + (" (optional)" if optional else "")
        tk.Label(self, text=title_str, font=FONT_HEAD, fg=C_NAVY,
                 bg=C_PANEL, anchor="w").pack(fill="x")
        tk.Label(self, text=subtitle, font=FONT_SMALL, fg=C_MUTED,
                 bg=C_PANEL, anchor="w").pack(fill="x", pady=(2, 8))

        # File name label
        self._name_var = tk.StringVar(value="No file selected")
        tk.Label(self, textvariable=self._name_var, font=FONT_SMALL,
                 fg=C_MUTED, bg=C_PANEL, anchor="w",
                 wraplength=260).pack(fill="x", pady=(0, 4))

        # Detected type badge (hidden until file loaded)
        self._badge_frame = tk.Frame(self, bg=C_PANEL)
        self._badge_frame.pack(anchor="w", pady=(0, 6))

        SecondaryButton(self, text="Browse…",
                        command=self._browse).pack(anchor="w")

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[("Spreadsheets", "*.xlsx *.xls *.ods"),
                       ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except PermissionError:
            messagebox.showerror(
                "Permission denied",
                f"Could not open:\n{path}\n\n"
                "Make sure the file is not open in another application "
                "and that OneDrive has finished syncing.",
            )
            return

        load_result = load_spreadsheet(BytesIO(raw))
        if not load_result.success:
            messagebox.showerror("Load error",
                                 f"Could not read file:\n{load_result.error}")
            return

        parse_result = auto_parse(load_result)

        fname = path.replace("\\", "/").split("/")[-1]
        self._name_var.set(fname)
        self._show_badge(parse_result)
        self.parse_result = parse_result
        self.on_loaded(self)

    def _show_badge(self, pr: ParseResult):
        for w in self._badge_frame.winfo_children():
            w.destroy()
        src = pr.source_type if pr.success else "unknown"
        Badge(self._badge_frame, src).pack(side="left", padx=(0, 8))
        if pr.success:
            aids = ", ".join(pr.assessment_ids) or "none"
            tk.Label(self._badge_frame,
                     text=f"{len(pr.df)} students · {aids}",
                     font=FONT_SMALL, fg=C_MUTED, bg=C_PANEL).pack(side="left")
        else:
            tk.Label(self._badge_frame, text=f"❌ {pr.error}",
                     font=FONT_SMALL, fg=C_RED_FG, bg=C_PANEL,
                     wraplength=220, justify="left").pack(side="left")

    def ready(self) -> bool:
        return self.parse_result is not None and self.parse_result.success


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class GradeReconcilerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Grade Reconciler")
        self.geometry("1020x800")
        self.minsize(860, 640)
        self.configure(bg=C_BG)
        self._results: list[ReconcileResult] = []
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._root_frame    = tk.Frame(canvas, bg=C_BG, padx=24, pady=18)
        self._canvas_window = canvas.create_window(
            (0, 0), window=self._root_frame, anchor="nw")

        self._root_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._canvas_window, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        self._build_header()
        self._build_upload_section()
        self._build_run_section()
        self._results_frame = tk.Frame(self._root_frame, bg=C_BG)
        self._results_frame.pack(fill="both", expand=True)

    def _build_header(self):
        hdr = tk.Frame(self._root_frame, bg=C_NAVY, padx=20, pady=14)
        hdr.pack(fill="x", pady=(0, 16))
        tk.Label(hdr, text="🎓  Grade Reconciler", font=FONT_TITLE,
                 fg="white", bg=C_NAVY).pack(anchor="w")
        tk.Label(hdr,
                 text="Upload your spreadsheets and instantly spot any grade mismatches.",
                 font=FONT_SMALL, fg="#b3bef5", bg=C_NAVY).pack(anchor="w")

    def _build_upload_section(self):
        SectionLabel(self._root_frame, "Step 1 — Upload spreadsheets").pack(
            fill="x", pady=(0, 4))

        row = tk.Frame(self._root_frame, bg=C_BG)
        row.pack(fill="x", pady=(0, 8))
        row.columnconfigure((0, 1, 2), weight=1, uniform="upload")

        self._slot_pb = UploadSlot(
            row,
            title="📘  Power BI Export",
            subtitle="Marks Transfer Report (.xlsx)",
            on_loaded=self._on_file_loaded,
        )
        self._slot_pb.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        self._slot_b = UploadSlot(
            row,
            title="📗  Excel or Moodle",
            subtitle="Your spreadsheet or Moodle export (.xlsx / .ods)",
            on_loaded=self._on_file_loaded,
        )
        self._slot_b.grid(row=0, column=1, padx=(0, 8), sticky="nsew")

        self._slot_c = UploadSlot(
            row,
            title="📙  Excel or Moodle",
            subtitle="Second spreadsheet or Moodle export (.xlsx / .ods)",
            on_loaded=self._on_file_loaded,
            optional=True,
        )
        self._slot_c.grid(row=0, column=2, sticky="nsew")

        tk.Label(self._root_frame,
                 text="The source type (Power BI / Excel / Moodle) is detected automatically.",
                 font=FONT_SMALL, fg=C_MUTED, bg=C_BG).pack(anchor="w", pady=(0, 8))

    def _build_run_section(self):
        SectionLabel(self._root_frame, "Step 2 — Compare").pack(
            fill="x", pady=(0, 4))
        self._run_btn = PrimaryButton(
            self._root_frame, text="🔍  Run comparison",
            command=self._run, state="disabled")
        self._run_btn.pack(fill="x", pady=(0, 12))

    # ── Slot callback ──────────────────────────────────────────────────────────

    def _on_file_loaded(self, slot: UploadSlot):
        """Called whenever any upload slot finishes loading a file."""
        # Enable Run if Power BI + at least one other slot are ready
        pb_ready    = self._slot_pb.ready()
        other_ready = self._slot_b.ready() or self._slot_c.ready()
        self._run_btn.config(
            state="normal" if (pb_ready and other_ready) else "disabled")

    # ── Run comparison ─────────────────────────────────────────────────────────

    def _run(self):
        pr_pb = self._slot_pb.parse_result
        pr_b  = self._slot_b.parse_result   if self._slot_b.ready()  else None
        pr_c  = self._slot_c.parse_result   if self._slot_c.ready()  else None

        if pr_pb is None:
            messagebox.showerror("Missing file", "Please load the Power BI export.")
            return
        if pr_b is None and pr_c is None:
            messagebox.showerror("Missing file",
                                 "Please load at least one Excel or Moodle file.")
            return

        # Validate that the Power BI slot actually contains Power BI data
        if pr_pb.source_type != "powerbi":
            messagebox.showwarning(
                "Unexpected file type",
                f"The left slot was detected as '{pr_pb.source_type}', "
                "not Power BI. Please check you've uploaded the right file.",
            )

        results: list[ReconcileResult] = []

        if pr_b is not None and pr_c is not None:
            # Three-way comparison
            label_b = SOURCE_LABELS.get(pr_b.source_type, "File 2")
            label_c = SOURCE_LABELS.get(pr_c.source_type, "File 3")
            results.append(reconcile_three(
                pr_pb, pr_b, pr_c, "Power BI", label_b, label_c))
        else:
            # Two-way comparison
            pr_oth   = pr_b if pr_b is not None else pr_c
            label_oth = SOURCE_LABELS.get(pr_oth.source_type, "Other")
            result = reconcile(pr_pb, pr_oth, "Power BI", label_oth)

            skipped = result._skipped_assessments
            if skipped:
                messagebox.showwarning(
                    "Assessment columns not found",
                    "These Power BI assessment IDs were not found in the "
                    f"other file and were skipped:\n\n{', '.join(skipped)}",
                )
            results.append(result)

        self._results = results
        self._show_results()

    # ── Results panel ──────────────────────────────────────────────────────────

    def _show_results(self):
        for w in self._results_frame.winfo_children():
            w.destroy()

        SectionLabel(self._results_frame, "Step 3 — Results").pack(
            fill="x", pady=(0, 4))

        for result in self._results:
            heading = f"Power BI  vs  {result.label_other}"
            tk.Label(self._results_frame, text=heading,
                     font=FONT_HEAD, fg=C_NAVY, bg=C_BG,
                     anchor="w").pack(fill="x", pady=(4, 2))

            card = Card(self._results_frame)
            card.pack(fill="x", pady=(0, 14))
            ResultTable(card, result).pack(fill="both", expand=True)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = GradeReconcilerApp()
    app.mainloop()
