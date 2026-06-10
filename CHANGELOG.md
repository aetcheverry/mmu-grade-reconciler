# Changelog

All notable changes to this project will be documented here.

## [0.2.0] — 2026

### Added
- Reset button to clear all uploaded files and results in one click

### Fixed
- Three-way comparison now correctly reports grade mismatches for students
  missing from one source (e.g. absent from Moodle but present in both
  Power BI and Excel — their Power BI vs Excel mismatch is now shown)

---

## [0.1.0] — 2026

### Added
- Initial release
- Auto-detection of Power BI, Excel, and Moodle (.ods) file formats
- Two-way comparison: Power BI vs Excel or Power BI vs Moodle
- Three-way comparison: Power BI vs Excel vs Moodle
- Grade mismatch table with colour-coded rows
- Missing students table (separate from grade mismatches)
- OneDrive file-locking workaround (reads files into memory)
- Conda environment definition (`environment.yml`)
