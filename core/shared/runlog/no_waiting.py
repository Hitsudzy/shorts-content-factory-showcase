#!/usr/bin/env python3
"""CF-0317: in an autonomous run no stage waits for a human - and that is a
fact a machine checks, not a sentence in a skill.

The defect, from the grill of 2026-09-22 (Q19). `example-film/2026-09-19T0116Z`
stood **6h19m36s "waiting for a human"** of a 39h42m18s wall: 5h40m11s after
`trend-hunter` at the very start of the run, and 39m25s after `video-editor`
before the batch was closed. Nobody was at the machine. The factory simply
stood.

The user's decision is general, not a patch on those two places: **in an
autonomous run no stage may block on a decision that needs a person.**
Everything that would have asked becomes a *recorded outcome* - the topic is
dropped with a code, the video is marked, the batch closes with a reason - and
the run goes on. The person reads it afterwards. The single real exception is
publishing to a channel, and that is outside 1.x (`CF-0318`, the Publisher of
2.0).

**What this module is, and what it is not.** It is not a second measurer. The
measurement is `summary.waits()` (`CF-0252`) and it stays exactly as it is: a
silence of `WAIT_MIN_S` or more between a `stage-done` and the next
`stage-start`, with no script and no binary inside it. This module adds the
three things that measurement never had:

* `POINTS` - the *register*: every place a stage can block on a person today,
  what the person would decide there, and the automatic outcome that replaces
  the question, with a code (task item 1);
* `classify()` / `audit()` - the reading: a measured wait is matched to its
  register entry, so the record says *which* point fired and what should have
  happened instead, in the codes the funnel and the runs table already speak
  (task item 2);
* `dod()` - the check: from `RULE_EPOCH` on, a run whose summary carries
  `WAITS` or `GAPS` fails DoD 1 of the sprint, and the check goes red on the
  first such run rather than on a person's reading of a table (task item 3).

**Why the marker stays.** Deleting `WAITS` would make the factory look cured.
The marker is the only thing that can tell us the rule is being kept, so it
stays as a measurer - and its appearance in an autonomous run started on or
after `RULE_EPOCH` is an *incident*, not a normal end. That is the one
difference from the stop-cock of `CF-0322`, whose `no_material` close is a
normal end: a stop-cock stop means the batch had nothing left to do, while a
wait means it had something to do and did not do it.

**Why a register of prose points at all.** Four of the five stage procedures
live in `agents/*/.claude/skills/*/SKILL.md`, in separate repositories this
root cannot write to. `CF-0318` proved that a rule which lives only in prose is
executed by whoever happens to be reading it. So the root holds the register -
the machine-readable list of what must change and where - and the change in
each repository is dispatched from it. `repo` on every entry names the
repository that owns the fix; `ROOT` means this one.

**The two kinds of point**, and both are in the register:

    prose     a step in a SKILL.md whose only exit is a human answer ("stop and
              tell the user", "stop and say so"). Found by reading all five
              procedures, 2026-09-23. Eight of them, all in trend-hunter and
              content-researcher. compliance-checker, footage-indexer and
              video-editor have none, and neither do the two stages that are
              nobody's turn: `pool-maintenance`, and `frame-judge`, whose skill
              already says that a stage which stops early still ends with
              `stage-done` and a note. video-editor's `NEEDS-YOU` (CF-0098) is
              in fact the pattern the other two repositories are missing - mark
              the video, take the next one, never pause the run.
    orchestr. the orchestrator's own pause between two stages - not written in
              any skill, and the only kind that has actually cost this factory
              wall time. Both waits of `2026-09-19T0116Z` are of this kind,
              and so is a question the orchestrator asks the user mid-run
              (CF-0494, `2026-10-02T1748Z`): that point belongs to no stage
              (`ANY_STAGE`) and is told by a `runlog question` event inside
              the wait, not by the stage the wait began after.

`blocks()` is False for every entry by construction: an entry without an
automatic outcome cannot be in the register (checked at import). The register
is the answer to "what happens instead", so an unclassified wait - one no entry
matches - is itself the finding, and `audit()` says so with
`UNCLASSIFIED_CODE`.

CLI: `runlog no-waiting [--batch DIR] [--json] [--list] [--dod] [--since DAY]`;
exit 0 when the run is clean or exempt, 3 on an incident, 2 on a bad call.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# CF-0231 / tests/test_module_path_loading.py: our own directory first, then
# the neighbours by name.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402
import summary  # noqa: E402

__all__ = ["RULE_EPOCH", "EVENT_KEY", "ROOT_REPO", "POINTS", "CODES",
           "UNCLASSIFIED_CODE", "ANY_STAGE", "QUESTION_POINT", "CLEAN", "EXEMPT", "INCIDENT", "VERDICTS",
           "DOD_MET", "DOD_FAILED", "DOD_NO_RUN", "DOD_UNMEASURED", "DOD_STATES",
           "point", "points", "codes", "blocks", "classify", "pending",
           "RULINGS_JSONL", "RULING_FIELDS", "check_ruling", "rulings",
           "reset_stops_of", "reset_stop_text",
           "LOGIN_HALT_CODE", "login_stops_of", "login_stop_text",
           "audit", "headline", "render", "dod", "dod_line", "main"]

# The day the rule took effect: this task. A run started before it is evidence,
# not a violation - `2026-09-19T0116Z` is the reason the rule exists and may not
# be judged by it. A run started on or after it must show no wait.
RULE_EPOCH = "2026-09-23"

# The block this module attaches to a `stage-start` / `batch-done` event when
# the run has just stood still. Same shape of contract as `stopcock.EVENT_KEY`.
EVENT_KEY = "wait_incident"

ROOT_REPO = "—"                     # the root of the project, this checkout

CLEAN = "clean"                     # no wait, no gap: what every run must look like
EXEMPT = "exempt"                   # started before RULE_EPOCH - evidence, not a breach
INCIDENT = "incident"               # a run on the rule's own time stood still
VERDICTS = (CLEAN, EXEMPT, INCIDENT)

DOD_MET = "met"                     # at least one run on the rule's time, none waited
DOD_FAILED = "failed"               # a run on the rule's time waited or had a gap
DOD_NO_RUN = "no_run_yet"           # nothing has run since RULE_EPOCH: nothing to judge
DOD_UNMEASURED = "unmeasured"       # a row from before this module: it carries no `waits_s`
DOD_STATES = (DOD_MET, DOD_FAILED, DOD_NO_RUN, DOD_UNMEASURED)

# CF-0494 item 3, DECIDED by the user 2026-10-04 (night), variant A: a
# verification rerun - not a run for the feed - is not judged by DoD-1. A row
# whose batch was opened with `runlog batch-start --rerun <mode>` (runs row
# `rerun`) is listed under `reruns` instead of `offenders`, and the DoD line
# names it, so the exemption is never silent. The flag is never inferred from
# a note and never written into a closed batch after the fact, so a run opened
# without it - `2026-10-02T1748Z` among them - is still judged; that one is
# covered only by a named ruling (variant D, `RULINGS_JSONL` below).
EXEMPT_VERIFICATION_RERUNS = True

# CF-0494 variant D: the user's named rulings on single runs. One JSON object
# per line, next to `pipeline/runs.jsonl` and, like it, in git (`.gitignore`
# un-ignores both): the runs table is what DoD-1 reads, so the rulings that
# set some of its rows aside live beside it and survive the batch directory's
# move off this disk (CF-0056). A ruling covers exactly the batch it names and
# nothing else; the batch's own artifacts are never rewritten. Every field in
# `RULING_FIELDS` is required - a ruling without its reason, its date or who
# made it is refused, listed under `refused` and named in the DoD line.
RULINGS_JSONL = "pipeline/waits-ruled.jsonl"
RULING_FIELDS = ("batch", "ruling", "date", "by")
RULING_BY = ("user",)               # only the user rules a wait away
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The code a wait gets when no register entry matches it. Not a hole to be
# filled quietly: an unclassified wait means the factory stood still in a place
# nobody has written an outcome for, which is the whole defect, so it is louder
# than any named code and `audit()` carries it into the record verbatim.
UNCLASSIFIED_CODE = "unclassified_wait"

# CF-0899: the code of a stop on `claude` not logged in. Not a register entry:
# the register holds the points with an automatic outcome, and logging in has
# none - only the user can do it. The executor halts there (run-state.json
# `login_halts`), the person is told once a day, the schedule's tick resumes the
# batch by itself once the CLI is logged in again; the wait or gap that holds
# such a halt is set aside under `login_stops` - on the stage that halted, not
# on the stage before it, where `summary.waits()` measures the silence - and
# named, never silently (the same shape as CF-0739's `reset_stops`).
LOGIN_HALT_CODE = "not_logged_in_halt"

# CF-0494: a point that is not tied to a stage - matched by an event inside the
# wait, never by `after_stage` (no stage is called this).
ANY_STAGE = "*"
QUESTION_POINT = "orchestrator_question_mid_run"


# --------------------------------------------------------------------------
# the register (task item 1)
# --------------------------------------------------------------------------
#
# `where`    the heading or step of the procedure, so the worker who fixes it
#            can find it without re-reading the file;
# `quote`    the blocking instruction, short and verbatim;
# `decides`  what the person would decide, i.e. what the automatic outcome has
#            to answer without them;
# `outcome`  what the stage does instead - this is the change;
# `code`     the code that outcome records. The vocabulary the funnel and the
#            runs row read; never a second spelling of an existing code;
# `seen`     the batch where this point actually cost wall time, or None. Two
#            entries carry one, and they are the two waits of the task.

POINTS = (
    # ---- trend-hunter -----------------------------------------------------
    {"id": "hunter_quota_resume",
     "stage": "trend-hunter", "repo": ROOT_REPO, "kind": "orchestrator",
     "where": "between `stage-done trend-hunter` and the next `stage-start`",
     "quote": "resumed after the YouTube search quota reset",
     "decides": "whether to wait out the daily YouTube Search quota (100/day) "
                "so the topics left without footage evidence can get it",
     "outcome": "the run does not wait for the quota. The topics that got their "
                "footage evidence go on; every topic still without it is dropped "
                "there with the code, counted in the funnel as a loss, and the "
                "batch continues to the next stage inside the same minute. The "
                "quota resets on its own clock, which no batch may be paid for.",
     "code": "footage_evidence_quota",
     "seen": "example-film/2026-09-19T0116Z"},

    {"id": "hunter_missing_api_key",
     "stage": "trend-hunter", "repo": "agents/trend-hunter", "kind": "prose",
     "where": "Inputs",
     "quote": "If missing, stop and tell the user - do not fabricate data.",
     "decides": "where `YOUTUBE_API_KEY` comes from",
     "outcome": "no key is a fact about the machine, not about this batch, and "
                "it will not change inside the run. The stage writes no "
                "`01-trend-hunter.json`, closes with `stage-done --note` naming "
                "the missing key, and the batch ends there with the code - the "
                "next scheduled run tries again. It never asks and never waits.",
     "code": "missing_api_key_skip",
     "seen": None},

    # ---- content-researcher ----------------------------------------------
    {"id": "researcher_empty_shortlist",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Step 1",
     "quote": "If no topic is left to write, say so and stop",
     "decides": "nothing - an empty shortlist is a fact, and this point is "
                "already all but automatic. It is in the register so that "
                "`say so and stop` is spelled as a close with a code rather "
                "than as a sentence an operator may read as a question.",
     "outcome": "`stage-done --note \"0 eligible topics, no scripts written\"`, "
                "the loss already stands upstream in the funnel, and the "
                "stop-cock of CF-0322 closes the batch.",
     "code": "empty_shortlist_close",
     "seen": None},

    {"id": "researcher_missing_upstream",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Notes - the missing `02-compliance-checker.json` / `01b-footage-index.json`",
     "quote": "If the footage index is missing, stop and say so",
     "decides": "why the upstream artifact is absent - a stage skipped, a stage "
                "that fell over, or a batch assembled out of order",
     "outcome": "the stage still may not guess the missing verdicts or the "
                "missing shots - that part of the rule is right and stays. What "
                "changes is the exit: `stage-done --note` naming the absent "
                "file, the code on the batch, and the orchestrator closes the "
                "batch on it instead of the stage standing open for a person.",
     "code": "missing_upstream_file_skip",
     "seen": None},

    {"id": "researcher_missing_repo_asset",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Notes - `check_reactions.py` / `check_sounds.py` / `check_proofs.py`",
     "quote": "cannot find ~/shorts-content-factory/inserts/meme.json, stop and say so",
     "decides": "the integrity of the checkout - a file moved or deleted",
     "outcome": "a missing insert library is a defect of the machine that will "
                "be there for every batch until someone fixes it, so it is "
                "raised once as a standing note and not asked once per run: the "
                "stage closes with the code, the batch ends, and the run does "
                "not stand.",
     "code": "missing_repo_asset_skip",
     "seen": None},

    {"id": "researcher_stale_cache",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Notes - `check_anchor_coverage.py` exit 3, the stale-measurement cause",
     "quote": "If check_anchor_coverage.py exits 3, stop and say so.",
     "decides": "which of the four causes it is, and which repair to run",
     "outcome": "the stale-cache cause is the one that describes its own repair "
                "- the message already names the exact `remeasure_*` command - "
                "so the stage runs it and retries once, under the "
                "`pool-maintenance` markers, and the run never asks. Bounded to "
                "one retry: a second failure is not stale data.",
     "code": "stale_cache_auto_remeasure_retry",
     "seen": None},

    {"id": "researcher_env_broken",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Notes - `check_anchor_coverage.py` exit 3, the venv / drifted-constant causes",
     "quote": "If check_anchor_coverage.py exits 3, stop and say so.",
     "decides": "how to repair a broken venv, or which of two drifted constants "
                "is the right one",
     "outcome": "neither is repairable inside a batch and neither may be "
                "guessed. The stage closes with the code naming the cause, the "
                "batch ends, and the standing note is raised once - the same "
                "shape as the missing insert library, and for the same reason.",
     "code": "env_broken_skip",
     "seen": None},

    {"id": "researcher_missing_channel_config",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Notes - `check_narration_budget.py` without the channel config",
     "quote": "cannot find the channel config or its narration_budget block, stop",
     "decides": "what the channel's narration budget should be",
     "outcome": "a channel without a budget block is a channel that is not "
                "configured, and the number may not be invented here. The stage "
                "closes with the code, the batch ends, and the channel carries "
                "the flag until the block is added.",
     "code": "missing_channel_config_skip",
     "seen": None},

    {"id": "researcher_estimator_unavailable",
     "stage": "content-researcher", "repo": "agents/content-researcher", "kind": "prose",
     "where": "Step 6 - `check_narration_budget.py`, `narration_estimator_unavailable`",
     "quote": "Stop and report it. Do not divide the word count by words_per_second",
     "decides": "how to repair the TTS estimator on this machine",
     "outcome": "the refusal to fall back on a word-count guess is the point of "
                "CF-0279 and it stays. The change is only that the report is an "
                "exit and not a question: the stage closes with the code, the "
                "batch ends, and the standing note is raised once for the "
                "machine rather than once per batch.",
     "code": "estimator_unavailable_skip",
     "seen": None},

    # ---- video-editor -----------------------------------------------------
    {"id": "editor_close_out",
     "stage": "video-editor", "repo": ROOT_REPO, "kind": "orchestrator",
     "where": "between `stage-done video-editor` and `batch-done`",
     "quote": "0 videos rendered, 1 refused before the render, 0 needs-you",
     "decides": "whether anything can still be done with a batch whose editor "
                "rendered nothing - i.e. whether to re-cut, re-render or close",
     "outcome": "nothing follows the editor but the frame judge, and the frame "
                "judge of a batch with no video has nothing to read. The "
                "orchestrator closes the batch on the editor's own recorded "
                "refusal, in the same minute, with the code. A re-cut is a new "
                "batch and a decision for afterwards, never a pause inside this "
                "one.",
     "code": "nothing_left_close",
     "seen": "example-film/2026-09-19T0116Z"},

    # ---- any stage: the orchestrator asks the user (CF-0494) ----------------
    {"id": QUESTION_POINT,
     "stage": ANY_STAGE, "repo": ROOT_REPO, "kind": "orchestrator",
     "where": "between any `stage-done` and the next `stage-start`, a wait that "
              "holds a `runlog question` event",
     "quote": "runlog question --note \"<what was asked>\"",
     "decides": "whatever the orchestrator would not decide alone in the middle of "
                "the run - on `2026-10-02T1748Z` whether a verification rerun agreed "
                "\"without search\" may search for the thin-pool supplement (it "
                "stood 1h43m20s, recorded then as `unclassified_wait`)",
     "outcome": "the run does not wait for the answer. What a batch may do is "
                "agreed before `batch-start` and said there by a flag (`--rerun "
                "no-search`, CF-0494). A question that still comes up mid-run is "
                "written with `runlog question` for the user to read afterwards, "
                "the step takes its own automatic outcome (the supplement step "
                "closes `skipped`, a stage closes with its code), and the run goes "
                "on inside the same minute.",
     "code": "question_deferred",
     "seen": None},
)

# Every code the register can record, sorted. The runs row and the funnel read
# these spellings; a new outcome adds its code here by adding its entry, and
# nowhere else.
CODES = tuple(sorted({p["code"] for p in POINTS}))

_REQUIRED = ("id", "stage", "repo", "kind", "where", "quote", "decides", "outcome", "code")
_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def _check_register():
    """An entry without an automatic outcome cannot be in the register - that
    is the invariant the whole module rests on, so it is checked where it can
    never be skipped rather than only in a test."""
    seen = set()
    for p in POINTS:
        missing = [k for k in _REQUIRED if not p.get(k)]
        if missing:
            raise ValueError(f"no_waiting: register entry {p.get('id')!r} has no {missing}")
        if not _SNAKE.match(p["id"]) or not _SNAKE.match(p["code"]):
            raise ValueError(f"no_waiting: {p['id']!r}/{p['code']!r} is not snake_case")
        if p["id"] in seen:
            raise ValueError(f"no_waiting: duplicate register id {p['id']!r}")
        seen.add(p["id"])


_check_register()


def points(stage=None, repo=None, kind=None):
    """The register, filtered. Order is the order of POINTS - by stage, in the
    order of the pipeline."""
    out = list(POINTS)
    if stage:
        out = [p for p in out if p["stage"] == stage]
    if repo:
        out = [p for p in out if p["repo"] == repo]
    if kind:
        out = [p for p in out if p["kind"] == kind]
    return out


def point(pid):
    """One register entry by id, or None."""
    return next((p for p in POINTS if p["id"] == pid), None)


def codes(stage=None):
    return tuple(sorted({p["code"] for p in points(stage)}))


def blocks(p):
    """Does this point block the run? False, always - and it is a function
    rather than a constant so that the answer is asked of the register instead
    of assumed. A point that blocked would have no `outcome`, and `POINTS`
    cannot hold one (see `_check_register`)."""
    return not (isinstance(p, dict) and p.get("outcome") and p.get("code"))


# --------------------------------------------------------------------------
# reading a measured wait (task item 2)
# --------------------------------------------------------------------------

# What tells the two orchestrator points apart from each other and from a wait
# nobody has written an outcome for: the words of the `stage-done` note the
# wait began at. Deliberately few and deliberately literal - a matcher that
# guesses would hand an unwritten wait a code and hide it.
_HINTS = {
    "hunter_quota_resume": ("quota", "квот"),
    "hunter_missing_api_key": ("youtube_api_key", "api key", "api-key"),
    "researcher_empty_shortlist": ("0 eligible", "no eligible", "no topic", "empty shortlist"),
    "researcher_missing_upstream": ("compliance-checker.json", "footage-index.json",
                                    "footage index", "01b", "02-"),
    "researcher_missing_repo_asset": ("meme.json", "sound.json", "proof.json", "inserts/"),
    "researcher_stale_cache": ("stale", "remeasure"),
    "researcher_env_broken": ("venv", "drifted", "import", "anchor_coverage"),
    "researcher_missing_channel_config": ("narration_budget", "channel config"),
    "researcher_estimator_unavailable": ("estimator", "kokoro"),
    "editor_close_out": ("rendered", "refused", "needs-you", "attempts"),
}


def classify(after_stage, note=None, next_stage=None, asked=None):
    """The register entry a measured wait belongs to, or None.

    `after_stage` is the stage whose `stage-done` the silence began at (the
    field `summary.waits()` already carries) and `note` is that marker's note.
    A stage with exactly one point in the register needs no note; where a stage
    has several, the note decides, and a note that decides nothing leaves the
    wait unclassified on purpose.

    `asked` - the questions (`runlog question`, CF-0494) recorded inside the
    wait: any one makes it the question point, whatever stage it followed."""
    if asked:
        return point(QUESTION_POINT)
    cand = [p for p in POINTS if p["stage"] == after_stage]
    if not cand:
        return None
    if len(cand) == 1:
        return cand[0]
    text = (note or "").lower()
    for p in cand:
        for h in _HINTS.get(p["id"], ()):
            if h in text:
                return p
    return None


def _notes(d):
    """{(stage, ts_float): note} of every `stage-done` marker of the run."""
    out = {}
    for e in d["markers"]:
        if e.get("status") != runlog.M_STAGE_DONE:
            continue
        t = summary._ts(e.get("ts"))
        if t is not None:
            out[(e.get("stage"), round(t, 3))] = e.get("note")
    return out


def _note_for(d, wait):
    """The note of the `stage-done` this wait began at. The wait's own start may
    be later than the marker - a script can still have been running - so the
    latest marker of that stage at or before the wait's start is the one."""
    a = summary._ts(wait.get("start"))
    best, best_t = None, None
    for (stage, t), note in _notes(d).items():
        if stage != wait.get("after_stage") or a is None or t > a + 1.0:
            continue
        if best_t is None or t > best_t:
            best, best_t = note, t
    return best


