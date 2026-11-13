#!/usr/bin/env python3
"""CF-0437: the topic's pool laid out for the writer BEFORE a word is written.

Why
---
Batch `example-film/2026-09-27T0929Z`, mechanism B: hooks and visual lines were
written off the news and the trailer, not off the pool. Kaijura promised
"soldiers clearing rubble" and "aerial shots of the ruins" (not in the pool),
Day Drinker "the wave-shaped building" three times. Under the score model
(CF-0432) such a text no longer kills the video, but every block it asks for
and the pool cannot show costs points ("similarity < 0.22", "speech without a
frame"). The direction "make it from what is given" (the user, 2026-09-28;
grill 2026-09-29, Q20) turns the order round: first the shots the topic
actually holds, then the sequence of frames, then the narration and the
anchors written to that sequence.

What it prints
--------------
For every topic of the batch (or the one `--topic` names), the topic's OWN
sources (`01b-footage-index.json -> sources_by_topic`, CF-0274 - never the
batch's other footage) and every shot of them the Video Editor can put on
screen at all:

  * **clean** - no rule of `shot_usability` fired;
  * **weak**  - a soft rule fired (`low_framing`, `low_brightness`,
    `low_resolution`, `off_topic_shot`): the shot stays, it costs points when
    it reaches the screen, and the Editor often shows it with a presentation
    (`blur_fill` / `luma_lift`, CF-0436) for less;

and leaves out, with a count, every shot a **hard** rule takes out (black,
empty, burned-in text - CF-0435) and every shot the Editor's pre-cut gate
refuses (`resolve_anchors.precut_refusal`: no moment mark, shorter than
`MIN_CUT_SECONDS`; `text_cut_refusal`: text the crop would cut). Nothing here
judges a shot: the verdicts are `agents/footage-indexer/scripts/
shot_usability.py` (`of()`) and the Editor's own functions reached the way
`pool_depth.py` reaches them (`pool_depth.editor_module()`), so this list and
the pool-depth count of the indexer cannot drift. Nothing is re-measured
(CF-0410: the pool is transient) - a shot whose cached measurements are stale
is judged on its flags alone, as `pool_depth.screen_shots()` does.

Each shot carries its `ref` (`<video_id>:<index>`), `start`/`end`/`seconds`,
the one-line `description`, `is_card`, `shows_entity` (a supplement's entity
is on screen, CF-0344), `usability.score` (the ranking key of CF-0435) and the
soft rules that fired. The order is the order a sequence is built in: sources
in `sources_by_topic` order (the canonical ones first), shots in time order
inside each source - a trailer's own cut is the first sequence the pool
offers.

How long the pool is
--------------------
One sample, one use (CF-0121): every block needs a shot of its own, so the
pool holds about `available shots x block seconds` of narration. The block
length is the pattern's `key_frame_hold_seconds` - unknown before the
rotation's assignment (step 3), so `--hold` takes the drawn value and the
default is `DEFAULT_HOLD_SECONDS`. It is an **upper bound**: the similarity
floor (0.22) needs phrases, and there are none yet. The length the script is
written to (CF-0437 item 2, finished-video seconds, the channel's
`narration_budget`):

  * the pool holds the band (>= `total_seconds_min`) - write to the band;
  * it holds between the hard floor and the band - write to what it holds:
    a 30-45 s video is kept with the small `score.short_length` price, and
    the text is **not** stretched to reach 45;
  * it holds less than the hard floor - write to the hard floor (a video under
    it is not made) and say in the report that the pool is thin.

Exit codes: 0 laid out; 3 cannot answer (no footage index, no
`sources_by_topic`, the indexer's modules out of reach); 2 bad usage.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check_narration_budget import find_root, load_budget, narration_band, hard_min_seconds  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

TASK = "CF-0437"
FOOTAGE_INDEX_NAME = "01b-footage-index.json"
SOURCES_BY_TOPIC_KEY = "sources_by_topic"
FETCHED_KEY = "fetched"
SHOTS_SUFFIX = ".shots.json"
INDEXER_REL = Path("agents") / "footage-indexer" / "scripts"

# The block a shot fills when the pattern is not drawn yet. The channel's
# permitted patterns draw `key_frame_hold_seconds` from 1.0 (`list`) to 9.0
# (`contrast`); 3.0 sits at the top of `list`/`explainer` and the bottom of
# the long-hold patterns, so the estimate is conservative for a long hold and
# fair for a short one. A draft number: `--hold` with the drawn value replaces
# it once step 3 has run.
DEFAULT_HOLD_SECONDS = 3.0
# `resolve_anchors.MIN_CUT_SECONDS`, used only when the Editor's module cannot
# be imported (the layout then says `measured: false`).
FALLBACK_MIN_CUT_SECONDS = 0.7

CLEAN, WEAK = "clean", "weak"
EXIT_OK, EXIT_USAGE, EXIT_CANNOT_ANSWER = 0, 2, 3

TARGET_BAND, TARGET_POOL, TARGET_FLOOR = "band", "pool", "hard_floor"


class CannotAnswer(Exception):
    pass


# --------------------------------------------------------------------------
# the indexer's and the Editor's verdicts, reached, never copied

_MODULES = {}


def indexer_modules(root=None):
    """`(shot_usability, pool_depth)` out of the indexer's checkout."""
    key = str(root or "")
    if key in _MODULES:
        return _MODULES[key]
    scripts = Path(root or find_root()) / INDEXER_REL
    if not (scripts / "shot_usability.py").exists():
        raise CannotAnswer(f"{scripts / 'shot_usability.py'} is missing - the shot verdicts "
                           f"are the Footage Indexer's (CF-0435) and this repo has no copy")
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import shot_usability  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        raise CannotAnswer(f"cannot import shot_usability from {scripts}: {exc}")
    try:
        import pool_depth  # noqa: E402
    except Exception:  # noqa: BLE001 - the layout still stands on shot_usability alone
        pool_depth = None
    _MODULES[key] = (shot_usability, pool_depth)
    return _MODULES[key]


