#!/usr/bin/env python3
"""CC-0091: what each stage found and decided about a batch's topics, while
it runs (`api/topics.py`, `GET /api/batches/{channel}/{batch_id}/topics` and
`.../topics/{topic_id}`).

In-process (starlette's TestClient) against temp factory roots
(`test_cc_api_batches.factory_tree`): the stage files are written by the test
into a temp batch folder, in the shapes of a real finished batch (01, 02,
01b, 03-06) cut down to what the API reads - no real batch, no footage pool,
no network.

What is pinned:

* the contract: the two routes, GET only, version 0.48.0, `BatchProblem` on
  404 / 500 with `unknown_topic` and `stage_broken`, the models' fields;
* only 01 (the batch running): every shortlisted topic «в работе: проверка
  правил», no 02 / 01b / 03 block (null, not an error), the skipped topics
  with their lines, `search_quota`, `files[]` with only 01 present;
* 01 + 02: the verdict and its place (batch, reserve, refused), the cut, the
  pool's depth, «в работе: футаж» - and «не дошла: футаж» when the batch is
  stopped;
* the whole set: the indexer's record, a refusal at the footage, at the
  script, at the frame judge, «ролик готов», the counts; no absolute path in
  the answer (a video is its slug, the root's prefix is gone);
* no files at all: an empty answer; a broken 01 or 02: 500 `stage_broken`
  naming the file, `{message, code, details}`;
* one topic: scenes, fact and its source, the support texts, the links, the
  searches; a skipped one; an unknown one and one before 01: 404
  `unknown_topic`; an unknown batch 404;
* read only: the tree is the same after.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import _w, client, factory_tree   # noqa: E402

import api                                           # noqa: E402
from api import factory as _factory                  # noqa: E402


def RU(code):
    """CC-0113: the factory's Russian of a funnel code (funnel.reason_ru)."""
    return _factory.funnel().reason_ru(code)


CH, B = "reel", "2026-10-12T2001Z"
URL = f"/api/batches/{CH}/{B}/topics"


def _topic(n, name, usable=80, floor=60):
    tid = f"reel-00{n}"
    return {
        "topic_id": tid,
        "title_ref": {"name": name, "kind": "work", "type": "film", "year": 2026,
                      "season": None, "network": None, "parent_work": None, "person": None,
                      "rights_holder": "Studio"},
        "signal": {"popularity_score": 90.0 - n, "components": {}, "raw": {}},
        "evidence": {
            "youtube_video_ids": ["vid1"],
            "rss_links": [f"https://news.example/{tid}", f"https://other.example/{tid}"],
            "sources": [{"url": f"https://news.example/{tid}", "title": f"{name} news",
                         "publication": "News", "published_at": "2026-10-12T01:00:00+00:00",
                         "feed": "https://news.example/feed", "summary": "a summary"}],
            "footage_candidates": [{"video_id": "vid1", "kind": "trailer", "nature": "trailer",
                                    "title": f"{name} trailer", "channel_title": "Studio",
                                    "view_count": 1000, "duration_seconds": 120}]},
        "scenes": [{"scene_id": f"{tid}-s1", "description": f"{name}: the first scene",
                    "tags": ["casting"], "source_url": f"https://news.example/{tid}"},
                   {"scene_id": f"{tid}-s2", "description": "x" * 900, "tags": [],
                    "source_url": None}],
        "fact_probe": {"topic_id": tid, "outcome": "ok", "has_fact": True, "usable": True,
                       "article": name, "article_url": f"https://en.wikipedia.org/wiki/{name}",
                       "candidates": 1, "detail": None, "source": "wikipedia",
                       "asked_at": "2026-10-12T20:10:00Z"},
        "fact_candidates": [{"text": f"{name} cost a lot.", "kind": "production",
                             "source": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{name}"
                             "#Production", "section": "Production",
                             "check": {"passes": True, "failures": []},
                             "scenes": [f"{tid}-s1"]},
                            {"text": "a rumour", "kind": "other", "source": "Blog",
                             "url": "https://blog.example/x", "section": None,
                             "check": {"passes": False, "failures": ["tier"]}, "scenes": []}],
        "fact_search": {"asked": [], "error": None, "found": 2, "passing": 1},
        "support_text": [{"id": f"wikipedia:{name}", "kind": "work_article",
                          "source": "wikipedia", "title": name,
                          "url": f"https://en.wikipedia.org/wiki/{name}", "revision_id": 1,
                          "revised_at": "2026-10-11", "text": "long article text"}],
        "support_check": {"state": "ok", "event": None, "detail": None, "asked": [],
                          "requests": 1, "pieces": 1},
        "pool": {"rule": "CF-0325", "phrases": [name.lower()], "sources": 5, "shots": 300,
                 "retired": 10, "usable": usable, "measured": True, "floor": floor,
                 "coverage": 1.0, "coverage_by": "usable", "matched": [], "error": None},
    }


