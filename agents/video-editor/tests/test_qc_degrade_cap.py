#!/usr/bin/env python3
"""CF-0415: a degradation QC itself suggested is not an attempt.

Batch `example-film/2026-09-27T0929Z`, rebuild `2026-09-27T1757Z`: backrooms
went to `needs_you` over a 1.8s freeze because every `--degrade-block`
rebuild QC asked for spent one of the three attempts. The user's decision of
2026-09-28: the render whose only change is QC's own hint is a `qc_degrade`,
counted against `video_editor.max_qc_degrades_per_video` (default 3), not
against the attempt cap. These tests pin:

- 3 degradations + 1 attempt give no `needs_you`, the 4th degradation does;
- a video whose attempt cap is used up still takes the degradation QC named;
- a rebuild that also re-resolved (new build_inputs digest), that degrades a
  block QC did not name, that takes a degradation back, or that has no QC
  hint behind it is an ordinary attempt;
- build_render_plan's digest sees every input but `--degrade-block`;
- `_runlog` (the event numbering) agrees with attempts.exhausted();
- 05-video-editor.json carries `kind`, `qc_hint`, `attempts_used`,
  `qc_degrades_used` and `qc_degrade_cap`;
- render_video.py begins a `qc_degrade` off the plan on disk.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from repo_paths import VENV_PY  # noqa: E402
import attempts  # noqa: E402
import quiet  # noqa: E402
import _runlog  # noqa: E402
import write_batch_metadata  # noqa: E402


def _batch(tmp, channel="chan", slug="vid", cap=None, degrade_cap=None):
    root = Path(tmp) / "root"
    b = root / "pipeline" / channel / "b1"
    work = b / "work" / slug
    work.mkdir(parents=True)
    voice = work / "voice.wav"
    voice.write_bytes(b"RIFF")
    plan = {"blocks": [], "audio": {"src": str(voice), "duration": 2.0},
            "output": {"width": 1080, "height": 1920}, "style": "motion",
            "duration": {}, "degraded_blocks": [],
            "build_inputs": {"digest": "d1"}}
    (work / "plan.json").write_text(json.dumps(plan))
    ve = {}
    if cap is not None:
        ve["max_attempts_per_video"] = cap
    if degrade_cap is not None:
        ve["max_qc_degrades_per_video"] = degrade_cap
    if ve:
        (root / "channels").mkdir()
        (root / "channels" / f"{channel}.json").write_text(
            json.dumps({"id": channel, "video_editor": ve}))
    return b, slug, work / "plan.json", plan


def _degrade(plan, *indices, digest=None, to="still"):
    out = json.loads(json.dumps(plan))
    for i in indices:
        out["degraded_blocks"].append({"index": i, "from": "clip", "to": to,
                                       "reason": "frozen"})
    if digest is not None:
        out["build_inputs"] = {"digest": digest}
    return out


def _render(b, slug, plan, result="qc_failed", frozen=()):
    """One render the way render_video.py + qc_render.py record it."""
    ledger = attempts.load(b, slug)
    kind, reason = attempts.classify(ledger, plan)
    attempt, _ = attempts.begin(b, slug, reason, kind=kind,
                                degraded=attempts.degraded_tags(plan),
                                build_inputs=attempts.plan_digest(plan))
    _, ledger, capped = attempts.end(
        b, slug, result, detail=f"frozen {list(frozen)}" if frozen else None,
        failed_gates=["frozen"] if frozen else None,
        qc_hint=attempts.qc_hint_tags(frozen))
    return attempt, ledger, capped


def test_three_degrades_and_one_attempt_do_not_need_you():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp)
        a, ledger, capped = _render(b, slug, plan, frozen=[4])
        assert a["kind"] == "attempt" and a["reason"] == "first" and not capped
        assert ledger["attempts"][-1]["qc_hint"] == ["4:still"]
        p = _degrade(plan, 4)
        a, ledger, capped = _render(b, slug, p, frozen=[7])
        assert a["kind"] == "qc_degrade" and a["reason"] == "qc_degrade:4:still", a
        assert a["n"] == 2 and a["log"].endswith("vid-attempt-2.log")
        p = _degrade(p, 7)
        a, ledger, capped = _render(b, slug, p, frozen=[9])
        assert a["kind"] == "qc_degrade" and not capped
        p = _degrade(p, 9)
        a, ledger, capped = _render(b, slug, p, frozen=[11])
        assert a["kind"] == "qc_degrade" and not capped
        assert len(attempts.counted(ledger)) == 1
        assert len(attempts.qc_degrades(ledger)) == 3
        assert ledger["needs_you"] is None and not attempts.exhausted(ledger)
        assert ledger["qc_degrade_cap"] == 3 and ledger["qc_degrade_cap_source"] == "default"

        # the fourth degradation QC asks for is refused: needs_you on the
        # degrade cap, while two attempts are still unspent
        p = _degrade(p, 11)
        kind, reason = attempts.classify(attempts.load(b, slug), p)
        assert kind == "qc_degrade", (kind, reason)
        try:
            attempts.begin(b, slug, reason, kind=kind, build_inputs="d1")
            assert False, "a fourth qc_degrade must raise Capped"
        except attempts.Capped as c:
            assert str(c).startswith(
                "NEEDS-YOU vid: qc degrade cap 3 reached - last failure: "
                "qc_failed (render 4, qc degrade): frozen [11]"), str(c)
        ledger = attempts.load(b, slug)
        assert ledger["needs_you"]["reason"] == "qc degrade cap 3 reached"
        assert ledger["needs_you"]["attempts"] == 1 and ledger["needs_you"]["qc_degrades"] == 3
        assert ledger["attempts"][-1]["result"] == "capped"
        assert attempts.ledger_needs_you_line(slug, ledger).startswith(
            "NEEDS-YOU vid: qc degrade cap 3 reached")


def test_degrade_cap_from_channel_and_attempts_used_up():
    """The backrooms shape: the attempt cap is gone and QC names a freeze -
    the degradation is still open, and `end` does not stop the video."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp, cap=1, degrade_cap=2)
        a, ledger, capped = _render(b, slug, plan, frozen=[3, 11])
        assert ledger["attempt_cap"] == 1 and ledger["qc_degrade_cap"] == 2
        assert ledger["qc_degrade_cap_source"] == "channels/chan.json#video_editor.max_qc_degrades_per_video"
        assert not capped and ledger["needs_you"] is None, ledger["needs_you"]
        assert attempts.degrade_available(ledger)
        p = _degrade(plan, 3, 11)
        a, ledger, capped = _render(b, slug, p, frozen=[5])
        assert a["kind"] == "qc_degrade" and not capped
        p = _degrade(p, 5)
        a, ledger, capped = _render(b, slug, p, frozen=[6])
        # attempts used up, degrade cap used up, QC still failing: the stop
        # is written at `end`, and it names the degrade cap
        assert capped and ledger["needs_you"]["reason"] == "qc degrade cap 2 reached", ledger
    # a failure with no hint on the last attempt stops on the attempt cap
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp, cap=1)
        _, ledger, capped = _render(b, slug, plan, frozen=[])
        assert capped and ledger["needs_you"]["reason"] == "attempt cap 1 reached"


