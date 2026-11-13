#!/usr/bin/env python3
"""CF-0098: a hard ceiling on attempts per video, and render logs on disk.

Batch 2026-09-03T2037Z: the Clooney video took 42 minutes and 9.2M cache
reads, nearly all of it re-renders whose Remotion output and QC report were
read back into the operator's context each time. The ceiling ("two attempts
per rung") lived only in SKILL.md. These tests pin the mechanical version:

- the ledger (scripts/attempts.py) round-trips begin/end, and the cap comes
  from channels/<channel>.json#video_editor.max_attempts_per_video (default 3);
- at the cap `begin` exits 3 with the NEEDS-YOU line and writes `needs_you`;
- a CF-0031 degradation rebuild counts like any other attempt;
- render_video.py puts Remotion's output in <batch>/logs/<slug>-attempt-<n>.log
  and prints <= 20 lines (stub npx: 500 lines, exit 1), --verbose restores it;
- qc_render.py ends the attempt and summarises; write_batch_metadata carries
  attempts/attempt_cap/attempts_exhausted/needs_you and the root's
  check_* functions still accept the record.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"
CONTRACTS = next((a / "tests" / "test_pipeline_contracts.py" for a in AGENT_ROOT.parents
                  if (a / "tests" / "test_pipeline_contracts.py").exists()), None)

sys.path.insert(0, str(SCRIPTS))

from repo_paths import VENV_PY  # noqa: E402 - CF-0125: resolved against the main checkout
import attempts  # noqa: E402
import quiet  # noqa: E402
import write_batch_metadata  # noqa: E402


def _batch(tmp, channel="chan", batch="b1", slug="vid", cap=None):
    """A fake <root>/pipeline/<channel>/<batch>/work/<slug>/ with a plan, and
    an optional channels/<channel>.json carrying the cap."""
    root = Path(tmp) / "root"
    b = root / "pipeline" / channel / batch
    work = b / "work" / slug
    work.mkdir(parents=True)
    voice = work / "voice.wav"
    voice.write_bytes(b"RIFF")
    plan = {"blocks": [], "audio": {"src": str(voice), "duration": 2.0},
            "output": {"width": 1080, "height": 1920}, "style": "motion",
            "duration": {}}
    (work / "plan.json").write_text(json.dumps(plan))
    if cap is not None:
        (root / "channels").mkdir()
        (root / "channels" / f"{channel}.json").write_text(
            json.dumps({"id": channel, "video_editor": {"max_attempts_per_video": cap}}))
    return b, slug, work / "plan.json"


def _cli(*args):
    return subprocess.run([VENV_PY, str(SCRIPTS / "attempts.py"), *map(str, args)],
                          capture_output=True, text=True)


def test_ledger_round_trip_and_default_cap():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp)
        r = _cli("begin", b, slug, "--reason", "first")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "attempt 1/3 begun (first)" in r.stdout, r.stdout
        ledger = json.loads((b / "work" / slug / "attempts.json").read_text())
        assert ledger["attempt_cap"] == 3 and ledger["cap_source"] == "default"
        a = ledger["attempts"][0]
        assert a["n"] == 1 and a["result"] is None and a["reason"] == "first"
        assert a["log"] == str((b / "logs" / f"{slug}-attempt-1.log").resolve())

        r = _cli("end", b, slug, "--result", "qc_failed",
                 "--detail", "clip blocks rendered as stills: block 4 (motion 0.32)",
                 "--gate", "frozen")
        assert r.returncode == 0, r.stdout + r.stderr
        ledger = attempts.load(b, slug)
        a = ledger["attempts"][0]
        assert a["result"] == "qc_failed" and a["failed_gates"] == ["frozen"]
        assert a["ended_at"] and "motion 0.32" in a["detail"]
        assert not attempts.exhausted(ledger)
        assert attempts.auto_reason(ledger) == "qc_failed:frozen"

        # end without an open attempt records nothing
        r = _cli("end", b, slug, "--result", "rendered_ok")
        assert r.returncode == 0 and "no open attempt" in r.stderr
        assert len(attempts.load(b, slug)["attempts"]) == 1


def test_cap_from_channel_config():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp, cap=2)
        ledger = attempts.load(b, slug)
        assert ledger["attempt_cap"] == 2, ledger
        assert ledger["cap_source"] == "channels/chan.json#video_editor.max_attempts_per_video"
        # a bad value falls back to the default
        root = b.parent.parent.parent
        (root / "channels" / "chan.json").write_text(
            json.dumps({"video_editor": {"max_attempts_per_video": "three"}}))
        assert attempts.load_cap("chan", root) == (3, "default")
        assert attempts.load_cap("no-such-channel", root) == (3, "default")
    assert attempts.CHANNEL_KEY == "video_editor.max_attempts_per_video"
    assert attempts.DEFAULT_MAX_ATTEMPTS == 3


def test_cap_reached_exit_3_needs_you_line_and_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _ = _batch(tmp, cap=2)
        assert _cli("begin", b, slug, "--reason", "first").returncode == 0
        assert _cli("end", b, slug, "--result", "render_failed",
                    "--detail", "remotion exit 1").returncode == 0
        assert _cli("begin", b, slug, "--reason", "render_failed").returncode == 0
        # the failure that uses up the last attempt says so at once
        r = _cli("end", b, slug, "--result", "qc_failed", "--detail", "black run 0.9s")
        assert r.returncode == 3, r.stdout + r.stderr
        expected = "NEEDS-YOU vid: attempt cap 2 reached - last failure: qc_failed (attempt 2): black run 0.9s"
        assert expected in r.stdout, r.stdout
        # and a further begin is refused with the same line, exit 3
        r = _cli("begin", b, slug, "--reason", "operator")
        assert r.returncode == 3, r.stdout + r.stderr
        assert r.stdout.strip() == expected, r.stdout
        ledger = attempts.load(b, slug)
        assert ledger["needs_you"]["reason"] == "attempt cap 2 reached"
        assert ledger["needs_you"]["last_failure"] == "qc_failed (attempt 2): black run 0.9s"
        assert ledger["needs_you"]["attempts"] == 2
        assert attempts.exhausted(ledger)
        # the refused begin leaves one `capped` marker, not one per refusal
        r = _cli("begin", b, slug, "--reason", "operator")
        assert r.returncode == 3
        ledger = attempts.load(b, slug)
        assert [a["result"] for a in ledger["attempts"]] == ["render_failed", "qc_failed", "capped"]
        fields = attempts.record_fields(ledger)
        assert fields["attempts_exhausted"] is True and fields["attempt_cap"] == 2
        assert fields["needs_you"]["last_failure"] == "qc_failed (attempt 2): black run 0.9s"


def test_degradations_count_against_the_cap():
    """CF-0031's per-block rebuild is an attempt like any other: three
    renders, two of them degraded rebuilds, use up a cap of 3."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp)
        plan = json.loads(plan_path.read_text())
        ledger = attempts.load(b, slug)
        assert attempts.auto_reason(ledger, attempts.degraded_tags(plan)) == "first"
        attempts.begin(b, slug, "first")
        attempts.end(b, slug, "qc_failed", detail="frozen 4", failed_gates=["frozen"])

        plan["degraded_blocks"] = [{"index": 4, "from": "clip", "to": "still",
                                    "reason": "motion 0.32"}]
        tags = attempts.degraded_tags(plan)
        assert tags == ["4:still"]
        ledger = attempts.load(b, slug)
        reason = attempts.auto_reason(ledger, tags)
        assert reason == "degraded:4:still", reason
        attempts.begin(b, slug, reason, degraded=tags)
        attempts.end(b, slug, "qc_failed", detail="frozen 7", failed_gates=["frozen"])

        # same degradation as before -> the reason is the QC failure, not
        # "degraded" again; a new one -> degraded again
        ledger = attempts.load(b, slug)
        assert attempts.auto_reason(ledger, tags) == "qc_failed:frozen"
        plan["degraded_blocks"].append({"index": 7, "from": "clip", "to": "still"})
        tags = attempts.degraded_tags(plan)
        assert attempts.auto_reason(ledger, tags) == "degraded:4:still,7:still"
        attempts.begin(b, slug, "degraded:4:still,7:still", degraded=tags)
        _, ledger, capped = attempts.end(b, slug, "qc_failed", detail="frozen 9")
        assert capped and ledger["needs_you"], ledger
        assert len(attempts.counted(ledger)) == 3
        try:
            attempts.begin(b, slug, "degraded:9:still")
            assert False, "a fourth begin must raise Capped"
        except attempts.Capped as c:
            assert str(c).startswith("NEEDS-YOU vid: attempt cap 3 reached - last failure: qc_failed (attempt 3): frozen 9")


