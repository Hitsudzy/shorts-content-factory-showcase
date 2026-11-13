#!/usr/bin/env python3
"""CF-0881: mend the one or two blocks the frame judge refused a video for,
instead of losing the topic - re-pick, re-plan, re-render, re-check, re-pack.

The root's repair round (`shared/judge_repair.py`, task CF-0881) writes
`<batch>/work/repair-requests.json` (schema `judge-repair-request/1`): per
video refused for a defect in at most two blocks (a thin strip, a smeared or
cut subject, the wrong person, foreign text in the hook), the blocks of the
PLAN to mend - `target: shot` with the shot to exclude, or `target: meme`.
Its stage `judge-repair-editor` calls

    <agent python> scripts/repair_blocks.py <batch> \\
        --request <batch>/work/repair-requests.json \\
        --result  <batch>/work/repair-results.json

and this script answers every video of the request in the result (schema
`judge-repair-result/1`), one pass, never a second:

1. Snapshot: `work/<slug>/repair/before/` (the plan's files - plan*.json,
   storyboard*.json -, the clips, the judge's pack `frame-judge/`) and
   `work/<slug>/repair/before.mp4`. Every way the repair can end short of
   `rendered` puts all of it back, so the batch is exactly as the judge
   refused it (05 untouched, the mp4 the judge saw).
2. `target: shot` - the plan block is the storyboard block of the same index
   (build_render_plan.py builds one plan block per storyboard block), checked
   by its shots; the storyboard's own resolve command (`resolve_call`,
   CF-0648, as `held_recut.py` runs it) with `--exclude-candidate
   <block>=<shot>` per block and `--exclude-by judge_repair`. The resolve reads
   only the indexes the storyboard was built from: no YouTube search, no new
   source. `target: meme` - the refused meme (its asset id) is taken off the
   plan after the build, the footage under it stays; a meme that stands in for
   a hole (CF-0138 hole fill) has nothing under it - `no_replacement`.
3. The plan again, by the command the plan check ran (`plan_check.json`'s
   `plan` step, this checkout's interpreter and builder), else the same line
   rebuilt from 03; a meme-only repair edits the plan it has. Render
   (`render_video.py --reason judge_repair`: an attempt of the ledger like any
   other; the cap reached is `failed`) into `work/<slug>/repair/after.mp4`,
   QC (`qc_render.py --json`); a QC failure that is not only cosmetic
   (CF-0416) or a score under N is `qc_failed`. Only then the mp4 replaces
   the one at `output_path`.
4. The judge's pack again (`frame_judge_pack.py`) into `work/<slug>/frame-judge`
   (the old one is in the snapshot; no verdicts carried - the root composes
   them), and the row of 05 rewritten in place: `write_batch_metadata.py
   --repair` (the row carries `repair`, the retired-shot registry synced as on
   every write).

The result row: `outcome` (`rendered | no_replacement | render_failed |
qc_failed | failed`), `reason`, `changed_blocks` (every plan block whose
picture moved - the re-resolve may shift a neighbour), `replaced`
(`{block, entry, target, before, after}`), `output_path`, `qc_passed`.
Exit 0 when the result file is written (a video's failure is inside it), 2 on
a bad call or request. A time budget (`--budget-s`, under the root's 90 min)
leaves the videos it does not reach `failed`, with the sentence; the result
file is rewritten after every video, so a killed run still says what it did.
This script does not judge, does not touch `06-frame-judge.json`, adds no
video and runs no second pass.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197

TASK = "CF-0881"
BY = "judge_repair"
REQUEST_SCHEMA = "judge-repair-request/1"
RESULT_SCHEMA = "judge-repair-result/1"
EDITOR_FILE = "05-video-editor.json"
SCRIPTS_FILE = "03-content-researcher.json"
PACK_DIRNAME = "frame-judge"
REPAIR_DIRNAME = "repair"
TARGET_SHOT, TARGET_MEME = "shot", "meme"
RENDERED, NO_REPLACEMENT, RENDER_FAILED, QC_FAILED, FAILED = (
    "rendered", "no_replacement", "render_failed", "qc_failed", "failed")
OUTCOMES = (RENDERED, NO_REPLACEMENT, RENDER_FAILED, QC_FAILED, FAILED)
EXIT_OK, EXIT_BAD_CALL = 0, 2
RENDER_EXIT_CAPPED, RENDER_EXIT_SCORE_F = 3, 4     # render_video.py
MEME_OUTCOME_WITHDRAWN = "no_asset"                # meme_layer's closed list
# The root's ceiling is 90 min (judge_repair.EDITOR_TIMEOUT_S); a video is
# not started past this budget.
DEFAULT_BUDGET_S = 75 * 60
STEP_TIMEOUT_S = 1800          # one resolve / plan build (held_recut's ceiling)
RENDER_TIMEOUT_S = 2400
QC_TIMEOUT_S = 1800
PACK_TIMEOUT_S = 900
METADATA_TIMEOUT_S = 1800


class BadCall(Exception):
    """The call or the request cannot be answered at all (exit 2)."""


class Stop(Exception):
    """One video's repair ends short of `rendered`: (outcome, reason)."""

    def __init__(self, outcome, reason):
        super().__init__(reason)
        self.outcome, self.reason = outcome, reason


