#!/usr/bin/env python3
"""Is this upload footage of the work, or a talk about it? (CF-0309)

Why this module exists. The batch `example-film/2026-09-21T1541Z` was the first
run in which every source the indexer touched came back with a verdict of the
CF-0299 content sieve. Of the 25 candidates it reached, 9 survived and 14 were
refused on their content - and the indexer paid full price for every one of
them: the download, ~6 minutes of indexing per minute of source, the shot
describer. The stage took 5 h 37 min and lost four topics (Silent Tide,
Rennick, Delver, The Long Voyage) because their good candidates ran out before the
four attempts did.

What the refused uploads were, in the hunter's own artifact, before a single
frame was fetched: a news round-up naming three other works in its title, a
podcast recording, two press-junket interviews, a title made of nothing but
hashtags, two uploads of an entirely different work, a blogger's argument
about a film. None of that is what CF-0272 asks (does the upload *name* the
work - all of them do, or they would not be in the pool), nor what CF-0297
asks (does a word say it is a fan edit / reaction / podcast - the wrap-up and
the opinion piece say no such thing), nor what CF-0302 asks (is it too long -
they are not).

This module asks the remaining question: **does the upload's own title say it
is a cut of the work?** Six rules, each measured on the 25 labelled
candidates (`tests/fixtures/footage_sieve_1541z.json`: the 23 of `1541Z` the
indexer judged, plus `QJ1WSiMUVFA` and `wS6wtevVlmc`, named with their reasons
by CF-0297/CF-0299) - 9 good against 16 bad. The full table is in the task
file; `tests/test_footage_sieve.py` holds every rule to its two numbers, so a
rule that starts costing good footage fails the suite instead of the batch.

    rule                       code                    bad taken   good lost
    work not named in the      work_not_in_title           3/16         0/9
      upload's own title
    work's word only as the    other_works_name            1/16         0/9
      tail of another name
    a news round-up            news_wrap                   1/16         0/9
    hashtags are half the      hashtag_title               2/16         0/9
      title or more
    an opinion/news word       opinion                     2/16         0/9
    a press outlet's channel   press_outlet                2/16         0/9

The union takes 10 of the 16; `QJ1WSiMUVFA` is already taken by CF-0297, which
leaves 5 that no metadata rule reaches and that belong to the frame judge and
to the CF-0299 sieve: `FzTtOz1KJ1c` (Prime Video Canada, burned-in credits in
65 % of its shots - an official channel, and the task says not to try),
`bYKJxZYd66o` (a vertical short with captions in the middle of the frame),
`faEZRX9eg8Q` ("Harbourlights Is Changing DC Forever" - an opinion whose title is a
plain sentence), `wS6wtevVlmc` (an unrelated amateur short under a perfectly
clean title; CF-0297 said the same of it a run earlier) and `mtZjyyslZ_s` - see
`official_claim` below.

**The set is small.** 25 candidates is not a corpus, and a rule that separates
16 rows from 9 by luck would look exactly like a rule that works. So each rule
here is a mechanism somebody can state in one sentence without the data - a
round-up lists several works, a title of hashtags describes nothing, a title
that never names the work is not about it - and each one that costs good
footage is either out or carries its number and its argument. The rules
measured and **rejected** on the same set, in the task file's table:
`origin != official` (15/16 bad, but 4/9 good - most honest footage comes from
channels no list holds), `view_count < 1000` (4/16, 2/9 - the CLIPREEL cut of
Silent Tide that survived the sieve had 3 views), `nature == interview and not
official` (2/16, 1/9 - the classifier reads "Trailer | Maisri Shows Julia
Henry!" as an interview), `how` in the title (0/16 - no data behind it), and
`official_claim`: "official" in the title of a channel that is not one. That
last one measured 2 of 16 and 0 of 9 on this set, and was still left out - its
*unique* catch is `mtZjyyslZ_s` alone (the other, `NZ2VI7dQ91A`, is taken by
`work_not_in_title` anyway), and the repo's own CF-0129 fixture holds the
counter-example the 25 rows do not: `teaser-reup-2` "Official Teaser |
Everyday Sorcery 2 [4K]", an honest reupload of the official teaser, which the
same-cut collapse exists to handle and which the rule would have thrown away
before the collapse ever saw it. One catch is not worth a rule whose loss the
set cannot measure.

Two rules that are decisions and not mechanics, inherited whole from CF-0297:

  1. **An official channel is never sieved here either** - with one exception,
     `other_work_title` (CF-0924, below). Every other rule is skipped for a
     channel on the batch's channel's official list
     (`channels/<id>/footage-origin.json`, `footage_origin.load_config(channel)`).
  2. A drop is **recorded**, never silent: one record per upload in
     `evidence.footage_candidates_dropped` with `reason_code
     'not_the_works_footage'` and a reason that names the rule and quotes what
     was read, in the shape CF-0272 and CF-0297 write.

The word lists (news markers, opinion words, press outlets) are config -
`config/footage_sieve.json`, each entry with the `seen_in` upload it was read
off. The shape rules are here, because a shape is not a word.

CF-0924 - **the title names another work** (`other_work_title`). Acceptance
of Reel 2026-11-08T1117Z: the Jon Marrow topic (`lf-2026-11-08-020`, the
animated prequel news) was cut from one source, `jQHoAsDcjVU` "Karōshi (2027)
Official Trailer - Teo Yoo, ..." (Example Pictures) - a film *from the
producer of* Jon Marrow, not Jon Marrow. Not one frame of Jon Marrow in the
Short; the acceptance refused it `wrong_work_footage`, the ninth refusal with
that code. It got through twice: its description says "from the producer of
Jon Marrow", which is all CF-0272 asks, and Example Pictures is an official channel,
which every rule of this sieve skipped. Its Indonesian twin `9ia-5fCvqDI`
"Karōshi Rilis Trailer Perdana, Film Baru dari Produser Jon Marrow" names John
Wick in its title - as a credit. The rule, two branches:

  * **a credit, not a subject** - every place the title names the work, the
    words right before it are the marketing credit formula ("from the
    producer of", "From Zach Cregger, director of", "dari Produser"): the
    title's subject is whatever stands before the credit. Any one naming
    outside a credit keeps the upload ("Resident Dread - Official Teaser
    Trailer. From Zach Cregger, director of Weapons and Barbarian" names its
    own work first and others in the credit). Phrases are config
    (`credit_phrases`, each with its `seen_in`);
  * **an official upload of another work** - only for a screen work (a film
    or a series topic), only off an official channel (the unofficial case is
    `work_not_in_title` already), only when neither the title nor the channel
    names the work and the title's head (`title_subject`, the text before the
    first separator) holds a Latin word that is not a label ("Official",
    "Trailer", "Season", a year...). A head in another script is not read as
    another work: unknown is not other.

It runs **before** the official bypass - the exception to rule 1 - because a
studio uploads all its films and "official" only says the cut is the
studio's, never which work it is. Measured over the 46 batches of
pipeline/example* (1264 candidates) on 2026-11-09: it would have taken 3
candidates - the two Karōshi uploads above and `9iCJd_X-zYs` "The Gilded Age
Season 4 | Weeks Ahead Trailer | Example Max" offered for *Wren Hollow*
(2026-11-07T0840Z) - and no candidate of the work.

Used from `footage_candidates.py` as the fourth sieve, in the same place as
the other three - before grouping and before ranking, so a dropped upload is
replaced by the next real candidate rather than costing the topic a slot.

CLI (no network, reads a written batch or a saved search):
  scripts/footage_sieve.py <batch-dir|01-trend-hunter.json>
  scripts/footage_sieve.py /tmp/footage-rennick.json --topic lf-...-005
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import footage_origin  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
from footage_origin import ConfigError  # noqa: E402
from fact_probe_topics import _APOSTROPHES  # noqa: E402  - normalise's own flattening
from topic_relevance import normalise, work_forms  # noqa: E402

CONFIG_PATH = HERE.parent / "config" / "footage_sieve.json"

# The reason_code every rule in this module writes. One code, six rules: the
# funnel counts losses by code and the codes it knows are coarse, while the
# rule name belongs in the sentence a human reads - the same division CF-0297
# makes between `unofficial_source` and its `fan_made` / `podcast` codes.
NOT_FOOTAGE_CODE = "not_the_works_footage"

EXCLUSION_KEYS = ("video_id", "title", "channel_title", "view_count",
                  "reason_code", "reason")

_CACHE = {}

# A round-up is a *list* of items: three of them or more, separated by commas,
# at least two carrying the word an item of film news ends with. Two segments
# is not a list - "Tom Carver Says Taylor Sterling Was Schooling Him at Chiefs
# Game, Talks Wild Delver Transformation" (The Evening Show, kept by the
# sieve) is one sentence with a comma in it, and a two-segment rule would eat
# it.
WRAP_SEGMENTS = 3
WRAP_ITEMS = 2

_HASHTAG = re.compile(r"#[^\s#]+")
_WORD = re.compile(r"[0-9a-zЀ-ӿ]+", re.I)
_ARTICLE = re.compile(r"^(the|a|an)\s+")
# Long enough that the bare word is still the work's name and not a syllable.
MIN_BARE_FORM = 4


def load_config(path=None):
    """-> the parsed config, compiled and cached by path. Same contract as
    `footage_origin.load_config`: a typo in a pattern fails the run that loaded
    it, and an entry nobody can point at in a real pool fails it too."""
    path = Path(path or CONFIG_PATH)
    key = str(path.resolve()) if path.exists() else str(path)
    if key in _CACHE:
        return _CACHE[key]
    if not path.exists():
        raise ConfigError(f"no footage-sieve config at {path}")
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    out = {"path": path}
    for section in ("news_markers", "opinion_words", "press_channels", "credit_phrases"):
        entries = []
        for i, entry in enumerate(raw.get(section) or []):
            ctx = f"{path} {section}[{i}]"
            pattern = (entry or {}).get("pattern")
            if not pattern:
                raise ConfigError(f"{ctx}: no pattern")
            if not ((entry.get("seen_in") or {}).get("video_id")):
                raise ConfigError(
                    f"{ctx}: no seen_in.video_id - a pattern nobody can point at in a real "
                    f"pool is a rule fitted to 25 rows (CF-0309)")
            if section == "credit_phrases":
                # CF-0924: a credit is the words right before the work's name -
                # anchored at the end of what precedes it.
                pattern = rf"(?:{pattern})\s*$"
            try:
                compiled = re.compile(pattern, re.I)
            except re.error as exc:
                raise ConfigError(f"{ctx}: {pattern!r} is not a regular expression: {exc}") from exc
            entries.append(dict(entry, _re=compiled))
        if not entries:
            raise ConfigError(f"{path}: {section} must be non-empty")
        out[section] = entries
    _CACHE[key] = out
    return out


# --------------------------------------------------------------------------
# the seven rules - each one (video, forms, config) -> what was read, or None
# --------------------------------------------------------------------------

def _title(video):
    return str((video or {}).get("title") or "")


def _named_in_title(video, forms):
    """The form of the work the upload's **own title** names, or None. CF-0272
    accepts the title, the description *or* the channel, which is right for a
    signal - a network's channel is evidence that the upload is about the
    network. It is not right for footage: what is in the frame is what the
    uploader wrote on the front of it."""
    haystack = normalise(_title(video))
    for needle in forms or ():
        if f" {needle} " in haystack:
            return needle
    return None


def _article_pairs(forms):
    """The (full, bare) pairs of a name whose article `work_forms` dropped:
    ("the long voyage", "odyssey"). Read off the forms themselves, so a topic
    whose name carries no article - every other topic of the `1541Z` pool -
    never reaches `rule_other_works_name` at all."""
    pairs = []
    for full in forms or ():
        head = _ARTICLE.match(full)
        if not head:
            continue
        bare = full[head.end():]
        if bare and len(bare) >= MIN_BARE_FORM and " " not in bare and bare in forms:
            pairs.append((full, bare))
    return pairs


def rule_work_not_in_title(video, forms, config=None):
    """The title never names the work. `9a7i4LHHZNs` - "Fred Perry's Animated
    Antarctic Press Universe Trailer" - was offered for *Delver* because the
    description mentions it; the shots are another studio's cartoon."""
    if not forms or _named_in_title(video, forms):
        return None
    shown = ", ".join(repr(f) for f in list(forms)[:3])
    return f"its title names no form of the work ({shown})"


