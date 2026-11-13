#!/usr/bin/env python3
"""CF-0107, Footage Indexer part: every script of the stage writes `start` and
`done`/`failed` events to the batch's RUN_EVENTS.jsonl through the root's
shared/runlog library; every external binary and the in-process CLIP / Vision
work inside them is a `child` event (tool yt-dlp, ffmpeg, ffprobe, clip,
vision) with the script's event as parent and the source id as `video`; and
with no batch to write to nothing is written and the output is the same.

Everything runs offline, in seconds: the fetch against the fake yt-dlp from
test_partial_cache_cleanup.py in a temp cache, the fingerprint and the index
on a 3-second lavfi clip with CLIP and Vision stubbed at the seams the
scripts already expose (clip_model(), probe_usability, probe_captions,
sample_text_regions), ingest() with injected fetch/index/fingerprint.
"""
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

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("fi-runlog-")   # CF-0489: removed at exit
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # never touch ~/.shorts-content-factory
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import _runlog  # noqa: E402
import _fi_paths  # noqa: E402 - CF-0267
from _runlog import runlog  # noqa: E402
import fetch_footage as ff  # noqa: E402
import source_fingerprint as sf  # noqa: E402
import index_footage as idx  # noqa: E402
import ingest_batch as ib  # noqa: E402


def no_measure(vid, record=None):
    """CF-0302: the duration ceiling's measurement seam, injected away.

    `ingest()` reads how long a candidate is before it downloads it, and the
    real reader asks YouTube. Nothing in this file is about that ceiling, so
    the answer here is "nobody could tell" - which is never a refusal - and no
    request is made.
    """
    return ib.Measured(None, "metadata", "not measured in this test")

import caption_cache  # noqa: E402
# The fake yt-dlp and the temp-cache plumbing, shared with the CF-0090 tests
# (importing the module only writes the fake script; its tests run under
# __main__).
import test_partial_cache_cleanup as pcc  # noqa: E402

PY = str(_fi_paths.venv_bin("python3")) if _fi_paths.venv_bin("python3").exists() else sys.executable  # CF-0267
FFMPEG = idx.FFMPEG
STAGE = "footage-indexer"


def _events(batch):
    path = batch / "RUN_EVENTS.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fresh_batch(name):
    b = TMP / name
    b.mkdir(parents=True, exist_ok=True)
    return b


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


def _scripts(events):
    return [e for e in events if e["kind"] == "script"]


def _children(events):
    return [e for e in events if e["kind"] == "child"]


def _check_nesting(children, script_id):
    """CF-0160: every child event carries an integer `depth`; depth 0 hangs
    off the script, depth n >= 1 off another child of this run at depth n-1;
    start and done of one id agree on parent and depth. Returns the
    (wrapper, nested) pairs, from the done events."""
    by_id = {}
    for c in children:
        assert isinstance(c.get("depth"), int) and not isinstance(c["depth"], bool) and c["depth"] >= 0, c
        by_id.setdefault(c["id"], []).append(c)
    for evs in by_id.values():
        assert len({(e["parent"], e["depth"]) for e in evs}) == 1, evs
    pairs = []
    for c in children:
        if c["depth"] == 0:
            assert c["parent"] == script_id, c
            continue
        assert c["parent"] in by_id, c                   # another child of this run, not the script
        wrapper = by_id[c["parent"]][0]
        assert wrapper["depth"] == c["depth"] - 1, (wrapper, c)
        if c["status"] == "done":
            pairs.append((wrapper, c))
    return pairs


_CLIP = None


def lavfi_clip():
    """A 3-second 320x180 test clip, made once."""
    global _CLIP
    if _CLIP is None:
        _CLIP = TMP / "clip" / "lavfi01.mp4"
        _CLIP.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "testsrc=duration=3:size=320x180:rate=10",
                        "-pix_fmt", "yuv420p", str(_CLIP)], check=True, timeout=60)
    return _CLIP


