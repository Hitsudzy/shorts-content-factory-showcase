#!/usr/bin/env python3
"""CF-0791: the shot pool checked before the render, not after the judge.

ExampleScience lost two of its three rendered videos after the render
(`docs/notes/funnel-2026-10-18.md`, item 3): a cut after the render is the
dearest loss of a batch - every stage has already been paid for - and the slot
is not refilled from the reserve after it (the reserve loop of CF-0306 answers
only the Researcher's refusals, `03 -> skipped[]`). What the pool already knew
before the cut, from the indexer's cached measurement of every shot
(`<pool>/<video>.shots.json -> shots[].usable_cached`, CF-0435), was enough to
see the second of them coming:

* **voyager-1** (`example-science/2026-10-17T0817Z`, F 29 after the judge, C 77
  in the plan): the frame judge charged foreign on-screen text on 7 blocks
  (-36 at the rule's cap), all of them slides of one NASA lecture
  (`commons-64290655`) - plasma-wave charts, a magnetic-field plot, a
  "Termination Shock" diagram. Their cached `text_regions` were 13, 20, 21, 23,
  25, 25 and 7. The Editor's pre-cut text rule (CF-0275,
  `resolve_anchors.text_cut_refusal`) refuses a panel of text only when 95 %
  of it falls *outside* the 9:16 window and it has 20 regions or more; a chart
  that sits inside the window is shown, and the judge then reads it as text
  that is not ours. **text panel in the window** is that case.
* the same video's 4 worst shots were under 600 px on the short side (492,
  544, 580, 590) - the Editor prices a source under 720 at -2 a shot capped at
  -8 (`score.low_resolution`, "the best the pool had"), so 17 low shots cost
  what 4 do. **resolution floor** refuses a shot under a floor no accepted
  video has used: the lowest short side in the 40 accepted videos of Reel,
  Tech and Science whose shots are still in the pool is 608.
* **static hook** - a hook block (the first `hook_seconds`) whose every shot is
  motionless in its source (`sharpness_cached.motion` under the floor) opens
  the video on a slide. It is recorded, never refused: no cut so far came of
  it (voyager-1's opening slides were not charged), and the one "frozen hook"
  cut (sophie-adenot, `2026-10-12T2001Z`, F 24) was the QC probe reading black
  space, fixed in video-editor v2.3.2 (CF-0712) - the pinned editor reads that
  same render with no frozen block.

The rule lives here, in the root, beside the score model the Editor already
imports (`_score.py` puts `shared/score` on its path), so the Editor's pre-cut
filter and this module's offline audit cannot disagree: `shot_refusal()` is
the per-shot answer the Editor asks before the cut, `audit_plan()` is the same
answer over a finished plan.

Per channel: `channels/<id>.json -> video_editor.shot_guard` (all keys
optional, DEFAULTS below fill the rest), judged by `validate_config()` from
`patterns/validate_patterns.py` (`VIDEO_EDITOR_SHOT_GUARD_KEY`) and read by
the Editor's `resolve_anchors.configure_shot_guard()` once per run from its
`--channel`. Reel, Tech and Science carry `{"mode": "fail"}` since the
user's signature (CF-0797, Telegram 18.10.2026), the CF-0791 measurement kept
in `shot_guard_note`.

    python3 shared/score/shot_guard.py measure <batch-dir>... [--pool DIR] [--root DIR] [--json]
    python3 shared/score/shot_guard.py shot <shots.json> <index> [--channel ID] [--root DIR]

`measure` reads every `work/<slug>/plan.json` of each batch and the pool's
shot records, and sets the guard's verdict beside what happened to the video
(`05-video-editor.json` refusals, `06-frame-judge.json` gate). It reads and
writes nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL_REL = Path("shared") / "footage"

MODES = ("fail", "warn", "off")
DEFAULTS = {
    # `warn` records and refuses nothing; `fail` makes a refusing finding take
    # the shot out of the pool before the cut. The default stays `warn` for a
    # channel that names no mode; Reel, Tech and Science set `fail` (the
    # user's signature, CF-0797, Telegram 18.10.2026).
    "mode": "warn",
    # text regions in one frame from which the frame reads as a panel of
    # somebody else's text even inside the window. 13: every judged block of
    # the Reel/Tech/Science artifacts at or over it was charged foreign by the
    # judge except one (chatgpt, Tech 0839Z: our own recording, exempt by
    # kind); 7..12 also holds accepted Reel blocks (rink-rivals 12,
    # delver 11, blade-runner-2099 10, weekend-night-live 8) the judge passed.
    "text_panel_regions_min": 13,
    # the source's short side under which a shot is not shown at all.
    "min_short_side": 600,
    "hook_seconds": 5.0,
    # `sharpness_cached.motion` (CF-0452: mean luma change between probes) at
    # or under which a hook shot is a still in its own source.
    "hook_min_motion": 0.1,
}
KNOWN_KEYS = tuple(DEFAULTS)

TEXT_PANEL = "text_panel_in_window"
UNDER_FLOOR = "under_resolution_floor"
STATIC_HOOK = "static_hook"
REFUSING = (TEXT_PANEL, UNDER_FLOOR)   # STATIC_HOOK is recorded, never refused

OWN_CAPTURE_PREFIX = "own_capture-"     # video-editor _clip_names.OWN_CAPTURE_PREFIX (CF-0567)

# keys of a plan block under which the pictures it shows are held; anything
# else (length_supply, candidate_supply, face_window ...) lists candidates the
# planner looked at and did not show.
_PICTURE_CONTAINERS = ("asset", "cuts", "sides")


class ShotGuardError(ValueError):
    """A `video_editor.shot_guard` block that cannot be used as it stands."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