def rule_other_works_name(video, forms, config=None):
    """The work's name is an article and a noun ("The Long Voyage"), the title
    never uses the whole name, and the bare noun in it is the tail of somebody
    else's title: "The NFL Odyssey", "The Super Mario Odyssey Movie",
    "Roadside Odyssey".

    Deliberately narrow. The general version - "the work's word has another
    word before it" - takes 5 of the 16 bad candidates and 2 of the 9 good
    ones ("... | Hal Garrett | Harbourlights S1E5", "Talks Wild Delver
    Transformation"), because in an English title everything has a word before
    it. Restricted to a name whose article was dropped, it costs nothing: the
    full name is there to be written, and an upload of the work writes it.
    """
    haystack = normalise(_title(video))
    for full, bare in _article_pairs(forms):
        if f" {full} " in haystack:
            continue
        found = re.search(r"\b(\w+)\s+" + re.escape(bare) + r"\b", haystack)
        if found and found.group(1) not in (forms or ()):
            return (f"its title never says {full!r}, and the one word {bare!r} in it is the "
                    f"tail of another name ({found.group(0)!r})")
    return None


def rule_news_wrap(video, forms, config=None):
    """A round-up of several works: WRAP_SEGMENTS comma-separated items or
    more, WRAP_ITEMS of them or more carrying a news marker."""
    config = config or load_config()
    segments = [s for s in _title(video).split(",") if s.strip()]
    if len(segments) < WRAP_SEGMENTS:
        return None
    hits = [s.strip() for s in segments
            if any(m["_re"].search(s) for m in config["news_markers"])]
    if len(hits) < WRAP_ITEMS:
        return None
    return (f"its title is a list of {len(segments)} items, {len(hits)} of them a piece of "
            f"film news ({'; '.join(repr(h[:40]) for h in hits[:3])})")


