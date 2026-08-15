"""Tests for the bundled JLPT data and the provider that reads it.

These run against the real data files, so they also catch a bad rebuild.
"""

from __future__ import annotations

import random
import unittest

from mainichi.config import LEVELS
from mainichi.dataset import BundledProvider, DataNotBuilt

# What tools/build_data.py produced, and what the JLPT reconstruction says.
EXPECTED_COUNTS = {"N5": 79, "N4": 166, "N3": 367, "N2": 367, "N1": 1232}


class TestBundledData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = BundledProvider()
        if not cls.provider.available():
            raise unittest.SkipTest("data not built; run python tools/build_data.py")

    def test_every_level_is_present(self):
        self.assertEqual(sorted(self.provider.available()), sorted(LEVELS))

    def test_level_sizes(self):
        for level, expected in EXPECTED_COUNTS.items():
            with self.subTest(level=level):
                self.assertEqual(len(self.provider.load(level)), expected)

    def test_known_kanji_lookup(self):
        card = self.provider.next_card("N5", "日")
        self.assertEqual(card.kanji, "日")
        self.assertEqual(card.level, "N5")
        self.assertIn("day", card.meanings)
        self.assertTrue(card.words)
        self.assertFalse(card.is_placeholder)

    def test_unknown_kanji(self):
        self.assertIsNone(self.provider.find("龘"))
        with self.assertRaises(KeyError):
            self.provider.next_card("N5", "龘")

    def test_missing_data_directory(self):
        provider = BundledProvider(data_dir=self.provider.data_dir / "nope")
        self.assertEqual(provider.available(), [])
        with self.assertRaises(DataNotBuilt):
            provider.load("N5")

    def test_deck_deals_each_kanji_once(self):
        provider = BundledProvider(rng=random.Random(1))
        seen = [provider.next_card("N5").kanji for _ in range(EXPECTED_COUNTS["N5"])]
        self.assertEqual(len(set(seen)), EXPECTED_COUNTS["N5"])
        # The deck reshuffles rather than running out.
        self.assertTrue(provider.next_card("N5").kanji)

    def test_furigana_reconstructs_the_word(self):
        """The ruby segments must spell the word, or they sit over nothing."""
        checked = 0
        for level in LEVELS:
            for record in self.provider.load(level):
                for word in record.get("w", []):
                    if not word.get("f"):
                        continue
                    rebuilt = "".join(ruby for ruby, _rt in word["f"])
                    self.assertEqual(rebuilt, word["t"], f"{level} {record['k']}")
                    checked += 1
        self.assertGreater(checked, 4000)

    def test_words_and_sentences_are_well_formed(self):
        for level in LEVELS:
            for record in self.provider.load(level):
                self.assertTrue(record["k"], "kanji character missing")
                for word in record.get("w", []):
                    self.assertTrue(word["t"] and word["r"])
                    self.assertIn(record["k"], word["t"])
                    example = word.get("s")
                    if example is not None:
                        self.assertEqual(len(example), 2)
                        self.assertTrue(example[0] and example[1])

    def test_card_conversion(self):
        card = self.provider.next_card("N5", "語")
        self.assertTrue(all(w.furigana for w in card.words))
        self.assertTrue(all(s.translation for s in card.sentences))
        self.assertLessEqual(len(card.sentences), len(card.words))


if __name__ == "__main__":
    unittest.main()
