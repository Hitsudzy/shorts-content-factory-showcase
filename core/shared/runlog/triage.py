#!/usr/bin/env python3
"""CF-0319: the triage of a batch runs after it, as a script, and files its own tasks.

The defect, from the grill of 2026-09-22 (Q4'). A batch does not file tasks - it
runs the pipeline and writes statistics. What filed them was the session that
drove the batch: it read the run by hand while it was still going and right
after it, and 45 of the 234 task notes added between 2026-09-08 and 2026-09-25
came out of such a read ("triage <batch>", "filed mid-batch", "batch 1722Z
findings"). Nearly every one closed by adding a refusal, and the yield fell from
1.0 to 0.2 ready videos per batch over the same two weeks - the ratchet of
CF-0320. The run's own code wrote nothing into `tasks/` then and writes nothing
now: from the tracked tree `runlog batch-done` touches exactly the files
of the runs table (`pipeline/runs.jsonl`, `RUNS.md`), and
those are statistics.

So the read moves out of the run and into this module, and it reads nothing a
person wrote: `runlog triage --batch DIR`, after `batch-done`.

**Two kinds of event, and only one of them is a task** (task item 3):

* **авария** (`INCIDENT_KINDS`) - something of ours broke: a script that died
  on an exception rather than exiting with its own refusal code (`crash`), a
  stage opened and never closed (`crash` too), an operation the watchdog took
  down (`timeout`, CF-0316), a stage artifact that will not parse
  (`broken_artifact`), and a broken contract between stages (`contract`: a
  stage closed without writing its artifact, a topic that left the batch with
  no reason code, a code outside the funnel's vocabulary), a move of the
  code under the open run (`code_drift`, CF-0398), and a live monitor that is
  not green after the close (`live_monitor`, CF-0511 - `runlog monitors` runs
  between `batch-done` and this triage), and a video the Video Editor stopped
  because its render broke the same way twice in a row (`render_tool_stop`:
  `needs_you.reason` `render_stuck_on_asset`, CF-0518, or `render_broken`,
  CF-0305), and an LLM stage that changed the factory's tracked code while it
  ran (`stage_code_edit`, the executor's event, CF-0713), and a second
  compliance pass whose 04 does not answer 03 (`contract:output:04-...`:
  rows under the wrong id, no row, no `claims_gate` - read from the files
  and from the executor's `stage_contract_break`, CF-0917; the Editor's empty
  close and the scripts' silent losses after it are named in it, not filed
  each). **Always a task.**
* **находка** (`FINDING_KINDS`, CF-0622) - nothing broke, but a check of ours
  saw nothing: a live monitor that was `not_checked` (CF-0558 - the batch it
  reads has left the live tree, the pool dropped the trailer). A task on that
  monitor, keyed by the monitor (`monitor_not_checked:<repo>:<file.py::owner>`)
  so its repeat goes to the open note; not an авария (exit code and the
  `## Аварии` table stay theirs), and never green.
* **потеря темы** - a topic the funnel lost under one of its own codes
  (`shared/runlog/funnel.py`, FUNNEL_CODES). A number in the statistics, never a
  task: a refusal doing its job is not a defect, and filing one as a task is
  exactly how the ratchet turned.

A script that exits `SystemExit: N` is a refusal (every `check_*.py` of the
Researcher, `qc_asset.py`, `fetch_footage.py` on an unavailable source), not a crash:
across the last five example-film batches that is 149 of 149 failed script
events. Anything else in `error` - `KeyError`, `FileNotFoundError`,
`BrokenPipeError`, `CalledProcessError` - is a crash (13 over the whole pool).

**The gate price is a step, not advice** (task item 4, CF-0320). Every rule
registered in `gate_price.RULES` is priced over the last 5 batches on every
triage. A rule whose verdict is not `enforce` - a price above zero that nobody
signed, or no basis at all - while it is refusing in production is an авария
of its own kind (`unpriced_refusal`): the pipeline raised its own bar without
naming the cost. "Refusing in production" is read, in this order, from the
user's recorded decision in `shared/gate-prices.json` (`decision.mode`), from
the channel config at the rule's own path (`video_editor.two_source_gate:
"measure"`, `video_editor.panel_in_frame: {"mode": "warn"}`), from the mode
the registry states for the rule's code (`gate_price.Rule.mode`: `measure` or
`warn`, never a refusal - CF-0472), and otherwise the rule is hard-wired in
code and refuses (`MODE_HARDWIRED`). Because the decision is read before the
switch, a channel may not turn a rule the user left at `warn` (nothing signed)
to a refusing mode - the triage would still read `warn`; that is guarded by
`tests/test_channel_records_match_prices.py` (CF-0528).

**Filing** (task item 2). No human signs anything: the user's decision Q11 of
the same grill, standing for the whole of 1.x. One task per incident key; the
key is written into the note (`triage-key: ...`) and an open task carrying it
takes the incident instead of a second note - the same crash on the next batch
is one more line in the statistics, not one more task. A key whose task is
already closed files a new one that names the old: it came back. From major
version 2 the boundary is code, not records (the user, 07.10): code reaches
`main` only by a release or a hotfix (ROADMAP `## Versioning`); the run's
records - this triage's task notes among them - are written as before.

What is written: `TRIAGE.md` in the batch directory (gitignored, like the
summary) and, without `--dry-run`, the task notes and their `tasks/INDEX.md`
rows. Committing them is the caller's. Exit 0 - no авария (a находка alone files
its task and keeps 0: `runlog monitors` already exited 1 on it); 1 - at least one;
2 - no batch, or a batch that has not reached `batch-done`.
"""
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import funnel      # noqa: E402
import gate_price  # noqa: E402
import git_read    # noqa: E402  (CF-0717)
import monitors    # noqa: E402
import runlog      # noqa: E402
import watchdog    # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TASKS_ENV = "TRIAGE_TASKS_DIR"
REPORT_NAME = "TRIAGE.md"

CRASH = "crash"
TIMEOUT = "timeout"
BROKEN_ARTIFACT = "broken_artifact"
CONTRACT = "contract"
UNPRICED_REFUSAL = "unpriced_refusal"
CODE_DRIFT = "code_drift"              # CF-0398: the code moved under the open run
BUILT_OFF_RUN = "built_off_run"        # CF-0399: a ready video built by other code
VIDEO_EDITOR_STAGE = "video-editor"     # CF-0739: the stage whose reset rebases built_off_run
# CF-0511: a live monitor that is not green after the close (`runlog monitors`).
# An авария and not a finding: a monitor is an invariant of OUR code and of the
# contracts between stages, asked of the batches the factory just shipped (a
# funnel code outside the vocabulary - already a `contract` авария above - a
# gate rule raising on a new batch, a batch past the CF-0224 boundary with no
# fact, a fixture drifted from its batches). None of them is a refusal doing its
# job, which is what a topic loss is; and a monitor that hangs or whose file is
# gone is our check broken. So it is always a task - one per file key, the
# repeat on the next batch goes to the open note, which is what keeps it from
# becoming the ratchet CF-0319 was written against.
LIVE_MONITOR = "live_monitor"
# CF-0518 (the user's decision of 2026-10-04): the Video Editor stops a video
# whose render failed twice in a row with one `error_signature` - after frames
# were drawn (`render_stuck_on_asset`: the video runs into one asset, 0358Z) or
# before the first one both times (`render_broken`, CF-0305). The stop is the
# tool's or the asset's failure, not a refusal of the content: the topic stays
# a `needs_you` loss in the funnel, and the stop itself is an авария keyed by
# the failure, not by the clip, so the same asset failing in the next batch
# lands in the open task.
RENDER_TOOL_STOP = "render_tool_stop"
RENDER_STOP_REASONS = ("render_stuck_on_asset", "render_broken")
# CF-0713: an LLM stage changed the factory's tracked code (the executor's
# `stage_code_edit` event, shared/stage_code_guard.py) - 2001Z's footage-indexer
# patched source_rights.py and finished the batch on it. Ours broke twice: the
# code the stage hit, and the stage that wrote code. Always a task, keyed by
# the repo and the stage, so the same stage editing the same repo again lands
# in the open note.
STAGE_CODE_EDIT = "stage_code_edit"
INCIDENT_KINDS = (CRASH, TIMEOUT, BROKEN_ARTIFACT, CONTRACT, UNPRICED_REFUSAL, CODE_DRIFT,
                  BUILT_OFF_RUN, LIVE_MONITOR, RENDER_TOOL_STOP, STAGE_CODE_EDIT)
