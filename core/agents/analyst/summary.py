#!/usr/bin/env python3
"""CF-0021: the daily summary - each video's metrics beside the style it was made in.

Grill of 2026-10-06 (milestones 2.1-2.3): every video has carried its style
since 1.0 so that one day its numbers could be read against it. This module
does the reading and nothing more. Version 2.1's exit is "the summary works";
the decision "the data beat the taste" is a later checkpoint, at 20-30 videos
per style - so the summary shows how big every group is, marks a small one,
and never ranks, picks a winner or writes a conclusion.

The join, one key per hop and no guessing
-----------------------------------------

    publish/uploads.json          video_id -> entry_id     (upload_records.py, CF-0586)
    publish/acceptance-log.json   entry_id -> profile      (acceptance.row_keys(), CF-0328/CF-0440)
    analytics/<ch>/windows.jsonl  video_id -> YouTube's window row (metrics_store.window(), CF-0624)
    analytics/<ch>/daily.jsonl    video_id -> daily series (only to say why a window is missing)
    analytics/<ch>/studio.jsonl   video_id -> last read    (metrics_store.latest_studio(), CF-0588)

A video the journal has is never dropped: no acceptance row, a row without a
`profile`, no daily rows, no Studio read - each is a mark on the video's line
and a line of its own under "Пробелы". Its style then counts as `unknown`.

The style - one source of truth per field
-----------------------------------------
Every dimension is read from the acceptance row's `profile` (CF-0440,
`shared/runlog/publish_profile.py`), which was copied from the batch's own
artifacts when the verdict was filed and outlives the batch:

    pattern      profile.pattern       (03 scripts[].pattern)
    rhythm       profile.rhythm        (03 scripts[].pattern rhythm)
    hook_opener  profile.hook_opener   (03 scripts[].hook_opener_id, CF-0424)
    fact_kind    profile.fact_kind     (03 fact.kind, or derived - fact_kind_from says)
    tier         profile.tier          (05/06 score, CF-0434)

Nothing else is read for them. The rotation ledger
(`rotation/ledger/<ch>.csv`) has pattern and rhythm only, as the rotation
*assigned* them, and a row for a fraction of the videos; `05-video-editor.json`
leaves the disk with its batch after 31 days. Mixing either in would give one
field two sources that can disagree. A field the profile leaves `null` (a video
made before hook openers or scores existed) is `unknown` here - shown, not
filled; `runlog profile --fill` is the one way a profile is completed.

The metrics
-----------
* API window "first N days" (`--first-days`, default 7): `engagedViews` (the
  comparison metric, CF-0020), `averageViewPercentage`, plus `views` - all of
  them YouTube's own numbers for the window, the row `metrics.py collect` asked
  as one period (CF-0624, III.E.4.h(i) of the YouTube API policy: no "similar,
  independently calculated data"). Nothing here sums or averages the daily
  rows into a window: a video without a window row (collected before CF-0624,
  a window not yet answered, an N that `metrics_store.WINDOW_DAYS` does not
  collect, a row reaching past the summary day) has no API metrics, marked and
  listed under the gaps with the reason. A window not final yet is marked
  `не оконч.`; one shorter than N days (a young video) `окно < N д`.
* Studio "viewed" share (`viewed_pct`, CF-0588): the last read up to the
  summary day. It is a share over the period Studio named (usually "since
  published"), a snapshot of its read time - not the N-day window; the period
  and the read date are printed beside it.

Aggregates: for each dimension and each value of it, the number of videos and,
per metric, n / median / mean / min-max / standard deviation (n >= 2). A group
under `MIN_SAMPLE` (20) videos with that metric carries "выборка мала (<20)".
Values are listed by name, never sorted by a metric. They are the factory's
own statistics over the owner's own videos (III.E.2.a: the channels of one
content owner) and say so - «посчитано фабрикой», `computed_by: factory` -
shown beside YouTube's per-video numbers they come from (the "Ролики" table),
never in their place (CF-0624, the example of III.E.4.h).

Output: `analytics/<ch>/summary/<day>.md` for a person and `<day>.json` beside
it for a machine (the 2.2 console, CF-0590). Both are rewritten whole (temp
file + rename) and carry nothing that changes between two runs on the same
data, so running the day again gives the same bytes.

    python3 agents/analyst/summary.py daily [--channel C] [--day YYYY-MM-DD] [--first-days N] [--print] [--no-write]
    python3 agents/analyst/summary.py join  [--channel C]       # how the journal joins to profiles and metrics
"""
import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "agents" / "publisher", ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import metrics                                                  # noqa: E402
import metrics_store as store                                   # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0021"
SUMMARY_DIR = "summary"
DEFAULT_FIRST_DAYS = 7
MIN_SAMPLE = 20
UNKNOWN = "unknown"
COMPUTED_BY = "factory"
AGG_NOTE = ("посчитано фабрикой: статистики групп по числам YouTube Analytics роликов этого же "
            "владельца (III.E.2.a); исходные числа YouTube - по роликам в таблице «Ролики» и в "
            "windows.jsonl")
