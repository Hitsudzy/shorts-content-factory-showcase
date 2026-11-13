#!/usr/bin/env python3
"""CF-0125: paths that point outside this repo must not be counted in `..`.

Two halves. The first drives `repo_paths.main_checkout()` over synthetic
directory trees - a main checkout, a worktree with an absolute pointer, one
with a relative pointer, one whose gitdir has no `commondir`, a tree with no
git at all - because the real answer here depends on files git writes, and a
test that only ran in whichever tree the runner happened to be in would prove
nothing about the other one.

The second half is a guard over the source: the bug this task closes was not
one wrong line, it was a *habit* - resolve the sibling agent, the factory's
channels/ and pipeline/, or the interpreter by walking up from `__file__`.
Every such site was fixed once; this keeps the next one from being written.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import repo_paths  # noqa: E402


def _make_main(tmp, name="video-editor"):
    """A main checkout: <root>/agents/<name> with a real .git directory."""
    root = tmp / "agents" / name
    (root / ".git").mkdir(parents=True)
    return root


def _make_worktree(main, name="wt", pointer="absolute", commondir=True):
    """The tree git writes for `git worktree add <main>/.claude/worktrees/<name>`."""
    gitdir = main / ".git" / "worktrees" / name
    gitdir.mkdir(parents=True)
    if commondir:
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    wt = main / ".claude" / "worktrees" / name
    wt.mkdir(parents=True)
    if pointer == "absolute":
        target = str(gitdir)
    else:
        target = "../../../.git/worktrees/" + name
    (wt / ".git").write_text(f"gitdir: {target}\n", encoding="utf-8")
    return wt


def test_main_checkout_is_itself():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main = _make_main(Path(td).resolve())
        assert repo_paths.main_checkout(main) == main, \
            "a checkout whose .git is a directory is already the main checkout"


def test_worktree_resolves_to_main_checkout():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main = _make_main(Path(td).resolve())
        wt = _make_worktree(main)
        assert repo_paths.main_checkout(wt) == main, (
            "a worktree must resolve to the checkout it was branched from, not "
            f"to itself - got {repo_paths.main_checkout(wt)}")


def test_worktree_relative_gitdir_pointer():
    """git writes an absolute pointer today, a relative one when the repo was
    moved or created with an older git. Both are the same answer."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main = _make_main(Path(td).resolve())
        wt = _make_worktree(main, name="rel", pointer="relative")
        assert repo_paths.main_checkout(wt) == main, \
            "a relative `gitdir:` pointer resolves against the worktree itself"


def test_worktree_without_commondir_falls_back_to_layout():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main = _make_main(Path(td).resolve())
        wt = _make_worktree(main, name="nocommon", commondir=False)
        assert repo_paths.main_checkout(wt) == main, \
            "with no commondir file, <main>/.git/worktrees/<name> still names <main>"


def test_no_git_at_all_is_not_worse_than_the_old_arithmetic():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td).resolve() / "copied-tree"
        (plain / "scripts").mkdir(parents=True)
        assert repo_paths.main_checkout(plain) == plain, \
            "an exported/copied tree resolves to itself rather than raising"


def test_sibling_and_venv_hang_off_the_main_checkout():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main = _make_main(Path(td).resolve())
        wt = _make_worktree(main)
        assert repo_paths.sibling("footage-indexer", start=wt) == \
            main.parent / "footage-indexer", (
            "the sibling agent lives beside the main checkout; from a worktree "
            "the old arithmetic pointed at .claude/worktrees/footage-indexer")
        assert repo_paths.venv_python(repo_paths.main_checkout(wt)) == \
            str(main / ".venv" / "bin" / "python"), \
            "a worktree has no venv of its own (.venv/ is gitignored)"


def test_factory_root_walks_to_agents_and_channels():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        main = _make_main(root)
        (root / "channels").mkdir()
        assert repo_paths.factory_root(main) == root
        wt = _make_worktree(main)
        assert repo_paths.factory_root(repo_paths.main_checkout(wt)) == root, \
            "channels/ and pipeline/ live above agents/, from a worktree too"


def _make_version(tmp, names=("video-editor", "footage-indexer")):
    """CF-0482: a production checkout <tmp>/prod/agents/<name> and a version's
    root worktree <tmp>/prod/.worktrees/release-9.9 whose agents are git
    worktrees of the production agents, named by its agents.lock.json."""
    import json
    prod = tmp / "prod"
    (prod / "channels").mkdir(parents=True)
    vroot = prod / ".worktrees" / "release-9.9"
    (vroot / "channels").mkdir(parents=True)
    out = {}
    for n in names:
        main = prod / "agents" / n
        gitdir = main / ".git" / "worktrees" / n
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt = vroot / "agents" / n
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        out[n] = (main, wt)
    (vroot / "agents.lock.json").write_text(json.dumps({"agents": {
        n: {"path": f"agents/{n}", "rev": "main"} for n in names}}), encoding="utf-8")
    return prod, vroot, out


