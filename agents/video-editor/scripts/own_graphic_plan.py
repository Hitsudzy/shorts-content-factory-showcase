#!/usr/bin/env python3
"""CF-0689: the plan's side of `own_graphic` - a graphic the factory draws
itself in Remotion from the script's facts (ExampleTech's base footage, the
user's decision of 12.10: no rights risk, automatic, nothing invented).

The rule of what a graphic may say is the root's (`shared/own_graphic.py`,
loaded by path through `_root_shared.root_module("own_graphic")`): the six
templates, the order's shape, the values against the script's claims, the
text a template would add with nothing behind it, what the viewer reads.
This module only applies it where the editor needs it:

* `asset(graphic, graphic_id, offset, lang)` - the plan block's asset:
  `{kind: "own_graphic", graphic_id, template, data, source_label, caption,
  lang, offset_seconds}` (+ `bars` on a benchmark: each score's share of the
  largest, `bars()`). `GraphicLayer.jsx` draws `data` and `caption` and
  nothing else (the template adds no words of its own).
* `problems(graphic_id, graphic)` - the backstop at the plan: the order is
  re-checked (`order_errors`, `adds_text`) and a graphic anchor that names no
  graphic of the script's `graphics[]` is refused (`graphic_not_ordered`).
  Any finding refuses the whole plan (`plan_refusal.GATE_OWN_GRAPHIC`): a
  graphic is never drawn half-right and never swapped for footage.
* `record(plan)` - `plan["own_graphics"]`: one row per graphic on screen,
  its blocks, seconds, source line and what the viewer reads.
* `block_seconds(block)` / `seconds(plan)` - how long graphics are on
  screen; the two-source gate and the proof-quote cap count them as our own
  footage beside `own_capture`.

CF-0690 - the seventh template, `api_chat` ("a demo via API"): the topic's
model answered one of the channel's fixed prompts through its API, and the
graphic shows that REAL answer verbatim in our own chat
(`render/src/graphics/ApiChat.jsx`). Two things more than the others:

* the backstop holds it to the record of the call - `protocol_for(record_id,
  batch)` finds the protocol (the batch's `01-trend-hunter.json`, a topic's
  `api_demo_record`, else the Trend Hunter's cache
  `<batch>/work/api_demo/<record_id>.json`) and `problems(..., config,
  protocols)` runs the root's `own_graphic.chat_problems` (=
  `api_demo.chat_problems` + the date of the call) and `order_errors(graphic,
  config)` with the channel's `api_demo` block (`api_demo_config`); no
  protocol is `api_demo_no_record`, and every finding refuses the plan under
  the same own-graphic gate;
* `stamp_chat_timing(blocks)` - its clock: the prompt typed, a short think,
  the answer revealed word by word, scaled to the run of blocks the graphic
  spans so the whole answer stands for at least `HOLD_MIN` seconds before the
  run ends (`asset.chat_timing`); a run too short for that is refused
  (`api_chat_too_short`).

No credit: a graphic is not a borrowed source (`source_gate.FOOTAGE_KINDS`
does not hold the kind, so `block_sources()` is [] and no credit row or
overlay is made). Stdlib only, no network.
"""
import json
import math
import re
from pathlib import Path

from _root_shared import root_module

KIND = "own_graphic"
FIELD = "own_graphics"
DEFAULT_LANG = "en"

CODE_NOT_ORDERED = "graphic_not_ordered"
CODE_RULE_MISSING = "own_graphic_rule_missing"
CODE_ID_MISMATCH = "graphic_id_mismatch"
CODE_CHAT_TOO_SHORT = "api_chat_too_short"      # CF-0690: no 1.5 s for the whole answer

API_CHAT = "api_chat"                           # = own_graphic.API_CHAT (CF-0690)
TRENDS_FILE = "01-trend-hunter.json"
API_DEMO_WORK = Path("work") / "api_demo"       # = the Trend Hunter's fetch_api_demo.WORK_DIR
RECORD_FIELD = "api_demo_record"                # = api_demo.RECORD_FIELD
CONFIG_KEY = "api_demo"                         # the channel's footage-origin.json block

# CF-0690: the chat's clock (seconds of the graphic's own time). The prompt
# starts typing at LEAD; IDEAL_* are the unhurried lengths (= ApiChat.jsx
# defaultTiming), FLOOR_* the fastest the run may squeeze them to; the whole
# answer stands for HOLD_MIN at least before the run ends.
LEAD = 0.5
HOLD_MIN = 1.5
TYPE_CPS = 40.0
TYPE_RANGE = (0.8, 3.0)
THINK = 0.9
REVEAL_WPS = 6.0
REVEAL_RANGE = (1.0, 4.0)
FLOOR_TYPE, FLOOR_THINK, FLOOR_REVEAL = 0.4, 0.35, 0.6
RUN_TOUCH = 0.02


