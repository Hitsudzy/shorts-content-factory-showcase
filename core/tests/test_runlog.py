#!/usr/bin/env python3
"""CF-0107: the run's event file, RUN_EVENTS.jsonl, and what is derived from it.

Every script of every agent writes start/done|failed through shared/runlog/
runlog.py, every external binary is a child event under its script, the
operator's stage boundaries are markers from the `runlog` command, and
RUN_LOG.txt is rendered from the events rather than typed. Cross-agent by
construction - five repos import one module - so the contract is pinned here:
time is always UTC with Z, attempts are the caller's numbers, a failed script
still leaves its event, a child names its parent, a marker out of order is a
clear exit 2, and accounting never raises into the run it accounts for.

Runs in seconds: the only external calls are the header probes (sysctl, git,
system_profiler once - cached under RUNLOG_STATE_DIR) and `true`/`sh -c`.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("runlog-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")       # never touch ~/.shorts-content-factory
FAKE_ROOT = TMP / "root"                                   # CF-0111: batch-done appends to the runs
(FAKE_ROOT / "pipeline").mkdir(parents=True)               # table of FACTORY_ROOT - never the repo's
os.environ["FACTORY_ROOT"] = str(FAKE_ROOT)
os.environ["RUNLOG_TRANSCRIPTS"] = str(TMP / "no-transcripts")   # CF-0172: batch-done scans the
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "no-transcripts")  # transcripts - never ~/.claude here
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from shared.runlog import runlog as via_package  # noqa: E402
import runlog  # noqa: E402

CLI = [sys.executable, str(ROOT / "scripts" / "runlog")]
_n = [0]


def batch():
    """A fresh pipeline/<channel>/<batch-id> directory."""
    _n[0] += 1
    b = TMP / f"p{_n[0]}" / "pipeline" / "fashion" / f"2026-09-07-{_n[0]}"
    b.mkdir(parents=True)
    return b


def events(b):
    return runlog.read_events(b)


def cli(*args, env=None):
    e = dict(os.environ)
    e.pop("RUNLOG_BATCH", None)
    if env:
        e.update(env)
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=e, timeout=60)


# --------------------------------------------------------------------------

def test_both_import_paths_are_the_same_module():
    assert via_package is runlog or via_package.__file__ == runlog.__file__


def test_run_writes_start_and_done_with_duration_and_shared_id():
    b = batch()
    with runlog.run("trend-hunter", "fetch", params={"feeds": 7}, batch_dir=b):
        pass
    ev = events(b)
    assert [e["status"] for e in ev] == ["start", "done"], ev
    assert ev[0]["id"] == ev[1]["id"]
    assert ev[0]["kind"] == ev[1]["kind"] == "script"
    assert ev[0]["stage"] == "trend-hunter" and ev[0]["step"] == "fetch"
    assert ev[0]["params"] == {"feeds": 7}
    assert ev[0]["duration_s"] is None and ev[1]["duration_s"] >= 0
    assert ev[1]["pid"] == os.getpid()
    for e in ev:
        for key in ("ts", "machine", "kind", "stage", "video", "step", "attempt",
                    "status", "params", "duration_s", "pid", "id", "parent"):
            assert key in e, (key, e)


def test_run_writes_failed_with_exception_and_propagates():
    b = batch()
    try:
        with runlog.run("video-editor", "render", batch_dir=b):
            raise ValueError("boom\nsecond line ignored")
    except ValueError:
        pass
    else:
        raise AssertionError("exception swallowed")
    ev = events(b)
    assert ev[-1]["status"] == "failed"
    assert ev[-1]["error"] == "ValueError: boom"
    assert ev[-1]["duration_s"] is not None


def test_system_exit_nonzero_is_failed_zero_is_done():
    b = batch()
    for code, expect in ((3, "failed"), (0, "done"), (None, "done")):
        try:
            with runlog.run("video-editor", "qc", batch_dir=b):
                sys.exit(code)
        except SystemExit:
            pass
        assert events(b)[-1]["status"] == expect, (code, events(b)[-1])


def test_attempt_is_the_callers_number_not_invented():
    b = batch()
    for n in (1, 2, 7):
        with runlog.run("video-editor", "resolve", video="lisa", attempt=n, batch_dir=b):
            pass
    seen = [e["attempt"] for e in events(b)]
    assert seen == [1, 1, 2, 2, 7, 7], seen
    with runlog.run("video-editor", "resolve", video="lisa", batch_dir=b):
        pass
    assert events(b)[-1]["attempt"] is None


def test_annotate_lands_on_the_done_event():
    b = batch()
    with runlog.run("video-editor", "plan", batch_dir=b):
        runlog.annotate(video="kirby", attempt=2, shots=12)
    ev = events(b)
    assert ev[0]["video"] is None
    assert ev[1]["video"] == "kirby" and ev[1]["attempt"] == 2
    assert ev[1]["params"] == {"shots": 12}


def test_every_ts_ends_with_z_and_is_utc():
    b = batch()
    with runlog.run("content-researcher", batch_dir=b):
        runlog.run_child(["true"], tool="ffmpeg")
    runlog.marker("batch-start", batch_dir=b, strict=False)
    for e in events(b):
        assert e["ts"].endswith("Z"), e["ts"]
        assert "+" not in e["ts"]
        # round-trips through the module's own parser
        runlog.parse_z(e["ts"])
    z = runlog.now_z(0)
    assert z == "1970-01-01T00:00:00.000Z", z


def test_child_references_its_parent_and_records_rc():
    b = batch()
    with runlog.run("footage-indexer", "fetch", video="lisa", batch_dir=b) as fr:
        cp = runlog.run_child(["sh", "-c", "exit 3"], tool="yt-dlp")
        assert cp.returncode == 3
        runlog.run_child(["true"])                       # tool defaults to the binary name
        with runlog.child("vision", argv=["in-process"]) as c:
            c["rc"] = 0
    ev = events(b)
    kids = [e for e in ev if e["kind"] == "child"]
    assert len(kids) == 6, kids
    assert {k["parent"] for k in kids} == {fr["id"]}
    assert all(k["video"] == "lisa" and k["stage"] == "footage-indexer" for k in kids)
    ytdlp = [k for k in kids if k["tool"] == "yt-dlp" and k["status"] != "start"][0]
    assert ytdlp["status"] == "failed" and ytdlp["rc"] == 3
    assert ytdlp["argv"] == ["sh", "-c", "exit 3"]
    true_ = [k for k in kids if k["tool"] == "true" and k["status"] != "start"][0]
    assert true_["status"] == "done" and true_["rc"] == 0
    vis = [k for k in kids if k["tool"] == "vision" and k["status"] != "start"][0]
    assert vis["status"] == "done"
    # the child's start/done share an id distinct from the parent's
    assert kids[0]["id"] == kids[1]["id"] != fr["id"]


def test_nested_child_is_parented_to_the_enclosing_call():
    """CF-0160: `ffmpeg full-frames` -> `ffmpeg cropdetect` -> the real ffmpeg.
    The real call points at cropdetect, cropdetect at full-frames, full-frames at
    the script; RUNLOG_PARENT stays the script's id; an explicit parent= wins;
    a run() opened inside a call is nearer than the call; threads do not nest
    into each other's calls."""
    import threading
    b = batch()
    with runlog.run("footage-indexer", "index", video="lisa", batch_dir=b) as fr:
        with runlog.child("ffmpeg", argv=["full-frames"]) as outer:
            with runlog.child("ffmpeg", argv=["cropdetect"]) as mid:
                assert os.environ.get("RUNLOG_PARENT") == fr["id"]
                runlog.run_child(["true"], tool="ffmpeg")
                with runlog.child("vision", parent="EXPLICIT") as ex:
                    ex["rc"] = 0
                with runlog.run("footage-indexer", "inner", batch_dir=b) as inner:
                    with runlog.child("kokoro") as k:
                        k["rc"] = 0
            seen = {}

            def other():
                with runlog.child("yt-dlp") as t:
                    t["rc"] = 0
                    seen["t"] = t
            th = threading.Thread(target=other)
            th.start()
            th.join()
        with runlog.child("ffmpeg", argv=["after"]) as after:
            after["rc"] = 0
    kids = [e for e in events(b) if e["kind"] == "child"]
    starts = {e["id"]: e for e in kids if e["status"] == "start"}
    ends = {e["id"]: e for e in kids if e["status"] != "start"}
    assert set(starts) == set(ends)
    real = [e for e in starts.values() if e.get("argv") == ["true"]][0]
    assert starts[outer["id"]]["parent"] == fr["id"] and starts[outer["id"]]["depth"] == 0
    assert starts[mid["id"]]["parent"] == outer["id"] and starts[mid["id"]]["depth"] == 1
    assert real["parent"] == mid["id"] and real["depth"] == 2
    assert ends[real["id"]]["parent"] == mid["id"] and ends[real["id"]]["depth"] == 2
    assert starts[ex["id"]]["parent"] == "EXPLICIT"
    assert starts[k["id"]]["parent"] == inner["id"] and starts[k["id"]]["depth"] == 0
    # the thread has no open call of its own: it chains to the env (the script)
    assert starts[seen["t"]["id"]]["parent"] == fr["id"] and starts[seen["t"]["id"]]["depth"] == 0
    assert starts[after["id"]]["parent"] == fr["id"] and starts[after["id"]]["depth"] == 0
    # annotate() still lands on the script, not on a call
    assert runlog._child_stack() == []


