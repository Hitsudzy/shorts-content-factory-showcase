#!/usr/bin/env python3
"""CF-0418: how much of the video is a picture that does not move.

The user rejected `kaijura-minus-zero` (2026-09-28) as "a slide show of bad
pictures" and set the line: a picture may hold at most half of the running
time - `score.hard.still_share_over_half`, a point of the score model's hard
list (`shared/gate-prices.json`, CF-0432). On 2026-09-30 the user chose what a
"picture" is (variant (a) of CF-0432's open question):

    counts                                   does not count
    a picture / poster from an image file    a frame held from a video
      (a `still` asset that is not a frame     (`held_frame`, and a clip
      of a video), ken burns over it too        degraded to its frame -
    a card: the factory's own `card` /          `_degraded_still_<i>.png`)
      `typographic` frame, a proof card        moving footage (clips, the
      (`insert.kind: proof`), an end card        cuts of a sequence)
      that is a logo and not a clip            a blur_fill / luma_lift
    a meme picture over the whole frame          presentation of a video shot
      (`insert.kind: meme`, placement            (CF-0436) - it is a video
      `whole`, not animated)                   a meme cut out onto a subject /
                                                 a corner, an animated meme
                                               the channel's ending clip

That table is the HARD share: `score.hard.still_share_over_half` above
`video_editor.max_still_share` of the channel (0.5 unless the channel says
otherwise), and the zero-priced soft `score.still_share` per p.p. over 25 %.

The user's later calls, 2026-09-30: kaijura v3 passed (a) at 30.7 % although
every one of its blocks is a frame held off one behind-the-scenes video - shots
of ~1 s stood for 3-8 s. A STRETCHED held frame goes into a second, SOFT share
(and never into the hard one): a frame held off a video (a `held_frame` block
or cut, a clip degraded to its frame) whose shot stands on screen more than
`STRETCH_MIN_RATIO` times as long as the shot itself runs in its source AND
more than `STRETCH_MIN_SECONDS`. Pictures (a) + stretched held frames over
`STRETCHED_FROM` (50 %) of the running time cost `score.stretched_still_share`,
0.5 point per p.p. over, capped at 20 (the root's price table) - a penalty for
the score to weigh (CF-0434's early stop), never a refusal of its own. A held
frame within that (a 1.2x hold, a 1.5 s one) counts nowhere. The shot's source
length is `end - cut_at` of its `shots.json` entry (what the clip could have
played from where it was cut), stamped onto the plan as `shot_seconds` by the
plan builder so the plan still answers once the footage pool is gone
(CF-0358); a held frame whose shot cannot be found is listed as unmeasured and
not counted.

Both shares come out of one function (`measure`). They are of the video's
running time - the composition, end card included
(`plan["duration"]["composition"]`), which is how
`scripts/score_calibration.py` in the root measured it on the probe.

Pure over a plan dict; the plan builder (`build_render_plan.py`) asks it last,
once the proof card is bound to its line and the end card is on, and refuses
the plan above the line with gate `still_share_over_half` - before the render,
so the refusal goes back to the writer's anchor loop (CF-0411), where an anchor
can be moved onto a moving shot. Stdlib only, like the rest of scripts/.
"""
import json
import os
from pathlib import Path

import _score

RULE_HARD = "score.hard.still_share_over_half"
RULE_SOFT = "score.still_share"
# CF-0418, the user 2026-09-30: pictures + stretched held frames over half -
# 0.5 point per p.p. over 50 %, capped at 20 (was 1 / cap 40 - the user
# re-priced it after calibration, 2026-09-30). The price and the cap are the
# root's (shared/gate-prices.json, `per: "p.p. over 50 %"`, price 0.5, cap 20);
# until the table carries the row the finding is left out (_score.has_rule),
# as CF-0416 / CF-0436 do. The two numbers here are what the report and the
# record say it will cost - the model charges.
RULE_STRETCHED = "score.stretched_still_share"
STRETCHED_FROM = 0.5
STRETCHED_PRICE = 0.5
STRETCHED_CAP = 20

CONFIG_BLOCK = "video_editor"
CONFIG_KEY = "max_still_share"
DEFAULT_MAX_SHARE = 0.5      # the user's line, 2026-09-28
SOFT_FROM = 0.25             # shared/score/score.py STILL_SHARE_SOFT