def test_a_recut_is_an_attempt_and_names_itself_once():
    """CF-0367: a rebuild after `resolve_anchors.py --exclude-candidate`
    begins as `recut:<block=shot>`, counts against the cap like any render,
    and the next attempt on the same plan is named by its failure again."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp)
        plan = json.loads(plan_path.read_text())
        assert attempts.recut_tags(plan) == []
        attempts.begin(b, slug, "first")
        attempts.end(b, slug, "qc_failed", detail="subject 6",
                     failed_gates=["subject"])
        plan["recut"] = {"excluded_candidates": [
            {"block": 6, "word_index": 86, "shot": "EmOTDswBfgE:28"}]}
        tags = attempts.recut_tags(plan)
        assert tags == ["6=EmOTDswBfgE:28"], tags
        ledger = attempts.load(b, slug)
        reason = attempts.auto_reason(ledger, [], recut=tags)
        assert reason == "recut:6=EmOTDswBfgE:28", reason
        attempts.begin(b, slug, reason)
        attempts.end(b, slug, "qc_failed", detail="subject 6 again",
                     failed_gates=["subject"])
        ledger = attempts.load(b, slug)
        assert attempts.auto_reason(ledger, [], recut=tags) == "qc_failed:subject"
        assert len(attempts.counted(ledger)) == 2


def _stub_npx(tmp, script):
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    npx = bin_dir / "npx"
    npx.write_text(script)
    npx.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


# CF-0305: one frame is drawn before the failure, so this stays the mid-render
# `render_failed` that counts; the failure before the first frame is
# tests/test_render_broken.py. CF-0518: each run fails on another asset (a
# counter next to the stub) - the same error twice in a row is the
# `render_stuck_on_asset` stop of tests/test_render_stuck_on_asset.py.
NOISY_NPX = "#!/bin/sh\necho 'Rendered 1/10'\nfor i in $(seq 1 500); do echo \"remotion line $i\"; done\n" \
            "c=\"$(dirname \"$0\")/runs\"; n=$(( $(cat \"$c\" 2>/dev/null || echo 0) + 1 )); " \
            "echo $n > \"$c\"\necho \"Error: asset 404 on block a$n\" >&2\nexit 1\n"


def _render(b, slug, plan_path, env, *extra):
    return subprocess.run(
        [VENV_PY, str(SCRIPTS / "render_video.py"), str(plan_path),
         str(b / "videos" / f"{slug}.mp4"), *extra],
        capture_output=True, text=True, env=env)


def test_render_summary_and_log_on_disk():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp)
        env = _stub_npx(tmp, NOISY_NPX)
        r = _render(b, slug, plan_path, env)
        assert r.returncode == 1, r.stdout + r.stderr
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        assert len(lines) <= 20, f"{len(lines)} lines:\n{r.stdout}"
        assert lines[0].startswith("render FAILED  rc=1  attempt 1/3"), lines[0]
        log = b / "logs" / f"{slug}-attempt-1.log"
        assert lines[-1] == f"  log: {log.resolve()}", lines[-1]
        assert any("Error: asset 404" in l for l in lines), r.stdout
        text = log.read_text()
        assert text.count("remotion line ") == 500, "the full output must land in the log"
        assert "Error: asset 404" in text
        assert text.splitlines()[0].startswith("=== render_video (remotion+ffmpeg) ")
        assert "=== end render_video (remotion+ffmpeg) rc=1 lines=502 ===" in text
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][0]["result"] == "render_failed"
        assert "remotion exit 1" in ledger["attempts"][0]["detail"]
        assert ledger["attempts"][0]["log"] == str(log.resolve())

        # --verbose: the old firehose on the terminal, and still in the log
        r = _render(b, slug, plan_path, env, "--verbose")
        assert r.returncode == 1
        streamed = [l for l in r.stdout.splitlines() if l.startswith("remotion line ")]
        assert len(streamed) == 500, f"{len(streamed)} streamed lines"
        log2 = b / "logs" / f"{slug}-attempt-2.log"
        assert log2.read_text().count("remotion line ") == 500

        # third fails too -> the failure that used up the cap prints NEEDS-YOU
        r = _render(b, slug, plan_path, env)
        assert r.returncode == 1
        assert "NEEDS-YOU vid: attempt cap 3 reached - last failure: render_failed (attempt 3)" in r.stdout, r.stdout
        # fourth is refused before Remotion runs: exit 3, one line, no new log
        r = _render(b, slug, plan_path, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert r.stdout.strip().startswith("NEEDS-YOU vid: attempt cap 3 reached - last failure: render_failed (attempt 3): remotion exit 1"), r.stdout
        assert not (b / "logs" / f"{slug}-attempt-4.log").exists()
        assert sorted(p.name for p in (b / "logs").iterdir()) == [
            f"{slug}-attempt-1.log", f"{slug}-attempt-2.log", f"{slug}-attempt-3.log"]


def test_plan_outside_a_batch_keeps_the_old_behaviour():
    """A plan in a temp dir has no ledger and no log: no cap, output on the
    terminal as before CF-0098 (every existing test renders that way)."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp)
        loose = Path(tmp) / "loose.json"
        shutil.copy(plan_path, loose)
        env = _stub_npx(tmp, NOISY_NPX)
        for _ in range(4):
            r = subprocess.run([VENV_PY, str(SCRIPTS / "render_video.py"), str(loose),
                                str(Path(tmp) / "out.mp4")],
                               capture_output=True, text=True, env=env)
            assert r.returncode == 1, r.stdout + r.stderr
            streamed = [l for l in r.stdout.splitlines() if l.startswith("remotion line ")]
            assert len(streamed) == 500, f"{len(streamed)} streamed lines"
        assert not (b / "logs").exists()
        assert attempts.batch_context(loose) is None


