"""Input safety boundary for the buyer agent.

This is an early, deterministic gate—not the sole security control. Its job is
to stop overt attempts to replace agent instructions or expose internal data
before they enter any model prompt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SAFE_REFUSAL = (
    "I can help with shopping, comparisons, and checkout questions, but I "
    "can’t follow requests to change my instructions, bypass safeguards, or "
    "reveal protected information. What product are you looking for?"
)


@dataclass(frozen=True)
class PromptSafetyAssessment:
    blocked: bool
    category: str | None = None


_CONTROL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|override)\b.{0,80}\b"
            r"(previous|prior|above|system|developer)\b.{0,40}\b"
            r"(instructions?|rules?|prompt|policy)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|show|print|repeat|dump|extract|give|share|output)\b.{0,80}\b"
            r"(system prompt|developer message|hidden instructions?|secret key|api key)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "encoded_control_instruction",
        re.compile(
            r"\b(decode|base64|rot13|encoded)\b.{0,100}\b"
            r"(instructions?|prompt|system|developer|policy|rules?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "safeguard_bypass",
        re.compile(
            r"\b(jailbreak|dan mode|bypass|disable)\b.{0,80}\b"
            r"(guardrails?|safety|policy|filters?|restrictions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_injection",
        re.compile(
            r"\b(you are now|act as|roleplay as)\b.{0,80}\b"
            r"(system|developer|administrator|unrestricted|jailbreak)\b",
            re.IGNORECASE,
        ),
    ),
)


def assess_customer_message(message: str) -> PromptSafetyAssessment:
    """Classify clear control-plane attacks without logging the raw message."""
    normalized = unicodedata.normalize("NFKC", message)
    normalized = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    for category, pattern in _CONTROL_PATTERNS:
        if pattern.search(normalized):
            return PromptSafetyAssessment(blocked=True, category=category)
    return PromptSafetyAssessment(blocked=False)


def safe_offer_for_model(offer: dict) -> dict:
    """Whitelist merchant facts allowed into the final response prompt."""
    fields = (
        "merchant", "product_name", "price", "original_price",
        "currency", "pack_size", "required_quantity", "effective_quantity",
        "estimated_total", "negotiated", "item_query",
    )
    return {field: offer.get(field) for field in fields if field in offer}
