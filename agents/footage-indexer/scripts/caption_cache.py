#!/usr/bin/env python3
"""Which code produced a cached caption crop, and what to do when it was not
this one (CF-0055).

CF-0029 put two measurements per shot into `shots.json`. CF-0048 fixed the
staleness of the first one, `usable_cached`, and deliberately left the second:
`crop_bottom_cached`, the fraction of frame height `detect_text_band.
detect_captions()` says is burned-in subtitles. It goes stale by exactly the
same mechanism - it is the output of *code*, and the index recorded nothing
about which code - but the consequence is worse. `usable_cached` is read by a
pre-filter that only ever skips a candidate before `cut()`; a stale value there
costs speed. `crop_bottom_cached` is handed straight to `prepare_clip.py
--crop-bottom` and decides the geometry of a real clip in the finished video.
A wrong number there does not fail; it silently cuts the frame in the wrong
place.

## Why this refuses loudly instead of falling back

CF-0048's answer to a stale cache was a free honest fallback: check for real,
pay a `cut()`. `crop_bottom_cached` has no free fallback. Its fallback is
`--auto-crop`, i.e. a fresh 8-sample Vision scan on every single candidate -
which is precisely the cost CF-0029 removed, and the second-largest saving in
that task. It was measured on this pool on 2026-09-03 rather than argued
about: a cut with the cached value takes a median of 3.19 s, the same cut with
`--auto-crop` 13.32 s. That is +10 s per candidate, and a real video tries
several candidates per anchor over 50-100 cuts - +8 to 17 minutes per video.

So the three options CF-0055 listed were settled by that number, not by taste:
falling back to `--auto-crop` on drift (option 1) and moving the measurement
back to cut time (option 3) both hand that time back permanently. What is left
is option 2: keep the cache, and make an unrecognised stamp stop the run
outright with a message naming the command that fixes it. The failure mode is
chosen deliberately and it is the opposite of CF-0048's: there, drift costs
time and never correctness; here, drift costs a refusal to start, because the
alternative to a refusal is a wrongly framed clip nobody can see is wrong.

## Where the refusal fires

`match_anchors.py` - the one place every index a montage will use passes
through before any clip is cut, and a footage-indexer entry point, so the
check sits with the format it is about. `resolve_anchors.py` runs it as a
subprocess and exits on a non-zero return, so a stale pool stops the run in
its first seconds rather than after ten minutes of cutting.

That is a stand-in for the check belonging in `resolve_anchors.py` itself,
next to `_stale_cache()`, immediately before the `shot.get("crop_bottom_
cached")` lookups on lines 489 and 874 - `require_fresh()` is written to be
callable from there in one line. Until it is, one caller could still reach
those lookups without passing the matcher.

## The stamp is a sibling key, not a nested object

`usable_cached` is an object, so CF-0048 put `measured_by` inside it.
`crop_bottom_cached` is a bare float that is passed through to a command-line
argument, and every reader today - `resolve_anchors.cut()`, `measure_card_
bands.py` - reads it as a number. Turning it into an object would break each
of them at once, and break them on a *fresh* cache as loudly as on a stale
one, which is the wrong thing to be loud about. A sibling key keeps the number
a number and gives the reader something to compare, and the two keys can only
be written together, by `store()` below.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _fi_paths import sibling_scripts  # noqa: E402 - CF-0267: the sibling from the root, not by counting `..`
VIDEO_EDITOR_SCRIPTS = sibling_scripts("video-editor")
sys.path.insert(0, str(VIDEO_EDITOR_SCRIPTS))
import caption_probe  # noqa: E402 - the measurement itself, hashed below
from _runlog import runlog  # noqa: E402 - CF-0107; bookkeeping, outside the caption key
# The hash function itself, imported rather than copied (CF-0048 wrote it).
# Two fingerprints over two different file lists is the point; two different
# ways of hashing a file list is not, and a second copy is how they would
# eventually disagree about, say, whether a rename counts.
from cache_fingerprint import digest  # noqa: E402
import code_reach  # noqa: E402 - CF-0387: the key is what the probe reaches

# The files the measurement's import graph runs through. Since CF-0387 the key
# is no longer their bytes: it is the AST of what `probe_captions()` actually
# reaches in them (`code_reach.py`, see CAPTION_ROOTS below). The list is still
# the walk's whole universe - a file missing here is a file the walk cannot
# see - and it is still checked against the import graph by
# `test_fingerprint_covers_exactly_the_caption_measuring_code`.
#
# What each file contributes, and why it is here:
#   caption_probe.py    - the probe: which span, how many samples
#   detect_text_band.py - detect_captions(): LOWER_REGION, MIN_HIT_RATE,
#                         MAX_BAND_SPREAD, the clustering, the 0.45 clamp
#   vision_client.py    - transport to the warm worker, and the local fallback
#   vision_worker.py    - what the worker actually calls in-process
#   common.py           - FFMPEG/FFPROBE and media_duration(), i.e. which
#                         frames get sampled at all
#   _runlog.py          - reachable by import (every measuring module does
#                         `from _runlog import runlog`), and since CF-0387
#                         *opaque*: the walk stops at it and it contributes
#                         nothing. CF-0151 added it on the reading that
#                         `runlog.run_child()` executes the ffmpeg grabs. It
#                         does - by handing `cmd` and `**popen_kw` to
#                         `subprocess.run` unchanged, which is a contract,
#                         pinned by `test_accounting_does_not_touch_what_the_
#                         child_returns` instead of by bytes. The bytes never
#                         protected it anyway: this file only *locates*
#                         `shared/runlog/runlog.py`, the library that does the
#                         running, and that library was never in the key; and
#                         the measuring modules resolve `_runlog` to
#                         video-editor's own copy, not this one. What this file
#                         did do is invalidate 4818 shots when CF-0316 touched
#                         its no-root stand-in.
#   repo_paths.py       - CF-0125's AGENT_ROOT/VENV_PY, which common.py
#                         re-exports and vision_client.py reads to decide which
#                         checkout's venv the warm worker is spawned from, i.e.
#                         which Vision stack answers text_boxes().
#
# Both were added on 2026-09-14 (CF-0151): they had been reachable from
# `caption_probe.py` since CF-0107/CF-0125 and were missing from this tuple,
# which `test_fingerprint_covers_exactly_the_caption_measuring_code` had been
# failing on. The cost of leaving them out is not theoretical - it is that a
# pool re-measured against a fingerprint narrower than the real measurement
# reads as fresh while the code that took it has moved.
#
# Two files that are in the usability list and deliberately not in this one.
# `smart_crop.py` is reachable from here in the import graph, but only through
# `vision_client.find_roi`'s local fallback, and caption detection never calls
# find_roi - it goes to text_boxes(). `prepare_clip.py` *consumes* this number
# (it applies the crop, and detect_letterbox() runs first), but consuming a
# measurement is not making one: if prepare_clip.py changes how it applies the
# crop, re-measuring would not fix anything, so invalidating the pool would be
# noise. The question this fingerprint answers is "would today's code produce
# this number", not "will today's code use it the same way".
#
# CF-0711 added `vision_compute.py`: `detect_text_band.py` imports it and calls
# `vision_compute.pin(req)` before every text request, which picks the compute
# device (CPU on an Intel Mac) - reached code like any other, so it is listed.
CAPTION_SOURCES = (
    HERE / "caption_probe.py",
    VIDEO_EDITOR_SCRIPTS / "detect_text_band.py",
    VIDEO_EDITOR_SCRIPTS / "vision_client.py",
    VIDEO_EDITOR_SCRIPTS / "vision_worker.py",
    VIDEO_EDITOR_SCRIPTS / "common.py",
    HERE / "_runlog.py",
    VIDEO_EDITOR_SCRIPTS / "repo_paths.py",
    VIDEO_EDITOR_SCRIPTS / "vision_compute.py",
)

# CF-0387: what the key digests inside those files - everything the probe can
# execute, found by a static walk from here (`code_reach.reach`), docstrings
# and comments excluded. On today's code that is 143 of `common.py`'s 859
# lines (`grab_frames`, `media_duration`, `ffmpeg`/`ffprobe` and their
# timeouts), 233 of `detect_text_band.py`'s 381 (its CLI is not reached), all
# of `vision_worker.py` and none of `_runlog.py`. An edit outside that - a
# meme constant, a proof-card threshold, the detector's `main()` - no longer
# stales the pool; an edit inside it does, exactly as before.
CAPTION_ROOTS = (("caption_probe", "probe_captions"),)
# Spawned by `vision_client._spawn_worker()` as a script, not imported: the
# entry point is the file, so all of it counts, `__main__` block included.
CAPTION_WHOLE = ("vision_worker",)
# Accounting: see `_runlog.py` in the list above.
CAPTION_OPAQUE = ("_runlog",)

# Stamps written by the whole-file key (CF-0055..CF-0179) that name the same
# measuring code as a CF-0387 key: {old stamp: new key of the same files}.
# A shot carrying the old stamp is fresh exactly while the current key equals
# the new one - the verdict code has not moved since it was measured. Both
# sides were computed over the same bytes (footage-indexer 439321a plus
# video-editor as of 2026-09-27), and `test_the_legacy_stamp_names_the_same_
# code` re-derives the pair whenever those bytes are still present.
# `restamp()` below rewrites such stamps in place; until it is run the alias
# keeps the pool fresh.
SAME_CODE_STAMPS = {"5dd306686131": "7337012cb1b6"}

# Other code, same measurement (CF-0711, the shape of video-editor's
# cache_fingerprint.NEUTRAL_EDITS): one edit moved the key without changing
# what a measurement asks for. Each pair names the commit that made it (and
# `parent`, the code before it, when it took more than one commit), the
# footage-indexer revision the keys are taken beside, the kind of edit and
# why it is neutral. `test_the_device_pin_is_proven_and_nothing_more` proves
# it over git objects: the parent's key is the old stamp, the commit's key the
# new one, and with the documented edit undone mechanically both sides reach
# the same code.
#   "device-pin" - a new `module` whose `calls` are made as bare statements
#               (`module.pin(req)`, result unused) right before a request is
#               performed, plus the `import module` that brings it in. Undone:
#               those statements and imports come out and the module leaves
#               the key.
#   "decode-replace" (CF-0819) - `errors="replace"` added to a call that
#               already decodes its output as text (`text=True`). Undone: that
#               keyword comes out of every such call. A child whose output is
#               valid UTF-8 decodes to the same string either way; only output
#               that is not - which the old code turned into a
#               UnicodeDecodeError, i.e. a failed probe that wrote nothing -
#               now decodes with U+FFFD in it. No number a successful
#               measurement ever wrote can change.
NEUTRAL_EDITS = {
    # The pin and its one-switch rework (video-editor aa38ba1, 0f2a2a4) as one
    # edit; caption_probe.py and _runlog.py last changed at ee52436.
    "7337012cb1b6": {
        "after": "c0c904ae5145",
        "commit": ("video-editor", "0f2a2a4"),
        "parent": "7bcd6d9",
        "beside": ("footage-indexer", "ee52436"),
        "kind": "device-pin",
        "module": "vision_compute",
        "calls": ("pin", "pin_all"),
        "why": "CF-0711: detect_text_band's text recognition (the request "
               "the caption probe makes, warm worker and fallback alike) is "
               "pinned to the CPU on an Intel Mac, because it hung the UHD "
               "630 and shut the laptop down on 12.10. Same request, "
               "recognition level and revision, same frames, thresholds and "
               "rounding; only the device the model runs on moves, which the "
               "key never named (it was Vision's own per-machine choice, and "
               "FACTORY_GPU=on runs this code the old way under the same "
               "key). Not bit-exact: CPU float32 against GPU float16 can move "
               "a box in float noise, so a crop measured before the pin may "
               "differ from a CPU re-measure by that much. For a strict "
               "'this exact code measured it' standard, delete this entry: "
               "every crop stamped 7337012cb1b6 then reads stale and the "
               "gate names remeasure_captions.py",
    },
    # CF-0815's tool-output decoding (video-editor 809a030, half of it undone
    # by 8209783) as one edit; between 0f2a2a4 and 8209783 no other commit
    # touched a caption file of video-editor, and footage-indexer's two
    # (caption_probe.py, _runlog.py) last changed at ee52436. What is left in
    # the reach is common.ffprobe(), which media_duration() calls to pick the
    # probe's sample times; run_tool() got the same keyword but the probe
    # never reaches it. The pool's crops stamped c0c904ae5145 (and through the
    # chain 7337012cb1b6, 5dd306686131) stay current - CF-0819: Tech
    # 2026-10-20T0831Z spent 2 h re-measuring the whole pool over this edit.
    "c0c904ae5145": {
        "after": "e69cab16582e",
        "commit": ("video-editor", "8209783"),
        "parent": "0f2a2a4",
        "beside": ("footage-indexer", "ee52436"),
        "kind": "decode-replace",
        "why": "CF-0815/CF-0819: ffprobe's output (the source duration "
               "media_duration() reads to place the 8 samples) is decoded "
               "with errors='replace' instead of raising on a byte that is "
               "not UTF-8. ffprobe prints that duration in ASCII, so on every "
               "source the probe ever measured the string, the duration, the "
               "sample times, the frames and the crop are the same; a source "
               "whose output was not UTF-8 failed the probe before and wrote "
               "no crop at all. Bit-exact on everything cached.",
    },
}

# Every pair, both provenances: {old stamp: the key it leads to}. Followed as
# a chain (`stamp_is_current`), as video-editor's stamp_is_current does.
LEGACY_STAMPS = {**SAME_CODE_STAMPS,
                 **{old: e["after"] for old, e in NEUTRAL_EDITS.items()}}

# CF-0829: every move of the key is on record. On 2026-10-20 video-editor
# 8209783 moved the key c0c904ae5145 -> e69cab16582e, the plain suite stayed
# green, and only the live pool monitor inside a batch saw it - 2 h of
# `pool-maintenance`, then 2 h more on the retry. So the plain suite now asks
# (`test_todays_key_is_on_record`) that the key history - from KEY_ROOT
# through LEGACY_STAMPS, then STALE_MOVES - ends at today's key, and a move
# with no record is red at commit time, not in a batch.
#
# A move that is not a proven pair goes here instead: the key moved over code
# that changes (or that nobody has shown not to change) what a measurement
# returns, so the crops stamped `old` are stale and stay stale - this table is
# NOT followed by stamp_is_current(). It records that somebody saw the move
# and that the pool is owed a review by the rule (CF-0819: never re-measured
# in bulk; `pool-maintenance` re-takes within its budget and sets the rest
# aside with caption_cache.py --set-aside-stale). Shape:
#   {old key: {"after": new key, "task": "CF-xxxx",
#              "why": "what moved and why it is not neutral"}}
KEY_ROOT = "5dd306686131"
STALE_MOVES = {}


def key_history():
    """The recorded keys in order, from KEY_ROOT: a proven pair
    (LEGACY_STAMPS) is followed first, else a recorded stale move. Stops at a
    key with no record or at a loop."""
    history = [KEY_ROOT]
    while True:
        last = history[-1]
        nxt = LEGACY_STAMPS.get(last) or (STALE_MOVES.get(last) or {}).get("after")
        if nxt is None or nxt in history:
            return history
        history.append(nxt)


def unrecorded_key_move(current=None):
    """None when today's caption key is the end of the recorded history; else
    the message that tells the developer what to record (CF-0829)."""
    if current is None:
        current = captions_fingerprint()
    history = key_history()
    end = history[-1]
    if current is not None and current == end:
        return None
    if current is None:
        return ("the caption key cannot be computed (a measuring file is "
                "unreadable - see `caption_cache.py`'s list of sources); "
                "nothing can be checked against the pool's stamps")
    where = (f" {current} is an older key of the history "
             f"({' -> '.join(history)}): the measuring code went back"
             if current in history else "")
    return (
        f"the caption key moved: today's key is {current}, the recorded "
        f"history ends at {end}.{where}\n"
        f"Every crop in the pool stamped {end} now reads stale, and the live "
        f"monitor stops a batch on it (CF-0829: 20.10 cost two 2-hour "
        f"pool-maintenance runs). Find the commit that moved it (the key is "
        f"code_reach's digest over caption_cache.CAPTION_SOURCES, footage-"
        f"indexer and video-editor), then record the move in "
        f"agents/footage-indexer/scripts/caption_cache.py, one of:\n"
        f"  - neutral (same measurement, proven): NEUTRAL_EDITS[\"{end}\"] = "
        f"{{\"after\": \"{current}\", \"commit\": (repo, rev), \"parent\": "
        f"..., \"beside\": (other repo, rev), \"kind\": <an existing kind or "
        f"a new one with its undo in the tests>, \"why\": ...}} and a test that "
        f"proves it over git objects (see test_the_decode_replace_is_proven_"
        f"and_nothing_more);\n"
        f"  - not neutral: STALE_MOVES[\"{end}\"] = {{\"after\": \"{current}\", "
        f"\"task\": \"CF-xxxx\", \"why\": ...}} - the pool's cache is stale and "
        f"owed a review by the rule (never a bulk re-measure; pool-maintenance "
        f"re-takes within its budget and sets the rest aside), so say so in "
        f"the task before the next batch.")

# The two keys this measurement lives under in shots.json.
VALUE_KEY = "crop_bottom_cached"
STAMP_KEY = "crop_bottom_measured_by"

# CF-0819: where a stale crop goes instead of being re-measured in bulk -
# {"value", "measured_by", "at"}. See set_aside() below.
SET_ASIDE_KEY = "crop_bottom_set_aside"

REMEASURE = "agents/footage-indexer/scripts/remeasure_captions.py"

_MEMO = {}


def captions_fingerprint(refresh=False):
    """The fingerprint of the code that measures `crop_bottom_cached`.

    `None` when any of the files cannot be read, and `None` must compare
    unequal to every stored stamp including another `None`: a checkout that
    cannot see the measuring code cannot claim the cache was made by it.

    Memoised per process - the answer cannot change while the process lives,
    and the gate asks once per index. `refresh=True` is for the tests, which
    edit those files underneath it on purpose.
    """
    if refresh or "captions" not in _MEMO:
        _MEMO["captions"] = code_reach.reach_digest(
            CAPTION_SOURCES, CAPTION_ROOTS, CAPTION_WHOLE, CAPTION_OPAQUE)
    return _MEMO["captions"]


def legacy_fingerprint():
    """The pre-CF-0387 whole-file digest of the same files - only to prove
    the LEGACY_STAMPS pair, never to stamp anything."""
    return digest(CAPTION_SOURCES)


def stamp_is_current(stamp, current=None):
    """Whether a `crop_bottom_measured_by` stamp names the code running now:
    today's key, or a stamp from which the LEGACY_STAMPS pairs lead to it
    (5dd306686131 -> 7337012cb1b6 -> c0c904ae5145 -> e69cab16582e). Each
    link is proven on its own, so a pair keeps saying what it proved instead of being rewritten to
    the newest key. A chain only runs forward; with no computable key (None)
    no stamp is current, a stored `null` included."""
    if current is None:
        current = captions_fingerprint()
    if current is None:
        return False
    seen = set()
    while stamp not in seen:
        if stamp == current:
            return True
        seen.add(stamp)
        stamp = LEGACY_STAMPS.get(stamp)
    return False


def _names_current_code(stamp, current):
    return current is not None and stamp_is_current(stamp, current)


def _restamp_target(stamp):
    """How far `restamp()` may carry a stamp: along same-code links only (a
    LEGACY_STAMPS pair that is not a NEUTRAL_EDITS one). A neutral pair is not
    crossed - the shot keeps the stamp of the code that really measured it, so
    deleting that pair still makes its crops stale."""
    seen = set()
    while stamp not in seen and stamp in LEGACY_STAMPS and stamp not in NEUTRAL_EDITS:
        seen.add(stamp)
        stamp = LEGACY_STAMPS[stamp]
    return stamp


def store(shot, crop_bottom):
    """Write a fresh measurement and its stamp onto a shot, together.

    The only supported way to put `crop_bottom_cached` into an index. The
    value and the stamp are one fact in two keys, and this is what keeps them
    from being written apart - a value written without a stamp reads as stale
    below, which is safe but is a refusal nobody meant to cause.
    """
    shot[VALUE_KEY] = crop_bottom
    shot[STAMP_KEY] = captions_fingerprint()
    shot.pop(SET_ASIDE_KEY, None)   # CF-0819: a fresh number retires the old one
    return shot


def measure(shot, video_path):
    """Probe this shot's own span and store the result. Raises on a probe
    failure, leaving the shot exactly as it was."""
    # CF-0107: one `vision` child per shot (detect_captions' 8-sample Vision
    # scan, with its own frame grabs inside - video-editor code, not ours to
    # split). Here rather than in caption_probe.py, whose bytes are part of
    # the caption fingerprint.
    with runlog.child("vision", argv=["vision", "captions", str(video_path),
                                      f"{shot['start']:.2f}-{shot['end']:.2f}"], step="probe"):
        crop = caption_probe.probe_captions(video_path, shot["start"], shot["end"])
    return store(shot, crop)


def stale_stamp(shot):
    """The offending stamp when this shot's cached crop may not be used, or
    `None` when it may.

    Three states collapse into the same answer, as in CF-0048: a stamp from
    other code, no stamp at all (every index built before this task), and a
    fingerprint this checkout cannot compute. A shot with *no cached value* is
    not stale - `resolve_anchors.cut()` sends it to `--auto-crop`, which is a
    fresh measurement and always correct; that is CF-0029 not having reached
    that index, and it is none of this function's business.
    """
    if VALUE_KEY not in shot:
        return None
    current = captions_fingerprint()
    stamp = shot.get(STAMP_KEY)
    if _names_current_code(stamp, current):
        return None
    return stamp or "unstamped"


def stale_shots(data):
    """[(shot index, offending stamp)] for one loaded shots.json."""
    return [(s.get("index"), stale_stamp(s))
            for s in data.get("shots", []) if stale_stamp(s) is not None]


def survey(index_paths):
    """{path: [(shot, stamp)]} over indexes that have anything stale in them."""
    out = {}
    for path in index_paths:
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            # Not this check's failure to report: whoever reads the index for
            # its shots will say so far more usefully than a cache gate can.
            continue
        stale = stale_shots(data)
        if stale:
            out[str(path)] = stale
    return out


def complaint(stale_by_index):
    """The message a refusal prints. Says what is wrong, why it is not simply
    ignored, and the one command that fixes it - a refusal that does not name
    its own remedy just gets worked around."""
    current = captions_fingerprint() or "unknown (measuring code unreadable)"
    lines = [
        f"caption-band cache is stale: {sum(len(v) for v in stale_by_index.values())} "
        f"shot(s) in {len(stale_by_index)} index(es) carry a `{VALUE_KEY}` this "
        f"checkout did not measure (it measures {current}).",
        "",
        "This is refused rather than worked around (CF-0055). That number is "
        "passed straight to prepare_clip.py --crop-bottom and decides the "
        "geometry of the clip that ends up in the video, so a value from other "
        "code cuts the frame in the wrong place, silently. Falling back to a "
        "fresh --auto-crop per candidate is correct but costs a measured "
        "3.19s -> 13.32s per cut (+8-17 min per video), which is the saving "
        "CF-0029 exists for.",
        "",
    ]
    for path, stale in sorted(stale_by_index.items()):
        stamps = sorted({s for _, s in stale})
        shots = [i for i, _ in stale]
        lines.append(f"  {Path(path).name}: {len(shots)} shot(s) "
                     f"{shots[:8]}{' ...' if len(shots) > 8 else ''} "
                     f"stamped {', '.join(stamps)}")
    lines += ["", f"Re-measure them deliberately, then look at what moved:",
              f"  {REMEASURE} " + " ".join(sorted(stale_by_index)),
              f"  (add --dry-run to see what it would change first)",
              "or, for a pool this batch only reads (CF-0819: never re-measured "
              "in bulk), set them aside - nothing measured, each shot a batch "
              "cuts gets a fresh --auto-crop:",
              "  agents/footage-indexer/scripts/caption_cache.py --set-aside-stale "
              + " ".join(sorted(stale_by_index))]
    return "\n".join(lines)


def require_fresh(index_paths):
    """Refuse to go on when any index holds a caption crop this code did not
    make. Returns None when everything is fine, so it is one line at a call
    site; raises SystemExit with the complaint above otherwise.

    Written to be callable from `resolve_anchors.py` unchanged - that is where
    it belongs, next to the `crop_bottom_cached` lookups it protects.
    """
    stale = survey(index_paths)
    if stale:
        raise SystemExit(complaint(stale))


def restamp(index_path, dry_run=False):
    """CF-0387's one-off migration: rewrite a legacy stamp that names today's
    measuring code (LEGACY_STAMPS) to the newest key of the same code - today's
    key, or (CF-0711) the key just before a NEUTRAL_EDITS pair, which is not
    crossed (`_restamp_target`). Touches `STAMP_KEY` only -
    never a measured value - and only on shots `stale_stamp()` already reads as
    fresh, so it cannot make a stale crop fresh. Idempotent: a second run finds
    nothing to do. Returns the number of shots rewritten."""
    current = captions_fingerprint()
    if current is None:
        return 0
    data = json.load(open(index_path))
    n = 0
    for shot in data.get("shots", []):
        stamp = shot.get(STAMP_KEY)
        if VALUE_KEY not in shot or not stamp_is_current(stamp, current):
            continue
        target = _restamp_target(stamp)
        if target != stamp:
            shot[STAMP_KEY] = target
            n += 1
    if n and not dry_run:
        import shot_schema  # the one atomic index writer (CF-0281)
        shot_schema.write_index(index_path, data)
    return n


# --- CF-0819: a stale crop is set aside, not re-measured in bulk -----------
#
# Tech 2026-10-20T0831Z: a neutral edit nobody had paired yet moved the key,
# every crop in the pool read stale, pool-maintenance re-measured the whole
# pool for 2 h, hit its ceiling and failed the batch - 0 videos. The pool is
# transient (its sources are deleted once published) and the user's rule is
# that it is never re-measured in bulk. So the batch's answer to a stale crop
# is the one CF-0055 kept for a shot with no cached crop at all: the cut runs
# a fresh `--auto-crop` (resolve_anchors.cut_command()), which is always
# correct and costs ~10 s per candidate actually cut - paid only by the shots
# a batch uses, instead of ~2-8 s by every shot of the pool up front.
#
# The stale number is moved, not deleted: `crop_bottom_set_aside` keeps the
# value and the stamp, so a pair proven later (a NEUTRAL_EDITS entry, as
# CF-0819 itself added) can put it back with restore_set_aside() instead of
# anybody measuring it again.

def set_aside_shot(shot):
    """Set one shot's crop aside if it is stale; True when it was. In memory
    only - the caller writes the index."""
    if stale_stamp(shot) is None:
        return False
    from datetime import datetime, timezone
    shot[SET_ASIDE_KEY] = {
        "value": shot.pop(VALUE_KEY), "measured_by": shot.pop(STAMP_KEY, None),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return True


def set_aside(index_path, dry_run=False):
    """Move every stale `crop_bottom_cached` of one index aside: the value and
    its stamp go into SET_ASIDE_KEY, the two cache keys leave the shot, and the
    shot reads as "no cached crop" - a fresh `--auto-crop` at cut time. Fresh
    crops are not touched; nothing is measured. Returns the number of shots
    moved; the index is rewritten atomically only when there are any."""
    data = json.load(open(index_path))
    n = sum(set_aside_shot(shot) for shot in data.get("shots", []))
    if n and not dry_run:
        import shot_schema  # the one atomic index writer (CF-0281)
        shot_schema.write_index(index_path, data)
    return n


def restore_set_aside(index_path, dry_run=False):
    """The way back: a set-aside crop whose stamp names today's code again
    (a pair proven after it was set aside) returns to the two cache keys,
    stamp unchanged. A shot that has a cached crop again keeps it. Returns the
    number of shots restored."""
    current = captions_fingerprint()
    data = json.load(open(index_path))
    n = 0
    for shot in data.get("shots", []):
        aside = shot.get(SET_ASIDE_KEY)
        if not isinstance(aside, dict) or VALUE_KEY in shot:
            continue
        if not _names_current_code(aside.get("measured_by"), current):
            continue
        shot[VALUE_KEY] = aside.get("value")
        shot[STAMP_KEY] = aside.get("measured_by")
        del shot[SET_ASIDE_KEY]
        n += 1
    if n and not dry_run:
        import shot_schema
        shot_schema.write_index(index_path, data)
    return n


def set_aside_warning(n_shots, n_indexes):
    """The loud line: what was set aside, what it costs and what it is not."""
    return (f"WARNING caption-band cache: {n_shots} stale crop(s) in "
            f"{n_indexes} index(es) set aside, NOT re-measured (CF-0819: the "
            f"pool is never re-measured in bulk). Those shots are cut with a "
            f"fresh --auto-crop (~10 s per candidate actually cut). The caption "
            f"key moved to {captions_fingerprint()}: find the commit, and if it "
            f"is neutral pair it in caption_cache.NEUTRAL_EDITS and run "
            f"caption_cache.py --restore-set-aside over the pool; if it is "
            f"not, record it in caption_cache.STALE_MOVES (CF-0829).")


def _cli_over(fn, args, done, would):
    dry = "--dry-run" in args
    paths = [a for a in args if a != "--dry-run"]
    total, touched = 0, 0
    for path in paths:
        n = fn(path, dry_run=dry)
        total += n
        touched += bool(n)
        if n:
            print(f"  {Path(path).name}: {n} shot(s) {would if dry else done}")
    print(f"{total} shot(s) in {len(paths)} index(es) {would if dry else done}")
    return total, touched, dry


@runlog.script("footage-indexer", "caption-cache", name="caption_cache.py")
def cli():
    """CF-0107: the read-only freshness report leaves start/done as well."""
    args = sys.argv[1:]
    if args and args[0] == "--restamp":
        dry = "--dry-run" in args
        paths = [a for a in args[1:] if a != "--dry-run"]
        total = 0
        for path in paths:
            n = restamp(path, dry_run=dry)
            total += n
            if n:
                print(f"  {Path(path).name}: {n} shot(s) "
                      f"{'would be ' if dry else ''}restamped (same code, newer key)")
        print(f"{total} shot(s) in {len(paths)} index(es) "
              f"{'would be ' if dry else ''}restamped")
        return
    if args and args[0] == "--set-aside-stale":
        total, touched, dry = _cli_over(set_aside, args[1:], "set aside",
                                        "would be set aside")
        if total and not dry:
            runlog.annotate(caption_set_aside=total, caption_set_aside_indexes=touched,
                            caption_key=captions_fingerprint())
            print(set_aside_warning(total, touched), file=sys.stderr)
        return
    if args and args[0] == "--restore-set-aside":
        total, _, dry = _cli_over(restore_set_aside, args[1:], "restored",
                                  "would be restored")
        if total and not dry:
            runlog.annotate(caption_restored=total)
        return
    print(captions_fingerprint())
    for source in CAPTION_SOURCES:
        print(f"  {'ok ' if source.exists() else 'MISSING'} {source}")
    if len(sys.argv) > 1:
        stale = survey(sys.argv[1:])
        print(complaint(stale) if stale else
              f"\n{len(sys.argv) - 1} index(es): every cached caption crop is current")


if __name__ == "__main__":
    cli()
