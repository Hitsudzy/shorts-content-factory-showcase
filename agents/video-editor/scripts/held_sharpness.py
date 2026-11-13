#!/usr/bin/env python3
"""CF-0465: a soft frame held still - `score.held_soft_frame`.

The user rejected kaijura-minus-zero of `example-film/2026-09-30T1248Z`
(`blurry_footage`, "много смазанного материала") and decided on 2026-10-01
(B2+B3) that the smear is not soft footage in motion but a soft frame stopped
and held. The share of held frames is not what tells it (paper-dragon
`2026-09-23T1722Z` holds all its 8 blocks and was accepted -
`score.stretched_still_share` stays as it is); the sharpness of the frame
that is held is.

**The measure.** The frame the render holds is the `held_frame` still the
resolver lifted out of its clip (`clips/sNN_held_*.png`, a sequence's held
cut, a clip degraded to its frame) - the very picture, not the shot it came
from. It is read with the indexer's own focus measure
(`footage-indexer/scripts/sharpness.py`, `frame_sharpness`: blur effect of
Crete et al. 2007 per tile, the 90th percentile of the tiles - CF-0452), on
the whole held picture, with no motion excuse (a held frame does not move).
The value is stamped onto the block / cut (`held_sharpness`) while the PNG
is there, so the plan answers after the clips are gone (CF-0358).

**The floor, read off the measure (2026-10-01, all 19 plans of the
acceptance log that hold frames, 112 held frames).** No reading of the held
frame separates the rejected video from the accepted ones as a whole: the
held frames of kaijura 1248Z read 0.518-0.669, paper-dragon's 0.541-0.769,
all accepted 0.536-0.900 (and the same holds for the 9:16 window the render
shows, at source or screen scale, the tile median, Laplacian, gradient,
high-frequency share, motion at the held moment and smear direction - see
the task's report). What is under every accepted held frame is one frame:
kaijura's block 6, `xiEmt197Bk8:41`, 0.518 held 5.10 s (the same frame
held 5.86 s in the rejected kaijura of `rebuilds/2026-09-27T1757Z`). The
floor `FLOOR` sits between it and the softest accepted held frame
(primetime 2210Z block 14, 0.536; paper-dragon block 2, 0.541).

**The price: none until the user signs one (CF-0320).** `mode()` reads
`shared/gate-prices.json`: only a row `score.held_soft_frame` with the user's
`signature` makes it a penalty (per second of the soft frame on screen, the
row's price and cap - the score model charges); without it the record says
`warn`, the plan carries it in `held_sharpness` and a note, and nothing is
charged. `PROPOSED` is what the report proposes; this repo never writes the
row.

Stdlib + the indexer's module (numpy through it); without the indexer
nothing is measured and nothing is found.
"""
import json
from pathlib import Path

import still_share

TASK = "CF-0465"
RULE = "score.held_soft_frame"
FIELD = "held_sharpness"            # on the block / the cut that holds
MEASURED_BY = "CF-0465/held-png/crete-tiles-p90/v1"
FLOOR = 0.53
# The proposal (unsigned): per second of a soft held frame on screen. At 5 /
# cap 30 kaijura 1248Z's editor score goes 83.75 -> 58.25 (F under 60); no
# accepted video of the log loses a point.
PROPOSED = {"price": 5, "per": "second", "cap": 30, "hook_mult": None}

MODE_PENALTY = "penalty"
MODE_WARN = "warn"
PRICES_REL = Path("shared") / "gate-prices.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ the measure

def _sharpness():
    try:
        import shot_score
        return shot_score.sharpness_module()
    except Exception:  # noqa: BLE001 - no indexer: nothing measured
        return None


def frame_value(path):
    """The indexer's frame sharpness of the picture at `path` (a PNG / JPG,
    or the first frame of a video), or None when it cannot be read or says
    nothing about focus (a flat card)."""
    mod = _sharpness()
    if mod is None or not path or not Path(path).exists():
        return None
    try:
        got = mod.read_frames(str(path), [0.0], pairs=False)
        frame = next(iter(got.values()))[0] if got else None
        return mod.frame_sharpness(frame)[0] if frame is not None else None
    except Exception:  # noqa: BLE001 - an unreadable picture measures nothing
        return None


