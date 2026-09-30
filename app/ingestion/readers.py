"""Turn an uploaded file into plain text, and report anything that looks wrong.

Pure code, no AI. Problems are returned, not raised, so the UI can show them
and the user can decide what to do (the brief: 'report extraction problems').
"""
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".txt", ".pdf", ".docx"}
MIN_CHARS = 200  # below this the source is almost certainly not a screenplay


@dataclass
class IngestResult:
    text: str = ""
    problems: list[str] = field(default_factory=list)


# Lines a screenplay PDF adds that are layout, not story: page numbers ("2." / "Page 2" / "- 2 -"),
# page-break markers ("(MORE)", "(CONTINUED)", "12 CONTINUED:") and scene transitions ("CUT TO:", "FADE IN:").
_PAGE_NO = re.compile(r"\s*(?:page\s+)?-?\s*\d{1,3}\.?\s*-?\s*", re.I)
_BREAK = re.compile(r"\s*(?:\(?(?:MORE|CONTINUED)\)?:?|\d+\s+CONTINUED:?)\s*")
_TRANSITION = re.compile(r"\s*(?:(?:SMASH |MATCH |JUMP )?CUT (?:TO|BACK TO)|DISSOLVE TO|FADE (?:IN|OUT|TO BLACK)|WIPE TO)\s*[.:]?\s*")


def _is_layout(line: str) -> bool:
    return bool(_PAGE_NO.fullmatch(line) or _BREAK.fullmatch(line) or _TRANSITION.fullmatch(line))


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    lines = [ln for ln in text.split("\n") if not _is_layout(ln)]
    text = "\n".join(ln.strip() for ln in lines)  # layout mode indents; the blank lines carry the structure
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_txt(data: bytes, problems: list[str]) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    problems.append("could not detect text encoding; decoded with replacement characters")
    return data.decode("utf-8", errors="replace")


def _page_text(page) -> str:
    """Layout mode keeps the vertical gaps that separate one speaker from the next. The default mode drops them,
    which collapses a whole conversation into one block: fine for reading, fatal for numbering dialogue lines."""
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:  # noqa: BLE001: some odd PDFs cannot be laid out; the plain mode still gets the words
        return page.extract_text() or ""


def _read_pdf(data: bytes, problems: list[str]) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:  # corrupt / encrypted
        problems.append(f"PDF could not be opened: {e}")
        return ""
    if reader.is_encrypted:
        problems.append("PDF is password protected")
        return ""
    pages = [_page_text(p) for p in reader.pages]
    empty = [i + 1 for i, t in enumerate(pages) if not t.strip()]
    if empty and len(empty) == len(pages):
        problems.append("PDF has no extractable text (probably scanned images); OCR is not supported")
    elif empty:
        problems.append(f"no text found on page(s) {empty}; those pages may be scanned images")
    return "\n".join(pages)


def _read_docx(data: bytes, problems: list[str]) -> str:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        problems.append(f"DOCX could not be opened: {e}")
        return ""
    return "\n".join(p.text for p in doc.paragraphs)


def read_document(data: bytes, filename: str) -> IngestResult:
    ext = Path(filename).suffix.lower()
    result = IngestResult()
    if ext not in SUPPORTED:
        result.problems.append(f"unsupported file type {ext or '(none)'}; use TXT, PDF or DOCX")
        return result
    if not data:
        result.problems.append("file is empty")
        return result

    reader = {".txt": _read_txt, ".pdf": _read_pdf, ".docx": _read_docx}[ext]
    result.text = _normalize(reader(data, result.problems))

    if not result.text:
        result.problems.append("no text could be extracted")
    elif len(result.text) < MIN_CHARS:
        result.problems.append(f"very short source ({len(result.text)} characters); is this the full screenplay?")
    return result


def read_pasted(text: str) -> IngestResult:
    """Text pasted straight into the app."""
    return read_document(text.encode("utf-8"), "pasted.txt")
