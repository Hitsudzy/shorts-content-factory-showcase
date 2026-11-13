#!/usr/bin/env python3
"""CF-0607: the per-channel switch of the API upload (`upload.py`).

The code of the API upload (CF-0421) ships in 2.2; the upload itself waits for
the YouTube API Services Audit (CF-0470, `docs/api-audit/README.md`) - until it
is passed, everything `videos.insert` puts up stays private for good. So the
API path is behind a switch, **off by default for every channel**, and the user
turns it on after the audit - no release needed. The Studio path (CF-0018,
`studio_fields.py`) does not look at the switch: it works in either position
and stays the fallback.

    python3 agents/publisher/api_switch.py status [--channel <канал>]
    python3 agents/publisher/api_switch.py enable <канал> --by user --note "где и когда сказал"
    python3 agents/publisher/api_switch.py disable <канал> --by <кто> [--note "…"]

**Where it lives.** `schedule/api-upload.json` - the console's state directory
(gitignored, the same one as the batch schedule's `switch.json` and the
overlay `channel-settings.json`, CF-0592/CF-0605; `BATCH_SCHEDULE_STATE_DIR`
moves it), never `channels/*.json`. `set_switch` is its only writer: validated,
under a lock, written atomically, and every change is a row of its history
(who, when, the note, the warnings said at the time).

**Who.** `enable` takes `--by user` only and a `--note` (where and when the
user said so) - the switch is the user's decision; `disable` takes anyone.

**Warnings, not refusals.** Turning it on says, and writes into the history,
what is not ready yet: the OAuth app still in Testing (`PUBLISHER_OAUTH_MODE`,
CF-0607 - its uploads stay private and its token lives 7 days), the tick's
launchd timer not installed (the deletion of API Data by its term, CF-0618,
runs in the tick - gap 7 of `docs/api-audit/README.md`), the token expired, about
to expire, missing a scope or absent. None of them blocks: it is the user's call.

**The gate.** `upload.py` calls `check(channel)` before anything reaches
Google; off - one line, `refusal_line(channel)`, and nothing is uploaded.

Exit codes: 0 - done / status printed; 1 - refused (with the reason); 2 - bad arguments.
"""
import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))
if str(ROOT / "shared") not in sys.path:
    sys.path.append(str(ROOT / "shared"))

TASK = "CF-0607"
STATE_FILE = "api-upload.json"
LOCK_FILE = "api-upload.lock"
ENABLE_BY = ("user",)
BY_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
AUDIT_DOC = "docs/api-audit/README.md"


class SwitchError(Exception):
    pass


def _bs():
    import batch_schedule                                       # noqa: PLC0415
    return batch_schedule


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def state_path(root=None, environ=None):
    return _bs().state_dir(root or ROOT, environ) / STATE_FILE


def channels(root=None):
    d = Path(root or ROOT) / "channels"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def resolve(channel, root=None):
    """The channel under its current id (a former id of a record, CF-0250)."""
    try:
        return _bs().collect().resolve_channel(channel, root or ROOT)
    except Exception:                                           # noqa: BLE001
        return channel


def no_pipeline(channel, root=None):
    """CF-0562: «конвейера нет - батча не будет (...)» for a channel whose
    config says `status: no_pipeline`, None otherwise (and when the config does
    not read - the switch's own lines say that case)."""
    try:
        return _bs().collect().no_pipeline(channel, root or ROOT)
    except Exception:                                           # noqa: BLE001
        return None


def refusal_line(channel):
    return (f"API-загрузка для {channel} выключена: ждёт аудита YouTube API (CF-0470, "
            f"{AUDIT_DOC}); публикация — через Studio")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def read(root=None, environ=None):
    """`{"channels": {ch: {on, at, by, note}}, "history": [...], "path"}`;
    `error` when the file does not parse (then every channel reads as off)."""
    p = state_path(root, environ)
    out = {"channels": {}, "history": [], "path": str(p)}
    if not p.is_file():
        return out
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as e:
        return dict(out, error=str(e))
    chans = doc.get("channels") if isinstance(doc.get("channels"), dict) else {}
    out["channels"] = {k: v for k, v in chans.items() if isinstance(v, dict)}
    out["history"] = [h for h in doc.get("history") or [] if isinstance(h, dict)]
    return out


