#!/usr/bin/env python3
"""The per-shot time marks in `shots.json`: `tile_at` and `moment_at` (CF-0106).

A shot record is flat: `index`, `start`, `end`, `embedding`, `description`,
`is_card`, the cached measurements (`usable_cached`, `crop_bottom_cached`,
...). Two optional time marks live beside them, both absolute timecodes in
the *source* file, in seconds, same unit as `start`/`end`:

  tile_at    Where the shot's contact-sheet tile and CLIP embedding frame were
             sampled from - the shot's midpoint (`index_footage.extract_frames`).
             Written by `index_footage.py` on every shot it indexes. A fact,
             not a decision: it says which frame the description was written
             against, so that whoever reads a description of a 20-second shot
             knows it describes second 10, not second 0.

  moment_at  The moment inside the shot that the description is *about*, when
             that is not the shot's head. Set by whoever writes the
             `description` (a human or an LLM reading the contact sheet, or
             pulling frames by timecode - see SKILL.md), never by
             `index_footage.py`: the indexer cannot tell whether a shot's head
             looks like its tile, and marking every shot's midpoint would just
             move every cut to the middle. Absent (or null) means "cut from the
             head, as always". Video Editor's `resolve_anchors`/`prepare_clip`
             build the clip window around it instead of from `start`.

Both, when present, must lie inside the shot's own `[start, end]`; anything
else is refused loudly here, before the number reaches a cut. An index that
carries neither (every index written before CF-0106) is valid as it is - the
marks are optional, and their absence is the default.

**Whether a file on disk is a finished index at all (CF-0281).** The marks
above are about a record that was written; `file_problems()` / `is_complete()`
below are about whether the writing finished. On 2026-09-19 the machine went
down inside `index_footage.py`, and the only thing standing between the next
run and a half-written `shots.json` was `Path(...).exists()` in
`ingest_batch.py` - which a truncated file passes. So there is one function
both the writer and every reader can ask, and one writer (`write_index()`)
that renames a finished file into place instead of growing it under the name
readers use. An index that carries no shots is not a usable source either: it
backs no phrase, and counting it would be exactly the silent thinning of the
pool that CF-0281 is about.

Also a CLI: `shot_schema.py <shots.json> [...]` checks indexes and exits 1 on
the first file with a problem - for whoever just edited descriptions by hand.
"""
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
import shot_usability  # noqa: E402 - CF-0435: the usability record every written index carries

TILE_AT = "tile_at"
MOMENT_AT = "moment_at"
TIME_MARKS = (TILE_AT, MOMENT_AT)

# --------------------------------------------------------------------------
# CF-0299: the two flags the description pass puts on every shot it describes
# --------------------------------------------------------------------------
# Both are the *describer's* answer, not a measurement, for the reason
# CF-0299 exists at all: the measurements that already sit on a shot cannot
# tell a foreign source from a good one. Measured over the pool of batch
# 2026-09-21T0358Z, `usable_cached.text_outside_crop > 0` is true for 60 % of
# the shots of `JzA-WopbYnc` (real Coach Hale scenes, subtitles in the bottom
# band the 9:16 caption crop removes) and 0 % of `bYKJxZYd66o` (an interview
# Short whose captions sit in the *middle* of the frame - the six burned-in
# lines the frame judge rejected a finished render for). The detector is not
# wrong; it answers a different question. Whoever reads the contact sheet can
# answer this one, and does so while already looking at every tile.
#
#   burned_text  Somebody else's text is burned into this shot and will still
#                be there after the 9:16 caption crop (see SKILL.md, CF-0275):
#                a caption or subtitle outside the bottom band, a title card,
#                an end card, a screenshot of a website. A studio's corner
#                logo is NOT this (the user's decision, DoD item 2), and
#                neither is text that is part of the pictured world - a sign
#                on a wall, a name embossed on a prop.
#
#   on_topic     This shot pictures the topic's own work - its scenes, its
#                people, its making. False for a shot of something else
#                entirely: another film, a comic-universe trailer, an app's
#                website.
#
# Both are booleans and both are optional: every index described before this
# task carries neither, which is "nobody was asked", not "nothing is wrong".
# `sieve_counts()` below says how many shots were asked, and the sieve refuses
# to judge a source no one has answered for.
BURNED_TEXT = "burned_text"
ON_TOPIC = "on_topic"
SIEVE_FLAGS = (BURNED_TEXT, ON_TOPIC)

