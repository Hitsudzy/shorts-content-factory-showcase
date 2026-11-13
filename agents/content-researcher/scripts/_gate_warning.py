"""CF-0330: the pool gates of step 6 warn instead of refusing.

On 2026-09-23 two videos the user had accepted for publication were rebuilt on
the current code and both were refused before the render: `everyday-sorcery-2`
by `anchor_preflight` (one anchor with no survivor, best candidate 0.2198
against a floor of 0.22) and `widows-bay` by `assetless_rung` (3 of 24 blocks
with no picture). The user's answer, in chat: none of the three prices is
signed - `anchor_preflight` / `pool_too_thin`, `assetless_rung` /
`pattern_undeliverable` and `two_source_gate` all go back to a warning. The
Video Editor carries that decision in `plan_refusal.WARN_GATES`; this module is
the Content Researcher's half of it, because this stage runs the same
questions before the TTS and used to refuse (or send back for a rewrite) the
very scripts the Editor now lets through.

A warned gate writes the *same* numbers and the same funnel code a refusal
would, with `severity: "warn"` and the decision it rests on, into the batch
file's `warnings[]` - the list this stage already keeps for what the batch was
made in spite of (CF-0185; `merge_batch_file.py` merges it by
`topic_id` + `warning_code` + `gate`). The script stays in `scripts[]`, the
exit is 0, and the run goes on. Nothing is rewritten on a warning: the rewrite
the old ladder asked for was the price the user did not sign.

`WARN_GATES` is the switch, in one place: a gate removed from it goes back to
the ladder it had (the ladder code is kept, not deleted). The two-source gate
is not in it: that gate's mode is the channel's
(`channels/<channel>.json` -> `video_editor.two_source_gate`), and
`check_two_sources.py` follows the channel - `measure` warns, `enforce`
refuses - exactly as the Editor does, so the channel file never lies.

Stdlib only.
"""

SEVERITY_WARN = "warn"
ACTION_WARN = "warn"
WARNINGS_FIELD = "warnings"
DECISION = "CF-0330: the user, 2026-09-23 - a warning, not a refusal"

# This stage's gates, by the id each one writes into its warning.
GATE_ANCHOR_COVERAGE = "anchor_coverage"        # the preflight's verdict (weak/absent/contention)
GATE_ANCHOR_POOL = "anchor_coverage_pool"       # the pool's margin over the anchors (CF-0274)
GATE_BLOCK_CAPACITY = "block_capacity"          # blocks the pool cannot fill (CF-0284)
GATE_ALTERNATE_SIDES = "alternate_sides"        # a side that cannot carry its slots (CF-0285)
GATE_TWO_SOURCES = "two_source_spread"          # one source on screen (CF-0280), channel's mode
GATE_EVENT_FOOTAGE = "event_footage"           # the event's own footage under its words (CF-0575)

# The Video Editor gate each of them predicts - what the warning is about in
# the Editor's words, so a reader can join the two stages' records.
EDITOR_GATE = {
    GATE_ANCHOR_COVERAGE: "anchor_preflight",
    GATE_ANCHOR_POOL: "anchor_preflight",
    GATE_BLOCK_CAPACITY: "assetless_rung",
    GATE_ALTERNATE_SIDES: "assetless_rung",
    GATE_TWO_SOURCES: "two_source_gate",
    GATE_EVENT_FOOTAGE: "event_footage",
}

WARN_GATES = frozenset({GATE_ANCHOR_COVERAGE, GATE_ANCHOR_POOL,
                        GATE_BLOCK_CAPACITY, GATE_ALTERNATE_SIDES,
                        GATE_EVENT_FOOTAGE})


def warns(gate):
    """Whether this gate warns instead of refusing (CF-0330)."""
    return gate in WARN_GATES


def entry(topic_id, script_id, gate, warning_code, detail, numbers=None):
    """One `warnings[]` entry: the batch file's contract (`topic_id`,
    `warning_code`, `detail`) plus the gate, the numbers and the decision."""
    return {
        "topic_id": topic_id,
        "script_id": script_id,
        "warning_code": warning_code,
        "gate": gate,
        "editor_gate": EDITOR_GATE.get(gate),
        "severity": SEVERITY_WARN,
        "decision": DECISION,
        "detail": f"{script_id}: {detail}",
        "numbers": numbers or {},
    }


def _key(w):
    return (w.get("topic_id"), w.get("warning_code"), w.get("gate"))


def record(data, entries):
    """Write `entries` into `data["warnings"]` in place: an entry for the same
    topic, code and gate is replaced where it stands, anything else is
    appended. The field is created (`[]` at least) so the file says there was
    nothing to warn about rather than not saying."""
    current = data.get(WARNINGS_FIELD)
    if not isinstance(current, list):
        current = []
    index = {_key(w): i for i, w in enumerate(current) if isinstance(w, dict)}
    for e in entries:
        k = _key(e)
        if k in index:
            current[index[k]] = e
        else:
            index[k] = len(current)
            current.append(e)
    data[WARNINGS_FIELD] = current
    return current


def clear(data, topic_ids, gate):
    """Drop this gate's earlier warnings for topics it has just judged again -
    a script that passes now must not keep a warning an earlier run wrote."""
    current = data.get(WARNINGS_FIELD)
    if not isinstance(current, list):
        return
    ids = set(topic_ids)
    data[WARNINGS_FIELD] = [w for w in current
                            if not (isinstance(w, dict) and w.get("gate") == gate
                                    and w.get("topic_id") in ids)]


def line(e):
    """The operator's one line for a warned gate."""
    return (f"  WARNING (the script goes on): {e.get('script_id')} "
            f"[{e.get('warning_code')}/{e.get('gate')}] {e.get('detail')}")


NOT_RECORDED = ("  note: {n} warning(s) printed but not recorded - re-run with --write so "
                "`warnings[]` of the batch file carries them")