def channel_state(channel, root=None, environ=None, doc=None):
    """`{channel, on, at, by, note, warnings, line, history}` - off when never set."""
    doc = read(root, environ) if doc is None else doc
    ch = resolve(channel, root)
    hist = [h for h in doc["history"] if resolve(h.get("channel"), root) == ch]
    if doc.get("error"):
        return {"channel": ch, "on": False, "history": hist, "error": doc["error"],
                "line": f"API-загрузка {ch}: {Path(doc['path']).name} не читается "
                        f"({doc['error']}) - считаю ВЫКЛЮЧЕННОЙ"}
    cur = doc["channels"].get(ch) or {}
    on = cur.get("on") is True
    last = hist[-1] if hist else {}
    who = (f"{last.get('by')} {last.get('at')}" + (f" - {last['note']}" if last.get("note") else "")
           if last else "не включалась")
    stub = no_pipeline(ch, root)
    line = (f"API-загрузка {ch} ВКЛЮЧЕНА ({who}): upload.py грузит после «да» в терминале; "
            f"Studio-путь - запасной" if on else
            f"API-загрузка {ch} ВЫКЛЮЧЕНА ({who}): {stub} - грузить нечего" if stub else
            f"API-загрузка {ch} ВЫКЛЮЧЕНА ({who}): ждёт аудита YouTube API (CF-0470); "
            f"публикация - через Studio")
    return {"channel": ch, "on": on, "at": cur.get("at"), "by": cur.get("by"),
            "note": cur.get("note"), "warnings": list(last.get("warnings") or []),
            "history": hist, "line": line}


def is_on(channel, root=None, environ=None):
    return channel_state(channel, root, environ)["on"]


def check(channel, root=None, environ=None):
    """The gate of `upload.py`: SwitchError(`refusal_line`) unless the switch
    of `channel` is on. Reads one local file; nothing else."""
    if not channel:
        raise SwitchError("no channel to check the API switch of - nothing is uploaded")
    st = channel_state(channel, root, environ)
    if not st["on"]:
        raise SwitchError(refusal_line(st["channel"]))
    return st


# --------------------------------------------------------------------------
# what is not ready - said on enable, never a refusal
# --------------------------------------------------------------------------

def warnings(channel, root=None, env_file=None, environ=None, now=None, timer=None):
    """The list of lines: OAuth app in Testing, the tick's timer missing, the
    token not usable (expired / soon / no scope / none). `timer` stands in for
    `batch_schedule.timer_state()` (tests)."""
    import publisher_auth                                       # noqa: PLC0415
    import publisher_config                                     # noqa: PLC0415
    out = []
    try:
        cfg = publisher_config.load(env_file, environ)
    except publisher_config.ConfigError as e:
        cfg = None
        out.append(f"конфигурация публикатора не читается ({e}) - режим приложения и токен "
                   f"не проверены")
    if cfg is not None and cfg.oauth_mode != "production":
        out.append("OAuth-приложение в режиме Testing (PUBLISHER_OAUTH_MODE=testing): пока аудит "
                   "YouTube API не пройден и приложение не в Production, всё загруженное через "
                   "API остаётся private, а токен живёт 7 дней - шаги 9-10 и «После одобрения» "
                   f"в {AUDIT_DOC}")
    t = timer if timer is not None else _bs().timer_state()
    if not t.get("installed"):
        out.append(f"{t.get('line') or 'таймер тика не установлен'} - пробел 7 в {AUDIT_DOC}: "
                   f"срок удаления API Data после отзыва (CF-0618) держится тиком")
    if cfg is not None:
        st = publisher_auth.status(cfg, now)
        if st.kind != publisher_auth.OK:
            out.append(f"токен: {st.line}")
    return out