# CF-0622: a live monitor that had nothing to check (`not_checked`, CF-0558).
# A finding, not an авария: nothing of ours broke - the monitor saw nothing to
# judge. Still a task (not checked is not green): one per monitor, so the same
# monitor going blind on the next batch lands in the open note.
MONITOR_NOT_CHECKED = "monitor_not_checked"
FINDING_KINDS = (MONITOR_NOT_CHECKED,)
KIND_LABEL = {
    CRASH: "краш",
    TIMEOUT: "операция снята по таймауту",
    BROKEN_ARTIFACT: "битый артефакт",
    CONTRACT: "нарушен контракт между стадиями",
    UNPRICED_REFUSAL: "отказ в силе без подписанной цены",
    CODE_DRIFT: "код сдвинулся под открытым прогоном",
    BUILT_OFF_RUN: "готовый ролик собран не кодом прогона",
    LIVE_MONITOR: "живой монитор не зелёный",
    RENDER_TOOL_STOP: "рендер упёрся в ассет / инструмент",
    MONITOR_NOT_CHECKED: "живому монитору нечего было проверить",
    STAGE_CODE_EDIT: "стадия правила код фабрики",
}
KIND_RELATED = {
    TIMEOUT: "`CF-0316` (сторож)",
    UNPRICED_REFUSAL: "`CF-0320` (цена воротца), `shared/gate-prices.json`",
    CONTRACT: "`CF-0232` (воронка и её словарь кодов)",
    CODE_DRIFT: "`CF-0398` (батч только на `main`, код под ним не двигается), `CF-0400`",
    BUILT_OFF_RUN: "`CF-0399` (ролик несёт версию кода), `CF-0376`",
    LIVE_MONITOR: "`CF-0511` (живые мониторы — шаг закрытия батча), `CF-0503`",
    MONITOR_NOT_CHECKED: "`CF-0558` (не проверено — не зелёное), `CF-0622`, `CF-0511`",
    RENDER_TOOL_STOP: "`CF-0518` (стоп на втором одинаковом падении рендера), "
                      "`CF-0305` (падение до первого кадра)",
    STAGE_CODE_EDIT: "`CF-0713` (стадия не пишет в код фабрики), `CF-0479` (чистое дерево)",
}

REFUSAL_PREFIX = "SystemExit"          # a script's own refusal code, not a crash
MODE_HARDWIRED = "hard-wired"          # no switch in the config: the code refuses
MODE_PENALTY = "penalty"               # CF-0432: costs points in the score, never refuses
MODE_UNKNOWN = "unknown"               # no config to read at all: nothing is claimed
REFUSING_MODES = ("enforce", "fail", "refuse", MODE_HARDWIRED)
CLOSED_STATUSES = ("done", "wontfix")
KEY_LINE = re.compile(r"^triage-key:\s*`?([^`\s]+)`?\s*$", re.M)
TASK_ID = re.compile(r"\bCF-(\d{4})\b")

# The artifact each stage owns. compliance-checker runs twice: its first close
# owes 02, its second 04.
STAGE_ARTIFACTS = {
    "trend-hunter": ("01-trend-hunter.json",),
    "footage-indexer": ("01b-footage-index.json",),
    "compliance-checker": ("02-compliance-checker.json", "04-compliance-checker.json"),
    "content-researcher": ("03-content-researcher.json",),
    "video-editor": ("05-video-editor.json",),
    "frame-judge": (funnel.FRAME_JUDGE_FILE,),
}


# CF-0917: the second compliance pass - its runlog marker, its plan stage.
COMPLIANCE_STAGE = "compliance-checker"
COMPLIANCE_SCRIPTS_PLAN_STAGE = "compliance-scripts"
ROWS_BREAK = "\x00rows-break"          # artifact_incidents: a redirect to the rows break


class NotClosed(Exception):
    """The batch has no `batch-done`: the triage reads a finished run only."""


# --------------------------------------------------------------------------
# the statistics of one run
# --------------------------------------------------------------------------

def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def stage_times(events):
    """[(stage, seconds, runs)] from the markers, in first-seen order; and the
    stages opened and never closed: [(stage, ts)]."""
    open_, total, runs, order, unclosed = {}, {}, {}, [], []
    for e in events:
        if e.get("kind") != "marker":
            continue
        st, stage = e.get("status"), e.get("stage")
        if st == runlog.M_STAGE_START:
            if stage in open_:
                unclosed.append((stage, open_[stage]))
            open_[stage] = e.get("ts")
            if stage not in order:
                order.append(stage)
        elif st == runlog.M_STAGE_DONE and stage in open_:
            a, b = _ts(open_.pop(stage)), _ts(e.get("ts"))
            if a and b:
                total[stage] = total.get(stage, 0.0) + (b - a).total_seconds()
            runs[stage] = runs.get(stage, 0) + 1
    unclosed += sorted(open_.items(), key=lambda kv: kv[1] or "")
    return [(s, round(total.get(s, 0.0), 1), runs.get(s, 0)) for s in order], unclosed


def _closed_markers(events):
    return [e for e in events if isinstance(e, dict) and e.get("kind") == "marker"
            and e.get("status") == runlog.M_STAGE_DONE]


def _incident(kind, key, stage, what, detail, ts=None):
    return {"kind": kind, "key": f"{kind}:{key}", "stage": stage, "what": what,
            "detail": detail, "count": 1, "first": ts, "task": None, "filed": False,
            "dry_run": False}


def _merge(incidents):
    by = {}
    for i in incidents:
        if i["key"] in by:
            by[i["key"]]["count"] += 1
        else:
            by[i["key"]] = dict(i)
    return list(by.values())


