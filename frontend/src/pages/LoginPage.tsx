import { FormEvent, useState } from "react";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import { ApiError, api, type Session } from "../api";
import { Icon } from "../icons";
import "../login.css";

type Mode = "sign-in" | "create" | "join";

const defaultHint = "Sign in to the private document workspace.";
const organizationIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const copy: Record<Mode, { submit: string; pending: string }> = {
  "sign-in": { submit: "Authorize session", pending: "Signing in" },
  create: { submit: "Create organization", pending: "Creating organization" },
  join: { submit: "Join organization", pending: "Joining organization" },
};

function emailIsValid(email: string): boolean {
  if (email.split("@").length !== 2 || /\s/.test(email)) return false;
  const [local, domain] = email.split("@");
  return Boolean(local) && Boolean(domain) && !local.startsWith(".");
}

function failure(err: unknown, fallback: string): { status: number | null; detail: string } {
  if (err instanceof ApiError) return { status: err.status, detail: err.message };
  if (err instanceof TypeError) return { status: null, detail: "The server could not be reached." };
  if (err instanceof Error && err.message) return { status: null, detail: err.message };
  return { status: null, detail: fallback };
}

export function LoginPage({ onSession, hint = defaultHint }: { onSession: (session: Session) => void; hint?: string }) {
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [organizationName, setOrganizationName] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [acknowledged, setAcknowledged] = useState(true);
  const [error, setError] = useState<{ status: number | null; detail: string } | null>(null);
  const [pending, setPending] = useState(false);
  const creating = mode !== "sign-in";
  const active = copy[mode];

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setShowPassword(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const nextEmail = email.trim().toLowerCase();
    if (!emailIsValid(nextEmail)) {
      setError({ status: null, detail: "Enter a valid email address." });
      return;
    }
    if (!password) {
      setError({ status: null, detail: "Enter your password." });
      return;
    }
    if (creating && password.length < 12) {
      setError({ status: null, detail: "Use at least 12 characters." });
      return;
    }
    if (password.length > 200) {
      setError({ status: null, detail: "Password must be 200 characters or fewer." });
      return;
    }
    if (mode === "create" && !organizationName.trim()) {
      setError({ status: null, detail: "Enter a name for the new organization." });
      return;
    }
    if (mode === "create" && organizationName.trim().length > 80) {
      setError({ status: null, detail: "Organization name must be 80 characters or fewer." });
      return;
    }
    if (mode === "join" && !organizationIdPattern.test(organizationId.trim())) {
      setError({ status: null, detail: "Enter the organization id from the workspace." });
      return;
    }
    if (!acknowledged) {
      setError({ status: null, detail: "Confirm that the session stays in this tab." });
      return;
    }

    setError(null);
    setPending(true);
    try {
      const result = await api<{ token: string; userId: string; organizationId: string; role: string }>(
        creating ? "/api/auth/signup" : "/api/auth/login",
        null,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            creating
              ? {
                  email: nextEmail,
                  password,
                  organization_name: mode === "create" ? organizationName.trim() : null,
                  organization_id: mode === "join" ? organizationId.trim() : null,
                }
              : { email: nextEmail, password },
          ),
        },
      );
      onSession({ ...result, email: nextEmail });
    } catch (err) {
      setError(failure(err, creating ? "Account was not created" : "Sign-in failed"));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="gate">
      <header className="gate-bar">
        <div className="gate-brand">
          <span className="gate-mark">
            <Icon name="shield" size={16} />
          </span>
          DataBox
        </div>
        <p>Session stays in this tab</p>
      </header>
      <main className="gate-main">
        <p className="gate-kicker">
          <Icon name="shield" size={14} />
          Organization sign-in
        </p>
        <h1>Access the document workspace</h1>
        <p className="gate-lead">{hint === defaultHint ? "Sign in, create an organization, or join one with its id. Labels and roles are checked by the server." : hint}</p>
        <section className="gate-card">
          <div className="gate-tabs" role="group" aria-label="Account action">
            {(
              [
                ["sign-in", "Sign in"],
                ["create", "Create org"],
                ["join", "Join org"],
              ] as const
            ).map(([value, label]) => (
              <button key={value} type="button" aria-pressed={mode === value} onClick={() => switchMode(value)}>
                {label}
              </button>
            ))}
          </div>
          {error ? (
            <p className="gate-error" role="alert">
              {error.status ? `HTTP ${error.status}. ` : ""}
              {error.detail}
            </p>
          ) : null}
          <form onSubmit={(event) => void submit(event)} noValidate>
            {mode === "create" ? (
              <label>
                Organization name
                <input value={organizationName} maxLength={80} autoComplete="organization" placeholder="Acme" onChange={(event) => setOrganizationName(event.target.value)} required />
              </label>
            ) : null}
            {mode === "join" ? (
              <label>
                Organization id
                <input value={organizationId} maxLength={36} autoComplete="off" spellCheck={false} placeholder="Organization id from the workspace" onChange={(event) => setOrganizationId(event.target.value)} required />
              </label>
            ) : null}
            <label>
              Corporate identity email
              <input id="email" type="email" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={320} value={email} placeholder="officer@domain.com" onChange={(event) => setEmail(event.target.value)} required />
            </label>
            <label>
              <span className="gate-label-row">
                Password
                <button type="button" onClick={() => setShowPassword((current) => !current)}>
                  {showPassword ? "Hide" : "Show"}
                </button>
              </span>
              <input id="password" type={showPassword ? "text" : "password"} autoComplete={creating ? "new-password" : "current-password"} maxLength={200} value={password} placeholder="Password" onChange={(event) => setPassword(event.target.value)} required />
            </label>
            <label className="gate-note">
              <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
              <span>
                <Icon name="info" size={16} />
                The session stays in this tab, including after a refresh. Signing out or closing the tab clears it. It is not written to local storage.
              </span>
            </label>
            <button className="gate-submit" type="submit" disabled={pending}>
              <Icon name="lock" size={16} />
              {pending ? active.pending : active.submit}
            </button>
          </form>
        </section>
      </main>
      <footer className="gate-foot">
        <span>The password is hashed on the server. This form cannot choose a role.</span>
      </footer>
    </div>
  );
}
