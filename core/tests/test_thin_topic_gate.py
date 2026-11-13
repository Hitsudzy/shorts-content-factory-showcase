#!/usr/bin/env python3
"""CF-0845: a topic with fewer clean usable shots than the channel's floor
(`content_researcher.min_usable_shots_for_script`, 10 by the user's signature
of 2026-10-21, Q8) leaves 03 before the first plan check as `pool_too_thin`,
and its slot goes to the reserve by the usual `reserve_refill`.

What is held here (stand-in batches and channel configs in a tmp root; the
tracked channel configs are read as a contract only):

* the count is the indexer's own `01b pool_depth.topics[].usable_shots`; an
  unmeasured topic is never called thin;
* the floor comes from the channel, the default is 10, 0 switches it off;
* `--write` moves every script of a thin topic from `scripts[]` to
  `skipped[]` with the funnel's existing code, once (idempotent), and leaves
  the deep topics alone;
* CF-0850: a thin topic the Researcher was handed and never wrote (step 2's
  `--check` listed it) is recorded too, so it is never lost silently;
* the freed slot is a refusal `reserve_refill` counts - with a reserve left
  the reserve round runs;
* the schema takes a whole number >= 0 only; ExampleFilm carries 10 with the
  user's note, ExampleTech 0 (CF-0863: the rule off on Tech) - and with 0 the
  gate takes nothing out, written or unwritten, and its `--check` exits 0.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "patterns"))
from _tmproot import tmp_root  # noqa: E402
import run_checks  # noqa: E402
import thin_topic  # noqa: E402
import funnel  # noqa: E402
import validate_patterns as vp  # noqa: E402

TMP = tmp_root("thin-topic-gate-test-")
_N = [0]


def _chan(name, block=None):
    cdir = TMP / "channels"
    cdir.mkdir(exist_ok=True)
    cfg = {"channel_id": name}
    if block is not None:
        cfg["content_researcher"] = block
    (cdir / f"{name}.json").write_text(json.dumps(cfg))


def batch(depth, channel="thinchan", scripts=None, remaining=None, skipped=()):
    """`depth`: {topic: usable_shots | None (unmeasured)}."""
    _N[0] += 1
    b = TMP / "pipeline" / channel / f"2026-10-21T{_N[0]:04d}Z"
    b.mkdir(parents=True)
    topics = list(depth)
    rows = [{"topic_id": t, "usable_shots": n if n is not None else 0, "measured": n is not None,
             "floor": 60, "deep_enough": bool(n and n >= 60)} for t, n in depth.items()]
    idx = {"batch": str(b), "sources_by_topic": {t: [f"{t}-a"] for t in topics},
           "pool_depth": {"floor": 60, "topics": rows, "thin": []}}
    if remaining is not None:
        idx["reserve_substitution"] = {"remaining": remaining}
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    scripts = scripts if scripts is not None else [
        {"script_id": f"{t}-script1", "topic_id": t} for t in topics]
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": b.name, "channel": channel, "scripts": scripts,
         "skipped": [dict(s) for s in skipped]}))
    return b


def _03(b):
    return json.loads((b / "03-content-researcher.json").read_text())


@contextlib.contextmanager
def factory_root():
    old = os.environ.get("FACTORY_ROOT")
    os.environ["FACTORY_ROOT"] = str(TMP)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("FACTORY_ROOT", None)
        else:
            os.environ["FACTORY_ROOT"] = old


def test_the_count_is_the_indexers_usable_shots_and_unmeasured_is_not_thin():
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = batch({"t1": 0, "t2": 9, "t3": 10, "t4": 96, "t5": None})
    assert thin_topic.usable_shots(b) == {"t1": 0, "t2": 9, "t3": 10, "t4": 96}
    rows = thin_topic.thin_topics(b, TMP)
    assert [r["topic_id"] for r in rows] == ["t1", "t2"], rows
    assert rows[0] == {"topic_id": "t1", "usable_shots": 0, "floor": 10,
                       "floor_from": "channels/thinchan.json "
                                     "content_researcher.min_usable_shots_for_script"}, rows
    # no pool_depth at all: nobody is called thin
    (b / "01b-footage-index.json").write_text(json.dumps({"sources_by_topic": {}}))
    assert thin_topic.thin_topics(b, TMP) == []


def test_the_floor_is_the_channels_the_default_is_10_and_0_is_off():
    _chan("nokey", {"plan_check_rounds": 3})
    _chan("off", {"min_usable_shots_for_script": 0})
    _chan("five", {"min_usable_shots_for_script": 5})
    _chan("bad", {"min_usable_shots_for_script": "10"})
    assert thin_topic.threshold("nokey", TMP) == (10, "default")
    assert thin_topic.threshold("nosuchchannel", TMP) == (10, "default")
    assert thin_topic.threshold("bad", TMP) == (10, "default")
    assert thin_topic.threshold("off", TMP)[0] == 0
    assert thin_topic.threshold("five", TMP)[0] == 5
    assert thin_topic.thin_topics(batch({"t1": 0}, channel="off"), TMP) == []
    assert [r["topic_id"] for r in thin_topic.thin_topics(
        batch({"t1": 4, "t2": 7}, channel="five"), TMP)] == ["t1"]
    assert [r["topic_id"] for r in thin_topic.thin_topics(
        batch({"t1": 9, "t2": 12}, channel="nokey"), TMP)] == ["t1"]


def test_write_moves_every_script_of_a_thin_topic_to_skipped_once():
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = batch({"t1": 0, "t2": 2, "t3": 40},
              scripts=[{"script_id": "t1-script1", "topic_id": "t1"},
                       {"script_id": "t1-script2", "topic_id": "t1"},
                       {"script_id": "t2-script1", "topic_id": "t2"},
                       {"script_id": "t3-script1", "topic_id": "t3"}],
              skipped=[{"topic_id": "t0", "reason_code": "no_fact"}])
    rows, added = thin_topic.write(b, TMP)
    doc = _03(b)
    assert [s["script_id"] for s in doc["scripts"]] == ["t3-script1"], doc["scripts"]
    assert [s["topic_id"] for s in doc["skipped"]] == ["t0", "t1", "t1", "t2"], doc["skipped"]
    e = doc["skipped"][3]
    assert e["reason_code"] == "pool_too_thin" == thin_topic.REASON_CODE, e
    assert e["stage"] == "scripts" and e["gate"] == "min_usable_shots", e
    assert e["usable_shots"] == 2 and e["min_usable_shots"] == 10, e
    assert e["script_id"] == "t2-script1" and e["reason"].startswith("t2-script1: 2 usable"), e
    assert "CF-0845" in e["reason"] and "plan check" in e["reason"], e
    assert doc["thin_topic_gate"][0]["topics"] == ["t1", "t2"], doc
    # the funnel reads it as its existing code, with its Russian line
    assert funnel.code_of(e) == "pool_too_thin", funnel.code_of(e)
    assert "pool_too_thin" in funnel.FUNNEL_CODES and funnel.REASONS_RU["pool_too_thin"]
    # idempotent: a second run moves nothing and writes nothing
    before = (b / "03-content-researcher.json").read_text()
    assert thin_topic.write(b, TMP)[1] == []
    assert (b / "03-content-researcher.json").read_text() == before


def test_a_batch_with_only_deep_topics_is_not_rewritten():
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = batch({"t1": 10, "t2": 300})
    before = (b / "03-content-researcher.json").read_text()
    assert thin_topic.write(b, TMP) == ([], [])
    assert (b / "03-content-researcher.json").read_text() == before


def test_the_freed_slot_goes_to_the_reserve_by_reserve_refill():
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = batch({"t1": 0, "t2": 50}, remaining=["r1"])
    assert run_checks.reserve_refill(b)[0] is False     # nobody refused yet
    thin_topic.write(b, TMP)
    holds, why = run_checks.reserve_refill(b)
    assert holds and why.startswith("N=1 refused, M=1"), why
    # with the reserve empty the slot stays empty - the usual rule, nothing new
    b2 = batch({"t1": 0}, remaining=[])
    thin_topic.write(b2, TMP)
    assert run_checks.reserve_refill(b2)[0] is False


def _contract():
    """The live monitor's own reading (CF-0850): the test must hold the gate
    to the very function that went red on example-tech/2026-10-22T0833Z."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pipeline_contracts_for_thin", HERE / "test_pipeline_contracts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tech_0833z_shape(scripts_written, results, extra_idx=None, skipped=()):
    """The shape of example-tech/2026-10-22T0833Z: 02 results carry a topic
    (`-017`) the indexer kept (on own graphics, 0 sources, measured 0 usable
    shots); step 2's `--check` listed it, so the Researcher wrote no script of
    it and no skip either."""
    depth = {t: n for t, n in results.items()}
    b = batch(depth, scripts=[{"script_id": f"{t}-script1", "topic_id": t}
                              for t in scripts_written], skipped=skipped)
    idx = json.loads((b / "01b-footage-index.json").read_text())
    idx["sources_by_topic"] = {t: ([] if n == 0 else [f"{t}-a"]) for t, n in depth.items()}
    idx["skipped_topics"] = []
    idx["two_source_floor"] = {"kept_on_own_graphics": [t for t, n in depth.items() if n == 0]}
    idx.update(extra_idx or {})
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    (b / "02-compliance-checker.json").write_text(json.dumps(
        {"batch_id": b.name, "results": [{"topic_id": t, "verdict": "clear"} for t in results],
         "reserve": [], "cut": []}))
    return b


