#!/usr/bin/env python3
"""CF-0774: the vendor's quotes stay quotes - asked of every script, not only a demo.

On a channel whose `channels/<channel>/footage-origin.json` has `proof_quotes`
(ExampleTech) a vendor's official clip is a short proof quote and never the
base of a video: at most `max_seconds_per_quote` a quote, `max_quotes_per_video`
quotes, `max_seconds_per_video` in all, and never most of the footage
(`never_the_base`). The base is our own footage - the recording of the tool
(`own_capture`) and the graphics the Video Editor draws from the script's facts
(`own_graphic`, CF-0689, step 5 «Own graphics»). The Video Editor measures the
same on the finished plan (`proof_quote_cap.py`, "PROOF-QUOTE CAP BROKEN") and
refuses it - after the voice is paid for and with only anchor edits left
(step 6b), which cannot turn a quote into a graphic.

`example-tech/2026-10-16T0839Z` is why this exists: four scripts (HomeView,
Gemini 4 Argon, ChatGPT, HomePod - explainer, list, contrast) ordered no
graphic at all and put every anchor on the vendor's clips (8-32 s a quote, up
to 32 s of 32 s), and all four died `plan_unassembled` on the Editor's cap.
`check_demo.py` measures quotes only on a `demo`; every other pattern went
unasked.

What a quote is, read off the script before the voice:

  * each anchor drives its stretch of speech - its `beat_text`'s first word to
    the next anchor's (the first anchor also takes the words before it, the
    last runs to the end), at this script's own reading rate
    (`check_anchor_cadence.speech_rate`, CF-0279) - the Editor's rule
    (`resolve_anchors.py`: a segment spans its anchor's word to the next
    anchor's);
  * when `check_block_capacity.py` has recorded the Editor's own block layout
    for exactly this text and these anchors (`block_capacity.blocks[]`, its
    `script_hash` current), that layout is read instead - `hold` merges
    stretches into one block, and the block's shots name the source the pool
    would give it;
  * a stretch (or block) driven by a graphic anchor is ours. A pool anchor's is
    a **quote** when its block's shot is from a source that is not our own
    recording, or - no shot known - when the topic's pool
    (`01b-footage-index.json` -> `sources_by_topic`) holds no own recording at
    all: on this channel the pool holds nothing but our recordings and the
    vendors' quotes (footage-origin.json `licences`). With a recording in the
    pool and no shot known, the stretch is left to the Editor (`unknown`);
  * neighbouring quote stretches are **one quote** - back to back the viewer
    sees one run of the vendor's footage; two runs are told apart only where
    the layout names two different sources.

Four codes, the Editor's own words, each with what to do:

    quote_too_long          a quote over `max_seconds_per_quote`
    too_many_quotes         more quotes than `max_quotes_per_video`
    quotes_over_video_total the quotes over `max_seconds_per_video` in all
    quote_is_the_base       the quotes more than half of the speech

The caps are compared less `ESTIMATE_MARGIN_SECONDS`: before TTS a position is
an estimate (CF-0277 measured 0.6-1.7 s per anchor against the real wav), and
a quote estimated right on the cap is one the Editor measures over it.

Read-only: no `--write`, no attempt counter - a finding is fixed in the script
(graphics ordered and placed, a quote anchor moved onto the words its clip
proves) before the file leaves the stage. A channel with no `proof_quotes`
(ExampleFilm, ExampleScience) prints `none` and is untouched.

Usage:
    python3 scripts/check_proof_quotes.py <03-content-researcher.json> \\
        [--trend <01-trend-hunter.json>] [--footage-index <01b-footage-index.json>]

`--trend` and `--footage-index` default to the files of the same name beside
the batch file; both are optional (without either, a pool anchor whose block
names no shot is `unknown`).

Exit codes: 0 every script keeps its quotes inside the cap (or the channel has
no cap), 1 a finding, 3 cannot answer (no batch file, a channel with no
words-per-second, an anchor whose `beat_text` is not in the speech). Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0869: --trend spelled any usable way)
from _channel_ids import resolve_channel  # noqa: E402
import _rewrite_guard as rg  # noqa: E402
import _own_graphic as ogl  # noqa: E402
from check_narration_budget import find_root  # noqa: E402
from check_anchor_cadence import (  # noqa: E402
    CannotJudge, anchor_word_index, narration_words, speech_rate)
from check_anchor_coverage import counted_sections  # noqa: E402
from check_demo import (  # noqa: E402
    file_id, is_own_capture, proof_quote_caps, quote_sources, shot_source, topics_by_id)

FIELD = "visual_anchors"
LAYOUT_KEY = "block_capacity"        # = check_block_capacity.RECORD_KEY

CODE_TOO_LONG = "quote_too_long"            # = video-editor proof_quote_cap codes
CODE_TOO_MANY = "too_many_quotes"
CODE_OVER_TOTAL = "quotes_over_video_total"
CODE_IS_BASE = "quote_is_the_base"
CODES = (CODE_TOO_LONG, CODE_TOO_MANY, CODE_OVER_TOTAL, CODE_IS_BASE)

KIND_OWN, KIND_QUOTE, KIND_UNKNOWN = "own", "quote", "unknown"

# Before TTS an anchor's place is an estimate: CF-0277 measured it 0.64-1.74 s
# off the real wav on average (check_anchor_cadence.anchor_times). A quote's
# length is the difference of two such places, so part of the error cancels;
# half a second under each cap keeps a quote the writer passes from being one
# the Editor refuses.
ESTIMATE_MARGIN_SECONDS = 0.5

GRAPHICS_STEP = "step 5, «Own graphics»"
FIX = {
    CODE_TOO_LONG: (
        "end the quote where its proof ends: the vendor's clip stands only under the one "
        "sentence it proves, and the next anchor - a graphic of the script's own facts "
        f"(`graphics[]` + an anchor `{{anchor_id, graphic_id, beat_text}}`, {GRAPHICS_STEP}) "
        "- starts on the first words after it"),
    CODE_TOO_MANY: (
        "keep the quotes the narration needs as proof - the vendor showing or saying the "
        "thing in its own words - and give every other stretch a graphic anchor "
        f"({GRAPHICS_STEP}); a pool phrase on a vendor clip is a quote however it is worded"),
    CODE_OVER_TOTAL: (
        "cut the vendor's footage back to the channel's cap: fewer quote anchors, fewer "
        f"words over each, the rest of the speech on graphics of the script's facts "
        f"({GRAPHICS_STEP})"),
    CODE_IS_BASE: (
        "the base of this channel's video is our own footage, never the vendor's: order "
        f"`graphics[]` from the script's facts and claims ({GRAPHICS_STEP}) and place one "
        "on every stretch a quote does not prove - an explainer, a list or a contrast may "
        "stand on graphics alone; then `check_graphics.py` and this check again"),
}

EXIT_OK, EXIT_FINDING, EXIT_CANNOT_ANSWER = 0, 1, 3


class CannotAnswer(Exception):
    """The question could not be put. Never a verdict on a script."""


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {path}: {exc}")


def topic_pool(topic_id, sources_by_topic, topic):
    """File ids of the topic's pool: `01b sources_by_topic`, else the Trend
    Hunter's candidates; None when neither is known."""
    if isinstance(sources_by_topic, dict) and isinstance(sources_by_topic.get(topic_id), list):
        return [file_id(v) for v in sources_by_topic[topic_id] if isinstance(v, str)]
    cands = ((topic or {}).get("evidence") or {}).get("footage_candidates")
    if isinstance(cands, list):
        return [file_id(c.get("video_id")) for c in cands
                if isinstance(c, dict) and isinstance(c.get("video_id"), str)]
    return None