def event_incidents(events):
    """Crashes, interrupted stages and watchdog kills, from RUN_EVENTS.jsonl."""
    out = []
    for e in events:
        kind, st = e.get("kind"), e.get("status")
        if kind in ("script", "child") and watchdog.is_kill(e):
            w = e.get(watchdog.WATCHDOG_KEY) or {}
            code = w.get("code") or e.get("rc") or "timeout"
            out.append(_incident(TIMEOUT, f"{e.get('stage')}:{e.get('step')}:{code}",
                                 e.get("stage"), f"{e.get('step')} -> {code}",
                                 f"source {w.get('source') or e.get('video')}, silent "
                                 f"{w.get('silent_s')} s against a ceiling of "
                                 f"{w.get('ceiling_s')} s", e.get("ts")))
            continue
        if st != "failed":
            continue
        if kind == "child" and isinstance(e.get("rc"), str) and e["rc"].endswith("timeout"):
            out.append(_incident(TIMEOUT, f"{e.get('stage')}:{e.get('step')}:{e['rc']}",
                                 e.get("stage"), f"{e.get('tool')} {e.get('step')} -> {e['rc']}",
                                 f"a child of {e.get('step')} timed out "
                                 f"(video {e.get('video')})", e.get("ts")))
        elif kind == "script":
            err = str(e.get("error") or "")
            if err.startswith(REFUSAL_PREFIX):
                continue
            cls = err.split(":", 1)[0].strip() or "no error recorded"
            name = e.get("name") or e.get("step") or "?"
            out.append(_incident(CRASH, f"{e.get('stage')}:{name}:{cls}", e.get("stage"),
                                 f"{name}: {cls}", err[:300] or "the script failed with "
                                 "no error text and no refusal code", e.get("ts")))
    return out


def code_edit_incidents(events):
    """CF-0713: one авария per repo the executor saw an LLM stage change."""
    out = []
    for e in events:
        if not isinstance(e, dict) or e.get("kind") != STAGE_CODE_EDIT:
            continue
        stage = e.get("plan_stage") or e.get("stage")
        for ed in e.get("edits") or []:
            if not isinstance(ed, dict):
                continue
            repo, files = ed.get("repo") or "?", list(ed.get("files") or [])
            what = f"{stage}: {repo}: " + (", ".join(files[:4]) or "commit")
            detail = (f"stage {stage} changed tracked code of {repo} while it ran: "
                      f"{', '.join(files) or '(no file)'}"
                      + (f"; HEAD {ed.get('head_was')} -> {ed.get('head_now')}"
                         if ed.get("head_now") else "")
                      + f" (run {e.get('run')}, mode {e.get('status')}); the batch went on "
                        f"on code its code_shas do not name")
            out.append(_incident(STAGE_CODE_EDIT, f"{repo}:{stage}", stage, what, detail,
                                 e.get("ts")))
    return out


SIEVE_FLAG_OVERRIDE = "sieve_flag_override"   # CF-0713: footage-indexer's sieve_flag_override.py


def flag_overrides(events):
    """CF-0713: every sieve flag a stage changed after the describer answered
    it (`sieve_flag_override` events) - who, which source and shots, what to,
    why. Not an incident: the override is allowed, it only may not be silent,
    so it is listed in its own section of TRIAGE.md and nothing is filed."""
    out = []
    for e in events:
        if not isinstance(e, dict) or e.get("kind") != SIEVE_FLAG_OVERRIDE:
            continue
        out.append({"ts": e.get("ts"), "stage": e.get("stage"), "by": e.get("by"),
                    "video": e.get("video"), "flag": e.get("flag"), "to": e.get("to"),
                    "shots": list(e.get("shots") or []), "was": list(e.get("was") or []),
                    "why": e.get("note")})
    return out


# CF-0730: a stage's sanctioned no-waiting exit (CF-0317) names the upstream
# file it found missing - `--note "01b-footage-index.json is missing, no
# scripts written"`. The break of the contract is then the upstream stage's.
MISSING_UPSTREAM_RE = re.compile(r"([\w./-]+\.json) is missing")
# CF-0763..0766 (example-tech/2026-10-16T0702Z): the downstream stages' own
# closes on an empty batch spell it "no 03-content-researcher.json: ..." -
# compliance-scripts, the Editor and the frame judge each closed on the
# Researcher's missing 03 (and the judge on the Editor's missing 05), and the
# triage filed four broken contracts for one. Both spellings name the file.
NO_UPSTREAM_RE = re.compile(r"(?<![\w-])no ([\w./-]+\.json)")


def _named_missing(note):
    """The files a close's note names as missing, in the order they appear."""
    hits = [(m.start(), m.group(1)) for rx in (MISSING_UPSTREAM_RE, NO_UPSTREAM_RE)
            for m in rx.finditer(note)]
    return [name for _, name in sorted(hits)]


def _owner_of(name):
    for stage, owed in STAGE_ARTIFACTS.items():
        if name in owed:
            return stage
    return None


def _reset_covers(r, stage, name, channel, cache):
    """Did the reset `r` reset the run of `stage` that owed `name`? By the plan
    stage producing the file when the plan names one (a shared marker is not
    enough: compliance-scripts' reset does not reset compliance-shortlist's
    02), else by the marker."""
    if "producers" not in cache:
        cache["producers"] = runlog.plan_producers(channel)
    prod = cache["producers"].get(name)
    if prod:
        return prod in (r.get("reset") or [])
    return stage in runlog.reset_names(r, channel, None, cache.setdefault("markers", {}))


# CF-0917: the executor's event for an LLM stage it failed because the file
# it wrote breaks the contract with the files it read (run_executor
# CONTRACT_BREAK_EVENT): {stage, plan_stage, file, note, reason_code}.
STAGE_CONTRACT_BREAK = "stage_contract_break"


def contract_breaks(events):
    return [e for e in events or [] if isinstance(e, dict)
            and e.get("kind") == STAGE_CONTRACT_BREAK]


