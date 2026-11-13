#!/usr/bin/env python3
"""CC-0125: «оценка ролика» in the command center's API - the badge on every
video of `GET /api/batches/{channel}/{batch_id}/videos` (`Video.score`, the
tiers once as `BatchVideos.score_model`) and the reasoning behind it, `GET
.../videos/{slug}/score` (`VideoScore`), over the factory's score model
(`shared/score/score.py`: `load_model`, `stages_block`, `LABELS` /
`HARD_LABELS`, CF-0432 / CF-0434).

In-process (starlette's TestClient) against the stand-in roots of
`tests/test_cc_api_videos.py` / `test_cc_api_videos_refused.py` in a temp dir,
with a stand-in price table `shared/gate-prices.json` written here. The score
logs are made by the factory's own `stages_block` over that table, so they are
the shape the Editor writes. **Nothing outside the temp dir is read or
written**; no network.

What is pinned:

* the badge: `{tier, score, threshold, passed, stopped_at, source, url}` -
  `plan.score.json` first, else the 05's block (a refused video's
  `refusals[].score`), else null; a rebuild's video too;
* the tiers: `score_model.tiers` [{name, floor}] best first off the root's
  table, `below: F`; a table that does not load - `tiers: []` and why, the
  list still answers;
* the route: tier, points, start, N, passed, stopped_at, prices_status, the
  model's tiers, the stages with Russian labels and what each charged, the
  findings in stage order with the rule's Russian name (the factory's
  `LABELS` / `HARD_LABELS`, `судья: <verdict>`, an unknown rule by its short
  name), price / capped / hook from the log, `hard` from the hard list,
  `forecast` from `source: forecast` (no price), `by_rule`, the score line;
  absolute clip paths in `shot` / `note` cut (`paths.clean`);
* a refused video without its log: the 05's block, stages from its block,
  findings from its log, `stage: null`;
* 404: an unknown video `unknown_video`, a video with no score `no_score`, in
  Russian;
* the contract: the route, `VideoScore`, `Video.score`,
  `BatchVideos.score_model`, `no_score` in `BatchProblem`, version 0.58.0;
* CF-0751: `note_ru` from the log row (a new log), else `score.note_ru` - what
  `score.with_note_ru` gives (an old log), never for the judge's prose; `shot_ru` the clip's display name.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import test_cc_api_videos as tv                     # noqa: E402
import test_cc_api_videos_refused as tr             # noqa: E402
from test_cc_api_batches import _w, client          # noqa: E402

import api                                          # noqa: E402
from api import factory                             # noqa: E402

BATCH = tv.BATCH
HARD = ("score.hard.foreign_text", "score.hard.foreign_work_footage",
        "score.hard.duration_out_of_range", "score.hard.still_share_over_half",
        "score.hard.sound_broken", "score.hard.forbidden_topic", "score.hard.render_defect",
        "score.hard.footage_defect")
LEDGER = {
    "score": {"status": "signed", "signature": {"user": "test", "date": "2026-09-30"},
              "start": 100, "threshold": 60,
              "tiers": {"S": 95, "A": 85, "B": 75, "C": 67, "D": 60}},
    "rules": dict({h: {"mode": "hard"} for h in HARD}, **{
        "score.low_framing": {"mode": "penalty",
                              "penalty": {"price": 3, "per": "shot", "hook_mult": 2, "cap": 5}},
        "score.judge_contradicts": {"mode": "penalty",
                                    "penalty": {"price": 6, "per": "case", "cap": None}},
        "score.thin_picture": {"mode": "penalty",
                               "penalty": {"price": 5, "per": "second", "cap": 25}},
    })}


def ledger(root):
    _w(root / "shared" / "gate-prices.json", LEDGER)


def log_doc(root, d, slug, stages):
    """A `plan.score.json` as the Editor's `score_log.record` writes it - the
    block by the factory's own `stages_block` over the stand-in table."""
    block = factory.score_model().stages_block(stages, root / "shared" / "gate-prices.json")
    doc = {"schema": "cf0434.score_log/1", "script_id": f"t-{slug}-script1", "plan": "plan.json",
           "stages": stages,
           "score": {k: v for k, v in block.items() if k != "stages"},
           "stage_scores": block["stages"],
           "score_line": factory.score_model().summary_line(block, LEDGER)}
    _w(d / "work" / slug / "plan.score.json", doc)
    return doc


