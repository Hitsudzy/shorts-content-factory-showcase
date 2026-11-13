#!/usr/bin/env python3
"""CF-0013: the schema of the insert-layer vocabulary, as executable code.

This file *is* the schema, exactly as `patterns/validate_patterns.py` is the
schema of the pattern vocabulary. There is no prose copy of it: CF-0015
rejected the "numbers in JSON, prose in SKILL.md" split for creating two
sources of truth about one entity, and a SCHEMA.md next to a validator would
be the same mistake one level up. To find out what an insert file may contain,
read `validate_insert` below; to find out what an insert *is*, read that
insert's own `purpose`.

Run it directly to check the vocabulary on disk:

    python3 inserts/validate_inserts.py

The one prose rule that sits beside this schema is `inserts/POLICY.md`
(CF-0114): what third-party material an insert may contain, and the two
mechanisms that stand in for a rights gate - per-file provenance in the
factory library `shared/inserts/` (schema: `shared/inserts/inserts_lib.py`)
and one blacklist check at selection time. `capture_methods[].rights_note`
and `provenance` below are the vocabulary's side of that rule; POLICY.md is
the rule itself.

--------------------------------------------------------------------------
Layer, insert, and why this is not part of patterns/
--------------------------------------------------------------------------

A **layer** is a mechanism the factory owns and a channel switches on. An
**insert** is one use of that layer inside one video. CF-0012 settled the shape
for the meme layer and it is the shape used here:

* the layer is **orthogonal to the pattern**, never a property of it and never
  a third dimension of the rotation tag - four patterns by four rhythms at ~90
  videos a month is already a sparse interaction, and a third axis halves the
  Analyst's cells again (CF-0015 Q1, CF-0012 Q3);
* a pattern may nonetheless **refuse** a layer at home, through an optional
  `<kind>_layer: {allowed, reason}` field in `patterns/` - the form's answer to
  "does this shape of script tolerate the interruption";
* a channel **enables or disables** the layer in its own config - the editorial
  voice's answer to "do we want it". Both gates exist because they answer
  different questions, and the channel one is what makes the layer a capability
  of the factory rather than a feature of one channel (CF-0012, 2026-09-03).

The vocabulary lives in the repo root next to `patterns/` for the same reason
that one does: Content Researcher decides where an insert is wanted, Video
Editor builds it, Compliance Checker reads what was recorded, and nobody owns
it alone.

--------------------------------------------------------------------------
An insert file - inserts/<insert_kind>.json, one per kind
--------------------------------------------------------------------------

Two sourcings, one schema with a branch. A **captured** kind (proof) obtains
somebody's document per insert, by one of KNOWN_CAPTURE_METHODS, and is read;
a **library** kind (meme, CF-0067; sound, CF-0068) selects a file from the
factory library `shared/inserts/<kind>s/` (CF-0114) and is recognised. Which
branch a kind is on is a fact of this file - `LIBRARY_BLOCK_LAYERS` - not of
the JSON, for the same reason the underlay's flag is code: the
executable_today gate has to live where a test can check it against the task
tracker.

A second branch, the **medium** (`LIBRARY_BLOCK_LAYERS[kind]['medium']`): a
*picture* (proof, meme) is composed into a block's frame and carries
`composition` and a pixel `asset_floor`; *audio* (sound) is mixed into the
soundtrack at a moment and carries `mix`, `exclusions`, a duration ceiling
in `asset_floor`, tag matching in `selection` and a moment-shaped
`placement`. See `validate_audio_placement`, `validate_audio_floor` and
`validate_mix` for the audio side of every section named below.

Required on both:

  insert_kind         str, matches the filename stem, one of KNOWN_INSERT_KINDS
  display_name        str, short human name
  summary             str, one line - what the insert is
  purpose             non-empty list of paragraphs, >= 400 chars in total: the
                      whole of what this insert is and when it earns its place.
                      A stub is a failure, not a warning - an insert nobody can
                      judge by is not a vocabulary entry.
  storyboard_contract {field, kind_value, sits_beside, note} - how the script
                      declares it, and what it sits beside rather than replaces
  placement           captured: {min_block_seconds, reading_rate_cps,
                       max_reading_seconds, max_inserts_per_video, rule[],
                       priority[]}; library: {min_block_seconds,
                       max_block_seconds, max_inserts_per_video, rule[],
                       priority[]} - a meme is not read, so it has no reading
                       rate, and its span is the block's
  provenance          {required[], conditional{}, written_to, note} - what is
                      recorded about every insert that ships
  attribution         {must_be_visible_in_insert, required_elements[],
                       reuse_sourcing_line, note} - true on a captured kind
                      (a proof's attribution is part of the evidence), false on
                      a library kind (a meme with a credit inside the frame is
                      not the picture the viewer recognises; the credit goes on
                      the sourcing line, and required_elements say what)
  composition         {fit, background, ken_burns, punch, smart_crop,
                       our_captions, asset_gate{skipped{}, added[]}, note};
                      a meme adds motion{push_in_zoom, min_zoom, pan_fraction,
                      min_pan_px, modes[], ...} - its own move (CF-0405),
                      never the generic Ken Burns, which stays false
  degradation         {on_failure, never_substitute[], note}
  metadata            {requested_field, delivered_field, provenance_field, note};
                      a library kind adds requested_shape, delivered_shape and
                      the closed outcomes[] list the delivered entries use
  compliance          non-empty list of paragraphs
  honesty_rules       non-empty list of paragraphs
  validated           {status, measured_on, note} - "unvalidated" while the
                      numbers are derived rather than measured. Required, and
                      required to be honest: a file full of thresholds that
                      claims nothing about where they came from is how CF-0003's
                      constants drifted.

Required on a captured kind only:

  capture_methods     non-empty list of ways the material is obtained; see below
  legibility          the readability gate; see below

Required on a library kind only:

  source              {library_kind, folder, index, index_schema, rule,
                       executable_today_lives_in, note} - the one source, and
                       where the flag is
  selection           {script_stage, script_field, script_shape, absent_means,
                       max_reactions_per_script, intent_vocabulary{},
                       query_embedding, ranking, min_similarity, min_lead,
                       lead_rank, tag_match?{floor_rank_fraction, sources[],
                       note}, distinct_per_video, note} - the contract between the
                       writer's request and the editor's choice; see below.
                       `tag_match` (CF-0388) is optional: request words matched
                       against library tags before the CLIP walk, floored at a
                       fraction of CLIP's own ranking; `sources` must be fields
                       of script_shape
  meaning_rule        {label, status, rule, negative_half_checked_by,
                       positive_half_checked_by, note} - M3, and `status` has
                       to say it is not verified until a published video says
                       otherwise
  asset_floor         {rule, general_floor_constant, general_floor_px,
                       general_floor_untouched, allow_upscale,
                       max_upscale_factor, upscale_measure, output_px[w, h],
                       fit_box_px[w, h], fit_box_source, still_suffixes[],
                       animated_suffixes[], audio_track, measured_with, note} -
                       the quality gate a recognised picture gets instead of a
                       legibility gate; see below

Optional:

  notes               free text

--------------------------------------------------------------------------
selection (library kinds)
--------------------------------------------------------------------------

The script side names an intent from a closed vocabulary on a beat of the
commentary, anchored by a verbatim `beat_text` - the device
script.production_fact uses (CF-0186) - and at most a free-text `query` for the CLIP
ranking. The vocabulary is closed for the Analyst's sake (a count over eleven
intents means something, a count over free strings does not), and every
intent carries a `default_query` so that a request with no query still
embeds to something. `min_similarity` is a CLIP text-image dot product in
(0, 1); a floor at 0 would place the least wrong picture, a floor at 1 would
place nothing. An embedding-ranked kind carries a second floor beside it
(CF-0143): `min_lead` in (0, 1) is how far the leader has to stand above the
score `lead_rank - 1` places below it, and `lead_rank` is at least 3 - a
library that holds near-duplicates on purpose puts a right pick's own twin in
second place, so the second place is not the field a right pick has to beat. `max_reactions_per_script` has to equal
placement.max_inserts_per_video, or the writer and the editor disagree about
how many a video may carry.

--------------------------------------------------------------------------
asset_floor (library kinds)
--------------------------------------------------------------------------

A recognised picture is gated on being big enough to survive the frame, not
on type height - and, since CF-0392, on the stretch it actually gets: fitted
`contain` into the insert box `fit_box_px` (the editor's meme_box(), CF-0394),
a file of w x h px is stretched min(box_w / w, box_h / h) times, and it is
refused only when that exceeds `max_upscale_factor`. The file's short side
alone decides nothing, so `min_short_side_px` and `constant_name` (the old
MEME_MIN_SHORT_SIDE) are refused as stale keys. `general_floor_untouched` has
to be true with `general_floor_px` = 720: MIN_SHORT_SIDE is a footage-quality
signal and is never lowered for another asset class (CF-0012). The box has to
fit inside `output_px`, and the ceiling has to reject something: the
smallest picture it admits across the box's narrow side,
min(fit_box_px) / max_upscale_factor, may not be under 240 px - a thumbnail.

--------------------------------------------------------------------------
capture_methods
--------------------------------------------------------------------------

Each entry: {method, summary, description, executable_today,
blocked_by | implemented_by, needs_decision, question? | decision, rejected?,
behaviour?, rights_note}.

`executable_today` is the same device `patterns/rhythms.json` uses for rhythms
and openings, and it exists for the same reason: admitting a capability before
the code that performs it is how a pipeline quietly ships something that is not
what it claims to be. A method that is not executable must name the task that
makes it one (`blocked_by`); a method that is executable must name the task
that made it one (`implemented_by`), so that the flag can be checked against
the work instead of trusted. A method that additionally needs a *decision*
(not just work)
carries `needs_decision: true` and the question in `question` - so that an open
question stays a question instead of being settled by whoever writes the code
first.

`rights_note` is mandatory on every method, including the ones that copy
nothing: "this copies no third-party material" is itself the note.

A method that has been decided (CF-0071, 2026-09-05) carries `decision`
instead of `question`: {date: YYYY-MM-DD, accepted: bool, constraints[] when
accepted | reason when rejected, log}. `rejected: true` marks a method the
decision turned down: it can never be `executable_today`, it names no
`blocked_by` (a rejected method is owed to nobody), and a channel can never
name it as `capture_method`. A question kept next to an answer reads as still
open, so a decided method may not carry `question`. `behaviour` is the
method's constants for the implementing repo (viewport, timeout, per-host
rate, what is captured by default, what must be shown) - free shape, checked
for presence on an accepted method only.

--------------------------------------------------------------------------
capture_priority (captured kinds)
--------------------------------------------------------------------------

  {order[], never, rule[], decided} - the decision's sentence as a list:
  the real page when it can be fetched automatically and lawfully, else the
  quotation in our own voice, never an imitation. `order` names every
  accepted method and no rejected one. A channel's `capture_method` is the
  top of this chain, and `validate_channel_inserts` requires the chain from
  there down to be executable end to end.

--------------------------------------------------------------------------
evidence_contract and script_contract (captured kinds)
--------------------------------------------------------------------------

The two upstream contracts the other repositories implement from this file:

  evidence_contract   {stage, field, item_shape{url, title, publication,
                       published_at, feed}, compatibility, rule[], owed_to,
                       note} - what 01-trend-hunter.json carries per link so
                       that a rendered_quote has a headline, an outlet and a
                       date to show (CF-0071 part 2)
  script_contract     {script_stage, script_field, script_shape, absent_means,
                       max_proofs_per_script, max_verbatim_chars, anchor,
                       placement_rule, source_rule, owed_to, note} - the
                       writer's request, anchored to script.production_fact
                       .beat_text (CF-0186; CF-0223 moved it there off the
                       cancelled check, and the request carries no id for
                       what it supports because a script has one fact).
                       (CF-0071 part 3.)
                       max_proofs_per_script has to equal
                       placement.max_inserts_per_video and max_verbatim_chars
                       has to equal max_reading_seconds * reading_rate_cps,
                       or the writer and the editor disagree

A captured kind's `metadata` adds requested_shape, delivered_shape, the closed
outcomes[] list, placed_outcomes[] (the subset that carries a file - the
fallback of the decision is a placed outcome counted apart), and
capture_method_used_values[] (accepted methods only).

--------------------------------------------------------------------------
legibility
--------------------------------------------------------------------------

  min_text_height_fraction_of_caption   in (0, 1]; the floor is expressed
                                        against the renderer's own caption size
                                        rather than as a bare pixel count, so it
                                        moves with the one piece of type this
                                        project has already defended
  caption_size_px_reference             the caption size the fraction refers to
  frame_height_reference                the frame those pixels are in
  frame_width_reference                 the delivered frame width
  min_capture_width_px                  >= frame_width_reference: a capture
                                        narrower than the frame can only be
                                        shown by enlarging it
  allow_upscale                         must be false - an enlarged proof is a
                                        blurred proof
  min_recognised_lines                  >= 1 (text_present: lines anywhere)
  min_gating_lines                      >= 1: proof-text lines that must be
                                        recognised for the gate to pass at all
  max_lines                             >= min_gating_lines; counts gating lines
  measured_with                         the instrument, named
  floor_applies_to                      must be "gating_lines" - the floor is a
                                        rule about the proof text, not about
                                        the outlet's chrome (refined 2026-09-06
                                        on the first real capture: a headline
                                        at 45-54px was failed by a 17px
                                        "Subscribe" in the same header)
  rule[]                                prose: which lines gate and which are
                                        only measured
  gating_lines                          one entry per accepted capture method,
                                        keys == accepted_methods(), each
                                        {gating, furniture, proof_text_field,
                                        match}: `gating` and `furniture` are
                                        prose; `proof_text_field` is the name
                                        of the sidecar the capture step writes
                                        for the gate (str) or null when every
                                        line gates; `match` is null or
                                        {normalise, line_gates_when,
                                        match_min_token_fraction in (0, 1],
                                        min_line_chars >= 1, note}. A method
                                        with a proof_text_field must have a
                                        match rule - text passed to a gate that
                                        has no rule for matching it is passed
                                        nowhere
  record                                {field, shape, note} - the measurement
                                        written on the delivered entry
  changes[]                             {date, found_on, change} - dated notes
                                        on every refinement of the gate

--------------------------------------------------------------------------
The channel side
--------------------------------------------------------------------------

`validate_channel_inserts` checks a channel config's `insert_layers` block:

    "insert_layers": {
      "<kind>": {"enabled": bool, "reason": str, "capture_method": str|null}
    }

Rules, and the forcing function that matters: **a channel may not enable a
layer for which no capture method is executable today.** Without it the switch
could be turned on months before anything could act on it, and the config would
be describing a video the factory cannot make - the failure `patterns/`'s own
channel gate exists to prevent. A disabled layer must say why, because a bare
`false` is a preference and a reason is a decision.

A library block layer's switch is the same shape minus `capture_method` (the
material comes from the library, there is nothing to capture) and is gated by
`LIBRARY_BLOCK_LAYERS[kind]['executable_today']` - the same flag, the same
order, as VIDEO_LAYERS. Both gates have to agree before a meme happens: the
channel's switch here, and the pattern's `meme_layer.allowed` in patterns/,
which for a library block layer has to be filled on every pattern
(`validate_pattern_layer_fields`) - a meme is an orthogonal decoration any
pattern may carry, so a pattern that has not answered has not been asked.
"""
import json
import re
import sys
from pathlib import Path

