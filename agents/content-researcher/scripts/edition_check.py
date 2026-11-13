#!/usr/bin/env python3
"""CF-0812: is the article about the edition of the thing the news is about?

The probe (`fact_probe.py`, CF-0263) is asked about a name - `Tesla Roadster`,
`The Scarab` - and the search resolves *an* article named after it. Nothing
held that article's subject against the news: batch example-tech
2026-10-19T0844Z topic 005 (the NEW Roadster) took `Tesla Roadster (first
generation)`, the 2008-12 car; example-film 2026-10-18T0841Z topic 009 (the
fourth Mummy film, asked with year 2027) took `The Scarab (1999 film)` -
accepted because nothing contradicted the type, and a year-count would not
have caught it either: that article names 2027 twice (the planned sequel).
ExampleFilm 2026-10-05T0701Z `Skyman: Man of Tomorrow` (2027) went through
the parent hop to `Skyman (2025 film)`. The article's text becomes the
topic's facts and support text, so a fact about another car or another film
would reach a script (CF-0263: the article must be about the thing itself).

**The rule.** An article whose title carries an EDITION qualifier -
`(first generation)`, `(2nd generation)`, `(generation 2)`, `(gen 2)`,
`(original)`, a year `(2008)` / `(1999 film)` / `(2019 TV series)` - is the
topic's article only when that edition is the news's:

  * the topic's own text (its name, year, season, parent and - when the
    caller passes it - its news: headlines, summaries, scene descriptions)
    names every marker of the qualifier; else
  * a **year** marker (`1999` in `(1999 film)`) is another edition when the
    topic has a year of its own and it is a different one, when the topic's
    text says it is about a new installment (sequel, prequel, reboot, remake,
    follow-up, installment, `part two`, ...), or when the year is older than
    `EDITION_RECENT_YEARS` before now. The article's own years are never
    counted for it - that is the Mummy case;
  * a **generation / original** marker is another edition unless the article
    is current: the newest year its prose names at least twice (one stray
    "In November 2023, ..." does not make an article about 2008-12 one about
    today) is no older than `EDITION_RECENT_YEARS` before now.

A qualifier that names no edition (`(TV series)`, `(film)`, `(smartphone)`)
and an unqualified title are the thing itself, as before. The same markers
and the same "current" test as the hunter's own-graphics count
(`agents/trend-hunter/scripts/footage_candidates.py` `other_subject`,
CF-0809), so the two ends of the pipeline call the same article the same
thing; this end adds the topic's year and the new-installment words, because
the probe has the year and the hunter's count does not need it.

Stdlib only.
"""
import datetime
import re

EDITION_RECENT_YEARS = 1
MISMATCH = "edition"

_ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                  "eighth", "ninth", "tenth")
QUALIFIED_TITLE_RE = re.compile(r"^(?P<base>.*\S)\s*\((?P<qual>[^()]+)\)\s*$")
EDITION_MARKER_RE = re.compile(
    r"\b(?:(?:" + "|".join(_ORDINAL_WORDS) + r"|\d+(?:st|nd|rd|th))[\s\-‐‑]+generation"
    r"|generation[\s\-‐‑]*\d+|gen[\s\-‐‑]*\d+|original|(?:19|20)\d\d)\b", re.I)
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
# The topic's own words for "this is not the edition you have, it is the next
# one". Deliberately not `new`, `upcoming` or `season`: a new trailer of the
# 2025 film and a new season of a series are the same work.
NEW_INSTALLMENT_RE = re.compile(
    r"\b(?:sequel|sequels|prequel|reboot|rebooted|remake|follow up|installment|"
    r"instalment|part (?:two|three|four|five|ii|iii|iv|v|[2-9])|chapter (?:two|three|[2-9]))\b")


def plain(text):
    """Lower case, hyphens and punctuation as spaces - "first-generation" and
    "First generation" are one marker."""
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").casefold()).split())


