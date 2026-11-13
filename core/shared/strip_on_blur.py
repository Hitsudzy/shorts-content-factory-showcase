#!/usr/bin/env python3
"""CF-0878: how long a video shows its picture as a narrow strip on its blurred
ground - read off the plan's geometry, summed over the whole video.

The user's refusal `narrow_strip_on_blur` («узкая полоса картинки на размытом
фоне») is about how much of the video the strip takes: wildwood 0840Z «примерно
70-80 % времени», carrie 0840Z «в половине ролика», the-gilded-age 0836Z «~10 с»,
resident-dread 0836Z «8 с». The two checks there were both look at one picture
at a time:

* `score.thin_picture` (agents/video-editor/scripts/held_screen.py, CF-0646 /
  CF-0650, signed 2026-10-09) charges a block or a cut under 25 % of the
  screen's height held still, or moving for 3 s or more, or under 33 % when a
  clip of 3 s or more stands nearly still. Each piece is read alone, so a
  strip cut into pieces under 3 s - the-gilded-age 0836Z: six 16:9 pieces
  (0.317 of the height) of 0.96-2.49 s, two of them back to back, 10.2 s in all
  - costs nothing, and a moving 16:9 strip never does.
* the frame judge's `thin_strip` (SKILL step 4a, hard list) is a still sliver
  under about a quarter of the height: two tiles of one entry, never the time
  the strip takes over the video.

This module is the missing reading: every picture of the plan (a block's
asset, a sequence's cut, a held frame) shown whole on its blurred frame or
`contain`-fitted under `STRIP_SHARE` of the screen's height, moving or not,
merged into runs where they follow each other, and summed. Pictures under an
opaque card (a proof or a meme fitted whole on its black box) are not on
screen and are not counted; a cut-out meme sits on the picture and is.

`STRIP_SHARE` is held_screen's `STILL_SHARE` (0.33, signed with CF-0650):
16:9 shown whole reads 0.317, 2:1 0.281, 2.39:1 0.235; 5:3 (0.338) is over it.

The seconds `score.thin_picture` already charges (the plan's
`held_screen.findings`) are counted in the reading and left out of the price,
so one strip is never charged twice.

**The price: signed by the user on 2026-10-27 (CF-0320).** `score.narrow_strip_on_blur`
(-2 per second over 5 s, cap 30) stands in `shared/gate-prices.json#rules`;
the frame judge's gate (scripts/frame_judge_gate.py) records this reading on
every video and charges it at the judge stage while the row is in `rules` (a
table without it - the row back in `proposals` - only records it).

    python3 shared/strip_on_blur.py PLAN.json ...        the reading of each plan
    python3 shared/strip_on_blur.py --replay [--since 2026-10-10] [--root R]
        every rendered plan of the window beside its score after the judge and
        the user's answer (publish/acceptance-log.json), with what the proposed
        price would do
"""
import json
import sys
from pathlib import Path

TASK = "CF-0878"
RULE = "score.narrow_strip_on_blur"
SCREEN = (1080, 1920)
STRIP_SHARE = 0.33       # held_screen.STILL_SHARE: 16:9 shown whole is 0.317
ALLOW_SECONDS = 5.0      # strip time a video may carry before it is charged
JOIN_GAP = 0.05          # pieces closer than this are one run
THIN_RULE = "score.thin_picture"
CUTOUT_PLACEMENTS = ("cutout_on_subject", "cutout_in_corner")
# Proposed by CF-0878, signed by the user 2026-10-27: per second of strip
# over ALLOW_SECONDS that score.thin_picture does not already charge.
PROPOSED = {"price": 2, "per": "second", "cap": 30, "hook_mult": None,
            "allow_seconds": ALLOW_SECONDS}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def picture_share(target, screen=SCREEN):
    """The picture's height on screen over the screen's: a `blur_fill` rect's
    height, a `contain` picture fitted whole, 1.0 for a cover crop and for a
    target the plan does not size (held_screen.picture_share)."""
    target = target or {}
    rect = ((target.get("presentation") or {}).get("blur_fill") or {}).get("rect")
    if isinstance(rect, dict) and _f(rect.get("height")):
        return round(min(1.0, _f(rect["height"]) / screen[1]), 3)
    if target.get("fit") == "contain":
        ss = target.get("source_size") or {}
        w, h = _f(ss.get("width")), _f(ss.get("height"))
        if w and h:
            s = min(screen[0] / w, screen[1] / h)
            return round(min(1.0, h * s / screen[1]), 3)
    return 1.0