def _asked(d, wait):
    """CF-0494: the texts of the `question` events inside the wait (a second of
    slack either side - the event can land just before the silence is measured
    from or just as the next marker closes it)."""
    a, b = wait.get("_a"), wait.get("_b")
    if a is None or b is None:
        a, b = summary._ts(wait.get("start")), summary._ts(wait.get("end"))
    if a is None or b is None:
        return []
    out = []
    for e in d["events"]:
        if e.get("kind") != runlog.KIND_QUESTION:
            continue
        t = summary._ts(e.get("ts"))
        if t is not None and a - 1.0 <= t <= b + 1.0:
            out.append(e.get("note") or "")
    return out


def _read(wait, p, note, asked=None):
    """One line of the record: the measured wait, the point it belongs to, the
    code its outcome should have written."""
    return {"after_stage": wait.get("after_stage"), "next_stage": wait.get("next_stage"),
            "since": wait.get("since"), "seconds": wait.get("seconds"),
            "minutes": wait.get("minutes"),
            "point": p["id"] if p else None,
            "repo": p["repo"] if p else ROOT_REPO,
            "kind": p["kind"] if p else None,
            "code": p["code"] if p else UNCLASSIFIED_CODE,
            "outcome": p["outcome"] if p else
                       "no register entry covers this wait - CF-0317 item 1 is "
                       "incomplete, and that is the finding",
            "note": note,
            "asked": list(asked or [])}


