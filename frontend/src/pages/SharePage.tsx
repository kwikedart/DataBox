import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, tokenExpiry, writeViewToken, type Session } from "../api";
import { CollaborativeText } from "../CollaborativeText";
import { connectCollaboration, type Presence } from "../collaboration";

type ShareLink = {
  documentId: string;
  permission: string;
  mimeType?: string;
  title?: string;
  expiresAt?: string;
};

export function SharePage({ session }: { session: Session }) {
  const { token = "" } = useParams();
  const [error, setError] = useState("");
  const [title, setTitle] = useState("Shared document");
  const [expiresAt, setExpiresAt] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const [status, setStatus] = useState("");
  const [presence, setPresence] = useState<Presence[]>([]);
  const [editor, setEditor] = useState<ReturnType<typeof connectCollaboration> | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    let connection: ReturnType<typeof connectCollaboration> | null = null;

    async function openShare() {
      const link = await api<ShareLink>(`/api/v1/share/${encodeURIComponent(token)}`, session);
      if (cancelled) return;
      setTitle(link.title || "Shared document");
      setExpiresAt(link.expiresAt || "");
      if (link.mimeType === "text/plain" && link.permission === "editor") {
        const opened = await api<{ ticket: string }>(
          `/api/v1/documents/${link.documentId}/collaboration-session`,
          session,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ share_token: token }),
          },
        );
        if (cancelled) return;
        connection = connectCollaboration({
          documentId: link.documentId,
          ticket: opened.ticket,
          name: session.email,
          onStatus: (role, editing) => {
            setCanEdit(editing);
            setStatus(editing ? "You can edit this document" : `You can view this document (${role})`);
          },
          onAnnotations: () => undefined,
          onPresence: setPresence,
          onSynced: () => {
            if (!cancelled) setReady(true);
          },
        });
        setEditor(connection);
        return;
      }
      const view = await api<{ token: string }>(`/api/v1/share/${encodeURIComponent(token)}/view-token`, session, {
        method: "POST",
      });
      if (tokenExpiry(view.token) <= Date.now()) throw new Error("Share link is not available");
      writeViewToken(link.documentId, view.token);
      let page = await fetch(`/api/v1/documents/${link.documentId}/pages/1`, {
        headers: { Authorization: `Bearer ${view.token}` },
      });
      if (page.status === 503) {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        page = await fetch(`/api/v1/documents/${link.documentId}/pages/1`, {
          headers: { Authorization: `Bearer ${view.token}` },
        });
      }
      if (!page.ok) throw new Error(page.status === 503 ? "Page is still rendering" : "Page is not available");
      const blob = await page.blob();
      objectUrl = URL.createObjectURL(blob);
      if (!cancelled) setPageUrl(objectUrl);
    }

    openShare().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "Share link is not available");
    });
    return () => {
      cancelled = true;
      connection?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [session, token]);

  const expiry = expiresAt ? new Date(expiresAt) : null;
  const expiryText =
    expiry && !Number.isNaN(expiry.getTime()) ? `This link expires ${expiry.toLocaleString()}.` : "";

  return (
    <main className="screen share-screen">
      <header className="topbar">
        <div>
          <p className="mark">DataBox</p>
          <h1>{title}</h1>
          <p className="hint">
            Signed in as {session.email}. {expiryText}{" "}
            {editor ? status || "Opening the shared document" : "This link shows a picture of the document and cannot edit it."}
          </p>
        </div>
      </header>
      {error ? <p className="error">{error}</p> : null}
      <section className="panel">
        {editor ? (
          <>
            <p className="muted">Present: {presence.map((person) => person.name).join(", ") || "nobody else"}</p>
            {ready ? <CollaborativeText doc={editor.doc} canEdit={canEdit} /> : <p className="hint">Opening the shared editor</p>}
          </>
        ) : null}
        {pageUrl ? <img className="page" alt="Shared document page" src={pageUrl} /> : null}
      </section>
    </main>
  );
}