def artifact_incidents(events, f, resets=(), channel=None, explained=None):
    """Broken artifacts and broken contracts, from the funnel's own reading.

    CF-0730 (example-film/2026-10-13T1411Z): two readings of a stage-done whose
    file is not there.
    * A close before a recorded reset (CF-0739, `resets`) that reset that
      stage is superseded: the reset threw that run away and the stage ran
      again - the later run is judged, the old one is listed in `explained`
      (`artifact_superseded`), never silently. It does not count toward the
      n-th file a stage owes (compliance-checker: 02, then 04).
    * A close whose note names another stage's file as missing (the
      no-waiting exit of CF-0317, `missing_upstream_file_skip`) is the
      upstream stage's broken contract - keyed `contract:missing:<upstream
      file>` under the upstream stage, so it merges with the upstream's own
      close without its file - not the downstream stage's, which did what its
      SKILL says."""
    out = []
    for line in f.get("errors") or []:
        name = line.split(":", 1)[0]
        out.append(_incident(BROKEN_ARTIFACT, name, None, name, line))
    unreadable = {line.split(":", 1)[0] for line in f.get("errors") or []}
    have = lambda name: bool(f.get("_dir") and (Path(f["_dir"]) / name).is_file())  # noqa: E731
    cache = {}
    seen = {}
    # CF-0763: a file whose stage closed on its no-waiting exit naming another
    # stage's missing file -> that file. The break of the chain is followed to
    # the first stage that broke, so one empty upstream is one task, and the
    # stages that closed on its absence are named in it, not filed each.
    redirect, first_of, downstream = {}, {}, {}

    def root_of(name):
        hops = set()
        while name in redirect and name not in hops:
            hops.add(name)
            name = redirect[name]
        return name
    # CF-0917: 04 that does not answer 03 (rows under the wrong id, no row, no
    # claims_gate) is the second compliance pass's broken contract - one
    # авария under compliance-checker, whatever happened downstream. When it
    # left the Editor nothing to build (no script of 03 both has a row and was
    # cleared), the Editor's close without 05 - and the judge's close on the
    # missing 05 after it - is that break's consequence, named in it, not
    # filed as the Editor's (0835Z filed only `missing:05-video-editor.json`).
    # The executor's own `stage_contract_break` (it failed the stage, so the
    # stages after it never ran) is the same break, said by the run.
    rows = f.get(funnel.COMPLIANCE_ROWS_KEY) or {}
    rows_key = f"output:{funnel.SCRIPTS_04_FILE}"
    brk = None
    for e in contract_breaks(events):
        if e.get("file") != funnel.SCRIPTS_04_FILE:
            continue
        t = runlog._reset_t(e.get("ts"))
        by = next((r for r in resets or [] if t is not None and t < r["t"]
                   and e.get("plan_stage") in (r.get("reset") or [])), None)
        if by is None:
            brk = e
        elif explained is not None:
            explained.append({"what": "contract_break_superseded", "stage": e.get("stage"),
                              "file": e.get("file"), "ts": e.get("ts"),
                              "reset": runlog.reset_brief(by)})
    if rows or brk:
        said = (f"; the executor failed {brk.get('plan_stage') or COMPLIANCE_SCRIPTS_PLAN_STAGE} "
                f"on it ({brk.get('reason_code')}), the stages after it did not run"
                if brk else "")
        first_of[rows_key] = len(out)
        out.append(_incident(
            CONTRACT, rows_key, COMPLIANCE_STAGE,
            f"{COMPLIANCE_STAGE} -> {funnel.SCRIPTS_04_FILE}: does not answer "
            f"03-content-researcher.json",
            f"{rows.get('line') or brk.get('note')} - the second compliance pass (plan stage "
            f"{COMPLIANCE_SCRIPTS_PLAN_STAGE}) broke its contract with 03; a script with no "
            f"row reaches the Editor unjudged and is lost there, not refused (CF-0917)"
            + said, (brk or {}).get("ts")))
        if rows.get("missing") and not rows.get("cleared_with_row"):
            redirect[STAGE_ARTIFACTS[VIDEO_EDITOR_STAGE][0]] = ROWS_BREAK
    for e in _closed_markers(events):
        stage = e.get("stage")
        owed = STAGE_ARTIFACTS.get(stage)
        if not owed:
            continue
        t = runlog._reset_t(e.get("ts"))
        name = owed[min(seen.get(stage, 0), len(owed) - 1)]
        by = next((r for r in resets or [] if t is not None and t < r["t"]
                   and _reset_covers(r, stage, name, channel, cache)), None)
        if by is not None:
            if explained is not None and not have(name):
                explained.append({"what": "artifact_superseded", "stage": stage,
                                  "file": name, "ts": e.get("ts"),
                                  "reset": runlog.reset_brief(by)})
            continue
        n = seen.get(stage, 0)
        seen[stage] = n + 1
        name = owed[min(n, len(owed) - 1)]
        if name in unreadable or have(name):
            continue
        note = str(e.get("note") or "")
        if redirect.get(name) == ROWS_BREAK:
            # CF-0917: the Editor had nothing to build - 04 answered no script
            downstream.setdefault(rows_key, []).append(stage)
            continue
        # CF-0763: only a file that is really not there moves the break
        # upstream - a stage that had its input and wrote nothing is its own
        up = next((m for m in _named_missing(note)
                   if _owner_of(m) and _owner_of(m) != stage and not have(m)), None)
        if up:
            redirect[name] = up
            first = root_of(up)
            if first == ROWS_BREAK:
                downstream.setdefault(rows_key, []).append(stage)
                continue
            owner = _owner_of(first)
            key = f"missing:{first}"
            downstream.setdefault(key, []).append(stage)
            first_of.setdefault(key, len(out))
            out.append(_incident(CONTRACT, key, owner, f"{owner} -> {first}",
                                 f"{stage} closed on its no-waiting exit ({note[:160]}): "
                                 f"{up} was not there when it ran - the break is upstream, "
                                 f"at {owner}" + (f" (whose {first} is missing first)"
                                                  if first != up else "")
                                 + f"; {stage} wrote no {name} by its rule",
                                 e.get("ts")))
            continue
        first_of.setdefault(f"missing:{name}", len(out))
        out.append(_incident(CONTRACT, f"missing:{name}", stage, f"{stage} -> {name}",
                             f"{stage} closed (stage-done) without writing {name}"
                             + (f" ({note[:160]})" if note else ""), e.get("ts")))
    for key, stages in downstream.items():
        if key == rows_key:
            out[first_of[key]]["detail"] += (f"; left with no script to build, closed "
                                             f"downstream without their file, not filed "
                                             f"each (CF-0917): {', '.join(stages)}")
            continue
        out[first_of[key]]["detail"] += (f"; closed on its absence downstream, not filed "
                                         f"each (CF-0763): {', '.join(stages)}")
    starved = set(rows.get("missing") or [])
    folded = []
    for u in f.get("unexplained") or []:
        if u.get("item") in starved or (brk and u.get("stage") ==
                                         STAGE_ARTIFACTS[VIDEO_EDITOR_STAGE][0]):
            folded.append(u.get("item"))     # CF-0917: the rows break's, said there
            continue
        step = u.get("step") or u.get("stage") or "?"
        out.append(_incident(CONTRACT, f"unexplained:{step}", u.get("stage"),
                             f"a topic lost at {step} without a reason code",
                             json.dumps(u, ensure_ascii=False, default=str)[:300]))
    if folded:
        out[first_of[rows_key]]["detail"] += (
            f"; the funnel's {len(folded)} silent loss(es) are these scripts, not filed "
            f"as `unexplained` (CF-0917): {', '.join(folded[:6])}")
    for code in f.get("unknown_codes") or []:
        out.append(_incident(CONTRACT, f"unknown_code:{code}", None,
                             f"code {code} outside the funnel's vocabulary",
                             f"`{code}` is not in funnel.FUNNEL_CODES"))
    return out


def built_off_run_incidents(events, batch_dir, ready_slugs, root=None, resets=None):
    """CF-0399: a ready video whose `code_shas` (05-video-editor.json) is not
    the code the run started on - a commit other than the batch-start header's,
    or a dirty tree. The CF-0376 case: a video in the batch built by a rebuild
    or a hand run on other code. One key per repo and reason, a count per
    video. A video without `code_shas` (built before CF-0399) or with `null`
    is unknown and is not claimed either way; a repo the header has no commit
    for is compared on `dirty` only. Other code is judged by the rule of
    code_drift (runlog.code_moved, CF-0484): a root commit that moved records
    only (NON_CODE_PATHS) is the run's code; an agent differs on any sha.
    CF-0685: so is a root commit that moved only another channel's config -
    the batch's channel is read from its directory (runlog.batch_channel).
    CF-0739: when a recorded reset (run-state.json `manual_resets`) reset the
    video-editor, its videos are judged against the code base that reset set -
    the HEADs at the first stage-start after it (runlog.code_bases) - and a
    move after that is still another code."""
    starts = [e for e in events if isinstance(e, dict) and e.get("kind") == "marker"
              and e.get("status") == runlog.M_BATCH_START]
    header = runlog._header_heads(starts[-1:])
    channel = runlog.batch_channel(batch_dir, root)          # CF-0685
    if resets is None:
        resets = runlog.manual_resets(batch_dir, events)
    cache = {}
    for r, heads in runlog.code_bases(events, resets):       # CF-0739
        if VIDEO_EDITOR_STAGE in runlog.reset_names(r, channel, root, cache):
            header = dict(heads)
    out = []
    ready = set(ready_slugs)
    for m in runlog.editor_videos(batch_dir):
        shas = m["entry"].get("code_shas")
        if m["slug"] not in ready or not isinstance(shas, dict):
            continue
        for label, st in sorted(shas.items()):
            if not isinstance(st, dict):
                continue
            commit, was = st.get("commit"), header.get(label)
            if runlog.code_moved(label, was, commit, root, channel=channel):
                out.append(_incident(BUILT_OFF_RUN, f"{label}:commit", "video-editor",
                                     f"{label}: {str(was)[:12]} -> {str(commit)[:12]}",
                                     f"ready video {m['slug']} was built by {label} at "
                                     f"{commit}, the run started on {was}: the video is not "
                                     f"the output of the run's code"))
            if st.get("dirty") is True:
                out.append(_incident(BUILT_OFF_RUN, f"{label}:dirty", "video-editor",
                                     f"{label}: dirty tree",
                                     f"ready video {m['slug']} was built by {label} at "
                                     f"{commit} with uncommitted changes: no commit "
                                     f"reproduces it"))
    return out


