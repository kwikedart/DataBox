import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, issueViewToken, type DocumentRow, type Session, type VersionRow } from "../api";
import "../document.css";
import { Icon } from "../icons";
import { Shell } from "../shell";
import { CollaborativeText } from "../CollaborativeText";
import { connectCollaboration, type Annotation, type Presence } from "../collaboration";
import { AccessRequestDialog } from "../AccessRequestDialog";
import { AccessMatrix } from "./AccessMatrix";

function roleLabel(role: string): string {
  if (role === "owner") return "Owner";
  if (role === "admin") return "Admin";
  if (role === "viewer") return "Viewer";
  return "Member";
}

function initials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._-]+/).filter(Boolean);
  const letters = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
  return (letters || local.slice(0, 2) || "DB").toUpperCase();
}

export function DocumentPage({ session, onSignOut }: { session: Session; onSignOut: () => void }) {
  const { documentId = "" } = useParams();
  const [documentRow, setDocumentRow] = useState<DocumentRow | null>(null);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [pageUrl, setPageUrl] = useState("");
  const [status, setStatus] = useState("Collaboration: disconnected");
  const [canEdit, setCanEdit] = useState(false);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("");
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [presence, setPresence] = useState<Presence[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [accessView, setAccessView] = useState(() => window.location.hash.startsWith("#access"));
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<ReturnType<typeof connectCollaboration> | null>(null);
  const canManage = session.role === "owner" || session.role === "admin";
  const canShare = canManage || documentRow?.createdBy === session.userId;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const metadata = await api<DocumentRow>(`/api/v1/documents/${documentId}`, session);
      if (cancelled) return;
      setDocumentRow(metadata);
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

  useEffect(() => {
    const sync = () => setAccessView(window.location.hash.startsWith("#access"));
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

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
      throw err;
    }
  }

  const textDocument = documentRow?.mimeType === "text/plain";
  const locked = documentRow?.canOpen === false;
  const currentVersion = versions.find((version) => version.id === documentRow?.currentVersionId);
  const publicDocument = documentRow?.visibility === "public";
  const faces = (presence.length ? presence : [{ clientId: 0, name: session.email, page: 1 }]).slice(0, 5);
  const access = documentRow && canShare && !locked ? (
    <AccessMatrix session={session} document={documentRow} versions={versions} onDocument={setDocumentRow} />
  ) : null;
  const history = historyOpen ? (
    <aside className="desk-history" aria-label="Version history">
      <h2>Versions</h2>
      <ul>
        {versions.map((version) => {
          const current = version.id === documentRow?.currentVersionId;
          return (
            <li key={version.id}>
              <span>
                Version {version.versionNumber}
                {current ? " · current" : ""}
              </span>
              {textDocument || current ? null : (
                <button type="button" className="desk-secondary" onClick={() => void restore(version.id)}>
                  Restore
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </aside>
  ) : null;

  async function copyOrganizationId() {
    try {
      await navigator.clipboard.writeText(session.organizationId);
      setNotice("Organization id copied.");
    } catch {
      setNotice("The organization id was not copied.");
    }
  }

  if (accessView && access) {
    return (
      <Shell session={session} onSignOut={onSignOut} notice={notice}>
        <div className="ui-title-row">
          <div>
            <Link to={`/documents/${documentId}`}>Back to document</Link>
            <h1>Share and permissions</h1>
          </div>
        </div>
        {access}
      </Shell>
    );
  }

  return (
    <div className="desk">
      <header className="desk-top">
        <div className="desk-brand">
          <span className="desk-mark">
            <Icon name="shield" size={16} />
          </span>
          <Link to="/">DataBox</Link>
          <nav aria-label="Workspace">
            <Link to="/" className="desk-nav-current">
              Workspaces
            </Link>
          </nav>
        </div>
        <div className="desk-top-side">
          <button type="button" className="desk-secondary" onClick={() => void copyOrganizationId()}>
            <Icon name="copy" size={14} />
            Copy org id
          </button>
          <button type="button" className="desk-account" aria-expanded={menuOpen} aria-label="Account" onClick={() => setMenuOpen((open) => !open)}>
            <span className="desk-avatar">{initials(session.email)}</span>
          </button>
        </div>
      </header>
      {menuOpen ? (
        <>
          <button type="button" className="desk-scrim" aria-label="Close account menu" onClick={() => setMenuOpen(false)} />
          <div className="desk-menu">
            <p>{session.email}</p>
            <button type="button" className="desk-secondary" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </>
      ) : null}
      <section className="desk-sub">
        <div className="desk-identity">
          <div className="desk-crumb">
            <Link to="/">
              <Icon name="chevron" size={14} />
              Back to workspace
            </Link>
          </div>
          <div className="desk-title-row">
            <h1>{documentRow?.title ?? "Document"}</h1>
            <div className="desk-chips">
              <span className="desk-chip">
                <Icon name={publicDocument ? "globe" : "lock"} size={12} />
                {publicDocument ? "Public document" : "Private document"}
              </span>
              {currentVersion ? <span className="desk-chip quiet">Version {currentVersion.versionNumber} · live</span> : null}
              {documentRow?.audienceLabels.map((label) => (
                <span className="desk-chip" key={label}>
                  <Icon name="tag" size={12} />#{label}
                </span>
              ))}
              <span className="desk-chip quiet">{textDocument ? (ready ? (canEdit ? "Editing" : "Viewing") : "Connecting") : "Page"}</span>
            </div>
          </div>
        </div>
        <div className="desk-actions">
          {locked ? null : (
            <div className="desk-faces" aria-label="People in this document">
              {faces.map((person) => {
                const you = person.name === session.email;
                return (
                  <span className={you ? "desk-face you" : "desk-face"} key={person.clientId} tabIndex={0}>
                    {initials(person.name)}
                    <span className="dot" />
                    <span className="desk-tip">
                      {person.name}
                      {you ? ` · You · ${canEdit ? "Editing" : "Viewing"}` : " · Present"}
                    </span>
                  </span>
                );
              })}
            </div>
          )}
          {canShare && !locked ? (
            <button type="button" className="desk-secondary" onClick={() => { window.location.hash = "access"; }}>
              <Icon name="lock" size={14} />
              Share and permissions
            </button>
          ) : null}
          {textDocument && !locked ? (
            <div className="desk-save">
              <button type="button" className="desk-primary" onClick={() => void saveVersion()} disabled={saving || !documentRow?.currentVersionId || locked}>
                <Icon name="check" size={14} />
                {saving ? "Saving" : "Save version"}
              </button>
              <p className="desk-save-note">Saves this draft as the next version. Older edit links stop opening the current text.</p>
            </div>
          ) : locked ? null : (
            <button type="button" className="desk-primary" onClick={() => void viewPage()}>
              View page
            </button>
          )}
        </div>
      </section>
      {notice ? <p className="desk-notice">{notice}</p> : null}
      {error ? <p className="desk-error banner">{error}</p> : null}
      {locked && documentRow ? (
        <AccessRequestDialog
          session={session}
          document={documentRow}
          onClose={() => {
            window.location.assign("/");
          }}
          onRequested={requestAccess}
        />
      ) : textDocument && editor && ready ? (
        <CollaborativeText doc={editor.doc} canEdit={canEdit} history={history} onHistory={() => setHistoryOpen((open) => !open)} />
      ) : (
        <main className="desk-canvas">
          <div className={historyOpen ? "desk-stage with-history" : "desk-stage"}>
            <article className="desk-sheet">
              {textDocument ? <p className="desk-muted">Opening the shared editor</p> : null}
              {textDocument ? null : (
                <div className="desk-inline-actions">
                  <button type="button" className="desk-secondary" onClick={collaborate}>
                    Collaborate
                  </button>
                  <button type="button" className="desk-secondary" onClick={() => setHistoryOpen((open) => !open)}>
                    Version history
                  </button>
                </div>
              )}
              {pageUrl ? <img className="page" alt="Document page" src={pageUrl} /> : null}
              {textDocument
                ? null
                : annotations
                    .filter((item) => item.page === 1)
                    .map((item) => (
                      <p className="note" key={item.id}>
                        {item.text}
                      </p>
                    ))}
              {textDocument ? null : (
                <label className="desk-note">
                  Annotation note
                  <textarea value={note} rows={3} disabled={!canEdit} onChange={(event) => setNote(event.target.value)} />
                  <button
                    type="button"
                    className="desk-primary"
                    disabled={!canEdit}
                    onClick={() => {
                      editor?.addNote(1, note);
                      setNote("");
                    }}
                  >
                    Add annotation
                  </button>
                </label>
              )}
            </article>
            {history}
          </div>
        </main>
      )}
      {textDocument && !locked ? (
        <footer className="desk-status">
          <p>
            <span className={ready ? "desk-live" : "desk-live wait"} />
            {ready ? "Shared editing is connected" : "Connecting the shared editor"}
            <span className="sep">·</span>
            {session.email} [{roleLabel(session.role)}]
            {documentRow?.audienceLabels.length ? (
              <>
                <span className="sep">·</span>
                {documentRow.audienceLabels.map((label) => `#${label}`).join(", ")}
              </>
            ) : null}
          </p>
          <p>{ready ? (canEdit ? "You can edit" : "You can view") : status}</p>
        </footer>
      ) : null}
    </div>
  );
}
