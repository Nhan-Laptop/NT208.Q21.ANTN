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
  Database,
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
              Đã mã hóa
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ====================================================================
 * JournalListCard — rendering for journal_list results
 * ==================================================================== */

interface JournalItem {
  journal: string;
  entity_type?: string;
  venue_type?: string | null;
  score?: number | null;
  score_calibrated?: boolean;
  reason?: string;
  url?: string;
  impact_factor?: number | null;
  publisher?: string | null;
  open_access?: boolean;
  h_index?: number | null;
  review_time_weeks?: number | null;
  acceptance_rate?: number | null;
  supporting_evidence?: Array<{
    entity_type?: string;
    title?: string;
    doi?: string | null;
    publication_year?: number | null;
    url?: string | null;
  }>;
  metric_provenance?: Record<string, string>;
  unverified_metrics?: string[];
  warning_flags?: string[];
  scope_fit?: string | null;
  evidence_count?: number;
}

export function JournalListCard({ journals }: { journals: JournalItem[] }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <BookOpen size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Gợi ý tạp chí có căn cứ ({journals.length})
        </span>
      </div>
      {journals.map((j, i) => (
        <div
          key={i}
          className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3 hover:border-accent/30 dark:hover:border-dark-accent/30 transition-colors"
        >
              <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-bold text-accent dark:text-dark-accent">
                  #{i + 1}
                </span>
                <h4 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary truncate">
                  {j.journal}
                </h4>
                {j.score != null && (
                  <span
                    className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                      j.score >= 0.7
                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        : j.score >= 0.4
                          ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                          : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                    }`}
                  >
                    {j.score >= 0.7 ? "Độ tin cậy cao" : j.score >= 0.4 ? "Độ tin cậy TB" : "Độ tin cậy thấp"}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5">
                {j.impact_factor != null && (
                  <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary" title={j.metric_provenance?.impact_factor}>
                    IF: <strong>{j.impact_factor}</strong>
                  </span>
                )}
                {j.h_index != null && (
                  <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary" title={j.metric_provenance?.h_index}>
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
                    Truy cập mở
                  </span>
                )}
                {j.review_time_weeks != null && (
                  <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary" title={j.metric_provenance?.avg_review_weeks}>
                    ~{j.review_time_weeks} tuần review
                  </span>
                )}
                {j.acceptance_rate != null && (
                  <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary" title={j.metric_provenance?.acceptance_rate}>
                    {(j.acceptance_rate * 100).toFixed(0)}% chấp nhận
                  </span>
                )}
                {j.warning_flags?.includes("suspected_book_series") && (
                  <span className="text-[10px] font-medium text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 px-1.5 py-0.5 rounded">
                    Book series
                  </span>
                )}
              </div>
              {j.reason && (
                <div className="mt-1.5 text-[11px] text-text-secondary dark:text-dark-text-secondary leading-relaxed">
                  {j.reason}
                </div>
              )}
              {j.supporting_evidence && j.supporting_evidence.length > 0 && (
                <div className="mt-2 border-t border-border/70 dark:border-dark-border/70 pt-2">
                  <div className="text-[10px] font-medium text-text-tertiary dark:text-dark-text-tertiary uppercase">
                    Bằng chứng hỗ trợ
                  </div>
                  <div className="mt-1 space-y-0.5">
                    {j.supporting_evidence.slice(0, 2).map((item, idx) => (
                      <div key={idx} className="text-[11px] text-text-secondary dark:text-dark-text-secondary truncate">
                        {item.title}
                        {item.publication_year ? ` (${item.publication_year})` : ""}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {j.url && (
              <a
                href={j.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 p-1.5 rounded-lg text-text-tertiary hover:text-accent hover:bg-accent/10 dark:text-dark-text-tertiary dark:hover:text-dark-accent dark:hover:bg-dark-accent/10 transition-colors"
                title="Mở nguồn tạp chí"
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
 * JournalMatchStatusCard — insufficient corpus handling
 * ==================================================================== */

export function JournalMatchStatusCard({ status }: { status?: string }) {
  if (status !== "insufficient_corpus") return null;
  return (
    <div className="mt-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-4">
      <div className="flex items-center gap-1.5 mb-1">
        <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Chưa đủ dữ liệu để gợi ý tạp chí
        </span>
      </div>
      <p className="text-xs text-amber-700 dark:text-amber-400">
        Corpus học thuật đã xác minh hiện chưa có đủ journal phù hợp để đề xuất. Hãy bổ sung abstract, keywords, hoặc lĩnh vực nghiên cứu để mình thử lại.
      </p>
    </div>
  );
}

/* ====================================================================
 * AcademicLookupCard — for academic_lookup results
 * ==================================================================== */

interface AcademicLookupRecord {
  entity_type?: string;
  title?: string;
  abstract?: string | null;
  snippet?: string | null;
  venue?: string | null;
  year?: string | number | null;
  doi?: string | null;
  url?: string | null;
  authors?: string[];
}

interface AcademicLookupPayload {
  records?: AcademicLookupRecord[];
  count?: number;
}

export function AcademicLookupCard({ payload }: { payload: AcademicLookupPayload }) {
  const records = payload.records ?? [];
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <Database size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Kết quả tra cứu dữ liệu học thuật ({records.length})
        </span>
      </div>
      {records.map((record, i) => (
        <div
          key={`${record.title ?? "record"}-${i}`}
          className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-text-primary dark:text-dark-text-primary line-clamp-2">
                {record.title || "Bản ghi học thuật"}
              </p>
              {record.venue && (
                <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-0.5">
                  {record.venue}
                </p>
              )}
              {(record.snippet || record.abstract) && (
                <p className="text-xs text-text-secondary dark:text-dark-text-secondary mt-1 line-clamp-3">
                  {record.snippet || record.abstract}
                </p>
              )}
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-1">
                {record.doi && <span>DOI: {record.doi}</span>}
                {record.year && <span>Năm: {record.year}</span>}
                {record.authors && record.authors.length > 0 && (
                  <span>Tác giả: {record.authors.slice(0, 3).join(", ")}</span>
                )}
              </div>
            </div>
            {record.url && (
              <a
                href={record.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 p-1.5 rounded-lg text-text-tertiary hover:text-accent hover:bg-accent/10 dark:text-dark-text-tertiary dark:hover:text-dark-accent dark:hover:bg-dark-accent/10 transition-colors"
                title="Mở nguồn"
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
 * DoiMetadataCard — for doi_metadata results
 * ==================================================================== */

interface DoiMetadataPayload {
  type?: string;
  status?: string;
  data?: {
    doi?: string | null;
    title?: string | null;
    abstract?: string | null;
    year?: number | null;
    venue?: string | null;
    authors?: string[] | null;
    subjects?: string[] | null;
    keywords?: string[] | null;
    url?: string | null;
  };
}

export function DoiMetadataCard({ payload }: { payload: DoiMetadataPayload }) {
  const status = payload.status ?? "unknown";
  const data = payload.data ?? {};
  const hasData = Boolean(data.title || data.abstract || data.venue || data.authors?.length);

  return (
    <div className="mt-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
      <div className="flex items-center gap-1.5 mb-2">
        <BookOpen size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Thông tin DOI
        </span>
        <span
          className={clsx(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded",
            status === "verified"
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
              : "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400",
          )}
        >
          {status === "verified" ? "Đã xác minh" : "Chưa đủ dữ liệu"}
        </span>
      </div>
      {data.doi && (
        <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mb-1">
          DOI: {data.doi}
        </p>
      )}
      {hasData ? (
        <>
          {data.title && (
            <p className="text-sm font-semibold text-text-primary dark:text-dark-text-primary">
              {data.title}
            </p>
          )}
          {data.venue && (
            <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-0.5">
              {data.venue}
            </p>
          )}
          {data.abstract && (
            <p className="text-xs text-text-secondary dark:text-dark-text-secondary mt-2 whitespace-pre-wrap">
              {data.abstract}
            </p>
          )}
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-2">
            {data.year && <span>Năm: {data.year}</span>}
            {data.authors && data.authors.length > 0 && (
              <span>Tác giả: {data.authors.slice(0, 3).join(", ")}</span>
            )}
          </div>
          {data.subjects && data.subjects.length > 0 && (
            <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-2">
              Chủ đề: {data.subjects.slice(0, 6).join(", ")}
            </p>
          )}
          {data.keywords && data.keywords.length > 0 && (
            <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-1">
              Từ khóa: {data.keywords.slice(0, 6).join(", ")}
            </p>
          )}
          {data.url && (
            <a
              href={data.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 mt-2 text-[11px] text-accent dark:text-dark-accent hover:underline"
            >
              Mở nguồn
              <ExternalLink size={11} />
            </a>
          )}
        </>
      ) : (
        <p className="text-xs text-text-secondary dark:text-dark-text-secondary">
          Chưa có metadata đủ chi tiết trong dữ liệu học thuật hiện có cho DOI này.
        </p>
      )}
    </div>
  );
}

/* ====================================================================
 * CitationReportCard — for citation_report results
 * ==================================================================== */

interface CitationItem {
  raw_text?: string;
  citation?: string;
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
  if (s === "VERIFIED" || s === "FOUND" || s === "DOI_VERIFIED" || s === "VALID")
    return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (s === "HALLUCINATED" || s === "NOT_FOUND" || s === "DOI_NOT_FOUND")
    return <XCircle size={14} className="text-red-500" />;
  return <HelpCircle size={14} className="text-amber-500" />;
}

function citationStatusLabel(status: string) {
  const s = status.toUpperCase();
  if (s === "DOI_VERIFIED") return "Đã xác minh DOI";
  if (s === "VALID" || s === "VERIFIED" || s === "FOUND") return "Khớp rõ ràng";
  if (s === "PARTIAL_MATCH") return "Khớp một phần";
  if (s === "DOI_NOT_FOUND") return "Chưa tìm thấy DOI";
  if (s === "HALLUCINATED" || s === "NOT_FOUND") return "Chưa tìm thấy nguồn";
  if (s === "UNVERIFIED") return "Chưa xác minh được";
  if (s === "NO_CITATION_FOUND") return "Thiếu thông tin";
  return status || "Chưa rõ";
}

function statusBadge(status: string) {
  const s = status.toUpperCase();
  const cls =
    s === "VERIFIED" || s === "FOUND" || s === "DOI_VERIFIED" || s === "VALID"
      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
      : s === "HALLUCINATED" || s === "NOT_FOUND" || s === "DOI_NOT_FOUND"
        ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
        : "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
  return (
    <span className={clsx("inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded", cls)}>
      {statusIcon(status)}
      {citationStatusLabel(status)}
    </span>
  );
}

export function CitationReportCard({ citations }: { citations: CitationItem[] }) {
  const verified = citations.filter((c) => {
    const s = (c.status ?? "").toUpperCase();
    return s === "VERIFIED" || s === "FOUND" || s === "DOI_VERIFIED" || s === "VALID";
  }).length;
  const hallucinated = citations.filter((c) => {
    const s = (c.status ?? "").toUpperCase();
    return s === "HALLUCINATED" || s === "NOT_FOUND" || s === "DOI_NOT_FOUND";
  }).length;

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <ShieldCheck size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Kết quả xác minh trích dẫn — {citations.length} mục
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
              {c.raw_text || c.citation_text || c.citation || "Trích dẫn"}
            </p>
            {statusBadge(c.status ?? "UNKNOWN")}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            {c.doi && <span>DOI: {c.doi}</span>}
            {c.confidence != null && <span>Độ tin cậy: {(c.confidence * 100).toFixed(0)}%</span>}
            {c.source && <span>Nguồn: {c.source}</span>}
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
  scan_skipped?: boolean;
  skip_reason?: string | null;
}

function sourceLabel(source: string) {
  const normalized = source.toLowerCase();
  if (normalized === "doi_resolution") return "xác minh DOI";
  if (normalized === "crossref") return "Crossref";
  if (normalized === "openalex") return "OpenAlex";
  if (normalized === "pubpeer") return "PubPeer";
  return source;
}

export function RetractionReportCard({ items }: { items: RetractionItem[] }) {
  const checkedCount = items.filter((item) => (item.status ?? "").toUpperCase() !== "UNVERIFIED" && !item.scan_skipped).length;
  const skippedCount = items.filter((item) => item.scan_skipped || (item.status ?? "").toUpperCase() === "UNVERIFIED").length;
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <AlertTriangle size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Rà soát rút bài — {checkedCount} DOI đã kiểm tra
          {skippedCount > 0 ? `, ${skippedCount} DOI đã bỏ qua` : ""}
        </span>
      </div>
      {items.map((item, i) => {
        const status = (item.status ?? "UNKNOWN").toUpperCase();
        const scanSkipped = Boolean(item.scan_skipped) || status === "UNVERIFIED";
        const statusLabel =
          scanSkipped
            ? "Đã bỏ qua rà soát"
            : status === "ACTIVE"
            ? "Chưa thấy cảnh báo"
            : status === "RETRACTED"
              ? "Đã bị rút"
              : status === "CONCERN"
                ? "Có cảnh báo"
                : status === "CORRECTED"
                  ? "Có hiệu đính"
                  : "Chưa rõ";
        const isRetracted =
          status === "RETRACTED" || item.has_retraction || item.is_retracted || item.retracted;
        const risk = (item.risk_level ?? "NONE").toUpperCase();
        const riskLabel =
          scanSkipped
            ? "Chưa đánh giá"
            : risk === "NONE"
            ? "Thấp"
            : risk === "UNKNOWN"
              ? "Chưa rõ"
              : risk === "CRITICAL"
                ? "Rất cao"
                : risk === "HIGH"
                  ? "Cao"
                  : risk === "MEDIUM"
                    ? "Trung bình"
                    : "Thấp";
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
          scanSkipped
            ? "bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-300"
            : risk === "CRITICAL" || risk === "HIGH"
            ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
            : risk === "MEDIUM"
              ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
              : risk === "UNKNOWN"
                ? "bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-300"
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
                  {statusLabel}
                </span>
                <span className={clsx("text-[10px] font-medium px-1.5 py-0.5 rounded", riskCls)}>
                  Rủi ro: {riskLabel}
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
            {scanSkipped && item.skip_reason && (
              <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-0.5">
                {item.skip_reason}
              </p>
            )}
            {!isRetracted && hasPubPeer && status !== "CONCERN" && (
              <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1">
                Có thảo luận trên PubPeer nhưng chưa có bằng chứng bài đã bị rút.
              </p>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-1">
              {item.journal && <span>Tạp chí: {item.journal}</span>}
              {item.publication_year != null && <span>Năm: {item.publication_year}</span>}
              {authors.length > 0 && <span>Tác giả: {authors.slice(0, 3).join(", ")}</span>}
              {item.source && <span>Nguồn: {item.source}</span>}
              {sources.length > 0 && <span>Nguồn đã dùng: {sources.map(sourceLabel).join(", ")}</span>}
              {item.pubpeer_comments != null && item.pubpeer_comments > 0 && (
                <span>PubPeer: {item.pubpeer_comments} bình luận</span>
              )}
            </div>
            {item.pubpeer_url && (
              <a
                href={item.pubpeer_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-1 text-[11px] text-accent dark:text-dark-accent hover:underline"
              >
                Xem PubPeer
                <ExternalLink size={11} />
              </a>
            )}
            {factors.length > 0 && (
              <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary mt-1">
                Ghi chú: {factors.join("; ")}
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
  specter2_score?: number | null;
  skipped_detectors?: string[];
  fallback_reason?: string | null;
  detectors_used?: string[];
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
          Nhận diện văn bản AI
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
          <span>Thiên về người viết</span>
          <span>Thiên về AI</span>
        </div>
      </div>

      {/* Detectors used badges */}
      {data.detectors_used && data.detectors_used.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {data.detectors_used.map((d, i) => (
            <span
              key={i}
              className="text-[9px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400 font-medium"
            >
              {d.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* Meta */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
        {data.confidence && <span>Độ tin cậy: {data.confidence}</span>}
        {data.method && <span>Phương pháp: {data.method.replace(/_/g, " ")}</span>}
        {data.ml_score != null && <span>ML: {(data.ml_score * 100).toFixed(1)}%</span>}
        {data.rule_score != null && <span>Rules: {(data.rule_score * 100).toFixed(1)}%</span>}
        {data.specter2_score != null && <span>SPECTER2: {(data.specter2_score * 100).toFixed(1)}%</span>}
      </div>

      {/* Skipped detectors warning */}
      {data.skipped_detectors && data.skipped_detectors.length > 0 && (
        <div className="mt-2 mb-1 flex flex-wrap gap-1">
          {data.skipped_detectors.map((s, i) => (
            <span
              key={i}
              className="text-[9px] px-1.5 py-0.5 rounded bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-400"
              title={s}
            >
              ⏭ {s}
            </span>
          ))}
        </div>
      )}

      {/* Fallback reason warning */}
      {data.fallback_reason && (
        <div className="mt-1 mb-1 text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400 inline-block">
          Fallback: {data.fallback_reason.replace(/_/g, " ")}
        </div>
      )}

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

  // Error state
  if (errorMsg) {
    return (
      <div className="mt-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-4">
        <div className="flex items-center gap-1.5 mb-1">
          <SpellCheck size={14} className="text-amber-600 dark:text-amber-400" />
          <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
            Báo cáo ngữ pháp và chính tả
          </span>
        </div>
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Chưa thể chạy công cụ rà soát ngữ pháp trong ngữ cảnh hiện tại. Bạn có thể thử lại sau.
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
            Báo cáo ngữ pháp và chính tả
          </span>
        </div>
        {/* Status badge */}
        {total === 0 ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400">
            <CheckCircle2 size={10} />
            Không phát hiện lỗi
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400">
            <AlertTriangle size={10} />
            Phát hiện {total} lỗi
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
                  <ChevronUp size={12} /> Thu gọn
                </>
              ) : (
                <>
                  <ChevronDown size={12} /> …và {issues.length - VISIBLE_COUNT} lỗi khác
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
              Văn bản đã gợi ý sửa
            </span>
            <button
              onClick={handleCopy}
              className={clsx(
                "inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md transition-colors",
                copied
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                  : "bg-white dark:bg-dark-surface text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent border border-border dark:border-dark-border",
              )}
              title="Sao chép văn bản đã sửa"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? "Đã sao chép" : "Sao chép"}
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
          Tóm tắt PDF
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
            const groupLabel = group.label ?? group.tool_name ?? `Kết quả ${idx + 1}`;
            return (
              <div
                key={`${group.tool_name ?? "tool"}-${idx}`}
                className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3"
              >
                <div className="text-xs font-semibold text-text-primary dark:text-dark-text-primary mb-1">
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
    const tr = toolResults as Record<string, unknown> | undefined;
    const status = tr?.status as string | undefined;
    const doiMeta = tr?.doi_metadata as DoiMetadataPayload["data"] | undefined;
    if (Array.isArray(rows) && rows.length > 0) {
      return (
        <div className="space-y-4">
          {doiMeta ? (
            <DoiMetadataCard payload={{ type: "doi_metadata", status: "verified", data: doiMeta }} />
          ) : null}
          <JournalListCard journals={rows as JournalItem[]} />
        </div>
      );
    }
    if (status === "insufficient_corpus") {
      return (
        <div className="space-y-4">
          {doiMeta ? (
            <DoiMetadataCard payload={{ type: "doi_metadata", status: "verified", data: doiMeta }} />
          ) : null}
          <JournalMatchStatusCard status={status} />
        </div>
      );
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

  // --- Academic lookup ---
  if (type === "academic_lookup" && toolResults && !Array.isArray(toolResults)) {
    const payload = (toolResults as Record<string, unknown>).data as AcademicLookupPayload | undefined;
    if (payload) return <AcademicLookupCard payload={payload} />;
  }

  // --- DOI metadata ---
  if (type === "doi_metadata" && toolResults && !Array.isArray(toolResults)) {
    return <DoiMetadataCard payload={toolResults as DoiMetadataPayload} />;
  }

  // --- PDF summary (usually just content text, but handle if in tool_results) ---
  if (messageType === "pdf_summary") {
    if (content) return <PdfSummaryCard text={content} />;
  }

  // --- Fallback: avoid exposing raw backend payloads to normal users ---
  if (toolResults) {
    if (process.env.NODE_ENV !== "production") {
      console.warn("Missing tool result renderer", { messageType, toolResults });
    }
    return (
      <div className="mt-2 rounded-lg border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3 text-xs text-text-secondary dark:text-dark-text-secondary">
        Mình đã nhận được dữ liệu từ hệ thống. Bạn có thể cung cấp thêm ngữ cảnh nếu cần hiển thị chi tiết hơn.
      </div>
    );
  }

  return null;
}