def test_a_thin_topic_never_written_is_recorded_not_lost():
    """CF-0850, on the shape of example-tech/2026-10-22T0833Z: `-017` (0 usable
    shots, in 02 results, not taken off by 01b) was listed by step 2's
    `--check` and never written, so the 6b drop had no script of it to move
    and it left the batch in neither `scripts[]` nor `skipped[]` - the live
    monitor went red and its slot never reached the reserve. The gate now
    records it as `pool_too_thin` (no `script_id`), once, and the monitor's
    own check is green on the result."""
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    pc = _contract()
    b = _tech_0833z_shape(["t003", "t002"], {"t003": 73, "t002": 22, "t017": 0})
    # before the gate: the monitor's breach, exactly as on the batch
    try:
        pc.check_researcher_accounts_for_every_topic(b / "03-content-researcher.json", "pre")
        raise RuntimeError("the stand-in batch is not the breach it imitates")
    except AssertionError as e:
        assert "t017" in str(e), e
    rows, added = thin_topic.write(b, TMP)
    doc = _03(b)
    assert [s["topic_id"] for s in doc["scripts"]] == ["t003", "t002"], doc["scripts"]
    assert [a["topic_id"] for a in added] == ["t017"], added
    e = doc["skipped"][0]
    assert e["reason_code"] == "pool_too_thin" and e["gate"] == "min_usable_shots", e
    assert "script_id" not in e and e["unwritten"] is True and e["usable_shots"] == 0, e
    assert "not written" in e["reason"] and "CF-0850" in e["reason"], e
    assert funnel.code_of(e) == "pool_too_thin", e
    pc.check_researcher_accounts_for_every_topic(b / "03-content-researcher.json", "post")
    # its slot is a refusal the reserve round answers
    idx = json.loads((b / "01b-footage-index.json").read_text())
    idx["reserve_substitution"] = {"remaining": ["r1"]}
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    assert run_checks.reserve_refill(b)[0] is True
    # idempotent: a second pass writes nothing
    before = (b / "03-content-researcher.json").read_text()
    assert thin_topic.write(b, TMP)[1] == []
    assert (b / "03-content-researcher.json").read_text() == before


