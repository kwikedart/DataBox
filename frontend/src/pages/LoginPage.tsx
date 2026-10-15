import { FormEvent, useState } from "react";
import { api, type Session } from "../api";

export function LoginPage({
  onSession,
  hint = "Sign in to the private document workspace.",
}: {
  onSession: (session: Session) => void;
  hint?: string;
}) {
  const [mode, setMode] = useState<"sign-in" | "create" | "join">("sign-in");
  const [email, setEmail] = useState("owner@localhost");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const creating = mode !== "sign-in";
      const result = await api<{ token: string; userId: string; organizationId: string; role: string }>(
        creating ? "/api/auth/signup" : "/api/auth/login",
        null,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            creating
              ? {
                  email,
                  password,
                  organization_name: mode === "create" ? organizationName.trim() : null,
                  organization_id: mode === "join" ? organizationId.trim() : null,
                }
              : { email, password },
          ),
        },
      );
      onSession({ ...result, email: email.trim().toLowerCase() });
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "sign-in" ? "Sign-in failed" : "Account was not created");
    }
  }

  const creating = mode !== "sign-in";

  return (
    <main>
      <h1>DataBox</h1>
      <p className="hint">
        {mode === "create"
          ? "This account starts a new organization. Share the organization id with the people who should join it."
          : mode === "join"
            ? "Join an organization with the id its owner gives you. You join as a member."
            : hint}
      </p>
      {error ? <p className="error">{error}</p> : null}
      <form onSubmit={submit}>
        <label>
          Email
          <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={creating ? "new-password" : "current-password"}
            minLength={creating ? 12 : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {mode === "create" ? (
          <label>
            Organization name
            <input value={organizationName} maxLength={80} onChange={(event) => setOrganizationName(event.target.value)} required />
          </label>
        ) : null}
        {mode === "join" ? (
          <label>
            Organization id
            <input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} required />
          </label>
        ) : null}
        {creating ? <p className="hint">Use at least 12 characters.</p> : null}
        <button type="submit">{mode === "create" ? "Create organization" : mode === "join" ? "Join organization" : "Sign in"}</button>
        {mode !== "create" ? (
          <button type="button" className="secondary" onClick={() => { setMode("create"); setError(""); setPassword(""); setEmail(""); }}>
            Create an organization
          </button>
        ) : null}
        {mode !== "join" ? (
          <button type="button" className="secondary" onClick={() => { setMode("join"); setError(""); setPassword(""); setEmail(""); }}>
            Join an organization
          </button>
        ) : null}
        {mode !== "sign-in" ? (
          <button type="button" className="secondary" onClick={() => { setMode("sign-in"); setError(""); setPassword(""); }}>
            Sign in instead
          </button>
        ) : null}
      </form>
    </main>
  );
}
