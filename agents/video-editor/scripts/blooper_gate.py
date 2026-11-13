#!/usr/bin/env python3
"""CF-0190 part 3: the two borders of the blooper relaxation, measured on the
plan before anything is rendered.

The decision (grill 2026-09-11, written down by CF-0190)
--------------------------------------------------------
The channel's ending clip promises `On-set bloopers`, and the one fact this
channel owes every video (of any kind since CF-0439 - production, box office,
casting, reception, an unscripted moment and so on) is sometimes exactly "what
went wrong on set". But a
blooper is studio material end to end - not one frame of it is ours - and the
ordinary rights-holder check takes such a topic off the batch, correctly (batch
`2026-09-09T2031Z`, a Sony/Spire-Runner match at `review`). The user chose to show
bloopers anyway, with that check relaxed *for them only* and with borders a
machine can check:

  * the fragment is at most `max_fragment_seconds` (3.0) long, and
  * narration runs over it - no stretch of it longer than
    `narration_over_fragment.max_silent_seconds` (0.5) sits outside the aligned
    words, its leading and trailing edges included.

`agents/compliance-checker` (part 2) is the half that stops forcing `review` on
marked material. This module is the half that makes the borders real: the
relaxation buys a blooper its way past the rights-holder verdict, and this is
where it pays for it. Without this file the relaxation would be a threshold
quietly loosened so a render would pass - which is what the project already
named brak twice (`gate honesty`; the nearly black frame that shipped in 1.0).

Where the numbers come from
---------------------------
The channel config block, never this file. `MAX_FRAGMENT_CEILING` and
`MAX_SILENT_CEILING` are here only as *ceilings the reader refuses to exceed*:
a channel may write stricter numbers than the decision, and a channel that
writes looser ones has written an illegal block, which grants no relaxation at
all (the root's schema refuses it too - patterns/validate_patterns.py
BLOOPER_* - but a reader that trusted the root to have run is a reader that can
be widened by editing a file nobody re-validated).

The three states of a block, and why the middle one refuses
-----------------------------------------------------------
1. **No marker** - the field is absent, `null`, `false`, a non-object, or an
   object missing/emptying one of `marker.required_keys`. Not a blooper. Not
   measured against these numbers at all, and the kind of the material is never
   guessed from a description, a tag or a filename: the contract says so, and
   part 2 makes the same reading, so material like this was already taken off
   the batch by the ordinary verdict if it really was studio footage.
2. **A well-formed marker, with no relaxation in force** - the block is absent,
   switched off, unreadable or illegal. The plan is REFUSED. This is the
   fail-closed direction and it is deliberate: the marker is the editor saying
   "this fragment is somebody else's blooper", and with no relaxation in force
   there is no rule in this factory that lets such a fragment ship. Refusing
   costs nothing real (nothing writes the marker yet) and the alternative -
   shipping an unmeasured studio fragment because a switch was off - is the
   exact shape of the defect this task exists to prevent.
3. **A well-formed marker with the relaxation in force** - the two borders are
   measured, and a breach refuses the plan.

Before the render, not after
----------------------------
Same shape and the same reason as CF-0137's assetless rung: `judge()` returns
`passed: False`, build_render_plan.py exits 2, no plan file is written, and a
machine-readable deficit lands beside where the plan would have been
(`plan.blooper-gate.json`, `write_deficit()`). `qc_render.py` could not do this
job - it probes a rendered file, so by the time it saw anything the render would
already have been paid for, and it cannot see a marker at all.
"""
import json
from pathlib import Path

# The channel config's key. Top-level beside `insert_layers` and
# `assetless_block_rung`, not under `video_editor`: what a channel is willing to
# publish is an editorial decision rather than a render knob, and this block is
# read by two agents.
CHANNEL_KEY = "blooper_rights_relaxation"

# A channel that wrote no block, or wrote one and left it off, has no
# relaxation. There is no way to configure a default of true.
DEFAULT_ENABLED = False

# The `rhythm_shortfalls()` / deficit kind (CF-0057's shape), so a refused plan
# comes back with a record rather than a paragraph of stderr.
DEFICIT_KIND = "blooper_borders_refused"

# The marker object's key name is `marker.field` in the config and is read from
# there (`marker_field()`). This fallback is used for one purpose only: to
# *detect and refuse* a marked block when no relaxation is in force, i.e. when
# there is no config to read the name out of. It never grants anything, and it
# is never used when a legal block is in force - that block's own `field` wins.
FALLBACK_MARKER_FIELD = "blooper"

