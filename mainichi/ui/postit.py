"""The post-it window.

A borderless always-on-top Toplevel holding a single Canvas. Everything is
drawn by hand on that canvas: there are no widgets, no menus and no buttons
on the paper itself, exactly like a real post-it.

Interaction
-----------
* drag anywhere            -> move the note
* drag the folded corner   -> resize the note
* left click (no drag)     -> flip recto/verso
* right click              -> context menu
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from mainichi.config import MIN_SIZE, PostItOptions
from mainichi.content import KanjiCard
from mainichi.ui.theme import PALETTES, get_palette

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mainichi.app import MainichiApp

# Reference size the proportional layout was designed against.
_BASE_W, _BASE_H = 300, 340

RECTO, VERSO = "recto", "verso"


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

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("mainichi")

        w, h, x, y = geometry
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.minsize(self.MIN_W, self.MIN_H)

        if app.config.decorated:
            self.win.resizable(True, True)
        else:
            # Borderless: the paper is the whole window.
            self.win.overrideredirect(True)

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
        c.bind("<Button-3>", self._on_context_menu)
        c.bind("<Configure>", lambda _e: self.redraw())
        c.bind("<Motion>", self._on_hover)

        w = self.win
        w.bind("<space>", lambda _e: self.flip())
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

        m = tk.Menu(self.win, tearoff=0)
        m.add_checkbutton(label="Always on top", variable=self._var_on_top, command=self._toggle_on_top)
        m.add_command(label="Traces", state="disabled")  # stroke animation, later
        m.add_checkbutton(label="Furigana", variable=self._var_furigana, command=self._toggle_furigana)
        m.add_checkbutton(label="Translation", variable=self._var_translation, command=self._toggle_translation)
        m.add_separator()
        m.add_command(label="Copy", accelerator="Ctrl+C", state="disabled")  # needs selectable text
        m.add_command(label="Flip", accelerator="Space", command=self.flip)
        m.add_command(label="Next kanji", command=self.next_card)

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
        for menu in (m, colours):
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
        if self.app.config.decorated:
            return
        self.canvas.configure(cursor="bottom_right_corner" if self._in_fold(event.x, event.y) else "hand2")

    def _menu_is_open(self) -> bool:
        try:
            return bool(self.menu.winfo_ismapped())
        except tk.TclError:  # pragma: no cover - menu already gone
            return False

    def _on_press(self, event: tk.Event) -> str | None:
        # A click while the menu is up only dismisses it: it should not also
        # flip the note or start a drag.
        if self._menu_is_open():
            self._dismiss_menu()
            return "break"
        self.win.focus_force()
        self._moved = False
        w, h, x, y = self.geometry_tuple()
        if self._in_fold(event.x, event.y) and not self.app.config.decorated:
            self._resize_origin = (event.x_root, event.y_root, w, h)
            self._drag_origin = None
        else:
            self._resize_origin = None
            self._drag_origin = (event.x_root - x, event.y_root - y)
        return None

    def _on_motion(self, event: tk.Event) -> None:
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
        was_drag = self._moved
        self._drag_origin = self._resize_origin = None
        self._moved = False
        if not was_drag:
            self.flip()

    def _on_context_menu(self, event: tk.Event) -> None:
        """Post the context menu under the pointer.

        The grab that ``tk_popup`` takes is deliberately kept: it is what
        makes a click anywhere outside the menu dismiss it. Releasing it
        straight away (the usual Tkinter snippet) leaves the menu stuck on
        screen. It is released again when the menu unmaps, and by
        :meth:`_dismiss_menu`.

        The keyboard focus is taken first: a borderless window is never given
        the focus by the window manager, so otherwise the Escape key goes to
        whichever window happens to hold the focus instead of to the menu.
        """
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
        self.redraw()

    def next_card(self) -> None:
        self.card = self.app.provider.next_card(self.app.config.level, self.app.config.kanji)
        self.face = RECTO
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

    def _apply_topmost(self) -> None:
        on_top = self.options.always_on_top
        try:
            if self.win.winfo_viewable() and self.win.overrideredirect():
                # X11 silently ignores a -topmost change on a borderless
                # window that is already mapped, so unmap it around the
                # change. The geometry is restored right after.
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

        self._draw_paper(w, h)
        if self.face == RECTO:
            self._draw_recto(w, h, scale)
        else:
            self._draw_verso(w, h, scale)
        self._draw_fold(w, h)

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
            c.create_text(
                w / 2,
                (kanji_box[1] + kanji_box[3]) / 2,
                text=self.card.kanji,
                fill=pal.ink,
                font=self.app.fonts.jp(max(24, int((kanji_box[3] - kanji_box[1]) * 0.82))),
            )

        # Words row: one slot per reading, most common on the left.
        row_top, row_bottom = int(h * 0.62), int(h * 0.87)
        slots = max(1, len(self.card.words) or 3)
        gap = max(4, int(6 * scale))
        slot_w = (w - 2 * pad - gap * (slots - 1)) / slots
        for i in range(slots):
            x0 = pad + i * (slot_w + gap)
            x1 = x0 + slot_w
            if self.card.is_placeholder:
                self._zone(x0, row_top, x1, row_bottom, "word", scale)
            else:
                word = self.card.words[i]
                if self.options.show_furigana and word.reading:
                    c.create_text(
                        (x0 + x1) / 2, row_top,
                        text=word.reading, anchor="n",
                        fill=pal.ink_soft, font=self.app.fonts.jp(max(7, int(10 * scale))),
                    )
                c.create_text(
                    (x0 + x1) / 2, (row_top + row_bottom) / 2,
                    text=word.text, anchor="center",
                    fill=pal.ink, font=self.app.fonts.jp(max(10, int(16 * scale))),
                )

        self._draw_footer(w, h, scale, "click to flip · right-click for options")

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
            c.create_text(
                w / 2,
                (meaning_box[1] + meaning_box[3]) / 2,
                text=", ".join(self.card.meanings),
                fill=pal.ink,
                font=self.app.fonts.ui(max(10, int(14 * scale)), "bold"),
                width=w - 2 * pad,
                justify="center",
            )

        rows = max(1, len(self.card.sentences) or 3)
        top, bottom = int(h * 0.36), int(h * 0.88)
        gap = max(4, int(6 * scale))
        row_h = (bottom - top - gap * (rows - 1)) / rows
        for i in range(rows):
            y0 = top + i * (row_h + gap)
            y1 = y0 + row_h
            if self.card.is_placeholder:
                self._zone(pad, y0, w - pad, y1, "sentence", scale)
            else:
                sentence = self.card.sentences[i]
                item = c.create_text(
                    pad, y0,
                    text=sentence.text, anchor="nw",
                    fill=pal.ink, font=self.app.fonts.jp(max(9, int(12 * scale))),
                    width=w - 2 * pad,
                )
                if self.options.show_translation and sentence.translation:
                    # Sit right under this sentence (which may have wrapped),
                    # not at the bottom of the row: otherwise the translation
                    # looks like it belongs to the next sentence.
                    bottom = c.bbox(item)[3]
                    c.create_text(
                        pad, bottom + max(1, int(2 * scale)),
                        text=sentence.translation, anchor="nw",
                        fill=pal.ink_soft, font=self.app.fonts.ui(max(7, int(9 * scale))),
                        width=w - 2 * pad,
                    )

        self._draw_footer(w, h, scale, "click to flip back")
