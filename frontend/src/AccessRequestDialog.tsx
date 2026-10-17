import { useEffect, useState } from "react";
import { api, type DocumentRow, type Session } from "./api";
import { Icon } from "./icons";

type ReceivedLabel = { name: string; tag: string; assignedBy: string | null };

export function AccessRequestDialog({
  session,
  document,
  onClose,
  onRequested,
}: {
  session: Session;
  document: DocumentRow;
  onClose: () => void;
  onRequested: (role: "viewer" | "editor") => Promise<void>;
}) {
  const [role, setRole] = useState<"viewer" | "editor">(document.pendingRequest === "editor" ? "editor" : "viewer");
  const [note, setNote] = useState("");
  const [labels, setLabels] = useState<ReceivedLabel[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const mine = new Set(labels.map((label) => label.name));
  const missing = document.audienceLabels.filter((label) => !mine.has(label));

  useEffect(() => {
    let cancelled = false;
    api<{ received: ReceivedLabel[] }>("/api/v1/labels", session)
      .then((payload) => {
        if (!cancelled) setLabels(payload.received);
      })
      .catch(() => {
        if (!cancelled) setLabels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  async function submit() {
    setError("");
    setPending(true);
    try {
      await onRequested(role);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request was not sent");
    } finally {
      setPending(false);
    }
  }

  const shortId = document.documentId;
  const kind = document.mimeType === "text/plain" ? "Text" : "PDF";

  return (
    <div className="req-scrim" role="presentation" onMouseDown={onClose}>
      <section className="req-dialog" role="dialog" aria-modal="true" aria-labelledby="req-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="req-head">
          <span>
            <Icon name="shield" size={16} />
            Document inspector
          </span>
          <button type="button" aria-label="Close" onClick={onClose}>
            <Icon name="close" size={18} />
          </button>
        </header>
        <div className="req-grid">
          <div className="req-identity">
            <div className="req-id">
              <span className="req-docid">{shortId}</span>
              <span className="req-restricted">
                <i />
                Restricted access
              </span>
            </div>
            <h2 id="req-title">{document.title}</h2>
            <p className="req-meta">
              {document.visibility === "public" ? "Public" : "Private"} · {kind}
            </p>
            <div className="req-rule">
              <div className="req-rule-title">
                <Icon name="shield" size={14} />
                Access requirement
              </div>
              {document.audienceLabels.length > 0 ? (
                <p>
                  This document requires the{" "}
                  {document.audienceLabels.map((label) => (
                    <span className="req-tag" key={label}>
                      #{label}
                    </span>
                  ))}{" "}
                  label to open.
                </p>
              ) : (
                <p>No audience label is set. A direct share is required.</p>
              )}
              <div className="req-yours">
                <span>Your active labels:</span>
                {labels.length === 0 ? <em>none</em> : null}
                {labels.map((label) => (
                  <span className="req-tag mine" key={label.name}>
                    #{label.name}
                  </span>
                ))}
              </div>
              {missing.length > 0 ? (
                <p className="req-miss">
                  <Icon name="warning" size={14} />
                  Missing required label: {missing.map((label) => `#${label}`).join(", ")}
                </p>
              ) : null}
            </div>
            <p className="req-foot">
              {shortId} · {document.visibility === "public" ? "Listed for the organization" : "Private to people it is shared with"}
            </p>
          </div>
          <div className="req-form">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!document.pendingRequest) void submit();
              }}
            >
              <div className="req-form-head">
                <strong>Request document access</strong>
                <span>{document.pendingRequest ? "Pending review" : "Direct approval"}</span>
              </div>
              <p className="req-label">Requested access level</p>
              <div className="req-choices">
                <label className={role === "viewer" ? "on" : ""}>
                  <input type="radio" name="access" checked={role === "viewer"} disabled={Boolean(document.pendingRequest)} onChange={() => setRole("viewer")} />
                  <span>
                    <b>View only</b>
                    <small>Read and verify the document</small>
                  </span>
                </label>
                <label className={role === "editor" ? "on" : ""}>
                  <input type="radio" name="access" checked={role === "editor"} disabled={Boolean(document.pendingRequest)} onChange={() => setRole("editor")} />
                  <span>
                    <b>Edit access</b>
                    <small>Change the current version</small>
                  </span>
                </label>
              </div>
              <label className="req-note">
                Justification / business need
                <textarea value={note} rows={3} maxLength={500} placeholder="Why you need this document" disabled={Boolean(document.pendingRequest)} onChange={(event) => setNote(event.target.value)} />
              </label>
              {error ? <p className="req-miss">{error}</p> : null}
              {document.pendingRequest ? (
                <p className="req-hint">Asked to {document.pendingRequest === "editor" ? "edit" : "view"}. An owner or admin still has to approve it.</p>
              ) : (
                <>
                  <button type="submit" className="req-send" disabled={pending}>
                    <Icon name="chevron" size={14} />
                    {pending ? "Sending" : "Send access request"}
                  </button>
                  <p className="req-hint">An owner or admin reviews this request. The note stays on this screen.</p>
                </>
              )}
            </form>
          </div>
        </div>
      </section>
    </div>
  );
}
