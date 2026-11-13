#!/usr/bin/env python3
"""Which code produced a cached measurement (CF-0048).

CF-0029 caches raw measurements - `roi_source`, `roi_coverage`,
`black_fraction`, `mean_luma` - in `shots.json` rather than a baked verdict,
so that changing a *threshold* never needs a re-index. That reasoning is
sound and unchanged. What it missed is that a raw measurement is the output
of *code*, and the code moves too: every index in `shared/footage/` was
measured on 2026-09-01 01:01-01:49, and CF-0004's animation-aware fallback
landed in `smart_crop.py` at 08:57 the same morning. From that commit on, the
cached numbers described a measurement the pipeline no longer makes, and
nothing anywhere could tell - `shots.json` carried no record of what had
measured it. Two of ten re-probed shots flipped from "doomed" to "fine", both
of them title cards, i.e. exactly the class CF-0035 had just taught the
matcher to find. CF-0047 then changed the measuring code a second time within
the same day, which is the honest measure of how often this happens.

So: stamp every cached measurement with a fingerprint of the code that made
it, and let the reader compare that against the code it is running now. When
they disagree the cache is not trusted and the caller falls back to measuring
for real - the behaviour that existed before CF-0029, slower but never wrong.
The failure mode is chosen deliberately: a drift between cache and code turns
into lost speed, never into a wrong answer.

**The fingerprint is over raw file bytes, so a comment change invalidates the
pool.** That is the intended direction and not an oversight. The alternative -
deciding which edits are "semantic" - is a judgement this file would have to
make correctly every single time, and the one time it got it wrong the cache
would be silently wrong again, which is the entire defect being fixed here.
Over-invalidating costs one `remeasure_usability.py` run (minutes over the
whole pool); under-invalidating costs a wrong montage nobody can see is wrong.

A hand-maintained schema number was the other option and was rejected for the
same reason: it is correct only as long as every future edit remembers to bump
it, and CF-0004 is proof that nobody remembers.

## CF-0406: the key is what the probe reaches, not whole files

The paragraph on raw bytes above is still how `digest()` works, and `digest()`
stays - `caption_cache.legacy_fingerprint()` and `legacy_fingerprint()` below
use it to prove old stamps. It is no longer the usability key. CF-0387 moved
the caption key to `code_reach.reach_digest()` - the AST of what the
measurement's entry points can actually execute, docstrings and comments out -
and left this one on the raw bytes of eight files, all 859 lines of
`common.py` among them for the 14 of its 103 top-level statements the probe
runs. The bill came in batch 0929Z: CF-0367 added `smart_crop.faces_in_rect()`,
which no probe calls, the key moved, 3229 of 5550 cached measurements read as
stale, and every anchor re-resolve measured its candidates live (1-9 minutes
each). CF-0392's two dead `MEME_*` constants in `common.py` would have done the
same to the whole pool, which is why they had to be put back then.

The walk is the same one and is not copied: `code_reach.py` is loaded from the
Footage Indexer beside the main checkout, as `usability_probe.py` already is.
What counts as a change is decided by the parser, not by judgement - a
statement the roots can reach is in the key (as AST), constants, thresholds and
default arguments included; a statement they cannot reach is out. When the
walk cannot answer honestly (a file missing, a syntax error, a name the reached
code demands that nobody defines) the key is None, which trusts no stamp - the
same failure direction as before.
"""
import hashlib
import importlib.util
from pathlib import Path

from repo_paths import INDEXER_SCRIPTS  # CF-0125: beside the main checkout

SCRIPTS = Path(__file__).resolve().parent
AGENT_ROOT = SCRIPTS.parent
# The other half of the measurement lives in the Footage Indexer (imported
# above) - it decides which frame is measured (offset, letterbox crop, native
# resolution) and when the ink probe is taken. A fingerprint over Video
# Editor's files alone would call a cache fresh after a change that moved the
# probe to a different frame. Resolved beside the *main* checkout: from a
# worktree the sibling agent is not one `..` away (CF-0125), and a
# fingerprint over files that are simply missing is not a fingerprint.

# Every file whose bytes can change the numbers in `usable_cached`:
#   usability_probe.py  - the probe itself: frame choice, aspect, ink trigger
#   smart_crop.py       - find_roi/crop_for_aspect/animation fallback -> roi_*
#   qc_asset.py         - luma_stats/card_ink -> black_fraction, mean_luma, ink
#   detect_text_band.py - text_regions(), which card_ink() measures inside
#   prepare_clip.py     - detect_letterbox(), the crop the probe frame gets
#   vision_client.py    - transport to the worker, and the local fallback path
#   vision_worker.py    - what the worker actually calls in-process
#   common.py           - PROBE_OFFSET, MIN_COVERAGE (the fallback's trigger)
#   vision_compute.py   - CF-0711: which compute device every Vision request
#                         above runs on (pin() before performRequests)
USABILITY_SOURCES = (
    INDEXER_SCRIPTS / "usability_probe.py",
    SCRIPTS / "smart_crop.py",
    SCRIPTS / "qc_asset.py",
    SCRIPTS / "detect_text_band.py",
    SCRIPTS / "prepare_clip.py",
    SCRIPTS / "vision_client.py",
    SCRIPTS / "vision_worker.py",
    SCRIPTS / "common.py",
    SCRIPTS / "vision_compute.py",
)

