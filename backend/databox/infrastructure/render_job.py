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
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _mark_on(attrs: dict | None, name: str) -> bool:
    if not isinstance(attrs, dict) or name not in attrs:
        return False
    value = attrs[name]
    return value is not False and value is not None


def _safe_href(value: object) -> str | None:
    """Allow http, https, and mailto. Everything else is dropped before HTML is emitted."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in candidate):
        return None
    lowered = candidate.lower()
    if lowered.startswith(("https://", "http://")):
        host = candidate.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        if not host or "@" in host or "\\" in host or host.startswith("."):
            return None
        return candidate
    if lowered.startswith("mailto:"):
        address = candidate[7:]
        if not address or any(ch in address for ch in "<>\"'\\"):
            return None
        return candidate
    return None


def _href(attrs: dict | None) -> str | None:
    if not isinstance(attrs, dict):
        return None
    raw = attrs.get("link")
    if isinstance(raw, dict):
        return _safe_href(raw.get("href"))
    if isinstance(raw, str):
        return _safe_href(raw)
    return None


def _wrap_marks(text: str, attrs: dict | None) -> str:
    body = text
    if _mark_on(attrs, "code"):
        body = f"<code>{body}</code>"
    if _mark_on(attrs, "strike"):
        body = f"<s>{body}</s>"
    if _mark_on(attrs, "underline"):
        body = f"<u>{body}</u>"
    if _mark_on(attrs, "italic"):
        body = f"<em>{body}</em>"
    if _mark_on(attrs, "bold"):
        body = f"<strong>{body}</strong>"
    href = _href(attrs)
    if href:
        body = f'<a href="{_escape(href)}" rel="noopener noreferrer nofollow">{body}</a>'
    return body


def _inline_html(node) -> str:
    from pycrdt import XmlElement, XmlText

    if isinstance(node, XmlText):
        parts: list[str] = []
        for text, attrs in node.diff():
            if not isinstance(text, str) or not text:
                continue
            parts.append(_wrap_marks(_escape(text), attrs if isinstance(attrs, dict) else None))
        return "".join(parts)
    if isinstance(node, XmlElement):
        if (node.tag or "").lower() == "hardbreak":
            return "<br>"
        return "".join(_inline_html(child) for child in node.children)
    return ""


def _heading_tag(level: object) -> str:
    text = str(level if level is not None else "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if text in {"1", "2", "3"}:
        return f"h{text}"
    return "p"


def _block_html(node) -> str:
    """Map known TipTap nodes to tags. Any other node name becomes escaped text."""
    from pycrdt import XmlElement

    if not isinstance(node, XmlElement):
        return ""
    name = (node.tag or "").lower()
    if name == "heading":
        element = _heading_tag(node.attributes.get("level"))
        inner = "".join(_inline_html(child) for child in node.children)
        return f"<{element}>{inner}</{element}>"
    if name == "paragraph":
        inner = "".join(_inline_html(child) for child in node.children)
        return f"<p>{inner}</p>"
    if name == "codeblock":
        inner = "".join(_inline_html(child) for child in node.children)
        return f"<pre><code>{inner}</code></pre>"
    if name == "horizontalrule":
        return "<hr>"
    if name in {"blockquote", "bulletlist", "orderedlist", "listitem"}:
        tag = {"blockquote": "blockquote", "bulletlist": "ul", "orderedlist": "ol", "listitem": "li"}[name]
        inner = "".join(_block_html(child) for child in node.children)
        return f"<{tag}>{inner}</{tag}>"
    inner = "".join(_inline_html(child) for child in node.children)
    return f"<p>{inner}</p>" if inner else ""


def document_html(document) -> str:
    """Turn the collaborative fragment into HTML. Unknown nodes contribute text only."""
    from pycrdt import XmlFragment

    fragment = document.get("content", type=XmlFragment)
    body = "".join(_block_html(child) for child in fragment.children) or "<p></p>"
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