# The decision's own numbers, as ceilings a channel may not exceed. Not
# defaults: a channel with no legal block gets no relaxation, not these.
MAX_FRAGMENT_CEILING = 3.0
MAX_SILENT_CEILING = 0.5

# The marker key carrying the one border no machine checks.
ATTESTATION_KEY = "not_whole_gag"

# The block's keys, mirroring the root schema (patterns/validate_patterns.py
# BLOOPER_*) and `agents/compliance-checker/scripts/blooper_relaxation.py`.
# All are required at `enabled: false` too - a relaxation is recorded whole or
# not at all - and `note`/`<key>_note` prose is allowed beside them.
BLOCK_KEYS = ("enabled", "decided_on", "recorded_by", "reason", "marker",
              "max_fragment_seconds", "narration_over_fragment",
              "not_the_whole_gag", "applies_to", "does_not_touch", "read_by")
MARKER_KEYS = ("field", "required_keys", "carried_on", "absent_or_malformed")
NARRATION_KEYS = ("required", "max_silent_seconds", "words_source")
GAG_KEYS = ("machine_checkable", "attested_by", "min_chars", "held_by")
NOTE_KEY = "note"
NOTE_SUFFIX = "_note"

# The timeline is written in milliseconds everywhere in this repo (every span
# is `round(x, 3)`), so the tolerance is half a millisecond rather than a
# float-noise epsilon: a border is breached when it is breached by something a
# viewer could be told about, not by 1e-12 of arithmetic.
EPS = 5e-4

# The violation codes. A closed list, because the rotation and the driver read
# codes and only read prose when there are none.
CODE_NO_RELAXATION = "no_relaxation_in_force"
CODE_TOO_LONG = "fragment_too_long"
CODE_NOT_COVERED = "narration_not_over_fragment"


# --------------------------------------------------------------------------
# Reading the channel's block
# --------------------------------------------------------------------------
def _known(keys):
    return tuple(keys) + (NOTE_KEY,) + tuple(f"{k}{NOTE_SUFFIX}" for k in keys)


def _unknown(node, keys, ctx):
    unknown = sorted(k for k in node if k not in _known(keys))
    return [f"{ctx}: unknown key(s) {unknown}"] if unknown else []


def _missing(node, keys, ctx):
    return [f"{ctx}.{k}: required" for k in keys if k not in node]


