import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { CitationReportCard } from "@/components/citation-report";
import { ToolResultsRenderer } from "@/components/tool-results";
import { buildCitationReportBibtex } from "@/lib/citation-report-export";

describe("ToolResultsRenderer", () => {
  it("renders journal match links as clickable anchors", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "journal_match",
          status: "matched",
          matches: [
            {
              id: "venue-1",
              name: "Quantum Network Security Journal",
              journal: "Quantum Network Security Journal",
              score: 0.82,
              publisher: "Trusted Computing Society",
              issn: "1234-5678",
              links: [
                { label: "Journal home", url: "https://example.org/quantum-network-security-journal", type: "homepage" },
                { label: "SJR page", url: "https://www.scimagojr.com/journalsearch.php?q=21111111111", type: "sjr" },
              ],
              metrics: { sjr_quartile: "Q1" },
            },
          ],
        }}
      />,
    );

    const homeLink = screen.getByRole("link", { name: /journal home/i });
    const sjrLink = screen.getByRole("link", { name: /sjr page/i });
    expect(homeLink).toHaveAttribute("href", "https://example.org/quantum-network-security-journal");
    expect(homeLink).toHaveAttribute("target", "_blank");
    expect(homeLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(sjrLink).toHaveAttribute("href", "https://www.scimagojr.com/journalsearch.php?q=21111111111");
  });

  it("handles journal matches with empty links gracefully", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "journal_match",
          status: "matched",
          matches: [
            {
              id: "venue-2",
              name: "Privacy Governance Notes",
              journal: "Privacy Governance Notes",
              score: 0.31,
              links: [],
              link_warning: "Chua co lien ket da xac minh trong metadata venue hien co.",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/privacy governance notes/i)).toBeInTheDocument();
    expect(screen.getByText(/chua co lien ket da xac minh/i)).toBeInTheDocument();
  });

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

  it("renders journal lookup failure with resolved source record and checked sources", () => {
    render(
      <ToolResultsRenderer
        messageType="journal_list"
        content=""
        toolResults={{
          type: "journal_list",
          data: [],
          status: "record_not_found",
          source_record: {
            title: "Is working memory domain-general or domain-specific?",
            authors: ["Nazbanou Nozari", "Randi C. Martin"],
            source: "OpenAlex",
            confidence: 0.82,
          },
          checked_sources: [
            { name: "Internal academic database", state: "no_match", candidate_count: 0 },
            { name: "Crossref", state: "matched", candidate_count: 1 },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Chưa resolve được tài liệu nguồn/i)).toBeInTheDocument();
    expect(screen.getByText(/Is working memory domain-general or domain-specific\?/i)).toBeInTheDocument();
    expect(screen.getByText(/Nguồn đã kiểm tra/i)).toBeInTheDocument();
    expect(screen.getByText("Crossref")).toBeInTheDocument();
  });

  it("renders academic lookup fallback result with confidence and checked sources", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "academic_lookup",
          status: "external_found",
          source_mode: "external_scholarly",
          confidence: 0.92,
          confidence_label: "High",
          external_search_used: true,
          checked_sources: [
            { name: "Internal academic database", state: "no_match", candidate_count: 0 },
            { name: "OpenAlex", state: "matched", candidate_count: 1 },
            { name: "Crossref", state: "matched", candidate_count: 1 },
          ],
          data: {
            records: [
              {
                title: "Is working memory domain-general or domain-specific?",
                authors: ["Nazbanou Nozari", "Randi C. Martin"],
              venue: "Psychonomic Bulletin & Review",
              year: 2024,
              source: "OpenAlex",
              confidence: 0.92,
              abstract: "This paper discusses competing views of working memory.",
              doi: "10.1234/example",
              volume: "28",
              issue: "11",
              pages: "1023-1036",
              pmid: "39019705",
              pmcid: "PMC11540753",
              match_status: "best_match",
              subjects: ["Cognitive psychology"],
              keywords: ["working memory"],
              score: 0.92,
            },
            ],
            best_record: {
              title: "Is working memory domain-general or domain-specific?",
              authors: ["Nazbanou Nozari", "Randi C. Martin"],
              venue: "Psychonomic Bulletin & Review",
              year: 2024,
              source: "OpenAlex",
              confidence: 0.92,
              volume: "28",
              issue: "11",
              pages: "1023-1036",
              pmid: "39019705",
              pmcid: "PMC11540753",
              subjects: ["Cognitive psychology"],
              keywords: ["working memory"],
            },
            notes: ["Resolved the lookup query from a pasted paper header (title + author line)."],
            internal_result: {
              count: 0,
              best_score: 0,
              confidence: 0,
            },
          },
        }}
      />,
    );

    expect(screen.getByText(/Đã fallback sang nguồn học thuật bên ngoài/i)).toBeInTheDocument();
    expect(screen.getByText(/Confidence: High/i)).toBeInTheDocument();
    expect(screen.getByText(/Không tìm thấy đủ mạnh trong dữ liệu nội bộ/i)).toBeInTheDocument();
    expect(screen.getAllByText(/OpenAlex/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Crossref/i)).toBeInTheDocument();
    expect(screen.getByText(/Cognitive psychology/i)).toBeInTheDocument();
    expect(screen.getByText(/PMID: 39019705/i)).toBeInTheDocument();
    expect(screen.getByText(/Vol: 28/i)).toBeInTheDocument();
    expect(screen.getByText(/Pages: 1023-1036/i)).toBeInTheDocument();
  });

  it("renders low-confidence academic lookup without promoting a best match", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "academic_lookup",
          status: "low_confidence",
          source_mode: "external_scholarly",
          confidence: 0.28,
          external_search_used: true,
          checked_sources: [
            { name: "Internal academic database", state: "no_match", candidate_count: 0 },
            { name: "Crossref", state: "matched", candidate_count: 1 },
            { name: "Semantic Scholar", state: "rate_limited", candidate_count: 0, detail: "HTTP 429" },
          ],
          data: {
            records: [],
            best_record: null,
            low_confidence_records: [
              {
                title: "Working Memory in Chinese Text Comprehension",
                venue: "Psi Chi Journal of Psychological Research",
                year: 2021,
                source: "Crossref",
                confidence: 0.28,
                match_status: "low_confidence",
                score: 0.28,
              },
            ],
            notes: ["The closest external candidates stayed below the verification threshold."],
            internal_result: {
              count: 0,
              best_score: 0,
              confidence: 0,
            },
          },
        }}
      />,
    );

    expect(screen.getAllByText(/Không tìm thấy kết quả đủ tin cậy/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Tài liệu phù hợp nhất/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Candidate độ tin cậy thấp/i)).toBeInTheDocument();
    expect(screen.getByText(/Working Memory in Chinese Text Comprehension/i)).toBeInTheDocument();
    expect(screen.getByText(/Rate limited/i)).toBeInTheDocument();
  });

  it("renders author publication search results without falling back to citation report UI", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "author_publication_search",
          status: "matched",
          source_doi: "10.1038/s41586-020-2649-2",
          source_title: "Array programming with NumPy",
          source_record: {
            title: "Array programming with NumPy",
            authors: ["Stefan van der Walt", "Ralf Gommers"],
            venue: "Nature",
            year: 2020,
            source: "Crossref",
            confidence: 1,
            doi: "10.1038/s41586-020-2649-2",
          },
          authors: [
            {
              name: "Stefan van der Walt",
              external_ids: { openalex: "A500000001" },
              confidence: 0.98,
              checked_sources: [
                { name: "Internal academic database", state: "no_match", candidate_count: 0 },
                { name: "OpenAlex", state: "matched", candidate_count: 2 },
              ],
              publications: [
                {
                  title: "Python for scientific computing",
                  authors: ["Stefan van der Walt"],
                  venue: "Computing in Science & Engineering",
                  year: 2021,
                  source: "OpenAlex",
                  confidence: 0.84,
                  doi: "10.1109/example.2021.1",
                },
              ],
              notes: ["Author identity was resolved from an OpenAlex author profile."],
            },
          ],
          external_search_used: true,
          checked_sources: [
            { name: "Internal academic database", state: "no_match", candidate_count: 0 },
            { name: "OpenAlex", state: "matched", candidate_count: 2 },
          ],
          notes: ["External scholarly sources were checked to expand author-publication coverage beyond the resolved source paper."],
        }}
      />,
    );

    expect(screen.getByText(/Đã tìm publication khác của tác giả/i)).toBeInTheDocument();
    expect(screen.getByText(/Array programming with NumPy/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Stefan van der Walt/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Python for scientific computing/i)).toBeInTheDocument();
    expect(screen.getAllByText(/OpenAlex/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Báo cáo xác minh trích dẫn/i)).not.toBeInTheDocument();
  });

  it("does not render an empty citation report when routing says general QA", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content="Mình chưa tìm thấy publication phù hợp."
        toolResults={{
          type: "citation_report",
          results: [],
          summary: {
            total_count: 0,
            verified_count: 0,
            review_count: 0,
            problem_count: 0,
            temporary_issue_count: 0,
            status_counts: {},
          },
          meta: {
            routing: {
              resolved_feature: "general_qa",
            },
          },
        }}
      />,
    );

    expect(screen.queryByText(/Báo cáo xác minh trích dẫn/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total citations/i)).not.toBeInTheDocument();
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

    expect(screen.getByText(/Rule source: Custom rules/i)).toBeInTheDocument();
    expect(screen.getByText(/Matched custom rules/i)).toBeInTheDocument();
    expect(screen.getByText("as an AI language model")).toBeInTheDocument();
    expect(screen.getByText("it is important to note that")).toBeInTheDocument();
  });

  it("renders structured ai_detection payload with evidence and suggestions", () => {
    render(
      <ToolResultsRenderer
        messageType="ai_writing_detection"
        content=""
        toolResults={{
          type: "ai_detection",
          data: {
            type: "ai_detection",
            mode: "deep",
            score: 0.61,
            final_score: 0.61,
            custom_rule_score: 0.42,
            model_score: 0.68,
            roberta_score: 0.7,
            risk_level: "medium",
            verdict: "POSSIBLY_AI",
            confidence: "MEDIUM",
            method: "ensemble",
            flags: ["Matched 2 custom rule signals"],
            details: {},
            detectors_used: ["rule_based", "roberta_gpt2_detector"],
            skipped_detectors: [],
            rule_source: "user_custom_rules",
            matched_rules: [
              {
                rule_id: "rule-1",
                rule_name: "Generic academic phrasing",
                rule_type: "hybrid",
                severity: "medium",
                weight: 0.3,
                matched_text: "It is important to note that...",
                reason: "Generic transition phrase.",
                confidence: 0.84,
                location: { scope: "paragraph", paragraph_index: 1 },
              },
            ],
            evidence: [
              {
                text: "It is important to note that...",
                reason: "Generic transition phrase.",
                rule_id: "rule-1",
                severity: "medium",
                paragraph_index: 1,
              },
            ],
            explanation: "The text shows moderate AI-like signals.",
            suggestions: ["Add more specific examples."],
            disclaimer: "AI-writing detection is probabilistic and should not be treated as definitive proof.",
            warnings: [],
          },
        }}
      />,
    );

    expect(screen.getByText(/Generic academic phrasing/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Add more specific examples\./i)).toBeInTheDocument();
    expect(screen.getByText(/Baseline: 68.0%/i)).toBeInTheDocument();
  });

  it("renders AI detection disclaimer", () => {
    render(
      <ToolResultsRenderer
        messageType="ai_writing_detection"
        content=""
        toolResults={{
          type: "ai_writing_detection",
          data: {
            score: 0.41,
            verdict: "UNCERTAIN",
          },
        }}
      />,
    );

    expect(
      screen.getByText(/Kết quả này chỉ là tín hiệu ước lượng về khả năng văn bản do AI hỗ trợ viết\./i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This result is a likelihood\/risk signal only\./i),
    ).toBeInTheDocument();
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
    expect(screen.getAllByText(/Đã xác minh định danh/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("PMID 12345678").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Transformer Paper").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/DOI: 10.5555\/transformer/i).length).toBeGreaterThan(0);
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

  it("renders requested DOI authors prominently with expand and collapse support", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "doi_metadata",
          status: "verified",
          requested_field: "authors",
          data: {
            doi: "10.1038/s41586-020-2649-2",
            title: "Array programming with NumPy",
            journal: "Nature",
            publisher: "Springer Science and Business Media LLC",
            publication_year: 2020,
            authors: [
              "Charles R. Harris",
              "K. Jarrod Millman",
              "Stéfan J. van der Walt",
              "Ralf Gommers",
              "Pauli Virtanen",
              "David Cournapeau",
              "Eric Wieser",
              "Julian Taylor",
              "Sebastian Berg",
              "Nathaniel J. Smith",
              "Robert Kern",
              "Travis E. Oliphant",
            ],
            author_count: 12,
            verification_status: "Valid DOI",
            confidence: 1,
            source: "Crossref",
            missing_fields: [],
            notes: [],
          },
        }}
      />,
    );

    expect(screen.getByText(/Authors \(12\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Requested field/i)).toBeInTheDocument();
    expect(screen.getByText(/\[1\]/i)).toBeInTheDocument();
    expect(screen.getByText(/Charles R\. Harris/i)).toBeInTheDocument();
    expect(screen.getByText(/Travis E\. Oliphant/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /thu gọn danh sách tác giả/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /thu gọn danh sách tác giả/i }));

    expect(screen.queryByText(/Travis E\. Oliphant/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hiển thị thêm 4 tác giả/i })).toBeInTheDocument();
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

    const badge = screen.getAllByText(/Likely match \/ Cần kiểm tra thêm/i)[0].closest("span");
    expect(badge).toHaveClass("text-amber-700");
    expect(badge).not.toHaveClass("text-emerald-700");
    expect(screen.getByText(/Field evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Source checks/i)).toBeInTheDocument();
    expect(screen.getByText(/Score: 88%/i)).toBeInTheDocument();
    expect(screen.getByText(/Thiếu: authors, venue/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Needs review/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Copy APA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Copy BibTeX/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Copy CSL/i)).not.toBeInTheDocument();
  });

  it("renders possible and ambiguous metadata matches as review-needed", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          data: [
            {
              citation: "Candidate one",
              status: "POSSIBLE_MATCH",
              verification_mode: "metadata_match",
            },
            {
              citation: "Candidate two",
              status: "AMBIGUOUS_MATCH",
              verification_mode: "metadata_match",
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByText(/Possible match \/ Độ tin cậy thấp/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Ambiguous \/ Có nhiều ứng viên gần giống/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Needs review/i).length).toBeGreaterThan(0);
  });

  it("renders citation evidence chain fields", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          data: [
            {
              citation: "Attention is all you need. 2017.",
              status: "METADATA_VERIFIED",
              verification_mode: "metadata_match",
              matched_title: "Attention is all you need",
              matched_doi: "10.5555/attention",
              matched_year: 2017,
              source: "crossref",
              confidence: 0.96,
              matched_by: "publisher_meta_confirmed",
              resolved_url: "https://publisher.example.org/attention",
              resolver_chain: ["crossref", "publisher_meta"],
              evidence_urls: [
                "https://publisher.example.org/attention",
                "https://example.org/attention",
              ],
              candidate_gap: 0.12,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Matched by: Publisher meta confirmed/i)).toBeInTheDocument();
    expect(screen.getByText(/Gap: 12.0%/i)).toBeInTheDocument();
    expect(screen.getByText(/Resolved URL:/i)).toBeInTheDocument();
    expect(screen.getByText(/Resolver chain:/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence URLs/i)).toBeInTheDocument();
    expect(screen.getAllByText("https://publisher.example.org/attention").length).toBeGreaterThan(0);
  });

  it("renders web-search discovery evidence for citation fallback", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          data: [
            {
              citation: "Attention is all you need. 2017.",
              status: "DOI_VERIFIED",
              verification_mode: "metadata_match",
              matched_title: "Attention is all you need",
              matched_doi: "10.5555/attention",
              source: "crossref_doi",
              discovered_from: "web_search",
              source_domain: "example.org",
              web_search_provider: "generic_json",
              evidence_urls: [
                "https://example.org/attention",
                "https://doi.org/10.5555/attention",
              ],
              resolver_chain: ["web_search", "crossref_exact"],
              matched_by: "doi_exact",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/DOI\/URL discovered via web search/i)).toBeInTheDocument();
    expect(screen.getByText(/Domain: example.org/i)).toBeInTheDocument();
    expect(screen.getByText(/Web provider:/i)).toBeInTheDocument();
    expect(screen.getByText(/Resolver chain:/i)).toBeInTheDocument();
    expect(screen.getAllByText("https://example.org/attention").length).toBeGreaterThan(0);
  });

  it("renders batch citation summary from results payload shape", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          summary: {
            total_count: 3,
            verified_count: 1,
            review_count: 1,
            problem_count: 1,
            temporary_issue_count: 0,
            status_counts: {
              DOI_VERIFIED: 1,
              LIKELY_MATCH: 1,
              DOI_NOT_FOUND: 1,
            },
            default_summary_text: "1 verified, 1 review, 1 problem.",
          },
          results: [
            {
              index: 1,
              raw_citation: "Verified citation",
              citation: "10.1000/verified",
              status: "DOI_VERIFIED",
              ux_group: "verified",
              matched_title: "Verified title",
              matched_doi: "10.1000/verified",
              matched_year: 2024,
              matched_venue: "Journal A",
              confidence: 1,
            },
            {
              index: 2,
              raw_citation: "Review citation",
              citation: "Review citation",
              status: "LIKELY_MATCH",
              ux_group: "review",
              matched_title: "Review title",
              confidence: 0.83,
              short_issue: "Needs manual review.",
            },
            {
              index: 3,
              raw_citation: "Problem citation",
              citation: "10.1000/missing",
              status: "DOI_NOT_FOUND",
              ux_group: "problem",
              confidence: 0,
              short_issue: "DOI did not resolve.",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Báo cáo xác minh trích dẫn/i)).toBeInTheDocument();
    expect(screen.queryByText(/Citation Checker/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Total citations/i)).toBeInTheDocument();
    expect(screen.getAllByText("3").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Needs review/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Problems/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/1 verified, 1 review, 1 problem\./i)).toBeInTheDocument();
    expect(screen.getAllByText(/Verified title/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Review title/i).length).toBeGreaterThan(0);
  });

  it("renders the extracted citation report component with summary, filters, and exports", () => {
    render(
      <CitationReportCard
        summary={{
          total_count: 2,
          verified_count: 1,
          review_count: 1,
          problem_count: 0,
          temporary_issue_count: 0,
          status_counts: {
            DOI_VERIFIED: 1,
            LIKELY_MATCH: 1,
          },
          default_summary_text: "1 verified, 1 review.",
        }}
        citations={[
          {
            index: 1,
            raw_citation: "10.1000/verified",
            citation: "10.1000/verified",
            status: "DOI_VERIFIED",
            ux_group: "verified",
            matched_title: "Verified title",
            confidence: 1,
            formatted_bibtex: "@article{verified}",
          },
          {
            index: 2,
            raw_citation: "Review citation",
            citation: "Review citation",
            status: "LIKELY_MATCH",
            ux_group: "review",
            matched_title: "Review title",
            confidence: 0.84,
          },
        ]}
        reportPayload={{
          type: "citation_report",
          text: "1 verified, 1 review.",
        }}
      />,
    );

    expect(screen.getByText(/Báo cáo xác minh trích dẫn/i)).toBeInTheDocument();
    expect(screen.getByText(/1 verified, 1 review\./i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Verified/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Needs review/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export CSV/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export JSON/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export BibTeX/i })).toBeEnabled();
  });

  it("renders citation reports even when the message type is plain text", () => {
    render(
      <ToolResultsRenderer
        messageType="text"
        content=""
        toolResults={{
          type: "citation_report",
          summary: {
            total_count: 1,
            verified_count: 0,
            review_count: 1,
            problem_count: 0,
            temporary_issue_count: 0,
            status_counts: { UNVERIFIED_NO_DOI: 1 },
            default_summary_text: "1 review.",
          },
          results: [
            {
              index: 1,
              raw_citation: "A blog source without enough metadata",
              citation: "A blog source without enough metadata",
              status: "UNVERIFIED_NO_DOI",
              ux_group: "review",
              source_type: "blog_or_non_scholarly",
              confidence: 0.1,
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("citation-report-card")).toBeInTheDocument();
    expect(screen.getByText(/Báo cáo xác minh trích dẫn/i)).toBeInTheDocument();
  });

  it("keeps citation report constrained within the chat width and wraps long DOI values", () => {
    const longDoi = "10.1234/this-is-a-very-long-doi-fragment-that-should-wrap-cleanly-inside-the-report-card-without-forcing-page-overflow";

    render(
      <CitationReportCard
        summary={{
          total_count: 1,
          verified_count: 1,
          review_count: 0,
          problem_count: 0,
          temporary_issue_count: 0,
          status_counts: { DOI_VERIFIED: 1 },
          default_summary_text: "1 verified.",
        }}
        citations={[
          {
            index: 1,
            raw_citation: longDoi,
            citation: longDoi,
            status: "DOI_VERIFIED",
            ux_group: "verified",
            matched_title: "A long-title citation used to verify responsive wrapping inside the chat report",
            matched_doi: longDoi,
            matched_venue: "Journal of Extremely Long Layout Regression Tests",
            confidence: 1,
          },
        ]}
      />,
    );

    expect(screen.getByTestId("citation-report-card")).toHaveClass("w-full", "max-w-full", "overflow-hidden");
    expect(screen.getAllByText(longDoi).some((node) => node.className.includes("break-all"))).toBe(true);
  });

  it("does not crash when optional citation fields are missing", () => {
    render(
      <CitationReportCard
        summary={{
          total_count: 1,
          verified_count: 0,
          review_count: 1,
          problem_count: 0,
          temporary_issue_count: 0,
          status_counts: { UNVERIFIED_NO_DOI: 1 },
          default_summary_text: "1 review.",
        }}
        citations={[
          {
            index: 1,
            raw_citation: "Sparse citation",
            citation: "Sparse citation",
            status: "UNVERIFIED_NO_DOI",
            ux_group: "review",
            source_type: "blog_or_non_scholarly",
            confidence: 0,
            matched_title: null,
            matched_doi: null,
            matched_year: null,
            matched_venue: null,
          },
        ]}
      />,
    );

    expect(screen.getByTestId("citation-report-card")).toBeInTheDocument();
    expect(screen.getByText(/Báo cáo xác minh trích dẫn/i)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows CSV and JSON export buttons for citation reports", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          summary: {
            total_count: 1,
            verified_count: 1,
            review_count: 0,
            problem_count: 0,
            temporary_issue_count: 0,
            status_counts: { DOI_VERIFIED: 1 },
          },
          results: [
            {
              index: 1,
              raw_citation: "Verified citation",
              citation: "10.1000/verified",
              status: "DOI_VERIFIED",
              ux_group: "verified",
              matched_title: "Verified title",
              confidence: 1,
              formatted_bibtex: "@article{verified}",
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: /Export CSV/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export JSON/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export BibTeX/i })).toBeEnabled();
  });

  it("disables BibTeX export when no verified BibTeX entries exist", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          results: [
            {
              index: 1,
              raw_citation: "Weak citation",
              citation: "Weak citation",
              status: "LIKELY_MATCH",
              ux_group: "review",
              matched_title: "Weak title",
              confidence: 0.81,
              formatted_bibtex: "@article{should_not_show}",
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: /Export BibTeX/i })).toBeDisabled();
    expect(screen.getByText(/No verified BibTeX entries available yet\./i)).toBeInTheDocument();
  });

  it("builds BibTeX export from verified citations only", () => {
    const bibtex = buildCitationReportBibtex([
      {
        citation: "Verified citation",
        status: "DOI_VERIFIED",
        formatted_bibtex: "@article{verified,\n  title={Verified}\n}",
      },
      {
        citation: "Review citation",
        status: "LIKELY_MATCH",
        formatted_bibtex: "@article{review,\n  title={Review}\n}",
      },
      {
        citation: "Temporary citation",
        status: "UNVERIFIED",
        formatted_bibtex: "@article{temporary,\n  title={Temporary}\n}",
      },
      {
        citation: "Metadata citation",
        status: "METADATA_VERIFIED",
        formatted_bibtex: "@article{metadata,\n  title={Metadata}\n}",
      },
    ]);

    expect(bibtex).toContain("@article{verified");
    expect(bibtex).toContain("@article{metadata");
    expect(bibtex).not.toContain("@article{review");
    expect(bibtex).not.toContain("@article{temporary");
  });

  it("filters citation report by ux group", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          results: [
            {
              index: 1,
              raw_citation: "Verified citation",
              citation: "10.1000/verified",
              status: "DOI_VERIFIED",
              ux_group: "verified",
              matched_title: "Verified title",
              confidence: 1,
            },
            {
              index: 2,
              raw_citation: "Review citation",
              citation: "Review citation",
              status: "LIKELY_MATCH",
              ux_group: "review",
              matched_title: "Review title",
              confidence: 0.82,
              short_issue: "Needs review.",
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByText(/Verified title/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Review title/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Verified/i }));
    expect(screen.getAllByText(/Verified title/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/Review title/i).length).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: /Needs review/i }));
    expect(screen.getAllByText(/Review title/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/Verified title/i).length).toBe(0);
  });

  it("renders mixed academic and blog citation rows with correct counts", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          summary: {
            total_count: 3,
            verified_count: 2,
            review_count: 1,
            problem_count: 0,
            temporary_issue_count: 0,
            status_counts: {
              DOI_VERIFIED: 1,
              METADATA_VERIFIED: 1,
              UNVERIFIED_NO_DOI: 1,
            },
            default_summary_text: "2 verified, 1 review.",
          },
          results: [
            {
              index: 1,
              raw_citation: "10.1000/verified",
              citation: "10.1000/verified",
              status: "DOI_VERIFIED",
              ux_group: "verified",
              matched_title: "Verified title",
              confidence: 1,
            },
            {
              index: 2,
              raw_citation: "A personal dengue blog post",
              citation: "A personal dengue blog post",
              status: "UNVERIFIED_NO_DOI",
              ux_group: "review",
              source_type: "blog_or_non_scholarly",
              reason: "Add the direct URL plus title, author/organization, and publication date.",
              confidence: 0.1,
            },
            {
              index: 3,
              raw_citation: "Academic metadata citation",
              citation: "Academic metadata citation",
              status: "METADATA_VERIFIED",
              ux_group: "verified",
              matched_title: "Metadata verified title",
              confidence: 0.94,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/2 verified, 1 review\./i)).toBeInTheDocument();
    expect(screen.getAllByText(/Needs review/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/A personal dengue blog post/i)).toBeInTheDocument();
  });

  it("renders summary and filters for a large citation report", () => {
    render(
      <ToolResultsRenderer
        messageType="citation_report"
        content=""
        toolResults={{
          type: "citation_report",
          summary: {
            total_count: 24,
            verified_count: 8,
            review_count: 8,
            problem_count: 8,
            temporary_issue_count: 0,
            status_counts: {
              DOI_VERIFIED: 8,
              LIKELY_MATCH: 8,
              DOI_NOT_FOUND: 8,
            },
            default_summary_text: "8 verified, 8 review, 8 problem.",
          },
          results: Array.from({ length: 24 }, (_, index) => ({
            index: index + 1,
            raw_citation: `Citation ${index + 1}`,
            citation: `Citation ${index + 1}`,
            status: index < 8 ? "DOI_VERIFIED" : index < 16 ? "LIKELY_MATCH" : "DOI_NOT_FOUND",
            ux_group: index < 8 ? "verified" : index < 16 ? "review" : "problem",
            matched_title: `Title ${index + 1}`,
            confidence: index < 8 ? 1 : index < 16 ? 0.82 : 0,
          })),
        }}
      />,
    );

    expect(screen.getByText(/Báo cáo xác minh trích dẫn/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Verified/i })).toBeInTheDocument();
    expect(screen.getAllByText(/Needs review/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Problems/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/8 verified, 8 review, 8 problem\./i)).toBeInTheDocument();
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
