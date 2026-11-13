#!/usr/bin/env python3
"""CF-0068: the sound insert - plan the sound inserts for one video.

The contract is `inserts/sound.json` in the factory root and nothing else;
this file executes it and carries no paraphrase of it. In one line: the
writer names an *intent* on a *beat* of the commentary (`sounds[]` in
03-content-researcher.json), the editor chooses the *file* from the factory
library (shared/inserts/sounds/index.json) by its tags, fixes the moment from
words.json, applies the slot rules, and every request is answered in
`sound_requested`/`sound_delivered` with one of the closed outcomes - never
with a file that matched no tag, a moment the request did not name, or a
sound stretched to fit.

What one request goes through, in order (the spec's "pattern, beat, slot,
asset"):

    layer_off        channels/<channel>.json insert_layers.sound.enabled is not true
    pattern_refused  patterns/<pattern_id>.json sound_layer.allowed is not true
    beat_missing_in_script
                     beat_text is not in the script's hook + commentary +
                     payoff either - the sound is asked for on a sentence the
                     video never says
    beat_unmatched_in_alignment
                     the words are in the script and the forced alignment did
                     not give them back - ours to fix, and the answer carries
                     the evidence (CF-0235; S1 makes at_seconds the start of
                     the beat's first word, and with no beat there is no
                     moment, no offset and no guess)
    beat_no_alignment
                     there is no words.json to look the beat up in at all
    no_slot          S2/S4: the slot would cross into the payoff's first word
                     or past the end of the voice (or sit inside the hook -
                     `protected_sections`), the anchor is inside
                     SOUND_MIN_GAP_SECONDS of an earlier placed sound, or
                     SOUND_MAX_PER_VIDEO is reached
    no_asset         every candidate failed the tag match, the asset gate or
                     S3's negative half
    placed           block_index / asset_id / at_seconds set

Selection (`selection.matching`/`ranking`): inserts_lib.eligible() first, so
a high-risk rights holder is skipped before it can rank and the skip is
recorded; then the entries answering the intent - a vocabulary tag equals an
entry tag exactly, or, underscores read as spaces, occurs as whole words in
the entry's description - ordered by match count descending and id
ascending; then the asset gate walked in that order, first pass wins. No
embedding, no score: the record carries `matched_tags`.

CF-0143 asked whether the meme layer's lead floor - place the insert only if
the leader stands clear of the field - belongs here too. It does not, for
two reasons, and neither is a deferral:

  * The statistic is a different shape. A meme is ranked by a CLIP dot
    product, a continuous number in a band so narrow (0.18-0.35 over the
    whole library) that an absolute floor picked off the model's usual range
    refused nothing at all - which is the bug CF-0143 fixed. A sound is
    ranked by *how many of the intent's tags it carries*: a small integer
    over a closed vocabulary, and an entry either carries a tag or it does
    not. `no_asset` already happens here whenever nothing carries one, so
    the mechanism CF-0143 had to build already exists in this layer.
  * A tie means the opposite thing. Two memes level at the top mean the
    query matched nothing in particular; two sounds with the same matched
    tags are two files that both genuinely answer the intent, and the tie is
    broken by id so that two renders of one script pick the same one.
    Demanding a lead would refuse exactly the case where the library got
    *better* - a second usable buzzer.

What this layer does have, and what CF-0143 could not calibrate, is
`selection.min_tag_matches: 1`: one tag is enough, so an entry whose
description merely contains "bell" answers `alert`. Whether one is the right
number is measurable the same way the meme floors were - labelled intents
against a library - but `shared/inserts/sounds/index.json` held 0 entries on
2026-09-08 (CF-0115 filled the memes only). There is nothing to measure yet,
and a number guessed without a library is what CF-0143 was cleaning up.

The asset gate: file present, a sound suffix, re-measured duration in
[asset_floor.min_duration_s, MAX_SOUND_SECONDS] (the index is a promise, the
file is the fact), the slot [at, at + duration_s] inside the commentary (S2,
per candidate because the length is the file's own), an audio stream and no
video stream (a file with a picture is a clip and is never placed), distinct
per video, and S3's negative half.

S3 (`meaning_rule`) is "not verified" and is reported as such: the negative
half here is mechanical - a word spoken over the slot equal to a matched tag
(underscores read as spaces) fails that candidate; the positive half - that
the sound punctuates something the words leave unsaid - is the writer's and
is only answerable after publication. Nothing here measures it.

Degradation: a sound is a fourth mix input over a soundtrack that is
complete without it. `apply_to_plan()` writes `sound` on the block whose
span contains the anchor (recorded, never chosen) and `plan["sound"]`, and
touches nothing else - not the block's asset, length, rhythm fields or
captions; a request that was not placed leaves every block identical and
build_soundtrack.py builds the mix it would have built with the layer off.

Factory root: FACTORY_ROOT or the checkout above this repo, the way
meme_layer.factory_root() finds it (shared with the meme layer, as are the
channel/pattern loaders, the beat lookup and the provenance merge).

Usage:
    sound_layer.py <plan.json> --script <03-content-researcher.json> --script-id <id>
        [--channel <id|path.json>] [--pattern <id>] [--root <factory root>]
        [--words <words.json>] [--write]
"""
import argparse
import json
import sys
from pathlib import Path

