#!/usr/bin/env python3
"""CF-0190 part 2: what a rights-holder match forces when the material it
matched is a marked blooper.

RETIRED FROM THE PROCEDURE by CF-0420 (user's decision of 2026-09-28): a
rights-holder match no longer earns any verdict - `rights_holder_info.py`
makes it informational in both passes - so there is no rights-holder `review`
left for this module to cap, and the SKILL no longer runs it. It stays, with
its tests, as the record of the CF-0190 decision; running it is harmless.

The decision (user, grill of 2026-09-11) and the whole relaxation - borders,
date, reason - live in the channel config, not here:
`channels/<channel>.json` -> `blooper_rights_relaxation`, with its schema at
`patterns/validate_patterns.py::validate_blooper_relaxation_block`. This file
is one of the two readers that block names (`read_by.compliance_checker`);
the other is the Video Editor's (part 3, `read_by.video_editor`).

What changes, and the one sentence that bounds it
-------------------------------------------------
Nothing about how a match is found. The channel's rights-holder list
(`channels/<channel>/rights-holder-blacklist.json`, CF-0629) is not read here
at all - this module never opens it, never filters it, never re-scores it - and `rights_holder_check` is written by the pass exactly as
before: `matched`, `risk_level`, `reason`. What changes is only what a match
*forces*: on material carrying a well-formed marker the verdict is capped at
`caution` instead of `review`, and the result carries a record naming the
config block that granted the relaxation and the marker that earned it.

`caution` is the verdict that proceeds (`review` is what the footage indexer
and the Content Researcher skip on - `01b-footage-index.json` `skipped_topics`,
`03-content-researcher.json` `skipped.reason_code = compliance_review`), and
it is also the verdict that leaves the relaxation visible. `clear` is never
raised by this module: a relaxation nobody can see afterwards is the exact
shape this project has twice called brak ("every relaxation is recorded
rather than hidden", "gate honesty"). The gate stays a gate; it got a rule.

Four things the relaxation deliberately does not do
---------------------------------------------------
1. It does not lower a `review` that the rights-holder check did not raise.
   A result with no rights-holder match is not this module's business.
2. It does not soften the content-sensitivity check. Neither a `review` for
   content sensitivity nor a `block` from the contribution-substance check
   (CF-0066, CF-0187) is a rights-holder verdict, and neither is touched -
   `contribution_check` is a separate enum (`pass|block`) and is copied
   through untouched.
3. It never produces `clear` - the cap is a ceiling of `caution`, applied to
   `review` only, and it never raises a verdict either.
4. It changes nothing for material without a well-formed marker. A topic
   taken to `review` by a rights-holder match with no blooper in it is taken
   off the batch exactly as before - the acceptance criterion of CF-0190.

Fail closed, and no guessing
----------------------------
Both halves of the reading fail closed, the same way
`agents/video-editor/scripts/assetless_rung.py::enabled()` reads its own
switch: what cannot be read has not been written.

* The block: absent, `enabled: false`, not an object, or structurally
  illegal -> no relaxation at all (`relaxation()` returns None).
* The marker: absent, `null`, `false`, a non-object, missing any of the
  config's `marker.required_keys`, carrying an empty one, or carrying a stub
  attestation shorter than `not_the_whole_gag.min_chars` -> not a blooper
  (`marker_of()` returns None). The material's kind is never inferred from a
  description, a tag or a filename: the marker is the only evidence, and an
  unmarked piece of studio footage keeps the ordinary verdict.

The marker's field name and its required keys are read from the config
(`marker.field`, `marker.required_keys`), never hardcoded, so the contract
has one home.

On legality
-----------
The authoritative schema is the root's, run from the root
(`inserts/validate_inserts.py`). The `structural_errors()` below is a
deliberate subset: the shape this reader itself stands on plus the two
ceilings the decision set, without the prose-length and date rules that are
the root's to enforce. It exists so that an illegal block relaxes nothing on
this side either - the safe direction - not as a second schema. It is never
looser than the root's: `tests/test_blooper_relaxation.py` reads the root's
constants back out and fails when the two drift apart.
"""
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
from _cli import screen  # noqa: E402


def _find_repo_root(start):
    """Walk upward from `start` for the shorts-content-factory root (an
    ancestor holding both `channels/` and `patterns/`). Same lookup
    check_contribution.py makes, and for the same reason: this file's depth
    differs between a normal checkout and a worktree.

    `FACTORY_ROOT` wins when it is set, the convention `_runlog.py` and
    `shared/inserts/underlay.py` already use - it is how the tests point this
    reader at a config of their own instead of the channel's real one, so no
    test ever has to edit a live config to see the other side of the switch.
    """
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for p in [start, *start.parents]:
        if (p / "channels").is_dir() and (p / "patterns").is_dir():
            return p
    raise RuntimeError(
        f"could not locate the shorts-content-factory root above {start} "
        f"(looked for an ancestor with both channels/ and patterns/)")


