#!/usr/bin/env python3
"""CF-0552: every claim the viewer meets stands on a verbatim quote of the
topic's own text, or on a shot that is on screen under its words.

The defect (grill of 2026-10-05, CF-0546). Up to 1.8 the pipeline had no
source text, only headlines and RSS summaries, and the model filled the rest:
`coach-hale` 1313Z gave Mae to Anthony Hart, `harbourlights` 0701Z made Zorvath
the killer, and `east-of-eden` 0701Z said "months before anyone outside the
production knew ... before a single frame leaked" - while Variety had
announced the cast in September 2024, which was the video's own fact. CF-0551
gave every topic its text (`01 topics[].support_text[]`: the work's Wikipedia
article, its season's, the episode descriptions, the RSS summaries). This
module is the deterministic half of the rule the writer works under:

    script.claims[] = {"claim_id", "text", "where", "support": [...]}

* A claim (Q2) is anything checkable: who / what / when / how many, "first",
  "only", "nobody knew", "before". An exaggeration is a claim. Only an
  explicit opinion ("bold", "the best") is not one.
* `where` (Q4) is where the viewer meets it: `hook`, `commentary`, `payoff`
  (the narrator), `on_screen` (our wording on the frame -
  `production_fact.on_screen`), `title`, `description` (the publication;
  CF-0555 hands them to this check). `text` is the claim's words, verbatim
  from that field.
  CF-0689: `graphic:<graphic_id>` - a value on one of the script's own
  graphics (`graphics[]`, shared/own_graphic.py); its `text` is copied from
  that graphic's `own_graphic.viewer_text`, which `viewer_texts()` carries
  under that key. A graphic is neither the narrator nor the plate: it does
  not say whose a fact is (WHERE_ATTRIBUTION) nor carry the caveat.
  CF-0690: an `api_chat` graphic (a model's real answer through its API,
  shared/api_demo.py) is NOT a viewer text of this rule - the model's words
  on our record are never our fact (`not_a_fact`): `viewer_texts()` leaves it
  out (so no hedge, leak, caveat or attribution reading and nothing for the
  judge to extract), and a claim whose `where` is such a graphic is refused
  as `api_demo_answer_is_fact` (API_DEMO_CODES - outside FAIL_CODES, the
  claim-backed codes the writer's skill lists).
* `support` is one or more footings:
    `{"source": "<support_text id>", "quote": "<verbatim>"}` - the quote is in
      that piece of the topic's support_text, word for word (spaces, quote
      marks, dashes and case are normalised; nothing else is);
    `{"shot_id": "<video_id>:<index>"}` (Q8) - a claim about what is visible:
      the shot is one of the topic's pool (its Indexer description goes into
      the report - it supports what is visible, never a reading of it), and
      once the Editor's plan exists (step 6b), that shot is in a block under
      the claim's words.
* Q3: nothing is said "reportedly", "rumoured", "allegedly" - a sentence of
  any viewer text with such a word is a violation whether it is declared or
  not; the honest move is to drop the sentence.
* CF-0660 (grill «Каналы ИИ и Наука» Q14): a video whose fact stands on a
  preprint - the script's `fact` record says `needs_caveat: true`, set by
  `fact_rule.check_candidate` for an outlet flagged `preprint` - says so: its
  narration (hook / commentary / payoff) or its plate (`on_screen`) carries
  "not peer-reviewed" or one of its forms (CAVEAT_PATTERNS, English and
  Russian). Without it the script fails `preprint_without_caveat`; the word
  "preprint" alone is not the caveat.
* CF-0566 (the same grill, Q17, ExampleTech): two more rules a channel's
  fact-sources list switches on through the script's `fact` record
  (`fact_rule.check_candidate` sets the flags):
  - `needs_attribution: true` - the fact is its owner's claim (a vendor's
    benchmark, the list's `attributed_kinds`): the narration or the plate says
    whose it is in one sentence - the fact's `source` (or `attribution`, or a
    word of either) beside "according to", "says", "claims", "reports", "по
    данным", "по словам", "заявляет" (ATTRIBUTION_MARKERS), or right after
    "per" ("per Google"). Without it:
    `fact_without_attribution`.
  - `leaks_need_source: true` - a sentence of any viewer text that tells a
    leak ("leak", "leaked", "утечка", "слили" - LEAK_RE) names who reported it
    in that sentence: "according to The Verge", "as The Verge reported", "The
    Verge reports", "по данным The Verge", "как пишет The Verge" (SOURCED_RES).
    Without it: `leak_without_source`. Hearsay with no one behind it ("Apple
    is said to", "говорят") is `hedged_statement` on every channel already.

What this does not judge: whether the quote *says* the claim (entailment -
CF-0553, an independent model), and whether the writer declared every claim
(CF-0553's own extraction of the finished text). The report is built for that
loop: every support comes back with what the judge needs - the quote and the
paragraph around it, or the shot's description - and every violation with the
edit it asks for (FIXES).

Stdlib only, no network, loadable by path from any repository (CF-0231).
Command line (read-only, never writes the 03):

    python3 shared/factrule/claims.py <03-content-researcher.json>
        [--script-id ID] [--title T] [--description D] [--json]

exit 0 every script passes, 1 a violation, 3 the question could not be put.
"""
import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

RULE = "CF-0552"
CLAIMS_FIELD = "claims"
# The record CF-0553's loop writes on the script; named here so both sides
# spell it once.
CHECK_FIELD = "claims_check"

WHERE_SPOKEN = ("hook", "commentary", "payoff")
WHERE_ON_SCREEN = "on_screen"
WHERE_TITLE = "title"
WHERE_DESCRIPTION = "description"
WHERES = WHERE_SPOKEN + (WHERE_ON_SCREEN, WHERE_TITLE, WHERE_DESCRIPTION)
# CF-0689: a claim on one of the script's own graphics says
# `where: "graphic:<graphic_id>"` (= own_graphic.WHERE_PREFIX); not one of
# WHERES - a family of fields, one per graphic of `graphics[]`.
WHERE_GRAPHIC_PREFIX = "graphic:"
GRAPHICS_FIELD = "graphics"                 # = own_graphic.GRAPHICS_FIELD
GRAPHIC_WHERE_RE = re.compile(r"^graphic:[a-z0-9][a-z0-9_-]*$")
# Where the field's text comes from on a script: `production_fact.on_screen`
# is the only wording on the frame the writer authors. Title and description
# are not in 03 - the caller hands them in (CF-0555).
GIVEN_BY_CALLER = (WHERE_TITLE, WHERE_DESCRIPTION)

