"""CF-0323: the one place in this repo that finds the production-fact refusal
rule, the same way `_runlog.py` finds the run-accounting library:

    from _factrule import fact_rule

    state, decision = fact_rule.judge(fact_rule.answer_of_probe(record),
                                      stage="trend-hunter")

Lookup order, and why there are two places to look:

  1. `<root>/shared/factrule/fact_rule.py` - the rule's home. Both this stage
     and the Content Researcher are meant to load it from there, which is the
     whole point of CF-0323: one predicate, not two similar ones.
  2. `scripts/fact_rule.py` in this repo - the same module, authored here,
     because the root and the researcher are separate checkouts and land on
     separate days. This half of the task ships the rule and its caller; the
     next half moves the file to the root verbatim and points
     `agents/content-researcher/scripts/fact_refusal.py` at it.

Both paths hold the same module, so the answer does not depend on which one was
found - but which one answered is written to `fact_rule.ORIGIN` and printed by
the stage, because "the root has it and both ends use it" and "only the hunter
has it" are different states of the migration and a reader should not have to
guess which one a batch ran under.

Root lookup is `_runlog.factory_root()`, so `FACTORY_ROOT` wins and a worktree
resolves like a normal checkout. A root that cannot be found at all is not an
error here: this repo's own copy answers and nothing about the decision
changes."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "fact_rule.py"
LOCAL = HERE / "fact_rule.py"


def shared_path():
    """The root's copy, or None when the root cannot be found or has not got
    the module yet."""
    try:
        path = factory_root() / SHARED_REL
    except RuntimeError:
        return None
    return path if path.is_file() else None


def _load():
    path = shared_path()
    if path is None:
        import fact_rule as mod
        return mod
    spec = importlib.util.spec_from_file_location("fact_rule_shared", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ORIGIN = str(path)
    return mod


fact_rule = _load()
