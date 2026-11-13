#!/usr/bin/env python3
"""CF-0856: move a placed video to another day, or take it back into the
копилка - the two edits of the publication queue that placing (CF-0587,
`publish_card.py place`, `publish_stash.py`) does not make.

Why (23.10): gemini (slot 24.10) and spacex could not be uploaded to Studio;
the user asked for the queue to be shifted so the coming days have posts
("с 25 на 24, с 26 на 25"). The center moved the dates in Studio, the factory's
data was fixed by hand (commit 09ba3029). This is that fix as a tool - one
command, one plan, one commit:

* **unplace** `slug`: a video in a day folder `publish/<channel>/<day>/` that
  is not in Studio (no live row of `publish/uploads.json`) goes back into
  `publish/<channel>/_queue/` (note + mp4, `publish_layout.unassign`: the
  README row and the acceptance record's `publish_path` follow); its note's
  `## Публикация` becomes "Слот не назначен. ..." - no bold time, so
  `publish_note` / `publish_queue` read it as waiting and the копилка shows
  it; `publish_card.py place` / `publish_stash.py` put it into a slot again.
  A video already in Studio (a live journal row) is refused (`in_studio`): it
  is on the channel, the journal never deletes a row - move it instead.
* **move** `slug` to `day`: the video takes that day's slot of the channel
  (`channels/<id>.json` -> `publisher.slot`; the first free one when there are
  several). The note's `## Публикация` names the new slot in bold (the form
  `publish_note` reads) and the pair moves into the day folder
  (`publish_layout.move_day`). When the video is already in Studio (a live
  journal row), the row's `publish_at` / `publish_day` / `note` are rewritten
  and the move is appended to its `rescheduled` (from, to, when, by, via -
  `upload_records.reschedule`). The Studio part - the date in Studio itself -
  is the human's or the center's on the user's word; this tool never touches
  Studio, it writes the data after it (the answer says so in `warnings`).

* **withdraw** `slug` (CF-0918, the user's policy of 04.11: the feed 3 days
  ahead, a reserve of evergreen videos): a video already in Studio (a live
  journal row) with its slot ahead, taken off that slot in Studio first
  (scheduled -> «Ограниченный доступ», by a human or the center), goes into
  `_reserve/` (CF-0919: apart from the queue, so its name does not stand in the
  way of a new video); its `## Публикация` reads "Слот не
  назначен. В Studio: ограниченный доступ, video_id ..." and its journal row
  gets `withdrawn` (`upload_records.withdraw`: no slot, no day - nothing
  counts it as the feed any more). It stays in the копилка as reserve with
  its video id: a **move** of it to a day brings it back without a new upload
  (`return_reserve`: the pair into the day folder, `upload_records.reschedule`
  takes the mark off); so does `publish_stash.py confirm`. Its own refusals
  are `WITHDRAW_REFUSALS` (not_in_studio, in_reserve, not_placed, reserve_taken - CF-0920: the
  name and `<slug>~<batch>` both taken there, or no batch to name it by). A move to a
  day past the channel's horizon (`publish_queue.horizon`, min_feed_days) is
  written with a `HORIZON` warning - the day is the user's.

`--migrate-reserve` (CF-0919, `migrate_plan` / `migrate_confirm`): the videos
withdrawn before `_reserve/` existed, from `_queue/` into it (a dry run without
`--apply`) - the README row, `publish_path` and the journal row's `note` follow,
`withdrawn.from_note` and the `rescheduled` steps stay as they were.

A name two videos share (the reserve's and a new one, a hype repeat): `--unplace`
and `--withdraw` mean the placed one, `--move` names which: `BATCH/SLUG=DAY`.

Several edits go in one plan and are judged as a whole: every video named
leaves its day first, then each move takes its target day's slot - so a shift
"25->24, 26->25" with 24's video unplaced is no conflict (the order on disk
does not matter: the files of different slugs never collide). A target day is
refused when it is still taken after the plan (`day_taken`), has no slot of the
channel (`no_slot_day`), or its slot is sooner than the channel's lead
(`too_soon`). A video whose slot is already past is refused (`published`). The
candidate checks of placing (`publish_queue.check_candidate`: the CF-0042
pattern window) are asked about every move, with the other videos of the plan
where the plan puts them; what they say is a warning, never a refusal - the
user named the day.

The rotation ledger (`rotation/ledger/<channel>.csv`) is not touched: its only
day-bound columns (`published_at`, `feed_position`, `video_id`) are filled for
published videos (`publish_window.record_published`), and a published video
is never moved here. The answer says so in `ledger`.

Applying is all or nothing: one refusal anywhere and nothing is written.
Applying needs `by` and `via`, no batch going (a commit under an open batch
moves the root's HEAD under it, CF-0675), and - when given - `base_sha256`
still the state (`publish_stash.state_sha256`); it runs under the acceptance
record's lock, measures the files it touched (`publish_stash._snapshot`) and
commits exactly those (`git_commit.commit_paths`; the gitignored mp4 are left
out).

The answer (the shape of CF-0726 / `publish_stash`):

    {ok, written, dry_run, task, channel, by, via, base_sha256, sha256,
     new_sha256, commit, ledger,
     items [{op: move|unplace, slug, batch_id, video_id, in_studio, ok,
             from_day, from_slot, day, slot, label, refusals [{code, line}],
             warnings, path?, journal? {from_at, to_at}}],
     refusals [{code, line, slug?}], warnings, lines, touched [path]}

Refusal codes - top (`TOP_REFUSALS`): bad_who, unknown_channel, no_queue,
empty_order, batch_open, check_changed, apply_failed, commit_refused; per
item (`ITEM_REFUSALS`): bad_order, duplicate, not_found, in_queue, ambiguous,
inconsistent, published, in_studio, bad_day, same_day, no_slot_day, day_taken,
too_soon.

    python3 agents/publisher/publish_move.py --channel C [--unplace SLUG]... \\
        [--withdraw SLUG]... [--move SLUG=YYYY-MM-DD]... [--now ISO] [--root DIR] [--json]
        [--apply --by WHO --via WHAT [--base-sha256 H]]
        # exit 0 - ok (dry run or written), 1 - refused, 2 - error
"""
import argparse
import contextlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import acceptance                                               # noqa: E402
import publish_layout                                           # noqa: E402
import publish_queue                                            # noqa: E402
import publish_stash                                            # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0856"
TOOL = "agents/publisher/publish_move.py"
TOP_REFUSALS = ("bad_who", "unknown_channel", "no_queue", "empty_order", "batch_open",
                "check_changed", "apply_failed", "commit_refused")
