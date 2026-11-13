#!/usr/bin/env python3
"""CF-0184/CF-0237/CF-0439: candidates for the script's one fact, out of
Wikipedia.

CF-0183 made `production_fact` a required field of every script and gave it a
gate (`check_production_fact.py`). This module is the other end: where the
writer gets the fact from when the hunter did not settle one (CF-0438 - an
old batch, or a `re_ask`). It reads **every prose section** of the article
about the title and hands back short statements that could be that fact,
each with the URL it is shown with and the `kind` of fact it is.

**Any kind of fact** (CF-0439, the stance: a retelling plus one verifiable
fact of any kind the story does not tell). The kind comes from the section's
heading - `Box office` is `box_office`, `Release` is `release`, `Casting`,
`Reception`, `Controversy`, `Personal life`... (`HEADING_KINDS`, the same map
as the hunter's `fact_search.py`) - and in the Production tree, the lead and
an unnamed section from the sentence's own words (`KIND_SIGNALS`). The plot,
cast and episode lists, tables and the References are never read.

**What a candidate has to be**, and why each condition is there:

* *with a footnote* - the footnote is the whole reason this source was chosen.
  The channel shows the fact with its source (`insert_layers.proof`, CF-0071)
  rather than on its own word, so a sentence Wikipedia itself does not source
  is not a fact we can show. The article URL is always returned; the
  footnote's own URL is returned when the citation carries one.
* *short* - it has to be sayable in one beat of the commentary and, at 60
  characters, on screen. A paragraph is not a fact.
* *concrete* - a number (a count of takes, nights, dollars, screens) or a
  name (a person, a place, a stage). "The shoot was difficult" is not a fact.
* *about the craft, when it is a production fact* - what was done, to what:
  shot, built, re-laid, rigged, rehearsed, improvised.

**What is thrown away, by name** (`REJECTIONS` and `judge`): announcements,
talks and negotiations (nothing that has not happened can be shown as a
fact), bare schedule lines ("principal photography began in December 2025",
"released on 5 May 2023" - a date alone), lists, the lead's definition of the
work, and anything with no footnote. Every rejection is reported with its
reason, so a title that yields nothing can be *read* rather than guessed at.

**Empty is a result, not a failure.** No article, no section to read, no
sentence that survives: `status` says which, `candidates` is `[]`, and nothing
is raised. CF-0185's refusal rule is what reads that emptiness; a module that
raised instead would break it. Only an unreachable source raises
(`wikipedia_api.WikipediaError`) - a run that could not ask must never look
like a title with no facts.

**The article has to be about this work** (CF-0263, decision of CF-0260's
grill on 2026-09-17). A search for a title resolves to *an* article, and the
fact off the wrong one passes every checker downstream - compliance judges
how concrete a sentence is, never what it is about. So the caller says what
the topic is (`work_type`, `year`, `network`) and the resolved article is
held against it: `Wren Hollow` for a topic about the Example Network series resolved to
`Wren Hollow (film series)` and handed back five perfectly good facts about
the wrong work. A contradiction is the fifth outcome, `wrong_article`, which
names the article it refused and counts as no fact at all.

**A spin-off borrows from the parent named in the topic.** `Rennick: Quill`
has no article of its own (`no_article`), and the topic itself says the word
`Rennick`; the lookup goes on to `Rennick (TV series)` and marks the result
`parent_work`, so the writer's lead-in can say where the fact is from ("in
the main series...") instead of pretending it is about the spin-off. Only a
parent the topic names - never a title that merely looks similar.

**How a candidate becomes the script's fact** (the writer's step 2, the gate
CF-0183): `kind` -> `fact.kind`, `text` -> `production_fact.text` (a record of the fact, trimmed or
rewritten in the channel's voice), `source_url` -> `production_fact.source_url`
(the article with the section anchor; `citation_url` is the primary source
behind it, for the writer to read and to cite instead when it is better).
`beat_text` and `on_screen` are **not** here and cannot be: the beat is a
verbatim substring of a commentary nobody has written yet, and the screen
wording is the channel's, not the encyclopedia's. `fits_on_screen` says
whether the sentence would fit in the 60-character budget as it stands.

Usage::

    python3 scripts/production_facts.py --title "Bunker" --year 2026
    python3 scripts/production_facts.py --from-batch \\
        ~/shorts-content-factory/pipeline/<channel>/<batch>/01-trend-hunter.json

Stdlib only; no venv in this repository.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
from wikipedia_api import (MAX_REQUESTS_PER_TOPIC, NO_ARTICLE_DISAMBIGUATION,  # noqa: E402
                           WikipediaClient,
                           WikipediaError, anchored, document_of,
                           matches_topic, plain_text, resolve_article,
                           verify_article)
import edition_check  # noqa: E402

# The five ways a lookup can end. The first four are CF-0184's and are the
# words `channels/<channel>.json` -> `production_fact_refusal.not_found`
# pins; `wrong_article` is CF-0263's and is deliberately *not* in that list,
# because that list is pinned by the root's schema and a new loss code in the
# root's funnel is not what this is - see `fact_refusal.py`, which reads it as
# the emptiness it is under the funnel code the channel already has.
STATUS_OK = "ok"
STATUS_NO_ARTICLE = "no_article"
STATUS_NO_SECTION = "no_section"
STATUS_NO_CANDIDATES = "no_candidates"
STATUS_WRONG_ARTICLE = "wrong_article"
# CF-0828: why a `no_article` has no article, when the reason is known - every
# candidate the search gave was a disambiguation page (`Amazon`, `Mercury`).
# A sub-reason, not a status: `status` stays `no_article`, the word the
# channel's `production_fact_refusal.not_found` and the root's schema pin, and
# the funnel counts the loss under `no_fact` as before. It is on the result as
# `sub_reason`, with the pages under `skipped_articles`, only when set.
NO_ARTICLE_REASON_DISAMBIGUATION = NO_ARTICLE_DISAMBIGUATION

# CF-0263: how a topic may name its parent work. Only the topic's own words
# count - `Rennick: Quill` names `Rennick`, and that is the whole of the
# derivation. A title that merely looks similar is never a parent: the
# viewer is owed a lead-in that is true ("in the main series..."), and a
# fact off a neighbouring show is exactly the wrong-article problem again.
PARENT_SEPARATORS = (":", " – ", " — ", " - ")
MIN_PARENT_CHARS = 3

# -- the section tree ------------------------------------------------------
HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)

# Headings that open the production tree. `Production` is the usual root; the
# others appear as roots of their own on articles that have no `Production`.
PRODUCTION_HEADING_RE = re.compile(
    r"^(production|filming|principal photography|shooting|cinematography|"
    r"visual effects|special effects|effects|stunts|production design|"
    r"set design|costume design|costumes|make-?up|prosthetics|animation|"
    r"post-?production|editing|filming and post-?production|"
    r"development and production|production and filming)\b", re.I)

# Subsections of the tree that are about something else than how it was made.
# `Development` stays in: it holds "the floor had to be re-laid" as often as
# it holds announcements, and the content rules below judge those.
EXCLUDED_HEADING_RE = re.compile(
    r"^(cast|casting|writing|music|soundtrack|score|marketing|promotion|"
    r"release|box office|budget|financing|distribution|legal|lawsuits?|"
    r"reception|accolades|awards|critical response|audience|ratings|"
    r"home media|controversy|controversies|themes|analysis|references|"
    r"notes|external links|see also|bibliography|episodes)\b", re.I)

# -- citations -------------------------------------------------------------
REF_RE = re.compile(r"<ref(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</ref\s*>)",
                    re.S | re.I)
REF_NAME_RE = re.compile(r"""name\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>]+))""", re.I)
CITE_URL_RE = re.compile(r"\|\s*(?:url|URL)\s*=\s*([^|}\n]+)")
CITE_ARCHIVE_URL_RE = re.compile(r"\|\s*archive-?url\s*=\s*([^|}\n]+)", re.I)
BARE_URL_RE = re.compile(r"https?://[^\s|}\]<]+")
# CF-0241: what a footnote says about the document it points at. A proof of a
# fact taken from a primary source has to show that source own publication,
# title and date, and the footnote is the only place this pipeline ever sees
# them - the cited page is not fetched (its host is not in the pool anyone
# decided to fetch, CF-0045). Each field is whatever the citation template
# carries, and None when it carries nothing.
CITE_TITLE_RE = re.compile(r"\|\s*title\s*=\s*([^|}\n]+)", re.I)
CITE_DATE_RE = re.compile(r"\|\s*(?:date|publication-date)\s*=\s*([^|}\n]+)", re.I)
CITE_WORK_RE = re.compile(
    r"\|\s*(?:work|website|newspaper|magazine|journal|publisher)\s*=\s*([^|}\n]+)", re.I)
WIKILINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
QUOTES_RE = re.compile(r"'{2,}")
DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y")
ARCHIVE_HOSTS = ("web.archive.org", "archive.today", "archive.ph", "archive.is")

# Markers that stand in for a footnote while the wikitext is cleaned, so a
# sentence keeps the footnotes that belong to it. Private-use characters:
# nothing in an article can collide with them.
MARK_OPEN, MARK_CLOSE = "", ""
MARK_RE = re.compile(MARK_OPEN + r"(\d+)" + MARK_CLOSE)

# -- what a fact looks like ------------------------------------------------
MIN_CHARS = 30
MAX_CHARS = 300

NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten", "eleven", "twelve", "fifteen", "twenty",
                "thirty", "forty", "fifty", "hundred", "dozen")
NUMBER_RE = re.compile(r"\b\d[\d,.]*\b|\b(?:" + "|".join(NUMBER_WORDS) + r")\b", re.I)
UNIT_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:-|\s)?\s*(?:takes?|days?|nights?|weeks?|months?|hours?|"
    r"minutes?|seconds?|shots?|set-?ups?|cameras?|lenses?|scenes?|episodes?|"
    r"pages?|drafts?|versions?|extras?|puppets?|miniatures?|feet|foot|metres?|"
    r"meters?|tons?|litres?|liters?|gallons?|pounds?|kilos?|degrees?)\b", re.I)
UNIT_WORD_RE = re.compile(
    r"\b(?:" + "|".join(NUMBER_WORDS) + r")\s+(?:takes?|days?|nights?|weeks?|"
    r"months?|hours?|cameras?|scenes?|set-?ups?|versions?|drafts?)\b", re.I)

CRAFT_RE = re.compile(
    r"\b(shot|shoots?|shooting|filmed|filming|re-?shot|reshoots?|takes?|"
    r"on set|the set|sets? (?:was|were|had)|soundstage|studio|location|"
    r"built|rebuilt|construct\w*|"
    r"re-?laid|practical|prosthetic\w*|animatronic\w*|puppet\w*|miniature\w*|"
    r"stunt\w*|rig\w*|harness|wire\w*|camera\w*|lens|lenses|handheld|"
    r"steadicam|anamorphic|drone|crane|dolly|improvis\w*|ad-?libbed|"
    r"rehears\w*|choreograph\w*|storyboard\w*|green ?screen|blue ?screen|"
    r"cgi|vfx|visual effects|make-?up|costume\w*|wig|prop|props|underwater|"
    r"blocking|coverage|principal photography|second unit|dailies|"
    r"edit(?:ed|ing)?|cut together|takes place on)\b", re.I)

# A fact worth a beat: a count of takes or nights, something rebuilt, a
# practical effect. These are what the stance asks for by name.
STRONG_RE = re.compile(
    r"\b(?:(?:one|two|three|single|first|second|third|fourth|fifth|\d+)\s*(?:-|\s)?"
    r"(?:takes?|nights?|days?)|takes?\b[^.]{0,20}\b\d+|\d+\s*takes?|"
    r"rebuilt|re-?laid|hand-?built|by hand|practical effects?|animatronic\w*|"
    r"miniatures?|without (?:cgi|visual effects|a stunt double)|"
    r"in (?:a )?single take|in one take|no cgi|transformed into|"
    r"converted into|doubled for|stood in for|re-?dressed|dressed as)\b", re.I)

# CF-0439: what a sentence is about. Until CF-0439 these four were
# rejections - the channel wanted only how the thing was made - and a budget,
# an opening weekend, a casting or a review was thrown away. The stance now
# asks for one verifiable fact *of any kind* the story does not tell, so they
# name the sentence's kind instead (`sentence_kind`), in this order: a
# sentence in the Production tree that says `$90 million` is a box-office
# fact read out of the Production tree, not a production one.
KIND_SIGNALS = (
    ("box_office", re.compile(
        r"\$|\b(budget|grossed|gross|box office|million|billion|tax credit|"
        r"financ\w*|salary|paid|profit|revenue|earnings|opening weekend|"
        r"viewers|viewership|ratings?)\b", re.I)),
    ("scandal", re.compile(
        r"\b(lawsuit|sued|sues|arrest\w*|alleg\w*|accus\w*|controvers\w*|"
        r"boycott\w*|banned)\b", re.I)),
    ("release", re.compile(
        r"\b(was|were|is|are) (?:released|scheduled)\b|"
        r"\b(premiere[ds]?|world premiere|release date|"
        r"distribut\w*|streaming|renewed|greenlit|green-?lit|ordered to series|"
        r"picked up|acquired|theatrical(?:ly)? release)\b", re.I)),
    ("casting", re.compile(
        r"\b(was|were) cast\b|\bcast as\b|\bjoined the cast\b|\bsigned on\b|"
        r"\breprise\w*\b|\bcast members?\b|\badded to the (?:cast|series|show)\b|"
        r"\b(?:exited|quit|left|departed|rejoined) the (?:show|series|cast|season)\b|"
        r"\breplaced\b[^.]{0,40}\b(?:cast|show|series|role)\b", re.I)),
    ("reception", re.compile(
        r"\b(review\w*|acclaim\w*|praise\w*|criticis\w*|criticiz\w*|"
        r"rotten tomatoes|metacritic|nominat\w*|won the|award\w*|"
        r"ovation|standing ovation)\b", re.I)),
)

# What stays a rejection, whatever the kind: news that something *will*
# happen. "Bravo announced filming would begin...", "Bullock and Kidman were
# in negotiations to reprise their roles", "named as potential new
# housewives" - none of it has happened, so none of it can be shown as a
# fact. These are the parts of the old money/release/casting rejections that
# threw away junk rather than a kind of fact.
REJECTIONS = (
    ("announcement", re.compile(
        r"\bannounc\w*\b|\bin (?:final )?(?:talks|negotiations)\b|"
        r"\bnegotiat\w*\b|\bwill (?:star|play|appear|be released|premiere)\b|"
        r"\bpotential new\b|\bis set to (?:star|play|appear|be released|premiere)\b|"
        r"\bexpected to\b|\brumou?r\w*\b", re.I)),
)

# "Principal photography began on 9 January 2025 in New York" - a date, a
# verb, nothing about how anything was made. Rejected unless the sentence
# also carries a duration or a craft noun of its own.
SCHEDULE_VERB_RE = re.compile(
    r"\b(began|begun|commenced|started|concluded|wrapped|completed|ended|"
    r"resumed|took place|is set to begin|was scheduled|"
    r"released|premiered|debuted|aired|opened)\b", re.I)
DATE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b|\b(19|20)\d{2}\b", re.I)
SCHEDULE_DETAIL_RE = re.compile(
    r"\b(takes?|nights?|weeks?|days? of (?:shooting|filming|production)|"
    r"rebuilt|re-?laid|built|practical|stunt\w*|miniature\w*|"
    r"soundstage|set was|sets were|underwater|handheld|single take)\b", re.I)

# A date and its day: what is left of a sentence's numbers once these are
# gone is what makes "premiered on 5 May 2023 to 12 million viewers" more
# than a line of the schedule.
DATE_NUMBER_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|"
    r"july|august|september|october|november|december)\b|"
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b|\b(?:19|20)\d{2}\b",
    re.I)

LIST_COMMA_CEILING = 4

# -- the kind of a section (CF-0439) --------------------------------------
# Sections that are never read: the story itself (the fact has to be one the
# story does not tell), lists of people, and the article's apparatus. A
# subsection of one of them is skipped with it. The same list as the hunter's
# `fact_search.SKIP_HEADING_RE` - the two ends read an article alike.
SKIP_HEADING_RE = re.compile(
    r"\b(plot|synopsis|premise|summary|story|cast|characters|episodes|"
    r"see also|references|notes|external links|further reading|bibliography|"
    r"citations|sources|footnotes|track listing|gallery)\b", re.I)

# Heading -> kind, first match wins (the hunter's `fact_search.HEADING_KINDS`).
HEADING_KINDS = (
    ("box_office", re.compile(r"box office|gross|commercial performance|ratings|"
                              r"viewership", re.I)),
    ("casting", re.compile(r"casting", re.I)),
    ("production", re.compile(r"production|filming|photography|shooting|development|"
                              r"design|writing|pre-production|post-production|effects|"
                              r"cinematograph|music|score|costume|make-?up|stunt|"
                              r"conception|origin|animation|editing|prosthetic", re.I)),
    ("release", re.compile(r"release|marketing|distribution|broadcast|premiere|"
                           r"home media|streaming|promotion", re.I)),
    ("reception", re.compile(r"reception|critical|accolades|awards|response|legacy|"
                             r"audience|reviews|impact", re.I)),
    ("scandal", re.compile(r"controvers|lawsuit|legal|allegation|dispute|criticism",
                           re.I)),
    ("people_news", re.compile(r"personal life", re.I)),
)
KIND_OTHER = "other"
# The order of preference among kinds when the best of each is lined up
# (`candidates_from_article`) - the hunter's `KIND_ORDER` as it stood before
# CF-0627 put the tie-break into the channel's `kinds`. It only orders this
# stage's own Wikipedia fallback (sections named by the patterns above); the
# gate on `kind` is the channel's list (check_production_fact.py, CF-0628).
KIND_ORDER = ("production", "box_office", "casting", "release", "reception",
              "scandal", "people_news", KIND_OTHER)
# The lead defines the work ("X is a 2024 American film directed by Y"):
# a name in it is not a fact. There a sentence has to carry a number, and a
# definition is refused even then.
LEAD_HEADING = ""
DEFINITION_RE = re.compile(
    r"^[^.]{0,80}\b(?:is|was) an? [^.]{0,80}\b(?:film|series|show|sitcom|drama|"
    r"miniseries|comedy|thriller|documentary|franchise|special|anthology)\b", re.I)

# Capitalised words that are not the kind of name that makes a fact concrete.
NAME_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "of", "and", "but", "for", "it", "he",
    "she", "they", "this", "that", "there", "when", "while", "after", "before",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
}
NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b")

# `Example Studios` is not two sentences, and neither is `J. J. Abrams`.
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "inc", "ltd", "co",
                 "vs", "no", "approx", "est", "prof", "gen", "col", "capt",
                 "bros", "corp", "dept", "prod", "ep", "vol", "ft", "mt",
                 "u.s", "u.k", "a.m", "p.m"}

ON_SCREEN_BUDGET = 60          # comparison_line.FACT_MAX_CHARS - CF-0186
DEFAULT_LIMIT = 5


# =========================================================== wikitext -> text
def collect_named_refs(wikitext):
    """`{ref name: body}` for the whole article - a footnote is often defined
    in one section and reused with `<ref name="x" />` in another (the Filming
    section of `Bunker (2026 film)` does exactly that), and a reused footnote
    is as good a source as its first use."""
    named = {}
    for match in REF_RE.finditer(wikitext):
        body = match.group("body")
        if not body:
            continue
        name = _ref_name(match.group("attrs") or "")
        if name and name not in named:
            named[name] = body
    return named


def _ref_name(attrs):
    found = REF_NAME_RE.search(attrs or "")
    if not found:
        return None
    return next((group for group in found.groups() if group), None)


def citation_url(body):
    """The URL a footnote points at: the citation's `url`, or its
    `archive-url` when that is all there is, or a bare link in the body.
    None for a footnote that cites a book, a DVD commentary or a tweet with
    no link - those are still footnotes, they just have no URL to pass on."""
    if not body:
        return None
    for match in CITE_URL_RE.finditer(body):
        url = match.group(1).strip()
        if url.startswith("http") and not any(h in url for h in ARCHIVE_HOSTS):
            return url.rstrip(" |}")
    for regex in (CITE_ARCHIVE_URL_RE,):
        match = regex.search(body)
        if match and match.group(1).strip().startswith("http"):
            return match.group(1).strip().rstrip(" |}")
    bare = BARE_URL_RE.search(body)
    return bare.group(0).rstrip(".,;") if bare else None


def _cite_value(text):
    """One field of a citation template as plain text: wiki links unwrapped,
    italics and comments gone. Empty becomes None - a field the footnote left
    blank is a field it does not have."""
    if not text:
        return None
    value = COMMENT_RE.sub("", text)
    value = WIKILINK_RE.sub(r"\1", value)
    value = QUOTES_RE.sub("", value).replace("&nbsp;", " ")
    value = re.sub(r"\s+", " ", value).strip().strip("|}").strip()
    return value or None


def iso_date(text):
    """A citation date as `YYYY-MM-DD`, or None.

    None covers both halves of CF-0241 rule about absence: a footnote with no
    date at all, and one that carries less than a whole date (`2025`,
    `May 2025`). A proof shows the date to the viewer, so a day this pipeline
    invented to fill the shape out would be worse than saying the footnote
    gives none - `published_at` is then null, and the writer can see that the
    document is not usable as a proof until somebody reads the date off it.
    """
    value = _cite_value(text)
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _first(regex, body):
    match = regex.search(body or "")
    return match.group(1) if match else None


def citation(body):
    """The document a footnote names, in the shape a proof source takes
    (inserts/proof.json script_contract, minus `handle`, which belongs to a
    post): where it is, who published it, what it is called and when it came
    out.

    CF-0241: a fact whose `source_url` is the primary source its footnote
    points at - as the fact of `lf-2026-09-15-004` is - can only be put on
    screen with these three fields beside the URL, and the footnote is where
    they are written down. Nothing is fetched to build this: it is the
    wikitext this module already has in hand.
    """
    return {"url": citation_url(body),
            "publication": _cite_value(_first(CITE_WORK_RE, body)),
            "title": _cite_value(_first(CITE_TITLE_RE, body)),
            "published_at": iso_date(_first(CITE_DATE_RE, body))}


def mask_refs(text, named_refs):
    """Replace every footnote with a marker and return (masked text, refs).

    The marker keeps the footnote attached to its sentence through the
    cleaning below - which is the only way to tell a sourced statement from
    an unsourced one after the wikitext is gone.
    """
    refs = []

    def swap(match):
        body = match.group("body")
        if not body:
            body = named_refs.get(_ref_name(match.group("attrs") or ""), "")
        refs.append({"url": citation_url(body), "body": body or "",
                     "citation": citation(body)})
        return f"{MARK_OPEN}{len(refs) - 1}{MARK_CLOSE}"

    return REF_RE.sub(swap, text), refs


# CF-0673: the article's text is the root's one reading of it
# (`wikipedia_api.plain_text`): it unwraps `{{val}}` / `{{convert}}` into the
# number in the page's own unit - this function used to drop `{{val}}` and
# lose exactly the measured numbers a fact is made of. What stays this
# stage's own is what a *sentence* is: a list item, a heading or a stray table
# row is never one statement, and the paragraphs stay apart as they were.
# `{{'s}}` / `{{'}}` are the root's too: put down here as a bare `'` before
# `plain_text`, they met its `''italic''` stripping and «''Coach Hale''{{'s}}»
# came out «Ted Lassos».
_NOT_A_STATEMENT_RE = re.compile(r"^(?:- |[|!]|\{\||(={2,6}) .* \1$)")


def clean_wikitext(text):
    """Wikitext with the markup taken off - footnotes are expected to be
    masked already. The root's `wikipedia_api.plain_text`, minus the lines
    that are never a statement (a list item, a heading, a table row), one
    paragraph per line pair as the article has them."""
    lines = [line for line in plain_text(text).splitlines()
             if line.strip() and not _NOT_A_STATEMENT_RE.match(line.strip())]
    return re.sub(r"[ \t]+", " ", "\n\n".join(lines)).strip()


# ============================================================ sections
class Section(object):
    def __init__(self, heading, level, text):
        self.heading = heading
        self.level = level
        self.text = text

    def __repr__(self):                                   # pragma: no cover
        return f"<Section {self.heading!r} level={self.level}>"


def split_sections(wikitext):
    """Every `== heading ==` of an article with the text under it (the lead
    comes back as the heading `""`, level 0)."""
    sections = []
    matches = list(HEADING_RE.finditer(wikitext))
    lead_end = matches[0].start() if matches else len(wikitext)
    sections.append(Section("", 0, wikitext[:lead_end]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(wikitext)
        sections.append(Section(match.group(2), len(match.group(1)),
                                wikitext[match.end():end]))
    return sections


def production_sections(sections):
    """The sections of the production tree, minus the subsections that are
    about something else (Casting, Release, Reception...).

    A tree is opened by a heading like `Production` or `Filming` and holds
    every deeper heading under it until the next heading of the same level.
    """
    chosen, tree_level, excluded_level = [], None, None
    for section in sections:
        if section.level == 0:
            continue
        if excluded_level is not None and section.level > excluded_level:
            continue
        excluded_level = None
        if tree_level is not None and section.level <= tree_level:
            tree_level = None
        inside = tree_level is not None
        if PRODUCTION_HEADING_RE.match(section.heading) and not inside:
            tree_level = section.level
            inside = True
        if not inside:
            continue
        if EXCLUDED_HEADING_RE.match(section.heading):
            excluded_level = section.level
            continue
        chosen.append(section)
    return chosen


def has_production_section(article):
    """Does the article have a Production tree? Since CF-0439 this is no
    longer what an article is accepted by (`has_fact_section` is): a fact of
    any kind is the channel's, and an article with no Production heading
    still has its Release, its Box office, its Controversy."""
    return bool(production_sections(split_sections(article.get("wikitext", ""))))


def kind_of_heading(*headings):
    """The fact kind a section's heading names (its own, then its level-2
    parent's), `other` when none does."""
    for heading in headings:
        for kind, pattern in HEADING_KINDS:
            if pattern.search(heading or ""):
                return kind
    return KIND_OTHER


