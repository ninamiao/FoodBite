"""Extract evidence-backed free-food events from a locally saved HTML page.

The source is preprocessed locally with BeautifulSoup. A Gemini request is made
only when --confirm-api is supplied; --dry-run never contacts the API.
"""

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MODEL_ENV = "GEMINI_MODEL"
REQUEST_TIMEOUT_MS = 60_000
MAX_REQUESTS_PER_MINUTE = 15
MIN_REQUEST_INTERVAL_SECONDS = 60.0 / MAX_REQUESTS_PER_MINUTE + 0.1

EVENT_FIELDS = (
    "title",
    "description",
    "date",
    "start_time",
    "end_time",
    "location",
    "address",
    "provides_food",
    "is_free",
    "food_description",
    "eligibility",
    "registration_url",
    "event_url",
    "source_url",
    "evidence",
)
EVIDENCE_FIELDS = (
    "title",
    "date",
    "time",
    "location",
    "address",
    "provides_food",
    "is_free",
    "food_description",
    "eligibility",
)
FIELD_EVIDENCE = {
    "title": "title",
    "date": "date",
    "start_time": "time",
    "end_time": "time",
    "location": "location",
    "address": "address",
    "provides_food": "provides_food",
    "is_free": "is_free",
    "food_description": "food_description",
    "eligibility": "eligibility",
}
class ExtractError(Exception):
    """An actionable extraction or validation error."""


