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

    def test_vocabulary_is_the_default_back(self):
        from mainichi.config import DEFAULT_VERSO

        self.assertEqual(DEFAULT_VERSO, "vocabulary")
        self.assertEqual(self.postit.options.verso, "vocabulary")

    def test_back_shows_vocabulary_words(self):
        self.postit.face = "verso"
        self.postit.redraw()
        shown = {r.text for r in self.postit._regions}
        available = {w.text for w in self.postit.card.vocabulary}
        self.assertTrue(available, "the card should carry extra vocabulary")
        self.assertTrue(shown & available, "no vocabulary word was drawn")
        # Those words are not the ones already on the front.
        self.assertFalse(available & {w.text for w in self.postit.card.words})

    def test_switching_the_back_changes_what_is_drawn(self):
        self.postit.face = "verso"
        self.postit.options.verso = "vocabulary"
        self.postit.redraw()
        vocabulary = {r.text for r in self.postit._regions}
        self.postit.options.verso = "sentences"
        self.postit.redraw()
        sentences = {r.text for r in self.postit._regions}
        self.assertNotEqual(vocabulary, sentences)
        self.assertTrue(sentences & {s.text for s in self.postit.card.sentences})

    def test_menu_switch_from_the_front_flips_to_show_it(self):
        self.postit.face = "recto"
        self.postit._var_verso.set("sentences")
        self.postit._change_verso()
        self.assertEqual(self.postit.options.verso, "sentences")
        self.assertEqual(self.postit.face, "verso")

    def _vocabulary_regions(self):
        wanted = {w.text for w in self.postit.card.vocabulary}
        return [r for r in self.postit._regions if r.text in wanted]

    def test_vocabulary_uses_two_columns_on_a_small_note(self):
        """The meaning follows its word, which leaves room for a column."""
        self.postit.options.verso = "vocabulary"
        self.postit.face = "verso"
        self.postit.win.geometry("210x230")  # the smallest a note can be
        self.postit.win.update()
        self.postit.redraw()

        rows: dict[int, list[float]] = {}
        for region in self._vocabulary_regions():
            x0, y0, _x1, _y1 = region.boxes[0]
            rows.setdefault(round(y0), []).append(x0)
        self.assertTrue(rows, "no vocabulary was drawn")
        widest = max(len(xs) for xs in rows.values())
        self.assertGreaterEqual(widest, 2, "expected two words side by side")
        self.assertGreaterEqual(len(self._vocabulary_regions()), 6)

    def test_a_bigger_note_shows_more_words(self):
        self.postit.options.verso = "vocabulary"
        self.postit.face = "verso"
        self.postit.win.geometry("210x230")
        self.postit.win.update()
        self.postit.redraw()
        small = len(self._vocabulary_regions())
        self.postit.win.geometry("420x480")
        self.postit.win.update()
        self.postit.redraw()
        self.assertGreater(len(self._vocabulary_regions()), small)

    def test_shortened_meanings_can_be_read_in_the_bubble(self):
        """Narrow columns cut long meanings; hovering shows the whole thing."""
        self.postit.options.verso = "vocabulary"
        self.postit.face = "verso"
        self.postit.win.geometry("210x230")
        self.postit.win.update()
        self.postit.redraw()
        elided = [i for i, r in enumerate(self.postit._regions) if r.elided]
        if not elided:
            self.skipTest("nothing needed shortening for this kanji")
        index = elided[0]
        self.postit._hover_region(index, 300, 300)
        self.assertIsNotNone(self.postit._hover_job, "a cut meaning deserves a bubble")
        self.postit._show_bubble()
        self.postit.win.update()
        self.assertTrue(self.postit._bubble_shown())
        drawn = " ".join(
            self.postit._bubble.canvas.itemcget(item, "text")
            for item in self.postit._bubble.canvas.find_all()
            if self.postit._bubble.canvas.type(item) == "text"
        )
        self.assertIn(self.postit._regions[index].text, drawn)
        self.assertNotIn("…", drawn)

    def test_elide_keeps_what_fits(self):
        font = self.app.fonts.measurable(self.app.fonts.ui(10))
        self.assertEqual(self.postit._elide("short", font, 500), "short")
        cut = self.postit._elide("a very long meaning indeed", font, 40)
        self.assertTrue(cut.endswith("…"))
        self.assertLessEqual(font.measure(cut), 40)

    def test_vocabulary_words_are_selectable(self):
        self.postit.face = "verso"
        self.postit.options.verso = "vocabulary"
        self.postit.redraw()
        self.postit.win.update()
        first = next(
            i for i, r in enumerate(self.postit._regions)
            if r.text in {w.text for w in self.postit.card.vocabulary}
        )
        x0, y0, x1, y1 = self.postit._regions[first].boxes[0]
        self._press(int((x0 + x1) / 2), int((y0 + y1) / 2))
        self.postit.copy_selection()
        self.assertEqual(self.postit.win.clipboard_get(), self.postit._regions[first].text)

    def test_traces_animate_stroke_by_stroke(self):
        """The animation walks the strokes in order and then stops."""
        self.postit.card = self.app.provider.next_card("N5", "語")
        self.postit.play_traces()
        self.assertTrue(self.postit.tracing)
        self.assertEqual(self.postit.face, "recto", "the kanji is on the front")
        total = len(self.postit._trace["strokes"])
        self.assertEqual(total, 14, "語 is written with fourteen strokes")

        seen = []
        for _ in range(4000):  # drive the frames directly, without waiting
            if not self.postit.tracing:
                break
            seen.append(self.postit._trace["index"])
            self.postit._trace_tick()
        self.assertFalse(self.postit.tracing, "the animation should finish")
        self.assertEqual(seen, sorted(seen), "strokes must be drawn in order")
        self.assertEqual(max(seen), total - 1, "every stroke should be drawn")

    def test_traces_from_the_back_flips_to_the_front(self):
        self.postit.face = "verso"
        self.postit.play_traces()
        self.assertEqual(self.postit.face, "recto")

    def test_redraw_cancels_a_running_animation(self):
        self.postit.play_traces()
        self.assertTrue(self.postit.tracing)
        self.postit.redraw()
        self.assertFalse(self.postit.tracing)
        self.assertIsNone(self.postit._trace_job)

    def test_traces_without_stroke_data_do_not_crash(self):
        from mainichi.content import KanjiCard

        self.postit.card = KanjiCard(kanji="A", level="N5")  # no KanjiVG entry
        self.postit.play_traces()
        self.assertFalse(self.postit.tracing)

    def test_only_japanese_text_gets_a_bubble(self):
        """Words and sentences have readings worth magnifying; glosses do not."""
        with_furigana = [r.text for r in self.postit._regions if r.furigana]
        self.assertTrue(with_furigana)
        for region in self.postit._regions:
            if region.furigana:
                rebuilt = "".join(text for text, _rt in region.furigana)
                self.assertEqual(rebuilt, region.text)

    def _first_furigana_region(self):
        return next(i for i, r in enumerate(self.postit._regions) if r.furigana)

    def test_hovering_a_word_schedules_then_shows_the_bubble(self):
        index = self._first_furigana_region()
        self.postit._hover_region(index, 300, 300)
        self.assertIsNotNone(self.postit._hover_job, "should wait before popping up")
        self.assertFalse(self.postit._bubble_shown(), "not immediately")
        self.postit._show_bubble()  # what the timer would do
        self.postit.win.update()
        self.assertTrue(self.postit._bubble_shown())

    def test_bubble_shows_the_same_reading_as_the_note(self):
        index = self._first_furigana_region()
        self.postit._hover_region(index, 300, 300)
        self.postit._show_bubble()
        self.postit.win.update()
        readings = [rt for _t, rt in self.postit._regions[index].furigana if rt]
        drawn = [
            self.postit._bubble.canvas.itemcget(item, "text")
            for item in self.postit._bubble.canvas.find_all()
            if self.postit._bubble.canvas.type(item) == "text"
        ]
        for reading in readings:
            self.assertIn(reading, drawn)

    def test_moving_off_the_word_hides_the_bubble(self):
        index = self._first_furigana_region()
        self.postit._hover_region(index, 300, 300)
        self.postit._show_bubble()
        self.postit.win.update()
        self.assertTrue(self.postit._bubble_shown())
        self.postit._hover_region(None, 900, 900)
        self.postit.win.update()
        self.assertFalse(self.postit._bubble_shown())

    def test_bubble_can_be_switched_off(self):
        self.postit._var_bubble.set(False)
        self.postit._toggle_bubble()
        self.postit._hover_region(self._first_furigana_region(), 300, 300)
        self.assertIsNone(self.postit._hover_job)
        self.assertFalse(self.postit._bubble_shown())

    def test_bubble_stays_on_screen(self):
        index = self._first_furigana_region()
        screen_w = self.postit.win.winfo_screenwidth()
        screen_h = self.postit.win.winfo_screenheight()
        self.postit._hover_region(index, screen_w - 5, screen_h - 5)
        self.postit._show_bubble()
        self.postit.win.update()
        window = self.postit._bubble.win
        self.assertLessEqual(window.winfo_x() + window.winfo_width(), screen_w)
        self.assertLessEqual(window.winfo_y() + window.winfo_height(), screen_h)
        self.assertGreaterEqual(window.winfo_x(), 0)

    def test_a_click_hides_the_bubble(self):
        index = self._first_furigana_region()
        self.postit._hover_region(index, 300, 300)
        self.postit._show_bubble()
        self.postit.win.update()
        x0, y0, x1, y1 = self.postit._regions[index].boxes[0]
        self._press(int((x0 + x1) / 2), int((y0 + y1) / 2))
        self.assertFalse(self.postit._bubble_shown())

    def test_copy_with_nothing_selected_is_harmless(self):
        self.postit.win.clipboard_clear()
        self.postit.win.clipboard_append("untouched")
        self.postit.copy_selection()
        self.assertEqual(self.postit.win.clipboard_get(), "untouched")


if __name__ == "__main__":
    unittest.main()