def hunter():
    return {
        "batch_id": B, "channel": CH, "language": "en", "generated_at": "2026-10-12T20:20:00Z",
        "sources_used": ["rss", "youtube"], "discovery": {},
        "topics": [_topic(1, "Alpha"), _topic(2, "Beta"), _topic(3, "Gamma"),
                   _topic(4, "Delta"), _topic(5, "Epsilon", usable=20), _topic(6, "Zeta")],
        "skipped_topics": [
            {"topic_id": "reel-007", "reason_code": "no_fact", "reason": "no fact found",
             "stage": "trend-hunter", "title": "Eta", "kind": "work", "popularity_score": 70.0,
             "fact_probe": {"outcome": "wrong_article", "has_fact": False}},
            {"topic_id": "reel-008", "reason_code": "below_shortlist", "reason": "rank 9",
             "stage": "trend-hunter", "title": "Theta", "kind": "work",
             "popularity_score": 50.0, "fact_probe": None}],
        "selection": {"stage": "trend-hunter", "shortlist_size": 6, "scored": 9, "viable": 7,
                      "carried": 6},
        "search_quota": {"task": "CF-0313", "searches_by_topic": {"reel-001": 6, "reel-002": 0,
                                                                  "supplement:reel-001": 16},
                         "api_units_by_key": {"reel-001": 3}, "daily_limit_searches": 100,
                         "units_per_search": 100, "spent_searches": 22, "spent_units": 2200,
                         "remaining_searches": 78, "resets_at": "07:00Z",
                         "by_article": {"scoring": {"search_calls": 6, "api_units": 6,
                                                    "what": "the scoring pass"}},
                         "summary_line": "YouTube quota: 22 of 100"},
        "footage_substitution": {"substitutions": [], "unmatched": [], "remaining": []},
        "footage_candidates_shared": [],
    }


def _verdict(tid, verdict, **kw):
    return dict({"topic_id": tid, "verdict": verdict,
                 "rights_holder_check": {"matched": False, "reason": "not on the blacklist"},
                 "content_sensitivity_check": {"flagged": False, "notes": "fine"}}, **kw)


def compliance():
    return {"batch_id": B, "channel": CH, "stage_checked": "01-trend-hunter",
            "checked_at": "2026-10-12T20:30:00Z", "disclaimer": "Heuristic first-pass screen.",
            "results": [_verdict("reel-001", "clear"), _verdict("reel-002", "caution"),
                        _verdict("reel-004", "reject"), _verdict("reel-005", "clear"),
                        _verdict("reel-006", "clear")],
            "reserve": [_verdict("reel-003", "clear", reason_code="reserve_unused",
                                 reason="eligible and unused")],
            "cut": {"task": "CF-0265", "cut_at": "2026-10-12T20:30:01Z", "shortlist_size": 6,
                    "judged": 6, "eligible": 5, "carried": 4, "reserve": 1, "refused": 1,
                    "held": 0, "target": 4, "reason_code": "reserve_unused",
                    "pass_verdicts": ["clear", "caution", "review"],
                    "production_verdicts": ["clear", "caution", "review"],
                    "publish_verdicts": ["clear", "caution"]}}


def _depth(tid, usable, deep, indexed_at=None):
    row = {"topic_id": tid, "sources": 2, "shots": 100, "usable_shots": usable,
           "weak_shots": 5, "available_shots": usable + 5, "usable_seconds": 200.5,
           "floor": 60, "deep_enough": deep, "measured": True, "at_source_floor": True,
           "error": None, "exhausted": None if deep else "attempt_cap", "attempts": 2,
           "per_source": []}
    if indexed_at:                  # CF-0715 (2.4+); a batch before it has no such key
        row["indexed_at"] = indexed_at
    return row


INDEXED_AT = "2026-10-01T11:40:00Z"