def test_only_handed_topics_are_recorded():
    """CF-0850: what the gate records is what the Researcher was handed - an
    unused reserve topic, a topic 01b took off, and a topic already skipped
    under another code are not recorded; a promoted substitute is."""
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = _tech_0833z_shape(
        ["t1"], {"t1": 40, "t2": 0, "t3": 0, "t4": 0},
        extra_idx={"skipped_topics": [{"topic_id": "t3", "reason_code": "no_second_source",
                                       "reason": "x"}],
                   "reserve_substitution": {"substitutions": [
                       {"topic_id": "r1", "outcome": "sources", "replaced": "t2"},
                       {"topic_id": "r2", "outcome": "none", "replaced": "t4"}]},
                   "pool_depth": {"topics": [
                       {"topic_id": t, "usable_shots": n, "measured": True}
                       for t, n in (("t1", 40), ("t2", 0), ("t3", 0), ("t4", 0),
                                    ("r1", 2), ("r2", 0), ("r9", 0))]}},
        skipped=[{"topic_id": "t4", "reason_code": "no_fact", "reason": "y"}])
    assert thin_topic.handed_topics(b) == {"t1", "t2", "t4", "r1"}
    rows, added = thin_topic.write(b, TMP)
    assert sorted(a["topic_id"] for a in added) == ["r1", "t2"], added
    # no 02 (the older stand-ins above): nothing is called handed
    (b / "02-compliance-checker.json").unlink()
    assert thin_topic.handed_topics(b) == set()


