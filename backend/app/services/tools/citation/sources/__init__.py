from .base import CitationSource
from .crossref import CrossrefSource, normalize_crossref_work
from .datacite import DataCiteSource, normalize_datacite_work
from .openalex import OpenAlexSource, normalize_openalex_work
from .publisher_meta import PublisherMetaSource
from .semantic_scholar import SemanticScholarSource, normalize_semantic_scholar_paper
from .web_search import WebSearchSource

__all__ = [
    "CitationSource",
    "CrossrefSource",
    "DataCiteSource",
    "OpenAlexSource",
    "PublisherMetaSource",
    "SemanticScholarSource",
    "WebSearchSource",
    "normalize_crossref_work",
    "normalize_datacite_work",
    "normalize_openalex_work",
    "normalize_semantic_scholar_paper",
]
