#!/usr/bin/env python3
"""CF-0040: the rotation that assigns a (pattern, rhythm) pair, and the guard
that stands at the point of assignment.

Run it to see where a channel currently stands:

    python3 rotation/rotate.py status example-film

Assign, before Content Researcher writes anything:

    python3 rotation/rotate.py assign example-film 2026-09-02T0053Z \\
        --script lf-2026-09-02-001-script1 --script lf-2026-09-02-002-script1

Reject an assignment, with a written reason (the fallback is chosen here, not
by the caller - there is deliberately no way to ask for a particular pair):

    python3 rotation/rotate.py reject example-film lf-2026-09-02-001-script1 \\
        --reason "the story has one side, so contrast has nothing to compare"

A script id is unique inside a batch, not across batches (CF-0383): one that
stands in two batches - two batches of one day, a repeat and its parent - is
refused until the batch is named, with `--batch-id <batch>` (or `--batch DIR`).

From a rebuild (or any batch directory) the channel is read off the batch's own
records instead of typed - CF-0416, see `channel_of_batch()`:

    python3 rotation/rotate.py reject --batch pipeline/rebuilds/2026-09-27T1757Z \\
        lf-2026-09-27-009-script1 --reason "the pool has no shot for the held moment"

Reject the *rhythm* rather than the pair - CF-0286. Same command with
`--rhythm`, same guard, same rules; the one difference is that the replacement
skips every pair carrying the rhythm that was refused, instead of only the pair:

    python3 rotation/rotate.py reject example-film lf-2026-09-02-001-script1 \\
        --rhythm --reason "the fact has no second side, so alternate has nothing to cross"

Refuse an assignment the pool cannot supply - the planner's refusal, CF-0139.
Not an opinion about the pair, so no replacement is chosen and the topic goes
back to the queue to wait for material:

    python3 rotation/rotate.py refuse example-film lf-2026-09-02-001-script1 \\
        --deficit pipeline/.../work/<topic>/plan.assetless-rung.json \\
        --reason "four blocks would ship with no picture and every rung is spent"

Fill in the production columns once Video Editor has run:

    python3 rotation/rotate.py produced example-film 2026-09-02T0053Z

Or, for every batch still on disk that the ledger has not caught up with -
which `assign` also does on its own, see the enrichment section below:

    python3 rotation/rotate.py backfill example-film

--------------------------------------------------------------------------
Why the rotation assigns instead of the agent choosing (CF-0015 Q4)
--------------------------------------------------------------------------

An LLM given a free choice of form collapses onto its favourite one. A month
later the channel is 70-80% one pattern and that is discovered at a
channel review, with the channel already full. The guarantee has to be a
property of the mechanism, not of a judgement made 90 times.

The agent keeps one valve: it may reject an assignment in writing, because a
pattern can be genuinely wrong for a story (a `contrast` on a story with one
side has nothing to compare). The fallback is strictly the next pair in the
rotation and never the agent's preference, and every rejection is ruled on by
the guard - otherwise "reject until the one I like comes up" is free choice
through the back door, and the whole mechanism degenerates into the thing it
was built to prevent.

The rotation assigns the pair only. The numbers inside it - block_count, the
hold ceiling - are drawn afterwards by Content Researcher via
`patterns/validate_patterns.py draw_order`, and since CF-0086 that draw is
checked against the narration it will be read over (`fit_order_to_voice`): a
block count the hold cannot fit is recomputed there, in writing, and a pair
that cannot fit at the top of its bands comes back as a written reason for the
`reject` valve above. The pair is never swapped by that check - it is this
file's decision, not the draw's.

CF-0446 moved the coarse half of that question to the point of issue: the
channel's expected speech (`narration_budget`, target minus tail) is known
before a word is written, so a pair whose block band cannot carry it even at
the top of its hold window is left out of the set the rotation turns over,
and every assignment carries a `speech_fit` record - what was passed over and
why, and `hold_floor_seconds`, the lowest hold the draw may take on this
speech (AHS 0929Z drew 1.8 s under a floor of 2.08 s). See
`choose_pair_for_speech`. Every path that issues a pair - `assign` and the
replacement after an upheld rejection - draws through `_draw_for_speech`, so
neither can hand out a pair the other keeps out.

CF-0300 narrowed where inside the envelope that draw may land, and only for
the `hold` rhythm: there the montage grows the held block *past* the number it
was given by swallowing whole stretches of narration, so a hold drawn near the
top of the pattern's band puts the block over the top of the band, and nothing
downstream may cut it back. `hold_draw_band()` answers where the draw may fall
and `check_hold_draw()` reads an already written order against it; the
envelope itself is untouched (CF-0195). None of that is this file's business -
the rotation still assigns the pair only - but a pair whose hold cannot be
drawn legally would be refused there, on the `reject` route this file owns.

--------------------------------------------------------------------------
Eligibility is a property of the PAIR, not of the pattern (CF-0039's note)
--------------------------------------------------------------------------

`channels/<channel>.json` lists allowed `pattern_id`s. That gate is real but
deliberately weaker than what is needed: `explainer` on `even` builds today,
`explainer` on `alternate` does not, because nothing executes `alternate`
until CF-0041. Assigning the pair anyway would hand the agent a pattern whose
rhythm Video Editor silently ignores, and leave a rhythm in the metadata that
is not in the video - exactly the confusion the requested/delivered pairs of
CF-0015 exist to prevent. So eligibility is computed per pair, against
`executable_today` in patterns/rhythms.json, and a pair that is blocked says
which task unblocks it.

--------------------------------------------------------------------------
When there is nothing to choose between
--------------------------------------------------------------------------

Today exactly one pair is executable: `explainer` on `even`. The no-repeat
window K cannot be satisfied - four consecutive assignments cannot hold four
distinct pairs when only one exists - and that is a state, not a fault. So K
is applied as `k_effective = min(K, number of eligible pairs)`, the reports
say the window is constrained and name the task that widens it, and nothing
raises. The moment CF-0041 flips `executable_today` and the channel admits
more patterns, k_effective rises to the configured K on its own, with no code
change and no config change.

What the guard must NOT do in that state is manufacture activity: it does not
reject, it does not write empty assignments, and it does not report skew. One
pair with 30 uses out of 30 is a perfectly even distribution over the pairs
that exist.
"""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "shared"))

# CF-0231: and this file's own directory, for the same reason - `import pool`
# / `import shortage` below resolve because the interpreter puts a script's
# directory on sys.path, which is true of `python3 rotation/rotate.py` and of
# nothing else. See rotation/shortage.py for the whole note.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import validate_patterns as vp  # noqa: E402
import channel_ids  # noqa: E402

from ledger import (  # noqa: E402
    Ledger,
    LedgerError,
    excluded_rhythm,
    ledger_path,
    locked as ledger_locked,
    mark_pattern_undeliverable,
    mark_rhythm_excluded,
    rejection_prose,
    history_of_script,
    rhythms_excluded_for,
    undeliverable_pattern,
    utc_now,
)
import material  # noqa: E402
import pool  # noqa: E402
import shortage  # noqa: E402

CHANNELS_DIR = ROOT / "channels"
PIPELINE_DIR = ROOT / "pipeline"

# CF-0180 (2026-09-12) renamed a channel - legacy-film -> example-film - and
# deliberately left its batch directories under pipeline/ named as they were
# created (decision Q3 of the 2026-09-11 grill): those directories, like the run
# journals beside them, are dated records of what happened, and renaming them
# would rewrite that record. So for a renamed channel the directory name and the
# channel id are no longer one string, and both directions of the mapping are
# needed here:
#   reading  a channel's batches live in every directory the channel has ever
#            used, so the lookups below search all of them, current name first.
#            New batches are only ever written under the current id; the former
#            names are read-only history.
#   naming   the monthly archive (scripts/monthly_archive.py) knows a channel only by the
#            directory it found on disk and then asks the ledger about it under
#            that name, so a former id given on the command line has to resolve
#            to the current one or the archive job blocks forever on a ledger it
#            cannot find.
# A channel that was never renamed is unaffected: its list is one name long.
#
# CF-0197 moved the mapping itself out of this file and into the data it is a
# fact about - `channels/<id>.json` -> `former_channel_ids`, read by
# `shared/channel_ids.py`, written down once in README "Renamed channels and
# their batch directories". The rotation was the first reader to need it and is
# no longer the only one, and a rule kept in two places is CF-0159.
def channel_names(channel):
    """Every name this channel's directories may carry, current one first."""
    return channel_ids.channel_names(channel, root=ROOT)


def resolve_channel(name):
    """The current id of a channel that may have been named by a former one."""
    return channel_ids.resolve_channel(name, root=ROOT)


def channel_batch_dirs(channel, pipeline_dir=None):
    """The directories on disk that hold this channel's batches."""
    return channel_ids.channel_batch_dirs(channel, pipeline_dir or PIPELINE_DIR,
                                          root=ROOT)


# Both per-channel files of the rotation, opened under the channel's current
# id whatever id the caller holds (CF-0197). The CLI resolves at the door and
# says so out loud, but a library caller does not go through it - and it is
# exactly the caller holding a channel read out of a batch file written before
# the rename that would otherwise open an empty ledger and read "nothing was
# ever assigned" off it.
def _ledger_path(channel, ledger_dir=None):
    return ledger_path(resolve_channel(channel), ledger_dir)


# CF-0416: the channel of a batch directory, read off the batch's own records.
# A rebuild lives at `pipeline/rebuilds/<ts>` and its directory names no
# channel; its own `05-video-editor.json` does (`rebuild_of.channel`, and the
# top-level `channel` the Editor writes as the source batch's), and before the
# Editor has run the copied `03`/`01` do - they are the source batch's files
# byte for byte. The rotation row a rebuild rejects is the source batch's row,
# found by script id in that channel's ledger; nothing about the pattern or
# its numbers is touched on the way (0929Z's operator, refused the write,
# bent the plan's held moment to the pool instead - CF-0416 item 3).
BATCH_CHANNEL_GROUP = "rebuilds"          # `05.channel` of a rebuild that could not tell
BATCH_CHANNEL_RECORDS = ("03-content-researcher.json", "01-trend-hunter.json")


