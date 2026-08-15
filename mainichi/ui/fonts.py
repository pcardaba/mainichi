"""Locating a font that can actually draw kanji.

Tk gives no direct way to ask "does this family cover CJK?", so we work
from a per-platform candidate list and, on Linux, fall back to asking
fontconfig for anything that claims Japanese coverage.
"""

from __future__ import annotations

import subprocess
import sys
import tkinter.font as tkfont

# Ordered by preference: good CJK faces first, then the usual system ones.
_JP_CANDIDATES: tuple[str, ...] = (
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "Source Han Sans JP",
    "Yu Gothic UI",
    "Yu Gothic",
    "Meiryo",
    "MS Gothic",
    "Hiragino Sans",
    "Hiragino Kaku Gothic ProN",
    "TakaoPGothic",
    "IPAPGothic",
    "IPAGothic",
    "VL PGothic",
    "Droid Sans Fallback",
    "Noto Sans CJK SC",
    "Sazanami Gothic",
)

_UI_CANDIDATES: tuple[str, ...] = (
    "Segoe UI",
    "Inter",
    "Cantarell",
    "DejaVu Sans",
    "Helvetica",
)


def _fontconfig_japanese() -> list[str]:
    """Ask fontconfig for families covering Japanese (Linux/BSD only)."""
    if sys.platform.startswith(("win", "darwin")):
        return []
    try:
        out = subprocess.run(
            ["fc-list", ":lang=ja", "family"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    families: list[str] = []
    for line in out.splitlines():
        # fc-list prints comma separated aliases, e.g. "Noto Sans CJK JP,Noto Sans CJK JP Regular"
        for alias in line.split(","):
            alias = alias.strip()
            if alias and alias not in families:
                families.append(alias)
    return families


class FontBook:
    """Resolves the families once and hands out sized font tuples."""

    def __init__(self) -> None:
        self._measurable: dict[tuple[str, int, str], tkfont.Font] = {}
        available = set(tkfont.families())
        self.jp_family = self._first_available(_JP_CANDIDATES, available)
        self.jp_is_guess = self.jp_family is None

        if self.jp_family is None:
            self.jp_family = self._first_available(_fontconfig_japanese(), available)

        if self.jp_family is None:
            # Nothing found: Tk will substitute glyphs and kanji may show as
            # empty boxes. The app still runs; app.py reports this once.
            self.jp_family = "TkDefaultFont"
            self.jp_missing = True
        else:
            self.jp_missing = False

        self.ui_family = self._first_available(_UI_CANDIDATES, available) or "TkDefaultFont"

    @staticmethod
    def _first_available(names, available: set[str]) -> str | None:
        for name in names:
            if name in available:
                return name
        return None

    def jp(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        """Japanese capable font at ``size`` pixels-ish (Tk points)."""
        return (self.jp_family, max(6, size), weight)

    def ui(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        """Latin UI font for labels, hints and scaffolding text."""
        return (self.ui_family, max(6, size), weight)

    def measurable(self, spec: tuple[str, int, str]) -> tkfont.Font:
        """A real Font object, needed to place ruby over the right character."""
        if spec not in self._measurable:
            family, size, weight = spec
            self._measurable[spec] = tkfont.Font(family=family, size=size, weight=weight)
        return self._measurable[spec]
