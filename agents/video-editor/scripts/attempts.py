#!/usr/bin/env python3
"""CF-0098: the attempt ledger - a hard ceiling on how many times one video
may be (re)built, kept on disk where a wrapper can enforce it.

The cost of the Video Editor stage does not grow with the length of a video;
it grows with the number of rebuilds. Batch 2026-09-03T2037Z: the Clooney
video took 42 minutes and 9.2M cache reads, almost all of it re-renders,
and the Wren Hollow operator died on its session limit halfway through its
first pass. Until now the only ceiling was a sentence in SKILL.md ("two
attempts per rung"), which is a wish, not a limit. This module is the limit.

One entry = one render of the video (`render_video.py` begins one before
it runs Remotion; `qc_render.py` ends it with the verdict). Every render is
an entry and gets its own number `n` and its own log, but not every render
spends an attempt (CF-0415, the user's decision of 2026-09-28): a render
whose *only* change is the degradation QC itself suggested is a
`qc_degrade`, counted against a ceiling of its own and not against the
attempt cap. Everything else - the first render, a re-resolve, a re-cut, a
degradation QC did not ask for, a re-render after `render_failed` - is an
`attempt`. When a cap is reached, `begin` refuses with exit 3 and one line
the operator can paste into the report:

    NEEDS-YOU <slug>: attempt cap <N> reached - last failure: <...>
    NEEDS-YOU <slug>: qc degrade cap <N> reached - last failure: <...>

and writes `needs_you` into the ledger so write_batch_metadata.py carries
it into 05-video-editor.json. There is no "one more try" past that line.

What makes a render a `qc_degrade` (classify(), called by render_video.py
with the plan it is about to render) - all three, read off disk, never off
the operator's word:

  1. the previous render ended `qc_failed` and recorded a `qc_hint`: the
     degradations QC itself names. Today that is one gate - `frozen` -
     and its hint is `<idx>:still` for every block `frozen_blocks()`
     flagged (the `--degrade-block IDX:still:...` SKILL.md feeds back);
     qc_render.py writes it at `end`. No other QC failure suggests a
     degradation (`subject` is a re-cut, `bed`/`caption`/... are fixes);
  2. the plan's `degraded_blocks` are the previous render's plus at least
     one new tag, every new tag is in that hint, and none was taken back;
  3. the plan's `build_inputs.digest` - build_render_plan.py's fingerprint
     of every input but `--degrade-block` (the storyboard, the words, the
     voice, the script by content; every other flag by value) - equals the
     one the previous render was built from. A re-resolve rewrites the
     storyboard, a re-cut too, a new flag changes the arguments: any of them
     is a new digest, and the render is an attempt however many
     `--degrade-block` flags ride along. A plan without a digest (built
     before CF-0415, or by hand) is never a `qc_degrade`.

Ledger: <batch>/work/<slug>/attempts.json

    {
      "slug": "wren-hollow-christmas",
      "attempt_cap": 3,
      "cap_source": "channels/example-film.json#video_editor.max_attempts_per_video"
                    | "default",
      "attempts": [
        {"n": 1, "started_at": "...", "ended_at": "...",
         "kind": "attempt" | "qc_degrade",    # CF-0415: which ceiling it spends
         "reason": "first",                   # why this attempt was started
         "result": "qc_failed",               # how it ended
         "detail": "clip blocks rendered as stills: block 4 (motion 0.32)",
         "failed_gates": ["frozen"],
         "degraded": [],                      # plan["degraded_blocks"] as "idx:to"
         "qc_hint": ["4:still"],              # CF-0415: what QC suggests degrading
         "build_inputs": "3f2a...",           # CF-0415: the plan's input digest
         "log": "/abs/.../logs/wren-hollow-christmas-attempt-1.log"}
      ],
      "qc_degrade_cap": 3,
      "qc_degrade_cap_source": "channels/...#video_editor.max_qc_degrades_per_video"
                               | "default",
      "needs_you": null | {"reason": "attempt cap 3 reached" | "qc degrade cap 3 reached"
                                     | "render_broken" | "render_stuck_on_asset",
                           "last_failure": "...", "attempts": 3, "qc_degrades": 1,
                           "at": "..."}
    }

Reasons: first | qc_failed:<gate> | degraded:<idx:to,...> | recut:<block=shot,...> | render_failed |
         render_broken | assets_rejected | operator | qc_degrade:<idx:to,...>
Results: rendered_ok | qc_failed | assets_rejected | render_failed |
         render_broken | capped | abandoned   (abandoned = begun and never
                               ended; the next begin closes it so it still counts)

CF-0305 (the user's decision of 2026-09-21): a render the *tool* broke
before it drew a single frame did not build the video, so it does not spend
the attempt cap. render_video.py ends such a render `render_broken` (Remotion
printed no `Rendered N/M` with N >= 1, or the mix failed before Remotion
ran); the entry carries `counted: false`, the error line (`error`) and its
normalised form (`error_signature`: times, tmp/job paths, pids, ports and
hex ids taken out). The second `render_broken` in a row with the same
signature writes `needs_you` with reason `render_broken` and the error -
there is no third try of a tool that fails the same way. The stop is lifted
by the fix, not by a flag: a `begin` whose toolchain fingerprint (the agent
checkout's HEAD and its uncommitted diff of scripts/ and render/) or plan
digest differs from the broken renders' moves that `needs_you` to
`lifted_needs_you[]` and begins normally - no `--cap`. A failure after
frames were already drawn is `render_failed` and counts as before; an entry
without `counted` (every one written before CF-0305) counts.

CF-0518 (the user's decision of 2026-10-04): a `render_failed` - frames were
drawn, the render counts - right after a render that failed with the same
`error_signature` writes `needs_you` with reason `render_stuck_on_asset`:
the video runs into the same asset (0358Z: three renders died at frame 512
on one unstaged clip, after 507/508/509 frames drawn) and a third run cannot
change that. Both renders keep `counted: true` - the stop does not give the
attempts back. The previous render may be a `render_broken` as well (the
same tool failure, frames drawn once and not the other time); two
`render_broken` in a row stay the CF-0305 stop. No closeness of
`frames_rendered` is asked: the progress count at the crash is Remotion's
reporting, not the asset (0358Z: 507, 508, 509 for one frame 512), and the
asset is already in the signature. The needs_you carries the error, the
signature, both renders' `frames_rendered`, the asset path read off the
error line (`asset`, or null) and the toolchain/plan digests; it is lifted
the way the CF-0305 stop is - by a change to the code or to the plan.

The caps come from the channel config, channels/<channel>.json:
    "video_editor": {"max_attempts_per_video": 3,
                     "max_qc_degrades_per_video": 3}
and default to DEFAULT_MAX_ATTEMPTS / DEFAULT_MAX_QC_DEGRADES when a key is
absent. A video whose attempts are used up may still take a `qc_degrade`
while QC's last hint stands and the degrade cap has room - `end` does not
write `needs_you` then, and `begin` refuses only the kind that is used up.

CLI:
    attempts.py begin <batch-dir> <slug> (--reason <reason> | --plan plan.json)
                      [--cap N] [--degrade-cap N] [--channel c]
        exit 0 and prints "attempt <n>/<cap> begun (<reason>)"; with --plan
        the kind and the reason are classify()'s (a `qc_degrade` prints
        "qc degrade <k>/<cap> (render <n>) begun (...)")
        exit 3 and prints the NEEDS-YOU line when the cap is reached
    attempts.py end <batch-dir> <slug> --result <result> [--detail ..] [--log path]
        exit 0; prints the NEEDS-YOU line too (exit 3) when this failure
        used up the last attempt - the operator does not have to try a
        fourth begin to learn that.
    attempts.py show <batch-dir> <slug>
"""
import argparse
import functools
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import repo_paths  # CF-0125: channels/ sits above the main checkout
from _runlog import runlog, video_script  # CF-0107: begin/end/show are the attempt boundaries

