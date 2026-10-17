import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { clearSession, readSession, writeSession, type Session } from "./api";
import { DocumentPage } from "./pages/DocumentPage";
import { LoginPage } from "./pages/LoginPage";
import { SharePage } from "./pages/SharePage";
import { WorkspacePage } from "./pages/WorkspacePage";

export function App() {
  const [session, setSession] = useState<Session | null>(() => readSession());

  function signIn(next: Session) {
    writeSession(next);
    setSession(next);
  }

  function signOut() {
    clearSession();
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
              onSession={signIn}
              hint="Sign in before this link opens. The document checks who you are and which labels you have."
            />
          )
        }
      />
      <Route
        path="/documents/:documentId"
        element={session ? <DocumentPage session={session} onSignOut={signOut} /> : <LoginPage onSession={signIn} />}
      />
      <Route
        path="*"
        element={session ? <WorkspacePage session={session} onSignOut={signOut} /> : <LoginPage onSession={signIn} />}
      />
    </Routes>
  );
}
