#!/usr/bin/env python3
"""CF-0603: the stage knows itself; the batch's order is the run plan's.

The order of a batch's stages lives in one place, the channel's run plan
(`channels/<channel>.json` -> `run_plan`, read by the root's
`python3 shared/run_plan.py show <channel>`; CF-0202/0203/0204). The root's
guard (`tests/test_run_plan.py::test_no_document_lists_the_order_again`) reads
the root's documents only, so this repository holds the same rule for its own
(the same guard as trend-hunter's CF-0601 and compliance-checker's CF-0602):

  * the SKILL names its runs by the plan - the stages `footage-indexer` and
    `footage-indexer-reserve` (condition `reserve_refill`) and the handler
    `supplement-describe` (on `thin-pool-supplement`'s exit 10) - and points
    at the plan for where they sit;
  * there is no "Video Editor call" of this stage: the Editor's
    `resolve_anchors.py` runs `match_anchors.py` as a script;
  * the check of the whole pool is the plan's `pool-maintenance`; this stage
    keeps only the 1.3 s `caption_cache.py` guard as its first step;
  * the batch is opened by the plan's root stage `batch-start` and closed by
    the plan's `always` stages - this stage writes neither;
  * no document here lists the stages in sequence again (the README's one
    mermaid block is the root template's diagram, held by
    test_readme_layout.py);
  * every `doc` of the root's plans that points into this SKILL names a
    section that is here.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
import _runlog  # noqa: E402

SKILL = REPO / ".claude" / "skills" / "footage-indexer" / "SKILL.md"
README = REPO / "README.md"
SKILL_REL = "agents/footage-indexer/.claude/skills/footage-indexer/SKILL.md"

STAGE_NAMES = ("Trend Hunter", "Compliance", "Compliance Checker", "Footage Indexer",
               "Content Researcher", "Video Editor", "frame-judge", "Frame Judge",
               "trend-hunter", "compliance-shortlist", "footage-indexer",
               "footage-indexer-reserve", "content-researcher",
               "content-researcher-reserve", "thin-pool-supplement",
               "supplement-describe", "compliance-scripts", "video-editor",
               "pool-maintenance", "batch-start", "batch-done", "monitors", "triage")
ARROW = re.compile(r"-->|──►|→|->|=>")
RUNS = (("footage-indexer", "01b-footage-index.json"),
        ("footage-indexer-reserve", "reserve_refill"),
        ("supplement-describe", "thin-pool-supplement"))


def _fences(text):
    return re.findall(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M)


def _docs():
    return [SKILL, README] + sorted((REPO / "docs").glob("*.md"))


def _names_in(line):
    return {n for n in STAGE_NAMES
            if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", line)}


def _head():
    """The SKILL's front matter and opening, before its first section."""
    text = SKILL.read_text()
    return text[:text.index("\n## ")]


def _section(prefix):
    text = SKILL.read_text()
    start = text.index("\n## " + prefix)
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else len(text)]


def test_the_skill_points_at_the_plan():
    assert "run_plan.py show" in _head(), \
        "the SKILL's opening does not point at `python3 shared/run_plan.py show`"
    assert "run_plan.py show" in README.read_text(), "README does not point at the run plan"


def test_each_run_is_named_by_the_plan():
    head = _head()
    for name, said in RUNS:
        lines = [l for l in head.splitlines() if f"`{name}`" in l]
        assert lines, f"the SKILL's opening does not name the plan entry `{name}`"
        assert any(said in l for l in lines), f"`{name}` is not said with `{said}`"
        assert f"`{name}`" in README.read_text(), f"README does not name `{name}`"
    desc = re.search(r"^description: (.*)$", head, re.M).group(1)
    for name, _ in RUNS:
        assert f"`{name}`" in desc, f"the SKILL's description does not name `{name}`"


def test_the_old_place_list_is_gone():
    text = SKILL.read_text()
    for old in ("invoked before writing and again while editing",
                "Before Content Researcher writes", "While Video Editor edits",
                "second invocation", "After Content Researcher",
                "Video Editor call", "orchestrator"):
        assert old not in text, f"the SKILL places itself by its neighbours again: {old!r}"


def test_the_editor_runs_the_matcher_as_a_script():
    head = _head()
    line = [l for l in head.splitlines() if "match_anchors.py" in l]
    assert line and "resolve_anchors.py" in line[0] and "as a script" in line[0], \
        "the opening does not say the Editor runs match_anchors.py as a script"


def test_the_pool_check_is_pool_maintenance_and_here_is_a_guard():
    sec = _section("Check the pool's freshness")
    assert "`pool-maintenance`" in sec.splitlines()[1], "the heading does not name `pool-maintenance`"
    assert "run_checks.py captions-stale" in sec, \
        "the section does not say what the plan's pool-maintenance runs"
    assert "pool-remeasure-captions" in sec, "the repair handler of the plan is not named"
    blocks = [b for _, b in _fences(sec)]
    assert blocks and blocks[0].strip().startswith("scripts/caption_cache.py"), \
        "the guard (caption_cache.py) is not the section's first command"
    assert "1.3 s" in sec and "guard" in sec


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