AGENT_ROOT = Path(__file__).resolve().parent.parent


# The repo root above this agent - the checkout carrying channels/ and
# agents/, so a worktree under .claude/worktrees/ reads the same
# channels/<channel>.json the main checkout does (CF-0125).
PROJECT_ROOT = repo_paths.FACTORY_ROOT

DEFAULT_MAX_ATTEMPTS = 3
CHANNEL_KEY = "video_editor.max_attempts_per_video"
# CF-0415: the degradations QC itself suggested have a ceiling of their own.
DEFAULT_MAX_QC_DEGRADES = 3
DEGRADE_CHANNEL_KEY = "video_editor.max_qc_degrades_per_video"

KIND_ATTEMPT = "attempt"
KIND_QC_DEGRADE = "qc_degrade"
KINDS = (KIND_ATTEMPT, KIND_QC_DEGRADE)
# The one QC gate whose failure names its own degradation: frozen_blocks()
# flags a clip block that renders as a still, and the fix SKILL.md feeds back
# is `--degrade-block IDX:still` on exactly those indices.
QC_HINT_TARGET = "still"
LEDGER_NAME = "attempts.json"
LOGS_DIR = "logs"

EXIT_CAPPED = 3

RESULT_OK = "rendered_ok"
RESULT_QC_FAILED = "qc_failed"
RESULT_ASSETS_REJECTED = "assets_rejected"
RESULT_RENDER_FAILED = "render_failed"
# CF-0305: the tool broke before the first frame - recorded, not counted.
RESULT_RENDER_BROKEN = "render_broken"
RESULT_CAPPED = "capped"
RESULT_ABANDONED = "abandoned"
RESULTS = (RESULT_OK, RESULT_QC_FAILED, RESULT_ASSETS_REJECTED,
           RESULT_RENDER_FAILED, RESULT_RENDER_BROKEN, RESULT_CAPPED, RESULT_ABANDONED)
FAILURES = (RESULT_QC_FAILED, RESULT_ASSETS_REJECTED, RESULT_RENDER_FAILED,
            RESULT_RENDER_BROKEN, RESULT_ABANDONED)
# CF-0305: the needs_you reason of the same tool failure twice in a row.
NEEDS_YOU_RENDER_BROKEN = "render_broken"
# CF-0518: the same failure twice in a row with frames drawn - the video runs
# into one asset. A stop of the tool, not of a cap: lifted by a fix.
NEEDS_YOU_STUCK_ON_ASSET = "render_stuck_on_asset"
TOOL_STOPS = (NEEDS_YOU_RENDER_BROKEN, NEEDS_YOU_STUCK_ON_ASSET)


class Capped(Exception):
    """Raised by begin() when the cap is reached; str() is the NEEDS-YOU line."""

    def __init__(self, slug, cap, last_failure, what="attempt cap", line=None):
        self.slug, self.cap, self.last_failure = slug, cap, last_failure
        self.what = what
        super().__init__(line or needs_you_line(slug, cap, last_failure, what))


def needs_you_line(slug, cap, last_failure, what="attempt cap"):
    return f"NEEDS-YOU {slug}: {what} {cap} reached - last failure: {last_failure}"


