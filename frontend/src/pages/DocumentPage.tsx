import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, issueViewToken, type DocumentRow, type Session, type VersionRow } from "../api";
import { CollaborativeText } from "../CollaborativeText";
import { connectCollaboration, type Annotation, type Presence } from "../collaboration";

type VersionLink = {
  shareId: string;
  versionId: string;
  permission: string;
  token: string;
  expiresAt: string;
  current: boolean;
};

function shareUrl(token: string): string {
  return `${window.location.origin}/share/${token}`;
}

function expiryLabel(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return `Expires ${when.toLocaleString()}`;
}

function labelsFromInput(value: string): string[] {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const part of value.split(",")) {
    const label = part.trim().toLowerCase();
    if (!label || seen.has(label) || labels.length >= 32) continue;
    seen.add(label);
    labels.push(label);
  }
  return labels;
}

export function DocumentPage({ session }: { session: Session }) {
  const { documentId = "" } = useParams();
  const [documentRow, setDocumentRow] = useState<DocumentRow | null>(null);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [links, setLinks] = useState<VersionLink[]>([]);
  const [pageUrl, setPageUrl] = useState("");
  const [status, setStatus] = useState("Collaboration: disconnected");
  const [canEdit, setCanEdit] = useState(false);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("");
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [presence, setPresence] = useState<Presence[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [linkHours, setLinkHours] = useState("24");
  const [audience, setAudience] = useState("");
  const [restricted, setRestricted] = useState("");
  const [personId, setPersonId] = useState("");
  const [personRole, setPersonRole] = useState("viewer");
  const [people, setPeople] = useState<{ userId: string; role: string }[]>([]);
  const [editor, setEditor] = useState<ReturnType<typeof connectCollaboration> | null>(null);
  const [requests, setRequests] = useState<{ requestId: string; userId: string; role: string }[]>([]);
  const canManage = session.role === "owner" || session.role === "admin";
  const canShare = canManage || documentRow?.createdBy === session.userId;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const metadata = await api<DocumentRow>(`/api/v1/documents/${documentId}`, session);
      if (cancelled) return;
      setDocumentRow(metadata);
      setAudience(metadata.audienceLabels.join(", "));
      setRestricted(metadata.restrictedLabels.join(", "));
      if (metadata.canOpen === false) {
        setVersions([]);
        return;
      }
      const history = await api<{ versions: VersionRow[] }>(`/api/v1/documents/${documentId}/versions`, session);
      if (cancelled) return;
      setVersions(history.versions);
    }
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Document is unavailable"));
    return () => {
      cancelled = true;
    };
  }, [documentId, session]);

  useEffect(() => {
    if (!canShare) return;
    let cancelled = false;
    api<{ links: VersionLink[] }>(`/api/v1/documents/${documentId}/shares`, session)
      .then((payload) => {
        if (!cancelled) setLinks(payload.links);
      })
      .catch(() => {
        if (!cancelled) setLinks([]);
      });
    api<{ shares: { userId: string; role: string }[] }>(`/api/v1/documents/${documentId}/permissions`, session)
      .then((payload) => {
        if (!cancelled) setPeople(payload.shares);
      })
      .catch(() => {
        if (!cancelled) setPeople([]);
      });
    api<{ requests: { requestId: string; userId: string; role: string }[] }>(
      `/api/v1/documents/${documentId}/access-requests`,
      session,
    )
      .then((payload) => {
        if (!cancelled) setRequests(payload.requests);
      })
      .catch(() => {
        if (!cancelled) setRequests([]);
      });
    return () => {
      cancelled = true;
    };
  }, [canShare, documentId, documentRow?.currentVersionId, session]);

  useEffect(() => {
    if (documentRow?.canOpen === false || documentRow?.mimeType !== "text/plain" || !documentRow.currentVersionId) return;
    let cancelled = false;
    let connection: ReturnType<typeof connectCollaboration> | null = null;
    setReady(false);
    api<{ ticket: string }>(`/api/v1/documents/${documentId}/collaboration-session`, session, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((opened) => {
        if (cancelled) return;
        connection = connectCollaboration({
          documentId,
          ticket: opened.ticket,
          name: session.email,
          onStatus: (role, editing) => {
            setCanEdit(editing);
            setStatus(`Collaboration: ${editing ? "editing" : role}`);
          },
          onAnnotations: setAnnotations,
          onPresence: setPresence,
          onSynced: () => {
            if (!cancelled) setReady(true);
          },
        });
        setEditor(connection);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Collaboration is unavailable");
      });
    return () => {
      cancelled = true;
      connection?.disconnect();
    };
  }, [documentId, documentRow?.mimeType, documentRow?.currentVersionId, session]);

  useEffect(() => {
    return () => {
      if (pageUrl) URL.revokeObjectURL(pageUrl);
    };
  }, [pageUrl]);

  const currentEdit = links.find((link) => link.current && link.permission === "editor");
  const currentView = links.find((link) => link.current && link.permission === "viewer");

  async function viewPage() {
    setError("");
    try {
      let token = await issueViewToken(session, documentId);
      let response = await fetch(`/api/v1/documents/${documentId}/pages/1`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) {
        token = await issueViewToken(session, documentId, true);
        response = await fetch(`/api/v1/documents/${documentId}/pages/1`, {
          headers: { Authorization: `Bearer ${token}` },
        });
      }
      if (!response.ok) throw new Error(response.status === 503 ? "Page is still rendering" : "Page is not available");
      const blob = await response.blob();
      if (pageUrl) URL.revokeObjectURL(pageUrl);
      setPageUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Page is not available");
    }
  }

  async function saveVersion() {
    if (!documentRow?.currentVersionId) return;
    setSaving(true);
    setError("");
    try {
      const saved = await api<DocumentRow>(`/api/v1/documents/${documentId}/save`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version_id: documentRow.currentVersionId }),
      });
      const history = await api<{ versions: VersionRow[] }>(`/api/v1/documents/${documentId}/versions`, session);
      setDocumentRow(saved);
      setVersions(history.versions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function reloadShares() {
    if (!canShare) return;
    const payload = await api<{ links: VersionLink[] }>(`/api/v1/documents/${documentId}/shares`, session);
    setLinks(payload.links);
  }

  async function setLinkLifetime(versionId: string, permission: string) {
    const hours = Number(linkHours);
    if (!Number.isFinite(hours) || hours < 1 || hours > 168) {
      setError("Link lifetime must be between 1 and 168 hours");
      return;
    }
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/shares/lifetime`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version_id: versionId,
          permission,
          ttl_seconds: Math.round(hours * 3600),
        }),
      });
      await reloadShares();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Link lifetime was not saved");
    }
  }

  async function saveLabels() {
    setError("");
    try {
      const saved = await api<DocumentRow>(`/api/v1/documents/${documentId}/labels`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audience_labels: labelsFromInput(audience),
          restricted_labels: labelsFromInput(restricted),
        }),
      });
      setDocumentRow(saved);
      setAudience(saved.audienceLabels.join(", "));
      setRestricted(saved.restrictedLabels.join(", "));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Labels were not saved");
    }
  }

  async function reloadPeople() {
    const payload = await api<{ shares: { userId: string; role: string }[] }>(
      `/api/v1/documents/${documentId}/permissions`,
      session,
    );
    setPeople(payload.shares);
  }

  async function shareWithUser() {
    const userId = personId.trim();
    if (!userId) return;
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/permissions`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, role: personRole }),
      });
      setPersonId("");
      await reloadPeople();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That user was not shared");
    }
  }

  async function removePerson(userId: string) {
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/permissions/${userId}`, session, { method: "DELETE" });
      await reloadPeople();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That share was not removed");
    }
  }

  async function restore(versionId: string) {
    if (!documentRow?.currentVersionId) return;
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/versions/${versionId}/restore`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version_id: documentRow.currentVersionId }),
      });
      const history = await api<{ versions: VersionRow[] }>(`/api/v1/documents/${documentId}/versions`, session);
      const metadata = await api<DocumentRow>(`/api/v1/documents/${documentId}`, session);
      setVersions(history.versions);
      setDocumentRow(metadata);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Restore failed");
    }
  }

  function collaborate() {
    setError("");
    editor?.disconnect();
    api<{ ticket: string }>(`/api/v1/documents/${documentId}/collaboration-session`, session, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((opened) => {
        const next = connectCollaboration({
          documentId,
          ticket: opened.ticket,
          name: session.email,
          onStatus: (role, editing) => {
            setCanEdit(editing);
            setStatus(`Collaboration: ${editing ? "editing" : role}`);
          },
          onAnnotations: setAnnotations,
          onPresence: setPresence,
          onSynced: () => setReady(true),
        });
        setEditor(next);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Collaboration is unavailable"));
  }

  async function requestAccess(role: "viewer" | "editor") {
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/access-requests`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      setDocumentRow((current) => (current ? { ...current, pendingRequest: role } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request was not sent");
    }
  }

  async function setVisibility(visibility: "public" | "private") {
    setError("");
    try {
      const saved = await api<DocumentRow>(`/api/v1/documents/${documentId}/visibility`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility }),
      });
      setDocumentRow(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Visibility was not saved");
    }
  }

  async function decideRequest(requestId: string, approve: boolean) {
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/access-requests/${requestId}`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve }),
      });
      setRequests((current) => current.filter((request) => request.requestId !== requestId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request was not updated");
    }
  }

  const textDocument = documentRow?.mimeType === "text/plain";
  const locked = documentRow?.canOpen === false;

  return (
    <main className="screen document-screen">
      <header className="topbar">
        <div>
          <p className="mark">
            <Link to="/">DataBox</Link>
          </p>
          <h1>{documentRow?.title ?? "Document"}</h1>
        </div>
      </header>
      {error ? <p className="error">{error}</p> : null}
      {locked ? (
        <section className="panel">
          <p>This public document is visible to your organization. It opens when it is shared with you or tagged with one of your labels.</p>
          {documentRow?.pendingRequest ? (
            <p className="hint">Asked for {documentRow.pendingRequest === "editor" ? "edit" : "view"} access</p>
          ) : (
            <span className="actions">
              <button type="button" onClick={() => void requestAccess("viewer")}>Ask to view</button>
              <button type="button" className="secondary" onClick={() => void requestAccess("editor")}>Ask to edit</button>
            </span>
          )}
        </section>
      ) : (
        <div className="split document-split">
          <section className="panel editor-panel">
            <div className="actions">
              {textDocument ? (
                <button type="button" onClick={() => void saveVersion()} disabled={saving || !documentRow?.currentVersionId}>
                  {saving ? "Saving" : "Save version"}
                </button>
              ) : (
                <button type="button" onClick={() => void viewPage()}>
                  View page
                </button>
              )}
              {textDocument ? null : (
                <button type="button" className="secondary" onClick={collaborate}>
                  Collaborate
                </button>
              )}
            </div>
            <p>{status}</p>
            <p className="muted">Present: {presence.map((person) => person.name).join(", ") || "nobody else"}</p>
            {textDocument && editor && ready ? <CollaborativeText doc={editor.doc} canEdit={canEdit} /> : null}
            {textDocument && editor && !ready ? <p className="hint">Opening the shared editor</p> : null}
            {pageUrl ? <img className="page" alt="Document page" src={pageUrl} /> : null}
            {textDocument ? null : (
              <>
                {annotations
                  .filter((item) => item.page === 1)
                  .map((item) => (
                    <p className="note" key={item.id}>
                      {item.text}
                    </p>
                  ))}
                <label>
                  Annotation note
                  <textarea value={note} rows={3} disabled={!canEdit} onChange={(event) => setNote(event.target.value)} />
                </label>
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => {
                    editor?.addNote(1, note);
                    setNote("");
                  }}
                >
                  Add annotation
                </button>
              </>
            )}
          </section>
          <aside className="panel share-panel">
            <h2>Access</h2>
            {canManage ? (
              <label>
                Link lifetime in hours
                <input
                  type="number"
                  min={1}
                  max={168}
                  value={linkHours}
                  aria-label="Link lifetime in hours"
                  onChange={(event) => setLinkHours(event.target.value)}
                />
              </label>
            ) : null}
            {currentEdit ? (
              <>
                <label>
                  Edit link
                  <input readOnly value={shareUrl(currentEdit.token)} aria-label="Edit link" />
                </label>
                <p className="hint">{expiryLabel(currentEdit.expiresAt)}</p>
                {canManage ? (
                  <button type="button" className="secondary" onClick={() => void setLinkLifetime(currentEdit.versionId, "editor")}>
                    Set edit link expiry
                  </button>
                ) : null}
              </>
            ) : null}
            {currentView ? (
              <>
                <label>
                  View link
                  <input readOnly value={shareUrl(currentView.token)} aria-label="View link" />
                </label>
                <p className="hint">{expiryLabel(currentView.expiresAt)}</p>
                {canManage ? (
                  <button type="button" className="secondary" onClick={() => void setLinkLifetime(currentView.versionId, "viewer")}>
                    Set view link expiry
                  </button>
                ) : null}
              </>
            ) : null}
            {canShare ? (
              <>
                <p className="hint">This document is {documentRow?.visibility === "public" ? "public" : "private"}.</p>
                <span className="actions">
                  <button type="button" className="secondary" onClick={() => void setVisibility("public")}>Make public</button>
                  <button type="button" className="secondary" onClick={() => void setVisibility("private")}>Make private</button>
                </span>
                {requests.map((request) => (
                  <p key={request.requestId}>
                    {request.userId} asked to {request.role === "editor" ? "edit" : "view"}
                    <span className="actions">
                      <button type="button" onClick={() => void decideRequest(request.requestId, true)}>Allow</button>
                      <button type="button" className="secondary" onClick={() => void decideRequest(request.requestId, false)}>Deny</button>
                    </span>
                  </p>
                ))}
                <label>
                  Share with user id
                  <input
                    value={personId}
                    aria-label="Share with user id"
                    placeholder="User id"
                    onChange={(event) => setPersonId(event.target.value)}
                  />
                </label>
                <label>
                  Access for this user
                  <select aria-label="Access for this user" value={personRole} onChange={(event) => setPersonRole(event.target.value)}>
                    <option value="viewer">View</option>
                    <option value="editor">Edit</option>
                  </select>
                </label>
                <button type="button" className="secondary" onClick={() => void shareWithUser()} disabled={!personId.trim()}>
                  Share with this user
                </button>
                <p className="hint">
                  This share does not expire. The person signs in with that user id. A blocked label still keeps them out, and the access cannot exceed their organization role.
                </p>
                <ul>
                  {people.map((person) => (
                    <li key={person.userId}>
                      {person.userId} ({person.role === "editor" ? "edit" : "view"})
                      <button type="button" className="secondary" onClick={() => void removePerson(person.userId)}>
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
                <label>
                  Always opened by
                  <input
                    value={audience}
                    aria-label="Audience labels"
                    placeholder="finance, legal"
                    onChange={(event) => setAudience(event.target.value)}
                  />
                </label>
                <p className="hint">People with one of these labels can open this public document. A private document still opens only for the people you share it with.</p>
                <label>
                  Blocked for
                  <input
                    value={restricted}
                    aria-label="Restricted labels"
                    placeholder="contractor"
                    onChange={(event) => setRestricted(event.target.value)}
                  />
                </label>
                <p className="hint">People with one of these labels cannot open this document.</p>
                <button type="button" className="secondary" onClick={() => void saveLabels()}>
                  Save document labels
                </button>
              </>
            ) : null}
            <h2>Versions</h2>
            <ul>
              {versions.map((version) => {
                const view = links.find((link) => link.versionId === version.id && link.permission === "viewer");
                const current = version.id === documentRow?.currentVersionId;
                return (
                  <li key={version.id}>
                    Version {version.versionNumber}
                    {current ? " (current)" : ""}
                    {view && !current ? (
                      <>
                        <input readOnly value={shareUrl(view.token)} aria-label={`Version ${version.versionNumber} view link`} />
                        <p className="hint">{expiryLabel(view.expiresAt)}</p>
                        {canManage ? (
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => void setLinkLifetime(view.versionId, "viewer")}
                          >
                            Set this link expiry
                          </button>
                        ) : null}
                      </>
                    ) : null}
                    {textDocument ? null : (
                      <button type="button" className="secondary" onClick={() => void restore(version.id)}>
                        Restore
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </aside>
        </div>
      )}
    </main>
  );
}