def _holder(plan, h):
    b = plan["blocks"][h["block"]]
    return b if h["cut"] is None else b["asset"]["cuts"][h["cut"]]


def _resolve(src, base):
    """The held picture's path: as written, else beside the plan in `clips/`
    (a plan moved with its work dir)."""
    if not src:
        return None
    p = Path(src)
    if p.exists() or base is None:
        return p
    q = Path(base) / "clips" / p.name
    return q if q.exists() else p


def _no_pool(_key):
    return None


def stamp(plan, measure=None, base=None):
    """Write `held_sharpness` onto every held frame of the plan that has no
    record of this measure yet: `{"task", "measured_by", "value", "src"}`.
    `measure(path) -> value|None` is `frame_value` by default; `base` - the
    plan's work dir, where `clips/` lies. Returns how many were stamped."""
    measure = measure or frame_value
    n = 0
    for h in still_share.held_frames(plan, _no_pool):
        holder = _holder(plan, h)
        rec = holder.get(FIELD)
        if isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY:
            continue
        path = _resolve(h["src"], base)
        holder[FIELD] = {"task": TASK, "measured_by": MEASURED_BY,
                         "value": measure(str(path)) if path else None,
                         "src": str(path) if path else None}
        n += 1
    return n


def record(plan, floor=FLOOR, measure=None):
    """The record of the plan's held frames:

        {"rule", "floor", "frames": [{"block", "cut", "start", "end",
          "seconds", "value", "soft"}], "soft_seconds", "units",
          "proposed": {...}, "proposed_penalty"}

    A frame without a stamp is measured now (`measure`, `frame_value` by
    default) and not written back - `stamp()` writes. `seconds` is the held
    span on screen; `soft` when the value is under `floor`."""
    measure = measure or frame_value
    frames = []
    for h in still_share.held_frames(plan, _no_pool):
        rec = _holder(plan, h).get(FIELD)
        if isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY:
            value = rec.get("value")
        else:
            value = measure(h["src"]) if h["src"] else None
        sec = round(max(0.0, h["end"] - h["start"]), 3)
        frames.append({"block": h["block"], "cut": h["cut"],
                       "start": round(h["start"], 3), "end": round(h["end"], 3),
                       "seconds": sec, "value": value,
                       "soft": bool(isinstance(value, (int, float)) and value < floor)})
    soft = round(sum(x["seconds"] for x in frames if x["soft"]), 3)
    return {"task": TASK, "rule": RULE, "floor": floor, "frames": frames,
            "soft_seconds": soft, "units": round(soft, 2),
            "proposed": dict(PROPOSED),
            "proposed_penalty": round(-min(PROPOSED["cap"], soft * PROPOSED["price"]), 2) or 0.0}


# ------------------------------------------------------------- the price

def _signed(row):
    sig = (row or {}).get("signature")
    return isinstance(sig, dict) and bool(sig.get("user")) and bool(sig.get("date"))


def prices_path():
    try:
        import _score
        root = _score.factory_root()
    except Exception:  # noqa: BLE001
        root = None
    return root / PRICES_REL if root else None


def mode(path=None):
    """`{"mode": penalty|warn, "price", "cap", "signed"}` - what the price
    table says about `score.held_soft_frame`. Only a row with the user's
    `signature` and a numeric price counts; anything else is `warn`."""
    path = path or prices_path()
    rules = {}
    if path:
        try:
            rules = (json.loads(Path(path).read_text()) or {}).get("rules") or {}
        except (OSError, ValueError, AttributeError):
            rules = {}
    row = rules.get(RULE)
    out = {"mode": MODE_WARN, "price": None, "cap": None, "signed": False}
    if _signed(row):
        pen = row.get("penalty") or {}
        price = pen.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out = {"mode": MODE_PENALTY, "price": price, "cap": pen.get("cap"),
                   "signed": True}
    return out