def _read_json(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def channel_of_batch(batch_dir):
    """`{"channel", "batch_id", "read_from"}` for a batch directory: the channel
    (current id) and the batch the rotation rows belong to - for a rebuild, the
    source batch. Raises RotationError when no record of the batch names one."""
    bd = Path(batch_dir)
    if not bd.is_dir():
        raise RotationError(f"{bd} is not a batch directory")
    ve = _read_json(bd / "05-video-editor.json")
    if ve is not None:
        src = ve.get("rebuild_of") if isinstance(ve.get("rebuild_of"), dict) else {}
        if src.get("channel"):
            return {"channel": resolve_channel(str(src["channel"])),
                    "batch_id": src.get("batch_id"),
                    "read_from": "05-video-editor.json#rebuild_of"}
        if ve.get("channel") and ve["channel"] != BATCH_CHANNEL_GROUP:
            return {"channel": resolve_channel(str(ve["channel"])),
                    "batch_id": ve.get("batch_id"),
                    "read_from": "05-video-editor.json#channel"}
    for name in BATCH_CHANNEL_RECORDS:
        d = _read_json(bd / name)
        if d and d.get("channel"):
            return {"channel": resolve_channel(str(d["channel"])),
                    "batch_id": d.get("batch_id"), "read_from": f"{name}#channel"}
    raise RotationError(
        f"{bd}: no record names the channel (05-video-editor.json `rebuild_of`/`channel`, "
        f"then {', '.join(BATCH_CHANNEL_RECORDS)} `channel`) - name it on the command line")


def _shortage_log_path(channel, ledger_dir=None):
    return shortage.log_path(resolve_channel(channel), ledger_dir)

# The shortest rejection reason that is a reason. A rejection costs the
# rotation a slot and is data about the pattern's design, so "no" is not
# enough; the agent has to say what about *this script* made the pair wrong.
MIN_REASON_CHARS = 25


class RotationError(Exception):
    pass


# --------------------------------------------------------------------------
# configuration - K and the window live in the channel file, never here
# --------------------------------------------------------------------------

def load_channel(channel):
    # A former id resolves before the lookup (CF-0197): this is reached from
    # the CLI, which has already resolved, but also from callers holding a
    # channel read out of a batch file written before the rename.
    path = channel_ids.channel_config_path(channel, root=ROOT)
    if not path.exists():
        raise RotationError(f"no channel config at {path}")
    return json.loads(path.read_text())


def rotation_config(channel_cfg):
    """K and the distribution window, from the channel file.

    No defaults in code, on purpose (CF-0015): both numbers are near-certain to
    move after the first live batches, and a default here would mean a channel
    that silently disagrees with its own config file. Missing is an error.
    """
    cfg = channel_cfg.get("patterns", {}).get("rotation")
    if not isinstance(cfg, dict):
        raise RotationError(
            f"channel {channel_cfg.get('channel_id')!r}: patterns.rotation is missing - K and "
            f"the distribution window are channel configuration, and this code carries no "
            f"default for either")
    out = {}
    for key in ("no_repeat_window_k", "distribution_window"):
        value = cfg.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise RotationError(
                f"channel {channel_cfg.get('channel_id')!r}: patterns.rotation.{key} must be a "
                f"positive integer, got {value!r}")
        out[key] = value
    if out["distribution_window"] < out["no_repeat_window_k"]:
        raise RotationError(
            f"distribution_window {out['distribution_window']} is smaller than "
            f"no_repeat_window_k {out['no_repeat_window_k']} - the skew window has to contain "
            f"the no-repeat window to mean anything")
    return out


# --------------------------------------------------------------------------
# eligibility: which (pattern, rhythm) pairs can actually become a video today
# --------------------------------------------------------------------------

def eligible_pairs(channel_cfg, patterns=None, rhythms=None):
    """Returns (pairs, blocked).

    `pairs` is the sorted list of (pattern_id, rhythm_id) that pass both gates:
    the channel's pattern permission, and the pair's own executability.
    `blocked` is [((pattern_id, rhythm_id), blocking_task_id), ...] - what the
    channel permits but nothing can build yet, and what will open it.
    """
    patterns = patterns if patterns is not None else vp.load_patterns()
    rhythms = rhythms if rhythms is not None else vp.load_rhythms()

    allowed = channel_cfg.get("patterns", {}).get("allowed_pattern_ids") or []
    ex_rhythms = {r["rhythm_id"] for r in rhythms["rhythms"] if r["executable_today"]}
    rhythm_blocker = {r["rhythm_id"]: r.get("blocked_by") for r in rhythms["rhythms"]}
    ex_openings = {o["kind"] for o in rhythms["opening_block_kinds"] if o["executable_today"]}
    opening_blocker = {o["kind"]: o.get("blocked_by") for o in rhythms["opening_block_kinds"]}

    pairs, blocked = [], []
    for pid in allowed:
        pattern = patterns.get(pid)
        if pattern is None:
            raise RotationError(
                f"channel allows pattern {pid!r}, which is not in patterns/ - the channel "
                f"gate and the vocabulary have drifted apart")
        choices = pattern["parameters"]["opening_block"]["choices"]
        buildable_openings = set(choices) & ex_openings
        for rid in pattern["allowed_rhythms"]:
            if not buildable_openings:
                # Nothing can open this pattern yet, so no rhythm of it is a
                # buildable pair either.
                blocked.append(((pid, rid), opening_blocker.get(sorted(choices)[0])))
            elif rid in ex_rhythms:
                pairs.append((pid, rid))
            else:
                blocked.append(((pid, rid), rhythm_blocker.get(rid)))
    return sorted(pairs), sorted(blocked)


def blocking_tasks(blocked):
    return sorted({task for _, task in blocked if task})


# --------------------------------------------------------------------------
# the rotation
# --------------------------------------------------------------------------

def effective_k(k, pairs):
    """K, capped by how many distinct pairs exist.

    Four consecutive assignments cannot hold four distinct pairs when the
    vocabulary offers one. Capping is what makes the pre-CF-0041 state a state
    instead of a permanent violation.
    """
    return min(k, len(pairs))


def _window_the_next_row_joins(history, window):
    """The rows already in the window that the next assignment will complete.

    A window of `window` rows ending on the row about to be written consists of
    that row plus the `window - 1` before it. Both the rotation's choice and the
    guard's re-derivation have to count that set, and not `history[-window:]`,
    which is the window ending on the *previous* row - see `choose_pair`.
    """
    return history[-(window - 1):] if window > 1 else []


def choose_pair(history, pairs, k, window, exclude=()):
    """Pick the next pair. Deterministic - no randomness anywhere in here.

    `history` is the list of standing pairs in assignment order (rejected
    assignments are not in it: they produced no video, so they must not move
    the distribution - see the note on the rejection guard below).

    Two rules, in this order:

      1. hard: not one of the last k_effective - 1 standing pairs. That is the
         no-repeat window, and it is a filter rather than a preference because
         "no pair twice inside K" is the thing being guaranteed.
      2. soft: of what is left, the pair least used inside the distribution
         window; ties broken by total use, then by least recently used, then
         by name. Least-used-first is what keeps the pool even, which is the
         whole job of 1.3.3 - Publisher (CF-0042) can only draw a
         non-repeating feed cheaply from an even pool.

    The window counted is the `window - 1` rows the new assignment is about to
    join, not the `window` rows it follows (CF-0145). Those are different sets:
    the window this choice has to leave even is the one the new row completes,
    and `history[-window:]` includes one row that drops out of it. Counting the
    row that is leaving was harmless while the standing sequence only ever grew
    - the greedy self-corrects one step later - but an upheld rejection deletes
    a row from inside the window as well as shifting it, and then the two
    errors no longer cancel: the pair the deletion took out is counted as one
    short, the replacement goes to whatever is least-used in the misaligned
    window, and the window the replacement lands in comes out two uses apart.
    """
    if not pairs:
        raise RotationError(
            "no eligible (pattern, rhythm) pair for this channel - every permitted pattern "
            "is waiting on a task that makes its rhythm or opening executable")
    k_eff = effective_k(k, pairs)
    banned = set(history[-(k_eff - 1):]) if k_eff > 1 else set()
    candidates = [p for p in pairs if p not in banned and p not in set(exclude)]
    if not candidates:
        raise RotationError(
            f"nothing left to assign: {len(pairs)} eligible pair(s), {len(banned)} inside the "
            f"no-repeat window, {len(set(exclude))} excluded")

    in_window = _window_the_next_row_joins(history, window)
    win_counts = Counter(in_window)
    totals = Counter(history)
    last_used = {}
    for i, pair in enumerate(history):
        last_used[pair] = i

    return min(candidates,
               key=lambda p: (win_counts[p], totals[p], last_used.get(p, -1), p))


def pairs_carrying(pairs, rhythms):
    """Every eligible pair whose rhythm is one of `rhythms`. CF-0286.

    The bridge between "the rhythm was refused" and the only thing the
    rotation's draw understands, which is a set of pairs to leave alone. It is
    a widening of `exclude`, never of the candidate set: a rhythm exclusion can
    only take pairs off the table, so it cannot be a way to reach a pair - see
    `rule_on_rejection`'s note on R7.
    """
    rhythms = set(rhythms or ())
    return [p for p in pairs if p[1] in rhythms]


def pairs_of_patterns(pairs, patterns):
    """Every eligible pair whose pattern is one of `patterns`. CF-0775 - the
    pattern-level twin of `pairs_carrying`, and like it only ever a widening
    of `exclude`."""
    patterns = set(patterns or ())
    return [p for p in pairs if p[0] in patterns]


def _batch_material(channel, batch_id, pipeline_dir=None, batch_dir=None):
    """The batch's topics and pool for `rotation/material.py` (CF-0775).
    `batch_dir` (a `reject --batch DIR`, a rebuild included) wins; else the
    batch is looked up under the channel's directories. Unreadable is
    `known: False` - nothing is excluded on a guess."""
    if batch_dir is None and batch_id:
        batch_dir = channel_ids.batch_dir(channel, batch_id, pipeline_dir or PIPELINE_DIR,
                                          root=ROOT)
    return material.BatchMaterial(batch_dir)


def check_assignment(pair, history, pairs, k, window, exclude=()):
    """The guard, at the point of assignment. Returns a list of violations.

    It re-derives what should have happened rather than trusting the rotation:
    a guard that only checks what the rotation told it is a comment.

    `exclude` is what the rotation was not allowed to pick - the pair the agent
    just refused. The skew rule is evaluated against what was actually pickable,
    otherwise every upheld rejection would read as a skew violation.
    """
    violations = []
    if pair not in pairs:
        violations.append(
            f"{pair[0]}/{pair[1]} is not an eligible pair - either the channel does not permit "
            f"the pattern or the rhythm is not executable today")
        return violations
    if pair in set(exclude):
        violations.append(
            f"{pair[0]}/{pair[1]} was excluded from this choice and was chosen anyway")
        return violations

    k_eff = effective_k(k, pairs)
    recent = history[-(k_eff - 1):] if k_eff > 1 else []
    if pair in recent:
        violations.append(
            f"{pair[0]}/{pair[1]} was assigned {len(recent) - recent.index(pair)} assignment(s) "
            f"ago, inside the no-repeat window of {k_eff}")

    banned = set(recent) | set(exclude)
    candidates = [p for p in pairs if p not in banned]
    win_counts = Counter(_window_the_next_row_joins(history, window))
    floor = min(win_counts[p] for p in candidates)
    if win_counts[pair] > floor:
        least = sorted(p for p in candidates if win_counts[p] == floor)
        violations.append(
            f"{pair[0]}/{pair[1]} has {win_counts[pair]} use(s) in the {window - 1} standing "
            f"assignments this one would join to make a window of {window}, but "
            f"{least[0][0]}/{least[0][1]} has {floor} - assigning the more-used pair skews the "
            f"pool that CF-0042 has to draw an even feed from")
    return violations


def _removal_damage(history_after, position, pairs, k_eff, window):
    """What deleting the element at `position` costs the assignments around it.

    `history_after` is the standing sequence with that element already gone.
    Deleting an element pulls everything after it one step closer to everything
    before it, so windows that straddle the deletion point change composition
    while every other window is untouched - only the straddling ones are
    examined, and only they can have gone bad.

    Two things can go bad, and they are the two guarantees the rotation makes:
    a pair can land inside K of itself, and a window of `window` assignments
    can end up more than one use apart between its most- and least-used pair.
    Both are breakages caused by an assignment nobody made, which is why they
    are the guard's business at the moment of the rejection rather than a
    discrepancy someone finds in the ledger a month later.

    Returns a human-readable string, or None when the removal is harmless.
    """
    if k_eff >= 2:
        for start in range(max(0, position - k_eff + 1), position):
            seen = {}
            for offset, pair in enumerate(history_after[start:start + k_eff]):
                if pair in seen:
                    return (f"{pair[0]}/{pair[1]} twice inside {k_eff} consecutive standing "
                            f"assignments (positions {start + seen[pair]} and {start + offset})")
                seen[pair] = offset

    for start in range(max(0, position - window + 1), position):
        chunk = history_after[start:start + window]
        if len(chunk) < window:
            continue
        counts = Counter(chunk)
        values = [counts[p] for p in pairs]
        if max(values) - min(values) > 1:
            worst = max(pairs, key=lambda p: counts[p])
            least = min(pairs, key=lambda p: counts[p])
            return (f"the window of {window} at position {start} skewed to "
                    f"{counts[worst]} uses of {worst[0]}/{worst[1]} against "
                    f"{counts[least]} of {least[0]}/{least[1]}")
    return None


def _window_skew(chunk, pairs):
    """Max-min of uses across `pairs` in one window, described if over one."""
    counts = Counter(chunk)
    values = [counts[p] for p in pairs]
    if max(values) - min(values) <= 1:
        return None
    worst = max(pairs, key=lambda p: counts[p])
    least = min(pairs, key=lambda p: counts[p])
    return (f"{counts[worst]} uses of {worst[0]}/{worst[1]} against "
            f"{counts[least]} of {least[0]}/{least[1]}")


def _replacement_skew(history, replacement, pairs, k, window):
    """R8 (CF-0526): whether appending `replacement` skews a window - the one
    it completes, or one the rotation's own next draws are then forced into.

    `history` is the standing sequence with the refused row already taken out,
    so the window ending on the replacement is the `window - 1` rows the draw
    counted (`_window_the_next_row_joins`) plus the replacement itself - the
    same set, which is the point: the draw picked the least-used pickable pair
    of that set, and this asks whether least-used-pickable was even enough.

    Then the next `window` draws are played forward, exactly as `choose_pair`
    would make them with nothing refused. Those are deterministic, so their
    windows are already decided by the time the rejection is upheld - and a
    rejection in the middle of a batch reorders the standing sequence, which
    can leave the pairs one use short exactly where the no-repeat filter will
    ban them a few draws later. That skew would surface as an ordinary
    assignment, far from the rejection that caused it; R6 cannot see it
    either, because the windows it would land in are not full yet when R6
    looks (the CF-0145 note: 93 % of them). Played-forward draws stop at the
    first one the rotation could not make.

    Measured across `pairs` - the set the rotation turned over, so a pair the
    speech check keeps out of the rotation (CF-0446) is not counted short.
    Only a full window is judged, as in `_removal_damage`. Returns a string,
    or None.
    """
    seq = list(history) + [replacement]
    for step in range(window + 1):
        if step:
            try:
                seq.append(choose_pair(seq, pairs, k, window))
            except RotationError:
                return None
        if len(seq) < window:
            continue
        skew = _window_skew(seq[-window:], pairs)
        if skew:
            where = ("the window of {w} it would complete" if not step else
                     "the window of {w} that the rotation's own draw {n} after it would "
                     "complete, with nothing else refused,")
            return where.format(w=window, n=step) + f" skews to {skew}"
    return None


def no_repeat_violations(history, k_eff):
    """Every place a pair repeats inside k_eff consecutive assignments.

    The exit-criterion check of CF-0040, and the guard's own audit of a
    history it did not build itself.
    """
    out = []
    if k_eff < 2:
        return out
    for start in range(0, max(0, len(history) - k_eff + 1)):
        window = history[start:start + k_eff]
        seen = {}
        for offset, pair in enumerate(window):
            if pair in seen:
                out.append((start + seen[pair], start + offset, pair))
            seen[pair] = offset
    return out


def distribution_report(channel, ledger_dir=None, pipeline_dir=None, root=None):
    """What the guard sees. Read-only; this is what `status` prints.

    It also reports the production gap (CF-0049) - what the batches on disk
    say happened that the ledger does not. Read-only stays read-only: `status`
    names the gap and the command that closes it, it does not close it.
    """
    cfg = load_channel(channel)
    rot = rotation_config(cfg)
    pairs, blocked = eligible_pairs(cfg)
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    rows = ledger.rows()
    standing = ledger.standing_rows(rows)
    history = [(r["pattern_id"], r["rhythm_id"]) for r in standing]
    window = rot["distribution_window"]
    in_window = history[-window:]
    counts = Counter(in_window)
    per_pair = {f"{p}/{r}": counts[(p, r)] for p, r in pairs}
    unknown = {f"{p}/{r}": c for (p, r), c in counts.items() if (p, r) not in pairs}
    values = list(per_pair.values()) or [0]
    k_eff = effective_k(rot["no_repeat_window_k"], pairs)

    rejections = [r for r in rows if r["rejected_at"]]
    denied = [r for r in rows if r["rejection_verdict"] == "denied"]
    gap = production_gap(channel, ledger_dir, pipeline_dir)
    waiting = awaiting_material(channel, ledger_dir, root=root)

    return {
        "channel": channel,
        "eligible_pairs": [f"{p}/{r}" for p, r in pairs],
        "blocked_pairs": {f"{p}/{r}": task for (p, r), task in blocked},
        "blocked_by": blocking_tasks(blocked),
        "k_configured": rot["no_repeat_window_k"],
        "k_effective": k_eff,
        "constrained": k_eff < rot["no_repeat_window_k"],
        "window": window,
        "assignments_total": len(rows),
        "standing_total": len(standing),
        "counts_in_window": per_pair,
        "counts_outside_vocabulary": unknown,
        "spread": max(values) - min(values),
        "no_repeat_violations": no_repeat_violations(history, k_eff),
        "rejections_upheld": len(rejections),
        "rejections_denied": len(denied),
        "awaiting_material": waiting,
        "production_recoverable": gap["recoverable"],
        "production_awaiting": gap["awaiting"],
        "production_unrecorded": gap["unrecorded"],
    }


# --------------------------------------------------------------------------
# CF-0446: does the pair fit the speech it will be read over?
# --------------------------------------------------------------------------
#
# AHS, batch 2026-09-27T0929Z: list on staccato, a 1.8 s block ceiling, a
# narration of ~49 s. However the anchors fall, 49 s under a 1.8 s ceiling is
# at least ceil(49 / 1.8) = 28 blocks, and the pattern's band is 12-24, so the
# order could not be executed as issued and the topic was lost at the cadence
# gate two rewrites later. Nothing at the point of assignment had compared the
# pair with the length of the speech, although that length is known before a
# word is written: it is the channel's own target (`narration_budget`,
# `target_total_seconds` minus the tail - the same subtraction as
# `narration_seconds`, CF-0141).
#
# The user's decision of 2026-10-02: the rotation checks the pair against the
# expected speech at issue and takes the next pair if this one does not fit.
# The arithmetic is the one rhythm.py applies when it cuts:
#
#   the fewest blocks the speech can be cut into = ceil(speech / ceiling)
#   the most blocks it can be cut into           = floor(speech / MIN_BLOCK_SECONDS)
#
# and the pair fits when that range meets the pattern's `block_count` band.
# The ceiling of a PAIR is the highest one its draw may reach: the top of
# `hold_draw_band` on a cap rhythm, the band's top on `hold` (where the drawn
# number is a floor, CF-0300 - see `vp.block_cap_seconds`). A drawn value
# below that is the draw's business, and `vp.fit_order_to_voice` recomputes
# it; what the rotation adds for it is `hold_floor_seconds` - the lowest hold
# this speech allows on this pair, i.e. the number the AHS draw went under.
#
# A pattern that orders no count (CF-0310 rates) or draws no hold has nothing
# to be unreachable, and is reported as not checked rather than as a fit.

def expected_speech_seconds(channel_cfg):
    """(seconds, source) the channel expects its narration to take, or (None, why)."""
    budget = channel_cfg.get(vp.NARRATION_BUDGET_KEY)
    if not isinstance(budget, dict) or budget.get("target_total_seconds") is None:
        return None, (f"the channel has no {vp.NARRATION_BUDGET_KEY}.target_total_seconds - "
                      f"nothing to check the pair against")
    try:
        seconds = float(budget["target_total_seconds"]) - vp.tail_seconds(budget)
    except (KeyError, ValueError, TypeError) as exc:
        return None, f"{vp.NARRATION_BUDGET_KEY} is unreadable here: {exc}"
    return round(seconds, 3), (f"{vp.NARRATION_BUDGET_KEY}.target_total_seconds "
                               f"{budget['target_total_seconds']} - {vp.tail_key(budget)} "
                               f"{vp.tail_seconds(budget)}")


def speech_fits_band(speech_seconds, block_ceiling, band, block_floor=None):
    """The bare arithmetic: can `speech_seconds` be cut into a block count inside
    `band` with no block longer than `block_ceiling` and none shorter than
    `block_floor` (MIN_BLOCK_SECONDS by default)?"""
    floor = vp.MIN_BLOCK_SECONDS if block_floor is None else float(block_floor)
    lo, hi = int(band[0]), int(band[1])
    min_blocks = max(1, math.ceil(speech_seconds / float(block_ceiling) - 1e-9))
    max_blocks = max(1, math.floor(speech_seconds / floor + 1e-9))
    return {"min_blocks": min_blocks, "max_blocks": max_blocks,
            "fits": min_blocks <= hi and max_blocks >= lo}


def pair_speech_fit(pattern, rhythm_id, speech_seconds, rhythms=None, words_per_second=None):
    """Report whether (pattern, rhythm) can carry `speech_seconds` inside its band."""
    pair = f"{pattern['pattern_id']}/{rhythm_id}"
    out = {"pair": pair, "expected_speech_seconds": speech_seconds, "checked": False,
           "fits": True}
    params = pattern["parameters"]
    bc_cfg = params.get(vp.BLOCK_COUNT_KEY)
    if speech_seconds is None:
        out["reason"] = "no expected speech length - not checked"
        return out
    if bc_cfg is None or not vp.draws_a_value(bc_cfg):
        out["reason"] = (f"{pattern['pattern_id']} orders no block count (its blocks are "
                         f"observed, CF-0310) - nothing to be unreachable")
        return out
    if rhythm_id == vp.HOLD_RHYTHM_ID:
        hold_cfg = params["key_frame_hold_seconds"]
        if not vp.draws_a_value(hold_cfg):
            out["reason"] = "the hold is not drawn - no block ceiling to check against"
            return out
        ceiling, source = float(hold_cfg["max"]), (
            f"{pattern['pattern_id']}'s hold band top (on {vp.HOLD_RHYTHM_ID} the drawn "
            f"hold is a floor, CF-0300)")
        window = None
    else:
        window = vp.hold_draw_band(pattern, rhythm_id, rhythms)
        if window is None:
            out["reason"] = "the hold is not drawn - no block ceiling to check against"
            return out
        ceiling, source = float(window[1]), (
            f"the top of the window {pattern['pattern_id']}/{rhythm_id} draws "
            f"key_frame_hold_seconds from")
    band = (int(bc_cfg["min"]), int(bc_cfg["max"]))
    out.update(speech_fits_band(speech_seconds, ceiling, band))
    out.update(checked=True, block_ceiling_seconds=ceiling, block_ceiling_source=source,
               block_floor_seconds=vp.MIN_BLOCK_SECONDS, block_count_band=list(band))
    if out["fits"]:
        out["reason"] = (f"{speech_seconds:.1f}s of speech cuts into {out['min_blocks']}-"
                         f"{out['max_blocks']} blocks under a {ceiling:.2f}s ceiling, which "
                         f"meets the band {band[0]}-{band[1]}")
        if window is not None:
            # The lowest hold on the draw grid that still cuts the speech into
            # no more than the band's top - the floor the AHS draw went under.
            need = math.ceil(speech_seconds / band[1] / vp.HOLD_GRID - 1e-9) * vp.HOLD_GRID
            floor = round(max(float(window[0]), need), 2)
            if floor > float(window[0]) + 1e-9:
                out["hold_floor_seconds"] = floor
                out["reason"] += (f"; key_frame_hold_seconds has to be drawn at "
                                  f"{floor:.2f}s or more, under it the speech needs more "
                                  f"than {band[1]} blocks")
        return out
    if out["min_blocks"] > band[1]:
        target = round(band[1] * ceiling, 1)
        out["speech_target_seconds"] = target
        if words_per_second:
            out["speech_target_words"] = math.floor(target * float(words_per_second))
        out["reason"] = (f"{speech_seconds:.1f}s of speech under a {ceiling:.2f}s ceiling "
                         f"({source}) is at least {out['min_blocks']} blocks whatever the "
                         f"anchors, the band is {band[0]}-{band[1]}: the speech has to be "
                         f"{target:.1f}s or shorter on this pair")
    else:
        target = round(band[0] * vp.MIN_BLOCK_SECONDS, 1)
        out["speech_target_seconds"] = target
        if words_per_second:
            out["speech_target_words"] = math.ceil(target * float(words_per_second))
        out["reason"] = (f"{speech_seconds:.1f}s of speech is at most {out['max_blocks']} "
                         f"blocks of {vp.MIN_BLOCK_SECONDS}s, under the band's floor of "
                         f"{band[0]}: the speech has to be {target:.1f}s or longer on this pair")
    return out


def _shortfall(fit):
    """How far an unfit pair is from fitting, in seconds of speech - the order
    the fallback ranks pairs by when no pair fits."""
    if fit.get("speech_target_seconds") is None:
        return 0.0
    return abs(fit["expected_speech_seconds"] - fit["speech_target_seconds"])


def choose_pair_for_speech(history, pairs, k, window, fits, exclude=()):
    """The rotation's choice among the pairs that can carry the speech.

    Returns (pair, skipped, exclude, no_fit, rotated_over).

    The expected speech is the channel's, not the script's, so whether a pair
    fits is a property of the pair on this channel for as long as the config
    stands - which makes an unfit pair the same kind of thing as one that is
    not executable today: it is left out of the set the rotation turns over
    (`rotated_over`), and K, the no-repeat window and the skew rule are all
    applied to what is left. Walking past it one draw at a time instead would
    keep it inside k_effective, and with two unfit pairs of eight the window
    would run out of fitting pairs every few draws and hand the unfit ones
    back.

    `skipped` is for the record: the unfit pairs the rotation over every
    eligible pair would have issued, in its own order, before reaching the one
    issued - what this check took away from this draw.

    When no pair the rotation could take fits, nothing is refused: of those
    pairs the one closest to fitting is issued (ties in rotation order) with
    `no_fit` set, and its `speech_fit` carries the speech length to write to.
    """
    exclude = list(exclude)
    fitting = [p for p in pairs if (fits.get(p) or {"fits": True})["fits"]]
    if fitting and [p for p in fitting if p not in exclude]:
        pair = choose_pair(history, fitting, k, window, exclude=exclude)
        skipped, walked = [], list(exclude)
        while True:
            try:
                nxt = choose_pair(history, pairs, k, window, exclude=walked)
            except RotationError:
                break
            if nxt in fitting:
                break
            skipped.append(nxt)
            walked.append(nxt)
        return pair, skipped, exclude, False, fitting
    # Nothing fits: rotate over everything, and of what the rotation could
    # take issue the pair closest to fitting.
    candidates, walked = [], list(exclude)
    while True:
        try:
            nxt = choose_pair(history, pairs, k, window, exclude=walked)
        except RotationError:
            break
        candidates.append(nxt)
        walked.append(nxt)
    if not candidates:
        choose_pair(history, pairs, k, window, exclude=exclude)   # raises, and says why
    best = min(candidates, key=lambda p: (_shortfall(fits[p]), candidates.index(p)))
    # What was passed over for the closer one counts as excluded for the guard:
    # it was not pickable on this draw, exactly like a CF-0286 exclusion.
    skipped = candidates[:candidates.index(best)]
    return best, skipped, exclude + skipped, True, pairs


# --------------------------------------------------------------------------
# assignment and rejection
# --------------------------------------------------------------------------

def assign(channel, batch_id, script_ids, ledger_dir=None, now=None, pipeline_dir=None,
           despite_shortage=False, root=None):
    """`_assign` under the ledger's write lock (CF-0416)."""
    with ledger_locked(_ledger_path(channel, ledger_dir)):
        return _assign(channel, batch_id, script_ids, ledger_dir=ledger_dir, now=now,
                       pipeline_dir=pipeline_dir, despite_shortage=despite_shortage,
                       root=root)


def _assign(channel, batch_id, script_ids, ledger_dir=None, now=None, pipeline_dir=None,
            despite_shortage=False, root=None):
    """Assign a pair to each script. Idempotent per (batch, script) - CF-0383:
    the same id in another batch is another video and gets its own row.

    Re-running it for a script that already has a standing assignment returns
    that assignment untouched rather than making a second one: the CLI is
    called by an agent, and an agent that reruns a step must not be able to
    double-count itself in the distribution.

    It reconciles the production columns first (CF-0049). That is not this
    function's subject and it is here anyway, because assignment is the one
    step of the pipeline that cannot be skipped - see the enrichment section
    for why the enrichment borrows its pressure instead of inventing its own.

    CF-0149: it is also where a topic refused for want of material waits.
    CF-0139 sent such a topic back to the queue and marked its return, but
    nothing stopped the return happening the same minute - and the pool that
    could not supply the pictures a minute ago cannot supply them now, so the
    second attempt walks into the same hole and spends a stage proving it.
    So a script whose latest shortage record is still open is **skipped**, not
    assigned, until the store that record names has grown (`rotation/pool.py`).
    Skipped and not raised: a batch of five topics, one of which is waiting,
    has four topics of work to do, and refusing the other four would be the
    waiting topic spreading.

    The one case that does raise is every offered topic waiting at once. That
    is the batch having nothing to do, and the two wrong answers to it are
    both cheap to fall into: assigning one anyway (a stage spent on a hole
    that is still there) or returning an empty list (a caller that reads it as
    "nothing to do, done" and loops). So nothing is written - the check runs
    before the first append - and the error names every topic, what each waits
    for, and what would change the answer.

    `despite_shortage` overrides the gate. It is for a person who has looked
    at `status` and decided the census is wrong about their pool - not for an
    agent, which is why it is off by default and why the override is printed
    rather than silent. It cannot be used to walk the rotation to a nicer pair
    (the topic comes back on `rotation-after-rejection` either way, and the
    pair is still the rotation's choice), so it opens no door that R3/R4 close.
    """
    cfg = load_channel(channel)
    rot = rotation_config(cfg)
    pairs, blocked = eligible_pairs(cfg)
    if not pairs:
        raise RotationError(
            f"channel {channel}: no pair is executable today; blocked by "
            f"{', '.join(blocking_tasks(blocked)) or 'nothing named'}")
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    _reconcile_before_assigning(channel, ledger_dir, pipeline_dir)
    # CF-0446: every eligible pair against the speech the channel expects.
    speech, speech_source = expected_speech_seconds(cfg)
    fits = _speech_fits(cfg, pairs, speech)
    # CF-0775: a pattern whose base footage a topic does not have (`demo`
    # with no own capture and no api_demo_record) is left out of that topic's
    # draw - a missing-material fact read off the batch's own 01/01b, not a
    # rejection for the writer to make after the draw. Read only when a pair
    # of such a pattern is eligible at all, so other channels read nothing.
    ruled = material.patterns_with_rules(pairs)
    batch_material = _batch_material(channel, batch_id, pipeline_dir) if ruled else None

    # Before the first append, so that "every topic is waiting" leaves the
    # ledger exactly as it was and the error can be raised honestly.
    held = {} if despite_shortage else _held_by_shortage(channel, ledger_dir, root)
    rows_now = ledger.rows()
    # CF-0383: the key is (batch, script) - the same id standing in another
    # batch is another video, not this one already assigned.
    standing_now = [s for s in script_ids
                    if ledger.standing_row_for(s, rows_now, batch_id)]
    fresh = [s for s in script_ids if s not in standing_now]
    # "Nothing to do" is the condition, not "nothing new to do": a script that
    # already carries a standing assignment is work the batch can get on with,
    # and its pair is returned untouched as it always was.
    if fresh and not standing_now and all(s in held for s in fresh):
        raise RotationError(_nothing_to_assign(channel, fresh, held))

    out = []
    for script_id in script_ids:
        rows = ledger.rows()
        existing = ledger.standing_row_for(script_id, rows, batch_id)
        if existing:
            out.append({"script_id": script_id,
                        "pattern_id": existing["pattern_id"],
                        "rhythm_id": existing["rhythm_id"],
                        "assigned_by": existing["assigned_by"],
                        "seq": int(existing["seq"]),
                        "assigned": True,
                        "reassigned": False,
                        "speech_fit": _speech_fit_record(
                            fits.get((existing["pattern_id"], existing["rhythm_id"])),
                            speech_source)})
            continue
        if script_id in held:
            w = held[script_id]
            out.append({"script_id": script_id, "assigned": False,
                        "awaiting_pool": True, "state": w["state"],
                        "refused_at_seq": w["seq"], "causes": w["causes"],
                        "retry_when": w["retry_when"], "pool_says": w["pool_says"]})
            continue
        history = [(r["pattern_id"], r["rhythm_id"]) for r in ledger.standing_rows(rows)]
        # CF-0286: a rhythm this script's own upheld rejection took off the
        # table stays off it. Without this the exclusion would last exactly one
        # draw: a topic refused for want of material (CF-0139) comes back
        # through here, not through `reject`, and would be handed the very
        # rhythm the guard already agreed its fact cannot carry.
        # CF-0784: a re-run's (`rerun-from`) closed run is not this script's
        # history - neither its exclusions nor its rejections below count.
        closed_run = ledger.closed_run_seqs(rows)
        dropped = rhythms_excluded_for(script_id, rows, batch_id, skip_seqs=closed_run)
        missing = batch_material.undeliverable(script_id, ruled) if batch_material else {}
        exclude = sorted(set(pairs_carrying(pairs, dropped))
                         | set(pairs_of_patterns(pairs, missing)))
        if exclude and not [p for p in pairs if p not in exclude]:
            why = []
            if dropped:
                why.append(f"a rhythm this script's own upheld rejection excluded "
                           f"({', '.join(dropped)}) - what CF-0286 exists to stop")
            if missing:
                why.append("a pattern the topic has no base footage for (" +
                           "; ".join(f"{k}: {v}" for k, v in sorted(missing.items())) +
                           ") - CF-0775")
            raise RotationError(
                f"{script_id}: every eligible pair carries " + ", or ".join(why) +
                f". There is nothing left to assign it. This is the channel's allowed "
                f"pattern list against this topic, and it needs a person: widen the list, "
                f"or take the topic out")
        pair, speech_fit, _ = _draw_for_speech(history, pairs, rot, fits, speech_source,
                                               exclude, f"the rotation's own choice for {script_id}")
        # CF-0139 point 3: a topic that comes back after an upheld rejection -
        # the agent's, or the planner's refusal for want of material - is
        # assigned again like any other, and says so. `rotation-after-rejection`
        # is the existing form; `reject()` writes it on the replacement it
        # picks itself, and a refusal picks none, so the marking has to happen
        # here or the second attempt would read as a first one.
        returning = any(r["rejected_at"]
                        for r in history_of_script(script_id, rows, batch_id)
                        if r["seq"] not in closed_run)
        by = "rotation-after-rejection" if returning else "rotation"
        row = ledger.append(channel=channel, batch_id=batch_id, script_id=script_id,
                            pattern_id=pair[0], rhythm_id=pair[1], assigned_by=by,
                            assigned_at=now or utc_now())
        result = {"script_id": script_id, "pattern_id": pair[0], "rhythm_id": pair[1],
                  "assigned_by": by, "seq": int(row["seq"]), "assigned": True,
                  "reassigned": True, "speech_fit": speech_fit}
        if missing:
            result["material_excluded"] = dict(sorted(missing.items()))
        out.append(result)
    return out


def _draw_for_speech(history, pairs, rot, fits, speech_source, exclude, what):
    """The one draw every path that issues a pair goes through (CF-0446):
    `assign` and the replacement after an upheld rejection alike.

    A pair that cannot carry the expected speech inside its block band is left
    out of the set the rotation turns over (`choose_pair_for_speech`), the
    guard is asked about the set that was actually turned over, and the
    `speech_fit` record is built here so that no path can issue a pair without
    one. Returns (pair, speech_fit, rotated_over) - the last is the set the
    rotation turned over, which is what an even window is even across (R8)."""
    k, window = rot["no_repeat_window_k"], rot["distribution_window"]
    pair, skipped, exclude, no_fit, rotated_over = choose_pair_for_speech(
        history, pairs, k, window, fits, exclude=exclude)
    violations = check_assignment(pair, history, rotated_over, k, window, exclude=exclude)
    if violations:
        raise RotationError(f"the guard refused {what}:\n  " + "\n  ".join(violations))
    return pair, _speech_fit_record(fits.get(pair), speech_source,
                                    skipped=[fits[p] for p in skipped if p != pair],
                                    no_fit=no_fit), rotated_over


def _speech_fits(cfg, pairs, speech):
    """{pair: pair_speech_fit report} for every eligible pair. CF-0446."""
    if speech is None:
        return {}
    patterns, rhythms = vp.load_patterns(), vp.load_rhythms()
    wps = (cfg.get(vp.NARRATION_BUDGET_KEY) or {}).get("words_per_second")
    return {p: pair_speech_fit(patterns[p[0]], p[1], speech, rhythms, words_per_second=wps)
            for p in pairs}


def _speech_fit_record(fit, source, skipped=(), no_fit=False):
    """What the assignment says about the speech it was checked against. CF-0446.

    `skipped` names every pair the rotation walked past and why; `no_fit` says
    no pair the rotation could take fits, so this one is issued with the speech
    length it needs (`speech_target_seconds`/`_words`) - an order to the writer,
    not a refusal."""
    if fit is None:
        return {"checked": False, "reason": source}
    rec = dict(fit)
    rec["expected_speech_source"] = source
    rec["skipped"] = [{"pair": f["pair"], "reason": f["reason"],
                       **({"speech_target_seconds": f["speech_target_seconds"]}
                          if "speech_target_seconds" in f else {})}
                      for f in skipped]
    rec["no_compatible_pair"] = bool(no_fit)
    if no_fit:
        rec["note"] = ("no pair the rotation could issue fits the expected speech; this is "
                       "the closest, and the script has to be written to "
                       f"{rec.get('speech_target_seconds')}s"
                       + (f" (~{rec['speech_target_words']} words)"
                          if rec.get("speech_target_words") else "")
                       + " for it to be cut inside the band")
    return rec


def _held_by_shortage(channel, ledger_dir=None, root=None):
    """{script_id: the waiting entry} for every topic the gate holds.

    One source of truth with `status`: both read `awaiting_material()`, so the
    line an operator is shown and the decision the gate makes cannot disagree.
    """
    return {w["script_id"]: w
            for w in awaiting_material(channel, ledger_dir, root=root)
            if not w["assignable"]}


def _nothing_to_assign(channel, scripts, held):
    """The edge case CF-0149 point 4 refused to leave unsaid: every topic on
    offer is waiting for the same pool."""
    lines = [f"channel {channel}: all {len(scripts)} topic(s) offered are waiting for "
             f"the pool to be topped up, so nothing was assigned and nothing was "
             f"written (CF-0149). One of them assigned anyway would spend a stage on "
             f"a hole that is still there; an empty list returned quietly would read "
             f"as 'nothing to do' to a caller that then runs the batch on no topics."]
    for script_id in scripts:
        w = held[script_id]
        lines.append(f"  {script_id} (refused at seq {w['seq']}, {w['refused_at']})")
        lines.append(f"      waits for: {w['retry_when']}")
        lines.append(f"      the pool : {w['pool_says']}")
    lines.append("What changes the answer: material into shared/footage/ (the footage "
                 "ingest, CF-0099) or entries into shared/inserts/ (the insert library, "
                 "CF-0114) - which one, per topic, is the line above. "
                 f"`rotation/rotate.py status {channel}` shows the same list at any "
                 "time. A person who has looked and disagrees can pass "
                 "--despite-shortage; an agent may not decide that for itself.")
    return "\n".join(lines)


def rule_on_rejection(channel, script_id, reason, ledger_dir=None, rejects_rhythm=False,
                      batch_id=None, pipeline_dir=None, batch_dir=None):
    """The guard's ruling on a rejection. Read-only - decides, does not write.

    Returns {verdict, explanation, replacement, rule, excluded_rhythm}. The
    rules, and why each one exists, because each closes a way of turning the
    valve into free choice:

      R1  there has to be a standing assignment to reject.
      R2  a written reason, and one long enough to be a reason. The reason is
          the price of the valve and it is also data: a pattern refused half
          the time is badly designed, and that is visible here long before the
          Analyst exists to notice it.
      R3  one rejection per script. Without it an agent walks the rotation one
          rejection at a time until its favourite pair comes up - free choice
          by exhaustion.
      R4  the same pair may be refused at most once inside the distribution
          window. Without it an agent that dislikes a pattern refuses it every
          single time it is offered; because a rejected assignment does not
          count towards the distribution, that pattern stays permanently the
          least-used one, is permanently offered first, and is permanently
          refused - it disappears from the channel while the ledger fills with
          refusals. The second refusal of the same pair inside a window is not
          a statement about a script any more, it is a statement about the
          pattern's design, and that is a decision for a person and a task.
      R5  there has to be somewhere to fall back to. In the single-pair state
          before CF-0041 there is not, and the ruling is a denial that names
          the blocking task - not an error, and not an empty assignment.
      R6  taking this row out must not retroactively break either guarantee -
          the no-repeat window or the even distribution - for assignments that
          already stand. A rejection deletes an element from the standing
          sequence, which pulls everything after it one step closer to
          everything before it: a pair that sat exactly K apart ends up inside
          K of itself, and a window that was even ends up two uses apart. The
          breakage is caused by an assignment nobody made, which is why it is
          ruled on here rather than found in the ledger a month later. It only
          arises when the refused assignment is not the most recent one, i.e.
          when a whole batch was assigned up front and refused afterwards;
          ruling on each assignment before the next script is assigned - what
          the Content Researcher skill tells the agent to do - never trips it.
      R7  (CF-0286, only when `rejects_rhythm`) there has to be somewhere to
          fall back to that does not carry the refused rhythm. R5 asks whether
          another *pair* exists; this asks whether another *rhythm* does, and
          it is a separate rule because the two states need different answers
          from a person: R5 waits for a task that makes a rhythm executable,
          R7 says this channel's allowed patterns all want the thing this fact
          does not have.
      R8  (CF-0526) the replacement must not skew the window it completes. R6
          is the removal half of a rejection; this is the other half. The
          fallback is the least-used *pickable* pair, and the pickable set has
          two holes in it the soft rule cannot see past: the refused pair
          (excluded) and the last k_effective - 1 standing pairs (the hard
          no-repeat filter). The window of `distribution_window` rows that the
          replacement completes holds `window - 1` rows already, so some pairs
          sit one use short of the rest; when every one of those short pairs
          is in a hole - the refused one plus the ones just assigned - every
          pickable pair is already at the top, and whichever is handed back
          lands that window two uses apart. Found by CF-0525 as
          [4,4,4,4,4,4,4,2]; reproduced on synthetic batch sizes by CF-0526
          (`test_the_replacement_may_not_skew_the_window_it_completes`). It is
          a defect of the guard, not a property of the rule: the even window
          is one of the two guarantees R6 already defends, and the hole was
          that the replacement was checked only against what was pickable
          (`check_assignment`, rightly, for a draw) and never against the
          window. The answer is the one R6 gives: the assignment stands.
          The same shape can also be set up for later: a rejection inside a
          batch reorders the standing sequence, and the short pairs can end up
          exactly where the rotation's own next draws will have them banned,
          so the skew surfaces several plain assignments on, not at the
          replacement (CF-0526's sweep: [2,7,3,2]). Those draws are
          deterministic, so R8 plays one window of them forward and denies a
          rejection whose skew is already decided. In serial order - the
          refused row is always the newest - it changed nothing on CF-0526's
          sweep (identical histories); batch-at-once, it took every skewed
          window out.

    `rejects_rhythm` (CF-0286) is what The Traitors needed and did not have.
    `contrast`/`alternate` was refused because the fact has no second side a
    viewer can tell apart; the rejection was upheld and the rotation handed
    back `explainer`/`alternate`, a different pattern with the same rhythm and
    therefore the same demand, and the script died at the Video Editor twice.
    With the flag, the replacement draw excludes every pair carrying that
    rhythm rather than only the pair that was refused.

    It loosens nothing. R1-R5 judge this rejection exactly as they judge any
    other - in particular R2 measures the agent's own words, because the
    exclusion marker is written afterwards by the guard and cannot pay for a
    shorter reason - and the exclusion is a *consequence* of the ruling, not an
    input to it: a denied rejection excludes nothing at all, and nothing about
    the flag reaches the draw unless the verdict is `upheld`. Nor is it a way
    to steer: `exclude` only ever removes candidates, the replacement is still
    the least-used pair of what is left, and R3 still allows one ruling per
    script - so the flag can buy a script out of a rhythm, which is the whole
    point, and can never buy it into a pattern.

    CF-0775 - the missing-material case. When the refused pattern is one the
    topic has no base footage for (`rotation/material.py`, read off the
    batch's own 01/01b: `demo` with no own capture and no api_demo_record),
    the rejection is not taste and is not judged as taste. The guard checks
    the claim itself - the agent's words buy nothing here, the batch's files
    do - and then: R3 does not count rulings on the script's *other* rows
    (an earlier upheld rejection that handed back the same pattern on another
    rhythm, 0839Z's -005), R4 is not asked (0839Z's -013 was denied because
    -005 had refused the same pair for the same missing base), and R6/R8 are
    not a veto - denying it would leave the ledger claiming a video stands
    that nobody can build, the reasoning `refuse` already follows. The
    replacement is drawn with every pair of every pattern the topic has no
    base for excluded (R9 denies only when that leaves nothing), and the row
    is stored with the `[undeliverable pattern: <id>]` marker, which is how
    R4 leaves such a refusal out of the next topic's count.
    """
    cfg = load_channel(channel)
    rot = rotation_config(cfg)
    pairs, blocked = eligible_pairs(cfg)
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    rows = ledger.rows()

    # CF-0383: `batch_id` names which batch's video is rejected; without it the
    # id alone must be unambiguous, and the ledger raises if it is not.
    try:
        row = ledger.standing_row_for(script_id, rows, batch_id)
    except LedgerError as exc:
        raise RotationError(f"{exc}: pass --batch-id (or --batch DIR)") from exc
    if row is None:                                                     # R1
        raise RotationError(
            f"{(batch_id + '/') if batch_id else ''}{script_id} has no standing "
            f"assignment to reject in {ledger.path}")

    def denied(explanation, rule):
        return {"verdict": "denied", "explanation": explanation, "replacement": None,
                "rule": rule, "excluded_rhythm": None, "undeliverable_pattern": None,
                "speech_fit": None, "row": row}

    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_CHARS:                                  # R2
        raise RotationError(
            f"a rejection needs a written reason about this script (at least "
            f"{MIN_REASON_CHARS} characters); got {reason!r}. The reason is the price of "
            f"being allowed to refuse, and it is the data that shows a badly designed "
            f"pattern before anything else does")

    # CF-0775: is the refused pattern one this topic has no base for?
    missing = {}
    if row["pattern_id"] in material.RULES:
        missing = _batch_material(channel, row["batch_id"], pipeline_dir,
                                  batch_dir).undeliverable(
            script_id, material.patterns_with_rules(pairs))
    material_case = row["pattern_id"] in missing
    closed_run = ledger.closed_run_seqs(rows)

    if material_case:
        if row["rejection_verdict"]:                                    # R3 (the row)
            return denied(
                f"seq {row['seq']} already carries a {row['rejection_verdict']!r} ruling and "
                f"a ledger cell only goes from empty to filled - the missing base "
                f"({missing[row['pattern_id']]}) cannot be written onto it. This needs a "
                f"person", "R3")
    elif any(r["rejection_verdict"]                                     # R3
             for r in history_of_script(script_id, rows, row["batch_id"])
             if r["seq"] not in closed_run):                  # CF-0781: a re-run's past
        return denied(
            f"{script_id} has already been ruled on once. One rejection per script: an agent "
            f"that may reject repeatedly walks the rotation until its preferred pair comes "
            f"up, which is the free choice this mechanism exists to remove", "R3")

    pair = (row["pattern_id"], row["rhythm_id"])
    window_rows = rows[-rot["distribution_window"]:]
    prior = [r for r in window_rows
             if r["rejected_at"] and (r["pattern_id"], r["rhythm_id"]) == pair
             and not undeliverable_pattern(r)]            # CF-0775: material, not taste
    if prior and not material_case:                                     # R4
        return denied(
            f"{pair[0]}/{pair[1]} was already refused at seq {prior[-1]['seq']}, inside the "
            f"last {rot['distribution_window']} assignments. A pair refused twice in one "
            f"window is a statement about the pattern, not about a script - take it out of "
            f"the channel's allowed list or fix the pattern, with a task, rather than "
            f"refusing it case by case", "R4")

    # The history the replacement is chosen against is the standing history
    # with the refused row taken out - it is about to stop standing. Taking it
    # out by seq rather than by position matters: a batch assigns several
    # scripts at once, and the one being refused is usually not the last.
    standing = ledger.standing_rows(rows)
    position = [r["seq"] for r in standing].index(row["seq"])
    history = [(r["pattern_id"], r["rhythm_id"])
               for r in standing if r["seq"] != row["seq"]]
    k_eff = effective_k(rot["no_repeat_window_k"], pairs)

    damage = _removal_damage(history, position, pairs, k_eff,            # R6
                             rot["distribution_window"])
    if damage and not material_case:
        return denied(
            f"assignments made after this one already stand on it: taking seq {row['seq']} out "
            f"would leave {damage}, which nobody assigned. Reject an assignment before the "
            f"rest of the batch is assigned, or let this one stand", "R6")

    banned = set(history[-(k_eff - 1):]) if k_eff > 1 else set()
    alternatives = [p for p in pairs if p != pair and p not in banned]
    if not alternatives:                                                # R5
        blockers = ", ".join(blocking_tasks(blocked)) or "nothing named"
        return denied(
            f"there is no other pair to fall back to: {len(pairs)} pair(s) are executable "
            f"today and the rest wait on {blockers}. The assignment stands - refusing it "
            f"would leave the script unwritten, and the fallback is never the agent's choice", "R5")

    # CF-0286. The refused pair is always excluded; with `rejects_rhythm` so is
    # every other pair carrying its rhythm, which is the whole change - the
    # rotation was handing the same demand back under another pattern's name.
    rhythm = pair[1] if rejects_rhythm else None
    exclude = sorted({pair} | set(pairs_carrying(pairs, [rhythm] if rhythm else []))
                     | set(pairs_of_patterns(pairs, missing)))

    if material_case and not [p for p in alternatives if p not in exclude]:   # R9
        return denied(
            f"{pair[0]} cannot be delivered for this topic ({missing[pair[0]]}), and every "
            f"pair left to fall back to is excluded too ("
            + ", ".join(f"{a}/{b}" for a, b in sorted(alternatives)) + "). The assignment "
            f"stands because there is nothing to hand back; this is the channel's allowed "
            f"patterns against this topic, and it needs a person", "R9")

    if rhythm and not [p for p in alternatives if p[1] != rhythm]:       # R7
        carrying = ", ".join(f"{a}/{b}" for a, b in sorted(
            p for p in alternatives if p[1] == rhythm))
        windowed = sorted(p for p in pairs
                          if p != pair and p[1] != rhythm and p in banned)
        aside = ""
        if windowed:
            aside = (" (the pair(s) that do not - " +
                     ", ".join(f"{a}/{b}" for a, b in windowed) +
                     f" - are inside the no-repeat window of {k_eff})")
        return denied(
            f"the rhythm `{rhythm}` is what was refused, and every pair left to fall back "
            f"to carries it: {carrying}{aside}. The assignment stands, because handing back "
            f"another pattern on the same rhythm is the defect CF-0286 closed and there is "
            f"nothing else to hand back. This is a statement about the channel's allowed "
            f"patterns against this fact, not about the script: it needs a person and a "
            f"task, the way R4 and R5 do",
            "R7")

    # CF-0446: the replacement is drawn the way `assign` draws - over the pairs
    # that can carry the channel's expected speech - so a rejection cannot hand
    # back the pair the issue check keeps out of the rotation.
    speech, speech_source = expected_speech_seconds(cfg)
    replacement, speech_fit, rotated_over = _draw_for_speech(
        history, pairs, rot, _speech_fits(cfg, pairs, speech), speech_source, exclude,
        f"the fallback for {script_id}")

    # CF-0526. R6 covered the removal half of a rejection; this is the other
    # half - the replacement row and the window it completes.
    skew = _replacement_skew(history, replacement, rotated_over,                # R8
                             rot["no_repeat_window_k"], rot["distribution_window"])
    if skew and not material_case:
        return denied(
            f"there is no fallback that keeps the pool even: the rotation would hand back "
            f"{replacement[0]}/{replacement[1]}, and {skew}. The pairs short there are ones "
            f"the draw may not take - the refused one, those excluded with it, those inside "
            f"the no-repeat window of {k_eff}. The assignment stands - refusing it would skew "
            f"the pool through assignments nobody chose, as R6 says of a removal", "R8")
    if material_case:
        return {"verdict": "upheld",
                "explanation": (f"upheld as missing material (CF-0775): {pair[0]} has no base "
                                f"for this topic - {missing[pair[0]]}; the fallback is the "
                                f"next pair in the rotation with every pair of " +
                                ", ".join(sorted(missing)) + " excluded" +
                                (f" and every pair on `{rhythm}`" if rhythm else "") +
                                ("" if not (damage or skew) else
                                 f" (the window cost, not a veto here: {damage or skew})")),
                "replacement": replacement, "rule": None, "excluded_rhythm": rhythm,
                "undeliverable_pattern": pair[0], "material": dict(sorted(missing.items())),
                "speech_fit": speech_fit, "row": row}
    return {"verdict": "upheld",
            "explanation": ("upheld; the fallback is the next pair in the rotation" +
                            (f", and every pair on `{rhythm}` was excluded from the draw"
                             if rhythm else "") +
                            ("; no pair left fits the expected speech - this one is the "
                             "closest, written to its speech target"
                             if speech_fit.get("no_compatible_pair") else "")),
            "replacement": replacement, "rule": None, "excluded_rhythm": rhythm,
            "speech_fit": speech_fit, "row": row}


def reject(channel, script_id, reason, ledger_dir=None, now=None, rejects_rhythm=False,
           batch_id=None, pipeline_dir=None, batch_dir=None):
    """`_reject` under the ledger's write lock (CF-0416): the ruling reads the
    ledger and then writes it, and a second writer in between would be ruled on
    a history that is no longer the file's."""
    with ledger_locked(_ledger_path(channel, ledger_dir)):
        return _reject(channel, script_id, reason, ledger_dir=ledger_dir, now=now,
                       rejects_rhythm=rejects_rhythm, batch_id=batch_id,
                       pipeline_dir=pipeline_dir, batch_dir=batch_dir)


def _reject(channel, script_id, reason, ledger_dir=None, now=None, rejects_rhythm=False,
            batch_id=None, pipeline_dir=None, batch_dir=None):
    """Rule on a rejection and write the ruling. Returns the ruling.

    `rejects_rhythm` (CF-0286) says the rhythm is what does not fit, not only
    the pair. The ruling decides whether that has any effect at all: on a
    denial nothing is excluded and the reason is written exactly as the agent
    wrote it, so a rejection that was not upheld cannot take a rhythm off the
    table. On an upheld one the reason is stored with the guard's exclusion
    marker in front of it, which is what makes the exclusion outlive this call.
    """
    ruling = rule_on_rejection(channel, script_id, reason, ledger_dir,
                               rejects_rhythm=rejects_rhythm, batch_id=batch_id,
                               pipeline_dir=pipeline_dir, batch_dir=batch_dir)
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    row = ruling["row"]
    stamp = now or utc_now()

    if ruling["verdict"] == "denied":
        # Recorded on the standing row, not as a row of its own: nothing about
        # the distribution changed, and a row per denial would let a refused
        # agent inflate the ledger and double-count its script.
        if not row["rejection_verdict"]:
            ledger.enrich(row["seq"], rejection_reason=reason.strip(),
                          rejection_verdict="denied")
        ruling["assignment"] = {"script_id": script_id, "pattern_id": row["pattern_id"],
                                "rhythm_id": row["rhythm_id"], "seq": int(row["seq"])}
        return ruling

    ledger.enrich(row["seq"],
                  rejection_reason=mark_pattern_undeliverable(
                      mark_rhythm_excluded(reason.strip(), ruling["excluded_rhythm"]),
                      ruling.get("undeliverable_pattern")),
                  rejection_verdict="upheld", rejected_at=stamp)
    pair = ruling["replacement"]
    new = ledger.append(channel=channel, batch_id=row["batch_id"], script_id=script_id,
                        pattern_id=pair[0], rhythm_id=pair[1],
                        assigned_by="rotation-after-rejection", assigned_at=stamp)
    ruling["assignment"] = {"script_id": script_id, "pattern_id": pair[0],
                            "rhythm_id": pair[1], "seq": int(new["seq"]),
                            "speech_fit": ruling["speech_fit"]}
    return ruling


def refuse(channel, script_id, reason, deficit=None, deficit_path=None,
           ledger_dir=None, now=None, root=None, batch_id=None):
    """`_refuse` under the ledger's write lock (CF-0416)."""
    with ledger_locked(_ledger_path(channel, ledger_dir)):
        return _refuse(channel, script_id, reason, deficit=deficit,
                       deficit_path=deficit_path, ledger_dir=ledger_dir, now=now, root=root,
                       batch_id=batch_id)


def _refuse(channel, script_id, reason, deficit=None, deficit_path=None,
            ledger_dir=None, now=None, root=None, batch_id=None):
    """CF-0139: the planner's refusal - the third thing that can happen to a row.

    A row had two ends until now: it lives to a `produced_at`, or the agent
    rejects the assignment and the guard rules on it. A video the planner
    refuses to build is neither. Nothing was wrong with the assignment - the
    pair was drawn correctly, the script was written to it, and the pool then
    could not supply the pictures. CF-0137 rung 4: `build_render_plan.py`
    exits 2 and writes `plan.assetless-rung.json` instead of a plan.

    It is written as an ordinary rejection and nothing else - `rejection_reason`,
    `rejection_verdict: upheld`, `rejected_at` - because that is already the
    shape of "an event without a continuation, excluded from every distribution
    count", which is exactly what this is. CF-0139 rejected a
    `production_failed_at` column: the difference between a bad script and a
    short pool reads from the reason, and a column would be a migration plus a
    new branch in every counter. The alternative - leaving the row standing
    with no outcome - was rejected on sight: CF-0040 built its guard on every
    row having one.

    Three differences from `reject()`, and each one follows from the refusal
    being a fact rather than a request:

      * **no replacement is assigned.** `reject()` hands the script the next
        pair in the rotation, because the objection was to the pair. Here the
        pair is innocent and the pool has not changed since the plan was
        refused a minute ago, so a second attempt walks into the same hole.
        The topic leaves the ledger with no standing row and waits in the
        queue; when it is assigned again - after the pool is topped up - the
        row says `rotation-after-rejection`, which `assign` now writes on its
        own for any script coming back from an upheld refusal.
      * **the guard's taste rules do not apply.** R3 (one rejection per
        script) and R4 (one refusal of a pair per window) exist to stop an
        agent walking the rotation to a pair it likes. This path chooses no
        pair at all, so there is nothing to walk to. R6 (removal damage) is
        not a veto here either - a refusal cannot be denied, because denying
        it would leave the ledger claiming a video stands that no one can
        build. The damage R6 would have named is measured and written into
        the shortage record instead of being used to refuse the refusal.
      * **a machine-readable deficit is required**, and it is the price of
        this path the way the written reason is the price of `reject()`.
        Without it "the pool was short" is an unfalsifiable sentence that
        buys an agent out of any assignment; with it the refusal names the
        blocks, and the shortage log says whether topping up the pool would
        change the answer (`rotation/shortage.py`).
    """
    if deficit is None:
        if not deficit_path:
            raise RotationError(
                f"refusing {script_id} for want of material needs the planner's deficit "
                f"(plan.assetless-rung.json) - a refusal on prose alone is an opinion, and "
                f"opinions about a pair go through `reject` (CF-0139)")
        deficit = shortage.read_deficit(deficit_path)

    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_CHARS:
        raise RotationError(
            f"a refusal needs a written reason about this video (at least "
            f"{MIN_REASON_CHARS} characters); got {reason!r}. The prose says what a person "
            f"has to know; the deficit beside it says what a program has to know")

    ledger = Ledger(_ledger_path(channel, ledger_dir))
    rows = ledger.rows()
    try:
        row = ledger.standing_row_for(script_id, rows, batch_id)       # CF-0383
    except LedgerError as exc:
        raise RotationError(f"{exc}: pass --batch-id") from exc
    if row is None:
        raise RotationError(
            f"{(batch_id + '/') if batch_id else ''}{script_id} has no standing "
            f"assignment to refuse in {ledger.path}")
    if row["rejection_verdict"]:
        raise RotationError(
            f"seq {row['seq']} already carries a {row['rejection_verdict']!r} rejection "
            f"({row['rejection_reason']!r}). A denied rejection leaves the assignment "
            f"standing and its reason on the row, and the ledger's cells only ever go "
            f"from empty to filled - so this row cannot also record a refusal. This needs "
            f"a person: the video cannot be built and the row cannot say so")

    anchors = shortage.anchors_from_deficit(deficit)
    stamp = now or utc_now()

    # What R6 would have measured. Recorded, not enforced - see the docstring.
    damage = None
    try:
        cfg = load_channel(channel)
        rot = rotation_config(cfg)
        pairs, _ = eligible_pairs(cfg)
        standing = ledger.standing_rows(rows)
        position = [r["seq"] for r in standing].index(row["seq"])
        history = [(r["pattern_id"], r["rhythm_id"])
                   for r in standing if r["seq"] != row["seq"]]
        damage = _removal_damage(history, position, pairs,
                                 effective_k(rot["no_repeat_window_k"], pairs),
                                 rot["distribution_window"])
    except (RotationError, LedgerError, ValueError):
        damage = None

    record = shortage.build(
        seq=int(row["seq"]), channel=channel, batch_id=row["batch_id"],
        script_id=script_id, anchors=anchors, refused_at=stamp, reason=reason,
        source=str(deficit_path or ""), root=root)
    record["pattern_id"] = row["pattern_id"]
    record["rhythm_id"] = row["rhythm_id"]
    record["distribution_damage"] = damage or ""

    # The log first: a ledger row saying "refused for want of material" with no
    # record of what was missing is the prose-only refusal this path refuses to
    # take. If the log write fails, nothing has been written at all.
    log = shortage.ShortageLog(_shortage_log_path(channel, ledger_dir))
    log.append(record)
    ledger.enrich(row["seq"], rejection_reason=reason,
                  rejection_verdict="upheld", rejected_at=stamp)

    return {"verdict": "upheld", "script_id": script_id, "seq": int(row["seq"]),
            "pattern_id": row["pattern_id"], "rhythm_id": row["rhythm_id"],
            "replacement": None, "shortage": record, "log": str(log.path),
            "explanation": (
                "refused for want of material (CF-0139): the assignment is closed, no "
                "replacement is assigned, and the topic waits in the queue until the "
                "pool can answer it - " + record["retry_when"])}


def awaiting_material(channel, ledger_dir=None, now_census=None, root=None):
    """Topics closed by a refusal that have not been assigned again, and
    whether what each waits for has arrived.

    The queue side of CF-0139 point 3 and the whole of CF-0149, read-only.
    CF-0139 could only say what would have to arrive; the census in
    `rotation/pool.py` says whether it did, so every entry now carries a
    `state` (`arrived` / `waiting` / `not-a-pool-question` / `no-baseline`)
    and the numbers behind it. `assign` reads exactly this and refuses on it -
    there is one answer and one place it is computed, so `status` cannot say
    one thing while the gate does another.

    A topic refused more than once is answered by its **latest** record: the
    earlier refusal's baseline is a pool two refusals old, and comparing
    against it would release the topic on growth it has already been shown
    not to be enough.
    """
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    rows = ledger.rows()
    log = shortage.ShortageLog(_shortage_log_path(channel, ledger_dir))
    try:
        records = log.records()
    except shortage.ShortageError:
        records = []
    # CF-0383: back in the rotation means standing *after* the refusal. A row
    # of the same id standing before it is another batch's video (two batches
    # of one day, a repeat and its parent), and is not this topic's return.
    last_standing = {}
    for r in ledger.standing_rows(rows):
        last_standing[r["script_id"]] = max(int(r["seq"]),
                                            last_standing.get(r["script_id"], 0))
    latest = {}
    for rec in records:
        sid = rec.get("script_id")
        if last_standing.get(sid, 0) > int(rec.get("seq", 0)):
            continue          # already back in the rotation
        if sid not in latest or int(rec.get("seq", 0)) > int(latest[sid].get("seq", 0)):
            latest[sid] = rec

    if now_census is None and latest:
        wanted = sorted({s for rec in latest.values()
                         for s in pool.stores_for(rec.get("causes"))})
        now_census = pool.census(root, stores=wanted)

    out = []
    for rec in sorted(latest.values(), key=lambda r: int(r.get("seq", 0))):
        state = pool.arrival(rec, now=now_census, root=root)
        out.append({"script_id": rec.get("script_id"), "seq": rec.get("seq"),
                    "batch_id": rec.get("batch_id"),
                    "refused_at": rec.get("refused_at"),
                    "pool_fixable": rec.get("pool_fixable"),
                    "causes": rec.get("causes") or {},
                    "retry_when": rec.get("retry_when") or "",
                    "state": state["state"],
                    "assignable": state["assignable"],
                    "stores": state["stores"],
                    "pool_says": state["says"]})
    return out


# --------------------------------------------------------------------------
# enrichment, and the forcing function it did not have (CF-0049)
# --------------------------------------------------------------------------
#
# Assignment cannot be skipped: Content Researcher has no other way to obtain
# a pair, so those columns fill themselves. Production had no such pressure.
# `produced` returns nothing anyone downstream needs today, there is no
# orchestrator to call it, and a skipped call leaves an empty cell - which is
# also exactly what a row that has not been produced yet looks like. The skip
# breaks nothing and is therefore invisible, which is the same class of defect
# as CF-0048 and CF-0055: not a wrong value, an unnoticed one.
#
# A complaint would not have fixed it. `status` shouting into a run nobody is
# watching is a notification, not a guarantee.
#
# What makes it fixable is that the enrichment is *derivable*: the production
# columns are a pure function of 05-video-editor.json, which is a durable file
# on disk. So it does not have to happen at the moment of production at all -
# it has to have happened before that file goes away, and that deadline is
# real and dated: scripts/monthly_archive.py zips batches older than 30
# days onto Archive and deletes them here (CF-0358; before it
# archive_old_batches.sh moved them with `mv`). Hence, in order of strength:
#
#   * the rotation reconciles itself with the pipeline every time it assigns.
#     Assignment is the step that cannot be skipped, so the enrichment
#     inherits its forcing function instead of inventing one, and the ledger
#     can never fall more than one batch behind. It acts rather than warns,
#     which is the whole difference in an unattended run.
#   * `backfill` does the same on demand over every batch still on disk, and
#     `backfill --check` is its machine-readable form: report, write nothing,
#     exit non-zero. That is what a caller about to destroy a batch asks
#     first, and since CF-0056 the archive job is that caller: it runs
#     `backfill <channel>` before the first batch it is due to move and skips
#     the whole channel, in writing, if `--check` then still exits non-zero.
#     So the deadline is now guarded at the deadline itself, by the process
#     that sets it.
#   * `status` names what is left, because one kind of gap is not recoverable
#     by any of this and must not be quietly rounded off.
#
# What none of it may do is invent an assignment. A batch produced before the
# rotation existed has no row, and the pair it was cut to is written nowhere;
# appending a row for it would drop a pair nobody assigned into the history
# the guard counts - the precise falsification the append-only invariant
# exists to prevent. Those are reported as unrecorded, for as long as they are
# on disk, and left alone.


def batch_metadata(channel, batch_id, pipeline_dir=None):
    """Video Editor's file for one batch as (meta, path); meta is None if the
    file is not there - not produced yet, or produced and archived away.

    Searched under every name the channel's directories carry (see
    FORMER_CHANNEL_IDS); the path reported when nothing is found is the one
    under the current id, because that is where a new batch would be."""
    root = Path(pipeline_dir or PIPELINE_DIR)
    candidates = [root / n / batch_id / "05-video-editor.json"
                  for n in channel_names(channel)]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text()), path
    return None, candidates[0]