def _now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _rows(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def block_shots(block):
    """Every shot a plan or storyboard block puts on screen (the retired-shot
    registry's reading: own shot, cuts, swing chain, both sides)."""
    import retired_shots  # noqa: PLC0415 - rhythm comes with it
    return retired_shots.block_shots(block or {})


# --------------------------------------------------------------------------
# the request


def load_request(path):
    req = _read(path)
    if req is None:
        raise BadCall(f"no readable request at {path}")
    if req.get("schema") != REQUEST_SCHEMA:
        raise BadCall(f"{path}: schema {req.get('schema')!r}, expected {REQUEST_SCHEMA!r}")
    if not isinstance(req.get("videos"), list):
        raise BadCall(f"{path}: no videos[]")
    for v in req["videos"]:
        if not isinstance(v, dict) or not v.get("script_id") or not v.get("slug"):
            raise BadCall(f"{path}: a video without script_id/slug: {v!r}")
        if not isinstance(v.get("blocks"), list) or not v["blocks"]:
            raise BadCall(f"{path}: {v['script_id']} names no block")
        for b in v["blocks"]:
            if not isinstance(b, dict) or not isinstance(b.get("block"), int) \
                    or b.get("target") not in (TARGET_SHOT, TARGET_MEME):
                raise BadCall(f"{path}: {v['script_id']}: a block that is not "
                              f"{{block: int, target: shot|meme}}: {b!r}")
            if b["target"] == TARGET_SHOT and not b.get("exclude_shot"):
                raise BadCall(f"{path}: {v['script_id']} block {b['block']}: target shot "
                              f"with no exclude_shot")
    return req


def result_row(v, outcome, reason=None, **extra):
    row = {"script_id": v["script_id"], "slug": v["slug"], "outcome": outcome,
           "reason": reason, "changed_blocks": [], "replaced": [],
           "output_path": None, "qc_passed": None}
    row.update(extra)
    return row


# --------------------------------------------------------------------------
# snapshot / restore


def _plan_files(work):
    return sorted(set(Path(work).glob("plan*.json")) | set(Path(work).glob("storyboard*.json")))


def snapshot(work, clips, mp4):
    """Copy the plan's files, the clips, the pack and the mp4 under
    `work/repair/`. Returns the snapshot directory."""
    rdir = Path(work) / REPAIR_DIRNAME
    before = rdir / "before"
    if before.exists():
        shutil.rmtree(before)
    before.mkdir(parents=True)
    files = []
    for f in _plan_files(work):
        shutil.copy2(f, before / f.name)
        files.append(f.name)
    pack = Path(work) / PACK_DIRNAME
    if pack.is_dir():
        shutil.copytree(pack, before / PACK_DIRNAME)
    if clips and Path(clips).is_dir():
        shutil.copytree(clips, before / "clips")
    if mp4 and Path(mp4).is_file():
        shutil.copy2(mp4, rdir / "before.mp4")
    _write_json(before / "manifest.json", {
        "task": TASK, "at": _now_z(), "files": files,
        "clips": str(clips) if clips else None, "mp4": str(mp4) if mp4 else None,
        "pack": pack.is_dir()})
    return before


def restore(work, before):
    """Put back what snapshot() took; plan files written since and not in it
    (a refusal sidecar of the new plan, a score refusal) are removed."""
    work, before = Path(work), Path(before)
    man = _read(before / "manifest.json") or {}
    had = set(man.get("files") or [])
    for f in _plan_files(work):
        if f.name not in had:
            f.unlink(missing_ok=True)
    for name in had:
        shutil.copy2(before / name, work / name)
    pack = work / PACK_DIRNAME
    if man.get("pack") and (before / PACK_DIRNAME).is_dir():
        if pack.exists():
            shutil.rmtree(pack)
        shutil.copytree(before / PACK_DIRNAME, pack)
    clips = Path(man["clips"]) if man.get("clips") else None
    if clips and (before / "clips").is_dir():
        if clips.exists():
            shutil.rmtree(clips)
        shutil.copytree(before / "clips", clips)
    mp4 = Path(man["mp4"]) if man.get("mp4") else None
    saved = before.parent / "before.mp4"
    if mp4 and saved.is_file():
        shutil.copy2(saved, mp4)
    after = before.parent / "after.mp4"
    after.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# what changes


def story_index(story_blocks, i, shot):
    """The storyboard block showing plan block `i`'s `shot`: block `i` itself
    when it shows it (one plan block per storyboard block), else the nearest
    block that does; None when none does."""
    if 0 <= i < len(story_blocks) and shot in block_shots(story_blocks[i]):
        return i
    hits = [j for j, b in enumerate(story_blocks) if shot in block_shots(b)]
    return min(hits, key=lambda j: abs(j - i)) if hits else None


def _r(x):
    return round(float(x), 2) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def picture_sig(block):
    """What a viewer sees of one plan block: its span, its shots, its asset,
    the insert over it."""
    b = block or {}
    asset = b.get("asset") if isinstance(b.get("asset"), dict) else {}
    ins = b.get("insert") if isinstance(b.get("insert"), dict) else {}
    return json.dumps({
        "span": [_r(b.get("start")), _r(b.get("end"))],
        "shots": block_shots(b),
        "kind": asset.get("kind"), "src": asset.get("src"),
        "cut_at": _r(b.get("cut_at")),
        "insert": [ins.get("kind"), ins.get("asset_id") or ins.get("proof_id"),
                   ins.get("render_src") or ins.get("capture_path")] if ins else None,
    }, sort_keys=True, default=str)


def changed_blocks(old_plan, new_plan, also=()):
    """Every plan block index whose picture differs between the two plans
    (a block present in only one of them included), plus `also`."""
    a = (old_plan or {}).get("blocks") or []
    b = (new_plan or {}).get("blocks") or []
    out = {i for i in range(max(len(a), len(b)))
           if i >= len(a) or i >= len(b) or picture_sig(a[i]) != picture_sig(b[i])}
    return sorted(out | {i for i in also if isinstance(i, int)})


def meme_of(block):
    ins = (block or {}).get("insert")
    return ins if isinstance(ins, dict) and ins.get("kind") == "meme" else None


def hole_filled(plan, i):
    """Plan block `i`'s meme stands in for a hole (CF-0138): nothing under it."""
    hf = ((plan or {}).get("meme") or {}).get("hole_fill") or {}
    return any(isinstance(r, dict) and r.get("block_index") == i for r in hf.get("filled") or [])


def withdraw_memes(plan, asset_ids, why):
    """Take every meme insert whose asset is in `asset_ids` off the plan, in
    place, and say so in the meme record (`meme_delivered` answered
    `no_asset` with the reason, provenance dropped). Returns the block
    indices it was taken off."""
    gone = []
    for i, b in enumerate(plan.get("blocks") or []):
        m = meme_of(b)
        if m and m.get("asset_id") in asset_ids:
            del b["insert"]
            gone.append(i)
    meme = plan.get("meme") if isinstance(plan.get("meme"), dict) else None
    if meme is not None and gone:
        for d in meme.get("meme_delivered") or []:
            if isinstance(d, dict) and d.get("asset_id") in asset_ids \
                    and d.get("block_index") in gone:
                d.update(outcome=MEME_OUTCOME_WITHDRAWN, reason=why, withdrawn_by=BY)
        meme["inserts"] = [x for x in meme.get("inserts") or []
                           if not (isinstance(x, dict) and x.get("id") in asset_ids
                                   and x.get("block") in gone)]
        hf = meme.get("hole_fill")
        if isinstance(hf, dict) and isinstance(hf.get("filled"), list):
            hf["filled"] = [x for x in hf["filled"]
                            if not (isinstance(x, dict) and x.get("block_index") in gone)]
    if gone:
        plan.setdefault("judge_repair", {}).setdefault("memes_withdrawn", []).append(
            {"task": TASK, "assets": sorted(asset_ids), "blocks": gone, "why": why})
    return gone


# --------------------------------------------------------------------------
# the commands


def _clips_dir(call, work):
    import held_recut  # noqa: PLC0415
    d = held_recut._clips_dir(call) if isinstance(call, dict) else None
    return d or Path(work) / "clips"


def plan_argv(batch, work, script_id, channel, python):
    """The plan build's command line: the plan check's own `plan` step (its
    builder and interpreter swapped for this checkout's), when it wrote this
    work dir's plan; else the same line rebuilt from 03 (plan_check.check's)."""
    import plan_check  # noqa: PLC0415
    work = Path(work)
    plan = work / "plan.json"
    builder = str(HERE / "build_render_plan.py")
    pc = _read(work / plan_check.VERDICT) or {}
    for s in reversed(_rows(pc, "steps")):
        argv = [str(a) for a in s.get("argv") or []]
        if s.get("step") == "plan" and len(argv) > 5:
            try:
                same = Path(argv[5]).resolve() == plan.resolve()
            except (OSError, RuntimeError):
                same = False
            if same:
                return [python, builder, *argv[2:]]
            break
    doc, script = plan_check.load_script(batch, script_id)
    channel = resolve_channel(channel or doc.get("channel"))
    if not channel:
        raise Stop(FAILED, "no channel to build the plan for (no plan check, none in 03)")
    argv = [python, builder, work / "storyboard.json", work / "words.json",
            work / "voice.wav", plan, "--channel", channel,
            "--script", Path(batch) / SCRIPTS_FILE, "--script-id", script_id]
    est = plan_check.estimated_seconds(script)
    if est is not None:
        argv += ["--estimated-seconds", str(est)]
    for ix in plan_check.default_indexes(script):
        argv += ["--index", ix]
    return [str(a) for a in argv]


def _subprocess_runner(argv, cwd=None, env=None, timeout=None):
    """(exit code, stdout). A timeout is exit 124."""
    try:
        p = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, text=True)
        return p.returncode, p.stdout or ""
    except subprocess.TimeoutExpired:
        return 124, ""


