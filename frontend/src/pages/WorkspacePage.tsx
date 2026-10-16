import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type DocumentRow, type Session } from "../api";

export function WorkspacePage({ session, onSignOut }: { session: Session; onSignOut: () => void }) {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [myLabels, setMyLabels] = useState("");
  const canManage = session.role === "owner" || session.role === "admin";

  async function refresh() {
    const data = await api<{ documents: DocumentRow[] }>("/api/v1/documents", session);
    setDocuments(data.documents);
  }

  useEffect(() => {
    refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load documents"));
    if (!canManage) return;
    api<{ labels: string[] }>("/api/v1/membership-attributes", session)
      .then((payload) => setMyLabels(payload.labels.join(", ")))
      .catch(() => setMyLabels(""));
  }, [session.token]);

  async function saveMyLabels(event: FormEvent) {
    event.preventDefault();
    const labels = myLabels
      .split(",")
      .map((label) => label.trim().toLowerCase())
      .filter((label, index, all) => label && all.indexOf(label) === index)
      .slice(0, 32);
    setError("");
    try {
      const saved = await api<{ labels: string[] }>("/api/v1/membership-attributes", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: session.userId, labels }),
      });
      setMyLabels(saved.labels.join(", "));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Labels were not saved");
    }
  }

  async function requestAccess(documentId: string, role: "viewer" | "editor") {
    setError("");
    try {
      await api(`/api/v1/documents/${documentId}/access-requests`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request was not sent");
    }
  }

  async function createDocument(event: FormEvent) {
    event.preventDefault();
    const nextTitle = title.trim();
    if (!nextTitle) return;
    setError("");
    try {
      const created = await api<DocumentRow>("/api/v1/documents/text", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: nextTitle }),
      });
      setTitle("");
      navigate(`/documents/${created.documentId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document was not created");
    }
  }

  return (
    <main className="screen">
      <header className="topbar">
        <div>
          <p className="mark">DataBox</p>
          <h1>Workspace</h1>
          <p className="hint">
            Signed in as {session.email} ({session.role})
          </p>
        </div>
        <button type="button" className="secondary" onClick={onSignOut}>
          Sign out
        </button>
      </header>
      {error ? <p className="error">{error}</p> : null}
      <div className="split">
        <aside className="panel">
          <h2>This organization</h2>
          <label>
            Your user id
            <input readOnly value={session.userId} aria-label="Your user id" />
          </label>
          <label>
            Organization id
            <input readOnly value={session.organizationId} aria-label="Organization id" />
          </label>
          <p className="hint">People join this organization with that id. Share a document with a user id, or tag it with their label.</p>
          {canManage ? (
            <form onSubmit={(event) => void saveMyLabels(event)}>
              <label>
                My labels
                <input
                  value={myLabels}
                  aria-label="My labels"
                  placeholder="finance, legal"
                  onChange={(event) => setMyLabels(event.target.value)}
                />
              </label>
              <p className="hint">A public document opens for people who have one of these labels, and stays closed for people who have a blocked label.</p>
              <button type="submit">Save my labels</button>
            </form>
          ) : null}
        </aside>
        <div className="stack">
          <form className="panel" onSubmit={(event) => void createDocument(event)}>
            <label>
              New document
              <input value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <button type="submit" disabled={!title.trim()}>
              Create document
            </button>
          </form>
          <section className="panel">
            <h2>Documents</h2>
            <ul className="doc-list">
              {documents.length === 0 ? <li>No secure documents yet.</li> : null}
              {documents.map((document) => (
                <li key={document.documentId}>
                  <Link to={`/documents/${document.documentId}`}>{document.title}</Link>
                  <span className="pill">{document.visibility === "private" ? "Private" : "Public"}</span>
                  {document.canOpen === false ? (
                    document.pendingRequest ? (
                      <p className="hint">Asked for {document.pendingRequest === "editor" ? "edit" : "view"} access</p>
                    ) : (
                      <span className="actions">
                        <button type="button" className="secondary" onClick={() => void requestAccess(document.documentId, "viewer")}>
                          Ask to view
                        </button>
                        <button type="button" className="secondary" onClick={() => void requestAccess(document.documentId, "editor")}>
                          Ask to edit
                        </button>
                      </span>
                    )
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </main>
  );
}
