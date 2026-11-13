#!/usr/bin/env python3
"""CF-0927: a shot cut from an upload whose title is about another work is not
the topic's own footage - the frame judge's copy of trend-hunter's CF-0924
rule (`agents/trend-hunter/scripts/footage_sieve.py`, `other_work_title`).

Why: Reel 2026-11-08T1117Z, the Jon Marrow topic (`lf-2026-11-08-020`). The
whole Short was cut from one upload, `jQHoAsDcjVU` "Karōshi (2027) Official
Trailer - Teo Yoo, ..." on Example Pictures - a film *from the producer of*
Jon Marrow. The frame judge read `judge_sources.py`'s "official - channel
'Example Pictures'" and wrote nine `neutral`s ("from Example Pictures's own upload
... does not fight it"); the gate passed the video at E 58.54 and the
acceptance refused it `wrong_work_footage`. A studio uploads all its films:
`origin: official` says whose cut it is, never which work. CF-0924 now drops
such a candidate in the Trend Hunter's sieve; what the metadata did not catch
(an older batch, a pool source, a candidate offered another way) reaches the
judge, and the judge needs the same rule.

The rule, the two branches of CF-0924, read off the upload's own title:

  * **a credit, not a subject** - every place the title names the work, the
    words right before it are the marketing credit formula ("from the
    producer of", "From Zach Cregger, director of", "dari Produser"). One
    naming outside a credit keeps the upload. Any origin.
  * **an official upload of another work** - an official upload whose title
    does not name the work, whose channel does not name it either, and whose
    head (`title_subject`, the text before the first separator) holds a Latin
    word that is not the label of a cut. A head in another script, a generic
    label ("Official Trailer 2") and a maker's credit as the head ("A
    Christopher Nolan Film", "From Christopher Nolan") are not read as another
    work: unknown is not other, and a work under its director's name is the
    work. An unofficial upload that does not name the work is CF-0924's
    `work_not_in_title` upstream; its head may be a person of the work (an
    interview with the lead), so the judge does not read it here.

Only for a screen work (`title_ref.kind == "work"`, `type` film or tv_series)
- the topics CF-0924's official branch reads. A Tech product's own vendor demo
may never say the product's name, and a story is named by its subjects.

A flag the Trend Hunter already wrote is taken as it is: an upload whose
record in the video's own topic carries `rule: other_work_title` and
`title_subject` (CF-0924's drop record) needs no second reading.

The word lists are a copy, not an import: the Trend Hunter is its own repo on
its own pin (v3.0), and the root may not reach into it at run time. When
CF-0924's `credit_phrases` (agents/trend-hunter/config/footage_sieve.json)
grow, copy the entry here with its `seen_in`.

What the judge does with a hit is the gate's (scripts/frame_judge_gate.py):
the entry is `contradicts` with `mismatch: work`, whatever the model wrote.
"""
from __future__ import annotations

import re
import unicodedata

TASK = "CF-0927"
RULE = "other_work_source"
MISMATCH = "work"
# The acceptance code the user refuses such a video with (TRIAGE, acceptance).
ACCEPTANCE_CODE = "wrong_work_footage"
# CF-0924's rule code in the Trend Hunter's drop record, and its subject key.
TREND_RULE = "other_work_title"
SUBJECT_KEY = "title_subject"
SCREEN_TYPES = ("film", "tv_series")
OFFICIAL_ORIGINS = ("official", "vendor_official")

