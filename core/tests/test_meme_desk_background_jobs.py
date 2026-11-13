#!/usr/bin/env python3
"""CF-0755: the meme desk's background jobs for the command center 0.4.1
(CC-0075/CC-0076) - start_job / job_status / list_jobs and `job-run`.

What is checked, on temp banks only (test_meme_desk_jobs.world under the
runner's temp root; the real banks and the real schedule/ are never opened):
* start_job refuses exactly what the job's plan refuses - before any process
  starts and before anything is written;
* a job really runs detached: a real `python3` child (a stub of job-run whose
  embedding is a stand-in - no yt-dlp, ffmpeg, Vision or network) writes its
  progress, result and outcome into the state file; a crash is job_crashed
  with the log's tail; PATH gets the homebrew folders;
* one job per machine (job_running with the job's id, read from disk - a
  fresh process sees it too); a job whose process died is `interrupted` and
  does not hold the slot;
* job-run in this process (its child a no-op) for the trim, the add, the
  cutout and the embedding: done / failed with the function's code;
* the last 50 records per bank, list_jobs newest first; the slot's folder is
  the main checkout's schedule/meme-desk/.
Every child started here is this test's own and is stopped by its own pid.
"""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import inserts_lib as lib  # noqa: E402,F401
import meme_desk as desk  # noqa: E402
from _tmproot import tmp_root  # noqa: E402
from test_meme_cutout import disk  # noqa: E402
from test_meme_desk_jobs import FakeVision, refused, snapshot, stand_ins, world  # noqa: E402

TMP = tmp_root("meme-desk-bg-jobs-")
WHO = {"by": "user", "via": "center"}

# job-run with its embedding a stand-in (STUB_EMBED=ok|crash|slow), network closed
REAL_STUB = f"""
import os, sys, time, urllib.request
sys.path.insert(0, {str(ROOT / 'scripts')!r})
import meme_desk as desk

def no_net(*a, **kw):
    raise AssertionError("a job stub reached the network")

urllib.request.urlopen = no_net

def embed(name, root):
    mode = os.environ.get("STUB_EMBED", "ok")
    if mode == "crash":
        raise RuntimeError("boom in the embedding")
    return {{"done": True, "line": os.environ["PATH"], "error": None, "en": None,
            "fatal": False}}

desk._embed_run = embed
desk.main(["job-run", sys.argv[1]])
"""
# a job-run that never ends on its own: it waits for <state_file>.release (30 s cap)
SLEEPER = """
import sys, time
from pathlib import Path
release = Path(sys.argv[1] + ".release")
end = time.monotonic() + 30
while time.monotonic() < end and not release.exists():
    time.sleep(0.05)
"""
NOOP = [sys.executable, "-c", "pass"]


def stub(tmp, text, name):
    p = Path(tmp) / name
    p.write_text(text)
    return [sys.executable, str(p)]


@contextlib.contextmanager
def child(argv):
    saved = desk.JOB_ARGV
    desk.JOB_ARGV = argv
    try:
        yield
    finally:
        desk.JOB_ARGV = saved


@contextlib.contextmanager
def own_pids():
    """The pids of the children a test starts; each still alive at the end is
    stopped by its own process group (start_new_session: pgid = pid)."""
    pids = []
    try:
        yield pids
    finally:
        for pid in pids:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                os.waitpid(pid, os.WNOHANG)


def wait_until(pred, timeout=30.0, what="the job"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.05)
    raise AssertionError(f"{what}: not within {timeout} s")


def ended(job_id, **kw):
    wait_until(lambda: desk.job_status(job_id, **kw)["state"] != "running", what=job_id)
    return desk.job_status(job_id, **kw)


def env(tmp, **over):
    e = {k: v for k, v in os.environ.items() if k != desk.JOBS_DIR_ENV}
    e.update(over)
    return e


def quiet_run(state_file):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = desk.job_run(state_file)
    return code, out.getvalue(), err.getvalue()


