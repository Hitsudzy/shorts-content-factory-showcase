#!/usr/bin/env python3
"""CF-0042: the no-repeat window of (pattern, rhythm) pairs over the channel's
published feed, checked when a video is put into a slot of the queue (CF-0587).

Why on publication (CF-0015, the decision): the YouTube reviewer looks at the
channel's newest videos in a row, not at `pipeline/`. The rotation (CF-0040)
keeps the *pool* even; only the queue knows the order the feed will have, so
the guarantee "any K consecutive videos of the feed carry K different pairs"
is kept here - at the moment a video gets its slot.

K is the channel's - `channels/<channel>.json` -> `patterns.rotation.
no_repeat_window_k` (the same number the rotation counts assignments with),
capped by the pairs the channel can build today (`rotate.effective_k`); no
default in code. A channel with no `patterns.rotation` has no window: the
check says so as a warning and lets the slot through.

The feed - `feed()`, in slot order: every video that holds a day of the
channel (`publish_queue.occupants`: day folders + live rows of
`publish/uploads.json`). Published = its slot is in the past; scheduled = in
the future; a row of the journal means it is already in Studio (its schedule
is set there and nobody here moves it).

The pair of one video - `pair_of()`: its batch's own `05-video-editor.json`
(delivered, else requested - the requested pattern is the script's structure,
which a degraded cut does not change), found by the video's output path; a
rebuild's script goes back to its source batch through `rebuild_of`. When the
batch is gone (archived), the ledger row (CF-0040) whose `video_path` is the
video. Nothing found = no data, never a guess: the check lets the video
through with a warning naming it.

The check - `candidate_check()` is registered in
`publish_queue.CANDIDATE_CHECKS`: `(channel, slug, slot, root, now, ctx)` ->
None | {"verdict": "reorder" | "warn", "reason", ...}. `ctx` carries the
video's `batch_id` and `moved` - the other videos a reorder would put
elsewhere (`{slug: {"slot", "batch_id"}}`), so one plan is judged as a whole.
What the queue does with a `reorder` is publish_queue's: a swap inside the
queue, never a shift of the schedule.

The ledger's publication columns (CF-0040: `published_at`, `feed_position`,
`video_id`, owed to this task) - `record_published()`: derived from the
journal (the one record of uploads), written through the ledger's one writer
(`Ledger.enrich`, empty -> filled only), on the script's row. Run by
`publish_card.py place` after every placement and by `record` below.

    python3 agents/publisher/publish_window.py check [--channel C] [--now ISO] [--root DIR]
        # the feed with pairs, every repeat inside K; exit 1 on a repeat
    python3 agents/publisher/publish_window.py record [--channel C] [--now ISO] [--root DIR] [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog", ROOT / "shared", ROOT / "rotation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import channel_ids                                              # noqa: E402
import publish_layout                                           # noqa: E402
import upload_records                                           # noqa: E402
from ledger import Ledger, LedgerError, ledger_path              # noqa: E402

TASK = "CF-0042"
EXIT_OK, EXIT_REPEAT, EXIT_ERROR = 0, 1, 2
REBUILDS = "rebuilds"            # pipeline/rebuilds/<batch> - a rebuild's directory names no channel


class WindowError(Exception):
    pass


def _pq():
    import publish_queue                                        # noqa: PLC0415 - it imports us lazily
    return publish_queue


def _rotate():
    import rotate                                               # noqa: PLC0415
    return rotate


def _pairstr(pair):
    return f"{pair[0]}/{pair[1]}" if pair else "?"


# --------------------------------------------------------------------------
# K
# --------------------------------------------------------------------------

def window_config(channel, root=None):
    """`{k, configured, pairs}` of the channel, or None when it has no
    `patterns.rotation` (no window). WindowError on a broken block."""
    root = Path(root or ROOT)
    path = channel_ids.channel_config_path(channel, root)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise WindowError(f"{path}: cannot read ({e})") from e
    if not isinstance((cfg.get("patterns") or {}).get("rotation"), dict):
        return None
    rot = _rotate()
    try:
        k = rot.rotation_config(cfg)["no_repeat_window_k"]
        pairs, _ = rot.eligible_pairs(cfg)
    except rot.RotationError as e:
        raise WindowError(f"{path}: {e}") from e
    return {"k": rot.effective_k(k, pairs) if pairs else k, "configured": k, "pairs": len(pairs)}


# --------------------------------------------------------------------------
# the pair of one video
# --------------------------------------------------------------------------

def _batch_dirs(channel, batch_id, root):
    base = Path(root) / "pipeline"
    names = list(channel_ids.channel_names(channel, root)) + [REBUILDS]
    return [base / n / batch_id for n in names if (base / n / batch_id).is_dir()]


def _ledger(channel, root):
    p = ledger_path(channel_ids.resolve_channel(channel, root), Path(root) / "rotation" / "ledger")
    return Ledger(p) if p.is_file() else None


def _of(video, key):
    return video.get(f"{key}_delivered") or video.get(f"{key}_requested") or None


def _ordered(batch_dirs, script_id):
    """The pair Content Researcher's file of the batch says the script was written in."""
    for d in batch_dirs:
        try:
            meta = json.loads((d / "03-content-researcher.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for s in meta.get("scripts") or []:
            if s.get("script_id") == script_id and isinstance(s.get("pattern"), dict):
                return s["pattern"].get("pattern_id"), s["pattern"].get("rhythm_id")
    return None, None


def pair_of(channel, batch_id, slug, root=None):
    """`{pair, source, script_id, ledger_batch, seq}` of one video; `pair` is
    None when nothing on disk says it (`source` says what was looked at)."""
    root = Path(root or ROOT)
    out = {"pair": None, "source": None, "script_id": None, "ledger_batch": batch_id, "seq": None}
    if not batch_id:
        out["source"] = "no batch id"
        return out
    video = None
    batch_dirs = _batch_dirs(channel, batch_id, root)
    for d in batch_dirs:
        try:
            meta = json.loads((d / "05-video-editor.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in meta.get("videos") or []:
            if Path(str(v.get("output_path") or "")).stem == slug:
                video = v
                out["ledger_batch"] = (meta.get("rebuild_of") or {}).get("batch_id") or batch_id
                break
        if video:
            break
    led = _ledger(channel, root)
    rows = []
    if led is not None:
        try:
            rows = led.rows()
        except LedgerError:
            rows = []
    row = None
    if video:
        out["script_id"] = video.get("script_id")
        if out["script_id"] and led is not None:
            try:
                row = led.standing_row_for(out["script_id"], rows, out["ledger_batch"])
            except LedgerError:
                row = None
        p, r = _of(video, "pattern"), _of(video, "rhythm")
        if p and r:
            out.update(pair=(p, r), source=f"{batch_id}/05-video-editor.json")
        else:
            p, r = _ordered(batch_dirs, out["script_id"])
            if p and r:
                out.update(pair=(p, r), source=f"{batch_id}/03-content-researcher.json")
    if row is None and not video:
        hits = [x for x in (led.standing_rows(rows) if led else [])
                if x["batch_id"] == batch_id and Path(x["video_path"]).stem == slug]
        row = hits[0] if len(hits) == 1 else None
        if row:
            out["script_id"] = row["script_id"]
    if row is None and out["pair"] is None and out["script_id"] and rows:
        # the script's one assignment anywhere in the ledger - for the pair only;
        # the publication columns are written on the strict (batch, script) key
        hits = [x for x in led.standing_rows(rows) if x["script_id"] == out["script_id"]]
        if len(hits) == 1 and (hits[0]["pattern_delivered"] or hits[0]["pattern_id"]):
            h = hits[0]
            out.update(pair=(h["pattern_delivered"] or h["pattern_id"],
                             h["rhythm_delivered"] or h["rhythm_id"]),
                       source=f"ledger seq {h['seq']} (script id {out['script_id']} only)")
    if row:
        out["seq"] = row["seq"]
        if out["pair"] is None:
            p = row["pattern_delivered"] or row["pattern_id"]
            r = row["rhythm_delivered"] or row["rhythm_id"]
            if p and r:
                out.update(pair=(p, r), source=f"ledger seq {row['seq']}")
    if out["pair"] is None:
        out["source"] = (f"no 05-video-editor.json entry and no ledger row for {batch_id}/{slug}"
                         if not video else f"{batch_id}/05-video-editor.json names no pattern")
    return out


# --------------------------------------------------------------------------
# the feed
# --------------------------------------------------------------------------

def _accepted_batch(channel, slug, root):
    """The batch of `slug` from the acceptance log when exactly one accepted row names it."""
    try:
        log = json.loads((Path(root) / "publish" / "acceptance-log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ch = channel_ids.resolve_channel(channel, root)
    found = {r.get("batch_id") for r in log.get("acceptances") or []
             if r.get("slug") == slug and r.get("verdict") == "accepted"
             and channel_ids.resolve_channel(r.get("channel"), root) == ch}
    return found.pop() if len(found) == 1 else None


def batch_of_entry(channel, entry, root):
    """The batch of a `publish/<channel>/<bucket>/` entry: its note's `Батч` line,
    else the one accepted row of the slug."""
    return publish_layout.batch_of(entry) or _accepted_batch(channel, entry["slug"], root)


def _noon(day):
    pq = _pq()
    return datetime.combine(datetime.strptime(day, "%Y-%m-%d").date(), time(12, 0),
                            tzinfo=pq._zone(pq.MSK))


def feed(channel, root=None, now=None, journal=None):
    """`[{slug, batch_id, at, day, published, in_studio, bucket, video_id}]` in
    slot order: everything that holds a day of the channel. `at` is the slot,
    or noon of the Moscow day when nobody wrote the time (the order inside such
    a day is by name)."""
    pq = _pq()
    root = Path(root or ROOT)
    now = pq.now_utc(now)
    pub = root / "publish"
    jpath = Path(journal) if journal else pub / "uploads.json"
    try:
        jrows = [r for r in upload_records.uploads(jpath, channel) if upload_records.holds_slot(r)]
    except (upload_records.JournalError, ValueError) as e:
        raise WindowError(f"{jpath}: {e}") from e
    folders = {(e["slug"], e["bucket"]): e for e in publish_layout.entries(pub, channel)
               if e["channel"] == channel and publish_layout.DAY_RE.match(e["bucket"])}
    out = []
    for o in pq.occupants(channel, root, journal):
        jr = next((r for r in jrows if r.get("slug") == o["slug"]
                   and (r.get("publish_day") == o["day"] or (
                       r.get("publish_at") and pq.msk_day(pq.now_utc(r["publish_at"])) == o["day"]))),
                  None)
        entry = folders.get((o["slug"], o["day"]))
        batch = (jr or {}).get("batch_id") or (batch_of_entry(channel, entry, root) if entry else None)
        at = o["at"] or _noon(o["day"])
        out.append({"slug": o["slug"], "batch_id": batch, "at": at, "day": o["day"],
                    "published": at <= now, "in_studio": jr is not None,
                    "bucket": o["day"] if entry else None, "video_id": (jr or {}).get("video_id")})
    out.sort(key=lambda x: (x["at"], x["slug"] or ""))
    return out


# --------------------------------------------------------------------------
# the window
# --------------------------------------------------------------------------

def repeats(items, k, focus=None):
    """`[(a, b)]` - two items of `items` (in feed order, each with `pair`) less
    than `k` apart carrying the same pair; only those touching `focus` (slugs)
    when it is given. Items with no pair are not counted."""
    out = []
    for i, a in enumerate(items):
        for b in items[i + 1:i + k]:
            if a.get("pair") and a.get("pair") == b.get("pair") and (
                    focus is None or a["slug"] in focus or b["slug"] in focus):
                out.append((a, b))
    return out


def _with_pairs(channel, items, root, cache):
    for it in items:
        key = (it.get("batch_id"), it["slug"])
        if key not in cache:
            cache[key] = pair_of(channel, it.get("batch_id"), it["slug"], root)
        it["pair"] = cache[key]["pair"]
        it["pair_source"] = cache[key]["source"]
    return items


def arrange(channel, slug, slot, root=None, now=None, ctx=None, journal=None, base=None):
    """The feed as it would be with `slug` (batch `ctx.batch_id`) at `slot`,
    every `ctx.moved` video at its own new slot and every `ctx.removed` slug
    (CF-0856: taken back into `_queue/` by the same plan) off the feed."""
    ctx = ctx or {}
    moved = dict(ctx.get("moved") or {})
    moved[slug] = {"slot": slot, "batch_id": ctx.get("batch_id")}
    removed = set(ctx.get("removed") or ()) - set(moved)
    items = [dict(x) for x in (base if base is not None else feed(channel, root, now, journal))
             if x["slug"] not in moved and x["slug"] not in removed]
    for s, m in moved.items():
        items.append({"slug": s, "batch_id": m.get("batch_id"), "at": m["slot"],
                      "day": _pq().msk_day(m["slot"]), "published": False, "in_studio": False,
                      "bucket": None, "video_id": None})
    items.sort(key=lambda x: (x["at"], x["slug"] or ""))
    return items


def candidate_check(channel, slug, slot, root=None, now=None, ctx=None):
    """The hook of `publish_queue.CANDIDATE_CHECKS`."""
    root = Path(root or ROOT)
    try:
        wc = window_config(channel, root)
    except WindowError as e:
        return {"verdict": "warn", "reason": f"окно паттернов не проверено ({TASK}): {e}"}
    if wc is None:
        return {"verdict": "warn", "reason": (
            f"окно паттернов не проверено ({TASK}): у канала {channel} нет "
            f"patterns.rotation.no_repeat_window_k в channels/{channel}.json")}
    k = wc["k"]
    if k <= 1:
        return None
    ctx = ctx or {}
    try:
        items = arrange(channel, slug, slot, root, now, ctx)
    except WindowError as e:
        return {"verdict": "warn", "reason": f"окно паттернов не проверено ({TASK}): {e}"}
    cache = ctx.setdefault("_pairs", {}) if isinstance(ctx, dict) else {}
    _with_pairs(channel, items, root, cache)
    focus = {slug} | set(ctx.get("moved") or {})
    me = next(x for x in items if x["slug"] == slug)
    if me["pair"] is None:
        return {"verdict": "warn", "reason": (
            f"нет данных о паре паттернов у {slug} ({me['pair_source']}) - окно K={k} "
            f"для него не проверено, слот без проверки ({TASK})")}
    hits = repeats(items, k, focus)
    if hits:
        a, b = hits[0]
        other = b if a["slug"] in focus else a
        mine = a if other is b else b
        return {"verdict": "reorder", "k": k, "conflicts": [
            {"slug": x["slug"], "other": y["slug"], "pair": _pairstr(x["pair"]),
             "other_day": y["day"]} for x, y in [(mine, other)]],
            "reason": (f"пара {_pairstr(mine['pair'])} у {mine['slug']} ({mine['day']}) "
                       f"повторяет {other['slug']} ({other['day']}"
                       f"{', опубликован' if other['published'] else ''}) внутри окна K={k} "
                       f"({TASK})")}
    i = items.index(me)
    near = items[max(0, i - k + 1):i + k]
    blind = [x["slug"] for x in near if x["pair"] is None and x["slug"] != slug]
    if blind:
        return {"verdict": "warn", "reason": (
            f"окно K={k} вокруг {slug} проверено не целиком: нет данных о паре у "
            f"{', '.join(blind)} ({TASK})")}
    return None


# --------------------------------------------------------------------------
# the ledger's publication columns (CF-0040 -> CF-0042)
# --------------------------------------------------------------------------

def published_rows(channel, root=None, now=None, journal=None):
    """The journal rows of the channel that went out, in feed order, each with
    `at` and its 1-based `feed_position`. A row whose video was removed counts
    when the removal came after its slot - it was on the feed."""
    pq = _pq()
    root = Path(root or ROOT)
    now = pq.now_utc(now)
    jpath = Path(journal) if journal else root / "publish" / "uploads.json"
    try:
        rows = upload_records.uploads(jpath, channel)
    except (upload_records.JournalError, ValueError) as e:
        raise WindowError(f"{jpath}: {e}") from e
    out = []
    for r in rows:
        if upload_records.is_withdrawn(r):         # CF-0918: in the копилка, never went out
            continue
        at = pq.now_utc(r["publish_at"]) if r.get("publish_at") else (
            _noon(r["publish_day"]) if r.get("publish_day") else None)
        if at is None or at > now:
            continue
        if r.get("removed_at") and pq.now_utc(r["removed_at"]) <= at:
            continue
        out.append(dict(r, at=at))
    out.sort(key=lambda r: (r["at"], r.get("slug") or ""))
    for i, r in enumerate(out, 1):
        r["feed_position"] = i
    return out


def record_published(channel, root=None, now=None, journal=None, dry_run=False):
    """Fill `published_at`, `feed_position`, `video_id` of the script's ledger
    row for every published video. Idempotent; a cell holding another value is
    collected into `conflicts`, never raised (a bookkeeping disagreement does
    not stop a placement); a video with no row is listed under `no_row`.

    CF-0866: `feed_position` is a rank in the journal, so a video written into
    the journal before an already-ranked one shifts it. When `published_at` and
    `video_id` match and only the rank differs, that is not a conflict: the
    rank is re-derived (`Ledger.resync`, logged beside the CSV) and the row is
    listed under `shifted` as `{video, seq, old, new}`."""
    root = Path(root or ROOT)
    led = _ledger(channel, root)
    res = {"filled": [], "already": [], "no_row": [], "shifted": [], "conflicts": [],
           "ledger": None}
    if led is None:
        return res
    res["ledger"] = str(led.path)
    for r in published_rows(channel, root, now, journal):
        info = pair_of(channel, r.get("batch_id"), r.get("slug"), root)
        what = f"{r.get('batch_id')}/{r.get('slug')}"
        if not info["seq"]:
            res["no_row"].append(what)
            continue
        cells = {"published_at": r["at"].astimezone(timezone.utc).isoformat(), "feed_position": str(r["feed_position"]),
                 "video_id": r.get("video_id") or ""}
        row = led.row_by_seq(info["seq"])
        if all(row[c] == v for c, v in cells.items()):
            res["already"].append(what)
            continue
        clash = [c for c, v in cells.items() if row[c] and row[c] != v]
        if clash == ["feed_position"] and all(row[c] == cells[c] for c in ("published_at", "video_id")):
            shift = {"video": what, "seq": info["seq"], "old": row["feed_position"],
                     "new": cells["feed_position"]}
            if not dry_run:
                try:
                    led.resync(info["seq"], cells["feed_position"], by="publish_window.record",
                               task="CF-0866", why="feed rank re-derived from publish/uploads.json")
                except LedgerError as e:
                    res["conflicts"].append({"video": what, "seq": info["seq"], "error": str(e)})
                    continue
            res["shifted"].append(shift)
            continue
        if clash:
            res["conflicts"].append({"video": what, "seq": info["seq"], "cells": {
                c: [row[c], cells[c]] for c in clash}})
            continue
        if not dry_run:
            try:
                led.enrich(info["seq"], **cells)
            except LedgerError as e:
                res["conflicts"].append({"video": what, "seq": info["seq"], "error": str(e)})
                continue
        res["filled"].append(f"{what} -> seq {info['seq']}")
    return res


def shifted_line(shifted, dry_run=False):
    """One line for every re-derived rank (CF-0866) - information, not a WARNING."""
    seqs = ", ".join(f"{x['seq']}: {x['old']}->{x['new']}" for x in shifted)
    verb = "would be re-derived" if dry_run else "re-derived"
    return f"feed rank shifted for {len(shifted)} video(s), {verb} (CF-0866): seq {seqs}"


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def report(channel, root=None, now=None, out=sys.stdout):
    """The feed with pairs and every repeat inside K; returns the exit code."""
    wc = window_config(channel, root)
    if wc is None:
        print(f"{channel}: no patterns.rotation - no window", file=out)
        return EXIT_OK
    k = wc["k"]
    items = _with_pairs(channel, feed(channel, root, now), Path(root or ROOT), {})
    print(f"{channel}: K={k} (configured {wc['configured']}, {wc['pairs']} buildable pairs)",
          file=out)
    for x in items:
        state = "published" if x["published"] else ("studio" if x["in_studio"] else "planned")
        print(f"  {x['day']}  {x['slug']:<26} {state:<9} {_pairstr(x['pair']):<26} "
              f"{x['batch_id'] or '-'}" + ("" if x["pair"] else f"  [{x['pair_source']}]"), file=out)
    hits = repeats(items, k)
    for a, b in hits:
        print(f"  REPEAT {_pairstr(a['pair'])}: {a['slug']} ({a['day']}) and {b['slug']} "
              f"({b['day']}) are {items.index(b) - items.index(a)} apart, K={k}", file=out)
    blind = [x["slug"] for x in items if x["pair"] is None]
    print(f"  {len(hits)} repeat(s) inside K; no pair data: {len(blind)}"
          + (f" ({', '.join(blind)})" if blind else ""), file=out)
    return EXIT_REPEAT if hits else EXIT_OK


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record"):
        p = sub.add_parser(name)
        p.add_argument("--channel")
        p.add_argument("--root")
        p.add_argument("--now")
        if name == "record":
            p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    chans = [args.channel] if args.channel else _pq().queue_channels(args.root)
    code = EXIT_OK
    for ch in chans:
        try:
            if args.cmd == "check":
                code = max(code, report(ch, args.root, args.now, out))
                continue
            res = record_published(ch, args.root, args.now, dry_run=args.dry_run)
            print(f"{ch}: ledger {res['ledger'] or '(none)'}"
                  f"{' (dry run)' if args.dry_run else ''}: filled {len(res['filled'])}, "
                  f"already {len(res['already'])}, no row {len(res['no_row'])}, "
                  f"shifted {len(res['shifted'])}, conflicts {len(res['conflicts'])}", file=out)
            if res["shifted"]:
                print(f"  {shifted_line(res['shifted'], args.dry_run)}", file=out)
            for key in ("filled", "no_row"):
                for x in res[key]:
                    print(f"  {key}: {x}", file=out)
            for c in res["conflicts"]:
                print(f"  CONFLICT: {json.dumps(c, ensure_ascii=False)}", file=out)
            if res["conflicts"]:
                code = max(code, EXIT_ERROR)
        except (WindowError, _pq().QueueError) as e:
            print(f"PUBLISH WINDOW {ch}: {e}", file=out)
            code = max(code, EXIT_ERROR)
    return code


if __name__ == "__main__":
    sys.exit(main())
