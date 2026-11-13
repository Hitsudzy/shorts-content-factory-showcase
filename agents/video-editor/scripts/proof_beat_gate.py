#!/usr/bin/env python3
"""CF-0193: may a video ship with a proof that was ordered and never arrived.

The gate, kept out of proof_layer.py the way CF-0137's assetless_rung.py is
kept out of meme_layer.py, and for the same two reasons: a layer plans and a
gate refuses, and build_render_plan.py's deficit writers are named alike so
that a refusal can be recognised as one without reading the module it came
from (CF-0139's rule, `tests/test_rotation_shortage_refusal.py`).

The ladder
----------
A proof whose beat cannot be located climbs, in this order:

  1. the equal-length window - `meme_layer._window_match()`, CF-0064's rule
     unchanged: 0.6 of the beat's words in the right order and position.
  2. the drift-tolerant pass - `meme_layer._drift_match()`, CF-0193. The
     window cannot survive the alignment being a word longer or shorter than
     the beat, and that is what actually happens: of the four beats in the
     corpus this layer could not locate, all four were in the script
     character for character and none differed by a single letter.
  3. shipping without the proof, **in writing** - `proof_layer.
     proof_shortfalls()` with `decision: ship_without_proof`, a code and,
     for the beat diagnoses, the fragment searched for and the nearest
     fragment heard. This is the rung that did not exist: before CF-0193 an
     unlocatable beat ended `beat_not_found` with `attempted: []`, one
     sentence in the plan's notes, and the video shipped as a normal video.
     Two of the three proofs ever ordered ended exactly there.
  4. the refusal - `judge()` below returning `passed: False`, `sys.exit(2)`
     in build_render_plan.py, no plan file and a `plan.proof-beat.json`
     deficit in its place.

Why rung 4 is narrow
--------------------
`proof_layer.REFUSAL_OUTCOMES` is two codes, not every way a proof can fail:
`fact_not_found` (the script carries no fact for the document to
be evidence of - CF-0223's word, CF-0243's migration off the cancelled
`check_not_found`) and `beat_missing_in_script` (the fact names a sentence
the video never says). Both say the request points at something that does
not exist, and no rung below can conjure it. They are two codes and not one
on purpose: "the script has no fact" is fixed in the script's fact and "the
video never says the fact's beat" is fixed in the narration, and one word
for two questions is what CF-0235 spent a day undoing.

The third state is deliberately *not* here: a beat the script does say and
the alignment lost (`beat_unmatched_in_alignment`) is ours, measurable and
shippable, and it stays on rung 3. Everything else - the channel switch, an incomplete
source, no free block, a capture chain walked and empty, and the alignment
losing words the script does have - is a fact about this run that rung 3
records; refusing over those would be refusing a video for being made on a
Tuesday, and CF-0137's own narrowness is the precedent.

Boolean, with no threshold, for CF-0137's reason: the request points at
nothing or it does not, and a share-of-requests threshold would be a constant
nobody measured guarding a defect everybody agrees is a defect.
"""
import json
from pathlib import Path

import proof_layer


def report_lines(shortfalls):
    """The stderr lines for a refusal, in the shape assetless_rung and
    source_gate write theirs."""
    out = []
    for sf in shortfalls:
        # CF-0243: no id of what the proof supports - a script carries one
        # fact (`production_fact`, any kind since CF-0439), so the code and the note are the whole address.
        out.append(f"proof {sf['proof_id']}: {sf['code']} - {sf['note']}")
    return out


def write_deficit(output, shortfalls):
    """The refused plan's deficit beside where the plan would have been
    (`plan.proof-beat.json`), the same move CF-0118 and CF-0137 make: on a
    refusal there is no plan file, so the record that names the reason has to
    live somewhere a reader can find without parsing stderr."""
    p = Path(output)
    path = p.with_name(f"{p.stem}.proof-beat.json")
    try:
        json.dump({"proof_shortfalls": shortfalls,
                   "proof_not_delivered": proof_layer.proof_not_delivered_code(shortfalls),
                   "proof_delivered_fully": not shortfalls}, open(path, "w"), indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def refusals(shortfalls):
    """The shortfalls the CF-0137 ladder refuses the plan over - see
    proof_layer.REFUSAL_OUTCOMES. A list rather than a boolean so the refusal can name
    every request it is refusing over, the way CF-0118 and CF-0137 do."""
    return [s for s in shortfalls if s.get("decision") == proof_layer.DECISION_REFUSE]


def judge(requested, delivered):
    """`{passed, refusals, shortfalls}` for one video's proof pair.

    `passed` is False only when a refusal-grade shortfall is present - the
    record always says what else fell short, because a gate that only speaks
    when it refuses leaves the ordinary shortfall unrecorded, which is the
    defect CF-0193 was filed for."""
    short = proof_layer.proof_shortfalls(requested, delivered)
    ref = refusals(short)
    return {"passed": not ref, "refusals": ref, "shortfalls": short}
