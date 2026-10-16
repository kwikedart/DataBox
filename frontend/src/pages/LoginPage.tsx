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
const passwordMask = "••••••••";
const organizationIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const copy: Record<Mode, { title: string; subtitle: string; endpoint: string; submit: string; pending: string; callout: string }> = {
  "sign-in": {
    title: "Sign in to DataBox",
    subtitle: "Email and password for an existing account.",
    endpoint: "POST /api/auth/login",
    submit: "Sign in",
    pending: "Signing in",
    callout: "A failed sign-in shows the server message. The session token stays in memory for this tab.",
  },
  create: {
    title: "Create an organization",
    subtitle: "You become the owner. This form cannot choose a role.",
    endpoint: "POST /api/auth/signup",
    submit: "Create organization",
    pending: "Creating organization",
    callout: "A new password needs at least 12 characters. One address can create at most five accounts an hour.",
  },
  join: {
    title: "Join an organization",
    subtitle: "You join as a member. Paste the organization id from the workspace.",
    endpoint: "POST /api/auth/signup",
    submit: "Join organization",
    pending: "Joining organization",
    callout: "The organization id is on the workspace. This form does not send a role.",
  },
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
  const customHint = hint !== defaultHint;
  const subtitle = mode === "sign-in" && customHint ? hint : active.subtitle;
  const normalizedEmail = email.trim().toLowerCase();
  const passwordReady = password.length >= 12;
  const meter = Math.min(100, Math.round((password.length / 12) * 100));

  const preview =
    mode === "sign-in"
      ? { email: normalizedEmail, password: passwordMask }
      : mode === "create"
        ? { email: normalizedEmail, password: passwordMask, organization_name: organizationName.trim() }
        : { email: normalizedEmail, password: passwordMask, organization_id: organizationId.trim() };

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
      setError({ status: null, detail: "Confirm that the session token stays in memory." });
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
    <div className="vault">
      <header className="vault-bar">
        <div className="vault-brand">
          <span className="vault-mark">
            <Icon name="lock" />
          </span>
          <span className="vault-name">DataBox</span>
          <span className="vault-sep" aria-hidden="true">
            /
          </span>
          <span className="vault-code vault-crumb">Sign in</span>
        </div>
        <div className="vault-bar-side">
          <span className="vault-bar-note vault-code">
            <i className="vault-live" aria-hidden="true" /> Session stays in this tab
          </span>
          <span className="vault-pill">
            <Icon name="shield" />
            In-memory session
          </span>
        </div>
      </header>

      <main className="vault-main">
        <div className="vault-grid">
          <section className="vault-pitch">
            <p className="vault-kicker">
              <Icon name="shield" />
              Private document workspace
            </p>
            <h1 className="vault-title">Documents stay inside the organization.</h1>
            <p className="vault-lead">{customHint ? hint : "Sign in, start an organization, or join one with its id."}</p>
            <div className="vault-assurances">
              <article className="vault-assure">
                <span className="vault-assure-icon">
                  <Icon name="memory" />
                </span>
                <div>
                  <h2>Session token stays in memory</h2>
                  <p>
                    The sign-in token is kept in this tab and cleared on refresh or sign-out. It is not written to <code className="vault-mono">localStorage</code>.
                  </p>
                </div>
              </article>
              <article className="vault-assure">
                <span className="vault-assure-icon">
                  <Icon name="speed" />
                </span>
                <div>
                  <h2>Five new accounts an hour</h2>
                  <p>
                    One address can create at most five accounts an hour. A refusal is shown with the server’s own <code className="vault-mono">detail</code>.
                  </p>
                </div>
              </article>
              <article className="vault-assure">
                <span className="vault-assure-icon">
                  <Icon name="hash" />
                </span>
                <div>
                  <h2>Password hashed on the server</h2>
                  <p>A new password needs at least 12 characters. The server stores a scrypt hash. This form cannot choose a role.</p>
                </div>
              </article>
            </div>
            <div className="vault-facts">
              <p className="vault-facts-label">WHAT THIS PAGE ENFORCES</p>
              <span className="vault-chip">
                <i aria-hidden="true" /> In-memory session
              </span>
              <span className="vault-chip">
                <i aria-hidden="true" /> 5 accounts / hour
              </span>
              <span className="vault-chip">
                <i aria-hidden="true" /> Server-set role
              </span>
            </div>
          </section>

          <section className="vault-panel">
            <div className="vault-card">
              <div className="vault-card-head">
                <div className="vault-card-title-row">
                  <div>
                    <h2>{active.title}</h2>
                    <p className="vault-help">{subtitle}</p>
                  </div>
                  <code className="vault-code vault-endpoint">{active.endpoint}</code>
                </div>
                <div className="vault-tabs" role="group" aria-label="Account action">
                  {(
                    [
                      ["sign-in", "Sign in"],
                      ["create", "Create"],
                      ["join", "Join"],
                    ] as const
                  ).map(([value, label]) => (
                    <button key={value} type="button" className="vault-tab" aria-pressed={mode === value} onClick={() => switchMode(value)}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {error ? (
                <div className="vault-error" role="alert">
                  <Icon name="warning" />
                  <div>
                    <strong>{error.status ? `HTTP ${error.status}` : "Check this form"}</strong>
                    <p>{error.detail}</p>
                  </div>
                  <button type="button" className="vault-dismiss" aria-label="Dismiss error" onClick={() => setError(null)}>
                    <Icon name="close" />
                  </button>
                </div>
              ) : null}

              <div className="vault-callout">
                <Icon name="info" />
                <div>
                  <strong>How this request works</strong>
                  <p>{active.callout}</p>
                </div>
              </div>

              {mode === "create" ? (
                <div className="vault-role">
                  <span>
                    <Icon name="badge" /> You will be the owner of this organization
                  </span>
                  <b>ROLE: OWNER</b>
                </div>
              ) : null}
              {mode === "join" ? (
                <div className="vault-role">
                  <span>
                    <Icon name="badge" /> You will join as a member. This form does not send a role.
                  </span>
                  <b>ROLE: MEMBER</b>
                </div>
              ) : null}

              <form className="vault-form" method="post" action="#" onSubmit={(event) => void submit(event)} noValidate>
                {mode === "create" ? (
                  <div>
                    <label className="vault-label" htmlFor="organization-name">
                      Organization name <em>*</em>
                    </label>
                    <div className="vault-field">
                      <span className="vault-field-icon">
                        <Icon name="building" />
                      </span>
                      <input
                        id="organization-name"
                        className="vault-input"
                        name="organization_name"
                        value={organizationName}
                        maxLength={80}
                        autoComplete="organization"
                        placeholder="Organization name"
                        onChange={(event) => setOrganizationName(event.target.value)}
                        required
                      />
                    </div>
                    <p className="vault-help">This starts a new organization and makes you the owner.</p>
                  </div>
                ) : null}

                {mode === "join" ? (
                  <div>
                    <label className="vault-label" htmlFor="organization-id">
                      Organization id <em>*</em>
                    </label>
                    <div className="vault-field">
                      <span className="vault-field-icon">
                        <Icon name="tag" />
                      </span>
                      <input
                        id="organization-id"
                        className="vault-input vault-code"
                        name="organization_id"
                        value={organizationId}
                        maxLength={36}
                        autoComplete="off"
                        autoCapitalize="none"
                        spellCheck={false}
                        placeholder="Organization id from the workspace"
                        onChange={(event) => setOrganizationId(event.target.value)}
                        required
                      />
                    </div>
                    <p className="vault-help">Paste the id shown on the workspace. The server assigns member.</p>
                  </div>
                ) : null}

                <div>
                  <label className="vault-label" htmlFor="email">
                    Email <em>*</em>
                  </label>
                  <div className="vault-field">
                    <span className="vault-field-icon">
                      <Icon name="mail" />
                    </span>
                    <input
                      id="email"
                      className="vault-input"
                      name="email"
                      type="email"
                      inputMode="email"
                      autoComplete="username"
                      autoCapitalize="none"
                      spellCheck={false}
                      maxLength={320}
                      value={email}
                      placeholder="you@example.com"
                      onChange={(event) => setEmail(event.target.value)}
                      required
                    />
                  </div>
                </div>

                <div>
                  <div className="vault-label-row">
                    <label className="vault-label" htmlFor="password">
                      Password <em>*</em>
                    </label>
                    {creating ? (
                      <span className="vault-code">
                        {password.length} / 12
                      </span>
                    ) : null}
                  </div>
                  <div className="vault-field">
                    <span className="vault-field-icon">
                      <Icon name="key" />
                    </span>
                    <input
                      id="password"
                      className="vault-input has-action"
                      name="password"
                      type={showPassword ? "text" : "password"}
                      autoComplete={creating ? "new-password" : "current-password"}
                      maxLength={200}
                      minLength={creating ? 12 : undefined}
                      value={password}
                      placeholder={creating ? "At least 12 characters" : "Password"}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                    />
                    <button
                      type="button"
                      className="vault-reveal"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      aria-pressed={showPassword}
                      onClick={() => setShowPassword((current) => !current)}
                    >
                      <Icon name={showPassword ? "eyeOff" : "eye"} />
                    </button>
                  </div>
                  {creating ? (
                    <div>
                      <div className="vault-meter" aria-hidden="true">
                        <span className={passwordReady ? "is-met" : undefined} style={{ width: `${meter}%` }} />
                      </div>
                      <div className="vault-reqs">
                        <span className={passwordReady ? "vault-req is-met" : "vault-req is-short"}>
                          <Icon name={passwordReady ? "check" : "warning"} />
                          12+ characters
                        </span>
                        <span className="vault-req">
                          <Icon name="shield" />
                          Hashed with scrypt
                        </span>
                      </div>
                    </div>
                  ) : null}
                </div>

                <label className="vault-check">
                  <input
                    type="checkbox"
                    name="session-acknowledgment"
                    checked={acknowledged}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  <span>The session token stays in this tab’s memory and is cleared when you refresh or sign out.</span>
                </label>

                <button className="vault-submit" type="submit" disabled={pending}>
                  <Icon name="lock" />
                  {pending ? active.pending : active.submit}
                </button>
              </form>

              <div className="vault-card-foot">
                <Icon name="shield" />
                <span>Who can open a document is decided by the server. The password is hashed before it is stored.</span>
              </div>
            </div>

            <div className="vault-preview" aria-hidden="true">
              <div className="vault-preview-head">
                <span>
                  <Icon name="info" />
                  Request body
                </span>
                <code className="vault-code">{active.endpoint}</code>
              </div>
              <pre>{JSON.stringify(preview, null, 2)}</pre>
            </div>
          </section>
        </div>
      </main>

      <footer className="vault-foot">
        <span>DataBox</span>
        <span>Session token stays in memory until you refresh or sign out.</span>
      </footer>
    </div>
  );
}