ITEM_REFUSALS = ("bad_order", "duplicate", "not_found", "in_queue", "ambiguous", "inconsistent",
                 "published", "in_studio", "bad_day", "same_day", "no_slot_day", "day_taken",
                 "too_soon")
# CF-0918: the codes only a withdraw gives; the center sends withdraws too (CC-0179,
# contract 0.78.0: `api/publish_move.py` on cc/api names them in its MOVE_RU) - an
# unplace of a video already in the копилка is `in_queue`. CF-0919's `reserve_taken`
# is new there: until the center names it, it answers with the factory's line. CF-0920:
# a second video of a name goes under `<slug>~<batch>`, the refusal is the rare rest.
WITHDRAW_REFUSALS = ("not_in_studio", "in_reserve", "not_placed", "reserve_taken")
MIGRATE_TASK = "CF-0919"
WITHDRAW_TASK = "CF-0918"
LEDGER = ("not touched: its day-bound columns (published_at, feed_position, video_id) are "
          "filled for published videos only (publish_window.record_published), and a "
          "published video is not moved")


def _refusal(code, line):
    return {"code": code, "line": line}


def _git_commit():
    import git_commit                                           # noqa: PLC0415
    return git_commit


def _iso(at):
    return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if at else None


def _order(moves, unplace, withdraw=()):
    """`[(op, slug, day or None, raw)]` from `moves` (`{slug, day}` or
    `"slug=YYYY-MM-DD"`), `unplace` and `withdraw` (slugs)."""
    out = []
    for op, named in (("unplace", unplace), ("withdraw", withdraw)):
        for raw in named or ():
            slug = raw.get("slug") if isinstance(raw, dict) else raw
            out.append((op, str(slug or "").strip(), None, raw))
    for raw in moves or ():
        if isinstance(raw, dict):
            slug, day = raw.get("slug"), raw.get("day")
        else:
            slug, _, day = str(raw).partition("=")
        out.append(("move", str(slug or "").strip(), str(day or "").strip() or None, raw))
    return out


def _item(op, slug):
    return {"op": op, "slug": slug, "batch_id": None, "video_id": None, "in_studio": False,
            "ok": False, "from_day": None, "from_slot": None, "day": None, "slot": None,
            "label": None, "reserve": False, "refusals": [], "warnings": []}


def _day_slots(cfg, day):
    """The channel's slots that fall on the Moscow day `day`, in order."""
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return [at for at in publish_queue.slots(cfg, d - timedelta(days=1), 3)
            if publish_queue.msk_day(at) == day]


def _locate(cid, slug, pub, jrows, batch=None):
    """`(day entries, queue entries, reserve entries, live journal rows)` of
    `slug` in `cid`; `batch` narrows to the video of that batch (a name two
    videos share, CF-0919)."""
    mine = [e for e in publish_layout.entries(pub, cid) if e["channel"] == cid and e["slug"] == slug]
    rows = [r for r in jrows if r.get("slug") == slug]
    if batch:
        def of_batch(e):
            owner = publish_layout.batch_of(e)
            return owner is None or owner == batch
        mine = [e for e in mine if of_batch(e)]
        rows = [r for r in rows if r.get("batch_id") == batch]
    days = [e for e in mine if publish_layout.DAY_RE.match(e["bucket"])]
    queued = [e for e in mine if e["bucket"] == publish_layout.QUEUE]
    kept = [e for e in mine if e["bucket"] == publish_layout.RESERVE]
    return days, queued, kept, rows


def _reserve_taken_line(cid, slug, batch):
    """CF-0920: what is left of the refusal - a second video of a name goes under
    `<slug>~<batch>`, so only that file being there too, or no batch to name it by."""
    return (f"{slug}: publish/{cid}/{publish_layout.RESERVE}/ holds this name and "
            f"{publish_layout.file_stem(slug, batch) if batch else 'no batch tells this video'}"
            f" apart - bring that one back first (--move BATCH/{slug}=DAY)")


