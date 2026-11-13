#!/usr/bin/env python3
"""CF-0139: the machine-readable record of what the pool was short of when the
planner refused to build a video.

This file *is* the format, the same way ledger.py is the format of the ledger:
there is no second description of these fields anywhere, because two
descriptions of one record is how they drift.

Why it is not a ledger column
-----------------------------
The refusal itself is an ordinary rejection - `rejection_reason`,
`rejection_verdict: upheld`, `rejected_at`, no new columns (CF-0139 rejected
`production_failed_at` outright). But the reason column is prose written for a
person, and the question this record has to answer is not a question prose can
answer: *when the pool is topped up, may this topic be tried again?* That is a
list of anchors with a cause each, and a CSV cell is the wrong shape for a
list. So it lives beside the ledger, keyed by the `seq` of the row it explains.

Why JSONL, and beside the ledger
--------------------------------
Same two reasons the ledger is a CSV (see ledger.py):

  * append-only has to be *visible* as an append. One refusal is one added
    line and nothing else - a JSON array would rewrite the previous line's
    comma and the closing bracket for every append.
  * a record is a nested thing (a list of anchors, each with its own cause),
    which is what a CSV cannot hold and what a line of JSON holds naturally.

`rotation/ledger/<channel>.shortages.jsonl`. A refusal writes exactly one
line; a `seq` already present is refused rather than rewritten, for the same
reason a filled ledger cell is.

The causes
----------
A closed vocabulary, and the point of the whole record. What matters is not
which rung of the CF-0137 ladder failed but *what would have to change* for
the topic to be worth trying again, so the causes are grouped by that:

  the pool would fix it (POOL_FIXABLE)

    no_footage          nothing in the pool answers this anchor at all. The
                        one cause CF-0023's shopping list is actually about.
    footage_unusable    a frame exists and cannot be taken - the asset gate,
                        cached usability, a caption crop under the floor, the
                        wrong card. Kept apart from `no_footage` on purpose:
                        of the fourteen reasons in batch 2026-09-03T2037Z,
                        thirteen were of this kind and one was the other, and
                        a record that folded them together would send the
                        operator shopping for material he already has.
    insert_below_floor  the library was offered the hole and nothing stood
                        clear of the M4 floors CF-0143 measured. Growing the
                        insert library fixes this one; more footage does not.

  the pool would not fix it

    insert_layer_off       the meme layer is off on this channel, or this
                           pattern refuses it. Configuration, not shortage.
    insert_not_applicable  the block is under the M2 length floor, the video's
                           insert budget was spent, or the block says nothing
                           an insert could be searched by.
    repeat_budget_spent    the one emergency shot repeat per video (CF-0137
                           rung 2) was already spent elsewhere.

    unclassified           the refusal arrived as prose this module could not
                           place. Explicit and counted, never folded into a
                           neighbouring cause: a classifier that guesses is
                           worse than one that says it does not know, because
                           the guess is invisible and the shopping list is
                           then wrong in a way nobody can see.

What the record notes about the pool (CF-0149)
----------------------------------------------

`pool_census` - the count of the stores this refusal waits on, as they stood
at the moment it was written. `retry_when` is the sentence a person reads;
this is the number a program subtracts from. Without it "has the pool been
topped up since?" is unanswerable after the fact, because nothing else in the
factory keeps an inventory: `01b-footage-index.json` is the list of files one
batch touched. It is ~170 bytes on the pool as it stands, and it is absent on
a refusal no shopping can fix, because such a refusal waits on a person.
See rotation/pool.py for what is counted and why it is a count and not a
digest.

Where the input comes from
--------------------------
`build_render_plan.py` exits 2 and writes `plan.assetless-rung.json` beside
where the plan would have been (CF-0137 `write_deficit()`). Today that file
carries the gate's own record: block indices and one prose `reason` per
block. Two things it does not carry, and both are asked for here:

  * the per-block *outcome codes* of the library rung - `hole_fill.refused[]`
    has them (`layer_off` / `pattern_refused` / `no_block` / `no_asset`,
    CF-0138), machine-readable already, and on a refusal they go to stderr
    and nowhere else;
  * the block's own `intent` and span, which is what makes an entry an
    *anchor* rather than an index into a plan file that was never written.

Which fact answers for the cause
--------------------------------
An anchor can arrive carrying three things that all look like a reason: the
plan builder's degradation record (`from`), the insert layer's outcome code,
and a line of prose. `classify()` reads them in the order CF-0137's ladder
ran, not in the order they are convenient: a block with a degradation record
is a hole *because its picture failed*, and rung 1's code says only that the
rescue failed too. Measured on batch 2026-09-03T2037Z, reading them the
other way round is not a nicety - the Editor's most common line ("no usable
footage for this block", the default of the `unfilled` branch) matches no
prose marker at all, so the one cause CF-0023's shopping list is about was
the one cause the record never named.

So this module reads both forms: the enriched one first (`anchors` /
`deficits` with a `cause` already on them, and a `hole_fill` node), and the
current one by classifying the prose. The exact patch that would make the
Editor write the enriched form is in tasks/CF-0139-planner-refusal-in-ledger.md
- it belongs to agents/video-editor, which is a repository of its own.

The fact that splits the footage pair (CF-0150)
-----------------------------------------------
None of the three above can answer the one question `no_footage` versus
`footage_unusable` actually asks - *was there ever a picture to fall with*.
`from` says which rung the block fell from, and a block whose single offer
scored 0.116 and a block whose two good offers were refused by the usability
gate both fall from the same rung and read identically. Before CF-0150 this
module answered that question by a default (`unfilled` -> `no_footage`,
anything else -> `footage_unusable`), which is a guess dressed as a fact: on
batch 2026-09-03T2037Z the default was wrong on 27 of the 51 anchors.

So the Editor now measures it where the candidates are actually ranked and
writes it on the anchor as `candidate_supply`
(agents/video-editor/scripts/resolve_anchors.py::candidate_supply()). It has
three states and all three are different, which is why it is read by key
presence and not by `.get()`:

  key absent      the plan predates CF-0150. Nothing is inferred; the anchor
                  is classified exactly as it was before.
  value null      the pool offered a frame on topic and it was used, so this
                  hole is not a want of material - `no_footage` is then
                  impossible and only `footage_unusable` is left of the pair.
  value an object `code` says why the pool did not deliver:
                  `pool_offered_nothing` (nothing was even ranked) and
                  `pool_offered_off_topic` (ranked, and the best of them under
                  the match threshold) are `no_footage` - the remedy is
                  material, not a looser gate; `pool_offered_refused` (a
                  candidate stood at or over the threshold and the gates took
                  it) is `footage_unusable`.

A code outranks the degradation record and the prose both, because it is a
measurement of the pool and they are inferences about it. It does not outrank
the *other* causes: the insert-layer codes answer a question about the library
and are left where they are (see `classify()`).
"""
import json
import re
import sys
from pathlib import Path

