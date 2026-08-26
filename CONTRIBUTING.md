# Contributing to mainichi

Thanks for taking a look. This is a small project with a deliberately small
surface: a desktop post-it that shows a kanji a day. Bug reports, data
corrections and focused patches are all welcome.

## Getting set up

mainichi has **no third-party dependencies** — it runs on the standard
library and tkinter. You need Python 3.10 or newer.

```bash
git clone https://github.com/pcardaba/mainichi
cd mainichi
python -m mainichi            # run it
```

If kanji show up as empty boxes, you are missing a Japanese font
(`sudo apt install fonts-noto-cjk` on Debian/Ubuntu). If you get a
`ModuleNotFoundError: No module named 'tkinter'`, install `python3-tk`.

## Running the tests

```bash
python -m pytest
```

74 tests. The 36 that open real windows skip themselves automatically when
there is no display, so a headless run reports `38 passed, 36 skipped` and
that is a pass. To run the whole suite headlessly:

```bash
xvfb-run -a python -m pytest
```

Please run the tests before opening a pull request, and add one for any
behaviour you change. `tests/test_framework.py` holds the helpers the window
tests are built on.

## Regenerating the bundled data

`mainichi/data/*.json.gz` is generated, not hand-edited. It is committed so
that the application never needs the network at runtime. To rebuild it:

```bash
python tools/build_data.py            # all levels, needs an internet connection
python tools/build_data.py --levels N5
```

The build downloads KANJIDIC2, JMdict, JmdictFurigana, the Tanaka Corpus,
Tatoeba and KanjiVG, caches them in `.datacache/`, and takes about ten
seconds once the downloads are done.

**If you are fixing a wrong reading, a bad translation or an odd example
sentence, the fix usually belongs upstream, not here.** Those files are
built from the sources listed in [ATTRIBUTION.md](ATTRIBUTION.md); correcting
JMdict or Tatoeba fixes it for everyone and it flows back into the next
rebuild. Open an issue here if you are not sure which upstream owns it.

Changes to `tools/build_data.py` that alter selection or scoring should say
in the pull request how the coverage table in the README moves.

## Architecture in one paragraph

The presentation layer only ever reads a `KanjiCard` and asks a
`CardProvider` for the next one, so the UI in `mainichi/ui/` knows nothing
about where cards come from. Keep that seam intact: data work belongs in
`dataset.py` / `content.py`, drawing and input belong in `ui/`. The layout
in the README's Architecture section is the map.

## Licensing

Two licences, and the split matters:

* **The code** is Apache-2.0. By contributing code you agree it is released
  under that licence.
* **The data** in `mainichi/data/` is CC BY-SA 4.0, inherited from its
  sources. It is not ours to relicense.

Do not add data from a source whose licence is unclear or incompatible with
CC BY-SA, and add any new source to `ATTRIBUTION.md` in the same pull
request.

## Style

Match the surrounding code. It is plain, typed where it helps, and comments
explain *why* rather than restating the line. No formatter is enforced.