def validate_config(block, ctx="video_editor.shot_guard"):
    """Errors for one `video_editor.shot_guard` block, as a list of strings."""
    if not isinstance(block, dict):
        return [f"{ctx}: must be an object, got {block!r}"]
    errs = [f"{ctx}: unknown key {k!r} - the guard reads only {list(KNOWN_KEYS)} "
            f"(beside 'note' and '<key>_note' prose)"
            for k in block
            if k not in KNOWN_KEYS and k != "note"
            and not (k.endswith("_note") and k[:-5] in KNOWN_KEYS)]
    if "mode" in block and block["mode"] not in MODES:
        errs.append(f"{ctx}.mode: must be one of {list(MODES)}, got {block['mode']!r}")
    for key in ("text_panel_regions_min", "min_short_side"):
        v = block.get(key)
        if key in block and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            errs.append(f"{ctx}.{key}: must be an integer >= 1, got {v!r}")
    for key in ("hook_seconds", "hook_min_motion"):
        v = block.get(key)
        if key in block and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
            errs.append(f"{ctx}.{key}: must be a number >= 0, got {v!r}")
    return errs


def config(block=None):
    """DEFAULTS overlaid with a channel's `video_editor.shot_guard` block."""
    block = block or {}
    errs = validate_config(block)
    if errs:
        raise ShotGuardError("; ".join(errs))
    return {**DEFAULTS, **{k: block[k] for k in KNOWN_KEYS if k in block}}


def channel_config(channel_id, root=None):
    """The guard's settings for one channel, from `channels/<id>.json`."""
    if not channel_id:
        return config()
    path = Path(root or ROOT) / "channels" / f"{channel_id}.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config()
    return config(((cfg.get("video_editor") or {}).get("shot_guard")) or {})


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------
def is_own_capture(shot_id):
    return str(shot_id or "").startswith(OWN_CAPTURE_PREFIX)


def shot_findings(shot, cfg=None, shot_id=None):
    """The guard's findings for one pool shot record, a list of dicts
    `{rule, value, limit, refuses}`. `shot` is a `shots[]` entry of a
    `.shots.json`; a shot with no cached measurement has nothing to say -
    the guard never measures, it reads what the indexer froze."""
    cfg = cfg or config()
    if cfg["mode"] == "off" or not isinstance(shot, dict):
        return []
    cached = shot.get("usable_cached") or {}
    out = []
    regions = cached.get("text_regions")
    # our own recording is delivered as recorded and its text is the tool's
    # interface - the footage itself (CF-0567), exempt by kind
    if (isinstance(regions, (int, float)) and regions >= cfg["text_panel_regions_min"]
            and not is_own_capture(shot_id)):
        out.append({"rule": TEXT_PANEL, "value": regions,
                    "limit": cfg["text_panel_regions_min"],
                    "area": cached.get("text_area"),
                    "outside": cached.get("text_outside_crop")})
    short = cached.get("short_side")
    if isinstance(short, (int, float)) and short < cfg["min_short_side"]:
        out.append({"rule": UNDER_FLOOR, "value": short, "limit": cfg["min_short_side"]})
    for f in out:
        f["refuses"] = cfg["mode"] == "fail" and f["rule"] in REFUSING
    return out