# CF-0231: the directory this file lives in, registered before a neighbour is
# named. Bare `import pool` worked only while somebody else had already put
# rotation/ on sys.path - true of `python3 rotation/rotate.py ...` (the
# interpreter puts a script's own directory there) and of the root suite, and
# false of every other way of loading this file. agents/video-editor's
# tests/test_deficit_anchors.py runs this reader over the deficit file the
# Editor writes, loading it with spec_from_file_location by path, and got
# ModuleNotFoundError instead of a reader. Same form as rotate.py's
# `ROOT / "patterns"` line and pool.py's `_inserts_lib()`: compute the
# directory from __file__, register it if it is not there, then import by
# name - never assume somebody upstream did it.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pool  # noqa: E402 - after the sys.path line above, on purpose

KIND = "assetless_blocks_refused"

CAUSES = (
    "no_footage",
    "footage_unusable",
    "insert_below_floor",
    "insert_layer_off",
    "insert_not_applicable",
    "repeat_budget_spent",
    "unclassified",
)

# The causes a fuller pool would answer. `unclassified` is deliberately not
# here: an unknown cause is not a promise that shopping helps.
POOL_FIXABLE = ("no_footage", "footage_unusable", "insert_below_floor")

# meme_layer.py's outcome codes (CF-0138), which are already a closed list on
# the Editor's side. `no_asset` splits in two here, because it covers both "the
# library had candidates and none cleared the floor" and "this block gave the
# search nothing to go on" - one is fixed by a bigger library, the other by
# nothing at all.
INSERT_OUTCOMES = {
    "layer_off": "insert_layer_off",
    "pattern_refused": "insert_layer_off",
    "no_block": "insert_not_applicable",
    "no_asset": "insert_below_floor",
}
NOTHING_TO_EMBED = "says nothing about what it wanted to show"