DEFICIT_SUFFIX = ".still-share.json"
SCHEMA = "cf0418.still_share/1"

# what a counted span is
WHAT_PICTURE = "picture"     # a still asset from an image file
WHAT_CARD = "card"           # the factory's own card / typographic frame
WHAT_PROOF = "proof"         # a proof card insert
WHAT_MEME = "meme"           # a meme picture over the whole frame
WHAT_END_CARD = "end_card"   # an end card that is a logo, not a clip

WHAT_HELD = "held_frame"     # a frame held off a video, stretched: the soft share only

# CF-0418, the user's call of 2026-09-30: a held frame joins the soft share when
# it is stretched - its shot on screen MORE than twice as long as the shot runs in
# its source, and MORE than 2 s. The user's own reference, kept as given: the
# 123 held frames of the 31 plans of September (pipeline/*/2026-09-*/work/*)
# show no gap to put a different line in - the stretch runs continuously from
# 1.0x to 6x+ (8/8/6/4 per quarter from 1.0 to 2.0, 5/5/6/5 from 2.0 to 3.0),
# and 119 of them already stand >= 2 s (the rhythm's shortest hold). What the
# two numbers mean on screen: past 2x the frame stands still longer than its
# shot ever moved; under 2 s it is one beat of a cut, not a slide. Not fitted
# to the accepted videos - CF-0418's report gives their shares as they fall.
STRETCH_MIN_RATIO = 2.0
STRETCH_MIN_SECONDS = 2.0
SHOT_SECONDS_KEY = "shot_seconds"   # the plan builder's stamp (stamp_shot_seconds)

CARD_KINDS = ("card", "typographic")
MEME_WHOLE = (None, "whole")
DEGRADED_PREFIX = "_degraded_still_"
END_CARD_CLIP = "clip"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def soft_from():
    """The soft rule's floor - the root's constant when it is reachable."""
    mod = _score.module()
    return float(getattr(mod, "STILL_SHARE_SOFT", SOFT_FROM)) if mod else SOFT_FROM


def max_share(cfg):
    """`video_editor.max_still_share` of the channel config, or 0.5. A value
    that is not a fraction in (0, 1] is not a stated opinion."""
    v = _f(((cfg or {}).get(CONFIG_BLOCK) or {}).get(CONFIG_KEY))
    return v if v is not None and 0 < v <= 1 else DEFAULT_MAX_SHARE


def _degraded_from_video(plan):
    """Indices of blocks degraded to a still off a video (a clip, a sequence,
    a split): their still is a frame of that video."""
    out = set()
    for d in plan.get("degraded_blocks") or []:
        if isinstance(d, dict) and d.get("to") == "still" and d.get("from") != "still":
            if isinstance(d.get("index"), int):
                out.add(d["index"])
    return out


def _is_video_frame(asset, block, i, degraded):
    if block.get("held_frame") or asset.get("held_frame"):
        return True
    if i in degraded:
        return True
    return Path(str(asset.get("src") or "")).name.startswith(DEGRADED_PREFIX)


def footage_dirs():
    """Where the `shots.json` of the pool lie: `$FOOTAGE_DIR`, else the
    factory's `shared/footage`."""
    env = os.environ.get("FOOTAGE_DIR")
    if env:
        return [Path(env)]
    try:
        import repo_paths
        return [repo_paths.FACTORY_ROOT / "shared" / "footage"]
    except Exception:  # noqa: BLE001 - no factory around: no pool
        return []


def shot_reader(dirs=None):
    """`"<video id>:<shot n>" -> (start, end)` of that shot in its source, or
    None - reading `<dir>/<id>.shots.json` once per id, first dir that has it."""
    dirs = [Path(d) for d in (footage_dirs() if dirs is None else dirs)]
    cache = {}

    def read(key):
        if not key or ":" not in str(key):
            return None
        vid, n = str(key).rsplit(":", 1)
        if vid not in cache:
            lut = {}
            for d in dirs:
                try:
                    data = json.loads((d / f"{vid}.shots.json").read_text())
                except (OSError, ValueError):
                    continue
                for sh in (data.get("shots") if isinstance(data, dict) else None) or []:
                    if not isinstance(sh, dict):
                        continue
                    a, z = _f(sh.get("start")), _f(sh.get("end"))
                    if isinstance(sh.get("index"), int) and a is not None and z is not None:
                        lut[sh["index"]] = (a, z)
                break
            cache[vid] = lut
        try:
            return cache[vid].get(int(n))
        except (TypeError, ValueError):
            return None
    return read