def screen(shot, su, pd):
    """`(verdict, why_out)` for one shot: `verdict` is the usability record
    of a shot the Editor can show, `why_out` the reason it cannot (then the
    verdict is None). The same questions `pool_depth.screen_shots()` asks."""
    try:
        start, end = float(shot["start"]), float(shot["end"])
    except (KeyError, TypeError, ValueError):
        return None, "malformed"
    editor = pd.editor_module() if pd is not None else None
    gate = pd.gate_defaults() if pd is not None and editor is not None else None
    cached = shot.get("usable_cached")
    fresh = bool(cached)
    if editor is not None and gate is not None:
        fresh = bool(cached) and not pd._stale(editor, cached)
        bare = {k: v for k, v in shot.items() if k != "usable_cached"}
        cand = {"start": start, "end": end, "shot": shot.get("index"),
                "moment_at": shot.get("moment_at"), "score": None, "source": "pool-layout"}
        try:
            _at, _origin, _span, refusal = editor.precut_refusal(cand, bare, *gate, need=None)
            text_cut = (fresh and hasattr(editor, "text_cut_refusal")
                        and editor.text_cut_refusal(shot, cached))
        except Exception:  # noqa: BLE001 - one malformed shot is not a verdict on the pool
            return None, "malformed"
        if refusal:
            return None, "precut"
        if text_cut:
            return None, "text_cut"
    elif end - start < FALLBACK_MIN_CUT_SECONDS:
        return None, "precut"
    verdict = su.of(shot, measurements=fresh)
    if verdict["hard"]:
        return None, "hard"
    return verdict, None


# --------------------------------------------------------------------------
# the batch

def batch_dir(path):
    p = Path(path)
    return p if p.is_dir() else p.parent


def load_index(directory, footage_index=None):
    path = Path(footage_index) if footage_index else directory / FOOTAGE_INDEX_NAME
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"no readable footage index at {path}: {exc}")
    by_topic = data.get(SOURCES_BY_TOPIC_KEY) if isinstance(data, dict) else None
    if not isinstance(by_topic, dict) or not by_topic:
        raise CannotAnswer(f"{path}: `{SOURCES_BY_TOPIC_KEY}` is missing or empty - the only "
                           f"record of which sources belong to which topic (CF-0274)")
    return path, data


def shots_path(video_id, data, footage_dir=None):
    """The source's `shots.json`: next to the file `fetched[]` names, else in
    `FOOTAGE_DIR` / `--footage-dir` / the shared pool."""
    for entry in data.get(FETCHED_KEY) or []:
        if isinstance(entry, dict) and entry.get("video_id") == video_id and entry.get("path"):
            p = Path(entry["path"]).with_suffix(SHOTS_SUFFIX)
            if p.exists():
                return p
    base = Path(footage_dir or os.environ.get("FOOTAGE_DIR")
                or Path.home() / "shorts-content-factory" / "shared" / "footage")
    p = base / f"{video_id}{SHOTS_SUFFIX}"
    return p if p.exists() else None