# The two causes a degradation record can carry. `build_render_plan.py` writes
# one per block that fell to the assetless rung, and its `from` is the only
# machine-readable thing anyone knows about *why* the block is a hole:
# `unfilled` is an anchor the resolver could not fill at all (CF-0085's
# `unfilled_block()`), any other value is the kind of picture the block was
# built with and then lost. Both are footage facts, which is why they are the
# footage family and nothing else.
FOOTAGE_CAUSES = ("no_footage", "footage_unusable")
DEGRADED_FROM_UNFILLED = "unfilled"

# CF-0150. The Editor's supply codes (`CANDIDATE_SUPPLY_CODES` in
# agents/video-editor/scripts/resolve_anchors.py) and the cause each one means
# here. A closed list on that side, mapped whole on this one -
# test_every_supply_code_the_editor_can_write_has_a_cause holds the two ends
# together, the same way the meme-layer outcomes are held.
SUPPLY_CAUSES = {
    "pool_offered_nothing": "no_footage",
    "pool_offered_off_topic": "no_footage",
    "pool_offered_refused": "footage_unusable",
}

# The three states as they are written onto an anchor of this record. The
# Editor's null is not a code and needs a name here, because "the pool
# delivered" and "nobody measured" have to stay apart in the record too - a
# shopping list cannot be re-derived from a field that folded them.
SUPPLY_DELIVERED = "pool_delivered"
SUPPLY_UNKNOWN = ""
SUPPLY_STATES = (SUPPLY_UNKNOWN, SUPPLY_DELIVERED) + tuple(sorted(SUPPLY_CAUSES))


class _SupplyAbsent:
    """`candidate_supply` was not on the anchor at all.

    A sentinel rather than `None`, because `None` is one of the three states
    and the most easily lost of them: `d.get("candidate_supply")` answers it
    for a plan that predates CF-0150 as well, and the two mean opposite
    things ("the pool delivered" against "nobody looked"). Read by key
    presence, kept apart by this.
    """
    __slots__ = ()

    def __repr__(self):
        return "SUPPLY_ABSENT"


SUPPLY_ABSENT = _SupplyAbsent()

# Prose markers, in the order they are tried. A reason that names a frame and
# says why it could not be taken is `footage_unusable`; only a reason with no
# frame in it at all is `no_footage`.
_MARKERS = (
    ("repeat_budget_spent", (
        "emergency repeat", "emergency reuse", "repeat budget", "reuse budget",
        "no repeat is left", "no emergency")),
    ("footage_unusable", (
        "asset gate", "usability", "caption crop", "cannot be supplied",
        "is rejected on", "unusable", "not the card", "substituted",
        "too dark", "black bars")),
    ("insert_below_floor", (
        "clear of the field", "m4", "library", "similarity")),
    ("no_footage", (
        "no picture at all", "no shot", "nothing in the pool", "pool has no",
        "never arrived", "no candidate", "unresolved anchor", "resolved to nothing")),
)


class ShortageError(Exception):
    """A write that would break the append-only invariant of the log."""


def _from_prose(reason):
    """The cause the Editor's prose names, or None when it names none."""
    text = (reason or "").lower()
    if not text.strip():
        return None
    for cause, markers in _MARKERS:
        if any(m in text for m in markers):
            return cause
    return None


def supply_code(candidate_supply):
    """The Editor's `code` on one anchor's supply fact, or None.

    None for every state that is not a code: the key absent, the pool having
    delivered, and a malformed value. Callers that need the three states apart
    test the value itself against `SUPPLY_ABSENT` / `None`.
    """
    if isinstance(candidate_supply, dict):
        return str(candidate_supply.get("code") or "").strip() or None
    return None


