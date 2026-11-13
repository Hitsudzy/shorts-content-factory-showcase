#!/usr/bin/env python3
"""CF-0183: hold a written batch's `production_fact` to the script contract.

**What this field is.** Since the position was rewritten (CF-0181), a script
retells one story and owes it **one concrete, verifiable fact the story does
not carry** - of any kind since CF-0439: how a scene was shot, what the film
grossed, when and where it premiered, who was cast or replaced, what the
critics scored it, a lawsuit, news about the people (its kind is in the
script's `fact.kind`, CF-0438; the field keeps its old name). The stance
calls that the contribution and gives it three layers (`how_the_contribution_shows`): the
viewer hears it in a beat, the reviewer sees it on screen, and the gate can
only read the field. This script is the gate's half.

It replaces the field CF-0064 introduced. `comparison` - the claim, the
compared shots, the finding - belonged to the cancelled position (announce
against footage) and is not written any more; a script still carrying it is
flagged here, because the one thing DoD 1.4.1 item 1 refuses is that position
surviving in an artifact.

**The shape**, per script, required and never empty::

    "production_fact": {
      "text": "<the fact, as a record: one or two sentences, concrete>",
      "beat_text": "<verbatim contiguous substring of `commentary`>",
      "source_url": "https://...",
      "on_screen": "<our wording for the screen, <= 60 chars>" | null
    }

Three of the four names are CF-0186's, not this repo's: the Video Editor's
`comparison_line.py` reads `beat_text`, `on_screen` and `source_url` off this
object and nothing else, so they are spelled the way it spells them. `text`
is the record - the fact in words, which is what CF-0187 judges and what the
screen falls back to when it is short enough to read.

What each one is held to, and why:

    text        non-empty. The fact as a record. Whether it is concrete,
                absent from the story and backed by its link is **not**
                judged here - that is Compliance Checker's (CF-0187). This
                catches absence and a stub, the cheap deterministic half of
                the split the stance's `verification` draws.
    beat_text   non-empty and a verbatim contiguous substring of
                `commentary`. It is the *locator*: the Video Editor finds its
                word range in the forced alignment and mounts the line on it,
                so a beat rephrased between the field and the prose points at
                nothing. Same rule the `reactions[]` and `sounds[]` beats
                carry, and for the same reason.
    source_url  non-empty, http(s). The channel takes the fact from a source
                of its own and names it (stance `the_channel_does`); a fact
                on our word alone is the thing the stance refuses. The Video
                Editor treats it as optional - a fact with no source still
                gets its line, it just gets no badge - and that is the
                editor being defensive about a field it did not write, not a
                licence for the writer to leave it out.
    on_screen   optional: absent or null, else non-empty and at most
                FACT_MAX_CHARS characters (60 - `comparison_line.FACT_MAX_CHARS`
                in agents/video-editor). Nothing is ever shortened on the way
                to the screen, so a longer wording is not trimmed, it is
                refused here. It becomes **required** when `text` is itself
                over the budget: with neither, the line goes up with its badge
                alone and the fact is on screen nowhere - a silent loss that
                looks like a design.

**The fact's record** (CF-0438), per script, beside `production_fact` and
required too::

    "fact": {"text": ..., "kind": "production" | "box_office" | ..., "source":
             "Variety", "url": "https://...", "primary_url"?, "source_type"?,
             "quote"?, "attribution"?, "section"?, "tier"?}

It is `fact_rule.fact_record()` of the candidate step 2 took - copied as
`production_facts.py --from-batch` prints it under `fact`, never retyped. The
fact may be of any kind of the channel's now (its `kinds`), and the kind travels on
from here into the publication record (CF-0440). Held to: an object, only the
record's own keys, `text` / `kind` / `source` / `url` non-empty, `kind` one of
the channel's kinds, `url` a URL, and `production_fact.source_url` one of the
record's two links (`url`, or `primary_url` when the writer cited the
original) - the badge and the record must name the same source.

**The kinds are the channel's** (CF-0628, CF-0561): `kind` is held to the
`kinds` of the batch's channel's fact-source list
(`channels/<id>/fact-sources.json`, read through the root's
`shared/channel_data.py` by `scripts/_channel_data.py`), the channel being
the 03's own `channel` field with a former id resolved. There is no default
channel and no common list: a batch without `channel`, or a channel without
the list, is exit 2 naming what is missing - a gate with no list to judge by
says so, it does not judge by another channel's.

**The outlet's terms for AI output** (CF-0671): an outlet of the channel's
list may forbid the phrasing an AI product names it with (NASA: no "according
to NASA", no "NASA says / confirms", no "NASA-approved" - the source would
read as the video's endorser). The bans are the channel's data
(`fact-sources.json` -> `ai_output_terms`, read through `attribution_terms`)
and are matched deterministically (`attribution_hits`: case-blind, links cut
out) in what the video says and shows - `hook`, `commentary`, `payoff` and
`production_fact.text` / `beat_text` / `on_screen`. A hit is
`attribution_forbidden`: say the fact in the video's own voice, the source is
named by the badge and the description ("Source: NASA" with the link) - the
topic stays. `proofs[].verbatim_text` is not read: it is the source document's
own headline, quoted. A channel with no such terms (example-film) is judged as
before; a block that cannot be matched is exit 2, like a missing list.

**Never the factory's own record** (CF-0690): the fact's record (`fact.url`,
`primary_url`, `source`) or its `source_url` naming a support_text piece the
Trend Hunter marked `not_a_fact` (the API demo's `api_demo_record`, the own
capture's `own_capture_record`), or a record whose `source` is `api_demo` /
`own_capture`, is `api_demo_answer_is_fact`: what a model answered through
its API or a recorded tool showed is its output, not the story's fact - take
the fact from step 2's candidates. Read when the 01 is beside the batch.

**Never wider than its quote where the quote is known to be short**
(CF-0729, sophie-adenot, rebuild 2026-10-13T0524Z: the Wikipedia sentence lost
the award's name - "was awarded the for her" - the caveat said "the award's
name is missing", and `production_fact.text` still said "awarded a prize").
When the record's quote (`fact.text`, and `fact.quote` when there is one) has
a hole the extraction left, or `sourcing_caveat` says the source leaves
something out, every content word of `production_fact.text` / `on_screen`
has to be the quote's own (its stem) or a name the record carries (`source`,
`url`, `section`, `attribution`) - else `fact_wider_than_quote`. Without
either sign the record in the writer's words is the claim judge's, as before.

The refusal rule - no fact found, so the topic is dropped - is deliberately
NOT here. It is CF-0185's, it arrives behind a switch, and the reason is in
the stance's `refusal`: declaring the fact mandatory before CF-0184 supplies
the facts would empty the batch. This script judges a script that was
written, not a topic that was not.

Usage:

    python3 scripts/check_production_fact.py <03-content-researcher.json> [--root <factory>]

Prints one line per script; exit 0 when every script is clean, 1 otherwise,
2 when the batch's channel, its kinds or its outlets' terms cannot be had.
Read-only: nothing is written back.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)

from check_narration_budget import find_root  # noqa: E402
from _factrule import fact_rule  # noqa: E402
from _channel_data import channel_data  # noqa: E402 - CF-0628: the channel's kinds
from _channel_ids import resolve_channel  # noqa: E402
import _score  # noqa: E402 - CF-0547: the price of fact_anchor_early

FIELD = "production_fact"
# CF-0438: the record of the fact taken at step 2 (`fact_rule.fact_record`).
RECORD_FIELD = "fact"
RECORD_REQUIRED = ("text", "kind", "source", "url")
RECORD_KEYS = tuple(fact_rule.FACT_KEYS) + ("tier",)
COMMENTARY_KEY = "commentary"
REQUIRED_KEYS = ("text", "beat_text", "source_url")
OPTIONAL_KEYS = ("on_screen",)

# The cancelled position's field (CF-0064). Named here so that a script that
# still carries it is answered by name rather than silently ignored.
LEGACY_FIELD = "comparison"

# The screen wording's budget, in characters. Owned by the Video Editor -
# agents/video-editor/scripts/comparison_line.py, FACT_MAX_CHARS - because it
# is what fits in the frame beside the subtitles for the length of one beat.
# The number is declared here so this checker runs without the sibling repo
# on disk, and read from there when it is: two copies that can drift silently
# is exactly the failure CF-0054 was written about.
FACT_MAX_CHARS = 60
EDITOR_CONSTANT = ("agents", "video-editor", "scripts", "comparison_line.py")
EDITOR_CONSTANT_RE = re.compile(r"^FACT_MAX_CHARS\s*=\s*(\d+)\s*$", re.M)

URL_SCHEMES = ("http://", "https://")

# CF-0538 (WNL 0701Z, the user 2026-10-05: "30с: поясни в чем суть этого
# кадра"): a picture of the fact's own story does not arrive before the fact's
# first word. The anchor whose `beat_text` begins before `production_fact.
# beat_text` and runs into it asks for its frame on words about something else
# - v5's cold-open sketch stood 6 s under "with Swift's entrance standing out
# as the one moment that actually landed". The words before the fact keep the
# previous anchor's picture, or get an anchor of their own.
# Mode `warn` (the CF-0539 precedent): the line is printed with the repair,
# the exit stays 0. The user decided on 2026-10-05 it is never a refusal but a
# price (CF-0547, below), so `warn` is where it stays; `fail` (a problem of the
# script) is kept only as the switch the tests exercise.
FACT_ANCHOR_RULE = "fact_anchor_early"
FACT_ANCHOR_MODE = "warn"
ANCHORS_KEY = "visual_anchors"


def editor_fact_max_chars(root=None):
    """FACT_MAX_CHARS as the Video Editor declares it, or None when that repo
    is not on this disk. Read as text rather than imported: the sibling module
    imports its own dependencies and has its own venv, and all we want is one
    integer."""
    root = root or find_root()
    path = root.joinpath(*EDITOR_CONSTANT)
    if not path.exists():
        return None
    found = EDITOR_CONSTANT_RE.search(path.read_text())
    return int(found.group(1)) if found else None


def fact_max_chars(root=None):
    """The budget this run holds `on_screen` to: the editor's number when it
    can be read, else the declared one."""
    try:
        theirs = editor_fact_max_chars(root)
    except OSError:
        theirs = None
    return FACT_MAX_CHARS if theirs is None else theirs


# CF-0860 (example-film 2026-10-24T0840Z, wildwood and rink-rivals): step
# 6's later gates (the claims judge's rewrite, the cadence, the number
# density) rewrote the fact's sentence in the commentary after this check had
# passed, `claims[]` was rewritten with it and `production_fact.beat_text` was
# not - "In September twenty eleven, a week after the release of the book
# Wildwood, Laika optioned the novel ..." stayed in the field while the
# narrator said "Laika optioned the novel a week after its release." The
# Video Editor found 0.226 of the beat's words, put no fact line up at all,
# and the root contract went red. The beat is a locator, not a claim: the
# commentary's sentence the fact is spoken in now is found mechanically, and
# step 6b writes it back before the first plan check (plan_check_loop.py).
# Only words of the old beat and of the fact's record count; a sentence that
# says something else, or two sentences that tie, find nothing - and then the
# writer has to say where the fact is.
REANCHOR_MIN_SHARED = 3        # content words a sentence shares with the beat / the record
REANCHOR_MIN_PRECISION = 0.75  # of the sentence's content words, the share from them
REANCHOR_STOPWORDS = frozenset("""a an the of in on at to and or but nor so for from by with as
into onto over under about after before than then that this these those there here it its it's
is are was were be been being has have had do does did not no he she they we you i his her their
our your my him them us who whom which what when where while also just only very now all any
each both some such own same too can could would should will shall may might must""".split())
_REANCHOR_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
_REANCHOR_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+[\"'\u2019\u201d)]*|[^.!?]+$")


def _content_words(text):
    words = _REANCHOR_WORD_RE.findall((text or "").lower().replace("\u2019", "'"))
    return {w for w in words if w not in REANCHOR_STOPWORDS}


def _sentence_spans(commentary):
    """(start, end) of every sentence of the commentary, white space off."""
    spans = []
    for m in _REANCHOR_SENTENCE_RE.finditer(commentary):
        a, b = m.start(), m.end()
        while a < b and commentary[a].isspace():
            a += 1
        while b > a and commentary[b - 1].isspace():
            b -= 1
        if a < b:
            spans.append((a, b))
    return spans


def reanchor_beat(fact, commentary):
    """CF-0860: the words of `commentary` the fact is spoken in, for a
    `production_fact.beat_text` that is not (or no longer) a verbatim
    substring of it. Returns `(beat, how)`; `beat` is None when nothing
    qualifies, and `how` then says why.

      verbatim    the beat stands as it is
      same_words  the beat's words in the beat's order, the commentary
                  differing only in case, punctuation or spacing
      sentence    the commentary sentence (or two running sentences, a fact
                  split in two) whose content words come from the old beat
                  and the record (`text`) - at least REANCHOR_MIN_SHARED of
                  them and REANCHOR_MIN_PRECISION of the sentence's - the
                  one sharing the most; two that tie find nothing
    """
    if not isinstance(fact, dict) or not isinstance(commentary, str) or not commentary.strip():
        return None, "no commentary"
    bt = fact.get("beat_text")
    if not isinstance(bt, str) or not bt.strip():
        return None, "no beat_text"
    if bt in commentary:
        return bt, "verbatim"
    words = _REANCHOR_WORD_RE.findall(bt.lower().replace("\u2019", "'"))
    if words:
        pattern = r"(?<!\w)" + r"[\W_]+".join(
            re.escape(w).replace("'", "['\u2019]") for w in words) + r"(?!\w)"
        m = re.search(pattern, commentary, re.I)
        if m:
            return m.group(0), "same_words"
    beat = _content_words(bt)
    ref = beat | _content_words(fact.get("text"))
    spans = _sentence_spans(commentary)

    def score(a, b):
        """(words shared with the old beat, with the beat and the record,
        the share of the span's own words that come from either)"""
        c = _content_words(commentary[a:b])
        return len(c & beat), len(c & ref), (len(c & ref) / len(c) if c else 0.0)

    def fits(n_beat, precision):
        return n_beat >= REANCHOR_MIN_SHARED and precision >= REANCHOR_MIN_PRECISION

    singles = [(a, b) + score(a, b) for a, b in spans]
    candidates = [c for c in singles if fits(c[2], c[4])]
    for first, second in zip(singles, singles[1:]):
        if min(first[4], second[4]) < REANCHOR_MIN_PRECISION or not first[2] or not second[2]:
            continue
        pair = (first[0], second[1]) + score(first[0], second[1])
        if fits(pair[2], pair[4]):
            candidates.append(pair)
    if not candidates:
        return None, (f"no sentence shares {REANCHOR_MIN_SHARED}+ content words with the old "
                      f"beat, {REANCHOR_MIN_PRECISION:.0%} of its own from the beat and the record")
    candidates.sort(key=lambda c: (-c[2], -c[3], -c[4], c[1] - c[0]))
    best = candidates[0]
    # another place in the prose sharing as many of the beat's words is a
    # second reading of where the fact is - nothing is guessed between them
    rivals = [c for c in candidates[1:] if c[2] == best[2]
              and (c[1] <= best[0] or c[0] >= best[1])]
    if rivals:
        return None, (f"two sentences carry it alike ({commentary[best[0]:best[1]]!r}, "
                      f"{commentary[rivals[0][0]:rivals[0][1]]!r})")
    return commentary[best[0]:best[1]], "sentence"


def check_fact(fact, commentary, max_chars=FACT_MAX_CHARS):
    """Problems with one script's `production_fact`. Every message names the
    field it is about; an empty list means the shape is sound (what the fact
    *says* is CF-0187's)."""
    if fact is None:
        return [f"{FIELD}: missing - every script carries one fact of any kind the story "
                f"does not (stance position.thesis); a script without it cannot be judged "
                f"and is not written"]
    if not isinstance(fact, dict):
        return [f"{FIELD}: must be an object, got {type(fact).__name__}"]
    if not fact:
        return [f"{FIELD}: empty - see the missing case; an empty object is not a fact"]
    problems = []
    for key in REQUIRED_KEYS:
        if key not in fact:
            problems.append(f"{FIELD}.{key}: missing")
    extra = sorted(set(fact) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if extra:
        problems.append(f"{FIELD}: unknown key(s) {extra} - the field carries the fact, the "
                        f"words it is spoken in, its source and (optionally) our wording for "
                        f"the screen; the word index, the block and the file are the Video "
                        f"Editor's (CF-0186)")

    text = fact.get("text")
    if "text" in fact and (not isinstance(text, str) or not text.strip()):
        problems.append(f"{FIELD}.text: must be a non-empty string - the fact as a record")

    if "beat_text" in fact:
        bt = fact["beat_text"]
        if not isinstance(bt, str) or not bt.strip():
            problems.append(f"{FIELD}.beat_text: must be a non-empty string")
        elif bt not in (commentary or ""):
            found, how = reanchor_beat(fact, commentary)
            hint = (f"; the commentary says it now as {found!r} ({how}) - set beat_text to "
                    f"those words (step 6b's plan_check_loop.py --write does it before the "
                    f"first check, CF-0860)" if found else
                    f"; no sentence of the commentary carries it ({how}) - write beat_text "
                    f"as the commentary's words the fact is spoken in (CF-0860)")
            problems.append(f"{FIELD}.beat_text: not a verbatim substring of `{COMMENTARY_KEY}` - "
                            f"the Video Editor locates the beat by these exact words, and a beat "
                            f"rephrased between the field and the prose points at nothing"
                            + hint)

    if "source_url" in fact:
        url = fact["source_url"]
        if not isinstance(url, str) or not url.strip():
            problems.append(f"{FIELD}.source_url: must be a non-empty string - the channel names "
                            f"the source the fact was taken from (stance the_channel_does)")
        elif not url.strip().lower().startswith(URL_SCHEMES):
            problems.append(f"{FIELD}.source_url: {url!r} is not a URL (expected one of "
                            f"{list(URL_SCHEMES)}) - the badge is drawn from its host")

    on_screen = fact.get("on_screen")
    if "on_screen" in fact and on_screen is not None:
        if not isinstance(on_screen, str) or not on_screen.strip():
            problems.append(f"{FIELD}.on_screen: must be null or a non-empty string")
        elif len(on_screen) > max_chars:
            problems.append(f"{FIELD}.on_screen: {len(on_screen)} chars, the budget is "
                            f"{max_chars} (comparison_line.FACT_MAX_CHARS in agents/video-editor) "
                            f"- nothing is shortened on the way to the screen, so rewrite it "
                            f"shorter rather than letting it be cut")
    elif isinstance(text, str) and len(text) > max_chars:
        problems.append(f"{FIELD}.on_screen: missing while `text` is {len(text)} chars (over the "
                        f"{max_chars}-char budget) - with neither, the line goes up with its "
                        f"badge alone and the fact is on screen nowhere; write the screen wording")
    return problems


def early_fact_anchors(script):
    """CF-0538: the anchors whose `beat_text` begins before the fact beat
    (`production_fact.beat_text`) and runs into it, as `{anchor_id, index,
    words_early, fact_start}` - `words_early` is the count of spoken words the
    anchor starts ahead of the fact's first word. Both beats are located the
    way the cadence gate locates an anchor: first occurrence in `commentary`.
    An anchor that ends before the fact begins is not early - its picture is
    the previous one the fact's first words may hold - and an anchor that is
    not in the commentary, or a fact beat that is not, is another check's
    problem. Pure."""
    fact = script.get(FIELD)
    commentary = script.get(COMMENTARY_KEY)
    if not isinstance(fact, dict) or not isinstance(commentary, str):
        return []
    beat = fact.get("beat_text")
    if not isinstance(beat, str) or not beat.strip():
        return []
    f0 = commentary.find(beat)
    if f0 < 0:
        return []
    out = []
    for i, a in enumerate(script.get(ANCHORS_KEY) or []):
        bt = a.get("beat_text") if isinstance(a, dict) else None
        if not isinstance(bt, str) or not bt.strip():
            continue
        a0 = commentary.find(bt)
        if a0 < 0 or a0 >= f0 or a0 + len(bt.rstrip()) <= f0:
            continue
        out.append({"anchor_id": a.get("anchor_id"), "index": i,
                    "words_early": len(commentary[a0:f0].split()),
                    "fact_start": " ".join(beat.split()[:4]),
                    "anchor_char": a0, "fact_char": f0})
    return out


def early_anchor_lines(script):
    """The CF-0538 lines for one script, with the repair."""
    return [f"{ANCHORS_KEY}[{e['index']}] ({e['anchor_id']}): {FACT_ANCHOR_RULE} - its "
            f"beat_text begins {e['words_early']} spoken word(s) before "
            f"`{FIELD}.beat_text` and runs into it, so the frame it asks for arrives "
            f"before the fact is said, under words about something else (CF-0538). "
            f"If its picture is of the fact, start its beat_text at the fact's first "
            f"words ({e['fact_start']!r}...) - the words before keep the previous "
            f"anchor's picture or get an anchor of their own; if its picture is of "
            f"the words before, end its beat_text before the fact begins"
            for e in early_fact_anchors(script)]


# CF-0547 (the user 2026-10-05 on CF-0538: «не сошлись картинка с текстом на
# пару секунд - это не крит», sometimes a staging device): an early fact anchor
# is never a refusal. It is a price in the score model - per second the
# anchor's picture arrives ahead of the fact's first word in the voice
# (`work/<slug>/words.json`, step 6b and later), with a cap. The repair line
# above stays: the writer fixes it at step 6; the price is what is left when
# the writer did not. The price is the user's to sign: until
# `shared/gate-prices.json#rules` carries `score.fact_anchor_early` (it sits in
# `proposals.rows`), nothing is charged and the line only says what it would
# cost (`_score.rule_price`).
SCORE_RULE = "score.fact_anchor_early"
WORDS_FILE = "words.json"
WORK_DIR = "work"
SPOKEN_SECTIONS = ("hook", COMMENTARY_KEY, "payoff")
LEAD_RECORD = "fact_anchor_early"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
LOCATE_TOKENS = (6, 4, 3, 2)


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower().replace("\u2019", "'"))


def alignment_tokens(words):
    """`words.json` as comparable tokens and the word each came from: a word
    that normalises to nothing (a dash spoken as a pause) takes no place, one
    that splits ("talked-about") takes two - the CF-0193 lesson of the Editor's
    `meme_layer.alignment_tokens()`, which this mirrors (that repo is not on
    this one's path)."""
    toks, owner = [], []
    for i, w in enumerate(words or []):
        for t in _tokens((w or {}).get("word") if isinstance(w, dict) else None):
            toks.append(t)
            owner.append(i)
    return toks, owner


def word_at(script, words, at, section=COMMENTARY_KEY):
    """The index in `words` of the spoken word at character `at` of `section`,
    or None. The script's first tokens from there are searched for in the
    alignment (6, then 4, 3, 2 of them); of several hits the one nearest the
    expected position (the tokens of the sections before plus the section's
    own before `at`) wins - the counts drift a little between the script and
    the voice, the words do not."""
    toks, owner = alignment_tokens(words)
    if not toks:
        return None
    before = 0
    for name in SPOKEN_SECTIONS:
        if name == section:
            break
        before += len(_tokens(script.get(name) if isinstance(script.get(name), str) else ""))
    text = script.get(section) or ""
    expected = before + len(_tokens(text[:at]))
    want = _tokens(text[at:])
    for n in LOCATE_TOKENS:
        seq = want[:n]
        if len(seq) < n:
            continue
        hits = [k for k in range(len(toks) - n + 1) if toks[k:k + n] == seq]
        if hits:
            return owner[min(hits, key=lambda k: (abs(k - expected), k))]
    return None


def fact_anchor_leads(script, words):
    """`early_fact_anchors()` with `lead_s` on each: how many seconds of voice
    the anchor's first word stands ahead of the fact's first word in
    `words.json` (None when either cannot be found in the alignment)."""
    out = []
    for e in early_fact_anchors(script):
        ia = word_at(script, words, e["anchor_char"])
        jf = word_at(script, words, e["fact_char"])
        lead = None
        if ia is not None and jf is not None and jf >= ia:
            try:
                lead = round(float(words[jf]["start"]) - float(words[ia]["start"]), 2)
            except (KeyError, TypeError, ValueError):
                lead = None
        out.append(dict(e, lead_s=lead, anchor_t=None if ia is None else words[ia].get("start")))
    return out


def lead_cost(lead_s, price):
    """`(units, cost)` of `lead_s` seconds at a price row `{price, cap,
    allow_seconds?}`: units are the seconds over the allowance (to 0.1 s),
    the cost is `price * units`, capped. Pure."""
    if not isinstance(price, dict) or lead_s is None:
        return 0, 0
    allow = price.get("allow_seconds") or 0
    units = round(max(0.0, float(lead_s) - float(allow)), 1)
    cost = float(price.get("price") or 0) * units
    if price.get("cap") is not None:
        cost = min(cost, float(price["cap"]))
    cost = round(cost, 2)
    return units, (int(cost) if float(cost).is_integer() else cost)


def fact_anchor_record(script, words, ledger=None):
    """CF-0547: what this script's early fact anchor costs on the real voice,
    or None when no anchor is early.

    `{rule, anchors: [{anchor_id, index, words_early, lead_s}], lead_s, status,
    price, units, cost, findings}`. `status` is `signed` (the rule is in the
    price table's `rules`: `findings` carries the one `score.fact_anchor_early`
    finding, units = the seconds over the allowance) or `proposed` (only in
    `proposals.rows`: `cost` is what it WOULD cost, `findings` is empty -
    nothing is charged before the user signs) or None (no price at all)."""
    leads = fact_anchor_leads(script, words)
    if not leads:
        return None
    measured = [e["lead_s"] for e in leads if e["lead_s"] is not None]
    lead = round(max(measured), 2) if measured else None
    status, price = _score.rule_price(SCORE_RULE, ledger)
    units, cost = lead_cost(lead, price)
    findings = []
    if status == _score.SIGNED and units > 0:
        first = min(leads, key=lambda e: e["index"])
        findings.append(_score.finding(
            SCORE_RULE, {"anchor": first["anchor_id"], "t": first.get("anchor_t")},
            units=units, hook=_score.in_hook(first.get("anchor_t")),
            note=f"{first['anchor_id']}'s picture {lead} s ahead of the fact's first word "
                 f"({first['words_early']} word(s))", estimate=None))
    return {"rule": SCORE_RULE,
            "anchors": [{k: e[k] for k in ("anchor_id", "index", "words_early", "lead_s")}
                        for e in leads],
            "lead_s": lead, "status": status, "price": price, "units": units,
            "cost": cost, "findings": findings}


def price_line(rec):
    """The words the WARN line adds once the voice exists."""
    if not rec or rec.get("lead_s") is None:
        return "not located in words.json - no seconds, no price"
    head = f"{rec['lead_s']} s ahead in words.json"
    if rec["status"] == _score.SIGNED:
        return f"{head}: {SCORE_RULE} -{rec['cost']} ({rec['units']} s priced)"
    if rec["status"] == _score.PROPOSED:
        return (f"{head}: would cost -{rec['cost']} at the proposed price, not charged "
                f"(unsigned, CF-0547)")
    return f"{head}: {SCORE_RULE} has no price in the table"


def slug_of(script):
    """plan_check.py's work directory of a script (`plan_check_loop.slug_of`,
    the same rule): the title's name, else the script id."""
    def slugify(name):
        s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
        return s or None
    return slugify(((script or {}).get("title_ref") or {}).get("name")) or \
        slugify((script or {}).get("script_id"))


def words_of(batch_dir, script):
    """`work/<slug>/words.json` of a script in this batch, or None (step 6:
    no voice yet)."""
    slug = slug_of(script)
    if batch_dir is None or not slug:
        return None
    try:
        words = json.loads((Path(batch_dir) / WORK_DIR / slug / WORDS_FILE).read_text())
    except (OSError, ValueError):
        return None
    return words if isinstance(words, list) else None


def check_record(record, fact, kinds):
    """Problems with one script's `fact` - the record of the fact step 2 took
    (CF-0438). `fact` is the script's `production_fact`, whose `source_url`
    has to be one of the record's links; `kinds` are the batch's channel's
    kinds of fact (`batch_kinds`, CF-0628)."""
    if record is None:
        return [f"{RECORD_FIELD}: missing - every script carries the record of its fact "
                f"(CF-0438): copy `fact` from production_facts.py --from-batch, it is "
                f"fact_rule.fact_record() of the candidate taken, `kind` and all"]
    if not isinstance(record, dict) or not record:
        return [f"{RECORD_FIELD}: must be a non-empty object, got {record!r}"]
    problems = []
    for key in RECORD_REQUIRED:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{RECORD_FIELD}.{key}: missing or empty")
    extra = sorted(set(record) - set(RECORD_KEYS))
    if extra:
        problems.append(f"{RECORD_FIELD}: unknown key(s) {extra} - the record carries "
                        f"fact_rule.FACT_KEYS and `tier`, nothing else")
    kind = record.get("kind")
    if isinstance(kind, str) and kind and kind not in kinds:
        problems.append(f"{RECORD_FIELD}.kind: {kind!r} is not one of the channel's "
                        f"kinds {list(kinds)}")
    for key in ("url", "primary_url"):
        url = record.get(key)
        if isinstance(url, str) and url.strip() and \
                not url.strip().lower().startswith(URL_SCHEMES):
            problems.append(f"{RECORD_FIELD}.{key}: {url!r} is not a URL")
    source_url = fact.get("source_url") if isinstance(fact, dict) else None
    links = {record.get("url"), record.get("primary_url")} - {None, ""}
    if isinstance(source_url, str) and source_url.strip().lower().startswith(URL_SCHEMES) \
            and links and source_url not in links:
        problems.append(f"{FIELD}.source_url: {source_url!r} is neither `{RECORD_FIELD}.url` "
                        f"nor `{RECORD_FIELD}.primary_url` - the badge on screen and the "
                        f"record that goes on to the publication must name the same source")
    return problems


WIDER_RULE = "fact_wider_than_quote"
CAVEAT_KEY = "sourcing_caveat"
# CF-0729: the two wordings of the fact read as a record - what goes on file
# and what the viewer reads. `beat_text` is the spoken prose of the commentary
# and is the claim judge's (check_claims.py), not this word-for-word test.
WIDER_FACT_KEYS = ("text", "on_screen")
# The record's footing: the source's sentence (`text`) and, when it carries
# one, its `quote`. The other fields lend names only (the subject's name in a
# Wikipedia URL is how a quote's "she" becomes "Adenot" without inventing it).
WIDER_FOOTING_KEYS = ("text", "quote")
WIDER_NAME_KEYS = ("source", "url", "primary_url", "section", "attribution")
# A hole the extraction left in the quote: an article followed straight by a
# word or mark no noun phrase starts with ("was awarded the for her") - the
# name of what was given was lost on the way.
QUOTE_BLANK_RE = re.compile(
    r"\b(?:the|a|an)\s+(?:for|of|in|by|and|or|to|with|at|on|from|as|is|was|were|the|a|an)\b"
    r"|\b(?:the|a|an)\s*[,.;:)\]]", re.I)
# The caveat saying the source leaves something out ("the award's name is
# missing", "does not name the studio", "says only that an award ...").
# CF-0737: "only says" alone is not a gap - the factory's caveats say «the
# Wikipedia sentence behind this fact only says filming happened in Atlanta»
# of a thinner source the record does not stand on (frozen 2026-09-15T1034Z
# DTF St. Louis, 2026-09-16T2148Z Slow Hounds); it is one when what is said
# is a thing left unnamed - «says only that an award ...».
CAVEAT_GAP_RE = re.compile(
    r"\b(?:missing|unnamed|unknown|blank|not\s+(?:named|given|stated|said|specified)"
    r"|(?:does|do|did)\s*(?:n't|\s+not)\s+(?:name|say|give|state|specify)"
    r"|(?:says?\s+only|only\s+says?)(?:\s+that)?\s+(?:an?|one|some)"
    r"|only\s+that\s+(?:an?|one|some)"
    r"|lost\s+in\s+(?:the\s+)?extraction)\b", re.I)
_WORD_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset("""
a an the and or but nor so yet of in on at to for from by with into onto over under
after before during about as than then that this these those there here which who
whom whose what when where why how is was were be been being are am has had have
having do does did done not no it its he him his she her hers they them their theirs
we us our you your i me my also both each either neither s t
""".split())


def _same_word(word, other):
    """One word of the fact found among the quote's: the same token, or the
    same stem (a shared start of five letters, or the whole of the shorter
    word when it is four or more: "award" / "awarded", "science" / "sciences")."""
    if word == other:
        return True
    shorter = min(len(word), len(other))
    if shorter < 4 or word.isdigit() or other.isdigit():
        return False
    need = min(5, shorter)
    return word[:need] == other[:need]


# CF-0737 (frozen 2026-09-15T1034Z, DTF St. Louis): «... in Dunwoody, GA» on
# the plate, «Dunwoody, Georgia» in the quote. A short form of a name the
# quote spells out says nothing the quote does not: a US state's postal code
# (and the country's own: US, USA, UK), or the initials of a run of the
# quote's words («Home Box Office» - «Example Network»).
STATE_CODES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "US": "United States", "USA": "United States", "UK": "United Kingdom",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_SHORT_FORM_RE = re.compile(r"[A-Z]{2,5}")
_INITIALS_SKIP = frozenset(("of", "and", "the", "for"))


def short_form_of(token, footing):
    """True when `token` («GA», «NY», «Example Network») - two to five capitals as the
    wording spells it - stands for a name `footing` spells out: a state's
    or the country's name for its postal code, or a run of the footing's
    words whose initials it is (`_INITIALS_SKIP` words left out)."""
    if not _SHORT_FORM_RE.fullmatch(token or ""):
        return False
    footing = footing or ""
    name = STATE_CODES.get(token)
    if name and re.search(r"\b" + re.escape(name) + r"\b", footing, re.I):
        return True
    words = [w for w in _TOKEN_RE.findall(footing) if w.lower() not in _INITIALS_SKIP]
    n = len(token)
    return any("".join(w[0] for w in words[i:i + n]).upper() == token
               and all(w[:1].isupper() for w in words[i:i + n])
               for i in range(len(words) - n + 1))


def wider_words(wording, footing, names=""):
    """The content words of `wording` that neither the quote (`footing`) nor
    the record's own names (`names`) carry, in order and once each. A short
    form of a name the quote spells out is the quote's (`short_form_of`)."""
    have = set(_WORD_RE.findall((footing or "").lower()))
    named = set(_WORD_RE.findall((names or "").lower()))
    out = []
    for token in _TOKEN_RE.findall(wording or ""):
        word = token.lower()
        if word in STOP_WORDS or word in out or word in named:
            continue
        if short_form_of(token, footing):
            continue
        if not any(_same_word(word, other) for other in have):
            out.append(word)
    return out


def wider_than_quote_lines(script):
    """CF-0729 (sophie-adenot, rebuild 2026-10-13T0524Z): the fact's record
    may not say more than the quote it stands on. Asked only where the quote
    itself is known to be short - a hole the extraction left in it
    (`QUOTE_BLANK_RE`: "was awarded the for her") or a `sourcing_caveat` that
    says the source leaves something out (`CAVEAT_GAP_RE`: "the award's name
    is missing", "says only that an award ...") - and then every content word
    of `production_fact.text` / `on_screen` has to be the quote's own (its
    stem) or a name the record carries. Elsewhere a record in the writer's
    words is the claim judge's to read, as before. [] when clean."""
    record = script.get(RECORD_FIELD)
    fact = script.get(FIELD)
    if not isinstance(record, dict) or not isinstance(fact, dict):
        return []
    footing = " ".join(v for v in (record.get(k) for k in WIDER_FOOTING_KEYS)
                       if isinstance(v, str))
    if not footing.strip():
        return []
    caveat = script.get(CAVEAT_KEY)
    caveat = caveat if isinstance(caveat, str) else ""
    blank = QUOTE_BLANK_RE.search(footing)
    gap = CAVEAT_GAP_RE.search(caveat)
    if not blank and not gap:
        return []
    why = []
    if blank:
        why.append(f"the quote has a hole where a word was lost ({blank.group(0)!r})")
    if gap:
        why.append(f"`{CAVEAT_KEY}` says the source leaves something out "
                   f"({gap.group(0)!r})")
    names = " ".join(v for v in (record.get(k) for k in WIDER_NAME_KEYS)
                     if isinstance(v, str))
    out = []
    for key in WIDER_FACT_KEYS:
        words = wider_words(fact.get(key), footing, names)
        if words:
            out.append(f"{FIELD}.{key}: {WIDER_RULE} - {words} is not in the quote the fact "
                       f"stands on ({RECORD_FIELD}.text {footing[:160]!r}), and "
                       f"{' and '.join(why)}. The record says what the quote says and no "
                       f"more: say the missing thing as unknown in the quote's own words "
                       f"(\"an award\", never a name or a kind the quote does not give), or "
                       f"take a fact whose source names it (no invented facts, CF-0729)")
    return out


ATTRIBUTION_RULE = "attribution_forbidden"
ATTRIBUTION_FACT_KEYS = ("text", "beat_text", "on_screen")


def attribution_fields(script, extra=None):
    """`(field, text)` of what the viewer hears or reads that the outlets'
    terms are held against (CF-0671): the spoken sections, the fact's three
    wordings, and `extra` (`{"title": ..., "description": ...}`) when handed
    in. Never `proofs[].verbatim_text` - the source's own headline, quoted."""
    out = [(name, script.get(name)) for name in SPOKEN_SECTIONS]
    fact = script.get(FIELD)
    if isinstance(fact, dict):
        out += [(f"{FIELD}.{key}", fact.get(key)) for key in ATTRIBUTION_FACT_KEYS]
    out += sorted((extra or {}).items())
    return [(name, text) for name, text in out if isinstance(text, str) and text.strip()]


def attribution_lines(script, terms, extra=None):
    """CF-0671: one problem per forbidden phrase of an outlet's terms
    (`terms` = `channel_data.attribution_terms`) found in a field of
    `attribution_fields`; [] when the channel has no terms."""
    if not terms:
        return []
    out = []
    for name, text in attribution_fields(script, extra):
        for hit in channel_data.attribution_hits(text, terms):
            out.append(f"{name}: {ATTRIBUTION_RULE} - {hit['match']!r} is a phrasing "
                       f"{hit['outlet']}'s terms forbid in an AI product ({hit['id']}: "
                       f"{hit['phrase']}; {hit['terms_url']}). Say the fact in the video's "
                       f"own voice and name the source neutrally - the badge and the "
                       f"description (\"Source: <outlet>\" with the link) do that; the topic "
                       f"stays (CF-0671)")
    return out


def batch_terms(data, root=None):
    """The batch's channel's outlets' terms for AI output (CF-0671), [] when
    it has none. Raises `channel_data.ChannelDataError` as `batch_kinds`."""
    root = Path(root) if root else None
    return channel_data.attribution_terms(resolve_channel(data.get("channel"), root), root)


def check_script(script, kinds, terms=None):
    """Problems with one script: the fact's shape and its record (`kind` one
    of `kinds`, the channel's), the outlets' `terms` for AI output (CF-0671),
    plus the cancelled field when it is still there."""
    problems = check_fact(script.get(FIELD), script.get(COMMENTARY_KEY), fact_max_chars())
    problems += check_record(script.get(RECORD_FIELD), script.get(FIELD), kinds)
    problems += attribution_lines(script, terms)
    problems += wider_than_quote_lines(script)
    if FACT_ANCHOR_MODE == "fail":
        problems += early_anchor_lines(script)
    if script.get(LEGACY_FIELD) is not None:
        problems.append(f"{LEGACY_FIELD}: the cancelled position's field (CF-0064: the claim, "
                        f"the compared shots, the finding) is still written - CF-0183 replaced "
                        f"it with `{FIELD}`; drop it")
    return problems


OFF_SCENE_RULE = "fact_off_scene"
HUNTER_FILE = "01-trend-hunter.json"


def hunter_topics(batch_dir):
    """The batch's 01 topics, or None when there is no 01 beside the 03 (a
    fixture, an old layout): then the scene is not judged."""
    if batch_dir is None:
        return None
    path = Path(batch_dir) / HUNTER_FILE
    if not path.is_file():
        return None
    try:
        return [t for t in json.loads(path.read_text()).get("topics") or []
                if isinstance(t, dict)]
    except (OSError, ValueError):
        return None


def off_scene_lines(script, topics):
    """CF-0548: the script's `fact` must be about the scene the script tells
    (`scene_id`) - not about the segment next to it (WNL 0701Z: a cold-open
    fact under Taylor Sterling's walk-on in the monologue). [] when it is, or
    when the topic/scene cannot be found."""
    if topics is None:
        return []
    topic = next((t for t in topics if t.get("topic_id") == script.get("topic_id")), None)
    record = script.get(RECORD_FIELD)
    if topic is None or not isinstance(record, dict):
        return []
    from _factrule import fact_scene
    verdict = fact_scene().fact_fits_script(record, script, topic, topics)
    if verdict is None or verdict["fits"]:
        return []
    said = []
    if verdict["segments"]["fact"] and fact_scene().FAIL_OTHER_SEGMENT in verdict["failures"]:
        said.append(f"the fact is about the {'/'.join(verdict['segments']['fact'])}, the scene "
                    f"about the {'/'.join(verdict['segments']['scene'])}")
    if verdict["foreign"]:
        said.append(f"it names another topic's work: {', '.join(verdict['foreign'])}")
    if verdict["outside"] and fact_scene().FAIL_NAMES_OUTSIDE_SCENE in verdict["failures"]:
        said.append(f"names nobody of the scene: {', '.join(verdict['outside'][:4])}")
    return [f"{RECORD_FIELD}: {OFF_SCENE_RULE} ({', '.join(verdict['failures'])}) - the fact is "
            f"not about scene {script.get('scene_id')}"
            + (f" ({'; '.join(said)})" if said else "")
            + ". Take the next candidate production_facts.py lists for this scene "
              "(`scenes`), or the scene the fact belongs to; a topic with none is no_fact "
              "(CF-0548)"]


# CF-0690: the video's own fact never stands on the factory's own record - a
# support_text piece marked `not_a_fact` (the API demo's `api_demo_record`, the
# own capture's `own_capture_record`): what a model answered or a tool showed is
# its output, not the story's fact.
NOT_A_FACT_RULE = "api_demo_answer_is_fact"    # = claims.FAIL_API_DEMO_IS_FACT
NOT_A_FACT_KEY = "not_a_fact"
NOT_A_FACT_SOURCES = ("api_demo", "own_capture")


def not_a_fact_lines(script, topics):
    """CF-0690: the record of the fact taken (`fact`) or the fact's
    `source_url` names one of the topic's `not_a_fact` pieces (by its id, its
    `url`), or the record's `source` is the factory's own (`api_demo`,
    `own_capture`). [] when not, or when the 01 is not there."""
    record = script.get(RECORD_FIELD)
    fact = script.get(FIELD)
    record = record if isinstance(record, dict) else {}
    fact = fact if isinstance(fact, dict) else {}
    said = []
    if record.get("source") in NOT_A_FACT_SOURCES:
        said.append(f"{RECORD_FIELD}.source is {record['source']!r}")
    topic = None
    if topics is not None:
        topic = next((t for t in topics if t.get("topic_id") == script.get("topic_id")), None)
    for piece in (topic or {}).get("support_text") or []:
        if not (isinstance(piece, dict) and piece.get(NOT_A_FACT_KEY) is True):
            continue
        marks = {piece.get("id"), piece.get("url")} - {None, ""}
        for name, value in ((f"{RECORD_FIELD}.url", record.get("url")),
                            (f"{RECORD_FIELD}.primary_url", record.get("primary_url")),
                            (f"{RECORD_FIELD}.source", record.get("source")),
                            (f"{FIELD}.source_url", fact.get("source_url"))):
            if isinstance(value, str) and value in marks:
                said.append(f"{name} is the piece {piece.get('id')} ({piece.get('kind')}, "
                            f"not_a_fact)")
    if not said:
        return []
    return [f"{RECORD_FIELD}: {NOT_A_FACT_RULE} - the video's own fact stands on the "
            f"factory's own record ({'; '.join(dict.fromkeys(said))}). A model's answer "
            f"through its API or what a recorded tool showed is never the story's fact: take "
            f"the fact from step 2's candidates of the channel's fact sources (CF-0690)"]


def batch_kinds(data, root=None):
    """The kinds of fact of the batch's channel - `kinds` of its fact-source
    list (CF-0628). The channel is the batch's `channel` field, a former id
    resolved; `root` is the factory whose `channels/` holds the list (default:
    this checkout's). Raises `channel_data.ChannelDataError` when the batch
    names no channel or the channel has no list: there is no default."""
    root = Path(root) if root else None
    return channel_data.fact_kinds(resolve_channel(data.get("channel"), root), root)


def check_batch_data(data, out=print, batch_dir=None, root=None):
    """The whole batch. Returns the problems, each prefixed with the script id.
    `batch_dir` (CF-0547): where `work/<slug>/words.json` is looked for - the
    WARN line then carries the seconds and the price. It is also where the
    01 is read for CF-0548 (the fact is about the script's scene). `root`:
    where the channel's kinds are read (`batch_kinds`)."""
    problems = []
    kinds = batch_kinds(data, root)
    terms = batch_terms(data, root)
    topics = hunter_topics(batch_dir)
    for s in data.get("scripts", []):
        sid = s.get("script_id")
        found = check_script(s, kinds, terms) + off_scene_lines(s, topics) \
            + not_a_fact_lines(s, topics)
        if found:
            out(f"  FAIL {sid}: {len(found)} problem(s)")
            problems += [f"{sid}: {p}" for p in found]
        else:
            fact = s[FIELD]
            shown = fact.get("on_screen") or fact.get("text")
            kind = (s.get(RECORD_FIELD) or {}).get("kind")
            out(f"  ok   {sid}: [{kind}] {shown[:fact_max_chars()]!r} <- {fact.get('source_url')}")
        if FACT_ANCHOR_MODE != "fail":
            lines = early_anchor_lines(s)
            words = words_of(batch_dir, s) if lines else None
            priced = f"; {price_line(fact_anchor_record(s, words))}" if words else ""
            for line in lines:
                out(f"  WARN {sid}: {line} [mode {FACT_ANCHOR_MODE}, a price not a "
                    f"refusal{priced}]")
    return problems


def check_batch(path, root=None):
    data = json.loads(Path(path).read_text())
    print(f"{path}: {len(data.get('scripts', []))} script(s); `{FIELD}` and `{RECORD_FIELD}` "
          f"required on each, `kind` one of the batch's channel's kinds, "
          f"on_screen budget {fact_max_chars()} chars")
    return check_batch_data(data, batch_dir=Path(path).resolve().parent, root=root)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--root", default=None,
                    help="the factory whose channels/<id>/fact-sources.json gives the "
                         "channel's kinds (default: this checkout's)")
    args = ap.parse_args(argv)
    try:
        problems = check_batch(args.batch_file, root=args.root)
    except channel_data.ChannelDataError as exc:
        print(f"check_production_fact.py: the batch's kinds of fact or its outlets' terms "
              f"cannot be had: {exc}",
              file=sys.stderr)
        return 2
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


@runlog.script("content-researcher", "check-production-fact", name="check_production_fact.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = at least one script is not
    ok, 2 = usage) is recorded as `failed` (CF-0107). The check is pure Python
    over the batch file: no external binary, no model call, so no `child`
    events. Without a batch (no RUNLOG_BATCH, no batch-shaped path) the
    library warns once on stderr and records nothing; the check itself is
    unchanged."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
