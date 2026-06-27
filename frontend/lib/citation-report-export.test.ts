import { describe, expect, it } from "vitest";
import {
  buildCitationReportBibtex,
  buildCitationReportCsv,
  buildCitationReportJson,
  getCitationReportExportMeta,
} from "@/lib/citation-report-export";
import type { CitationReportPayload } from "@/lib/types";

describe("citation-report-export", () => {
  it("escapes CSV commas, quotes, newlines, and nullish values", () => {
    const csv = buildCitationReportCsv([
      {
        index: 1,
        raw_citation: "Smith, J.\n\"Quoted\" title",
        status: "LIKELY_MATCH",
        ux_group: "review",
        confidence: 0.82,
        matched_title: "Alpha, Beta",
        matched_doi: null,
        matched_year: 2024,
        matched_venue: undefined,
        short_issue: "Needs \"manual\" review",
        suggested_action: null,
        citation: "ignored fallback",
      },
    ]);

    expect(csv).toContain("\"Smith, J.\n\"\"Quoted\"\" title\"");
    expect(csv).toContain("\"Alpha, Beta\"");
    expect(csv).toContain("\"Needs \"\"manual\"\" review\"");
    expect(csv).toContain("\"Alpha, Beta\",,2024,,");
  });

  it("builds BibTeX from verified statuses only even if weak rows carry accidental formatted_bibtex", () => {
    const bibtex = buildCitationReportBibtex([
      {
        citation: "Verified citation",
        status: "DOI_VERIFIED",
        formatted_bibtex: "@article{verified}",
      },
      {
        citation: "Weak citation",
        status: "LIKELY_MATCH",
        formatted_bibtex: "@article{weak}",
      },
      {
        citation: "Problem citation",
        status: "DOI_NOT_FOUND",
        formatted_bibtex: "@article{problem}",
      },
      {
        citation: "Metadata citation",
        status: "METADATA_VERIFIED",
        formatted_bibtex: "@article{metadata}",
      },
    ]);

    expect(bibtex).toContain("@article{verified}");
    expect(bibtex).toContain("@article{metadata}");
    expect(bibtex).not.toContain("@article{weak}");
    expect(bibtex).not.toContain("@article{problem}");
  });

  it("builds JSON export from the full report payload", () => {
    const payload: CitationReportPayload = {
      type: "citation_report",
      text: "One verified.",
      no_citation_found: false,
      statistics: { total: 1, doi_verified: 1 },
      summary: {
        total_count: 1,
        verified_count: 1,
        review_count: 0,
        problem_count: 0,
        temporary_issue_count: 0,
        status_counts: { DOI_VERIFIED: 1 },
        default_summary_text: "One verified.",
      },
      results: [
        {
          index: 1,
          raw_citation: "10.1000/example",
          citation: "10.1000/example",
          status: "DOI_VERIFIED",
          ux_group: "verified",
          matched_title: "Example",
          matched_doi: "10.1000/example",
          confidence: 1,
        },
      ],
      data: [],
    };

    const json = buildCitationReportJson(payload);
    const parsed = JSON.parse(json) as CitationReportPayload;

    expect(parsed.summary?.status_counts?.DOI_VERIFIED).toBe(1);
    expect(parsed.results?.[0]?.matched_doi).toBe("10.1000/example");
    expect(parsed.statistics).toEqual({ total: 1, doi_verified: 1 });
    expect(parsed.text).toBe("One verified.");
  });

  it("marks large reports so JSON export can switch to compact mode", () => {
    const citations = Array.from({ length: 260 }, (_, index) => ({
      index: index + 1,
      raw_citation: `Citation ${index + 1}`,
      citation: `Citation ${index + 1}`,
      status: "DOI_VERIFIED",
      ux_group: "verified",
      matched_title: `Title ${index + 1}`,
      confidence: 1,
    }));

    const meta = getCitationReportExportMeta(
      {
        type: "citation_report",
        results: citations,
      },
      citations,
    );

    expect(meta.citationCount).toBe(260);
    expect(meta.isLargeReport).toBe(true);
    expect(meta.preferCompactJson).toBe(true);
  });
});
