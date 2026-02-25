import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES

from app.core.config import settings


@dataclass(slots=True)
class KeyInfo:
    source: str
    path: str | None


class CryptoManager:
    """Single place for AES-256-GCM operations used in transit and at-rest encryption."""

    def __init__(self, master_key: bytes, key_info: KeyInfo):
        if len(master_key) != 32:
            raise ValueError("Master key must be 32 bytes for AES-256-GCM")
        self._master_key = master_key
        self.key_info = key_info

    @staticmethod
    def generate_master_key_b64() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")

    def encrypt_bytes(self, plaintext: bytes, aad: bytes | None = None) -> str:
        nonce = os.urandom(12)
        cipher = AES.new(self._master_key, AES.MODE_GCM, nonce=nonce)
        if aad:
            cipher.update(aad)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        payload = nonce + tag + ciphertext
        return base64.urlsafe_b64encode(payload).decode("utf-8")

    def decrypt_bytes(self, token: str, aad: bytes | None = None) -> bytes:
        payload = base64.urlsafe_b64decode(token.encode("utf-8"))
        if len(payload) < 28:
            raise ValueError("Invalid encrypted payload length")
        nonce, tag, ciphertext = payload[:12], payload[12:28], payload[28:]
        cipher = AES.new(self._master_key, AES.MODE_GCM, nonce=nonce)
        if aad:
            cipher.update(aad)
        return cipher.decrypt_and_verify(ciphertext, tag)

    def encrypt_text(self, plaintext: str) -> str:
        return self.encrypt_bytes(plaintext.encode("utf-8"))

    def decrypt_text(self, token: str) -> str:
        return self.decrypt_bytes(token).decode("utf-8")

    def encrypt_json(self, data: dict[str, Any], aad: bytes | None = None) -> str:
        return self.encrypt_bytes(json.dumps(data, ensure_ascii=True).encode("utf-8"), aad=aad)

    def decrypt_json(self, token: str, aad: bytes | None = None) -> dict[str, Any]:
        raw = self.decrypt_bytes(token, aad=aad)
        return json.loads(raw.decode("utf-8"))



def _load_or_create_master_key() -> tuple[bytes, KeyInfo]:
    env_key = settings.admin_master_key_b64
    if env_key:
        return base64.urlsafe_b64decode(env_key.encode("utf-8")), KeyInfo(source="env", path=None)

    key_path: Path = settings.master_key_path
    if key_path.exists():
        value = key_path.read_text(encoding="utf-8").strip()
        return base64.urlsafe_b64decode(value.encode("utf-8")), KeyInfo(source="file", path=str(key_path))

    key_path.parent.mkdir(parents=True, exist_ok=True)
    generated = CryptoManager.generate_master_key_b64()
    key_path.write_text(generated, encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except PermissionError:
        pass
    return base64.urlsafe_b64decode(generated.encode("utf-8")), KeyInfo(source="generated_file", path=str(key_path))


_master_key, _key_info = _load_or_create_master_key()
crypto_manager = CryptoManager(master_key=_master_key, key_info=_key_info)
