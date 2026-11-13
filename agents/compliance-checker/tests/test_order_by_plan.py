#!/usr/bin/env python3
"""CF-0602: the stage knows itself; the batch's order is the run plan's.

The order of a batch's stages lives in one place, the channel's run plan
(`channels/<channel>.json` -> `run_plan`, read by the root's
`python3 shared/run_plan.py show <channel>`; CF-0202/0203/0204). The root's
guard (`tests/test_run_plan.py::test_no_document_lists_the_order_again`) reads
the root's documents only, so this repository holds the same rule for its own
(the same guard as trend-hunter's, CF-0601):

  * the SKILL says what each of its two passes judges - `compliance-shortlist`
    judges `01-trend-hunter.json`, `compliance-scripts` judges
    `03-content-researcher.json` - and points at the plan for where they sit;
  * the batch is opened by the plan's root stage `batch-start` and closed by
    the plan's `always` stages - this stage writes neither;
  * no document here lists the stages in sequence again (the README's one
    mermaid block is the root template's diagram, held by
    test_readme_layout.py).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SKILL = REPO / ".claude" / "skills" / "compliance-checker" / "SKILL.md"
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


def _head():
    """The SKILL's opening, before its first section."""
    text = SKILL.read_text()
    return text[:text.index("\n## ")]


def test_the_skill_points_at_the_plan():
    assert "run_plan.py show" in _head(), \
        "the SKILL's opening does not point at `python3 shared/run_plan.py show`"
    assert "run_plan.py show" in README.read_text(), "README does not point at the run plan"


def test_each_pass_is_named_by_its_plan_stage_and_its_input():
    head = _head()
    for stage, judged in (("compliance-shortlist", "01-trend-hunter.json"),
                          ("compliance-scripts", "03-content-researcher.json")):
        lines = [l for l in head.splitlines() if f"`{stage}`" in l]
        assert lines, f"the SKILL's opening does not name the plan stage `{stage}`"
        assert any(judged in l for l in lines), \
            f"`{stage}` is not said to judge `{judged}`"
    for stage in ("compliance-shortlist", "compliance-scripts"):
        assert f"`{stage}`" in README.read_text(), f"README does not name `{stage}`"


def test_the_old_place_list_is_gone():
    head = _head()
    assert "After Trend Hunter" not in head and "After Content Researcher" not in head, \
        "the SKILL places its passes by the neighbouring agents again"
    assert "orchestrator" not in SKILL.read_text(), \
        "the SKILL leans on an orchestrator's order instead of the run plan"


def test_the_stage_neither_opens_nor_closes_the_batch():
    text = SKILL.read_text()
    for _, body in _fences(text):
        assert not re.search(r"runlog\S*\"?\s+batch-(start|done)", body, re.I), \
            "SKILL.md writes batch-start / batch-done"
    assert "root stage `batch-start`" in text, "the open does not point at the plan's `batch-start`"
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
