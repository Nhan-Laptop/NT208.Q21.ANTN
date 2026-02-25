"use client";

import { api, ApiError } from "@/lib/api";
import { User } from "@/lib/types";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

interface AuthContextValue {
  token: string | null;
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  registerAndLogin: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = "aira-token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) {
      api
        .me(stored)
        .then((profile) => {
          setToken(stored);
          setUser(profile);
        })
        .catch(() => {
          localStorage.removeItem(TOKEN_KEY);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const authToken = await api.login(email, password);
    const profile = await api.me(authToken);
    localStorage.setItem(TOKEN_KEY, authToken);
    setToken(authToken);
    setUser(profile);
  }, []);

  const registerAndLogin = useCallback(async (email: string, password: string, fullName?: string) => {
    try {
      await api.register(email, password, fullName);
    } catch (error) {
      // Show registration error to user instead of silently falling through
      if (error instanceof ApiError && error.status === 400) {
        toast.error(error.message || "Registration failed — email may already be in use.");
        throw error;
      }
      throw error;
    }
    await login(email, password);
  }, [login]);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    toast.success("Đã đăng xuất");
  }, []);

  const value = useMemo(
    () => ({ token, user, loading, login, registerAndLogin, logout }),
    [token, user, loading, login, registerAndLogin, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
