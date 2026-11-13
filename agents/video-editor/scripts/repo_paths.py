"""Where the *real* checkout is - the one thing a git worktree cannot answer
by counting `..` (CF-0125).

Every path in this repo used to be resolved relative to the file asking for
it: `Path(__file__).parent.parent` for the agent root, `.parent` again for the
sibling agent, `AGENT_ROOT / ".venv"` for the interpreter. In the main checkout
that is correct. Under a git worktree - `agents/video-editor/.claude/worktrees/
<name>/` - the same arithmetic lands inside `.claude`:

    main checkout   agents/video-editor/scripts/..            -> agents/video-editor
                    agents/video-editor/../footage-indexer    -> agents/footage-indexer   OK
    worktree        .../.claude/worktrees/cf-0125/scripts/..  -> .../worktrees/cf-0125
                    .../worktrees/cf-0125/../footage-indexer  -> .../worktrees/footage-indexer   does not exist

and `.venv/` is gitignored, so a worktree has none of its own either and the
suite falls back to whatever `python3` the shell happens to mean (3.9, no PIL).
Both produced the same systematic false failures for every auto-dev worker on
this repo, plus a habit of papering over them with temporary symlinks that
somebody then has to remember to delete.

The fix is to ask git, not the filesystem. A worktree's `.git` is a *file*
holding `gitdir: <main>/.git/worktrees/<name>`, and that directory holds a
`commondir` pointing back at the one `.git` every worktree of the repo shares;
its parent is the main checkout. That is exactly what
`git rev-parse --git-common-dir` reports, read here directly instead of through
a subprocess - these files are plain text written by git itself, and this module
is imported by scripts that already run hundreds of times in one suite.

Two rules for callers:

  * Code *inside* this repo (scripts/, tests/, render/) stays anchored on
    `AGENT_ROOT` - the checkout the file actually lives in. A worktree exists
    precisely so its own code is what runs; resolving that to the main checkout
    would test the wrong tree.
  * Anything *outside* this repo - the sibling agent, the factory's channels/
    and pipeline/, the interpreter - is anchored here, on `MAIN_CHECKOUT`.
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# This checkout: a worktree when running from one. Repo-internal paths only.
AGENT_ROOT = HERE.parent


def main_checkout(start=None):
    """The non-worktree checkout of the repo `start` belongs to.

    `start` itself when it is the main checkout (its `.git` is a directory) or
    when nothing git-shaped is found - a tarball, a copied tree - so this is
    never worse than the arithmetic it replaces.
    """
    root = Path(start).resolve() if start is not None else AGENT_ROOT
    dot_git = root / ".git"
    if dot_git.is_dir():
        return root
    if not dot_git.is_file():
        return root
    try:
        pointer = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return root
    if not pointer.startswith("gitdir:"):
        return root
    gitdir = Path(pointer.split(":", 1)[1].strip()).expanduser()
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    common = gitdir / "commondir"
    try:
        rel = common.read_text(encoding="utf-8").strip()
        shared_git = Path(rel).expanduser()
        if not shared_git.is_absolute():
            shared_git = (gitdir / shared_git).resolve()
    except OSError:
        # No commondir file: fall back to the layout git writes,
        # <main>/.git/worktrees/<name>.
        shared_git = gitdir.parent.parent
    if shared_git.name == ".git" and shared_git.parent.is_dir():
        return shared_git.parent
    return root


# The checkout that has a .venv, and whose siblings are the other agents.
MAIN_CHECKOUT = main_checkout()

LOCK_NAME = "agents.lock.json"


def version_root(start=None):
    """CF-0482: the root whose `agents.lock.json` names this checkout as one of
    its agents, or None.

    A version is built in a worktree of the *root* (`.worktrees/release-<v>/`,
    CF-0479) with every agent checked out under it as a git worktree of the
    agent's own repo. Asked for its main checkout, such an agent answers - by
    git, correctly - the production one at `<factory>/agents/<name>`, so
    everything anchored on `MAIN_CHECKOUT` used to leave the version: the
    sibling indexer, channels/ and pipeline/ were the production v1.4 ones.
    The lock is the version's own word on where its agents are, so the
    neighbours are resolved off it. Only `<checkout>/../../agents.lock.json`
    is read, and only an entry whose `path` *is* this checkout counts - a
    checkout merely sitting somewhere under some root is not enough.

    Deliberately a separate function: `main_checkout()` and `VENV_PY` are part
    of what the caption probe reaches (CF-0387's key over `repo_paths.py`), and
    moving them would make the shared pool's caption stamps stale for nothing.
    The interpreter is the same anyway - the version links `.venv` from the
    working copy (`agents.lock.json` -> `links`).
    """
    root = Path(start).resolve() if start is not None else AGENT_ROOT
    cand = root.parent.parent
    try:
        lock = json.loads((cand / LOCK_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    agents = lock.get("agents") if isinstance(lock, dict) else None
    for entry in (agents or {}).values():
        rel = entry.get("path") if isinstance(entry, dict) else None
        if rel and (cand / rel).resolve() == root:
            return cand
    return None


VERSION_ROOT = version_root()

# agents/ - every agent of this factory is a sibling directory of the checkout;
# in a version's root worktree, the version's own agents/ (CF-0482).
AGENTS_DIR = VERSION_ROOT / "agents" if VERSION_ROOT else MAIN_CHECKOUT.parent

FACTORY_ROOT_ENV = "FACTORY_ROOT"


def factory_root(start=None):
    """The factory checkout above agents/ - where channels/ and pipeline/ live.

    Not the `FACTORY_ROOT` environment variable: that one is the *inserts
    library* root (shared/inserts/underlay.py's convention, honoured by
    meme_layer.factory_root() and _runlog.factory_root()), and this repo's own
    tests point it at a synthetic temp root. Use `meme_layer.factory_root()`
    when you want that override; use this when you want the real checkout.
    """
    if start is None and VERSION_ROOT is not None:
        return VERSION_ROOT
    base = MAIN_CHECKOUT if start is None else Path(start).resolve()
    for cand in [base, *base.parents]:
        if (cand / "agents").is_dir() and (cand / "channels").is_dir():
            return cand
    return base.parent.parent


FACTORY_ROOT = factory_root()
CHANNELS_DIR = FACTORY_ROOT / "channels"
PIPELINE_DIR = FACTORY_ROOT / "pipeline"

# Gitignored directories: they exist in the main checkout only, so a worktree
# that resolved them against itself would find nothing at all.
MODELS_DIR = MAIN_CHECKOUT / "models"


def sibling(name, start=None):
    """A sibling agent's checkout, e.g. sibling("footage-indexer")."""
    if start is None:
        base = AGENTS_DIR
    else:
        vroot = version_root(start)
        base = vroot / "agents" if vroot else main_checkout(start).parent
    return base / name


INDEXER = sibling("footage-indexer")
INDEXER_SCRIPTS = INDEXER / "scripts"
INDEXER_PY = str(INDEXER / ".venv" / "bin" / "python")


def venv_python(root=None, name="python"):
    """Path (str) to an interpreter in a checkout's .venv.

    `.venv/` is gitignored, so it exists in the main checkout only - that is
    the whole reason this is not `AGENT_ROOT / ".venv"`. Returned whether or
    not it exists: callers that want a fallback already test for it, and the
    ones that do not should fail loudly rather than silently run on a system
    python that lacks the repo's dependencies.
    """
    base = MAIN_CHECKOUT if root is None else Path(root)
    return str(base / ".venv" / "bin" / name)


VENV_PY = venv_python()
VENV_PY3 = venv_python(name="python3")


def is_worktree():
    """True when this file is running from a git worktree rather than the
    main checkout. For messages, not for path arithmetic."""
    return MAIN_CHECKOUT != AGENT_ROOT


# The root above the git main checkout - to tell a version's root from it.
FACTORY_ROOT_OF_MAIN = factory_root(MAIN_CHECKOUT)


def describe():
    """One line for a diagnostic: which tree is running, which one is lending
    its .venv and its siblings."""
    if VERSION_ROOT is not None and VERSION_ROOT != FACTORY_ROOT_OF_MAIN:
        return (f"version checkout {AGENT_ROOT} (root {VERSION_ROOT}, "
                f"git main checkout {MAIN_CHECKOUT})")
    if not is_worktree():
        return f"checkout {AGENT_ROOT}"
    return f"worktree {AGENT_ROOT} (main checkout {MAIN_CHECKOUT})"


if __name__ == "__main__":
    print(describe())
    for label, value in (("AGENT_ROOT", AGENT_ROOT), ("MAIN_CHECKOUT", MAIN_CHECKOUT),
                         ("VERSION_ROOT", VERSION_ROOT), ("FACTORY_ROOT", FACTORY_ROOT),
                         ("INDEXER", INDEXER),
                         ("VENV_PY", VENV_PY)):
        mark = "" if value is not None and Path(value).exists() else "   [missing]"
        print(f"  {label:<14} {value}{mark}")
    if os.environ.get(FACTORY_ROOT_ENV):
        print(f"  note: ${FACTORY_ROOT_ENV} is set; it names the inserts-library "
              "root, not this one")
