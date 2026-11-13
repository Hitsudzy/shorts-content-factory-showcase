#!/usr/bin/env python3
"""CF-0815: qc_render.py handed `plan.json <slug>.mp4` instead of `video plan`.

Tech 2026-10-19T0844Z, stage video-editor: both videos' QC died in 0.05 s on
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xdf in position 34` -
`json.load(open(<the mp4>))`, the mp4 read as the plan. Now:

- the swapped pair is read the right way round, and the verdict is the one
  the right-order call gives (same JSON record, byte for byte);
- a plan argument that is not text / not JSON / cut mid-character is a
  sentence naming the file, exit 2, never a traceback;
- frame_judge_pack.py, with the same `video plan` positionals, follows the
  same rule;
- common.run_tool() and common.ffprobe() read tool output that is not UTF-8
  as text with replacement characters instead of raising (common.ffmpeg() is
  left as it is: it is inside the footage usability key).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0815-runlog-")))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import _synthetic_media as M  # noqa: E402
import common  # noqa: E402
import repo_paths  # noqa: E402
import video_plan_args as V  # noqa: E402

# The head of an mp4 as ffmpeg writes it: a 32-byte ftyp box, then the next
# box's size with a 0xdf byte at offset 34 - the batch's exact error.
MP4_HEAD = (b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
            b"\x00\x08\xdf\x26mdat" + bytes(range(256)) * 4)


def _py():
    venv = Path(repo_paths.VENV_PY3)
    return str(venv) if venv.exists() else sys.executable


def _run(argv, cwd):
    return subprocess.run([_py()] + [str(a) for a in argv], capture_output=True, text=True,
                          cwd=cwd, env=dict(os.environ), timeout=120)


def _plan(tmp):
    plan = Path(tmp) / "plan.json"
    plan.write_text(json.dumps({"style": "motion", "blocks": [],
                                "audio": {"duration": 2.0, "src": "voice.wav"},
                                "output": {"width": 1080, "height": 1920, "fps": 25}}))
    return plan


def _clean(r):
    both = r.stdout + r.stderr
    assert "Traceback" not in both and "UnicodeDecodeError" not in both, both[-3000:]


def test_the_batch_failure_is_what_a_binary_plan_does():
    """The stand-in reproduces the crash the old `json.load(open(plan))` had."""
    with tempfile.TemporaryDirectory() as tmp:
        mp4 = Path(tmp) / "googlebook.mp4"
        mp4.write_bytes(MP4_HEAD)
        try:
            with open(mp4, encoding="utf-8") as fh:
                json.load(fh)
        except UnicodeDecodeError as e:
            assert e.start == 34, e
        else:
            raise AssertionError("the stand-in mp4 decoded as UTF-8")


def test_ordered_swaps_only_the_unambiguous_pair():
    with tempfile.TemporaryDirectory() as tmp:
        plan, mp4 = _plan(tmp), Path(tmp) / "v.mp4"
        mp4.write_bytes(MP4_HEAD)
        assert V.ordered(str(mp4), str(plan)) == (str(mp4), str(plan), False)
        assert V.ordered(str(plan), str(mp4)) == (str(mp4), str(plan), True)
        # both JSON / neither / one missing: left as given
        other = Path(tmp) / "other.json"
        other.write_text("{}")
        assert V.ordered(str(plan), str(other))[2] is False
        assert V.ordered(str(mp4), str(mp4))[2] is False
        assert V.ordered(str(plan), str(Path(tmp) / "none.mp4"))[2] is False
        # a BOM and leading whitespace still read as JSON
        bom = Path(tmp) / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf\n  {\"output\": {}}")
        assert V.looks_like_json(bom)


def test_load_plan_says_what_is_wrong_in_a_sentence():
    with tempfile.TemporaryDirectory() as tmp:
        mp4 = Path(tmp) / "v.mp4"
        mp4.write_bytes(MP4_HEAD)
        cut = Path(tmp) / "cut.json"   # cut mid-character: "é" is c3 a9
        cut.write_bytes('{"title": "café"}'.encode()[:-3])
        arr = Path(tmp) / "arr.json"
        arr.write_text("[1, 2]")
        for path, said in ((mp4, "not text"), (cut, "not"), (arr, "not an object"),
                           (Path(tmp) / "none.json", "no plan at")):
            try:
                V.load_plan(path)
            except V.PlanUnreadable as e:
                assert said in str(e) and str(path) in str(e), (path, e)
            else:
                raise AssertionError(f"{path} loaded as a plan")
        assert V.load_plan(_plan(tmp))["output"]["width"] == 1080


def _verdict(stdout, tmp):
    """The --json record with what differs between two runs taken out: the
    clock (`at`) and the temp directory the run sat in."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "at"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x.replace(str(tmp), "<tmp>") if isinstance(x, str) else x
    return strip(json.loads(stdout))