def supply_state(candidate_supply):
    """One of `SUPPLY_STATES` - how this anchor's supply fact is recorded."""
    if candidate_supply is SUPPLY_ABSENT:
        return SUPPLY_UNKNOWN
    if candidate_supply is None:
        return SUPPLY_DELIVERED
    return supply_code(candidate_supply) or SUPPLY_UNKNOWN


def classify(reason, outcome=None, note=None, degraded_from=None,
             candidate_supply=SUPPLY_ABSENT):
    """The cause of one unresolved anchor, machine facts before prose.

    Four sources, and the order between them is the whole of this function:

    `candidate_supply` first, when it carries a code (CF-0150). It is the
    only one of the four that was *measured* rather than inferred: the Editor
    counted, at the point the candidates were ranked, what the pool offered
    this anchor and what became of it. So it settles the footage pair
    outright - `pool_offered_nothing` and `pool_offered_off_topic` are
    `no_footage`, `pool_offered_refused` is `footage_unusable` - and it
    settles it against the degradation record and against the prose both.
    This is a changed answer, not only a sharper one: on batch
    2026-09-03T2037Z 27 of 51 anchors fell from `unfilled`, which the default
    below reads as `no_footage`, while the pool had in fact offered frames on
    topic and the gates had taken them. Those are `footage_unusable`, and a
    shopping list that asked for material to fill them would be asking for
    material the operator already owns.

    A supply fact of `null` - the pool delivered a frame on topic and it was
    used - is not a cause of its own but it *rules one out*: whatever put this
    block in the deficit, it was not a want of material, so `no_footage`
    cannot be the answer and `footage_unusable` is the whole of the pair. It
    does not reach past the pair: an anchor whose hole the insert layer
    answers for (`outcome` below) keeps that cause - "the meme layer is off"
    stays configuration rather than shortage, and folding it into the footage
    family would put a topic on the shopping list that no shopping helps.
    A code, by contrast, does reach past it, for the same reason the
    degradation record does: the block has no picture *because the pool had
    none to give*, and rung 1's code says only that the rescue failed too.

    An unrecognised code decides nothing and the sources below answer instead
    - same as an unrecognised `outcome`. A fourth code appearing on the
    Editor's side is caught by a test here, not by a silent guess in a record.

    `degraded_from` second. A degradation record on the block says this hole
    is a hole *because its picture failed* - that is CF-0137's ladder read in
    the order it ran, and it is a fact from the plan builder rather than a
    reading of prose. So an anchor that carries one is a footage anchor, and
    the only question left is which of the two footage causes it is:
    `unfilled` means the anchor resolved to nothing (`no_footage`), any other
    kind means a picture was designated and lost (`footage_unusable`). Prose
    may refine *within* that pair - a reason that names an asset gate on an
    `unfilled` block is the more precise answer - and may not leave it.

    `outcome` third, and only for an anchor with no degradation record.
    meme_layer's codes are a closed list and beat prose, but they answer a
    different question: whether rung 1 could *rescue* a hole, not why the
    hole is there. Letting them answer for a block whose footage is known to
    have failed is how a shortage becomes `insert_layer_off` ("configuration,
    not shortage") and drops out of CF-0023's shopping list while the video
    still has no picture in it.

    Prose last, and `unclassified` when it says nothing this module can place.
    """
    measured = SUPPLY_CAUSES.get(supply_code(candidate_supply))
    if measured:
        return measured
    # Key present and null: the pool delivered, so the hole is not a want of
    # material and `no_footage` is off the table wherever the pair applies.
    delivered = (candidate_supply is not SUPPLY_ABSENT
                 and candidate_supply is None)

    kind = (degraded_from or "").strip().lower()
    if kind:
        if delivered:
            return "footage_unusable"
        prose = _from_prose(reason)
        if prose in FOOTAGE_CAUSES:
            return prose
        return ("no_footage" if kind == DEGRADED_FROM_UNFILLED
                else "footage_unusable")
    if outcome:
        cause = INSERT_OUTCOMES.get(str(outcome).strip())
        if cause == "insert_below_floor" and note and NOTHING_TO_EMBED in note:
            return "insert_not_applicable"
        if cause:
            return cause
    cause = _from_prose(reason)
    if delivered and cause in (None, "no_footage"):
        # Nothing outside the footage pair answers for this hole, and the one
        # measured fact there is says a frame arrived. That is the definition
        # of `footage_unusable`, and it beats both the silence and a line of
        # prose that says the pool had nothing - it demonstrably had.
        return "footage_unusable"
    return cause or "unclassified"


