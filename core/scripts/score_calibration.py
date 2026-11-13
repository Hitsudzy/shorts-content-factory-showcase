#!/usr/bin/env python3
"""CF-0432 item 4: the score model, calibrated on the videos the user has
already seen and judged by name (`publish/acceptance-log.json`).

Two steps, so that the arithmetic can be re-run on any checkout while the
measurement needs the one that carries `pipeline/`:

    scripts/score_calibration.py measure [label ...]   # reads pipeline/, writes docs/score-calibration/<label>.json
    scripts/score_calibration.py report [--write]      # scores the frozen measurements with shared/gate-prices.json
    scripts/score_calibration.py still-share [label ...]  # re-reads only the still shares off the plans (CF-0418)

`measure` reads, never writes, the batch it measures. For a video with a render
plan on disk it runs the Video Editor's own render QC over the finished mp4
(`qc_render.py <video> <plan> --json`) - the gates of today, on the render the
user saw - and keeps what the plan, `05`, `06` and `03` froze about it. For a
video whose plan is gone (`example-film/2026-09-15T1034Z` kept no `work/`) it
measures the mp4 itself: length, frame size, the motion sweep of the render
gate, and what `05` recorded.

`findings()` turns one measurement into the model's findings. Every finding
names its source: `metric` (a detector read it), `record` (a number a stage
froze into the batch) or `user_verdict` (a defect the user saw that no
detector reads yet - written down as exactly that, never dressed as a metric).

The still shares (CF-0418) are the Video Editor's own count - its
`scripts/still_share.py` `measure(plan)` - frozen into the measurement as
`still_share`, so the plan stage and the calibration count pictures one way:
the picture share (images, posters, cards, whole-frame memes; a frame held off
a video does not count) for the hard line and the zero-priced soft rule, the
stretched share (+ held frames stretched past 2x their shot and 2 s) for
`score.stretched_still_share`. A video whose plan is gone has no picture
record; its picture share is its title/end cards only.

`$RUNLOG_POOL` points at the pipeline/ to read and `$VIDEO_EDITOR_DIR` at the
agents/video-editor checkout; both default to this checkout and then to the
main checkout of the repository (a worktree carries neither).
"""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "score"))

import score as S  # noqa: E402

if str(ROOT / "shared" / "runlog") not in sys.path:
    sys.path.append(str(ROOT / "shared" / "runlog"))
import git_read  # noqa: E402  (CF-0717: git reads with optional locks off)

CACHE = ROOT / "docs" / "score-calibration"
QC_TIMEOUT = 280
MIN_BLOCK_MOTION = 1.0      # qc_render.MIN_BLOCK_MOTION
MAX_HELD_RUN = 1.8          # common.MAX_HELD_RUN
PROBE_GAP = 0.3             # common.PROBE_GAP
RENDER_PROBE_VF = "crop=iw:ih*0.36:0:0,scale=200:-2"   # qc_render.RENDER_PROBE_VF
MIN_SIMILARITY = 0.22       # CF-0290 floor
MIN_COVERAGE = 0.65
MIN_SHORT_SIDE = 720
MIN_MEAN_LUMA = 28          # qc_asset.MIN_MEAN_LUMA
# Under it the viewer gets a strip of a panel, not a panel. The price table's
# `score.panel_partly_cut.panel_visible_from` (pinned by a test): a third until
# CF-0493, 27.5 % since the user's 2026-10-03 signature - between the sliver he
# rejected mormon-wives-comeback for (24 %) and coach-hale 1748Z (31 %, accepted).
PANEL_SLIVER = 0.275
EXPLAINER_RATE_FLOOR = 15.39  # patterns/explainer.json block_rate_per_minute.min


