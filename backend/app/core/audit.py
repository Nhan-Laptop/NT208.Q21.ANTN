import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import settings


def _build_audit_logger() -> logging.Logger:
    logger = logging.getLogger("aira.audit")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    path = Path(settings.audit_log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


audit_logger = _build_audit_logger()



def log_audit_event(
    event: str,
    actor_id: str | None,
    actor_role: str | None,
    outcome: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "outcome": outcome,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details or {},
    }
    audit_logger.info(json.dumps(payload, ensure_ascii=True))
