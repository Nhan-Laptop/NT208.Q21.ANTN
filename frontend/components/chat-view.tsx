"use client";

import { api, showApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat-store";
import { Message } from "@/lib/types";
import { ModeSelector } from "@/components/topbar";
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
import { ChangeEvent, FormEvent, KeyboardEvent, memo, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { toast } from "sonner";

export function ChatView() {
  const { token } = useAuth();
  const { state, loadMessages, sendMessage } = useChat();
  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const prevMessageCountRef = useRef(0);

  const { activeSessionId, messages, isLoadingMessages, isSending } = state;

  // Load messages when session changes
  useEffect(() => {
    if (token && activeSessionId) {
      loadMessages(token, activeSessionId);
    }
  }, [token, activeSessionId, loadMessages]);

  // Scroll to bottom only when new messages are appended (not on initial load)
  useEffect(() => {
    if (messages.length > prevMessageCountRef.current && prevMessageCountRef.current > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevMessageCountRef.current = messages.length;
  }, [messages]);

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

  const handleFileUpload = async () => {
    if (!selectedFile || !token || !activeSessionId) return;
    setIsUploading(true);
    try {
      await api.uploadFile(token, activeSessionId, selectedFile);
      toast.success(`Uploaded ${selectedFile.name}`);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      loadMessages(token, activeSessionId);
    } catch (err) {
      showApiError(err);
    } finally {
      setIsUploading(false);
    }
  };

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    if (file && activeSessionId) {
      // auto-upload
      setIsUploading(true);
      api
        .uploadFile(token!, activeSessionId, file)
        .then(() => {
          toast.success(`Uploaded ${file.name}`);
          setSelectedFile(null);
          if (fileInputRef.current) fileInputRef.current.value = "";
          loadMessages(token!, activeSessionId);
        })
        .catch(showApiError)
        .finally(() => setIsUploading(false));
    }
  };

  // Empty state
  if (!activeSessionId && messages.length === 0) {
    return (
      <div className="flex flex-col h-full">
        {/* Empty center */}
        <div className="flex-1 flex flex-col items-center justify-center px-4">
          <div className="w-14 h-14 rounded-2xl bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center mb-5">
            <Sparkles className="w-7 h-7 text-accent dark:text-dark-accent" />
          </div>
          <h1 className="text-2xl font-semibold text-text-primary dark:text-dark-text-primary mb-2">
            How can I help you today?
          </h1>
          <p className="text-text-secondary dark:text-dark-text-secondary text-sm max-w-md text-center mb-6">
            Ask research questions, verify citations, find journals, or check for AI-written content.
          </p>

          {/* Quick actions */}
          <div className="flex flex-wrap gap-2 justify-center max-w-lg">
            {[
              "Verify a citation in APA format",
              "Find journals for my paper",
              "Check if references are retracted",
              "Detect AI writing in my text",
            ].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => {
                  setInput(suggestion);
                  textareaRef.current?.focus();
                }}
                className="px-3 py-2 rounded-xl border border-border bg-surface text-sm text-text-secondary hover:bg-bg-secondary hover:text-text-primary dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover dark:hover:text-dark-text-primary transition-colors"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>

        {/* Input area */}
        <InputArea
          input={input}
          setInput={setInput}
          isSending={isSending}
          textareaRef={textareaRef}
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
          fileInputRef={fileInputRef}
          onFileChange={onFileChange}
          isUploading={isUploading}
          selectedFile={selectedFile}
          setSelectedFile={setSelectedFile}
          showAttach={false}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      {activeSessionId && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border dark:border-dark-border bg-surface/80 dark:bg-dark-surface/80 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <ModeSelector />
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-1">
          {isLoadingMessages && (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-text-tertiary dark:text-dark-text-tertiary" />
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {isSending && (
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
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <InputArea
        input={input}
        setInput={setInput}
        isSending={isSending}
        textareaRef={textareaRef}
        onSubmit={handleSubmit}
        onKeyDown={handleKeyDown}
        fileInputRef={fileInputRef}
        onFileChange={onFileChange}
        isUploading={isUploading}
        selectedFile={selectedFile}
        setSelectedFile={setSelectedFile}
        showAttach={!!activeSessionId}
      />
    </div>
  );
}

/* ── Input Area ── */
function InputArea({
  input,
  setInput,
  isSending,
  textareaRef,
  onSubmit,
  onKeyDown,
  fileInputRef,
  onFileChange,
  isUploading,
  selectedFile,
  setSelectedFile,
  showAttach,
}: {
  input: string;
  setInput: (v: string) => void;
  isSending: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onSubmit: (e?: FormEvent) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileChange: (e: ChangeEvent<HTMLInputElement>) => void;
  isUploading: boolean;
  selectedFile: File | null;
  setSelectedFile: (f: File | null) => void;
  showAttach: boolean;
}) {
  return (
    <div className="border-t border-border dark:border-dark-border bg-surface/80 dark:bg-dark-surface/80 backdrop-blur-sm px-4 py-3">
      <div className="max-w-3xl mx-auto">
        {/* File preview */}
        {selectedFile && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-lg bg-bg-secondary dark:bg-dark-bg-secondary text-sm">
            <FileUp size={14} className="text-text-tertiary dark:text-dark-text-tertiary" />
            <span className="truncate text-text-secondary dark:text-dark-text-secondary">
              {selectedFile.name}
            </span>
            {isUploading && <Loader2 size={14} className="animate-spin text-accent dark:text-dark-accent" />}
            <button
              onClick={() => {
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
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
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="p-2 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-secondary dark:text-dark-text-tertiary dark:hover:text-dark-text-primary dark:hover:bg-dark-surface-hover transition-colors disabled:opacity-50"
                title="Attach file"
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
              placeholder="Send a message..."
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
              {isSending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <ArrowUp size={16} />
              )}
            </button>
          </div>
        </form>

        <div className="flex items-center justify-end mt-2">
          <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            Shift+Enter for new line
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Message Bubble ── */
const MessageBubble = memo(function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const isTool = message.role === "tool";

  return (
    <div
      className={clsx("flex items-start gap-3 py-4", isUser && "flex-row-reverse")}
    >
      {/* Avatar */}
      <div
        className={clsx(
          "w-7 h-7 rounded-full flex items-center justify-center shrink-0",
          isUser
            ? "bg-accent text-white dark:bg-dark-accent"
            : "bg-accent/10 dark:bg-dark-accent/10",
        )}
      >
        {isUser ? (
          <User size={15} />
        ) : (
          <Bot
            size={15}
            className="text-accent dark:text-dark-accent"
          />
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
          {message.content && (
            <p className="whitespace-pre-wrap break-words m-0">{message.content}</p>
          )}
          {message.tool_results && (
            <ToolResultsDisplay data={message.tool_results} isUser={isUser} />
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
          {message.message_type !== "text" && (
            <span className="px-1.5 py-0.5 rounded bg-bg-secondary dark:bg-dark-bg-secondary text-[10px]">
              {message.message_type.replace("_", " ")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
});

/* ── Tool Results ── */
function ToolResultsDisplay({
  data,
  isUser,
}: {
  data: Record<string, unknown> | unknown[];
  isUser: boolean;
}) {
  if (Array.isArray(data)) {
    return (
      <pre
        className={clsx(
          "mt-2 p-3 rounded-lg text-xs overflow-x-auto",
          isUser
            ? "bg-white/10"
            : "bg-surface dark:bg-dark-surface border border-border dark:border-dark-border",
        )}
      >
        {JSON.stringify(data, null, 2)}
      </pre>
    );
  }

  const type = typeof data.type === "string" ? data.type : "result";
  const rows = Array.isArray(data.data) ? data.data : null;

  if (!rows || rows.length === 0) {
    return (
      <pre
        className={clsx(
          "mt-2 p-3 rounded-lg text-xs overflow-x-auto",
          isUser
            ? "bg-white/10"
            : "bg-surface dark:bg-dark-surface border border-border dark:border-dark-border",
        )}
      >
        {JSON.stringify(data, null, 2)}
      </pre>
    );
  }

  const keys =
    typeof rows[0] === "object" && rows[0]
      ? Object.keys(rows[0] as Record<string, unknown>)
      : [];

  return (
    <div className="mt-2">
      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent dark:bg-dark-accent/10 dark:text-dark-accent mb-1">
        {type}
      </span>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              {keys.map((key) => (
                <th
                  key={key}
                  className="text-left px-2 py-1.5 border-b border-border dark:border-dark-border font-medium text-text-secondary dark:text-dark-text-secondary"
                >
                  {key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              if (typeof row !== "object" || !row) return null;
              return (
                <tr key={i}>
                  {keys.map((key) => (
                    <td
                      key={key}
                      className="px-2 py-1.5 border-b border-border/50 dark:border-dark-border/50"
                    >
                      {String((row as Record<string, unknown>)[key] ?? "")}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