def _source_seconds(holder, shots_of):
    """How long the shot behind a held frame runs in its source from where it
    was cut: the plan's stamp, else `end - cut_at` off shots.json, else None."""
    v = _f(holder.get(SHOT_SECONDS_KEY))
    if v and v > 0:
        return v
    se = shots_of(holder.get("shot")) if shots_of else None
    if not se:
        return None
    a, z = se
    c = _f(holder.get("cut_at"))
    if c is not None and a <= c < z:
        a = c
    return round(z - a, 3) if z > a else None


def stretched(screen, source):
    """The user's line: a held frame is a picture past 2x its shot and 2 s."""
    return bool(source and screen > STRETCH_MIN_RATIO * source
                and screen > STRETCH_MIN_SECONDS)


def _held_entry(block, cut, screen, still, source):
    return {"block": block, "cut": cut, "screen_seconds": round(screen, 3),
            "still_seconds": round(still, 3), "source_seconds": source,
            "ratio": round(screen / source, 2) if source else None,
            "counted": stretched(screen, source), "unmeasured": source is None}


def _is_held_cut(c):
    return c.get("kind") == "still" and (
        c.get("held_frame") or Path(str(c.get("src") or "")).name.startswith(DEGRADED_PREFIX))


def held_frames(plan, shots_of=None):
    """Every frame held off a video in the plan, with its stretch:
    `[{"block", "cut", "start", "end", "src", "entry"}]` - `entry` is what
    goes into the record's `held` list, `counted` when stretched. A side of
    the split opening is not here: half a frame, capped by the rhythm."""
    out = []
    degraded = _degraded_from_video(plan)
    for i, b in enumerate(plan.get("blocks") or []):
        s, e = _f(b.get("start")), _f(b.get("end"))
        if s is None or e is None or e <= s:
            continue
        asset = b.get("asset") or {}
        ak = asset.get("kind")
        if ak == "still" and _is_video_frame(asset, b, i, degraded):
            src = _source_seconds(b, shots_of)
            out.append({"block": i, "cut": None, "start": s, "end": e,
                        "src": asset.get("src"),
                        "entry": _held_entry(i, None, e - s, e - s, src)})
        elif ak == "sequence":
            cuts = asset.get("cuts") or []
            t = s
            for ci, c in enumerate(cuts):
                sec = _f(c.get("seconds")) or 0.0
                if _is_held_cut(c):
                    # the shot's screen time: its held tail plus the cut of
                    # the same shot that played before it in this block
                    screen = max(sec, sum(_f(o.get("seconds")) or 0.0 for o in cuts
                                          if o.get("shot") and o.get("shot") == c.get("shot")))
                    src = _source_seconds(c, shots_of)
                    out.append({"block": i, "cut": ci, "start": t,
                                "end": min(e, t + sec), "src": c.get("src"),
                                "entry": _held_entry(i, ci, screen, sec, src)})
                t += sec
    return out


def stamp_shot_seconds(plan, shots_of=None):
    """Write each held frame's source length onto its block / cut as
    `shot_seconds` while the pool is still there - the plan builder calls it
    before `measure`, so the plan answers after the pool is gone (CF-0358).
    Returns how many were stamped."""
    shots_of = shots_of or shot_reader()
    n = 0
    for h in held_frames(plan, shots_of):
        src = h["entry"]["source_seconds"]
        if not src:
            continue
        b = plan["blocks"][h["block"]]
        holder = b if h["cut"] is None else b["asset"]["cuts"][h["cut"]]
        if holder.get(SHOT_SECONDS_KEY) != src:
            holder[SHOT_SECONDS_KEY] = src
            n += 1
    return n


def _insert_span(block, ins):
    a, z = _f(ins.get("start_s")), _f(ins.get("end_s"))
    if a is None or z is None or z <= a:
        a, z = _f(block.get("start")), _f(block.get("end"))
    return a, z