def shot_refusal(shot, cfg=None, shot_id=None):
    """None, or the sentence for why this shot leaves the pool before the cut
    (only in mode `fail`). The Editor's pre-cut filter asks this next to its
    own cached refusals (`resolve_anchors.precut_cache_refusal`)."""
    words = []
    for f in shot_findings(shot, cfg, shot_id):
        if not f["refuses"]:
            continue
        if f["rule"] == TEXT_PANEL:
            words.append(f"{TEXT_PANEL}: {f['value']} text regions in the frame (from "
                         f"{f['limit']}) - a chart or slide of somebody else's text the "
                         f"judge reads as foreign (CF-0791)")
        else:
            words.append(f"{UNDER_FLOOR}: short side {f['value']} px under the "
                         f"channel's floor {f['limit']} px (CF-0791)")
    return "; ".join(words) or None


def plan_shots(block):
    """The pool shot ids a plan block shows, in order, each once."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            sid = node.get("shot")
            if isinstance(sid, str) and ":" in sid:
                out.append(sid)
            for key in _PICTURE_CONTAINERS:
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(block)
    return list(dict.fromkeys(out))


def split_shot_id(shot_id):
    vid, _, idx = str(shot_id).rpartition(":")
    try:
        return vid, int(idx)
    except ValueError:
        return vid, None


class Pool:
    """The pool's shot records by shot id, read lazily from `<dir>/<video>.shots.json`."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self._videos = {}

    def video(self, vid):
        if vid not in self._videos:
            path = self.dir / f"{vid}.shots.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._videos[vid] = {s.get("index"): s for s in data.get("shots") or []}
            except (OSError, ValueError, AttributeError):
                self._videos[vid] = None
        return self._videos[vid]

    def shot(self, shot_id):
        vid, idx = split_shot_id(shot_id)
        shots = self.video(vid)
        return None if shots is None or idx is None else shots.get(idx)


def audit_plan(plan, pool, cfg=None):
    """The guard over a finished plan: one finding per (block, shot, rule).

    Returns {"mode", "findings": [...], "refuses": bool, "shots": n,
    "unmeasured": [shot ids the pool no longer holds]}. `refuses` is whether
    the plan shows a shot the guard would have taken out before the cut.
    """
    cfg = cfg or config()
    findings, unmeasured, seen = [], [], 0
    hook = float(cfg["hook_seconds"])
    for i, block in enumerate(plan.get("blocks") or []):
        ids = plan_shots(block)
        start = float(block.get("start") or 0.0)
        hook_motions = []
        for sid in ids:
            seen += 1
            rec = pool.shot(sid)
            if rec is None:
                unmeasured.append(sid)
                continue
            for f in shot_findings(rec, cfg, sid):
                findings.append({"block": i, "t": round(start, 2), "shot": sid, **f})
            motion = (rec.get("sharpness_cached") or {}).get("motion")
            hook_motions.append(None if is_own_capture(sid) else motion)
        if (cfg["mode"] != "off" and start < hook and hook_motions
                and all(isinstance(m, (int, float)) and m <= cfg["hook_min_motion"]
                        for m in hook_motions)):
            findings.append({"block": i, "t": round(start, 2), "shot": ",".join(ids),
                             "rule": STATIC_HOOK, "value": max(hook_motions),
                             "limit": cfg["hook_min_motion"], "refuses": False})
    return {"mode": cfg["mode"], "findings": findings,
            "refuses": any(f["refuses"] for f in findings),
            "shots": seen, "unmeasured": unmeasured}


# --------------------------------------------------------------------------
# the offline measurement
# --------------------------------------------------------------------------
def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def outcomes(batch_dir):
    """{slug: what happened to the video} from the batch's 05 and 06."""
    batch_dir = Path(batch_dir)
    out = {}
    judge = _read(batch_dir / "06-frame-judge.json") or {}
    for v in judge.get("videos") or []:
        foreign = sorted({int(str((e.get("where") or {}).get("block", "")).split("-")[-1])
                          for e in (v.get("score") or {}).get("log") or []
                          if e.get("rule") == "score.judge_foreign"
                          and str((e.get("where") or {}).get("block", "")).split("-")[-1].isdigit()})
        out[v.get("slug")] = {"stage": "judge", "gate": v.get("gate"),
                              "reason_code": v.get("reason_code"),
                              "score": (v.get("score") or {}).get("score"),
                              "foreign_blocks": foreign}
    editor = _read(batch_dir / "05-video-editor.json") or {}
    by_script = {}
    for board in (batch_dir / "work").glob("*/storyboard.json"):
        sid = (_read(board) or {}).get("script_id")
        if sid:
            by_script[sid] = board.parent.name
    for r in editor.get("refusals") or []:
        slug = by_script.get(r.get("script_id"))
        if slug and slug not in out:
            out[slug] = {"stage": "editor", "gate": "refused",
                         "reason_code": r.get("reason_code"),
                         "score": (r.get("numbers") or {}).get("score"), "foreign_blocks": []}
    return out