def index(d):
    return {"batch": str(d),
            "fetched": [], "sources_by_topic": {"reel-001": ["a", "b"], "reel-002": ["c", "d"],
                                                "reel-006": ["e", "f"]},
            "skipped_topics": [
                {"topic_id": "reel-003", "reason_code": "reserve_unused", "reason": "reserve",
                 "stage": "footage-indexer"},
                {"topic_id": "reel-005", "reason_code": "no_second_source",
                 "reason": f"one source; see {d}/work/epsilon/log.txt",
                 "stage": "footage-indexer"}],
            "failed": [{"video_id": "z", "topic_id": "reel-002", "reason_code": "fetch_failed"}],
            "warnings": [{"topic_id": "reel-002", "warning_code": "thin_pool"}],
            "pool_depth": {"floor": 60, "topics": [_depth("reel-001", 80, True, INDEXED_AT),
                                                   _depth("reel-002", 30, False),
                                                   _depth("reel-006", 70, True)],
                           "thin": ["reel-002"]},
            "reserve_substitution": {"substitutions": [], "unmatched": [], "remaining": []}}


def researcher(d):
    def script(tid, name):
        return {"script_id": f"{tid}-script1", "topic_id": tid, "scene_id": f"{tid}-s1",
                "hook": f"{name} hook", "estimated_spoken_duration_seconds": 38.5,
                "fact": {"text": f"{name} cost a lot.", "kind": "production",
                         "source": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{name}",
                         "primary_url": "https://news.example/primary", "section": "Production"}}
    return {"batch_id": B, "channel": CH, "scripts": [script("reel-001", "Alpha"),
                                                      script("reel-006", "Zeta")],
            "skipped": [{"topic_id": "reel-002", "script_id": "reel-002-script1",
                         "reason_code": "plan_unassembled", "reason": "no plan",
                         "stage": "scripts",
                         "plan_check": {"verdict": f"{d}/work/beta/plan-check.json"}}]}


def scripts_check():
    return {"batch_id": B, "channel": CH, "stage_checked": "03-content-researcher",
            "results": [{"script_id": f"{t}-script1", "topic_id": t, "verdict": "clear",
                         "contribution_check": {"verdict": "pass"}}
                        for t in ("reel-001", "reel-006")]}


def editor(d):
    return {"batch_id": B, "channel": CH, "refusals": [],
            "videos": [{"script_id": f"{t}-script1", "output_path": str(d / "videos" / f"{s}.mp4"),
                        "qc": {"passed": True, "failures": []}, "needs_you": None,
                        "score_line": "A · 90"}
                       for t, s in (("reel-001", "alpha"), ("reel-006", "zeta"))]}


def judge():
    return {"schema": "frame-judge/2", "batch_id": B, "channel": CH,
            "videos": [{"script_id": "reel-001-script1", "slug": "alpha", "gate": "pass",
                        "reason_code": None, "reason": None, "score_line": "A · 88"},
                       {"script_id": "reel-006-script1", "slug": "zeta", "gate": "reject",
                        "reason_code": "score_below_threshold", "reason": "under 60",
                        "score_line": "E · 41"}]}


def tree(upto=7, status="running"):
    """A temp batch with the stage files of the first `upto` stages (in the
    stages' order: 01, 02, 01b, 03, 04, 05, 06)."""
    root = factory_tree()
    d = root / "pipeline" / CH / B
    d.mkdir(parents=True)
    if status is not None:
        _w(d / "run-state.json", {"status": status, "batch_id": B, "channel": CH})
    files = (("01-trend-hunter.json", hunter), ("02-compliance-checker.json", compliance),
             ("01b-footage-index.json", lambda: index(d)),
             ("03-content-researcher.json", lambda: researcher(d)),
             ("04-compliance-checker.json", scripts_check),
             ("05-video-editor.json", lambda: editor(d)), ("06-frame-judge.json", judge))
    for name, make in files[:upto]:
        _w(d / name, make())
    return root, d


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if ".git" not in p.parts and p.is_file()}


def get(root, url=URL, status=200):
    r = client(root).get(url)
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


