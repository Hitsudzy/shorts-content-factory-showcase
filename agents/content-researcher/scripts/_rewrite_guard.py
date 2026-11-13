"""CF-0430: a gate re-run on an unchanged script spends nothing.

Every step-6 gate that counts attempts - `check_narration_budget.py`,
`check_anchor_coverage.py`, `check_block_capacity.py`,
`check_alternate_sides.py`, `check_anchor_cadence.py` - gives a script one
rewrite and refuses the topic on the second failure. The counter lives in the
gate's own record on the script in `03-content-researcher.json`
(`scripts[].<record key>.failed_attempts`, written by `--write`), and until
this task a run counted a failure whether or not anything had been rewritten
since the last one. On `example-film/2026-09-28T1126Z` AHS and Wolfhame were
refused `thin_scene` by `check_anchor_cadence.py` after the gate was run twice
with no edit between the runs: the one rewrite was spent on nothing.

The user's decision of 28.09 (option A) was to forbid that by mechanics, not
by a sentence in SKILL.md. This module is that mechanic, in one place for all
five gates:

  * `stamp()` writes `script_hash` into the record a gate is about to put on
    the script - a hash of what the writer controls: the text of the spoken
    sections and `visual_anchors` (and `graphics[]`, CF-0689);
  * `split()` takes the scripts a gate is about to judge and puts aside every
    one whose own record of that gate asked for a rewrite (`action ==
    "rewrite"`) and whose `script_hash` equals the script's hash now. Such a
    script is not judged: the gate prints `UNCHANGED - edit the script first`,
    leaves the record as it was (`failed_attempts` does not move), and the
    script counts as the rewrite it still is - so the run exits with the same
    code the last one did.

A record written before this task has no `script_hash` and is judged as
before. Only `rewrite` is guarded: a pass has nothing to spend, a refused topic
is already out of `scripts[]`, and a rejected assignment (block capacity's
`reject`, alternate sides' `reject_assignment`) is fixed by redrawing the
pattern, which is not text. Nor is `check_narration_budget.py`'s `top_up`
(CF-0796): "nothing quotable is left, the script comes back unchanged" is a
legal answer to the one top-up pass, and the re-run on it is what closes the
pass (`accept_short`, `topped_up: false`) - its bound is the record's own
`top_up_attempts`, not this guard.
"""
import hashlib
import json

HASH_KEY = "script_hash"
UNCHANGED = "UNCHANGED - edit the script first"
RERUNS_KEY = "unchanged_reruns"
GUARDED_ACTION = "rewrite"

# The sections every channel reads aloud today. A gate passes its channel's
# `counted_sections` as well; the hash is taken over the union, sorted, so it
# does not depend on the order the sections were named in.
TEXT_SECTIONS = ("hook", "commentary", "payoff")
ANCHORS_FIELD = "visual_anchors"
GRAPHICS_FIELD = "graphics"          # = shared/own_graphic.py GRAPHICS_FIELD (CF-0689)


def _words(text):
    """A section as the words it says: whitespace is not a rewrite."""
    return " ".join(text.split()) if isinstance(text, str) else text


def script_hash(script, sections=()):
    """`sha256:<hex>` of the script's spoken text and its `visual_anchors`
    (and, CF-0689, its `graphics[]` when it orders any).

    Each section is taken as its words (a space added or removed is not an
    edit), the anchors as written; canonical JSON (sorted keys, no whitespace),
    so re-serialising the batch file does not change it and changing one word
    or one anchor field does.
    """
    names = sorted(set(TEXT_SECTIONS) | set(sections or ()))
    payload = {"text": {n: _words(script.get(n)) for n in names},
               "anchors": script.get(ANCHORS_FIELD)}
    # CF-0689: a graphic the script orders is text the viewer reads - an edited
    # graphic is an edit. Only when the script has the field, so the hash of
    # every script written before graphics (and every record stamped on one)
    # stays what it was.
    if GRAPHICS_FIELD in script:
        payload["graphics"] = script.get(GRAPHICS_FIELD)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stamp(record, script, sections=()):
    """Put the hash of the script as judged onto the gate's record."""
    if isinstance(record, dict):
        record[HASH_KEY] = script_hash(script, sections)
    return record


def unchanged(script, record_key, sections=()):
    """The gate's previous record, if it asked for a rewrite of exactly the
    text and anchors the script still has; else None."""
    record = script.get(record_key)
    if not isinstance(record, dict) or record.get("action") != GUARDED_ACTION:
        return None
    stamped = record.get(HASH_KEY)
    if not stamped or stamped != script_hash(script, sections):
        return None
    return record


def line(script, record):
    """The report line of a script that was not judged again."""
    return (f"  UNCHANGED {script.get('script_id')}: {UNCHANGED} - the text and "
            f"`{ANCHORS_FIELD}` are the ones the last run asked to rewrite, so this run "
            f"judged nothing and spent nothing (failed_attempts stays "
            f"{record.get('failed_attempts')}); the answer is still the last one: "
            f"{record.get('reason')}")


def problem(script, record):
    """The rewrite the script still is, in the gate's `problems[]` shape."""
    return f"{script.get('script_id')}: {UNCHANGED} (last run: {record.get('reason')})"


def split(scripts, record_key, sections=(), out=print, write=False):
    """`(to_judge, unchanged_scripts, problems)`.

    `to_judge` keeps the order of `scripts`. For every script put aside the
    line is printed and its problem returned, and with `write` the record's
    `unchanged_reruns` is counted up - a record of the refused re-run, which is
    not a failed attempt.
    """
    to_judge, kept, problems = [], [], []
    for script in scripts:
        record = unchanged(script, record_key, sections)
        if record is None:
            to_judge.append(script)
            continue
        kept.append(script)
        out(line(script, record))
        problems.append(problem(script, record))
        if write:
            n = record.get(RERUNS_KEY)
            record[RERUNS_KEY] = (n if isinstance(n, int) and not isinstance(n, bool) else 0) + 1
    return to_judge, kept, problems