def record_produced(channel, batch_id, ledger_dir=None, pipeline_dir=None):
    """Fill the production columns from Video Editor's own file.

    pattern_delivered / rhythm_delivered are read if present and left empty if
    not: batches cut before CF-0041 do not carry them, and an empty cell is
    the honest record that nobody checked whether the delivered cut is still
    the rhythm it was ordered as.

    A cell already holding the same value is a no-op, so this is idempotent
    and re-running it costs nothing; rows that were already recorded come back
    under `already` rather than `filled`, so that "filled" means a cell that
    actually changed and a report of work is not a report of a re-read. A cell
    holding a *different* value is
    collected into `conflicts` instead of raised: this runs inside `assign`
    now, and a bookkeeping disagreement about one row must not be able to stop
    the factory from assigning the next batch, nor to hide the rows behind it.
    The conflict stays in `status` until a person settles it.
    """
    meta, path = batch_metadata(channel, batch_id, pipeline_dir)
    if meta is None:
        raise RotationError(f"no {path} - nothing has been produced for this batch yet")
    ledger = Ledger(_ledger_path(channel, ledger_dir))

    filled, already, unassigned, conflicts = [], [], [], []
    for video in meta.get("videos", []):
        rows = ledger.rows()
        row = ledger.standing_row_for(video["script_id"], rows, batch_id)   # CF-0383
        if row is None:
            unassigned.append(video["script_id"])
            continue
        was_blank = not row["produced_at"]
        try:
            ledger.enrich(row["seq"],
                          produced_at=meta.get("generated_at", "") or utc_now(),
                          video_path=video.get("output_path", ""),
                          pattern_delivered=video.get("pattern_delivered", ""),
                          rhythm_delivered=video.get("rhythm_delivered", ""))
        except LedgerError as exc:
            conflicts.append({"batch_id": batch_id, "script_id": video["script_id"],
                              "error": str(exc)})
            continue
        (filled if was_blank else already).append(video["script_id"])
    return {"batch_id": batch_id, "filled": filled, "already": already,
            "no_assignment": unassigned, "conflicts": conflicts}