def by_id(got):
    return {t["topic_id"]: t for t in got["topics"]}


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_topic_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for path in ("/api/batches/{channel}/{batch_id}/topics",
                 "/api/batches/{channel}/{batch_id}/topics/{topic_id}"):
        assert sorted(spec["paths"][path]) == ["get"], spec["paths"][path].keys()
        resp = spec["paths"][path]["get"]["responses"]
        for code in ("404", "500"):
            assert resp[code]["content"]["application/json"]["schema"]["$ref"] \
                .endswith("/BatchProblem"), code
    schemas = spec["components"]["schemas"]
    assert {"unknown_topic", "stage_broken"} <= \
        set(schemas["BatchProblem"]["properties"]["code"]["enum"])
    assert {"files", "trend_hunter_done", "compliance", "search_quota", "counts", "topics",
            "skipped", "going"} <= set(schemas["BatchTopics"]["properties"])
    assert {"topic_id", "title", "kind", "type", "popularity_score", "sources", "scenes",
            "compliance", "footage", "scripts", "state"} <= \
        set(schemas["TopicSummary"]["properties"])
    assert {"scenes", "fact", "sources", "videos", "searches", "summary", "skipped"} <= \
        set(schemas["BatchTopic"]["properties"])
    assert {"spent_searches", "remaining_searches", "searches_by_topic"} <= \
        set(schemas["SearchQuota"]["properties"])


# --------------------------------------------------------------------- stage by stage
def test_only_01_every_topic_waits_for_the_check():
    root, d = tree(upto=1)
    before = snapshot(root)
    got = get(root)
    assert got["trend_hunter_done"] and got["going"] and not got["closed"], got
    assert [f["present"] for f in got["files"]] == [True] + [False] * 6, got["files"]
    assert got["files"][0]["written_at"] and got["files"][1]["written_at"] is None
    assert got["compliance"] is None
    assert [t["topic_id"] for t in got["topics"]] == [f"reel-00{n}" for n in range(1, 7)]
    a = by_id(got)["reel-001"]
    assert (a["title"], a["kind"], a["type"], a["rank"]) == ("Alpha", "work", "film", 1)
    assert a["popularity_score"] == 89.0 and a["scenes"] == 2 and a["has_fact"] is True
    assert [s["url"] for s in a["sources"]] == ["https://news.example/reel-001",
                                                "https://other.example/reel-001"], a["sources"]
    assert a["compliance"] is None and a["scripts"] is None
    assert a["footage"]["indexer"] is None
    assert a["footage"]["pool"]["usable"] == 80 and a["footage"]["pool"]["deep_enough"] is True
    assert by_id(got)["reel-005"]["footage"]["pool"]["deep_enough"] is False
    for t in got["topics"]:
        assert t["state"] == {"phase": "in_work", "stage": "compliance-shortlist",
                              "line": "в работе: проверка правил", "reason_code": None,
                              "reason_ru": None}, t
    sk = {s["topic_id"]: s for s in got["skipped"]}
    assert sk["reel-007"]["state"]["line"] == f"отсеяна: {RU('no_fact')}"
    assert sk["reel-007"]["reason_code"] == "no_fact" and sk["reel-007"]["stage"] == "trend-hunter"
    assert sk["reel-007"]["reason_ru"] == RU("no_fact") is not None, sk["reel-007"]   # CC-0113
    assert sk["reel-007"]["state"]["reason_ru"] == RU("no_fact"), sk["reel-007"]
    assert sk["reel-008"]["state"]["line"] == "не вошла в шорт-лист"
    q = got["search_quota"]
    assert q["spent_searches"] == 22 and q["remaining_searches"] == 78, q
    assert q["searches_by_topic"] == {"reel-001": 6, "reel-002": 0, "supplement:reel-001": 16}
    assert q["by_article"]["scoring"]["search_calls"] == 6
    assert got["counts"] == {"topics": 6, "skipped": 2, "in_work": 6, "stalled": 0,
                             "reserve": 0, "dropped": 0, "done": 0}, got["counts"]
    assert got["selection"]["shortlist_size"] == 6
    assert snapshot(root) == before, "read only"


def test_01_and_02_the_verdicts_and_the_footage_next():
    root, d = tree(upto=2)
    got = get(root)
    t = by_id(got)
    assert got["compliance"]["cut"]["carried"] == 4 and got["compliance"]["cut"]["target"] == 4
    assert t["reel-001"]["compliance"]["verdict"] == "clear"
    assert t["reel-001"]["compliance"]["place"] == "batch"
    assert t["reel-001"]["compliance"]["rights_reason"] == "not on the blacklist"
    assert t["reel-001"]["state"]["line"] == "в работе: футаж"
    assert t["reel-001"]["state"]["phase"] == "in_work"
    assert t["reel-003"]["compliance"]["place"] == "reserve"
    assert t["reel-003"]["state"] == {"phase": "reserve", "stage": "compliance-shortlist",
                                      "line": "в резерве", "reason_code": "reserve_unused",
                                      "reason_ru": RU("reserve_unused")}
    assert t["reel-004"]["compliance"]["place"] == "refused"
    assert t["reel-004"]["state"]["line"] == "отсеяна: проверка правил (reject)"
    assert t["reel-004"]["state"]["phase"] == "dropped"
    assert [f["present"] for f in got["files"]] == [True, True] + [False] * 5
    assert t["reel-001"]["footage"]["indexer"] is None
    assert got["counts"]["in_work"] == 4 and got["counts"]["reserve"] == 1 \
        and got["counts"]["dropped"] == 1, got["counts"]


