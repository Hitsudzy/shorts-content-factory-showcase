#!/usr/bin/env python3
"""How deep a topic's footage pool is, asked before a word is written (CF-0304).

Two sources is a count, not a depth. Batch `example-film/2026-09-21T0358Z` is
what the difference costs: Harbourlights (`lf-2026-09-21-002`) held its two
canonical sources and 117 indexed shots, Rennick (`lf-2026-09-21-005`) held
two sources and 29 - and Content Researcher then refused both with
`pool_too_thin`, because once the Editor's own gates are applied those pools
carry 14 and 16 distinct usable samples, enough for 2 and 4 anchors against
the 4-5 a 45-60 s narration needs. Four and a half hours of indexing, a
written scene and a production fact for each, and four further candidates per
topic that were never downloaded because the count said "two, done".

This module is the number the stage did not have: **how many shots of the
topic's pool the Video Editor would still be holding after its pre-cut gate**,
computed from the indexes alone.

The measurement is the Editor's, not a second copy of it
---------------------------------------------------------
`resolve_anchors.precut_refusal(..., need=None)` is the largest usability
question that can be answered from an index (its own docstring says so): the
`moment_at` mark, the shot being long enough to cut (`MIN_CUT_SECONDS`), and
the cached usability verdict - resolution floor, subject, black, luma,
coverage, and the CF-0275 `text_cut_by_crop` veto. It is the function
`anchor_coverage.py` asks an hour later, so this stage and that preflight
cannot drift: a copy of the arithmetic here is exactly the defect class
CF-0003 and CF-0033 are named for. The module is reached the way
`usability_probe.py`, `index_footage.py` and `caption_probe.py` already reach
into the Video Editor's scripts directory - with one addition those three did
not need and this one does, because `resolve_anchors` pulls `meme_layer` in
behind it: see `editor_module()` for the `_runlog` collision and why the
import is isolated rather than plain.

What it deliberately cannot see is everything downstream of a script: the
similarity floor (`DEFAULT_MIN_SCORE = 0.22`) needs per-anchor CLIP scores,
which need phrases, which do not exist at this stage. So this count is an
**upper bound** on the `distinct usable samples` `check_anchor_coverage.py`
will report, and on the live batches that bound is loose by a factor between
1.0 and 2.6 (Harbourlights 36 -> 14; Rennick 27 -> 16; `lf-2026-09-18-003` 7 ->
7). That is why the number below is a floor for *fetching another candidate*
and never a refusal: the refusal stays with the stage that measures real
anchors.

Order of the stage
------------------
Every field this reads is written by `index_footage.py` into the same
`shots.json` it produces - `usable_cached` (CF-0029), `crop_bottom_cached`
(CF-0275), `is_card` (CF-0093). There is no describer pass in between and no
caption pass owed: the answer is available the moment a source is admitted,
which is the moment `ingest_batch.walk()` has to decide whether to take
another candidate. A cache whose `measured_by` stamp is stale is treated by
`precut_refusal` as no cache at all, i.e. the shot is *kept* - so a pool
measured against a restamped probe reads deeper, never thinner, and a stale
pool never triggers a download it does not need.

The floor, and where the number comes from
------------------------------------------
Measured over every topic of the seven `pipeline/example-film/*` batches that
have an `01b-footage-index.json`, against what became of that topic
(`03-content-researcher.json`, `05-video-editor.json`). Usable shots by
outcome:

    reached a finished video      61, 83, 96, 106, 110, 141
    refused for pool depth         7, 23, 27, 34, 36, 59

The two bands do not overlap, and nothing lies between 59 and 61. Every other
candidate measure tried does overlap, on the same topics:

    measure                         thinnest video   deepest depth-refusal
    usable shots                           61              59   <- clean
    usable seconds                      289.3             503.4
    usable non-card shots                  55                57
    indexed shots (today's count)          79               120

So the floor is **60 usable shots**, the largest value that sends no topic
that reached a video after another source. It is not a claim that 60 shots are
"enough" - it is the boundary this factory's own history puts between the
pools that carried a script and the pools that did not, and it moves when the
history does (`POOL_DEPTH_FLOOR` below, one number, one reader).

Two honest caveats, because the table above is small:

  * `lf-2026-09-19-002` was refused `no_second_source` by the writer with 76
    usable shots - every block resolved from one of its two sources. That is
    source *balance*, not depth, and this measure does not claim it; a deeper
    pool would not have been the fix, a better second source would.
  * The indexes are re-measured over time (CF-0275 restamped
    `crop_bottom_cached`, CF-0283 the caption cache), so a pool screened today
    is not byte-for-byte the pool those batches screened. Where a batch-era
    number survives - `anchor_preflight.json`'s `contention.distinct_samples` -
    it is quoted above beside today's count rather than replaced by it.

CF-0435: a weak shot is a shot
------------------------------
Since the grill of 2026-09-29 (Q19 step 4) the usability bundle is a score, not
a gate: a shot under the framing, brightness or resolution floor, or flagged
`on_topic: false`, stays in the pool at a cost (`shot_usability.py`, the
`score.low_*` / `score.off_topic_shot` rows of the score model), and the
Editor ranks by it instead of refusing. So this count no longer asks the
Editor's cached verdict: from `precut_refusal` it takes only what is about the
cut (a valid `moment_at`, `MIN_CUT_SECONDS` of shot), keeps the CF-0275
`text_cut_by_crop` veto, and then asks `shot_usability.of()` - a shot is out
only on a **hard** rule (black past the Editor's clip ceiling, no subject at
all, burned-in text), and a shot with soft violations is **weak**: in the pool,
at a cost, but not part of the floor. A stale `measured_by` stamp is read as
no measurement (the flags alone), the way `precut_refusal` has always read it.
Nothing is re-measured.

Two numbers, two readers (CF-0435 review fix):

    usable_shots     CLEAN shots - no hard and no soft rule. The only number
                     `deep_enough()` compares with the floor, so a pool deep
                     only in weak shots still goes for its next candidate:
                     the Editor MAY take a weak shot at a price when nothing
                     better exists, and this stage never stops looking for the
                     better one because of it.
    weak_shots       shots with soft violations only - kept, not in the floor.
    available_shots  usable_shots + weak_shots: everything the Editor can put
                     on screen at all. What the writer/resolver reads as "how
                     much material is there", so a pool that is thin on clean
                     shots but has weak ones does not read as empty.

A burned-text shot (hard, and refused by the Editor's own CF-0351 screen) is in
none of them. That is why the batch-era numbers of the table above moved: Ted
Lasso's `bYKJxZYd66o` is a captioned portrait source (43 of 45 shots
`burned_text`, all 608 px wide) and measures 51 clean shots today, not 96, and
Rennick's title cards are burned-text cards - the walk now goes for their next
candidate, which is the sieve's own CF-0435 rule (a topic thinned by burned
shots is re-walked for depth).

A measurement that does not answer never costs a download
---------------------------------------------------------
If the Video Editor's scripts are not importable (this repo copied on its
own), or a source has no readable index, the pool reads `measured=False` and
`deep_enough()` says **yes**: the walk stops at the two-source floor exactly
as it did before CF-0304. The failure is in the report, never in the number of
videos this stage downloads - the mirror of CF-0302's rule that a measurement
which explodes never loses a topic.
"""
import json
import sys
import time
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import shot_usability  # noqa: E402 - CF-0435: hard rules out, soft rules weak
from _fi_paths import FactoryRootError, pool_dir, sibling_scripts  # noqa: E402 - CF-0267, CF-0620
try:
    VIDEO_EDITOR_SCRIPTS = sibling_scripts("video-editor")
    _EDITOR_MISSING = None
