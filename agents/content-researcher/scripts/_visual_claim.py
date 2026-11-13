"""CF-0412: a narrator's line that points at a picture the pool does not hold.

Why
---
Batch `example-film/2026-09-27T0929Z`, mechanism B. Hooks of the shape "that
one-second shot of X in the trailer" were written off the news and the
trailer, not off the pool. Kaijura Minus Zero promised "one shot ... of
soldiers just clearing rubble by hand" - the pool had no such shot, the
topic-footage rung (CF-0337) closed the block with some other frame of the
film, and the frame judge ruled `contradicts`, twice. Day Drinker promised
"that one-second shot of the wave-shaped building" three times over a title
card, faces and credits.

The user's decision of 2026-09-28: **a warning only** - no refusal, no
required rewrite. CF-0437 (grill 2026-09-29, "make it from what is given")
adds one rung in front of it at step 6 only: the first uncovered claim sends
the script back once to be reworded to the pool (`check_anchor_coverage.py`,
`claim_judgement()`); after that one rewrite it is this warning again. So nothing here is a gate (CF-0320's price of gates): this
module finds such lines, says which of them no usable shot of the pool
answers, and hands back one `warnings[]` entry per script. The writer decides.

What counts as a visual claim
-----------------------------
A phrase of the narration that points the viewer at one concrete picture:

  * a determiner and a picture noun - "that one-second shot of ...",
    "one shot in the ... trailer of ...", "the scene where ...", "that
    soldiers-in-the-rubble scene", "the quiet frame";
  * a look verb - "you can see ...", "look at ...", "watch the ...",
    "notice the ...";
  * "blink and you miss it".

Its **object** is what the phrase says is in the picture: the words after
"of" / "where" / the look verb, or the modifiers in front of the noun
("soldiers-in-the-rubble scene"). Durations and adjectives that describe no
thing ("one-second", "quiet", "brief") are not an object. A claim that names
no object ("that's the shot this whole sequel earned ...", "blink and you
miss it") points back at the last claim that did name one, and inherits its
object.

Which anchor answers it
-----------------------
Positions are taken in the narration the voice speaks (hook, commentary,
payoff, joined by one space - `plan_check.py`'s own text). The anchors whose
`beat_text` overlaps the claim's words answer it; when none does, the anchor
whose beat started last before the claim - the picture on screen when the
words are said (a block runs until the next anchor); before the first anchor,
the first one.

When it is uncovered
--------------------
The claim is covered when one of its anchors is pictured (the judgement
`status` callable says so) **and**, when the claim has an object, that
anchor's `phrase` names at least one word of the object. Otherwise every
anchor of it contributes a reason: its uncovered status (`absent`, `weak`,
`cut_gate`, `background`, `typographic`, `topic_footage`, ...), or
`off_object` - the anchor is pictured, but its phrase is of something else
(Day Drinker's hook over a title card).

Two callers judge the anchors, each with what it knows:

  * `check_anchor_coverage.py` (step 6, the text can still change) - the
    preflight's per-anchor verdict; gate `visual_claim`;
  * `plan_check_loop.py` (step 6b, the text is locked) - the real resolve's
    refusals in `work/<slug>/plan_check.json`; gate `visual_claim_plan`, and
    the same claims in `work/<slug>/visual_claims.json` beside the plan, for
    the frame judge's pack.

Stdlib only.
"""
import re

import _gate_warning as gw

WARNING_CODE = "visual_claim_uncovered"
GATE_PREFLIGHT = "visual_claim"          # step 6, the preflight's verdicts
GATE_PLAN = "visual_claim_plan"          # step 6b, the real resolve
DECISION = ("CF-0412: the user, 2026-09-28 - a warning only: no refusal and no "
            "required rewrite")
PREDICTS = "frame_judge: contradicts"
SIDECAR = "visual_claims.json"

TEXT_FIELDS = ("hook", "commentary", "payoff")

OFF_OBJECT = "off_object"
PICTURED = "pictured"

# Nouns that name one picture of the film - singular only: "the seaside
# scenes were shot in Nova Scotia" talks about the film, it points at no one
# picture the viewer is about to see.
_NOUNS = r"(?:shot|frame|scene|sequence|close-?up)"
_DET = r"(?:that|this|the|one|a)"
_BOUNDARY = r"[.,;:!?—–()\"]|\s-\s"

_DEMONSTRATIVE = re.compile(
    rf"\b(?P<det>{_DET})\s+(?P<mods>(?:[\w'’-]+\s+){{0,3}}?)(?P<noun>{_NOUNS})\b",
    re.IGNORECASE)