def test_run_child_check_true_raises_after_writing_failed():
    b = batch()
    with runlog.run("video-editor", "tts", batch_dir=b):
        try:
            runlog.run_child(["sh", "-c", "exit 2"], tool="kokoro", check=True)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("check=True did not raise")
    k = [e for e in events(b) if e["kind"] == "child"][-1]
    assert k["status"] == "failed" and k["rc"] == 2 and k["tool"] == "kokoro"


def test_nested_run_and_subprocess_chain_through_env():
    """A script started from an instrumented script (subprocess) inherits the
    batch and the parent through RUNLOG_BATCH / RUNLOG_PARENT."""
    b = batch()
    inner = TMP / "inner.py"
    inner.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
        "import runlog\n"
        "with runlog.run('video-editor', 'align'):\n"
        "    pass\n")
    assert "RUNLOG_BATCH" not in os.environ
    with runlog.run("video-editor", "render", video="lisa", attempt=1, batch_dir=b) as outer:
        assert os.environ["RUNLOG_BATCH"] == str(b.resolve())
        assert os.environ["RUNLOG_PARENT"] == outer["id"]
        with runlog.run("video-editor", "qc", batch_dir=b) as nested:
            assert nested["parent"] == outer["id"]
        subprocess.run([sys.executable, str(inner)], check=True, cwd=str(TMP))
    assert "RUNLOG_BATCH" not in os.environ and "RUNLOG_PARENT" not in os.environ
    ev = events(b)
    align = [e for e in ev if e["step"] == "align"]
    assert len(align) == 2 and align[0]["parent"] == outer["id"] and align[0]["pid"] != os.getpid()
    qc = [e for e in ev if e["step"] == "qc"][0]
    assert qc["parent"] == outer["id"]


