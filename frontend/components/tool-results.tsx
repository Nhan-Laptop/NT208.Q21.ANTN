"use client";

import {
  FileText,
  Lock,
  ExternalLink,
  BookOpen,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ShieldCheck,
  Brain,
  SpellCheck,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import clsx from "clsx";
import { useState, useCallback } from "react";

/* ====================================================================
 * Shared helpers
 * ==================================================================== */

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/* ====================================================================
 * FileAttachmentCard — replaces raw JSON for file_upload messages
 * ==================================================================== */

interface FileUploadData {
  attachment_id?: string;
  file_name?: string;
  mime_type?: string;
  size_bytes?: number;
  storage_encrypted?: boolean;
}

export function FileAttachmentCard({ data }: { data: FileUploadData }) {
  const fileName = data.file_name ?? "Unknown file";
  const isPdf = data.mime_type === "application/pdf" || fileName.endsWith(".pdf");

  return (
    <div className="mt-2 flex items-center gap-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface px-4 py-3 max-w-sm">
      {/* Icon */}
      <div
        className={clsx(
          "w-10 h-10 rounded-lg flex items-center justify-center shrink-0",
          isPdf
            ? "bg-red-100 dark:bg-red-900/30"
            : "bg-blue-100 dark:bg-blue-900/30",
        )}
      >
        <FileText
          size={20}
          className={isPdf ? "text-red-600 dark:text-red-400" : "text-blue-600 dark:text-blue-400"}
        />
      </div>

      {/* Info */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary dark:text-dark-text-primary truncate">
          {fileName}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          {data.size_bytes != null && (
            <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
              {formatBytes(data.size_bytes)}
            </span>
          )}
          {data.storage_encrypted && (
            <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-1.5 py-0.5 rounded">
              <Lock size={10} />
              Encrypted
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ====================================================================
 * JournalListCard — beautiful rendering for journal_list results
 * ==================================================================== */

interface JournalItem {
  journal: string;
  score: number;
  reason?: string;
  url?: string;
  impact_factor?: number | null;
  publisher?: string | null;
  open_access?: boolean;
  h_index?: number | null;
  review_time_weeks?: number | null;
  acceptance_rate?: number | null;
}

export function JournalListCard({ journals }: { journals: JournalItem[] }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <BookOpen size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Recommended Journals ({journals.length})
        </span>
      </div>
      {journals.map((j, i) => (
        <div
          key={i}
          className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3 hover:border-accent/30 dark:hover:border-dark-accent/30 transition-colors"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-accent dark:text-dark-accent">
                  #{i + 1}
                </span>
                <h4 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary truncate">
                  {j.journal}
                </h4>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5">
                {j.impact_factor != null && (
                  <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                    IF: <strong>{j.impact_factor}</strong>
                  </span>
                )}
                {j.h_index != null && (
                  <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                    h-index: {j.h_index}
                  </span>
                )}
                {j.publisher && (
                  <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                    {j.publisher}
                  </span>
                )}
                {j.open_access && (
                  <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 px-1.5 py-0.5 rounded">
                    Open Access
                  </span>
                )}
                {j.review_time_weeks != null && (
                  <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                    ~{j.review_time_weeks}w review
                  </span>
                )}
                {j.acceptance_rate != null && (
                  <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                    {(j.acceptance_rate * 100).toFixed(0)}% accept
                  </span>
                )}
              </div>
              <div className="mt-1">
                <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                  Match: {(j.score * 100).toFixed(1)}%
                </span>
              </div>
            </div>
            {j.url && (
              <a
                href={j.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 p-1.5 rounded-lg text-text-tertiary hover:text-accent hover:bg-accent/10 dark:text-dark-text-tertiary dark:hover:text-dark-accent dark:hover:bg-dark-accent/10 transition-colors"
                title="Visit journal"
              >
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ====================================================================
 * CitationReportCard — for citation_report results
 * ==================================================================== */

interface CitationItem {
  raw_text?: string;
  citation_text?: string;
  status?: string;
  doi?: string;
  confidence?: number | null;
  title?: string;
  source?: string;
  details?: string;
}

function statusIcon(status: string) {
  const s = status.toUpperCase();
  if (s === "VERIFIED" || s === "FOUND")
    return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (s === "HALLUCINATED" || s === "NOT_FOUND")
    return <XCircle size={14} className="text-red-500" />;
  return <HelpCircle size={14} className="text-amber-500" />;
}

function statusBadge(status: string) {
  const s = status.toUpperCase();
  const cls =
    s === "VERIFIED" || s === "FOUND"
      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
      : s === "HALLUCINATED" || s === "NOT_FOUND"
        ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
        : "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
  return (
    <span className={clsx("inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded", cls)}>
      {statusIcon(status)}
      {status}
    </span>
  );
}

export function CitationReportCard({ citations }: { citations: CitationItem[] }) {
  const verified = citations.filter((c) => {
    const s = (c.status ?? "").toUpperCase();
    return s === "VERIFIED" || s === "FOUND";
  }).length;
  const hallucinated = citations.filter((c) => {
    const s = (c.status ?? "").toUpperCase();
    return s === "HALLUCINATED" || s === "NOT_FOUND";
  }).length;

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <ShieldCheck size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Citation Report — {citations.length} checked
        </span>
        <span className="text-[10px] text-emerald-600 dark:text-emerald-400">✓{verified}</span>
        {hallucinated > 0 && (
          <span className="text-[10px] text-red-600 dark:text-red-400">✗{hallucinated}</span>
        )}
      </div>
      {citations.map((c, i) => (
        <div
          key={i}
          className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3"
        >
          <div className="flex items-start justify-between gap-2 mb-1">
            <p className="text-xs text-text-primary dark:text-dark-text-primary line-clamp-2">
              {c.raw_text || c.citation_text || "Citation"}
            </p>
            {statusBadge(c.status ?? "UNKNOWN")}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            {c.doi && <span>DOI: {c.doi}</span>}
            {c.confidence != null && <span>Confidence: {(c.confidence * 100).toFixed(0)}%</span>}
            {c.source && <span>Source: {c.source}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ====================================================================
 * RetractionReportCard — for retraction_report results
 * ==================================================================== */

interface RetractionItem {
  doi?: string;
  status?: string;
  title?: string;
  is_retracted?: boolean;
  retracted?: boolean;
  risk_level?: string;
  risk_factors?: string[];
  reason?: string;
  journal?: string;
  publication_year?: number;
  authors?: string[];
  sources_checked?: string[];
  source?: string;
  details?: string;
  update_to?: string;
  pubpeer_comments?: number;
  pubpeer_url?: string;
  has_retraction?: boolean;
  has_correction?: boolean;
  has_concern?: boolean;
}

export function RetractionReportCard({ items }: { items: RetractionItem[] }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <AlertTriangle size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Retraction Scan — {items.length} DOI(s) checked
        </span>
      </div>
      {items.map((item, i) => {
        const status = (item.status ?? "UNKNOWN").toUpperCase();
        const isRetracted =
          status === "RETRACTED" || item.has_retraction || item.is_retracted || item.retracted;
        const risk = (item.risk_level ?? "NONE").toUpperCase();
        const statusCls =
          status === "RETRACTED"
            ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
            : status === "CONCERN"
              ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
              : status === "CORRECTED"
                ? "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                : status === "ACTIVE"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
                  : "bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-300";
        const riskCls =
          risk === "CRITICAL" || risk === "HIGH"
            ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
            : risk === "MEDIUM"
              ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
              : "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400";

        const hasPubPeer = (item.pubpeer_comments ?? 0) > 0;
        const factors = item.risk_factors ?? [];
        const authors = item.authors ?? [];
        const sources = item.sources_checked ?? [];

        return (
          <div
            key={i}
            className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3"
          >
            <div className="flex items-start justify-between gap-2 mb-1">
              <p className="text-xs font-medium text-text-primary dark:text-dark-text-primary truncate">
                {item.title || item.doi || `DOI #${i + 1}`}
              </p>
              <div className="flex items-center gap-1 shrink-0">
                <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", statusCls)}>
                  {status}
                </span>
                <span className={clsx("text-[10px] font-medium px-1.5 py-0.5 rounded", riskCls)}>
                  Risk: {risk}
                </span>
              </div>
            </div>
            {item.doi && (
              <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-0.5">
                DOI: {item.doi}
              </p>
            )}
            {item.reason && (
              <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-0.5">
                {item.reason}
              </p>
            )}
            {!isRetracted && hasPubPeer && status !== "CONCERN" && (
              <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1">
                Có thảo luận trên PubPeer nhưng chưa có bằng chứng bài đã bị rút.
              </p>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-1">
              {item.journal && <span>Journal: {item.journal}</span>}
              {item.publication_year != null && <span>Year: {item.publication_year}</span>}
              {authors.length > 0 && <span>Authors: {authors.slice(0, 3).join(", ")}</span>}
              {item.source && <span>Source: {item.source}</span>}
              {sources.length > 0 && <span>Sources checked: {sources.join(", ")}</span>}
              {item.pubpeer_comments != null && item.pubpeer_comments > 0 && (
                <span>PubPeer: {item.pubpeer_comments} comment(s)</span>
              )}
            </div>
            {item.pubpeer_url && (
              <a
                href={item.pubpeer_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-1 text-[11px] text-accent dark:text-dark-accent hover:underline"
              >
                View PubPeer
                <ExternalLink size={11} />
              </a>
            )}
            {factors.length > 0 && (
              <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary mt-1">
                Risk factors: {factors.join("; ")}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface MultiToolGroup {
  tool_name?: string;
  label?: string;
  type?: string;
  data?: unknown;
  summary?: string;
}

/* ====================================================================
 * AIDetectionCard — for ai_writing_detection results
 * ==================================================================== */

interface AIDetectionData {
  score?: number;
  verdict?: string;
  confidence?: string;
  method?: string;
  flags?: string[];
  ml_score?: number | null;
  rule_score?: number;
  details?: Record<string, unknown>;
}

export function AIDetectionCard({ data }: { data: AIDetectionData }) {
  const score = data.score ?? 0;
  const pct = (score * 100).toFixed(1);
  const verdict = data.verdict ?? "UNCERTAIN";

  const verdictColor =
    verdict.includes("HUMAN")
      ? "text-emerald-600 dark:text-emerald-400"
      : verdict.includes("AI")
        ? "text-red-600 dark:text-red-400"
        : "text-amber-600 dark:text-amber-400";

  const barColor =
    score < 0.4
      ? "bg-emerald-500"
      : score < 0.6
        ? "bg-amber-500"
        : "bg-red-500";

  return (
    <div className="mt-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
      <div className="flex items-center gap-1.5 mb-3">
        <Brain size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          AI Writing Detection
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-3">
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-2xl font-bold text-text-primary dark:text-dark-text-primary">
            {pct}%
          </span>
          <span className={clsx("text-sm font-semibold", verdictColor)}>
            {verdict.replace(/_/g, " ")}
          </span>
        </div>
        <div className="w-full h-2 rounded-full bg-bg-secondary dark:bg-dark-bg-secondary overflow-hidden">
          <div
            className={clsx("h-full rounded-full transition-all", barColor)}
            style={{ width: `${Math.min(score * 100, 100)}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-text-tertiary dark:text-dark-text-tertiary mt-0.5">
          <span>Human</span>
          <span>AI Generated</span>
        </div>
      </div>

      {/* Meta */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
        {data.confidence && <span>Confidence: {data.confidence}</span>}
        {data.method && <span>Method: {data.method.replace(/_/g, " ")}</span>}
        {data.ml_score != null && <span>ML: {(data.ml_score * 100).toFixed(1)}%</span>}
        {data.rule_score != null && <span>Rules: {(data.rule_score * 100).toFixed(1)}%</span>}
      </div>

      {/* Flags */}
      {data.flags && data.flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {data.flags.map((f, i) => (
            <span
              key={i}
              className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
            >
              {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ====================================================================
 * GrammarReportCard — for grammar_report results
 * ==================================================================== */

interface GrammarIssue {
  rule_id?: string;
  message?: string;
  offset?: number;
  length?: number;
  replacements?: string[];
  category?: string;
  context?: string;
}

interface GrammarReportData {
  total_errors?: number;
  issues?: GrammarIssue[];
  corrected_text?: string;
  error?: string;
}

export function GrammarReportCard({ data }: { data: GrammarReportData }) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const total = data.total_errors ?? 0;
  const issues = data.issues ?? [];
  const corrected = data.corrected_text ?? "";
  const errorMsg = data.error;
  const VISIBLE_COUNT = 5;
  const hasMore = issues.length > VISIBLE_COUNT;
  const visibleIssues = expanded ? issues : issues.slice(0, VISIBLE_COUNT);

  const handleCopy = useCallback(async () => {
    if (!corrected) return;
    try {
      await navigator.clipboard.writeText(corrected);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API may be blocked */
    }
  }, [corrected]);

  // Error state (LanguageTool unavailable)
  if (errorMsg) {
    return (
      <div className="mt-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-4">
        <div className="flex items-center gap-1.5 mb-1">
          <SpellCheck size={14} className="text-amber-600 dark:text-amber-400" />
          <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
            Grammar & Spelling Report
          </span>
        </div>
        <p className="text-xs text-amber-700 dark:text-amber-400">
          ⚠️ LanguageTool unavailable: {errorMsg}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <SpellCheck size={14} className="text-accent dark:text-dark-accent" />
          <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
            Grammar & Spelling Report
          </span>
        </div>
        {/* Status badge */}
        {total === 0 ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400">
            <CheckCircle2 size={10} />
            Perfect — 0 errors
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400">
            <AlertTriangle size={10} />
            {total} error{total > 1 ? "s" : ""} found
          </span>
        )}
      </div>

      {/* Issues list */}
      {visibleIssues.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {visibleIssues.map((issue, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-lg bg-bg-secondary dark:bg-dark-bg-secondary px-3 py-2"
            >
              <span className="text-[10px] font-bold text-text-tertiary dark:text-dark-text-tertiary mt-0.5 shrink-0">
                {i + 1}.
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-text-primary dark:text-dark-text-primary leading-relaxed">
                  {issue.message || "Unknown issue"}
                </p>
                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                  {issue.replacements && issue.replacements.length > 0 && (
                    <span className="inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded bg-accent/10 text-accent dark:bg-dark-accent/15 dark:text-dark-accent">
                      → {issue.replacements[0]}
                    </span>
                  )}
                  {issue.category && (
                    <span className="text-[10px] text-text-tertiary dark:text-dark-text-tertiary">
                      [{issue.category}]
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
          {/* Expand / collapse toggle */}
          {hasMore && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 text-[11px] font-medium text-accent dark:text-dark-accent hover:underline mt-1 ml-1"
            >
              {expanded ? (
                <>
                  <ChevronUp size={12} /> Show fewer
                </>
              ) : (
                <>
                  <ChevronDown size={12} /> …and {issues.length - VISIBLE_COUNT} more
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Corrected text */}
      {corrected && (
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/40 dark:bg-emerald-900/10 p-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
              Corrected text
            </span>
            <button
              onClick={handleCopy}
              className={clsx(
                "inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md transition-colors",
                copied
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                  : "bg-white dark:bg-dark-surface text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent border border-border dark:border-dark-border",
              )}
              title="Copy corrected text"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-xs leading-relaxed text-text-primary dark:text-dark-text-primary whitespace-pre-wrap">
            {corrected}
          </p>
        </div>
      )}
    </div>
  );
}

/* ====================================================================
 * PdfSummaryCard — for pdf_summary results
 * ==================================================================== */

export function PdfSummaryCard({ text }: { text: string }) {
  return (
    <div className="mt-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
      <div className="flex items-center gap-1.5 mb-2">
        <FileText size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          PDF Summary
        </span>
      </div>
      <p className="text-sm leading-relaxed text-text-primary dark:text-dark-text-primary whitespace-pre-wrap">
        {text}
      </p>
    </div>
  );
}

/* ====================================================================
 * ToolResultsRenderer — master dispatcher that picks the right card
 * ==================================================================== */

export function ToolResultsRenderer({
  messageType,
  content,
  toolResults,
}: {
  messageType: string;
  content: string | null;
  toolResults: Record<string, unknown> | unknown[] | null;
}) {
  if (toolResults && !Array.isArray(toolResults)) {
    const payloadType = (toolResults as Record<string, unknown>).type as string | undefined;
    const groups = (toolResults as Record<string, unknown>).groups;
    if (payloadType === "multi_tool_report" && Array.isArray(groups) && groups.length > 0) {
      return (
        <div className="mt-3 space-y-3">
          {(groups as MultiToolGroup[]).map((group, idx) => {
            const groupType = group.type ?? "text";
            const groupLabel = group.label ?? group.tool_name ?? `Tool ${idx + 1}`;
            return (
              <div
                key={`${group.tool_name ?? "tool"}-${idx}`}
                className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3"
              >
                <div className="text-[11px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary mb-1">
                  {groupLabel}
                </div>
                {group.summary && (
                  <p className="text-xs text-text-secondary dark:text-dark-text-secondary mb-2">
                    {group.summary}
                  </p>
                )}
                <ToolResultsRenderer
                  messageType={groupType}
                  content={group.summary ?? content}
                  toolResults={{ type: groupType, data: group.data }}
                />
              </div>
            );
          })}
        </div>
      );
    }
  }

  // --- File upload ---
  if (messageType === "file_upload" && toolResults && !Array.isArray(toolResults)) {
    const d = (toolResults as Record<string, unknown>).data as FileUploadData | undefined;
    if (d) return <FileAttachmentCard data={d} />;
  }

  // --- Extract structured data from tool_results ---
  const type = toolResults && !Array.isArray(toolResults)
    ? (toolResults as Record<string, unknown>).type as string | undefined
    : undefined;
  const rows = toolResults && !Array.isArray(toolResults)
    ? (toolResults as Record<string, unknown>).data
    : Array.isArray(toolResults)
      ? toolResults
      : undefined;

  // --- Journal list ---
  if (messageType === "journal_list" || type === "journal_list") {
    if (Array.isArray(rows) && rows.length > 0) {
      return <JournalListCard journals={rows as JournalItem[]} />;
    }
  }

  // --- Citation report ---
  if (messageType === "citation_report" || type === "citation_report") {
    if (Array.isArray(rows) && rows.length > 0) {
      return <CitationReportCard citations={rows as CitationItem[]} />;
    }
  }

  // --- Retraction report ---
  if (messageType === "retraction_report" || type === "retraction_report") {
    if (Array.isArray(rows) && rows.length > 0) {
      return <RetractionReportCard items={rows as RetractionItem[]} />;
    }
  }

  // --- AI writing detection ---
  if (messageType === "ai_writing_detection" || type === "ai_writing_detection") {
    // data could be the detection result directly or nested under .data
    const detection = (rows ?? toolResults) as AIDetectionData | undefined;
    if (detection) return <AIDetectionCard data={detection} />;
  }

  // --- Grammar report ---
  if (messageType === "grammar_report" || type === "grammar_report") {
    const grammar = (rows ?? toolResults) as GrammarReportData | undefined;
    if (grammar) return <GrammarReportCard data={grammar} />;
  }

  // --- PDF summary (usually just content text, but handle if in tool_results) ---
  if (messageType === "pdf_summary") {
    if (content) return <PdfSummaryCard text={content} />;
  }

  // --- Fallback: show raw data in a code block ---
  if (toolResults) {
    return (
      <pre className="mt-2 p-3 rounded-lg text-xs overflow-x-auto bg-surface dark:bg-dark-surface border border-border dark:border-dark-border">
        {JSON.stringify(toolResults, null, 2)}
      </pre>
    );
  }

  return null;
}
