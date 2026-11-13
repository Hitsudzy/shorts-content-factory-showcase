#!/usr/bin/env python3
"""CF-0569: a channel's "publications are paused" flag - the one writer and
reader of `publish/channel-pauses.json`.

The flag is set by the operator on the user's word; the Publisher only obeys
it.

Where the flag lives, and why there: `publish/channel-pauses.json`, next to
the other publication-state registries (`acceptance-log.json`,
`publication-holds.json`, `uploads.json`). It is state, not a setting - so not
`channels/<channel>.json` (the channel's configuration, edited by hand and
reviewed as such); and not `publish/<channel>/` (that folder is the queue's
picture on disk: day folders that `publish_layout` enumerates and the month
archive moves away - CF-0475/CF-0476). One file holds every channel, so the
history of all pauses is one read.

    {"pauses": [
      {"pause_id": "example-film/2026-10-06T12:00:00Z",
       "channel": "example-film",
       "by": "user",                   # who set it: user | operator | ...
       "reason": "on the user's word",
       "set_at": "2026-10-06T12:00:00Z",
       "until": "2026-10-20T00:00:00+03:00",   # null = until cleared
       "cleared_at": null, "cleared_by": null, "clear_note": null}
    ]}

A row is never deleted: clearing fills `cleared_at`/`cleared_by`/`clear_note`
and the row stays as history. A channel has at most one open (uncleared) row.

State of a channel at `now`:

* `paused` - an open row whose `until` is null or still ahead: nothing of the
  channel is placed in a slot (`publish_queue.PAUSE_CHECKS`), uploaded
  (`upload_gate.check_channel_not_paused`, CF-0421/CF-0585), or scheduled in
  Studio (CF-0018 calls the same function before filling the schedule);
* `expired` - an open row whose `until` has passed: it does not hold, but
  every check says so (a notice) until someone clears the record;
* `free` - no open row.

A registry that does not parse pauses every channel (fail closed), like the
publication holds; a missing registry pauses nothing.

`--until` takes an ISO time with a zone, or a date `YYYY-MM-DD`, which means
"publications resume on that Moscow day" (00:00 Europe/Moscow).

    python3 agents/publisher/channel_pause.py set --channel C --by user --reason "..." [--until DATE|ISO] [--replace]
    python3 agents/publisher/channel_pause.py clear --channel C --by user [--note "..."]
    python3 agents/publisher/channel_pause.py show [--channel C] [--history]
        # every command takes [--root DIR] [--now ISO]; `show` exits 3 when a
        # shown channel is paused, 0 otherwise, 2 on an error
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent

TASK = "CF-0569"
REGISTRY = "channel-pauses.json"
MSK = "Europe/Moscow"
BY = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
KNOWN_BY = ("user", "operator")
PAUSED, EXPIRED, FREE = "paused", "expired", "free"
EXIT_OK, EXIT_ERROR, EXIT_PAUSED = 0, 2, 3


class PauseError(Exception):
    pass


# ------------------------------------------------------------------ helpers
def _channel_ids():
    spec = importlib.util.spec_from_file_location("channel_ids_channel_pause",
                                                  ROOT / "shared" / "channel_ids.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def resolve(channel, root=None):
    """The channel's current id (a former id is followed, CF channel_ids)."""
    if not channel:
        raise PauseError("no channel named")
    return _channel_ids().resolve_channel(str(channel), Path(root or ROOT))


def registry_path(root=None):
    return Path(root or ROOT) / "publish" / REGISTRY


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc(now=None):
    """`now` as an aware datetime: None is the clock, a string is ISO with a zone."""
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise PauseError(f"{now!r} has no zone")
        return now
    return _parse_time(now, "--now")


def _parse_time(text, what):
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise PauseError(f"{what} {text!r} is not an ISO time") from e
    if dt.tzinfo is None:
        raise PauseError(f"{what} {text!r} has no zone - name it (2026-10-20T00:00+03:00 or ...Z)")
    return dt


