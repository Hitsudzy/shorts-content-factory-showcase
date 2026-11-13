#!/usr/bin/env python3
"""CF-0322: a batch that got no script out of the Content Researcher closes
there - and the close is a fact a machine checks, not a line an operator reads.

The defect, from the grill of 2026-09-22 (Q3b). `example-film/2026-09-22T1001Z`
selected 6 topics, indexed 2 of them to the source floor and came out of the
Researcher with **0 scripts**; the wall was 4h57m. `2026-09-20T1610Z` drew the
same picture. After the Researcher a batch with no script has nothing left to
spend anything on: there is no video to build, and no number the next stage
could produce that the funnel of this batch does not already carry. Every
minute past that point is paid out of the same subscription ceiling the next
run needs.

Both those batches were in fact closed by hand, correctly, by an operator who
read the artifact and stopped. That is exactly the problem CF-0318 wrote down
on two `SKILL.md` files: a rule that lives in prose is executed by whoever
happens to be reading, and a rule the code does not hold is a rule that is not
held. So the stop-cock is not a sentence in the skill. It is:

* `verdict()` here - four states over the batch's own frozen artifacts;
* `runlog.marker()` - with the cock down, `runlog stage-start <anything>` is
  refused with exit 2, so the only marker a stopped batch can still write is
  `batch-done`;
* the record - `batch-done` carries `stopcock` in its event, the runs row
  carries `outcome`, and RUN_SUMMARY carries the line.

**The four states**, and why the middle one exists:

    not_reached   no `03-content-researcher.json`: the stage has not run, and
                  a stop-cock that fired here would be a stop-cock on a batch
                  that has not been given its chance.
    open          the Researcher wrote at least one script. Nothing to do.
    refill        no script, and the reserve still holds a topic this batch
                  may spend, or a substitute the loop already gave sources
                  that the Researcher has not written yet (CF-0805): the
                  CF-0306 loop (Indexer in reserve mode -> descriptions ->
                  Researcher again) is the next step, and the cock must not
                  come down in front of it or in the middle of it.
    stop          no script and nothing to substitute. The batch closes.

**A substitute already spent is still a refill** (CF-0805,
`example-tech/2026-10-19T0844Z`). The reserve Indexer of the CF-0306 loop moves
the topics it gives sources from `remaining[]` into `substitutions[]` with
`outcome: "sources"`; the Researcher has not written them yet. Reading
`remaining[]` alone, the cock was up in front of the reserve Indexer (it
started on `stopcock exits 0`) and came down behind it - the reserve
Researcher's `stage-start` was refused and the two substitutes the Indexer had
spent 54 minutes on were never written. So with 0 scripts a substitution
`outcome == "sources"` whose topic is in neither `03 -> scripts[]` nor
`skipped[]` is pending (`pending_substitutes`), and the state is `refill`. It
holds for every round of the loop (`at` = `researcher_refusal`, the late round,
`frame_judge_refusal`, `sieve`): the record says what was spent, not when -
only the Indexer's first pass before the Researcher (`index_pass`) is not a
refill. A re-run
from the scriptwriter (its `01b` is the parent's) and the previous run's block
a `rerun-from` left (CF-0781) carry no pending substitute - neither run
indexed it.

`refill` is the whole reason this module reads `01b-footage-index.json` at
all. Without it the stop-cock would fire between the Researcher's refusal and
the substitution README describes, and a batch that had a spare topic on the
shelf would be closed before it spent it - which is the opposite of what
CF-0306 was for.

**A re-run from the scriptwriter has no refill.** It copies `01`, `01b` and
`02` from its parent and writes only `03` (README, "When a batch is a re-run of
the one before it"): the footage is the parent's footage, and nothing in the
run indexes anything, so a reserve topic on the parent's shelf cannot be given
sources here. The mark is the one `tests/test_pipeline_contracts.py` already
reads - `01b` naming a batch other than this one - and `2026-09-20T1610Z` is
the case: its `02` holds an untouched reserve topic and its `01b` is
`2026-09-19T0116Z`'s file. So: `stop`, not `refill`.

**This is not `empty_batch_guard`** (`channels/<id>.json` ->
`fact_refusal.empty_batch_guard.min_scripts_after_refusal`, CF-0185). That
guard is a bound on a *refusal*: the production-fact rule may not be the thing
that takes a batch's last script away. It answers "may this rule fire?" before
the Researcher decides. The stop-cock answers "is there anything left to do?"
after the Researcher has decided, and it refuses no topic, no script and no
video - it only declines to spend the stages that follow on a batch with
nothing in it. The guard can leave a batch with one script and the stop-cock
stays up; the guard can be absent entirely and the stop-cock still works. They
never read the same number and neither can overrule the other.

**A stop is not an incident** (task item 2, for the triage of CF-0319, which
does not exist yet). A batch that closes here ran correctly and produced the
one thing it had to produce: the record of why there was no material. So the
runs row's `outcome` is `no_material`, a named, normal end - `OUTCOME_NORMAL`
below is the mark a later triage reads to tell it apart from a run that fell
over. What is worth a task is not one such batch: it is the same loss codes
coming back, which is why the record carries `losses` by code, in the funnel's
own vocabulary and never a second one.

CLI: `runlog stopcock [--batch DIR] [--json]`; exit 0 while the batch may go
on, 3 when the cock is down (so a script can branch on it), 2 on a bad call.
"""
import json
import sys
from pathlib import Path

