#!/usr/bin/env python3
"""CF-0021: the Analyst's daily summary - each video's metrics beside its style.

Nothing here reads the real `publish/` or `analytics/`: the upload journal, the
acceptance record and the metrics store are fixtures in a temp dir, passed to
`summary.py` by its hidden `--journal` / `--acceptance` / `--store`.

What is pinned:

* the join video_id -> entry_id -> acceptance row -> profile -> metrics, a
  rebuild's entry_id included; the style is read from `profile` only, a null
  field of it is `unknown`;
* a video without an acceptance row, without a profile, without API rows or
  without a Studio read is kept, marked, and listed under the gaps; a video not
  yet out is listed and left out of the aggregates;
* aggregates per style dimension: count, median / mean / min-max / stdev, and
  "выборка мала (<20)" under 20 videos, gone at 20; values in name order;
* the window is the first N days (`--first-days`) as YouTube computed it - the
  stored `windows.jsonl` row (CF-0624), never a sum or a view-weighted average
  of the daily rows; no row is "no API metrics" with the reason;
* group statistics say they are the factory's (`computed_by: factory`,
  «посчитано фабрикой») beside YouTube's per-video numbers;
* a non-final day marks the video and the group; a video younger than N days
  is marked as an incomplete window;
* a second channel gets its own files and nothing of the first;
* the day's files are rewritten whole: a second run gives the same bytes;
  Studio reads after the summary day are not used.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "analyst"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))

import metrics_store as store       # noqa: E402
import summary                      # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("analyst-summary-test-")
_n = [0]
DAY = "2026-10-10"
CH = "example-film"


def profile(pattern="list", rhythm="hold", hook_opener="wildest-fact", fact_kind="production",
            tier="B"):
    return {"task": "CF-0440", "pattern": pattern, "rhythm": rhythm, "hook_opener": hook_opener,
            "fact_kind": fact_kind, "tier": tier, "score": 80, "problem": None}


def upload(vid, slug, channel=CH, batch="2026-09-30T0000Z", publish_at="2026-10-01T01:00:00+03:00",
           entry_id=None, **extra):
    r = {"channel": channel, "entry_id": entry_id or f"{channel}/{batch}/{slug}", "batch_id": batch,
         "slug": slug, "video_id": vid, "publish_at": publish_at,
         "publish_day": publish_at[:10], "source": "api"}
    r.update(extra)
    return r


def acc_row(up, prof="default", verdict="accepted"):
    r = {"entry_id": up["entry_id"], "slug": up["slug"], "channel": up["channel"],
         "batch_id": up["batch_id"], "verdict": verdict, "recorded_at": "2026-10-01T00:00:00Z"}
    if prof == "default":
        r["profile"] = profile()
    elif prof is not None:
        r["profile"] = prof
    return r


def daily(vid, ages, channel=CH, first="2026-09-30", final=True, views=100, engaged=50, pct=60.0):
    from datetime import date, timedelta
    d0 = date.fromisoformat(first)
    out = []
    for a in ages:
        f = final(a) if callable(final) else final
        v = views(a) if callable(views) else views
        out.append({"channel": channel, "video_id": vid, "entry_id": None,
                    "day": (d0 + timedelta(days=a)).isoformat(), "age": a, "views": v,
                    "engagedViews": engaged(a) if callable(engaged) else engaged,
                    "averageViewPercentage": pct(a) if callable(pct) else pct,
                    "averageViewDuration": 20, "likes": 1, "subscribersGained": 0,
                    "final": f, "collected_at": "2026-10-10T09:00:00Z"})
    return out


def yt(rows, n=7, pct=60.0, end=None):
    """Stand-in YouTube Analytics (CF-0624): the window rows `metrics.py
    collect` would store for these daily rows - counts over the period, and
    YouTube's own average `pct` (given, not derived from the daily rows)."""
    from datetime import date, timedelta
    out = []
    for vid in sorted({r["video_id"] for r in rows}):
        vr = [r for r in rows if r["video_id"] == vid]
        start = min(date.fromisoformat(r["day"]) - timedelta(days=r["age"]) for r in vr)
        full = start + timedelta(days=n - 1)
        last = min(full, date.fromisoformat(end) if end else
                   max(date.fromisoformat(r["day"]) for r in vr))
        inside = [r for r in vr if r["age"] < n and date.fromisoformat(r["day"]) <= last]
        out.append({"channel": vr[0]["channel"], "video_id": vid, "entry_id": None,
                    "window": f"first{n}d", "first_days": n, "start": start.isoformat(),
                    "end": last.isoformat(), "complete": last == full,
                    "views": sum(r["views"] for r in inside),
                    "engagedViews": sum(r["engagedViews"] for r in inside),
                    "averageViewPercentage": pct(vid) if callable(pct) else pct,
                    "averageViewDuration": 19.5, "likes": len(inside), "subscribersGained": 0,
                    "final": last == full and all(r["final"] for r in inside),
                    "collected_at": "2026-10-10T09:00:00Z", "source": store.WINDOW_SOURCE})
    return out


