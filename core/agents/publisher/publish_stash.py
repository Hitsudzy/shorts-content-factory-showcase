#!/usr/bin/env python3
"""CF-0738: the channel's копилка - the accepted videos waiting in
`publish/<channel>/_queue/` (CF-0919: and the reserve in `_reserve/`) with no
slot - read with its details for the command center, and placed onto the coming slots as one batch (plan/confirm).

The user's way of working (13.10, CC-0122): accept videos over several batches,
let them pile up, then put N of them on the coming week at once. Until now the
pile could not be seen with its details, and placing was one video at a time
(`publish_card.py place`, `rotation assign <slug> --apply`).

**The pile** (`stash`): per video in `_queue/` - its slug, its `title` and
`title_source` (CF-0750: the card's `## Название` as the card says it -
`card`; else the topic's `title_ref` in the batch's 01 - `topic`; else both
None), batch or rebuild,
when it was accepted, whether its card is there and ready, the paths of the
mp4 (in publish/) and of the thumbnail (in the batch), a hold, and its age:
days since the acceptance and, when the topic's news date is on file (the
trend hunter's `evidence.sources[].published_at` in the batch's 01), days
since the news. Beside it, `not_queued`: accepted rows of the channel that have
no place in publish/ and should (what `runlog acceptance --enqueue-accepted`
would do with them, CF-0738 item 2). CF-0921: and `other_version` - accepted
rows left out as another version of a placed video (`other_version_placed`)
only because the record has no topic or fact to tell a new video from a version
(`acceptance.VERSION_UNSURE`): the driver decides - a new video goes in with
`--other-version-ok`, a version stays out. A sure version (the same batch,
rebuild, topic, script or fact) and the rows the user settled (CF-0463) are
not listed: nothing is left to do with them.

**The aging rule** (CF-0741, the user's decision of 13.10 21:17: "возраст
считается от новости, если новость не протухает, то от даты принятия.
устаревший ролик только помечаем. порог 14 дней"). A video's age is counted
from its topic's news when the topic has a dated news hook (`age.news_at` is
on file: `age.basis` "news", `age.days` = `age.news_days`); a topic with no
dated news - an evergreen one, the news does not go off - is counted from the
acceptance (`age.basis` "accepted", `age.days` = `age.accepted_days`). The
trend hunter's topics carry no explicit news/evergreen marker (checked 13.10:
a topic is `topic_id, title_ref, signal, evidence, scenes, fact_*`, the
`kind: news` in `fact-sources.json` is a fact source's kind, not a topic's),
so a dated `evidence.sources[].published_at` is what the age counts from. A
video is `stale` when `age.days` > `STALE_AFTER_DAYS` (14): day 14 is still
fresh, day 15 is stale. Neither date on file - `basis`, `days` and `stale` are
None (unknown), not an error. The rule only marks: a stale video is placed,
queued and answered like any other - no refusal comes from it; `place_plan` /
`place_confirm` items carry `stale`, `age_days`, `age_basis` for display.
CF-0918: one exception - the копилка's own choice (`choose`, `--auto`) leaves
a stale *news* video out unless forced; named by hand it is placed, warned.
CF-0919: the rule is the news' - an evergreen video (`fact_kind.py`) has
`stale` False and is counted from the acceptance.

**Batch placement** (`place_plan` / `place_confirm`): K videos, in the order
given, onto the K nearest free slots of the channel. The slot rules are not
here: the plan reads the free slots from `publish_queue.table` (the channel's
`publisher.slot`, the lead time, the day folders, the upload journal) and
each confirmed video goes through `publish_card.place` - the one placing
there is (card next to the video, `publish_queue.plan_slot`, the pattern
window of CF-0042, `publish_layout.assign`) - one after another, in order, so
each takes the nearest slot left by the ones before it. A window reorder can
still swap a pair at confirm; the answer says where each one actually went.

**The feed's horizon and the reserve** (CF-0918, the user's policy of 04.11:
make videos 3 days ahead to post fresh news, keep a reserve of evergreen
ones). A video of the pile is `feed_kind` news or evergreen by its own fact -
title, description, the note's claims (CF-0919, `fact_kind.py`; a dated source
of the topic says where it was found, not what it is about), or by the driver's
mark (`kind`, the journal `publish/feed-kinds.json`) -, with `stale_at` for
news; an evergreen video does not age (the rule of CF-0741 is the news'). The
reserve lies apart from the queue (CF-0919, `_reserve/`: a new video of the same
name goes into `_queue/` as usual; the answer's `bucket` says which); two videos
of one name in the pile are told by `batch/slug`. `reserve` / `video_id` mark a video
withdrawn from Studio (`publish_move.py --withdraw`), which comes back by
`place_confirm` without a new upload (`publish_move.return_reserve`). No slot
past the channel's horizon (`publish_queue.horizon`: min_feed_days) is given -
`no_slot` with the line `beyond_horizon: ...`. `place_plan(..., auto=True)`
takes the pile's own order (`choose`): fresh news first, the one closest to
going stale first, then the evergreen reserve, as many as the slots inside
the horizon; a stale news video only with `force` (or named by hand, with a
`STALE` warning).

The answer has the shape of CF-0726:

    {ok, written, dry_run, task, channel, by, via, base_sha256, sha256,
     new_sha256, commit (None - the single place does not commit either),
     items [{slug, batch_id, entry_id, ok, slot, day, label, refusals
             [{code, line}], warnings, placed?, path?, report?}],
     refusals [{code, line}], lines, touched [path]}

`touched` (CF-0738 follow-up, for the center): every file a confirm created,
modified or removed, relative to the root, sorted, unique - a moved pair is
its old path in `_queue/` and its new one in the day folder, as `git status`
shows it. It is not gathered from what the place calls say (they write through
several helpers - the card, `publish_layout.assign`'s move and README row and
acceptance record, `publish_queue.apply_moves` of a CF-0042 reorder, the
ledger columns of `publish_window.record_published`), but measured: the files
under `publish/` and `rotation/ledger/` are snapshotted before and after the
placements, inside the same acceptance lock (`_snapshot`: a note or journal by
the sha256 of its bytes - rewritten with the same bytes is not touched -, an
mp4 by its size and mtime). Lock files (`*.lock`) and dot files are left out
(git ignores them). `place_plan` and a refused confirm answer `touched: []`.

`base_sha256` / `sha256` are the fingerprint of what a placement writes and
reads (`state_sha256`: the channel's publish/ folder, the acceptance record,
publish/README.md, the upload journal, the holds) - a confirm whose base is
not the state now is refused (`check_changed`).

Refusal codes - top level (`TOP_REFUSALS`): bad_who, unknown_channel,
no_queue, paused, batch_open, empty_order, check_changed; per video
(`ITEM_REFUSALS`): duplicate, not_in_queue, not_accepted, held,
render_missing, batch_missing, no_card, card_building (CF-0747: a build is
going), card_not_ready (neither ready nor taken by the user's ruling - a ruled
card is placed like a ready one, CF-0747), note_differs, no_slot, place_failed.

    python3 agents/publisher/publish_stash.py show --channel C [--now ISO] [--root DIR] [--json]
    python3 agents/publisher/publish_stash.py plan --channel C (SLUG... | --auto [--force]) [--now ISO] [--root DIR]
    python3 agents/publisher/publish_stash.py confirm --channel C SLUG... --base-sha256 H
        --by WHO --via WHAT [--now ISO] [--root DIR]
    python3 agents/publisher/publish_stash.py kind --channel C [BATCH/]SLUG news|evergreen
        --by WHO --via WHAT [--now ISO] [--root DIR]     # CF-0919: the driver's mark, committed
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import acceptance                                               # noqa: E402
import fact_kind                                                # noqa: E402
import publish_card                                             # noqa: E402
import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402
import publish_queue                                            # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0738"
FEED_TASK = "CF-0918"
KIND_TASK = "CF-0919"
KIND_JOURNAL = "feed-kinds.json"
WHO_MAX = 40
TOP_REFUSALS = ("bad_who", "unknown_channel", "no_queue", "paused", "batch_open",
                "empty_order", "check_changed")
ITEM_REFUSALS = ("duplicate", "not_in_queue", "not_accepted", "held", "render_missing",
                 "batch_missing", "no_card", "card_building", "card_not_ready", "note_differs",
                 "no_slot", "place_failed")
STALE_AFTER_DAYS = 14
STALENESS = {"rule": "CF-0741", "decided": "2026-10-13 21:17 (пользователь)",
             "threshold_days": STALE_AFTER_DAYS, "stale_when": f"days > {STALE_AFTER_DAYS}",
             "basis": "только новости (CF-0919: вид по факту ролика): news - от даты новости "
                      "темы (evidence.sources[].published_at в 01), если она есть; accepted - "
                      "от даты принятия; бессрочный ролик не стареет",
             "only_marks": True,
             "note": f"устаревшая новость (старше {STALE_AFTER_DAYS} дн. от новости или "
                     f"принятия, с датой впереди - после этой даты) только помечается: руками "
                     f"ставится; бессрочные не стареют"}
CARD_WORDS = {"none": "нет", "building": "собирается", "ready": "готова",
              "ruled": "принята решением пользователя", "not_ready": "не готова"}
_STATE_FILES = ("acceptance-log.json", "README.md", "uploads.json", "publication-holds.json",
                KIND_JOURNAL)
_TOUCH_SCOPE = ("publish", "rotation/ledger")


def _rel(path, root):
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _channel_ids():
    spec = importlib.util.spec_from_file_location("channel_ids_publish_stash",
                                                  ROOT / "shared" / "channel_ids.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _list_write():
    spec = importlib.util.spec_from_file_location("channel_list_write_publish_stash",
                                                  ROOT / "shared" / "channel_list_write.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _channel(channel, root):
    """Today's id of `channel`, or None when it has no `channels/<id>.json`."""
    ids = _channel_ids()
    cid = ids.resolve_channel(channel, root)
    return cid if cid and ids.channel_config_path(cid, root).is_file() else None