# CF-0132: stream_kinds() moved to common.py, uncapped ffprobe and all -
# meme_layer.py was asking the same question with a second command of its own,
# and neither wait had a ceiling. One definition, one ceiling.
from common import (SOUND_MAX_PER_VIDEO, SOUND_MIN_GAP_SECONDS, load_words,
                    stream_kinds)
import meme_layer
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from meme_layer import (BEAT_FAILURE_CODES, ChannelDataError, beat_failure, channel_of,
                        factory_root, _lib, load_channel, load_pattern, load_blacklist,
                        locate_beat, norm_tokens, spoken_over)

LAYER = "sound"
LIBRARY_KIND = "sound"
SPEC_REL = ("inserts", "sound.json")

OUTCOME_PLACED = "placed"
OUTCOME_LAYER_OFF = "layer_off"
OUTCOME_PATTERN_REFUSED = "pattern_refused"
# CF-0235: the same split CF-0193 made for the proof layer, from the same
# `meme_layer.beat_failure()`. One word answered two unrelated faults - "the
# video never says this sentence" and "the video says it and our aligner lost
# it" - and only the second is ours. The old code is kept for *reading*
# records written before 2026-09-15; nothing writes it.
OUTCOME_BEAT_NOT_FOUND = "beat_not_found"
LEGACY_OUTCOMES = (OUTCOME_BEAT_NOT_FOUND,)
OUTCOME_NO_SLOT = "no_slot"
OUTCOME_NO_ASSET = "no_asset"
OUTCOMES = ((OUTCOME_PLACED, OUTCOME_LAYER_OFF, OUTCOME_PATTERN_REFUSED)
            + BEAT_FAILURE_CODES + LEGACY_OUTCOMES
            + (OUTCOME_NO_SLOT, OUTCOME_NO_ASSET))

# Asset-gate skip reasons - closed list, written as `skip_reason` on the
# provenance record of every candidate the walk passed over.
# CF-0236: `skip_reason` is on every record this layer writes - null on the
# placed file, one of these names on every skipped one - and "cut before the
# ranking" is the one name SKIP_BLACKLIST, on the record inserts_lib.eligible()
# returns for a file whose rights holder is on the blacklist. Before
# 2026-09-26 that record carried no `skip_reason` key at all, and "not
# ranked" read as the key's absence.
SKIP_BLACKLIST = "blacklist"
SKIP_DISTINCT = "distinct_per_video"
SKIP_FILE_MISSING = "file_present"
SKIP_SUFFIX = "sound_suffix"
SKIP_DURATION = "duration_floor"          # outside [min_duration_s, MAX_SOUND_SECONDS]
SKIP_SLOT = "slot_protected"              # S2: the file's own length crosses the payoff / voice end
SKIP_NO_AUDIO = "audio_track"
SKIP_VIDEO = "video_track"
SKIP_MEANING = "meaning_negative_half"    # S3
SKIP_UNREADABLE = "unreadable"