except FactoryRootError as e:   # remembered, not raised - see editor_module()
    VIDEO_EDITOR_SCRIPTS = SCRIPTS.parent.parent / "video-editor" / "scripts"
    _EDITOR_MISSING = f"{type(e).__name__}: {e}"

# The floor, in shots the Editor's pre-cut gate leaves standing. See the
# module docstring for the table it comes from. A topic under it takes its
# next candidate; a topic at or over it is done.
POOL_DEPTH_FLOOR = 60

_EDITOR = []                # [module] or [None, "why not"] - see editor_module()


def editor_module():
    """`resolve_anchors` from the Video Editor's checkout, or None.

    Three things make this five lines instead of an `import` at the top, and
    all three are load-bearing.

    **It is done on first use, not on import.** `ingest_batch.py` imports this
    module beside its own, and the isolation below depends on what is in
    `sys.modules` at the moment it runs. A lazy import runs at the moment the
    depth is first asked for, which is the same in every caller.

    **`_runlog` is the one module name the two repositories share** (checked:
    it is the only overlap between the two `scripts/` directories). The Video
    Editor's shim has `video_script` and `video_attempt`; this repo's does not,
    and `meme_layer.py` - two imports deep under `resolve_anchors` - asks for
    both at module level without a fallback. With this repo's `_runlog`
    already in `sys.modules`, the import dies there. So this repo's `_runlog`
    is lifted out for the duration and put back afterwards: the Video Editor's
    modules keep direct references to the functions they bound, and every
    later `from _runlog import runlog` in *this* repo gets this repo's shim,
    exactly as before. `sys.path` is restored for the same reason.

    **A failure is remembered, not raised.** The error travels as the second
    element and comes out as `measured=False` on every pool - see the module
    docstring's last paragraph.
    """
    if _EDITOR:
        return _EDITOR[0]
    if _EDITOR_MISSING and not Path(VIDEO_EDITOR_SCRIPTS).is_dir():
        _EDITOR.extend([None, _EDITOR_MISSING])
        return None
    saved_path = list(sys.path)
    saved_runlog = sys.modules.pop("_runlog", None)
    sys.path.insert(0, str(VIDEO_EDITOR_SCRIPTS))
    try:
        import resolve_anchors  # noqa: E402 - precut_refusal(), the Editor's own gate
        _EDITOR.extend([resolve_anchors, None])
    except Exception as e:  # pragma: no cover - only when the sibling repo is gone
        _EDITOR.extend([None, f"{type(e).__name__}: {e}"])
    finally:
        sys.path[:] = saved_path
        sys.modules.pop("_runlog", None)
        if saved_runlog is not None:
            sys.modules["_runlog"] = saved_runlog
    return _EDITOR[0]