def test_anything_but_the_hint_is_an_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp)
        _render(b, slug, plan, frozen=[3])
        ledger = attempts.load(b, slug)
        # re-resolve: same degradation, new storyboard -> new digest
        kind, reason = attempts.classify(ledger, _degrade(plan, 3, digest="d2"))
        assert kind == "attempt" and reason == "degraded:3:still", (kind, reason)
        # a block QC did not name
        assert attempts.classify(ledger, _degrade(plan, 3, 5))[0] == "attempt"
        assert attempts.classify(ledger, _degrade(plan, 5))[0] == "attempt"
        # a different rung than QC's hint
        assert attempts.classify(ledger, _degrade(plan, 3, to="typographic"))[0] == "attempt"
        # a plan without a digest (built before CF-0415 or by hand)
        bare = _degrade(plan, 3)
        del bare["build_inputs"]
        assert attempts.classify(ledger, bare)[0] == "attempt"
        # nothing changed at all -> a plain re-render, an attempt
        assert attempts.classify(ledger, plan) == ("attempt", "qc_failed:frozen")
        # the hint applied, as QC asked -> qc_degrade
        assert attempts.classify(ledger, _degrade(plan, 3)) == ("qc_degrade", "qc_degrade:3:still")

        # a failure QC named no degradation for (subject, bed, ...): the
        # degraded rebuild after it is an attempt
        attempts.begin(b, slug, "x", kind="qc_degrade", degraded=["3:still"],
                       build_inputs="d1")
        attempts.end(b, slug, "qc_failed", detail="subject 6", failed_gates=["subject"])
        ledger = attempts.load(b, slug)
        assert attempts.pending_hint(ledger) == []
        assert attempts.classify(ledger, _degrade(plan, 3, 6))[0] == "attempt"
    # taking a degradation back is not a degradation
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp)
        p = _degrade(plan, 3)
        _render(b, slug, p, frozen=[5])
        swapped = _degrade(plan, 5)
        assert attempts.classify(attempts.load(b, slug), swapped)[0] == "attempt"
    # a render that failed outright leaves no hint either
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp)
        attempts.begin(b, slug, "first", build_inputs="d1")
        attempts.end(b, slug, "render_failed", qc_hint=["3:still"])
        ledger = attempts.load(b, slug)
        assert ledger["attempts"][-1]["qc_hint"] == []
        assert attempts.classify(ledger, _degrade(plan, 3))[0] == "attempt"