DIMENSIONS = ("pattern", "rhythm", "hook_opener", "fact_kind", "tier")
# metric key -> (where it comes from, label)
METRIC_LABELS = {
    "engagedViews": "engagedViews",
    "averageViewPercentage": "% просмотра",
    "viewed_pct": "досмотрели %",
}
AGG_METRICS = tuple(METRIC_LABELS)
EXIT_OK, EXIT_ERROR = 0, 2


def _acceptance():
    import acceptance                                           # noqa: PLC0415
    return acceptance


# ------------------------------------------------------------------ the join

def acceptance_index(path=None):
    """{key: acceptance row} for every key a row answers to. Where two rows
    answer to one key the accepted one wins, then the later recorded."""
    acc = _acceptance()
    rows = acc.entries(path=path)
    order = sorted(rows, key=lambda r: (r.get("verdict") == acc.ACCEPTED, str(r.get("recorded_at") or "")))
    out = {}
    for r in order:
        for k in acc.row_keys(r):
            out[k] = r
    return out


def style_of(profile):
    """The five dimensions from the profile, `unknown` where it has none."""
    p = profile or {}
    return {d: (p.get(d) if p.get(d) not in (None, "") else UNKNOWN) for d in DIMENSIONS}


def join(channel, journal=None, acceptance_log=None, store_root=None, index=None):
    """One record per journal row of the channel (journal order): the upload,
    its acceptance row's profile (or why there is none), its daily rows and
    its Studio reads. Nothing is filtered out here."""
    index = acceptance_index(acceptance_log) if index is None else index
    daily = store.read_daily(channel, store_root)
    windows = store.read_windows(channel, store_root)
    studio = store.read_studio(channel, store_root)
    out = []
    for u in upload_records.uploads(journal, channel=channel):
        vid, eid = u.get("video_id"), u.get("entry_id")
        arow = index.get(eid) if eid else None
        profile = (arow or {}).get("profile") or None
        if not eid:
            profile_gap = "в журнале нет entry_id"
        elif arow is None:
            profile_gap = "нет строки приёмки"
        elif not profile:
            profile_gap = "у строки приёмки нет profile"
        else:
            profile_gap = profile.get("problem") or None
        out.append({
            "upload": u, "video_id": vid, "entry_id": eid, "slug": u.get("slug"),
            "profile": profile, "profile_gap": profile_gap,
            "daily": [r for r in daily if r["video_id"] == vid],
            "windows": [r for r in windows if r["video_id"] == vid],
            "studio": [r for r in studio if r["video_id"] == vid],
        })
    return out


def channels_of(journal=None):
    return sorted({r.get("channel") for r in upload_records.uploads(journal) if r.get("channel")})


# ------------------------------------------------------------------ one video

def _published(u, day):
    """(published by the end of `day`?, first Pacific day) - the Analyst's own
    reading of the journal row (metrics.publication)."""
    end = metrics._now(f"{day.isoformat()}T23:59:59-08:00")
    return metrics.publication(u, end)


