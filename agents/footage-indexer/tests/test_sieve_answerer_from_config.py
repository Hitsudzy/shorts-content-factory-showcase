#!/usr/bin/env python3
"""CF-0374: the sieve's answerer is a setting of the run, and the run says what
it marked.

CF-0359 put the marking of a reused old source inside the sieve run and left
the answerer to `--answer-cmd` or `$SIEVE_FLAGS_ANSWER_CMD`. Neither was ever
set, so in an unattended run the step meant "apply the answers already in the
directory": every source with no answer on `burned_text`/`on_topic` was taken
out of the batch with an `index_failed` record. Legal under DoD 1 - the run
does not stop - and a lost topic every time, when marking one source is
cheaper than losing a topic.

Pinned here, on `main()` over a real batch directory:

  - the command comes from the channel's config
    (`footage_indexer.sieve_flags_answer_cmd`), with no flag and no
    environment variable in sight, and the source it marks stays in the batch;
  - `--answer-cmd` wins over the config, the config over the environment, and
    with none of the three there is no answerer - which is still not a refusal;
  - a run with no answerer takes the source out with a record and exits 0;
  - either way the run leaves a `sieve_answers` event whose `line` is the
    finished sentence `RUN_SUMMARY.md` carries, and the two states do not read
    the same.

The batch harness is CF-0359's (`test_sieve_backfill_on_the_spot.pool`) - the
same batch over the same footage directory, deliberately not a second copy of
it. `answer=None` there means no callable is injected, so the answerer really
is the command under test.

No pytest dependency - plain asserts, run directly.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import ingest_batch as ib           # noqa: E402
import source_sieve as sv           # noqa: E402
from test_sieve_backfill_on_the_spot import index, pool   # noqa: E402

EVENTS = "RUN_EVENTS.jsonl"


def answerer_script(batch):
    """A stand-in for the frame subagent: answers every open shot of one
    source's questions file. What `--answer-cmd` and the config's command are
    both expected to be."""
    helper = Path(batch) / "answerer.py"
    helper.write_text(
        "import json, sys\n"
        "q = json.load(open(sys.argv[1]))\n"
        "json.dump({'video_id': q['video_id'], 'answers': ["
        "{'index': s['index'], 'burned_text': False, 'on_topic': True}"
        " for s in q['shots']]}, open(sys.argv[2], 'w'))\n")
    return f"{sys.executable} {helper} {{questions}} {{answers}}"


def with_config(batch, value):
    """Put `footage_indexer.sieve_flags_answer_cmd` where the stage reads it,
    and point the stage's root at it. The harness's batch lives at
    `<root>/pipeline/<channel>/<batch>`, so the root is its third parent -
    the same layout the real factory has."""
    root = Path(batch).resolve().parents[2]
    channel = Path(batch).resolve().parent.name
    (root / "channels").mkdir(parents=True, exist_ok=True)
    (root / "channels" / f"{channel}.json").write_text(json.dumps(
        {"channel_id": channel,
         "footage_indexer": {"sieve_flags_answer_cmd": value}}))
    ib.FACTORY_ROOT = root
    return root


def events(batch, kind=sv.ANSWER_EVENT_KIND):
    path = Path(batch) / EVENTS
    if not path.is_file():
        return []
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return [e for e in rows if e.get("kind") == kind]


# ---------------------------------------------------------------------------
# 1. where the command comes from
# ---------------------------------------------------------------------------

def test_the_config_names_the_answerer_and_the_source_stays_in_the_batch():
    """The whole point of the task: no flag, no environment variable, and the
    old source is still marked and kept."""
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            with_config(batch, answerer_script(batch))
            code, out, report = run()
            assert code == 0, (code, out)
            block = report[sv.BACKFILL_KEY]
            assert block["answered"] == ["old"], block
            assert block["failed"] == []
            assert block["answerer_from"] == sv.ANSWER_FROM_CONFIG
            # marked, judged, kept - not taken out with a record
            assert report["source_sieve"]["unsieved"] == []
            assert report["sources_by_topic"]["001"] == ["new", "old"]
            assert report["failed"] == []
            data = json.loads((footage / "old.shots.json").read_text())
            assert all(isinstance(s["burned_text"], bool) and
                       isinstance(s["on_topic"], bool) for s in data["shots"])
    finally:
        ib.FACTORY_ROOT = real_root


def test_a_block_in_the_config_may_carry_the_command_and_its_ceiling():
    """`{"command": ..., "timeout_seconds": N}` - the shape
    `max_source_duration_seconds` already uses, so the ceiling on one source's
    answerer is configured beside the command."""
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            root = with_config(batch, {"command": answerer_script(batch),
                                       "timeout_seconds": 90,
                                       "note": "CF-0374"})
            channel = Path(batch).resolve().parent.name
            said = sv.answerer(channel=channel, root=root)
            assert said["timeout"] == 90
            assert said["from"] == sv.ANSWER_FROM_CONFIG
            code, out, report = run()
            assert code == 0, (code, out)
            assert report[sv.BACKFILL_KEY]["answered"] == ["old"]
    finally:
        ib.FACTORY_ROOT = real_root


def test_the_flag_beats_the_config_and_the_config_beats_the_environment():
    cfg = {"footage_indexer": {"sieve_flags_answer_cmd": "cfg {answers}"}}
    env = {sv.backfill.ANSWER_CMD_ENV: "env {answers}"}
    def said(**kw):
        return sv.answerer(env=env, **kw)

    # the config, read from a real file, is what a run of that channel gets
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "c.json"
        p.write_text(json.dumps(cfg))
        got = said(channel="nochannel", config_path=p)
        assert got["command"] == "cfg {answers}"
        assert got["from"] == sv.ANSWER_FROM_CONFIG
        got = said(channel="nochannel", config_path=p, flag="flag {answers}")
        assert got["command"] == "flag {answers}"
        assert got["from"] == sv.ANSWER_FROM_FLAG
    # with no config the environment is still read - the pilot's sessions
    got = said(channel="nochannel", config_path=Path(tmp) / "gone.json")
    assert got["command"] == "env {answers}"
    assert got["from"] == sv.ANSWER_FROM_ENV
    # and with nothing at all there is no answerer, which is a word, not a crash
    got = sv.answerer(channel="nochannel", config_path=Path(tmp) / "gone.json",
                      env={})
    assert got["command"] is None and got["from"] == sv.ANSWER_FROM_NOWHERE


def test_a_typo_in_the_config_is_neither_a_command_nor_a_refusal():
    for value in (17, [], {"commnad": "x"}, "   ", {"command": None},
                  {"command": "x", "timeout_seconds": "soon"}):
        cmd, timeout = sv.answer_cmd_from_config(
            {"footage_indexer": {"sieve_flags_answer_cmd": value}})
        if isinstance(value, dict) and value.get("command") == "x":
            assert cmd == "x" and timeout is None, value
        else:
            assert cmd is None, value
            assert timeout is None, value


# ---------------------------------------------------------------------------
# 2. no answerer is still a legal run (DoD 1)
# ---------------------------------------------------------------------------

def test_with_no_answerer_the_source_is_taken_out_with_a_record_and_exit_0():
    """The behaviour CF-0359 left behind, pinned as legal: nothing marked, the
    source refused with the existing `index_failed` code, the run goes on."""
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            # a root with a config that says nothing about an answerer
            with_config(batch, None)
            code, out, report = run()
            assert code == 0, (code, out)
            block = report[sv.BACKFILL_KEY]
            assert block["answered"] == [] and block["failed"] == ["old"]
            assert block["answerer_from"] == sv.ANSWER_FROM_NOWHERE
            assert report["sources_by_topic"]["001"] == ["new"]
            rec = [f for f in report["failed"] if f.get("video_id") == "old"]
            assert rec and rec[0]["reason_code"] == sv.UNANSWERED_CODE, rec
    finally:
        ib.FACTORY_ROOT = real_root


# ---------------------------------------------------------------------------
# 3. the run summary can tell the two apart
# ---------------------------------------------------------------------------

def test_the_event_carries_the_finished_line_for_the_run_summary():
    """The root builds RUN_SUMMARY.md out of RUN_EVENTS.jsonl and opens no
    stage artifact (CF-0368), so the counts travel as a finished line on an
    event of this stage's own."""
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            with_config(batch, answerer_script(batch))
            code, out, report = run()
            assert code == 0, (code, out)
            ev = events(batch)
            assert len(ev) == 1, ev
            line = ev[0]["line"]
            assert "1 of 1 source(s) marked on the spot" in line, line
            assert "0 taken out" in line, line
            assert sv.ANSWER_FROM_CONFIG in line, line
            assert ev[0]["stage"] == sv.STAGE_NAME
            body = ev[0][sv.ANSWER_EVENT_KIND]
            assert body["marked"] == 1 and body["asked"] == 1
            assert body["taken_out"] == [] and body["answerer_configured"]
            assert body["refusal_code"] == sv.UNANSWERED_CODE
            # the same line is printed where the operator can read it
            assert line in out
    finally:
        ib.FACTORY_ROOT = real_root


