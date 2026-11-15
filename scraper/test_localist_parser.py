"""Offline tests for parsing JSON-escaped UCSD Localist widget responses."""

import json
import unittest
from pathlib import Path

from scraper.localist_parser import (
    LocalistParseError,
    parse_localist_widget_response,
    parse_localist_widget_response_detailed,
)


ROOT = Path(__file__).resolve().parent.parent
WIDGET_HTML = ROOT / "data" / "calendar_ucsd_edu_widget_view.html"
WIDGET_SOURCE_URL = (
    "https://calendar.ucsd.edu/widget/view?schools=ucsd&groups=muir-college%2Cstudent-life"
)


def card_html(
    *,
    title="Café &amp; Tea",
    date="Nov 14 - Dec 6",
    time="at 2pm PST",
    location="Muir Hall",
    description="Crème brûlée, tea &amp; pastries.",
    detail_url="https://calendar.ucsd.edu/event/cafe-tea?utm_source=widget&amp;ref=source",
    extra="",
):
    time_html = f'<span class="lw_event_item_time">{time}</span>' if time is not None else ""
    date_html = f'<div class="lw_event_item_date"><p>{date} {time_html}</p></div>' if date is not None else ""
    location_html = f'<div class="lw_event_item_location">Location: <a href="/place">{location}</a></div>' if location is not None else ""
    description_html = f'<div class="lw_event_item_description">{description}</div>' if description is not None else ""
    title_anchor = f'<a href="{detail_url}">{title}</a>' if detail_url is not None else f"<a>{title}</a>"
    return f"""
    <li class="lw lw_event_item">
      <div class="lw_event_item_title"><h3>{title_anchor}</h3></div>
      {date_html}{description_html}{location_html}{extra}
    </li>
    """


def widget_response(*cards: str, container="localist-widget-test") -> str:
    embedded = '<ul class="lw lw_event_list">' + "".join(cards) + "</ul>"
    return f"document.getElementById({json.dumps(container)}).innerHTML={json.dumps(embedded, ensure_ascii=True)};"

def widget_response_raw(js_code: str) -> str:
    """Helper for providing completely custom JavaScript code."""
    return js_code

def arbitrary_widget_response(embedded_html: str, container="localist-widget-test") -> str:
    return f"document.getElementById({json.dumps(container)}).innerHTML={json.dumps(embedded_html, ensure_ascii=True)};"


