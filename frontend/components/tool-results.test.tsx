import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ToolResultsRenderer } from "@/components/tool-results";

describe("ToolResultsRenderer", () => {
  it("renders insufficient corpus journal match card", () => {
    render(
      <ToolResultsRenderer
        messageType="journal_list"
        content=""
        toolResults={{ type: "journal_list", data: [], status: "insufficient_corpus" }}
      />,
    );
    expect(screen.getByText(/Chưa đủ dữ liệu để gợi ý tạp chí/i)).toBeInTheDocument();
  });

  it("renders AI detection custom rule metadata", () => {
    render(
      <ToolResultsRenderer
        messageType="ai_writing_detection"
        content=""
        toolResults={{
          type: "ai_writing_detection",
          data: {
            score: 0.82,
            verdict: "LIKELY_AI",
            confidence: "MEDIUM",
            rule_source: "user_custom_rules",
            matched_rules: ["as an AI language model", "it is important to note that"],
          },
        }}
      />,
    );

    expect(screen.getByText(/Rule source: User custom rules/i)).toBeInTheDocument();
    expect(screen.getByText("as an AI language model")).toBeInTheDocument();
    expect(screen.getByText("it is important to note that")).toBeInTheDocument();
  });

  it("renders exact identifier citation provenance", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          data: [
            {
              citation: "PMID: 12345678",
              status: "IDENTIFIER_VERIFIED",
              verification_mode: "identifier_exact",
              input_identifier: "12345678",
              input_identifier_type: "pmid",
              matched_identifier: "12345678",
              matched_identifier_type: "pmid",
              matched_title: "Transformer Paper",
              matched_year: 2024,
              matched_doi: "10.5555/transformer",
              source: "openalex_exact",
              confidence: 1,
              reason: "PMID resolved exactly to a scholarly record. The supplied metadata conflicts with the resolved record.",
              metadata_consistency: "mismatch",
              field_evidence: {
                title: {
                  input: "Wrong Transformer Paper",
                  candidate: "Transformer Paper",
                  similarity: 0.31,
                  verdict: "mismatch",
                },
                exact_identifier: {
                  input: "12345678",
                  candidate: "12345678",
                  verdict: "exact",
                },
              },
              source_diagnostics: {
                openalex: { state: "matched", candidate_count: 1, detail: null },
              },
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Exact PMID/i)).toBeInTheDocument();
    expect(screen.getByText(/Đã xác minh định danh/i)).toBeInTheDocument();
    expect(screen.getAllByText("PMID 12345678").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Transformer Paper").length).toBeGreaterThan(0);
    expect(screen.getByText(/DOI: 10.5555\/transformer/i)).toBeInTheDocument();
    expect(screen.getByText(/Metadata consistency:/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Mismatch/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Field evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Source checks/i)).toBeInTheDocument();
  });

  it("renders detailed DOI metadata with explicit missing-field notes", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "doi_metadata",
          status: "verified",
          data: {
            doi: "10.1038/s41586-020-2649-2",
            title: "Array programming with NumPy",
            journal: "Nature",
            publisher: "Springer Science and Business Media LLC",
            publication_year: 2020,
            research_field: null,
            research_field_note: "Not directly available from Crossref/OpenAlex metadata.",
            main_topic: "Array programming with NumPy",
            main_topic_note: "Not directly available from Crossref/OpenAlex metadata. Inferred from the article title.",
            verification_status: "Valid DOI",
            confidence: 1,
            source: "Crossref",
            missing_fields: ["research_field"],
            notes: [
              "Not directly available from Crossref/OpenAlex metadata.",
              "Not directly available from Crossref/OpenAlex metadata. Inferred from the article title.",
            ],
          },
        }}
      />,
    );

    expect(screen.getByText(/DOI Analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/Verification status/i)).toBeInTheDocument();
    expect(screen.getByText("Valid DOI")).toBeInTheDocument();
    expect(screen.getByText(/Journal/i)).toBeInTheDocument();
    expect(screen.getByText("Nature")).toBeInTheDocument();
    expect(screen.getByText(/Publisher/i)).toBeInTheDocument();
    expect(screen.getByText("Springer Science and Business Media LLC")).toBeInTheDocument();
    expect(screen.getByText(/Publication year/i)).toBeInTheDocument();
    expect(screen.getByText("2020")).toBeInTheDocument();
    expect(screen.getAllByText(/Not directly available from Crossref\/OpenAlex metadata\./i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Missing fields: research_field/i)).toBeInTheDocument();
  });

  it("renders metadata-match evidence and hides exports for likely match", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          data: [
            {
              citation: "Attention is all you need. 2017.",
              status: "LIKELY_MATCH",
              verification_mode: "metadata_match",
              matched_title: "Attention is all you need",
              matched_year: 2017,
              source: "crossref",
              confidence: 0.88,
              reason: "Title matches strongly and year matches exactly. The evidence supports a likely match, but not a verified one.",
              field_evidence: {
                title: {
                  input: "Attention is all you need",
                  candidate: "Attention is all you need",
                  similarity: 1,
                  verdict: "match",
                },
                year: {
                  input: 2017,
                  candidate: 2017,
                  similarity: 1,
                  verdict: "exact",
                },
              },
              source_diagnostics: {
                crossref: { state: "matched", candidate_count: 1, detail: null },
                openalex: { state: "no_match", candidate_count: 0, detail: null },
                semantic_scholar: { state: "skipped", candidate_count: 0, detail: null },
              },
              candidates: [
                {
                  source: "crossref",
                  title: "Attention is all you need",
                  year: 2017,
                  score: 0.88,
                  missing_fields: ["authors", "venue"],
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Có khả năng khớp/i)).toBeInTheDocument();
    expect(screen.getByText(/Field evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Source checks/i)).toBeInTheDocument();
    expect(screen.getByText(/Score: 88%/i)).toBeInTheDocument();
    expect(screen.getByText(/Thiếu: authors, venue/i)).toBeInTheDocument();
    expect(screen.queryByText(/Copy APA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/BibTeX/i)).not.toBeInTheDocument();
  });

  it("renders intent disambiguation suggestions", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "intent_disambiguation",
          data: {
            candidates: [
              { feature: "ai_detection", label: "Nhận diện văn bản AI", confidence: 0.74 },
              { feature: "grammar", label: "Rà soát ngữ pháp", confidence: 0.69 },
            ],
          },
        }}
      />,
    );

    expect(screen.getByText(/Cần làm rõ tính năng/i)).toBeInTheDocument();
    expect(screen.getByText("Nhận diện văn bản AI")).toBeInTheDocument();
    expect(screen.getByText("Rà soát ngữ pháp")).toBeInTheDocument();
  });
});
