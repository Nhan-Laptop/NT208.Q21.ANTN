"use client";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Loader2, Moon, Sparkles, Sun } from "lucide-react";
import { toast } from "sonner";
import clsx from "clsx";

export default function LoginPage() {
  const { token, loading: authLoading, login, registerAndLogin } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && token) {
      router.replace("/chat");
    }
  }, [token, authLoading, router]);

  useEffect(() => {
    const desired = new URLSearchParams(window.location.search).get("tab");
    if (desired === "register") {
      setTab("register");
    }
  }, []);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (tab === "register") {
        await registerAndLogin(email, password, fullName || undefined);
        toast.success("Account created successfully!");
      } else {
        await login(email, password);
        toast.success("Welcome back!");
      }
      router.replace("/chat");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError("Invalid email or password.");
        } else if (err.status === 429) {
          setError("Too many attempts. Please try again later.");
        } else if (err.status === 400 && tab === "register") {
          setError("Email already exists or invalid data.");
        } else {
          setError(err.message);
        }
      } else if (err instanceof TypeError && (err as TypeError).message.includes("fetch")) {
        setError("Cannot connect to server. Make sure backend is running.");
      } else {
        setError(tab === "register" ? "Registration failed." : "Login failed.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center bg-bg-primary dark:bg-dark-bg-primary p-6">
      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        className="fixed top-4 right-4 p-2 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
      >
        {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      <div className="w-full max-w-sm space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="flex items-center justify-center mb-3">
            <div className="w-12 h-12 rounded-xl bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center">
              <Sparkles className="w-6 h-6 text-accent dark:text-dark-accent" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-text-primary dark:text-dark-text-primary">
            {tab === "login" ? "Welcome back" : "Create account"}
          </h1>
          <p className="text-sm text-text-secondary dark:text-dark-text-secondary">
            {tab === "login"
              ? "Sign in to your AIRA workspace"
              : "Start your research journey with AIRA"}
          </p>
        </div>

        {/* Tab switch */}
        <div className="flex rounded-xl border border-border dark:border-dark-border bg-bg-secondary dark:bg-dark-bg-secondary p-1">
          <button
            type="button"
            onClick={() => setTab("login")}
            className={clsx(
              "flex-1 py-2 text-sm font-medium rounded-lg transition-all",
              tab === "login"
                ? "bg-surface dark:bg-dark-surface text-text-primary dark:text-dark-text-primary shadow-sm"
                : "text-text-secondary dark:text-dark-text-secondary hover:text-text-primary dark:hover:text-dark-text-primary",
            )}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => setTab("register")}
            className={clsx(
              "flex-1 py-2 text-sm font-medium rounded-lg transition-all",
              tab === "register"
                ? "bg-surface dark:bg-dark-surface text-text-primary dark:text-dark-text-primary shadow-sm"
                : "text-text-secondary dark:text-dark-text-secondary hover:text-text-primary dark:hover:text-dark-text-primary",
            )}
          >
            Sign Up
          </button>
        </div>

        {/* Form */}
        <form onSubmit={onSubmit} className="space-y-4">
          {tab === "register" && (
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-text-primary dark:text-dark-text-primary">
                Full Name
              </label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-surface text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent transition-colors"
                placeholder="Optional"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-text-primary dark:text-dark-text-primary">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-surface text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent transition-colors"
              placeholder="you@example.com"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-text-primary dark:text-dark-text-primary">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-surface text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent transition-colors"
              placeholder="Minimum 8 characters"
            />
          </div>

          {error && (
            <p className="text-sm text-danger">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-accent text-white text-sm font-medium hover:bg-accent-hover disabled:opacity-60 disabled:cursor-not-allowed dark:bg-dark-accent dark:hover:bg-dark-accent-hover transition-colors"
          >
            {loading && <Loader2 size={16} className="animate-spin" />}
            {loading
              ? tab === "register"
                ? "Creating account..."
                : "Signing in..."
              : tab === "register"
                ? "Create Account"
                : "Sign In"}
          </button>
        </form>
      </div>
    </main>
  );
}
