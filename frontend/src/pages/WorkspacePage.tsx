import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type DocumentRow, type Session } from "../api";
import { Icon } from "../icons";
import { AccessRequestDialog } from "../AccessRequestDialog";
import { Shell, type ShellFolder } from "../shell";
import { LabelDirectory } from "./LabelDirectory";

type Folder = ShellFolder;
type Segment = "all" | "open" | "closed";

function accessLabel(document: DocumentRow, session: Session): { text: string; kind: "open" | "closed" | "wait" } {
  if (document.canOpen === false) {
    if (document.pendingRequest) {
      return { text: document.pendingRequest === "editor" ? "Asked to edit" : "Asked to view", kind: "wait" };
    }
    return { text: "Request needed", kind: "closed" };
  }
  if (document.createdBy === session.userId || session.role === "owner" || session.role === "admin") {
    return { text: "You can edit", kind: "open" };
  }
  if (session.role === "viewer") return { text: "You can view", kind: "open" };
  return { text: "You can open", kind: "open" };
}

export function WorkspacePage({ session, onSignOut }: { session: Session; onSignOut: () => void }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [documents, setDocuments] = useState<DocumentRow[] | null>(null);
  const [labelCount, setLabelCount] = useState(0);
  const [labelNames, setLabelNames] = useState<string[]>([]);
  const [folder, setFolder] = useState<Folder>("all");
  const [segment, setSegment] = useState<Segment>("all");
  const [query, setQuery] = useState("");
  const [labelFilter, setLabelFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [creating, setCreating] = useState(false);
  const [requestDoc, setRequestDoc] = useState<DocumentRow | null>(null);
  const [title, setTitle] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const data = await api<{ documents: DocumentRow[] }>("/api/v1/documents", session);
    setDocuments(data.documents);
  }

  useEffect(() => {
    refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load documents"));
    api<{ received: { name: string }[]; catalog: { name: string }[] }>("/api/v1/labels", session)
      .then((payload) => {
        setLabelCount(payload.received.length);
        const names = new Set<string>();
        for (const label of payload.catalog) names.add(label.name);
        setLabelNames([...names].sort());
      })
      .catch(() => {
        setLabelCount(0);
        setLabelNames([]);
      });
  }, [session.token]);

  useEffect(() => {
    const next = params.get("folder");
    if (next === "all" || next === "mine" || next === "shared" || next === "public" || next === "requests" || next === "labels") {
      setFolder(next);
    }
  }, [params]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (documents ?? []).filter((document) => {
      if (folder === "mine" && document.createdBy !== session.userId) return false;
      if (folder === "shared" && (!document.createdBy || document.createdBy === session.userId)) return false;
      if (folder === "public" && document.visibility === "private") return false;
      if (folder === "requests" && document.canOpen !== false) return false;
      if (segment === "open" && document.canOpen === false) return false;
      if (segment === "closed" && document.canOpen !== false) return false;
      if (needle && !`${document.title} ${document.documentId}`.toLowerCase().includes(needle)) return false;
      if (labelFilter) {
        const labels = [...(document.audienceLabels ?? []), ...(document.restrictedLabels ?? [])];
        if (!labels.includes(labelFilter)) return false;
      }
      return true;
    });
  }, [documents, folder, segment, query, labelFilter, session.userId]);

  const filterLabels = useMemo(() => {
    const names = new Set(labelNames);
    for (const document of documents ?? []) {
      for (const label of [...(document.audienceLabels ?? []), ...(document.restrictedLabels ?? [])]) names.add(label);
    }
    return [...names].sort();
  }, [documents, labelNames]);

  const selected = visible.find((document) => document.documentId === selectedId) ?? visible[0] ?? null;
  const requestCount = (documents ?? []).filter((document) => document.canOpen === false).length;
  const canManage = selected ? selected.createdBy === session.userId || session.role === "owner" || session.role === "admin" : false;

  function selectDocument(documentId: string) {
    setSelectedId(documentId);
    setInspectorOpen(true);
  }

  async function createDocument(event: FormEvent) {
    event.preventDefault();
    const nextTitle = title.trim();
    if (!nextTitle || pending) return;
    setError("");
    setPending(true);
    try {
      const created = await api<DocumentRow>("/api/v1/documents/text", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: nextTitle }),
      });
      setTitle("");
      setCreating(false);
      navigate(`/documents/${created.documentId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document was not created");
    } finally {
      setPending(false);
    }
  }

  async function requestAccess(documentId: string, role: "viewer" | "editor") {
    setError("");
    setPending(true);
    try {
      await api(`/api/v1/documents/${documentId}/access-requests`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request was not sent");
      throw err;
    } finally {
      setPending(false);
    }
  }

  return (
    <Shell
      session={session}
      onSignOut={onSignOut}
      folder={folder}
      onFolder={setFolder}
      counts={{ documents: documents?.length, requests: requestCount, labels: labelCount }}
      onCreate={() => setCreating(true)}
    >
      {folder === "labels" ? null : <div className="ui-title-row">
        <div>
          <div className="ui-kicker">
            <h1>Documents</h1>
            <span className="ui-live">Live directory</span>
          </div>
          <p className="ui-lead">Documents stay in this organization. A public document is listed for everyone here, and it opens only for people who are allowed.</p>
        </div>
        <button type="button" className="ui-black" onClick={() => setCreating(true)}>
          <Icon name="plus" size={16} />
          New text document
        </button>
      </div>}
      {error ? <p className="ui-error">{error}</p> : null}
      {folder === "labels" ? (
        <LabelDirectory
          session={session}
          documents={documents ?? []}
          onViewLabel={(name) => {
            setLabelFilter(name);
            setFolder("all");
          }}
        />
      ) : (
        <>
          <div className="ui-banner">
            <span>
              <Icon name="info" size={16} /> New text documents start private. PDFs open as a page preview.
            </span>
          </div>
          <div className="ui-filters">
            <label className="ui-search">
              <Icon name="search" size={16} />
              <input aria-label="Filter by title or keyword" placeholder="Filter title or keyword..." value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <div className="ui-segment" role="group" aria-label="Access filter">
              {(
                [
                  ["all", "All"],
                  ["open", "Active"],
                  ["closed", "Needs access"],
                ] as const
              ).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={segment === value} onClick={() => setSegment(value)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="ui-label-row">
            Filter by label:
            {filterLabels.map((name) => (
              <button key={name} type="button" className="ui-chip" aria-pressed={labelFilter === name} onClick={() => setLabelFilter(labelFilter === name ? "" : name)}>
                #{name}
              </button>
            ))}
          </div>
          {documents && visible.length === 0 ? (
            <div className="ui-empty">
              <h2>No documents found in this view</h2>
              <p>Nothing in this organization matches the current folder, search, or label filter.</p>
              <div className="ui-empty-actions">
                <button type="button" className="ui-black" onClick={() => setCreating(true)}>
                  <Icon name="plus" size={16} />
                  New text document
                </button>
                {labelFilter || query || segment !== "all" || folder !== "all" ? (
                  <button
                    type="button"
                    className="ui-ghost"
                    onClick={() => {
                      setLabelFilter("");
                      setQuery("");
                      setSegment("all");
                      setFolder("all");
                    }}
                  >
                    Clear filters
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
          <div className={selected && inspectorOpen ? "ui-split" : undefined}>
            <div className="ui-table-card">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th>Document title</th>
                    <th>Visibility</th>
                    <th>Access state</th>
                    <th>Security labels</th>
                    <th>Type</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {documents === null ? (
                    <tr>
                      <td colSpan={6}>Loading documents</td>
                    </tr>
                  ) : null}
                  {documents && visible.length === 0 ? (
                    <tr>
                      <td colSpan={6}>No documents in this view.</td>
                    </tr>
                  ) : null}
                  {visible.map((document) => {
                    const access = accessLabel(document, session);
                    return (
                      <tr
                        key={document.documentId}
                        aria-selected={selected?.documentId === document.documentId}
                        onClick={() => (document.canOpen === false ? setRequestDoc(document) : selectDocument(document.documentId))}
                      >
                        <td>
                          <div className="ui-row-title">
                            <Icon name={document.mimeType === "text/plain" ? "file" : "folder"} size={18} />
                            <span>
                              <strong>{document.title}</strong>
                              <small>
                                {document.documentId} · {document.mimeType === "text/plain" ? "Text" : "PDF"}
                              </small>
                            </span>
                          </div>
                        </td>
                        <td>
                          <span className="ui-state">
                            <Icon name={document.visibility === "private" ? "lock" : "globe"} size={14} />
                            {document.visibility === "private" ? "Private" : "Public"}
                          </span>
                        </td>
                        <td>
                          <span className={`ui-state ${access.kind}`}>
                            <i className="ui-dot" />
                            {access.text}
                          </span>
                        </td>
                        <td>
                          {(document.audienceLabels ?? []).map((label) => (
                            <button key={`a-${label}`} type="button" className="ui-chip good" onClick={() => setLabelFilter(label)}>
                              #{label}
                            </button>
                          ))}
                          {(document.restrictedLabels ?? []).map((label) => (
                            <button key={`b-${label}`} type="button" className="ui-chip bad" onClick={() => setLabelFilter(label)}>
                              #{label}
                            </button>
                          ))}
                          {(document.audienceLabels ?? []).length + (document.restrictedLabels ?? []).length === 0 ? <span className="ui-help">No restrictions</span> : null}
                        </td>
                        <td className="ui-version">{document.mimeType === "text/plain" ? "Text" : "PDF"}</td>
                        <td>
                          {document.canOpen === false ? (
                            <button type="button" className="ui-ghost" onClick={() => setRequestDoc(document)}>
                              Ask
                            </button>
                          ) : (
                            <button type="button" className="ui-open" aria-label={`Open ${document.title}`} onClick={() => navigate(`/documents/${document.documentId}`)}>
                              Open
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {selected && inspectorOpen ? (
              <aside className="ui-inspector" aria-label="Document inspector">
                <div className="ui-inspector-head">
                  <span>{selected.mimeType === "text/plain" ? "Text document" : "PDF"}</span>
                  <button type="button" aria-label="Close inspector" onClick={() => setInspectorOpen(false)}>
                    <Icon name="close" size={16} />
                  </button>
                </div>
                <h2>{selected.title}</h2>
                <p className="ui-help">{selected.documentId}</p>
                <div className="ui-meta">
                  <div>
                    <span>Your access</span>
                    <strong>{accessLabel(selected, session).text}</strong>
                  </div>
                  <div>
                    <span>Visibility</span>
                    <strong>{selected.visibility === "private" ? "Private" : "Public"}</strong>
                  </div>
                  <div>
                    <span>Created by</span>
                    <strong>{selected.createdBy === session.userId ? "You" : (selected.createdBy ?? "Unknown")}</strong>
                  </div>
                </div>
                <div className="ui-block">
                  <h3>Allowed labels</h3>
                  {(selected.audienceLabels ?? []).length === 0 ? <p className="ui-help">None</p> : null}
                  {(selected.audienceLabels ?? []).map((label) => (
                    <span key={label} className="ui-chip good">
                      #{label}
                    </span>
                  ))}
                </div>
                <div className="ui-block">
                  <h3>Blocked labels</h3>
                  {(selected.restrictedLabels ?? []).length === 0 ? <p className="ui-help">None</p> : null}
                  {(selected.restrictedLabels ?? []).map((label) => (
                    <span key={label} className="ui-chip bad">
                      #{label}
                    </span>
                  ))}
                </div>
                {selected.canOpen === false ? (
                  <button type="button" className="ui-black" onClick={() => setRequestDoc(selected)}>
                    {selected.pendingRequest ? "View request" : "Request access"}
                  </button>
                ) : null}
                {selected.canOpen !== false ? (
                  <button type="button" className="ui-black" onClick={() => navigate(`/documents/${selected.documentId}`)}>
                    Open document
                  </button>
                ) : null}
                {canManage ? (
                  <button type="button" className="ui-ghost" onClick={() => navigate(`/documents/${selected.documentId}#access`)}>
                    Share and permissions
                  </button>
                ) : null}
              </aside>
            ) : null}
          </div>
          )}
        </>
      )}
      {requestDoc ? (
        <AccessRequestDialog
          session={session}
          document={requestDoc}
          onClose={() => setRequestDoc(null)}
          onRequested={async (role) => {
            await requestAccess(requestDoc.documentId, role);
            setRequestDoc({ ...requestDoc, pendingRequest: role });
          }}
        />
      ) : null}
      {creating ? (
        <>
          <button type="button" className="ui-dialog-scrim" aria-label="Close new document" onClick={() => setCreating(false)} />
          <form className="ui-dialog" onSubmit={(event) => void createDocument(event)}>
            <h2>New text document</h2>
            <p className="ui-help">It starts private. You can make it public from the document.</p>
            <label>
              Title
              <input value={title} maxLength={255} autoFocus aria-label="Document title" onChange={(event) => setTitle(event.target.value)} />
            </label>
            <div className="ui-dialog-actions">
              <button type="button" className="ui-ghost" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button type="submit" className="ui-black" disabled={pending || !title.trim()}>
                {pending ? "Creating" : "Create"}
              </button>
            </div>
          </form>
        </>
      ) : null}
    </Shell>
  );
}