def _qc_ok(result, channel):
    """(judge takes it, why not). QC passed, or failed only on the channel's
    cosmetic rules (CF-0416)."""
    if not isinstance(result, dict):
        return False, "QC printed no verdict"
    if result.get("passed") is True:
        return True, None
    import qc_cosmetic  # noqa: PLC0415
    if qc_cosmetic.admitted_despite(result, qc_cosmetic.load(channel)):
        return True, None
    fails = result.get("failures") or []
    return False, "QC failed: " + ("; ".join(str(f) for f in fails[:3]) or "no failure named")


def _score_stops(plan_path):
    import score_log  # noqa: PLC0415
    block = score_log.current(plan_path)
    if block is not None and score_log.stops(block):
        return block.get("line") or "under N"
    return None


def _cap_reached(batch, slug, channel):
    import attempts  # noqa: PLC0415
    ledger = attempts.load(batch, slug, channel=channel)
    if ledger.get("needs_you"):
        return f"the video's ledger says NEEDS-YOU ({str(ledger['needs_you'])[:120]})"
    if attempts.attempts_used_up(ledger):
        return (f"the attempt cap is reached ({len(attempts.counted(ledger))}/"
                f"{ledger['attempt_cap']}) - no render left for a repair")
    return None


# --------------------------------------------------------------------------
# one video


