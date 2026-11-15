"""Build a human-review candidate dataset from a validated extraction run."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curated_data import (
    duplicate_key,
    food_relevance_reason,
    normalize_eligibility,
    stable_event_id,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def plain_url(value: str | None) -> str:
    """Normalize a Markdown URL to its underlying URL."""
    if not isinstance(value, str):
        return ""
    match = re.fullmatch(r"\[.*?\]\((.*?)\)", value.strip())
    return (match.group(1) if match else value).strip().casefold()


def completeness_score(event: dict[str, Any]) -> int:
    """Prefer records with complete details and stronger food evidence."""
    score = 0

    for key in ("title", "date", "start_time", "end_time",
                "location", "address", "food_description"):
        if event.get(key):
            score += 2

    evidence = event.get("evidence") or {}
    for key in ("provides_food", "is_free", "food_description"):
        if evidence.get(key):
            score += 2

    status_scores = {
        "confirmed_free": 6,
        "provided_cost_unknown": 5,
        "food_unconfirmed": 2,
        "not_provided": 0,
    }
    score += status_scores.get(event.get("food_status"), 0)
    return score



def merge_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge complementary fields while preserving conflicts for review."""
    if not records:
        raise ValueError("Cannot merge an empty record group.")

    ranked = sorted(
        records,
        key=completeness_score,
        reverse=True,
    )

    merged = dict(ranked[0])

    # Fill missing ordinary fields from less complete variants.
    for record in ranked[1:]:
        for key, value in record.items():
            if key in {
                "evidence",
                "extraction_evidence",
                "review_warnings",
                "source_records",
                "food_status",
            }:
                continue

            if merged.get(key) in (None, "", [], {}):
                if value not in (None, "", [], {}):
                    merged[key] = value

    warnings = []
    for record in records:
        for warning in record.get("review_warnings") or []:
            if warning not in warnings:
                warnings.append(warning)

    # Preserve evidence from every variant for human review.
    evidence_variants = []
    for record in records:
        evidence = record.get("evidence")
        if evidence and evidence not in evidence_variants:
            evidence_variants.append(evidence)

    extraction_variants = []
    for record in records:
        evidence = record.get("extraction_evidence")
        if evidence and evidence not in extraction_variants:
            extraction_variants.append(evidence)

    if len(evidence_variants) > 1:
        warnings.append(
            "Duplicate records contain different evidence; manual review required."
        )

    if len(extraction_variants) > 1:
        warnings.append(
            "Duplicate records contain different extraction evidence; manual review required."
        )

    merged["evidence_variants"] = evidence_variants
    merged["extraction_evidence_variants"] = extraction_variants
    merged["review_warnings"] = warnings

    source_records = []
    for record in records:
        for source_record in record.get("source_records") or []:
            if source_record not in source_records:
                source_records.append(source_record)

    if source_records:
        merged["source_records"] = source_records

    merged["duplicate_variants_count"] = len(records)
    merged["eligibility"] = normalize_eligibility(
        merged.get("eligibility")
    )

    if not merged.get("id"):
        merged["id"] = stable_event_id(merged)

    return merged



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validated", required=True, type=Path)
    parser.add_argument("--published", default=Path("data/events.json"), type=Path)
    parser.add_argument(
        "--exclusions",
        default=Path("data/event_curation_exclusions.json"),
        type=Path,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    validated_data = read_json(args.validated)
    events = (
        validated_data
        if isinstance(validated_data, list)
        else validated_data.get("events", [])
    )

    published_data = read_json(args.published)
    published_events = published_data.get("events", [])

    exclusions_data = read_json(args.exclusions)
    excluded_events = exclusions_data.get("excluded_events", [])

    # Group repeated extraction records using the existing canonical rule.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for event in events:
        key = duplicate_key(event)
        groups.setdefault(key, []).append(event)

    # Build lookup sets for existing published and excluded events.
    published_keys = {duplicate_key(event) for event in published_events}
    excluded_ids = {
        event.get("id")
        for event in excluded_events
        if event.get("id")
    }
    excluded_urls = {
        plain_url(event.get("event_url"))
        for event in excluded_events
        if event.get("event_url")
    }

    candidates = []
    excluded = []

    for records in groups.values():
        event = merge_group(records)
        reason = food_relevance_reason(event)

        if reason is None:
            excluded.append({
                "event": event,
                "reason": "No source-supported food relevance found.",
            })
            continue

        event_url = plain_url(event.get("event_url"))

        event["candidate_reason"] = reason
        event["already_published"] = duplicate_key(event) in published_keys
        event["previously_excluded"] = (
            event.get("id") in excluded_ids
            or event_url in excluded_urls
        )

        candidates.append(event)

    candidates.sort(
        key=lambda event: (
            event.get("date") or "9999-99-99",
            event.get("start_time") or "99:99",
            event.get("title") or "",
        )
    )

    output = {
        "schema_version": "1.0",
        "source_run": args.validated.parent.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(args.validated),
        "published_dataset": str(args.published),
        "counts": {
            "validated_records": len(events),
            "unique_events": len(groups),
            "candidate_count": len(candidates),
            "already_published_count": sum(
                event["already_published"] for event in candidates
            ),
            "previously_excluded_count": sum(
                event["previously_excluded"] for event in candidates
            ),
            "excluded_non_food_count": len(excluded),
        },
        "candidates": candidates,
        "excluded": excluded,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(output["counts"], indent=2))
    print(f"\nCandidate file written to: {args.output}")


if __name__ == "__main__":
    main()