INSERTS_DIR = Path(__file__).resolve().parent
REPO = INSERTS_DIR.parent
CHANNELS_DIR = REPO / "channels"

# patterns/ owns the channel duration ceiling; repeating the number here would
# give the repo two of them, and the feasibility check below is the same kind
# of check validate_patterns.py already makes against it.
sys.path.insert(0, str(REPO / "patterns"))
from validate_patterns import MAX_TARGET_SECONDS  # noqa: E402

# shared/inserts/ owns the sound ceiling (CF-0068) and the audio suffixes; the audio branch below checks
# the spec against them rather than carrying a second copy.
sys.path.insert(0, str(REPO / "shared" / "inserts"))
from inserts_lib import MAX_SOUND_SECONDS, SOUND_SUFFIXES  # noqa: E402
import inserts_lib as _inserts_lib  # noqa: E402  (CF-0393: meme banks)

# The family. A kind with no file on disk is not an error here, but it is not
# free either: tests/test_insert_layers.py requires a missing kind to be owed
# to a task that is still open, the same forcing function patterns/ uses for
# original_contribution. All three kinds are described today (proof by
# CF-0013, meme by the root part of CF-0067, sound by the root part of
# CF-0068), so nothing is owed.
KNOWN_INSERT_KINDS = {
    "proof": None,
    "meme": None,
    "sound": None,
}

# CF-0067: block layers whose material is the factory library rather than a
# capture. The meme takes a block like a proof does, but nothing is obtained
# per insert - the file is selected from shared/inserts/memes/ by the intent
# the script wrote and the CLIP ranking of inserts_lib - so it has no capture
# methods to carry the executable_today flag. The flag lives here instead,
# the way VIDEO_LAYERS carries the underlay's, and obeys the same order:
# implement selection, placement, composition and the 05-*.json fields in
# agents/video-editor (the Video Editor part of CF-0067), flip
# `executable_today` and name `implemented_by`, only then let a channel
# switch it on. tests/test_insert_layers.py checks the flag against the task
# tracker in both directions.
#
# `medium` is which branch of the library schema the kind is validated on:
# a "picture" is fitted into a block's frame (composition, a pixel floor,
# CLIP ranking); "audio" (the sound of CF-0068) is mixed into the soundtrack
# at a moment (mix, a duration ceiling, tag matching). Same source, same
# provenance, same requested/delivered pair, different gates - the branch is
# code here rather than a field of the JSON for the reason the flag is.
LIBRARY_BLOCK_LAYERS = {
    "meme": {
        "library_kind": "meme",
        "index": "shared/inserts/memes/index.json",
        "medium": "picture",
        "executable_today": True,
        "blocked_by": "CF-0067",
        "implemented_by": "CF-0067",
    },
    # CF-0068: the sound insert. The root part (this file, inserts/sound.json,
    # the pattern field and the channel switch) is done; the flag stays
    # false until the Video Editor part lands the fourth mix input and the
    # tag selector - then flip it and set implemented_by to "CF-0068".
    "sound": {
        "library_kind": "sound",
        "index": "shared/inserts/sounds/index.json",
        "medium": "audio",
        "executable_today": False,
        "blocked_by": "CF-0068",
        "implemented_by": None,
    },
}
MEDIA = ("picture", "audio")

# CF-0014: layers that span the whole video instead of one block. The
# underlay is a muted loop from shared/inserts/loops/ in the second plane of
# the frame, under the main content, chosen per video by rotation
# (shared/inserts/underlay.py). It has no block, no capture method, no
# legibility gate and nothing to attribute on screen, so it is not an
# inserts/<kind>.json entry - that schema describes a document put in a
# block, and forcing a decorative background through it would be the wrong
# vocabulary for the sake of one switch. What it shares with the block
# layers is the channel side: the switch lives in the same `insert_layers`
# block, needs the same reason, and is gated by the same rule - a channel may
# not enable a layer nothing can place yet. `executable_today` here is the
# layer-level twin of a capture method's flag, and it obeys the same order:
# implement in agents/video-editor, flip the flag and name `implemented_by`,
# only then let a channel switch it on. tests/test_insert_layers.py checks
# the flag against the task tracker.
VIDEO_LAYERS = {
    "underlay": {
        "library_kind": "loop",
        "module": "shared/inserts/underlay.py",
        "executable_today": True,
        "blocked_by": None,
        "implemented_by": "CF-0127",
    },
}

# Capture methods this schema recognises. Closed on purpose: a sixth way of
# obtaining somebody else's document is a decision about what this factory
# does, not a string somebody types into a JSON file.
KNOWN_CAPTURE_METHODS = (
    "rendered_quote",
    "operator_browser",
    "platform_embed",
    "headless_browser",
    "manual_dropin",
)

COMMON_REQUIRED_KEYS = (
    "insert_kind", "display_name", "summary", "purpose", "storyboard_contract",
    "placement", "provenance", "attribution", "degradation",
    "metadata", "compliance", "honesty_rules", "validated",
)
# A picture (proof, meme) is composed into a frame; a sound is mixed into the
# soundtrack and says what it is not (the clip exclusions of CF-0068).
PICTURE_REQUIRED_KEYS = ("composition",)
AUDIO_REQUIRED_KEYS = ("mix", "exclusions")
CAPTURE_REQUIRED_KEYS = ("capture_methods", "capture_priority", "legibility",
                         "evidence_contract", "script_contract")
LIBRARY_REQUIRED_KEYS = ("source", "selection", "meaning_rule", "asset_floor")
# Kept under its old name for the callers that only ever meant the proof.
REQUIRED_KEYS = COMMON_REQUIRED_KEYS + PICTURE_REQUIRED_KEYS + CAPTURE_REQUIRED_KEYS

VALIDATION_STATUSES = ("unvalidated", "measured")

# The general footage floor in agents/video-editor's common.py, repeated here
# only as the number a library kind's asset_floor has to leave alone.
GENERAL_MIN_SHORT_SIDE = 720

# CF-0392 (user's decision of 2026-09-24): a picture insert is gated on the
# stretch it gets in the box it is drawn into, not on its short side. The
# ceiling may not admit a picture thinner than this across the box's narrow
# side - that is a thumbnail, and a ceiling that admits it rejects nothing.
PICTURE_FLOOR_RULE = "upscale_in_insert_box"
MIN_ADMITTED_SIDE_PX = 240

# The one outcome a delivered entry has to be able to carry: the request was
# answered with a file. Everything else in a kind's `outcomes` is its own.
OUTCOME_PLACED = "placed"

# CF-0071 (decided 2026-09-05): the shapes the other repositories implement
# for the proof layer, pinned here so that a rename is a schema change.
INSERT_RECORD_KEYS = ("kind", "id", "file", "source_url", "rights_holder", "licence",
                      "blacklist_check", "skipped", "block")
EVIDENCE_ITEM_KEYS = ("url", "title", "publication", "published_at", "feed")
PROOF_REQUEST_KEYS = ("proof_id", "verbatim_text", "source", "capture_method_hint")

# CF-0071 (2026-09-06): the legibility floor applies to the lines that carry
# the proof, named per capture method under legibility.gating_lines; the
# capture step hands the gate the text they are matched against in the sidecar
# field named there (headless_browser: `proof_text` = {h1, standfirst}).
GATING_LINES = "gating_lines"
PROOF_TEXT_FIELD = "proof_text"
PROOF_TEXT_KEYS = ("h1", "standfirst")
PROOF_SOURCE_KEYS = ("url", "publication", "title", "published_at", "handle")
TREND_HUNTER_STAGE = "01-trend-hunter.json"
CONTENT_RESEARCHER_STAGE = "03-content-researcher.json"


def is_library_kind(kind):
    return kind in LIBRARY_BLOCK_LAYERS


def layer_medium(kind):
    """'picture' or 'audio'. A captured kind is a picture: a proof is a page."""
    return LIBRARY_BLOCK_LAYERS.get(kind, {}).get("medium", "picture")


def is_audio_kind(kind):
    return layer_medium(kind) == "audio"


# CF-0379 (2026-09-24): whether our own word-by-word captions keep running
# while a picture insert holds the block. The answer belongs to the kind and
# not to the layer, because the argument for silencing them is an argument
# about *this* picture rather than about inserts as a class - which is the
# confusion CF-0379 was raised for: render/src/Video.jsx silenced the captions
# on `block.insert` alone, and the meme inherited a rule written for the proof.
#
#   proof -> "shown"  (CF-0390, 2026-09-24; was "hidden" under CF-0071): the
#            card carries the document's title, outlet and date plus our fact
#            strip, not the narrator's line, so hiding our words left the voice
#            without text for the card's window. The band keeps clear of the
#            card's text instead (render/src/lib/captionBand.js).
#   meme  -> "shown"  (CF-0379): the picture is a reaction to the block and
#            does not carry the line being spoken. Hiding our words there buys
#            nothing and costs the viewer the narration for the insert's whole
#            span; readability is bought by lifting the caption band above the
#            insert for its span, with the meme left where it stands.
#
# A kind missing from this table is a kind whose composition has not answered
# the question, and that is an error and not a default: "hidden" as a fallback
# is precisely how the meme came by the proof's rule.
PICTURE_OUR_CAPTIONS = {
    "proof": "shown",
    "meme": "shown",
}
PICTURE_OUR_CAPTIONS_WHY = {
    "hidden": ("the document carries its own text, and stacking ours on top is the "
               "double-text defect v1 already shipped once (CF-0071)"),
    "shown": ("the insert does not carry the line the voice is speaking at that moment "
              "(a meme is a reaction, a proof card is a title, an outlet and a date), so "
              "hiding our words buys nothing and costs the viewer the narration for the "
              "insert's span - the caption band gives way instead (CF-0379, CF-0390)"),
}

# The one legal answer to "the insert did not arrive". Named as a constant
# because it is the whole of the degradation promise: a missing insert costs
# the insert and nothing else - never the video, never a rung of the
# motion -> stills -> typographic chain, never a silent substitute.
DEGRADE_TO_ORDINARY_BLOCK = "block_without_insert"


def insert_files():
    return sorted(INSERTS_DIR.glob("*.json"))


def load_inserts():
    return {p.stem: json.loads(p.read_text()) for p in insert_files()}


def missing_kinds():
    """kind -> the task that owes it, for every known kind with no file."""
    on_disk = {p.stem for p in insert_files()}
    return {k: owed for k, owed in KNOWN_INSERT_KINDS.items()
            if k not in on_disk and owed}


# CF-0405: a picture kind whose file moves on its own terms inside the insert
# box - a slow push-in or a pan along the letterbox - read by the editor
# (meme_layer.meme_motion) from `composition.motion` by exactly the four
# numeric keys below. The generic ken_burns / punch stay false on every
# picture kind: this is not them switched on, it is a bounded move of the
# kind's own, capped by asset_floor.max_upscale_factor.
PICTURE_OWN_MOTION = ("meme",)
PICTURE_MOTION_MODES = ("push_in", "pan", "static")


def validate_picture_motion(mo, ctx):
    errs = []
    if not isinstance(mo, dict):
        return [f"{ctx}: must be an object - without it the editor places every "
                f"meme `static` (no_motion_in_contract), CF-0405"]

    def num(key):
        v = mo.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errs.append(f"{ctx}.{key}: must be a number - the editor reads it as one")
            return None
        return float(v)

    push, low = num("push_in_zoom"), num("min_zoom")
    pan, pan_px = num("pan_fraction"), num("min_pan_px")
    if push is not None and low is not None and not (1 < low <= push <= 1.2):
        errs.append(f"{ctx}: needs 1 < min_zoom <= push_in_zoom <= 1.2, got "
                    f"min_zoom {low}, push_in_zoom {push} - a zoom of 1 is no move, "
                    f"and past 1.2 the push crops the joke instead of breathing on it")
    if pan is not None and not (0 < pan <= 0.2):
        errs.append(f"{ctx}.pan_fraction: must be in (0, 0.2], got {pan}")
    if pan_px is not None and pan_px < 0:
        errs.append(f"{ctx}.min_pan_px: must be >= 0, got {pan_px}")
    modes = mo.get("modes")
    if not isinstance(modes, list) or not modes or not set(modes) <= set(PICTURE_MOTION_MODES):
        errs.append(f"{ctx}.modes: must be a non-empty subset of {list(PICTURE_MOTION_MODES)}")
    return errs


def _prose(errs, obj, ctx, min_chars=0):
    if not isinstance(obj, list) or not obj or not all(
            isinstance(p, str) and p.strip() for p in obj):
        errs.append(f"{ctx}: must be a non-empty list of paragraphs")
        return
    if min_chars and sum(len(p) for p in obj) < min_chars:
        errs.append(f"{ctx}: is a stub ({sum(len(p) for p in obj)} chars) - the prose "
                    f"of what this insert is lives here in full, not in any SKILL.md")


def _pixel_pair(errs, obj, key, ctx):
    """[w, h] of positive integers, or None with an error recorded."""
    value = obj.get(key)
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0
                       for v in value)):
        errs.append(f"{ctx}.{key}: must be [width, height] in positive integer px, "
                    f"got {value!r}")
        return None
    return tuple(value)


def _positive(errs, obj, key, ctx, integral=False):
    value = obj.get(key, "<missing>")
    if value == "<missing>":
        errs.append(f"{ctx}: missing {key}")
        return None
    kind = int if integral else (int, float)
    if isinstance(value, bool) or not isinstance(value, kind):
        errs.append(f"{ctx}.{key}: must be a positive "
                    f"{'integer' if integral else 'number'}, got {value!r}")
        return None
    if value <= 0:
        errs.append(f"{ctx}.{key}: must be positive, got {value}")
        return None
    return value