def test_a_version_checkout_finds_its_neighbours_in_the_version():
    """CF-0482: in a version's root worktree git still answers the production
    checkout as main (that is where .git lives), but the sibling agent and the
    factory root are the version's own - off its agents.lock.json."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prod, vroot, agents = _make_version(Path(td).resolve())
        main, wt = agents["video-editor"]
        assert repo_paths.main_checkout(wt) == main
        assert repo_paths.version_root(wt) == vroot
        assert repo_paths.sibling("footage-indexer", start=wt) == \
            vroot / "agents" / "footage-indexer", "the version's indexer, not production's"
        assert repo_paths.factory_root(vroot) == vroot
        # production stays production: its own root's lock is not in the picture
        assert repo_paths.version_root(main) is None
        assert repo_paths.sibling("footage-indexer", start=main) == \
            prod / "agents" / "footage-indexer"


def test_a_lock_that_does_not_name_this_checkout_is_not_a_version():
    """Only an entry whose path *is* the checkout counts; a stray or broken
    lock two levels up changes nothing."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prod, vroot, agents = _make_version(Path(td).resolve(), names=("video-editor",))
        _, wt = agents["video-editor"]
        (vroot / "agents.lock.json").write_text(json.dumps(
            {"agents": {"other": {"path": "agents/other"}}}), encoding="utf-8")
        assert repo_paths.version_root(wt) is None
        (vroot / "agents.lock.json").write_text("{not json", encoding="utf-8")
        assert repo_paths.version_root(wt) is None


def test_the_version_root_does_not_move_what_the_caption_probe_reaches():
    """`main_checkout()` and `VENV_PY` are reached by the caption probe, so the
    version lookup must not run through them - otherwise the shared pool's
    caption stamps would go stale for a path question (CF-0387 key)."""
    import ast
    tree = ast.parse((SCRIPTS / "repo_paths.py").read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("main_checkout", "venv_python"):
        used = {x.id for x in ast.walk(fns[name]) if isinstance(x, ast.Name)}
        assert not used & {"version_root", "VERSION_ROOT", "AGENTS_DIR"}, name


def test_this_checkout_reaches_the_real_neighbours():
    """The acceptance criterion of CF-0125, asserted from wherever this runs:
    in the main checkout and in a worktree the answers must be the same, with
    no symlink propping them up."""
    assert repo_paths.INDEXER.is_dir(), (
        f"{repo_paths.INDEXER} is not a directory - the sibling agent did not "
        f"resolve ({repo_paths.describe()})")
    assert Path(repo_paths.VENV_PY).exists(), (
        f"{repo_paths.VENV_PY} does not exist - the repo's own interpreter did "
        f"not resolve ({repo_paths.describe()})")
    assert repo_paths.CHANNELS_DIR.is_dir(), f"{repo_paths.CHANNELS_DIR} is not a directory"
    for label, value in (("INDEXER", repo_paths.INDEXER),
                         ("VENV_PY", Path(repo_paths.VENV_PY)),
                         ("FACTORY_ROOT", repo_paths.FACTORY_ROOT)):
        assert ".claude" not in value.parts, \
            f"{label} points inside .claude ({value}) - that is the CF-0125 bug"


# --------------------------------------------------------------------------
# the guard: no new site may go back to counting `..`
# --------------------------------------------------------------------------

# `repo_paths.py` is where these literals belong; this file quotes them to
# describe them. Nothing else in scripts/ or tests/ may build them by hand.
GUARD_EXEMPT = {"repo_paths.py", "test_repo_paths.py"}

# One narrow exception, marked line by line rather than by whole file:
# run_tests.py has to work in a repo that has no scripts/repo_paths.py at all
# (the stdlib-only pipeline-contract suite at the factory root), so its loader
# keeps the old arithmetic as a fallback. Any other use of this marker is a
# bug, which is why it is a marker and not a file exemption.
BOOTSTRAP_MARK = "# repo_paths-bootstrap"

VENV_LITERAL = re.compile(r'["\']\.venv["\']|\.venv/bin/')
SIBLING_LITERAL = re.compile(r'/\s*["\']footage-indexer["\']')
FACTORY_DIR_LITERAL = re.compile(r'parent\s*/\s*["\'](?:channels|pipeline)["\']')

GUARDS = (
    (VENV_LITERAL, "build the interpreter path by hand",
     "use repo_paths.VENV_PY / repo_paths.VENV_PY3 / repo_paths.venv_python()"),
    (SIBLING_LITERAL, "name the sibling agent's directory by hand",
     "use repo_paths.INDEXER / repo_paths.INDEXER_SCRIPTS / repo_paths.sibling()"),
    (FACTORY_DIR_LITERAL, "walk up to the factory's channels/ or pipeline/",
     "use repo_paths.CHANNELS_DIR / repo_paths.PIPELINE_DIR"),
)


def _guarded_files():
    for d in (SCRIPTS, HERE):
        for p in sorted(d.glob("*.py")):
            if p.name not in GUARD_EXEMPT:
                yield p


def test_no_hand_rolled_paths_outside_the_repo():
    offences = []
    for path in _guarded_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or BOOTSTRAP_MARK in line:
                continue  # prose about the bug, and the one marked bootstrap
            for pattern, what, instead in GUARDS:
                if pattern.search(line):
                    offences.append(f"{path.name}:{lineno} tries to {what} "
                                    f"- {instead}\n      {stripped}")
    assert not offences, (
        "CF-0125: paths outside this repo must come from repo_paths.py, which "
        "resolves them against the main checkout - counting `..` from __file__ "
        "lands in .claude/worktrees/ when the code runs from a git worktree:\n  "
        + "\n  ".join(offences))


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
