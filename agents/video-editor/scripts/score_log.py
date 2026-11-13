#!/usr/bin/env python3
"""CF-0434: the score log of one video, and the early stop on it.

The grill of 2026-09-29 (Q11, Q17, Q20, Q21, Q28): the score (CF-0432,
`shared/score/score.py`, prices in `shared/gate-prices.json`) is counted at
every stage, and as soon as the penalties that have **already happened** put a
video under the threshold N, the video goes no further - no render, no second
render, no delivery of what surely will not pass. A forecast never counts
(Q17). Lesson `example-film/2026-09-27T0929Z`: three of five scripts died in
this stage after the voice was paid for.

One file per video, beside its plan (`work/<slug>/plan.json` ->
`work/<slug>/plan.score.json`). Each stage of this repo writes its own real
penalties into it and asks what is left:

    stage    who writes it                  what it prices
    plan     build_render_plan.py           pace, hold band, similarity (CF-0433)
    render   render_video.py                the file: length (30-60 s hard, 30-45 s
                                            short_length), frame size (render_defect)
    qc       qc_render.py                   frozen blocks, crop and panel, holes,
                                            repeats, off-entity shots, bed, sound
    judge    (the frame judge, root, CF-0434 part C)

Recording a stage replaces that stage and forgets every later one: a rebuilt
plan is a new video as far as its render and QC go, and a QC-degrade render
replaces the render the previous QC judged.

**The stop.** `stops(block)` is true when the score was computed and its
points are under the threshold. The hard list does not go through here: a
hard finding makes the tier F in the log, and the gate that found it refuses
the way it always did (QC failure, narration ceiling, ...), unchanged. A video
that stops writes `<plan stem>.score.refusal.json` (gate
`score_below_threshold`, funnel code `score_below_threshold`,
`supersedes_video: true`), so
`write_batch_metadata.py` finds it with every other refusal, drops the mp4 of
that script from `videos[]` and lists the script in `refusals[]` with its score
line. A stage that records the video back over N removes that sidecar.

Everything else still goes to the user (Q14): a video at or over N is
delivered exactly as before, its tier shown and nothing decided on it.

**The log in 05.** `record_fields(plan_path, plan)` is the one call that
turns the file into the two fields of a `videos[]` record - `score` (the full
log) and `score_line` (one line) - so a rebuild (CF-0416) writes the same two
fields by calling it. `summary_line(block)` is the line:

    B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts

Stdlib only, like the rest of scripts/.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import _score
import plan_refusal

SCHEMA = "cf0434.score_log/1"
SUFFIX = ".score.json"
STAGE_PLAN, STAGE_RENDER, STAGE_QC, STAGE_JUDGE = "plan", "render", "qc", "judge"
STAGES = (STAGE_PLAN, STAGE_RENDER, STAGE_QC, STAGE_JUDGE)

# the 05 fields
FIELD = "score"
LINE_FIELD = "score_line"

# The render file (score.hard.* and score.short_length live in the model:
# 30-60 s is the hard line, 30-45 s the short-length price).
WANT_FRAME = (1080, 1920)

# qc_render readings -> the model's rules (the same mapping
# scripts/score_calibration.py in the root measured the 17 videos with).
# Under it the viewer gets a strip of a panel, not a panel. The root price
# table's `score.panel_partly_cut.panel_visible_from` (tests/test_score_log.py
# pins the two together): a third until CF-0493, 27.5 % since the user's
# 2026-10-03 signature - between the sliver he rejected mormon-wives-comeback
# for (24 %) and coach-hale of the rerun 1748Z (31 %, refused on -61, accepted).
PANEL_SLIVER = 0.275

R = "score."
RULE_FROZEN = R + "frozen_block"
RULE_CROP = R + "crop_cuts_subject"
RULE_PANEL = R + "panel_partly_cut"
RULE_CARD_OVER_FACE = R + "card_over_face"
RULE_BACKGROUND = R + "abstract_background"
RULE_REPEAT = R + "repeated_shot"
RULE_OFF_TOPIC = R + "off_topic_shot"
RULE_NO_BED = R + "no_lofi_bed"
RULE_LOW_BRIGHTNESS = R + "low_brightness"   # CF-0436: a lift that did not lift
HARD_FOREIGN_TEXT = R + "hard.foreign_text"
HARD_SOUND = R + "hard.sound_broken"
HARD_RENDER = R + "hard.render_defect"
HARD_DURATION = R + "hard.duration_out_of_range"
RULE_SHORT = R + "short_length"
# CF-0416: the cosmetic QC rule `meme_caption_blank_blocks`, priced per block
# once shared/gate-prices.json carries it (_score.has_rule) - not yet.
RULE_MEME_CAPTION_BLANK = R + "meme_caption_blank"
HOOK_SECONDS = _score.HOOK_SECONDS

# The line (`summary_line`), its labels and the stage arithmetic (`build`,
# `stops`, `path_for`) are the root's (`shared/score/score.py`: LABELS,
# HARD_LABELS, summary_line, stages_block, stops, log_path) - one spelling for
# the Editor, the frame judge and the run summary. SCHEMA / SUFFIX / STAGES
# above are kept here only so that a checkout without the root still writes a
# readable log; tests/test_score_log.py pins them equal to the root's.


# --------------------------------------------------------------------------
# findings of the render and of QC (pure)
# --------------------------------------------------------------------------

def render_findings(duration, width=None, height=None, want=WANT_FRAME):
    """The rendered file's own facts: its length (hard outside 30-60 s,
    `short_length` at 30-45 s) and its frame (hard `render_defect` when it is
    not 1080x1920). `duration` is the whole file, end card included."""
    out = []
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None:
        mod = _score.module()
        if mod is not None:
            out += mod.duration_findings(seconds)
    if width and height and (int(width), int(height)) != tuple(want):
        out.append(_score.finding(HARD_RENDER, {},
                                  note=f"frame {width}x{height}, not {want[0]}x{want[1]}"))
    return out


def _idx(r):
    if isinstance(r, dict):
        return r.get("index", r.get("block"))
    return r if isinstance(r, int) else None


def _faults(rows):
    """The records a detector stands behind. A face gate that could not open
    the source refuses by caution, and a caution is not a real penalty (Q17)."""
    return [r for r in rows or [] if not isinstance(r, dict) or (
        r.get("fault", True) and "could not be checked" not in str(r.get("reason") or ""))]


def _start(plan, i):
    blocks = (plan or {}).get("blocks") or []
    if isinstance(i, int) and 0 <= i < len(blocks):
        s = blocks[i].get("start")
        return round(s, 3) if isinstance(s, (int, float)) else None
    return None


def _where(plan, i, at=None):
    t = at if at is not None else _start(plan, i)
    w = {"block": i}
    if t is not None:
        w["t"] = t
    return w


def plan_charged(plan, rule):
    """CF-0435: `(blocks, shots)` the plan stage already charged `rule` on -
    read off the plan's own score block (`plan["score"]["findings"]`), so a
    later stage does not charge the same shot for the same rule twice."""
    blocks, shots = set(), set()
    for f in (((plan or {}).get("score") or {}).get("findings") or []):
        if not isinstance(f, dict) or f.get("rule") != rule:
            continue
        w = f.get("where") or {}
        if w.get("block") is not None:
            blocks.add(w["block"])
        if w.get("shot"):
            shots.add(w["shot"])
    return blocks, shots


def qc_findings(result, plan):
    """The real penalties of one QC verdict (qc_render.py's result dict) over
    the plan it judged. Pure. What each reading costs is the price table's;
    what a reading *is* is decided here, once:

        frozen_clip_blocks           score.frozen_block (x2 in the hook)
        subject_offscreen_blocks     score.crop_cuts_subject
        panel_cut_blocks             crop_cuts_subject under PANEL_SLIVER
                                     (27.5 %) visible, else
                                     score.panel_partly_cut
        subject_covered_blocks       score.card_over_face (0) - the gate's own
                                     call (CF-0442): a block under any card
                                     of the plan (insert, comparison line,
                                     end card) is recorded covered, never
                                     offscreen, so nothing is guessed here
        background_hole_blocks       score.abstract_background
        repeated_pictures            score.repeated_shot where the second lands
        a supplement shot without
          its entity (CF-0348)       score.off_topic_shot
        a shot with burned-in text   score.hard.foreign_text
        bed_missing                  score.no_lofi_bed
        lifted_blocks (fault)        score.low_brightness (CF-0436: the lift
                                     did not clear the floor on the render)
        meme_caption_blank_blocks    score.meme_caption_blank (CF-0416), only
                                     once the price table carries it
        a long silence, clipping     score.hard.sound_broken
        no stream, wrong frame,
          picture adrift of plan     score.hard.render_defect

    The file's length is the render stage's (`render_findings`), not this.

    CF-0435: `score.off_topic_shot` is also a plan-stage price now (a weak
    shot the describer marked `on_topic: false`, `shot_score.plan_findings`).
    A QC finding for a block or shot the plan already charged it on is not
    charged again - one shot, one rule, one price."""
    if not result or result.get("audio_only"):
        return []
    F = _score.finding
    m = result.get("measured") or {}
    fails = [str(f) for f in result.get("failures") or []]
    out = []
    off_blocks, off_shots = plan_charged(plan, RULE_OFF_TOPIC)

    for r in _faults(m.get("frozen_clip_blocks")):
        i = _idx(r)
        w = _where(plan, i)
        out.append(F(RULE_FROZEN, w, hook=_score.in_hook(w.get("t")),
                     note="clip block rendered as a still (qc_render frozen_blocks)"))

    for r in _faults(m.get("subject_offscreen_blocks")):
        i, at = _idx(r), (r.get("at") if isinstance(r, dict) else None)
        out.append(F(RULE_CROP, _where(plan, i, at),
                     note="framed on a face, none in the picture: "
                          + str((r or {}).get("reason", "") if isinstance(r, dict) else "")[:90]))
    for r in _faults(m.get("panel_cut_blocks")):
        i = _idx(r)
        vis = r.get("visible") if isinstance(r, dict) else None
        w = _where(plan, i, r.get("at") if isinstance(r, dict) else None)
        if vis is not None and vis < PANEL_SLIVER:
            out.append(F(RULE_CROP, w, note=f"a sliver of an inset panel: {vis:.0%} in frame"))
        else:
            out.append(F(RULE_PANEL, w, note="inset panel partly in frame"
                         + (f": {vis:.0%}" if vis is not None else "")))
    for r in m.get("subject_covered_blocks") or []:
        # a card over a face is the norm (the user, 2026-09-28): priced 0,
        # said which card. Not _faults(): a covered record is fault: False.
        kinds = [c.get("kind") for c in (r.get("covered_by") or [])
                 if isinstance(c, dict)] if isinstance(r, dict) else []
        if not kinds and isinstance(r, dict) and r.get("insert_kind"):
            kinds = [r["insert_kind"]]
        out.append(F(RULE_CARD_OVER_FACE, _where(plan, _idx(r)),
                     note="face under " + (" + ".join(str(k) for k in kinds)
                                           if kinds else "a card")))

    for i in sorted({_idx(r) for r in m.get("background_hole_blocks") or []} - {None}):
        out.append(F(RULE_BACKGROUND, _where(plan, i), note="block on the procedural background"))
    for r in m.get("repeated_pictures") or []:
        pair = (r.get("blocks") or [None, None]) if isinstance(r, dict) else [None, None]
        i = pair[-1]
        w = _where(plan, i)
        out.append(F(RULE_REPEAT, w, hook=_score.in_hook(w.get("t")),
                     note=f"{r.get('kind')} of block {pair[0]} ({r.get('similarity')})"))

    for f in fails:
        low = f.lower()
        blk = re.search(r"block (\d+)", low)
        i = int(blk.group(1)) if blk else None
        if "burned-in text" in low:
            out.append(F(HARD_FOREIGN_TEXT, _where(plan, i), note=f[:160]))
        elif "without the entity" in low:
            named = re.search(r"block \d+ \(([^)]+)\)", f)
            if i in off_blocks or (named and named.group(1) in off_shots):
                continue   # CF-0435: the plan already charged this shot
            out.append(F(RULE_OFF_TOPIC, _where(plan, i), note=f[:160]))
        elif "silent stretch" in low or "clipping" in low:
            out.append(F(HARD_SOUND, {}, note=f[:160]))
        elif (low.startswith("no video stream") or low.startswith("no audio stream")
              or low.startswith("resolution ") or "adrift" in low):
            out.append(F(HARD_RENDER, {}, note=f[:160]))

    # CF-0436: a luma_lift picture still under the floor on the render - the
    # plan charged the lift, the viewer got a dark shot: one price, here.
    for r in _faults(m.get("lifted_blocks")):
        i = _idx(r)
        out.append(F(RULE_LOW_BRIGHTNESS, _where(plan, i, r.get("at")),
                     note=f"luma_lift x{r.get('gain')} left mean luma "
                          f"{r.get('luma_render')} on the render"))

    if m.get("bed_missing"):
        out.append(F(RULE_NO_BED, {}, note="no bed in the mix (qc_render)"))
    # CF-0416: a cosmetic QC finding costs its own price - one per block a
    # meme holds with none of our captions under it (CF-0379), whatever the
    # gate's mode made of it. Only once the price table carries the rule: a
    # finding the table does not price would stop the whole log.
    if _score.has_rule(RULE_MEME_CAPTION_BLANK):
        for r in _faults(m.get("meme_caption_blank_blocks")):
            i = _idx(r)
            w = _where(plan, i, r.get("at") if isinstance(r, dict) else None)
            out.append(F(RULE_MEME_CAPTION_BLANK, w,
                         note="a meme block with none of our captions under it"))
    return out


# --------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------

def path_for(plan_path):
    """`work/<slug>/plan.json` -> `work/<slug>/plan.score.json`."""
    mod = _score.module()
    if mod is not None:
        return mod.log_path(plan_path)
    p = Path(plan_path)
    return p.with_name(f"{p.stem}{SUFFIX}")


def refusal_path(plan_path):
    return plan_refusal.sidecar_path(path_for(plan_path))


def read(plan_path):
    """The log file of a plan as a dict, or None."""
    try:
        d = json.loads(path_for(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("stages"), list) else None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build(stages, ledger=None):
    """The score block of a list of stage records - the root's
    `stages_block()`: `score()` of every finding in stage order, the findings,
    plus `stages` (per stage: the findings, what it charged, the score and tier
    after it) and `stopped_at` (the first stage after which the points were
    under N, or None). Without the root: `_score.score_block()`'s
    `score: null` + `error`, the stages listed with nothing charged."""
    mod = _score.module()
    if mod is not None:
        return mod.stages_block(stages, ledger)
    rows = [s for s in stages or [] if isinstance(s, dict)]
    rows.sort(key=lambda s: STAGES.index(s["stage"]) if s.get("stage") in STAGES else 99)
    so_far, summary = [], []
    for s in rows:
        found = list(s.get("findings") or [])
        so_far += found
        summary.append({"stage": s.get("stage"), "at": s.get("at"), "findings": found,
                        "charged": None, "score_after": None, "tier_after": None})
    block = dict(_score.score_block(so_far, ledger))
    block["stages"] = summary
    block["stopped_at"] = None
    return block


def record(plan_path, stage, findings, script_id=None, ledger=None):
    """Write one stage's real penalties into the video's log, forget every
    later stage, and return the new block (with `line`). Never raises for an
    I/O reason: a stage must not fail on its bookkeeping - the block is still
    returned, with `write_error`."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r} (one of {STAGES})")
    old = read(plan_path) or {}
    keep = [s for s in old.get("stages") or []
            if s.get("stage") in STAGES and STAGES.index(s["stage"]) < STAGES.index(stage)]
    keep.append({"stage": stage, "at": _now(), "findings": list(findings or [])})
    block = build(keep, ledger)
    doc = {"schema": SCHEMA,
           "script_id": script_id or old.get("script_id"),
           "plan": Path(plan_path).name,
           "stages": keep,
           FIELD: {k: v for k, v in block.items() if k != "stages"},
           "stage_scores": block["stages"],
           LINE_FIELD: summary_line(block)}
    try:
        path_for(plan_path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    except OSError as e:
        block["write_error"] = str(e)
    block["line"] = doc[LINE_FIELD]
    return block


def stops(block):
    """True when the score was computed and its points are under N (the
    root's `stops()`). The hard list is not this: it makes the tier F, and its
    own gate refuses."""
    mod = _score.module()
    if mod is not None:
        return mod.stops(block)
    if not block or block.get("score") is None or block.get("threshold") is None:
        return False
    return block["score"] < block["threshold"]


def check(plan_path, block, script_id, stage, supersedes_video=True):
    """The early stop after `stage`: under N -> write the refusal sidecar and
    return its path; otherwise remove a stale one and return None."""
    side = refusal_path(plan_path)
    if not stops(block):
        try:
            side.unlink()
        except OSError:
            pass
        return None
    line = block.get("line") or summary_line(block)
    reason = plan_refusal.reason_text(
        f"SCORE UNDER THE THRESHOLD after {stage}",
        [f"{block.get('score')} < {block.get('threshold')} (tier F)", line,
         "the video goes no further (CF-0434)"])
    rec = plan_refusal.entry(script_id, plan_refusal.GATE_SCORE, reason,
                             supersedes_video=supersedes_video,
                             numbers={"score": block.get("score"),
                                      "threshold": block.get("threshold"),
                                      "stage": stage})
    rec[LINE_FIELD] = line
    rec[FIELD] = {k: v for k, v in block.items() if k not in ("findings", "line")}
    try:
        side.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        return f"<not written: {e}>"
    return str(side)


def ensure_refusals(batch_dir):
    """CF-0794: the refusal of every video under `<batch>/work/*/` whose log,
    as it was written, stopped under N while no stage wrote the sidecar.

    A stop is a refusal whoever forgot to file it: street-fighter (example-film
    2026-10-18T0841Z) went under N on the plan stage after the plan's own
    check, nothing wrote `plan.score.refusal.json`, and the script was in
    neither list of 05-video-editor.json. Read off the log's stored block -
    never re-priced on today's table, so a price change cannot turn a
    delivered video into a refusal here. Returns the sidecars written."""
    work = Path(batch_dir) / "work"
    if not work.is_dir():
        return []
    written = []
    for log in sorted(work.glob(f"*/*{SUFFIX}")):
        plan = log.with_name(log.name[:-len(SUFFIX)] + ".json")
        if refusal_path(plan).exists():
            continue
        try:
            doc = json.loads(log.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        block = dict(doc.get(FIELD) or {}) if isinstance(doc, dict) else {}
        if block.get("score") is None or block.get("threshold") is None \
                or not block["score"] < block["threshold"]:
            continue
        block["line"] = doc.get(LINE_FIELD)
        side = check(plan, block, doc.get("script_id") or script_id_for(plan),
                     block.get("stopped_at") or STAGE_PLAN)
        if side and not side.startswith("<"):
            written.append(side)
    return written


def script_id_for(plan_path):
    """The script this log is about: the id the plan stage recorded, else the
    slug of `<batch>/work/<slug>/`, else the plan's stem."""
    doc = read(plan_path) or {}
    if doc.get("script_id"):
        return doc["script_id"]
    import attempts
    found = attempts.batch_context(plan_path)
    return found[1] if found else Path(plan_path).stem


def current(plan_path, ledger=None):
    """The block of the log as it stands, or None when there is no log."""
    doc = read(plan_path)
    if doc is None:
        return None
    block = build(doc["stages"], ledger)
    block["line"] = summary_line(block, ledger)
    return block


def record_render(plan_path, video):
    """The render stage: probe the rendered file and record its length and
    frame. Returns the block, or None when the file cannot be probed (the QC
    that follows says why; a render is never failed on its bookkeeping)."""
    try:
        from common import probe_json
        info = probe_json(video)
    except Exception:
        return None
    v = next((st for st in info.get("streams") or [] if st.get("codec_type") == "video"), {})
    duration = (info.get("format") or {}).get("duration")
    return record(plan_path, STAGE_RENDER,
                  render_findings(duration, v.get("width"), v.get("height")))


def stop_line(block, stage, sidecar):
    return (f"SCORE F after {stage}: {block.get('line') or summary_line(block)} - "
            f"the video goes no further; refusal -> {sidecar} "
            f"({plan_refusal.code_for(plan_refusal.GATE_SCORE)}/{plan_refusal.GATE_SCORE})")


def record_fields(plan_path=None, plan=None, ledger=None):
    """`{"score": ..., "score_line": ...}` for a `videos[]` record of
    05-video-editor.json (and for a rebuild's, CF-0416). Read off the log file
    beside the plan; a plan with no log file (built before CF-0434) is scored
    on what it carries itself (`plan["score"]["findings"]`, the plan stage).
    `score: null` / `score_line: null` when neither exists."""
    doc = read(plan_path) if plan_path else None
    if doc is not None:
        block = build(doc["stages"], ledger)
    elif isinstance((plan or {}).get("score"), dict) and "findings" in plan["score"]:
        block = build([{"stage": STAGE_PLAN, "findings": plan["score"]["findings"]}], ledger)
    else:
        return {FIELD: None, LINE_FIELD: None}
    block.pop("line", None)
    return {FIELD: block, LINE_FIELD: summary_line(block)}


# --------------------------------------------------------------------------
# the line
# --------------------------------------------------------------------------

def summary_line(block, ledger=None):
    """One line - the root's `summary_line()`:

        B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts

    `очки не посчитаны: <why>` when the block has no score or the root's
    model is not reachable."""
    mod = _score.module()
    if mod is not None:
        return mod.summary_line(block, ledger)
    return f"очки не посчитаны: {(block or {}).get('error') or _score.error() or 'нет лога'}"


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="score_log",
                                 description="the score log of one video (CF-0434)")
    ap.add_argument("plan", help="the video's plan.json (the log is <stem>.score.json)")
    ap.add_argument("--json", action="store_true", help="the 05 fields as JSON")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    plan = None
    try:
        plan = json.loads(Path(ns.plan).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    fields = record_fields(ns.plan, plan)
    if ns.json:
        print(json.dumps(fields, ensure_ascii=False, indent=2))
    else:
        print(fields[LINE_FIELD] or "no score log")
        for s in (fields[FIELD] or {}).get("stages") or []:
            print(f"  {s['stage']}: {s['charged']} -> {s['score_after']} ({s['tier_after']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
