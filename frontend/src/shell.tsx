import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Session } from "./api";
import { Icon } from "./icons";
import "./ui.css";

export type ShellFolder = "all" | "mine" | "shared" | "public" | "requests" | "labels";

const nav: { id: ShellFolder; label: string; icon: "folder" | "person" | "users" | "globe" | "inbox" | "tag" }[] = [
  { id: "all", label: "All documents", icon: "folder" },
  { id: "mine", label: "Created by me", icon: "person" },
  { id: "shared", label: "Shared with me", icon: "users" },
  { id: "public", label: "Public", icon: "globe" },
  { id: "requests", label: "Access requests", icon: "inbox" },
  { id: "labels", label: "Org labels and tags", icon: "tag" },
];

export function roleLabel(role: string): string {
  if (role === "owner") return "Owner";
  if (role === "admin") return "Admin";
  if (role === "viewer") return "Viewer";
  return "Member";
}

export function initials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._-]+/).filter(Boolean);
  const letters = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
  return (letters || local.slice(0, 2) || "DB").toUpperCase();
}

export function Shell({
  session,
  onSignOut,
  folder,
  onFolder,
  counts,
  onCreate,
  notice,
  children,
}: {
  session: Session;
  onSignOut: () => void;
  folder?: ShellFolder;
  onFolder?: (folder: ShellFolder) => void;
  counts?: { documents?: number; requests?: number; labels?: number };
  onCreate?: () => void;
  notice?: string;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [copied, setCopied] = useState("");
  const orgShort = session.organizationId;

  async function copyText(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(`${label} copied.`);
      return;
    } catch {
      const field = document.createElement("textarea");
      field.value = value;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.left = "-9999px";
      document.body.appendChild(field);
      field.select();
      const copiedValue = document.execCommand("copy");
      field.remove();
      setCopied(copiedValue ? `${label} copied.` : "Copy was blocked by the browser.");
    }
  }

  function choose(next: ShellFolder) {
    setNavOpen(false);
    if (onFolder) onFolder(next);
    else navigate(next === "all" ? "/" : `/?folder=${next}`);
  }

  return (
    <div className="ui">
      <header className="ui-top">
        <div className="ui-brand">
          <button type="button" className="ui-icon ui-burger" aria-label="Open navigation" onClick={() => setNavOpen(true)}>
            <Icon name="menu" size={18} />
          </button>
          <Link to="/" className="ui-logo">
            <span className="ui-mark">
              <Icon name="shield" size={16} />
            </span>
            DataBox
          </Link>
          <span className="ui-org">
            <Icon name="building" size={14} />
            <span className="ui-org-id">ID: {orgShort}</span>
          </span>
          <nav className="ui-tabs" aria-label="Primary">
            <Link to="/" className="is-current">
              Workspaces
            </Link>
          </nav>
        </div>
        <div className="ui-top-side">
          <span className="ui-pill">
            <Icon name="badge" size={14} />
            {roleLabel(session.role)}
          </span>
          <button type="button" className="ui-pill" onClick={() => choose("labels")}>
            <Icon name="tag" size={14} />
            {counts?.labels ?? 0} labels on me
          </button>
          <button type="button" className="ui-ghost" onClick={() => void copyText(session.organizationId, "Organization id")}>
            <Icon name="copy" size={14} />
            Copy org id
          </button>
          <button type="button" className="ui-black" onClick={() => void copyText(session.userId, "User id")}>
            <Icon name="copy" size={14} />
            Copy user id
          </button>
          <button type="button" className="ui-account" aria-expanded={menuOpen} aria-label="Account" onClick={() => setMenuOpen((open) => !open)}>
            <span className="ui-avatar">{initials(session.email)}</span>
            <span>
              <strong>{session.email}</strong>
              <small>{roleLabel(session.role)}</small>
            </span>
          </button>
        </div>
      </header>
      {menuOpen ? (
        <>
          <button type="button" className="ui-scrim" aria-label="Close account menu" onClick={() => setMenuOpen(false)} />
          <div className="ui-menu">
            <p>{session.email}</p>
            <button type="button" className="ui-user-id" onClick={() => void copyText(session.userId, "User id")}>
              User id {session.userId}
            </button>
            <button type="button" className="ui-ghost" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </>
      ) : null}
      <div className="ui-body">
        {navOpen ? <button type="button" className="ui-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} /> : null}
        <aside className={navOpen ? "ui-side open" : "ui-side"}>
          <div>
            <div className="ui-side-org">
              <span className="ui-mark">
                <Icon name="shield" size={16} />
              </span>
              <div>
                <strong>Organization</strong>
                <button type="button" onClick={() => void copyText(session.organizationId, "Organization id")}>
                  {session.organizationId}
                </button>
              </div>
            </div>
            {onCreate ? (
              <button type="button" className="ui-black ui-wide" onClick={onCreate}>
                <Icon name="plus" size={16} />
                New text document
              </button>
            ) : null}
            <nav aria-label="Workspace">
              {nav.map((item) => (
                <button key={item.id} type="button" aria-current={folder === item.id ? "page" : undefined} onClick={() => choose(item.id)}>
                  <Icon name={item.icon} size={16} />
                  {item.label}
                  {item.id === "all" && counts?.documents !== undefined ? <span className="ui-count">{counts?.documents}</span> : null}
                  {item.id === "requests" && (counts?.requests ?? 0) > 0 ? <span className="ui-count warn">{counts?.requests}</span> : null}
                  {item.id === "labels" && counts?.labels !== undefined ? <span className="ui-count">{counts?.labels}</span> : null}
                </button>
              ))}
            </nav>
          </div>
          <p className="ui-side-note">Share a document with the user id from the account menu.</p>
        </aside>
        <div className="ui-main">
          {copied || notice ? <p className="ui-toast">{copied || notice}</p> : null}
          {children}
        </div>
      </div>
    </div>
  );
}
