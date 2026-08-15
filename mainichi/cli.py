"""Command line entry point: ``python -m mainichi`` / ``mainichi``."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk

from mainichi import __version__
from mainichi.config import (
    DEFAULT_LANGUAGE,
    DEFAULT_LEVEL,
    DEFAULT_VERSO,
    DEFAULT_SIZE,
    LANGUAGES,
    LEVELS,
    MIN_SIZE,
    VERSO_MODES,
    AppConfig,
    PostItOptions,
)
from mainichi.ui.theme import DEFAULT_PALETTE, PALETTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mainichi",
        description="Stick a kanji of the day on your desktop.",
    )
    parser.add_argument("--version", action="version", version=f"mainichi {__version__}")

    # A level and an explicit kanji are mutually exclusive by design.
    what = parser.add_mutually_exclusive_group()
    what.add_argument(
        "-l", "--level",
        choices=LEVELS,
        default=DEFAULT_LEVEL,
        help=f"JLPT level to pick a random kanji from (default: {DEFAULT_LEVEL})",
    )
    what.add_argument(
        "-k", "--kanji",
        metavar="字",
        help="show this exact kanji instead of a random one",
    )

    parser.add_argument(
        "-c", "--colour", "--color",
        dest="colour",
        choices=sorted(PALETTES),
        default=DEFAULT_PALETTE,
        help=f"post-it background colour (default: {DEFAULT_PALETTE})",
    )
    parser.add_argument(
        "-L", "--language",
        choices=sorted(LANGUAGES),
        default=DEFAULT_LANGUAGE,
        help="language of the sentence translations (default: %(default)s)",
    )
    parser.add_argument(
        "--verso",
        choices=sorted(VERSO_MODES),
        default=DEFAULT_VERSO,
        help="what the back of the note shows (default: %(default)s)",
    )
    parser.add_argument(
        "--size",
        metavar="WxH",
        default="{}x{}".format(*DEFAULT_SIZE),
        help="initial post-it size in pixels (default: {}x{})".format(*DEFAULT_SIZE),
    )
    parser.add_argument(
        "--no-on-top",
        action="store_true",
        help="do not keep the post-it above other windows",
    )
    parser.add_argument(
        "--decorated",
        action="store_true",
        help="keep the window manager title bar (fallback if the borderless "
             "window misbehaves on your desktop)",
    )
    return parser


def _parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(part) for part in text.lower().split("x", 1))
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid size {text!r}, expected WxH e.g. 300x340") from None
    return max(MIN_SIZE[0], w), max(MIN_SIZE[1], h)


def _validate_kanji(text: str) -> str:
    """Accept exactly one CJK ideograph."""
    text = text.strip()
    if len(text) != 1:
        raise argparse.ArgumentTypeError("--kanji takes a single character")
    if not ("一" <= text <= "鿿" or "㐀" <= text <= "䶿"):
        raise argparse.ArgumentTypeError(f"{text!r} is not a kanji")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        size = _parse_size(args.size)
        kanji = _validate_kanji(args.kanji) if args.kanji else None
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        return 2  # unreachable, parser.error exits

    # Check the kanji is actually in the data before opening a window.
    provider = None
    if kanji:
        from mainichi.dataset import BundledProvider, DataNotBuilt

        try:
            provider = BundledProvider()
            if provider.find(kanji) is None:
                print(
                    f"mainichi: {kanji} is not in the JLPT kanji data (N5-N1).",
                    file=sys.stderr,
                )
                return 1
        except DataNotBuilt as exc:
            print(f"mainichi: {exc}", file=sys.stderr)
            return 1

    config = AppConfig(
        level=args.level,
        kanji=kanji,
        decorated=args.decorated,
        size=size,
        options=PostItOptions(
            palette=args.colour,
            always_on_top=not args.no_on_top,
            language=args.language,
            verso=args.verso,
        ),
    )

    # Imported late so that --help/--version work on a machine with no display.
    from mainichi.app import MainichiApp

    try:
        app = MainichiApp(config, provider=provider)
    except tk.TclError as exc:
        print(f"mainichi: cannot open a window ({exc})", file=sys.stderr)
        return 1
    return app.run()