def _plan(cid, order, root, now, cfg):
    """The items of `order`, judged as one plan (see the module's docstring)."""
    pub = root / "publish"
    jpath = pub / "uploads.json"
    try:
        jrows = [r for r in upload_records.uploads(jpath, cid) if not r.get("removed_at")]
    except (upload_records.JournalError, ValueError) as e:
        raise publish_queue.QueueError(f"{jpath}: {e} - nothing is moved around an unreadable "
                                       f"journal") from e
    items, seen = [], set()
    for op, named, day, raw in order:
        slug, batch = publish_stash._wanted(named)
        it = _item(op, slug)
        items.append(it)
        refuse = it["refusals"].append
        if not slug or (op == "move" and not day):
            refuse(_refusal("bad_order", f"{raw!r}: a move is SLUG=YYYY-MM-DD, an unplace / a "
                                         f"withdraw a slug"))
            continue
        if (slug, batch) in seen:
            refuse(_refusal("duplicate", f"{slug}: named twice in one plan"))
            continue
        seen.add((slug, batch))
        days, queued, kept, rows = _locate(cid, slug, pub, jrows, batch)
        if not days and not rows:
            where = publish_layout.RESERVE if kept else publish_layout.QUEUE
            refuse(_refusal("in_queue", f"{slug}: waits in publish/{cid}/{where}/ with no slot - "
                                        f"nothing to move (publish_card.py place / "
                                        f"publish_stash.py put it into a slot)")
                   if queued or kept else
                   _refusal("not_found", f"{slug}: not in any day folder of publish/{cid}/ and "
                                         f"not in the upload journal"))
            continue
        live = [r for r in rows if not upload_records.is_withdrawn(r)]
        out = [r for r in rows if upload_records.is_withdrawn(r)]
        placed = bool(days or live)
        if placed and op == "move" and out:
            refuse(_refusal("ambiguous", f"{slug}: two videos of this name - on "
                            + ", ".join([e["bucket"] for e in days] or [str(r.get("video_id"))
                                                                        for r in live])
                            + f" and in the reserve ({out[0].get('video_id')}, "
                              f"{out[0].get('batch_id')}) - name it: --move BATCH/{slug}=DAY"))
            continue
        pool = live if placed else out
        if len(days) > 1 or len(pool) > 1:
            refuse(_refusal("ambiguous", f"{slug}: " + ", ".join(
                [f"publish/{cid}/{e['bucket']}/" for e in days]
                + [f"uploads.json:{r.get('video_id')}" for r in pool]) + " - more than one place"))
            continue
        e, row = (days[0] if days else None), (pool[0] if pool else None)
        if row is not None and upload_records.is_withdrawn(row):
            # CF-0918: in the копилка already - its pair in _reserve/ (CF-0919; before the
            # migration in _queue/), its row with no slot
            if op != "move":
                refuse(_refusal("in_reserve" if op == "withdraw" else "in_queue",
                                f"{slug}: already in the копилка (запас) "
                                              f"({row.get('video_id')}, withdrawn "
                                              f"{row['withdrawn'].get('at')}) - nothing to take "
                                              f"off a slot"))
                continue
            pair = kept[0] if len(kept) == 1 else None
            if pair is None and not kept:
                # CF-0920: `_queue/` may hold a namesake beside it, `x` and `x~batch`
                own = [q for q in queued
                       if publish_layout.batch_of(q) in (None, row.get("batch_id"))]
                pair = own[0] if len(own) == 1 else None
            if pair is None:
                refuse(_refusal("inconsistent", f"{slug}: the journal row {row.get('video_id')} "
                                                f"is withdrawn but publish/{cid}/ has "
                                                f"{len(kept)} _reserve/ and {len(queued)} "
                                                f"_queue/ pair(s) of it - fix the record first"))
                continue
            it.update(in_studio=True, video_id=row.get("video_id"), _entry=pair, _row=row,
                      reserve=True, batch_id=row.get("batch_id"))
            it["_from_at"] = None
        else:
            if _placed(it, cid, slug, op, e, row, days, root, cfg, now) is None:
                continue
        if op == "withdraw" and publish_layout.free_stem(
                pub, cid, publish_layout.RESERVE, slug,
                it.get("batch_id") or (publish_layout.batch_of(e) if e else None)) is None:
            refuse(_refusal("reserve_taken", _reserve_taken_line(cid, slug, it.get("batch_id"))))
            continue
        if op in ("unplace", "withdraw"):
            continue
        try:
            target = publish_layout.release_day(day)
        except publish_layout.LayoutError as exc:
            refuse(_refusal("bad_day", f"{slug}: {exc}"))
            continue
        it["day"] = target
        if target == it["from_day"]:
            refuse(_refusal("same_day", f"{slug}: already on {target}"))
            continue
        if not _day_slots(cfg, target):
            refuse(_refusal("no_slot_day", f"{slug}: {cid} has no slot on {target}"))
    _assign(cid, items, root, now, cfg)
    return items


def _placed(it, cid, slug, op, e, row, days, root, cfg, now):
    """The checks of a video on a day (not in the копилка): fills `it`, returns
    True when it may go on, None when an item refusal was added."""
    refuse = it["refusals"].append
    from_day = e["bucket"] if e else row.get("publish_day")
    if not from_day and row and row.get("publish_at"):
        from_day = publish_queue.msk_day(publish_queue.now_utc(row["publish_at"]))
    if e and row and row.get("publish_day") and row["publish_day"] != e["bucket"]:
        refuse(_refusal("inconsistent", f"{slug}: the folder says {e['bucket']}, the journal "
                                        f"row {row.get('video_id')} says {row['publish_day']}"
                                        f" - fix the record first"))
        return None
    it.update(from_day=from_day, in_studio=row is not None,
              video_id=(row or {}).get("video_id"), _entry=e, _row=row,
              batch_id=(row or {}).get("batch_id") or (
                  _window().batch_of_entry(cid, e, root) if e else None))
    if row is not None and row.get("publish_at"):
        at = publish_queue.now_utc(row["publish_at"])
    else:
        at = (publish_queue._note_time(e["md"]) if e and e["md"] else None)
        if at is None or publish_queue.msk_day(at) != from_day:
            own = _day_slots(cfg, from_day) if from_day else []
            at = own[0] if own else None
    it["from_slot"] = _iso(at)
    it["_from_at"] = at
    if at is not None and at <= now:
        refuse(_refusal("published", f"{slug}: its slot {publish_queue.label(at, cfg)} is "
                                     f"past - a published video is not "
                                     + ("taken back" if op != "move" else "moved")))
        return None
    if op == "unplace" and row is not None:
        refuse(_refusal("in_studio", f"{slug}: already in Studio ({row.get('video_id')}, "
                                     f"{row.get('publish_at') or row.get('publish_day')})"
                                     f" - it is on the channel and the journal keeps its "
                                     f"row; move it to another day, or --withdraw it into the "
                                     f"копилка (CF-0918)"))
        return None
    if op == "withdraw":
        if row is None:
            refuse(_refusal("not_in_studio", f"{slug}: not in Studio (no live row of "
                                             f"uploads.json) - --unplace takes it back into the "
                                             f"копилка"))
            return None
        if e is None:
            refuse(_refusal("not_placed", f"{slug}: {row.get('video_id')} has no pair in a day "
                                          f"folder of publish/{cid}/ - nothing to take into "
                                          f"_reserve/; fix the record first"))
            return None
    return True


