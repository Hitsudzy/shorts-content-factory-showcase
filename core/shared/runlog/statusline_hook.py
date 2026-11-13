#!/usr/bin/env python3
"""CF-0108: drop-in statusline command that records the window percentages into the active run.

Install (scripts/install_accounting_hooks.py does it):

    "statusLine": {"type": "command",
                   "command": "python3 <root>/shared/runlog/statusline_hook.py"}

What it does on every call:

1. reads the statusline JSON from stdin;
2. **delegates to the user's own ~/.claude/statusline.py unchanged** - runs it
   with the same stdin and passes its stdout/exit code through (that script
   keeps writing ~/.claude/rate_limits.json and printing the status text). With
   no such script it prints a minimal "<model> · 5h N% · 7d N%" line itself;
   RUNLOG_STATUSLINE_DELEGATE overrides the delegate path ("" disables it);
3. if a run is active (limits.active_batch()), appends a `kind: limits` event
   to it. With no active run it writes nothing anywhere and prints nothing
   beyond the delegate's output;
4. CF-0247: appends `repo_sync.segment()` - `⚠ git: video-editor +40` - when a
   project repo has drifted from origin, and nothing at all while everything is
   pushed. Only a JSON cache is read here; the recount (with fetch) happens in a
   detached process, so the statusline never waits on git or on the network.

Never fails the statusline: any error becomes a stderr line, the delegate's
output still goes out, the exit code is the delegate's (0 without one).
Note (item 1 of CF-0108): Claude Code only calls the statusline command in
terminal sessions, not in the desktop app - runs driven from there get their
percentages from limit_hook.py / transcript markers / rate_limits.json instead.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limits  # noqa: E402
import repo_sync  # noqa: E402
import runlog  # noqa: E402

DELEGATE = "~/.claude/statusline.py"
DELEGATE_ENV = "RUNLOG_STATUSLINE_DELEGATE"


def delegate_path():
    env = os.environ.get(DELEGATE_ENV)
    if env is not None:
        return Path(env).expanduser() if env else None
    p = Path(DELEGATE).expanduser()
    return p if p.is_file() else None


def own_line(data):
    model = (data.get("model") or {}) if isinstance(data, dict) else {}
    parts = [model.get("display_name") or model.get("id") or "?"]
    norm = limits.normalize(data) or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = norm.get(key) or {}
        if w.get("used_percentage") is not None:
            parts.append(f"{label} {round(float(w['used_percentage']))}%")
    return " · ".join(parts)


def sync_segment():
    """CF-0247: '⚠ git: <репо> +N' или '' - никогда не роняет статусную строку."""
    try:
        return repo_sync.segment()
    except Exception as e:
        runlog._warn(f"repo sync not shown ({e.__class__.__name__}: {e})")
        return ""


def with_segment(text, seg):
    """Пометка приклеивается к последней строке делегата, чтобы не съесть строку.

    Хвостовой перевод строки возвращается как был: статусная строка одна, и
    лишняя пустая строка под ней - такой же мусор, как потерянный перевод.
    """
    if not seg:
        return text
    if not text.strip():
        return seg + "\n" if text.endswith("\n") else seg
    tail = "\n" if text.endswith("\n") else ""
    lines = text.rstrip("\n").split("\n")
    lines[-1] = f"{lines[-1]} · {seg}"
    return "\n".join(lines) + tail


def main(argv=None):
    raw = b""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        pass
    rc = 0
    seg = sync_segment()
    dp = delegate_path()
    printed = False
    if dp is not None:
        try:
            cp = subprocess.run([sys.executable, str(dp)], input=raw, capture_output=True, timeout=10)
            sys.stdout.write(with_segment(cp.stdout.decode("utf-8", "replace"), seg))
            sys.stdout.flush()
            if cp.stderr:
                sys.stderr.buffer.write(cp.stderr)
            rc = cp.returncode
            printed = True
        except Exception as e:
            runlog._warn(f"statusline delegate failed ({e.__class__.__name__}: {e})")
    try:
        data = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
    except ValueError:
        data = {}
    if not printed:
        print(with_segment(own_line(data), seg))
    try:
        batch = limits.active_batch()
        if batch is not None:
            limits.record(batch, data, source="statusline", stale_s=0)
    except Exception as e:
        runlog._warn(f"limits not recorded ({e.__class__.__name__}: {e})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
