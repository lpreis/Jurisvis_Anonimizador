from __future__ import annotations

from io import BytesIO


def extract_text(uploaded_file) -> str:
    if uploaded_file is None:
        return ""

    suffix = uploaded_file.name.rsplit(".", 1)[-1].lower()
    data = uploaded_file.getvalue()

    if suffix == "txt":
        return data.decode("utf-8", errors="replace")
    if suffix == "docx":
        return extract_docx(data)
    if suffix == "pdf":
        return extract_pdf(data)

    raise ValueError("Formato nao suportado. Usa TXT, DOCX ou PDF.")


def extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("Para ler DOCX instala: pip install python-docx") from exc

    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Para ler PDF instala: pip install pypdf") from exc

    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(page.strip() for page in pages if page.strip())
