"use client";

import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat-store";
import { useTheme } from "@/lib/theme";
import {
  LogOut,
  MessageSquarePlus,
  Moon,
  Search,
  Shield,
  Sun,
  Trash2,
  MessageSquare,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";

export function Sidebar() {
  const { token, user, logout } = useAuth();
  const { state, loadSessions, selectSession, startNewChat, deleteSession } = useChat();
  const { theme, toggleTheme } = useTheme();
  const [filter, setFilter] = useState("");
  const filterRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (token) loadSessions(token);
  }, [token, loadSessions]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        filterRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const filtered = filter.trim()
    ? state.sessions.filter((s) =>
        s.title.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : state.sessions;

  return (
    <aside className="flex flex-col h-screen w-[280px] shrink-0 border-r border-border bg-surface dark:border-dark-border dark:bg-dark-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <span className="text-lg font-bold tracking-tight text-text-primary dark:text-dark-text-primary">
          AIRA
        </span>
        <button
          onClick={toggleTheme}
          className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
          title="Toggle theme"
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>

      {/* New Chat */}
      <div className="px-3 py-2">
        <button
          onClick={startNewChat}
          className="flex items-center gap-2.5 w-full px-3 py-2.5 rounded-xl border border-border bg-surface hover:bg-bg-secondary text-text-primary text-sm font-medium transition-all dark:border-dark-border dark:bg-dark-surface dark:hover:bg-dark-surface-hover dark:text-dark-text-primary"
        >
          <MessageSquarePlus size={18} />
          New Chat
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary dark:text-dark-text-tertiary"
          />
          <input
            ref={filterRef}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-bg-primary text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-bg-primary dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent transition-colors"
          />
        </div>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-3 space-y-0.5">
        {state.isLoadingSessions && (
          <p className="text-xs text-text-tertiary dark:text-dark-text-tertiary px-2 py-4 text-center">
            Loading...
          </p>
        )}
        {filtered.map((s) => {
          const active = state.activeSessionId === s.id;
          return (
            <div
              key={s.id}
              className={clsx(
                "group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors",
                active
                  ? "bg-accent-light text-accent dark:bg-dark-accent-light dark:text-dark-accent"
                  : "text-text-primary hover:bg-bg-secondary dark:text-dark-text-primary dark:hover:bg-dark-surface-hover",
              )}
              onClick={() => selectSession(s.id)}
            >
              <MessageSquare size={16} className="shrink-0 opacity-50" />
              <div className="flex-1 min-w-0">
                <div className="truncate text-sm font-medium">{s.title}</div>
                <div className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary capitalize">
                  {s.mode.replace("_", " ")}
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (token) deleteSession(token, s.id);
                }}
                className="hidden group-hover:flex items-center p-1 rounded text-text-tertiary hover:text-danger dark:text-dark-text-tertiary dark:hover:text-danger transition-colors"
                title="Delete"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
        {!state.isLoadingSessions && filtered.length === 0 && (
          <p className="text-xs text-text-tertiary dark:text-dark-text-tertiary text-center py-8">
            No conversations yet
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-border dark:border-dark-border p-3 space-y-2">
        {user?.role === "admin" && (
          <Link
            href="/admin"
            className="flex items-center gap-2.5 w-full px-3 py-2.5 rounded-xl border border-amber-300 bg-amber-50 text-amber-800 text-sm font-semibold hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/30 transition-colors"
          >
            <Shield size={16} />
            Admin Dashboard
          </Link>
        )}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center text-xs font-bold text-accent dark:text-dark-accent">
            {user?.email?.charAt(0).toUpperCase() ?? "?"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="truncate text-sm text-text-primary dark:text-dark-text-primary">
              {user?.email}
            </div>
            <div className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary capitalize">
              {user?.role}
            </div>
          </div>
          <button
            onClick={logout}
            className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-secondary hover:text-danger dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
            title="Logout"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}