def studio(vid, viewed, read_at="2026-10-09T10:00:00Z", channel=CH):
    return {"kind": "studio", "channel": channel, "video_id": vid, "entry_id": None,
            "read_at": read_at, "hook": "daily", "period_text": "С момента публикации",
            "viewed_pct": viewed, "swiped_pct": round(100 - viewed, 1), "raw_lines": [],
            "warnings": [], "recorded_at": read_at}


def fixture(uploads, accs, dailies=(), studios=(), windows=None):
    """`windows` - the stored YouTube window rows; None: what the stand-in
    YouTube (`yt`) answers for `dailies`."""
    _n[0] += 1
    base = TMP / f"f{_n[0]}"
    base.mkdir(parents=True)
    journal = base / "uploads.json"
    journal.write_text(json.dumps({"note": "t", "task": "CF-0586", "format": 2, "uploads": uploads}))
    acc = base / "acceptance-log.json"
    acc.write_text(json.dumps({"note": "t", "task": "CF-0328", "acceptances": accs}))
    st = base / "analytics"
    by_ch = {}
    for r in dailies:
        by_ch.setdefault(r["channel"], []).append(r)
    for ch, rows in by_ch.items():
        store.merge(ch, rows, st)
    by_ch = {}
    for r in (yt(list(dailies)) if windows is None else windows):
        by_ch.setdefault(r["channel"], []).append(r)
    for ch, rows in by_ch.items():
        store.merge_windows(ch, rows, st)
    by_ch = {}
    for r in studios:
        by_ch.setdefault(r["channel"], []).append(r)
    for ch, rows in by_ch.items():
        store.merge_studio(ch, rows, st)
    return {"journal": journal, "acceptance": acc, "store": st}


def run(fx, *argv, cmd="daily"):
    out = io.StringIO()
    args = [cmd] + list(argv) + ["--journal", str(fx["journal"]), "--acceptance", str(fx["acceptance"]),
                                 "--store", str(fx["store"])]
    if cmd == "daily" and "--day" not in argv:
        args += ["--day", DAY]
    code = summary.main(args, out=out)
    return code, out.getvalue()


def report(fx, channel=CH, first_days=7):
    return summary.build(channel, summary.date.fromisoformat(DAY), first_days, fx["journal"],
                         fx["acceptance"], fx["store"])


def by_vid(rep):
    return {ln["video_id"]: ln for ln in rep["videos"]}


def group(rep, dim, value):
    return next(g for g in rep["aggregates"][dim] if g["value"] == value)


# ---------------------------------------------------------------- the join

