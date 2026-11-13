#!/usr/bin/env python3
"""CF-0800: `scripts/merge_verdicts.py` - the second pass over the scripts
judges only the new ones and merges them into `04`; every verdict already in
`04` keeps its bytes, and an attempt to change one is refused.

Offline: a synthetic batch under a temp root (03, 04, 01b, a staging file),
RUNLOG_BATCH only where a test sets it to its own temp batch. Seconds.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cc-merge-verdicts-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import merge_verdicts as mv  # noqa: E402

PY = sys.executable
BATCH_ID = "2026-10-18T0841Z"
CHANNEL = "example-film"


def _row(sid, tid, verdict="clear", contribution="pass"):
    """The shape of a real `04` row (example-film/2026-10-18T0841Z), non-ASCII
    included - `04` is written with ensure_ascii=False."""
    return {
        "script_id": sid, "topic_id": tid, "verdict": verdict,
        "rights_holder_check": {"matched": None, "risk_level": None,
                                "reason": "title_ref.rights_holder is null — nothing guessed.",
                                "affects_verdict": False, "task": "CF-0420"},
        "content_sensitivity_check": {"flagged": False, "notes": "box office — no tragedy"},
        "contribution_check": {"verdict": contribution, "judged": True,
                               "checked_against": "channels/example-film/stance.json (CF-0181)",
                               "compared_against": ["01-trend-hunter.json topic " + tid],
                               "failures": [], "reason": None, "note": None},
        "claims_gate": {"rule": "CF-0553", "action": "pass", "codes": [], "struck": [],
                        "undeclared": [], "asked": 0, "cached": 10, "opinion_calls": 0,
                        "model": "sonnet"},
    }


def _head(results):
    return {"batch_id": BATCH_ID, "channel": CHANNEL, "stage_checked": "03-content-researcher",
            "checked_at": "2026-10-18T16:36:13Z",
            "disclaimer": "Heuristic first-pass screen, not legal advice.",
            "results": results}


def _batch(n_scripts=3, judged=2):
    b = Path(tempfile.mkdtemp(dir=TMP)) / BATCH_ID
    b.mkdir()
    scripts = [{"script_id": f"t{i}-script1", "topic_id": f"t{i}"} for i in range(1, n_scripts + 1)]
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": BATCH_ID, "channel": CHANNEL, "scripts": scripts}))
    rows = [_row(s["script_id"], s["topic_id"]) for s in scripts[:judged]]
    (b / mv.VERDICTS_FILE).write_text(mv._dump(_head(rows)), encoding="utf-8")
    (b / "01b-footage-index.json").write_text(json.dumps({"reserve_substitution": {
        "task": "CF-0306", "substitutions": [
            {"replaced": "t2", "replaced_reason_code": "frame_judge_refused",
             "replaced_stage": "frame-judge", "topic_id": "t3",
             "reason_code": "reserve_substituted", "at": "frame_judge_refusal"}]}}))
    return b


def _stage(b, rows, **head):
    doc = _head(rows)
    doc.update(head)
    p = b / mv.STAGING_NAME
    p.write_text(mv._dump(doc), encoding="utf-8")
    return p


def _results_block(text):
    """The text of `results[]`'s rows, as written."""
    start = text.index('"results": [') + len('"results": [')
    end = text.index("\n  ]", start)
    return text[start:end]


