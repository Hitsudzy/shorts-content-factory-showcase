#!/usr/bin/env python3
"""CF-0340: every render has its own job directory.

Until this task `render_video.py` staged into one shared `render/public/job/`
and began each render with `rmtree` of it. Two renders at once - the operator
starting three in the background (batch 0705Z), a rebuild beside a batch, the
daemon - wiped each other's assets and overwrote each other's props: Remotion
answered `durationInFrames NaN` (CF-0336, widows-bay) or a 404 on an asset
(Harbourlights attempt 1), and each video lost an attempt.

Locked here:
  * two job directories are distinct, and removing one leaves the other's
    staged files and props untouched;
  * two `render_video.py` processes run at the same time (Remotion replaced by
    a stub `npx` that waits, then checks that everything its props name is
    still there under the --public-dir it was handed) both render their own
    plan, and leave no job directory behind;
  * the sweep removes a stale directory of a dead owner and never a fresh one
    or one whose owner is alive;
  * the job's public dir carries everything render/public tracks.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

import render_video as rv  # noqa: E402
from repo_paths import VENV_PY  # noqa: E402

PY = str(VENV_PY) if Path(VENV_PY).exists() else sys.executable

# The stub: remotion render src/index.js Video <out> --props=... --public-dir=...
# It waits long enough for the other render to have staged (and, before
# CF-0340, wiped the shared directory), then checks its own props and files.
STUB_NPX = f"""#!{PY}
import json, sys, time
from pathlib import Path
argv = sys.argv[1:]
out = argv[4]
props = next(a for a in argv if a.startswith("--props="))[len("--props="):]
public = next(a for a in argv if a.startswith("--public-dir="))[len("--public-dir="):]
time.sleep(1.5)
plan = json.load(open(props))["plan"]
srcs = [b["asset"]["src"] for b in plan["blocks"]] + [plan["audio"]["src"]]
missing = [s for s in srcs if not (Path(public) / s).is_file()]
if missing:
    print("asset 404:", missing); sys.exit(1)
if not (Path(public) / "fonts").is_dir():
    print("no fonts in", public); sys.exit(1)
Path(out).write_bytes(b"x" * 2048)
Path(out + ".seen.json").write_text(json.dumps({{
    "title": plan["title"], "blocks": len(plan["blocks"]),
    "durationInFrames": plan["duration"]["composition"] * 30,
    "public": public, "props": props}}))
