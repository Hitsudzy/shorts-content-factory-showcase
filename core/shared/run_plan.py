#!/usr/bin/env python3
"""CF-0202: the run plan of a channel - its stages, their order, arguments,
dependencies and contracts - and the one reader that validates it.

Until CF-0202 `channels/<channel>.json` held the *parameters* of a fixed chain
and no key named a stage, an agent or an order: the sequence lived in prose
(five `SKILL.md`, the root README, `docs/running-a-batch.md`) and in how an LLM
operator read it. `run_plan` is the chain itself, as data, so that a different
channel can describe a different *graph* - other stages, other edges - and not
just other values (grill 2026-09-12 "Второй канал"). The executor that walks it
is CF-0203; this module only reads and refuses.

    python3 shared/run_plan.py validate <channel> [--root DIR] [--skip-missing-checkouts]
    python3 shared/run_plan.py show     <channel> [--root DIR] [--json]

`validate` exits 0 on a valid plan, 1 with one line per error, 2 on a bad call
(no channel file, no `run_plan` key). `show` prints the stages in run order
(handlers indented under the step that calls them) and exits like `validate`.
A valid plan of a channel that may not start yet (`start_refusal`, CF-0659: a
placeholder voice) gets one `НЕ СТАРТУЕТ` line on stderr; the exit stays 0 -
the executor's `run` is what refuses.

The format (`channels/<channel>.json` -> `run_plan`):

    {
      "version": 1,
      "batch_dir": "pipeline/{channel}/{batch_id}",
      "stages": [ <stage>, ... ]          # declaration order breaks ties in `show`
    }

A stage:

    id          unique slug; what `after`, `when.ran` and `on_exit.run` name
    title       one line for a human
    kind        "machine"  - commands the executor runs itself (`steps`)
                "llm"      - an LLM works the stage by a SKILL.md (`skill`, `model`),
                             headless (`claude -p`) under CF-0203
                "decision" - the executor stops and asks (`question`), and takes
                             `default` when nobody answers - no stage waits for a
                             human (CF-0317)
    owner       "root" or an agent of `agents.lock.json`: whose code the stage is
    marker      the `runlog stage-start/stage-done` name (`runlog.AGENT_NAMES`,
                `runlog.NON_AGENT_STAGES`, "publisher") or null for a step that has
                no stage markers (batch-start, the close, the pre-batch reads)
    marker_by   who writes that marker pair: "skill" (the SKILL.md does it itself,
                today's rule for every agent stage) or "executor"; required with
                a marker
    role        whose transcript pays for it today: "operator" (the orchestrator
                session) or "subagent" (a stage operator); null for pure machine
    after       ids of the stages that finish first (done or skipped)
    trigger     "on_exit" for a handler: not in the `after` order, run only when
                a step's `on_exit` names it; a handler has no `after`
    always      true for a stage of the close: it runs even when a stage before
                it failed or was skipped (batch-done, monitors, triage, ...)
    when        run only if - one condition, or a list of them (all must hold):
                  {"cmd": [argv], "exit": [codes]}  a probe's exit code
                  {"exists": "<glob under the batch dir>"}
                  {"ran": "<stage id>"}             that stage ran (not skipped)
                  {"check": "<name>"}               a named rule of CONDITIONS
                otherwise the stage is skipped and the run goes on
    steps       machine: [{"argv": [...], "ok_exit": [0], "on_exit": {...},
                           "env": {...}, "env_unset": [...], "glob": bool}]
                `on_exit` maps an exit code to {"run": <handler id>, "then":
                "rerun"|"continue"} or {"then": "rerun"} (no handler); any code
                in neither `ok_exit` nor `on_exit` fails the stage;
                `note_on_exit` maps an exit code the stage goes on with (one of
                `ok_exit` or `on_exit`) to a text the executor puts into the
                stage's `stage-done --note` (CF-0204);
                an `on_exit` act may carry `"rerun_env": {name: text}` - the
                environment of the rerun that follows it (CF-0793: the plan
                check is told an anchor-edit pass ran before it);
                `"exhausted": {"argv_add": [...], "note": text}` - when the
                reruns are spent the step runs once more with these arguments
                appended and that run's exit decides (`ok_exit`: the stage is
                done with the note; anything else fails it) instead of failing
                at the limit (CF-0793: `--final` closes the scripts still
                waiting, the batch goes on with the rest)
    skill       llm/decision: the SKILL.md path under the root (`#anchor` allowed)
    model       llm: "sonnet" | "opus" | "haiku"
    timeout_min llm: the stage's ceiling in minutes of wall (CF-0204). Past it the
                executor kills the stage's process group and fails the stage with
                the reason; none = no ceiling
    args        llm: {name: template} handed to the SKILL as its arguments
    question, decided_by ("llm"|"human"), outcomes [..], default   decision
    notify      decision by human (CF-0735): "bus" (the default) - the default taken
                is one `needs_human` notification; "quiet" - no notification, one
                quiet line in the run state (`quiet`) and the executor's journal
                (a safety net elsewhere calls the user, e.g. the Studio insurance)
    say         decision by human (CF-0735): the Russian line the user gets (or the
                quiet line says) instead of the question - placeholders as anywhere
    fallback    llm: what happens when the LLM cannot do it (no login, no browser)
    consumes    contract files under the batch dir the stage reads
    produces    contract files it writes first (one producer per file)
    updates     contract files it rewrites in place (needs an upstream producer)
    doc, note   where the rule is written, and anything else a reader needs

The rebuild modes (CF-0668, optional) - how a rebuild of chosen videos of a
finished batch (`pipeline/rebuilds/<ts>`) uses the same stages:

    "rebuild": {"modes": {"<mode>": {
        "title":       one line for a human
        "from":        the first stage that runs; every stage before it in the
                       run order stands for the copied records and does not run
        "copy":        files of the source batch copied byte for byte (their
                       `batch_id` stays the source's: that is `rebuild_of`, CF-0416)
        "only_videos": copied files whose `scripts[]` / `results[]` keep only the
                       chosen videos' entries
        "work":        paths under the source's `work/` copied too (`{slug}` per video)
        "skip":        stages after `from` a rebuild leaves out (no batch-done, CF-0339)
        "args":        {stage: {name: template}} added to that llm stage's args;
                       besides the placeholders below `{source}` `{videos}`
                       `{scripts}` `{topics}` `{exclusions}` `{notes}`, filled
                       when the rebuild starts
    }}}

A mode is refused when a stage it runs consumes a file it neither copies nor
produces upstream. The block is not part of the plan's fingerprint (a rebuild
reads it once, into its `run-state.json`). `shared/batch_control.py rebuild`
writes the starting state - the copied stages `skipped` - and resumes the
executor on it: the rebuild runs, stops and resumes as any batch.

Templates may use only `PLACEHOLDERS`: {root} {channel} {batch} {batch_id}
{runlog} {python} {agent_dir}, and {python:<agent>} {dir:<agent>} for another
owner's interpreter and checkout.

What is refused, before any run: an unknown owner (not in the lock) or a
missing checkout, a script, program or SKILL.md that is not on disk, a
duplicate id, an `after`/`when.ran`/`on_exit.run` that names no stage, a cycle,
a stage the entry does not reach (or a handler nobody calls), a consumed file
nobody produces - or that only a stage *not upstream* produces -, two producers
of one file, an unknown marker, placeholder, key, kind or condition.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = "run_plan"
VERSION = 1

KINDS = ("machine", "llm", "decision")
MODELS = ("sonnet", "opus", "haiku")
ROLES = ("operator", "subagent")
MARKER_BY = ("skill", "executor")
DECIDED_BY = ("llm", "human")
HUMAN_NOTIFY = ("bus", "quiet")          # CF-0735: decision.notify
THEN = ("rerun", "continue")
ROOT_OWNER = "root"

# Markers the runlog accepts (shared/runlog/runlog.py): every agent, every
# stage that is nobody's turn, and the Publisher of docs/run-accounting.md.
# Read from the runlog itself when it imports; the literal is the fallback
# for a checkout where it does not.
_FALLBACK_MARKERS = ("trend-hunter", "compliance-checker", "footage-indexer",
                     "content-researcher", "video-editor", "pool-maintenance",
                     "frame-judge", "thin-pool-supplement", "publisher")


def known_markers():
    try:
        sys.path.insert(0, str(ROOT / "shared" / "runlog"))
        import runlog  # noqa: PLC0415
        return tuple(runlog.AGENT_NAMES) + tuple(runlog.NON_AGENT_STAGES) + ("publisher",)
    except Exception:                                   # noqa: BLE001
        return _FALLBACK_MARKERS
    finally:
        if sys.path and sys.path[0] == str(ROOT / "shared" / "runlog"):
            sys.path.pop(0)


# Named conditions: a rule the docs state that no single command answers.
# Each is evaluated by `shared/run_checks.py` (CHECKS, the same names; CF-0203),
# also a CLI (`run_checks.py reserve-refill <batch>`); the doc is where it is written.
CONDITIONS = {
    "reserve_refill": (
        "the Researcher refused topics whose slot the reserve has not answered "
        "yet (03 -> skipped[] less 01b -> reserve_substitution substitutions[]/"
        "unmatched[] `replaced`, N > 0; CF-0645) and the reserve still holds some "
        "(01b -> reserve_substitution.remaining[], M > 0)",
        "docs/pipeline.md#when-a-topic-is-lost-after-the-cut-cf-0306"),
    "below_shortlist_refill": (
        "the Researcher's refusals the reserve round will try to fill outnumber the "
        "reserve (N > M, shared/run_checks.py refill_counts), an unspent below_shortlist "
        "topic is left in 01-trend-hunter.json -> skipped_topics[], and the first round "
        "has no record in work/below-shortlist-refill.json yet (shared/below_shortlist.py; "
        "the Search budget is the round's own decision, CF-0882)",
        "docs/pipeline.md#when-the-reserve-runs-out-the-topics-below-the-shortlist-cf-0882"),
    "below_shortlist_refill_late": (
        "below_shortlist_refill for the late reserve round (the round after the "
        "supplement's plan check, CF-0645): N > M, the queue below the shortlist not "
        "empty, no `late` record yet (CF-0882)",
        "docs/pipeline.md#when-the-reserve-runs-out-the-topics-below-the-shortlist-cf-0882"),
    "below_shortlist_refill_judge": (
        "the reserve round after the frame judge would run but for an empty reserve "
        "(reserve_after_judge with the reserve clause left out: refused topics, slots "
        "short, one round, the time guard), the slots short outnumber the reserve, the "
        "queue below the shortlist is not empty, no `judge` record yet (CF-0882)",
        "docs/pipeline.md#when-the-reserve-runs-out-the-topics-below-the-shortlist-cf-0882"),
    "reserve_after_judge": (
        "the frame judge refused topics (06-frame-judge.json: no video of the topic "
        "passed the gate) whose slot nothing answered yet, fewer topics have a video "
        "through the gate than the channel's slots (scope.max_titles_per_batch), the "
        "reserve still holds some (stopcock._remaining_reserve), no round ran yet "
        "(no 01b -> reserve_substitution record at frame_judge_refusal - one round), and "
        "the round (this batch's own stage times, else 2 h) fits before the end of the "
        "YouTube quota day and the factory's next planned batch (CF-0801, CF-0798)",
        "docs/pipeline.md#when-the-frame-judge-refuses-a-video-cf-0798"),
    "repair_after_judge": (
        "the frame judge refused a video for a defect in one or two blocks (thin strip, "
        "smear, cut subject, wrong person, foreign in the hook) whose topic has no other "
        "video through the gate, the blocks have a shot or a meme card to exclude, mending "
        "them can lift the score to N, and no repair round ran yet (no "
        "work/repair-requests.json - one pass; shared/judge_repair.py, CF-0881)",
        "docs/pipeline.md#when-the-frame-judge-refuses-a-video-for-one-or-two-blocks-cf-0881"),
    "repair_judge_pending": (
        "the Editor re-rendered a video of the repair round (work/repair-results.json "
        "outcome `rendered`) that 06-frame-judge.json -> repairs[] holds no record of yet: "
        "the judge owes verdicts on its changed blocks (CF-0881)",
        "docs/pipeline.md#when-the-frame-judge-refuses-a-video-for-one-or-two-blocks-cf-0881"),
    "judge_candidates": (
        "05-video-editor.json names a video the frame judge owes a verdict on "
        "(scripts/frame_judge_gate.py deliverable(): QC passed with no NEEDS-YOU, or "
        "admitted to the judge), or there is no readable 05 (CF-0707)",
        ".claude/skills/frame-judge/SKILL.md"),
    "nothing_to_judge": (
        "05-video-editor.json is readable and names no video to judge - the gate "
        "writes 06-frame-judge.json with videos: [] and the sentence why (CF-0707)",
        ".claude/skills/frame-judge/SKILL.md"),
    "write_candidates": (
        "02-compliance-checker.json and 01b-footage-index.json hand the Content Researcher "
        "at least one topic, or one of them is not readable (the Researcher's own "
        "no-waiting exit names it) - the complement of nothing_to_write (CF-0763)",
        "scripts/researcher_nothing_to_write.py"),
    "nothing_to_write": (
        "02-compliance-checker.json and 01b-footage-index.json are readable and hand the "
        "Content Researcher no topic - the script writes 03-content-researcher.json with "
        "scripts: [] and the sentence why, and the stop-cock reads stop (CF-0763)",
        "scripts/researcher_nothing_to_write.py"),
}

PLACEHOLDERS = ("root", "channel", "batch", "batch_id", "runlog", "python", "agent_dir")
PREFIXED = ("python", "dir")           # {python:<agent>}, {dir:<agent>}
_PH = re.compile(r"\{([^{}]*)\}")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Programs an argv may start with that are not files of a checkout.
SYSTEM_PROGRAMS = ("python3", "git")

STAGE_KEYS = {
    "common": {"id", "title", "kind", "owner", "marker", "marker_by", "role", "after",
               "trigger", "always", "when", "consumes", "produces", "updates", "doc", "note"},
    "machine": {"steps"},
    "llm": {"skill", "model", "args", "fallback", "timeout_min"},
    "decision": {"question", "decided_by", "outcomes", "default", "skill", "notify", "say"},
}
STEP_KEYS = {"argv", "ok_exit", "on_exit", "env", "env_unset", "glob", "note", "note_on_exit",
             "exhausted"}
ON_EXIT_KEYS = {"run", "then", "note", "rerun_env"}
EXHAUSTED_KEYS = {"argv_add", "note"}
PLAN_KEYS = {"_doc", "version", "batch_dir", "stages", "rebuild"}

# CF-0668: the rebuild modes of a plan (`run_plan.rebuild.modes.<mode>`).
REBUILD_KEY = "rebuild"
REBUILD_KEYS = {"_doc", "modes"}
REBUILD_MODE_KEYS = {"title", "from", "copy", "only_videos", "work", "skip", "args", "doc"}
# What a mode's `args` may say besides PLACEHOLDERS - filled once, by
# shared/batch_control.py rebuild(), when the rebuild starts.
REBUILD_PLACEHOLDERS = ("source", "videos", "scripts", "topics", "exclusions", "notes")
REBUILDS_GROUP = "rebuilds"            # pipeline/rebuilds/<ts> (write_batch_metadata CF-0416)
REBUILD_FILTERED = ("scripts", "results")   # the per-video lists `only_videos` trims


class PlanError(Exception):
    """A plan that cannot be read at all (no file, no key)."""


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def channel_file(channel, root=None):
    return Path(root or ROOT) / "channels" / f"{channel}.json"


def load(channel, root=None):
    """The `run_plan` block of a channel, or PlanError."""
    path = channel_file(channel, root)
    if not path.is_file():
        raise PlanError(f"no channel config {path}")
    try:
        cfg = json.loads(path.read_text())
    except ValueError as e:
        raise PlanError(f"{path}: not JSON ({e})") from e
    try:
        stub = _channel_ids().no_pipeline_reason(cfg, channel)
    except _channel_ids().ChannelIdError as e:
        raise PlanError(str(e)) from e
    if stub:
        raise PlanError(f"{path}: у канала нет run_plan - {stub} (CF-0562, `status: "
                        f"{cfg.get('status')}`)")
    if KEY not in cfg:
        raise PlanError(f"{path}: no `{KEY}` key - this channel has no run plan")
    return cfg[KEY]


def _channel_ids():
    """shared/channel_ids.py of this checkout, by path (the no-pipeline mark)."""
    import importlib.util
    name = "channel_ids"
    mod = sys.modules.get(name)
    here = Path(__file__).resolve().parent / "channel_ids.py"
    if mod is None or Path(getattr(mod, "__file__", "") or "").resolve() != here:
        spec = importlib.util.spec_from_file_location(name, here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def start_refusal(channel, root=None):
    """CF-0659: why a batch of this channel may not start although its plan is
    valid, or None. Today one reason: the voice is still a placeholder
    (`channel_ids.voice_placeholder_reason` - `TODO` in `voice_profile`).
    `validate` and `show` print it and still exit 0 (the plan is valid);
    `run_executor.py run` refuses (exit 2), the dry run prints it first."""
    path = channel_file(channel, root)
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return _channel_ids().voice_placeholder_reason(cfg, channel)


def lock_agents(root=None):
    """Agent name -> path from agents.lock.json (empty when unreadable)."""
    try:
        data = json.loads((Path(root or ROOT) / "agents.lock.json").read_text())
        return {name: spec.get("path", f"agents/{name}")
                for name, spec in data.get("agents", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from _strings(x)
    elif isinstance(node, dict):
        for x in node.values():
            yield from _strings(x)


def _placeholder_errors(sid, node, agents):
    errs = []
    for s in _strings(node):
        for name in _PH.findall(s):
            if name in PLACEHOLDERS:
                continue
            head, _, agent = name.partition(":")
            if head in PREFIXED and agent:
                if agent not in agents:
                    errs.append(f"stage {sid}: placeholder {{{name}}} names {agent!r}, "
                                f"which is not an agent of agents.lock.json")
                continue
            errs.append(f"stage {sid}: unknown placeholder {{{name}}} in {s!r} "
                        f"(known: {', '.join('{%s}' % p for p in PLACEHOLDERS)}, "
                        f"{{python:<agent>}}, {{dir:<agent>}})")
    return errs


def _owner_dir(owner, agents, root):
    return root if owner == ROOT_OWNER else root / agents[owner]


def _resolve_path(token, owner, agents, root):
    """A template that names a file -> (Path, agent whose checkout holds it or
    None), or None when the token is not a path template."""
    m = re.match(r"^\{(root|agent_dir|dir:[a-z0-9-]+)\}/(.+)$", token)
    if not m:
        return None
    head, rest = m.groups()
    if any(c in rest for c in "*?[{"):
        return None
    if head == "root":
        base, agent = root, None
        for name, p in agents.items():
            if rest.startswith(p.rstrip("/") + "/"):
                agent = name
    elif head == "agent_dir":
        base = _owner_dir(owner, agents, root)
        agent = None if owner == ROOT_OWNER else owner
    else:
        agent = head.split(":", 1)[1]
        if agent not in agents:
            return None
        base = root / agents[agent]
    return base / rest, agent


def _argv_errors(sid, where, argv, owner, agents, root, missing_checkouts):
    """The program of an argv (and the script it runs) must exist."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return [f"stage {sid}: {where}: argv must be a non-empty list of strings"]
    if root is None:
        return []
    errs = []
    prog = argv[0]
    targets = []
    if prog in SYSTEM_PROGRAMS:
        if shutil.which(prog) is None:
            errs.append(f"stage {sid}: {where}: program {prog!r} is not on PATH")
        if prog == "python3" and len(argv) > 1:
            targets.append(argv[1])
    elif prog == "{runlog}":
        targets.append("{root}/scripts/runlog")
    elif prog == "{python}" or prog.startswith("{python:"):
        if len(argv) < 2:
            errs.append(f"stage {sid}: {where}: {prog} with no script")
        else:
            targets.append(argv[1])
    else:
        targets.append(prog)
    for t in targets:
        r = _resolve_path(t, owner, agents, root)
        if r is None:
            errs.append(f"stage {sid}: {where}: entry point {t!r} is not a path under "
                        f"{{root}}/, {{agent_dir}}/ or {{dir:<agent>}}/")
            continue
        path, agent = r
        if agent and agent in missing_checkouts:
            continue
        if not path.exists():
            errs.append(f"stage {sid}: {where}: script {t!r} does not exist ({path})")
    return errs