def validate_capture_methods(methods, ctx):
    errs = []
    if not isinstance(methods, list) or not methods:
        return [f"{ctx}: capture_methods must be a non-empty list - an insert with no "
                f"way of being obtained is not a capability, it is a wish"]
    seen = []
    for m in methods:
        if not isinstance(m, dict) or not isinstance(m.get("method"), str):
            errs.append(f"{ctx}.capture_methods: every entry needs a `method` string")
            continue
        name = m["method"]
        mctx = f"{ctx}.capture_methods[{name}]"
        seen.append(name)
        if name not in KNOWN_CAPTURE_METHODS:
            errs.append(f"{mctx}: unknown method (known: {list(KNOWN_CAPTURE_METHODS)}) - "
                        f"a new way of obtaining somebody's document is a decision, "
                        f"not a new string")
        for key in ("summary", "description", "rights_note"):
            if not isinstance(m.get(key), str) or not m[key].strip():
                errs.append(f"{mctx}: {key} must be a non-empty string"
                            + (" - 'this copies nothing' is itself the note"
                               if key == "rights_note" else ""))
        rejected = m.get("rejected", False)
        if not isinstance(rejected, bool):
            errs.append(f"{mctx}: rejected must be a boolean when present")
            rejected = bool(rejected)
        if not isinstance(m.get("executable_today"), bool):
            errs.append(f"{mctx}: executable_today must be a boolean")
        elif rejected:
            if m["executable_today"]:
                errs.append(f"{mctx}: rejected by decision and executable today at once - "
                            f"a method the user turned down cannot be the one the code runs")
            if m.get("blocked_by") or m.get("implemented_by"):
                errs.append(f"{mctx}: rejected, so blocked_by/implemented_by must be absent or "
                            f"null - a rejected method is owed to nobody")
        elif m["executable_today"] is False and not str(m.get("blocked_by", "")).startswith("CF-"):
            errs.append(f"{mctx}: is not executable but names no blocking task - "
                        f"a capability owed to nobody is a capability nobody will build")
        elif m["executable_today"] is True:
            if m.get("blocked_by"):
                errs.append(f"{mctx}: is executable today, so blocked_by must be absent "
                            f"or null")
            if not str(m.get("implemented_by", "")).startswith("CF-"):
                errs.append(f"{mctx}: is executable today but names no task that made it "
                            f"so - `implemented_by` is what lets a test check the flag "
                            f"against the work instead of trusting it")
        if not isinstance(m.get("needs_decision"), bool):
            errs.append(f"{mctx}: needs_decision must be a boolean - whether a method is "
                        f"merely unbuilt or actually undecided is the difference between "
                        f"work and a question for the user")
        elif m["needs_decision"] and not str(m.get("question", "")).strip():
            errs.append(f"{mctx}: needs_decision is true but no question is written - "
                        f"an undecided method with no question gets decided by whoever "
                        f"writes the code first")
        elif m["needs_decision"]:
            if rejected or "decision" in m:
                errs.append(f"{mctx}: needs_decision is true next to a decision - an "
                            f"answered question is not still open")
        else:
            errs += validate_decision(m, mctx, rejected)
    if len(set(seen)) != len(seen):
        errs.append(f"{ctx}.capture_methods: duplicate method(s) in {seen}")
    return errs


def _iso_date(value):
    import re
    return isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value) is not None


def validate_decision(m, mctx, rejected):
    """A decided method: `decision` in place of `question`, `rejected` agreeing
    with `decision.accepted`."""
    errs = []
    if "question" in m:
        errs.append(f"{mctx}: decided, so `question` must be gone - a question kept next "
                    f"to an answer reads as still open")
    d = m.get("decision")
    if not isinstance(d, dict):
        errs.append(f"{mctx}: neither needs_decision nor a `decision` block - a method that "
                    f"is not a question has to say who answered it and when")
        return errs
    if not _iso_date(d.get("date")):
        errs.append(f"{mctx}.decision: date must be YYYY-MM-DD")
    if not isinstance(d.get("accepted"), bool):
        errs.append(f"{mctx}.decision: accepted must be a boolean")
    elif d["accepted"] == rejected:
        errs.append(f"{mctx}: rejected={rejected} disagrees with decision.accepted="
                    f"{d['accepted']} - one flag, two answers")
    elif d["accepted"]:
        _prose(errs, d.get("constraints"), f"{mctx}.decision.constraints")
        if not isinstance(m.get("behaviour"), dict) or not m["behaviour"]:
            errs.append(f"{mctx}: accepted but carries no `behaviour` - the implementing "
                        f"repo needs the constants, not the sentiment")
    else:
        if not isinstance(d.get("reason"), str) or len(d["reason"].strip()) < 40:
            errs.append(f"{mctx}.decision: a rejected method carries its reason in full - "
                        f"that is what replaces the question on the record")
    if not isinstance(d.get("log"), str) or not d["log"].strip():
        errs.append(f"{mctx}.decision: log must name where the decision was taken")
    return errs