def monitor_incidents(m):
    """CF-0511: one авария per live-monitor file that is not green, keyed by
    repo and file (`live_monitor:root:tests/test_funnel.py`). Monitors that did
    not run are no incident - the summary and TRIAGE.md say so instead. A file
    that is `not_checked` is no авария either: `monitor_findings` (CF-0622)."""
    out = []
    for f in monitors.broken_files(m):
        detail = (f"{f['state']}: {f.get('error') or '-'}; "
                  f"FAIL {', '.join(f['failed'])}" if f.get("failed") else
                  f"{f['state']}: {f.get('error') or '-'}")
        out.append(_incident(LIVE_MONITOR, f"{f['repo']}:{f['file']}", None,
                             f"{f['repo']}:{f['file']} ({f.get('env') or '-'}=1) -> "
                             f"{f['state']}",
                             f"{detail}; monitors {', '.join(f.get('monitors') or [])}; "
                             f"output in {monitors.REPORT_FILE} of the batch",
                             (m or {}).get("ts")))
    return out


def monitor_findings(m):
    """CF-0622: one находка per live monitor that had nothing to check, keyed
    by repo and monitor (`monitor_not_checked:video-editor:test_x.py::_live`) -
    the registry key the `NOT_CHECKED` line names, else the test, else the file."""
    out = []
    for f in monitors.unchecked_files(m):
        rows = f.get("not_checked") or [{"test": t, "monitor": None, "why": f.get("error")}
                                        for t in f.get("failed") or []] \
            or [{"test": None, "monitor": None, "why": f.get("error")}]
        for r in rows:
            who = r.get("monitor") or (f"{Path(f['file']).name}::{r['test']}" if r.get("test")
                                       else f["file"])
            out.append(_incident(MONITOR_NOT_CHECKED, f"{f['repo']}:{who}", None,
                                 f"{f['repo']}:{who} ({f.get('env') or '-'}=1) -> not checked",
                                 f"{f['repo']}:{f['file']} test {r.get('test') or '-'}: "
                                 f"{r.get('why') or '-'}; passed {f.get('passed') or '-'}, "
                                 f"exit {f.get('rc')}; output in {monitors.REPORT_FILE} of "
                                 f"the batch", (m or {}).get("ts")))
    return out


# The asset a signature names under the batch's work dir (`<work>/clips/a06_…
# .mp4`, CF-0518 normalisation of attempts.error_signature), up to a quote or
# a space - the clip differs from batch to batch, the failure does not.
_WORK_ASSET = re.compile(r"<work>/[^\s\"'`]*")


def render_stop_key(reason, signature):
    """The key of a render stop: `video-editor:<reason>:<signature>`, with the
    asset under `<work>/` read as `<asset>` and the signature made one token
    (a triage key is one: `triage-key: ...` is matched up to the first space
    or backtick) - whitespace runs to `_`, backticks to `'`."""
    sig = _WORK_ASSET.sub("<asset>", str(signature or "")) or "no-signature"
    sig = re.sub(r"\s+", "_", sig.strip()).replace("`", "'")
    return f"video-editor:{reason}:{sig[:200]}"


def render_stop_incidents(batch_dir):
    """CF-0518 / CF-0305: one авария per video of `05-video-editor.json`
    `videos[]` whose `needs_you.reason` is a render stop, keyed by the reason
    and the failure (`render_stop_key`), never by the clip."""
    out = []
    for m in runlog.editor_videos(batch_dir):
        ny = m["entry"].get("needs_you")
        if not isinstance(ny, dict) or ny.get("reason") not in RENDER_STOP_REASONS:
            continue
        reason = ny["reason"]
        sig = ny.get("error_signature") or ny.get("error") or ny.get("last_failure")
        asset = ny.get("asset")
        where = Path(asset).name if asset else "ассет не назван"
        out.append(_incident(RENDER_TOOL_STOP, render_stop_key(reason, sig), "video-editor",
                             f"{reason}: {where}",
                             f"video {m['slug']}: renders {ny.get('renders') or '-'}, "
                             f"frames_rendered {ny.get('frames_rendered') or '-'}, "
                             f"asset {asset or '-'}; error: "
                             f"{str(ny.get('error') or ny.get('last_failure') or '-')[:300]}",
                             ny.get("at")))
    return out


def _monitor_digest(m):
    if m is None:
        return None
    return {"state": m.get("state"), "files": len(m.get("files") or []),
            "red": [f"{f['repo']}:{f['file']} {f['state']}" for f in monitors.broken_files(m)],
            "not_checked": [f"{f['repo']}:{f['file']} {f['state']}"
                            for f in monitors.unchecked_files(m)],
            "ts": m.get("ts")}


# --------------------------------------------------------------------------
# the gate price step (CF-0320)
# --------------------------------------------------------------------------

def mode_of(rule_name, config=None, ledger=None):
    """How the rule stands in production: the user's decision, the channel
    config's switch at the rule's own path, the mode of its code as the
    registry states it (`gate_price.Rule.mode`, CF-0472), or MODE_HARDWIRED."""
    row = ((ledger or {}).get("rules") or {}).get(rule_name, {})
    # CF-0432: a rule the score model holds as a penalty only costs points; it
    # is never a refusal, priced or not, whatever the config switch says.
    if isinstance(row, dict) and row.get("mode") == MODE_PENALTY:
        return MODE_PENALTY, "score model"
    dec = row.get("decision") if isinstance(row, dict) else None
    if isinstance(dec, dict) and dec.get("mode"):
        return str(dec["mode"]), "decision"
    if isinstance(config, dict):
        d = config
        for part in rule_name.split("."):
            d = d.get(part) if isinstance(d, dict) else None
        if isinstance(d, str):
            return d, "config"
        if isinstance(d, dict) and d.get("mode"):
            return str(d["mode"]), "config"
    # CF-0472: the registry knows what the rule's code does - it records
    # (`measure`) or warns (`warn`). Only a non-refusing mode is ever
    # registered, so this can lift a false `hard-wired`, never invent a refusal.
    reg = getattr(gate_price.RULES.get(rule_name), "mode", None)
    if reg:
        return str(reg), "registry"
    if not isinstance(config, dict):
        # No channel config to read the switch from (a synthetic `backfill/`
        # run, a channel this checkout does not carry): the mode is unknown,
        # and an unknown mode is not evidence of a refusal.
        return MODE_UNKNOWN, "no channel config"
    return MODE_HARDWIRED, "code"


