from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.entity_fingerprint import EntityFingerprint


class DedupService:
    TRACKING_QUERY_PREFIXES = ("utm_",)
    TRACKING_QUERY_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}

    def normalize_url(self, url: str | None) -> str:
        if not url:
            return ""
        parsed = urlparse(url.strip())
        query_parts = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=False):
            lowered = key.lower()
            if lowered in self.TRACKING_QUERY_PARAMS:
                continue
            if any(lowered.startswith(prefix) for prefix in self.TRACKING_QUERY_PREFIXES):
                continue
            query_parts.append((key, value))
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            query=urlencode(query_parts, doseq=True),
            fragment="",
        )
        return urlunparse(normalized).rstrip("/")

    def hash_value(self, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    def normalized_url_hash(self, url: str | None) -> str | None:
        return self.hash_value(self.normalize_url(url))

    def business_key_for_article(self, title: str, venue: str | None, publication_year: int | None, doi: str | None) -> str | None:
        if doi:
            return doi.lower()
        basis = "|".join(part for part in [title.lower(), (venue or "").lower(), str(publication_year or "")] if part)
        return self.hash_value(basis)

    def business_key_for_venue(self, title: str, publisher: str | None, issn: str | None) -> str | None:
        basis = "|".join(part for part in [title.lower(), (publisher or "").lower(), (issn or "").lower()] if part)
        return self.hash_value(basis)

    def business_key_for_cfp(self, title: str, venue_title: str | None, deadline: str | None) -> str | None:
        basis = "|".join(part for part in [title.lower(), (venue_title or "").lower(), (deadline or "").lower()] if part)
        return self.hash_value(basis)

    def content_fingerprint(self, *parts: str | None) -> str | None:
        basis = " | ".join((part or "").strip().lower() for part in parts if (part or "").strip())
        return self.hash_value(basis)

    def find_existing(
        self,
        db: Session,
        *,
        entity_type: str,
        source_name: str | None,
        raw_identifier: str | None,
        normalized_url_hash: str | None,
        business_key: str | None,
        content_fingerprint: str | None,
    ) -> EntityFingerprint | None:
        query = db.query(EntityFingerprint).filter(EntityFingerprint.entity_type == entity_type)
        if business_key:
            row = query.filter(EntityFingerprint.business_key == business_key).first()
            if row:
                return row
        if raw_identifier:
            row = query.filter(EntityFingerprint.raw_identifier == raw_identifier, EntityFingerprint.source_name == source_name).first()
            if row:
                return row
        if normalized_url_hash:
            row = query.filter(EntityFingerprint.normalized_url_hash == normalized_url_hash).first()
            if row:
                return row
        if content_fingerprint:
            return query.filter(EntityFingerprint.content_fingerprint == content_fingerprint).first()
        return None

    def upsert_fingerprint(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        source_name: str | None,
        raw_identifier: str | None,
        normalized_url_hash: str | None,
        business_key: str | None,
        content_fingerprint: str | None,
    ) -> EntityFingerprint:
        query = db.query(EntityFingerprint).filter(EntityFingerprint.entity_type == entity_type)
        fingerprint = query.filter(
            EntityFingerprint.entity_id == entity_id,
            EntityFingerprint.source_name == source_name,
        ).first()
        if fingerprint is None:
            source_query = query.filter(EntityFingerprint.source_name == source_name)
            match_conditions = []
            if raw_identifier:
                match_conditions.append(EntityFingerprint.raw_identifier == raw_identifier)
            if normalized_url_hash:
                match_conditions.append(EntityFingerprint.normalized_url_hash == normalized_url_hash)
            if business_key:
                match_conditions.append(EntityFingerprint.business_key == business_key)
            if content_fingerprint:
                match_conditions.append(EntityFingerprint.content_fingerprint == content_fingerprint)
            if match_conditions:
                fingerprint = source_query.filter(or_(*match_conditions)).first()
        if fingerprint is None:
            fingerprint = EntityFingerprint(entity_type=entity_type, entity_id=entity_id, source_name=source_name)
        fingerprint.entity_id = entity_id
        fingerprint.source_name = source_name
        fingerprint.raw_identifier = raw_identifier
        fingerprint.normalized_url_hash = normalized_url_hash
        fingerprint.business_key = business_key
        fingerprint.content_fingerprint = content_fingerprint
        db.add(fingerprint)
        return fingerprint


dedup_service = DedupService()
