#!/usr/bin/env python3
"""CF-0108: wire the accounting hooks into ~/.claude/settings.json - dry-run by default.

    python3 scripts/install_accounting_hooks.py            # print the merged JSON, change nothing
    python3 scripts/install_accounting_hooks.py --apply    # write it, keeping a timestamped backup

What the merge does, and only that:

    statusLine.command   -> "python3 <root>/shared/runlog/statusline_hook.py"
                            (statusline_hook.py itself delegates to the previous
                            ~/.claude/statusline.py, so its output is unchanged)
    hooks.StopFailure    += {matcher: "rate_limit",
                             hooks: [{type: command,
                                      command: "python3 <root>/shared/runlog/limit_hook.py"}]}
                            (other StopFailure entries are kept; the entry is not
                            added twice)

Everything else in the file is preserved byte-for-byte in meaning (the file is
re-serialized with indent=2). --settings PATH and --root DIR override the
defaults (~/.claude/settings.json, the repo this script lives in). --apply
writes <settings>.bak-<UTC timestamp> first, then the new file atomically.

Note (task item 1): Claude Code calls the statusline command and the hooks in
terminal sessions; the desktop app / auto-dev sessions do not call the
statusline, so runs driven from there still rely on the fallback
(limit_hook.py where it fires, transcript markers via `runlog gaps`,
~/.claude/rate_limits.json when fresh). Installing is still worth it for
terminal-driven runs.
"""
import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = "~/.claude/settings.json"


def desired(root):
    root = Path(root).resolve()
    return {
        "statusLine": {"type": "command",
                       "command": f"python3 {root / 'shared' / 'runlog' / 'statusline_hook.py'}"},
        "StopFailure": {"matcher": "rate_limit",
                        "hooks": [{"type": "command",
                                   "command": f"python3 {root / 'shared' / 'runlog' / 'limit_hook.py'}"}]},
    }


def merge(settings, root):
    """The merged settings dict (a deep copy; the input is not touched) and the change list."""
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    want = desired(root)
    changes = []
    sl = out.get("statusLine")
    if not isinstance(sl, dict):
        sl = {}
    if sl.get("command") != want["statusLine"]["command"] or sl.get("type") != "command":
        changes.append(f"statusLine.command: {sl.get('command')!r} -> {want['statusLine']['command']!r}")
        sl = dict(sl)
        sl.update(want["statusLine"])
    out["statusLine"] = sl
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    sf = hooks.get("StopFailure")
    if not isinstance(sf, list):
        sf = []
    want_cmd = want["StopFailure"]["hooks"][0]["command"]
    present = any(isinstance(e, dict) and any(isinstance(h, dict) and h.get("command") == want_cmd
                                              for h in (e.get("hooks") or []))
                  for e in sf)
    if not present:
        sf = list(sf) + [want["StopFailure"]]
        changes.append(f"hooks.StopFailure += matcher=rate_limit command={want_cmd!r}")
    hooks = dict(hooks)
    hooks["StopFailure"] = sf
    out["hooks"] = hooks
    return out, changes


def load(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return json.loads(text) if text.strip() else {}


def apply(path, merged):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        backup.write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", default=DEFAULT_SETTINGS)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--apply", action="store_true", help="write the merge (default: dry-run)")
    ns = ap.parse_args(argv)
    path = Path(ns.settings).expanduser()
    try:
        current = load(path)
    except ValueError as e:
        sys.stderr.write(f"install_accounting_hooks: {path} is not valid JSON ({e}); fix it first\n")
        return 2
    merged, changes = merge(current, ns.root)
    if not ns.apply:
        print(json.dumps(merged, ensure_ascii=False, indent=2))
        sys.stderr.write(f"# dry-run: {path} not touched; {len(changes)} change(s):\n")
        for c in changes:
            sys.stderr.write(f"#   {c}\n")
        sys.stderr.write("# re-run with --apply to write it (a timestamped backup is kept)\n")
        return 0
    if not changes:
        print(f"{path}: already installed, nothing to do")
        return 0
    backup = apply(path, merged)
    print(f"{path}: written ({len(changes)} change(s)); backup {backup}")
    for c in changes:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