def _when_errors(sid, when, ids, owner, agents, root, missing):
    if not isinstance(when, dict) or len(when) not in (1, 2):
        return [f"stage {sid}: when must be one of {{cmd, exit}}, {{exists}}, {{ran}}, {{check}}"]
    if "cmd" in when:
        errs = _argv_errors(sid, "when.cmd", when["cmd"], owner, agents, root, missing)
        codes = when.get("exit")
        if not isinstance(codes, list) or not codes or not all(isinstance(c, int) for c in codes):
            errs.append(f"stage {sid}: when.cmd needs `exit`, a non-empty list of exit codes")
        if set(when) - {"cmd", "exit"}:
            errs.append(f"stage {sid}: when: unknown key(s) {sorted(set(when) - {'cmd', 'exit'})}")
        return errs
    if len(when) != 1:
        return [f"stage {sid}: when: one condition per stage, got {sorted(when)}"]
    (k, v), = when.items()
    if k == "exists":
        return [] if isinstance(v, str) and v and not v.startswith("/") and ".." not in v \
            else [f"stage {sid}: when.exists must be a relative glob under the batch dir"]
    if k == "ran":
        if v == sid:
            return [f"stage {sid}: when.ran names the stage itself"]
        return [] if v in ids else [f"stage {sid}: when.ran names unknown stage {v!r}"]
    if k == "check":
        return [] if v in CONDITIONS else \
            [f"stage {sid}: when.check {v!r} is not a known condition ({', '.join(CONDITIONS)})"]
    return [f"stage {sid}: when: unknown condition kind {k!r}"]


