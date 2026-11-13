#!/usr/bin/env python3
"""Does this video *name the topic's work*? (CF-0272)

Why this module exists. Discovery asks YouTube for a topic by its title and
takes the answer back ordered by view count (`fetch_youtube_signal.py`,
`order=viewCount`). The Data API's `q` is a relevance search, not a filter: it
happily answers a query with video it considers related through the channel
and the network rather than through the words of the query. On the topic
"Wren Hollow" (the Example Max series) that produced, in two batches running -
`example-film/2026-09-17T1901Z` and `2026-09-18T1058Z` - five uploads from the
Example Max channel about **other** Example Max shows:

    RgptVRnT4XI  2,488,566  Example Max  Harbourlights | Episode 6 Preview | Example Max
    -05WmSAmLK4  2,078,310  Example Max  Harbourlights | Midseason Trailer | Example Max
    COipU_RnqI8    329,582  Example Max  Harbourlights | Inside Episode 5 | Example Max
    _tahRnssfIE    107,394  Example Max  Harbourlights | Kyle Chandler & Aaron Pryce ...
    ZybkHGaoPvQ    203,414  Example Max  WAR | Official Trailer | Example Max

Nothing downstream could catch them. `footage_candidates.py` classifies an
upload by the *nature of the footage* ("trailer", "episode clip") and collapses
same-cut reuploads; a Harbourlights trailer is a perfectly good trailer of a
perfectly wrong work, so it was kept, and because the pool is ordered by views
inside each nature, 2.5M and 2.1M views put the two of them at the head of the
list. The indexer spent its two canonical downloads on them and the researcher
dropped the topic (`pool_too_thin`, 0/6 anchors). The two-source gate is no
help either: two Harbourlights uploads are genuinely *independent* footage, so the
CF-0080 fingerprint passes them. Independence is not relevance, which is the
whole of CF-0272.

The rule here is the cheapest thing that is also honest: **a video belongs to
a topic only if it names the topic's work in its own metadata** - its title,
failing that its description, failing that the channel's name. Never the
network: "Example Max" is exactly the string that let Harbourlights in.

Normalisation is `fact_probe_topics.normalise`, the same one the fact probe
resolves `title_ref` with, so "'Wren Hollow'" and "WREN HOLLOW" are the same
string here and there. What counts as naming the work is deliberately generous,
because a false drop costs a real candidate:

  * the full name, and for a name with a colon both the stem and the subtitle -
    "The Famine Trials: Sunrise on the Reaping" is named by "Sunrise on the
    Reaping" alone (SzAYr5leH0E, EjCspdsvZ48), "Spire-Runner: Fresh Dawn" by
    "Fresh Dawn", "The Traitors: New Blood" by "New Blood";
  * `parent_work`, when the topic has one;
  * each of those without a leading article ("FAMINE TRIALS : Lever de Soleil",
    rLPSbyHHTFc, does not print "The") and without a trailing sequel number
    ("Sandra Birch and Nora Kingsley on returning to Everyday Sorcery");
  * the space-less form, because a hashtag has no spaces: "#wrenhollow"
    (QJ1WSiMUVFA), "#spirerunner", "#PinePark";
  * acronyms of three letters or more: "SVU", "BND", "SOTR". Two-letter ones
    ("HP", "RE", "SP") are not generated - they collide with ordinary words and
    the topics that would need them are already carried by the space-less form.

What the rule does **not** do is translate. A localised title that prints only
the local name ("Jogos Vorazes", "LOS JUEGOS DEL HAMBRE") and a title in a
non-Latin script ("ГАРРИ ПОТТЕР", "哈利波特") are dropped, and so is an upload
that names the family rather than the show ("Kim Kardashian", "The kardashian
season 8"). Measured over the 340 videos of the 2026-09-18T1058Z pools that is
10 of the 31 drops - eight of them a name in another language or script - and
in every case the topic's own pool still held far more than the floor of three
candidates without them. The numbers are in
`tasks/CF-0272-second-source-passes-independence-but-not-relevance.md`.

Used from two places, with one rule and one record shape:

  * `footage_candidates.py` filters the footage pool with it *before* grouping
    and ranking, so a dropped upload is replaced by the next real candidate
    rather than costing the topic a slot; the drops land in
    `evidence.footage_candidates_dropped`;
  * the scoring pass (SKILL.md step 4) runs this module's CLI over its own
    signal file, which prints the view sum after exclusions and the
    `evidence.excluded_evidence` records - the exclusions the operator used to
    make by hand and record nowhere.

CLI:
  scripts/topic_relevance.py /tmp/signal-wren-hollow.json --name "Wren Hollow"
  scripts/topic_relevance.py /tmp/footage-delver.json --name Delver --kind person \\
      --person "Tom Carver"
  scripts/topic_relevance.py <batch-dir|01-trend-hunter.json> --topic lf-...-007 \\
      --signal /tmp/signal.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fact_probe_topics import normalise  # noqa: E402  - one normalisation, not two

# The code a candidate is dropped with. Not a `shared/runlog/funnel.py`
# FUNNEL_CODE: the funnel counts *topics* leaving the batch, and this is one
# upload leaving a topic's pool. When the rule empties a pool the topic is
# refused by footage_candidates.py with the funnel's own `no_source`, and the
# reason says how many uploads named another work.
WRONG_WORK_CODE = "wrong_work"

# Where a work may be named, in the order it is looked for. `channel_title` is
# last and is there for the work's own channel ("Pine Park Studios" uploading
# "We Are South America"); it is not the network, and the network is why this
# module exists - see the docstring.
MATCH_FIELDS = ("title", "description", "channel_title")

# The keys of one exclusion record. `reason_code` is new (CF-0272); the other
# five are the shape SKILL.md already asked the operator for in
# `excluded_evidence`, so a record written by hand before this and a record
# written by the script now read the same.
EXCLUSION_KEYS = ("video_id", "title", "channel_title", "view_count",
                  "reason_code", "reason")

# Articles a title may drop; matched at the head of a form only.
ARTICLES = ("the ", "a ", "an ")
# A sequel number at the end of a name: "Everyday Sorcery 2" is named by
# "Everyday Sorcery".
SEQUEL_TAIL = re.compile(r"\s+(\d{1,2}|ii|iii|iv|v|vi)$")
# Words that carry no initial worth putting in an acronym.
ACRONYM_STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "on",
                     "for", "with"}
# Shortest needle that may be matched at all. Two letters is noise: " re ",
# " hp ", " sp " occur in ordinary titles and in other languages.
MIN_NEEDLE = 3
# Shortest space-less form worth generating - "wrenhollow" yes, "up" no.
MIN_SPACELESS = 6


def _add(value, into):
    needle = normalise(value).strip()
    if needle and len(needle) >= MIN_NEEDLE and needle not in into:
        into.append(needle)


def _ref_of(title_ref):
    """`title_ref`, a bare name, or None -> a dict with the keys read here."""
    if isinstance(title_ref, str):
        return {"name": title_ref}
    return dict(title_ref or {})


def base_names(title_ref):
    """The names of the work itself: the full name, the stem and the subtitle
    around a colon, and `parent_work`.

    A person-topic contributes its **work** and never the person (CF-0264: the
    named work must appear; a video that only says "Tom Carver" is not footage
    of *Delver*). `title_ref.person` is therefore never a name here, and a
    topic whose name *is* the person's name yields nothing - since CF-0439
    such a topic is the channel's own (a story about the person, not refused
    upstream any more), and yielding nothing means its footage is not
    filtered by a work it does not have.
    """
    ref = _ref_of(title_ref)
    name = str(ref.get("name") or "").strip()
    person = str(ref.get("person") or "").strip()
    names = []
    _add(name, names)
    if ":" in name:
        stem, _, subtitle = name.partition(":")
        _add(stem, names)
        _add(subtitle, names)
    _add(ref.get("parent_work") or ref.get("parent"), names)
    if person:
        needle = normalise(person).strip()
        names = [n for n in names if n != needle]
    return names


def _acronyms(form):
    out = []
    words = form.split()
    for chosen in (words, [w for w in words if w not in ACRONYM_STOPWORDS]):
        if len(chosen) >= 3:
            acronym = "".join(w[0] for w in chosen)
            if len(acronym) >= MIN_NEEDLE and acronym not in out:
                out.append(acronym)
    return out


# --------------------------------------------------------------------------
# CF-0662 (TH-1 of the root's docs/science-footage.md) - a story's subjects
# --------------------------------------------------------------------------
# A science story has no "work". What its footage names is the mission, the
# spacecraft, the object or the phenomenon the story is about: "Artemis II",
# "JWST" / "Webb", "C/2025 A6 (Lemmon)", "aurora". A topic says it is such a
# story by its `title_ref.type` (one of STORY_TYPES - never a film's
# `film` / `tv_series` / `animation`) or by naming `title_ref.subjects` (the
# named subjects of its headline, the operator's copy of what the headline
# says - SKILL.md step 3). Its forms are then the subjects' forms, read the
# way a mission or a catalogue name is written:
#   * the trailing number is part of the name - "Artemis II" is never named by
#     "Artemis" (that is Artemis I's footage too), and is named by "Artemis 2";
#   * a parenthesised name is a name of its own - "Lemmon" of "C/2025 A6
#     (Lemmon)", and the designation without it;
#   * a leading kind or agency word is dropped - "Comet Lemmon" -> "lemmon",
#     "NASA's Webb" -> "webb";
#   * a form that every agency upload carries ("nasa", "space", "comet") is
#     never a form: it would keep the whole channel.
STORY_TYPES = ("mission", "spacecraft", "telescope", "celestial_object", "phenomenon",
               "discovery", "place", "science_story")
STORY_LEAD_WORDS = {"the", "a", "an", "comet", "asteroid", "interstellar", "object",
                    "nasa", "nasas", "esa", "esas", "eso", "jpl", "noaa", "usgs", "s"}
STORY_GENERIC_FORMS = {"nasa", "esa", "eso", "jpl", "noaa", "usgs", "space", "science",
                       "comet", "asteroid", "mission", "telescope", "spacecraft", "rocket",
                       "launch", "earth", "live", "news", "update", "nasa science",
                       "european space agency", "space agency"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7",
         "viii": "8", "ix": "9", "x": "10"}
ARABIC = {v: k for k, v in ROMAN.items()}
PARENS = re.compile(r"\(([^)]*)\)")


def is_story(title_ref):
    """True when the topic is a story whose footage names its subjects (a
    science story), not a work."""
    ref = _ref_of(title_ref)
    subjects = ref.get("subjects")
    return ref.get("type") in STORY_TYPES or (isinstance(subjects, list) and any(
        isinstance(x, str) and x.strip() for x in subjects))


def _story_names(text):
    """One subject as written -> its raw names: itself, its parenthesised
    names, itself without them, and the parts around a colon."""
    text = str(text or "").strip()
    out = [text]
    inner = [m.strip() for m in PARENS.findall(text) if m.strip()]
    bare = PARENS.sub(" ", text).strip()
    out += inner + ([bare] if bare and bare != text else [])
    for name in list(out):
        if ":" in name:
            stem, _, sub = name.partition(":")
            out += [stem.strip(), sub.strip()]
    return [n for n in out if n]


def _story_add(form, into):
    form = form.strip()
    if form and form not in STORY_GENERIC_FORMS:
        _add(form, into)


def story_forms(title_ref):
    """-> the normalised needles that name this story: its name's and its
    subjects' forms (see the block above). Empty when nothing is left."""
    ref = _ref_of(title_ref)
    raw = [ref.get("name")] + [x for x in (ref.get("subjects") or []) if isinstance(x, str)]
    forms = []
    for subject in raw:
        for name in _story_names(subject):
            words = normalise(name).split()
            while len(words) > 1 and words[0] in STORY_LEAD_WORDS:
                words = words[1:]
            if not words:
                continue
            form = " ".join(words)
            _story_add(form, forms)
            tail = words[-1]
            alt = ROMAN.get(tail) or ARABIC.get(tail)
            if alt and len(words) > 1:
                _story_add(" ".join(words[:-1] + [alt]), forms)
    for form in list(forms):
        flat = form.replace(" ", "")
        if flat != form and len(flat) >= MIN_SPACELESS:
            _story_add(flat, forms)
        # an acronym of words only ("jwst"), never of a designation ("c 2025 a6")
        if all(w.isalpha() for w in form.split()):
            for acronym in _acronyms(form):
                _story_add(acronym, forms)
    return forms


