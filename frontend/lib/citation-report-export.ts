import type { CitationBatchSummary, CitationReportPayload } from "@/lib/types";

type CitationReportSummaryLike = Partial<CitationBatchSummary>;

type CitationReportExportItem = {
  citation?: string;
  status?: string | null;
  confidence?: number | null;
  matched_title?: string | null;
  matched_doi?: string | null;
  matched_year?: number | null;
  matched_venue?: string | null;
  formatted_bibtex?: string | null;
  index?: number;
  raw_citation?: string | null;
  ux_group?: string | null;
  short_issue?: string | null;
  suggested_action?: string | null;
};

export const VERIFIED_CITATION_STATUSES = new Set([
  "DOI_VERIFIED",
  "IDENTIFIER_VERIFIED",
  "METADATA_VERIFIED",
]);
export const LARGE_REPORT_CITATION_THRESHOLD = 250;
export const LARGE_REPORT_JSON_BYTE_THRESHOLD = 250_000;

const CSV_COLUMNS = [
  "index",
  "raw_citation",
  "status",
  "ux_group",
  "confidence",
  "matched_title",
  "matched_doi",
  "matched_year",
  "matched_venue",
  "short_issue",
  "suggested_action",
] as const;

function normalizeCitationText(citation: CitationReportExportItem, fallbackIndex: number): string {
  return citation.raw_citation ?? citation.citation ?? `Citation ${fallbackIndex + 1}`;
}

function escapeCsvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, "\"\"")}"`;
}

function estimateTextBytes(text: string): number {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(text).length;
  }
  return text.length;
}

export function isVerifiedCitationStatus(status?: string | null): boolean {
  return VERIFIED_CITATION_STATUSES.has(String(status ?? "").trim().toUpperCase());
}

export function canExportCitationFormats(citation?: { status?: string | null } | null): boolean {
  return isVerifiedCitationStatus(citation?.status);
}

export function getCitationReportBibtexEntries(citations: CitationReportExportItem[]): string[] {
  return citations
    .filter((citation) => canExportCitationFormats(citation))
    .map((citation) => citation.formatted_bibtex?.trim() ?? "")
    .filter((entry) => entry.length > 0);
}

export function buildCitationReportBibtex(citations: CitationReportExportItem[]): string {
  return getCitationReportBibtexEntries(citations).join("\n\n");
}

export function buildCitationReportCsv(
  citations: CitationReportExportItem[],
  options?: { includeBom?: boolean },
): string {
  const header = CSV_COLUMNS.join(",");
  const rows = citations.map((citation, index) => {
    const values = {
      index: citation.index ?? index + 1,
      raw_citation: normalizeCitationText(citation, index),
      status: citation.status ?? "",
      ux_group: citation.ux_group ?? "",
      confidence: citation.confidence ?? "",
      matched_title: citation.matched_title ?? "",
      matched_doi: citation.matched_doi ?? "",
      matched_year: citation.matched_year ?? "",
      matched_venue: citation.matched_venue ?? "",
      short_issue: citation.short_issue ?? "",
      suggested_action: citation.suggested_action ?? "",
    };
    return CSV_COLUMNS.map((column) => escapeCsvCell(values[column])).join(",");
  });

  const body = [header, ...rows].join("\n");
  return options?.includeBom ? `\uFEFF${body}` : body;
}

export function buildCitationReportJson(
  payload?: CitationReportPayload | null,
  options?: {
    citations?: CitationReportExportItem[];
    summary?: CitationReportSummaryLike | null;
    text?: string | null;
    compact?: boolean;
  },
): string {
  const fallbackPayload: CitationReportPayload = {
    type: "citation_report",
    data: options?.citations as CitationReportPayload["data"],
    results: options?.citations as CitationReportPayload["results"],
    summary: options?.summary as CitationReportPayload["summary"],
    text: options?.text ?? undefined,
  };
  return JSON.stringify(payload ?? fallbackPayload, null, options?.compact ? 0 : 2);
}

export function getCitationReportExportMeta(
  payload: CitationReportPayload | null | undefined,
  citations: CitationReportExportItem[],
): {
  citationCount: number;
  verifiedBibtexCount: number;
  approxJsonBytes: number;
  approxCsvBytes: number;
  isLargeReport: boolean;
  preferCompactJson: boolean;
} {
  const prettyJson = buildCitationReportJson(payload, { citations });
  const csv = buildCitationReportCsv(citations);
  const citationCount = citations.length;
  const approxJsonBytes = estimateTextBytes(prettyJson);
  return {
    citationCount,
    verifiedBibtexCount: getCitationReportBibtexEntries(citations).length,
    approxJsonBytes,
    approxCsvBytes: estimateTextBytes(csv),
    isLargeReport: citationCount >= LARGE_REPORT_CITATION_THRESHOLD,
    preferCompactJson:
      citationCount >= LARGE_REPORT_CITATION_THRESHOLD || approxJsonBytes >= LARGE_REPORT_JSON_BYTE_THRESHOLD,
  };
}