def _day(text):
    try:
        return datetime.fromisoformat(str(text)[:10]).date()
    except (TypeError, ValueError):
        return None


def _iso(at):
    return at.isoformat() if at is not None else None


# --------------------------------------------------------------------------
# the pile
# --------------------------------------------------------------------------

def state_sha256(channel, root=None):
    """The fingerprint of what a placement of `channel` reads and writes:
    every file under `publish/<channel>/` (a note by its bytes, an mp4 by its
    name and size) and the journals at the root of publish/."""
    root = Path(root or ROOT)
    pub = root / "publish"
    h = hashlib.sha256()
    files = [pub / n for n in _STATE_FILES]
    base = pub / channel
    if base.is_dir():
        files += sorted(p for p in base.rglob("*") if p.is_file() and not p.name.startswith("."))
    for p in files:
        if not p.is_file():
            continue
        h.update(str(p.relative_to(root)).encode("utf-8") + b"\0")
        if p.suffix == publish_layout.VIDEO:
            h.update(str(p.stat().st_size).encode("ascii"))
        else:
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def _snapshot(root):
    """`{relative path: fingerprint}` of every file a placement can write
    (`_TOUCH_SCOPE`): a note/journal by its sha256, an mp4 by size and mtime;
    lock and dot files left out."""
    root = Path(root)
    snap = {}
    for top in _TOUCH_SCOPE:
        base = root / top
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            rel = p.relative_to(root)
            if (any(part.startswith(".") for part in rel.parts) or p.suffix == ".lock"
                    or not p.is_file()):
                continue
            try:
                if p.suffix == publish_layout.VIDEO:
                    st = p.stat()
                    snap[str(rel)] = ("v", st.st_size, st.st_mtime_ns)
                else:
                    snap[str(rel)] = ("h", hashlib.sha256(p.read_bytes()).hexdigest())
            except OSError:
                continue
    return snap