class StageError(ExtractError):
    def __init__(self, stage: str, category: str, message: str, *, duration: float | None = None,
                 status_code: int | None = None, raw_message: str | None = None, failed_stage: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.category = category
        self.duration = duration
        self.status_code = status_code
        self.raw_message = raw_message
        self.failed_stage = failed_stage or ("parsing" if "parse" in stage.lower() else "server_response")


class EventEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None
    date: str | None
    time: str | None
    location: str | None
    address: str | None
    provides_food: str | None
    is_free: str | None
    food_description: str | None
    eligibility: str | None


class FreeBiteEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str
    description: str | None
    date: str | None
    start_time: str | None
    end_time: str | None
    location: str | None
    address: str | None
    provides_food: bool | None
    is_free: bool | None
    food_description: str | None
    eligibility: str | None
    registration_url: str | None
    event_url: str | None
    source_url: str
    evidence: EventEvidence


EVENT_LIST_ADAPTER = TypeAdapter(list[FreeBiteEvent])


def normalize_text(value: Any) -> str:
    """Normalize whitespace while retaining the source wording verbatim."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _iter_event_objects(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _iter_event_objects(item)
    elif isinstance(value, dict):
        event_type = value.get("@type")
        if event_type == "Event" or (isinstance(event_type, list) and "Event" in event_type):
            yield value
        elif isinstance(value.get("@graph"), list):
            yield from _iter_event_objects(value["@graph"])


def _event_url(event: dict[str, Any]) -> str:
    value = event.get("url")
    if isinstance(value, list):
        value = value[0] if value else None
    return normalize_text(value)


def _card_index(soup: BeautifulSoup) -> dict[str, str]:
    """Map visible event URLs to their cleaned card text and useful links."""
    cards: dict[str, str] = {}
    for card in soup.select(".em-card"):
        for item in card.select("script, style, nav, footer, button, .em-card-share, .em-share"):
            item.decompose()
        for anchor in card.find_all("a"):
            if re.match(r"share\b", normalize_text(anchor.get_text(" ", strip=True)), re.I):
                anchor.decompose()
        link_rows: list[str] = []
        for anchor in card.find_all("a", href=True):
            label = normalize_text(anchor.get_text(" ", strip=True))
            href = normalize_text(anchor.get("href"))
            if href and ("/event/" in href or re.search(r"register|ticket|rsvp|apply", label, re.I)):
                link_rows.append(f"Link: {label or 'Event'} | URL: {href}")
        card_text = normalize_text(card.get_text(" ", strip=True))
        if link_rows:
            card_text = normalize_text(f"{card_text} {' '.join(link_rows)}")
        for anchor in card.find_all("a", href=True):
            href = normalize_text(anchor.get("href"))
            if "/event/" in href:
                cards[href] = card_text
    return cards


def _jsonld_event_text(event: dict[str, Any], visible_card: str = "") -> str:
    """Serialize only event fields that can help identify food opportunities."""
    location = event.get("location")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, dict):
        location_values = [location.get("name"), location.get("address")]
        location_text = " | ".join(normalize_text(item) for item in location_values if item)
    else:
        location_text = normalize_text(location)

    offers = event.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    offer_text = []
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                parts = [offer.get("price"), offer.get("priceCurrency"), offer.get("description"), offer.get("url")]
                rendered = " | ".join(normalize_text(part) for part in parts if part is not None)
                if rendered:
                    offer_text.append(rendered)

    pieces = [
        f"Title: {normalize_text(event.get('name'))}",
        f"Description: {normalize_text(event.get('description'))}",
        f"Start: {normalize_text(event.get('startDate'))}",
        f"End: {normalize_text(event.get('endDate'))}",
        f"Location: {location_text}",
        f"Event URL: {_event_url(event)}",
    ]
    if offer_text:
        pieces.append("Offers: " + " ; ".join(offer_text))
    if visible_card:
        pieces.append("Visible listing card: " + visible_card)
    return "\n".join(piece for piece in pieces if piece.strip())


def _page_source_url(soup: BeautifulSoup) -> str | None:
    canonical = soup.find("link", rel=lambda rel: rel and "canonical" in rel)
    if canonical and canonical.get("href"):
        return normalize_text(canonical["href"])
    for attrs in ({"property": "og:url"}, {"name": "twitter:url"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            return normalize_text(meta["content"])
    return None


def preprocess_html(html: str, source_url: str | None = None) -> dict[str, Any]:
    """Return compact source text for every usable JSON-LD event record.

    This UCSD calendar uses per-event JSON-LD blocks and `.em-card` listings.
    JSON-LD retains descriptions and full date/time values for events not
    currently visible in the card list, so it is the primary source. Candidate
    selection intentionally has no food keyword filter: Gemini decides whether
    food is actually served. If JSON-LD is absent, all visible event cards are
    used, followed by main-page text as a final fallback.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_title = normalize_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    detected_source_url = source_url or _page_source_url(soup)
    card_text_by_url = _card_index(soup)
    event_sources: list[dict[str, str]] = []
    jsonld_event_count = 0

    for script in soup.select('script[type="application/ld+json"]'):
        raw_json = script.string or script.get_text()
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for event in _iter_event_objects(data):
            jsonld_event_count += 1
            event_text = _jsonld_event_text(event, card_text_by_url.get(_event_url(event), ""))
            title = normalize_text(event.get("name"))
            # A usable event needs a title plus some source content beyond it.
            if title and event_text:
                event_sources.append(
                    {"title": title, "text": event_text, "event_url": _event_url(event)}
                )

    if not event_sources:
        for card in soup.select(".em-card"):
            for item in card.select("script, style, nav, footer, button, .em-card-share, .em-share"):
                item.decompose()
            for anchor in card.find_all("a"):
                if re.match(r"share\b", normalize_text(anchor.get_text(" ", strip=True)), re.I):
                    anchor.decompose()
            text = normalize_text(card.get_text(" ", strip=True))
            links = [normalize_text(a.get("href")) for a in card.find_all("a", href=True)]
            text = normalize_text(f"{text} {' '.join(link for link in links if link)}")
            title_link = card.find("a", href=lambda href: href and "/event/" in href)
            title = normalize_text(title_link.get_text(" ", strip=True)) if title_link else ""
            if title and text:
                event_sources.append(
                    {"title": title, "text": text, "event_url": next((u for u in links if "/event/" in u), "")}
                )

    fallback_used = False
    if not event_sources:
        fallback_used = True
        for item in soup.select("script, style, nav, footer, header, form, button, [role='navigation'], [aria-hidden='true']"):
            item.decompose()
        main = soup.find("main") or soup.body or soup
        blocks = main.find_all(["article", "section", "p", "li", "h2", "h3"], recursive=True)
        seen: set[str] = set()
        for block in blocks:
            text = normalize_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text in seen:
                continue
            seen.add(text)
            event_sources.append({"title": normalize_text(block.get_text(" ", strip=True))[:180], "text": text, "event_url": ""})

    # Keep repeated JSON-LD records for separate dates, but remove byte-for-byte duplicates.
    unique_sources: list[dict[str, str]] = []
    seen_sources: set[tuple[str, str]] = set()
    for source in event_sources:
        key = (source["event_url"], source["text"])
        if key not in seen_sources:
            seen_sources.add(key)
            unique_sources.append(source)

    heading = [f"Page title: {page_title}" if page_title else ""]
    if detected_source_url:
        heading.append(f"Listing source URL: {detected_source_url}")
    heading.append("Candidate event records (broad, unclassified; source wording preserved):")
    record_text = [f"[Candidate {index}]\n{item['text']}" for index, item in enumerate(unique_sources, 1)]
    preprocessed_text = "\n\n".join(part for part in (*heading, *record_text) if part)
    return {
        "text": preprocessed_text,
        "candidates": unique_sources,
        "jsonld_event_count": jsonld_event_count,
        "candidate_count": len(unique_sources),
        "source_url": detected_source_url,
        "page_title": page_title,
        "fallback_used": fallback_used,
    }


EVENT_JSON_SCHEMA: dict[str, Any] = EVENT_LIST_ADAPTER.json_schema()


def build_prompt(preprocessed_text: str, source_url: str) -> str:
    """Build extraction instructions separately from deterministic validation."""
    return f"""For each candidate event below, decide whether the source says food or drinks are actually provided or served. The candidate set is deliberately broad; many entries may be unrelated.

Return only a JSON array matching the configured schema. Use null for every unknown field.
Do not invent, infer, or fill gaps. Do not treat a general campus announcement as an event. Set provides_food=true only when the source indicates something edible or drinkable will actually be served, offered, available, distributed, received, or enjoyed. Explicit food distribution or serving counts as provision. Mere mentions of objects such as lunchboxes, food-themed exhibits, or campus traditions do not mean food is served. Use false only when the source explicitly says no food/drinks are provided; otherwise use null.
Treat provides_food and is_free as separate facts. is_free describes the cost of the food/drinks themselves, never merely whether the event is free. Set is_free=true only when the source explicitly says the provided food/drinks are free, false only when it explicitly gives a price for the provided food/drinks, otherwise null. Keep separate exact evidence for food provision and the food's cost.
Distinguish event dates from publication or update dates. Do not interpret relative dates such as tomorrow without an explicit reliable reference date.
Keep eligibility restrictions. Extract each event independently, including repeated dates as separate events only when the source presents them as separate occurrences.
Every non-null description, URL, and evidence value must be copied from the matching candidate record below. Evidence strings must be exact quotations that directly support the corresponding claim, not merely occur elsewhere in the page. If the source does not support a field, set both the field and its corresponding evidence to null. Use an event detail page for event_url and only a clearly labeled registration or RSVP link for registration_url.
Use YYYY-MM-DD for date and 24-hour HH:MM for times when the source supplies enough information to normalize them. Retain evidence in its exact original wording.
The listing source_url for each event must be exactly: {source_url}

Source text:\n{preprocessed_text}"""


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_iso_time(value: str) -> bool:
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M") == value
    except ValueError:
        return False


def _normalize_time(value: str) -> str | None:
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, pattern)
            if pattern.endswith("%S") and parsed.second != 0:
                return None
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    return None


def _time_values(text: str) -> set[str]:
    values: set[str] = set()
    pattern = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\b", re.I)
    for match in pattern.finditer(text):
        hour, minute, seconds, meridiem = match.groups()
        if seconds not in (None, "00"):
            continue
        h, m = int(hour), int(minute)
        if m > 59:
            continue
        if meridiem:
            if not 1 <= h <= 12:
                continue
            h = h % 12 + (12 if meridiem.upper() == "PM" else 0)
        elif h > 23:
            continue
        values.add(f"{h:02d}:{m:02d}")
    simple = re.compile(r"(?<!\d)(\d{1,2})\s*(AM|PM)\b", re.I)
    for match in simple.finditer(text):
        hour = int(match.group(1))
        if 1 <= hour <= 12:
            hour = hour % 12 + (12 if match.group(2).upper() == "PM" else 0)
            values.add(f"{hour:02d}:00")
    return values


