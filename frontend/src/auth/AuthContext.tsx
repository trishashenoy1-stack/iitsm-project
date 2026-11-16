import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, tokenStore } from "../api/client";
import type { Role, Session, User } from "../api/types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export const homeFor = (role: Role) =>
  ({ EMPLOYEE: "/employee", TECHNICIAN: "/technician/queue", ADMIN: "/admin" })[role];

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => tokenStore.get() !== null);

  useEffect(() => {
    if (!tokenStore.get()) return;
    api
      .me()
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  const start = useCallback((session: Session) => {
    tokenStore.set(session.token);
    setUser(session.user);
    return session.user;
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      signIn: (email, password) => api.login(email, password).then(start),
      register: (name, email, password) => api.register(name, email, password).then(start),
      signOut: () => {
        tokenStore.clear();
        queryClient.clear();
        setUser(null);
      },
    }),
    [user, loading, start, queryClient],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