def _run(*args, batch=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    if batch is not None:
        env["RUNLOG_BATCH"] = str(batch)
    return subprocess.run([PY, str(SCRIPTS / "merge_verdicts.py"), *map(str, args)], env=env,
                          cwd=str(TMP), capture_output=True, text=True, timeout=60)


def _quiet(*_a, **_k):
    pass


# --------------------------------------------------------------------------

def test_pending_lists_the_scripts_without_a_verdict_in_03_order():
    b = _batch(n_scripts=4, judged=2)
    assert mv.pending(b / mv.VERDICTS_FILE) == ["t3-script1", "t4-script1"]
    cp = _run("pending", b / mv.VERDICTS_FILE)
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.split() == ["t3-script1", "t4-script1"], cp.stdout


def test_pending_is_empty_when_every_script_is_judged():
    b = _batch(n_scripts=2, judged=2)
    cp = _run("pending", b / mv.VERDICTS_FILE)
    assert cp.returncode == 0 and cp.stdout == "", (cp.stdout, cp.stderr)


def test_merge_appends_the_new_verdict_and_keeps_the_old_bytes():
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before_text = p04.read_text(encoding="utf-8")
    before = json.loads(before_text)
    staging = _stage(b, [_row("t3-script1", "t3", verdict="caution")])
    added = mv.merge(p04, staging, out=_quiet, when="2026-10-18T20:00:00Z")
    assert [a["script_id"] for a in added] == ["t3-script1"]
    after_text = p04.read_text(encoding="utf-8")
    after = json.loads(after_text)
    # the old rows: same values, same bytes, same place
    assert after["results"][:2] == before["results"]
    assert after_text.startswith(before_text[:before_text.index("\n  ]")])
    assert _results_block(after_text).startswith(_results_block(before_text) + ",")
    # the top level of the first pass is untouched
    for k in ("batch_id", "channel", "stage_checked", "checked_at", "disclaimer"):
        assert after[k] == before[k], k
    assert after["results"][2]["script_id"] == "t3-script1"
    assert after["results"][2]["verdict"] == "caution"
    rec, = after[mv.MERGES_KEY]
    assert rec["task"] == "CF-0800" and rec["mode"] == "new-only"
    assert rec["at"] == "2026-10-18T20:00:00Z"
    assert rec["reason"] == mv.DEFAULT_REASON == "after frame judge reserve"
    assert rec["results_before"] == 2 and rec["results_after"] == 3
    assert rec["blocked_added"] == 0
    a, = rec["added"]
    assert a["script_id"] == "t3-script1" and a["verdict"] == "caution"
    assert a["substitution"]["at"] == "frame_judge_refusal"
    assert a["substitution"]["replaced"] == "t2"
    assert not staging.exists(), "the consumed staging file is removed"


def test_a_second_merge_keeps_the_first_merge_and_its_rows():
    b = _batch(n_scripts=4, judged=2)
    p04 = b / mv.VERDICTS_FILE
    mv.merge(p04, _stage(b, [_row("t3-script1", "t3")]), out=_quiet)
    mid_text = p04.read_text(encoding="utf-8")
    mid = json.loads(mid_text)
    mv.merge(p04, _stage(b, [_row("t4-script1", "t4", contribution="block")]),
             reason="after frame judge reserve, round 2", out=_quiet)
    after_text = p04.read_text(encoding="utf-8")
    after = json.loads(after_text)
    assert after["results"][:3] == mid["results"]
    assert _results_block(after_text).startswith(_results_block(mid_text) + ",")
    assert len(after[mv.MERGES_KEY]) == 2
    assert after[mv.MERGES_KEY][0] == mid[mv.MERGES_KEY][0]
    second = after[mv.MERGES_KEY][1]
    assert second["reason"] == "after frame judge reserve, round 2"
    assert second["blocked_added"] == 1 and second["added"][0]["substitution"] is None
    assert mv.note_line(after) == "4 verdicts, 1 blocked (after 03-content-researcher)"


def test_an_existing_verdict_in_the_new_set_is_refused_and_nothing_written():
    """Refused, not skipped: the whole merge, even beside a legitimate new row."""
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before = p04.read_bytes()
    changed = _row("t1-script1", "t1", verdict="review")
    staging = _stage(b, [_row("t3-script1", "t3"), changed])
    try:
        mv.merge(p04, staging, out=_quiet)
    except mv.Refused as exc:
        assert "t1-script1" in str(exc) and "never changes" in str(exc), exc
    else:
        raise AssertionError("a changed verdict was merged")
    assert p04.read_bytes() == before
    assert staging.exists(), "a refused staging file is left for the report"
    cp = _run("merge", p04, staging)
    assert cp.returncode == 2 and "refused" in cp.stderr, (cp.returncode, cp.stderr)
    assert p04.read_bytes() == before


def test_an_identical_copy_of_an_existing_verdict_is_refused_too():
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before = p04.read_bytes()
    same = copy.deepcopy(json.loads(before)["results"][0])
    cp = _run("merge", p04, _stage(b, [same]))
    assert cp.returncode == 2, cp.stderr
    assert p04.read_bytes() == before


def test_rows_that_are_not_new_scripts_of_this_batch_are_refused():
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before = p04.read_bytes()
    cases = [
        ([_row("t9-script1", "t9")], {}),                                  # not in 03
        ([_row("t3-script1", "t3"), _row("t3-script1", "t3")], {}),         # duplicate
        ([{"topic_id": "t3", "verdict": "clear"}], {}),                     # no script_id
        ([{"script_id": "t3-script1", "topic_id": "t3"}], {}),              # no verdict
        ([_row("t3-script1", "t3")], {"batch_id": "2026-10-17T0817Z"}),     # another batch
        ([_row("t3-script1", "t3")], {"stage_checked": "01-trend-hunter"}), # another pass
        ([_row("t3-script1", "t3")], {"channel": "example-tech"}),           # another channel
    ]
    for rows, head in cases:
        staging = _stage(b, rows, **head)
        cp = _run("merge", p04, staging)
        assert cp.returncode == 2, (rows, head, cp.stdout, cp.stderr)
        assert "refused" in cp.stderr and "Traceback" not in cp.stderr, cp.stderr
        assert p04.read_bytes() == before, (rows, head)


def test_an_empty_new_set_is_a_no_op():
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before = p04.read_bytes()
    staging = _stage(b, [])
    cp = _run("merge", p04, staging)
    assert cp.returncode == 0, cp.stderr
    assert "not touched" in cp.stdout, cp.stdout
    assert p04.read_bytes() == before
    assert mv.MERGES_KEY not in json.loads(before)


def test_dry_run_and_keep():
    b = _batch()
    p04 = b / mv.VERDICTS_FILE
    before = p04.read_bytes()
    staging = _stage(b, [_row("t3-script1", "t3")])
    cp = _run("merge", p04, staging, "--dry-run")
    assert cp.returncode == 0 and "dry run" in cp.stdout, (cp.stdout, cp.stderr)
    assert p04.read_bytes() == before and staging.exists()
    cp = _run("merge", p04, staging, "--keep", "--reason", "a reason of my own")
    assert cp.returncode == 0, cp.stderr
    assert staging.exists()
    assert json.loads(p04.read_text())[mv.MERGES_KEY][0]["reason"] == "a reason of my own"
    assert "note: 3 verdicts, 0 blocked" in cp.stdout, cp.stdout


def test_no_04_means_no_first_pass_and_is_refused():
    b = _batch()
    (b / mv.VERDICTS_FILE).unlink()
    staging = _stage(b, [_row("t3-script1", "t3")])
    cp = _run("merge", b / mv.VERDICTS_FILE, staging)
    assert cp.returncode == 2 and "full pass" in cp.stderr, cp.stderr
    assert not (b / mv.VERDICTS_FILE).exists()
    assert _run("pending", b / mv.VERDICTS_FILE).returncode == 2


def test_merge_events_land_in_the_batch_run_log():
    b = _batch()
    staging = _stage(b, [_row("t3-script1", "t3")])
    cp = _run("merge", b / mv.VERDICTS_FILE, staging, batch=b)
    assert cp.returncode == 0, cp.stderr
    events = [json.loads(line) for line in
              (b / "RUN_EVENTS.jsonl").read_text().splitlines() if line.strip()]
    mine = [e for e in events if e.get("step") == "merge-verdicts"]
    assert [e["status"] for e in mine] == ["start", "done"], events
    assert all(e.get("stage") == "compliance-checker" for e in mine), mine


def test_the_full_pass_is_unchanged_and_the_skill_names_the_merge():
    """The default pass still writes 04 whole; the new-only pass is the merge."""
    skill = (HERE.parent / ".claude" / "skills" / "compliance-checker" / "SKILL.md").read_text()
    assert "written to `04-compliance-checker.json`" in skill
    assert "merge_verdicts.py" in skill and "pending" in skill
    assert mv.STAGING_NAME in skill
    assert "new-only" in skill


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
