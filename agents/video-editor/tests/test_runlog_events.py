#!/usr/bin/env python3
"""CF-0107, Video Editor part: every script of the stage writes `start` and
`done`/`failed` events to the batch's RUN_EVENTS.jsonl through the root's
shared/runlog library (stage video-editor, `video` = the slug read off
work/<slug>/, `attempt` = the CF-0098 ledger's number - never one the
scripts invent); every external binary (Remotion through quiet.run_logged,
ffmpeg/ffprobe, the qc_asset.py / smart_crop.py gate tools) and every
in-process macOS Vision call is a `child` event with the script's event as
parent; with no batch to write to nothing is written and the output is the
same.

Everything runs offline, in seconds: the render against the stub `npx` of
test_attempt_cap.py (which copies a 2 s lavfi mp4 into place), qc_render.py
on that file, write_batch_metadata.py on top, build_render_plan.py on a
one-still storyboard with the gate tools faked at the seam
test_asset_tool_timeout.py already uses, and the Vision call sites with
their in-process halves stubbed.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

TMP = tmp_root("ve-runlog-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # never touch ~/.shorts-content-factory
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import _runlog  # noqa: E402
from _runlog import runlog, video_attempt  # noqa: E402
import attempts  # noqa: E402
import quiet  # noqa: E402
import smart_crop  # noqa: E402
import detect_text_band  # noqa: E402
import vision_client  # noqa: E402
import build_render_plan as brp  # noqa: E402
from common import FFMPEG  # noqa: E402
# The fake batch / stub npx / lavfi video of the CF-0098 tests and the
# subprocess.run fake of the CF-0077 tests (importing them runs nothing).
import test_attempt_cap as tac  # noqa: E402
import test_asset_tool_timeout as tat  # noqa: E402

PY = repo_paths.VENV_PY3 if Path(repo_paths.VENV_PY3).exists() else sys.executable
STAGE = "video-editor"


def _events(batch):
    path = Path(batch) / "RUN_EVENTS.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _scripts(events, step=None):
    return [e for e in events if e["kind"] == "script" and (step is None or e["step"] == step)]


def _children(events, parent=None, tool=None):
    return [e for e in events if e["kind"] == "child"
            and (parent is None or e["parent"] == parent)
            and (tool is None or e["tool"] == tool)]


def _env(batch=None, base=None):
    env = dict(base or os.environ)
    env.pop("RUNLOG_BATCH", None)
    env.pop("RUNLOG_PARENT", None)
    env["RUNLOG_STATE_DIR"] = str(TMP / "state")
    if batch is not None:
        env["RUNLOG_BATCH"] = str(batch)
    return env


@contextlib.contextmanager
def _batch_env(batch):
    saved = os.environ.get("RUNLOG_BATCH")
    if batch is None:
        os.environ.pop("RUNLOG_BATCH", None)
    else:
        os.environ["RUNLOG_BATCH"] = str(batch)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("RUNLOG_BATCH", None)
        else:
            os.environ["RUNLOG_BATCH"] = saved


@contextlib.contextmanager
def _argv(*args):
    saved = sys.argv
    sys.argv = list(args)
    try:
        yield
    finally:
        sys.argv = saved


def _call_cli(fn):
    """Run a decorated cli() in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn()
        except SystemExit as e:
            if isinstance(e.code, str):
                print(e.code, file=sys.stderr)
                code = 1
            else:
                code = e.code or 0
    return code, out.getvalue(), err.getvalue()