def _main_checkout():
    try:
        out = git_read.run(["-C", str(ROOT), "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        return (ROOT / out).resolve().parent if out else ROOT
    except (OSError, subprocess.SubprocessError):
        return ROOT


def pool():
    if os.environ.get("RUNLOG_POOL"):
        return Path(os.environ["RUNLOG_POOL"])
    # CF-0562: "this checkout holds the batches the entries name", not "it has
    # one channel's directory" - no channel is spelled here
    here = ROOT / "pipeline"
    return here if any((here / e["batch"]).is_dir() for e in ENTRIES) \
        else _main_checkout() / "pipeline"


def editor():
    if os.environ.get("VIDEO_EDITOR_DIR"):
        return Path(os.environ["VIDEO_EDITOR_DIR"])
    here = ROOT / "agents" / "video-editor"
    return here if here.is_dir() else _main_checkout() / "agents" / "video-editor"


_STILL_SHARE = []


def still_share_module():
    """The Video Editor's `scripts/still_share.py` (CF-0418), loaded by path
    from the checkout `editor()` names - one count of pictures for the plan
    stage and for this calibration. Its own imports (`_score`, `repo_paths`)
    live beside it, so its directory goes on the path first."""
    if not _STILL_SHARE:
        import importlib.util
        scripts = editor() / "scripts"
        path = scripts / "still_share.py"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location("still_share_for_calibration", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _STILL_SHARE.append(mod)
    return _STILL_SHARE[0]


def still_record(plan):
    """The Editor's still-share record of a plan (`still_share.measure`)."""
    return still_share_module().measure(plan)


# --------------------------------------------------------------------------
# the videos the user judged by name
# --------------------------------------------------------------------------

def E(label, batch, verdict, why, slug=None, calibrate=True, extra=None):
    return {"label": label, "batch": batch, "slug": slug or label.split("@")[0],
            "verdict": verdict, "why": why, "calibrate": calibrate, "extra": extra or []}


ENTRIES = [
    E("wolfhame", "rebuilds/2026-09-27T1757Z", "accepted", "эталон: «выглядит очень круто»"),
    E("backrooms", "rebuilds/2026-09-27T1757Z", "accepted", "«не идеален, проблемы допустимые»"),
    E("paper-dragon", "example-film/2026-09-23T1722Z", "accepted", "принят 23.09"),
    E("you-can-see-everything", "example-film/2026-09-23T1722Z", "accepted", "принят 23.09"),
    E("american-dread-story", "example-film/2026-09-23T1722Z", "accepted", "принят 23.09"),
    E("widows-bay@v0", "example-film/2026-09-15T1034Z", "accepted",
      "первая сборка, принята 22.09 (опубликована не она)"),
    E("widows-bay@v2", "rebuilds/2026-09-23T1053Z", "accepted", "пересборка, принята"),
    E("outrider-doune-castle", "example-film/2026-09-21T1541Z", "accepted", "принят, опубликован"),
    E("harbourlights", "example-film/2026-09-29T0705Z", "accepted", "принят 29.09"),
    E("vanguards-endgame", "example-film/2026-09-29T0705Z", "accepted", "принят 29.09"),
    E("dtf-st-louis", "example-film/2026-09-15T1034Z", "rejected", "зависший кадр на ~7 с"),
    E("mormon-wives-comeback", "example-film/2026-09-17T1901Z", "rejected",
      "29 с: обрезанная вставка, край панели въехал в кадр"),
    E("delver", "example-film/2026-09-18T2232Z", "rejected", "38 с: кроп 9:16 обрезал обоих"),
    E("everyday-sorcery-2", "example-film/2026-09-15T1034Z", "rejected",
      "13,5 с речи после последнего якоря без своего кадра",
      extra=[S.finding("score.speech_without_picture", {"block": 21, "t": 25.58}, units=13.52,
                       source="record",
                       note="the last block holds one frame for 13.52 s after the last "
                            "anchor (05 cadence + held_frames [21]; the gate reading "
                            "quoted in the acceptance log) - the plan is gone")]),
    E("widows-bay@v1", "rebuilds/2026-09-23T0725Z", "rejected",
      "дубли кадра в первые 5 с и абстрактный фон"),
    E("vanguards-doomsday", "example-film/2026-09-29T0705Z", "rejected",
      "wrong_work_footage: под текстом о Doomsday - кадры других фильмов"),
    E("kaijura-minus-zero", "rebuilds/2026-09-27T1757Z", "rejected",
      "«кринж» - признанное слепое пятно (Q25), в калибровку не входит", calibrate=False),
]


def entry(label):
    for e in ENTRIES:
        if e["label"] == label:
            return e
    raise KeyError(label)


# --------------------------------------------------------------------------
# measure (needs pipeline/)
# --------------------------------------------------------------------------

def _json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe(video):
    r = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height:format=duration", "-of", "json", str(video)])
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    return {"duration": round(float(d.get("format", {}).get("duration", 0)), 3),
            "width": st.get("width"), "height": st.get("height")}


def motion_timeline(video):
    """qc_render.motion_timeline(), the same filter chain, for a render whose
    plan is gone and whose QC therefore cannot be re-run."""
    r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-an", "-vf",
              f"fps={1 / PROBE_GAP},{RENDER_PROBE_VF},tblend=all_mode=difference,"
              f"signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
              "-f", "null", "-"], timeout=240)
    out, at = [], None
    for line in (r.stdout or "").splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            at = float(m.group(1))
            continue
        v = re.search(r"YAVG=([0-9.]+)", line)
        if v and at is not None:
            out.append((round(at - PROBE_GAP, 3), float(v.group(1))))
            at = None
    return out


def still_runs(timeline):
    runs, cur = [], None
    for s, m in timeline:
        if m < MIN_BLOCK_MOTION:
            cur = [cur[0] if cur else s, s + PROBE_GAP]
        else:
            if cur:
                runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    return [{"start": round(a, 2), "end": round(b, 2), "seconds": round(b - a, 2)}
            for a, b in runs if b - a >= MAX_HELD_RUN - 1e-6]


def mean_luma(src, at=None):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if at is not None:
        cmd += ["-ss", f"{max(0.0, at):.2f}"]
    cmd += ["-i", str(src), "-frames:v", "1", "-vf",
            "scale=160:160,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
            "-f", "null", "-"]
    try:
        r = _run(cmd, timeout=30)
    except subprocess.SubprocessError:
        return None
    v = re.search(r"YAVG=([0-9.]+)", r.stdout or "")
    return round(float(v.group(1)), 1) if v else None


def _video_record(doc, slug):
    for v in (doc or {}).get("videos") or []:
        if str(v.get("output_path") or "").endswith(f"/{slug}.mp4") or v.get("slug") == slug:
            return v
    return None


def _sim(intent):
    m = re.search(r"score (\d\.\d+)", intent or "")
    return float(m.group(1)) if m else None


def plan_blocks(plan, base):
    out = []
    for i, b in enumerate(plan.get("blocks") or []):
        a = b.get("asset") or {}
        size = a.get("source_size") or {}
        dur = b["end"] - b["start"]
        src = a.get("src")
        if src and not Path(src).is_absolute():
            src = str(base / src)       # older plans name clips relative to the batch
        at = None if (src or "").endswith((".png", ".jpg", ".jpeg", ".webp")) else \
            (a.get("start_seconds") or 0) + dur / 2
        out.append({
            "i": i, "start": b["start"], "end": b["end"], "kind": a.get("kind"),
            "held": bool(b.get("held_frame")), "shot": b.get("shot"),
            "coverage": a.get("coverage"), "fit": a.get("fit"),
            "short_side": min(size.values()) if size else None,
            "sim": None if b.get("topic_fill") else _sim(b.get("intent")),
            "topic_fill": bool(b.get("topic_fill")),
            "luma": mean_luma(src, at) if src and Path(src).is_file() and a.get("kind") in (
                "clip", "still") else None,
        })
    return out


QC_KEEP = ("duration", "audio_duration", "bed_missing", "bed_declared", "bed_rms_db",
           "background_hole_blocks", "repeated_pictures", "frozen_clip_blocks",
           "held_source_blocks", "subject_offscreen_blocks", "subject_covered_blocks",
           "subject_turned_away_blocks", "panel_cut_blocks", "meme_caption_blank_blocks",
           "caption_contrast", "black_runs", "silence_runs")


def run_qc(video, plan_path, cwd):
    """The render QC of today over the render the user saw. It runs in the
    batch directory: older plans name their clips relative to it, and a
    source the gate cannot open is a gate that cannot explain a missing
    face (the first measurement of delver ran from the wrong place and got
    exactly that)."""
    ed = editor()
    py = ed / ".venv" / "bin" / "python"
    env = dict(os.environ)
    if env.get("RUNLOG_BATCH") and not os.path.isabs(os.path.expanduser(env["RUNLOG_BATCH"])):
        # CF-0541: the child runs in the batch dir - a relative batch is ours
        env["RUNLOG_BATCH"] = os.path.abspath(os.path.expanduser(env["RUNLOG_BATCH"]))
    r = subprocess.run([str(py if py.exists() else sys.executable),
                        str(ed / "scripts" / "qc_render.py"), str(video), str(plan_path),
                        "--json"], capture_output=True, text=True, timeout=QC_TIMEOUT,
                       cwd=str(cwd), env=env)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return {"error": (r.stderr or "")[-800:]}
    m = d.get("measured") or {}
    return {"passed": d.get("passed"), "failures": d.get("failures"),
            "notes": [n for n in d.get("notes") or [] if re.match(r"block \d+:", n)],
            "measured": {k: m.get(k) for k in QC_KEEP}}


def measure(e, keep_qc=False):
    b = pool() / e["batch"]
    slug = e["slug"]
    video = b / "videos" / f"{slug}.mp4"
    plan_path = b / "work" / slug / "plan.json"
    plan = _json(plan_path)
    rec05 = _video_record(_json(b / "05-video-editor.json"), slug)
    rec06 = _video_record(_json(b / "06-frame-judge.json"), slug)
    m = {"label": e["label"], "batch": e["batch"], "slug": slug,
         "video": str(video.relative_to(pool().parent)), "probe": ffprobe(video),
         "plan": bool(plan)}
    if plan:
        m["blocks"] = plan_blocks(plan, b)
        m["comparison_spans"] = [[c.get("start_s"), c.get("end_s")]
                                 for c in plan.get("comparison_lines") or []]
        r = plan.get("rhythm") or {}
        m["pattern"] = r.get("pattern_delivered") or r.get("pattern_requested")
        m["hold_band"] = ((r.get("hold_ceiling") or {}).get("band"))
        m["hold_breaches"] = (r.get("hold_ceiling") or {}).get("breaches")
        m["cadence"] = r.get("cadence")
        m["still_share"] = still_record(plan)
        old = load(e["label"]) if keep_qc else None
        m["qc"] = (old or {}).get("qc") or run_qc(video, plan_path, b)
    else:
        m["motion_runs"] = still_runs(motion_timeline(video))
    if rec05:
        m["rec05"] = {k: rec05.get(k) for k in (
            "cadence", "rhythm_deviations", "held_frames", "pattern_delivered",
            "pattern_requested", "hold_ceiling", "emergency_reuse")}
        q = rec05.get("qc") or {}
        m["rec05"]["qc_bed"] = q.get("bed")
        m["rec05"]["qc_block_notes"] = [n for n in q.get("notes") or []
                                        if re.match(r"block \d+:", n)]
        m["script_id"] = rec05.get("script_id")
    if rec06:
        m["judge"] = [{"entry": v.get("entry"), "verdict": v.get("verdict"),
                       "start": v.get("start"), "end": v.get("end")}
                      for v in rec06.get("verdicts") or []]
        m["judge_gate"] = rec06.get("gate")
    else:
        # a video the operator judged outside the batch's 06 (harbourlights): the
        # judge's own verdicts file in the video's work dir
        vj = _json(b / "work" / slug / "frame-judge" / "verdicts.json")
        if isinstance(vj, dict) and vj.get("verdicts"):
            m["judge"] = [{"entry": v.get("entry"), "verdict": v.get("verdict"),
                           "start": v.get("start"), "end": v.get("end")}
                          for v in vj["verdicts"]]
            m["judge_source"] = "work/frame-judge/verdicts.json"
    cr = _json(b / "03-content-researcher.json") or {}
    for s in cr.get("scripts") or []:
        if s.get("script_id") and s.get("script_id") == m.get("script_id"):
            tail = ((s.get("anchor_cadence") or {}).get("tail")) or None
            m["tail"] = {k: tail.get(k) for k in (
                "deliverable", "speech_after_last_anchor_seconds", "last_anchor")} if tail else None
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{e['label']}.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return m


def restamp_still_share(label):
    """Re-read only `still_share` of a frozen measurement off its plan - the
    rest of the measurement (the render QC, the luma probes) stays as it was.
    None when the video has no measurement or no plan on this disk."""
    m = load(label)
    if not m or not m.get("plan"):
        return None
    e = entry(label)
    plan = _json(pool() / e["batch"] / "work" / e["slug"] / "plan.json")
    if not plan:
        return None
    m["still_share"] = still_record(plan)
    (CACHE / f"{label}.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return m["still_share"]


# --------------------------------------------------------------------------
# findings (pure: reads a frozen measurement)
# --------------------------------------------------------------------------

def _idx(r):
    if isinstance(r, dict):
        return r.get("index", r.get("block"))
    return r if isinstance(r, int) else None


def _faults(rows):
    """The records a detector stands behind. A face gate whose source clip is
    gone ("could not be checked to explain it") has not established a fault -
    it refuses by caution, and a caution is not a real penalty (Q17)."""
    return [r for r in rows or [] if not isinstance(r, dict) or (
        r.get("fault", True) and "could not be checked" not in str(r.get("reason") or ""))]


def _card_blocks(notes):
    return {int(m.group(1)) for n in notes or []
            for m in [re.match(r"block (\d+): title/end card", n)] if m}


def _block_bounds(m):
    """[(start, end)] of the body blocks - the plan's, or 05's cadence laid
    end to end from 0 for a video whose plan is gone."""
    if m.get("blocks"):
        return [(b["start"], b["end"]) for b in m["blocks"]]
    durs = ((m.get("rec05") or {}).get("cadence") or {}).get("durations") or []
    out, t = [], 0.0
    for d in durs:
        out.append((round(t, 3), round(t + d, 3)))
        t += d
    return out


def _start_of(m, i):
    bb = _block_bounds(m)
    return bb[i][0] if i is not None and 0 <= i < len(bb) else None


def findings(m, e=None):
    f = []
    F = S.finding
    probe = m.get("probe") or {}
    f += S.duration_findings(probe.get("duration"))
    if (probe.get("width"), probe.get("height")) != (1080, 1920):
        f.append(F("score.hard.render_defect", {},
                   note=f"frame {probe.get('width')}x{probe.get('height')}, not 1080x1920"))
    rec05 = m.get("rec05") or {}
    qc = (m.get("qc") or {}).get("measured") or {}
    notes = ((m.get("qc") or {}).get("notes") or []) + (rec05.get("qc_block_notes") or [])
    cards = _card_blocks(notes)
    bounds = _block_bounds(m)
    body = bounds[-1][1] if bounds else None

    # blocks that do not move by design - a held frame, a picture, a card: a
    # motionless run over one of them is not a frozen block
    if m.get("blocks"):
        still_idx = {b["i"] for b in m["blocks"] if b["held"] or b["kind"] == "still"} | cards
    else:
        still_idx = set(rec05.get("held_frames") or []) | cards
    # CF-0418: the still shares are the Editor's count (still_share.measure),
    # frozen as `still_share`: pictures for the hard line and the soft rule,
    # pictures + stretched held frames for score.stretched_still_share.
    rec = m.get("still_share") or {}
    if rec.get("share") is not None:
        f += S.still_share_findings(rec["share"])
        st = rec.get("stretched") or {}
        f += S.stretched_still_findings(st.get("share"))
    elif not m.get("blocks"):
        # the plan is gone: no picture record - the title/end cards are the
        # only pictures on record (a held frame never counts, variant (a))
        total = probe.get("duration") or body
        if total:
            card_s = sum(bounds[i][1] - bounds[i][0] for i in cards if i < len(bounds))
            f += S.still_share_findings(card_s / total)

    # frozen picture inside a block that should move
    if m.get("plan"):
        for r in _faults(qc.get("frozen_clip_blocks")):
            i = _idx(r)
            t = _start_of(m, i)
            f.append(F("score.frozen_block", {"block": i, "t": t}, hook=S.in_hook(t)))
    else:
        for run in m.get("motion_runs") or []:
            if body is not None and run["start"] >= body - 1e-6:
                continue            # the channel's ending clip
            i = next((k for k, (a, z) in enumerate(bounds) if a - 1e-6 <= run["start"] < z), None)
            if i is None or i in still_idx:
                continue
            f.append(F("score.frozen_block", {"block": i, "t": run["start"]},
                       hook=S.in_hook(run["start"]),
                       note=f"{run['seconds']} s motionless (render sweep, plan gone)"))

    # the crop / the panel
    spans = m.get("comparison_spans") or []
    for r in _faults(qc.get("subject_offscreen_blocks")):
        i, at = _idx(r), r.get("at") if isinstance(r, dict) else None
        if at is not None and any(a is not None and a <= at <= z for a, z in spans):
            # the face is under the comparison card: a card over a face is the
            # norm (the user, 2026-09-28), not a crop that cut the hero
            f.append(F("score.card_over_face", {"block": i, "t": at},
                       note="no face under the comparison line"))
            continue
        f.append(F("score.crop_cuts_subject", {"block": i, "t": at},
                   note="subject_offscreen_blocks: " + str(r.get("reason", ""))[:90]))
    for r in _faults(qc.get("panel_cut_blocks")):
        i, vis = _idx(r), r.get("visible")
        w = {"block": i, "t": r.get("at")}
        if vis is not None and vis < PANEL_SLIVER:
            f.append(F("score.crop_cuts_subject", w,
                       note=f"a sliver of an inset panel: {vis:.0%} of it in frame"))
        else:
            f.append(F("score.panel_partly_cut", w,
                       note=f"inset panel partly in frame: {vis:.0%}"))
    for r in _faults(qc.get("subject_covered_blocks")):
        f.append(F("score.card_over_face", {"block": _idx(r)}))

    # holes and repeats
    # a hole on the procedural background is one defect, not two: it is
    # charged as abstract background per block, never also as speech seconds
    holes = {_idx(r) for r in qc.get("background_hole_blocks") or []}
    holes |= {b["i"] for b in m.get("blocks") or [] if b["kind"] == "procedural"}
    for i in sorted(h for h in holes if h is not None):
        f.append(F("score.abstract_background", {"block": i, "t": _start_of(m, i)}))
    # repeats: the render gate's own reading (CF-0337) - the same shot again,
    # or a look-alike of it; charged where the second one lands
    for r in qc.get("repeated_pictures") or []:
        i = (r.get("blocks") or [None, None])[-1]
        t = _start_of(m, i)
        f.append(F("score.repeated_shot", {"block": i, "t": t}, hook=S.in_hook(t),
                   note=f"{r.get('kind')} of block {(r.get('blocks') or ['?'])[0]} "
                        f"({r.get('similarity')})"))
    tail = m.get("tail") or {}
    if tail.get("deliverable") is False and tail.get("speech_after_last_anchor_seconds"):
        f.append(F("score.speech_without_picture", {"t": body},
                   units=tail["speech_after_last_anchor_seconds"], source="record",
                   note=f"tail after {tail.get('last_anchor')} (03 anchor_cadence.tail)"))

    # per shot quality
    for b in m.get("blocks") or []:
        w = {"block": b["i"], "t": b["start"]}
        if b["sim"] is not None and b["sim"] < MIN_SIMILARITY:
            f.append(F("score.low_similarity", w, note=f"score {b['sim']}"))
        if b["coverage"] is not None and b["coverage"] < MIN_COVERAGE:
            f.append(F("score.low_framing", w, note=f"coverage {b['coverage']}"))
        if b["short_side"] is not None and b["short_side"] < MIN_SHORT_SIDE:
            f.append(F("score.low_resolution", w, note=f"short side {b['short_side']}"))
        if b["luma"] is not None and b["luma"] < MIN_MEAN_LUMA and b["i"] not in cards:
            f.append(F("score.low_brightness", w, note=f"mean luma {b['luma']}"))
    if not m.get("blocks"):
        for n in notes:
            c = re.match(r"block (\d+): crop keeps (\d+)% of the subject", n)
            if c and int(c.group(2)) < MIN_COVERAGE * 100:
                f.append(F("score.low_framing", {"block": int(c.group(1))}, note=n))

    # pace and hold band
    cad = m.get("cadence") or rec05.get("cadence") or {}
    pattern = m.get("pattern") or rec05.get("pattern_delivered") or rec05.get("pattern_requested")
    durs = cad.get("durations") or []
    if pattern == "explainer" and durs:
        bpm = len(durs) / (sum(durs) / 60.0)
        if bpm < EXPLAINER_RATE_FLOOR:
            f.append(F("score.pace_below_floor", {}, units=math.ceil(EXPLAINER_RATE_FLOOR - bpm),
                       note=f"{bpm:.2f} blocks/min under {EXPLAINER_RATE_FLOOR}"))
    band = m.get("hold_band")
    if not band:
        for d in rec05.get("rhythm_deviations") or []:
            h = re.search(r"hold band ([0-9.]+)-([0-9.]+)s", d)
            if h:
                band = {"min": float(h.group(1)), "max": float(h.group(2))}
    if band and band.get("max") and durs:
        for i, d in enumerate(durs):
            if d > band["max"] + 1e-6:
                f.append(F("score.hold_band_exceeded", {"block": i},
                           note=f"{d}s over the {band['max']}s hold band"))

    # the bed
    if qc.get("bed_missing"):
        f.append(F("score.no_lofi_bed", {}, note="no bed in the mix (qc_render)"))
    elif not m.get("plan"):
        bed = rec05.get("qc_bed") or {}
        if bed and not bed.get("bed_declared"):
            f.append(F("score.no_lofi_bed", {}, source="record", note="05 qc.bed"))

    # frame-judge
    per = {"contradicts": "score.judge_contradicts", "foreign": "score.judge_foreign",
           "neutral": "score.judge_neutral"}
    for v in m.get("judge") or []:
        if v["verdict"] in per:
            f.append(F(per[v["verdict"]], {"block": v["entry"], "t": v.get("start")}))

    for x in (e or {}).get("extra") or []:
        f.append(dict(x))
    return f


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def load(label):
    return _json(CACHE / f"{label}.json")


def score_all(model=None):
    model = model or S.load_model()
    rows = []
    for e in ENTRIES:
        m = load(e["label"])
        if m is None:
            rows.append({"entry": e, "missing": True})
            continue
        fs = findings(m, e)
        rows.append({"entry": e, "findings": fs, "result": S.score(fs, model), "m": m})
    return rows


def verdict_line(rows, threshold):
    bad = []
    for r in rows:
        e = r["entry"]
        if r.get("missing") or not e["calibrate"]:
            continue
        ok = r["result"]["passed"]
        if (e["verdict"] == "accepted") != ok:
            bad.append(e["label"])
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("measure", "report", "still-share"):
        print(__doc__)
        return 2
    if argv[0] == "still-share":
        for lb in argv[1:] or [e["label"] for e in ENTRIES]:
            rec = restamp_still_share(lb)
            if rec is None:
                print(f"{lb}: no plan - left as it was")
                continue
            st = rec.get("stretched") or {}
            print(f"{lb}: pictures {rec.get('share')}, with stretched held frames "
                  f"{st.get('share')} ({st.get('pp_over')} p.p. over 50 %)")
        return 0
    if argv[0] == "measure":
        keep = "--keep-qc" in argv
        labels = [a for a in argv[1:] if a != "--keep-qc"] or [e["label"] for e in ENTRIES]
        for lb in labels:
            m = measure(entry(lb), keep_qc=keep)
            err = (m.get("qc") or {}).get("error")
            print(f"{lb}: measured{' - QC ERROR ' + err[-200:] if err else ''}")
        return 0
    rows = score_all()
    model = S.load_model()
    for r in rows:
        e = r["entry"]
        if r.get("missing"):
            print(f"{e['label']:24} NOT MEASURED")
            continue
        res = r["result"]
        hard = ",".join(h["rule"].split(".")[-1] for h in res["hard"])
        print(f"{e['label']:24} {e['verdict']:9} {res['score']:>6} {res['tier']} "
              f"{'hard:' + hard if hard else ''}")
        if "-v" in argv:
            for x in res["log"]:
                print(f"      {x['price']:>6} {x['rule']} {x['where']} {x.get('note') or ''}")
    bad = verdict_line(rows, model["threshold"])
    print("\nmisplaced:", bad or "none")
    if "--json" in argv:
        print(json.dumps([{"label": r["entry"]["label"], "verdict": r["entry"]["verdict"],
                           "result": r.get("result")} for r in rows], ensure_ascii=False,
                         indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