# --------------------------------------------------------------------------
# the one writer
# --------------------------------------------------------------------------

@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / LOCK_FILE, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_atomic(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def set_switch(channel, on, by, note=None, root=None, now=None, environ=None, env_file=None,
               timer=None):
    """The only writer of `schedule/api-upload.json`. `on=True` takes `by` in
    ENABLE_BY and a note. Returns `{"changed", "state", "warnings"}` - the
    warnings are computed on enable (and written into its history row)."""
    root = Path(root or ROOT)
    by = str(by or "").strip()
    note = (note or "").strip() or None
    if not BY_RE.match(by):
        raise SwitchError(f"--by {by!r}: a short lower-case name (user, operator, ...)")
    if on and by not in ENABLE_BY:
        raise SwitchError(f"only the user turns the API upload on (--by {' | '.join(ENABLE_BY)}); "
                          f"{by!r} may only turn it off")
    if on and not note:
        raise SwitchError("--note is required to turn it on: where and when the user said so "
                          "(after the audit, CF-0470)")
    ch = resolve(channel, root)
    if ch not in channels(root):
        raise SwitchError(f"канала {channel!r} нет в channels/")
    stub = no_pipeline(ch, root)
    if on and stub:
        raise SwitchError(f"{ch}: {stub} - API-загрузке нечего грузить (CF-0562)")
    warn = warnings(ch, root, env_file, environ, now, timer) if on else []
    p = state_path(root, environ)
    with _locked(p.parent):
        doc = read(root, environ)
        if doc.get("error"):
            raise SwitchError(f"{p} does not parse ({doc['error']}) - fix or remove it by hand")
        was = (doc["channels"].get(ch) or {}).get("on") is True
        at = _iso(_now(now))
        row = {"at": at, "by": by, "channel": ch, "action": "enable" if on else "disable",
               "note": note, "task": TASK}
        if on:
            row["warnings"] = warn
        chans = dict(doc["channels"])
        chans[ch] = {"on": bool(on), "at": at, "by": by, "note": note}
        _write_atomic(p, {"channels": chans, "history": doc["history"] + [row]})
    return {"changed": was != bool(on), "state": channel_state(ch, root, environ),
            "warnings": warn}


def status(root=None, environ=None, channel=None):
    """One state per channel of channels/ (or the one asked)."""
    doc = read(root, environ)
    names = [resolve(channel, root)] if channel else channels(root)
    return [channel_state(c, root, environ, doc) for c in names]


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="CF-0607: the per-channel switch of the API upload",
                                 allow_abbrev=False)
    ap.add_argument("--root", help="the factory root (default this checkout)")
    ap.add_argument("--env", help="the Publisher's .env (default agents/publisher/.env)")
    ap.add_argument("--now", help="ISO time with a zone (tests)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="the switch of every channel")
    st.add_argument("--channel")
    for name in ("enable", "disable"):
        s = sub.add_parser(name)
        s.add_argument("channel")
        s.add_argument("--by", required=True, help="enable: user only")
        s.add_argument("--note", help="enable: required - where and when the user said so")
    return ap


def main(argv=None, out=sys.stdout, timer=None):
    args = build_parser().parse_args(argv)
    root = Path(args.root) if args.root else ROOT
    try:
        if args.cmd == "status":
            for st in status(root, channel=args.channel):
                print(st["line"], file=out)
                for w in st["warnings"] if st["on"] else []:
                    print(f"     при включении: {w}", file=out)
            return 0
        got = set_switch(args.channel, args.cmd == "enable", args.by, args.note, root,
                         args.now, env_file=args.env, timer=timer)
    except SwitchError as e:
        print(f"REFUSED: {e}", file=out)
        return 1
    for w in got["warnings"]:
        print(f"WARNING {w}", file=out)
    print(got["state"]["line"] + ("" if got["changed"] else " (уже было так)"), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
