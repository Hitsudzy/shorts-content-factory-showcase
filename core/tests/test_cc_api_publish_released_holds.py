#!/usr/bin/env python3
"""CC-0169 (factory 2.29, CF-0846): the holds lifted by the scene rule, and
the scenes a content-sensitivity flag rests on.

    GET /api/publish/holds/released?channel&days&limit
        resolved rows (`resolved_at`) and rows the scene rule put back
        (`scene_release_reopened`) in the window, newest first, each with
        `release {state, at, by, code, ..., flagged_short, script_short,
        signature_needed, line_ru}`

and `sensitivity_scenes` (content_sensitivity_check.scenes: a list of scene
ids or "whole_topic") on the hold rows, the signature's plan and the batch's
topics; `hold_released` among the notification kinds.

In-process (starlette's TestClient) against stand-in factory roots in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`): the ledger, the batch and
the notification journal are written here; no network, nothing outside the
temp dir.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import H, _w, client, factory_tree               # noqa: E402
from test_cc_api_publish import BATCH, files, setup                       # noqa: E402
from test_cc_api_publish_holds_sign import ledger_path, post, row          # noqa: E402
import test_cc_api_batch_topics as topics_t                                # noqa: E402

import api                                                                  # noqa: E402
from api import notifications                                               # noqa: E402

# the clock of test_cc_api_publish: 2026-10-06T12:00:00+03:00 = 09:00Z
T = "lf-2026-10-05-006"
S1, S2 = f"{T}-s1", f"{T}-s2"
SCENE_SENS = {"flagged": True, "notes": "scene 2: sitting politicians", "scenes": [S2]}
REASON = ("flagged_scene_not_in_script: every content-sensitivity flag of the shortlist pass "
          f"rests on {S2}; the script ({T}-script1) took {S1} - a scene the flag does not "
          f"touch. Lifted by the root, no signature needed (CF-0846); the rule never reads "
          f"the script's text. Topic {T}.")
RELEASE = {"task": "CF-0846", "script_scenes": [S1], "scripts": [f"{T}-script1"],
           "flagged_scenes": [S2], "by": "runlog scene-holds",
           "batch_dir": f"pipeline/reel/{BATCH}"}


def released(topic=T, at="2026-10-06T08:00:00Z", **kw):
    return row(topic, stage_checked="01-trend-hunter", content_sensitivity_check=SCENE_SENS,
               resolved_at=at, resolved_reason=REASON,
               resolved_reason_code="flagged_scene_not_in_script",
               scene_release=dict(RELEASE), **kw)


def reopened(topic="t-back"):
    s2 = f"{topic}-s2"
    return row(topic, stage_checked="01-trend-hunter",
               content_sensitivity_check={"flagged": True, "scenes": [s2]},
               scene_release_reopened={
                   "at": "2026-10-06T07:00:00Z", "task": "CF-0846",
                   "was": dict(RELEASE, script_scenes=[f"{topic}-s1"], flagged_scenes=[s2]),
                   "why": f"the script took {s2} - a flagged scene",
                   "script_scenes": [s2]})


def world(extra=()):
    root = factory_tree()
    _w(ledger_path(root), {"note": "test", "task": "CF-0318", "holds": [
        row("t-open"),
        released(),
        reopened(),
        row("t-rights", resolved_at="2026-10-05T09:00:00Z",
            resolved_reason="решение пользователя 28.09: ограничение по правообладателям "
                            "снято (CF-0420)"),
        row("t-old", resolved_at="2026-09-01T00:00:00Z", resolved_reason="снят давно"),
        released("t-demo", channel="demo"),
        row("t-whole", stage_checked="01-trend-hunter",
            content_sensitivity_check={"flagged": True, "scenes": "whole_topic"}),
        row("t-stray", content_sensitivity_check={"flagged": True, "scenes": []}),
        *extra]})
    return root


def get(c, path, status=200, **params):
    r = c.get(path, params=params, headers=H)
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


# --------------------------------------------------------------------- released
def test_a_hold_lifted_by_the_scene_rule_says_flag_on_s2_video_s1():
    setup()
    root = world()
    c = client(root)
    before = files(root)
    d = get(c, "/api/publish/holds/released", channel="reel")
    assert files(root) == before, "a read wrote something"
    assert (d["channel"], d["days"], d["limit"], d["problem"]) == ("reel", 14, 50, None), d
    assert d["as_of"] == "2026-10-06T09:00:00Z" and d["since"] == "2026-09-22T09:00:00Z", d
    assert [h["topic_id"] for h in d["holds"]] == [T, "t-back", "t-rights"], d["holds"]
    assert (d["total"], d["released"], d["reopened"]) == (3, 2, 1), d
    h = d["holds"][0]
    assert h["resolved_reason_code"] == "flagged_scene_not_in_script"
    assert h["scene_release"] == RELEASE, h["scene_release"]
    assert h["sensitivity_scenes"] == [S2]
    assert h["signable"] is False and h["sign_refusal"]["code"] == "already_resolved"
    assert h["release"] == {
        "state": "released", "at": "2026-10-06T08:00:00Z", "by": "runlog scene-holds",
        "code": "flagged_scene_not_in_script", "reason": REASON, "task": "CF-0846",
        "flagged_scenes": [S2], "script_scenes": [S1], "scripts": [f"{T}-script1"],
        "flagged_short": ["s2"], "script_short": ["s1"], "signature_needed": False,
        "line_ru": "Удержание снято: флаг на s2, в ролике s1, подпись не нужна"}, h["release"]


def test_a_hold_put_back_stands_again_and_needs_the_signature():
    setup()
    c = client(world())
    d = get(c, "/api/publish/holds/released", channel="reel")
    h = {x["topic_id"]: x for x in d["holds"]}["t-back"]
    assert h["resolved_at"] is None and h.get("resolved_reason_code") is None, h
    assert h["scene_release_reopened"]["was"]["flagged_scenes"] == ["t-back-s2"]
    assert h["signable"] is True and h["sign_refusal"] is None
    r = h["release"]
    assert (r["state"], r["at"], r["code"], r["signature_needed"]) == \
        ("reopened", "2026-10-06T07:00:00Z", None, True), r
    assert (r["flagged_short"], r["script_short"], r["by"]) == \
        (["s2"], ["s2"], "runlog scene-holds"), r
    assert r["line_ru"] == "Удержание снова стоит: флаг на s2, в ролике s2, нужна подпись"
    # still among the open ones
    o = get(c, "/api/publish/holds", channel="reel")
    assert "t-back" in {x["topic_id"] for x in o["open"]}


def test_another_release_has_no_scenes_and_its_reason_as_the_line():
    setup()
    d = get(client(world()), "/api/publish/holds/released", channel="reel")
    r = {x["topic_id"]: x for x in d["holds"]}["t-rights"]["release"]
    assert (r["state"], r["code"], r["by"], r["flagged_scenes"], r["script_scenes"]) == \
        ("released", None, None, [], []), r
    assert r["line_ru"].startswith("Удержание снято: решение пользователя 28.09"), r


def test_the_window_the_limit_and_every_channel():
    setup()
    c = client(world())
    d = get(c, "/api/publish/holds/released", days=60)
    assert [h["topic_id"] for h in d["holds"]] == [T, "t-demo", "t-back", "t-rights", "t-old"]
    assert d["channel"] is None and d["total"] == 5
    d = get(c, "/api/publish/holds/released", days=60, limit=2)
    assert [h["topic_id"] for h in d["holds"]] == [T, "t-demo"] and d["total"] == 5, d
    for bad in ({"days": 0}, {"days": 91}, {"limit": 0}, {"limit": 201}):
        get(c, "/api/publish/holds/released", status=422, **bad)


def test_a_broken_moment_is_kept_last_and_a_broken_ledger_is_the_problem():
    setup()
    root = world([row("t-when", resolved_at="yesterday", resolved_reason="?")])
    d = get(client(root), "/api/publish/holds/released", channel="reel")
    assert d["holds"][-1]["topic_id"] == "t-when", d["holds"]
    ledger_path(root).write_text("{not json", encoding="utf-8")
    d = get(client(root), "/api/publish/holds/released")
    assert d["problem"] and d["holds"] == [] and d["total"] == 0, d


# --------------------------------------------------------------------- the flag's scenes
def test_the_hold_rows_carry_the_scenes_as_a_list_or_the_whole_topic():
    setup()
    d = get(client(world()), "/api/publish/holds", channel="reel")
    by = {x["topic_id"]: x for x in d["rows"]}
    assert by[T]["sensitivity_scenes"] == [S2]
    assert by["t-whole"]["sensitivity_scenes"] == "whole_topic"
    assert by["t-stray"]["sensitivity_scenes"] == "whole_topic"      # fail closed
    assert by["t-open"]["sensitivity_scenes"] is None                # before CF-0846
    assert by[T]["content_sensitivity_check"]["scenes"] == [S2]


def test_the_signature_s_plan_says_the_flag_s_scenes():
    setup()
    c = client(world([row("t-sc", content_sensitivity_check={"flagged": True,
                                                            "scenes": ["t-sc-s3"]})]))
    for topic, scenes, line in (("t-sc", ["t-sc-s3"], "Сцены флага: s3"),
                                ("t-whole", "whole_topic", "Сцены флага: вся тема")):
        code, plan = post(c, f"/api/publish/reel/holds/{BATCH}/{topic}/sign/plan",
                          {"note": "посмотрел"})
        assert code == 200, plan
        assert plan["sensitivity_scenes"] == scenes, plan
        assert line in plan["flagged"], plan["flagged"]
    code, plan = post(c, f"/api/publish/reel/holds/{BATCH}/t-open/sign/plan", {"note": "да"})
    assert plan["sensitivity_scenes"] is None
    assert not any(x.startswith("Сцены флага") for x in plan["flagged"]), plan["flagged"]


def test_the_batch_topics_carry_the_scenes():
    root, d = topics_t.tree(upto=2)
    doc = json.loads((d / "02-compliance-checker.json").read_text(encoding="utf-8"))
    for r in doc["results"]:
        if r["topic_id"] == "reel-001":
            r["content_sensitivity_check"] = {"flagged": True, "scenes": ["reel-001-s2"]}
        if r["topic_id"] == "reel-002":
            r["content_sensitivity_check"] = {"flagged": True, "scenes": "whole_topic"}
    _w(d / "02-compliance-checker.json", doc)
    t = topics_t.by_id(topics_t.get(root))
    assert t["reel-001"]["compliance"]["sensitivity_scenes"] == ["reel-001-s2"]
    assert t["reel-002"]["compliance"]["sensitivity_scenes"] == "whole_topic"
    assert t["reel-005"]["compliance"]["sensitivity_scenes"] is None
    one = topics_t.get(root, f"{topics_t.URL}/reel-002")
    assert one["summary"]["compliance"]["sensitivity_scenes"] == "whole_topic", one["summary"]


# --------------------------------------------------------------------- the notification
def test_hold_released_is_a_kind_of_the_bus():
    saved = os.environ.get("NOTIFY_STATE_DIR")
    try:
        notifications.FACTORY_KW.clear()
        notifications.FACTORY_KW["now"] = "2026-10-06T09:00:00Z"
        root = factory_tree()
        os.environ["NOTIFY_STATE_DIR"] = str(root / "notify")
        _w(root / "notify" / "sent.jsonl", json.dumps({
            "at": "2026-10-06T08:00:00Z", "kind": "hold_released", "channel": "reel",
            "key": f"hold_released:reel/{BATCH}/{T}:2026-10-06T08:00:00Z",
            "text": f"reel: удержание {T} снято — флаг комплаенса на сцене s2, в ролике s1 "
                    f"(CF-0846)", "link": None, "task": "CF-0846",
            "backends": {"log": "ok"}}, ensure_ascii=False) + "\n")
        c = client(root)
        r = c.get("/api/notify/journal", params={"kind": "hold_released"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "hold_released" in d["kinds"], d["kinds"]
        assert d["total"] == 1 and d["events"][0]["kind"] == "hold_released", d
    finally:
        notifications.FACTORY_KW.clear()
        if saved is None:
            os.environ.pop("NOTIFY_STATE_DIR", None)
        else:
            os.environ["NOTIFY_STATE_DIR"] = saved


# --------------------------------------------------------------------- the contract
def test_the_contract_carries_the_route_and_the_fields():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    op = spec["paths"]["/api/publish/holds/released"]
    assert set(op) == {"get"}, op
    ok = op["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok["$ref"].endswith("/ReleasedHolds"), ok
    assert {p["name"] for p in op["get"]["parameters"]} == {"channel", "days", "limit"}
    s = spec["components"]["schemas"]
    for model, fields in (("HoldRow", {"resolved_reason_code", "scene_release",
                                       "scene_release_reopened", "sensitivity_scenes"}),
                          ("HoldRelease", {"state", "flagged_short", "script_short",
                                           "signature_needed", "line_ru"}),
                          ("TopicCompliance", {"sensitivity_scenes"}),
                          ("HoldSignPlan", {"sensitivity_scenes"})):
        assert fields <= set(s[model]["properties"]), (model, set(s[model]["properties"]))
    rows = json.loads((ROOT / "api" / "commands.json").read_text(encoding="utf-8"))["commands"]
    assert any(r.get("api") == "GET /api/publish/holds/released" for r in rows)


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
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