def validate_gating_lines(insert, lg, lctx):
    """The floor gates the proof text, not the outlet's chrome (2026-09-06).

    The first real capture - a Variety header whose headline measured 45-54px
    on the frame - was failed by a 17px "Subscribe" in the same region, because
    the rule as first written measured the smallest recognised line. A gate
    that every real capture fails is a gate that places nothing, so the floor
    now names the lines it applies to, per capture method, and the capture
    step has to hand the gate the text those lines are matched against.
    """
    errs = []
    if lg.get("floor_applies_to") != GATING_LINES:
        errs.append(f"{lctx}.floor_applies_to: must be {GATING_LINES!r} - the floor is a "
                    f"rule about the proof text; a floor on the smallest recognised line "
                    f"gates the outlet's navigation and fails every real capture")
    _prose(errs, lg.get("rule"), f"{lctx}.rule")
    gl = lg.get(GATING_LINES)
    gctx = f"{lctx}.{GATING_LINES}"
    if not isinstance(gl, dict):
        errs.append(f"{gctx}: must be an object, one entry per accepted capture method")
        gl = {}
    expected = sorted(accepted_methods(insert))
    if sorted(gl) != expected:
        errs.append(f"{gctx}: keys {sorted(gl)} must be exactly the accepted methods "
                    f"{expected} - a method that names no gating lines cannot pass the "
                    f"gate, and a rejected method needs no rule")
    for method, entry in sorted(gl.items()):
        ectx = f"{gctx}.{method}"
        if not isinstance(entry, dict):
            errs.append(f"{ectx}: must be an object")
            continue
        for key in ("gating", "furniture"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                errs.append(f"{ectx}.{key}: must say in words which lines it means")
        field = entry.get("proof_text_field")
        if field is not None and (not isinstance(field, str) or not field.strip()):
            errs.append(f"{ectx}.proof_text_field: null or the sidecar's field name")
        if field is not None and not isinstance(entry.get("proof_text_shape"), str):
            errs.append(f"{ectx}.proof_text_shape: a method that passes text to the gate "
                        f"has to say what shape it comes in")
        match = entry.get("match")
        if field is not None and not isinstance(match, dict):
            errs.append(f"{ectx}.match: a method that hands the gate a proof text has to "
                        f"say how a recognised line is matched against it")
        elif match is not None:
            if not isinstance(match, dict):
                errs.append(f"{ectx}.match: null or an object")
            else:
                mctx = f"{ectx}.match"
                for key in ("normalise", "line_gates_when"):
                    if not isinstance(match.get(key), str) or not match[key].strip():
                        errs.append(f"{mctx}.{key}: must be a non-empty string")
                frac = match.get("match_min_token_fraction")
                if isinstance(frac, bool) or not isinstance(frac, (int, float)) or not (0 < frac <= 1):
                    errs.append(f"{mctx}.match_min_token_fraction: must lie in (0, 1]")
                _positive(errs, match, "min_line_chars", mctx, integral=True)
    rec = lg.get("record")
    if not isinstance(rec, dict) or any(
            not isinstance(rec.get(k), str) or not rec[k].strip()
            for k in ("field", "shape", "note")):
        errs.append(f"{lctx}.record: must be {{field, shape, note}} - the measurement the "
                    f"gate writes beside its verdict, so that the floor can be re-derived")
    changes = lg.get("changes")
    if not isinstance(changes, list) or not changes:
        errs.append(f"{lctx}.changes: must be a non-empty list of {{date, found_on, change}}")
    else:
        for i, ch in enumerate(changes):
            if not isinstance(ch, dict) or any(
                    not isinstance(ch.get(k), str) or not ch[k].strip()
                    for k in ("date", "found_on", "change")):
                errs.append(f"{lctx}.changes[{i}]: must be {{date, found_on, change}}, all "
                            f"non-empty - an undated refinement of a gate is a gate nobody "
                            f"can argue with")
    return errs


def accepted_methods(insert):
    """Methods that are decided and not rejected - the ones a chain may hold."""
    return [m["method"] for m in insert.get("capture_methods", [])
            if isinstance(m, dict) and not m.get("rejected") and not m.get("needs_decision")]


def rejected_methods(insert):
    return [m["method"] for m in insert.get("capture_methods", [])
            if isinstance(m, dict) and m.get("rejected")]


def capture_chain(insert, top):
    """The methods tried for a proof when a channel names `top`: `top` and
    everything after it in capture_priority.order. [] when top is not in the
    order."""
    order = (insert.get("capture_priority") or {}).get("order") or []
    return order[order.index(top):] if top in order else []


def validate_capture_priority(insert, ctx):
    cp = insert.get("capture_priority")
    pctx = f"{ctx}.capture_priority"
    if not isinstance(cp, dict):
        return [f"{pctx}: must be an object with order[], never, rule[] and decided"]
    errs = []
    order = cp.get("order")
    names = [m.get("method") for m in insert.get("capture_methods", []) if isinstance(m, dict)]
    if not isinstance(order, list) or not order or not all(isinstance(o, str) for o in order):
        errs.append(f"{pctx}.order: must be a non-empty list of method names")
    else:
        if len(set(order)) != len(order):
            errs.append(f"{pctx}.order: duplicate method(s) in {order}")
        unknown = [o for o in order if o not in names]
        if unknown:
            errs.append(f"{pctx}.order: {unknown} are not capture methods of this kind")
        rej = [o for o in order if o in rejected_methods(insert)]
        if rej:
            errs.append(f"{pctx}.order: {rej} were rejected by decision - a rejected method "
                        f"in the chain is a method that gets tried anyway")
        missing = [a for a in accepted_methods(insert) if a not in order]
        if missing:
            errs.append(f"{pctx}.order: accepted method(s) {missing} are not in the chain - "
                        f"a method that is not in the order is never tried, so accepting it "
                        f"meant nothing")
    if not isinstance(cp.get("never"), str) or not cp["never"].strip():
        errs.append(f"{pctx}: never must say what is never done (imitation)")
    _prose(errs, cp.get("rule"), f"{pctx}.rule")
    if not _iso_date(cp.get("decided")):
        errs.append(f"{pctx}: decided must be YYYY-MM-DD")
    return errs


def validate_evidence_contract(insert, ctx):
    ec = insert.get("evidence_contract")
    ectx = f"{ctx}.evidence_contract"
    if not isinstance(ec, dict):
        return [f"{ectx}: must be an object"]
    errs = []
    if ec.get("stage") != TREND_HUNTER_STAGE:
        errs.append(f"{ectx}.stage: must be {TREND_HUNTER_STAGE!r}")
    if not isinstance(ec.get("field"), str) or not ec["field"].startswith("evidence."):
        errs.append(f"{ectx}.field: must name a field under `evidence` of a topic")
    shape = ec.get("item_shape")
    if not isinstance(shape, dict) or tuple(shape) != EVIDENCE_ITEM_KEYS:
        errs.append(f"{ectx}.item_shape: keys must be exactly {list(EVIDENCE_ITEM_KEYS)} in "
                    f"that order, got {list(shape) if isinstance(shape, dict) else shape}")
    else:
        for k, v in shape.items():
            if not isinstance(v, str) or len(v.strip()) < 20:
                errs.append(f"{ectx}.item_shape.{k}: has to say what the field holds")
    for key in ("compatibility", "owed_to", "note"):
        if not isinstance(ec.get(key), str) or len(ec[key].strip()) < (5 if key == "owed_to" else 40):
            errs.append(f"{ectx}.{key}: must be written in full")
    _prose(errs, ec.get("rule"), f"{ectx}.rule")
    return errs


def validate_script_contract(insert, ctx):
    sc = insert.get("script_contract")
    sctx = f"{ctx}.script_contract"
    if not isinstance(sc, dict):
        return [f"{sctx}: must be an object"]
    errs = []
    if sc.get("script_stage") != CONTENT_RESEARCHER_STAGE:
        errs.append(f"{sctx}.script_stage: must be {CONTENT_RESEARCHER_STAGE!r}")
    field = sc.get("script_field")
    if not isinstance(field, str) or not field.strip():
        errs.append(f"{sctx}.script_field: must name the script field")
    shape = sc.get("script_shape")
    entries = shape.get(field) if isinstance(shape, dict) and isinstance(field, str) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        errs.append(f"{sctx}.script_shape: must be {{{field}: [one example entry]}}")
    else:
        entry = entries[0]
        if tuple(entry) != PROOF_REQUEST_KEYS:
            errs.append(f"{sctx}.script_shape: entry keys must be exactly "
                        f"{list(PROOF_REQUEST_KEYS)}, got {list(entry)}")
        src = entry.get("source")
        if not isinstance(src, dict) or tuple(src) != PROOF_SOURCE_KEYS:
            errs.append(f"{sctx}.script_shape.source: keys must be exactly "
                        f"{list(PROOF_SOURCE_KEYS)}")
    pl = insert.get("placement") or {}
    if sc.get("max_proofs_per_script") != pl.get("max_inserts_per_video"):
        errs.append(f"{sctx}: max_proofs_per_script {sc.get('max_proofs_per_script')!r} must "
                    f"equal placement.max_inserts_per_video {pl.get('max_inserts_per_video')!r} - "
                    f"or the writer and the editor disagree about how many a video may carry")
    try:
        expected = int(pl["max_reading_seconds"] * pl["reading_rate_cps"])
    except (KeyError, TypeError):
        expected = None
    if expected is None or sc.get("max_verbatim_chars") != expected:
        errs.append(f"{sctx}: max_verbatim_chars must equal placement.max_reading_seconds * "
                    f"placement.reading_rate_cps = {expected} - the character half of the "
                    f"placement rule, stated once")
    for key in ("absent_means", "anchor", "placement_rule", "source_rule", "note"):
        if not isinstance(sc.get(key), str) or len(sc[key].strip()) < 40:
            errs.append(f"{sctx}.{key}: must be written in full")
    if not isinstance(sc.get("owed_to"), str) or "CF-" not in sc["owed_to"]:
        errs.append(f"{sctx}.owed_to: must name the task that implements it")
    return errs


def validate_captured_metadata(insert, md, ctx):
    """The requested/delivered shapes and the closed outcome list of a
    captured kind, mirroring what a library kind carries."""
    errs = []
    for key in ("requested_shape", "delivered_shape"):
        if not isinstance(md.get(key), str) or len(md[key].strip()) < 40:
            errs.append(f"{ctx}.metadata.{key}: spells out the shape the Video Editor "
                        f"writes - 'a list' is not a contract")
    outcomes = md.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes or not all(
            isinstance(o, str) and o.strip() for o in outcomes):
        errs.append(f"{ctx}.metadata.outcomes: must be a non-empty list of outcome names")
        return errs
    if OUTCOME_PLACED not in outcomes:
        errs.append(f"{ctx}.metadata.outcomes: {OUTCOME_PLACED!r} is missing")
    if len(set(outcomes)) != len(outcomes):
        errs.append(f"{ctx}.metadata.outcomes: duplicates in {outcomes}")
    placed = md.get("placed_outcomes")
    if not isinstance(placed, list) or OUTCOME_PLACED not in placed or not set(placed) <= set(outcomes):
        errs.append(f"{ctx}.metadata.placed_outcomes: must be a subset of outcomes that "
                    f"contains {OUTCOME_PLACED!r}")
    meanings = md.get("outcome_meanings")
    if not isinstance(meanings, dict) or set(meanings) != set(outcomes):
        errs.append(f"{ctx}.metadata.outcome_meanings: one meaning per outcome, no more, "
                    f"no fewer")
    used = md.get("capture_method_used_values")
    acc = accepted_methods(insert)
    if not isinstance(used, list) or sorted(used) != sorted(acc):
        errs.append(f"{ctx}.metadata.capture_method_used_values: must be exactly the accepted "
                    f"methods {sorted(acc)}, got {used}")
    return errs


def validate_insert(insert, stem=None):
    """Return a list of human-readable errors. Empty list means valid."""
    errs = []
    kind = insert.get("insert_kind", "<no insert_kind>")
    ctx = f"insert {kind}"

    library = is_library_kind(kind)
    audio = is_audio_kind(kind)
    required = COMMON_REQUIRED_KEYS + (LIBRARY_REQUIRED_KEYS if library
                                       else CAPTURE_REQUIRED_KEYS)
    required += AUDIO_REQUIRED_KEYS if audio else PICTURE_REQUIRED_KEYS
    missing = [k for k in required if k not in insert]
    if missing:
        return [f"{ctx}: missing required field(s) {missing}"]
    stray = [k for k in (CAPTURE_REQUIRED_KEYS if library else LIBRARY_REQUIRED_KEYS)
             if k in insert]
    if stray:
        errs.append(f"{ctx}: {stray} belong to the other sourcing - a "
                    f"{'library' if library else 'captured'} kind does not carry them")
    stray = [k for k in (PICTURE_REQUIRED_KEYS if audio else AUDIO_REQUIRED_KEYS)
             if k in insert]
    if stray:
        errs.append(f"{ctx}: {stray} belong to the other medium - a sound is not "
                    f"composed into a frame and a picture is not mixed")

    if stem is not None and insert["insert_kind"] != stem:
        errs.append(f"{ctx}: insert_kind does not match filename stem {stem!r}")
    if kind not in KNOWN_INSERT_KINDS:
        errs.append(f"{ctx}: unknown insert kind (known: {sorted(KNOWN_INSERT_KINDS)})")
    for key in ("display_name", "summary"):
        if not isinstance(insert[key], str) or not insert[key].strip():
            errs.append(f"{ctx}: {key} must be a non-empty string")

    _prose(errs, insert["purpose"], f"{ctx}.purpose", min_chars=400)
    _prose(errs, insert["compliance"], f"{ctx}.compliance")
    _prose(errs, insert["honesty_rules"], f"{ctx}.honesty_rules")

    # --- storyboard contract
    sc = insert["storyboard_contract"]
    if not isinstance(sc, dict):
        errs.append(f"{ctx}.storyboard_contract: must be an object")
    else:
        for key in ("field", "kind_value", "sits_beside", "note"):
            if not isinstance(sc.get(key), str) or not sc[key].strip():
                errs.append(f"{ctx}.storyboard_contract: {key} must be a non-empty string")
        if sc.get("kind_value") not in (None, kind):
            errs.append(f"{ctx}.storyboard_contract: kind_value {sc['kind_value']!r} is not "
                        f"this insert's kind")
        if sc.get("sits_beside") == sc.get("field"):
            errs.append(f"{ctx}.storyboard_contract: an insert that sits beside its own "
                        f"field replaces the block's asset, and then it has nothing to "
                        f"degrade to")

    # --- placement
    pl = insert["placement"]
    if not isinstance(pl, dict):
        errs.append(f"{ctx}.placement: must be an object")
    elif audio:
        errs += validate_audio_placement(pl, f"{ctx}.placement")
    else:
        pctx = f"{ctx}.placement"
        min_block = _positive(errs, pl, "min_block_seconds", pctx)
        if library:
            # A recognised picture has no reading time: its span is the
            # block's, and the ceiling is the longest block a pattern makes.
            max_span = _positive(errs, pl, "max_block_seconds", pctx)
            span_key = "max_block_seconds"
        else:
            _positive(errs, pl, "reading_rate_cps", pctx)
            max_span = _positive(errs, pl, "max_reading_seconds", pctx)
            span_key = "max_reading_seconds"
        max_inserts = _positive(errs, pl, "max_inserts_per_video", pctx, integral=True)
        _prose(errs, pl.get("rule"), f"{pctx}.rule")
        _prose(errs, pl.get("priority"), f"{pctx}.priority")
        if min_block is not None and max_span is not None and max_span < min_block:
            errs.append(f"{pctx}: {span_key} {max_span} is under the "
                        f"min_block_seconds floor {min_block} - no insert could ever "
                        f"both fit and be allowed")
        if max_inserts is not None and max_span is not None:
            budget = max_inserts * max_span
            if budget > MAX_TARGET_SECONDS / 2:
                errs.append(f"{pctx}: {max_inserts} insert(s) of up to {max_span}s can take "
                            f"{budget:.0f}s of a video whose ceiling is "
                            f"{MAX_TARGET_SECONDS:.0f}s - past half the running time this "
                            f"is not a video with inserts in it, it is a slideshow")

    # --- provenance
    pr = insert["provenance"]
    if not isinstance(pr, dict):
        errs.append(f"{ctx}.provenance: must be an object")
    else:
        req = pr.get("required")
        if not isinstance(req, list) or not req or not all(
                isinstance(f, str) and f for f in req):
            errs.append(f"{ctx}.provenance.required: must be a non-empty list of field names")
        elif len(set(req)) != len(req):
            errs.append(f"{ctx}.provenance.required: duplicate field names in {req}")
        cond = pr.get("conditional", {})
        if not isinstance(cond, dict):
            errs.append(f"{ctx}.provenance.conditional: must be an object of "
                        f"field -> when it is required")
        else:
            for field, when in cond.items():
                if not isinstance(when, str) or not when.strip():
                    errs.append(f"{ctx}.provenance.conditional.{field}: must say when the "
                                f"field is required")
        # CF-0236: a library layer's `skip_reason` is on every record - null on
        # the placed file, otherwise one of a closed list - so the list is part
        # of the contract, not prose a reader has to parse the names out of.
        if library and isinstance(cond, dict) and "skip_reason" in cond:
            reasons = pr.get("skip_reasons")
            legacy = pr.get("legacy_skip_reasons", [])
            if not isinstance(reasons, list) or not reasons or not all(
                    isinstance(r, str) and r for r in reasons) or len(set(reasons)) != len(reasons):
                errs.append(f"{ctx}.provenance.skip_reasons: must be a non-empty list of "
                            f"distinct names - the closed values of `skip_reason`")
            elif not isinstance(legacy, list) or set(legacy) & set(reasons):
                errs.append(f"{ctx}.provenance.legacy_skip_reasons: must be a list of names "
                            f"no longer written, none of them in skip_reasons")
        if not isinstance(pr.get("written_to"), str) or not pr["written_to"].strip():
            errs.append(f"{ctx}.provenance: written_to must name the file the record lands in")
        if not library:
            vals = pr.get("capture_method_values")
            if not isinstance(vals, list) or sorted(vals) != sorted(accepted_methods(insert)):
                errs.append(f"{ctx}.provenance.capture_method_values: must be exactly the "
                            f"accepted methods {sorted(accepted_methods(insert))}")
            shape = pr.get("record_shape")
            if not isinstance(shape, dict):
                errs.append(f"{ctx}.provenance.record_shape: must spell out the record")
            else:
                owed = list(req or []) + list(cond or []) + list(INSERT_RECORD_KEYS)
                missing = [f for f in owed if f not in shape]
                if missing:
                    errs.append(f"{ctx}.provenance.record_shape: missing {missing} - every "
                                f"required, conditional and POLICY.md field is in the record")

    # --- attribution
    at = insert["attribution"]
    if not isinstance(at, dict):
        errs.append(f"{ctx}.attribution: must be an object")
    else:
        visible = at.get("must_be_visible_in_insert")
        if library:
            if visible is not False:
                errs.append(f"{ctx}.attribution: must_be_visible_in_insert must be false "
                            f"on a library kind - a credit inside the frame is not the "
                            f"picture the viewer recognises; the credit goes on the "
                            f"sourcing line (reuse_sourcing_line)")
            if at.get("reuse_sourcing_line") is not True:
                errs.append(f"{ctx}.attribution: a library kind pays its attribution on "
                            f"the sourcing line, so reuse_sourcing_line must be true - "
                            f"off-frame and off-line is no attribution at all")
        elif visible is not True:
            errs.append(f"{ctx}.attribution: must_be_visible_in_insert must be true - "
                        f"attribution that exists only in the JSON is not attribution")
        el = at.get("required_elements")
        if not isinstance(el, list) or not el:
            errs.append(f"{ctx}.attribution.required_elements: must be a non-empty list")
        elif isinstance(insert["provenance"].get("required"), list):
            unknown = [e for e in el if e not in insert["provenance"]["required"]]
            if unknown:
                errs.append(f"{ctx}.attribution.required_elements: {unknown} are not "
                            f"provenance fields - what is shown on screen and what is "
                            f"recorded have to be the same facts")
        if not isinstance(at.get("reuse_sourcing_line"), bool):
            errs.append(f"{ctx}.attribution: reuse_sourcing_line must be a boolean")

    # --- legibility (captured) / asset_floor (library)
    lg = insert.get("legibility")
    if library:
        errs += validate_library_fields(insert, ctx)
    elif not isinstance(lg, dict):
        errs.append(f"{ctx}.legibility: must be an object")
    else:
        lctx = f"{ctx}.legibility"
        frac = lg.get("min_text_height_fraction_of_caption")
        if isinstance(frac, bool) or not isinstance(frac, (int, float)) or not (0 < frac <= 1):
            errs.append(f"{lctx}.min_text_height_fraction_of_caption: must lie in (0, 1] - "
                        f"the floor is a share of the renderer's own caption size, not a "
                        f"pixel count that goes stale the next time the theme moves")
        _positive(errs, lg, "caption_size_px_reference", lctx)
        _positive(errs, lg, "frame_height_reference", lctx)
        width = _positive(errs, lg, "frame_width_reference", lctx)
        capture_width = _positive(errs, lg, "min_capture_width_px", lctx)
        if width is not None and capture_width is not None and capture_width < width:
            errs.append(f"{lctx}: min_capture_width_px {capture_width} is under the "
                        f"delivered frame width {width} - such a capture can only be "
                        f"shown by enlarging it, which allow_upscale forbids")
        if lg.get("allow_upscale") is not False:
            errs.append(f"{lctx}: allow_upscale must be false - an enlarged document is a "
                        f"blurred document, and a blurred proof proves nothing")
        min_lines = _positive(errs, lg, "min_recognised_lines", lctx, integral=True)
        min_gating = _positive(errs, lg, "min_gating_lines", lctx, integral=True)
        max_lines = _positive(errs, lg, "max_lines", lctx, integral=True)
        if min_lines is not None and max_lines is not None and max_lines < min_lines:
            errs.append(f"{lctx}: max_lines {max_lines} is under min_recognised_lines "
                        f"{min_lines}")
        if min_gating is not None and max_lines is not None and max_lines < min_gating:
            errs.append(f"{lctx}: max_lines {max_lines} is under min_gating_lines "
                        f"{min_gating}")
        if not isinstance(lg.get("measured_with"), str) or not lg["measured_with"].strip():
            errs.append(f"{lctx}: measured_with must name the instrument - a gate whose "
                        f"instrument is unnamed cannot be reproduced or argued with")
        errs += validate_gating_lines(insert, lg, lctx)

    # --- composition (picture) / mix (audio)
    cp = insert.get("composition")
    if audio:
        errs += validate_mix(insert["mix"], f"{ctx}.mix")
        _prose(errs, insert["exclusions"], f"{ctx}.exclusions")
    elif not isinstance(cp, dict):
        errs.append(f"{ctx}.composition: must be an object")
    else:
        cctx = f"{ctx}.composition"
        if cp.get("fit") != "contain":
            errs.append(f"{cctx}.fit: must be 'contain' - a document is fitted whole; "
                        f"cover-cropping into one cuts off the words that are the point "
                        f"(the CF-0047 argument, applied to a page instead of a card)")
        for key in ("ken_burns", "punch", "smart_crop"):
            if cp.get(key) is not False:
                errs.append(f"{cctx}.{key}: must be false - motion and zoom on text push "
                            f"the words the viewer is reading off the edge of the frame")
        if kind in PICTURE_OWN_MOTION:
            errs += validate_picture_motion(cp.get("motion"), f"{cctx}.motion")
        if not isinstance(cp.get("background"), str) or not cp["background"].strip():
            errs.append(f"{cctx}.background: must name what fills the letterboxing")
        want = PICTURE_OUR_CAPTIONS.get(kind)
        if want is None:
            errs.append(f"{cctx}.our_captions: {kind!r} is not in PICTURE_OUR_CAPTIONS - "
                        f"a picture kind has to answer for itself whether our captions "
                        f"keep running under it, and inheriting another kind's answer is "
                        f"the CF-0379 defect itself")
        elif cp.get("our_captions") != want:
            errs.append(f"{cctx}.our_captions: must be {want!r} for {kind!r} - "
                        f"{PICTURE_OUR_CAPTIONS_WHY[want]}")
        gate = cp.get("asset_gate")
        if not isinstance(gate, dict):
            errs.append(f"{cctx}.asset_gate: must be an object with `skipped` and `added`")
        else:
            skipped = gate.get("skipped")
            if not isinstance(skipped, dict):
                errs.append(f"{cctx}.asset_gate.skipped: must be an object of "
                            f"check -> why it does not apply")
            else:
                for check, why in skipped.items():
                    if not isinstance(why, str) or len(why.strip()) < 40:
                        errs.append(f"{cctx}.asset_gate.skipped.{check}: a check this kind "
                                    f"skips has to say why in full - a gate switched off "
                                    f"without an argument is a gate switched off")
            added = gate.get("added")
            if not isinstance(added, list) or not added:
                errs.append(f"{cctx}.asset_gate.added: must be a non-empty list - a kind "
                            f"that only ever relaxes checks has lowered the bar, which is "
                            f"the thing CF-0047 refused to do")

    # --- degradation
    dg = insert["degradation"]
    if not isinstance(dg, dict):
        errs.append(f"{ctx}.degradation: must be an object")
    else:
        if dg.get("on_failure") != DEGRADE_TO_ORDINARY_BLOCK:
            errs.append(f"{ctx}.degradation.on_failure: must be "
                        f"{DEGRADE_TO_ORDINARY_BLOCK!r} - an insert is a superstructure, "
                        f"not a rung of motion -> stills -> typographic, and a missing one "
                        f"costs the insert and nothing else")
        _prose(errs, dg.get("never_substitute"), f"{ctx}.degradation.never_substitute")

    # --- metadata
    md = insert["metadata"]
    if not isinstance(md, dict):
        errs.append(f"{ctx}.metadata: must be an object")
    else:
        for key in ("requested_field", "delivered_field", "provenance_field"):
            if not isinstance(md.get(key), str) or not md[key].strip():
                errs.append(f"{ctx}.metadata: {key} must be a non-empty field name")
        if md.get("requested_field") == md.get("delivered_field"):
            errs.append(f"{ctx}.metadata: requested and delivered must be two fields, or "
                        f"the Analyst cannot tell an insert that shipped from one that was "
                        f"wanted (CF-0041's requested/delivered argument)")
        if library:
            for key in ("requested_shape", "delivered_shape"):
                if not isinstance(md.get(key), str) or len(md[key].strip()) < 40:
                    errs.append(f"{ctx}.metadata.{key}: a library kind spells out the "
                                f"shape the Video Editor writes - two repos implement "
                                f"this file, and 'a list' is not a contract")
            outcomes = md.get("outcomes")
            if not isinstance(outcomes, list) or not outcomes or not all(
                    isinstance(o, str) and o.strip() for o in outcomes):
                errs.append(f"{ctx}.metadata.outcomes: must be a non-empty list of outcome "
                            f"names - a free-text reason is a reason nobody counts")
            elif OUTCOME_PLACED not in outcomes:
                errs.append(f"{ctx}.metadata.outcomes: {OUTCOME_PLACED!r} is missing - the "
                            f"delivered list could never say an insert arrived")
            elif len(set(outcomes)) != len(outcomes):
                errs.append(f"{ctx}.metadata.outcomes: duplicates in {outcomes}")

    if not library:
        errs += validate_capture_methods(insert["capture_methods"], ctx)
        errs += validate_capture_priority(insert, ctx)
        errs += validate_evidence_contract(insert, ctx)
        errs += validate_script_contract(insert, ctx)
        if isinstance(md, dict):
            errs += validate_captured_metadata(insert, md, ctx)

    # --- validated: honesty about where the numbers came from
    va = insert["validated"]
    if not isinstance(va, dict):
        errs.append(f"{ctx}.validated: must be an object")
    else:
        if va.get("status") not in VALIDATION_STATUSES:
            errs.append(f"{ctx}.validated.status: must be one of {VALIDATION_STATUSES}, "
                        f"got {va.get('status')!r}")
        for key in ("measured_on", "note"):
            if not isinstance(va.get(key), str) or not va[key].strip():
                errs.append(f"{ctx}.validated: {key} must be a non-empty string - "
                            f"thresholds that claim nothing about their origin are how "
                            f"CF-0003's constants drifted")

    return errs


def validate_library_fields(insert, ctx):
    """The library-kind branch: source, selection, meaning_rule, asset_floor."""
    errs = []
    kind = insert.get("insert_kind")
    layer = LIBRARY_BLOCK_LAYERS.get(kind, {})

    # --- source
    so = insert["source"]
    sctx = f"{ctx}.source"
    if not isinstance(so, dict):
        errs.append(f"{sctx}: must be an object")
    else:
        for key in ("library_kind", "folder", "index", "index_schema", "rule",
                    "executable_today_lives_in", "note"):
            if not isinstance(so.get(key), str) or not so[key].strip():
                errs.append(f"{sctx}: {key} must be a non-empty string")
        if layer and so.get("library_kind") != layer["library_kind"]:
            errs.append(f"{sctx}: library_kind {so.get('library_kind')!r} is not the "
                        f"{layer['library_kind']!r} LIBRARY_BLOCK_LAYERS names for {kind}")
        if layer and so.get("index") != layer["index"]:
            errs.append(f"{sctx}: index {so.get('index')!r} is not {layer['index']!r}")
        if "executable_today" in so:
            errs.append(f"{sctx}: executable_today is code (LIBRARY_BLOCK_LAYERS), not a "
                        f"field of this file - two copies of one flag is how they disagree")

    # --- selection
    se = insert["selection"]
    ectx = f"{ctx}.selection"
    audio = is_audio_kind(kind)
    max_key = "max_sounds_per_script" if audio else "max_reactions_per_script"
    if not isinstance(se, dict):
        errs.append(f"{ectx}: must be an object")
    else:
        text_keys = ("script_stage", "script_field", "absent_means", "ranking", "note")
        text_keys += ("matching",) if audio else ("query_embedding",)
        for key in text_keys:
            if not isinstance(se.get(key), str) or not se[key].strip():
                errs.append(f"{ectx}: {key} must be a non-empty string")
        shape = se.get("script_shape")
        field = se.get("script_field")
        if not isinstance(shape, dict) or field not in shape:
            errs.append(f"{ectx}.script_shape: must be an object keyed by script_field "
                        f"{field!r} - the writer's side of the contract, spelled out")
        max_req = _positive(errs, se, max_key, ectx, integral=True)
        pl = insert.get("placement") or {}
        if max_req is not None and pl.get("max_inserts_per_video") not in (None, max_req):
            errs.append(f"{ectx}: {max_key} {max_req} disagrees with "
                        f"placement.max_inserts_per_video {pl.get('max_inserts_per_video')} "
                        f"- the writer and the editor would count differently")
        vocab = se.get("intent_vocabulary")
        if not isinstance(vocab, dict) or not vocab:
            errs.append(f"{ectx}.intent_vocabulary: must be a non-empty object of "
                        f"intent -> {{{'tags, description' if audio else 'default_query'}}} - "
                        f"a closed vocabulary is what the Analyst counts over")
        else:
            for intent, spec in vocab.items():
                if not isinstance(intent, str) or not intent or intent != intent.lower() \
                        or not intent.replace("_", "").isalnum():
                    errs.append(f"{ectx}.intent_vocabulary: {intent!r} is not a lowercase "
                                f"identifier")
                if audio:
                    errs += _validate_sound_intent(spec, f"{ectx}.intent_vocabulary.{intent}")
                elif not isinstance(spec, dict) or not isinstance(spec.get("default_query"), str) \
                        or len(spec["default_query"].strip()) < 10:
                    errs.append(f"{ectx}.intent_vocabulary.{intent}: needs a default_query "
                                f"in words, so a request with no query still embeds")
        if audio:
            # Text matching over tags: the floor is a count of matching tags,
            # and there is no embedding and no free-text query on purpose.
            _positive(errs, se, "min_tag_matches", ectx, integral=True)
            for key in ("min_similarity", "query_embedding"):
                if key in se:
                    errs.append(f"{ectx}.{key}: a sound is matched on tags, not ranked by "
                                f"an embedding - the index carries none for audio")
            entry = (shape or {}).get(field, [{}])
            if isinstance(entry, list) and entry and isinstance(entry[0], dict) \
                    and "query" in entry[0]:
                errs.append(f"{ectx}.script_shape: a sound request carries no `query` - "
                            f"free text over a tag match is a tag nobody agreed on")
        else:
            sim = se.get("min_similarity")
            if isinstance(sim, bool) or not isinstance(sim, (int, float)) or not (0 < sim < 1):
                errs.append(f"{ectx}.min_similarity: must lie in (0, 1) - at 0 the least "
                            f"wrong picture is placed, at 1 nothing is")
            lead = se.get("min_lead")
            if isinstance(lead, bool) or not isinstance(lead, (int, float)) or not (0 < lead < 1):
                errs.append(f"{ectx}.min_lead: must lie in (0, 1) - an embedding-ranked kind "
                            f"is gated on the leader's lead over the field as well as on its "
                            f"score (CF-0143)")
            rank = se.get("lead_rank")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 3:
                errs.append(f"{ectx}.lead_rank: must be an integer of at least 3 - the second "
                            f"place is a right pick's own near-duplicate too often to be the "
                            f"field it has to beat (CF-0143)")
            if "tag_match" in se:
                errs += _validate_tag_match(se["tag_match"], shape, field,
                                            f"{ectx}.tag_match")
        if se.get("distinct_per_video") is not True:
            errs.append(f"{ectx}: distinct_per_video must be true - the same "
                        f"{'sound' if audio else 'picture'} twice in 55 seconds is a "
                        f"running gag nobody wrote")

    # --- meaning rule (M3)
    mr = insert["meaning_rule"]
    mctx = f"{ctx}.meaning_rule"
    if not isinstance(mr, dict):
        errs.append(f"{mctx}: must be an object")
    else:
        for key in ("label", "status", "rule", "negative_half_checked_by",
                    "positive_half_checked_by", "note"):
            if not isinstance(mr.get(key), str) or not mr[key].strip():
                errs.append(f"{mctx}: {key} must be a non-empty string")
        va = insert.get("validated") or {}
        if va.get("status") != "measured" and "not verified" not in str(mr.get("status", "")):
            errs.append(f"{mctx}.status: has to say 'not verified' while validated.status is "
                        f"not 'measured' - the positive half of M3 is only checkable by "
                        f"release, and this file may not present it as checked")

    # --- asset floor
    af = insert["asset_floor"]
    actx = f"{ctx}.asset_floor"
    if not isinstance(af, dict):
        errs.append(f"{actx}: must be an object")
    elif audio:
        errs += validate_audio_floor(af, actx)
    else:
        for key in ("rule", "general_floor_constant", "upscale_measure", "fit_box_source",
                    "audio_track", "measured_with", "note"):
            if not isinstance(af.get(key), str) or not af[key].strip():
                errs.append(f"{actx}: {key} must be a non-empty string")
        if af.get("rule") != PICTURE_FLOOR_RULE:
            errs.append(f"{actx}.rule: must be {PICTURE_FLOOR_RULE!r} - a picture is gated "
                        f"on its stretch in the insert box (CF-0392)")
        if af.get("general_floor_constant") != "MIN_SHORT_SIDE":
            errs.append(f"{actx}.general_floor_constant: must be 'MIN_SHORT_SIDE'")
        for key in ("min_short_side_px", "constant_name", "frame_width_reference",
                    "frame_height_reference"):
            if key in af:
                errs.append(f"{actx}.{key}: the short-side floor is gone (CF-0392) - the "
                            f"gate is the stretch in fit_box_px, and a stale key reads as "
                            f"a floor the editor no longer applies; drop it")
        general = _positive(errs, af, "general_floor_px", actx, integral=True)
        if general is not None and general != GENERAL_MIN_SHORT_SIDE:
            errs.append(f"{actx}.general_floor_px: is {general}, the footage floor is "
                        f"{GENERAL_MIN_SHORT_SIDE} - this file does not get to move it")
        if af.get("general_floor_untouched") is not True:
            errs.append(f"{actx}: general_floor_untouched must be true - MIN_SHORT_SIDE is "
                        f"not lowered for any insert kind (CF-0012)")
        if not isinstance(af.get("allow_upscale"), bool):
            errs.append(f"{actx}: allow_upscale must be a boolean")
        factor = _positive(errs, af, "max_upscale_factor", actx)
        output = _pixel_pair(errs, af, "output_px", actx)
        box = _pixel_pair(errs, af, "fit_box_px", actx)
        if output and box and (box[0] > output[0] or box[1] > output[1]):
            errs.append(f"{actx}.fit_box_px: {box} does not fit in output_px {output}")
        if box and factor is not None and min(box) / factor < MIN_ADMITTED_SIDE_PX:
            errs.append(f"{actx}: max_upscale_factor {factor} admits a {min(box) / factor:.0f}px "
                        f"picture across the box's narrow side - a thumbnail; the ceiling "
                        f"has to reject something")
        if af.get("allow_upscale") is False and factor is not None and factor > 1:
            errs.append(f"{actx}: allow_upscale is false but max_upscale_factor is {factor}")
        for key in ("still_suffixes", "animated_suffixes"):
            sfx = af.get(key)
            if not isinstance(sfx, list) or not all(
                    isinstance(s, str) and s.startswith(".") for s in sfx):
                errs.append(f"{actx}.{key}: must be a list of '.ext' suffixes")
        if af.get("audio_track") != "none":
            errs.append(f"{actx}.audio_track: must be 'none' - a file with sound is "
                        f"CF-0068's layer, not this one")
    return errs


def _validate_tag_match(tm, shape, field, tctx):
    """CF-0388: the optional tag route of an embedding-ranked kind. The floor
    is a fraction of CLIP's own ranking, and the words matched are fields the
    writer's request actually carries."""
    errs = []
    if not isinstance(tm, dict):
        return [f"{tctx}: must be an object"]
    frac = tm.get("floor_rank_fraction")
    if isinstance(frac, bool) or not isinstance(frac, (int, float)) or not (0 < frac <= 1):
        errs.append(f"{tctx}.floor_rank_fraction: must lie in (0, 1] - the share of the "
                    f"library, as CLIP ranks it, a tag-named file must stand inside")
    entry = (shape or {}).get(field, [{}])
    entry = entry[0] if isinstance(entry, list) and entry and isinstance(entry[0], dict) else {}
    sources = tm.get("sources")
    if not isinstance(sources, list) or not sources:
        errs.append(f"{tctx}.sources: must be a non-empty list of request fields")
    else:
        for s in sources:
            if s not in entry:
                errs.append(f"{tctx}.sources: {s!r} is not a field of script_shape.{field} "
                            f"- a tag can only be heard in words the request carries")
    if not isinstance(tm.get("note"), str) or not tm["note"].strip():
        errs.append(f"{tctx}: note must be a non-empty string")
    return errs


def _validate_sound_intent(spec, ictx):
    """One entry of a sound's intent_vocabulary: {tags[], description}. The
    tags are the whole of the matching, so they are identifiers, lowercase,
    and at least one; the description is for the person filling CF-0115."""
    errs = []
    if not isinstance(spec, dict):
        return [f"{ictx}: must be an object with `tags` and a `description`"]
    tags = spec.get("tags")
    if not isinstance(tags, list) or not tags or not all(
            isinstance(t, str) and t and t == t.lower() and t.replace("_", "").isalnum()
            for t in tags):
        errs.append(f"{ictx}.tags: must be a non-empty list of lowercase identifiers - the "
                    f"tags are the matching, and a tag with a space or a capital in it "
                    f"matches nothing in an index written by hand")
    elif len(set(tags)) != len(tags):
        errs.append(f"{ictx}.tags: duplicates in {tags}")
    if not isinstance(spec.get("description"), str) or len(spec["description"].strip()) < 10:
        errs.append(f"{ictx}: needs a description in words - what the sound is for, so "
                    f"that CF-0115 can fill the folder against the vocabulary")
    return errs


def validate_audio_placement(pl, pctx):
    """CF-0068: a sound sits on a moment, not on a block.

    Anchor from the forced alignment, a ceiling on the file rather than a
    floor on the block, a gap between two sounds, and the sections a sound
    may never cover. The budget check is the same one a picture gets, on
    the ceiling instead of the block span - two sounds of 1.5 s could not
    take half a video, but the check is what keeps the number honest.
    """
    errs = []
    for key in ("anchor", "anchor_source", "block_index", "rule", "priority",
                "protected_sections"):
        if key not in pl:
            errs.append(f"{pctx}: missing {key}")
    for key in ("anchor", "anchor_source", "block_index"):
        if key in pl and (not isinstance(pl[key], str) or not pl[key].strip()):
            errs.append(f"{pctx}: {key} must be a non-empty string")
    if pl.get("anchor_source") not in (None, "words.json"):
        errs.append(f"{pctx}.anchor_source: must be 'words.json' - the forced alignment is "
                    f"the one clock the voice, the captions and the beats share")
    for key in ("min_block_seconds", "max_block_seconds"):
        if key in pl:
            errs.append(f"{pctx}.{key}: a sound has no block floor or span - it is placed "
                        f"on a moment, and the block is recorded, not chosen")
    ceiling = _positive(errs, pl, "max_insert_seconds", pctx)
    if ceiling is not None and abs(ceiling - MAX_SOUND_SECONDS) > 1e-9:
        errs.append(f"{pctx}.max_insert_seconds: is {ceiling}, inserts_lib.MAX_SOUND_SECONDS "
                    f"is {MAX_SOUND_SECONDS} - the ceiling is the user's accepted "
                    f"mitigation and lives once, in shared/inserts/")
    gap = _positive(errs, pl, "min_gap_seconds", pctx)
    if gap is not None and ceiling is not None and gap < ceiling:
        errs.append(f"{pctx}: min_gap_seconds {gap} is under the ceiling {ceiling} - two "
                    f"sounds could overlap")
    max_inserts = _positive(errs, pl, "max_inserts_per_video", pctx, integral=True)
    if max_inserts is not None and ceiling is not None:
        budget = max_inserts * ceiling
        if budget > MAX_TARGET_SECONDS / 2:
            errs.append(f"{pctx}: {max_inserts} sound(s) of up to {ceiling}s take "
                        f"{budget:.0f}s of a {MAX_TARGET_SECONDS:.0f}s ceiling")
    sections = pl.get("protected_sections")
    if not isinstance(sections, list) or not all(isinstance(s, str) and s for s in sections):
        errs.append(f"{pctx}.protected_sections: must be a list of section names")
    elif not {"hook", "payoff"} <= set(sections):
        errs.append(f"{pctx}.protected_sections: hook and payoff carry the claim and the "
                    f"verdict, and a sound over either is the one the video cannot afford "
                    f"- both have to be protected")
    _prose(errs, pl.get("rule"), f"{pctx}.rule")
    _prose(errs, pl.get("priority"), f"{pctx}.priority")
    return errs


def validate_audio_floor(af, actx):
    """CF-0068: the floor of a sound is a ceiling - it is gated on being short.

    The ceiling is inserts_lib's and is checked equal rather than repeated;
    the picture floors are named as untouched, exactly as the meme names
    MIN_SHORT_SIDE untouched, and a file with a video stream is a clip, which
    the CF-0068 decision keeps out of every layer.
    """
    errs = []
    for key in ("constant_name", "constant_lives_in", "general_floor_constant",
                "audio_track", "video_track", "measured_with", "note"):
        if not isinstance(af.get(key), str) or not af[key].strip():
            errs.append(f"{actx}: {key} must be a non-empty string")
    if af.get("constant_name") != "MAX_SOUND_SECONDS":
        errs.append(f"{actx}.constant_name: must be 'MAX_SOUND_SECONDS' - the ceiling has one "
                    f"name, inserts_lib's")
    if af.get("constant_name") == af.get("general_floor_constant"):
        errs.append(f"{actx}: constant_name must not be the general floor's")
    ceiling = _positive(errs, af, "max_duration_s", actx)
    if ceiling is not None and abs(ceiling - MAX_SOUND_SECONDS) > 1e-9:
        errs.append(f"{actx}.max_duration_s: is {ceiling}, inserts_lib.MAX_SOUND_SECONDS is "
                    f"{MAX_SOUND_SECONDS} - this file does not get to move it")
    floor = _positive(errs, af, "min_duration_s", actx)
    if floor is not None and ceiling is not None and floor >= ceiling:
        errs.append(f"{actx}: min_duration_s {floor} is not under the ceiling {ceiling}")
    if af.get("general_floor_untouched") is not True:
        errs.append(f"{actx}: general_floor_untouched must be true - a sound has no short "
                    f"side, and MIN_SHORT_SIDE keeps its footage signal (CF-0012)")
    for key in ("min_short_side_px", "allow_upscale", "max_upscale_factor"):
        if key in af:
            errs.append(f"{actx}.{key}: a pixel floor on a sound - drop it")
    sfx = af.get("suffixes")
    if not isinstance(sfx, list) or not sfx or not all(
            isinstance(s, str) and s.startswith(".") for s in sfx):
        errs.append(f"{actx}.suffixes: must be a non-empty list of '.ext' suffixes")
    else:
        unknown = sorted(set(sfx) - set(SOUND_SUFFIXES))
        if unknown:
            errs.append(f"{actx}.suffixes: {unknown} are not sound suffixes inserts_lib "
                        f"indexes ({sorted(SOUND_SUFFIXES)})")
    if af.get("audio_track") != "required":
        errs.append(f"{actx}.audio_track: must be 'required' - a sound is its audio track")
    if af.get("video_track") != "none":
        errs.append(f"{actx}.video_track: must be 'none' - a file with a picture is a clip, "
                    f"and a clip is a muted meme or nothing (CF-0068 decision)")
    return errs


def validate_mix(mx, mctx):
    """CF-0068: the fourth input of build_soundtrack.py, as numbers.

    Level relative to the voice, which of the other inputs the sound ducks,
    fades, the hard cut at the ceiling, a peak ceiling and an audibility gate
    - and a `constants` map naming what agents/video-editor defines, so that
    the dispatch implementing it has the names and the values in one place.
    """
    errs = []
    if not isinstance(mx, dict):
        return [f"{mctx}: must be an object"]
    for key in ("input_name", "level_reference", "our_captions", "note"):
        if not isinstance(mx.get(key), str) or not mx[key].strip():
            errs.append(f"{mctx}: {key} must be a non-empty string")
    inputs = mx.get("existing_inputs")
    if not isinstance(inputs, list) or not inputs or mx.get("input_name") in inputs:
        errs.append(f"{mctx}.existing_inputs: must list the inputs the mix already has, "
                    f"and input_name must not be one of them - it is the fourth")
    level = mx.get("level_rel_voice_db")
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not (-20 <= level <= 0):
        errs.append(f"{mctx}.level_rel_voice_db: must lie in [-20, 0] - above the voice "
                    f"the sound is a second speaker, 20 dB under it is the bed")
    if mx.get("ducks_bed") is not True:
        errs.append(f"{mctx}: ducks_bed must be true - the bed yields to the sound as it "
                    f"yields to the voice, or the sound fights the bed at the moment it is "
                    f"meant to punctuate")
    if mx.get("ducks_voice") is not False:
        errs.append(f"{mctx}: ducks_voice must be false - the narration is the product, and "
                    f"a hole in the one track every layer is timed against is not a mix "
                    f"decision this file may make")
    fade_in = _positive(errs, mx, "fade_in_ms", mctx, integral=True)
    fade_out = _positive(errs, mx, "fade_out_ms", mctx, integral=True)
    cut = _positive(errs, mx, "hard_cut_seconds", mctx)
    if cut is not None and abs(cut - MAX_SOUND_SECONDS) > 1e-9:
        errs.append(f"{mctx}.hard_cut_seconds: is {cut}, inserts_lib.MAX_SOUND_SECONDS is "
                    f"{MAX_SOUND_SECONDS} - the mix cuts where the ceiling is")
    if None not in (fade_in, fade_out, cut) and fade_in + fade_out >= cut * 1000:
        errs.append(f"{mctx}: fades {fade_in}+{fade_out} ms leave nothing of a "
                    f"{cut}s sound")
    peak = mx.get("peak_ceiling_dbfs")
    if isinstance(peak, bool) or not isinstance(peak, (int, float)) or not (-6 <= peak < 0):
        errs.append(f"{mctx}.peak_ceiling_dbfs: must lie in [-6, 0)")
    au = mx.get("audibility")
    if not isinstance(au, dict):
        errs.append(f"{mctx}.audibility: must be an object - a placed sound nobody can hear "
                    f"is a delivered insert that did not arrive")
    else:
        for key in ("constant_name", "measured_with", "on_failure"):
            if not isinstance(au.get(key), str) or not au[key].strip():
                errs.append(f"{mctx}.audibility: {key} must be a non-empty string")
        rms = au.get("min_rms_db")
        if isinstance(rms, bool) or not isinstance(rms, (int, float)) or not (-60 < rms < 0):
            errs.append(f"{mctx}.audibility.min_rms_db: must lie in (-60, 0)")
    if mx.get("our_captions") != "visible":
        errs.append(f"{mctx}.our_captions: must be 'visible' - a sound has no text and hides "
                    f"nothing; the picture kinds' `shown`/`hidden` is about a picture")
    consts = mx.get("constants")
    if not isinstance(consts, dict) or not consts:
        errs.append(f"{mctx}.constants: must map the constant names agents/video-editor "
                    f"defines to their values")
    else:
        expect = {
            "MAX_SOUND_SECONDS": MAX_SOUND_SECONDS,
            "SOUND_LEVEL_REL_VOICE_DB": mx.get("level_rel_voice_db"),
            "SOUND_DUCKS_BED": mx.get("ducks_bed"),
            "SOUND_DUCKS_VOICE": mx.get("ducks_voice"),
            "SOUND_FADE_IN_MS": mx.get("fade_in_ms"),
            "SOUND_FADE_OUT_MS": mx.get("fade_out_ms"),
            "SOUND_PEAK_CEILING_DBFS": mx.get("peak_ceiling_dbfs"),
        }
        if isinstance(au, dict):
            expect[au.get("constant_name", "MIN_SOUND_RMS_DB")] = au.get("min_rms_db")
        for name, value in expect.items():
            if name not in consts:
                errs.append(f"{mctx}.constants: {name} missing")
            elif consts[name] != value:
                errs.append(f"{mctx}.constants.{name}: {consts[name]!r} disagrees with the "
                            f"field it names ({value!r}) - two copies of one number")
        for name, value in consts.items():
            if not isinstance(value, (bool, int, float)):
                errs.append(f"{mctx}.constants.{name}: must be a number or a boolean flag")
    return errs


def executable_methods(insert):
    """The capture methods that could actually run today. A library kind has
    no capture methods; whether it is executable is `layer_executable`."""
    return sorted(m["method"] for m in insert.get("capture_methods", [])
                  if m.get("executable_today"))


def layer_executable(kind, insert=None):
    """Can a channel switch this block layer on today? Library kinds answer
    from LIBRARY_BLOCK_LAYERS, captured kinds from their capture methods."""
    if is_library_kind(kind):
        return bool(LIBRARY_BLOCK_LAYERS[kind]["executable_today"])
    return bool(executable_methods(insert or {}))


def open_questions(inserts=None):
    """(insert_kind, method, question) for every method still awaiting a decision."""
    out = []
    for kind, insert in sorted((inserts if inserts is not None else load_inserts()).items()):
        for m in insert.get("capture_methods", []):
            if m.get("needs_decision"):
                out.append((kind, m.get("method"), m.get("question", "")))
    return out


def validate_video_layer_switch(kind, switch, kctx):
    """CF-0014: a channel's switch over a video-level layer (VIDEO_LAYERS).

    Same shape as a block layer's switch - `enabled` and a reason - minus
    the capture method, which this kind of layer does not have: the material
    comes from the factory library by rotation. The gate is the same one:
    enabled only when the layer is executable today.
    """
    errs = []
    layer = VIDEO_LAYERS[kind]
    if not isinstance(switch, dict):
        return [f"{kctx}: must be an object with `enabled` and a reason"]
    enabled = switch.get("enabled")
    if not isinstance(enabled, bool):
        return [f"{kctx}: enabled must be a boolean"]
    if not str(switch.get("reason", "")).strip():
        errs.append(f"{kctx}: needs a reason - whether a channel wants a layer is an "
                    f"editorial decision, and a bare {str(enabled).lower()} records a "
                    f"preference instead of one")
    if switch.get("capture_method") is not None:
        errs.append(f"{kctx}: a video-level layer has no capture method - its material "
                    f"is the factory library shared/inserts/{layer['library_kind']}s/ by "
                    f"rotation; drop capture_method")
    if enabled and not layer["executable_today"]:
        errs.append(f"{kctx}: enabled, but nothing can place a {kind} yet "
                    f"(blocked by {layer['blocked_by']}) - the switch would describe a "
                    f"video the factory cannot make. Land the wiring in agents/video-editor "
                    f"and flip VIDEO_LAYERS[{kind!r}]['executable_today'] first")
    return errs


def validate_library_layer_switch(kind, switch, kctx, inserts):
    """CF-0067: a channel's switch over a library block layer
    (LIBRARY_BLOCK_LAYERS). Same shape as the underlay's - `enabled` and a
    reason, no capture method - and the same gate: enabled only while the
    layer is executable today, which is a flag in this file that the Video
    Editor part of the task flips after the code lands."""
    errs = []
    layer = LIBRARY_BLOCK_LAYERS[kind]
    if not isinstance(switch, dict):
        return [f"{kctx}: must be an object with `enabled` and a reason"]
    enabled = switch.get("enabled")
    if not isinstance(enabled, bool):
        return [f"{kctx}: enabled must be a boolean"]
    if not str(switch.get("reason", "")).strip():
        errs.append(f"{kctx}: needs a reason - whether a channel wants a layer is an "
                    f"editorial decision, and a bare {str(enabled).lower()} records a "
                    f"preference instead of one")
    if switch.get("capture_method") is not None:
        errs.append(f"{kctx}: a library block layer has no capture method - its material "
                    f"is the factory library shared/inserts/{layer['library_kind']}s/ "
                    f"selected by the script's intent; drop capture_method")
    if kind not in inserts:
        errs.append(f"{kctx}: no inserts/{kind}.json describes this layer")
    if enabled and not layer["executable_today"]:
        errs.append(f"{kctx}: enabled, but nothing can place a {kind} yet "
                    f"(blocked by {layer['blocked_by']}) - the switch would describe a "
                    f"video the factory cannot make. Land the Video Editor part of "
                    f"{layer['blocked_by']} and flip "
                    f"LIBRARY_BLOCK_LAYERS[{kind!r}]['executable_today'] first")
    errs += _bank_errors(kind, switch, enabled, kctx)
    return errs


def _bank_errors(kind, switch, enabled, kctx, inserts_root=None):
    """CF-0393: `bank` names a channel's own meme bank. Only the meme layer
    has one; the name must be a folder shared/inserts/memes-<channel>/ with
    its index on disk; and a switch may be on over a named bank only once the
    bank holds an accepted entry - an empty or all-pending bank would leave
    the layer with nothing to place, and nothing may fall back to the
    default (cinema) bank in its stead."""
    if "bank" not in switch:
        return []
    if kind != "meme":
        return [f"{kctx}.bank: only the meme layer has per-channel banks"]
    root = inserts_root or _inserts_lib.INSERTS_ROOT
    try:
        name, folder = _inserts_lib.meme_bank_folder(
            {"insert_layers": {"meme": {"bank": switch["bank"]}}}, root)
    except _inserts_lib.MemeBankError as e:
        return [f"{kctx}.bank: {e}"]
    if enabled and name is not None:
        entries = _inserts_lib.load_index("meme", root, name).get("entries") or []
        if not [e for e in entries if e.get("review") != "pending"]:
            return [f"{kctx}: enabled over the bank {name}/, which holds no accepted "
                    f"entry yet - accept the user's picks on the meme desk "
                    f"(scripts/meme_desk.py apply --bank {name}) before switching it on"]
    return []


def validate_pattern_layer_fields(patterns, inserts=None):
    """CF-0067: every pattern answers every insert layer that has a file.

    A meme is an orthogonal decoration any pattern may carry, so the pattern's
    `<kind>_layer` is the first gate the selector reads - and a pattern that
    has not filled it has not been asked, which the selector would have to
    read as either yes or no and be wrong half the time. The captured kind
    was first left optional here on the argument that a proof is placed by
    its claim, not by the pattern; the first Video Editor run (CF-0071,
    2026-09-06) showed what optional means in practice - `proof_layer: null`
    on all four patterns, read as `pattern_refused` on every request, so the
    layer could never fire even with the channel switch on. Every kind in
    `inserts/` is answered by every pattern now; patterns/validate_patterns.py
    still checks the shape.
    """
    errs = []
    inserts = inserts if inserts is not None else load_inserts()
    for kind in sorted(set(LIBRARY_BLOCK_LAYERS) | set(inserts)):
        if kind not in inserts:
            continue
        field = f"{kind}_layer"
        for pid, pattern in sorted(patterns.items()):
            pctx = f"patterns/{pid}.json.{field}"
            entry = pattern.get(field)
            if not isinstance(entry, dict) or not isinstance(entry.get("allowed"), bool):
                errs.append(f"{pctx}: missing or without a boolean `allowed` - an insert "
                            f"layer has to be answered by every pattern, because 'not "
                            f"asked' is not an answer the selector can act on (it reads "
                            f"as refused, and the layer never fires)")
                continue
            if len(str(entry.get("reason", "")).strip()) < 40:
                errs.append(f"{pctx}: needs a reason either way - which shapes tolerate a "
                            f"reaction insert is the pattern's argument, and a bare "
                            f"{str(entry['allowed']).lower()} is a preference")
    return errs


def validate_channel_inserts(cfg, inserts=None, ctx="channel"):
    """The channel side: which layers this channel switches on, and may it.

    The gate that matters is the last one: a channel may not enable a layer
    that nothing can build yet. `patterns/` has the same rule for patterns, and
    it is there because admitting a capability ahead of its code is how a
    config comes to describe a video the factory cannot make.
    """
    errs = []
    inserts = inserts if inserts is not None else load_inserts()
    block = cfg.get("insert_layers")
    if block is None:
        # Absent is legal and means every layer is off. A channel written
        # before the layer existed must keep working unchanged.
        return errs
    if not isinstance(block, dict):
        return [f"{ctx}: insert_layers must be an object of kind -> switch"]
    for kind, switch in sorted(block.items()):
        # `note` is free text, the same way the channel's `patterns` block
        # carries one. Everything else in here is a switch.
        if kind == "note":
            continue
        kctx = f"{ctx}.insert_layers.{kind}"
        if kind in VIDEO_LAYERS:
            errs += validate_video_layer_switch(kind, switch, kctx)
            continue
        if kind in LIBRARY_BLOCK_LAYERS:
            errs += validate_library_layer_switch(kind, switch, kctx, inserts)
            continue
        if kind not in KNOWN_INSERT_KINDS:
            errs.append(f"{kctx}: unknown insert kind (known: "
                        f"{sorted(KNOWN_INSERT_KINDS)} and video layers "
                        f"{sorted(VIDEO_LAYERS)})")
            continue
        if not isinstance(switch, dict):
            errs.append(f"{kctx}: must be an object with `enabled` and a reason")
            continue
        enabled = switch.get("enabled")
        if not isinstance(enabled, bool):
            errs.append(f"{kctx}: enabled must be a boolean")
            continue
        if not str(switch.get("reason", "")).strip():
            errs.append(f"{kctx}: needs a reason - whether a channel wants a layer is an "
                        f"editorial decision, and a bare {str(enabled).lower()} records a "
                        f"preference instead of one")
        if kind not in inserts:
            errs.append(f"{kctx}: no inserts/{kind}.json describes this layer")
            continue
        available = executable_methods(inserts[kind])
        chosen = switch.get("capture_method")
        if chosen is not None and chosen in rejected_methods(inserts[kind]):
            errs.append(f"{kctx}: capture_method {chosen!r} was rejected by decision "
                        f"(inserts/{kind}.json capture_methods[{chosen}].decision) - a "
                        f"channel cannot choose what the user turned down")
        elif enabled:
            if not available:
                errs.append(f"{kctx}: enabled, but no capture method for {kind} is "
                            f"executable today - the switch would describe a video the "
                            f"factory cannot make. Land the implementation and flip "
                            f"executable_today first, exactly as CF-0041 did for rhythms")
            elif chosen not in available:
                errs.append(f"{kctx}: capture_method {chosen!r} is not executable today "
                            f"(executable: {available})")
            else:
                chain = capture_chain(inserts[kind], chosen)
                dead = [m for m in chain if m not in available]
                if not chain:
                    errs.append(f"{kctx}: capture_method {chosen!r} is not in "
                                f"capture_priority.order - a method outside the chain is "
                                f"never tried")
                elif dead:
                    errs.append(f"{kctx}: the chain from {chosen!r} falls back to {dead}, "
                                f"which is not executable today - a fallback that cannot "
                                f"run fails a block quietly")
        elif chosen is not None:
            errs.append(f"{kctx}: disabled, so capture_method must be null - a method "
                        f"named on a switched-off layer reads as a choice nobody made")
    return errs


def no_pipeline_reason(cfg, channel):
    """CF-0562: `shared/channel_ids.no_pipeline_reason` (loaded by path) - the
    «конвейера нет» line of a stub channel, None for a channel with a pipeline;
    ValueError for an unknown `status` or a half-stub."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "channel_ids_for_validate_inserts", REPO / "shared" / "channel_ids.py")
    ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ids)
    try:
        return ids.no_pipeline_reason(cfg, channel)
    except ids.ChannelIdError as e:
        raise ValueError(str(e)) from e


def channel_theme_errors(cfg, ctx="channel"):
    """CF-0572: the on-screen theme of a channel config (`theme`), by the one
    rule `shared/channel_data.theme_errors` holds (loaded by path). Every
    channel carries one - a stub too: its palette is the channel's brand,
    which exists before its pipeline does, and a missing one would leave the
    Video Editor nothing but another channel's palette to draw with."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "channel_data_for_validate_inserts", REPO / "shared" / "channel_data.py")
    data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data)
    if not isinstance(cfg, dict) or data.THEME_KEY not in cfg:
        return [f"{ctx}: no `{data.THEME_KEY}` - the on-screen palette is the "
                f"channel's (CF-0572, docs/channel-data.md «The theme»)"]
    return [f"{ctx}: {e}" for e in data.theme_errors(cfg[data.THEME_KEY])]