def started(kind, params, kw, **extra):
    """start_job with a no-op child; returns once the child is gone (the slot
    is free again), the state file still says running - job_run is then run
    in this process."""
    with child(NOOP):
        r = desk.start_job(kind, params, **WHO, **kw, **extra)
    wait_until(lambda: not desk._lock_held(Path(r["state_file"]).with_suffix(".lock")))
    with contextlib.suppress(OSError):
        os.waitpid(r["pid"], 0)
    return r


# --------------------------------------------------------------------------
# 1. refusals: the plan's, before anything starts or is written
# --------------------------------------------------------------------------

def test_start_job_refuses_what_the_plan_refuses_and_writes_nothing():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        (t / "elsewhere.mp4").write_bytes(b"x")
        before = snapshot(t)
        cases = [
            ("add_image", dict(meme_id="x", url="file:///etc/passwd", source_url="https://e.org",
                               description="d", tags="a,b"),
             desk.plan_add_image, ("x", "file:///etc/passwd", "https://e.org", "d", "a,b")),
            ("add_gif", dict(meme_id="x", video=str(t / "elsewhere.mp4"), start=0, end=1,
                             description="d", tags="a", source_url="https://e.org", local=True),
             desk.plan_add_gif, ("x", str(t / "elsewhere.mp4"), 0, 1, "d", "a", "https://e.org")),
            ("sheet", dict(video="https://e.org/v", start=0, end=400, every=1),
             desk.plan_sheet, ("https://e.org/v", 0, 400, 1)),
        ]
        with stand_ins(_cutout_check=lambda: (True, "t", "t")), child(NOOP):
            for kind, params, plan, args in cases:
                extra = {"local": True} if params.get("local") else {}
                try:
                    plan(*args, bank="memes-tech", **extra, **kw)
                except desk.MemeDeskError as e:
                    code = e.code
                else:
                    raise AssertionError(f"plan of {kind} took {params}")
                refused(code, desk.start_job, kind, params, bank="memes-tech", **WHO, **kw)
            # the dry runs: a GIF / an unticked still is not_cutout, an unknown id
            refused("not_cutout", desk.start_job, "cutout", {"ids": ["plain"]},
                    bank="memes-tech", **WHO, **kw)
            refused("unknown_id", desk.start_job, "trim_blank", {"id": "nope"},
                    bank="memes-tech", **WHO, **kw)
            refused("bad_bank", desk.start_job, "embed", {}, bank="memes-nope", **WHO, **kw)
            refused("bad_kind", desk.start_job, "rm", {}, bank="memes-tech", **WHO, **kw)
            refused("bad_params", desk.start_job, "cutout", {"dry_run": True},
                    bank="memes-tech", **WHO, **kw)
            refused("bad_params", desk.start_job, "add_image", {"meme_id": "x"},
                    bank="memes-tech", **WHO, **kw)
            refused("bad_params", desk.start_job, "embed", [], bank="memes-tech", **WHO, **kw)
            refused("bad_params", desk.start_job, "sheet", {"video": object()},
                    bank="memes-tech", **WHO, **kw)
            refused("bad_who", desk.start_job, "embed", {}, bank="memes-tech", by=None,
                    via="center", **kw)
            refused("bad_who", desk.start_job, "embed", {}, bank="memes-tech", by="user",
                    via="two\nlines", **kw)
        with stand_ins(_platform=lambda: ("linux", "")), child(NOOP):
            refused("cutout_unavailable", desk.start_job, "cutout", {}, bank="memes-tech",
                    **WHO, **kw)
        assert snapshot(t) == before, "a refused start wrote something"


# --------------------------------------------------------------------------
# 2. a real detached job-run: state file, progress, result, crash, PATH
# --------------------------------------------------------------------------