def measure(batch_dirs, pool, cfg_for=None):
    """One row per plan of the given batches: the guard against the outcome."""
    rows = []
    for bd in batch_dirs:
        bd = Path(bd)
        channel = bd.parent.name
        cfg = cfg_for(channel) if cfg_for else config()
        # judged as if the channel were in `fail`: the question of the
        # measurement is what the guard *would* take out
        cfg = {**cfg, "mode": "fail"}
        happened = outcomes(bd)
        for plan_path in sorted(bd.glob("work/*/plan.json")):
            plan = _read(plan_path)
            if not isinstance(plan, dict):
                continue
            slug = plan_path.parent.name
            res = audit_plan(plan, pool, cfg)
            o = happened.get(slug) or {}
            foreign = set(o.get("foreign_blocks") or [])
            panel = sorted({f["block"] for f in res["findings"] if f["rule"] == TEXT_PANEL})
            rows.append({
                "batch": f"{channel}/{bd.name}", "slug": slug,
                "outcome": o.get("gate") or "not judged",
                "reason_code": o.get("reason_code"), "score": o.get("score"),
                "plan_score": (plan.get("score") or {}).get("score"),
                "refuses": res["refuses"],
                "taken_out": len({f["shot"] for f in res["findings"] if f["refuses"]}),
                "text_panel_blocks": panel,
                "judge_foreign_blocks": sorted(foreign),
                "text_panel_caught": sorted(set(panel) & foreign),
                "under_floor_blocks": sorted({f["block"] for f in res["findings"]
                                              if f["rule"] == UNDER_FLOOR}),
                "static_hook_blocks": sorted({f["block"] for f in res["findings"]
                                              if f["rule"] == STATIC_HOOK}),
                "shots": res["shots"], "unmeasured": len(res["unmeasured"]),
            })
    return rows


def _line(r):
    flags = []
    if r["text_panel_blocks"]:
        flags.append(f"text panel {r['text_panel_blocks']} (judge foreign {r['judge_foreign_blocks']}, "
                     f"caught {r['text_panel_caught']})")
    if r["under_floor_blocks"]:
        flags.append(f"under floor {r['under_floor_blocks']}")
    if r["static_hook_blocks"]:
        flags.append(f"static hook {r['static_hook_blocks']}")
    verdict = (f"would take out {r['taken_out']} shot(s) before the cut" if r["refuses"]
               else "clear")
    tail = f" [{r['unmeasured']}/{r['shots']} shots no longer in the pool]" if r["unmeasured"] else ""
    return (f"{r['batch']} {r['slug']}: {r['outcome']}"
            f"{' ' + str(r['reason_code']) if r['reason_code'] else ''}"
            f"{' ' + str(r['score']) if r['score'] is not None else ''} - {verdict}"
            f"{': ' + '; '.join(flags) if flags else ''}{tail}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="the guard over finished batches, against their outcome")
    m.add_argument("batches", nargs="+")
    m.add_argument("--pool", help="the shot pool directory (default <root>/shared/footage)")
    m.add_argument("--root", help="the factory root for channels/ (default this checkout)")
    m.add_argument("--json", action="store_true")
    s = sub.add_parser("shot", help="the guard's answer for one shot of a .shots.json")
    s.add_argument("shots_json")
    s.add_argument("index", type=int)
    s.add_argument("--channel")
    s.add_argument("--root")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else ROOT
    if a.cmd == "shot":
        data = _read(a.shots_json)
        if not isinstance(data, dict):
            print(f"shot_guard: cannot read {a.shots_json}", file=sys.stderr)
            return 2
        rec = {x.get("index"): x for x in data.get("shots") or []}.get(a.index)
        if rec is None:
            print(f"shot_guard: no shot {a.index} in {a.shots_json}", file=sys.stderr)
            return 2
        sid = f"{Path(a.shots_json).name[:-len('.shots.json')]}:{a.index}"
        cfg = channel_config(a.channel, root)
        print(json.dumps({"shot": sid, "mode": cfg["mode"],
                          "findings": shot_findings(rec, cfg, sid),
                          "refusal": shot_refusal(rec, cfg, sid)}, ensure_ascii=False))
        return 0
    pool = Pool(a.pool or root / POOL_REL)
    rows = measure(a.batches, pool, cfg_for=lambda ch: channel_config(ch, root))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(_line(r))
        refused = [r for r in rows if r["refuses"]]
        passed = [r for r in rows if r["refuses"] and r["outcome"] == "pass"]
        print(f"\n{len(rows)} plan(s); the guard would change the cut of {len(refused)}; "
              f"of them accepted by the judge: {len(passed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
