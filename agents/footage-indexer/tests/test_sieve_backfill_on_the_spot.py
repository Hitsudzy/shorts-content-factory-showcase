#!/usr/bin/env python3
"""CF-0359: a batch that takes an old source again marks it on the spot.

CF-0355 gave `source_sieve.py` an exit code over a source with no answer on
`burned_text`/`on_topic`, and the stage does not close until there is one. The
old pool is not going to be marked wholesale - 2708 shots in 82 sources of
dead topics, deleted after publication anyway (CF-0358, the user's ruling of
2026-09-23) - so the marking happens inside the sieve run, over this batch's
own sources and nothing else, and a source it could not answer for is refused
with a record instead of stopping the run (DoD 1 of milestone 1.4.5: an
operation without a sign of life is taken out, the run goes on).

Pinned here, on `main()` over a real batch directory:

  - a batch holding an old unmarked source is answered, judged and exits 0;
  - the pool outside the batch keeps its unanswered shots;
  - an answerer that fails costs the batch that source - out of
    `sources_by_topic`, into `failed[]` with a code and a sentence - and the
    stage still closes with 0;
  - a backfill step that cannot start at all is the same: recorded, refused,
    exit 0;
  - `--no-backfill` leaves CF-0355's exit code exactly as it was, the
    insurance behind all of this.

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

import backfill_sieve_flags as bf   # noqa: E402
import ingest_batch as ib           # noqa: E402
import shot_schema                  # noqa: E402
import source_sieve as sv           # noqa: E402


def index(n, flagged=True, source=None):
    shots = []
    for i in range(n):
        s = {"index": i, "start": float(i), "end": float(i) + 1.0,
             "tile_at": float(i) + 0.5,
             "description": "two people on a deck by a lake"}
        if flagged:
            s[shot_schema.BURNED_TEXT] = False
            s[shot_schema.ON_TOPIC] = True
        shots.append(s)
    return {"source": source or "/tmp/x.mp4", "shots": shots}


def all_false(q, path):
    """Stands in for the frame subagent: every open shot answered `false`."""
    Path(path).write_text(json.dumps({"video_id": q["video_id"], "answers": [
        {"index": s["index"], "burned_text": False, "on_topic": True}
        for s in q["shots"]]}))


def fake_sheet(footage):
    """`backfill_sieve_flags.sheet` without ffmpeg or an mp4."""
    def build(vid, out_dir, _f=None, _p=None, open_test=None):
        _, data = bf.load_index(vid, footage)
        q = bf.questions(vid, data, [], open_test=open_test or bf.sieve_open)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / f"{vid}{bf.QUESTIONS_SUFFIX}").write_text(json.dumps(q))
        q["sheet"] = None
        return q
    return build


@contextlib.contextmanager
def pool(indexes, extra=None, answer=all_false, sheet=None, batch_of=None):
    """A batch directory over a real footage directory.

    `indexes` are the sources of the batch, `extra` sources of the pool the
    batch did not take. Yields (batch dir, footage dir, run(argv) -> (code,
    output, report)).
    """
    with tempfile.TemporaryDirectory() as tmp:
        footage = Path(tmp) / "footage"
        footage.mkdir()
        for vid, data in {**indexes, **(extra or {})}.items():
            (footage / f"{vid}.shots.json").write_text(json.dumps(data))
        pipeline = Path(tmp) / "pipeline"
        batch = pipeline / "nochannel" / "2026-09-23T0000Z"
        batch.mkdir(parents=True)
        taken = list(batch_of or indexes)
        (batch / sv.REPORT_FILE).write_text(json.dumps({
            "batch": str(batch),
            "fetched": [{"video_id": v, "topic_id": "001"} for v in taken],
            "sources_by_topic": {"001": taken},
            "failed": [], "skipped_topics": []}))
        real = (ib.CACHE, bf.PIPELINE, bf.sheet, bf.answer_cmd_setting)
        ib.CACHE = footage
        bf.PIPELINE = pipeline
        bf.sheet = sheet or fake_sheet(footage)
        # no answerer command may leak in from the environment
        bf.answer_cmd_setting = lambda cmd=None: cmd

        def run(argv=None):
            out = io.StringIO()
            real_batch = bf.backfill_batch
            if answer is not None:
                bf.backfill_batch = (
                    lambda report, out_dir, **kw: real_batch(
                        report, out_dir, **{**kw, "answer": answer}))
            try:
                with contextlib.redirect_stdout(out):
                    code = sv.main([str(batch), "--no-top-up", "--no-reserve"]
                                   + list(argv or []))
            finally:
                bf.backfill_batch = real_batch
            report = json.loads((batch / sv.REPORT_FILE).read_text())
            return code, out.getvalue(), report

        try:
            yield batch, footage, run
        finally:
            ib.CACHE, bf.PIPELINE, bf.sheet, bf.answer_cmd_setting = real


def test_an_old_unmarked_source_is_marked_and_the_stage_closes():
    with pool({"new": index(5), "old": index(4, flagged=False)}) as (b, f, run):
        code, out, report = run()
        assert code == 0, (code, out)
        block = report["source_sieve"]
        assert block["unsieved"] == [] and block["refused"] == []
        # it is still in the batch: answered, judged, kept
        assert report["sources_by_topic"]["001"] == ["new", "old"]
        assert report[sv.BACKFILL_KEY]["answered"] == ["old"]
        assert report[sv.BACKFILL_KEY]["failed"] == []
        data = json.loads((f / "old.shots.json").read_text())
        assert all(isinstance(s["burned_text"], bool) and
                   isinstance(s["on_topic"], bool) for s in data["shots"])
        assert all(s[bf.PROVENANCE] == bf.SOURCE_TAG for s in data["shots"])
        # and the sheets/questions/answers it was judged on are still readable
        assert (b / sv.BACKFILL_DIR / "old.answers.json").exists()


def test_only_the_sources_of_the_batch_are_marked():
    """The user's ruling of 2026-09-23: the old pool is not marked wholesale.
    A source sitting in `shared/footage` that this batch did not take keeps
    its unanswered shots, however cheap it would have been to answer it."""
    with pool({"new": index(3), "old": index(4, flagged=False)},
              extra={"dead": index(6, flagged=False)}) as (b, f, run):
        before = (f / "dead.shots.json").read_text()
        code, out, report = run()
        assert code == 0, (code, out)
        # the batch's own unmarked source was answered, the pool's was not
        assert report[sv.BACKFILL_KEY]["answered"] == ["old"]
        assert [r["video_id"] for r in report[sv.BACKFILL_KEY]["sources"]] \
            == ["old"]
        assert (f / "dead.shots.json").read_text() == before
        assert not (b / sv.BACKFILL_DIR / "dead.questions.json").exists()


def test_the_flags_the_batch_answers_are_judged_like_any_others():
    """The backfill is not an amnesty: a source whose answers say the frames
    are somebody else's work is refused for `source_foreign` on the spot, by
    the same arithmetic as a freshly described one."""
    def off_topic(q, path):
        Path(path).write_text(json.dumps({"video_id": q["video_id"], "answers": [
            {"index": s["index"], "burned_text": False, "on_topic": False}
            for s in q["shots"]]}))

    with pool({"new": index(3), "old": index(4, flagged=False)},
              answer=off_topic) as (b, f, run):
        code, out, report = run()
        assert code == 0, (code, out)
        assert report["source_sieve"]["refused"] == ["old"]
        rec, = [s for s in report["source_sieve"]["sources"]
                if s["video_id"] == "old"]
        assert rec["reason_code"] == ib.SIEVE_FOREIGN_CODE
        assert report["sources_by_topic"]["001"] == ["new"]


def failure_record(report, vid):
    recs = [f for f in report["failed"] if f["video_id"] == vid]
    assert len(recs) == 1, report["failed"]
    return recs[0]


def test_an_answerer_that_fails_costs_the_source_and_not_the_run():
    def boom(q, path):
        raise TimeoutError("the answerer sat for 240 s and wrote nothing")

    with pool({"new": index(3), "old": index(4, flagged=False)},
              answer=boom) as (b, f, run):
        code, out, report = run()
        # the whole point of the task: the stage closes
        assert code == 0, (code, out)
        assert report["source_sieve"]["unsieved"] == []
        assert report["source_sieve"]["refused"] == ["old"]
        assert report["sources_by_topic"]["001"] == ["new"]
        assert report[sv.BACKFILL_KEY]["failed"] == ["old"]
        rec = failure_record(report, "old")
        assert rec["reason_code"] == sv.UNANSWERED_CODE
        assert rec["refused_at"] == ib.RUNG_SIEVE
        # the sentence reads on its own - the funnel copies it into `detail`
        assert "CF-0359" in rec["error"] and "240 s" in rec["error"]
        assert "the run goes on" in rec["error"]
        assert "old" in out and "taken out of the batch" in out
        # nothing was invented on the shots it could not answer
        data = json.loads((f / "old.shots.json").read_text())
        assert all("burned_text" not in s for s in data["shots"])


def test_a_backfill_that_cannot_start_at_all_is_the_same_answer():
    with pool({"new": index(3), "old": index(4, flagged=False)}) as (b, f, run):
        real = bf.backfill_batch

        def explode(*a, **kw):
            raise OSError("no space left on device")

        bf.backfill_batch = explode
        try:
            code, out, report = run()
        finally:
            bf.backfill_batch = real
        assert code == 0, (code, out)
        block = report[sv.BACKFILL_KEY]
        assert block["ran"] is False and "no space left" in block["error"]
        assert report["source_sieve"]["unsieved"] == []
        rec = failure_record(report, "old")
        assert rec["reason_code"] == sv.UNANSWERED_CODE
        assert "no space left" in rec["error"]


def test_a_source_whose_mp4_is_gone_is_refused_and_the_run_goes_on():
    """CF-0358 deletes the sources after publication, so a sheet cannot always
    be built. That is a failure of the marking, not of the run."""
    def no_frames(vid, out_dir, *a, **kw):
        raise FileNotFoundError(f"{vid}.mp4")

    with pool({"new": index(3), "old": index(4, flagged=False)},
              sheet=no_frames) as (b, f, run):
        code, out, report = run()
        assert code == 0, (code, out)
        rec = failure_record(report, "old")
        assert rec["reason_code"] == sv.UNANSWERED_CODE
        assert "old.mp4" in rec["error"]


def test_no_backfill_leaves_the_cf0355_exit_code_as_the_insurance():
    with pool({"new": index(3), "old": index(4, flagged=False)}) as (b, f, run):
        code, out, report = run(["--no-backfill"])
        assert code == sv.UNSIEVED_EXIT, (code, out)
        assert report["source_sieve"]["unsieved"] == ["old"]
        assert report["source_sieve"]["refused"] == []
        assert sv.BACKFILL_KEY not in report
        assert report["sources_by_topic"]["001"] == ["new", "old"]
        # and the shots are untouched: nothing marked, nothing refused
        data = json.loads((f / "old.shots.json").read_text())
        assert all("burned_text" not in s for s in data["shots"])


def test_a_dry_run_marks_nothing_and_says_what_it_would_mark():
    with pool({"new": index(3), "old": index(4, flagged=False)}) as (b, f, run):
        before = (f / "old.shots.json").read_text()
        code, out, report = run(["--dry-run"])
        assert code == 0, (code, out)
        assert "would answer 1 source(s)" in out
        assert (f / "old.shots.json").read_text() == before
        assert sv.BACKFILL_KEY not in report


def test_the_answer_cmd_the_sieve_is_given_is_the_answerer():
    """The whole wiring with no stub in the middle: `--answer-cmd` reaches the
    step, the command answers one source's questions file, and the sieve judges
    what it wrote. This is the shape the frame subagent is dispatched in."""
    with pool({"new": index(3), "old": index(4, flagged=False)},
              answer=None) as (batch, f, run):
        helper = batch / "answerer.py"
        helper.write_text(
            "import json, sys\n"
            "q = json.load(open(sys.argv[1]))\n"
            "json.dump({'video_id': q['video_id'], 'answers': ["
            "{'index': s['index'], 'burned_text': False, 'on_topic': True}"
            " for s in q['shots']]}, open(sys.argv[2], 'w'))\n")
        code, out, report = run(
            ["--answer-cmd", f"{sys.executable} {helper} {{questions}} {{answers}}"])
        assert code == 0, (code, out)
        assert report[sv.BACKFILL_KEY]["answered"] == ["old"]
        assert report["source_sieve"]["unsieved"] == []
        assert report["sources_by_topic"]["001"] == ["new", "old"]


def test_an_answered_batch_pays_for_no_backfill_at_all():
    with pool({"new": index(3), "b": index(2)}) as (batch, f, run):
        code, out, report = run()
        assert code == 0, (code, out)
        assert report[sv.BACKFILL_KEY]["sources"] == []
        assert report[sv.BACKFILL_KEY]["answered"] == []
        # "nobody had to be asked" is not "nobody asked": the block is written
        assert report[sv.BACKFILL_KEY]["ran"] is True


def test_the_skill_says_the_stage_marks_a_reused_source_and_goes_on():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer" /
             "SKILL.md").read_text()
    assert "backfill_sieve_flags.py queue | sheet" in skill
    assert "batch <batch-dir>" in skill and "--answer-cmd" in skill
    # the two things an operator must not guess: what happens by default, and
    # what the exit code means now
    assert "A reused old source does not stop the stage (CF-0359" in skill
    assert "--no-backfill" in skill
    assert "insurance behind the backfill" in skill


def test_the_docstrings_name_the_task_and_the_ruling():
    """The two rules this mechanism must not drift from are written where the
    next reader of the code will be: only the batch's own sources, and a
    failure that costs a source and not the run."""
    src = (HERE.parent / "scripts" / "source_sieve.py").read_text()
    assert "CF-0359" in src and "DoD 1" in src
    assert "2026-09-23" in src
    bfsrc = (HERE.parent / "scripts" / "backfill_sieve_flags.py").read_text()
    assert "CF-0359" in bfsrc and "never a guess" in bfsrc


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