"""


def _stub_env(tmp):
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    npx = bin_dir / "npx"
    npx.write_text(STUB_NPX)
    npx.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.pop("RUNLOG_BATCH", None)
    return env


def _plan(dirpath, title, n_blocks, seconds):
    """A loose plan (no batch, no ledger) whose blocks each stage a file."""
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    blocks = []
    for i in range(n_blocks):
        f = d / f"shot{i}.png"
        f.write_bytes(f"{title}-{i}".encode())
        blocks.append({"start": i, "end": i + 1, "asset": {"kind": "image", "src": str(f)}})
    voice = d / "voice.wav"
    voice.write_bytes(b"RIFF" + title.encode())
    plan = {"title": title, "blocks": blocks, "audio": {"src": str(voice)},
            "duration": {"composition": seconds, "actual": seconds}}
    path = d / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def _owned_jobs(pid):
    return [d for d in rv.JOBS.iterdir() if rv.job_owner(d) == pid] if rv.JOBS.is_dir() else []


def test_two_job_dirs_are_distinct_and_independent():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        jobs = tmp / "jobs"
        # the same file name in both: before CF-0340 the second staging
        # overwrote the first one's `job/00_shot.png`
        (tmp / "a").mkdir()
        (tmp / "b").mkdir()
        shot_a, shot_b = tmp / "a" / "shot.png", tmp / "b" / "shot.png"
        shot_a.write_bytes(b"a")
        shot_b.write_bytes(b"b")
        a = rv.new_job("same-slug", jobs=jobs)
        b = rv.new_job("same-slug", jobs=jobs)
        assert a != b and a.parent == b.parent == jobs, (a, b)
        assert rv.job_owner(a) == rv.job_owner(b) == os.getpid()
        rel_a = rv.stage(shot_a, {}, a)
        rel_b = rv.stage(shot_b, {}, b)
        # the composition's path shape is unchanged: staticFile(`job/...`)
        assert rel_a.startswith("job/") and rel_a == rel_b, (rel_a, rel_b)
        (a / "props.json").write_text(json.dumps({"plan": {"title": "A"}}))
        (b / "props.json").write_text(json.dumps({"plan": {"title": "B"}}))
        import shutil
        shutil.rmtree(a)
        assert (rv.job_public(b) / rel_b).read_bytes() == b"b"
        assert json.loads((b / "props.json").read_text())["plan"]["title"] == "B"
        assert (rv.job_public(b) / "fonts").is_dir()


def test_two_renders_at_once_do_not_touch_each_other():
    """The regression itself: two render_video.py processes side by side.
    Before CF-0340 the second one's rmtree removed the first one's staged
    files while its Remotion was reading them (the stub's `asset 404`), and
    its props.json replaced the first one's."""
    with tempfile.TemporaryDirectory() as tmp:
        env = _stub_env(tmp)
        runs = []
        for title, n, secs in (("alpha", 3, 31.0), ("bravo", 5, 44.0)):
            plan = _plan(Path(tmp) / title, title, n, secs)
            out = Path(tmp) / f"{title}.mp4"
            proc = subprocess.Popen([PY, str(SCRIPTS / "render_video.py"), str(plan), str(out),
                                     "--bare-voice", "--verbose"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env)
            runs.append((title, n, secs, out, proc))
            time.sleep(0.4)   # the second starts while the first is inside Remotion
        seen = {}
        for title, n, secs, out, proc in runs:
            text, _ = proc.communicate(timeout=120)
            assert proc.returncode == 0, f"{title}: rc={proc.returncode}\n{text}"
            rec = json.loads(Path(str(out) + ".seen.json").read_text())
            assert rec["title"] == title and rec["blocks"] == n, rec
            assert rec["durationInFrames"] == secs * 30, rec
            seen[title] = rec
            # its own job directory, and it is gone after the render
            assert not Path(rec["public"]).exists(), rec
            assert rv.job_owner(Path(rec["public"]).parent) == proc.pid, rec
        assert seen["alpha"]["public"] != seen["bravo"]["public"]
        assert seen["alpha"]["props"] != seen["bravo"]["props"]


def test_a_failed_render_removes_its_own_dir_only():
    """A failed render cleans up after itself, and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        env = _stub_env(tmp)
        (Path(tmp) / "bin" / "npx").write_text(f"#!{PY}\nimport sys; print('boom'); sys.exit(2)\n")
        other = rv.new_job("bystander")
        try:
            plan = _plan(Path(tmp) / "p", "failing", 1, 30.0)
            r = subprocess.run([PY, str(SCRIPTS / "render_video.py"), str(plan),
                                str(Path(tmp) / "out.mp4"), "--bare-voice", "--verbose"],
                               capture_output=True, text=True, env=env, timeout=120)
            assert r.returncode != 0, r.stdout + r.stderr
            assert other.is_dir() and (rv.job_public(other) / "job").is_dir()
            assert not [d for d in rv.JOBS.iterdir() if d.name.startswith("p-")], \
                list(rv.JOBS.iterdir())
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)


def _dead_pid():
    """A pid that is not running: a child that has exited and been reaped."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_the_sweep_removes_only_stale_dirs_of_dead_owners():
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        dead = _dead_pid()
        day = rv.JOB_STALE_SECONDS
        stale = jobs / f"old-{dead}-0000aaaa"
        fresh = jobs / f"fresh-{dead}-0000bbbb"
        alive_old = jobs / f"running-{os.getpid()}-0000cccc"
        for d in (stale, fresh, alive_old):
            (d / "public" / "job").mkdir(parents=True)
            (d / "props.json").write_text("{}")
        old = time.time() - day - 3600
        for d in (stale, alive_old):
            os.utime(d, (old, old))
        removed = rv.sweep_stale_jobs(jobs)
        assert removed == [stale], removed
        assert not stale.exists()
        assert fresh.is_dir() and (fresh / "props.json").exists()
        assert alive_old.is_dir()
        # new_job() sweeps on its way in, and leaves a fresh stranger alone
        mine = rv.new_job("next", jobs=jobs)
        assert fresh.is_dir() and alive_old.is_dir() and mine.is_dir()


def test_the_job_public_dir_carries_everything_render_public_tracks():
    """SHARED_PUBLIC is named, not globbed (a directory another tool is
    filling in render/public must never be copied half-done); so a file
    tracked there and missing from the list would silently not reach the
    render. Every tracked top-level entry is on the list."""
    r = subprocess.run(["git", "ls-files", "render/public"], cwd=AGENT_ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    tops = {Path(line).relative_to("render/public").parts[0]
            for line in r.stdout.splitlines() if line.strip()}
    assert tops, "render/public tracks nothing?"
    assert tops <= set(rv.SHARED_PUBLIC), (tops, rv.SHARED_PUBLIC)
    with tempfile.TemporaryDirectory() as tmp:
        job = rv.new_job("fonts", jobs=Path(tmp))
        fonts = sorted(p.name for p in (rv.job_public(job) / "fonts").iterdir())
        assert fonts == sorted(p.name for p in (rv.PUBLIC / "fonts").iterdir()), fonts


def test_render_video_never_writes_the_shared_public_dir():
    src = (SCRIPTS / "render_video.py").read_text()
    assert "rmtree(JOB)" not in src and 'JOB / "props.json"' not in src
    assert '"--public-dir=' in src or "f\"--public-dir=" in src, "Remotion is not given the job's public dir"


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