def _window():
    import publish_window                                       # noqa: PLC0415
    return publish_window


def _assign(cid, items, root, now, cfg):
    """Give each move that is still ok its target day's slot - all the named
    videos off their days first; a move refused here keeps its video where it
    was, so the plan is judged again until nothing changes."""
    days = sorted({it["from_day"] for it in items if it["from_day"]}
                  | {it["day"] for it in items if it["day"]}
                  | {publish_queue.msk_day(now)})
    first = datetime.strptime(days[0], "%Y-%m-%d").date() - timedelta(days=1)
    span = (datetime.strptime(days[-1], "%Y-%m-%d").date() - first).days + 3
    base = publish_queue.table(cid, root, now, span, None, cfg, start=first)
    earliest = now + cfg["lead"]
    while True:
        going = {it["slug"] for it in items if not it["refusals"]}
        rows = [dict(r, taken_by=None if r["taken_by"] in going else r["taken_by"]) for r in base]
        newly = False
        for it in sorted((i for i in items if i["op"] == "move" and not i["refusals"]),
                         key=lambda i: (i["day"], i["slug"])):
            on_day = [r for r in rows if r["day"] == it["day"]]
            free = [r for r in on_day if r["taken_by"] is None and r["at"] >= earliest]
            if free:
                free[0]["taken_by"] = it["slug"]
                it.update(_slot=free[0]["at"], slot=_iso(free[0]["at"]),
                          label=publish_queue.label(free[0]["at"], cfg))
                continue
            if any(r["taken_by"] is None for r in on_day):
                it["refusals"].append(_refusal("too_soon", f"{it['slug']}: the slot of "
                                               f"{it['day']} is sooner than the channel's lead "
                                               f"({cfg['lead']}) - Studio cannot be set for it"))
            else:
                taken = ", ".join(sorted({r["taken_by"] for r in on_day if r["taken_by"]}))
                it["refusals"].append(_refusal("day_taken", f"{it['slug']}: {it['day']} is taken "
                                               f"by {taken} - move or unplace it in the same "
                                               f"plan"))
            newly = True
        if not newly:
            break
    for it in items:
        if it["op"] == "move" and it["refusals"]:
            it.update(_slot=None, slot=None, label=None)
    _warn(cid, items, root, now, cfg)


def _warn(cid, items, root, now, cfg):
    ok = [it for it in items if not it["refusals"]]
    hz = publish_queue.horizon(cid, root, now)
    removed = [it["slug"] for it in ok if it["op"] in ("unplace", "withdraw")]
    moved = {it["slug"]: {"slot": it["_slot"], "batch_id": it["batch_id"]}
             for it in ok if it["op"] == "move"}
    for it in ok:
        it["ok"] = True
        if it["op"] == "withdraw":
            it["warnings"].append(
                f"STUDIO {it['slug']} ({it['video_id']}): in Studio it must be taken off its "
                f"schedule - «Ограниченный доступ», no publication date - by a human or the "
                f"center on the user's word; this tool writes the journal and the копилка only "
                f"({WITHDRAW_TASK})")
            continue
        if it["op"] != "move":
            continue
        ctx = {"batch_id": it["batch_id"], "removed": removed,
               "moved": {s: m for s, m in moved.items() if s != it["slug"]}}
        try:
            objections = publish_queue.check_candidate(cid, it["slug"], it["_slot"], root, now, ctx)
        except Exception as e:                                  # noqa: BLE001
            objections = [{"verdict": "warn", "reason": f"the candidate checks did not answer: "
                                                        f"{e}"}]
        for o in objections:
            it["warnings"].append(("WINDOW (CF-0042, the day is the user's - not reordered): "
                                   if o.get("verdict") == "reorder" else "") + str(o.get("reason")))
        if not publish_queue.within_horizon(it["_slot"], hz):
            it["warnings"].append(
                f"HORIZON {it['slug']}: {it['label']} is past the channel's horizon "
                f"({hz['days']} дн., до {hz['last_day']} МСК; {publish_queue.HORIZON_TASK}) - "
                f"the day is the user's, written as named")
        if it.get("reserve"):
            it["warnings"].append(
                f"STUDIO {it['slug']} ({it['video_id']}) comes back from the копилка: in Studio "
                f"set «Отложенная публикация» on {it['label']} (it stands at «Ограниченный "
                f"доступ») - a human or the center on the user's word; no new upload "
                f"({WITHDRAW_TASK})")
        elif it["in_studio"]:
            it["warnings"].append(
                f"STUDIO {it['slug']} ({it['video_id']}) is in Studio: the date there is set by "
                f"a human or the center on the user's word - this tool writes the journal only "
                f"(it must read {it['label']} in Studio)")


def _strip(items):
    return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]