def ledger_needs_you_line(slug, ledger):
    """The NEEDS-YOU line for a ledger that carries `needs_you`, naming the
    cap that was actually reached (CF-0415: attempts or QC degradations)."""
    ny = ledger.get("needs_you") or {}
    if ny.get("reason") == NEEDS_YOU_RENDER_BROKEN:
        # CF-0305: the stop names the error, not a cap that was never reached.
        return (f"NEEDS-YOU {slug}: render_broken - the same failure twice in a row "
                f"before the first frame, not counted against the cap: "
                f"{ny.get('last_failure', 'unknown')}")
    if ny.get("reason") == NEEDS_YOU_STUCK_ON_ASSET:
        # CF-0518: the stop names the error and the asset; both renders counted.
        frames = " and ".join(str(f) for f in ny.get("frames_rendered") or []) or "?"
        asset = f" ({ny['asset']})" if ny.get("asset") else ""
        return (f"NEEDS-YOU {slug}: render_stuck_on_asset - the same render failure twice "
                f"in a row (after {frames} frame(s)), the video runs into the same "
                f"asset{asset}: {ny.get('last_failure', 'unknown')}")
    reason = ny.get("reason") or f"attempt cap {ledger.get('attempt_cap')} reached"
    return f"NEEDS-YOU {slug}: {reason} - last failure: {ny.get('last_failure', 'unknown')}"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- batch layout ----------------------------------------------------------

def batch_context(plan_path):
    """(batch_dir, slug) when `plan_path` lies at <batch>/work/<slug>/<file>,
    else None. A plan in a temp dir or handed in by path from anywhere else
    has no ledger and no log - the wrappers then behave as before CF-0098."""
    plan = Path(plan_path).resolve()
    work = plan.parent.parent
    if work.name != "work" or not plan.parent.is_dir():
        return None
    return work.parent, plan.parent.name


def project_root_for(batch_dir):
    """The repo root a batch belongs to (pipeline/<channel>/<batch> -> root),
    falling back to this agent's own repo root for a batch parked elsewhere
    (tests build one in a temp dir)."""
    batch_dir = Path(batch_dir).resolve()
    candidate = batch_dir.parent.parent
    if candidate.name == "pipeline":
        return candidate.parent
    return PROJECT_ROOT


def channel_of(batch_dir):
    return Path(batch_dir).resolve().parent.name


def ledger_path(batch_dir, slug):
    return Path(batch_dir) / "work" / slug / LEDGER_NAME


def log_path(batch_dir, slug, n):
    return Path(batch_dir) / LOGS_DIR / f"{slug}-attempt-{n}.log"


# --- cap -------------------------------------------------------------------

