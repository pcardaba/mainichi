"""The post-it window.

A borderless always-on-top Toplevel holding a single Canvas. Everything is
drawn by hand on that canvas: there are no widgets, no menus and no buttons
on the paper itself, exactly like a real post-it.

Interaction
-----------
* click / drag on text     -> select a word, a sentence, or a run of them
* drag the blank paper     -> move the note
* drag the folded corner   -> resize the note
* double click             -> flip recto/verso
* right click              -> context menu
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mainichi.config import LANGUAGES, MIN_SIZE, PostItOptions
from mainichi.content import KanjiCard
from mainichi.ui.theme import PALETTES, get_palette

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mainichi.app import MainichiApp

# Reference size the proportional layout was designed against.
_BASE_W, _BASE_H = 300, 340

RECTO, VERSO = "recto", "verso"


@dataclass(slots=True)
class _Region:
    """A stretch of text on the paper that can be selected and copied.

    Selection works on whole words and sentences rather than on individual
    characters: that is the unit worth copying out of a post-it, and it stays
    easy to hit on a note a few hundred pixels wide.
    """

    text: str
    boxes: list[tuple[float, float, float, float]]  # one per line of text

    def hit(self, x: float, y: float) -> bool:
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in self.boxes)


class PostItWindow:
    """One post-it stuck on the desktop."""

    MIN_W, MIN_H = MIN_SIZE
    CLICK_SLOP = 4  # px of movement still counted as a click, not a drag

    def __init__(
        self,
        app: "MainichiApp",
        card: KanjiCard,
        options: PostItOptions,
        geometry: tuple[int, int, int, int],
    ) -> None:
        self.app = app
        self.card = card
        self.options = options
        self.face = RECTO

        self._drag_origin: tuple[int, int] | None = None
        self._resize_origin: tuple[int, int, int, int] | None = None
        self._moved = False

        # Text selection. Regions are rebuilt on every redraw, in a stable
        # order, so the selection survives a resize or a colour change.
        self._regions: list[_Region] = []
        self._selection: set[int] = set()
        self._select_anchor: int | None = None
        self._items: list[int] = []  # items drawn since the last region mark

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("mainichi")

        w, h, x, y = geometry
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.minsize(self.MIN_W, self.MIN_H)

        self._unmanaged = False  # True when the window manager ignores us
        if app.config.decorated:
            self.win.resizable(True, True)
        else:
            self._make_borderless()

        self.canvas = tk.Canvas(
            self.win,
            highlightthickness=0,
            borderwidth=0,
            bg=self.palette.paper,
            cursor="hand2" if not app.config.decorated else "",
        )
        self.canvas.pack(fill="both", expand=True)

        self._build_menu()
        self._bind_events()
        self._apply_topmost()

        self.win.deiconify()
        self.redraw()

    def _make_borderless(self) -> None:
        """Drop the title bar, while staying under the window manager.

        The obvious way, ``overrideredirect(True)``, takes the window out of
        the window manager's hands entirely. On X11 that also puts it above
        every ordinary window permanently, and no ``-topmost`` setting can
        bring it back down: "always on top" could be switched off in the menu
        but nothing happened.

        A splash window is undecorated *and* managed, so the window manager
        stacks it like any other window and honours the request. Windows and
        macOS have no such window type, but there ``overrideredirect`` does
        not break stacking, so it is used as before.
        """
        if sys.platform.startswith("win") or sys.platform == "darwin":
            self.win.overrideredirect(True)
            self._unmanaged = True
            return
        try:
            self.win.attributes("-type", "splash")
        except tk.TclError:  # pragma: no cover - very old or unusual X11 Tk
            self.win.overrideredirect(True)
            self._unmanaged = True

    # ------------------------------------------------------------------ state

    @property
    def palette(self):
        return get_palette(self.options.palette)

    def geometry_tuple(self) -> tuple[int, int, int, int]:
        self.win.update_idletasks()
        return (
            self.win.winfo_width(),
            self.win.winfo_height(),
            self.win.winfo_x(),
            self.win.winfo_y(),
        )

    # ----------------------------------------------------------------- wiring

    def _bind_events(self) -> None:
        c = self.canvas
        c.bind("<Button-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", self._on_double_click)
        c.bind("<Button-3>", self._on_context_menu)
        c.bind("<Configure>", lambda _e: self.redraw())
        c.bind("<Motion>", self._on_hover)

        w = self.win
        w.bind("<space>", lambda _e: self.flip())
        w.bind("<Control-c>", self.copy_selection)
        w.bind("<Control-C>", self.copy_selection)
        w.bind("<Control-a>", lambda _e: self.select_all())
        w.bind("<Control-A>", lambda _e: self.select_all())
        w.bind("<Control-n>", lambda _e: self.app.spawn_postit())
        w.bind("<Control-w>", lambda _e: self.close())
        w.bind("<Control-q>", lambda _e: self.app.quit())
        # Escape only ever dismisses the context menu. It must not close the
        # note: an unposted menu would otherwise take the whole post-it away.
        w.bind("<Escape>", self._dismiss_menu)
        w.protocol("WM_DELETE_WINDOW", self.close)

    def _build_menu(self) -> None:
        """Right-click menu. Items with no engine behind them yet are disabled."""
        self._var_on_top = tk.BooleanVar(self.win, self.options.always_on_top)
        self._var_furigana = tk.BooleanVar(self.win, self.options.show_furigana)
        self._var_translation = tk.BooleanVar(self.win, self.options.show_translation)
        self._var_language = tk.StringVar(self.win, self.options.language)

        m = tk.Menu(self.win, tearoff=0)
        m.add_checkbutton(label="Always on top", variable=self._var_on_top, command=self._toggle_on_top)
        m.add_command(label="Traces", state="disabled")  # stroke animation, later
        m.add_checkbutton(label="Furigana", variable=self._var_furigana, command=self._toggle_furigana)
        m.add_checkbutton(label="Translation", variable=self._var_translation, command=self._toggle_translation)
        m.add_separator()
        m.add_command(label="Copy", accelerator="Ctrl+C", command=self.copy_selection)
        m.add_command(label="Select all", accelerator="Ctrl+A", command=self.select_all)
        m.add_command(label="Flip", accelerator="Double click", command=self.flip)
        m.add_command(label="Next kanji", command=self.next_card)

        languages = tk.Menu(m, tearoff=0)
        for code, label in LANGUAGES.items():
            languages.add_radiobutton(
                label=label,
                value=code,
                variable=self._var_language,
                command=self._change_language,
            )
        m.add_cascade(label="Language", menu=languages)

        colours = tk.Menu(m, tearoff=0)
        for pal in PALETTES.values():
            colours.add_command(
                label=pal.label,
                background=pal.paper,
                activebackground=pal.fold,
                command=lambda name=pal.name: self.set_palette(name),
            )
        m.add_cascade(label="Background colour", menu=colours)

        m.add_separator()
        m.add_command(label="New post-it", accelerator="Ctrl+N", command=self.app.spawn_postit)
        m.add_command(label="Close this post-it", accelerator="Ctrl+W", command=self.close)
        m.add_command(label="Quit mainichi", accelerator="Ctrl+Q", command=self.app.quit)

        # Escape closes the menu wherever the keyboard focus happens to be,
        # and the grab is dropped as soon as the menu is off screen.
        for menu in (m, colours, languages):
            menu.bind("<Escape>", self._dismiss_menu)
            menu.bind("<Unmap>", lambda _e: m.grab_release())
        self.menu = m

    # -------------------------------------------------------------- behaviour

    def _fold_size(self) -> int:
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        return max(16, int(min(w, h) * 0.09))

    def _in_fold(self, x: int, y: int) -> bool:
        """True if (x, y) is inside the folded corner used as resize grip."""
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        fold = self._fold_size()
        return x >= w - fold and y >= h - fold

    def _on_hover(self, event: tk.Event) -> None:
        if not self.app.config.decorated and self._in_fold(event.x, event.y):
            self.canvas.configure(cursor="bottom_right_corner")
        elif self._region_at(event.x, event.y) is not None:
            self.canvas.configure(cursor="xterm")  # this text can be selected
        else:
            self.canvas.configure(cursor="" if self.app.config.decorated else "hand2")

    def _on_double_click(self, _event: tk.Event) -> str:
        """Flip the note.

        Flipping used to be a single left click, but that made selecting
        text impossible: every attempt to select turned the note over.
        """
        self.flip()
        return "break"

    def _menu_is_open(self) -> bool:
        try:
            return bool(self.menu.winfo_ismapped())
        except tk.TclError:  # pragma: no cover - menu already gone
            return False

    def _on_press(self, event: tk.Event) -> str | None:
        # A click while the menu is up only dismisses it: it should not also
        # start a drag or change the selection.
        if self._menu_is_open():
            self._dismiss_menu()
            return "break"
        # Clicking a note brings it forward, which matters once it is no
        # longer pinned on top and something else is covering it.
        self.win.lift()
        self.win.focus_force()
        self._moved = False
        self._resize_origin = self._drag_origin = None
        self._select_anchor = None

        w, h, x, y = self.geometry_tuple()
        if self._in_fold(event.x, event.y) and not self.app.config.decorated:
            self._resize_origin = (event.x_root, event.y_root, w, h)
            return None

        hit = self._region_at(event.x, event.y)
        if hit is not None:
            # Pressing on text starts a selection; the note is moved by
            # dragging the blank paper around it.
            self._select_anchor = hit
            self._selection = {hit}
            self.redraw()
            return None

        if self._selection:
            self.clear_selection()
        self._drag_origin = (event.x_root - x, event.y_root - y)
        return None

    def _on_motion(self, event: tk.Event) -> None:
        if self._select_anchor is not None:
            # Extend the selection over every region between the one the
            # drag started on and the one under the pointer.
            hit = self._region_at(event.x, event.y)
            if hit is not None:
                low, high = sorted((self._select_anchor, hit))
                wanted = set(range(low, high + 1))
                if wanted != self._selection:
                    self._selection = wanted
                    self.redraw()
            return
        if self._resize_origin is not None:
            sx, sy, sw, sh = self._resize_origin
            new_w = max(self.MIN_W, sw + (event.x_root - sx))
            new_h = max(self.MIN_H, sh + (event.y_root - sy))
            if (new_w, new_h) != (sw, sh):
                self._moved = True
            self.win.geometry(f"{new_w}x{new_h}")
        elif self._drag_origin is not None and not self.app.config.decorated:
            ox, oy = self._drag_origin
            nx, ny = event.x_root - ox, event.y_root - oy
            if abs(nx - self.win.winfo_x()) > self.CLICK_SLOP or abs(ny - self.win.winfo_y()) > self.CLICK_SLOP:
                self._moved = True
            self.win.geometry(f"+{nx}+{ny}")

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_origin = self._resize_origin = None
        self._select_anchor = None
        self._moved = False

    def _on_context_menu(self, event: tk.Event) -> None:
        """Post the context menu under the pointer, over the selection.

        Right-clicking on text that is not selected selects it first, so
        that "select, right click, Copy" works in one gesture.

        The grab that ``tk_popup`` takes is deliberately kept: it is what
        makes a click anywhere outside the menu dismiss it. Releasing it
        straight away (the usual Tkinter snippet) leaves the menu stuck on
        screen. It is released again when the menu unmaps, and by
        :meth:`_dismiss_menu`.

        The keyboard focus is taken first: a borderless window is never given
        the focus by the window manager, so otherwise the Escape key goes to
        whichever window happens to hold the focus instead of to the menu.
        """
        hit = self._region_at(event.x, event.y)
        if hit is not None and hit not in self._selection:
            self._selection = {hit}
            self.redraw()
        self.menu.entryconfigure(
            "Copy", state="normal" if self._selection else "disabled"
        )
        self.win.focus_force()
        self.menu.tk_popup(event.x_root, event.y_root)
        self.menu.focus_set()

    def _dismiss_menu(self, _event: tk.Event | None = None) -> str:
        """Take the context menu down; harmless when none is posted."""
        try:
            self.menu.unpost()
            self.menu.grab_release()
        except tk.TclError:  # pragma: no cover - menu already gone
            pass
        return "break"

    def flip(self) -> None:
        self.face = VERSO if self.face == RECTO else RECTO
        self._selection.clear()  # the other side has entirely different text
        self._select_anchor = None
        self.redraw()

    def next_card(self) -> None:
        """Move on to another kanji of the level currently being shown.

        A note launched with an explicit ``--kanji`` continues with random
        kanji from that kanji's own level: asking for the next one and being
        given the same character again would be useless.
        """
        level = self.card.level or self.app.config.level
        self.card = self.app.provider.next_card(level)
        self.face = RECTO
        self._selection.clear()
        self._select_anchor = None
        self.redraw()

    def set_palette(self, name: str) -> None:
        self.options.palette = name
        self.canvas.configure(bg=self.palette.paper)
        self.redraw()

    def _toggle_on_top(self) -> None:
        self.options.always_on_top = self._var_on_top.get()
        self._apply_topmost()

    def _toggle_furigana(self) -> None:
        self.options.show_furigana = self._var_furigana.get()
        self.redraw()

    def _toggle_translation(self) -> None:
        self.options.show_translation = self._var_translation.get()
        self.redraw()

    def _change_language(self) -> None:
        self.options.language = self._var_language.get()
        self.options.show_translation = True  # picking a language implies wanting it
        self._var_translation.set(True)
        self.redraw()

    def _apply_topmost(self) -> None:
        on_top = self.options.always_on_top
        try:
            if self.win.winfo_viewable() and self._unmanaged:
                # An unmanaged window ignores a -topmost change once it is
                # mapped, so unmap it around the change. The geometry is
                # restored right after.
                geometry = self.win.geometry()
                self.win.withdraw()
                self.win.attributes("-topmost", on_top)
                self.win.deiconify()
                self.win.geometry(geometry)
            else:
                self.win.attributes("-topmost", on_top)
            if on_top:
                self.win.lift()
        except tk.TclError:  # pragma: no cover - window manager dependent
            pass

    def close(self) -> None:
        self.app.forget_postit(self)
        self.win.destroy()

    # -------------------------------------------------------------- selection

    def _text(self, *args, **kwargs) -> int:
        """create_text that also records the item for the region being built."""
        item = self.canvas.create_text(*args, **kwargs)
        self._items.append(item)
        return item

    def _mark(self) -> None:
        """Start collecting the items that will make up the next region."""
        self._items = []

    def _region(self, text: str, boxes: list[tuple[float, float, float, float]] | None = None) -> None:
        """Close the current region, covering everything drawn since _mark."""
        if not text:
            self._items = []
            return
        if boxes is None:
            spans = [self.canvas.bbox(item) for item in self._items]
            spans = [b for b in spans if b]
            if not spans:
                self._items = []
                return
            boxes = [(
                min(b[0] for b in spans),
                min(b[1] for b in spans),
                max(b[2] for b in spans),
                max(b[3] for b in spans),
            )]
        self._regions.append(_Region(text=text, boxes=boxes))
        self._items = []

    def _draw_selection(self) -> None:
        """Paint the highlight behind every selected region."""
        pal = self.palette
        for index in sorted(self._selection):
            if index >= len(self._regions):
                continue
            for x0, y0, x1, y1 in self._regions[index].boxes:
                rect = self.canvas.create_rectangle(
                    x0 - 2, y0 - 1, x1 + 2, y1 + 1,
                    fill=pal.select, outline="",
                )
                self.canvas.tag_lower(rect)  # behind the text it highlights

    def _region_at(self, x: float, y: float) -> int | None:
        for index, region in enumerate(self._regions):
            if region.hit(x, y):
                return index
        return None

    def selected_text(self) -> str:
        """The selection, in the order it appears on the paper.

        Never includes furigana: a region holds the text as written (日本),
        not the reading drawn above it (にほん), so what gets pasted into
        another application is the word or sentence itself.
        """
        return "\n".join(
            self._regions[i].text for i in sorted(self._selection) if i < len(self._regions)
        )

    def clear_selection(self) -> None:
        if self._selection:
            self._selection.clear()
            self._select_anchor = None
            self.redraw()

    def select_all(self) -> str:
        self._selection = set(range(len(self._regions)))
        self.redraw()
        return "break"

    def copy_selection(self, _event: tk.Event | None = None) -> str:
        """Put the selection on the clipboard, for pasting anywhere else."""
        text = self.selected_text()
        if text:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
        return "break"

    # ---------------------------------------------------------------- drawing

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w <= 1 or h <= 1:  # not mapped yet
            return

        pal = self.palette
        c.configure(bg=pal.paper)
        scale = min(w / _BASE_W, h / _BASE_H)

        self._regions = []
        self._items = []
        self._draw_paper(w, h)
        if self.face == RECTO:
            self._draw_recto(w, h, scale)
        else:
            self._draw_verso(w, h, scale)
        self._draw_fold(w, h)
        self._draw_selection()

    def _draw_paper(self, w: int, h: int) -> None:
        """Paper edge plus the glued strip along the top."""
        pal = self.palette
        c = self.canvas
        c.create_rectangle(0, 0, w - 1, h - 1, outline=pal.fold, width=1)
        c.create_rectangle(0, 0, w, max(3, int(h * 0.015)), fill=pal.fold, outline="")

    def _draw_fold(self, w: int, h: int) -> None:
        """Dog-eared bottom right corner, which doubles as the resize grip."""
        pal = self.palette
        fold = self._fold_size()
        self.canvas.create_polygon(
            w - fold, h, w, h - fold, w, h,
            fill=pal.fold,
            outline=pal.guide,
        )

    def _zone(self, x0, y0, x1, y1, label: str, scale: float) -> None:
        """Dashed placeholder box: scaffolding until real content exists."""
        pal = self.palette
        c = self.canvas
        c.create_rectangle(x0, y0, x1, y1, outline=pal.guide, dash=(4, 3))
        c.create_text(
            (x0 + x1) / 2,
            (y0 + y1) / 2,
            text=label,
            fill=pal.guide,
            font=self.app.fonts.ui(max(7, int(9 * scale))),
            width=max(20, int(x1 - x0 - 8)),
            justify="center",
        )

    def _draw_header(self, w: int, h: int, scale: float, right_text: str) -> None:
        pal = self.palette
        pad = max(8, int(w * 0.05))
        top = max(8, int(h * 0.035))
        self.canvas.create_text(
            pad, top,
            text=self.card.level or self.app.config.level,
            anchor="nw",
            fill=pal.ink_soft,
            font=self.app.fonts.ui(max(8, int(10 * scale)), "bold"),
        )
        self.canvas.create_text(
            w - pad, top,
            text=right_text,
            anchor="ne",
            fill=pal.ink_soft,
            font=self.app.fonts.ui(max(7, int(9 * scale))),
        )

    def _draw_footer(self, w: int, h: int, scale: float, text: str) -> None:
        self.canvas.create_text(
            w / 2,
            h - max(10, int(h * 0.045)),
            text=text,
            fill=self.palette.ink_soft,
            font=self.app.fonts.ui(max(7, int(8 * scale))),
        )

    def _draw_recto(self, w: int, h: int, scale: float) -> None:
        """Front: the kanji, big, with the common words underneath."""
        pal = self.palette
        c = self.canvas
        pad = max(8, int(w * 0.05))
        self._draw_header(w, h, scale, "recto")

        kanji_box = (pad, int(h * 0.12), w - pad, int(h * 0.56))
        if self.card.is_placeholder:
            self._zone(*kanji_box, "kanji", scale)
        else:
            self._mark()
            self._text(
                w / 2,
                (kanji_box[1] + kanji_box[3]) / 2,
                text=self.card.kanji,
                fill=pal.ink,
                font=self.app.fonts.jp(max(24, int((kanji_box[3] - kanji_box[1]) * 0.82))),
            )
            self._region(self.card.kanji)

        # Words row: one slot per reading, most common on the left.
        row_top, row_bottom = int(h * 0.62), int(h * 0.87)
        if not self.card.is_placeholder and not self.card.words:
            # A handful of kanji (mostly used only in names) have no common
            # vocabulary: show the readings rather than an empty note.
            self._draw_readings(w, h, scale, row_top, row_bottom)
        else:
            slots = max(1, len(self.card.words) or 3)
            gap = max(4, int(6 * scale))
            slot_w = (w - 2 * pad - gap * (slots - 1)) / slots
            for i in range(slots):
                x0 = pad + i * (slot_w + gap)
                x1 = x0 + slot_w
                if self.card.is_placeholder:
                    self._zone(x0, row_top, x1, row_bottom, "word", scale)
                else:
                    self._draw_word(
                        self.card.words[i],
                        (x0 + x1) / 2,
                        row_top,
                        slot_w,
                        row_bottom - row_top,
                        scale,
                    )

        self._draw_footer(w, h, scale, "double-click to flip · right-click for options")

    def _draw_word(
        self,
        word,
        centre_x: float,
        top_y: float,
        max_width: float,
        max_height: float,
        scale: float,
    ) -> None:
        """Draw one word with its furigana sitting over the right characters.

        ``word.furigana`` aligns each character with its reading, so 日曜日
        gets にち above 日, よう above 曜 and び above the second 日, instead
        of the whole reading floating over the middle of the word.
        """
        pal = self.palette
        c = self.canvas
        fonts = self.app.fonts
        segments = word.furigana or ((word.text, word.reading),)
        show_ruby = self.options.show_furigana and any(rt for _, rt in segments)

        # Shrink until the word fits its slot: a four character compound in a
        # narrow note would otherwise run into its neighbour.
        size = max(9, int(17 * scale))
        while size > 7:
            main = fonts.measurable(fonts.jp(size))
            widths = [main.measure(ruby) for ruby, _ in segments]
            if sum(widths) <= max_width:
                break
            size -= 1

        main = fonts.measurable(fonts.jp(size))
        widths = [main.measure(ruby) for ruby, _ in segments]
        ruby_size = max(6, int(size * 0.5))
        ruby_font = fonts.jp(ruby_size)
        ruby_height = ruby_size + 2 if show_ruby else 0

        # Centre the whole word, then walk along it character by character.
        x = centre_x - sum(widths) / 2
        baseline = top_y + ruby_height
        self._mark()
        for (ruby, rt), width in zip(segments, widths):
            if show_ruby and rt:
                self._text(
                    x + width / 2, top_y,
                    text=rt, anchor="n",
                    fill=pal.ink_soft, font=ruby_font,
                )
            self._text(
                x + width / 2, baseline,
                text=ruby, anchor="n",
                fill=pal.ink, font=fonts.jp(size),
            )
            x += width
        self._region(word.text)

        # The English gloss, as much of it as the slot can take.
        if word.meaning:
            gloss = word.meaning.split(";")[0].strip()
            self._mark()
            self._text(
                centre_x, baseline + size * 1.5,
                text=gloss,
                anchor="n",
                fill=pal.ink_soft,
                font=fonts.ui(max(6, int(8 * scale))),
                width=max_width,
                justify="center",
            )
            self._region(gloss)

    # Japanese line breaking: these may not begin a line (kinsoku shori).
    _NO_LINE_START = "。、）」』？！ぁぃぅぇぉっゃゅょゎヽヾー・"

    def _draw_ruby_text(
        self,
        segments,
        left: float,
        top: float,
        max_width: float,
        size: int,
    ) -> tuple[float, list[tuple[float, float, float, float]]]:
        """Draw furigana'd Japanese that wraps; return the y below it and the
        box of each line, which is what the selection highlight uses.

        Tk can wrap a plain string on its own, but not with ruby sitting over
        individual characters, so the line breaking is done here: every
        annotated group is one unbreakable cell, plain kana break anywhere.
        """
        c = self.canvas
        pal = self.palette
        fonts = self.app.fonts
        main_spec = fonts.jp(size)
        ruby_spec = fonts.jp(max(6, int(size * 0.52)))
        main = fonts.measurable(main_spec)
        ruby = fonts.measurable(ruby_spec)

        show_ruby = self.options.show_furigana and any(rt for _, rt in segments)
        ruby_height = ruby.metrics("linespace") if show_ruby else 0
        line_height = ruby_height + main.metrics("linespace")

        # An annotated group stays whole; unannotated runs break per character
        # so that a long tail of kana still wraps.
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

        x, y = left, top
        boxes: list[tuple[float, float, float, float]] = []
        line_start = left
        for text, rt, width in cells:
            if x + width > left + max_width and x > left and text[0] not in self._NO_LINE_START:
                boxes.append((line_start, y, x, y + line_height))
                x = left
                y += line_height
            if rt:
                self._text(x + width / 2, y, text=rt, anchor="n", fill=pal.ink_soft, font=ruby_spec)
            self._text(x + width / 2, y + ruby_height, text=text, anchor="n", fill=pal.ink, font=main_spec)
            x += width
        if x > line_start:
            boxes.append((line_start, y, x, y + line_height))
        return y + line_height, boxes

    def _draw_readings(self, w: int, h: int, scale: float, top: int, bottom: int) -> None:
        """Fallback for a kanji with no vocabulary: show its readings."""
        pal = self.palette
        parts = []
        if self.card.on_readings:
            parts.append("　".join(self.card.on_readings[:3]))
        if self.card.kun_readings:
            parts.append("　".join(r.strip("-") for r in self.card.kun_readings[:3]))
        readings = "\n".join(parts)
        self._mark()
        self._text(
            w / 2, (top + bottom) / 2,
            text=readings,
            fill=pal.ink_soft,
            font=self.app.fonts.jp(max(9, int(12 * scale))),
            justify="center",
        )
        self._region(readings)

    def _draw_verso(self, w: int, h: int, scale: float) -> None:
        """Back: meaning of the kanji and one example sentence per word."""
        pal = self.palette
        c = self.canvas
        pad = max(8, int(w * 0.05))
        self._draw_header(w, h, scale, "verso")

        meaning_box = (pad, int(h * 0.12), w - pad, int(h * 0.32))
        if self.card.is_placeholder:
            self._zone(*meaning_box, "meaning", scale)
        else:
            meanings = ", ".join(self.card.meanings)
            self._mark()
            self._text(
                w / 2,
                (meaning_box[1] + meaning_box[3]) / 2,
                text=meanings,
                fill=pal.ink,
                font=self.app.fonts.ui(max(10, int(14 * scale)), "bold"),
                width=w - 2 * pad,
                justify="center",
            )
            self._region(meanings)

        top, floor = int(h * 0.36), int(h * 0.90)
        gap = max(5, int(7 * scale))

        if self.card.is_placeholder:
            rows = 3
            row_h = (floor - top - gap * (rows - 1)) / rows
            for i in range(rows):
                y0 = top + i * (row_h + gap)
                self._zone(pad, y0, w - pad, y0 + row_h, "sentence", scale)
        else:
            # Sentences are stacked in the order of the words on the recto,
            # each one followed by its own translation. They are laid out as
            # they come rather than in fixed rows, because sentence lengths
            # differ wildly and empty rows look like something is missing.
            text_width = w - 2 * pad
            y = float(top)
            for sentence in self.card.sentences:
                first_item = len(c.find_all())  # so this sentence can be undone
                first_region = len(self._regions)
                segments = sentence.furigana or ((sentence.text, ""),)
                self._mark()
                y, boxes = self._draw_ruby_text(
                    segments, pad, y, text_width, max(9, int(12 * scale))
                )
                self._region(sentence.text, boxes)
                if self.options.show_translation:
                    text, language = sentence.translation(self.options.language)
                    if text:
                        shown = text
                        if language != self.options.language:
                            # Say so rather than quietly showing another
                            # language: not every sentence is translated.
                            shown = f"{text}  [{language}]"
                        self._mark()
                        item = self._text(
                            pad, y + max(1, int(2 * scale)),
                            text=shown, anchor="nw",
                            fill=pal.ink_soft,
                            font=self.app.fonts.ui(max(7, int(9 * scale))),
                            width=text_width,
                        )
                        y = c.bbox(item)[3]
                        self._region(text)  # copy the translation, not the marker
                if y > floor:  # ran off the note: drop this one and stop
                    for item in c.find_all()[first_item:]:
                        c.delete(item)
                    del self._regions[first_region:]
                    break
                y += gap

        self._draw_footer(w, h, scale, "double-click to flip back")
