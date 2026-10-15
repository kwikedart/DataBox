"""Bounded checks for untrusted PDF uploads. This does not render pages."""

from __future__ import annotations

import re

from databox.domain.exceptions import ValidationError

_PAGE = re.compile(br"/Type\s*/Page(?!s)")
_ACTIVE = (b"/JavaScript", b"/Launch", b"/EmbeddedFile")


def validate_pdf(data: bytes, *, max_bytes: int, max_pages: int) -> int:
    if max_bytes < 1 or max_pages < 1:
        raise ValidationError("Upload limits must be positive")
    if not data:
        raise ValidationError("PDF payload is empty")
    if len(data) > max_bytes:
        raise ValidationError("File exceeds maximum size", code="payload_too_large")
    if not data.startswith(b"%PDF-"):
        raise ValidationError("File is not a PDF", code="unsupported_media_type")
    tail = data[-4096:]
    if b"%%EOF" not in tail and b"%%EOF" not in data:
        raise ValidationError("PDF structure is incomplete", code="unsupported_media_type")
    for marker in _ACTIVE:
        if marker in data:
            raise ValidationError("PDF contains disallowed active content", code="unsupported_media_type")
    page_count = len(_PAGE.findall(data))
    if page_count > max_pages:
        raise ValidationError("PDF exceeds the page limit", code="payload_too_large")
    return page_count