def _contract_list(sid, st, key):
    v = st.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        return [], [f"stage {sid}: {key} must be a list of file names"]
    bad = [x for x in v if x.startswith("/") or ".." in Path(x).parts]
    return v, [f"stage {sid}: {key}: {x!r} must be a path under the batch dir" for x in bad]


def _ancestors(sid, after):
    seen, todo = set(), list(after.get(sid, []))
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        todo.extend(after.get(x, []))
    return seen


def find_cycle(after):
    """One cycle of the `after` graph as a list of ids, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in after}
    stack = []

    def visit(n):
        color[n] = GREY
        stack.append(n)
        for m in after.get(n, []):
            if m not in color:
                continue
            if color[m] == GREY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                c = visit(m)
                if c:
                    return c
        stack.pop()
        color[n] = BLACK
        return None

    for n in after:
        if color[n] == WHITE:
            c = visit(n)
            if c:
                return list(reversed(c))
    return None


def validate(plan, root=None, skip_missing_checkouts=False):
    """Every error of a run plan as a list of lines; [] is a valid plan.

    `root` is the factory root the paths are checked against (None: no disk
    checks at all - the structure only). With `skip_missing_checkouts` an
    agent whose checkout is not on this disk is not an error and the paths
    under it are not checked (a root test tree without `agents/`); its name
    is still checked against the lock."""
    root = Path(root) if root is not None else None
    errs = []
    if not isinstance(plan, dict):
        return [f"{KEY} must be an object"]
    unknown = set(plan) - PLAN_KEYS
    if unknown:
        errs.append(f"{KEY}: unknown key(s) {sorted(unknown)}")
    if plan.get("version") != VERSION:
        errs.append(f"{KEY}: version must be {VERSION}, got {plan.get('version')!r}")
    if not isinstance(plan.get("batch_dir"), str) or "{batch_id}" not in plan.get("batch_dir", ""):
        errs.append(f"{KEY}: batch_dir must be a template holding {{batch_id}}")
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        return errs + [f"{KEY}: stages must be a non-empty list"]

    agents = lock_agents(root if root is not None else ROOT)
    markers = known_markers()
    missing = set()
    if root is not None:
        for name, p in agents.items():
            if not (root / p).is_dir():
                missing.add(name)

    ids, seen = [], set()
    for i, st in enumerate(stages):
        sid = st.get("id") if isinstance(st, dict) else None
        if not isinstance(sid, str) or not _ID.match(sid):
            errs.append(f"stage #{i}: id must be a lowercase slug, got {sid!r}")
            continue
        if sid in seen:
            errs.append(f"stage {sid}: duplicate id")
        seen.add(sid)
        ids.append(sid)
    by_id = {}
    for st in stages:
        if isinstance(st, dict) and st.get("id") in seen and st["id"] not in by_id:
            by_id[st["id"]] = st

    after, handlers, called = {}, set(), {}
    for sid, st in by_id.items():
        kind = st.get("kind")
        if kind not in KINDS:
            errs.append(f"stage {sid}: kind must be one of {KINDS}, got {kind!r}")
            continue
        allowed = STAGE_KEYS["common"] | STAGE_KEYS[kind]
        extra = set(st) - allowed
        if extra:
            errs.append(f"stage {sid}: unknown key(s) for kind {kind}: {sorted(extra)}")
        if not isinstance(st.get("title"), str) or not st.get("title"):
            errs.append(f"stage {sid}: title is required")
        owner = st.get("owner")
        if owner != ROOT_OWNER and owner not in agents:
            errs.append(f"stage {sid}: owner {owner!r} is neither 'root' nor an agent of "
                        f"agents.lock.json ({', '.join(sorted(agents)) or 'none readable'})")
            owner = ROOT_OWNER
        elif owner in missing and not skip_missing_checkouts:
            errs.append(f"stage {sid}: owner {owner!r} has no checkout at {agents[owner]} "
                        f"(scripts/agents sync)")
        marker = st.get("marker")
        if marker is not None:
            if marker not in markers:
                errs.append(f"stage {sid}: marker {marker!r} is not a runlog stage "
                            f"({', '.join(markers)})")
            if st.get("marker_by") not in MARKER_BY:
                errs.append(f"stage {sid}: marker_by must be one of {MARKER_BY} with a marker")
        elif "marker_by" in st:
            errs.append(f"stage {sid}: marker_by without a marker")
        if st.get("role") not in ROLES + (None,):
            errs.append(f"stage {sid}: role must be one of {ROLES} or null")
        if "always" in st and not isinstance(st["always"], bool):
            errs.append(f"stage {sid}: always must be true or false")

        trig = st.get("trigger")
        dep = st.get("after", [])
        if trig is not None:
            if trig != "on_exit":
                errs.append(f"stage {sid}: trigger must be 'on_exit', got {trig!r}")
            if dep:
                errs.append(f"stage {sid}: a handler (trigger on_exit) has no `after`")
            handlers.add(sid)
            dep = []
        if not isinstance(dep, list) or not all(isinstance(d, str) for d in dep):
            errs.append(f"stage {sid}: after must be a list of stage ids")
            dep = []
        for d in dep:
            if d == sid:
                errs.append(f"stage {sid}: after names the stage itself")
            elif d not in by_id:
                errs.append(f"stage {sid}: after names unknown stage {d!r}")
        after[sid] = [d for d in dep if d in by_id and d != sid]

        if "when" in st:
            conds = st["when"] if isinstance(st["when"], list) else [st["when"]]
            if not conds:
                errs.append(f"stage {sid}: when is an empty list")
            for c in conds:
                errs += _when_errors(sid, c, by_id, owner, agents, root, missing)

        if kind == "machine":
            steps = st.get("steps")
            if not isinstance(steps, list) or not steps:
                errs.append(f"stage {sid}: a machine stage needs `steps`")
                steps = []
            for j, step in enumerate(steps):
                where = f"steps[{j}]"
                if not isinstance(step, dict):
                    errs.append(f"stage {sid}: {where} must be an object")
                    continue
                if set(step) - STEP_KEYS:
                    errs.append(f"stage {sid}: {where}: unknown key(s) {sorted(set(step) - STEP_KEYS)}")
                errs += _argv_errors(sid, where, step.get("argv"), owner, agents, root, missing)
                ok = step.get("ok_exit", [0])
                if not isinstance(ok, list) or not all(isinstance(c, int) for c in ok):
                    errs.append(f"stage {sid}: {where}: ok_exit must be a list of exit codes")
                    ok = []
                for code, act in (step.get("on_exit") or {}).items():
                    if not re.fullmatch(r"-?\d+", str(code)):
                        errs.append(f"stage {sid}: {where}: on_exit key {code!r} is not an exit code")
                    elif int(code) in ok:
                        errs.append(f"stage {sid}: {where}: exit {code} is both ok and on_exit")
                    if not isinstance(act, dict) or act.get("then") not in THEN \
                            or set(act) - ON_EXIT_KEYS:
                        errs.append(f"stage {sid}: {where}: on_exit {code} must be "
                                    f"{{\"run\": <handler>, \"then\": rerun|continue}}")
                        continue
                    renv = act.get("rerun_env")
                    if renv is not None and (
                            act.get("then") != "rerun" or not isinstance(renv, dict) or not renv
                            or not all(isinstance(k, str) and isinstance(v, str)
                                       for k, v in renv.items())):
                        errs.append(f"stage {sid}: {where}: on_exit {code} rerun_env must be a "
                                    f"non-empty {{name: text}} on a `then: rerun`")
                    if "run" in act:
                        called.setdefault(act["run"], []).append(sid)
                        if act["run"] not in by_id:
                            errs.append(f"stage {sid}: {where}: on_exit {code} runs unknown "
                                        f"stage {act['run']!r}")
                errs += _note_on_exit_errors(sid, where, step, ok)
                ex = step.get("exhausted")
                if ex is not None:
                    reruns = any(isinstance(a, dict) and a.get("then") == "rerun"
                                 for a in (step.get("on_exit") or {}).values())
                    if not isinstance(ex, dict) or set(ex) - EXHAUSTED_KEYS \
                            or not isinstance(ex.get("argv_add"), list) or not ex["argv_add"] \
                            or not all(isinstance(a, str) and a for a in ex["argv_add"]) \
                            or not isinstance(ex.get("note", ""), str):
                        errs.append(f"stage {sid}: {where}: exhausted must be "
                                    f"{{\"argv_add\": [<args>], \"note\": <text>}}")
                    elif not reruns:
                        errs.append(f"stage {sid}: {where}: exhausted without an on_exit "
                                    f"`then: rerun` - nothing can run out")
        elif kind == "llm":
            errs += _skill_errors(sid, st.get("skill"), agents, root, missing, required=True)
            if st.get("model") not in MODELS:
                errs.append(f"stage {sid}: model must be one of {MODELS}, got {st.get('model')!r}")
            if "args" in st and not isinstance(st["args"], dict):
                errs.append(f"stage {sid}: args must be an object of templates")
            if "timeout_min" in st:
                t = st["timeout_min"]
                if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
                    errs.append(f"stage {sid}: timeout_min must be a positive number of "
                                f"minutes, got {t!r}")
        else:
            if not isinstance(st.get("question"), str) or not st.get("question"):
                errs.append(f"stage {sid}: a decision needs its `question`")
            if st.get("decided_by") not in DECIDED_BY:
                errs.append(f"stage {sid}: decided_by must be one of {DECIDED_BY}")
            outs = st.get("outcomes")
            if not isinstance(outs, list) or len(outs) < 2 or not all(isinstance(o, str) for o in outs):
                errs.append(f"stage {sid}: a decision needs at least two `outcomes`")
                outs = []
            if st.get("default") not in outs:
                errs.append(f"stage {sid}: `default` must be one of its outcomes - the run "
                            f"takes it when nobody answers (CF-0317)")
            if "skill" in st:
                errs += _skill_errors(sid, st["skill"], agents, root, missing, required=False)
            if "notify" in st and st["notify"] not in HUMAN_NOTIFY:            # CF-0735
                errs.append(f"stage {sid}: notify must be one of {HUMAN_NOTIFY}, got "
                            f"{st['notify']!r}")
            if ("notify" in st or "say" in st) and st.get("decided_by") != "human":
                errs.append(f"stage {sid}: notify/say are for decided_by human only")
            if "say" in st and (not isinstance(st["say"], str) or not st["say"].strip()):
                errs.append(f"stage {sid}: say must be a non-empty line")
        errs += _placeholder_errors(sid, st, agents)

    for h, callers in called.items():
        if h in by_id and h not in handlers:
            errs.append(f"stage {h}: named by on_exit of {', '.join(sorted(set(callers)))} "
                        f"but has no `trigger: on_exit`")

    cycle = find_cycle(after)
    if cycle:
        errs.append("cycle in `after`: " + " -> ".join(cycle))

    # Reachability: one entry, every ordered stage reachable from it, every
    # handler called by a step of a reachable stage.
    ordered = [s for s in by_id if s not in handlers]
    entries = [s for s in ordered if not after.get(s)]
    if len(entries) != 1:
        errs.append(f"a plan has exactly one entry stage (no `after`); found "
                    f"{len(entries)}: {', '.join(entries) or 'none'} - every other "
                    f"stage is unreachable from the start")
    if entries and not cycle:
        children = {}
        for s, deps in after.items():
            for d in deps:
                children.setdefault(d, []).append(s)
        reach, todo = set(), [entries[0]]
        while todo:
            x = todo.pop()
            if x in reach:
                continue
            reach.add(x)
            todo.extend(children.get(x, []))
        for s in ordered:
            if s not in reach:
                errs.append(f"stage {s}: unreachable from the entry stage {entries[0]!r}")
        for h in sorted(handlers):
            callers = [c for c in called.get(h, []) if c in reach or c in handlers]
            if not callers:
                errs.append(f"stage {h}: unreachable - a handler no step's on_exit runs")

    # Contracts.
    producers, prod_lists, upd_lists, cons_lists = {}, {}, {}, {}
    for sid, st in by_id.items():
        for key, store in (("produces", prod_lists), ("updates", upd_lists),
                           ("consumes", cons_lists)):
            v, e = _contract_list(sid, st, key)
            errs += e
            store[sid] = v
        for f in prod_lists[sid]:
            if f in producers:
                errs.append(f"contract {f}: produced by both {producers[f]} and {sid} "
                            f"(one producer per file; a later stage `updates` it)")
            else:
                producers[f] = sid
    if not cycle:
        writers = {}
        for sid in by_id:
            for f in prod_lists[sid] + upd_lists[sid]:
                writers.setdefault(f, set()).add(sid)
        for sid in by_id:
            # A handler runs inside the stage that calls it: it sees what that
            # stage's ancestors (and the stage itself) wrote.
            if sid in handlers:
                anc = set()
                for c in called.get(sid, []):
                    anc |= _ancestors(c, after) | {c}
            else:
                anc = _ancestors(sid, after)
            for f in cons_lists[sid] + upd_lists[sid]:
                if f in prod_lists[sid] and f not in upd_lists[sid]:
                    continue
                if f not in producers:
                    errs.append(f"stage {sid}: consumes {f}, which no stage produces")
                elif not (writers[f] & anc):
                    errs.append(f"stage {sid}: consumes {f}, but its producer "
                                f"{producers[f]} is not upstream of it")
    if REBUILD_KEY in plan and not cycle and not errs:
        errs += rebuild_errors(plan)
    return errs


# --------------------------------------------------------------------------
# CF-0668: the rebuild modes
# --------------------------------------------------------------------------

def rebuild_modes(plan):
    """`{mode: spec}` of the plan's rebuild block ({} when it has none)."""
    block = plan.get(REBUILD_KEY) if isinstance(plan, dict) else None
    modes = block.get("modes") if isinstance(block, dict) else None
    return modes if isinstance(modes, dict) else {}