def repair_video(batch, v, python=None, runner=None, env=None, log=None):
    """The result row for one requested video (see the module doc)."""
    batch = Path(batch)
    python = python or sys.executable
    runner = runner or _subprocess_runner
    log = log or (lambda m: print(f"REPAIR: {v['slug']}: {m}", file=sys.stderr))
    env = dict(os.environ if env is None else env)
    sid, slug = v["script_id"], v["slug"]
    work = batch / "work" / slug
    plan_path, story_path = work / "plan.json", work / "storyboard.json"
    ve = _read(batch / EDITOR_FILE) or {}
    row = next((r for r in _rows(ve, "videos") if r.get("script_id") == sid), None)
    if row is None:
        return result_row(v, FAILED, f"{EDITOR_FILE} holds no videos[] row for {sid}")
    mp4 = Path(row.get("output_path") or batch / "videos" / f"{slug}.mp4")
    old_plan, story = _read(plan_path), _read(story_path)
    if old_plan is None:
        return result_row(v, FAILED, f"no readable plan at {plan_path}")
    channel = resolve_channel(ve.get("channel"))
    blocks = v["blocks"]
    shot_targets = [b for b in blocks if b["target"] == TARGET_SHOT]
    meme_targets = [b for b in blocks if b["target"] == TARGET_MEME]
    pblocks = old_plan.get("blocks") or []

    # what is asked, read before anything is touched
    excl, memes = [], set()
    for b in shot_targets:
        if story is None:
            return result_row(v, FAILED, f"no readable storyboard at {story_path} - "
                                         f"a shot cannot be re-picked without it")
        j = story_index(story.get("blocks") or [], b["block"], b["exclude_shot"])
        if j is None:
            return result_row(v, FAILED, f"block {b['block']}: no storyboard block shows "
                                         f"{b['exclude_shot']} - nothing to exclude it from")
        excl.append(f"{j}={b['exclude_shot']}")
    for b in meme_targets:
        i = b["block"]
        m = meme_of(pblocks[i]) if 0 <= i < len(pblocks) else None
        if m is None:
            return result_row(v, FAILED, f"block {i}: the plan shows no meme there")
        if hole_filled(old_plan, i):
            return result_row(v, NO_REPLACEMENT, (
                f"block {i}: the meme {m.get('asset_id')} stands in for a hole (CF-0138) - "
                f"there is no footage under it to show instead"))
        memes.add(m.get("asset_id"))
    call = (story or {}).get("resolve_call")
    if excl:
        import held_recut  # noqa: PLC0415
        if not isinstance(call, dict) or not call.get("argv"):
            return result_row(v, FAILED, "the storyboard does not say how it was resolved "
                                         "(no resolve_call, CF-0648) - re-pick by hand")
        if not held_recut.names_storyboard(call, story_path):
            return result_row(v, FAILED, "the storyboard's resolve_call writes another "
                                         "storyboard (copied from another batch, CF-0669)")
    why = _cap_reached(batch, slug, channel)
    if why:
        return result_row(v, FAILED, why)

    clips = (_clips_dir(call, work) if excl else None)
    before = snapshot(work, clips, mp4)
    after_mp4 = work / REPAIR_DIRNAME / "after.mp4"
    try:
        new_plan = _rebuild(batch, work, v, excl, memes, call, python, runner, env, channel, log)
        replaced = []
        npb = new_plan.get("blocks") or []
        for b in shot_targets:
            i = b["block"]
            shots = block_shots(npb[i]) if 0 <= i < len(npb) else []
            if b["exclude_shot"] in shots:
                raise Stop(NO_REPLACEMENT, f"block {i} still shows {b['exclude_shot']} "
                                           f"after the re-pick")
            replaced.append({"block": i, "entry": b.get("entry"), "target": TARGET_SHOT,
                             "before": b["exclude_shot"], "after": shots[0] if shots else None})
        for b in meme_targets:
            m = meme_of(pblocks[b["block"]])
            replaced.append({"block": b["block"], "entry": b.get("entry"),
                             "target": TARGET_MEME, "before": m.get("asset_id"), "after": None})
        changed = changed_blocks(old_plan, new_plan, also=[b["block"] for b in blocks])

        # render, QC - into repair/after.mp4, the judged mp4 untouched until it passes
        code, _ = runner([python, HERE / "render_video.py", plan_path, after_mp4,
                          "--reason", BY], None, env, RENDER_TIMEOUT_S)
        if code == RENDER_EXIT_CAPPED:
            raise Stop(FAILED, "render_video.py: the attempt cap (or NEEDS-YOU) - not rendered")
        if code == RENDER_EXIT_SCORE_F:
            raise Stop(NO_REPLACEMENT, f"the re-picked plan scores under N "
                                       f"({_score_stops(plan_path) or 'SCORE F'}) - not rendered")
        if code != 0 or not after_mp4.is_file() or after_mp4.stat().st_size == 0:
            raise Stop(RENDER_FAILED, f"render_video.py exit {code}"
                       + ("" if after_mp4.is_file() else ", no file"))
        code, out = runner([python, HERE / "qc_render.py", after_mp4, plan_path, "--json"],
                           None, env, QC_TIMEOUT_S)
        try:
            qc = json.loads(out) if out.strip() else None
        except ValueError:
            qc = None
        ok, why = _qc_ok(qc, channel)
        if not ok:
            raise Stop(QC_FAILED, why if qc is not None else f"qc_render.py exit {code}, {why}")
        stop = _score_stops(plan_path)
        if stop:
            raise Stop(QC_FAILED, f"the score after QC is under N: {stop}")
        mp4.parent.mkdir(parents=True, exist_ok=True)
        os.replace(after_mp4, mp4)

        # the judge's pack anew, then the 05 row
        pack = work / PACK_DIRNAME
        if pack.exists():
            shutil.rmtree(pack)
        code, _ = runner([python, HERE / "frame_judge_pack.py", mp4, plan_path,
                          "--out", pack], None, env, PACK_TIMEOUT_S)
        if code != 0 or not (pack / "manifest.json").is_file():
            raise Stop(FAILED, f"frame_judge_pack.py exit {code} - no pack for the judge")
        rec = {"task": TASK, "at": _now_z(), "blocks": blocks, "replaced": replaced,
               "changed_blocks": changed, "snapshot": str(before)}
        _write_json(work / REPAIR_DIRNAME / "record.json", rec)
        code, _ = runner([python, HERE / "write_batch_metadata.py", batch, "--repair",
                          "--video", sid, plan_path, mp4], None, env, METADATA_TIMEOUT_S)
        if code != 0:
            raise Stop(FAILED, f"write_batch_metadata.py --repair exit {code} - 05 not rewritten")
    except Stop as s:
        restore(work, before)
        log(f"{s.outcome} - {s.reason} (put back as the judge refused it)")
        return result_row(v, s.outcome, s.reason)
    except Exception as e:                                      # noqa: BLE001
        restore(work, before)
        log(f"failed - {type(e).__name__}: {e} (put back)")
        return result_row(v, FAILED, f"{type(e).__name__}: {e}")
    log(f"rendered - blocks {changed} changed, "
        + ", ".join(f"block {r['block']} {r['before']} -> {r['after']}" for r in replaced))
    return result_row(v, RENDERED, None, changed_blocks=changed, replaced=replaced,
                      output_path=str(mp4.resolve()),
                      qc_passed=bool(qc.get("passed")))


