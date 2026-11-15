"""Offline checks for the shared scraper's supported source handling."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scraper.scrape import (
    SUPPORTED_SOURCES,
    identify_source,
    save_html,
    validate_target_url,
)


class SupportedSourceTests(unittest.TestCase):
    def test_both_calendar_urls_use_the_existing_generic_scraper(self):
        for key, source in SUPPORTED_SOURCES.items():
            with self.subTest(source=key):
                url = validate_target_url(source["url"])
                self.assertEqual(identify_source(url), key)

    def test_muir_html_saves_to_a_safe_unique_file_without_overwriting(self):
        source_url = SUPPORTED_SOURCES["muir_college"]["url"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scraper.scrape.PROJECT_ROOT", Path(temp_dir)):
                first = save_html(source_url, "<html>first</html>")
                second = save_html(source_url, "<html>second</html>")
            self.assertEqual(first.read_text(encoding="utf-8"), "<html>first</html>")
            self.assertEqual(second.read_text(encoding="utf-8"), "<html>second</html>")
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(temp_dir) / "data")
            self.assertTrue(first.name.startswith("muir_ucsd_edu_studentlife_calendarofevents_html"))


if __name__ == "__main__":
    unittest.main()