_LOOK = re.compile(
    r"\b(?:you\s+can\s+(?:see|spot|catch|glimpse|make\s+out)|you(?:'ll|\s+will)\s+"
    r"(?:see|spot|notice)|look\s+at|watch(?:\s+for)?\s+(?=the\b|that\b|this\b|how\b|his\b|"
    r"her\b|their\b)|notice\s+(?=the\b|that\b|this\b|how\b)|check\s+out\s+the)\b",
    re.IGNORECASE)
_BLINK = re.compile(r"\bblink\s+and\s+you(?:'ll|\s+will)?\s+miss\s+it\b", re.IGNORECASE)

# "a shot at the title", "give it a shot": not a picture.
_NOT_A_PICTURE_AFTER = re.compile(r"^\s+at\b", re.IGNORECASE)
_NOT_A_PICTURE_BEFORE = re.compile(r"\b(?:give|gave|given|take|took|taken|get|got|"
                                   r"worth|have|had|has)\s+(?:it\s+)?$", re.IGNORECASE)
# "a horror movie shot like ...", "a film shot on location": a clause, not a picture.
_WORK_NOUNS = {"movie", "film", "series", "show", "episode", "documentary", "feature",
               "sequel", "prequel", "remake"}
# Words that cannot stand between a determiner and a picture noun as its
# modifiers - a preposition or a verb of a clause ("that stayed out of frame",
# "the one it was cut from"): the determiner was a pronoun there.
_NOT_MODIFIERS = {"of", "in", "on", "at", "to", "into", "from", "out", "off", "over", "under",
                  "by", "for", "with", "about", "is", "was", "are", "were", "be", "been", "has",
                  "had", "have", "it", "it's", "you", "we", "they", "he", "she", "i", "not",
                  "never", "stayed", "stays", "got", "gets", "made", "makes"}
# "in the Day Drinker trailer" between the noun and its object.
_IN_THE_WORK = re.compile(
    r"^\s+in\s+the\s+(?:[\w'’:-]+\s+){0,6}?(?:trailer|teaser|film|movie|clip|"
    r"episode|video|promo|spot)\b", re.IGNORECASE)
_OBJECT_LEAD = re.compile(r"^\s+(?:of|where|with|showing|in\s+which)\s+", re.IGNORECASE)
_OBJECT_STOP = re.compile(
    rf"(?:{_BOUNDARY})|\s(?:is|was|are|were|isn't|wasn't|that's|and|but|flashes|which|"
    r"who|gone|before|after|when|while|so)\b"
    r"|\s(?:in|from)\s+(?:the|a|this|that)\s+(?:[\w'\u2019:-]+\s+){0,6}?(?:trailer|"
    r"teaser|film|movie|clip|episode|video|promo|spot|cut)\b", re.IGNORECASE)

# Words that name no thing in a picture: durations, rank, mood, the work itself.
STOPWORDS = set("""a an the of in on at to and or with for from by over under into onto as is
are was were be it its this that these those his her their our your one two three four five
six seven eight nine ten out up down off near behind front side some very just only even also
second seconds minute minutes half quiet brief single short little tiny final last first
opening closing same whole strange key famous blink miss trailer teaser film movie video clip
promo spot episode barely actually really real there here where which what who whom whose
then than while when flashes flash shot shots frame frames scene scenes sequence sequences
closeup close up picture image moment you can see look watch notice spot catch glimpse
make check""".split())


def _stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(text):
    """The content words of a phrase, lowercased and de-pluralised."""
    raw = re.findall(r"[a-z]{3,}", str(text or "").lower().replace("’", "'"))
    return {_stem(w) for w in raw if w not in STOPWORDS and _stem(w) not in STOPWORDS}


def _object_after(rest):
    """(object, length of `rest` the claim runs over) - the words the claim
    says are in the picture, out of the text right after its noun."""
    off = 0
    m = _IN_THE_WORK.match(rest)
    if m:
        off = m.end()
    lead = _OBJECT_LEAD.match(rest[off:])
    if not lead:
        return None, 0
    start = off + lead.end()
    stop = _OBJECT_STOP.search(rest[start:])
    end = start + (stop.start() if stop else len(rest) - start)
    body = " ".join(rest[start:end].split()[:8])
    return (body or None), end


def _object_after_look(rest):
    stop = _OBJECT_STOP.search(rest)
    end = stop.start() if stop else len(rest)
    body = " ".join(rest[:end].split()[:8])
    return (body or None), end