def rebuild_layout(plan, mode):
    """`{"copied": [ids], "skipped": [ids], "run": [ids]}` of a rebuild mode, in
    run order: the stages before `from` stand for the copied files (they do
    not run), `skip` are left out of a rebuild, the rest run as in a batch.
    KeyError for an unknown mode. Assumes a valid plan."""
    spec = rebuild_modes(plan)[mode]
    ids = order(plan)
    start = ids.index(spec["from"])
    skip = set(spec.get("skip") or [])
    return {"copied": ids[:start],
            "skipped": [s for s in ids[start:] if s in skip],
            "run": [s for s in ids[start:] if s not in skip]}


def _rebuild_placeholder_errors(where, node, agents):
    errs = []
    for s in _strings(node):
        for name in _PH.findall(s):
            if name in PLACEHOLDERS or name in REBUILD_PLACEHOLDERS:
                continue
            head, _, agent = name.partition(":")
            if head in PREFIXED and agent in agents:
                continue
            errs.append(f"{where}: unknown placeholder {{{name}}} in {s!r} (a rebuild "
                        f"knows {', '.join('{%s}' % p for p in REBUILD_PLACEHOLDERS)} "
                        f"besides the plan's)")
    return errs


def rebuild_errors(plan):
    """Every error of `run_plan.rebuild` (CF-0668), for a plan whose stages are
    valid. A mode is refused when its stages could not run on what it copies:
    every file a running stage consumes is copied or produced by a running
    stage upstream of it."""
    block = plan.get(REBUILD_KEY)
    where = f"{KEY}.{REBUILD_KEY}"
    if not isinstance(block, dict):
        return [f"{where} must be an object"]
    errs = []
    if set(block) - REBUILD_KEYS:
        errs.append(f"{where}: unknown key(s) {sorted(set(block) - REBUILD_KEYS)}")
    modes = block.get("modes")
    if not isinstance(modes, dict) or not modes:
        return errs + [f"{where}.modes must be a non-empty object"]
    by_id = {s["id"]: s for s in plan["stages"]}
    ids = order(plan)
    after = {s["id"]: list(s.get("after") or []) for s in plan["stages"]}
    agents = lock_agents()
    for mode, spec in modes.items():
        w = f"{where}.modes.{mode}"
        if not _ID.match(str(mode)):
            errs.append(f"{w}: a mode name is a lowercase slug")
        if not isinstance(spec, dict):
            errs.append(f"{w} must be an object")
            continue
        if set(spec) - REBUILD_MODE_KEYS:
            errs.append(f"{w}: unknown key(s) {sorted(set(spec) - REBUILD_MODE_KEYS)}")
        if not isinstance(spec.get("title"), str) or not spec.get("title"):
            errs.append(f"{w}: title is required")
        frm = spec.get("from")
        if frm not in ids:
            errs.append(f"{w}: from {frm!r} is not a stage of the run order")
            continue
        lists = {}
        for k in ("copy", "only_videos", "work", "skip"):
            v = spec.get(k, [])
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                errs.append(f"{w}: {k} must be a list of names")
                v = []
            lists[k] = v
        if not lists["copy"]:
            errs.append(f"{w}: copy names no file - a rebuild starts from the batch's records")
        for f in lists["copy"]:
            if "/" in f or f.startswith("."):
                errs.append(f"{w}: copy {f!r} is not a file of the batch directory")
        for f in lists["only_videos"]:
            if f not in lists["copy"]:
                errs.append(f"{w}: only_videos {f!r} is not copied")
        for f in lists["work"]:
            if f.startswith(("/", ".")) or ".." in f.split("/"):
                errs.append(f"{w}: work {f!r} must be a path under work/")
        start = ids.index(frm)
        for sid in lists["skip"]:
            if sid not in ids:
                errs.append(f"{w}: skip {sid!r} is not a stage of the run order")
            elif ids.index(sid) <= start:
                errs.append(f"{w}: skip {sid!r} is not after `from` {frm!r}")
        running = [s for s in ids[start:] if s not in lists["skip"]]
        if frm in lists["skip"]:
            errs.append(f"{w}: `from` {frm!r} is skipped")
        args = spec.get("args", {})
        if not isinstance(args, dict):
            errs.append(f"{w}: args must be an object {{stage: {{name: template}}}}")
            args = {}
        for sid, a in args.items():
            if sid not in running:
                errs.append(f"{w}: args for {sid!r}, which does not run in this mode")
            elif by_id[sid].get("kind") != "llm":
                errs.append(f"{w}: args for {sid!r}, which is not an llm stage")
            if not isinstance(a, dict) or not all(isinstance(v, str) for v in a.values()):
                errs.append(f"{w}: args.{sid} must be an object of templates")
                continue
            errs += _rebuild_placeholder_errors(f"{w}: args.{sid}", a, agents)
        # contracts: what a running stage reads is copied or written upstream
        have = set(lists["copy"])
        for sid in running:
            st = by_id[sid]
            anc = _ancestors(sid, after)
            upstream = set(have)
            for o in running:
                if o in anc:
                    upstream |= set(by_id[o].get("produces") or []) | \
                        set(by_id[o].get("updates") or [])
            for f in list(st.get("consumes") or []) + list(st.get("updates") or []):
                if f not in upstream:
                    errs.append(f"{w}: stage {sid} consumes {f}, which the rebuild neither "
                                f"copies nor produces upstream of it (copy it or skip {sid})")
    return errs


