#!/usr/bin/env python3
"""How usable one shot is, as a score and a list of violations - not a
refusal (CF-0435, the grill of 2026-09-29, Q16 and Q19 step 4).

Up to this task the pool's usability bundle was a gate. `usable_cached`
(CF-0029) holds the raw measurements of one full frame per shot, and the
Video Editor's pre-cut filter (`resolve_anchors.precut_cache_refusal`) threw a
shot away the moment one of them missed its floor: framing under 0.65, mean
luma under 28, a short side under 720, no subject. Batch
`example-film/2026-09-29T0929Z` is what that costs: 699 shots of raw footage,
541 after the sieve, **294** after the bundle - 42 % of the raw material reached
the writer, and two topics died of a thin scene. The score model of CF-0432
says what to do instead: a weak shot costs the video points when it reaches
the screen (`score.low_framing`, `score.low_brightness`,
`score.low_resolution`, `score.off_topic_shot` in `shared/gate-prices.json`),
and the Editor takes the best shot it has instead of no shot at all.

So a shot now carries its verdict in words the score model can charge:

    shot["usability"] = {
        "task":     "CF-0435",
        "score":    0.97,          # 1.0 clean ... 0.0 unusable; ranking key
        "penalty":  3,             # points the soft rules would cost, per shot
        "soft": [                  # costs points, never excludes the shot
            {"rule": "low_framing", "price_key": "score.low_framing",
             "value": 0.52, "floor": 0.65},
            ...
        ],
        "hard": [                  # excludes the shot: it cannot be read
            {"rule": "black_frame", "value": 0.97, "ceiling": 0.90},
            ...
        ],
        "measured": True,          # False: no usable_cached to judge from
        "measured_by": "<usable_cached.measured_by>",
    }

The soft rules (the rule name is the score model's key without `score.`):

    low_framing     usable_cached.roi_coverage  < MIN_COVERAGE   (0.65)
    low_brightness  usable_cached.mean_luma     < MIN_MEAN_LUMA  (28)
                    - a lit title card is excused, as qc_asset.evaluate()
                      excuses it (CF-0047)
    low_resolution  min(width, height)          < MIN_SHORT_SIDE (720)
    off_topic_shot  on_topic is false (the describer's flag, CF-0299) and the
                    shot does not show a supplement's entity (CF-0344)

The hard rules - the only ones that still take a shot out:

    black_frame     usable_cached.black_fraction > MAX_BLACK (0.90, the
                    Editor's own ceiling for a clip, `MAX_BLACK_CLIPS`) - a lit
                    card is excused. Not qc_asset's 0.35 for a still: a shot
                    that fades through black is normal footage, and the Editor's
                    pre-cut filter never applied 0.35 to a shot either.
    empty_frame     usable_cached.roi_source == "none" - Vision found neither a
                    face nor a salient object: nothing on screen to look at.
    burned_text     burned_text is true (CF-0299). Somebody else's text on the
                    screen is the hard list's `score.hard.foreign_text`, so the
                    shot stays out, shot by shot, until the grill "вшитый текст"
                    decides which text can stay or be covered. Since CF-0435 the
                    sieve no longer refuses a whole source for it. CF-0567: not
                    on a shot of an own capture (`source_kind: own_capture`,
                    `screen_recording.exempt`) - the tool's interface text is
                    the footage; the flag stays on the shot and is listed in
                    the record's `exempt[]`, never in `hard[]`.

The warning (CF-0451) - neither soft nor hard until the user signs a price:

    screen_recording  the shot is a screen filmed from the room (the cinema
                    cam): the describer's `screen_recording` flag, else its
                    sentence (`screen_recording.shot_verdict`). With no signed
                    row in the price table it goes to `warn[]` with
                    `signed: false` and costs nothing (CF-0320); a signed
                    `score.hard.screen_recording` moves it to `hard[]`, a signed
                    `score.screen_recording` to `soft[]` at the row's price.
                    CF-0567: never on a shot of an own capture
                    (`source_kind: own_capture`) - exempt by its kind.

    low_sharpness (CF-0452) the shot is smeared: its own measurement
                    `sharpness_cached.value` (`sharpness.py`, stamped with
                    `sharpness.MEASURED_BY`) under `sharpness.MIN_SHARPNESS`
                    (0.57), a soft clip whose frames move excused. Unsigned
                    it goes to `warn[]` (`signed: false`, the proposed price
                    beside it) and costs nothing; a signed
                    `score.low_sharpness` makes it a soft rule at the row's
                    price. A shot without the field, or with one another
                    version of the measure took, is not judged on this rule
                    and is never sent to be measured (the pool is transient);
                    the Editor measures a planned shot on the fly
                    (`sharpness.measure()` / `sharpness.at()`).

`sharpness` on the record is the shot's `sharpness_cached.value` (None when
it was not measured) - a ranking key between otherwise equal shots whatever
the floor says.

`score` is `1 - penalty / 100` with the prices of `shared/gate-prices.json`
(the draft prices below when the file cannot be read), and 0.0 when any hard
rule fired. It is a ranking key between shots, not the video's score: the
video is charged by CF-0432 for the weak shots that actually reach the screen,
with the caps the table sets per video.

**Nothing is re-measured here** (CF-0410, the user's ruling that the pool is
transient - `project-footage-pool-is-transient`). `assess()` is a pure function
of what the shot already stores. `shot_schema.write_index()` stamps the field
on every index it writes, which is new material and the indexes a batch
touches; a shot of the old pool without the field is judged on the fly by the
same `assess()` from its stored measurements, and a shot with no
`usable_cached` at all is judged on its flags alone (`measured: false`), never
sent to be measured again.

The thresholds are the Video Editor's numbers, written down here rather than
imported: importing `qc_asset`/`common` into every writer of an index would pull
Vision and PIL into `shot_schema`. `tests/test_shot_usability.py` holds them
equal to the Editor's own constants, so a floor moved there fails a test here
instead of drifting.
"""
import json
from pathlib import Path