def fact_sections(sections):
    """CF-0439: every section a fact of any kind can be read out of, each with
    the `kind` its heading names: the lead and every prose section, minus the
    story, the cast and episode lists and the apparatus (`SKIP_HEADING_RE`),
    with their subsections. Tables and lists inside a section are dropped by
    `clean_wikitext` line by line."""
    chosen, skip_level, top = [], None, LEAD_HEADING
    for section in sections:
        if section.level == 0:
            section.kind = KIND_OTHER
            chosen.append(section)
            continue
        if skip_level is not None and section.level > skip_level:
            continue
        skip_level = None
        if section.level <= 2:
            top = section.heading
        if SKIP_HEADING_RE.search(section.heading):
            skip_level = section.level
            continue
        section.kind = kind_of_heading(section.heading,
                                       top if section.level > 2 else None)
        chosen.append(section)
    return chosen


def readable_sections(sections):
    """`fact_sections` without the lead - what an article has to have to be
    worth reading for a fact (a lead alone is a stub)."""
    return [section for section in fact_sections(sections) if section.level > 0]


def has_fact_section(article):
    """The `accept` the article resolver asks (CF-0439): does this article
    have a section a fact of any kind can come out of? Not whether it has a
    Production tree - that is no longer what the channel came for."""
    return bool(readable_sections(split_sections(article.get("wikitext", ""))))


