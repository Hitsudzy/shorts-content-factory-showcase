#!/usr/bin/env python3
"""CF-0067: hold a written batch's `reactions` to the meme layer's contract.

The reaction meme is a factory mechanism switched per channel (inserts/
meme.json). Content Researcher writes the *intent* of a reaction on a
specific beat of the commentary - "facepalm, on these words" - and the Video
Editor picks the file. The contract for the writer's half is the `selection`
block of the root spec, and this script reads it from there rather than
carrying a copy:

    inserts/meme.json -> selection
        script_field               "reactions"
        intent_vocabulary          the closed list of intents (keys)
        max_reactions_per_script   2
    channels/<channel>.json -> insert_layers.meme.enabled   the channel switch
    patterns/<pattern_id>.json -> meme_layer.allowed         the pattern gate

Per script the field is:

    "reactions": [
      {"beat_id": "r1",              # [a-z0-9][a-z0-9_-]*, unique in the script
       "intent": "facepalm",         # one of intent_vocabulary
       "beat_text": "<verbatim substring of the commentary>",
       "query": "<free text for CLIP>" | null}   # never a file name or an id
    ]

Absent or `[]` asks for no meme. The field may only be written when BOTH
gates are on; a request on a channel with the switch off, or on a pattern
that refuses, is flagged here with the gate's name (`layer_off` /
`pattern_refused`) - the Video Editor would answer it the same way and
count it, but a writer who wrote it did not read the config.

The meaning rule M3 (the meme carries a reaction the narration does not
voice) is the writer's and is NOT checked here - see SKILL.md, step 4.

CF-0388: `beat_text` is also the key the meme is chosen by - the Video Editor
matches its words against the library's `tags` (inserts/meme.json
selection.tag_match), and the meme lands on its first word. A beat of three
to eight words starting at the reaction word is what the writer is asked for;
outside that length the script gets a `warn` line, never a failure: 30 of the
31 reactions in the batches written before CF-0388 were whole sentences, and
a whole sentence still locates the beat - it only picks the meme by
incidental words.

CF-0811 (2026-10-19, the user: "there is not one meme insert in the
videos"): since 2026-10-08 the writer had asked for no meme at all - the
field was optional, and an optional field nobody is held to is a field that
stops being written. So when both gates are open the field is owed:

  * one or two reactions (`max_reactions_per_script`), or
  * zero with a recorded reason - `meme_none_reason`, one code of the closed
    set NONE_REASONS below, on the script itself. Zero without one is
    `meme_missing`, a failure. A reason beside a non-empty `reactions` is a
    failure too (the script says two things at once).

The gate codes (`layer_off`, `pattern_forbids`) are facts of the config, not
judgments: `--write` stamps them on every zero-reaction script whose gate is
closed, so that every script of a written batch says why it carries no meme
(the root's summary counts them). The judgment codes (`no_fitting_meme`,
`tone`) are the writer's; `no_room` is checked against the commentary's
length.

And a request is placed where a meme can be shown. The Video Editor gives a
meme a block of at least `placement.min_block_seconds` (3.0 s) that starts on
the beat's first word, so the beat has to have that much commentary after
it: at least ceil(min_block_seconds x rate) words of `commentary` from the
beat's first word to the end of the section (the payoff is protected - the
meme's block does not run into it), where the rate is this script's own
`narration.estimated_words_per_second` (check_narration_budget.py), else the
record's channel `words_per_second`, else FALLBACK_WORDS_PER_SECOND (4.0 -
the high side, which asks for more words, never fewer). Two reactions are at
least that many words apart, so that they do not ask for the same block. A
beat that breaks either is `meme_spot_short` / `meme_beats_too_close`: move
the beat earlier (or to another sentence), not the narration.

Every failure of this check is a structural fix - no rewrite attempt of any
other check is spent on it; fix the field and rerun.

Usage:

    python3 scripts/check_reactions.py <03-content-researcher.json> [--write]
    python3 scripts/check_reactions.py <03-content-researcher.json> --channel <id> --root <checkout>

Prints one line per script; exit 0 when every script is clean, 1 otherwise.
Without `--write` nothing is written back; with it only the gate codes of
`meme_none_reason` are (CF-0811), and the file is rewritten only when one
changed.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)
import _no_waiting as nw  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

from check_narration_budget import find_root

SPEC_PATH = ("inserts", "meme.json")

# CF-0317: the two register points a missing file can end this checker in. An
# insert library that is not in the checkout is a defect of the machine that
# will be there for every batch until somebody fixes it, so it is raised once
# as a standing note and not asked once per run.
POINT_ASSET = "researcher_missing_repo_asset"
POINT_CHANNEL = "researcher_missing_channel_config"
BEAT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REQUIRED_KEYS = ("beat_id", "intent", "beat_text")
OPTIONAL_KEYS = ("query",)
COMMENTARY_KEY = "commentary"
# CF-0388: the length a beat_text should have to work as a selection key.
BEAT_WORDS_MIN, BEAT_WORDS_MAX = 3, 8
GATE_LAYER_OFF, GATE_PATTERN_REFUSED = "layer_off", "pattern_refused"
# The Video Editor's outcome names for the two gates (inserts/meme.json
# metadata.outcomes); the checker names the gate the same way so that a
# reviewer reads one vocabulary on both sides of the hand-off.

# CF-0811: zero memes on a script whose gates are open is allowed only with a
# recorded reason - one code of this closed set in `meme_none_reason`.
NONE_REASON_KEY = "meme_none_reason"
REASON_LAYER_OFF, REASON_PATTERN_FORBIDS = "layer_off", "pattern_forbids"
REASON_NO_ROOM, REASON_NO_FITTING_MEME, REASON_TONE = "no_room", "no_fitting_meme", "tone"
NONE_REASONS = {
    REASON_LAYER_OFF: "gate: the channel's insert_layers.meme.enabled is not true "
                      "(stamped by --write)",
    REASON_PATTERN_FORBIDS: "gate: the drawn pattern's meme_layer.allowed is not true "
                            "(stamped by --write)",
    REASON_NO_ROOM: "the whole commentary is shorter than one meme spot (fewer words "
                    "than the spot rule asks for) - checked",
    REASON_NO_FITTING_MEME: "the writer's: no entry of the channel's bank carries a reaction "
                            "the commentary leaves unsaid (M3) on any beat that has the room",
    REASON_TONE: "the writer's: the subject is not one to react to with a joke - a death, "
                 "an injury, a disaster, a crime with victims",
}
GATE_REASONS = (REASON_LAYER_OFF, REASON_PATTERN_FORBIDS)
# Problem codes of CF-0811, named in the failure lines.
CODE_MISSING = "meme_missing"
CODE_SPOT_SHORT = "meme_spot_short"
CODE_TOO_CLOSE = "meme_beats_too_close"
# The rate a script without its narration record is read at - the high side
# of the voices measured (3.3-3.7 w/s), so the spot asks for more words.
FALLBACK_WORDS_PER_SECOND = 4.0
NARRATION_RECORD_KEY = "narration"   # = check_narration_budget.py RECORD_KEY


def load_spec(root=None):
    """The `selection` block of inserts/meme.json plus the asset suffixes,
    which are what a query must not look like. Raises when the spec is
    missing - this script carries no vocabulary of its own."""
    root = root or find_root()
    path = root.joinpath(*SPEC_PATH)
    if not path.exists():
        raise nw.CannotAnswer(f"no meme spec at {path}", point=POINT_ASSET, file='inserts/meme.json')
    spec = json.loads(path.read_text())
    sel = spec.get("selection")
    if not isinstance(sel, dict) or not isinstance(sel.get("intent_vocabulary"), dict):
        raise nw.CannotAnswer(f"{path}: selection.intent_vocabulary is missing", point=POINT_ASSET, file='inserts/meme.json')
    floor = spec.get("asset_floor", {})
    return {
        "field": sel.get("script_field", "reactions"),
        "vocabulary": sorted(sel["intent_vocabulary"]),
        "max": int(sel.get("max_reactions_per_script", 2)),
        "suffixes": tuple(floor.get("still_suffixes", []) + floor.get("animated_suffixes", [])),
        "min_block_seconds": float((spec.get("placement") or {}).get("min_block_seconds", 3.0)),
        "source": f"inserts/meme.json#selection",
    }


def load_channel_config(channel, root=None):
    root = root or find_root()
    path = root / "channels" / f"{channel}.json"
    if not path.exists():
        raise nw.CannotAnswer(f"no channel config at {path}", point=POINT_CHANNEL,
                              what="channel config", channel=channel)
    return json.loads(path.read_text())


def load_patterns(root=None):
    """{pattern_id: pattern dict} for every patterns/<id>.json (rhythms.json
    is the rhythm vocabulary, not a pattern, and is left out)."""
    root = root or find_root()
    out = {}
    for path in sorted((root / "patterns").glob("*.json")):
        if path.name == "rhythms.json":
            continue
        out[path.stem] = json.loads(path.read_text())
    return out


def channel_switch(channel_cfg):
    """`insert_layers.meme.enabled`, False when the block is absent - a
    channel that has not said yes has said no."""
    layer = (channel_cfg.get("insert_layers") or {}).get("meme") or {}
    return layer.get("enabled") is True


def pattern_gate(pattern):
    """`meme_layer.allowed`, False when absent for the same reason."""
    return ((pattern or {}).get("meme_layer") or {}).get("allowed") is True


def looks_like_file_or_id(query, suffixes, library_ids=()):
    """A query is words for CLIP. A path, a file suffix, an index id, or a
    single token with the shape of an id ('meme-0007', 'img_12') is a writer
    choosing the file, which pre-empts the Video Editor's gate."""
    q = str(query).strip()
    low = q.lower()
    if q in library_ids:
        return "is a library asset id"
    if "/" in q or "\\" in q:
        return "contains a path separator"
    if suffixes and low.endswith(tuple(s.lower() for s in suffixes)):
        return "ends in a file suffix"
    if " " not in q and re.search(r"[0-9_.\-]", q):
        return "is a single id-shaped token, not words"
    return None


