#!/usr/bin/env python3
"""CF-0865: the second step of `already_published` - after the writer has
picked the fact (step 2), before steps 3-6 spend anything.

Why a second step. The first one is the Trend Hunter's, at selection
(`agents/trend-hunter/scripts/published_before.py`): a topic whose news shares
an article with a video the channel already made leaves as
`already_published`; a topic about the same work with other news stays and
carries `published_before: [{relation: same_work, story: different, ...}]`.
The news a topic is found by is not what its video ends up saying, though.
`example-tech/2026-10-25T0834Z`, topic `lf-2026-10-25-003` (ChatGPT): other
articles than the ChatGPT video of 16.10 (published 19.10), so kept and
marked - and then the writer took "In July 2026, ChatGPT apps were renamed to
plugins", the very sentence that closed the 16.10 commentary, and retold that
commentary around it (plugins in March 2023, web browsing and code
interpretation, Expedia, OpenTable and Zapier). The user refused it as a
repeat (`repeated_work`); nothing in the factory looked.

What is compared. A topic of this batch with a `published_before[]` mark of
`relation: same_work` is held against every video of that work the channel
**accepted before this batch started** - the videos the mark names (by
`entry_id`, or by the batch and slug of a mark written before CF-0865) and
every other accepted video of the same channel and slug. "Before this batch
started" is the row's `recorded_at` (its `answered_at` day when there is no
time) earlier than the batch id's own time, and the video's batch earlier
than this one: the videos accepted from batches running alongside are not a
past the writer could have known, and on 25.10 two accepted ChatGPT videos
(24T1528Z and 25T0934Z) share hook articles - compared with each other they
would refuse each other. A rejected video is not "made": the latest row of
each `entry_id` in `publish/acceptance-log.json` is that video's verdict.

What the published video is: its row (`publish_path`, `profile.fact_text`,
`profile.fact_source.url`) and its script in its batch's
`03-content-researcher.json` (`profile.script_id`, else the row's
`topic_id`): `fact`, `production_fact`, `claims[]` (text and source quotes),
hook, commentary, payoff.

A repeat is any one of three:

  * **the same source** - the fact's `url`, `primary_url` or
    `production_fact.source_url` is one of the published video's (scheme,
    `www.`, a trailing slash and the query ignored). A page of a reference
    work (`REFERENCE_HOSTS`: Wikipedia, Wikidata, IMDb, Fandom, Britannica)
    does not count: one section of it holds many facts - measured below, the
    same Wikipedia section stood behind three pairs of different videos;
  * **the same fact** - the fact (`fact.text`, `production_fact.text`) is a
    statement the published video already made: one sentence of the
    published hook/commentary/payoff, its fact, or a `claims[]` text or
    source quote carries at least `FACT_SHARE` (0.7) of the fact's content
    words and at least `FACT_BIGRAM_SHARE` (0.4) of its pairs of neighbouring
    content words (the words alone match "July 2026 ... ChatGPT ... apps" in
    an unrelated sentence), the fact having at least `FACT_MIN_WORDS` (4)
    content words; **or the other way round** (CF-0871) - one of those
    published statements, of at least `CONTAINED_MIN_WORDS` (6) content
    words, lies almost whole inside the longer fact: at least
    `CONTAINED_SHARE` (0.85) of its content words are the fact's, at least
    `CONTAINED_PAIR_SHARE` (0.45) of its pairs of neighbouring content words
    stand within `CONTAINED_PAIR_WINDOW` (3) content words of each other in
    the fact (either order - a longer sentence inserts words and moves
    clauses), and every number of two digits or more it names is in the fact
    ("July 2024" is not "July 2022");
  * **the same text** - hook + commentary + payoff of the two scripts share at
    least `SHARED_6GRAMS` (24) word 6-grams.

Text is compared normalised: lower case, punctuation off, and every number
the voice spells out read back as digits ("twenty twenty three" -> 2023,
"nine hundred million" -> 900000000) - the scripts are written for the
voice, the facts and quotes are not, and 0834Z's "plugins in March 2023" is
16.10's "March twenty twenty three". Punctuation ends a spoken number
(CF-0871): "July twenty twenty-two, two new films" is 2022 and 2 - it read
20222 before, and the Doomsday claim below lost its year.

The thresholds, measured 2026-10-26 on the live `publish/acceptance-log.json`
(84 rows, 61 accepted videos, 56 of their scripts found in their `03`): every
ordered pair of accepted videos of one channel and one work (title or slug),
the earlier one as the published side, plus the refused 0834Z.

  ==============================================  =======  ===========  ====
  pair (published -> later)                       6-grams  fact words/  url
                                                           pairs
  ==============================================  =======  ===========  ====
  chatgpt 16T0839Z -> 25T0834Z (refused, repeat)        3   1.00/1.00   -
  vanguards-doomsday 08T1824Z -> 13T1411Z               13   1.00/1.00   THR
  day-drinker 30T1248Z -> 30T2210Z                      7   1.00/1.00   THR
  american-dread-story 23T1722Z -> 01T0200Z            0   0.75/0.50   wiki
  chatgpt 24T1528Z -> 25T0834Z                          0   0.67/0.20   -
  chatgpt 25T0834Z -> 25T0934Z (never compared)        18      -        -
  chatgpt 24T1528Z -> 25T0934Z                          0   0.38/0.14   -
  every other pair (chatgpt, anthropic x3, AHS,       0-1  <=0.27/0.14  wiki
    YCSE x3, Endgame, Harbourlights)
  ==============================================  =======  ===========  ====

* The text test alone does not find the repeat: 16.10/0834Z share 3
  6-grams, while 0834Z/0934Z - two different ChatGPT videos with common hook
  articles - share 18. N = `SHARED_6GRAMS` = 24 sits above every pair
  measured: it is the net for a retelling in the old words around a new
  fact, not the first test.
* The fact test is what catches 0834Z: its fact is the last sentence of the
  16.10 commentary (1.00/1.00, after "July twenty twenty six" is read back
  as "July 2026"). The words alone do not separate: 0834Z's fact has 0.67 of
  its words in 24T1528Z's "In July 2026, OpenAI launched ChatGPT Work ...
  connected apps", while AHS 01T0200Z, retelling 23T1722Z's "shot in Los
  Angeles, principal photography July 14, 2015" in other words, has 0.75.
  The pairs do: 0.20 against 0.50. Both thresholds sit in the gaps (words
  0.7 between 0.67 and 0.75, pairs 0.4 between 0.20 and 0.50).
* Three of the four "same fact" pairs were accepted by the user before this
  rule existed (Doomsday 13T1411Z, Day Drinker 30T2210Z, AHS 01T0200Z took
  an earlier accepted video's very fact). By the rule they are repeats - the
  video's own contribution is one it already made; a finding for the driver,
  not a reason to blind the rule.
* The URL test, with Wikipedia counted, fired on AHS #Filming, Endgame
  #Production and Anthropic #History - different facts of one section;
  hence `REFERENCE_HOSTS`. Off Wikipedia it fires only on Doomsday and Day
  Drinker (the same THR article), which the fact test catches anyway.

The other way round (CF-0871), measured 2026-10-26 on the same log (90 rows,
63 accepted videos): `example-film/2026-10-26T1514Z` took Wikipedia's "At San
Diego Comic-Con (SDCC) in July 2022, Zenith Studios president Kevin Feige
announced the films Vanguards: The Kang Dynasty and Vanguards: Secret Wars, to
be released on May 2, 2025, and November 7, 2025, respectively." - the claim
c1 of the Doomsday video 13T1411Z (published 19.10), "In July twenty
twenty-two, two new Vanguards films were announced: The Kang Dynasty and
Secret Wars", with SDCC, Feige and two release dates around it. The driver
refused it (`repeated_work`); the check above passed it: the fact has 25
content words, the best published sentence holds 0.40 of them and 0.12 of
its pairs (the quote "Two new Vanguards films ... were announced in July
2022"), 0 shared 6-grams, the URL a Wikipedia section. Measured the other
way - the share of the *published* sentence inside the fact - over every
ordered pair of one channel (1184, the same work or not, the later video's
fact against every sentence, fact, claim and quote of the earlier one with
at least 6 content words):

  ==============================================  =====  =====  =======  =====
  pair (published -> later)                       words  pairs  strict   2+dig.
                                                         (<=3)  pairs    nums
  ==============================================  =====  =====  =======  =====
  doomsday 13T1411Z -> 26T1514Z (refused, repeat)  0.91   0.70    0.30   in
  doomsday 13T1411Z -> 24T0840Z (refused, other)   0.91   0.70    0.30   in
  4 repeats the check above already finds          0.75+  0.57+   0.57+  in
  RT score sentences, different works (x3)        <=0.77  <=0.58   -     not in
  YCSE 23T1722Z -> 01T0200Z (same work, other)     0.52   0.29    0.19   in
  chatgpt 24T1528Z -> 25T0834Z (same work, other)  0.50   0.20    0.20   in
  doomsday 08T1824Z -> 26T1514Z (Comic-Con 2024)   0.43   0.17    0.17   not in
  every other pair                                <=0.53  <=0.20   -      -
  ==============================================  =====  =====  =======  =====

* Words: 0.85 sits between 0.77 (a Rotten Tomatoes sentence of another
  work - another score, another count; production never compares different
  works, but one work's two seasons would read the same) and 0.91; for one
  work, between 0.52 and 0.91.
* Pairs: strict neighbours do not survive the longer sentence - "the films
  Vanguards: The Kang Dynasty and Vanguards: Secret Wars" splits every pair of
  "Vanguards films, The Kang Dynasty and Secret Wars" but two, and "announced
  in July 2022" moved to the front: 0.30 against 0.20 for another ChatGPT
  fact. Neighbours of the published sentence within 3 content words in the
  fact, either order: 0.70 against 0.29 (one work) and 0.58 (another work);
  0.45 sits in the gap.
* Numbers: the RT sentences of other works carry other scores (81%, 92%,
  100%) and the 08T1824Z sentence "the Comic-Con announcement in July 2024";
  a sentence naming a year or count the fact does not name is another fact
  even at 0.91 of its words ("... were announced in July 2024" against the
  2022 fact). One digit is left out: "two new films" is a count the fact
  need not repeat.
* `CONTAINED_MIN_WORDS` (6): "It did not start as Doomsday" (13T1411Z's
  claim c2) has 2 content words and lies in many Doomsday facts; under six
  one word moves the share by 0.2. The repeated sentence has 10 and 11.
* With all four, the test fires on 2 of the 1184 pairs - 13T1411Z ->
  26T1514Z and 13T1411Z -> 24T0840Z (refused for its footage; the same
  fact again) - and on nothing else: no cross-work pair, no other pair of
  one work. A different fact of the same franchise passes (the user's
  rule: a franchise on hype is not limited; a repeat is the same fact).

CF-0928: a gone batch, and the repeats the user refused. Rink Rivals,
accepted 09.10 (`example-film/2026-10-09T1208Z`, rebuilt in
`pipeline/rebuilds/2026-10-09T1208Z`), published 13.10: the Example Max deal of
19.11.2025. The channel's batch dir is gone, so Trend Hunter marks every later
Rink Rivals topic `relation: same_work_unverified, story: unknown`
(`published_before.py` UNVERIFIED), and this check compared `same_work` only:
the same fact was built again 25.10 (1024T0840Z), 09.11 (0839Z, 1511Z), and
the user refused each as `repeated_work`. Now:

  * a `same_work_unverified` mark is compared like `same_work`;
  * the published video is read from what is left of it: its batch's 03, else
    the 03 of the batch its row was read from (`profile.read_from`, a rebuild
    under `pipeline/`), else its publish card - `publish/<channel>/<day>/
    <slug>.md` in the tree, or, a month moved to Archive (CF-0476), the
    same `<day>/<slug>.md` inside `<VOLUMES_DIR>/<publish_path's zip>`: the
    description's fact, every «quote» of `## Утверждения` (voice, caption,
    title, description and their source quotes) and the fact's URL - and
    always its row (`profile.fact_text`, `profile.fact_source.url`);
  * a video of the same work the user refused as `repeated_work` (latest
    verdict, before this batch started, its batch earlier) is held like an
    accepted one - its fact, claims and text in its own 03: the fact it was
    refused for is not taken again. A video refused for anything else is not
    "made" and refuses nothing. The accepted videos are compared first, so
    `published_video` names a published one when there is one.

Replayed on the live tree 2026-11-10: 0839Z `lf-2026-11-09-003` and 1511Z
`lf-2026-11-09-002` leave (the same fact and the same Variety article as the
13.10 video); 1110T0832Z `lf-2026-11-10-008` (No. 2 on Example Max's US top 10
by FlixPatrol) is held against five videos and stays. Over the last 40
batches one more video newly reads as a repeat: delver 1030T1033Z (accepted
30.10) - its fact holds the CinemaScore "C+" sentence the delver video of
1009T1208Z said, which the check could not read before (that batch's 03 is
only in `rebuilds/`).

Usage

At step 2, per topic (no script yet - the text test has nothing to read).
A repeated fact is the fact's fault, not the topic's (the driver's decision
of 2026-10-26: the factory's aim is videos): try the topic's passing
candidates best first and take the first that repeats nothing; the topic
leaves only when every candidate is a repeat:

    already_published.py pipeline/<channel>/<batch> --topic <topic_id> --candidates [FILE]

(exit 0 + `TAKE candidate K`; exit 1 when all of them repeat). One fact the
writer picked for another reason (the scene rule) is checked alone:

    already_published.py pipeline/<channel>/<batch> --topic <topic_id> \\
        --fact-text "<fact.text>" --fact-url <fact.url> [--primary-url <url>]

After step 5 (the batch file is written), every script, all three tests;
`--write` moves a repeat from `scripts[]` to `skipped[]`:

    already_published.py pipeline/<channel>/<batch>/03-content-researcher.json [--write]

Exit 0: no repeat (with `--candidates`: one was found). Exit 1: a repeat -
for one fact at step 2, take the next candidate; with `--candidates`, every
candidate repeats, and after step 5 the script does: the topic leaves the batch as
`already_published` (`skipped[]`, with `published_video: publish/<...>.mp4`),
and its slot goes back to the reserve ladder like any refusal of this stage
(`shared/run_checks.py reserve_refill` counts every `skipped[]` row). Exit 2:
usage. No `acceptance-log.json` (a fresh root) is nothing published: exit 0.
Read only, except `--write` on the batch file.
"""
import argparse
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402
from _channel_ids import batch_dir as find_batch_dir, resolve_channel  # noqa: E402  - CF-0197