def _rebuild(batch, work, v, excl, memes, call, python, runner, env, channel, log):
    """Re-resolve (shot targets) and re-plan; take the refused memes off.
    Returns the new plan (written at work/plan.json)."""
    plan_path = Path(work) / "plan.json"
    if excl:
        argv = [python, HERE / "resolve_anchors.py", *call["argv"]]
        for e in excl:
            argv += ["--exclude-candidate", e]
        argv += ["--exclude-by", BY]
        cwd = call.get("cwd") if call.get("cwd") and Path(call["cwd"]).is_dir() else None
        log("re-pick " + ", ".join(excl))
        code, _ = runner(argv, cwd, env, STEP_TIMEOUT_S)
        if code != 0:
            raise Stop(NO_REPLACEMENT, f"resolve_anchors.py exit {code} - no other "
                                       f"candidate for {', '.join(excl)} in the topic's pool")
        code, _ = runner(plan_argv(batch, work, v["script_id"], channel, python),
                         None, env, STEP_TIMEOUT_S)
        if code != 0:
            side = Path(work) / "plan.refusal.json"
            why = (_read(side) or {}).get("reason") if side.exists() else None
            raise Stop(NO_REPLACEMENT if side.exists() else FAILED,
                       f"build_render_plan.py exit {code}"
                       + (f" - the plan refused: {str(why)[:300]}" if why else ""))
    plan = _read(plan_path)
    if plan is None:
        raise Stop(FAILED, f"no readable plan at {plan_path} after the build")
    if memes:
        why = (f"the frame judge refused this meme ({', '.join(sorted(memes))}) - "
               f"taken off by the repair ({TASK})")
        gone = withdraw_memes(plan, memes, why)
        log(f"memes {sorted(memes)} taken off block(s) {gone}")
        _write_json(plan_path, plan)
    return plan


