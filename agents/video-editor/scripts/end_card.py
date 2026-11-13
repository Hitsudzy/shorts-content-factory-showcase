#!/usr/bin/env python3
"""CF-0117 / CF-0141: how a video of this channel ends.

**CF-0141 changed what that is.** The ending is a finished mp4 the channel
brings with it - `channels/<channel_id>/ending.mp4`, or wherever
`video_editor.ending.path` points - generated and approved by the user
outside the factory and identical in every video of the channel. Everything
below about the drawn card is still true and still ships, but only for a
channel that has no such file: the chain is `clip -> logo -> typographic`,
and the two drawn variants are the floor. See the CF-0141 block further down
for the clip's own rules (its length is a config constant, its format is
checked and never converted, its sound is its own).

CF-0117: the end card - the channel's logo and its signature phrase, after
the last word of the narration.

Item 2 and 4 of the former CF-0065. The card is the one frame that is the
same in every video of a channel: `stance.json`'s own reason for it is that
"it reads as the channel's position precisely because it never changes"
(`signature_phrase.placement`). So nothing here writes words - it reads them.

**The phrase, and CF-0186: there may be none.** `channels/<channel>.json`
names its stance document in the `stance` field, relative to `channels/`
(CF-0063). The text is `signature_phrase.text` in that document. It is never
defaulted and never hard-coded - a card with a phrase this file invented
would be the channel saying something nobody decided, and the one guarantee
CF-0063 asks of every consumer is that the phrase has exactly one source.
`text_source` records which file and field it came from, so the batch record
can be checked against the stance rather than trusted.

What changed with CF-0186 is what happens when that field is not there.
A stance document with no `signature_phrase` used to raise `EndCardError`
and the plan was not written. It is now a state the card is planned in: the
channel signs with its logo, or with its own name, and the card is drawn
without a phrase. example-film is the channel that made this real - CF-0181
removed its phrase outright, because the slogans its ending clip already
carries drawn into it (MOVIES · TV · FACTS, NEW SHORTS EVERY DAY) say what a
second slate set in code would have said. A stance document that is *named
and missing* is still a refusal: that is a broken channel, not a channel
without a phrase.

With no phrase, no logo and no channel name there is nothing left to draw
and no card is planned at all (`plan_end_card()` returns None); the seconds
go back to the narration.

**The seconds.** `narration_budget.end_card_seconds` in the channel config
(CF-0087), 3 s today. The card comes *out of* `target_total_seconds`, not on
top of it - the same constant `narration_length.judge()` already reserves at
the TTS gate, which is why nothing here re-derives it. Missing constant,
same answer as a missing phrase: `EndCardError`.

**Where it starts.** At the end of the voice-over - `plan["audio"]
["duration"]`, which is also the last block's end (build_render_plan.py runs
the last block to the end of the audio so the picture never dies before the
voice does). That is the number CF-0087's budget means: `narration_length.
judge()` measures the whole wav, lead silence and trailing breath included,
and adds `end_card_seconds` to it for the total. The last *word* ends a
fraction earlier; using it would open a hole between the last word and the
card that the arithmetic never budgeted. The word timings are the fallback
for a plan with no audio record, and the last block's end the one before.

**The logo.** `channels/<channel_id>/logo.<ext>` - the channel's own
directory, beside the stance document it already keeps there (png, svg, jpg,
jpeg, webp, in that order); `video_editor.end_card.logo` in the channel
config overrides the convention with any path. No file -> `variant:
"typographic"`, the phrase large with the channel name under it, or - since
CF-0186 - the channel's name alone when there is no phrase either. That is
the same floor as the `typographic` style: a card that depends on no asset
cannot fail for want of one, and the end of a video is the last place to
discover a missing file. example-film has no logo today (branding is
Publisher's job, CF-0016), and closes on its own clip anyway.

Usage:
    end_card.py <plan.json> --channel <id|path.json> [--root <factory root>]
        [--write]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import meme_layer
import rhythm  # CF-0315: block_count_parameter() / KNOWN_BAND_MODES - one reader
              # of the shape a pattern states its block envelope in
from common import probe_json
from _channel_data import channel_data  # CF-0722: the ending section of brand.json
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

PLAN_FIELD = "end_card"
DELIVERED_FIELD = "end_card_delivered"
ENDING_DELIVERED_FIELD = "ending_delivered"

VARIANT_CLIP = "clip"
VARIANT_LOGO = "logo"
VARIANT_TYPOGRAPHIC = "typographic"

# The stance field the phrase lives in (CF-0063). One dotted path, used both
# to read the text and to name it in `text_source`.
PHRASE_PATH = ("signature_phrase", "text")

# The channel constant the card's length is (CF-0087).
SECONDS_PATH = ("narration_budget", "end_card_seconds")

# CF-0141: the same constant for the *ending clip* - the finished mp4 the
# channel brings with it. Two names rather than one because they are not the
# same decision: `end_card_seconds` is how long a card this repo draws is
# held, `ending_seconds` is how long somebody else's finished file runs, and a
# channel that keeps both (one for the clip, one for the floor it would fall
# back to) must be able to say both numbers.
ENDING_SECONDS_PATH = ("narration_budget", "ending_seconds")

# Where the channel's ending clip lives by convention: its own directory, the
# one that already holds `stance.json` and (CF-0117) `logo.png`.
# `video_editor.ending.path` overrides it, exactly as `video_editor.end_card
# .logo` overrides the logo.
ENDING_NAME = "ending.mp4"

# The logo's file names under channels/<channel_id>/, in the order they are
# tried. Raster first: the card is rendered by a browser, which reads all of
# these, and png is what a channel asset is delivered as in practice.
LOGO_NAMES = ("logo.png", "logo.svg", "logo.jpg", "logo.jpeg", "logo.webp")

# The delivered record's keys, in the order write_batch_metadata.py writes
# them. Kept here so the metadata cannot drift from the plan.
DELIVERED_KEYS = ("seconds", "start_s", "text", "text_source", "variant", "logo_path")

# CF-0141 (section H): what the ending clip leaves on the batch record. Four
# keys, on the same promise as the six above - always all of them, `null` in
# each on a video that did not close on a clip, so absence never has to be
# interpreted. `source` is how the file was found: the channel's config named
# it, or the convention did.
ENDING_DELIVERED_KEYS = ("path", "seconds", "source", "variant")

ENDING_SOURCE_CONFIG = "config"        # video_editor.ending.path
ENDING_SOURCE_CONVENTION = "convention"  # channels/<channel_id>/ending.mp4


class EndCardError(Exception):
    """The card cannot be planned from what the channel says. Loud on
    purpose: every other layer in this repo degrades to a note, because a
    missing insert costs a video one insert. A named-and-missing stance
    document, or a missing length constant, costs the channel its position,
    and there is no honest fallback for either - inventing one is exactly
    what CF-0063 forbids.

    CF-0186 took one case off this list: a stance document that carries no
    `signature_phrase` is no longer an error. A channel may sign with
    nothing, and a card without a phrase is a card, not a failure."""

    def __init__(self, *args, code=None):
        # CF-0722: a refusal may name itself (`ending_sha256_mismatch`,
        # `ending_invalid`); the message is unchanged for every other one.
        super().__init__(*args)
        self.code = code


# --------------------------------------------------------------------------
# what the channel says
# --------------------------------------------------------------------------

def stance_path(channel_cfg, root, channel=None):
    """The stance document's path, or None when the config names none.

    `stance` is relative to `channels/` (CF-0063's `stance_note`: it sits in
    a subdirectory on purpose, so that anything globbing `channels/*.json`
    does not read it as a channel config). An absolute value is taken as
    given, which is what a test config in a temp directory needs.
    """
    rel = (channel_cfg or {}).get("stance")
    if not isinstance(rel, str) or not rel.strip():
        return None
    p = Path(rel.strip())
    if p.is_absolute():
        return p
    # A channel config read from a path of its own (a temp config in a test)
    # keeps its stance beside itself; one read from the factory root resolves
    # under <root>/channels/.
    base = Path(channel).resolve().parent if channel and str(channel).endswith(".json") \
        else Path(root) / "channels"
    return base / p


def load_stance(channel_cfg, root, channel=None):
    """The stance document as a dict. Raises rather than returning None: a
    channel that names a stance file and does not have one is a broken
    channel, not a channel without a card."""
    path = stance_path(channel_cfg, root, channel)
    if path is None:
        raise EndCardError(
            "the channel config names no `stance` document - the end card's phrase "
            "has one source (CF-0063) and this channel does not point at it")
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise EndCardError(f"the stance document {path} cannot be read ({e}) - "
                           f"the end card's phrase is not written anywhere else") from e
    if not isinstance(data, dict):
        raise EndCardError(f"the stance document {path} is not an object")
    data = dict(data)
    data["_path"] = str(path)
    return data


def _relative(path, root):
    """`channels/example-film/stance.json` rather than the machine's own
    absolute path, when the file is under the factory root - `text_source` is
    read by a human checking the card against the stance, and the batch
    record travels."""
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return str(path)


def signature_phrase(stance, source_label=None):
    """(text, text_source), or (None, None) when the channel has no phrase.

    `text_source` is `<path>#signature_phrase.text`, the path relative to the
    factory root when it is under it. It is written into the plan and the
    batch record so a reader can check the phrase against its source instead
    of taking the card's word for it.

    **CF-0186: absence is a state, not a fault.** This used to raise
    `EndCardError` on a stance document with no `signature_phrase.text`, on
    the ground that a channel which says it has a position must be able to
    produce it. That ground went with CF-0181: a channel may decide it signs
    with nothing, and example-film is the first one that did - its ending clip
    already carries the channel's slogans drawn into it, and a second slogan
    set in code right before it is the same thing said twice. So a missing
    phrase now returns None and the card is planned without it
    (plan_end_card()); what is still refused is a channel that *names* a
    stance document it does not have, which is a broken channel and not a
    channel without a phrase - see load_stance().

    Nothing is defaulted and nothing is invented, which was the real
    obligation CF-0063 laid down: the phrase has exactly one source, and a
    channel with no phrase gets no phrase rather than one this file made up.
    """
    node = stance if isinstance(stance, dict) else {}
    for key in PHRASE_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    text = node.strip() if isinstance(node, str) else ""
    if not text:
        return None, None
    path = source_label or (stance or {}).get("_path") or "<stance>"
    return text, f"{path}#{'.'.join(PHRASE_PATH)}"


def card_seconds(channel_cfg):
    """`narration_budget.end_card_seconds` (CF-0087). No default: the number
    is a decision recorded in the channel config, and a card of some other
    length would silently break the budget the narration was written to."""
    node = channel_cfg if isinstance(channel_cfg, dict) else {}
    for key in SECONDS_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    try:
        seconds = float(node)
    except (TypeError, ValueError):
        raise EndCardError(
            f"the channel config carries no {'.'.join(SECONDS_PATH)} - the card's "
            f"length is the CF-0087 constant and is not guessed here") from None
    if seconds <= 0:
        raise EndCardError(f"{'.'.join(SECONDS_PATH)} is {seconds} - a card of no "
                           f"length is not a card")
    return seconds


def logo_path(channel_cfg, root, channel=None):
    """The channel's logo file, or None.

    Convention: `channels/<channel_id>/logo.png` (or .svg/.jpg/.jpeg/.webp) -
    the channel's own directory, the one that already holds its stance
    document. `video_editor.end_card.logo` overrides it with any path,
    resolved against the factory root when it is relative.
    """
    ve = (channel_cfg or {}).get("video_editor") or {}
    override = (ve.get("end_card") or {}).get("logo") if isinstance(ve, dict) else None
    if isinstance(override, str) and override.strip():
        p = Path(override.strip())
        if not p.is_absolute():
            p = Path(root) / p
        return p if p.exists() else None
    channel_id = (channel_cfg or {}).get("channel_id")
    if not channel_id:
        return None
    base = Path(channel).resolve().parent if channel and str(channel).endswith(".json") \
        else Path(root) / "channels"
    for name in LOGO_NAMES:
        cand = base / str(channel_id) / name
        if cand.exists():
            return cand
    return None


# --------------------------------------------------------------------------
# CF-0141: the ending clip - the finished mp4 the channel brings with it
# --------------------------------------------------------------------------
#
# The end of a video of this channel is not a frame this repo draws. It is a
# file the user generated elsewhere, approved, and put in the channel's
# directory; every video of the channel ends on it. The card below it stays in
# the code as the floor - what a channel *without* a file gets - so the chain
# is clip -> logo -> typographic.
#
# Three things about it are decisions and not measurements, and each is
# checked here rather than discovered at render time:
#
#   * **its length is a written number.** `narration_budget.ending_seconds` in
#     the channel config, verified against the file. Not read off the file
#     alone, because Content Researcher's check_narration_budget.py compresses
#     the script against that number long before this repo sees the file: if
#     the length only exists on disk, the script was already written to the
#     wrong budget. Swapping the file for a longer one is therefore a config
#     edit, not a file swap - which is right, because it shortens the script
#     of every future video of the channel.
#   * **its format is the composition's.** 1080x1920 at the composition's fps
#     (decision 5 of 2026-09-08). Checked, never converted: a mismatch is a
#     misconfigured channel, and normalising it here would hide the fault in
#     a re-encode nobody asked for.
#   * **it carries its own sound.** Decision 2: the clip's track is what is
#     heard over it, and the bed is faded to silence under it rather than
#     mixed beneath. A clip with no audio stream would therefore play silent
#     over an interval the render gate deliberately does not measure, so the
#     missing track is caught here or not at all.


def ending_path(channel_cfg, root, channel=None):
    """(path, source) for the channel's ending clip, or (None, None).

    `video_editor.ending.path` first - the config's own answer, resolved
    against the factory root when relative, and *not* silently dropped when it
    points at nothing: a channel that names a file and does not have one is a
    broken channel, exactly as with the stance document. Then the convention
    `channels/<channel_id>/ending.mp4`. No file by either route is not an
    error - it is the channel that falls back to the drawn card.
    """
    ve = (channel_cfg or {}).get("video_editor") or {}
    named = (ve.get("ending") or {}).get("path") if isinstance(ve, dict) else None
    if isinstance(named, str) and named.strip():
        p = Path(named.strip())
        if not p.is_absolute():
            p = Path(root) / p
        if not p.exists():
            raise EndCardError(
                f"the channel config names video_editor.ending.path {named!r} and "
                f"there is no file at {p} - a channel that says it closes on a clip "
                f"and cannot produce it is not a channel without an ending, and the "
                f"drawn card is not quietly substituted for the file the channel named")
        return p, ENDING_SOURCE_CONFIG
    channel_id = (channel_cfg or {}).get("channel_id")
    if not channel_id:
        return None, None
    base = Path(channel).resolve().parent if channel and str(channel).endswith(".json") \
        else Path(root) / "channels"
    cand = base / str(channel_id) / ENDING_NAME
    return (cand, ENDING_SOURCE_CONVENTION) if cand.exists() else (None, None)


# CF-0722: the clip's bytes are the channel's data too. `channels/<id>/
# brand.json` -> `ending.clip_sha256` (the root's shared/channel_data.py,
# `ending()`) records them; a clip that is not those bytes - re-rendered,
# swapped, a copy of another channel's - is refused by name before it is
# probed, and the plan is not written. A channel without brand.json or
# without the section is not checked (the old behaviour), so the plan of every
# channel whose clip is the recorded one is the same, byte for byte.
ENDING_SHA256_MISMATCH = "ending_sha256_mismatch"
ENDING_INVALID = "ending_invalid"


def check_ending_bytes(clip, channel_cfg, root):
    """The clip's sha256 when the channel records one and it matches; None
    when the channel records none. Raises EndCardError (`code`
    ENDING_SHA256_MISMATCH, or the section's own ENDING_INVALID) otherwise."""
    cid = (channel_cfg or {}).get("channel_id")
    if not cid:
        return None
    try:
        section = channel_data.ending(cid, root)
    except channel_data.ChannelDataError as e:
        code = getattr(e, "code", None)
        if code is None:
            # not a channel of this root (a config handed in by path) - it has
            # no brand data here to check against
            return None
        raise EndCardError(f"{code}: {e}", code=code) from e
    if not section or not section.get("clip_sha256"):
        return None
    want = section["clip_sha256"]
    got = channel_data.file_sha256(clip)
    if got != want:
        raise EndCardError(
            f"{ENDING_SHA256_MISMATCH}: the ending clip {clip} is not the file the "
            f"channel recorded - sha256 {got}, channels/{cid}/brand.json "
            f"ending.clip_sha256 says {want}. A swapped clip is refused, not shipped; "
            f"if the new clip is meant, record its sha256 there (and in the "
            f"channel's SOURCES.md)", code=ENDING_SHA256_MISMATCH)
    return got


def ending_seconds(channel_cfg):
    """`narration_budget.ending_seconds`, or None when the channel records
    none. None is not an error here: only a channel that *has* a clip owes the
    constant, and plan_ending() is what asks for it."""
    node = channel_cfg if isinstance(channel_cfg, dict) else {}
    for key in ENDING_SECONDS_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    try:
        seconds = float(node)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def probe_ending(path):
    """{seconds, width, height, fps, has_audio} for the clip.

    `fps` off `r_frame_rate` ("24/1"), which is the stream's nominal rate -
    the one a mismatch with the composition is a mismatch in. A file ffprobe
    cannot read at all raises, rather than answering zeros that would then be
    compared against the composition and reported as a format fault.
    """
    try:
        info = probe_json(path)
    except Exception as e:  # noqa: BLE001 - any probe failure is the same answer
        raise EndCardError(f"the ending clip {path} cannot be probed ({e})") from e
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise EndCardError(f"the ending clip {path} carries no video stream")
    rate = str(video.get("r_frame_rate") or "0/1")
    try:
        num, _, den = rate.partition("/")
        fps = float(num) / float(den or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        seconds = float(video.get("duration") or (info.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        raise EndCardError(f"the ending clip {path} reports no duration") from None
    return {
        "seconds": round(seconds, 6),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(fps, 6),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def composition_format(plan):
    """(width, height, fps) the composition renders at - `plan["output"]`,
    written by build_render_plan.py from its own --width/--height/--fps. A
    plan that carries none cannot have its clip checked against anything, and
    saying so is the honest answer; the caller turns that into a refusal."""
    out = (plan or {}).get("output")
    if not isinstance(out, dict):
        return None
    try:
        return int(out["width"]), int(out["height"]), float(out["fps"])
    except (KeyError, TypeError, ValueError):
        return None


def check_ending(probe, declared, plan, path):
    """Raise EndCardError unless the file is the one the channel says it is.

    Two separate checks, and they fail for different reasons:

      * **length against the config.** More than one frame of the composition
        apart and the plan is not written. The tolerance is a frame because
        that is the resolution the composition has; anything coarser lets the
        budget the script was written to drift away from the file.
      * **format against the composition.** Frame size and rate, decision 5.
        Not converted - a clip at 24 fps in a 30 fps composition duplicates
        every fifth frame unevenly, and that is a file to re-render, not a
        render stage to add.
    """
    fmt = composition_format(plan)
    if fmt is None:
        raise EndCardError(
            f"the plan carries no `output` block, so the ending clip {path} cannot "
            f"be checked against the composition it would play in")
    width, height, fps = fmt
    if declared is None:
        raise EndCardError(
            f"the channel closes on {path} and records no "
            f"{'.'.join(ENDING_SECONDS_PATH)} - the clip's length is the number the "
            f"script's word budget was written against (CF-0087) and is not read off "
            f"the file here")
    tolerance = 1.0 / fps if fps > 0 else 1.0 / 30.0
    if abs(probe["seconds"] - declared) > tolerance:
        raise EndCardError(
            f"{'.'.join(ENDING_SECONDS_PATH)} says {declared:.3f}s and {path} runs "
            f"{probe['seconds']:.3f}s - {abs(probe['seconds'] - declared):.3f}s apart, "
            f"over one frame ({tolerance:.3f}s). The narration of every video of this "
            f"channel was written to the config's number; fix the config or the file, "
            f"but they may not disagree")
    faults = []
    if (probe["width"], probe["height"]) != (width, height):
        faults.append(f"{probe['width']}x{probe['height']} against the composition's "
                      f"{width}x{height}")
    if abs(probe["fps"] - fps) > 1e-6:
        faults.append(f"{probe['fps']:g} fps against the composition's {fps:g}")
    if not probe["has_audio"]:
        faults.append("no audio stream - the clip's own track is what is heard over "
                      "it (decision 2) and the bed is faded to silence under it, so a "
                      "clip without one plays as dead air")
    if faults:
        raise EndCardError(
            f"the ending clip {path} is not the composition's format: "
            + "; ".join(faults)
            + ". This is a channel-setup fault, not a render step: nothing here "
              "converts the file (decision 5 of 2026-09-08). Re-render the clip to "
              f"{width}x{height} at {fps:g} fps and re-check "
              f"{'.'.join(ENDING_SECONDS_PATH)}, which a change of frame rate can "
              "move by a frame")


# --------------------------------------------------------------------------
# CF-0141 (section C): how long an ending the channel can afford
# --------------------------------------------------------------------------
#
# The ending comes out of `target_total_seconds`, so every second of it is a
# second the narration does not get. Two different limits bound that, and
# only one of them exists in this project.
#
# **The structural ceiling** is machine-derivable and is derived here, not
# typed in. `patterns/validate_patterns.py` already owns the arithmetic for
# "the shortest narration this pattern can physically be built in":
# `key_frame_hold_seconds.max + (block_count.min - 1) * MIN_BLOCK_SECONDS`,
# its feasibility check. The most demanding pattern the channel admits sets
# the floor under the narration, and `target_total_seconds` minus that floor
# is the longest ending the channel can afford. On example-film that was
# 40.40 s (explainer, 8.0 + 11 x 0.6 = 14.60 s of narration, against a 55 s
# target) while explainer stated its envelope as a count; the other three
# admitted patterns ask for less (moment-breakdown 12.00, contrast 10.10,
# list 9.10). Since CF-0310 explainer states a *pace* instead, it asks 9.20 s,
# moment-breakdown binds, and the ceiling is 43.00 s - see CF-0315 below.
#
# MIN_BLOCK_SECONDS is imported rather than copied, and from the validator
# rather than from this repo's rhythm.py - which has a constant of the same
# name with a *different* value (1.6, and it means something else: the
# spacing below which an anchor is too tight to read, not a floor on block
# length; the shortest block the pipeline has actually produced is the 0.60 s
# the validator records). Reading rhythm.py's number here would give 29.40 s
# and would be the wrong answer to this question.
#
# **The editorial limit** - the length of narration below which the video has
# nothing left to say - does not exist in this repository in any form, and is
# not invented here. See `EDITORIAL_LIMIT_NOTE`.
#
# --------------------------------------------------------------------------
# CF-0315 (2026-09-22): the binding pattern may state a *pace*
# --------------------------------------------------------------------------
#
# Since CF-0310 `explainer` carries `block_rate_per_minute` (15.39-47.88,
# `mode: floor_drawn` since CF-0314) and no `block_count` at all. The formula
# above read `block_count.min` inside a `try` whose `except KeyError: continue`
# dropped the pattern without a word, so the ceiling on example-film quietly
# became moment-breakdown's while every comment and test here still said
# 40.40 s, and the most demanding pattern the channel admits stopped being
# consulted about the length of its own ending.
#
# A pace states no count until a length is chosen, and choosing one here is
# exactly the length-dependence CF-0310 took *out* of the envelope. The root
# says so where it refuses to run the same feasibility check on a rate: "Both
# checks are about a count of blocks having to fit in a video, so they are
# skipped for a rate, which carries no count until a length is chosen - and
# choosing one here would be the length-dependence CF-0310 removed, put back
# by the validator" (`patterns/validate_patterns.py`). So no length is
# imported here either - not the channel's 30 s hard floor (CF-0293), not the
# 45-60 s band. The formula is solved for its own fixed point instead, out of
# the pattern's parameters and nothing else:
#
#     the narration has to hold n blocks   L >= hold.max + (n - 1) * MIN_BLOCK
#     the pace floor demands them          n >= rate.min * L / 60, i.e.
#                                          L <= 60 * n / rate.min
#
# Both hold from n = ceil((hold.max - MIN_BLOCK) / (60/rate.min - MIN_BLOCK))
# upward: the requirement grows by MIN_BLOCK every 60/rate.min seconds of
# length, a slope under 1, so the feasible lengths are closed upward and the
# smallest of them is the floor. On explainer: 60 / 15.39 = 3.899 s a block at
# the floor pace, n = ceil(7.4 / 3.299) = 3, floor = 8.0 + 2 x 0.6 = 9.20 s.
# Two blocks would need 8.60 s and the pace floor caps a two-block explainer
# at 7.80 s, which is why it is three and not two.
#
# So moment-breakdown (12.00 s) binds and the ceiling is 43.00 s, up from
# 40.40. The rise is CF-0310's measurement arriving here: the count floor of
# 12 was observed on videos 40-47 s long and carried their length inside it,
# and 14.60 s of narration was never something explainer itself demanded.
# Nothing on disk moves - the one channel's ending runs 5.167 s, and so do all
# seven plans that carry one.
#
# Two other readings were weighed, with their numbers:
#   * a count from the pace floor times the channel's shortest video
#     (ceil(15.39 * 30/60) = 8 blocks, floor 12.20 s, ceiling 42.80 s). It
#     imports a length - the one thing CF-0310 removed - and imports the
#     *finished video's* floor at that, while the subject of this formula is
#     the narration. At the 12.20 s it then demands, explainer's own pace
#     floor asks for 4 blocks, not 8: a floor measured at a length nobody is
#     asking about.
#   * leaving explainer out of the formula, named rather than dropped
#     (ceiling 43.00 s, the same number here). Honest only for as long as some
#     *other* pattern is still counted: a channel admitting explainer alone
#     would get no ceiling at all, so the single guard on the ending's length
#     would disappear on the most demanding pattern in the vocabulary.
#
# The mode of the band is read but does not change the arithmetic, which is
# how the count form has always worked here: explainer's count band was
# `emergent` and its floor of 12 was what gave 40.40 s. What the mode decides
# is whether this module may read the band at all - a word it does not know
# means the numbers may not mean what it thinks, and the pattern is then named
# in the reading instead of being counted on a guess (the same answer
# `rhythm.pattern_shortfalls()` gives an unknown mode, and for the same
# reason).

# CF-0315: why a pattern gave the ceiling no number. Codes and not sentences,
# because `structural_ceiling()` answers with a record now and whoever reads it
# - a test, the operator's note, a gate later on - must not have to parse
# prose. `band_mode_unreadable` is rhythm.py's own word, taken from there
# rather than re-spelt: it means the same thing in both places and the two may
# not drift apart.
CEILING_NO_BLOCK_PARAMETER = "no_block_count_parameter"
CEILING_NO_HOLD_BAND = "no_key_frame_hold_band"
CEILING_BAND_UNREADABLE = "band_numbers_unreadable"
CEILING_BAND_MODE_UNREADABLE = rhythm.PATTERN_BAND_MODE_UNREADABLE
CEILING_PACE_FLOOR_INFEASIBLE = "pace_floor_infeasible"
CEILING_PATTERN_NOT_LOADED = "pattern_not_loaded"
# The three that are the channel's own, not any pattern's. They carry
# `pattern_id: None` in the record.
CEILING_NO_TARGET = "no_target_total_seconds"
CEILING_NO_ADMITTED_PATTERNS = "no_admitted_patterns"
CEILING_MIN_BLOCK_UNREADABLE = "min_block_seconds_unreadable"

# The two shapes an envelope arrives in are rhythm's, newest first
# (`BLOCK_COUNT_PARAMETER_FORMS`, CF-0310). They are named here because the
# arithmetic below has to tell them apart - a count *is* a number of blocks,
# a pace becomes one only once a length is solved for - and pinned to those
# names by tests/test_ending_clip.py, so that a reordering of the forms
# cannot silently swap the two branches.
CEILING_PACE_PARAMETER = rhythm.BLOCK_COUNT_PARAMETER_FORMS[0][0]
CEILING_COUNT_PARAMETER = rhythm.BLOCK_COUNT_PARAMETER_FORMS[1][0]

EDITORIAL_LIMIT_NOTE = (
    "CF-0141 section C: the editorial limit - the shortest narration this "
    "channel would still publish - is not recorded anywhere in this project "
    "and is not derived here. Nothing in the repo bounds it: the pattern "
    "files bound structure, not substance; narration_budget records a target "
    "and a words-per-second rate but no floor; and the published feed has no "
    "retention data yet (target_total_seconds itself is marked HYPOTHESIS in "
    "the channel config, to be revisited when the Analyst has it). Naming a "
    "number from that would be a constant with no derivation behind it, which "
    "is the failure CF-0143 and CF-0137 exist as the record of. It is the "
    "user's call, and it needs either a stated editorial rule or retention "
    "data from real publications to stand on. Until it is named, the ceiling "
    "below is the only one enforced, and it is a structural one - it says "
    "what cannot be built, never what is worth watching.")


class _NotCounted(Exception):
    """One pattern could not give the ceiling a number.

    Never leaves this module: `structural_ceiling()` turns it into an entry of
    the reading's `skipped` list. It exists so that every dead end in the
    arithmetic has to *say* which one it is - what CF-0315 closes is a bare
    `except KeyError: continue` that said nothing at all.
    """

    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def structural_ceiling(channel_cfg, root):
    """The longest ending this channel's own pattern vocabulary leaves room
    for - a reading, not a bare number (CF-0315):

        {"seconds": 43.0,                     # the ceiling, or None
         "target_seconds": 55.0,
         "min_block_seconds": 0.6,
         "binding_pattern": "moment-breakdown",
         "counted": [{"pattern_id", "narration_floor_seconds", "blocks",
                      "parameter", "mode", "band_floor",
                      "key_frame_hold_seconds_max"}, ...],
         "skipped": [{"pattern_id", "code", "reason"}, ...]}

    `counted` is ordered by the narration each pattern asks for, longest
    first, so `counted[0]` is the pattern the ceiling is made of. `seconds` is
    None when no pattern gave a number, and `skipped` then says why for every
    one of them; the reasons that are the channel's rather than a pattern's
    (no target, no admitted patterns, no validator to take MIN_BLOCK_SECONDS
    from) are a single entry with `pattern_id: None`.

    The number is derived and never stored: the patterns move, the target
    moves, and a number typed into a config would go on being true after
    neither was. The *skipped* half is the CF-0315 half - a pattern that gave
    no number is named here and in `ceiling_sentence()`, because the ceiling
    silently losing the most demanding pattern in the vocabulary looks exactly
    like a ceiling that was computed.
    """
    budget = (channel_cfg or {}).get("narration_budget") or {}

    def nothing(code, reason, target=None, min_block=None):
        return {"seconds": None, "target_seconds": target,
                "min_block_seconds": min_block, "binding_pattern": None,
                "counted": [],
                "skipped": [{"pattern_id": None, "code": code, "reason": reason}]}

    try:
        target = float(budget["target_total_seconds"])
    except (KeyError, TypeError, ValueError):
        return nothing(CEILING_NO_TARGET,
                       "narration_budget states no readable target_total_seconds, so "
                       "there is no length for a narration floor to be taken out of")
    allowed = ((channel_cfg or {}).get("patterns") or {}).get("allowed_pattern_ids")
    if not isinstance(allowed, list) or not allowed:
        return nothing(CEILING_NO_ADMITTED_PATTERNS,
                       "the channel admits no patterns (patterns.allowed_pattern_ids), "
                       "so nothing in its vocabulary demands any narration at all",
                       target=target)
    try:
        min_block = _validator_min_block_seconds(root)
    except Exception as e:  # noqa: BLE001 - no validator, no derivation, no check
        return nothing(CEILING_MIN_BLOCK_UNREADABLE,
                       f"patterns/validate_patterns.py MIN_BLOCK_SECONDS could not be "
                       f"read under {root} ({type(e).__name__}: {e}) - the arithmetic is "
                       f"the validator's and is not re-typed on this side",
                       target=target)
    counted, skipped = [], []
    for pattern_id in allowed:
        params = ((meme_layer.load_pattern(pattern_id, root) or {})
                  .get("parameters") or {})
        try:
            if not isinstance(params, dict) or not params:
                raise _NotCounted(CEILING_PATTERN_NOT_LOADED,
                                  f"patterns/{pattern_id}.json is missing or states no "
                                  f"parameters under {root}")
            counted.append(_pattern_narration_floor(pattern_id, params, min_block))
        except _NotCounted as e:
            skipped.append({"pattern_id": pattern_id, "code": e.code,
                            "reason": e.reason})
    counted.sort(key=lambda c: c["narration_floor_seconds"], reverse=True)
    return {
        "seconds": (round(target - counted[0]["narration_floor_seconds"], 2)
                    if counted else None),
        "target_seconds": target,
        "min_block_seconds": min_block,
        "binding_pattern": counted[0]["pattern_id"] if counted else None,
        "counted": counted,
        "skipped": skipped,
    }


def _pattern_narration_floor(pattern_id, params, min_block):
    """The shortest narration this one pattern's own parameters can be
    satisfied in, as an entry of the reading's `counted` list.

    Raises `_NotCounted` - never returns a quiet None - when the pattern
    states no number to derive one from, or states it in a word this repo
    cannot read.
    """
    hold = params.get("key_frame_hold_seconds")
    if not isinstance(hold, dict):
        raise _NotCounted(
            CEILING_NO_HOLD_BAND,
            "the pattern states no key_frame_hold_seconds band, and that band's top "
            "is the one block the formula takes whole")
    form = rhythm.block_count_parameter(params)
    if form is None:
        shapes = " or ".join(f[0] for f in rhythm.BLOCK_COUNT_PARAMETER_FORMS)
        raise _NotCounted(
            CEILING_NO_BLOCK_PARAMETER,
            f"the pattern states neither {shapes}, so nothing in it says how many "
            f"blocks a video of it has - and a floor under the narration is a "
            f"statement about blocks")
    key = form[0]
    band = params[key]
    for name, declared in (("key_frame_hold_seconds", hold), (key, band)):
        mode = declared.get("mode")
        if mode not in rhythm.KNOWN_BAND_MODES:
            raise _NotCounted(
                CEILING_BAND_MODE_UNREADABLE,
                f"{name}.mode is {mode!r} and this repo knows only "
                f"{', '.join(rhythm.KNOWN_BAND_MODES)} - a word it cannot read may not "
                f"be taken for one it can, so the pattern is named here instead of "
                f"being counted on a guess about what its numbers mean")
    try:
        hold_max = float(hold["max"])
        band_floor = float(band["min"])
    except (KeyError, TypeError, ValueError):
        raise _NotCounted(
            CEILING_BAND_UNREADABLE,
            f"{key}.min or key_frame_hold_seconds.max is missing or is not a number "
            f"({key}.min={band.get('min')!r}, key_frame_hold_seconds.max="
            f"{hold.get('max')!r})")
    if hold_max <= 0 or band_floor <= 0:
        raise _NotCounted(
            CEILING_BAND_UNREADABLE,
            f"{key}.min is {band_floor:g} and key_frame_hold_seconds.max is "
            f"{hold_max:g} - neither a hold nor a block envelope is a positive number "
            f"here, and the formula has nothing to stand on")
    if key == CEILING_COUNT_PARAMETER:
        # A count is already the number of blocks: this is the validator's
        # feasibility formula unchanged, and the number it gave before CF-0315
        # for every pattern that states one.
        blocks = max(1, int(band_floor))
    else:
        # A pace. `span` is the longest a block may be if the video is to stay
        # at or above the floor pace; the fixed point is the smallest block
        # count at which the hold still fits inside that span (see the CF-0315
        # note above for why no length is imported to get there).
        span = 60.0 / band_floor
        if span <= min_block:
            raise _NotCounted(
                CEILING_PACE_FLOOR_INFEASIBLE,
                f"a floor of {band_floor:g} blocks/min leaves {span:.3f}s a block, at or "
                f"under the {min_block:g}s shortest block the pipeline has ever produced "
                f"- no length of video satisfies this pattern, so none is its floor")
        blocks = max(1, math.ceil((hold_max - min_block) / (span - min_block) - 1e-9))
        # The closed form above is exact; the loop is the guard against a float
        # landing a hair under an integer, and it terminates because the
        # requirement grows by min_block per span of length and span > min_block.
        while hold_max + (blocks - 1) * min_block > blocks * span + 1e-9:
            blocks += 1
    return {"pattern_id": pattern_id,
            "narration_floor_seconds": round(hold_max + (blocks - 1) * min_block, 2),
            "blocks": blocks,
            "parameter": key,
            "mode": band.get("mode"),
            "band_floor": int(band_floor) if key == CEILING_COUNT_PARAMETER
            else band_floor,
            "key_frame_hold_seconds_max": hold_max}


def ceiling_sentence(reading):
    """The reading as one line, for the refusal and for the operator's notes.

    Names the number, the pattern that binds it, every pattern counted and -
    the point of CF-0315 - every pattern that gave no number, with the code
    and the reason. A skipped pattern is loud here and nowhere else: the
    ceiling itself is just a number, and a number computed over half the
    vocabulary looks exactly like one computed over all of it.
    """
    counted = (reading or {}).get("counted") or []
    skipped = (reading or {}).get("skipped") or []
    if not counted:
        line = "no structural ceiling could be derived - no admitted pattern gave a number"
    else:
        top = counted[0]
        line = (f"{reading['seconds']:.2f}s of ending out of a "
                f"{reading['target_seconds']:.2f}s target - {top['pattern_id']} binds it, "
                f"asking {top['narration_floor_seconds']:.2f}s of narration "
                f"({top['blocks']} blocks from {top['parameter']} floor "
                f"{top['band_floor']:g} [{top['mode']}], "
                f"{top['key_frame_hold_seconds_max']:g}s hold + ({top['blocks']} - 1) x "
                f"{reading['min_block_seconds']:g}s)")
        if len(counted) > 1:
            line += ("; also counted " + ", ".join(
                f"{c['pattern_id']} {c['narration_floor_seconds']:.2f}s"
                for c in counted[1:]))
    if skipped:
        line += ("; NOT COUNTED: " + "; ".join(
            f"{s['pattern_id'] or 'the channel'} ({s['code']}) - {s['reason']}"
            for s in skipped))
    return line


def _validator_min_block_seconds(root):
    """`patterns/validate_patterns.py MIN_BLOCK_SECONDS`, imported by path.

    One source for the constant. Copying it here is what would let the two
    repos come to disagree about the same arithmetic, and this repo already
    carries a *different* constant under the same name (rhythm.py's 1.6),
    which is exactly how such a copy would go wrong.
    """
    import importlib.util
    path = Path(root) / "patterns" / "validate_patterns.py"
    spec = importlib.util.spec_from_file_location("_cf0141_validate_patterns", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return float(module.MIN_BLOCK_SECONDS)


def channel_name(channel_cfg):
    """What the typographic variant puts under the phrase. `display_name`,
    falling back to the id - never invented."""
    cfg = channel_cfg or {}
    for key in ("display_name", "channel_id"):
        v = cfg.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# --------------------------------------------------------------------------
# where the card starts
# --------------------------------------------------------------------------

def narration_end(plan):
    """The end of the narration in the finished video - where the card goes.

    The voice-over's own length first (`audio.duration`), because that is
    what CF-0087 budgeted against; then the last block's end, which
    build_render_plan.py sets to exactly that; then the last aligned word,
    for a plan that carries neither.
    """
    audio = (plan or {}).get("audio") or {}
    d = audio.get("duration")
    if isinstance(d, (int, float)) and d > 0:
        return float(d)
    ends = [float(b["end"]) for b in (plan or {}).get("blocks") or []
            if isinstance(b, dict) and isinstance(b.get("end"), (int, float))]
    if ends:
        return max(ends)
    words = (plan or {}).get("words") or []
    word_ends = [float(w["end"]) for w in words
                 if isinstance(w, dict) and isinstance(w.get("end"), (int, float))]
    if word_ends:
        return max(word_ends)
    raise EndCardError("the plan says nothing about how long the narration is - "
                       "no audio duration, no blocks, no words")


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def plan_end_card(plan, channel_cfg, stance, root=None, channel=None,
                  source_label=None):
    """The card for one video, as a dict:

        {text, text_source, channel_name, logo_path, variant, start_s, seconds}

    or None when there is nothing to put on it (CF-0186): no signature
    phrase, no logo and no channel name. `text` is None on a card the channel
    signs without a phrase - the logo, or the channel's own name, is then
    what the card is.

    `stance` is the loaded stance document (load_stance()); `channel_cfg` the
    channel config. Raises EndCardError when either cannot answer - see the
    class's docstring for why this one layer does not degrade to a note.
    """
    root = Path(root) if root else meme_layer.factory_root()
    start = narration_end(plan)
    blank = {"text": None, "text_source": None, "path": None, "source": None}

    # CF-0141: the clip is the top of the chain, so it is asked for first. A
    # channel with a file does not need the phrase at all - the ending it
    # ships *is* its sign-off, and reading a phrase that will not be on the
    # frame would put a line in the batch record for something nobody saw.
    clip, clip_source = ending_path(channel_cfg, root, channel)
    if clip is not None:
        check_ending_bytes(clip, channel_cfg, root)  # CF-0722
        probe = probe_ending(clip)
        check_ending(probe, ending_seconds(channel_cfg), plan, clip)
        # CF-0141 section C: and the ending has to leave the narration room to
        # exist. This is the structural ceiling and only the structural one -
        # it says what the channel's admitted patterns cannot physically be
        # built under, never what is worth watching. See
        # EDITORIAL_LIMIT_NOTE for the limit this project does not have.
        reading = structural_ceiling(channel_cfg, root)
        ceiling = reading["seconds"]
        if ceiling is not None and probe["seconds"] > ceiling:
            raise EndCardError(
                f"the ending clip {clip} runs {probe['seconds']:.2f}s and the "
                f"channel can afford at most {ceiling:.2f}s: the most demanding "
                f"pattern it admits cannot be built in the narration that would be "
                f"left. {ceiling_sentence(reading)}. The arithmetic is "
                f"patterns/validate_patterns.py's own feasibility check, "
                f"key_frame_hold_seconds.max + (blocks - 1) * MIN_BLOCK_SECONDS, "
                f"solved for the pattern's own number of blocks where the pattern "
                f"states a pace rather than a count (CF-0315). This is the structural "
                f"ceiling only - {EDITORIAL_LIMIT_NOTE}")
        return {
            **blank,
            "channel_name": channel_name(channel_cfg),
            "logo_path": None,
            "variant": VARIANT_CLIP,
            "start_s": round(float(start), 3),
            # The file's own measured length, not the config's number: the two
            # were just checked to agree inside a frame, and it is the file
            # that will actually be on screen, so the composition is sized to
            # it exactly.
            "seconds": round(float(probe["seconds"]), 3),
            "path": str(clip),
            "source": clip_source,
        }

    text, text_source = signature_phrase(
        stance, source_label or _relative(stance.get("_path") if isinstance(stance, dict)
                                          else None, root))
    logo = logo_path(channel_cfg, root, channel)
    name = channel_name(channel_cfg)
    # CF-0186: the card is drawn out of what the channel actually has. The
    # phrase is one of three things that can be on it, no longer the one that
    # has to be; with none of the three there is nothing to hold the frame for
    # and the card is not planned at all. `None` rather than a card with three
    # nulls in it: an empty card would still take end_card_seconds out of the
    # budget and put a blank slate on the end of the video, which is the one
    # outcome nobody would have chosen. The seconds go back to the narration,
    # which is what scope item 2 of CF-0186 says happens when the card goes.
    if not (text or logo or name):
        return None
    seconds = card_seconds(channel_cfg)
    return {
        **blank,
        "text": text,
        "text_source": text_source,
        "channel_name": name,
        "logo_path": str(logo) if logo else None,
        "variant": VARIANT_LOGO if logo else VARIANT_TYPOGRAPHIC,
        "start_s": round(float(start), 3),
        "seconds": round(float(seconds), 3),
    }


def composition_seconds(card, plan=None):
    """How long the finished composition runs: the card's end, never less
    than the narration itself."""
    end = float(card["start_s"]) + float(card["seconds"])
    if plan is not None:
        try:
            end = max(end, narration_end(plan))
        except EndCardError:
            pass
    return round(end, 3)


def apply_to_plan(plan, card):
    """plan["end_card"] - what Remotion draws (render_video.py hands the whole
    plan to the composition as props) - and plan["duration"]["composition"],
    the composition's length in seconds: the narration plus the card.

    `duration.actual` is deliberately left alone. It is the length of the
    voice-over and every judgement already made on it - the CF-0087 target
    band, the deviation, the window comparison_line.py clips its lines to -
    is a judgement about the narration, not about the tail card. The renderer
    (`Root.jsx`), the mix (`build_soundtrack.py`) and the render gate
    (`qc_render.py`) read `composition`. Idempotent: a rerun replaces both.
    """
    plan[PLAN_FIELD] = dict(card)
    duration = plan.get("duration")
    if not isinstance(duration, dict):
        duration = {}
        plan["duration"] = duration
    duration["composition"] = composition_seconds(card, plan)
    return plan


def stage_fields(plan):
    """What write_batch_metadata.py copies onto videos[].end_card_delivered:
    the six keys, always all of them. A plan that predates the card (or one
    built without a channel, which cannot know the phrase) gets the same six
    keys with `null` in each - absence never has to be interpreted, the same
    promise the insert pairs make."""
    card = (plan or {}).get(PLAN_FIELD)
    if not isinstance(card, dict) or card.get("variant") == VARIANT_CLIP:
        return {k: None for k in DELIVERED_KEYS}
    return {k: card.get(k) for k in DELIVERED_KEYS}


def ending_stage_fields(plan):
    """CF-0141 (section H): what write_batch_metadata.py copies onto
    videos[].ending_delivered - the four keys, always all of them.

    The pair with stage_fields() above is deliberate and is the whole point of
    keeping two fields instead of renaming one. A video closed by a drawn card
    fills the six card keys and nulls these four; a video closed by the
    channel's clip does the opposite. Neither is a missing field, so a reader
    of the batch record can tell "this video ended on the channel's file" from
    "this video ended on the floor the code draws" without knowing which
    milestone the batch was produced in - which is exactly what a renamed key
    would have destroyed for every batch already shipped.
    """
    card = (plan or {}).get(PLAN_FIELD)
    if not isinstance(card, dict) or card.get("variant") != VARIANT_CLIP:
        return {k: None for k in ENDING_DELIVERED_KEYS}
    return {k: card.get(k) for k in ENDING_DELIVERED_KEYS}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="plan the channel's end card")
    ap.add_argument("plan")
    ap.add_argument("--channel", required=True,
                    help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--root", help="factory root (default $FACTORY_ROOT or the checkout)")
    ap.add_argument("--write", action="store_true", help="merge the card into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else meme_layer.factory_root()
    plan = json.load(open(a.plan))
    cfg = meme_layer.load_channel(a.channel, root)
    if cfg is None:
        raise SystemExit(f"channel {a.channel!r} not found under {root}/channels")
    stance = load_stance(cfg, root, a.channel)
    card = plan_end_card(plan, cfg, stance, root=root, channel=a.channel)
    if a.write:
        apply_to_plan(plan, card)
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "end_card", name="end_card.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
