#!/usr/bin/env python3
"""CC-0020: the statistics and the analyst in the command center's API, read
only (`api/analytics.py`; `GET /api/analytics`, `/analytics/{channel}/metrics`,
`/videos/{video_id}`, `/summary`, `/summary/{day}`, `/footage-wanted`,
`/studio`) over the factory's own readers - `metrics_store`, `metrics`,
`summary`, `footage_wanted`, `studio_read`.

In-process (starlette's TestClient) against a stand-in factory root in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`: `reel` and the stub
`demo`). **Nothing outside the temp dir is read or written**: the journal,
the acceptance record, the analytics store, the batches and the archive are
the temp tree's; the clock is fixed (`analytics.FACTORY_KW`); no network.

What is pinned:

* the contract: the seven routes, every one a GET only, version 0.48.0,
  `AnalyticsProblem` on the problems (the two Studio writes beside them are
  CC-0074's `api/studio_entry.py`, tests/test_cc_api_studio_entry.py);
* nothing writes: `api/analytics.py` names none of the analyst's writers, and
  every GET leaves the temp tree byte for byte as it was;
* the overview: the journal's channels, the last run, the summary days;
* the metrics: YouTube's window row (never the daily rows recombined), the
  daily count and last row, the last Studio read; an N the factory does not
  collect has no window; a video's series; an unknown video 404;
* the summary: `summary.build` for the day (the clock's Pacific yesterday by
  default), the style off the acceptance profile, saved days; the written day
  as it is; a bad day 422, a missing one 404; a broken store line 409;
* the footage wanted: a hunter's `no_source` topic is a row; packed batches
  only when asked (a missing archive is the factory's note);
* Studio: the settings, the last videos with their Studio links, the due line,
  the visits, the latest read per video; a channel without the settings gets
  the factory's refusal as `settings_error`;
* an unknown channel 404.
"""
import ast
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, _w, client, factory_tree     # noqa: E402

import api                                                         # noqa: E402
from api import analytics, factory                                 # noqa: E402

NOW = "2026-10-11T12:00:00Z"          # Pacific yesterday: 2026-10-10
DAY = "2026-10-10"
BATCH = "2026-09-30T0000Z"
V1, V2 = "AbCdEfGhIj0", "ZyXwVuTsRq9"
ROUTES = {"/api/analytics", "/api/analytics/{channel}/metrics",
          "/api/analytics/{channel}/videos/{video_id}", "/api/analytics/{channel}/summary",
          "/api/analytics/{channel}/summary/{day}", "/api/analytics/{channel}/footage-wanted",
          "/api/analytics/{channel}/studio",
          "/api/analytics/diversity"}                     # CC-0108
#: CC-0074: entering a Studio read - api/studio_entry.py, not this module.
STUDIO_WRITES = {"/api/analytics/{channel}/studio/record/plan",
                 "/api/analytics/{channel}/studio/record"}
#: What `api/analytics.py` never names: the analyst's writers and notices.
FORBIDDEN = {"cmd_collect", "merge", "merge_windows", "merge_studio", "append_run",
             "append_visit", "merge_events", "write", "parse_read", "record", "raise_notice",
             "write_needs_you", "_push", "_atomic_write", "write_text", "write_bytes", "unlink",
             "mkdir", "rename", "rmtree", "subprocess", "main", "api_data_auto",
             "refresh_journal", "fill", "stamp_md"}
SETTINGS = {"last_videos": 5, "insurance_hours": 24, "hook_min_gap_hours": 6}
PROFILE = {"pattern": "list", "rhythm": "hold", "hook_opener": None, "fact_kind": "production",
           "tier": "A"}


def upload(vid, slug, publish_at):
    return {"channel": "reel", "entry_id": f"reel/{BATCH}/{slug}", "batch_id": BATCH,
            "slug": slug, "video_id": vid, "publish_at": publish_at,
            "publish_day": publish_at[:10], "source": "api"}


def daily(vid, day, age, final=True):
    return {"channel": "reel", "video_id": vid, "entry_id": None, "day": day, "age": age,
            "views": 100, "engagedViews": 50, "averageViewPercentage": 61.5,
            "averageViewDuration": 20, "likes": 1, "subscribersGained": 0, "final": final,
            "collected_at": "2026-10-10T09:00:00Z"}