# CF-0231 / tests/test_module_path_loading.py: our own directory first, then
# the neighbours by name - the one mechanism every module of shared/runlog/
# uses, so a loader outside this checkout gets the same modules a `runlog`
# subcommand does.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import funnel  # noqa: E402
import previous_run  # noqa: E402
import runlog  # noqa: E402

__all__ = ["NOT_REACHED", "OPEN", "REFILL", "STOP", "STATES", "STOPPED", "substitution_block",
           "OUTCOME_NO_MATERIAL", "OUTCOME_VIDEOS", "OUTCOME_NORMAL", "OUTCOMES",
           "RESEARCHER_FILE", "INDEX_FILE", "COMPLIANCE_FILE", "EVENT_KEY", "SUBSTITUTE_SOURCED",
           "BEFORE_RESEARCHER_ATS",
           "verdict", "stopped", "outcome_of", "headline", "render", "main"]

# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

NOT_REACHED = "not_reached"   # the Researcher has not run: nothing to judge yet
OPEN = "open"                 # at least one script: the batch goes on
REFILL = "refill"             # no script, but the reserve can still be spent (CF-0306),
                              # or a spent substitute is still to be written (CF-0805)
STOP = "stop"                 # no script and nothing to substitute: close the batch
STATES = (NOT_REACHED, OPEN, REFILL, STOP)

# The one state the marker check acts on. Spelled as a tuple so that a future
# state that also closes a batch is added in one place rather than in every
# `== STOP` in the tree.
STOPPED = (STOP,)

# What the runs row (`pipeline/runs.jsonl` -> `outcome`) says about how a batch
# ended. Read by the triage of CF-0319 when it is written; its whole job here is
# that "closed because there was no material" is a value of its own and can
# never be mistaken for a run that fell over.
OUTCOME_NO_MATERIAL = "no_material"   # the stop-cock closed it. Normal.
OUTCOME_VIDEOS = "videos"             # the batch delivered at least one ready video
# Both of the above are normal ends. Anything else leaves `outcome` null: this
# module does not own the vocabulary of failure and does not invent one.
OUTCOME_NORMAL = (OUTCOME_NO_MATERIAL, OUTCOME_VIDEOS)
OUTCOMES = OUTCOME_NORMAL

RESEARCHER_FILE = "03-content-researcher.json"
INDEX_FILE = "01b-footage-index.json"
COMPLIANCE_FILE = "02-compliance-checker.json"

