import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { ApiError, apiFetch, setUnauthorizedHandler } from "../../lib/http/client";

interface AuthState {
  username: string | null;
  isAuthenticated: boolean;
  isLoadingAuth: boolean;
}

interface AuthContextValue extends AuthState {
  login: () => Promise<void>;
  logout: () => void;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface MeResponse {
  username: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    username: null,
    isAuthenticated: false,
    isLoadingAuth: true,
  });

  const bootstrapFromMe = useCallback(async (suppressErrors = false) => {
    setState((prev) => ({ ...prev, isLoadingAuth: true }));
    try {
      const me = await apiFetch<MeResponse>("/api/console/auth/me");
      setState({
        username: me.username,
        isAuthenticated: true,
        isLoadingAuth: false,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({
          username: null,
          isAuthenticated: false,
          isLoadingAuth: false,
        });
        return;
      }
      setState({
        username: null,
        isAuthenticated: false,
        isLoadingAuth: false,
      });
      if (!suppressErrors) {
        throw error;
      }
    }
  }, []);

  useEffect(() => {
    void bootstrapFromMe(true);
  }, [bootstrapFromMe]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setState({
        username: null,
        isAuthenticated: false,
        isLoadingAuth: false,
      });
    });
    return () => {
      setUnauthorizedHandler(null);
    };
  }, []);

  const login = useCallback(async () => {
    await bootstrapFromMe();
  }, [bootstrapFromMe]);

  const logout = useCallback(() => {
    setState({
      username: null,
      isAuthenticated: false,
      isLoadingAuth: false,
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      login,
      logout,
      refreshAuth: bootstrapFromMe,
    }),
    [bootstrapFromMe, login, logout, state],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