def rule_hashtag_title(video, forms, config=None):
    """Half of what the uploader wrote, or more, is reach tags. The upload was
    indexed for reach and never described: "#tomcarver #movies #interview
    #examplestudios #delver #missionunlikely #bts" is a title that says nothing
    at all about what is in the frame. Not the same rule as CF-0297's
    `shortform_repost`, which reads *which* tags (#fyp, #viral); this one reads
    how much of the title is tags."""
    tags = _HASHTAG.findall(_title(video))
    words = _WORD.findall(_HASHTAG.sub(" ", _title(video)))
    if not tags or len(tags) < len(words):
        return None
    return (f"{len(tags)} of the {len(tags) + len(words)} things in its title are hashtags - "
            f"a title written for reach, not a description of a cut")


def rule_opinion(video, forms, config=None):
    """A word that makes the title an argument about the work rather than the
    label of a cut of it."""
    config = config or load_config()
    for entry in config["opinion_words"]:
        found = entry["_re"].search(_title(video))
        if found:
            return f"its title says {found.group(0)!r} - {entry['why'].split('.')[0]}"
    return None


def rule_press_outlet(video, forms, config=None):
    """The channel is a film-press or entertainment-news outlet. Its uploads
    are its own junket interviews and podcast recordings - talking heads on its
    own set, which is what the CF-0299 sieve calls `source_foreign`."""
    config = config or load_config()
    channel = str((video or {}).get("channel_title") or "")
    for entry in config["press_channels"]:
        if entry["_re"].search(channel):
            return (f"its channel {channel!r} is a {entry.get('what') or 'press outlet'} "
                    f"({entry['pattern']!r})")
    return None


