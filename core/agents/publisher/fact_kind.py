#!/usr/bin/env python3
"""CF-0919: is a video of the копилка news (it goes off) or evergreen (the
reserve keeps it)? Read off the video's own fact - its title, description and
the claims of its note - not off the dates of the sources the topic was found
in: a dated source is where the topic came from, and nearly every topic has one
(CF-0918 read it, and on 04.11 Doctor Who of 1964 and Palantir of 2013 came out
as news going stale in 14 days).

A video is `news` when

* its words speak of what is still to come (`FUTURE_RE`: will, due, upcoming,
  coming, is slated to...) - in the title, the description or a claim;
* or a date it names is ahead of the acceptance - anywhere in those texts. A
  date with no year is read in the acceptance's year and counts only when it
  is ahead and its sentence does not tell of the past («released it on
  November second» of a 2012 story);
* or the title or description names a date with its year no older than
  `FRESH_DAYS` (60) days from the acceptance.

Everything else is `evergreen`. What is deliberately not counted, on the real
pile of 04.11: a date with no year behind the acceptance («on November first»,
the-gilded-age; «on October thirtieth», homepod-mini-2) - and a fresh date only
in a claim, not in the headline (exponential-time-hypothesis names 26.10.2026 in
its narration and is a video about a theorem). A disputed case is what the
manual mark is for (`publish_stash.py kind`).

The texts: the card's `## Название`, `## Описание` (without its source line and
hashtags) and the claims of `## Утверждения` (the claim, not the source's quote
under it); with no card or no claims there - the script in the batch's 03
(`fact.text`, `claims[]`, `story_claims[]`, `hook`, `commentary`, `payoff`). A
`## Публикация` is never read: it is the factory's own dates.

    python3 agents/publisher/fact_kind.py NOTE.md --accepted YYYY-MM-DD   # the verdict, for a look
"""
import argparse
import calendar
import json
import re
import sys
from datetime import date
from pathlib import Path

AGENT = Path(__file__).resolve().parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import publish_note                                             # noqa: E402

TASK = "CF-0919"
FRESH_DAYS = 60
NEWS, EVERGREEN = "news", "evergreen"
KINDS = (NEWS, EVERGREEN)

FUTURE_RE = re.compile(
    r"(?<!free )(?<!ill )(?<!good )\bwill\b(?: \w+){0,2}"
    r"|\bWill (?:Be|Arrive|Launch|Release|Return|Premiere|Debut|Ship|Open|Start|Come)\b(?: \w+)?"
    r"|(?i:\b(?:is|are)\s+due\b(?!\s+to\b)"
    r"|\bdue\s+(?:in|on|out|for|next|this|later|early|back)\b"
    r"|\bdue\s+to\s+(?:arrive|launch|release|open|ship|start|come|debut|premiere|be)\b"
    r"|\bupcoming\b"
    r"|\b(?:is|are)\s+coming\b"
    r"|\bcoming\s+(?:soon|next|this|in|later|out|back|to(?!\s+terms))\b"
    r"|\b(?:is|are)\s+(?:set|slated|scheduled|planned|expected|stated|poised)\s+(?:to|for)\b"
    r"|\bnext\s+(?:year|month|week|season|spring|summer|fall|autumn|winter)\b"
    r"|\blater\s+this\s+(?:year|month|week|season)\b)")
# a sentence telling of the past: its date with no year is not read as ahead
PAST_RE = re.compile(
    r"(?i:\b(?:was|were|had|has|have|did|announced|released|launched|premiered|debuted|opened"
    r"|began|started|wrapped|shipped|arrived|rose|fell|ended|said|reported|aired)\b)")

_FULL = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
         "October", "November", "December")
MONTHS = {m: i + 1 for i, m in enumerate(_FULL)}
MONTHS.update({m[:3]: i + 1 for i, m in enumerate(_FULL) if m != "May"})
MONTHS["Sept"] = 9
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_ONES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
        "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
        "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
        "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
_SEP = r"[ -]"
_TAIL = (rf"(?:(?:{'|'.join(_TENS)})(?:{_SEP}(?:{'|'.join(_ONES)}))?"
         rf"|{'|'.join(_TEENS)}|{'|'.join(_ONES)})")
