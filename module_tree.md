# Citation Check (DOI & Metadata) - Module Assessment Tree

Dưới đây là sơ đồ chi tiết các thành phần (modules) liên quan đến tính năng **Citation Check** (bao gồm kiểm tra DOI, đối chiếu Metadata không có DOI) trong kiến trúc của hệ thống. 

Nếu bạn muốn update hoặc nâng cấp tính năng này (ví dụ: thay đổi logic parse metadata, thêm nguồn tra cứu mới ngoài OpenAlex/Crossref, hay thay đổi giao diện hiển thị), bạn sẽ cần tác động đến các module được liệt kê dưới đây.

## 1. Backend (Python / FastAPI)

Đây là nơi chứa toàn bộ logic xử lý chính bao gồm parsing, deduplication, gọi API của bên thứ 3 và chấm điểm đối chiếu (scoring).

### 1.1. Lớp Core / Dịch vụ (Service Layer) - Quan trọng nhất
* **`backend/app/services/tools/citation_checker.py`**
  * **Vai trò:** Trái tim của tính năng. Nơi chứa logic trích xuất DOI bằng regex (`_extract_dois_from_text`), phân tách metadata đối với các citation không có DOI (`parse_reference_metadata`), tìm kiếm ứng viên qua OpenAlex (`pyalex`) và Crossref (`habanero`), thuật toán đối chiếu chuỗi và tính điểm (`score_candidate`), và ra quyết định kết quả cuối cùng (`choose_best_match`).
  * **Cần đụng khi:** Thay đổi thuật toán check DOI, nâng cấp logic string matching cho Metadata (ví dụ thay SequenceMatcher bằng embeddings), thêm thư viện tính điểm mới, format lại kết quả trả về cơ sở.

### 1.2. Lớp API / Routing (API Layer)
* **`backend/app/api/v1/endpoints/tools.py`**
  * **Vai trò:** Expose endpoint `/verify-citation`. Hàm `verify_citation` tiếp nhận text từ người dùng/frontend, gọi `citation_checker.verify()`, thống kê và compile payload trả về `CitationReportResponse`.
  * **Cần đụng khi:** Thay đổi API contract, thêm các trường input mới (parameter) hoặc thay đổi cấu trúc trả về HTTP.

### 1.3. Lớp Schemas (Data Models)
* **`backend/app/schemas/tools.py`**
  * **Vai trò:** Nơi khai báo các Pydantic class: `VerifyCitationRequest`, `CitationItem` (chứa các field metadata_match_doi, confidence, verification_mode...), `CitationReportResponse`.
  * **Cần đụng khi:** Bạn map thêm trường dữ liệu nào đó ở service (`citation_checker.py`) và muốn API serializable trường đó xuống chuỗi JSON trả về cho frontend.

### 1.4. Lớp LLM & Routing Tool (AI/Agent Layer)
* **`backend/app/services/llm_service.py`**
  * **Vai trò:** Khai báo function scheme/tool `verify_citation` cho LLM hiểu để tự động gọi khi người dùng yêu cầu trong chat.
* **`backend/app/services/heuristic_router.py`**
  * **Vai trò:** Chứa logic route deterministic (heuristics). Chặn prompt và ép chạy hệ thống `verify_citation` nếu người dùng truyền thẳng chuỗi có chứa nhiều DOI hay bắt đầu bằng các từ khoá check trích dẫn.
* **`backend/app/services/academic_policy.py`**
  * **Vai trò:** Đưa ra các system prompt limits để quản lý khi nào AI được gọi citation check.

### 1.5. Lớp Kiểm thử (Unit/Integration Tests)
* **`backend/tests/test_citation_metadata_matching.py`**
  * Nơi chứa test cases độc lập cho thuật toán chấm điểm match (match title, authors, year...).
* **`backend/tests/test_academic_verification_flow.py`** & **`backend/tests/test_chat_academic_db_routing.py`**
  * Đảm bảo luồng request check citation thông suốt từ nhận chữ -> tách request -> trả kết quả. 

---

## 2. Frontend (Next.js / TypeScript)

Khu vực này nhận data API từ backend, xử lý state và vẽ UI/UX cho người dùng.

### 2.1. Lớp Gọi API (Network Layer)
* **`frontend/lib/api.ts`**
  * **Vai trò:** Có hàm `verifyCitation(token, sessionId, text)` gọi POST tới server `/api/v1/tools/verify-citation`.
  * **Cần đụng khi:** Thay đổi cách truyền parameter lên Backend.

### 2.2. Lớp Định nghĩa Kiểu (Types)
* **`frontend/lib/types.ts`**
  * **Vai trò:** Khai báo Type/Interface TypeScript cho Tool, ví dụ: type `citation_report` và interface của từng Item trả về tương tự như Pydantic bên Backend.
  * **Cần đụng khi:** Cập nhật các trường hiển thị, TypeScript báo lỗi thiếu trường.

### 2.3. Lớp Hiển thị (UI Components)
* **`frontend/components/tool-results.tsx`**
  * **Vai trò:** Quan trọng nhất của Frontend. Nơi render các Tool Card. Nó sẽ switch dựa trên `type === 'citation_report'` để vẽ ra các component box hiển thị Citation có DOI thì xanh (Verified), có Metadata match mập mờ thì vàng (Possible Match), hay không ra gì (Parse failed).
  * **Cần đụng khi:** Muốn redesign lại UI, chia bar màu mức độ confidence, show/hide các text liên quan đến match title / match year.
* **`frontend/components/chat-view.tsx`**
  * **Vai trò:** Flow wrap tổng chứa chat và gọi render tool-results.

---

## Tóm lược: Thay đổi từ A-Z sẽ đi qua các file nào?

Giả sử bạn cập nhật một thuật toán check DOI mới trả về thêm hệ số uy tín của nhà xuất bản bên cạnh kết quả check citation thông thường, thứ tự file bạn sửa sẽ là:
1. `backend/app/services/tools/citation_checker.py` (Móc thêm nguồn dữ liệu, nhét vào struct)
2. `backend/app/schemas/tools.py` (Bổ sung biến `publisher_trust_score` cho class `CitationItem`)
3. `backend/app/api/v1/endpoints/tools.py` (Tiếp nhận và parse biến xuống response)
4. (Tuỳ chọn cập nhật LLM scheme ở `llm_service.py` nếu cần AI luận về score này)
5. `frontend/lib/types.ts` (Thêm thuộc tính `publisher_trust_score?: number;` vào kiểu dữ liệu)
6. `frontend/components/tool-results.tsx` (Vẽ thêm badge hiển thị điểm `trust_score` này lên UI)
7. Cập nhật các file Tests ở backend để không gây lỗi CI/CD.