def import_error():
    """Why the Editor's gate is not available, or None."""
    editor_module()
    return _EDITOR[1]

CACHE = pool_dir()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout

# One source's screening. `usable`/`seconds` are what survives the gate;
# `refused` counts what did not, and `error` is filled instead of all of them
# when the index could not be read at all.
# CF-0435: `usable`/`seconds`/`cards` are CLEAN shots only (no hard, no soft
# rule) - the floor's number. `weak` is how many shots carry soft violations
# only: kept in the pool, NOT in `usable`. `available(depth)` is the sum.
SourceDepth = namedtuple("SourceDepth",
                         "video_id shots usable seconds cards error weak",
                         defaults=(0,))

# One topic's. `measured` is False when any part of the answer is missing -
# see `deep_enough()`.
TopicDepth = namedtuple("TopicDepth",
                        "topic_id sources shots usable seconds measured error "
                        "per_source weak", defaults=(0,))


def index_path(vid, cache=None):
    """Where this factory keeps `<id>.shots.json`."""
    return Path(cache or CACHE) / f"{vid}.shots.json"


def gate_defaults():
    """The three numbers `precut_refusal` is asked with - the Video Editor's
    own defaults, read from its module rather than written down here, so the
    stage never screens against a floor the Editor has moved."""
    editor = editor_module()
    if editor is None:
        return None
    return (editor.MIN_SHORT_SIDE, editor.MIN_COVERAGE, editor.MAX_BLACK_CLIPS)


