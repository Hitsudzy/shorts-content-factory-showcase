#!/usr/bin/env python3
"""CF-0787: the YouTube Search quota day (`shared/quota_day.py`) and the
day's earlier spend the executor hands the trend-hunter stage.

Every root is a synthetic tree in a temp dir; no batch runs, no `claude` is
started - the executor is built only to render its prompt.

What is pinned:

* a batch's own spend is the larger of its 01 (`spent_searches` minus
  `searches_before_stage`) and its run log's `youtube-api search` starts;
* `day_spend` sums the batches whose id starts in the quota day, the running
  batch, rebuilds and other quota days left out;
* the 17.10 scenario: with Science 2026-10-17T0817Z (66 calls) on disk, the
  trend-hunter stage of the Reel batch at 18.10 02:00 МСК is told 66 and to
  pass `--searches-spent 66`; the run-state records it; other stages are not
  told anything.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import quota_day as qd              # noqa: E402
import run_executor as rx           # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("quota-day-test-")
_n = [0]
SCI = "2026-10-17T0817Z"            # 17.10 11:17 МСК, quota day 17.10
REEL = "2026-10-17T2300Z"           # 18.10 02:00 МСК, quota day 17.10 too


def _root():
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    r.mkdir(parents=True)
    return r


def _batch(root, ch, bid, spent=None, before=0, searches_in_log=None, group=None):
    d = root / "pipeline" / (group or ch) / bid
    d.mkdir(parents=True)
    if spent is not None:
        (d / "01-trend-hunter.json").write_text(json.dumps(
            {"search_quota": {"spent_searches": spent, "searches_before_stage": before}}))
    if searches_in_log is not None:
        rows = [{"kind": "script", "status": "start", "id": "s1", "stage": "trend-hunter"}]
        rows += [{"kind": "child", "status": "start", "id": f"c{i}", "parent": "s1",
                  "tool": "youtube-api", "argv": ["youtube-api", "search"]}
                 for i in range(searches_in_log)]
        rows += [{"kind": "child", "status": "start", "id": "v1", "parent": "s1",
                  "tool": "youtube-api", "argv": ["youtube-api", "videos"]},
                 {"kind": "child", "status": "done", "id": "c0", "tool": "youtube-api",
                  "argv": ["youtube-api", "search"]}]
        (d / "RUN_EVENTS.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    return d


def _now(text):
    return rx.dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_a_batch_spend_is_the_larger_of_its_01_and_its_run_log():
    r = _root()
    assert qd.batch_searches(_batch(r, "a", "2026-10-17T0100Z", spent=66)) == (
        66, "01-trend-hunter.json -> search_quota")
    # what the batches before it spent is theirs, not this one's
    assert qd.batch_searches(_batch(r, "a", "2026-10-17T0200Z", spent=90, before=66))[0] == 24
    assert qd.batch_searches(_batch(r, "a", "2026-10-17T0300Z", spent=10,
                                    searches_in_log=20)) == (20, "RUN_EVENTS.jsonl")
    assert qd.batch_searches(_batch(r, "a", "2026-10-17T0400Z", searches_in_log=7))[0] == 7
    assert qd.batch_searches(_batch(r, "a", "2026-10-17T0500Z")) == (0, None)


def test_the_day_spend_counts_only_this_quota_days_batches_but_the_running_one():
    r = _root()
    _batch(r, "example-science", SCI, spent=66)
    reel = _batch(r, "example-film", REEL)                         # the running batch
    _batch(r, "example-film", "2026-10-16T2300Z", spent=68)        # quota day 16.10
    _batch(r, "example-film", "2026-10-18T0700Z", spent=50)        # quota day 18.10 (07:00Z)
    _batch(r, "example-film", "2026-10-17T1200Z", spent=40, group="rebuilds")
    _batch(r, "example-film", "2026-10-17T1300Z", spent=40, group="backfill")
    s = qd.day_spend(r, exclude=reel, now=_now("2026-10-17T23:05:00Z"))
    assert s["quota_day"] == "2026-10-17" and s["searches"] == 66, s
    assert s["batches"] == [{"batch": f"example-science/{SCI}", "searches": 66,
                             "source": "01-trend-hunter.json -> search_quota"}], s
    assert (s["start"], s["end"]) == ("2026-10-17T07:00:00Z", "2026-10-18T07:00:00Z"), s
    # the running batch counts for the next one of the day
    assert qd.day_spend(r, now=_now("2026-10-17T23:05:00Z"))["searches"] == 66
    assert qd.day_spend(r, now=_now("2026-10-18T07:30:00Z"))["searches"] == 50


def _executor(root, batch, now):
    plan = {"stages": [
        {"id": "trend-hunter", "title": "Trend Hunter", "kind": "llm", "owner": "trend-hunter",
         "marker": "trend-hunter", "marker_by": "skill",
         "skill": "agents/trend-hunter/.claude/skills/trend-hunter/SKILL.md",
         "args": {"channel": "{channel}", "batch": "{batch}"}},
        {"id": "video-editor", "title": "Video Editor", "kind": "llm", "owner": "video-editor",
         "after": ["trend-hunter"], "skill": "agents/video-editor/SKILL.md", "args": {}}]}
    state = {"stages": {}, "runs": {}}
    return rx.Executor(root, "example-film", plan, batch, state, claude="/bin/false",
                       out=lambda *_: None, clock=lambda: _now(now)), state


def test_the_trend_hunter_stage_is_told_the_days_earlier_spend():
    """17.10: the Reel batch at 18.10 02:00 МСК, had the plan let it start, is
    told the 66 Science spent - no person passes `--searches-spent`."""
    r = _root()
    _batch(r, "example-science", SCI, spent=66)
    reel = _batch(r, "example-film", REEL)
    ex, state = _executor(r, reel, "2026-10-17T23:05:00Z")
    text = ex.prompt(ex.by_id["trend-hunter"])
    assert "  searches_spent: 66" in text, text
    assert "--searches-spent 66" in text and f"example-science/{SCI} 66" in text, text
    assert "already spent 66 of its 100" in text and "2026-10-17" in text, text
    rec = state["stages"]["trend-hunter"]["searches_before_stage"]
    assert rec["searches"] == 66 and rec["quota_day"] == "2026-10-17", rec
    assert "searches_spent" not in ex.prompt(ex.by_id["video-editor"])
    # the first batch of a quota day is told 0, in so many words
    ex2, _ = _executor(r, reel, "2026-10-18T08:00:00Z")
    t2 = ex2.prompt(ex2.by_id["trend-hunter"])
    assert "--searches-spent 0" in t2 and "no other batch of this quota day" in t2, t2


if __name__ == "__main__":
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
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:400]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
