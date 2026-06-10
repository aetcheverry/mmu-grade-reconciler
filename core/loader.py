import re
import pandas as pd
from dataclasses import dataclass
from io import BytesIO

MMU_EMAIL_RE = re.compile(r'\d{8}@stu\.mmu\.ac\.uk', re.IGNORECASE)
MMU_ID_RE    = re.compile(r'\b\d{8}\b')


@dataclass
class LoadResult:
    df: pd.DataFrame | None
    success: bool
    error: str | None = None
    sheet_names: list[str] | None = None
    file_type: str | None = None   # "excel", "powerbi", "moodle" — set by parser


def load_spreadsheet(uploaded_file, sheet_name: str | int = 0) -> LoadResult:
    """
    Read any uploaded spreadsheet (.xlsx, .xls, .ods) into a raw DataFrame
    with no header assumptions — all values as strings, row 0 = first sheet row.
    """
    if uploaded_file is None:
        return LoadResult(df=None, success=False, error="No file provided.")

    try:
        if isinstance(uploaded_file, (bytes,)):
            uploaded_file = BytesIO(uploaded_file)

        # Detect format by trying openpyxl first, then odf
        raw = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file
        if isinstance(raw, bytes):
            buf = BytesIO(raw)
        else:
            buf = raw

        # Try to determine engine
        engine = _detect_engine(buf)
        buf.seek(0)

        if engine == "odf":
            df = pd.read_excel(buf, engine="odf", header=None, dtype=str)
            sheet_names = ["Sheet1"]   # ODS via pandas doesn't expose sheet names easily
        else:
            xf          = pd.ExcelFile(buf, engine=engine)
            sheet_names = xf.sheet_names
            buf.seek(0)
            df = pd.read_excel(buf, engine=engine, sheet_name=sheet_name,
                               header=None, dtype=str)

        df.columns = range(len(df.columns))
        df.dropna(how="all", inplace=True)
        df.reset_index(drop=True, inplace=True)

        return LoadResult(df=df, success=True, sheet_names=sheet_names)

    except Exception as e:
        return LoadResult(df=None, success=False, error=str(e))


def _detect_engine(buf: BytesIO) -> str:
    """Sniff file magic bytes to choose the right pandas engine."""
    header = buf.read(8)
    buf.seek(0)
    # ODS: PK zip with mimetype 'application/vnd.oasis.opendocument'
    if header[:2] == b'PK':
        # Could be xlsx or ods — read the mimetype entry
        try:
            import zipfile
            with zipfile.ZipFile(BytesIO(buf.read())) as zf:
                buf.seek(0)
                if 'mimetype' in zf.namelist():
                    mt = zf.read('mimetype').decode()
                    if 'opendocument' in mt:
                        return 'odf'
            buf.seek(0)
            return 'openpyxl'
        except Exception:
            buf.seek(0)
            return 'openpyxl'
    # Legacy .xls
    if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return 'xlrd'
    return 'openpyxl'


def detect_header_row(df: pd.DataFrame, pattern: re.Pattern) -> int | None:
    """Return index of the first row containing a cell matching pattern."""
    for i, row in df.iterrows():
        for val in row:
            if pattern.search(str(val)):
                return i
    return None


def preview(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return df.head(n)