# --------------------------------------------------------------------------
# CF-0924 - the title names another work
# --------------------------------------------------------------------------

OTHER_WORK_CODE = "other_work_title"
# The topics whose official uploads are read for another work's name: a film
# and a series. A Tech product's own vendor demo may never say the product's
# name ("The new iPad mini" for Apple Intelligence), and a story's footage is
# named by its subjects (CF-0662); neither is a work with a title of its own.
SCREEN_TYPES = ("film", "tv_series")
# The key the drop record carries: what the title is about instead.
SUBJECT_KEY = "title_subject"
# Where the head of a title ends: a bracket, a pipe, a dash or colon between
# words, a comma, a full stop between words.
_HEAD_END = re.compile(r"\s[-–—|·:]\s|[|–—·:(\[,]|\.\s")
_LATIN_WORD = re.compile(r"[a-z][a-z0-9']*", re.I)
# Words a head may hold without naming anything: the label of a cut. A head
# left with nothing else ("Official Trailer 2", "Season 3 | Teaser") is
# generic, not another work.
LABEL_WORDS = frozenset("""
    official trailer trailers teaser teasers clip clips featurette promo spot tv
    final new first look full hd uhd imax red band international exclusive sneak
    peek season seasons episode part extended the a an and of
    """.split())


def _plain_latin(text):
    """Accents off, case off: "Karōshi" -> "karoshi" (the head is shown, and
    compared, as words)."""
    flat = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in flat if not unicodedata.combining(ch)).lower()


