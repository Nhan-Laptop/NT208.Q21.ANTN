from __future__ import annotations

from typing import Any


def _count(mapping: dict[str, Any], key: str) -> int:
    return int(mapping.get(key, 0) or 0)


def format_citation_summary(stats: dict[str, Any], *, no_citation_found: bool = False) -> str:
    total = _count(stats, "total")
    if no_citation_found or total == 0:
        return (
            "Mình chưa thấy citation hoặc DOI đủ rõ để xác minh. "
            "Bạn có thể gửi DOI đầy đủ, tiêu đề bài báo, tác giả hoặc một dòng reference đầy đủ để mình kiểm tra chính xác hơn."
        )

    valid = _count(stats, "valid")
    doi_verified = _count(stats, "doi_verified")
    verified = valid + doi_verified
    partial = _count(stats, "partial_match")
    hallucinated = _count(stats, "hallucinated")
    unverified = _count(stats, "unverified")
    doi_not_found = _count(stats, "doi_not_found")

    if doi_not_found > 0 and verified == 0 and partial == 0:
        return (
            "Mình đã thử xác minh DOI bạn cung cấp, nhưng hiện chưa tìm thấy bản ghi học thuật khớp hoàn toàn. "
            "Mình không dùng kết quả gần giống để thay thế cho DOI này, vì DOI là định danh cần khớp chính xác. "
            "Bạn nên đối chiếu lại DOI trên trang DOI, trang nhà xuất bản, hoặc gửi thêm tiêu đề bài báo để kiểm tra tiếp."
        )

    if verified > 0 and partial == 0 and hallucinated == 0 and unverified == 0 and doi_not_found == 0:
        noun = "DOI" if doi_verified > 0 and valid == 0 else "trích dẫn"
        return (
            f"Mình đã kiểm tra {noun} này và tìm thấy bản ghi học thuật khớp rõ ràng. "
            "Bạn vẫn nên giữ DOI hoặc đường dẫn nhà xuất bản trong danh mục tài liệu để người đọc dễ đối chiếu."
        )

    if partial > 0 and verified == 0 and hallucinated == 0:
        return (
            "Mình đã kiểm tra trích dẫn này. Kết quả hiện chỉ khớp một phần với dữ liệu học thuật đang có, "
            "nên chưa thể xác nhận hoàn toàn. Bạn nên đối chiếu thêm DOI, trang nhà xuất bản, tên tác giả hoặc năm xuất bản trước khi sử dụng."
        )

    if partial > 0:
        return (
            f"Mình đã kiểm tra {total} mục trích dẫn. Có {verified} mục khớp rõ ràng, "
            f"nhưng {partial} mục chỉ khớp một phần nên cần rà soát thủ công thêm. "
            "Hãy ưu tiên kiểm tra lại DOI, tiêu đề và thông tin tác giả của các mục chưa chắc chắn."
        )

    if hallucinated > 0:
        return (
            f"Mình đã kiểm tra {total} mục trích dẫn và có {hallucinated} mục chưa tìm thấy bằng chứng học thuật phù hợp. "
            "Bạn nên kiểm tra lại thông tin nguồn trước khi đưa các mục này vào bài viết."
        )

    if unverified > 0:
        return (
            f"Mình đã kiểm tra {total} mục trích dẫn, nhưng {unverified} mục hiện chưa xác minh được từ nguồn học thuật. "
            "Nguyên nhân có thể là nguồn tra cứu tạm thời không phản hồi hoặc thông tin trích dẫn còn thiếu."
        )

    return (
        f"Mình đã kiểm tra {total} mục trích dẫn và chưa thấy dấu hiệu bất thường rõ ràng. "
        "Bạn có thể xem phần chi tiết để đối chiếu từng mục nếu cần."
    )