def work_forms(title_ref):
    """-> the ordered list of normalised needles that count as naming this
    work. Empty when the topic names no work at all, which this module reads
    as "do not filter" rather than as "drop everything".

    CF-0662: a story (`is_story`) is named by its subjects - `story_forms`."""
    if is_story(title_ref):
        return story_forms(title_ref)
    names = base_names(title_ref)
    forms = list(names)
    for name in names:
        for article in ARTICLES:
            if name.startswith(article) and len(name) > len(article):
                _add(name[len(article):], forms)
        stripped = SEQUEL_TAIL.sub("", name)
        if stripped != name:
            _add(stripped, forms)
    for form in list(forms):
        flat = form.replace(" ", "")
        if flat != form and len(flat) >= MIN_SPACELESS:
            _add(flat, forms)
    for form in list(forms):
        for acronym in _acronyms(form):
            _add(acronym, forms)
    return forms


def names_work(video, forms):
    """-> (field, needle) the work was named by, or (None, None).

    Whole words, case and punctuation ignored, exactly as
    `fact_probe_topics.named_in_leads` reads a headline.
    """
    for field in MATCH_FIELDS:
        haystack = normalise((video or {}).get(field))
        for needle in forms:
            if f" {needle} " in haystack:
                return field, needle
    return None, None