def narration(script):
    """(text, {section: offset}) - the three spoken sections on one line."""
    parts, offsets, pos = [], {}, 0
    for k in TEXT_FIELDS:
        t = script.get(k)
        if not t:
            continue
        if parts:
            pos += 1
        offsets[k] = pos
        parts.append(t)
        pos += len(t)
    return " ".join(parts), offsets


def _section_at(offsets, pos):
    best = None
    for k, off in offsets.items():
        if off <= pos:
            best = k
    return best


def find_claims(script):
    """Every visual claim of the narration, in order: `{section, claim, object,
    object_words, start, end, inherited}`. `object` is None for a claim that
    names nothing and follows no claim that did."""
    text, offsets = narration(script)
    # The work's own name is not a thing in the picture ("the building in the
    # Day Drinker trailer" is not answered by a title card reading DAY DRINKER).
    title = words(((script.get("title_ref") or {}).get("name")))
    found = []
    for m in _DEMONSTRATIVE.finditer(text):
        after, before = text[m.end():], text[:m.start()]
        if _NOT_A_PICTURE_AFTER.match(after) or _NOT_A_PICTURE_BEFORE.search(before[-20:]):
            continue
        # "shot on location", "was shot" - the verb, not the noun: the
        # determiner rule already keeps most of them out; "the shot on" stays.
        mods_list = [w.lower().strip("'\u2019") for w in m.group("mods").split()]
        if mods_list and mods_list[-1] in _WORK_NOUNS:
            continue   # "a horror movie shot like ...": the participle, not a picture
        if _NOT_MODIFIERS & set(mods_list):
            continue   # "a city that stayed out of frame": a clause, not a picture
        obj, extra = _object_after(after)
        end = m.end() + extra
        if obj is None:
            mods = words(m.group("mods"))
            obj = m.group("mods").strip() if mods else None
        found.append((m.start(), end, obj))
    for m in _LOOK.finditer(text):
        obj, extra = _object_after_look(text[m.end():])
        found.append((m.start(), m.end() + extra, obj))
    for m in _BLINK.finditer(text):
        found.append((m.start(), m.end(), None))
    found.sort()
    claims, last_obj = [], None
    for start, end, obj in found:
        if claims and start < claims[-1]["end"]:
            continue   # one claim, two patterns ("look at that shot of ...")
        ow = (words(obj) - title) if obj else set()
        inherited = False
        if not ow and last_obj:
            obj, ow, inherited = last_obj[0], last_obj[1], True
        elif ow:
            last_obj = (obj, ow)
        claims.append({"section": _section_at(offsets, start),
                       "claim": " ".join(text[start:end].split()),
                       "object": obj if ow else None,
                       "object_words": sorted(ow),
                       "inherited": inherited,
                       "start": start, "end": end})
    return claims


def anchor_spans(script):
    """[(start, end, anchor)] - each anchor's beat in the narration, in order.
    An anchor whose beat is not found is left out (the shape gate and
    `anchors_dropped` own that problem)."""
    text, _ = narration(script)
    low = text.lower()
    out, cursor = [], 0
    for a in script.get("visual_anchors") or []:
        beat = " ".join(str(a.get("beat_text") or "").split()).lower()
        if not beat:
            continue
        at = low.find(beat, cursor)
        if at < 0:
            at = low.find(beat)
        if at < 0:
            continue
        out.append((at, at + len(beat), a))
        cursor = at
    return sorted(out, key=lambda t: t[0])


def anchors_of(claim, spans):
    over = [a for s, e, a in spans if s < claim["end"] and claim["start"] < e]
    if over:
        return over
    before = [a for s, e, a in spans if s <= claim["start"]]
    if before:
        return [before[-1]]
    return [spans[0][2]] if spans else []


def judge(script, status):
    """The claims no pictured anchor answers.

    `status(anchor)` -> `PICTURED`, or the anchor's uncovered status (a short
    code: `absent`, `weak`, `cut_gate`, `background`, `typographic`, ...).
    Returns one record per uncovered claim."""
    spans = anchor_spans(script)
    out = []
    for c in find_claims(script):
        anchors = anchors_of(c, spans)
        if not anchors:
            continue
        reasons, covered = [], False
        for a in anchors:
            st = status(a) or PICTURED
            if st == PICTURED:
                if not c["object_words"] or (set(c["object_words"]) & words(a.get("phrase"))):
                    covered = True
                    break
                st = OFF_OBJECT
            reasons.append({"anchor_id": a.get("anchor_id"), "status": st,
                            "phrase": a.get("phrase"), "beat_text": a.get("beat_text")})
        if covered:
            continue
        out.append({"section": c["section"], "claim": c["claim"], "object": c["object"],
                    "object_inherited": c["inherited"],
                    "anchor_id": reasons[0]["anchor_id"], "anchors": reasons})
    return out


