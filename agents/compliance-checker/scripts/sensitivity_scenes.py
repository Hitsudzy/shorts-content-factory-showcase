#!/usr/bin/env python3
"""CF-0846: which scene of a topic a content-sensitivity flag rests on.

Why
---
`example-film/2026-10-21T0837Z`, topic `lf-2026-10-21-006` (The Daily Show).
The shortlist pass flagged the topic `review` because of its scene 2 (Jon
Stewart's Skydance joke turning on JD Vance, Trump and Macron - sitting
politicians at the centre) and said in its notes that scene 1 (the host deal
through 2028) was harmless on its own. The Content Researcher wrote the script
on scene 1. The publication hold (CF-0318) still stood on the whole topic and
waited for the user's signature: a hold earned by a scene that is not in the
video. The user, 2026-10-21: "да, заводи задачу".

The notes said which scene it was, but only in prose. This module makes it a
field, so the root can lift such a hold by itself once the script is chosen
(`03-content-researcher.json` -> `scene_id`), and nobody has to read prose to
do it.

The field
---------
`content_sensitivity_check.scenes` on every **flagged** row of the shortlist
pass (`02-compliance-checker.json`, `stage_checked: "01-trend-hunter"`),
`results[]` and `reserve[]` alike. Exactly one of two forms:

* a non-empty list of the topic's own `scene_id`s (`01-trend-hunter.json`
  `topics[].scenes[].scene_id`, e.g. `"lf-2026-10-21-006-s2"`) - the flag
  rests on these scenes and on nothing else of the topic;
* the string `"whole_topic"` - the flag rests on the topic as such (its
  subject, a person it is about, every scene), or the reading cannot say.

How it is read - one rule, fail closed
--------------------------------------
Only a clean non-empty list of non-empty strings ties a flag to scenes.
Anything else - the field missing (every file written before CF-0846), `null`,
`[]`, `"whole_topic"`, a stray value - reads as **the whole topic**, and the
hold stands exactly as it did. The absence of the field can never read as
"another scene". That is `flagged_scenes()`; `spares_scene()` and
`hold_spared_by_scene()` are the questions the root asks with it.

The flag of the scripts pass (`04`, `stage_checked: "03-content-researcher"`)
is on the written script, which is the chosen scene by construction: it never
spares anything, and `hold_spared_by_scene()` says no to every row not raised
by the shortlist pass. Checking a flag against the final text is deliberately
not here (it would soften the gate, and that needs the user's signature).

What it does not do
-------------------
It moves no verdict and resolves no hold. The command line only checks the
field the pass wrote (step 4a of the skill) and exits 1 when a flagged row
lacks it or names a scene the topic does not have, so the model fixes the row
before the hold is written. Pure Python over two batch files, no model call,
no child process.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runlog import runlog  # noqa: E402
from _cli import screen  # noqa: E402

TASK = "CF-0846"
FIELD = "scenes"
WHOLE_TOPIC = "whole_topic"
CHECK_KEY = "content_sensitivity_check"
# The pass whose flags may be tied to scenes: the one that reads a topic and its
# scenes. The scripts pass judges one scene's script, so its flags are on the
# chosen scene by construction.
STAGE_CHECKED = "01-trend-hunter"
STAGE_FILE = "01-trend-hunter.json"
# The `resolved_reason` code the root writes when it lifts a hold whose flags
# all rest on scenes the script did not take (CF-0846, the root's half).
RESOLVED_REASON_CODE = "flagged_scene_not_in_script"


# --------------------------------------------------------------------------
# reading the field
# --------------------------------------------------------------------------
def flagged(check):
    """Whether a `content_sensitivity_check` carries a flag."""
    return isinstance(check, dict) and bool(check.get("flagged"))


def flagged_scenes(check):
    """The scene ids a flag rests on, as a frozenset - or `None`, which means
    **the whole topic**.

    `None` for everything that is not a clean non-empty list of non-empty
    strings: no field (a file written before CF-0846), `null`, `[]`,
    `"whole_topic"`, a damaged value. Fail closed: what cannot be read as
    "these scenes" is read as "all of it"."""
    if not isinstance(check, dict):
        return None
    value = check.get(FIELD)
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(s, str) and s.strip() for s in value):
        return None
    return frozenset(s.strip() for s in value)


def spares_scene(check, scene_id, topic_scene_ids=None):
    """True only when a flag is there, is tied to scenes, and `scene_id` is
    not one of them - the flag is about a scene the video does not use.

    False whenever there is any doubt: no flag (nothing to spare on this
    basis), a whole-topic flag, an old file without the field, a missing
    `scene_id`, or - when `topic_scene_ids` is given - a `scene_id` the topic
    does not have (a scene nobody judged is not a scene the flag spared)."""
    if not flagged(check):
        return False
    scenes = flagged_scenes(check)
    if scenes is None:
        return False
    if not isinstance(scene_id, str) or not scene_id.strip():
        return False
    scene_id = scene_id.strip()
    if topic_scene_ids is not None and scene_id not in set(topic_scene_ids):
        return False
    return scene_id not in scenes


def hold_spared_by_scene(hold, scene_id, topic_scene_ids=None):
    """`(spared, reason)` for a hold row - a `publish/publication-holds.json`
    row, or a `02` verdict row with `stage_checked` set on it - and the
    `scene_id` the script took.

    Spared only when the hold was raised by the shortlist pass
    (`stage_checked: "01-trend-hunter"`) and `spares_scene()` says yes on its
    `content_sensitivity_check`. It does not look at `resolved_at` or
    `signature`: whether the row still stands is the caller's question."""
    if not isinstance(hold, dict):
        return False, "no hold row to read"
    stage = hold.get("stage_checked")
    if stage != STAGE_CHECKED:
        return False, (f"the hold was raised by the {stage!r} pass, not the "
                       f"shortlist pass ({STAGE_CHECKED}): a flag on a written "
                       f"script is on the chosen scene ({TASK})")
    check = hold.get(CHECK_KEY)
    if not flagged(check):
        return False, "the content-sensitivity check is not flagged: not this rule's to lift"
    scenes = flagged_scenes(check)
    if scenes is None:
        return False, ("the flag rests on the whole topic (`scenes` is "
                       f"{(check or {}).get(FIELD, 'absent')!r}) - it holds whatever scene "
                       f"the script took ({TASK})")
    if spares_scene(check, scene_id, topic_scene_ids):
        return True, (f"every flag rests on {sorted(scenes)}; the script took "
                      f"{scene_id.strip()!r} ({RESOLVED_REASON_CODE}, {TASK})")
    if isinstance(scene_id, str) and scene_id.strip() in scenes:
        return False, f"the script took the flagged scene {scene_id.strip()!r}"
    return False, (f"the script's scene {scene_id!r} cannot be told apart from the "
                   f"flagged ones {sorted(scenes)} - the hold stands")