def audit(batch_dir=None, events=None, since=RULE_EPOCH, data=None):
    """The reading of one run against the rule.

        {"batch", "started", "since", "verdict" (CLEAN|EXEMPT|INCIDENT),
         "waits_count", "waits_s", "gaps_count", "gaps_s", "wall_s",
         "codes": [...], "unclassified": n, "reads": [ ... ], "task": str|None,
         "reset_stops": [{at, task, by, why, from, gaps_s, waits_s, start, end}]}

    CF-0739: a wait or gap that holds a recorded reset of the batch's stages
    (runlog.manual_resets) is not counted in `waits_*` / `gaps_*` and does not
    make an INCIDENT: it is listed under `reset_stops`, named by the reset.

    EXEMPT is the run that started before the rule did: `2026-09-19T0116Z` is
    the evidence this task was written from and may not be judged by it. Its
    waits are still read and still named - the exemption is from the verdict,
    not from the record.

    INCIDENT is a run on the rule's own time that carried a wait or a gap. Both,
    because DoD 1 asks for a summary with neither: a gap is the machine stopped
    and a wait is the factory stopped, and a run that shows either did not run
    unattended to the end."""
    d = data if data is not None else summary.load(batch_dir, events)
    w = summary.waits(d)
    g = summary.gaps_summary(d)
    t0, t1 = d["wall"]
    started = summary._iso(t0) if t0 is not None else None
    # CF-0739: the stop that holds a recorded reset of the batch's stages - the
    # batch stopped, the stages were reset, the batch resumed - is a ruled stop,
    # set aside under `reset_stops` and named by the reset; every other wait and
    # gap of the run is judged as before.
    gm = runlog.sibling("gaps")
    resets = d.get("resets") or []
    stops = {}

    def _stop(r):
        b = runlog.reset_brief(r)
        return stops.setdefault(b["at"], dict(b, gaps_s=0.0, waits_s=0.0, start=None, end=None))

    judged_waits = []
    for q in w["waits"]:
        r = gm.reset_in(q.get("_a"), q.get("_b"), resets)
        if r is None:
            judged_waits.append(q)
            continue
        st = _stop(r)
        st["waits_s"] = round(st["waits_s"] + float(q.get("seconds") or 0.0), 1)
        st["start"], st["end"] = st["start"] or q.get("start"), st["end"] or q.get("end")
    judged_gaps = []
    for gg in g.get("gaps") or []:
        r = gm.reset_in(summary._ts(gg.get("start")), summary._ts(gg.get("end")), resets)
        if r is None:
            judged_gaps.append(gg)
            continue
        st = _stop(r)
        st["gaps_s"] = round(st["gaps_s"] + float(gg.get("seconds") or 0.0), 1)
        st["start"], st["end"] = gg.get("start"), gg.get("end")
    # CF-0899: the silence that overlaps a recorded halt on `claude` not logged
    # in - from the halt to the resume that went on from it - is the user's
    # stop, set aside under `login_stops` on the stage that halted.
    halts = d.get("login_halts") or []
    logins = {}

    def _login(q0, q1):
        for h in halts:
            h1 = h.get("t_resumed") if h.get("t_resumed") is not None else float("inf")
            if q0 is not None and q1 is not None and q0 <= h1 and q1 >= h["t"]:
                return logins.setdefault(h["at"], {
                    "at": h["at"], "stage": h.get("stage"), "reason": h.get("reason"),
                    "task": h.get("task"), "resumed": h.get("resumed"),
                    "code": LOGIN_HALT_CODE, "source": h.get("source"),
                    "gaps_s": 0.0, "waits_s": 0.0, "start": None, "end": None})
        return None

    if halts:
        kept = []
        for q in judged_waits:
            q0 = q.get("_a") if q.get("_a") is not None else summary._ts(q.get("start"))
            q1 = q.get("_b") if q.get("_b") is not None else summary._ts(q.get("end"))
            st = _login(q0, q1)
            if st is None:
                kept.append(q)
                continue
            st["waits_s"] = round(st["waits_s"] + float(q.get("seconds") or 0.0), 1)
            st["start"], st["end"] = st["start"] or q.get("start"), q.get("end")
        judged_waits = kept
        kept = []
        for gg in judged_gaps:
            st = _login(summary._ts(gg.get("start")), summary._ts(gg.get("end")))
            if st is None:
                kept.append(gg)
                continue
            st["gaps_s"] = round(st["gaps_s"] + float(gg.get("seconds") or 0.0), 1)
            st["start"] = min(x for x in (st["start"], gg.get("start")) if x)
            st["end"] = max(x for x in (st["end"], gg.get("end")) if x)
        judged_gaps = kept
    reads = [_read(q, classify(q.get("after_stage"), _note_for(d, q), q.get("next_stage"),
                               _asked(d, q)),
                   _note_for(d, q), _asked(d, q)) for q in judged_waits]
    exempt = bool(started) and started[:10] < (since or RULE_EPOCH)
    if exempt:
        verdict = EXEMPT
    elif judged_waits or judged_gaps:
        verdict = INCIDENT
    else:
        verdict = CLEAN
    return {"batch": (d["header"] or {}).get("batch") or summary._batch_name(batch_dir),
            "started": started, "since": since or RULE_EPOCH, "verdict": verdict,
            "waits_count": len(judged_waits),
            "waits_s": round(sum(float(q.get("seconds") or 0.0) for q in judged_waits), 1),
            "gaps_count": len(judged_gaps),
            "gaps_s": round(sum(float(x.get("seconds") or 0.0) for x in judged_gaps), 1),
            "reset_stops": sorted(stops.values(), key=lambda x: str(x["at"])),
            "login_stops": sorted(logins.values(), key=lambda x: str(x["at"])),   # CF-0899
            "wall_s": round((t1 - t0), 1) if t0 is not None and t1 is not None else None,
            "codes": sorted({r["code"] for r in reads}),
            "unclassified": sum(1 for r in reads if r["point"] is None),
            "reads": reads,
            "task": ("file a task: an autonomous run stood still" if verdict == INCIDENT
                     else None)}