def _note_on_exit_errors(sid, where, step, ok):
    """CF-0204: `note_on_exit` names codes the stage goes on with - a code that
    fails the stage has its own reason in the stage-done note already."""
    notes = step.get("note_on_exit")
    if notes is None:
        return []
    if not isinstance(notes, dict) or not notes:
        return [f"stage {sid}: {where}: note_on_exit must be an object {{exit code: text}}"]
    errs = []
    goes_on = {str(c) for c in ok} | {str(c) for c in (step.get("on_exit") or {})}
    for code, text in notes.items():
        if not re.fullmatch(r"-?\d+", str(code)):
            errs.append(f"stage {sid}: {where}: note_on_exit key {code!r} is not an exit code")
        elif str(int(code)) not in goes_on:
            errs.append(f"stage {sid}: {where}: note_on_exit {code} is neither ok_exit nor "
                        f"on_exit - a code that fails the stage says so itself")
        if not isinstance(text, str) or not text.strip():
            errs.append(f"stage {sid}: {where}: note_on_exit {code} must be a non-empty text")
    return errs


def _skill_errors(sid, skill, agents, root, missing, required):
    if not isinstance(skill, str) or not skill:
        return [f"stage {sid}: an llm stage needs `skill`, the SKILL.md path"] if required else \
            [f"stage {sid}: skill must be a path"]
    rel = skill.split("#", 1)[0]
    if rel.startswith("/") or ".." in Path(rel).parts or not rel.endswith(".md"):
        return [f"stage {sid}: skill {skill!r} must be a .md path under the root"]
    if root is None:
        return []
    for name, p in agents.items():
        if rel.startswith(p.rstrip("/") + "/") and name in missing:
            return []
    if not (root / rel).is_file():
        return [f"stage {sid}: skill {rel} does not exist"]
    return []


