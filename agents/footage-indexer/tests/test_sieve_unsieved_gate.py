#!/usr/bin/env python3
"""CF-0355: the sieve does not let the stage close over an unanswered source.

Up to CF-0355 a source with no `burned_text`/`on_topic` answer was printed as
`unsieved` and `source_sieve.py` still exited 0 - so the old pool, described
before CF-0299, went through every batch that reused it with nobody asked
about burned-in text. Pinned here, on `main()` itself over a real batch
directory: an unsieved source makes the script exit `UNSIEVED_EXIT` (the
runlog records the sieve step `failed`) after writing the report, and a batch
whose every source is answered exits 0 as before.

CF-0359 put the batch's own backfill in front of the judging, so the exit code
is now the *insurance* behind it rather than the stage's normal answer to an
old source: the runs below ask for it with `--no-backfill`, which is the state
this file was written to pin, and
`tests/test_sieve_backfill_on_the_spot.py` owns what the default path does
(marks the source, or refuses it with a record and goes on).

No pytest dependency - plain asserts, run directly.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import ingest_batch as ib           # noqa: E402
import shot_schema                  # noqa: E402
import source_sieve as sv           # noqa: E402


def index(n, flagged=True):
    shots = []
    for i in range(n):
        s = {"index": i, "start": float(i), "end": float(i) + 1.0,
             "description": "two people on a deck by a lake"}
        if flagged:
            s[shot_schema.BURNED_TEXT] = False
            s[shot_schema.ON_TOPIC] = True
        shots.append(s)
    return {"source": "/tmp/x.mp4", "shots": shots}


def run(indexes):
    with tempfile.TemporaryDirectory() as tmp:
        batch = Path(tmp) / "nochannel" / "2026-09-23T0000Z"
        batch.mkdir(parents=True)
        (batch / sv.REPORT_FILE).write_text(json.dumps({
            "fetched": [{"video_id": v, "topic_id": "001"} for v in indexes],
            "sources_by_topic": {"001": list(indexes)},
            "failed": [], "skipped_topics": []}))
        real, real_cache = sv.read_index, ib.CACHE
        sv.read_index = lambda vid, cache=None: indexes.get(vid)
        # nothing here reads or writes the real pool: the indexes are the dict
        # above, and the CF-0359 backfill is off in these runs anyway
        ib.CACHE = Path(tmp) / "footage"
        ib.CACHE.mkdir()
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = sv.main([str(batch), "--no-top-up", "--no-reserve",
                                "--no-backfill"])
        finally:
            sv.read_index, ib.CACHE = real, real_cache
        report = json.loads((batch / sv.REPORT_FILE).read_text())
    return code, out.getvalue(), report


def test_an_unanswered_source_fails_the_sieve_step():
    code, out, report = run({"a": index(5), "old": index(5, flagged=False)})
    assert code == sv.UNSIEVED_EXIT, (code, out)
    assert "old" in out and "backfill_sieve_flags.py" in out
    # the report is still written: the gate is the exit code, not a lost file
    assert report["source_sieve"]["unsieved"] == ["old"]


def test_a_fully_answered_batch_exits_zero():
    code, out, report = run({"a": index(5), "b": index(4)})
    assert code == 0, (code, out)
    assert report["source_sieve"]["unsieved"] == []


def test_a_partly_answered_source_is_not_answered():
    part = index(4)
    del part["shots"][2][shot_schema.BURNED_TEXT]
    code, _, _ = run({"a": index(5), "p": part})
    assert code == sv.UNSIEVED_EXIT


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