def video_line(rec, day, first_days):
    u = rec["upload"]
    published, first = _published(u, day)
    win = store.window(rec.get("windows") or [], rec["video_id"], first_days, up_to=day)
    reads = [r for r in rec["studio"]
             if store._instant(r["read_at"], "read_at").date() <= day]
    last = store.latest_studio(reads, rec["video_id"]) if reads else None
    age_days = (day - first).days + 1 if first else None
    marks = []
    if u.get("removed_at"):
        marks.append("снят")
    if published is False:
        marks.append("ещё не вышел")
    elif published is None:
        marks.append("нет даты публикации")
    if rec["profile_gap"] and not rec["profile"]:
        marks.append("нет профиля")
    if published and win is None:
        marks.append("нет метрик API")
    if win is not None and not win["final"]:
        marks.append("не оконч.")
    if win is not None and not win["complete"]:
        marks.append(f"окно < {first_days} д")
    if published and last is None:
        marks.append("нет чтения Studio")
    elif last is not None and last.get("note"):                 # CF-0639
        marks.append("Studio: недостаточно данных")
    return {
        "video_id": rec["video_id"], "entry_id": rec["entry_id"], "slug": rec["slug"],
        "published": first.isoformat() if first else None,
        "age_days": age_days, "removed": bool(u.get("removed_at")),
        "is_published": bool(published),
        "style": style_of(rec["profile"]),
        "profile_found": bool(rec["profile"]), "profile_gap": rec["profile_gap"],
        "window": None if win is None else {
            "days": win["days"], "from": win["from"], "to": win["to"], "final": win["final"],
            "complete": bool(win["complete"]), "source": "youtube",
            "views": win["views"], "engagedViews": win["engagedViews"],
            "averageViewPercentage": win["averageViewPercentage"],
            "averageViewDuration": win["averageViewDuration"],
        },
        "api_gap": None if win is not None or not published else
        api_gap(rec, first_days, day),
        "studio": None if last is None else {
            "viewed_pct": last.get("viewed_pct"), "swiped_pct": last.get("swiped_pct"),
            "period_text": last.get("period_text"), "read_at": last.get("read_at"),
            "note": last.get("note"),
        },
        "marks": marks,
    }


def api_gap(rec, first_days, day):
    """Why a published video has no YouTube window on `day` (CF-0624) - the
    daily rows are never a substitute."""
    if not rec.get("daily") and not rec.get("windows"):
        return "нет строк в daily.jsonl"
    if first_days not in store.WINDOW_DAYS:
        return (f"окно {first_days} д не собирается (metrics_store.WINDOW_DAYS = "
                f"{', '.join(map(str, store.WINDOW_DAYS))})")
    name = store.window_name(first_days)
    if any(r["window"] == name for r in rec.get("windows") or []):
        return f"окно YouTube снято по дню позже {day.isoformat()}"
    return (f"нет окна YouTube за {first_days} д в windows.jsonl (collect его ещё не спросил) - "
            f"из дневных строк не пересчитывается")


def metric_value(line, metric):
    if metric == "viewed_pct":
        return (line["studio"] or {}).get("viewed_pct")
    return (line["window"] or {}).get(metric)


# ------------------------------------------------------------------ aggregates

def _num(x):
    return None if x is None else round(float(x), 2)


def stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "median": None, "mean": None, "min": None, "max": None, "stdev": None}
    return {"n": len(vals), "median": _num(statistics.median(vals)),
            "mean": _num(statistics.fmean(vals)), "min": _num(min(vals)), "max": _num(max(vals)),
            "stdev": _num(statistics.stdev(vals)) if len(vals) >= 2 else None}


def aggregates(lines):
    """{dimension: [group]}; a group: value, videos, not_final, incomplete,
    metrics {metric: stats}, small_sample. Only published videos count."""
    counted = [ln for ln in lines if ln["is_published"]]
    out = {}
    for dim in DIMENSIONS:
        groups = []
        for value in sorted({ln["style"][dim] for ln in counted}, key=lambda v: (v == UNKNOWN, v)):
            members = [ln for ln in counted if ln["style"][dim] == value]
            ms = {m: stats(metric_value(ln, m) for ln in members) for m in AGG_METRICS}
            groups.append({
                "value": value, "videos": len(members), "computed_by": COMPUTED_BY,
                "not_final": sum(1 for ln in members if ln["window"] and not ln["window"]["final"]),
                "incomplete": sum(1 for ln in members if ln["window"] and not ln["window"]["complete"]),
                "metrics": ms,
                "small_sample": any(s["n"] < MIN_SAMPLE for s in ms.values()),
            })
        out[dim] = groups
    return out


# ------------------------------------------------------------------ the report