def gate_step(config=None, ledger=None, results=None, pool=None):
    """Every registered rule, priced; an `unpriced_refusal` for each one that
    refuses while its price does not let it."""
    if results is None:
        results = gate_price.measure_all(pool=pool)
    if ledger is None:
        ledger = gate_price.read_ledger()
    rows, incidents = [], []
    for r in results:
        mode, whence = mode_of(r["rule"], config, ledger)
        refusing = mode in REFUSING_MODES
        row = {"rule": r["rule"], "price": r.get("price"), "verdict": r.get("verdict"),
               "measured_on": r.get("measured_on"), "of": r.get("of"), "mode": mode,
               "mode_from": whence, "refusing": refusing, "why": r.get("why")}
        rows.append(row)
        if refusing and r.get("verdict") != gate_price.ENFORCE:
            incidents.append(_incident(
                UNPRICED_REFUSAL, r["rule"], None, r["rule"],
                f"refuses in production (mode `{mode}`, from the {whence}) while its price "
                f"does not let it: {r.get('why')}"))
    return rows, incidents


# --------------------------------------------------------------------------
# the whole read
# --------------------------------------------------------------------------

def _config_for(batch_dir):
    cid = funnel._channel_ids()
    try:
        p = (cid.channel_config_path(Path(batch_dir).parent.name) if cid
             else ROOT / "channels" / f"{Path(batch_dir).parent.name}.json")
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return None


def triage(batch_dir, events=None, config=None, ledger=None, gate_results=None, pool=None,
           require_done=True):
    """The statistics and the incidents of one finished run. Writes nothing."""
    bd = Path(batch_dir)
    evs = events if events is not None else runlog.sibling("event_log").load_events(bd)  # CF-0718
    if require_done and not any(e.get("kind") == "marker"
                                and e.get("status") == runlog.M_BATCH_DONE for e in evs):
        raise NotClosed(f"{bd}: no batch-done - the triage reads a finished run only")
    f = funnel.funnel(bd)
    f["_dir"] = str(bd)
    times, unclosed = stage_times(evs)
    incidents = event_incidents(evs) + code_edit_incidents(evs)
    # CF-0739: a recorded reset of the batch's stages (run-state.json
    # `manual_resets`, or rerun_from's `control batch-rerun-from` event) is a
    # fact of the run: the code base it set, the stages it closed and the stop
    # around it are not аварии. Listed under `resets`, never silently.
    resets = runlog.manual_resets(bd, evs)
    channel = runlog.batch_channel(bd)
    cache = {}
    explained = []
    incidents += artifact_incidents(evs, f, resets, channel, explained)     # CF-0730
    for r in runlog.drift_rows(evs, resets, channel):
        if r["reset"]:
            explained.append({"what": "code_base", "repo": r["repo"], "was": r["was"],
                              "now": r["now"], "marker": r["marker"], "stage": r["stage"],
                              "ts": r["ts"], "reset": r["reset"]})
    for stage, ts in list(unclosed):
        t = runlog._reset_t(ts)
        for r in resets:
            if t is not None and t < r["t"] and stage in runlog.reset_names(r, channel, None,
                                                                             cache):
                unclosed.remove((stage, ts))
                explained.append({"what": "stage_closed", "stage": stage, "ts": ts,
                                  "reset": runlog.reset_brief(r)})
                break
    for r in runlog.drift_rows(evs, resets, channel):   # CF-0398: one key per repo, a count per move
        if r["reset"]:
            continue
        incidents.append(_incident(CODE_DRIFT, r["repo"], r["stage"],
                                   f"{r['repo']}: {str(r['was'])[:12]} -> {str(r['now'])[:12]}",
                                   f"HEAD of {r['repo']} moved from {r['was']} to {r['now']} "
                                   f"while the batch was open (seen at {r['marker']} "
                                   f"{r['stage']}); the output of the run does not belong to "
                                   f"one version of the code", r["ts"]))
    incidents += built_off_run_incidents(
        evs, bd, [r.get("slug") for r in f.get("ready") or [] if isinstance(r, dict)],
        resets=resets)
    incidents += render_stop_incidents(bd)
    mon = monitors.of(evs)
    incidents += monitor_incidents(mon)
    for stage, ts in unclosed:
        incidents.append(_incident(CRASH, f"{stage}:stage_not_closed", stage,
                                   f"{stage}: stage-start without stage-done",
                                   f"stage {stage} opened at {ts} and was never closed", ts))
    gates, gate_incidents = gate_step(config if config is not None else _config_for(bd),
                                      ledger, gate_results,
                                      pool if pool is not None else bd.parent.parent)
    incidents = _merge(incidents + gate_incidents)
    findings = _merge(monitor_findings(mon))
    return {"batch": f"{bd.parent.name}/{bd.name}", "dir": str(bd),
            "stage_times": [{"stage": s, "seconds": t, "runs": n} for s, t, n in times],
            "losses": dict(sorted((f.get("losses") or {}).items())),
            "ready": len(f.get("ready") or []),
            "watchdog": watchdog.detect(events=evs),
            "monitors": _monitor_digest(mon),
            "gates": gates, "incidents": incidents, "findings": findings,
            "flag_overrides": flag_overrides(evs),
            "resets": [dict(runlog.reset_brief(r), reset=list(r["reset"]),
                            explained=[x for x in explained
                                       if x["reset"]["at"] == r["at"]])
                       for r in resets]}


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------

def tasks_dir(path=None):
    if path:
        return Path(path)
    env = os.environ.get(TASKS_ENV)
    return Path(env) if env else ROOT / "tasks"


def _status(text):
    m = re.search(r"^status:\s*(\S+)", text, re.M)
    return m.group(1) if m else None


# CF-0492: the task notes of a version worktree (`release/<v>`) lag behind
# `main`, where the driver files new tasks while the version is built. Numbers
# and triage keys are therefore read from the union of the tree's own `tasks/`
# and the same directory on `main` - through git, locally, never the network.
TRUNK_REFS = ("refs/heads/main", "refs/remotes/origin/main")


