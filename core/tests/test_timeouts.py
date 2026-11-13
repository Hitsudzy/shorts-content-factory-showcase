#!/usr/bin/env python3
"""CF-0229: nothing in the root waits on a subprocess without a ceiling.

The rule is agents/video-editor's (CF-0077 -> CF-0128 -> CF-0132 -> CF-0135):
every child started carries a deadline, and a function that starts a child
does not drain its pipe on the thread that owns that deadline. Until CF-0229
the guard lived only there, and the root was held by attention - which had
already slipped: scripts/meme_desk.py carried five waits with no ceiling, and
shared/runlog/supplement.py ran its three recheck steps through
`_run(timeout=None)`, i.e. `communicate()` with no deadline at all.

The how-to-scan lives in shared/timeout_guard.py, one copy for every
repository (CF-0159: a copied rule drifts). What lives here is the root's own
half: which directories are scanned, the pass-through sites exempted by
name, and POPEN_SITES - one line of review per Popen saying what bounds it.

Scope: the root's code - scripts/, shared/ (the footage pool pruned, not
walked), rotation/, patterns/, inserts/, channels/. tests/ is not scanned: a
test's child is bounded by tests/run_tests.py's per-file ceiling (CF-0077).
"""
import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("timeout_guard", ROOT / "shared" / "timeout_guard.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

SCANNED = ("scripts", "shared", "rotation", "patterns", "inserts", "channels")
# shared/footage is the media pool: thousands of clips, no code. Pruned.
SKIP = ("footage",)

# Sites whose subprocess.run takes the caller's kwargs through `**kw` - the
# ceiling is the caller's, so an AST scan of the call cannot see it. Named by
# (file, function), with the reason; a new pass-through fails the scan until
# it is either rewritten to name its timeout= or described here.
PASSTHROUGH = {
    ("shared/runlog/runlog.py", "run_child"): (
        "the accounting wrapper itself: subprocess.run(cmd, **popen_kw) hands "
        "the caller's timeout= straight down (CF-0128); with watchdog= the "
        "child goes through _watched() instead, under the silence ceiling."),
}

POPEN_SITES = {
    "shared/run_checks.py": (
        "_run_remeasure(): remeasure_captions.py for pool-maintenance (CF-0819). "
        "No pipes - output is inherited by the step's log - so wait(timeout=) is "
        "the whole deadline (REMEASURE_TIMEOUT, the 300 s budget + 300 s); past "
        "it the process group (start_new_session, its --jobs children too) gets "
        "SIGTERM then SIGKILL, 10 s grace each."),
    "shared/runlog/monitors.py": (
        "run_file(): one live-monitor test file (CF-0511). Output goes to a "
        "temporary file, not a pipe - nothing to drain - so wait(timeout=) is the "
        "whole deadline; past it the file's process group is killed "
        "(start_new_session). The step's own ceiling bounds the sum."),
    "shared/runlog/sampler.py": (
        "the per-batch CPU sampler daemon: start_new_session, all three pipes "
        "on DEVNULL, nobody waits on it or reads it - there is no wait to cap. "
        "It ends itself after --idle-minutes; stop() signals it."),
    "shared/runlog/repo_sync.py": (
        "refresh_in_background(): the statusline's detached recount, pipes on "
        "DEVNULL, start_new_session - the statusline does not wait for it; its "
        "own git calls carry timeout= (they are subprocess.run, scanned above)."),
    "shared/runlog/supplement.py": (
        "_run(): one machine step of the thin-pool supplement. "
        "communicate(timeout=) is the deadline over the whole operation, the "
        "pipes included, and the group is killed past it (CF-0426). The "
        "deadline is the caller's, so every _step() names timeout= - checked "
        "by test_every_supplement_step_names_its_ceiling."),
    "shared/runlog/runlog.py": (
        "_watched(): run_child under the CF-0316 silence watchdog. The pipes "
        "are drained by threads, the deadline is watchdog.wait() on this one, "
        "and the child is terminated then killed when it is reached."),
    "shared/factrule/claim_judge.py": (
        "Asker._run(): one answer command of the claim judge (CF-0553). "
        "communicate(timeout=) is the deadline over the whole operation, the "
        "pipes included (the call's ceiling + 30 s), and the group is killed "
        "past it (start_new_session)."),
    "shared/run_executor.py": (
        "Executor.process(): one step or `claude -p` of the run plan (CF-0203), "
        "started detached on purpose - start_new_session, stdin/stdout/stderr on "
        "DEVNULL (the wrapper writes the log file), so there is no pipe to drain "
        "and nothing to cap here: the executor only polls the pid and the exit "
        "file, and must not kill a step when it dies or stops waiting. The "
        "step's ceiling is the step's own (thin_pool_supplement.py's "
        "max_wall_seconds, the claim judge's timeouts, ...)."),
    "shared/batch_schedule.py": (
        "_spawn(): the day's batch by the schedule's tick (CF-0592) or the console's "
        "«запустить батч сейчас» (CF-0605) - `run_executor.py run` "
        "started detached on purpose: start_new_session, stdin on DEVNULL, stdout "
        "and stderr into the log file schedule/logs/<day>-<channel>.log, so there "
        "is no pipe to drain and nothing to wait for; the tick returns at once. "
        "The batch's ceilings are the executor's own (each stage's timeout_min)."),
    "scripts/brand_ending.py": (
        "main(): ffmpeg encoding a channel's ending clip from raw frames piped "
        "into its stdin (CF-0565). stdout/stderr are not piped - nothing to "
        "drain. One threading.Timer of RENDER_DEADLINE_SECONDS covers the whole "
        "operation (drawing and writing every frame, then wait()); past it the "
        "group is killed (start_new_session), the write breaks, wait() returns "
        "and the script fails."),
    "shared/factrule/claim_answer_claude.py": (
        "run(): one headless `claude -p` of the claim judge (CF-0553). The "
        "prompt goes in and the answer comes out through communicate(timeout=), "
        "the deadline over the whole call; past it the process group is "
        "killed (start_new_session)."),
    "scripts/meme_desk.py": (
        "start_job(): the center's background job `meme_desk.py job-run` "
        "(CF-0755) - start_new_session, stdin on DEVNULL, output into the "
        "job's log file (no pipe to drain), nobody waits on it: the center "
        "reads its state file. The job's own children carry their ceilings "
        "(the plan's max_seconds is their sum)."),
}


def _check(cond, msg, fix=None):
    if not cond:
        raise AssertionError(msg + (f"\n  {fix}" if fix else ""))
    print(f"ok: {msg}")


def _files():
    out = []
    for d in SCANNED:
        out += tg.python_files(ROOT / d, skip=SKIP)
    return out


def _rel(p):
    return p.relative_to(ROOT).as_posix()


def _src(text):
    return ast.parse(text)


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------

def test_the_scan_has_the_root_code_to_scan():
    """A moved directory or a glob that matches nothing must fail here rather
    than turn every check below into a pass over an empty list."""
    files = [_rel(p) for p in _files()]
    for must in ("scripts/meme_desk.py", "scripts/runlog", "shared/runlog/runlog.py",
                 "shared/runlog/supplement.py", "shared/inserts/inserts_lib.py",
                 "rotation/rotate.py"):
        _check(must in files, f"{must} is in the scan")
    _check(not any(f.startswith("shared/footage/") for f in files),
           "the footage pool is pruned, not walked")
    _check(len(files) > 40, f"the scan covers the root's code ({len(files)} files)")


# --------------------------------------------------------------------------
# 1. every waiting call names its ceiling
# --------------------------------------------------------------------------

def test_no_root_code_waits_on_a_child_without_a_ceiling():
    checked, used = 0, set()
    for path in _files():
        tree = tg.parse(path)
        owner = tg.owners(tree)
        for call in tg.subprocess_calls(tree, tg.WAITING_STARTERS):
            checked += 1
            if tg.has_ceiling(call):
                continue
            key = (_rel(path), owner.get(id(call)))
            if key in PASSTHROUGH:
                used.add(key)
                continue
            _check(False, f"{_rel(path)}:{call.lineno} hands subprocess.{call.func.attr} a ceiling",
                   fix="Pass timeout= with the constant its class of call is documented "
                       "against (and turn TimeoutExpired into a verdict), or - for a "
                       "**kw pass-through - name the site in PASSTHROUGH with why.")
    _check(checked >= 20, f"the scan found waiting calls to check ({checked})")
    for key in PASSTHROUGH:
        _check(key in used, f"PASSTHROUGH describes {key[0]}::{key[1]}, which still passes through",
               fix="Drop the entry rather than leave the guard describing code that is gone.")


# --------------------------------------------------------------------------
# 2. the Popen registry, and the pipe rule
# --------------------------------------------------------------------------

def test_no_root_code_starts_a_popen_this_guard_has_not_seen():
    found = {}
    for path in _files():
        for call in tg.popen_calls(tg.parse(path)):
            found.setdefault(_rel(path), []).append(call.lineno)
    unregistered, stale = tg.popen_registry_drift(found, POPEN_SITES)
    for name in unregistered:
        _check(False, f"{name}:{found[name][0]} starts a subprocess.Popen this guard has seen",
               fix="A Popen carries no timeout= to check, so name the site in POPEN_SITES "
                   "with the deadline that covers the whole operation - the reading of "
                   "its pipe included - or use subprocess.run(timeout=).")
    for name in stale:
        _check(False, f"POPEN_SITES describes {name}, which still starts one",
               fix="Drop the entry rather than leave the guard describing code that is gone.")
    _check(len(found) == len(POPEN_SITES) >= 4,
           f"every Popen site in the root is registered ({len(found)})")


def test_no_root_code_reads_a_child_pipe_on_the_thread_that_owns_its_deadline():
    checked = 0
    for path in _files():
        for fn, read in tg.popen_functions(tg.parse(path)):
            checked += 1
            _check(read is None,
                   f"{_rel(path)}:{fn.lineno} {fn.name}() starts a child and leaves the "
                   "reading of its pipe to somewhere that can be bounded"
                   + (f" - line {read.lineno} does not" if read is not None else ""))
    _check(checked >= 4, f"the rule was applied to every function that starts a child ({checked})")


def test_every_supplement_step_names_its_ceiling():
    """supplement._run's deadline is its caller's: a _step() with no timeout=
    is communicate() with none - how the three recheck steps ran until
    CF-0229."""
    path = ROOT / "shared" / "runlog" / "supplement.py"
    steps = [n for n in ast.walk(tg.parse(path))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_step"]
    for call in steps:
        _check(tg.has_ceiling(call), f"supplement.py:{call.lineno} _step() names its timeout=")
    _check(len(steps) >= 4, f"the scan found the supplement's steps ({len(steps)})")


# --------------------------------------------------------------------------
# 3. the guard catches what it is for (negative controls)
# --------------------------------------------------------------------------

def test_the_shared_scan_catches_a_wait_without_a_ceiling():
    bad = _src("import subprocess\n"
               "def f():\n    subprocess.run(['sleep', '9'])\n"
               "def g(**kw):\n    subprocess.check_output(['x'], **kw)\n"
               "def h():\n    subprocess.run(['true'], timeout=5)\n")
    hits = tg.waits_without_ceiling(bad)
    _check([c.lineno for c in hits] == [3, 5],
           "a bare subprocess.run and a **kw pass-through are both caught; a capped one is not")
    owner = tg.owners(bad)
    _check([owner[id(c)] for c in hits] == ["f", "g"], "and each is attributed to its function")


def test_the_shared_scan_catches_a_popen_read_on_the_owning_thread():
    bad = _src("import subprocess, threading\n"
               "def bad():\n    p = subprocess.Popen(['x'], stdout=subprocess.PIPE)\n"
               "    for line in p.stdout:\n        pass\n    p.wait(timeout=5)\n"
               "def good():\n    p = subprocess.Popen(['x'], stdout=subprocess.PIPE)\n"
               "    def reader():\n        for line in p.stdout:\n            pass\n"
               "    threading.Thread(target=reader).start()\n    p.wait(timeout=5)\n")
    got = {fn.name: (read.lineno if read is not None else None)
           for fn, read in tg.popen_functions(bad)}
    _check(got == {"bad": 4, "good": None},
           "the CF-0135 shape is caught; a read on its own thread is not")
    unregistered, stale = tg.popen_registry_drift({"new.py": [3], "old.py": [1]},
                                                  {"old.py": "x", "gone.py": "y"})
    _check(unregistered == ["new.py"] and stale == ["gone.py"],
           "an unregistered Popen and a stale registry entry are both reported")


def test_the_meme_desk_turns_a_hang_into_a_verdict():
    """The behavioural half for the five sites CF-0229 capped: a hang does not
    come back as a value (an empty scene-cut list, a parsed size)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import meme_desk
    real = subprocess.run
    seen = []

    def hang(cmd, *a, **kw):
        seen.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    subprocess.run = hang
    try:
        for name, call in (("run", lambda: meme_desk.run(["yt-dlp", "x"])),
                           ("media_size", lambda: meme_desk.media_size("/x/y.png")),
                           ("scene_cuts", lambda: meme_desk.scene_cuts("/x/y.mp4"))):
            try:
                call()
            except SystemExit as e:
                _check("ceiling" in str(e), f"meme_desk.{name}: a hang stops with the ceiling named")
            else:
                raise AssertionError(f"meme_desk.{name}: a hung child came back as a value")
    finally:
        subprocess.run = real
    _check(seen and all(isinstance(t, (int, float)) and t > 0 for t in seen),
           f"every child the desk started carried a positive ceiling ({seen})")


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