# `shared/runlog/funnel.py` FUNNEL_CODES (CF-0019), and the root's contract
# `tests/test_pipeline_contracts.py SKIP_CODES` reads this constant.
SKIP_REASON_CODE = "already_published"
FUNNEL_STAGE = "scripts"
MARK_KEY = "published_before"
SAME_WORK = "same_work"
# CF-0928: Trend Hunter's mark for a slug match whose batch is gone
# (`agents/trend-hunter/scripts/published_before.py` UNVERIFIED) - the work is
# the same as far as anyone can tell, the story unknown: compared too.
UNVERIFIED = "same_work_unverified"
COMPARED_RELATIONS = (SAME_WORK, UNVERIFIED)
ACCEPTED = "accepted"
REJECTED = "rejected"
# CF-0928: a video the user refused as a repeat of the channel's own video -
# the fact it was refused for is not taken again.
REPEAT_REJECTION = "repeated_work"
# Where `Archive:<path>.zip#<day>/<slug>.mp4` lives: `<VOLUMES_DIR>/Archive/<path>.zip`
# (CF-0476). Tests point it at a stand-in.
VOLUMES_DIR = Path(os.environ.get("CF_VOLUMES_DIR", "/Volumes"))

LOG_REL = Path("publish") / "acceptance-log.json"
RESEARCHER_FILE = "03-content-researcher.json"
TREND_FILE = "01-trend-hunter.json"

