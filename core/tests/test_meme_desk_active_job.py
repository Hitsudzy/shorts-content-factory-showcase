#!/usr/bin/env python3
"""CF-0761: active_job() - the meme desk's machine slot read for the center's
plan (CC-0075), with no side effects.

On temp banks only (test_meme_desk_jobs.world under the runner's temp root)
and a temp slot folder ($MEME_DESK_JOBS_DIR); the real banks and the real
schedule/ are never opened:
* no slot file: None, and the slot folder is not created;
* a live stub job (a real detached `python3` child that waits): its id,
  kind, bank, channel, started_at and alive True;
* the same job killed: still reported, alive False;
* nothing is written - a snapshot of the slot, the bank and the repo is the
  same before and after - and the slot's .lock is not taken (a call made
  while somebody holds it returns at once);
* the channel: the one channel naming the bank, None for a shared one.
Every child started here is this test's own and is stopped by its own pid.
"""
import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import meme_desk as desk  # noqa: E402
from _tmproot import tmp_root  # noqa: E402
from test_meme_desk_background_jobs import (  # noqa: E402
    SLEEPER, WHO, child, env, own_pids, stub, wait_until)
from test_meme_desk_jobs import snapshot, world  # noqa: E402

TMP = tmp_root("meme-desk-active-job-")


def state(tmp):
    """Everything a call could touch: the slot folder, the banks, the repo."""
    return snapshot(tmp)


def call_without_the_slot_lock(slot, **kw):
    """active_job() while this process holds the slot's .lock: it must not wait."""
    out = {}
    with desk._flocked(Path(slot) / ".lock"):
        t = threading.Thread(target=lambda: out.setdefault("r", desk.active_job(**kw)),
                             daemon=True)
        t.start()
        t.join(10)
        assert not t.is_alive(), "active_job waited on the slot's .lock"
    return out["r"]


def test_no_slot_file_is_none_and_nothing_is_created():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        t, repo, inserts = world(tmp, escape=False)
        slot = Path(tmp) / "slot"
        environ = env(tmp, **{desk.JOBS_DIR_ENV: str(slot)})
        before = state(tmp)
        assert desk.active_job(root=inserts, repo=repo, environ=environ) is None
        assert not slot.exists()
        slot.mkdir()
        assert desk.active_job(root=inserts, repo=repo, environ=environ) is None
        # a slot file that names no job is no job either
        (slot / desk.JOBS_ACTIVE).write_text("{not json")
        assert desk.active_job(root=inserts, repo=repo, environ=environ) is None
        (slot / desk.JOBS_ACTIVE).write_text(json.dumps({"job_id": "../x"}))
        assert desk.active_job(root=inserts, repo=repo, environ=environ) is None
        (slot / desk.JOBS_ACTIVE).unlink()
        slot.rmdir()
        assert state(tmp) == before


def test_a_live_job_then_killed_is_reported_and_nothing_is_written():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp, own_pids() as pids:
        t, repo, inserts = world(tmp, escape=False)
        slot = Path(tmp) / "slot"
        environ = env(tmp, **{desk.JOBS_DIR_ENV: str(slot)})
        kw = dict(root=inserts, repo=repo, environ=environ)
        with child(stub(tmp, SLEEPER, "sleeper.py")):
            first = desk.start_job("embed", {}, bank="memes-tech", **WHO, **kw)
        pids.append(first["pid"])
        assert (slot / desk.JOBS_ACTIVE).is_file()
        wait_until(lambda: desk._lock_held(Path(first["state_file"]).with_suffix(".lock")))
        before = state(tmp)
        a = desk.active_job(**kw)
        started = desk.job_status(first["job_id"], bank="memes-tech", root=inserts,
                                  repo=repo)["started_at"]
        assert a == {"job_id": first["job_id"], "kind": "embed", "bank": "memes-tech",
                     "channel": "tech", "started_at": started, "alive": True}, a
        assert call_without_the_slot_lock(slot, **kw) == a
        assert state(tmp) == before
        # the process dies: still the slot's job, alive False - not None
        os.killpg(first["pid"], signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(first["pid"], 0)
        wait_until(lambda: not desk._lock_held(Path(first["state_file"]).with_suffix(".lock")))
        before = state(tmp)
        dead = desk.active_job(**kw)
        assert dead == {**a, "alive": False}, dead
        assert state(tmp) == before                 # the slot is not cleaned up
        assert json.loads((slot / desk.JOBS_ACTIVE).read_text())["job_id"] == first["job_id"]
        # a state file that is gone, or that says done, is not alive either
        sf = Path(first["state_file"])
        s = json.loads(sf.read_text())
        sf.write_text(json.dumps({**s, "state": "done"}))
        assert desk.active_job(**kw)["alive"] is False
        sf.unlink()
        assert desk.active_job(**kw) == dead


def test_the_channel_is_the_one_channel_naming_the_bank():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        t, repo, inserts = world(tmp, escape=False)
        chans = repo / "channels"
        assert desk._bank_channel("memes-tech", repo) == "tech"
        assert desk._bank_channel("memes", repo) is None       # no channel uses it
        (chans / "reel.json").write_text(json.dumps({"insert_layers": {"meme": {}}}))
        assert desk._bank_channel("memes", repo) == "reel"
        (chans / "science.json").write_text("{}")
        assert desk._bank_channel("memes", repo) is None       # shared by two
        (chans / "broken.json").write_text("{nope")
        (chans / "odd.json").write_text(json.dumps(
            {"insert_layers": {"meme": {"bank": "../elsewhere"}}}))
        assert desk._bank_channel("memes-tech", repo) == "tech"
        assert desk._bank_channel("memes-other", repo) is None
        assert desk._bank_channel(None, repo) is None


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