def pool_is_quotes_only(pool):
    """True when the pool holds sources and none of them is our recording."""
    return bool(pool) and not any(is_own_capture(v) for v in pool)


def stretches(script, sections, rate):
    """`[{anchor, anchor_id, graphic, source, seconds}]` in speech order - the
    stretch each anchor drives, from its word to the next anchor's."""
    anchors = script.get(FIELD)
    if not isinstance(anchors, list) or not anchors:
        return []
    texts, offsets, total = narration_words(script, sections)
    placed = []
    for i, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            continue
        at = anchor_word_index(anchor, texts, offsets)
        if at is None:
            raise CannotAnswer(
                f"{script.get('script_id')}: anchor {anchor.get('anchor_id')!r} has a "
                f"`beat_text` that is not in the speech - no stretch to measure "
                f"(`check_anchor_coverage.py` refuses it)")
        placed.append((at, i, anchor))
    placed.sort(key=lambda p: (p[0], p[1]))
    out = []
    for n, (at, i, anchor) in enumerate(placed):
        start = 0 if n == 0 else at
        end = placed[n + 1][0] if n + 1 < len(placed) else total
        out.append({"anchor": i, "anchor_id": anchor.get("anchor_id"),
                    "graphic": ogl.is_graphic_anchor(anchor), "source": None,
                    "seconds": max(0, end - start) / rate})
    return out