def _answer(cid, by, via, dry_run, base, sha, top, items, warnings=()):
    clean = _strip(items)
    refusals = top + [dict(r, slug=it["slug"]) for it in clean for r in it["refusals"]]
    lines = []
    for it in clean:
        if it["refusals"]:
            what = "; ".join(r["code"] for r in it["refusals"])
        elif it["op"] == "unplace":
            what = f"{it['from_day']} -> _queue/ (копилка)"
        elif it["op"] == "withdraw":
            what = (f"{it['from_day']} -> _reserve/ (запас, {it['video_id']}; в Studio ограниченный "
                    f"доступ) + журнал")
        else:
            what = f"{it['from_day'] or '_reserve/ (запас)'} -> {it['label']}" + (
                " + журнал (в Studio)" if it["in_studio"] else "")
        lines.append(f"{it['op']:<7} {it['slug']}: {what}")
        lines += [f"  WARNING {w}" for w in it["warnings"]]
    lines += [r["line"] for r in top] + [f"WARNING {w}" for w in warnings]
    return {"ok": not refusals, "written": False, "dry_run": dry_run, "task": TASK,
            "channel": cid, "by": by, "via": via, "base_sha256": base, "sha256": sha,
            "new_sha256": None, "commit": None, "ledger": LEDGER, "items": clean,
            "refusals": refusals, "warnings": list(warnings), "lines": lines, "touched": []}


def _setup(channel, moves, unplace, root, now, withdraw=()):
    """(cid, cfg, order, top refusals, warnings)."""
    top, warnings, cfg = [], [], None
    cid = publish_stash._channel(channel, root)
    order = _order(moves, unplace, withdraw)
    if cid is None:
        return None, None, order, [_refusal("unknown_channel", f"{channel!r}: no "
                                                               f"channels/<id>.json")], warnings
    if not order:
        top.append(_refusal("empty_order", "nothing named - --move SLUG=DAY / --unplace SLUG / "
                                           "--withdraw SLUG"))
    try:
        cfg = publish_queue.slot_config(cid, root)
        if cfg is None:
            top.append(_refusal("no_queue", f"{cid} has no publisher.slot in channels/{cid}.json"
                                            f" - it has no queue"))
    except publish_queue.QueueError as e:
        top.append(_refusal("no_queue", str(e)))
    if cfg is not None:
        why, notices = publish_queue.pause_state(cid, root, now)
        if why:
            warnings.append(f"PAUSE {cid}: publications are paused ({why}) - the moves are "
                            f"written, nothing goes out while the pause stands")
        warnings += [f"PAUSE {n}" for n in notices]
    return cid, cfg, order, top, warnings


def move_plan(channel, moves=(), unplace=(), root=None, now=None, by=None, via=None,
              withdraw=()):
    """What `move_confirm` would do - nothing written. `moves`: `[{slug, day}]`
    or `["slug=YYYY-MM-DD"]`; `unplace` / `withdraw` (CF-0918): `[slug]`. Its
    `sha256` is the `base_sha256` a confirm may take."""
    root = Path(root or ROOT)
    now = publish_queue.now_utc(now)
    cid, cfg, order, top, warnings = _setup(channel, moves, unplace, root, now, withdraw)
    if cid is None:
        return _answer(channel, by, via, True, None, None, top, [], warnings)
    sha = publish_stash.state_sha256(cid, root)
    items = _plan(cid, order, root, now, cfg) if cfg is not None and order else []
    return _answer(cid, by, via, True, sha, sha, top, items, warnings)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def _who_line(by, via):
    return f"{by}, {via}"


def move_line(at, cfg, from_day, now, by, via, in_studio):
    """The `## Публикация` body of a moved video: the slot in bold (the form
    `publish_note` reads), where from, by whom."""
    m = at.astimezone(publish_queue._zone(publish_queue.MSK))
    own = "" if cfg["tz"] == publish_queue.MSK else \
        f" ({at.astimezone(cfg['zone']):%Y-%m-%d %H:%M} {cfg['tz']} по поясу канала)"
    studio = "; в Studio дату переставили по слову пользователя" if in_studio else ""
    whence = f"перенесён с {from_day} ({TASK}" if from_day else \
        f"возвращён из запаса копилки ({WITHDRAW_TASK}"
    if not from_day and in_studio:
        studio = "; в Studio — отложенная публикация на этот слот по слову пользователя"
    return (f"**{m:%Y-%m-%d %H:%M} МСК**{own} — {whence}, `{TOOL}`, "
            f"{_who_line(by, via)}{studio}), {now.astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}.")


def unplace_line(from_day, now, by, via):
    """The `## Публикация` body of a video taken back into `_queue/`: no time
    in bold, so it reads as waiting."""
    return (f"Слот не назначен. Снят с {from_day} ({TASK}, `{TOOL}`, {_who_line(by, via)}), "
            f"{now.astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}. `publish_card.py place` или "
            f"копилка (`publish_stash.py`) ставят его в ближайший свободный слот (CF-0587, "
            f"`publish_queue.py`).")


def withdraw_line(from_day, video_id, now, by, via):
    """CF-0918: the `## Публикация` body of a video taken off its slot in
    Studio into the копилка: no time in bold (it reads as waiting), the video
    id it keeps - a return needs no new upload."""
    return (f"Слот не назначен. В Studio: ограниченный доступ, video_id {video_id} — снят с "
            f"{from_day} в запас ({WITHDRAW_TASK}, `{TOOL}`, {_who_line(by, via)}), "
            f"{now.astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}. Перезаливка не нужна: "
            f"`{TOOL} --move {{slug}}=ДЕНЬ` или копилка (`publish_stash.py`) ставят его в слот, "
            f"в Studio - отложенная публикация на этот слот.")


def _rewrite(md, body):
    if md and Path(md).is_file():
        p = Path(md)
        p.write_text(publish_queue.replace_section(p.read_text(encoding="utf-8"), "Публикация",
                                                   body), encoding="utf-8")