def production_gap(channel, ledger_dir=None, pipeline_dir=None):
    """Where the ledger and the pipeline disagree, in three kinds.

    They are three different problems and collapsing them into one number
    would be the same mistake as an empty cell that means two things:

      recoverable  standing rows with no produced_at whose batch still has its
                   05-video-editor.json. Mechanical, and `reconcile` fills
                   them. This should only ever be seen between a render and
                   the next assignment.
      awaiting     standing rows with no produced_at and no file to fill them
                   from. Either the video has not been made yet - the normal
                   state of a fresh assignment - or it was made and its batch
                   has since been archived away. The ledger cannot tell those
                   two apart, which is why the gap is also closed where the
                   batch is destroyed: since CF-0056 the archive job fills the
                   columns and refuses to move a channel's batches while
                   `backfill --check` is still non-zero. This list should
                   therefore only ever mean "not produced yet".
      unrecorded   videos in a batch's own file that no ledger row mentions at
                   all. Not recoverable: nothing assigned them, and the pair
                   they were cut to exists in no file. Reported, never written.
    """
    ledger = Ledger(_ledger_path(channel, ledger_dir))
    rows = ledger.rows()
    # CF-0383: a video is recorded when a row names its batch *and* its script;
    # the id alone would credit it to whichever batch reused the id.
    known = {(r["batch_id"], r["script_id"]) for r in rows}

    metas, recoverable, awaiting = {}, {}, {}
    for row in ledger.standing_rows(rows):
        if row["produced_at"]:
            continue
        batch_id = row["batch_id"]
        if batch_id not in metas:
            metas[batch_id] = batch_metadata(channel, batch_id, pipeline_dir)[0]
        produced_here = {v.get("script_id") for v in (metas[batch_id] or {}).get("videos", [])}
        target = recoverable if row["script_id"] in produced_here else awaiting
        target.setdefault(batch_id, []).append(row["script_id"])

    unrecorded = {}
    for channel_dir in channel_batch_dirs(channel, pipeline_dir):
        for batch in sorted(d for d in channel_dir.iterdir() if d.is_dir()):
            meta = batch_metadata(channel, batch.name, pipeline_dir)[0]
            missing = [v["script_id"] for v in (meta or {}).get("videos", [])
                       if (batch.name, v.get("script_id")) not in known]
            if missing:
                unrecorded[batch.name] = missing
    return {"recoverable": recoverable, "awaiting": awaiting, "unrecorded": unrecorded}