import screen_recording
import sharpness

TASK = "CF-0435"
FIELD = "usability"

# The Editor's floors (see the module docstring for why they are copies, and
# the test that keeps them honest).
MIN_COVERAGE = 0.65         # agents/video-editor/scripts/common.py MIN_COVERAGE
MIN_SHORT_SIDE = 720        # agents/video-editor/scripts/common.py MIN_SHORT_SIDE
MIN_MEAN_LUMA = 28          # agents/video-editor/scripts/qc_asset.py MIN_MEAN_LUMA
MIN_CARD_INK_FRACTION = 0.02  # qc_asset.py MIN_CARD_INK_FRACTION (a lit card)
MAX_BLACK = 0.90            # resolve_anchors.py MAX_BLACK_CLIPS

# Rule names. A soft rule's price key is `score.<rule>`; the hard ones are the
# pool's own and exclude a shot rather than cost the video points.
LOW_FRAMING = "low_framing"
LOW_BRIGHTNESS = "low_brightness"
LOW_RESOLUTION = "low_resolution"
OFF_TOPIC_SHOT = "off_topic_shot"
SOFT_RULES = (LOW_FRAMING, LOW_BRIGHTNESS, LOW_RESOLUTION, OFF_TOPIC_SHOT)

BLACK_FRAME = "black_frame"
EMPTY_FRAME = "empty_frame"
BURNED_TEXT = "burned_text"
HARD_RULES = (BLACK_FRAME, EMPTY_FRAME, BURNED_TEXT)
# CF-0451: a screen filmed from the room (the cinema cam). Hard, soft or a
# warning by the *signed* row of the price table (`screen_recording.mode()`);
# with no signature it is a warning - the shot keeps its score (CF-0320).
SCREEN_RECORDING = screen_recording.RULE
# CF-0452: a smeared shot. Soft at a price only by the signed row
# `score.low_sharpness` (`sharpness.mode()`); a warning until then.
LOW_SHARPNESS = sharpness.RULE
# What a hard rule is on the video's hard list, where there is one.
HARD_PRICE_KEYS = {BURNED_TEXT: "score.hard.foreign_text"}

