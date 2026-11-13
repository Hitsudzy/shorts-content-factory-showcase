#!/usr/bin/env python3
"""CF-0239: the stage speaks while it walks, not only after the walk.

On `example-film/2026-09-15T1034Z` `ingest_batch.py` ran for an hour with its
log at 0 bytes: the only lines it printed came after the loop over topics,
and a run killed on its fourth source had to be read back from
RUN_EVENTS.jsonl by hand. Now every source's attempt prints `SOURCE start`
when its download begins and `SOURCE done` when it is over (topic, rung,
outcome, size, seconds), flushed at once; the existing per-source runlog pair
carries the topic and the size in its params - no second event.

Offline and in seconds: injected fetch / index / fingerprint, temp files.
"""
import contextlib
import io
import json
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0239-")
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _runlog import runlog  # noqa: E402
import ingest_batch as ib  # noqa: E402

STAGE = "footage-indexer"


def no_measure(vid, record=None):
    return ib.Measured(None, "metadata", "not measured in this test")


def media(d, vid, size=2_500_000):
    p = Path(d) / f"{vid}.mp4"
    p.write_bytes(b"\0" * size)
    return p


def walk(d, ids, fail=(), batch=None):
    """ingest() over one topic with the given ids; returns (lines, result)."""
    lines = []
    files = {v: media(d, v) for v in ids if v not in fail}

    def fetch(vid, note):
        if vid in fail:
            raise RuntimeError(f"yt-dlp failed for {vid}")
        return str(files[vid])

    def index(path):
        Path(path).with_suffix(".shots.json").write_text("{}")

    fps = {v: {"kind": "k", "hashes": [str(i)] * 8, "luma": [i] * 8, "fps": 2}
           for i, v in enumerate(ids)}
    topics = [{"topic_id": "007", "evidence": {"youtube_video_ids": list(ids)}}]
    env = {} if batch is None else {"RUNLOG_BATCH": str(batch)}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            res = ib.ingest(topics, {}, "b", 5, True, fetch=fetch, index=index,
                            fingerprint=lambda p: fps[Path(p).stem],
                            log=lambda m, file=None: lines.append(m),
                            sleep=lambda s: None, pause=0,
                            measure=no_measure, wanted=99)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return lines, res


def test_a_start_and_a_done_line_per_source():
    d = tempfile.mkdtemp(dir=TMP)
    lines, (fetched, _a, _s, failed, _b) = walk(d, ["aaa", "bbb"], fail=("bbb",))
    mine = [l for l in lines if l.startswith("SOURCE ")]
    assert mine[0] == "SOURCE start aaa topic 007 rung first_pass" or \
        mine[0].startswith("SOURCE start aaa topic 007 rung "), mine
    assert mine[1].startswith("SOURCE done aaa topic 007 rung "), mine
    assert mine[1].endswith(": source, 2.5 MB, 0 s"), mine[1]
    assert mine[2].startswith("SOURCE start bbb topic 007"), mine
    assert mine[3].startswith("SOURCE done bbb topic 007") and ": fetch_failed, size ?," in mine[3], mine
    # the start comes before anything else the attempt prints, the done after
    assert lines.index(mine[0]) < lines.index(mine[1]) < lines.index(mine[2])
    assert [f["video_id"] for f in fetched] == ["aaa"]


def test_the_outcome_words():
    line = ib.source_done_line("x", "t", "r", "alias of y", 12.34, 61.6, cached=True)
    assert line == "SOURCE done x topic t rung r: alias of y, 12.34 MB (cache), 62 s", line
    assert ib.file_mb("/no/such/file") is None


def test_the_runlog_pair_carries_topic_and_size_and_nothing_new():
    d = tempfile.mkdtemp(dir=TMP)
    batch = Path(tempfile.mkdtemp(dir=TMP))
    (batch / "RUN_EVENTS.jsonl").write_text("")
    with contextlib.redirect_stdout(io.StringIO()):
        walk(d, ["aaa"], batch=batch)
    evs = [json.loads(l) for l in (batch / "RUN_EVENTS.jsonl").read_text().splitlines() if l.strip()]
    ingest = [e for e in evs if e.get("kind") == "script" and e.get("step") == "ingest"]
    assert [(e["video"], e["status"]) for e in ingest] == [("aaa", "start"), ("aaa", "done")], evs
    assert ingest[0]["params"] == {"topic": "007"}, ingest[0]
    assert ingest[1]["params"]["topic"] == "007" and ingest[1]["params"]["size_mb"] == 2.5, ingest[1]
    assert not [e for e in evs if e.get("kind") == "marker"], evs


CHILD = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import ingest_batch as ib
from _temp_pool import fence_cache_index  # CF-0683: the child's own fetch_footage.INDEX
d, go = Path(sys.argv[3]), Path(sys.argv[4])
fence_cache_index(d / "ff-pool")
ib.line_buffered()
for v in ("aaa", "bbb"):
    (d / f"{v}.mp4").write_bytes(b"\0" * 1000)

def fetch(vid, note):
    if vid == "bbb":
        t = time.time()
        while not go.exists() and time.time() - t < 20:
            time.sleep(0.05)
    return str(d / f"{vid}.mp4")

ib.ingest([{"topic_id": "007", "evidence": {"youtube_video_ids": ["aaa", "bbb"]}}],
          {}, "b", 5, True, fetch=fetch, index=lambda p: None,
          fingerprint=lambda p: None,
          sleep=lambda s: None, pause=0,
          measure=lambda vid, record=None: ib.Measured(None, "metadata", "x"),
          wanted=99)
print("WALK OVER")
"""


def test_the_line_reaches_a_pipe_while_the_walk_is_still_on():
    """stdout is a pipe: the first source's done line must arrive while the
    second source's download is still blocked - not when the process ends."""
    d = Path(tempfile.mkdtemp(dir=TMP))
    go = d / "go"
    env = dict(os.environ)
    env.pop("RUNLOG_BATCH", None)
    env.pop("PYTHONUNBUFFERED", None)
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(SCRIPTS), str(HERE),
                             str(d), str(go)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    seen, buf, t = [], b"", time.time()
    try:
        while time.time() - t < 20:
            r, _, _ = select.select([proc.stdout], [], [], 0.5)
            if r:
                chunk = os.read(proc.stdout.fileno(), 4096)
                if not chunk:
                    break
                buf += chunk
                seen = buf.decode().splitlines()
                if any(l.startswith("SOURCE start bbb") for l in seen):
                    break
        assert proc.poll() is None, "the child finished before it was let go"
        assert any(l.startswith("SOURCE done aaa topic 007") for l in seen), seen
        assert not any(l == "WALL OVER" or l == "WALK OVER" for l in seen), seen
    finally:
        go.write_text("")
        out = proc.communicate(timeout=30)[0].decode()
    assert proc.returncode == 0, out
    assert "SOURCE done bbb" in buf.decode() + out


def test_line_buffered_survives_a_stream_without_reconfigure():
    ib.line_buffered(io.StringIO())     # no AttributeError out of it


if __name__ == "__main__":
    failures = ran = 0
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
        except Exception as exc:
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