def spans(plan, shots_of=None, held=None, stretched=False):
    """Every span of the running time a picture holds, per the definition
    above: `[{"block", "what", "start", "end", "src"}]` in block order. An
    insert over a block wins over the block's own asset (it covers it).
    The hard share's spans (variant (a)) by default; `stretched=True` adds
    the stretched held frames - the soft share's spans. `held` -
    `held_frames()`'s answer, when the caller has it already."""
    out = []
    degraded = _degraded_from_video(plan)
    stretched_at = {}
    if stretched:
        if held is None:
            held = held_frames(plan, shots_of)
        for h in held:
            if h["entry"]["counted"]:
                stretched_at.setdefault(h["block"], []).append(h)
    for i, b in enumerate(plan.get("blocks") or []):
        s, e = _f(b.get("start")), _f(b.get("end"))
        if s is None or e is None or e <= s:
            continue
        ins = b.get("insert") or {}
        kind = ins.get("kind")
        if kind == "proof":
            a, z = _insert_span(b, ins)
            out.append({"block": i, "what": WHAT_PROOF, "start": a, "end": z,
                        "src": ins.get("capture_path")})
            if a <= s + 1e-6 and z >= e - 1e-6:
                continue
        elif (kind == "meme" and ins.get("placement") in MEME_WHOLE
              and not ins.get("animated")):
            a, z = _insert_span(b, ins)
            out.append({"block": i, "what": WHAT_MEME, "start": a, "end": z,
                        "src": ins.get("render_src") or ins.get("file")})
            if a <= s + 1e-6 and z >= e - 1e-6:
                continue
        asset = b.get("asset") or {}
        ak = asset.get("kind")
        if ak in CARD_KINDS:
            out.append({"block": i, "what": WHAT_CARD, "start": s, "end": e, "src": None})
        elif ak == "still" and not _is_video_frame(asset, b, i, degraded):
            out.append({"block": i, "what": WHAT_PICTURE, "start": s, "end": e,
                        "src": asset.get("src")})
        elif ak == "sequence":
            t = s
            for c in asset.get("cuts") or []:
                sec = _f(c.get("seconds")) or 0.0
                if (c.get("kind") == "still" and not c.get("held_frame")
                        and not Path(str(c.get("src") or "")).name.startswith(DEGRADED_PREFIX)):
                    out.append({"block": i, "what": WHAT_PICTURE, "start": t,
                                "end": min(e, t + sec), "src": c.get("src")})
                t += sec
        for h in stretched_at.get(i, []):
            out.append({"block": i, "what": WHAT_HELD, "start": h["start"],
                        "end": h["end"], "src": h["src"], "ratio": h["entry"]["ratio"]})
    card = plan.get("end_card") or {}
    if card and card.get("variant") != END_CARD_CLIP:
        a, sec = _f(card.get("start_s")), _f(card.get("seconds"))
        if a is not None and sec:
            out.append({"block": None, "what": WHAT_END_CARD, "start": a, "end": a + sec,
                        "src": card.get("logo_path")})
    return out


def _union_seconds(ranges):
    total, cur_a, cur_z = 0.0, None, None
    for a, z in sorted(ranges):
        if cur_z is None or a > cur_z:
            if cur_z is not None:
                total += cur_z - cur_a
            cur_a, cur_z = a, z
        else:
            cur_z = max(cur_z, z)
    if cur_z is not None:
        total += cur_z - cur_a
    return total


def running_time(plan):
    """The composition's length (end card included), else the last block's end."""
    dur = plan.get("duration")
    if isinstance(dur, dict):
        v = _f(dur.get("composition")) or _f((dur.get("narration") or {}).get("total_seconds"))
        if v:
            return v
    elif _f(dur):
        return _f(dur)
    ends = [_f(b.get("end")) for b in plan.get("blocks") or []]
    ends = [x for x in ends if x is not None]
    return max(ends) if ends else None