# --------------------------------------------------------------------------
# spec, gates, library
# --------------------------------------------------------------------------

def load_spec(root):
    return json.loads((Path(root).joinpath(*SPEC_REL)).read_text())


def layer_enabled(channel_cfg):
    """insert_layers.sound.enabled is exactly true - the reading the meme
    and underlay switches get."""
    layers = (channel_cfg or {}).get("insert_layers") or {}
    switch = layers.get(LAYER) if isinstance(layers, dict) else None
    return isinstance(switch, dict) and switch.get("enabled") is True


def pattern_allows(pattern_cfg):
    """sound_layer.allowed is exactly true. A missing or silent pattern
    refuses: the pattern has to say it tolerates the interruption."""
    block = (pattern_cfg or {}).get("sound_layer")
    return isinstance(block, dict) and block.get("allowed") is True


def load_library(root):
    lib = _lib(root)
    return lib.load_index(LIBRARY_KIND, Path(root) / "shared" / "inserts")


# --------------------------------------------------------------------------
# matching (selection.matching) - tags, no embedding
# --------------------------------------------------------------------------

def intent_tags(spec, intent):
    vocab = spec["selection"]["intent_vocabulary"]
    entry = vocab.get(intent) or {}
    return [str(t).lower() for t in entry.get("tags") or []]


def _phrase_in(phrase_tokens, tokens):
    """A run of tokens equal to `phrase_tokens`, whole words only."""
    n = len(phrase_tokens)
    if not n or n > len(tokens):
        return False
    return any(tokens[i:i + n] == phrase_tokens for i in range(len(tokens) - n + 1))


def matched_tags(entry, tags):
    """The vocabulary tags an index entry answers, in vocabulary order: a
    tag equal to one of the entry's tags (lowercase), or the tag with its
    underscores read as spaces occurring as whole words in the description,
    case-insensitively. No stemming, no synonyms."""
    entry_tags = {str(t).lower() for t in entry.get("tags") or []}
    desc = norm_tokens(entry.get("description") or "")
    out = []
    for tag in tags:
        if tag in entry_tags or _phrase_in(tag.replace("_", " ").split(), desc):
            out.append(tag)
    return out


def rank_by_tags(entries, tags, min_matches):
    """[(matched_tags, entry)] for the entries answering the intent, by match
    count descending then id ascending - deterministic across renders."""
    ranked = []
    for e in entries:
        m = matched_tags(e, tags)
        if len(m) >= min_matches:
            ranked.append((m, e))
    ranked.sort(key=lambda t: (-len(t[0]), str(t[1].get("id"))))
    return ranked


# --------------------------------------------------------------------------
# the moment (S1), the block, the protected sections (S2)
# --------------------------------------------------------------------------

def anchor_seconds(beat_text, script, words):
    """S1: the start of the beat's first word in words.json, or None."""
    span = locate_beat(beat_text, script, words)
    if span is None:
        return None
    return float(words[span[0]]["start"])


def block_index_at(blocks, at):
    """The index of the block whose [start, end) span contains `at` -
    recorded, never chosen. Falls back to the last block starting before
    the moment (the last block's end is the voice end, which a moment inside
    the commentary never reaches), else None on an empty plan."""
    for i, b in enumerate(blocks):
        if b["start"] <= at < b["end"]:
            return i
    before = [i for i, b in enumerate(blocks) if b["start"] <= at]
    return before[-1] if before else None


