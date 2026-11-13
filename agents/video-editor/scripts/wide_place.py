#!/usr/bin/env python3
"""CF-0352: a wide shot of a place is not a badly framed shot.

`roi_coverage` asks how much of the frame's subject box the 9:16 window
keeps. For a face that is the right question - a crop that cuts the hero is a
known defect, and the 0.65 floor (`common.MIN_COVERAGE`) stays for it. For a
frame with no face Vision returns a *saliency* box, and on a general view of a
building or a landscape that box is most of the frame: the 9:16 window of a
16:9 frame is 0.32 of its width, so the window "keeps" 0.29-0.40 of it on
every such shot, however good. Anchor v4 of `everyday-sorcery-2` (a white
Victorian house, CF-0346) had three pool shots of exactly that house -
`vCOn4RibD1g:24` 0.2896, `:13` 0.2778, `Ho10_4IX1jE:4` 0.2756 - at 0.33-0.40.
Up to CF-0435 the floor refused them; since then each costs the video
`score.low_framing` and is ranked behind any clean shot of the same phrase, and
is shown blur-filled (CF-0436) instead of as the view it is.

The rule here: when the *anchor* names a place (a building, a street, a
landscape - `is_place_anchor()`) and the *shot* has no face in its subject
box (`roi_source` is not `faces`), coverage is not a rule. The shot ranks as
clean, the cut clip carries no `low_framing`, the plan neither charges nor
blur-fills it. What remains is a warning (`wide_place_shot`, in the record's
`warn` with the measured coverage under `wide_place`) - unpriced, so nothing
new is charged without a signature (CF-0320).

The anchor's kind is read from its phrase, because nothing upstream marks
it: a script anchor is `{anchor_id, phrase, beat_text, side}`, and the
supplement request's `entities` are absent on exactly such an anchor (v4 had
none). The test is deliberately narrow - a place word, and no word for a
person, a creature or a vehicle, no close-up, and no capitalised name - so a miss leaves the anchor
where it was before this task (priced), never the other way round.

Stdlib only.
"""
import re

TASK = "CF-0352"
WARN_RULE = "wide_place_shot"
FIELD = "wide_place"          # the record's detail key

# The subject box of a frame with faces in it: the gate stays (the hero must
# not be cut). Every other source (`saliency`, `animation_center`) is not a
# person the window could cut.
FACE_SOURCE = "faces"

# Nouns that make an anchor a view of a place.
PLACE_WORDS = frozenset("""
house houses home mansion manor cottage cabin farmhouse villa palace castle
building buildings tower towers skyscraper skyline cityscape city town village
street streets road highway bridge alley square plaza facade exterior porch
neighborhood neighbourhood suburb block campus estate
landscape countryside field fields meadow farm forest woods woodland jungle
mountain mountains hill hills valley canyon desert beach coast coastline shore
ocean sea lake river waterfall island harbor harbour port bay cliff cliffs
garden yard park lawn church cathedral temple ruins lighthouse stadium arena
theater theatre warehouse factory station airport
""".split())

# Words for a person or a creature: a view of one is not a general view.
PERSON_WORDS = frozenset("""
man men woman women person people boy boys girl girls child children kid kids
baby guy guys lady ladies gentleman actor actors actress actresses host hosts
hero heroes heroine villain character characters figure figures crowd crowds
audience cast crew couple family families sisters sister brother brothers
mother father mom dad wife husband friend friends soldier soldiers warrior
warriors army armies fighter fighters team member members player players
fan fans face faces head heads body bodies hand hands silhouette silhouettes
he she they his her him their someone somebody anyone everyone
creature creatures monster monsters kaiju robot robots android dragon beast
animal animals dog dogs cat cats horse horses bird birds
interview interviewer presenter reporter singer dancer dancers
villager villagers knight knights rider riders performer performers stunt
worker workers pedestrian pedestrians passenger passengers tourist tourists
guest guests student students
""".split())

# A thing standing in the place is the subject, not the place: a window that
# keeps 0.3 of a plane or a car has cut it. And a close-up is never a general
# view.
OBJECT_WORDS = frozenset("""
car cars van vans truck trucks bus plane planes biplane aircraft jet jets
helicopter ship ships yacht boat boats train trains coaster rocket
close-up closeup close detail insert
""".split())