def pending(events, which, stage=None, ts=None):
    """The wait a marker about to be written would close, or None.

    Called from `runlog.marker()` before the event lands: the events so far plus
    a synthetic marker at `ts` are handed to the same `summary.waits()` every
    other reader uses, and the wait that ends at `ts` - if there is one - comes
    back as a record. One measurer, read at a second moment; never a second
    definition of what a wait is."""
    if which not in (runlog.M_STAGE_START, runlog.M_BATCH_DONE):
        return None
    ts = ts or runlog.now_z()
    ev = list(events) + [{"ts": ts, "kind": runlog.KIND_MARKER,
                          "status": which, "stage": stage}]
    d = summary.load(events=ev)
    w = summary.waits(d)
    if not w["waits"]:
        return None
    last = w["waits"][-1]
    end = summary._ts(last.get("end"))
    now = summary._ts(ts)
    if end is None or now is None or now - end > 2.0:
        return None
    note = _note_for(d, last)
    asked = _asked(d, last)
    r = _read(last, classify(last.get("after_stage"), note, stage, asked), note, asked)
    r["closed_by"] = which
    return r


# --------------------------------------------------------------------------
# the lines
# --------------------------------------------------------------------------

def headline(a):
    """The NO-WAITING line of the summary, under the WAITS line - and empty on a
    clean run, the way the stop-cock line is empty on a healthy one."""
    if not a:
        return ""
    if not a["waits_count"] or a["verdict"] == CLEAN:
        if a.get("login_stops") and a["verdict"] != EXEMPT:      # CF-0899: named, never silent
            return ("NO-WAITING: not judged - "
                    + "; ".join(login_stop_text(x) for x in a["login_stops"])
                    + " (CF-0899: only the user logs in)")
        return ""
    bits = "; ".join(f"{r['after_stage'] or '?'} -> {r['code']}" for r in a["reads"])
    if a["verdict"] == EXEMPT:
        return (f"NO-WAITING: exempt (this run started before {a['since']}, "
                f"the rule of CF-0317) - {a['waits_count']} wait(s) read: {bits}")
    return (f"NO-WAITING: INCIDENT - an autonomous run stood still "
            f"{summary._hms(a['waits_s'])} in {a['waits_count']} place(s): {bits}. "
            f"CF-0317: every one of these has an automatic outcome; the run took none.")