def test_a_job_runs_detached_and_writes_its_outcome():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp, own_pids() as pids:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        with child(stub(tmp, REAL_STUB, "job_stub.py")):
            r = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw,
                               environ=env(tmp, PATH="/usr/bin:/bin"))
        pids.append(r["pid"])
        assert set(r) == {"job_id", "bank", "kind", "pid", "log", "state_file"}, r
        assert r["bank"] == "memes-tech" and r["kind"] == "embed"
        jobs = inserts / "memes-tech" / "_desk" / "jobs"
        assert Path(r["state_file"]) == jobs / f"{r['job_id']}.json"
        assert Path(r["log"]) == jobs / f"{r['job_id']}.log"
        assert desk.JOB_ID_RE.fullmatch(r["job_id"]) and "-embed-" in r["job_id"]
        s = ended(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "done" and s["done"] and not s["alive"], s
        assert s["error"] is None and s["by"] == "user" and s["via"] == "center"
        assert s["progress"] == {"step": "embedding", "i": 1, "of": 1,
                                 "text": desk.EMBED_STEP_RU}, s["progress"]
        assert s["result"]["embedding"]["done"] is True
        assert s["result"]["embedding"]["line"] == \
            "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "job-run puts homebrew first"
        assert s["pid"] == r["pid"] and s["started_at"] and s["ended_at"]
        assert s["max_seconds"] == desk._embed_seconds(True)
        raw = json.loads(Path(r["state_file"]).read_text())
        for k in ("job_id", "kind", "bank", "bank_name", "root", "repo", "params", "plan",
                  "by", "via", "state", "started_at", "attached_at", "ended_at", "pid",
                  "progress", "result", "error", "log", "machine_dir"):
            assert k in raw, k
        assert raw["state"] == "done" and raw["bank_name"] == "memes-tech"
        log = Path(r["log"]).read_text()
        assert f"job {r['job_id']}: done" in log, log
        rows = [json.loads(x) for x in
                (inserts / "memes-tech" / "_desk" / "jobs.jsonl").read_text().splitlines()]
        assert rows[-1]["kind"] == "embed" and rows[-1]["by"] == "user", rows
        mdir = repo / "schedule" / "meme-desk"
        # CF-0858: the slot is free the moment the file says done (alive False);
        # job-run removes the slot's stale active.json right after - wait for it
        a = desk.active_job(**kw, environ=env(tmp))
        assert a is None or (a["job_id"] == r["job_id"] and not a["alive"]), a
        wait_until(lambda: not (mdir / desk.JOBS_ACTIVE).exists(), what="the ended job's slot")

        # a crash: job_crashed with the traceback's tail from the log
        with child(stub(tmp, REAL_STUB, "job_stub.py")):
            r = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw,
                               environ=env(tmp, STUB_EMBED="crash"))
        pids.append(r["pid"])
        s = ended(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "failed" and s["error"]["code"] == "job_crashed", s
        assert "RuntimeError: boom in the embedding" in s["error"]["log_tail"], s["error"]
        assert "boom in the embedding" in s["error"]["en"]          # CF-0762: the detail is in en
        assert s["error"]["text"] == "задача упала — подробности в её журнале", s["error"]


def test_the_slot_is_free_once_the_outcome_is_written_before_its_file_goes():
    """CF-0858: job-run writes the outcome, then removes active.json - the
    window between the two is held open here (a hook at the slot's lock) and
    is safe: the center sees the job ended and not alive, and a new start is
    let in; the old job's unlink then leaves the new job's slot alone. While
    the job still says running (its lock held), a start is refused."""
    with tempfile.TemporaryDirectory(dir=TMP) as tmp, own_pids() as pids:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        mdir = repo / "schedule" / "meme-desk"
        with stand_ins():
            r = started("embed", {}, kw, bank="memes-tech")
        pids.append(r["pid"])
        assert desk._job_read(mdir / desk.JOBS_ACTIVE)["job_id"] == r["job_id"]
        import fcntl
        fd = os.open(str(Path(r["state_file"]).with_suffix(".lock")), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)          # this process is the job's job-run now
        seen = {}
        real_flocked = desk._flocked

        @contextlib.contextmanager
        def hooked(path):
            if Path(path).resolve() == (mdir / ".lock").resolve() and "window" not in seen:
                seen["window"] = True           # between the outcome and the unlink
                s = desk._job_read(r["state_file"])
                seen["state"] = s["state"]
                seen["slot_file"] = (mdir / desk.JOBS_ACTIVE).exists()
                seen["active"] = desk.active_job(**kw, environ=env(tmp))
                seen["status"] = desk.job_status(r["job_id"], bank="memes-tech", **kw)
                with child(NOOP):
                    seen["next"] = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw,
                                                  environ=env(tmp))
                pids.append(seen["next"]["pid"])
            with real_flocked(path):
                yield

        try:
            with child(NOOP):                   # running + lock held: the slot is busy
                e = refused("job_running", desk.start_job, "embed", {}, **WHO, **kw,
                            environ=env(tmp))
            assert e.job_id == r["job_id"]
            with stand_ins(_flocked=hooked):
                code, out, err = quiet_run(r["state_file"])
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        assert code == 0, (out, err)
        assert seen.get("window"), "job-run never freed the slot"
        assert seen["state"] == "done" and seen["slot_file"], seen
        assert seen["active"]["job_id"] == r["job_id"] and not seen["active"]["alive"], seen
        assert seen["status"]["done"] and not seen["status"]["alive"], seen["status"]
        nxt = seen["next"]
        assert nxt["job_id"] != r["job_id"]
        assert desk._job_read(mdir / desk.JOBS_ACTIVE)["job_id"] == nxt["job_id"], \
            "the ended job's unlink took the next job's slot"