def _namings(title, forms):
    """-> the (start, end) spans of every place the title names a form, read
    exactly as `normalise` reads it: any run of characters that is not a-z/0-9
    separates words."""
    low = str(title or "").translate(_APOSTROPHES).lower()
    spans = []
    for form in forms or ():
        words = form.split()
        if not words:
            continue
        rx = (r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(w) for w in words)
              + r"(?![a-z0-9])")
        spans += [(m.start(), m.end()) for m in re.finditer(rx, low)]
    return low, sorted(set(spans))


def _credit_before(prefix, config):
    """The `credit_phrases` entry the text right before a naming ends with,
    as (entry, start of the phrase in `prefix`), or (None, None). Punctuation
    reads as a space, one for one, so a position here is a position in the
    title: "From Zach Cregger, director of" is the credit formula."""
    flat = re.sub(r"[\W_]", " ", prefix)
    for entry in config.get("credit_phrases") or ():
        found = entry["_re"].search(flat)
        if found:
            return entry, found.start()
    return None, None


def title_subject(title):
    """The head of a title - the text before its first separator, stripped:
    "Karōshi (2027) Official Trailer - Teo Yoo" -> "Karōshi". What a title is
    about comes first; the label of the cut and the cast come after."""
    text = str(title or "").strip(" -–—|·:,.")
    head = _HEAD_END.split(text, maxsplit=1)[0] if text else ""
    return head.strip(" -–—|·:,.\"'«»“”") or None


def _names_something(head):
    """The head holds a Latin word that is not the label of a cut."""
    words = [w.strip("'") for w in _LATIN_WORD.findall(_plain_latin(head or ""))]
    return [w for w in words if w and w not in LABEL_WORDS and not w.isdigit()
            and not YEAR_WORD.match(w)]


YEAR_WORD = re.compile(r"^(19|20)\d\d$")


def is_screen_work(title_ref):
    """A film or a series topic (CF-0924's official branch reads only these)."""
    ref = title_ref if isinstance(title_ref, dict) else {}
    return ref.get("kind") == "work" and ref.get("type") in SCREEN_TYPES


def rule_other_work_title(video, forms, config=None, official=False, screen_work=False):
    """-> (what was read, the title's subject) when the title is about another
    work, or (None, None). See the module docstring (CF-0924)."""
    if not forms:
        return None, None
    config = config or load_config()
    title = _title(video)
    low, spans = _namings(title, forms)
    if spans:
        credits = []
        for start, end in spans:
            entry, at = _credit_before(low[:start], config)
            if not entry:
                return None, None          # named as itself at least once
            credits.append((start, end, at))
        start, end, at = credits[0]
        subject = title_subject(title[:at]) if at else None
        if not subject:
            # "From the producer of Jon Marrow: Karōshi" - the subject follows
            subject = title_subject(title[max(e for _, e, _ in credits):]) or None
        named = title[credits[0][0]:credits[0][1]]
        return ((f"its title names the work only as a credit ({title[at:end].strip()!r}) - "
                 f"the upload is about {subject or 'another work'!r}, not about {named!r}"),
                subject)
    if not (official and screen_work):
        return None, None
    if _named_in_title({"title": (video or {}).get("channel_title")}, forms):
        return None, None                  # the work's own channel
    subject = title_subject(title)
    if not _names_something(subject):
        return None, None                  # a generic label, or a head in another script
    shown = ", ".join(repr(f) for f in list(forms)[:3])
    return ((f"an official upload whose title is about {subject!r} and names no form of the "
             f"work ({shown}) - a studio uploads all its films; official says whose cut it "
             f"is, not which work"), subject)


# The order is the order a reason is read in: what the upload is *about*
# first, then what it is.
RULES = (
    ("work_not_in_title", rule_work_not_in_title),
    ("other_works_name", rule_other_works_name),
    ("news_wrap", rule_news_wrap),
    ("hashtag_title", rule_hashtag_title),
    ("opinion", rule_opinion),
    ("press_outlet", rule_press_outlet),
)
RULE_CODES = (OTHER_WORK_CODE,) + tuple(code for code, _ in RULES)
# The task each rule was adopted on, for the reason a human reads.
RULE_TASK = {OTHER_WORK_CODE: "CF-0924"}