def check_reaction(r, i, commentary, spec, seen_ids, library_ids=()):
    """Problems with one entry; every message names the field it is about."""
    field = spec["field"]
    p = f"{field}[{i}]"
    problems = []
    if not isinstance(r, dict):
        return [f"{p}: must be an object, got {type(r).__name__}"]
    for k in REQUIRED_KEYS:
        if k not in r:
            problems.append(f"{p}.{k}: missing")
    extra = sorted(set(r) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if extra:
        problems.append(f"{p}: unknown key(s) {extra} - the script names an intent and "
                        f"words, never a file or an id (inserts/meme.json honesty_rules)")
    beat_id = r.get("beat_id")
    if "beat_id" in r:
        if not isinstance(beat_id, str) or not BEAT_ID_RE.match(beat_id):
            problems.append(f"{p}.beat_id: {beat_id!r} must match {BEAT_ID_RE.pattern}")
        elif beat_id in seen_ids:
            problems.append(f"{p}.beat_id: {beat_id!r} is not unique in this script")
        seen_ids.add(beat_id)
    if "intent" in r and r["intent"] not in spec["vocabulary"]:
        problems.append(f"{p}.intent: {r['intent']!r} is not in {spec['source']} "
                        f"intent_vocabulary {spec['vocabulary']}")
    if "beat_text" in r:
        bt = r["beat_text"]
        if not isinstance(bt, str) or not bt.strip():
            problems.append(f"{p}.beat_text: must be a non-empty string")
        elif bt not in (commentary or ""):
            problems.append(f"{p}.beat_text: not a verbatim substring of `{COMMENTARY_KEY}` - "
                            f"the Video Editor locates the beat by these exact words")
    if "query" in r and r["query"] is not None:
        q = r["query"]
        if not isinstance(q, str) or not q.strip():
            problems.append(f"{p}.query: must be null or a non-empty string")
        else:
            why = looks_like_file_or_id(q, spec["suffixes"], library_ids)
            if why:
                problems.append(f"{p}.query: {q!r} {why} - the query is words for the CLIP "
                                f"ranking; the file is the Video Editor's to choose")
    return problems


def beat_text_warnings(script, spec):
    """CF-0388: warnings (never problems) for a reaction whose beat_text is
    outside BEAT_WORDS_MIN..BEAT_WORDS_MAX words. Only well-formed entries
    are read; a malformed one is check_reaction's to name."""
    field = spec["field"]
    reactions = script.get(field)
    if not isinstance(reactions, list):
        return []
    warnings = []
    for i, r in enumerate(reactions):
        bt = r.get("beat_text") if isinstance(r, dict) else None
        if not isinstance(bt, str) or not bt.strip():
            continue
        n = len(bt.split())
        if BEAT_WORDS_MIN <= n <= BEAT_WORDS_MAX:
            continue
        side = "long" if n > BEAT_WORDS_MAX else "short"
        warnings.append(f"{field}[{i}].beat_text: {n} words, too {side} for a selection key "
                        f"({BEAT_WORDS_MIN}-{BEAT_WORDS_MAX} words starting at the reaction "
                        f"word) - the Video Editor matches its words against the library's "
                        f"tags and lands the meme on its first word (CF-0388)")
    return warnings


def gate_state(script, channel_cfg, patterns):
    """Which gate answers this script (CF-0811): `open` (both on),
    REASON_LAYER_OFF, REASON_PATTERN_FORBIDS, or `unknown` (the switch is on
    and the script's pattern cannot be read - no pattern_id, or a file that is
    not there; check_script names that when a request rides on it)."""
    if not channel_switch(channel_cfg):
        return REASON_LAYER_OFF
    pid = (script.get("pattern") or {}).get("pattern_id")
    if pid is None or pid not in patterns:
        return "unknown"
    if not pattern_gate(patterns[pid]):
        return REASON_PATTERN_FORBIDS
    return "open"


def speech_rate(script):
    """(words per second, where it came from) for the spot rule: this
    script's own estimated rate, else the narration record's channel rate,
    else FALLBACK_WORDS_PER_SECOND."""
    rec = script.get(NARRATION_RECORD_KEY)
    rec = rec if isinstance(rec, dict) else {}
    for key in ("estimated_words_per_second", "words_per_second"):
        v = rec.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v), f"{NARRATION_RECORD_KEY}.{key}"
    return FALLBACK_WORDS_PER_SECOND, "fallback"


