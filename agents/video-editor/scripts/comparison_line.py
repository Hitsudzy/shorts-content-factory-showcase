#!/usr/bin/env python3
"""CF-0116 / CF-0186: the on-screen line - the fact, and where it came from.

**What this layer is, since CF-0186.** While the voice speaks the video's one
fact (CF-0439: a concrete, verifiable fact of any kind - production, box
office, release, casting, reception, scandal, people news, an unscripted
moment - that the story itself does not carry), the frame carries two things of ours beside the captions:
our own short wording of that fact, and a badge naming the source it came
from. Typography is the same from video to video; the words are the
script's. Either half may be missing - a fact with no source draws the line
alone, a source with no screen wording draws the badge alone - and with
neither there is nothing to put up and nothing is planned.

**What it was, and why none of that survives.** CF-0116 built this as the
visible half of CF-0043: one line per entry of `comparison.checks[]`, our
wording of the divergence between what was announced and what the footage
shows. That position was cancelled by CF-0181 - the material the indexer
actually acquires does not support it - and CF-0183 replaces the comparison
beat in the script with a fact beat. So this file no longer reads
`comparison.checks[]` at all. It reads one field:

    production_fact   the video's one concrete fact (CF-0183). The name is
                      the contract's and stays; since CF-0439 the fact is of
                      any kind (`kind` in the writer's `scripts[].fact`), not
                      only one about the production.

and there is deliberately no fallback to the old field: a line keyed to a
cancelled position is that position surviving, which is exactly what DoD
1.4.1 item 1 refuses. Until CF-0183 lands, scripts carry no `production_fact`
and this layer plans nothing and says so in a note. That is a state, not a
failure - the same shape the end card's missing phrase now has (CF-0186).

**The three fields of `production_fact` this file uses.** Named here because
CF-0183 writes into them; everything else the field carries is the writer's
and the compliance checker's business, not this layer's.

    beat_text   the verbatim substring of the narration that speaks the
                fact. It is the *locator*: meme_layer.locate_beat() finds its
                word range in words.json (align_words), which is the line's
                time window. It is never drawn - it is the narration itself,
                and on screen it would be a second copy of the subtitles.
                No beat_text, no line: there is nowhere to put one.
    on_screen   our wording of the fact for the screen, at most
                FACT_MAX_CHARS characters. Optional: with no `on_screen`,
                `text` is used when it fits that budget, because the fact
                *is* the line and a fact short enough to read needs no second
                wording. Nothing is shortened and nothing is invented - a
                text over the budget is recorded as a note and the line goes
                up with its badge alone.
    source_url  where the fact was found. Optional in the same way: a fact
                with no source still gets its line, it just gets no badge.

**The badge (CF-0164, CF-0166) is unchanged and is now the source half.**
The host of `source_url` is read against two lists - the publication names
and the platforms - and gives three answers. A name draws a badge. A platform
(youtube.com, x.com, ...) draws none and is recorded as a note: the badge
says "we found this here, look into it yourself", and a warehouse's name does
not answer that. A host in neither list still stops the stage, because that
is the one case where silence would hide something - a publication we simply
forgot to enter. What changed is only the consequence: a line without a badge
is no longer dropped, because the fact on it is worth the frame on its own.

The window (CF-0157 item C): the *rest* runs from the start of the beat's
first word to the end of its last, held to a floor of MIN_SECONDS (2.0 s)
and clipped to the video's duration; the movement is added around it, so the
mounted window is move_in + rest + move_out. The floor is on the rest, never
on the window - taking a 0.42 s arrival and a 0.30 s exit out of a 2.0 s
window would leave 1.28 s to read, less than the user called enough. Two
lines never overlap on the full window, movement included: the earlier one
ends where the later one comes up, floor or no floor - two of our own cards
stacked on one frame is the one thing the layer must never do.

The source (CF-0157 items A and B). What the card is, is a pointer to where
we found this: "we found this here; if you are curious, look into it
yourself using this data" (the user's own words, 2026-09-08). Not a
verdict - neither a tick ("we vouch") nor a question mark ("we doubt") - so
what is drawn is a reference: a numeral, the same device a footnote uses.
`number_references()` assigns it, 1..n in the order the lines come up, and
only to a line that actually carries a badge - an address *and* a
publication to name (CF-0166: a source on a platform gets neither a badge
nor a number, so the description's list has no hole in it).

No URL is drawn. **The address is in the video's description**, and the card
says so; the earlier plan to print a host and a path segment on the frame was
withdrawn by the user the same day it was taken. `source_url` therefore
stays in the record in full - from a proof CF-0071 placed on the same beat
(source_url_from = "proof"), else from the fact's own `source_url`
(= "script") - and goes to the description through
`comparison_line_delivered`. The obligation on the other end is CF-0017's:
the description must carry the source block this card promises. Until
publisher exists nothing is published, so there is no window in which the
card lies to a living viewer, which is why there is no gate here.

Outcomes are notes, not a requested/delivered pair: unlike the insert layers
this line is not requested by the script - a fact that can carry one gets
one - so `05-video-editor.json` records what was delivered
(`comparison_line_delivered`, symmetric with `pattern_delivered` of CF-0041)
and the reasons for the rest go into the plan's notes.

**The names `comparison_line` / `comparison_lines` are left alone on
purpose** (CF-0186). The module, the plan field, the delivered field and the
channel-config switch `video_editor.comparison_line.enabled` are read by the
factory root - `patterns/validate_patterns.py`, the config schema that
CF-0161 had just finished adding them to, `channels/example-film.json` - and
renaming them is a change to the root repository, not to this one. Nothing
they *carry* describes the cancelled position any more; the identifiers are
naming debt, recorded as such in the CF-0186 report.

Usage:
    comparison_line.py <plan.json> --script <03-content-researcher.json>
        --script-id <id> [--channel <id|path.json>] [--root <factory root>]
        [--words <words.json>] [--write]
"""
import argparse
import json
import sys
from pathlib import Path

