import { createContext, useContext, useState, ReactNode } from "react";

interface AuthState {
  username: string | null;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login: (username: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    username: null,
    isAuthenticated: document.cookie.includes("console_session="),
  });

  function login(username: string) {
    setState({ username, isAuthenticated: true });
  }

  function logout() {
    setState({ username: null, isAuthenticated: false });
  }

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
