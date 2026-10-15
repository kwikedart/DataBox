import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { clearViewTokens, type Session } from "./api";
import { DocumentPage } from "./pages/DocumentPage";
import { LoginPage } from "./pages/LoginPage";
import { SharePage } from "./pages/SharePage";
import { WorkspacePage } from "./pages/WorkspacePage";

export function App() {
  const [session, setSession] = useState<Session | null>(null);

  function signOut() {
    clearViewTokens();
    setSession(null);
  }

  return (
    <Routes>
      <Route
        path="/share/:token"
        element={
          session ? (
            <SharePage session={session} />
          ) : (
            <LoginPage
              onSession={setSession}
              hint="Sign in before this link opens. The document checks who you are and which labels you have."
            />
          )
        }
      />
      <Route
        path="/documents/:documentId"
        element={session ? <DocumentPage session={session} /> : <LoginPage onSession={setSession} />}
      />
      <Route
        path="*"
        element={session ? <WorkspacePage session={session} onSignOut={signOut} /> : <LoginPage onSession={setSession} />}
      />
    </Routes>
  );
}