def reconcile(channel, ledger_dir=None, pipeline_dir=None):
    """Fill every production cell the batches on disk can fill.

    Idempotent, and cheap because it opens only the batches that have a row
    waiting for them - a ledger that is up to date reads no metadata at all.
    """
    gap = production_gap(channel, ledger_dir, pipeline_dir)
    filled, conflicts, batches = [], [], []
    for batch_id in sorted(gap["recoverable"]):
        result = record_produced(channel, batch_id, ledger_dir, pipeline_dir)
        if result["filled"]:
            batches.append(batch_id)
        filled.extend(result["filled"])
        conflicts.extend(result["conflicts"])
    return {"filled": filled, "batches": batches, "conflicts": conflicts,
            "awaiting": gap["awaiting"], "unrecorded": gap["unrecorded"]}


def _reconcile_before_assigning(channel, ledger_dir, pipeline_dir):
    """The forcing function itself: catch the ledger up before assigning.

    Notes go to stderr deliberately - stdout of `assign` is one JSON object
    per assignment and something may be parsing it - and nothing raised here
    is allowed to abort the assignment: this is bookkeeping riding along on a
    step that has real work to do, and it must never become a reason the
    factory cannot assign the next batch.
    """
    try:
        report = reconcile(channel, ledger_dir, pipeline_dir)
    except (LedgerError, RotationError, ValueError, OSError) as exc:
        print(f"note: production columns could not be reconciled: {exc}", file=sys.stderr)
        return
    if report["filled"]:
        print(f"note: CF-0049 reconcile: filled the production columns of "
              f"{len(report['filled'])} row(s) from {len(report['batches'])} batch(es) "
              f"already on disk ({', '.join(report['batches'])})", file=sys.stderr)
    for conflict in report["conflicts"]:
        print(f"note: {conflict['batch_id']}/{conflict['script_id']}: {conflict['error']}",
              file=sys.stderr)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_status(report):
    print(f"channel {report['channel']}: {report['assignments_total']} ledger row(s), "
          f"{report['standing_total']} standing")
    print(f"  eligible pairs : {', '.join(report['eligible_pairs']) or 'none'}")
    if report["blocked_pairs"]:
        for pair, task in sorted(report["blocked_pairs"].items()):
            print(f"  blocked        : {pair} (waits on {task})")
    print(f"  no-repeat K    : {report['k_effective']} "
          f"(configured {report['k_configured']})"
          + ("" if not report["constrained"] else
             f" - capped by the {len(report['eligible_pairs'])} pair(s) that exist; "
             f"widened by {', '.join(report['blocked_by'])}. This is a state, not skew."))
    print(f"  window         : last {report['window']} standing assignments")
    for pair, count in sorted(report["counts_in_window"].items()):
        print(f"    {pair:<32} {count}")
    if report["counts_outside_vocabulary"]:
        for pair, count in sorted(report["counts_outside_vocabulary"].items()):
            print(f"    {pair:<32} {count}  (no longer eligible)")
    print(f"  spread         : {report['spread']}")
    if report["no_repeat_violations"]:
        print(f"  NO-REPEAT BROKEN at {report['no_repeat_violations'][:5]}")
    print(f"  rejections     : {report['rejections_upheld']} upheld, "
          f"{report['rejections_denied']} denied")

    # CF-0149: the line says what the topic waits for *and* whether it has
    # arrived. "awaiting pool" that only ever says "waiting" is a line an
    # operator stops reading; the state is the half that changes.
    _STATE_WORD = {"arrived": "ARRIVED, assignable",
                   "waiting": "still waiting",
                   "not-a-pool-question": "not a pool question - needs a person",
                   "no-baseline": "no baseline census - let through once"}
    for w in report.get("awaiting_material") or []:
        print(f"  awaiting pool  : {w['script_id']} (refused at seq {w['seq']}, "
              f"{w['refused_at']}) - {w['retry_when']}")
        print(f"                   {_STATE_WORD.get(w['state'], w['state'])}"
              f"{' - ' + w['pool_says'] if w['pool_says'] else ''}")

    recoverable = report["production_recoverable"]
    if recoverable:
        n = sum(len(v) for v in recoverable.values())
        print(f"  PRODUCED, NOT RECORDED: {n} row(s) in {len(recoverable)} batch(es) - "
              f"run `rotation/rotate.py backfill {report['channel']}` "
              f"({', '.join(sorted(recoverable))})")
    awaiting = report["production_awaiting"]
    if awaiting:
        n = sum(len(v) for v in awaiting.values())
        print(f"  awaiting video : {n} row(s) in {len(awaiting)} batch(es) have no "
              f"05-video-editor.json - not produced yet, or produced and archived away; "
              f"the ledger cannot tell those apart")
    unrecorded = report["production_unrecorded"]
    if unrecorded:
        n = sum(len(v) for v in unrecorded.values())
        print(f"  unrecorded     : {n} video(s) in {len(unrecorded)} batch(es) have no "
              f"ledger row at all - produced outside the rotation; not recoverable, and "
              f"not invented ({', '.join(sorted(unrecorded))})")


