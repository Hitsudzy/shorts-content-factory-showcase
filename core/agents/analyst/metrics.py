#!/usr/bin/env python3
"""CF-0020: the daily YouTube Analytics collection, per channel.

Which videos: every row of the upload journal `publish/uploads.json` (read only
through `agents/publisher/upload_records.py`) that is live - no `removed_at` -
and whose publication is in the past. Nothing else names a video on the
channel; a video the journal does not have is not collected (it would have no
`entry_id`, the key back to the acceptance row and the batch).

What is asked, per video (`reports.query`, `ids=channel==MINE`,
`dimensions=day`, `filters=video==<id>`, `sort=day`), from the first day not yet
final in the store to `--day` (default: yesterday, Pacific time - the zone
YouTube Analytics counts days in; today is never complete):

    core     views, likes, subscribersGained, averageViewDuration, averageViewPercentage
             - the classic metrics of the time-based video report
    engaged  engagedViews - newer (2025); asked separately so that a report
             refusing it (HTTP 400) costs that one column, marked unavailable
             in the run log, and never the whole collection

Two small queries per video instead of one combined: the combination is not
documented as supported, a 400 on it would lose everything, and the Analytics
API's quota is its own (not the Data API's upload/search buckets).

CF-0624 - the windows (III.E.4.h(i): no "similar, independently calculated
data"): for every window of `metrics_store.WINDOW_DAYS` (first 7 days) not yet
final in `windows.jsonl`, the same two groups again over the window's
`startDate..endDate` WITHOUT `dimensions` - YouTube computes the window's
counts and averages itself; the daily rows are never summed or averaged into
a window. The window's end follows the daily rule (`--day`, yesterday
Pacific); it is final once complete and its last day 3+ days old, then never
asked again. Queries per run: 2 per video with daily rows due (every live
video) + 2 per open window (a video in its first ~10 days; the first run after
CF-0624 also asks it once for every older video) - `docs/api-audit/
policy-reading.md` section 4.

Stops (exit codes):
    0  collected (skipped videos are named in the run log and on stdout)
    2  configuration error (`agents/publisher/.env`, Google libraries missing)
    3  the user must re-authorize: no token, the yt-analytics.readonly scope
       missing, the token expired or revoked (CF-0589's exceptions)
    4  the API kept failing (quota, 5xx) after the retries with pauses, or
       refused the request itself - what was collected before is kept
    5  (CF-0623) the API refused the whole run, not a video: it is disabled
       in the token's Google Cloud project (403 `accessNotConfigured` /
       `SERVICE_DISABLED` - the run line `outcome: api-disabled` with the
       answer's `activation_url`), or every video asked of a channel was
       refused (`outcome: all-forbidden` - the token is not the channel's?).
       Either is a question in the journal of questions (shared/needs_you.py,
       CF-0652; one live per reason) and a notice on the bus (`needs_human`).

The run line's `outcome` (`analytics/<channel>/runs.jsonl`): `ok`,
`nothing-to-ask`, `reauthorize`, `api-error`, `api-disabled`, `all-forbidden`.

CF-0618 (YouTube API Services Developer Policies, `agents/publisher/api_data.py`):
a real `collect` (not a dry run) first runs the API Data auto-run - after a
revocation (`invalid_grant`) past its term, or for journal rows not refreshed
for 28 days, the API Data is deleted (nothing else, nothing earlier) - and,
once the token works, refreshes the `videos.insert` fields of the journal's
API rows through `videos.list` (part=status, 1 unit per 50 videos) when they
are 7 days old (III.E.4.c). Neither step stops the collection: a failure is a
warning line.

    agents/publisher/.venv/bin/python agents/analyst/metrics.py collect [--channel C] [--day YYYY-MM-DD]
    python3 agents/analyst/metrics.py collect --dry-run [--channel C] [--day YYYY-MM-DD]
    python3 agents/analyst/metrics.py show [--channel C] [--first-days N]
"""
import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
PUBLISHER = ROOT / "agents" / "publisher"
for _p in (AGENT, PUBLISHER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analytics_client as ac                                   # noqa: E402
import metrics_store as store                                   # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0020"
PACIFIC = ZoneInfo("America/Los_Angeles") if ZoneInfo else timezone(timedelta(hours=-7))
MSK = timezone(timedelta(hours=3))
IDS = "channel==MINE"
GROUPS = (
    ("core", ("views", "likes", "subscribersGained", "averageViewDuration",
              "averageViewPercentage")),
    ("engaged", ("engagedViews",)),
)
EXIT_OK, EXIT_ERROR, EXIT_REAUTHORIZE, EXIT_API, EXIT_REFUSED = 0, 2, 3, 4, 5
NOTICE_TASK = "CF-0623"
NEEDS_YOU_SOURCE = "analyst-metrics"          # CF-0652: the journal of questions

SKIP_REASONS = {
    "removed": "removed from the channel (removed_at) - not asked",
    "not-yet-published": "publication slot still ahead",
    "withdrawn": "taken off its slot back into the копилка (CF-0918) - not published, not asked",
    "after-day": "published after the asked day",
    "up-to-date": "every day up to the asked one is already final in the store",
    "no-publish-day": "the journal row has neither publish_at nor publish_day",
    "no-data-yet": "the API has no rows for it yet (fresh video, data lags ~2-3 days)",
    "forbidden": "the API refused this video (not a video of the token's channel?)",
}


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pacific_day(dt):
    return dt.astimezone(PACIFIC).date()


def default_day(now=None):
    """Yesterday in Pacific time - the last day YouTube Analytics can have."""
    return pacific_day(_now(now)) - timedelta(days=1)


def publication(row, now):
    """(published?, first Pacific day) of a journal row, or (None, None) when
    the row does not say when the video went out."""
    at = row.get("publish_at")
    if at:
        dt = _now(at)
        return dt <= now, pacific_day(dt)
    if row.get("publish_day"):
        # Released at once (the backfilled rows): the Moscow day, one day earlier
        # in Pacific at the latest - start there; a day before release is empty.
        d = date.fromisoformat(row["publish_day"])
        return d <= now.astimezone(MSK).date(), d - timedelta(days=1)
    return None, None


def plan(journal=None, channel=None, day=None, now=None, root=None):
    """(jobs, skips): a job per video to ask about, a skip per journal row that
    is not asked, with its reason. A job is a dict: channel, video_id,
    entry_id, published (first Pacific day), start, end."""
    now = _now(now)
    end = date.fromisoformat(str(day)) if day else default_day(now)
    jobs, skips = [], []
    stored = {}
    for row in upload_records.uploads(journal, channel=channel):
        ch, vid = row.get("channel"), row.get("video_id")
        base = {"channel": ch, "video_id": vid, "entry_id": row.get("entry_id")}
        if row.get("removed_at"):
            skips.append(dict(base, reason="removed"))
            continue
        if upload_records.is_withdrawn(row):
            skips.append(dict(base, reason="withdrawn"))
            continue
        published, first = publication(row, now)
        if published is None:
            skips.append(dict(base, reason="no-publish-day"))
            continue
        if not published:
            skips.append(dict(base, reason="not-yet-published"))
            continue
        if first > end:
            skips.append(dict(base, reason="after-day"))
            continue
        if ch not in stored:
            stored[ch] = (store.read_daily(ch, root), store.read_windows(ch, root))
        daily, wrows = stored[ch]
        start = store.resume_day(daily, vid, first)
        windows = []
        for n in store.WINDOW_DAYS:
            if store.window_due(wrows, vid, n):
                ws, we, complete = store.window_span(first, n, end)
                windows.append({"window": store.window_name(n), "first_days": n,
                                "start": ws.isoformat(), "end": we.isoformat(),
                                "complete": complete})
        if start > end and not windows:
            skips.append(dict(base, reason="up-to-date"))
            continue
        jobs.append(dict(base, published=first.isoformat(), start=start.isoformat(),
                         end=end.isoformat(), daily=start <= end, windows=windows))
    return jobs, skips


def query_params(job, metrics):
    return {"ids": IDS, "startDate": job["start"], "endDate": job["end"],
            "metrics": ",".join(metrics), "dimensions": "day",
            "filters": f"video=={job['video_id']}", "sort": "day"}


def window_params(job, win, metrics):
    """CF-0624: the window asked as one period - no `dimensions`, so the
    answer is YouTube's own total/average over `start..end`."""
    return {"ids": IDS, "startDate": win["start"], "endDate": win["end"],
            "metrics": ",".join(metrics), "filters": f"video=={job['video_id']}"}


def build_window_row(job, win, values, got, collected_at, collected_on):
    """The store row of one window from YouTube's {metric: value}: a count of a
    group that answered without it is 0, an average null; a group that did not
    answer leaves its metrics null."""
    row = {"channel": job["channel"], "video_id": job["video_id"], "entry_id": job["entry_id"],
           "window": win["window"], "first_days": win["first_days"], "start": win["start"],
           "end": win["end"], "complete": win["complete"]}
    for group, metrics in GROUPS:
        for m in metrics:
            v = values.get(m)
            if v is None and group in got and m in store.COUNT_METRICS:
                v = 0
            row[m] = v
    row["final"] = bool(win["complete"]) and store.is_final(win["end"], collected_on)
    row["collected_at"] = collected_at
    row["source"] = store.WINDOW_SOURCE
    return row


def build_rows(job, data, got, collected_at, collected_on):
    """Store rows of one video from {day: {metric: value}}. A metric of a group
    that answered but has no value for the day is 0 (a count) or null (an
    average); a metric of a group that did not answer is null."""
    published = date.fromisoformat(job["published"])
    rows = []
    for day in sorted(data):
        row = {"channel": job["channel"], "video_id": job["video_id"],
               "entry_id": job["entry_id"], "day": day,
               "age": (date.fromisoformat(day) - published).days}
        for group, metrics in GROUPS:
            for m in metrics:
                v = data[day].get(m)
                if v is None and group in got and m in store.COUNT_METRICS:
                    v = 0
                row[m] = v
        row["final"] = store.is_final(day, collected_on)
        row["collected_at"] = collected_at
        rows.append(row)
    return rows


def _auth():
    import publisher_auth                                       # noqa: PLC0415
    return publisher_auth


def _api_data():
    import api_data                                             # noqa: PLC0415
    return api_data


def api_data_auto(cfg, args, now, out):
    """CF-0618: the API Data auto-run before the collection (rules 1-2 of
    api_data.py: only what is due is deleted). Never stops the collection."""
    try:
        ad = _api_data()
        # the notes and publish/README.md the video id is scrubbed from live
        # beside the journal (`publish/uploads.json` -> the root)
        root = Path(args.journal).resolve().parent.parent if args.journal else ROOT
        for p, rec in ad.auto(cfg, root, now, delete=True, journal=args.journal,
                              analytics=args.store):
            print(f"API DATA DELETED ({p['reason']}, {ad.TASK}): " + "; ".join(
                x.strip() for x in ad.describe(p)), file=out)
    except Exception as e:                                      # noqa: BLE001
        print(f"warning: the API Data auto-run failed ({type(e).__name__}: {e}) - "
              f"`python3 agents/publisher/api_data.py auto` shows what is due", file=out)


def refresh_due(args, now):
    """CF-0618: API rows of the journal due for their videos.list refresh."""
    try:
        ad = _api_data()
        return ad.due_for_refresh(upload_records.uploads(args.journal or ad._paths(ROOT)[1]), now)
    except Exception:                                           # noqa: BLE001
        return []


def refresh_journal(yt, creds, args, now, out, build=None):
    """CF-0618: III.E.4.c - the API rows' fields refreshed through videos.list
    when due. `yt` - a ready client (tests); else one is built from `creds`.
    Never stops the collection."""
    try:
        ad = _api_data()
        if not refresh_due(args, now):
            return None
        if yt is None:
            import youtube_client                               # noqa: PLC0415
            yt = youtube_client.YouTubeClient(creds, build=build,
                                              media_upload=lambda *a, **k: None)
        res = ad.refresh_journal(yt, ROOT, journal=args.journal, now=now)
        print(f"journal refresh (videos.list, {ad.TASK}): {len(res['refreshed'])} refreshed"
              + (f", {len(res['missing'])} no longer on YouTube -> removed_at: "
                 f"{', '.join(res['missing'])}" if res["missing"] else ""), file=out)
        return res
    except Exception as e:                                      # noqa: BLE001
        print(f"warning: the journal refresh through videos.list failed "
              f"({type(e).__name__}: {e}) - the API rows are refreshed on the next run; "
              f"after 28 days without one their API fields are deleted", file=out)
        return None


def collect(jobs, client, now=None, root=None, sleep=time.sleep, pauses=ac.PAUSES,
            auth=None, skips=()):
    """Ask the API about every job and merge the answers into the store, one
    video at a time (a failure keeps what came before). `skips` - the plan's
    skipped rows - go into the run line of their channel; a channel with
    skips and no job gets a `nothing-to-ask` line. Returns {channel: summary};
    on a stop the channel's run is logged and the exception goes on to the
    caller."""
    now = _now(now)
    collected_at, collected_on = _iso(now), pacific_day(now)
    result = {}
    unavailable = {}
    by_channel = {}
    for job in jobs:
        by_channel.setdefault(job["channel"], []).append(job)
    for ch, chjobs in by_channel.items():
        summary = {"collected_at": collected_at, "end_day": chjobs[0]["end"],
                   "queried": [], "rows": {"added": 0, "replaced": 0, "unchanged": 0},
                   "skipped": [{"video_id": s["video_id"], "reason": s["reason"]}
                               for s in skips if s["channel"] == ch],
                   "unavailable_metrics": unavailable, "outcome": "ok"}
        result[ch] = summary
        summary["windows"] = {"added": 0, "replaced": 0, "unchanged": 0}

        def ask(params_of, parse):
            """Both groups of one question -> (merged answer, groups that
            answered, refusal or None)."""
            data, got = {}, set()
            for group, metrics in GROUPS:
                if any(m in unavailable for m in metrics):
                    continue
                params = params_of(metrics)
                try:
                    resp = ac.call_with_retry(lambda p=params: client.query(**p),
                                              sleep=sleep, pauses=pauses, auth=auth)
                except ac.ApiError as e:
                    if e.kind == "bad" and group != "core":
                        for m in metrics:
                            unavailable[m] = str(e)
                        continue
                    if e.kind == "forbidden":
                        return data, got, str(e)
                    raise
                got.add(group)
                parse(resp, data)
            return data, got, None

        def _days(resp, data):
            for day, values in ac.parse_report(resp).items():
                data.setdefault(day, {}).update(values)

        def _total(resp, data):
            data.update(ac.parse_total(resp))

        try:
            for job in chjobs:
                data, got, refused = {}, set(), None
                if job.get("daily", True):
                    data, got, refused = ask(lambda ms, j=job: query_params(j, ms), _days)
                wrows = []
                for win in job.get("windows") or ():
                    if refused:
                        break
                    wdata, wgot, refused = ask(
                        lambda ms, j=job, w=win: window_params(j, w, ms), _total)
                    if wdata and not refused:
                        wrows.append(build_window_row(job, win, wdata, wgot, collected_at,
                                                      collected_on))
                summary["queried"].append(job["video_id"])
                if refused:
                    summary["skipped"].append({"video_id": job["video_id"], "reason": "forbidden",
                                               "detail": refused})
                    continue
                if not data and not wrows:
                    summary["skipped"].append({"video_id": job["video_id"],
                                               "reason": "no-data-yet"})
                    continue
                if data:
                    counts = store.merge(ch, build_rows(job, data, got, collected_at,
                                                        collected_on), root)
                    for k, v in counts.items():
                        summary["rows"][k] += v
                if wrows:
                    for k, v in store.merge_windows(ch, wrows, root).items():
                        summary["windows"][k] += v
        except Exception as e:                                  # noqa: BLE001
            if getattr(e, "exit_code", None) == EXIT_REAUTHORIZE:
                summary["outcome"] = "reauthorize"
            elif getattr(e, "kind", None) == "disabled":
                summary["outcome"] = "api-disabled"
                summary["activation_url"] = e.activation_url
            else:
                summary["outcome"] = "api-error"
            summary["error"] = str(e)
            raise
        else:
            # CF-0623: every video asked was refused - not a run that went well
            refused = [s["video_id"] for s in summary["skipped"] if s["reason"] == "forbidden"]
            if summary["queried"] and set(summary["queried"]) <= set(refused):
                summary["outcome"] = "all-forbidden"
        finally:
            store.append_run(ch, summary, root)
    end_day = jobs[0]["end"] if jobs else None
    for ch in sorted({s["channel"] for s in skips} - set(by_channel)):
        store.append_run(ch, {"collected_at": collected_at, "end_day": end_day, "queried": [],
                              "rows": {}, "skipped": [{"video_id": s["video_id"],
                                                       "reason": s["reason"]}
                                                      for s in skips if s["channel"] == ch],
                              "unavailable_metrics": {}, "outcome": "nothing-to-ask"}, root)
        result[ch] = None
    return result


# --------------------------------------------------------------------------
# CF-0623: a run the API refused as a whole -> a question + the bus
# (CF-0652: the question is a row of the journal of questions, shared/needs_you.py)
# --------------------------------------------------------------------------

def _notify_bus():
    """The notification bus `shared/notify.py` - None when it cannot be loaded:
    a notification is never on the critical path."""
    try:
        shared = str(ROOT / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus                                    # noqa: PLC0415
        return bus
    except Exception:                                           # noqa: BLE001
        return None


def _push(notice):
    bus = _notify_bus()
    if bus is not None:
        bus.send("needs_human", notice["key"], notice["text"], channel=notice["channel"],
                 link=notice["link"] or bus.link_of(None, "needs-you"))


# Each is called as fn(notice) - {key, channel, text, link, tag, line}. The
# bus of CF-0591 is registered here; tests put a recorder in its place. A
# notifier that raises is said and skipped.
NOTIFIERS = [_push]


def needs_you_dir(args):
    """--needs-you-dir, else the journal's own default ($NEEDS_YOU_DIR, else
    <root>/needs-you)."""
    d = getattr(args, "needs_you_dir", None)
    return Path(d).expanduser() if d else None


def _journal():
    shared = str(ROOT / "shared")
    if shared not in sys.path:
        sys.path.append(shared)
    import needs_you                                            # noqa: PLC0415
    return needs_you


def write_needs_you(notice, directory=None):
    """One live question per reason (`ny_key`); the bus is told by NOTIFIERS,
    so the journal sends nothing of its own. Returns the message."""
    q, created = _journal().add(NEEDS_YOU_SOURCE, notice["ny_key"], notice["line"],
                                channel=notice["channel"], link=notice["link"],
                                notify=False, directory=directory)
    if not created:
        return f"NEEDS-YOU: вопрос {q['id']} {notice['tag']} уже есть"
    return f"NEEDS-YOU {q['id']}: {q['text']}"


def disabled_notice(err, day):
    url = getattr(err, "activation_url", None)
    tag = f"({NOTICE_TASK}, analytics-api-disabled)"
    what = ("YouTube Analytics API выключено в проекте Google Cloud токена - метрики не "
            "собираются ни по одному ролику")
    todo = f"включить: {url}" if url else "включить YouTube Analytics API в Google Cloud Console"
    return {"key": f"analytics-api-disabled:{day}", "ny_key": "analytics-api-disabled",
            "channel": None, "link": url, "tag": tag,
            "text": f"{what}; включить по ссылке, затем `metrics.py collect` снова"
                    if url else f"{what}; {todo}, затем `metrics.py collect` снова",
            "line": f"{what}. Решить: {todo}, затем "
                    f"`agents/publisher/.venv/bin/python agents/analyst/metrics.py collect` {tag}"}


def all_forbidden_notice(channel, summary, day):
    n = len(summary["queried"])
    tag = f"({NOTICE_TASK}, analytics-all-forbidden {channel})"
    what = (f"YouTube Analytics отверг все {n} ролик(ов) {channel} (403) - токен не канала "
            f"{channel}?")
    todo = ("сверить канал токена (`PUBLISHER_CHANNEL_ID`, channels.list mine) с каналом "
            "роликов; ошибку - в `analytics/" + channel + "/runs.jsonl`")
    return {"key": f"analytics-all-forbidden:{channel}:{day}",
            "ny_key": f"analytics-all-forbidden:{channel}", "channel": channel, "link": None,
            "tag": tag, "text": f"{what} Сверить канал токена",
            "line": f"{what} Решить: {todo} {tag}"}


def raise_notice(notice, directory, out, notifiers=None):
    """The question in the journal (`directory` None - its default) and every
    notifier. Never raises."""
    try:
        print(write_needs_you(notice, directory), file=out)
    except Exception as e:                                      # noqa: BLE001
        print(f"NEEDS-YOU: не записано ({e.__class__.__name__}: {e}) - {notice['line']}",
              file=out)
    for fn in (NOTIFIERS if notifiers is None else notifiers):
        try:
            fn(notice)
        except Exception as e:                                  # noqa: BLE001
            print(f"warning: notifier {getattr(fn, '__name__', fn)}: "
                  f"{type(e).__name__}: {e}", file=out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _skip_line(s):
    return f"  skip {s['video_id']}  {s['reason']}: {SKIP_REASONS.get(s['reason'], '')}"


def queries_of(job):
    """How many `reports.query` calls a job costs (CF-0624: quota per run)."""
    return len(GROUPS) * (int(job.get("daily", True)) + len(job.get("windows") or ()))


def _print_plan(jobs, skips, out):
    total = sum(queries_of(j) for j in jobs)
    print(f"dry run - nothing is sent; {len(jobs)} video(s) would be asked, "
          f"{total} queries in all ({len(GROUPS)} per daily series, {len(GROUPS)} per open "
          f"window)", file=out)
    for job in jobs:
        daily = f"{job['start']}..{job['end']}" if job.get("daily", True) else "daily up to date"
        print(f"  ask  {job['channel']}  {job['video_id']}  {daily}  "
              f"(published {job['published']} PT, entry {job['entry_id']})", file=out)
        if job.get("daily", True):
            for _, metrics in GROUPS:
                p = query_params(job, metrics)
                print("       reports.query " + " ".join(f"{k}={v}" for k, v in p.items()),
                      file=out)
        for win in job.get("windows") or ():
            print(f"       window {win['window']} {win['start']}..{win['end']}"
                  f"{'' if win['complete'] else ' (not complete yet)'}:", file=out)
            for _, metrics in GROUPS:
                p = window_params(job, win, metrics)
                print("       reports.query " + " ".join(f"{k}={v}" for k, v in p.items()),
                      file=out)
    for s in skips:
        print(_skip_line(s), file=out)


def _print_summary(result, out):
    unavailable = {}
    for ch, s in result.items():
        if s is None:
            print(f"{ch}: nothing to ask", file=out)
            continue
        unavailable.update(s["unavailable_metrics"])
        r, w = s["rows"], s.get("windows") or {}
        print(f"{ch}: asked {len(s['queried'])} video(s) up to {s['end_day']}; rows "
              f"+{r['added']} replaced {r['replaced']} unchanged {r['unchanged']}; "
              f"windows +{w.get('added', 0)} replaced {w.get('replaced', 0)} "
              f"unchanged {w.get('unchanged', 0)}; "
              f"skipped {len(s['skipped'])}; outcome {s['outcome']}", file=out)
        for sk in s["skipped"]:
            print(_skip_line(sk), file=out)
    for m, why in unavailable.items():
        print(f"  metric {m} unavailable this run: {why}", file=out)


def cmd_collect(args, out, client=None, sleep=time.sleep, auth_libs=None, build=None, yt=None):
    now = _now(args.now)
    try:
        jobs, skips = plan(args.journal, channel=args.channel, day=args.day, now=now,
                           root=args.store)
    except (ValueError, upload_records.JournalError, store.StoreError) as e:
        print(f"error: {e}", file=out)
        return EXIT_ERROR
    if args.dry_run:
        _print_plan(jobs, skips, out)
        return EXIT_OK
    if not jobs:
        collect([], None, now=now, root=args.store, skips=skips)
        print(f"nothing to ask{f' for channel {args.channel}' if args.channel else ''}: "
              f"{len(skips)} journal row(s), none due", file=out)
        for s in skips:
            print(_skip_line(s), file=out)
        if yt is None and not refresh_due(args, now):
            return EXIT_OK
        # CF-0618: nothing to collect, but API rows of the journal are due for
        # their videos.list refresh - that needs the token too
    auth = _auth()
    creds = cfg = None
    code = EXIT_OK
    if client is None:
        import publisher_config                                 # noqa: PLC0415
        try:
            cfg = publisher_config.load(args.env)
        except publisher_config.ConfigError as e:
            print(f"error: {e}", file=out)
            return EXIT_ERROR
        api_data_auto(cfg, args, now, out)
        if not Path(cfg.token_file).is_file():
            print(f"STOP (re-authorize): no OAuth token at {cfg.token_file} - the user signs in "
                  f"with `{auth.AUTHORIZE_COMMAND}` (opens a browser)", file=out)
            return EXIT_REAUTHORIZE
        try:
            creds = auth.analytics_credentials(cfg, libs=auth_libs)
        except auth.ReauthorizeRequired as e:
            print(f"STOP (re-authorize): {e}", file=out)
            return EXIT_REAUTHORIZE
        except auth.AuthError as e:          # the Google libraries, a token that does not parse
            print(f"error: {e}", file=out)
            return EXIT_ERROR
        try:
            client = ac.AnalyticsClient(creds, build=build)
        except ac.ApiError as e:
            print(f"error: {e}", file=out)
            return EXIT_ERROR
    if jobs:
        try:
            result = collect(jobs, client, now=now, root=args.store, sleep=sleep, auth=auth,
                             skips=skips)
        except auth.ReauthorizeRequired as e:
            print(f"STOP (re-authorize): {e}", file=out)
            return EXIT_REAUTHORIZE
        except ac.ApiError as e:
            if e.kind == "disabled":
                print(f"STOP (YouTube Analytics API disabled in the Google Cloud project): {e} "
                      f"- nothing more is asked; switch the API on and run `collect` again",
                      file=out)
                raise_notice(disabled_notice(e, pacific_day(now)), needs_you_dir(args), out)
                return EXIT_REFUSED
            print(f"STOP (YouTube Analytics API): {e} - what was collected before is kept; "
                  f"run `collect` again later", file=out)
            return EXIT_API
        _print_summary(result, out)
        refused = sorted(ch for ch, s in result.items() if s and s["outcome"] == "all-forbidden")
        for ch in refused:
            print(f"STOP ({ch}): the API refused every video asked (403 forbidden) - the token "
                  f"is not the channel's? not a run that went well", file=out)
            raise_notice(all_forbidden_notice(ch, result[ch], pacific_day(now)),
                         needs_you_dir(args), out)
        if refused:
            code = EXIT_REFUSED
    if yt is not None or creds is not None:
        refresh_journal(yt, creds, args, now, out, build=build)
    return code


def cmd_show(args, out):
    """CF-0624: YouTube's own window rows (`windows.jsonl`); a video without
    one is said to have none - never a window recombined from daily rows."""
    root = Path(args.store or store.STORE)
    channels = [args.channel] if args.channel else sorted(
        p.name for p in root.glob("*")
        if (p / store.DAILY).is_file() or (p / store.WINDOWS).is_file())
    n = args.first_days
    for ch in channels:
        rows, wrows = store.read_daily(ch, args.store), store.read_windows(ch, args.store)
        vids = sorted({r["video_id"] for r in rows} | {r["video_id"] for r in wrows})
        print(f"{ch}: {len(vids)} video(s), window first {n} day(s) as YouTube computed it"
              + ("" if n in store.WINDOW_DAYS else
                 f" - not collected (metrics_store.WINDOW_DAYS = {store.WINDOW_DAYS})"), file=out)
        for vid in vids:
            w = store.window(wrows, vid, n)
            if w is None:
                print(f"  {vid}  no YouTube window of {n} d (windows.jsonl) - not recomputed "
                      f"from {len(store.video_rows(rows, vid))} daily row(s)", file=out)
                continue
            marks = ", ".join(x for x in ("" if w["complete"] else "not complete",
                                          "" if w["final"] else "not final") if x)
            print(f"  {vid}  {w['from']}..{w['to']} ({w['days']} d{', ' + marks if marks else ''})"
                  f"  views {w['views']}  engaged {w['engagedViews']}  "
                  f"avg% {w['averageViewPercentage']}  avg s {w['averageViewDuration']}  "
                  f"likes {w['likes']}  subs+ {w['subscribersGained']}", file=out)
    return EXIT_OK


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="ask YouTube Analytics about every live video")
    c.add_argument("--channel", help="one channel id (default: every channel of the journal)")
    c.add_argument("--day", help="last day to ask for, YYYY-MM-DD (default: yesterday, Pacific)")
    c.add_argument("--dry-run", action="store_true", help="print the videos and queries, send nothing")
    c.add_argument("--now", help=argparse.SUPPRESS)
    c.add_argument("--env", help="the Publisher's .env (default agents/publisher/.env)")
    c.add_argument("--needs-you-dir", help="the journal of questions' directory (CF-0652; "
                                           "default $NEEDS_YOU_DIR, else <root>/needs-you)")
    c.add_argument("--journal", help=argparse.SUPPRESS)
    c.add_argument("--store", help=argparse.SUPPRESS)
    s = sub.add_parser("show", help="per-video YouTube windows from the store")
    s.add_argument("--channel")
    s.add_argument("--first-days", type=int, default=store.WINDOW_DAYS[0],
                   help=f"window: the first N days of each video (collected: "
                        f"{', '.join(map(str, store.WINDOW_DAYS))}; default {store.WINDOW_DAYS[0]})")
    s.add_argument("--store", help=argparse.SUPPRESS)
    return ap


def main(argv=None, out=None, client=None, sleep=time.sleep, auth_libs=None, build=None, yt=None):
    """`client`, `auth_libs`, `build`, `yt` - stand-ins for the tests: a ready
    client, the OAuth libraries (publisher_auth), the discovery `build`, a
    ready YouTube Data client for the journal refresh (CF-0618)."""
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    if args.cmd == "collect":
        return cmd_collect(args, out, client=client, sleep=sleep, auth_libs=auth_libs,
                           build=build, yt=yt)
    return cmd_show(args, out)


if __name__ == "__main__":
    sys.exit(main())