def test_script_decorator_reads_slug_and_attempt_from_argv():
    b = batch()
    # CF-0251: the walk from argv writes only into an open journal
    runlog.emit(b, runlog.KIND_MARKER, None, status="batch-start")
    saved = sys.argv
    sys.argv = ["render.py", "--slug", "lisa", "--attempt", "3", str(b / "work" / "lisa" / "plan.json")]
    try:
        @runlog.script("video-editor", "render", video_arg="--slug", attempt_arg="--attempt")
        def main():
            return 42
        assert main() == 42
    finally:
        sys.argv = saved
    ev = [e for e in events(b) if e["kind"] == "script"]   # batch found by walking up from the path argument
    assert ev and ev[0]["video"] == "lisa" and ev[0]["attempt"] == 3
    assert ev[0]["name"] == "render.py"
    assert ev[0]["params"]["--slug"] == "lisa"
    assert ev[-1]["status"] == "done"


def test_batch_dir_lookup_order():
    b1, b2, b3 = batch(), batch(), batch()
    assert runlog.find_batch_dir(b1) == b1.resolve()
    os.environ["RUNLOG_BATCH"] = str(b2)
    try:
        assert runlog.find_batch_dir() == b2.resolve()
        assert runlog.find_batch_dir(b1) == b1.resolve()          # explicit beats env
    finally:
        del os.environ["RUNLOG_BATCH"]
    deep = b3 / "work" / "lisa" / "clips"
    deep.mkdir(parents=True)
    assert runlog.find_batch_dir(paths=[deep / "x.mp4"], use_cwd=False) == b3.resolve()
    assert runlog.find_batch_dir(paths=["--flag", "nope"], use_cwd=False) is None
    cwd = os.getcwd()
    os.chdir(deep)
    try:
        assert runlog.find_batch_dir(paths=[]) == b3.resolve()
    finally:
        os.chdir(cwd)
    # a dir that is not under pipeline/ but holds RUN_LOG.txt counts too
    other = TMP / "elsewhere" / "run"
    other.mkdir(parents=True)
    (other / "RUN_LOG.txt").write_text("x")
    assert runlog.find_batch_dir(paths=[other / "a" / "b"], use_cwd=False) == other.resolve()


