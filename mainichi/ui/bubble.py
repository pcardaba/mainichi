"""The hover bubble: a word shown larger, so its furigana can be read.

A post-it parked in a corner of the screen is often too small for the
furigana over its example words. Resting the pointer on a word pops this up
next to it, with the reading at a comfortable size, and no need to resize
the note.

It is a window of its own rather than something drawn on the note, so that
it can spill outside a small post-it instead of being clipped by it.
"""

from __future__ import annotations

import sys
import tkinter as tk

from mainichi.ui import ruby

# Big enough to read the furigana at a glance. The main text follows from
# it: the reading is drawn at roughly half the size of the word.
RUBY_SIZE = 11
TEXT_SIZE = 21
PADDING = 8
MAX_WIDTH = 380  # a long sentence wraps rather than crossing the screen
POINTER_GAP = 14


class Bubble:
    """A single reusable popup window, shared by one post-it."""

    def __init__(self, master: tk.Misc, fonts) -> None:
        self.fonts = fonts
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self._make_borderless()
        self.canvas = tk.Canvas(self.win, highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True)
        self._visible = False

    def _make_borderless(self) -> None:
        """No decorations, and above the note it belongs to.

        Unlike the note, this window is deliberately taken out of the window
        manager's hands: a tooltip should never be decorated, focused, or
        stacked below anything. Asking for a tooltip window *type* instead
        was not enough, some window managers still put a title bar on it.
        """
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-type", "tooltip")  # a hint, where supported
        except tk.TclError:  # pragma: no cover - unusual X11 Tk
            pass
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:  # pragma: no cover - window manager dependent
            pass

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self, segments, palette, x: int, y: int) -> None:
        """Draw ``segments`` and place the bubble near screen point (x, y)."""
        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(bg=palette.paper)

        width, _height = ruby.measure(self.fonts, segments, TEXT_SIZE, RUBY_SIZE)
        wrap = min(MAX_WIDTH, max(40.0, width))
        layout = ruby.draw(
            canvas,
            self.fonts,
            segments,
            PADDING,
            PADDING,
            wrap,
            TEXT_SIZE,
            ink=palette.ink,
            ink_soft=palette.ink_soft,
            ruby_size=RUBY_SIZE,
        )
        box_w = int(layout.width + 2 * PADDING)
        box_h = int(layout.bottom - PADDING + 2 * PADDING)
        canvas.create_rectangle(
            0, 0, box_w - 1, box_h - 1, outline=palette.fold, width=1
        )

        # Keep it on screen: flip to the other side of the pointer if needed.
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        left = x + POINTER_GAP
        top = y + POINTER_GAP
        if left + box_w > screen_w:
            left = max(0, x - box_w - POINTER_GAP)
        if top + box_h > screen_h:
            top = max(0, y - box_h - POINTER_GAP)

        self.win.geometry(f"{box_w}x{box_h}+{int(left)}+{int(top)}")
        if not self._visible:
            self.win.deiconify()
            self._visible = True
        self.win.lift()

    def hide(self) -> None:
        if self._visible:
            self._visible = False
            try:
                self.win.withdraw()
            except tk.TclError:  # pragma: no cover - destroyed with its parent
                pass

    def destroy(self) -> None:
        # The bubble belongs to the note, so it may already have been taken
        # down with it by the time this runs.
        self.hide()
        try:
            self.win.destroy()
        except tk.TclError:  # pragma: no cover - already gone
            pass