def test_the_cli_checks_and_writes():
    _chan("thinchan", {"min_usable_shots_for_script": 10})
    b = batch({"t1": 3, "t2": 30})
    with factory_root():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert thin_topic.main(["--batch", str(b), "--json"]) == 1
        out = json.loads(buf.getvalue())
        assert out["floor"] == 10 and [r["topic_id"] for r in out["thin"]] == ["t1"], out
        assert _03(b)["skipped"] == []                  # --check writes nothing
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert thin_topic.main(["--batch", str(b), "--write"]) == 0
        assert "t1-script1 -> skipped[] pool_too_thin (3 usable)" in buf.getvalue(), buf.getvalue()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert thin_topic.main(["--batch", str(TMP / "no-such-batch")]) == 2
    # the shim runs the same code
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "thin_topic_gate.py"),
                         "--batch", str(b), "--root", str(TMP)],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 1 and "t1 (3 usable)" in cp.stdout, cp.stdout + cp.stderr


def test_the_schema_takes_a_whole_number_from_0():
    for ok in (0, 10, 96):
        assert vp.validate_content_researcher_block(
            {"content_researcher": {"min_usable_shots_for_script": ok,
                                    "min_usable_shots_for_script_note": "why"}}) == [], ok
    for bad in ("10", -1, 1.5, True, None):
        errs = vp.validate_content_researcher_block(
            {"content_researcher": {"min_usable_shots_for_script": bad}})
        assert errs and "CF-0845" in errs[0], (bad, errs)






def test_floor_0_takes_nothing_out_written_or_unwritten():
    """With the rule off nothing leaves 03: not a written script of a 0-shot
    topic, not a handed topic never written (CF-0850); 03 is not rewritten,
    `--check` exits 0 and `--write` reports nothing to take out."""
    _chan("offchan", {"min_usable_shots_for_script": 0})
    b = batch({"t1": 0, "t2": 3, "t3": 40}, channel="offchan",
              scripts=[{"script_id": "t1-script1", "topic_id": "t1"},
                       {"script_id": "t3-script1", "topic_id": "t3"}])
    (b / "02-compliance-checker.json").write_text(json.dumps(
        {"results": [{"topic_id": t, "verdict": "clear"} for t in ("t1", "t2", "t3")]}))
    before = (b / "03-content-researcher.json").read_text()
    assert thin_topic.write(b, TMP) == ([], [])
    assert (b / "03-content-researcher.json").read_text() == before
    for args in (["--check"], ["--write"]):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = thin_topic.main(["--batch", str(b), "--root", str(TMP), "--json"] + args)
        out = json.loads(buf.getvalue())
        assert code == 0 and out["floor"] == 0 and out["thin"] == [], (args, out)
    assert (b / "03-content-researcher.json").read_text() == before
    # the shim runs the same code
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "thin_topic_gate.py"),
                         "--batch", str(b), "--root", str(TMP)],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0 and "floor 0" in cp.stdout, cp.stdout + cp.stderr


if __name__ == "__main__":
    import shutil
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
