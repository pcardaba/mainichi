"""Stroke order outlines, and the geometry needed to animate them.

The data comes from KanjiVG as SVG path strings inside a 109x109 box. Tk
cannot draw an SVG path, so each one is flattened into a polyline here. That
is done at display time rather than at build time: it keeps the shipped data
smaller, and lets a big note be drawn with more detail than a small one.

Only the commands KanjiVG actually uses are supported: M/m, C/c and S/s. It
contains no arcs, no quadratics and no closed paths.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "strokes.json.gz"

# KanjiVG draws every kanji inside this square, with a pen 3 units wide.
VIEWBOX = 109.0
PEN_WIDTH = 3.0

Point = tuple[float, float]

_TOKEN = re.compile(r"([MmCcSsLlZz])|(-?\d*\.?\d+)")


def _commands(path: str) -> list[tuple[str, list[float]]]:
    """Split an SVG path into (letter, numbers) pairs."""
    out: list[tuple[str, list[float]]] = []
    for letter, number in _TOKEN.findall(path):
        if letter:
            out.append((letter, []))
        elif out:
            out[-1][1].append(float(number))
    return out


def flatten(path: str, detail: float = 2.0) -> list[Point]:
    """Turn one stroke into a polyline.

    ``detail`` is roughly the length of a segment in the 109 unit box, so a
    smaller value gives a smoother curve and more points.
    """
    points: list[Point] = []
    cursor: Point = (0.0, 0.0)
    last_control: Point | None = None

    for letter, numbers in _commands(path):
        if letter in "Mm":
            if len(numbers) < 2:
                continue
            x, y = numbers[0], numbers[1]
            if letter == "m":
                x, y = cursor[0] + x, cursor[1] + y
            cursor = (x, y)
            points.append(cursor)
            last_control = None
            continue
        if letter in "Ll":
            for i in range(0, len(numbers) - 1, 2):
                x, y = numbers[i], numbers[i + 1]
                if letter == "l":
                    x, y = cursor[0] + x, cursor[1] + y
                cursor = (x, y)
                points.append(cursor)
            last_control = None
            continue
        if letter not in "CcSs":
            continue

        step = 6 if letter in "Cc" else 4
        for i in range(0, len(numbers) - step + 1, step):
            chunk = numbers[i : i + step]
            if letter in "Cc":
                x1, y1, x2, y2, x, y = chunk
                if letter == "c":
                    x1, y1 = cursor[0] + x1, cursor[1] + y1
                    x2, y2 = cursor[0] + x2, cursor[1] + y2
                    x, y = cursor[0] + x, cursor[1] + y
            else:
                x2, y2, x, y = chunk
                if letter == "s":
                    x2, y2 = cursor[0] + x2, cursor[1] + y2
                    x, y = cursor[0] + x, cursor[1] + y
                # A smooth curve mirrors the previous control point.
                if last_control is not None:
                    x1 = 2 * cursor[0] - last_control[0]
                    y1 = 2 * cursor[1] - last_control[1]
                else:
                    x1, y1 = cursor

            span = (
                math.dist(cursor, (x1, y1))
                + math.dist((x1, y1), (x2, y2))
                + math.dist((x2, y2), (x, y))
            )
            steps = max(2, min(32, int(span / max(0.5, detail))))
            for s in range(1, steps + 1):
                t = s / steps
                u = 1 - t
                points.append((
                    u * u * u * cursor[0] + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x,
                    u * u * u * cursor[1] + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y,
                ))
            last_control = (x2, y2)
            cursor = (x, y)

    # Consecutive duplicates would stall the animation without drawing.
    cleaned: list[Point] = []
    for point in points:
        if not cleaned or math.dist(cleaned[-1], point) > 0.01:
            cleaned.append(point)
    return cleaned


class StrokeLibrary:
    """Lazily reads the stroke file, and remembers what it has flattened."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_FILE
        self._raw: dict[str, list[str]] | None = None
        self._cache: dict[str, list[list[Point]]] = {}

    @property
    def available(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, list[str]]:
        if self._raw is None:
            if not self.path.exists():
                self._raw = {}
            else:
                with gzip.open(self.path, "rt", encoding="utf-8") as handle:
                    self._raw = json.load(handle).get("kanji", {})
        return self._raw

    def strokes(self, kanji: str, detail: float = 2.0) -> list[list[Point]]:
        """Polylines for each stroke, in writing order, in the 109 unit box."""
        if kanji not in self._cache:
            self._cache[kanji] = [flatten(p, detail) for p in self._load().get(kanji, [])]
        return self._cache[kanji]

    def has(self, kanji: str) -> bool:
        return bool(self._load().get(kanji))
