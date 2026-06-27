import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Session } from "@/lib/types";

const mockLoadSessions = vi.fn();
const mockSelectSession = vi.fn();
const mockStartNewChat = vi.fn();
const mockDeleteSession = vi.fn();
const mockLogout = vi.fn();
const mockToggleTheme = vi.fn();

const sessions: Session[] = [
  {
    id: "session-1",
    title: "Xác minh bibliography",
    mode: "verification",
    created_at: "2026-06-24T00:00:00Z",
    updated_at: "2026-06-24T00:00:00Z",
  },
];

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    token: "token-123",
    user: {
      email: "user@example.com",
      role: "user",
    },
    logout: mockLogout,
  }),
}));

vi.mock("@/lib/chat-store", () => ({
  useChat: () => ({
    state: {
      sessions,
      activeSessionId: "session-1",
      isLoadingSessions: false,
    },
    loadSessions: mockLoadSessions,
    selectSession: mockSelectSession,
    startNewChat: mockStartNewChat,
    deleteSession: mockDeleteSession,
  }),
}));

vi.mock("@/lib/theme", () => ({
  useTheme: () => ({
    theme: "light",
    toggleTheme: mockToggleTheme,
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
}));

import { Sidebar } from "@/components/chat-shell";

describe("Sidebar", () => {
  beforeEach(() => {
    mockLoadSessions.mockReset();
    mockSelectSession.mockReset();
    mockStartNewChat.mockReset();
    mockDeleteSession.mockReset();
    mockLogout.mockReset();
    mockToggleTheme.mockReset();
  });

  it("does not expose a standalone Citation Checker entry", () => {
    render(<Sidebar />);

    expect(screen.getByRole("button", { name: /New Chat/i })).toBeInTheDocument();
    expect(screen.queryByText(/Citation Checker/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Xác minh bibliography/i)).toBeInTheDocument();
  });
});
