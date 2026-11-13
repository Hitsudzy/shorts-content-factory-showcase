#!/usr/bin/env python3
"""CF-0846: a publication hold whose flags all rest on a scene the script did
not take lifts itself (`shared/runlog/scene_holds.py`, `runlog scene-holds`,
the plan's close stage `scene-holds`).

21.10 `example-film/2026-10-21T0837Z`, topic `lf-2026-10-21-006`: the shortlist
pass flagged scene 2 (sitting politicians), the script took scene 1, and the hold
still waited for the user's signature. What is pinned, on temp roots only (a
synthetic ledger and batch; the agent's real `sensitivity_scenes.py` and
`publication_hold.py` from this checkout; the notification through a stand-in):

* flag on scene 2, script on scene 1 -> lifted: `resolved_at`,
  `resolved_reason` starting with `flagged_scene_not_in_script`,
  `resolved_reason_code`, `scene_release` naming the script's scene; no
  signature; one line to the user; a second run changes and sends nothing;
* flag on scene 1 (the chosen one) -> held; flag without scenes, `"whole_topic"`,
  the scripts pass's hold, two scripts one of which is on the flagged scene -> held;
* a hold this rule lifted is put back when a later script takes the flagged
  scene; a row the pass raised again carries no leftover of the old release;
* signed rows, rows resolved by anything else, other batches: untouched;
* an agent checkout without the module, an unreadable ledger: nothing lifted.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import scene_holds as sh          # noqa: E402

from _tmproot import tmp_root     # noqa: E402

TMP = tmp_root("scene-holds-test-")
_n = [0]
CH, BID, TOPIC = "example-film", "2026-10-21T0837Z", "lf-2026-10-21-006"
S1, S2 = f"{TOPIC}-s1", f"{TOPIC}-s2"


def hold(scenes="absent", stage="01-trend-hunter", topic=TOPIC, batch=BID, **extra):
    check = {"flagged": True, "notes": "scene 2 puts sitting politicians at the centre"}
    if scenes != "absent":
        check["scenes"] = scenes
    row = {"hold_id": f"{CH}/{batch}/{topic}", "channel": CH, "batch_id": batch,
           "topic_id": topic, "script_id": None, "verdict": "review", "stage_checked": stage,
           "found_in": "reserve", "raised_by": "compliance-checker",
           "raised_at": "2026-10-21T08:47:57Z", "task": "CF-0318", "blocks": "publication",
           "blocks_production": False, "reason_code": "compliance_review_hold",
           "reason": "held", "rights_holder_check": None, "content_sensitivity_check": check,
           "batch_artifact": f"pipeline/{CH}/{batch}/02-compliance-checker.json",
           "resolved_at": None, "resolved_reason": None, "signature": None}
    row.update(extra)
    return row


def factory(rows, script_scenes=(S1,), topics=None):
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    b = r / "pipeline" / CH / BID
    b.mkdir(parents=True)
    (r / "publish").mkdir()
    (r / "publish" / "publication-holds.json").write_text(
        json.dumps({"note": "n", "task": "CF-0318", "holds": rows}, indent=2) + "\n")
    topics = topics or [{"topic_id": TOPIC, "scenes": [{"scene_id": S1}, {"scene_id": S2}]}]
    (b / "01-trend-hunter.json").write_text(json.dumps({"batch_id": BID, "channel": CH,
                                                        "topics": topics}))
    write_scripts(b, script_scenes)
    return r, b


def write_scripts(b, script_scenes, topic=TOPIC):
    scripts = [{"script_id": f"{topic}-script{i + 1}", "topic_id": topic, "scene_id": sc}
               for i, sc in enumerate(script_scenes)]
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": BID, "channel": CH, "scripts": scripts}))


class Sent(list):
    def __call__(self, channel, row, info, root):
        self.append(sh.notify_text(channel, row, info))
        return {"status": "sent"}


def ledger(r):
    return json.loads((r / "publish" / "publication-holds.json").read_text())["holds"]


def run(r, b, **kw):
    sent = kw.pop("send", None) or Sent()
    rep = sh.run(b, root=r, send=sent, when="2026-10-21T21:00:00Z", **kw)
    return rep, sent


def _ph():
    _, ph, problem = sh.agent_modules()
    assert problem is None, problem
    return ph


def test_flag_on_scene_2_script_on_scene_1_lifts_the_hold():
    r, b = factory([hold(scenes=[S2])])
    rep, sent = run(r, b)
    assert rep["ok"] and rep["lifted"] == [f"{CH}/{BID}/{TOPIC}"], rep
    row = ledger(r)[0]
    assert row["resolved_at"] == "2026-10-21T21:00:00Z"
    assert row["resolved_reason"].startswith("flagged_scene_not_in_script"), row
    assert S1 in row["resolved_reason"] and S2 in row["resolved_reason"]
    assert row["resolved_reason_code"] == "flagged_scene_not_in_script"
    rel = row["scene_release"]
    assert rel["script_scenes"] == [S1] and rel["flagged_scenes"] == [S2], rel
    assert rel["scripts"] == [f"{TOPIC}-script1"] and rel["task"] == "CF-0846"
    assert row["signature"] is None, "no signature is written or needed"
    assert sent == [f"{CH}: удержание {TOPIC} снято — флаг комплаенса на сцене s2, "
                    f"в ролике s1 (CF-0846)"], sent
    held, why = _ph().is_held(CH, BID, TOPIC, root=r)
    assert not held and "flagged_scene_not_in_script" in why, why
    # idempotent: nothing written, nothing sent the second time
    before = (r / "publish" / "publication-holds.json").read_bytes()
    rep2, sent2 = run(r, b)
    assert rep2["lifted"] == [] and rep2["already"] == [row["hold_id"]] and not rep2["written"]
    assert sent2 == [] and (r / "publish" / "publication-holds.json").read_bytes() == before


def test_flag_on_scene_1_the_scripts_scene_holds():
    r, b = factory([hold(scenes=[S1])])
    rep, sent = run(r, b)
    assert rep["lifted"] == [] and rep["held"] == [f"{CH}/{BID}/{TOPIC}"], rep
    assert ledger(r)[0]["resolved_at"] is None and sent == []
    assert _ph().is_held(CH, BID, TOPIC, root=r)[0]


def test_a_flag_not_tied_to_a_scene_holds():
    for scenes in ("absent", None, [], "whole_topic", [""], "s2"):
        r, b = factory([hold(scenes=scenes)])
        rep, sent = run(r, b)
        assert rep["lifted"] == [] and len(rep["held"]) == 1, (scenes, rep)
        assert ledger(r)[0]["resolved_at"] is None and not rep["written"], scenes
        assert sent == []


def test_the_scripts_pass_hold_is_never_lifted_by_scene():
    r, b = factory([hold(scenes=[S2], stage="03-content-researcher")])
    rep, _ = run(r, b)
    assert rep["lifted"] == [] and ledger(r)[0]["resolved_at"] is None, rep


def test_every_script_of_the_topic_must_be_spared():
    r, b = factory([hold(scenes=[S2])], script_scenes=(S1, S2))
    rep, _ = run(r, b)
    assert rep["lifted"] == [] and ledger(r)[0]["resolved_at"] is None, rep


def test_a_scene_the_topic_does_not_have_or_no_scene_id_holds():
    for scenes in ((f"{TOPIC}-s9",), (None,)):
        r, b = factory([hold(scenes=[S2])], script_scenes=scenes)
        rep, _ = run(r, b)
        assert rep["lifted"] == [] and ledger(r)[0]["resolved_at"] is None, (scenes, rep)


def test_no_script_of_the_topic_leaves_the_hold_as_it_is():
    r, b = factory([hold(scenes=[S2])], script_scenes=())
    rep, _ = run(r, b)
    assert rep["lifted"] == [] and ledger(r)[0]["resolved_at"] is None, rep


def test_a_later_script_on_the_flagged_scene_puts_the_hold_back():
    r, b = factory([hold(scenes=[S2])])
    run(r, b)
    assert ledger(r)[0]["resolved_at"]
    write_scripts(b, (S1, S2))
    rep, sent = run(r, b)
    assert rep["reopened"] == [f"{CH}/{BID}/{TOPIC}"] and sent == [], rep
    row = ledger(r)[0]
    assert row["resolved_at"] is None and row["resolved_reason"] is None, row
    assert "resolved_reason_code" not in row and "scene_release" not in row, row
    assert row["scene_release_reopened"]["was"]["script_scenes"] == [S1]
    assert _ph().is_held(CH, BID, TOPIC, root=r)[0]


def test_a_row_the_pass_raised_again_carries_no_leftover():
    """merge() clears resolved_at / resolved_reason only; the rule's own fields
    are taken off when the row stands, or rewritten when it is lifted again."""
    left = {"resolved_reason_code": "flagged_scene_not_in_script",
            "scene_release": {"script_scenes": [S1]}}
    r, b = factory([hold(scenes=[S1], **left)])
    rep, _ = run(r, b)
    row = ledger(r)[0]
    assert rep["tidied"] and row["resolved_at"] is None, rep
    assert "resolved_reason_code" not in row and "scene_release" not in row, row
    r, b = factory([hold(scenes=[S2], **left)])
    rep, sent = run(r, b)
    assert rep["lifted"] and ledger(r)[0]["resolved_at"] and len(sent) == 1, rep


def test_signed_resolved_and_other_batches_are_untouched():
    rows = [hold(scenes=[S2], signature={"user": "user", "date": "d", "note": "n"}),
            hold(scenes=[S2], topic="lf-2026-10-21-007", resolved_at="x",
                 resolved_reason="rights only"),
            hold(scenes=[S2], batch="2026-10-20T0837Z")]
    r, b = factory(rows)
    write_scripts(b, (S1,))
    before = (r / "publish" / "publication-holds.json").read_bytes()
    rep, sent = run(r, b)
    assert rep["lifted"] == [] and not rep["written"] and sent == [], rep
    assert (r / "publish" / "publication-holds.json").read_bytes() == before


def test_an_agent_without_the_module_lifts_nothing():
    r, b = factory([hold(scenes=[S2])])
    rep, sent = run(r, b, code_root=TMP / "no-agent")
    assert rep["ok"] and rep["problem"] and "is not in this checkout" in rep["problem"], rep
    assert ledger(r)[0]["resolved_at"] is None and sent == []


def test_an_unreadable_ledger_lifts_nothing():
    r, b = factory([hold(scenes=[S2])])
    p = r / "publish" / "publication-holds.json"
    p.write_text("{not json")
    rep, sent = run(r, b)
    assert not rep["ok"] and rep["lifted"] == [] and sent == [], rep
    assert p.read_text() == "{not json"


def test_dry_run_writes_and_sends_nothing():
    r, b = factory([hold(scenes=[S2])])
    rep, sent = run(r, b, dry_run=True)
    assert rep["lifted"] and not rep["written"] and sent == [], rep
    assert ledger(r)[0]["resolved_at"] is None


def test_the_cli_through_runlog():
    r, b = factory([hold(scenes=[S2])])
    env = dict(os.environ, FACTORY_ROOT=str(r), RUNLOG_STATE_DIR=str(r / "state"),
               NOTIFY_BACKENDS="log", NOTIFY_STATE_DIR=str(r / "notify"))
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog"), "scene-holds",
                         "--batch", str(b)], capture_output=True, text=True, env=env,
                        timeout=120)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "lifted" in cp.stdout and "1 lifted" in cp.stdout, cp.stdout
    assert ledger(r)[0]["resolved_reason_code"] == "flagged_scene_not_in_script"
    journal = [json.loads(x) for x in (r / "notify" / "sent.jsonl").read_text().splitlines()]
    assert [j["kind"] for j in journal] == ["hold_released"], journal
    assert "снято" in journal[0]["text"] and "s2" in journal[0]["text"], journal
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog"), "scene-holds",
                         "--batch", str(b)], capture_output=True, text=True, env=env,
                        timeout=120)
    assert cp.returncode == 0 and "0 lifted" in cp.stdout, cp.stdout
    assert len((r / "notify" / "sent.jsonl").read_text().splitlines()) == 1


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