def _reject_target(args):
    """(channel, script_id, batch source or None) of a `reject` command line."""
    t = list(args.target)
    if args.batch is None:
        if len(t) != 2:
            raise RotationError("reject takes CHANNEL SCRIPT_ID, or --batch DIR SCRIPT_ID")
        return t[0], t[1], None
    src = channel_of_batch(args.batch)
    if len(t) == 1:
        return src["channel"], t[0], src
    if len(t) == 2:
        if resolve_channel(t[0]) != src["channel"]:
            raise RotationError(
                f"channel {t[0]!r} on the command line, {src['channel']!r} in "
                f"{args.batch} ({src['read_from']}) - one of them is wrong")
        return src["channel"], t[1], src
    raise RotationError("reject takes CHANNEL SCRIPT_ID, or --batch DIR SCRIPT_ID")


def _reject_batch_id(args):
    """The batch a `reject` command line names, or None (CF-0383).

    `--batch-id` is taken as typed. `--batch DIR` names the batch its records
    carry (for a rebuild, the source batch) - and only if that batch has a
    standing row for the script: a directory whose records name a batch the
    row does not belong to falls back to the id alone, which still refuses
    when the id stands in two batches, and the note below says which batch
    the ruled row belonged to."""
    if args.batch_id:
        return args.batch_id
    src = args.batch_source
    if not src or not src.get("batch_id"):
        return None
    ledger = Ledger(_ledger_path(args.channel, args.ledger_dir))
    if ledger.standing_row_for(args.script_id, None, src["batch_id"]) is None:
        return None
    return src["batch_id"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger-dir", default=None,
                        help="override the ledger directory (tests, dry runs)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="what the guard currently sees")
    p.add_argument("channel")

    p = sub.add_parser("assign", help="assign a pair to each script, before writing")
    p.add_argument("channel")
    p.add_argument("batch_id")
    p.add_argument("--script", action="append", required=True, dest="scripts")
    p.add_argument("--despite-shortage", action="store_true",
                   help="assign a topic whose shortage record is still open (CF-0149). "
                        "A person's override of the pool census, not an agent's: the "
                        "default is to wait until the store the record names has grown")

    p = sub.add_parser("reject", help="reject a standing assignment, in writing")
    p.add_argument("target", nargs="+", metavar="[CHANNEL] SCRIPT_ID",
                   help="the channel and the script; with --batch the script alone")
    p.add_argument("--batch", default=None,
                   help="a batch directory - a rebuild (pipeline/rebuilds/<ts>) included - "
                        "whose own records name the channel (CF-0416): 05-video-editor.json "
                        "`rebuild_of`/`channel`, else the copied 03/01 `channel`")
    p.add_argument("--batch-id", default=None, dest="batch_id",
                   help="the batch whose assignment is rejected (CF-0383): a script id is "
                        "unique inside a batch, not across them, so an id that stands in two "
                        "batches is refused until the batch is named. --batch DIR names it "
                        "from the directory's own records")
    p.add_argument("--reason", required=True)
    p.add_argument("--rhythm", action="store_true", dest="rejects_rhythm",
                   help="what is refused is the rhythm, not only the pattern (CF-0286): "
                        "the replacement skips every pair carrying this assignment's "
                        "rhythm. Takes no value - the rhythm excluded is the one on the "
                        "row being rejected, and only an upheld rejection excludes it")

    p = sub.add_parser("refuse",
                       help="close an assignment the pool cannot supply (CF-0139): the "
                            "planner's refusal, with the deficit that proves it")
    p.add_argument("channel")
    p.add_argument("script_id")
    p.add_argument("--batch-id", default=None, dest="batch_id",
                   help="the batch whose assignment is refused (CF-0383) - needed only "
                        "when the script id stands in more than one batch")
    p.add_argument("--reason", required=True)
    p.add_argument("--deficit", required=True,
                   help="path to plan.assetless-rung.json - the machine-readable "
                        "record of what the pool could not supply")

    p = sub.add_parser("produced", help="fill production columns from 05-video-editor.json")
    p.add_argument("channel")
    p.add_argument("batch_id")

    p = sub.add_parser("backfill",
                       help="fill the production columns of every batch still on disk")
    p.add_argument("channel")
    p.add_argument("--check", action="store_true",
                   help="report and write nothing, exiting non-zero if anything produced "
                        "is still unrecorded - for a caller that must not destroy a batch "
                        "while the ledger is behind it")

    p = sub.add_parser("validate", help="structural check of the ledger on disk")
    p.add_argument("channel")

    args = parser.parse_args(argv)
    if args.command == "reject":
        try:
            args.channel, args.script_id, args.batch_source = _reject_target(args)
        except RotationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    # A channel named by a former id is answered under its current one, out
    # loud: the archive job passes the directory name it found (see
    # FORMER_CHANNEL_IDS), and an operator typing the old name should be told
    # which channel actually answered rather than get a missing-ledger error.
    current = resolve_channel(args.channel)
    if current != args.channel:
        print(f"note: {args.channel} is the former id of {current}; answering for "
              f"{current} (CF-0180)", file=sys.stderr)
        args.channel = current
    try:
        if args.command == "status":
            _print_status(distribution_report(args.channel, args.ledger_dir))
        elif args.command == "assign":
            if args.despite_shortage:
                print("note: --despite-shortage; the pool census is not consulted "
                      "(CF-0149)", file=sys.stderr)
            results = assign(args.channel, args.batch_id, args.scripts, args.ledger_dir,
                             despite_shortage=args.despite_shortage)
            for a in results:
                print(json.dumps(a))
            # A skipped topic is not an error - the batch has the rest to do -
            # but it is not a success either, and a caller that only reads the
            # exit code must not read "four of five assigned" as "five".
            if any(not a.get("assigned", True) for a in results):
                skipped = [a["script_id"] for a in results if not a.get("assigned", True)]
                print(f"note: {len(skipped)} topic(s) not assigned, waiting for the pool "
                      f"({', '.join(skipped)}) - `status {args.channel}` says what each "
                      f"waits for", file=sys.stderr)
                return 2
        elif args.command == "reject":
            ruling = reject(args.channel, args.script_id, args.reason, args.ledger_dir,
                            rejects_rhythm=args.rejects_rhythm,
                            batch_id=_reject_batch_id(args), batch_dir=args.batch)
            out = {k: v for k, v in ruling.items() if k != "row"}
            src = args.batch_source
            if src is not None:
                out["batch_source"] = src
                row_batch = (ruling.get("row") or {}).get("batch_id")
                if src.get("batch_id") and row_batch and row_batch != src["batch_id"]:
                    print(f"note: the row ruled on belongs to batch {row_batch}, the batch "
                          f"directory names {src['batch_id']} ({src['read_from']})",
                          file=sys.stderr)
            print(json.dumps(out, default=str))
        elif args.command == "refuse":
            ruling = refuse(args.channel, args.script_id, args.reason,
                            deficit_path=args.deficit, ledger_dir=args.ledger_dir,
                            batch_id=args.batch_id)
            print(json.dumps(ruling, default=str))
        elif args.command == "produced":
            print(json.dumps(record_produced(args.channel, args.batch_id, args.ledger_dir)))
        elif args.command == "backfill":
            if args.check:
                gap = production_gap(args.channel, args.ledger_dir)
                print(json.dumps(gap))
                return 1 if gap["recoverable"] else 0
            print(json.dumps(reconcile(args.channel, args.ledger_dir)))
        elif args.command == "validate":
            from ledger import validate as validate_ledger
            errs = validate_ledger(_ledger_path(args.channel, args.ledger_dir))
            errs += shortage.validate(
                _shortage_log_path(args.channel, args.ledger_dir),
                ledger_rows=Ledger(_ledger_path(args.channel, args.ledger_dir)).rows())
            for e in errs:
                print(f"  - {e}")
            print(f"{len(errs)} error(s)")
            return 1 if errs else 0
    except (RotationError, LedgerError, shortage.ShortageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