# --------------------------------------------------------------------------
# order
# --------------------------------------------------------------------------

def order(plan):
    """Stage ids in run order: a topological order of `after`, ties broken by
    declaration order. Handlers are left out (see `handlers_of`). Assumes a
    valid plan."""
    stages = [s for s in plan["stages"] if not s.get("trigger")]
    pos = {s["id"]: i for i, s in enumerate(stages)}
    deps = {s["id"]: set(s.get("after", [])) & set(pos) for s in stages}
    done, out = set(), []
    while len(out) < len(stages):
        ready = [s for s in pos if s not in done and deps[s] <= done]
        if not ready:
            raise ValueError("cycle")
        nxt = min(ready, key=pos.get)
        done.add(nxt)
        out.append(nxt)
    return out


def handlers_of(stage):
    """[(exit code, handler id or None, then)] of a machine stage's steps."""
    rows = []
    for step in stage.get("steps", []) or []:
        for code, act in (step.get("on_exit") or {}).items():
            rows.append((int(code), act.get("run"), act.get("then")))
    return rows


def _cond_text(c):
    if "cmd" in c:
        words = [w.rsplit("/", 1)[-1] for w in c["cmd"]
                 if not (w.startswith("{python") or w in ("{runlog}", "python3", "{batch}", "--batch"))]
        return f"{' '.join(words)} exits {'/'.join(map(str, c['exit']))}"
    (k, v), = c.items()
    return f"{k} {v}"