# --------------------------------------------------------------------------
# the shim
# --------------------------------------------------------------------------

def test_shim_resolves_the_root_from_inside_this_checkout():
    """The ancestor walk finds shared/runlog/runlog.py whether this repo is the
    normal agents/footage-indexer checkout or a worktree under .claude/worktrees/."""
    root = _runlog.factory_root()
    assert (root / "shared" / "runlog" / "runlog.py").is_file(), root
    assert (root / "README.md").is_file() and (root / "agents").is_dir(), f"{root} is not the factory root"
    # CF-0267: a checkout outside the tree reaches the root through
    # FACTORY_ROOT only, and is then by definition not under it.
    if not os.environ.get("FACTORY_ROOT"):
        assert REPO.resolve().is_relative_to(root), (REPO, root)
    assert Path(runlog.__file__).resolve() == (root / "shared" / "runlog" / "runlog.py").resolve()
    assert hasattr(runlog, "script") and hasattr(runlog, "child") and hasattr(runlog, "run_child")


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


# --------------------------------------------------------------------------
# fetch_footage.py: script event + yt-dlp children
# --------------------------------------------------------------------------

def _run_fetch(batch, mode="ok", url=pcc.URL):
    pcc.fresh_cache("runlog-" + (batch.name if batch else "nobatch"))
    os.environ["FAKE_YTDLP_MODE"] = mode
    # CF-0598/CF-0597: the strike registry of an empty temp root, never the live one.
    with _batch_env(batch), _argv("fetch_footage.py", url, "--ytdlp", str(pcc.FAKE),
                                  "--rights-root", str(TMP)):
        return _call_cli(ff.cli)


def test_fetch_writes_script_events_and_a_ytdlp_child_per_call():
    batch = _fresh_batch("fetch")
    code, out, err = _run_fetch(batch)
    assert code == 0 and "fetched -> " in out, (code, out, err)
    assert "[runlog]" not in err, err

    events = _events(batch)
    scripts, children = _scripts(events), _children(events)
    assert [e["status"] for e in scripts] == ["start", "done"], scripts
    start, done = scripts
    assert start["id"] == done["id"] and start["pid"] == done["pid"] == os.getpid()
    for e in scripts:
        assert e["stage"] == STAGE and e["step"] == "fetch" and e["name"] == "fetch_footage.py", e
        assert e["ts"].endswith("Z")
    assert done["video"] == pcc.VID, done          # annotated once yt-dlp named the id
    assert start["params"]["--ytdlp"] == str(pcc.FAKE), start["params"]
    assert start["duration_s"] is None and isinstance(done["duration_s"], (int, float))

    # the download and the metadata dump: two yt-dlp children, both under the script
    assert [(c["tool"], c["status"]) for c in children] == \
        [("yt-dlp", "start"), ("yt-dlp", "done"), ("yt-dlp", "start"), ("yt-dlp", "done")], children
    for c in children:
        assert c["parent"] == start["id"] and c["stage"] == STAGE and c["step"] == "fetch", c
        assert c["argv"][0] == str(pcc.FAKE) and pcc.URL in c["argv"], c["argv"]
    assert children[1]["rc"] == 0 and children[3]["rc"] == 0
    assert "--dump-single-json" in children[2]["argv"]
    # The id is what the download discovers, so the download child itself cannot
    # carry it; the annotation lands on the script event and on every child
    # started after it - here the metadata dump.
    assert children[1]["video"] is None and children[3]["video"] == pcc.VID, children
    order = [(e["kind"], e["status"]) for e in events]
    assert order[0] == ("script", "start") and order[-1] == ("script", "done"), order