def build(channel, day, first_days=DEFAULT_FIRST_DAYS, journal=None, acceptance_log=None,
          store_root=None, index=None):
    if first_days < 1:
        raise store.StoreError(f"--first-days {first_days}: give 1 or more")
    recs = join(channel, journal, acceptance_log, store_root, index=index)
    lines = [video_line(r, day, first_days) for r in recs]
    gaps = {
        "no_profile": [{"video_id": ln["video_id"], "entry_id": ln["entry_id"], "why": ln["profile_gap"]}
                       for ln in lines if not ln["profile_found"]],
        "no_metrics": [{"video_id": ln["video_id"], "entry_id": ln["entry_id"],
                        "why": "ещё не вышел" if not ln["is_published"] else ln["api_gap"]}
                       for ln in lines if ln["window"] is None],
        "no_studio": [{"video_id": ln["video_id"], "entry_id": ln["entry_id"]}
                      for ln in lines if ln["is_published"] and ln["studio"] is None],
    }
    return {
        "task": TASK, "channel": channel, "day": day.isoformat(), "first_days": first_days,
        "min_sample": MIN_SAMPLE, "dimensions": list(DIMENSIONS), "metrics": list(AGG_METRICS),
        "sources": {
            "videos": "publish/uploads.json",
            "style": "publish/acceptance-log.json profile (CF-0440)",
            "api": f"analytics/{channel}/windows.jsonl, window: first {first_days} day(s) as "
                   f"YouTube Analytics computed it (reports.query without dimensions, CF-0624), "
                   f"ending <= {day.isoformat()}",
            "studio": f"analytics/{channel}/studio.jsonl, last read up to {day.isoformat()}",
        },
        "counts": {
            "videos": len(lines),
            "published": sum(1 for ln in lines if ln["is_published"]),
            "with_profile": sum(1 for ln in lines if ln["profile_found"]),
            "with_api": sum(1 for ln in lines if ln["window"] is not None),
            "with_studio": sum(1 for ln in lines if ln["studio"] is not None),
            "not_final": sum(1 for ln in lines if ln["window"] and not ln["window"]["final"]),
        },
        "videos": lines, "aggregates": aggregates(lines), "gaps": gaps,
        "aggregates_computed_by": COMPUTED_BY, "aggregates_note": AGG_NOTE,
    }


def _f(x, pct=False):
    if x is None:
        return "—"
    s = str(int(x)) if float(x).is_integer() else f"{x:.1f}"
    return s + (" %" if pct else "")


