#!/usr/bin/env python3
"""CF-0648: a picture `held_screen` (CF-0646) flags is re-cut before the
render, under its anchor's next candidate - automatically, the way the
operator did it by hand on `rebuilds/2026-10-09T1208Z`.

The rebuild's operator read each plan's `held_screen` findings and ran
`resolve_anchors.py --exclude-candidate BLOCK` (CF-0367) and the plan again,
at most twice per block: delver block 7 `wIM1PDRvKSE:55` -> `:22` -> `:21`
(clean), rink-rivals block 8 `ADi1iextoUM:4` -> `:2` (a strip again) ->
`cFP-IWif0wc:34`, mudform blocks 11 and 14. This module is that loop,
called by `build_render_plan.py` once its plan is written:

1. `wanted()` - every finding of the three rules (`score.thin_picture`,
   `score.held_cut_subject`, `score.held_soft_stretch`) on a picture the
   storyboard block shows as a shot of its own, whose anchor has had fewer
   than MAX_PER_ANCHOR such re-cuts (`by: held_screen` on the storyboard's
   `excluded_candidates`) and whose walk left a candidate unreached
   (`length_supply.not_reached`; a storyboard without the count is tried).
   A pool with nothing else to offer is a property of the pool, not a re-cut
   (rink-rivals 1824Z block 8: 19 offered, none long enough).
2. `run()` - snapshot the storyboard, the plan's files and the clips; run
   the storyboard's own resolve command (`resolve_call`, written by
   resolve_anchors.py) with `--exclude-candidate BLOCK=SHOT` for each and
   `--exclude-by held_screen`; build the plan again with this process's own
   command line, one round deeper (ENV_ROUND; at most MAX_ROUNDS).
3. The new plan is kept when it was built (exit 0) and scores higher than
   the one it replaces, or the same with fewer findings - the signed prices
   of the three rules are in the score, so a clean held frame that costs a
   similarity point is kept and a re-cut that only moved the defect is not.
   Otherwise everything is put back as it was and the plan says so
   (`held_recut.outcome: reverted`).

Nothing here measures a picture: the plan builder's `held_screen_gate` did,
and the re-cut plan is measured by the same gate.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TASK = "CF-0648"
FIELD = "held_recut"
BY = "held_screen"
RULES = ("score.thin_picture", "score.held_cut_subject", "score.held_soft_stretch")
MAX_PER_ANCHOR = 2   # the operator's ceiling on 2026-10-09
MAX_ROUNDS = 2       # re-cut rounds per plan build (each re-resolves once)
ENV_ROUND = "CF0648_HELD_RECUT_ROUND"
ENV_OFF = "CF0648_HELD_RECUT_OFF"
SNAP_DIR = ".held_recut"


def _shows(story_block):
    import resolve_anchors
    return resolve_anchors.block_shots(story_block or {})


def _picture_shot(plan_block, cut):
    if cut is None:
        return plan_block.get("shot")
    cuts = (plan_block.get("asset") or {}).get("cuts") or []
    return cuts[cut].get("shot") if 0 <= cut < len(cuts) else None


def done_for(story, word_index):
    """How many re-cuts of this module the anchor at `word_index` has had."""
    return sum(1 for e in story.get("excluded_candidates") or []
               if e.get("by") == BY and e.get("word_index") == word_index)


def alternatives(story_block):
    """None when unknown (no count on the record), else the number of the
    anchor's candidates the walk never reached."""
    ls = story_block.get("length_supply")
    if not isinstance(ls, dict) or "not_reached" not in ls:
        return None
    return int(ls.get("not_reached") or 0)


def wanted(plan, story, max_per_anchor=MAX_PER_ANCHOR):
    """`(todo, skipped)`: the pictures to re-cut - `{"block", "cut", "shot",
    "rules", "word_index"}` - and the flagged ones left as they are, each
    with `why`."""
    rec = plan.get("held_screen") or {}
    pblocks = plan.get("blocks") or []
    sblocks = story.get("blocks") or []
    todo, skipped = {}, []
    for f in rec.get("findings") or []:
        if f.get("rule") not in RULES:
            continue
        i, ci = f.get("block"), f.get("cut")
        if not isinstance(i, int) or not (0 <= i < len(pblocks)) or i >= len(sblocks):
            continue
        shot = _picture_shot(pblocks[i], ci)
        key = (i, shot)
        if key in todo:
            todo[key]["rules"].append(f["rule"])
            continue
        x = {"block": i, "cut": ci, "shot": shot, "rules": [f["rule"]]}
        sb = sblocks[i]
        wi = (sb.get("word_range") or [None])[0]
        if not shot or shot not in _shows(sb) or wi is None:
            skipped.append({**x, "why": "not a shot of the block's own pool "
                                        "(a card, an opening or an unfilled block)"})
            continue
        x["word_index"] = wi
        if done_for(story, wi) >= max_per_anchor:
            skipped.append({**x, "why": f"the anchor had its {max_per_anchor} "
                                        f"re-cuts ({TASK})"})
            continue
        if alternatives(sb) == 0:
            skipped.append({**x, "why": "the walk reached every candidate the "
                                        "pool offered - nothing else to cut"})
            continue
        todo[key] = x
    return list(todo.values()), skipped