def exclusion_record(video, forms):
    """One `wrong_work` record: what the upload was and why it is not this
    topic's footage. The view count is on it because the same record is what
    `evidence.excluded_evidence` subtracts from the scored view sum."""
    shown = ", ".join(repr(f) for f in forms[:4]) or "nothing"
    return {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": WRONG_WORK_CODE,
        "reason": (f"names no form of the topic's work ({shown}) in its title, "
                   f"description or channel - the search matched it through the "
                   f"channel or the network, not through the work (CF-0272)"),
    }


def partition(videos, title_ref):
    """-> (kept, dropped_records). `dropped_records` is in the shape of
    EXCLUSION_KEYS, ordered as the pool was.

    A topic with no usable name is not filtered: everything is kept and nothing
    is recorded. Dropping a whole pool because a `title_ref` is malformed would
    turn a metadata defect into a lost topic, and the malformed `title_ref` has
    its own refusal upstream.
    """
    forms = work_forms(title_ref)
    if not forms:
        return list(videos or []), []
    kept, dropped = [], []
    for video in videos or []:
        field, _ = names_work(video, forms)
        if field:
            kept.append(video)
        else:
            dropped.append(exclusion_record(video, forms))
    return kept, dropped


# --------------------------------------------------------------------------
# CF-0444 - another installment of the same franchise
# --------------------------------------------------------------------------

