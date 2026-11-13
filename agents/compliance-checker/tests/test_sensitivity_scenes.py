#!/usr/bin/env python3
"""CF-0846: `scripts/sensitivity_scenes.py` - a content-sensitivity flag of the
shortlist pass names the scene(s) it rests on, and a missing field never reads
as "another scene".

The case: `example-film/2026-10-21T0837Z`, topic `lf-2026-10-21-006` (The
Daily Show) - flagged on scene 2 (Stewart's joke turning on Vance, Trump,
Macron), scene 1 harmless; the script took scene 1 and the hold still waited
for a signature. The topic below is a stand-in of that shape, nothing is read
from the live batch.

Offline: synthetic batch files under a temp root, RUNLOG_BATCH only where a
test sets it to its own temp batch. Seconds.
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
SKILL = HERE.parent / ".claude" / "skills" / "compliance-checker" / "SKILL.md"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cc-sensitivity-scenes-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import sensitivity_scenes as ss  # noqa: E402
import publication_hold as ph  # noqa: E402
import cut_shortlist as cs  # noqa: E402
import rights_holder_info as rhi  # noqa: E402

PY = sys.executable
TID = "lf-2026-10-21-006"
S1, S2 = f"{TID}-s1", f"{TID}-s2"
OTHER = "lf-2026-10-21-002"


def _stage_doc():
    return {"batch_id": "2026-10-21T0837Z", "channel": "example-film", "topics": [
        {"topic_id": TID, "title_ref": {"name": "The Daily Show", "rights_holder": None},
         "scenes": [
             {"scene_id": S1, "description": "Stewart stays host through 2028."},
             {"scene_id": S2, "description": "Stewart jokes about Skydance, then "
                                             "turns on Vance, Trump and Macron."}]},
        {"topic_id": OTHER, "title_ref": {"name": "Other", "rights_holder": None},
         "scenes": [{"scene_id": f"{OTHER}-s1", "description": "box office"}]},
    ]}


def _check(scenes="<absent>", flagged=True):
    out = {"flagged": flagged,
           "notes": "Real political flashpoint: scene 2 puts sitting politicians "
                    "at the centre. Scene 1 is harmless on its own."}
    if scenes != "<absent>":
        out["scenes"] = scenes
    return out


def _doc(scenes="<absent>", where="results"):
    held = {"topic_id": TID, "verdict": "review",
            "rights_holder_check": {"matched": False, "risk_level": None,
                                    "reason": "rights_holder is null",
                                    "affects_verdict": False},
            "content_sensitivity_check": _check(scenes)}
    clear = {"topic_id": OTHER, "verdict": "clear",
             "rights_holder_check": {"matched": False, "affects_verdict": False},
             "content_sensitivity_check": {"flagged": False, "notes": "box office"}}
    doc = {"batch_id": "2026-10-21T0837Z", "channel": "example-film",
           "stage_checked": "01-trend-hunter", "checked_at": "2026-10-21T08:47:54Z",
           "results": [clear], "reserve": []}
    doc[where].append(held)
    return doc


def _batch(doc, stage_doc=None):
    b = Path(tempfile.mkdtemp(dir=TMP))
    (b / "02-compliance-checker.json").write_text(json.dumps(doc, ensure_ascii=False))
    (b / "01-trend-hunter.json").write_text(json.dumps(stage_doc or _stage_doc()))
    return b


def _run(*args, batch=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    if batch is not None:
        env["RUNLOG_BATCH"] = str(batch)
    return subprocess.run([PY, str(SCRIPTS / "sensitivity_scenes.py"), *args], env=env,
                          cwd=str(TMP), capture_output=True, text=True, timeout=60)


# --------------------------------------------------------------------------
# reading the field: only a clean list ties a flag to scenes
# --------------------------------------------------------------------------
def test_anything_but_a_clean_list_reads_as_the_whole_topic():
    for scenes in ("<absent>", None, [], "whole_topic", "", S2, [""], [None],
                   [S2, 3], {"s": S2}):
        assert ss.flagged_scenes(_check(scenes)) is None, scenes
    assert ss.flagged_scenes(None) is None
    assert ss.flagged_scenes(_check([S2])) == frozenset({S2})
    assert ss.flagged_scenes(_check([f" {S2} ", S1])) == frozenset({S1, S2})


def test_the_case_of_21_10_the_script_on_scene_1_is_spared():
    assert ss.spares_scene(_check([S2]), S1) is True
    assert ss.spares_scene(_check([S2]), S1, topic_scene_ids=[S1, S2]) is True


def test_the_flagged_scene_and_every_doubt_keep_the_hold():
    assert ss.spares_scene(_check([S2]), S2) is False                 # the flagged scene
    assert ss.spares_scene(_check([S1, S2]), S1) is False
    assert ss.spares_scene(_check(), S1) is False                     # file before CF-0846
    assert ss.spares_scene(_check(None), S1) is False
    assert ss.spares_scene(_check([]), S1) is False
    assert ss.spares_scene(_check("whole_topic"), S1) is False
    assert ss.spares_scene(_check([S2]), None) is False               # no scene_id in 03
    assert ss.spares_scene(_check([S2]), "  ") is False
    assert ss.spares_scene(_check([S2]), f"{TID}-s9",
                           topic_scene_ids=[S1, S2]) is False         # a scene nobody judged
    assert ss.spares_scene(_check([S2], flagged=False), S1) is False  # no flag, not this rule
    assert ss.spares_scene(None, S1) is False


def test_a_hold_is_spared_only_when_the_shortlist_pass_raised_it():
    row = {"stage_checked": "01-trend-hunter", "content_sensitivity_check": _check([S2])}
    spared, reason = ss.hold_spared_by_scene(row, S1, [S1, S2])
    assert spared and ss.RESOLVED_REASON_CODE in reason and S2 in reason, reason
    spared, reason = ss.hold_spared_by_scene(row, S2)
    assert not spared and "flagged scene" in reason, reason
    for stage in ("03-content-researcher", None):
        spared, reason = ss.hold_spared_by_scene(dict(row, stage_checked=stage), S1)
        assert not spared and "shortlist pass" in reason, reason
    old = {"stage_checked": "01-trend-hunter", "content_sensitivity_check": _check()}
    spared, reason = ss.hold_spared_by_scene(old, S1)
    assert not spared and "whole topic" in reason, reason
    assert ss.hold_spared_by_scene(None, S1)[0] is False
    assert ss.RESOLVED_REASON_CODE == "flagged_scene_not_in_script"


# --------------------------------------------------------------------------
# the check the pass runs (step 4a)
# --------------------------------------------------------------------------
def test_check_document_accepts_a_list_of_the_topics_scenes_or_whole_topic():
    for scenes in ([S2], [S1, S2], "whole_topic"):
        rows = ss.check_document(_doc(scenes), _stage_doc())
        assert [(r[0], r[3]) for r in rows] == [(TID, None)], (scenes, rows)


def test_check_document_names_every_flagged_row_without_valid_scenes():
    for scenes in ("<absent>", None, [], "all", [f"{TID}-s9"], [f"{OTHER}-s1"],
                   [S2, S2], [""]):
        rows = ss.check_document(_doc(scenes), _stage_doc())
        assert len(rows) == 1 and rows[0][0] == TID and rows[0][3], (scenes, rows)


def test_a_topic_without_scene_ids_takes_only_whole_topic():
    stage = _stage_doc()
    stage["topics"][0]["scenes"] = [{"description": "no id"}]
    assert ss.check_document(_doc("whole_topic"), stage)[0][3] is None
    assert ss.check_document(_doc([S2]), stage)[0][3]


def test_reserve_rows_are_checked_and_unflagged_rows_are_not():
    rows = ss.check_document(_doc(where="reserve"), _stage_doc())
    assert [r[0] for r in rows] == [TID] and rows[0][3]
    doc = _doc([S2])
    doc["results"][0]["content_sensitivity_check"]["scenes"] = "anything"
    assert [r[0] for r in ss.check_document(doc, _stage_doc())] == [TID]


def test_the_cli_exits_1_on_a_missing_field_and_0_once_it_is_written():
    b = _batch(_doc())
    cp = _run(str(b / "02-compliance-checker.json"), batch=b)
    assert cp.returncode == 1 and f"{TID}: MISSING" in cp.stdout, cp.stdout + cp.stderr
    events = [json.loads(line) for line in
              (b / "RUN_EVENTS.jsonl").read_text().splitlines() if line.strip()]
    mine = [e for e in events if e.get("step") == "sensitivity-scenes"]
    assert [e["status"] for e in mine] == ["start", "failed"], events
    assert all(e.get("stage") == "compliance-checker" for e in mine), mine

    b = _batch(_doc([S2]))
    cp = _run(str(b / "02-compliance-checker.json"), str(b / "01-trend-hunter.json"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "1 tied to scenes, 0 whole topic, 0 without" in cp.stdout, cp.stdout
    before = (b / "02-compliance-checker.json").read_bytes()
    assert _run(str(b / "02-compliance-checker.json")).returncode == 0
    assert (b / "02-compliance-checker.json").read_bytes() == before  # writes nothing


def test_the_cli_refuses_the_scripts_pass_and_answers_help():
    doc = _doc([S2])
    doc["stage_checked"] = "03-content-researcher"
    b = _batch(doc)
    cp = _run(str(b / "02-compliance-checker.json"))
    assert cp.returncode == 2 and "refusing" in cp.stdout, cp.stdout
    cp = _run("--help")
    assert cp.returncode == 0 and "usage: sensitivity_scenes.py" in cp.stdout
    assert _run().returncode == 2
    assert _run(str(TMP / "nope.json")).returncode == 2


# --------------------------------------------------------------------------
# the field survives the rest of the pass and reaches the ledger
# --------------------------------------------------------------------------
def test_the_field_survives_4b_4c_and_reaches_the_ledger_row():
    doc = _doc([S2])
    empty_root = Path(tempfile.mkdtemp(dir=TMP))
    out, _, _ = rhi.decouple_document_full(copy.deepcopy(doc), root=str(empty_root))
    out, _, _ = cs.cut_document(out, _stage_doc(), 5, "test")
    held = [r for r in out["results"] + out["reserve"] if r["topic_id"] == TID]
    assert held and held[0]["content_sensitivity_check"]["scenes"] == [S2], held
    marked, held_ids, _ = ph.mark_document(out)
    assert held_ids == [TID]
    rows = ph.hold_rows(marked)
    assert len(rows) == 1 and rows[0]["stage_checked"] == "01-trend-hunter"
    assert rows[0]["content_sensitivity_check"]["scenes"] == [S2]
    assert ss.hold_spared_by_scene(rows[0], S1, [S1, S2])[0] is True
    assert ss.hold_spared_by_scene(rows[0], S2, [S1, S2])[0] is False


def test_the_skill_writes_the_field_and_runs_the_check():
    text = SKILL.read_text()
    assert "sensitivity_scenes.py" in text and "4a." in text
    start = text.index("**Write output.**")
    block = text[start:text.index("```", text.index("```json", start) + 7)]
    assert '"scenes"' in block and "whole_topic" in block, block
    assert ss.RESOLVED_REASON_CODE in text and "CF-0846" in text


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