def _anchor(index, reason, intent=None, start=None, end=None, degraded_from=None,
            cause=None, outcome=None, note=None, candidate_supply=SUPPLY_ABSENT):
    seconds = None
    if start is not None and end is not None:
        seconds = round(float(end) - float(start), 3)
    cause = (cause if cause in CAUSES
             else classify(reason, outcome, note, degraded_from, candidate_supply))
    evidence = candidate_supply if isinstance(candidate_supply, dict) else {}
    return {
        "block_index": int(index),
        "intent": intent or "",
        "start": None if start is None else round(float(start), 3),
        "end": None if end is None else round(float(end), 3),
        "seconds": seconds,
        "cause": cause,
        "degraded_from": degraded_from or "",
        # Kept even when it did not decide the cause. On a footage anchor the
        # rung-1 code is the second half of the story (the rescue that was
        # tried and failed), and dropping it here would put it back where
        # CF-0139 found it: printed to stderr on a run with no plan file.
        "insert_outcome": str(outcome or "").strip(),
        # CF-0150. The measured state of the pool for this anchor, kept on the
        # record whether or not it decided the cause: `""` when the plan
        # predates the fact, `pool_delivered` when the pool delivered, one of
        # the Editor's three codes when it did not. Without it the record says
        # `no_footage` and cannot say whether that is a measurement or the old
        # default, which is exactly the doubt CF-0150 exists to end.
        "candidate_supply": supply_state(candidate_supply),
        # The two evidence fields CF-0023's shopping list is written from, and
        # only those two: what the pool was searched by, and the closest thing
        # it had. The other seven counters in the Editor's fact are the working
        # of the diagnosis and stay in the plan file - this record is read to
        # decide what to buy, and "we looked for X, the nearest we own is Y at
        # 0.12" is that line. Absent on every state but a code, because no
        # other state has a search behind it.
        "searched": str(evidence.get("searched") or "").strip(),
        "nearest": evidence.get("nearest") or None,
        "detail": (reason or note or "").strip(),
    }


def anchors_from_deficit(deficit):
    """The unresolved anchors of one `plan.assetless-rung.json`.

    Accepts the file as written today (`{"assetless_rung": {blocks, reasons}}`)
    and the enriched form asked for in the task (`anchors`/`deficits` carrying
    `intent`, `start`, `end`, `candidate_supply` (CF-0150) and optionally a
    `cause`, plus a `hole_fill` node whose `refused[]` gives the library rung's
    outcome code per block).

    Only the enriched form can carry the supply fact: the flat one is a list
    of block indices and a line of prose each, with no anchor to hang it on.
    """
    if not isinstance(deficit, dict):
        raise ShortageError("a deficit is a JSON object, not "
                            f"{type(deficit).__name__}")
    rec = deficit.get("assetless_rung")
    rec = rec if isinstance(rec, dict) else deficit
    if rec.get("kind") and rec.get("kind") != KIND:
        raise ShortageError(f"deficit kind {rec['kind']!r} is not {KIND!r} - this "
                            f"record explains a refusal for want of material")

    hole_fill = deficit.get("hole_fill")
    if not isinstance(hole_fill, dict):
        hole_fill = (deficit.get("meme") or {}).get("hole_fill")
    refused = {}
    if isinstance(hole_fill, dict):
        for r in hole_fill.get("refused") or []:
            try:
                refused[int(r["block_index"])] = r
            except (KeyError, TypeError, ValueError):
                continue

    detailed = rec.get("anchors") or rec.get("deficits")
    out = []
    if isinstance(detailed, list) and detailed:
        for d in detailed:
            i = int(d.get("block_index", d.get("index")))
            ins = refused.get(i, {})
            # CF-0150: by key presence, never `.get()`. A null there means the
            # pool delivered and a missing key means nobody measured, and
            # `.get()` answers `None` to both.
            supply = (d["candidate_supply"] if "candidate_supply" in d
                      else SUPPLY_ABSENT)
            out.append(_anchor(i, d.get("reason"), intent=d.get("intent"),
                               start=d.get("start"), end=d.get("end"),
                               degraded_from=d.get("from") or d.get("degraded_from"),
                               cause=d.get("cause"), outcome=ins.get("outcome"),
                               note=ins.get("note"), candidate_supply=supply))
    else:
        blocks = list(rec.get("blocks") or [])
        reasons = list(rec.get("reasons") or [])
        reasons += [""] * (len(blocks) - len(reasons))
        for i, reason in zip(blocks, reasons):
            i = int(i)
            ins = refused.get(i, {})
            out.append(_anchor(i, reason, outcome=ins.get("outcome"),
                               note=ins.get("note")))
    return out


