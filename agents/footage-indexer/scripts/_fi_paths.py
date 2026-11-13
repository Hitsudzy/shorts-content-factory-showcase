"""CF-0267: where the factory root, the sibling agents' scripts and this
agent's `.venv` are - asked from the root, not by counting `..`.

A module of its own, under a name no other agent repo uses, on purpose. This
lived in `_runlog.py` first, and every agent repo has a `_runlog.py`: when
video-editor's tests import `caption_cache` / `usability_probe` from here,
`_runlog` in sys.modules is already the Video Editor's, which has no
`sibling_scripts`, and the import died with ImportError. Scripts here import
the resolver as `from _fi_paths import ...`; `_runlog` stays the accounting
shim only (`runlog`, `factory_root`). `test_foreign_runlog.py` pins it.
"""
import os
from pathlib import Path

RUNLOG_REL = Path("shared") / "runlog" / "runlog.py"


def factory_root():
    """The factory root: FACTORY_ROOT if set, else the nearest ancestor of this
    file that holds shared/runlog/runlog.py (the same lookup as `_runlog`)."""
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for p in Path(__file__).resolve().parents:
        if (p / RUNLOG_REL).is_file():
            return p
    raise RuntimeError("factory root not found: set FACTORY_ROOT")


# CF-0267: the same lookup, asked for a *sibling* - the Video Editor's scripts
# this repo imports, and this repo's own `.venv` - instead of counting `..`
# from the asking file. `parent.parent.parent / "video-editor"` is right in
# `<root>/agents/footage-indexer/scripts/` and wrong everywhere the agent is not
# a direct child of `agents/`: a harness worktree (`agents/footage-indexer/
# .claude/worktrees/<x>/scripts/` -> `.claude/worktrees/video-editor`) or any
# checkout outside the tree. The answer is the root, found the way
# factory_root() finds it, with one difference: a FACTORY_ROOT without the
# sibling (a test's temp root holding only `channels/`) does not end the
# search - the walk is still asked. Outside the tree and without FACTORY_ROOT
# there is no answer, and the caller gets a FactoryRootError that says so and
# names the fix, not a ModuleNotFoundError three imports later.
AGENT = "footage-indexer"


class FactoryRootError(RuntimeError):
    """A sibling agent (or this agent's venv) is not reachable from here."""


def root_candidates():
    """Factory roots to try, in order: FACTORY_ROOT, then the nearest ancestor
    of this file that holds shared/runlog/runlog.py. Duplicates dropped."""
    seen = []
    env = os.environ.get("FACTORY_ROOT")
    if env:
        seen.append(Path(env).expanduser().resolve())
    for p in Path(__file__).resolve().parents:
        if (p / RUNLOG_REL).is_file():
            if p not in seen:
                seen.append(p)
            break
    return seen


def sibling_scripts(agent):
    """`<root>/agents/<agent>/scripts` - the first candidate root that has it.
    Raises FactoryRootError naming every place looked at."""
    tried = []
    for root in root_candidates():
        d = root / "agents" / agent / "scripts"
        if d.is_dir():
            return d
        tried.append(str(d))
    where = ", ".join(tried) if tried else "no FACTORY_ROOT and no ancestor holding " + str(RUNLOG_REL)
    raise FactoryRootError(
        f"{AGENT}: {agent}/scripts not found ({where}). This checkout "
        f"({Path(__file__).resolve().parents[1]}) is not inside the factory "
        f"tree; set FACTORY_ROOT=<factory root> (CF-0267)")


def venv_bin(name="python3"):
    """This agent's `.venv/bin/<name>`: the checkout's own when it has one
    (`.venv/` is gitignored, so a fresh worktree has none), else
    `<root>/agents/footage-indexer/.venv/bin/<name>`. When neither exists, the
    checkout's own path - the old answer, so `.exists()` checks keep working."""
    own = Path(__file__).resolve().parents[1] / ".venv" / "bin" / name
    if own.exists():
        return own
    for root in root_candidates():
        p = root / "agents" / AGENT / ".venv" / "bin" / name
        if p.exists():
            return p
    return own


# CF-0620: the defaults of the stage's own code that live under the factory
# root - the price table, the footage pool - asked from the root this checkout
# belongs to, not spelled as `Path.home() / "shorts-content-factory"` (the home
# checkout: code and tests of a version worktree read the live factory's copy
# instead of their own). Computed at import, so they must not raise: outside
# the tree with no FACTORY_ROOT the answer is the root this agent would have
# as `<root>/agents/footage-indexer/scripts/` - three parents up.
PRICES_REL = Path("shared") / "gate-prices.json"
POOL_REL = Path("shared") / "footage"


def checkout_root():
    """factory_root(), or - when neither FACTORY_ROOT nor an ancestor answers -
    the root this file's place implies (never the home checkout)."""
    try:
        return factory_root()
    except RuntimeError:
        return Path(__file__).resolve().parents[3]


def prices_file():
    """`<root>/shared/gate-prices.json`: the first candidate root
    (`root_candidates()`: FACTORY_ROOT, then this checkout's own root) that
    holds the table - a FACTORY_ROOT that is a test's temp root with no table
    does not hide this checkout's copy (the table is a contract, not live data);
    with no table anywhere, `checkout_root()`'s path (the module's draft prices
    then apply)."""
    for root in root_candidates():
        if (root / PRICES_REL).is_file():
            return root / PRICES_REL
    return checkout_root() / PRICES_REL


def pool_dir():
    """`<root>/shared/footage` of `checkout_root()` - strictly: a FACTORY_ROOT
    without a pool is an empty pool, never a fall-through to the live one."""
    return checkout_root() / POOL_REL