def _stale(editor, cached):
    """Whether the Editor would read this cache as no cache at all (CF-0048).
    A checkout without the check reads every cache as current."""
    check = getattr(editor, "_stale_cache", None)
    if check is None:
        return False
    try:
        return bool(check(cached))
    except Exception:
        return True


def screen_shots(shots, detail=False):
    """`(usable, seconds, cards)` over one index's `shots[]`, or with
    `detail=True` `(usable, seconds, cards, weak)`.

    CF-0435: a shot is out only on a hard rule of `shot_usability`. `usable`
    (and `seconds`, `cards`) counts CLEAN shots - no soft rule either - and is
    what the floor reads; a shot with soft violations is counted in `weak`
    instead, never in `usable` (module docstring, "Two numbers, two readers").

    `cards` is how many of the usable ones are title cards (`is_card`), which
    is not part of the floor - a card is a legitimate frame and the Editor
    cuts it - but is the first thing an operator asks about a pool that
    measures deep and reads thin (Rennick: 27 usable, 15 of them cards).
    """
    editor = editor_module()
    gate = gate_defaults()
    if gate is None:                       # pragma: no cover - see import_error()
        raise RuntimeError(
            f"resolve_anchors is not importable: {import_error()}")
    min_short_side, min_coverage, max_black = gate
    usable = cards = weak = 0
    seconds = 0.0
    for shot in shots or ():
        if not isinstance(shot, dict):
            continue
        cached = shot.get("usable_cached")
        fresh = bool(cached) and not _stale(editor, cached)
        # The cut questions only: without its cache the Editor's pre-cut gate
        # asks the moment mark and the length, and nothing about usability.
        bare = {k: v for k, v in shot.items() if k != "usable_cached"}
        try:
            cand = {
                "start": float(shot["start"]),
                "end": float(shot["end"]),
                "shot": shot.get("index"),
                "moment_at": shot.get("moment_at"),
                # `precut_refusal` puts the candidate's similarity score into
                # the refusal record it builds. There is no score before a
                # script, and nothing here reads the record - the key exists so
                # the Editor's function runs unmodified.
                "score": None,
                "source": "pool-depth",
            }
            _at, _origin, span, refusal = editor.precut_refusal(
                cand, bare, min_short_side, min_coverage, max_black, need=None)
            text_cut = (fresh and hasattr(editor, "text_cut_refusal")
                        and editor.text_cut_refusal(shot, cached))
            verdict = shot_usability.of(shot, measurements=fresh)
        except Exception:
            # A single malformed shot is not a verdict about the pool: it is
            # not counted as usable and does not stop the count.
            continue
        if refusal or text_cut or verdict["hard"]:
            continue
        if verdict["soft"]:
            weak += 1                      # available, not clean: not the floor
            continue
        usable += 1
        seconds += float(span or 0.0)
        if shot.get("is_card"):
            cards += 1
    if detail:
        return usable, round(seconds, 3), cards, weak
    return usable, round(seconds, 3), cards


# The walk asks a topic's depth once per candidate it considers, and an index
# with its embeddings in it is a megabyte or three of JSON. A screening is a
# pure function of the file, so it is remembered by (path, mtime, size): a
# re-indexed source is a different key and is screened again, and nothing here
# is ever stale. Cleared by `forget()` for the tests that write an index twice
# inside one second.
_SCREENED = {}


def forget():
    """Drop the memo. For a test that rewrites an index under the same path."""
    _SCREENED.clear()


def screen_source(vid, cache=None):
    """Screen one canonical source. Never raises: an index that cannot be read
    comes back as a `SourceDepth` with `error` set and zeroes elsewhere."""
    path = index_path(vid, cache)
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except Exception as e:
        return SourceDepth(vid, 0, 0, 0.0, 0, f"{type(e).__name__}: {e}")
    if key in _SCREENED:
        return _SCREENED[key]._replace(video_id=vid)
    out = _screen_source(vid, path)
    _SCREENED[key] = out
    return out


