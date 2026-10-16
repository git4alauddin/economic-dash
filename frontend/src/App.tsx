import { AuthProvider, useAuth } from "./auth/AuthProvider";
import DashboardScreen from "./components/DashboardScreen";
import SignInScreen from "./components/SignInScreen";
import DataModeSwitch from "./components/DataModeSwitch";

function SessionScreen() {
  const { session, snapshot } = useAuth();
  if (snapshot.phase !== "signed-in") return <SignInScreen busy={snapshot.phase === "signing-in"}
    message={snapshot.message} onSignIn={session.signIn} />;
  const seed = snapshot.dataMode === "seed";
  return <div className="authenticated-page" data-data-mode={snapshot.dataMode}>
    <nav className="session-toolbar" aria-label="Dashboard session">
      <span>Signed in as <strong>{snapshot.user?.username}</strong></span>
      <div>
        <button type="button" disabled={seed || snapshot.refreshing} onClick={() => { void session.refresh(); }}>{seed ? "Seed data" : snapshot.refreshing ? "Updating…" : "Refresh data"}</button>
        <button type="button" onClick={session.signOut}>Sign out</button>
      </div>
    </nav>
    <p className={`dashboard-feedback${seed ? " seed-notice" : ""}`} role="status">{snapshot.dashboard.message}</p>
    <DashboardScreen view={snapshot.dashboard} readIndicator={seed ? undefined : session.readIndicator} refreshSequence={snapshot.refreshSequence}
      modeControl={<DataModeSwitch mode={snapshot.dataMode} onChange={session.setDataMode} />} />
  </div>;
}

export default function App() { return <AuthProvider><SessionScreen /></AuthProvider>; }
