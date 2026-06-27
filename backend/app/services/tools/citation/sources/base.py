from __future__ import annotations

from typing import Protocol

from ..models import CandidateWork, ReferenceMetadata


class CitationSource(Protocol):
    name: str

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        ...

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        ...