def sieve(video, title_ref=None, config=None, forms=None, origin=None, screen_work=None,
          detail=None):
    """-> (rule_code, what_was_read) for the first rule this upload hits, or
    (None, None). An official channel hits nothing but `other_work_title` -
    rule 1 of CF-0297 and its CF-0924 exception; `origin` is
    `footage_origin.load_config(<the batch's channel>)`, the channel's
    official list (CF-0627), and has to be handed in. `detail`, a dict when
    given, receives the title's subject of an `other_work_title` hit."""
    config = config or load_config()
    forms = work_forms(title_ref) if forms is None else forms
    official = bool(footage_origin.is_official(video, origin))
    screen = is_screen_work(title_ref) if screen_work is None else screen_work
    what, subject = rule_other_work_title(video, forms, config, official=official,
                                          screen_work=screen)
    if what:
        if detail is not None:
            detail[SUBJECT_KEY] = subject
        return OTHER_WORK_CODE, what
    if official:
        return None, None
    for code, rule in RULES:
        what = rule(video, forms, config)
        if what:
            return code, what
    return None, None


def exclusion_record(video, code, what, subject=None):
    """One `not_the_works_footage` record, in the shape
    `footage_candidates_dropped` already holds. An `other_work_title` drop
    (CF-0924) also carries `rule` and `title_subject` - what the title is
    about instead - so a reader (and the frame judge's own check) need not
    parse the sentence."""
    record = {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": NOT_FOOTAGE_CODE,
        "reason": (f"{what} ({code}, {RULE_TASK.get(code, 'CF-0309')}). An upload that talks "
                   f"about the work is not footage of it; offering it costs the topic an "
                   f"indexer attempt (~6 min per minute of source) and a slot it does not "
                   f"get back."),
    }
    if code == OTHER_WORK_CODE:
        record["rule"] = OTHER_WORK_CODE
        record[SUBJECT_KEY] = subject
    return record


def partition(videos, title_ref=None, config=None, origin=None):
    """-> (kept, dropped_records), the pool order preserved - the fourth sieve,
    in the same place and for the same reason as the other three. `origin`:
    the channel's footage-origin config, as `sieve` takes it."""
    config = config or load_config()
    origin = footage_origin._require(origin)
    forms = work_forms(title_ref)
    screen = is_screen_work(title_ref)
    kept, dropped = [], []
    for video in videos or []:
        detail = {}
        code, what = sieve(video, config=config, forms=forms, origin=origin,
                           screen_work=screen, detail=detail)
        if code:
            dropped.append(exclusion_record(video, code, what, detail.get(SUBJECT_KEY)))
        else:
            kept.append(video)
    return kept, dropped


# --------------------------------------------------------------------------
# CLI - what the sieve would say about a written batch or a saved search,
# with no call to YouTube at all
# --------------------------------------------------------------------------

def _batch_path(arg):
    path = Path(arg)
    return path / "01-trend-hunter.json" if path.is_dir() else path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="a batch dir / 01-trend-hunter.json, or a saved footage search")
    ap.add_argument("--topic", help="topic_id, when the file is a saved search")
    ap.add_argument("--config", help="an alternative config/footage_sieve.json")
    ap.add_argument("--channel", help="the channel whose official footage channels pass "
                                      "unsieved (CF-0627); default the batch's `channel`, "
                                      "required for a saved search")
    args = ap.parse_args(argv)
    config = load_config(args.config)
    data = json.loads(_batch_path(args.path).read_text())
    channel = args.channel or (resolve_channel(data.get("channel"))
                               if isinstance(data, dict) and data.get("channel") else None)
    try:
        origin = footage_origin.load_config(channel)
    except ConfigError as exc:
        print(f"footage-sieve: {exc}", file=sys.stderr)
        return 2

    pools = []
    if isinstance(data, dict) and data.get("topics"):
        for topic in data["topics"]:
            pools.append((topic.get("topic_id"), topic.get("title_ref") or {},
                          (topic.get("evidence") or {}).get("footage_candidates") or []))
    else:
        pools.append((args.topic, {"name": data.get("query")}, data.get("videos") or []))

    total = dropped_n = 0
    for topic_id, title_ref, videos in pools:
        kept, dropped = partition(videos, title_ref, config, origin)
        total += len(videos)
        dropped_n += len(dropped)
        print(f"{topic_id or '?'}: {len(kept)} kept, {len(dropped)} dropped")
        for record in dropped:
            print(f"    {record['video_id']}  {record['title']!r}")
            print(f"        {record['reason']}")
    print(f"\n{dropped_n} of {total} upload(s) are not the work's footage "
          f"({NOT_FOOTAGE_CODE}, CF-0309)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