NGRAM = 6
SHARED_6GRAMS = 24
FACT_SHARE = 0.7
FACT_BIGRAM_SHARE = 0.4
FACT_MIN_WORDS = 4
# CF-0871: the other way round - a published sentence inside a longer fact.
CONTAINED_SHARE = 0.85
CONTAINED_PAIR_SHARE = 0.45
CONTAINED_PAIR_WINDOW = 3
CONTAINED_MIN_WORDS = 6

EXIT_OK, EXIT_REPEAT, EXIT_USAGE = 0, 1, 2

_BATCH_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

STOP = frozenset("""a an the and or but of to in on at for by with from as is are was were be
been being it its this that these those he she they them his her their we our you your i
so not no than then there here who whom which what when where how also very just into over
after before about up out more most some such can could would will may might do did does
has have had""".split())

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12}
_NUMWORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"hundred"}
_SCALES_AND = set(_SCALES) | {"hundred"}     # "two thousand and five", not "five, and two"
# A reference work's page holds many facts: the same section of it is not the
# same fact (measured: AHS #Filming, Endgame #Production, Anthropic #History -
# three pairs of different accepted videos). On these hosts the URL alone is
# no repeat; the fact test decides.
REFERENCE_HOSTS = ("wikipedia.org", "wikidata.org", "imdb.com", "fandom.com",
                   "britannica.com")


