"""CF-0430: the writer's rewrite, on disk, for the suites of the step-6 gates.

A gate re-run on a script whose text and `visual_anchors` are the ones it last
asked to rewrite spends nothing (`scripts/_rewrite_guard.py`). A test that
means "the rewrite came back and failed again" therefore has to rewrite
something. `edit_on_disk()` makes the smallest edit the hash sees and no gate
measures: the `phrase` of every script's first anchor (what the matcher looks
for, not when it is spoken), or - on a script with no anchors - the last word
of its commentary, word count kept.
"""
import json
from pathlib import Path


def edit(script, mark="rewritten"):
    anchors = script.get("visual_anchors")
    if isinstance(anchors, list) and anchors and isinstance(anchors[0], dict):
        phrase = anchors[0].get("phrase") or ""
        tag = f"({mark})"
        anchors[0]["phrase"] = f"{phrase} (again)" if phrase.endswith(tag) else f"{phrase} {tag}"
        return script
    words = (script.get("commentary") or "").split() or [""]
    words[-1] = "again" if words[-1] == mark else mark
    script["commentary"] = " ".join(words)
    return script


def edit_on_disk(path, mark="rewritten"):
    """Every script of the batch file at `path`, edited in place."""
    path = Path(path)
    data = json.loads(path.read_text())
    for script in data.get("scripts", []):
        edit(script, mark)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def reword_on_disk(path):
    """One word of every script's payoff changed, the word count kept: its
    last word gets an `s`. For the gates that read the coverage report
    (`check_block_capacity.py`, `check_alternate_sides.py`), where a new anchor
    phrase makes the report stale before anything is judged; a `beat_text` that
    ends on that word is still found in the speech (the match is a substring).
    Whitespace alone would not do: the hash is taken over the words."""
    path = Path(path)
    data = json.loads(path.read_text())
    for script in data.get("scripts", []):
        words = (script.get("payoff") or "").split() or [""]
        words[-1] = words[-1] + "s"
        script["payoff"] = " ".join(words)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