def test_emit_never_raises_without_a_batch_or_on_an_unwritable_dir():
    cwd = os.getcwd()
    os.chdir(TMP)           # nothing batch-like above here
    try:
        ev = runlog.emit(None, "script", "trend-hunter", status="start")
        assert ev is not None and ev["ts"].endswith("Z")
        with runlog.run("trend-hunter", "fetch"):
            pass            # no batch: warns, does not raise
    finally:
        os.chdir(cwd)
    ro = TMP / "readonly"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        if os.access(ro, os.W_OK):      # running as root: cannot make it unwritable
            return
        assert runlog.emit(ro, "script", "x", status="start") is None
        with runlog.run("x", batch_dir=ro):
            pass
        assert runlog.run_child(["true"], batch_dir=ro).returncode == 0
        assert not (ro / "RUN_EVENTS.jsonl").exists()
    finally:
        ro.chmod(0o700)
    assert runlog.emit(TMP / "missing" / "dir", "script", "x", status="start") is None


def test_concurrent_writers_leave_valid_jsonl():
    b = batch()
    n_threads, n_each = 8, 60

    def worker(k):
        for i in range(n_each):
            with runlog.run("video-editor", "render", video=f"v{k}", attempt=i, batch_dir=b,
                            params={"pad": "x" * 100}):
                pass

    ts = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    lines = (b / "RUN_EVENTS.jsonl").read_text().splitlines()
    assert len(lines) == n_threads * n_each * 2, len(lines)
    ev = [json.loads(line) for line in lines]
    assert len({e["id"] for e in ev}) == n_threads * n_each
    # and across processes: two CLI markers racing
    procs = [subprocess.Popen(CLI + ["batch-start", "--batch", str(b), "--no-render"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for _ in range(3)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    assert all(json.loads(line) for line in (b / "RUN_EVENTS.jsonl").read_text().splitlines())


def test_marker_without_batch_start_is_exit_2_with_a_clear_message():
    b = batch()
    for args in (("stage-start", "trend-hunter"), ("stage-done", "trend-hunter"), ("batch-done",)):
        cp = cli(*args, "--batch", str(b))
        assert cp.returncode == 2, (args, cp.stdout, cp.stderr)
        assert "before batch-start" in cp.stderr and "runlog batch-start" in cp.stderr, cp.stderr
    assert not (b / "RUN_EVENTS.jsonl").exists()
    # no batch dir at all
    cp = cli("stage-start", "trend-hunter", "--batch", str(TMP / "nowhere"))
    assert cp.returncode == 2
    cwd = os.getcwd()
    os.chdir(TMP)
    try:
        cp = cli("batch-start")
        assert cp.returncode == 2 and "no batch directory" in cp.stderr, cp.stderr
    finally:
        os.chdir(cwd)
    try:
        runlog.marker("stage-done", "x", batch_dir=b)
    except runlog.RunlogError as e:
        assert "batch-start" in str(e)
    else:
        raise AssertionError("marker() strict did not raise")


def test_stage_done_needs_an_open_stage_start():
    b = batch()
    assert cli("batch-start", "--batch", str(b)).returncode == 0
    cp = cli("stage-done", "trend-hunter", "--batch", str(b))
    assert cp.returncode == 2 and "no open stage-start for 'trend-hunter'" in cp.stderr, cp.stderr
    assert cli("stage-start", "trend-hunter", "--batch", str(b)).returncode == 0
    assert cli("stage-done", "trend-hunter", "--batch", str(b), "--note", "7 topics").returncode == 0
    cp = cli("stage-done", "trend-hunter", "--batch", str(b))       # closed twice
    assert cp.returncode == 2
    # sub-stage names pass verbatim
    assert cli("stage-start", "footage-indexer-descriptions", "--batch", str(b)).returncode == 0
    assert cli("stage-done", "footage-indexer-descriptions", "--batch", str(b)).returncode == 0
    assert cli("batch-done", "--batch", str(b)).returncode == 0
    ev = events(b)
    markers = [e for e in ev if e["kind"] == "marker"]     # CF-0108: samples interleave
    assert [e["status"] for e in markers] == [
        "batch-start", "stage-start", "stage-done", "stage-start", "stage-done", "batch-done"]
    assert markers[2]["note"] == "7 topics"
    assert (b / "RUN_LOG.txt").exists()          # markers render as they go


def test_a_rebuild_video_editor_stage_done_without_its_own_05_warns_and_records_it():
    """CF-0416: a rebuild writes its own 05 with the Editor's code; one whose
    video-editor stage closes without it is told so (a warning, and a field on
    the event) - not refused, since stage-done is never refused on content."""
    _n[0] += 1
    b = TMP / f"p{_n[0]}" / "pipeline" / "rebuilds" / "2026-09-27T1757Z"
    b.mkdir(parents=True)
    assert cli("batch-start", "--batch", str(b), "--anyway", "test").returncode == 0
    assert cli("stage-start", "video-editor", "--batch", str(b)).returncode == 0
    cp = cli("stage-done", "video-editor", "--batch", str(b))
    assert cp.returncode == 0, cp.stderr
    assert "no 05-video-editor.json of its own" in cp.stderr, cp.stderr
    done = [e for e in events(b) if e.get("status") == "stage-done"][-1]
    assert done[runlog.REBUILD_RECORD_KEY]["file"] == "05-video-editor.json", done
    # with the record on disk: silence
    (b / "05-video-editor.json").write_text("{}")
    assert cli("stage-start", "video-editor", "--batch", str(b)).returncode == 0
    cp = cli("stage-done", "video-editor", "--batch", str(b))
    assert cp.returncode == 0 and "of its own" not in cp.stderr, cp.stderr
    # an ordinary batch is not a rebuild: no warning there
    o = batch()
    assert cli("batch-start", "--batch", str(o)).returncode == 0
    assert cli("stage-start", "video-editor", "--batch", str(o)).returncode == 0
    cp = cli("stage-done", "video-editor", "--batch", str(o))
    assert cp.returncode == 0 and "of its own" not in cp.stderr, cp.stderr


def test_batch_start_header_has_the_fields():
    b = batch()
    (b / "01-trend-hunter.json").write_text(json.dumps({"topics": [
        {"evidence": {"sources": ["a", "b"]}}, {"evidence": {"sources": ["b", "c"]}}, {}]}))
    (b / "03-content-researcher.json").write_text(json.dumps({"scripts": [{}, {}]}))
    env = {"CLAUDE_MODEL": "test-operator-model", "FACTORY_ROOT": str(ROOT)}   # header of the real repo; writes nothing there
    cp = cli("batch-start", "--batch", str(b), env=env)
    assert cp.returncode == 0, cp.stderr
    ev = events(b)[0]
    assert ev["kind"] == "marker" and ev["status"] == "batch-start"
    h = ev["header"]
    for key in ("batch", "git", "version", "models", "counts", "machine"):
        assert key in h, (key, h)
    assert h["batch"] == f"fashion/{b.name}"
    root = h["git"]["root"]
    assert root and len(root["commit"]) == 40 and isinstance(root["dirty"], bool), root
    for name in runlog.AGENT_NAMES:
        assert name in h["git"]["agents"]
    if not (ROOT / "agents").exists():
        assert all(v is None for v in h["git"]["agents"].values()), h["git"]["agents"]
    assert h["version"] == runlog.readme_version(ROOT) and h["version"]
    assert h["models"]["operator"] == "test-operator-model"
    assert "subagents" in h["models"] and "subagent_default" in h["models"]
    assert h["counts"] == {"topics": 3, "sources": 3, "videos": 2}
    m = h["machine"]
    for key in ("platform", "os", "cpu", "cpu_count", "ram_gb", "gpu"):
        assert key in m, (key, m)
    assert m["cpu_count"] and m["ram_gb"]
    if sys.platform == "darwin":
        assert m["cpu"] and m["os"].startswith("macOS"), m


def test_models_are_read_never_guessed():
    for key in ("CLAUDE_MODEL", "ANTHROPIC_MODEL"):
        saved = os.environ.pop(key, None)
        try:
            pass
        finally:
            if saved is not None:
                os.environ[key] = saved
    env = dict(os.environ)
    env.pop("CLAUDE_MODEL", None)
    env.pop("ANTHROPIC_MODEL", None)
    env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
    out = subprocess.run(CLI + ["header", "--batch", str(batch())], capture_output=True,
                         text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    h = json.loads(out.stdout)
    assert h["models"]["operator"] is None
    assert h["models"]["subagent_default"] is None


def test_readme_version_is_parsed_from_the_heading():
    d = TMP / "readme"
    d.mkdir()
    (d / "README.md").write_text("# Shorts Content Factory — 1.2, with 1.3 in progress\n\ntext\n")
    assert runlog.readme_version(d) == "1.2"
    (d / "README.md").write_text("# Thing 2.0.1\n")
    assert runlog.readme_version(d) == "2.0.1"
    assert runlog.readme_version(TMP / "nope") is None


def test_render_runlog_is_readable_and_keeps_stage_done_lines():
    b = batch()
    runlog.marker("batch-start", batch_dir=b, note="run 3")
    runlog.marker("stage-start", "trend-hunter", batch_dir=b)
    with runlog.run("trend-hunter", "fetch", batch_dir=b, name="fetch_rss_news.py"):
        runlog.run_child(["true"], tool="chrome")
    runlog.marker("stage-done", "trend-hunter", batch_dir=b, note="7 topics")
    runlog.marker("stage-start", "video-editor", batch_dir=b)
    with runlog.run("video-editor", "resolve", video="lisa", attempt=1, batch_dir=b, name="resolve_anchors.py"):
        pass
    try:
        with runlog.run("video-editor", "render", video="lisa", attempt=2, batch_dir=b, name="render.py"):
            runlog.run_child(["sh", "-c", "exit 1"], tool="ffmpeg")
            raise RuntimeError("ffmpeg failed")
    except RuntimeError:
        pass
    runlog.emit(b, "script", "video-editor", step="qc", video="lisa", attempt=2, status="start",
                event_id="deadbeef0000", name="qc.py")           # cut run: no end
    runlog.marker("stage-done", "video-editor", batch_dir=b)
    runlog.marker("batch-done", batch_dir=b)
    text = runlog.render_runlog(b)
    lines = text.splitlines()
    assert lines[0].startswith("# RUN_LOG.txt - generated")
    assert "MSK" not in text and "+03:00" not in text
    stage_done = [l for l in lines if l.startswith("STAGE_DONE ")]
    assert stage_done[0].startswith("STAGE_DONE trend-hunter 20") and stage_done[0].endswith("7 topics"), stage_done
    assert stage_done[1].startswith("STAGE_DONE video-editor ")
    assert any(l.startswith("STAGE_START trend-hunter 20") for l in lines)
    assert lines[1].startswith(f"BATCH_START fashion/{b.name} 20") and lines[1].endswith(" run 3") and " machine=" in lines[1]
    assert lines[2].startswith("  version=") and "root=" in lines[2] and "cpu=" in lines[2]
    assert any(l.startswith(f"BATCH_DONE fashion/{b.name} 20") for l in lines)
    assert any(l.startswith("  trend-hunter/fetch (fetch_rss_news.py) done 20") for l in lines), text
    assert any(l.startswith("    chrome done ") for l in lines), text
    assert any(l.startswith("  video-editor/resolve (resolve_anchors.py) lisa attempt 1 done ") for l in lines), text
    render = [l for l in lines if l.startswith("  video-editor/render (render.py) lisa attempt 2 failed ")]
    assert render and render[0].endswith("RuntimeError: ffmpeg failed"), text
    assert any(l.startswith("    ffmpeg failed ") and "rc=1" in l for l in lines), text
    assert any("video-editor/qc (qc.py) lisa attempt 2 started " in l and "(no end recorded)" in l
               for l in lines), text
    # every timestamp in the file is Z
    import re
    stamps = re.findall(r"\d{4}-\d\d-\d\dT[\d:.]+(\S*)", text)
    assert stamps and all(s == "Z" for s in stamps), stamps
    # the root has no programmatic RUN_LOG reader (rotation/ledger reads
    # 05-video-editor.json); the shape kept for grep is `STAGE_DONE <stage> ...`
    assert all(re.match(r"^STAGE_DONE \S+ \d{4}-", l) for l in stage_done)


def test_write_runlog_does_not_clobber_a_hand_written_log():
    b = batch()
    (b / "RUN_LOG.txt").write_text("2026-09-01 12:00 MSK BATCH_START by hand\n")
    runlog.marker("batch-start", batch_dir=b)
    out = runlog.write_runlog(b)
    assert out.name == "RUN_LOG.generated.txt"
    assert (b / "RUN_LOG.txt").read_text().startswith("2026-09-01 12:00 MSK")
    out = runlog.write_runlog(b, force=True)
    assert out.name == "RUN_LOG.txt" and runlog.is_generated(out)
    # once generated, later renders overwrite in place
    runlog.marker("batch-done", batch_dir=b)
    assert runlog.write_runlog(b).name == "RUN_LOG.txt"
    assert "BATCH_DONE" in (b / "RUN_LOG.txt").read_text()
    cp = cli("render", "--batch", str(b), "--stdout")
    assert cp.returncode == 0 and cp.stdout.startswith("# RUN_LOG.txt - generated")


def test_cli_tail_and_help():
    b = batch()
    runlog.marker("batch-start", batch_dir=b)
    with runlog.run("trend-hunter", batch_dir=b):
        pass
    cp = cli("tail", "--batch", str(b), "-n", "2")
    assert cp.returncode == 0
    rows = [json.loads(l) for l in cp.stdout.splitlines()]
    assert len(rows) == 2 and rows[-1]["status"] == "done"
    assert cli("--help").returncode == 0 and "batch-start" in cli("--help").stdout
    assert cli("bogus").returncode == 2


def test_machine_id_is_stable_and_persisted():
    a = runlog.machine_id()
    assert a == runlog.machine_id()
    assert (TMP / "state" / "machine-id").is_file()
    import re
    assert re.match(r"^[A-Za-z0-9-]+-[0-9a-f]{8}$", a), a
    # a second process on the same state dir agrees
    out = subprocess.run([sys.executable, "-c",
                          f"import sys; sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r}); "
                          "import runlog; print(runlog.machine_id())"],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == a, out


def test_overhead_is_milliseconds_per_event():
    """An event costs milliseconds. CF-0649: an event is syscall-bound (path
    resolve, open, append), and under a loaded Mac (load 10-20, Time Machine,
    mediaanalysisd) every syscall stretches - the flat 5 ms went red with the
    library unchanged. The budget is 5 ms on a quiet machine and, on a loaded
    one, 25x the cheapest honest write of the same line to the same disk,
    measured interleaved with the events in this run (an event is ~6x that
    write). A regression that is not load - a subprocess or a journal re-read
    per event - blows through both."""
    import time
    b = batch()
    with runlog.run("video-editor", "render", attempt=-1, batch_dir=b):   # warm-up, and a line
        pass
    line = (b / runlog.EVENTS_FILE).read_text().splitlines()[-1] + "\n"
    raw = b / "raw-append.jsonl"
    t_events = t_raw = 0.0
    for r in range(5):                                   # interleaved: same load for both
        t = time.perf_counter()
        for i in range(40):
            with runlog.run("video-editor", "render", attempt=r * 40 + i, batch_dir=b):
                pass
        t_events += time.perf_counter() - t
        t = time.perf_counter()
        for _ in range(80):
            with open(raw, "a", encoding="utf-8") as fh:
                fh.write(line)
        t_raw += time.perf_counter() - t
    per_event, per_raw = t_events / 400, t_raw / 400
    budget = max(0.005, 25 * per_raw)
    assert per_event < budget, (f"{per_event*1000:.2f} ms per event, budget {budget*1000:.2f} ms "
                                f"(a raw append of the line: {per_raw*1000:.3f} ms)")



# ------------------------------------------- CF-0541: a relative batch path
def test_a_relative_batch_path_is_made_absolute_before_a_child_sees_it():
    env = {"RUNLOG_BATCH": "pipeline/example-film/b1"}
    root_batch = FAKE_ROOT / "pipeline" / "example-film" / "b1"
    root_batch.mkdir(parents=True, exist_ok=True)
    # from the caller's directory when it is there
    assert runlog.normalize_batch_env(env, cwd=FAKE_ROOT) == str(root_batch.resolve())
    assert env["RUNLOG_BATCH"] == str(root_batch.resolve())
    # an absolute one is left as it is
    assert runlog.normalize_batch_env(env, cwd=TMP) == str(root_batch.resolve())
    # from an agent's directory it is not there - the factory root has it
    agent = FAKE_ROOT / "agents" / "trend-hunter"
    agent.mkdir(parents=True, exist_ok=True)
    assert runlog.resolve_batch_path("pipeline/example-film/b1", cwd=agent) == root_batch.resolve()
    # nothing anywhere: the caller's directory, as before
    assert runlog.resolve_batch_path("nowhere/b9", cwd=agent) == (agent / "nowhere" / "b9").resolve()
    assert runlog.normalize_batch_env({}) is None


def test_children_in_agent_dirs_write_a_relative_batch_into_its_journal():
    """CF-0541 (batch 0701Z, the supplement): the operator's shell had
    `RUNLOG_BATCH=pipeline/example-film/<batch>`, the root started the hunter
    and the indexer with `cwd=agents/<agent>`, and their events went to
    `agents/<agent>/pipeline/...` - not written. Both routes now land in the
    batch: a root parent that imports the library hands its children the
    absolute path, and a child that got the relative one anyway finds the
    batch under the factory root."""
    b = FAKE_ROOT / "pipeline" / "example-film" / "2026-10-05T0701Z-cf0541"
    b.mkdir(parents=True)
    rel = "pipeline/example-film/2026-10-05T0701Z-cf0541"
    hunter = FAKE_ROOT / "agents" / "trend-hunter"
    indexer = FAKE_ROOT / "agents" / "footage-indexer"
    for d in (hunter, indexer):
        d.mkdir(parents=True, exist_ok=True)
    child = TMP / "cf0541_child.py"
    child.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
        "import runlog\n"
        "print(os.environ['RUNLOG_BATCH'])\n"
        "with runlog.run(sys.argv[1], 'search'):\n"
        "    pass\n")
    parent = TMP / "cf0541_parent.py"
    parent.write_text(
        "import os, subprocess, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
        "import runlog\n"
        f"subprocess.run([sys.executable, {str(child)!r}, 'trend-hunter'],\n"
        f"               cwd={str(hunter)!r}, check=True)\n")
    env = dict(os.environ, RUNLOG_BATCH=rel, FACTORY_ROOT=str(FAKE_ROOT))
    env.pop("RUNLOG_PARENT", None)
    out = subprocess.run([sys.executable, str(parent)], cwd=str(FAKE_ROOT), env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == str(b.resolve()), out.stdout   # the child got it absolute
    # a child started with the relative path from its own directory
    out = subprocess.run([sys.executable, str(child), "footage-indexer"], cwd=str(indexer),
                         env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "event not written" not in out.stderr, out.stderr
    ev = [e for e in events(b) if e["kind"] == "script"]
    assert sorted({e["stage"] for e in ev}) == ["footage-indexer", "trend-hunter"], ev
    assert len(ev) == 4, ev
    for d in (hunter, indexer):
        assert not (d / "pipeline").exists(), d

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
    for pf in TMP.glob("*/pipeline/*/*/RUN_SAMPLER.pid"):        # CF-0108: batches left open
        runlog.sibling("sampler").stop(pf.parent)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