# agents/trend-hunter/config/footage_sieve.json `credit_phrases` (v3.0)
CREDIT_PHRASES = (
    {"pattern": r"\bfrom\s+(?:[\w']+\s+){0,3}?(?:producers?|directors?|creators?|makers?|"
                r"writers?|filmmakers?|studios?|team)\s+(?:of|behind)(?:\s+the)?",
     "what": "the English marketing credit - 'From the producer of X'",
     "seen_in": {"video_id": "oBWrb8HTU44",
                 "title": "Resident Dread – Official Teaser Trailer. From Zach Cregger, "
                          "director of Weapons and Barbarian.",
                 "verdict": "kept - names its own work first"}},
    {"pattern": r"\bdari\s+(?:[\w']+\s+){0,3}?(?:produser|sutradara|pembuat|kreator)"
                r"(?:\s+film)?",
     "what": "the Indonesian credit - 'dari Produser X'",
     "seen_in": {"video_id": "9ia-5fCvqDI",
                 "title": "Karōshi Rilis Trailer Perdana, Film Baru dari Produser Jon Marrow",
                 "verdict": "wrong_work_footage"}},
)
_CREDITS = [dict(c, _re=re.compile(c["pattern"] + r"\s*$", re.I)) for c in CREDIT_PHRASES]

# topic_relevance.py (trend-hunter): the forms of a work's name
ARTICLES = ("the ", "a ", "an ")
SEQUEL_TAIL = re.compile(r"\s+(\d{1,2}|ii|iii|iv|v|vi)$")
ACRONYM_STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with"}
MIN_NEEDLE = 3
MIN_SPACELESS = 6
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})

# footage_sieve.py (trend-hunter): the head of a title and the label words
_HEAD_END = re.compile(r"\s[-–—|·:]\s|[|–—·:(\[,]|\.\s")
_LATIN_WORD = re.compile(r"[a-z][a-z0-9']*", re.I)
YEAR_WORD = re.compile(r"^(19|20)\d\d$")
LABEL_WORDS = frozenset("""
    official trailer trailers teaser teasers clip clips featurette promo spot tv
    final new first look full hd uhd imax red band international exclusive sneak
    peek season seasons episode part extended the a an and of
    """.split())
# CF-0927: a head that is a maker's credit, not a work - "A Christopher Nolan
# Film", "From Christopher Nolan", "Christopher Nolan's". The work under its
# director's name is the work; the head names nobody else's film.
MAKER_HEAD = re.compile(
    r"^(?:an?\s+(?:[\w.'-]+\s+){2,3}(?:film|movie|picture|production|joint|series)"
    r"|(?:from|by)\s+.+|[^\s].*'s)$", re.I)


def normalise(text):
    """Lowercased, curly punctuation flattened, everything that is not a-z/0-9
    one space, a space at each end - a substring test is a whole-word test
    (trend-hunter fact_probe_topics.normalise)."""
    if not text:
        return " "
    flat = str(text).translate(_APOSTROPHES).lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", flat).strip() + " "


def _add(value, into):
    needle = normalise(value).strip()
    if needle and len(needle) >= MIN_NEEDLE and needle not in into:
        into.append(needle)


def _ref(title_ref):
    if isinstance(title_ref, str):
        return {"name": title_ref}
    return dict(title_ref) if isinstance(title_ref, dict) else {}


def is_screen_work(title_ref):
    """A film or a series topic - the only topics this rule reads."""
    ref = _ref(title_ref)
    return ref.get("kind") == "work" and ref.get("type") in SCREEN_TYPES


def work_forms(title_ref):
    """The normalised needles that count as naming the work - the name, its
    stem and subtitle around a colon, `parent_work`, without a leading article
    or a sequel number, space-less, and its acronyms; never the person
    (trend-hunter topic_relevance.work_forms for a work)."""
    ref = _ref(title_ref)
    name = str(ref.get("name") or "").strip()
    names = []
    _add(name, names)
    if ":" in name:
        stem, _, subtitle = name.partition(":")
        _add(stem, names)
        _add(subtitle, names)
    _add(ref.get("parent_work") or ref.get("parent"), names)
    person = normalise(ref.get("person")).strip()
    if person:
        names = [n for n in names if n != person]
    forms = list(names)
    for n in names:
        for article in ARTICLES:
            if n.startswith(article) and len(n) > len(article):
                _add(n[len(article):], forms)
        stripped = SEQUEL_TAIL.sub("", n)
        if stripped != n:
            _add(stripped, forms)
    for form in list(forms):
        flat = form.replace(" ", "")
        if flat != form and len(flat) >= MIN_SPACELESS:
            _add(flat, forms)
    for form in list(forms):
        words = form.split()
        for chosen in (words, [w for w in words if w not in ACRONYM_STOPWORDS]):
            if len(chosen) >= 3:
                _add("".join(w[0] for w in chosen), forms)
    return forms


