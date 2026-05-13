from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_backend_root = Path(__file__).resolve().parents[3]

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency guard
    SentenceTransformer = None  # type: ignore[assignment]

try:
    from adapters import AutoAdapterModel
except ImportError:  # pragma: no cover - optional dependency guard
    AutoAdapterModel = None  # type: ignore[assignment]

try:
    import torch
    from transformers import AutoModel, AutoTokenizer
except ImportError:  # pragma: no cover - optional dependency guard
    torch = None  # type: ignore[assignment]
    AutoModel = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]


class Specter2Service:
    """Centralized SPECTER2 embedding service with development-safe fallback."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._backend: str | None = None
        self._loaded_model_name: str | None = None
        self._adapter_label: str | None = None
        self._load_attempted = False

    def _ensure_cache_dir(self) -> None:
        cache_root = (_backend_root / settings.hf_cache_dir).resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(cache_root))
        os.environ.setdefault("HF_HUB_CACHE", str(cache_root / "hub"))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(cache_root / "transformers"))

    def _preprocess_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return "empty document"
        return normalized[: settings.specter2_max_chars]

    def _load_sentence_transformer_local(self, model_name: str) -> bool:
        if SentenceTransformer is None:
            return False
        try:
            self._model = SentenceTransformer(model_name, trust_remote_code=False, local_files_only=True)
            self._backend = "sentence-transformers"
            self._loaded_model_name = model_name
            logger.info("Loaded %s via SentenceTransformer (local)", model_name)
            return True
        except Exception as exc:  # pragma: no cover - external model load
            logger.warning("Failed loading %s via SentenceTransformer (local): %s", model_name, exc)
            return False

    def _load_sentence_transformer(self, model_name: str) -> bool:
        if SentenceTransformer is None:
            return False
        try:
            self._model = SentenceTransformer(
                model_name, trust_remote_code=False,
                token=settings.hf_token or True,
            )
            self._backend = "sentence-transformers"
            self._loaded_model_name = model_name
            logger.info("Loaded %s via SentenceTransformer (downloaded)", model_name)
            return True
        except Exception as exc:
            logger.warning("Failed loading %s via SentenceTransformer download: %s", model_name, exc)
        return self._load_sentence_transformer_local(model_name)

    def _load_transformers_model_local(self, model_name: str) -> bool:
        if AutoTokenizer is None or AutoModel is None or torch is None:
            return False
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
            self._model = AutoModel.from_pretrained(model_name, local_files_only=True)
            self._model.eval()
            self._backend = "transformers"
            self._loaded_model_name = model_name
            logger.info("Loaded %s via transformers (local)", model_name)
            return True
        except Exception as exc:
            logger.warning("Failed loading %s via transformers (local): %s", model_name, exc)
            return False

    def _load_transformers_model(self, model_name: str) -> bool:
        if AutoTokenizer is None or AutoModel is None or torch is None:
            return False
        if self._load_transformers_model_local(model_name):
            return True
        token = settings.hf_token or None
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_name, token=token)
            self._model = AutoModel.from_pretrained(model_name, token=token)
            self._model.eval()
            self._backend = "transformers"
            self._loaded_model_name = model_name
            logger.info("Loaded %s via transformers (downloaded)", model_name)
            return True
        except Exception as exc:
            logger.warning("Failed loading %s via transformers download: %s", model_name, exc)
            return False

    def _load_adapter_model(self, adapter_name: str, base_model_name: str) -> bool:
        if AutoAdapterModel is None or AutoTokenizer is None or torch is None:
            return False
        adapter_path = Path(adapter_name)
        is_hub_model = "/" in adapter_name and not adapter_path.is_dir()
        if not is_hub_model and (not adapter_path.is_dir() or not (adapter_path / "adapter_config.json").exists()):
            return False
        # Try local first
        for kw in [{"local_files_only": True}, {"token": settings.hf_token or None} if settings.hf_token else {}]:
            try:
                self._tokenizer = AutoTokenizer.from_pretrained(base_model_name, **kw)
                self._model = AutoAdapterModel.from_pretrained(base_model_name, **kw)
                adapter_label = self._model.load_adapter(adapter_name, load_as="specter2", **kw)
                self._adapter_label = str(adapter_label)
                self._ensure_adapter_active()
                self._model.eval()
                self._backend = "adapters"
                self._loaded_model_name = adapter_name
                mode = "local" if kw.get("local_files_only") else "downloaded"
                logger.info("Loaded adapter %s with base %s (%s)", adapter_name, base_model_name, mode)
                return True
            except Exception as exc:
                mode = "local" if kw.get("local_files_only") else "download"
                logger.warning("Failed loading %s adapter %s: %s", adapter_name, mode, exc)
                self._model = None
                self._tokenizer = None
                self._adapter_label = None
                if is_hub_model and not kw.get("local_files_only"):
                    return False
        return False

    def _ensure_adapter_active(self) -> None:
        if self._adapter_label is None:
            raise RuntimeError("SPECTER2 adapter backend selected without an adapter label.")
        self._model.set_active_adapters(self._adapter_label)
        active_adapters = str(getattr(self._model, "active_adapters", ""))
        if self._adapter_label not in active_adapters:
            raise RuntimeError(
                f"SPECTER2 adapter {self._adapter_label!r} is not active; active_adapters={active_adapters!r}"
            )

    def _ensure_model(self) -> None:
        if self._backend == "hash-fallback":
            return
        if self._model is not None:
            return
        if self._load_attempted and self._backend is None:
            raise RuntimeError("Embedding backend initialization previously failed.")
        self._load_attempted = True
        self._ensure_cache_dir()
        if self._load_adapter_model(settings.specter2_model_name, settings.specter2_fallback_model_name):
            logger.info("Embedding adapter ready: %s (%s)", settings.specter2_model_name, self._backend)
            return
        for model_name in (settings.specter2_model_name, settings.specter2_fallback_model_name):
            if self._load_sentence_transformer_local(model_name):
                logger.info("Embedding model ready: %s (%s)", model_name, self._backend)
                return
        for model_name in (settings.specter2_model_name, settings.specter2_fallback_model_name):
            if self._load_sentence_transformer(model_name):
                logger.info("Embedding model ready: %s (%s)", model_name, self._backend)
                return
            if self._load_transformers_model(model_name):
                logger.info("Embedding model ready: %s (%s)", model_name, self._backend)
                return
        if not settings.academic_embedding_hash_fallback:
            raise RuntimeError(
                "SPECTER2 could not be loaded. Install model dependencies and authenticate Hugging Face access if required."
            )
        self._backend = "hash-fallback"
        self._loaded_model_name = "hash-fallback"
        self._model = "hash-fallback"
        logger.warning("Falling back to deterministic hash embeddings because SPECTER2 is unavailable.")

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    def _hash_embed(self, text: str, dimension: int = 384) -> list[float]:
        vector = [0.0] * dimension
        for token in re.findall(r"[a-z0-9]{2,}", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % dimension
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            weight = 1.0 + (digest[3] / 255.0)
            vector[index] += sign * weight
        return self._normalize_vector(vector)

    def _embed_transformers(self, texts: list[str]) -> list[list[float]]:
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.no_grad():
            outputs = self._model(**encoded)
        hidden = outputs.last_hidden_state
        attention_mask = encoded["attention_mask"].unsqueeze(-1)
        summed = (hidden * attention_mask).sum(dim=1)
        counts = attention_mask.sum(dim=1).clamp(min=1)
        pooled = summed / counts
        return [self._normalize_vector(row.tolist()) for row in pooled]

    def _embed_adapters(self, texts: list[str]) -> list[list[float]]:
        self._ensure_adapter_active()
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.no_grad():
            outputs = self._model(**encoded)
        pooled = outputs.last_hidden_state[:, 0, :]
        return [self._normalize_vector(row.tolist()) for row in pooled]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        prepared = [self._preprocess_text(text) for text in texts]
        self._ensure_model()
        if self._backend == "hash-fallback":
            return [self._hash_embed(text) for text in prepared]
        if self._backend == "sentence-transformers":
            vectors = self._model.encode(prepared, show_progress_bar=False).tolist()
            return [self._normalize_vector(vector) for vector in vectors]
        if self._backend == "transformers":
            return self._embed_transformers(prepared)
        if self._backend == "adapters":
            return self._embed_adapters(prepared)
        raise RuntimeError("Embedding backend is not initialized.")

    @property
    def embedding_model_name(self) -> str:
        self._ensure_model()
        return self._loaded_model_name or settings.specter2_model_name

    @property
    def is_degraded(self) -> bool:
        self._ensure_model()
        return self._backend == "hash-fallback"

    def status(self) -> dict[str, Any]:
        self._ensure_model()
        return {
            "backend": self._backend,
            "model_name": self._loaded_model_name,
            "degraded": self._backend == "hash-fallback",
        }


specter2_service = Specter2Service()
