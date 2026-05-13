from __future__ import annotations

from typing import Any

from app.services.ingestion.index_service import academic_index_service


class ManuscriptRetriever:
    def retrieve(self, query_text: str, top_k_each: int = 5) -> list[dict[str, Any]]:
        return academic_index_service.query_all(query_text=query_text, top_k_each=top_k_each)


manuscript_retriever = ManuscriptRetriever()
