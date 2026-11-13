#!/usr/bin/env python3
"""CF-0152: one name, two numbers, two repositories - the defect no one can
see by reading a single file.

`patterns/validate_patterns.py MIN_BLOCK_SECONDS` was 0.6, the shortest block
the pipeline has ever produced. `agents/video-editor/scripts/rhythm.py
MIN_BLOCK_SECONDS` was 1.6, the gap below which an anchor is too tight to read
- a different quantity answering a different question. Both were right in their
own file. Between them lies 41.5% of the real material (153 of 369 blocks in 24
released plans are shorter than 1.6s), so importing the wrong one changes an
answer quietly and plausibly: the structural ceiling of CF-0141 is 40.40s on
0.6 and 29.40s on 1.6. It was caught by a worker who happened to check the
formula, not by anything in the code.

This is that check, made mechanical. It reads *measured quantities* only -
module-level constants whose name carries a unit (`_SECONDS`, `_RATIO`, ...)
and whose value is a number - because those are exactly the constants where
"same name, different number" silently changes an answer. A name shared between
the root and any `agents/*` must carry the same number in both.

Deliberately narrow, and the narrowness is measured (CF-0152): over the whole
project, 17 ALL_CAPS names are shared between the root and the agents and 8 of
them hold different values - but all 8 are generic test fixtures and per-module
enums (`CEILING`, `CHANNEL`, `KIND`, `OTHER`, `VERDICTS`, ...) where the
collision means nothing. Restricted to unit-carrying numbers the noise is zero
today, and the scan over the pre-CF-0152 tree reports exactly one clash:
MIN_BLOCK_SECONDS, root=0.6 agents=1.6. A guard that fires once and only on the
real thing is worth having; a guard with eight standing exceptions is not.

Pure `ast`: nothing is imported, nothing is executed, ~2s over ~90 files.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"

# Directories that hold no cross-repo contract: test fixtures, scratch work,
# vendored code, per-run pipeline output.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__",
             "pipeline", "shared", ".claude", "tests", "work", "archive"}

# A name ending in one of these is a measured quantity, not a label. This is
# the whole filter, and it is why the guard is quiet.
UNIT_SUFFIXES = ("_SECONDS", "_MS", "_MINUTES", "_HOURS", "_CHARS", "_WORDS",
                 "_PX", "_RATIO", "_PERCENT", "_BYTES", "_MB", "_CPS", "_FPS",
                 "_DB", "_HZ", "_KBPS")


def _numeric_constants(path):
    """{NAME: value} for module-level `NAME_WITH_UNIT = <number>` in one file."""
    found = {}
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return found
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name)
                    and target.id.endswith(UNIT_SUFFIXES)):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            found[target.id] = float(value)
    return found


def _sources(base, extra_skip=()):
    skip = SKIP_DIRS | set(extra_skip)
    return [p for p in sorted(base.rglob("*.py"))
            if not (set(p.relative_to(base).parts) & skip)]


def _collect(files):
    """{NAME: {value: [paths]}} across a set of files."""
    out = {}
    for f in files:
        for name, value in _numeric_constants(f).items():
            try:
                where = str(f.relative_to(ROOT))
            except ValueError:                 # a synthetic tree in a tmpdir
                where = str(f)
            out.setdefault(name, {}).setdefault(value, []).append(where)
    return out


def test_a_measured_constant_shared_with_an_agent_holds_the_same_number():
    if not AGENTS.is_dir():
        # A git worktree of the root has no `agents/` at all (it is gitignored,
        # CF-0196). Nothing to compare - say so out loud rather than pass mute.
        print("   no agents/ checkout here - cross-repo scan not run")
        return

    # CF-0651: frontend/ is the command center's own repo (node_modules inside)
    root_consts = _collect(_sources(ROOT, extra_skip={"agents", "frontend"}))
    agent_files = []
    for agent in sorted(AGENTS.iterdir()):
        if agent.is_dir():
            agent_files += _sources(agent)
    assert agent_files, "agents/ exists but holds no python - scan is blind"
    agent_consts = _collect(agent_files)

    clashes = []
    for name in sorted(set(root_consts) & set(agent_consts)):
        root_values = set(root_consts[name])
        agent_values = set(agent_consts[name])
        if root_values == agent_values:
            continue
        where = sorted({p for v in root_consts[name] for p in root_consts[name][v]}
                       | {p for v in agent_consts[name] for p in agent_consts[name][v]})
        clashes.append(f"{name}: root={sorted(root_values)} "
                       f"agents={sorted(agent_values)}\n        "
                       + "\n        ".join(where))

    assert not clashes, (
        "the same name holds different numbers in the root and in an agent "
        "(CF-0152). Either they are the same quantity - then one of them is a "
        "copy that has drifted, and the reader should import it rather than "
        "restate it - or they are different quantities, and the one that is "
        "misnamed has to be renamed for what it measures. Do not settle it by "
        "moving a number.\n     " + "\n     ".join(clashes))


def test_the_scan_actually_sees_the_constants_it_claims_to_read():
    """The guard above passes trivially if the walk finds nothing. Pin both
    ends of the real pair it exists for: the root's block floor, and the
    Editor's anchor gap under the name CF-0152 gave it."""
    validator = _numeric_constants(ROOT / "patterns" / "validate_patterns.py")
    assert validator.get("MIN_BLOCK_SECONDS") == 0.6, validator
    if not AGENTS.is_dir():
        print("   no agents/ checkout here - editor half not checked")
        return
    rhythm = AGENTS / "video-editor" / "scripts" / "rhythm.py"
    if not rhythm.exists():
        print("   no video-editor checkout here - editor half not checked")
        return
    editor = _numeric_constants(rhythm)
    assert editor.get("MIN_ANCHOR_GAP_SECONDS") == 1.6, editor
    assert "MIN_BLOCK_SECONDS" not in editor, (
        "MIN_BLOCK_SECONDS is back in rhythm.py under a block-floor reading - "
        "that is the CF-0152 collision returning")


def test_the_guard_fires_on_the_defect_it_was_built_for():
    """A negative control: the scan must report the pre-CF-0152 pair. Run over
    a synthetic two-repo tree rather than over git history, so the control
    survives rebases and shallow clones."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "patterns").mkdir()
        (tmp / "patterns" / "v.py").write_text("MIN_BLOCK_SECONDS = 0.6\n")
        (tmp / "agents" / "ed" / "scripts").mkdir(parents=True)
        (tmp / "agents" / "ed" / "scripts" / "r.py").write_text(
            "MIN_BLOCK_SECONDS = 1.6\nLEAD_SECONDS = 0.35\n")

        root_consts = _collect(_sources(tmp, extra_skip={"agents"}))
        agent_consts = _collect(_sources(tmp / "agents" / "ed"))
        clashing = {n for n in set(root_consts) & set(agent_consts)
                    if set(root_consts[n]) != set(agent_consts[n])}
        assert clashing == {"MIN_BLOCK_SECONDS"}, (clashing, root_consts, agent_consts)

        # ...and stays quiet when the same name holds the same number.
        (tmp / "patterns" / "v.py").write_text("LEAD_SECONDS = 0.35\n")
        root_consts = _collect(_sources(tmp, extra_skip={"agents"}))
        agreeing = {n for n in set(root_consts) & set(agent_consts)
                    if set(root_consts[n]) != set(agent_consts[n])}
        assert agreeing == set(), agreeing


# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