def read_deficit(path):
    path = Path(path)
    if not path.exists():
        raise ShortageError(f"no deficit at {path} - a refusal for want of material is "
                            f"not taken on prose alone (CF-0139)")
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ShortageError(f"{path}: {exc}") from exc


def build(seq, channel, batch_id, script_id, anchors, refused_at,
          reason="", source="", seconds=None, pool_census=None, root=None):
    """One shortage record, ready to be appended. Writes nothing.

    Not quite pure: it reads the two stores, because `pool_census` is the one
    field that cannot be reconstructed later. `retry_when` says what would
    have to arrive; without a note of what was there when it was written,
    "has it arrived" has no subtrahend and CF-0149's gate has nothing to
    stand on. It is taken here rather than in `refuse()` for the reason this
    module exists at all: the record is the format, and a field some callers
    fill and others do not is a field the reader cannot trust.

    Only the stores the record actually waits on are counted (see
    `pool.stores_for`), so a refusal no shopping can fix carries no census -
    there is nothing for it to wait for.
    """
    anchors = list(anchors)
    if not anchors:
        raise ShortageError(
            "a shortage record with no unresolved anchor says nothing that the "
            "rejection reason does not - a refusal for want of material has to name "
            "what was missing (CF-0139)")
    counts = {}
    for a in anchors:
        counts[a["cause"]] = counts.get(a["cause"], 0) + 1
    spans = [a["seconds"] for a in anchors if a["seconds"] is not None]
    fixable = sorted(c for c in counts if c in POOL_FIXABLE)
    return {
        "seq": int(seq),
        "channel": channel,
        "script_id": script_id,
        "batch_id": batch_id,
        "refused_at": refused_at,
        "kind": KIND,
        "source": str(source or ""),
        "reason": (reason or "").strip(),
        "anchors": anchors,
        "blocks": [a["block_index"] for a in anchors],
        "causes": counts,
        "seconds": round(sum(spans), 3) if spans else seconds,
        "pool_fixable": bool(fixable),
        "retry_when": _retry_when(counts, fixable),
        "pool_census": (pool_census if pool_census is not None
                        else pool.census(root, stores=pool.stores_for(counts))),
    }


def _retry_when(counts, fixable):
    """The one line a person reads before re-queueing the topic."""
    if not fixable:
        return ("nothing about the pool would change this refusal: "
                + ", ".join(f"{c} x{counts[c]}" for c in sorted(counts))
                + " - the topic waits on a fix, not on material")
    parts = []
    if "no_footage" in fixable:
        parts.append(f"footage for {counts['no_footage']} anchor(s) that has none")
    if "footage_unusable" in fixable:
        parts.append(f"a usable frame for {counts['footage_unusable']} anchor(s) whose "
                     f"frames exist and cannot be taken")
    if "insert_below_floor" in fixable:
        parts.append(f"a library insert clear of the M4 floors for "
                     f"{counts['insert_below_floor']} hole(s)")
    tail = ""
    if counts.get("unclassified"):
        tail = (f"; {counts['unclassified']} anchor(s) came as prose this record could "
                f"not classify, so the list may be short")
    return "try this topic again once the pool has " + ", ".join(parts) + tail


def log_path(channel, directory=None):
    from ledger import DEFAULT_LEDGER_DIR
    return Path(directory or DEFAULT_LEDGER_DIR) / f"{channel}.shortages.jsonl"


