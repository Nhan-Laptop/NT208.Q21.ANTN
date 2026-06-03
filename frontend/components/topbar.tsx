"use client";

import { useAuth } from "@/lib/auth";
import { api, showApiError } from "@/lib/api";
import { useChat } from "@/lib/chat-store";
import { AIDetectionRulePreferences, Session } from "@/lib/types";
import clsx from "clsx";
import {
  Brain,
  Check,
  ChevronDown,
  Loader2,
  PencilLine,
  RotateCcw,
  Save,
  X,
} from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

const MODE_LABELS: Record<Session["mode"], string> = {
  auto: "Tự nhận diện",
  general_qa: "Hỏi đáp học thuật",
  verification: "Xác minh trích dẫn",
  journal_match: "Gợi ý tạp chí",
  retraction: "Rà soát rút bài",
  ai_detection: "Nhận diện văn bản AI",
};

type RuleMode = "default" | "custom";
const AI_RULES_PANEL_VISIBILITY_KEY = "aira_ai_rules_panel_visible";

function getRuleMode(prefs: AIDetectionRulePreferences | null): RuleMode {
  return prefs?.rule_source === "user_custom_rules" ? "custom" : "default";
}

function ruleStatusLabel(prefs: AIDetectionRulePreferences | null): string {
  if (!prefs || prefs.rule_source === "default_app_rules") {
    return "Đang dùng quy tắc mặc định";
  }
  return "Đang dùng quy tắc tùy chỉnh";
}

function formatRulesDraft(phrases: string[] | null | undefined): string {
  return (phrases ?? []).join("\n");
}

function normalizeRuleLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}

function summarizeRuleSource(prefs: AIDetectionRulePreferences | null): string {
  if (!prefs || prefs.rule_source === "default_app_rules") {
    return "AIRA đang áp dụng bộ quy tắc mặc định cho toàn bộ phiên nghiên cứu hiện tại.";
  }
  return `${prefs.phrase_count} quy tắc tùy chỉnh đang được áp dụng cho lớp rule-based của AIRA.`;
}

function readRulesPanelVisibility(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(AI_RULES_PANEL_VISIBILITY_KEY) === "true";
}

