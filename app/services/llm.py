import json
import logging
import re
from typing import TypeVar

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

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


def _coerce_clinical_insights(data: dict) -> dict:
    def _as_str(item: object) -> str:
        return str(item).strip()

    def _parse_confidence(text: str) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%?", text)
        if not match:
            return 0.0
        value = float(match.group(1))
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _coerce_list(value: object, builder) -> list:
        if not isinstance(value, list):
            return []
        output = []
        for item in value:
            if isinstance(item, dict):
                output.append(item)
            else:
                output.append(builder(item))
        return output

    prep_alerts = _coerce_list(
        data.get("prep_alerts"),
        lambda item: {"label": _as_str(item), "severity": "moderate", "action": _as_str(item), "evidence": []},
    )
    contraindications = _coerce_list(
        data.get("contraindications"),
        lambda item: {"label": _as_str(item), "reason": _as_str(item), "evidence": []},
    )
    likely_diagnoses = _coerce_list(
        data.get("likely_diagnoses"),
        lambda item: {
            "label": _as_str(item),
            "confidence": _parse_confidence(_as_str(item)),
            "evidence": [],
        },
    )
    evidence = _coerce_list(
        data.get("evidence"),
        lambda item: {"source_type": "summary", "source_label": "LLM", "summary": _as_str(item)},
    )
    attachments = _coerce_list(
        data.get("attachments"),
        lambda item: {"name": _as_str(item), "file_type": "", "url": "", "source": "LLM", "timestamp": ""},
    )
    history_warnings = data.get("history_warnings") if isinstance(data.get("history_warnings"), list) else []
    updated_at = data.get("updated_at") if isinstance(data.get("updated_at"), str) else ""

    return {
        "prep_alerts": prep_alerts,
        "contraindications": contraindications,
        "likely_diagnoses": likely_diagnoses,
        "evidence": evidence,
        "attachments": attachments,
        "history_warnings": history_warnings,
        "updated_at": updated_at,
    }


def _coerce_payload(data: object, response_model: type[T]) -> object:
    name = response_model.__name__
    if name == "HistoryWarnings":
        if isinstance(data, list):
            return {"warnings": [str(item) for item in data]}
        if isinstance(data, dict) and isinstance(data.get("warnings"), list):
            return {"warnings": [str(item) for item in data.get("warnings") or []]}
        return {"warnings": []}
    if name == "ClinicalInsights":
        if isinstance(data, dict):
            return _coerce_clinical_insights(data)
        return _coerce_clinical_insights({})
    return data


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
            try:
                return response_model.model_validate_json(raw)
            except ValidationError:
                try:
                    payload = json.loads(raw)
                except Exception:
                    raise
                coerced = _coerce_payload(payload, response_model)
                return response_model.model_validate(coerced)

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