def _fi_paths():
    """CF-0620: this directory's `_fi_paths.py`, loaded by path - video-editor's
    `shot_score` loads this module by path with the indexer's scripts/ not on
    sys.path, so a plain `import _fi_paths` would fail there."""
    import importlib.util
    path = Path(__file__).resolve().with_name("_fi_paths.py")
    spec = importlib.util.spec_from_file_location("_fi_paths", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# CF-0620: the price table of the factory this checkout belongs to (a version
# worktree's own, or FACTORY_ROOT's), not the home checkout's.
PRICES_FILE = _fi_paths().prices_file()
# The draft prices of the grill (Q23), used only when the table cannot be read.
DEFAULT_PRICES = {LOW_FRAMING: 3, LOW_BRIGHTNESS: 3, LOW_RESOLUTION: 2,
                  OFF_TOPIC_SHOT: 4}

_PRICES = {}


def price_key(rule):
    return f"score.{rule}"


def prices(path=None, refresh=False):
    """`{rule: points}` for the soft rules, from `shared/gate-prices.json`.

    Read once per process. A missing file, a missing row or a row without a
    price falls back to the draft price for that rule - a price the table does
    not give is not a price of zero, and a shot must never rank as clean
    because a file was not there."""
    key = str(path or PRICES_FILE)
    if key in _PRICES and not refresh:
        return _PRICES[key]
    out = dict(DEFAULT_PRICES)
    try:
        rules = (json.loads(Path(key).read_text()) or {}).get("rules") or {}
    except (OSError, ValueError):
        rules = {}
    for rule in SOFT_RULES:
        price = ((rules.get(price_key(rule)) or {}).get("penalty") or {}).get(
            "price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out[rule] = price
    _PRICES[key] = out
    return out


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _lit_card(shot, cached):
    ink = cached.get("card_ink_fraction")
    return bool(shot.get("is_card")) and _num(ink) and ink >= MIN_CARD_INK_FRACTION


def _short_side(cached):
    w, h = cached.get("width"), cached.get("height")
    if _num(w) and _num(h):
        return min(w, h)
    s = cached.get("short_side")
    return s if _num(s) else None


def _shows_entity(shot):
    return shot.get("shows_entity") is True


def assess(shot, measurements=True, price_table=None, rule_mode=None,
           sharpness_mode=None):
    """The `usability` record of one shot, from what it already stores.

    `measurements=False` judges the flags alone - for a caller that knows the
    stored `usable_cached` was taken by code that no longer measures that way
    (a stale `measured_by`, CF-0048) and will not act on it. The record then
    says `measured: false`, exactly as for a shot that never had a cache.
    The sharpness record carries its own stamp (`sharpness.is_fresh`) and is
    read on it, whatever `measurements` says.
    """
    shot = shot or {}
    table = price_table or prices()
    warn = []
    cached = shot.get("usable_cached") if measurements else None
    cached = cached if isinstance(cached, dict) and cached else None
    soft, hard = [], []
    if cached:
        lit = _lit_card(shot, cached)
        black = cached.get("black_fraction")
        if _num(black) and black > MAX_BLACK and not lit:
            hard.append({"rule": BLACK_FRAME, "value": black,
                         "ceiling": MAX_BLACK})
        if cached.get("roi_source") == "none":
            hard.append({"rule": EMPTY_FRAME, "value": "none"})
        cover = cached.get("roi_coverage")
        if (_num(cover) and cover < MIN_COVERAGE
                and cached.get("roi_source") != "none"):
            soft.append({"rule": LOW_FRAMING, "value": cover,
                         "floor": MIN_COVERAGE})
        luma = cached.get("mean_luma")
        if _num(luma) and luma < MIN_MEAN_LUMA and not lit:
            soft.append({"rule": LOW_BRIGHTNESS, "value": luma,
                         "floor": MIN_MEAN_LUMA})
        side = _short_side(cached)
        if side is not None and side < MIN_SHORT_SIDE:
            soft.append({"rule": LOW_RESOLUTION, "value": side,
                         "floor": MIN_SHORT_SIDE})
    if shot.get("on_topic") is False and not _shows_entity(shot):
        soft.append({"rule": OFF_TOPIC_SHOT, "value": False, "floor": True})
    own = screen_recording.exempt(shot)          # CF-0567: by the source's kind
    exempt = []
    if shot.get("burned_text") is True:
        if own:
            exempt.append({"rule": BURNED_TEXT, "value": True,
                           "exempt": screen_recording.OWN_CAPTURE})
        else:
            hard.append({"rule": BURNED_TEXT, "value": True})
    for v in soft:
        v["price_key"] = price_key(v["rule"])
        v["price"] = table.get(v["rule"], DEFAULT_PRICES[v["rule"]])
    for v in hard:
        if v["rule"] in HARD_PRICE_KEYS:
            v["price_key"] = HARD_PRICE_KEYS[v["rule"]]
    screen = screen_recording.shot_verdict(shot)
    if screen:
        m = rule_mode or screen_recording.mode()
        v = {"rule": SCREEN_RECORDING, "value": True, "by": screen["by"],
             "match": screen["match"], "price_key": m["price_key"]}
        if m["mode"] == screen_recording.MODE_HARD:
            hard.append(v)
        elif m["mode"] == screen_recording.MODE_PENALTY:
            v["price"] = m["price"]
            soft.append(v)
        else:
            v["signed"] = False
            warn.append(v)
    sharp_rec = shot.get(sharpness.FIELD)
    sharp_rec = sharp_rec if sharpness.is_fresh(sharp_rec) else None
    blur = sharpness.verdict(sharp_rec)
    if blur:
        m = sharpness_mode or sharpness.mode()
        v = {"rule": LOW_SHARPNESS, "value": blur["value"],
             "floor": blur["floor"], "price_key": m["price_key"]}
        if m["mode"] == sharpness.MODE_PENALTY:
            v["price"] = m["price"]
            soft.append(v)
        else:
            v["signed"] = False
            v["proposed_price"] = sharpness.PROPOSED_PRICE["price"]
            warn.append(v)
    penalty = sum(v["price"] for v in soft)
    score = 0.0 if hard else max(0.0, round(1.0 - penalty / 100.0, 4))
    out = {"task": TASK, "score": score, "penalty": penalty,
           "soft": soft, "hard": hard, "warn": warn,
           "measured": bool(cached),
           "measured_by": (cached or {}).get("measured_by"),
           "sharpness": (sharp_rec or {}).get("value")}
    if exempt:
        # CF-0567: on the record, never a rejection (only own captures have it).
        out["exempt"] = exempt
    return out


def of(shot, measurements=True):
    """The shot's usability as the pool reads it: always derived from what
    the shot stores now, so a flag the describer changed after the index was
    written is never read through an older stamp. The stored `usability`
    field is the same record, written for readers outside this repo."""
    return assess(shot, measurements=measurements)


def is_hard(shot, measurements=True):
    """True when the shot cannot be shown at all (black, empty, burned-in
    text) - the only verdict that still takes a shot out of the pool."""
    return bool(of(shot, measurements)["hard"])


def is_weak(shot, measurements=True):
    """True for a shot that stays in the pool at a cost (a soft rule fired)."""
    u = of(shot, measurements)
    return not u["hard"] and bool(u["soft"])


def stamp(shot):
    """Write `shot["usability"]`; returns True when it changed."""
    if not isinstance(shot, dict):
        return False
    new = assess(shot)
    if shot.get(FIELD) == new:
        return False
    shot[FIELD] = new
    return True


CARD_DETECTED = "card_detected"


def exempt_cards(index):
    """CF-0567: an own capture's shot is never a title card - the page's text
    is the footage, not a card. For every shot marked `source_kind:
    own_capture` (`screen_recording.mark_kind` first) a true `is_card` is kept
    as `card_detected: true` (the card probe's answer, on the record) and
    `is_card` becomes false, so no reader - the depth count, the anchor
    matcher, the Editor - treats it as a card. Any other source's shots are
    left as they are. Returns how many changed."""
    if not isinstance(index, dict):
        return 0
    n = 0
    for s in index.get("shots") or []:
        if isinstance(s, dict) and screen_recording.exempt(s) and s.get("is_card"):
            s[CARD_DETECTED] = True
            s["is_card"] = False
            n += 1
    return n


def stamp_index(index):
    """Stamp every shot of a loaded index; returns how many changed. CF-0567:
    the shots of an own capture get their `source_kind` first (the cam-rip,
    burned-text and card exemptions, `screen_recording.mark_kind`,
    `exempt_cards`), so the stamp reads it."""
    marked = screen_recording.mark_kind(index) if isinstance(index, dict) else 0
    marked += exempt_cards(index)
    shots = index.get("shots") if isinstance(index, dict) else index
    return sum(1 for s in (shots or []) if stamp(s)) + marked


def summary(shots, measurements=True):
    """`{"shots", "clean", "weak", "hard", "by_rule": {rule: n}}` over a list
    of shots - what a source or a pool holds, for the reports."""
    out = {"shots": 0, "clean": 0, "weak": 0, "hard": 0, "warned": 0,
           "by_rule": {}}
    for s in shots or ():
        if not isinstance(s, dict):
            continue
        u = of(s, measurements)
        out["shots"] += 1
        if u["hard"]:
            out["hard"] += 1
        elif u["soft"]:
            out["weak"] += 1
        else:
            out["clean"] += 1
        if u.get("warn"):
            out["warned"] += 1
        for v in u["soft"] + u["hard"] + u.get("warn", []):
            out["by_rule"][v["rule"]] = out["by_rule"].get(v["rule"], 0) + 1
    return out
