import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_BIBLIOGRAPHY_FILE_BYTES } from "@/lib/citation-file-import";
import type { Message, Session } from "@/lib/types";

let mockSearchMode: string | null = null;

const mockLoadMessages = vi.fn();
const mockSendMessage = vi.fn();
const mockSetMode = vi.fn();

const baseState: {
  activeSessionId: string | null;
  messages: Message[];
  isLoadingMessages: boolean;
  isLoadingSessions: boolean;
  isSending: boolean;
  mode: Session["mode"];
  sessions: Session[];
} = {
  activeSessionId: null,
  messages: [],
  isLoadingMessages: false,
  isLoadingSessions: false,
  isSending: false,
  mode: "verification",
  sessions: [],
};

const mockUseChat = vi.fn(() => ({
  state: baseState,
  loadMessages: mockLoadMessages,
  sendMessage: mockSendMessage,
  setMode: mockSetMode,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    token: "token-123",
  }),
}));

vi.mock("@/lib/chat-store", () => ({
  useChat: () => mockUseChat(),
}));

vi.mock("@/lib/useAutoScroll", () => ({
  useAutoScroll: () => ({ current: null }),
}));

vi.mock("@/lib/useFileUpload", () => ({
  useFileUpload: () => ({
    selectedFile: null,
    isUploading: false,
    fileInputRef: { current: null },
    onFileChange: vi.fn(),
    openFilePicker: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("@/components/topbar", () => ({
  ModeSelector: () => <div>mode-selector</div>,
  AIDetectionRulesPanel: () => <div>ai-rules-panel</div>,
}));

vi.mock("@/components/tool-results", () => ({
  ToolResultsRenderer: ({ messageType }: { messageType: string }) => (
    <div data-testid="tool-results-renderer">{messageType}</div>
  ),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (key: string) => (key === "mode" ? mockSearchMode : null),
  }),
}));

import { ChatView } from "@/components/chat-view";

function buildMessage(overrides: Partial<Message>): Message {
  return {
    id: "msg-1",
    session_id: "session-1",
    role: "assistant",
    message_type: "text",
    content: "",
    tool_results: null,
    created_at: "2026-06-24T00:00:00Z",
    ...overrides,
  };
}

describe("ChatView verification mode", () => {
  beforeEach(() => {
    mockSearchMode = null;
    mockLoadMessages.mockReset();
    mockSendMessage.mockReset();
    mockSetMode.mockReset();
    baseState.activeSessionId = null;
    baseState.messages = [];
    baseState.isLoadingMessages = false;
    baseState.isLoadingSessions = false;
    baseState.isSending = false;
    baseState.mode = "verification";
    baseState.sessions = [];
    mockUseChat.mockClear();
  });

  it("switches the first empty chat into verification mode from the query string", async () => {
    baseState.mode = "auto";
    mockSearchMode = "verification";

    render(<ChatView />);

    await waitFor(() => {
      expect(mockSetMode).toHaveBeenCalledWith("verification");
    });
  });

  it("loads a .txt bibliography file into the chat textarea", async () => {
    render(<ChatView />);

    const file = new File(
      ["First citation\nSecond citation\nThird citation"],
      "references.txt",
      { type: "text/plain" },
    );

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByRole("textbox")).toHaveValue(
        "First citation\nSecond citation\nThird citation",
      );
    });

    expect(screen.getByText("references.txt")).toBeInTheDocument();
    expect(screen.getByText(/~3 citation/i)).toBeInTheDocument();
  });

  it("loads a .bib bibliography file and preserves BibTeX blocks", async () => {
    render(<ChatView />);

    const bibContent = `@article{alpha,
  title = {Alpha},
  year = {2020}
}

@inproceedings{beta,
  title = {Beta},
  year = {2021}
}`;
    const file = new File([bibContent], "library.bib", {
      type: "application/x-bibtex",
    });

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toContain("@article{alpha");
      expect(textarea.value).toContain("@inproceedings{beta");
      expect(textarea.value).toContain("}\n\n@inproceedings");
    });
  });

  it("loads a .ris bibliography file and preserves TY/ER records", async () => {
    render(<ChatView />);

    const risContent = `TY  - JOUR
TI  - First title
ER  -

TY  - CONF
TI  - Second title
ER  -`;
    const file = new File([risContent], "records.ris", {
      type: "application/x-research-info-systems",
    });

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toContain("TY  - JOUR");
      expect(textarea.value).toContain("ER  -\n\nTY  - CONF");
    });
  });

  it("shows an inline error for unsupported bibliography files", async () => {
    render(<ChatView />);

    const file = new File(["not supported"], "references.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Unsupported file type/i);
    });
  });

  it("rejects oversized bibliography files", async () => {
    render(<ChatView />);

    const file = new File(
      ["a".repeat(MAX_BIBLIOGRAPHY_FILE_BYTES + 1)],
      "huge.txt",
      { type: "text/plain" },
    );

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/File is too large/i);
    });
  });

  it("clears imported bibliography state and textarea", async () => {
    render(<ChatView />);

    const file = new File(["First citation"], "references.txt", {
      type: "text/plain",
    });

    fireEvent.change(screen.getByLabelText(/Nạp file bibliography/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByRole("textbox")).toHaveValue("First citation");
    });

    fireEvent.click(screen.getByRole("button", { name: /Xóa nội dung/i }));

    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.queryByText("references.txt")).not.toBeInTheDocument();
  });

  it("blocks over-limit bibliography input instead of silently truncating", async () => {
    render(<ChatView />);

    const overLimitText = Array.from({ length: 4001 }, () => "word").join(" ");
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: overLimitText } });

    expect(
      screen.getByText(/vượt giới hạn chat cho một lượt xác minh/i),
    ).toBeInTheDocument();

    const submitButton = textarea.parentElement?.querySelector(
      'button[type="submit"]',
    ) as HTMLButtonElement | null;
    expect(submitButton).not.toBeNull();
    expect(submitButton).toBeDisabled();

    fireEvent.submit(textarea.closest("form") as HTMLFormElement);
    await waitFor(() => {
      expect(mockSendMessage).not.toHaveBeenCalled();
    });
  });

  it("renders citation reports in chat under the Xác minh trích dẫn label", () => {
    baseState.activeSessionId = "session-1";
    baseState.messages = [
      buildMessage({
        role: "user",
        content: "Verify these citations",
        message_type: "text",
      }),
      buildMessage({
        id: "msg-2",
        message_type: "citation_report",
        tool_results: {
          type: "citation_report",
          summary: {
            total_count: 1,
            verified_count: 1,
            review_count: 0,
            problem_count: 0,
            temporary_issue_count: 0,
            status_counts: { DOI_VERIFIED: 1 },
          },
          results: [],
        },
      }),
    ];

    render(<ChatView />);

    expect(screen.getByText(/Xác minh trích dẫn/i)).toBeInTheDocument();
    expect(screen.getByTestId("tool-results-renderer")).toHaveTextContent(
      "citation_report",
    );
    expect(screen.getByTestId("tool-results-renderer").parentElement).toHaveClass("w-full", "max-w-full");
    expect(screen.queryByText(/Citation Checker/i)).not.toBeInTheDocument();
  });
});