def clip(root, d, slug):
    return str(d / "work" / slug / "clips" / "a06_x.mp4")


def tree():
    root = tv.tree()
    ledger(root)
    d = root / "pipeline" / "reel" / BATCH
    abs_clip = clip(root, d, "paper-dragon")
    log_doc(root, d, "paper-dragon", [
        {"stage": "plan", "at": "2026-10-09T09:10:00+00:00", "findings": [
            {"rule": "score.low_framing", "where": {"block": 1, "shot": abs_clip, "t": 2.0},
             "units": 1, "hook": True, "source": "metric", "note": f"shot {abs_clip}: framing"},
            {"rule": "score.low_framing", "where": {"block": 4, "shot": "yt:26", "t": 9.7},
             "units": 1, "hook": False, "source": "metric", "note": "second one"},
            {"rule": "score.thin_picture", "where": {"block": 5, "t": 12.0}, "units": 2,
             "source": FORECAST_SRC, "note": "a forecast"}]},
        {"stage": "judge", "at": "2026-10-09T09:40:00+00:00", "findings": [
            {"rule": "score.judge_contradicts", "where": {"block": 6, "t": 15.0}, "units": 1,
             "source": "judge", "note": "the picture contradicts the words"}]},
        {"stage": "qc", "at": "2026-10-09T09:30:00+00:00", "findings": [
            {"rule": "score.thin_picture", "where": {"block": 7, "t": 20.5}, "units": 1.5,
             "source": "metric", "note": "thin"}]},
    ])
    rb = root / "pipeline" / "rebuilds" / tv.RB1
    log_doc(root, rb, "paper-dragon", [
        {"stage": "qc", "at": "2026-10-10T09:30:00+00:00", "findings": [
            {"rule": "score.hard.render_defect", "where": {}, "source": "metric",
             "note": "not 9:16"}]}])
    return root


FORECAST_SRC = "forecast"


def get(c, batch, slug=None):
    r = c.get(f"/api/batches/{batch}/videos" + (f"/{slug}/score" if slug else ""))
    return r.status_code, r.json()


# --------------------------------------------------------------------- the badge
def test_every_video_carries_its_badge_and_the_tiers_once():
    root = tree()
    st, b = get(client(root), f"reel/{BATCH}")
    assert st == 200, b
    assert b["score_model"] == {"start": 100, "threshold": 60, "below": "F", "status": "signed",
                                "error": None, "tiers": [
                                    {"name": "S", "floor": 95}, {"name": "A", "floor": 85},
                                    {"name": "B", "floor": 75}, {"name": "C", "floor": 67},
                                    {"name": "D", "floor": 60}]}, b["score_model"]
    vs = tv.by_slug(b["videos"])
    # 100 - 5 (framing: 6 hook + 3, capped at 5) - 7.5 (thin 1.5 s) - 6 (judge) = 81.5 -> B
    assert vs["paper-dragon"]["score"] == {
        "tier": "B", "score": 81.5, "threshold": 60, "passed": True, "stopped_at": None,
        "source": "plan.score.json",
        "url": f"/api/batches/reel/{BATCH}/videos/paper-dragon/score"}, vs["paper-dragon"]["score"]
    assert vs["night-owl"]["score"] is None
    reb = {r["batch_id"]: r for r in b["rebuilds"]}
    sc = tv.by_slug(reb[tv.RB1]["videos"])["paper-dragon"]["score"]
    assert sc["tier"] == "F" and sc["passed"] is False and sc["source"] == "plan.score.json", sc
    assert sc["url"] == f"/api/batches/rebuilds/{tv.RB1}/videos/paper-dragon/score", sc