# Long enough that two different measurement paths will not collide, short
# enough to read in a diff of shots.json. 12 hex chars is 48 bits.
DIGEST_CHARS = 12

_MEMO = {}


def digest(paths):
    """Fingerprint of an ordered set of source files, or None if any of them
    cannot be read.

    None is not an error to swallow: a caller that cannot see the measuring
    code cannot claim a cache was made by it, so None must compare unequal to
    every stored fingerprint and send the reader to the real check. (It is
    also the honest answer when Video Editor is used without the Footage
    Indexer beside it - the cache still works, it is just not trusted.)

    The file's name and byte length go into the hash alongside its content so
    that renaming a file, or two files trading contents, cannot produce the
    same digest as before.
    """
    h = hashlib.sha256()
    for path in paths:
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
    return h.hexdigest()[:DIGEST_CHARS]


# CF-0406: what the key digests inside USABILITY_SOURCES - what these entry
# points can execute (`code_reach.reach`). Together they are the measurement:
# `extract_full_frames()` decides which frame (PROBE_OFFSET, the letterbox
# crop, native resolution), `probe_usability()` measures it (find_roi, the
# luma stats, the text-against-window numbers, the ink probe and the
# thresholds that decide whether it is taken). On today's code that is 14 of
# `common.py`'s 103 top-level statements, 32 of `smart_crop.py`'s 39, 15 of
# `qc_asset.py`'s 31 and all of `vision_worker.py`.
USABILITY_ROOTS = (("usability_probe", "extract_full_frames"),
                   ("usability_probe", "probe_usability"))
# Spawned by `vision_client` as a script, not imported: the file is the entry
# point, `__main__` block included (the rule caption_cache.CAPTION_WHOLE states).
USABILITY_WHOLE = ("vision_worker",)

# Two kinds of pair, one table: LEGACY_STAMPS is {old stamp: newer key}, and
# a shot carrying the old stamp is fresh exactly while following the pairs
# from it arrives at the current key (`stamp_is_current`). Every pair is
# proven over real bytes by a test, never asserted; a pair is written into
# one of the two provenance tables below and LEGACY_STAMPS is built from them.
#
# Kind 1 - same code, other key. Stamps written by the whole-file key
# (CF-0048..CF-0406) that name the same measuring code as a CF-0406 key:
#   c8a4a9661e70 - video-editor db3f68c (CF-0296) + footage-indexer
#                  366b2c9's usability_probe.py; CF-0367 (094976c) then added
#                  smart_crop.faces_in_rect(), which the probe never calls,
#                  and moved the whole-file key
#   dfe991a344df - video-editor 094976c..bd23270, same usability_probe.py
# Both reach-digest to edcd5ade6f17; `test_the_legacy_stamps_name_the_same_
# code` re-derives the pairs from git objects while those exist.
SAME_CODE_STAMPS = {
    "c8a4a9661e70": "edcd5ade6f17",
    "dfe991a344df": "edcd5ade6f17",
}

# Kind 2 (CF-0506) - other code, same numbers: one commit changed reached code
# in a way that cannot move a number a successful measurement writes (or, for
# "device-pin", moves only where the same computation runs - see below), so
# the key moved and the cache did not go stale. Each pair names that commit (and
# the other repo's revision the keys are taken beside; `parent`, when given,
# is the code before the edit if it took more than one commit), the kind of
# edit and why it is neutral. `test_a_neutral_edit_names_the_commit_that_made_it`
# proves it: the key of the commit's parent is the old stamp, the key of the
# commit is the new one, and with the documented edit undone mechanically
# (the `kind` says which undo) the two sides reach the same code - so the
# commit moved nothing else the probe runs. A pair written "so the cache does
# not go stale" has no such commit and goes red.
#
# Kinds the test knows how to undo:
#   "ceiling" - `timeout=<ceiling>` added to a call, and a `try:` around that
#               one statement whose handlers catch only TimeoutExpired. On a
#               call that finishes the result is the one it always was; only
#               a call that used to hang forever now ends in the handler.
#   "device-pin" (CF-0711) - a new `module` whose `calls` are made as bare
#               statements (`module.pin(req)`, result unused) right before a
#               request is performed, plus the `import module` that brings it
#               in. Undone: those statements and imports come out and the
#               module leaves the key. Which device runs the same model on the
#               same frame was never part of this key - it was Vision's own
#               choice per machine (GPU on this Intel Mac, ANE on Apple
#               Silicon), the same code runs the old way under FACTORY_GPU=on
#               with the same key, and a macOS update that swaps a model moves
#               numbers far more without moving any key. Not bit-exact: CPU
#               float32 against GPU float16 can move a box in its 4th decimal;
#               no request, revision, frame, threshold or rounding changes.
NEUTRAL_EDITS = {
    "edcd5ade6f17": {
        "after": "c883fbad1183",
        "commit": ("footage-indexer", "e0506c3"),
        "beside": ("video-editor", "d2f6604"),
        "kind": "ceiling",
        "ceiling": "PROBE_FRAME_TIMEOUT_SECONDS",
        "why": "CF-0506: extract_full_frames() grabs each frame under "
               "PROBE_FRAME_TIMEOUT_SECONDS; a grab that finishes writes the "
               "same png, one that hangs is that shot's frame not extracted "
               "(None, as when ffmpeg fails) instead of the source waiting "
               "forever",
    },
    # The pin and its one-switch rework (aa38ba1, 0f2a2a4) as one edit:
    # `parent` is the code before the first of them.
    "c883fbad1183": {
        "after": "9b61e5035625",
        "commit": ("video-editor", "0f2a2a4"),
        "parent": "7bcd6d9",
        "beside": ("footage-indexer", "e0506c3"),
        "kind": "device-pin",
        "module": "vision_compute",
        "calls": ("pin", "pin_all"),
        "why": "CF-0711: every Vision request smart_crop and detect_text_band "
               "perform (saliency, faces, text recognition) is pinned to the "
               "CPU on an Intel Mac, because the warm worker's text "
               "recognition hung the UHD 630 and shut the laptop down on "
               "12.10. Same request, revision, frame, thresholds and "
               "rounding; only the device the model runs on moves, which "
               "the key has never named (it was Vision's per-machine choice "
               "and FACTORY_GPU=on runs this code the old way under the "
               "same key). The pool's numbers may differ from a CPU "
               "re-measure in float noise only",
    },
}