def render_md(rep):
    ch, day, n = rep["channel"], rep["day"], rep["first_days"]
    c = rep["counts"]
    out = [f"# Сводка метрик × стиль — {ch}, {day}", "",
           f"`{TASK}` · окно API: первые {n} д ролика, числа YouTube за окно целиком (окно ≤ {day}) · "
           f"Studio: последнее чтение ≤ {day} "
           f"(доля за период страницы, не окно) · стиль: `profile` строки приёмки.", "",
           f"Роликов в журнале: {c['videos']}; вышло: {c['published']}; с профилем: {c['with_profile']}; "
           f"с метриками API: {c['with_api']} (неокончательных окон: {c['not_final']}); "
           f"с чтением Studio: {c['with_studio']}.", "",
           f"Выводов нет: решение «данные против вкуса» — при 20–30 роликах на стиль. "
           f"Группа, где у какой-то метрики меньше {rep['min_sample']} роликов, помечена «выборка мала».", "",
           "## Ролики", "",
           "| ролик | вышел (PT) | pattern | rhythm | hook_opener | fact_kind | tier | engagedViews | % просмотра | досмотрели % | пометки |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for ln in rep["videos"]:
        s, w, st = ln["style"], ln["window"] or {}, ln["studio"]
        viewed = _f(st and st.get("viewed_pct"), pct=True)
        if st and st.get("viewed_pct") is not None:
            viewed += f" ({st.get('period_text') or 'период ?'}, {str(st.get('read_at'))[:10]})"
        out.append(f"| {ln['slug'] or '—'} `{ln['video_id']}` | {ln['published'] or '—'} | "
                   + " | ".join(s[d] for d in DIMENSIONS)
                   + f" | {_f(w.get('engagedViews'))} | {_f(w.get('averageViewPercentage'), pct=True)} | "
                   f"{viewed} | {', '.join(ln['marks']) or ''} |")
    out += ["", "## По измерениям стиля — посчитано фабрикой", "",
            f"{rep['aggregates_note'][0].upper()}{rep['aggregates_note'][1:]}.", "",
            "n — роликов с этой метрикой; медиана / среднее / мин–макс / σ.", ""]
    for dim in DIMENSIONS:
        out += [f"### {dim}", "",
                "| значение | роликов | " + " | ".join(METRIC_LABELS[m] for m in AGG_METRICS) + " | пометки |",
                "|---|---|" + "---|" * len(AGG_METRICS) + "---|"]
        for g in rep["aggregates"][dim]:
            cells = []
            for m in AGG_METRICS:
                s = g["metrics"][m]
                pct = m != "engagedViews"
                if not s["n"]:
                    cells.append("n=0")
                    continue
                cells.append(f"n={s['n']}: {_f(s['median'], pct)} / {_f(s['mean'], pct)} / "
                             f"{_f(s['min'])}–{_f(s['max'])} / σ {_f(s['stdev'])}")
            marks = []
            if g["small_sample"]:
                marks.append(f"выборка мала (<{rep['min_sample']})")
            if g["not_final"]:
                marks.append(f"неоконч.: {g['not_final']}")
            if g["incomplete"]:
                marks.append(f"окно < {n} д: {g['incomplete']}")
            out.append(f"| {g['value']} | {g['videos']} | " + " | ".join(cells) + f" | {', '.join(marks)} |")
        out.append("")
    out += ["## Пробелы", ""]
    gaps = rep["gaps"]
    if not any(gaps.values()):
        out.append("Нет.")
    for ln in gaps["no_profile"]:
        out.append(f"- нет профиля: `{ln['video_id']}` {ln['entry_id']} — {ln['why']}")
    for ln in gaps["no_metrics"]:
        out.append(f"- нет метрик API: `{ln['video_id']}` {ln['entry_id']} — {ln['why']}")
    for ln in gaps["no_studio"]:
        out.append(f"- нет чтения Studio: `{ln['video_id']}` {ln['entry_id']}")
    return "\n".join(out) + "\n"


def write(rep, store_root=None):
    """Write `<day>.md` and `<day>.json` under analytics/<ch>/summary/; returns their paths."""
    d = store.channel_dir(rep["channel"], store_root) / SUMMARY_DIR
    md, js = d / f"{rep['day']}.md", d / f"{rep['day']}.json"
    store._atomic_write(md, render_md(rep))
    store._atomic_write(js, json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return md, js


# ------------------------------------------------------------------ CLI

def _day_arg(args):
    if args.day:
        return date.fromisoformat(args.day)
    return metrics.default_day(args.now)


def cmd_daily(args, out):
    day = _day_arg(args)
    chans = [args.channel] if args.channel else channels_of(args.journal)
    if not chans:
        print("no channel in the upload journal - nothing to summarise", file=out)
        return EXIT_OK
    index = acceptance_index(args.acceptance)
    for ch in chans:
        rep = build(ch, day, args.first_days, args.journal, args.acceptance, args.store, index=index)
        c = rep["counts"]
        where = "not written (--no-write)"
        if not args.no_write:
            md, js = write(rep, args.store)
            where = f"{md} (+ .json)"
        print(f"{ch} {rep['day']}: {c['videos']} video(s), published {c['published']}, "
              f"profile {c['with_profile']}, api {c['with_api']} (not final {c['not_final']}), "
              f"studio {c['with_studio']} -> {where}", file=out)
        if args.print:
            out.write(render_md(rep))
    return EXIT_OK


def cmd_join(args, out):
    index = acceptance_index(args.acceptance)
    chans = [args.channel] if args.channel else channels_of(args.journal)
    for ch in chans:
        recs = join(ch, args.journal, args.acceptance, args.store, index=index)
        prof = [r for r in recs if r["profile"]]
        print(f"{ch}: {len(recs)} video(s) in the journal, {len(prof)} with a profile, "
              f"{sum(1 for r in recs if r['daily'])} with API rows, "
              f"{sum(1 for r in recs if r['windows'])} with a YouTube window, "
              f"{sum(1 for r in recs if r['studio'])} with a Studio read", file=out)
        for r in recs:
            s = style_of(r["profile"])
            print(f"  {r['video_id']}  {r['entry_id']}  "
                  + " ".join(f"{d}={s[d]}" for d in DIMENSIONS)
                  + (f"  [{r['profile_gap']}]" if r["profile_gap"] else ""), file=out)
    return EXIT_OK


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily", help="write the day's summary of every channel (or one)")
    d.add_argument("--channel", help="one channel id (default: every channel of the journal)")
    d.add_argument("--day", help="summary day YYYY-MM-DD (default: yesterday, Pacific - the last day collect asks)")
    d.add_argument("--first-days", type=int, default=DEFAULT_FIRST_DAYS,
                   help=f"API window: the first N days of each video (default {DEFAULT_FIRST_DAYS})")
    d.add_argument("--print", action="store_true", help="also print the markdown")
    d.add_argument("--no-write", action="store_true", help="write no file")
    j = sub.add_parser("join", help="how the journal joins to profiles and metrics")
    j.add_argument("--channel")
    for p in (d, j):
        p.add_argument("--now", help=argparse.SUPPRESS)
        p.add_argument("--journal", help=argparse.SUPPRESS)
        p.add_argument("--acceptance", help=argparse.SUPPRESS)
        p.add_argument("--store", help=argparse.SUPPRESS)
    return ap


def main(argv=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "daily":
            return cmd_daily(args, out)
        return cmd_join(args, out)
    except (store.StoreError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