# --------------------------------------------------------------------------
# CLI


def run(batch, request_path, result_path, budget_s=DEFAULT_BUDGET_S, python=None,
        runner=None, env=None, clock=time.monotonic, log=None):
    """Answer the request; the result doc is written after every video."""
    batch = Path(batch).resolve()
    req = load_request(request_path)
    t0 = clock()
    res = {"schema": RESULT_SCHEMA, "task": TASK, "batch_id": req.get("batch_id"),
           "request_at": req.get("at"), "at": _now_z(), "videos": []}
    for v in req["videos"]:
        if clock() - t0 > budget_s:
            row = result_row(v, FAILED, f"the repair's time budget ({budget_s:.0f} s) ran "
                                        f"out before this video - not attempted")
        else:
            try:
                row = repair_video(batch, v, python=python, runner=runner, env=env, log=log)
            except Exception as e:                              # noqa: BLE001
                # before the snapshot (a disk error, an unreadable file):
                # nothing was touched, the refusal stands
                row = result_row(v, FAILED, f"{type(e).__name__}: {e}")
        res["videos"].append(row)
        res["at"] = _now_z()
        _write_json(result_path, res)
    if not req["videos"]:
        _write_json(result_path, res)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch")
    ap.add_argument("--request", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S,
                    help="no video is started past this many seconds (default "
                         "%(default)s; the root's ceiling is 90 min)")
    a = ap.parse_args(argv)
    batch = Path(a.batch)
    if not batch.is_dir():
        print(f"REPAIR: ERROR: no batch directory {batch}", file=sys.stderr)
        return EXIT_BAD_CALL
    try:
        res = run(batch, a.request, a.result, budget_s=a.budget_s)
    except BadCall as e:
        print(f"REPAIR: ERROR: {e}", file=sys.stderr)
        return EXIT_BAD_CALL
    for r in res["videos"]:
        print(f"{r['slug']}: {r['outcome']}" + (f" - {r['reason']}" if r.get("reason") else ""))
    print(f"{a.result}: {len(res['videos'])} video(s), "
          f"{sum(1 for r in res['videos'] if r['outcome'] == RENDERED)} re-rendered")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
