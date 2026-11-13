#!/usr/bin/env python3
"""CF-0806: a topic kept on own graphics is not refused for want of a pool.

`example-tech/2026-10-19T0844Z`: the Footage Indexer kept 004 (no source, 38
quotable facts) and 005 (one 9 s source, 215 facts) on own graphics
(`01b-footage-index.json -> own_graphic_footing.kept[]`, CF-0689), and the
writer refused them anyway - 004 as `nothing_to_check`, 005 as `thin_scene`.
Pinned here:

* `scripts/check_own_graphic_skips.py` refuses `nothing_to_check` and
  `thin_scene` for a kept topic (both places the indexer writes the list),
  lets the cadence gate's own `thin_scene` (with its `anchor_cadence`
  record) through, leaves a topic that is not kept exactly as before, and
  keeps every other code (`claim_unsupported`, `no_fact`, ...) open for a
  kept topic;
* `scripts/merge_batch_file.py` refuses such a fragment and writes nothing;
* SKILL.md says so in step 2 and names the check.

Stand-ins in a temp directory - no pipeline, no pool, no network.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-og-skips-")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import check_own_graphic_skips as ogs  # noqa: E402
import merge_batch_file as mbf  # noqa: E402
import _own_graphic as ogl  # noqa: E402

SKILL = (REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
README = (REPO / "README.md").read_text()

KEPT, KEPT_FLOOR, PLAIN = "tech-004", "tech-009", "tech-006"


def _index():
    return {
        "sources_by_topic": {PLAIN: ["aaa", "bbb"]},
        "own_graphic_footing": {
            "origin": "own_graphic",
            "kept": [{"topic_id": KEPT, "note": "kept on own graphics",
                      "origin": "own_graphic", "sources": [], "quotable_facts": 38,
                      "floor": 3}]},
        "two_source_floor": {"kept_on_own_graphics": [KEPT_FLOOR]},
    }


def _skip(topic, code, **extra):
    return dict({"topic_id": topic, "reason_code": code, "stage": "scripts",
                 "reason": "a sentence", "checked": []}, **extra)


def _batch(*skipped):
    return {"batch_id": "b-1", "channel": "example-tech", "scripts": [],
            "skipped": list(skipped), "warnings": []}


def _dir(index=True):
    # under pipeline/<channel>/<batch-id>/: where merge_batch_file.py writes (CF-0907)
    d = Path(tempfile.mkdtemp(dir=_TMP)) / "pipeline" / "example-tech" / "2026-10-19T0844Z"
    d.mkdir(parents=True)
    if index:
        (d / ogs.FOOTAGE_INDEX_NAME).write_text(json.dumps(_index()))
    return d


def _run(batch, index=True):
    d = _dir(index)
    path = d / "03-content-researcher.json"
    path.write_text(json.dumps(batch))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = ogs.main([str(path)])
    return code, out.getvalue()


def test_the_kept_list_is_read_from_both_places():
    kept = ogl.kept_on_own_graphics(_index())
    assert set(kept) == {KEPT, KEPT_FLOOR}, kept
    assert kept[KEPT]["quotable_facts"] == 38
    assert ogl.kept_on_own_graphics(None) == {} and ogl.kept_on_own_graphics({}) == {}


def test_kept_topic_refused_as_nothing_to_check_is_refused():
    code, out = _run(_batch(_skip(KEPT, "nothing_to_check")))
    assert code == 1, out
    assert "FAIL" in out and KEPT in out and "CF-0806" in out and "nothing_to_check" in out


def test_kept_topic_refused_as_thin_scene_is_refused():
    code, out = _run(_batch(_skip(KEPT, "thin_scene")))
    assert code == 1, out
    assert KEPT in out and "thin_scene" in out


def test_topic_kept_by_the_floor_list_is_held_too():
    code, out = _run(_batch(_skip(KEPT_FLOOR, "thin_scene")))
    assert code == 1 and KEPT_FLOOR in out, out


def test_not_kept_topic_may_still_be_thin_scene():
    code, out = _run(_batch(_skip(PLAIN, "thin_scene"), _skip(PLAIN + "x", "nothing_to_check")))
    assert code == 0 and "ok" in out, out


def test_kept_topic_may_be_refused_on_its_facts():
    for c in ("claim_unsupported", "no_fact", "story_claim_failed", "scale_unsupported",
              "held_back"):
        code, out = _run(_batch(_skip(KEPT, c)))
        assert code == 0, (c, out)


def test_the_cadence_gates_own_thin_scene_stays_open():
    entry = _skip(KEPT, "thin_scene", anchor_cadence={"failed_attempts": 2})
    code, out = _run(_batch(entry))
    assert code == 0, out


def test_no_index_beside_the_file_keeps_nothing():
    code, out = _run(_batch(_skip(KEPT, "nothing_to_check")), index=False)
    assert code == 0 and "none" in out, out


def test_an_unreadable_index_is_usage_not_a_pass():
    d = _dir(index=False)
    (d / ogs.FOOTAGE_INDEX_NAME).write_text("{not json")
    path = d / "03-content-researcher.json"
    path.write_text(json.dumps(_batch()))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert ogs.main([str(path)]) == 2


def test_merge_refuses_such_a_fragment_and_writes_nothing():
    d = _dir()
    path = d / "03-content-researcher.json"
    before = json.dumps(_batch(_skip(PLAIN, "thin_scene")))
    path.write_text(before)
    frag = d / "fragment.json"
    frag.write_text(json.dumps(_batch(_skip(KEPT_FLOOR, "nothing_to_check"))))
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = mbf.main([str(path), "--add", str(frag)])
    assert code == 2 and "CF-0806" in err.getvalue(), err.getvalue()
    assert path.read_text() == before


def test_merge_takes_a_fact_refusal_of_a_kept_topic():
    d = _dir()
    path = d / "03-content-researcher.json"
    frag = d / "fragment.json"
    frag.write_text(json.dumps(_batch(_skip(KEPT, "claim_unsupported"))))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert mbf.main([str(path), "--add", str(frag)]) == 0
    assert json.loads(path.read_text())["skipped"][0]["reason_code"] == "claim_unsupported"


def test_the_skill_and_readme_say_so():
    assert "check_own_graphic_skips.py" in SKILL and "CF-0806" in SKILL
    assert "own_graphic_footing.kept[]" in SKILL
    assert "check_own_graphic_skips.py" in README


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
