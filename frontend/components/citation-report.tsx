"use client";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  HelpCircle,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import clsx from "clsx";
import React, { useCallback, useMemo, useState } from "react";
import type {
  CitationBatchSummary as CitationBatchSummaryModel,
  CitationItem as CitationItemModel,
  CitationReportPayload as CitationReportPayloadModel,
} from "@/lib/types";
import {
  buildCitationReportBibtex,
  buildCitationReportCsv,
  buildCitationReportJson,
  canExportCitationFormats,
  getCitationReportExportMeta,
} from "@/lib/citation-report-export";

interface CitationCandidate {
  source?: string;
  title?: string | null;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  url?: string | null;
  external_id?: string | null;
  external_id_type?: string | null;
  score?: number | null;
  missing_fields?: string[];
  source_domain?: string | null;
}

interface CompletedCitationMetadata {
  source?: string;
  confidence?: number;
  type?: "article" | "inproceedings" | "misc" | string;
  title?: string;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  url?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  external_id?: string | null;
  external_id_type?: string | null;
}

interface CitationFieldEvidenceItem {
  input?: unknown;
  candidate?: unknown;
  similarity?: number | null;
  verdict?: string | null;
  notes?: string | null;
}

interface CitationSourceDiagnostic {
  state?: string | null;
  candidate_count?: number | null;
  detail?: string | null;
}

type CitationBatchSummary = CitationBatchSummaryModel;

type CitationReportItem = CitationItemModel & {
  raw_text?: string;
  citation_text?: string;
  details?: string;
  candidates?: CitationCandidate[];
  evidence_breakdown?: Record<string, number> | null;
  field_evidence?: Record<string, CitationFieldEvidenceItem> | null;
  source_diagnostics?: Record<string, CitationSourceDiagnostic> | null;
  completed_metadata?: CompletedCitationMetadata | null;
  csl_json?: Record<string, unknown> | null;
};

const OFFICIAL_VERIFIED_CITATION_STATUSES = new Set([
  "DOI_VERIFIED", "IDENTIFIER_VERIFIED", "METADATA_VERIFIED",
]);
const CLEAR_MATCH_CITATION_STATUSES = new Set([
  "VERIFIED", "FOUND", "VALID", ...OFFICIAL_VERIFIED_CITATION_STATUSES,
]);
const REVIEW_CITATION_STATUSES = new Set([
  "LIKELY_MATCH", "POSSIBLE_MATCH", "AMBIGUOUS_MATCH", "UNVERIFIED_NO_DOI",
]);
const RED_STATUSES = new Set([
  "HALLUCINATED", "NOT_FOUND", "DOI_NOT_FOUND", "IDENTIFIER_NOT_FOUND", "NO_MATCH_FOUND", "PARSE_FAILED",
]);
const TEMPORARY_CITATION_STATUSES = new Set([
  "UNVERIFIED",
]);

function buildCitationExportFilename(extension: "csv" | "json" | "bib"): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `citation-report-${stamp}.${extension}`;
}

