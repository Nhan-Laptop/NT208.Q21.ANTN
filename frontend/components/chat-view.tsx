"use client";

import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat-store";
import { useAutoScroll } from "@/lib/useAutoScroll";
import { useFileUpload } from "@/lib/useFileUpload";
import { Message } from "@/lib/types";
import { AIDetectionRulesPanel, ModeSelector } from "@/components/topbar";
import { ToolResultsRenderer } from "@/components/tool-results";
import {
  ArrowUp,
  Bot,
  FileUp,
  Loader2,
  Paperclip,
  Sparkles,
  User,
  X,
} from "lucide-react";
import {
  FormEvent,
  KeyboardEvent,
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import clsx from "clsx";

const MESSAGE_TYPE_LABELS: Record<string, string> = {
  citation_report: "Xác minh trích dẫn",
  journal_list: "Gợi ý tạp chí",
  retraction_report: "Rà soát rút bài",
  pdf_summary: "Tóm tắt PDF",
  ai_writing_detection: "Nhận diện văn bản AI",
  grammar_report: "Rà soát ngữ pháp",
};

interface RoutingMeta {
  requested_mode?: string;
  resolved_label?: string;
  is_ambiguous?: boolean;
}

function extractRoutingMeta(toolResults: Message["tool_results"]): RoutingMeta | null {
  if (!toolResults || Array.isArray(toolResults)) return null;
  const meta = (toolResults as Record<string, unknown>).meta;
  if (!meta || typeof meta !== "object") return null;
  const routing = (meta as Record<string, unknown>).routing;
  if (!routing || typeof routing !== "object") return null;
  return routing as RoutingMeta;
}

/* ====================================================================
 * ChatView — main exported component
 * ==================================================================== */

export function ChatView() {
  const { token } = useAuth();
  const { state, loadMessages, sendMessage } = useChat();
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { activeSessionId, messages, isLoadingMessages, isSending } = state;

  // Auto-scroll
  const messagesEndRef = useAutoScroll([messages]);

  // File upload
  const reloadMessages = useCallback(() => {
    if (token && activeSessionId) loadMessages(token, activeSessionId);
  }, [token, activeSessionId, loadMessages]);

  const fileUpload = useFileUpload({
    token,
    sessionId: activeSessionId,
    onSuccess: reloadMessages,
  });

  // Load messages when session changes
  useEffect(() => {
    if (token && activeSessionId) loadMessages(token, activeSessionId);
  }, [token, activeSessionId, loadMessages]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || !token || isSending) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    await sendMessage(token, text);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isEmptyState = !activeSessionId && messages.length === 0;
  const isAutoMode = state.mode === "auto";
  const showAiRulesPanel = state.mode === "ai_detection";
  const emptyStateDescription = showAiRulesPanel
    ? "Dán đoạn văn, abstract hoặc tải tài liệu lên để AIRA rà soát tín hiệu do AI tạo theo bộ quy tắc bạn đã chọn."
    : isAutoMode
      ? "Mô tả nhu cầu của bạn, AIRA sẽ tự nhận diện nên dùng hỏi đáp, xác minh trích dẫn, gợi ý tạp chí, rà soát rút bài, kiểm tra AI hay ngữ pháp."
      : "Hỏi đáp từ dữ liệu học thuật đã lưu, xác minh trích dẫn, gợi ý tạp chí, hoặc rà soát tín hiệu rút bài.";
  const suggestionPrompts = showAiRulesPanel
    ? [
        "Kiểm tra đoạn abstract này có tín hiệu AI không?",
        "Rà soát văn phong AI trong phần mở đầu",
        "Đánh dấu các câu lặp cấu trúc trong đoạn này",
        "Phân tích văn bản AI từ tài liệu tải lên",
      ]
    : isAutoMode
      ? [
          "Verify DOI 10.1111/gcb.17128",
          "Gợi ý tạp chí cho manuscript này",
          "Kiểm tra DOI này có bị retract không",
          "Proofread đoạn abstract tiếng Anh này",
        ]
      : [
          "Xác minh một reference APA",
          "Gợi ý tạp chí cho manuscript",
          "Kiểm tra DOI có tín hiệu rút bài",
          "Nhận diện văn bản AI",
        ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border bg-surface/80 backdrop-blur-sm dark:border-dark-border dark:bg-dark-surface/80">
        <div className="mx-auto flex w-full max-w-3xl items-center px-4 py-3">
          <div className="flex w-full items-center gap-2">
            <ModeSelector />
          </div>
        </div>
      </div>

      {showAiRulesPanel && (
        <div className="shrink-0 border-b border-border/80 bg-surface/55 dark:border-white/8 dark:bg-[#121212]/85">
          <div className="mx-auto w-full max-w-3xl px-4 py-4">
            <AIDetectionRulesPanel chatInputRef={textareaRef} />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1">
        {isEmptyState ? (
          <div className="h-full overflow-y-auto">
            <div
              className={clsx(
                "mx-auto flex min-h-full max-w-3xl flex-col items-center justify-center px-4",
                showAiRulesPanel ? "py-8" : "py-6",
              )}
            >
              <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 dark:bg-dark-accent/10">
                <Sparkles className="h-7 w-7 text-accent dark:text-dark-accent" />
              </div>
              <h1 className="mb-2 text-center text-2xl font-semibold text-text-primary dark:text-dark-text-primary">
                Mình có thể hỗ trợ gì cho nghiên cứu của bạn?
              </h1>
              <p className="mb-6 max-w-xl text-center text-sm leading-6 text-text-secondary dark:text-dark-text-secondary">
                {emptyStateDescription}
              </p>
              <div className="flex max-w-2xl flex-wrap justify-center gap-2">
                {suggestionPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => {
                      setInput(prompt);
                      textareaRef.current?.focus();
                    }}
                    className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover dark:hover:text-dark-text-primary"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-1 px-4 py-6">
            {isLoadingMessages && (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-text-tertiary dark:text-dark-text-tertiary" />
              </div>
            )}
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {isSending && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
          </div>
        )}
      </div>

      <InputArea
        input={input}
        setInput={setInput}
        isSending={isSending}
        textareaRef={textareaRef}
        onSubmit={handleSubmit}
        onKeyDown={handleKeyDown}
        fileUpload={fileUpload}
        showAttach={!!activeSessionId}
      />
    </div>
  );
}

/* ====================================================================
 * TypingIndicator
 * ==================================================================== */

function TypingIndicator() {
  return (
    <div className="flex items-start gap-3 py-4">
      <div className="w-7 h-7 rounded-full bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center shrink-0">
        <Bot size={15} className="text-accent dark:text-dark-accent" />
      </div>
      <div className="flex items-center gap-2 pt-1">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-text-tertiary dark:bg-dark-text-tertiary animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-text-tertiary dark:bg-dark-text-tertiary animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-text-tertiary dark:bg-dark-text-tertiary animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

/* ====================================================================
 * InputArea
 * ==================================================================== */

interface InputAreaProps {
  input: string;
  setInput: (v: string) => void;
  isSending: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onSubmit: (e?: FormEvent) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  fileUpload: ReturnType<typeof useFileUpload>;
  showAttach: boolean;
}

function InputArea({
  input,
  setInput,
  isSending,
  textareaRef,
  onSubmit,
  onKeyDown,
  fileUpload,
  showAttach,
}: InputAreaProps) {
  const { selectedFile, isUploading, fileInputRef, onFileChange, openFilePicker, reset } =
    fileUpload;

  return (
    <div className="shrink-0 border-t border-border bg-surface/80 px-4 py-3 backdrop-blur-sm dark:border-dark-border dark:bg-dark-surface/80">
      <div className="max-w-3xl mx-auto">
        {/* File preview */}
        {selectedFile && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-lg bg-bg-secondary dark:bg-dark-bg-secondary text-sm">
            <FileUp size={14} className="text-text-tertiary dark:text-dark-text-tertiary" />
            <span className="truncate text-text-secondary dark:text-dark-text-secondary">
              {selectedFile.name}
            </span>
            {isUploading && (
              <Loader2 size={14} className="animate-spin text-accent dark:text-dark-accent" />
            )}
            <button
              onClick={() => reset()}
              className="ml-auto text-text-tertiary hover:text-text-primary dark:text-dark-text-tertiary dark:hover:text-dark-text-primary"
            >
              <X size={14} />
            </button>
          </div>
        )}

        <form onSubmit={onSubmit} className="flex items-end gap-2">
          {showAttach && (
            <>
              <input
                ref={fileInputRef as React.RefObject<HTMLInputElement>}
                type="file"
                className="hidden"
                onChange={onFileChange}
                accept=".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg"
              />
              <button
                type="button"
                onClick={openFilePicker}
                disabled={isUploading}
                className="p-2 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-secondary dark:text-dark-text-tertiary dark:hover:text-dark-text-primary dark:hover:bg-dark-surface-hover transition-colors disabled:opacity-50"
                title="Đính kèm tệp"
                aria-label="Đính kèm tệp"
              >
                <Paperclip size={18} />
              </button>
            </>
          )}

          <div className="flex-1 relative">
            <textarea
              ref={textareaRef as React.RefObject<HTMLTextAreaElement>}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Nhập câu hỏi, DOI, trích dẫn hoặc nội dung manuscript..."
              rows={1}
              className="w-full resize-none rounded-xl border border-border bg-bg-primary px-4 py-3 pr-12 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-bg-primary dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent transition-colors"
              style={{ maxHeight: 200 }}
            />
            <button
              type="submit"
              disabled={!input.trim() || isSending}
              className={clsx(
                "absolute right-2 bottom-2 p-1.5 rounded-lg transition-all",
                input.trim() && !isSending
                  ? "bg-accent text-white hover:bg-accent-hover dark:bg-dark-accent dark:hover:bg-dark-accent-hover"
                  : "bg-border/50 text-text-tertiary dark:bg-dark-border/50 dark:text-dark-text-tertiary cursor-not-allowed",
              )}
            >
              {isSending ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
            </button>
          </div>
        </form>

        <div className="flex items-center justify-end mt-2">
          <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            Shift+Enter để xuống dòng
          </span>
        </div>
      </div>
    </div>
  );
}

/* ====================================================================
 * MessageBubble — smart rendering via ToolResultsRenderer
 * ==================================================================== */

const MessageBubble = memo(function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isFileUpload = message.message_type === "file_upload";
  const routingMeta = extractRoutingMeta(message.tool_results);
  const routingBadge =
    !isUser && routingMeta?.requested_mode === "auto"
      ? routingMeta.is_ambiguous
        ? "Cần làm rõ tính năng"
        : routingMeta.resolved_label
          ? `Đã nhận diện: ${routingMeta.resolved_label}`
          : null
      : null;

  // System file-upload messages get a clean card, not a chat bubble
  if (isSystem && isFileUpload) {
    return (
      <div className="py-2 flex justify-center">
        <ToolResultsRenderer
          messageType={message.message_type}
          content={message.content}
          toolResults={message.tool_results}
        />
      </div>
    );
  }

  // Determine if this is a tool-result message (assistant with structured data)
  const hasToolResults = !!message.tool_results;

  return (
    <div className={clsx("flex items-start gap-3 py-4", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={clsx(
          "w-7 h-7 rounded-full flex items-center justify-center shrink-0",
          isUser ? "bg-accent text-white dark:bg-dark-accent" : "bg-accent/10 dark:bg-dark-accent/10",
        )}
      >
        {isUser ? (
          <User size={15} />
        ) : (
          <Bot size={15} className="text-accent dark:text-dark-accent" />
        )}
      </div>

      {/* Content */}
      <div className={clsx("flex-1 min-w-0", isUser && "text-right")}>
        <div
          className={clsx(
            "inline-block max-w-full rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            isUser
              ? "bg-accent text-white dark:bg-dark-accent rounded-tr-md"
              : "bg-bg-secondary dark:bg-dark-bg-secondary text-text-primary dark:text-dark-text-primary rounded-tl-md",
          )}
        >
          {/* Text content — skip for system/file_upload junk */}
          {message.content && !isFileUpload && (
            <p className="whitespace-pre-wrap break-words m-0">{message.content}</p>
          )}

          {/* Rich tool results — rendered as beautiful cards */}
          {hasToolResults && (
            <ToolResultsRenderer
              messageType={message.message_type}
              content={message.content}
              toolResults={message.tool_results}
            />
          )}
        </div>

        {/* Meta */}
        <div
          className={clsx(
            "mt-1 text-[11px] text-text-tertiary dark:text-dark-text-tertiary flex items-center gap-2",
            isUser ? "justify-end" : "justify-start",
          )}
        >
          <span>{new Date(message.created_at).toLocaleTimeString()}</span>
          {routingBadge && (
            <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent dark:bg-dark-accent/15 dark:text-dark-accent">
              {routingBadge}
            </span>
          )}
          {message.message_type !== "text" && message.message_type !== "file_upload" && (
            <span className="px-1.5 py-0.5 rounded bg-bg-secondary dark:bg-dark-bg-secondary text-[10px]">
              {MESSAGE_TYPE_LABELS[message.message_type] ?? message.message_type.replace(/_/g, " ")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
});
