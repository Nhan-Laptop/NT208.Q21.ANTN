"use client";

import {
  FileText,
  Lock,
  ExternalLink,
  BookOpen,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Database,
  Brain,
  SpellCheck,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import clsx from "clsx";
import React, { useState, useCallback } from "react";
import { CitationReportCard } from "@/components/citation-report";
import type {
  CitationBatchSummary,
  CitationItem,
  CitationReportPayload as CitationReportPayloadModel,
  DoiMetadataResult,
} from "@/lib/types";

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
  id?: string | null;
  name?: string | null;
  journal: string;
  entity_type?: string;
  venue_type?: string | null;
  score?: number | null;
  score_calibrated?: boolean;
  reason?: string;
  url?: string | null;
  impact_factor?: number | null;
  publisher?: string | null;
  open_access?: boolean;
  issn?: string | null;
  eissn?: string | null;
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
  metrics?: JournalMetrics;
  subject_fit?: string | null;
  links?: Array<{
    label: string;
    url: string;
    type: string;
  }>;
  link_warning?: string | null;
}

interface JournalMetrics {
  impact_factor?: number | null;
  h_index?: number | null;
  review_time_weeks?: number | null;
  acceptance_rate?: number | null;
  open_access?: boolean | null;
  citescore?: number | null;
  sjr_quartile?: string | null;
  jcr_quartile?: string | null;
  indexed_scopus?: boolean | null;
  indexed_wos?: boolean | null;
}

interface JournalMatchItem {
  id?: string | null;
  name?: string | null;
  journal: string;
  venue_id?: string | null;
  venue_type?: string | null;
  score?: number | null;
  reason?: string | null;
  subject_fit?: string | null;
  publisher?: string | null;
  url?: string | null;
  issn?: string | null;
  eissn?: string | null;
  links?: Array<{
    label: string;
    url: string;
    type: string;
  }>;
  link_warning?: string | null;
  supporting_evidence?: Array<{
    entity_type?: string;
    title?: string;
    doi?: string | null;
    publication_year?: number | null;
    url?: string | null;
  }>;
  warning_flags?: string[];
  metric_provenance?: Record<string, string>;
  unverified_metrics?: string[];
  metrics?: JournalMetrics;
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
          key={j.id ?? j.url ?? `${j.journal}-${i}`}
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
                {(() => {
                  const m = j.metrics;
                  const if_val = j.impact_factor ?? m?.impact_factor;
                  const h_val = j.h_index ?? m?.h_index;
                  const oa_val = j.open_access ?? m?.open_access;
                  const rw_val = j.review_time_weeks ?? m?.review_time_weeks;
                  const ar_val = j.acceptance_rate ?? m?.acceptance_rate;
                  return (
                    <>
                      {if_val != null && (
                        <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary" title={j.metric_provenance?.impact_factor}>
                          IF: <strong>{if_val}</strong>
                        </span>
                      )}
                      {h_val != null && (
                        <span className="text-[11px] text-text-secondary dark:text-dark-text-secondary" title={j.metric_provenance?.h_index}>
                          h-index: {h_val}
                        </span>
                      )}
                      {j.publisher && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          {j.publisher}
                        </span>
                      )}
                      {j.issn && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          ISSN: {j.issn}
                        </span>
                      )}
                      {j.eissn && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          eISSN: {j.eissn}
                        </span>
                      )}
                      {oa_val && (
                        <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 px-1.5 py-0.5 rounded">
                          Truy cập mở
                        </span>
                      )}
                      {rw_val != null && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary" title={j.metric_provenance?.avg_review_weeks ?? m?.review_time_weeks}>
                          ~{rw_val} tuần review
                        </span>
                      )}
                      {ar_val != null && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary" title={j.metric_provenance?.acceptance_rate}>
                          {(ar_val * 100).toFixed(0)}% chấp nhận
                        </span>
                      )}
                      {m?.citescore != null && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          CiteScore: {m.citescore}
                        </span>
                      )}
                      {m?.sjr_quartile && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          SJR: {m.sjr_quartile}
                        </span>
                      )}
                      {m?.jcr_quartile && (
                        <span className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          JCR: {m.jcr_quartile}
                        </span>
                      )}
                      {j.warning_flags?.includes("suspected_book_series") && (
                        <span className="text-[10px] font-medium text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 px-1.5 py-0.5 rounded">
                          Book series
                        </span>
                      )}
                      {j.warning_flags?.includes("broad_subject_only") && (
                        <span className="text-[10px] font-medium text-yellow-700 dark:text-yellow-300 bg-yellow-100 dark:bg-yellow-900/30 px-1.5 py-0.5 rounded">
                          Khớp rộng
                        </span>
                      )}
                    </>
                  );
                })()}
              </div>
              {(j.reason || j.subject_fit || j.scope_fit) && (
                <div className="mt-1.5 text-[11px] text-text-secondary dark:text-dark-text-secondary leading-relaxed">
                  {j.reason}
                  {j.subject_fit && (
                    <span className="block mt-0.5 text-text-tertiary dark:text-dark-text-tertiary">
                      Phù hợp: {j.subject_fit}
                    </span>
                  )}
                  {j.scope_fit && !j.subject_fit && (
                    <span className="block mt-0.5 text-text-tertiary dark:text-dark-text-tertiary">
                      {j.scope_fit}
                    </span>
                  )}
                </div>
              )}
              {Array.isArray(j.links) && j.links.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {j.links.map((link, idx) => {
                    const external = !link.type.startsWith("internal");
                    return (
                      <a
                        key={`${link.url}-${idx}`}
                        href={link.url}
                        target={external ? "_blank" : undefined}
                        rel={external ? "noopener noreferrer" : undefined}
                        className="inline-flex items-center gap-1 rounded-full border border-border/70 dark:border-dark-border/70 px-2 py-1 text-[11px] text-text-secondary dark:text-dark-text-secondary hover:border-accent/40 hover:text-accent dark:hover:border-dark-accent/40 dark:hover:text-dark-accent transition-colors"
                      >
                        <ExternalLink size={11} />
                        <span>{link.label}</span>
                      </a>
                    );
                  })}
                </div>
              ) : j.link_warning ? (
                <div className="mt-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                  {j.link_warning}
                </div>
              ) : null}
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

interface CheckedSourceItem {
  name?: string;
  state?: string;
  detail?: string | null;
  candidate_count?: number;
}

function checkedSourceStateLabel(state?: string) {
  const normalized = (state ?? "").toLowerCase();
  if (normalized === "matched") return "Matched";
  if (normalized === "low_confidence") return "Low confidence";
  if (normalized === "no_match") return "No match";
  if (normalized === "timeout") return "Timeout";
  if (normalized === "rate_limited") return "Rate limited";
  if (normalized === "http_error") return "HTTP error";
  if (normalized === "error") return "Error";
  if (normalized === "disabled") return "Disabled";
  if (normalized === "skipped") return "Skipped";
  return state || "Unknown";
}