def _run(script, *args, env):
    return subprocess.run([PY, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, env=env, timeout=120)


# --------------------------------------------------------------------------
# the shim
# --------------------------------------------------------------------------

def test_shim_resolves_the_root_from_inside_this_checkout():
    """The ancestor walk finds shared/runlog/runlog.py whether this repo is the
    normal agents/video-editor checkout or a worktree under .claude/worktrees/."""
    root = _runlog.factory_root()
    assert (root / "shared" / "runlog" / "runlog.py").is_file(), root
    assert (root / "README.md").is_file() and (root / "agents").is_dir(), f"{root} is not the factory root"
    assert REPO.resolve().is_relative_to(root), (REPO, root)
    assert Path(runlog.__file__).resolve() == (root / "shared" / "runlog" / "runlog.py").resolve()
    assert hasattr(runlog, "script") and hasattr(runlog, "child") and hasattr(runlog, "run_child")


def test_shim_prefers_the_checkout_over_a_factory_root_without_the_library():
    """The layer tests point FACTORY_ROOT at a synthetic root (channels/, a
    sound library) that has no shared/runlog - the accounting still goes to
    the real root above this checkout."""
    fake = TMP / "fake-root"
    (fake / "channels").mkdir(parents=True, exist_ok=True)
    saved = os.environ.get("FACTORY_ROOT")
    os.environ["FACTORY_ROOT"] = str(fake)
    try:
        root = _runlog.factory_root()
    finally:
        if saved is None:
            os.environ.pop("FACTORY_ROOT", None)
        else:
            os.environ["FACTORY_ROOT"] = saved
    assert (root / "shared" / "runlog" / "runlog.py").is_file() and root != fake, root


def test_shim_survives_a_missing_root_with_the_silent_stand_in():
    orphan = TMP / "orphan"
    orphan.mkdir(exist_ok=True)
    (orphan / "_runlog.py").write_bytes((SCRIPTS / "_runlog.py").read_bytes())
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_ROOT"}
    env["PYTHONPATH"] = str(orphan)
    code = "import _runlog; print(type(_runlog.runlog).__name__)"
    cp = subprocess.run([PY, "-c", code], env=env, cwd=str(orphan),
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0 and cp.stdout.strip() == "_Silent", (cp.stdout, cp.stderr)
    assert "factory root not found" in cp.stderr


def test_video_attempt_reads_the_slug_off_the_path_and_the_number_the_work_belongs_to():
    """CF-0177: the number is the attempt the work belongs to - the open one,
    or the one begin() would hand out next. Before the first begin() that is
    1, not null: the assets a video is being prepared from are prepared for
    attempt 1, and a step that runs 37 times inside one attempt has to read
    as one attempt rather than 37."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp)
        assert video_attempt(plan) == {"video": slug, "attempt": 1}        # no ledger yet
        assert video_attempt(b / "work" / slug / "clips" / "c1.mp4") == {"video": slug, "attempt": 1}
        assert video_attempt(Path(tmp) / "plan.json") == {}                # not under work/<slug>/
        attempts.begin(b, slug, "first", cap=3)
        assert video_attempt(plan) == {"video": slug, "attempt": 1}        # open: its own number
        attempts.end(b, slug, attempts.RESULT_QC_FAILED, detail="frozen", cap=3)
        assert video_attempt(plan) == {"video": slug, "attempt": 2}        # ended: the next one
        attempts.begin(b, slug, "qc_failed", cap=3)
        assert video_attempt(plan) == {"video": slug, "attempt": 2}
        attempts.end(b, slug, attempts.RESULT_QC_FAILED, detail="frozen", cap=3)
        attempts.begin(b, slug, "qc_failed", cap=3)
        attempts.end(b, slug, attempts.RESULT_QC_FAILED, detail="frozen", cap=3)
        # the cap is used up: begin() would refuse, so there is no attempt 4
        assert video_attempt(plan) == {"video": slug, "attempt": 3}


def test_a_rendered_video_does_not_predict_another_attempt():
    """CF-0177: the prediction stops where the ledger says the work is over -
    what runs after a `rendered_ok` (the batch metadata) belongs to the
    attempt that rendered it, not to an attempt nobody will make."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp)
        attempts.begin(b, slug, "first", cap=3)
        attempts.end(b, slug, attempts.RESULT_OK, cap=3)
        assert video_attempt(plan) == {"video": slug, "attempt": 1}


def test_argv_video_attempt_names_the_video_before_the_script_parses_anything():
    """CF-0177: `video_script` has to know the slug before the start line is
    written, and the command line is all it has."""
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp)
        mp4 = b / "videos" / f"{slug}.mp4"
        both = {"video": slug, "attempt": 1}
        # any argument that is a path under <batch>/work/<slug>/ names the video
        assert _runlog.argv_video_attempt([str(plan), str(mp4)]) == both
        assert _runlog.argv_video_attempt(["--plan", str(plan), "--json"]) == both
        assert _runlog.argv_video_attempt([str(mp4), "--json"]) == {}       # nothing under work/
        # two videos on one line: the event belongs to the batch, not a video
        other = b / "work" / "second-slug"
        other.mkdir(parents=True)
        assert _runlog.argv_video_attempt([str(plan), str(other / "plan.json")]) == {}
        # the slug as a bare argument (attempts.py begin <batch> <slug>)
        named = ["begin", str(b), slug, "--reason", "first"]
        assert _runlog.argv_video_attempt(named, video_arg=2, batch_arg=1) == both
        assert _runlog.argv_video_attempt(["show", str(b)], video_arg=2, batch_arg=1) == {}


# --------------------------------------------------------------------------
# render -> qc -> metadata as subprocesses under RUNLOG_BATCH
# --------------------------------------------------------------------------

def test_render_qc_and_metadata_leave_script_events_with_slug_attempt_and_children():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp)
        synth = tac._synthetic_video(tmp)
        env = _env(b, tac._stub_npx(tmp, f"#!/bin/sh\necho remotion ok\ncp {synth} \"$5\"\n"))

        # render: begins attempt 1; the event carries the number begin() handed out
        r = tac._render(b, slug, plan, env)
        assert r.returncode == 0 and "render OK  rc=0  attempt 1/3" in r.stdout, r.stdout + r.stderr
        assert "[runlog]" not in r.stderr, r.stderr
        events = _events(b)
        render = _scripts(events, "render")
        assert [e["status"] for e in render] == ["start", "done"], render
        start, done = render
        assert start["id"] == done["id"] and start["stage"] == STAGE and start["name"] == "render_video.py"
        # CF-0177: the slug is on BOTH halves - video_script reads it off the
        # command line before the start line is written, which is what makes
        # the pair a per-video pair the summary can count attempts from. The
        # number is still annotate()'s: begin() hands it out after the start.
        assert start["video"] == slug and start["attempt"] == 1, start
        assert done["video"] == slug and done["attempt"] == 1, done
        assert done["ts"].endswith("Z") and isinstance(done["duration_s"], (int, float))
        # CF-0434: after the render the file is probed for the score log's
        # render stage - an ffprobe child of the same script, after remotion.
        children = _children(events, parent=start["id"])
        assert [c["tool"] for c in children][:2] == ["remotion", "remotion"], children
        assert {c["tool"] for c in children[2:]} <= {"ffprobe"}, children
        remotion = [c for c in children if c["tool"] == "remotion"]
        assert [(c["tool"], c["status"]) for c in remotion] == [("remotion", "start"), ("remotion", "done")], remotion
        assert remotion[1]["rc"] == 0 and remotion[1]["argv"][:3] == ["npx", "remotion", "render"], remotion[1]
        assert remotion[1]["video"] == slug and remotion[1]["attempt"] == 1 and remotion[1]["step"] == "render"

        # qc: ends attempt 1; ffmpeg/ffprobe probes are its children
        mp4 = b / "videos" / f"{slug}.mp4"
        r = _run("qc_render.py", mp4, plan, env=env)
        assert r.returncode == 0 and r.stdout.startswith("qc PASS  rc=0  attempt 1/3"), r.stdout + r.stderr
        events = _events(b)
        qc = _scripts(events, "qc")
        assert [e["status"] for e in qc] == ["start", "done"], qc
        assert qc[0]["name"] == "qc_render.py" and qc[1]["video"] == slug and qc[1]["attempt"] == 1, qc
        # CF-0177: the plan on the line names the video, and the ledger has a
        # number by now, so the start carries both without any annotate().
        assert qc[0]["video"] == slug and qc[0]["attempt"] == 1, qc[0]
        assert qc[0]["parent"] is None
        probes = _children(events, parent=qc[0]["id"])
        tools = {c["tool"] for c in probes}
        assert tools == {"ffprobe", "ffmpeg"}, tools
        assert all(c["video"] == slug and c["attempt"] == 1 and c["step"] == "qc" for c in probes), probes
        assert all(c["status"] == "done" and c["rc"] == 0 for c in probes if c["status"] != "start"), probes

        # metadata: one video -> its slug and attempt; qc_render.py is a child
        # AND a nested script event chained through RUNLOG_PARENT
        r = _run("write_batch_metadata.py", b, "--video", "cf-1", plan, mp4, env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (b / "05-video-editor.json").exists()
        events = _events(b)
        meta = _scripts(events, "metadata")
        assert [e["status"] for e in meta] == ["start", "done"], meta
        assert meta[0]["name"] == "write_batch_metadata.py"
        assert meta[1]["video"] == slug and meta[1]["attempt"] == 1, meta[1]
        assert meta[0]["video"] == slug and meta[0]["attempt"] == 1, meta[0]   # CF-0177
        qc_child = _children(events, parent=meta[0]["id"], tool="qc_render.py")
        assert [c["status"] for c in qc_child] == ["start", "done"] and qc_child[1]["rc"] == 0, qc_child
        nested = [e for e in _scripts(events, "qc") if e["parent"] == meta[0]["id"]]
        assert [e["status"] for e in nested] == ["start", "done"], nested
        assert nested[1]["pid"] != meta[0]["pid"]
        order = [(e["kind"], e["step"], e["status"]) for e in events]
        assert order[0] == ("script", "render", "start") and order[-1] == ("script", "metadata", "done"), order


def test_render_at_the_cap_is_a_failed_script_with_exit_3_and_no_child():
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp, cap=1)
        env = _env(b, tac._stub_npx(tmp, tac.NOISY_NPX))
        r = tac._render(b, slug, plan, env)                # attempt 1: remotion fails
        assert r.returncode == 1, r.stdout + r.stderr
        events = _events(b)
        first = _scripts(events, "render")
        assert [e["status"] for e in first] == ["start", "failed"] and first[1]["error"] == "SystemExit: 1", first
        assert first[1]["attempt"] == 1
        # CF-0177: a failed attempt pairs like any other - that is exactly what
        # the att/video column has to count.
        assert first[0]["id"] == first[1]["id"] and first[0]["video"] == slug == first[1]["video"], first
        rem = _children(events, parent=first[0]["id"], tool="remotion")
        assert rem[1]["status"] == "failed" and rem[1]["rc"] == 1, rem

        r = tac._render(b, slug, plan, env)                # the cap: exit 3, nothing rendered
        assert r.returncode == attempts.EXIT_CAPPED == 3 and "NEEDS-YOU" in r.stdout, r.stdout + r.stderr
        events = _events(b)
        second = _scripts(events, "render")[2:]
        assert [e["status"] for e in second] == ["start", "failed"], second
        assert second[1]["error"] == "SystemExit: 3" and second[1]["video"] == slug, second[1]
        assert second[0]["video"] == slug and second[0]["attempt"] == 1, second[0]   # CF-0177
        assert second[1]["attempt"] == 1, second[1]          # the ledger's number: no new attempt was begun
        assert _children(events, parent=second[0]["id"]) == []


