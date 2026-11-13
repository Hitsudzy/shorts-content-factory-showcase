#!/usr/bin/env python3
"""CF-0881: `repair_blocks.py` - the Editor's half of the repair after the
frame judge: re-pick the refused block(s), plan, render, QC, pack, 05 row.

On stand-ins only (CF-0613/CF-0609): a temp batch, a runner that plays
resolve_anchors / build_render_plan / render_video / qc_render /
frame_judge_pack / write_batch_metadata - no pool, no Remotion, no network.
Pinned here:

  * a shot target: the storyboard's own resolve command with
    `--exclude-candidate <story block>=<shot> --exclude-by judge_repair`, the
    plan check's plan command with this checkout's builder, the render with
    `--reason judge_repair` into repair/after.mp4, QC, the mp4 replaced only
    then, the pack anew, `write_batch_metadata.py --repair`; the result row
    `rendered` with `changed_blocks` (a moved neighbour too) and `replaced`;
    the snapshot (repair/before/, before.mp4) is there;
  * a resolve with nothing else to offer is `no_replacement`, a QC failure
    `qc_failed`, the cap `failed` - and each puts the batch back byte for
    byte (plan, storyboard, clips, pack, mp4);
  * a meme target: no resolve, the meme taken off the plan and said so in
    `meme_delivered`; a meme in a hole is `no_replacement`, nothing run;
  * the cap reached before anything: `failed`, nothing run;
  * the plan command rebuilt from 03 when there is no plan check;
  * a bad request is exit 2; a video 05 has no row for is a `failed` row; a
    spent time budget leaves the rest `failed`; every requested video gets
    its row, written after each one.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482
from _tmproot import tmp_root  # noqa: E402 - CF-0489
import contextlib
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
TMP = tmp_root("cf0881-repair-")
os.environ.setdefault("RUNLOG_BATCH", str(TMP / "runlog"))
sys.path.insert(0, str(SCRIPTS))

import repair_blocks as rb  # noqa: E402

SID, SLUG = "tulsa-king-001-script1", "tulsa-king"
_n = [0]


def _story_block(i, shot):
    return {"word_range": [i * 3, i * 3 + 2], "shot": shot, "asset_kind": "clip",
            "intent": f"beat {i}"}


def _plan_from_story(story, inserts=None):
    blocks = []
    for i, sb in enumerate(story["blocks"]):
        b = {"start": float(i * 3), "end": float(i * 3 + 3), "shot": sb.get("shot"),
             "asset": {"kind": "clip", "src": f"/clips/{sb.get('shot')}.mp4"},
             "intent": sb.get("intent")}
        if inserts and i in inserts:
            b["insert"] = dict(inserts[i])
        blocks.append(b)
    return {"style": "motion", "blocks": blocks, "output": {"width": 1080, "height": 1920}}


MEME = {"kind": "meme", "asset_id": "smeared-cat", "render_src": "/memes/smeared-cat.gif"}


def _batch(shots=("a:1", "b:2", "c:3", "d:4", "e:5"), meme_at=None, hole=False,
           plan_check=True, ledger=None):
    _n[0] += 1
    b = TMP / f"b{_n[0]}" / "pipeline" / "testchan" / "2026-10-28T0800Z"
    b.mkdir(parents=True)
    b = b.resolve()                     # run() works on the resolved batch
    work = b / "work" / SLUG
    (work / "clips").mkdir(parents=True)
    (work / "clips" / "a00_x_s001.mp4").write_bytes(b"clip-before")
    (b / "videos").mkdir()
    mp4 = b / "videos" / f"{SLUG}.mp4"
    mp4.write_bytes(b"MP4-BEFORE")
    story = {"blocks": [_story_block(i, s) for i, s in enumerate(shots)]}
    story["resolve_call"] = {"task": "CF-0648", "script": "/elsewhere/resolve_anchors.py",
                             "python": "/elsewhere/python", "cwd": str(work),
                             "argv": [str(work / "anchors.json"), str(work / "words.json"),
                                      str(work / "voice.wav"), str(work / "storyboard.json"),
                                      "--index", "/pool/x.shots.json",
                                      "--clips-dir", str(work / "clips")]}
    (work / "storyboard.json").write_text(json.dumps(story))
    inserts = {meme_at: MEME} if meme_at is not None else None
    plan = _plan_from_story(story, inserts)
    if meme_at is not None:
        plan["meme"] = {"meme_requested": [{"beat_id": "r1"}],
                        "meme_delivered": [{"beat_id": "r1", "outcome": "placed",
                                            "block_index": meme_at,
                                            "asset_id": MEME["asset_id"]}],
                        "inserts": [{"kind": "meme", "id": MEME["asset_id"],
                                     "block": meme_at}],
                        "hole_fill": {"filled": [{"block_index": meme_at}] if hole else []}}
    (work / "plan.json").write_text(json.dumps(plan))
    (work / "plan.score.json").write_text(json.dumps({"schema": "x", "stages": {}}))
    (work / "frame-judge").mkdir()
    (work / "frame-judge" / "manifest.json").write_text(json.dumps({"old": True}))
    (work / "frame-judge" / "verdicts.json").write_text(json.dumps({"verdicts": []}))
    if plan_check:
        (work / "plan_check.json").write_text(json.dumps({"kind": "plan_check", "steps": [
            {"step": "plan", "exit": 0, "argv": [
                "/prod/python", "/prod/agents/video-editor/scripts/build_render_plan.py",
                str(work / "storyboard.json"), str(work / "words.json"),
                str(work / "voice.wav"), str(work / "plan.json"),
                "--channel", "testchan", "--script-id", SID]}]}))
    (work / "attempts.json").write_text(json.dumps(ledger or {
        "slug": SLUG, "attempts": [{"n": 1, "result": "rendered_ok", "kind": "attempt"}],
        "needs_you": None, "attempt_cap": 3, "cap_source": "test",
        "qc_degrade_cap": 3, "qc_degrade_cap_source": "test"}))
    (b / "05-video-editor.json").write_text(json.dumps({
        "channel": "testchan", "videos": [{"script_id": SID, "output_path": str(mp4)},
                                          {"script_id": "other-script1",
                                           "output_path": str(b / "videos" / "o.mp4")}],
        "refusals": []}))
    return b, work, mp4


def _req(blocks, extra_videos=()):
    return {"schema": rb.REQUEST_SCHEMA, "task": "CF-0881", "batch_id": "x",
            "channel": "testchan", "at": "2026-10-28T09:00:00Z",
            "rules": {"max_blocks": 2, "search": False, "one_pass": True},
            "videos": [{"script_id": SID, "slug": SLUG, "topic_id": "t",
                        "reason_code": "judge_footage_defect", "score_line": "B 70",
                        "blocks": blocks}, *extra_videos]}


SHOT14 = {"block": 2, "entry": "block-2", "target": "shot", "exclude_shot": "c:3",
          "kind": "thin_strip", "why": "a strip", "start": 6.0, "end": 9.0}


class Stand:
    """The tools, played. `fail` maps a tool name to an exit code; `shift`
    moves a neighbour's shot on the re-resolve; `qc` is QC's verdict."""

    def __init__(self, work, fail=None, shift=None, qc=None, new_shot="c:22"):
        self.work, self.fail, self.calls = work, fail or {}, []
        self.shift, self.new_shot = shift or {}, new_shot
        self.qc = qc if qc is not None else {"passed": True, "failures": []}

    def __call__(self, argv, cwd=None, env=None, timeout=None):
        argv = [str(a) for a in argv]
        tool = Path(argv[1]).name
        self.calls.append((tool, argv, cwd))
        code = self.fail.get(tool, 0)
        sp = self.work / "storyboard.json"
        if tool == "resolve_anchors.py":
            if code:
                (self.work / "clips" / "a00_x_s001.mp4").write_bytes(b"clip-trashed")
                return code, ""
            story = json.loads(sp.read_text())
            for i, e in enumerate(argv):
                if e == "--exclude-candidate":
                    j, shot = argv[i + 1].split("=")
                    story["blocks"][int(j)]["shot"] = self.new_shot
            for j, s in self.shift.items():
                story["blocks"][j]["shot"] = s
            story.setdefault("excluded_candidates", []).append({"by": "judge_repair"})
            sp.write_text(json.dumps(story))
            (self.work / "clips" / "a00_x_s001.mp4").write_bytes(b"clip-after")
            return 0, ""
        if tool == "build_render_plan.py":
            if code:
                (self.work / "plan.refusal.json").write_text(json.dumps({"reason": "no"}))
                return code, ""
            old = json.loads((self.work / "plan.json").read_text())
            ins = {i: b["insert"] for i, b in enumerate(old["blocks"]) if b.get("insert")}
            plan = _plan_from_story(json.loads(sp.read_text()), ins)
            if "meme" in old:
                plan["meme"] = old["meme"]
            Path(argv[5]).write_text(json.dumps(plan))
            return 0, ""
        if tool == "render_video.py":
            if not code:
                Path(argv[3]).write_bytes(b"MP4-AFTER")
            return code, ""
        if tool == "qc_render.py":
            return (0 if self.qc.get("passed") else 1), json.dumps(self.qc)
        if tool == "frame_judge_pack.py":
            if not code:
                out = Path(argv[argv.index("--out") + 1])
                out.mkdir(parents=True, exist_ok=True)
                (out / "manifest.json").write_text(json.dumps({"new": True}))
            return code, ""
        if tool == "write_batch_metadata.py":
            return code, ""
        raise AssertionError(f"unexpected tool {tool}")

    def tools(self):
        return [c[0] for c in self.calls]

    def argv_of(self, tool):
        return next(c[1] for c in self.calls if c[0] == tool)


def _tree(work, mp4):
    """Everything a failed repair has to put back, as bytes."""
    out = {p.relative_to(work).as_posix(): p.read_bytes()
           for p in sorted(work.rglob("*")) if p.is_file()
           and not p.relative_to(work).as_posix().startswith(("repair/", "attempts.json"))}
    out["MP4"] = mp4.read_bytes()
    return out


def _run(b, req, stand, **kw):
    rq = b / "work" / "repair-requests.json"
    rq.write_text(json.dumps(req))
    rs = b / "work" / "repair-results.json"
    res = rb.run(b, rq, rs, runner=stand, log=lambda m: None, **kw)
    assert json.loads(rs.read_text()) == res
    return res


def test_shot_target_is_re_picked_rendered_and_recorded():
    b, work, mp4 = _batch()
    st = Stand(work, shift={3: "d:40"})
    res = _run(b, _req([SHOT14]), st)
    assert res["schema"] == "judge-repair-result/1" and res["task"] == "CF-0881"
    assert res["request_at"] == "2026-10-28T09:00:00Z"
    row = res["videos"][0]
    assert row["outcome"] == "rendered", row
    assert row["changed_blocks"] == [2, 3], row          # block 3 moved with it
    assert row["replaced"] == [{"block": 2, "entry": "block-2", "target": "shot",
                                "before": "c:3", "after": "c:22"}]
    assert row["output_path"] == str(mp4.resolve()) and row["qc_passed"] is True
    assert st.tools() == ["resolve_anchors.py", "build_render_plan.py", "render_video.py",
                          "qc_render.py", "frame_judge_pack.py", "write_batch_metadata.py"]
    r = st.argv_of("resolve_anchors.py")
    assert r[1] == str(SCRIPTS / "resolve_anchors.py")          # this checkout's
    assert r[-4:] == ["--exclude-candidate", "2=c:3", "--exclude-by", "judge_repair"]
    p = st.argv_of("build_render_plan.py")
    assert p[1] == str(SCRIPTS / "build_render_plan.py") and p[5] == str(work / "plan.json")
    v = st.argv_of("render_video.py")
    assert v[3] == str(work / "repair" / "after.mp4") and v[-2:] == ["--reason", "judge_repair"]
    m = st.argv_of("write_batch_metadata.py")
    assert m[3:] == ["--repair", "--video", SID, str(work / "plan.json"), str(mp4)], m
    assert mp4.read_bytes() == b"MP4-AFTER"
    assert not (work / "repair" / "after.mp4").exists()
    assert (work / "repair" / "before.mp4").read_bytes() == b"MP4-BEFORE"
    before = work / "repair" / "before"
    for f in ("plan.json", "plan.score.json", "storyboard.json", "frame-judge/manifest.json",
              "frame-judge/verdicts.json", "clips/a00_x_s001.mp4"):
        assert (before / f).is_file(), f
    assert json.loads((work / "frame-judge" / "manifest.json").read_text()) == {"new": True}
    assert not (work / "frame-judge" / "verdicts.json").exists()   # the root composes them
    rec = json.loads((work / "repair" / "record.json").read_text())
    assert rec["task"] == "CF-0881" and rec["blocks"][0]["block"] == 2
    assert rec["changed_blocks"] == [2, 3] and rec["replaced"] == row["replaced"]


def _assert_put_back(b, work, mp4, req, stand, outcome, says):
    before = _tree(work, mp4)
    row = _run(b, req, stand)["videos"][0]
    assert row["outcome"] == outcome, row
    assert says in (row["reason"] or ""), row
    assert row["changed_blocks"] == [] and row["replaced"] == []
    after = _tree(work, mp4)
    assert after == before, sorted(set(after) ^ set(before)) or \
        [k for k in after if after[k] != before[k]]
    assert not (work / "repair" / "after.mp4").exists()
    return row


def test_nothing_else_in_the_pool_is_no_replacement_and_put_back():
    b, work, mp4 = _batch()
    st = Stand(work, fail={"resolve_anchors.py": 1})
    _assert_put_back(b, work, mp4, _req([SHOT14]), st, "no_replacement", "resolve_anchors.py exit 1")
    assert st.tools() == ["resolve_anchors.py"]


def test_a_refused_plan_is_no_replacement_and_its_sidecar_goes():
    b, work, mp4 = _batch()
    st = Stand(work, fail={"build_render_plan.py": 2})
    _assert_put_back(b, work, mp4, _req([SHOT14]), st, "no_replacement", "the plan refused")
    assert not (work / "plan.refusal.json").exists()


def test_qc_failure_is_qc_failed_and_the_judged_mp4_stays():
    b, work, mp4 = _batch()
    st = Stand(work, qc={"passed": False, "failures": ["black run 1.2s at 14.0s"]})
    _assert_put_back(b, work, mp4, _req([SHOT14]), st, "qc_failed", "black run")
    assert "frame_judge_pack.py" not in st.tools()
    assert "write_batch_metadata.py" not in st.tools()


def test_cap_at_render_and_a_failed_pack_are_failed_and_put_back():
    b, work, mp4 = _batch()
    _assert_put_back(b, work, mp4, _req([SHOT14]), Stand(work, fail={"render_video.py": 3}),
                     "failed", "attempt cap")
    b, work, mp4 = _batch()
    _assert_put_back(b, work, mp4, _req([SHOT14]), Stand(work, fail={"render_video.py": 1}),
                     "render_failed", "exit 1")
    b, work, mp4 = _batch()
    _assert_put_back(b, work, mp4, _req([SHOT14]), Stand(work, fail={"frame_judge_pack.py": 1}),
                     "failed", "no pack")
    b, work, mp4 = _batch()
    _assert_put_back(b, work, mp4, _req([SHOT14]),
                     Stand(work, fail={"write_batch_metadata.py": 2}), "failed", "05 not rewritten")


def test_same_shot_again_is_no_replacement():
    b, work, mp4 = _batch()
    st = Stand(work, new_shot="c:3")
    _assert_put_back(b, work, mp4, _req([SHOT14]), st, "no_replacement", "still shows c:3")


def test_meme_target_is_taken_off_without_a_resolve():
    b, work, mp4 = _batch(meme_at=1)
    st = Stand(work)
    meme = {"block": 1, "entry": "block-1-meme", "target": "meme", "exclude_shot": None,
            "kind": "smeared", "why": "smeared", "start": 3.0, "end": 6.0}
    row = _run(b, _req([meme]), st)["videos"][0]
    assert row["outcome"] == "rendered", row
    assert row["replaced"] == [{"block": 1, "entry": "block-1-meme", "target": "meme",
                                "before": "smeared-cat", "after": None}]
    assert row["changed_blocks"] == [1]
    assert "resolve_anchors.py" not in st.tools() and "build_render_plan.py" not in st.tools()
    plan = json.loads((work / "plan.json").read_text())
    assert "insert" not in plan["blocks"][1]
    d = plan["meme"]["meme_delivered"][0]
    assert d["outcome"] == "no_asset" and d["withdrawn_by"] == "judge_repair" and d["reason"]
    assert plan["meme"]["inserts"] == []
    assert plan["judge_repair"]["memes_withdrawn"][0]["blocks"] == [1]


def test_shot_and_meme_together():
    b, work, mp4 = _batch(meme_at=4)
    st = Stand(work)
    meme = {"block": 4, "entry": "block-4-meme", "target": "meme", "exclude_shot": None,
            "kind": "smeared"}
    row = _run(b, _req([SHOT14, meme]), st)["videos"][0]
    assert row["outcome"] == "rendered", row
    assert row["changed_blocks"] == [2, 4]
    plan = json.loads((work / "plan.json").read_text())
    assert "insert" not in plan["blocks"][4] and plan["blocks"][2]["shot"] == "c:22"


def test_meme_in_a_hole_is_no_replacement_and_nothing_runs():
    b, work, mp4 = _batch(meme_at=1, hole=True)
    st = Stand(work)
    meme = {"block": 1, "entry": "block-1-meme", "target": "meme", "exclude_shot": None,
            "kind": "smeared"}
    before = _tree(work, mp4)
    row = _run(b, _req([meme]), st)["videos"][0]
    assert row["outcome"] == "no_replacement" and "hole" in row["reason"], row
    assert st.calls == [] and _tree(work, mp4) == before


def test_cap_reached_before_anything_runs_nothing():
    b, work, mp4 = _batch(ledger={
        "slug": SLUG, "attempts": [{"n": i, "result": "qc_failed", "kind": "attempt"}
                                   for i in (1, 2, 3)],
        "needs_you": None, "attempt_cap": 3, "cap_source": "test",
        "qc_degrade_cap": 3, "qc_degrade_cap_source": "test"})
    st = Stand(work)
    row = _run(b, _req([SHOT14]), st)["videos"][0]
    assert row["outcome"] == "failed" and "attempt cap" in row["reason"], row
    assert st.calls == [] and not (work / "repair").exists()


def test_plan_command_rebuilt_from_03_without_a_plan_check():
    b, work, mp4 = _batch(plan_check=False)
    (b / "03-content-researcher.json").write_text(json.dumps({
        "channel": "testchan", "scripts": [{
            "script_id": SID, "narration": {"estimated_seconds": 41.5},
            "anchor_coverage_pool": {"indexes": ["/pool/x.shots.json"]}}]}))
    argv = rb.plan_argv(b, work, SID, None, "/py")
    assert argv[:6] == ["/py", str(SCRIPTS / "build_render_plan.py"),
                        str(work / "storyboard.json"), str(work / "words.json"),
                        str(work / "voice.wav"), str(work / "plan.json")]
    assert argv[argv.index("--channel") + 1] == "testchan"
    assert argv[argv.index("--script-id") + 1] == SID
    assert argv[argv.index("--estimated-seconds") + 1] == "41.5"
    assert argv[argv.index("--index") + 1] == "/pool/x.shots.json"


def test_unanswerable_videos_get_failed_rows():
    b, work, mp4 = _batch()
    ghost = {"script_id": "ghost-script1", "slug": "ghost", "blocks": [SHOT14]}
    st = Stand(work)
    res = _run(b, _req([SHOT14], extra_videos=[ghost]), st)
    assert [r["outcome"] for r in res["videos"]] == ["rendered", "failed"]
    assert "holds no videos[] row" in res["videos"][1]["reason"]
    # a spent budget: nothing started, every video still answered
    b, work, mp4 = _batch()
    st = Stand(work)
    ticks = iter([0.0, 999.0, 999.0, 999.0])
    res = _run(b, _req([SHOT14], extra_videos=[ghost]), st, budget_s=10,
               clock=lambda: next(ticks))
    assert [r["outcome"] for r in res["videos"]] == ["failed", "failed"]
    assert all("time budget" in r["reason"] for r in res["videos"])
    assert st.calls == []


def test_a_bad_call_is_exit_2():
    b, work, mp4 = _batch()
    rq, rs = b / "work" / "repair-requests.json", b / "work" / "repair-results.json"
    for doc in ({"schema": "something-else/1", "videos": []},
                _req([{"block": 2, "target": "shot"}]),             # no exclude_shot
                _req([{"block": "2", "target": "meme"}])):
        rq.write_text(json.dumps(doc))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = rb.main([str(b), "--request", str(rq), "--result", str(rs)])
        assert code == 2 and "REPAIR: ERROR" in err.getvalue(), (doc, err.getvalue())
        assert not rs.exists()
    with contextlib.redirect_stderr(io.StringIO()):
        assert rb.main([str(b / "nope"), "--request", str(rq), "--result", str(rs)]) == 2


def test_empty_request_writes_an_empty_result():
    b, work, mp4 = _batch()
    req = _req([SHOT14])
    req["videos"] = []
    res = _run(b, req, Stand(work))
    assert res["videos"] == []


def test_the_root_reads_every_outcome():
    """The outcomes are the root's EDITOR_OUTCOMES (shared/judge_repair.py)
    minus its own `not_attempted`."""
    assert set(rb.OUTCOMES) == {"rendered", "no_replacement", "render_failed",
                                "qc_failed", "failed"}


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
