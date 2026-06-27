import { render, screen, waitFor } from "@testing-library/react";
import React, { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatCompletionResponse, Session } from "@/lib/types";

const mockListSessions = vi.fn();
const mockCreateSession = vi.fn();
const mockSendChat = vi.fn();
const mockListMessages = vi.fn();
const mockShowApiError = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    listSessions: (...args: unknown[]) => mockListSessions(...args),
    createSession: (...args: unknown[]) => mockCreateSession(...args),
    sendChat: (...args: unknown[]) => mockSendChat(...args),
    listMessages: (...args: unknown[]) => mockListMessages(...args),
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

function VerificationSendProbe() {
  const { state, setMode, sendMessage } = useChat();

  useEffect(() => {
    setMode("verification");
  }, [setMode]);

  useEffect(() => {
    if (state.mode !== "verification") return;
    void sendMessage("token", "Citation A\nCitation B");
  }, [sendMessage, state.mode]);

  return null;
}

describe("ChatProvider session mode sync", () => {
  beforeEach(() => {
    mockListSessions.mockReset();
    mockCreateSession.mockReset();
    mockSendChat.mockReset();
    mockListMessages.mockReset();
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

  it("creates the first session in verification mode when verification is selected", async () => {
    const createdSession: Session = {
      id: "session-verification",
      title: "Xác minh trích dẫn",
      mode: "verification",
      created_at: "2026-06-24T00:00:00Z",
      updated_at: "2026-06-24T00:00:00Z",
    };
    const chatResponse: ChatCompletionResponse = {
      session_id: createdSession.id,
      session: createdSession,
      user_message: {
        id: "user-1",
        session_id: createdSession.id,
        role: "user",
        message_type: "text",
        content: "Citation A\nCitation B",
        tool_results: null,
        created_at: "2026-06-24T00:00:00Z",
      },
      assistant_message: {
        id: "assistant-1",
        session_id: createdSession.id,
        role: "assistant",
        message_type: "citation_report",
        content: "Đã xác minh 2 trích dẫn.",
        tool_results: { type: "citation_report", results: [] },
        created_at: "2026-06-24T00:00:01Z",
      },
    };

    mockCreateSession.mockResolvedValue(createdSession);
    mockSendChat.mockResolvedValue(chatResponse);
    mockListMessages.mockResolvedValue([
      chatResponse.user_message,
      chatResponse.assistant_message,
    ]);

    render(
      <ChatProvider>
        <VerificationSendProbe />
      </ChatProvider>,
    );

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith(
        "token",
        "Trò chuyện mới",
        "verification",
      );
    });
    expect(mockSendChat).toHaveBeenCalledWith(
      "token",
      createdSession.id,
      "Citation A\nCitation B",
      "verification",
    );
  });
});