def test_a_refused_video_s_badge_is_the_05_s_block():
    root = tr.refused_tree()
    ledger(root)
    st, b = get(client(root), f"reel/{tr.RB}")
    assert st == 200, b
    sc = tv.by_slug(b["videos"])["adenot"]["score"]
    assert sc["source"] == "05" and sc["tier"] == "F" and sc["score"] == 24 and \
        sc["threshold"] == 40 and sc["passed"] is False, sc


def test_a_table_that_does_not_load_is_said_and_the_list_still_answers():
    root = tv.tree()                                   # no shared/gate-prices.json
    st, b = get(client(root), f"reel/{BATCH}")
    assert st == 200, b
    m = b["score_model"]
    assert m["tiers"] == [] and m["error"] and "таблица цен" in m["error"], m
    assert str(root) not in m["error"], m


# --------------------------------------------------------------------- the reasoning
def test_the_score_route_is_the_log_with_russian_names():
    root = tree()
    st, s = get(client(root), f"reel/{BATCH}", "paper-dragon")
    assert st == 200, s
    assert (s["tier"], s["score"], s["start"], s["threshold"], s["passed"], s["stopped_at"],
            s["prices_status"], s["source"]) == ("B", 81.5, 100, 60, True, None, "signed",
                                                 "plan.score.json"), s
    assert s["path"] == f"pipeline/reel/{BATCH}/work/paper-dragon/plan.score.json", s["path"]
    assert [t["name"] for t in s["tiers"]] == ["S", "A", "B", "C", "D"]
    assert s["forecast_ignored"] == 1
    # the stages in the factory's order (plan, render, qc, judge), each in Russian
    assert [(x["stage"], x["label_ru"], x["charged"], x["score_after"], x["tier_after"])
            for x in s["stages"]] == [("plan", "план монтажа", -5, 95, "S"),
                                      ("qc", "проверка рендера (QC)", -7.5, 87.5, "A"),
                                      ("judge", "судья кадров", -6, 81.5, "B")], s["stages"]
    f = s["findings"]
    assert [(x["rule"], x["stage"], x["price"], x["hard"], x["forecast"]) for x in f] == [
        ("score.low_framing", "plan", -5, False, False),
        ("score.low_framing", "plan", 0, False, False),
        ("score.thin_picture", "plan", None, False, True),
        ("score.thin_picture", "qc", -7.5, False, False),
        ("score.judge_contradicts", "judge", -6, False, False)], f
    assert f[0]["label_ru"] == "кадрирование" and f[0]["hook"] is True and \
        f[0]["capped"] is True and f[0]["block"] == 1 and f[0]["t"] == 2.0, f[0]
    assert f[1]["capped"] is True and f[1]["shot"] == "yt:26", f[1]
    assert f[4]["label_ru"] == "судья: contradicts", f[4]
    # CF-0749: thin_picture has its Russian words now (the factory's LABELS)
    assert f[2]["label_ru"] == f[3]["label_ru"] == "тонкая картинка", f[3]
    assert s["by_rule"]["score.thin_picture"]["label_ru"] == "тонкая картинка", s["by_rule"]
    # the Editor's absolute clip path is cut
    want = f"pipeline/reel/{BATCH}/work/paper-dragon/clips/a06_x.mp4"
    assert f[0]["shot"] == want and want in f[0]["note"], f[0]
    assert str(root) not in json.dumps(s, ensure_ascii=False)
    assert s["by_rule"]["score.low_framing"] == {"raw": -9, "charged": -5, "cap": 5,
                                                 "label_ru": "кадрирование"}, s["by_rule"]
    assert s["score_line"].startswith("B · 81,5 — −5 кадрирование (2 шота, хук)"), \
        s["score_line"]


def test_a_rebuild_s_video_and_a_hard_finding():
    root = tree()
    st, s = get(client(root), f"rebuilds/{tv.RB1}", "paper-dragon")
    assert st == 200, s
    assert s["tier"] == "F" and s["passed"] is False and s["score"] == 100, s
    assert s["path"] == f"pipeline/rebuilds/{tv.RB1}/work/paper-dragon/plan.score.json"
    [h] = s["findings"]
    assert h["hard"] is True and h["price"] is None and h["label_ru"] == "брак рендера" and \
        h["stage"] == "qc", h
    assert "жёсткий: брак рендера" in s["score_line"], s["score_line"]


