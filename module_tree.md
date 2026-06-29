# Citation Check (DOI, Identifier & Metadata) - Module Assessment Tree

Dưới đây là sơ đồ cập nhật các thành phần (modules) liên quan đến tính năng **Citation Check** trong project hiện tại. Snapshot này đã được đối chiếu trực tiếp với mã nguồn ngày **2026-06-29**.

Phạm vi hiện tại không chỉ còn DOI đơn lẻ. Citation pipeline bây giờ bao gồm:

- Batch verification cho nhiều dòng reference trong một lần paste.
- Exact identifier verification cho **DOI, PMID, PMCID, OpenAlex ID**.
- No-DOI metadata matching với Crossref, OpenAlex, DataCite, Semantic Scholar và web fallback có kiểm soát.
- Metadata completion / export (`formatted_apa`, `formatted_bibtex`, `csl_json`) chỉ khi match đủ mạnh.
- Frontend renderer riêng cho citation report và export CSV / JSON / BibTeX.

## 1. Backend (Python / FastAPI)

Đây là nơi chứa logic xử lý chính: tách reference, phân loại input, gọi scholarly sources, chấm điểm candidates và dựng report payload cho chat/UI.

### 1.1. Lớp Core / Dịch vụ (Service Layer) - Quan trọng nhất
* **`backend/app/services/tools/citation_batch_service.py`**
  * **Vai trò:** Lớp orchestration hiện tại cho citation verification khi người dùng paste cả bibliography hoặc nhiều citation cùng lúc. File này chịu trách nhiệm tách occurrences, giữ nguyên thứ tự input, reuse cache trong cùng request, phân nhóm trạng thái, dựng `summary`, `statistics`, và payload dạng `citation_report`.
  * **Cần đụng khi:** Thay đổi cách batch verify, summary text, exportability, grouping verified/review/problem, hoặc cách chat/UI nhận report tổng.

* **`backend/app/services/tools/citation_checker.py`**
  * **Vai trò:** Engine xác minh lõi. Xử lý exact DOI / identifier lookup, parse metadata, lấy candidates từ scholarly sources, compare và ra status cuối cùng như `DOI_VERIFIED`, `IDENTIFIER_VERIFIED`, `METADATA_VERIFIED`, `LIKELY_MATCH`, `NO_MATCH_FOUND`, `PARSE_FAILED`.
  * **Cần đụng khi:** Đổi verification policy, status enum, lookup/fallback strategy, safety caps, exact-identifier behavior hoặc zero-hallucination rules.

* **`backend/app/services/tools/citation/parser.py`**
  * **Vai trò:** Parse reference metadata, detect reference preamble, extract DOI/PMID/PMCID/OpenAlex markers, tách citation items từ bibliography và build fallback title query.
  * **Cần đụng khi:** Nâng cấp parser cho format citation mới hoặc giảm false positive lúc split bibliography.

* **`backend/app/services/tools/citation/scoring.py`**
  * **Vai trò:** Chứa field-level evidence và thuật toán scoring giữa reference và candidate (`title`, `authors`, `year`, `venue`, `volume_issue_pages`), đồng thời build reason text cho từng trạng thái.
  * **Cần đụng khi:** Đổi trọng số, ngưỡng match, hoặc logic explainable evidence.

* **`backend/app/services/tools/citation/formatters.py`**
  * **Vai trò:** Sinh `completed_metadata`, APA-like text, BibTeX và CSL JSON từ candidate đã đủ mạnh.
  * **Cần đụng khi:** Thay đổi export format hoặc policy “chỉ export khi verified”.

* **`backend/app/services/tools/citation/sources/*.py`**
  * **Vai trò:** Adapter tới Crossref, OpenAlex, DataCite, Semantic Scholar, Publisher metadata và web-search fallback.
  * **Cần đụng khi:** Thêm nguồn mới, đổi provider web fallback, thay timeout/retry/normalization theo từng nguồn.

### 1.2. Lớp API / Routing (API Layer)
* **`backend/app/api/v1/endpoints/tools.py`**
  * **Vai trò:** Expose hai endpoint citation chính:
    * `POST /api/v1/tools/verify-citations` — batch API mới.
    * `POST /api/v1/tools/verify-citation` — legacy compatibility endpoint.
  * **Cần đụng khi:** Thay đổi request/response contract hoặc persist tool interaction vào lịch sử chat.

* **`backend/app/services/chat_service.py`**
  * **Vai trò:** Deterministic execution path khi chat explicit yêu cầu verify citation, đồng thời persist `message_type="citation_report"` vào `chat_messages`.
  * **Cần đụng khi:** Thay đổi cách chat mode `verification` hoặc auto-mode gọi citation pipeline.

### 1.3. Lớp Schemas (Data Models)
* **`backend/app/schemas/tools.py`**
  * **Vai trò:** Khai báo `VerifyCitationRequest`, `CitationBatchVerifyRequest`, `CitationItem`, `CitationBatchSummary`, `CitationReportResponse`, `CitationBatchVerifyResponse`.
  * **Cần đụng khi:** Thêm hoặc đổi field ở payload trả về cho frontend.