REPO = _find_repo_root(Path(__file__).resolve())

# The channel config's key, top-level beside `insert_layers` and
# `assetless_block_rung` - what a channel is willing to publish, not a render
# knob (CF-0137's reason), and read by two agents rather than one.
CHANNEL_KEY = "blooper_rights_relaxation"

# A channel that wrote no block, or wrote one and left it off, has no
# relaxation. There is no way to configure a default of true.
DEFAULT_ENABLED = False

# The block's keys, mirroring patterns/validate_patterns.py BLOOPER_*. All of
# them are required even at `enabled: false` - a relaxation is recorded whole
# or not at all - and `note`/`<key>_note` prose is allowed beside them.
BLOCK_KEYS = ("enabled", "decided_on", "recorded_by", "reason", "marker",
              "max_fragment_seconds", "narration_over_fragment",
              "not_the_whole_gag", "applies_to", "does_not_touch", "read_by")
MARKER_KEYS = ("field", "required_keys", "carried_on", "absent_or_malformed")
NARRATION_KEYS = ("required", "max_silent_seconds", "words_source")
GAG_KEYS = ("machine_checkable", "attested_by", "min_chars", "held_by")
NOTE_KEY = "note"
NOTE_SUFFIX = "_note"

# The decision's own numbers, as ceilings: a channel may be stricter, never
# looser. Neither is measured here (both are the Editor's, part 3) - they are
# checked because a block that widened itself past the decision is not a legal
# block, and an illegal block relaxes nothing anywhere.
MAX_FRAGMENT_CEILING = 3.0
MAX_SILENT_CEILING = 0.5

# The marker key carrying the one border no machine checks (the attestation).
ATTESTATION_KEY = "not_whole_gag"

# The check whose verdict this relaxation may cap, and nothing else.
RELAXED_CHECK = "rights_holder_check"
# The verdict that may be capped, and the ceiling it is capped to.
RELAXABLE_VERDICT = "review"
CAP_VERDICT = "caution"
# Where the record of an applied relaxation lands in the result object.
RECORD_KEY = "blooper_relaxation"

RECORD_NOTE = (
    "The rights-holder match stands exactly as written in rights_holder_check "
    "(matched, risk_level, reason); the channel's "
    "channels/<channel>/rights-holder-blacklist.json was "
    "not read differently, not filtered and not changed. Only what the match "
    "forces changed: capped at caution instead of review. Never clear - "
    "caution is the verdict that proceeds and the one that keeps this "
    "relaxation visible. Verdicts raised by any other check are untouched: "
    "content sensitivity is not a rights-holder check, and contribution_check "
    "(CF-0066/CF-0187) is a separate pass|block verdict this never softens."
)
RECORD_BY = ("agents/compliance-checker/scripts/blooper_relaxation.py "
             "(CF-0190 part 2)")

# The identifier fields a material record may carry, most specific first.
ID_KEYS = ("scene_id", "script_id", "topic_id", "block_id", "id")


# --------------------------------------------------------------------------
# Reading the block
# --------------------------------------------------------------------------
def _known(keys):
    return tuple(keys) + (NOTE_KEY,) + tuple(f"{k}{NOTE_SUFFIX}" for k in keys)


def _unknown(node, keys, ctx):
    known = _known(keys)
    unknown = sorted(k for k in node if k not in known)
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
    if value <= 0 if strict_floor else value < 0:
        errs.append(f"{ctx}.{key}: out of band, got {value!r}")
    if value > ceiling:
        errs.append(f"{ctx}.{key}: {value!r} is looser than the decision's "
                    f"{ceiling} - a channel may be stricter, never looser")