def channel_of(directory, data, override=None, root=None):
    if override:
        return resolve_channel(override, root)
    for name in ("03-content-researcher.json", "01-trend-hunter.json"):
        try:
            doc = json.loads((directory / name).read_text())
            ch = resolve_channel(doc.get("channel"), root) if doc.get("channel") else None
        except (OSError, ValueError, AttributeError):
            continue
        if ch:
            return ch
    return resolve_channel(directory.parent.name, root)


# --------------------------------------------------------------------------
# the layout

def shot_entry(video_id, shot, verdict):
    start, end = float(shot["start"]), float(shot["end"])
    soft = [v["rule"] for v in verdict.get("soft") or []]
    return {
        "ref": f"{video_id}:{shot.get('index')}",
        "video_id": video_id,
        "shot": shot.get("index"),
        "start": round(start, 3),
        "end": round(end, 3),
        "seconds": round(end - start, 3),
        "description": (shot.get("description") or "").strip(),
        "is_card": bool(shot.get("is_card")),
        "shows_entity": shot.get("shows_entity") is True,
        "score": verdict.get("score"),
        "penalty": verdict.get("penalty"),
        "soft": soft,
        "class": WEAK if soft else CLEAN,
    }


def topic_layout(topic_id, data, root=None, footage_dir=None):
    su, pd = indexer_modules(root)
    measured = pd is not None and pd.editor_module() is not None
    sources, shots, out = [], [], {}
    for video_id in data.get(SOURCES_BY_TOPIC_KEY, {}).get(topic_id) or []:
        path = shots_path(video_id, data, footage_dir)
        if path is None:
            sources.append({"video_id": video_id, "indexed": False, "shots": 0, "available": 0})
            continue
        try:
            raw = (json.loads(path.read_text()) or {}).get("shots") or []
        except (OSError, ValueError):
            sources.append({"video_id": video_id, "indexed": False, "shots": 0, "available": 0})
            continue
        mine = []
        for shot in sorted((s for s in raw if isinstance(s, dict)),
                           key=lambda s: (float(s.get("start") or 0.0), s.get("index") or 0)):
            verdict, why = screen(shot, su, pd)
            if verdict is None:
                out[why] = out.get(why, 0) + 1
                continue
            mine.append(shot_entry(video_id, shot, verdict))
        sources.append({"video_id": video_id, "indexed": True, "shots": len(raw),
                        "available": len(mine)})
        shots.extend(mine)
    return {
        "topic_id": topic_id,
        "sources": sources,
        "shots": shots,
        "counts": {"available": len(shots),
                   "clean": sum(1 for s in shots if s["class"] == CLEAN),
                   "weak": sum(1 for s in shots if s["class"] == WEAK),
                   "cards": sum(1 for s in shots if s["is_card"]),
                   "left_out": out},
        "measured": measured,
    }


def length_target(available, hold, budget, root=None):
    """How long the pool lets the video be, and what to write to (item 2).

    Seconds of the FINISHED video (the channel's band is about that), with
    the narration's share beside it. None fields when the channel names no
    band - the numbers are not invented here."""
    holds_narration = round(available * hold, 1)
    rec = {"hold_seconds": hold, "holds_narration_seconds": holds_narration,
           "holds_video_seconds": None, "target": None, "target_video_seconds": None,
           "band": None, "hard_min": None}
    if not budget:
        return rec
    lo, hi = budget.get("total_seconds_min"), budget.get("total_seconds_max")
    nb = narration_band(budget, root)
    hard = hard_min_seconds(budget, root)
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)) or not nb:
        return rec
    tail = round(lo - nb[0], 3)
    video = round(holds_narration + tail, 1)
    rec.update({"band": [lo, hi], "hard_min": hard, "tail_seconds": tail,
                "holds_video_seconds": video})
    if video >= lo:
        rec["target"], rec["target_video_seconds"] = TARGET_BAND, [lo, hi]
    elif hard is not None and video >= hard:
        rec["target"], rec["target_video_seconds"] = TARGET_POOL, [math.floor(video), math.floor(video)]
    else:
        floor = hard if hard is not None else lo
        rec["target"], rec["target_video_seconds"] = TARGET_FLOOR, [floor, floor]
    return rec