def hidden(block):
    """True when the block's own picture is not on screen: an insert fitted
    whole on its opaque box (a proof, a meme that is not a cutout)."""
    ins = (block or {}).get("insert")
    if not isinstance(ins, dict) or not ins:
        return False
    return ins.get("placement") not in CUTOUT_PLACEMENTS


def pieces(plan):
    """Every picture on screen: `(block, cut, start, end, target)` - a block's
    asset, or each cut of a sequence over its own seconds."""
    for i, b in enumerate((plan or {}).get("blocks") or []):
        s, e = _f(b.get("start")), _f(b.get("end"))
        if s is None or e is None or e <= s:
            continue
        a = b.get("asset") or {}
        cuts = a.get("cuts") if a.get("kind") == "sequence" else None
        if cuts:
            t = s
            for ci, c in enumerate(cuts):
                end = min(e, t + (_f(c.get("seconds")) or 0.0))
                if end > t:
                    yield i, ci, t, end, c
                t = end
        else:
            yield i, None, s, e, a


def _charged_thin(plan):
    """(block, cut) of the pictures score.thin_picture already finds."""
    out = set()
    for f in ((plan or {}).get("held_screen") or {}).get("findings") or []:
        if isinstance(f, dict) and f.get("rule") == THIN_RULE:
            out.add((f.get("block"), f.get("cut")))
    return out


def reading(plan, share_below=STRIP_SHARE, allow=ALLOW_SECONDS):
    """The plan's strip time: `{"task", "share_below", "seconds", "video_seconds",
    "share_of_video", "longest", "runs": [{"start", "end", "seconds", "pieces"}],
    "thin_charged_seconds", "uncharged_seconds", "allow_seconds", "over_seconds"}`.
    `over_seconds` is what the proposed price counts: the strip seconds
    score.thin_picture does not charge, past `allow`."""
    blocks = (plan or {}).get("blocks") or []
    thin = _charged_thin(plan)
    strips = []
    for i, ci, s, e, target in pieces(plan):
        if hidden(blocks[i]):
            continue
        share = picture_share(target)
        if share < share_below:
            strips.append({"block": i, "cut": ci, "start": round(s, 3), "end": round(e, 3),
                           "share": share, "thin_charged": (i, ci) in thin})
    runs = []
    for x in strips:
        if runs and x["start"] - runs[-1]["end"] <= JOIN_GAP:
            runs[-1]["end"] = x["end"]
            runs[-1]["pieces"].append(x)
        else:
            runs.append({"start": x["start"], "end": x["end"], "pieces": [x]})
    for r in runs:
        r["seconds"] = round(r["end"] - r["start"], 3)
    total = round(sum(x["end"] - x["start"] for x in strips), 3)
    charged = round(sum(x["end"] - x["start"] for x in strips if x["thin_charged"]), 3)
    video = _f(((plan or {}).get("audio") or {}).get("duration")) or \
        max([_f(b.get("end")) or 0.0 for b in blocks] or [0.0])
    uncharged = round(total - charged, 3)
    return {"task": TASK, "rule": RULE, "share_below": share_below,
            "seconds": total, "video_seconds": round(video, 3),
            "share_of_video": round(total / video, 3) if video else None,
            "longest": max((r["seconds"] for r in runs), default=0.0),
            "runs": runs, "thin_charged_seconds": charged,
            "uncharged_seconds": uncharged, "allow_seconds": allow,
            "over_seconds": round(max(0.0, uncharged - allow), 3)}


def line(rec):
    """One line for the operator's report."""
    if not rec or not rec.get("seconds"):
        return "no picture as a strip on its blurred ground"
    runs = ", ".join(f"{r['start']:g}-{r['end']:g}s" for r in rec["runs"][:6])
    more = f" +{len(rec['runs']) - 6}" if len(rec["runs"]) > 6 else ""
    pct = f" ({rec['share_of_video']:.0%} of the video)" if rec.get("share_of_video") else ""
    return (f"{rec['seconds']:g} s as a strip under {rec['share_below']:.0%} of the height"
            f"{pct}, longest {rec['longest']:g} s [{runs}{more}]; "
            f"{rec['over_seconds']:g} s over the {rec['allow_seconds']:g} s allowance "
            f"not charged by {THIN_RULE}")