# --------------------------------------------------------------------------
# CF-0177: what the pair is for - the summary counts the attempts per video
# --------------------------------------------------------------------------

def test_two_attempts_of_one_video_are_two_attempts_in_the_summary():
    """The point of the whole task: the summary builds its per-video records
    from `start` events paired by id, and counts attempts per (video, step)
    off them. While the slug was annotated onto the done event alone, every
    per-video record was missing and `att/video` came out 0 with a batch of
    263 events on disk. Two failed renders of one video now read as two
    attempts of that video - a failed attempt is an attempt."""
    summary = runlog.sibling("summary")
    with tempfile.TemporaryDirectory() as tmp:
        b, slug, plan = tac._batch(tmp, cap=3)
        env = _env(b, tac._stub_npx(tmp, tac.NOISY_NPX))       # remotion fails
        for n in (1, 2):
            r = tac._render(b, slug, plan, env)
            assert r.returncode == 1, r.stdout + r.stderr
        events = _events(b)
        render = _scripts(events, "render")
        assert [e["status"] for e in render] == ["start", "failed", "start", "failed"], render
        # both attempts are complete pairs, and the slug and the number are on
        # the start line, which is the one the summary reads
        assert render[0]["id"] == render[1]["id"] and render[2]["id"] == render[3]["id"]
        assert [e["video"] for e in render] == [slug] * 4, render
        assert [e["attempt"] for e in render] == [1, 1, 2, 2], render

        T = summary.stage_times(summary.load(batch_dir=b))
        rows = [v for v in T["videos"] if v["stage"] == STAGE and v["video"] == slug]
        assert len(rows) == 1, T["videos"]
        row = rows[0]
        assert row["attempts_total"] == 2, row          # not 0, and not 1
        assert row["attempts"]["render"] == {"attempts": 2, "failed": 2}, row
        # and the stage row of the same table agrees
        stage = [w for w in T["stages"] if w["stage"] == STAGE]
        if stage:                                       # no stage marker in this fixture
            assert stage[0]["attempts"]["render"]["attempts"] == 2, stage[0]