function downloadTextFile(filename: string, text: string, mimeType: string): void {
  if (!text) return;
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function citationUxGroup(status?: string | null) {
  const normalized = (status ?? "").toUpperCase();
  if (OFFICIAL_VERIFIED_CITATION_STATUSES.has(normalized)) return "verified";
  if (REVIEW_CITATION_STATUSES.has(normalized)) return "review";
  if (RED_STATUSES.has(normalized)) return "problem";
  if (TEMPORARY_CITATION_STATUSES.has(normalized)) return "temporary_issue";
  return "problem";
}

function statusIcon(status: string) {
  const s = status.toUpperCase();
  if (CLEAR_MATCH_CITATION_STATUSES.has(s))
    return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (REVIEW_CITATION_STATUSES.has(s))
    return <HelpCircle size={14} className="text-amber-500" />;
  if (RED_STATUSES.has(s))
    return <XCircle size={14} className="text-red-500" />;
  if (TEMPORARY_CITATION_STATUSES.has(s))
    return <AlertTriangle size={14} className="text-slate-500" />;
  return <HelpCircle size={14} className="text-amber-500" />;
}

function citationStatusLabel(status: string) {
  const s = status.toUpperCase();
  if (s === "DOI_VERIFIED") return "Đã xác minh DOI";
  if (s === "IDENTIFIER_VERIFIED") return "Đã xác minh định danh";
  if (s === "VALID" || s === "VERIFIED" || s === "FOUND") return "Khớp rõ ràng";
  if (s === "PARTIAL_MATCH") return "Khớp một phần";
  if (s === "DOI_NOT_FOUND") return "Chưa tìm thấy DOI";
  if (s === "IDENTIFIER_NOT_FOUND") return "Chưa tìm thấy định danh";
  if (s === "HALLUCINATED" || s === "NOT_FOUND") return "Chưa tìm thấy nguồn";
  if (s === "UNVERIFIED") return "Tạm thời chưa xác minh được";
  if (s === "NO_CITATION_FOUND") return "Thiếu thông tin";
  if (s === "METADATA_VERIFIED") return "Khớp metadata (cao)";
  if (s === "LIKELY_MATCH") return "Likely match / Cần kiểm tra thêm";
  if (s === "POSSIBLE_MATCH") return "Possible match / Độ tin cậy thấp";
  if (s === "AMBIGUOUS_MATCH") return "Ambiguous / Có nhiều ứng viên gần giống";
  if (s === "UNVERIFIED_NO_DOI") return "Không đủ tin cậy (no DOI)";
  if (s === "NO_MATCH_FOUND") return "Không tìm thấy nguồn";
  if (s === "PARSE_FAILED") return "Không phân tích được";
  return status || "Chưa rõ";
}

function statusBadge(status: string) {
  const s = status.toUpperCase();
  let cls: string;
  if (CLEAR_MATCH_CITATION_STATUSES.has(s)) {
    cls = "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400";
  } else if (REVIEW_CITATION_STATUSES.has(s)) {
    cls = "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
  } else if (RED_STATUSES.has(s)) {
    cls = "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400";
  } else if (TEMPORARY_CITATION_STATUSES.has(s)) {
    cls = "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
  } else {
    cls = "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
  }
  return (
    <span className={clsx("inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded", cls)}>
      {statusIcon(status)}
      {citationStatusLabel(status)}
    </span>
  );
}

function citationGroupLabel(group: string) {
  if (group === "verified") return "Verified";
  if (group === "review") return "Needs review";
  if (group === "problem") return "Problems";
  if (group === "temporary_issue") return "Temporary issue";
  return "Unknown";
}

function citationGroupBadge(group: string) {
  const cls = group === "verified"
    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
    : group === "review"
      ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
      : group === "problem"
        ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
        : "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
  return (
    <span className={clsx("inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded", cls)}>
      {citationGroupLabel(group)}
    </span>
  );
}

function citationSourceLabel(source?: string | null) {
  const normalized = (source ?? "").toLowerCase();
  if (normalized.includes("web_search")) return "Web search";
  if (normalized === "semantic_scholar") return "Semantic Scholar";
  if (normalized.includes("datacite")) return "DataCite";
  if (normalized.includes("publisher_meta")) return "Publisher metadata";
  if (normalized.includes("openalex") || normalized === "pyalex") return "OpenAlex";
  if (normalized.includes("crossref")) return "Crossref";
  return source || "Nguồn";
}

function citationMatchedByLabel(matchedBy?: string | null) {
  const normalized = (matchedBy ?? "").toLowerCase();
  if (normalized === "doi_exact") return "DOI exact";
  if (normalized === "identifier_exact") return "Identifier exact";
  if (normalized === "metadata_match") return "Metadata match";
  if (normalized === "datacite_match") return "DataCite match";
  if (normalized === "publisher_meta_confirmed") return "Publisher meta confirmed";
  if (normalized === "web_search_evidence") return "Web search evidence";
  return matchedBy || "Unknown";
}

function citationIdentifierLabel(identifierType?: string | null) {
  const normalized = (identifierType ?? "").toLowerCase();
  if (normalized === "pmid") return "PMID";
  if (normalized === "pmcid") return "PMCID";
  if (normalized === "openalex") return "OpenAlex ID";
  return "Identifier";
}

function citationFieldLabel(field: string) {
  if (field === "title") return "Title";
  if (field === "authors") return "Authors";
  if (field === "year") return "Year";
  if (field === "venue") return "Venue";
  if (field === "volume_issue_pages") return "Volume / issue / pages";
  if (field === "doi") return "DOI";
  if (field === "exact_identifier") return "Exact identifier";
  return field;
}

function citationVerdictLabel(verdict?: string | null) {
  const normalized = (verdict ?? "").toLowerCase();
  if (normalized === "exact") return "Exact";
  if (normalized === "match") return "Match";
  if (normalized === "partial_match") return "Partial match";
  if (normalized === "near_match") return "Near match";
  if (normalized === "mismatch") return "Mismatch";
  if (normalized === "missing_candidate") return "Missing from source";
  if (normalized === "source_backed") return "Source-backed";
  if (normalized === "not_provided") return "Not provided";
  return verdict || "—";
}

function citationSourceStateLabel(state?: string | null) {
  const normalized = (state ?? "").toLowerCase();
  if (normalized === "matched") return "Matched";
  if (normalized === "no_match") return "No match";
  if (normalized === "timeout") return "Timeout";
  if (normalized === "http_error") return "HTTP error";
  if (normalized === "disabled") return "Disabled";
  if (normalized === "skipped") return "Skipped";
  if (normalized === "error") return "Error";
  if (normalized === "ambiguous") return "Ambiguous";
  return state || "Unknown";
}

function citationMetadataConsistencyLabel(consistency?: string | null) {
  const normalized = (consistency ?? "").toLowerCase();
  if (normalized === "consistent") return "Consistent";
  if (normalized === "partial_mismatch") return "Partial mismatch";
  if (normalized === "mismatch") return "Mismatch";
  if (normalized === "not_provided") return "Not provided";
  return consistency || "Unknown";
}

function renderCitationEvidenceValue(value: unknown) {
  if (value == null) return "—";
  if (typeof value === "string") return value || "—";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item != null && `${item}`.trim() !== "");
    if (!entries.length) return "—";
    return entries.map(([key, item]) => `${key}: ${item}`).join(" · ");
  }
  return String(value);
}

