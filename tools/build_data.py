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
JMdict           vocabulary, frequency markers, en/fr/es glosses (CC BY-SA 4.0)
JmdictFurigana   which kanji in a word takes which reading       (CC BY-SA 4.0)
Tanaka corpus    example sentences with English translations     (CC BY 2.0 FR)

The JLPT no longer publishes official kanji lists (it stopped in 2010), so
the N5..N1 assignment is Jonathan Waller's widely used reconstruction, as
shipped by kanji-data. It is an approximation, not an official list.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import io
import json
import re
import tarfile
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
    # The full JMdict, not JMdict_e: it carries the French and Spanish word
    # glosses as well as the English ones (11 MB more to download, build time
    # only).
    "JMdict.gz": "http://ftp.edrdg.org/pub/Nihongo/JMdict.gz",
    "examples.utf.gz": "http://ftp.edrdg.org/pub/Nihongo/examples.utf.gz",
    "JmdictFurigana.json.tar.gz": (
        "https://github.com/Doublevil/JmdictFurigana/releases/download/"
        "2.3.1%2B2026-07-25/JmdictFurigana.json.tar.gz"
    ),
    # Tatoeba, for the French and Spanish translations. The Tanaka corpus
    # sentences are Tatoeba sentences, and its #ID= field carries the Tatoeba
    # id, so the two join directly.
    "fra_sentences.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/fra/fra_sentences.tsv.bz2",
    "spa_sentences.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/spa/spa_sentences.tsv.bz2",
    "links.tar.bz2": "https://downloads.tatoeba.org/exports/links.tar.bz2",
    # Stroke order outlines, for the writing animation.
    "kanjivg.xml.gz": (
        "https://github.com/KanjiVG/kanjivg/releases/download/"
        "r20250816/kanjivg-20250816.xml.gz"
    ),
}

LANGUAGES = ("en", "fr", "es")

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
    glosses: dict[str, str]  # language code -> meaning, "en" always present
    score: int  # lower is more common
    common: bool


# JMdict tags its glosses with ISO 639-2 codes; untagged means English.
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
GLOSS_LANGUAGES = {"eng": "en", "fre": "fr", "spa": "es"}


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

            senses = entry.findall("sense")
            if not senses:
                entry.clear()
                continue
            misc = " ".join(m.text or "" for m in senses[0].findall("misc")).lower()
            if any(tag in misc for tag in SKIP_MISC):
                entry.clear()  # archaic, poetical, ... : not worth learning
                continue

            # Each language sits in its own <sense>, so the English meaning
            # comes from the first sense and the others from wherever they
            # are. They are not guaranteed to describe the same sense: JMdict
            # carries no mapping between them.
            glosses: dict[str, str] = {}
            english = [g.text for g in senses[0].findall("gloss") if g.text][:2]
            if not english:
                entry.clear()
                continue
            glosses["en"] = "; ".join(english)
            for sense in senses:
                for gloss in sense.findall("gloss"):
                    code = GLOSS_LANGUAGES.get(gloss.get(XML_LANG) or "eng")
                    if code and code != "en" and gloss.text:
                        current = glosses.get(code)
                        if current is None:
                            glosses[code] = gloss.text
                        elif current.count(";") < 1:
                            glosses[code] = f"{current}; {gloss.text}"

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

# A Tanaka B-line token: headword(reading)[sense]{surface as written}~
_TOKEN_RE = re.compile(
    r"^(?P<head>[^\s({\[~]+)"
    r"(?:\((?P<read>[^)]*)\))?"
    r"(?:\[[^\]]*\])?"
    r"(?:\{(?P<surf>[^}]*)\})?"
)
_LATIN_DIGIT_RE = re.compile(r"[A-Za-z0-9０-９]")


@dataclass(slots=True)
class Example:
    """One example sentence, annotated and translated."""

    jid: str
    text: str
    furigana: list[tuple[str, str]]
    complete: bool  # every kanji got a reading
    translations: dict[str, str]