function checkedSourceStateClass(state?: string) {
  const normalized = (state ?? "").toLowerCase();
  if (normalized === "matched") {
    return "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300";
  }
  if (normalized === "low_confidence") {
    return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300";
  }
  if (normalized === "timeout" || normalized === "rate_limited" || normalized === "http_error" || normalized === "error") {
    return "bg-rose-50 text-rose-700 dark:bg-rose-900/20 dark:text-rose-300";
  }
  return "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
}

function renderCheckedSourceList(sources?: CheckedSourceItem[]) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
        Nguồn đã kiểm tra
      </div>
      <div className="space-y-2">
        {sources.map((source, index) => (
          <div
            key={`${source.name ?? "source"}-${index}`}
            className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">
                {source.name ?? "Unknown source"}
              </span>
              <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", checkedSourceStateClass(source.state))}>
                {checkedSourceStateLabel(source.state)}
              </span>
              {typeof source.candidate_count === "number" ? (
                <span className="text-[10px] text-text-tertiary dark:text-dark-text-tertiary">
                  {source.candidate_count} candidate{source.candidate_count === 1 ? "" : "s"}
                </span>
              ) : null}
            </div>
            {source.detail ? (
              <p className="mt-1 text-[11px] text-text-secondary dark:text-dark-text-secondary">
                {source.detail}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function journalStatusTitle(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "insufficient_record_metadata") return "Metadata tài liệu chưa đủ để gợi ý tạp chí";
  if (normalized === "record_not_found") return "Chưa resolve được tài liệu nguồn";
  if (normalized === "source_degraded") return "Nguồn học thuật bên ngoài đang bị lỗi";
  return "Chưa đủ dữ liệu để gợi ý tạp chí";
}

function journalStatusDescription(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "insufficient_record_metadata") {
    return "Hệ thống đã resolve được tài liệu, nhưng metadata hiện chưa đủ abstract/keywords để chạy journal matching đáng tin cậy.";
  }
  if (normalized === "record_not_found") {
    return "Hệ thống chưa tìm được một bản ghi học thuật đủ tin cậy cho tài liệu này, nên tạm dừng journal matching để tránh gợi ý sai lĩnh vực.";
  }
  if (normalized === "source_degraded") {
    return "Một hoặc nhiều nguồn học thuật bên ngoài bị timeout hoặc lỗi trong lúc resolve tài liệu nguồn. Hãy thử lại sau hoặc gửi thêm DOI/abstract.";
  }
  return "Corpus học thuật đã xác minh hiện chưa có đủ journal phù hợp để đề xuất. Hãy bổ sung abstract, keywords, hoặc lĩnh vực nghiên cứu để mình thử lại.";
}

export function JournalMatchStatusCard({
  status,
  checkedSources,
}: {
  status?: string;
  checkedSources?: CheckedSourceItem[];
}) {
  if (!status || status === "matched") return null;
  return (
    <div className="mt-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-4 space-y-3">
      <div className="flex items-center gap-1.5">
        <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          {journalStatusTitle(status)}
        </span>
      </div>
      <p className="text-xs text-amber-700 dark:text-amber-400">
        {journalStatusDescription(status)}
      </p>
      {renderCheckedSourceList(checkedSources)}
    </div>
  );
}

/* ====================================================================
 * AcademicLookupCard — for academic_lookup results
 * ==================================================================== */

interface AcademicLookupRecord {
  entity_type?: string;
  source?: string | null;
  confidence?: number | null;
  match_status?: string | null;
  score?: number | null;
  title?: string;
  abstract?: string | null;
  snippet?: string | null;
  venue?: string | null;
  year?: string | number | null;
  doi?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  pmid?: string | null;
  pmcid?: string | null;
  url?: string | null;
  authors?: string[];
  subjects?: string[];
  keywords?: string[];
}

interface InputReference {
  query_type?: string;
  authors?: string[];
  venue?: string | null;
  year?: number | null;
  location?: string | null;
  strong_terms?: string[];
  abstract_excerpt?: string | null;
  title_hint?: string | null;
}

interface RejectedCandidate {
  title?: string | null;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  rejection_reasons?: string[];
}

interface AcademicLookupPayload {
  records?: AcademicLookupRecord[];
  count?: number;
  best_record?: AcademicLookupRecord | null;
  low_confidence_records?: AcademicLookupRecord[];
  notes?: string[];
  internal_result?: {
    count?: number;
    best_score?: number;
    confidence?: number;
  } | null;
  source_health?: string;
  input_reference?: InputReference | null;
  rejected_candidates?: RejectedCandidate[];
}

interface AuthorPublicationAuthor {
  name?: string;
  orcid?: string | null;
  external_ids?: {
    openalex?: string | null;
  };
  confidence?: number | null;
  identity_status?: string | null;
  checked_sources?: CheckedSourceItem[];
  publications?: AcademicLookupRecord[];
  publication_count?: number;
  notes?: string[];
}

interface AuthorPublicationSearchPayload {
  type?: string;
  status?: string;
  source_doi?: string | null;
  source_title?: string | null;
  source_record?: AcademicLookupRecord | null;
  authors?: AuthorPublicationAuthor[];
  external_search_used?: boolean;
  checked_sources?: CheckedSourceItem[];
  notes?: string[];
}

function lookupStatusTitle(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "external_found") return "Đã fallback sang nguồn học thuật bên ngoài";
  if (normalized === "external_possible_match") return "Tìm được ứng viên bên ngoài nhưng confidence chưa cao";
  if (normalized === "low_confidence") return "Không tìm thấy kết quả đủ tin cậy";
  if (normalized === "source_degraded") return "Nguồn học thuật bên ngoài đang bị degrade";
  if (normalized === "no_reliable_match") return "Không tìm thấy kết quả phù hợp";
  if (normalized === "not_found") return "Chưa tìm thấy bản ghi đủ tin cậy";
  return "Kết quả tra cứu dữ liệu học thuật";
}

function lookupStatusDescription(status?: string, externalSearchUsed?: boolean) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "external_found") {
    return "Không tìm thấy trong dữ liệu nội bộ, nhưng đã tìm được một bản ghi học thuật phù hợp từ nguồn ngoài.";
  }
  if (normalized === "external_possible_match") {
    return "Đã thử internal search trước, sau đó fallback sang nguồn ngoài và tìm được một candidate ở mức confidence trung bình.";
  }
  if (normalized === "low_confidence") {
    return "Đã kiểm tra dữ liệu nội bộ và nguồn học thuật bên ngoài, nhưng candidate gần nhất vẫn dưới ngưỡng xác minh nên không được coi là bài báo cần tìm.";
  }
  if (normalized === "source_degraded") {
    return "External search đã được kích hoạt nhưng một hoặc nhiều nguồn học thuật bị timeout/lỗi, nên kết quả có thể chưa đầy đủ.";
  }
  if (normalized === "no_reliable_match") {
    return "Đã kiểm tra dữ liệu nội bộ và nguồn học thuật bên ngoài, nhưng không ứng viên nào vượt qua ngưỡng đối sánh với thông tin bạn cung cấp.";
  }
  if (normalized === "not_found") {
    return externalSearchUsed
      ? "Đã kiểm tra cả dữ liệu nội bộ và nguồn học thuật bên ngoài, nhưng chưa thấy bản ghi đủ tin cậy."
      : "Chưa tìm thấy bản ghi đủ tin cậy trong dữ liệu hiện có.";
  }
  return "Kết quả grounded từ dữ liệu học thuật hiện có.";
}