# The code an upload is dropped with when its title names the topic's work only
# by the franchise's short form. The same string as the indexer's
# `pool_work_check.OTHER_INSTALLMENT` (CF-0325), which asks the same question
# of a pool source; this module is where the rule lives, so the two stages
# cannot drift apart again.
OTHER_INSTALLMENT_CODE = "other_installment"


def franchise_forms(title_ref, sequel=True):
    """-> the set of normalised forms the topic's name shares with the rest of
    its franchise: the stem before a colon ("Vanguards" of "Vanguards:
    Doomsday"), `parent_work` ("Outrider" of "Outrider: Blood of My Blood",
    "Kaijura Minus One" of "Kaijura Minus Zero") and, with `sequel`, the
    name without its sequel number ("Everyday Sorcery" of "Everyday Sorcery 2").

    `work_forms` counts all of them as naming the work, which is right for a
    scoring signal - a false drop there costs a candidate - and wrong for
    footage: "Vanguards: Endgame | Official Trailer" names "Vanguards" and is
    not one frame of Doomsday (batch 2026-09-29T0705Z, CF-0444)."""
    ref = _ref_of(title_ref)
    name = str(ref.get("name") or "").strip()
    parent = str(ref.get("parent_work") or ref.get("parent") or "").strip()
    wide = set()
    if ":" in name:
        wide.update(work_forms({"name": name.partition(":")[0]}))
    norm = normalise(name).strip()
    stripped = SEQUEL_TAIL.sub("", norm)
    if sequel and stripped and stripped != norm:
        wide.update(work_forms({"name": stripped}))
    if parent:
        wide.update(work_forms({"name": parent}))
    return wide