function CitationSourceBadge({ source }: { source?: string | null }) {
  if (!source) return null;
  return (
    <span className="inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
      {citationSourceLabel(source)}
    </span>
  );
}

function CitationVerificationDetails({ c }: { c: CitationReportItem }) {
  const [copiedKind, setCopiedKind] = useState<"apa" | "bibtex" | "csl" | null>(null);
  const isMetadataMatch = c.verification_mode === "metadata_match";
  const isExactMatch = c.verification_mode === "doi" || c.verification_mode === "identifier_exact";
  const ev = c.evidence_breakdown ?? null;
  const fieldEvidence = c.field_evidence ?? null;
  const fieldEvidenceEntries = [
    "title",
    "authors",
    "year",
    "venue",
    "volume_issue_pages",
    "doi",
    "exact_identifier",
  ]
    .map((key) => [key, fieldEvidence?.[key]] as const)
    .filter(([, value]) => Boolean(value));
  const sourceDiagnostics = c.source_diagnostics
    ? Object.entries(c.source_diagnostics).filter(([, value]) => Boolean(value))
    : [];
  const cands = c.candidates ?? [];
  const inputIdentifier = c.input_identifier
    ? `${citationIdentifierLabel(c.input_identifier_type)} ${c.input_identifier}`
    : null;
  const matchedIdentifier = c.matched_identifier
    ? `${citationIdentifierLabel(c.matched_identifier_type)} ${c.matched_identifier}`
    : null;
  const hasMatched = Boolean(
    c.matched_title || c.matched_doi || c.matched_year || c.matched_venue || inputIdentifier || matchedIdentifier,
  );
  const cslText = c.csl_json ? JSON.stringify(c.csl_json, null, 2) : "";
  const hasFormatted = canExportCitationFormats(c) && Boolean(c.formatted_apa || c.formatted_bibtex || cslText);
  const evidenceUrls = Array.from(new Set((c.evidence_urls ?? []).filter(Boolean)));
  const discoveredViaWebSearch = c.discovered_from === "web_search";

  const handleCopy = useCallback(async (kind: "apa" | "bibtex" | "csl", text: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKind(kind);
      setTimeout(() => setCopiedKind(null), 1800);
    } catch {
      /* clipboard API may be blocked */
    }
  }, []);

  return (
    <div className="mt-2 space-y-2">
      {c.raw_citation && (
        <div className="rounded-md border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2 py-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Raw citation
          </div>
          <p className="mt-1 break-words text-[11px] leading-relaxed text-text-secondary dark:text-dark-text-secondary whitespace-pre-wrap">
            {c.raw_citation}
          </p>
        </div>
      )}

      {c.reason && (
        <p className="text-[11px] leading-relaxed text-text-secondary dark:text-dark-text-secondary">
          {c.reason}
        </p>
      )}

      {c.suggested_action && (
        <div className="rounded-md border border-blue-200 dark:border-blue-900/60 bg-blue-50/70 dark:bg-blue-900/10 px-2 py-1.5 text-[11px] text-blue-800 dark:text-blue-300">
          Next action: {c.suggested_action}
        </div>
      )}

      {discoveredViaWebSearch && (
        <div className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2 py-1 text-[10px] font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
          <span>DOI/URL discovered via web search</span>
        </div>
      )}

      {hasMatched && (
        <div className="text-[11px] text-text-secondary dark:text-dark-text-secondary space-y-0.5">
          {inputIdentifier && (
            <div>
              <span className="text-text-tertiary dark:text-dark-text-tertiary">Input:</span>{" "}
              <span className="break-words text-text-primary dark:text-dark-text-primary">{inputIdentifier}</span>
            </div>
          )}
          {c.matched_title && (
            <div>
              <span className="text-text-tertiary dark:text-dark-text-tertiary">Matched:</span>{" "}
              <span className="break-words text-text-primary dark:text-dark-text-primary">{c.matched_title}</span>
            </div>
          )}
          <div className="flex flex-wrap gap-x-3 gap-y-0.5">
            {matchedIdentifier && <span>{matchedIdentifier}</span>}
            {c.matched_doi && <span className="break-all">DOI: {c.matched_doi}</span>}
            {c.matched_year != null && <span>Năm: {c.matched_year}</span>}
            {c.matched_venue && <span className="break-words">Tạp chí: {c.matched_venue}</span>}
            {c.source_domain && <span>Domain: {c.source_domain}</span>}
            {c.matched_by && <span>Matched by: {citationMatchedByLabel(c.matched_by)}</span>}
            {typeof c.candidate_gap === "number" && <span>Gap: {(c.candidate_gap * 100).toFixed(1)}%</span>}
          </div>
        </div>
      )}

      {(c.resolved_url || evidenceUrls.length > 0 || (c.resolver_chain ?? []).length > 0) && (
        <div className="rounded-md border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2 py-1.5 text-[11px] text-text-secondary dark:text-dark-text-secondary space-y-1">
          {c.resolved_url && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-text-tertiary dark:text-dark-text-tertiary">Resolved URL:</span>
              <a
                href={c.resolved_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-text-primary dark:text-dark-text-primary hover:text-accent dark:hover:text-dark-accent hover:underline break-all"
              >
                {c.resolved_url}
                <ExternalLink size={10} />
              </a>
            </div>
          )}
          {(c.resolver_chain ?? []).length > 0 && (
            <div>
              <span className="text-text-tertiary dark:text-dark-text-tertiary">Resolver chain:</span>{" "}
              {(c.resolver_chain ?? []).map((item) => citationSourceLabel(item)).join(" -> ")}
            </div>
          )}
          {discoveredViaWebSearch && c.web_search_provider && (
            <div>
              <span className="text-text-tertiary dark:text-dark-text-tertiary">Web provider:</span>{" "}
              {c.web_search_provider}
            </div>
          )}
          {evidenceUrls.length > 0 && (
            <div>
              <div className="text-text-tertiary dark:text-dark-text-tertiary">Evidence URLs</div>
              <div className="mt-1 flex flex-col gap-1">
                {evidenceUrls.slice(0, 3).map((url) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-text-primary dark:text-dark-text-primary hover:text-accent dark:hover:text-dark-accent hover:underline break-all"
                  >
                    {url}
                    <ExternalLink size={10} />
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {isExactMatch && c.metadata_consistency && c.metadata_consistency !== "not_provided" && (
        <div className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2 py-1 text-[10px] font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
          <span>Metadata consistency:</span>
          <span>{citationMetadataConsistencyLabel(c.metadata_consistency)}</span>
        </div>
      )}

      {fieldEvidenceEntries.length > 0 && (
        <details className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary" open={isExactMatch}>
          <summary className="cursor-pointer select-none">Field evidence</summary>
          <div className="mt-1 overflow-x-auto rounded-md border border-border/70 dark:border-dark-border/70">
            <table className="min-w-[640px] w-full text-left text-[10px]">
              <thead className="bg-bg-secondary/70 dark:bg-dark-bg-secondary/70 text-text-tertiary dark:text-dark-text-tertiary">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Field</th>
                  <th className="px-2 py-1.5 font-medium">Input</th>
                  <th className="px-2 py-1.5 font-medium">Source</th>
                  <th className="px-2 py-1.5 font-medium">Verdict</th>
                  <th className="px-2 py-1.5 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {fieldEvidenceEntries.map(([field, evidence]) => {
                  const similarity = typeof evidence?.similarity === "number" ? evidence.similarity : null;
                  return (
                    <tr key={field} className="border-t border-border/70 dark:border-dark-border/70">
                      <td className="px-2 py-1.5 align-top text-text-primary dark:text-dark-text-primary">
                        {citationFieldLabel(field)}
                      </td>
                      <td className="px-2 py-1.5 align-top break-words">{renderCitationEvidenceValue(evidence?.input)}</td>
                      <td className="px-2 py-1.5 align-top break-words">{renderCitationEvidenceValue(evidence?.candidate)}</td>
                      <td className="px-2 py-1.5 align-top">{citationVerdictLabel(evidence?.verdict)}</td>
                      <td className="px-2 py-1.5 align-top text-right">
                        {similarity == null ? "—" : `${(similarity * 100).toFixed(0)}%`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {isMetadataMatch && ev && (
        <details className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
          <summary className="cursor-pointer select-none">Chi tiết điểm khớp</summary>
          <div className="mt-1 space-y-0.5">
            {[
              ["Title", ev.title_similarity],
              ["Authors", ev.author_overlap],
              ["Year", ev.year_score],
              ["Venue", ev.venue_similarity],
              ["Vol/Pages", ev.page_volume_bonus],
              ["Tổng", ev.final_score],
            ].map(([label, value]) => {
              const v = typeof value === "number" ? value : 0;
              return (
                <div key={label as string} className="flex items-center gap-2">
                  <span className="w-16">{label}</span>
                  <div className="flex-1 h-1.5 bg-amber-100/60 dark:bg-amber-900/20 rounded">
                    <div
                      className="h-1.5 bg-amber-400 dark:bg-amber-500 rounded"
                      style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }}
                    />
                  </div>
                  <span className="w-10 text-right">{(v * 100).toFixed(0)}%</span>
                </div>
              );
            })}
          </div>
        </details>
      )}

      {sourceDiagnostics.length > 0 && (
        <details className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
          <summary className="cursor-pointer select-none">Source checks</summary>
          <div className="mt-1 space-y-1">
            {sourceDiagnostics.map(([source, diagnostic]) => (
              <div
                key={source}
                className="rounded-md border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2 py-1.5"
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-medium text-text-primary dark:text-dark-text-primary">
                    {citationSourceLabel(source)}
                  </span>
                  <span>{citationSourceStateLabel(diagnostic?.state)}</span>
                  {typeof diagnostic?.candidate_count === "number" && (
                    <span>Candidates: {diagnostic.candidate_count}</span>
                  )}
                </div>
                {diagnostic?.detail && <div className="mt-0.5">{diagnostic.detail}</div>}
              </div>
            ))}
          </div>
        </details>
      )}

      {isMetadataMatch && cands.length > 0 && (
        <details className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
          <summary className="cursor-pointer select-none">Ứng viên khác (top {cands.length})</summary>
          <ol className="mt-1 space-y-1 list-decimal pl-4">
            {cands.slice(0, 3).map((cand, idx) => (
              <li key={idx}>
                {cand.url ? (
                  <a
                    href={cand.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-text-primary dark:text-dark-text-primary hover:text-accent dark:hover:text-dark-accent hover:underline"
                  >
                    {cand.title || "(không có tiêu đề)"}
                    <ExternalLink size={10} />
                  </a>
                ) : (
                  <span className="text-text-primary dark:text-dark-text-primary">
                    {cand.title || "(không có tiêu đề)"}
                  </span>
                )}
                <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px]">
                  {cand.year != null && <span>Năm: {cand.year}</span>}
                  {cand.doi && <span>DOI: {cand.doi}</span>}
                  {typeof cand.score === "number" && <span>Score: {(cand.score * 100).toFixed(0)}%</span>}
                  {cand.missing_fields && cand.missing_fields.length > 0 && (
                    <span>Thiếu: {cand.missing_fields.join(", ")}</span>
                  )}
                  {cand.source && <CitationSourceBadge source={cand.source} />}
                </div>
              </li>
            ))}
          </ol>
        </details>
      )}

      {hasFormatted && (
        <div className="rounded-lg border border-border/80 dark:border-dark-border/80 bg-bg-secondary/50 dark:bg-dark-bg-secondary/50 p-2.5">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <span className="text-[11px] font-semibold text-text-primary dark:text-dark-text-primary">
              Gợi ý hoàn thiện trích dẫn
            </span>
            {c.completed_metadata?.source && <CitationSourceBadge source={c.completed_metadata.source} />}
          </div>

          {c.formatted_apa && (
            <div className="rounded-md bg-surface dark:bg-dark-surface border border-border/70 dark:border-dark-border/70 p-2">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-[10px] font-semibold text-text-tertiary dark:text-dark-text-tertiary uppercase">
                  APA-like
                </span>
                <button
                  onClick={() => handleCopy("apa", c.formatted_apa ?? "")}
                  className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md border border-border dark:border-dark-border text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent"
                  title="Sao chép APA-like"
                >
                  {copiedKind === "apa" ? <Check size={10} /> : <Copy size={10} />}
                  {copiedKind === "apa" ? "Đã sao chép" : "Copy APA"}
                </button>
              </div>
              <p className="text-[11px] leading-relaxed text-text-secondary dark:text-dark-text-secondary">
                {c.formatted_apa}
              </p>
            </div>
          )}

          {c.formatted_bibtex && (
            <details className="mt-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
              <summary className="cursor-pointer select-none">BibTeX</summary>
              <div className="mt-1 rounded-md bg-surface dark:bg-dark-surface border border-border/70 dark:border-dark-border/70 p-2">
                <div className="flex justify-end mb-1">
                  <button
                    onClick={() => handleCopy("bibtex", c.formatted_bibtex ?? "")}
                    className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md border border-border dark:border-dark-border text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent"
                    title="Sao chép BibTeX"
                  >
                    {copiedKind === "bibtex" ? <Check size={10} /> : <Copy size={10} />}
                    {copiedKind === "bibtex" ? "Đã sao chép" : "Copy BibTeX"}
                  </button>
                </div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-relaxed text-text-secondary dark:text-dark-text-secondary">
                  {c.formatted_bibtex}
                </pre>
              </div>
            </details>
          )}

          {cslText && (
            <details className="mt-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
              <summary className="cursor-pointer select-none">CSL JSON</summary>
              <div className="mt-1 rounded-md bg-surface dark:bg-dark-surface border border-border/70 dark:border-dark-border/70 p-2">
                <div className="flex justify-end mb-1">
                  <button
                    onClick={() => handleCopy("csl", cslText)}
                    className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md border border-border dark:border-dark-border text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent"
                    title="Sao chép CSL JSON"
                  >
                    {copiedKind === "csl" ? <Check size={10} /> : <Copy size={10} />}
                    {copiedKind === "csl" ? "Đã sao chép" : "Copy CSL"}
                  </button>
                </div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-relaxed text-text-secondary dark:text-dark-text-secondary">
                  {cslText}
                </pre>
              </div>
            </details>
          )}
        </div>
      )}

      {c.warning && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400">{c.warning}</p>
      )}
    </div>
  );
}

export function CitationReportCard({
  citations,
  summary,
  reportPayload,
}: {
  citations: CitationItemModel[];
  summary?: CitationBatchSummary | null;
  reportPayload?: CitationReportPayloadModel | null;
}) {
  const [filter, setFilter] = useState<"all" | "verified" | "review" | "problem" | "temporary_issue">("all");
  const normalizedCitations = useMemo<CitationReportItem[]>(() => citations.map((citation, index) => {
    const sourceCitation = citation as CitationReportItem;
    return {
      ...sourceCitation,
      index: citation.index ?? index + 1,
      raw_citation:
        citation.raw_citation ?? sourceCitation.raw_text ?? sourceCitation.citation_text ?? citation.citation ?? null,
      ux_group: citation.ux_group ?? citationUxGroup(citation.status),
    };
  }), [citations]);

  const fallbackCounts = normalizedCitations.reduce(
    (acc, citation) => {
      const group = citation.ux_group ?? "problem";
      acc.total_count += 1;
      if (group === "verified") acc.verified_count += 1;
      if (group === "review") acc.review_count += 1;
      if (group === "problem") acc.problem_count += 1;
      if (group === "temporary_issue") acc.temporary_issue_count += 1;
      return acc;
    },
    {
      total_count: 0,
      verified_count: 0,
      review_count: 0,
      problem_count: 0,
      temporary_issue_count: 0,
    },
  );
  const counts = {
    total_count: summary?.total_count ?? fallbackCounts.total_count,
    verified_count: summary?.verified_count ?? fallbackCounts.verified_count,
    review_count: summary?.review_count ?? fallbackCounts.review_count,
    problem_count: summary?.problem_count ?? fallbackCounts.problem_count,
    temporary_issue_count: summary?.temporary_issue_count ?? fallbackCounts.temporary_issue_count,
  };
  const summaryText = summary?.summary_text ?? summary?.default_summary_text ?? null;
  const filteredCitations = normalizedCitations.filter((citation) => filter === "all" || citation.ux_group === filter);
  const exportMeta = useMemo(
    () => getCitationReportExportMeta(reportPayload, normalizedCitations),
    [normalizedCitations, reportPayload],
  );
  const hasBibtexExport = exportMeta.verifiedBibtexCount > 0;

  const filterOptions: Array<{
    id: "all" | "verified" | "review" | "problem" | "temporary_issue";
    label: string;
    count: number;
  }> = [
    { id: "all", label: "All", count: counts.total_count },
    { id: "verified", label: "Verified", count: counts.verified_count },
    { id: "review", label: "Needs review", count: counts.review_count },
    { id: "problem", label: "Problems", count: counts.problem_count },
    { id: "temporary_issue", label: "Temporary issue", count: counts.temporary_issue_count },
  ];

  const handleExportCsv = useCallback(() => {
    downloadTextFile(
      buildCitationExportFilename("csv"),
      buildCitationReportCsv(normalizedCitations, { includeBom: true }),
      "text/csv;charset=utf-8",
    );
  }, [normalizedCitations]);

  const handleExportJson = useCallback(() => {
    downloadTextFile(
      buildCitationExportFilename("json"),
      buildCitationReportJson(reportPayload, {
        citations: normalizedCitations,
        summary,
        text: reportPayload?.text ?? summaryText,
        compact: exportMeta.preferCompactJson,
      }),
      "application/json;charset=utf-8",
    );
  }, [exportMeta.preferCompactJson, normalizedCitations, reportPayload, summary, summaryText]);

  const handleExportBibtex = useCallback(() => {
    if (!hasBibtexExport) return;
    downloadTextFile(
      buildCitationExportFilename("bib"),
      buildCitationReportBibtex(normalizedCitations),
      "application/x-bibtex;charset=utf-8",
    );
  }, [hasBibtexExport, normalizedCitations]);

  return (
    <div data-testid="citation-report-card" className="mt-3 w-full max-w-full space-y-3 overflow-hidden">
      <div className="w-full max-w-full overflow-hidden rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <ShieldCheck size={14} className="text-accent dark:text-dark-accent" />
              <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
                Báo cáo xác minh trích dẫn
              </span>
            </div>
            {summaryText && (
              <p className="break-words text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
                {summaryText}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleExportCsv}
              className="inline-flex items-center gap-1.5 rounded-md border border-border dark:border-dark-border px-3 py-1.5 text-[11px] font-medium text-text-secondary dark:text-dark-text-secondary hover:text-text-primary dark:hover:text-dark-text-primary"
            >
              <Download size={12} />
              Export CSV
            </button>
            <button
              type="button"
              onClick={handleExportJson}
              className="inline-flex items-center gap-1.5 rounded-md border border-border dark:border-dark-border px-3 py-1.5 text-[11px] font-medium text-text-secondary dark:text-dark-text-secondary hover:text-text-primary dark:hover:text-dark-text-primary"
            >
              <Download size={12} />
              Export JSON
            </button>
            <button
              type="button"
              onClick={handleExportBibtex}
              disabled={!hasBibtexExport}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[11px] font-medium transition-colors",
                hasBibtexExport
                  ? "border-border text-text-secondary hover:text-text-primary dark:border-dark-border dark:text-dark-text-secondary dark:hover:text-dark-text-primary"
                  : "cursor-not-allowed border-border/70 text-text-tertiary/80 dark:border-dark-border/70 dark:text-dark-text-tertiary/80",
              )}
            >
              <Download size={12} />
              Export BibTeX
            </button>
          </div>
        </div>
        {exportMeta.isLargeReport && (
          <p className="mt-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            Large report detected. JSON export will use compact formatting to reduce file size.
          </p>
        )}
        {!hasBibtexExport && (
          <p className="mt-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            No verified BibTeX entries available yet.
          </p>
        )}
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <div className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">Total citations</div>
            <div className="mt-1 text-lg font-semibold text-text-primary dark:text-dark-text-primary">{counts.total_count}</div>
          </div>
          <div className="rounded-lg border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/60 dark:bg-emerald-900/10 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Verified</div>
            <div className="mt-1 text-lg font-semibold text-emerald-700 dark:text-emerald-300">{counts.verified_count}</div>
          </div>
          <div className="rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-900/10 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">Needs review</div>
            <div className="mt-1 text-lg font-semibold text-amber-700 dark:text-amber-300">{counts.review_count}</div>
          </div>
          <div className="rounded-lg border border-red-200 dark:border-red-900/60 bg-red-50/60 dark:bg-red-900/10 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-red-700 dark:text-red-300">Problems</div>
            <div className="mt-1 text-lg font-semibold text-red-700 dark:text-red-300">{counts.problem_count}</div>
          </div>
          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100/70 dark:bg-slate-900/20 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">Temporary issues</div>
            <div className="mt-1 text-lg font-semibold text-slate-700 dark:text-slate-300">{counts.temporary_issue_count}</div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {filterOptions.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setFilter(option.id)}
              className={clsx(
                "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors",
                filter === option.id
                  ? "border-accent/40 bg-accent/10 text-accent dark:border-dark-accent/40 dark:bg-dark-accent/10 dark:text-dark-accent"
                  : "border-border text-text-secondary hover:text-text-primary dark:border-dark-border dark:text-dark-text-secondary dark:hover:text-dark-text-primary",
              )}
            >
              <span>{option.label}</span>
              <span className="rounded-full bg-black/5 dark:bg-white/10 px-1.5 py-0.5 text-[10px]">{option.count}</span>
            </button>
          ))}
        </div>
      </div>

      {filteredCitations.length === 0 ? (
        <div className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4 text-sm text-text-secondary dark:text-dark-text-secondary">
          No citations in this filter.
        </div>
      ) : (
        filteredCitations.map((citation) => {
          const status = citation.status ?? "UNKNOWN";
          const group = citation.ux_group ?? "problem";
          const isMetadataMatch = citation.verification_mode === "metadata_match";
          const isDoiExact = citation.verification_mode === "doi";
          const isIdentifierExact = citation.verification_mode === "identifier_exact";
          const verificationHint = isMetadataMatch
            ? "No DOI · Metadata match"
            : isDoiExact
              ? "Exact DOI"
              : isIdentifierExact
                ? `Exact ${citationIdentifierLabel(citation.input_identifier_type)}`
                : null;
          const displayConfidence = typeof citation.confidence === "number"
            ? `${(citation.confidence * 100).toFixed(0)}%`
            : "—";
          const displayTitle = citation.matched_title || citation.title || "—";
          const displayDoi = citation.matched_doi || citation.doi || "—";
          const displayYear = citation.matched_year ?? citation.year ?? "—";
          const displayVenue = citation.matched_venue || "—";
          const displayIssue = citation.short_issue || citation.warning || "—";

          return (
            <details
              key={`${citation.index}-${citation.raw_citation ?? citation.citation ?? "citation"}`}
              className="w-full max-w-full overflow-hidden rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface px-3 py-3"
            >
              <summary className="list-none cursor-pointer">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-bold text-accent dark:text-dark-accent">#{citation.index}</span>
                      {statusBadge(status)}
                      {citationGroupBadge(group)}
                      {verificationHint && (
                        <span className="inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400">
                          {verificationHint}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 break-words text-sm font-medium text-text-primary dark:text-dark-text-primary">
                      {displayTitle}
                    </p>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      <div className="min-w-0 rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2.5 py-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                        <div className="text-[10px] font-semibold uppercase tracking-wide">Confidence</div>
                        <div className="mt-1 text-text-secondary dark:text-dark-text-secondary">{displayConfidence}</div>
                      </div>
                      {displayDoi !== "—" && (
                        <div className="min-w-0 rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2.5 py-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          <div className="text-[10px] font-semibold uppercase tracking-wide">DOI</div>
                          <div className="mt-1 break-all text-text-secondary dark:text-dark-text-secondary">{displayDoi}</div>
                        </div>
                      )}
                      {displayYear !== "—" && (
                        <div className="min-w-0 rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2.5 py-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          <div className="text-[10px] font-semibold uppercase tracking-wide">Year</div>
                          <div className="mt-1 text-text-secondary dark:text-dark-text-secondary">{displayYear}</div>
                        </div>
                      )}
                      {displayVenue !== "—" && (
                        <div className="min-w-0 rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-2.5 py-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          <div className="text-[10px] font-semibold uppercase tracking-wide">Venue</div>
                          <div className="mt-1 break-words text-text-secondary dark:text-dark-text-secondary">{displayVenue}</div>
                        </div>
                      )}
                    </div>
                    {displayIssue !== "—" && (
                      <p className="mt-2 break-words text-[11px] text-text-secondary dark:text-dark-text-secondary">
                        {displayIssue}
                      </p>
                    )}
                  </div>
                  <ChevronDown size={16} className="mt-1 shrink-0 text-text-tertiary dark:text-dark-text-tertiary" />
                </div>
              </summary>

              <div className="mt-3 border-t border-border/70 dark:border-dark-border/70 pt-3">
                {(isMetadataMatch || isDoiExact || isIdentifierExact) ? (
                  <CitationVerificationDetails c={citation} />
                ) : (
                  <div className="space-y-2">
                    {citation.raw_citation && (
                      <p className="break-words text-[11px] text-text-secondary dark:text-dark-text-secondary whitespace-pre-wrap">
                        {citation.raw_citation}
                      </p>
                    )}
                    {citation.reason && (
                      <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                        {citation.reason}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </details>
          );
        })
      )}
    </div>
  );
}
