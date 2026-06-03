import { render, screen, waitFor } from "@testing-library/react";
import React, { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Session } from "@/lib/types";

const mockListSessions = vi.fn();
const mockShowApiError = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    listSessions: (...args: unknown[]) => mockListSessions(...args),
  },
  showApiError: (...args: unknown[]) => mockShowApiError(...args),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
  },
}));

import { ChatProvider, useChat } from "@/lib/chat-store";

function ModeProbe() {
  const { state, loadSessions, selectSession } = useChat();

  useEffect(() => {
    selectSession("session-ai");
    void loadSessions("token");
  }, [loadSessions, selectSession]);

  return <div data-testid="mode-value">{state.mode}</div>;
}

function DefaultModeProbe() {
  const { state } = useChat();
  return <div data-testid="mode-value">{state.mode}</div>;
}

describe("ChatProvider session mode sync", () => {
  beforeEach(() => {
    mockListSessions.mockReset();
    mockShowApiError.mockReset();
  });

  it("syncs mode from the active session after sessions load", async () => {
    const sessions: Session[] = [
      {
        id: "session-ai",
        title: "AI detection session",
        mode: "ai_detection",
        created_at: "2026-06-03T00:00:00Z",
        updated_at: "2026-06-03T00:00:00Z",
      },
    ];
    mockListSessions.mockResolvedValue(sessions);

    render(
      <ChatProvider>
        <ModeProbe />
      </ChatProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("mode-value")).toHaveTextContent("ai_detection");
    });
  });

  it("defaults new chat mode to auto", () => {
    render(
      <ChatProvider>
        <DefaultModeProbe />
      </ChatProvider>,
    );

    expect(screen.getByTestId("mode-value")).toHaveTextContent("auto");
  });
});
