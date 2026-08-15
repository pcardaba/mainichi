"""Reading the bundled kanji data.

The files in ``mainichi/data`` are produced by ``tools/build_data.py``. They
are gzipped JSON, one per JLPT level, and are loaded lazily: showing an N5
note never touches the 1232 kanji of N1.
"""

from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

from mainichi.content import KanjiCard, Sentence, Word

DATA_DIR = Path(__file__).resolve().parent / "data"


class DataNotBuilt(RuntimeError):
    """Raised when the data files are missing from the installation."""


class BundledProvider:
    """Serves cards from the data shipped with the package.

    Each level keeps a shuffled deck, so every kanji of a level is seen once
    before any of them comes round again.
    """

    def __init__(self, data_dir: Path | None = None, rng: random.Random | None = None) -> None:
        self.data_dir = data_dir or DATA_DIR
        self._rng = rng or random.Random()
        self._levels: dict[str, list[dict]] = {}
        self._decks: dict[str, list[dict]] = {}
        self._index: dict[str, tuple[str, dict]] = {}  # kanji -> (level, record)

    # ------------------------------------------------------------- loading

    def available(self) -> list[str]:
        """Levels that actually have a data file."""
        return sorted(p.name.split(".")[0] for p in self.data_dir.glob("*.json.gz"))

    def load(self, level: str) -> list[dict]:
        """Records for one level, read from disk at most once."""
        if level not in self._levels:
            path = self.data_dir / f"{level}.json.gz"
            if not path.exists():
                raise DataNotBuilt(
                    f"no data for {level} ({path} is missing). "
                    "Run: python tools/build_data.py"
                )
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            records = payload["kanji"]
            self._levels[level] = records
            for record in records:
                self._index.setdefault(record["k"], (level, record))
        return self._levels[level]

    def find(self, kanji: str) -> tuple[str, dict] | None:
        """Locate a kanji in any level, loading levels until it turns up."""
        if kanji in self._index:
            return self._index[kanji]
        for level in self.available():
            self.load(level)
            if kanji in self._index:
                return self._index[kanji]
        return None

    # ---------------------------------------------------------------- cards

    def next_card(self, level: str, kanji: str | None = None) -> KanjiCard:
        if kanji:
            found = self.find(kanji)
            if found is None:
                raise KeyError(kanji)
            return self._card(*found)

        records = self.load(level)
        deck = self._decks.get(level)
        if not deck:  # empty or exhausted: deal a fresh shuffled deck
            deck = list(records)
            self._rng.shuffle(deck)
            self._decks[level] = deck
        return self._card(level, deck.pop())

    @staticmethod
    def _card(level: str, record: dict) -> KanjiCard:
        words, sentences = [], []
        for raw in record.get("w", []):
            words.append(
                Word(
                    text=raw["t"],
                    reading=raw["r"],
                    meaning=raw.get("m", ""),
                    furigana=tuple((ruby, rt) for ruby, rt in raw.get("f", [])),
                )
            )
            example = raw.get("s")
            if example:
                sentences.append(
                    Sentence(
                        text=example["t"],
                        furigana=tuple((text, rt) for text, rt in example.get("f", [])),
                        translations=dict(example.get("tr", {})),
                    )
                )

        return KanjiCard(
            kanji=record["k"],
            level=level,
            meanings=tuple(record.get("m", ())),
            on_readings=tuple(record.get("on", ())),
            kun_readings=tuple(record.get("kun", ())),
            words=tuple(words),
            sentences=tuple(sentences),
            strokes=record.get("st", 0),
        )
