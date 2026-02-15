import logging
import re
from typing import TypeVar

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import (
    ANTHROPIC_API_KEY,
    LLM_DEFAULT_TIER,
    LLM_MODEL_FAST,
    LLM_MODEL_HIGH,
    LLM_MODEL_STANDARD,
    LLM_PROVIDER,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


_ANTHROPIC_DEFAULTS = {
    "fast": "claude-3-haiku-20240307",
    "standard": "claude-3-5-sonnet-20240620",
    "high": "claude-3-5-sonnet-20240620",
}

_OPENAI_DEFAULTS = {
    "fast": "gpt-4o-mini",
    "standard": "gpt-4o",
    "high": "gpt-4o",
}


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


class LLMClient:
    def __init__(self) -> None:
        provider = (LLM_PROVIDER or "auto").lower()
        if provider == "auto":
            if ANTHROPIC_API_KEY:
                provider = "anthropic"
            elif OPENAI_API_KEY:
                provider = "openai"
            else:
                provider = "dummy"
        self.provider = provider

        self._anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
        self._openai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    def available(self) -> bool:
        if self.provider == "anthropic":
            return self._anthropic is not None
        if self.provider == "openai":
            return self._openai is not None
        return False

    def model_for_tier(self, tier: str | None) -> str:
        tier = (tier or LLM_DEFAULT_TIER or "fast").lower()
        if tier not in ("fast", "standard", "high"):
            tier = "standard"

        if tier == "fast" and LLM_MODEL_FAST:
            return LLM_MODEL_FAST
        if tier == "standard" and LLM_MODEL_STANDARD:
            return LLM_MODEL_STANDARD
        if tier == "high" and LLM_MODEL_HIGH:
            return LLM_MODEL_HIGH

        if self.provider == "anthropic":
            return _ANTHROPIC_DEFAULTS[tier]
        return _OPENAI_DEFAULTS[tier]

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        max_tokens: int = 2048,
        tier: str | None = None,
    ) -> T:
        if not self.available():
            raise RuntimeError("LLM provider unavailable")

        model = self.model_for_tier(tier)

        if self.provider == "anthropic":
            message = await self._anthropic.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = ""
            for block in message.content:
                if hasattr(block, "text"):
                    raw += block.text
            raw = _strip_json(raw)
            return response_model.model_validate_json(raw)

        response = await self._openai.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_model,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("LLM parse returned no data")
        return parsed


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
