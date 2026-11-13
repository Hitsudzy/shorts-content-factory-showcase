#!/usr/bin/env python3
"""CF-0305: a render the tool broke before the first frame does not spend
the attempt cap, and the same such failure twice in a row is a stop.

Batch 2026-09-21T0358Z: three `render_failed` with one and the same Remotion
error, ~140 s each, and the video was `needs_you` on "attempt cap 3 reached"
although the error was the tool's (CF-0301) - and after the fix the batch
could not render the video again without going around the cap. The user's
decision of 2026-09-21: a render that drew no frame did not build the video;
it is recorded as `render_broken` with `counted: false`, and the second one
in a row with the same error is `needs_you` `render_broken` naming the
error. A failure after frames were drawn, and every `qc_failed`, counts as
before. An entry written before CF-0305 has no `counted` and counts.

Remotion is a stub `npx` here - no real render runs.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

import attempts  # noqa: E402
import _runlog  # noqa: E402
import render_video  # noqa: E402
import test_attempt_cap as tac  # noqa: E402

# The 0358Z error line as Remotion printed it, with the parts that change
# from run to run (a job dir with pid and hex, a port, a time, a tmp path).
ERR_0358Z = ('Could not extract frame from compositor Error: Can only download URLs '
             'starting with http:// or https://, got "file:///home/x/pipeline/c/b/work/'
             'ted/clips/a06_bYKJxZYd66o_s009.mp4" (job render/jobs/ted-{pid}-{hex}/, '
             'http://localhost:{port}/proxy, at 2026-09-21T09:5{m}:33+00:00, '
             '/var/folders/0p/T/remotion-{hex}/x pid {pid})')


def _err(pid, port, hexid, m):
    return ERR_0358Z.format(pid=pid, port=port, hex=hexid, m=m)


def _broken_npx(error_file):
    """Remotion that bundles, prints `Rendered 0/N` (no frame yet) and dies
    with the error line read from `error_file` plus a stack and a code frame."""
    return ("#!/bin/sh\n"
            "echo 'Bundling 100%'\necho 'Rendered 0/1630'\n"
            f"cat '{error_file}'\n"
            "echo '    at readFile (/x/node_modules/@remotion/renderer/dist/read-file.js:44:41)'\n"
            "echo '12696 |     throw new Error(cleanedUpErrorMessage);'\necho ''\nexit 1\n")


def _midway_npx(error_file):
    return ("#!/bin/sh\n"
            "for i in 1 2 3 4 5; do echo \"Rendered $i/1630, time remaining: 4m 1${i}s\"; done\n"
            f"cat '{error_file}'\nexit 1\n")


def test_signature_ignores_what_changes_between_runs():
    a = attempts.error_signature(_err(4411, 3000, "ab12cd34ef", 8))
    b = attempts.error_signature(_err(9087, 3017, "0099ffee11", 3))
    assert a == b, (a, b)
    assert "Can only download URLs" in a and "a06_bYKJxZYd66o_s009.mp4" in a, a
    other = attempts.error_signature("Error: Could not find composition Video")
    assert other != a
    # the same words, a different file: a different failure
    assert attempts.error_signature(_err(1, 3000, "ab12cd34ef", 8).replace("s009", "s010")) != a


def _batch(tmp, cap=None):
    return tac._batch(tmp, cap=cap)


def test_broken_is_not_counted_and_the_second_identical_one_stops():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp, cap=1)
        attempts.begin(b, slug, "first", toolchain="t1")
        _, ledger, capped = attempts.end(b, slug, attempts.RESULT_RENDER_BROKEN,
                                         detail="remotion exit 1: x",
                                         error=_err(1, 3000, "ab12cd34ef", 1), frames=0)
        assert not capped and ledger["needs_you"] is None
        a = ledger["attempts"][0]
        assert a["counted"] is False and a["frames_rendered"] == 0 and a["error_signature"]
        assert attempts.counted(ledger) == [] and not attempts.exhausted(ledger)
        # a different error is not "the same twice": the tool is tried again
        attempts.begin(b, slug, attempts.auto_reason(ledger), toolchain="t1")
        _, ledger, capped = attempts.end(b, slug, attempts.RESULT_RENDER_BROKEN,
                                         error="rc=1: Error: something else", frames=0)
        assert not capped and ledger["needs_you"] is None
        # the same error again (pid, port, time and tmp paths differ): stop
        attempt, _ = attempts.begin(b, slug, "render_broken", toolchain="t1")
        assert attempt["n"] == 3 and attempts.begun_line(attempt, attempts.load(b, slug)) \
            .startswith("attempt 1/1 begun"), "a broken render spent nothing"
        _, ledger, capped = attempts.end(b, slug, attempts.RESULT_RENDER_BROKEN,
                                         detail="remotion exit 1: other",
                                         error="rc=1:  Error: something  else", frames=0)
        assert capped
        ny = ledger["needs_you"]
        assert ny["reason"] == "render_broken" and ny["attempts"] == 0, ny
        assert ny["error"] == "rc=1:  Error: something  else" and ny["toolchain"] == "t1"
        line = attempts.ledger_needs_you_line(slug, ledger)
        assert line.startswith("NEEDS-YOU vid: render_broken - "), line
        assert "attempt cap" not in line and "remotion exit 1: other" in line, line
        # the ledger mirrored into 05-video-editor.json
        rec = attempts.record_fields(ledger)
        assert [a["counted"] for a in rec["attempts"]] == [False, False, False]
        assert rec["attempts_used"] == 0 and rec["attempts_exhausted"] is True
        assert rec["attempts"][2]["error"] == "rc=1:  Error: something  else"


def test_the_stop_refuses_until_the_code_or_the_plan_changes():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp)
        for _ in range(2):
            attempts.begin(b, slug, "first", toolchain="t1", build_inputs="d1")
            attempts.end(b, slug, attempts.RESULT_RENDER_BROKEN, error="rc=1: Error: x",
                         frames=0)
        try:
            attempts.begin(b, slug, "render_broken", toolchain="t1", build_inputs="d1")
            raise AssertionError("the same code and plan must be refused")
        except attempts.Capped as c:
            assert str(c).startswith("NEEDS-YOU vid: render_broken - "), str(c)
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][-1]["result"] == attempts.RESULT_CAPPED
        # a qc_degrade is refused by the same stop
        try:
            attempts.begin(b, slug, "qc_degrade:1:still", kind=attempts.KIND_QC_DEGRADE,
                           toolchain="t1", build_inputs="d1")
            raise AssertionError("refused")
        except attempts.Capped as c:
            assert "render_broken" in str(c)
        # the fix is committed: a new toolchain fingerprint lifts it, no --cap
        attempt, ledger = attempts.begin(b, slug, "render_broken", toolchain="t2",
                                         build_inputs="d1")
        assert ledger["needs_you"] is None and attempt["n"] == 3, ledger
        assert [a["n"] for a in ledger["attempts"]] == [1, 2, 3], "the capped marker goes"
        lifted = ledger["lifted_needs_you"]
        assert len(lifted) == 1 and lifted[0]["reason"] == "render_broken"
        assert lifted[0]["lifted_by"]["toolchain"] == "t2" and "refused_begin" in lifted[0]
        assert attempts.begun_line(attempt, ledger).startswith("attempt 1/3 begun")

        # the "fix" did not fix it: the same failure right after it is the
        # stop again (the two in a row straddle the lift), then a changed
        # plan lifts it as well
        _, ledger, capped = attempts.end(b, slug, attempts.RESULT_RENDER_BROKEN,
                                         error="rc=1: Error: x", frames=0)
        assert capped and ledger["needs_you"]["reason"] == "render_broken"
        attempt, ledger = attempts.begin(b, slug, "r", toolchain="t2", build_inputs="d2")
        assert ledger["needs_you"] is None and len(ledger["lifted_needs_you"]) == 2


def test_mid_render_failures_and_old_entries_count_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp, cap=2)
        # two different errors: the same one twice is CF-0518's stop
        # (tests/test_render_stuck_on_asset.py)
        for n in range(2):
            attempts.begin(b, slug, "first", toolchain="t1")
            _, ledger, capped = attempts.end(b, slug, attempts.RESULT_RENDER_FAILED,
                                             error=f"rc=1: Error: x{'yz'[n]}", frames=507)
        assert capped and ledger["needs_you"]["reason"] == "attempt cap 2 reached"
        assert [a["counted"] for a in ledger["attempts"]] == [True, True]
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp)
        # the 0358Z ledger as written before CF-0305: no `counted` anywhere
        old = {"slug": slug, "attempt_cap": 3, "cap_source": "default", "needs_you": None,
               "attempts": [{"n": n, "reason": "first", "result": "render_failed",
                             "detail": "remotion exit 1: "} for n in (1, 2, 3)]}
        attempts.save(b, slug, old)
        ledger = attempts.load(b, slug)
        assert len(attempts.counted(ledger)) == 3 and attempts.exhausted(ledger)
        assert [a["counted"] for a in attempts.record_fields(ledger)["attempts"]] == [True] * 3
        assert _runlog._exhausted(old, old["attempts"])


def test_runlog_reads_the_ledger_the_same_way():
    ledger = {"attempt_cap": 1, "needs_you": None,
              "attempts": [{"n": 1, "result": "render_broken", "counted": False}]}
    assert not _runlog._exhausted(ledger, ledger["attempts"])
    assert "render_broken" in _runlog.FAILURES


def test_remotion_watch_frames_and_error_line():
    w = render_video.RemotionWatch()
    for line in ["Bundling 100%", "Rendered 0/1630", _err(1, 3000, "ab12cd34ef", 1),
                 "    at readFile (/x/Error.js:1:1)", "Error: later"]:
        w(line)
    assert w.frames == 0 and w.error.startswith("Could not extract frame"), w.error
    w("Rendered 507/1630, time remaining: 4m 11s")
    assert w.frames == 507
    assert render_video.RemotionWatch().failure_line(["x", "last line", "  "]) == "last line"


def test_render_video_before_the_first_frame_does_not_spend_the_cap():
    """cap 1. Render 1 breaks (error A), render 2 breaks with another error -
    the cap is untouched, so it is tried; render 3 breaks with that error
    again (other pid/port/time) - the stop, naming the error; render 4 is
    refused before Remotion runs. A changed plan lets render 5 run."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp, cap=1)
        err = Path(tmp) / "err.txt"
        env = tac._stub_npx(tmp, _broken_npx(err))
        err.write_text("Error: Could not find composition Video\n")
        r = tac._render(b, slug, plan_path, env)
        assert r.returncode == 1, r.stdout + r.stderr
        first = [l for l in r.stdout.splitlines() if l.strip()][0]
        assert first.startswith("render BROKEN  rc=1  attempt 1/1  (before the first frame"), first
        ledger = attempts.load(b, slug)
        a = ledger["attempts"][0]
        assert a["result"] == "render_broken" and a["counted"] is False, a
        assert a["detail"] == "remotion exit 1: Error: Could not find composition Video", a
        assert a["frames_rendered"] == 0

        for n, (pid, port, m) in enumerate([(4411, 3000, 8), (9087, 3017, 3)], start=2):
            err.write_text(_err(pid, port, "ab12cd34ef" if n == 2 else "0099ffee11", m) + "\n")
            r = tac._render(b, slug, plan_path, env)
            assert r.returncode == 1, r.stdout + r.stderr
            if n == 2:
                assert "NEEDS-YOU" not in r.stdout and "attempt 1/1" in r.stdout, r.stdout
        assert "NEEDS-YOU vid: render_broken - " in r.stdout, r.stdout
        assert "Can only download URLs" in r.stdout and "attempt cap" not in r.stdout, r.stdout
        ledger = attempts.load(b, slug)
        assert ledger["needs_you"]["reason"] == "render_broken"
        assert "Can only download URLs" in ledger["needs_you"]["error"]
        assert attempts.counted(ledger) == []

        r = tac._render(b, slug, plan_path, env)
        assert r.returncode == attempts.EXIT_CAPPED, r.stdout + r.stderr
        assert r.stdout.startswith("NEEDS-YOU vid: render_broken - "), r.stdout
        assert not (b / "logs" / f"{slug}-attempt-4.log").exists()

        # a rebuilt plan (another build_inputs digest) is a fix: rendered again
        plan = json.loads(plan_path.read_text())
        plan["build_inputs"] = {"digest": "rebuilt"}
        plan_path.write_text(json.dumps(plan))
        r = tac._render(b, slug, plan_path, env)
        assert r.returncode == 1 and "render BROKEN" in r.stdout, r.stdout + r.stderr
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][-1]["n"] == 4 and ledger["lifted_needs_you"], ledger


def test_render_video_failure_after_frames_counts():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp, cap=1)
        err = Path(tmp) / "err.txt"
        err.write_text(_err(1, 3000, "ab12cd34ef", 1) + "\n")
        env = tac._stub_npx(tmp, _midway_npx(err))
        r = tac._render(b, slug, plan_path, env)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "render FAILED  rc=1  attempt 1/1  (after 5 frame(s)" in r.stdout, r.stdout
        assert "NEEDS-YOU vid: attempt cap 1 reached - last failure: render_failed (attempt 1): " \
               "remotion exit 1: Could not extract frame" in r.stdout, r.stdout
        a = attempts.load(b, slug)["attempts"][0]
        assert a["result"] == "render_failed" and a["counted"] is True and a["frames_rendered"] == 5


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