def spot_words(script, spec):
    """(N, rate, source): the words of commentary a meme's beat needs from
    its first word on - ceil(min_block_seconds x rate)."""
    rate, source = speech_rate(script)
    floor = float(spec.get("min_block_seconds", 3.0))
    return int(math.ceil(floor * rate - 1e-9)), rate, source


def _words(text):
    return len((text or "").split())


def spot_problems(script, spec):
    """CF-0811: every well-formed request sits where a block of the meme
    floor fits after it, and two of them are that far apart. Malformed
    entries (no beat_text, not a substring) are check_reaction's."""
    field = spec["field"]
    commentary = script.get(COMMENTARY_KEY)
    reactions = script.get(field)
    if not isinstance(commentary, str) or not isinstance(reactions, list):
        return []
    need, rate, source = spot_words(script, spec)
    floor = float(spec.get("min_block_seconds", 3.0))
    total = _words(commentary)
    starts, problems = [], []
    for i, r in enumerate(reactions):
        bt = r.get("beat_text") if isinstance(r, dict) else None
        if not isinstance(bt, str) or not bt.strip() or bt not in commentary:
            continue
        at = _words(commentary[:commentary.index(bt)])
        left = total - at
        starts.append((at, i))
        if left < need:
            problems.append(
                f"{field}[{i}].beat_text: {left} word(s) of `{COMMENTARY_KEY}` from the beat's "
                f"first word to the end of the section, a meme needs {need} - a block of "
                f"{floor:g} s at {rate:g} w/s ({source}) ({CODE_SPOT_SHORT}); put the beat "
                f"earlier, the narration stays as it is")
    starts.sort()
    for (a, ia), (b, ib) in zip(starts, starts[1:]):
        if b - a < need:
            problems.append(
                f"{field}[{ib}].beat_text: starts {b - a} word(s) after {field}[{ia}]'s, "
                f"two memes need {need} between them or they ask for the same block "
                f"({CODE_TOO_CLOSE})")
    return problems