def test_a_step_that_runs_many_times_inside_one_attempt_is_one_attempt():
    """The other half of the count: `qc-asset` runs once per candidate frame,
    `prepare-clip` once per clip. They belong to the attempt they are run
    for, so they carry its number and read as one attempt - counting their
    runs instead put the mean at 57 attempts per video on the 2026-09-09
    batch, against 7.3 and 9.5 in the rows written by hand."""
    summary = runlog.sibling("summary")
    b = TMP / "pipeline" / "chan" / "many-runs"
    (b / "work" / "vid").mkdir(parents=True, exist_ok=True)
    frame = b / "work" / "vid" / "f.png"
    frame.write_bytes(b"")
    for _ in range(5):
        with runlog.run(STAGE, "qc-asset", batch_dir=b, name="qc_asset.py",
                        **_runlog.argv_video_attempt([str(frame)])):
            pass
    T = summary.stage_times(summary.load(batch_dir=b))
    row = [v for v in T["videos"] if v["stage"] == STAGE and v["video"] == "vid"][0]
    assert row["attempts"]["qc-asset"] == {"attempts": 1, "failed": 0}, row
    assert row["attempts_total"] == 1, row


# --------------------------------------------------------------------------
# quiet.run_logged: the Remotion / ffmpeg child
# --------------------------------------------------------------------------

