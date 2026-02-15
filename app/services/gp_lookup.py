"""GP contact resolution using Perplexity Sonar API.

Given a GP/doctor name and location, resolves the practice phone number
by querying Perplexity's search-augmented LLM endpoint.
"""

import json
import logging
import re

import httpx

from app.config import PERPLEXITY_API_KEY

logger = logging.getLogger(__name__)

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"
PERPLEXITY_TIMEOUT = 30.0

_SYSTEM_PROMPT = (
    "You are a medical practice phone number lookup assistant. "
    "Given a doctor or practice name and location, find the practice phone number. "
    "Return ONLY a valid JSON object with these keys: "
    '"phone" (string, E.164 or standard US format), '
    '"practice_name" (string), '
    '"address" (string). '
    "If you cannot find the number with confidence, return the JSON string: null"
)


def _validate_phone(phone: str) -> str | None:
    """Validate and normalize a phone number string.

    Returns the cleaned phone string if it contains enough digits, else None.
    """
    if not phone:
        return None
    digits = re.sub(r"[^\d]", "", phone)
    if len(digits) < 7:
        return None
    return phone.strip()


async def lookup_gp_phone(
    gp_name: str,
    location: str,
    practice_name: str | None = None,
) -> dict | None:
    """Search for a GP practice phone number using Perplexity Sonar API.

    Args:
        gp_name: Doctor or GP name
        location: City, address, or area to search near
        practice_name: Optional practice/clinic name if different from doctor

    Returns:
        Dict with keys: phone, practice_name, address, source — or None if not found.
    """
    if not PERPLEXITY_API_KEY:
        logger.warning("PERPLEXITY_API_KEY not set, cannot look up GP phone")
        return None

    # Build the search query
    parts = [gp_name]
    if practice_name:
        parts.append(practice_name)
    query = f"Find the phone number for {' at '.join(parts)} near {location}"

    try:
        async with httpx.AsyncClient(timeout=PERPLEXITY_TIMEOUT) as client:
            resp = await client.post(
                PERPLEXITY_URL,
                headers={
                    "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": PERPLEXITY_MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                },
            )
            resp.raise_for_status()

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        logger.info("Perplexity response for GP lookup: %s", content[:200])

        # Extract JSON from response (may be wrapped in markdown code block)
        json_str = content.strip()
        if json_str.startswith("```"):
            # Strip markdown code fences
            lines = json_str.split("\n")
            json_str = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

        parsed = json.loads(json_str)
        if parsed is None:
            logger.info("Perplexity returned null — GP not found")
            return None

        phone = _validate_phone(parsed.get("phone", ""))
        if not phone:
            logger.warning("Perplexity returned invalid phone: %s", parsed.get("phone"))
            return None

        return {
            "phone": phone,
            "practice_name": parsed.get("practice_name", gp_name),
            "address": parsed.get("address", ""),
            "source": "perplexity",
        }

    except httpx.HTTPStatusError as e:
        logger.error("Perplexity API error %s: %s", e.response.status_code, e)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Perplexity response as JSON: %s", e)
    except Exception as e:
        logger.error("GP lookup failed: %s", e)

    return None
