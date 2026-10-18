"""Upload validation and bounded text extraction and chunking of PDF, Markdown and text files."""
import io
import re
from pathlib import PurePath

from pypdf import PdfReader

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 500_000
MAX_CHUNKS = 500
EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}


def validated_filename(filename, content):
    """The upload's base filename; raises when its format, size or name length is not accepted."""
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if PurePath(filename).suffix.lower() not in EXTENSIONS:
        raise ValueError("supported_formats_pdf_md_txt")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("file_size_must_be_between_1_byte_and_10_mb")
    if len(filename) > 255:
        raise ValueError("filename_too_long")
    return filename


def parse_chunks(filename, content):
    if PurePath(filename).suffix.lower() == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError("encrypted_or_too_many_pdf_pages")
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    else:
        pages = [(None, content.decode("utf-8-sig"))]
    if sum(len(text) for _, text in pages) > MAX_TEXT:
        raise ValueError("document_text_too_large")
    result = []
    for page, text in pages:
        text = text.replace("\x00", "").strip()
        section, pending = None, ""
        def flush():
            nonlocal pending
            if pending.strip():
                result.append({"text": pending.strip(), "page": page, "section": section})
            pending = ""
        # Keep paragraphs and headings together; only oversized paragraphs split.
        for paragraph in re.split(r"\n\s*\n", text):
            for segment in re.split(r"(?m)(?=^#{1,6} )", paragraph):
                segment = segment.strip()
                if not segment:
                    continue
                if segment.startswith("#"):
                    flush()
                    section = segment.splitlines()[0].lstrip("# ")[:200]
                if pending and len(pending) + len(segment) + 2 > 1600:
                    flush()
                while len(segment) > 1600:
                    flush()
                    boundary = segment.rfind(" ", 800, 1600)
                    boundary = boundary if boundary > 0 else 1600
                    result.append({"text": segment[:boundary], "page": page, "section": section})
                    segment = segment[max(0, boundary-150):].strip()
                pending = (pending + "\n\n" + segment).strip()
        flush()
        if len(result) > MAX_CHUNKS:
            raise ValueError("too_many_document_chunks")
    if not result:
        raise ValueError("no_extractable_text_ocr_not_supported")
    return result
