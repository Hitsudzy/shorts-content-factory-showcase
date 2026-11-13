#!/usr/bin/env python3
"""CF-0648: what held_screen (CF-0646) flags is re-cut before the render.

The operator of `rebuilds/2026-10-09T1208Z` did it by hand - read the plan's
`held_screen` findings, `resolve_anchors.py --exclude-candidate BLOCK`
(CF-0367), the plan again, at most twice per block. `held_recut.py` is that
loop inside build_render_plan.py. What these tests hold, on stand-ins (no
resolve, no render, no pool - CF-0613):

  * `wanted()`: a finding of the three rules on a shot the storyboard block
    shows is asked for; a card / opening, an anchor with its 2 re-cuts, a
    walk that reached every candidate are left, each with why;
  * `better()`: built, and a higher score - or the same with fewer findings;
  * `run()`: the storyboard's own resolve command with `--exclude-candidate
    BLOCK=SHOT --exclude-by held_screen`, then this build's own command one
    round deeper; kept when better, otherwise the storyboard, the plan files
    and the clips are put back; a failed resolve is put back too; the round
    cap, an older storyboard and the off switch do nothing;
  * resolve_anchors.py: `--exclude-by` rides on the new exclusions, the
    storyboard says how it was resolved (`resolve_call`, the exclusion flags
    out); build_render_plan.py calls the loop last, `--no-held-recut` off.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import inspect
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0648-recut-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import held_recut as hr  # noqa: E402
import resolve_anchors as ra  # noqa: E402

SOFT, THIN, CUT = hr.RULES[2], hr.RULES[0], hr.RULES[1]


def story_block(shot, wi, not_reached=3):
    b = {"shot": shot, "word_range": [wi, wi], "held_frame": True}
    if not_reached is not None:
        b["length_supply"] = {"need_seconds": 2.9, "offered": 9,
                              "not_reached": not_reached}
    return b


def finding(block, rule, cut=None):
    return {"rule": rule, "block": block, "cut": cut, "start": 0.0, "end": 2.9,
            "seconds": 2.9}


def plan_of(blocks, findings, score=60.0):
    return {"blocks": blocks, "held_screen": {"findings": findings},
            "score": {"score": score}}


def scene():
    story = {"blocks": [story_block("A:1", 0), story_block("A:55", 65),
                        {"kind": "card", "word_range": [80, 80]}],
             "excluded_candidates": []}
    plan = plan_of([{"shot": "A:1"}, {"shot": "A:55"}, {"asset": {"kind": "card"}}],
                   [finding(1, SOFT), finding(1, CUT), finding(2, THIN),
                    finding(0, "score.held_soft_frame")])
    return plan, story


# --- wanted / better --------------------------------------------------------

def test_a_flagged_shot_of_the_blocks_own_pool_is_asked_for():
    plan, story = scene()
    todo, skipped = hr.wanted(plan, story)
    assert [(t["block"], t["shot"], t["word_index"]) for t in todo] == [(1, "A:55", 65)]
    assert todo[0]["rules"] == [SOFT, CUT]
    assert [s["block"] for s in skipped] == [2] and "card" in skipped[0]["why"]


def test_an_anchor_with_its_two_recuts_is_left():
    plan, story = scene()
    story["excluded_candidates"] = [
        {"word_index": 65, "shot": "A:9", "by": hr.BY},
        {"word_index": 65, "shot": "A:8", "by": hr.BY},
        {"word_index": 65, "shot": "A:7"}]          # the operator's, not counted
    todo, skipped = hr.wanted(plan, story)
    assert todo == [] and "2 re-cuts" in skipped[0]["why"]
    story["excluded_candidates"].pop(0)
    assert len(hr.wanted(plan, story)[0]) == 1


def test_a_walk_that_reached_every_candidate_is_left_an_unknown_one_tried():
    plan, story = scene()
    story["blocks"][1] = story_block("A:55", 65, not_reached=0)
    todo, skipped = hr.wanted(plan, story)
    assert todo == [] and "nothing else" in skipped[0]["why"]
    story["blocks"][1] = story_block("A:55", 65, not_reached=None)
    assert len(hr.wanted(plan, story)[0]) == 1


def test_a_sequence_cut_is_named_by_its_shot():
    story = {"blocks": [{"shot": "A:1", "swing_block_shots": ["A:1", "B:4"],
                         "word_range": [3, 3]}]}
    plan = plan_of([{"shot": "A:1", "asset": {"kind": "sequence",
                                              "cuts": [{"shot": "A:1"}, {"shot": "B:4"}]}}],
                   [finding(0, SOFT, cut=1)])
    todo, _ = hr.wanted(plan, story)
    assert [(t["block"], t["cut"], t["shot"]) for t in todo] == [(0, 1, "B:4")]


def test_better_reads_the_exit_the_score_and_the_findings():
    old = plan_of([], [finding(1, SOFT)], score=49.16)
    assert hr.better(plan_of([], [], score=60.71), old, 0)
    assert not hr.better(plan_of([], [], score=60.71), old, 2)
    assert not hr.better(plan_of([], [], score=40.0), old, 0)
    assert hr.better(plan_of([], [], score=49.16), old, 0)        # same, fewer
    assert not hr.better(plan_of([], [finding(1, SOFT)], score=49.16), old, 0)
    assert not hr.better(None, old, 0)


# --- run --------------------------------------------------------------------

def workdir(name):
    work = tmp_root(f"cf0648-{name}-")
    (work / "clips").mkdir()
    (work / "clips" / "s01_held.png").write_text("old frame")
    plan, story = scene()
    story["resolve_call"] = {"task": "CF-0648", "script": "/x/resolve_anchors.py",
                             "python": "/x/python", "cwd": str(work),
                             "argv": ["anchors.json", "words.json", "voice.wav",
                                      str(work / "storyboard.json"),
                                      "--clips-dir", "clips", "--index", "i"]}
    (work / "storyboard.json").write_text(json.dumps(story))
    (work / "plan.json").write_text(json.dumps(plan))
    (work / "plan.score.json").write_text('{"old": true}')
    return work, plan, story


class Runner:
    """resolve, then the child build - each a function of (argv, work)."""
    def __init__(self, work, resolve, child):
        self.work, self.calls, self.steps = work, [], [resolve, child]

    def __call__(self, argv, cwd, env):
        self.calls.append((list(argv), cwd, dict(env)))
        return self.steps[len(self.calls) - 1](argv, self.work, env)


def recut_ok(argv, work, env):
    s = json.loads((work / "storyboard.json").read_text())
    s["blocks"][1]["shot"] = "A:21"
    (work / "storyboard.json").write_text(json.dumps(s))
    (work / "clips" / "s01_held.png").write_text("new frame")
    return 0


def child_scoring(score, findings=(), code=0):
    def child(argv, work, env):
        (work / "plan.json").write_text(json.dumps(
            plan_of([{"shot": "A:1"}, {"shot": "A:21"}, {}], list(findings), score=score)))
        (work / "plan.refusal.json").write_text("{}") if code else None
        return code
    return child


def test_a_better_recut_is_kept_and_recorded():
    work, plan, story = workdir("kept")
    run = Runner(work, recut_ok, child_scoring(64.0))
    rec = hr.run(str(work / "plan.json"), str(work / "storyboard.json"), plan, story,
                 argv=["build_render_plan.py", "sb", "w", "v", "plan.json"],
                 python="/py", runner=run, env={}, log=lambda m: None)
    assert rec["outcome"] == "kept" and rec["score"] == [60.0, 64.0], rec
    resolve, cwd, _ = run.calls[0]
    assert resolve[:2] == ["/x/python", "/x/resolve_anchors.py"]
    assert resolve[-4:] == ["--exclude-candidate", "1=A:55", "--exclude-by", hr.BY]
    assert cwd == str(work)
    child, _, env = run.calls[1]
    assert child == ["/py", "build_render_plan.py", "sb", "w", "v", "plan.json"]
    assert env[hr.ENV_ROUND] == "1"
    final = json.loads((work / "plan.json").read_text())
    assert final[hr.FIELD][0]["outcome"] == "kept"
    assert (work / "clips" / "s01_held.png").read_text() == "new frame"
    assert not (work / hr.SNAP_DIR).exists()


def test_a_worse_recut_is_put_back_whole():
    work, plan, story = workdir("worse")
    before_story = (work / "storyboard.json").read_text()
    run = Runner(work, recut_ok, child_scoring(55.0, findings=[finding(1, SOFT)]))
    rec = hr.run(str(work / "plan.json"), str(work / "storyboard.json"), plan, story,
                 argv=["b.py"], python="/py", runner=run, env={}, log=lambda m: None)
    assert rec["outcome"] == "reverted", rec
    assert (work / "storyboard.json").read_text() == before_story
    assert (work / "clips" / "s01_held.png").read_text() == "old frame"
    assert (work / "plan.score.json").read_text() == '{"old": true}'
    final = json.loads((work / "plan.json").read_text())
    assert final["blocks"][1]["shot"] == "A:55"
    assert final[hr.FIELD][-1]["outcome"] == "reverted"


def test_a_refused_recut_plan_is_put_back_and_its_sidecar_removed():
    work, plan, story = workdir("refused")
    run = Runner(work, recut_ok, child_scoring(70.0, code=2))
    rec = hr.run(str(work / "plan.json"), str(work / "storyboard.json"), plan, story,
                 argv=["b.py"], python="/py", runner=run, env={}, log=lambda m: None)
    assert rec["outcome"] == "reverted" and rec["exit"] == 2
    assert not (work / "plan.refusal.json").exists()


def test_a_failed_resolve_is_put_back_and_no_plan_is_built():
    work, plan, story = workdir("failed")

    def broken(argv, work, env):
        (work / "clips" / "s01_held.png").write_text("half-written")
        return 1
    run = Runner(work, broken, None)
    rec = hr.run(str(work / "plan.json"), str(work / "storyboard.json"), plan, story,
                 argv=["b.py"], python="/py", runner=run, env={}, log=lambda m: None)
    assert rec["outcome"] == "resolve_failed" and len(run.calls) == 1
    assert (work / "clips" / "s01_held.png").read_text() == "old frame"


def test_the_round_cap_an_old_storyboard_and_the_switch_run_nothing():
    work, plan, story = workdir("caps")
    run = Runner(work, None, None)
    kw = dict(argv=["b.py"], python="/py", runner=run, log=lambda m: None)
    p, s = str(work / "plan.json"), str(work / "storyboard.json")
    rec = hr.run(p, s, plan, story, env={hr.ENV_ROUND: str(hr.MAX_ROUNDS)}, **kw)
    assert rec["outcome"] == "round_cap"
    old = dict(story)
    old.pop("resolve_call")
    assert hr.run(p, s, plan, old, env={}, **kw)["outcome"] == "no_resolve_call"
    assert hr.run(p, s, plan, story, env={hr.ENV_OFF: "1"}, **kw) is None
    assert run.calls == []
    clean = dict(plan, held_screen={"findings": []})
    assert hr.run(p, s, clean, story, env={}, **kw) is None


def test_a_call_copied_from_another_batch_is_not_run():
    """CF-0669: a rebuild copies work/<slug>/ with the storyboard's
    resolve_call, whose OUTPUT is the source batch's storyboard - run as
    written it would re-cut the source. Nothing runs, the plan says why."""
    work, plan, story = workdir("copied")
    source = tmp_root("cf0669-source-")
    story["resolve_call"]["argv"][3] = str(source / "storyboard.json")
    run = Runner(work, None, None)
    p = str(work / "plan.json")
    rec = hr.run(p, str(work / "storyboard.json"), plan, story, argv=["b.py"],
                 python="/py", runner=run, env={}, log=lambda m: None)
    assert rec["outcome"] == "resolve_call_elsewhere" and run.calls == []
    assert json.loads(Path(p).read_text())[hr.FIELD][-1]["outcome"] == \
        "resolve_call_elsewhere"
    assert not (source / "storyboard.json").exists()
    # a relative OUTPUT against the call's own cwd is this storyboard
    story["resolve_call"]["argv"][3] = "storyboard.json"
    assert hr.names_storyboard(story["resolve_call"], work / "storyboard.json")


# --- the wiring --------------------------------------------------------------

def test_resolve_tags_its_exclusions_and_records_its_call():
    work = tmp_root("cf0648-excl-")
    sb = work / "storyboard.json"
    sb.write_text(json.dumps({"blocks": [story_block("A:1", 0), story_block("A:55", 65)],
                              "excluded_candidates": [
                                  {"block": 1, "word_index": 65, "shot": "A:9"}]}))
    got, _ = ra.load_exclusions(sb, ["1=A:55"], by=hr.BY)
    assert got[0].get("by") is None and got[1]["by"] == hr.BY and got[1]["shot"] == "A:55"
    call = ra.resolve_call(["a", "--exclude-candidate", "7", "--exclude-by=x",
                            "--exclude-candidate=8", "--clips-dir", "c"])
    assert call["argv"] == ["a", "--clips-dir", "c"]
    assert call["script"].endswith("resolve_anchors.py") and call["cwd"]
    src = inspect.getsource(ra.main)
    assert 'out["resolve_call"] = resolve_call(sys.argv[1:])' in src
    assert "by=args.exclude_by" in src


def test_the_plan_builder_calls_the_loop_last_and_can_be_told_not_to():
    import build_render_plan as brp
    src = inspect.getsource(brp.main)
    assert "if HELD_RECUT_ON and not args.no_held_recut:\n        held_recut.run(" \
           "args.output, args.storyboard, plan, story," in src
    assert src.index("held_recut.run(") > src.index("json.dump(plan, open(args.output")
    # only the command line's run re-cuts; a test calling main() builds once
    assert "HELD_RECUT_ON = True\n    main()" in inspect.getsource(brp.cli)
    assert brp.HELD_RECUT_ON is False


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