def measure(plan, threshold=DEFAULT_MAX_SHARE, shots_of=None):
    """The record: share, seconds, the blocks and spans behind it, the line,
    and every held frame with its stretch (`held`). `shots_of` - a
    `shot_reader()`; the pool's by default (a stamped plan needs none)."""
    if shots_of is None:
        shots_of = shot_reader()
    held = held_frames(plan, shots_of)
    sp = spans(plan, held=held)
    total = running_time(plan)
    seconds = _union_seconds([(x["start"], x["end"]) for x in sp])
    share = round(seconds / total, 4) if total else None
    blocks = sorted({x["block"] for x in sp if x["block"] is not None})
    extra = spans(plan, held=held, stretched=True)
    extra = [x for x in extra if x["what"] == WHAT_HELD]
    soft_seconds = _union_seconds([(x["start"], x["end"]) for x in sp + extra])
    soft = round(soft_seconds / total, 4) if total else None
    pp = round((soft - STRETCHED_FROM) * 100, 1) if soft is not None else 0.0
    return {"schema": SCHEMA, "share": share, "picture_seconds": round(seconds, 3),
            "running_seconds": round(total, 3) if total else None,
            "threshold": threshold, "soft_from": soft_from(),
            "over": bool(share is not None and share > threshold),
            "blocks": blocks,
            "spans": [_rounded(x) for x in sp],
            # the soft share: pictures (a) + stretched held frames
            "stretched": {
                "rule": RULE_STRETCHED, "share": soft,
                "seconds": round(soft_seconds, 3), "from": STRETCHED_FROM,
                "pp_over": max(0.0, pp),
                "penalty": round(-min(STRETCHED_CAP, max(0.0, pp) * STRETCHED_PRICE), 2) or 0.0,
                "min_ratio": STRETCH_MIN_RATIO, "min_seconds": STRETCH_MIN_SECONDS,
                "spans": [_rounded(x) for x in extra]},
            "held": [h["entry"] for h in held]}


# ---------------------------------------------------------------- CF-0480

POOL_TASK = "CF-0480"
# Item 4: one source behind every held frame - its own line of the score log,
# priced only once the root's table carries the row (`_score.has_rule`), a
# note until then. vanguards-doomsday 1313Z (refused) and paper-dragon 1722Z
# (accepted) both hold frames off one upload only, so the line is a fact for
# the user to price, not a defect this task can price: proposed at 0.
RULE_ONE_SOURCE = "score.held_one_source"
PROPOSED_ONE_SOURCE = {"price": 0, "per": "video", "cap": None, "hook_mult": None}


def _shot_of(plan, block, cut):
    b = (plan.get("blocks") or [])[block]
    holder = b if cut is None else ((b.get("asset") or {}).get("cuts") or [])[cut]
    shot = holder.get("shot") or b.get("shot")
    return shot if isinstance(shot, str) and ":" in shot else None


def held_sources(plan, held=None, shots_of=None):
    """CF-0480 item 4: whose frames the video holds - `{"sources": {id:
    seconds}, "held_seconds", "stretched_seconds", "one_source": id | None}`,
    seconds on screen of every held frame (stretched or not); `one_source`
    when a single upload is behind all of them. A frame whose shot is not
    named counts under None and is never "one source"."""
    held = held_frames(plan, shots_of) if held is None else held
    sources, total, stretched_s = {}, 0.0, 0.0
    for h in held:
        shot = _shot_of(plan, h["block"], h["cut"])
        src = shot.rsplit(":", 1)[0] if shot else None
        sec = max(0.0, h["end"] - h["start"])
        sources[src] = round(sources.get(src, 0.0) + sec, 3)
        total += sec
        if h["entry"]["counted"]:
            stretched_s += sec
    named = [k for k in sources if k is not None]
    one = named[0] if len(sources) == 1 and named else None
    return {"rule": RULE_ONE_SOURCE, "task": POOL_TASK,
            "sources": {str(k): v for k, v in sources.items()},
            "held_seconds": round(total, 3),
            "stretched_seconds": round(stretched_s, 3), "one_source": one}