def test_run_logged_is_one_child_under_the_open_script_event():
    b = TMP / "pipeline" / "chan" / "run-logged"
    b.mkdir(parents=True, exist_ok=True)
    log = TMP / "run-logged.log"
    with runlog.run(STAGE, "render", video="vid", attempt=2, batch_dir=b, name="x.py") as fr:
        rc, lines, tail = quiet.run_logged(["sh", "-c", "echo one; echo two"], log,
                                           "stub", verbose=False, tool="remotion")
        assert (rc, lines, tail) == (0, 2, ["one", "two"])
        rc, _, _ = quiet.run_logged([FFMPEG, "-version"], log, "probe", verbose=False)
        assert rc == 0
        # no log + verbose: the plain subprocess.run path, whose timeout raises
        try:
            quiet.run_logged(["sh", "-c", "sleep 5"], None, "hang", verbose=True, timeout=0.3)
            raise AssertionError("run_logged did not time out")
        except subprocess.TimeoutExpired:
            pass
    events = _events(b)
    kids = _children(events, parent=fr["id"])
    assert [(c["tool"], c["status"]) for c in kids] == [
        ("remotion", "start"), ("remotion", "done"),
        ("ffmpeg", "start"), ("ffmpeg", "done"),
        ("sh", "start"), ("sh", "failed")], kids
    assert kids[1]["rc"] == 0 and kids[1]["argv"] == ["sh", "-c", "echo one; echo two"]
    assert kids[3]["rc"] == 0 and kids[3]["argv"][0] == FFMPEG
    assert kids[5]["rc"] == "timeout" and kids[5]["error"].startswith("TimeoutExpired"), kids[5]
    assert all(c["video"] == "vid" and c["attempt"] == 2 and c["step"] == "render" for c in kids), kids
    done = _scripts(events)[-1]
    assert done["status"] == "done" and done["attempt"] == 2 and done["id"] == fr["id"]