def structural_errors(block, ctx=CHANNEL_KEY):
    """The shape this reader stands on, or [] if the block is sound.

    A subset of the root's schema on purpose (see the module docstring): the
    keys and value shapes a reader depends on, plus the two ceilings, minus
    the prose and date rules that belong to `inserts/validate_inserts.py`.
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
                    errs.append(f"{mctx}.required_keys: must be a non-empty list "
                                f"of key names, got {required!r}")
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
            if ("machine_checkable" in gag
                    and gag["machine_checkable"] is not False):
                errs.append(f"{gctx}.machine_checkable: must be false - there is "
                            f"no such check, and a config claiming one claims a "
                            f"gate that does not exist")
            attested = gag.get("attested_by")
            if "attested_by" in gag:
                legal = None
                if isinstance(marker, dict):
                    field = marker.get("field")
                    required = marker.get("required_keys")
                    if isinstance(field, str) and isinstance(required, list):
                        legal = [f"{field}.{k}" for k in required
                                 if isinstance(k, str)]
                if not isinstance(attested, str) or (legal and attested not in legal):
                    errs.append(f"{gctx}.attested_by: must name a key of the "
                                f"marker, got {attested!r}")
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

    None when the block is absent, not an object, switched off, or
    structurally illegal - the fail-closed reading both CF-0190 agents are
    contracted to make, and the same one `assetless_rung.enabled()` makes of
    its switch. Mirrors the root's `validate_patterns.blooper_relaxation()`.
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


def channel_config_path(channel, repo=REPO):
    return Path(repo) / "channels" / f"{channel}.json"


def load_relaxation(channel, repo=REPO):
    """`relaxation()` for a channel by id. A config that is missing or not
    readable as JSON grants nothing - a relaxation that cannot be read has
    not been granted."""
    path = channel_config_path(channel, repo)
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return relaxation(cfg)


def config_ref(channel):
    """How the record points back at the block that granted the relaxation."""
    return f"channels/{channel}.json :: {CHANNEL_KEY}"


# --------------------------------------------------------------------------
# Reading the marker on a piece of material
# --------------------------------------------------------------------------
def marker_field(relax):
    """The marker object's key name, from the config. Never hardcoded."""
    return relax["marker"]["field"] if relax else None


def marker_of(record, relax):
    """The well-formed marker on this record, or None.

    None for every form of absence the contract names - no key, `null`,
    `false`, a non-object, a missing or empty required key - and for a stub
    attestation (shorter than `not_the_whole_gag.min_chars`), because the one
    thing a machine can check about that border is that the claim was made
    and is not filler. Required keys must be non-empty strings: anything else
    is a marker that was not written the way the contract writes it, and this
    reads as not a blooper rather than as a blooper on a technicality.
    """
    if not relax or not isinstance(record, dict):
        return None
    field = marker_field(relax)
    value = record.get(field)
    if not isinstance(value, dict):
        return None
    required = relax["marker"]["required_keys"]
    for key in required:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            return None
    gag = relax.get("not_the_whole_gag")
    if isinstance(gag, dict):
        attested, min_chars = gag.get("attested_by"), gag.get("min_chars")
        if (isinstance(attested, str) and isinstance(min_chars, int)
                and not isinstance(min_chars, bool)):
            key = attested.split(".")[-1]
            if key in required and len(value[key].strip()) < min_chars:
                return None
    return value


def _ident(record, fallback):
    for key in ID_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


def marked_material(material, relax):
    """Every marked record inside this piece of material, as `(id, marker)`.

    Both stages of the contract in one function: the marker sits on whatever
    record describes the material at that stage - `topics[].scenes[]` in
    `01-trend-hunter.json` (a topic is marked when a scene of it is), and the
    `scripts[]` record itself in `03-content-researcher.json`. An empty list
    means nothing here is a blooper.
    """
    if not relax or not isinstance(material, dict):
        return []
    found = []
    own = marker_of(material, relax)
    if own is not None:
        found.append((_ident(material, "material"), own))
    scenes = material.get("scenes")
    if isinstance(scenes, list):
        for i, scene in enumerate(scenes):
            marker = marker_of(scene, relax)
            if marker is not None:
                found.append((_ident(scene, f"scenes[{i}]"), marker))
    return found


# --------------------------------------------------------------------------
# Applying it to a verdict
# --------------------------------------------------------------------------
def rights_holder_matched(result):
    check = result.get(RELAXED_CHECK) if isinstance(result, dict) else None
    return isinstance(check, dict) and check.get("matched") is True


def sensitivity_flagged(result):
    """Whether the content-sensitivity check flagged this result.

    A flagged result is never relaxed. The two severities that check
    produces - a soft flag (`caution`) and a real concern (`review`) - are
    written into the same `flagged: true`, so a flagged `review` cannot be
    attributed to the rights-holder match alone, and the relaxation may only
    lower what the rights-holder check alone raised.
    """
    check = result.get("content_sensitivity_check") if isinstance(result, dict) else None
    return isinstance(check, dict) and check.get("flagged") is True