function confidenceLabel(confidence?: number | null) {
  if (typeof confidence !== "number") return null;
  return `${Math.round(confidence * 100)}%`;
}

function recordScoreLabel(score?: number | null) {
  if (typeof score !== "number") return null;
  if (score <= 1) return `${Math.round(score * 100)}%`;
  return String(score);
}

function lookupStatusBadge(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "external_found" || normalized === "internal_found") {
    return "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300";
  }
  if (normalized === "external_possible_match") {
    return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300";
  }
  if (normalized === "low_confidence") {
    return "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
  }
  if (normalized === "source_degraded") {
    return "bg-rose-50 text-rose-700 dark:bg-rose-900/20 dark:text-rose-300";
  }
  if (normalized === "no_reliable_match") {
    return "bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-300";
  }
  return "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
}

function ScholarlyRecordCard({
  record,
  accent = "default",
}: {
  record: AcademicLookupRecord;
  accent?: "default" | "primary";
}) {
  const percent = confidenceLabel(record.confidence);
  const showAbstract = record.abstract || record.snippet;
  return (
    <div
      className={clsx(
        "rounded-xl border p-3",
        accent === "primary"
          ? "border-accent/25 dark:border-dark-accent/30 bg-accent/5 dark:bg-dark-accent/10"
          : "border-border dark:border-dark-border bg-surface dark:bg-dark-surface",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text-primary dark:text-dark-text-primary line-clamp-3">
            {record.title || "Bản ghi học thuật"}
          </p>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
            {record.venue ? <span>{record.venue}</span> : null}
            {record.year ? <span>Năm: {record.year}</span> : null}
            {record.volume ? <span>Vol: {record.volume}</span> : null}
            {record.issue ? <span>Issue: {record.issue}</span> : null}
            {record.pages ? <span>Pages: {record.pages}</span> : null}
            {record.source ? <span>Nguồn: {record.source}</span> : null}
            {percent ? <span>Confidence: {percent}</span> : null}
          </div>
          {record.authors && record.authors.length > 0 ? (
            <p className="mt-1 text-[11px] text-text-secondary dark:text-dark-text-secondary">
              Tác giả: {record.authors.slice(0, 6).join(", ")}
            </p>
          ) : null}
          {showAbstract ? (
            <p className="mt-2 text-xs text-text-secondary dark:text-dark-text-secondary line-clamp-4">
              {showAbstract}
            </p>
          ) : null}
          {(record.subjects && record.subjects.length > 0) || (record.keywords && record.keywords.length > 0) ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(record.subjects ?? []).slice(0, 3).map((subject) => (
                <span
                  key={`subject-${subject}`}
                  className="rounded-full bg-slate-100 dark:bg-slate-800/60 px-2 py-0.5 text-[10px] text-slate-700 dark:text-slate-300"
                >
                  {subject}
                </span>
              ))}
              {(record.keywords ?? []).slice(0, 3).map((keyword) => (
                <span
                  key={`keyword-${keyword}`}
                  className="rounded-full bg-blue-50 dark:bg-blue-900/20 px-2 py-0.5 text-[10px] text-blue-700 dark:text-blue-300"
                >
                  {keyword}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {record.url ? (
          <a
            href={record.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 p-1.5 rounded-lg text-text-tertiary hover:text-accent hover:bg-accent/10 dark:text-dark-text-tertiary dark:hover:text-dark-accent dark:hover:bg-dark-accent/10 transition-colors"
            title="Mở nguồn"
          >
            <ExternalLink size={14} />
          </a>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
        {record.doi ? <span>DOI: {record.doi}</span> : null}
        {record.pmid ? <span>PMID: {record.pmid}</span> : null}
        {record.pmcid ? <span>PMCID: {record.pmcid}</span> : null}
        {record.match_status ? <span>Match: {record.match_status}</span> : null}
        {recordScoreLabel(record.score) ? <span>Score: {recordScoreLabel(record.score)}</span> : null}
      </div>
    </div>
  );
}

function NoReliableMatchCard({
  status,
  externalSearchUsed,
  checkedSources,
  payload,
  inputReference,
  sourceHealth,
  rejectedCandidates: rejectedCandidatesProp,
}: {
  status?: string;
  externalSearchUsed?: boolean;
  checkedSources?: CheckedSourceItem[];
  payload: AcademicLookupPayload;
  inputReference?: InputReference | null;
  sourceHealth?: string;
  rejectedCandidates?: RejectedCandidate[];
}) {
  const inputRef = inputReference ?? payload.input_reference ?? null;
  const health = sourceHealth ?? payload.source_health ?? "healthy";
  const rejectedCandidates = rejectedCandidatesProp ?? payload.rejected_candidates ?? [];
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Database size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          {lookupStatusTitle(status)}
        </span>
        {status ? (
          <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", lookupStatusBadge(status))}>
            {status}
          </span>
        ) : null}
        {health === "degraded" ? (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 dark:bg-rose-900/20 dark:text-rose-300">
            Source degraded
          </span>
        ) : null}
      </div>
      <p className="text-xs text-text-secondary dark:text-dark-text-secondary">
        {lookupStatusDescription(status, externalSearchUsed)}
      </p>

      <div className="rounded-xl border border-orange-200 dark:border-orange-800 bg-orange-50/50 dark:bg-orange-900/10 p-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <HelpCircle size={14} className="text-orange-600 dark:text-orange-400" />
          <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
            Không tìm thấy kết quả phù hợp
          </span>
        </div>
        <p className="text-[11px] text-orange-700 dark:text-orange-300">
          Không có ứng viên nào vượt qua ngưỡng đối sánh với thông tin bạn cung cấp.
        </p>

        {inputRef ? (
          <div className="rounded-lg border border-orange-200/60 dark:border-orange-800/40 bg-white/50 dark:bg-black/10 px-3 py-2 space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
              Thông tin bạn cung cấp
            </p>
            {inputRef.authors && inputRef.authors.length > 0 ? (
              <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                Tác giả: {inputRef.authors.slice(0, 4).join(", ")}
              </p>
            ) : null}
            {inputRef.venue ? (
              <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                Venue: {inputRef.venue}
              </p>
            ) : null}
            {inputRef.year ? (
              <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                Năm: {inputRef.year}
              </p>
            ) : null}
            {inputRef.abstract_excerpt ? (
              <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary line-clamp-2">
                Abstract excerpt: {inputRef.abstract_excerpt}
              </p>
            ) : null}
            {inputRef.strong_terms && inputRef.strong_terms.length > 0 ? (
              <div className="flex flex-wrap gap-1 mt-1">
                {inputRef.strong_terms.slice(0, 5).map((term) => (
                  <span
                    key={term}
                    className="rounded-full bg-slate-100 dark:bg-slate-800/60 px-2 py-0.5 text-[10px] text-slate-700 dark:text-slate-300"
                  >
                    {term}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {health === "degraded" ? (
          <div className="rounded-lg border border-rose-200 dark:border-rose-800 bg-rose-50/50 dark:bg-rose-900/10 px-3 py-2">
            <p className="text-[10px] font-semibold text-rose-700 dark:text-rose-400">
              Nguồn học thuật bị degrade
            </p>
            <p className="text-[11px] text-rose-600 dark:text-rose-300 mt-0.5">
              Một hoặc nhiều nguồn học thuật bên ngoài không khả dụng trong quá trình tra cứu.
            </p>
          </div>
        ) : null}
      </div>

      {rejectedCandidates.length > 0 ? (
        <div className="border border-border dark:border-dark-border rounded-xl overflow-hidden">
          <button
            onClick={() => setDiagnosticsOpen((v) => !v)}
            className="flex items-center justify-between w-full px-3 py-2 text-[11px] font-medium text-text-secondary dark:text-dark-text-secondary hover:bg-bg-secondary/50 dark:hover:bg-dark-bg-secondary/50 transition-colors"
          >
            <span>Candidate bị loại ({rejectedCandidates.length})</span>
            {diagnosticsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          {diagnosticsOpen ? (
            <div className="border-t border-border dark:border-dark-border divide-y divide-border/50 dark:divide-dark-border/50">
              {rejectedCandidates.map((candidate, index) => (
                <div key={`rejected-${index}`} className="px-3 py-2 space-y-1">
                  <p className="text-[11px] font-medium text-text-primary dark:text-dark-text-primary">
                    {candidate.title ?? `Candidate #${index + 1}`}
                  </p>
                  {candidate.authors && candidate.authors.length > 0 ? (
                    <p className="text-[10px] text-text-tertiary dark:text-dark-text-tertiary">
                      Tác giả: {candidate.authors.slice(0, 3).join(", ")}
                    </p>
                  ) : null}
                  {candidate.venue || candidate.year ? (
                    <p className="text-[10px] text-text-tertiary dark:text-dark-text-tertiary">
                      {candidate.venue ? `${candidate.venue}` : ""}
                      {candidate.venue && candidate.year ? " · " : ""}
                      {candidate.year ? `${candidate.year}` : ""}
                    </p>
                  ) : null}
                  {candidate.rejection_reasons && candidate.rejection_reasons.length > 0 ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {candidate.rejection_reasons.map((reason, ri) => (
                        <span
                          key={`reason-${ri}`}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800/40 text-slate-600 dark:text-slate-400"
                        >
                          {reason}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {payload.notes && payload.notes.length > 0 ? (
        <div className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Ghi chú
          </div>
          <div className="mt-1 space-y-1">
            {payload.notes.map((note, index) => (
              <p key={`${note}-${index}`} className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                {note}
              </p>
            ))}
          </div>
        </div>
      ) : null}

      {renderCheckedSourceList(checkedSources)}
    </div>
  );
}

export function AcademicLookupCard({
  status,
  sourceMode,
  confidence,
  confidenceLabel: lookupConfidenceLabel,
  externalSearchUsed,
  checkedSources,
  requestedField,
  payload,
  sourceHealth,
  inputReference,
  rejectedCandidates,
}: {
  status?: string;
  sourceMode?: string;
  confidence?: number;
  confidenceLabel?: string | null;
  externalSearchUsed?: boolean;
  checkedSources?: CheckedSourceItem[];
  requestedField?: string | null;
  payload: AcademicLookupPayload;
  sourceHealth?: string;
  inputReference?: InputReference | null;
  rejectedCandidates?: RejectedCandidate[];
}) {
  const normalizedStatus = (status ?? "").toLowerCase();

  if (normalizedStatus === "no_reliable_match") {
    return (
      <NoReliableMatchCard
        status={status}
        externalSearchUsed={externalSearchUsed}
        checkedSources={checkedSources}
        payload={payload}
        inputReference={inputReference}
        sourceHealth={sourceHealth}
        rejectedCandidates={rejectedCandidates}
      />
    );
  }
  const records = payload.records ?? [];
  const bestRecord = payload.best_record ?? null;
  const lowConfidenceRecords = payload.low_confidence_records ?? [];
  const secondaryRecords = bestRecord ? records.slice(1) : records;
  const internalConfidence = confidenceLabel(payload.internal_result?.confidence);
  const lowConfidenceCandidate = lowConfidenceRecords[0] ?? null;
  const primarySectionTitle = status === "external_possible_match" ? "Ứng viên phù hợp nhất" : "Tài liệu phù hợp nhất";
  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Database size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          {lookupStatusTitle(status)}
        </span>
        {status ? (
          <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", lookupStatusBadge(status))}>
            {status}
          </span>
        ) : null}
        {sourceMode ? (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
            {sourceMode === "internal_corpus" ? "Internal corpus" : "External scholarly"}
          </span>
        ) : null}
        {(lookupConfidenceLabel || confidenceLabel(confidence)) ? (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
            Confidence: {lookupConfidenceLabel ?? confidenceLabel(confidence)}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-text-secondary dark:text-dark-text-secondary">
        {lookupStatusDescription(status, externalSearchUsed)}
      </p>

      {externalSearchUsed ? (
        <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-3">
          <div className="flex items-center gap-1.5">
            <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400" />
            <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
              Không tìm thấy đủ mạnh trong dữ liệu nội bộ
            </span>
          </div>
          <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">
            Internal retrieval
            {typeof payload.internal_result?.count === "number" ? `: ${payload.internal_result.count} candidate` : ""}
            {payload.internal_result?.count === 1 ? "" : typeof payload.internal_result?.count === "number" ? "s" : ""}
            {typeof payload.internal_result?.best_score === "number" ? `, best score ${payload.internal_result.best_score}` : ""}
            {internalConfidence ? `, confidence ${internalConfidence}` : ""}.
          </p>
        </div>
      ) : null}

      {status === "low_confidence" ? (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/20 p-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <HelpCircle size={14} className="text-slate-600 dark:text-slate-300" />
            <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
              Không tìm thấy kết quả đủ tin cậy
            </span>
          </div>
          <p className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
            {lowConfidenceCandidate?.confidence != null
              ? `Candidate gần nhất chỉ đạt ${confidenceLabel(lowConfidenceCandidate.confidence)}, thấp hơn ngưỡng xác minh. Vì vậy mình không coi đây là bài báo người dùng đang tìm.`
              : "Các candidate hiện có chưa vượt ngưỡng xác minh, nên mình không promote candidate nào thành kết quả chính."}
          </p>
        </div>
      ) : null}

      {requestedField === "authors" && bestRecord?.authors && bestRecord.authors.length > 0 ? (
        <div className="rounded-xl border border-accent/30 dark:border-dark-accent/35 bg-accent/5 dark:bg-dark-accent/10 p-3">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
              Authors found ({bestRecord.authors.length})
            </span>
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
              Requested field
            </span>
            {(status === "external_possible_match" || status === "low_confidence") && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                Possible match, needs verification
              </span>
            )}
          </div>
          <div className="space-y-1.5">
            {bestRecord.authors.map((author, index) => (
              <p
                key={`${author}-${index}`}
                className="text-sm leading-relaxed text-text-primary dark:text-dark-text-primary break-words"
              >
                <span className="mr-2 text-[11px] font-semibold text-text-tertiary dark:text-dark-text-tertiary">
                  [{index + 1}]
                </span>
                {author}
              </p>
            ))}
          </div>
        </div>
      ) : null}

      {bestRecord ? (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            {primarySectionTitle}
          </div>
          <ScholarlyRecordCard record={bestRecord} accent="primary" />
        </div>
      ) : null}

      {secondaryRecords.length > 0 ? (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Candidate bổ sung
          </div>
          {secondaryRecords.slice(0, 2).map((record, index) => (
            <ScholarlyRecordCard key={`${record.title ?? "record"}-${index}`} record={record} />
          ))}
        </div>
      ) : null}

      {lowConfidenceRecords.length > 0 ? (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Candidate độ tin cậy thấp
          </div>
          {lowConfidenceRecords.slice(0, 2).map((record, index) => (
            <ScholarlyRecordCard key={`${record.title ?? "low-record"}-${index}`} record={record} />
          ))}
        </div>
      ) : null}

      {renderCheckedSourceList(checkedSources)}

      {payload.notes && payload.notes.length > 0 ? (
        <div className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Ghi chú
          </div>
          <div className="mt-1 space-y-1">
            {payload.notes.map((note, index) => (
              <p key={`${note}-${index}`} className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                {note}
              </p>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function authorPublicationStatusTitle(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "matched") return "Đã tìm publication khác của tác giả";
  if (normalized === "source_degraded") return "Nguồn học thuật bên ngoài đang bị lỗi";
  if (normalized === "source_not_found") return "Chưa resolve được bài báo nguồn";
  return "Tra publication theo tác giả";
}

function authorPublicationStatusDescription(status?: string, externalSearchUsed?: boolean) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "matched") {
    return "Hệ thống đã resolve bài báo gốc, lấy danh sách tác giả và liệt kê thêm các publication khác ngoài bài gốc.";
  }
  if (normalized === "source_degraded") {
    return "Bài báo nguồn đã được resolve, nhưng một hoặc nhiều nguồn học thuật bên ngoài bị timeout hoặc lỗi trong lúc tra publication theo tác giả.";
  }
  if (normalized === "source_not_found") {
    return "Hệ thống chưa resolve được DOI thành bài báo nguồn đủ tin cậy nên chưa thể đi tiếp sang bước tra publication của tác giả.";
  }
  return externalSearchUsed
    ? "Đã thử mở rộng sang nguồn học thuật bên ngoài, nhưng chưa tìm được publication khác đủ tin cậy."
    : "Đã resolve được tác giả, nhưng chưa tìm thấy publication khác đủ tin cậy trong dữ liệu hiện có.";
}

export function AuthorPublicationSearchCard({ payload }: { payload: AuthorPublicationSearchPayload }) {
  const authors = payload.authors ?? [];
  const sourceRecord = payload.source_record ?? null;
  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <BookOpen size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          {authorPublicationStatusTitle(payload.status)}
        </span>
        {payload.status ? (
          <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded", lookupStatusBadge(payload.status))}>
            {payload.status}
          </span>
        ) : null}
        {payload.external_search_used ? (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
            External fallback used
          </span>
        ) : null}
      </div>
      <p className="text-xs text-text-secondary dark:text-dark-text-secondary">
        {authorPublicationStatusDescription(payload.status, payload.external_search_used)}
      </p>

      {sourceRecord ? (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Bài báo nguồn
          </div>
          <ScholarlyRecordCard record={sourceRecord} accent="primary" />
        </div>
      ) : null}

      {authors.length > 0 ? (
        <div className="space-y-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Tác giả và publication khác
          </div>
          {authors.map((author, index) => (
            <div
              key={`${author.name ?? "author"}-${index}`}
              className="rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-3 space-y-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-text-primary dark:text-dark-text-primary">
                  {author.name ?? "Unknown author"}
                </span>
                {author.orcid ? (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
                    ORCID
                  </span>
                ) : null}
                {author.external_ids?.openalex ? (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                    OpenAlex
                  </span>
                ) : null}
                {confidenceLabel(author.confidence) ? (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                    Confidence: {confidenceLabel(author.confidence)}
                  </span>
                ) : null}
              </div>

              {author.notes && author.notes.length > 0 ? (
                <div className="space-y-1">
                  {author.notes.map((note, noteIndex) => (
                    <p key={`${note}-${noteIndex}`} className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                      {note}
                    </p>
                  ))}
                </div>
              ) : null}

              {author.publications && author.publications.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
                    Publication khác ({author.publications.length})
                  </div>
                  {author.publications.map((record, recordIndex) => (
                    <ScholarlyRecordCard key={`${record.title ?? "record"}-${recordIndex}`} record={record} />
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/20 px-3 py-2 text-[11px] text-text-secondary dark:text-dark-text-secondary">
                  Chưa tìm thấy publication khác đủ tin cậy ngoài bài gốc cho tác giả này.
                </div>
              )}

              {renderCheckedSourceList(author.checked_sources)}
            </div>
          ))}
        </div>
      ) : null}

      {renderCheckedSourceList(payload.checked_sources)}

      {payload.notes && payload.notes.length > 0 ? (
        <div className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Ghi chú
          </div>
          <div className="mt-1 space-y-1">
            {payload.notes.map((note, index) => (
              <p key={`${note}-${index}`} className="text-[11px] text-text-secondary dark:text-dark-text-secondary">
                {note}
              </p>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ====================================================================
 * DoiMetadataCard — for doi_metadata results
 * ==================================================================== */

type DoiMetadataPayload = DoiMetadataResult;

interface IntentCandidate {
  feature?: string;
  label?: string;
  confidence?: number;
  source?: string;
}

interface IntentDisambiguationPayload {
  type?: string;
  data?: {
    candidates?: IntentCandidate[];
  };
}

export function DoiMetadataCard({ payload }: { payload: DoiMetadataPayload }) {
  const status = payload.status ?? "unknown";
  const data = payload.data ?? {};
  const requestedField = payload.requested_field ?? null;
  const authorNamesFromDetails = data.author_details
    ?.map((author) => author.name?.trim())
    .filter((author): author is string => Boolean(author));
  const authorNamesFromList = data.authors
    ?.map((author) => author?.trim())
    .filter((author): author is string => Boolean(author));
  const authorNames = authorNamesFromDetails && authorNamesFromDetails.length > 0
    ? authorNamesFromDetails
    : (authorNamesFromList ?? []);
  const authorCount = data.author_count ?? authorNames.length;
  const hasData = Boolean(
    data.title
    || data.journal
    || data.venue
    || data.publisher
    || data.abstract
    || authorNames.length
    || data.research_field
    || data.main_topic,
  );
  const journal = data.journal ?? data.venue ?? null;
  const publicationYear = data.publication_year ?? data.year ?? null;
  const confidence = typeof data.confidence === "number" ? `${Math.round(data.confidence * 100)}%` : null;
  const notes = (data.notes ?? []).filter(Boolean);
  const missingFields = (data.missing_fields ?? []).filter(Boolean);
  const [authorsExpanded, setAuthorsExpanded] = useState(
    requestedField === "authors" || authorNames.length <= 8,
  );
  const [authorsCopied, setAuthorsCopied] = useState(false);
  const hasMoreAuthors = authorNames.length > 8;
  const visibleAuthors = authorsExpanded ? authorNames : authorNames.slice(0, 8);

  const renderField = (label: string, value?: string | number | null, fallback?: string | null) => (
    <div className="rounded-lg border border-border/70 dark:border-dark-border/70 bg-bg-secondary/40 dark:bg-dark-bg-secondary/40 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
        {label}
      </div>
      <div className="mt-1 text-sm text-text-primary dark:text-dark-text-primary break-words">
        {value ?? fallback ?? "Not available"}
      </div>
    </div>
  );

  const handleCopyAuthors = useCallback(async () => {
    if (authorNames.length === 0) return;
    try {
      await navigator.clipboard.writeText(
        authorNames.map((author, index) => `${index + 1}. ${author}`).join("\n"),
      );
      setAuthorsCopied(true);
      setTimeout(() => setAuthorsCopied(false), 1800);
    } catch {
      /* clipboard API may be blocked */
    }
  }, [authorNames]);

  return (
    <div className="mt-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface p-4">
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <BookOpen size={14} className="text-accent dark:text-dark-accent" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          DOI Analysis
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
        {data.source && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
            Source: {data.source}
          </span>
        )}
        {confidence && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
            Confidence: {confidence}
          </span>
        )}
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
          {authorNames.length > 0 && (
            <div
              className={clsx(
                "mt-3 rounded-xl border p-3",
                requestedField === "authors"
                  ? "border-accent/30 dark:border-dark-accent/35 bg-accent/5 dark:bg-dark-accent/10"
                  : "border-border/70 dark:border-dark-border/70 bg-bg-secondary/35 dark:bg-dark-bg-secondary/35",
              )}
            >
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
                    Authors{typeof authorCount === "number" ? ` (${authorCount})` : ""}
                  </span>
                  {requestedField === "authors" && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
                      Requested field
                    </span>
                  )}
                </div>
                <button
                  onClick={handleCopyAuthors}
                  className={clsx(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors",
                    authorsCopied
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300"
                      : "border-border dark:border-dark-border text-text-secondary dark:text-dark-text-secondary hover:text-accent dark:hover:text-dark-accent",
                  )}
                  title="Sao chép danh sách tác giả"
                >
                  {authorsCopied ? <Check size={10} /> : <Copy size={10} />}
                  {authorsCopied ? "Đã sao chép" : "Sao chép tác giả"}
                </button>
              </div>
              <div className="mt-2 space-y-1.5">
                {visibleAuthors.map((author, index) => (
                  <p
                    key={`${author}-${index}`}
                    className="text-sm leading-relaxed text-text-primary dark:text-dark-text-primary break-words"
                  >
                    <span className="mr-2 text-[11px] font-semibold text-text-tertiary dark:text-dark-text-tertiary">
                      [{index + 1}]
                    </span>
                    {author}
                  </p>
                ))}
              </div>
              {hasMoreAuthors && (
                <button
                  onClick={() => setAuthorsExpanded((value) => !value)}
                  className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-accent dark:text-dark-accent hover:underline"
                >
                  {authorsExpanded ? (
                    <>
                      <ChevronUp size={12} />
                      Thu gọn danh sách tác giả
                    </>
                  ) : (
                    <>
                      <ChevronDown size={12} />
                      Hiển thị thêm {authorNames.length - visibleAuthors.length} tác giả
                    </>
                  )}
                </button>
              )}
            </div>
          )}
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {renderField("Verification status", data.verification_status ?? (status === "verified" ? "Valid DOI" : "DOI not found"))}
            {renderField("Journal", journal)}
            {renderField("Publisher", data.publisher)}
            {renderField("Publication year", publicationYear)}
            {renderField(
              "Research field",
              data.research_field,
              data.research_field_note ?? "Not directly available from source metadata.",
            )}
            {renderField(
              "Main topic",
              data.main_topic,
              data.main_topic_note ?? "Not directly available from source metadata.",
            )}
          </div>
          {data.abstract && (
            <p className="text-xs text-text-secondary dark:text-dark-text-secondary mt-2 whitespace-pre-wrap">
              {data.abstract}
            </p>
          )}
          {data.subjects && data.subjects.length > 0 && (
            <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-2">
              Subjects: {data.subjects.slice(0, 6).join(", ")}
            </p>
          )}
          {data.keywords && data.keywords.length > 0 && (
            <p className="text-[11px] text-text-tertiary dark:text-dark-text-tertiary mt-1">
              Keywords: {data.keywords.slice(0, 6).join(", ")}
            </p>
          )}
          {missingFields.length > 0 && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-2">
              Missing fields: {missingFields.join(", ")}
            </p>
          )}
          {notes.length > 0 && (
            <div className="mt-2 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-900/10 p-2.5 text-[11px] text-amber-800 dark:text-amber-300">
              {notes.map((note, idx) => (
                <p key={`${note}-${idx}`}>{note}</p>
              ))}
            </div>
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

export function IntentDisambiguationCard({ payload }: { payload: IntentDisambiguationPayload }) {
  const candidates = payload.data?.candidates ?? [];
  if (candidates.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-4">
      <div className="flex items-center gap-1.5 mb-2">
        <HelpCircle size={14} className="text-amber-600 dark:text-amber-400" />
        <span className="text-xs font-semibold text-text-primary dark:text-dark-text-primary">
          Cần làm rõ tính năng
        </span>
      </div>
      <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">
        Prompt này có thể thuộc nhiều hướng xử lý. Hãy nói rõ bạn muốn AIRA dùng tính năng nào.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {candidates.map((candidate, index) => (
          <span
            key={`${candidate.feature ?? "candidate"}-${index}`}
            className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-medium text-amber-700 dark:bg-black/10 dark:text-amber-300"
          >
            {candidate.label ?? candidate.feature ?? `Lựa chọn ${index + 1}`}
            {typeof candidate.confidence === "number" && (
              <span className="text-[10px] opacity-80">
                {Math.round(candidate.confidence * 100)}%
              </span>
            )}
          </span>
        ))}
      </div>
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
  final_score?: number;
  model_score?: number | null;
  roberta_score?: number | null;
  custom_rule_score?: number;
  risk_level?: string;
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
  rule_source?: "default_app_rules" | "user_custom_rules";
  matched_rules?: Array<
    | string
    | {
        rule_id?: string;
        rule_name?: string;
        rule_type?: string;
        severity?: string;
        weight?: number;
        matched_text?: string | null;
        reason?: string;
        confidence?: number | null;
        location?: {
          paragraph_index?: number | null;
        } | null;
      }
  >;
  evidence?: Array<{
    text?: string;
    reason?: string;
    rule_id?: string;
    severity?: string;
    paragraph_index?: number | null;
  }>;
  explanation?: string | null;
  suggestions?: string[];
  disclaimer?: string | null;
  warnings?: string[];
  details?: Record<string, unknown>;
}

const AI_DETECTION_DISCLAIMER_VI = "Kết quả này chỉ là tín hiệu ước lượng về khả năng văn bản do AI hỗ trợ viết. Không nên dùng như bằng chứng kết luận; cần kết hợp với đánh giá của con người và ngữ cảnh học thuật.";
const AI_DETECTION_DISCLAIMER_EN = "This result is a likelihood/risk signal only. It should not be treated as conclusive evidence and should be reviewed together with human judgment and academic context.";

export function AIDetectionCard({ data }: { data: AIDetectionData }) {
  const score = data.final_score ?? data.score ?? 0;
  const pct = (score * 100).toFixed(1);
  const verdict = data.verdict ?? "UNCERTAIN";
  const customRuleScore = data.custom_rule_score ?? data.rule_score ?? 0;
  const robertaScore = data.roberta_score ?? data.ml_score;
  const disclaimer = data.disclaimer ?? AI_DETECTION_DISCLAIMER_EN;

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
        {data.risk_level && <span>Risk: {data.risk_level}</span>}
        {data.confidence && <span>Độ tin cậy: {data.confidence}</span>}
        {data.method && <span>Phương pháp: {data.method.replace(/_/g, " ")}</span>}
        {data.model_score != null && <span>Baseline: {(data.model_score * 100).toFixed(1)}%</span>}
        {robertaScore != null && <span>RoBERTa: {(robertaScore * 100).toFixed(1)}%</span>}
        {customRuleScore != null && <span>Custom rules: {(customRuleScore * 100).toFixed(1)}%</span>}
        {data.specter2_score != null && <span>SPECTER2: {(data.specter2_score * 100).toFixed(1)}%</span>}
        {data.rule_source && (
          <span>
            Rule source: {data.rule_source === "user_custom_rules" ? "Custom rules" : "Default rules"}
          </span>
        )}
      </div>

      <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900 dark:border-amber-900/40 dark:bg-amber-900/10 dark:text-amber-200">
        <p>{AI_DETECTION_DISCLAIMER_VI}</p>
        <p className="mt-1">{disclaimer}</p>
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

      {data.warnings && data.warnings.length > 0 && (
        <div className="mt-2 space-y-1">
          {data.warnings.map((warning, index) => (
            <div
              key={`${warning}-${index}`}
              className="rounded-lg bg-orange-50 px-2.5 py-1.5 text-[10px] text-orange-800 dark:bg-orange-900/20 dark:text-orange-300"
            >
              {warning}
            </div>
          ))}
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

      {data.matched_rules && data.matched_rules.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-medium uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Matched custom rules
          </div>
          <div className="mt-2 space-y-2">
            {data.matched_rules.map((rule, i) => {
              if (typeof rule === "string") {
                return (
                  <span
                    key={`${rule}-${i}`}
                    className="inline-flex text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                  >
                    {rule}
                  </span>
                );
              }

              return (
                <div
                  key={`${rule.rule_id ?? rule.rule_name ?? "rule"}-${i}`}
                  className="rounded-xl border border-border/70 bg-bg-secondary/55 px-3 py-2 dark:border-white/10 dark:bg-white/[0.03]"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">
                      {rule.rule_name ?? "Matched rule"}
                    </span>
                    {rule.rule_type && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] uppercase text-blue-700 dark:bg-blue-900/20 dark:text-blue-400">
                        {rule.rule_type}
                      </span>
                    )}
                    {rule.severity && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] uppercase text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
                        {rule.severity}
                      </span>
                    )}
                  </div>
                  {rule.reason && (
                    <p className="mt-1 text-[11px] leading-5 text-text-secondary dark:text-dark-text-secondary">
                      {rule.reason}
                    </p>
                  )}
                  {rule.matched_text && (
                    <div className="mt-1 rounded-lg bg-surface px-2 py-1.5 text-[11px] text-text-primary dark:bg-[#101010] dark:text-dark-text-primary">
                      {rule.matched_text}
                    </div>
                  )}
                  {(rule.confidence != null || rule.location?.paragraph_index != null) && (
                    <div className="mt-1 text-[10px] text-text-tertiary dark:text-dark-text-tertiary">
                      {rule.confidence != null ? `Confidence: ${(rule.confidence * 100).toFixed(0)}%` : ""}
                      {rule.confidence != null && rule.location?.paragraph_index != null ? " | " : ""}
                      {rule.location?.paragraph_index != null ? `Paragraph: ${rule.location.paragraph_index + 1}` : ""}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.evidence && data.evidence.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-medium uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Evidence
          </div>
          <div className="mt-2 space-y-2">
            {data.evidence.map((item, index) => (
              <div
                key={`${item.rule_id ?? "evidence"}-${index}`}
                className="rounded-xl border border-border/70 bg-bg-secondary/55 px-3 py-2 dark:border-white/10 dark:bg-white/[0.03]"
              >
                <div className="text-[11px] leading-5 text-text-primary dark:text-dark-text-primary">
                  {item.text}
                </div>
                {item.reason && (
                  <div className="mt-1 text-[10px] text-text-secondary dark:text-dark-text-secondary">
                    {item.reason}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {data.explanation && (
        <div className="mt-3 rounded-xl border border-border/70 bg-bg-secondary/55 px-3 py-2 dark:border-white/10 dark:bg-white/[0.03]">
          <div className="text-[10px] font-medium uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Explanation
          </div>
          <p className="mt-1 text-[11px] leading-5 text-text-secondary dark:text-dark-text-secondary">
            {data.explanation}
          </p>
        </div>
      )}

      {data.suggestions && data.suggestions.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-medium uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
            Suggestions
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {data.suggestions.map((suggestion, index) => (
              <span
                key={`${suggestion}-${index}`}
                className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
              >
                {suggestion}
              </span>
            ))}
          </div>
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
  const routingFeature = toolResults && !Array.isArray(toolResults)
    ? ((((toolResults as Record<string, unknown>).meta as Record<string, unknown> | undefined)?.routing as Record<string, unknown> | undefined)?.resolved_feature as string | undefined)
    : undefined;

  // --- Journal list ---
  if (messageType === "journal_list" || type === "journal_list") {
    const tr = toolResults as Record<string, unknown> | undefined;
    const status = tr?.status as string | undefined;
    const doiMeta = tr?.doi_metadata as DoiMetadataPayload["data"] | undefined;
    const sourceRecord = tr?.source_record as AcademicLookupRecord | undefined;
    const checkedSources = tr?.checked_sources as CheckedSourceItem[] | undefined;
    if (Array.isArray(rows) && rows.length > 0) {
      return (
        <div className="space-y-4">
          {sourceRecord ? <ScholarlyRecordCard record={sourceRecord} accent="primary" /> : null}
          {doiMeta ? (
            <DoiMetadataCard payload={{ type: "doi_metadata", status: "verified", data: doiMeta }} />
          ) : null}
          <JournalListCard journals={rows as JournalItem[]} />
        </div>
      );
    }
    if (status && status !== "matched") {
      return (
        <div className="space-y-4">
          {sourceRecord ? <ScholarlyRecordCard record={sourceRecord} accent="primary" /> : null}
          {doiMeta ? (
            <DoiMetadataCard payload={{ type: "doi_metadata", status: "verified", data: doiMeta }} />
          ) : null}
          <JournalMatchStatusCard status={status} checkedSources={checkedSources} />
        </div>
      );
    }
  }

  // --- Journal match (new chat payload) ---
  if (type === "journal_match" && toolResults && !Array.isArray(toolResults)) {
    const tr = toolResults as Record<string, unknown>;
    const matches = tr.matches as JournalMatchItem[] | undefined;
    const matchStatus = tr.status as string | undefined;
    if (Array.isArray(matches) && matches.length > 0) {
      return <JournalListCard journals={matches as unknown as JournalItem[]} />;
    }
    if (matchStatus) {
      return <JournalMatchStatusCard status={matchStatus} />;
    }
  }

  // --- Citation report ---
  if (messageType === "citation_report" || type === "citation_report") {
    const tr = toolResults as Record<string, unknown> | undefined;
    const reportRows = Array.isArray(tr?.results)
      ? tr?.results
      : Array.isArray(rows)
        ? rows
        : undefined;
    const reportSummary = tr?.summary as CitationBatchSummary | undefined;
    const emptyCitationReport = Array.isArray(reportRows) && reportRows.length === 0;
    if (emptyCitationReport && routingFeature === "general_qa") {
      return null;
    }
    if (Array.isArray(reportRows)) {
      return (
        <CitationReportCard
          citations={reportRows as CitationItem[]}
          summary={reportSummary}
          reportPayload={tr as CitationReportPayloadModel | undefined}
        />
      );
    }
  }

  // --- Retraction report ---
  if (messageType === "retraction_report" || type === "retraction_report") {
    if (Array.isArray(rows) && rows.length > 0) {
      return <RetractionReportCard items={rows as RetractionItem[]} />;
    }
  }

  // --- AI writing detection ---
  if (messageType === "ai_writing_detection" || type === "ai_writing_detection" || type === "ai_detection") {
    // data could be the detection result directly or nested under .data
    const detection = (rows ?? toolResults) as AIDetectionData | undefined;
    if (detection) return <AIDetectionCard data={detection} />;
  }

  // --- Grammar report ---
  if (messageType === "grammar_report" || type === "grammar_report") {
    const grammar = (rows ?? toolResults) as GrammarReportData | undefined;
    if (grammar) return <GrammarReportCard data={grammar} />;
  }

  // --- Author publication search ---
  if (type === "author_publication_search" && toolResults && !Array.isArray(toolResults)) {
    return <AuthorPublicationSearchCard payload={toolResults as AuthorPublicationSearchPayload} />;
  }

  // --- Academic lookup ---
  if (type === "academic_lookup" && toolResults && !Array.isArray(toolResults)) {
    const payload = (toolResults as Record<string, unknown>).data as AcademicLookupPayload | undefined;
    if (payload) {
      const root = toolResults as Record<string, unknown>;
      return (
        <AcademicLookupCard
          status={root.status as string | undefined}
          sourceMode={root.source_mode as string | undefined}
          confidence={root.confidence as number | undefined}
          confidenceLabel={root.confidence_label as string | undefined}
          externalSearchUsed={Boolean(root.external_search_used)}
          checkedSources={root.checked_sources as CheckedSourceItem[] | undefined}
          requestedField={root.requested_field as string | undefined}
          payload={payload}
          sourceHealth={root.source_health as string | undefined}
          inputReference={root.input_reference as InputReference | undefined}
          rejectedCandidates={root.rejected_candidates as RejectedCandidate[] | undefined}
        />
      );
    }
  }

  // --- DOI metadata ---
  if (type === "doi_metadata" && toolResults && !Array.isArray(toolResults)) {
    return <DoiMetadataCard payload={toolResults as DoiMetadataPayload} />;
  }

  // --- Intent disambiguation ---
  if (type === "intent_disambiguation" && toolResults && !Array.isArray(toolResults)) {
    return <IntentDisambiguationCard payload={toolResults as IntentDisambiguationPayload} />;
  }

  // --- PDF summary (usually just content text, but handle if in tool_results) ---
  if (messageType === "pdf_summary") {
    if (content) return <PdfSummaryCard text={content} />;
  }

  // --- Routing metadata only ---
  if (toolResults && !Array.isArray(toolResults)) {
    const meta = (toolResults as Record<string, unknown>).meta;
    const keys = Object.keys(toolResults as Record<string, unknown>);
    if (keys.length === 1 && meta && typeof meta === "object") {
      return null;
    }
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