def _number_in_band(errs, node, key, ctx, ceiling, strict_floor=False):
    if key not in node:
        return
    value = node[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errs.append(f"{ctx}.{key}: must be a number, got {value!r}")
        return
    if (value <= 0) if strict_floor else (value < 0):
        errs.append(f"{ctx}.{key}: out of band, got {value!r}")
    if value > ceiling:
        errs.append(f"{ctx}.{key}: {value!r} is looser than the decision's "
                    f"{ceiling} - a channel may be stricter, never looser")


def structural_errors(block, ctx=CHANNEL_KEY):
    """The shape this reader stands on, or `[]` if the block is sound.

    A subset of the root's schema on purpose: the keys and value shapes this
    reader depends on, plus the two ceilings, minus the prose and date rules
    that belong to `inserts/validate_inserts.py`. Deliberately the same subset
    the Checker's reader validates, so the two agents cannot disagree about
    whether a relaxation exists.
    """
    if not isinstance(block, dict):
        return [f"{ctx}: must be an object"]
    errs = _unknown(block, BLOCK_KEYS, ctx)
    errs += _missing(block, BLOCK_KEYS, ctx)
    if "enabled" in block and not isinstance(block["enabled"], bool):
        errs.append(f"{ctx}.enabled: must be true or false, got "
                    f"{block['enabled']!r} - an unreadable switch is not a "
                    f"switched-on one")

    mctx = f"{ctx}.marker"
    marker = block.get("marker")
    if "marker" in block:
        if not isinstance(marker, dict):
            errs.append(f"{mctx}: must be an object")
        else:
            errs += _unknown(marker, MARKER_KEYS, mctx)
            errs += _missing(marker, MARKER_KEYS, mctx)
            field = marker.get("field")
            if "field" in marker and (not isinstance(field, str) or not field.strip()):
                errs.append(f"{mctx}.field: must name the marker object's key, "
                            f"got {field!r}")
            required = marker.get("required_keys")
            if "required_keys" in marker:
                if (not isinstance(required, list) or not required
                        or any(not isinstance(k, str) or not k.strip()
                               for k in required)):
                    errs.append(f"{mctx}.required_keys: must be a non-empty "
                                f"list of key names, got {required!r}")
                elif ATTESTATION_KEY not in required:
                    errs.append(f"{mctx}.required_keys: must include "
                                f"{ATTESTATION_KEY!r} - it carries the one "
                                f"border no machine checks")

    nctx = f"{ctx}.narration_over_fragment"
    narration = block.get("narration_over_fragment")
    if "narration_over_fragment" in block:
        if not isinstance(narration, dict):
            errs.append(f"{nctx}: must be an object")
        else:
            errs += _unknown(narration, NARRATION_KEYS, nctx)
            errs += _missing(narration, NARRATION_KEYS, nctx)
            if "required" in narration and narration["required"] is not True:
                errs.append(f"{nctx}.required: must be true - a blooper with no "
                            f"commentary over it does not pass")
            _number_in_band(errs, narration, "max_silent_seconds", nctx,
                            MAX_SILENT_CEILING)

    gctx = f"{ctx}.not_the_whole_gag"
    gag = block.get("not_the_whole_gag")
    if "not_the_whole_gag" in block:
        if not isinstance(gag, dict):
            errs.append(f"{gctx}: must be an object")
        else:
            errs += _unknown(gag, GAG_KEYS, gctx)
            errs += _missing(gag, GAG_KEYS, gctx)
            if "machine_checkable" in gag and gag["machine_checkable"] is not False:
                errs.append(f"{gctx}.machine_checkable: must be false - there is "
                            f"no such check, and a config claiming one claims a "
                            f"gate that does not exist")
            if "min_chars" in gag:
                mc = gag["min_chars"]
                if not isinstance(mc, int) or isinstance(mc, bool) or mc < 1:
                    errs.append(f"{gctx}.min_chars: must be an integer >= 1, "
                                f"got {mc!r}")

    _number_in_band(errs, block, "max_fragment_seconds", ctx,
                    MAX_FRAGMENT_CEILING, strict_floor=True)
    return errs


def relaxation(channel_cfg):
    """The relaxation this channel config grants, or None.

    None when the block is absent, not an object, switched off, or structurally
    illegal - the fail-closed reading both CF-0190 agents are contracted to
    make, and the same one `assetless_rung.enabled()` makes of its switch.
    Mirrors the root's `validate_patterns.blooper_relaxation()`.
    """
    if not isinstance(channel_cfg, dict):
        return None
    block = channel_cfg.get(CHANNEL_KEY)
    if not isinstance(block, dict):
        return None
    if block.get("enabled", DEFAULT_ENABLED) is not True:
        return None
    if structural_errors(block):
        return None
    return block


def why_not_in_force(channel_cfg):
    """One line naming why no relaxation is in force, for the record a refusal
    leaves behind. `None` when one *is* in force."""
    if not isinstance(channel_cfg, dict):
        return "no channel config could be read"
    block = channel_cfg.get(CHANNEL_KEY)
    if block is None:
        return f"this channel wrote no {CHANNEL_KEY} block"
    if not isinstance(block, dict):
        return f"{CHANNEL_KEY} is not an object"
    if block.get("enabled", DEFAULT_ENABLED) is not True:
        return f"{CHANNEL_KEY}.enabled is not true"
    errs = structural_errors(block)
    if errs:
        return f"{CHANNEL_KEY} is not legal: {'; '.join(errs)}"
    return None


def marker_field(relax):
    """The marker object's key name, from the config - never hardcoded while
    there is a config to read it from. See FALLBACK_MARKER_FIELD for the one
    case there is not."""
    if relax:
        field = relax["marker"]["field"]
        if isinstance(field, str) and field.strip():
            return field
    return FALLBACK_MARKER_FIELD


def required_keys(relax):
    if relax:
        return tuple(relax["marker"]["required_keys"])
    # No config to read: the contract's three keys, used only to decide that a
    # marked block is marked - never to let one through.
    return ("marked_by", "marked_at", ATTESTATION_KEY)


def min_attestation_chars(relax):
    gag = (relax or {}).get("not_the_whole_gag")
    if isinstance(gag, dict):
        mc = gag.get("min_chars")
        if isinstance(mc, int) and not isinstance(mc, bool) and mc >= 1:
            return mc
    return None


def max_fragment_seconds(relax):
    return relax["max_fragment_seconds"] if relax else None


def max_silent_seconds(relax):
    return relax["narration_over_fragment"]["max_silent_seconds"] if relax else None


# --------------------------------------------------------------------------
# Reading the marker on a plan block
# --------------------------------------------------------------------------
def marker_state(record, relax):
    """`(state, marker_or_reason)` for one plan block.

    * `("unmarked", reason)` - absent, `null`, `false`, or not an object. Not a
      blooper, and not this gate's business.
    * `("malformed", reason)` - an object, but missing or emptying a required
      key, or carrying a stub attestation. The contract is explicit that this
      is *not* a blooper either: reading it as one would be a gate deciding the
      kind of the material on a technicality, and the same reading upstream
      (part 2) already left the ordinary rights-holder verdict in place, which
      takes real studio material off the batch. Recorded, never guessed at.
    * `("marked", marker)` - the marker as written.
    """
    field = marker_field(relax)
    if not isinstance(record, dict) or field not in record:
        return "unmarked", f"no {field!r} key"
    value = record[field]
    if value is None or value is False:
        return "unmarked", f"{field} is {value!r}"
    if not isinstance(value, dict):
        return "unmarked", f"{field} is not an object ({type(value).__name__})"
    for key in required_keys(relax):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            return "malformed", f"{field}.{key} is missing or empty"
    min_chars = min_attestation_chars(relax)
    if min_chars is not None and ATTESTATION_KEY in required_keys(relax):
        if len(value[ATTESTATION_KEY].strip()) < min_chars:
            return ("malformed",
                    f"{field}.{ATTESTATION_KEY} is a stub "
                    f"({len(value[ATTESTATION_KEY].strip())} chars < {min_chars})")
    return "marked", value


# --------------------------------------------------------------------------
# The second border: is the narration actually over the fragment?
# --------------------------------------------------------------------------
def speech_intervals(words):
    """`[start, end)` per aligned word, in order, skipping anything unreadable.

    Unreadable is skipped rather than guessed: a word with no usable timing is
    not speech this gate can point at, and the fragment it would have covered
    has to be covered by a word that *is* readable. `align_words.py` writes
    `{word, start, end}` in seconds on the block timeline.
    """
    out = []
    if not isinstance(words, list):
        return out
    for w in words:
        if not isinstance(w, dict):
            continue
        start, end = w.get("start"), w.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if end <= start:
            continue
        out.append((float(start), float(end)))
    out.sort()
    return out


def uncovered_stretches(start, end, words, max_silent):
    """Every stretch of `[start, end)` longer than `max_silent` that no word
    covers - the leading and trailing edges included.

    The edges are the point of the rule, not a detail of it: a fragment parked
    in a pause between two sentences has no commentary over it whatever the
    script claims, and a rule that only looked at the gaps *between* words
    would pass exactly that fragment.
    """
    start, end = float(start), float(end)
    if end <= start:
        return []
    limit = float(max_silent)
    gaps, cursor = [], start
    for lo, hi in speech_intervals(words):
        if hi <= start:
            continue
        if lo >= end:
            break
        lo, hi = max(lo, start), min(hi, end)
        if lo > cursor:
            gaps.append((cursor, lo))
        cursor = max(cursor, hi)
    if end > cursor:
        gaps.append((cursor, end))
    return [{"start": round(lo, 3), "end": round(hi, 3),
             "seconds": round(hi - lo, 3)}
            for lo, hi in gaps if (hi - lo) > limit + EPS]


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------
def measure(index, block, words, relax):
    """The record for one marked block: both borders, measured."""
    start, end = float(block.get("start") or 0.0), float(block.get("end") or 0.0)
    seconds = round(end - start, 3)
    rec = {
        "block_index": index,
        "start": round(start, 3),
        "end": round(end, 3),
        "seconds": seconds,
        "intent": (block.get("intent") or "").strip(),
        "codes": [],
        "over_by": None,
        "uncovered": [],
        "longest_uncovered_seconds": None,
    }
    if relax is None:
        rec["codes"].append(CODE_NO_RELAXATION)
        rec["passed"] = False
        return rec
    ceiling = float(max_fragment_seconds(relax))
    if seconds > ceiling + EPS:
        rec["codes"].append(CODE_TOO_LONG)
        rec["over_by"] = round(seconds - ceiling, 3)
    silent = float(max_silent_seconds(relax))
    rec["uncovered"] = uncovered_stretches(start, end, words, silent)
    if rec["uncovered"]:
        rec["codes"].append(CODE_NOT_COVERED)
        rec["longest_uncovered_seconds"] = max(g["seconds"] for g in rec["uncovered"])
    rec["passed"] = not rec["codes"]
    return rec


def judge(blocks, words, channel_cfg):
    """The verdict for a finished block list. `passed: False` means: do not
    write the plan.

    `blocks` are the plan's blocks (each carrying the marker copied off the
    storyboard by build_render_plan.py), `words` the plan's aligned `words[]`.
    """
    relax = relaxation(channel_cfg)
    field = marker_field(relax)
    marked, malformed = [], []
    for i, b in enumerate(blocks or []):
        state, payload = marker_state(b, relax)
        if state == "marked":
            marked.append(measure(i, b, words, relax))
        elif state == "malformed":
            malformed.append({"block_index": i, "reason": payload})

    failed = [m for m in marked if not m["passed"]]
    ceiling = max_fragment_seconds(relax)
    silent = max_silent_seconds(relax)
    if not marked:
        note = (f"no block carries a {field!r} marker - nothing here claims to "
                f"be somebody else's blooper, and no block is measured against "
                f"the relaxation's borders")
    elif relax is None:
        note = (f"block(s) {[m['block_index'] for m in marked]} carry a "
                f"{field!r} marker and no relaxation is in force "
                f"({why_not_in_force(channel_cfg)}). A marked fragment is "
                f"third-party studio material by the editor's own word, and "
                f"with no relaxation in force nothing permits it to ship - the "
                f"plan is refused (CF-0190)")
    elif failed:
        note = (f"{len(failed)} of {len(marked)} marked fragment(s) breach the "
                f"relaxation's borders (<= {ceiling}s on the timeline, no "
                f"stretch over {silent}s outside the narration). The relaxation "
                f"is what let this material past the rights-holder verdict at "
                f"all; the borders are what it was granted for - the plan is "
                f"refused")
    else:
        note = (f"{len(marked)} marked fragment(s) inside the relaxation's "
                f"borders (<= {ceiling}s, narration over all of them) - "
                f"allowed, and recorded")
    if malformed:
        note += (f"; {len(malformed)} block(s) carry a {field!r} key that is "
                 f"not a marker and are not read as bloopers")
    return {
        "kind": DEFICIT_KIND,
        "relaxation_in_force": relax is not None,
        "relaxation_note": why_not_in_force(channel_cfg),
        "marker_field": field,
        "max_fragment_seconds": ceiling,
        "max_silent_seconds": silent,
        "blocks": [m["block_index"] for m in marked],
        "marked_count": len(marked),
        "fragments": marked,
        "malformed_markers": malformed,
        # The one field a caller has to read. True = build the plan.
        "passed": not failed,
        "note": note,
    }


def report_lines(rec):
    """The stderr lines - written on a pass too, for the same reason CF-0137's
    gate writes its passing lines: a run that never says whether a blooper was
    inside its borders cannot be audited afterwards, and this is the field the
    relaxation was granted on."""
    verdict = "passed" if rec["passed"] else "REFUSED"
    lines = [f"blooper borders {verdict}: {rec['note']}"]
    for f in rec["fragments"]:
        state = "ok" if f["passed"] else ", ".join(f["codes"])
        lines.append(f"  block {f['block_index']}: {f['seconds']}s "
                     f"[{f['start']}-{f['end']}] {state}")
        for gap in f["uncovered"]:
            lines.append(f"    no narration over {gap['start']}-{gap['end']} "
                         f"({gap['seconds']}s)")
    for m in rec["malformed_markers"]:
        lines.append(f"  block {m['block_index']}: {m['reason']} - not read as "
                     f"a blooper, and not measured")
    return lines


def write_deficit(output, rec):
    """The refused plan's deficit, beside where the plan would have been
    (`plan.blooper-gate.json`).

    The same move CF-0118's `plan.two-source-gate.json` and CF-0137's
    `plan.assetless-rung.json` make, and for the same reason: on a refusal
    there is no plan file to carry the record, and the caller has to be able to
    read the shortfall rather than parse stderr."""
    p = Path(output)
    path = p.with_name(f"{p.stem}.blooper-gate.json")
    try:
        json.dump({"blooper_gate": rec}, open(path, "w"), indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)