def describe_sources(rec):
    """`held frames: 16.90 s, all off one source xe3qx0kXArA (stretched 16.90 s)`."""
    if not rec.get("held_seconds"):
        return "held frames: none"
    if rec.get("one_source"):
        return (f"held frames: {rec['held_seconds']:.2f} s, all off one source "
                f"{rec['one_source']} (stretched {rec['stretched_seconds']:.2f} s) "
                f"({RULE_ONE_SOURCE})")
    parts = ", ".join(f"{k} {v:.2f} s" for k, v in sorted(
        rec["sources"].items(), key=lambda kv: -kv[1]))
    return f"held frames: {rec['held_seconds']:.2f} s from {len(rec['sources'])} sources ({parts})"


def one_source_findings(rec):
    """The line of the score log - only once the table prices it."""
    if not rec.get("one_source") or not rec.get("held_seconds") \
            or not _priced(RULE_ONE_SOURCE):
        return []
    return [_score.finding(RULE_ONE_SOURCE, {}, units=1, source="metric",
                           note=describe_sources(rec))]


# Item 3: the pool does not hold the video. A one-frame block the resolver
# wanted to cut into 2-3 shots of its phrase and could not
# (`stretch_split.short`, resolve_anchors.py) is the pool's shortage, not the
# montage's choice; when such blocks leave the video over the stretched line
# (pictures + stretched held frames over 50 %), the plan says "the pool does
# not hold this video" - gate `pool_holds_video`, funnel `pool_too_thin`, the
# topic's supplement request named. A new refusal: priced on the replay of
# 1313Z + 1722Z (CF-0320) and a WARNING until the user signs it.
POOL_GATE = "pool_holds_video"
POOL_SHORT = "short"
POOL_HOLDS = "holds"


def pool_holds(plan, rec):
    """`{"task", "verdict": holds|short, "share", "from", "blocks": [...]}`:
    the blocks the resolver could not split (`stretch_split.short`) and the
    stretched share they leave. `short` only when there are such blocks and
    the share is over `STRETCHED_FROM`."""
    st = (rec or {}).get("stretched") or {}
    blocks = []
    for i, b in enumerate(plan.get("blocks") or []):
        sp = b.get("stretch_split") or {}
        if sp.get("short"):
            blocks.append({"block": i, "shot": b.get("shot"), "need": sp.get("need"),
                           "shot_seconds": sp.get("first_shot_seconds"),
                           "ratio": sp.get("ratio")})
    split = sum(1 for b in plan.get("blocks") or []
                if (b.get("stretch_split") or {}).get("got", 0) >= 2)
    share = st.get("share")
    short = bool(blocks) and share is not None and share > STRETCHED_FROM
    return {"task": POOL_TASK, "gate": POOL_GATE,
            "verdict": POOL_SHORT if short else POOL_HOLDS,
            "share": share, "from": STRETCHED_FROM, "split_blocks": split,
            "short_blocks": blocks}


def describe_pool(rec):
    blocks = ", ".join(f"block {x['block']} {x['shot']} {x['shot_seconds']} s for "
                       f"{x['need']} s (x{x['ratio']})" for x in rec["short_blocks"])
    return (f"the pool does not hold this video: {_pct(rec['share'])} % of it stands "
            f"still in pictures and stretched held frames (over {_pct(rec['from'])} %), "
            f"and {len(rec['short_blocks'])} one-frame block(s) had no second shot of "
            f"their phrase to cut to ({blocks}); {rec['split_blocks']} block(s) were cut "
            f"into 2-3 shots (CF-0480)")


def _rounded(x):
    return {**x, "start": round(x["start"], 3), "end": round(x["end"], 3),
            "seconds": round(x["end"] - x["start"], 3)}


ANCHORED = (WHAT_PICTURE, WHAT_CARD)   # a block's own picture: an anchor chose it


def fixable_by_anchors(rec):
    """CF-0428's question for this refusal: True when the pictures the anchors
    chose (a block's own picture or card) are enough to bring the share to the
    line if they became moving shots; None otherwise - the rest is a proof card
    and memes, which the script's fact beat and meme requests place, not its
    anchors. Never False: a writer can always drop a meme request."""
    total = rec.get("running_seconds")
    if not rec.get("over") or not total:
        return None
    rest = _union_seconds([(x["start"], x["end"]) for x in rec.get("spans") or []
                           if x["what"] not in ANCHORED])
    return True if rest / total <= rec["threshold"] else None


def _pct(x):
    return round(x * 100, 1)