CLAIM_KEYS = ("claim_id", "text", "where", "support")
CLAIM_OPTIONAL_KEYS = ()
SUPPORT_QUOTE_KEYS = ("source", "quote")
SUPPORT_SHOT_KEYS = ("shot_id",)
CLAIM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHOT_ID_RE = re.compile(r"^\S+:\d+$")
# A quote has to carry a statement, not a name: under three words it is a
# keyword hit, and whatever it "supports" is the writer's reading.
QUOTE_MIN_WORDS = 3

SUPPORT_OK_STATE = "ok"          # = trend-hunter support_text.STATE_OK

FAIL_MISSING = "claims_missing"
FAIL_MALFORMED = "claim_malformed"
FAIL_TEXT_NOT_IN_FIELD = "claim_text_not_in_field"
FAIL_TOPIC_WITHOUT_TEXT = "topic_without_support_text"
FAIL_SOURCE_UNKNOWN = "source_not_in_support_text"
FAIL_QUOTE_NOT_IN_SOURCE = "quote_not_in_source"
FAIL_QUOTE_TOO_SHORT = "quote_too_short"
FAIL_SHOT_NOT_IN_POOL = "shot_not_in_pool"
FAIL_SHOT_NOT_SPOKEN = "shot_support_not_spoken"
FAIL_SHOT_NOT_UNDER_WORDS = "shot_not_under_words"
FAIL_SHOT_UNLOCATED = "shot_placement_unknown"
FAIL_HEDGED = "hedged_statement"
FAIL_PREPRINT_WITHOUT_CAVEAT = "preprint_without_caveat"   # CF-0660
FAIL_FACT_WITHOUT_ATTRIBUTION = "fact_without_attribution"  # CF-0566
FAIL_LEAK_WITHOUT_SOURCE = "leak_without_source"            # CF-0566
# CF-0690: a claim on an `api_chat` graphic - the model's answer is never our
# fact. = api_demo.FAIL_ANSWER_IS_FACT; kept out of FAIL_CODES (its fix and
# words are API_DEMO_FIXES / API_DEMO_REFUSALS_RU).
FAIL_API_DEMO_IS_FACT = "api_demo_answer_is_fact"
API_DEMO_CODES = (FAIL_API_DEMO_IS_FACT,)
API_CHAT_TEMPLATE = "api_chat"              # = own_graphic.API_CHAT
FAIL_CODES = (FAIL_MISSING, FAIL_MALFORMED, FAIL_TEXT_NOT_IN_FIELD, FAIL_TOPIC_WITHOUT_TEXT,
              FAIL_SOURCE_UNKNOWN, FAIL_QUOTE_NOT_IN_SOURCE, FAIL_QUOTE_TOO_SHORT,
              FAIL_SHOT_NOT_IN_POOL, FAIL_SHOT_NOT_SPOKEN, FAIL_SHOT_NOT_UNDER_WORDS,
              FAIL_SHOT_UNLOCATED, FAIL_HEDGED, FAIL_PREPRINT_WITHOUT_CAVEAT,
              FAIL_FACT_WITHOUT_ATTRIBUTION, FAIL_LEAK_WITHOUT_SOURCE)

# CF-0660: the script's fact record (`fact` of 03 = fact_rule.fact_record(),
# CR's check_production_fact.RECORD_FIELD) and its flag
# (= fact_rule.NEEDS_CAVEAT_KEY): the fact stands on a preprint.
FACT_RECORD_FIELD = "fact"
NEEDS_CAVEAT_KEY = "needs_caveat"
# Where the caveat may be said: the narrator or the plate - not the title or
# the description, which are not the video.
WHERE_CAVEAT = WHERE_SPOKEN + (WHERE_ON_SCREEN,)
# The caveat, matched on `norm()`ed text (case folded, dashes one hyphen, an
# apostrophe inside a word kept). The one list: «not peer-reviewed» and its
# forms («not yet», «has not been», «hasn't been», «yet to be», «non-»), and
# the Russian «не рецензирован(а)», «ещё не прошло рецензирование», «без
# рецензирования», «нерецензированный». «preprint» / «препринт» alone is not
# one - a viewer is not expected to know what it means.
CAVEAT_PATTERNS = (
    r"\bnot\s+(?:yet\s+)?(?:been\s+)?peer-?\s?reviewed\b",
    r"n't\s+(?:yet\s+)?(?:been\s+)?peer-?\s?reviewed\b",
    r"\byet\s+to\s+be\s+peer-?\s?reviewed\b",
    r"\bnon-?\s?peer-?\s?reviewed\b",
    r"\bне\s+(?:(?:ещё|еще|пока)\s+)?рецензир",
    r"\bне\s+(?:(?:ещё|еще|пока)\s+)?прош(?:ло|ла|ли|ел|ёл)\s+(?:\w+\s+)?рецензи",
    r"\bбез\s+рецензи",
    r"\bнерецензир",
)
_CAVEAT_RES = tuple(re.compile(p) for p in CAVEAT_PATTERNS)

# CF-0566: the flags of the fact record (= fact_rule.NEEDS_ATTRIBUTION_KEY,
# fact_rule.LEAKS_NEED_SOURCE_KEY) and the words the two rules read, matched
# on `norm()`ed text. Whose claim it is: one of these in the sentence that
# names the owner.
NEEDS_ATTRIBUTION_KEY = "needs_attribution"
LEAKS_NEED_SOURCE_KEY = "leaks_need_source"
WHERE_ATTRIBUTION = WHERE_SPOKEN + (WHERE_ON_SCREEN,)
ATTRIBUTION_MARKERS = (
    r"\baccording to\b", r"\bsays?\b", r"\bsaid\b", r"\bclaims?\b",
    r"\bclaimed\b", r"\breports?\b", r"\breported\b", r"\bstates?\b", r"\bstated\b",
    r"\bmeasured\b", r"\bown (?:numbers|figures|tests?|benchmarks?|testing|data)\b",
    r"\bпо данным\b", r"\bпо словам\b", r"\bпо заявлению\b", r"\bпо собственным\b",
    r"\bпо (?:его|её|ее|их) (?:данным|словам|замерам|тестам)\b",
    r"\bзаявля\w*", r"\bзаявил\w*", r"\bутвержда\w*", r"\bсообща\w*", r"\bсообщил\w*",
)
_ATTRIBUTION_RES = tuple(re.compile(p) for p in ATTRIBUTION_MARKERS)
# A leak told by the video: the English word family and the Russian
# «утечка», «слив», «слили», «слитые» (not «сливаться» - merge).
LEAK_RE = re.compile(r"\bleak(?:s|ed|ing|er|ers)?\b|\bутечк\w*|\bслив\b|\bслил[аио]?\b|"
                     r"\bслит\w*")