# --------------------------------------------------------------------------
# checking what the pass wrote
# --------------------------------------------------------------------------
def topic_scene_ids(stage_doc):
    """`{topic_id: [scene_id, ...]}` from `01-trend-hunter.json`, in order."""
    out = {}
    topics = stage_doc.get("topics") if isinstance(stage_doc, dict) else None
    for topic in topics if isinstance(topics, list) else []:
        if not isinstance(topic, dict) or not topic.get("topic_id"):
            continue
        ids = []
        for scene in topic.get("scenes") or []:
            if isinstance(scene, dict) and isinstance(scene.get("scene_id"), str) \
                    and scene["scene_id"].strip():
                ids.append(scene["scene_id"].strip())
        out[topic["topic_id"]] = ids
    return out


def _rows(doc):
    for key in ("results", "reserve"):
        value = doc.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict) and row.get("topic_id"):
                    yield row


def check_row(row, scene_ids):
    """`(kind, problem)` for one verdict row. `kind` is `None` (not flagged),
    `"whole_topic"` or `"scenes"`; `problem` is a sentence or `None`."""
    check = row.get(CHECK_KEY)
    if not flagged(check):
        return None, None
    value = check.get(FIELD, "<absent>")
    if value == WHOLE_TOPIC:
        return WHOLE_TOPIC, None
    expect = (f"write `{CHECK_KEY}.{FIELD}`: a non-empty list of the scenes the "
              f"flag rests on, from {scene_ids or 'the topic (it has no scene ids)'}, "
              f"or {WHOLE_TOPIC!r}")
    if not isinstance(value, list) or not value:
        return "scenes", f"{FIELD} is {value!r} on a flagged row - {expect}"
    bad = [s for s in value if not isinstance(s, str) or not s.strip()]
    if bad:
        return "scenes", f"{FIELD} carries {bad!r}, not scene ids - {expect}"
    names = [s.strip() for s in value]
    if len(set(names)) != len(names):
        return "scenes", f"{FIELD} names a scene twice ({names}) - {expect}"
    unknown = [s for s in names if s not in scene_ids]
    if unknown:
        return "scenes", (f"{FIELD} names {unknown}, which the topic does not have "
                          f"in {STAGE_FILE} - {expect}")
    return "scenes", None