# ---------------------------------------------------------------- normalising

def _pairs(words):
    """'twenty three' -> [23]; 'twenty twenty six' -> [20, 26]: the two-digit
    groups of a run with no scale word."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in _TENS and i + 1 < len(words) and words[i + 1] in _UNITS and _UNITS[words[i + 1]] < 10:
            out.append(_TENS[w] + _UNITS[words[i + 1]])
            i += 2
        elif w in _TENS:
            out.append(_TENS[w])
            i += 1
        elif w in _UNITS:
            out.append(_UNITS[w])
            i += 1
        else:
            return None
    return out


def _number(words):
    """A run of number words as one digit string, or None."""
    if "hundred" not in words and not any(w in _SCALES for w in words):
        groups = _pairs(words)
        if not groups:
            return None
        if len(groups) == 1:
            return str(groups[0])
        if len(groups) == 2 and 10 <= groups[0] <= 99 and (groups[1] >= 10 or groups[1] == 0 or
                                                            words[-2] in ("oh", "o")):
            return f"{groups[0]}{groups[1]:02d}"           # a year: twenty twenty six
        return "".join(str(g) for g in groups)
    total, current = 0, 0
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w in _SCALES:
            total += max(current, 1) * _SCALES[w]
            current = 0
    return str(total + current)


def words(text):
    """Lower-case word tokens, spelled-out numbers read back as digits,
    digit groupings ("900,000,000") joined."""
    t = (text or "").lower().replace("’", "'")
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)
    # A comma, colon, dash or full stop ends a spoken number (CF-0871):
    # "July twenty twenty-two, two new films" is 2022 and 2, not 20222.
    t = re.sub(r"[,;:!?()–—]|\.(?!\d)", " | ", t)
    raw = re.findall(r"[a-z0-9]+|\|", t.replace("'", ""))
    out, run = [], []
    for w in raw + [None]:
        if w is not None and (w in _NUMWORDS or (w == "and" and run and run[-1] in _SCALES_AND)):
            run.append(w)
            continue
        while run and run[-1] == "and":
            run.pop()
            tail_and = True
        else:
            tail_and = False
        if run:
            n = _number([x for x in run if x != "and"])
            out.extend([n] if n is not None else run)
            run = []
            if tail_and:
                out.append("and")
        if w is not None and w != "|":
            out.append(w)
    return out


def content(tokens):
    return {w for w in tokens if w not in STOP}


def bigrams(text):
    """Pairs of neighbouring content words: the order a fact is said in."""
    c = [w for w in words(text) if w not in STOP]
    return {tuple(c[i:i + 2]) for i in range(len(c) - 1)}


def near_pair_share(stmt_seq, fact_seq, window=CONTAINED_PAIR_WINDOW):
    """Share of the statement's pairs of neighbouring content words that stand
    within `window` content words of each other in the fact, in either order:
    a longer sentence inserts words ("the films Vanguards: The Kang Dynasty and
    Vanguards: Secret Wars") and moves clauses ("announced in July 2022" to the
    front), which strict neighbour pairs do not survive."""
    pos = {}
    for i, w in enumerate(fact_seq):
        pos.setdefault(w, []).append(i)
    pairs = list(dict.fromkeys(zip(stmt_seq, stmt_seq[1:])))
    if not pairs:
        return 0.0
    hit = sum(1 for a, b in pairs
              if any(abs(i - j) <= window for i in pos.get(a, ()) for j in pos.get(b, ())))
    return hit / len(pairs)


def numbers(tokens):
    """The numbers of two digits or more (years, counts, scores): a sentence
    naming one the fact does not name is another fact ("July 2024" is not
    "July 2022"). One digit is left out - "two new films" counts, not dates."""
    return {w for w in tokens if w.isdigit() and len(w) >= 2}


def contained(fact_text, stmts):
    """The best published statement that lies almost whole inside the fact:
    (word share, pair share, statement) or None."""
    ft = words(fact_text)
    fw, fs, fn = {w for w in ft if w not in STOP}, [w for w in ft if w not in STOP], set(ft)
    best = None
    for s in stmts:
        st = words(s)
        ss = [w for w in st if w not in STOP]
        sw = set(ss)
        if len(sw) < CONTAINED_MIN_WORDS:
            continue
        share = len(sw & fw) / len(sw)
        if share < CONTAINED_SHARE or not numbers(st) <= fn:
            continue
        pair = near_pair_share(ss, fs)
        if pair >= CONTAINED_PAIR_SHARE and (best is None or (share, pair) > best[:2]):
            best = (share, pair, s)
    return best


def ngrams(tokens, n=NGRAM):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def norm_url(url):
    if not isinstance(url, str) or not url.strip():
        return None
    p = urlsplit(url.strip())
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    frag = f"#{p.fragment}" if p.fragment else ""
    return f"{host}{p.path.rstrip('/')}{frag}"


def reference_page(url):
    host = (url or "").split("/", 1)[0]
    return any(host == h or host.endswith("." + h) for h in REFERENCE_HOSTS)


def _text_fields(script):
    parts = []
    for key in ("hook", "commentary", "payoff"):
        v = script.get(key)
        if isinstance(v, list):
            v = " ".join(x if isinstance(x, str) else (x or {}).get("text", "") for x in v)
        if isinstance(v, str):
            parts.append(v)
    return parts


def script_text(script):
    return " ".join(_text_fields(script))


def fact_of(script):
    """(texts, urls) of a script's fact record."""
    fact = script.get("fact") or {}
    pf = script.get("production_fact") or {}
    texts = [x for x in (fact.get("text"), pf.get("text")) if isinstance(x, str) and x.strip()]
    urls = {norm_url(u) for u in (fact.get("url"), fact.get("primary_url"), pf.get("source_url"))}
    return texts, {u for u in urls if u}