def test_failed_download_is_a_failed_child_and_a_failed_script():
    batch = _fresh_batch("fetch-fail")
    code, out, err = _run_fetch(batch, mode="fail")
    assert code == 1 and f"CLEANUP {pcc.VID}" in err, (code, err)
    events = _events(batch)
    scripts, children = _scripts(events), _children(events)
    assert [e["status"] for e in scripts] == ["start", "failed"], scripts
    assert scripts[1]["error"].startswith("SystemExit:"), scripts[1]
    assert [c["status"] for c in children] == ["start", "failed"] and children[1]["rc"] == 1, children
    assert children[1]["parent"] == scripts[0]["id"]


def test_cache_hit_is_a_script_event_without_a_download_child():
    batch = _fresh_batch("fetch-cached")
    code, out, _ = _run_fetch(batch)                     # first: real (fake) download
    assert code == 0 and "fetched -> " in out
    os.environ["FAKE_YTDLP_MODE"] = "fail"               # must not be called now
    with _batch_env(batch), _argv("fetch_footage.py", pcc.URL, "--ytdlp", str(pcc.FAKE),
                                  "--rights-root", str(TMP)):
        code, out, err = _call_cli(ff.cli)
    assert code == 0 and "cached -> " in out, (code, out, err)
    events = _events(batch)
    second = _scripts(events)[2:]
    assert [e["status"] for e in second] == ["start", "done"] and second[1]["video"] == pcc.VID, second
    assert second[1]["params"].get("cached") is True, second[1]
    assert not [c for c in _children(events) if c["parent"] == second[0]["id"]]


# --------------------------------------------------------------------------
# source_fingerprint.py / index_footage.py: ffmpeg, ffprobe, clip, vision children
# --------------------------------------------------------------------------

def test_fingerprint_leaves_an_ffmpeg_child_under_a_per_source_event():
    batch = _fresh_batch("fingerprint")
    clip = lavfi_clip()
    with _batch_env(batch), _argv("source_fingerprint.py", str(clip)):
        code, out, err = _call_cli(sf.cli)
    assert code == 0 and '"kind"' in out, (code, out, err)
    events = _events(batch)
    scripts, children = _scripts(events), _children(events)
    # the script event and, nested in it, one event for the one source
    assert [(e["status"], e["video"]) for e in scripts] == \
        [("start", None), ("start", "lavfi01"), ("done", "lavfi01"), ("done", None)], scripts
    outer, inner = scripts[0], scripts[1]
    assert inner["parent"] == outer["id"] and outer["step"] == inner["step"] == "fingerprint"
    assert [c["tool"] for c in children] == ["ffmpeg", "ffmpeg"] and children[1]["rc"] == 0, children
    assert children[0]["parent"] == inner["id"] and children[0]["video"] == "lavfi01", children[0]
    assert children[0]["argv"][0] == sf.FFMPEG and str(clip) in children[0]["argv"]


