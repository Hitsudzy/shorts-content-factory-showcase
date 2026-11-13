"""CF-0416: which QC failures are cosmetic, and the explicit admission of a
video to the frame judge despite them.

Batch `2026-09-27T0929Z`, mechanism L. The frame judge takes a video whose
`05-video-editor.json` record says `qc.passed: true`. The third kaijura
render failed QC on attempt 3/3 on one rule only - `meme_caption_blank_blocks`,
a meme block with none of our captions under it - and went to the user as
`needs_you`; to have it judged at all, the orchestrator told the operators to
write `qc.passed: true` into a hand-made record. That is a false record: QC
did fail, and the judge's own SKILL says the gate never edits 05.

The fix is a field, not an edit. `qc.passed` stays what QC said. When every
failure of a verdict is on a rule the channel calls cosmetic, the record
carries

    "judge_admitted_despite": ["meme_caption_blank_blocks"]

- the rules QC failed on, sorted, no repeats - and a video with that field is
a candidate for the judge (root `scripts/frame_judge_gate.py` reads it). A
video that failed on anything else has no such field at all.

Rule names. QC reports its failures as sentences; `qc_render.failure_gate()`
names the gate of each (GATE_KEYWORDS), and the rule is the `measured` key
that gate counts in when it has one (`meme_caption` -> the
`meme_caption_blank_blocks` rows), else the gate's own short name
(`caption`, `bed`, ...). `qc.failed_rules` in the record lists them, one per
failure, in the order of `qc.failures`.

The setting. `channels/<id>.json#video_editor.qc_cosmetic_rules` (a list of
rule names), `DEFAULT_RULES` when the channel does not say. A rule of the hard
list or a failure no keyword names (`other`) is never cosmetic, whatever the
setting says: the loader drops it and says so in `dropped`.
"""
import json
from pathlib import Path

import qc_render
import repo_paths

FIELD = "judge_admitted_despite"
RULES_FIELD = "failed_rules"
CONFIG_KEY = "video_editor.qc_cosmetic_rules"
DEFAULT_RULES = ("meme_caption_blank_blocks",)

# gate (qc_render.GATE_KEYWORDS) -> the `measured` key its rows are in.
GATE_RULES = {
    "meme_caption": "meme_caption_blank_blocks",   # CF-0379
    "panel": "panel_cut_blocks",                   # CF-0327
    "subject": "subject_offscreen_blocks",         # CF-0294
    "frozen": "frozen_clip_blocks",
    "background": "background_hole_blocks",        # CF-0337
    "repeat": "repeated_pictures",                 # CF-0337
}
# Never cosmetic: the hard list of the score model (a broken stream or frame,
# the length, sound, foreign text) and a failure QC could not name.
NEVER_COSMETIC = frozenset({"stream", "resolution", "duration", "black", "silence",
                            "clipping", "burned_text", "other"})


def rule_of(failure):
    gate = qc_render.failure_gate(failure)
    return GATE_RULES.get(gate, gate)


def rules_of(failures):
    """One rule name per failure line, in order."""
    return [rule_of(f) for f in failures or []]


def load(channel, root=None):
    """`{"rules": [...], "source": "...", "dropped": [...]}` for a channel id
    (or a path to a channel `.json`). A missing file, a missing key or a value
    that is not a list of strings reads as DEFAULT_RULES / "default"."""
    root = Path(root) if root else repo_paths.FACTORY_ROOT
    rules, source = list(DEFAULT_RULES), "default"
    if channel:
        path = (Path(channel) if str(channel).endswith(".json")
                else root / "channels" / f"{channel}.json")
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = None
        section, name = CONFIG_KEY.split(".")
        value = ((cfg or {}).get(section) or {}).get(name) \
            if isinstance((cfg or {}).get(section), dict) else None
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            try:
                shown = path.relative_to(root)
            except ValueError:
                shown = path
            rules, source = list(value), f"{shown}#{CONFIG_KEY}"
    dropped = [r for r in rules if r in NEVER_COSMETIC]
    return {"rules": [r for r in rules if r not in NEVER_COSMETIC],
            "source": source, "dropped": dropped}


def admitted_despite(qc, cosmetic):
    """The sorted rules a failed QC verdict is admitted to the judge despite,
    or None. None on a passed verdict, on a verdict with no failure lines, and
    on one where any failure is on a rule outside `cosmetic` (a load() result
    or a plain list of rule names)."""
    if not qc or qc.get("passed") is not False:
        return None
    failures = qc.get("failures") or []
    if not failures:
        return None
    allowed = set(cosmetic.get("rules") if isinstance(cosmetic, dict) else cosmetic or [])
    allowed -= NEVER_COSMETIC
    rules = rules_of(failures)
    if not all(r in allowed for r in rules):
        return None
    return sorted(set(rules))