# ------------------------------------------------------------------------
# what each caller knows about an anchor

# The preflight's verdicts (the Video Editor's anchor_coverage.py).
PREFLIGHT_PICTURED = ("covered",)

# The kinds of `plan_check.json -> refusals[]` that leave a block without a
# picture of its own anchor (`pattern_ceiling`, `plan_refused` and the rest
# are about the plan, not about one anchor's picture).
PLAN_UNCOVERED = ("absent", "cut_gate", "background", "typographic")
TOPIC_FOOTAGE = "topic_footage"


def preflight_status(report, script):
    """status(anchor) out of the preflight's report: its `anchors[]` follow
    the script's `visual_anchors` in order (one phrase each)."""
    by_phrase, by_pos = {}, []
    for a in (report or {}).get("anchors") or []:
        if isinstance(a, dict):
            by_phrase.setdefault(a.get("phrase"), a.get("verdict"))
            by_pos.append(a.get("verdict"))
    order = {id(a): i for i, a in enumerate(script.get("visual_anchors") or [])}

    def status(anchor):
        v = by_phrase.get(anchor.get("phrase"))
        if v is None:
            i = order.get(id(anchor))
            v = by_pos[i] if i is not None and i < len(by_pos) else None
        return PICTURED if v in PREFLIGHT_PICTURED or v is None else v
    return status


def unresolved_status(reasons):
    """One anchor's status out of the resolver's `unresolved_anchors` reasons
    (the storyboard lists a phrase once per thing that happened to it)."""
    text = " | ".join(reasons)
    if "filled from the topic's footage" in text:
        return TOPIC_FOOTAGE        # CF-0337: a frame of the topic, not of the phrase
    if "nothing filled this anchor" in text or "topic-footage rung found no" in text:
        return "absent"
    if "shortfall" in text and "every candidate failed" not in text:
        return PICTURED             # a short picture of it is still its picture
    if "on the cut clip" in text:
        return "cut_gate"
    return "absent"


def plan_status(verdict, unresolved=None):
    """status(anchor) out of the real resolve: the storyboard's
    `unresolved_anchors` (which also names the topic-footage rung) and the
    blocking refusals of `plan_check.json` by anchor id / phrase."""
    by_phrase = {}
    for u in unresolved or []:
        if isinstance(u, dict):
            by_phrase.setdefault(" ".join(str(u.get("phrase") or "").split()), []).append(
                str(u.get("reason") or ""))
    by_id, by_ref_phrase = {}, {}
    for r in (verdict or {}).get("refusals") or []:
        if r.get("kind") not in PLAN_UNCOVERED:
            continue
        if r.get("anchor_id"):
            by_id.setdefault(r["anchor_id"], r["kind"])
        if r.get("phrase"):
            by_ref_phrase.setdefault(" ".join(str(r["phrase"]).split()), r["kind"])

    def status(anchor):
        phrase = " ".join(str(anchor.get("phrase") or "").split())
        if phrase in by_phrase:
            st = unresolved_status(by_phrase[phrase])
            if st != PICTURED:
                return st
        return by_id.get(anchor.get("anchor_id")) or by_ref_phrase.get(phrase) or PICTURED
    return status


def detail(claims):
    parts = []
    for c in claims:
        why = "; ".join(f"{r['anchor_id']} {r['status']}" for r in c["anchors"])
        obj = f" (of: {c['object']})" if c.get("object") else ""
        parts.append(f"[{c['section']}] «{c['claim']}»{obj} -> {why}")
    return (f"{len(claims)} line(s) of the narrator point at a picture no usable shot of the "
            f"pool answers - the frame judge rules such a block `contradicts`. Prefer a "
            f"wording the pool can show (in the hook above all); the choice is the writer's: "
            + " | ".join(parts))


def entry(script, claims, gate, stage_note=None):
    """The `warnings[]` entry for one script, or None when no claim is uncovered."""
    if not claims:
        return None
    e = gw.entry(script.get("topic_id"), script.get("script_id"), gate, WARNING_CODE,
                 detail(claims), numbers={"claims": claims})
    e["decision"] = DECISION
    e["predicts"] = PREDICTS
    e["editor_gate"] = None
    if stage_note:
        e["measured_on"] = stage_note
    return e


def line(e):
    return gw.line(e)