def test_the_hard_footage_defect_is_said_in_russian():
    # CF-0749: a hard rule's Russian words come from the factory's HARD_LABELS
    root = tree()
    rb = root / "pipeline" / "rebuilds" / tv.RB1
    log_doc(root, rb, "paper-dragon", [
        {"stage": "qc", "at": "2026-10-10T09:30:00+00:00", "findings": [
            {"rule": "score.hard.footage_defect", "where": {"block": 2, "t": 4.0},
             "source": "metric", "note": "a broken source clip"}]}])
    st, s = get(client(root), f"rebuilds/{tv.RB1}", "paper-dragon")
    assert st == 200, s
    [h] = s["findings"]
    assert h["hard"] is True and h["price"] is None and h["label_ru"] == "брак футажа", h
    assert "брак футажа" in s["score_line"], s["score_line"]


def test_a_refused_video_without_its_log_is_read_off_the_05():
    root = tr.refused_tree()
    ledger(root)
    st, s = get(client(root), f"reel/{tr.RB}", "adenot")
    assert st == 200, s
    assert s["source"] == "05" and s["path"] is None and s["tier"] == "F" and \
        s["score"] == 24, s
    assert s["score_line"] == tr.REFUSAL["score_line"]
    assert s["stages"] == []
    [f] = s["findings"]
    assert (f["rule"], f["price"], f["stage"], f["label_ru"]) == \
        ("score.frozen_frame", -62, None, "frozen_frame"), f


def test_no_video_or_no_score_is_a_russian_404():
    root = tree()
    c = client(root)
    st, b = get(c, f"reel/{BATCH}", "no-such")
    assert st == 404 and b["code"] == "unknown_video", b
    st, b = get(c, f"reel/{BATCH}", "night-owl")
    assert st == 404 and b["code"] == "no_score" and "Оценки ролика «night-owl» нет" in \
        b["message"], b


# --------------------------------------------------------------------- CF-0751: Russian notes
FACE = "framed on a face, none in the picture"
FACE_RU = "кадр выстроен по лицу, а лица в кадре нет"


def _ru_stages(root, d, slug):
    shot = str(d / "work" / slug / "clips" / "a04_mine-cart.mp4")
    return [
        {"stage": "plan", "at": "2026-10-09T09:10:00+00:00", "findings": [
            {"rule": "score.low_framing", "where": {"block": 1, "shot": shot, "t": 2.0},
             "units": 1, "hook": False, "source": "metric", "note": FACE},
            {"rule": "score.low_framing", "where": {"block": 2, "shot": "yt:26", "t": 6.0},
             "units": 1, "hook": False, "source": "metric", "note": "no template says this"}]},
        {"stage": "judge", "at": "2026-10-09T09:40:00+00:00", "findings": [
            {"rule": "score.judge_contradicts", "where": {"block": 6, "t": 15.0}, "units": 1,
             "source": "judge", "note": FACE}]}]


def test_a_new_log_s_note_ru_is_the_row_s():
    root = tree()
    d = root / "pipeline" / "reel" / BATCH
    doc = log_doc(root, d, "paper-dragon", _ru_stages(root, d, "paper-dragon"))
    # the factory's score() wrote note_ru into the log row (CF-0751)
    assert doc["score"]["log"][0]["note_ru"] == FACE_RU, doc["score"]["log"]
    # a row's own note_ru wins over the template: the API passes the row on
    doc["score"]["log"][0]["note_ru"] = "как записал лог"
    _w(d / "work" / "paper-dragon" / "plan.score.json", doc)
    st, s = get(client(root), f"reel/{BATCH}", "paper-dragon")
    assert st == 200, s
    f = s["findings"]
    assert f[0]["note"] == FACE and f[0]["note_ru"] == "как записал лог", f[0]
    assert f[1]["note_ru"] is None, f[1]                  # no template - no Russian
    assert f[0]["shot_ru"] == "mine cart" and f[0]["shot"].endswith("a04_mine-cart.mp4"), f[0]
    assert f[1]["shot_ru"] == "yt:26" and f[1]["shot"] == "yt:26", f[1]


