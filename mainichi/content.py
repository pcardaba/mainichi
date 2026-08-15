"""The data a post-it displays, and where it comes from.

The UI only ever talks to a :class:`CardProvider`. At this stage the only
implementation is :class:`PlaceholderProvider`, which returns empty cards so
the window can be laid out and judged before any kanji data exists. Real
providers (bundled JLPT data set, KANJIDIC, Jisho, ...) plug in here later
without touching the presentation layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from mainichi.config import DEFAULT_LANGUAGE


@dataclass(frozen=True, slots=True)
class Word:
    """A vocabulary item shown on the recto, one per reading of the kanji."""

    text: str  # e.g. 日本
    reading: str  # furigana for the whole word, e.g. にほん
    # Meanings by language code, e.g. {"en": "Japan", "fr": "Japon"}. English
    # is always present; JMdict translates only part of its entries.
    meanings: Mapping[str, str] = field(default_factory=dict)
    # Per-character alignment, e.g. 日曜日 -> (("日","にち"),("曜","よう"),("日","び")).
    # Kana characters carry an empty reading. This is what lets the ruby text
    # sit over the right character instead of over the whole word.
    furigana: tuple[tuple[str, str], ...] = ()

    def meaning(self, language: str) -> tuple[str, str]:
        """The meaning and the language it is actually in.

        Falls back to English, and says so, rather than quietly showing a
        language the reader did not ask for.
        """
        text = self.meanings.get(language)
        if text:
            return text, language
        fallback = self.meanings.get(DEFAULT_LANGUAGE, "")
        return fallback, DEFAULT_LANGUAGE if fallback else language


@dataclass(frozen=True, slots=True)
class Sentence:
    """An example sentence shown on the verso, one per word."""

    text: str
    # Same per-character alignment as Word.furigana, for the whole sentence.
    furigana: tuple[tuple[str, str], ...] = ()
    # Translations by language code: "en", "fr", "es".
    translations: Mapping[str, str] = field(default_factory=dict)

    def translation(self, language: str) -> tuple[str, str]:
        """The translation and the language it is actually in.

        Tatoeba has a French or Spanish translation for only part of its
        Japanese sentences, so the caller is told when it had to fall back to
        English and can say so rather than silently showing another language.
        """
        text = self.translations.get(language)
        if text:
            return text, language
        fallback = self.translations.get(DEFAULT_LANGUAGE, "")
        return fallback, DEFAULT_LANGUAGE if fallback else language


@dataclass(frozen=True, slots=True)
class KanjiCard:
    """Everything both faces of a single post-it need."""

    kanji: str = ""
    level: str = ""
    meanings: tuple[str, ...] = ()
    on_readings: tuple[str, ...] = ()
    kun_readings: tuple[str, ...] = ()
    words: tuple[Word, ...] = ()
    sentences: tuple[Sentence, ...] = ()
    # Further words using this kanji, beyond the one-per-reading set shown on
    # the recto. The verso can show these instead of the example sentences.
    vocabulary: tuple[Word, ...] = ()
    strokes: int = 0

    @property
    def is_placeholder(self) -> bool:
        """True while no real kanji has been loaded yet."""
        return not self.kanji


class CardProvider(Protocol):
    """Source of kanji cards."""

    def next_card(self, level: str, kanji: str | None = None) -> KanjiCard:
        """Return a card: the given ``kanji`` if any, else one for ``level``."""
        ...


@dataclass(slots=True)
class PlaceholderProvider:
    """Framework stage stand-in: hands out empty cards.

    It keeps a counter so that "Next" is visibly doing something even before
    there is any content to show.
    """

    served: int = field(default=0)

    def next_card(self, level: str, kanji: str | None = None) -> KanjiCard:
        self.served += 1
        return KanjiCard(kanji=kanji or "", level=level)
