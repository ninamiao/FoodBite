"""Deterministically parse event cards embedded in a Localist widget response.

Localist's ``/widget/view`` response can be JavaScript which assigns a
JSON-escaped HTML string to a container's ``innerHTML``. This module decodes
that string and parses only ``li.lw_event_item`` cards. It deliberately keeps
displayed dates as source text because these widgets may omit the year or show
multi-day ranges.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


class LocalistParseError(ValueError):
    """Raised when a response does not contain parseable Localist event cards."""


@dataclass(frozen=True)
class LocalistParseResult:
    """Parsed cards plus lightweight diagnostics for automated runs."""

    events: list[dict[str, Any]]
    widget_container_id: str
    card_count: int
    parsed_count: int
    skipped_count: int
    missing_detail_url_count: int
    result_limit: int | None
    possible_truncation: bool
    warnings: tuple[str, ...]


# The regex captures the target container ID and the complete escaped string literal.
# It safely demands an explicit semicolon or the absolute end of input to terminate.
_INNER_HTML_ASSIGNMENT_RE = re.compile(
    r"(?:document\.)?getElementById\(\s*(?P<container>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')\s*\)"
    r"\s*\.innerHTML\s*=\s*(?P<html>\"(?:\\.|[^\"\\])*\")\s*(?:;|$)",
    re.DOTALL,
)

_GROUP_SELECTORS = (
    ".lw_event_item_group",
    ".lw_event_group",
    "[data-group-name]",
)
_ORGANIZER_SELECTORS = (
    ".lw_event_item_organization",
    ".lw_organization_name",
    "[itemprop='organizer']",
    "[data-organization]",
)


def _text(element: Tag | None) -> str | None:
    if element is None:
        return None
    value = " ".join(element.get_text(" ", strip=True).split())
    return value or None


def _date_text(element: Tag | None) -> str | None:
    if element is None:
        return None
    date_element = copy.deepcopy(element)
    for time_element in date_element.select(".lw_event_item_time"):
        time_element.decompose()
    return _text(date_element)


def _location_text(element: Tag | None) -> str | None:
    value = _text(element)
    if value is None:
        return None
    value = re.sub(r"^Location\s*:\s*", "", value, flags=re.IGNORECASE).strip()
    return value or None


def _explicit_value(card: Tag, selectors: tuple[str, ...]) -> str | None:
    """Read only explicitly marked group/organizer fields inside this card."""
    for selector in selectors:
        element = card.select_one(selector)
        if element is None:
            continue
        value = (
            element.get("data-group-name")
            or element.get("data-organization")
            or _text(element)
        )
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _normalize_detail_url(detail_url: str | None, widget_source_url: str) -> str | None:
    """Resolve a link and remove tracking parameters, keeping other URL parts."""
    if not detail_url:
        return None
    parts = urlsplit(urljoin(widget_source_url, detail_url))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _parse_card(card: Tag, widget_source_url: str) -> dict[str, Any]:
    title_link = card.select_one(".lw_event_item_title a")
    date_element = card.select_one(".lw_event_item_date")
    time_element = card.select_one(".lw_event_item_time")
    location_element = card.select_one(".lw_event_item_location")
    detail_url = title_link.get("href") if title_link else None
    if not isinstance(detail_url, str):
        detail_url = None

    return {
        "title": _text(title_link),
        "date_text": _date_text(date_element),
        "time_text": _text(time_element),
        "date_time_text": _text(date_element),
        "location": _location_text(location_element),
        "location_text": _text(location_element),
        "description": _text(card.select_one(".lw_event_item_description")),
        "detail_url": detail_url,
        "normalized_detail_url": _normalize_detail_url(detail_url, widget_source_url),
        "widget_source_url": widget_source_url,
        # Never infer an event's organizer from the widget's group filters,
        # its location, or words in the title/description.
        "group": _explicit_value(card, _GROUP_SELECTORS),
        "organizer": _explicit_value(card, _ORGANIZER_SELECTORS),
    }


def _decode_container_id(value: str) -> str:
    if value.startswith('"'):
        decoded = json.loads(value)
    else:
        # Widget IDs are plain strings; support ordinary escaped quote and
        # backslash forms for single-quoted JavaScript literals as well.
        decoded = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    if not isinstance(decoded, str):
        raise LocalistParseError("The innerHTML assignment has an invalid container ID.")
    return decoded


def _result_limit(widget_source_url: str, explicit_limit: int | None) -> int | None:
    if explicit_limit is not None:
        return explicit_limit if explicit_limit > 0 else None
    try:
        raw_limit = parse_qs(urlsplit(widget_source_url).query).get("num", [None])[0]
        parsed_limit = int(raw_limit) if raw_limit is not None else None
    except (TypeError, ValueError):
        return None
    return parsed_limit if parsed_limit and parsed_limit > 0 else None


def parse_localist_widget_response_detailed(
    response_text: str,
    widget_source_url: str,
    *,
    container_id: str | None = None,
    result_limit: int | None = None,
) -> LocalistParseResult:
    """Parse one widget assignment and return card counts and warnings.

    A target ``container_id`` selects exactly that widget. Without one, a
    response must contain exactly one widget assignment. No event-title
    deduplication, date/year inference, text repair, or group inference occurs.
    """
    matches = [
        (_decode_container_id(match.group("container")), match.group("html"))
        for match in _INNER_HTML_ASSIGNMENT_RE.finditer(response_text)
    ]
    if not matches:
        raise LocalistParseError("No JSON-escaped innerHTML assignment was found in the Localist response.")

    if container_id is not None:
        selected = [(widget_id, value) for widget_id, value in matches if widget_id == container_id]
        if not selected:
            raise LocalistParseError(f"No innerHTML assignment was found for widget container {container_id!r}.")
        if len(selected) != 1:
            raise LocalistParseError(
                f"Found {len(selected)} innerHTML assignments for widget container {container_id!r}; refusing to combine them."
            )
    else:
        widget_ids = {widget_id for widget_id, _ in matches}
        if len(widget_ids) != 1:
            choices = ", ".join(sorted(widget_ids))
            raise LocalistParseError(
                f"Found multiple widget containers ({choices}); pass container_id to select one."
            )
        if len(matches) != 1:
            raise LocalistParseError(
                f"Found multiple innerHTML assignments for widget container {next(iter(widget_ids))!r}; refusing to combine them."
            )
        selected = matches

    selected_id, encoded_html = selected[0]
    try:
        embedded_html = json.loads(encoded_html)
    except json.JSONDecodeError as exc:
        raise LocalistParseError("Could not decode the selected innerHTML assignment as a JSON string.") from exc
    if not isinstance(embedded_html, str):
        raise LocalistParseError("The selected innerHTML assignment did not decode to text.")

    soup = BeautifulSoup(embedded_html, "html.parser")
    list_containers = soup.select("ul.lw_event_list")
    if not list_containers:
        raise LocalistParseError("The selected widget innerHTML contains no ul.lw_event_list container.")
    cards = [card for container in list_containers for card in container.select("li.lw_event_item")]
    if not cards:
        raise LocalistParseError("Found ul.lw_event_list, but it contained no li.lw_event_item event cards.")

    events: list[dict[str, Any]] = []
    skipped_count = 0
    missing_detail_url_count = 0
    for card in cards:
        event = _parse_card(card, widget_source_url)
        if not event["title"] or not event["title"].strip():
            skipped_count += 1
            continue
        if not event["detail_url"]:
            missing_detail_url_count += 1
        events.append(event)

    limit = _result_limit(widget_source_url, result_limit)
    possible_truncation = limit is not None and len(cards) >= limit
    warnings: list[str] = []
    if skipped_count:
        warnings.append(f"Skipped {skipped_count} card(s) with a missing or blank title.")
    if missing_detail_url_count:
        warnings.append(f"{missing_detail_url_count} parsed card(s) have no detail URL.")
    if possible_truncation:
        warnings.append(
            f"Found {len(cards)} cards, reaching the configured result limit of {limit}; results may be truncated."
        )

    return LocalistParseResult(
        events=events,
        widget_container_id=selected_id,
        card_count=len(cards),
        parsed_count=len(events),
        skipped_count=skipped_count,
        missing_detail_url_count=missing_detail_url_count,
        result_limit=limit,
        possible_truncation=possible_truncation,
        warnings=tuple(warnings),
    )


def parse_localist_widget_response(
    response_text: str,
    widget_source_url: str,
    container_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility list interface; use the detailed variant for diagnostics."""
    return parse_localist_widget_response_detailed(
        response_text,
        widget_source_url,
        container_id=container_id,
    ).events
