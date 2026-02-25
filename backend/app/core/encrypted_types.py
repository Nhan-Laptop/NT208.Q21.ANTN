import json
from typing import Any

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.crypto import crypto_manager


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return crypto_manager.encrypt_text(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return crypto_manager.decrypt_text(value)


class EncryptedJSON(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: dict[str, Any] | list[Any] | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return crypto_manager.encrypt_text(json.dumps(value, ensure_ascii=True))

    def process_result_value(self, value: str | None, dialect: Any) -> dict[str, Any] | list[Any] | None:
        if value is None:
            return None
        return json.loads(crypto_manager.decrypt_text(value))