def test_join_video_to_profile_to_metrics():
    a = upload("AAAAAAAAAAA", "alpha")
    b = upload("BBBBBBBBBBB", "beta", entry_id="rebuilds/2026-09-30T0000Z/beta")
    fx = fixture([a, b],
                 [acc_row(a, profile("contrast", "staccato", "sounds-made-up", "casting", "A")),
                  acc_row(b, profile("explainer", "even", None, "production", None))],
                 daily("AAAAAAAAAAA", range(3)) + daily("BBBBBBBBBBB", range(3)),
                 [studio("AAAAAAAAAAA", 71.5)])
    rep = report(fx)
    v = by_vid(rep)
    assert v["AAAAAAAAAAA"]["style"] == {"pattern": "contrast", "rhythm": "staccato",
                                         "hook_opener": "sounds-made-up", "fact_kind": "casting",
                                         "tier": "A"}, v["AAAAAAAAAAA"]
    assert v["AAAAAAAAAAA"]["window"]["engagedViews"] == 150
    assert v["AAAAAAAAAAA"]["studio"]["viewed_pct"] == 71.5
    # a rebuild's entry id joins by the stored key; a null profile field is unknown
    assert v["BBBBBBBBBBB"]["profile_found"] and v["BBBBBBBBBBB"]["style"]["hook_opener"] == "unknown"
    assert v["BBBBBBBBBBB"]["style"]["tier"] == "unknown"
    assert rep["counts"]["with_profile"] == 2 and rep["counts"]["with_api"] == 2
    code, out = run(fx, cmd="join")
    assert code == 0 and "2 video(s) in the journal, 2 with a profile" in out, out


def test_style_comes_from_the_profile_only():
    src = (AGENT / "summary.py").read_text()
    assert "rotation/ledger" in src  # named in the docstring as not read
    code = src.split('"""', 2)[2]
    assert "ledger" not in code and "05-video-editor" not in code, \
        "the style has one source - the acceptance profile"


# ---------------------------------------------------------------- gaps

def test_video_without_profile_or_metrics_is_kept_and_listed():
    a = upload("AAAAAAAAAAA", "alpha")
    b = upload("BBBBBBBBBBB", "beta")          # no acceptance row
    c = upload("CCCCCCCCCCC", "gamma")         # acceptance row without a profile
    d = upload("DDDDDDDDDDD", "delta")         # profile, no metrics at all
    e = upload("EEEEEEEEEEE", "eps", publish_at="2026-10-20T01:00:00+03:00")   # not out yet
    fx = fixture([a, b, c, d, e], [acc_row(a), acc_row(c, prof=None), acc_row(d), acc_row(e)],
                 daily("AAAAAAAAAAA", range(3)) + daily("BBBBBBBBBBB", range(3))
                 + daily("CCCCCCCCCCC", range(3)),
                 [studio(x, 60.0) for x in ("AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC")])
    rep = report(fx)
    v = by_vid(rep)
    assert len(rep["videos"]) == 5
    assert "нет профиля" in v["BBBBBBBBBBB"]["marks"] and v["BBBBBBBBBBB"]["style"]["pattern"] == "unknown"
    assert v["BBBBBBBBBBB"]["profile_gap"] == "нет строки приёмки"
    assert v["CCCCCCCCCCC"]["profile_gap"] == "у строки приёмки нет profile"
    assert "нет метрик API" in v["DDDDDDDDDDD"]["marks"] and "нет чтения Studio" in v["DDDDDDDDDDD"]["marks"]
    assert "ещё не вышел" in v["EEEEEEEEEEE"]["marks"]
    assert {g["video_id"] for g in rep["gaps"]["no_profile"]} == {"BBBBBBBBBBB", "CCCCCCCCCCC"}
    assert {g["video_id"]: g["why"] for g in rep["gaps"]["no_metrics"]} == {
        "DDDDDDDDDDD": "нет строк в daily.jsonl", "EEEEEEEEEEE": "ещё не вышел"}
    # the unpublished one is not counted; the profileless ones count under unknown
    assert sum(g["videos"] for g in rep["aggregates"]["pattern"]) == 4
    assert group(rep, "pattern", "unknown")["videos"] == 2
    assert [g["value"] for g in rep["aggregates"]["pattern"]][-1] == "unknown"
    md = summary.render_md(rep)
    for vid in ("AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC", "DDDDDDDDDDD", "EEEEEEEEEEE"):
        assert vid in md, vid
    assert "- нет профиля: `BBBBBBBBBBB`" in md and "- нет метрик API: `DDDDDDDDDDD`" in md, md


# ---------------------------------------------------------------- aggregates

