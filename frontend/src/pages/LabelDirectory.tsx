import { FormEvent, useEffect, useState } from "react";
import { api, type Session } from "../api";

type LabelInfo = {
  labelId: string;
  name: string;
  tag: string;
  createdBy: string | null;
};

type Holder = {
  assignmentId: string;
  userId: string;
  assignedBy: string | null;
};

type Directory = {
  received: (LabelInfo & { assignmentId: string; assignedBy: string | null })[];
  created: (LabelInfo & { holders: Holder[] })[];
  catalog: LabelInfo[];
};

const tags = ["owner", "admin", "dev", "sales", "member", "contractor", "viewer"];
const userIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function token(value: string): string {
  return value.trim().toLowerCase();
}

export function LabelDirectory({ session }: { session: Session }) {
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [name, setName] = useState("");
  const [tag, setTag] = useState("dev");
  const [labelId, setLabelId] = useState("");
  const [personId, setPersonId] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const canManage = session.role === "owner" || session.role === "admin";

  async function refresh() {
    const payload = await api<Directory>("/api/v1/labels", session);
    setDirectory(payload);
    setLabelId((current) =>
      payload.catalog.some((label) => label.labelId === current) ? current : (payload.catalog[0]?.labelId ?? ""),
    );
  }

  useEffect(() => {
    refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : "Labels could not be loaded"));
  }, [session.token]);

  async function run(action: () => Promise<void>) {
    if (pending) return;
    setError("");
    setPending(true);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The label was not saved");
    } finally {
      setPending(false);
    }
  }

  function createLabel(event: FormEvent) {
    event.preventDefault();
    const nextName = token(name);
    const nextTag = token(tag);
    if (!nextName || !nextTag || /\s/.test(nextName) || /\s/.test(nextTag)) {
      setError("Use a short label and tag without spaces.");
      return;
    }
    void run(async () => {
      const created = await api<LabelInfo>("/api/v1/labels", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName, tag: nextTag }),
      });
      setName("");
      setLabelId(created.labelId);
    });
  }

  function assignLabel(event: FormEvent) {
    event.preventDefault();
    const userId = personId.trim();
    if (!labelId) {
      setError("Create a label first.");
      return;
    }
    if (!userIdPattern.test(userId)) {
      setError("Enter the user id from their workspace.");
      return;
    }
    if (userId === session.userId) {
      setError("Assign a label to someone else.");
      return;
    }
    void run(async () => {
      await api(`/api/v1/labels/${labelId}/assignments`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      setPersonId("");
    });
  }

  function canRemove(assignedBy: string | null): boolean {
    return canManage || assignedBy === session.userId;
  }

  return (
    <div className="label-directory">
      <h2>Labels</h2>
      <p className="hint">
        A tag such as dev or sales names the group. It does not change an organization role. You can give a label to another person in this organization, not to yourself.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <h3>On you</h3>
      <ul className="label-list">
        {directory && directory.received.length === 0 ? <li>No labels yet.</li> : null}
        {directory?.received.map((label) => (
          <li key={label.assignmentId}>
            <span>
              {label.name} <span className="pill">{label.tag}</span>
            </span>
            <span className="hint uid">From {label.assignedBy ?? "an earlier record"}</span>
            {canRemove(label.assignedBy) ? (
              <button
                type="button"
                className="secondary"
                disabled={pending}
                onClick={() => void run(() => api(`/api/v1/label-assignments/${label.assignmentId}`, session, { method: "DELETE" }))}
              >
                Remove
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      <h3>You created</h3>
      <ul className="label-list">
        {directory && directory.created.length === 0 ? <li>You have not created a label.</li> : null}
        {directory?.created.map((label) => (
          <li key={label.labelId}>
            <span>
              {label.name} <span className="pill">{label.tag}</span>
            </span>
            {label.holders.length === 0 ? <span className="hint">Not given to anyone yet.</span> : null}
            {label.holders.map((holder) => (
              <span key={holder.assignmentId} className="holder">
                <span className="hint uid">Given to {holder.userId}</span>
                {canRemove(holder.assignedBy) ? (
                  <button
                    type="button"
                    className="secondary"
                    disabled={pending}
                    onClick={() => void run(() => api(`/api/v1/label-assignments/${holder.assignmentId}`, session, { method: "DELETE" }))}
                  >
                    Remove
                  </button>
                ) : null}
              </span>
            ))}
          </li>
        ))}
      </ul>
      <form onSubmit={createLabel}>
        <label>
          New label
          <input value={name} maxLength={64} aria-label="New label" placeholder="sales" onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Tag
          <input value={tag} maxLength={64} aria-label="Label tag" list="label-tags" onChange={(event) => setTag(event.target.value)} />
        </label>
        <datalist id="label-tags">
          {tags.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
        <button type="submit" disabled={pending || !name.trim() || !tag.trim()}>
          Create label
        </button>
      </form>
      <form onSubmit={assignLabel}>
        <label>
          Label to give
          <select aria-label="Label to give" value={labelId} onChange={(event) => setLabelId(event.target.value)}>
            {directory?.catalog.length === 0 ? <option value="">No labels yet</option> : null}
            {directory?.catalog.map((label) => (
              <option key={label.labelId} value={label.labelId}>
                {label.name} ({label.tag})
              </option>
            ))}
          </select>
        </label>
        <label>
          User id
          <input
            value={personId}
            aria-label="User id for this label"
            placeholder="User id"
            spellCheck={false}
            autoCapitalize="none"
            onChange={(event) => setPersonId(event.target.value)}
          />
        </label>
        <button type="submit" className="secondary" disabled={pending || !labelId || !personId.trim()}>
          Give this label
        </button>
        {labelId && (canManage || directory?.catalog.find((label) => label.labelId === labelId)?.createdBy === session.userId) ? (
          <button
            type="button"
            className="secondary"
            disabled={pending}
            onClick={() => void run(() => api(`/api/v1/labels/${labelId}`, session, { method: "DELETE" }))}
          >
            Delete this label
          </button>
        ) : null}
      </form>
    </div>
  );
}
