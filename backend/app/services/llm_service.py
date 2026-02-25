import logging
from typing import Sequence

from app.core.config import settings
from app.models.chat_message import ChatMessage

logger = logging.getLogger(__name__)

try:
    from google import genai as genai_new
except Exception:  # pragma: no cover - optional dependency runtime issues
    genai_new = None

try:
    import google.generativeai as genai_old
except Exception:  # pragma: no cover - optional dependency runtime issues
    genai_old = None


class GeminiService:
    def __init__(self) -> None:
        self._enabled = bool(settings.google_api_key and (genai_new is not None or genai_old is not None))
        self._provider = "none"
        self._client = None
        self._model = None
        if not self._enabled:
            return

        if genai_new is not None:
            try:
                self._client = genai_new.Client(api_key=settings.google_api_key)
                self._provider = "google.genai"
                return
            except Exception:
                self._client = None

        if genai_old is not None:
            genai_old.configure(api_key=settings.google_api_key)
            self._model = genai_old.GenerativeModel(
                model_name=settings.gemini_model,
                system_instruction=settings.system_prompt,
            )
            self._provider = "google.generativeai"

    @property
    def enabled(self) -> bool:
        if not self._enabled:
            return False
        return self._provider in {"google.genai", "google.generativeai"}

    def _build_prompt(self, history: Sequence[ChatMessage], user_text: str) -> str:
        lines: list[str] = ["Conversation context:"]
        for msg in history:
            role = msg.role.value.upper()
            content = (msg.content or "").strip()
            if content:
                lines.append(f"[{role}] {content}")
        lines.append(f"[USER] {user_text}")
        lines.append("[ASSISTANT]")
        return "\n".join(lines)

    def generate_response(self, history: Sequence[ChatMessage], user_text: str) -> str:
        if not self.enabled:
            return (
                "Gemini is not configured. Please set GOOGLE_API_KEY to enable model responses. "
                "Current message has been stored successfully."
            )

        prompt = self._build_prompt(history, user_text)
        if self._provider == "google.genai" and self._client is not None:
            try:
                result = self._client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config={"system_instruction": settings.system_prompt},
                )
                text = getattr(result, "text", "") or ""
                if text.strip():
                    return text.strip()
            except Exception:
                # Runtime fallback to legacy SDK
                logger.warning("Gemini call via google.genai failed; falling back to legacy SDK.", exc_info=True)
                pass

        if self._model is not None:
            try:
                result = self._model.generate_content(prompt)
                text = getattr(result, "text", "") or ""
                return text.strip() or "I could not generate a response for this message."
            except Exception:
                logger.warning("Gemini call via google.generativeai failed.", exc_info=True)
                return (
                    "Gemini is configured but the request failed (model/key may be invalid). "
                    "Current message has been stored successfully."
                )

        return "I could not generate a response for this message."

    def summarize_text(self, text: str, max_words: int = 180) -> str:
        prompt = (
            "Summarize the following academic document in Vietnamese with an academic style. "
            f"Limit to around {max_words} words and include core contributions, methods, and limitations.\n\n"
            f"{text}"
        )
        if not self.enabled:
            clipped = " ".join(text.split()[:max_words])
            return f"Tóm tắt (fallback khi Gemini chưa cấu hình): {clipped}"
        if self._provider == "google.genai" and self._client is not None:
            try:
                result = self._client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config={"system_instruction": settings.system_prompt},
                )
                out = getattr(result, "text", "") or ""
                if out.strip():
                    return out.strip()
            except Exception:
                logger.warning("Gemini summarize via google.genai failed; falling back to legacy SDK.", exc_info=True)
                pass

        if self._model is not None:
            try:
                result = self._model.generate_content(prompt)
                out = getattr(result, "text", "") or ""
                return out.strip() or "Không thể sinh tóm tắt cho tài liệu này."
            except Exception:
                logger.warning("Gemini summarize via google.generativeai failed.", exc_info=True)
                clipped = " ".join(text.split()[:max_words])
                return f"Tóm tắt (fallback do Gemini lỗi): {clipped}"

        return "Không thể sinh tóm tắt cho tài liệu này."


gemini_service = GeminiService()