# `01b -> reserve_substitution.substitutions[].outcome` of a substitute the
# reserve Indexer gave sources (`ingest_batch.substitute_reserve`): the slot is
# spent, the Researcher's turn is next (CF-0805).
SUBSTITUTE_SOURCED = "sources"
# The `at` of the Indexer's first pass (`ingest_batch.substitute_reserve`
# default), which substitutes *before* the Researcher's first pass: the
# Researcher was handed those topics already, so they are no refill. Every
# other `at` is what a reserve Researcher stage is handed (the run plan's
# `content-researcher-reserve*` -> `args.topics`): `researcher_refusal` (the
# first and the late round), `frame_judge_refusal` (the round after the judge)
# and `sieve` - `source_sieve.py` runs inside every reserve round too, over the
# new sources, so a `sieve` substitute may well be one the Researcher has not
# seen.
BEFORE_RESEARCHER_ATS = ("index_pass",)
# CF-0882: the mark on a `02 -> reserve[]` row the refill from below the
# shortlist admitted (shared/below_shortlist.py REFILL_MARK).
REFILL_MARK = "refill"
REFILL_TASK = "CF-0882"

# Where the record lands inside the `batch-done` marker event.
EVENT_KEY = "stopcock"


# ---------------------------------------------------------------------------
# the reserve: can this batch still spend one?
# ---------------------------------------------------------------------------

def _batch_id(A, batch_dir):
    """Which batch these artifacts belong to, by id. Read from
    `03-content-researcher.json` first - a re-run from the scriptwriter copies
    `01`, `01b` and `02` from its parent and writes only `03`, so `03` is the
    one artifact that always names *this* run - and from the directory second,
    for a batch whose `03` carries no id."""
    for name in (RESEARCHER_FILE, "05-video-editor.json"):
        d = A.get(name)
        if isinstance(d, dict):
            v = d.get("batch_id") or d.get("batch")
            if v:
                return Path(str(v)).name
    return Path(batch_dir).name if batch_dir is not None else None


def _own_index(A, batch_dir):
    """True when `01b-footage-index.json` is this batch's own file.

    A re-run from the scriptwriter copies it from its parent and indexes
    nothing, so no reserve topic can be given sources in it - the same mark
    `tests/test_pipeline_contracts.py` reads to decide whether the parent may
    answer for a topic. Unknown (no `batch` field on `01b`, or no id to compare
    it with) is read as "its own": the batches written before those fields
    existed are ordinary runs, and guessing `copied` for them would hand the
    stop-cock a reason to fire that the artifacts never gave it.

    Deliberately not read from the directory alone: `gate_price` replays this
    rule over artifacts with no batch dir at all, and a rule whose answer
    changes depending on whether the caller happened to pass a path is a rule
    that cannot be priced."""
    idx = A.get(INDEX_FILE)
    if not isinstance(idx, dict):
        return True
    named, mine = idx.get("batch"), _batch_id(A, batch_dir)
    if not named or not mine:
        return True
    return Path(str(named)).name == mine


def substitution_block(A, batch_dir):
    """`(01b -> reserve_substitution or None, why it was left unread or None)`.

    CF-0781: a batch re-run from the Researcher (`batch_control rerun-from`)
    keeps `01b` - it is the Indexer's file - with the block the run before's
    reserve loop wrote into it. The reset records the block's fingerprint
    (`previous_run`); a block that still matches it is not this run's answer
    and is read as absent. Needs the batch dir (the reset's row is in its
    `run-state.json`); without one the block is read as it is."""
    idx = A.get(INDEX_FILE)
    sub = idx.get(funnel.SUBSTITUTION_KEY) if isinstance(idx, dict) else None
    if sub is not None and batch_dir is not None and previous_run.is_previous_block(
            previous_run.read_state(batch_dir), INDEX_FILE, funnel.SUBSTITUTION_KEY, sub):
        return None, (f"{INDEX_FILE} -> {funnel.SUBSTITUTION_KEY} is the previous run's "
                      f"(before rerun-from), not read ({previous_run.TASK})")
    return sub, None


