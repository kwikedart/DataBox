import { useEffect, useState } from "react";
import { api, type DocumentRow, type Session, type VersionRow } from "../api";
import { Icon } from "../icons";
import "../access.css";

type VersionLink = {
  shareId: string;
  versionId: string;
  permission: string;
  token: string;
  expiresAt: string;
  current: boolean;
};

type Person = { userId: string; role: string };
type RequestRow = { requestId: string; userId: string; role: string };

const userIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function shareUrl(token: string): string {
  return `${window.location.origin}/share/${token}`;
}

function expiryLabel(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return `Expires ${when.toLocaleString()}`;
}

function labelToken(value: string): string {
  return value.trim().toLowerCase().replace(/^#/, "");
}

function initials(userId: string): string {
  return userId.replace(/-/g, "").slice(0, 2).toUpperCase();
}

export function AccessMatrix({
  session,
  document,
  versions,
  onDocument,
}: {
  session: Session;
  document: DocumentRow;
  versions: VersionRow[];
  onDocument: (document: DocumentRow) => void;
}) {
  const [links, setLinks] = useState<VersionLink[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [audienceInput, setAudienceInput] = useState("");
  const [blockedInput, setBlockedInput] = useState("");
  const [personId, setPersonId] = useState("");
  const [personRole, setPersonRole] = useState("viewer");
  const [editHours, setEditHours] = useState(24);
  const [viewHours, setViewHours] = useState(72);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [tab, setTab] = useState<"labels" | "people" | "links" | "requests">("labels");
  const canManage = session.role === "owner" || session.role === "admin";

  const currentEdit = links.find((link) => link.current && link.permission === "editor");
  const currentView = links.find((link) => link.current && link.permission === "viewer");
  const olderViews = links.filter((link) => link.permission === "viewer" && !link.current);

  async function loadShares() {
    const [sharePayload, peoplePayload, requestPayload] = await Promise.all([
      api<{ links: VersionLink[] }>(`/api/v1/documents/${document.documentId}/shares`, session),
      api<{ shares: Person[] }>(`/api/v1/documents/${document.documentId}/permissions`, session),
      api<{ requests: RequestRow[] }>(`/api/v1/documents/${document.documentId}/access-requests`, session),
    ]);
    setLinks(sharePayload.links);
    setPeople(peoplePayload.shares);
    setRequests(requestPayload.requests);
  }

  useEffect(() => {
    let cancelled = false;
    loadShares().catch(() => {
      if (!cancelled) setError("Access details could not be loaded");
    });
    return () => {
      cancelled = true;
    };
  }, [document.documentId, document.currentVersionId, session.token]);

  async function run(action: () => Promise<void>) {
    if (pending) return;
    setError("");
    setPending(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That change was not saved");
    } finally {
      setPending(false);
    }
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice("Link copied.");
    } catch {
      setNotice("Copy was blocked by the browser.");
    }
  }

  function saveLabels(audience: string[], restricted: string[]) {
    return run(async () => {
      const saved = await api<DocumentRow>(`/api/v1/documents/${document.documentId}/labels`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audience_labels: audience, restricted_labels: restricted }),
      });
      onDocument(saved);
    });
  }

  function addLabel(kind: "audience" | "blocked") {
    const raw = kind === "audience" ? audienceInput : blockedInput;
    const label = labelToken(raw);
    if (!label || /\s/.test(label)) {
      setError("Use a short label without spaces.");
      return;
    }
    const audience = kind === "audience" ? [...document.audienceLabels, label] : document.audienceLabels;
    const restricted = kind === "blocked" ? [...document.restrictedLabels, label] : document.restrictedLabels;
    const unique = (values: string[]) => [...new Set(values.map((item) => item.trim().toLowerCase()).filter(Boolean))].slice(0, 32);
    void saveLabels(unique(audience), unique(restricted));
    if (kind === "audience") setAudienceInput("");
    else setBlockedInput("");
  }

  function removeLabel(kind: "audience" | "blocked", label: string) {
    const audience = kind === "audience" ? document.audienceLabels.filter((item) => item !== label) : document.audienceLabels;
    const restricted = kind === "blocked" ? document.restrictedLabels.filter((item) => item !== label) : document.restrictedLabels;
    void saveLabels(audience, restricted);
  }

  function setLifetime(versionId: string, permission: string, hours: number) {
    if (hours < 1 || hours > 168) {
      setError("Link lifetime must be between 1 and 168 hours.");
      return;
    }
    void run(async () => {
      await api(`/api/v1/documents/${document.documentId}/shares/lifetime`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: versionId, permission, ttl_seconds: Math.round(hours * 3600) }),
      });
      await loadShares();
      setNotice("A new link was issued. The previous URL no longer works.");
    });
  }

  const currentVersion = versions.find((version) => version.id === document.currentVersionId);
  const tabs = [
    ["labels", "Visibility and labels"],
    ["people", `Direct shares ${people.length}`],
    ["links", "Expiring share links"],
    ["requests", `Access requests ${requests.length}`],
  ] as const;

  return (
    <section className="ui-access" id="access">
      <header className="ui-access-head">
        <div>
          <h2>{document.title}</h2>
          <p>
            {document.documentId}
            {currentVersion ? ` · v${currentVersion.versionNumber}` : ""}
          </p>
        </div>
        <span className={document.visibility === "public" ? "ui-chip" : "ui-chip"}>{document.visibility === "public" ? "Public" : "Private"}</span>
      </header>
      <div className="ui-access-tabs" role="tablist">
        {tabs.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
            {id === "requests" && requests.length > 0 ? <b>{requests.length}</b> : null}
          </button>
        ))}
      </div>
      {error ? <p className="ui-error">{error}</p> : null}
      {notice ? <p className="ui-toast">{notice}</p> : null}
      {tab === "labels" ? (
        <div className="ui-access-body">
          <div className="ui-access-scope">
            <div>
              <strong>Document scope</strong>
              <p>A public document is listed for the organization. It still opens only for people who are allowed.</p>
            </div>
            <div className="ui-segment" role="group" aria-label="Document visibility">
              <button type="button" aria-pressed={document.visibility !== "public"} disabled={pending} onClick={() => void run(async () => onDocument(await api<DocumentRow>(`/api/v1/documents/${document.documentId}/visibility`, session, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visibility: "private" }) })))}>
                Private
              </button>
              <button type="button" aria-pressed={document.visibility === "public"} disabled={pending} onClick={() => void run(async () => onDocument(await api<DocumentRow>(`/api/v1/documents/${document.documentId}/visibility`, session, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visibility: "public" }) })))}>
                Public
              </button>
            </div>
          </div>
          <div className="ui-access-grid">
            <article>
              <header>
                <strong>Always opened by</strong>
                <span>{document.audienceLabels.length} active</span>
              </header>
              <p>People with one of these labels can open this public document.</p>
              <ul>
                {document.audienceLabels.map((label) => (
                  <li key={label}>
                    #{label}
                    <button type="button" aria-label={`Remove ${label}`} disabled={pending} onClick={() => removeLabel("audience", label)}>
                      <Icon name="close" size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              <div>
                <input aria-label="Add an audience label" placeholder="Add a label" value={audienceInput} onChange={(event) => setAudienceInput(event.target.value)} />
                <button type="button" disabled={pending || !audienceInput.trim()} onClick={() => addLabel("audience")}>Add</button>
              </div>
            </article>
            <article className="is-blocked">
              <header>
                <strong>Blocked for</strong>
                <span>Priority override</span>
              </header>
              <p>A blocked label denies access even when the document was shared with that person.</p>
              <ul>
                {document.restrictedLabels.map((label) => (
                  <li key={label}>
                    #{label}
                    <button type="button" aria-label={`Remove blocked ${label}`} disabled={pending} onClick={() => removeLabel("blocked", label)}>
                      <Icon name="close" size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              <div>
                <input aria-label="Add a blocked label" placeholder="Add a restriction" value={blockedInput} onChange={(event) => setBlockedInput(event.target.value)} />
                <button type="button" disabled={pending || !blockedInput.trim()} onClick={() => addLabel("blocked")}>Block</button>
              </div>
            </article>
          </div>
        </div>
      ) : null}
      {tab === "people" ? (
        <div className="ui-access-body">
          <p>This share does not expire. It cannot give more access than the person's organization role.</p>
          <div className="ui-access-inline">
            <input aria-label="User id" placeholder="User id" value={personId} onChange={(event) => setPersonId(event.target.value)} />
            <select aria-label="Access for this user" value={personRole} onChange={(event) => setPersonRole(event.target.value)}>
              <option value="viewer">Can view</option>
              <option value="editor">Can edit</option>
            </select>
            <button type="button" className="ui-black" disabled={pending || !personId.trim()} onClick={() => {
              const userId = personId.trim();
              if (!userIdPattern.test(userId)) {
                setError("Enter the user id from their workspace.");
                return;
              }
              void run(async () => {
                await api(`/api/v1/documents/${document.documentId}/permissions`, session, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ user_id: userId, role: personRole }),
                });
                setPersonId("");
                await loadShares();
              });
            }}>Add share</button>
          </div>
          <ul className="ui-access-people">
            {people.length === 0 ? <li>No one else has a direct share.</li> : null}
            {people.map((person) => (
              <li key={person.userId}>
                <span className="ui-avatar">{initials(person.userId)}</span>
                <code>{person.userId}</code>
                <b>{person.role === "editor" ? "Can edit" : "Can view"}</b>
                <button type="button" disabled={pending} onClick={() => void run(async () => {
                  await api(`/api/v1/documents/${document.documentId}/permissions/${person.userId}`, session, { method: "DELETE" });
                  await loadShares();
                })}>Remove</button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {tab === "links" ? (
        <div className="ui-access-body">
          <p>A link requires sign-in in this organization, and the person must already be allowed to open the document. Setting a lifetime issues a new URL.</p>
          <div className="ui-access-grid">
            <article>
              <header><strong>Edit link</strong></header>
              <p>Opens the current version. Older edit links stop working when you save a version.</p>
              {currentEdit ? <p>{expiryLabel(currentEdit.expiresAt)}</p> : <p>No current edit link.</p>}
              {canManage && document.currentVersionId ? (
                <label>
                  Lifetime in hours: {editHours}
                  <input type="range" min={1} max={168} value={editHours} aria-label="Edit link lifetime in hours" onChange={(event) => setEditHours(Number(event.target.value))} />
                  <button type="button" disabled={pending} onClick={() => setLifetime(currentEdit?.versionId ?? document.currentVersionId!, "editor", editHours)}>Set edit link lifetime</button>
                </label>
              ) : null}
              {currentEdit ? (
                <div className="ui-access-inline">
                  <input readOnly aria-label="Edit link" value={shareUrl(currentEdit.token)} />
                  <button type="button" onClick={() => void copy(shareUrl(currentEdit.token))}>Copy</button>
                </div>
              ) : null}
            </article>
            <article>
              <header><strong>View link</strong></header>
              <p>Shows a picture of the current version.</p>
              {currentView ? <p>{expiryLabel(currentView.expiresAt)}</p> : <p>No current view link.</p>}
              {canManage && document.currentVersionId ? (
                <label>
                  Lifetime
                  <select aria-label="View link lifetime" value={viewHours} onChange={(event) => setViewHours(Number(event.target.value))}>
                    <option value={24}>24 hours</option>
                    <option value={72}>72 hours</option>
                    <option value={168}>168 hours</option>
                  </select>
                  <button type="button" disabled={pending} onClick={() => setLifetime(currentView?.versionId ?? document.currentVersionId!, "viewer", viewHours)}>Set view link lifetime</button>
                </label>
              ) : null}
              {currentView ? (
                <div className="ui-access-inline">
                  <input readOnly aria-label="View link" value={shareUrl(currentView.token)} />
                  <button type="button" onClick={() => void copy(shareUrl(currentView.token))}>Copy</button>
                </div>
              ) : null}
              {olderViews.map((link) => {
                const version = versions.find((item) => item.id === link.versionId);
                return (
                  <div key={link.shareId}>
                    <span>Version {version?.versionNumber ?? link.versionId} view link</span>
                    <span>{expiryLabel(link.expiresAt)}</span>
                    <input readOnly aria-label="Older view link" value={shareUrl(link.token)} />
                  </div>
                );
              })}
            </article>
          </div>
        </div>
      ) : null}
      {tab === "requests" ? (
        <div className="ui-access-body">
          {requests.length === 0 ? <p>No pending requests.</p> : null}
          <ul className="ui-access-people">
            {requests.map((request) => (
              <li key={request.requestId}>
                <span className="ui-avatar">{initials(request.userId)}</span>
                <code>{request.userId}</code>
                <b>Asked to {request.role === "editor" ? "edit" : "view"}</b>
                <button type="button" className="ui-black" disabled={pending} onClick={() => void run(async () => {
                  await api(`/api/v1/documents/${document.documentId}/access-requests/${request.requestId}`, session, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ approve: true }),
                  });
                  await loadShares();
                })}>Allow</button>
                <button type="button" disabled={pending} onClick={() => void run(async () => {
                  await api(`/api/v1/documents/${document.documentId}/access-requests/${request.requestId}`, session, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ approve: false }),
                  });
                  setRequests((current) => current.filter((item) => item.requestId !== request.requestId));
                })}>Deny</button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