# CF-0344: the third answer, asked only of a thin-pool supplement source
# (CF-0338 - `fetched[].supplement.entity` in the stage report). Such a source
# is fetched *for its entity* - the actor's other film, a talk-show interview -
# so it is somebody else's work by design and `on_topic` is `false` on it
# honestly. What decides whether its shot is any use is whether the entity is
# in it:
#
#   shows_entity  The entity the source was fetched for (the person, show or
#                 place of `supplement.entity`) is seen in this shot, or named
#                 by it. False for a shot of the same film without them - a
#                 frame of Ocean's 8 with no Sandra Birch in it.
#
# Optional even there: when it is absent, the describer's own sentence
# answers - a description that names the entity (its full name, or a person's
# surname) counts as the entity shown. It is not one of SIEVE_FLAGS: a source
# is complete for the sieve on `burned_text` and `on_topic` alone.
SHOWS_ENTITY = "shows_entity"

# CF-0451: the fourth answer, asked of every shot from 2026-10-01 on:
#
#   screen_recording  This shot is a screen filmed from the room - the cinema
#                     "экранка": the big screen seen from the stalls, the
#                     audience's heads across it, the screen's edge or its
#                     keystoned perspective, moiré; a phone pointed at a TV.
#                     False for the work's own image, including a scene the
#                     work sets in a cinema, and for a screen that is part of
#                     the pictured world in the work's own shot.
#
# Optional, like `shows_entity`: absent, the describer's sentence answers
# (`screen_recording.DESCRIPTION_RE`), which is how the pool as it stands is
# read without being re-described. Not one of SIEVE_FLAGS - a source is
# complete for the sieve without it, and until the user signs a price
# (CF-0320) it is a warning, never a refusal (`screen_recording.py`).
#
# CF-0567: a shot of an own capture (ExampleTech's own screen recording) carries
# `source_kind: "own_capture"` (index_footage.py) and is exempt from the rule by
# that kind (`screen_recording.exempt`) - the describer may still answer the
# flag; it is not read there.
SCREEN_RECORDING = "screen_recording"
SOURCE_KIND = "source_kind"
BOOL_FLAGS = SIEVE_FLAGS + (SHOWS_ENTITY, SCREEN_RECORDING)


def _is_number(v):
    # bool is an int subclass; `true` is not a timecode.
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def mark_problems(shot, key):
    """Why `shot[key]` is not a valid time mark; [] when it is valid or absent.

    Absent and null both mean "no mark" and are fine. Anything else must be
    a finite number inside the shot's own [start, end] (inclusive)."""
    v = shot.get(key)
    if v is None:
        return []
    label = f"shot {shot.get('index', '?')}"
    if not _is_number(v):
        return [f"{label}: {key} must be a timecode in seconds, got {v!r}"]
    start, end = shot.get("start"), shot.get("end")
    if not (_is_number(start) and _is_number(end)):
        return [f"{label}: {key}={v} cannot be checked, start/end are not numbers"]
    if not start <= v <= end:
        return [f"{label}: {key}={v} lies outside the shot's own bounds "
                f"[{start}, {end}]"]
    return []


def flag_problems(shot, key):
    """Why `shot[key]` is not a valid sieve flag; [] when it is one or absent.

    CF-0299. Absent and null both mean "nobody answered for this shot" and are
    fine. Anything else must be a boolean: a source is refused whole on the
    fraction of its shots that carry these, and a string, a number or a note
    would be counted as `true` by every `if shot.get(...)` in the factory.
    """
    v = shot.get(key)
    if v is None:
        return []
    if not isinstance(v, bool):
        return [f"shot {shot.get('index', '?')}: {key} must be true or false, "
                f"got {v!r}"]
    return []


def shot_problems(shot):
    """All time-mark and sieve-flag problems on one shot; [] for a valid one."""
    out = []
    for key in TIME_MARKS:
        out.extend(mark_problems(shot, key))
    for key in BOOL_FLAGS:
        out.extend(flag_problems(shot, key))
    return out


