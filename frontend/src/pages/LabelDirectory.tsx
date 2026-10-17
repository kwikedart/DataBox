import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type DocumentRow, type Session } from "../api";
import { Icon } from "../icons";

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

const roleOrder = [
  { name: "Owner", tier: "Highest", note: "Can manage labels, shares, and every document in the organization." },
  { name: "Admin", tier: "Elevated", note: "Can manage labels and shares. A document share still cannot exceed this role." },
  { name: "Member", tier: "Standard", note: "Opens a document when it is shared or tagged with one of their labels." },
  { name: "Viewer", tier: "Read only", note: "Can be given view access. A share cannot grant more than the organization role allows." },
];

const userIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function token(value: string): string {
  return value.trim().toLowerCase();
}

function shortId(value: string | null): string {
  return value ?? "an earlier record";
}

export function LabelDirectory({
  session,
  documents,
  onViewLabel,
}: {
  session: Session;
  documents: DocumentRow[];
  onViewLabel: (name: string) => void;
}) {
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [personId, setPersonId] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const canManage = session.role === "owner" || session.role === "admin";

  async function refresh() {
    const payload = await api<Directory>("/api/v1/labels", session);
    setDirectory(payload);
    setSelectedId((current) =>
      payload.created.some((label) => label.labelId === current) ? current : (payload.created[0]?.labelId ?? payload.catalog[0]?.labelId ?? ""),
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

  const needle = query.trim().toLowerCase();
  const received = useMemo(
    () => (directory?.received ?? []).filter((label) => !needle || `${label.name} ${label.tag} ${label.assignedBy ?? ""}`.includes(needle)),
    [directory, needle],
  );
  const created = directory?.created ?? [];
  const selected = created.find((label) => label.labelId === selectedId) ?? created[0] ?? null;
  const holders = (selected?.holders ?? []).filter((holder) => !needle || holder.userId.includes(needle));

  function usage(labelName: string): number {
    return documents.filter((document) =>
      [...(document.audienceLabels ?? []), ...(document.restrictedLabels ?? [])].includes(labelName),
    ).length;
  }

  function createLabel(event: FormEvent) {
    event.preventDefault();
    const nextName = token(name);
    if (!nextName || /\s/.test(nextName)) {
      setError("Use a short label name without spaces.");
      return;
    }
    void run(async () => {
      const createdLabel = await api<LabelInfo>("/api/v1/labels", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      setName("");
      setCreating(false);
      setSelectedId(createdLabel.labelId);
    });
  }

  function assignLabel(event: FormEvent) {
    event.preventDefault();
    const userId = personId.trim();
    if (!selected) {
      setError("Create a label first.");
      return;
    }
    if (!userIdPattern.test(userId)) {
      setError("Enter the user id from their account menu.");
      return;
    }
    if (userId === session.userId) {
      setError("Assign a label to someone else.");
      return;
    }
    void run(async () => {
      await api(`/api/v1/labels/${selected.labelId}/assignments`, session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      setPersonId("");
    });
  }

  return (
    <div className="lab">
      <header className="lab-head">
        <div className="lab-title">
          <div>
            <h1>
              Organization labels and access tags
              <span className="lab-gov">Governance</span>
            </h1>
            <p>Any member can create a label and give it to someone else. A document uses those labels to allow or block access. An organization role still limits what a share can grant.</p>
          </div>
          <div className="lab-counts">
            <span><i className="blue" /> {received.length} labels on me</span>
            <span><i className="green" /> {created.length} created</span>
          </div>
        </div>
        <div className="lab-tools">
          <label className="lab-search">
            <Icon name="search" size={16} />
            <input aria-label="Search labels or members" placeholder="Search labels or members..." value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <button type="button" className="lab-black" onClick={() => setCreating((open) => !open)}>
            <Icon name="plus" size={16} />
            Create new org label
          </button>
        </div>
        {creating ? (
          <form className="lab-create" onSubmit={createLabel}>
            <input aria-label="New label" placeholder="Label name" value={name} maxLength={64} onChange={(event) => setName(event.target.value)} />
            <button type="submit" className="lab-black" disabled={pending || !name.trim()}>
              {pending ? "Creating" : "Create"}
            </button>
          </form>
        ) : null}
      </header>
      {error ? <p className="lab-error">{error}</p> : null}

      <section className="lab-section">
        <div className="lab-section-head">
          <h2>1. Labels assigned to me <span>({received.length} active)</span></h2>
          <p>Checked when a document opens</p>
        </div>
        {directory && received.length === 0 ? <p className="lab-empty">No labels are assigned to you.</p> : null}
        <div className="lab-cards">
          {received.map((label) => (
            <article key={label.assignmentId}>
              <div className="lab-card-top">
                <span className="lab-hash">#{label.name}</span>
                <span className="lab-active">Active</span>
              </div>
              <p>Granted by <strong>{shortId(label.assignedBy)}</strong> <span className="lab-role">[{label.tag}]</span></p>
              <div className="lab-card-foot">
                <span>Used by <strong>{usage(label.name)} documents</strong></span>
                <button type="button" onClick={() => onViewLabel(label.name)}>
                  View matching docs
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="lab-section">
        <div className="lab-section-head">
          <h2>2. Labels I created and assigned <span>({created.length} managed)</span></h2>
          <p>You can give these to another member and take them back</p>
        </div>
        {directory && created.length === 0 ? <p className="lab-empty">You have not created a label.</p> : null}
        {selected ? (
          <div className="lab-managed">
            <div className="lab-managed-head">
              <div className="lab-pills">
                {created.map((label) => (
                  <button key={label.labelId} type="button" className={label.labelId === selected.labelId ? "lab-hash on" : "lab-hash"} onClick={() => setSelectedId(label.labelId)}>
                    #{label.name}
                  </button>
                ))}
                <span className="lab-role">Created by you · [{selected.tag}]</span>
              </div>
              {canManage || selected.createdBy === session.userId ? (
                <button
                  type="button"
                  className="lab-revoke"
                  disabled={pending}
                  onClick={() => void run(() => api(`/api/v1/labels/${selected.labelId}`, session, { method: "DELETE" }))}
                >
                  Delete label
                </button>
              ) : null}
            </div>
            <form className="lab-grant" onSubmit={assignLabel}>
              <input
                aria-label={`User id for #${selected.name}`}
                placeholder="User id from their account menu"
                value={personId}
                spellCheck={false}
                autoCapitalize="none"
                onChange={(event) => setPersonId(event.target.value)}
              />
              <button type="submit" className="lab-blue" disabled={pending || !personId.trim()}>
                Grant to member
              </button>
            </form>
            <table>
              <thead>
                <tr>
                  <th>Assigned member</th>
                  <th>Tag</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {holders.length === 0 ? (
                  <tr>
                    <td colSpan={3}>Not given to anyone yet.</td>
                  </tr>
                ) : null}
                {holders.map((holder) => (
                  <tr key={holder.assignmentId}>
                    <td>
                      <span className="lab-avatar">{holder.userId.slice(0, 2).toUpperCase()}</span>
                      <code>{holder.userId}</code>
                    </td>
                    <td><span className="lab-role">[{selected.tag}]</span></td>
                    <td>
                      <button
                        type="button"
                        className="lab-revoke"
                        disabled={pending}
                        onClick={() => void run(() => api(`/api/v1/label-assignments/${holder.assignmentId}`, session, { method: "DELETE" }))}
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="lab-section">
        <div className="lab-section-head">
          <h2>3. Organization role order</h2>
          <p>A label cannot grant more than the person's organization role</p>
        </div>
        <div className="lab-hierarchy">
          <p className="lab-note">
            <Icon name="info" size={16} />
            A document share stays inside the person's organization role. Owner and admin can manage labels. Member and viewer only receive the access that role allows.
          </p>
          <div className="lab-chain">
            {roleOrder.map((role, index) => (
              <span key={role.name}>
                {index > 0 ? <span className="lab-arrow">›</span> : null}
                <b className={index === 0 ? "top" : ""}>[{role.name}]</b>
              </span>
            ))}
          </div>
          <div className="lab-tiers">
            {roleOrder.map((role) => (
              <article key={role.name}>
                <strong>[{role.name}]</strong>
                <span>{role.tier}</span>
                <p>{role.note}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