def channel_source_policy_errors(cfg, cfg_path):
    """CF-0557: the channel's outlets and feeds against the AI-bot rule
    (`shared/channel_data.policy_errors_of`, loaded by path): an outlet whose
    text is read is `allowed` by its robots.txt for Anthropic's bots; a
    forbidden one stands only as a headline feed or a citation (CF-0635); every
    tier-1 row says whether its terms were read (`terms_marker_errors`,
    CF-0810). Read from the config in
    hand and the fact-sources list beside it (`<dir>/<id>/fact-sources.json`)
    - every channel; a stub without lists has nothing to break."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "channel_data_policy_for_validate_inserts", REPO / "shared" / "channel_data.py")
    data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data)
    channel = cfg_path.stem
    lists = cfg_path.parent / channel / data.LISTS["fact-sources"][0]
    try:
        sources = json.loads(lists.read_text(encoding="utf-8")) if lists.is_file() else None
    except ValueError as e:
        return [f"{lists}{_UNPARSED}{e}"]
    return (data.policy_errors_of(channel, sources, data.feeds_of(cfg))
            + data.terms_marker_errors(channel, sources))


def channel_affiliate_errors(cfg, cfg_path):
    """CF-0593: the channel's affiliate-link slot - the `affiliate` block of
    the config and the programmes-and-links table beside it
    (`<dir>/<id>/affiliate.json`), by the one rule `shared/affiliate.py`
    holds (loaded by path). Every channel, a stub too: the slot is the
    channel's switch and the user's data, not a stage of its pipeline -
    ExampleTech carries it (off) before it has one. Absent = off, nothing
    to check."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "affiliate_for_validate_inserts", REPO / "shared" / "affiliate.py")
    aff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aff)
    return aff.channel_errors(cfg, cfg_path)