# --------------------------------------------------------------------------
# build_render_plan.py: gate-tool children, a failed child on TimeoutExpired
# --------------------------------------------------------------------------

def test_build_render_plan_leaves_gate_tool_children_and_a_failed_child_on_timeout():
    from PIL import Image
    b = TMP / "pipeline" / "chan" / "plan"
    work = b / "work" / "vid-plan"
    work.mkdir(parents=True, exist_ok=True)
    tat._silent_wav(work / "voice.wav")
    still = work / "still.png"
    Image.new("RGB", (1920, 1080), (120, 140, 160)).save(still)
    words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(6)]
    (work / "words.json").write_text(json.dumps(words))
    story = {"script_id": "cf-0107", "style": "motion",
             "blocks": [{"word_range": [0, 5], "intent": "a still",
                         "asset_kind": "still", "asset": str(still),
                         "emphasis_words": []}]}
    (work / "storyboard.json").write_text(json.dumps(story))
    out = work / "plan.json"
    # smart_crop.py hangs behind a passing qc_asset.py: the plan is refused (exit 2)
    with _batch_env(b), tat.hanging("smart_crop.py", qc_verdict=tat.USABLE_VERDICT), \
            _argv("build_render_plan.py", str(work / "storyboard.json"), str(work / "words.json"),
                  str(work / "voice.wav"), str(out), "--style", "motion",
                  "--target-duration", "1", "60"):
        code, _, err = _call_cli(brp.cli)
    assert code == 2 and "ASSETS REJECTED" in err and not out.exists(), (code, err)
    events = _events(b)
    plan = _scripts(events, "plan")
    assert [e["status"] for e in plan] == ["start", "failed"], plan
    assert plan[1]["error"] == "SystemExit: 2" and plan[1]["video"] == "vid-plan", plan[1]
    # CF-0177: no ledger under this fake batch - the plan is being built for
    # attempt 1, and both halves of the pair say so.
    assert plan[1]["attempt"] == 1 and plan[0]["name"] == "build_render_plan.py"
    assert plan[0]["video"] == "vid-plan" and plan[0]["attempt"] == 1, plan[0]
    kids = _children(events, parent=plan[0]["id"])
    assert [(c["tool"], c["status"]) for c in kids] == [
        ("qc_asset.py", "start"), ("qc_asset.py", "done"),
        ("smart_crop.py", "start"), ("smart_crop.py", "failed")], kids
    assert kids[1]["rc"] == 0 and kids[1]["argv"][1].endswith("qc_asset.py")
    assert kids[3]["rc"] == "timeout" and kids[3]["error"].startswith("TimeoutExpired"), kids[3]
    assert all(c["video"] == "vid-plan" and c["step"] == "plan" for c in kids)


# --------------------------------------------------------------------------
# Vision call sites
# --------------------------------------------------------------------------

