#!/usr/bin/env python3
"""How this repository asks the Video Editor for a block plan.

The two halves of one call, lifted out of `check_block_capacity.py` (CF-0284,
where they were written) when a second gate ahead of it needed them: CF-0277
gave `check_anchor_cadence.py` - the first and cheapest gate of the stage -
the same question, and a gate that runs *before* the pool is measured may not
import the gate that measures it. The move is the direction of the dependency
and nothing else; `check_block_capacity` and `check_alternate_sides` re-export
both names, so every caller keeps the import it had.

What it raises is `check_anchor_coverage.CannotAnswer` itself, not one of the
gates' own subclasses of it: `check_two_sources.CannotJudge` cannot be
imported from here without a cycle (it imports the cadence gate, which imports
this file), and the base class is what every gate's `main` already catches.

`plan_blocks.py` is the stub that runs on the Editor's interpreter
(`agents/video-editor/.venv`) and imports its `rhythm.py`. Nothing about block
boundaries is computed on this side of the process boundary - that is the
point of the child process, and the reason the answer carries the Editor's own
constants back with it.
"""
import json
import subprocess
from pathlib import Path

from _runlog import runlog
from check_anchor_coverage import CannotAnswer, EDITOR_PY_REL, EDITOR_REL
from check_narration_budget import find_root

PLANNER_REL = Path("scripts") / "plan_blocks.py"
EDITOR_SCRIPTS_REL = Path("scripts")
PATTERNS_REL = Path("patterns")
DEFAULT_TIMEOUT = 120


def planner_paths(root=None, editor_python=None, planner=None, editor_scripts=None,
                  patterns=None):
    """Where the stub, the Editor's interpreter and the patterns are.

    Nothing is imported: `rhythm.py` belongs to the Video Editor's checkout and
    runs on its venv (CF-0140), the same way the coverage preflight does.

    `patterns` (CF-0277) is the factory root's `patterns/` directory, which the
    stub reads through the Editor's own `rhythm.load_pattern()` so that the
    plan is laid out under the pattern's drawn hold ceiling - the layout the
    Editor will actually cut, rather than the pre-CF-0276 one. A missing
    directory is not fatal here: the stub answers `pattern_read: false` and the
    caller decides whether its question can be put without the band. It is the
    one the band belongs to (`check_anchor_cadence.hold_ceiling()`) that
    refuses to judge without it.
    """
    root = Path(root) if root else find_root()
    editor = root / EDITOR_REL
    here = Path(__file__).resolve().parent
    paths = {
        "planner": Path(planner) if planner else here / PLANNER_REL.name,
        "python": Path(editor_python) if editor_python else editor / EDITOR_PY_REL,
        "editor_scripts": (Path(editor_scripts) if editor_scripts
                           else editor / EDITOR_SCRIPTS_REL),
        "patterns": Path(patterns) if patterns else root / PATTERNS_REL,
    }
    for key in ("planner", "python"):
        if not paths[key].exists():
            raise CannotAnswer(
                f"no {key} at {paths[key]} - the block plan is the Video Editor's rule "
                f"(`rhythm.plan_segments()`), asked for on its own venv; this repository "
                f"carries no copy of it and claims nothing without it")
    return paths


def run_planner(entries, paths, timeout=DEFAULT_TIMEOUT, margin_fraction=None,
                last_margin_fraction=None):
    """One child process for the whole batch. Returns `(plans, constants)`.

    `margin_fraction` (CF-0303) is the share of the hold band's width the
    caller wants every block of the estimated layout to stay under the top by,
    and `last_margin_fraction` the same for the last block. They are passed
    through to the stub because the comparison with the top belongs to the
    Editor (`rhythm.over_band_top()`), and the estimate is this side's - the
    number travels, the arithmetic does not. A caller that asks for no margin
    (`check_block_capacity.py`, `check_alternate_sides.py`) sends neither flag
    and gets the answer it always got.
    """
    cmd = [str(paths["python"]), str(paths["planner"]),
           "--editor-scripts", str(paths["editor_scripts"])]
    if paths.get("patterns") and Path(paths["patterns"]).is_dir():
        cmd += ["--patterns", str(paths["patterns"])]
    if margin_fraction is not None:
        cmd += ["--hold-margin-fraction", repr(float(margin_fraction))]
        if last_margin_fraction is not None:
            cmd += ["--hold-margin-last-fraction", repr(float(last_margin_fraction))]
    payload = json.dumps({"scripts": entries})
    try:
        cp = runlog.run_child(cmd, tool="plan_blocks.py", input=payload,
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CannotAnswer(f"could not run the block planner: {exc}")
    if cp.returncode != 0:
        raise CannotAnswer(f"plan_blocks.py exited {cp.returncode}:\n"
                           f"{(cp.stderr or '').strip()[:2000]}")
    try:
        answer = json.loads(cp.stdout)
        plans = {p["script_id"]: p for p in answer["plans"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise CannotAnswer(f"plan_blocks.py answered something else: {exc}")
    return plans, (answer.get("constants") or {})