def section_bounds(script, words, voice_end):
    """(hook_end, payoff_start): the end of the hook's last word and the
    start of the payoff's first word in the alignment - the two edges of
    `protected_sections`. Located the way a beat is (the alignment drifts
    after prosody restructuring); when a section cannot be located its
    word count stands in; a script with no such section leaves that edge at
    the video's own edge."""
    hook = norm_tokens(script.get("hook") or "")
    commentary = norm_tokens(script.get("commentary") or "")
    payoff = norm_tokens(script.get("payoff") or "")
    hook_end = 0.0
    if hook and words:
        span = locate_beat(script.get("hook"), script, words)
        if span is None and len(hook) <= len(words):
            span = (0, len(hook) - 1)
        if span is not None:
            hook_end = float(words[span[1]]["end"])
    payoff_start = float(voice_end)
    if payoff and words:
        span = locate_beat(script.get("payoff"), script, words)
        if span is None:
            k = len(hook) + len(commentary)
            span = (k, k) if k < len(words) else None
        if span is not None:
            payoff_start = min(payoff_start, float(words[span[0]]["start"]))
    return hook_end, payoff_start


# --------------------------------------------------------------------------
# the asset gate
# --------------------------------------------------------------------------

def speaks_a_tag(words, at, end, tags):
    """S3, negative half: a matched tag (underscores as spaces) spoken as
    whole words over [at, end]. Returns the tag, or None."""
    spoken = norm_tokens(spoken_over(words, at, end))
    for tag in tags:
        if _phrase_in(tag.replace("_", " ").split(), spoken):
            return tag
    return None


def check_asset(path, spec, lib, at, room, words, tags):
    """(ok, reason, duration_s) for one candidate file: present, a sound
    suffix, re-measured length inside the floor, the slot inside the
    commentary (S2 - `room` is the seconds between the anchor and the
    nearest protected edge), an audio stream and no video stream, S3."""
    floor = spec["asset_floor"]
    path = Path(path)
    if not path.exists():
        return False, SKIP_FILE_MISSING, None
    if path.suffix.lower() not in set(floor["suffixes"]) | set(lib.SOUND_SUFFIXES):
        return False, SKIP_SUFFIX, None
    try:
        duration = float(lib.measure_duration(path))
    except Exception:  # noqa: BLE001 - an unreadable file is a skip, not a crash
        return False, SKIP_UNREADABLE, None
    if not (float(floor["min_duration_s"]) <= duration <= float(lib.MAX_SOUND_SECONDS) + 1e-6):
        return False, SKIP_DURATION, duration
    if duration > room + 1e-6:
        return False, SKIP_SLOT, duration
    kinds = stream_kinds(path)
    if "audio" not in kinds:
        return False, SKIP_NO_AUDIO, duration
    if "video" in kinds:
        return False, SKIP_VIDEO, duration
    if speaks_a_tag(words, at, at + duration, tags):
        return False, SKIP_MEANING, duration
    return True, None, duration


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def _answer(beat_id, outcome, block_index=None, asset_id=None, at_seconds=None, evidence=None):
    """`evidence` (CF-0235) is written exactly when the outcome is one of the
    three beat diagnoses - the fragment searched for, how much of it is in the
    script and in the alignment, and the stretch that came closest as it was
    heard. A diagnosis about words that does not quote the words cannot be
    checked by anyone downstream."""
    a = {"beat_id": beat_id, "outcome": outcome, "block_index": block_index,
         "asset_id": asset_id, "at_seconds": at_seconds}
    if evidence is not None:
        a["evidence"] = evidence
    return a


def _record(lib, entry, check, block, beat_id, at, tags, skip_reason=None):
    rec = lib.provenance_record(entry, check, block=block)
    rec.update({"layer": LAYER, "beat_id": beat_id, "at_seconds": at,
                "matched_tags": list(tags), "skip_reason": skip_reason})
    if skip_reason:
        rec["skipped"] = True
    return rec