def _write(cid, items, root, now, cfg, by, via):
    pub = root / "publish"
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for it in [i for i in items if i["op"] in ("unplace", "withdraw")]:
        line = unplace_line(it["from_day"], now, by, via) if it["op"] == "unplace" else \
            withdraw_line(it["from_day"], it["video_id"], now, by, via)
        _rewrite(it["_entry"]["md"], line)
        to = publish_layout.QUEUE if it["op"] == "unplace" else publish_layout.RESERVE
        # CF-0920: a name taken there - the pair goes under <slug>~<batch>
        moved = publish_layout.unassign(it["slug"], cid, it["from_day"], publish=pub, apply=True,
                                        to=to, batch=it.get("batch_id"))
        it["path"] = publish_layout.note_rel(moved)
        if it["op"] == "withdraw":
            done = upload_records.withdraw(it["video_id"], note=it["path"], by=by, via=via,
                                           path=pub / "uploads.json", now=stamp)
            it["journal"] = {"from_at": done["withdrawn"]["from_at"], "to_at": None}
    for it in sorted((i for i in items if i["op"] == "move"), key=lambda i: (i["day"], i["slug"])):
        e, row = it.get("_entry"), it.get("_row")
        new_note = f"publish/{cid}/{it['day']}/{it['slug']}.md"
        if it.get("reserve"):
            it["path"], it["journal"] = return_reserve(cid, it["slug"], e["md"], row["video_id"],
                                                       it["_slot"], cfg, root, now, by, via,
                                                       bucket=e["bucket"])
            continue
        if e is not None:
            _rewrite(e["md"], move_line(it["_slot"], cfg, it["from_day"], now, by, via,
                                        it["in_studio"]))
            publish_layout.move_day(it["slug"], cid, it["from_day"], it["day"], publish=pub,
                                    apply=True)
            it["path"] = new_note
        if row is not None:
            old_note = f"publish/{cid}/{it['from_day']}/{it['slug']}.md"
            note = new_note if (e is not None or row.get("note") == old_note) else None
            done = upload_records.reschedule(row["video_id"], it["_slot"], note=note, by=by,
                                             via=via, path=pub / "uploads.json", now=stamp)
            it["journal"] = {"from_at": row.get("publish_at"), "to_at": done["publish_at"]}


def return_reserve(cid, slug, md, video_id, at, cfg, root, now, by, via,
                   bucket=publish_layout.RESERVE):
    """CF-0918: a video of the копилка's reserve (in Studio, withdrawn) back on
    the slot `at`: its note in `bucket` (`_reserve/`; `_queue/` before the
    migration, CF-0919) names the slot in bold, the pair goes
    to the day folder (`publish_layout.assign`), the journal row gets the slot
    again (`upload_records.reschedule`, the step `from_reserve`). No new upload;
    Studio - «Отложенная публикация» on that slot - is a human's or the
    center's. Returns `(note path from the root, {from_at, to_at})`.
    `publish_stash.py confirm` brings a reserve video back through here too."""
    pub = Path(root) / "publish"
    day = publish_queue.msk_day(at)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_note = f"publish/{cid}/{day}/{slug}.md"
    _rewrite(md, move_line(at, cfg, None, now, by, via, True))
    publish_layout.assign(slug, cid, day, publish=pub, apply=True, bucket=bucket,
                          stem=Path(md).stem if md else None)
    done = upload_records.reschedule(video_id, at, note=new_note, by=by, via=via,
                                     path=pub / "uploads.json", now=stamp, task=WITHDRAW_TASK)
    return new_note, {"from_at": None, "to_at": done["publish_at"]}


def _message(cid, items, by, via):
    parts = []
    for it in items:
        if it["op"] == "move":
            parts.append(f"{it['slug']} {it['from_day'][5:] if it['from_day'] else 'запас'}"
                         f"→{it['day'][5:]}")
    gone = [it["slug"] for it in items if it["op"] == "unplace"]
    kept = [it["slug"] for it in items if it["op"] == "withdraw"]
    subject = f"Очередь {cid}: " + "; ".join(
        ([("перенос " + ", ".join(parts))] if parts else [])
        + ([", ".join(gone) + " в копилку"] if gone else [])
        + ([", ".join(kept) + " в запас (снят из Studio)"] if kept else [])) \
        + f" ({_who_line(by, via)})"
    body = [f"{TASK}/{WITHDRAW_TASK}: перенос / снятие размещённого ролика (`{TOOL}`)."]
    for it in items:
        if it["op"] == "unplace":
            body.append(f"- {it['slug']}: publish/{cid}/{it['from_day']}/ -> _queue/, "
                        f"«Слот не назначен»")
        elif it["op"] == "withdraw":
            body.append(f"- {it['slug']}: publish/{cid}/{it['from_day']}/ -> _reserve/ (запас); "
                        f"uploads.json {it['video_id']}: withdrawn, publish_at "
                        f"{(it.get('journal') or {}).get('from_at')} -> null (в Studio "
                        f"ограниченный доступ по слову пользователя)")
        elif it.get("reserve"):
            body.append(f"- {it['slug']}: _reserve/ (запас) -> {it['label']}; uploads.json "
                        f"{it['video_id']}: publish_at null -> "
                        f"{(it.get('journal') or {}).get('to_at')} (в Studio отложенная "
                        f"публикация по слову пользователя)")
        else:
            body.append(f"- {it['slug']}: {it['from_day']} -> {it['label']}"
                        + (f"; uploads.json {it['video_id']}: publish_at "
                           f"{(it.get('journal') or {}).get('from_at')} -> "
                           f"{(it.get('journal') or {}).get('to_at')} (в Studio переставлено "
                           f"по слову пользователя)" if it["in_studio"] else ""))
    return subject + "\n\n" + "\n".join(body) + "\n"