def _score(plan):
    s = (plan or {}).get("score") or {}
    v = s.get("score")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _findings(plan):
    return len(((plan or {}).get("held_screen") or {}).get("findings") or [])


def better(new, old, new_exit):
    """Whether the re-cut plan `new` replaces `old`: built, and a higher
    score - or the same score with fewer held-screen findings."""
    if new_exit != 0 or not isinstance(new, dict):
        return False
    a, b = _score(new), _score(old)
    if a is None or b is None:
        return _findings(new) < _findings(old)
    return a > b or (a == b and _findings(new) < _findings(old))


def _clips_dir(call):
    argv = list(call.get("argv") or [])
    for i, a in enumerate(argv):
        if a == "--clips-dir" and i + 1 < len(argv):
            d = Path(argv[i + 1])
            return d if d.is_absolute() else Path(call.get("cwd") or ".") / d
        if a.startswith("--clips-dir="):
            d = Path(a.split("=", 1)[1])
            return d if d.is_absolute() else Path(call.get("cwd") or ".") / d
    return None


def names_storyboard(call, storyboard_path):
    """CF-0669: True when the call's command line names `storyboard_path` (its
    OUTPUT, resolved against the call's cwd). A storyboard copied into a
    rebuild (`pipeline/rebuilds/<ts>`, CF-0668) keeps the source batch's
    call, whose OUTPUT is the source's storyboard: run as written it would
    re-cut the published batch, not the rebuild."""
    target = Path(storyboard_path).resolve()
    cwd = Path(call.get("cwd") or ".")
    for a in call.get("argv") or []:
        q = Path(str(a))
        q = q if q.is_absolute() else cwd / q
        try:
            if q.resolve() == target:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def snapshot(files, clips, dest):
    """Copy `files` and the `clips` directory to `dest`."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    kept = []
    for f in dict.fromkeys(Path(x).resolve() for x in files):
        if f.exists():
            name = f"{len(kept):02d}-{f.name}"
            shutil.copy2(f, dest / name)
            kept.append([str(f), name])
    if clips and clips.is_dir():
        shutil.copytree(clips, dest / "clips")
    (dest / "manifest.json").write_text(json.dumps(
        {"files": kept, "clips": str(clips) if clips else None}))
    return dest


def restore(work, dest):
    """Put back what snapshot() took; files written since and not in the
    snapshot (a refusal sidecar of the re-cut plan) are removed."""
    man = json.loads((dest / "manifest.json").read_text())
    had = {orig for orig, _ in man["files"]}
    for f in _plan_files(work):
        if str(f.resolve()) not in had:
            f.unlink(missing_ok=True)
    for orig, name in man["files"]:
        shutil.copy2(dest / name, orig)
    clips = Path(man["clips"]) if man.get("clips") else None
    if clips and (dest / "clips").is_dir():
        if clips.exists():
            shutil.rmtree(clips)
        shutil.copytree(dest / "clips", clips)


def _plan_files(work):
    return sorted(set(Path(work).glob("plan*.json")) | set(Path(work).glob("storyboard*.json")))


def run(plan_path, storyboard_path, plan, story, argv=None, python=None,
        runner=None, env=None, log=None):
    """The loop's one round from this plan build - see the module doc.
    Returns the record (also written onto the plan file that stands at the
    end), or None when there was nothing to do. `runner(argv, cwd, env)` ->
    exit code runs a command (subprocess by default)."""
    env = dict(os.environ if env is None else env)
    log = log or (lambda m: print(f"  HELD RECUT: {m}", file=sys.stderr))
    if env.get(ENV_OFF):
        return None
    rnd = int(env.get(ENV_ROUND) or 0)
    call = story.get("resolve_call")
    todo, skipped = wanted(plan, story)
    if not todo:
        if skipped:
            log("; ".join(f"block {s['block']} {s['shot'] or ''} left: {s['why']}"
                          for s in skipped))
        return None
    rec = {"task": TASK, "round": rnd + 1, "asked": todo, "skipped": skipped}
    if rnd >= MAX_ROUNDS:
        rec.update(outcome="round_cap", why=f"{MAX_ROUNDS} re-cut rounds already "
                                            f"ran for this plan")
        return _stamp(plan_path, plan, rec, log)
    if not isinstance(call, dict) or not call.get("argv"):
        # an older storyboard: said, the plan left as it was written
        rec.update(outcome="no_resolve_call",
                   why="the storyboard does not say how it was resolved (an older "
                       "resolve) - re-cut by hand: resolve_anchors.py "
                       "--exclude-candidate (CF-0367)")
        log(f"{rec['outcome']} - {rec['why']}")
        return rec
    if not names_storyboard(call, storyboard_path):
        # CF-0669: a copied storyboard's call writes the source batch's
        rec.update(outcome="resolve_call_elsewhere",
                   why=f"the storyboard's resolve_call writes another storyboard "
                       f"(copied from another batch?) - re-resolve it here first "
                       f"(step 4 with this batch's paths), then build the plan")
        return _stamp(plan_path, plan, rec, log)
    runner = runner or _subprocess_runner
    work = Path(plan_path).parent
    clips = _clips_dir(call)
    snap = snapshot(_plan_files(work) + [Path(storyboard_path)], clips,
                    work / SNAP_DIR / f"round-{rnd + 1}")
    old = json.loads(json.dumps(plan))
    resolve = [call.get("python") or python or sys.executable, call["script"],
               *call["argv"]]
    for t in todo:
        resolve += ["--exclude-candidate", f"{t['block']}={t['shot']}"]
    resolve += ["--exclude-by", BY]
    log(f"round {rnd + 1}: re-cut " + ", ".join(
        f"block {t['block']} {t['shot']} ({', '.join(r.split('.')[-1] for r in t['rules'])})"
        for t in todo))
    code = runner(resolve, call.get("cwd") or None, env)
    if code != 0:
        restore(work, snap)
        rec.update(outcome="resolve_failed", exit=code)
        _drop(snap)
        return _stamp(plan_path, old, rec, log)
    child_env = dict(env, **{ENV_ROUND: str(rnd + 1)})
    me = list(argv if argv is not None else sys.argv)
    code = runner([python or sys.executable, *me], os.getcwd(), child_env)
    try:
        new = json.loads(Path(plan_path).read_text())
    except (OSError, ValueError):
        new = None
    if better(new, old, code):
        rec.update(outcome="kept", score=[_score(old), _score(new)],
                   findings=[_findings(old), _findings(new)])
        _drop(snap)
        log(f"round {rnd + 1} kept: score {_score(old)} -> {_score(new)}, "
            f"held-screen findings {_findings(old)} -> {_findings(new)}")
        # this round first, then the child's own (if it re-cut again)
        new[FIELD] = [rec] + list(new.get(FIELD) or [])
        Path(plan_path).write_text(json.dumps(new, indent=2))
        return rec
    restore(work, snap)
    _drop(snap)
    rec.update(outcome="reverted", exit=code,
               score=[_score(old), _score(new)],
               findings=[_findings(old), _findings(new)])
    return _stamp(plan_path, old, rec, log)


def _stamp(plan_path, plan, rec, log):
    plan[FIELD] = list(plan.get(FIELD) or []) + [rec]
    Path(plan_path).write_text(json.dumps(plan, indent=2))
    log(f"round {rec['round']}: {rec['outcome']}"
        + (f" - {rec['why']}" if rec.get("why") else "")
        + (f" (score {rec['score'][0]} -> {rec['score'][1]})" if rec.get("score") else ""))
    return rec


def _drop(snap):
    shutil.rmtree(snap, ignore_errors=True)
    parent = snap.parent
    try:
        parent.rmdir()
    except OSError:
        pass


# One resolve or one plan build (plan_check.py's step ceiling): 1.5-8 min on
# 1824Z / 1208Z; a wedged one is a failed round (put back), not a hung stage.
STEP_TIMEOUT_SECONDS = 1800


def _subprocess_runner(argv, cwd, env):
    try:
        return subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                              timeout=STEP_TIMEOUT_SECONDS).returncode
    except subprocess.TimeoutExpired:
        return 124
