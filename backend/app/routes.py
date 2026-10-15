"""DataBox HTTP and WebSocket delivery. Authorization stays in the application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.deps import get_actor, get_databox_application, get_optional_actor
from databox.application.service import DataboxApplication
from databox.domain.exceptions import ConflictError, DomainError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1", tags=["databox"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


class ShareRequest(BaseModel):
    permission: str = "viewer"
    expires_at: datetime


class LabelRequest(BaseModel):
    audience_labels: list[str] = Field(default_factory=list, max_length=32)
    restricted_labels: list[str] = Field(default_factory=list, max_length=32)


class MembershipLabelRequest(BaseModel):
    user_id: UUID
    labels: list[str] = Field(default_factory=list, max_length=32)


class PermissionRequest(BaseModel):
    user_id: UUID
    role: str


class LinkRequest(BaseModel):
    target_document_id: UUID
    label: str | None = None
    cascade_depth: int = 1


class ViewTokenRequest(BaseModel):
    share_token: str | None = None
    parent_token: str | None = None


class RestoreRequest(BaseModel):
    expected_version_id: UUID | None = None


class SaveVersionRequest(BaseModel):
    expected_version_id: UUID


class ShareLifetimeRequest(BaseModel):
    version_id: UUID
    permission: str
    ttl_seconds: int = Field(ge=300, le=7 * 24 * 3600)


class TextDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class VisibilityRequest(BaseModel):
    visibility: str


class AccessRequestBody(BaseModel):
    role: str


class AccessDecisionRequest(BaseModel):
    approve: bool


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, DomainError) and exc.code == "rate_limited":
        return HTTPException(status_code=429, detail="Too many requests")
    if isinstance(exc, DomainError) and exc.code == "payload_too_large":
        return HTTPException(status_code=413, detail="File exceeds maximum size")
    if isinstance(exc, DomainError) and exc.code == "unsupported_media_type":
        return HTTPException(status_code=415, detail="File is not a supported PDF")
    if isinstance(exc, DomainError) and exc.code == "page_not_ready":
        return HTTPException(status_code=503, detail="Page is not ready")
    if isinstance(exc, ValidationError) and str(exc) == "Access token is not valid":
        return HTTPException(status_code=401, detail="Access token is not valid")
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail="Document version changed")
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DomainError):
        return HTTPException(status_code=503, detail="Document service is unavailable")
    return HTTPException(status_code=503, detail="Document service is unavailable")


def _document_payload(document, *, can_open: bool = True, pending_request: str | None = None) -> dict:
    return {
        "documentId": str(document.id),
        "title": document.title,
        "status": document.status,
        "caseId": str(document.case_id) if document.case_id else None,
        "currentVersionId": str(document.current_version_id) if document.current_version_id else None,
        "policyEpoch": document.policy_epoch,
        "audienceLabels": list(document.audience_labels),
        "restrictedLabels": list(document.restricted_labels),
        "mimeType": document.mime_type,
        "visibility": document.visibility,
        "createdBy": str(document.created_by),
        "canOpen": can_open,
        "pendingRequest": pending_request,
    }


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationError("File exceeds maximum size", code="payload_too_large")
    return data


@router.post("/documents", status_code=201)
async def create_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    case_id: UUID | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        content = await _read_limited(file, application.settings.max_upload_bytes)
        document = await application.create_document(
            actor=actor,
            title=title,
            content=content,
            case_id=case_id,
            idempotency_key=idempotency_key,
        )
    except (DomainError, ValidationError) as exc:
        raise _http(exc) from exc
    return _document_payload(document)


@router.post("/documents/text", status_code=201)
async def create_text_document(
    payload: TextDocumentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        document = await application.create_text_document(
            actor=actor,
            title=payload.title,
            idempotency_key=idempotency_key,
        )
    except (DomainError, ValidationError) as exc:
        raise _http(exc) from exc
    return _document_payload(document)


@router.get("/documents")
async def list_documents(
    case_id: UUID | None = None,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        rows = await application.list_documents(actor=actor, case_id=case_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "documents": [
            _document_payload(row.document, can_open=row.can_open, pending_request=row.pending_role)
            for row in rows
        ]
    }


@router.get("/documents/{document_id}")
async def get_document(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        listing = await application.inspect_document(
            actor=actor,
            document_id=document_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return _document_payload(listing.document, can_open=listing.can_open, pending_request=listing.pending_role)


@router.post("/documents/{document_id}/versions", status_code=201)
async def add_version(
    document_id: UUID,
    file: UploadFile = File(...),
    expected_version_id: UUID | None = Form(default=None),
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        content = await _read_limited(file, application.settings.max_upload_bytes)
        version = await application.add_version(
            actor=actor,
            document_id=document_id,
            content=content,
            expected_version_id=expected_version_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"versionId": str(version.id), "versionNumber": version.version_number}


@router.get("/documents/{document_id}/versions")
async def list_versions(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        versions = await application.list_versions(
            actor=actor,
            document_id=document_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "documentId": str(document_id),
        "versions": [
            {
                "id": str(version.id),
                "versionNumber": version.version_number,
                "createdAt": version.created_at.isoformat() if version.created_at else None,
                "sourceVersionId": str(version.source_version_id) if version.source_version_id else None,
            }
            for version in versions
        ],
    }


@router.get("/documents/{document_id}/shares")
async def list_version_shares(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        links = await application.list_version_shares(actor=actor, document_id=document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "links": [
            {
                "shareId": str(link.share_id),
                "versionId": str(link.version_id),
                "permission": link.permission,
                "token": link.url_token,
                "expiresAt": link.expires_at.isoformat(),
                "current": link.current,
            }
            for link in links
        ]
    }


@router.post("/documents/{document_id}/save")
async def save_text_version(
    document_id: UUID,
    payload: SaveVersionRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        document = await application.save_text_version(
            actor=actor,
            document_id=document_id,
            expected_version_id=payload.expected_version_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return _document_payload(document)


@router.post("/documents/{document_id}/versions/{version_id}/restore", status_code=201)
async def restore_version(
    document_id: UUID,
    version_id: UUID,
    payload: RestoreRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        version = await application.restore_version(
            actor=actor,
            document_id=document_id,
            version_id=version_id,
            expected_version_id=payload.expected_version_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"versionId": str(version.id), "versionNumber": version.version_number, "sourceVersionId": str(version.source_version_id)}


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        version, content = await application.download(
            actor=actor,
            document_id=document_id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{version.id}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/documents/{document_id}/view-token")
async def issue_view_token(
    document_id: UUID,
    payload: ViewTokenRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        token = await application.issue_view_token(
            actor=actor,
            document_id=document_id,
            share_token=payload.share_token,
            parent_token=payload.parent_token,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"token": token, "tokenType": "Bearer"}


@router.get("/documents/{document_id}/pages/{page}")
async def document_page(
    document_id: UUID,
    page: int,
    request: Request,
    application: DataboxApplication = Depends(get_databox_application),
):
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Access token is not valid")
    token = header.removeprefix("Bearer ").strip()
    try:
        grant = await application.authorize_page(token=token, document_id=document_id, page=page)
        first, chunks = await application.open_rendered_page(grant)
    except HTTPException:
        raise
    except DomainError as exc:
        raise _http(exc) from exc

    async def body():
        try:
            yield first
            async for chunk in chunks:
                yield chunk
        finally:
            await chunks.aclose()

    return StreamingResponse(
        body(),
        media_type="image/webp",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/documents/{document_id}/share-links", status_code=201)
async def create_share_link(
    document_id: UUID,
    payload: ShareRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        created = await application.create_share_link(
            actor=actor,
            document_id=document_id,
            permission=payload.permission,
            expires_at=payload.expires_at,
            idempotency_key=idempotency_key,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "shareLinkId": str(created.share_id),
        "token": created.url_token,
        "permission": created.permission,
        "expiresAt": created.expires_at.isoformat(),
    }


@router.delete("/share-links/{share_id}", status_code=204)
async def revoke_share_link(
    share_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        await application.revoke_share_link(actor=actor, share_id=share_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.post("/documents/{document_id}/shares/lifetime")
async def set_share_lifetime(
    document_id: UUID,
    payload: ShareLifetimeRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        link = await application.set_share_lifetime(
            actor=actor,
            document_id=document_id,
            version_id=payload.version_id,
            permission=payload.permission,
            ttl_seconds=payload.ttl_seconds,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "shareId": str(link.share_id),
        "versionId": str(link.version_id),
        "permission": link.permission,
        "token": link.url_token,
        "expiresAt": link.expires_at.isoformat(),
        "current": link.current,
    }


@router.get("/share/{token}")
async def resolve_share(
    token: str,
    request: Request,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    caller = request.client.host if request.client else "unknown"
    try:
        link = await application.resolve_share(actor=actor, token=token, caller_key=caller)
        document = await application.store.get_document(link.organization_id, link.document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    if document is None or document.status != "active":
        raise HTTPException(status_code=404, detail="Share link not found")
    return {
        "shareLinkId": str(link.id),
        "documentId": str(link.document_id),
        "permission": link.permission,
        "expiresAt": link.expires_at.isoformat(),
        "mimeType": document.mime_type,
        "title": document.title,
    }


@router.post("/share/{token}/view-token")
async def share_view_token(
    token: str,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        view_token = await application.issue_view_token(
            actor=actor,
            share_token=token,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"token": view_token, "tokenType": "Bearer"}


@router.post("/documents/{document_id}/labels")
async def set_labels(
    document_id: UUID,
    payload: LabelRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        document = await application.set_labels(
            actor=actor,
            document_id=document_id,
            audience_labels=tuple(payload.audience_labels),
            restricted_labels=tuple(payload.restricted_labels),
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return _document_payload(document)


@router.get("/membership-attributes")
async def get_membership_labels(
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    labels = await application.get_membership_labels(actor=actor)
    return {"userId": str(actor.user_id), "labels": list(labels)}


@router.post("/membership-attributes")
async def set_membership_labels(
    payload: MembershipLabelRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        attributes = await application.set_membership_labels(
            actor=actor,
            user_id=payload.user_id,
            labels=tuple(payload.labels),
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"userId": str(attributes.user_id), "labels": list(attributes.labels)}


@router.post("/documents/{document_id}/permissions")
async def grant_permission(
    document_id: UUID,
    payload: PermissionRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        permission = await application.grant_permission(
            actor=actor,
            document_id=document_id,
            user_id=payload.user_id,
            role=payload.role,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"documentId": str(permission.document_id), "userId": str(permission.user_id), "role": permission.role}


@router.post("/documents/{document_id}/visibility")
async def set_visibility(
    document_id: UUID,
    payload: VisibilityRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        document = await application.set_visibility(
            actor=actor,
            document_id=document_id,
            visibility=payload.visibility,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return _document_payload(document)


@router.post("/documents/{document_id}/access-requests", status_code=201)
async def request_access(
    document_id: UUID,
    payload: AccessRequestBody,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        request = await application.request_access(actor=actor, document_id=document_id, role=payload.role)
    except DomainError as exc:
        raise _http(exc) from exc
    return {"requestId": str(request.id), "role": request.role, "status": request.status}


@router.get("/documents/{document_id}/access-requests")
async def list_access_requests(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        requests = await application.list_access_requests(actor=actor, document_id=document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "requests": [
            {"requestId": str(row.id), "userId": str(row.user_id), "role": row.role, "status": row.status}
            for row in requests
        ]
    }


@router.post("/documents/{document_id}/access-requests/{request_id}")
async def decide_access_request(
    document_id: UUID,
    request_id: UUID,
    payload: AccessDecisionRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        await application.decide_access_request(
            actor=actor,
            document_id=document_id,
            request_id=request_id,
            approve=payload.approve,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.get("/documents/{document_id}/permissions")
async def list_user_shares(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        shares = await application.list_user_shares(actor=actor, document_id=document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "shares": [{"userId": str(share.user_id), "role": share.role} for share in shares],
    }


@router.delete("/documents/{document_id}/permissions/{user_id}", status_code=204)
async def revoke_user_share(
    document_id: UUID,
    user_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        await application.revoke_user_share(actor=actor, document_id=document_id, user_id=user_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.post("/documents/{document_id}/links", status_code=201)
async def create_link(
    document_id: UUID,
    payload: LinkRequest,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        link = await application.create_link(
            actor=actor,
            document_id=document_id,
            target_document_id=payload.target_document_id,
            label=payload.label,
            cascade_depth=payload.cascade_depth,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"linkId": str(link.id), "targetDocumentId": str(link.target_document_id)}


@router.get("/documents/{document_id}/links")
async def list_links(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        links = await application.list_links(actor=actor, document_id=document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return {
        "links": [
            {"linkId": str(link.id), "targetDocumentId": str(link.target_document_id), "label": link.label}
            for link in links
        ]
    }


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    actor=Depends(get_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    try:
        await application.delete_document(actor=actor, document_id=document_id)
    except DomainError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.post("/documents/{document_id}/collaboration-session")
async def open_collaboration(
    document_id: UUID,
    payload: ViewTokenRequest,
    actor=Depends(get_optional_actor),
    application: DataboxApplication = Depends(get_databox_application),
):
    share_token = (payload.share_token or "").strip() or None
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication failed")
    try:
        ticket = await application.open_collaboration(
            actor=actor,
            document_id=document_id,
            share_token=share_token,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    return {"ticket": ticket}
