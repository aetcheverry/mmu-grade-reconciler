# Grade Reconciler

A desktop tool for reconciling student grades across multiple sources — Power BI exports, personal Excel spreadsheets, and Moodle gradebooks. Automatically detects file formats, flags grade mismatches and missing students, and displays results in a clean local GUI.

Built with Python and Tkinter, designed for use at Manchester Metropolitan University.

---

## Features

- **Auto-detects file format** — Power BI export, Excel spreadsheet, or Moodle gradebook (.ods), no manual column mapping needed
- **Two-way or three-way comparison** — Power BI vs Excel, Power BI vs Moodle, or all three at once
- **Flags grade mismatches** — highlights every student/assessment combination where grades differ
- **Flags missing students** — separate table showing students present in one source but absent in another
- **Fully local** — runs entirely on your machine, no browser or internet connection required

---

## Supported File Formats

| Source | Format | Notes |
|--------|--------|-------|
| Power BI Marks Transfer Report | `.xlsx` | Long format — one row per student per assessment |
| Teacher Excel spreadsheet | `.xlsx` | Assessment IDs (e.g. `1CWK40`) auto-detected from column headers |
| Moodle gradebook export | `.ods` | `Coursework: <ID> ... (Real)` columns; Reassessment columns skipped |

---

## Requirements

- [Anaconda](https://www.anaconda.com/download) or Miniconda
- Windows, macOS, or Linux

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/aetcheverry/mmu-grade-reconciler.git
cd mmu-grade-reconciler
```

**2. Create the conda environment**

```bash
conda env create -f environment.yml
```

**3. Activate the environment**

```bash
conda activate grade-reconciler
```

**4. Install ODS support**

```bash
pip install odfpy
```

---

## Usage

With the environment active, run:

```bash
python app.py
```

The app opens a desktop window. Follow the three steps:

1. **Upload spreadsheets** — browse for your Power BI export (left), and one or two Excel/Moodle files (centre and right). The source type is detected automatically and shown as a badge.
2. **Run comparison** — click **Run comparison**. The button activates once the required files are loaded.
3. **Review results** — two tables are shown:
   - **Grade mismatches** — students present in both sources where the grade values differ
   - **Missing students** — students found in one source but not the other

---

## Project Structure

```
mmu-grade-reconciler/
├── app.py                  # Tkinter UI — main entry point
├── environment.yml         # Conda environment definition
├── core/
│   ├── loader.py           # File ingestion (.xlsx, .xls, .ods)
│   ├── parser.py           # Format auto-detection and per-source parsers
│   └── reconciler.py       # Join logic and mismatch detection
```

---

## Notes

- Files stored on OneDrive may be locked while syncing or open in Excel. Close the file first if you get a permission error.
- The app matches students by their 8-digit MMU ID. Email-format IDs are automatically stripped to the numeric part.
- Only assessments present in the Power BI export are compared. If an assessment ID appears in Power BI but not in your Excel/Moodle file, a warning is shown.

---

## Contributing

Contributions and suggestions are welcome. Please open an issue before submitting a pull request.

---

## Licence

MIT