def reset_stop_text(x):
    """One ruled stop (CF-0739) in words."""
    secs = (x.get("gaps_s") or 0.0) or (x.get("waits_s") or 0.0)
    return (f"stopped {summary._hms(secs)} for a recorded reset {x.get('at')} "
            f"({x.get('task') or 'no task'}, {x.get('by') or '?'}: "
            f"{x.get('why') or 'no reason recorded'}; from {x.get('from')})")


def login_stop_text(x):
    """One stop on `claude` not logged in (CF-0899) in words, on its stage."""
    secs = max(x.get("gaps_s") or 0.0, x.get("waits_s") or 0.0)
    return (f"{x.get('stage') or '?'} stood {summary._hms(secs)} halted on `claude` not "
            f"logged in ({x.get('code') or LOGIN_HALT_CODE}) {x.get('at')} -> "
            + (f"resumed {x['resumed']}" if x.get("resumed") else "not resumed yet"))


def render(a):
    """The block of the summary. [] unless there is something to say."""
    if not a or not (a["waits_count"] or a.get("reset_stops") or a.get("login_stops")):
        return []
    if not a["waits_count"]:
        tasks = ", ".join(t for t, k in (("CF-0739", "reset_stops"), ("CF-0899", "login_stops"))
                          if a.get(k))
        return (["", f"## Ruled stops ({tasks})", ""]
                + [f"- {reset_stop_text(x)}" for x in a.get("reset_stops") or []]
                + [f"- {login_stop_text(x)}" for x in a.get("login_stops") or []] + [""])
    L = ["", "## Where the factory stood still (CF-0317)", "",
         f"verdict: {a['verdict']} · rule in force from {a['since']}", ""]
    for x in a.get("reset_stops") or []:
        L.append(f"- ruled stop, not judged: {reset_stop_text(x)}")
    for x in a.get("login_stops") or []:
        L.append(f"- the user's stop, not judged: {login_stop_text(x)}")
    for r in a["reads"]:
        L.append(f"- **{r['after_stage'] or '?'}** since {r['since']} "
                 f"{summary._hms(r['seconds'])} -> `{r['code']}` "
                 f"({r['repo']}{', unclassified' if r['point'] is None else ''})")
        L.append(f"  - instead: {r['outcome']}")
    L.append("")
    return L


