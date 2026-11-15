"""Regression checks for curated FreeBite data rules."""

import json
import unittest
from pathlib import Path

from scraper.curated_data import (
    derive_food_status,
    duplicate_key,
    food_relevance_reason,
    normalize_eligibility,
    stable_event_id,
)

ROOT = Path(__file__).resolve().parent.parent


class FoodStatusTests(unittest.TestCase):
    def test_food_and_free_food_are_both_required_for_confirmed_free(self):
        self.assertEqual(
            derive_food_status(True, True, "Snacks will be provided", "Free snacks are available"),
            "confirmed_free",
        )

    def test_free_admission_does_not_mean_free_food(self):
        self.assertEqual(
            derive_food_status(True, True, "Snacks will be provided", "Free event admission"),
            "provided_cost_unknown",
        )

    def test_unknowns_stay_unknown_and_no_food_requires_evidence(self):
        self.assertEqual(derive_food_status(None, True, None, "Free event"), "food_unconfirmed")
        self.assertEqual(derive_food_status(False, None, None, None), "food_unconfirmed")
        self.assertEqual(derive_food_status(False, None, "No food will be provided", None), "not_provided")


class FoodRelevanceTests(unittest.TestCase):
    def test_food_mention_with_uncertain_provision_is_still_relevant(self):
        event = {
            "food_status": "food_unconfirmed",
            "title": "Campus gathering",
            "description": "The source mentions pastries but does not say whether they are served.",
            "food_description": None,
            "evidence": {"provides_food": None, "food_description": None},
        }
        self.assertIsNotNone(food_relevance_reason(event))

    def test_explicit_refreshment_reference_is_relevant_for_review(self):
        event = {
            "food_status": "food_unconfirmed",
            "title": "Research seminar",
            "description": "Join us on the terrace for refreshments before the event.",
            "food_description": "refreshments",
            "evidence": {"provides_food": None, "food_description": "refreshments"},
        }
        self.assertIsNotNone(food_relevance_reason(event))

    def test_non_provision_water_and_exhibit_contexts_are_not_food_opportunities(self):
        examples = (
            ("Men's Water Polo", "The match is at the aquatic center."),
            ("Wetlands walk", "Please bring closed-toed shoes, sun protection, and water."),
            ("Poetry reading", "The author writes about relations to land and water."),
            ("Library exhibit", "This exhibit features historic lunchboxes."),
        )
        for title, description in examples:
            with self.subTest(title=title):
                self.assertIsNone(food_relevance_reason({
                    "food_status": "food_unconfirmed",
                    "title": title,
                    "description": description,
                    "food_description": None,
                    "evidence": {"provides_food": None, "food_description": None},
                }))

    def test_free_admission_without_food_information_is_not_relevant(self):
        self.assertIsNone(food_relevance_reason({
            "food_status": "food_unconfirmed",
            "title": "Chemistry review session",
            "description": "Review ionic bonding with peer tutors.",
            "food_description": None,
            "evidence": {"provides_food": None, "food_description": None, "is_free": "Free"},
        }))


class EligibilityNormalizationTests(unittest.TestCase):
    def test_unrestricted_source_phrases_normalize_to_everyone(self):
        examples = (
            "All are welcome",
            "Everyone is welcome.",
            "Open to all",
            "open to the public",
            "any and everyone",
            "Students, faculty, staff, families, and community members are all welcome. No UC San Diego affiliation is required.",
        )
        for value in examples:
            with self.subTest(value=value):
                self.assertEqual(normalize_eligibility(value), "Everyone")

    def test_all_students_and_genuine_restrictions_keep_their_scope(self):
        self.assertEqual(normalize_eligibility("All students are welcome."), "All students")
        restriction = "UCSD students with a valid student ID are encouraged to use the promo code."
        self.assertEqual(normalize_eligibility(restriction), restriction.rstrip("."))
        self.assertIsNone(normalize_eligibility(None))


class CanonicalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "data/events.json").read_text(encoding="utf-8"))

    def test_ids_are_stable_and_unique(self):
        events = self.data["events"]
        self.assertEqual(len({e["id"] for e in events}), len(events))
        self.assertTrue(all(e["id"] == stable_event_id(e) for e in events))

    def test_duplicate_occurrences_are_removed_without_collapsing_different_dates(self):
        keys = [duplicate_key(e) for e in self.data["events"]]
        self.assertEqual(len(keys), len(set(keys)))
        distributions = [e for e in self.data["events"] if e["title"] == "Free Food Distribution"]
        self.assertEqual({e["date"] for e in distributions}, {"2026-11-20", "2026-12-11"})

    def test_evidence_and_unknown_fields_are_preserved(self):
        events = self.data["events"]
        self.assertTrue(all("evidence" in e and "extraction_evidence" in e for e in events))
        self.assertTrue(all(e["date"] is not None for e in events))
        self.assertTrue(all(e["food_status"] in {
            "confirmed_free", "provided_cost_unknown", "food_unconfirmed", "not_provided"
        } for e in events))

    def test_reviewed_food_status_counts_and_provision_correction(self):
        events = self.data["events"]
        counts = {status: sum(e["food_status"] == status for e in events) for status in (
            "confirmed_free", "provided_cost_unknown", "food_unconfirmed", "not_provided"
        )}
        self.assertEqual(counts, {
            "confirmed_free": 3,
            "provided_cost_unknown": 5,
            "food_unconfirmed": 0,
            "not_provided": 0,
        })
        nov20 = next(e for e in events if e["event_url"].endswith("free-food-distribution-1533"))
        self.assertEqual(nov20["food_status"], "confirmed_free")
        world_aids = next(e for e in events if "world-aids-day" in e["event_url"])
        self.assertIn("boba", world_aids["evidence"]["is_free"].casefold())
        sanford = next(e for e in events if e["title"].startswith("Sanford Stem Cell"))
        self.assertEqual(sanford["food_status"], "provided_cost_unknown")
        self.assertIn("refreshments", sanford["evidence"]["provides_food"].casefold())

    def test_every_canonical_record_has_food_relevance_and_archived_records_do_not(self):
        self.assertTrue(all(food_relevance_reason(event) for event in self.data["events"]))
        archive = json.loads((ROOT / "data/event_curation_exclusions.json").read_text(encoding="utf-8"))
        self.assertTrue(all(food_relevance_reason(item["record"]) is None for item in archive["excluded_events"]))

    def test_retained_eligibility_is_normalized_without_overwriting_evidence(self):
        distributions = [e for e in self.data["events"] if e["title"] == "Free Food Distribution"]
        for event in distributions:
            self.assertEqual(event["eligibility"], "Students, staff, faculty, and San Diego community members")
            self.assertIn("faculty ,", event["evidence"]["eligibility"])
        research = next(e for e in self.data["events"] if e["title"] == "Research in the Arts and Humanities")
        self.assertEqual(research["eligibility"], "All UC San Diego students; Arts and Humanities emphasized")
        self.assertIn("open to all students", research["evidence"]["eligibility"].casefold())

    def test_exclusion_audit_preserves_records_and_reasons(self):
        audit = json.loads((ROOT / "data/event_curation_exclusions.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["excluded_count"], 43)
        self.assertEqual(len(audit["excluded_events"]), 43)
        self.assertEqual(
            {category: details["count"] for category, details in audit["categories"].items()},
            {"no_food_related_evidence": 39, "non_provision_context": 4},
        )
        self.assertTrue(all(item["record"]["id"] == item["id"] for item in audit["excluded_events"]))


if __name__ == "__main__":
    unittest.main()