def test_a_subprocessed_script_chains_to_the_parent_through_the_environment():
    """RUNLOG_BATCH/RUNLOG_PARENT exported by an instrumented parent (ingest_batch.py
    does this through runlog.run) make the subprocessed script's event a child of it."""
    batch = _fresh_batch("chain")
    clip = lavfi_clip()
    env = dict(os.environ, RUNLOG_BATCH=str(batch), RUNLOG_PARENT="feedfacecafe")
    cp = subprocess.run([PY, str(SCRIPTS / "source_fingerprint.py"), str(clip)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr
    scripts = _scripts(_events(batch))
    assert scripts[0]["parent"] == "feedfacecafe" and scripts[0]["name"] == "source_fingerprint.py", scripts[0]
    assert scripts[1]["parent"] == scripts[0]["id"] and scripts[0]["pid"] != os.getpid()


class _FakeClip:
    """Stands in for (model, processor, tokenizer): the real embed()/flag_cards()
    code runs, only the network weights are replaced by unit vectors."""

    def __call__(self, images=None, return_tensors=None, **kw):
        return {"n": len(images)}

    def get_image_features(self, n=0, **kw):
        import torch
        return torch.ones(n, 4)

    def get_text_features(self, n=0, **kw):
        import torch
        return torch.ones(n, 4)


@contextlib.contextmanager
def _stubbed_clip_and_vision():
    fake = _FakeClip()
    saved = (idx.clip_model.__dict__.get("_cached"), idx.probe_usability,
             caption_cache.caption_probe.probe_captions,
             idx.detect_text_band.sample_text_regions, idx.card_frame.classify_frame)

    def tok(phrases, padding=True, return_tensors=None):
        return {"n": len(phrases)}

    idx.clip_model._cached = (fake, fake, tok)
    idx.probe_usability = lambda frame: {"short_side": 180, "width": 320, "height": 180,
                                         "roi_source": "none", "roi_coverage": 0.0,
                                         "black_fraction": 0.0, "mean_luma": 120.0}
    caption_cache.caption_probe.probe_captions = lambda v, s, e: 0.0
    idx.detect_text_band.sample_text_regions = lambda frame, level=0: []
    idx.card_frame.classify_frame = lambda frame, regions: {"verdict": None}
    try:
        yield
    finally:
        if saved[0] is None:
            idx.clip_model.__dict__.pop("_cached", None)
        else:
            idx.clip_model._cached = saved[0]
        idx.probe_usability = saved[1]
        caption_cache.caption_probe.probe_captions = saved[2]
        idx.detect_text_band.sample_text_regions = saved[3]
        idx.card_frame.classify_frame = saved[4]


def _run_index(batch, clip):
    with _batch_env(batch), _stubbed_clip_and_vision(), \
            _argv("index_footage.py", str(clip), "--no-split", "--threshold", "0.3"):
        return _call_cli(idx.cli)


def test_index_leaves_ffmpeg_ffprobe_clip_and_vision_children_with_the_video_set():
    batch = _fresh_batch("index")
    clip = lavfi_clip()
    code, out, err = _run_index(batch, clip)
    assert code == 0 and "shots -> " in out and clip.with_suffix(".shots.json").exists(), (code, out, err)
    assert "[runlog]" not in err, err

    events = _events(batch)
    scripts, children = _scripts(events), _children(events)
    assert [e["status"] for e in scripts] == ["start", "done"], scripts
    start, done = scripts
    assert start["step"] == "index" and start["name"] == "index_footage.py" and done["video"] == "lavfi01", done

    by_tool = {}
    for c in children:
        assert c["video"] == "lavfi01", c               # annotated before any child runs
        assert c["status"] in ("start", "done"), c
        by_tool.setdefault(c["tool"], []).append(c)
    assert set(by_tool) == {"ffmpeg", "ffprobe", "clip", "vision"}, sorted(by_tool)
    # Every child id opens once and closes once, start before done. Not
    # strict start/done alternation: a call-site child (e.g. "full-frames",
    # "cropdetect") wraps the real ffmpeg runs it makes, so children nest.
    for tool, evs in by_tool.items():
        by_id = {}
        for e in evs:
            by_id.setdefault(e["id"], []).append(e["status"])
        assert all(v == ["start", "done"] for v in by_id.values()), (tool, by_id)

    # CF-0160: nesting is recorded, not guessed. A top-level child (depth 0)
    # hangs off the script; a real ffmpeg run inside a call-site wrapper
    # ("full-frames", "cropdetect") hangs off that wrapper, one level down.
    wrapped = _check_nesting(children, start["id"])
    assert any(w["argv"][1] in ("full-frames", "cropdetect") for w, _ in wrapped), \
        [w["argv"][:2] for w, _ in wrapped]
    assert all(w["tool"] == "ffmpeg" and c["tool"] == "ffmpeg" for w, c in wrapped), wrapped
    # Negative control, kept in the test: the pre-CF-0160 journal, where the
    # nested ffmpeg named the script as its parent, must fail the same check.
    old = [dict(c, parent=start["id"]) if c.get("depth", 0) >= 1 else c for c in children]
    try:
        _check_nesting(old, start["id"])
    except AssertionError:
        pass
    else:
        raise AssertionError("nested ffmpeg pointing at the script passed the nesting check")
    # The summary counts leaves only: wrappers are not ffmpeg calls of their own.
    import summary  # shared/runlog, on sys.path once runlog is loaded
    wrapper_ids = {c["parent"] for c in children if c["depth"] >= 1}
    leaf_ffmpeg = {c["id"] for c in by_tool["ffmpeg"] if c["id"] not in wrapper_ids}
    bt = summary.binary_times(events)
    assert bt["tools"]["ffmpeg"]["calls"] == len(leaf_ffmpeg), (bt["tools"]["ffmpeg"], len(leaf_ffmpeg))

    # ffmpeg: shot detection, one frame per shot, the contact sheet, the
    # full-frame pass, the card-text samples, the fingerprint decode.
    ffmpeg_args = [" ".join(e["argv"]) for e in by_tool["ffmpeg"] if e["status"] == "done"]
    assert any("scene," in a for a in ffmpeg_args), ffmpeg_args           # shot_boundaries
    assert any("scale=336:-2" in a for a in ffmpeg_args), ffmpeg_args     # extract_frames
    assert any("tile=" in a for a in ffmpeg_args), ffmpeg_args            # contact_sheet
    assert any("full-frames" in a for a in ffmpeg_args), ffmpeg_args      # extract_full_frames, at the call site
    assert any("rawvideo" in a for a in ffmpeg_args), ffmpeg_args         # source_fingerprint._grab
    samples = [e for e in by_tool["ffmpeg"] if e["status"] == "done" and (e["params"] or {}).get("samples")]
    assert samples and samples[0]["params"]["samples"] >= 8, samples
    # CF-0452: the per-shot sharpness pass is an ffmpeg child under a step of
    # its own, "sharpness", so its cost shows apart from the rest of index;
    # every other ffmpeg/ffprobe child is step index.
    sharp = [e for e in by_tool["ffmpeg"] if e["argv"][:2] == ["ffmpeg", "sharpness"]]
    assert sharp and all(e["step"] == "sharpness" for e in sharp), sharp
    rest = [e for e in by_tool["ffmpeg"] + by_tool["ffprobe"] if e not in sharp]
    assert all(e["step"] == "index" for e in rest), [e for e in rest if e["step"] != "index"]

    # clip: the embedding pass and the card-phrase text pass, step embed
    clip_kinds = [e["argv"][1] for e in by_tool["clip"] if e["status"] == "done"]
    assert clip_kinds == ["embed", "text"], clip_kinds
    assert all(e["step"] == "embed" for e in by_tool["clip"]), by_tool["clip"]

    # vision: usability, captions and card-text per shot, step probe
    vision_kinds = sorted({e["argv"][1] for e in by_tool["vision"]})
    assert vision_kinds == ["captions", "card-text", "usability"], vision_kinds
    assert all(e["step"] == "probe" for e in by_tool["vision"]), by_tool["vision"]
    n_shots = int(out.split(" shots -> ")[0].strip().split()[-1])
    assert len([e for e in by_tool["vision"] if e["status"] == "done"]) == 3 * n_shots, n_shots

    # every child sits between the script's start and done
    assert events[0] is start and events[-1] is done or (events[0]["id"] == start["id"] and events[-1]["id"] == done["id"])


def test_index_output_is_the_same_without_a_batch_and_nothing_is_written():
    clip = lavfi_clip()
    with_batch = _fresh_batch("index-ref")
    code, ref_out, _ = _run_index(with_batch, clip)
    assert code == 0
    ref = json.load(open(clip.with_suffix(".shots.json")))

    nowhere = TMP / "nowhere" / "deeper"
    nowhere.mkdir(parents=True, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(nowhere)
    try:
        code, out, err = _run_index(None, clip)
    finally:
        os.chdir(cwd)
    assert code == 0 and out == ref_out, (out, ref_out)
    assert "no batch dir" in err, err                    # says so, does not raise
    now = json.load(open(clip.with_suffix(".shots.json")))
    assert now["shots"] == ref["shots"] and now["fingerprint"] == ref["fingerprint"]
    stray = list((TMP / "nowhere").rglob("RUN_EVENTS.jsonl")) + list(clip.parent.rglob("RUN_EVENTS.jsonl")) \
        + list(REPO.glob("RUN_EVENTS.jsonl")) + list(SCRIPTS.glob("RUN_EVENTS.jsonl"))
    assert not stray, stray
    assert "RUNLOG_BATCH" not in os.environ and "RUNLOG_PARENT" not in os.environ


def test_fetch_output_is_the_same_without_a_batch():
    batch = _fresh_batch("fetch-ref")
    code, ref_out, _ = _run_fetch(batch)
    code2, out, err = _run_fetch(None)
    assert code == code2 == 0
    # the cache path differs by test name only
    norm = lambda s: s.replace("runlog-fetch-ref", "X").replace("runlog-nobatch", "X")
    assert norm(out) == norm(ref_out), (out, ref_out)
    assert "no batch dir" in err and "CLEANUP" not in err, err


# --------------------------------------------------------------------------
# ingest_batch.py: one nested event per source
# --------------------------------------------------------------------------

def test_ingest_nests_one_event_per_source_with_the_video_id():
    batch = _fresh_batch("ingest")
    topics = [{"topic_id": "001", "evidence": {"youtube_video_ids": ["aaa", "bbb", "ccc"]}}]
    fps = {"aaa": {"kind": "k", "hashes": ["0"] * 8, "luma": [0] * 8, "fps": 2},
           "bbb": None}
    calls = []

    def fetch(vid, note):
        calls.append(("fetch", vid))
        if vid == "ccc":
            raise RuntimeError("yt-dlp failed for ccc")
        return f"/tmp/{vid}.mp4"

    def index(path):
        calls.append(("index", path))
        assert runlog.current_id() is not None            # runs inside the per-source event

    def fingerprint(path):
        return fps[Path(path).stem]

    with _batch_env(batch), runlog.run(STAGE, "ingest", name="ingest_batch.py") as outer, \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        fetched, aliases, skipped, failed, by_topic = ib.ingest(
            topics, {}, "b", 3, False, fetch=fetch, index=index, fingerprint=fingerprint,
            sleep=lambda s: None, pause=0,   # CF-0253 pacing, injected away
            measure=no_measure,                          # CF-0302 probe, injected away
            # CF-0129: this test wants one event per id of the topic, so the
            # floor is set above what the topic can reach - the walk stopping
            # at two canonical sources is pinned in test_two_sources_per_topic.py.
            wanted=99)
    assert [f["video_id"] for f in fetched] == ["aaa", "bbb"]
    assert [(f["video_id"], f["error"]) for f in failed] == [("ccc", "yt-dlp failed for ccc")]

    scripts = _scripts(_events(batch))
    inner = [e for e in scripts if e["parent"] == outer["id"]]
    assert [(e["video"], e["status"]) for e in inner] == \
        [("aaa", "start"), ("aaa", "done"), ("bbb", "start"), ("bbb", "done"),
         ("ccc", "start"), ("ccc", "done")], inner
    for e in inner:
        assert e["stage"] == STAGE and e["step"] == "ingest" and e["name"] == "ingest_batch.py", e
    assert inner[-1]["params"]["fetch_failed"] == "yt-dlp failed for ccc", inner[-1]
    assert scripts[0]["id"] == outer["id"] and scripts[-1]["status"] == "done"
    # the outer event's env exports are what a subprocessed fetch_footage.py chains on
    assert "RUNLOG_PARENT" not in os.environ


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # a crash is a failure, not a skip
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
