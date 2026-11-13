#!/usr/bin/env python3
"""CF-0108: subscription-window percentages as `kind: limits` events, and "which run is active".

Claude Code hands its statusline command a JSON on stdin with

    rate_limits.five_hour.{used_percentage, resets_at}
    rate_limits.seven_day.{used_percentage, resets_at}

statusline_hook.py (the drop-in statusline command, see there) forwards that
JSON to record() for the active batch, so the events of a run carry the
window percentages at every statusline refresh; CF-0110 turns the readings at
the stage boundaries into "this stage cost N % of the 5-hour window".

Verdict of the task's item 1 (2026-09-07): the statusline command is invoked
only in *terminal* sessions - the desktop app / auto-dev sessions that drive
the runs never call it (~/.claude/rate_limits.json, rewritten on every call,
had not moved for two days of desktop runs). Hence the fallback:
from_rate_limits_file() reads that file and marks how stale it is
(`stale_s`), and the limit *events* come from limit_hook.py or, after the
fact, from the marker line in the session transcript (gaps.py).

Event: kind=limits, stage=null, params:

    five_hour   {used_percentage, resets_at} - null when the payload carried no
                such block (it happens: 3 of the 280 readings of run 2026-09-09
                have no five_hour, and so does ~/.claude/rate_limits.json at times).
                The event is written anyway for the window that *is* there, and
                summary.window_share() counts the missing ones per window (CF-0175).
    seven_day   {used_percentage, resets_at} - same
    source      "statusline" | "rate_limits.json" | <caller's tag>
    stale_s     age of the reading in seconds (rate_limits.json only; 0 for live)
    session_id  when the statusline JSON carried one

active_batch(): RUNLOG_BATCH env -> newest live RUN_SAMPLER.pid under
<root>/pipeline/*/*/ -> <state dir>/active-batch written by batch-start.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["KIND_LIMITS", "WINDOWS", "RATE_LIMITS_FILE", "normalize", "offers_windows",
           "record", "active_batch", "from_rate_limits_file", "record_from_file"]

KIND_LIMITS = "limits"
WINDOWS = ("five_hour", "seven_day")
RATE_LIMITS_FILE = "~/.claude/rate_limits.json"


def _window(d):
    if not isinstance(d, dict):
        return None
    out = {"used_percentage": d.get("used_percentage"), "resets_at": d.get("resets_at")}
    up = out["used_percentage"]
    if isinstance(up, str):
        try:
            up = out["used_percentage"] = float(up.rstrip("%"))
        except ValueError:
            pass
    if isinstance(up, float):
        # CF-0175 item 3: the percentage is *computed upstream* (Claude Code divides
        # used by the limit in floating point) and arrives with the division's tail -
        # `7.000000000000001`, `14.000000000000002`. Nothing here multiplies or
        # divides it; the readings sit on a whole-percent grid. So drop the foreign
        # tail at the door instead of carrying it into every report.
        out["used_percentage"] = round(up, 3)
    return out


def _rate_limits(payload):
    """The rate_limits dict inside a statusline payload, or the payload itself when
    it already is one. None when the payload is not a dict at all."""
    if not isinstance(payload, dict):
        return None
    rl = payload.get("rate_limits") if "rate_limits" in payload else payload
    return rl if isinstance(rl, dict) else None


def offers_windows(payload):
    """True when the payload actually offered a window block - i.e. an unusable
    reading is a *loss* worth naming (CF-0175 item 1) and not simply a statusline
    JSON that carries no rate limits at all."""
    rl = _rate_limits(payload)
    return bool(rl) and any(w in rl for w in WINDOWS)


def normalize(payload):
    """{five_hour, seven_day} from either the full statusline JSON (with a
    `rate_limits` key) or a bare rate_limits dict. None when nothing usable.

    A window the payload does not carry stays `None` in the result - the event is
    still written, and `summary.window_share()` counts those per window rather
    than dropping them quietly (CF-0175 item 1)."""
    rl = _rate_limits(payload)
    if rl is None:
        return None
    out = {w: _window(rl.get(w)) for w in WINDOWS}
    if all(v is None for v in out.values()):
        return None
    return out


def record(batch_dir, payload, source="statusline", stale_s=0, session_id=None):
    """Append one `kind: limits` event to the batch. Returns the event or None."""
    try:
        norm = normalize(payload)
        if norm is None:
            # CF-0175 item 1, by the `probe_errors` rule of CF-0167: a refusal must
            # not look like a measurement. A payload that offered `rate_limits` and
            # still yielded no usable window is a lost reading - say so. A payload
            # that offered nothing (statusline JSON without rate limits at all) is
            # not a loss and stays silent, or every statusline refresh would warn.
            if offers_windows(payload):
                runlog._warn("limits reading dropped: `rate_limits` carries no usable "
                             f"{' / '.join(WINDOWS)} block")
            return None
        params = dict(norm)
        params["source"] = source
        params["stale_s"] = round(float(stale_s), 1) if stale_s is not None else None
        sid = session_id or (payload.get("session_id") if isinstance(payload, dict) else None)
        if sid:
            params["session_id"] = sid
        return runlog.emit(batch_dir, KIND_LIMITS, None, params=params)
    except Exception as e:                        # accounting never breaks a run
        runlog._warn(f"limits not recorded ({e.__class__.__name__}: {e})")
        return None


def _sampler():
    return runlog.sibling("sampler")


def _live_pidfile_batches(root):
    """Batches under <root>/pipeline/*/*/ with a live sampler, newest pid-file first."""
    hits = []
    try:
        for pf in Path(root).glob("pipeline/*/*/" + _sampler().PID_FILE):
            try:
                pid = int(pf.read_text().strip().split()[0])
            except (OSError, ValueError, IndexError):
                continue
            if _sampler().pid_alive(pid):
                hits.append((pf.stat().st_mtime, pf.parent))
    except OSError:
        pass
    return [b for _, b in sorted(hits, reverse=True)]


def active_batch(root=None):
    """The batch a user-level hook should write to, or None.

    1. RUNLOG_BATCH in the environment (a hook started under an instrumented run);
    2. the newest live RUN_SAMPLER.pid under <root>/pipeline/<channel>/<batch>/;
    3. <state dir>/active-batch, written by batch-start and removed by batch-done,
       if that directory still exists and has no batch-done marker.
    """
    env = os.environ.get(runlog.BATCH_ENV)
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    try:
        root = Path(root) if root else runlog.factory_root()
    except Exception:
        root = None
    if root:
        live = _live_pidfile_batches(root)
        if live:
            return live[0].resolve()
    try:
        state = runlog.active_batch_file()
        if state.is_file():
            p = Path(state.read_text().strip())
            if p.is_dir():
                done = any(e.get("kind") == runlog.KIND_MARKER
                           and e.get("status") == runlog.M_BATCH_DONE
                           for e in runlog.read_events(p))
                if not done:
                    return p.resolve()
    except Exception:
        pass
    return None


def from_rate_limits_file(path=None, now=None):
    """The fallback reading: ~/.claude/rate_limits.json as written by the user's
    statusline.py ({"ts": epoch, "rate_limits": {...}}). Returns
    {five_hour, seven_day, stale_s, source} or None when unreadable."""
    p = Path(path or os.environ.get("RUNLOG_RATE_LIMITS_FILE") or RATE_LIMITS_FILE).expanduser()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    norm = normalize(data)
    if norm is None:
        return None
    ts = data.get("ts") if isinstance(data, dict) else None
    try:
        ts = float(ts) if ts is not None else p.stat().st_mtime
    except (TypeError, ValueError, OSError):
        ts = None
    stale = round(max(0.0, (now or time.time()) - ts), 1) if ts is not None else None
    norm["stale_s"] = stale
    norm["source"] = "rate_limits.json"
    return norm


SOURCE_KEY = "limits_source"      # CF-0230: the batch-start field
SOURCE_FRESH_S = 600.0            # CF-0230: older than this, the file says nothing about the run


def source_state(path=None, now=None):
    """CF-0230: what the fallback source looks like right now - a diagnosis, never
    a reading. Written once into `batch-start` (SOURCE_KEY) so that section 5 of
    the summary can say *why* a run has no `limits` readings from the state the
    source was in when the run began, not from whatever the file holds when the
    summary happens to be rendered.

        {"file", "exists", "age_s", "block", "windows", "fresh"}

    `block` is False when the file holds `"rate_limits": null` (the user's
    statusline.py rewrites the file on every redraw, also when Claude Code sent
    no block); `windows` lists the windows that carry a percentage; `fresh` is
    age_s <= SOURCE_FRESH_S. Never raises."""
    p = Path(path or os.environ.get("RUNLOG_RATE_LIMITS_FILE") or RATE_LIMITS_FILE).expanduser()
    out = {"file": str(p), "exists": False, "age_s": None, "block": False,
           "windows": [], "fresh": False}
    try:
        st = p.stat()
    except OSError:
        return out
    out["exists"] = True
    data = None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        pass
    ts = data.get("ts") if isinstance(data, dict) else None
    try:
        ts = float(ts) if ts is not None else st.st_mtime
    except (TypeError, ValueError):
        ts = st.st_mtime
    out["age_s"] = round(max(0.0, (now or time.time()) - ts), 1)
    out["fresh"] = out["age_s"] <= SOURCE_FRESH_S
    out["block"] = _rate_limits(data) is not None if data is not None else False
    norm = normalize(data) if data is not None else None
    out["windows"] = [w for w in WINDOWS if norm and norm.get(w) is not None]
    return out


def source_problem(state):
    """CF-0230: one line naming why the source will give this run no usable
    reading, or None when it would (fresh, with a five_hour window)."""
    if not state:
        return None
    if not state.get("exists"):
        return f"{state.get('file')} does not exist"
    bits = []
    if not state.get("fresh"):
        bits.append(f"last written {round((state.get('age_s') or 0) / 60)} min ago")
    if not state.get("block"):
        bits.append("holds no rate_limits block")
    elif "five_hour" not in (state.get("windows") or []):
        bits.append("has no five_hour window (only " + (", ".join(state.get("windows") or []) or "nothing") + ")")
    if not bits:
        return None
    return "~/.claude/rate_limits.json " + ", ".join(bits)


def record_from_file(batch_dir, path=None, max_stale_s=None):
    """record() the rate_limits.json reading into the batch; None when the file
    is unreadable or older than max_stale_s (when given)."""
    r = from_rate_limits_file(path)
    if r is None:
        return None
    if max_stale_s is not None and (r["stale_s"] is None or r["stale_s"] > max_stale_s):
        return None
    return record(batch_dir, r, source=r["source"], stale_s=r["stale_s"])


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="limits")
    ap.add_argument("--batch", default=None, help="default: the active batch")
    ap.add_argument("--from-file", nargs="?", const=RATE_LIMITS_FILE, metavar="PATH",
                    help="record the rate_limits.json reading (default ~/.claude/rate_limits.json)")
    ap.add_argument("--active", action="store_true", help="print the active batch and exit")
    ns = ap.parse_args(argv)
    if ns.active:
        b = active_batch()
        print(b or "")
        return 0 if b else 1
    b = Path(ns.batch).expanduser() if ns.batch else active_batch()
    if b is None:
        sys.stderr.write("limits: no active batch\n")
        return 1
    if ns.from_file:
        ev = record_from_file(b, ns.from_file)
    else:
        try:
            ev = record(b, json.load(sys.stdin))
        except ValueError:
            ev = None
    print(json.dumps(ev, ensure_ascii=False) if ev else "")
    return 0 if ev else 1


if __name__ == "__main__":
    sys.exit(main())