def test_vision_call_sites_leave_vision_children_naming_the_probe():
    b = TMP / "pipeline" / "chan" / "vision"
    b.mkdir(parents=True, exist_ok=True)
    real = (smart_crop._find_roi, detect_text_band._text_regions, vision_client._request_raw)
    smart_crop._find_roi = lambda p: ((0, 0, 10, 10), (100, 100), "faces", True)
    detect_text_band._text_regions = lambda p, level=1: [{"top": 0.1, "bottom": 0.2, "text": "hi"}]
    vision_client._request_raw = lambda op, **payload: []
    try:
        with runlog.run(STAGE, "qc-asset", video="vid", batch_dir=b, name="qc_asset.py") as fr:
            assert smart_crop.find_roi("frame.png")[2] == "faces"
            assert detect_text_band.text_regions("frame.png", level=0)[0]["text"] == "hi"
            assert vision_client._request("text_regions", image="frame.png", level=0) == []
    finally:
        smart_crop._find_roi, detect_text_band._text_regions, vision_client._request_raw = real
    kids = _children(_events(b), parent=fr["id"], tool="vision")
    assert [c["status"] for c in kids] == ["start", "done"] * 3, kids
    probes = [(c["argv"][1], c["params"]["probe"], c["params"].get("via")) for c in kids[1::2]]
    assert probes == [("find_roi", "find_roi", None), ("text_regions", "text_regions", None),
                      ("text_regions", "text_regions", "worker")], probes
    assert kids[3]["params"]["level"] == 0 and kids[1]["argv"][2] == "frame.png"
    assert all(c["video"] == "vid" and c["step"] == "qc-asset" and c["stage"] == STAGE for c in kids)


def test_the_vision_worker_is_spawned_without_the_batch_and_never_accounts():
    src = (SCRIPTS / "vision_client.py").read_text()
    assert '"RUNLOG_BATCH", "RUNLOG_PARENT"' in src and "env=env" in src
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import vision_worker, _runlog, smart_crop; "
            "print(type(_runlog.runlog).__name__, type(smart_crop.runlog).__name__)")
    cp = subprocess.run([PY, "-c", code, str(SCRIPTS)], capture_output=True, text=True,
                        env=_env(TMP / "pipeline" / "chan" / "worker"), timeout=60)
    assert cp.returncode == 0 and cp.stdout.split() == ["_Silent", "_Silent"], (cp.stdout, cp.stderr)


# --------------------------------------------------------------------------
# no batch: nothing written, same output
# --------------------------------------------------------------------------

def test_no_batch_dir_writes_nothing_and_leaves_the_output_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        synth = tac._synthetic_video(tmp)
        plan = tmp / "plan.json"
        plan.write_text(json.dumps({"blocks": [], "audio": {"src": str(synth), "duration": 2.0},
                                    "output": {"width": 1080, "height": 1920}, "style": "motion",
                                    "duration": {}}))
        # The runner (tests/run_tests.py, CF-0107) exports RUNLOG_BATCH for
        # the whole suite so no test records into a real batch; this test
        # is about the no-batch path, so the child env must drop it
        # explicitly rather than inherit whatever the runner set.
        no_batch = _env(None)
        assert "RUNLOG_BATCH" not in no_batch and "RUNLOG_PARENT" not in no_batch
        bare = _run("qc_render.py", synth, plan, env=no_batch)
        assert bare.returncode == 0, bare.stdout + bare.stderr
        assert not list(tmp.rglob("RUN_EVENTS.jsonl")) and not list(tmp.rglob("RUN_LOG.txt"))
        noise = [l for l in bare.stderr.splitlines() if l.strip() and not l.startswith("[runlog]")]
        assert noise == [], bare.stderr

        b = tmp / "pipeline" / "chan" / "b-nobatch"
        b.mkdir(parents=True)
        under = _run("qc_render.py", synth, plan, env=_env(b))
        assert under.returncode == 0 and under.stdout == bare.stdout, (bare.stdout, under.stdout)
        assert "[runlog]" not in under.stderr and _scripts(_events(b), "qc"), under.stderr


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