# A capitalised word is a name (a person, a character, a creature) unless it
# is ordinary sentence case or an adjective of style/origin.
_COMMON_CAPS = frozenset("""
a an the wide aerial exterior establishing general long distant drone overhead
daytime night nighttime evening morning dusk dawn sunset sunrise empty quiet
dark bright old new ancient small large big tall white black red blue green
""".split())
_ADJ_SUFFIX = re.compile(r"(?:an|ese|ish|ic|ian)$")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _words(phrase):
    return _WORD.findall(phrase or "")


def _is_name(token):
    """True for a capitalised token that reads as a name."""
    if not token[:1].isupper():
        return False
    head = token.split("-")[0]
    if "-" in token and token.split("-", 1)[1][:1].islower():
        return False          # "Victorian-style", "WWII-era": an adjective
    low = head.lower()
    if low in _COMMON_CAPS or low in PLACE_WORDS:
        return False
    if _ADJ_SUFFIX.search(low) and len(low) > 4:
        return False          # "Victorian", "Japanese", "Gothic"
    return True


def is_place_anchor(phrase):
    """True when the anchor's phrase is a view of a place: some place word,
    no word for a person or creature, no capitalised name."""
    words = _words(phrase)
    lower = [w.lower() for w in words]
    parts = set(lower) | {p for w in lower for p in w.split("-")}
    if not parts & PLACE_WORDS:
        return False
    if parts & PERSON_WORDS or parts & OBJECT_WORDS:
        return False
    return not any(_is_name(w) for w in words)


def wide_ok(roi_source):
    """True when a shot whose subject box came from `roi_source` may be shown
    as a wide view: anything but faces (and a measured box at all)."""
    return bool(roi_source) and roi_source not in (FACE_SOURCE, "none")


def shot_roi_source(shot):
    """The cached subject source of a pool shot, or None."""
    cached = (shot or {}).get("usable_cached")
    return cached.get("roi_source") if isinstance(cached, dict) else None


def waive_record(u):
    """A pool `usability` record (shot_usability.of) without `low_framing`,
    its penalty and score recomputed. The input is not changed."""
    if not isinstance(u, dict):
        return u
    soft = [v for v in u.get("soft") or [] if v.get("rule") != "low_framing"]
    if len(soft) == len(u.get("soft") or []):
        return u
    out = dict(u)
    out["soft"] = soft
    out["penalty"] = sum(v.get("price") or 0 for v in soft)
    if not u.get("hard"):
        out["score"] = max(0.0, round(1.0 - out["penalty"] / 100.0, 4))
    return out


def waive_qc(qc):
    """A qc_asset.py verdict with a `coverage` failure taken out when the
    frame's subject box is not a face. `(verdict, coverage or None)` - the
    coverage it waived, None when nothing was. The input is not changed."""
    qc = qc or {}
    failed = list(qc.get("failed") or [])
    if "coverage" not in failed or not wide_ok(qc.get("roi_source")):
        return qc, None
    out = dict(qc)
    out["failed"] = [k for k in failed if k != "coverage"]
    out["failures"] = [f for f in qc.get("failures") or []
                       if not f.startswith("framing")]
    if not out["failed"]:
        out["usable"] = True
    return out, qc.get("roi_coverage")


def mark(rec, coverage, roi_source=None):
    """The storyboard's `usability` record `rec` (or None) with the warning
    added: `wide_place_shot` in `warn`, the measured coverage under
    `wide_place`. Unpriced - nothing in `soft` changes."""
    rec = dict(rec) if isinstance(rec, dict) else {"task": TASK, "soft": [],
                                                  "penalty": 0, "score": 1.0}
    warn = [w for w in rec.get("warn") or [] if w != WARN_RULE]
    rec["warn"] = warn + [WARN_RULE]
    rec[FIELD] = {"task": TASK,
                  "coverage": None if coverage is None else round(coverage, 3),
                  "roi_source": roi_source}
    return rec


def waived(rec):
    """True when a storyboard picture's record carries the waiver."""
    return isinstance(rec, dict) and isinstance(rec.get(FIELD), dict)