def test_build_inputs_digest_sees_everything_but_degrade_block():
    with tempfile.TemporaryDirectory() as tmp:
        sb = Path(tmp) / "storyboard.json"
        sb.write_text('{"blocks": [1]}')
        base = {"storyboard": str(sb), "output": str(Path(tmp) / "plan.json"),
                "degrade_block": [], "channel": "example-film", "index": [str(sb)]}
        d1 = attempts.build_inputs(base)["digest"]
        assert attempts.build_inputs(dict(base, degrade_block=["3:still:frozen"]))["digest"] == d1
        assert attempts.build_inputs(dict(base, output="/elsewhere.json"))["digest"] == d1
        assert attempts.build_inputs(dict(base, channel="other"))["digest"] != d1
        sb.write_text('{"blocks": [2]}')     # re-resolve at the same path
        assert attempts.build_inputs(base)["digest"] != d1
        assert attempts.plan_digest({"build_inputs": attempts.build_inputs(base)})
        assert attempts.plan_digest({}) is None
    assert attempts.qc_hint_tags([11, 3, 3]) == ["3:still", "11:still"]
    assert attempts.qc_hint_tags([]) == []


def test_runlog_numbering_agrees_with_the_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, _, plan = _batch(tmp, cap=1)
        _render(b, slug, plan, frozen=[3])
        data = json.loads(attempts.ledger_path(b, slug).read_text())
        ledger = attempts.load(b, slug)
        assert _runlog._exhausted(data, data["attempts"]) is attempts.exhausted(ledger) is False
        # the next render (a qc_degrade) is render 2 on the events
        assert _runlog.current_attempt(b, slug) == 2
        _render(b, slug, _degrade(plan, 3), frozen=[])
        data = json.loads(attempts.ledger_path(b, slug).read_text())
        ledger = attempts.load(b, slug)
        assert ledger["needs_you"] and attempts.exhausted(ledger)
        assert _runlog._exhausted(data, data["attempts"]) is True
        assert _runlog.current_attempt(b, slug) == 2


def test_metadata_and_labels_carry_both_ceilings():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path, plan = _batch(tmp)
        _render(b, slug, plan, frozen=[4])
        p = _degrade(plan, 4)
        a, ledger, _ = _render(b, slug, p, result="rendered_ok")
        assert quiet.attempt_label(a, ledger) == "qc degrade 1/3 (render 2)"
        assert quiet.attempt_label(ledger["attempts"][0], ledger) == "attempt 1/3"
        qc = {"passed": True, "failures": [], "notes": []}
        v = write_batch_metadata.video_record("s1", p, str(b / "videos" / "s1.mp4"),
                                              qc, None, ledger=ledger)
        assert v["attempts_used"] == 1 and v["qc_degrades_used"] == 1
        assert v["qc_degrade_cap"] == 3 and v["attempt_cap"] == 3
        assert [x["kind"] for x in v["attempts"]] == ["attempt", "qc_degrade"]
        assert v["attempts"][0]["qc_hint"] == ["4:still"]
        assert v["attempts"][1]["build_inputs"] == "d1"
        empty = write_batch_metadata.video_record("s2", plan, "x.mp4", qc, None)
        assert empty["attempts_used"] == 0 and empty["qc_degrades_used"] == 0
        assert empty["qc_degrade_cap"] is None


def test_render_video_begins_a_qc_degrade_off_the_plan():
    """render_video.py classifies the render itself: the stub Remotion
    fails, but the entry it began is a qc_degrade and no attempt was spent."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan_path, plan = _batch(tmp, cap=1)
        attempts.begin(b, slug, "first", build_inputs="d1")
        attempts.end(b, slug, "qc_failed", detail="frozen 3", failed_gates=["frozen"],
                     qc_hint=["3:still"])
        plan_path.write_text(json.dumps(_degrade(plan, 3)))
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        (bin_dir / "npx").write_text("#!/bin/sh\necho 'Error: stub' >&2\nexit 1\n")
        (bin_dir / "npx").chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        r = subprocess.run([VENV_PY, str(SCRIPTS / "render_video.py"), str(plan_path),
                            str(b / "videos" / f"{slug}.mp4"), "--bare-voice"],
                           capture_output=True, text=True, env=env, timeout=120)
        ledger = attempts.load(b, slug)
        entry = ledger["attempts"][1]
        assert entry["kind"] == "qc_degrade", (entry, r.stdout, r.stderr)
        assert entry["reason"] == "qc_degrade:3:still" and entry["build_inputs"] == "d1"
        assert "qc degrade 1/3 (render 2)" in r.stdout, r.stdout
        assert len(attempts.counted(ledger)) == 1


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