_YEAR_WORDS = (rf"(?:(?:nineteen|twenty){_SEP}(?:oh{_SEP})?{_TAIL}"
               rf"|two{_SEP}thousand(?:{_SEP}and)?(?:{_SEP}{_TAIL})?)")
_YEAR = rf"(?:(?:1[5-9]|20|21)\d\d(?!\d)|{_YEAR_WORDS})"
_DAY_WORDS = (rf"(?:(?:twenty|thirty){_SEP}(?:{'|'.join(k for k, v in _ORD.items() if v < 10)})"
              rf"|{'|'.join(_ORD)})")
_DAY = rf"(?:(?:3[01]|[12]?\d)(?:st|nd|rd|th)?(?![\d,]*\d)|{_DAY_WORDS}\b)"
_DATE_RE = re.compile(
    # 1 July 2026, the third of December
    rf"\b(?P<day1>{_DAY})(?: of)? (?P<mon1>{_MON})\b\.?(?:,? (?P<year1>{_YEAR})\b)?"
    # October 26, 2026 / Oct. 23 / November twentieth, twenty twenty-six / October 2026
    rf"|\b(?P<mon2>{_MON})\b\.?(?: (?P<day2>(?!{_YEAR}\b){_DAY}))?(?:,? (?P<year2>{_YEAR})\b)?"
    # 2026-11-20
    rf"|\b(?P<iso>(?:19|20|21)\d\d-[01]\d-[0-3]\d)\b")
_BARE_MONTH_BEFORE = re.compile(
    r"(?:\b(?:in|by|until|till|this|from|since|late|early|mid|next)[ -]|:\s*)$", re.I)
_YEAR_ONLY_RE = re.compile(rf"\b(?:in|by|until|for|during) (?P<year>{_YEAR})\b", re.I)
_CLAIM_RE = re.compile(r"(?m)^- \*\*[^*\n]+:\*\* «(.*)»\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z«“\"])")


def _year_value(text):
    """The year a digit or a spoken year says: 2026, «twenty twenty-six»,
    «nineteen sixty four», «two thousand twenty four» - None when it is neither."""
    t = str(text).strip().lower()
    if t.isdigit():
        return int(t)
    words = re.split(r"[ -]+", t)
    if words[:2] == ["two", "thousand"]:
        base, rest = 2000, [w for w in words[2:] if w != "and"]
    elif words[0] == "nineteen":
        base, rest = 1900, words[1:]
    elif words[0] == "twenty":
        base, rest = 2000, words[1:]
    else:
        return None
    rest = [w for w in rest if w != "oh"]
    n = 0
    for w in rest:
        n += _TENS.get(w) or _TEENS.get(w) or _ONES.get(w) or 0
    return base + n


def _day_value(text):
    t = str(text).strip().lower()
    digits = re.match(r"\d+", t)
    if digits:
        return int(digits.group(0))
    words = re.split(r"[ -]+", t)
    if len(words) == 2:
        return _TENS.get(words[0], 0) + _ORD.get(words[1], 0)
    return _ORD.get(t)


def _span(year, month, day):
    """`(first day, last day)` of a named day or month, or None for no such date."""
    try:
        if day is not None:
            at = date(year, month, day)
            return at, at
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None


def dates_in(text, on):
    """The dates `text` names: `[{text, start, end, year_named}]`; a date with no
    year is read in the year of `on` (a month alone only after «in», «by», «:»... -
    «May» opening a title is a modal, «March» a verb)."""
    out = []
    for m in _DATE_RE.finditer(text):
        if m.group("iso"):
            y, mon, d = (int(x) for x in m.group("iso").split("-"))
            span = _span(y, mon, d)
            if span:
                out.append({"text": m.group(0), "start": span[0], "end": span[1],
                            "year_named": True})
            continue
        mon_name = m.group("mon1") or m.group("mon2")
        day_text = m.group("day1") or m.group("day2")
        year_text = m.group("year1") or m.group("year2")
        day = _day_value(day_text) if day_text else None
        if day_text and not day:
            continue
        if not day_text and not year_text and (
                mon_name not in _FULL or not _BARE_MONTH_BEFORE.search(text[:m.start()])):
            continue
        year = _year_value(year_text) if year_text else on.year
        span = _span(year, MONTHS[mon_name], day) if year else None
        if span:
            out.append({"text": m.group(0).strip(), "start": span[0], "end": span[1],
                        "year_named": bool(year_text)})
    for m in _YEAR_ONLY_RE.finditer(text):
        y = _year_value(m.group("year"))
        if y and y > on.year:            # a year alone speaks only of what is ahead
            out.append({"text": m.group(0), "start": date(y, 1, 1), "end": date(y, 12, 31),
                        "year_named": True})
    return out


