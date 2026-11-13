#!/usr/bin/env python3
"""CF-0356: a script reaches the voice only through the Researcher's text gates.

The hole
--------
`everyday-sorcery-2` (`pipeline/rebuilds/2026-09-23T1344Z`) was voiced with 5
anchors and 15.3 s of speech after the last one. The Researcher's cadence gate
(`check_anchor_cadence.py`, CF-0233/CF-0277, the tail reading since CF-0353)
refuses exactly that script - but the script was written 2026-09-15, before the
gate existed, and a rebuild copies `03-content-researcher.json` byte for byte
and runs only the pool gates. The script carried no `anchor_cadence` record at
all, and the Editor learnt of the defect from `build_render_plan.py`
(`pattern_ceiling` / `no_next_block`) - after the TTS had been paid for.

The decision: run the gate, then refuse
---------------------------------------
Before the TTS (`script_anchors.py preflight`, step 3 of the SKILL) every text
gate below is asked of the script:

* the script already carries the gate's record, with the reading this stage
  depends on, and the record's action is the gate's own "pass" - nothing is
  run, the script goes on;
* otherwise the Editor runs **the Researcher's own gate** on the batch file,
  read-only (`--script-id`, `--out` into the video's work directory, never
  `--write`: `03` is the Researcher's artifact, not ours), and judges the
  record it returns by the same rule.

A gate that does not pass is a refusal before the TTS - gate `text_gates`,
funnel code `thin_scene` (the cadence gate's own code), a sidecar under
`work/<slug>/` that `write_batch_metadata.py` carries to `refusals[]`. A gate
that cannot judge (its exit 3, a missing sibling checkout) is "cannot answer",
never a pass and never a refusal.

Why run it rather than refuse on the missing record alone: calling a sibling
repo's script as-is is what this stage already does with the Footage Indexer
(`repo_paths.INDEXER_SCRIPTS`), and what the Researcher does with our
`plan_blocks.py` - the gate is arithmetic over the text (0.2-0.7 s, no model).
Refusing on the absence alone would refuse every rebuild of a script older
than the gate, including the ones that would pass it; the result is videos,
and the question the record answers can be asked for the price of one
subprocess. The Editor cannot rewrite a script, so a gate that says
"rewrite" is, here, a refusal: the script goes back to the Researcher with the
gate's own sentence (the `tail:` remedy, the `anchor needed` address).

Where the list comes from
-------------------------
`REQUIRED` names the Researcher's scripts and the reading of each record this
stage depends on - `anchor_cadence.layout` is what `build_render_plan.py`
cites when it refuses a block (CF-0277). CF-0370 adds `block_capacity.picture_band`,
the same band counted in pictures (CF-0365), judged by its own action
(`NESTED`) and never run here when it is missing. Nothing else about a gate is copied
here: the record key (`RECORD_KEY`), the "pass" action (`ACTION_PASS`) and the
exit codes are read out of the gate's own source (`ast`, not an import - the
gate's imports are the Researcher's business), and a name is judged only
while the Researcher's SKILL still lists it among the stage's checkers (the
step table). A gate the SKILL drops stops being asked here without an edit.

Stdlib only, like the rest of scripts/.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_paths  # noqa: E402
from _runlog import runlog  # noqa: E402 - CF-0107: the gate's run is a child event

RESEARCHER = repo_paths.sibling("content-researcher")
RESEARCHER_SCRIPTS = RESEARCHER / "scripts"
RESEARCHER_SKILL = RESEARCHER / ".claude" / "skills" / "content-researcher" / "SKILL.md"

# The Researcher's text gates whose record a script must carry before its
# voice is paid for: (the gate's script, the reading of its record this stage
# depends on). Names only - see the module docstring.
REQUIRED = (
    ("check_anchor_cadence.py", "layout"),
    # CF-0370: the pattern's block band read in pictures (CF-0365). The
    # cadence gate's `block_band` counts segments; under `even` the resolver
    # cuts a segment into several blocks, and 004 of 2026-09-23T1722Z passed
    # it at 11 and reached the planner at 22.
    ("check_block_capacity.py", "picture_band"),
)

# CF-0370: readings that are a record of their own inside the gate's record
# and are judged by *their* action, not the record's. `block_capacity`'s own
# action is usually `warn` (CF-0330: the pool gates warn and the script goes
# on), so "the record passed" would refuse every script it ever warned about;
# the picture band inside it has its own verdict, and `pass` and its `note`
# (over the top but inside the replay's error, CF-0365) both go on.
#
# `pass_actions` names the gate's own constants, read off its source like the
# rest of the contract. `run` says whether this stage may run the gate when
# the reading is missing: the capacity gate replays the pool from
# `check_anchor_coverage.py --out` (`--reports`, the CLIP matcher's answer,
# the one expensive thing the Researcher runs), which this stage has no copy
# of - so a script older than CF-0365 goes on with a note instead. What it
# would have been refused for is what the resolver budgets since CF-0370 (the
# `even` chain under a drawn top), and `pattern_ceiling` still stands after
# it; the record, where there is one, is judged.
NESTED = {
    "picture_band": {"pass_actions": ("ACTION_PASS", "PICTURE_NOTE"),
                     "run": False},
}

TIMEOUT = 120
SOURCE_RECORDED = "recorded"   # the record in 03 answered, nothing was run
SOURCE_RUN = "run"             # the Editor ran the gate on the batch file
SOURCE_SKIPPED = "not_in_skill"
SOURCE_NOT_RECORDED = "not_recorded"  # CF-0370: absent, and not ours to run

# The runlog variable the Researcher's checker writes its own stage events
# under. The gate is our child here, not a Researcher stage: the variable is
# withheld from it so the batch's events do not grow a `content-researcher`
# step after that stage closed. `runlog.run_child()` records the call.
RUNLOG_ENV = "RUNLOG_BATCH"


class CannotJudge(Exception):
    """The gate could not be asked. Never a verdict on a script."""


# --------------------------------------------------------------------------
# what is read out of the Researcher's checkout
# --------------------------------------------------------------------------

def module_constants(path):
    """Top-level `NAME = <literal>` (and `A, B = <literal>, <literal>`)
    assignments of a Python file, without importing it."""
    try:
        tree = ast.parse(Path(path).read_text())
    except (OSError, SyntaxError, ValueError) as exc:
        raise CannotJudge(f"cannot read {path}: {exc}")
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        pairs = []
        if isinstance(target, ast.Name):
            pairs = [(target, value)]
        elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) \
                and len(target.elts) == len(value.elts):
            pairs = list(zip(target.elts, value.elts))
        for t, v in pairs:
            if isinstance(t, ast.Name):
                try:
                    found[t.id] = ast.literal_eval(v)
                except ValueError:
                    continue
    return found


def contract(script_name, scripts_dir=None, reading=None):
    """What this stage needs to know about one gate, read off its source.

    `reading` defaults to the one `REQUIRED` names for the script. A nested
    reading (`NESTED`) the stage never runs needs no exit codes - only the
    record key and the actions that pass it."""
    if reading is None:
        reading = dict(REQUIRED).get(script_name)
    nested = NESTED.get(reading)
    path = Path(scripts_dir or RESEARCHER_SCRIPTS) / script_name
    consts = module_constants(path)
    need = ("RECORD_KEY", "ACTION_PASS")
    if nested:
        need += tuple(n for n in nested["pass_actions"] if n not in need)
    if not nested or nested["run"]:
        need += ("EXIT_CANNOT_JUDGE", "EXIT_USAGE")
    missing = [k for k in need if k not in consts]
    if missing:
        raise CannotJudge(f"{path}: no {', '.join(missing)} at module level - the "
                          f"gate's contract moved; this stage cannot tell its "
                          f"record from its verdict")
    c = {"script": script_name, "path": str(path),
         "record_key": consts["RECORD_KEY"], "action_pass": consts["ACTION_PASS"],
         "exit_cannot_judge": consts.get("EXIT_CANNOT_JUDGE"),
         "exit_usage": consts.get("EXIT_USAGE")}
    if nested:
        c["nested"] = reading
        c["pass_actions"] = [consts[n] for n in nested["pass_actions"]]
        c["runnable"] = nested["run"]
    return c


def skill_checkers(skill=None):
    """The checkers the Researcher's SKILL lists in its step table: the rows
    that start with a backticked `check_*.py`."""
    path = Path(skill or RESEARCHER_SKILL)
    try:
        text = path.read_text()
    except OSError as exc:
        raise CannotJudge(f"cannot read the Researcher's SKILL {path}: {exc}")
    names = set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and cells and cells[0].startswith("`check_"):
            names.add(cells[0].split("`")[1])
    return names


# --------------------------------------------------------------------------
# the judgement
# --------------------------------------------------------------------------

def passes(record, reading, action_pass):
    """A record that answers: it carries the reading and the gate passed it."""
    return (isinstance(record, dict) and reading in record
            and record.get("action") == action_pass)


def nested_passes(record, reading, pass_actions):
    """CF-0370: a nested reading answers by its own action (see `NESTED`)."""
    inner = record.get(reading) if isinstance(record, dict) else None
    return isinstance(inner, dict) and inner.get("action") in pass_actions


def _default_runner(cmd, timeout):
    env = {k: v for k, v in os.environ.items() if k != RUNLOG_ENV}
    try:
        return runlog.run_child(cmd, tool=Path(cmd[1]).name, capture_output=True,
                                text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        # CF-0132: the ceiling is a verdict about the environment, not a value
        raise CannotJudge(f"{Path(cmd[1]).name} did not answer within {timeout}s")


def run_gate(c, batch_file, script_id, out, runner=None, timeout=TIMEOUT):
    """The Researcher's gate on one script, read-only. Returns its record."""
    cmd = [sys.executable, c["path"], str(batch_file), "--script-id", str(script_id),
           "--out", str(out)]
    try:
        cp = (runner or _default_runner)(cmd, timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CannotJudge(f"{c['script']} could not be run: {exc}")
    if cp.returncode in (c["exit_cannot_judge"], c["exit_usage"]):
        tail = " ".join(((cp.stderr or "") + (cp.stdout or "")).split())[-400:]
        raise CannotJudge(f"{c['script']} exit {cp.returncode} - could not judge "
                          f"{script_id}: {tail}")
    try:
        records = json.loads(Path(out).read_text())
    except (OSError, ValueError):
        records = {}
    rec = records.get(script_id) if isinstance(records, dict) else None
    if rec is None:
        # A script the gate could not even phrase the question for (a
        # malformed anchor) has no record and a non-zero exit: its report is
        # the verdict.
        return {"action": None, "reason": " ".join((cp.stdout or "").split())[-600:]
                or f"{c['script']} exit {cp.returncode} and no record"}
    return rec


def judge(batch_file, script, work_dir=None, runner=None, scripts_dir=None,
          skill=None, required=REQUIRED):
    """Every required text gate, asked of one script.

    Returns `{"script_id", "passed", "gates": [...]}`; each gate carries where
    its answer came from (`recorded` / `run` / `not_in_skill`), whether it
    passed, and the gate's own action and reason."""
    sid = script.get("script_id")
    listed = skill_checkers(skill)
    gates = []
    tmp = None
    for name, reading in required:
        if name not in listed:
            gates.append({"script": name, "reading": reading, "source": SOURCE_SKIPPED,
                          "passed": True, "reason": "no longer in the Researcher's "
                          "SKILL step table - not asked"})
            continue
        c = contract(name, scripts_dir, reading)
        key = c["record_key"]
        g = {"script": name, "record": f"{key}.{reading}", "reading": reading}
        rec = script.get(key)
        if c.get("nested"):
            gates.append(judge_nested(g, c, rec, reading))
            continue
        if passes(rec, reading, c["action_pass"]):
            g.update(source=SOURCE_RECORDED, passed=True, action=rec.get("action"))
            gates.append(g)
            continue
        g["recorded"] = ("absent" if rec is None else
                         f"no `{reading}` reading" if reading not in (rec or {}) else
                         f"action {rec.get('action')!r}")
        if work_dir is None:
            tmp = tmp or tempfile.mkdtemp(prefix="text_gates.")
            out_dir = Path(tmp)
        else:
            out_dir = Path(work_dir)
        out = out_dir / f"text_gates.{Path(name).stem}.json"
        fresh = run_gate(c, batch_file, sid, out, runner=runner)
        g.update(source=SOURCE_RUN, out=str(out),
                 passed=passes(fresh, reading, c["action_pass"]),
                 action=fresh.get("action"), reason=fresh.get("reason"))
        for k in ("verdict", "tail", "tail_deliverable", "layout_breaches",
                  "max_block_seconds", "max_gap_seconds", "anchors", "min_anchors"):
            if k in fresh:
                g[k] = fresh[k]
        gates.append(g)
    return {"kind": "text_gates", "script_id": sid,
            "passed": all(g["passed"] for g in gates), "gates": gates}


def judge_nested(g, c, rec, reading):
    """One nested reading (`NESTED`), judged off the record in 03 only."""
    inner = rec.get(reading) if isinstance(rec, dict) else None
    if isinstance(inner, dict):
        ok = nested_passes(rec, reading, c["pass_actions"])
        g.update(source=SOURCE_RECORDED, passed=ok, action=inner.get("action"))
        if not ok:
            g["reason"] = (inner.get("reason") or inner.get("reject_reason")
                           or f"{g['record']} action {inner.get('action')!r}, not "
                           f"one of {c['pass_actions']}")
        for k in ("measured", "band_min", "band_max", "shots", "reject_command"):
            if k in inner:
                g[k] = inner[k]
        return g
    g["recorded"] = ("absent" if rec is None else f"no `{reading}` reading")
    g.update(source=SOURCE_NOT_RECORDED, passed=True, action=None,
             reason=(f"{c['script']} needs the coverage preflight's --reports to "
                     f"replay the pool, which this stage has no copy of - not "
                     f"run; the resolver budgets the `even` chain under a drawn "
                     f"block-count top (CF-0370) and pattern_ceiling stands "
                     f"after it"))
    return g


def failed(verdict):
    return [g for g in verdict["gates"] if not g["passed"]]


def report_lines(verdict):
    lines = []
    for g in verdict["gates"]:
        mark = "ok  " if g["passed"] else "FAIL"
        how = {SOURCE_RECORDED: "recorded in 03",
               SOURCE_RUN: f"not in 03 ({g.get('recorded')}), run by the Editor",
               SOURCE_SKIPPED: "not asked",
               SOURCE_NOT_RECORDED: f"not in 03 ({g.get('recorded')}), not "
                                    f"ours to run - goes on with a note"}[g["source"]]
        lines.append(f"  {mark} {g['script']} [{g.get('record', g['reading'])}] - {how}"
                     + (f": {g.get('action')}" if g["source"] == SOURCE_RUN
                        or (g["source"] == SOURCE_RECORDED and not g["passed"])
                        else ""))
        if not g["passed"] and g.get("reason"):
            lines.append(f"       {g['reason']}")
    return lines
