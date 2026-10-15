"""Domain exceptions with stable, transport-neutral error codes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    default_code = "domain_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = dict(details or {})


class ValidationError(DomainError):
    default_code = "validation_error"


class NotFoundError(DomainError):
    default_code = "not_found"


class AccessDenied(DomainError):
    default_code = "access_denied"


class ConflictError(DomainError):
    default_code = "conflict"