# --------------------------------------------------------------------------
# 3. one job per machine; a dead job is interrupted and frees the slot
# --------------------------------------------------------------------------

def test_one_job_per_machine_and_a_dead_job_is_interrupted():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp, own_pids() as pids:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        sleeper = stub(tmp, SLEEPER, "sleeper.py")
        with child(sleeper):
            first = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw)
        pids.append(first["pid"])
        s = desk.job_status(first["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "running" and s["alive"] and not s["done"], s
        assert s["result"] is None and s["error"] is None
        with child(NOOP):
            e = refused("job_running", desk.start_job, "embed", {}, **WHO, **kw)
        assert e.job_id == first["job_id"] and first["job_id"] in e.text
        # a restarted center: a fresh process reads the slot from disk
        code = (f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
                "import meme_desk as d\n"
                "try:\n"
                f"    d.start_job('embed', {{}}, by='user', via='center', root={str(inserts)!r},"
                f" repo={str(repo)!r})\n"
                "except d.MemeDeskError as e:\n"
                "    print(e.code, e.job_id)\n")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             timeout=60)
        assert out.stdout.split() == ["job_running", first["job_id"]], (out.stdout, out.stderr)
        listed = desk.list_jobs(bank="memes-tech", **kw)
        assert [j["job_id"] for j in listed] == [first["job_id"]]
        # the process dies (killed, reboot): interrupted, not running forever
        os.killpg(first["pid"], signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(first["pid"], 0)
        s = desk.job_status(first["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "interrupted" and s["done"] and not s["alive"], s
        assert s["error"]["code"] == "job_interrupted" and "log_tail" in s["error"]
        # ... and it does not block the next one
        with child(sleeper):
            nxt = desk.start_job("embed", {}, **WHO, **kw)
        pids.append(nxt["pid"])
        assert nxt["bank"] == "memes" and nxt["job_id"] != first["job_id"]
        Path(nxt["state_file"] + ".release").write_text("")
        wait_until(lambda: not desk._lock_held(Path(nxt["state_file"]).with_suffix(".lock")))
        with contextlib.suppress(ChildProcessError):
            os.waitpid(nxt["pid"], 0)
        # its job-run never wrote an outcome: interrupted too, and the slot is free
        assert desk.job_status(nxt["job_id"], **kw)["state"] == "interrupted"
        with child(NOOP):
            third = desk.start_job("embed", {}, **WHO, **kw)
        pids.append(third["pid"])


def test_a_child_that_cannot_start_is_spawn_failed_and_frees_the_slot():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp, own_pids() as pids:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        with child([str(Path(tmp) / "no-such-python")]):
            refused("spawn_failed", desk.start_job, "embed", {}, bank="memes-tech", **WHO, **kw)
        (j,) = desk.list_jobs(bank="memes-tech", **kw)
        assert j["state"] == "failed" and j["error"]["code"] == "spawn_failed", j
        with child(NOOP):
            r = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw)
        pids.append(r["pid"])


# --------------------------------------------------------------------------
# 4. job-run in this process: the real functions, stand-ins underneath
# --------------------------------------------------------------------------

def test_job_run_runs_the_function_and_records_its_outcome():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        with stand_ins() as calls:
            r = started("trim_blank", {}, kw, bank="memes-tech")
            code, out, err = quiet_run(r["state_file"])
        assert code == 0 and f"job {r['job_id']}: done" in out, (out, err)
        s = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "done" and s["result"]["changed"] == ["banded"], s
        assert s["progress"]["step"] == "embedding" and calls["embed"]
        assert s["max_seconds"] is None and s["params"] == {}
        notes = {e["id"]: e.get("notes") for e in json.loads(
            (inserts / "memes-tech" / "index.json").read_text())["entries"]}
        assert "trim_blank" in notes["banded"] and "by user, via center" in notes["banded"]
        # a refusal of the function itself: failed with its code
        with stand_ins() as calls:
            r = started("trim_blank", {"id": "banded"}, kw, bank="memes-tech")
            idx = json.loads((inserts / "memes-tech" / "index.json").read_text())
            idx["entries"] = [e for e in idx["entries"] if e["id"] != "banded"]
            (inserts / "memes-tech" / "index.json").write_text(json.dumps(idx))
            code, out, err = quiet_run(r["state_file"])
        s = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert code == 1 and s["state"] == "failed" and s["error"]["code"] == "unknown_id", s
        # an embedding job whose embedding did not happen is failed, not done
        with stand_ins(_embed_run=lambda n, root: {"done": False, "line": None,
                                                   "error": "нет venv", "en": "no venv",
                                                   "fatal": False}):
            r = started("embed", {}, kw, bank="memes-tech")
            code, _, _ = quiet_run(r["state_file"])
        s = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "failed" and s["error"]["code"] == "embed_failed", s
        assert s["result"]["embedding"]["done"] is False
        # an add whose download fails: the add's code, nothing in the bank
        def no_fetch(url):
            raise desk.MemeDeskError("download_failed", "не скачалось", "no download")
        params = dict(meme_id="new-one", url="https://e.org/x.png",
                      source_url="https://e.org/p", description="d", tags="a,b")
        with stand_ins(_fetch=no_fetch):
            r = started("add_image", params, kw, bank="memes-tech")
            code, _, _ = quiet_run(r["state_file"])
        s = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "failed" and s["error"]["code"] == "download_failed", s
        assert s["max_seconds"] == desk.plan_add_image(**params, bank="memes-tech",
                                                       **kw)["max_seconds"]
        assert not (inserts / "memes-tech" / "new-one.png").exists()
        # the cutout: only the ticked stills, the flag never set by the job
        fake = FakeVision({"cut-good.png": disk(), "cut-bad.png": disk()})
        with stand_ins(run_vision=fake, _cutout_check=lambda: (True, "t", "t")):
            r = started("cutout", {"ids": ["cut-good"]}, kw, bank="memes-tech")
            code, _, _ = quiet_run(r["state_file"])
        s = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert s["state"] == "done" and [m["id"] for m in s["result"]["made"]] == ["cut-good"]
        assert fake.calls == ["cut-good.png"] and s["progress"]["step"] == "cutout"
        # job-run on a file that is not a running job's: exit 2, nothing changed
        before = Path(r["state_file"]).read_text()
        code, _, err = quiet_run(r["state_file"])
        assert code == 2 and "not a running job" in err
        assert Path(r["state_file"]).read_text() == before
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                desk.main(["job-run", str(Path(tmp) / "nothing.json")])
        except SystemExit as e:
            assert e.code == 2
        else:
            raise AssertionError("job-run took a missing state file")


# --------------------------------------------------------------------------
# 5. the last 50 per bank, the list, the ids
# --------------------------------------------------------------------------

def test_the_last_50_records_are_kept_and_listed_newest_first():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        jobs = inserts / "memes-tech" / "_desk" / "jobs"
        jobs.mkdir(parents=True)
        old = [f"20260101T0000{i:02d}Z-embed-{i:06x}" for i in range(52)]
        for job_id in old:
            (jobs / f"{job_id}.json").write_text(json.dumps(
                {"job_id": job_id, "kind": "embed", "bank": "memes-tech", "state": "done"}))
            (jobs / f"{job_id}.log").write_text("x")
        r = started("embed", {}, kw, bank="memes-tech")
        left = sorted(p.stem for p in jobs.glob("*.json"))
        assert len(left) == desk.JOBS_KEEP and r["job_id"] in left, len(left)
        assert old[0] not in left and old[2] not in left and old[3] in left
        assert not (jobs / f"{old[0]}.log").exists()
        listed = desk.list_jobs(bank="memes-tech", **kw)
        assert len(listed) == 20 and listed[0]["job_id"] == r["job_id"]
        assert [j["job_id"] for j in listed[1:]] == sorted(old, reverse=True)[:19]
        assert len(desk.list_jobs(bank="memes-tech", limit=50, **kw)) == 50
        for bad in (0, 51, True, "5"):
            refused("bad_limit", desk.list_jobs, bank="memes-tech", limit=bad, **kw)
        for bad in ("../../index", "20260101T000000Z-embed-zzzzzz", None,
                    "20990101T000000Z-embed-000000"):
            refused("unknown_job", desk.job_status, bad, bank="memes-tech", **kw)
        assert desk.list_jobs(**kw) == [], "the default bank has no jobs"


# --------------------------------------------------------------------------
# 6. where the machine's slot lives
# --------------------------------------------------------------------------

def test_the_slot_lives_in_the_main_checkouts_schedule():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        main = Path(tmp) / "main"
        (main / ".git" / "worktrees" / "release-x").mkdir(parents=True)
        (main / ".git" / "worktrees" / "release-x" / "commondir").write_text("../..\n")
        wt = main / ".worktrees" / "release-x"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'release-x'}\n")
        clean = {k: v for k, v in os.environ.items() if k != desk.JOBS_DIR_ENV}
        assert desk.jobs_machine_dir(wt, clean) == main.resolve() / "schedule" / "meme-desk"
        assert desk.jobs_machine_dir(main, clean) == main / "schedule" / "meme-desk"
        lone = Path(tmp) / "lone"
        lone.mkdir()
        assert desk.jobs_machine_dir(lone, clean) == lone / "schedule" / "meme-desk"
        (lone / ".git").write_text("not a gitdir line")
        assert desk.jobs_machine_dir(lone, clean) == lone / "schedule" / "meme-desk"
        assert desk.jobs_machine_dir(wt, {**clean, desk.JOBS_DIR_ENV: str(lone / "s")}) == \
            lone / "s"
        assert desk.job_path({"PATH": "/usr/local/bin:/bin"}) == \
            "/opt/homebrew/bin:/usr/local/bin:/bin"
        assert desk.job_path({}) == "/opt/homebrew/bin:/usr/local/bin"


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
