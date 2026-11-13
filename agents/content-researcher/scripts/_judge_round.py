"""CF-0902: in the round after the frame judge, the first pass's scripts are
decided - this stage's gates neither judge nor re-plan them.

Why (batch `example-film/2026-10-30T1033Z`): after the frame judge refused four
videos, the reserve round brought four substitutes in (`01b ->
reserve_substitution.substitutions[]` with `at: "frame_judge_refusal"`,
CF-0798) and the Researcher's round wrote their scripts into `03`
(`merge_batch_file.py --add`). The round's gates take the whole file:
`plan_check_loop.py --write <batch>` re-planned every first-pass script
(pine-park's `work/pine-park/plan.json`, the plan its judged video was
rendered from, was overwritten two hours after the render) and
`check_claims.py --write` judged them again against that new plan - and wrote
a failing `claims_check` (`shot_not_under_words`) onto
`lf-2026-10-30-017-script1`, a script whose video the frame judge had
already refused. Nobody owns such a script any more, so nobody rewrote it, and
the root contract went red on a script whose claims did not pass sitting in
`03`. Compliance froze the first pass's verdicts the same way for the same
round (`merge_verdicts.py pending`, CF-0800), and the Video Editor renders
only what `05` names in neither `videos[]` nor `refusals[]` (CF-0802).

The rule, deterministic and reset-proof: when `01b` carries a substitution at
`frame_judge_refusal`, the round after the judge is on, and it owns only the
scripts of those substitute topics; every other script of `03` is the first
pass's and is decided. A reset that takes the round back drops those entries
(`shared/batch_control.py` STALE_BLOCKS, CF-0784), so a re-run of the first
pass is never mistaken for this round. Before the judge (the main round, the
late reserve round) nothing is frozen.

CF-0933 (batch `example-tech/2026-11-11T0956Z`, nvidia): the reserve round
before compliance - a substitution at `researcher_refusal` (CF-0306, the late
round alike) - ran `check_claims.py --write` over the whole `03` and stamped a
failing `claims_check` (`shot_not_under_words`, judged against the plan 6b of
the first pass had just built) onto `lf-2026-11-11-002-script1`, a script of
the first pass that round does not own and nobody rewrote; compliance then
blocked it as `claim_unsupported`. So every round with substitutions owns only
its substitute topics (`not_owned()`): the verdict gates do not write onto a
first-pass script - they say what they found (`NOT OWNED (fails: ...)`) and
write nothing. What the first pass's records must hold against its own plan is
the first pass's to settle, in its own 6b (`plan_check_loop.py` checks the
claims against the plan it built). The round after the frame judge keeps its
stricter rule above (`frozen()`: nothing judged at all). An `index_pass` /
`sieve` substitution is not a round: the Indexer's own passes refill a slot
before this stage ever runs, and the first pass writes those topics itself.
"""
import json
from pathlib import Path

INDEX_FILE = "01b-footage-index.json"
SUBSTITUTION_KEY = "reserve_substitution"          # = ingest_batch.SUBSTITUTION_KEY
JUDGE_AT = "frame_judge_refusal"                   # = ingest_batch.JUDGE_AT (CF-0799)
RESERVE_AT = "researcher_refusal"                  # = ingest_batch refill_slots(..., at) (CF-0306)
TASK = "CF-0902"
NOT_OWNED_TASK = "CF-0933"


def _substitutions(batch_dir):
    """`01b -> reserve_substitution.substitutions[]` (dicts only), or []."""
    try:
        doc = json.loads((Path(batch_dir) / INDEX_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    block = doc.get(SUBSTITUTION_KEY) if isinstance(doc, dict) else None
    subs = block.get("substitutions") if isinstance(block, dict) else None
    return [s for s in subs if isinstance(s, dict)] if isinstance(subs, list) else []


def _topics_at(batch_dir, at):
    out = {s.get("topic_id") for s in _substitutions(batch_dir)
           if s.get("at") == at and s.get("topic_id")}
    return out or None


def round_topics(batch_dir):
    """The substitute topic ids of the round after the frame judge, or None
    when there is no such round in this batch (no `01b`, no substitution at
    `frame_judge_refusal`)."""
    return _topics_at(batch_dir, JUDGE_AT)


def reserve_topics(batch_dir):
    """CF-0933: the substitute topic ids of the reserve round before
    compliance (`at: researcher_refusal`, the first and the late round), or
    None when there is no such round in this batch."""
    return _topics_at(batch_dir, RESERVE_AT)


def frozen(batch_dir, scripts):
    """{script_id: why} of the scripts of `scripts` the round after the frame
    judge does not own - empty when that round is not on."""
    own = round_topics(batch_dir)
    if own is None:
        return {}
    out = {}
    for s in scripts or []:
        if not isinstance(s, dict) or not s.get("script_id"):
            continue
        if s.get("topic_id") not in own:
            out[s["script_id"]] = (
                f"a first-pass script - the round after the frame judge owns only its "
                f"substitute topics ({', '.join(sorted(own))}); this one was decided by "
                f"compliance, the Editor and the judge before it ({TASK})")
    return out


def not_owned(batch_dir, scripts):
    """CF-0933: {script_id: why} of the scripts of `scripts` the current round
    does not own - the round after the frame judge (its substitutes, as
    `frozen()`), else the reserve round before compliance (its substitutes);
    empty when no such round is on (the first pass owns everything)."""
    judged = frozen(batch_dir, scripts)
    if judged or round_topics(batch_dir) is not None:
        return judged
    own = reserve_topics(batch_dir)
    if own is None:
        return {}
    out = {}
    for s in scripts or []:
        if not isinstance(s, dict) or not s.get("script_id"):
            continue
        if s.get("topic_id") not in own:
            out[s["script_id"]] = (
                f"a first-pass script - the reserve round owns only its substitute topics "
                f"({', '.join(sorted(own))}); what this script's records hold against its "
                f"plan was the first pass's to settle in its own step 6b ({NOT_OWNED_TASK})")
    return out