def test_aggregates_and_small_sample_mark():
    ups, accs, ds, ss = [], [], [], []
    for i in range(20):                       # 20 lists: the mark goes away
        u = upload(f"L{i:010d}", f"list{i}")
        ups.append(u)
        accs.append(acc_row(u, profile("list")))
        ds += daily(u["video_id"], range(7), engaged=i + 1)
        ss.append(studio(u["video_id"], 50.0 + i))
    for i, eng in enumerate((10, 20, 60)):    # 3 contrasts: per-day engaged
        u = upload(f"C{i:010d}", f"contrast{i}")
        ups.append(u)
        accs.append(acc_row(u, profile("contrast")))
        ds += daily(u["video_id"], range(7), engaged=eng)
        ss.append(studio(u["video_id"], 70.0))
    rep = report(fx := fixture(ups, accs, ds, ss))
    c = group(rep, "pattern", "contrast")
    e = c["metrics"]["engagedViews"]
    assert c["videos"] == 3 and e["n"] == 3
    assert (e["median"], e["mean"], e["min"], e["max"]) == (140.0, 210.0, 70.0, 420.0), e
    assert e["stdev"] == 185.2, e
    assert c["small_sample"]
    lst = group(rep, "pattern", "list")
    assert lst["videos"] == 20 and not lst["small_sample"], lst
    assert lst["metrics"]["viewed_pct"]["median"] == 59.5
    assert [g["value"] for g in rep["aggregates"]["pattern"]] == ["contrast", "list"], "name order"
    md = summary.render_md(rep)
    row = next(x for x in md.splitlines() if x.startswith("| contrast |"))
    assert "выборка мала (<20)" in row, row
    row = next(x for x in md.splitlines() if x.startswith("| list |"))
    assert "выборка мала" not in row, row
    for dim in summary.DIMENSIONS:
        assert f"### {dim}" in md
    code, out = run(fx, "--no-write")
    assert code == 0 and not (fx["store"] / CH / "summary").exists()


def test_one_video_has_no_stdev():
    a = upload("AAAAAAAAAAA", "alpha")
    rep = report(fixture([a], [acc_row(a)], daily("AAAAAAAAAAA", range(7))))
    s = group(rep, "tier", "B")["metrics"]["engagedViews"]
    assert s["n"] == 1 and s["stdev"] is None and s["median"] == 350.0
    assert group(rep, "tier", "B")["metrics"]["viewed_pct"]["n"] == 0


# ---------------------------------------------------------------- the window

def test_window_is_youtubes_row_never_the_daily_rows_recombined():
    """CF-0624: the averages are what YouTube said for the window; where it said
    nothing the summary says so - it never falls back to the daily rows."""
    a = upload("AAAAAAAAAAA", "alpha")
    ds = daily("AAAAAAAAAAA", range(10), views=lambda age: 100 if age == 0 else 300,
               engaged=lambda age: age + 1, pct=lambda age: 40.0 if age == 0 else 80.0)
    fx = fixture([a], [acc_row(a)], ds, windows=yt(ds, pct=66.6))
    v = by_vid(report(fx))["AAAAAAAAAAA"]
    w = v["window"]
    # the view-weighted average of the daily rows would be 74.29; YouTube said 66.6
    assert (w["days"], w["engagedViews"], w["views"]) == (7, 28, 1900), w
    assert w["averageViewPercentage"] == 66.6 and w["source"] == "youtube", w
    assert w["averageViewDuration"] == 19.5, w
    md = summary.render_md(report(fx))
    assert "66.6 %" in md, md
    # a window the collection does not ask for: no numbers, the reason named
    v = by_vid(report(fx, first_days=2))["AAAAAAAAAAA"]
    assert v["window"] is None and "нет метрик API" in v["marks"], v
    assert "не собирается" in v["api_gap"], v
    # daily rows but no window row yet (collected before CF-0624): no numbers either
    rep = report(fixture([a], [acc_row(a)], ds, windows=[]))
    v = by_vid(rep)["AAAAAAAAAAA"]
    assert v["window"] is None and "не пересчитывается" in v["api_gap"], v
    assert rep["counts"]["with_api"] == 0 and rep["gaps"]["no_metrics"][0]["why"] == v["api_gap"]
    assert group(rep, "pattern", "list")["metrics"]["averageViewPercentage"]["n"] == 0
    # a window row reaching past the summary day is not that day's window
    late = yt(ds, end="2026-10-06")
    late[0]["end"] = "2026-10-11"
    v = by_vid(report(fixture([a], [acc_row(a)], ds, windows=late)))["AAAAAAAAAAA"]
    assert v["window"] is None and "позже" in v["api_gap"], v
    code, _ = run(fixture([a], [acc_row(a)]), "--first-days", "0")
    assert code == summary.EXIT_ERROR