def _git_lines(d, *args, timeout=20):
    import subprocess
    try:
        cp = git_read.run(["-C", str(d), *args], capture_output=True, text=True,
                          timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout.splitlines() if cp.returncode == 0 else None


def _trunk_tasks(tdir):
    """(git dir, [(ref, path)]) of the task notes `CF-*.md` under the same
    directory as tdir on every trunk ref that exists (TRUNK_REFS); (None, [])
    when tdir is not inside a git work tree or no trunk ref exists."""
    d = Path(tdir)
    while not d.is_dir():
        if d.parent == d:
            return None, []
        d = d.parent
    top = _git_lines(d, "rev-parse", "--show-toplevel")
    if not top:
        return None, []
    try:
        rel = Path(tdir).resolve().relative_to(Path(top[0]).resolve()).as_posix()
    except ValueError:
        return None, []
    d = Path(top[0])                    # paths of ls-tree / grep / show: from the top
    out = []
    for ref in TRUNK_REFS:
        if _git_lines(d, "rev-parse", "--verify", "-q", ref) is None:
            continue
        for path in _git_lines(d, "ls-tree", "-r", "--name-only", ref, "--", f"{rel}/") or []:
            if TASK_ID.match(Path(path).name) and path.endswith(".md"):
                out.append((ref, path))
    return d, out


def _trunk_keyed_notes(tdir):
    """[(file name, text)] of the trunk's task notes that carry a triage key -
    one `git grep` per trunk ref, then one `git show` per keyed note."""
    d, notes = _trunk_tasks(tdir)
    if d is None or not notes:
        return []
    out, wanted = [], set(notes)
    for ref in dict.fromkeys(r for r, _ in notes):
        for line in _git_lines(d, "grep", "-l", "-e", "triage-key:", ref, "--",
                               *sorted({str(Path(p).parent) for r, p in notes if r == ref})) or []:
            path = line[len(ref) + 1:] if line.startswith(ref + ":") else line
            if (ref, path) not in wanted:
                continue
            text = _git_lines(d, "show", f"{ref}:{path}")
            if text is not None:
                out.append((Path(path).name, "\n".join(text) + "\n"))
    return out


def known_keys(tdir):
    """{key: (task_id, status)} over every note that carries a triage key; an
    open note wins over a closed one. CF-0492: the notes on `main` count too -
    the tree's own copy of a note wins over the trunk's."""
    out = {}
    notes = []
    own = set()
    for p in sorted(Path(tdir).rglob("CF-*.md")) if Path(tdir).is_dir() else []:
        try:
            notes.append((p.name, p.read_text(encoding="utf-8")))
            own.add(p.name)
        except OSError:
            continue
    notes += [(n, t) for n, t in _trunk_keyed_notes(tdir) if n not in own]
    for name, text in notes:
        tid = name[:7]
        st = _status(text)
        for key in KEY_LINE.findall(text):
            have = out.get(key)
            if have is None or (have[1] in CLOSED_STATUSES and st not in CLOSED_STATUSES):
                out[key] = (tid, st)
    return out


def next_id(tdir):
    """The next free task number: one past the highest `CF-NNNN` in the tree's
    own `tasks/` and - CF-0492 - in the same directory on `main`, so that a
    triage run from a version worktree whose `tasks/` lags never re-issues a
    number the driver already filed on `main`."""
    n = 0
    names = [p.name for p in Path(tdir).rglob("CF-*.md")] if Path(tdir).is_dir() else []
    names += [Path(path).name for _, path in _trunk_tasks(tdir)[1]]
    for name in names:
        m = TASK_ID.match(name)
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50].strip("-") or "incident"


def render_task(tid, inc, batch, milestone, today, previous=None):
    if inc["kind"] in FINDING_KINDS:
        return render_finding(tid, inc, batch, milestone, today, previous)
    title = f"Авария прогона {batch}: {KIND_LABEL[inc['kind']]} — {inc['what']}"
    related = ", ".join(x for x in ("`CF-0319` (разбор)", KIND_RELATED.get(inc["kind"]),
                                    f"`{previous}` (закрыта, авария вернулась)"
                                    if previous else None) if x)
    return f"""---
id: {tid}
title: "{title.replace('"', "'")}"
type: task
status: open
milestone: {milestone or ''}
dod:
repo: —
created: {today}
closed:
---

## Описание
Заведена разбором прогона (`runlog triage`, `CF-0319`) без подписи пользователя — решение
Q11 гриля 2026-09-22, в силе на весь 1.x. Сорт события — **авария** ({KIND_LABEL[inc['kind']]}):
по правилу `CF-0319` авария — всегда задача, в отличие от потери темы под кодом воронки.

- Батч: `{batch}`
- Стадия: `{inc.get('stage') or '—'}`
- Что: {inc['what']}
- Сколько раз за прогон: {inc['count']}
- Первое событие: {inc.get('first') or '—'}
- Подробности: {inc['detail']}

## Что сделать
Найти причину и устранить её так, чтобы следующий прогон её не повторил. Если исправление
вводит новый отказ (код, снимающий тему или ролик), — сначала цена по правилу `CF-0320`
(`runlog gate-price`): отказ без цены стоит предупреждением.

## Связано
{related}

## Ключ разбора
triage-key: `{inc['key']}`
"""


def render_finding(tid, inc, batch, milestone, today, previous=None):
    """CF-0622: the note of a находка - a monitor that saw nothing to check."""
    title = f"Находка прогона {batch}: {KIND_LABEL[inc['kind']]} — {inc['what']}"
    related = ", ".join(x for x in ("`CF-0319` (разбор)", KIND_RELATED.get(inc["kind"]),
                                    f"`{previous}` (закрыта, находка вернулась)"
                                    if previous else None) if x)
    return f"""---
id: {tid}
title: "{title.replace('"', "'")}"
type: task
status: open
milestone: {milestone or ''}
dod:
repo: —
created: {today}
closed:
---

## Описание
Заведена разбором прогона (`runlog triage`, `CF-0319`) без подписи пользователя. Сорт события —
**находка** ({KIND_LABEL[inc['kind']]}), не авария: ничего не сломалось, но живой монитор
не нашёл, что проверить (`NOT_CHECKED`, `CF-0558`), — проверка этого батча не состоялась,
а не проверено — не зелёное (`CF-0622`).

- Батч: `{batch}`
- Монитор: {inc['what']}
- Сколько раз за прогон: {inc['count']}
- Первое событие: {inc.get('first') or '—'}
- Подробности: {inc['detail']}

## Что сделать
Вернуть монитору предмет проверки: он должен читать то, что фабрика выпускает сейчас
(новейший батч, где лежит нужное, — `newest_run()`), или, если предмета больше нет,
снять монитор из реестра (`tests/_live_monitors.py` агента / `tests/_real_batches.py` корня)
вместе с его правилом в наборе тестов.

## Связано
{related}

## Ключ разбора
triage-key: `{inc['key']}`
"""


def file_tasks(result, tdir=None, milestone=None, today=None, dry_run=False):
    """Attach every incident and every finding (CF-0622) to an open task with
    its key, or file a new one. Returns the list of (task_id, path) filed."""
    tdir = tasks_dir(tdir)
    today = today or date.today().isoformat()
    known = known_keys(tdir)
    nid = next_id(tdir)
    filed = []
    for inc in list(result["incidents"]) + list(result.get("findings") or []):
        have = known.get(inc["key"])
        if have and have[1] not in CLOSED_STATUSES:
            inc["task"] = have[0]
            continue
        tid = f"CF-{nid:04d}"
        nid += 1
        inc["task"], inc["filed"], inc["dry_run"] = tid, not dry_run, dry_run
        name = f"{tid}-triage-{inc['kind'].replace('_', '-')}-{_slug(inc['what'])}.md"
        text = render_task(tid, inc, result["batch"], milestone, today,
                           previous=have[0] if have else None)
        filed.append((tid, tdir / name))
        if dry_run:
            continue
        (tdir / name).write_text(text, encoding="utf-8")
        _index_row(tdir, tid, name, milestone, text)
        known[inc["key"]] = (tid, "open")
    return filed


def _index_row(tdir, tid, name, milestone, text):
    idx = Path(tdir) / "INDEX.md"
    if not idx.is_file():
        return
    title = re.search(r'^title:\s*"(.*)"$', text, re.M).group(1).replace("|", "/")
    row = f"| [{tid}]({name}) | {milestone or '—'} | task | open | — | {title} |\n"
    body = idx.read_text(encoding="utf-8")
    if not body.endswith("\n"):
        body += "\n"
    idx.write_text(body + row, encoding="utf-8")


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def _hms(s):
    s = int(round(s or 0))
    return f"{s // 3600}ч{s % 3600 // 60:02d}м{s % 60:02d}с"


