"""Headless tests: argument parsing, config and the content seam.

The Tk layer is not covered here; it needs a display and is checked by hand.
Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from mainichi.cli import _parse_size, _validate_kanji, build_parser
from mainichi.config import DEFAULT_LEVEL, MIN_SIZE, AppConfig, PostItOptions
from mainichi.content import KanjiCard, PlaceholderProvider
from mainichi.ui.theme import PALETTES, get_palette


class TestCli(unittest.TestCase):
    def test_default_level_is_n5(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.level, DEFAULT_LEVEL)
        self.assertIsNone(args.kanji)

    def test_level_and_kanji_are_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--level", "N3", "--kanji", "日"])

    def test_unknown_level_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--level", "N9"])

    def test_kanji_validation(self):
        self.assertEqual(_validate_kanji(" 日 "), "日")
        for bad in ("ab", "", "あ", "A"):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                _validate_kanji(bad)

    def test_size_parsing_and_floor(self):
        self.assertEqual(_parse_size("400x500"), (400, 500))
        self.assertEqual(_parse_size("10x10"), MIN_SIZE)
        with self.assertRaises(Exception):
            _parse_size("wide")


class TestConfig(unittest.TestCase):
    def test_options_copy_is_independent(self):
        original = PostItOptions()
        clone = original.copy()
        clone.palette = "blue"
        self.assertEqual(original.palette, "yellow")

    def test_selection_label(self):
        self.assertEqual(AppConfig().selection_label, "JLPT N5")
        self.assertEqual(AppConfig(kanji="日").selection_label, "日")


class TestContent(unittest.TestCase):
    def test_placeholder_cards_are_empty_but_keep_level(self):
        provider = PlaceholderProvider()
        card = provider.next_card("N3")
        self.assertTrue(card.is_placeholder)
        self.assertEqual(card.level, "N3")
        self.assertEqual(provider.served, 1)

    def test_explicit_kanji_is_not_a_placeholder(self):
        card = PlaceholderProvider().next_card("N5", "日")
        self.assertFalse(card.is_placeholder)
        self.assertEqual(card.kanji, "日")

    def test_card_defaults(self):
        self.assertTrue(KanjiCard().is_placeholder)


class TestTheme(unittest.TestCase):
    def test_all_palettes_complete(self):
        for name, pal in PALETTES.items():
            with self.subTest(palette=name):
                for slot in (pal.paper, pal.fold, pal.ink, pal.ink_soft, pal.guide):
                    self.assertRegex(slot, r"^#[0-9a-f]{6}$")

    def test_unknown_palette_falls_back(self):
        self.assertEqual(get_palette("chartreuse").name, "yellow")


if __name__ == "__main__":
    unittest.main()
