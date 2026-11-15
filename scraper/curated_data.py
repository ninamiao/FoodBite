"""Small deterministic helpers for the reviewed frontend event dataset."""

from __future__ import annotations

import hashlib
import re
from typing import Any


FOOD_STATUS = {"confirmed_free", "provided_cost_unknown", "food_unconfirmed", "not_provided"}

FOOD_MENTION_RE = re.compile(
    r"\b(?:food|meals?|snacks?|refreshments?|pastr(?:y|ies)|pizza|boba|drinks?|catered|catering|"
    r"beverages?|coffee|tea|juice|chocolate|pan dulce|produce|fruit|sandwich(?:es)?|"
    r"tacos?|doughnuts?|donuts?|cookies?|bread|cocoa|lunch|dinner|breakfast|milk|water)\b",
    re.I,
)

_NON_FOOD_CONTEXT_REPLACEMENTS = (
    re.compile(r"\bwater polo\b", re.I),
    re.compile(r"\b(?:please\s+)?bring\b[^.]{0,120}\bwater\b", re.I),
    re.compile(r"\bland and water\b", re.I),
    re.compile(r"\blunchboxes?\b", re.I),
    re.compile(r"\blunch with (?:the )?chancellor\b", re.I),
)


def food_relevance_reason(event: dict[str, Any]) -> str | None:
    """Return why source content belongs in FreeBite, or None if irrelevant.

    Food-status values that already establish provision are retained. Otherwise,
    actual food-related source mentions qualify for review, while common
    non-provision contexts (sports, attendee-supplied water, metaphors, and
    historical lunchbox exhibits) are ignored.
    """
    if event.get("food_status") in {"confirmed_free", "provided_cost_unknown"}:
        return "Food provision is explicitly supported by the curated status."

    evidence = event.get("evidence") or {}
    extraction_evidence = event.get("extraction_evidence") or {}
    values = [
        event.get("title"),
        event.get("description"),
        event.get("food_description"),
        evidence.get("provides_food"),
        evidence.get("food_description"),
        extraction_evidence.get("provides_food"),
        extraction_evidence.get("food_description"),
    ]
    source_text = " ".join(value for value in values if isinstance(value, str) and value.strip())
    contextual_text = source_text
    for pattern in _NON_FOOD_CONTEXT_REPLACEMENTS:
        contextual_text = pattern.sub(" ", contextual_text)
    if FOOD_MENTION_RE.search(contextual_text):
        return "The source explicitly mentions food or a beverage; provision remains uncertain."
    return None


def normalize_eligibility(value: str | None) -> str | None:
    """Standardize only source-supported broad eligibility; retain student scope."""
    if value is None or not value.strip():
        return None
    clean = re.sub(r"\s+", " ", value).strip().rstrip(".")
    clean = re.sub(r"\s+,", ",", clean)
    lowered = clean.casefold()

    if (
        lowered in {"everyone is welcome", "everyone welcome", "any and everyone", "all are welcome", "open to all"}
        or "no uc san diego affiliation is required" in lowered
        or lowered in {"open to the public", "open to public", "open to everyone"}
        or lowered in {"uc san diego community and beyond", "open to the uc san diego community and beyond"}
    ):
        return "Everyone"

    if lowered in {"all students are welcome", "all students welcome"}:
        # All students is not the same audience as everyone.
        return "All students"

    if lowered.startswith("open to all students of all majors"):
        if "arts and humanities" in lowered:
            return "All UC San Diego students; Arts and Humanities emphasized"
        return "All UC San Diego students"

    return clean[0].upper() + clean[1:] if clean else clean


def derive_food_status(
    provides_food: bool | None,
    is_free: bool | None,
    provision_evidence: str | None,
    free_food_evidence: str | None,
) -> str:
    """Derive food status only when both the claim and relevant evidence exist."""
    if provides_food is False and provision_evidence:
        return "not_provided"
    if provides_food is not True or not provision_evidence:
        return "food_unconfirmed"
    if is_free is True and free_food_evidence and re.search(
        r"\bfree\b.{0,35}\b(food|meal|drink|beverage|boba|snacks?|refreshments?|coffee|pastry|produce)\b|"
        r"\b(food|meal|drink|beverage|boba|snacks?|refreshments?|coffee|pastry|produce)\b.{0,35}\bfree\b",
        free_food_evidence,
        re.I,
    ):
        return "confirmed_free"
    return "provided_cost_unknown"


def stable_event_id(event: dict[str, Any]) -> str:
    """Use the event URL where possible; otherwise hash stable source identity."""
    identity = event.get("event_url") or "|".join(
        str(event.get(key) or "") for key in ("source_url", "title", "date", "location")
    )
    return "event-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def duplicate_key(event: dict[str, Any]) -> tuple[str, ...]:
    """Occurrences with distinct event URLs or dates remain separate."""
    url = str(event.get("event_url") or "").strip().casefold()
    if url:
        return ("url", url)
    return tuple(str(event.get(key) or "").strip().casefold() for key in ("title", "date", "location", "source_url"))