# --------------------------------------------------------------------------
# CC-0006: the checks of one channel config, named once
# --------------------------------------------------------------------------
# `validate_vocabulary()` below is the one place the root walks every channel
# config. The command center (api/, CC-0006) checks a config *before* it is
# written - one channel, a candidate that is not on disk yet - and shows a
# form whose every block says which check reads it. Both read this table, so
# the loop and the center cannot disagree about what is checked: a check added
# here is a check of both, and there is no second list of blocks in api/.
#
#     (block, check, on a stub too)
#
# `block` is the top-level key of channels/<id>.json the check reads (None:
# the config as a whole); `check` is the name of the function - of this file,
# or of patterns/validate_patterns.py for the `validate_*_block` ones. The
# order is the order the loop always ran them in. What a field *means* is not
# here: it is the config's own prose, `note` inside a block and `<key>_note`
# beside a key (CF-0191, `validate_patterns.VIDEO_EDITOR_NOTE_*`) - read by
# `channel_fields()`.
CHANNEL_CHECKS = (
    ("theme", "channel_theme_errors", True),                    # CF-0572
    ("sources", "channel_source_policy_errors", True),          # CF-0557 (+ fact-sources.json)
    ("status", "no_pipeline_reason", True),                     # CF-0562
    ("affiliate", "channel_affiliate_errors", True),            # CF-0593 (+ affiliate.json)
    ("insert_layers", "validate_channel_inserts", False),
    ("video_editor", "validate_video_editor_block", False),     # CF-0098
    ("blooper_rights_relaxation", "validate_blooper_relaxation_block", False),  # CF-0190
    ("production_fact_refusal", "validate_production_fact_refusal_block", False),  # CF-0185
    ("footage_indexer", "validate_footage_indexer_block", False),  # CF-0374
    ("content_researcher", "validate_content_researcher_block", False),  # CF-0411
    ("supplement", "validate_supplement_block", False),         # CF-0426
)


