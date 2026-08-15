# mainichi 毎日

A kanji a day, stuck on your desktop like a post-it.

> **Status: framework stage.** The window, the interaction model and the
> architecture are in place. There is no kanji data yet, so the post-it shows
> dashed placeholder zones where the content will go.

## Requirements

* Python >= 3.10 with tkinter (standard library, no third-party dependency)
  * Debian/Ubuntu: `sudo apt install python3-tk`
  * Windows / macOS: bundled with the python.org installer
* A font covering Japanese. Without one, kanji show up as empty boxes.
  * Debian/Ubuntu: `sudo apt install fonts-noto-cjk`
  * Windows 10/11: Yu Gothic / MS Gothic are already installed

## Running

```bash
python -m mainichi                 # random kanji from N5 (default)
python -m mainichi --level N3      # random kanji from N3
python -m mainichi --kanji 日      # one specific kanji
python -m mainichi --colour blue --size 360x400
python -m mainichi --decorated     # keep the title bar, if borderless misbehaves
```

`--level` and `--kanji` are mutually exclusive, as they should be.

Launch it several times for several post-its, or press `Ctrl+N` on one.

## Using a post-it

| Action | Result |
| --- | --- |
| left click | flip between recto (kanji + words) and verso (meaning + sentences) |
| drag | move the note around the desktop |
| drag the folded corner | resize the note |
| right click | context menu (on-top, furigana, translation, colour, next, ...) |
| `Space` | flip |
| `Ctrl+N` / `Ctrl+W` / `Ctrl+Q` | new note / close note / quit |

Closing the last post-it quits the application.

## Architecture

```
mainichi/
├── cli.py          argument parsing, builds an AppConfig
├── config.py       AppConfig (launch) + PostItOptions (per-note, menu toggles)
├── content.py      KanjiCard / Word / Sentence + the CardProvider protocol
├── app.py          MainichiApp: owns the Tk root and every open post-it
└── ui/
    ├── postit.py   PostItWindow: borderless window, canvas drawing, input
    ├── theme.py    Palette + the six post-it colours
    └── fonts.py    finds a Japanese capable font family per platform
```

The presentation layer only ever reads a `KanjiCard` and only ever asks a
`CardProvider` for the next one. Today the sole provider is
`PlaceholderProvider`, which returns empty cards; a real one (bundled JLPT
lists, KANJIDIC, an online lookup) drops in without touching `ui/`.

## Not implemented yet

* kanji data for the five JLPT levels, and the random pick within a level
* words, readings, furigana rendering as real ruby text, example sentences
* **Traces**: stroke order animation (menu entry present but disabled)
* **Copy**: text selection and `Ctrl+C` (menu entry present but disabled)
* persisting position, size, colour and options between runs