import meme_layer
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

LAYER = "comparison_line"
PLAN_FIELD = "comparison_lines"
DELIVERED_FIELD = "comparison_line_delivered"

# The floor of the *rest* (CF-0116 item 1, restated by CF-0157). A beat
# shorter than this - the voice states the fact in 1.4 s - still leaves the
# line standing long enough to be read; the line outliving its beat by a
# fraction of a second is cheaper than a line nobody could read.
#
# CF-0157: the floor is on the rest, not on the window. The movement is
# counted *over* it, never inside it - a 0.42 s arrival and a 0.30 s exit
# taken out of a 2.0 s window would leave 1.28 s of readable time, less than
# the 2.0 s the user had just called enough ("кому нужно - тот остановит и
# посмотрит"). So: window = move_in + rest (>= MIN_SECONDS) + move_out.
MIN_SECONDS = 2.0

# The movement (CF-0157 item C, re-timed by CF-0164 §6). Asymmetric on
# purpose: the card takes longer to arrive than to leave, because the arrival
# has to be noticed - it is the thing that says "there is a source under
# this" - and the exit only has to get out of the way. Both are eased in
# ComparisonLine.jsx; these are only the lengths, and they live here rather
# than in the component because they are what the window is built out of: the
# planner cannot promise "2.0 s of rest" without knowing how long the
# movement takes.
#
# CF-0164: 0.42/0.30 -> 0.38/0.24, the spec's own numbers (380 ms of arrival,
# 240 ms of exit). The rest floor is untouched, so the minimum time on screen
# is 0.38 + 2.0 + 0.24 = 2.62 s.
MOVE_IN_SECONDS = 0.38
MOVE_OUT_SECONDS = 0.24

# The script field this layer reads (CF-0183's, named here by CF-0186 so
# that the writer and the editor agree on one word). One fact per video, so
# one object and not a list - the plan field stays a list because two of the
# geometry's promises (no two lines on one frame, the footnote numbering) are
# written for more than one and cost nothing to keep.
FACT_FIELD = "production_fact"

# The screen wording's budget, in characters. Inherited unchanged from the
# contract that CF-0116 was built against - "our wording for the screen at
# that moment, under sixty characters" - because the ground has not moved:
# it is what can be read in the time a beat takes, beside subtitles that are
# already running. The fact's own `text` is drawn only when it fits this;
# longer, and the writer owes an `on_screen`.
FACT_MAX_CHARS = 60

# Why a fact got no line, or a line no badge. Recorded as notes; a line that
# went up is in `comparison_line_delivered`.
#
# CF-0186 changed what these decide. `no_source_url` and `source_is_platform`
# used to drop the line, because the line *was* the badge; the line now
# carries the fact, so the two are reasons the badge is absent and the line
# stands without it. They are still two reasons and not one, for the reason
# CF-0166 gave: `no_source_url` is a fact that points at nothing and should
# be fixed in the script, `source_is_platform` is a fact pointing at
# something real that is simply not a publication and there is nothing to
# fix.
#
# `nothing_to_draw` is new: no screen wording *and* no badge leaves an empty
# window, and an empty window mounted for 2.6 s is a bug that looks like a
# design.
SKIP_NO_FACT = "no_fact"
SKIP_NO_BEAT_TEXT = "no_beat_text"
SKIP_NOTHING_TO_DRAW = "nothing_to_draw"
# CF-0193 split `beat_not_found` here too, and it has to be the same three
# words it is in proof_layer.py: one predicate (meme_layer.match_beat) fails,
# and two layers reading it must not name that failure differently - that is
# the CF-0159 defect. The fourth code below is this layer's own: the beat was
# located and the alignment carries no timing for it, which is not a matching
# failure at all and used to be filed as one.
SKIP_BEAT_MISSING_IN_SCRIPT = meme_layer.BEAT_MISSING_IN_SCRIPT
SKIP_BEAT_UNMATCHED_IN_ALIGNMENT = meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT
SKIP_BEAT_NO_ALIGNMENT = meme_layer.BEAT_NO_ALIGNMENT
SKIP_BEAT_NOT_TIMED = "beat_not_timed"
# Read-only: plans and notes written before CF-0193 carry this word.
SKIP_BEAT_NOT_FOUND = "beat_not_found"
SKIP_NO_ROOM = "no_room"
SKIP_REASONS = ((SKIP_NO_FACT, SKIP_NO_BEAT_TEXT, SKIP_NOTHING_TO_DRAW)
                + meme_layer.BEAT_FAILURE_CODES
                + (SKIP_BEAT_NOT_TIMED, SKIP_NO_ROOM))

# Why a line carries no badge. Not skips - the line is on screen either way.
NO_BADGE_NO_SOURCE_URL = "no_source_url"
NO_BADGE_SOURCE_IS_PLATFORM = "source_is_platform"