class Annotator:
    """Adds per-kanji furigana to a sentence, without a morphological analyser.

    The Tanaka corpus already lists the dictionary form of every word in a
    sentence, and JmdictFurigana knows how each dictionary form is read, so
    the two together are enough: look each word up, then map its readings
    onto the inflected form as actually written.
    """

    def __init__(self, table: dict[tuple[str, str], list[tuple[str, str]]]) -> None:
        self.by_pair = table
        self.by_text: dict[str, list[list[tuple[str, str]]]] = defaultdict(list)
        for (text, _reading), segments in table.items():
            self.by_text[text].append(segments)

    def _segments_for(self, head: str, reading: str | None) -> list[tuple[str, str]] | None:
        if reading and (head, reading) in self.by_pair:
            return self.by_pair[(head, reading)]
        options = self.by_text.get(head)
        if not options:
            return None
        # Homographs (言う read いう or ゆう): the corpus spells the reading
        # out only when it is the unusual one, so the primary entry is right.
        return options[0]

    @staticmethod
    def _onto_surface(surface: str, segments: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Map a dictionary form's readings onto the inflected surface form.

        会う → [(会,あ),(う,)] applied to 会えない gives [(会,あ),(えない,)]:
        the kanji keeps its reading, the okurigana is taken as written.
        """
        out: list[tuple[str, str]] = []
        cursor = 0
        for ruby, rt in segments:
            if not rt:
                continue  # kana in the dictionary form; may have inflected
            at = surface.find(ruby, cursor)
            if at < 0:
                continue
            if at > cursor:
                out.append((surface[cursor:at], ""))
            out.append((ruby, rt))
            cursor = at + len(ruby)
        if cursor < len(surface):
            out.append((surface[cursor:], ""))
        return out

    def annotate(self, sentence: str, bline: str) -> tuple[list[tuple[str, str]], bool]:
        """Return (segments, every kanji has a reading)."""
        out: list[tuple[str, str]] = []
        cursor = 0
        for raw in bline.split():
            match = _TOKEN_RE.match(raw)
            if not match:
                continue
            head, reading, surf = match.group("head"), match.group("read"), match.group("surf")
            surface = surf or head
            at = sentence.find(surface, cursor)
            if at < 0:
                continue
            if at > cursor:
                out.append((sentence[cursor:at], ""))
            if not KANJI_RE.search(surface):
                out.append((surface, ""))
            else:
                segments = self._segments_for(head, reading) or self._segments_for(surface, None)
                if segments:
                    out.extend(self._onto_surface(surface, segments))
                elif reading and surface == head:
                    out.append((surface, reading))
                else:
                    out.append((surface, ""))  # no reading found
            cursor = at + len(surface)
        if cursor < len(sentence):
            out.append((sentence[cursor:], ""))

        merged: list[tuple[str, str]] = []
        for text, rt in out:
            if not rt and merged and not merged[-1][1]:
                merged[-1] = (merged[-1][0] + text, "")
            else:
                merged.append((text, rt))

        unread = sum(len(KANJI_RE.findall(t)) for t, rt in merged if not rt)
        return merged, unread == 0


def load_translations(
    links_path: Path, language_paths: dict[str, Path], japanese_ids: set[str]
) -> dict[str, dict[str, str]]:
    """Tatoeba id -> {"fr": ..., "es": ...} for the sentences we care about."""
    # Which foreign sentences are linked to our Japanese ones?
    linked: dict[str, list[str]] = defaultdict(list)
    targets: set[str] = set()
    with tarfile.open(links_path, "r:bz2") as archive:
        member = next(m for m in archive.getmembers() if m.name.endswith(".csv"))
        stream = archive.extractfile(member)
        assert stream is not None
        for line in io.TextIOWrapper(stream, encoding="utf-8"):
            left, _, right = line.rstrip("\n").partition("\t")
            if left in japanese_ids:
                linked[left].append(right)
                targets.add(right)

    translations: dict[str, dict[str, str]] = defaultdict(dict)
    for language, path in language_paths.items():
        text_by_id: dict[str, str] = {}
        with bz2.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")  # id, language, text
                if len(parts) == 3 and parts[0] in targets:
                    text_by_id[parts[0]] = parts[2]
        for japanese_id, others in linked.items():
            for other in others:
                if other in text_by_id:
                    # Keep the shortest translation: they are usually the
                    # plainest, and the note has little room.
                    current = translations[japanese_id].get(language)
                    if current is None or len(text_by_id[other]) < len(current):
                        translations[japanese_id][language] = text_by_id[other]
    return translations


def load_sentences(
    path: Path, wanted_words: set[str], annotator: Annotator
) -> tuple[dict[str, Example], dict[str, list[str]]]:
    """Parse the Tanaka corpus into annotated examples indexed by word."""
    examples: dict[str, Example] = {}
    by_word: dict[str, list[str]] = defaultdict(list)
    japanese = english = jid = ""

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("A: "):
                body = line[3:].rstrip("\n")
                parts = body.split("\t")
                japanese = parts[0]
                english = jid = ""
                if len(parts) > 1:
                    english, _, ident = parts[1].partition("#ID=")
                    # "#ID=<english id>_<japanese id>": the Japanese sentence
                    # is the second one, which is the id Tatoeba links use.
                    jid = ident.split("_")[-1].strip() if ident else ""
            elif line.startswith("B: ") and japanese and english and jid:
                heads = []
                for token in line[3:].split():
                    match = _TOKEN_RE.match(token)
                    if match:
                        heads.append(match.group("head"))
                if any(head in wanted_words for head in heads):
                    if jid not in examples:
                        segments, complete = annotator.annotate(japanese, line[3:].rstrip("\n"))
                        examples[jid] = Example(
                            jid=jid,
                            text=japanese,
                            furigana=segments,
                            complete=complete,
                            translations={"en": english.strip()},
                        )
                    for head in set(heads):
                        if head in wanted_words and len(by_word[head]) < 200:
                            by_word[head].append(jid)
                japanese = english = jid = ""

    return examples, by_word


def sentence_cost(example: Example, level_rank: int, levels_of: dict[str, str]) -> int:
    """How well a sentence suits a learner at this level. Lower is better.

    A learner at N5 should get everyday sentences built from N5 kanji, not a
    grammatically fine sentence bristling with N1 characters.
    """
    cost = 0
    for char in KANJI_RE.findall(example.text):
        level = levels_of.get(char)
        if level is None:
            cost += 400  # not a JLPT kanji: certainly too hard
        else:
            harder = LEVELS.index(level) - level_rank
            if harder > 0:
                cost += 190 * harder

    # Everyday sentences are short ones. Around 16 characters reads well on
    # a post-it; much longer and it wraps into a wall of text.
    cost += 4 * abs(len(example.text) - 16)
    if len(example.text) > 34:
        cost += 250

    if not example.complete:
        cost += 400  # cannot be fully furigana'd, so it cannot be read
    if _LATIN_DIGIT_RE.search(example.text):
        cost += 60  # dates, measurements, acronyms: rarely casual speech
    return cost


# Sentences within this much of the best score are treated as equally
# suitable for the level, so the tie can be broken on something else.
_LEVEL_SLACK = 120


def pick_sentence(
    candidates: list[Example], level_rank: int, levels_of: dict[str, str]
) -> Example | None:
    """The best example for this level, preferring fully translated ones.

    Tatoeba has a French or Spanish translation for only about a fifth of
    its Japanese sentences. Rather than let that drag in harder sentences,
    the level fit is settled first and the translations only break ties.
    """
    if not candidates:
        return None
    scored = [(sentence_cost(e, level_rank, levels_of), e) for e in candidates]
    floor = min(cost for cost, _ in scored)
    shortlist = [(cost, e) for cost, e in scored if cost <= floor + _LEVEL_SLACK]
    return min(shortlist, key=lambda pair: (-len(pair[1].translations), pair[0]))[1]


# --------------------------------------------------------------------- build


@dataclass
class Stats:
    kanji: int = 0
    with_words: int = 0
    with_sentences: int = 0
    words: int = 0
    vocabulary: int = 0  # extra words for the vocabulary side
    sentences: int = 0
    sentences_annotated: int = 0
    sentences_on_level: int = 0  # every kanji at or below the target level
    above_level_kanji: int = 0  # how many too-hard kanji, in total
    readings_unknown: int = 0
    translated: dict[str, int] = field(default_factory=lambda: {k: 0 for k in LANGUAGES})
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
            "m": dict(vocab.glosses),
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


_SVG_NUMBER = re.compile(r"-?\d*\.?\d+")


def load_strokes(path: Path, wanted: set[str]) -> dict[str, list[str]]:
    """Stroke outlines per kanji, in KanjiVG's 109x109 box.

    The SVG path strings are kept as they are rather than flattened into
    point lists: they are smaller that way, and the application can then
    flatten them to whatever size the note is being drawn at.
    """
    strokes: dict[str, list[str]] = {}
    with gzip.open(path, "rb") as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            # Note: only kanji elements are cleared. Clearing the others
            # would throw away the paths before they can be read.
            if not element.tag.endswith("kanji"):
                continue
            try:
                char = chr(int(element.get("id", "").split("_")[-1], 16))
            except ValueError:
                element.clear()
                continue
            if char in wanted:
                paths = [
                    _shrink(node.get("d", ""))
                    for node in element.iter()
                    if node.tag.endswith("path") and node.get("d")
                ]
                if paths:
                    strokes[char] = paths
            element.clear()
    return strokes


def _shrink(path: str) -> str:
    """Round the coordinates: a hundredth of a 109 unit box is invisible."""
    return _SVG_NUMBER.sub(lambda m: f"{float(m.group()):.1f}".rstrip("0").rstrip("."), path)


EXTRA_VOCABULARY = 10  # more than fits on a note, so resizing shows more


def pick_vocabulary(
    kanji: Kanji,
    candidates: list[Vocab],
    furigana: dict[tuple[str, str], list[tuple[str, str]]],
    levels_of: dict[str, str],
    sentences: dict[str, list[str]],
    already_shown: list[dict],
) -> list[dict]:
    """More words using this kanji, for the vocabulary side of the note.

    The recto shows one word per reading; this is the next most common
    vocabulary, so that flipping the note can show breadth instead of
    example sentences.
    """
    taken = {word["t"] for word in already_shown}
    scored: list[tuple[int, dict]] = []
    for vocab in candidates:
        if vocab.text in taken:
            continue
        segments = furigana.get((vocab.text, vocab.reading))
        if not segments:
            continue  # without alignment the ruby cannot be placed
        taken.add(vocab.text)
        cost = word_cost(vocab, kanji, levels_of, vocab.text in sentences)
        # JMdict translates only part of its entries into French and Spanish.
        # Among words of comparable usefulness, prefer the translated ones so
        # that a note read in French is not mostly English fallbacks.
        cost += 25 * (len(LANGUAGES) - len(vocab.glosses))
        scored.append((cost, {
            "t": vocab.text,
            "r": vocab.reading,
            "f": [[ruby, rt] for ruby, rt in segments],
            "m": dict(vocab.glosses),
        }))
    scored.sort(key=lambda pair: pair[0])
    return [word for _cost, word in scored[:EXTRA_VOCABULARY]]


def build(levels: list[str], cache_dir: Path, out_dir: Path) -> dict[str, Stats]:
    print("sources:")
    paths = {name: fetch(name, cache_dir) for name in SOURCES}

    print("loading kanji list ...", flush=True)
    meanings = load_meanings(paths["kanjidic2.xml.gz"])
    all_kanji = load_kanji(paths["kanji-data.json"], meanings)
    targets = {c: k for c, k in all_kanji.items() if k.level in levels}
    print(f"  {len(targets)} kanji across {', '.join(levels)}")

    print("loading vocabulary (JMdict) ...", flush=True)
    vocab = load_vocab(paths["JMdict.gz"], set(targets))
    print(f"  {sum(len(v) for v in vocab.values())} word/kanji pairs")

    print("loading furigana alignment ...", flush=True)
    furigana = load_furigana(paths["JmdictFurigana.json.tar.gz"], cache_dir)
    print(f"  {len(furigana)} aligned words")

    # Sentences are loaded before the words are chosen, so that a word that
    # can be illustrated is preferred over one that cannot.
    print("reading example sentences (Tanaka corpus) ...", flush=True)
    candidate_texts = {v.text for words in vocab.values() for v in words}
    annotator = Annotator(furigana)
    examples, sentence_ids = load_sentences(paths["examples.utf.gz"], candidate_texts, annotator)
    complete = sum(1 for e in examples.values() if e.complete)
    print(f"  {len(examples)} sentences for {len(sentence_ids)} words")
    print(f"  {complete} ({complete / max(1, len(examples)):.0%}) fully furigana annotated")

    print("linking French and Spanish translations (Tatoeba) ...", flush=True)
    translations = load_translations(
        paths["links.tar.bz2"],
        {"fr": paths["fra_sentences.tsv.bz2"], "es": paths["spa_sentences.tsv.bz2"]},
        set(examples),
    )
    for jid, extra in translations.items():
        examples[jid].translations.update(extra)
    have = {lang: sum(1 for e in examples.values() if lang in e.translations) for lang in LANGUAGES}
    print("  translations: " + ", ".join(f"{k}={v}" for k, v in have.items()))

    print("selecting words ...", flush=True)
    levels_of = {char: k.level for char, k in all_kanji.items()}
    stats = {level: Stats() for level in levels}
    chosen: dict[str, list[dict]] = {}
    for char, kanji in targets.items():
        chosen[char] = pick_words(
            kanji, vocab.get(char, []), furigana, levels_of, sentence_ids, stats[kanji.level]
        )
    print(f"  {len({w['t'] for ws in chosen.values() for w in ws})} distinct words chosen")

    print("collecting extra vocabulary ...", flush=True)
    extra: dict[str, list[dict]] = {}
    for char, kanji in targets.items():
        extra[char] = pick_vocabulary(
            kanji, vocab.get(char, []), furigana, levels_of, sentence_ids, chosen[char]
        )
    print(f"  {sum(len(v) for v in extra.values())} extra words")

    print("reading stroke order outlines (KanjiVG) ...", flush=True)
    strokes = load_strokes(paths["kanjivg.xml.gz"], set(targets))
    print(f"  {len(strokes)} of {len(targets)} kanji have stroke data")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Stroke outlines live in their own file: they are only read when the
    # writing animation is played, and they come from a different source.
    stroke_file = out_dir / "strokes.json.gz"
    with gzip.open(stroke_file, "wt", encoding="utf-8") as out:
        json.dump(
            {
                "viewbox": 109,
                "source": "KanjiVG (CC BY-SA 3.0)",
                "kanji": strokes,
            },
            out,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    print(f"  wrote {stroke_file.name}  {stroke_file.stat().st_size / 1024:.1f} KiB")

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

            # One example sentence per word, chosen for this level.
            has_sentence = False
            level_rank = LEVELS.index(level)
            used_ids: set[str] = set()
            for word in words:
                candidates = [
                    examples[jid]
                    for jid in sentence_ids.get(word["t"], ())
                    if jid not in used_ids
                ]
                best = pick_sentence(candidates, level_rank, levels_of)
                if best is None:
                    continue
                used_ids.add(best.jid)
                word["s"] = {
                    "t": best.text,
                    "f": [[text, rt] for text, rt in best.furigana],
                    "tr": {k: v for k, v in best.translations.items() if v},
                }
                stat.sentences += 1
                if best.complete:
                    stat.sentences_annotated += 1
                too_hard = sum(
                    1
                    for ch in KANJI_RE.findall(best.text)
                    if levels_of.get(ch) is None or LEVELS.index(levels_of[ch]) > level_rank
                )
                stat.above_level_kanji += too_hard
                if not too_hard:
                    stat.sentences_on_level += 1
                for language in LANGUAGES:
                    if language in best.translations:
                        stat.translated[language] += 1
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
                "v": extra.get(char, []),
            })
            stat.vocabulary += len(extra.get(char, []))

        payload = {
            "level": level,
            "count": len(records),
            "sources": [
                "kanji-data (CC BY 4.0)",
                "KANJIDIC2 (CC BY-SA 4.0, EDRDG)",
                "JMdict (CC BY-SA 4.0, EDRDG)",
                "JmdictFurigana (CC BY-SA 4.0)",
                "Tanaka corpus (CC BY 2.0 FR)",
                "Tatoeba (CC BY 2.0 FR)",
            ],
            "languages": list(LANGUAGES),
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

    print(
        "\nlevel  kanji  words  vocab  sentences  furigana  on-level  too-hard"
        "      en      fr      es"
    )
    for level, stat in stats.items():
        done = stat.sentences or 1
        print(
            f"{level:>5} {stat.kanji:6d} {stat.words:6d} {stat.vocabulary:6d} {stat.sentences:10d}"
            f" {stat.sentences_annotated / done:8.0%}"
            f" {stat.sentences_on_level / done:9.0%}"
            f" {stat.above_level_kanji / done:9.2f}"
            + "".join(f" {stat.translated[lang] / done:7.0%}" for lang in LANGUAGES)
        )
        if stat.missing:
            shown = "".join(stat.missing[:20])
            print(f"       no word found for {len(stat.missing)}: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
