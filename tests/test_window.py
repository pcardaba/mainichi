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

    def test_flip_and_next(self):
        self.assertEqual(self.postit.face, "recto")
        self.postit.flip()
        self.assertEqual(self.postit.face, "verso")
        self.postit.next_card()
        self.assertEqual(self.postit.face, "recto")


if __name__ == "__main__":
    unittest.main()
