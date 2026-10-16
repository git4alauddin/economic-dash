import { AuthProvider, useAuth } from "./auth/AuthProvider";
import DashboardScreen from "./components/DashboardScreen";
import SignInScreen from "./components/SignInScreen";

function SessionScreen() {
  const { session, snapshot } = useAuth();
  if (snapshot.phase !== "signed-in") return <SignInScreen busy={snapshot.phase === "signing-in"}
    message={snapshot.message} onSignIn={session.signIn} />;
  return <>
    <nav className="session-toolbar" aria-label="Dashboard session">
      <span>Signed in as <strong>{snapshot.user?.username}</strong></span>
      <div>
        <button type="button" disabled={snapshot.refreshing} onClick={() => { void session.refresh(); }}>{snapshot.refreshing ? "Updating…" : "Refresh data"}</button>
        <button type="button" onClick={session.signOut}>Sign out</button>
      </div>
    </nav>
    <p className="dashboard-feedback">{snapshot.dashboard.message}</p>
    <DashboardScreen view={snapshot.dashboard} readIndicator={session.readIndicator} />
  </>;
}

export default function App() { return <AuthProvider><SessionScreen /></AuthProvider>; }