def none_reason_problems(script, spec, channel_cfg, patterns, channel="<channel>"):
    """CF-0811: the zero-meme rule. Returns problems for `meme_none_reason`
    and for a zero-reaction script whose gates are open."""
    field = spec["field"]
    reactions = script.get(field)
    n = len(reactions) if isinstance(reactions, list) else 0
    reason = script.get(NONE_REASON_KEY)
    problems = []
    if reason is not None and reason not in NONE_REASONS:
        return [f"{NONE_REASON_KEY}: {reason!r} is not one of {sorted(NONE_REASONS)}"]
    if n:
        if reason is not None:
            problems.append(f"{NONE_REASON_KEY}: {reason!r} written beside {n} reaction(s) - "
                            f"a reason is for zero; drop one of the two")
        return problems
    if reactions is not None and not isinstance(reactions, list):
        return problems
    gate = gate_state(script, channel_cfg, patterns)
    pid = (script.get("pattern") or {}).get("pattern_id")
    if gate == "unknown":
        return problems
    if gate != "open":
        if reason in GATE_REASONS and reason != gate:
            problems.append(f"{NONE_REASON_KEY}: {reason!r}, but the gate that is closed is "
                            f"{gate!r} - rerun with --write")
        return problems
    if reason is None:
        problems.append(
            f"{field}: none, and the meme layer is on (channels/{channel}.json) and pattern "
            f"{pid!r} allows it ({CODE_MISSING}) - mark one or two reactions (step 4), or record "
            f"why not in {NONE_REASON_KEY}: one of "
            f"{[r for r in NONE_REASONS if r not in GATE_REASONS]}")
    elif reason in GATE_REASONS:
        problems.append(f"{NONE_REASON_KEY}: {reason!r}, but both gates are open on this "
                        f"script (channel switch on, pattern {pid!r} allows) - mark one or two "
                        f"reactions ({CODE_MISSING})")
    elif reason == REASON_NO_ROOM:
        need, rate, _src = spot_words(script, spec)
        have = _words(script.get(COMMENTARY_KEY))
        if have >= need:
            problems.append(f"{NONE_REASON_KEY}: {REASON_NO_ROOM!r}, but `{COMMENTARY_KEY}` has "
                            f"{have} words and one meme spot needs {need} - there is room; "
                            f"mark a reaction on its first sentences ({CODE_MISSING})")
    return problems


