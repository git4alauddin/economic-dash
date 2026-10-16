import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { createAuthSession } from "./session";

const AuthContext = createContext<ReturnType<typeof createAuthSession> | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session] = useState(() => createAuthSession());
  useEffect(() => {
    const check = () => session.checkExpiry();
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
      window.removeEventListener("pageshow", check);
      session.dispose();
    };
  }, [session]);
  return <AuthContext.Provider value={session}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const session = useContext(AuthContext);
  if (!session) throw new Error("AuthProvider is required.");
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  return { session, snapshot };
}
