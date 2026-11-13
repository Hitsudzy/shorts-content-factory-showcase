#!/usr/bin/env python3
"""CF-0214: no root script picks a channel, or a channel's switch, for a
caller who named none.

The recorded defect: `shared/inserts/underlay.py` took `--channel` as
optional and documented its absence as "omitted = layer forced on". A run
that forgot the flag did not get another channel's value - it got the
underlay that example-film had switched off by tone (CF-0014/CF-0189) switched
back on, visible only on the finished video. That CLI is a refusal now
(tests/test_underlay_layer.py has its behaviour); this file is the guard on
the class, the root's copy of the agents' guards
(agents/trend-hunter/tests/test_no_default_channel.py, CF-0213;
agents/video-editor/tests/test_channel_watermark.py, CF-0212):

* no Python under `shared/`, `scripts/`, `inserts/`, `patterns/`,
  `rotation/`, `agents/analyst/` and `agents/publisher/` (CF-0562) carries a
  channel's name as an argparse default, a parameter default, a `.get()`
  fallback, the right side of `x or ...`, a module constant, or a piece of a
  path (`root / "pipeline" / "<channel>"`, `.glob("<channel>*")`, CF-0562);
* no `--channel` argument there documents its absence as switching
  something on ("forced on" / "omitted =" in its help).

Source files are parsed, never run; the guard's own self-test writes its bad
example into a temp directory (docs/test-hygiene.md).
"""
import ast
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# CF-0562: patterns/, rotation/ and the two agents that live in this repo
# (analyst, publisher) are root code too; their tests carry channel names as
# fixtures and are not scanned.
SCANNED = ("shared", "scripts", "inserts", "patterns", "rotation", "agents/analyst",
           "agents/publisher")
SKIP_PARTS = {"__pycache__", "node_modules", ".venv", "tests"}

# Every name a channel of this factory has gone by, squashed to letters and
# digits - the same list as the agents' guards.
CHANNEL_NAMES = ("legacyfilm", "example-film", "example-tech", "example-science")

# (path, value) pairs that carry a channel's name and are not a channel:
# each with the reason it is allowed. Keep this short.
ALLOWED = {
    ("shared/batch_schedule.py", "com.example-film.batch-schedule"):
        "the launchd label of the one factory-wide scheduler (the brand's "
        "reverse-DNS, CF-0605): it serves every channel, and renaming it "
        "would orphan the job already installed under ~/Library/LaunchAgents",
}


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _channel_name_defaults(path):
    """(line, value, what) for every string in `path` that stands in for a
    channel nobody named."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    def check(node, what):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(name in _squash(node.value) for name in CHANNEL_NAMES):
                found.append((node.lineno, node.value, what))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attr = getattr(node.func, "attr", None)
            if attr == "add_argument":
                for kw in node.keywords:
                    if kw.arg == "default":
                        check(kw.value, "add_argument default")
            elif attr in ("get", "setdefault", "getenv") and len(node.args) >= 2:
                check(node.args[1], f".{attr}() fallback")
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values[1:]:
                check(value, "`or` fallback")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for d in [*node.args.defaults, *node.args.kw_defaults]:
                if d is not None:
                    check(d, f"default of {getattr(node, 'name', 'lambda')}()")
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            check(node.value, "module constant")
    # CF-0562: a channel's name as a piece of a path - `root / "pipeline" /
    # "example-film"`, `.glob("example-film*")` - is the same default in another
    # shape: the code looks where the first channel lives and nowhere else.
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            check(node.left, "path segment")
            check(node.right, "path segment")
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", None) in (
                "glob", "rglob", "joinpath", "with_name"):
            for a in node.args:
                check(a, f".{node.func.attr}() argument")
    return found


_FORCING_HELP = re.compile(r"\b(forced|switched|turned|always)\s+on\b"
                           r"|\b(omitted|absent|none)\s*(=|means)\s*(on|enabled|forced)\b", re.I)


def _channel_args_that_switch_on_when_absent(path):
    """(line, help) for every `add_argument("--channel...", help=...)` whose
    help says leaving it out turns something on - the shape underlay.py had.
    An optional --channel that filters (omitted = every channel) is fine."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not any(f.startswith("--channel") for f in flags):
            continue
        for kw in node.keywords:
            if kw.arg == "help" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str) and _FORCING_HELP.search(kw.value.value):
                found.append((node.lineno, kw.value.value))
    return found


def _is_python(path):
    if path.suffix == ".py":
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as fh:
            first = fh.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def _sources():
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*")):
            if path.is_file() and not SKIP_PARTS & set(path.parts) and _is_python(path):
                yield path


# --------------------------------------------------------------------------
# the guard sees what it guards against
# --------------------------------------------------------------------------

def test_the_guard_sees_what_it_guards_against():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.py"
        bad.write_text('"""a docstring may say example-film"""\n'
                       'import argparse\n'
                       'p = argparse.ArgumentParser()\n'
                       'p.add_argument("--channel", default="example-film")\n'
                       'def f(channel="ExampleTech"): pass\n'
                       'c = batch.get("channel", "legacy-film")\n'
                       'd = arg or "Example Science"\n'
                       'DEFAULT_CHANNEL = "example-film"\n'
                       'def g(name="ok"): return {}.get("k", "fine") or "x"\n'
                       'print("pipeline/example-film/ is where it went")\n'
                       'p.add_argument("--channel", help="channel JSON; omitted = layer forced on")\n'
                       'p.add_argument("--channel-id", help="the id; omitted = every channel")\n'
                       'p.add_argument("--channel", help="the channel config, required")\n'
                       'pool = root / "pipeline" / "example-film"\n'
                       'hits = root.glob("channels/example-film*")\n'
                       'ok = root / "pipeline" / channel\n')
        assert sorted(line for line, _, _ in _channel_name_defaults(bad)) == [4, 5, 6, 7, 8, 14, 15]
        assert [line for line, _ in _channel_args_that_switch_on_when_absent(bad)] == [11]


def test_the_scan_covers_the_root_code():
    names = {str(p.relative_to(ROOT)) for p in _sources()}
    for must in ("shared/inserts/underlay.py", "shared/batch_schedule.py",
                 "scripts/agents", "inserts/validate_inserts.py", "patterns/validate_patterns.py",
                 "rotation/rotate.py", "agents/analyst/studio_read.py",
                 "agents/publisher/api_switch.py"):
        assert must in names, f"{must} is not scanned"


# --------------------------------------------------------------------------
# the root
# --------------------------------------------------------------------------

def test_no_root_script_defaults_to_a_channels_name():
    hits, used = [], set()
    for path in _sources():
        rel = str(path.relative_to(ROOT))
        for line, value, what in _channel_name_defaults(path):
            if (rel, value) in ALLOWED:
                used.add((rel, value))
                continue
            hits.append(f"{rel}:{line}: {what} = {value!r}")
    assert not hits, ("a channel's name as a default - a second channel that forgets "
                      "the flag runs as the first one (CF-0213/CF-0214):\n  "
                      + "\n  ".join(hits))
    stale = set(ALLOWED) - used
    assert not stale, f"ALLOWED names what is no longer there - drop it: {sorted(stale)}"


def test_no_channel_argument_switches_something_on_when_left_out():
    hits = [f"{path.relative_to(ROOT)}:{line}: help={text!r}"
            for path in _sources()
            for line, text in _channel_args_that_switch_on_when_absent(path)]
    assert not hits, ("a --channel whose absence switches something on - a forgotten "
                      "flag cancels the channel's own switch (CF-0214):\n  "
                      + "\n  ".join(hits))


def _run():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