def _sentences(text):
    return [s for s in _SENTENCE_RE.split(str(text or "")) if s.strip()]


def judge(headline, claims, accepted_on):
    """`{feed_kind, news_why, ahead (latest date ahead, ISO, or None), fresh
    (latest fresh date of the headline, ISO, or None)}` for the texts of one
    video, by the rule of the module's docstring."""
    on = accepted_on
    texts = [t for t in list(headline) + list(claims) if isinstance(t, str) and t.strip()]
    words = None
    ahead, fresh = [], []
    for t in texts:
        if words is None:
            m = FUTURE_RE.search(t)
            words = m.group(0).strip() if m else None
        for s in _sentences(t):
            for d in dates_in(s, on):
                if d["start"] > on and (d["year_named"] or not PAST_RE.search(s)):
                    ahead.append(d)
    for t in headline:
        for s in _sentences(t):
            for d in dates_in(s, on):
                if d["year_named"] and d["start"] <= on and (on - d["end"]).days <= FRESH_DAYS:
                    fresh.append(d)
    later = max(ahead, key=lambda d: d["end"]) if ahead else None
    recent = max(fresh, key=lambda d: d["end"]) if fresh else None
    if words:
        why = f"«{words}»"
    elif later:
        why = f"«{later['text']}»: дата впереди"
    elif recent:
        why = f"«{recent['text']}»: дата не старше {FRESH_DAYS} дн. от принятия"
    else:
        why = None
    return {"feed_kind": NEWS if why else EVERGREEN, "news_why": why,
            "ahead": later["end"].isoformat() if later else None,
            "fresh": min(recent["end"], on).isoformat() if recent else None}


def from_note(text):
    """`(headline texts, claims)` of a card's text."""
    sec = publish_note.sections(text)
    title, about = publish_note.title_and_description(sec)
    headline = []
    if title:
        headline.append(re.sub(r"\s*#\w+", "", title).strip())
    for line in str(about or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("The fact in this video"):
            continue
        headline.append(line)
    return headline, _CLAIM_RE.findall(str(sec.get("Утверждения") or ""))


def from_script(batch_dir, topic_id):
    """`(headline texts, claims)` of the topic's script in the batch's 03."""
    if batch_dir is None or not topic_id:
        return [], []
    try:
        data = json.loads((Path(batch_dir) / "03-content-researcher.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    for sc in (data.get("scripts") or []) if isinstance(data, dict) else []:
        if not isinstance(sc, dict) or sc.get("topic_id") != topic_id:
            continue
        fact = sc.get("fact")
        headline = [fact["text"]] if isinstance(fact, dict) and fact.get("text") else []
        claims = [c.get("text") for f in ("claims", "story_claims") for c in (sc.get(f) or [])
                  if isinstance(c, dict)]
        claims += [sc.get(k) for k in ("hook", "commentary", "payoff", "narration")
                   if isinstance(sc.get(k), str)]
        return headline, [c for c in claims if isinstance(c, str)]
    return [], []


def of_video(card_path, batch_dir, topic_id, accepted_on):
    """`judge` over the video's texts: its card, what the card lacks - its script."""
    headline, claims = [], []
    if card_path and Path(card_path).is_file():
        headline, claims = from_note(Path(card_path).read_text(encoding="utf-8"))
    if not headline or not claims:
        h, c = from_script(batch_dir, topic_id)
        headline, claims = headline or h, claims or c
    return judge(headline, claims, accepted_on)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fact_kind.py", description=__doc__.splitlines()[0])
    ap.add_argument("note")
    ap.add_argument("--accepted", required=True, help="YYYY-MM-DD")
    ns = ap.parse_args(argv)
    print(json.dumps(of_video(ns.note, None, None, date.fromisoformat(ns.accepted)),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