def _synthetic_video(tmp):
    out = Path(tmp) / "synth.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(out)], check=True)
    return out


def test_qc_summary_ends_attempt_and_metadata_carries_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp)
        synth = _synthetic_video(tmp)
        env = _stub_npx(tmp, f"#!/bin/sh\necho remotion ok\ncp {synth} \"$5\"\n")
        r = _render(b, slug, plan_path, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "render OK  rc=0  attempt 1/3" in r.stdout
        mp4 = b / "videos" / f"{slug}.mp4"
        assert attempts.open_attempt(attempts.load(b, slug)) is not None

        # the plan says the voice is 2.0s and the picture is 2.0s: PASS
        r = subprocess.run([VENV_PY, str(SCRIPTS / "qc_render.py"), str(mp4), str(plan_path)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        assert len(lines) <= 20 and lines[0].startswith("qc PASS  rc=0  attempt 1/3"), r.stdout
        log = b / "logs" / f"{slug}-attempt-1.log"
        assert lines[-1] == f"  log: {log.resolve()}"
        text = log.read_text()
        assert "=== qc_render " in text and '"passed": true' in text
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][0]["result"] == "rendered_ok"

        # a re-run with no open attempt records and logs nothing new
        before = log.read_text()
        r = subprocess.run([VENV_PY, str(SCRIPTS / "qc_render.py"), str(mp4), str(plan_path),
                            "--json"], capture_output=True, text=True)
        assert r.returncode == 0 and json.loads(r.stdout)["passed"]
        assert log.read_text() == before
        assert len(attempts.load(b, slug)["attempts"]) == 1

        # a failing attempt: the plan now claims a 5s voice -> duration gate
        plan = json.loads(plan_path.read_text())
        plan["audio"]["duration"] = 5.0
        plan_path.write_text(json.dumps(plan))
        r = _render(b, slug, plan_path, env)
        assert r.returncode == 0 and "attempt 2/3" in r.stdout, r.stdout
        r = subprocess.run([VENV_PY, str(SCRIPTS / "qc_render.py"), str(mp4), str(plan_path)],
                           capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        assert lines[0].startswith("qc FAIL  rc=1  attempt 2/3"), lines[0]
        assert any(l.startswith("  FAIL: picture runs") for l in lines), r.stdout
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][1]["result"] == "qc_failed"
        assert ledger["attempts"][1]["failed_gates"] == ["duration"]
        assert ledger["attempts"][1]["reason"] == "operator"
        assert attempts.auto_reason(ledger) == "qc_failed:duration"

        # write_batch_metadata mirrors the ledger
        r = subprocess.run([VENV_PY, str(SCRIPTS / "write_batch_metadata.py"), str(b),
                            "--video", "s1", str(plan_path), str(mp4)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ATTEMPTS: s1 2/3" in r.stderr, r.stderr
        v = json.load(open(b / "05-video-editor.json"))["videos"][0]
        assert v["attempt_cap"] == 3 and v["attempts_exhausted"] is False
        assert v["needs_you"] is None
        assert [a["result"] for a in v["attempts"]] == ["rendered_ok", "qc_failed"]
        assert v["attempts"][1]["log"] == str((b / "logs" / f"{slug}-attempt-2.log").resolve())
        _accepted_by_root_contract(v)


def _accepted_by_root_contract(v):
    if CONTRACTS is None:
        print("  (root tests/test_pipeline_contracts.py not found - contract check skipped)")
        return
    sys.path.insert(0, str(CONTRACTS.parent))
    import test_pipeline_contracts as tpc
    ctx = f"video {v['script_id']}"
    tpc.require(v, ["script_id", "output_path"], ctx)
    tpc.check_insert_provenance(v, ctx)
    tpc.check_meme_pair(v, ctx)
    tpc.check_sound_pair(v, ctx)
    tpc.check_proof_provenance(v, ctx)
    tpc.check_proof_pair(v, ctx)


def test_video_record_carries_needs_you_and_summary_cap():
    """video_record() with an exhausted ledger, and quiet.summary()'s cap."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path = _batch(tmp, cap=1)
        attempts.begin(b, slug, "first")
        attempts.end(b, slug, "qc_failed", detail="frozen 4", failed_gates=["frozen"])
        plan = json.loads(plan_path.read_text())
        qc = {"passed": False, "failures": ["frozen 4"], "notes": []}
        v = write_batch_metadata.video_record("s1", plan, str(b / "videos" / "s1.mp4"),
                                              qc, None, ledger=attempts.load(b, slug))
        assert v["attempt_cap"] == 1 and v["attempts_exhausted"] is True
        assert v["needs_you"]["last_failure"] == "qc_failed (attempt 1): frozen 4"
        assert v["attempts"][0]["reason"] == "first"
        _accepted_by_root_contract(v)
        empty = write_batch_metadata.video_record("s2", plan, "x.mp4", qc, None)
        assert empty["attempts"] == [] and empty["attempt_cap"] is None
        assert empty["attempts_exhausted"] is False and empty["needs_you"] is None
        _accepted_by_root_contract(empty)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        printed = quiet.summary([f"line {i}" for i in range(60)], "/tmp/x.log")
    assert len(printed) == 20 and printed[-1] == "  log: /tmp/x.log"
    assert printed[-2].startswith("  ... ") and "more line(s) in the log" in printed[-2]
    assert buf.getvalue().count("\n") == 20


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