### 1.4. Lớp LLM & Routing Tool (AI/Agent Layer)
* **`backend/app/services/llm_service.py`**
  * **Vai trò:** Khai báo tool schema `verify_citation` cho Groq function calling, đồng thời xử lý path `document_id` vs `text`.
* **`backend/app/services/heuristic_router.py`**
  * **Vai trò:** Fallback deterministic / heuristic khi Groq lỗi hoặc intent quá rõ ràng cho citation verification.
* **`backend/app/services/academic_policy.py`**
  * **Vai trò:** Giữ các guardrail học thuật, hạn chế over-claim và chuẩn hóa cách assistant mô tả kết quả citation.

### 1.5. Lớp Kiểm thử (Unit/Integration Tests)
* **`backend/tests/test_citation_batch_service.py`**
  * Kiểm tra batch extraction, summary, payload shape.
* **`backend/tests/test_citation_identifier_exact.py`**
  * Kiểm tra DOI / PMID / PMCID / OpenAlex exact verification.
* **`backend/tests/test_citation_metadata_matching.py`**
  * Kiểm tra field scoring và lựa chọn candidate cho nhánh no-DOI.
* **`backend/tests/test_citation_enrichment.py`**
  * Kiểm tra metadata completion / export fields.
* **`backend/tests/test_citation_web_search_fallback.py`**
  * Kiểm tra web fallback chỉ đóng vai trò hint, không bypass exact verification.
* **`backend/tests/test_academic_verification_flow.py`**
  * Kiểm tra flow tích hợp từ request đến response.

---

## 2. Frontend (Next.js / TypeScript)

Khu vực này nhận data từ backend, đồng bộ state phiên chat và render citation report thành card có thể review/export.

### 2.1. Lớp Gọi API (Network Layer)
* **`frontend/lib/api.ts`**
  * **Vai trò:** Có cả `verifyCitation(...)` cho legacy endpoint và `verifyCitations(...)` cho batch endpoint hiện tại.
  * **Cần đụng khi:** Thay đổi path API, request body hoặc kiểu payload trả về.

### 2.2. Lớp Định nghĩa Kiểu (Types)
* **`frontend/lib/types.ts`**
  * **Vai trò:** Khai báo `CitationItem`, `CitationBatchSummary`, `CitationReportPayload` và các field evidence/export mà UI dùng để render.
  * **Cần đụng khi:** Backend thêm field mới như `field_evidence`, `source_diagnostics`, `completed_metadata`, `resolver_chain`, `matched_by`.

### 2.3. Lớp Hiển thị (UI Components)
* **`frontend/components/citation-report.tsx`**
  * **Vai trò:** Card render chính cho citation report: phân nhóm verified / needs review / problems, show evidence, show candidates, export CSV / JSON / BibTeX.
  * **Cần đụng khi:** Thay đổi UX review, badge status, collapsible details hoặc export controls.

* **`frontend/components/tool-results.tsx`**
  * **Vai trò:** Master dispatcher. Route payload `message_type="citation_report"` hoặc `type="citation_report"` sang `CitationReportCard`. Đồng thời hỗ trợ `multi_tool_report` khi citation chạy cùng tool khác.
  * **Cần đụng khi:** Thay đổi contract render tool cards trong chat.

* **`frontend/components/chat-view.tsx`**
  * **Vai trò:** Entry point của mode `verification`; hỗ trợ import bibliography file và giới hạn word-count riêng cho verification flow.
  * **Cần đụng khi:** Đổi UX gửi citation hàng loạt hoặc prompt gợi ý cho mode verification.

### 2.4. Lớp Utility / Export
* **`frontend/lib/citation-report-export.ts`**
  * **Vai trò:** Build file export CSV / JSON / BibTeX từ citation report hiện có.
* **`frontend/lib/citation-file-import.ts`**
  * **Vai trò:** Đọc bibliography file trong browser, ước lượng số citation và đưa text vào input verification.

### 2.5. Route hỗ trợ
* **`frontend/app/chat/citation-checker/page.tsx`**
  * **Vai trò:** Route compatibility; hiện chỉ redirect sang `/chat?mode=verification`.

---

## Tóm lược: Thay đổi từ A-Z sẽ đi qua các file nào?

Nếu bạn thay đổi một phần lớn của Citation Check, thứ tự tác động thường sẽ là:

1. `backend/app/services/tools/citation_batch_service.py`
2. `backend/app/services/tools/citation_checker.py`
3. `backend/app/services/tools/citation/parser.py`
4. `backend/app/services/tools/citation/scoring.py`
5. `backend/app/services/tools/citation/formatters.py`
6. `backend/app/services/tools/citation/sources/*.py`
7. `backend/app/schemas/tools.py`
8. `backend/app/api/v1/endpoints/tools.py`
9. `backend/app/services/chat_service.py` hoặc `backend/app/services/llm_service.py` nếu flow chat/tool-call thay đổi
10. `frontend/lib/types.ts`
11. `frontend/lib/api.ts`
12. `frontend/components/citation-report.tsx`
13. `frontend/components/tool-results.tsx`
14. `frontend/lib/citation-report-export.ts`
15. Các file test backend/frontend liên quan

Nếu chỉ đổi UI review/export mà không chạm logic verify, bạn thường chỉ cần động tới cụm frontend ở bước 10-14.