def check_document(doc, stage_doc):
    """`[(topic_id, kind, scenes, problem)]` for every flagged row of a `02`."""
    ids = topic_scene_ids(stage_doc)
    out = []
    for row in _rows(doc):
        kind, problem = check_row(row, ids.get(row["topic_id"], []))
        if kind is None:
            continue
        out.append((row["topic_id"], kind, row[CHECK_KEY].get(FIELD), problem))
    return out


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------
USAGE = ("usage: sensitivity_scenes.py <02-compliance-checker.json> "
         "[<01-trend-hunter.json>]\n"
         "  checks that every flagged row names the scenes its flag rests on "
         f"(`{CHECK_KEY}.{FIELD}`: a list of the topic's scene ids, or "
         f"{WHOLE_TOPIC!r}); exit 1 when a row does not ({TASK}). "
         f"Default <01>: {STAGE_FILE} beside the 02 file.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen(argv, USAGE)  # CF-0777
    if rc is not None:
        return rc
    if not argv or len(argv) > 2:
        print(USAGE)
        return 2
    out_path = Path(argv[0])
    stage_path = Path(argv[1]) if len(argv) > 1 else out_path.parent / STAGE_FILE
    try:
        doc = json.loads(out_path.read_text())
        stage_doc = json.loads(stage_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read the batch: {exc}")
        return 2
    stage = doc.get("stage_checked")
    if stage and stage != STAGE_CHECKED:
        print(f"refusing: {out_path.name} was written about {stage!r}; the scenes "
              f"of a flag are written by the {STAGE_CHECKED} pass only - a script "
              f"is one scene already ({TASK})")
        return 2
    rows = check_document(doc, stage_doc)
    problems = 0
    for topic_id, kind, scenes, problem in rows:
        if problem:
            problems += 1
            print(f"{topic_id}: MISSING - {problem}")
        elif kind == WHOLE_TOPIC:
            print(f"{topic_id}: flag on the whole topic - its hold stands whatever "
                  f"scene the script takes")
        else:
            print(f"{topic_id}: flag on {scenes} - a script on another scene "
                  f"lifts its hold ({RESOLVED_REASON_CODE})")
    whole = sum(1 for r in rows if r[1] == WHOLE_TOPIC and not r[3])
    tied = sum(1 for r in rows if r[1] == "scenes" and not r[3])
    print(f"\n{len(rows)} flagged: {tied} tied to scenes, {whole} whole topic, "
          f"{problems} without a valid `{FIELD}`"
          + (" - fix those rows and run this again" if problems else ""))
    return 1 if problems else 0


@runlog.script("compliance-checker", "sensitivity-scenes", name="sensitivity_scenes.py")
def cli():
    """CF-0107 accounting: main()'s return code becomes the exit code inside the
    run event, so a row without its scenes (1) or a usage error (2) is recorded
    as `failed`. No model call, no external binary: no `child` event."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