# ============================================================ sentences
def split_sentences(text):
    """Sentences, with their footnote markers kept on the sentence they
    belong to - the marker sits *after* the full stop in wikitext."""
    pieces, start = [], 0
    # The closing punctuation of a quoted sentence can be three characters
    # deep - `... in this house?'"` - and a sentence cut inside a quotation
    # comes back as a fragment glued to the next statement.
    pattern = re.compile(r"[.!?][\"'\u2019\u201d)\]]{0,3}"
                         + f"(?:{MARK_OPEN}\\d+{MARK_CLOSE})*" + r"\s+")
    for match in pattern.finditer(text):
        if _is_abbreviation(text, match.start()):
            continue
        pieces.append(text[start:match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return [piece for piece in pieces if piece]


def _is_abbreviation(text, dot_index):
    """`Mr. Smith` and `J. J. Abrams` are not two sentences."""
    before = text[:dot_index + 1]
    word = re.search(r"([A-Za-z.]+)\.$", before)
    if not word:
        return False
    token = word.group(1).rstrip(".").lower()
    return token in ABBREVIATIONS or len(token) == 1


def sentence_refs(sentence, refs):
    """The footnotes marked on this sentence, in order."""
    return [refs[int(index)] for index in MARK_RE.findall(sentence)
            if int(index) < len(refs)]


def strip_marks(sentence):
    # A template dropped at the head of a sentence ("{{As of|2026}}, the
    # film has grossed...") leaves its comma behind.
    return re.sub(r"\s+([,.;:])", r"\1",
                  re.sub(r"\s{2,}", " ", MARK_RE.sub("", sentence))
                  ).strip().lstrip(",;: ")


# ============================================================ the rule
def proper_names(sentence):
    names = []
    for match in NAME_RE.finditer(sentence):
        name = match.group(0)
        if match.start() == 0 and " " not in name:
            continue                                   # the first word
        if name.lower() in NAME_STOPWORDS:
            continue
        if name.split()[0].lower() in NAME_STOPWORDS and " " not in name:
            continue
        names.append(name)
    return names


def sentence_kind(sentence, section_kind="production"):
    """The kind of fact a sentence is (CF-0439). A section that names a kind
    other than production (`Box office`, `Release`, `Controversy`) gives it
    to every sentence in it; in the Production tree, the lead and a section
    that names none, the sentence's own words decide (`KIND_SIGNALS`) and the
    section's kind stands when they say nothing."""
    if section_kind not in ("production", KIND_OTHER, None):
        return section_kind
    for kind, pattern in KIND_SIGNALS:
        if pattern.search(sentence):
            return kind
    return section_kind or KIND_OTHER


def _schedule_only(sentence):
    """A date and a verb and nothing else: "Principal photography began in
    December 2025", "The film was released on 5 May 2023"."""
    if not (SCHEDULE_VERB_RE.search(sentence) and DATE_RE.search(sentence)):
        return False
    if SCHEDULE_DETAIL_RE.search(sentence):
        return False
    # A number that is not the date - `$12 million`, `3,000 screens`,
    # `12 million viewers` - is the fact the date came with.
    return not re.search(r"\$|\d", DATE_NUMBER_RE.sub("", sentence))


def judge(sentence, refs, kind="production"):
    """Why this sentence is not a fact, or None when it is one.

    `kind` is the sentence's (`sentence_kind`). Returned as a reason code so a
    title that yields nothing can be read: `no_citation`, `too_short`,
    `too_long`, `announcement`, `schedule_only`, `list`, `not_craft` (a
    production sentence about nothing that was made), `not_concrete`.
    """
    if not refs:
        return "no_citation"
    if len(sentence) < MIN_CHARS:
        return "too_short"
    if len(sentence) > MAX_CHARS:
        return "too_long"
    for reason, pattern in REJECTIONS:
        if pattern.search(sentence):
            return reason
    if _schedule_only(sentence):
        return "schedule_only"
    if sentence.count(",") > LIST_COMMA_CEILING and not STRONG_RE.search(sentence):
        return "list"
    if kind == "production" and not CRAFT_RE.search(sentence):
        return "not_craft"
    if not (NUMBER_RE.search(sentence) or proper_names(sentence)):
        return "not_concrete"
    return None


def judge_in_section(sentence, refs, section):
    """`(reason, kind)` for a sentence of one of `fact_sections`: the lead
    asks for a number and refuses a definition of the work (`definition`)."""
    kind = sentence_kind(sentence, getattr(section, "kind", "production"))
    if section.level == 0 and refs and len(sentence) >= MIN_CHARS:
        if DEFINITION_RE.search(sentence):
            return "definition", kind
        if not re.search(r"\d", sentence):
            return "not_concrete", kind
    return judge(sentence, refs, kind), kind


def score(sentence, refs, section_heading):
    """How much of a fact this is. Ranking only - everything scored has
    already passed `judge`."""
    points = 0.0
    if STRONG_RE.search(sentence):
        points += 4
    if UNIT_RE.search(sentence) or UNIT_WORD_RE.search(sentence):
        points += 2
    points += min(len(NUMBER_RE.findall(sentence)), 2)
    points += min(len(proper_names(sentence)), 2)
    if any(ref.get("url") for ref in refs):
        points += 1
    if len(sentence) <= 160:
        points += 1
    if not re.match(r"^development\b", section_heading or "", re.I):
        points += 1
    # CF-0439: a money figure is what makes a box-office sentence a fact.
    if re.search(r"\$\s?\d|\b\d[\d,.]*\s*(?:million|billion)\b", sentence):
        points += 2
    return points


def candidates_from_article(article, limit=DEFAULT_LIMIT, keep_rejected=False):
    """Every sentence of the article that could be the fact, of any kind
    (CF-0439), best first: the best of each kind lined up in `KIND_ORDER`,
    then the second of each, so one long Development section does not crowd
    out the one box-office number. `([], [...])` when nothing survives -
    which is a result, not a failure."""
    wikitext = article.get("wikitext", "")
    named = collect_named_refs(wikitext)
    found, rejected = [], []
    for section in fact_sections(split_sections(wikitext)):
        masked, refs = mask_refs(section.text, named)
        for raw in split_sentences(clean_wikitext(masked)):
            here = sentence_refs(raw, refs)
            sentence = strip_marks(raw)
            if not sentence:
                continue
            reason, kind = judge_in_section(sentence, here, section)
            if reason:
                if keep_rejected:
                    rejected.append({"text": sentence, "reason": reason,
                                     "kind": kind, "section": section.heading})
                continue
            urls = [ref["url"] for ref in here if ref.get("url")]
            found.append({
                "text": sentence,
                "kind": kind,
                "source_url": (anchored(article["url"], section.heading)
                               if section.level else article["url"]),
                "citation_url": urls[0] if urls else None,
                "citation_urls": urls,
                # CF-0241: the two documents this sentence could be proved on
                # screen with - the section it was read from, and the sources
                # its footnotes name - each with the publication, the title
                # and the date a proof has to show beside the URL.
                "source_document": document_of(article, section.heading or None),
                "citation_documents": [ref["citation"] for ref in here
                                       if (ref.get("citation") or {}).get("url")],
                "article_title": article["title"],
                "article_url": article["url"],
                "section": section.heading,
                "score": score(sentence, here, section.heading),
                "fits_on_screen": len(sentence) <= ON_SCREEN_BUDGET,
                "signals": {
                    "numbers": NUMBER_RE.findall(sentence)[:4],
                    "names": proper_names(sentence)[:4],
                    "craft": sorted({m.group(0).lower()
                                     for m in CRAFT_RE.finditer(sentence)})[:4],
                },
            })
    seen, unique = set(), []
    for candidate in sorted(found, key=lambda c: -c["score"]):
        if candidate["text"] in seen:
            continue
        seen.add(candidate["text"])
        unique.append(candidate)
    # Already best-first within a kind; the n-th of every kind goes before
    # the (n+1)-th of any, kinds in `KIND_ORDER`.
    order = {kind: index for index, kind in enumerate(KIND_ORDER)}
    taken, rank = {}, {}
    for candidate in unique:
        taken[candidate["kind"]] = taken.get(candidate["kind"], -1) + 1
        rank[id(candidate)] = taken[candidate["kind"]]
    unique.sort(key=lambda c: (rank[id(c)], order.get(c["kind"], len(order))))
    return unique[:limit], rejected


# ============================================================ the entry point
def parent_title(name, parent=None):
    """The parent work this topic names, or None.

    Two ways, and no third. `parent` is the caller saying "the topic's own
    news name this franchise" - Trend Hunter reads the news, this module does
    not - and it is taken at its word. Failing that, the topic's own title is
    read: everything before the first `Rennick: Quill`-style separator, when
    what is left on either side is a name rather than a fragment.

    Never a search for something similar. `Quill` resolving to a series
    called Quill is the lookup doing its job; `Rennick: Quill` borrowing a
    fact from `Rennick (TV series)` is a lead-in the writer has to make
    honest, and it is only honest because the topic said the word `Rennick`.
    """
    if parent and str(parent).strip():
        named = str(parent).strip()
        return named if named.lower() != (name or "").strip().lower() else None
    text = (name or "").strip()
    for separator in PARENT_SEPARATORS:
        if separator in text:
            head, tail = (part.strip() for part in text.split(separator, 1))
            if len(head) >= MIN_PARENT_CHARS and tail:
                return head
    return None


def _lookup(name, year, season, client, limit, keep_rejected,
            work_type, network, subject=None):
    """One title's lookup - the whole of CF-0184's flow plus CF-0263's check
    that the article the search resolved to is about the work we asked about,
    and CF-0812's that it is about the edition the topic's news is about
    (`subject`: `edition_check.subject_of`, the topic's own text - for the
    parent hop too, whose `year` is None but whose topic is still this one)."""
    if subject is None:
        subject = edition_check.subject_of(name, year, season)
    result = {"query": {"name": name, "year": year, "season": season,
                        "type": work_type, "network": network, "parent": None},
              "article": None, "article_check": None, "parent_work": None,
              "sections": [], "candidates": [], "rejected": [],
              "status": STATUS_NO_ARTICLE, "requests": 0}

    # CF-0439: an article is accepted for being about this work and having a
    # section a fact can come out of - not for having a Production tree.
    def edition(article):
        return edition_check.other_edition(article.get("title"), article.get("wikitext"),
                                           subject, plain_text=plain_text)

    def fits(article):
        return (matches_topic(article, work_type, year, network)
                and edition(article) is None)

    def accept(article):
        return fits(article) and has_fact_section(article)

    def _checked(article):
        check = verify_article(article, work_type, year, network)
        if not check["mismatch"]:
            other = edition(article)
            if other is not None:
                check["mismatch"] = other["mismatch"]
                check["detail"] = other["detail"]
                check["edition"] = {k: other[k] for k in ("qualifier", "unnamed",
                                                         "newest_year", "now_year")}
        return check

    read = []
    skipped = []
    article = resolve_article(client, name, year=year, season=season,
                              accept=accept, work_type=work_type, seen=read,
                              skipped=skipped)
    result["requests"] = client.request_count
    if article is None:
        if skipped:
            result["sub_reason"] = NO_ARTICLE_REASON_DISAMBIGUATION
            result["skipped_articles"] = [page["title"] for page in skipped]
        return result
    check = _checked(article)
    if check["mismatch"]:
        # The resolver hands back the last article it read when nothing was
        # accepted, and that one may be the wrong work while an earlier read
        # was the right work with nothing to read. Report the emptiness of
        # the right article rather than the wrongness of the other one - the
        # two are different answers and only one of them is about this topic.
        # CF-0812: "the wrong work" includes another edition of it - the
        # first-generation Roadster for the new one, the 1999 Mummy for the
        # fourth - and so does "the right article".
        better = next((seen for seen in read if fits(seen)), None)
        if better is not None:
            article, check = better, _checked(better)
    result["article"] = {"title": article["title"], "url": article["url"],
                         "pageid": article.get("pageid"),
                         "revised_at": article.get("revised_at"),
                         "license": article.get("license")}
    result["article_check"] = check
    if check["mismatch"]:
        result["status"] = STATUS_WRONG_ARTICLE
        return result
    sections = readable_sections(split_sections(article.get("wikitext", "")))
    result["sections"] = [section.heading for section in sections]
    if not sections:
        result["status"] = STATUS_NO_SECTION
        return result
    found, rejected = candidates_from_article(article, limit=limit,
                                              keep_rejected=keep_rejected)
    result["candidates"] = found
    result["rejected"] = rejected
    result["status"] = STATUS_OK if found else STATUS_NO_CANDIDATES
    return result


def find_production_facts(name, year=None, season=None, client=None,
                          limit=DEFAULT_LIMIT, keep_rejected=False,
                          work_type=None, network=None, parent=None,
                          follow_parent=True, news=None, now_year=None):
    """Candidates for one title's fact, of any kind (CF-0439).

    Never raises for an empty result: `status` is `ok`, `no_article` (nothing
    on Wikipedia matches the title), `no_section` (an article with no section
    a fact can come out of - all plot and cast, CF-0439), `no_candidates`
    (sections with nothing in them that is a fact) or `wrong_article` (an article, but about something other than this
    topic), and `candidates` is `[]` for the last four. Only an unreachable
    API raises (`WikipediaError`).

    **What the topic is** (CF-0263) - `work_type` (`tv_series`, `film`),
    `year`, `network` - is what the article is held against. Passing none of
    it is legal and is CF-0184's behaviour for the kind: no type is verified.

    **Which edition** (CF-0812, `edition_check.py`) - an article titled with
    an edition (`(first generation)`, `(1999 film)`) is the topic's only when
    the topic's own text names it, or when it is current and the topic does
    not point elsewhere (its year, a sequel). Otherwise the resolver reads
    the next candidate, and when none fits the answer is `wrong_article`
    with `article_check.mismatch == "edition"` and the reason in `detail`.
    The topic's own text is the name, `year`, `season`, the parent it names
    and `news` - the caller's text of its news (headlines, summaries, scene
    descriptions; a string or a list). `now_year` is the year "current" is
    measured from (default: this year); a replay passes the batch's.

    **The parent work** - a topic with no article of its own that names a
    parent (`Rennick: Quill`) is looked up again under that parent, and the
    result carries `parent_work` with the parent article's title so the writer
    can say where the fact is from ("in the main series..."). One hop, never a
    chain: `follow_parent` is false inside the parent's own lookup, so a topic
    costs at most `MAX_REQUESTS_PER_TOPIC` (6) requests - two titles at the
    module's standing ceiling of three, with the standing one-second floor
    between every one of them.
    """
    client = client or WikipediaClient()
    named = parent_title(name, parent) if follow_parent else None
    subject = edition_check.subject_of(name, year, season, named, news=news,
                                       now_year=now_year)
    result = _lookup(name, year, season, client, limit, keep_rejected,
                     work_type, network, subject=subject)
    if result["status"] != STATUS_NO_ARTICLE or not follow_parent:
        return result
    if not named:
        return result
    result["query"]["parent"] = named
    # The parent is a different work: its year and its season are not the
    # spin-off's, so only the name and the kind carry over. The edition check
    # still reads the topic's own text and year (CF-0812): `Skyman: Man of
    # Tomorrow` (2027) borrowing from `Skyman (2025 film)` is a fact about
    # another film, not about the parent the topic names.
    up = _lookup(named, None, None, client, limit, keep_rejected,
                 work_type, network, subject=subject)
    if up["article"] is None:
        return result
    up["query"] = dict(result["query"])
    up["parent_work"] = up["article"]["title"]
    up["requests"] = client.request_count
    return up


def topics_of_batch(path):
    """`[{name, year, season, type, network, parent}]` out of a Trend Hunter
    batch file. The last three are CF-0263's and are optional: a batch written
    before them simply verifies nothing."""
    data = json.loads(Path(path).read_text())
    topics = []
    batch_topics = [t for t in data.get("topics", []) if isinstance(t, dict)]
    for topic in data.get("topics", []):
        ref = topic.get("title_ref") or {}
        if not ref.get("name"):
            continue
        topics.append({"topic_id": topic.get("topic_id"),
                       "name": ref["name"],
                       "year": ref.get("year"),
                       "season": ref.get("season"),
                       "type": ref.get("type"),
                       "network": ref.get("network") or ref.get("studio"),
                       "parent": ref.get("parent_work") or ref.get("parent"),
                       # CF-0812: the topic's own news, for the edition check.
                       "news": edition_check.news_of_topic(topic),
                       # CF-0438: what the hunter already found and how the
                       # rule judged it. None on a batch written before.
                       "fact_candidates": topic.get(CANDIDATES_FIELD),
                       "fact_rule": (topic.get("fact_probe") or {}).get("fact_rule")
                       if isinstance(topic.get("fact_probe"), dict) else None,
                       # CF-0548: the scenes the fact has to be about, and the
                       # batch's other topics (whose works are not this one's).
                       "scene_topic": topic,
                       "batch_topics": batch_topics})
    return topics


# ============================================================ CF-0438: take, don't search
# Trend Hunter searches every source of the batch's channel's fact-source list
# (`channels/<id>/fact-sources.json`, CF-0561/CF-0627) at selection, checks
# each candidate against the fact rule's four requirements and writes them,
# best first with their verdicts, into `01-trend-hunter.json` ->
# `topics[].fact_candidates`. Step 2 takes the best passing one from there;
# Wikipedia is asked again only for a topic the hunter never settled - a batch
# written before CF-0438 (no `fact_candidates` at all) or a decision that says
# re-ask (`fact_probe.fact_rule.settled == false`: the source did not answer).
CANDIDATES_FIELD = "fact_candidates"
TAKEN_FROM = "01-trend-hunter.json topics[].fact_candidates"
WIKIPEDIA_SOURCE = "Wikipedia"
WIKIPEDIA_KIND = "production"


SCENES_KEY = "scenes"        # fact_scene.SCENES_KEY, CF-0548
FIT_KEY = "scene_fit"        # fact_scene.FIT_KEY


def _fact_scene():
    from _factrule import fact_scene
    return fact_scene()


def _fact_rule():
    """The shared rule, loaded on first use: a `--title` lookup needs none of
    it, and the module stays importable where the root is not."""
    from _factrule import fact_rule
    return fact_rule


def takes_from_batch(topic):
    """True when the hunter's candidates answer this topic and nothing is to
    be asked again: the batch carries `fact_candidates` for it and the rule's
    decision is settled (`fact_rule.re_ask()` is False)."""
    if not isinstance(topic.get("fact_candidates"), list):
        return False
    return not _fact_rule().re_ask(topic.get("fact_rule"))


def _taken_candidate(candidate, fact_rule):
    """One of the hunter's passing candidates in the shape the rest of this
    stage reads a lookup candidate in (`source_url`, `citation_url`,
    `fits_on_screen`), plus `fact` - the record that goes into 03 as is."""
    fact = fact_rule.fact_record(candidate)
    primary = candidate.get("primary_url") or None
    return {"text": candidate.get("text"),
            "kind": fact.get("kind"),
            "source": candidate.get("source"),
            "source_url": candidate.get("url"),
            "citation_url": primary,
            "citation_urls": [primary] if primary else [],
            "section": candidate.get("section"),
            "attribution": candidate.get("attribution"),
            "quote": candidate.get("quote"),
            "source_type": candidate.get("source_type"),
            "score": None,
            "fits_on_screen": len(candidate.get("text") or "") <= ON_SCREEN_BUDGET,
            "check": candidate.get(fact_rule.CHECK_KEY),
            # CF-0548: the scenes of the topic this fact is about - pick the
            # scene out of these, never a fact for a scene it does not fit.
            "scenes": candidate.get(SCENES_KEY),
            "fact": fact}


def result_from_batch(topic):
    """A lookup result built out of the hunter's candidates, no request made.

    `candidates` holds only the ones that pass the rule, the best first
    (`fact_rule.best_candidate`), so `fact_refusal.py` reads the result exactly
    as it reads a Wikipedia answer: some -> found, none -> `no_candidates`.
    `fact` is `fact_rule.fact_record(best)` - what the script's `fact` field
    carries into 03 - and None when nothing passed. The ones that failed are
    under `rejected`, with the rule's own failure codes."""
    fact_rule = _fact_rule()
    listed = [c for c in topic.get("fact_candidates") or [] if isinstance(c, dict)]
    best = fact_rule.best_candidate(listed)
    passing = [c for c in listed
               if (c.get(fact_rule.CHECK_KEY) or {}).get("passes") and c is not best]
    ordered = ([best] if best else []) + passing
    # CF-0548: a candidate that fits no scene of the topic - another segment of
    # the same broadcast, another topic's work - is not this topic's fact. It
    # leaves the offer for `rejected`, and the next one is taken; none left is
    # `no_candidates` with `off_scene_only`, which fact_refusal.py refuses as
    # no_fact even on a settled topic (the same data, judged once more fully).
    off_scene = []
    scene_topic = topic.get("scene_topic")
    if isinstance(scene_topic, dict) and scene_topic.get("scenes"):
        fs = _fact_scene()
        annotated = fs.annotate(ordered, scene_topic, topic.get("batch_topics"))
        ordered = [c for c in annotated if c.get(SCENES_KEY)]
        off_scene = [c for c in annotated if not c.get(SCENES_KEY)]
        best = ordered[0] if ordered else None
    return {"topic_id": topic.get("topic_id"),
            "query": {"name": topic.get("name"), "year": topic.get("year"),
                      "season": topic.get("season"), "type": topic.get("type"),
                      "network": topic.get("network"), "parent": topic.get("parent")},
            "status": STATUS_OK if best else STATUS_NO_CANDIDATES,
            "article": None,
            "candidates": [_taken_candidate(c, fact_rule) for c in ordered],
            "rejected": [{"text": c.get("text"), "kind": c.get("kind"),
                          "source": c.get("source"), "url": c.get("url"),
                          "reason": ",".join((c.get(fact_rule.CHECK_KEY) or {})
                                             .get("failures") or []) or "not_passing"}
                         for c in listed
                         if not (c.get(fact_rule.CHECK_KEY) or {}).get("passes")]
                        + [{"text": c.get("text"), "kind": c.get("kind"),
                            "source": c.get("source"), "url": c.get("url"),
                            "reason": "off_scene:" + ",".join(_fact_scene().failure_summary(c)),
                            "scene_fit": c.get(FIT_KEY)}
                           for c in off_scene],
            "off_scene": len(off_scene),
            "off_scene_only": bool(off_scene) and best is None,
            "requests": 0,
            "taken_from": TAKEN_FROM,
            "fact_rule": topic.get("fact_rule"),
            "fact": fact_rule.fact_record(best)}


def with_fact_records(result):
    """A Wikipedia lookup's result with `fact` on every candidate and on the
    result (the first candidate's): the same record the hunter's candidates
    carry, so the writer copies one field whichever way the fact came. The
    kind is the candidate's own (CF-0439), `production` for a result written
    before candidates carried one."""
    fact_rule = _fact_rule()
    for candidate in result.get("candidates") or []:
        candidate.setdefault("fact", fact_rule.fact_record({
            "text": candidate.get("text"),
            "kind": candidate.get("kind") or WIKIPEDIA_KIND,
            "source": WIKIPEDIA_SOURCE, "url": candidate.get("source_url"),
            "primary_url": candidate.get("citation_url"),
            "section": candidate.get("section")}))
    first = (result.get("candidates") or [None])[0]
    result["fact"] = first.get("fact") if first else None
    return result


# ============================================================ the CLI
def print_result(result, out=print, show_rejected=False):
    query = result["query"]
    head = query["name"] + (f" ({query['year']})" if query.get("year") else "")
    article = result["article"]
    where = article["title"] if article else "-"
    if result.get("parent_work"):
        where += f" (parent of {query['name']})"
    if result.get("taken_from"):
        where = f"taken from {result['taken_from']}"
    out(f"{head}: {result['status']} [{where}] "
        f"{len(result['candidates'])} candidate(s), {result['requests']} request(s)")
    check = result.get("article_check") or {}
    if check.get("detail"):
        out(f"      wrong article: {check['detail']}")
    for candidate in result["candidates"]:
        fits = "fits" if candidate["fits_on_screen"] else "needs on_screen"
        rank = (f"{candidate['score']:.0f}" if candidate.get("score") is not None
                else (candidate.get("fact") or {}).get("kind", "?"))
        out(f"  [{rank}] {candidate['text']}")
        out(f"      source_url: {candidate['source_url']}")
        out(f"      citation:   {candidate['citation_url'] or '-'} ({fits})")
        if candidate.get("scenes") is not None:
            out(f"      scenes:     {', '.join(candidate['scenes'])}")
    if result.get("off_scene"):
        # CF-0548: said always, not only with --show-rejected - a fact that was
        # the best of its topic and is not about any of its scenes is the
        # finding (WNL 0701Z: the cold open under the monologue).
        out(f"  OFF SCENE {result['off_scene']} candidate(s) are about no scene of this "
            f"topic (CF-0548) - not offered"
            + ("; none is left: the topic leaves as no_fact" if result.get("off_scene_only") else ""))
        for item in result.get("rejected") or []:
            if str(item.get("reason", "")).startswith("off_scene:"):
                out(f"  - {item['reason']}: {item['text'][:110]}")
    if show_rejected:
        for item in result.get("rejected") or []:
            if not str(item.get("reason", "")).startswith("off_scene:"):
                out(f"  - {item['reason']}: {item['text'][:110]}")


def record_fixtures(directory, client=None):            # pragma: no cover
    """Re-record the test fixtures from the live API (see the README beside
    them). Not used by the test suite - the suite never goes out."""
    import wikipedia_api as wapi
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    plan = [
        ("search-bunker.json", wapi.SEARCH_PATH,
         {"q": "Bunker 2026", "limit": wapi.SEARCH_LIMIT}),
        ("search-everyday-sorcery-2.json", wapi.SEARCH_PATH,
         {"q": "Everyday Sorcery 2", "limit": wapi.SEARCH_LIMIT}),
        ("search-no-hits.json", wapi.SEARCH_PATH,
         {"q": "Cf0184 No Such Article Qwerty Zzz", "limit": wapi.SEARCH_LIMIT}),
        ("page-bunker-2026-film.json", wapi.page_path("Bunker (2026 film)"), None),
        ("page-everyday-sorcery-2.json", wapi.page_path("Everyday Sorcery 2"), None),
        ("page-missing-title.json",
         wapi.page_path("Cf0184 No Such Article Qwerty"), None),
        ("page-redirect.json", wapi.page_path("Sopranos"), None),
    ]
    client = client or WikipediaClient()
    for name, path, params in plan:
        response = client.fetch(path, params)
        payload = json.loads(response.body)
        (target / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print(f"recorded {name} (HTTP {response.status})")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Candidates for a script's fact of any kind, from every "
                    "prose section of the Wikipedia article (CF-0184, CF-0439).")
    parser.add_argument("--title", help="the title, as in title_ref.name")
    parser.add_argument("--year", help="release year, when the batch knows one")
    parser.add_argument("--season", help="season, for a series")
    parser.add_argument("--type", dest="work_type",
                        help="what the topic is: tv_series, film (CF-0263) - "
                             "the resolved article is held against it")
    parser.add_argument("--network", help="network or studio, when known "
                                          "(reported, never a refusal)")
    parser.add_argument("--parent", help="the parent work the topic names, "
                                         "when the caller read it out of the news")
    parser.add_argument("--news", help="the topic's own news text (headline, "
                                       "summary) - an article about another edition "
                                       "than the one it names is refused (CF-0812)")
    parser.add_argument("--no-parent", dest="follow_parent",
                        action="store_false",
                        help="do not fall back to the parent work named in the title")
    parser.add_argument("--from-batch", dest="batch",
                        help="a 01-trend-hunter.json - every topic in it")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true", help="the whole result")
    parser.add_argument("--show-rejected", action="store_true",
                        help="what was thrown away and why")
    parser.add_argument("--record-fixtures", metavar="DIR",
                        help="re-record the test fixtures from the live API")
    return parser


def main(argv=None, client=None):
    """`client` is the test seam: the suite must never touch the network."""
    args = build_parser().parse_args(argv)
    if args.record_fixtures:                            # pragma: no cover
        record_fixtures(args.record_fixtures)
        return 0
    if not args.title and not args.batch:
        build_parser().print_usage()
        print("give --title or --from-batch", file=sys.stderr)
        return 2
    if args.batch:
        wanted = topics_of_batch(args.batch)
    else:
        wanted = [{"topic_id": None, "name": args.title,
                   "year": args.year, "season": args.season,
                   "type": args.work_type, "network": args.network,
                   "parent": args.parent, "news": args.news}]
    client = client or WikipediaClient()
    results = []
    try:
        for topic in wanted:
            # CF-0438: the hunter's settled candidates are taken as they are;
            # only an old batch or an unsettled topic is asked again.
            if args.batch and takes_from_batch(topic):
                results.append(result_from_batch(topic))
                continue
            result = find_production_facts(
                topic["name"], year=topic.get("year"), season=topic.get("season"),
                client=client, limit=args.limit,
                keep_rejected=args.show_rejected,
                work_type=topic.get("type"), network=topic.get("network"),
                parent=topic.get("parent"), follow_parent=args.follow_parent,
                news=topic.get("news"))
            if topic.get("topic_id"):
                result["topic_id"] = topic["topic_id"]
            results.append(with_fact_records(result))
    except WikipediaError as error:
        # Unreachable is not empty: say so loudly rather than hand back a
        # silence that CF-0185 would read as "this title has no fact".
        print(f"wikipedia unavailable: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for result in results:
            print_result(result, show_rejected=args.show_rejected)
    return 0


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
