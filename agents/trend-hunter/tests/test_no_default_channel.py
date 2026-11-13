#!/usr/bin/env python3
"""CF-0213: no script of this agent picks a channel for a caller who named none.

The recorded defect: `score_candidates.py` read `batch.get("channel", <first
channel>)` and `--channel-config or <first channel>`; `fact_probe_topics.py`
gave a batch without a `channel` field the first channel's id; `pool_coverage.py`
and `pool_coverage_replay.py` had it as an argparse default and a module
constant. A second channel's run that forgot the flag would have been scored,
cut and pool-checked as the first channel - its feeds, its shortlist size, its
refusal switch, its retired shots - without a word. No channel is a refusal
now, and the guard below keeps a channel's name out of every default in
`scripts/` (the same guard as video-editor's CF-0212, widened to the shapes
this agent had: `.get(key, <name>)`, `x or <name>` and a module constant).

Stand-in batches in temporary directories only - no live channel file, no
live batch (docs/test-hygiene.md of the root).
"""
import ast
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fact_probe_topics as fp  # noqa: E402
import pool_coverage as pc  # noqa: E402
import pool_coverage_replay as pr  # noqa: E402

# Every name a channel of this factory has gone by, squashed to letters and
# digits - the same list as agents/video-editor/tests/test_channel_watermark.py.
CHANNEL_NAMES = ("legacyfilm", "example-film", "example-tech", "example-science")


def _quiet(fn, *args):
    err = io.StringIO()
    code = None
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            code = fn(*args)
        except SystemExit as exc:
            code = exc.code
    return code, err.getvalue()


# --------------------------------------------------------------------------
# the scripts refuse
# --------------------------------------------------------------------------

def test_the_fact_probe_refuses_a_batch_without_a_channel():
    with tempfile.TemporaryDirectory() as d:
        batch = {"batch_id": "2026-10-07T1200Z", "topics": []}
        path = Path(d) / "01-trend-hunter.json"
        path.write_text(json.dumps(batch))
        code, err = _quiet(fp.main, [d, "--check"])
        assert code == 2, (code, err)
        assert "no `channel` field" in err and "CF-0213" in err, err
        assert json.loads(path.read_text()) == batch


def test_pool_coverage_needs_the_channel():
    code, err = _quiet(pc.main, ["Some Title"])
    assert code == 2 and "--channel" in err, (code, err)


def test_the_pool_replay_needs_the_channel():
    code, err = _quiet(pr.main, ["--json"])
    assert code == 2 and "--channel" in err, (code, err)


def test_the_pool_replay_takes_the_channel_it_is_given():
    import inspect
    assert list(inspect.signature(pr.replay).parameters) == ["root", "channel"]
    assert not hasattr(pr, "CHANNEL") and not hasattr(pr, "RETIRED_CHANNEL")


# --------------------------------------------------------------------------
# the guard
# --------------------------------------------------------------------------

def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _channel_name_defaults(path):
    """(line, what) for every string in `path` that stands in for a channel
    nobody named: an `add_argument(..., default=...)`, a function parameter's
    default, the fallback of a `.get(key, ...)`, the right side of `x or ...`,
    and a module-level constant."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []

    def check(node, what):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(name in _squash(node.value) for name in CHANNEL_NAMES):
                found.append((node.lineno, f"{what} = {node.value!r}"))

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
    return found


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
                       'print("pipeline/example-film/ is where it went")\n')
        assert sorted(line for line, _ in _channel_name_defaults(bad)) == [4, 5, 6, 7, 8]


def test_no_script_defaults_to_a_channels_name():
    hits = [f"{path.relative_to(AGENT_ROOT)}:{line}: {what}"
            for path in sorted(SCRIPTS.rglob("*.py")) if "__pycache__" not in path.parts
            for line, what in _channel_name_defaults(path)]
    assert not hits, ("a channel's name as a default - a second channel that "
                      "forgets the flag runs as the first one (CF-0213):\n  "
                      + "\n  ".join(hits))


def test_the_skill_declares_no_default_channel():
    skill = (AGENT_ROOT / ".claude" / "skills" / "trend-hunter" / "SKILL.md").read_text()
    for line in skill.splitlines():
        if "default" in line.lower() and "channel" in line.lower():
            assert not any(name in _squash(line) for name in CHANNEL_NAMES), (
                f"SKILL.md names a default channel again (CF-0213): {line.strip()}")


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
