#!/usr/bin/env python3
"""
Pre-download the RoBERTa GPT-2 detector model so the AI writing detection
pipeline does not need to download it during an API request.

Usage:
    python scripts/download_detector_model.py

This will download ~500 MB of model weights into the project-local
HuggingFace cache (``backend/.cache/huggingface/``), respecting the
``HF_CACHE_DIR`` and ``HF_TOKEN`` settings from ``backend/.env``.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

# Ensure we can import from the backend package
_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
logger = logging.getLogger("download_detector_model")


def _ensure_cache_dir(cache_dir: str) -> Path:
    """Set HuggingFace cache environment variables and return the cache root."""
    cache_root = (_backend_root / cache_dir).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_root))
    # TRANSFORMERS_CACHE intentionally NOT set — huggingface_hub places
    # files under HF_HOME/hub/ which is where local_files_only=True looks.
    return cache_root


def _clean_partial_download(model_name: str) -> None:
    """Remove any partial / corrupted cache entries for *model_name*."""
    hf_home = os.environ.get("HF_HOME", "")
    if hf_home:
        slug = f"models--{model_name.replace('/', '--')}"
        for pattern in (f"hub/{slug}*", f"{slug}*"):
            for path in Path(hf_home).glob(pattern):
                if path.exists():
                    logger.warning("Removing partial cache: %s", path)
                    shutil.rmtree(path)


def download_model(
    model_name: str = "roberta-base-openai-detector",
    cache_dir: str = ".cache/huggingface",
    force: bool = False,
) -> bool:
    """Download the RoBERTa detector model to the project cache.

    Returns True on success, False on failure.
    """
    from app.core.config import settings

    cache_root = _ensure_cache_dir(cache_dir)
    logger.info("Cache root: %s", cache_root)
    logger.info("Model:      %s", model_name)
    logger.info("Force:      %s", force)

    # Check if already fully cached
    if not force:
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_name, local_files_only=True
            )
            logger.info("Model already fully cached — nothing to do.")
            return True
        except Exception:
            logger.info("Model not fully cached; beginning download...")

    # Clean partial artifacts before starting fresh
    _clean_partial_download(model_name)

    # Attempt download
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info("Downloading tokenizer (this should be quick)...")
        tok = AutoTokenizer.from_pretrained(model_name, local_files_only=False)
        logger.info("Tokenizer downloaded.")

        logger.info(
            "Downloading model weights (~500 MB, may take several minutes)..."
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name, local_files_only=False
        )
        logger.info("Model weights downloaded.")

        # Verify by loading with local_files_only
        _ = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        _ = AutoModelForSequenceClassification.from_pretrained(
            model_name, local_files_only=True
        )
        logger.info("Verification OK — model is ready for offline use.")
        return True
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        # Clean up partial artifacts so subsequent local-only attempts fail
        # cleanly instead of crashing on missing weights.
        _clean_partial_download(model_name)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-download the RoBERTa GPT-2 detector model."
    )
    parser.add_argument(
        "--model-name",
        default="roberta-base-openai-detector",
        help="HuggingFace model identifier (default: roberta-base-openai-detector)",
    )
    parser.add_argument(
        "--cache-dir",
        default=".cache/huggingface",
        help="Relative path from backend/ to cache directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    args = parser.parse_args()

    success = download_model(
        model_name=args.model_name,
        cache_dir=args.cache_dir,
        force=args.force,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