MONTHS = {name.lower(): number for number, name in enumerate(("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if name}
MONTH_PATTERN = "|".join(MONTHS)


def _date_values(text: str, year_hint: int | None) -> tuple[set[str], bool]:
    values: set[str] = set()
    for match in re.finditer(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text):
        try:
            values.add(date.fromisoformat(match.group(1)).isoformat())
        except ValueError:
            pass
    month_matches = list(re.finditer(rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", text, re.I))
    for match in month_matches:
        year = int(match.group(3)) if match.group(3) else year_hint
        if year is None:
            continue
        month = MONTHS[match.group(1).lower()]
        try:
            values.add(date(year, month, int(match.group(2))).isoformat())
        except ValueError:
            pass
    range_clause = len(month_matches) >= 2 and bool(re.search(r"\b(?:through|until|to)\b|[–—-]", text, re.I))
    return values, range_clause


def _explicit_free_evidence(value: str, is_free: bool) -> bool:
    food = r"(?:food|meal|snack|drink|beverage|refreshment|coffee|tea|pastr\w*|produce|chocolate|boba|pan\s+dulce|pizza|bagel|sandwich|cookie|donut|doughnut|grocery|groceries|pantry|shelf[- ]stable items?)"
    if is_free:
        free_before_food = rf"\bfree\s+(?:(?:and|of|for|the|our|your|fresh|hot|cold|provided|available)\s+){{0,3}}{food}\b"
        food_before_free = rf"\b{food}\s+(?:(?:is|are|was|were|will\s+be|provided|served|available)\s+){{0,3}}free\b"
        no_cost = rf"\bno[- ]cost\s+(?:(?:and|of|for|the)\s+){{0,2}}{food}\b"
        return bool(re.search(f"{free_before_food}|{food_before_free}|{no_cost}", value, re.I))
    return bool(re.search(rf"\b{food}\b.{{0,50}}(?:\$\s*\d|\b\d+(?:\.\d{{2}})?\s*(?:USD|dollars?)\b|\bpaid\b|\bcosts?\b|\bprice\b)", value, re.I))


FOOD_TERM = re.compile(
    r"\b(?:food|beverages?|drinks?|refreshments?|snacks?|meals?|breakfast|lunch|dinner|"
    r"coffee|tea|cocoa|pastries|pastry|produce|boba|chocolate|pan\s+dulce|pizza|bagels?|"
    r"sandwiches?|cookies?|donuts?|doughnuts?|groceries|grocery|pantry|shelf[- ]stable items?)\b",
    re.I,
)
PROVISION_TERM = re.compile(
    r"\b(?:serv(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|distribut(?:e|s|ed|ing|ion)|"
    r"receiv(?:e|es|ed|ing)|available|offer(?:s|ed|ing)?|includes?|enjoy(?:s|ed|ing)?|"
    r"hand(?:s|ed)?\s+out|grab(?:s|bed|bing)?)\b|"
    r"\b(?:come|join)\s+(?:on\s+over\s+)?for\b",
    re.I,
)


def _find_food_provision_evidence(source_text: str) -> str | None:
    for segment in re.split(r"(?<=[.!?])\s+|\n+", source_text):
        segment = normalize_text(segment)
        explicit_denial = re.search(
            r"\b(?:no|not|without)\s+(?:food|drinks?|beverages?|refreshments?|meals?|snacks?)\b|"
            r"\b(?:food|drinks?|beverages?|refreshments?|meals?|snacks?)\s+(?:will not|are not|aren't|is not|isn't)\b",
            segment,
            re.I,
        )
        if FOOD_TERM.search(segment) and PROVISION_TERM.search(segment) and not explicit_denial:
            # Exclude a mere object/club mention such as lunchboxes.
            if re.search(r"\blunchboxes?\b", segment, re.I) and not re.search(r"\b(?:food|meal|lunch|drinks?|beverages?)\b", segment, re.I):
                continue
            return segment
    # A source title can itself explicitly identify distribution of food.
    for line in source_text.splitlines():
        if line.lower().startswith("title:") and re.search(r"\bfood\s+distributions?\b", line, re.I):
            return normalize_text(line.removeprefix("Title:"))
    return None


def _find_free_food_evidence(source_text: str) -> str | None:
    for segment in re.split(r"(?<=[.!?])\s+|\n+", source_text):
        segment = normalize_text(segment)
        if _explicit_free_evidence(segment, True):
            return segment
    return None


def _explicit_food_provision_evidence(value: str, provides_food: bool) -> bool:
    """Require a provision statement tied to edible/drinkable wording.

    This is a conservative field validator, not a candidate-selection filter;
    all usable JSON-LD Event records reach the model regardless of these words.
    """
    sentences = re.split(r"(?<=[.!?])\s+", value)
    food_or_drink = re.compile(
        r"\b(?:food|drink|beverage|refreshment|snack|meal|lunch|dinner|breakfast|"
        r"coffee|tea|pastr\w*|produce|chocolate|boba|pan\s+dulce|pizza|bagel|"
        r"sandwich|cookie|donut|doughnut|grocery|groceries|pantry)\w*\b",
        re.I,
    )
    if provides_food:
        provision = re.compile(
            r"\b(?:served|serving|provided|providing|available|distributions?|distributed|"
            r"receive|received|enjoy|enjoying|includes|included|include|offers?|offered)\b|"
            r"\b(?:join us|come join us|come on over)\s+for\b",
            re.I,
        )
        return any(food_or_drink.search(sentence) and provision.search(sentence) for sentence in sentences)
    no_provision = re.compile(
        r"\b(?:no|not|without)\s+(?:food|drinks?|beverages?|refreshments?|meals?|snacks?)\b|"
        r"\bfood\s+(?:will not|is not|isn't)\s+(?:be\s+)?(?:served|provided)\b",
        re.I,
    )
    return bool(no_provision.search(value))


def _blank_field(event: dict[str, Any], evidence: dict[str, Any], field: str) -> None:
    event[field] = None
    evidence_key = FIELD_EVIDENCE.get(field)
    if evidence_key:
        evidence[evidence_key] = None


def validate_events(
    payload: Any,
    source_text: str,
    source_url: str,
    source_records: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Validate each event against its own candidate source text."""
    if not isinstance(payload, list):
        raise ExtractError("Gemini output must be a JSON array of events.")
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    flagged: list[str] = []
    expected_keys = set(EVENT_FIELDS)
    expected_evidence = set(EVIDENCE_FIELDS)
    records = list(source_records) if source_records is not None else []

    for index, original in enumerate(payload, 1):
        label = f"event {index}"
        if not isinstance(original, dict) or set(original) != expected_keys:
            rejected.append(f"{label} [schema]: missing/extra event keys or value is not an object")
            continue
        try:
            event = FreeBiteEvent.model_validate(original).model_dump()
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field_name = ".".join(str(part) for part in first_error.get("loc", ())) or "event"
            rejected.append(f"{label} [schema]: invalid type or value for {field_name}")
            continue
        evidence = event["evidence"]
        if set(evidence) != expected_evidence:
            rejected.append(f"{label} [evidence_schema]: missing/extra evidence keys")
            continue
        if not isinstance(event.get("title"), str) or not event["title"].strip():
            rejected.append(f"{label} [title]: missing usable title")
            continue
        if not isinstance(event.get("source_url"), str) or not event["source_url"].strip():
            rejected.append(f"{label} [source_url]: missing source_url")
            continue

        event["title"] = normalize_text(event["title"])
        evidence = {key: normalize_text(value) if value is not None else None for key, value in evidence.items()}
        if records:
            event_records = records
        else:
            fallback_title = evidence.get("title") if evidence.get("title") in source_text else event["title"]
            # Build fallback context per event; never let the first event's title
            # constrain matching for later events in the same response.
            event_records = [{"title": fallback_title, "text": source_text, "event_url": event.get("event_url") or ""}]
        response_url = normalize_text(event.get("event_url") or "")
        url_matches = [record for record in event_records if response_url and record.get("event_url") == response_url]
        matched = url_matches[0] if url_matches else None
        if matched is None:
            title_matches = [record for record in event_records if normalize_text(record.get("title", "")).casefold() == event["title"].casefold()]
            if len(title_matches) > 1 and evidence.get("date"):
                by_date = [record for record in title_matches if evidence["date"] in record.get("text", "")]
                if len(by_date) == 1:
                    title_matches = by_date
            if len(title_matches) == 1:
                matched = title_matches[0]
        if matched is None:
            rejected.append(f"{label} [source_title]: title does not match a candidate event heading")
            continue
        record_text = matched.get("text", "")
        canonical_title = normalize_text(matched.get("title", ""))
        if event["title"].casefold() != canonical_title.casefold():
            rejected.append(f"{label} [source_title]: title differs from its candidate heading")
            continue
        if evidence.get("title") != canonical_title:
            evidence["title"] = canonical_title
            flagged.append(f"{label} [title_evidence_repaired]: restored exact source heading")
        for evidence_key, quote in evidence.items():
            if quote is not None and quote not in record_text:
                evidence[evidence_key] = None
                flagged.append(f"{label} [unsupported_evidence]: {evidence_key} quote is absent from matching record")
        event["evidence"] = evidence

        if event["date"] is not None and not _is_iso_date(event["date"]):
            rejected.append(f"{label} [date_format]: invalid date {event['date']!r}; expected YYYY-MM-DD")
            continue
        bad_time = False
        for key in ("start_time", "end_time"):
            if event[key] is not None:
                normalized_time = _normalize_time(event[key])
                if normalized_time is None:
                    rejected.append(f"{label} [time_format]: invalid {key} {event[key]!r}")
                    bad_time = True
                    break
                if normalized_time != event[key]:
                    event[key] = normalized_time
                    flagged.append(f"{label} [time_normalized]: normalized {key} to {normalized_time}")
        if bad_time:
            continue

        start_match = re.search(r"^Start:\s*(\d{4}-\d{2}-\d{2})", record_text, re.M)
        end_match = re.search(r"^End:\s*(\d{4}-\d{2}-\d{2})", record_text, re.M)
        source_start_date = start_match.group(1) if start_match else None
        source_end_date = end_match.group(1) if end_match else None
        year_hint = int(source_start_date[:4]) if source_start_date else None
        _, source_has_range = _date_values(record_text, year_hint)
        is_display_period = (
            bool(re.search(r"\b(?:on view|on display|exhibition|display)\b", record_text, re.I))
            and source_has_range
        )
        if event["date"] is not None:
            date_quote = evidence.get("date")
            supported_dates, range_quote = _date_values(date_quote or "", year_hint)
            if is_display_period:
                event["date"] = None
                evidence["date"] = None
                flagged.append(f"{label} [ongoing_display]: source describes a multi-day display period, not one event date")
            elif source_start_date and source_end_date and event["date"] != source_start_date:
                event["date"] = None
                evidence["date"] = None
                flagged.append(f"{label} [date_conflict]: date does not match the source Start date {source_start_date}")
            elif date_quote is None or range_quote or event["date"] not in supported_dates:
                event["date"] = None
                evidence["date"] = None
                flagged.append(f"{label} [date_conflict]: date is not supported as a single occurrence by its evidence")
        for key in ("start_time", "end_time"):
            if event[key] is not None:
                time_quote = evidence.get("time")
                if time_quote is None or event[key] not in _time_values(time_quote):
                    event[key] = None
                    evidence["time"] = None
                    flagged.append(f"{label} [time_conflict]: {key} is not supported by its time evidence")

        for key in ("description", "registration_url", "event_url"):
            if event[key] is not None and event[key] not in record_text:
                event[key] = None
                flagged.append(f"{label} [unsupported_field]: cleared unsupported {key}")
        for key in ("location", "address", "eligibility", "food_description"):
            value = event[key]
            quote = evidence.get(FIELD_EVIDENCE[key])
            if value is not None and (quote is None or value.casefold() not in quote.casefold()):
                event[key] = None
                evidence[FIELD_EVIDENCE[key]] = None
                flagged.append(f"{label} [unsupported_field]: cleared {key} without corresponding evidence")

        provision_quote = _find_food_provision_evidence(record_text)
        if provision_quote:
            if event["provides_food"] is not True:
                flagged.append(f"{label} [food_provision_corrected]: source explicitly says food/drinks are provided")
            event["provides_food"] = True
            evidence["provides_food"] = provision_quote
        elif event["provides_food"] is not None:
            quote = evidence.get("provides_food")
            if quote is None or not _explicit_food_provision_evidence(quote, bool(event["provides_food"])):
                event["provides_food"] = None
                evidence["provides_food"] = None
                flagged.append(f"{label} [unsupported_food_status]: cleared unsupported provides_food value")

        free_quote = _find_free_food_evidence(record_text) if event["provides_food"] is True else None
        if event["provides_food"] is not True:
            if event["is_free"] is not None:
                flagged.append(f"{label} [food_price_unknown]: event price does not establish a food price")
            event["is_free"] = None
            evidence["is_free"] = None
        elif free_quote:
            if event["is_free"] is not True or evidence.get("is_free") != free_quote:
                flagged.append(f"{label} [food_price_corrected]: source explicitly says provided food/drinks are free")
            event["is_free"] = True
            evidence["is_free"] = free_quote
        elif event["is_free"] is not None:
            quote = evidence.get("is_free")
            if quote is None or not _explicit_free_evidence(quote, bool(event["is_free"])):
                event["is_free"] = None
                evidence["is_free"] = None
                flagged.append(f"{label} [unsupported_food_price]: cleared unsupported food-price value")

        if event["address"] is not None:
            structured_address = re.search(r"^Location:.*?\|\s*(.+)$", record_text, re.M)
            prose_address = re.search(r"\bAddress:\s*([^\n.]+)", record_text, re.I)
            if structured_address and prose_address:
                structured = normalize_text(structured_address.group(1)).casefold()
                prose = normalize_text(prose_address.group(1)).casefold()
                if event["address"].casefold() in prose and event["address"].casefold() not in structured and structured not in prose:
                    event["address"] = None
                    evidence["address"] = None
                    flagged.append(f"{label} [address_conflict]: source contains conflicting structured and prose addresses")

        event["source_url"] = source_url
        accepted.append(event)
    return accepted, rejected, flagged

def _normalized_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value).casefold()).strip()


def _identity(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        normalize_text(event.get(key) or "").casefold()
        for key in ("title", "date", "location", "source_url")
    )  # type: ignore[return-value]


def _duplicate_pair(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Require same occurrence date/source plus strong URL or title/venue match."""
    if normalize_text(left.get("date") or "") != normalize_text(right.get("date") or ""):
        return False
    if normalize_text(left.get("source_url") or "").casefold() != normalize_text(right.get("source_url") or "").casefold():
        return False
    left_url = normalize_text(left.get("event_url") or "").casefold()
    right_url = normalize_text(right.get("event_url") or "").casefold()
    if left_url and right_url and left_url == right_url:
        return True
    left_title, right_title = _normalized_title(left.get("title")), _normalized_title(right.get("title"))
    similarity = difflib.SequenceMatcher(None, left_title, right_title).ratio()
    if similarity < 0.9:
        return False
    left_location = _normalized_title(left.get("location"))
    right_location = _normalized_title(right.get("location"))
    if not left_location or not right_location or left_location != right_location:
        return False
    left_start, right_start = left.get("start_time"), right.get("start_time")
    return not (left_start and right_start and left_start != right_start)


def _merge_compatible(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = dict(left)
    merged_evidence = dict(left.get("evidence") or {})
    conflicts: list[str] = []
    for key in EVENT_FIELDS:
        if key == "evidence":
            continue
        a, b = merged.get(key), right.get(key)
        if a is not None and b is not None and a != b:
            if key == "title" and _normalized_title(a) == _normalized_title(b):
                continue
            conflicts.append(key)
        elif a is None and b is not None:
            merged[key] = b
    for key, value in (right.get("evidence") or {}).items():
        current = merged_evidence.get(key)
        if current is not None and value is not None and current != value:
            conflicts.append(f"evidence.{key}")
        elif current is None and value is not None:
            merged_evidence[key] = value
    merged["evidence"] = merged_evidence
    return merged, sorted(set(conflicts))


def merge_events_detailed(existing: Any, new_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    """Deduplicate compatible same-occurrence records and flag conflicts without discarding either."""
    if not isinstance(existing, list):
        raise ExtractError("data/events.json must contain a JSON array to preserve its existing structure.")
    if any(not isinstance(item, dict) for item in existing):
        raise ExtractError("Existing events JSON contains a non-object entry; refusing to discard it.")
    merged = list(existing)
    added = updated = 0
    flags: list[str] = []
    for candidate in new_events:
        matches = [index for index, item in enumerate(merged) if _duplicate_pair(item, candidate)]
        if not matches:
            # Drop exact byte/value duplicates even if optional fields have no identity data.
            if candidate in merged:
                flags.append(f"[exact_duplicate]: skipped exact duplicate {candidate.get('title')!r} on {candidate.get('date')!r}")
                continue
            merged.append(candidate)
            added += 1
            continue
        index = matches[0]
        combined, conflicts = _merge_compatible(merged[index], candidate)
        if conflicts:
            flags.append(f"[duplicate_conflict]: retained both {candidate.get('title')!r} records on {candidate.get('date')!r}; conflicting fields: {', '.join(conflicts)}")
            merged.append(candidate)
        else:
            changed = combined != merged[index]
            merged[index] = combined
            updated += int(changed)
            # Similar duplicate records may be omitted after complementary fields are preserved.
    return merged, added, updated, flags


def merge_events(existing: Any, new_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Compatibility wrapper around conservative duplicate-aware merging."""
    merged, added, updated, _ = merge_events_detailed(existing, new_events)
    return merged, added, updated


def save_events(path: Path, events: list[dict[str, Any]]) -> None:
    """Atomically write UTF-8 JSON without replacing the file until serialization succeeds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(events, ensure_ascii=False, indent=2) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(serialized)
        os.replace(temporary_name, path)
    except OSError:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def save_json_new(path: Path, value: Any) -> None:
    """Write a JSON artifact without ever replacing an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _unique_run_stem() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S_%fZ')}_{uuid.uuid4().hex[:8]}"


def _stage(stage: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"[{timestamp}] {stage}", flush=True)


def chunk_candidates(candidates: list[dict[str, str]], batch_size: int = 10) -> list[list[dict[str, str]]]:
    if batch_size < 1:
        raise ValueError("batch size must be at least 1")
    return [candidates[index:index + batch_size] for index in range(0, len(candidates), batch_size)]


def render_candidate_batch(prepared: dict[str, Any], batch: list[dict[str, str]], offset: int) -> str:
    """Render original candidate text in a numbered batch without altering the prompt instructions."""
    sections = []
    if prepared.get("page_title"):
        sections.append(f"Page title: {prepared['page_title']}")
    if prepared.get("source_url"):
        sections.append(f"Listing source URL: {prepared['source_url']}")
    sections.append("Candidate event records (broad, unclassified; source wording preserved):")
    sections.extend(f"[Candidate {offset + index}]\n{record['text']}" for index, record in enumerate(batch, 1))
    return "\n\n".join(sections)


def _safe_api_message(exc: Exception, api_key: str) -> str:
    raw = getattr(exc, "message", None)
    if not isinstance(raw, str) or not raw.strip():
        raw = str(exc)
    raw = raw.replace(api_key, "[REDACTED]") if api_key else raw
    raw = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [REDACTED]", raw)
    raw = re.sub(r"(?i)([?&]key=)[^&\s]+", r"\1[REDACTED]", raw)
    return " ".join(raw.split())[:1000]


def read_json_response(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ExtractError("Gemini returned invalid JSON; events.json was not changed.") from exc


def load_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ExtractError("GEMINI_API_KEY is missing. Add it to the project-root .env file.")
    return api_key


def get_model_name() -> str:
    """Return the configured Gemini model or the current stable default."""
    load_dotenv(PROJECT_ROOT / ".env")
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL).strip() or DEFAULT_MODEL


def call_gemini(api_key: str, model: str, prompt: str) -> str:
    """Make one bounded SDK request with SDK-level retries disabled."""
    from google import genai
    from google.genai import types

    started = time.perf_counter()
    try:
        with genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_json_schema=EVENT_JSON_SCHEMA,
                    automatic_continuation=False,
                ),
            )
    except Exception as exc:
        duration = round(time.perf_counter() - started, 3)
        status_code = getattr(exc, "code", None)
        if not isinstance(status_code, int):
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        raw_message = _safe_api_message(exc, api_key)
        exception_types = {cls.__name__.lower() for cls in type(exc).__mro__}
        if isinstance(exc, TimeoutError) or any("timeout" in name for name in exception_types):
            raise StageError("API_REQUEST_STARTED", "timeout", f"Gemini request timed out after {REQUEST_TIMEOUT_MS // 1000} seconds; no retry was attempted.", duration=duration, status_code=status_code, raw_message=raw_message, failed_stage="network_transit") from None
        if any(token in name for name in exception_types for token in ("connection", "connecterror", "network")):
            raise StageError("API_REQUEST_STARTED", "connection_error", f"Gemini connection failed ({type(exc).__name__}); no retry was attempted.", duration=duration, status_code=status_code, raw_message=raw_message, failed_stage="network_transit") from None
        if any(token in name for name in exception_types for token in ("apierror", "responseerror", "httpresponse", "servererror", "clienterror")):
            raise StageError("API_REQUEST_STARTED", "api_error", f"Gemini API returned an error ({type(exc).__name__}); no retry was attempted.", duration=duration, status_code=status_code, raw_message=raw_message, failed_stage="server_response") from None
        # Avoid logging provider request details, which can contain sensitive data.
        raise StageError("API_REQUEST_STARTED", "api_error", f"Gemini request failed ({type(exc).__name__}); no retry was attempted.", duration=duration, status_code=status_code, raw_message=raw_message, failed_stage="server_response") from None
    return response.text or ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract food events from saved HTML using Gemini.")
    parser.add_argument("html_file", type=Path, help="Path to the saved HTML file")
    parser.add_argument("--source-url", help="Original listing URL (used if the HTML has no canonical URL)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "events.json",
                        help="Existing event array to preserve and merge into the per-run validated artifact")
    parser.add_argument("--run-dir", type=Path, default=PROJECT_ROOT / "data" / "extraction_runs", help="Directory for unique raw, validated, and metadata artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Preview preprocessed input; never calls Gemini")
    parser.add_argument("--confirm-api", action="store_true", help="Send exactly one confirmed Gemini request")
    parser.add_argument("--preview-chars", type=int, default=5000, help="Maximum preview characters in dry-run mode")
    parser.add_argument("--batch-size", type=int, default=10, help="Candidate records per Gemini request (default: 10)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _stage("PREFLIGHT_STARTED")
    if args.batch_size < 1:
        print("Error: --batch-size must be at least 1.", file=sys.stderr)
        return 2
    if not args.html_file.is_file():
        print(f"Last completed stage: PREFLIGHT_STARTED\nFailure stage: PREFLIGHT_STARTED\nError: HTML file does not exist: {args.html_file}\nExit code: 2", file=sys.stderr)
        return 2
    try:
        html = args.html_file.read_text(encoding="utf-8")
        prepared = preprocess_html(html, args.source_url)
    except (OSError, UnicodeError) as exc:
        print(f"Last completed stage: PREFLIGHT_STARTED\nFailure stage: PREFLIGHT_STARTED\nError: Could not read HTML file ({type(exc).__name__}).\nExit code: 1", file=sys.stderr)
        return 1

    print(f"JSON-LD Event records discovered: {prepared['jsonld_event_count']}.")
    print(f"Preprocessed {prepared['candidate_count']} broad candidate record(s).")
    print(f"Approximate Gemini input size: {len(prepared['text']):,} characters.")
    print(f"Configured Gemini model: {get_model_name()}.")
    batches = chunk_candidates(prepared["candidates"], args.batch_size)
    print(f"Batch plan: {len(batches)} batch(es) of up to {args.batch_size} candidate(s).")
    for batch_index, batch in enumerate(batches, 1):
        print(f"Batch {batch_index}/{len(batches)}: {len(batch)} candidate(s).")
    if prepared["fallback_used"]:
        print("Note: Used conservative relevant-text fallback; no event JSON-LD or cards were detected.")
    if args.dry_run:
        preview_limit = max(0, args.preview_chars)
        print("\n--- Preprocessed content preview (not sent to Gemini) ---")
        print(prepared["text"][:preview_limit])
        if len(prepared["text"]) > preview_limit:
            print(f"\n[Preview truncated; {len(prepared['text']) - preview_limit:,} characters omitted]")
        return 0
    if not args.confirm_api:
        print("No Gemini API request sent. Review with --dry-run; pass --confirm-api to send one request.")
        return 0
    if not prepared["source_url"]:
        print("Last completed stage: PREFLIGHT_STARTED\nFailure stage: PREFLIGHT_STARTED\nError: HTML has no canonical listing URL. Pass --source-url before confirming the API call.\nExit code: 2", file=sys.stderr)
        return 2
    if prepared["candidate_count"] == 0:
        print("No food-related source text was found; no Gemini request sent.")
        return 0

    run_stem = _unique_run_stem()
    validated_path = args.run_dir / f"{run_stem}_validated.json"
    metadata_path = args.run_dir / f"{run_stem}_metadata.json"
    attempt = {
        "attempt_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_identifier": None,
        "input_filename": args.html_file.name,
        "source_url": prepared["source_url"],
        "candidate_count": prepared["candidate_count"],
        "batch_size": args.batch_size,
        "batch_count": len(batches),
        "last_completed_stage": "PREFLIGHT_STARTED",
        "final_status": "in_progress",
        "error_type": None,
        "error_message": None,
        "raw_response_file": None,
        "raw_response_files": [],
        "validated_output_file": None,
        "request_duration_seconds": None,
        "http_status_code": None,
        "raw_error_message": None,
        "failed_stage": None,
        "failed_batch": None,
        "failed_batches": [],
        "retry_attempts": 0,
        "retry_log": [],
        "automatic_sdk_retries_disabled": True,
        "batch_results": [],
    }
    failure_stage = "PREFLIGHT_STARTED"
    validated_written = False
    try:
        if validated_path.exists():
            raise FileExistsError(f"Per-run validated artifact already exists: {validated_path}")
        existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else []
        if not isinstance(existing, list) or any(not isinstance(item, dict) for item in existing):
            raise ExtractError("Output JSON must be an array of event objects; refusing to overwrite it.")
        api_key = load_api_key()
        model = get_model_name()
        attempt["model_identifier"] = model
        _stage("PREFLIGHT_PASSED")
        attempt["last_completed_stage"] = "PREFLIGHT_PASSED"
        failure_stage = "PREFLIGHT_PASSED"
        accepted_all: list[dict[str, Any]] = []
        rejected_all: list[str] = []
        flagged_all: list[str] = []
        returned_count = 0
        any_batch_failed = False
        last_request_started: float | None = None
        for batch_index, batch in enumerate(batches, 1):
            batch_label = f"batch {batch_index}/{len(batches)}"
            batch_raw_path = args.run_dir / f"{run_stem}_batch_{batch_index:03d}_raw.json"
            batch_start = time.perf_counter()
            try:
                batch_source = render_candidate_batch(prepared, batch, (batch_index - 1) * args.batch_size + 1)
                batch_prompt = build_prompt(batch_source, prepared["source_url"])
                if last_request_started is not None:
                    wait_seconds = MIN_REQUEST_INTERVAL_SECONDS - (time.perf_counter() - last_request_started)
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                _stage(f"API_REQUEST_STARTED {batch_label}")
                failure_stage = "API_REQUEST_STARTED"
                last_request_started = time.perf_counter()
                raw_response = call_gemini(api_key, model, batch_prompt)
                retry_log: list[dict[str, Any]] = []
                batch_retry_count = 0
                duration = round(time.perf_counter() - batch_start, 3)
                _stage(f"API_RESPONSE_RECEIVED {batch_label}")
                attempt["last_completed_stage"] = "API_RESPONSE_RECEIVED"
                failure_stage = "RAW_RESPONSE_SAVED"
                save_json_new(batch_raw_path, raw_response)
                attempt["raw_response_files"].append(str(batch_raw_path))
                attempt["raw_response_file"] = str(batch_raw_path)
                _stage(f"RAW_RESPONSE_SAVED {batch_label}")
                attempt["last_completed_stage"] = "RAW_RESPONSE_SAVED"
                if not raw_response.strip():
                    raise StageError("API_RESPONSE_RECEIVED", "empty_response", f"Gemini returned an empty response for {batch_label}.", duration=duration, failed_stage="server_response")
                failure_stage = "JSON_PARSE_STARTED"
                _stage(f"JSON_PARSE_STARTED {batch_label}")
                try:
                    parsed = read_json_response(raw_response)
                except ExtractError as exc:
                    raise StageError("JSON_PARSE_STARTED", "json_parse_error", f"Gemini returned invalid JSON for {batch_label}.", duration=duration, raw_message=str(exc), failed_stage="parsing") from None
                attempt["last_completed_stage"] = "JSON_PARSE_STARTED"
                returned_count += len(parsed) if isinstance(parsed, list) else 0
                failure_stage = "VALIDATION_COMPLETED"
                accepted, rejected, flagged = validate_events(parsed, batch_source, prepared["source_url"], batch)
                accepted_all.extend(accepted)
                rejected_all.extend([f"{batch_label}: {reason}" for reason in rejected])
                flagged_all.extend([f"{batch_label}: {reason}" for reason in flagged])
                _stage(f"VALIDATION_COMPLETED {batch_label}")
                attempt["last_completed_stage"] = "VALIDATION_COMPLETED"
                merged, _, _, duplicate_flags = merge_events_detailed(existing, accepted_all)
                flagged_all.extend(duplicate_flags)
                if not validated_written:
                    save_json_new(validated_path, merged)
                    validated_written = True
                else:
                    save_events(validated_path, merged)
                attempt["validated_output_file"] = str(validated_path)
                attempt["last_completed_stage"] = "VALIDATED_OUTPUT_SAVED"
                _stage(f"VALIDATED_OUTPUT_SAVED {batch_label}")
                attempt["batch_results"].append({"batch": batch_index, "candidate_count": len(batch), "status": "success", "request_duration_seconds": duration, "retry_attempts": batch_retry_count, "retry_log": retry_log, "events_returned": len(parsed) if isinstance(parsed, list) else 0, "accepted": len(accepted), "rejected": len(rejected)})
            except StageError as exc:
                duration = exc.duration if exc.duration is not None else round(time.perf_counter() - batch_start, 3)
                retry_log = getattr(exc, "retry_log", [])
                batch_retry_count = getattr(exc, "retry_attempts", 0)
                attempt["retry_log"].extend({"batch": batch_index, **entry} for entry in retry_log)
                attempt["retry_attempts"] += batch_retry_count
                attempt["request_duration_seconds"] = duration
                attempt["http_status_code"] = exc.status_code
                attempt["raw_error_message"] = exc.raw_message
                attempt["failed_stage"] = exc.failed_stage
                attempt["failed_batch"] = batch_index
                attempt["failed_batches"].append(batch_index)
                attempt["batch_results"].append({"batch": batch_index, "candidate_count": len(batch), "status": "failed", "request_duration_seconds": duration, "retry_attempts": batch_retry_count, "retry_log": retry_log, "http_status_code": exc.status_code, "raw_error_message": exc.raw_message, "failed_stage": exc.failed_stage, "error_type": exc.category, "error_message": str(exc)})
                attempt["error_type"] = exc.category
                attempt["error_message"] = str(exc)
                any_batch_failed = True
                disposition = "stopping remaining batches" if exc.status_code == 429 else "continuing to the next batch"
                print(f"Batch {batch_index}/{len(batches)} failed after {batch_retry_count} retries ({exc.category}, HTTP {exc.status_code}): {exc}; {disposition}.", file=sys.stderr, flush=True)
                if exc.status_code == 429:
                    skipped = list(range(batch_index + 1, len(batches) + 1))
                    attempt["quota_limited_batches"] = skipped
                    for skipped_index in skipped:
                        attempt["batch_results"].append({
                            "batch": skipped_index,
                            "candidate_count": len(batches[skipped_index - 1]),
                            "status": "skipped_quota_limit",
                            "retry_attempts": 0,
                        })
                    print(f"HTTP 429 quota response; skipped remaining batches: {skipped}.", file=sys.stderr, flush=True)
                    break
                continue
            except Exception as exc:
                duration = round(time.perf_counter() - batch_start, 3)
                attempt["request_duration_seconds"] = duration
                attempt["failed_stage"] = "parsing" if failure_stage in ("JSON_PARSE_STARTED", "VALIDATION_COMPLETED") else "server_response"
                attempt["failed_batch"] = batch_index
                attempt["batch_results"].append({"batch": batch_index, "candidate_count": len(batch), "status": "failed", "request_duration_seconds": duration, "failed_stage": attempt["failed_stage"], "error_type": type(exc).__name__})
                attempt["failed_batches"].append(batch_index)
                if isinstance(exc, ExtractError):
                    attempt["error_type"] = "validation_error" if failure_stage == "VALIDATION_COMPLETED" else "json_parse_error"
                    attempt["error_message"] = str(exc)
                else:
                    attempt["error_type"] = type(exc).__name__
                    attempt["error_message"] = f"Batch {batch_index} failed ({type(exc).__name__})."
                any_batch_failed = True
                print(f"Batch {batch_index}/{len(batches)} failed ({type(exc).__name__}); continuing to the next batch.", file=sys.stderr, flush=True)
                continue
            attempt["batch_results"][-1]["http_status_code"] = 200

        merged, added, updated, duplicate_flags = merge_events_detailed(existing, accepted_all)
        flagged_all.extend(flag for flag in duplicate_flags if flag not in flagged_all)
        # The cumulative validated artifact already exists, created exclusively above.
        if batches and not validated_written:
            save_json_new(validated_path, merged)
            validated_written = True
        attempt["validated_output_file"] = str(validated_path) if validated_path.exists() else None
        attempt["events_returned"] = returned_count
        attempt["events_accepted"] = len(accepted_all)
        attempt["events_rejected"] = len(rejected_all)
        flagged_all = list(dict.fromkeys(flagged_all))
        flagged_ids: set[str] = set()
        for reason in flagged_all:
            record_match = re.match(r"(batch \d+: event \d+)", reason)
            flagged_ids.add(record_match.group(1) if record_match else reason)
        attempt["events_flagged"] = len(flagged_ids)
        attempt["flagged_finding_count"] = len(flagged_all)
        attempt["rejected_reasons"] = rejected_all
        attempt["flagged_reasons"] = flagged_all
        attempt["final_status"] = "partial_failure" if any_batch_failed else "success"
    except Exception as exc:
        if isinstance(exc, StageError):
            failure_stage = exc.stage
            error_type = exc.category
            message = str(exc)
            attempt["request_duration_seconds"] = exc.duration
            attempt["http_status_code"] = exc.status_code
            attempt["raw_error_message"] = exc.raw_message
            attempt["failed_stage"] = exc.failed_stage
        elif isinstance(exc, json.JSONDecodeError):
            error_type = "json_parse_error"
            message = "Gemini response was not valid JSON."
        elif isinstance(exc, ValidationError):
            error_type = "validation_error"
            message = "Gemini response failed schema validation."
        elif isinstance(exc, ExtractError):
            if failure_stage == "JSON_PARSE_STARTED":
                error_type = "json_parse_error"
            elif failure_stage == "VALIDATION_COMPLETED":
                error_type = "validation_error"
            elif failure_stage in ("PREFLIGHT_PASSED", "PREFLIGHT_STARTED"):
                error_type = "preflight_error"
            else:
                error_type = "api_error"
            message = str(exc)
        elif isinstance(exc, (OSError, UnicodeError)):
            error_type = "file_error"
            message = f"Could not read or save extraction artifact ({type(exc).__name__})."
        else:
            error_type = "internal_error"
            message = f"Unexpected extraction failure ({type(exc).__name__})."
        attempt["error_type"] = error_type
        attempt["error_message"] = message
        attempt["final_status"] = "failed"
        if attempt["failed_stage"] is None:
            attempt["failed_stage"] = "parsing" if failure_stage in ("JSON_PARSE_STARTED", "VALIDATION_COMPLETED") else "server_response"
        try:
            save_json_new(metadata_path, attempt)
        except OSError as metadata_exc:
            print(f"Attempt metadata could not be saved ({type(metadata_exc).__name__}).", file=sys.stderr)
        print(f"Last completed stage: {attempt['last_completed_stage']}\nFailure stage: {failure_stage}\nError ({error_type}): {message}\nExit code: 1", file=sys.stderr)
        return 1

    try:
        save_json_new(metadata_path, attempt)
    except OSError as exc:
        print(f"Last completed stage: {attempt['last_completed_stage']}\nFailure stage: METADATA_SAVED\nError (file_error): Could not save attempt metadata ({type(exc).__name__}).\nExit code: 1", file=sys.stderr)
        return 1

    print(f"Gemini model: {model}")
    print(f"Events returned: {attempt['events_returned']}; accepted: {attempt['events_accepted']}; rejected: {attempt['events_rejected']}; flagged records: {attempt['events_flagged']}.")
    for reason in rejected_all:
        print(f"Rejected {reason}")
    for reason in flagged_all:
        print(f"Flagged {reason}")
    print(f"Added: {added}; updated existing duplicates: {updated}.")
    print(f"Saved {len(merged)} validated event(s) to {validated_path}.")
    print(f"Saved attempt metadata to {metadata_path}.")
    if attempt["failed_batches"]:
        print(f"Completed with failed batch(es): {', '.join(str(i) for i in attempt['failed_batches'])}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