def statements(script, row=None):
    """Every sentence the published video said or stood on."""
    out = []
    for part in _text_fields(script):
        out.extend(s for s in _SENTENCE.split(part) if s.strip())
    texts, _ = fact_of(script)
    out.extend(texts)
    for c in script.get("claims") or []:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("text"), str):
            out.append(c["text"])
        for s in c.get("support") or []:
            if isinstance(s, dict) and isinstance(s.get("quote"), str):
                out.append(s["quote"])
    prof = (row or {}).get("profile") or {}
    if isinstance(prof.get("fact_text"), str):
        out.append(prof["fact_text"])
    return out


# ---------------------------------------------------------------- comparing

def compare(current, published):
    """`current` / `published`: {"fact_texts": [...], "urls": set, "text": str,
    "statements": [...]} (`text` may be empty - step 2 has no script yet).
    Returns a list of reasons, empty when not a repeat."""
    why = []
    same = sorted(u for u in current["urls"] & published["urls"] if not reference_page(u))
    if same:
        why.append({"test": "same_source", "url": same[0]})
    stmts = [(s, content(words(s)), bigrams(s)) for s in published["statements"]]
    for ft in current["fact_texts"]:
        fw, fb = content(words(ft)), bigrams(ft)
        if len(fw) < FACT_MIN_WORDS or not fb:
            continue
        best = max(((len(fw & sw) / len(fw), len(fb & sb) / len(fb), s)
                    for s, sw, sb in stmts if len(fb & sb) / len(fb) >= FACT_BIGRAM_SHARE),
                   default=(0, 0, None))
        if best[0] >= FACT_SHARE:
            why.append({"test": "same_fact", "fact": ft, "published": best[2].strip(),
                        "share": round(best[0], 2), "bigram_share": round(best[1], 2)})
            break
    else:
        for ft in current["fact_texts"]:
            hit = contained(ft, published["statements"])
            if hit:
                why.append({"test": "same_fact", "contained": True, "fact": ft,
                            "published": hit[2].strip(), "share": round(hit[0], 2),
                            "pair_share": round(hit[1], 2)})
                break
    if current.get("text") and published.get("text"):
        n = len(ngrams(words(current["text"])) & ngrams(words(published["text"])))
        if n >= SHARED_6GRAMS:
            why.append({"test": "same_text", "shared_6grams": n})
    return why


# ---------------------------------------------------------------- the published side

def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def batch_start(batch_id):
    m = _BATCH_TIME.match(batch_id or "")
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)}T{m.group(2)}{m.group(3)}", "%Y-%m-%dT%H%M").replace(
        tzinfo=timezone.utc)


