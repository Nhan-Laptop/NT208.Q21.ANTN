import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIDetectionRulePreferences, Session } from "@/lib/types";

const mockGetAiDetectionRules = vi.fn();
const mockUpdateAiDetectionRules = vi.fn();
const mockClearAiDetectionRules = vi.fn();
const mockShowApiError = vi.fn();
const mockSetMode = vi.fn();
const mockToastSuccess = vi.fn();

let currentMode: Session["mode"] = "ai_detection";

function buildPrefs(phrases: string[]): AIDetectionRulePreferences {
  return {
    phrases,
    phrase_count: phrases.length,
    rule_source: phrases.length > 0 ? "user_custom_rules" : "default_app_rules",
    updated_at: phrases.length > 0 ? "2026-06-03T00:00:00Z" : null,
  };
}

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ token: "token" }),
}));

vi.mock("@/lib/chat-store", () => ({
  useChat: () => ({
    state: { mode: currentMode },
    setMode: mockSetMode,
  }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getAiDetectionRules: (...args: unknown[]) => mockGetAiDetectionRules(...args),
    updateAiDetectionRules: (...args: unknown[]) => mockUpdateAiDetectionRules(...args),
    clearAiDetectionRules: (...args: unknown[]) => mockClearAiDetectionRules(...args),
  },
  showApiError: (...args: unknown[]) => mockShowApiError(...args),
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
  },
}));

import { AIDetectionRulesPanel, ModeSelector } from "@/components/topbar";

describe("ModeSelector", () => {
  beforeEach(() => {
    currentMode = "ai_detection";
    mockSetMode.mockReset();
  });

  it("changes the selected research mode", () => {
    render(<ModeSelector />);

    fireEvent.change(screen.getByRole("combobox", { name: /Chế độ hỗ trợ nghiên cứu/i }), {
      target: { value: "verification" },
    });

    expect(mockSetMode).toHaveBeenCalledWith("verification");
  });
});

describe("AIDetectionRulesPanel", () => {
  beforeEach(() => {
    currentMode = "ai_detection";
    window.localStorage.clear();
    mockGetAiDetectionRules.mockReset();
    mockUpdateAiDetectionRules.mockReset();
    mockClearAiDetectionRules.mockReset();
    mockShowApiError.mockReset();
    mockToastSuccess.mockReset();
  });

  it("loads saved custom rules and shows the custom editor", async () => {
    mockGetAiDetectionRules.mockResolvedValue(buildPrefs(["rule one", "rule two"]));

    render(<AIDetectionRulesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Đang dùng quy tắc tùy chỉnh/i)).toBeInTheDocument();
    });

    expect(screen.queryByRole("textbox", { name: /Danh sách quy tắc tùy chỉnh/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i }));

    expect(screen.getByRole("textbox", { name: /Danh sách quy tắc tùy chỉnh/i })).toHaveValue(
      "rule one\nrule two",
    );
    expect(screen.getByRole("radio", { name: /Dùng quy tắc tùy chỉnh/i })).toBeChecked();
  });

  it("saves custom rules and updates the status badge", async () => {
    mockGetAiDetectionRules.mockResolvedValue(buildPrefs([]));
    mockUpdateAiDetectionRules.mockResolvedValue(buildPrefs(["custom rule"]));
    const chatInputRef = React.createRef<HTMLTextAreaElement>();

    render(
      <>
        <textarea ref={chatInputRef} />
        <AIDetectionRulesPanel chatInputRef={chatInputRef} />
      </>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Đang dùng quy tắc mặc định/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i }));
    fireEvent.click(screen.getByRole("radio", { name: /Dùng quy tắc tùy chỉnh/i }));
    fireEvent.change(screen.getByRole("textbox", { name: /Danh sách quy tắc tùy chỉnh/i }), {
      target: { value: "custom rule" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Lưu quy tắc/i }));

    await waitFor(() => {
      expect(mockUpdateAiDetectionRules).toHaveBeenCalledWith("token", ["custom rule"]);
    });
    expect(screen.getByText(/Đang dùng quy tắc tùy chỉnh/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Đã lưu quy tắc tùy chỉnh. Bạn có thể tiếp tục kiểm tra văn bản AI./i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i })).toBeInTheDocument();
    expect(window.localStorage.getItem("aira_ai_rules_panel_visible")).toBe("false");

    await waitFor(() => {
      expect(document.activeElement).toBe(chatInputRef.current);
    });
  });

  it("resets back to default rules", async () => {
    mockGetAiDetectionRules.mockResolvedValue(buildPrefs(["custom rule"]));
    mockClearAiDetectionRules.mockResolvedValue(buildPrefs([]));

    render(<AIDetectionRulesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Đang dùng quy tắc tùy chỉnh/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i }));
    fireEvent.click(screen.getByRole("radio", { name: /Dùng quy tắc mặc định/i }));
    fireEvent.click(screen.getByRole("button", { name: /Khôi phục mặc định/i }));

    await waitFor(() => {
      expect(mockClearAiDetectionRules).toHaveBeenCalledWith("token");
    });
    expect(screen.getByText(/Đang dùng quy tắc mặc định/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Đã khôi phục quy tắc mặc định. Bạn có thể tiếp tục kiểm tra văn bản AI./i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i })).toBeInTheDocument();
  });

  it("shows a validation hint when saving custom mode with an empty textarea", async () => {
    mockGetAiDetectionRules.mockResolvedValue(buildPrefs([]));

    render(<AIDetectionRulesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Đang dùng quy tắc mặc định/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i }));
    fireEvent.click(screen.getByRole("radio", { name: /Dùng quy tắc tùy chỉnh/i }));
    fireEvent.click(screen.getByRole("button", { name: /Lưu quy tắc/i }));

    expect(screen.getByText(/Thêm ít nhất 1 quy tắc để lưu./i)).toBeInTheDocument();
    expect(mockUpdateAiDetectionRules).not.toHaveBeenCalled();
  });

  it("persists the user's toggle choice for the rules panel", async () => {
    mockGetAiDetectionRules.mockResolvedValue(buildPrefs(["custom rule"]));

    render(<AIDetectionRulesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Đang dùng quy tắc tùy chỉnh/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Chỉnh sửa quy tắc/i }));

    expect(window.localStorage.getItem("aira_ai_rules_panel_visible")).toBe("true");
    expect(screen.getByRole("textbox", { name: /Danh sách quy tắc tùy chỉnh/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Ẩn quy tắc/i }));

    expect(window.localStorage.getItem("aira_ai_rules_panel_visible")).toBe("false");
    expect(screen.queryByRole("textbox", { name: /Danh sách quy tắc tùy chỉnh/i })).not.toBeInTheDocument();
  });
});