def _remaining_reserve(A, batch_dir):
    """([topic ids the batch may still substitute], why).

    `01b` -> `reserve_substitution.remaining[]` when the CF-0306 loop ran here:
    it is written by the loop itself and is the authoritative answer. Without
    the block the loop never ran, and the untouched reserve is what compliance
    put on the shelf (`02` -> `reserve[]`) minus whatever already has a pool in
    this batch's index.

    CF-0882: a topic the refill from below the shortlist admitted
    (`shared/below_shortlist.py`: a `02 -> reserve[]` row marked `refill`) is
    reserve too after the loop wrote `remaining[]` - the loop never saw it -
    until the loop answers it (a substitute's `topic_id` in `substitutions[]`)
    or it has a pool in this batch."""
    if not _own_index(A, batch_dir):
        return [], (f"{INDEX_FILE} is {Path(str((A.get(INDEX_FILE) or {}).get('batch'))).name}'s "
                    f"file - a re-run from the scriptwriter indexes nothing, so no reserve "
                    f"topic can be given sources here")
    idx = A.get(INDEX_FILE) or {}
    sub, unread = substitution_block(A, batch_dir)
    if isinstance(sub, dict) and sub.get("remaining") is not None:
        left = [_id(t) for t in sub.get("remaining") or []]
        left = [t for t in left if t]
        why = (f"{INDEX_FILE} -> {funnel.SUBSTITUTION_KEY}.remaining: "
               + (", ".join(left) if left else "empty"))
        used = {_id(r) for r in sub.get("substitutions") or [] if isinstance(r, dict)}
        used |= set(idx.get("sources_by_topic") or {})
        refill = [_id(r) for r in (A.get(COMPLIANCE_FILE) or {}).get("reserve") or []
                  if isinstance(r, dict) and r.get(REFILL_MARK)]
        refill = [t for t in refill if t and t not in used and t not in left]
        if refill:
            left = left + refill
            why += f"; admitted from below the shortlist ({REFILL_TASK}): " + ", ".join(refill)
        return left, why
    tail = f"; {unread}" if unread else ""
    c02 = A.get(COMPLIANCE_FILE) or {}
    shelf = [_id(t) for t in c02.get("reserve") or []]
    pooled = set(idx.get("sources_by_topic") or {})
    left = [t for t in shelf if t and t not in pooled]
    if not shelf:
        return [], f"{COMPLIANCE_FILE} put no topic in reserve{tail}"
    return left, ((f"{COMPLIANCE_FILE} -> reserve[] holds {', '.join(left)}, none of it indexed"
                   if left else
                   f"every topic of {COMPLIANCE_FILE} -> reserve[] already has a pool in this "
                   f"batch") + tail)


def _pending_substitutes(A, batch_dir, cr):
    """CF-0805: [topic ids the reserve loop gave sources the Researcher has not
    written yet] - `01b -> reserve_substitution.substitutions[]` with
    `outcome == "sources"`, less every topic `03` names in `scripts[]` or
    `skipped[]`. Any round of the loop counts; the Indexer's first pass
    (`BEFORE_RESEARCHER_ATS`) does not - it ran before the Researcher did.
    Empty for a `01b` that is not this batch's own (a re-run from the
    scriptwriter indexes nothing, and nothing in it will research a
    substitute) and for the previous run's block (CF-0781), both read through
    the same readers `_remaining_reserve` uses."""
    if not _own_index(A, batch_dir):
        return []
    sub, _ = substitution_block(A, batch_dir)
    if not isinstance(sub, dict):
        return []
    written = {_id(s) for key in ("scripts", "skipped")
               for s in (cr.get(key) or []) if s is not None}
    out = []
    for r in sub.get("substitutions") or []:
        if not isinstance(r, dict) or r.get("outcome") != SUBSTITUTE_SOURCED:
            continue
        if r.get("at") in BEFORE_RESEARCHER_ATS:
            continue
        t = _id(r)
        if t and t not in written and t not in out:
            out.append(t)
    return out


def _id(t):
    if isinstance(t, dict):
        return t.get("topic_id") or t.get("id")
    return t if isinstance(t, str) else None


# ---------------------------------------------------------------------------
# the ceiling nobody spent
# ---------------------------------------------------------------------------

def _window_left(events):
    """{window: {"used_pct", "left_pct", "at"}} from the batch's last `limits`
    reading, or None when the run has none.

    None rather than 100: the desktop sessions that drive the runs never call
    the statusline command, so most batches on disk carry no reading at all
    (CF-0108), and printing "100 % of the ceiling left" off an absent number
    would be exactly the manufactured measurement `funnel.py` exists to stop."""
    last = None
    for e in events or []:
        if e.get("kind") == getattr(runlog.sibling("limits"), "KIND_LIMITS", "limits"):
            last = e
    if last is None:
        return None
    out = {}
    params = last.get("params") or last
    for w in ("five_hour", "seven_day"):
        block = params.get(w)
        used = (block or {}).get("used_percentage")
        if used is None:
            continue
        out[w] = {"used_pct": used, "left_pct": round(100.0 - float(used), 1),
                  "at": last.get("ts")}
    return out or None