# Who reported it, named in the sentence: "according to X", "reported by X",
# "as X reported / reports / wrote", "X reports / reported / writes / wrote"
# (not "was reported" - nobody), and the Russian «по данным X», «по словам X»,
# «по информации X», «как пишет / сообщает X», «X сообщает / пишет».
_PASSIVE = r"(?<!\bwas )(?<!\bwere )(?<!\bis )(?<!\bare )(?<!\bbeen )(?<!\bbe )(?<!\bbeing )"
SOURCED_PATTERNS = (
    r"\baccording to [^\s,.;:]+",
    r"\breported by [^\s,.;:]+",
    r"\bas [^\s,.;:]+(?: [^\s,.;:]+){0,3} (?:first )?(?:reported|reports|wrote|writes|revealed)\b",
    r"\b[^\s,.;:]+ " + _PASSIVE + r"(?:first )?(?:reported|reports|wrote|writes|revealed)\b",
    r"\bпо (?:данным|словам|информации|сведениям) [^\s,.;:]+",
    r"\bкак (?:пишет|писал[аи]?|сообщает|сообщил[аи]?|написал[аи]?) [^\s,.;:]+",
    r"\b[^\s,.;:]+ (?:сообщает|сообщил[аи]?|пишет|написал[аи]?)\b",
)
_SOURCED_RES = tuple(re.compile(p) for p in SOURCED_PATTERNS)
# A word that stands before "reported" without naming anyone.
_NOBODY = frozenset("was were is are been be being it that this which who and or but "
                    "first widely also".split())

# Not a violation: a part of the rule that cannot be judged yet, and says why.
PENDING_FIELD_NOT_GIVEN = "field_not_given"      # title / description not handed in
PENDING_NO_PLAN = "no_plan"                      # before step 6b: no block exists yet
PENDING_POOL_NOT_READ = "pool_not_read"          # no shots index to look the shot up in
PENDING_CODES = (PENDING_FIELD_NOT_GIVEN, PENDING_NO_PLAN, PENDING_POOL_NOT_READ)

ACTION_PASS = "pass"
ACTION_FAIL = "fail"
STATE_OK, STATE_FAIL, STATE_PENDING = "ok", "fail", "pending"

PLACED_UNDER = "under_words"
PLACED_ELSEWHERE = "not_under_words"
PLACED_UNLOCATED = "unlocated"

# What each violation asks of the writer - one edit, printed beside it.
FIXES = {
    FAIL_MISSING: "write `claims` on the script - one entry per checkable statement the viewer "
                  "meets (`[]` only when it says nothing checkable)",
    FAIL_MALFORMED: "a claim is {claim_id, text, where: hook|commentary|payoff|on_screen|title|"
                    "description|graphic:<graphic_id>, support: [{source, quote} | {shot_id}, "
                    "...]}",
    FAIL_TEXT_NOT_IN_FIELD: "`text` must be copied verbatim from the field `where` names",
    FAIL_TOPIC_WITHOUT_TEXT: "the topic has no support text (Wikipedia was not reachable or "
                             "gave nothing) - no claim can stand, the topic is refused",
    FAIL_SOURCE_UNKNOWN: "`source` must be the `id` of a piece of the topic's support_text "
                         "in 01-trend-hunter.json (or of its continuation "
                         "01-scale-support.json - a scale stand-in's page, CF-0673)",
    FAIL_QUOTE_NOT_IN_SOURCE: "the quote is not in that piece word for word - copy it from the "
                              "text (no paraphrase, no splice with '...'), or drop the claim",
    FAIL_QUOTE_TOO_SHORT: f"a quote of under {QUOTE_MIN_WORDS} words is a keyword, not a "
                          f"statement - quote the sentence that says it",
    FAIL_SHOT_NOT_IN_POOL: "`shot_id` must be `<video_id>:<index>` of a shot of this topic's "
                           "pool (its shots.json)",
    FAIL_SHOT_NOT_SPOKEN: "a shot backs only a spoken claim (hook / commentary / payoff) - "
                          "the shot has to be on screen under its words",
    FAIL_SHOT_NOT_UNDER_WORDS: "the plan puts another picture under these words - anchor that "
                               "shot to them (a `visual_anchors` phrase of it on these words), "
                               "or say only what the shot under them shows, or drop the claim",
    FAIL_SHOT_UNLOCATED: "the claim's words could not be found in the voice's alignment - make "
                         "`text` a verbatim stretch of the spoken words",
    FAIL_HEDGED: "\"reportedly\", \"rumoured\", \"allegedly\" do not make a statement safe "
                 "(Q3) - say it with a quote, or drop the sentence",
    FAIL_PREPRINT_WITHOUT_CAVEAT: "the video's fact stands on a preprint (`fact.needs_caveat`) - "
                                  "say in the narration or on the plate (`on_screen`) that it "
                                  "is not peer-reviewed (\"a preprint, not yet peer-reviewed\"), "
                                  "or take a peer-reviewed fact",
    FAIL_FACT_WITHOUT_ATTRIBUTION: "the video's fact is its owner's own claim "
                                   "(`fact.needs_attribution` - a vendor's benchmark): say "
                                   "whose it is in the sentence that gives it, in the "
                                   "narration or on the plate (\"according to Google, it "
                                   "scores 87%\", \"по данным Google\"), or take a fact "
                                   "that is not a claim",
    FAIL_LEAK_WITHOUT_SOURCE: "a leak is told only as the report of the outlet that "
                              "published it: name it in the same sentence (\"according to "
                              "The Verge, ...\", \"as The Verge reported\"), or drop the "
                              "sentence",
}

