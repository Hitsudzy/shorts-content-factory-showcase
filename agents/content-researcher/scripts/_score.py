"""CF-0433: the Content Researcher's one door to the factory's score model
(`<root>/shared/score/score.py`, CF-0432; prices in `shared/gate-prices.json`,
`docs/score-model.md`).

The grill of 2026-09-29 ("делать из того, что дают") turned three rules this
stage used to refuse on - the pace floor, the hold band and the similarity
floor 0.22 - into prices. The Video Editor charges them on the real wav
(`build_render_plan.py`, `plan.json -> score`); this stage reads the same rules
off its estimate before the TTS (`plan_blocks.score_findings()`, the replay of
`check_block_capacity.py`) and records them with the same model, so the
writer sees the bill the Editor will write. None of the three can take a video
under N on its own, so this stage never refuses on them: the score is
recorded, the refusal - if the whole video's score falls under N - is the
Editor's, after the voice.

N is the table's `score.threshold` (read by the root model, never here): 40
since CF-0462 (signed 2026-10-01), 60 before. The arithmetic behind "cannot
take a video under N": the stage's prices cap at 12 + 10 + 15 = 37, and with
`block_band_exceeded` (CF-0447, cap 10) at 47. At N = 60 that was 37 of the 40
points above N - and 47 > 40 once CF-0447 added the fourth price, so between
CF-0447 and CF-0462 the stage's prices together could, in principle, take a
video under N. At N = 40 they are 47 of the 60 points above N: the claim holds
again, for all four together.

Root lookup: `FACTORY_ROOT` when it holds the module, else the nearest
ancestor of this file that does (the normal checkout and a worktree both reach
the real root). No root, no model: `score_block()` still returns the findings,
with `score: null` and the reason in `error` - a record is never lost to its
bookkeeping, and nothing here refuses on a score it could not compute.

Stdlib only.
"""
import os
import sys
from pathlib import Path

SCORE_REL = Path("shared") / "score" / "score.py"

RULE_PACE_BELOW_FLOOR = "score.pace_below_floor"
RULE_HOLD_BAND_EXCEEDED = "score.hold_band_exceeded"
RULE_LOW_SIMILARITY = "score.low_similarity"
# CF-0447: more blocks than the top of the pattern's block band - a price per
# block over the top (the user's decision of 2026-09-30), not a refusal.
RULE_BLOCK_BAND_EXCEEDED = "score.block_band_exceeded"
STAGE_RULES = (RULE_PACE_BELOW_FLOOR, RULE_HOLD_BAND_EXCEEDED, RULE_LOW_SIMILARITY,
               RULE_BLOCK_BAND_EXCEEDED)

HOOK_SECONDS = 5.0
ESTIMATE_BEFORE_TTS = "before_tts"


def factory_root():
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
    except Exception as exc:  # noqa: BLE001 - a broken module must not lose a record
        _ERR = f"cannot import {lib}/score.py ({exc})"
        return None
    _MOD = mod
    return mod


def error():
    module()
    return _ERR


def finding(rule, where=None, units=1, hook=False, note=None, source="metric",
            estimate=ESTIMATE_BEFORE_TTS):
    """score.finding()'s shape, plus `estimate` - this stage measures before
    the voice exists."""
    out = {"rule": rule, "where": dict(where or {}), "units": units, "hook": bool(hook),
           "source": source, "note": note}
    if estimate:
        out["estimate"] = estimate
    return out


def in_hook(t):
    try:
        return t is not None and float(t) < HOOK_SECONDS
    except (TypeError, ValueError):
        return False


def score_block(findings):
    """`{"findings": [...], **score.score(findings)}`, or `score: null` with
    `error` when the model is not reachable. An unknown rule raises, as the
    model wants: a rule the price table does not carry is a bug."""
    findings = list(findings or [])
    mod = module()
    if mod is None:
        return {"findings": findings, "score": None, "passed": None, "error": error()}
    return {"findings": findings, **mod.score(findings)}


SIGNED, PROPOSED = "signed", "proposed"


def rule_price(name, ledger=None):
    """CF-0547: `(status, price)` of one rule in the root's price table.

    `("signed", penalty)` when `rules` carries it - the row the model charges
    (`{price, per, cap, hook_mult, ...}`); `("proposed", proposed)` when only
    `proposals.rows` does (CF-0472: a price offered for the user's signature
    and NOT in force - nothing charges on it, a stage may only say what it
    would cost); `(None, None)` when neither does or the table cannot be read.
    `ledger` is a path or an already-read dict (tests)."""
    mod = module()
    try:
        d = ledger if isinstance(ledger, dict) else (mod.read_ledger(ledger) if mod else None)
    except Exception:  # noqa: BLE001 - an unreadable table prices nothing from here
        d = None
    if not isinstance(d, dict):
        return None, None
    row = (d.get("rules") or {}).get(name)
    if isinstance(row, dict) and row.get("mode") == "penalty" and \
            isinstance(row.get("penalty"), dict):
        return SIGNED, dict(row["penalty"])
    prop = ((d.get("proposals") or {}).get("rows") or {}).get(name)
    if isinstance(prop, dict) and isinstance(prop.get("proposed"), dict):
        return PROPOSED, dict(prop["proposed"])
    return None, None


def below_threshold(block):
    """True only when a score was computed and fell under N (or hit the hard
    list). A missing score never counts as under."""
    return bool(block) and block.get("score") is not None and block.get("passed") is False


def summary_line(block, ledger=None):
    """CF-0434: the factory's one line of a score block - the root's
    `score.summary_line()` (`B · 74 — −9 похожесть (3 блока), ...`, the same the
    Video Editor prints); `summary()` below when the root model cannot be
    loaded or fails on the block."""
    mod = module()
    fn = getattr(mod, "summary_line", None) if mod is not None else None
    if fn is not None:
        try:
            return fn(block, ledger)
        except Exception:  # noqa: BLE001 - a line must not lose a record
            pass
    return summary(block)


def summary(block):
    """One line: `92/100 (S) - pace_below_floor -4, hold_band_exceeded -2`."""
    if not isinstance(block, dict) or block.get("score") is None:
        return f"score not computed: {(block or {}).get('error')}"
    parts = [f"{rule.split('.', 1)[-1]} {agg.get('charged')}"
             for rule, agg in (block.get("by_rule") or {}).items() if agg.get("charged")]
    head = f"{block['score']}/{block.get('start')} ({block.get('tier')}, N={block.get('threshold')})"
    return head + (" - " + ", ".join(parts) if parts else " - no penalty")