def plan_sounds(script, words, blocks, channel_cfg, pattern_cfg, root=None,
                voice_end=None, index=None, blacklist=None):
    """The whole decision for one video.

    Returns {sound_requested, sound_delivered, inserts (provenance records,
    placed first), placed [{block_index, record}], notes}. Pure with respect
    to `blocks` - apply_to_plan() is the only writer.
    """
    root = Path(root) if root else factory_root()
    spec = load_spec(root)
    sounds = script.get(spec["selection"]["script_field"]) or []
    requested, delivered, placed_recs, skipped_recs, placed, notes = [], [], [], [], [], []
    if not isinstance(sounds, list) or not sounds:
        return {"sound_requested": [], "sound_delivered": [], "inserts": [],
                "placed": [], "notes": notes}
    sounds = sounds[:int(spec["selection"]["max_sounds_per_script"])]
    for s in sounds:
        requested.append({"beat_id": s.get("beat_id"), "intent": s.get("intent")})

    enabled = layer_enabled(channel_cfg)
    allowed = pattern_allows(pattern_cfg)
    min_matches = int(spec["selection"]["min_tag_matches"])
    max_per_video = min(int(spec["placement"]["max_inserts_per_video"]), SOUND_MAX_PER_VIDEO)
    min_gap = max(float(spec["placement"]["min_gap_seconds"]), SOUND_MIN_GAP_SECONDS)
    min_duration = float(spec["asset_floor"]["min_duration_s"])
    if voice_end is None:
        voice_end = max((float(w.get("end", 0)) for w in words), default=0.0)
        if blocks:
            voice_end = max(voice_end, float(blocks[-1]["end"]))

    lib = index_entries = bl = no_list = None
    hook_end = payoff_start = None
    if enabled and allowed:
        lib = _lib(root)
        index = index if index is not None else load_library(root)
        index_entries = index.get("entries", [])
        if blacklist is not None:
            bl = blacklist
        else:
            # CF-0630: the channel's own rights-holder list. A channel without
            # one gets no sound: every file in this library is checked against
            # the list (only memes are exempt, CF-0389), and a file whose
            # holder cannot be checked is not placed - never with another
            # channel's list standing in.
            try:
                bl = load_blacklist(root, channel_of(channel_cfg))
            except ChannelDataError as e:
                no_list = str(e)
                notes.append(f"sound: no rights-holder list for channel "
                             f"{channel_of(channel_cfg)!r} - {no_list}; no sound file is "
                             f"taken, a holder that cannot be checked is refused (CF-0630)")
        hook_end, payoff_start = section_bounds(script, words, voice_end)

    anchors, placed_ids = [], set()
    for req, s in zip(requested, sounds):
        beat_id = req["beat_id"]
        if not enabled:
            delivered.append(_answer(beat_id, OUTCOME_LAYER_OFF))
            continue
        if not allowed:
            delivered.append(_answer(beat_id, OUTCOME_PATTERN_REFUSED))
            continue
        at = anchor_seconds(s.get("beat_text"), script, words)
        if at is None:
            # CF-0235: which of the two, and the fragments to check it by.
            why = beat_failure(s.get("beat_text"), script, words)
            delivered.append(_answer(beat_id, why["code"], evidence=why))
            near = why.get("nearest") or {}
            notes.append(f"sound {beat_id}: {why['code']} - beat {why['searched']!r} "
                         f"({why['in_script_coverage']} of its words are in the script, "
                         f"{why['alignment_coverage']} in the alignment); nearest heard "
                         f"at word {near.get('word_index')}: {near.get('text')!r}")
            continue
        at = round(at, 3)
        # S2 / S4 - the moment-side refusals, before any file is looked at.
        if len(anchors) >= max_per_video:
            delivered.append(_answer(beat_id, OUTCOME_NO_SLOT))
            notes.append(f"sound {beat_id}: max_inserts_per_video ({max_per_video}) reached")
            continue
        collision = next((a for a in anchors if abs(a - at) < min_gap), None)
        if collision is not None:
            delivered.append(_answer(beat_id, OUTCOME_NO_SLOT))
            notes.append(f"sound {beat_id}: anchor {at:.2f}s is {abs(collision - at):.2f}s from "
                         f"the sound at {collision:.2f}s, the gap is {min_gap}s (S4)")
            continue
        if at < hook_end:
            delivered.append(_answer(beat_id, OUTCOME_NO_SLOT))
            notes.append(f"sound {beat_id}: anchor {at:.2f}s is inside the hook "
                         f"(ends {hook_end:.2f}s) - protected section")
            continue
        room = round(min(payoff_start, voice_end) - at, 3)
        if room < min_duration:
            delivered.append(_answer(beat_id, OUTCOME_NO_SLOT))
            notes.append(f"sound {beat_id}: anchor {at:.2f}s leaves {room:.2f}s before the "
                         f"payoff ({payoff_start:.2f}s) / voice end ({voice_end:.2f}s) (S2)")
            continue
        bi = block_index_at(blocks, at)
        if no_list is not None:
            delivered.append(_answer(beat_id, OUTCOME_NO_ASSET))
            notes.append(f"sound {beat_id}: no_asset - the channel has no rights-holder "
                         f"list, no file is checked or taken (CF-0630)")
            continue
        tags = intent_tags(spec, req["intent"])

        # selection: eligible -> tags -> walk the gate
        kept, skipped = lib.eligible(index_entries, bl)
        for rec in skipped:
            rec.update({"block": bi, "layer": LAYER, "beat_id": beat_id, "at_seconds": at,
                        "skip_reason": SKIP_BLACKLIST,
                        "matched_tags": matched_tags(
                            next(e for e in index_entries if e.get("id") == rec["id"]), tags)})
            skipped_recs.append(rec)
        chosen, slot_refused = None, False
        for m, entry in rank_by_tags(kept, tags, min_matches):
            check = lib.blacklist_check(entry.get("rights_holder"), entry.get("medium"), bl)
            if entry["id"] in placed_ids:
                skipped_recs.append(_record(lib, entry, check, bi, beat_id, at, m, SKIP_DISTINCT))
                continue
            path = Path(root) / "shared" / "inserts" / lib.KIND_FOLDERS[LIBRARY_KIND] / entry["file"]
            ok, reason, duration = check_asset(path, spec, lib, at, room, words, m)
            if not ok:
                slot_refused = slot_refused or reason == SKIP_SLOT
                skipped_recs.append(_record(lib, entry, check, bi, beat_id, at, m, reason))
                continue
            chosen = (m, entry, check, path, duration)
            break
        if chosen is None:
            # Every candidate that was long enough to matter was refused by
            # the moment, not by what it is: that is the slot's answer.
            outcome = OUTCOME_NO_SLOT if slot_refused else OUTCOME_NO_ASSET
            delivered.append(_answer(beat_id, outcome))
            notes.append(f"sound {beat_id}: no file for intent {req['intent']!r} "
                         f"({'slot' if slot_refused else 'no candidate passed the gate'}; "
                         f"library has {len(index_entries)} entr{'y' if len(index_entries) == 1 else 'ies'})")
            continue
        m, entry, check, path, duration = chosen
        anchors.append(at)
        placed_ids.add(entry["id"])
        placed_recs.append(_record(lib, entry, check, bi, beat_id, at, m))
        placed.append({"block_index": bi, "record": {
            "kind": LAYER,
            "beat_id": beat_id,
            "intent": req["intent"],
            "asset_id": entry["id"],
            "file": str(path.resolve()),
            "at_seconds": at,
            "duration_s": round(duration, 3),
            "matched_tags": list(m),
        }})
        delivered.append(_answer(beat_id, OUTCOME_PLACED, bi, entry["id"], at))
        notes.append(f"sound {beat_id}: {entry['id']} at {at:.2f}s on block {bi} "
                     f"(tags {', '.join(m)}, {duration:.2f}s)")

    return {"sound_requested": requested, "sound_delivered": delivered,
            "inserts": placed_recs + skipped_recs, "placed": placed, "notes": notes}