def _when(row):
    """(datetime, exact?) of a row's verdict."""
    ts = row.get("recorded_at")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")), True
        except ValueError:
            pass
    day = row.get("answered_at")
    if isinstance(day, str):
        try:
            return datetime.strptime(day[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc), False
        except ValueError:
            pass
    return None, False


def accepted_before(row, batch_id):
    """The row is a video accepted before the batch `batch_id` started."""
    return row.get("verdict") == ACCEPTED and decided_before(row, batch_id)


def refused_as_repeat(row):
    """CF-0928: the user refused the video as a repeat of the channel's own."""
    return row.get("verdict") == REJECTED and row.get("reason_code") == REPEAT_REJECTION


def decided_before(row, batch_id):
    """The row's verdict was given, and its batch started, before the batch
    `batch_id` started."""
    start = batch_start(batch_id)
    if start is None or not row.get("batch_id") or row["batch_id"] >= batch_id:
        return False
    when, exact = _when(row)
    if when is None:
        return False
    return when < start if exact else when.date() < start.date()


def canon_entry(entry_id, root=None):
    """`<channel>/<batch>/<slug>` with the channel under its current id: a row
    or mark written before a rename names the channel by its former id
    (CF-0197), and the same video must not become two keys."""
    if not entry_id:
        return entry_id
    head, sep, rest = str(entry_id).partition("/")
    return f"{resolve_channel(head, root=root) or head}{sep}{rest}" if sep else str(entry_id)


def latest_rows(root):
    """`entry_id -> latest row` of the acceptance log ({} without one)."""
    log = _read(Path(root) / LOG_REL)
    rows = (log or {}).get("acceptances") if isinstance(log, dict) else None
    latest = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("entry_id"):
            latest[r["entry_id"]] = r
    return latest


def _read_from_dir(root, row):
    """CF-0928: the batch the row's profile was read from (`profile.read_from`,
    e.g. `pipeline/rebuilds/2026-10-09T1208Z` - a rebuilt video's 03 lives
    there, not under the channel), when it is a directory under the root's
    `pipeline/`."""
    rel = (row.get("profile") or {}).get("read_from")
    if not isinstance(rel, str) or not rel.strip():
        return None
    base = (Path(root) / "pipeline").resolve()
    d = (Path(root) / rel.strip()).resolve()
    if d == base or base not in d.parents or not d.is_dir():
        return None
    return d


def published_script(root, row):
    """The published video's script in its batch's 03, or None."""
    # The batch dir is searched under every name the channel has had: a batch
    # accepted before a rename lives under the former id (CF-0197).
    bdir = find_batch_dir(resolve_channel(row.get("channel"), root=root),
                          str(row.get("batch_id")), root=root) if row.get("batch_id") else None
    d = _read(bdir / RESEARCHER_FILE) if bdir else None
    if not isinstance(d, dict):
        # CF-0928: the channel's batch dir is gone or holds no 03 - a rebuild
        # names the dir it was read from.
        rdir = _read_from_dir(root, row)
        d = _read(rdir / RESEARCHER_FILE) if rdir else None
    if not isinstance(d, dict):
        return None
    sid = (row.get("profile") or {}).get("script_id")
    scripts = [s for s in d.get("scripts") or [] if isinstance(s, dict)]
    for s in scripts:
        if sid and s.get("script_id") == sid:
            return s
    for s in scripts:
        if row.get("topic_id") and s.get("topic_id") == row["topic_id"]:
            return s
    return None


_ARCHIVE_PATH = re.compile(r"^(?P<volume>[^:/]+):(?P<zip>[^#]+\.zip)#(?P<inner>.+)$")


def video_ref(row):
    path = row.get("publish_path")
    if isinstance(path, str) and path:
        if _ARCHIVE_PATH.match(path):
            return path
        return path if path.startswith("publish/") else f"publish/{path}"
    if refused_as_repeat(row):
        return (f"pipeline/{resolve_channel(row.get('channel'))}/{row.get('batch_id')} "
                f"({row.get('slug')}, refused as {REPEAT_REJECTION} {row.get('answered_at')})")
    return (f"pipeline/{resolve_channel(row.get('channel'))}/{row.get('batch_id')} ({row.get('slug')}, "
            f"accepted {row.get('answered_at')}, no publish_path)")


def verdict_words(row):
    if refused_as_repeat(row):
        return f"refused as {REPEAT_REJECTION} {row.get('answered_at')}"
    return f"accepted {row.get('answered_at')}"


# ---------------------------------------------------------------- the publish card

def _card_text(root, publish_path):
    """CF-0928: the publish card (`<slug>.md` beside the `.mp4`) of a
    `publish_path`: in the tree (`publish/<channel>/<day>/<slug>.md`), else -
    a month moved to Archive (CF-0476) - inside its zip
    (`<VOLUMES_DIR>/<volume>/<path>.zip`, `<day>/<slug>.md`). None when
    neither is there (the disk not mounted)."""
    if not isinstance(publish_path, str) or not publish_path.endswith(".mp4"):
        return None
    m = _ARCHIVE_PATH.match(publish_path)
    if m:
        inner = m.group("inner")[:-4] + ".md"
        zpath = m.group("zip")
        channel = Path(zpath).parent.name
        in_tree = Path(root) / "publish" / channel / inner
    else:
        rel = publish_path[len("publish/"):] if publish_path.startswith("publish/") else publish_path
        in_tree = Path(root) / "publish" / (rel[:-4] + ".md")
    try:
        if in_tree.is_file():
            return in_tree.read_text()
    except OSError:
        pass
    if not m:
        return None
    archive = VOLUMES_DIR / m.group("volume") / m.group("zip")
    try:
        with zipfile.ZipFile(archive) as z:
            return z.read(inner).decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile, ValueError):
        return None


_CARD_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_CARD_QUOTE = re.compile(r"«([^«»]+)»")
_CARD_URL = re.compile(r"https?://\S+")


def card_facts(text):
    """(statements, urls) of a publish card: the description's first paragraph
    (the fact as published), every «quote» of `## Утверждения` (what the voice,
    the caption, the title and the description said, and the source quotes
    under them), and the URL of the description's `The fact in this video comes
    from:` line."""
    if not text:
        return [], set()
    sections, last = {}, None
    for m in _CARD_SECTION.finditer(text):
        if last:
            sections[last[0]] = text[last[1]:m.start()]
        last = (m.group(1).strip().lower(), m.end())
    if last:
        sections[last[0]] = text[last[1]:]
    stmts, urls = [], set()
    desc = sections.get("описание", "")
    paras = [p.strip() for p in re.split(r"\n\s*\n", desc) if p.strip()]
    if paras and not paras[0].startswith("The fact in this video"):
        stmts.extend(x for x in _SENTENCE.split(paras[0]) if x.strip())
    for p in paras:
        if p.startswith("The fact in this video comes from"):
            for u in _CARD_URL.findall(p.splitlines()[0]):
                n = norm_url(u)
                if n:
                    urls.add(n)
    stmts.extend(q.strip() for q in _CARD_QUOTE.findall(sections.get("утверждения", "")) if q.strip())
    return stmts, urls


def marks_of(topic):
    return [m for m in (topic or {}).get(MARK_KEY) or []
            if isinstance(m, dict) and m.get("relation") in COMPARED_RELATIONS]


def find_topic(batch_dir, topic_id):
    """The topic's record in `01` (topics[] or any reserve row carrying it)."""
    d = _read(Path(batch_dir) / TREND_FILE)
    found = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("topic_id") == topic_id and ("title_ref" in x or MARK_KEY in x):
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
    with_mark = [t for t in found if t.get(MARK_KEY)]
    return (with_mark or found or [None])[0]


def published_videos(root, channel, batch_id, marks, latest=None):
    """The rows a topic with these `same_work` / `same_work_unverified` marks
    is held against: the videos the marks name and every video of the same
    channel and slug, accepted - or refused as `repeated_work` (CF-0928) -
    before `batch_id` started."""
    latest = latest_rows(root) if latest is None else latest
    channel = resolve_channel(channel, root=root)
    named, slugs = set(), set()
    for m in marks:
        if m.get("entry_id"):
            named.add(canon_entry(m["entry_id"], root))
        if m.get("slug"):
            slugs.add(m["slug"])
            if m.get("batch"):
                named.add(f"{resolve_channel(m.get('channel'), root=root) or channel}/{m['batch']}/{m['slug']}")
    out = []
    for eid, row in latest.items():
        if row.get("verdict") != ACCEPTED and not refused_as_repeat(row):
            continue
        if (canon_entry(eid, root) not in named
                and not (resolve_channel(row.get("channel"), root=root) == channel
                         and row.get("slug") in slugs)):
            continue
        if decided_before(row, batch_id):
            out.append(row)
    # The accepted videos first: the first hit is the `published_video` a
    # refusal names.
    return sorted(out, key=lambda r: (r.get("verdict") != ACCEPTED, r.get("batch_id") or ""))


