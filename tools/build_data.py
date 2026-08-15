#!/usr/bin/env python3
"""Build the bundled kanji data set for mainichi.

Downloads the open Japanese data sets, cross references them and writes one
compressed file per JLPT level into ``mainichi/data/``. The application
itself never needs the network: this runs at development time and the result
is committed.

    python tools/build_data.py                # download (cached) and build
    python tools/build_data.py --levels N5    # just one level, for a quick look
    python tools/build_data.py --report       # show what was produced

Sources
-------
kanji-data       kanji list per JLPT level, meanings, readings   (CC BY 4.0)
JMdict_e         vocabulary with frequency markers               (CC BY-SA 4.0)
JmdictFurigana   which kanji in a word takes which reading       (CC BY-SA 4.0)
Tanaka corpus    example sentences with English translations     (CC BY 2.0 FR)

The JLPT no longer publishes official kanji lists (it stopped in 2010), so
the N5..N1 assignment is Jonathan Waller's widely used reconstruction, as
shipped by kanji-data. It is an approximation, not an official list.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import tarfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "mainichi" / "data"
CACHE_DIR = REPO / ".datacache"

SOURCES = {
    "kanji-data.json": "https://raw.githubusercontent.com/davidluzgouveia/kanji-data/master/kanji.json",
    "kanjidic2.xml.gz": "http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz",
    "JMdict_e.gz": "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
    "examples.utf.gz": "http://ftp.edrdg.org/pub/Nihongo/examples.utf.gz",
    "JmdictFurigana.json.tar.gz": (
        "https://github.com/Doublevil/JmdictFurigana/releases/download/"
        "2.3.1%2B2026-07-25/JmdictFurigana.json.tar.gz"
    ),
}

LEVELS = ("N5", "N4", "N3", "N2", "N1")
WORDS_PER_KANJI = 4  # at most one per distinct reading; the note shows 3 well

KANA_RANGE = ("぀", "ヿ")
KANJI_RE = re.compile(r"[一-鿿㐀-䶿]")

# Rendaku (連濁): a reading can voice when it is not word initial.
UNVOICE = str.maketrans(
    "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ",
    "かきくけこさしすせそたちつてとはひふへほはひふへほ",
)


# --------------------------------------------------------------------- fetch


def fetch(name: str, cache_dir: Path) -> Path:
    """Download a source file once and keep it in the cache directory."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    if path.exists() and path.stat().st_size > 0:
        return path
    url = SOURCES[name]
    print(f"  downloading {name} ...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "mainichi-build"})
    with urllib.request.urlopen(request, timeout=300) as response, path.open("wb") as out:
        out.write(response.read())
    return path


# --------------------------------------------------------------------- kanji


@dataclass(slots=True)
class Kanji:
    char: str
    level: str
    meanings: list[str]
    on: list[str]
    kun: list[str]
    strokes: int
    freq: int  # newspaper frequency rank, 0 when unranked


def load_meanings(path: Path) -> dict[str, list[str]]:
    """English meanings from KANJIDIC2.

    kanji-data title cases its meanings ("Counter For Days", "Japan" and
    "japan" indistinguishable), so the meanings come from KANJIDIC2 instead,
    which cases them the way a dictionary would.
    """
    meanings: dict[str, list[str]] = {}
    with gzip.open(path, "rb") as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            if element.tag != "character":
                continue
            literal = element.findtext("literal")
            if literal:
                english = [
                    m.text
                    for m in element.findall("reading_meaning/rmgroup/meaning")
                    if m.text and not m.get("m_lang")  # untagged means English
                ]
                if english:
                    meanings[literal] = english[:4]
            element.clear()
    return meanings


def load_kanji(path: Path, meanings: dict[str, list[str]]) -> dict[str, Kanji]:
    """Every kanji that has a JLPT level, keyed by the character."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    kanji: dict[str, Kanji] = {}
    for char, entry in raw.items():
        level_number = entry.get("jlpt_new")
        if not level_number:
            continue
        fallback = [m.lower() for m in entry.get("meanings", [])][:4]
        kanji[char] = Kanji(
            char=char,
            level=f"N{level_number}",
            meanings=meanings.get(char, fallback),
            on=[r for r in entry.get("readings_on", [])],
            kun=[r for r in entry.get("readings_kun", [])],
            strokes=entry.get("strokes", 0) or 0,
            freq=entry.get("freq") or 0,
        )
    return kanji


def reading_stem(reading: str) -> str:
    """``あか.い`` -> ``あか``, ``-び`` -> ``び``: the part written in kanji."""
    return reading.split(".")[0].strip("-").strip()


# ---------------------------------------------------------------- vocabulary


@dataclass(slots=True)
class Vocab:
    text: str
    reading: str
    glosses: list[str]
    score: int  # lower is more common
    common: bool


# JMdict priority markers, best (most common) first.
_NF_RE = re.compile(r"nf(\d+)")

# Senses carrying one of these is not what a learner should be shown.
SKIP_MISC = (
    "archaic",
    "obsolete",
    "obscure",
    "poetical",
    "rare",
    "dated",
    "slang",
    "vulgar",
    "derogatory",
)


def _priority(tags: list[str]) -> tuple[int, bool]:
    """Turn JMdict priority tags into a sortable score."""
    if not tags:
        return 999, False
    score = 500
    common = False
    for tag in tags:
        match = _NF_RE.fullmatch(tag)
        if match:  # nf01 = the 500 most common words, nf48 the rarest band
            score = min(score, int(match.group(1)))
            common = True
        elif tag in ("news1", "ichi1", "spec1"):
            score = min(score, 20)
            common = True
        elif tag in ("news2", "ichi2", "spec2"):
            score = min(score, 40)
            common = True
        elif tag == "gai1":
            score = min(score, 30)
            common = True
    return score, common


def load_vocab(path: Path, wanted: set[str]) -> dict[str, list[Vocab]]:
    """Words from JMdict that contain one of the wanted kanji, per kanji."""
    by_kanji: dict[str, list[Vocab]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()

    with gzip.open(path, "rb") as handle:
        # JMdict declares its tag entities in an internal DTD subset, which
        # expat expands on its own; no entity handling is needed here.
        for _event, entry in ET.iterparse(handle, events=("end",)):
            if entry.tag != "entry":
                continue

            kanji_forms = entry.findall("k_ele")
            if not kanji_forms:
                entry.clear()
                continue

            keb = kanji_forms[0].findtext("keb", "")
            characters = set(KANJI_RE.findall(keb))
            if not characters & wanted:
                entry.clear()
                continue

            reading_element = entry.find("r_ele")
            reb = reading_element.findtext("reb", "") if reading_element is not None else ""
            if not reb:
                entry.clear()
                continue

            tags = [t.text for t in kanji_forms[0].findall("ke_pri") if t.text]
            if reading_element is not None:
                tags += [t.text for t in reading_element.findall("re_pri") if t.text]
            score, common = _priority(tags)

            sense = entry.find("sense")
            glosses = []
            if sense is not None:
                misc = " ".join(m.text or "" for m in sense.findall("misc")).lower()
                if any(tag in misc for tag in SKIP_MISC):
                    entry.clear()  # archaic, poetical, ... : not worth learning
                    continue
                glosses = [g.text for g in sense.findall("gloss") if g.text][:2]
            if not glosses:
                entry.clear()
                continue

            if (keb, reb) not in seen:
                seen.add((keb, reb))
                vocab = Vocab(keb, reb, glosses, score, common)
                for char in characters & wanted:
                    by_kanji[char].append(vocab)
            entry.clear()

    for words in by_kanji.values():
        words.sort(key=lambda v: (v.score, len(v.text)))
    return by_kanji


# ------------------------------------------------------------------ furigana


def load_furigana(path: Path, cache_dir: Path) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(word, reading) -> [(ruby, rt), ...] segment list."""
    extracted = cache_dir / "JmdictFurigana.json"
    if not extracted.exists():
        with tarfile.open(path, "r:gz") as archive:
            archive.extractall(cache_dir, filter="data")
    table: dict[tuple[str, str], list[tuple[str, str]]] = {}
    entries = json.loads(extracted.read_text(encoding="utf-8-sig"))
    for entry in entries:
        segments = [(s["ruby"], s.get("rt", "")) for s in entry["furigana"]]
        table[(entry["text"], entry["reading"])] = segments
    return table


KATAKANA_RE = re.compile(r"[ァ-ヿ]")


def reading_of(kanji: str, segments: list[tuple[str, str]]) -> str:
    """Which reading this kanji takes in the word, '' if it cannot be told.

    Irregular words such as 日本 (にほん) are annotated as a single unsplit
    block, so no reading can be attributed to the individual kanji. Those
    words are still worth showing; they are handled separately.
    """
    for ruby, rt in segments:
        if ruby == kanji:
            # A katakana "reading" means the entry is a letter name or an
            # abbreviation (一 read イー), never a real kanji reading.
            return "" if KATAKANA_RE.search(rt) else rt
    return ""


def canonical_reading(kanji: Kanji, used: str) -> str:
    """Map a reading as used in a word back to a dictionary reading.

    Handles rendaku (ひ -> び in 日曜日) and gemination (にち -> にっ in
    日本), so that 毎日 and 日曜日 are not mistaken for two readings.
    """
    if not used:
        return ""
    candidates = [reading_stem(r) for r in (*kanji.on, *kanji.kun)]
    candidates = [c for c in candidates if c]

    plain = used.translate(UNVOICE)
    for candidate in candidates:
        if used == candidate or plain == candidate:
            return candidate
    # Gemination: にち -> にっ, はつ -> はっ
    for candidate in candidates:
        if len(used) == len(candidate) and used.endswith("っ") and plain[:-1] == candidate[:-1]:
            return candidate
    # Truncation in compounds, e.g. がく -> が
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate.startswith(plain) or plain.startswith(candidate):
            return candidate
    # Nothing in the dictionary matches: an irregular reading such as 一 read
    # いっち. Reporting it as its own reading would invent a pronunciation.
    return ""


# ----------------------------------------------------------------- sentences

_TOKEN_RE = re.compile(r"^([^\s({\[~]+)")


def load_sentences(path: Path, wanted_words: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Word -> [(japanese, english), ...] from the Tanaka corpus."""
    by_word: dict[str, list[tuple[str, str]]] = defaultdict(list)
    japanese = english = ""

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("A: "):
                body = line[3:].rstrip("\n")
                parts = body.split("\t")
                japanese = parts[0]
                english = parts[1].split("#ID=")[0] if len(parts) > 1 else ""
            elif line.startswith("B: ") and japanese and english:
                for token in line[3:].split():
                    match = _TOKEN_RE.match(token)
                    if not match:
                        continue
                    head = match.group(1)
                    if head in wanted_words and len(by_word[head]) < 50:
                        by_word[head].append((japanese, english))
                japanese = english = ""

    # Short, complete sentences make the better examples.
    for word, pairs in by_word.items():
        pairs.sort(key=lambda p: (abs(len(p[0]) - 18), len(p[1])))
        by_word[word] = pairs[:3]
    return by_word


# --------------------------------------------------------------------- build


@dataclass
class Stats:
    kanji: int = 0
    with_words: int = 0
    with_sentences: int = 0
    words: int = 0
    sentences: int = 0
    readings_unknown: int = 0
    missing: list[str] = field(default_factory=list)


def word_cost(
    vocab: Vocab,
    kanji: Kanji,
    levels_of: dict[str, str],
    has_sentence: bool,
) -> int:
    """How suitable a word is as an example for this kanji. Lower is better.

    A learner meeting 日 at N5 wants 日本 and 毎日, not 日米 or 三十日, so
    raw dictionary frequency is only the starting point.
    """
    cost = vocab.score

    # Words written with kanji harder than the one being taught are a poor
    # example: the learner cannot read them yet.
    own_rank = LEVELS.index(kanji.level)  # N5 -> 0, N1 -> 4
    for char in KANJI_RE.findall(vocab.text):
        if char == kanji.char:
            continue
        other = levels_of.get(char)
        if other is None:
            cost += 250  # not a JLPT kanji at all
        else:
            harder = LEVELS.index(other) - own_rank
            if harder > 0:
                cost += 60 * harder

    # Short compounds teach the reading best; 在監の長 does not.
    cost += 45 * max(0, len(vocab.text) - 3)
    if "の" in vocab.text or " " in vocab.text:
        cost += 300  # a phrase, not a word
    if not vocab.common:
        cost += 120
    if not has_sentence:
        cost += 80  # the verso needs an example sentence
    return cost


def pick_words(
    kanji: Kanji,
    candidates: list[Vocab],
    furigana: dict[tuple[str, str], list[tuple[str, str]]],
    levels_of: dict[str, str],
    sentences: dict[str, list[tuple[str, str]]],
    stats: Stats,
) -> list[dict]:
    """One word per distinct reading of the kanji, most common first."""

    def record(vocab: Vocab, segments, used: str, cost: int) -> dict:
        return {
            "t": vocab.text,
            "r": vocab.reading,
            "f": [[ruby, rt] for ruby, rt in segments],
            "m": "; ".join(vocab.glosses),
            "kr": used,
            "_cost": cost,
        }

    by_reading: dict[str, dict] = {}
    irregular: list[dict] = []

    for vocab in candidates:
        segments = furigana.get((vocab.text, vocab.reading))
        if not segments:
            continue
        cost = word_cost(vocab, kanji, levels_of, vocab.text in sentences)
        used = reading_of(kanji.char, segments)

        if not used:
            # 日本 and friends: no reading attributable to this kanji alone,
            # but they are exactly the words a learner needs. Keep the best
            # one aside and use it only if there is room left over.
            if vocab.common and len(irregular) < 3:
                irregular.append(record(vocab, segments, "", cost))
            continue

        key = canonical_reading(kanji, used)
        if not key:
            # Irregular reading, not one the dictionary lists for this kanji.
            if vocab.common and len(irregular) < 3:
                irregular.append(record(vocab, segments, used, cost))
            continue
        previous = by_reading.get(key)
        if previous is None or cost < previous["_cost"]:
            by_reading[key] = record(vocab, segments, used, cost)

    # A common irregular word (日本) competes for a slot on equal terms, so
    # it can displace at most one of the regular readings.
    pool = sorted(by_reading.values(), key=lambda w: w["_cost"])[:WORDS_PER_KANJI]
    if irregular:
        best = min(irregular, key=lambda w: w["_cost"])
        if best["t"] not in {w["t"] for w in pool}:
            pool = sorted([*pool, best], key=lambda w: w["_cost"])[:WORDS_PER_KANJI]
    words = pool

    # Most common on the left, as the note is meant to be read.
    words.sort(key=lambda w: w["_cost"])
    for word in words:
        word.pop("_cost", None)
        if not word["kr"]:
            stats.readings_unknown += 1
    return words


def build(levels: list[str], cache_dir: Path, out_dir: Path) -> dict[str, Stats]:
    print("sources:")
    paths = {name: fetch(name, cache_dir) for name in SOURCES}

    print("loading kanji list ...", flush=True)
    meanings = load_meanings(paths["kanjidic2.xml.gz"])
    all_kanji = load_kanji(paths["kanji-data.json"], meanings)
    targets = {c: k for c, k in all_kanji.items() if k.level in levels}
    print(f"  {len(targets)} kanji across {', '.join(levels)}")

    print("loading vocabulary (JMdict) ...", flush=True)
    vocab = load_vocab(paths["JMdict_e.gz"], set(targets))
    print(f"  {sum(len(v) for v in vocab.values())} word/kanji pairs")

    print("loading furigana alignment ...", flush=True)
    furigana = load_furigana(paths["JmdictFurigana.json.tar.gz"], cache_dir)
    print(f"  {len(furigana)} aligned words")

    # Sentences are loaded before the words are chosen, so that a word that
    # can be illustrated is preferred over one that cannot.
    print("loading example sentences (Tanaka corpus) ...", flush=True)
    candidate_texts = {v.text for words in vocab.values() for v in words}
    sentences = load_sentences(paths["examples.utf.gz"], candidate_texts)
    print(f"  sentences found for {len(sentences)} of {len(candidate_texts)} candidate words")

    print("selecting words ...", flush=True)
    levels_of = {char: k.level for char, k in all_kanji.items()}
    stats = {level: Stats() for level in levels}
    chosen: dict[str, list[dict]] = {}
    for char, kanji in targets.items():
        chosen[char] = pick_words(
            kanji, vocab.get(char, []), furigana, levels_of, sentences, stats[kanji.level]
        )
    print(f"  {len({w['t'] for ws in chosen.values() for w in ws})} distinct words chosen")

    out_dir.mkdir(parents=True, exist_ok=True)
    for level in levels:
        records = []
        stat = stats[level]
        for char, kanji in sorted(targets.items(), key=lambda kv: (kv[1].freq or 99999)):
            if kanji.level != level:
                continue
            words = chosen[char]
            stat.kanji += 1
            if words:
                stat.with_words += 1
            else:
                stat.missing.append(char)
            stat.words += len(words)

            has_sentence = False
            for word in words:
                found = sentences.get(word["t"])
                if found:
                    japanese, english = found[0]
                    word["s"] = [japanese, english]
                    stat.sentences += 1
                    has_sentence = True
            if has_sentence:
                stat.with_sentences += 1

            records.append({
                "k": char,
                "m": kanji.meanings,
                "on": kanji.on,
                "kun": kanji.kun,
                "st": kanji.strokes,
                "fq": kanji.freq,
                "w": words,
            })

        payload = {
            "level": level,
            "count": len(records),
            "sources": [
                "kanji-data (CC BY 4.0)",
                "KANJIDIC2 (CC BY-SA 4.0, EDRDG)",
                "JMdict (CC BY-SA 4.0, EDRDG)",
                "JmdictFurigana (CC BY-SA 4.0)",
                "Tanaka corpus (CC BY 2.0 FR)",
            ],
            "kanji": records,
        }
        target = out_dir / f"{level}.json.gz"
        with gzip.open(target, "wt", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, separators=(",", ":"))
        size = target.stat().st_size / 1024
        try:
            shown = target.relative_to(REPO)
        except ValueError:  # --out-dir outside the repo
            shown = target
        print(f"  wrote {shown}  {len(records):4d} kanji  {size:7.1f} KiB")

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--levels", nargs="+", choices=LEVELS, default=list(LEVELS))
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    stats = build(args.levels, args.cache_dir, args.out_dir)

    print("\nlevel  kanji  with words  with sentences  words  sentences")
    for level, stat in stats.items():
        print(
            f"{level:>5} {stat.kanji:6d} {stat.with_words:11d} {stat.with_sentences:15d}"
            f" {stat.words:6d} {stat.sentences:10d}"
        )
        if stat.missing:
            shown = "".join(stat.missing[:20])
            print(f"       no word found for {len(stat.missing)}: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