def test_a_stopped_batch_says_the_topic_did_not_get_there():
    root, d = tree(upto=2, status="stopped")
    got = get(root)
    assert not got["going"] and got["status"] == "stopped"
    st = by_id(got)["reel-001"]["state"]
    assert st["phase"] == "stalled" and st["line"] == "не дошла: футаж (батч stopped)", st


def test_the_whole_batch_every_stage_s_word():
    root, d = tree(upto=7, status="done")
    before = snapshot(root)
    r = client(root).get(URL)
    assert r.status_code == 200, r.text
    assert str(root) not in r.text and str(root.resolve()) not in r.text, "no absolute path"
    got = r.json()
    assert got["closed"] and not got["going"]
    assert all(f["present"] for f in got["files"])
    t = by_id(got)
    a = t["reel-001"]
    ix = a["footage"]["indexer"]
    assert ix["registered_sources"] == 2 and ix["depth"]["usable_shots"] == 80
    assert ix["depth"]["deep_enough"] is True and ix["thin"] is False and ix["indexed_at"]
    assert ix["depth"]["indexed_at"] == INDEXED_AT, ix["depth"]     # CC-0119 (CF-0715)
    assert t["reel-002"]["footage"]["indexer"]["depth"]["indexed_at"] is None, \
        "a row without indexed_at (before 2.4) reads null"
    s = a["scripts"][0]
    assert s["script_id"] == "reel-001-script1" and s["hook"] == "Alpha hook"
    assert s["compliance"] == {"verdict": "clear", "contribution": "pass", "passes": True}
    assert s["video"]["slug"] == "alpha" and s["video"]["qc_passed"] is True
    assert s["frame"]["gate"] == "pass"
    assert a["state"] == {"phase": "done", "stage": "frame-judge", "line": "ролик готов",
                          "reason_code": None, "reason_ru": None}
    b = t["reel-002"]
    assert b["footage"]["indexer"]["thin"] is True
    assert b["footage"]["indexer"]["failed_downloads"] == 1
    assert b["footage"]["indexer"]["warnings"] == ["thin_pool"]
    assert b["scripts"] == []
    assert b["state"]["line"] == f"отсеяна: сценарий ({RU('plan_unassembled')})", b["state"]
    assert b["state"]["reason_code"] == "plan_unassembled"
    e = t["reel-005"]
    assert e["footage"]["indexer"]["skipped"]["reason_code"] == "no_second_source"
    assert e["footage"]["indexer"]["skipped"]["reason"] == \
        f"one source; see pipeline/{CH}/{B}/work/epsilon/log.txt", "the root's prefix is gone"
    assert e["state"]["line"] == f"отсеяна: футаж ({RU('no_second_source')})"
    assert e["footage"]["indexer"]["skipped"]["reason_ru"] == RU("no_second_source"), e
    assert t["reel-003"]["state"]["phase"] == "reserve"
    z = t["reel-006"]
    assert z["state"]["line"] == f"отсеяна: судья кадров ({RU('score_below_threshold')})", \
        z["state"]
    assert z["scripts"][0]["frame"]["score_line"] == "E · 41"
    assert got["counts"] == {"topics": 6, "skipped": 2, "in_work": 0, "stalled": 0,
                             "reserve": 1, "dropped": 4, "done": 1}, got["counts"]
    assert snapshot(root) == before, "read only"


def test_a_built_video_waits_for_the_frame_judge():
    root, d = tree(upto=6)
    st = by_id(get(root))["reel-001"]["state"]
    assert st == {"phase": "in_work", "stage": "frame-judge",
                  "line": "ролик собран, в работе: судья кадров", "reason_code": None,
                  "reason_ru": None}, st
    root, d = tree(upto=4)
    st = by_id(get(root))["reel-001"]["state"]
    assert st["line"] == "сценарий готов, в работе: проверка сценария", st