def format_retraction_summary(summary: dict[str, Any]) -> str:
    total_checked = _count(summary, "total_checked") or _count(summary, "total")
    no_doi = bool(summary.get("no_doi_found", False))
    unresolved = _count(summary, "unresolved")
    scan_skipped = bool(summary.get("scan_skipped", False))

    if scan_skipped or (unresolved > 0 and total_checked == 0):
        return (
            "Mình đã thử xác minh DOI bạn cung cấp, nhưng hiện chưa tìm thấy bản ghi học thuật khớp hoàn toàn. "
            "Vì chưa xác minh được tài liệu gốc, bước kiểm tra retraction cũng được bỏ qua. "
            "Bạn có thể gửi thêm tiêu đề bài báo, tên tác giả hoặc nguồn trích dẫn để mình kiểm tra tiếp."
        )

    if no_doi or total_checked == 0:
        return (
            "Mình chưa thấy DOI đủ rõ để kiểm tra retraction. "
            "Hãy gửi DOI đầy đủ hoặc reference có DOI để mình rà soát trạng thái rút bài và cảnh báo học thuật."
        )

    retracted = _count(summary, "retracted")
    concerns = _count(summary, "concerns")
    corrected = _count(summary, "corrected")
    high_risk = _count(summary, "high_risk")
    critical_risk = _count(summary, "critical_risk")
    pubpeer = _count(summary, "pubpeer_discussions")
    pubpeer_lookup_failed = _count(summary, "pubpeer_lookup_failed")

    if retracted > 0 or concerns > 0 or high_risk > 0 or critical_risk > 0:
        parts: list[str] = []
        if retracted:
            parts.append(f"{retracted} mục có tín hiệu đã bị rút bài")
        if concerns:
            parts.append(f"{concerns} mục có cảnh báo hoặc expression of concern")
        if high_risk or critical_risk:
            parts.append("có mức rủi ro cần chú ý")
        if pubpeer:
            parts.append(f"{pubpeer} mục có thảo luận PubPeer")
        detail = ", ".join(parts)
        return (
            f"Mình đã kiểm tra thông tin retraction cho {total_checked} DOI và thấy {detail}. "
            "Bạn nên mở phần chi tiết, kiểm tra nguồn gốc cảnh báo, rồi đối chiếu lại với trang nhà xuất bản trước khi trích dẫn."
        )

    if corrected > 0 or pubpeer > 0:
        extras: list[str] = []
        if corrected:
            extras.append(f"{corrected} mục có correction/erratum")
        if pubpeer:
            extras.append(f"{pubpeer} mục có thảo luận PubPeer")
        if corrected and pubpeer:
            detail = " và ".join(extras)
        else:
            detail = extras[0]
        return (
            f"Mình đã kiểm tra {total_checked} DOI. Chưa thấy tín hiệu bài bị rút, "
            f"nhưng {detail}. Bạn nên xem thêm chi tiết để đánh giá mức độ ảnh hưởng đến nội dung trích dẫn."
        )

    if pubpeer_lookup_failed > 0:
        return (
            f"Mình đã kiểm tra {total_checked} DOI và chưa thấy tín hiệu retraction từ Crossref/OpenAlex. "
            f"Tuy nhiên có {pubpeer_lookup_failed} mục chưa kiểm tra được PubPeer (lỗi kết nối), "
            "nên kết quả này chưa phải là đánh giá đầy đủ."
        )

    return (
        f"Mình đã kiểm tra thêm các nguồn retraction và cảnh báo học thuật liên quan cho {total_checked} DOI. "
        "Hiện chưa thấy tín hiệu đáng lo ngại trong các nguồn đã rà soát."
    )


def format_academic_tool_error(tool_name: str, error: str) -> str:
    low_error = (error or "").lower()
    if (
        "document_id" in low_error
        or "unknown function" in low_error
        or "unexpected arguments" in low_error
        or "missing required argument" in low_error
    ):
        return (
            "Mình chưa xử lý được yêu cầu này vì tham chiếu tài liệu không hợp lệ hoặc không còn trong phiên hiện tại. "
            "Bạn có thể gửi lại tài liệu, hoặc nhập trực tiếp DOI/citation cần kiểm tra."
        )

    if tool_name in {"scan_retraction_and_pubpeer", "verify_citation"}:
        return (
            "Mình chưa truy vấn được nguồn dữ liệu học thuật ở thời điểm này. "
            "Bạn có thể thử lại sau hoặc gửi thêm thông tin như DOI, tiêu đề và tên tác giả để kiểm tra lại."
        )

    return "Mình chưa xử lý được yêu cầu này. Bạn vui lòng thử lại hoặc gửi thêm ngữ cảnh cụ thể hơn."