def target_line(rec):
    held = (f"the pool holds ~{rec['holds_narration_seconds']:g}s of narration at "
            f"{rec['hold_seconds']:g}s a shot (one shot, one block - an upper bound, before "
            f"the similarity floor)")
    if rec["target"] is None:
        return f"{held}; no narration_budget band to hold it to"
    lo, hi = rec["band"]
    t = rec["target_video_seconds"]
    if rec["target"] == TARGET_BAND:
        return f"{held} = ~{rec['holds_video_seconds']:g}s of video -> write to the band {lo:g}-{hi:g}s"
    if rec["target"] == TARGET_POOL:
        return (f"{held} = ~{rec['holds_video_seconds']:g}s of video -> write ~{t[0]:g}s: "
                f"{rec['hard_min']:g}-{lo:g}s is kept with the small score.short_length price; "
                f"do NOT stretch the text to {lo:g}s (CF-0437)")
    return (f"{held} = ~{rec['holds_video_seconds']:g}s of video -> THIN POOL: write to the "
            f"{t[0]:g}s hard floor (under it there is no video) and say it in the report")


def layout(batch, topic=None, footage_index=None, footage_dir=None, hold=None,
           channel=None, root=None):
    directory = batch_dir(batch)
    index_path, data = load_index(directory, footage_index)
    topics = list(data[SOURCES_BY_TOPIC_KEY])
    if topic:
        if topic not in data[SOURCES_BY_TOPIC_KEY]:
            raise CannotAnswer(f"{index_path}: no `{SOURCES_BY_TOPIC_KEY}` entry for {topic!r}")
        topics = [topic]
    try:
        budget = load_budget(channel_of(directory, data, channel, root), root)
    except (OSError, ValueError, KeyError):
        budget = None
    hold = float(hold) if hold else DEFAULT_HOLD_SECONDS
    out = {"task": TASK, "batch": str(directory), "footage_index": str(index_path),
           "hold_seconds": hold, "topics": []}
    for t in topics:
        lay = topic_layout(t, data, root, footage_dir)
        lay["length"] = length_target(lay["counts"]["available"], hold, budget, root)
        out["topics"].append(lay)
    return out


def lines(doc, limit=None):
    for lay in doc["topics"]:
        c = lay["counts"]
        left = ", ".join(f"{n} {k}" for k, n in sorted(c["left_out"].items())) or "none"
        yield (f"POOL {lay['topic_id']}: {len(lay['sources'])} source(s), {c['available']} "
               f"shot(s) the Editor can show ({c['clean']} clean, {c['weak']} weak, "
               f"{c['cards']} card(s)); left out: {left}"
               + ("" if lay["measured"] else " [Editor's pre-cut gate not reachable: "
                  "flags and length only]"))
        yield f"  length: {target_line(lay['length'])}"
        shown = 0
        for src in lay["sources"]:
            if not src["indexed"]:
                yield f"  source {src['video_id']}: no shot index - not in the pool"
                continue
            yield f"  source {src['video_id']}: {src['available']} of {src['shots']} shot(s)"
            for s in (x for x in lay["shots"] if x["video_id"] == src["video_id"]):
                if limit is not None and shown >= limit:
                    break
                shown += 1
                tags = [s["class"] if not s["soft"] else "weak[" + ",".join(s["soft"]) + "]"]
                if s["is_card"]:
                    tags.append("card")
                if s["shows_entity"]:
                    tags.append("entity")
                yield (f"    {s['ref']:<18} {s['start']:7.2f}-{s['end']:<7.2f} {s['seconds']:5.2f}s "
                       f"score {s['score']:.2f} {' '.join(tags):<22} {s['description']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch", required=True,
                    help="the batch directory (or any file in it)")
    ap.add_argument("--topic", help="lay out one topic only")
    ap.add_argument("--footage-index", help="a 01b-footage-index.json elsewhere")
    ap.add_argument("--footage-dir", help="where the shots.json files are (default: next to "
                    "the fetched file, then FOOTAGE_DIR, then shared/footage)")
    ap.add_argument("--hold", type=float, help="seconds a shot holds - the drawn "
                    f"key_frame_hold_seconds (default {DEFAULT_HOLD_SECONDS})")
    ap.add_argument("--channel", help="the channel id (default: read from the batch)")
    ap.add_argument("--json", action="store_true", help="print the layout as JSON")
    ap.add_argument("--out", help="also write the JSON layout to this file")
    ap.add_argument("--limit", type=int, help="print at most this many shots per topic")
    args = ap.parse_args(argv)
    if args.hold is not None and args.hold <= 0:
        ap.error("--hold must be positive")
    try:
        doc = layout(args.batch, args.topic, args.footage_index, args.footage_dir,
                     args.hold, args.channel)
    except CannotAnswer as exc:
        print(f"pool_layout.py: {exc} - nothing laid out", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
    else:
        for line in lines(doc, args.limit):
            print(line)
    return EXIT_OK


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