def finding(rec, score_model):
    """The score finding of the price for `rec` (units = seconds over the
    allowance), or None when there is nothing over it."""
    if not rec or not rec.get("over_seconds"):
        return None
    first = rec["runs"][0]["start"] if rec.get("runs") else None
    return score_model.finding(RULE, {"t": first} if first is not None else {},
                               units=rec["over_seconds"], hook=False, source="metric",
                               note=note(rec))


def note(rec):
    """The finding's note - one fixed shape, so score.NOTE_TEMPLATES says it
    in Russian (CF-0751)."""
    return (f"{rec['seconds']:g} s as a strip under {rec['share_below']:.0%} of the "
            f"screen's height, longest {rec['longest']:g} s, {rec['over_seconds']:g} s over "
            f"{rec['allow_seconds']:g} s ({TASK})")


def proposed_row():
    """The row this task proposed for `shared/gate-prices.json#proposals`
    (signed 2026-10-27 and moved to `rules` with the user's signature)."""
    return {"what": "video", "mode": "penalty", "penalty": dict(PROPOSED),
            "detector": "auto", "signature": None}


# ------------------------------------------------------------------ replay

def _acceptance(root):
    try:
        d = json.loads((root / "publish" / "acceptance-log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {a.get("entry_id"): a for a in d.get("acceptances") or [] if isinstance(a, dict)}


def _judged(root, since):
    """{entry_id: 06 row} of every judged video of the window."""
    out = {}
    for p in sorted((root / "pipeline").glob("*/*/06-frame-judge.json")):
        ch, batch = p.parent.parent.name, p.parent.name
        if batch < since:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in d.get("videos") or []:
            if isinstance(v, dict) and v.get("slug"):
                out[f"{ch}/{batch}/{v['slug']}"] = v
    return out


def replay(root, since="2026-10-10", price=None, cap=None, allow=None):
    """Rows `{id, reading, score, gate, after, answer}` for every judged video
    of the window: its strip reading, its score after the judge, and its score
    with the proposed price added (read-only)."""
    price = PROPOSED["price"] if price is None else price
    cap = PROPOSED["cap"] if cap is None else cap
    allow = ALLOW_SECONDS if allow is None else allow
    acc = _acceptance(root)
    rows = []
    for eid, v in _judged(root, since).items():
        ch, batch, slug = eid.split("/")
        plan_p = root / "pipeline" / ch / batch / "work" / slug / "plan.json"
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rec = reading(plan, allow=allow)
        sc = v.get("score") if isinstance(v.get("score"), dict) else {}
        pts = _f(sc.get("score"))
        cost = min(cap, price * rec["over_seconds"])
        a = acc.get(eid) or {}
        rows.append({"id": eid, "reading": rec, "score": pts, "threshold": sc.get("threshold"),
                     "gate": v.get("gate"), "reason_code": v.get("reason_code"),
                     "after": None if pts is None else round(pts - cost, 2),
                     "answer": a.get("verdict"), "answer_code": a.get("reason_code"),
                     "answer_reason": a.get("reason")})
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plans", nargs="*")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--since", default="2026-10-10")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--price", type=float)
    ap.add_argument("--cap", type=float)
    ap.add_argument("--allow", type=float)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.replay:
        rows = replay(Path(a.root), a.since, a.price, a.cap, a.allow)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        for r in sorted(rows, key=lambda r: -r["reading"]["seconds"]):
            rec = r["reading"]
            if not rec["seconds"]:
                continue
            print(f"{r['id'][:56]:56} strip {rec['seconds']:5.2f}s "
                  f"({(rec['share_of_video'] or 0):4.0%}) longest {rec['longest']:5.2f} "
                  f"over {rec['over_seconds']:5.2f} | {r['gate']}/{r['reason_code'] or '-'} "
                  f"{r['score']} -> {r['after']} | user: {r['answer'] or '-'}"
                  f"{'/' + r['answer_code'] if r['answer_code'] else ''}")
        return 0
    for p in a.plans:
        rec = reading(json.loads(Path(p).read_text(encoding="utf-8")))
        print(json.dumps(rec, ensure_ascii=False) if a.json else f"{p}: {line(rec)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
