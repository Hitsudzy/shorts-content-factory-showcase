#!/usr/bin/env python3
"""CF-0604: the stage knows itself; the batch's order is the run plan's.

The order of a batch's stages lives in one place, the channel's run plan
(`channels/<channel>.json` -> `run_plan`, read by the root's
`python3 shared/run_plan.py show <channel>`; CF-0202/0203/0204). The root's
guard (`tests/test_run_plan.py::test_no_document_lists_the_order_again`) reads
the root's documents only, so this repository holds the same rule for its own
(the same guard as trend-hunter's CF-0601, compliance-checker's CF-0602 and
footage-indexer's CF-0603):

  * the SKILL names its runs by the plan - the stages `content-researcher`
    and `content-researcher-reserve` (after `footage-indexer-reserve`, whose
    condition is `reserve_refill`, `shared/run_checks.py reserve-refill`), the
    machine stage `plan-check-after-supplement` (after `thin-pool-supplement`)
    and its handler `plan-check-anchor-edit` (step 6b's anchor edit) - and
    points at the plan for where they sit;
  * step 6b stays a step inside the stage, and its "check after the
    supplement" is said by the plan's names, not by an orchestrator;
  * the batch is opened by the plan's root stage `batch-start` and closed by
    the plan's `always` stages - this stage writes neither;
  * no document here lists the stages in sequence again (the README's one
    mermaid block is the root template's diagram, held by
    test_readme_layout.py);
  * every `doc` / `skill` of the root's plans that points into this SKILL
    names a section or a step that is here.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
import _runlog  # noqa: E402

SKILL = REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md"
README = REPO / "README.md"
SKILL_REL = "agents/content-researcher/.claude/skills/content-researcher/SKILL.md"

STAGE_NAMES = ("Trend Hunter", "Compliance", "Compliance Checker", "Footage Indexer",
               "Content Researcher", "Video Editor", "frame-judge", "Frame Judge",
               "trend-hunter", "compliance-shortlist", "footage-indexer",
               "footage-indexer-reserve", "content-researcher",
               "content-researcher-reserve", "thin-pool-supplement",
               "plan-check-after-supplement", "plan-check-anchor-edit",
               "supplement-describe", "compliance-scripts", "video-editor",
               "pool-maintenance", "batch-start", "batch-done", "monitors", "triage")
ARROW = re.compile(r"-->|──►|→|->|=>")
RUNS = (("content-researcher", "03-content-researcher.json"),
        ("content-researcher-reserve", "reserve_refill"),
        ("plan-check-after-supplement", "thin-pool-supplement"),
        ("plan-check-anchor-edit", "6b"))
STEP = re.compile(r"^(\d+[a-z]?)\. \*\*", re.M)


def _fences(text):
    return re.findall(r"^\s*```([a-z]*)\n(.*?)^\s*```", text, re.S | re.M)


def _docs():
    return [SKILL, README] + sorted((REPO / "docs").glob("*.md"))


def _names_in(line):
    return {n for n in STAGE_NAMES
            if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", line)}


def _head():
    """The SKILL's front matter and opening, before its first section."""
    text = SKILL.read_text()
    return text[:text.index("\n## ")]


def _step(label):
    """The body of the numbered step `label` of the Procedure (e.g. '6b')."""
    text = SKILL.read_text()
    text = text[text.index("\n## Procedure"):]
    marks = list(STEP.finditer(text))
    for i, m in enumerate(marks):
        if m.group(1) == label:
            end = marks[i + 1].start() if i + 1 < len(marks) else text.find("\n## ", m.start())
            return text[m.start():end]
    raise AssertionError(f"the SKILL has no step {label}")


def test_the_skill_points_at_the_plan():
    assert "run_plan.py show" in _head(), \
        "the SKILL's opening does not point at `python3 shared/run_plan.py show`"
    assert "run_plan.py show" in README.read_text(), "README does not point at the run plan"


def test_each_run_is_named_by_the_plan():
    head = _head()
    readme = README.read_text()
    desc = re.search(r"^description: (.*)$", head, re.M).group(1)
    for name, said in RUNS:
        lines = [l for l in head.splitlines() if f"`{name}`" in l]
        assert lines, f"the SKILL's opening does not name the plan entry `{name}`"
        assert any(said in l for l in lines), f"`{name}` is not said with `{said}`"
        assert f"`{name}`" in readme, f"README does not name `{name}`"
        assert f"`{name}`" in desc, f"the SKILL's description does not name `{name}`"


def test_the_reserve_condition_is_the_plans():
    head = _head()
    assert "shared/run_checks.py reserve-refill" in head, \
        "the opening does not say how the plan answers `reserve_refill`"
    line = [l for l in head.splitlines() if "`content-researcher-reserve`" in l
            and l.lstrip().startswith("2.")]
    assert line and "`footage-indexer-reserve`" in line[0], \
        "the reserve call is not tied to the plan's `footage-indexer-reserve`"
    step1 = _step("1")
    assert "`content-researcher-reserve`" in step1 and "`footage-indexer-reserve`" in step1 \
        and "`reserve_refill`" in step1, "step 1's reserve half is not said by the plan's names"


def test_step_6b_stays_a_step_and_its_aftercheck_is_the_plans():
    sec = _step("6b")
    i = sec.index("**The check after the supplement**")
    after = sec[i:]
    for name in ("`thin-pool-supplement`", "`plan-check-after-supplement`",
                 "`plan-check-anchor-edit`"):
        assert name in after, f"the check after the supplement does not name {name}"
    assert "--write --after-supplement" in after and "--pending-after-supplement" in after


def test_the_old_place_list_is_gone():
    text = SKILL.read_text()
    for old in ("orchestrator", "runs after this stage", "Trend Hunter (or the",
                "the gate before compliance pass 2", "run the supplement step first"):
        assert old not in text, f"the SKILL places itself by its neighbours again: {old!r}"
    assert "orchestrator" not in README.read_text()


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


def _resolves(rest, heads, slugs, steps):
    """Whether `rest` - what follows the SKILL path in a plan's reference -
    finds its place here: `#<heading slug>` / `#<step>` or `(<heading
    prefix>)` / `(step <label>)`. A bare path needs nothing."""
    if not rest:
        return True
    if rest.startswith("#"):
        return rest[1:] in slugs or rest[1:] in steps
    if rest.startswith("("):
        sec = rest[1:rest.rindex(")")]
        m = re.fullmatch(r"step (\d+[a-z]?)", sec)
        if m:
            return m.group(1) in steps
        return any(h.startswith(sec) for h in heads)
    return False


def test_the_resolver_bites():
    heads, slugs, steps = ["Procedure"], {"procedure"}, {"6", "6b"}
    for good in ("", "#6b", "#procedure", "(step 6b)", "(Proc)"):
        assert _resolves(good, heads, slugs, steps), good
    for bad in ("#6c", "#notes", "(step 9)", "(Notes)", "junk"):
        assert not _resolves(bad, heads, slugs, steps), bad




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
