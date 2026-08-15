"""Stroke outlines: parsing KanjiVG paths and flattening them to polylines."""

from __future__ import annotations

import math
import unittest

from mainichi.strokes import PEN_WIDTH, VIEWBOX, StrokeLibrary, flatten


class TestFlatten(unittest.TestCase):
    def test_move_and_cubic(self):
        points = flatten("M10,10c5,0,10,5,10,10")
        self.assertEqual(points[0], (10.0, 10.0))
        self.assertAlmostEqual(points[-1][0], 20.0, places=6)
        self.assertAlmostEqual(points[-1][1], 20.0, places=6)
        self.assertGreater(len(points), 3, "the curve should be subdivided")

    def test_absolute_and_relative_agree(self):
        relative = flatten("M0,0c10,0,20,10,20,20")
        absolute = flatten("M0,0C10,0,20,10,20,20")
        self.assertEqual(len(relative), len(absolute))
        for a, b in zip(relative, absolute):
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)

    def test_smooth_curve_mirrors_the_control_point(self):
        points = flatten("M0,0c5,0,10,5,10,10s5,10,10,10")
        self.assertAlmostEqual(points[-1][0], 20.0, places=6)
        self.assertAlmostEqual(points[-1][1], 20.0, places=6)

    def test_detail_controls_smoothness(self):
        coarse = flatten("M0,0c20,0,40,20,40,40", detail=8.0)
        fine = flatten("M0,0c20,0,40,20,40,40", detail=1.0)
        self.assertGreater(len(fine), len(coarse))

    def test_no_duplicate_points(self):
        for point_a, point_b in zip(flatten("M10,10c5,0,10,5,10,10"), flatten("M10,10c5,0,10,5,10,10")[1:]):
            self.assertGreater(math.dist(point_a, point_b), 0)

    def test_rubbish_does_not_raise(self):
        self.assertEqual(flatten(""), [])
        self.assertEqual(flatten("Z"), [])


class TestStrokeLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = StrokeLibrary()
        if not cls.library.available:
            raise unittest.SkipTest("stroke data not built")

    def test_known_kanji(self):
        self.assertTrue(self.library.has("日"))
        strokes = self.library.strokes("日")
        self.assertEqual(len(strokes), 4, "日 is written with four strokes")
        for stroke in strokes:
            self.assertGreaterEqual(len(stroke), 2)

    def test_strokes_fit_the_viewbox(self):
        for kanji in ("日", "語", "一", "働"):
            with self.subTest(kanji=kanji):
                for stroke in self.library.strokes(kanji):
                    for x, y in stroke:
                        self.assertTrue(-1 <= x <= VIEWBOX + 1, f"{kanji}: x={x}")
                        self.assertTrue(-1 <= y <= VIEWBOX + 1, f"{kanji}: y={y}")

    def test_stroke_counts_match_the_card_data(self):
        """KanjiVG's stroke count should agree with KANJIDIC's."""
        from mainichi.dataset import BundledProvider

        provider = BundledProvider()
        if not provider.available():
            self.skipTest("card data not built")
        mismatched = []
        for record in provider.load("N5"):
            kanji = record["k"]
            expected = record.get("st", 0)
            found = len(self.library.strokes(kanji))
            if expected and found and expected != found:
                mismatched.append((kanji, expected, found))
        self.assertEqual(mismatched, [])

    def test_unknown_kanji_is_empty_not_an_error(self):
        self.assertFalse(self.library.has("漢" * 2))
        self.assertEqual(self.library.strokes("A"), [])

    def test_pen_width_is_sane(self):
        self.assertGreater(PEN_WIDTH, 0)
        self.assertLess(PEN_WIDTH, VIEWBOX / 10)


if __name__ == "__main__":
    unittest.main()