function RuleModeOption({
  checked,
  description,
  disabled,
  label,
  name,
  onChange,
  value,
}: {
  checked: boolean;
  description: string;
  disabled: boolean;
  label: string;
  name: string;
  onChange: (value: RuleMode) => void;
  value: RuleMode;
}) {
  return (
    <label className="block">
      <input
        checked={checked}
        className="peer sr-only"
        disabled={disabled}
        name={name}
        onChange={() => onChange(value)}
        type="radio"
      />
      <div
        className={clsx(
          "rounded-2xl border px-4 py-3.5 transition-all peer-focus-visible:ring-2 peer-focus-visible:ring-accent/25 dark:peer-focus-visible:ring-dark-accent/30",
          checked
            ? "border-accent/45 bg-accent-light shadow-[0_0_0_1px_rgba(11,107,83,0.14)] dark:border-dark-accent/45 dark:bg-dark-accent/10 dark:shadow-[0_0_0_1px_rgba(16,185,129,0.18)]"
            : "border-border bg-surface/70 hover:border-border-hover hover:bg-bg-secondary/60 dark:border-white/8 dark:bg-white/[0.03] dark:hover:border-white/15 dark:hover:bg-white/[0.05]",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <div className="flex items-start gap-3">
          <div
            className={clsx(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors",
              checked
                ? "border-accent bg-accent text-white dark:border-dark-accent dark:bg-dark-accent dark:text-dark-bg-primary"
                : "border-border bg-transparent text-transparent dark:border-white/15",
            )}
            aria-hidden="true"
          >
            <Check size={12} strokeWidth={2.4} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-text-primary dark:text-dark-text-primary">
              {label}
            </div>
            <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
              {description}
            </p>
          </div>
        </div>
      </div>
    </label>
  );
}

export function ModeSelector() {
  const { state, setMode } = useChat();

  return (
    <div className="flex w-full items-center gap-2.5">
      <div className="relative inline-flex w-full items-center sm:w-auto">
        <select
          value={state.mode}
          onChange={(e) => setMode(e.target.value as Session["mode"])}
          className="min-w-0 appearance-none rounded-xl border border-border bg-surface px-3 py-2 pl-3 pr-9 text-sm text-text-primary shadow-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20 sm:min-w-[220px]"
          aria-label="Chế độ hỗ trợ nghiên cứu"
        >
          {Object.entries(MODE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary dark:text-dark-text-tertiary"
        />
      </div>
    </div>
  );
}

export function AIDetectionRulesPanel({
  chatInputRef,
}: {
  chatInputRef?: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const { state } = useChat();
  const { token } = useAuth();
  const [prefs, setPrefs] = useState<AIDetectionRulePreferences | null>(null);
  const [isLoadingPrefs, setIsLoadingPrefs] = useState(false);
  const [selectedMode, setSelectedMode] = useState<RuleMode>("default");
  const [draft, setDraft] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [showRulesPanel, setShowRulesPanel] = useState(readRulesPanelVisibility);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const prefsRequestRef = useRef<Promise<AIDetectionRulePreferences | null> | null>(null);

  const focusChatInput = useCallback(() => {
    if (!chatInputRef?.current) return;
    requestAnimationFrame(() => {
      chatInputRef.current?.focus();
      chatInputRef.current?.scrollIntoView?.({ block: "nearest" });
    });
  }, [chatInputRef]);

  const syncFromPrefs = useCallback((next: AIDetectionRulePreferences | null) => {
    setPrefs(next);
    setSelectedMode(getRuleMode(next));
    setDraft(formatRulesDraft(next?.phrases));
  }, []);

  const loadPrefs = useCallback(async (): Promise<AIDetectionRulePreferences | null> => {
    if (!token) return null;
    if (prefsRequestRef.current) {
      return prefsRequestRef.current;
    }

    const request = (async () => {
      setIsLoadingPrefs(true);
      try {
        const next = await api.getAiDetectionRules(token);
        syncFromPrefs(next);
        return next;
      } catch (error) {
        showApiError(error);
        return null;
      } finally {
        setIsLoadingPrefs(false);
        prefsRequestRef.current = null;
      }
    })();

    prefsRequestRef.current = request;
    return request;
  }, [syncFromPrefs, token]);

  useEffect(() => {
    if (state.mode !== "ai_detection" || !token) return;
    void loadPrefs();
  }, [loadPrefs, state.mode, token]);

  useEffect(() => {
    if (selectedMode === "custom" && showRulesPanel) {
      setStatusMessage((current) =>
        hasMeaningfulDraftChange(current, draft) ? "Bạn có thay đổi chưa lưu." : current,
      );
    }
  }, [draft, selectedMode, showRulesPanel]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(AI_RULES_PANEL_VISIBILITY_KEY, String(showRulesPanel));
  }, [showRulesPanel]);

  const persistedMode = getRuleMode(prefs);
  const normalizedDraft = normalizeRuleLines(draft);
  const normalizedSavedDraft = normalizeRuleLines(formatRulesDraft(prefs?.phrases));
  const hasTextChanges =
    formatRulesDraft(normalizedDraft) !== formatRulesDraft(normalizedSavedDraft);
  const hasUnsavedChanges =
    selectedMode !== persistedMode || (selectedMode === "custom" && hasTextChanges);
  const canSaveCustomRules =
    !isLoadingPrefs &&
    !isSaving &&
    selectedMode === "custom" &&
    normalizedDraft.length > 0 &&
    hasUnsavedChanges;

  const handleModeChange = (value: RuleMode) => {
    setSelectedMode(value);
    if (value === "custom") {
      setStatusMessage(
        normalizedDraft.length > 0 ? "Bạn có thể lưu quy tắc rồi tiếp tục nhập prompt." : null,
      );
      return;
    }
    if (persistedMode === "custom") {
      setStatusMessage("Bạn đang chuyển về bộ mặc định. Nhấn Khôi phục mặc định để áp dụng.");
    } else {
      setStatusMessage(null);
    }
  };

  const toggleRulesPanel = () => {
    setShowRulesPanel((current) => !current);
  };

  const saveRules = async () => {
    if (!token || isLoadingPrefs || isSaving) return;
    if (selectedMode === "custom" && normalizedDraft.length === 0) {
      setStatusMessage("Thêm ít nhất 1 quy tắc để lưu.");
      return;
    }
    if (!canSaveCustomRules) return;
    setIsSaving(true);
    try {
      const next = await api.updateAiDetectionRules(token, normalizedDraft);
      syncFromPrefs(next);
      setStatusMessage("Đã lưu quy tắc tùy chỉnh. Bạn có thể tiếp tục kiểm tra văn bản AI.");
      setShowRulesPanel(false);
      toast.success("Đã lưu quy tắc. Bạn có thể tiếp tục kiểm tra văn bản AI.");
      focusChatInput();
    } catch (error) {
      showApiError(error);
    } finally {
      setIsSaving(false);
    }
  };

  const clearRules = async () => {
    if (!token || isSaving || isLoadingPrefs) return;
    setIsSaving(true);
    try {
      const next = await api.clearAiDetectionRules(token);
      syncFromPrefs(next);
      setStatusMessage("Đã khôi phục quy tắc mặc định. Bạn có thể tiếp tục kiểm tra văn bản AI.");
      setShowRulesPanel(false);
      toast.success("Đã khôi phục quy tắc mặc định");
      focusChatInput();
    } catch (error) {
      showApiError(error);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section
      aria-labelledby="ai-rules-panel-title"
      className="ai-rules-panel flex flex-col rounded-2xl border border-border bg-surface/95 shadow-[0_20px_45px_rgba(15,23,42,0.08)] dark:border-white/8 dark:bg-[#171717] dark:shadow-[0_24px_60px_rgba(0,0,0,0.28)]"
    >
      <div
        className={clsx(
          "shrink-0 px-4 py-4 sm:px-5",
          showRulesPanel && "border-b border-border/80 dark:border-white/8",
        )}
      >
        <div className="ai-rules-compact-status flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-border bg-accent-light text-accent dark:border-white/10 dark:bg-dark-accent/10 dark:text-dark-accent">
              <Brain size={18} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2
                  id="ai-rules-panel-title"
                  className="text-base font-semibold text-text-primary dark:text-dark-text-primary"
                >
                  Quy tắc nhận diện văn bản AI
                </h2>
                <span className="inline-flex items-center rounded-full border border-border bg-bg-secondary/80 px-2.5 py-1 text-[11px] font-medium text-text-secondary dark:border-white/10 dark:bg-white/[0.05] dark:text-dark-text-secondary">
                  {isLoadingPrefs ? "Đang tải quy tắc..." : ruleStatusLabel(prefs)}
                </span>
              </div>
              <p className="mt-1 text-sm leading-6 text-text-secondary dark:text-dark-text-secondary">
                {isLoadingPrefs
                  ? "Đang đồng bộ thiết lập nhận diện AI từ tài khoản của bạn."
                  : summarizeRuleSource(prefs)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleRulesPanel}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary dark:focus:ring-dark-accent/20",
                showRulesPanel && "rules-close-button",
              )}
              aria-controls="ai-rules-panel-body"
              aria-expanded={showRulesPanel}
              aria-label={
                showRulesPanel ? "Ẩn quy tắc nhận diện AI" : "Chỉnh sửa quy tắc nhận diện AI"
              }
            >
              {showRulesPanel ? <X size={16} /> : <PencilLine size={14} />}
              <span>{showRulesPanel ? "Ẩn quy tắc" : "Chỉnh sửa quy tắc"}</span>
            </button>
          </div>
        </div>
      </div>

      {statusMessage && (
        <div className="shrink-0 border-b border-border/70 bg-bg-secondary/55 px-4 py-2.5 dark:border-white/8 dark:bg-white/[0.03] sm:px-5">
          <p className="text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
            {statusMessage}
          </p>
        </div>
      )}

      {showRulesPanel && (
        <div
          id="ai-rules-panel-body"
          className="ai-rules-body min-h-0 flex-1 px-4 py-4 pr-3 dark:[scrollbar-color:var(--color-dark-border)_transparent] sm:px-5 sm:py-5"
        >
          <div className="flex flex-col gap-4">
            <fieldset className="grid gap-3 sm:grid-cols-2">
              <legend className="sr-only">Chọn nguồn quy tắc nhận diện AI</legend>
              <RuleModeOption
                checked={selectedMode === "default"}
                description="Dùng bộ quy tắc mặc định của AIRA để giữ đánh giá nhất quán giữa các phiên nghiên cứu."
                disabled={isLoadingPrefs || isSaving}
                label="Dùng quy tắc mặc định"
                name="ai-rule-mode"
                onChange={handleModeChange}
                value="default"
              />
              <RuleModeOption
                checked={selectedMode === "custom"}
                description="Tùy chỉnh các tín hiệu rule-based để ưu tiên dấu hiệu phù hợp với bối cảnh tài liệu của bạn."
                disabled={isLoadingPrefs || isSaving}
                label="Dùng quy tắc tùy chỉnh"
                name="ai-rule-mode"
                onChange={handleModeChange}
                value="custom"
              />
            </fieldset>

            {selectedMode === "custom" ? (
              <div className="rounded-2xl border border-border bg-bg-secondary/35 p-4 dark:border-white/8 dark:bg-white/[0.03]">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                  <label
                    htmlFor="custom-ai-rules"
                    className="text-sm font-medium text-text-primary dark:text-dark-text-primary"
                  >
                    Danh sách quy tắc tùy chỉnh
                  </label>
                  <span className="text-xs text-text-secondary dark:text-dark-text-secondary">
                    {normalizedDraft.length > 0
                      ? `${normalizedDraft.length} quy tắc sẵn sàng lưu`
                      : "Thêm ít nhất 1 quy tắc để lưu"}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
                  Mỗi dòng là một quy tắc hoặc tín hiệu cần gắn cờ. AIRA vẫn giữ pipeline
                  ML hiện tại và dùng danh sách này cho lớp rule-based.
                </p>
                <textarea
                  id="custom-ai-rules"
                  value={draft}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    if (statusMessage?.includes("Đã lưu")) {
                      setStatusMessage("Bạn có thay đổi chưa lưu.");
                    }
                  }}
                  placeholder="Ví dụ: Flag text with repetitive sentence patterns, generic claims, or low citation density."
                  rows={7}
                  disabled={isLoadingPrefs || isSaving}
                  aria-busy={isLoadingPrefs}
                  className="mt-3 min-h-[140px] max-h-[240px] w-full resize-y overflow-y-auto rounded-2xl border border-border bg-surface px-3.5 py-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-tertiary focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:cursor-wait disabled:opacity-70 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
                />
                <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
                    {hasUnsavedChanges
                      ? "Bạn có thay đổi chưa lưu. Prompt bên dưới vẫn dùng được bình thường."
                      : "Các dòng trống sẽ bị bỏ qua và khoảng trắng dư sẽ được chuẩn hóa khi lưu."}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    {(isSaving || isLoadingPrefs) && (
                      <Loader2
                        size={14}
                        className="animate-spin text-text-tertiary dark:text-dark-text-tertiary"
                      />
                    )}
                    <button
                      type="button"
                      onClick={clearRules}
                      disabled={isSaving || isLoadingPrefs}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-50 dark:border-white/10 dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary dark:focus:ring-dark-accent/20"
                    >
                      <RotateCcw size={14} />
                      <span>Khôi phục mặc định</span>
                    </button>
                    <button
                      type="button"
                      onClick={saveRules}
                      disabled={isSaving || isLoadingPrefs}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-dark-accent dark:text-dark-bg-primary dark:hover:bg-dark-accent-hover dark:focus:ring-dark-accent/25"
                    >
                      <Save size={14} />
                      <span>Lưu quy tắc</span>
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-secondary/35 p-4 dark:border-white/8 dark:bg-white/[0.03] sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <p className="text-sm font-medium text-text-primary dark:text-dark-text-primary">
                    AIRA sẽ dùng bộ quy tắc mặc định của ứng dụng.
                  </p>
                  <p className="text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
                    {persistedMode === "custom"
                      ? "Bạn đang chuyển về bộ mặc định. Nhấn Khôi phục mặc định để bỏ danh sách tùy chỉnh đã lưu."
                      : "Phù hợp khi bạn muốn giữ tiêu chí đánh giá ổn định giữa các lần rà soát."}
                  </p>
                </div>
                {persistedMode === "custom" ? (
                  <button
                    type="button"
                    onClick={clearRules}
                    disabled={isSaving || isLoadingPrefs}
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-50 dark:border-white/10 dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary dark:focus:ring-dark-accent/20"
                  >
                    <RotateCcw size={14} />
                    <span>Khôi phục mặc định</span>
                  </button>
                ) : (
                  <span className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] font-medium text-text-secondary dark:border-white/10 dark:bg-white/[0.05] dark:text-dark-text-secondary">
                    Đang áp dụng
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function hasMeaningfulDraftChange(currentMessage: string | null, nextDraft: string): boolean {
  if (currentMessage?.includes("Đã lưu")) {
    return normalizeRuleLines(nextDraft).length > 0;
  }
  return false;
}