def relax_result(result, material, relax, channel):
    """`(result, record)` - the result as it should be written, and the record
    of the relaxation if one applied (None if none did).

    The returned result is a copy; the input is never mutated. When nothing
    applies the copy is identical to the input, record included in nothing:
    the relaxation is written down only where it actually changed something.
    """
    out = copy.deepcopy(result) if isinstance(result, dict) else result
    if not relax or not isinstance(result, dict):
        return out, None
    if result.get("verdict") != RELAXABLE_VERDICT:
        return out, None          # never raises a verdict, never touches clear
    if not rights_holder_matched(result):
        return out, None          # a review this check did not raise
    if sensitivity_flagged(result):
        return out, None          # not the rights-holder check's review alone
    marked = marked_material(material, relax)
    if not marked:
        return out, None          # not a blooper: the ordinary verdict stands
    record = {
        "applied": True,
        "relaxed_check": RELAXED_CHECK,
        "verdict_before": RELAXABLE_VERDICT,
        "verdict_after": CAP_VERDICT,
        "granted_by": {
            "config": config_ref(channel),
            "decided_on": relax.get("decided_on"),
            "recorded_by": relax.get("recorded_by"),
            "applies_to": relax.get("applies_to"),
        },
        "marker_field": marker_field(relax),
        "marked_material": [{"id": ident, "marker": marker}
                            for ident, marker in marked],
        "note": RECORD_NOTE,
        "recorded_by_reader": RECORD_BY,
    }
    out["verdict"] = CAP_VERDICT
    out[RECORD_KEY] = record
    return out, record


# --------------------------------------------------------------------------
# The pass over a written compliance file
# --------------------------------------------------------------------------
def index_material(stage_doc):
    """`{id: record}` for the stage file the verdicts were written about -
    `topics[]` of `01-trend-hunter.json` or `scripts[]` of
    `03-content-researcher.json`."""
    index = {}
    if not isinstance(stage_doc, dict):
        return index
    for key in ("topics", "scripts"):
        items = stage_doc.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                ident = _ident(item, None)
                if ident:
                    index[ident] = item
    return index


def result_id(result):
    return _ident(result, None) if isinstance(result, dict) else None


def relax_document(doc, stage_doc, relax, channel):
    """`(doc, applied)` - the compliance output with the relaxation applied
    where it is earned, and `{result_id: record}` for what it did."""
    out = copy.deepcopy(doc)
    applied = {}
    if not isinstance(out, dict) or not isinstance(out.get("results"), list):
        return out, applied
    index = index_material(stage_doc)
    for i, result in enumerate(out["results"]):
        ident = result_id(result)
        material = index.get(ident) if ident else None
        new_result, record = relax_result(result, material, relax, channel)
        out["results"][i] = new_result
        if record:
            applied[ident] = record
    return out, applied


USAGE = ("usage: blooper_relaxation.py <NN-compliance-checker.json> "
         "<stage-input.json> [channel] [--dry-run]")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen(argv, USAGE, flags=("--dry-run",))  # CF-0777
    if rc is not None:
        return rc
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if len(argv) < 2:
        print(USAGE)
        return 2
    out_path, stage_path = Path(argv[0]), Path(argv[1])
    doc = json.loads(out_path.read_text())
    stage_doc = json.loads(stage_path.read_text())
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in its `channel` field - the file is a dated record and
    # is not rewritten - so resolve it before the config is looked up.
    channel = resolve_channel(
        argv[2] if len(argv) > 2 else doc.get("channel", "example-film"))

    relax = load_relaxation(channel)
    if relax is None:
        print(f"no relaxation: {config_ref(channel)} is absent, switched off "
              f"or not legal - every verdict stands as written")
        return 0

    new_doc, applied = relax_document(doc, stage_doc, relax, channel)
    for result in new_doc.get("results", []):
        ident = result_id(result)
        record = applied.get(ident)
        if record:
            ids = ", ".join(m["id"] for m in record["marked_material"])
            print(f"{ident}: {RELAXABLE_VERDICT} -> {CAP_VERDICT} "
                  f"(blooper marker on {ids}; rights-holder match unchanged)")
        elif result.get("verdict") == RELAXABLE_VERDICT:
            print(f"{ident}: {RELAXABLE_VERDICT} stands "
                  f"(no {marker_field(relax)!r} marker, or the review is not "
                  f"the rights-holder check's)")
    if not dry_run:
        out_path.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{len(new_doc.get('results', []))} result(s), {len(applied)} relaxed"
          + (" (dry run, nothing written)" if dry_run else ""))
    return 0


@runlog.script("compliance-checker", "blooper-relaxation",
               name="blooper_relaxation.py")
def cli():
    """The command-line entry (CF-0107 accounting, same shape as
    check_contribution.py): main()'s return code becomes the exit code inside
    the run event, so a usage error (2) is recorded as `failed`. The pass
    itself is pure Python over the channel config and the stage file - no
    model call, no external binary - so there is no `child` event."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