def parse_until(text):
    """`--until`: a date is 00:00 Moscow of that day (publications resume that
    day); otherwise an ISO time with a zone. None/"" = until cleared."""
    if text is None or str(text).strip() == "":
        return None
    s = str(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        if ZoneInfo is None:                                    # pragma: no cover
            raise PauseError("zoneinfo is unavailable (Python < 3.9)")
        try:
            d = date.fromisoformat(s)
        except ValueError as e:
            raise PauseError(f"--until {s!r} is not a date") from e
        return datetime.combine(d, time(0, 0), tzinfo=ZoneInfo(MSK))
    return _parse_time(s, "--until")


def _until_of(row):
    u = row.get("until")
    return None if not u else _parse_time(u, f"{row.get('pause_id')}: until")


def _msk(dt):
    if ZoneInfo is None:                                        # pragma: no cover
        return _iso(dt)
    return f"{dt.astimezone(ZoneInfo(MSK)):%Y-%m-%d %H:%M} МСК"


# ------------------------------------------------------------------ the registry
def read(root=None):
    """Every row of the registry, in order. Missing file: []. A file that does
    not parse, or a row without its fields, is a PauseError (callers that gate
    turn it into a pause - fail closed)."""
    p = registry_path(root)
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PauseError(f"publish/{REGISTRY} does not parse ({e})") from e
    rows = doc.get("pauses") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise PauseError(f"publish/{REGISTRY} has no `pauses` list")
    for r in rows:
        missing = [k for k in ("pause_id", "channel", "by", "reason", "set_at")
                   if not isinstance(r, dict) or not r.get(k)]
        if missing:
            raise PauseError(f"publish/{REGISTRY}: a row lacks {', '.join(missing)}: {r!r}")
        _until_of(r)
    return rows


def _write(rows, root=None):
    p = registry_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"pauses": rows}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, p)


def history(channel, root=None):
    """Every row of `channel`, oldest first (cleared ones included)."""
    ch = resolve(channel, root)
    return [r for r in read(root) if resolve(r["channel"], root) == ch]


def open_row(channel, root=None):
    """The channel's uncleared row, or None."""
    rows = [r for r in history(channel, root) if not r.get("cleared_at")]
    return rows[-1] if rows else None


def describe(row):
    until = _until_of(row)
    return (f"{row['by']}: {row['reason']} (с {row['set_at']}, "
            + (f"до {_msk(until)}" if until else "бессрочно - до снятия") + ")")


def status(channel, root=None, now=None):
    """`{"state": paused|expired|free, "row", "line"}` for `channel` at `now`."""
    now = now_utc(now)
    ch = resolve(channel, root)
    row = open_row(ch, root)
    if row is None:
        return {"state": FREE, "row": None, "line": f"{ch}: публикации идут (паузы нет)"}
    until = _until_of(row)
    if until is not None and until <= now:
        return {"state": EXPIRED, "row": row,
                "line": (f"{ch}: пауза ИСТЕКЛА {_msk(until)} и не держит - {describe(row)}; "
                         f"закрыть запись: channel_pause.py clear --channel {ch} --by <кто> ({TASK})")}
    return {"state": PAUSED, "row": row,
            "line": f"{ch}: публикации НА ПАУЗЕ - {describe(row)} ({TASK})"}


def set_pause(channel, by, reason, until=None, root=None, now=None, replace=False):
    """Pause `channel`. Refused when an open row stands (an expired one too -
    clear it or pass `replace`, which clears it with a note)."""
    now = now_utc(now)
    ch = resolve(channel, root)
    if not (Path(root or ROOT) / "channels" / f"{ch}.json").is_file():
        raise PauseError(f"channel {ch!r} has no channels/{ch}.json - a typo? nothing paused")
    if not by or not BY.match(str(by)):
        raise PauseError(f"--by {by!r}: who sets it, a word like {', '.join(KNOWN_BY)}")
    if not reason or not str(reason).strip():
        raise PauseError("--reason is empty - a pause says why")
    until_dt = parse_until(until) if not isinstance(until, datetime) else until
    if until_dt is not None and until_dt <= now:
        raise PauseError(f"--until {_msk(until_dt)} is already past - nothing to pause")
    rows = read(root)
    stands = [r for r in rows if resolve(r["channel"], root) == ch and not r.get("cleared_at")]
    if stands and not replace:
        raise PauseError(f"{ch} already has a pause: {describe(stands[-1])} - clear it first "
                         f"or pass --replace")
    for r in stands:
        r.update(cleared_at=_iso(now), cleared_by=str(by),
                 clear_note=f"заменена новой паузой ({by}: {str(reason).strip()})")
    row = {"pause_id": f"{ch}/{_iso(now)}", "channel": ch, "by": str(by),
           "reason": str(reason).strip(), "set_at": _iso(now),
           "until": until_dt.isoformat() if until_dt else None,
           "cleared_at": None, "cleared_by": None, "clear_note": None}
    if any(r["pause_id"] == row["pause_id"] for r in rows):
        raise PauseError(f"{row['pause_id']} already exists - one pause per channel per second")
    rows.append(row)
    _write(rows, root)
    return row