def move_confirm(channel, moves=(), unplace=(), by=None, via=None, root=None, now=None,
                 base_sha256=None, open_rows=None, withdraw=()):
    """Apply the plan and commit it: all or nothing - any refusal (top or of
    an item) and nothing is written. `by` / `via` are required; `base_sha256`
    (from `move_plan`) is checked when given; `open_rows` - the rows of
    `runlog.open_batches` when the caller has them (a test: `[]`)."""
    root = Path(root or ROOT)
    now = publish_queue.now_utc(now)
    who = [_refusal("bad_who", w) for w in (publish_stash._who(by, "by"),
                                             publish_stash._who(via, "via")) if w]
    cid, cfg, order, top, warnings = _setup(channel, moves, unplace, root, now, withdraw)
    top = who + top
    if cid is None:
        return _answer(channel, by, via, False, base_sha256, None, top, [], warnings)
    if open_rows is None:          # a `shared/` on sys.path makes `runlog` the package
        open_rows = publish_stash._list_write().runlog().open_batches(root)
    going = acceptance.open_now(root, open_rows)
    if going:
        top.append(_refusal("batch_open", f"a batch is going ({going[0]['dir']}) - the move "
                                          f"commits and waits for it (CF-0675)"))
    log = root / "publish" / "acceptance-log.json"
    lock = acceptance._queue_lock(log) if log.parent.is_dir() else contextlib.nullcontext()
    with lock:
        sha = publish_stash.state_sha256(cid, root)
        if base_sha256 is not None and base_sha256 != sha:
            top.append(_refusal("check_changed", f"publish/{cid}/ or its journals changed since "
                                                 f"the plan ({base_sha256} -> {sha}) - plan "
                                                 f"again"))
        items = _plan(cid, order, root, now, cfg) if cfg is not None and order else []
        ans = _answer(cid, by, via, False, base_sha256, sha, top, items, warnings)
        if not ans["ok"]:
            return ans
        before = publish_stash._snapshot(root)
        try:
            _write(cid, items, root, now, cfg, by.strip(), via.strip())
        except (publish_layout.LayoutError, upload_records.JournalError, OSError) as e:
            ans = _answer(cid, by, via, False, base_sha256, sha,
                          [_refusal("apply_failed", f"stopped half-way: {e} - see `touched` "
                                                    f"and fix by hand")], items, warnings)
            ans["written"] = True
            ans["touched"] = publish_stash._touched(before, publish_stash._snapshot(root))
            return ans
        ans = _answer(cid, by, via, False, base_sha256, sha, [], items, warnings)
        ans["written"] = True
        ans["touched"] = publish_stash._touched(before, publish_stash._snapshot(root))
        ans["new_sha256"] = publish_stash.state_sha256(cid, root)
        gc = _git_commit()
        try:
            ans["commit"], _committed = gc.commit_paths(root, ans["touched"],
                                                        _message(cid, items, by, via))
        except (gc.CommitError, OSError) as e:
            ans["refusals"].append(_refusal("commit_refused", f"written, not committed: {e} "
                                            + " ".join(getattr(e, "details", []) or [])))
            ans["ok"] = False
        return ans


# --------------------------------------------------------------------------
# the migration of the reserve (CF-0919)
# --------------------------------------------------------------------------

def _migrate_items(cid, root):
    """The withdrawn rows whose pair still lies in `_queue/`: `[{slug, stem, video_id,
    batch_id, from, to, refusals}]`. CF-0920: a name the reserve holds already, or a
    second withdrawn row of one name - `to` is `<slug>~<batch>`."""
    pub = Path(root) / "publish"
    items, taken = [], set()
    for e, row in publish_queue.reserve_entries(cid, root):
        if e["bucket"] != publish_layout.QUEUE:
            continue
        batch = row.get("batch_id") or publish_layout.batch_of(e)
        stem = publish_layout.free_stem(pub, cid, publish_layout.RESERVE, e["slug"], batch, taken)
        taken.add(stem)
        it = {"slug": e["slug"], "stem": e["stem"], "video_id": row.get("video_id"),
              "batch_id": row.get("batch_id"),
              "from": publish_layout.rel(cid, publish_layout.QUEUE, e["stem"],
                                         publish_layout.NOTE),
              "to": publish_layout.rel(cid, publish_layout.RESERVE, stem or e["slug"],
                                       publish_layout.NOTE), "refusals": []}
        if stem is None:
            it["refusals"].append(_refusal("reserve_taken",
                                           _reserve_taken_line(cid, e["slug"], batch)))
        items.append(it)
    return items


def _migrate_answer(cid, by, via, dry_run, sha, top, items):
    refusals = top + [dict(r, slug=it["slug"]) for it in items for r in it["refusals"]]
    lines = [f"{it['slug']} ({it['video_id']}): {it['from']} -> {it['to']}"
             + (" - " + "; ".join(r["code"] for r in it["refusals"]) if it["refusals"] else "")
             for it in items]
    lines += [r["line"] for r in refusals]
    if not items and not refusals:
        lines.append(f"{cid}: the reserve is in _reserve/ already - nothing to migrate")
    return {"ok": not refusals, "written": False, "dry_run": dry_run, "task": MIGRATE_TASK,
            "channel": cid, "by": by, "via": via, "sha256": sha, "new_sha256": None,
            "commit": None, "items": items, "refusals": refusals, "lines": lines, "touched": []}


def migrate_plan(channel, root=None, by=None, via=None):
    """CF-0919: what `migrate_confirm` would do - nothing written."""
    root = Path(root or ROOT)
    cid = publish_stash._channel(channel, root)
    if cid is None:
        return _migrate_answer(channel, by, via, True, None, [
            _refusal("unknown_channel", f"{channel!r}: no channels/<id>.json")], [])
    return _migrate_answer(cid, by, via, True, publish_stash.state_sha256(cid, root), [],
                           _migrate_items(cid, root))