LEGACY_STAMPS = {**SAME_CODE_STAMPS,
                 **{old: edit["after"] for old, edit in NEUTRAL_EDITS.items()}}

CODE_REACH = INDEXER_SCRIPTS / "code_reach.py"


def code_reach():
    """footage-indexer's `code_reach` module (CF-0387), or None when it is
    not beside the main checkout.

    Loaded by path, not by putting INDEXER_SCRIPTS on sys.path: that directory
    has its own `_runlog.py`, and prepending it in a Video Editor process
    would shadow this repo's copy for every later import (the hazard
    `usability_probe.py` spends a paragraph on). `code_reach` imports only the
    standard library, so a file load is all it needs. Imported, not copied:
    two walkers are two keys for the same code, and the day they disagree the
    caption and usability caches disagree about what "changed" means.
    """
    if "code_reach" not in _MEMO:
        module = None
        if CODE_REACH.exists():
            spec = importlib.util.spec_from_file_location("code_reach", CODE_REACH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        _MEMO["code_reach"] = module
    return _MEMO["code_reach"]


def usability_digest(paths=USABILITY_SOURCES):
    """The CF-0406 key over `paths` (module name = file stem), or None when
    it cannot be computed honestly - including when `code_reach.py` is not
    there: without the walk there is no key, and no key trusts no stamp."""
    walk = code_reach()
    if walk is None:
        return None
    return walk.reach_digest(paths, USABILITY_ROOTS, USABILITY_WHOLE)


def usability_fingerprint(refresh=False):
    """The fingerprint of the code that measures `usable_cached`.

    Memoised per process: `probably_unusable()` asks once per candidate per
    anchor - thousands of times in a real run - and the answer cannot change
    while the process is alive. `refresh=True` is for the tests, which edit
    the files underneath it on purpose.
    """
    if refresh or "usability" not in _MEMO:
        _MEMO["usability"] = usability_digest()
    return _MEMO["usability"]


def legacy_fingerprint():
    """The pre-CF-0406 whole-file digest of the same files - only to prove a
    SAME_CODE_STAMPS pair, never to stamp anything."""
    return digest(USABILITY_SOURCES)


def stamp_is_current(stamp, current=None):
    """Whether a `usable_cached.measured_by` stamp names the code running now:
    today's key, or a stamp from which the LEGACY_STAMPS pairs lead to today's
    key. The pairs are followed as a chain (CF-0506): c8a4a9661e70 names the
    code of edcd5ade6f17, and edcd5ade6f17's measurements are still today's
    after a neutral edit moved the key on to c883fbad1183 - each link is
    proven on its own, so a pair keeps saying what it proved instead of being
    rewritten to the newest key. A chain only runs forward: a shot stamped
    with a newer key is not current on older code. With no computable key
    (None) no stamp is current, a stored `null` included."""
    if current is None:
        current = usability_fingerprint()
    if current is None:
        return False
    seen = set()
    while stamp not in seen:
        if stamp == current:
            return True
        seen.add(stamp)
        stamp = LEGACY_STAMPS.get(stamp)
    return False


if __name__ == "__main__":
    print(usability_fingerprint(), f"(whole-file, legacy: {legacy_fingerprint()})")
    for source in USABILITY_SOURCES:
        print(f"  {'ok ' if source.exists() else 'MISSING'} {source}")