def describe(rec):
    """`30.7 % (13.32 of 43.39 s): block 5 proof 5.38 s, block 6 meme 7.94 s`."""
    head = (f"{_pct(rec['share'])} % ({rec['picture_seconds']:.2f} of "
            f"{rec['running_seconds']:.2f} s)") if rec.get("share") is not None else "no length"
    parts = [f"{'end card' if x['block'] is None else 'block ' + str(x['block'])} "
             f"{x['what']}{' x' + str(x['ratio']) if x.get('ratio') else ''} "
             f"{x['seconds']:.2f} s" for x in rec.get("spans") or []]
    return head + (": " + ", ".join(parts) if parts else ": no pictures")


def describe_stretched(rec):
    """`88.1 % with stretched held frames (38.1 p.p. over 50 %): block 0
    held_frame x6.06 5.82 s, ...` - the soft share and what it adds."""
    st = rec.get("stretched") or {}
    if st.get("share") is None:
        return "no length"
    parts = [f"block {x['block']} held_frame x{x.get('ratio')} {x['seconds']:.2f} s"
             for x in st.get("spans") or []]
    return (f"{_pct(st['share'])} % with stretched held frames ({st['pp_over']} p.p. over "
            f"{_pct(st['from'])} %)" + (": " + ", ".join(parts) if parts else ""))


def _priced(rule):
    """The rule is in the root's price table (a finding it does not price
    would stop the whole log - score.ScoreModelError)."""
    return _score.has_rule(rule)


def findings(rec):
    """The score findings of the record: the hard line above the channel's
    threshold, else the soft per-p.p. rule above 25 % (both variant (a));
    and, on its own, `score.stretched_still_share` - p.p. of pictures +
    stretched held frames over 50 % - once the price table carries it."""
    share = rec.get("share")
    if share is None:
        return []
    pct = _pct(share)
    out = []
    if rec.get("over"):
        out.append(_score.finding(RULE_HARD, {}, source="metric",
                                  note=f"{pct} % of the running time in pictures, over "
                                       f"{_pct(rec['threshold'])} % - {describe(rec)}"))
    else:
        pp = round((share - rec.get("soft_from", SOFT_FROM)) * 100, 1)
        if pp > 0:
            out.append(_score.finding(RULE_SOFT, {}, units=pp, source="metric",
                                      note=f"{pct} % in pictures: {pp} p.p. over "
                                           f"{_pct(rec.get('soft_from', SOFT_FROM))} %"))
    st = rec.get("stretched") or {}
    if (st.get("pp_over") or 0) > 0 and _priced(RULE_STRETCHED):
        out.append(_score.finding(RULE_STRETCHED, {}, units=st["pp_over"], source="metric",
                                  note=describe_stretched(rec)))
    return out


def report_lines(rec):
    lines = [f"{_pct(rec['share'])} % of the running time is pictures (cards, posters, "
             f"proof cards, whole-frame memes), over the channel's "
             f"{_pct(rec['threshold'])} % (video_editor.{CONFIG_KEY})",
             describe(rec),
             "held frames of a video and moving footage are not in this share (the "
             "user, 2026-09-30; stretched held frames are priced apart, "
             f"{RULE_STRETCHED}): move anchors onto moving shots, or drop a picture insert"]
    return lines


def deficit_path(plan_output):
    p = Path(plan_output)
    return p.with_name(p.stem + DEFICIT_SUFFIX)


def write_deficit(plan_output, rec):
    path = deficit_path(plan_output)
    try:
        path.write_text(json.dumps({"still_share": rec}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    except OSError:
        return None
    return str(path)


def main(argv=None):
    """`still_share.py PLAN [--max 0.5]` - the record of a written plan."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan")
    ap.add_argument("--max", type=float, default=DEFAULT_MAX_SHARE)
    a = ap.parse_args(argv)
    rec = measure(json.loads(Path(a.plan).read_text()), a.max)
    print(("OVER " if rec["over"] else "ok   ") + describe(rec))
    st = rec["stretched"]
    print(("COST " if st["pp_over"] > 0 else "ok   ") + describe_stretched(rec)
          + (f" -> {st['penalty']:g} ({RULE_STRETCHED})" if st["pp_over"] > 0 else ""))
    return 1 if rec["over"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
