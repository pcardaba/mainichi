"""Application object: owns the Tk root and every post-it on the desktop."""

from __future__ import annotations

import sys
import tkinter as tk

from mainichi.config import AppConfig
from mainichi.content import CardProvider, PlaceholderProvider
from mainichi.ui.fonts import FontBook
from mainichi.ui.postit import PostItWindow

# Each extra post-it is dealt slightly down and to the left of the previous one.
_CASCADE = 28
_SCREEN_MARGIN = 60


class MainichiApp:
    """Runs the Tk main loop and keeps track of the open post-its."""

    def __init__(self, config: AppConfig, provider: CardProvider | None = None) -> None:
        self.config = config
        self.provider: CardProvider = provider or PlaceholderProvider()

        self.root = tk.Tk()
        self.root.withdraw()  # the root is never shown; post-its are Toplevels
        self.root.title("mainichi")

        self.fonts = FontBook()
        if self.fonts.jp_missing:
            print(
                "mainichi: no Japanese font found; kanji may render as empty boxes.\n"
                "          install e.g. 'fonts-noto-cjk' (Linux) or use Yu Gothic (Windows).",
                file=sys.stderr,
            )

        self.postits: list[PostItWindow] = []
        self._spawned = 0

    # ------------------------------------------------------------- post-its

    def spawn_postit(self) -> PostItWindow:
        """Create one more post-it, cascaded from the previous one."""
        card = self.provider.next_card(self.config.level, self.config.kanji)
        options = self.config.options.copy()
        postit = PostItWindow(self, card, options, self._next_geometry())
        self.postits.append(postit)
        self._spawned += 1
        return postit

    def _next_geometry(self) -> tuple[int, int, int, int]:
        w, h = self.config.size
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - w - _SCREEN_MARGIN + self._spawned * -_CASCADE
        y = _SCREEN_MARGIN + self._spawned * _CASCADE
        return w, h, max(0, x), max(0, y)

    def forget_postit(self, postit: PostItWindow) -> None:
        """Drop a closed post-it; quit once the last one is gone."""
        if postit in self.postits:
            self.postits.remove(postit)
        if not self.postits:
            self.quit()

    # ----------------------------------------------------------------- loop

    def quit(self) -> None:
        self.root.quit()

    def _keep_signals_alive(self) -> None:
        """Wake Tk periodically so Ctrl+C in the terminal is handled."""
        self.root.after(200, self._keep_signals_alive)

    def run(self) -> int:
        self.spawn_postit()
        self._keep_signals_alive()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
        return 0