def findings(rec, mode_rec=None):
    """One score finding per soft held frame (units = its seconds on
    screen) - only in `penalty` mode; `[]` while the row is not signed."""
    mode_rec = mode_rec or mode()
    if mode_rec.get("mode") != MODE_PENALTY:
        return []
    try:
        import _score
    except Exception:  # noqa: BLE001
        return []
    out = []
    for x in rec.get("frames") or []:
        if not x["soft"]:
            continue
        out.append(_score.finding(
            RULE, {"block": x["block"], **({"cut": x["cut"]} if x["cut"] is not None else {}),
                   "t": x["start"]},
            units=x["seconds"], hook=_score.in_hook(x["start"]), source="metric",
            note=(f"block {x['block']}{'' if x['cut'] is None else ' cut ' + str(x['cut'])}: "
                  f"held frame sharpness {x['value']} under {rec['floor']} for "
                  f"{x['seconds']:.2f} s (CF-0465)")))
    return out


def describe(rec, mode_rec=None):
    """`held soft frames: 5.10 s under 0.53 (block 6 0.518 5.10 s) - warn,
    would cost -25.5 at the proposed 5/s cap 30`."""
    soft = [x for x in rec.get("frames") or [] if x["soft"]]
    if not soft:
        return (f"held frames: none under {rec['floor']} "
                f"({len(rec.get('frames') or [])} held)")
    parts = ", ".join(f"block {x['block']}{'' if x['cut'] is None else '.' + str(x['cut'])} "
                      f"{x['value']} {x['seconds']:.2f} s" for x in soft)
    m = (mode_rec or {}).get("mode", MODE_WARN)
    tail = ("charged per second at the signed price" if m == MODE_PENALTY else
            f"warn (unsigned), would cost {rec['proposed_penalty']:g} at the proposed "
            f"{PROPOSED['price']}/s cap {PROPOSED['cap']}")
    return (f"held soft frames: {rec['soft_seconds']:.2f} s under {rec['floor']} "
            f"({parts}) - {tail} ({RULE})")


def proposed_row():
    """The row this task proposes for `shared/gate-prices.json` - unsigned."""
    return {"what": "block", "mode": "penalty", "penalty": dict(PROPOSED),
            "detector": "auto",
            "note": (f"CF-0465: a soft frame held still - the held_frame picture the "
                     f"render holds (clips/sNN_held_*.png, a held cut, a clip degraded "
                     f"to its frame) reads under {FLOOR} on the indexer's frame "
                     f"sharpness (blur effect, p90 of tiles; footage-indexer/scripts/"
                     f"sharpness.py), no motion excuse; per second it stands on screen. "
                     f"Plan stage, agents/video-editor/scripts/held_sharpness.py. "
                     f"Measured 2026-10-01 on the acceptance log: kaijura 1248Z 5.10 s "
                     f"(xiEmt197Bk8:41 at 0.518), no accepted video under it (softest "
                     f"accepted held frame 0.536)."),
            "signature": None}


def main(argv=None):
    """`held_sharpness.py PLAN [--floor 0.53] [--row]` - the record of a plan."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--floor", type=float, default=FLOOR)
    ap.add_argument("--row", action="store_true", help="print the proposed price row")
    a = ap.parse_args(argv)
    if a.row:
        print(json.dumps({RULE: proposed_row()}, ensure_ascii=False, indent=2))
        return 0
    if not a.plan:
        ap.error("PLAN is required")
    plan = json.loads(Path(a.plan).read_text())
    base = Path(a.plan).parent

    def measure(src):
        p = _resolve(src, base)
        return frame_value(str(p)) if p else None
    rec = record(plan, a.floor, measure)
    for x in rec["frames"]:
        print(f"  block {x['block']:>2} cut {str(x['cut']):>4} {x['seconds']:5.2f} s "
              f"{x['value']} {'SOFT' if x['soft'] else ''}")
    print(describe(rec, mode()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