# CF-0660: what each violation means, in Russian, for a person (the command
# center) - one row per code, as acceptance.REFUSALS_RU (CF-0676) and
# validate_inserts.CHECK_REASONS_RU (CF-0657) do for theirs. Every violation
# carries its line as `text_ru`; the English `fix` stays what it was.
REFUSALS_RU = {
    FAIL_MISSING: "У сценария нет списка утверждений (`claims`) - не на чем проверить, "
                  "на чём стоит каждое.",
    FAIL_MALFORMED: "Утверждение записано не по форме: нужны id, текст, место в ролике и опора.",
    FAIL_TEXT_NOT_IN_FIELD: "Текста утверждения нет дословно в том поле ролика, на которое "
                            "оно ссылается.",
    FAIL_TOPIC_WITHOUT_TEXT: "У темы нет опорного текста (Википедия не ответила или ничего не "
                             "дала) - ни одно утверждение не устоит, тема снимается.",
    FAIL_SOURCE_UNKNOWN: "Утверждение ссылается на кусок опорного текста, которого у темы нет.",
    FAIL_QUOTE_NOT_IN_SOURCE: "Цитаты нет в источнике слово в слово - пересказ или склейка "
                              "опорой не считаются.",
    FAIL_QUOTE_TOO_SHORT: f"Цитата короче {QUOTE_MIN_WORDS} слов - это ключевое слово, "
                          f"а не утверждение.",
    FAIL_SHOT_NOT_IN_POOL: "Кадр, на который опирается утверждение, не из футажа темы.",
    FAIL_SHOT_NOT_SPOKEN: "Кадр подтверждает только сказанное голосом, а не плашку, "
                          "название или описание.",
    FAIL_SHOT_NOT_UNDER_WORDS: "Под словами утверждения в плане монтажа стоит другой кадр.",
    FAIL_SHOT_UNLOCATED: "Слов утверждения нет в разметке озвучки - не понять, какой кадр "
                         "под ними.",
    FAIL_HEDGED: "«По слухам», «якобы», «reportedly» не делают утверждение безопасным - "
                 "нужна цитата, иначе фразу убрать.",
    FAIL_PREPRINT_WITHOUT_CAVEAT: "Факт ролика взят из препринта, а в ролике нигде не сказано, "
                                  "что работа не рецензирована - нужна оговорка «not "
                                  "peer-reviewed» в закадре или на плашке.",
    FAIL_FACT_WITHOUT_ATTRIBUTION: "Факт ролика - заявление его владельца (бенчмарк вендора), "
                                   "а в ролике не сказано, чьё оно - нужно «по данным X» "
                                   "в закадре или на плашке.",
    FAIL_LEAK_WITHOUT_SOURCE: "Ролик рассказывает об утечке, не называя издание, которое о "
                              "ней сообщило, - нужно «по данным The Verge…» в той же фразе, "
                              "иначе фразу убрать.",
}

# Q3: the words that pass a statement off as hearsay.
HEDGE_WORDS = ("rumor", "rumors", "rumored", "rumour", "rumours", "rumoured",
               "reportedly", "allegedly", "supposedly", "purportedly", "unconfirmed")
HEDGE_PHRASES = ("word is", "sources say", "insiders say", "it is said", "it's said",
                 "is said to", "are said to", "rumor has it", "rumour has it",
                 "по слухам", "якобы", "говорят")

# ------------------------------------------------------------- normalising
_QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
           "`": "'", "´": "'",
           "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
           "«": '"', "»": '"'}
_DASHES = "‐‑‒–—―−⸺⸻﹘﹣－"
_INVISIBLE = "­​‌‍⁠﻿"
_TRANS = {ord(k): v for k, v in _QUOTES.items()}
_TRANS.update({ord(c): "-" for c in _DASHES})
_TRANS.update({ord(c): None for c in _INVISIBLE})
_DASH_SPACE_RE = re.compile(r"\s*-\s*")
_SPACE_RE = re.compile(r"\s+")
# Quotation marks go: single or double, curly or straight, a quote inside a
# quote is the same words. An apostrophe inside a word (it's) stays.
_QUOTE_MARK_RE = re.compile(r"\"|(?<!\w)'|'(?!\w)")
_EDGE_PUNCT = " \t\n\"'.,;:!?"
_WORD_RE = re.compile(r"[a-z0-9À-ɏЀ-ӿ]+(?:'[a-z0-9À-ɏЀ-ӿ]+)*")


def norm(text):
    """What two copies of one sentence have in common: Unicode compatibility
    form, curly quotes straight, every dash a hyphen with no space around it,
    the ellipsis as three dots, invisible characters out, runs of white space
    one space, case folded, quotation marks out (single or double - a quote
    inside a quote is the same words; an apostrophe inside a word stays).
    Words and their order are untouched - that is what "verbatim" keeps."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_TRANS).replace("…", "...")
    text = _QUOTE_MARK_RE.sub("", text)
    text = _DASH_SPACE_RE.sub("-", text)
    return _SPACE_RE.sub(" ", text).strip().casefold()


def norm_quote(quote):
    """The quote as it is looked for: normalised, the sentence's end
    punctuation off."""
    return norm(quote).strip(_EDGE_PUNCT)


def words(text):
    return _WORD_RE.findall(norm(text))


# ------------------------------------------------------------------ inputs
def is_graphic_where(where):
    """CF-0689: is this `where` a graphic of the script (`graphic:<id>`)?"""
    return isinstance(where, str) and bool(GRAPHIC_WHERE_RE.match(where))


OWN_GRAPHIC_PATH = Path(__file__).resolve().parents[1] / "own_graphic.py"
_OWN_GRAPHIC = []


def own_graphic_module():
    """shared/own_graphic.py beside this package, loaded by path once (it
    loads this file for its normalising - so only when a script has
    graphics), or None when the checkout has none: a graphic then has no
    text, and every claim on it fails `claim_text_not_in_field`."""
    if not _OWN_GRAPHIC:
        mod = None
        if OWN_GRAPHIC_PATH.is_file():
            spec = importlib.util.spec_from_file_location("_own_graphic_for_claims",
                                                          OWN_GRAPHIC_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        _OWN_GRAPHIC.append(mod)
    return _OWN_GRAPHIC[0]


def api_chat_wheres(script):
    """CF-0690: the `graphic:<graphic_id>` of every `api_chat` graphic of the
    script - a model's answer on our record, never a viewer text of this rule."""
    out = set()
    graphics = (script or {}).get(GRAPHICS_FIELD)
    for g in graphics if isinstance(graphics, list) else []:
        if isinstance(g, dict) and g.get("template") == API_CHAT_TEMPLATE \
                and isinstance(g.get("graphic_id"), str):
            out.add(WHERE_GRAPHIC_PREFIX + g["graphic_id"])
    return out


def viewer_texts(script, extra=None):
    """{where: text} of everything the viewer meets that the script writes;
    `extra` adds what is not in 03 (title, description - CF-0555); CF-0689:
    each of the script's own graphics under `graphic:<graphic_id>` - except
    an `api_chat` (CF-0690): the model's words are not the script's."""
    s = script or {}
    out = {w: s.get(w) for w in WHERE_SPOKEN if isinstance(s.get(w), str)}
    pf = s.get("production_fact")
    if isinstance(pf, dict) and isinstance(pf.get("on_screen"), str) and pf["on_screen"].strip():
        out[WHERE_ON_SCREEN] = pf["on_screen"]
    if isinstance(s.get(GRAPHICS_FIELD), list) and s[GRAPHICS_FIELD]:
        og = own_graphic_module()
        if og is not None:
            chats = api_chat_wheres(s)
            out.update({w: t for w, t in og.viewer_texts(s).items() if w not in chats})
    for k, v in (extra or {}).items():
        if k in GIVEN_BY_CALLER and isinstance(v, str) and v.strip():
            out[k] = v
    return out


