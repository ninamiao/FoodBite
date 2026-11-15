"""Local, network-free checks for evidence validation and source preprocessing."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch

from scraper.extract import (
    EVENT_FIELDS,
    EVIDENCE_FIELDS,
    ExtractError,
    StageError,
    DEFAULT_MODEL,
    MODEL_ENV,
    call_gemini,
    chunk_candidates,
    get_model_name,
    load_existing_events,
    main,
    merge_events,
    preprocess_html,
    read_json_response,
    validate_events,
)

ROOT = Path(__file__).resolve().parent.parent


def event_sample(source: str) -> dict:
    evidence = {key: None for key in EVIDENCE_FIELDS}
    evidence.update(
        {
            "title": "Free Food Distribution",
            "date": "2026-11-20",
            "time": "12:00 PM - 2:30 PM",
            "location": "Basic Needs Center at Malk Hall",
            "provides_food": "Free Food Distribution",
            "is_free": "Free Food Distribution",
            "food_description": "shelf stable items and seasonal produce",
            "eligibility": "students, staff, faculty, and San Diego community members",
        }
    )
    event = {
        "title": "Free Food Distribution",
        "description": "Monthly free food distribution with seasonal produce.",
        "date": "2026-11-20",
        "start_time": "12:00",
        "end_time": "14:30",
        "location": "Basic Needs Center at Malk Hall",
        "address": None,
        "provides_food": True,
        "is_free": True,
        "food_description": "shelf stable items and seasonal produce",
        "eligibility": "students, staff, faculty, and San Diego community members",
        "registration_url": None,
        "event_url": "https://calendar.ucsd.edu/event/free-food-distribution",
        "source_url": "https://calendar.ucsd.edu/student-life",
        "evidence": evidence,
    }
    assert set(event) == set(EVENT_FIELDS)
    return event


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            "Free Food Distribution on 2026-11-20 from 12:00 PM - 2:30 PM "
            "at the Basic Needs Center at Malk Hall. Free Food Distribution. "
            "The Hub provides Free Food Distribution with shelf stable items and seasonal produce to students, "
            "staff, faculty, and San Diego community members. "
            "https://calendar.ucsd.edu/event/free-food-distribution"
        )
        self.source_url = "https://calendar.ucsd.edu/student-life"

    def test_valid_complete_event_is_accepted(self):
        response = read_json_response(json.dumps([event_sample(self.source)]))
        accepted, rejected, flagged = validate_events(response, self.source, self.source_url)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])
        self.assertIs(accepted[0]["is_free"], True)
        self.assertTrue(any("unsupported_field" in item for item in flagged))

    def test_missing_date_is_accepted_as_null(self):
        sample = event_sample(self.source)
        sample["date"] = None
        sample["evidence"]["date"] = None
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), self.source, self.source_url)
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0]["date"])
        self.assertEqual(rejected, [])

    def test_free_claim_is_kept_only_with_food_specific_source_evidence(self):
        source = self.source.replace("Free Food Distribution. ", "Food distribution. ")
        sample = event_sample(source)
        sample["evidence"]["is_free"] = "Food distribution"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), source, self.source_url)
        self.assertEqual(len(accepted), 1)
        self.assertIs(accepted[0]["is_free"], True)
        self.assertIn("Free Food Distribution", accepted[0]["evidence"]["is_free"])
        self.assertEqual(rejected, [])

    def test_invalid_date_is_rejected(self):
        sample = event_sample(self.source)
        sample["date"] = "2026-02-30"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), self.source, self.source_url)
        self.assertEqual(accepted, [])
        self.assertIn("date_format", rejected[0])

    def test_invalid_time_is_rejected(self):
        sample = event_sample(self.source)
        sample["start_time"] = "25:00"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), self.source, self.source_url)
        self.assertEqual(accepted, [])
        self.assertIn("time_format", rejected[0])

    def test_title_not_in_source_is_rejected(self):
        sample = event_sample(self.source)
        sample["title"] = "Invented Campus Lunch"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), self.source, self.source_url)
        self.assertEqual(accepted, [])
        self.assertIn("title", rejected[0])

    def test_free_event_does_not_imply_food_is_provided(self):
        source = "Campus Open House. This is a free event."
        sample = event_sample(self.source)
        sample.update({
            "title": "Campus Open House",
            "description": None,
            "date": None,
            "start_time": None,
            "end_time": None,
            "location": None,
            "address": None,
            "provides_food": None,
            "is_free": True,
            "food_description": None,
            "eligibility": None,
            "registration_url": None,
            "event_url": None,
            "evidence": {key: None for key in EVIDENCE_FIELDS},
        })
        sample["evidence"]["title"] = "Campus Open House"
        sample["evidence"]["is_free"] = "free event"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), source, self.source_url)
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0]["provides_food"])
        self.assertIsNone(accepted[0]["is_free"])

    def test_free_event_with_available_food_does_not_make_food_free(self):
        source = "Campus Open House is a free event. Snacks will be available."
        sample = event_sample(self.source)
        sample.update({
            "title": "Campus Open House", "description": source, "date": None,
            "start_time": None, "end_time": None, "location": None, "address": None,
            "provides_food": True, "is_free": True, "food_description": "Snacks",
            "eligibility": None, "registration_url": None, "event_url": None,
            "evidence": {key: None for key in EVIDENCE_FIELDS},
        })
        sample["evidence"].update({
            "title": "Campus Open House", "provides_food": "Snacks will be available",
            "is_free": "Campus Open House is a free event", "food_description": "Snacks",
        })
        accepted, rejected, _ = validate_events(read_json_response(json.dumps([sample])), source, self.source_url)
        self.assertEqual(rejected, [])
        self.assertIs(accepted[0]["provides_food"], True)
        self.assertIsNone(accepted[0]["is_free"])

    def test_lunchbox_mention_does_not_support_food_provision(self):
        source = (
            "Welcome to UC San Diego | Exhibit. This exhibit showcases the Chancellor's Lunchbox Club."
        )
        sample = event_sample(self.source)
        sample.update({
            "title": "Welcome to UC San Diego | Exhibit",
            "description": source,
            "date": None,
            "start_time": None,
            "end_time": None,
            "location": None,
            "address": None,
            "provides_food": True,
            "is_free": None,
            "food_description": None,
            "eligibility": None,
            "registration_url": None,
            "event_url": None,
            "evidence": {key: None for key in EVIDENCE_FIELDS},
        })
        sample["evidence"]["title"] = "Welcome to UC San Diego | Exhibit"
        sample["evidence"]["provides_food"] = "Chancellor's Lunchbox Club"
        accepted, rejected, flagged = validate_events(read_json_response(json.dumps([sample])), source, self.source_url)
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0]["provides_food"])
        self.assertIsNone(accepted[0]["evidence"]["provides_food"])

    def test_hh_mm_ss_normalizes_without_guessing(self):
        sample = event_sample(self.source)
        sample["start_time"] = "12:00:00"
        accepted, rejected, flagged = validate_events(
            read_json_response(json.dumps([sample])), self.source, self.source_url
        )
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["start_time"], "12:00")
        self.assertTrue(any("time_normalized" in item for item in flagged))

    def test_conflicting_date_evidence_is_nulled_and_flagged(self):
        sample = event_sample(self.source)
        sample["date"] = "2026-11-14"
        sample["evidence"]["date"] = "2026-11-20"
        accepted, rejected, flagged = validate_events(
            read_json_response(json.dumps([sample])), self.source, self.source_url
        )
        self.assertEqual(rejected, [])
        self.assertIsNone(accepted[0]["date"])
        self.assertTrue(any("date_conflict" in item for item in flagged))

    def _date_case(self, title, start, end, date_value, date_evidence, description=""):
        text = f"Title: {title}\nDescription: {description}\nStart: {start}\nEnd: {end}\nEvent URL: https://example.test/{title.replace(' ', '-').lower()}"
        record = {"title": title, "text": text, "event_url": f"https://example.test/{title.replace(' ', '-').lower()}"}
        sample = event_sample(text)
        sample.update({
            "title": title, "description": None, "date": date_value,
            "start_time": None, "end_time": None, "location": None, "address": None,
            "provides_food": None, "is_free": None, "food_description": None,
            "eligibility": None, "registration_url": None,
            "event_url": record["event_url"],
            "evidence": {key: None for key in EVIDENCE_FIELDS},
        })
        sample["evidence"].update({"title": title, "date": date_evidence})
        return sample, record

    def test_single_day_start_and_end_preserve_valid_event_date(self):
        sample, record = self._date_case(
            "Single Day Workshop", "2026-05-01T10:00:00-07:00", "2026-05-01T11:00:00-07:00",
            "2026-05-01", "Start: 2026-05-01T10:00:00-07:00",
        )
        accepted, rejected, _ = validate_events([sample], record["text"], self.source_url, [record])
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["date"], "2026-05-01")

    def test_multi_day_display_does_not_accept_end_as_single_event_date(self):
        sample, record = self._date_case(
            "Library Exhibit", "2026-05-01", "2026-05-03", "2026-05-03",
            "End: 2026-05-03", "On view May 1 through May 3, 2026.",
        )
        accepted, rejected, flagged = validate_events([sample], record["text"], self.source_url, [record])
        self.assertEqual(rejected, [])
        self.assertIsNone(accepted[0]["date"])
        self.assertTrue(any("ongoing_display" in item for item in flagged))

    def test_multiple_events_match_independently_without_source_records(self):
        source = "First Campus Event\nSecond Campus Event"

        def fallback_event(title):
            sample = event_sample(source)
            sample.update({key: None for key in EVENT_FIELDS if key not in ("title", "source_url", "evidence")})
            sample["title"] = title
            sample["source_url"] = self.source_url
            sample["evidence"] = {key: None for key in EVIDENCE_FIELDS}
            sample["evidence"]["title"] = title
            return sample

        accepted, rejected, _ = validate_events(
            [fallback_event("First Campus Event"), fallback_event("Second Campus Event")],
            source,
            self.source_url,
        )
        self.assertEqual(rejected, [])
        self.assertEqual([event["title"] for event in accepted], ["First Campus Event", "Second Campus Event"])

    def test_food_provision_phrases_require_explicit_serving_or_availability(self):
        from scraper.extract import _find_food_provision_evidence

        for phrase in ("Enjoy a cup of cocoa.", "Pizza will be handed out.", "Grab refreshments."):
            with self.subTest(phrase=phrase):
                self.assertEqual(_find_food_provision_evidence(phrase), phrase)
        for phrase in ("A cup of cocoa is mentioned in the talk.", "The discussion covers pizza."):
            with self.subTest(phrase=phrase):
                self.assertIsNone(_find_food_provision_evidence(phrase))

    def test_local_source_food_and_date_regressions(self):
        html_path = ROOT / "data" / "calendar_ucsd_edu_student-life.html"
        prepared = preprocess_html(html_path.read_text(encoding="utf-8"), self.source_url)
        records = prepared["candidates"]

        def candidate_event(record, *, date_value=None, date_evidence=None, provides=None, free=None):
            evidence = {key: None for key in EVIDENCE_FIELDS}
            evidence["title"] = record["title"]
            evidence["date"] = date_evidence
            event = {key: None for key in EVENT_FIELDS if key != "evidence"}
            event.update({
                "title": record["title"], "date": date_value,
                "provides_food": provides, "is_free": free,
                "source_url": self.source_url, "event_url": record["event_url"],
                "evidence": evidence,
            })
            return event

        distributions = [r for r in records if r["title"] == "Free Food Distribution"]
        self.assertEqual(len(distributions), 2)
        for record in distributions:
            date_evidence = re.search(r"^Start: ([^\n]+)", record["text"], re.M).group(1)
            sample = candidate_event(record, date_value=date_evidence[:10],
                                     date_evidence=f"Start: {date_evidence}", provides=None, free=None)
            accepted, rejected, flagged = validate_events([sample], record["text"], self.source_url, [record])
            self.assertEqual(rejected, [])
            self.assertEqual(len(accepted), 1)
            self.assertIs(accepted[0]["provides_food"], True)
            self.assertIs(accepted[0]["is_free"], True)
            self.assertTrue(accepted[0]["evidence"]["provides_food"])
            self.assertTrue(accepted[0]["evidence"]["is_free"])

        world_aids = next(r for r in records if "World AIDS Day" in r["title"])
        sample = candidate_event(world_aids, provides=None, free=None)
        accepted, rejected, _ = validate_events([sample], world_aids["text"], self.source_url, [world_aids])
        self.assertEqual(rejected, [])
        self.assertIs(accepted[0]["provides_food"], True)
        self.assertIs(accepted[0]["is_free"], True)
        self.assertIn("free boba", accepted[0]["evidence"]["is_free"].casefold())

        destress = next(r for r in records if "Destress with CLS" in r["title"])
        sample = candidate_event(destress, provides=None, free=None)
        accepted, rejected, _ = validate_events([sample], destress["text"], self.source_url, [destress])
        self.assertEqual(rejected, [])
        self.assertIs(accepted[0]["provides_food"], True)
        self.assertIsNone(accepted[0]["is_free"])

        welcome = next(r for r in records if "Welcome to UC San Diego" in r["title"])
        sample = candidate_event(welcome, date_value="2026-11-14", date_evidence="Start: 2026-11-14",
                                 provides=True, free=True)
        accepted, rejected, flagged = validate_events([sample], welcome["text"], self.source_url, [welcome])
        self.assertEqual(rejected, [])
        self.assertIsNone(accepted[0]["provides_food"])
        self.assertIsNone(accepted[0]["is_free"])
        self.assertIsNone(accepted[0]["date"])
        self.assertTrue(any("ongoing_display" in item for item in flagged))

    def test_request_timeout_is_configured_and_reported_without_api(self):
        class ReadTimeout(Exception):
            pass

        continuation_values = []

        class FakeModels:
            def generate_content(self, **kwargs):
                continuation_values.append(kwargs["config"].automatic_continuation)
                raise ReadTimeout()

        configured_options = []

        class FakeClient:
            def __init__(self, api_key, http_options):
                self.models = FakeModels()
                configured_options.append((http_options.timeout, http_options.retry_options.attempts))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        import sys
        from types import ModuleType, SimpleNamespace
        fake_genai = ModuleType("google.genai")
        fake_genai.Client = FakeClient
        fake_genai.types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        with patch.dict(sys.modules, {"google.genai": fake_genai}):
            with self.assertRaisesRegex(ExtractError, "timed out after 60 seconds"):
                call_gemini("test-key-not-used", DEFAULT_MODEL, "local timeout test")
        self.assertEqual(configured_options, [(60_000, 1)])
        self.assertEqual(continuation_values, [False])

    def test_model_defaults_to_current_stable_identifier(self):
        with patch.dict("os.environ", {MODEL_ENV: ""}):
            with patch("scraper.extract.load_dotenv"):
                self.assertEqual(get_model_name(), DEFAULT_MODEL)


class PreprocessingTests(unittest.TestCase):
    def test_saved_ucsd_html_preprocesses_event_jsonld(self):
        html_path = ROOT / "data" / "calendar_ucsd_edu_student-life.html"
        prepared = preprocess_html(html_path.read_text(encoding="utf-8"), "https://calendar.ucsd.edu/student-life")
        titles = [candidate["title"] for candidate in prepared["candidates"]]
        self.assertEqual(prepared["jsonld_event_count"], 67)
        self.assertEqual(prepared["candidate_count"], len(titles))
        self.assertEqual(prepared["candidate_count"], 61)
        self.assertEqual(sum(title == "Free Food Distribution" for title in titles), 2)
        self.assertTrue(any("World AIDS Day" in title for title in titles))
        self.assertTrue(any("Destress with CLS" in title for title in titles))
        self.assertIn("Free Food Distribution", prepared["text"])
        self.assertIn("shelf stable items", prepared["text"])
        self.assertLess(len(prepared["text"]), html_path.stat().st_size)
        self.assertNotIn("Cookie Consent", prepared["text"])

        welcome = next(candidate for candidate in prepared["candidates"] if "Welcome to UC San Diego" in candidate["title"])
        self.assertNotIn("provides_food", welcome)
        self.assertNotIn("provides_food", welcome["text"])

    def test_muir_jsonld_candidate_keeps_listing_and_event_source_urls(self):
        source_url = "https://muir.ucsd.edu/studentlife/calendarofevents.html"
        html = """<html><head><title>Muir Calendar</title></head><body>
        <script type="application/ld+json">{
          "@type":"Event","name":"Muir Community Dinner",
          "description":"Dinner will be served to attendees.",
          "startDate":"2026-11-20T18:00:00-08:00",
          "url":"https://muir.ucsd.edu/event/community-dinner"
        }</script></body></html>"""
        prepared = preprocess_html(html, source_url)
        self.assertEqual(prepared["source_url"], source_url)
        self.assertEqual(prepared["candidate_count"], 1)
        self.assertEqual(prepared["candidates"][0]["title"], "Muir Community Dinner")
        self.assertIn("https://muir.ucsd.edu/event/community-dinner", prepared["candidates"][0]["text"])

    def test_merge_base_loader_accepts_array_and_canonical_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(load_existing_events(path), ([], "array"))
            existing = event_sample("source")
            canonical = {"schema_version": "1.2", "reviewed_at": "2026-11-14", "events": [existing]}
            path.write_text(json.dumps(canonical), encoding="utf-8")
            loaded, source_format = load_existing_events(path)
            self.assertEqual(source_format, "canonical_object")
            self.assertEqual(loaded, [existing])
            path.write_text('{"schema_version":"1.2","events":[]}', encoding="utf-8")
            self.assertEqual(load_existing_events(path), ([], "canonical_object"))
            path.write_text('{"schema_version":"1.2"}', encoding="utf-8")
            with self.assertRaisesRegex(ExtractError, "events array"):
                load_existing_events(path)

    def test_merge_preserves_more_complete_existing_duplicate(self):
        current = event_sample("source")
        less_complete = dict(current)
        less_complete["description"] = None
        merged, added, updated = merge_events([current], [less_complete])
        self.assertEqual(len(merged), 1)
        self.assertEqual(added, 0)
        self.assertEqual(updated, 1)
        self.assertEqual(merged[0]["description"], current["description"])
        self.assertTrue(any(record.get("description") is None for record in merged[0]["source_records"]))

    def test_same_date_duplicates_are_removed_but_recurring_dates_remain(self):
        first = event_sample("source")
        minor_variant = dict(first)
        minor_variant["title"] = "Free Food Distribution!"
        second_occurrence = dict(first)
        second_occurrence["date"] = "2026-12-11"
        merged, added, updated = merge_events([first], [minor_variant, second_occurrence])
        self.assertEqual(len(merged), 2)
        self.assertEqual(added, 1)
        self.assertEqual(updated, 1)

    def test_conflicting_confirmed_duplicate_is_one_record_with_both_source_evidence(self):
        from scraper.extract import merge_events_detailed
        first = event_sample("source")
        first["id"] = "event-established-id"
        conflict = dict(first)
        conflict["is_free"] = False
        merged, added, updated, flags = merge_events_detailed([first], [conflict])
        self.assertEqual(len(merged), 1)
        self.assertEqual(added, 0)
        self.assertEqual(updated, 1)
        self.assertTrue(any("duplicate_conflict" in item and "is_free" in item for item in flags))
        self.assertEqual(merged[0]["id"], "event-established-id")
        self.assertEqual(merged[0]["is_free"], True)
        self.assertEqual({record["is_free"] for record in merged[0]["source_records"]}, {True, False})
        self.assertTrue(any("is_free" in warning for warning in merged[0]["review_warnings"]))

    def test_cross_source_duplicate_merges_and_preserves_both_source_urls(self):
        from scraper.extract import merge_events_detailed
        first = event_sample("source one")
        first.update({"id": "event-stable", "source_url": "https://calendar.ucsd.edu/student-life",
                      "event_url": "https://calendar.ucsd.edu/event/community-dinner"})
        second = dict(first)
        second.update({"source_url": "https://muir.ucsd.edu/studentlife/calendarofevents.html",
                       "event_url": "https://muir.ucsd.edu/event/community-dinner"})
        second["evidence"] = dict(first["evidence"], provides_food="Dinner will be served to attendees")
        second["description"] = "Muir's listing gives a longer dinner description."
        merged, added, updated, flags = merge_events_detailed([first], [second])
        self.assertEqual((len(merged), added), (1, 0))
        self.assertEqual(updated, 1)
        self.assertEqual(merged[0]["id"], "event-stable")
        self.assertEqual(merged[0]["source_url"], first["source_url"])
        self.assertEqual(set(merged[0]["source_urls"]), {first["source_url"], second["source_url"]})
        self.assertEqual({record["event_url"] for record in merged[0]["source_records"]},
                         {first["event_url"], second["event_url"]})
        self.assertTrue(any(record["evidence"]["provides_food"] == "Dinner will be served to attendees"
                            for record in merged[0]["source_records"]))
        self.assertTrue(any("description" in flag for flag in flags))

    def test_possible_duplicate_is_flagged_but_not_merged(self):
        from scraper.extract import merge_events_detailed
        first = event_sample("source one")
        first["event_url"] = "https://calendar.ucsd.edu/event/community-dinner"
        second = dict(first)
        second.update({"source_url": "https://muir.ucsd.edu/studentlife/calendarofevents.html",
                       "event_url": "https://muir.ucsd.edu/event/community-dinner",
                       "location": "Different venue"})
        merged, added, _, flags = merge_events_detailed([first], [second])
        self.assertEqual((len(merged), added), (2, 1))
        self.assertTrue(any("possible_duplicate_review" in flag for flag in flags))
        self.assertTrue(all(any("possible_duplicate_review" in warning for warning in event["review_warnings"])
                            for event in merged))

    def test_same_title_date_and_venue_with_conflicting_time_is_not_auto_merged(self):
        from scraper.extract import merge_events_detailed
        first = event_sample("source one")
        second = dict(first, event_url="https://muir.ucsd.edu/event/community-dinner", end_time="15:00")
        merged, added, _, flags = merge_events_detailed([first], [second])
        self.assertEqual((len(merged), added), (2, 1))
        self.assertTrue(any("possible_duplicate_review" in flag for flag in flags))

    def test_same_title_recurring_event_on_different_date_is_not_flagged_or_merged(self):
        from scraper.extract import merge_events_detailed
        first = event_sample("source one")
        second = dict(first, date="2026-12-11", event_url="https://muir.ucsd.edu/event/community-dinner")
        merged, added, updated, flags = merge_events_detailed([first], [second])
        self.assertEqual((len(merged), added, updated), (2, 1, 0))
        self.assertEqual(flags, [])
        self.assertEqual({event["date"] for event in merged}, {"2026-11-20", "2026-12-11"})

    def test_new_extraction_records_receive_deterministic_ids_and_food_status(self):
        first = event_sample("source")
        first.pop("id", None)
        merged_a, _, _ = merge_events([], [first])
        merged_b, _, _ = merge_events([], [first])
        self.assertEqual(merged_a[0]["id"], merged_b[0]["id"])
        self.assertEqual(merged_a[0]["food_status"], "confirmed_free")
        self.assertEqual(merged_a[0]["original_title"], first["title"])
        self.assertEqual(merged_a[0]["extraction_evidence"], first["evidence"])

    def test_same_title_alone_does_not_collapse_distinct_events(self):
        first = event_sample("source")
        first["location"] = None
        first["event_url"] = "https://example.test/event/a"
        second = dict(first)
        second["event_url"] = "https://example.test/event/b"
        merged, added, updated = merge_events([first], [second])
        self.assertEqual(len(merged), 2)
        self.assertEqual(added, 1)
        self.assertEqual(updated, 0)

    def test_quota_429_stops_remaining_batches(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.html_path = root / "input.html"
        self.run_dir = root / "runs"
        self.events_path = root / "events.json"
        self.events_path.write_text("[]\n", encoding="utf-8")
        html = "<html><body>" + "".join(
            '<script type="application/ld+json">' + json.dumps({
                "@type": "Event", "name": f"Quota Event {index}",
                "description": f"Local source text {index}",
                "url": f"https://example.test/event/{index}",
            }) + "</script>" for index in range(11)
        ) + "</body></html>"
        self.html_path.write_text(html, encoding="utf-8")
        calls = []

        def quota_error(*args):
            calls.append(1)
            raise StageError("API_REQUEST_STARTED", "api_error", "quota", status_code=429,
                             duration=0.2, raw_message="rate limit", failed_stage="server_response")

        args = [str(self.html_path), "--source-url", "https://example.test/list", "--confirm-api",
                "--run-dir", str(self.run_dir), "--output", str(self.events_path), "--batch-size", "10"]
        with patch("scraper.extract._unique_run_stem", return_value="quota-attempt"), \
             patch("scraper.extract.load_api_key", return_value="local-test-key"), \
             patch("scraper.extract.get_model_name", return_value=DEFAULT_MODEL), \
             patch("scraper.extract.call_gemini", side_effect=quota_error), \
             patch("scraper.extract.time.sleep"), \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            status = main(args)
        metadata = json.loads((self.run_dir / "quota-attempt_metadata.json").read_text())
        self.assertEqual(status, 1)
        self.assertEqual(calls, [1])
        self.assertEqual(metadata["failed_batches"], [1])
        self.assertEqual(metadata["quota_limited_batches"], [2])
        self.assertEqual([batch["status"] for batch in metadata["batch_results"]],
                         ["failed", "skipped_quota_limit"])

    def test_candidates_are_chunked_with_default_size_ten(self):
        records = [{"title": f"Event {i}", "text": f"Event {i}"} for i in range(61)]
        batches = chunk_candidates(records)
        self.assertEqual([len(batch) for batch in batches], [10, 10, 10, 10, 10, 10, 1])
        self.assertEqual([record["title"] for batch in batches for record in batch], [f"Event {i}" for i in range(61)])


class AttemptArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.html_path = self.root / "input.html"
        self.html_path.write_text(
            '<html><head><title>Listing</title></head><body><script type="application/ld+json">'
            '{"@type":"Event","name":"Example Event","description":"Source listing"}'
            '</script></body></html>', encoding="utf-8"
        )
        self.run_dir = self.root / "runs"
        self.events_path = self.root / "existing-events.json"
        self.events_path.write_text("[]\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_confirmed(self, response_text="[]", *, stem="attempt", validator=None, failure=None):
        args = [str(self.html_path), "--source-url", "https://example.test/list", "--confirm-api",
                "--run-dir", str(self.run_dir), "--output", str(self.events_path)]
        stdout, stderr = StringIO(), StringIO()
        with patch("scraper.extract._unique_run_stem", return_value=stem), \
             patch("scraper.extract.load_api_key", return_value="local-test-key"), \
             patch("scraper.extract.get_model_name", return_value=DEFAULT_MODEL), \
             patch("scraper.extract.call_gemini", side_effect=failure or (lambda *a: response_text)), \
             patch("scraper.extract.time.sleep"), \
             patch("scraper.extract.validate_events", side_effect=validator) if validator else patch("scraper.extract.validate_events", wraps=validate_events), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_success_saves_raw_response_before_validation(self):
        def assert_raw_exists(*args):
            self.assertTrue((self.run_dir / "attempt_batch_001_raw.json").exists())
            return [], [], []
        status, stdout, _ = self.run_confirmed(validator=assert_raw_exists)
        self.assertEqual(status, 0)
        self.assertIn("RAW_RESPONSE_SAVED", stdout)
        self.assertTrue((self.run_dir / "attempt_validated.json").exists())
        metadata = json.loads((self.run_dir / "attempt_metadata.json").read_text())
        self.assertEqual(metadata["last_completed_stage"], "VALIDATED_OUTPUT_SAVED")
        self.assertEqual(metadata["final_status"], "success")

    def test_canonical_object_is_read_only_merge_base_and_run_artifact_remains_an_array(self):
        existing = event_sample("existing curated event")
        existing["id"] = "existing-stable-id"
        canonical = {"schema_version": "1.2", "reviewed_at": "2026-11-14", "events": [existing]}
        original_text = json.dumps(canonical, ensure_ascii=False, indent=2) + "\n"
        self.events_path.write_text(original_text, encoding="utf-8")
        status, _, _ = self.run_confirmed("[]", stem="canonical-base")
        self.assertEqual(status, 0)
        self.assertEqual(self.events_path.read_text(encoding="utf-8"), original_text)
        artifact = json.loads((self.run_dir / "canonical-base_validated.json").read_text(encoding="utf-8"))
        metadata = json.loads((self.run_dir / "canonical-base_metadata.json").read_text(encoding="utf-8"))
        self.assertIsInstance(artifact, list)
        self.assertEqual(artifact[0]["id"], "existing-stable-id")
        self.assertEqual(metadata["merge_base_format"], "canonical_object")

    def test_events_without_food_evidence_are_filtered_before_validated_output(self):
        unrelated = event_sample("source")
        unrelated.update({
            "title": "Campus Meeting", "description": "Discuss campus planning.",
            "food_description": None, "provides_food": None, "is_free": None,
            "evidence": {key: None for key in EVIDENCE_FIELDS},
        })
        unrelated["evidence"]["title"] = "Campus Meeting"
        status, _, _ = self.run_confirmed(validator=lambda *args: ([unrelated], [], []), stem="food-relevance")
        self.assertEqual(status, 0)
        artifact = json.loads((self.run_dir / "food-relevance_validated.json").read_text(encoding="utf-8"))
        metadata = json.loads((self.run_dir / "food-relevance_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact, [])
        self.assertEqual(metadata["food_relevance_excluded_count"], 1)
        self.assertEqual(metadata["events_accepted"], 0)
        self.assertTrue(any("food_relevance" in reason for reason in metadata["rejected_reasons"]))

    def test_invalid_json_keeps_raw_and_records_last_completed_stage(self):
        status, _, stderr = self.run_confirmed("not JSON")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads((self.run_dir / "attempt_batch_001_raw.json").read_text()), "not JSON")
        metadata = json.loads((self.run_dir / "attempt_metadata.json").read_text())
        self.assertEqual(metadata["last_completed_stage"], "RAW_RESPONSE_SAVED")
        self.assertEqual(metadata["error_type"], "json_parse_error")
        self.assertEqual(metadata["failed_stage"], "parsing")
        self.assertIn("failed batch(es): 1", stderr)

    def test_validation_failure_keeps_raw(self):
        status, _, _ = self.run_confirmed("[]", validator=ExtractError("local validation failure"))
        self.assertEqual(status, 1)
        self.assertTrue((self.run_dir / "attempt_batch_001_raw.json").exists())
        metadata = json.loads((self.run_dir / "attempt_metadata.json").read_text())
        self.assertEqual(metadata["last_completed_stage"], "JSON_PARSE_STARTED")
        self.assertEqual(metadata["error_type"], "validation_error")

    def test_existing_raw_and_metadata_files_are_not_overwritten(self):
        self.run_dir.mkdir()
        raw_path = self.run_dir / "attempt_batch_001_raw.json"
        raw_path.write_text('"keep me"', encoding="utf-8")
        status, _, stderr = self.run_confirmed("[]")
        self.assertEqual(status, 1)
        self.assertEqual(raw_path.read_text(encoding="utf-8"), '"keep me"')
        self.assertIn("FileExistsError", stderr)

    def test_existing_validated_output_is_not_overwritten(self):
        self.run_dir.mkdir()
        validated_path = self.run_dir / "attempt_validated.json"
        validated_path.write_text('[{"keep":"me"}]\n', encoding="utf-8")
        status, _, stderr = self.run_confirmed("[]")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(validated_path.read_text(encoding="utf-8")), [{"keep": "me"}])
        self.assertFalse((self.run_dir / "attempt_batch_001_raw.json").exists())
        self.assertIn("FileExistsError", stderr)

    def test_timeout_records_failure_and_never_retries(self):
        status, _, stderr = self.run_confirmed(failure=StageError(
            "API_REQUEST_STARTED", "timeout", "Gemini request timed out after 60 seconds; no retry was attempted."))
        self.assertEqual(status, 1)
        metadata = json.loads((self.run_dir / "attempt_metadata.json").read_text())
        self.assertEqual(metadata["last_completed_stage"], "PREFLIGHT_PASSED")
        self.assertEqual(metadata["error_type"], "timeout")
        self.assertIn("timed out after 60 seconds", stderr)

    def test_503_and_429_are_not_retried_and_metadata_is_accurate(self):
        for status_code in (503, 429):
            with self.subTest(status_code=status_code):
                run_dir = self.root / f"runs-{status_code}"
                calls = []

                def failed_request(*args):
                    calls.append(1)
                    raise StageError("API_REQUEST_STARTED", "api_error", "temporary API error",
                                     duration=0.125, status_code=status_code,
                                     raw_message="temporary", failed_stage="server_response")

                args = [str(self.html_path), "--source-url", "https://example.test/list", "--confirm-api",
                        "--run-dir", str(run_dir), "--output", str(self.events_path)]
                with patch("scraper.extract._unique_run_stem", return_value=f"attempt-{status_code}"), \
                     patch("scraper.extract.load_api_key", return_value="local-test-key"), \
                     patch("scraper.extract.get_model_name", return_value=DEFAULT_MODEL), \
                     patch("scraper.extract.call_gemini", side_effect=failed_request), \
                     redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    status = main(args)
                self.assertEqual(status, 1)
                self.assertEqual(len(calls), 1)
                metadata = json.loads((run_dir / f"attempt-{status_code}_metadata.json").read_text())
                self.assertEqual(metadata["retry_attempts"], 0)
                self.assertEqual(metadata["http_status_code"], status_code)
                self.assertEqual(metadata["request_duration_seconds"], 0.125)
                self.assertEqual(metadata["raw_error_message"], "temporary")
                self.assertTrue(metadata["automatic_sdk_retries_disabled"])

    def test_server_error_on_second_batch_records_diagnostics(self):
        html = "<html><head><title>Listing</title></head><body>" + "".join(
            '<script type="application/ld+json">' + json.dumps({
                "@type": "Event", "name": f"Local Event {index}", "description": f"Description {index}",
                "url": f"https://example.test/event/{index}",
            }) + "</script>" for index in range(21)
        ) + "</body></html>"
        self.html_path.write_text(html, encoding="utf-8")

        class ServerError(Exception):
            code = 503
            message = "Temporary overload."

        class FakeModels:
            def __init__(self):
                self.calls = 0
            def generate_content(self, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise ServerError("Temporary overload.")
                return type("Response", (), {"text": "[]"})()

        models = FakeModels()
        class FakeClient:
            def __init__(self, api_key, http_options):
                self.models = models
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        args = [str(self.html_path), "--source-url", "https://example.test/list", "--confirm-api",
                "--run-dir", str(self.run_dir), "--output", str(self.events_path), "--batch-size", "10"]
        import sys
        from types import ModuleType, SimpleNamespace
        fake_genai = ModuleType("google.genai")
        fake_genai.Client = FakeClient
        fake_genai.types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        with patch.dict(sys.modules, {"google.genai": fake_genai}), \
             patch("scraper.extract._unique_run_stem", return_value="server-failure"), \
             patch("scraper.extract.load_api_key", return_value="local-test-key"), \
             patch("scraper.extract.get_model_name", return_value=DEFAULT_MODEL), \
             patch("scraper.extract.time.sleep") as sleep_mock, \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()) as error_output:
            status = main(args)
        self.assertEqual(status, 1)
        self.assertEqual(models.calls, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        self.assertTrue(all(4.0 <= call.args[0] <= 4.1 for call in sleep_mock.call_args_list))
        metadata = json.loads((self.run_dir / "server-failure_metadata.json").read_text())
        self.assertEqual(metadata["failed_batch"], 2)
        self.assertEqual(metadata["http_status_code"], 503)
        self.assertEqual(metadata["raw_error_message"], "Temporary overload.")
        self.assertEqual(metadata["failed_stage"], "server_response")
        self.assertIsInstance(metadata["request_duration_seconds"], float)
        self.assertEqual(metadata["retry_attempts"], 0)
        self.assertEqual(metadata["retry_log"], [])
        self.assertEqual(len(metadata["raw_response_files"]), 2)
        self.assertTrue(Path(metadata["validated_output_file"]).exists())
        self.assertEqual(len(metadata["batch_results"]), 3)
        self.assertEqual(metadata["failed_batches"], [2])
        self.assertEqual(metadata["final_status"], "partial_failure")
        self.assertIn("failed after 0 retries", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