def _ceiling(f, events):
    """What the batch was aimed at and did not touch. `videos.left` is the
    target the channel set (`scope.target_ready_videos_per_batch`) against what
    the batch delivered - on a stopped batch that is the whole target."""
    target = f.get("target") if isinstance(f.get("target"), dict) else None
    # `funnel.target_of` calls it `ready` - the channel's
    # `scope.target_ready_videos_per_batch`. Read from there and never from the
    # config here: the funnel is the only code in the root allowed to read that
    # number, and a second reader would be a second opinion on it.
    want = (target or {}).get("ready")
    got = len(f.get("ready") or [])
    left = None if want is None else max(0, want - got)
    return {"videos": {"target": want, "delivered": got, "left": left},
            "window": _window_left(events)}


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------

def _selected(f):
    for s in f.get("steps") or []:
        if s["step"] == "selected":
            return s
    return None


def verdict(batch_dir=None, artifacts=None, events=None):
    """The stop-cock over one batch:

        {"batch", "state", "reason", "scripts", "refused", "reserve_remaining",
         "pending_substitutes", "topics", "losses", "ceiling"}

    Pure over the batch's frozen artifacts; `events` only fills
    `ceiling.window` and may be left out (gate_price replays this rule with
    artifacts alone). Never raises - an artifact that will not parse is already
    a line in `funnel.read_artifacts()`'s `_errors` and leaves the state
    `not_reached`, which stops nothing."""
    A = artifacts if artifacts is not None else funnel.read_artifacts(batch_dir)
    if events is None and batch_dir is not None:
        try:
            events = runlog.read_events(batch_dir)
        except Exception:                                   # noqa: BLE001
            events = None
    cr = A.get(RESEARCHER_FILE)
    f = funnel.funnel(artifacts=A)
    sel = _selected(f)
    out = {"batch": _name(batch_dir),
           "state": NOT_REACHED, "reason": f"no {RESEARCHER_FILE}: the Content Researcher "
                                          f"has not run for this batch",
           "scripts": None, "refused": [], "reserve_remaining": [],
           "pending_substitutes": [],
           "topics": sel["count"] if sel else None,
           "losses": dict(f.get("losses") or {}),
           "ceiling": _ceiling(f, events)}
    if not isinstance(cr, dict):
        return out
    scripts = [s for s in (cr.get("scripts") or []) if s is not None]
    out["scripts"] = len(scripts)
    out["refused"] = [{"topic": _id(s), "reason_code": (s or {}).get("reason_code")}
                      for s in cr.get("skipped") or []]
    if scripts:
        out["state"] = OPEN
        out["reason"] = (f"the Content Researcher wrote {len(scripts)} script(s): "
                         f"the batch has material and goes on")
        return out
    pending = _pending_substitutes(A, batch_dir, cr)
    out["pending_substitutes"] = pending
    if pending:
        out["reserve_remaining"], _ = _remaining_reserve(A, batch_dir)
        out["state"] = REFILL
        out["reason"] = (f"0 scripts, but {len(pending)} reserve substitute(s) already have "
                         f"sources and the Content Researcher has not written them yet "
                         f"({INDEX_FILE} -> {funnel.SUBSTITUTION_KEY}.substitutions[] outcome "
                         f"'{SUBSTITUTE_SOURCED}': {', '.join(pending)}): the CF-0306 refill "
                         f"runs before anything closes (CF-0805)")
        return out
    left, why = _remaining_reserve(A, batch_dir)
    out["reserve_remaining"] = left
    if left:
        out["state"] = REFILL
        out["reason"] = (f"0 scripts, but {len(left)} reserve topic(s) are still unspent "
                         f"({why}): the CF-0306 refill runs before anything closes")
        return out
    out["state"] = STOP
    out["reason"] = (f"0 scripts out of the Content Researcher and nothing to substitute "
                     f"({why}): there is no video left to build and no number the stages "
                     f"after it could add")
    return out