class LocalistParserTests(unittest.TestCase):
    def test_parses_one_card_and_preserves_original_and_normalized_urls(self):
        event = parse_localist_widget_response(widget_response(card_html()), WIDGET_SOURCE_URL)[0]
        self.assertEqual(event["title"], "Café & Tea")
        self.assertEqual(
            event["detail_url"],
            "https://calendar.ucsd.edu/event/cafe-tea?utm_source=widget&ref=source",
        )
        self.assertEqual(event["normalized_detail_url"], "https://calendar.ucsd.edu/event/cafe-tea?ref=source")
        self.assertEqual(event["widget_source_url"], WIDGET_SOURCE_URL)

    def test_parses_all_13_cards_in_the_saved_widget_response(self):
        response = WIDGET_HTML.read_text(encoding="utf-8")
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL)
        self.assertEqual(len(events), 13)
        self.assertEqual(events[0]["title"], "Grim")
        self.assertEqual(events[-1]["title"], "Smash Your Stress: Mosaic Workshop (Grads/Post-Docs Only)")
        self.assertTrue(all(event["detail_url"] for event in events))

    def test_two_widgets_only_the_requested_container_is_parsed(self):
        response = widget_response(card_html(title="Widget one"), container="widget-one")
        response += widget_response(card_html(title="Widget two"), container="widget-two")
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL, container_id="widget-two")
        self.assertEqual([event["title"] for event in events], ["Widget two"])

    def test_requested_container_missing_raises_a_clear_error(self):
        response = widget_response(card_html(title="Widget one"), container="widget-one")
        with self.assertRaisesRegex(LocalistParseError, "No innerHTML assignment was found for widget container 'missing'"):
            parse_localist_widget_response(response, WIDGET_SOURCE_URL, container_id="missing")

    def test_multiple_widgets_without_selection_raise_instead_of_merging(self):
        response = widget_response(card_html(title="Widget one"), container="widget-one")
        response += widget_response(card_html(title="Widget two"), container="widget-two")
        with self.assertRaisesRegex(LocalistParseError, "Found multiple widget containers"):
            parse_localist_widget_response(response, WIDGET_SOURCE_URL)

    def test_missing_time_and_location_remain_null(self):
        event = parse_localist_widget_response(
            widget_response(card_html(time=None, location=None)), WIDGET_SOURCE_URL
        )[0]
        self.assertIsNone(event["time_text"])
        self.assertIsNone(event["location"])
        self.assertIsNone(event["location_text"])

    def test_parses_assignment_ending_with_semicolon(self):
        html = '<ul class="lw_event_list">' + card_html(title="Semicolon End") + '</ul>'
        response = widget_response_raw(f"document.getElementById('localist-widget-test').innerHTML={json.dumps(html)};")
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL)
        self.assertEqual(events[0]["title"], "Semicolon End")

    def test_parses_assignment_ending_at_eof(self):
        html = '<ul class="lw_event_list">' + card_html(title="EOF End") + '</ul>'
        response = widget_response_raw(f"document.getElementById('localist-widget-test').innerHTML={json.dumps(html)}")
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL)
        self.assertEqual(events[0]["title"], "EOF End")

    def test_parses_escaped_quotes_and_backslashes(self):
        html = '<ul class="lw_event_list">' + card_html(title='\\"Quotes\\" & \\\\Backslashes\\\\') + '</ul>'
        response = widget_response_raw(f"document.getElementById('localist-widget-test').innerHTML={json.dumps(html)};")
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL)
        self.assertEqual(events[0]["title"], '\\"Quotes\\" & \\\\Backslashes\\\\')

    def test_rejects_multiline_string_concatenation(self):
        # Ensures that a trailing + operator safely causes the regex to fail matching, preventing truncation.
        part1 = '<ul class="lw_event_list"><li class="lw_event_item"><div class="lw_event_item_title"><a>'
        part2 = 'Concat Multi</a></div></li></ul>'
        response = widget_response_raw(f"document.getElementById('localist-widget-test').innerHTML={json.dumps(part1)} +\n {json.dumps(part2)};")
        with self.assertRaisesRegex(LocalistParseError, "No JSON-escaped innerHTML assignment"):
            parse_localist_widget_response(response, WIDGET_SOURCE_URL)

    def test_date_ranges_are_preserved_as_display_text_without_year_inference(self):
        event = parse_localist_widget_response(
            widget_response(card_html(date="Nov 14 - Dec 6", time=None)), WIDGET_SOURCE_URL
        )[0]
        self.assertEqual(event["date_text"], "Nov 14 - Dec 6")
        self.assertIsNone(event["time_text"])
        self.assertNotIn("202", event["date_text"])

    def test_non_ascii_and_html_special_characters_are_decoded_as_text(self):
        event = parse_localist_widget_response(widget_response(card_html()), WIDGET_SOURCE_URL)[0]
        self.assertEqual(event["title"], "Café & Tea")
        self.assertEqual(event["description"], "Crème brûlée, tea & pastries.")

    def test_json_escaped_javascript_string_is_decoded(self):
        source = widget_response(card_html(title='A "quoted" event', description="Line one\\nLine two"))
        event = parse_localist_widget_response(source, WIDGET_SOURCE_URL)[0]
        self.assertEqual(event["title"], 'A "quoted" event')
        self.assertEqual(event["description"], "Line one\\nLine two")

    def test_missing_innerhtml_raises_a_clear_error(self):
        with self.assertRaisesRegex(LocalistParseError, "No JSON-escaped innerHTML assignment"):
            parse_localist_widget_response("window.widget = {};", WIDGET_SOURCE_URL)

    def test_innerhtml_without_event_cards_raises_a_clear_error(self):
        response = widget_response('<p>Calendar introduction, not an event.</p>')
        with self.assertRaisesRegex(LocalistParseError, "contained no li.lw_event_item"):
            parse_localist_widget_response(response, WIDGET_SOURCE_URL)

    def test_event_class_outside_expected_list_container_is_not_parsed(self):
        response = arbitrary_widget_response('<div><li class="lw_event_item">Outside list</li></div>')
        with self.assertRaisesRegex(LocalistParseError, "no ul.lw_event_list container"):
            parse_localist_widget_response(response, WIDGET_SOURCE_URL)

    def test_source_and_detail_urls_are_kept_separately(self):
        event = parse_localist_widget_response(widget_response(card_html()), WIDGET_SOURCE_URL)[0]
        self.assertEqual(event["widget_source_url"], WIDGET_SOURCE_URL)
        self.assertIn("utm_source=widget", event["detail_url"])
        self.assertNotIn("utm_source", event["normalized_detail_url"])
        self.assertIn("ref=source", event["normalized_detail_url"])

    def test_relative_detail_url_is_resolved_and_original_query_and_fragment_are_preserved(self):
        raw_href = "../event/relative?utm_source=widget&ref=a%20b#details"
        source_url = "https://calendar.ucsd.edu/widget/view?schools=ucsd"
        event = parse_localist_widget_response(widget_response(card_html(detail_url=raw_href)), source_url)[0]
        self.assertEqual(event["detail_url"], raw_href)
        self.assertEqual(
            event["normalized_detail_url"],
            "https://calendar.ucsd.edu/event/relative?ref=a+b#details",
        )

    def test_missing_title_cards_are_skipped_and_counted(self):
        response = widget_response(card_html(title="   "), card_html(title="Usable title"))
        result = parse_localist_widget_response_detailed(response, WIDGET_SOURCE_URL)
        self.assertEqual(result.card_count, 2)
        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual([event["title"] for event in result.events], ["Usable title"])
        self.assertTrue(any("missing or blank title" in warning for warning in result.warnings))

    def test_event_without_detail_url_is_retained_and_diagnosed(self):
        result = parse_localist_widget_response_detailed(
            widget_response(card_html(title="No link", detail_url=None)), WIDGET_SOURCE_URL
        )
        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.missing_detail_url_count, 1)
        self.assertIsNone(result.events[0]["detail_url"])
        self.assertIsNone(result.events[0]["normalized_detail_url"])
        self.assertTrue(any("no detail URL" in warning for warning in result.warnings))

    def test_widget_filters_do_not_create_event_group_or_organizer(self):
        source_with_muir_filter = WIDGET_SOURCE_URL + "&groups=muir-college"
        event = parse_localist_widget_response(widget_response(card_html()), source_with_muir_filter)[0]
        self.assertIsNone(event["group"])
        self.assertIsNone(event["organizer"])

    def test_explicit_card_organizer_is_kept(self):
        event = parse_localist_widget_response(
            widget_response(card_html(extra='<span class="lw_event_item_organization">Muir College Council</span>')),
            WIDGET_SOURCE_URL,
        )[0]
        self.assertEqual(event["organizer"], "Muir College Council")
        self.assertIsNone(event["group"])

    def test_duplicate_titles_are_not_deduplicated_by_parser(self):
        response = widget_response(card_html(title="Repeated title"), card_html(title="Repeated title", detail_url="https://calendar.ucsd.edu/event/other"))
        events = parse_localist_widget_response(response, WIDGET_SOURCE_URL)
        self.assertEqual(len(events), 2)
        self.assertEqual([event["title"] for event in events], ["Repeated title", "Repeated title"])

    def test_reaching_num_limit_warns_possible_truncation_without_claiming_certainty(self):
        cards = [card_html(title=f"Card {index}") for index in range(50)]
        result = parse_localist_widget_response_detailed(
            widget_response(*cards), WIDGET_SOURCE_URL + "&num=50"
        )
        self.assertEqual(result.card_count, 50)
        self.assertTrue(result.possible_truncation)
        self.assertTrue(any("may be truncated" in warning for warning in result.warnings))

    def test_below_num_limit_has_no_possible_truncation_warning(self):
        result = parse_localist_widget_response_detailed(
            widget_response(card_html(title="Only result")), WIDGET_SOURCE_URL + "&num=50"
        )
        self.assertEqual(result.card_count, 1)
        self.assertFalse(result.possible_truncation)
        self.assertFalse(any("truncated" in warning for warning in result.warnings))

    def test_existing_mojibake_is_preserved_without_automatic_repair(self):
        events = parse_localist_widget_response(WIDGET_HTML.read_text(encoding="utf-8"), WIDGET_SOURCE_URL)
        event = next(item for item in events if item["title"] == "Destress with Diego")
        self.assertIn("Womenâ\x80\x99s Center", event["description"])
        self.assertNotIn("Women’s Center", event["description"])


if __name__ == "__main__":
    unittest.main()