def _touched(before, after):
    """The paths created, modified or removed between two `_snapshot`s."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def _row_for(entry, rows, cid, root):
    """The accepted row the video in `_queue/` belongs to: the one whose
    `publish_path` names it, else the batch its note names, else the only
    accepted row of the name without a place, else the latest accepted one."""
    slug = entry["slug"]
    mine = [r for r in rows if r.get("slug") == slug
            and publish_layout.channel_of_row(r, root=root) in (cid, None)]
    want = publish_layout.rel(cid, entry["bucket"], publish_layout.stem_of(entry))
    hit = [r for r in mine if r.get("publish_path") == want]
    if hit:
        return hit[-1]
    owner = publish_layout.batch_of(entry)
    if owner:
        hit = [r for r in mine if r.get("batch_id") == owner]
        if hit:
            return hit[-1]
    ok = [r for r in mine if r.get("verdict") == acceptance.ACCEPTED]
    free = [r for r in ok if not r.get("publish_path")]
    if len(free) == 1:
        return free[0]
    ok.sort(key=lambda r: str(r.get("recorded_at") or ""))
    return ok[-1] if ok else (mine[-1] if mine else None)


def news_date(batch_dir, topic_id):
    """`(published_at, source)` of the topic's news: the newest
    `evidence.sources[].published_at` of the topic in the batch's
    01-trend-hunter.json - `(None, why)` when it is not on file."""
    if batch_dir is None or not topic_id:
        return None, "no batch or no topic_id"
    p = Path(batch_dir) / "01-trend-hunter.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"{p.name}: not readable"
    for t in data.get("topics") or [] if isinstance(data, dict) else []:
        if not isinstance(t, dict) or t.get("topic_id") != topic_id:
            continue
        found = []
        for s in ((t.get("evidence") or {}).get("sources") or []):
            try:
                at = datetime.fromisoformat(str(s.get("published_at")).replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                continue
            found.append(at if at.tzinfo else at.replace(tzinfo=timezone.utc))
        if found:
            return max(found), f"{p.name}: topics[{topic_id}].evidence.sources[].published_at"
        return None, f"{p.name}: the topic carries no dated news source"
    return None, f"{p.name}: no topic {topic_id}"


def topic_title(batch_dir, topic_id):
    """The topic's `title_ref` in the batch's 01-trend-hunter.json, or None
    when the file, the topic or the field is not there (CF-0750)."""
    if batch_dir is None or not topic_id:
        return None
    try:
        data = json.loads((Path(batch_dir) / "01-trend-hunter.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for t in data.get("topics") or [] if isinstance(data, dict) else []:
        if isinstance(t, dict) and t.get("topic_id") == topic_id:
            ref = t.get("title_ref")
            return ref.strip() if isinstance(ref, str) and ref.strip() else None
    return None


def title_of(card, batch_dir, topic_id):
    """`(title, title_source)` of a video for the center (CF-0750): the card's
    `## Название` as the card says it (the channel's suffix included - the
    center trims) -> "card"; else the topic's `title_ref` -> "topic"; else
    `(None, None)`."""
    if card.get("title"):
        return card["title"], "card"
    ref = topic_title(batch_dir, topic_id)
    return (ref, "topic") if ref else (None, None)


def age_of(accepted_days, news_at, news_days, news_source):
    """The `age` of a video by the rule of CF-0741 (see the module's
    docstring): the news date when there is one, else the acceptance date;
    `stale` when the days are over `STALE_AFTER_DAYS`, None when unknown."""
    if news_at is not None and news_days is not None:
        basis, days = "news", news_days
    elif accepted_days is not None:
        basis, days = "accepted", accepted_days
    else:
        basis, days = None, None
    return {"accepted_days": accepted_days, "news_at": news_at, "news_days": news_days,
            "news_source": news_source, "basis": basis, "days": days,
            "stale": None if days is None else days > STALE_AFTER_DAYS}


def _card(entry, files, slug, root=None):
    """Where the card is (`publish` - already next to the video, else `batch`)
    and whether it is ready (`publish_card.card_state`).

    CF-0747: `state` - `none` (no card), `building` (a build of
    `card_center.py` is going for it), `ready`, `ruled` (taken by the user's
    ruling) or `not_ready` -, `placeable` (ready or ruled: what the placing
    reads), `reasons` (the codes of what kept it from being ready), `ruling`
    (by, via, words, at - a ruled card), and the last build's `build`
    `{run_id, log, code, started_at, by, via}` (None when it was never built
    from the center).

    CF-0750: `title` - the card's `## Название` (`publish_note`'s reading:
    its lines joined by a space), None when there is no card or no title."""
    out = {"present": False, "where": None, "path": None, "ready": None, "why_not": None,
           "batch": None, "state": "none", "placeable": False, "reasons": [], "ruling": None,
           "build": None, "title": None}
    md = entry.get("md") if entry else None
    src = Path(files["batch_dir"]) / publish_card.CARD_DIR / f"{slug}.md" \
        if files.get("batch_dir") else None
    for where, p in (("publish", md), ("batch", src)):
        if p and Path(p).is_file():
            text = Path(p).read_text(encoding="utf-8")
            st = publish_card.card_status(text)
            cb = publish_layout.card_batch(p)
            ruling = st["ruling"] if st["state"] == publish_card.RULED else None
            title = publish_note.title_and_description(publish_note.sections(text))[0]
            out.update(present=True, title=title or None, where=where, path=p, ready=st["state"] == publish_card.READY,
                       why_not=st["why"], batch=cb[1] if cb else None, state=st["state"],
                       placeable=bool(st["placeable"]), reasons=st["reasons"],
                       ruling=None if ruling is None else {
                           k: ruling.get(k) for k in ("by", "via", "words", "at")})
            break
    if files.get("batch_dir"):
        run = _card_center().last_run(files["batch_dir"], slug, root)
        if run is not None:
            out["build"] = run
            if run["code"] == "running":
                out["state"] = "building"
    return out


def _card_center():
    import card_center                                          # noqa: PLC0415
    return card_center


def feed_kind(age, facts, today=None, mark=None):
    """CF-0919: `{feed_kind, news_why, stale_at, kind_mark}` - the kind by the
    video's own fact (`fact_kind`: `facts` is its `judge`), or by the driver's
    mark (`mark`, `publish_stash.py kind`). `stale_at` (news only): a date the
    fact names ahead - that day, after it the video says what is no longer so;
    else 14 days after the news date (`age.news_at`), the fresh date of the
    headline or the acceptance; None when none is known. `today` given, `age`
    is brought to the kind: an evergreen video has no aging (the rule of CF-0741
    is the news' - `stale` False, counted from the acceptance), a news video is
    stale after its `stale_at`."""
    kind = mark["kind"] if mark else facts["feed_kind"]
    why = f"вид поставлен руками: {mark['by']}, {mark['via']}" if mark else facts["news_why"]
    if kind != fact_kind.NEWS:
        if today is not None:
            age.update(basis="accepted" if age.get("accepted_days") is not None else None,
                       days=age.get("accepted_days"), stale=False)
        return {"feed_kind": fact_kind.EVERGREEN, "news_why": None, "stale_at": None,
                "kind_mark": mark}
    if facts.get("ahead"):
        stale_at = facts["ahead"]
    else:
        base = None
        if age.get("news_at"):
            base = datetime.fromisoformat(str(age["news_at"]).replace("Z", "+00:00")).date()
        elif facts.get("fresh"):
            base = datetime.fromisoformat(facts["fresh"]).date()
        elif age.get("accepted_on"):
            base = datetime.fromisoformat(age["accepted_on"]).date()
        stale_at = (base + timedelta(days=STALE_AFTER_DAYS)).isoformat() if base else None
    if today is not None and stale_at:
        age["stale"] = today.isoformat() > stale_at
    return {"feed_kind": fact_kind.NEWS, "news_why": why, "stale_at": stale_at, "kind_mark": mark}


def _kind_marks(cid, root):
    """{(slug, batch_id): the last mark of `publish_stash.py kind`} of the channel."""
    p = Path(root) / "publish" / KIND_JOURNAL
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("marks") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return {(r.get("slug"), r.get("batch_id")): r for r in rows
            if isinstance(r, dict) and r.get("channel") == cid and r.get("kind") in fact_kind.KINDS}


def _reserve_rows(cid, root):
    """{(file's name, bucket): video_id} of the channel's reserve (CF-0918, CF-0919: a
    pair with its withdrawn journal row - a namesake is not it)."""
    try:
        return {(e["stem"], e["bucket"]): r.get("video_id")
                for e, r in publish_queue.reserve_entries(cid, root)}
    except publish_queue.QueueError:
        return {}


def _detail(entry, row, cid, root, now, holds, reserve=None, marks=None):
    slug = entry["slug"] if entry else row["slug"]
    files = acceptance.rendered_files(row, root=root) if row else \
        {"batch_dir": None, "mp4": None, "thumbnail": None}
    card = _card(entry, files, slug, root)
    b = files["batch_dir"]
    news_at, news_src = news_date(b, (row or {}).get("topic_id"))
    acc_day = _day((row or {}).get("answered_at"))
    held = acceptance.held_row(row, path=holds, root=root) if row else None
    mp4 = entry.get("mp4") if entry else None
    title, title_source = title_of(card, b, (row or {}).get("topic_id"))
    age = age_of((now.date() - acc_day).days if acc_day else None, _iso(news_at),
                 int((now - news_at).total_seconds() // 86400) if news_at else None, news_src)
    facts = fact_kind.of_video(card["path"], b, (row or {}).get("topic_id"), acc_day or now.date())
    aging = dict(age, accepted_on=acc_day.isoformat() if acc_day else None)
    kind = feed_kind(aging, facts, today=now.date(),
                     mark=(marks or {}).get((slug, (row or {}).get("batch_id"))))
    aging.pop("accepted_on")
    age = aging
    bucket = entry["bucket"] if entry else None
    vid = (reserve or {}).get((publish_layout.stem_of(entry), bucket)) \
        if entry is not None else None
    return {
        "slug": slug, "channel": cid, "title": title, "title_source": title_source,
        "entry_id": (row or {}).get("entry_id"), "batch_id": (row or {}).get("batch_id"),
        "verdict": (row or {}).get("verdict"),
        "kind": None if b is None else ("rebuild" if Path(b).parent.name == "rebuilds"
                                        else "batch"),
        "batch_dir": _rel(b, root),
        "accepted_at": (row or {}).get("answered_at"),
        "recorded_at": (row or {}).get("recorded_at"),
        "pending": bool((row or {}).get("pending")),
        "in_queue": entry is not None,
        "bucket": bucket,
        "mp4": _rel(mp4, root) if mp4 else ((row or {}).get("publish_path") if entry else None),
        "mp4_present": bool(mp4 and Path(mp4).is_file()),
        "source_mp4": _rel(files["mp4"], root),
        "thumbnail": _rel(files["thumbnail"], root),
        "card": dict(card, path=_rel(card["path"], root)),
        "held": bool(held), "hold_id": (held or {}).get("hold_id"),
        "topic_id": (row or {}).get("topic_id"),
        "age": age,
        **kind,
        "reserve": vid is not None, "video_id": vid,
    }


def stash(channel, root=None, now=None):
    """The channel's pile with its details (see the module's docstring):
    `{channel, task, now, count, stale, videos [...], not_queued [...], other_version [...],
    staleness}` -
    `stale` is how many videos in the pile are stale by the rule of CF-0741.
    Read only."""
    root = Path(root or ROOT)
    cid = _channel(channel, root)
    if cid is None:
        raise publish_queue.QueueError(f"{channel!r}: no channels/<id>.json - unknown channel")
    now = publish_queue.now_utc(now)
    pub = root / "publish"
    rows = acceptance.entries(path=pub / "acceptance-log.json")
    holds = pub / "publication-holds.json"
    reserve = _reserve_rows(cid, root)
    marks = _kind_marks(cid, root)
    videos = [_detail(e, _row_for(e, rows, cid, root), cid, root, now, holds, reserve, marks)
              for e in publish_layout.entries(pub, cid)
              if e["channel"] == cid and e["bucket"] in publish_layout.WAITING]
    videos.sort(key=_by_acceptance)
    lost, versions = [], []
    for r in acceptance.unqueued(rows):
        if publish_layout.channel_of_row(r, root=root) != cid:
            continue
        q = acceptance.queue_accepted(r, rows, root=root, publish_dir=pub, apply=False)
        if q["skipped"]:
            # another version is out (CF-0463): not lost, by design - CF-0921: unless
            # the rule could not tell it from a new video, then the driver decides
            if q.get("version_unsure"):
                d = _detail(None, r, cid, root, now, holds, marks=marks)
                d.update(queue_code=q["code"], queue_text_ru=q["text_ru"],
                         other_entry=q.get("other_entry"), other_path=q.get("other_path"),
                         other_why=q.get("other_why"), repair=q.get("repair"))
                versions.append(d)
            continue
        d = _detail(None, r, cid, root, now, holds, marks=marks)
        d.update(queue_code=q["code"], queue_text_ru=q["text_ru"],
                 repair=f"runlog acceptance --enqueue-accepted --entry {r.get('entry_id')}")
        lost.append(d)
    return {"channel": cid, "task": TASK, "now": _iso(now), "count": len(videos),
            "stale": sum(1 for v in videos if v["age"]["stale"]), "videos": videos,
            "not_queued": lost, "other_version": versions, "staleness": dict(STALENESS),
            "news": sum(1 for v in videos if v["feed_kind"] == "news"),
            "reserve": sum(1 for v in videos if v["reserve"]),
            "horizon": publish_queue.horizon(cid, root, now)}


def _by_acceptance(v):
    """The order of acceptance by the day, then the name: `answered_at` comes as
    a date and as a timestamp, and as raw strings "2026-10-12" stands before
    "2026-10-12T08:00:00Z" of the same day (CF-0919)."""
    return (str(_day(v["accepted_at"]) or ""), v["slug"])


def stale_news(v):
    """CF-0918: a news video gone stale by CF-0741 - it is not chosen for a slot
    by itself (`choose`), only by hand."""
    return v.get("feed_kind") == "news" and v["age"].get("stale") is True


def _card_refusal(v):
    """Why the card of pile video `v` cannot be placed: `{code, line}`, or None.
    A reserve video has its card in its note, it comes back by the journal."""
    slug, c = v["slug"], v["card"]
    if v["reserve"]:
        return None
    if not c["present"]:
        return _refusal("no_card", f"{slug}: no card - build it first (publish_card.py build)")
    if c["state"] == "building":
        return _refusal("card_building", f"{slug}: the card is being built "
                                         f"({c['build']['log']}) - wait for it")
    if not c["placeable"]:
        return _refusal("card_not_ready", f"{slug}: the card is not ready ({c['why_not']})")
    if c["where"] == "publish" and c["batch"] not in (None, v["batch_id"]):
        return _refusal("note_differs", f"{slug}: the note in {v['bucket']}/ is of batch "
                                        f"{c['batch']}, not {v['batch_id']}")
    return None


def choose(channel, root=None, now=None, force=False):
    """CF-0918: the order the копилка fills the free slots in by itself - the
    fresh news first, the one closest to going stale first (its `stale_at`, a
    day; CF-0919: one day is one day whatever it was counted from, then the name);
    then the evergreen reserve, oldest accepted first.
    A stale news video is left out (`skipped`, reason `stale_news`) unless
    `force`; CF-0919: so is a video whose card cannot be placed (the reason is
    the placing's code: `no_card`, `card_building`, `card_not_ready`,
    `note_differs`), whatever `force` - its slot goes to the next one. Returns `(slugs - `batch/slug` for a name two videos of the pile
    share -, skipped [{slug, batch_id, reason, line}])`; the placing
    itself (its refusals, the horizon) is `place_plan`'s."""
    res = stash(channel, root, now)
    news, evergreen, skipped = [], [], []
    for v in res["videos"]:
        no_card = _card_refusal(v)
        if stale_news(v) and not force:
            skipped.append({"slug": v["slug"], "batch_id": v["batch_id"], "reason": "stale_news",
                            "line": f"{v['slug']}: новость устарела ({v['age']['days']} дн., "
                                    f"{STALENESS['rule']}) - в слот только руками или с --force"})
        elif no_card:
            skipped.append({"slug": v["slug"], "batch_id": v["batch_id"], "reason": no_card["code"],
                            "line": no_card["line"]})
        elif v["feed_kind"] == "news":
            news.append(v)
        else:
            evergreen.append(v)
    news.sort(key=lambda v: (v["stale_at"] or "9999", v["slug"]))
    evergreen.sort(key=_by_acceptance)
    names = [v["slug"] for v in res["videos"]]
    return [v["slug"] if names.count(v["slug"]) == 1 else f"{v['batch_id']}/{v['slug']}"
            for v in news + evergreen], skipped


# --------------------------------------------------------------------------
# placing a batch of them
# --------------------------------------------------------------------------

def _refusal(code, line):
    return {"code": code, "line": line}


def _who(value, what):
    if not isinstance(value, str) or not value.strip():
        return f"{what}={value!r}: a placement is somebody's - a short non-empty string"
    if len(value.strip()) > WHO_MAX or any(c in value for c in "\r\n\t"):
        return f"{what}={value!r}: at most {WHO_MAX} characters on one line"
    return None


def _wanted(item):
    """`(slug, batch_id or None)` of one entry of `order`: a slug, `batch/slug`
    or `{slug, batch_id}`."""
    if isinstance(item, dict):
        return str(item.get("slug") or ""), item.get("batch_id")
    s = str(item or "").strip()
    if "/" in s:
        b, _, slug = s.rpartition("/")
        return slug, b.rpartition("/")[2] or None
    return s, None


def _not_one_line(cid, slug, batch, cands):
    """The line of a name that is not one video of the pile."""
    if len(cands) > 1:
        return (f"{slug}: {len(cands)} videos of this name wait in publish/{cid}/ - name which: "
                + " or ".join(f"{v['batch_id']}/{slug} ({v.get('bucket')})" for v in cands))
    return f"{slug}: not waiting in the копилка of {cid}" + (f" as batch {batch}" if batch else "")


def _plan(cid, order, root, now, open_rows, check_open=True):
    """(top refusals, items, cfg) - the shared reading of plan and confirm."""
    top, items = [], []
    cfg = None
    if not order:
        top.append(_refusal("empty_order", "no video named - order lists the slugs to place"))
    try:
        cfg = publish_queue.slot_config(cid, root)
        if cfg is None:
            top.append(_refusal("no_queue", f"{cid} has no publisher.slot in "
                                             f"channels/{cid}.json - it has no queue"))
    except publish_queue.QueueError as e:
        top.append(_refusal("no_queue", str(e)))
    if cfg is not None:
        why, _notices = publish_queue.pause_state(cid, root, now)
        if why:
            top.append(_refusal("paused", f"{cid}: publications are paused ({why})"))
    if check_open:
        going = _list_write().open_batches_of(cid, root, now=now, open_rows=open_rows)
        if going:
            top.append(_refusal("batch_open", f"a batch of {cid} is going ({going[0][0]}) - "
                                              f"the placement waits for it"))
    pile = {}
    for v in stash(cid, root, now)["videos"]:
        pile.setdefault(v["slug"], []).append(v)
    free, later = [], []
    hz = publish_queue.horizon(cid, root, now)
    if cfg is not None:
        earliest = now + cfg["lead"]
        try:
            free = [r["at"] for r in publish_queue.table(cid, root, now,
                                                         publish_queue.HORIZON_DAYS, None, cfg)
                    if r["taken_by"] is None and r["at"] >= earliest]
        except publish_queue.QueueError as e:
            top.append(_refusal("no_queue", str(e)))
        # CF-0918: a slot past the channel's horizon (min_feed_days) is not given
        later = [at for at in free if not publish_queue.within_horizon(at, hz)]
        free = [at for at in free if publish_queue.within_horizon(at, hz)]
    seen, planned, taken = set(), {}, 0
    for raw in order or []:
        slug, batch = _wanted(raw)
        it = {"slug": slug, "batch_id": batch, "entry_id": None, "ok": False, "slot": None,
              "day": None, "label": None, "stale": None, "age_days": None, "age_basis": None,
              "beyond_horizon": False, "feed_kind": None, "stale_at": None, "reserve": False,
              "video_id": None, "refusals": [], "warnings": []}
        items.append(it)
        refuse = it["refusals"].append
        if (slug, batch) in seen:
            refuse(_refusal("duplicate", f"{slug}: named twice in the order"))
            continue
        seen.add((slug, batch))
        cands = [v for v in pile.get(slug, []) if batch is None or v["batch_id"] == batch]
        if len(cands) == 1:
            one = (slug, cands[0]["batch_id"], "video")
            if one in seen:
                refuse(_refusal("duplicate", f"{slug}: named twice in the order"))
                continue
            seen.add(one)
        if len(cands) != 1:
            refuse(_refusal("not_in_queue", _not_one_line(cid, slug, batch, cands)))
            continue
        v = cands[0]
        it.update(batch_id=v["batch_id"], entry_id=v["entry_id"], stale=v["age"]["stale"],
                  age_days=v["age"]["days"], age_basis=v["age"]["basis"],
                  feed_kind=v["feed_kind"], stale_at=v["stale_at"], reserve=v["reserve"],
                  video_id=v["video_id"])
        if v["verdict"] != acceptance.ACCEPTED:
            refuse(_refusal("not_accepted", f"{slug}: {v['verdict'] or 'no verdict'} in the "
                                            f"acceptance record - no slot"))
        if v["held"]:
            refuse(_refusal("held", f"{slug}: publication hold {v['hold_id']} stands unsigned "
                                    f"(CF-0318)"))
        if not v["mp4_present"]:
            refuse(_refusal("render_missing", f"{slug}: no {slug}.mp4 in publish/{cid}/"
                                              f"{v['bucket']}/"))
        if v["bucket"] == publish_layout.RESERVE and not v["reserve"]:
            refuse(_refusal("not_in_queue", f"{slug}: lies in publish/{cid}/_reserve/ with no "
                                            f"withdrawn row of uploads.json - fix the record"))
        if stale_news(v):
            it["warnings"].append(f"STALE {slug}: новость устарела ({v['age']['days']} дн., "
                                  f"{STALENESS['rule']}) - ставится, потому что названа руками "
                                  f"({FEED_TASK})")
        if v["reserve"]:
            # CF-0918: in Studio already - its note in _reserve/ is its card; it comes back
            # by the journal (publish_move.return_reserve), not by a new placing
            it["warnings"].append(f"STUDIO {slug} ({v['video_id']}) comes back from the "
                                  f"копилка: in Studio set «Отложенная публикация» on its slot "
                                  f"(it stands at «Ограниченный доступ») - no new upload "
                                  f"({FEED_TASK})")
        elif not v["batch_dir"]:
            refuse(_refusal("batch_missing", f"{slug}: the batch of {v['entry_id']} is not "
                                             f"on disk - the card cannot be placed from it"))
        if _card_refusal(v):
            refuse(_card_refusal(v))
        if it["refusals"]:
            continue
        if taken >= len(free):
            if later:
                it["beyond_horizon"] = True
                refuse(_refusal("no_slot", publish_queue.beyond_line(slug, later[0], hz, cfg)))
            else:
                refuse(_refusal("no_slot", f"{slug}: no free slot left in "
                                           f"{publish_queue.HORIZON_DAYS} days"))
            continue
        at = free[taken]
        taken += 1
        planned[slug] = {"slot": at, "batch_id": v["batch_id"]}
        it.update(ok=True, slot=_iso(at), day=publish_queue.msk_day(at),
                  label=publish_queue.label(at, cfg), _v=v, _at=at)
    for it in items:
        if not it["ok"]:
            continue
        at = it["_at"]
        moved = {s: p for s, p in planned.items() if s != it["slug"]}
        try:
            objections = publish_queue.check_candidate(cid, it["slug"], at, root, now,
                                                       {"batch_id": it["batch_id"],
                                                        "moved": moved})
        except Exception as e:                                  # noqa: BLE001
            objections = [{"verdict": "warn", "reason": f"the candidate checks did not "
                                                        f"answer: {e}"}]
        for o in objections:
            it["warnings"].append(("WINDOW (CF-0042, at confirm the pair may be swapped): "
                                   if o.get("verdict") == "reorder" else "")
                                  + str(o.get("reason")))
    return top, items, cfg


def _answer(cid, by, via, dry_run, base, now_sha, top, items):
    clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
    refusals = top + [dict(r, slug=it["slug"]) for it in clean for r in it["refusals"]]
    lines = [f"{it['slug']}: " + (it["label"] if it["ok"] else
                                  "; ".join(r["code"] for r in it["refusals"]))
             + (f" (устарел: {it['age_days']} дн.)" if it.get("stale") else "")
             for it in clean]
    return {"ok": not refusals, "written": False, "dry_run": dry_run, "task": TASK,
            "channel": cid, "by": by, "via": via, "base_sha256": base, "sha256": now_sha,
            "new_sha256": None, "commit": None, "items": clean, "refusals": refusals,
            "lines": lines + [r["line"] for r in top], "touched": []}


def _auto(cid, order, root, now, auto, force):
    """CF-0918: `(order, skipped)` - with `auto` the order is `choose`'s (fresh
    news first, then the reserve), as many as the free slots inside the
    horizon take; the rest wait in the копилка."""
    if not auto:
        return order, []
    slugs, skipped = choose(cid, root, now, force=force)
    try:
        cfg = publish_queue.slot_config(cid, root)
    except publish_queue.QueueError:
        cfg = None
    if cfg is None:
        return slugs, skipped
    hz = publish_queue.horizon(cid, root, now)
    earliest = now + cfg["lead"]
    free = [r for r in publish_queue.table(cid, root, now, publish_queue.HORIZON_DAYS, None, cfg)
            if r["taken_by"] is None and r["at"] >= earliest
            and publish_queue.within_horizon(r["at"], hz)]
    return slugs[:len(free)], skipped + [
        {"slug": s, "reason": "beyond_horizon",
         "line": f"{s}: свободных слотов в горизонте {hz['days']} дн. (до {hz['last_day']}) не "
                 f"осталось - ждёт в копилке"} for s in slugs[len(free):]]


def place_plan(channel, order, root=None, now=None, by=None, via=None, open_rows=None,
               auto=False, force=False):
    """What placing `order` would do - nothing written. `base_sha256` of the
    answer is what `place_confirm` takes. CF-0918: `auto` - the order is the
    копилка's own (`choose`: fresh news first, then the evergreen reserve, as
    many as the free slots inside the horizon take; `skipped` says what waits
    and why); `force` lets a stale news video into that choice."""
    root = Path(root or ROOT)
    now = publish_queue.now_utc(now)
    cid = _channel(channel, root)
    if cid is None:
        return _answer(channel, by, via, True, None, None,
                       [_refusal("unknown_channel", f"{channel!r}: no channels/<id>.json")], [])
    sha = state_sha256(cid, root)
    order, skipped = _auto(cid, order, root, now, auto, force)
    top, items, _cfg = _plan(cid, order, root, now, open_rows)
    ans = _answer(cid, by, via, True, sha, sha, top, items)
    if auto:
        ans["order"], ans["skipped"] = list(order), skipped
        ans["lines"] += [f"ждёт: {x['line']}" for x in skipped]
    return ans


def place_confirm(channel, order, base_sha256, by, via, root=None, now=None, open_rows=None,
                  auto=False, force=False):
    """Place `order`: refused as a whole on a top-level refusal (bad_who,
    unknown_channel, no_queue, paused, batch_open, empty_order,
    check_changed); otherwise each video that passes goes through
    `publish_card.place` in order, a video refused - or failing there
    (`place_failed`) - is reported on its item and does not stop the others.
    Each placed item carries `placed`, `path` (the card), the `day` it
    actually went to and the factory's `report` lines."""
    root = Path(root or ROOT)
    now = publish_queue.now_utc(now)
    cid = _channel(channel, root)
    top = [_refusal("bad_who", why) for why in (_who(by, "by"), _who(via, "via")) if why]
    if cid is None:
        top.append(_refusal("unknown_channel", f"{channel!r}: no channels/<id>.json"))
        return _answer(channel, by, via, False, base_sha256, None, top, [])
    pub = root / "publish"
    log = pub / "acceptance-log.json"
    lock = acceptance._queue_lock(log) if log.parent.is_dir() else contextlib.nullcontext()
    with lock:
        sha = state_sha256(cid, root)
        if base_sha256 != sha:
            top.append(_refusal("check_changed", f"publish/{cid}/ or its journals changed since "
                                                 f"the plan ({base_sha256} -> {sha}) - plan "
                                                 f"again"))
        order, skipped = _auto(cid, order, root, now, auto, force)
        more, items, cfg = _plan(cid, order, root, now, open_rows)
        top += more
        if top:
            return _answer(cid, by, via, False, base_sha256, sha, top, items)
        written = False
        before = _snapshot(root)
        for it in items:
            v = it.get("_v")
            if not it["ok"] or v is None:
                continue
            report = []
            if v["reserve"]:
                try:
                    p = _return_reserve(cid, it, v, cfg, root, now, by.strip(), via.strip())
                except (publish_queue.QueueError, publish_layout.LayoutError,
                        upload_records.JournalError, OSError) as e:
                    it["ok"] = False
                    it["refusals"].append(_refusal("place_failed", f"{it['slug']}: {e}"))
                    continue
                written = True
                it.update(placed=True, path=p, report=[f"journal {v['video_id']}: back from the "
                                                       f"копилка on {it['label']}"])
                continue
            try:
                p = publish_card.place(root / v["batch_dir"], it["slug"], channel=cid,
                                       replace=v["card"]["where"] == "publish", root=root,
                                       now=now, report=report)
            except (publish_card.CardError, publish_queue.QueueError,
                    publish_layout.LayoutError, OSError) as e:
                it["ok"] = False
                it["refusals"].append(_refusal("place_failed", f"{it['slug']}: {e}"))
                continue
            written = True
            where = publish_layout.bucket_of(p, pub)
            day = where[1] if where else None
            it.update(placed=True, path=_rel(p, root), report=report)
            if day != it["day"]:
                it["warnings"].append(f"planned {it['day']}, went to {day} (the queue "
                                      f"decided at confirm - CF-0042 or a slot taken)")
                it["day"] = day
        ans = _answer(cid, by, via, False, base_sha256, sha, [], items)
        if auto:
            ans["order"], ans["skipped"] = list(order), skipped
        ans["written"] = written
        ans["new_sha256"] = state_sha256(cid, root)
        ans["touched"] = _touched(before, _snapshot(root))
        return ans


def _return_reserve(cid, it, v, cfg, root, now, by, via):
    """CF-0918: a reserve video (in Studio, withdrawn) onto the nearest free slot
    inside the horizon now - through `publish_move.return_reserve` (note, pair,
    journal row); the item's slot/day/label follow where it went."""
    import publish_move                                         # noqa: PLC0415
    hz = publish_queue.horizon(cid, root, now)
    at = publish_queue.next_free(cid, root, now, None, cfg)
    if not publish_queue.within_horizon(at, hz):
        raise publish_queue.QueueError(publish_queue.beyond_line(it["slug"], at, hz, cfg))
    md = Path(root) / v["card"]["path"] if v["card"]["where"] == "publish" else \
        Path(root) / "publish" / cid / v["bucket"] / f"{it['slug']}.md"
    path, _journal = publish_move.return_reserve(cid, it["slug"], md, v["video_id"], at, cfg,
                                                 root, now, by, via, bucket=v["bucket"])
    if publish_queue.msk_day(at) != it["day"]:
        it["warnings"].append(f"planned {it['day']}, went to {publish_queue.msk_day(at)}")
    it.update(slot=_iso(at), day=publish_queue.msk_day(at), label=publish_queue.label(at, cfg))
    return path


# --------------------------------------------------------------------------
# the driver's mark of the kind
# --------------------------------------------------------------------------

def set_kind(channel, wanted, kind, by, via, root=None, now=None):
    """CF-0919: the driver's word on a disputed video: `kind` (news | evergreen)
    of one video of the pile (`slug` or `batch/slug`), a row of
    `publish/feed-kinds.json` with by / via / at, committed. The last row of a
    video wins; a namesake of another batch does not inherit it. Answer:
    `{ok, written, task, channel, slug, batch_id, kind, by, via, commit,
    refusals [{code, line}], lines}` - refusals bad_who, unknown_channel,
    bad_kind, not_in_queue."""
    root = Path(root or ROOT)
    now = publish_queue.now_utc(now)
    slug, batch = _wanted(wanted)
    ans = {"ok": False, "written": False, "task": KIND_TASK, "channel": channel, "slug": slug,
           "batch_id": batch, "kind": kind, "by": by, "via": via, "commit": None,
           "refusals": [], "lines": []}
    top = [_refusal("bad_who", why) for why in (_who(by, "by"), _who(via, "via")) if why]
    if kind not in fact_kind.KINDS:
        top.append(_refusal("bad_kind", f"{kind!r}: news or evergreen"))
    cid = _channel(channel, root)
    if cid is None:
        top.append(_refusal("unknown_channel", f"{channel!r}: no channels/<id>.json"))
    log = root / "publish" / "acceptance-log.json"
    lock = acceptance._queue_lock(log) if log.parent.is_dir() else contextlib.nullcontext()
    with lock:
        if cid is not None:
            ans["channel"] = cid
            cands = [v for v in stash(cid, root, now)["videos"] if v["slug"] == slug
                     and (batch is None or v["batch_id"] == batch)]
            if len(cands) != 1:
                top.append(_refusal("not_in_queue", _not_one_line(cid, slug, batch, cands)))
            else:
                ans["batch_id"] = cands[0]["batch_id"]
        if top:
            ans.update(refusals=top, lines=[r["line"] for r in top])
            return ans
        p = root / "publish" / KIND_JOURNAL
        doc = {"note": "CF-0919: the driver's mark of a video's kind in the копилка "
                       "(publish_stash.py kind); the last row of (channel, slug, batch_id) wins.",
               "task": KIND_TASK, "marks": []}
        if p.is_file():
            doc = json.loads(p.read_text(encoding="utf-8"))
        doc.setdefault("marks", []).append(
            {"channel": cid, "slug": slug, "batch_id": ans["batch_id"], "kind": kind,
             "by": by.strip(), "via": via.strip(),
             "at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "task": KIND_TASK})
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        ans["written"] = True
        ans["ok"] = True
        ans["lines"].append(f"{slug} ({ans['batch_id']}): {kind} ({by.strip()}, {via.strip()})")
        import publish_move                                     # noqa: PLC0415
        gc = publish_move._git_commit()
        try:
            ans["commit"], _done = gc.commit_paths(
                root, [_rel(p, root)], f"Копилка {cid}: {slug} - {kind} ({by.strip()}, "
                                       f"{via.strip()})\n\n{KIND_TASK}: вид ролика поставлен "
                                       f"руками (publish_stash.py kind).\n")
        except (gc.CommitError, OSError) as e:
            ans["lines"].append(f"written, not committed: {e}")
        return ans


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="publish_stash.py",
                                 description="the channel's pile of accepted videos (CF-0738)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "plan", "confirm"):
        p = sub.add_parser(name)
        p.add_argument("--channel", required=True)
        p.add_argument("--root", default=None)
        p.add_argument("--now", default=None)
        p.add_argument("--json", action="store_true")
        if name != "show":
            p.add_argument("slugs", nargs="*", help="slug or batch/slug, in placing order")
            p.add_argument("--auto", action="store_true",
                           help="CF-0918: the копилка's own order - fresh news first, then the "
                                "evergreen reserve, as many as the slots inside the horizon")
            p.add_argument("--force", action="store_true",
                           help="CF-0918: with --auto, a stale news video may be chosen too")
        if name == "confirm":
            p.add_argument("--base-sha256", required=True)
            p.add_argument("--by", required=True)
            p.add_argument("--via", required=True)
    p = sub.add_parser("kind", help="CF-0919: the driver's mark of a video's kind")
    p.add_argument("--channel", required=True)
    p.add_argument("video", metavar="[BATCH/]SLUG")
    p.add_argument("value", choices=fact_kind.KINDS)
    p.add_argument("--by", required=True)
    p.add_argument("--via", required=True)
    p.add_argument("--root", default=None)
    p.add_argument("--now", default=None)
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if ns.cmd == "kind":
            res = set_kind(ns.channel, ns.video, ns.value, ns.by, ns.via, ns.root, ns.now)
            print(json.dumps(res, ensure_ascii=False, indent=2) if ns.json
                  else "\n".join(res["lines"] + ([f"commit {res['commit']}"] if res["commit"]
                                                 else [])))
            return 0 if res["ok"] else 1
        if ns.cmd == "show":
            res = stash(ns.channel, ns.root, ns.now)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                for v in res["videos"]:
                    age = v["age"]
                    kind = ("ЗАПАС " + v["video_id"] if v["reserve"] else "") + (
                        f" новость до {v['stale_at']}" if v["feed_kind"] == "news"
                        else " бессрочный")
                    print(f"{v['slug']:<28} {v['kind'] or '?':<7} {v['batch_id']}{kind} "
                          f"принят {v['accepted_at']} ({age['accepted_days']} дн.)"
                          + (f", новость {age['news_days']} дн." if age["news_days"] is not None
                             else "")
                          + (" УСТАРЕЛ" if age["stale"] else " возраст неизвестен"
                             if age["stale"] is None else "")
                          + f" карточка: {CARD_WORDS.get(v['card']['state'], v['card']['state'])}"
                          + (f" ({', '.join(v['card']['reasons'])})" if v['card']['reasons']
                             and v['card']['state'] == 'not_ready' else "")
                          + (f" журнал {v['card']['build']['log']}" if v['card']['build']
                             else ""))
                for v in res["not_queued"]:
                    print(f"НЕ В КОПИЛКЕ {v['entry_id']}: {v['queue_text_ru']} - {v['repair']}")
                for v in res["other_version"]:
                    print(f"ВЕРСИЯ ИЛИ НОВЫЙ? {v['entry_id']}: размещён {v['other_entry']} "
                          f"({v['other_path']}; {v['other_why']}) - новый ролик: {v['repair']}")
                print(f"{res['count']} в копилке {res['channel']} (новостей {res['news']}, "
                      f"в запасе с video_id {res['reserve']}), устаревших {res['stale']}; "
                      f"{res['staleness']['note']}; горизонт {res['horizon']['days']} дн. "
                      f"(до {res['horizon']['last_day']})")
            return 0
        if not ns.slugs and not ns.auto:
            ap.error("name the slugs to place, or --auto")
        if ns.cmd == "plan":
            res = place_plan(ns.channel, ns.slugs, ns.root, ns.now, auto=ns.auto,
                             force=ns.force)
        else:
            res = place_confirm(ns.channel, ns.slugs, ns.base_sha256, ns.by, ns.via, ns.root,
                                ns.now, auto=ns.auto, force=ns.force)
        if ns.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("\n".join(res["lines"]))
            print(f"base_sha256 {res['sha256']}")
        return 0 if res["ok"] else 1
    except publish_queue.QueueError as e:
        sys.stderr.write(f"publish_stash: error: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