def published_side(root, row):
    found = published_script(root, row)
    script = found or {}
    texts, urls = fact_of(script)
    prof = row.get("profile") or {}
    u = norm_url((prof.get("fact_source") or {}).get("url"))
    if u:
        urls.add(u)
    stmts = statements(script, row)
    if found is None:
        # CF-0928: the batch is gone (rink-rivals 1208Z, 13.10) - what is
        # left of the video is its log row (above) and its publish card.
        card_stmts, card_urls = card_facts(_card_text(root, row.get("publish_path")))
        stmts.extend(card_stmts)
        urls |= card_urls
    return {"fact_texts": texts, "urls": urls, "text": script_text(script),
            "statements": stmts, "script_id": script.get("script_id")}


def current_side(script=None, fact_text=None, fact_urls=()):
    if script is not None:
        texts, urls = fact_of(script)
        return {"fact_texts": texts, "urls": urls, "text": script_text(script)}
    return {"fact_texts": [t for t in [fact_text] if t],
            "urls": {u for u in map(norm_url, fact_urls) if u}, "text": ""}


def judge(root, batch_dir, channel, batch_id, topic_id, current, latest=None):
    """[(row, reasons)] of the published videos `current` repeats."""
    topic = find_topic(batch_dir, topic_id)
    marks = marks_of(topic)
    if not marks:
        return [], 0
    rows = published_videos(root, channel, batch_id, marks, latest)
    hits = []
    for row in rows:
        why = compare(current, published_side(root, row))
        if why:
            hits.append((row, why))
    return hits, len(rows)


def reason_line(topic_id, hits):
    row, why = hits[0]
    tests = ", ".join(w["test"] for w in why)
    detail = []
    for w in why:
        if w["test"] == "same_source":
            detail.append(f"the fact's source {w['url']} is that video's")
        elif w["test"] == "same_fact" and w.get("contained"):
            detail.append(f"that video said \"{w['published']}\", and it lies inside the fact "
                          f"\"{w['fact']}\"")
        elif w["test"] == "same_fact":
            detail.append(f"the fact \"{w['fact']}\" is what that video said: \"{w['published']}\"")
        elif w["test"] == "same_text":
            detail.append(f"{w['shared_6grams']} shared 6-word runs of hook/commentary/payoff")
    return (f"{topic_id} repeats {video_ref(row)} ({row.get('entry_id')}, "
            f"{verdict_words(row)}): {tests} - " + "; ".join(detail))


def skip_entry(topic_id, hits):
    row = hits[0][0]
    return {
        "topic_id": topic_id,
        "reason_code": SKIP_REASON_CODE,
        "reason": reason_line(topic_id, hits),
        "stage": FUNNEL_STAGE,
        "published_video": video_ref(row),
        "published_before": [{"entry_id": r.get("entry_id"), "video": video_ref(r),
                              "tests": why} for r, why in hits],
    }


def _cand_fact(c):
    """(text, urls) of one candidate: a `fact_candidates[]` row of 01, the
    `fact` record production_facts.py prints, or a bare {text, url}."""
    f = c.get("fact") if isinstance(c.get("fact"), dict) else c
    urls = [f.get("url"), f.get("primary_url"), f.get("source_url")]
    return f.get("text") or f.get("sentence"), [u for u in urls if u]


def ranked_candidates(topic):
    """The topic's passing `fact_candidates[]` of 01, best first - the order
    `fact_rule.best_candidate()` re-establishes (file order when the root's
    rule cannot be loaded)."""
    passing = [c for c in (topic or {}).get("fact_candidates") or []
               if isinstance(c, dict) and (c.get("check") or {}).get("passes")]
    try:
        from _factrule import fact_rule
        return sorted(passing, key=fact_rule._rank)
    except Exception:
        return passing


def load_candidates(spec, batch_dir, topic_id):
    """`--candidates` with no file: the topic's own list in 01; with a file:
    a JSON list (or {"candidates": [...]}) in the order to try."""
    if spec in (None, "", "01"):
        return ranked_candidates(find_topic(batch_dir, topic_id))
    d = _read(spec)
    if isinstance(d, dict):
        d = d.get("candidates")
    return [c for c in d or [] if isinstance(c, dict)]


def first_fresh(root, batch_dir, channel, batch_id, topic_id, candidates, latest=None):
    """(index of the first candidate that repeats no published video or None,
    [(index, hits)] of the candidates refused as repeats before it, n)."""
    repeats, n = [], 0
    for i, c in enumerate(candidates):
        text, urls = _cand_fact(c)
        hits, n = judge(root, batch_dir, channel, batch_id, topic_id,
                        current_side(fact_text=text, fact_urls=urls), latest)
        if not hits:
            return i, repeats, n
        repeats.append((i, hits))
    return None, repeats, n


# ---------------------------------------------------------------- CLI

def _locate(path):
    """(batch_dir, researcher_file_or_None)."""
    p = Path(path)
    if p.is_file():
        return p.parent, p
    if p.is_dir():
        f = p / RESEARCHER_FILE
        return p, (f if f.is_file() else None)
    return None, None