def test_a_run_with_no_answerer_says_so_in_the_line():
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            with_config(batch, None)
            code, out, report = run()
            assert code == 0, (code, out)
            ev = events(batch)
            assert len(ev) == 1, ev
            line = ev[0]["line"]
            assert "no answerer is configured" in line, line
            assert sv.ANSWER_CMD_KEY in line, line
            assert f"1 taken out of the batch with a record " \
                   f"({sv.UNANSWERED_CODE})" in line, line
            body = ev[0][sv.ANSWER_EVENT_KIND]
            assert body["marked"] == 0 and body["taken_out"] == ["old"]
            assert body["answerer_configured"] is False
            assert line in out
    finally:
        ib.FACTORY_ROOT = real_root


def test_a_batch_nobody_had_to_be_asked_about_does_not_read_as_a_loss():
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "b": index(2)}, answer=None) as (b, f, run):
            with_config(b, None)
            code, out, report = run()
            assert code == 0, (code, out)
            line = events(b)[0]["line"]
            assert "nothing to mark" in line, line
            assert "taken out" not in line, line
    finally:
        ib.FACTORY_ROOT = real_root


def test_no_backfill_still_exits_3_and_the_line_says_the_marking_was_off():
    """CF-0355's exit code is the insurance behind all of this and stays put -
    and the summary must not pass a stopped stage off as a clean one."""
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            with_config(batch, answerer_script(batch))
            code, out, report = run(["--no-backfill"])
            assert code == sv.UNSIEVED_EXIT, (code, out)
            line = events(batch)[0]["line"]
            assert "marking was off (--no-backfill)" in line, line
            assert "1 source(s) went into the sieve unanswered" in line, line
    finally:
        ib.FACTORY_ROOT = real_root


def test_a_dry_run_writes_no_event():
    real_root = ib.FACTORY_ROOT
    try:
        with pool({"new": index(3), "old": index(4, flagged=False)},
                  answer=None) as (batch, footage, run):
            with_config(batch, answerer_script(batch))
            code, out, report = run(["--dry-run"])
            assert code == 0, (code, out)
            assert events(batch) == []
    finally:
        ib.FACTORY_ROOT = real_root


def test_the_skill_and_the_docstrings_name_the_setting():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer" /
             "SKILL.md").read_text()
    assert sv.ANSWER_CMD_KEY in skill
    assert "CF-0374" in skill
    src = (HERE.parent / "scripts" / "source_sieve.py").read_text()
    assert "CF-0374" in src and sv.ANSWER_CMD_KEY in src
    # the two things the next reader must not have to guess
    assert "setting of the run" in src
    assert "RUN_SUMMARY" in src


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