def installment_forms(title_ref):
    """-> the forms that name **this** installment and not its franchise:
    `work_forms` of the full name and of the subtitle, minus the colon stem's
    and the `parent_work`'s forms. None when the rule does not apply - the
    name has neither a colon stem nor a `parent_work`, or nothing is left once
    the franchise is taken out (a malformed name is not a reason to drop a
    whole pool).

    The sequel number is **not** a franchise form here (it is in
    `franchise_forms`' default, for CF-0426's entity matching): a sequel's
    press names the original - "Sandra Birch and Nora Kingsley on returning
    to Everyday Sorcery" is Everyday Sorcery 2's interview - so dropping it
    would cost a topic its real candidates. A colon subtitle is what the
    studio's own uploads carry ("Vanguards: Doomsday | Silence Your Phones").

    One rule for two stages: Trend Hunter's candidate sieve
    (`footage_candidates.select_candidates`) and the indexer's pool check
    (`footage-indexer/scripts/pool_work_check.py`, CF-0325), which already
    imports this module. Its `_strict_forms` gives the same forms;
    `tests/test_other_installment.py` holds the two together until it calls
    this function itself."""
    ref = _ref_of(title_ref)
    if not work_forms(ref):
        return None
    wide = franchise_forms(ref, sequel=False)
    if not wide:
        return None
    name = str(ref.get("name") or "").strip()
    strict = [f for f in work_forms({"name": name}) if f not in wide]
    subtitle = name.partition(":")[2].strip() if ":" in name else ""
    if subtitle:
        strict += [f for f in work_forms({"name": subtitle})
                   if f not in wide and f not in strict]
    return strict or None


def names_installment(video, forms):
    """The installment form the upload's **own title** names, or None. Title
    only, as `footage_sieve._named_in_title` reads it: what is in the frame is
    what the uploader wrote on the front of it, and a description listing the
    franchise's films says nothing about which one was cut."""
    haystack = normalise((video or {}).get("title"))
    for needle in forms or ():
        if f" {needle} " in haystack:
            return needle
    return None


def other_installment_record(video, forms):
    """One `other_installment` record, in the shape of EXCLUSION_KEYS."""
    shown = ", ".join(repr(f) for f in (forms or [])[:3]) or "nothing"
    return {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": OTHER_INSTALLMENT_CODE,
        "reason": (f"its title names the work only by its franchise or parent, never "
                   f"as {shown} - another work of the same name "
                   f"({OTHER_INSTALLMENT_CODE}, CF-0444/CF-0325)"),
    }


