"""Laying out Japanese text with furigana over the right characters.

Tk can wrap a plain string on its own, but not with ruby sitting above
individual characters, so the line breaking is done here: an annotated group
is one unbreakable cell, plain kana may break anywhere.

Both the post-it and the hover bubble draw through this, so a word looks the
same magnified as it does on the paper.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field

# Japanese line breaking: these characters may not begin a line (kinsoku).
NO_LINE_START = "。、）」』？！ぁぃぅぇぉっゃゅょゎヽヾー・"

Segments = "list[tuple[str, str]]"


@dataclass(slots=True)
class Layout:
    """What was drawn, and where."""

    bottom: float  # y just below the last line
    width: float  # widest line actually used
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    items: list[int] = field(default_factory=list)


def draw(
    canvas: tk.Canvas,
    fonts,
    segments,
    left: float,
    top: float,
    max_width: float,
    size: int,
    ink: str,
    ink_soft: str,
    show_ruby: bool = True,
    ruby_size: int | None = None,
) -> Layout:
    """Draw ``segments`` as furigana'd text, wrapping within ``max_width``."""
    main_spec = fonts.jp(size)
    ruby_spec = fonts.jp(ruby_size or max(6, int(size * 0.52)))
    main = fonts.measurable(main_spec)
    ruby = fonts.measurable(ruby_spec)

    show_ruby = show_ruby and any(rt for _, rt in segments)
    ruby_height = ruby.metrics("linespace") if show_ruby else 0
    line_height = ruby_height + main.metrics("linespace")

    cells: list[tuple[str, str, float]] = []
    for text, rt in segments:
        if rt and show_ruby:
            # The reading is often wider than the character it sits on.
            cells.append((text, rt, max(main.measure(text), ruby.measure(rt) + 2)))
        elif rt:
            cells.append((text, "", main.measure(text)))
        else:
            for char in text:
                cells.append((char, "", main.measure(char)))

    layout = Layout(bottom=top, width=0.0)
    x, y = left, top
    line_start = left
    for text, rt, width in cells:
        if x + width > left + max_width and x > left and text[0] not in NO_LINE_START:
            layout.boxes.append((line_start, y, x, y + line_height))
            layout.width = max(layout.width, x - line_start)
            x = left
            y += line_height
        if rt:
            layout.items.append(
                canvas.create_text(
                    x + width / 2, y, text=rt, anchor="n", fill=ink_soft, font=ruby_spec
                )
            )
        layout.items.append(
            canvas.create_text(
                x + width / 2, y + ruby_height, text=text, anchor="n", fill=ink, font=main_spec
            )
        )
        x += width
    if x > line_start:
        layout.boxes.append((line_start, y, x, y + line_height))
        layout.width = max(layout.width, x - line_start)
    layout.bottom = y + line_height
    return layout


def measure(fonts, segments, size: int, ruby_size: int | None = None) -> tuple[float, float]:
    """Width and height of one unwrapped line, without drawing anything."""
    main = fonts.measurable(fonts.jp(size))
    ruby = fonts.measurable(fonts.jp(ruby_size or max(6, int(size * 0.52))))
    has_ruby = any(rt for _, rt in segments)
    width = sum(
        max(main.measure(text), ruby.measure(rt) + 2) if rt else main.measure(text)
        for text, rt in segments
    )
    height = (ruby.metrics("linespace") if has_ruby else 0) + main.metrics("linespace")
    return width, height