# --------------------------------------------------------------------------
# DoD 1 of the sprint (task item 3)
# --------------------------------------------------------------------------

def check_ruling(rec):
    """CF-0494 D: the reason a ruling is refused, or None when it stands."""
    if not isinstance(rec, dict):
        return "not a JSON object"
    missing = [k for k in RULING_FIELDS if not str(rec.get(k) or "").strip()]
    if missing:
        return "missing " + ", ".join(missing)
    if not _DATE.match(str(rec["date"])):
        return f"date {rec['date']!r} is not YYYY-MM-DD"
    if rec["by"] not in RULING_BY:
        return f"by {rec['by']!r}: only {', '.join(RULING_BY)} rules a wait away"
    if "/" not in str(rec["batch"]):
        return f"batch {rec['batch']!r} is not <channel>/<batch id>"
    return None


def rulings(root=None):
    """CF-0494 D: `(standing, refused)` read from `RULINGS_JSONL` under the root.
    `standing` maps a batch to its ruling; `refused` lists every line that was
    not taken, with why. No file is no rulings."""
    p = runlog.sibling("runs_table")._root(root) / RULINGS_JSONL
    standing, refused = {}, []
    if not p.is_file():
        return standing, refused
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            rec, why = None, "unreadable JSON"
        else:
            why = check_ruling(rec)
        if why:
            refused.append({"line": n, "batch": (rec or {}).get("batch") if isinstance(rec, dict) else None,
                            "why": why})
        else:
            standing[rec["batch"]] = rec
    return standing, refused


