#!/usr/bin/env python3
"""CF-0068: hold a written batch's `sounds` to the sound layer's contract.

The sound insert - a recognisable game or cartoon sound of at most 1.5 s from
shared/inserts/sounds/ - is a factory mechanism switched per channel
(inserts/sound.json). Content Researcher writes the *intent* of a sound on a
specific beat of the commentary - "record scratch, on these words" - and the
Video Editor picks the file by the intent's tags and mixes it. The contract
for the writer's half is the `selection` block of the root spec, and this
script reads it from there rather than carrying a copy:

    inserts/sound.json -> selection
        script_field               "sounds"
        intent_vocabulary          the closed list of intents (keys)
        max_sounds_per_script      2
    inserts/sound.json -> placement.protected_sections   ["hook", "payoff"]
    channels/<channel>.json -> insert_layers.sound.enabled   the channel switch
    patterns/<pattern_id>.json -> sound_layer.allowed         the pattern gate

Per script the field is:

    "sounds": [
      {"beat_id": "s1",              # [a-z0-9][a-z0-9_-]*, unique in sounds[]
       "intent": "record_scratch",   # one of intent_vocabulary
       "beat_text": "<verbatim substring of the commentary>"}
    ]

There is no `query`: a sound is matched on a closed set of tags, and a free
string would be a tag nobody agreed on (inserts/sound.json absent_means). A
`file`, an `asset_id` or any other key is a writer choosing the file, which
pre-empts the Video Editor's gate, and is rejected here.

`sounds[].beat_id` is its own namespace: it may repeat a `reactions[]`
beat_id, and a sound may share a beat with a reaction (the two planes do not
compete - one is a picture on a block, the other a moment in the mix).

Absent or `[]` asks for no sound. The field may only be written when BOTH
gates are on; a request on a channel with the switch off, or on a pattern
that refuses, is flagged here with the gate's name (`layer_off` /
`pattern_refused`) - the Video Editor would answer it the same way and
count it, but a writer who wrote it did not read the config.

The meaning rule S3 (the sound punctuates a reaction the narration does not
voice) is the writer's and is NOT checked here - see SKILL.md, step 4.

Usage:

    python3 scripts/check_sounds.py <03-content-researcher.json>
    python3 scripts/check_sounds.py <03-content-researcher.json> --channel <id> --root <checkout>

Prints one line per script; exit 0 when every script is clean, 1 otherwise.
Read-only: nothing is written back.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)
import _no_waiting as nw  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

from check_narration_budget import find_root
from check_reactions import load_channel_config, load_patterns

SPEC_PATH = ("inserts", "sound.json")

# CF-0317: the two register points a missing file can end this checker in. An
# insert library that is not in the checkout is a defect of the machine that
# will be there for every batch until somebody fixes it, so it is raised once
# as a standing note and not asked once per run.
POINT_ASSET = "researcher_missing_repo_asset"
POINT_CHANNEL = "researcher_missing_channel_config"
BEAT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REQUIRED_KEYS = ("beat_id", "intent", "beat_text")
COMMENTARY_KEY = "commentary"
GATE_LAYER_OFF, GATE_PATTERN_REFUSED = "layer_off", "pattern_refused"
# The Video Editor's outcome names for the two gates (inserts/sound.json
# metadata.outcomes); the checker names the gate the same way so that a
# reviewer reads one vocabulary on both sides of the hand-off.


def load_spec(root=None):
    """The `selection` block of inserts/sound.json plus the protected
    sections. Raises when the spec is missing - this script carries no
    vocabulary of its own."""
    root = root or find_root()
    path = root.joinpath(*SPEC_PATH)
    if not path.exists():
        raise nw.CannotAnswer(f"no sound spec at {path}", point=POINT_ASSET, file='inserts/sound.json')
    spec = json.loads(path.read_text())
    sel = spec.get("selection")
    if not isinstance(sel, dict) or not isinstance(sel.get("intent_vocabulary"), dict):
        raise nw.CannotAnswer(f"{path}: selection.intent_vocabulary is missing", point=POINT_ASSET, file='inserts/sound.json')
    placement = spec.get("placement") or {}
    return {
        "field": sel.get("script_field", "sounds"),
        "vocabulary": sorted(sel["intent_vocabulary"]),
        "max": int(sel.get("max_sounds_per_script", 2)),
        "protected": tuple(placement.get("protected_sections", ("hook", "payoff"))),
        "source": "inserts/sound.json#selection",
    }


def channel_switch(channel_cfg):
    """`insert_layers.sound.enabled`, False when the block is absent - a
    channel that has not said yes has said no."""
    layer = (channel_cfg.get("insert_layers") or {}).get("sound") or {}
    return layer.get("enabled") is True


def pattern_gate(pattern):
    """`sound_layer.allowed`, False when absent for the same reason."""
    return ((pattern or {}).get("sound_layer") or {}).get("allowed") is True


def check_sound(s, i, script, spec, seen_ids):
    """Problems with one entry; every message names the field it is about."""
    field = spec["field"]
    p = f"{field}[{i}]"
    problems = []
    if not isinstance(s, dict):
        return [f"{p}: must be an object, got {type(s).__name__}"]
    for k in REQUIRED_KEYS:
        if k not in s:
            problems.append(f"{p}.{k}: missing")
    extra = sorted(set(s) - set(REQUIRED_KEYS))
    if extra:
        problems.append(f"{p}: unknown key(s) {extra} - the script names an intent and a beat, "
                        f"never a query, a file or an id; the file is the Video Editor's to "
                        f"choose by the intent's tags (inserts/sound.json honesty_rules)")
    beat_id = s.get("beat_id")
    if "beat_id" in s:
        if not isinstance(beat_id, str) or not BEAT_ID_RE.match(beat_id):
            problems.append(f"{p}.beat_id: {beat_id!r} must match {BEAT_ID_RE.pattern}")
        elif beat_id in seen_ids:
            problems.append(f"{p}.beat_id: {beat_id!r} is not unique in this script's {field}[]")
        seen_ids.add(beat_id)
    if "intent" in s and s["intent"] not in spec["vocabulary"]:
        problems.append(f"{p}.intent: {s['intent']!r} is not in {spec['source']} "
                        f"intent_vocabulary {spec['vocabulary']}")
    if "beat_text" in s:
        bt = s["beat_text"]
        if not isinstance(bt, str) or not bt.strip():
            problems.append(f"{p}.beat_text: must be a non-empty string")
        elif bt not in (script.get(COMMENTARY_KEY) or ""):
            where = [sec for sec in spec["protected"]
                     if isinstance(script.get(sec), str) and bt in script[sec]]
            if where:
                problems.append(f"{p}.beat_text: found in `{where[0]}`, not in `{COMMENTARY_KEY}` - "
                                f"{', '.join(spec['protected'])} are protected sections "
                                f"(inserts/sound.json placement.protected_sections): a sound "
                                f"never lands on the claim or the verdict")
            else:
                problems.append(f"{p}.beat_text: not a verbatim substring of `{COMMENTARY_KEY}` - "
                                f"the Video Editor locates the beat's first word by these exact "
                                f"words in words.json")
    return problems


def check_script(script, spec, channel_cfg, patterns, channel="<channel>"):
    """Problems with one script's `sounds`. Absent or [] is clean."""
    field = spec["field"]
    sounds = script.get(field)
    if sounds is None or sounds == []:
        return []
    if not isinstance(sounds, list):
        return [f"{field}: must be a list, got {type(sounds).__name__}"]
    problems = []
    if not channel_switch(channel_cfg):
        problems.append(f"{field}: written while channels/{channel}.json insert_layers.sound.enabled "
                        f"is not true - the layer is off on this channel ({GATE_LAYER_OFF}); "
                        f"drop the field")
    order = script.get("pattern") or {}
    pid = order.get("pattern_id")
    if pid is None:
        problems.append(f"{field}: the script carries no pattern.pattern_id, so the pattern "
                        f"gate sound_layer.allowed cannot be read ({GATE_PATTERN_REFUSED})")
    elif pid not in patterns:
        problems.append(f"{field}: pattern {pid!r} is unknown, so sound_layer.allowed cannot "
                        f"be read ({GATE_PATTERN_REFUSED})")
    elif not pattern_gate(patterns[pid]):
        problems.append(f"{field}: written on pattern {pid!r} whose patterns/{pid}.json "
                        f"sound_layer.allowed is not true ({GATE_PATTERN_REFUSED}); drop the field")
    if len(sounds) > spec["max"]:
        problems.append(f"{field}: {len(sounds)} entries, {spec['source']} "
                        f"max_sounds_per_script is {spec['max']}")
    seen = set()
    for i, s in enumerate(sounds):
        problems += check_sound(s, i, script, spec, seen)
    return problems