URL_FROM_PROOF = "proof"
URL_FROM_SCRIPT = "script"

# --------------------------------------------------------------------------
# the badge's geometry (CF-0164, docs/source-badge-spec.md §§2-5, 7)
# --------------------------------------------------------------------------
#
# The width of the panel is decided here rather than in the component for one
# reason: §3 says a name that does not fit is a *refusal*, and a refusal has
# to happen where the plan is built, not on a frame nobody is watching being
# rendered. The component draws `panel_w` and never measures anything.
#
# The model is exact because both fonts are monospaced and both are vendored
# (render/public/fonts): Courier Prime advances 1228/2048 = 0.5996 em and IBM
# Plex Mono 600/1000 = 0.600 em per glyph, whatever the glyph. 0.6 is used
# here, so the model is never narrower than the render - the error is 0.06 %
# and it is on the safe side.
MONO_ADVANCE = 0.6

# CF-0572: the badge's face is the channel's now (`plan.theme.font.badge`),
# and MONO_ADVANCE above is measured for exactly these two vendored faces
# (render/public/fonts, lib/fonts.js BADGE_FACES). A stack that asks for
# another face first would be drawn at a width this module did not measure,
# so the badge is refused (`badge_font_error`) rather than mis-sized. Every
# channel's stack starts with Courier Prime today.
# TODO(CF-0572): when a channel picks another badge face, vendor it and
# measure its advance here (a table per family), instead of refusing it.
MEASURED_BADGE_FAMILIES = ("Courier Prime", "IBM Plex Mono")

LABEL_TEXT = "SOURCE ↓ DESC"   # §2: one string, never varies
LABEL_SIZE = 30                     # §5: Regular 30, tracking +2
LABEL_TRACKING = 2
NAME_SIZE = 40                      # §5: Bold 40, no tracking
PANEL_PADDING = 28                  # §3: W = text_width + 2*28
PANEL_MAX_W = 620                   # §3: over this the name does not fit
ANCHOR_W = 104                      # §3: 104x120 at x=0, y=260
ANCHOR_H = 120
BADGE_Y = 260

# §7: nine references, and the tenth is a refusal - the anchor is one glyph
# wide and a two-digit numeral does not fit it.
MAX_REFERENCES = 9

# §2/§3 and the spec header's decision 3: the panel says the publication's
# own name, and the name comes from a table keyed by the host of
# `source_url`. Never derived from the domain - "hollywoodreporter.com" is
# not "Hollywoodreporter" - and a host nobody has named stops the stage
# instead of guessing, by the same doctrine that forbids an ellipsis on a
# long name.
#
# These four are the channel's own newsrooms (channels/example-film.json,
# sources.rss.feeds[].site). A channel adds its own under
# `video_editor.comparison_line.publishers`; that table is merged over this
# one, so a channel can also correct a name here without a code change.
DEFAULT_PUBLISHERS = {
    "variety.com": "Variety",
    "deadline.com": "Deadline",
    "hollywoodreporter.com": "The Hollywood Reporter",
    "vulture.com": "Vulture",
}

# CF-0166: the second list, and the whole point of the task. CF-0157's rule
# ("an unknown host stops and is reported") glued two different cases
# together, and on the real corpus that fired at once - raygun-sneak-peek's
# check c3 cited a YouTube video and the batch stopped.
#
# A host is one of three things now:
#
#   in DEFAULT_PUBLISHERS / the channel's table   a publication -> a badge
#   here                                          a platform -> no badge
#   in neither                                    unknown -> the stage stops
#
# A platform is where a video happens to sit, not who vouches for the fact.
# Naming one on the badge would be worse than showing nothing: the badge
# promises "we found this here, look into it yourself if you like", and
# "YouTube" answers that promise with the name of a warehouse. So a platform
# is not an entry in the name table with a bad name - it is a source that
# gets no badge at all, recorded with its own reason
# (NO_BADGE_SOURCE_IS_PLATFORM). CF-0186: the line itself still goes up,
# carrying the fact - only the badge is absent.
#
# A host in neither list is still a refusal, and that is the signal the whole
# two-list split exists to keep: a *real* publication we simply have not
# entered would otherwise disappear silently, and nobody would learn that the
# table has a hole in it.
#
# These eight are what the corpus produced by 2026-09-09. The set grows with
# the material, not with a release: a channel adds its own under
# `video_editor.comparison_line.platforms` (a list of hosts) and they are
# added to these, so no code change is needed to name a new platform.
DEFAULT_PLATFORMS = frozenset({
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "reddit.com",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
})


class SourceBadgeError(Exception):
    """The badge cannot be drawn as specified, and nothing here may invent a
    way around it: an unknown host (§3, the spec header's decision 3), a name
    that does not fit `W <= 620` (§3) or a tenth source (§7).

    Deliberately *not* a note. Every other failure in this layer costs one
    line; these three would cost the viewer a wrong name, a truncated name or
    an unreadable numeral, and the user's instruction on all three is the
    same word: остановиться и сообщить."""