def recorded_layout(script, sections):
    """The Editor's block layout `check_block_capacity.py` recorded for exactly
    this text and these anchors - `[{block, anchor, anchor_id, graphic, source,
    seconds}]` - or None (no record, or one written for another script)."""
    record = script.get(LAYOUT_KEY)
    if not isinstance(record, dict) or not isinstance(record.get("blocks"), list):
        return None
    if record.get(rg.HASH_KEY) != rg.script_hash(script, sections):
        return None
    anchors = script.get(FIELD) or []
    out = []
    for b in record["blocks"]:
        if not isinstance(b, dict) or not isinstance(b.get("seconds"), (int, float)):
            return None
        ai = b.get("anchor")
        anchor = anchors[ai] if isinstance(ai, int) and 0 <= ai < len(anchors) else {}
        shots = [s for s in b.get("shots") or [] if isinstance(s, str)]
        out.append({"block": b.get("block"), "anchor": ai,
                    "anchor_id": (anchor or {}).get("anchor_id"),
                    "graphic": bool(b.get("own_graphic")) or ogl.is_graphic_anchor(anchor),
                    "source": shot_source(shots[0]) if shots else None,
                    "seconds": float(b["seconds"])})
    return out or None


def classify(unit, quotes_only):
    if unit["graphic"]:
        return KIND_OWN
    if unit["source"] is not None:
        return KIND_OWN if is_own_capture(unit["source"]) else KIND_QUOTE
    return KIND_QUOTE if quotes_only else KIND_UNKNOWN


def quote_runs(units, quotes_only):
    """Neighbouring quote units as one quote, split only where both name a
    source and the two differ. `[{anchors, blocks, sources, seconds}]`."""
    runs, cur = [], None
    for u in units:
        kind = classify(u, quotes_only)
        u["kind"] = kind
        if kind != KIND_QUOTE:
            cur = None
            continue
        if cur is not None and (u["source"] is None or cur["last"] is None
                                or u["source"] == cur["last"]):
            cur["seconds"] += u["seconds"]
        else:
            cur = {"anchors": [], "blocks": [], "sources": [], "seconds": u["seconds"],
                   "last": None}
            runs.append(cur)
        if u["anchor_id"] not in cur["anchors"]:
            cur["anchors"].append(u["anchor_id"])
        if u.get("block") is not None:
            cur["blocks"].append(u["block"])
        if u["source"] is not None:
            cur["last"] = u["source"]
            if u["source"] not in cur["sources"]:
                cur["sources"].append(u["source"])
    for r in runs:
        r.pop("last", None)
        r["seconds"] = round(r["seconds"], 2)
    return runs


def _num(caps, key):
    v = (caps or {}).get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _where(run):
    return (f"anchor(s) {', '.join(str(a) for a in run['anchors'])}"
            + (f" (block(s) {run['blocks']})" if run["blocks"] else "")
            + (f" on {', '.join(run['sources'])}" if run["sources"] else ""))


def judge(script, caps, rate, sections, pool):
    """`(findings, reading)` for one script. `findings` is `[(code, detail)]`."""
    layout = recorded_layout(script, sections)
    units = layout if layout is not None else stretches(script, sections, rate)
    quotes_only = pool_is_quotes_only(pool)
    runs = quote_runs(units, quotes_only)
    speech = sum(u["seconds"] for u in units)
    quote_s = sum(r["seconds"] for r in runs)
    unknown_s = sum(u["seconds"] for u in units if u["kind"] == KIND_UNKNOWN)
    own_s = sum(u["seconds"] for u in units if u["kind"] == KIND_OWN)
    reading = {"measured_on": "block_capacity" if layout is not None else "anchor_stretches",
               "speech_seconds": round(speech, 2), "quote_seconds": round(quote_s, 2),
               "own_seconds": round(own_s, 2), "unknown_seconds": round(unknown_s, 2),
               "quotes": runs, "pool_quotes_only": quotes_only,
               "graphic_anchors": sum(1 for a in script.get(FIELD) or []
                                      if ogl.is_graphic_anchor(a))}
    out = []
    most_one, most_n = _num(caps, "max_seconds_per_quote"), _num(caps, "max_quotes_per_video")
    most_all = _num(caps, "max_seconds_per_video")
    if most_one is not None:
        for r in runs:
            if r["seconds"] > most_one - ESTIMATE_MARGIN_SECONDS + 1e-9:
                out.append((CODE_TOO_LONG,
                            f"the quote on {_where(r)} is about {r['seconds']:.1f} s of speech - "
                            f"over max_seconds_per_quote {most_one} s less "
                            f"{ESTIMATE_MARGIN_SECONDS} s for the estimate"))
    if most_n is not None and len(runs) > most_n:
        out.append((CODE_TOO_MANY, f"{len(runs)} vendor quotes - over max_quotes_per_video "
                                   f"{most_n}"))
    if most_all is not None and quote_s > most_all - ESTIMATE_MARGIN_SECONDS + 1e-9:
        out.append((CODE_OVER_TOTAL,
                    f"the vendor quotes are about {quote_s:.1f} s in all - over "
                    f"max_seconds_per_video {most_all} s less {ESTIMATE_MARGIN_SECONDS} s"))
    if caps.get("never_the_base") is True and speech > 0 and quote_s > speech / 2 + 1e-9:
        out.append((CODE_IS_BASE,
                    f"the vendor quotes are about {quote_s:.1f} s of {speech:.1f} s of speech - "
                    f"most of it, with {reading['graphic_anchors']} graphic anchor(s); a quote "
                    f"is never the base of a video (never_the_base)"))
    return out, reading


