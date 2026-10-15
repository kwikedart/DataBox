"""Actor and object-key values owned by this project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from databox.domain.exceptions import ValidationError


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    user_id: UUID
    organization_id: UUID
    role: OrganizationRole
    external_subject: str | None = None

    def __post_init__(self) -> None:
        if self.external_subject is not None and not self.external_subject.strip():
            raise ValidationError("External subject cannot be blank")


@dataclass(frozen=True, slots=True)
class ObjectKey:
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        segments = value.split("/")
        if (
            not value
            or len(value) > 1024
            or "\x00" in value
            or "\\" in value
            or value.startswith("/")
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValidationError("Invalid object key")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value