def support_pieces(topic):
    """{id: piece} of the topic's support_text."""
    return {p.get("id"): p for p in (topic or {}).get("support_text") or []
            if isinstance(p, dict) and p.get("id")}


def topic_has_text(topic):
    check = (topic or {}).get("support_check") or {}
    return bool(support_pieces(topic)) and check.get("state", SUPPORT_OK_STATE) == SUPPORT_OK_STATE


def pool_from_indexes(paths):
    """{shot_id: description} out of the Indexer's `<video_id>.shots.json`
    files - the id is the Editor's (`build_render_plan`'s `shot`)."""
    pool = {}
    for p in paths or []:
        p = Path(p)
        if not p.is_file():
            continue
        video_id = p.name[:-len(".shots.json")] if p.name.endswith(".shots.json") else p.stem
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shots = data.get("shots") if isinstance(data, dict) else data
        for shot in shots or []:
            if isinstance(shot, dict) and isinstance(shot.get("index"), int):
                pool[f"{video_id}:{shot['index']}"] = shot.get("description") or ""
    return pool


# ------------------------------------------------------------------ quotes
def quote_context(piece_text, quote_n, width=600):
    """The paragraph of the piece the quote stands in (CF-0553's judge reads
    the pair claim-quote with the paragraph around it), at most `width`
    characters either side of it."""
    for para in re.split(r"\n\s*\n|\n", piece_text or ""):
        np_ = norm(para)
        at = np_.find(quote_n)
        if at >= 0:
            if len(para) <= 2 * width + len(quote_n):
                return para.strip()
            return np_[max(0, at - width):at + len(quote_n) + width]
    whole = norm(piece_text)
    at = whole.find(quote_n)
    return whole[max(0, at - width):at + len(quote_n) + width] if at >= 0 else None


HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")


def quote_section(piece_text, quote_n):
    """The heading path the quote stands under ("Reception > Critical response
    > Season 1"), or None. CF-0556: plain_article keeps the headings as their
    own lines and the paragraph around a quote does not carry them - the
    exam's Coach Hale "Season 1 scored 92% on Rotten Tomatoes" was `not_enough`
    because "Season 1" was the heading above the paragraph, not in it."""
    path = []
    for line in (piece_text or "").splitlines():
        m = HEADING_RE.match(line.strip())
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2))]
            continue
        if quote_n in norm(line):
            return " > ".join(t for _, t in path) or None
    return None


def judge_quote(support, pieces):
    """(record, violation_code_or_None) for one `{source, quote}`."""
    piece = pieces.get(support.get("source"))
    quote = support.get("quote")
    rec = {"kind": "quote", "source": support.get("source"), "quote": quote,
           "url": None, "revision_id": None, "piece_kind": None, "found": False,
           "context": None}
    if piece is None:
        return rec, FAIL_SOURCE_UNKNOWN
    rec.update(url=piece.get("url"), revision_id=piece.get("revision_id"),
               piece_kind=piece.get("kind"))
    if piece.get("fetched_at"):
        rec["fetched_at"] = piece["fetched_at"]     # CF-0636: a TVmaze text has no revision
    if len(words(quote)) < QUOTE_MIN_WORDS:
        return rec, FAIL_QUOTE_TOO_SHORT
    q = norm_quote(quote)
    body = quotable_text(piece)
    if not q or q not in norm(body):
        return rec, FAIL_QUOTE_NOT_IN_SOURCE
    rec["found"] = True
    rec["context"] = quote_context(body, q)
    section = quote_section(body, q)
    if section:
        rec["section"] = section
    return rec, None


RSS_KIND = "rss_summary"            # = trend-hunter support_text.KIND_RSS
# CF-0636: an episode description read from the TVmaze API
# (`shared/tvmaze/tvmaze_api.py`, `episode_piece`): quotable like any piece -
# its `text` is the summary, its `title` the episode's name (not text, as a
# Wikipedia episode row's) - and a second source for a fresh reveal
# (`claim_judge.SECOND_SOURCE_KINDS`).
TVMAZE_KIND = "tvmaze_episode"      # = shared/tvmaze/tvmaze_api.KIND_EPISODE
# CF-0637: one Wikidata statement as one English sentence
# (`shared/wikidata/wikidata_api.py`, `statement_piece`: "Kelly Macdonald is in
# the cast of Harbourlights as Kerry Kane.") - quotable like any piece (its `text` is
# the sentence, its `title` "<work> - <property>" is not text), its record
# carries the item's revision; it is never a reveal's second source
# (`claim_judge.SECOND_SOURCE_KINDS`) and its quote is not aged - Wikidata
# says who and when, never what happened in a story.
WIKIDATA_KIND = "wikidata_statement"  # = shared/wikidata/wikidata_api.KIND_STATEMENT


def quotable_text(piece):
    """The words a quote may come from. A news piece is its headline AND its
    summary (CF-0556: a batch whose RSS index kept no summary - 1313Z's
    Rennick, "Gets Early Season 6 Renewal ... With 66M Viewers In 28 Days" -
    otherwise has nothing to quote at all; CF-0551 hands the headline in as
    the piece's `title`). A Wikipedia piece's title is a page name, not text."""
    text = piece.get("text") or ""
    if piece.get("kind") == RSS_KIND and piece.get("title"):
        return f"{piece['title']}\n\n{text}" if text else piece["title"]
    return text


# ------------------------------------------------------------------- shots
def plan_blocks(plan):
    """[{index, start, end, shots}] of the Editor's plan: a block's own shot,
    its cuts' and its swing shots."""
    out = []
    for i, b in enumerate((plan or {}).get("blocks") or []):
        if not isinstance(b, dict):
            continue
        shots = [b.get("shot")] + [c.get("shot") for c in b.get("cuts") or []
                                   if isinstance(c, dict)] + list(b.get("swing_block_shots") or [])
        out.append({"index": i, "start": b.get("start"), "end": b.get("end"),
                    "shots": sorted({s for s in shots if isinstance(s, str)})})
    return out


def _alignment_tokens(aligned):
    tokens, owner = [], []
    for i, w in enumerate(aligned or []):
        for t in words((w or {}).get("word")):
            tokens.append(t)
            owner.append(i)
    return tokens, owner