def partition_other_installment(videos, title_ref):
    """-> (kept, dropped_records): the uploads whose title names this
    installment, and the ones that name only the franchise. Official channels
    are not exempt - Zenith's own Endgame trailer is exactly the upload this
    exists for. Nothing is dropped when `installment_forms` is None."""
    forms = installment_forms(title_ref)
    if forms is None:
        return list(videos or []), []
    kept, dropped = [], []
    for video in videos or []:
        if names_installment(video, forms):
            kept.append(video)
        else:
            dropped.append(other_installment_record(video, forms))
    return kept, dropped


def views_of(videos):
    return sum(int(v.get("view_count") or 0) for v in videos or [])


def check_exclusions(records, ctx="excluded_evidence", remedy=None):
    """The problems in a written exclusion list - used by the `--check` paths
    so that "the operator excluded something" is a claim the artifact can be
    read back for, instead of a line in a report."""
    problems = []
    if records is None:
        return [f"{ctx}: missing - what a topic excluded is a field of the artifact, "
                f"not of the operator's reasoning (CF-0272); "
                + (remedy or "write [] when nothing was excluded")]
    if not isinstance(records, list):
        return [f"{ctx}: not a list"]
    for i, record in enumerate(records):
        rctx = f"{ctx}[{i}]"
        if not isinstance(record, dict):
            problems.append(f"{rctx}: not an object")
            continue
        missing = [k for k in ("video_id", "reason") if not record.get(k)]
        if missing:
            problems.append(f"{rctx}: missing {missing} - an exclusion without a "
                            f"video id and a reason is invisible again")
    return problems


# --------------------------------------------------------------------------
# CLI - the scoring pass's exclusions, computed instead of eyeballed
# --------------------------------------------------------------------------

def _title_ref_from_batch(path, topic_id):
    batch = json.load(open(path))
    for topic in (batch.get("topics") or []) + (batch.get("skipped_topics") or []):
        if topic.get("topic_id") == topic_id:
            return topic.get("title_ref") or {}
    raise SystemExit(f"no topic {topic_id!r} in {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("signal", help="a fetch_youtube_signal.py output (the scoring pass "
                                   "or the footage pass), or a batch dir with --topic")
    ap.add_argument("--topic", help="read title_ref from this batch topic")
    ap.add_argument("--signal", dest="signal_file",
                    help="the signal file, when the positional argument is a batch")
    ap.add_argument("--name", help="title_ref.name")
    ap.add_argument("--parent", help="title_ref.parent_work")
    ap.add_argument("--person", help="title_ref.person")
    ap.add_argument("--kind", default=None, help="title_ref.kind (work|person)")
    args = ap.parse_args(argv)

    if args.topic:
        path = Path(args.signal).expanduser()
        batch = path / "01-trend-hunter.json" if path.is_dir() else path
        ref = _title_ref_from_batch(batch, args.topic)
        signal_path = args.signal_file
        if not signal_path:
            raise SystemExit("--topic needs --signal <the search output>")
    else:
        ref = {"name": args.name, "parent_work": args.parent,
               "person": args.person, "kind": args.kind}
        signal_path = args.signal_file or args.signal
        if not ref["name"]:
            raise SystemExit("--name is required without --topic")

    signal = json.load(open(Path(signal_path).expanduser()))
    videos = signal.get("videos") or []
    kept, dropped = partition(videos, ref)
    print(json.dumps({
        "topic": ref.get("name"),
        "forms": work_forms(ref),
        "videos_seen": len(videos),
        "named_the_work": len(kept),
        "views_before_exclusions": views_of(videos),
        "youtube_views_after_exclusions": views_of(kept),
        "excluded_evidence": dropped,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
