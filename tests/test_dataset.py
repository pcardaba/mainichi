"""Tests for the bundled JLPT data and the provider that reads it.

These run against the real data files, so they also catch a bad rebuild.
"""

from __future__ import annotations

import random
import unittest

from mainichi.config import LEVELS
from mainichi.content import Sentence, Word
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
                        self.assertTrue(example["t"])
                        self.assertTrue(example["tr"].get("en"), "English is always present")
                        # The furigana must spell the sentence back out.
                        rebuilt = "".join(text for text, _rt in example["f"])
                        self.assertEqual(rebuilt, example["t"], f"{level} {record['k']}")

    def test_sentences_carry_furigana_and_languages(self):
        card = self.provider.next_card("N5", "日")
        for sentence in card.sentences:
            with self.subTest(sentence=sentence.text):
                self.assertTrue(sentence.furigana)
                rebuilt = "".join(text for text, _rt in sentence.furigana)
                self.assertEqual(rebuilt, sentence.text)
                self.assertTrue(sentence.translations.get("en"))

    def test_word_meanings_carry_languages(self):
        card = self.provider.next_card("N5", "日")
        for word in (*card.words, *card.vocabulary):
            with self.subTest(word=word.text):
                self.assertTrue(word.meanings.get("en"), "English is always present")

    def test_word_meaning_falls_back_to_english(self):
        english_only = Word(text="x", reading="x", meanings={"en": "day"})
        self.assertEqual(english_only.meaning("fr"), ("day", "en"))
        both = Word(text="x", reading="x", meanings={"en": "day", "fr": "jour"})
        self.assertEqual(both.meaning("fr"), ("jour", "fr"))
        self.assertEqual(both.meaning("en"), ("day", "en"))

    def test_beginner_levels_are_mostly_translated(self):
        """The point of the full JMdict: N5/N4 words carry fr and es."""
        for level in ("N5", "N4"):
            words = [
                word
                for record in self.provider.load(level)
                for word in record.get("w", []) + record.get("v", [])
            ]
            for language in ("fr", "es"):
                share = sum(1 for w in words if language in w["m"]) / len(words)
                self.assertGreater(share, 0.6, f"{level} {language}: only {share:.0%}")

    def test_translation_falls_back_to_english(self):
        english_only = Sentence(text="x", translations={"en": "hello"})
        self.assertEqual(english_only.translation("fr"), ("hello", "en"))
        both = Sentence(text="x", translations={"en": "hello", "fr": "bonjour"})
        self.assertEqual(both.translation("fr"), ("bonjour", "fr"))
        self.assertEqual(both.translation("en"), ("hello", "en"))

    def test_sentences_prefer_kanji_at_or_below_the_level(self):
        """N5 sentences must not be built out of N1 characters."""
        levels = {}
        for level in LEVELS:
            for record in self.provider.load(level):
                levels.setdefault(record["k"], level)

        for level in ("N5", "N3"):
            rank = LEVELS.index(level)
            too_hard = total = 0
            for record in self.provider.load(level):
                for word in record.get("w", []):
                    example = word.get("s")
                    if not example:
                        continue
                    total += 1
                    for char in example["t"]:
                        found = levels.get(char)
                        if found and LEVELS.index(found) > rank:
                            too_hard += 1
                            break
            self.assertLess(too_hard / total, 0.55, f"{level}: sentences too hard")

    def test_card_conversion(self):
        card = self.provider.next_card("N5", "語")
        self.assertTrue(all(w.furigana for w in card.words))
        self.assertTrue(all(s.translation for s in card.sentences))
        self.assertLessEqual(len(card.sentences), len(card.words))


if __name__ == "__main__":
    unittest.main()