def reset_stops_of(row, root=None):
    """CF-0739: the ruled stops of a runs row - `reset_stops` when the row
    carries it (written from CF-0739 on); else, for an older row, read from the
    batch directory while it is still on this disk, and only when its
    run-state.json records a reset (`manual_resets`): the run's own summary
    names the stops. [] otherwise - an older row of a batch with no recorded
    reset, or one whose directory has moved off, is judged on its numbers."""
    if isinstance(row.get("reset_stops"), list):
        return [x for x in row["reset_stops"] if isinstance(x, dict)]
    try:
        base = Path(root) if root else runlog.factory_root()
        bd = base / "pipeline" / str(row.get("batch") or "")
        if not row.get("batch") or not (bd / runlog.STATE_FILE).is_file():
            return []
        if not runlog.manual_resets(bd):
            return []
        return [{k: x.get(k) for k in ("at", "task", "by", "why", "from", "gaps_s", "waits_s")}
                for x in audit(bd).get("reset_stops") or []]
    except Exception as e:                                     # noqa: BLE001
        runlog._warn(f"no-waiting: reset stops of {row.get('batch')} not read ({e})")
        return []


LOGIN_STOP_FIELDS = ("at", "stage", "reason", "task", "resumed", "code", "gaps_s", "waits_s")


def login_stops_of(row, root=None):
    """CF-0899: the stops of a runs row on `claude` not logged in - `login_stops`
    when the row carries it (written from CF-0899 on); else, for an older row,
    read from the batch directory while it is still on this disk, and only when
    its run-state.json records a login halt (`runlog.login_halts`: the
    executor's `login_halts`, or the run it discarded on NOT_LOGGED_IN before
    that key existed). [] otherwise: an older row whose directory has moved off
    (scripts/monthly_archive.py, 31 days after the close) is judged on its
    numbers - what keeps such a row out of the red then is the user's named
    ruling (`RULINGS_JSONL`)."""
    if isinstance(row.get("login_stops"), list):
        return [x for x in row["login_stops"] if isinstance(x, dict)]
    try:
        base = Path(root) if root else runlog.factory_root()
        bd = base / "pipeline" / str(row.get("batch") or "")
        if not row.get("batch") or not (bd / runlog.STATE_FILE).is_file():
            return []
        if not runlog.login_halts(bd):
            return []
        return [{k: x.get(k) for k in LOGIN_STOP_FIELDS}
                for x in audit(bd).get("login_stops") or []]
    except Exception as e:                                     # noqa: BLE001
        runlog._warn(f"no-waiting: login stops of {row.get('batch')} not read ({e})")
        return []


def dod(root=None, since=RULE_EPOCH, exempt_reruns=None, ruled=None):
    """DoD 1: a run whose summary carries neither `WAITS` nor `GAPS`.

        {"state", "since", "considered", "clean", "offenders": [...], "line"}

    Read from `pipeline/runs.jsonl` and not from the batch directories, because
    a batch directory is moved off this disk 31 days after it closes
    (`scripts/monthly_archive.py`, CF-0056/CF-0358) while the row stays in git
    forever - the same reason `CF-0318` put its holds in `publish/`.

    Today the answer is `no_run_yet`: no run has been started since the rule,
    and a check that went red for that would be red about the calendar rather
    than about the factory. It goes red on the first run started on or after
    `since` that shows a wait or a gap, which is exactly what the task asked
    for - a statement about the next run, checked by a machine.

    `unmeasured` is the third honest answer: a row written by a runlog older
    than this module carries no `waits_s` at all, and "no field" is not "no
    wait".

    Set aside, never silently (CF-0494): a flagged verification rerun under
    `reruns` while `EXEMPT_VERIFICATION_RERUNS` is on, and a batch the user
    ruled on by name under `ruled` (`ruled=None` reads `RULINGS_JSONL`; a dict
    of batch -> ruling replaces it, `{}` turns rulings off). Rulings that were
    refused are listed under `refused`. A run whose only waits and gaps are
    the stop around a recorded reset of its stages (CF-0739, `reset_stops_of`)
    is set aside under `reset`, named by the reset; a run with more than that
    is judged on the rest."""
    rows = runlog.sibling("runs_table").read_rows(root)
    refused = []
    if ruled is None:
        ruled, refused = rulings(root)
    mine = [r for r in rows if (r.get("started") or "")[:10] >= since]
    mine.sort(key=lambda r: r.get("started") or "")
    if exempt_reruns is None:
        exempt_reruns = EXEMPT_VERIFICATION_RERUNS
    offenders, unmeasured, clean, reruns, set_aside, by_reset = [], [], [], [], [], []
    by_login = []                                     # CF-0899
    for r in mine:
        if r.get("batch") in ruled:                   # CF-0494 D, by name only
            k = ruled[r["batch"]]
            set_aside.append({"batch": r["batch"], "ruling": k["ruling"], "date": k["date"],
                              "by": k["by"], "waits_s": r.get("waits_s"), "gaps_s": r.get("gaps_s")})
            continue
        if exempt_reruns and r.get("rerun"):          # CF-0494 A, decided 2026-10-04
            reruns.append({"batch": r.get("batch"), "rerun": r.get("rerun"),
                           "waits_s": r.get("waits_s"), "gaps_s": r.get("gaps_s")})
            continue
        if r.get("waits_s") is None:
            unmeasured.append(r)
            continue
        # CF-0739: the stop that holds a recorded reset is a ruled stop, set
        # aside and named by the reset; the rest of the run is judged.
        stood = bool(r.get("waits_s") or r.get("gaps_s"))
        stops = reset_stops_of(r, root) if stood else []
        logins = login_stops_of(r, root) if stood else []        # CF-0899
        both = stops + logins
        waits_s = max(0.0, (r.get("waits_s") or 0.0) - sum(x.get("waits_s") or 0.0 for x in both))
        gaps_s = max(0.0, (r.get("gaps_s") or 0.0) - sum(x.get("gaps_s") or 0.0 for x in both))
        waits_s = waits_s if waits_s >= 1.0 else 0.0
        gaps_s = gaps_s if gaps_s >= 1.0 else 0.0
        bad = []
        if waits_s:
            bad.append(f"WAITS {summary._hms(waits_s)}")
        if gaps_s:
            bad.append(f"GAPS {summary._hms(gaps_s)}")
        if both and not bad:
            if stops:
                by_reset.append({"batch": r.get("batch"), "started": r.get("started"),
                                 "resets": stops, "waits_s": r.get("waits_s"),
                                 "gaps_s": r.get("gaps_s")})
            if logins:
                by_login.append({"batch": r.get("batch"), "started": r.get("started"),
                                 "logins": logins, "waits_s": r.get("waits_s"),
                                 "gaps_s": r.get("gaps_s")})
            continue
        if both:
            bad.append("besides " + "; ".join([reset_stop_text(x) for x in stops]
                                              + [login_stop_text(x) for x in logins]))
        (offenders if bad else clean).append(
            {"batch": r.get("batch"), "started": r.get("started"), "why": ", ".join(bad),
             "codes": ((r.get("waits") or {}).get("codes") or [])} if bad
            else {"batch": r.get("batch"), "started": r.get("started")})
    if offenders:
        state = DOD_FAILED
    elif clean:
        state = DOD_MET
    elif unmeasured:
        state = DOD_UNMEASURED
    else:
        state = DOD_NO_RUN
    out = {"state": state, "since": since, "considered": len(mine),
           "clean": [c["batch"] for c in clean],
           "unmeasured": [r.get("batch") for r in unmeasured],
           "offenders": offenders, "reruns": reruns,
           "ruled": set_aside, "reset": by_reset, "login": by_login, "refused": refused}
    out["line"] = dod_line(out)
    return out