def check_batch(batch_file, trend_file=None, footage_index=None, root=None, out=print):
    """Judge every script. Returns `{script_id: [(code, detail)]}`."""
    batch_path = Path(batch_file)
    data = _load(batch_path)
    root = Path(root) if root else find_root()
    channel = resolve_channel(data.get("channel"), root)
    caps = proof_quote_caps(channel, root)
    scripts = [s for s in data.get("scripts") or [] if isinstance(s, dict)]
    if not caps:
        out(f"none  {batch_file}: no proof_quotes on channel {channel!r} - nothing to judge")
        return {}
    if not scripts:
        out(f"none  {batch_file}: no script - nothing to judge")
        return {}
    trend_path = Path(trend_file) if trend_file else batch_path.parent / "01-trend-hunter.json"
    topics = topics_by_id(_load(trend_path)) if trend_path.is_file() else {}
    index_path = (Path(footage_index) if footage_index
                  else batch_path.parent / "01b-footage-index.json")
    sbt = (_load(index_path).get("sources_by_topic") or {}) if index_path.is_file() else None
    sections = counted_sections(channel, root) if channel else rg.TEXT_SECTIONS
    out(f"{batch_file}: {len(scripts)} script(s); quote caps "
        f"{caps.get('max_quotes_per_video')} quote(s), {caps.get('max_seconds_per_quote')} s "
        f"each, {caps.get('max_seconds_per_video')} s in all, never the base "
        f"(channels/{channel}/footage-origin.json proof_quotes), less "
        f"{ESTIMATE_MARGIN_SECONDS} s for the estimate; pool from "
        + (index_path.name if sbt is not None else
           (f"{trend_path.name} candidates" if topics else "nowhere (no 01b, no 01)")))
    results = {}
    for script in scripts:
        sid = script.get("script_id")
        try:
            rate, _src = speech_rate(script, channel, root)
        except CannotJudge as exc:
            raise CannotAnswer(str(exc))
        tid = script.get("topic_id")
        pool = topic_pool(tid, sbt, topics.get(tid))
        found, reading = judge(script, caps, rate, sections, pool)
        results[sid] = found
        summary = (f"quotes {reading['quote_seconds']:.1f} s in {len(reading['quotes'])} "
                   f"of {reading['speech_seconds']:.1f} s, own {reading['own_seconds']:.1f} s "
                   f"({reading['graphic_anchors']} graphic anchor(s))"
                   + (f", {reading['unknown_seconds']:.1f} s left to the Editor (the pool "
                      f"holds our recording; no shot named)" if reading["unknown_seconds"]
                      else "")
                   + f"; measured on {reading['measured_on']}")
        if not found:
            out(f"  ok    {sid}: {summary}")
            if reading["unknown_seconds"] and reading["measured_on"] != "block_capacity":
                out(f"    note: run `check_block_capacity.py --write` on this text and these "
                    f"anchors first - its layout names the shot (our recording or the "
                    f"vendor's clip) each block gets, and this check reads it")
            continue
        out(f"  FAIL  {sid}: {summary}")
        for code, detail in found:
            out(f"    {code}: {detail}")
            out(f"      fix: {FIX[code]}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--trend", type=_batch_arg.beside(_batch_arg.TREND_FILE),  # CF-0869
                    help="01-trend-hunter.json (default: beside the batch file)")
    ap.add_argument("--footage-index",
                    help="01b-footage-index.json (default: beside the batch file, optional)")
    ap.add_argument("--root", help="the factory checkout (default: found from this file)")
    args = ap.parse_args(argv)
    try:
        results = check_batch(args.batch_file, args.trend, args.footage_index, args.root)
    except CannotAnswer as exc:
        print(f"cannot answer: {exc}")
        return EXIT_CANNOT_ANSWER
    bad = {sid: f for sid, f in results.items() if f}
    if bad:
        print(f"\n{len(bad)} script(s) to fix (codes and fixes above) - the Video Editor's "
              f"proof_quote_cap would refuse the plan")
        return EXIT_FINDING
    return EXIT_OK


@runlog.script("content-researcher", "check-proof-quotes", name="check_proof_quotes.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event (1 = a finding, 2 = usage, 3 = cannot answer). Pure
    Python over the batch files: no external binary, no model call, so no
    `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