def rule():
    """The root's shared/own_graphic.py, or None when no copy is found."""
    return root_module("own_graphic")


def kind_of(block):
    if not isinstance(block, dict):
        return None
    asset = block.get("asset")
    return asset.get("kind") if isinstance(asset, dict) else block.get("asset_kind")


def is_own_graphic(block):
    return kind_of(block) == KIND


def block_seconds(block):
    """Seconds an own-graphic block is on screen (0.0 for any other block)."""
    if not is_own_graphic(block):
        return 0.0
    try:
        return max(0.0, float(block.get("end", 0.0)) - float(block.get("start", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _blocks(plan):
    blocks = (plan or {}).get("blocks") if isinstance(plan, dict) else plan
    return blocks if isinstance(blocks, list) else []


def seconds(plan):
    return round(sum(block_seconds(b) for b in _blocks(plan)), 3)


def lang_of(channel_cfg):
    lang = (channel_cfg or {}).get("language")
    return lang if isinstance(lang, str) and lang.strip() else DEFAULT_LANG


def problems(graphic_id, graphic, config=None, protocols=None):
    """["<code>: <detail>"] of everything that stops this graphic being
    drawn; [] when it may be.

    CF-0690: an `api_chat` is checked against `config` (the channel's
    `api_demo` block - the answer cap, the model list) and against the record
    of its call (`protocols`: {record_id: protocol}; None or no entry -
    `api_demo_no_record`)."""
    og = rule()
    if og is None:
        return [f"{CODE_RULE_MISSING}: shared/own_graphic.py of the factory root was not "
                f"found - the graphic's order cannot be checked, so it is not drawn"]
    if not isinstance(graphic, dict):
        return [f"{CODE_NOT_ORDERED}: the anchor places graphic {graphic_id!r} and the "
                f"script's `graphics[]` orders no graphic with that id - nothing is drawn "
                f"in its place"]
    chat = graphic.get("template") == API_CHAT
    out = list(og.order_errors(graphic, config=config) if chat else og.order_errors(graphic))
    if chat and not out:
        out += [f"{p.get('code')}: {p.get('detail')}"
                for p in og.chat_problems(graphic, protocols, config)]
    if graphic.get("graphic_id") != graphic_id:
        out.append(f"{CODE_ID_MISMATCH}: the anchor places {graphic_id!r}, the order is "
                   f"{graphic.get('graphic_id')!r}")
    if not out:
        extra = og.adds_text(graphic)
        if extra:
            out.append(f"{og.FAIL_ADDS_TEXT}: " + "; ".join(
                f"{e['path']} {e['text']!r}" for e in extra)
                + " - no value names it, the template would draw it with no claim behind it")
    return out


# ------------------------------------------------------------ CF-0690 chat
def api_demo_config(origins_doc):
    """The channel's `api_demo` block of its footage-origin.json, or None."""
    block = (origins_doc or {}).get(CONFIG_KEY) if isinstance(origins_doc, dict) else None
    return block if isinstance(block, dict) else None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def protocols_in_batch(batch_dir):
    """{record_id: protocol} of every topic's `api_demo_record` in the batch's
    01-trend-hunter.json ({} when there is none)."""
    if batch_dir is None:
        return {}
    doc = _read_json(Path(batch_dir) / TRENDS_FILE)
    topics = doc.get("topics") if isinstance(doc, dict) else None
    ad = root_module("api_demo")
    out = {}
    for topic in topics if isinstance(topics, list) else []:
        if isinstance(topic, dict) and topic.get(RECORD_FIELD) is not None and ad is not None:
            for rid, prot in ad.protocols_by_record(topic[RECORD_FIELD]).items():
                out.setdefault(rid, prot)
    return out


def protocol_for(record_id, batch_dir, found=None):
    """The protocol of the call `record_id` names: the batch's
    01-trend-hunter.json first (`found` - its `protocols_in_batch`, read once
    by the caller), else the Trend Hunter's cache file
    `<batch>/work/api_demo/<record_id>.json` when it is that record's. None -
    no record."""
    if not (isinstance(record_id, str) and record_id):
        return None
    if found is None:
        found = protocols_in_batch(batch_dir)
    if record_id in found:
        return found[record_id]
    if batch_dir is None or not re.match(r"^api-demo-[a-z0-9][a-z0-9_-]*$", record_id):
        return None
    doc = _read_json(Path(batch_dir) / API_DEMO_WORK / f"{record_id}.json")
    if isinstance(doc, dict) and doc.get("record_id") == record_id \
            and isinstance(doc.get("protocol"), dict):
        return doc["protocol"]
    return None


def chat_protocols(graphics, batch_dir):
    """{record_id: protocol} for the `record_id`s of these api_chat orders -
    only the records found (a missing one is `api_demo_no_record`)."""
    found = protocols_in_batch(batch_dir)
    out = {}
    for g in graphics or []:
        rid = g.get("record_id") if isinstance(g, dict) else None
        if isinstance(g, dict) and g.get("template") == API_CHAT and isinstance(rid, str):
            prot = protocol_for(rid, batch_dir, found)
            if prot is not None:
                out[rid] = prot
    return out


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def ideal_timing(data):
    """(type, think, reveal) seconds unhurried (= ApiChat.jsx defaultTiming)."""
    d = data if isinstance(data, dict) else {}
    prompt = d.get("prompt") if isinstance(d.get("prompt"), str) else ""
    answer = d.get("answer") if isinstance(d.get("answer"), str) else ""
    return (_clamp(len(prompt) / TYPE_CPS, *TYPE_RANGE), THINK,
            _clamp(len(answer.split()) / REVEAL_WPS, *REVEAL_RANGE))


def chat_timing(data, run_seconds):
    """The chat's clock for a run of `run_seconds`: {type_start,
    type_seconds, think_seconds, reveal_seconds, answer_full_at, run_seconds,
    hold_seconds, scaled}; None when even the fastest clock leaves the whole
    answer less than HOLD_MIN on screen."""
    run = float(run_seconds or 0.0)
    ideal = ideal_timing(data)
    floor = (FLOOR_TYPE, FLOOR_THINK, FLOOR_REVEAL)
    room = run - LEAD - HOLD_MIN
    if room + 1e-9 < sum(floor):
        return None
    if room >= sum(ideal):
        parts, scaled = ideal, False
    else:
        k = (room - sum(floor)) / max(1e-9, sum(ideal) - sum(floor))
        parts, scaled = tuple(f + (i - f) * k for f, i in zip(floor, ideal)), True
    parts = tuple(math.floor(x * 1000) / 1000 for x in parts)
    full = round(LEAD + sum(parts), 3)
    return {"type_start": LEAD, "type_seconds": parts[0], "think_seconds": parts[1],
            "reveal_seconds": parts[2], "answer_full_at": full, "run_seconds": round(run, 3),
            "hold_seconds": round(run - full, 3), "scaled": scaled}


def chat_runs(blocks):
    """[[block index, ...]] - each run of api_chat blocks that is one
    animation on screen: a block continues the run before it when it shows the
    same graphic, starts where that one ended and its `offset_seconds` is the
    run's seconds so far (resolve_anchors.graphic_block)."""
    runs, cur, last = [], None, None
    for i, b in enumerate(blocks or []):
        a = b.get("asset") if isinstance(b, dict) else None
        if not (isinstance(a, dict) and a.get("kind") == KIND and a.get("template") == API_CHAT):
            cur = last = None
            continue
        off = float(a.get("offset_seconds") or 0.0)
        if (cur is not None and last is not None
                and last[0] == a.get("graphic_id")
                and abs(float(b.get("start", 0.0)) - last[1]) <= RUN_TOUCH
                and abs(off - last[2]) <= RUN_TOUCH):
            cur.append(i)
        else:
            cur = [i]
            runs.append(cur)
        dur = block_seconds(b)
        last = (a.get("graphic_id"), float(b.get("end", 0.0)), off + dur)
    return runs


def stamp_chat_timing(blocks):
    """Write `asset.chat_timing` on every api_chat block (the same clock on
    every block of a run, scaled to the whole run: offset of its first block +
    the run's seconds). -> ["<code>: <detail>"] of the runs too short to hold
    the whole answer HOLD_MIN seconds (the caller refuses the plan)."""
    out = []
    for run in chat_runs(blocks):
        first, last = blocks[run[0]], blocks[run[-1]]
        a0 = first["asset"]
        seconds = (float(a0.get("offset_seconds") or 0.0)
                   + sum(block_seconds(blocks[i]) for i in run))
        timing = chat_timing(a0.get("data"), seconds)
        if timing is None:
            need = LEAD + FLOOR_TYPE + FLOOR_THINK + FLOOR_REVEAL + HOLD_MIN
            out.append(f"block(s) {run} ({a0.get('graphic_id')}): {CODE_CHAT_TOO_SHORT}: the "
                       f"chat runs {seconds:.2f}s ({float(first.get('start', 0)):.2f}-"
                       f"{float(last.get('end', 0)):.2f}s) - typing the prompt, thinking and "
                       f"revealing the answer at their fastest and holding the whole answer "
                       f"{HOLD_MIN:g}s needs {need:.2f}s; the script's chat anchor needs a "
                       f"longer phrase")
            continue
        for i in run:
            blocks[i]["asset"]["chat_timing"] = dict(timing)
    return out


def _score_value(text):
    """The first number of a score as a float (its scaled value when it has a
    scale word: "1.5B" -> 1.5e9), or None."""
    og = rule()
    if og is None or not isinstance(text, str):
        return None
    found = og.parse_numbers(text)
    if not found:
        return None
    bare, scaled = found[0]
    try:
        return float(scaled if scaled is not None else bare)
    except (TypeError, ValueError):
        return None


def bars(graphic):
    """A benchmark's bar lengths: each score as a share of the largest, read
    off the scores themselves (own_graphic.parse_numbers). None when any score
    has no readable number or none is above zero - the template then draws
    every bar full, implying no ranking it could not read."""
    data = (graphic or {}).get("data") or {}
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    values = [_score_value((r or {}).get("score")) if isinstance(r, dict) else None for r in rows]
    if any(v is None or v < 0 for v in values) or max(values) <= 0:
        return None
    top = max(values)
    return [round(v / top, 4) for v in values]


def asset(graphic, graphic_id, offset=0.0, lang=DEFAULT_LANG):
    """The plan block's asset (call only on a graphic `problems()` passed).
    A benchmark also carries `bars` (bars())."""
    og = rule()
    g = graphic if isinstance(graphic, dict) else {}
    out = {
        "kind": KIND,
        "graphic_id": graphic_id,
        "template": g.get("template"),
        "data": g.get("data"),
        "source_label": g.get("source_label"),
        "caption": og.caption(g, lang) if og else None,
        "lang": lang,
        "offset_seconds": round(float(offset or 0.0), 3),
    }
    if g.get("template") == "benchmark":
        out["bars"] = bars(g)
    if g.get("template") == API_CHAT:
        # CF-0690: the record the chat stands on, and its clock until
        # stamp_chat_timing() scales it to the run
        out["record_id"] = g.get("record_id")
        out["chat_timing"] = chat_timing(g.get("data"), 1e9)
        out["chat_timing"].pop("run_seconds")
        out["chat_timing"].pop("hold_seconds")
    return out


def as_order(a):
    """A plan asset back in the order's shape (what own_graphic.py reads)."""
    a = a if isinstance(a, dict) else {}
    out = {"graphic_id": a.get("graphic_id"), "template": a.get("template"),
           "data": a.get("data"), "source_label": a.get("source_label")}
    if a.get("template") == API_CHAT:
        out["record_id"] = a.get("record_id")
    return out


def viewer_text(a):
    """What the viewer reads on this asset's frame, line by line."""
    og = rule()
    if og is None or not isinstance(a, dict):
        return ""
    return og.viewer_text(as_order(a), a.get("lang") or DEFAULT_LANG)


def record(plan):
    """`plan["own_graphics"]`: [{graphic_id, template, blocks, start_s, end_s,
    seconds, source_label, caption, viewer_text}] in order of first use."""
    rows = {}
    for i, b in enumerate(_blocks(plan)):
        if not is_own_graphic(b):
            continue
        a = b.get("asset") or {}
        gid = a.get("graphic_id")
        row = rows.get(gid)
        if row is None:
            row = rows[gid] = {"graphic_id": gid, "template": a.get("template"),
                               "blocks": [], "start_s": round(float(b.get("start", 0.0)), 3),
                               "end_s": 0.0, "seconds": 0.0,
                               "source_label": a.get("source_label"),
                               "caption": a.get("caption"), "viewer_text": viewer_text(a)}
            if a.get("template") == API_CHAT:
                row["record_id"] = a.get("record_id")       # CF-0690
        row["blocks"].append(i)
        row["end_s"] = round(float(b.get("end", 0.0)), 3)
        row["seconds"] = round(row["seconds"] + block_seconds(b), 3)
    return list(rows.values())