def migrate_confirm(channel, by=None, via=None, root=None, base_sha256=None, open_rows=None):
    """CF-0919: the reserve of `channel` from `_queue/` into `_reserve/`, one
    commit, all or nothing: the pair (`publish_layout.to_reserve`, with the README
    row and `publish_path`), the journal row's `note` (`upload_records.repoint_notes`;
    `withdrawn.from_note` and the `rescheduled` steps keep the history). Run twice,
    the second finds nothing to do."""
    root = Path(root or ROOT)
    top = [_refusal("bad_who", w) for w in (publish_stash._who(by, "by"),
                                             publish_stash._who(via, "via")) if w]
    cid = publish_stash._channel(channel, root)
    if cid is None:
        top.append(_refusal("unknown_channel", f"{channel!r}: no channels/<id>.json"))
        return _migrate_answer(channel, by, via, False, None, top, [])
    if open_rows is None:
        open_rows = publish_stash._list_write().runlog().open_batches(root)
    going = acceptance.open_now(root, open_rows)
    if going:
        top.append(_refusal("batch_open", f"a batch is going ({going[0]['dir']}) - the migration "
                                          f"commits and waits for it (CF-0675)"))
    pub = root / "publish"
    log = pub / "acceptance-log.json"
    lock = acceptance._queue_lock(log) if log.parent.is_dir() else contextlib.nullcontext()
    with lock:
        sha = publish_stash.state_sha256(cid, root)
        if base_sha256 is not None and base_sha256 != sha:
            top.append(_refusal("check_changed", f"publish/{cid}/ or its journals changed since "
                                                 f"the plan ({base_sha256} -> {sha}) - plan "
                                                 f"again"))
        items = _migrate_items(cid, root)
        ans = _migrate_answer(cid, by, via, False, sha, top, items)
        if not ans["ok"] or not items:
            return ans
        before = publish_stash._snapshot(root)
        try:
            for it in items:
                publish_layout.to_reserve(it["slug"], cid, publish=pub, apply=True,
                                          stem=it["stem"], batch=it["batch_id"])
            upload_records.repoint_notes({it["from"]: it["to"] for it in items},
                                         pub / "uploads.json")
        except (publish_layout.LayoutError, upload_records.JournalError, OSError) as e:
            ans["ok"], ans["written"] = False, True
            ans["refusals"].append(_refusal("apply_failed", f"stopped half-way: {e} - see "
                                                            f"`touched` and fix by hand"))
            ans["lines"].append(ans["refusals"][-1]["line"])
            ans["touched"] = publish_stash._touched(before, publish_stash._snapshot(root))
            return ans
        ans["written"] = True
        ans["touched"] = publish_stash._touched(before, publish_stash._snapshot(root))
        ans["new_sha256"] = publish_stash.state_sha256(cid, root)
        gc = _git_commit()
        subject = f"Запас {cid}: {len(items)} снятых роликов из _queue/ в _reserve/ ({by}, {via})"
        body = "\n".join(f"- {it['slug']} ({it['video_id']}, {it['batch_id']})" for it in items)
        try:
            ans["commit"], _done = gc.commit_paths(root, ans["touched"],
                                                   f"{subject}\n\n{MIGRATE_TASK}: запас живёт "
                                                   f"отдельно от очереди.\n{body}\n")
        except (gc.CommitError, OSError) as e:
            ans["ok"] = False
            ans["refusals"].append(_refusal("commit_refused", f"written, not committed: {e} "
                                            + " ".join(getattr(e, "details", []) or [])))
            ans["lines"].append(ans["refusals"][-1]["line"])
        return ans


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="publish_move.py",
                                 description="move a placed video to another day or back into "
                                             "the копилка (CF-0856); a dry run unless --apply")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--move", action="append", default=[], metavar="SLUG=YYYY-MM-DD")
    ap.add_argument("--unplace", action="append", default=[], metavar="SLUG")
    ap.add_argument("--withdraw", action="append", default=[], metavar="SLUG",
                    help="CF-0918: a video in Studio taken off its slot (Studio: «Ограниченный "
                         "доступ») into the копилка as reserve, with its video id")
    ap.add_argument("--migrate-reserve", action="store_true",
                    help="CF-0919: the videos withdrawn before _reserve/ existed, from _queue/ "
                         "into it; takes no --move/--unplace/--withdraw")
    ap.add_argument("--apply", action="store_true", help="write and commit")
    ap.add_argument("--by")
    ap.add_argument("--via")
    ap.add_argument("--base-sha256")
    ap.add_argument("--root")
    ap.add_argument("--now")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if ns.migrate_reserve:
            if ns.move or ns.unplace or ns.withdraw:
                ap.error("--migrate-reserve goes alone")
            res = migrate_confirm(ns.channel, ns.by, ns.via, ns.root, ns.base_sha256) \
                if ns.apply else migrate_plan(ns.channel, ns.root, ns.by, ns.via)
        elif ns.apply:
            res = move_confirm(ns.channel, ns.move, ns.unplace, ns.by, ns.via, ns.root, ns.now,
                               ns.base_sha256, withdraw=ns.withdraw)
        else:
            res = move_plan(ns.channel, ns.move, ns.unplace, ns.root, ns.now, ns.by, ns.via,
                            withdraw=ns.withdraw)
    except (publish_queue.QueueError, upload_records.JournalError) as e:
        print(f"publish_move: error: {e}", file=sys.stderr)
        return 2
    if ns.json:
        print(json.dumps(res, ensure_ascii=False, indent=2), file=out)
    else:
        print("\n".join(res["lines"]), file=out)
        if res["dry_run"]:
            print(f"dry run - nothing written; --apply --by WHO --via WHAT writes and commits "
                  f"(base_sha256 {res['sha256']})", file=out)
        else:
            print(f"commit {res['commit']}" if res["commit"] else "nothing committed", file=out)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