class ShortageLog:
    """The shortage records of one channel: one JSON object per line."""

    def __init__(self, path):
        self.path = Path(path)

    def records(self):
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                raise ShortageError(f"{self.path}:{n}: not JSON ({exc})") from exc
            if not isinstance(rec, dict) or "seq" not in rec:
                raise ShortageError(f"{self.path}:{n}: a record without a seq explains "
                                    f"no ledger row")
            out.append(rec)
        return out

    def for_seq(self, seq, records=None):
        recs = self.records() if records is None else records
        for rec in recs:
            if int(rec["seq"]) == int(seq):
                return rec
        return None

    def append(self, record):
        if self.for_seq(record["seq"]) is not None:
            raise ShortageError(
                f"seq {record['seq']} already carries a shortage record - a row is "
                f"refused once, and the record of why is written once with it")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record


def validate(path, ledger_rows=None):
    """Structural check of a shortage log. Returns a list of errors.

    With `ledger_rows` it also checks the join: every record explains a row
    that was actually refused, and the row it explains is the script it names.
    """
    errs = []
    log = ShortageLog(path)
    try:
        records = log.records()
    except ShortageError as exc:
        return [str(exc)]

    seen = set()
    by_seq = {int(r["seq"]): r for r in ledger_rows} if ledger_rows else None
    for rec in records:
        seq = rec["seq"]
        ctx = f"seq {seq}"
        if seq in seen:
            errs.append(f"{ctx}: two shortage records for one row")
        seen.add(seq)
        if not rec.get("anchors"):
            errs.append(f"{ctx}: no unresolved anchor - the record names nothing missing")
        for a in rec.get("anchors") or []:
            if a.get("cause") not in CAUSES:
                errs.append(f"{ctx}: cause {a.get('cause')!r} is not one of {CAUSES}")
            # CF-0150. Absent is allowed and reads as `""`: records written
            # before the fact existed say nothing about the pool's supply and
            # must not be made to. A value outside the vocabulary is not
            # allowed - it would be read as a measurement.
            supply = a.get("candidate_supply", SUPPLY_UNKNOWN)
            if supply not in SUPPLY_STATES:
                errs.append(f"{ctx}: candidate_supply {supply!r} is not one of "
                            f"{SUPPLY_STATES}")
        if rec.get("kind") != KIND:
            errs.append(f"{ctx}: kind {rec.get('kind')!r} is not {KIND!r}")
        # CF-0149. Absent is allowed and means "written before the census
        # existed" - `pool.arrival()` answers `no-baseline` and lets the topic
        # through rather than holding it for ever. Present and the wrong shape
        # is not allowed: that is a baseline the gate would read as a number.
        snapshot = rec.get("pool_census")
        if snapshot is not None and not isinstance(snapshot, dict):
            errs.append(f"{ctx}: pool_census is {type(snapshot).__name__}, not the "
                        f"per-store census pool.py writes")
        elif isinstance(snapshot, dict):
            missing = [s for s in pool.stores_for(rec.get("causes"))
                       if s not in snapshot]
            if missing:
                errs.append(f"{ctx}: pool_census does not count {', '.join(missing)}, "
                            f"which this refusal waits on")
            # CF-0527. `per_source` is absent on records written before it
            # (read with the old rule on totals); present, it is the baseline
            # the growth rule compares identities against, so it must be one.
            per_source = (snapshot.get(pool.FOOTAGE) or {}).get("per_source")
            if per_source is not None and not (
                    isinstance(per_source, dict)
                    and all(isinstance(v, int) for v in per_source.values())):
                errs.append(f"{ctx}: pool_census footage per_source is not "
                            f"{{source id: shots}}")
        if by_seq is not None:
            row = by_seq.get(int(seq))
            if row is None:
                errs.append(f"{ctx}: no such row in the ledger")
            else:
                if not row["rejected_at"]:
                    errs.append(f"{ctx}: the row is not a refusal, so nothing here "
                                f"explains it")
                if rec.get("script_id") and rec["script_id"] != row["script_id"]:
                    errs.append(f"{ctx}: record names {rec['script_id']}, the row is "
                                f"{row['script_id']}")
    return errs