def test_group_statistics_are_marked_as_the_factorys():
    a, b = upload("AAAAAAAAAAA", "alpha"), upload("BBBBBBBBBBB", "beta")
    ds = daily("AAAAAAAAAAA", range(7)) + daily("BBBBBBBBBBB", range(7), engaged=10)
    rep = report(fixture([a, b], [acc_row(a), acc_row(b)], ds))
    assert rep["aggregates_computed_by"] == "factory" and "III.E.2.a" in rep["aggregates_note"]
    assert all(g["computed_by"] == "factory" for gs in rep["aggregates"].values() for g in gs)
    md = summary.render_md(rep)
    assert "## По измерениям стиля — посчитано фабрикой" in md, md
    # YouTube's own per-video numbers are beside them, in the video table
    assert md.index("## Ролики") < md.index("посчитано фабрикой")
    assert "| 350 | 60 % |" in md and "| 70 | 60 % |" in md, md


# ---------------------------------------------------------------- non-final days

def test_non_final_days_and_young_videos_are_marked():
    a = upload("AAAAAAAAAAA", "alpha")
    b = upload("BBBBBBBBBBB", "beta", publish_at="2026-10-08T01:00:00+03:00")
    ds = daily("AAAAAAAAAAA", range(7), final=lambda age: age < 5) \
        + daily("BBBBBBBBBBB", range(3), first="2026-10-07", final=False)
    rep = report(fixture([a, b], [acc_row(a), acc_row(b)], ds))
    v = by_vid(rep)
    assert v["AAAAAAAAAAA"]["window"]["final"] is False and "не оконч." in v["AAAAAAAAAAA"]["marks"]
    assert v["AAAAAAAAAAA"]["window"]["complete"] is True
    assert v["BBBBBBBBBBB"]["window"]["complete"] is False
    assert "окно < 7 д" in v["BBBBBBBBBBB"]["marks"], v["BBBBBBBBBBB"]
    g = group(rep, "pattern", "list")
    assert (g["not_final"], g["incomplete"]) == (2, 1), g
    assert rep["counts"]["not_final"] == 2
    md = summary.render_md(rep)
    assert "неоконч.: 2" in md and "окно < 7 д: 1" in md, md


# ---------------------------------------------------------------- channels and files

def test_second_channel_gets_its_own_files():
    a = upload("AAAAAAAAAAA", "alpha")
    b = upload("BBBBBBBBBBB", "beta", channel="example-tech")
    fx = fixture([a, b], [acc_row(a, profile("list")), acc_row(b, profile("explainer"))],
                 daily("AAAAAAAAAAA", range(3)) + daily("BBBBBBBBBBB", range(3), channel="example-tech"),
                 [studio("BBBBBBBBBBB", 80.0, channel="example-tech")])
    code, out = run(fx)
    assert code == 0 and "example-film 2026-10-10" in out and "example-tech 2026-10-10" in out, out
    one = json.loads((fx["store"] / CH / "summary" / f"{DAY}.json").read_text())
    two = json.loads((fx["store"] / "example-tech" / "summary" / f"{DAY}.json").read_text())
    assert [v["video_id"] for v in one["videos"]] == ["AAAAAAAAAAA"]
    assert [v["video_id"] for v in two["videos"]] == ["BBBBBBBBBBB"]
    assert two["videos"][0]["studio"]["viewed_pct"] == 80.0 and one["videos"][0]["studio"] is None
    assert "example-tech" not in (fx["store"] / CH / "summary" / f"{DAY}.md").read_text()
    # --channel writes one
    fx2 = fixture([a, b], [acc_row(a), acc_row(b)])
    code, out = run(fx2, "--channel", "example-tech")
    assert code == 0 and "example-film" not in out
    assert not (fx2["store"] / CH).exists() and (fx2["store"] / "example-tech" / "summary").is_dir()