def entity_names(entity):
    """The words a description names `entity` by: the full name, and for a
    name of two or more words its last one (a person's surname - "Bullock").
    Lower-cased; empty for no entity."""
    if isinstance(entity, dict):
        entity = entity.get("name")
    name = " ".join(str(entity or "").split()).lower()
    if not name:
        return []
    out = [name]
    words = name.split(" ")
    if len(words) > 1 and len(words[-1]) > 2:
        out.append(words[-1])
    return out


def shows_entity(shot, entity):
    """Whether one shot pictures or names `entity` (CF-0344).

    The describer's `shows_entity` flag when it is a boolean; otherwise the
    description naming the entity, as a whole word, case-insensitively."""
    v = shot.get(SHOWS_ENTITY)
    if isinstance(v, bool):
        return v
    text = " ".join(str(shot.get("description") or "").split()).lower()
    if not text:
        return False
    return any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text)
               for n in entity_names(entity))


def sieve_counts(data, entity=None):
    """How the CF-0299 sieve reads one index: the shape it counts on.

    Takes a loaded shots.json (the dict or its `shots` list) and returns

        {"shots": n, "decided": k, "burned_text": b, "off_topic": o,
         "burned_text_shots": [...], "off_topic_shots": [...], "complete": bool}

    `decided` counts the shots that carry **both** flags; `complete` is
    `decided == shots` with at least one shot. The fractions the sieve applies
    are over `shots`, never over `decided`: a describer that flagged only the
    shots it found something wrong with would otherwise hand every source a
    fraction of 1.0. That is what `complete` is for - a source that is not
    complete is not judged at all, it is reported as unsieved.
    """
    shots = data.get("shots", []) if isinstance(data, dict) else data
    shots = [s for s in (shots or []) if isinstance(s, dict)]
    decided, burned, off, ent = 0, [], [], []
    for s in shots:
        flagged = all(isinstance(s.get(k), bool) for k in SIEVE_FLAGS)
        if flagged:
            decided += 1
        if s.get(BURNED_TEXT) is True:
            burned.append(s.get("index"))
        seen = bool(entity) and shows_entity(s, entity)
        if seen:
            ent.append(s.get("index"))
        if s.get(ON_TOPIC) is False and not seen:
            off.append(s.get("index"))
    n = len(shots)
    out = {"shots": n, "decided": decided,
           "burned_text": len(burned), "off_topic": len(off),
           "burned_text_shots": burned, "off_topic_shots": off,
           "complete": bool(n) and decided == n}
    if entity:
        # Only for a supplement source: an ordinary one reads exactly as it
        # did before CF-0344.
        out["entity_shots"] = ent
    return out


def index_problems(data):
    """All time-mark problems in a loaded shots.json (the dict, or its `shots`
    list); [] when the index is valid. Never raises on a shape it does not
    know - a malformed shot list is somebody else's error to report."""
    shots = data.get("shots", []) if isinstance(data, dict) else data
    out = []
    for shot in shots or []:
        if isinstance(shot, dict):
            out.extend(shot_problems(shot))
    return out


def require_valid(data, path="shots.json"):
    """Raise ValueError naming every bad mark in `data`, else return it."""
    problems = index_problems(data)
    if problems:
        raise ValueError(f"{path}: invalid shot record(s) - "
                         + "; ".join(problems)
                         + ". moment_at/tile_at are absolute source timecodes "
                           "in seconds and must lie within the shot's "
                           "[start, end]; burned_text/on_topic (CF-0299) are "
                           "true or false and nothing else")
    return data


# --------------------------------------------------------------------------
# CF-0281: is this file a finished index?
# --------------------------------------------------------------------------
# The keys `index_footage.py` has always written at the top level and every
# reader takes for granted. `model`, `split_stats` (CF-0105) and `fingerprint`
# (CF-0080) are deliberately *not* required: every index written before those
# tasks lacks them and is a perfectly good index - the pool on disk is the
# regression corpus for that.
INDEX_TOP_KEYS = ("source", "shots")


def shot_shape_problems(shot, label):
    """Why one record is not a shot: the three fields every reader indexes by."""
    if not isinstance(shot, dict):
        return [f"{label}: not a shot record ({type(shot).__name__})"]
    out = []
    for key in ("start", "end"):
        if not _is_number(shot.get(key)):
            out.append(f"{label}: {key} is not a number ({shot.get(key)!r})")
    if not isinstance(shot.get("index"), int) or isinstance(shot.get("index"), bool):
        out.append(f"{label}: index is not a shot number ({shot.get('index')!r})")
    return out


