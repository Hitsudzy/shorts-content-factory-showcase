"""CF-0905: a stop of render_video.py takes its children with it.

example-tech/2026-10-31T0840Z, doordash: the operator stopped its own
background render loop with `pkill -f ve_run.sh; pkill -f render_video.py`
(to fix an argument order in the loop). SIGTERM's default action killed
render_video.py on the spot - RUN_LOG says `started ... (no end recorded)`,
the attempt stayed open until the next render closed it `abandoned` - while
build_soundtrack.py, the render's child, went on as an orphan: it finished
mix.wav, wrote audio.bed onto the plan under the render the operator had just
restarted, and died on its last print into the pipe nobody read any more
(`BrokenPipeError`). Remotion would have been left the same way, node and
Chrome rendering into the mp4.

Now a SIGTERM/SIGHUP/SIGINT kills the live children with their process
groups, ends the attempt `abandoned` naming the stop, and exits 128+signal
through the runlog (`failed`, `SystemExit: 143`). The BrokenPipe in
build_soundtrack.py is not silenced: an orphan must not go on writing.

Both stands run render_video.py for real against a fake batch in a temp
dir; build_soundtrack.py is a stand-in (put in place by a driver), Remotion a
stub `npx` on PATH. On the code before CF-0905 the children outlive the stop.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

from repo_paths import VENV_PY  # noqa: E402
import test_attempt_cap as tac  # noqa: E402

RENDER_JOBS = AGENT_ROOT / "render" / "jobs"


def _alive(pid):
    """Running (not gone, not a zombie waiting for its reaper)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                          capture_output=True, text=True).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _wait_file(path, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists() and path.read_text().strip():
            return int(path.read_text().split()[0])
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _gone_within(pid, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _cleanup(*pids):
    for pid in pids:
        if pid and _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _stop(proc):
    proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return proc.returncode, out


def _attempt(work):
    ledger = json.loads((work / "attempts.json").read_text())
    return ledger["attempts"][-1]


def _render_events(batch):
    path = Path(batch) / "RUN_EVENTS.jsonl"
    if not path.exists():
        return []
    events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return [e for e in events if e.get("name") == "render_video.py"]


FAKE_SOUNDTRACK = textwrap.dedent('''\
    import os, sys, time
    from pathlib import Path
    out = Path(sys.argv[3])
    Path(os.environ["CF0905_CHILD_PID"]).write_text(str(os.getpid()))
    time.sleep(4)                      # mixing - prints nothing until the end
    out.write_bytes(b"RIFF")           # the orphan's mix.wav
    print("soundtrack -> " + str(out)) # the print that met the dead pipe
''')

DRIVER = textwrap.dedent('''\
    import sys
    from pathlib import Path
    sys.path.insert(0, {scripts!r})
    import render_video
    fake = Path({fake!r})
    render_video.SOUNDTRACK_SCRIPT = fake                         # CF-0905's name
    render_video.__file__ = str(fake.parent / "render_video.py")  # the code before it
    sys.argv = ["render_video.py", {plan!r}, {out!r}]
    render_video.cli()
''')


def test_a_stop_during_the_mix_kills_build_soundtrack_and_ends_the_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        b, slug, plan_path = tac._batch(tmp, slug="cf0905-mix")
        work = plan_path.parent
        plan = json.loads(plan_path.read_text())
        plan["audio"]["channel"] = "chan"   # a channel's plan: the mix is built here
        plan_path.write_text(json.dumps(plan))
        fake_dir = tmp / "fake"
        fake_dir.mkdir()
        fake = fake_dir / "build_soundtrack.py"
        fake.write_text(FAKE_SOUNDTRACK)
        driver = tmp / "driver.py"
        out = b / "videos" / f"{slug}.mp4"
        driver.write_text(DRIVER.format(scripts=str(SCRIPTS), fake=str(fake),
                                        plan=str(plan_path), out=str(out)))
        pid_file = tmp / "child.pid"
        env = dict(os.environ, CF0905_CHILD_PID=str(pid_file), RUNLOG_BATCH=str(b))
        proc = subprocess.Popen([VENV_PY, str(driver)], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        child = None
        try:
            child = _wait_file(pid_file)
            time.sleep(0.3)
            rc, said = _stop(proc)
            assert _gone_within(child), (
                f"build_soundtrack.py (pid {child}) outlived the stop of render_video.py "
                f"- the orphan of example-tech/2026-10-31T0840Z; render said: {said}")
            assert rc == 128 + signal.SIGTERM, (rc, said)
            attempt = _attempt(work)
            assert attempt["ended_at"], attempt
            assert attempt["result"] == "abandoned", attempt
            assert "SIGTERM" in (attempt.get("detail") or ""), attempt
            time.sleep(4.2)
            assert not (work / "mix.wav").exists(), "the killed mix still wrote mix.wav"
            ends = [e for e in _render_events(b) if e.get("status") in ("done", "failed")]
            assert ends and ends[-1]["status"] == "failed", ends
            assert "SystemExit: 143" in (ends[-1].get("error") or ""), ends[-1]
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            _cleanup(child)


STOP_NPX = textwrap.dedent('''\
    #!/bin/sh
    sleep 30 &
    echo $! > "$CF0905_GRANDCHILD_PID"
    echo $$ > "$CF0905_CHILD_PID"
    echo 'Bundling 100%'
    echo 'Rendered 1/1630, time remaining: 4m 10s'
    wait
''')


def test_a_stop_during_remotion_kills_its_whole_group_and_ends_the_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        b, slug, plan_path = tac._batch(tmp, slug="cf0905-render")
        work = plan_path.parent
        env = tac._stub_npx(tmp, STOP_NPX)
        child_file, grand_file = tmp / "npx.pid", tmp / "sleep.pid"
        env.update(CF0905_CHILD_PID=str(child_file), CF0905_GRANDCHILD_PID=str(grand_file),
                   RUNLOG_BATCH=str(b))
        out = b / "videos" / f"{slug}.mp4"
        proc = subprocess.Popen([VENV_PY, str(SCRIPTS / "render_video.py"), str(plan_path),
                                 str(out)], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        child = grand = None
        try:
            child = _wait_file(child_file)
            grand = _wait_file(grand_file)
            time.sleep(0.3)
            rc, said = _stop(proc)
            assert _gone_within(child), f"npx (pid {child}) outlived the stop: {said}"
            assert _gone_within(grand), (f"Remotion's grandchild (pid {grand}) outlived "
                                         f"the stop: {said}")
            assert rc == 128 + signal.SIGTERM, (rc, said)
            attempt = _attempt(work)
            assert attempt["ended_at"] and attempt["result"] == "abandoned", attempt
            assert "SIGTERM" in (attempt.get("detail") or ""), attempt
            assert not list(RENDER_JOBS.glob(f"{slug}-{proc.pid}-*")), \
                "the stopped render left its job directory behind"
            ends = [e for e in _render_events(b) if e.get("status") in ("done", "failed")]
            assert ends and "SystemExit: 143" in (ends[-1].get("error") or ""), ends
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            _cleanup(child, grand)


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