def clear_pause(channel, by, note=None, root=None, now=None):
    """Lift the channel's open pause (expired or not); the row stays, with
    who cleared it and when."""
    now = now_utc(now)
    ch = resolve(channel, root)
    if not by or not BY.match(str(by)):
        raise PauseError(f"--by {by!r}: who clears it, a word like {', '.join(KNOWN_BY)}")
    rows = read(root)
    stands = [r for r in rows if resolve(r["channel"], root) == ch and not r.get("cleared_at")]
    if not stands:
        raise PauseError(f"{ch} has no pause to clear")
    for r in stands:
        r.update(cleared_at=_iso(now), cleared_by=str(by),
                 clear_note=(str(note).strip() if note and str(note).strip() else None))
    _write(rows, root)
    return stands[-1]


# ------------------------------------------------------------------ for the gates
def gate(channel, root=None, now=None):
    """`(reason, notice)` for a gate: `reason` (a string) when the channel is
    paused - also when the registry cannot be read (fail closed); `notice`
    when an expired pause is still on record. Both None when free."""
    try:
        st = status(channel, root, now)
    except PauseError as e:
        return (f"{TASK}: реестр пауз нечитаем ({e}) - пауза для всех каналов, пока не "
                f"починят publish/{REGISTRY}"), None
    if st["state"] == PAUSED:
        return st["line"], None
    if st["state"] == EXPIRED:
        return None, st["line"]
    return None, None


def queue_check(channel, root=None, now=None):
    """For `publish_queue.PAUSE_CHECKS`: None, a reason (paused), or
    `{"notice": ...}` (an expired pause that does not hold)."""
    reason, notice = gate(channel, root, now)
    if reason:
        return reason
    return {"notice": notice} if notice else None


# ------------------------------------------------------------------ the command
def _channels(root):
    try:
        names = sorted({resolve(r["channel"], root) for r in read(root)})
    except PauseError:
        names = []
    return names


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("set", "clear", "show"):
        p = sub.add_parser(name)
        p.add_argument("--channel", required=name != "show")
        p.add_argument("--root")
        p.add_argument("--now")
        if name in ("set", "clear"):
            p.add_argument("--by", required=True,
                           help=f"who: {', '.join(KNOWN_BY)} (the operator on the user's word: user)")
        if name == "set":
            p.add_argument("--reason", required=True)
            p.add_argument("--until", help="YYYY-MM-DD (resume that Moscow day) or ISO with zone; "
                                           "absent = until cleared")
            p.add_argument("--replace", action="store_true")
        if name == "clear":
            p.add_argument("--note")
        if name == "show":
            p.add_argument("--history", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "set":
            row = set_pause(args.channel, args.by, args.reason, args.until, args.root, args.now,
                            replace=args.replace)
            print(f"ok   {row['channel']}: публикации на паузе - {describe(row)}", file=out)
            print(f"     publish/{REGISTRY} -> {row['pause_id']}", file=out)
            return EXIT_OK
        if args.cmd == "clear":
            row = clear_pause(args.channel, args.by, args.note, args.root, args.now)
            print(f"ok   {row['channel']}: пауза снята ({row['cleared_by']}, {row['cleared_at']}); "
                  f"была - {describe(row)}", file=out)
            return EXIT_OK
        names = [resolve(args.channel, args.root)] if args.channel else _channels(args.root)
        read(args.root)                                         # an unreadable registry is an error here
        if not names:
            print("ни один канал не на паузе (реестр пуст)", file=out)
            return EXIT_OK
        code = EXIT_OK
        for ch in names:
            st = status(ch, args.root, args.now)
            print(st["line"], file=out)
            if st["state"] == PAUSED:
                code = EXIT_PAUSED
            if args.history:
                for r in history(ch, args.root):
                    tail = (f" -> снята {r['cleared_at']} ({r['cleared_by']}"
                            + (f": {r['clear_note']}" if r.get("clear_note") else "") + ")"
                            if r.get("cleared_at") else " -> открыта")
                    print(f"  {r['pause_id']}  {describe(r)}{tail}", file=out)
        return code
    except PauseError as e:
        print(f"CHANNEL PAUSE: {e}", file=out)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