def apply_to_plan(plan, result):
    """Merge a plan_sounds() result into a render plan in place: `sound` on
    the block containing each placed anchor (and nothing else on any block -
    a second sound landing in the same block is kept beside it under
    `sounds`, since a held block can outlast the gap), and plan["sound"]
    with the pair, the provenance and the placed list build_soundtrack.py
    mixes from. Returns the plan."""
    for p in result["placed"]:
        block = plan["blocks"][int(p["block_index"])]
        if "sound" in block:
            block.setdefault("sounds", [block["sound"]]).append(dict(p["record"]))
        else:
            block["sound"] = dict(p["record"])
    plan["sound"] = {
        "sound_requested": result["sound_requested"],
        "sound_delivered": result["sound_delivered"],
        "inserts": result["inserts"],
        "placed": [dict(p["record"], block_index=p["block_index"]) for p in result["placed"]],
        "notes": result["notes"],
    }
    return plan


def placed_sounds(plan):
    """The sounds a plan carries for the mix: plan["sound"]["placed"] (the
    canonical list), or, on a plan whose blocks carry `sound` records
    without the summary, those. [] on a plan that ran no layer."""
    s = plan.get("sound") or {}
    if s.get("placed") is not None:
        return list(s["placed"])
    out = []
    for i, b in enumerate(plan.get("blocks", [])):
        for rec in ([b["sound"]] if b.get("sound") else []) + list(b.get("sounds") or [])[1:]:
            out.append(dict(rec, block_index=i))
    return out


