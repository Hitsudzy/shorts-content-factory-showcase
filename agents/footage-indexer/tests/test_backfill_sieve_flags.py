#!/usr/bin/env python3
"""CF-0355/CF-0359: the backfill answers only the sieve flags nobody gave.

The pool described before CF-0299 carries neither `burned_text` nor
`on_topic`; `backfill_sieve_flags.py` puts a model's answer there without
re-indexing. Pinned here: it lists exactly the unanswered shots (cards too),
it never overwrites an answer already on a shot, it never touches the
description, it marks what it set with `sieve_flags_by: CF-0355`, it keeps the
quoted text of a `true`, and a malformed answer file writes nothing.

CF-0359 added the batch step - the same three steps over the sources one batch
took and nothing else, so a batch that reuses an old source marks it on the
spot instead of stopping the stage on the sieve's exit code. Pinned here: it
touches no source outside the batch, it never raises whatever the answerer
does, a source it could not answer comes back as a record with the sentence
the sieve's refusal quotes, and `--answer-cmd` gets the paths.

No pytest dependency - plain asserts, run directly.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import backfill_sieve_flags as bf   # noqa: E402
import shot_schema                  # noqa: E402


def shot(i, desc, **kw):
    s = {"index": i, "start": float(i), "end": float(i) + 1.0,
         "tile_at": i + 0.5, "description": desc}
    s.update(kw)
    return s


def pool(tmp):
    footage = Path(tmp) / "footage"
    footage.mkdir()
    old = {"source": str(footage / "old.mp4"), "shots": [
        shot(0, "Two women talk, name captions visible"),
        shot(1, "A house by a lake"),
        shot(2, "Title card", is_card=True),
    ]}
    done = {"source": str(footage / "done.mp4"), "shots": [
        shot(0, "A kitchen", burned_text=False, on_topic=True)]}
    mixed = {"source": str(footage / "mixed.mp4"), "shots": [
        shot(0, "A street", burned_text=True, on_topic=True),
        shot(1, "A car")]}
    for name, d in (("old", old), ("done", done), ("mixed", mixed)):
        (footage / f"{name}.shots.json").write_text(json.dumps(d))
    pipeline = Path(tmp) / "pipeline"
    batch = pipeline / "chan" / "2026-09-01T0000Z"
    batch.mkdir(parents=True)
    (batch / "01b-footage-index.json").write_text(json.dumps({
        "fetched": [{"video_id": "old", "topic_id": "t1"}],
        "sources_by_topic": {"t1": ["old"]}}))
    (batch / "01-trend-hunter.json").write_text(json.dumps({"topics": [
        {"topic_id": "t1", "title_ref": {"name": "Everyday Sorcery 2",
                                         "type": "film", "year": 2026}}]}))
    return footage, pipeline


def test_queue_lists_only_unanswered_shots_with_topic():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        rows = {r["video_id"]: r for r in bf.queue(footage, pipeline)}
        assert set(rows) == {"old", "mixed"}, rows
        assert rows["old"]["unanswered"] == 3
        assert rows["old"]["unanswered_cards"] == 1
        assert rows["old"]["text_hint"] == 2      # "captions", "Title card"
        assert rows["old"]["topics"][0]["name"] == "Everyday Sorcery 2"
        assert rows["mixed"]["unanswered"] == 1
        # likeliest text first - ordering only
        assert bf.queue(footage, pipeline)[0]["video_id"] == "old"


def test_questions_carry_rules_topic_and_only_open_shots():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        _, data = bf.load_index("mixed", footage)
        q = bf.questions("mixed", data, [])
        assert [s["index"] for s in q["shots"]] == [1]
        assert set(q["rules"]) == {"burned_text", "on_topic", "screen_recording"}  # CF-0451: the third one optional
        q = bf.questions("old", bf.load_index("old", footage)[1],
                         bf.topics_by_source(pipeline)["old"])
        assert q["topic"] == "Everyday Sorcery 2 (film, 2026)"


def test_apply_sets_flags_marks_source_and_keeps_description():
    with tempfile.TemporaryDirectory() as tmp:
        footage, _ = pool(tmp)
        ans = Path(tmp) / "old.answers.json"
        ans.write_text(json.dumps({"video_id": "old", "answers": [
            {"index": 0, "burned_text": True, "on_topic": True,
             "text": "SALLY OWENS"},
            {"index": 1, "burned_text": False, "on_topic": True},
            {"index": 2, "burned_text": True, "on_topic": None}]}))
        backup = Path(tmp) / "backup"
        c = bf.apply_file(ans, footage, backup_dir=backup)
        assert c["burned_text_set"] == 3 and c["true"] == 2
        assert c["on_topic_set"] == 2 and c["left"] == 0
        data = json.loads((footage / "old.shots.json").read_text())
        s0, s1, s2 = data["shots"]
        assert s0["burned_text"] is True and s0["on_topic"] is True
        assert s0[bf.QUOTE] == "SALLY OWENS"
        assert s0["description"] == "Two women talk, name captions visible"
        assert all(s[bf.PROVENANCE] == "CF-0355" for s in data["shots"])
        assert "on_topic" not in s2          # null answer leaves it unasked
        assert bf.QUOTE not in s1
        orig = json.loads((backup / "old.shots.json").read_text())
        assert "burned_text" not in orig["shots"][0]   # the backup is the original
        assert shot_schema.is_complete(footage / "old.shots.json")


def test_apply_never_overwrites_an_existing_answer():
    with tempfile.TemporaryDirectory() as tmp:
        footage, _ = pool(tmp)
        ans = Path(tmp) / "mixed.answers.json"
        ans.write_text(json.dumps({"video_id": "mixed", "answers": [
            {"index": 0, "burned_text": False, "on_topic": False},
            {"index": 1, "burned_text": False, "on_topic": True}]}))
        c = bf.apply_file(ans, footage)
        assert c["kept_existing"] == 1 and c["burned_text_set"] == 1
        s0, s1 = json.loads((footage / "mixed.shots.json").read_text())["shots"]
        assert s0["burned_text"] is True and s0["on_topic"] is True
        assert bf.PROVENANCE not in s0
        assert s1["burned_text"] is False and s1[bf.PROVENANCE] == "CF-0355"


def test_a_bad_answer_file_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        footage, _ = pool(tmp)
        before = (footage / "old.shots.json").read_text()
        for answers in ([{"index": 0, "burned_text": "yes"}],
                        [{"index": 9, "burned_text": False}],
                        [{"index": 0, "burned_text": False, "on_topic": 1}]):
            ans = Path(tmp) / "old.answers.json"
            ans.write_text(json.dumps({"video_id": "old", "answers": answers}))
            try:
                bf.apply_file(ans, footage)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted {answers}")
            assert (footage / "old.shots.json").read_text() == before


# ---------------------------------------------------------------------------
# CF-0359: the batch step


def batch_report():
    """One batch holding `old` only - `mixed` is in the pool and not in it."""
    return {"fetched": [{"video_id": "old", "topic_id": "t1"}],
            "sources_by_topic": {"t1": ["old"]}}


def all_false(q, path):
    """A stand-in for the frame subagent: answers every open shot `false`."""
    Path(path).write_text(json.dumps({"video_id": q["video_id"], "answers": [
        {"index": s["index"], "burned_text": False, "on_topic": True}
        for s in q["shots"]]}))


def fake_sheet(footage, pipeline):
    """`bf.sheet` without ffmpeg: the questions, no contact sheet."""
    def build(vid, out_dir, _f=None, _p=None, open_test=None):
        _, data = bf.load_index(vid, footage)
        q = bf.questions(vid, data, bf.topics_by_source(pipeline).get(vid, []),
                         open_test=open_test or bf.sieve_open)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / f"{vid}{bf.QUESTIONS_SUFFIX}").write_text(
            json.dumps(q))
        q["sheet"] = None
        return q
    return build


def test_the_batch_step_marks_only_the_sources_of_the_batch():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        before = (footage / "mixed.shots.json").read_text()
        block = bf.backfill_batch(batch_report(), Path(tmp) / "out", footage,
                                  pipeline, answer=all_false,
                                  make_sheet=fake_sheet(footage, pipeline))
        assert block["answered"] == ["old"] and block["failed"] == []
        rec, = block["sources"]
        assert rec["asked"] == 3 and rec["burned_text_set"] == 3
        assert rec["left"] == 0 and rec["ok"] is True
        data = json.loads((footage / "old.shots.json").read_text())
        assert all(isinstance(s["burned_text"], bool) for s in data["shots"])
        # the pool outside the batch is left exactly as it was (the user,
        # 2026-09-23: the old pool is not marked wholesale)
        assert (footage / "mixed.shots.json").read_text() == before


def test_a_source_already_answered_is_not_in_the_batch_queue():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        report = {"sources_by_topic": {"t1": ["done"]}, "fetched": []}
        assert bf.batch_queue(report, footage) == []
        block = bf.backfill_batch(report, Path(tmp) / "out", footage, pipeline,
                                  answer=all_false)
        assert block["sources"] == [] and block["failed"] == []


def test_an_answerer_that_fails_is_a_record_and_not_an_exception():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        before = (footage / "old.shots.json").read_text()

        def boom(q, path):
            raise TimeoutError("the answerer sat for 240 s")

        block = bf.backfill_batch(batch_report(), Path(tmp) / "out", footage,
                                  pipeline, answer=boom,
                                  make_sheet=fake_sheet(footage, pipeline))
        assert block["failed"] == ["old"] and block["answered"] == []
        rec, = block["sources"]
        assert rec["ok"] is False and "240 s" in rec["error"]
        assert (footage / "old.shots.json").read_text() == before


def test_no_answers_at_all_is_a_named_failure():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        block = bf.backfill_batch(batch_report(), Path(tmp) / "out", footage,
                                  pipeline,
                                  make_sheet=fake_sheet(footage, pipeline))
        rec, = block["sources"]
        assert rec["ok"] is False and "no answers for it" in rec["error"]


def test_a_partly_answered_source_is_not_called_answered():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)

        def only_one(q, path):
            Path(path).write_text(json.dumps({"video_id": q["video_id"],
                                              "answers": [
                {"index": q["shots"][0]["index"], "burned_text": False,
                 "on_topic": True}]}))

        block = bf.backfill_batch(batch_report(), Path(tmp) / "out", footage,
                                  pipeline, answer=only_one,
                                  make_sheet=fake_sheet(footage, pipeline))
        rec, = block["sources"]
        assert rec["ok"] is False and "still unanswered" in rec["error"]
        assert rec["burned_text_set"] == 1 and rec["left"] == 2


def test_the_batch_step_asks_for_both_flags():
    """An index with `burned_text` everywhere and one `on_topic` missing is
    `unsieved` to the sieve (shot_schema.sieve_counts: both flags, every
    shot), so the batch step has to ask about it - the CF-0355 queue, which
    asks about `burned_text` alone, would call it done."""
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        half = {"source": str(footage / "half.mp4"), "shots": [
            shot(0, "A kitchen", burned_text=False, on_topic=True),
            shot(1, "A car", burned_text=False)]}
        (footage / "half.shots.json").write_text(json.dumps(half))
        report = {"sources_by_topic": {"t1": ["half"]}, "fetched": []}
        assert bf.queue(footage, pipeline) and not any(
            r["video_id"] == "half" for r in bf.queue(footage, pipeline))
        row, = bf.batch_queue(report, footage)
        assert row["video_id"] == "half" and row["unanswered"] == 1
        block = bf.backfill_batch(report, Path(tmp) / "out", footage, pipeline,
                                  answer=all_false,
                                  make_sheet=fake_sheet(footage, pipeline))
        assert block["answered"] == ["half"]
        data = json.loads((footage / "half.shots.json").read_text())
        assert data["shots"][1]["on_topic"] is True
        # the shot that was already answered keeps its own answer untouched
        assert bf.PROVENANCE not in data["shots"][0]


def test_a_source_with_no_readable_index_is_recorded_not_raised():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        report = {"sources_by_topic": {"t1": ["gone"]}, "fetched": []}
        block = bf.backfill_batch(report, Path(tmp) / "out", footage, pipeline,
                                  answer=all_false)
        rec, = block["sources"]
        assert rec["video_id"] == "gone" and rec["ok"] is False
        assert "no readable index" in rec["error"]


def test_answer_cmd_gets_the_paths_and_its_answers_are_applied():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        helper = Path(tmp) / "answerer.py"
        helper.write_text(
            "import json, os, sys\n"
            "q = json.load(open(sys.argv[1]))\n"
            "assert os.environ['SIEVE_FLAGS_VIDEO_ID'] == q['video_id']\n"
            "assert os.environ['SIEVE_FLAGS_ANSWERS'] == sys.argv[2]\n"
            "json.dump({'video_id': q['video_id'], 'answers': ["
            "{'index': s['index'], 'burned_text': False, 'on_topic': True}"
            " for s in q['shots']]}, open(sys.argv[2], 'w'))\n")
        cmd = f"{sys.executable} {helper} {{questions}} {{answers}}"
        block = bf.backfill_batch(batch_report(), Path(tmp) / "out", footage,
                                  pipeline, answer_cmd=cmd,
                                  make_sheet=fake_sheet(footage, pipeline))
        assert block["answered"] == ["old"], block
        assert block["answerer"] == cmd
        data = json.loads((footage / "old.shots.json").read_text())
        assert [s["burned_text"] for s in data["shots"]] == [False] * 3


def test_an_answer_cmd_that_writes_nothing_or_exits_nonzero_fails_the_source():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        for cmd, needle in ((f"{sys.executable} -c ''", "wrote no"),
                            (f"{sys.executable} -c 'raise SystemExit(7)'",
                             "exited 7")):
            block = bf.backfill_batch(batch_report(), Path(tmp) / "out",
                                      footage, pipeline, answer_cmd=cmd,
                                      make_sheet=fake_sheet(footage, pipeline))
            rec, = block["sources"]
            assert rec["ok"] is False and needle in rec["error"], rec


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