def check_batch_data(data, spec, channel_cfg, patterns, channel="<channel>", out=print):
    """The whole batch against synthetic or real config dicts. Returns the
    problems, each prefixed with the script id."""
    field = spec["field"]
    problems = []
    for s in data.get("scripts", []):
        sid = s.get("script_id")
        found = check_script(s, spec, channel_cfg, patterns, channel)
        n = len(s.get(field) or []) if isinstance(s.get(field), list) else 0
        if found:
            out(f"  FAIL {sid}: {len(found)} problem(s)")
            problems += [f"{sid}: {p}" for p in found]
        elif n:
            intents = ", ".join(f"{r.get('beat_id')}={r.get('intent')}" for r in s[field])
            out(f"  ok   {sid}: {n} sound(s) - {intents}")
        else:
            out(f"  none {sid}: no sounds requested")
    return problems


def check_batch(path, root=None, channel=None):
    root = root or find_root()
    data = json.loads(Path(path).read_text())
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in this field - the file is a dated record and is not
    # rewritten - so resolve it before anything is looked up under it.
    channel = resolve_channel(channel or data.get("channel"), root)
    if not channel:
        raise ValueError(f"{path}: no `channel` field and no --channel given")
    spec = load_spec(root)
    channel_cfg = load_channel_config(channel, root)
    patterns = load_patterns(root)
    print(f"{path}: {len(data.get('scripts', []))} script(s); channel switch "
          f"insert_layers.sound.enabled={'true' if channel_switch(channel_cfg) else 'false'}, "
          f"max {spec['max']} per script, vocabulary from {spec['source']}")
    return check_batch_data(data, spec, channel_cfg, patterns, channel)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--channel", default=None, help="override the file's `channel`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    try:
        problems = check_batch(args.batch_file, root=root, channel=args.channel)
    except nw.CannotAnswer as exc:
        # CF-0317: the library or the channel config is not there. That is a
        # fact about this checkout, not about this batch, and it will not
        # change inside the run - so the check names the code the stage
        # records and exits, instead of raising a traceback at a person who
        # is not at the machine.
        print(f"{Path(__file__).name}: {exc}", file=sys.stderr)
        print(nw.refuse(exc.point, **exc.note_fields()), file=sys.stderr)
        return nw.EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


@runlog.script("content-researcher", "check-sounds", name="check_sounds.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = at least one line is not
    ok, 2 = usage) is recorded as `failed` (CF-0107). The check - the sound spec -
    is pure Python over the batch file, the channel config and the specs: no
    external binary, no model call, so no `child` events. Without a batch
    (no RUNLOG_BATCH, no batch-shaped path) the library warns once on stderr
    and records nothing; the check itself is unchanged."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
