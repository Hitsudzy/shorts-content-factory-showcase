"""CF-0323: the one place in this repo that finds the production-fact refusal
rule, the same way `_runlog.py` finds the run-accounting library:

    from _factrule import fact_rule

    state = fact_rule.classify(fact_rule.answer_of_lookup(lookup, field),
                               rule.not_found_statuses)

**Why this file exists.** `fact_refusal.py` (CF-0185) and the Trend Hunter's
selection filter (`fact_probe_topics.py`, CF-0264) decided the same question -
"has this topic a production fact behind it?" - with two predicates written six
weeks apart, and the cheap one was the milder. Every topic the two disagreed
about passed selection, was judged by compliance, had its footage downloaded
and CLIPped, and was killed here afterwards. CF-0323 made the predicate one
module; this loader is how this repo reaches it.

**One copy, at the root.** The rule lives at `<root>/shared/factrule/fact_rule.py`
and this repository deliberately keeps **no** copy of it beside this file. The
Trend Hunter has one because it authored the module and lands on its own days;
the root's `tests/test_fact_rule_copies.py` holds the register of who may hold
a copy and compares every copy to the root's byte for byte, so a third copy
here would be a third dialect waiting to happen - the exact defect this task
is about.

**A root without the module is an error, and loudly.** `_runlog.py` degrades to
a silent stand-in because run accounting must never break a fetch; a predicate
is not accounting. A stand-in here could only either refuse topics with no rule
behind the refusal or carry them with no rule behind the carry, and inventing
an answer is how the two implementations drifted in the first place. Nothing is
lost by failing: `load_rule()` in `fact_refusal.py` is fail-closed on the same
root - a checkout with no factory root above it reads no channel config, gets
no rule, and refuses nothing - so the only state this raise can be reached in
is a root that has `patterns/` but not `shared/factrule/`, which is a half
checkout and not something to judge a batch under.

Root lookup is `_runlog.factory_root()`, so `FACTORY_ROOT` wins and a worktree
resolves like a normal checkout. Which file answered is written to
`fact_rule.ORIGIN`, the way the Hunter's loader does it: the module's own
default names the Hunter's path (the file at the root is that file, byte for
byte), and a reader should see the path the process actually loaded.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "fact_rule.py"


def shared_path():
    """The root's copy, or None when the root cannot be found or has not got
    the module."""
    try:
        path = factory_root() / SHARED_REL
    except RuntimeError:
        return None
    return path if path.is_file() else None


def _load():
    path = shared_path()
    if path is None:
        raise RuntimeError(
            f"the production-fact refusal rule was not found: this repository "
            f"keeps no copy of it on purpose and loads {SHARED_REL} from the "
            f"factory root (set FACTORY_ROOT, or see scripts/_factrule.py)")
    spec = importlib.util.spec_from_file_location("fact_rule_shared", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ORIGIN = str(path)
    return mod


fact_rule = _load()


# CF-0548: the rule "the fact is about the topic's own scene" lives beside the
# fact rule at the root (`shared/factrule/fact_scene.py`) and is loaded the
# same way, on first use - no copy here either.
SCENE_REL = Path("shared") / "factrule" / "fact_scene.py"
_scene_module = None


def fact_scene():
    """The root's scene-fit rule. A root without it is an error, like a root
    without the fact rule: a fact judged against no rule is not judged."""
    global _scene_module
    if _scene_module is None:
        try:
            path = factory_root() / SCENE_REL
        except RuntimeError:
            path = None
        if path is None or not path.is_file():
            raise RuntimeError(f"{SCENE_REL} was not found at the factory root (CF-0548): "
                               f"this repository keeps no copy of it")
        spec = importlib.util.spec_from_file_location("fact_scene_shared", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _scene_module = mod
    return _scene_module