def test_an_old_log_is_filled_by_the_factory_s_note_ru():
    root = tree()
    d = root / "pipeline" / "reel" / BATCH
    doc = log_doc(root, d, "paper-dragon", _ru_stages(root, d, "paper-dragon"))
    for key in ("log", "hard"):                           # as written before CF-0751
        doc["score"][key] = [{k: v for k, v in e.items() if k != "note_ru"}
                             for e in doc["score"].get(key) or []]
    _w(d / "work" / "paper-dragon" / "plan.score.json", doc)
    st, s = get(client(root), f"reel/{BATCH}", "paper-dragon")
    assert st == 200, s
    f = s["findings"]
    assert [x["rule"] for x in f] == ["score.low_framing", "score.low_framing",
                                      "score.judge_contradicts"], f
    assert f[0]["note_ru"] == FACE_RU, f[0]
    # the same words score.with_note_ru gives the old block
    from api import factory as fa
    assert fa.score_model().with_note_ru(doc["score"])["log"][0]["note_ru"] == FACE_RU
    # the judge's prose stays without Russian even when a template would match it
    assert f[2]["note"] == FACE and f[2]["note_ru"] is None, f[2]
    assert f[2]["shot_ru"] is None, f[2]


def test_a_hard_finding_s_note_ru():
    root = tree()
    rb = root / "pipeline" / "rebuilds" / tv.RB1
    log_doc(root, rb, "paper-dragon", [
        {"stage": "qc", "at": "2026-10-10T09:30:00+00:00", "findings": [
            {"rule": "score.hard.render_defect", "where": {}, "source": "metric",
             "note": "no video stream"}]}])
    st, s = get(client(root), f"rebuilds/{tv.RB1}", "paper-dragon")
    assert st == 200, s
    [h] = s["findings"]
    assert h["hard"] is True and h["note_ru"] == "нет видеодорожки" and h["shot_ru"] is None, h


def test_shot_ru():
    from api.videos import shot_ru
    assert shot_ru("a04_mine-cart.mp4") == "mine cart"
    assert shot_ru("/x/work/s/clips/a12_big_red-dog.mov") == "big red dog"
    assert shot_ru("yt:26") == "yt:26"
    assert shot_ru(None) is None and shot_ru("") is None


# --------------------------------------------------------------------- the contract
def test_the_contract_carries_the_score():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    path = "/api/batches/{channel}/{batch_id}/videos/{slug}/score"
    assert sorted(spec["paths"][path]) == ["get"], spec["paths"][path]
    resp = spec["paths"][path]["get"]["responses"]
    assert resp["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/VideoScore")
    assert resp["404"]["content"]["application/json"]["schema"]["$ref"].endswith("/BatchProblem")
    sch = spec["components"]["schemas"]
    assert {"tier", "score", "start", "threshold", "passed", "stopped_at", "prices_status",
            "tiers", "stages", "findings", "by_rule", "score_line", "source"} <= \
        set(sch["VideoScore"]["properties"])
    assert {"rule", "label_ru", "stage", "block", "t", "shot", "price", "units", "capped",
            "source", "note", "note_ru", "shot_ru", "hard", "forecast"} <= \
        set(sch["VideoScoreFinding"]["properties"])
    assert {"stage", "label_ru", "charged", "score_after", "tier_after", "at"} <= \
        set(sch["VideoScoreStage"]["properties"])
    assert set(sch["VideoScoreShort"]["properties"]) == {"tier", "score", "threshold", "passed",
                                                         "stopped_at", "source", "url"}
    assert "score" in sch["Video"]["properties"]
    assert "score_model" in sch["BatchVideos"]["properties"]
    assert "no_score" in sch["BatchProblem"]["properties"]["code"]["enum"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
    sys.exit(1 if failed else 0)
