"""Rasterize a private PDF into WebP pages. Import this from the worker, not the API."""

from __future__ import annotations

from uuid import UUID

from databox.domain.exceptions import ValidationError


def _webp_bytes(png: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(png))
    output = BytesIO()
    image.save(output, format="WEBP", quality=80, method=4)
    return output.getvalue()


def rasterize_pdf(data: bytes, *, max_pages: int) -> list[bytes]:
    import fitz

    document = fitz.open(stream=data, filetype="pdf")
    try:
        if document.page_count > max_pages:
            raise ValidationError("PDF exceeds the page limit", code="payload_too_large")
        pages: list[bytes] = []
        for index in range(document.page_count):
            pixmap = document.load_page(index).get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pages.append(_webp_bytes(pixmap.tobytes("png")))
        return pages
    finally:
        document.close()


def _escape(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    return cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _marks(attrs: dict | None) -> tuple[bool, bool]:
    if not attrs:
        return False, False
    return "bold" in attrs, "italic" in attrs


def _inline_html(node) -> str:
    from pycrdt import XmlElement, XmlText

    if isinstance(node, XmlText):
        chunks = node.diff()
        parts: list[str] = []
        for text, attrs in chunks:
            if not isinstance(text, str) or not text:
                continue
            body = _escape(text)
            bold, italic = _marks(attrs if isinstance(attrs, dict) else None)
            if bold:
                body = f"<strong>{body}</strong>"
            if italic:
                body = f"<em>{body}</em>"
            parts.append(body)
        return "".join(parts)
    if isinstance(node, XmlElement):
        return "".join(_inline_html(child) for child in node.children)
    return ""


def document_html(document) -> str:
    """Turn the allowed collaborative fragment into HTML. Unknown nodes contribute text only."""
    from pycrdt import XmlElement, XmlFragment

    fragment = document.get("content", type=XmlFragment)
    blocks: list[str] = []
    for child in fragment.children:
        if not isinstance(child, XmlElement):
            continue
        inner = _inline_html(child)
        tag = (child.tag or "").lower()
        level = str(child.attributes.get("level") or "")
        if tag == "heading" and level in {"1", "1.0"}:
            blocks.append(f"<h1>{inner}</h1>")
        elif tag == "heading" and level in {"2", "2.0"}:
            blocks.append(f"<h2>{inner}</h2>")
        else:
            blocks.append(f"<p>{inner}</p>")
    body = "".join(blocks) or "<p></p>"
    return (
        "<html><body style=\"font-family: sans-serif; font-size: 16px; color: #1c2430;\">"
        f"{body}</body></html>"
    )


def render_note_webp(document) -> bytes:
    """Draw one page from the collaborative document. Called by the render worker."""
    import fitz

    html = document_html(document)
    pdf = fitz.open()
    try:
        page = pdf.new_page(width=612, height=792)
        box = page.rect + (36, 36, -36, -36)
        page.insert_htmlbox(box, html)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return _webp_bytes(pixmap.tobytes("png"))
    finally:
        pdf.close()


def _load_note(snapshot: bytes | None, updates: list[bytes]):
    from pycrdt import Doc

    document = Doc()
    if snapshot:
        document.apply_update(snapshot)
    for update in updates:
        document.apply_update(update)
    return document


async def render_stored_version(
    *,
    store,
    storage,
    organization_id: UUID,
    document_id: UUID,
    version_id: UUID,
    max_pages: int,
    rasterize=rasterize_pdf,
) -> int:
    version = await store.get_version(organization_id, version_id)
    if version is None or version.document_id != document_id:
        return 0
    document = await store.get_document(organization_id, document_id)
    if document is not None and document.mime_type == "text/plain":
        try:
            checkpoint = await store.get_checkpoint(document_id, version_id)
            updates = await store.list_updates(document_id, version_id)
            generation = len(updates)
            snapshot = None if checkpoint is None else checkpoint.snapshot
            tail = updates if checkpoint is None else updates[checkpoint.state_version :]
            note = _load_note(snapshot, tail)
            image = render_note_webp(note)
            name = "page-1.webp" if generation <= 0 else f"page-1-{generation}.webp"
            key = f"org/{organization_id}/documents/{document_id}/renders/{version_id}/{name}"
            await storage.put(key, image, "image/webp")
        except Exception:
            await store.set_render_status(organization_id, version_id, "failed")
            raise
        await store.set_render_status(organization_id, version_id, "ready")
        return 1
    try:
        pdf = await storage.get(version.object_key)
        pages = rasterize(pdf, max_pages=max_pages)
        for number, page in enumerate(pages, start=1):
            key = f"org/{organization_id}/documents/{document_id}/renders/{version_id}/page-{number}.webp"
            await storage.put(key, page, "image/webp")
    except Exception:
        await store.set_render_status(organization_id, version_id, "failed")
        raise
    await store.set_render_status(organization_id, version_id, "ready" if pages else "failed")
    return len(pages)
