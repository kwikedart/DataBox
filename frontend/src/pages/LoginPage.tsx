import { FormEvent, useState } from "react";
import { api, type Session } from "../api";

export function LoginPage({
  onSession,
  hint = "Sign in to the private document workspace.",
}: {
  onSession: (session: Session) => void;
  hint?: string;
}) {
  const [email, setEmail] = useState("owner@localhost");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await api<{ token: string; userId: string; organizationId: string; role: string }>(
        "/api/auth/login",
        null,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        },
      );
      onSession({ ...result, email });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    }
  }

  return (
    <main>
      <h1>DataBox</h1>
      <p className="hint">{hint}</p>
      {error ? <p className="error">{error}</p> : null}
      <form onSubmit={submit}>
        <label>
          Email
          <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button type="submit">Sign in</button>
      </form>
    </main>
  );
}
