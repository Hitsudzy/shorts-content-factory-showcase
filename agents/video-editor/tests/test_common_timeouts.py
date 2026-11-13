#!/usr/bin/env python3
"""CF-0128/CF-0132: nothing in this agent waits on a subprocess without a ceiling.

CF-0077 capped the four calls build_render_plan.py makes directly. The
helpers every other script goes through - run_script/run_json, ffmpeg()/
grab_frame, media_duration/image_size - were still uncapped, so the same
hang was reachable from render_video.py, build_soundtrack.py, qc_render.py,
resolve_anchors.py and the layer scripts.

Two things are checked, and the second is the point:
  1. every helper passes a `timeout=` down to subprocess, and the number is
     the constant its class of call is documented against;
  2. reaching it raises ToolTimeout - not the 0.0 / None / False the same
     helper returns for a file it merely could not read. A hang that arrives
     as a plausible value is the failure the ceiling exists to prevent.

CF-0132 closes the other half. The helpers were capped, but 27 calls in nine
scripts were still going to runlog.run_child() directly, past them, with no
`timeout=` at all - qc_render.py and resolve_anchors.py among them, the two
stages a batch runs on every single video. They now go through the helpers,
and the last section of this file is the guard that keeps them there: a scan
of scripts/*.py, so the hole cannot be reopened by a call written next year.

Synthetic: `subprocess.run` is replaced with a fake that records the kwargs
it was handed and either raises TimeoutExpired or returns a canned result.
Nothing is actually run, so this file is fast and needs no media.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import ast
import contextlib
import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import common  # noqa: E402
import _runlog  # noqa: E402
from common import (FFMPEG_BASE_TIMEOUT_SECONDS, FFMPEG_SECONDS_PER_MEDIA_SECOND,  # noqa: E402
                    FFPROBE_TIMEOUT_SECONDS, PROBE_FRAME_TIMEOUT_SECONDS,
                    SIBLING_SCRIPT_TIMEOUT_SECONDS, ToolTimeout)

REAL_RUN = subprocess.run


def _check(cond, msg, fix=None):
    """`msg` reads as the thing that is true when the check passes; `fix`, if
    given, is the instruction appended to the AssertionError when it is not."""
    if not cond:
        raise AssertionError(msg + (f"\n  {fix}" if fix else ""))
    print(f"ok: {msg}")


@contextlib.contextmanager
def fake_run(hang=False, stdout="", returncode=0):
    """subprocess.run replaced. Records every call's kwargs in `seen`;
    raises TimeoutExpired when `hang`, otherwise returns a canned result."""
    seen = []

    def fake(cmd, *a, **kw):
        seen.append(kw)
        if hang:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    subprocess.run = fake
    try:
        yield seen
    finally:
        subprocess.run = REAL_RUN


def _timeouts(seen):
    return [kw.get("timeout") for kw in seen]


# --------------------------------------------------------------------------
# 1. every helper hands subprocess a ceiling, and it is the documented one
# --------------------------------------------------------------------------

def test_ffprobe_helpers_pass_the_ffprobe_ceiling():
    with fake_run(stdout="12.5") as seen:
        _check(common.media_duration("/x/y.mp4") == 12.5, "media_duration reads the duration")
    _check(_timeouts(seen) == [FFPROBE_TIMEOUT_SECONDS],
           f"media_duration probes under {FFPROBE_TIMEOUT_SECONDS} s")

    with fake_run(stdout="1920x1080") as seen:
        _check(common.image_size("/x/y.mp4") == (1920, 1080), "image_size reads the size")
    _check(_timeouts(seen) == [FFPROBE_TIMEOUT_SECONDS],
           f"image_size probes under {FFPROBE_TIMEOUT_SECONDS} s")


def test_the_probe_helpers_added_for_the_direct_callers_carry_the_same_ceiling():
    """CF-0132: probe_json() and stream_kinds() exist because qc_render.py,
    sound_layer.py and meme_layer.py were asking ffprobe these questions
    through runlog.run_child() directly, with no ceiling at all. They are the
    same class of wait as media_duration(), so they get its constant."""
    with fake_run(stdout='{"format": {"duration": "3.0"}}') as seen:
        _check(common.probe_json("/x/y.mp4") == {"format": {"duration": "3.0"}},
               "probe_json parses what ffprobe printed")
    _check(_timeouts(seen) == [FFPROBE_TIMEOUT_SECONDS],
           f"probe_json probes under {FFPROBE_TIMEOUT_SECONDS} s")

    with fake_run(stdout="video\naudio\n") as seen:
        _check(common.stream_kinds("/x/y.mp4") == {"video", "audio"},
               "stream_kinds reads the codec types")
    _check(_timeouts(seen) == [FFPROBE_TIMEOUT_SECONDS],
           f"stream_kinds probes under {FFPROBE_TIMEOUT_SECONDS} s")


def test_a_measuring_or_binary_ffmpeg_pass_is_still_one_ceilinged_pass():
    """CF-0132: `log_level=` (a pass whose answer is its own stderr) and
    `text=False` (a pass whose answer is raw bytes) are the two shapes that
    kept callers out of ffmpeg(). Neither is allowed to become a second code
    path with a ceiling of its own - or none."""
    with fake_run() as seen:
        common.ffmpeg("-i", "/x/y.mp4", "-af", "silencedetect=n=-45dB:d=1.0",
                      "-f", "null", "-", log_level="info", media_seconds=30)
    expected = FFMPEG_BASE_TIMEOUT_SECONDS + 30 * FFMPEG_SECONDS_PER_MEDIA_SECOND
    _check(_timeouts(seen) == [expected],
           "a measuring pass is ceilinged off its material like any other")
    _check(seen and seen[0].get("text") is True, "and still decodes its stderr as text")

    with fake_run() as seen:
        common.ffmpeg("-i", "/x/y.wav", "-f", "f32le", "-", text=False, media_seconds=30)
    _check(_timeouts(seen) == [expected], "so is a raw-bytes decode")
    _check(seen and seen[0].get("text") is False, "which keeps its stdout undecoded")


def test_grab_frame_uses_the_probe_frame_ceiling():
    """The same call build_render_plan.probe_frame() makes, so the same
    CF-0077 constant - not media_timeout(): one frame costs what it costs
    however long the source is."""
    with fake_run() as seen:
        common.grab_frame("/x/y.mp4", 0.5, "/x/frame.png")
    _check(_timeouts(seen) == [PROBE_FRAME_TIMEOUT_SECONDS],
           f"grab_frame grabs under {PROBE_FRAME_TIMEOUT_SECONDS} s")


def test_ffmpeg_ceiling_is_derived_from_the_material():
    """A fixed ceiling is what turns a long honest render into a false
    failure, so the pass-level one scales with the media it chews."""
    with fake_run() as seen:
        common.ffmpeg("-i", "/x/y.mp4", "/x/out.mp4")
    _check(_timeouts(seen) == [FFMPEG_BASE_TIMEOUT_SECONDS],
           "a caller that cannot say how long its material is gets the base alone")

    with fake_run() as seen:
        common.ffmpeg("-i", "/x/y.mp4", "/x/out.mp4", media_seconds=45)
    expected = FFMPEG_BASE_TIMEOUT_SECONDS + 45 * FFMPEG_SECONDS_PER_MEDIA_SECOND
    _check(_timeouts(seen) == [expected],
           f"45 s of material raises the ceiling to {expected:g} s")
    _check(expected > FFMPEG_BASE_TIMEOUT_SECONDS, "and it grows, not shrinks")

    with fake_run() as seen:
        common.ffmpeg("-i", "/x/y.mp4", "/x/out.mp4", timeout=17)
    _check(_timeouts(seen) == [17], "an explicit timeout= wins over the derived one")


def test_media_timeout_never_goes_below_the_base():
    for bad in (None, 0, -30, "not a number"):
        _check(common.media_timeout(bad) == FFMPEG_BASE_TIMEOUT_SECONDS,
               f"media_timeout({bad!r}) falls back to the base, never to zero")
    _check(common.media_timeout(10) < common.media_timeout(100),
           "longer material, longer ceiling")


def test_run_script_passes_the_sibling_ceiling_and_takes_an_override():
    with fake_run() as seen:
        common.run_script("qc_asset.py", "/x/y.png")
    _check(_timeouts(seen) == [SIBLING_SCRIPT_TIMEOUT_SECONDS],
           f"run_script runs under {SIBLING_SCRIPT_TIMEOUT_SECONDS} s by default")

    with fake_run() as seen:
        common.run_script("qc_asset.py", "/x/y.png", timeout=240)
    _check(_timeouts(seen) == [240],
           "a caller that knows its script's class passes its own ceiling")

    with fake_run(stdout='{"usable": true}') as seen:
        _check(common.run_json("qc_asset.py", "/x/y.png") == {"usable": True},
               "run_json parses what the script printed")
    _check(_timeouts(seen) == [SIBLING_SCRIPT_TIMEOUT_SECONDS],
           "run_json inherits run_script's ceiling")


def test_no_helper_runs_a_subprocess_without_a_ceiling():
    """The blanket check, so a helper added later cannot quietly go back to
    waiting forever: every subprocess this module starts carries a timeout."""
    calls = [
        ("media_duration", lambda: common.media_duration("/x/y.mp4")),
        ("image_size", lambda: common.image_size("/x/y.mp4")),
        ("grab_frame", lambda: common.grab_frame("/x/y.mp4", 0.5, "/x/f.png")),
        ("ffmpeg", lambda: common.ffmpeg("-i", "/x/y.mp4", "/x/o.mp4")),
        ("run_script", lambda: common.run_script("qc_asset.py", "/x/y.png")),
        ("run_json", lambda: common.run_json("qc_asset.py", "/x/y.png")),
        ("ffprobe", lambda: common.ffprobe("-show_entries", "format=duration", "/x/y.mp4")),
        ("probe_json", lambda: common.probe_json("/x/y.mp4")),
        ("stream_kinds", lambda: common.stream_kinds("/x/y.mp4")),
    ]
    for name, call in calls:
        with fake_run(stdout='{"a": 1}') as seen:
            call()
        _check(seen and all(isinstance(kw.get("timeout"), (int, float)) and kw["timeout"] > 0
                            for kw in seen),
               f"every subprocess {name}() starts carries a positive ceiling")


# --------------------------------------------------------------------------
# 2. a timeout is never a value
# --------------------------------------------------------------------------

def _hangs(call, tool, ceiling):
    with fake_run(hang=True):
        try:
            call()
        except ToolTimeout as exc:
            text = str(exc)
            _check(isinstance(exc, SystemExit),
                   f"{tool}: ToolTimeout is a SystemExit - no traceback for a caller "
                   "that does not catch it")
            _check(tool in text, f"{tool}: the message names the tool")
            _check(f"{ceiling:g} s ceiling" in text,
                   f"{tool}: the message names the {ceiling:g} s ceiling")
            _check("hung, not slow" in text,
                   f"{tool}: the message says this is a hang, not slow work")
            _check(exc.ceiling == ceiling and exc.tool,
                   f"{tool}: the ceiling and the tool are readable off the exception")
            return
        raise AssertionError(f"{tool}: a hung subprocess came back as a value")


def test_a_hung_probe_raises_instead_of_returning_zero():
    """media_duration returns 0.0 for a file ffprobe cannot read. A wedged
    probe must not arrive as that same 0.0 - a plan built on a silent zero
    duration is worse than one that stopped."""
    _hangs(lambda: common.media_duration("/x/y.mp4"), "ffprobe (duration)",
           FFPROBE_TIMEOUT_SECONDS)


def test_a_hung_size_probe_raises_instead_of_returning_none():
    _hangs(lambda: common.image_size("/x/y.mp4"), "ffprobe (size)", FFPROBE_TIMEOUT_SECONDS)


def test_a_hung_stream_probe_raises_instead_of_answering_no_audio():
    """CF-0132: stream_kinds() returning the empty set means "ffprobe found no
    streams", which meme_layer.py reads as "this asset is silent" and mixes
    accordingly. A wedged probe must not arrive as that answer."""
    _hangs(lambda: common.stream_kinds("/x/y.mp4"), "ffprobe (streams)",
           FFPROBE_TIMEOUT_SECONDS)
    _hangs(lambda: common.probe_json("/x/y.mp4"), "ffprobe (json)",
           FFPROBE_TIMEOUT_SECONDS)


def test_a_hung_frame_grab_raises_instead_of_returning_false():
    _hangs(lambda: common.grab_frame("/x/y.mp4", 0.5, "/x/f.png"), "ffmpeg",
           PROBE_FRAME_TIMEOUT_SECONDS)


def test_a_hung_ffmpeg_pass_raises_whatever_check_says():
    """`check` is about what a pass answered; one that never answered has
    not failed the check, it has stopped."""
    _hangs(lambda: common.ffmpeg("-i", "/x/y.mp4", "/x/o.mp4"), "ffmpeg",
           FFMPEG_BASE_TIMEOUT_SECONDS)
    _hangs(lambda: common.ffmpeg("-i", "/x/y.mp4", "/x/o.mp4", check=True), "ffmpeg",
           FFMPEG_BASE_TIMEOUT_SECONDS)


def test_a_hung_script_raises_whatever_check_says():
    _hangs(lambda: common.run_script("qc_asset.py", "/x/y.png"), "qc_asset.py",
           SIBLING_SCRIPT_TIMEOUT_SECONDS)
    _hangs(lambda: common.run_script("qc_asset.py", "/x/y.png", check=False), "qc_asset.py",
           SIBLING_SCRIPT_TIMEOUT_SECONDS)
    _hangs(lambda: common.run_json("qc_asset.py", "/x/y.png"), "qc_asset.py",
           SIBLING_SCRIPT_TIMEOUT_SECONDS)


def test_the_helpers_that_run_nothing_are_left_alone():
    """audio_duration/leading_silence read a wav header in this process.
    CF-0128 listed them, and they get no ceiling on purpose - there is no
    subprocess to kill. Pinned so a later reader does not 'fix' it."""
    import inspect
    for name in ("audio_duration", "leading_silence"):
        fn = getattr(common, name)
        src = inspect.getsource(fn).replace(fn.__doc__ or "", "")
        _check("run_child(" not in src and "subprocess.run" not in src,
               f"{name} starts no subprocess")


def test_every_ceiling_clears_the_measured_worst_case():
    """The numbers themselves. Each was measured on 2026-09-07 over the 12
    largest clips of shared/footage on an idle machine; CF-0052 measured
    this machine losing 1.4x to thermal throttling after ~2.5 h of
    back-to-back rendering, and a factory renders back to back - so the
    throttled figure is the one a ceiling has to clear, or it fires falsely
    on exactly the long batch it exists for."""
    throttle = 1.4
    for name, ceiling, measured in (
            ("ffprobe metadata", FFPROBE_TIMEOUT_SECONDS, 0.48),
            ("ffmpeg single frame", PROBE_FRAME_TIMEOUT_SECONDS, 1.08),
            # 0.52 s of wall per media second on the heaviest cut in the pool
            ("ffmpeg per media second", FFMPEG_SECONDS_PER_MEDIA_SECOND, 0.52),
            # the slowest single script the run ledger records: the 843 s
            # tts+align step, itself already throttled
            ("sibling script", SIBLING_SCRIPT_TIMEOUT_SECONDS, 843.0)):
        _check(ceiling >= measured * throttle * 2,
               f"{name}: {ceiling:g} s clears {measured:g} s x {throttle} throttling "
               "with room to spare")


# --------------------------------------------------------------------------
# 3. CF-0132: and no caller waits outside them
# --------------------------------------------------------------------------

SCRIPTS_DIR = HERE.parent / "scripts"

# CF-0229: the AST half of this guard - how a child start is found, what
# counts as a ceiling, the CF-0135 pipe rule, the registry drift - lives once,
# in the factory root's shared/timeout_guard.py, and the root's own guard
# (tests/test_timeouts.py) runs on the same copy. Loaded by path, the root
# found the way the run accounting finds it (_runlog.factory_root()). What
# stays here is what is this repository's own: which files are scanned,
# MOVED_SCRIPTS, SHIM, POPEN_SITES and the behavioural checks of common.py.
_TG_PATH = _runlog.factory_root() / "shared" / "timeout_guard.py"
_spec = importlib.util.spec_from_file_location("timeout_guard", _TG_PATH)
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

# The nine scripts CF-0132 moved onto the helpers. Named rather than derived,
# because the check on them is the strong one - they start no subprocess of
# their own at all - and a derived list would quietly stop covering a file
# that was renamed.
MOVED_SCRIPTS = ("qc_render.py", "resolve_anchors.py", "prepare_clip.py",
                 "build_soundtrack.py", "sound_layer.py", "meme_layer.py",
                 "detect_text_band.py", "align_words.py", "write_batch_metadata.py")

# _runlog.py is the accounting shim itself: its run_child *is* subprocess.run,
# and it passes the caller's kwargs - the `timeout=` included - straight down.
SHIM = "_runlog.py"


def test_no_script_starts_a_child_without_a_ceiling():
    """The scan CF-0132 exists for. Every runlog.run_child() left in the
    agent hands subprocess a `timeout=`; and every one outside common.py sits
    inside a `try` that catches TimeoutExpired, so reaching the ceiling
    becomes a verdict (build_render_plan.py's tool_timeout_info, capture_page's
    `reason: timeout`) rather than a traceback or a plausible value."""
    checked = 0
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name == SHIM:
            continue
        for call, guarded in tg.calls_named(tg.parse(path), "run_child"):
            checked += 1
            _check(tg.has_ceiling(call),
                   f"{path.name}:{call.lineno} hands its child a ceiling")
            if path.name != "common.py":
                _check(guarded,
                       f"{path.name}:{call.lineno} turns reaching that ceiling "
                       "into a verdict rather than a value")
    _check(checked >= 4,
           f"the scan actually found child calls to check ({checked}) - a rename "
           "of run_child must not turn this guard into a no-op")


def test_the_scripts_moved_onto_the_helpers_start_no_child_of_their_own():
    """The stronger half, on the nine scripts CF-0132 moved: they start no
    subprocess at all except through common.py. This is the shape the fix was
    scoped in - a ceiling copied to a call site is the thing that later drifts
    from the definition it was copied from (CF-0131's lesson), so the calls
    were moved onto the helpers instead of being capped where they stood."""
    starters = ("run_child", "run", "Popen", "call", "check_call", "check_output")
    for name in MOVED_SCRIPTS:
        path = SCRIPTS_DIR / name
        _check(path.is_file(), f"{name} is still here to check")
        own = [n for n in ast.walk(ast.parse(path.read_text()))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in starters and isinstance(n.func.value, ast.Name)
               and n.func.value.id in ("runlog", "subprocess")]
        _check(not own,
               f"{name} starts every child through a common.py helper"
               + (f" (line {own[0].lineno} does not)" if own else ""))


# --------------------------------------------------------------------------
# 4. CF-0135: and the other way to start a child
# --------------------------------------------------------------------------
#
# Everything above scans for runlog.run_child(), which is subprocess.run()
# underneath: a call that either answers or raises TimeoutExpired, and whose
# ceiling is a `timeout=` keyword an AST scan can read off the call node.
# subprocess.Popen() is the other way to start a child, and this guard was
# blind to it - which is how quiet.py ran Remotion, the longest stage of the
# pipeline, on every video of every batch, with no ceiling at all: the ceiling
# sat on the proc.wait() *after* a `for line in proc.stdout` loop that has no
# deadline of its own, so a child wedged with its pipe open never reached it.
#
# A Popen has no `timeout=` to check - what a Popen site owes is a deadline
# over the whole operation, which is not a property of the call node. So the
# check here is a registry plus one structural rule. The registry costs a line
# of review per site, which is exactly the review CF-0135 did not get.

POPEN_SITES = {
    "quiet.py": (
        "run_logged()'s child - Remotion and ffmpeg. One deadline for the "
        "whole call (quiet.ceiling(), i.e. common.media_timeout()), held by "
        "the thread that is not doing the reading: the read runs on its own "
        "thread and the child is killed when the deadline passes. Proven "
        "behaviourally in tests/test_render_ceiling.py."),
    "vision_client.py": (
        "the vision worker, started detached (start_new_session) on purpose - "
        "it outlives this run and serves every later script (CF-0107). "
        "Nothing here waits on it, so there is no wait to cap; the client's "
        "ceiling is CONNECT_TIMEOUT on the socket, not on the process."),
}


def test_no_script_starts_a_popen_this_guard_has_not_seen():
    """The registry. A Popen that is not named below fails the scan, and the
    way to pass is to say - here, in one line - what bounds the wait on it."""
    found = {}
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        for call in tg.popen_calls(tg.parse(path)):
            found.setdefault(path.name, []).append(call.lineno)
    unregistered, stale = tg.popen_registry_drift(found, POPEN_SITES)
    for name in unregistered:
        _check(False,
               f"{name}:{found[name][0]} starts a subprocess.Popen this guard has seen",
               fix="A Popen carries no timeout= to check, so name the site in "
                   "POPEN_SITES with the deadline that covers the whole "
                   "operation - the reading of its pipe included - or route it "
                   "through a common.py helper.")
    for name in stale:
        _check(False,
               f"POPEN_SITES describes {name}, which still starts one",
               fix="Drop the entry rather than leave the guard describing code "
                   "that is gone.")
    _check(not unregistered and not stale,
           f"every Popen site is registered and every registered site still starts one "
           f"({', '.join(sorted(found))})")
    _check(found, "the scan found a Popen to check - a rename of subprocess or "
                  "an import-as must not turn this guard into a no-op")


def test_no_script_reads_a_child_pipe_on_the_thread_that_owns_its_deadline():
    """The structural rule, and the exact shape of the CF-0135 bug: a function
    that starts a child and then drains its pipe in the same breath cannot
    enforce a deadline on itself - it is parked in the read, and whatever
    ceiling it meant to apply is on the line after. The read belongs on
    another thread (quiet.py) or behind a bounded select; either way it is not
    here. A rewrite that genuinely bounds its own read has to say so by
    editing this guard, which is the point."""
    checked = 0
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        for fn, read in tg.popen_functions(tg.parse(path)):
            checked += 1
            _check(read is None,
                   f"{path.name}:{fn.lineno} {fn.name}() starts a child and leaves "
                   "the reading of its pipe to somewhere that can be bounded"
                   + (f" - line {read.lineno} does not" if read else ""))
    _check(checked >= 2,
           f"the rule was applied to every function that starts a child ({checked})")


def test_every_run_logged_call_says_how_long_its_material_is():
    """quiet.run_logged() cannot be uncapped any more - quiet.ceiling() gives
    a caller that says nothing the base ceiling rather than None. But the base
    alone is 300 s, and a render is minutes: a call that does not pass
    `media_seconds=` (or its own `timeout=`) is a false failure waiting for
    the first long video, which is the other half of what CF-0135 found."""
    calls = 0
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name == "quiet.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run_logged"):
                calls += 1
                names = [kw.arg for kw in node.keywords]
                _check("media_seconds" in names or "timeout" in names,
                       f"{path.name}:{node.lineno} tells run_logged how long its "
                       "material is")
    _check(calls >= 1, f"the scan found run_logged calls to check ({calls})")


def test_no_script_calls_subprocess_run_without_a_ceiling():
    """The last way past all of the above: not run_child, not Popen, but
    subprocess.run() written out by hand. CF-0135 found three of them - two
    measurement instruments outside the pipeline (measure_crop_floor.py,
    measure_probe_profile.py), which is exactly where an uncapped call hides
    longest, because nothing in a batch fails when one wedges. common.py is
    where the helpers themselves live and _runlog.py is the shim that passes
    the caller's kwargs down, so both are checked by the sections above."""
    checked = 0
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name in (SHIM, "common.py"):
            continue
        for node in tg.subprocess_calls(tg.parse(path), ("run",)):
            checked += 1
            _check(tg.has_ceiling(node),
                   f"{path.name}:{node.lineno} hands subprocess.run a ceiling",
                   fix="Route it through a common.py helper, or pass the "
                       "constant its class of call is documented against.")
    _check(checked >= 1,
           f"the scan found subprocess.run calls to check ({checked})")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