def stopped(batch_dir=None, artifacts=None, events=None, v=None):
    """True when the cock is down. The one predicate `runlog.marker()` asks."""
    return (v or verdict(batch_dir, artifacts, events))["state"] in STOPPED


def outcome_of(v):
    """The runs row's `outcome` for this verdict, or None when this module has
    nothing to say about how the batch ended (see OUTCOME_NORMAL)."""
    if not v:
        return None
    if v["state"] in STOPPED:
        return OUTCOME_NO_MATERIAL
    got = ((v.get("ceiling") or {}).get("videos") or {}).get("delivered") or 0
    return OUTCOME_VIDEOS if got else None


def _name(batch_dir):
    if batch_dir is None:
        return None
    p = Path(batch_dir)
    return f"{p.parent.name}/{p.name}"


# ---------------------------------------------------------------------------
# the text
# ---------------------------------------------------------------------------

def _codes(losses):
    return ", ".join(f"{c} {n}" for c, n in (losses or {}).items()) or "none recorded"


def headline(v):
    """One line for RUN_SUMMARY, beside the funnel's. Says nothing at all while
    the batch is running normally - a stop-cock that printed `up` under every
    healthy run would be noise in the one place a reader scans for trouble."""
    if not v or v["state"] in (NOT_REACHED, OPEN):
        return None
    if v["state"] == REFILL:
        pending = v.get("pending_substitutes") or []
        if pending:
            return (f"STOP-COCK: up - 0 scripts, {len(pending)} reserve substitute(s) with "
                    f"sources not yet written: {', '.join(pending)} (CF-0306 refill, CF-0805)")
        return (f"STOP-COCK: up - 0 scripts, {len(v['reserve_remaining'])} reserve topic(s) "
                f"left to spend (CF-0306 refill, CF-0322)")
    cl = v.get("ceiling") or {}
    left = (cl.get("videos") or {}).get("left")
    tail = f"; {left} of the batch's target untouched" if left else ""
    win = cl.get("window") or {}
    if win.get("five_hour"):
        tail += f", {win['five_hour']['left_pct']} % of the 5-hour window unspent"
    return (f"STOP-COCK: down - {v['topics'] if v['topics'] is not None else '?'} topics, "
            f"0 scripts, losses: {_codes(v['losses'])}{tail}. "
            f"Closed with no material, not an incident (CF-0322)")


def render(v, level="###"):
    """The lines for RUN_SUMMARY when the cock came down; [] otherwise - so a
    batch that ran normally gets no block at all rather than a row of zeroes."""
    if not v or v["state"] not in STOPPED:
        return []
    cl = (v.get("ceiling") or {})
    vids, win = cl.get("videos") or {}, cl.get("window")
    L = [f"{level} Стоп-кран (CF-0322)", "",
         f"- тем в батче: **{v['topics'] if v['topics'] is not None else '?'}**, "
         f"сценариев: **0**",
         f"- коды потерь: {_codes(v['losses'])}",
         f"- потолок ролика: цель {vids.get('target')}, сделано {vids.get('delivered')}, "
         f"не тронуто {vids.get('left')}"]
    if win:
        L.append("- окно подписки на момент закрытия: "
                 + "; ".join(f"{w} — использовано {d['used_pct']} %, свободно {d['left_pct']} %"
                             for w, d in sorted(win.items())))
    else:
        L.append("- окно подписки: в батче нет ни одного замера `limits` — сказать нечего")
    L += ["", f"Исход `{OUTCOME_NO_MATERIAL}`: батч отработал правильно и закрылся потому, "
              f"что материала не было. Это **не** авария. Задачу заводят не из одного такого "
              f"прогона, а из повторяемости кодов потерь выше.", ""]
    return L


# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog stopcock",
                                 description="is there anything left to do after the "
                                             "Content Researcher? (CF-0322)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None:
        sys.stderr.write("runlog: error: no batch directory (use --batch DIR)\n")
        return 2
    v = verdict(bdir)
    if ns.json:
        print(json.dumps(v, ensure_ascii=False, indent=2))
    else:
        print(f"{v['batch']}: {v['state']} - {v['reason']}")
        line = headline(v)
        if line:
            print(line)
    return 3 if v["state"] in STOPPED else 0


if __name__ == "__main__":
    sys.exit(main())