def _join(value):
    if isinstance(value, (list, tuple)):
        return " ".join(_join(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_join(value.get(k)) for k in ("title", "summary", "description",
                                                     "text"))
    return "" if value in (None, "") else str(value)


def as_year(value):
    """`2027`, `"2027"` -> 2027; anything else None."""
    match = YEAR_RE.search(str(value or ""))
    return int(match.group(0)) if match else None


def subject_of(name=None, year=None, season=None, parent=None, news=None, now_year=None):
    """What the topic itself says it is about - never the article. `news` is
    the caller's text of the topic's news (a string, or a list of strings /
    `{title, summary}` / `{description}` records)."""
    parts = [name, year, f"season {season}" if season else None, parent, _join(news)]
    return {"text": " " + plain(" ".join(str(p) for p in parts if p not in (None, ""))) + " ",
            "year": as_year(year),
            "now_year": now_year}


def news_of_topic(topic):
    """The news text of a Trend Hunter batch topic, as the probe sees it at
    selection: its title, scene descriptions, the headlines of its evidence
    and - on a topic that already has them - its news pieces of support text
    (rss summaries, the company's own page). Never its Wikipedia pieces."""
    if not isinstance(topic, dict):
        return ""
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    parts = [ref.get(k) for k in ("tool", "model")]
    parts.append(topic.get("title"))
    parts += [s.get("description") for s in topic.get("scenes") or [] if isinstance(s, dict)]
    evidence = topic.get("evidence") if isinstance(topic.get("evidence"), dict) else {}
    for key in ("rss_links", "sources", "news"):
        for item in evidence.get(key) or []:
            if isinstance(item, dict):
                parts += [item.get("title"), item.get("summary")]
    parts += [p.get("text") for p in topic.get("support_text") or []
              if isinstance(p, dict) and p.get("kind") in ("rss_summary", "vendor_page")]
    return " ".join(str(p) for p in parts if p not in (None, ""))


def article_years(wikitext, plain_text=None):
    """{year: count} over the article's prose (footnotes out: an access-date
    is not the article's subject)."""
    text = re.sub(r"<ref[^>]*/\s*>", "", wikitext or "", flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref\s*>", "", text, flags=re.S | re.I)
    if plain_text is not None:
        text = plain_text(text)
    counts = {}
    for y in YEAR_RE.findall(text):
        counts[int(y)] = counts.get(int(y), 0) + 1
    return counts


def other_edition(title, wikitext, subject, plain_text=None):
    """-> None when the article may be the topic's; else the record of why it
    is another edition: `{mismatch, qualifier, markers, unnamed, newest_year,
    now_year, detail}`. `subject` is `subject_of(...)`'s answer."""
    m = QUALIFIED_TITLE_RE.match(str(title or ""))
    if not m:
        return None
    qual = m.group("qual").strip()
    markers = [x.group(0) for x in EDITION_MARKER_RE.finditer(qual)]
    if not markers:
        return None
    subject = subject or subject_of()
    own = subject.get("text") or " "
    unnamed = [x for x in markers if f" {plain(x)} " not in own]
    if not unnamed:
        return None
    now = subject.get("now_year") or datetime.datetime.now(datetime.timezone.utc).year
    floor = now - EDITION_RECENT_YEARS
    topic_year = subject.get("year")
    years = [int(x) for x in unnamed if YEAR_RE.fullmatch(x)]
    newest = None
    why = None
    if years:
        edition = max(years)
        if topic_year is not None and topic_year != edition:
            why = f"the topic is about {topic_year}"
        elif NEW_INSTALLMENT_RE.search(own):
            why = (f"the topic's text is about a new installment "
                   f"({NEW_INSTALLMENT_RE.search(own).group(0)!r})")
        elif edition < floor:
            why = f"{edition} is older than {floor} and nothing in the topic names it"
        newest = edition
    if why is None and len(years) < len(unnamed):
        counts = article_years(wikitext, plain_text)
        seen = [y for y, c in counts.items() if c >= 2]
        newest = max(seen) if seen else None
        if newest is None or newest < floor:
            why = (f"the newest year its prose names twice is {newest}" if newest is not None
                   else "its prose names no year twice") + f" (older than {floor})"
    if why is None:
        return None
    names = ", ".join(repr(x) for x in unnamed)
    return {"mismatch": MISMATCH, "qualifier": qual, "markers": markers,
            "unnamed": unnamed, "newest_year": newest, "now_year": now,
            "detail": (f"article {title!r} is about another edition ({qual}) than the topic: "
                       f"the topic's own text does not name {names} and {why} "
                       f"(CF-0263, CF-0812)")}
