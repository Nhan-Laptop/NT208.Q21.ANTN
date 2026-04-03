"use client";

import { useChat } from "@/lib/chat-store";
import { Session } from "@/lib/types";
import { ChevronDown } from "lucide-react";

const MODE_LABELS: Record<Session["mode"], string> = {
  general_qa: "General Chat",
  verification: "Citation Verification",
  journal_match: "Journal Match",
  retraction: "Retraction & PubPeer Scan",
  ai_detection: "AI Detection",
};

export function ModeSelector() {
  const { state, setMode } = useChat();

  return (
    <div className="relative inline-flex items-center">
      <select
        value={state.mode}
        onChange={(e) => setMode(e.target.value as Session["mode"])}
        className="appearance-none pl-3 pr-8 py-1.5 rounded-lg border border-border bg-surface text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text-primary dark:focus:ring-dark-accent/20 dark:focus:border-dark-accent cursor-pointer transition-colors"
      >
        {Object.entries(MODE_LABELS).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-tertiary dark:text-dark-text-tertiary pointer-events-none"
      />
    </div>
  );
}