def publishers(channel_cfg):
    """The host -> name table for this channel: the built-in one, with the
    channel's own entries merged over it."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    table = dict(DEFAULT_PUBLISHERS)
    extra = switch.get("publishers") if isinstance(switch, dict) else None
    if isinstance(extra, dict):
        for host, name in extra.items():
            if isinstance(host, str) and isinstance(name, str) and name.strip():
                table[host_of(f"https://{host.strip()}") or host.strip().lower()] = name.strip()
    return table


def platforms(channel_cfg):
    """The set of hosts that are places, not publications (CF-0166): the
    built-in list plus whatever the channel adds.

    Added to, never replaced - the same shape the name table has, for the
    same reason. A channel that meets a new platform writes one host into
    `video_editor.comparison_line.platforms` and the badge stops asking about
    it; nothing in this file has to be released for that."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    hosts = set(DEFAULT_PLATFORMS)
    extra = switch.get("platforms") if isinstance(switch, dict) else None
    if isinstance(extra, (list, tuple, set, frozenset)):
        for host in extra:
            if isinstance(host, str) and host.strip():
                hosts.add(host_of(f"https://{host.strip()}") or host.strip().lower())
    return hosts


def host_of(url):
    """The registrable host of `url`, lowercased and without `www.` or a
    port. None when there is no host to read."""
    if not isinstance(url, str) or "://" not in url:
        return None
    host = url.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0]
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def text_width(name):
    """The width of the widest of the panel's two rows, in whole pixels.

    The label is a constant, so this is really `max(constant, the name)`: a
    short name still gets a panel wide enough for `SOURCE ↓ DESC`. Tracking
    is counted between glyphs and not after the last one, which is how the
    component draws it (the trailing letter-space is pulled back)."""
    label = len(LABEL_TEXT) * LABEL_SIZE * MONO_ADVANCE \
        + max(0, len(LABEL_TEXT) - 1) * LABEL_TRACKING
    return int(round(max(label, len(name) * NAME_SIZE * MONO_ADVANCE)))


def badge_font_error(stack):
    """None when the badge's font stack (`theme.font.badge`) starts with a
    face the panel width is measured for (MEASURED_BADGE_FAMILIES), else the
    reason - the width model would not be the render's."""
    if not isinstance(stack, str) or not stack.strip():
        return "the plan's theme names no badge face (theme.font.badge)"
    first = stack.split(",")[0].strip().strip('"').strip("'")
    if first in MEASURED_BADGE_FAMILIES:
        return None
    return (f"the badge face {first!r} (theme.font.badge {stack!r}) is not one the "
            f"panel width is measured for ({', '.join(MEASURED_BADGE_FAMILIES)}, "
            f"MONO_ADVANCE {MONO_ADVANCE}) - vendor and measure it first (CF-0572)")


def panel_width(name):
    """§3: `W = text_width + 56`, in whole pixels (§7 - a subpixel edge
    flickers after YouTube's compression)."""
    return text_width(name) + 2 * PANEL_PADDING


def publisher_of(url, table, platform_hosts=None):
    """(name, panel width) for a `source_url`; `(None, None)` when the host is
    a platform; a refusal when it is neither.

    CF-0166: three outcomes, not two. The middle one is the new one and it is
    a *pair of Nones rather than an exception* because it is not a failure at
    all - a fact sourced to a YouTube clip is a perfectly good fact, it
    simply has no publication to put on a badge. The caller turns that into a
    note and draws the line without one; see NO_BADGE_SOURCE_IS_PLATFORM.

    The two failures stay loud, and the first of them is why the platform
    list had to be a list rather than "anything we cannot name". A host in
    neither list means the operator has to decide which list it belongs in -
    and until they do, the alternatives are a badge naming the wrong
    publication or a real publication quietly vanishing from the screen. A
    name too wide means the table has to carry the publication's own short
    form (the spec's "сокращение"), because the one thing §3 forbids is
    cutting the name with an ellipsis."""
    platform_hosts = platform_hosts or ()
    host = host_of(url)
    if host is None:
        raise SourceBadgeError(
            f"comparison line: {url!r} has no host to name a publication from")
    name = table.get(host)
    if not name:
        if host in platform_hosts:
            return None, None
        raise SourceBadgeError(
            f"comparison line: host {host!r} is in neither list ({url}). It is "
            f"either a publication - add it to "
            f"video_editor.comparison_line.publishers in the channel config "
            f"(or to comparison_line.DEFAULT_PUBLISHERS) as the publication "
            f"writes itself, nothing here derives a name from a domain - or a "
            f"place where a video sits and not a publication at all, in which "
            f"case add the host to video_editor.comparison_line.platforms and "
            f"the fact gets no badge (CF-0166). "
            f"Named: {', '.join(sorted(table))}. "
            f"Platforms: {', '.join(sorted(platform_hosts))}")
    width = panel_width(name)
    if width > PANEL_MAX_W:
        raise SourceBadgeError(
            f"comparison line: {name!r} needs a {width}px panel and the "
            f"maximum is {PANEL_MAX_W}px ({host}). Put the publication's own "
            f"short form in the table - at {NAME_SIZE}px monospace the fit is "
            f"{int((PANEL_MAX_W - 2 * PANEL_PADDING) / (NAME_SIZE * MONO_ADVANCE))} "
            f"characters. An ellipsis is not an option: a cut-off masthead "
            f"reads as a bug, not as a device")
    return name, width