def stage_fields(plan):
    """What write_batch_metadata.py copies onto the videos[] record: the
    pair (always both, [] when the plan never ran the layer) and this
    layer's provenance records."""
    s = plan.get("sound") or {}
    return (list(s.get("sound_requested") or []),
            list(s.get("sound_delivered") or []),
            list(s.get("inserts") or []))


def merge_inserts(existing, records):
    """videos[].inserts[] with this layer's records replacing this layer's
    previous ones and every other layer's (underlay, meme) left alone."""
    kept = [r for r in (existing or []) if not (isinstance(r, dict) and r.get("layer") == LAYER)]
    return kept + list(records)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="plan the sound inserts for one render plan")
    ap.add_argument("plan")
    ap.add_argument("--script", required=True, help="03-content-researcher.json")
    ap.add_argument("--script-id", required=True)
    ap.add_argument("--channel", help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--pattern", help="pattern id; default: the plan's rhythm.pattern_requested")
    ap.add_argument("--root", help=f"factory root (default ${meme_layer.FACTORY_ROOT_ENV} or the checkout)")
    ap.add_argument("--words", help="words.json; default: the plan's own `words`")
    ap.add_argument("--write", action="store_true", help="merge the result into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else factory_root()
    plan = json.load(open(a.plan))
    batch = json.load(open(a.script))
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((s for s in scripts or [] if s.get("script_id") == a.script_id), None)
    if script is None:
        raise SystemExit(f"script {a.script_id!r} not in {a.script}")
    words = load_words(a.words) if a.words else plan.get("words") or []
    pattern_id = a.pattern or (plan.get("rhythm") or {}).get("pattern_requested")
    result = plan_sounds(
        script, words, plan["blocks"], load_channel(a.channel, root),
        load_pattern(pattern_id, root), root=root,
        voice_end=(plan.get("audio") or {}).get("duration"))
    if a.write:
        apply_to_plan(plan, result)
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps({k: result[k] for k in ("sound_requested", "sound_delivered", "notes")},
                     ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "sound", name="sound_layer.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
