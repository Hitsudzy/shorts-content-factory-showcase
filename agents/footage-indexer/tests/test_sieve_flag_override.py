#!/usr/bin/env python3
"""CF-0713: a sieve flag the describer answered is changed only through
`sieve_flag_override.py`, and never silently.

Pinned here, on a temp pool and a temp batch (nothing live): the flag is set
and the shot carries `flag_overrides[]` with who / what / why; the batch gets a
line in `work/sieve-flag-overrides.jsonl` and a `sieve_flag_override` event in
RUN_EVENTS.jsonl; a short reason, an unknown flag or a missing shot is refused
with nothing written; a shot already at the value is left alone; `--dry-run`
writes nothing.

No pytest dependency - plain asserts, run directly.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import sieve_flag_override as sfo   # noqa: E402

WHY = "the frames show the ESA mission's own control room, not another work"


def shot(i, **kw):
    s = {"index": i, "start": float(i), "end": float(i) + 1.0, "tile_at": i + 0.5,
         "description": f"shot {i}", "burned_text": False, "on_topic": False}
    s.update(kw)
    return s


def world(tmp):
    footage = Path(tmp) / "footage"
    footage.mkdir()
    (footage / "esa1.shots.json").write_text(json.dumps({
        "source": str(footage / "esa1.mp4"),
        "shots": [shot(0), shot(1), shot(2, on_topic=True)]}))
    batch = Path(tmp) / "pipeline" / "chan" / "2026-10-12T2001Z"
    batch.mkdir(parents=True)
    (batch / "RUN_EVENTS.jsonl").write_text("")
    return footage, batch


def index(footage):
    return json.loads((footage / "esa1.shots.json").read_text())


def test_an_override_sets_the_flag_and_records_who_what_why_everywhere():
    with tempfile.TemporaryDirectory() as tmp:
        footage, batch = world(tmp)
        rc = sfo.main([str(batch), "esa1", "--shots", "0,1,2", "--flag", "on_topic",
                       "--to", "true", "--why", WHY, "--footage", str(footage)])
        assert rc == 0
        shots = index(footage)["shots"]
        assert [s["on_topic"] for s in shots] == [True, True, True]
        h = shots[0]["flag_overrides"]
        assert len(h) == 1 and h[0]["was"] is False and h[0]["to"] is True, h
        assert h[0]["why"] == WHY and h[0]["by"] == sfo.DEFAULT_BY and h[0]["task"] == "CF-0713"
        assert "flag_overrides" not in shots[2]                # already true: untouched
        [rec] = [json.loads(l) for l in (batch / sfo.RECORD).read_text().splitlines()]
        assert rec["changed"] == [{"index": 0, "was": False}, {"index": 1, "was": False}]
        assert rec["unchanged"] == [2]
        evs = [json.loads(l) for l in (batch / "RUN_EVENTS.jsonl").read_text().splitlines()
               if l.strip()]
        [e] = [e for e in evs if e.get("kind") == sfo.EVENT_KIND]
        assert e["video"] == "esa1" and e["flag"] == "on_topic" and e["to"] is True
        assert e["shots"] == [0, 1] and e["was"] == [False, False] and e["note"] == WHY


def test_a_bad_call_is_refused_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        footage, batch = world(tmp)
        before = (footage / "esa1.shots.json").read_text()
        for argv in (["--shots", "0", "--flag", "on_topic", "--to", "true", "--why", "save it"],
                     ["--shots", "0", "--flag", "description", "--to", "true", "--why", WHY],
                     ["--shots", "7", "--flag", "on_topic", "--to", "true", "--why", WHY]):
            assert sfo.main([str(batch), "esa1", *argv, "--footage", str(footage)]) == 2, argv
        assert (footage / "esa1.shots.json").read_text() == before
        assert not (batch / sfo.RECORD).exists()
        assert (batch / "RUN_EVENTS.jsonl").read_text() == ""


def test_a_dry_run_writes_nothing_and_nothing_to_change_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        footage, batch = world(tmp)
        before = (footage / "esa1.shots.json").read_text()
        assert sfo.main([str(batch), "esa1", "--shots", "0", "--flag", "on_topic", "--to",
                         "true", "--why", WHY, "--footage", str(footage), "--dry-run"]) == 0
        assert sfo.main([str(batch), "esa1", "--shots", "2", "--flag", "on_topic", "--to",
                         "true", "--why", WHY, "--footage", str(footage)]) == 0
        assert (footage / "esa1.shots.json").read_text() == before
        assert not (batch / sfo.RECORD).exists()


def test_the_skill_forbids_a_hand_flip_and_names_the_script():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer" / "SKILL.md").read_text()
    assert "sieve_flag_override.py" in skill and "CF-0713" in skill
    assert "never flip an answered flag by hand" in skill


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
