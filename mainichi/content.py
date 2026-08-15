"""The data a post-it displays, and where it comes from.

The UI only ever talks to a :class:`CardProvider`. At this stage the only
implementation is :class:`PlaceholderProvider`, which returns empty cards so
the window can be laid out and judged before any kanji data exists. Real
providers (bundled JLPT data set, KANJIDIC, Jisho, ...) plug in here later
without touching the presentation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Word:
    """A vocabulary item shown on the recto, one per reading of the kanji."""

    text: str  # e.g. 日本
    reading: str  # furigana for the whole word, e.g. にほん
    meaning: str = ""  # e.g. "Japan"
    # Per-character alignment, e.g. 日曜日 -> (("日","にち"),("曜","よう"),("日","び")).
    # Kana characters carry an empty reading. This is what lets the ruby text
    # sit over the right character instead of over the whole word.
    furigana: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Sentence:
    """An example sentence shown on the verso, one per word."""

    text: str
    reading: str = ""
    translation: str = ""


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