def test_nothing_written_yet_is_an_empty_answer():
    root, d = tree(upto=0)
    got = get(root)
    assert got["topics"] == [] and got["skipped"] == [] and not got["trend_hunter_done"]
    assert got["search_quota"] is None and got["compliance"] is None
    assert not any(f["present"] for f in got["files"])
    assert got["counts"]["topics"] == 0


def test_a_broken_stage_file_is_stage_broken():
    for name in ("01-trend-hunter.json", "02-compliance-checker.json"):
        root, d = tree(upto=2)
        (d / name).write_text('{"topics": [', encoding="utf-8")
        got = get(root, status=500)
        assert set(got) == {"message", "code", "details"}, got
        assert got["code"] == "stage_broken" and name in got["message"], got
        assert got["details"] and got["details"][0].startswith(name), got["details"]
        got = get(root, f"{URL}/reel-001", status=500)
        assert got["code"] == "stage_broken", got
    root, d = tree(upto=1)
    (d / "02-compliance-checker.json").write_text("[]", encoding="utf-8")
    got = get(root, status=500)
    assert got["code"] == "stage_broken" and "02-compliance-checker.json" in got["message"]


# --------------------------------------------------------------------- one topic
def test_one_topic_scenes_fact_and_links():
    root, d = tree(upto=7, status="done")
    r = client(root).get(f"{URL}/reel-001")
    assert r.status_code == 200, r.text
    assert str(root) not in r.text
    got = r.json()
    assert got["shortlisted"] and got["skipped"] is None
    assert got["summary"]["state"]["line"] == "ролик готов"
    assert got["title_ref"]["name"] == "Alpha" and got["title_ref"]["rights_holder"] == "Studio"
    assert [s["scene_id"] for s in got["scenes"]] == ["reel-001-s1", "reel-001-s2"]
    assert got["scenes"][0]["description"] == "Alpha: the first scene"
    assert len(got["scenes"][1]["description"]) == 600, "a long description is cut"
    f = got["fact"]
    assert f["probe"]["outcome"] == "ok" and f["probe"]["article_url"].endswith("/Alpha")
    assert [c["passes"] for c in f["candidates"]] == [True, False]
    assert f["candidates"][1]["failures"] == ["tier"]
    assert f["search"] == {"found": 2, "passing": 1, "error": None}
    assert f["support"]["state"] == "ok" and f["support"]["texts"][0]["title"] == "Alpha"
    assert "text" not in f["support"]["texts"][0], "the support text itself is not sent"
    assert f["chosen"][0]["script_id"] == "reel-001-script1"
    assert f["chosen"][0]["primary_url"] == "https://news.example/primary"
    assert got["videos"][0]["url"] == "https://www.youtube.com/watch?v=vid1"
    assert got["sources"][0]["publication"] == "News"
    assert got["searches"] == {"reel-001": 6, "supplement:reel-001": 16}


def test_one_topic_early_and_skipped_and_unknown():
    root, d = tree(upto=1)
    got = get(root, f"{URL}/reel-002")
    assert got["summary"]["state"]["line"] == "в работе: проверка правил"
    assert got["fact"]["chosen"] == [] and got["going"] is True
    got = get(root, f"{URL}/reel-007")
    assert not got["shortlisted"] and got["summary"] is None
    assert got["skipped"]["state"]["line"] == f"отсеяна: {RU('no_fact')}"
    assert got["skipped"]["reason_ru"] == RU("no_fact"), got["skipped"]
    assert got["title_ref"]["name"] == "Eta"
    assert got["fact"]["probe"]["outcome"] == "wrong_article"
    for tid in ("reel-999", ".hidden", "-x"):
        got = get(root, f"{URL}/{tid}", status=404)
        assert got["code"] == "unknown_topic", (tid, got)
    root, d = tree(upto=0)
    got = get(root, f"{URL}/reel-001", status=404)
    assert got["code"] == "unknown_topic" and "01-trend-hunter.json" in got["message"]


def test_an_unknown_batch_is_404():
    root, d = tree(upto=1)
    for url in (f"/api/batches/{CH}/2020-01-01T0000Z/topics",
                f"/api/batches/nochannel/{B}/topics/reel-001"):
        got = get(root, url, status=404)
        assert got["code"] == "unknown_batch", got


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