def locate_span(script, where, text, aligned):
    """(start_s, end_s) of the claim's words in the voice's alignment, or None.

    The voice reads hook + commentary + payoff in that order; the expected
    position of the words is the tokens before them, and it only breaks a tie
    between two equal windows (a payoff echoes the hook)."""
    field = (script or {}).get(where)
    if not isinstance(field, str):
        return None
    before = 0
    for w in WHERE_SPOKEN:
        if w == where:
            break
        before += len(words((script or {}).get(w)))
    at = norm(field).find(norm(text))
    expected = before + (len(words(norm(field)[:at])) if at >= 0 else 0)
    target = words(text)
    tokens, owner = _alignment_tokens(aligned)
    n = len(target)
    if not n or len(tokens) < n:
        return None
    best = None
    for k in range(len(tokens) - n + 1):
        window = tokens[k:k + n]
        hits = sum(1 for a, b in zip(window, target) if a == b)
        key = (hits, -abs(k - expected))
        if best is None or key > best[0]:
            best = (key, k)
    (hits, _), k = best
    if hits < max(1, round(0.8 * n)):
        return None
    first, last = aligned[owner[k]], aligned[owner[k + n - 1]]
    return first.get("start"), last.get("end")


def judge_shot(support, claim, script, pool, plan):
    """(record, violation_or_None, pending_or_None) for one `{shot_id}`."""
    shot_id = support.get("shot_id")
    rec = {"kind": "shot", "shot_id": shot_id, "description": None, "in_pool": None,
           "placement": None, "blocks": []}
    if claim.get("where") not in WHERE_SPOKEN:
        return rec, FAIL_SHOT_NOT_SPOKEN, None
    if pool is None:
        return rec, None, PENDING_POOL_NOT_READ
    rec["in_pool"] = shot_id in pool
    if not rec["in_pool"]:
        return rec, FAIL_SHOT_NOT_IN_POOL, None
    rec["description"] = pool[shot_id]
    if plan is None:
        return rec, None, PENDING_NO_PLAN
    span = locate_span(script, claim["where"], claim["text"], plan.get("words"))
    if span is None or None in span:
        rec["placement"] = PLACED_UNLOCATED
        return rec, FAIL_SHOT_UNLOCATED, None
    start, end = span
    under = [b for b in plan_blocks(plan)
             if isinstance(b["start"], (int, float)) and isinstance(b["end"], (int, float))
             and b["start"] < end and b["end"] > start]
    rec["blocks"] = [{"index": b["index"], "start": b["start"], "end": b["end"],
                      "shots": b["shots"]} for b in under]
    if any(shot_id in b["shots"] for b in under):
        rec["placement"] = PLACED_UNDER
        return rec, None, None
    rec["placement"] = PLACED_ELSEWHERE
    return rec, FAIL_SHOT_NOT_UNDER_WORDS, None


# ------------------------------------------------------------------- hedges
def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def hedges_in(text):
    """The hearsay words of one sentence (Q3)."""
    toks = set(words(text))
    n = " " + " ".join(words(text)) + " "
    found = [w for w in HEDGE_WORDS if w in toks]
    found += [p for p in HEDGE_PHRASES if " " + " ".join(words(p)) + " " in n]
    return found


# ------------------------------------------------------------------- shape
def shape_problems(claim):
    """What is wrong with one claim's shape, as sentences; [] when well formed."""
    if not isinstance(claim, dict):
        return [f"not an object: {claim!r}"]
    out = []
    missing = [k for k in CLAIM_KEYS if k not in claim]
    if missing:
        out.append(f"missing {missing}")
    extra = sorted(set(claim) - set(CLAIM_KEYS) - set(CLAIM_OPTIONAL_KEYS))
    if extra:
        out.append(f"unknown key(s) {extra}")
    cid = claim.get("claim_id")
    if "claim_id" in claim and not (isinstance(cid, str) and CLAIM_ID_RE.match(cid)):
        out.append(f"claim_id {cid!r} is not [a-z0-9][a-z0-9_-]*")
    if "text" in claim and not (isinstance(claim["text"], str) and claim["text"].strip()):
        out.append("text must be a non-empty string")
    if "where" in claim and claim["where"] not in WHERES and not is_graphic_where(claim["where"]):
        out.append(f"where {claim['where']!r} is not one of {list(WHERES)} or "
                   f"graphic:<graphic_id>")
    sup = claim.get("support")
    if "support" in claim:
        if not isinstance(sup, list) or not sup:
            out.append("support must be a non-empty list - a claim without a footing is "
                       "not written (Q3)")
        else:
            for j, s in enumerate(sup):
                keys = set(s) if isinstance(s, dict) else None
                if keys == set(SUPPORT_QUOTE_KEYS):
                    if not all(isinstance(s[k], str) and s[k].strip() for k in SUPPORT_QUOTE_KEYS):
                        out.append(f"support[{j}]: source and quote must be non-empty strings")
                elif keys == set(SUPPORT_SHOT_KEYS):
                    if not (isinstance(s["shot_id"], str) and SHOT_ID_RE.match(s["shot_id"])):
                        out.append(f"support[{j}]: shot_id {s['shot_id']!r} is not "
                                   f"<video_id>:<index>")
                else:
                    out.append(f"support[{j}]: exactly {{source, quote}} or {{shot_id}}, "
                               f"got {s!r}")
    return out


# ------------------------------------------------------------------- check
def has_caveat(text):
    """Does this text say the work is not peer-reviewed (CAVEAT_PATTERNS)?"""
    low = norm(text)
    return any(rx.search(low) for rx in _CAVEAT_RES)


def needs_caveat(script):
    """CF-0660: does the script's fact stand on a preprint? Its `fact` record
    says so (`needs_caveat: true`, from the fact rule's check)."""
    fact = (script or {}).get(FACT_RECORD_FIELD)
    return isinstance(fact, dict) and fact.get(NEEDS_CAVEAT_KEY) is True


def caveat_problem(script, texts):
    """The `preprint_without_caveat` violation of a script, or None: a fact
    that needs the caveat and no narration or plate of the video says it."""
    if not needs_caveat(script):
        return None
    if any(has_caveat(texts.get(w)) for w in WHERE_CAVEAT if texts.get(w)):
        return None
    fact = script.get(FACT_RECORD_FIELD) or {}
    return _violation(FAIL_PREPRINT_WITHOUT_CAVEAT,
                      detail=f"the fact stands on {fact.get('primary_url') or fact.get('url')} "
                             f"and none of {', '.join(WHERE_CAVEAT)} says it is not "
                             f"peer-reviewed", where=None)


def _fact_flag(script, key):
    fact = (script or {}).get(FACT_RECORD_FIELD)
    return isinstance(fact, dict) and fact.get(key) is True


def owner_names(fact):
    """CF-0566: the names that say whose claim a fact is - its `source` and its
    `attribution` whole, and each word of three letters or more of either
    ("Google DeepMind" -> "google deepmind", "google", "deepmind"), normed."""
    out = []
    for field in ("source", "attribution"):
        name = norm((fact or {}).get(field) or "").strip(_EDGE_PUNCT)
        if not name:
            continue
        out.append(name)
        out += [w for w in _WORD_RE.findall(name) if len(w) >= 3]
    return list(dict.fromkeys(out))


