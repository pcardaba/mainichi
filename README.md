# mainichi 毎日

A kanji a day, stuck on your desktop like a post-it.

> **Status:** the window, the interaction model and the kanji data are in
> place. 2211 kanji across the five JLPT levels, each with common words per
> reading, furigana, and example sentences. Text can be selected and copied.
> Stroke order animation is not implemented yet.

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
python -m mainichi --language fr    # translations in French (en, fr, es)
python -m mainichi --verso sentences # back of the note: example sentences
python -m mainichi --decorated     # keep the title bar, if borderless misbehaves
```

`--level` and `--kanji` are mutually exclusive, as they should be.

Launch it several times for several post-its, or press `Ctrl+N` on one.

## Using a post-it

| Action | Result |
| --- | --- |
| left click on text | select that word or sentence; drag to extend over several |
| left click on blank paper | clear the selection |
| double click | flip between the front (kanji + words) and the back (meaning + vocabulary or sentences) |
| drag the blank paper | move the note around the desktop |
| drag the folded corner | resize the note |
| right click | context menu (on-top, furigana, translation, language, back of the note, colour, next, ...) |
| left click outside the menu, or `Esc` | close the context menu |
| `Ctrl+C` / `Ctrl+A` | copy the selection / select everything on this side |
| `Space` | flip |
| `Ctrl+N` / `Ctrl+W` / `Ctrl+Q` | new note / close note / quit |

Closing the last post-it quits the application.

## The data

| Level | Kanji | Words | Extra vocabulary | Sentences | Furigana | On level | fr | es |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| N5 | 79 | 266 | 790 | 231 | 98% | 50% | 41% | 35% |
| N4 | 166 | 472 | 1660 | 426 | 99% | 69% | 47% | 45% |
| N3 | 367 | 1009 | 3670 | 872 | 99% | 88% | 59% | 54% |
| N2 | 367 | 826 | 3670 | 690 | 99% | 87% | 52% | 45% |
| N1 | 1232 | 2299 | 10840 | 1558 | 99% | 97% | 47% | 36% |

Each kanji carries its English meanings, its on and kun readings, and up to
four common words — **one per reading of that kanji**, most common first —
with the furigana aligned per character, so 日曜日 shows にち above 日, よう
above 曜 and び above the last 日.

The back of the note shows either **more vocabulary** written with the kanji
(the default: ten more words per kanji, as many as the paper holds, so a
bigger note shows more) or **example sentences**, one per word on the front.
The choice is in the context menu under "Back of the note".

The sentences are chosen *for the level*: short, everyday, and built from kanji the learner already knows.
"Furigana" above is the share of sentences where every kanji could be given
a reading; "on level" the share using no kanji above the level. N5 is the
hard case — with only 79 kanji available, half of its sentences still need
one harder character, which is why full furigana matters.

Translations come in **English, French and Spanish**, for both the sentence
translations and the word meanings. English is always present; the other two
depend on what the sources cover, and anything missing falls back to English
with a small `[en]` marker rather than silently showing another language.

| | French | Spanish |
| --- | ---: | ---: |
| Word meanings, N5/N4 | 73-81% | 82-86% |
| Word meanings, all levels | 71% front / 49% vocabulary | 75% / 56% |
| Sentence translations | 41-59% | 35-54% |

Word meanings come from the full JMdict rather than its English-only export.
Coverage is deliberately best where beginners are: among words of comparable
usefulness the build prefers the ones that are translated.

The whole set is 1.6 MiB, gzipped JSON, one file per level, loaded lazily:
showing an N5 note never reads the 1232 kanji of N1. **The application never
uses the network.**

To regenerate it (needs an internet connection, takes about ten seconds plus
downloads):

```bash
python tools/build_data.py            # all levels
python tools/build_data.py --levels N5
```

Data sources and their licences are listed in [ATTRIBUTION.md](ATTRIBUTION.md).
Note that the generated data is CC BY-SA, while this code is Apache-2.0, and
that the JLPT has published no official kanji lists since 2010 — the level
assignment is a well established reconstruction, not an official list.

## Architecture

```
mainichi/
├── cli.py          argument parsing, builds an AppConfig
├── config.py       AppConfig (launch) + PostItOptions (per-note, menu toggles)
├── content.py      KanjiCard / Word / Sentence + the CardProvider protocol
├── dataset.py      BundledProvider: reads mainichi/data, deals shuffled decks
├── data/           N5.json.gz ... N1.json.gz, generated, committed
├── app.py          MainichiApp: owns the Tk root and every open post-it
└── ui/
    ├── postit.py   PostItWindow: borderless window, canvas drawing, input
    ├── theme.py    Palette + the six post-it colours
    └── fonts.py    finds a Japanese capable font family per platform
tools/
└── build_data.py   downloads the open data sets and builds mainichi/data
```

The presentation layer only ever reads a `KanjiCard` and asks a
`CardProvider` for the next one, so swapping the bundled data for an online
lookup would not touch `ui/`.

## Copying text

Click a word or a sentence to select it, drag to take in several, then
`Ctrl+C` or right click and **Copy**. **Furigana is never copied**: the
clipboard gets 日本, not にほん, so what you paste elsewhere is the text as
written. On X11 the clipboard is owned by the running application, so paste
before closing the last note.

## Not implemented yet

* **Traces**: stroke order animation (menu entry present but disabled)
* persisting position, size, colour and options between runs
* 20 of the N1 kanji are used almost only in names and have no common word;
  those notes show the readings instead