# --------------------------------------------------------------------------
# CF-0657: what each check means, in Russian, for the command center
# --------------------------------------------------------------------------
# The center shows a check's line to a person who works in Russian; the line
# itself stays English (journals, tests, `main()`'s print are unchanged). One
# row per check *name*, not per message: a check says dozens of different
# English things and a translation per message would be a second copy of every
# validator, out of date the day a message changes. Per check, the row is a
# stable `code`, the topic (`title`) and what is wrong in it (`reason`); the
# values of the line - the field, the outlet, the file, the value it got - are
# lifted out of the English line by `_line_values()` and put into the Russian
# one. A check with no row here cannot report at all (`check_findings` raises
# KeyError), and tests/test_check_reasons_ru.py holds the table against
# CHANNEL_CHECKS and VOCABULARY_CHECKS - a new check comes with its row.
#
#     check name -> (code, title, reason)
CONFIG_IS_OBJECT = "config_is_object"      # channel_config_findings: not a JSON object
FACT_SOURCES_PARSE = "fact_sources_parse"  # the channel's fact-sources.json does not parse
RUN_PLAN_CHECK = "run_plan.validate"       # the center's own row (api config_checks)
# CF-0672: the checks of a new channel and of a channel's position that are
# the factory's (shared/new_channel.py) and not one channel config's - the
# center takes their findings from `new_channel` instead of naming the line
# itself (CC-0054 left them without a code).
STANCE_PARSE_CHECK = "new_channel.stance_parse"      # the position's text is not JSON
STANCE_CHECK = "new_channel.stance_errors"           # the position is not an object of this channel
TEMPLATE_STUB_CHECK = "new_channel.starts_without_pipeline"  # the template made a channel with a pipeline
TEMPLATE_STANCE_PATH_CHECK = "new_channel.stance_path"       # the template's config names no position file it makes
NEW_CHANNEL_CHECKS = (STANCE_PARSE_CHECK, STANCE_CHECK, TEMPLATE_STUB_CHECK,
                      TEMPLATE_STANCE_PATH_CHECK)