def load_cap(channel, root=None, key=CHANNEL_KEY, default=DEFAULT_MAX_ATTEMPTS):
    """(cap, source): channels/<channel>.json#<key> (by default
    video_editor.max_attempts_per_video), or (default, "default") when the
    file or the key is absent or not a positive integer."""
    root = Path(root) if root else PROJECT_ROOT
    if not channel:
        return default, "default"
    path = Path(channel) if str(channel).endswith(".json") else root / "channels" / f"{channel}.json"
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return default, "default"
    section, name = key.split(".")
    value = (cfg.get(section) or {}).get(name) if isinstance(cfg.get(section), dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default, "default"
    try:
        shown = path.relative_to(root)
    except ValueError:
        shown = path
    return value, f"{shown}#{key}"


def load_degrade_cap(channel, root=None):
    """CF-0415: (cap, source) for video_editor.max_qc_degrades_per_video,
    DEFAULT_MAX_QC_DEGRADES when the channel does not say."""
    return load_cap(channel, root, key=DEGRADE_CHANNEL_KEY, default=DEFAULT_MAX_QC_DEGRADES)


# --- ledger ----------------------------------------------------------------

def load(batch_dir, slug, cap=None, channel=None, degrade_cap=None):
    """The ledger for one video, created in memory (not on disk) if absent.
    `cap` / `degrade_cap` override the channel's numbers; `channel` overrides
    the batch dir's parent name. A ledger written before CF-0415 gets its
    degrade cap from the channel the first time it is loaded."""
    path = ledger_path(batch_dir, slug)
    ledger = None
    if path.exists():
        try:
            ledger = json.loads(path.read_text())
        except ValueError:
            ledger = None
    if not isinstance(ledger, dict):
        ledger = {"slug": slug, "attempts": [], "needs_you": None}
    ledger.setdefault("slug", slug)
    ledger.setdefault("attempts", [])
    ledger.setdefault("needs_you", None)
    if cap is not None:
        ledger["attempt_cap"], ledger["cap_source"] = int(cap), "override"
    elif "attempt_cap" not in ledger:
        ledger["attempt_cap"], ledger["cap_source"] = load_cap(
            channel or channel_of(batch_dir), project_root_for(batch_dir))
    if degrade_cap is not None:
        ledger["qc_degrade_cap"], ledger["qc_degrade_cap_source"] = int(degrade_cap), "override"
    elif "qc_degrade_cap" not in ledger:
        ledger["qc_degrade_cap"], ledger["qc_degrade_cap_source"] = load_degrade_cap(
            channel or channel_of(batch_dir), project_root_for(batch_dir))
    return ledger


def save(batch_dir, slug, ledger):
    path = ledger_path(batch_dir, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return path


def open_attempt(ledger):
    """The attempt begun and not yet ended, or None."""
    for a in reversed(ledger["attempts"]):
        if a.get("result") is None:
            return a
        break
    return None


def renders(ledger):
    """Every render the ledger records: everything but the `capped` marker
    begin() leaves behind. `n` is the next render's place in this list."""
    return [a for a in ledger["attempts"] if a.get("result") != RESULT_CAPPED]


def kind_of(attempt):
    """An entry written before CF-0415 has no `kind` and was an attempt."""
    return attempt.get("kind") or KIND_ATTEMPT


def is_counted(attempt):
    """CF-0305: `counted: false` is a render the tool broke before the first
    frame; an entry without the field (written before CF-0305) counted."""
    return attempt.get("counted", True) is not False


def counted(ledger):
    """Renders that count against the attempt cap: all of them but the
    `qc_degrade`s (CF-0415), which count against their own, and the
    `render_broken` ones (CF-0305), which count against nothing."""
    return [a for a in renders(ledger)
            if kind_of(a) != KIND_QC_DEGRADE and is_counted(a)]


def qc_degrades(ledger):
    """CF-0415: the renders that only applied QC's own hint."""
    return [a for a in renders(ledger) if kind_of(a) == KIND_QC_DEGRADE]


def qc_degrade_cap(ledger):
    try:
        return int(ledger.get("qc_degrade_cap") or DEFAULT_MAX_QC_DEGRADES)
    except (TypeError, ValueError):
        return DEFAULT_MAX_QC_DEGRADES


def _label(a):
    if kind_of(a) == KIND_QC_DEGRADE:
        return f"render {a['n']}, qc degrade"
    if not is_counted(a):
        return f"render {a['n']}, not counted"
    return f"attempt {a['n']}"


def last_failure_text(ledger):
    for a in reversed(renders(ledger)):
        if a.get("result") in FAILURES:
            detail = a.get("detail") or ""
            return f"{a['result']} ({_label(a)})" + (f": {detail}" if detail else "")
    for a in reversed(renders(ledger)):
        if a.get("result"):
            return f"{a['result']} ({_label(a)})"
    return "none recorded"


def pending_hint(ledger):
    """CF-0415: the degradations QC suggested after the last render, when
    that render ended `qc_failed` and named some - else []."""
    done = renders(ledger)
    if not done or done[-1].get("result") != RESULT_QC_FAILED:
        return []
    return list(done[-1].get("qc_hint") or [])


def degrades_used_up(ledger):
    return len(qc_degrades(ledger)) >= qc_degrade_cap(ledger)


def degrade_available(ledger):
    """A `qc_degrade` could still be begun: QC's last verdict named a
    degradation and the degrade cap has room."""
    return bool(pending_hint(ledger)) and not degrades_used_up(ledger)


def attempts_used_up(ledger):
    return len(counted(ledger)) >= int(ledger["attempt_cap"])


def exhausted(ledger):
    """Nothing more can be begun: `needs_you`, or the attempts are used up
    and no `qc_degrade` is open to the video either (CF-0415)."""
    return bool(ledger.get("needs_you")) or (
        attempts_used_up(ledger) and not degrade_available(ledger))


def _mark_needs_you(ledger, reason=None, kind=KIND_ATTEMPT):
    """`kind` names the cap that closed the road: the render `begin` refused,
    or, at `end`, the degrade cap when QC's hint stands and only that cap
    was out of room."""
    if ledger.get("needs_you"):
        return ledger["needs_you"]
    if kind == KIND_QC_DEGRADE:
        what = f"qc degrade cap {qc_degrade_cap(ledger)} reached"
    elif kind in TOOL_STOPS:
        what = kind
    else:
        what = f"attempt cap {int(ledger['attempt_cap'])} reached"
    ledger["needs_you"] = {
        "reason": what,
        "last_failure": last_failure_text(ledger),
        "attempts": len(counted(ledger)),
        "qc_degrades": len(qc_degrades(ledger)),
        "requested": reason,
        "at": _now(),
    }
    if kind in TOOL_STOPS:
        # CF-0305: what the stop is about, and what has to change to lift it.
        last = renders(ledger)[-1]
        ledger["needs_you"].update({
            "error": last.get("error"),
            "error_signature": last.get("error_signature"),
            "toolchain": last.get("toolchain"),
            "build_inputs": last.get("build_inputs"),
        })
    if kind == NEEDS_YOU_STUCK_ON_ASSET:
        # CF-0518: the two renders of the pair, how far each got, and the
        # asset the error line names.
        pair = renders(ledger)[-2:]
        ledger["needs_you"].update({
            "renders": [a.get("n") for a in pair],
            "frames_rendered": [a.get("frames_rendered") for a in pair],
            "asset": failing_asset(pair[-1].get("error")),
        })
    return ledger["needs_you"]


def _fixed_since(ledger, toolchain, build_inputs):
    """CF-0305: a `render_broken` stop is lifted when the code or the plan
    changed since the broken renders - the toolchain fingerprint or the
    plan's build_inputs digest differs from the one they ran with. CF-0518:
    so is a `render_stuck_on_asset` stop."""
    ny = ledger.get("needs_you") or {}
    if ny.get("reason") not in TOOL_STOPS:
        return False
    return bool((toolchain and toolchain != ny.get("toolchain"))
                or (build_inputs and build_inputs != ny.get("build_inputs")))


def _refused(ledger, kind):
    """The cap a `begin` of this kind runs into, or None when it may begin."""
    if ledger.get("needs_you"):
        if ledger["needs_you"].get("reason") in TOOL_STOPS and kind == KIND_ATTEMPT:
            return ledger["needs_you"]["reason"]
        return kind
    if kind == KIND_QC_DEGRADE:
        return kind if degrades_used_up(ledger) else None
    return kind if attempts_used_up(ledger) else None


def begin(batch_dir, slug, reason, cap=None, channel=None, degraded=None,
          kind=KIND_ATTEMPT, build_inputs=None, degrade_cap=None, toolchain=None):
    """Begin render n. Closes a still-open render as `abandoned` first (it
    was a render, it counts). `kind` says which ceiling it spends (CF-0415:
    `qc_degrade` only when classify() said so). Raises Capped - after
    writing `needs_you` and a `capped` marker into the ledger - when that
    ceiling is already reached. CF-0305: a `render_broken` stop refuses
    the same way until the toolchain (`toolchain`, default
    toolchain_fingerprint()) or the plan (`build_inputs`) changed; then it
    is moved to `lifted_needs_you[]` and the render begins."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    if toolchain is None:
        toolchain = toolchain_fingerprint()
    ledger = load(batch_dir, slug, cap=cap, channel=channel, degrade_cap=degrade_cap)
    if _fixed_since(ledger, toolchain, build_inputs):
        lifted = dict(ledger["needs_you"], lifted_at=_now(),
                      lifted_by={"toolchain": toolchain, "build_inputs": build_inputs})
        # The `capped` marker a refused begin left behind goes with the stop
        # it recorded: the render begun now takes its number.
        if ledger["attempts"] and ledger["attempts"][-1].get("result") == RESULT_CAPPED:
            lifted["refused_begin"] = ledger["attempts"].pop()
        ledger.setdefault("lifted_needs_you", []).append(lifted)
        ledger["needs_you"] = None
    stale = open_attempt(ledger)
    if stale is not None:
        stale["result"] = RESULT_ABANDONED
        stale["ended_at"] = _now()
        stale["detail"] = stale.get("detail") or "begun and never ended - closed by the next begin"
    refused = _refused(ledger, kind)
    if refused:
        _mark_needs_you(ledger, reason, kind=refused)
        # One marker, refreshed rather than repeated, so a fourth and a
        # fifth refused begin do not grow the list.
        marker = ledger["attempts"][-1] if ledger["attempts"] and \
            ledger["attempts"][-1].get("result") == RESULT_CAPPED else None
        if marker is None:
            marker = {"n": len(renders(ledger)) + 1, "started_at": _now()}
            ledger["attempts"].append(marker)
        marker.update({"reason": reason, "kind": kind, "result": RESULT_CAPPED,
                       "ended_at": _now(), "detail": ledger["needs_you"]["last_failure"]})
        save(batch_dir, slug, ledger)
        if ledger["needs_you"]["reason"] in TOOL_STOPS:
            raise Capped(slug, int(ledger["attempt_cap"]), ledger["needs_you"]["last_failure"],
                         ledger["needs_you"]["reason"], line=ledger_needs_you_line(slug, ledger))
        is_degrade = ledger["needs_you"]["reason"].startswith("qc degrade cap")
        raise Capped(slug,
                     qc_degrade_cap(ledger) if is_degrade else int(ledger["attempt_cap"]),
                     ledger["needs_you"]["last_failure"],
                     "qc degrade cap" if is_degrade else "attempt cap")
    n = len(renders(ledger)) + 1
    attempt = {
        "n": n,
        "started_at": _now(),
        "ended_at": None,
        "kind": kind,
        "counted": True,                 # CF-0305: false once it ends render_broken
        "reason": reason,
        "result": None,
        "detail": None,
        "failed_gates": [],
        "degraded": list(degraded or []),
        "qc_hint": [],
        "build_inputs": build_inputs,
        "toolchain": toolchain,
        "log": str(log_path(batch_dir, slug, n).resolve()),
    }
    ledger["attempts"].append(attempt)
    save(batch_dir, slug, ledger)
    return attempt, ledger


def end(batch_dir, slug, result, detail=None, log=None, failed_gates=None,
        cap=None, channel=None, qc_hint=None, error=None, frames=None,
        qc_frozen=None):
    """End the open attempt with `result`. Returns (attempt, ledger, capped):
    `capped` is True when this failure left nothing to begin - needs_you
    is written then and there, so the operator sees the stop without asking
    for a fourth begin. `qc_hint` (CF-0415) is what QC suggests degrading,
    as "idx:to" tags; while it stands and the degrade cap has room, a failure
    on the last attempt is not a stop. Without an open attempt (a re-run of
    qc on a finished video) nothing is recorded and attempt is None.

    CF-0305: `error` is the failure's own line (render_video.py: the first
    error line Remotion printed) and `frames` how many frames were drawn;
    both are recorded on a render failure, with the error's signature. A
    `render_broken` is `counted: false`, and the second one in a row with
    the same signature writes `needs_you` `render_broken` - `capped` then.
    CF-0518: a `render_failed` right after a render failure with the same
    signature writes `needs_you` `render_stuck_on_asset` - `capped` then,
    with attempts left or not; the pair keeps counting against the cap."""
    if result not in RESULTS:
        raise ValueError(f"unknown result {result!r}; one of {', '.join(RESULTS)}")
    ledger = load(batch_dir, slug, cap=cap, channel=channel)
    attempt = open_attempt(ledger)
    if attempt is None:
        return None, ledger, False
    attempt["result"] = result
    attempt["ended_at"] = _now()
    if detail:
        attempt["detail"] = str(detail)
    if log:
        attempt["log"] = str(Path(log).resolve())
    if failed_gates:
        attempt["failed_gates"] = list(failed_gates)
    attempt["qc_hint"] = list(qc_hint or []) if result == RESULT_QC_FAILED else []
    # CF-0549: where each hinted block stuck - the cut of a sequence block
    # build_render_plan.py's --degrade-block stills instead of the whole block.
    if result == RESULT_QC_FAILED and qc_frozen:
        attempt["qc_frozen"] = list(qc_frozen)
    if result in (RESULT_RENDER_FAILED, RESULT_RENDER_BROKEN):
        if error:
            attempt["error"] = str(error)
            attempt["error_signature"] = error_signature(error)
        if frames is not None:
            attempt["frames_rendered"] = int(frames)
    if result == RESULT_RENDER_BROKEN:
        attempt["counted"] = False
    stop = same_failure_stop(ledger, attempt)
    if stop:
        _mark_needs_you(ledger, kind=stop)
        save(batch_dir, slug, ledger)
        return attempt, ledger, True
    capped = result in FAILURES and exhausted(ledger)
    if capped:
        # The road closed on the degrade cap only when QC did name a
        # degradation and the attempts were already gone as well.
        _mark_needs_you(ledger, kind=KIND_QC_DEGRADE if pending_hint(ledger)
                        and degrades_used_up(ledger) else KIND_ATTEMPT)
    save(batch_dir, slug, ledger)
    return attempt, ledger, capped


def same_failure_stop(ledger, attempt):
    """The tool stop `attempt` (just ended) makes with the render before it,
    or None. CF-0305: two `render_broken` in a row with one signature ->
    `render_broken`. CF-0518: a `render_failed` after a `render_failed` or a
    `render_broken` with the same signature -> `render_stuck_on_asset` (and
    so is a `render_broken` after a `render_failed`: frames were drawn once).
    The render right before it only - a `qc_degrade`, a `qc_failed` or an
    `abandoned` render between the two breaks the pair."""
    result = attempt.get("result")
    sig = attempt.get("error_signature")
    if result not in (RESULT_RENDER_FAILED, RESULT_RENDER_BROKEN) or not sig:
        return None
    done = renders(ledger)
    if len(done) < 2 or done[-1] is not attempt:
        return None
    previous = done[-2]
    if (previous.get("result") not in (RESULT_RENDER_FAILED, RESULT_RENDER_BROKEN)
            or previous.get("error_signature") != sig):
        return None
    if result == RESULT_RENDER_BROKEN and previous.get("result") == RESULT_RENDER_BROKEN:
        return NEEDS_YOU_RENDER_BROKEN
    return NEEDS_YOU_STUCK_ON_ASSET


# CF-0518: the asset an error line names - a file:// URL, else an absolute
# path to a media file.
_ASSET_RES = (
    re.compile(r"file://(/[^\s\"'`)]+)"),
    re.compile(r"(/[^\s\"'`)]+\.(?:mp4|mov|m4v|webm|mkv|png|jpe?g|webp|gif|wav|mp3|m4a|aac))\b",
               re.I),
)


def failing_asset(error):
    """CF-0518: the path of the asset the error line names, or None."""
    for rx in _ASSET_RES:
        m = rx.search(str(error or ""))
        if m:
            return m.group(1)
    return None


def auto_reason(ledger, degraded=None, recut=None):
    """The reason for a new attempt, read off the ledger rather than typed by
    the operator: `first` for the first render, `degraded:<idx:to,...>` when
    the plan carries a fresh CF-0031 degradation, `recut:<block=shot,...>`
    when it carries a CF-0367 re-cut no earlier attempt was begun for,
    otherwise the previous attempt's failure, and `operator` for a re-render
    of a passing video."""
    degraded = list(degraded or [])
    previous = renders(ledger)
    if not previous:
        return "first"
    last = previous[-1]
    if degraded and degraded != list(last.get("degraded") or []):
        return "degraded:" + ",".join(degraded)
    if recut:
        reason = "recut:" + ",".join(recut)
        if all(a.get("reason") != reason for a in previous):
            return reason
    result = last.get("result")
    if result == RESULT_QC_FAILED:
        gates = last.get("failed_gates") or []
        return "qc_failed:" + (",".join(gates) if gates else "unspecified")
    if result in (RESULT_RENDER_FAILED, RESULT_RENDER_BROKEN, RESULT_ASSETS_REJECTED,
                  RESULT_ABANDONED):
        return result
    return "operator"


def classify(ledger, plan):
    """CF-0415: (kind, reason) for a render of `plan` about to begin.

    `qc_degrade` when the render's only change is QC's own suggestion - the
    three conditions in the module docstring: the previous render ended
    `qc_failed` with a `qc_hint`; the plan adds degradations, all of them
    from that hint, and takes none back; the plan was built from the same
    inputs (`build_inputs.digest`) as the previous render. Anything else is
    an `attempt`, named by auto_reason() as before - a re-resolve or a
    re-cut with a `--degrade-block` riding along included."""
    degraded = degraded_tags(plan)
    done = renders(ledger)
    hint = set(pending_hint(ledger))
    if done and hint:
        last = done[-1]
        before = set(last.get("degraded") or [])
        now = set(degraded)
        added = now - before
        digest = plan_digest(plan)
        if (added and added <= hint and before <= now and digest
                and digest == last.get("build_inputs")):
            return KIND_QC_DEGRADE, "qc_degrade:" + ",".join(
                t for t in degraded if t in added)
    return KIND_ATTEMPT, auto_reason(ledger, degraded, recut=recut_tags(plan))


# CF-0305: what changes between two runs of the same failure and is not the
# failure - taken out before two error lines are compared.
_NORMALISE = (
    # CF-0518: the frame a render died on and the progress count before it
    # move by a few frames between runs of one failure (0358Z: 507/508/509).
    (re.compile(r"\bframe\s+\d+", re.I), "frame <n>"),
    (re.compile(r"\bRendered\s+\d+/\d+"), "Rendered <n>/<m>"),
    # CF-0518: the batch's own work dir, so one asset failure reads the same
    # in every batch (the asset's own name under it stays). Before <tmp>: a
    # batch under a temp dir keeps the asset name too.
    (re.compile(r"(file://)?(?:/[^\s\"'`]*?/pipeline/[^/\s\"'`]+/[^/\s\"'`]+/work/[^/\s\"'`]+/"
                r"|/[^\s\"'`]*?/work/[^/\s\"'`]+/(?=clips/|frames/|assets/))"), r"\1<work>/"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<time>"),
    (re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\b"), "<time>"),
    (re.compile(r"\b\d+(\.\d+)?\s?(ms|s)\b"), "<dur>"),
    (re.compile(r"(\d+h\s*)?\d+m\s*\d+s\b"), "<dur>"),
    (re.compile(r"(/private)?/(var/folders|tmp|private/tmp)/[^\s\"'`]*"), "<tmp>"),
    (re.compile(r"render/jobs/[^/\s\"'`]+"), "render/jobs/<job>"),
    (re.compile(r"\bpid[\s=:]*\d+", re.I), "pid <pid>"),
    (re.compile(r"\b(localhost|127\.0\.0\.1):\d+"), r"\1:<port>"),
    (re.compile(r"\b[0-9a-f]{8,}\b"), "<hex>"),
)


def error_signature(text):
    """CF-0305: an error line with times, tmp/job paths, pids, ports and hex
    ids replaced by placeholders and whitespace collapsed - two runs of the
    same tool failure give the same signature. CF-0518: frame numbers and the
    batch's work dir (`<work>/`) as well."""
    text = str(text or "")
    for rx, sub in _NORMALISE:
        text = rx.sub(sub, text)
    return " ".join(text.split())[:300]


@functools.lru_cache(maxsize=1)
def toolchain_fingerprint():
    """CF-0305: what a fix to the render tool changes - the agent checkout's
    HEAD plus a digest of its uncommitted diff of scripts/ and render/ (a
    fix being tried before it is committed). None outside a git checkout."""
    try:
        head = subprocess.run(["git", "-C", str(AGENT_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        if head.returncode != 0:
            return None
        diff = subprocess.run(["git", "-C", str(AGENT_ROOT), "diff", "HEAD", "--",
                               "scripts", "render/src"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    tip = head.stdout.strip()[:12]
    if diff.returncode == 0 and diff.stdout:
        return f"{tip}+{hashlib.sha256(diff.stdout).hexdigest()[:8]}"
    return tip


def qc_hint_tags(frozen_indices):
    """CF-0415: the hint qc_render.py records for its `frozen` blocks - one
    "idx:still" per flagged block index, each once, in block order."""
    seen = []
    for i in frozen_indices or []:
        tag = f"{int(i)}:{QC_HINT_TARGET}"
        if tag not in seen:
            seen.append(tag)
    return sorted(seen, key=lambda t: int(t.split(":")[0]))


def qc_frozen_records(frozen):
    """CF-0549: qc_render.py's `frozen` records as the ledger keeps them -
    block index, the sequence cut that stuck (None for a one-picture block),
    and where and for how long the picture stuck."""
    return [{"index": int(s["index"]), "cut": s.get("cut"),
             "still_run_at": s.get("still_run_at"), "still_run": s.get("still_run")}
            for s in frozen or []]


# CF-0415: an input file bigger than this is fingerprinted by size and mtime
# rather than read - the digest is taken on every plan build, and the inputs
# that matter (storyboard, words, voice, script) are a few MB at most.
HASH_WHOLE_FILE_UNDER = 64 * 1024 * 1024
# Arguments that are not inputs: the plan's own path, and the flag whose
# change is exactly what the digest must not see.
BUILD_INPUT_EXCLUDED = ("output", "degrade_block")


def _file_fingerprint(path):
    st = path.stat()
    if st.st_size > HASH_WHOLE_FILE_UNDER:
        return f"size:{st.st_size}:mtime:{int(st.st_mtime)}"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _value_fingerprint(value):
    if isinstance(value, (list, tuple)):
        return [_value_fingerprint(v) for v in value]
    if isinstance(value, str) and value:
        try:
            path = Path(value)
            if path.is_file():
                return {"file": value, "content": _file_fingerprint(path)}
        except (OSError, ValueError):
            pass
    return value


def build_inputs(args):
    """CF-0415: build_render_plan.py's fingerprint of what it was built from,
    written to plan["build_inputs"]. `args` is vars() of its argparse
    namespace. Every argument but the plan's own path and `--degrade-block`
    goes in by value; an argument that names an existing file goes in by its
    content, so a re-resolve that rewrites the storyboard at the same path is
    a new digest."""
    inputs = {k: _value_fingerprint(v) for k, v in sorted(args.items())
              if k not in BUILD_INPUT_EXCLUDED}
    blob = json.dumps(inputs, sort_keys=True, default=str).encode()
    return {"digest": hashlib.sha256(blob).hexdigest()[:16],
            "excluded": list(BUILD_INPUT_EXCLUDED), "inputs": inputs}


def plan_digest(plan):
    """The plan's build_inputs digest, None for a plan built without one."""
    bi = plan.get("build_inputs") if isinstance(plan, dict) else None
    return bi.get("digest") if isinstance(bi, dict) else None


def recut_tags(plan):
    """plan["recut"]["excluded_candidates"] as "block=shot" tags (CF-0367)."""
    return [f"{e.get('block')}={e.get('shot')}"
            for e in ((plan.get("recut") or {}).get("excluded_candidates") or [])]


def degraded_tags(plan):
    """plan["degraded_blocks"] as the short "idx:to" tags the ledger stores."""
    return [f"{d.get('index')}:{d.get('to')}" for d in plan.get("degraded_blocks") or []]


def record_fields(ledger):
    """What write_batch_metadata.video_record() mirrors into 05-video-editor.json."""
    if not ledger:
        return {"attempts": [], "attempt_cap": None, "attempts_exhausted": False,
                "attempts_used": 0, "qc_degrade_cap": None, "qc_degrades_used": 0,
                "needs_you": None}
    return {
        "attempts": [
            dict({k: a.get(k) for k in ("n", "started_at", "ended_at", "reason", "result",
                                        "detail", "failed_gates", "degraded", "qc_hint",
                                        "build_inputs", "log")},
                 kind=kind_of(a), counted=is_counted(a),
                 **{k: a[k] for k in ("error", "error_signature", "frames_rendered")
                    if k in a})
            for a in ledger["attempts"]],
        "attempt_cap": ledger.get("attempt_cap"),
        "attempts_exhausted": exhausted(ledger),
        # CF-0415: the two ceilings apart - `attempts` above lists every
        # render; these say how many of them spent which cap.
        "attempts_used": len(counted(ledger)),
        "qc_degrade_cap": ledger.get("qc_degrade_cap"),
        "qc_degrades_used": len(qc_degrades(ledger)),
        "needs_you": ledger.get("needs_you"),
    }


def begun_line(attempt, ledger):
    """What `begin` prints: the render's number against the cap it spends."""
    if kind_of(attempt) == KIND_QC_DEGRADE:
        return (f"qc degrade {len(qc_degrades(ledger))}/{qc_degrade_cap(ledger)} "
                f"(render {attempt['n']}) begun ({attempt['reason']})")
    return (f"attempt {len(counted(ledger))}/{ledger['attempt_cap']} "
            f"begun ({attempt['reason']})")


# --- CLI -------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("begin", "end", "show"):
        s = sub.add_parser(name)
        s.add_argument("batch_dir")
        s.add_argument("slug")
        s.add_argument("--cap", type=int, default=None,
                       help=f"override {CHANNEL_KEY} (tests; default {DEFAULT_MAX_ATTEMPTS})")
        s.add_argument("--degrade-cap", type=int, default=None,
                       help=f"override {DEGRADE_CHANNEL_KEY} (tests; default "
                            f"{DEFAULT_MAX_QC_DEGRADES})")
        s.add_argument("--channel", default=None,
                       help="channel id or channels/*.json path (default: the batch dir's parent)")
        if name == "begin":
            s.add_argument("--reason", default=None)
            s.add_argument("--plan", default=None,
                           help="CF-0415: classify the render from the plan it renders "
                                "(qc_degrade or attempt, and the reason)")
        if name == "end":
            s.add_argument("--result", required=True, choices=RESULTS)
            s.add_argument("--detail", default=None)
            s.add_argument("--log", default=None)
            s.add_argument("--gate", action="append", default=[], dest="gates")
            s.add_argument("--qc-hint", action="append", default=[], dest="qc_hint",
                           help="CF-0415: a degradation QC suggests, as idx:to")
    args = p.parse_args(argv)
    if args.cmd == "begin" and not (args.reason or args.plan):
        p.error("begin needs --reason or --plan")
    runlog.annotate(video=args.slug, cmd=args.cmd)

    if args.cmd == "show":
        ledger = load(args.batch_dir, args.slug, cap=args.cap, channel=args.channel,
                      degrade_cap=args.degrade_cap)
        if ledger["attempts"]:
            runlog.annotate(attempt=ledger["attempts"][-1]["n"])
        json.dump(record_fields(ledger), sys.stdout, indent=2, ensure_ascii=False)
        print()
        if ledger.get("needs_you"):
            print(ledger_needs_you_line(args.slug, ledger), file=sys.stderr)
            return EXIT_CAPPED
        return 0

    if args.cmd == "begin":
        kind, degraded, inputs, reason = KIND_ATTEMPT, None, None, args.reason
        if args.plan:
            plan = json.loads(Path(args.plan).read_text())
            ledger = load(args.batch_dir, args.slug, cap=args.cap, channel=args.channel,
                          degrade_cap=args.degrade_cap)
            kind, auto = classify(ledger, plan)
            reason = args.reason or auto
            degraded, inputs = degraded_tags(plan), plan_digest(plan)
        try:
            attempt, ledger = begin(args.batch_dir, args.slug, reason,
                                    cap=args.cap, channel=args.channel, kind=kind,
                                    degraded=degraded, build_inputs=inputs,
                                    degrade_cap=args.degrade_cap)
        except Capped as c:
            print(str(c))
            return EXIT_CAPPED
        runlog.annotate(attempt=attempt["n"], attempt_kind=kind)
        print(f"{begun_line(attempt, ledger)} - log: {attempt['log']}")
        return 0

    attempt, ledger, capped = end(args.batch_dir, args.slug, args.result,
                                  detail=args.detail, log=args.log,
                                  failed_gates=args.gates, cap=args.cap,
                                  channel=args.channel, qc_hint=args.qc_hint)
    if attempt is None:
        print(f"no open attempt for {args.slug} - nothing recorded", file=sys.stderr)
        return 0
    runlog.annotate(attempt=attempt["n"])
    print(f"render {attempt['n']} ({kind_of(attempt)}) ended: {attempt['result']}")
    if capped:
        print(ledger_needs_you_line(args.slug, ledger))
        return EXIT_CAPPED
    return 0


@video_script("video-editor", "attempts", name="attempts.py", video_arg=2, batch_arg=1)
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
