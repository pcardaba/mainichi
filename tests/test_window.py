"""Window behaviour tests. Skipped when there is no display to open."""

from __future__ import annotations

import os
import sys
import time
import unittest

HAS_DISPLAY = bool(os.environ.get("DISPLAY")) or sys.platform.startswith(("win", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class TestPostItWindow(unittest.TestCase):
    def setUp(self):
        from mainichi.app import MainichiApp
        from mainichi.config import AppConfig
        from mainichi.content import PlaceholderProvider

        self.app = MainichiApp(AppConfig(), provider=PlaceholderProvider())
        self.postit = self.app.spawn_postit()
        self.postit.win.update()

    def tearDown(self):
        self.app.root.destroy()

    def test_borderless_note_stays_under_the_window_manager(self):
        """An override-redirect window on X11 can never be un-pinned.

        It is stacked above everything whatever -topmost says, so "always on
        top" becomes impossible to switch off. The note must stay managed.
        """
        if sys.platform.startswith(("win", "darwin")):
            self.assertTrue(self.postit._unmanaged)
        else:
            self.assertFalse(self.postit._unmanaged)
            self.assertFalse(bool(self.postit.win.overrideredirect()))

    def test_no_title_bar(self):
        self.assertFalse(self.app.config.decorated)
        self.postit.win.update()
        # A decorated window would be reparented into a taller frame.
        self.assertEqual(self.postit.geometry_tuple()[:2], self.app.config.size)

    def _settle(self, predicate, seconds: float = 2.0) -> bool:
        """Pump the event loop until the window manager has caught up."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.postit.win.update()
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    def test_always_on_top_toggles_both_ways(self):
        for wanted in (False, True, False):
            with self.subTest(on_top=wanted):
                self.postit._var_on_top.set(wanted)
                self.postit._toggle_on_top()
                self.assertEqual(self.postit.options.always_on_top, wanted)
                # The window manager applies this asynchronously.
                applied = self._settle(
                    lambda: bool(self.postit.win.attributes("-topmost")) == wanted
                )
                self.assertTrue(applied, f"-topmost never became {wanted}")

    def test_toggling_on_top_keeps_position_and_size(self):
        self.postit.win.geometry("360x400+500+300")
        self.postit.win.update()
        before = self.postit.geometry_tuple()
        self.postit._var_on_top.set(False)
        self.postit._toggle_on_top()
        self.postit.win.update()
        self.assertEqual(self.postit.geometry_tuple(), before)

    def test_escape_dismisses_the_menu_without_closing_the_note(self):
        self.postit.menu.tk_popup(600, 400)
        self.postit.win.update()
        self.assertTrue(self.postit._menu_is_open())
        self.postit._dismiss_menu()
        self.postit.win.update()
        self.assertFalse(self.postit._menu_is_open())
        self.assertTrue(self.postit.win.winfo_exists())
        self.assertEqual(len(self.app.postits), 1)

    def test_flip_and_next_card(self):
        self.assertEqual(self.postit.face, "recto")
        self.postit.flip()
        self.assertEqual(self.postit.face, "verso")
        self.postit.next_card()
        self.assertEqual(self.postit.face, "recto")


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class TestSelection(unittest.TestCase):
    """Selecting text on the note, and copying it out."""

    def setUp(self):
        from mainichi.app import MainichiApp
        from mainichi.config import AppConfig
        from mainichi.dataset import BundledProvider

        provider = BundledProvider()
        if not provider.available():
            raise unittest.SkipTest("data not built")
        self.app = MainichiApp(AppConfig(size=(330, 380)), provider=provider)
        self.postit = self.app.postits[0] if self.app.postits else self.app.spawn_postit()
        self.postit.card = provider.next_card("N5", "日")
        self.postit.redraw()
        self.postit.win.update()

    def tearDown(self):
        self.app.root.destroy()

    def _centre(self, index):
        x0, y0, x1, y1 = self.postit._regions[index].boxes[0]
        return int((x0 + x1) / 2), int((y0 + y1) / 2)

    def _press(self, x, y):
        self.postit.canvas.event_generate("<Button-1>", x=x, y=y)
        self.postit.win.update()

    def test_words_are_selectable_regions(self):
        texts = [r.text for r in self.postit._regions]
        self.assertIn("日", texts)
        self.assertTrue(any(len(t) > 1 for t in texts))

    def test_click_selects_a_word_and_does_not_flip(self):
        self._press(*self._centre(1))
        self.assertEqual(len(self.postit._selection), 1)
        self.assertEqual(self.postit.selected_text(), self.postit._regions[1].text)
        # Flipping on a plain click would make selecting impossible.
        self.assertEqual(self.postit.face, "recto")

    def test_copy_puts_the_selection_on_the_clipboard(self):
        self._press(*self._centre(1))
        self.postit.copy_selection()
        self.assertEqual(self.postit.win.clipboard_get(), self.postit._regions[1].text)

    def test_furigana_is_never_copied(self):
        """The clipboard must hold the text as written, not its reading."""
        self.postit.face = "verso"
        self.postit.redraw()
        self.postit.select_all()
        self.postit.copy_selection()
        copied = self.postit.win.clipboard_get()
        readings = {
            rt
            for sentence in self.postit.card.sentences
            for _text, rt in sentence.furigana
            if rt
        }
        readings |= {rt for word in self.postit.card.words for _t, rt in word.furigana if rt}
        leaked = sorted(r for r in readings if r and r in copied)
        self.assertEqual(leaked, [], "furigana leaked into the clipboard")

    def test_drag_extends_the_selection(self):
        self._press(*self._centre(1))
        x, y = self._centre(3)
        self.postit.canvas.event_generate("<B1-Motion>", x=x, y=y)
        self.postit.win.update()
        self.assertEqual(sorted(self.postit._selection), [1, 2, 3])
        self.assertIn("\n", self.postit.selected_text())

    def test_click_on_blank_paper_clears_the_selection(self):
        self._press(*self._centre(1))
        self.assertTrue(self.postit._selection)
        self._press(3, 3)  # top left corner: no text there
        self.assertFalse(self.postit._selection)

    def test_selection_survives_a_resize(self):
        self._press(*self._centre(1))
        before = self.postit.selected_text()
        self.postit.win.geometry("400x440")
        self.postit.win.update()
        self.postit.redraw()
        self.assertEqual(self.postit.selected_text(), before)

    def test_flip_clears_the_selection(self):
        self._press(*self._centre(1))
        self.postit.flip()
        self.assertFalse(self.postit._selection)

    def test_double_click_is_what_flips(self):
        self.assertIn("<Double-Button-1>", self.postit.canvas.bind())
        self.postit._on_double_click(None)
        self.assertEqual(self.postit.face, "verso")

    def test_copy_with_nothing_selected_is_harmless(self):
        self.postit.win.clipboard_clear()
        self.postit.win.clipboard_append("untouched")
        self.postit.copy_selection()
        self.assertEqual(self.postit.win.clipboard_get(), "untouched")


if __name__ == "__main__":
    unittest.main()