def window_row(vid):
    return {"channel": "reel", "video_id": vid, "entry_id": f"reel/{BATCH}/one",
            "window": "first7d", "first_days": 7, "start": "2026-09-30", "end": "2026-10-06",
            "complete": True, "views": 700, "engagedViews": 333, "averageViewPercentage": 58.2,
            "averageViewDuration": 19.5, "likes": 7, "subscribersGained": 1, "final": True,
            "collected_at": "2026-10-10T09:00:00Z",
            "source": "youtube-analytics reports.query, no dimensions"}


def studio_row(vid, viewed, read_at):
    return {"kind": "studio", "channel": "reel", "video_id": vid, "entry_id": None,
            "read_at": read_at, "hook": "daily", "period_text": "С момента публикации",
            "viewed_pct": viewed, "swiped_pct": None, "raw_lines": ["Досмотрели", f"{viewed} %"],
            "warnings": [], "note": None, "recorded_at": read_at}


def jsonl(path, rows):
    _w(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def world(studio_settings=True):
    """reel: two published videos in the journal (one with an accepted
    profile), daily rows and a YouTube window for the first, Studio reads, a
    run, a written summary, a batch whose hunter skipped a topic for footage."""
    root = factory_tree()
    cfg_p = root / "channels" / "reel.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    if studio_settings:
        cfg["analyst"] = {"studio_read": SETTINGS}
    _w(cfg_p, cfg)
    u1 = upload(V1, "one", "2026-09-30T01:00:00+03:00")
    u2 = upload(V2, "two", "2026-10-08T01:00:00+03:00")
    _w(root / "publish" / "uploads.json", {"uploads": [u1, u2]})
    _w(root / "publish" / "acceptance-log.json", {"acceptances": [
        {"entry_id": u1["entry_id"], "slug": "one", "channel": "reel", "batch_id": BATCH,
         "verdict": "accepted", "recorded_at": "2026-10-01T00:00:00Z", "profile": PROFILE}]})
    a = root / "analytics" / "reel"
    jsonl(a / "daily.jsonl", [daily(V1, "2026-09-30", 0), daily(V1, "2026-10-01", 1),
                              daily(V1, "2026-10-09", 9, final=False)])
    jsonl(a / "windows.jsonl", [window_row(V1)])
    jsonl(a / "studio.jsonl", [studio_row(V1, 70.1, "2026-10-08T10:00:00Z"),
                               studio_row(V1, 72.4, "2026-10-09T10:00:00Z")])
    jsonl(a / "studio_visits.jsonl", [
        {"read_at": "2026-10-09T10:00:00Z", "hook": "daily", "rights_read": True,
         "videos_read": 1, "videos_stored": 1, "channel": "reel", "task": "CF-0588"}])
    jsonl(a / "runs.jsonl", [{"collected_at": "2026-10-10T09:00:00Z", "end_day": "2026-10-09",
                              "outcome": "ok", "channel": "reel", "task": "CF-0020"}])
    su = factory.analyst_summary()                # the day `summary.py daily` wrote
    su.write(su.build("reel", date(2026, 10, 5), journal=root / "publish" / "uploads.json",
                      acceptance_log=root / "publish" / "acceptance-log.json",
                      store_root=root / "analytics"), root / "analytics")
    _w(root / "pipeline" / "reel" / BATCH / "01-trend-hunter.json", {
        "channel": "reel", "skipped_topics": [
            {"topic_id": "t-paper", "title": "Paper Dragon", "kind": "work",
             "reason_code": "no_source", "reason": "no footage at all"}]})
    return root


def setup():
    analytics.FACTORY_KW.clear()
    analytics.FACTORY_KW.update({"now": NOW, "archive": str(TMP / "no-archive-here")})


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def get(root, path, **params):
    r = client(root).get(path, params=params)
    return r.status_code, r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_statistics_routes_get_only():
    spec = client(factory_tree()).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    paths = {p: set(v) for p, v in spec["paths"].items()
             if p.startswith("/api/analytics") and p not in STUDIO_WRITES}
    assert all(set(spec["paths"][p]) == {"post"} for p in STUDIO_WRITES)
    assert set(paths) == ROUTES, set(paths) ^ ROUTES
    assert all(m == {"get"} for m in paths.values()), paths
    for p in ROUTES:
        ref = spec["paths"][p]["get"]["responses"]["404"]["content"]["application/json"]
        assert ref["schema"]["$ref"].endswith("/AnalyticsProblem"), (p, ref)


def _names(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr


def test_nothing_here_names_a_writer_and_every_get_writes_nothing():
    src = (ROOT / "api" / "analytics.py").read_text(encoding="utf-8")
    named = set(_names(ast.parse(src))) & FORBIDDEN
    assert not named, named
    setup()
    root = world()
    before = files(root)
    c = client(root)
    for path in ("/api/analytics", "/api/analytics/reel/metrics", f"/api/analytics/reel/videos/{V1}",
                 "/api/analytics/reel/summary", "/api/analytics/reel/summary/2026-10-05",
                 "/api/analytics/reel/footage-wanted?packed=true", "/api/analytics/reel/studio",
                 "/api/analytics/diversity?last=0"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.text)
    assert files(root) == before


def test_the_runlog_summary_stays_the_plain_import():
    """`summary.py` of the analyst loads as `analyst_summary`; a plain
    `import summary` (shared/runlog/no_waiting.py) still finds the runlog's."""
    import importlib.util
    factory.analyst_summary(), factory.studio_read(), factory.footage_wanted()
    have = sys.modules.get("summary")
    origin = have.__file__ if have else importlib.util.find_spec("summary").origin
    assert Path(origin).resolve() == (ROOT / "shared" / "runlog" / "summary.py").resolve(), origin
    assert "analyst_summary" in sys.modules


# --------------------------------------------------------------------- the overview
def test_the_overview_is_the_journal_s_channels_with_their_last_run():
    setup()
    code, got = get(world(), "/api/analytics")
    assert code == 200, got
    assert got["window_days"] == [7], got
    (reel,) = got["channels"]
    assert reel["channel"] == "reel" and reel["summary_days"] == ["2026-10-05"], reel
    assert reel["last_run"]["outcome"] == "ok" and reel["last_run"]["end_day"] == "2026-10-09"


# --------------------------------------------------------------------- the metrics
def test_the_metrics_are_youtube_s_window_never_the_daily_rows_summed():
    setup()
    root = world()
    code, got = get(root, "/api/analytics/reel/metrics")
    assert code == 200, got
    assert got["first_days"] == 7 and got["collected"] is True, got
    assert got["last_run"]["outcome"] == "ok"
    (v,) = got["videos"]                          # V2 has no row in the store
    assert v["video_id"] == V1 and v["daily_rows"] == 3, v
    w = v["window"]
    assert w["views"] == 700 and w["engagedViews"] == 333, w     # not 3 x 100
    assert w["from"] == "2026-09-30" and w["to"] == "2026-10-06" and w["days"] == 7, w
    assert v["last_daily"]["day"] == "2026-10-09" and v["last_daily"]["final"] is False, v
    assert v["studio"]["viewed_pct"] == 72.4, v                  # the later read
    code, got = get(root, "/api/analytics/reel/metrics", first_days=3)
    assert code == 200 and got["collected"] is False, got
    assert got["videos"][0]["window"] is None, got
    code, bad = get(root, "/api/analytics/reel/metrics", first_days=0)
    assert code == 422, bad


def test_a_video_s_series_and_an_unknown_video():
    setup()
    root = world()
    code, got = get(root, f"/api/analytics/reel/videos/{V1}")
    assert code == 200, got
    assert [r["day"] for r in got["daily"]] == ["2026-09-30", "2026-10-01", "2026-10-09"], got
    assert len(got["windows"]) == 1 and len(got["studio"]) == 2, got
    code, bad = get(root, f"/api/analytics/reel/videos/{V2}")
    assert code == 404 and bad["code"] == "unknown_video", bad


def test_a_broken_store_line_is_the_factory_s_refusal():
    setup()
    root = world()
    with (root / "analytics" / "reel" / "daily.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"video_id": "x"}\n')
    code, bad = get(root, "/api/analytics/reel/metrics")
    assert code == 409 and bad["code"] == "store_unreadable", bad
    assert "daily.jsonl:4" in bad["message"], bad


# --------------------------------------------------------------------- the summary
def test_the_summary_is_summary_build_for_the_pacific_yesterday():
    setup()
    root = world()
    code, got = get(root, "/api/analytics/reel/summary")
    assert code == 200, got
    assert got["day"] == DAY and got["first_days"] == 7 and got["task"] == "CF-0021", got
    assert got["saved"] is False and got["saved_days"] == ["2026-10-05"], got
    lines = {v["video_id"]: v for v in got["videos"]}
    assert set(lines) == {V1, V2}, lines
    one = lines[V1]
    assert one["style"]["pattern"] == "list" and one["style"]["hook_opener"] == "unknown", one
    assert one["window"]["engagedViews"] == 333 and one["studio"]["viewed_pct"] == 72.4, one
    assert lines[V2]["profile_found"] is False and "нет профиля" in lines[V2]["marks"], lines[V2]
    assert got["counts"]["videos"] == 2 and got["counts"]["with_api"] == 1, got["counts"]
    (grp,) = [g for g in got["aggregates"]["pattern"] if g["value"] == "list"]
    assert grp["computed_by"] == "factory" and grp["small_sample"] is True, grp
    code, got = get(root, "/api/analytics/reel/summary", day="2026-10-05")
    assert code == 200 and got["day"] == "2026-10-05" and got["saved"] is True, got


def test_the_written_summary_and_the_refusals():
    setup()
    root = world()
    code, got = get(root, "/api/analytics/reel/summary/2026-10-05")
    assert code == 200 and got["channel"] == "reel" and got["saved"] is True, got
    code, bad = get(root, "/api/analytics/reel/summary/2026-10-06")
    assert code == 404 and bad["code"] == "no_saved_summary", bad
    code, bad = get(root, "/api/analytics/reel/summary/yesterday")
    assert code == 422 and bad["code"] == "bad_day", bad
    code, bad = get(root, "/api/analytics/reel/summary", day="10.10.2026")
    assert code == 422 and bad["code"] == "bad_day", bad


# --------------------------------------------------------------------- the footage wanted
def test_the_footage_wanted_and_the_packed_batches_only_when_asked():
    setup()
    root = world()
    code, got = get(root, "/api/analytics/reel/footage-wanted")
    assert code == 200, got
    assert got["packed_read"] is False and got["batches"]["read"] == 1, got
    (row,) = got["rows"]
    assert row["name"] == "Paper Dragon" and row["kind"] == "work", row
    assert row["reasons"] == {"no_source": 1}, row
    assert not any(n.startswith("archive:") for n in got["notes"]), got["notes"]
    code, got = get(root, "/api/analytics/reel/footage-wanted", packed="true")
    assert code == 200 and got["packed_read"] is True, got
    assert any("no-archive-here" in n and "is not there" in n for n in got["notes"]), got["notes"]
    code, got = get(root, "/api/analytics/reel/footage-wanted", since="2026-10-01")
    assert code == 200 and got["rows"] == [] and got["batches"]["read"] == 0, got
    code, bad = get(root, "/api/analytics/reel/footage-wanted", since="Oct")
    assert code == 422 and bad["code"] == "bad_day", bad


# --------------------------------------------------------------------- Studio
def test_studio_says_what_to_read_and_what_was_read():
    setup()
    code, got = get(world(), "/api/analytics/reel/studio")
    assert code == 200, got
    assert got["settings"] == SETTINGS and got["settings_error"] is None, got
    assert got["n"] == 5 and [v["video_id"] for v in got["last_videos"]] == [V2, V1], got
    assert got["last_videos"][0]["studio_url"].startswith(f"https://studio.youtube.com/video/{V2}/")
    assert got["last_videos"][1]["published"] == "2026-09-29T22:00:00Z", got["last_videos"]
    assert got["due"]["due"] is True and "страховка" in got["due"]["line"], got["due"]
    assert got["last_rights_visit"]["read_at"] == "2026-10-09T10:00:00Z", got
    (latest,) = got["latest_reads"]
    assert latest["viewed_pct"] == 72.4, latest
    assert got["no_pipeline"] is None, got


def test_studio_without_settings_is_the_factory_s_refusal():
    setup()
    code, got = get(world(studio_settings=False), "/api/analytics/reel/studio")
    assert code == 200, got
    assert got["settings"] is None and "analyst.studio_read" in got["settings_error"], got
    assert got["last_videos"] == [] and got["due"] is None, got
    assert len(got["latest_reads"]) == 1, got


def test_an_unknown_channel_is_404():
    setup()
    root = world()
    for path in ("metrics", "summary", "footage-wanted", "studio", f"videos/{V1}"):
        code, bad = get(root, f"/api/analytics/nope/{path}")
        assert code == 404 and bad["code"] == "unknown_channel", (path, bad)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    analytics.FACTORY_KW.clear()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