def title_subject(title):
    """The head of a title, the text before its first separator: "Karōshi
    (2027) Official Trailer - Teo Yoo" -> "Karōshi"."""
    text = str(title or "").strip(" -–—|·:,.")
    head = _HEAD_END.split(text, maxsplit=1)[0] if text else ""
    return head.strip(" -–—|·:,.\"'«»“”") or None


def _plain(text):
    flat = unicodedata.normalize("NFKD", str(text or "").translate(_APOSTROPHES))
    return "".join(ch for ch in flat if not unicodedata.combining(ch)).lower()


def names_something(head):
    """The Latin words of a head that are not the label of a cut, a number or
    a year - empty for a generic label or a head in another script."""
    words = [w.strip("'") for w in _LATIN_WORD.findall(_plain(head))]
    return [w for w in words if w and w not in LABEL_WORDS and not w.isdigit()
            and not YEAR_WORD.match(w)]


def _namings(title, forms):
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


def _credit_before(prefix):
    flat = re.sub(r"[\W_]", " ", prefix)
    for c in _CREDITS:
        found = c["_re"].search(flat)
        if found:
            return c, found.start()
    return None, None


def is_official(upload):
    up = upload if isinstance(upload, dict) else {}
    return (up.get("footage_origin") in OFFICIAL_ORIGINS
            or up.get("origin") in OFFICIAL_ORIGINS)


def _hit(upload, branch, subject, work, why):
    up = upload or {}
    return {"rule": RULE, "task": TASK, "mismatch": MISMATCH, "branch": branch,
            SUBJECT_KEY: subject, "work": work, "video_id": up.get("video_id"),
            "title": up.get("title"), "channel_title": up.get("channel_title"),
            "why": why}


def check(upload, title_ref, forms=None, ready_subject=None):
    """-> the hit (a dict: `branch` credit / official_other_work / trend_hunter,
    `title_subject`, `work`, `why`) when the shot's upload is about another
    work than the screen-work topic `title_ref`, or None. `ready_subject` is
    the Trend Hunter's own `title_subject` for this upload in this topic
    (CF-0924's drop record), taken as it is. An upload with no title is None:
    unknown is not other."""
    if not is_screen_work(title_ref) or not isinstance(upload, dict):
        return None
    work = _ref(title_ref).get("name")
    if ready_subject:
        return _hit(upload, "trend_hunter", ready_subject, work,
                    f"the Trend Hunter read this upload's title as about {ready_subject!r}, "
                    f"not {work!r} (CF-0924 `{TREND_RULE}`)")
    title = str(upload.get("title") or "")
    forms = work_forms(title_ref) if forms is None else forms
    if not title.strip() or not forms:
        return None
    low, spans = _namings(title, forms)
    if spans:
        credits = []
        for start, end in spans:
            entry, at = _credit_before(low[:start])
            if not entry:
                return None                       # named as itself at least once
            credits.append((start, end, at))
        start, end, at = credits[0]
        subject = title_subject(title[:at]) if at else None
        if not subject:
            subject = title_subject(title[max(e for _, e, _ in credits):]) or None
        return _hit(upload, "credit", subject, work,
                    f"its title names {work!r} only as a credit "
                    f"({title[at:end].strip()!r}) - the upload is about "
                    f"{subject or 'another work'!r}")
    if not is_official(upload):
        return None
    if normalise(upload.get("channel_title")).strip() and any(
            f" {f} " in normalise(upload.get("channel_title")) for f in forms):
        return None                               # the work's own channel
    subject = title_subject(title)
    if not names_something(subject) or MAKER_HEAD.match(_plain(subject or "").strip()):
        return None
    return _hit(upload, "official_other_work", subject, work,
                f"an official upload whose title is about {subject!r} and never names "
                f"{work!r} - a studio uploads all its films; official says whose cut it "
                f"is, not which work")
