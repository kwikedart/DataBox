"""DataBox policy and application tests. No cloud services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from databox.application.service import DataboxApplication
from databox.domain.entities import UploadOperation
from databox.domain.exceptions import ConflictError, DomainError, NotFoundError, ValidationError
from databox.domain.pdf_validation import validate_pdf
from databox.domain.policies import epochs_match, labels_permit, orphan_keys
from databox.domain.tokens import read_view_token
from databox.infrastructure.memory import (
    MemoryDataboxStore,
    MemoryDocumentLock,
    MemoryEpochCache,
    MemoryFanout,
    MemoryObjectStorage,
    MemoryRateLimiter,
    MemoryTicketStore,
    NullTransaction,
    RecordingRenderQueue,
)
from databox.settings import DataboxSettings
from databox.domain.identity import OrganizationRole, TenantIdentity

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 3 3]>>endobj\n"
    b"trailer<<>>\n%%EOF\n"
)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def settings(**overrides) -> DataboxSettings:
    base = dict(
        token_pepper="pepper",
        view_token_secret="view-secret",
        share_min_ttl_seconds=60,
        share_max_ttl_seconds=86400,
        view_token_ttl_seconds=300,
        orphan_grace_seconds=60,
        allow_guest_edit=False,
        share_resolve_limit=2,
        upload_limit=20,
    )
    base.update(overrides)
    return DataboxSettings(**base)


def build(app_settings: DataboxSettings | None = None):
    store = MemoryDataboxStore()
    storage = MemoryObjectStorage()
    application = DataboxApplication(
        store=store,
        storage=storage,
        epochs=MemoryEpochCache(),
        clock=FrozenClock(NOW),
        settings=app_settings or settings(),
        render_queue=RecordingRenderQueue(),
        transaction=NullTransaction(),
        rate_limiter=MemoryRateLimiter(),
        locks=MemoryDocumentLock(),
        tickets=MemoryTicketStore(),
        fanout=MemoryFanout(),
    )
    return application, store, storage


def actor(role: str, organization_id=None, user_id=None) -> TenantIdentity:
    return TenantIdentity(
        user_id=user_id or uuid4(),
        organization_id=organization_id or uuid4(),
        role=OrganizationRole(role),
    )


def test_signup_email_requires_one_at_sign() -> None:
    from app.auth_routes import _email_is_valid

    assert _email_is_valid("owner@localhost")
    assert _email_is_valid("person@example.com")
    assert not _email_is_valid("not-an-email")
    assert not _email_is_valid("a b@example.com")
    assert not _email_is_valid("@example.com")
    assert not _email_is_valid("person@")


def test_label_ceiling_denies_caller_without_audience() -> None:
    assert labels_permit(audience_labels=("manager",), restricted_labels=(), caller_labels=frozenset()) is False
    assert labels_permit(
        audience_labels=("manager",),
        restricted_labels=(),
        caller_labels=frozenset({"manager"}),
    )


def test_restricted_label_denies_even_when_audience_matches() -> None:
    assert (
        labels_permit(
            audience_labels=("sales",),
            restricted_labels=("blocked",),
            caller_labels=frozenset({"sales", "blocked"}),
        )
        is False
    )


def test_pdf_rejects_active_content_and_non_pdf() -> None:
    with pytest.raises(ValidationError):
        validate_pdf(b"not a pdf", max_bytes=1000, max_pages=5)
    hostile = PDF.replace(b"trailer", b"/JavaScript (alert) trailer")
    with pytest.raises(ValidationError):
        validate_pdf(hostile, max_bytes=1000, max_pages=5)
    assert validate_pdf(PDF, max_bytes=1000, max_pages=5) == 1


def test_orphan_cleanup_skips_referenced_keys() -> None:
    referenced = "org/o/documents/d/versions/v.pdf"
    old = NOW - timedelta(hours=2)
    operations = [
        UploadOperation(id=uuid4(), organization_id=uuid4(), object_key=referenced, status="abandoned", created_at=old),
        UploadOperation(
            id=uuid4(),
            organization_id=uuid4(),
            object_key="org/o/documents/d/versions/orphan.pdf",
            status="abandoned",
            created_at=old,
        ),
        UploadOperation(
            id=uuid4(),
            organization_id=uuid4(),
            object_key="org/o/documents/d/versions/fresh.pdf",
            status="abandoned",
            created_at=NOW,
        ),
    ]
    ready = orphan_keys(operations, {referenced}, now=NOW, grace_seconds=60)
    assert [item.object_key for item in ready] == ["org/o/documents/d/versions/orphan.pdf"]


def test_epoch_mismatch_is_not_authorized() -> None:
    assert epochs_match(1, 1)
    assert epochs_match(1, 2) is False
    assert epochs_match(1, None) is False


@pytest.mark.asyncio
async def test_upload_lists_for_editor_and_hides_from_other_org() -> None:
    application, _store, storage = build()
    editor = actor("member")
    document = await application.create_document(actor=editor, title="Labs", content=PDF)
    assert document.current_version_id is not None
    assert storage.objects
    outsider = actor("owner")
    with pytest.raises(NotFoundError):
        await application.get_document(actor=outsider, document_id=document.id)
    listed = await application.list_documents(actor=editor)
    assert [row.document.id for row in listed] == [document.id]


@pytest.mark.asyncio
async def test_viewer_cannot_download_or_upload() -> None:
    application, _store, _storage = build()
    organization_id = uuid4()
    editor = actor("member", organization_id=organization_id)
    viewer = actor("viewer", organization_id=organization_id)
    document = await application.create_document(actor=editor, title="Labs", content=PDF)
    with pytest.raises(NotFoundError):
        await application.download(actor=viewer, document_id=document.id)
    with pytest.raises(NotFoundError):
        await application.add_version(
            actor=viewer,
            document_id=document.id,
            content=PDF,
            expected_version_id=document.current_version_id,
        )


@pytest.mark.asyncio
async def test_stale_restore_conflicts_and_lineage_is_a_new_version() -> None:
    application, _store, _storage = build()
    editor = actor("admin")
    document = await application.create_document(actor=editor, title="Labs", content=PDF)
    first = document.current_version_id
    second = await application.add_version(
        actor=editor,
        document_id=document.id,
        content=PDF,
        expected_version_id=first,
    )
    with pytest.raises(ConflictError):
        await application.restore_version(
            actor=editor,
            document_id=document.id,
            version_id=first,
            expected_version_id=first,
        )
    restored = await application.restore_version(
        actor=editor,
        document_id=document.id,
        version_id=first,
        expected_version_id=second.id,
    )
    assert restored.version_number == 3
    assert restored.source_version_id == first
    member = actor("member", organization_id=editor.organization_id)
    with pytest.raises(NotFoundError):
        await application.restore_version(
            actor=member,
            document_id=document.id,
            version_id=first,
            expected_version_id=restored.id,
        )


@pytest.mark.asyncio
async def test_share_link_is_hashed_and_label_ceiling_blocks_it() -> None:
    application, store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Secret", content=PDF)
    created = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    stored = await store.get_share(owner.organization_id, created.share_id)
    assert stored is not None
    assert created.url_token not in stored.token_hash
    assert stored.token_hash != created.url_token
    resolved = await application.resolve_share(actor=owner, token=created.url_token, caller_key="client")
    assert resolved.id == created.share_id
    with pytest.raises(ValidationError):
        await application.create_share_link(
            actor=owner,
            document_id=document.id,
            permission="editor",
            expires_at=NOW + timedelta(hours=2),
        )
    await application.set_visibility(actor=owner, document_id=document.id, visibility="public")
    await application.set_labels(
        actor=owner,
        document_id=document.id,
        audience_labels=("manager",),
        restricted_labels=(),
    )
    blocked = actor("member", organization_id=owner.organization_id)
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=blocked, token=created.url_token, caller_key="client-2")
    customer = actor("member", organization_id=owner.organization_id)
    await application.set_membership_labels(actor=owner, user_id=customer.user_id, labels=("manager",))
    allowed = await application.resolve_share(actor=customer, token=created.url_token, caller_key="customer")
    assert allowed.id == created.share_id
    outsider = actor("member")
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=outsider, token=created.url_token, caller_key="outsider")


@pytest.mark.asyncio
async def test_share_lifetime_expires_the_old_link_and_a_blocked_label_cannot_open_it() -> None:
    application, _store, _storage = build(settings(share_resolve_limit=20))
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Timed", content=PDF)
    created = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    assert document.current_version_id is not None
    replaced = await application.set_share_lifetime(
        actor=owner,
        document_id=document.id,
        version_id=document.current_version_id,
        permission="viewer",
        ttl_seconds=3600,
    )
    assert replaced.expires_at == NOW + timedelta(hours=1)
    assert replaced.url_token != created.url_token
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=owner, token=created.url_token, caller_key="old")
    await application.resolve_share(actor=owner, token=replaced.url_token, caller_key="new")
    blocked = actor("member", organization_id=owner.organization_id)
    await application.set_membership_labels(actor=owner, user_id=blocked.user_id, labels=("contractor",))
    await application.set_labels(
        actor=owner,
        document_id=document.id,
        audience_labels=(),
        restricted_labels=("contractor",),
    )
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=blocked, token=replaced.url_token, caller_key="blocked")
    with pytest.raises(NotFoundError):
        await application.open_collaboration(actor=None, document_id=document.id, share_token=replaced.url_token)


@pytest.mark.asyncio
async def test_revoked_and_missing_shares_look_the_same() -> None:
    application, _store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Secret", content=PDF)
    created = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    await application.revoke_share_link(actor=owner, share_id=created.share_id)
    with pytest.raises(NotFoundError, match="Share link not found"):
        await application.resolve_share(actor=owner, token=created.url_token, caller_key="a")
    with pytest.raises(NotFoundError, match="Share link not found"):
        await application.resolve_share(actor=owner, token="missing-token", caller_key="b")


def yjs_update(key: str, value: str) -> bytes:
    from pycrdt import Doc, Map

    document = Doc()
    notes = document.get("annotations", type=Map)
    notes[key] = value
    return document.get_update()


@pytest.mark.asyncio
async def test_view_token_page_check_ignores_later_policy_changes() -> None:
    application, store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Labs", content=PDF)
    token = await application.issue_view_token(actor=owner, document_id=document.id)
    calls = {"documents": 0}
    original = store.get_document

    async def counting(organization_id, document_id):
        calls["documents"] += 1
        return await original(organization_id, document_id)

    store.get_document = counting  # type: ignore[method-assign]
    grant = await application.authorize_page(token=token, document_id=document.id, page=1)
    assert calls["documents"] == 0
    assert grant.version_id == document.current_version_id
    assert grant.object_key.endswith(f"/renders/{document.current_version_id}/page-1.webp")
    await application.set_labels(actor=owner, document_id=document.id, audience_labels=("manager",), restricted_labels=())
    still_valid = await application.authorize_page(token=token, document_id=document.id, page=1)
    assert still_valid.object_key == grant.object_key
    stranger = actor("member", organization_id=owner.organization_id)
    with pytest.raises(NotFoundError):
        await application.issue_view_token(actor=stranger, document_id=document.id)
    claims = read_view_token(token, secret="view-secret", now=NOW)
    assert "download" not in claims.scope
    assert claims.page_count == 1


@pytest.mark.asyncio
async def test_cascade_does_not_grant_unlinked_or_deeper_documents() -> None:
    application, _store, _storage = build()
    owner = actor("owner")
    source = await application.create_document(actor=owner, title="A", content=PDF)
    target = await application.create_document(actor=owner, title="B", content=PDF)
    hidden = await application.create_document(actor=owner, title="C", content=PDF)
    parent = await application.issue_view_token(actor=owner, document_id=source.id)
    with pytest.raises(NotFoundError):
        await application.issue_view_token(actor=owner, document_id=target.id, parent_token=parent)
    await application.create_link(
        actor=owner,
        document_id=source.id,
        target_document_id=target.id,
        cascade_depth=1,
    )
    await application.create_link(
        actor=owner,
        document_id=target.id,
        target_document_id=hidden.id,
        cascade_depth=1,
    )
    await application.set_labels(
        actor=owner,
        document_id=hidden.id,
        audience_labels=("manager",),
        restricted_labels=(),
    )
    child = await application.issue_view_token(actor=owner, document_id=target.id, parent_token=parent)
    with pytest.raises(NotFoundError):
        await application.issue_view_token(actor=owner, document_id=hidden.id, parent_token=child)
    links = await application.list_links(actor=owner, document_id=target.id)
    assert [link.target_document_id for link in links] == [hidden.id]


@pytest.mark.asyncio
async def test_document_grant_cannot_widen_a_viewer() -> None:
    application, store, _storage = build()
    organization_id = uuid4()
    owner = actor("owner", organization_id=organization_id)
    viewer = actor("viewer", organization_id=organization_id)
    document = await application.create_document(actor=owner, title="Labs", content=PDF)
    store.members[(organization_id, viewer.user_id)] = "viewer"
    await application.grant_permission(
        actor=owner,
        document_id=document.id,
        user_id=viewer.user_id,
        role="editor",
    )
    with pytest.raises(NotFoundError):
        await application.add_version(
            actor=viewer,
            document_id=document.id,
            content=PDF,
            expected_version_id=document.current_version_id,
        )


@pytest.mark.asyncio
async def test_user_id_share_opens_a_labeled_document_until_it_is_removed() -> None:
    application, store, _storage = build(settings(share_resolve_limit=20))
    organization_id = uuid4()
    owner = actor("owner", organization_id=organization_id)
    customer = actor("member", organization_id=organization_id)
    other = actor("member", organization_id=organization_id)
    outsider = actor("member")
    store.members[(organization_id, customer.user_id)] = "member"
    store.members[(organization_id, other.user_id)] = "member"
    store.members[(organization_id, owner.user_id)] = "owner"
    await application.set_membership_labels(actor=owner, user_id=owner.user_id, labels=("finance",))
    document = await application.create_text_document(actor=owner, title="Named notes")
    await application.set_labels(
        actor=owner,
        document_id=document.id,
        audience_labels=("finance",),
        restricted_labels=(),
    )
    with pytest.raises(NotFoundError):
        await application.get_document(actor=customer, document_id=document.id)
    with pytest.raises(ValidationError):
        await application.grant_permission(
            actor=owner,
            document_id=document.id,
            user_id=outsider.user_id,
            role="viewer",
        )
    with pytest.raises(ValidationError):
        await application.grant_permission(
            actor=owner,
            document_id=document.id,
            user_id=owner.user_id,
            role="viewer",
        )
    granted = await application.grant_permission(
        actor=owner,
        document_id=document.id,
        user_id=customer.user_id,
        role="editor",
    )
    assert granted.role == "editor"
    assert (await application.get_document(actor=customer, document_id=document.id)).id == document.id
    with pytest.raises(NotFoundError):
        await application.get_document(actor=other, document_id=document.id)
    assert [row.document.id for row in await application.list_documents(actor=customer)] == [document.id]
    assert await application.list_documents(actor=other) == []
    shares = await application.list_user_shares(actor=owner, document_id=document.id)
    assert [(row.user_id, row.role) for row in shares] == [(customer.user_id, "editor")]
    with pytest.raises(NotFoundError):
        await application.list_user_shares(actor=customer, document_id=document.id)
    link = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=1),
    )
    opened = await application.resolve_share(actor=customer, token=link.url_token, caller_key="customer")
    assert opened.document_id == document.id
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=other, token=link.url_token, caller_key="other")
    await application.set_membership_labels(actor=owner, user_id=customer.user_id, labels=("contractor",))
    await application.set_labels(
        actor=owner,
        document_id=document.id,
        audience_labels=("finance",),
        restricted_labels=("contractor",),
    )
    with pytest.raises(NotFoundError):
        await application.get_document(actor=customer, document_id=document.id)
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=customer, token=link.url_token, caller_key="blocked")
    await application.set_membership_labels(actor=owner, user_id=customer.user_id, labels=())
    await application.set_labels(
        actor=owner,
        document_id=document.id,
        audience_labels=("finance",),
        restricted_labels=(),
    )
    await application.revoke_user_share(actor=owner, document_id=document.id, user_id=customer.user_id)
    with pytest.raises(NotFoundError):
        await application.get_document(actor=customer, document_id=document.id)
    with pytest.raises(NotFoundError):
        await application.resolve_share(actor=customer, token=link.url_token, caller_key="revoked")


@pytest.mark.asyncio
async def test_public_document_is_listed_and_opens_after_the_creator_approves() -> None:
    application, store, _storage = build()
    organization_id = uuid4()
    creator = actor("member", organization_id=organization_id)
    colleague = actor("member", organization_id=organization_id)
    store.members[(organization_id, creator.user_id)] = "member"
    store.members[(organization_id, colleague.user_id)] = "member"
    private_doc = await application.create_text_document(actor=creator, title="Private notes")
    public_doc = await application.create_text_document(actor=creator, title="Public notes")
    await application.set_visibility(actor=creator, document_id=public_doc.id, visibility="public")
    listed = await application.list_documents(actor=colleague)
    assert [row.document.id for row in listed] == [public_doc.id]
    assert listed[0].can_open is False
    with pytest.raises(NotFoundError):
        await application.get_document(actor=colleague, document_id=public_doc.id)
    with pytest.raises(NotFoundError):
        await application.get_document(actor=colleague, document_id=private_doc.id)
    request = await application.request_access(actor=colleague, document_id=public_doc.id, role="editor")
    await application.decide_access_request(
        actor=creator,
        document_id=public_doc.id,
        request_id=request.id,
        approve=True,
    )
    assert (await application.get_document(actor=colleague, document_id=public_doc.id)).id == public_doc.id
    with pytest.raises(NotFoundError):
        await application.get_document(actor=colleague, document_id=private_doc.id)


@pytest.mark.asyncio
async def test_failed_commit_abandons_unreferenced_object() -> None:
    application, store, storage = build()
    editor = actor("member")

    async def fail_commit(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    store.commit_new_version = fail_commit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await application.create_document(actor=editor, title="Labs", content=PDF)
    abandoned = await store.abandoned_uploads()
    assert len(abandoned) == 1
    assert abandoned[0].object_key not in await store.referenced_object_keys()
    application.clock._now = NOW + timedelta(hours=2)  # type: ignore[attr-defined]
    deleted = await application.cleanup_orphans()
    assert deleted == [abandoned[0].object_key]
    assert abandoned[0].object_key not in storage.objects


@pytest.mark.asyncio
async def test_collaboration_rejects_viewers_and_keeps_both_updates() -> None:
    application, store, _storage = build()
    organization_id = uuid4()
    editor = actor("member", organization_id=organization_id)
    viewer = actor("viewer", organization_id=organization_id)
    document = await application.create_document(actor=editor, title="Notes", content=PDF)
    store.members[(organization_id, viewer.user_id)] = "viewer"
    await application.grant_permission(actor=editor, document_id=document.id, user_id=viewer.user_id, role="viewer")
    editor_ticket = await application.open_collaboration(actor=editor, document_id=document.id)
    viewer_ticket = await application.open_collaboration(actor=viewer, document_id=document.id)
    editor_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=editor_ticket)
    viewer_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=viewer_ticket)
    with pytest.raises(NotFoundError):
        await application.accept_collaboration_ticket(document_id=document.id, ticket=editor_ticket)
    with pytest.raises(NotFoundError):
        await application.apply_collaboration_update(session=viewer_session, update=yjs_update("viewer", "no"))
    first = yjs_update("alpha", "1")
    second = yjs_update("beta", "2")
    await application.apply_collaboration_update(session=editor_session, update=first)
    await application.apply_collaboration_update(session=editor_session, update=second)
    snapshot, updates = await application.collaboration_state(editor_session)
    assert snapshot is None
    assert updates == [first, second]
    from pycrdt import Doc, Map

    merged = Doc()
    for update in updates:
        merged.apply_update(update)
    assert dict(merged.get("annotations", type=Map)) == {"alpha": "1", "beta": "2"}


@pytest.mark.asyncio
async def test_revoked_share_closes_collaboration_session() -> None:
    application, _store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Shared", content=PDF)
    created = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    ticket = await application.open_collaboration(
        actor=owner,
        document_id=document.id,
        share_token=created.url_token,
    )
    session = await application.accept_collaboration_ticket(document_id=document.id, ticket=ticket)
    assert await application.session_still_valid(session)
    await application.revoke_share_link(actor=owner, share_id=created.share_id)
    assert await application.session_still_valid(session) is False


@pytest.mark.asyncio
async def test_text_document_can_be_shared_for_editing() -> None:
    application, _store, _storage = build(settings(share_resolve_limit=20))
    owner = actor("owner")
    guest = actor("viewer")
    document = await application.create_text_document(actor=owner, title="Meeting notes")
    assert document.mime_type == "text/plain"
    assert document.current_version_id is not None
    assert application.render_queue.jobs == []
    token = await application.issue_view_token(actor=owner, document_id=document.id)
    claims = read_view_token(token, secret="view-secret", now=NOW)
    assert claims.page_count == 1
    assert claims.render_generation == 0
    grant = await application.authorize_page(token=token, document_id=document.id, page=1)
    assert grant.object_key.endswith("/page-1.webp")
    with pytest.raises(DomainError, match="Page is not ready"):
        await application.open_rendered_page(grant)
    assert application.render_queue.jobs[-1][1] == document.id
    editor_share = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="editor",
        expires_at=NOW + timedelta(hours=2),
    )
    viewer_share = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    editor_ticket = await application.open_collaboration(
        actor=owner,
        document_id=document.id,
        share_token=editor_share.url_token,
    )
    viewer_ticket = await application.open_collaboration(
        actor=owner,
        document_id=document.id,
        share_token=viewer_share.url_token,
    )
    editor_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=editor_ticket)
    viewer_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=viewer_ticket)
    assert "edit" in editor_session.actions
    await application.apply_collaboration_update(session=editor_session, update=yjs_update("body", "pasted"))
    with pytest.raises(NotFoundError):
        await application.apply_collaboration_update(session=viewer_session, update=yjs_update("body", "blocked"))
    pdf = await application.create_document(actor=owner, title="Scan", content=PDF)
    with pytest.raises(ValidationError):
        await application.create_share_link(
            actor=owner,
            document_id=pdf.id,
            permission="editor",
            expires_at=NOW + timedelta(hours=2),
        )
    with pytest.raises(NotFoundError):
        await application.create_text_document(actor=guest, title="Denied")


def note_update() -> bytes:
    from pycrdt import Doc, XmlElement, XmlFragment, XmlText

    document = Doc()
    fragment = document.get("content", type=XmlFragment)
    heading = XmlElement("heading", {"level": "1"})
    paragraph = XmlElement("paragraph")
    fragment.children.append(heading)
    fragment.children.append(paragraph)
    title = XmlText("Meeting")
    body = XmlText("bold note")
    heading.children.append(title)
    paragraph.children.append(body)
    body.format(0, 4, {"bold": True})
    return document.get_update()


@pytest.mark.asyncio
async def test_save_keeps_a_view_link_for_each_version_and_edits_only_the_current_one() -> None:
    from databox.infrastructure.render_job import document_html
    from pycrdt import Doc

    application, store, _storage = build(settings(share_resolve_limit=20))
    owner = actor("owner")
    document = await application.create_text_document(actor=owner, title="Meeting notes")
    assert document.current_version_id is not None
    session = await application.accept_collaboration_ticket(
        document_id=document.id,
        ticket=await application.open_collaboration(actor=owner, document_id=document.id),
    )
    await application.apply_collaboration_update(session=session, update=note_update())
    before = await application.list_version_shares(actor=owner, document_id=document.id)
    old_edit = next(link for link in before if link.permission == "editor" and link.current)
    saved = await application.save_text_version(
        actor=owner,
        document_id=document.id,
        expected_version_id=document.current_version_id,
    )
    assert saved.current_version_id != document.current_version_id
    with pytest.raises(NotFoundError):
        await application.open_collaboration(actor=owner, document_id=document.id, share_token=old_edit.url_token)
    links = await application.list_version_shares(actor=owner, document_id=document.id)
    assert sum(1 for link in links if link.current and link.permission == "editor") == 1
    assert sum(1 for link in links if link.current and link.permission == "viewer") == 1
    previous = [link for link in links if not link.current]
    assert previous and all(link.permission == "viewer" for link in previous)
    assert await store.list_updates(document.id, document.current_version_id)
    assert await store.list_updates(document.id, saved.current_version_id) == []
    current_edit = next(link for link in links if link.current and link.permission == "editor")
    current_session = await application.accept_collaboration_ticket(
        document_id=document.id,
        ticket=await application.open_collaboration(
            actor=owner,
            document_id=document.id,
            share_token=current_edit.url_token,
        ),
    )
    snapshot, updates = await application.collaboration_state(current_session)
    restored = Doc()
    if snapshot:
        restored.apply_update(snapshot)
    for update in updates:
        restored.apply_update(update)
    assert "Meeting" in document_html(restored)
    old_view = next(link for link in links if link.version_id == document.current_version_id)
    token = await application.issue_view_token(actor=owner, document_id=document.id, share_token=old_view.url_token)
    claims = read_view_token(token, secret="view-secret", now=NOW)
    assert claims.version_id == document.current_version_id
    fresh = await application.list_version_shares(actor=owner, document_id=document.id)
    assert {link.url_token for link in fresh} == {link.url_token for link in links}


@pytest.mark.asyncio
async def test_view_share_renders_heading_and_bold_without_edit_access() -> None:
    from databox.infrastructure.render_job import document_html, render_stored_version

    application, store, storage = build(settings(share_resolve_limit=20))
    owner = actor("owner")
    document = await application.create_text_document(actor=owner, title="Meeting notes")
    editor_share = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="editor",
        expires_at=NOW + timedelta(hours=2),
    )
    viewer_share = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    editor_ticket = await application.open_collaboration(
        actor=owner, document_id=document.id, share_token=editor_share.url_token
    )
    viewer_ticket = await application.open_collaboration(
        actor=owner, document_id=document.id, share_token=viewer_share.url_token
    )
    editor_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=editor_ticket)
    viewer_session = await application.accept_collaboration_ticket(document_id=document.id, ticket=viewer_ticket)
    update = note_update()
    await application.apply_collaboration_update(session=editor_session, update=update)
    with pytest.raises(NotFoundError):
        await application.apply_collaboration_update(session=viewer_session, update=update)
    loaded = await application.load_collaboration_document(editor_session)
    html = document_html(loaded)
    assert "<h1>" in html
    assert "Meeting" in html
    assert "<strong>" in html
    assert "<script>" not in html
    count = await render_stored_version(
        store=store,
        storage=storage,
        organization_id=owner.organization_id,
        document_id=document.id,
        version_id=document.current_version_id,
        max_pages=5,
    )
    assert count == 1
    token = await application.issue_view_token(actor=owner, document_id=document.id, share_token=viewer_share.url_token)
    claims = read_view_token(token, secret="view-secret", now=NOW)
    assert claims.page_count == 1
    assert claims.render_generation == 1
    grant = await application.authorize_page(token=token, document_id=document.id, page=1)
    first, chunks = await application.open_rendered_page(grant)
    assert first.startswith(b"RIFF")
    await chunks.aclose()


@pytest.mark.asyncio
async def test_render_job_writes_pages_without_touching_the_api_process() -> None:
    from databox.infrastructure.render_job import render_stored_version

    application, store, storage = build()
    editor = actor("member")
    document = await application.create_document(actor=editor, title="Labs", content=PDF)
    count = await render_stored_version(
        store=store,
        storage=storage,
        organization_id=editor.organization_id,
        document_id=document.id,
        version_id=document.current_version_id,
        max_pages=5,
        rasterize=lambda data, max_pages: [b"webp-page"],
    )
    assert count == 1
    key = f"org/{editor.organization_id}/documents/{document.id}/renders/{document.current_version_id}/page-1.webp"
    assert storage.objects[key] == b"webp-page"
    saved = await store.get_version(editor.organization_id, document.current_version_id)
    assert saved is not None
    assert saved.render_status == "ready"


@pytest.mark.asyncio
async def test_page_token_rejects_tampering_wrong_document_and_expiry() -> None:
    application, _store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Labs", content=PDF)
    token = await application.issue_view_token(actor=owner, document_id=document.id)
    signature = token.rsplit(".", 1)[-1]
    midpoint = max(len(signature) // 2, 1)
    damaged = signature[:midpoint] + ("A" if signature[midpoint] != "A" else "B") + signature[midpoint + 1 :]
    flipped = token[: -len(signature)] + damaged
    with pytest.raises(ValidationError):
        await application.authorize_page(token=flipped, document_id=document.id, page=1)
    with pytest.raises(ValidationError):
        await application.authorize_page(token=token, document_id=uuid4(), page=1)
    with pytest.raises(NotFoundError):
        await application.authorize_page(token=token, document_id=document.id, page=9)
    application.clock._now = NOW + timedelta(hours=2)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        await application.authorize_page(token=token, document_id=document.id, page=1)


@pytest.mark.asyncio
async def test_revoked_share_keeps_existing_page_token_until_expiry() -> None:
    application, _store, _storage = build(settings(share_resolve_limit=20))
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Shared", content=PDF)
    created = await application.create_share_link(
        actor=owner,
        document_id=document.id,
        permission="viewer",
        expires_at=NOW + timedelta(hours=2),
    )
    token = await application.issue_view_token(actor=owner, document_id=document.id, share_token=created.url_token)
    await application.revoke_share_link(actor=owner, share_id=created.share_id)
    grant = await application.authorize_page(token=token, document_id=document.id, page=1)
    assert grant.document_id == document.id
    with pytest.raises(NotFoundError):
        await application.issue_view_token(actor=owner, document_id=document.id, share_token=created.url_token)
    with pytest.raises(NotFoundError):
        await application.open_collaboration(actor=owner, document_id=document.id, share_token=created.url_token)


@pytest.mark.asyncio
async def test_missing_page_enqueues_render_without_rasterizing() -> None:
    import inspect

    import app.routes as routes

    application, _store, _storage = build()
    owner = actor("owner")
    document = await application.create_document(actor=owner, title="Labs", content=PDF)
    token = await application.issue_view_token(actor=owner, document_id=document.id)
    grant = await application.authorize_page(token=token, document_id=document.id, page=1)
    with pytest.raises(DomainError, match="Page is not ready"):
        await application.open_rendered_page(grant)
    assert application.render_queue.jobs[-1] == (owner.organization_id, document.id, document.current_version_id)
    source = inspect.getsource(routes)
    assert "fitz" not in source
    assert "pymupdf" not in source


@pytest.mark.asyncio
async def test_collaboration_reloads_snapshot_and_ignores_viewer_frames() -> None:
    from pycrdt import Map, create_update_message

    application, store, _storage = build(settings(snapshot_every_updates=1))
    organization_id = uuid4()
    editor = actor("member", organization_id=organization_id)
    viewer = actor("viewer", organization_id=organization_id)
    document = await application.create_document(actor=editor, title="Notes", content=PDF)
    store.members[(organization_id, viewer.user_id)] = "viewer"
    await application.grant_permission(actor=editor, document_id=document.id, user_id=viewer.user_id, role="viewer")
    editor_session = await application.accept_collaboration_ticket(
        document_id=document.id,
        ticket=await application.open_collaboration(actor=editor, document_id=document.id),
    )
    viewer_session = await application.accept_collaboration_ticket(
        document_id=document.id,
        ticket=await application.open_collaboration(actor=viewer, document_id=document.id),
    )
    server_doc = await application.load_collaboration_document(editor_session)
    ignored = await application.handle_collaboration_message(
        session=viewer_session,
        frame=create_update_message(yjs_update("secret", "no")),
        document=server_doc,
    )
    assert ignored.reply is None
    assert ignored.forward is None
    await application.handle_collaboration_message(
        session=editor_session,
        frame=create_update_message(yjs_update("note", "kept")),
        document=server_doc,
    )
    restored = await application.load_collaboration_document(editor_session)
    assert dict(restored.get("annotations", type=Map)) == {"note": "kept"}
