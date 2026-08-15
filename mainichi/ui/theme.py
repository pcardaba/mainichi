"""Post-it colour palettes.

A palette is deliberately tiny: paper, a slightly darker fold for the
dog-eared corner, ink for the main text and a softer ink for secondary
text such as furigana or translations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    label: str
    paper: str
    fold: str
    ink: str
    ink_soft: str
    guide: str  # scaffolding / placeholder outlines
    select: str  # background of selected text


PALETTES: dict[str, Palette] = {
    p.name: p
    for p in (
        Palette("yellow", "Yellow", "#fdf3a7", "#e8dc84", "#332f16", "#7a7247", "#c9bd6a", "#e3ce5d"),
        Palette("pink", "Pink", "#ffd1dc", "#efb6c4", "#3a1f27", "#8a5e6b", "#dda2b2", "#efa3b8"),
        Palette("green", "Green", "#ccf2c8", "#aedbaa", "#1e3320", "#5c7a5e", "#95c493", "#9fd79a"),
        Palette("blue", "Blue", "#cfe6fb", "#b0cfea", "#17293a", "#566e83", "#93b8d6", "#9cc8e9"),
        Palette("orange", "Orange", "#ffdcb0", "#eec392", "#3b2713", "#836444", "#d9ac79", "#efbe86"),
        Palette("grey", "Grey", "#e6e6e6", "#cccccc", "#242424", "#666666", "#b3b3b3", "#c2c2c2"),
    )
}

DEFAULT_PALETTE = "yellow"


def get_palette(name: str) -> Palette:
    """Return the named palette, falling back to the default one."""
    return PALETTES.get(name, PALETTES[DEFAULT_PALETTE])