def _screen_source(vid, path):
    try:
        shots = (json.load(open(path)) or {}).get("shots") or []
    except Exception as e:
        return SourceDepth(vid, 0, 0, 0.0, 0, f"{type(e).__name__}: {e}")
    try:
        usable, seconds, cards, weak = screen_shots(shots, detail=True)
    except Exception as e:                 # pragma: no cover - see import_error()
        return SourceDepth(vid, len(shots), 0, 0.0, 0, f"{type(e).__name__}: {e}")
    return SourceDepth(vid, len(shots), usable, seconds, cards, None, weak)


def topic_depth(topic_id, video_ids, cache=None):
    """How deep this topic's pool is, over the canonical sources it holds.

    `measured` is False when the Editor's gate is not importable or when any
    one source's index could not be read - in either case the number below is
    an undercount of the real pool, and `deep_enough()` will not spend a
    download on an undercount.
    """
    per_source = [screen_source(v, cache) for v in video_ids or ()]
    errors = [f"{s.video_id}: {s.error}" for s in per_source if s.error]
    if editor_module() is None:            # pragma: no cover - see import_error()
        errors.insert(0, f"resolve_anchors is not importable: {import_error()}")
    return TopicDepth(
        topic_id=topic_id,
        sources=len(per_source),
        shots=sum(s.shots for s in per_source),
        usable=sum(s.usable for s in per_source),
        seconds=round(sum(s.seconds for s in per_source), 3),
        measured=not errors,
        error="; ".join(errors) or None,
        per_source=per_source,
        weak=sum(getattr(s, "weak", 0) or 0 for s in per_source))


def available(depth):
    """Everything the Editor can put on screen at all: clean + weak shots
    (CF-0435). For the writer's picture of the pool, never for the floor."""
    return (getattr(depth, "usable", 0) or 0) + (getattr(depth, "weak", 0) or 0)


def deep_enough(depth, floor=POOL_DEPTH_FLOOR):
    """Is this pool deep enough to stop fetching?

    Counts CLEAN shots only (`depth.usable`, CF-0435): weak shots never stop
    the walk from taking a better candidate. True at or above the floor, and true for a pool that could not be measured
    - a number nobody could compute may make the report worse and may never
    make this stage download more.
    """
    if depth is None or not depth.measured:
        return True
    return depth.usable >= floor


def depth_line(depth, floor=POOL_DEPTH_FLOOR):
    """The one stdout line an operator reads while the stage runs."""
    if not depth.measured:
        return (f"DEPTH {depth.topic_id} pool depth not measured "
                f"({depth.error}) - the walk stops at the source floor")
    weak = getattr(depth, "weak", 0) or 0
    return (f"DEPTH {depth.topic_id} {depth.usable} usable shot(s) of "
            f"{depth.shots} over {depth.sources} source(s)"
            + (f" (+{weak} weak, {available(depth)} available, CF-0435)"
               if weak else "")
            + f", {depth.seconds:.0f}s, floor is {floor}")