def _when_text(when):
    if not when:
        return ""
    conds = when if isinstance(when, list) else [when]
    return " [if " + " and ".join(_cond_text(c) for c in conds) + "]"


def show_lines(plan):
    by_id = {s["id"]: s for s in plan["stages"]}
    lines = []
    for n, sid in enumerate(order(plan), 1):
        st = by_id[sid]
        mark = f" <{st['marker']}>" if st.get("marker") else ""
        tail = " (always)" if st.get("always") else ""
        if st.get("timeout_min"):
            tail += f" [ceiling {st['timeout_min']} min]"
        lines.append(f"{n:2d}. {sid:<30} {st['kind']:<8} {st['owner']}{mark}"
                     f"{_when_text(st.get('when'))}{tail}")
        for code, h, then in handlers_of(st):
            what = h or "-"
            lines.append(f"      exit {code} -> {what}, then {then}")
        for step in st.get("steps") or []:     # CF-0793
            for code, act in (step.get("on_exit") or {}).items():
                if isinstance(act, dict) and act.get("rerun_env"):
                    lines.append(f"      exit {code}: the rerun gets "
                                 + " ".join(f"{k}={v}" for k, v in act["rerun_env"].items()))
            if isinstance(step.get("exhausted"), dict):
                lines.append(f"      reruns spent -> once more with "
                             f"{' '.join(step['exhausted'].get('argv_add') or [])}")
    return lines


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_plan.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "show"):
        p = sub.add_parser(name)
        p.add_argument("channel")
        p.add_argument("--root", default=None, help="factory root (default: this checkout)")
        p.add_argument("--skip-missing-checkouts", action="store_true",
                       help="an agent not checked out here is not an error")
        if name == "show":
            p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    root = Path(ns.root).resolve() if ns.root else ROOT
    try:
        plan = load(ns.channel, root)
    except PlanError as e:
        print(f"run_plan: {e}", file=sys.stderr)
        return 2
    errs = validate(plan, root, skip_missing_checkouts=ns.skip_missing_checkouts)
    if errs:
        print(f"run_plan {ns.channel}: {len(errs)} error(s)")
        for e in errs:
            print(f"  - {e}")
        return 1
    refusal = start_refusal(ns.channel, root)
    if refusal:
        print(f"run_plan {ns.channel}: НЕ СТАРТУЕТ - {refusal} (CF-0659)", file=sys.stderr)
    if ns.cmd == "validate":
        n = len(plan["stages"])
        print(f"run_plan {ns.channel}: valid - {n} stage(s), "
              f"{len(order(plan))} in order, {n - len(order(plan))} handler(s)")
        return 0
    if ns.json:
        print(json.dumps({"channel": ns.channel, "order": order(plan),
                          "handlers": {s["id"]: [{"exit": c, "run": h, "then": t}
                                                 for c, h, t in handlers_of(s)]
                                       for s in plan["stages"] if handlers_of(s)}},
                         indent=2))
        return 0
    print(f"run_plan {ns.channel}: run order")
    for line in show_lines(plan):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