def stamp_gate_reasons(data, spec, channel_cfg, patterns):
    """CF-0811 `--write`: put the closed gate's code into `meme_none_reason`
    of every script that asks for no meme and whose gate is closed (a
    judgment code the writer wrote is replaced - the gate is the reason).
    Returns the script ids it changed. Nothing else is touched."""
    field = spec["field"]
    changed = []
    for s in data.get("scripts", []):
        if s.get(field) not in (None, []):
            continue
        gate = gate_state(s, channel_cfg, patterns)
        if gate in GATE_REASONS and s.get(NONE_REASON_KEY) != gate:
            s[NONE_REASON_KEY] = gate
            changed.append(s.get("script_id"))
    return changed


def check_script(script, spec, channel_cfg, patterns, channel="<channel>", library_ids=()):
    """Problems with one script's `reactions` and, since CF-0811, with its
    zero: absent or [] is clean only when a gate is closed or
    `meme_none_reason` says why."""
    field = spec["field"]
    reactions = script.get(field)
    zero = none_reason_problems(script, spec, channel_cfg, patterns, channel)
    if reactions is None or reactions == []:
        return zero
    if not isinstance(reactions, list):
        return [f"{field}: must be a list, got {type(reactions).__name__}"]
    problems = list(zero)
    if not channel_switch(channel_cfg):
        problems.append(f"{field}: written while channels/{channel}.json insert_layers.meme.enabled "
                        f"is not true - the layer is off on this channel ({GATE_LAYER_OFF}); "
                        f"drop the field")
    order = script.get("pattern") or {}
    pid = order.get("pattern_id")
    if pid is None:
        problems.append(f"{field}: the script carries no pattern.pattern_id, so the pattern "
                        f"gate meme_layer.allowed cannot be read ({GATE_PATTERN_REFUSED})")
    elif pid not in patterns:
        problems.append(f"{field}: pattern {pid!r} is unknown, so meme_layer.allowed cannot "
                        f"be read ({GATE_PATTERN_REFUSED})")
    elif not pattern_gate(patterns[pid]):
        problems.append(f"{field}: written on pattern {pid!r} whose patterns/{pid}.json "
                        f"meme_layer.allowed is not true ({GATE_PATTERN_REFUSED}); drop the field")
    if len(reactions) > spec["max"]:
        problems.append(f"{field}: {len(reactions)} entries, {spec['source']} "
                        f"max_reactions_per_script is {spec['max']}")
    seen = set()
    for i, r in enumerate(reactions):
        problems += check_reaction(r, i, script.get(COMMENTARY_KEY), spec, seen, library_ids)
    problems += spot_problems(script, spec)
    return problems


