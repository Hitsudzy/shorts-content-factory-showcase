"""CF-0433: the one place in this repo that reaches the factory's score model
(`<root>/shared/score/score.py`, CF-0432) and the three rules of this stage
that stopped refusing and started costing points.

    import _score
    findings = rhythm.pace_findings(...) + rhythm.hold_band_findings(...) \
        + [...low similarity...]
    block = _score.score_block(findings)     # -> plan["score"]

Root lookup is `_runlog.factory_root()`'s, for the same reason: from the
normal checkout (`agents/video-editor/scripts/`) and from a worktree
(`agents/video-editor/.claude/worktrees/<x>/scripts/`) the walk up this file's
ancestors reaches the real root, and `FACTORY_ROOT` wins when it holds the
module. Video Editor's own tests point `FACTORY_ROOT` at a synthetic root
without `shared/score/`; the walk then finds the real checkout above, exactly
as the runlog shim does (CF-0125's lesson: resolve by the real checkout, never
by a sibling path that a worktree does not have).

When the module cannot be found at all (this repo copied somewhere on its
own), `score_block()` still returns the findings, with `score: null` and the
reason in `error` - a plan is never lost to its bookkeeping, and nothing here
refuses on a score it could not compute.

The similarity floor lives here and nowhere else (CF-0433 item 3): it was
spelled twice, `resolve_anchors.DEFAULT_MIN_SCORE` and
`build_render_plan.DEFAULT_SIMILARITY_FLOOR`, kept equal by a test. Both names
are aliases of `SIMILARITY_FLOOR` now. It is the price table's own number:
`score.low_similarity` is "similarity of the picture to its phrase under 0.22".
"""
import os
import sys
from pathlib import Path

SCORE_REL = Path("shared") / "score" / "score.py"

# The rules this stage reports (shared/gate-prices.json -> rules["score.*"]).
RULE_PACE_BELOW_FLOOR = "score.pace_below_floor"
RULE_HOLD_BAND_EXCEEDED = "score.hold_band_exceeded"
RULE_LOW_SIMILARITY = "score.low_similarity"
STAGE_RULES = (RULE_PACE_BELOW_FLOOR, RULE_HOLD_BAND_EXCEEDED, RULE_LOW_SIMILARITY)

# CF-0290's floor, CF-0433's price line. A picture under it is admitted only
# when nothing at or above it fills the block, and costs `low_similarity`.
SIMILARITY_FLOOR = 0.22

HOOK_SECONDS = 5.0


def factory_root():
    """The root that holds shared/score/score.py, or None."""
    env = os.environ.get("FACTORY_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if (root / SCORE_REL).is_file():
            return root
    for p in Path(__file__).resolve().parents:
        if (p / SCORE_REL).is_file():
            return p
    return None


_MOD = None
_ERR = None


def module():
    """shared/score/score.py as a module, or None (the reason in `error()`)."""
    global _MOD, _ERR
    if _MOD is not None or _ERR is not None:
        return _MOD
    root = factory_root()
    if root is None:
        _ERR = f"score model not found: no ancestor of {Path(__file__).parent} holds {SCORE_REL}"
        return None
    lib = str(root / SCORE_REL.parent)
    if lib not in sys.path:
        sys.path.insert(0, lib)
    try:
        import score as mod  # noqa: E402
    except Exception as exc:  # a broken module must not lose a plan
        _ERR = f"cannot import {lib}/score.py ({exc})"
        return None
    _MOD = mod
    return mod


def error():
    module()
    return _ERR


# CF-0791: the root's shot rule before the cut (`shared/score/shot_guard.py`),
# beside the score model and found the same way - the root that holds
# score.py holds it too, so the Editor's pre-cut filter and the root's offline
# `shot_guard.py measure` read one copy of the rule.
SHOT_GUARD_REL = SCORE_REL.parent / "shot_guard.py"
_GUARD = None
_GUARD_ERR = None


def shot_guard():
    """shared/score/shot_guard.py as a module, or None (the reason in
    `shot_guard_error()`). None never refuses anything: a root older than
    CF-0791, or a broken module, leaves the pre-cut filter as it was."""
    global _GUARD, _GUARD_ERR
    if _GUARD is not None or _GUARD_ERR is not None:
        return _GUARD
    root = factory_root()
    if root is None or not (root / SHOT_GUARD_REL).is_file():
        _GUARD_ERR = (f"shot guard not found: {SHOT_GUARD_REL} is not in "
                      f"{root or 'any ancestor of ' + str(Path(__file__).parent)}")
        return None
    lib = str(root / SHOT_GUARD_REL.parent)
    if lib not in sys.path:
        sys.path.insert(0, lib)
    try:
        import shot_guard as mod  # noqa: E402
    except Exception as exc:  # a broken module must not lose a plan
        _GUARD_ERR = f"cannot import {lib}/shot_guard.py ({exc})"
        return None
    _GUARD = mod
    return mod


def shot_guard_error():
    shot_guard()
    return _GUARD_ERR


_RULES = None


def has_rule(name):
    """CF-0416: True when the factory's price table carries `name`. A rule a
    detector would like to report but the table does not price yet is left
    out of the log rather than raising `no such rule` (score.score) - the
    table is the root's, and a missing price is said in the task report, not
    guessed here. False when the model cannot be reached at all."""
    global _RULES
    if _RULES is None:
        mod = module()
        try:
            _RULES = frozenset(mod.load_model(None)["rules"]) if mod else frozenset()
        except Exception:  # a broken table: nothing is priced from here
            _RULES = frozenset()
    return name in _RULES


def finding(rule, where=None, units=1, hook=False, source="metric", note=None):
    """score.finding()'s shape, built without the module so that a checkout
    without the root still records what it found."""
    return {"rule": rule, "where": dict(where or {}), "units": units,
            "hook": bool(hook), "source": source, "note": note}


def in_hook(t):
    try:
        return t is not None and float(t) < HOOK_SECONDS
    except (TypeError, ValueError):
        return False


def score_block(findings, ledger=None):
    """`{"findings": [...], **score.score(findings)}` - the block a plan (and a
    plan_check verdict) carries. `score: null` + `error` when the model is not
    reachable; `score.ScoreModelError` (an unknown rule, a broken table) is
    raised, as the model wants: a rule the price table does not carry is a bug
    the log must not hide."""
    findings = list(findings or [])
    mod = module()
    if mod is None:
        return {"findings": findings, "score": None, "passed": None, "error": error()}
    # score() takes a loaded model; a ledger (path, or the raw table as a
    # dict - it also has `rules`) is loaded first.
    model = (ledger if isinstance(ledger, dict) and "threshold" in ledger
             else mod.load_model(ledger))
    res = mod.score(findings, model)
    return {"findings": findings, **res}


def refuses(block):
    """True only when the score was computed and fell under the threshold (or
    hit the hard list). A missing score never refuses."""
    return bool(block) and block.get("score") is not None and block.get("passed") is False


def lines(block, title=None):
    """The score log as text lines, for a refusal's findings or a report."""
    if not block or block.get("score") is None:
        return [f"score not computed: {(block or {}).get('error')}"]
    mod = module()
    return mod.render(block, title) if mod else []
