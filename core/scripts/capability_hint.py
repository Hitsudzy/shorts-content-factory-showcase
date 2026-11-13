#!/usr/bin/env python3
"""CF-0653: a hint for the driver - which new user capabilities a task's diff adds.

    python3 scripts/capability_hint.py <base>..<head> [-C DIR]... [--openapi PATH] [--json]

The rule (AUTONOMOUS_DEV_PROMPT.md, "Новая возможность = адрес API + задача на
экран"): a factory task that gives the user a new command, flag, setting,
action or view closes only when its address is in `api/openapi.json` or a
`CC-` task for the address and the screen is filed in `frontend/tasks`. The
driver checks that by hand when it closes a task; this script lists what to
check. It is a hint, not a gate - it always exits 0 (2 only on a bad call):

* new `argparse` commands and flags - an added line with `add_parser("x")` or
  `add_argument("--x")` in any file outside `tests/` and `api/` (scripts/,
  shared/, agents/*; `api/` is the address side itself); a name that the same file also lost in the diff is a move or an
  edit, not a new capability, and is left out;
* new keys of `channels/*.json` - the key paths (`a.b.c`, dicts only) the head
  version has and the base version had not.

Each line says whether the name is met anywhere in `api/openapi.json` (as
written, with `-`/`_` swapped, case ignored) - "met" is a lead, not a proof
that the address exists. Internal flags (debugging, test stands, the driver's
own service commands) need no address; telling them apart is the driver's
call. The check over the whole factory - command <-> address <-> screen - is
the command center's CC-0034.

`-C DIR` (repeatable) reads another repository, e.g. `-C agents/video-editor`;
without it the root is read. `<base>` alone means `<base>..HEAD`.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT_TIMEOUT = 60
if str(ROOT / "shared" / "runlog") not in sys.path:
    sys.path.append(str(ROOT / "shared" / "runlog"))
import git_read  # noqa: E402  (CF-0717: git reads with optional locks off)

PARSER_RE = re.compile(r"""add_parser\(\s*(?:name\s*=\s*)?["']([\w.-]+)["']""")
ARGUMENT_RE = re.compile(r"""add_argument\(\s*["']([\w-]+)["']""")


def _skipped(path):
    p = "/" + path
    return "/tests/" in p or p.startswith("/api/") or p.endswith(".md") or p.endswith(".json")


def scan_diff(diff_text):
    """New `add_parser` commands and `add_argument` flags of a unified diff.

    Returns [{"file", "kind": "command"|"flag"|"argument", "name"}], in diff
    order, one per (file, kind, name). Files under `tests/` are skipped."""
    added, removed, path = [], set(), None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = None if target == "/dev/null" else re.sub(r"^b/", "", target)
            continue
        if line.startswith("--- ") or path is None or _skipped(path):
            continue
        if line.startswith("+"):
            bucket = "+"
        elif line.startswith("-"):
            bucket = "-"
        else:
            continue
        found = [("command", n) for n in PARSER_RE.findall(line)]
        for n in ARGUMENT_RE.findall(line):
            found.append(("flag" if n.startswith("-") else "argument", n))
        for kind, name in found:
            key = (path, kind, name)
            if bucket == "-":
                removed.add(key)
            elif key not in added:
                added.append(key)
    return [{"file": f, "kind": k, "name": n} for f, k, n in added
            if (f, k, n) not in removed]


def new_json_keys(old, new, prefix=""):
    """Dotted key paths of dicts that `new` has and `old` had not. A key whose
    parent is new is not listed again - the parent covers it."""
    out = []
    if not isinstance(new, dict):
        return out
    old = old if isinstance(old, dict) else {}
    for k, v in new.items():
        dotted = f"{prefix}{k}"
        if k not in old:
            out.append(dotted)
        else:
            out.extend(new_json_keys(old[k], v, dotted + "."))
    return out


def _variants(name):
    bare = name.lstrip("-").split(".")[-1]
    return {bare, bare.replace("-", "_"), bare.replace("_", "-")}


def met_in_openapi(name, openapi_text):
    """Whether the name (the last segment of a key path, without dashes in
    front, `-`/`_` swapped) is met anywhere in the contract's text."""
    if not openapi_text:
        return False
    low = openapi_text.lower()
    return any(v and v.lower() in low for v in _variants(name))


def _git(repo, *args):
    cp = git_read.run(["-C", str(repo), *args], capture_output=True,
                      text=True, timeout=GIT_TIMEOUT)
    return cp


def _show_json(repo, rev, path):
    cp = _git(repo, "show", f"{rev}:{path}")
    if cp.returncode != 0:
        return {}
    try:
        return json.loads(cp.stdout)
    except ValueError:
        return {}


def scan_repo(repo, rng):
    base, _, head = rng.partition("..")
    head = head or "HEAD"
    diff = _git(repo, "diff", "-U0", f"{base}..{head}")
    if diff.returncode != 0:
        raise SystemExit(f"capability_hint: git diff {base}..{head} in {repo}: "
                         f"{diff.stderr.strip()}")
    items = scan_diff(diff.stdout)
    names = _git(repo, "diff", "--name-only", f"{base}..{head}", "--", "channels")
    for path in names.stdout.split():
        if not path.endswith(".json"):
            continue
        for key in new_json_keys(_show_json(repo, base, path), _show_json(repo, head, path)):
            items.append({"file": path, "kind": "setting", "name": key})
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("range", help="<base>..<head>, or <base> for <base>..HEAD")
    ap.add_argument("-C", dest="repos", action="append", default=[],
                    help="repository to read (repeatable); default: the root")
    ap.add_argument("--openapi", default=str(ROOT / "api" / "openapi.json"),
                    help="the API contract to look the names up in")
    ap.add_argument("--json", action="store_true", help="print the list as JSON")
    a = ap.parse_args(argv)
    repos = [Path(r) for r in a.repos] or [ROOT]
    try:
        openapi_text = Path(a.openapi).read_text(encoding="utf-8")
    except OSError:
        openapi_text = ""
    rows = []
    for repo in repos:
        for it in scan_repo(repo, a.range):
            it["repo"] = str(repo)
            it["in_openapi"] = met_in_openapi(it["name"], openapi_text)
            rows.append(it)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("capability_hint: no new commands, flags or channel keys in the diff")
        return 0
    print("capability_hint (CF-0653) - check by hand: a user capability needs an "
          "address in api/openapi.json or a CC- task for the address and the screen")
    for r in rows:
        mark = "met in openapi" if r["in_openapi"] else "NOT in openapi"
        where = r["file"] if len(repos) == 1 else f"{r['repo']}: {r['file']}"
        print(f"  {r['kind']:<8} {r['name']:<32} {mark:<15} {where}")
    if not openapi_text:
        print(f"  (no contract at {a.openapi} - every name reads NOT in openapi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