def enabled(channel_cfg):
    """The line is on unless the channel says otherwise. It is not an insert
    layer (nothing is borrowed, nothing is licensed - the words are ours), so
    it has no `insert_layers` switch; `video_editor.comparison_line.enabled:
    false` in the channel config turns it off for a channel that does not
    want it."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    if isinstance(switch, dict) and switch.get("enabled") is False:
        return False
    return True


def fact_records(script):
    """The script's facts (the `production_fact` field), as a list (CF-0186).

    One video carries one fact (CF-0183), so `production_fact` is an object
    and this returns a list of at most one. A list is accepted too and is not
    an invitation to write several - it is what keeps a future second fact
    from being a change to every caller of this function. Anything else, and
    an absent field, is an empty list: absence is this layer's normal state
    until CF-0183 lands, and it is never an exception.
    """
    node = (script or {}).get(FACT_FIELD)
    if isinstance(node, dict):
        node = [node]
    if not isinstance(node, list):
        return []
    # An empty object is absence written out, not a fact with every field
    # missing: it would otherwise be reported as a fact with no beat, which
    # reads as a script that tried and failed rather than one that has none.
    return [f for f in node if isinstance(f, dict) and f]


def line_text(fact, notes=None, fact_id=None):
    """Our wording of the fact for the screen, or None (CF-0186).

    `on_screen` when the writer wrote one; otherwise the fact's own `text`,
    but only when it is inside FACT_MAX_CHARS - a fact short enough to read
    in the time its beat takes *is* the line, and asking for a second wording
    of it would be asking the writer to say the same thing twice. Nothing is
    truncated: an over-long `text` with no `on_screen` beside it leaves the
    line to its badge and says so in a note, because a fact cut off
    mid-sentence on the frame reads as a bug and not as a device (the same
    rule §3 of the badge spec applies to a masthead that will not fit).
    """
    f = fact if isinstance(fact, dict) else {}
    on_screen = f.get("on_screen")
    on_screen = on_screen.strip() if isinstance(on_screen, str) else ""
    if on_screen:
        if len(on_screen) > FACT_MAX_CHARS and notes is not None:
            notes.append(f"comparison line {fact_id}: on_screen is "
                         f"{len(on_screen)} characters against a budget of "
                         f"{FACT_MAX_CHARS} - it goes up as written, and the "
                         f"budget is what can be read beside running subtitles")
        return on_screen
    text = f.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return None
    if len(text) > FACT_MAX_CHARS:
        if notes is not None:
            notes.append(f"comparison line {fact_id}: the fact's text is "
                         f"{len(text)} characters and the screen's budget is "
                         f"{FACT_MAX_CHARS} - no wording for the frame, so the "
                         f"line carries its badge only. Write "
                         f"{FACT_FIELD}.on_screen")
        return None
    return text


def proof_source_url(plan, fact):
    """The `source_url` of a proof CF-0071 actually placed on this fact's
    beat, or None. Read off the plan's own provenance records
    (proof_layer.apply_to_plan), because that is the list that says a capture
    exists.

    CF-0243: the join is the url. The proof records used to carry `check_id`
    and this matched the fact's id against it - a match that could never
    happen, because the fact has no id to match (CF-0223 deleted the field
    from the request when CF-0181 cancelled the check). The contract makes
    the url the join itself: `source.url` is `production_fact.source_url` and
    nothing else, so a placed record on that url is a capture of this fact's
    document.
    """
    want = (fact or {}).get("source_url")
    want = want.strip() if isinstance(want, str) else None
    if not want:
        return None
    records = ((plan or {}).get("proof") or {}).get("proofs") or []
    for r in records:
        if not isinstance(r, dict) or r.get("layer") != "proof":
            continue
        if r.get("source_url") == want and not r.get("skipped"):
            return r["source_url"]
    return None


def block_at(blocks, at):
    """The index of the block the line starts in, or None. The line spans the
    beat and a beat can cross a cut; the index recorded is where it comes up,
    which is the block a proof would have been placed on."""
    best = None
    for i, b in enumerate(blocks or []):
        try:
            start, end = float(b["start"]), float(b["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start - 1e-9 <= at < end:
            return i
        if at >= end:
            best = i
    return best


def video_duration(plan):
    d = (plan or {}).get("duration")
    if isinstance(d, dict):
        actual = d.get("actual")
        if isinstance(actual, (int, float)) and actual > 0:
            return float(actual)
    blocks = (plan or {}).get("blocks") or []
    ends = [float(b["end"]) for b in blocks if isinstance(b, dict) and "end" in b]
    return max(ends) if ends else None


def window_around(hold_start, hold_end, duration):
    """The full window around a rest period: (start, end, move_in, move_out).

    The rest is what the caller computed off the beat; the movement is added
    outside it. The card is therefore fully in place when the voice reaches
    the beat's first word, which is the point - it is read while it is
    still, not while it is arriving.

    Both movements shrink rather than push: a beat that starts at 0.2 s gets
    a 0.2 s arrival instead of one that would begin before the video, and a
    line resting to the last frame leaves with whatever is left (usually
    nothing - CF-0117 clips it to the end card anyway)."""
    move_in = max(0.0, min(MOVE_IN_SECONDS, hold_start))
    move_out = MOVE_OUT_SECONDS
    if duration is not None:
        move_out = max(0.0, min(move_out, duration - hold_end))
    return hold_start - move_in, hold_end + move_out, move_in, move_out


def _record(fact_id, hold_start, hold_end, duration, block_index, text, url, url_from,
            publisher, panel_w):
    start, end, move_in, move_out = window_around(hold_start, hold_end, duration)
    return {"fact_id": fact_id, "text": text,
            "start_s": round(start, 3), "end_s": round(end, 3),
            # The rest: what the 2.0 s floor is on, and what the component
            # holds the card still for. `start_s`/`end_s` stay the mounted
            # window (Video.jsx reads those), so nothing downstream has to
            # learn a second pair of names to know when the line is up.
            "hold_start_s": round(hold_start, 3), "hold_end_s": round(hold_end, 3),
            "move_in_s": round(move_in, 3), "move_out_s": round(move_out, 3),
            # CF-0157 item A: the reference mark drawn on the card. Filled in
            # after the overlaps are resolved (the numbering is over the
            # lines that survive), and only for a line that has a badge to
            # print it on (CF-0166).
            "ref": None,
            # CF-0164: what the panel actually says, and how wide it is. The
            # name is resolved here (the table lives with the channel, not
            # with the renderer) and the width is decided here (§3's refusal
            # on a name that does not fit has to happen while there is still
            # a plan to refuse). ComparisonLine.jsx draws both and measures
            # nothing - so the pixel that flickers, §7's whole worry, cannot
            # differ between two frames of the same line.
            "publisher": publisher, "panel_w": panel_w,
            "block_index": block_index, "source_url": url,
            "source_url_from": url_from}


def _shorten_arrival(rec, new_start):
    """The same line arriving from `new_start` instead of its own - a faster
    slide onto an untouched rest.

    This is what gives way first when two windows collide, because it is the
    cheapest thing in the layer: the next line's arrival is motion over a
    frame the previous line is vacating, and a shorter slide still reads as
    a slide. Squeezed to nothing the card simply appears, which is worse
    than a slide and still better than a rest anybody has to read fast."""
    new_start = min(max(new_start, rec["start_s"]), rec["hold_start_s"])
    return {**rec, "start_s": round(new_start, 3),
            "move_in_s": round(rec["hold_start_s"] - new_start, 3)}


def _clip_to(rec, new_end):
    """The same line ending at `new_end` instead of its own end, or None if
    nothing readable is left.

    What gives way first is the exit, not the rest: an exit cut to nothing
    costs the viewer a fifth of a second of motion, a rest cut below the
    floor costs them the sentence. Below the floor the exit is already gone
    and the rest simply ends where it is told - the no-overlap rule outranks
    the floor (see resolve_overlaps)."""
    hold_start = rec["hold_start_s"]
    if new_end - hold_start <= 1e-9:
        return None
    move_out = max(0.0, min(rec["move_out_s"], new_end - hold_start - MIN_SECONDS))
    return {**rec, "end_s": round(new_end, 3),
            "hold_end_s": round(new_end - move_out, 3),
            "move_out_s": round(move_out, 3)}


def resolve_overlaps(lines, notes=None):
    """No two lines are on screen at once: in start order, a line that would
    still be up when the next one comes ends at that start. The floor loses
    to this rule - a second line over the first is the failure the viewer
    sees; a line 0.3 s short of the floor is one they do not. A line left
    with nothing (the next line comes up before this one has even finished
    arriving) is dropped as `no_room`.

    CF-0157: "on screen at once" is measured on the full window, movement
    included. The overlap this rule exists to prevent is two of our own cards
    on one frame, and a card that is still sliding out is on the frame."""
    lines = sorted(lines, key=lambda r: (r["start_s"], r["end_s"]))
    kept = []
    for i, rec in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt is not None and rec["end_s"] > nxt["start_s"]:
            # In order of what it costs the viewer: the next line's arrival,
            # then this line's exit, then this line's rest. Only the last of
            # the three is words, so it is the last thing spent.
            nxt = _shorten_arrival(nxt, min(rec["end_s"], nxt["hold_start_s"]))
            lines[i + 1] = nxt
        if nxt is not None and rec["end_s"] > nxt["start_s"]:
            clipped = _clip_to(rec, nxt["start_s"])
            if clipped is None:
                if notes is not None:
                    notes.append(
                        f"comparison line {rec['fact_id']}: {SKIP_NO_ROOM} - the next "
                        f"line comes up before this one has finished arriving")
                continue
            rec = clipped
            held = rec["hold_end_s"] - rec["hold_start_s"]
            if notes is not None and held < MIN_SECONDS - 1e-9:
                notes.append(
                    f"comparison line {rec['fact_id']}: rest cut to "
                    f"{held:.2f}s at the next line's first frame - "
                    f"under the {MIN_SECONDS:.1f}s floor, and two lines never share a frame")
        if rec["hold_end_s"] - rec["hold_start_s"] <= 1e-9:
            if notes is not None:
                notes.append(f"comparison line {rec['fact_id']}: {SKIP_NO_ROOM} - "
                             f"the next beat starts on this one's first word")
            continue
        kept.append(rec)
    return kept


def has_badge(rec):
    """Whether this record carries a badge: an address to point at *and* a
    publication to name (CF-0166). ComparisonLine.jsx draws no badge without
    both, so this is the same question the component asks - kept here because
    the numbering has to ask it before the component can.

    CF-0186: "no badge" is no longer "nothing on screen". A line without one
    still draws the fact; what it does not draw is the anchor, the panel and
    the numeral, and what it does not take is a place in the description's
    numbered list."""
    return bool((rec or {}).get("source_url")) and bool((rec or {}).get("publisher"))


def number_references(lines):
    """CF-0157 item A: the reference mark, 1..n in the order the lines come
    up - and only on a line that carries a `source_url`.

    The numeral is not decoration. It is the key that joins the card on
    screen to the entry in the description CF-0017 owes it: the card says
    "[2], and the address is in the description", the description says
    "[2] <url>". A line with no address to point at gets no numeral, and
    ComparisonLine.jsx then draws no source mark at all - the element is a
    pointer to a source or it is not drawn, and a badge promising a source
    nobody can look up is the one failure worse than no mark.

    CF-0164 §7: nine of them, and the tenth stops the stage. The anchor is
    104px of red with one glyph in it; `10` either shrinks the numeral out of
    legibility or grows the anchor and breaks every other number in §3. A
    script with ten sourced facts is a script to re-cut, not a badge to
    redesign on the fly.

    CF-0166: what takes a number is a *badge*, not a `source_url`. The two
    stopped being the same thing when a platform became a third outcome: a
    line with an address but no publication has nothing on screen to print a
    numeral on, and if it took one anyway the description's list - which is
    numbered from these - would show [1] [3] with no [2] to be found. The
    planner leaves such a line without a publisher (NO_BADGE_SOURCE_IS_
    PLATFORM), so this condition is the lock on that door: a record that
    reaches the numbering without a publisher takes no number, whether it
    came from an old plan or from a future caller."""
    sourced = sum(1 for r in lines if has_badge(r))
    n = 0
    for rec in lines:
        if has_badge(rec):
            n += 1
            if n > MAX_REFERENCES:
                raise SourceBadgeError(
                    f"comparison line: {sourced} sourced facts in "
                    f"one video and the anchor holds one digit, so the "
                    f"{MAX_REFERENCES + 1}th has nowhere to go. Cut the script's facts "
                    f"to {MAX_REFERENCES} or fewer; a two-digit anchor is a different "
                    f"badge (docs/source-badge-spec.md §7)")
            rec["ref"] = n
        else:
            rec["ref"] = None
    return lines


def plan_lines(script, words, plan, channel_cfg=None):
    """The layer's decision for one video: {"lines": [...], "delivered":
    [...], "notes": [...]}. `lines` is what the renderer draws and is
    identical to `delivered`, which is what 05-video-editor.json records -
    a line that is not on screen is not delivered, so there is one list and
    two names for it. Never raises past a malformed script: a fact that
    cannot carry a line is a note.

    CF-0186: the video has one fact, so there is at most one line. The list
    shape is kept because the two promises built on it - no two lines on one
    frame, and the footnote numbering - cost nothing to keep and are what a
    second line would need on the day there is one.
    """
    notes = []
    facts = fact_records(script)
    theme = plan.get("theme") if isinstance(plan, dict) else None
    if facts and enabled(channel_cfg) and isinstance(theme, dict):
        # CF-0572: a badge drawn in a face the width was not measured for is
        # the class of error §3 refuses (a panel that does not fit its name).
        why = badge_font_error((theme.get("font") or {}).get("badge"))
        if why:
            raise SourceBadgeError(why)
    if not enabled(channel_cfg):
        if facts:
            notes.append(f"comparison line: off for this channel "
                         f"(video_editor.comparison_line.enabled = false), "
                         f"{len(facts)} fact(s) unwritten")
        return {"lines": [], "delivered": [], "notes": notes}
    if not facts:
        # CF-0186: the normal state until CF-0183 lands. Not a failure and
        # not silence - a reader of the plan's notes is told the layer ran
        # and found nothing to put up.
        notes.append(f"comparison line: {SKIP_NO_FACT} - the script carries no "
                     f"`{FACT_FIELD}` (CF-0183), so there is no fact to put on "
                     f"screen and no line was planned")
        return {"lines": [], "delivered": [], "notes": notes}

    blocks = (plan or {}).get("blocks") or []
    duration = video_duration(plan)
    table = publishers(channel_cfg)
    platform_hosts = platforms(channel_cfg)
    lines = []
    for fact in facts:
        fid = fact.get("fact_id") or FACT_FIELD
        beat_text = fact.get("beat_text")
        beat_text = beat_text.strip() if isinstance(beat_text, str) else ""
        if not beat_text:
            # CF-0183 makes beat_text mandatory; a script without it does not
            # pass the root contract. Nothing is invented here either way.
            notes.append(f"comparison line {fid}: {SKIP_NO_BEAT_TEXT} - "
                         f"no beat to put a line on")
            continue
        # Our wording of the fact for the screen. CF-0186: this is what the
        # line is *for*, and it no longer gates anything on its own - a fact
        # with no screen wording still gets its badge, exactly as before.
        text = line_text(fact, notes, fid)
        # The address. A proof CF-0071 placed on this beat first, because
        # that is a capture that exists; otherwise the fact's own source.
        url = proof_source_url(plan, fact)
        url_from = URL_FROM_PROOF if url else None
        if url is None:
            link = fact.get("source_url")
            if isinstance(link, str) and link.strip():
                url, url_from = link.strip(), URL_FROM_SCRIPT
        publisher, panel_w = (None, None)
        if not url:
            notes.append(f"comparison line {fid}: {NO_BADGE_NO_SOURCE_URL} - the "
                         f"fact points at nothing, so the line carries no badge")
        else:
            # A host in neither list, or a name too wide for the panel,
            # raises out of here; see SourceBadgeError. It is a
            # stage-stopper by decision, not a note. A *platform* is the
            # third outcome and is exactly the opposite - a note, never a
            # stop.
            publisher, panel_w = publisher_of(url, table, platform_hosts)
            if publisher is None:
                # CF-0166, as CF-0186 leaves it: no badge and no number, so
                # the description's numbered list still has no hole in it -
                # but the line itself stays up, because the fact on it is
                # ours and does not depend on who hosts the source.
                notes.append(f"comparison line {fid}: {NO_BADGE_SOURCE_IS_PLATFORM} - "
                             f"{host_of(url)} is a place where a video sits, not a "
                             f"publication that vouches for the fact ({url})")
        if not text and publisher is None:
            notes.append(f"comparison line {fid}: {SKIP_NOTHING_TO_DRAW} - no "
                         f"wording for the screen and no publication to name, so "
                         f"the window would be empty")
            continue
        found = meme_layer.match_beat(beat_text, script or {}, words or [])
        if found is None:
            # CF-0193: which of the two, and the fragments it was decided on.
            # "the beat's words are not in the alignment" was true of both and
            # useful for neither: one is a script that never says the fact,
            # the other is our aligner losing a sentence that is right there.
            why = meme_layer.beat_failure(beat_text, script or {}, words or [])
            near = why.get("nearest") or {}
            notes.append(f"comparison line {fid}: {why['code']} - beat "
                         f"{why['searched']!r} ({why['in_script_coverage']} of its words "
                         f"are in the script, {why['alignment_coverage']} in the "
                         f"alignment); nearest heard at word {near.get('word_index')}: "
                         f"{near.get('text')!r}")
            continue
        first, last = found["first_word_index"], found["last_word_index"]
        try:
            start = float(words[first]["start"])
            end = float(words[last]["end"])
        except (IndexError, KeyError, TypeError, ValueError):
            notes.append(f"comparison line {fid}: {SKIP_BEAT_NOT_TIMED} - the aligned "
                         f"words carry no timing")
            continue
        # The rest, and only the rest: the beat's own span held to the floor.
        # window_around() adds the movement outside it (CF-0157 item C).
        end = max(end, start + MIN_SECONDS)
        if duration is not None and end > duration:
            end = duration
            if end - start < MIN_SECONDS - 1e-9:
                notes.append(f"comparison line {fid}: rest held to the end of the video "
                             f"({end - start:.2f}s, under the {MIN_SECONDS:.1f}s floor)")
        if end - start <= 1e-9:
            notes.append(f"comparison line {fid}: {SKIP_NO_ROOM} - the beat ends where "
                         f"the video does")
            continue
        lines.append(_record(fid, start, end, duration, block_at(blocks, start),
                             text, url, url_from, publisher, panel_w))

    lines = number_references(resolve_overlaps(lines, notes))
    for rec in lines:
        notes.append(f"comparison line {rec['fact_id']}: {rec['start_s']:.2f}-"
                     f"{rec['end_s']:.2f}s on block {rec['block_index']} "
                     f"(rest {rec['hold_start_s']:.2f}-{rec['hold_end_s']:.2f}s, "
                     f"in {rec['move_in_s']:.2f}s / out {rec['move_out_s']:.2f}s)"
                     # CF-0186: the fact is on the frame now, so the note says
                     # what was on it - a record that only ever named the
                     # source could not be read against the screen.
                     + (f", fact {rec['text']!r}" if rec["text"] else "")
                     + (f", ref [{rec['ref']}] {rec['publisher']} "
                        f"({rec['panel_w']}px) -> {rec['source_url']}"
                        if rec["ref"] else ""))
    return {"lines": lines, "delivered": list(lines), "notes": notes}


# --------------------------------------------------------------------------
# the plan and the batch record
# --------------------------------------------------------------------------

def apply_to_plan(plan, result):
    """plan["comparison_lines"] - the list the Remotion composition reads
    (render_video.py hands the whole plan to it as props) and the same list
    05-video-editor.json records. Idempotent: a rerun replaces it."""
    plan[PLAN_FIELD] = [dict(r) for r in result["lines"]]
    return plan


def stage_fields(plan):
    """What write_batch_metadata.py copies onto the videos[] record: the
    delivered lines, always a list ([] when the plan carries none - absence
    never has to be interpreted, the same promise the insert pairs make)."""
    lines = (plan or {}).get(PLAN_FIELD)
    if not isinstance(lines, list):
        return []
    return [dict(r) for r in lines if isinstance(r, dict)]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="plan the on-screen fact line and its source badge")
    ap.add_argument("plan")
    ap.add_argument("--script", required=True, help="03-content-researcher.json")
    ap.add_argument("--script-id", required=True)
    ap.add_argument("--channel", help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--root", help="factory root (default $FACTORY_ROOT or the checkout)")
    ap.add_argument("--words", help="words.json; default: the plan's own `words`")
    ap.add_argument("--write", action="store_true", help="merge the result into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else meme_layer.factory_root()
    plan = json.load(open(a.plan))
    batch = json.load(open(a.script))
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((s for s in scripts or [] if s.get("script_id") == a.script_id), None)
    if script is None:
        raise SystemExit(f"script {a.script_id!r} not in {a.script}")
    words = meme_layer.load_words(a.words) if a.words else plan.get("words") or []
    result = plan_lines(script, words, plan, meme_layer.load_channel(a.channel, root))
    if a.write:
        apply_to_plan(plan, result)
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps({"comparison_lines": result["lines"], "notes": result["notes"]},
                     ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "comparison_line", name="comparison_line.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