def now_z(t=None):
    """UTC with millisecond precision and the Z suffix - runlog.now_z's form."""
    dt = datetime.fromtimestamp(time.time() if t is None else t, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def depth_record(depth, floor=POOL_DEPTH_FLOOR, exhausted=None, attempts=None,
                 at_source_floor=True, indexed_at=None):
    """One topic's line in the report's `pool_depth` block.

    `exhausted` is why the walk stopped without reaching the floor - one of
    `no_more_candidates` / `attempt_cap` / None (it did reach it).
    `at_source_floor` is whether the topic ended with its `wanted` canonical
    sources: a topic below *that* floor is refused by CF-0129 and never reaches
    a script, so its depth is recorded but is not a warning about anything.

    CF-0715: `indexed_at` (UTC, `now_z` form) is when the topic's pool last
    grew - `ingest()` hands in the moment its newest source was admitted with
    its index in this pass; a topic that took no new source in the pass (pool
    sources only, nothing came down) carries the moment this record was made,
    i.e. when its depth was measured. The command center reads it from
    `pool_depth.topics[]` as the topic's last footage update.
    """
    return {
        "topic_id": depth.topic_id,
        "sources": depth.sources,
        "shots": depth.shots,
        # CF-0435: `usable_shots` are CLEAN shots (no hard, no soft rule) and
        # the only number held against `floor`; `weak_shots` carry soft
        # violations only (low framing/brightness/resolution, off topic) - in
        # the pool at a cost, not in the floor; `available_shots` is the sum,
        # the writer's "how much material is there".
        "usable_shots": depth.usable,
        "weak_shots": getattr(depth, "weak", 0) or 0,
        "available_shots": available(depth),
        "usable_seconds": depth.seconds,
        "floor": floor,
        "deep_enough": bool(deep_enough(depth, floor)),
        "measured": bool(depth.measured),
        "at_source_floor": bool(at_source_floor),
        "error": depth.error,
        "exhausted": exhausted,
        "attempts": attempts,
        "indexed_at": indexed_at or now_z(),
        "per_source": [{"video_id": s.video_id, "shots": s.shots,
                        "usable_shots": s.usable,
                        "weak_shots": getattr(s, "weak", 0) or 0,
                        "available_shots": available(s),
                        "usable_seconds": s.seconds,
                        "usable_cards": s.cards, "error": s.error}
                       for s in depth.per_source],
    }


def pool_depth_report(records, floor=POOL_DEPTH_FLOOR):
    """The `pool_depth` block of `01b-footage-index.json` (CF-0304).

    Always present, empty lists included: "every pool is deep enough" and
    "nobody measured" must not read the same, the reason `compliance_gate` and
    `duration_ceiling` list their codes even when empty.

    `thin[]` is the one the funnel and the operator read: a topic that holds
    its two canonical sources, is below the depth floor, and has no candidate
    left to try. It is **not** a refusal - the topic goes to Content Researcher
    exactly as it would have - it is the warning that the refusal is likely and
    that the reason is the pool rather than the writing.
    """
    records = list(records or ())
    return {
        "floor": floor,
        "measure": "shots of the topic's pool that survive the Video Editor's "
                   "pre-cut gate (resolve_anchors.precut_refusal, need=None): "
                   "a valid moment mark, at least MIN_CUT_SECONDS of shot to "
                   "cut, no text_cut_by_crop veto, and no hard usability rule "
                   "(CF-0435 shot_usability: black, empty, burned text). "
                   "usable_shots are the CLEAN ones (no soft rule either) and "
                   "the only number held against floor; weak_shots carry soft "
                   "violations only (low framing/brightness/resolution, off "
                   "topic) and are kept at a cost but never stop the walk; "
                   "available_shots = usable_shots + weak_shots, the material "
                   "the Editor can use at all",
        "topics": records,
        "thin": [r["topic_id"] for r in records
                 if not r["deep_enough"] and r["measured"] and r["exhausted"]
                 and r.get("at_source_floor", True)],
        "unmeasured": [r["topic_id"] for r in records if not r["measured"]],
        "note": "CF-0304: two sources is a count, not a depth. After a topic "
                "holds `two_source_floor.wanted` canonical sources the walk "
                "goes on taking candidates while its pool is under `floor` "
                "usable shots, inside the same CF-0129 attempt cap and the "
                "same CF-0302 duration ceiling. A topic that never reaches the "
                "floor is NOT refused here: this count is an upper bound on "
                "the distinct usable samples check_anchor_coverage.py measures "
                "against real anchors, and the refusal (`pool_too_thin`) stays "
                "with the stage that has them. It is listed in `thin[]` "
                "instead, with the sources it did get and why the walk "
                "stopped. `unmeasured[]` is the case where the depth could not "
                "be computed at all - the walk then stopped at the source "
                "floor, as it did before CF-0304.",
    }