def render(result):
    out = [f"# Разбор прогона {result['batch']} (CF-0319)", "",
           "Прогон задач не заводит. Этот разбор делит события на **аварии** (задача всегда) "
           "и **потери темы** (число в статистике, не задача).", "",
           f"Готовых роликов: **{result['ready']}**.", "", "## Время по стадиям", ""]
    if result["stage_times"]:
        out += ["| стадия | время | прогонов |", "|---|---|---|"]
        out += [f"| {r['stage']} | {_hms(r['seconds'])} | {r['runs']} |"
                for r in result["stage_times"]]
    else:
        out.append("Маркеров стадий нет.")
    out += ["", "## Потери темы (коды воронки)", ""]
    if result["losses"]:
        out += ["| код | тем |", "|---|---|"]
        out += [f"| `{c}` | {n} |" for c, n in result["losses"].items()]
    else:
        out.append("Ни одной.")
    mon = result.get("monitors")
    out += ["", "## Живые мониторы (CF-0511)", ""]
    if mon is None:
        out.append("Не запускались: после `batch-done` шаг закрытия — `runlog monitors`, "
                   "потом этот разбор.")
    elif not mon["red"] and not mon.get("not_checked"):
        out.append(f"{mon['files']}/{mon['files']} файлов зелёные.")
    else:
        if mon["red"]:
            out.append(f"Не зелёные {len(mon['red'])} из {mon['files']} — каждый авария (ниже); "
                       f"вывод в `{monitors.REPORT_FILE}` батча.")
            out += [f"- `{r}`" for r in mon["red"]]
        if mon.get("not_checked"):
            out += ([""] if mon["red"] else []) + [
                f"Не проверены {len(mon['not_checked'])} из {mon['files']} — монитору нечего "
                f"было проверить: не зелёное, находка (ниже, CF-0622); вывод в "
                f"`{monitors.REPORT_FILE}` батча."]
            out += [f"- `{r}`" for r in mon["not_checked"]]
    overrides = result.get("flag_overrides") or []
    out += ["", f"## Ручные перезаписи флагов сита: {len(overrides)} (CF-0713)", ""]
    if overrides:
        out += ["Стадия поменяла ответ описателя через `sieve_flag_override.py` — разрешено, "
                "но не молча: кто, что и почему.", "",
                "| кто | источник | флаг | кадры | было → стало | почему |",
                "|---|---|---|---|---|---|"]
        for o in overrides:
            was = ", ".join(str(w).lower() for w in sorted(set(map(str, o["was"])))) or "—"
            out.append(f"| {o['by'] or o['stage']} | `{o['video']}` | `{o['flag']}` | "
                       f"{', '.join(map(str, o['shots']))} | {was} → {str(o['to']).lower()} | "
                       f"{str(o['why'] or '').replace('|', '/')} |")
    else:
        out.append("Ни одной.")
    resets = result.get("resets") or []
    if resets:                                   # CF-0739: never silent
        out += ["", f"## Ручные сбросы стадий: {len(resets)} (CF-0739)", "",
                "Сброс записан в `run-state.json` (`manual_resets`): с него у сброшенных "
                "стадий новая база кода, начатые до него стадии им закрыты, остановка вокруг "
                "него — не простой. Это не аварии; движение кода после сброса — авария, как "
                "всегда.", ""]
        for r in resets:
            out.append(f"- {r['at']}: {r['task'] or 'без задачи'}, {r['by'] or '?'} — "
                       f"{r['why'] or 'причина не записана'} (с {r['from']}, "
                       f"{len(r['reset'])} стад.)")
            for x in r["explained"]:
                if x["what"] == "code_base":
                    out.append(f"  - база кода: {x['repo']} {str(x['was'])[:12]} -> "
                               f"{str(x['now'])[:12]} (замечено на {x['marker']} "
                               f"{x['stage'] or ''} {x['ts']})")
                elif x["what"] == "artifact_superseded":                 # CF-0730
                    out.append(f"  - стадия {x['stage']} закрылась {x['ts']} без {x['file']} "
                               f"до сброса; этот прогон сброшен, судится следующий")
                elif x["what"] == "contract_break_superseded":           # CF-0917
                    out.append(f"  - стадия {x['stage']} нарушила контракт {x['file']} "
                               f"{x['ts']} до сброса; этот прогон сброшен, судится следующий")
                else:
                    out.append(f"  - стадия {x['stage']}, начатая {x['ts']}, закрыта сбросом")
    out += ["", f"## Снятые сторожем операции: {len(result['watchdog'])}", "",
            "## Цена воротец (CF-0320, обязательный шаг)", "",
            "| правило | цена | вердикт | режим | откуда режим |", "|---|---|---|---|---|"]
    for g in result["gates"]:
        price = "нет основания" if g["price"] is None else g["price"]
        out.append(f"| `{g['rule']}` | {price} | {g['verdict']} | {g['mode']} | {g['mode_from']} |")
    out += ["", f"## Аварии: {len(result['incidents'])}", ""]
    if result["incidents"]:
        out += ["| сорт | что | раз | задача |", "|---|---|---|---|"]
        for i in result["incidents"]:
            task = (f"{i['task']} (заведена)" if i.get("filed")
                    else f"{i['task']} (будет заведена, --dry-run)" if i.get("dry_run")
                    else f"{i['task']} (уже открыта)" if i.get("task") else "—")
            out.append(f"| {KIND_LABEL[i['kind']]} | {i['what'].replace('|', '/')} | "
                       f"{i['count']} | {task} |")
    else:
        out.append("Ни одной.")
    findings = result.get("findings") or []
    if findings:
        out += ["", f"## Находки: {len(findings)}", "",
                "Не аварии: ничего не сломалось, но проверка не состоялась — задача на неё.", "",
                "| сорт | что | раз | задача |", "|---|---|---|---|"]
        for i in findings:
            task = (f"{i['task']} (заведена)" if i.get("filed")
                    else f"{i['task']} (будет заведена, --dry-run)" if i.get("dry_run")
                    else f"{i['task']} (уже открыта)" if i.get("task") else "—")
            out.append(f"| {KIND_LABEL[i['kind']]} | {i['what'].replace('|', '/')} | "
                       f"{i['count']} | {task} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog triage",
                                 description="the post-run triage of a batch (CF-0319)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--tasks", default=None, help="the tasks/ directory to file into")
    ap.add_argument("--milestone", default=None,
                    help="milestone of the filed tasks (default: none - the backlog)")
    ap.add_argument("--dry-run", action="store_true",
                    help="file nothing, write nothing; print what would be filed")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bd = runlog.find_batch_dir(ns.batch)
    if bd is None:
        sys.stderr.write("runlog triage: error: no batch directory (use --batch DIR)\n")
        return 2
    try:
        res = triage(bd)
    except NotClosed as e:
        sys.stderr.write(f"runlog triage: error: {e}\n")
        return 2
    filed = file_tasks(res, ns.tasks, ns.milestone, dry_run=ns.dry_run)
    text = render(res)
    if not ns.dry_run:
        (Path(bd) / REPORT_NAME).write_text(text, encoding="utf-8")
    if ns.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    else:
        sys.stdout.write(text)
        for tid, p in filed:
            print(f"{'would file' if ns.dry_run else 'filed'} {tid}: {p}")
    return 1 if res["incidents"] else 0


if __name__ == "__main__":
    sys.exit(main())