def test_studio_without_swiped_or_with_not_enough_data_is_shown_not_broken():
    """CF-0639: Studio may give only «Продолжили смотреть» (swiped null), or no
    share yet for a new video (both null, a `note`)."""
    a = upload("AAAAAAAAAAA", "alpha")
    b = upload("BBBBBBBBBBB", "beta")
    only_viewed = dict(studio("AAAAAAAAAAA", 52.1), swiped_pct=None,
                       raw_lines=["Продолжили смотреть", "52,1 %"])
    no_data = dict(studio("BBBBBBBBBBB", 0.0), viewed_pct=None, swiped_pct=None,
                   raw_lines=["Удержание аудитории",
                              "Статистика пока недоступна: недостаточно данных."],
                   note="not enough data yet")
    fx = fixture([a, b], [acc_row(a), acc_row(b)],
                 daily("AAAAAAAAAAA", range(3)) + daily("BBBBBBBBBBB", range(3)),
                 [only_viewed, no_data])
    code, out = run(fx)
    assert code == 0, out
    doc = json.loads((fx["store"] / CH / "summary" / f"{DAY}.json").read_text())
    v = {x["video_id"]: x for x in doc["videos"]}
    assert v["AAAAAAAAAAA"]["studio"]["viewed_pct"] == 52.1, v
    assert v["AAAAAAAAAAA"]["studio"]["swiped_pct"] is None, v
    assert "Studio: недостаточно данных" not in v["AAAAAAAAAAA"]["marks"], v
    assert v["BBBBBBBBBBB"]["studio"]["viewed_pct"] is None, v
    assert "Studio: недостаточно данных" in v["BBBBBBBBBBB"]["marks"], v
    assert "нет чтения Studio" not in v["BBBBBBBBBBB"]["marks"], v
    md = (fx["store"] / CH / "summary" / f"{DAY}.md").read_text()
    assert "52.1 %" in md and "Studio: недостаточно данных" in md, md


def test_the_day_file_is_idempotent_and_studio_after_the_day_is_ignored():
    a = upload("AAAAAAAAAAA", "alpha")
    fx = fixture([a], [acc_row(a)], daily("AAAAAAAAAAA", range(7)),
                 [studio("AAAAAAAAAAA", 61.0, "2026-10-09T10:00:00Z"),
                  studio("AAAAAAAAAAA", 99.0, "2026-10-11T10:00:00Z")])
    d = fx["store"] / CH / "summary"
    assert run(fx)[0] == 0
    first = {p.name: p.read_bytes() for p in d.iterdir()}
    assert sorted(first) == [f"{DAY}.json", f"{DAY}.md"], sorted(first)
    assert run(fx)[0] == 0
    assert {p.name: p.read_bytes() for p in d.iterdir()} == first, "a second run changed the files"
    doc = json.loads(first[f"{DAY}.json"])
    assert doc["videos"][0]["studio"]["viewed_pct"] == 61.0 and doc["task"] == "CF-0021"
    assert doc["first_days"] == 7 and doc["min_sample"] == 20
    # new data for the same day replaces the file, never adds one
    store.merge(CH, daily("AAAAAAAAAAA", range(7), engaged=7), fx["store"])
    store.merge_windows(CH, yt(daily("AAAAAAAAAAA", range(7), engaged=7)), fx["store"])
    run(fx)
    assert sorted(p.name for p in d.iterdir()) == [f"{DAY}.json", f"{DAY}.md"]
    assert json.loads((d / f"{DAY}.json").read_text())["videos"][0]["window"]["engagedViews"] == 49


def test_skill_names_the_summary_after_collect():
    skill = (AGENT / "SKILL.md").read_text()
    assert "python3 agents/analyst/summary.py daily" in skill
    i, j = skill.index("metrics.py collect`, **затем**"), skill.index("summary.py daily`")
    assert i < j
    assert "example-film" not in (AGENT / "summary.py").read_text().split('"""', 2)[2], \
        "no channel spelled in the code"


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