def file_problems(path):
    """Why the file at `path` is not a finished index, as sentences; [] when it
    is one. Each sentence names the file, because it is copied into a refusal
    that is read with no other file open.

    This is the check a *reader* owes itself before treating `<id>.shots.json`
    as the answer for a source - `exists()` is not that check. A process killed
    mid-write leaves a file that exists, opens and is not an index (2026-09-19,
    `PEiDNOQ_0ms`), and a source with no index is not a source however many
    bytes sit beside it.
    """
    p = Path(path)
    name = p.name
    if not p.is_file():
        return [f"{name}: no index file"]
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return [f"{name}: cannot be read as an index - {e}"]
    if not isinstance(data, dict):
        return [f"{name}: the index is not an object ({type(data).__name__})"]
    missing = [k for k in INDEX_TOP_KEYS if k not in data]
    if missing:
        return [f"{name}: the index is missing {', '.join(missing)}"]
    shots = data.get("shots")
    if not isinstance(shots, list):
        return [f"{name}: `shots` is not a list ({type(shots).__name__})"]
    if not shots:
        return [f"{name}: the index carries no shots, so it backs no phrase"]
    out = []
    for i, shot in enumerate(shots):
        out.extend(shot_shape_problems(shot, f"{name} shot {i}"))
    out.extend(f"{name}: {p_}" for p_ in index_problems(data))
    return out


def is_complete(path):
    """Whether `path` is an index a reader may trust. See file_problems()."""
    return not file_problems(path)


def write_index(dest, index):
    """Write a finished index to `dest` - whole, or not at all.

    CF-0281: `json.dump(index, open(dest, "w"))` grows the file readers look
    for while it is being written, so a process that dies in the middle (the
    machine went down inside this write on 2026-09-19) leaves something that
    passes `exists()` and is not an index. The bytes go to a neighbour in the
    same directory and `os.replace` renames it over the destination, which is
    atomic on one filesystem: a reader sees the old index or the new one.

    CF-0435: every shot of the index gets its `usability` record here
    (`shot_usability.stamp_index`) - a score and the soft/hard violations,
    derived from what the shot already stores, never re-measured. This is the
    one writer, so new material and every index a batch rewrites carry the
    field; an old index nobody writes again is judged on the fly by the same
    function.
    """
    dest = Path(dest)
    if isinstance(index, dict):
        shot_usability.stamp_index(index)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=dest.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(index, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def moment_at(shot):
    """The shot's validated moment mark, or None when it has none.

    Raises ValueError for a mark that is present but not a timecode inside
    the shot - a caller relaying it to a cut must never pass that on."""
    problems = mark_problems(shot, MOMENT_AT)
    if problems:
        raise ValueError(problems[0])
    return shot.get(MOMENT_AT)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: shot_schema.py <shots.json> [...]")
    bad = 0
    for path in argv:
        # CF-0281: one question, asked the way every reader of the pool asks
        # it - is this file a finished index at all, and are its marks legal.
        problems = file_problems(path)
        if problems:
            bad += 1
            print(f"{path}: {len(problems)} problem(s)")
            for p in problems:
                print(f"  {p}")
            continue
        data = json.loads(Path(path).read_text())
        n_marked = sum(1 for s in data.get("shots", []) if s.get(MOMENT_AT) is not None)
        # CF-0299: whether this index can be sieved at all is the other thing
        # a hand-edit breaks, and it is not visible by reading the file.
        c = sieve_counts(data)
        sieve = (f"sieve flags on {c['decided']}/{c['shots']} shot(s)"
                 + ("" if c["complete"] else " - NOT sieveable")
                 + (f", {c['burned_text']} burned_text, {c['off_topic']} off-topic"
                    if c["decided"] else ""))
        print(f"{path}: ok ({n_marked} shot(s) carry {MOMENT_AT}; {sieve})")
    sys.exit(1 if bad else 0)


@runlog.script("footage-indexer", "check-schema", name="shot_schema.py")
def cli():
    """CF-0107: the hand-edit check leaves start/done|failed too (exit 1 on a
    bad index -> failed). main() stays bare for in-process callers."""
    main()


if __name__ == "__main__":
    cli()