CHECK_REASONS_RU = {
    CONFIG_IS_OBJECT: (
        "config_not_object", "Конфиг канала",
        "это не объект JSON - проверять в нём нечего"),
    FACT_SOURCES_PARSE: (
        "fact_sources_unreadable", "Список источников фактов",
        "файл не читается как JSON - источники канала не проверить"),
    "channel_theme_errors": (
        "theme_invalid", "Оформление канала",
        "цвета и шрифты заданы не по правилам - монтажёр рисует ролик этой палитрой"),
    "channel_source_policy_errors": (
        "source_policy", "Источники канала",
        "источник не проходит правило для ИИ-ботов - читать текст можно только там, "
        "где сайт это разрешает, остальное - заголовком или ссылкой"),
    "no_pipeline_reason": (
        "stub_invalid", "Статус канала",
        "статус неизвестен или канал без конвейера несёт то, чего у заглушки быть не должно"),
    "channel_affiliate_errors": (
        "affiliate_invalid", "Партнёрские ссылки",
        "переключатель, слова у ссылки или таблица программ заданы неверно - "
        "ссылку в описание ставить нельзя"),
    "validate_channel_inserts": (
        "insert_layers_invalid", "Слои вставок",
        "переключатель слоя задан неверно - нужно «включён или выключен» и причина"),
    "validate_video_editor_block": (
        "video_editor_invalid", "Настройки монтажёра",
        "значение не подходит монтажёру - с ним он не соберёт ролик"),
    "validate_blooper_relaxation_block": (
        "blooper_relaxation_invalid", "Послабление прав для ляпов",
        "переключатель или его границы заданы неверно"),
    "validate_production_fact_refusal_block": (
        "production_fact_refusal_invalid", "Отказ от темы без факта",
        "правило задано неверно - сценарист не поймёт, когда снимать тему"),
    "validate_footage_indexer_block": (
        "footage_indexer_invalid", "Настройки индексатора футажа",
        "значение не подходит индексатору - он его не прочтёт"),
    "validate_content_researcher_block": (
        "content_researcher_invalid", "Настройки сценариста",
        "значение не подходит сценаристу - он его не прочтёт"),
    "validate_supplement_block": (
        "supplement_invalid", "Добор материала",
        "значение не подходит шагу добора - нужен потолок времени в секундах"),
    "validate_insert": (
        "insert_invalid", "Описание слоя вставок",
        "описание слоя не проходит проверку - слой не сработает"),
    "validate_pattern_layer_fields": (
        "pattern_layer_invalid", "Паттерн",
        "паттерн не ответил, допускает ли он этот слой вставок, или не объяснил почему"),
    RUN_PLAN_CHECK: (
        "run_plan_invalid", "План запуска",
        "план стадий канала задан неверно - батч по нему не запустится"),
    STANCE_PARSE_CHECK: (
        "stance_unreadable", "Позиция канала",
        "текст позиции не читается как JSON - фабрика его не прочтёт"),
    STANCE_CHECK: (
        "stance_invalid", "Позиция канала",
        "позиция должна быть объектом JSON с id этого канала"),
    TEMPLATE_STUB_CHECK: (
        "template_has_pipeline", "Шаблон нового канала",
        "шаблон дал канал с конвейером - новый канал начинается без него"),
    TEMPLATE_STANCE_PATH_CHECK: (
        "template_stance_path", "Шаблон нового канала",
        "конфиг шаблона не указывает на файл позиции, который шаблон создаёт - "
        "позицию некуда записать"),
}
# The checks `validate_vocabulary()` runs beyond one channel's config: every
# insert file before the channels, the patterns' layer fields after them.
VOCABULARY_CHECKS = ("validate_insert",) + tuple(c for _, c, _ in CHANNEL_CHECKS) + (
    "validate_pattern_layer_fields",)

_UNPARSED = ": does not parse: "
_RE_FILE_PATH = re.compile(r"^(?:[^\s:]*/)?([\w.-]+?\.json)\.([^\s:]+):")
_RE_FILE = re.compile(r"^(?:[^\s:]*/)?([\w-]+/[\w.-]+\.json|[\w.-]+\.json):")
_RE_FEED = re.compile(r"^\S+ sources\.rss\.feeds\[([^\]]+)\]:")
_RE_TIER = re.compile(r"^\S+ fact-sources tiers\.[\w-]+\[([^\]]+)\]:")
_RE_INSERT = re.compile(r"^insert (\S+):")
_RE_BARE_PATH = re.compile(r"^([A-Za-z_][\w-]*(?:(?:\.[\w-]+)|\[[^\]\s]+\])*):\s")
_RE_TICK = re.compile(r"`([^`]+)`")
_RE_GOT = re.compile(r"\bgot (.+?)(?:[.,;)]?(?:\s|$))")
_RE_IS_NOT = re.compile(r"` is (.+?), not ")
_RE_UNKNOWN = re.compile(r"\bunknown `[^`]+` (\S+)")


def _line_values(line, ctx=None):
    """(place, value) the Russian line names: where - `поле video_editor.x`,
    `лента vulture.com`, `слой proof`, `patterns/x.json, поле meme_layer`, a
    file - and the value the English line says it got; either may be None."""
    place = value = None
    m = _RE_FILE_PATH.match(line)
    if m:
        file, path = m.groups()
        place = f"поле {path}" if file == ctx else f"файл {file}, поле {path}"
    elif _RE_FEED.match(line):
        place = f"лента {_RE_FEED.match(line).group(1)}"
    elif _RE_TIER.match(line):
        place = f"источник {_RE_TIER.match(line).group(1)}"
    elif _RE_INSERT.match(line):
        place = f"слой {_RE_INSERT.match(line).group(1)}"
    elif _RE_BARE_PATH.match(line) and not _RE_FILE.match(line):
        place = f"поле {_RE_BARE_PATH.match(line).group(1)}"
    else:
        tick = _RE_TICK.search(line)
        if tick:
            place = f"поле {tick.group(1)}"
        elif _UNPARSED in line:
            head = line.split(_UNPARSED, 1)[0]
            place = f"файл {'/'.join(Path(head).parts[-2:])}"
    for rx in (_RE_GOT, _RE_IS_NOT, _RE_UNKNOWN):
        m = rx.search(line)
        if m:
            value = "пусто" if m.group(1) == "None" else m.group(1)
            break
    return place, value


def check_finding(check, line, ctx=None):
    """CF-0657: one line of `check` as the center shows it -
    {"check", "code", "text" (the English line, unchanged), "text_ru"}.
    KeyError for a check with no row in CHECK_REASONS_RU."""
    code, title, reason = CHECK_REASONS_RU[check]
    place, value = _line_values(line, ctx)
    head = title + (f", {place}" if place else "") + (f" (сейчас {value})" if value else "")
    return {"check": check, "code": code, "text": line, "text_ru": f"{head}: {reason}."}


def check_findings(check, lines, ctx=None):
    """`check_finding` over every line one check returned."""
    CHECK_REASONS_RU[check]  # a check without its Russian row fails even when clean
    return [check_finding(check, line, ctx) for line in lines]


def _channel_check(name):
    if name in globals():
        return globals()[name]
    import validate_patterns  # noqa: E402 - sys.path set above
    return getattr(validate_patterns, name)


def channel_config_errors(cfg, cfg_path, inserts=None):
    """CC-0006: every error of one channel config by `CHANNEL_CHECKS` ([] when
    valid) - the body of `validate_vocabulary()`'s loop. `cfg` is the parsed
    config (a candidate need not be on disk); `cfg_path` is where it lives or
    would, `<dir>/<id>.json` - the channel's lists are read beside it."""
    return [f["text"] for f in channel_config_findings(cfg, cfg_path, inserts)]


def channel_config_findings(cfg, cfg_path, inserts=None):
    """CF-0657: `channel_config_errors` with each line's check, code and
    Russian text (`check_finding`) - the same lines, in the same order."""
    cfg_path = Path(cfg_path)
    inserts = inserts if inserts is not None else load_inserts()
    ctx = cfg_path.name
    if not isinstance(cfg, dict):
        return check_findings(CONFIG_IS_OBJECT, [f"{ctx}: is not a JSON object"], ctx)
    out = []
    stub = False
    for block, check, on_stub in CHANNEL_CHECKS:
        if stub and not on_stub:
            continue
        if on_stub:
            if check == "no_pipeline_reason":
                # CF-0562: a channel with no pipeline yet has no blocks to
                # check - its config is checked as a stub (status, no
                # run_plan/publisher, out of the schedule) and by the rows
                # that hold on a stub too, nothing else; a half-stub is an
                # error here.
                try:
                    stub = bool(no_pipeline_reason(cfg, cfg_path.stem))
                except ValueError as e:
                    return out + check_findings(check, [str(e)], ctx)
            elif check == "channel_source_policy_errors":
                out += [check_finding(FACT_SOURCES_PARSE if _UNPARSED in e else check, e, ctx)
                        for e in channel_source_policy_errors(cfg, cfg_path)]
            elif check == "channel_affiliate_errors":
                out += check_findings(check, channel_affiliate_errors(cfg, cfg_path), ctx)
            else:
                out += check_findings(check, _channel_check(check)(cfg, ctx=ctx), ctx)
        elif check == "validate_channel_inserts":
            out += check_findings(check, validate_channel_inserts(cfg, inserts, ctx=ctx), ctx)
        else:
            out += check_findings(check, _channel_check(check)(cfg, ctx=ctx), ctx)
    return out


def _json_kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def channel_fields(cfg):
    """CC-0006: the fields of one channel config, for a form - one row per
    key, objects walked, an array is one field:

        {"path": ["video_editor", "max_attempts_per_video"], "kind": "number",
         "prose": False, "note": "<its `max_attempts_per_video_note`>" | None,
         "checked_by": ["validate_video_editor_block"]}

    `note` is the field's own prose - `<key>_note` beside it, or `note`
    inside it for an object; a block's `note` is on the block's row, not
    repeated on its children. `prose` marks a string `note` / `*_note` key
    itself (text for a human, read by no stage); `checked_by` is the check of its top-level block in
    `CHANNEL_CHECKS` ([] when nothing but the stage that reads it checks it).
    Nothing here is a schema: it is the config described by its own prose."""
    from validate_patterns import (  # noqa: E402 - sys.path set above
        VIDEO_EDITOR_NOTE_KEY as NOTE, VIDEO_EDITOR_NOTE_SUFFIX as SUFFIX)
    checks = {}
    for block, check, _ in CHANNEL_CHECKS:
        checks.setdefault(block, []).append(check)
    rows = []

    def walk(node, path):
        for key, value in node.items():
            here = path + [key]
            prose = isinstance(value, str) and (key == NOTE or key.endswith(SUFFIX))
            note = node.get(f"{key}{SUFFIX}")
            if not isinstance(note, str) and isinstance(value, dict):
                note = value.get(NOTE)
            rows.append({"path": here, "kind": _json_kind(value), "prose": prose,
                         "note": note if isinstance(note, str) and not prose else None,
                         "checked_by": list(checks.get(here[0], []))})
            if isinstance(value, dict):
                walk(value, here)

    if isinstance(cfg, dict):
        walk(cfg, [])
    return rows


def validate_vocabulary():
    """Validate every insert file, and every channel's switches over them."""
    return [f["text"] for f in vocabulary_findings()]


def vocabulary_findings():
    """CF-0657: `validate_vocabulary()`'s lines with each one's check, code and
    Russian text (`check_finding`) - the same lines, in the same order."""
    errs = []
    inserts = {}
    for path in insert_files():
        insert = json.loads(path.read_text())
        inserts[path.stem] = insert
        errs += check_findings("validate_insert", validate_insert(insert, stem=path.stem))
    from validate_patterns import load_patterns  # noqa: E402 - sys.path set above
    # Every channel config by the one table of its checks (CHANNEL_CHECKS,
    # CC-0006): the theme and the AI-bot rule on every channel, a stub
    # included, then the blocks of a channel with a pipeline - each check's
    # reason is beside its row there.
    for cfg_path in sorted(CHANNELS_DIR.glob("*.json")):
        cfg = json.loads(cfg_path.read_text())
        errs += channel_config_findings(cfg, cfg_path, inserts)
    errs += check_findings("validate_pattern_layer_fields",
                           validate_pattern_layer_fields(load_patterns(), inserts))
    return errs


def channel_asset_reminder_lines():
    """CF-0154: the standing reminder about the two files a channel's owner
    brings - the ending clip (CF-0141) and the ambient bed (CF-0153).

    It is printed here because `validate_vocabulary()` above holds the one
    loop in the root that walks every channel config, and a channel config has
    to pass this validator to be legal at all - so a channel added from
    scratch meets the reminder by construction. There is no channel-creation
    script to put it in: CF-0016 creates the channel on YouTube, not the
    directory here, and `channels/example-film/` was assembled by hand.
    The alternatives that were weighed are in tasks/CF-0154-*.md.

    A *report*, not a verdict: these lines carry no errors, are not part of
    `validate_vocabulary()`, and never move `main()`'s exit code. Both files
    are optional and both degrade to a floor the factory owns; a reminder that
    read as a failure would be a lie about what happens without them.
    """
    from validate_patterns import (  # noqa: E402 - sys.path set above
        CHANNEL_ASSET_REMINDER_HEADING, channel_asset_reminder)
    lines = [CHANNEL_ASSET_REMINDER_HEADING]
    for cfg_path in sorted(CHANNELS_DIR.glob("*.json")):
        cfg = json.loads(cfg_path.read_text())
        cid = cfg.get("channel_id") or cfg_path.stem
        try:
            stub = no_pipeline_reason(cfg, cfg_path.stem)
        except ValueError as e:
            stub = f"config error: {e}"
        if stub:
            lines.append(f"  {cid}: {stub} - its files are asked for when it gets one")
            continue
        lines += channel_asset_reminder(cfg, cid)
    return lines


def main():
    errs = validate_vocabulary()
    inserts = load_inserts()
    print(f"inserts/: {len(inserts)} insert layer(s)")
    for kind, insert in sorted(inserts.items()):
        if is_library_kind(kind):
            layer = LIBRARY_BLOCK_LAYERS[kind]
            state = (f"executable today (implemented by {layer['implemented_by']})"
                     if layer["executable_today"]
                     else f"not executable today (blocked by {layer['blocked_by']})")
            print(f"  {kind:<8} library {layer['index']}, {state}")
            continue
        available = executable_methods(insert)
        print(f"  {kind:<8} {len(insert['capture_methods'])} capture method(s), "
              f"executable today: {available or 'none'}, accepted: "
              f"{accepted_methods(insert) or 'none'}, rejected: "
              f"{rejected_methods(insert) or 'none'}")
    owed = missing_kinds()
    if owed:
        for kind, task in sorted(owed.items()):
            print(f"  {kind:<8} not described yet - owed to {task}")
    questions = open_questions(inserts)
    if questions:
        print(f"  {len(questions)} capture method(s) awaiting a decision: "
              + ", ".join(f"{k}/{m}" for k, m, _ in questions))
    print()
    for line in channel_asset_reminder_lines():
        print(line)
    if errs:
        print(f"\n{len(errs)} error(s):")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("\nvocabulary valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
