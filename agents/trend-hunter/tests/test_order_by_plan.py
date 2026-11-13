#!/usr/bin/env python3
"""CF-0601: the stage knows itself; the batch's order is the run plan's.

The order of a batch's stages lives in one place, the channel's run plan
(`channels/<channel>.json` -> `run_plan`, read by the root's
`python3 shared/run_plan.py show <channel>`; CF-0202/0203/0204). The root's
guard (`tests/test_run_plan.py::test_no_document_lists_the_order_again`) reads
the root's documents only, so this repository holds the same rule for its own:

  * the SKILL points at the plan for where the stage sits;
  * the batch is opened by the plan's root stage `batch-start` - the hunter's
    own `grep ... || batch-start` is the fallback for a run outside the plan,
    in its own block, not part of the stage's first act;
  * the batch is closed by the plan's `always` stages - the SKILL never writes
    `batch-done`;
  * no document here lists the stages in sequence again (the README's one
    mermaid block is the root template's diagram, held by
    test_readme_layout.py).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SKILL = REPO / ".claude" / "skills" / "trend-hunter" / "SKILL.md"
README = REPO / "README.md"

STAGE_NAMES = ("Trend Hunter", "Compliance", "Compliance Checker", "Footage Indexer",
               "Content Researcher", "Video Editor", "frame-judge", "Frame Judge",
               "trend-hunter", "compliance-shortlist", "footage-indexer",
               "content-researcher", "compliance-scripts", "video-editor",
               "pool-maintenance", "batch-start", "batch-done", "monitors", "triage")
ARROW = re.compile(r"-->|──►|→|->|=>")


def _fences(text):
    return re.findall(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M)


def _docs():
    return [SKILL, README] + sorted((REPO / "docs").glob("*.md"))


def _names_in(line):
    return {n for n in STAGE_NAMES
            if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", line)}


def test_the_skill_points_at_the_plan():
    text = SKILL.read_text()
    assert "run_plan.py show" in text, "SKILL.md does not point at `python3 shared/run_plan.py show`"
    assert "run_plan.py show" in README.read_text(), "README does not point at the run plan"


def test_the_first_act_does_not_open_the_batch():
    blocks = [b for _, b in _fences(SKILL.read_text())]
    first = [b for b in blocks if "stage-start trend-hunter" in b]
    assert len(first) == 1, f"one block with `stage-start trend-hunter` expected, got {len(first)}"
    assert "batch-start" not in first[0], \
        "the stage's first act opens the batch - that is the plan's `batch-start` stage"


def test_the_outside_the_plan_fallback_is_kept_and_labelled():
    text = SKILL.read_text()
    fallback = [b for _, b in _fences(text) if re.search(r"runlog\S*\"?\s+batch-start", b, re.I)]
    assert len(fallback) == 1, "the `|| batch-start` fallback for a run outside the plan is gone"
    assert fallback[0].lstrip().startswith("mkdir") and "grep -q '\"batch-start\"'" in fallback[0]
    i = text.index(fallback[0])
    assert "outside the plan" in text[max(0, i - 400):i], \
        "the batch-start fallback is not introduced as the outside-the-plan case"


def test_the_skill_never_closes_the_batch():
    text = SKILL.read_text()
    for _, body in _fences(text):
        assert not re.search(r"runlog\S*\"?\s+batch-done", body, re.I), "SKILL.md writes batch-done"
    assert "orchestrator closes the batch" not in text
    assert "is the first stage, so it opens the batch" not in text
    assert "`always`" in text, "the close does not point at the plan's `always` stages"


def test_no_document_lists_the_order_again():
    bad = []
    for f in _docs():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if len(ARROW.findall(line)) >= 2 and len(_names_in(line)) >= 3:
                bad.append(f"{f.relative_to(REPO)}:{i}: {line.strip()[:120]}")
        for lang, body in _fences(f.read_text()):
            if lang == "mermaid" and f != README:
                bad.append(f"{f.relative_to(REPO)}: a mermaid diagram")
            starts = set(re.findall(r"stage-start\s+([a-z0-9-]+)", body))
            if len(starts) >= 2:
                bad.append(f"{f.relative_to(REPO)}: a block opening stages {sorted(starts)}")
    assert not bad, "documents that list the order again:\n" + "\n".join(bad)


def test_the_guard_catches_an_old_listing():
    line = "Trend Hunter ──► Compliance ──► Footage Indexer ──► Content Researcher"
    assert len(ARROW.findall(line)) >= 2 and len(_names_in(line)) >= 3


def _run():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
