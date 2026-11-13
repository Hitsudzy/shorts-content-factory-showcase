#!/usr/bin/env python3
"""CF-0362: the two-source floor and the thin pool warn in `measure`.

The user's decision of 2026-09-23 (CF-0320 / CF-0330): `no_second_source` and
`pool_too_thin` are a warning, not a refusal, and the channel's
`video_editor.two_source_gate` is the switch. On batch
`example-film/2026-09-23T1722Z` this stage still refused four topics that each
held a kept, sieved source. Pinned here:

  * `measure` - a topic with one kept source stays, with a `warnings[]` entry
    carrying its counts;
  * `enforce` - the same topic is refused `no_second_source` as before;
  * a topic with no kept source is refused in either mode;
  * a pool under the depth floor is a `pool_too_thin` warning in either mode.

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


def report():
    return {
        "sources_by_topic": {"one": ["a"], "none": [], "thin": ["b", "c"]},
        "skipped_topics": [
            {"topic_id": "one", "reason_code": ib.TOPIC_REFUSAL_CODE,
             "reason": "1 canonical source(s), floor is 2", "stage": ib.STAGE_NAME},
            {"topic_id": "none", "reason_code": ib.SIEVE_FOREIGN_CODE,
             "reason": "no source at all", "stage": ib.STAGE_NAME}],
        "two_source_floor": {"wanted": 2, "refused": ["one"]},
        "pool_depth": {"floor": 60, "topics": [
            {"topic_id": "one", "sources": 1, "shots": 56, "usable_shots": 33,
             "usable_seconds": 65.9, "floor": 60, "deep_enough": False,
             "measured": True},
            {"topic_id": "thin", "sources": 2, "shots": 80, "usable_shots": 40,
             "usable_seconds": 90.0, "floor": 60, "deep_enough": False,
             "measured": True}]},
    }


def codes(r):
    return {(w["topic_id"], w["warning_code"]) for w in r.get("warnings") or []}


def test_measure_keeps_a_one_source_topic_with_a_warning():
    r = report()
    kept = ib.apply_floor_mode(r, ib.GATE_MEASURE, log=lambda *_: None)
    assert kept == ["one"]
    assert [s["topic_id"] for s in r["skipped_topics"]] == ["none"]
    w = [w for w in r["warnings"] if w["warning_code"] == ib.TOPIC_REFUSAL_CODE]
    assert len(w) == 1 and w[0]["severity"] == "warn"
    assert w[0]["numbers"]["sources"] == 1
    assert w[0]["numbers"]["usable_shots"] == 33
    assert r["two_source_floor"]["refused"] == []
    assert r["two_source_floor"]["warned"] == ["one"]
    # the thin pool warns, and so does the kept one-source topic's pool
    assert ("thin", ib.POOL_THIN_WARNING_CODE) in codes(r)
    assert ("one", ib.POOL_THIN_WARNING_CODE) in codes(r)


def test_enforce_refuses_it_as_before():
    r = report()
    kept = ib.apply_floor_mode(r, ib.GATE_ENFORCE, log=lambda *_: None)
    assert kept == []
    assert [s["topic_id"] for s in r["skipped_topics"]] == ["one", "none"]
    assert r["two_source_floor"]["refused"] == ["one"]
    assert codes(r) == {("thin", ib.POOL_THIN_WARNING_CODE)}


def test_a_topic_with_no_source_is_refused_in_either_mode():
    for mode in ib.GATE_MODES:
        r = report()
        r["skipped_topics"][1]["reason_code"] = ib.TOPIC_REFUSAL_CODE
        ib.apply_floor_mode(r, mode, log=lambda *_: None)
        assert "none" in [s["topic_id"] for s in r["skipped_topics"]], mode


def test_a_second_pass_neither_doubles_nor_loses_a_warning():
    r = report()
    ib.apply_floor_mode(r, ib.GATE_MEASURE, log=lambda *_: None)
    first = json.dumps(r["warnings"], sort_keys=True)
    ib.apply_floor_mode(r, ib.GATE_MEASURE, log=lambda *_: None)
    assert json.dumps(r["warnings"], sort_keys=True) == first
    assert r["two_source_floor"]["warned"] == ["one"]


def test_the_mode_is_read_like_the_editor_reads_it():
    m = ib.gate_mode_from_config
    assert m({"video_editor": {"two_source_gate": "enforce"}}) == "enforce"
    assert m({"video_editor": {"two_source_gate": {"mode": "Enforce"}}}) == "enforce"
    assert m({"video_editor": {"two_source_gate": "measure"}}) == "measure"
    assert m({"video_editor": {"two_source_gate": "enforc"}}) == ib.DEFAULT_GATE_MODE
    assert m({}) == ib.DEFAULT_GATE_MODE
    assert ib.two_source_mode("no-such-channel-cf0362") == ib.DEFAULT_GATE_MODE


# --------------------------------------------------------------------------
# CF-0419: the rule's own switch, `footage_indexer.no_second_source` (the user,
# 2026-09-28: a warning). `runlog triage` reads a rule's mode at its own path
# in the channel config; with nothing there it called this rule `hard-wired`
# and filed an `unpriced_refusal` on every batch while the stage refused
# nothing.
# --------------------------------------------------------------------------

def test_the_floor_s_own_key_is_the_path_the_triage_reads():
    assert ib.FLOOR_RULE == "footage_indexer.no_second_source"
    assert ib.FLOOR_KEY_PATH == ("footage_indexer", "no_second_source")
    m = ib.floor_mode_from_config
    assert m({"footage_indexer": {"no_second_source": "warn"}}) == \
        ("warn", ib.FLOOR_FROM_OWN_KEY)
    assert m({"footage_indexer": {"no_second_source": {"mode": "Warn",
                                                       "note": "28.09"}}}) == \
        ("warn", ib.FLOOR_FROM_OWN_KEY)
    assert m({"footage_indexer": {"no_second_source": "enforce"}})[0] == "enforce"


def test_the_own_key_wins_over_the_editor_s_switch():
    cfg = {"footage_indexer": {"no_second_source": "warn"},
           "video_editor": {"two_source_gate": "enforce"}}
    assert ib.floor_mode_from_config(cfg) == ("warn", ib.FLOOR_FROM_OWN_KEY)
    cfg = {"footage_indexer": {"no_second_source": "enforce"},
           "video_editor": {"two_source_gate": "measure"}}
    assert ib.floor_mode_from_config(cfg) == ("enforce", ib.FLOOR_FROM_OWN_KEY)


def test_without_the_key_the_editor_s_switch_then_warn():
    m = ib.floor_mode_from_config
    assert m({"video_editor": {"two_source_gate": "enforce"}}) == \
        ("enforce", ib.FLOOR_FROM_EDITOR)
    assert m({}) == ("warn", ib.FLOOR_FROM_DEFAULT)
    # a typo in the own key is silence, not a refusal: it falls through
    assert m({"footage_indexer": {"no_second_source": "enforc"}}) == \
        ("warn", ib.FLOOR_FROM_DEFAULT)
    assert ib.floor_mode("no-such-channel-cf0419") == \
        ("warn", ib.FLOOR_FROM_DEFAULT)
    assert ib.floor_mode("no-such-channel-cf0419", flag="enforce") == \
        ("enforce", ib.FLOOR_FROM_FLAG)


def test_a_config_file_on_disk_is_read_at_the_own_key():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "ch.json"
        cfg.write_text(json.dumps({
            "footage_indexer": {"no_second_source": {"mode": "warn"}},
            "video_editor": {"two_source_gate": "enforce"}}))
        assert ib.floor_mode("ch", config_path=cfg) == \
            ("warn", ib.FLOOR_FROM_OWN_KEY)


def test_warn_keeps_the_topic_and_01b_says_which_rule_and_where_from():
    r = report()
    kept = ib.apply_floor_mode(r, "warn", log=lambda *_: None,
                               whence=ib.FLOOR_FROM_OWN_KEY)
    assert kept == ["one"]
    assert [s["topic_id"] for s in r["skipped_topics"]] == ["none"]
    w = [w for w in r["warnings"] if w["warning_code"] == ib.TOPIC_REFUSAL_CODE]
    assert len(w) == 1
    assert w[0]["rule"] == ib.FLOOR_RULE and w[0]["mode"] == "warn"
    assert w[0]["mode_from"] == ib.FLOOR_FROM_OWN_KEY
    assert w[0]["severity"] == "warn"
    floor = r["two_source_floor"]
    assert floor["mode"] == "warn" and floor["rule"] == ib.FLOOR_RULE
    assert floor["mode_from"] == ib.FLOOR_FROM_OWN_KEY
    assert floor["refused"] == [] and floor["warned"] == ["one"]
    # and a second pass under `warn` is idempotent, like `measure`
    first = json.dumps(r["warnings"], sort_keys=True)
    ib.apply_floor_mode(r, "warn", log=lambda *_: None,
                        whence=ib.FLOOR_FROM_OWN_KEY)
    assert json.dumps(r["warnings"], sort_keys=True) == first


def test_every_refusing_spelling_refuses_and_every_keeping_one_keeps():
    for mode in ib.FLOOR_REFUSE_MODES:
        r = report()
        assert ib.apply_floor_mode(r, mode, log=lambda *_: None) == [], mode
        assert r["two_source_floor"]["refused"] == ["one"], mode
    for mode in ib.FLOOR_KEEP_MODES:
        r = report()
        assert ib.apply_floor_mode(r, mode, log=lambda *_: None) == ["one"], mode


def test_a_one_source_substitute_does_not_free_its_slot_under_warn():
    """The reserve queue (CF-0306) must not take a second reserve topic for a
    substitute the floor is about to keep."""
    def run(floor):
        report = {"batch": "/tmp/x", "sources_by_topic": {"lost": []},
                  "skipped_topics": [{"topic_id": "lost",
                                      "reason_code": ib.TOPIC_NO_SOURCE_CODE,
                                      "stage": ib.STAGE_NAME}],
                  "fetched": [], "failed": [], "aliases": []}
        topics = [{"topic_id": t, "evidence": {"youtube_video_ids": [t + "v"]}}
                  for t in ("lost", "r1", "r2")]
        screening = ib.Screening(
            ran=True, verdict={"lost": "clear"},
            reserve=frozenset({"r1", "r2"}),
            rows=({"topic_id": "r1", "verdict": "clear"},
                  {"topic_id": "r2", "verdict": "clear"}))
        walked = []

        def fake_ingest(topics_, *a, **k):
            tid = topics_[0]["topic_id"]
            walked.append(tid)
            skip = {"topic_id": tid, "reason_code": ib.TOPIC_REFUSAL_CODE,
                    "stage": ib.STAGE_NAME, "reason": "1 source of 2"}
            return [], [], [skip], [], {tid: [tid + "v"]}
        real = ib.ingest
        ib.ingest = fake_ingest
        try:
            ib.substitute_reserve(report, topics, screening, depth_floor=0,
                                  log=lambda *_: None, floor=floor)
        finally:
            ib.ingest = real
        return walked
    assert run("warn") == ["r1"]
    assert run("enforce") == ["r1", "r2"]


def test_the_skill_names_the_switch_and_the_decision():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer"
             / "SKILL.md").read_text(encoding="utf-8")
    assert "`channels/<channel>.json` -> `footage_indexer.no_second_source`" in skill
    assert "2026-09-28" in skill and "`warn`" in skill
    assert "The refusal (under `enforce` only)" in skill


def index(n, on_topic=True):
    return {"source": "/tmp/x.mp4", "shots": [
        {"index": i, "start": float(i), "end": float(i) + 1.0,
         "description": "a scene", shot_schema.BURNED_TEXT: False,
         shot_schema.ON_TOPIC: on_topic} for i in range(n)]}


def sieve(mode):
    """`source_sieve.main()` over a batch where topic `001` holds a good
    source and a foreign one, and topic `002` only a foreign one."""
    indexes = {"good": index(5), "alien": index(5, on_topic=False),
               "alien2": index(4, on_topic=False)}
    with tempfile.TemporaryDirectory() as tmp:
        batch = Path(tmp) / "nochannel" / "2026-09-23T0000Z"
        batch.mkdir(parents=True)
        (batch / sv.REPORT_FILE).write_text(json.dumps({
            "fetched": [{"video_id": "good", "topic_id": "001"},
                        {"video_id": "alien", "topic_id": "001"},
                        {"video_id": "alien2", "topic_id": "002"}],
            "sources_by_topic": {"001": ["good", "alien"], "002": ["alien2"]},
            "failed": [], "skipped_topics": []}))
        real, real_cache = sv.read_index, ib.CACHE
        sv.read_index = lambda vid, cache=None: indexes.get(vid)
        # CF-0505: the pool is a temp one - the backfill step looks for
        # `<cache>/good.shots.json`, which must not be the live shared/footage.
        ib.CACHE = Path(tmp) / "footage"
        ib.CACHE.mkdir()
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = sv.main([str(batch), "--no-top-up", "--no-reserve",
                                "--pool-depth-floor", "0",
                                "--two-source-gate", mode])
        finally:
            sv.read_index, ib.CACHE = real, real_cache
        rep = json.loads((batch / sv.REPORT_FILE).read_text())
    return code, out.getvalue(), rep


def test_sieve_measure_keeps_the_topic_with_its_good_source():
    code, out, rep = sieve(ib.GATE_MEASURE)
    assert code == 0, out
    assert rep["sources_by_topic"]["001"] == ["good"]
    skipped = {s["topic_id"]: s["reason_code"] for s in rep["skipped_topics"]}
    assert "001" not in skipped, skipped
    assert "002" in skipped, skipped           # nothing good left: refused
    assert ("001", ib.TOPIC_REFUSAL_CODE) in codes(rep)
    assert "alien" in {f["video_id"] for f in rep["failed"]}


def test_sieve_warn_keeps_the_topic_and_records_the_rule():
    code, out, rep = sieve("warn")
    assert code == 0, out
    skipped = {s["topic_id"]: s["reason_code"] for s in rep["skipped_topics"]}
    assert "001" not in skipped and "002" in skipped, skipped
    w = [w for w in rep["warnings"] if w["warning_code"] == ib.TOPIC_REFUSAL_CODE]
    assert [x["topic_id"] for x in w] == ["001"]
    assert w[0]["rule"] == ib.FLOOR_RULE and w[0]["mode"] == "warn"
    assert w[0]["mode_from"] == ib.FLOOR_FROM_FLAG
    assert ib.FLOOR_RULE in out


def test_sieve_enforce_refuses_as_before():
    code, out, rep = sieve(ib.GATE_ENFORCE)
    assert code == 0, out
    skipped = {s["topic_id"]: s["reason_code"] for s in rep["skipped_topics"]}
    assert skipped.get("001") == ib.TOPIC_REFUSAL_CODE, skipped
    assert "002" in skipped
    assert not [w for w in rep.get("warnings") or []
                if w["warning_code"] == ib.TOPIC_REFUSAL_CODE]


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