def main(argv=None, out=print):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch", help="pipeline/<channel>/<batch> or its 03-content-researcher.json")
    ap.add_argument("--topic", help="step 2: the topic whose fact was just picked")
    ap.add_argument("--fact-text", help="step 2: the fact's text")
    ap.add_argument("--fact-url", action="append", default=[], help="step 2: fact.url")
    ap.add_argument("--primary-url", action="append", default=[], help="step 2: fact.primary_url")
    ap.add_argument("--candidates", nargs="?", const="01", default=None, metavar="FILE",
                    help="step 2: try the fact candidates in order and name the first that "
                         "repeats nothing (no FILE: the topic's passing fact_candidates of 01, "
                         "best first)")
    ap.add_argument("--root", help="factory root (default: <batch>/../../..)")
    ap.add_argument("--write", action="store_true",
                    help="after step 5: move a repeat from scripts[] to skipped[] in the 03")
    ap.add_argument("--json", action="store_true", help="print the skipped[] entries as JSON")
    args = ap.parse_args(argv)
    batch_dir, rfile = _locate(args.batch)
    if batch_dir is None:
        out(f"already_published.py: no such batch {args.batch!r}")
        return EXIT_USAGE
    batch_dir = batch_dir.resolve()
    root = Path(args.root).resolve() if args.root else batch_dir.parents[2]
    channel, batch_id = batch_dir.parent.name, batch_dir.name
    latest = latest_rows(root)
    if not latest:
        out(f"  note: no {LOG_REL} under {root} - nothing accepted, nothing to repeat")
    refused = []
    if args.topic and args.candidates is not None:
        cands = load_candidates(args.candidates, batch_dir, args.topic)
        if not cands:
            out(f"already_published.py: no passing fact candidate for {args.topic} "
                f"({args.candidates}) - nothing to try")
            return EXIT_USAGE
        take, repeats, n = first_fresh(root, batch_dir, channel, batch_id, args.topic,
                                       cands, latest)
        out(f"{args.topic}: {len(cands)} candidate(s), held against {n} accepted or "
            f"repeat-refused video(s) of the same work")
        for i, hits in repeats:
            out(f"  REPEAT candidate {i + 1}: {_cand_fact(cands[i])[0]!r} - "
                f"{reason_line(args.topic, hits)}")
        if take is not None:
            text, urls = _cand_fact(cands[take])
            out(f"  TAKE candidate {take + 1}: {text!r} ({', '.join(urls)})")
            if args.json:
                out(json.dumps({"take": take, "candidate": cands[take],
                                "refused_as_repeat": [i for i, _ in repeats]},
                               indent=2, ensure_ascii=False))
            return EXIT_OK
        entry = skip_entry(args.topic, repeats[0][1])
        entry["reason"] = (f"all {len(cands)} passing fact candidate(s) repeat a published "
                           f"video - {entry['reason']}")
        entry["candidates_refused"] = len(cands)
        refused.append((None, entry))
    elif args.topic:
        if not (args.fact_text or args.fact_url or args.primary_url):
            out("already_published.py: --topic needs the fact (--fact-text / --fact-url)")
            return EXIT_USAGE
        cur = current_side(fact_text=args.fact_text,
                           fact_urls=list(args.fact_url) + list(args.primary_url))
        hits, n = judge(root, batch_dir, channel, batch_id, args.topic, cur, latest)
        out(f"{args.topic}: held against {n} accepted or repeat-refused video(s) of the same work")
        if hits:
            refused.append((None, skip_entry(args.topic, hits)))
    else:
        if rfile is None:
            out(f"already_published.py: no {RESEARCHER_FILE} in {batch_dir} - at step 2 pass "
                f"--topic with the fact")
            return EXIT_USAGE
        data = _read(rfile)
        if not isinstance(data, dict):
            out(f"already_published.py: cannot read {rfile}")
            return EXIT_USAGE
        for s in data.get("scripts") or []:
            if not isinstance(s, dict):
                continue
            hits, n = judge(root, batch_dir, channel, batch_id, s.get("topic_id"),
                            current_side(s), latest)
            out(f"  {s.get('script_id')}: held against {n} accepted or repeat-refused video(s) of the same work"
                + (" - REPEAT" if hits else ""))
            if hits:
                refused.append((s, skip_entry(s.get("topic_id"), hits)))
        if refused and args.write:
            ids = {id(s) for s, _ in refused}
            data["scripts"] = [s for s in data.get("scripts") or [] if id(s) not in ids]
            data.setdefault("skipped", [])
            have = {k.get("topic_id") for k in data["skipped"] if isinstance(k, dict)
                    and k.get("reason_code") == SKIP_REASON_CODE}
            for _, entry in refused:
                if entry["topic_id"] not in have:
                    data["skipped"].append(entry)
                    have.add(entry["topic_id"])
            Path(rfile).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            out(f"  wrote {rfile}: {len(refused)} script(s) moved to skipped[] as "
                f"`{SKIP_REASON_CODE}`")
    for _, entry in refused:
        out(f"  REFUSE {entry['topic_id']}: {SKIP_REASON_CODE} - {entry['reason']}")
    if args.json and refused:
        out(json.dumps([e for _, e in refused], indent=2, ensure_ascii=False))
    if refused:
        out(f"\n{len(refused)} repeat(s) of a published video - the topic leaves the batch as "
            f"`{SKIP_REASON_CODE}` (skipped[], stage `{FUNNEL_STAGE}`); its slot goes to the "
            f"reserve ladder like any refusal. Do not write it, do not look for another fact.")
        return EXIT_REPEAT
    return EXIT_OK


@runlog.script("content-researcher", "already-published", name="already_published.py")
def cli():
    """The command-line entry (CF-0107): main()'s code is the exit code inside
    the run event. Pure Python over the batch's files and the root's
    acceptance log - no external call, no model call."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