def test_qc_on_the_swapped_pair_gives_the_right_order_verdict():
    """Each order on its own copy (the run writes a score log beside the plan)."""
    runs = {}
    for order in ("right", "swapped"):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(tmp)
            video = M.video_with_audio(Path(tmp) / "googlebook.mp4", 2)
            pair = (video, plan) if order == "right" else (plan, video)
            r = _run([SCRIPTS / "qc_render.py", *pair, "--json"], tmp)
            _clean(r)
            runs[order] = (r.returncode, _verdict(r.stdout, tmp), r.stderr)
    (rc_r, v_r, err_r), (rc_s, v_s, err_s) = runs["right"], runs["swapped"]
    assert rc_r == rc_s, (rc_r, rc_s, err_s[-2000:])
    assert v_r == v_s, (v_r, v_s)
    assert v_r["passed"] is False and any("resolution" in f for f in v_r["failures"]), v_r
    assert "CF-0815" in err_s and "CF-0815" not in err_r


def test_qc_on_a_plan_that_is_not_json_is_a_sentence_and_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "plan.json"
        bad.write_bytes(MP4_HEAD)       # both binary: nothing to swap
        video = Path(tmp) / "v.mp4"
        video.write_bytes(MP4_HEAD)
        r = _run([SCRIPTS / "qc_render.py", video, bad], tmp)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr[-2000:])
        _clean(r)
        assert f"{bad} is not a plan" in r.stderr, r.stderr
        r = _run([SCRIPTS / "qc_render.py", video, bad, "--json"], tmp)
        assert r.returncode == 2
        _clean(r)
        res = json.loads(r.stdout)
        assert res["passed"] is False and res["error"] == "no_plan", res


def test_frame_judge_pack_refuses_a_binary_plan_in_a_sentence():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "plan.json"
        bad.write_bytes(MP4_HEAD)
        video = Path(tmp) / "v.mp4"
        video.write_bytes(MP4_HEAD)
        r = _run([SCRIPTS / "frame_judge_pack.py", video, bad, "--out", Path(tmp) / "out"],
                 tmp)
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr[-2000:])
        _clean(r)
        assert "frame-judge pack refused" in r.stderr and "is not a plan" in r.stderr, r.stderr


def test_frame_judge_pack_reads_the_swapped_pair_the_right_way_round():
    """The swap is taken (the note) and the run gets past the argument check
    to the pack itself - whatever the pack then says about this stand-in."""
    with tempfile.TemporaryDirectory() as tmp:
        plan = _plan(tmp)
        video = M.video_with_audio(Path(tmp) / "v.mp4", 1)
        r = _run([SCRIPTS / "frame_judge_pack.py", plan, video, "--out", Path(tmp) / "out"],
                 tmp)
        _clean(r)
        assert "CF-0815" in r.stderr, r.stderr
        assert "not found" not in r.stderr and "is not a plan" not in r.stderr, r.stderr


def test_tool_output_that_is_not_utf8_is_read_not_raised():
    """common.run_tool / ffprobe: a non-UTF-8 byte on a tool's stdout/stderr
    is a replacement character (the rest of the text intact).

    Not common.ffmpeg(): it is inside the usability key (CF-0406 reach of
    usability_probe.extract_full_frames), so touching it would turn every
    pool shot's usable_cached stamp stale (CF-0048; test_stale_usability_cache.py
    is what says so)."""
    script = ("import sys; sys.stdout.buffer.write(b'ok \\xdf\\x26 end'); "
              "sys.stderr.buffer.write(b'err \\xc3')")
    r = common.run_tool([sys.executable, "-c", script], tool="stand-in", check=False,
                        timeout=30)
    assert r.stdout.startswith("ok ") and r.stdout.endswith(" end"), r.stdout
    assert "\ufffd" in r.stdout and r.stderr.startswith("err "), (r.stdout, r.stderr)
    seen = []
    real = common.runlog.run_child

    def spy(cmd, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    common.runlog.run_child = spy
    try:
        common.ffprobe("-version", timeout=10)
    finally:
        common.runlog.run_child = real
    assert seen[0].get("errors") == "replace" and seen[0]["text"] is True, seen[0]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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