def check_batch_data(data, spec, channel_cfg, patterns, channel="<channel>",
                     library_ids=(), out=print):
    """The whole batch against synthetic or real config dicts. Returns the
    problems, each prefixed with the script id."""
    field = spec["field"]
    problems = []
    for s in data.get("scripts", []):
        sid = s.get("script_id")
        found = check_script(s, spec, channel_cfg, patterns, channel, library_ids)
        n = len(s.get(field) or []) if isinstance(s.get(field), list) else 0
        if found:
            out(f"  FAIL {sid}: {len(found)} problem(s)")
            problems += [f"{sid}: {p}" for p in found]
        elif n:
            intents = ", ".join(f"{r.get('beat_id')}={r.get('intent')}" for r in s[field])
            out(f"  ok   {sid}: {n} reaction(s) - {intents}")
        else:
            why = s.get(NONE_REASON_KEY)
            out(f"  none {sid}: no reactions requested"
                + (f" - {NONE_REASON_KEY}={why}" if why else ""))
        for w in beat_text_warnings(s, spec):
            out(f"  warn {sid}: {w}")
    return problems


# CF-0393: a channel may name its own meme bank (insert_layers.meme.bank,
# shared/inserts/memes-<channel>/); the rule for the name is the root's
# shared/inserts/inserts_lib.py bank_name(), restated here only as far as
# this check needs it.
BANK_RE = re.compile(r"^memes(-[a-z0-9][a-z0-9-]*)?$")


def library_index_path(root, channel_cfg=None):
    """The index of the library the channel's memes come from: its own bank
    when `insert_layers.meme.bank` names one, shared/inserts/memes/ when it
    names none. A malformed name, or a named bank missing on a channel whose
    layer is on, ends the check (CannotAnswer) - the Video Editor would refuse
    it too, and the default (cinema) bank is never read in its place."""
    layer = ((channel_cfg or {}).get("insert_layers") or {}).get("meme") or {}
    bank = layer.get("bank") if isinstance(layer, dict) else None
    if bank is None:
        return root / "shared" / "inserts" / "memes" / "index.json"
    name = str(bank).strip().rstrip("/")
    if name.startswith("shared/inserts/"):
        name = name[len("shared/inserts/"):]
    if not BANK_RE.match(name):
        raise nw.CannotAnswer(f"insert_layers.meme.bank {bank!r} is not a folder "
                              f"shared/inserts/memes-<channel>/ (CF-0393)",
                              point=POINT_ASSET, file=f"shared/inserts/{name}/index.json")
    path = root / "shared" / "inserts" / name / "index.json"
    if not path.exists() and channel_switch(channel_cfg or {}):
        raise nw.CannotAnswer(f"the channel's meme bank has no index at {path} - its memes "
                              f"come from that bank only (CF-0393)",
                              point=POINT_ASSET, file=f"shared/inserts/{name}/index.json")
    return path


def library_asset_ids(root, channel_cfg=None):
    """Ids and file names of the channel's meme library index (its own bank,
    CF-0393, or shared/inserts/memes/index.json) when it is on this disk - a
    query equal to one of them is a chosen file. Optional."""
    path = library_index_path(root, channel_cfg)
    if not path.exists():
        return ()
    try:
        entries = json.loads(path.read_text()).get("entries", [])
    except (ValueError, AttributeError):
        return ()
    ids = set()
    for e in entries:
        for k in ("id", "file"):
            if isinstance(e.get(k), str):
                ids.add(e[k])
    return frozenset(ids)


def check_batch(path, root=None, channel=None, write=False):
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
    if write:
        stamped = stamp_gate_reasons(data, spec, channel_cfg, patterns)
        if stamped:
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            print(f"{path}: {NONE_REASON_KEY} stamped on {len(stamped)} script(s) whose gate "
                  f"is closed: {', '.join(str(x) for x in stamped)}")
    print(f"{path}: {len(data.get('scripts', []))} script(s); channel switch "
          f"insert_layers.meme.enabled={'true' if channel_switch(channel_cfg) else 'false'}, "
          f"max {spec['max']} per script, vocabulary from {spec['source']}")
    return check_batch_data(data, spec, channel_cfg, patterns, channel,
                            library_asset_ids(root, channel_cfg))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--channel", default=None, help="override the file's `channel`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--write", action="store_true",
                    help="stamp the closed gate's code into meme_none_reason (CF-0811)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    try:
        problems = check_batch(args.batch_file, root=root, channel=args.channel,
                               write=args.write)
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


@runlog.script("content-researcher", "check-reactions", name="check_reactions.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = at least one line is not
    ok, 2 = usage) is recorded as `failed` (CF-0107). The check - the meme spec -
    is pure Python over the batch file, the channel config and the specs: no
    external binary, no model call, so no `child` events. Without a batch
    (no RUNLOG_BATCH, no batch-shaped path) the library warns once on stderr
    and records nothing; the check itself is unchanged."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