def is_attributed_to(sentence, names):
    """Does this sentence name one of `names` and say it is their claim?"""
    n = norm(sentence)
    named = [name for name in names
             if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", n)]
    if not named:
        return False
    # "per Google" names the owner; a bare "per" is "per second"
    if any(re.search(r"\bper " + re.escape(name) + r"(?!\w)", n) for name in named):
        return True
    return any(rx.search(n) for rx in _ATTRIBUTION_RES)


def attribution_problem(script, texts):
    """The `fact_without_attribution` violation of a script, or None: a fact
    that is its owner's claim and no sentence of the narration or the plate
    says whose it is."""
    if not _fact_flag(script, NEEDS_ATTRIBUTION_KEY):
        return None
    fact = script.get(FACT_RECORD_FIELD) or {}
    names = owner_names(fact)
    for where in WHERE_ATTRIBUTION:
        if any(is_attributed_to(sent, names) for sent in _sentences(texts.get(where))):
            return None
    return _violation(FAIL_FACT_WITHOUT_ATTRIBUTION,
                      detail=f"the fact ({fact.get('kind')}) is {fact.get('source')!r}'s claim and "
                             f"none of {', '.join(WHERE_ATTRIBUTION)} says so", where=None)


def names_its_source(sentence):
    """Does a sentence that tells a leak name who reported it (SOURCED_PATTERNS)?"""
    n = norm(sentence)
    for rx in _SOURCED_RES:
        for m in rx.finditer(n):
            first = m.group(0).split(" ")[0]
            if first in _NOBODY:
                continue
            return True
    return False


def leak_problems(script, texts):
    """The `leak_without_source` violations of a script: with the channel's
    `leaks_need_source` on, every sentence of a viewer text that tells a leak
    and names nobody who reported it."""
    if not _fact_flag(script, LEAKS_NEED_SOURCE_KEY):
        return []
    out = []
    for where, text in texts.items():
        for sentence in _sentences(text):
            if LEAK_RE.search(norm(sentence)) and not names_its_source(sentence):
                out.append(_violation(FAIL_LEAK_WITHOUT_SOURCE,
                                      detail=f"{where}: {sentence!r}", where=where))
    return out


API_DEMO_FIXES = {
    FAIL_API_DEMO_IS_FACT: "a model's answer shown through its API (an `api_chat` graphic) is "
                           "the model's words on the call's record, never a fact of the story: "
                           "no claim stands on it - drop the claim, or say the fact in the "
                           "narration with its own footing",
}
API_DEMO_REFUSALS_RU = {
    FAIL_API_DEMO_IS_FACT: "Утверждение опирается на ответ модели из демо «через API» - это "
                           "слова модели, а не факт ролика.",
}


def _violation(code, claim_id=None, index=None, detail=None, **extra):
    fixes = FIXES if code in FIXES else API_DEMO_FIXES
    words = REFUSALS_RU if code in REFUSALS_RU else API_DEMO_REFUSALS_RU
    v = {"code": code, "claim_id": claim_id, "index": index, "detail": detail,
         "fix": fixes[code], "text_ru": words[code]}
    v.update(extra)
    return v


def check_claims(script, topic=None, pool=None, plan=None, extra_texts=None):
    """The mechanical verdict on one script's `claims[]`.

    `topic` - the script's topic of 01 (its support_text); `pool` -
    {shot_id: description} of the topic's shots (None: not read); `plan` -
    the Editor's plan of step 6b (`work/<slug>/plan.json`; None before it);
    `extra_texts` - {title, description} of the publication (CF-0555).

    Returns {rule, action, claims, violations[], pending[], results[]}: one
    result per claim with its state and every support's evidence (the quote
    and its paragraph, or the shot's description and the blocks under the
    words) - what CF-0553's judge and the writer's one edit read."""
    report = {"rule": RULE, "action": ACTION_PASS, "claims": 0, "violations": [],
              "pending": [], "results": []}
    claims = (script or {}).get(CLAIMS_FIELD)
    texts = viewer_texts(script, extra_texts)
    chat_wheres = api_chat_wheres(script)
    for where, text in texts.items():
        for sentence in _sentences(text):
            found = hedges_in(sentence)
            if found:
                report["violations"].append(_violation(
                    FAIL_HEDGED, detail=f"{where}: {sentence!r} ({', '.join(found)})",
                    where=where))
    caveat = caveat_problem(script, texts)
    if caveat:
        report["violations"].append(caveat)
    owner = attribution_problem(script, texts)          # CF-0566
    if owner:
        report["violations"].append(owner)
    report["violations"] += leak_problems(script, texts)
    if not isinstance(claims, list):
        report["violations"].append(_violation(
            FAIL_MISSING, detail=f"`{CLAIMS_FIELD}` is {type(claims).__name__}, not a list"))
        report["action"] = ACTION_FAIL
        return report
    report["claims"] = len(claims)
    pieces = support_pieces(topic)
    has_text = topic_has_text(topic)
    if any(isinstance(c, dict) and any(isinstance(s, dict) and "source" in s
                                       for s in c.get("support") or [])
           for c in claims) and not has_text:
        state = ((topic or {}).get("support_check") or {}).get("state")
        report["violations"].append(_violation(
            FAIL_TOPIC_WITHOUT_TEXT,
            detail=f"support_check.state {state!r}, {len(pieces)} piece(s)"))
    seen = set()
    for i, claim in enumerate(claims):
        problems = shape_problems(claim)
        cid = claim.get("claim_id") if isinstance(claim, dict) else None
        if cid in seen and cid is not None:
            problems.append(f"claim_id {cid!r} repeats")
        seen.add(cid)
        result = {"claim_id": cid, "index": i,
                  "text": claim.get("text") if isinstance(claim, dict) else None,
                  "where": claim.get("where") if isinstance(claim, dict) else None,
                  "state": STATE_OK, "supports": []}
        report["results"].append(result)
        if problems:
            report["violations"].append(_violation(FAIL_MALFORMED, cid, i, "; ".join(problems)))
            result["state"] = STATE_FAIL
            continue
        failed = False
        where = claim["where"]
        if where in chat_wheres:
            report["violations"].append(_violation(
                FAIL_API_DEMO_IS_FACT, cid, i, f"{where} is an api_chat - the model's answer "
                                               f"on our record, never a fact", where=where))
            result["state"] = STATE_FAIL
            continue
        if where not in texts:
            if where in GIVEN_BY_CALLER:
                report["pending"].append({"code": PENDING_FIELD_NOT_GIVEN, "claim_id": cid,
                                          "index": i, "detail": f"no {where} handed to the check"})
                result["state"] = STATE_PENDING
            else:
                report["violations"].append(_violation(
                    FAIL_TEXT_NOT_IN_FIELD, cid, i, f"the script has no {where}"))
                failed = True
        elif norm(claim["text"]).strip(_EDGE_PUNCT) not in norm(texts[where]):
            report["violations"].append(_violation(
                FAIL_TEXT_NOT_IN_FIELD, cid, i, f"{claim['text']!r} is not in {where}"))
            failed = True
        for j, sup in enumerate(claim["support"]):
            if "quote" in sup:
                rec, code = judge_quote(sup, pieces)
                pend = None
            else:
                rec, code, pend = judge_shot(sup, claim, script, pool, plan)
            result["supports"].append(rec)
            if code:
                detail = (f"support[{j}] {sup.get('source') or sup.get('shot_id')}: "
                          f"{rec.get('quote') or rec.get('placement') or ''}")
                report["violations"].append(_violation(code, cid, i, detail.strip(": "),
                                                       support=j))
                failed = True
            elif pend:
                report["pending"].append({"code": pend, "claim_id": cid, "index": i,
                                          "support": j, "detail": sup.get("shot_id")})
                if result["state"] == STATE_OK:
                    result["state"] = STATE_PENDING
        if failed:
            result["state"] = STATE_FAIL
    if report["violations"]:
        report["action"] = ACTION_FAIL
    return report


def codes(report):
    return [v.get("code") for v in (report or {}).get("violations") or []]


# ------------------------------------------------------------ batch reading
TOPICS_FILE = "01-trend-hunter.json"
# CF-0673: the explicit continuation of a topic's support text - the pages a
# `scale` script's reference and familiar size were read from, written by
# `shared/factrule/scale_support.py` (`attach`) at the Content Researcher.
SCALE_SUPPORT_FILE = "01-scale-support.json"     # = scale_support.CONTINUATION_FILE
INDEX_FILE = "01b-footage-index.json"
PLAN_VERDICT = "plan_check.json"     # = video-editor plan_check.VERDICT
PLAN_KIND = "plan_check"             # = video-editor plan_check.KIND
PLAN_FILE = "plan.json"
FOOTAGE_REL = Path("shared") / "footage"
ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def topics_of(batch_dir):
    """{topic_id: topic} of 01 - the carried topics and the reserve ones."""
    data = _read(Path(batch_dir) / TOPICS_FILE) or {}
    out = {}

    def take(t):
        if isinstance(t, dict) and t.get("topic_id") and t["topic_id"] not in out:
            out[t["topic_id"]] = t

    for t in data.get("topics") or []:
        take(t)
    for key in ("reserve", "below_shortlist"):
        for item in data.get(key) or []:
            take(item.get("topic") if isinstance(item, dict) and "topic" in item else item)
    # CF-0673: the continuation's pieces follow the topic's own; a piece whose
    # id the topic already has is not added twice. Nothing else of the topic
    # changes - its `support_check` still says whether it had text of its own.
    more = (_read(Path(batch_dir) / SCALE_SUPPORT_FILE) or {}).get("topics") or {}
    for tid, entry in more.items() if isinstance(more, dict) else ():
        topic = out.get(tid)
        pieces = (entry or {}).get("support_text") if isinstance(entry, dict) else None
        if topic is None or not isinstance(pieces, list):
            continue
        have = topic.setdefault("support_text", [])
        ids = {p.get("id") for p in have if isinstance(p, dict)}
        for piece in pieces:
            if isinstance(piece, dict) and piece.get("id") and piece["id"] not in ids:
                have.append(piece)
                ids.add(piece["id"])
    return out


def pool_of(script, batch_dir, root=ROOT):
    """The topic's shots: the indexes the writer's coverage gate judged, or
    the topic's sources of 01b; None when neither is there."""
    paths = ((script or {}).get("anchor_coverage_pool") or {}).get("indexes")
    if not paths:
        idx = _read(Path(batch_dir) / INDEX_FILE) or {}
        vids = (idx.get("sources_by_topic") or {}).get((script or {}).get("topic_id"))
        if not vids:
            return None
        paths = [Path(root) / FOOTAGE_REL / f"{v}.shots.json" for v in vids]
    return pool_from_indexes(paths)


def plan_of(script, batch_dir):
    """The Editor's plan of step 6b for this script (the newest plan_check
    verdict naming it), or None before 6b."""
    found = []
    for p in sorted((Path(batch_dir) / "work").glob(f"*/{PLAN_VERDICT}")):
        v = _read(p)
        if isinstance(v, dict) and v.get("kind") == PLAN_KIND and \
                v.get("script_id") == (script or {}).get("script_id"):
            found.append((v.get("at") or "", p.parent / PLAN_FILE))
    found.sort(key=lambda t: t[0])
    for _, plan_path in reversed(found):
        plan = _read(plan_path)
        if isinstance(plan, dict):
            return plan
    return None


def check_batch_file(path, script_id=None, extra_texts=None, root=ROOT):
    """[(script_id, report)] for the scripts of one 03."""
    path = Path(path)
    data = _read(path)
    if not isinstance(data, dict):
        raise FileNotFoundError(f"{path}: not a readable 03")
    batch = path.resolve().parent
    topics = topics_of(batch)
    out = []
    for s in data.get("scripts") or []:
        if script_id and s.get("script_id") != script_id:
            continue
        out.append((s.get("script_id"), check_claims(
            s, topic=topics.get(s.get("topic_id")), pool=pool_of(s, batch, root),
            plan=plan_of(s, batch), extra_texts=extra_texts)))
    return out


def render(script_id, report):
    lines = [f"{'ok  ' if report['action'] == ACTION_PASS else 'FAIL'} {script_id}: "
             f"{report['claims']} claim(s), {len(report['violations'])} violation(s), "
             f"{len(report['pending'])} pending"]
    for v in report["violations"]:
        who = f" {v['claim_id']}" if v.get("claim_id") else ""
        lines.append(f"  {v['code']}{who}: {v.get('detail') or ''}")
        lines.append(f"      -> {v['fix']}")
    for p in report["pending"]:
        lines.append(f"  pending {p['code']} {p.get('claim_id') or ''}: {p.get('detail') or ''}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file")
    ap.add_argument("--script-id")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    extra = {k: v for k, v in (("title", args.title), ("description", args.description)) if v}
    try:
        results = check_batch_file(args.batch_file, args.script_id, extra)
    except FileNotFoundError as exc:
        print(f"CLAIMS: cannot answer - {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({sid: rep for sid, rep in results}, ensure_ascii=False, indent=2))
    else:
        for sid, rep in results:
            print(render(sid, rep))
    if not results:
        print("CLAIMS: no script to judge", file=sys.stderr)
        return 3
    return 0 if all(r["action"] == ACTION_PASS for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