def dod_line(x):
    line = _dod_line(x)
    if x.get("reruns"):                               # CF-0494 A
        line += (f"; {len(x['reruns'])} verification rerun(s) not judged (CF-0494): "
                 + ", ".join(r["batch"] or "?" for r in x["reruns"]))
    if x.get("ruled"):                                # CF-0494 D
        line += (f"; {len(x['ruled'])} run(s) set aside by a named ruling ({RULINGS_JSONL}): "
                 + ", ".join(f"{r['batch']} ({r['by']} {r['date']}: {r['ruling']})" for r in x["ruled"]))
    if x.get("reset"):                                # CF-0739
        line += (f"; {len(x['reset'])} run(s) set aside by a recorded batch reset (CF-0739): "
                 + ", ".join(f"{r['batch']} ("
                             + "; ".join(reset_stop_text(s) for s in r["resets"]) + ")"
                             for r in x["reset"]))
    if x.get("login"):                                # CF-0899
        line += (f"; {len(x['login'])} run(s) set aside by a recorded halt on `claude` not "
                 f"logged in (CF-0899, only the user logs in): "
                 + ", ".join(f"{r['batch']} ("
                             + "; ".join(login_stop_text(s) for s in r["logins"]) + ")"
                             for r in x["login"]))
    if x.get("refused"):
        line += (f"; {len(x['refused'])} ruling(s) REFUSED in {RULINGS_JSONL}: "
                 + ", ".join(f"line {r['line']} {r['batch'] or '?'} ({r['why']})" for r in x["refused"]))
    return line


def _dod_line(x):
    s = x["state"]
    if s == DOD_FAILED:
        bits = "; ".join(f"{o['batch']} ({o['why']})" for o in x["offenders"])
        return (f"DOD-1: FAILED - {len(x['offenders'])} run(s) since {x['since']} "
                f"stood still or stopped: {bits}")
    if s == DOD_MET:
        return (f"DOD-1: met - {len(x['clean'])} run(s) since {x['since']} with no "
                f"WAITS and no GAPS ({', '.join(x['clean'])})")
    if s == DOD_UNMEASURED:
        return (f"DOD-1: unmeasured - {len(x['unmeasured'])} run(s) since {x['since']} "
                f"carry no `waits_s` in their row (a runlog older than CF-0317)")
    if x.get("reruns") or x.get("ruled") or x.get("reset") or x.get("login"):
        return (f"DOD-1: no judged run yet - every run since {x['since']} is set aside "
                f"below, so the rule of CF-0317 has not been put to a judged run")
    return (f"DOD-1: no run yet - nothing has started since {x['since']}, "
            f"so the rule of CF-0317 has not been put to a run")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_list():
    for p in POINTS:
        print(f"{p['id']:<34} {p['stage']:<18} {p['kind']:<12} {p['repo']:<26} -> {p['code']}")
    print(f"\n{len(POINTS)} points, {len(CODES)} codes, "
          f"{sum(1 for p in POINTS if blocks(p))} of them still blocking")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runlog no-waiting", add_help=True,
                                 description="CF-0317: no stage of an autonomous run waits for a human")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="print the register of wait points and exit")
    ap.add_argument("--dod", action="store_true", help="DoD 1 over pipeline/runs.jsonl")
    ap.add_argument("--since", default=RULE_EPOCH, help=f"the rule's epoch (default {RULE_EPOCH})")
    ap.add_argument("--root", default=None)
    ns = ap.parse_args([] if argv is None else list(argv))
    if ns.list:
        if ns.json:
            print(json.dumps(list(POINTS), ensure_ascii=False, indent=2))
        else:
            _print_list()
        return 0
    if ns.dod:
        x = dod(ns.root, since=ns.since)
        print(json.dumps(x, ensure_ascii=False, indent=2) if ns.json else x["line"])
        return 3 if x["state"] == DOD_FAILED else 0
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None:
        sys.stderr.write("runlog no-waiting: no batch directory (use --batch DIR, or --dod)\n")
        return 2
    a = audit(bdir, since=ns.since)
    if ns.json:
        print(json.dumps(a, ensure_ascii=False, indent=2))
    else:
        print(headline(a) or (
            f"NO-WAITING: clean - {a['batch']} never stood still"
            + ("" if not a.get("reset_stops") else " outside its ruled stop(s): "
               + "; ".join(reset_stop_text(x) for x in a["reset_stops"]))))
        for line in render(a):
            print(line)
    return 3 if a["verdict"] == INCIDENT else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
