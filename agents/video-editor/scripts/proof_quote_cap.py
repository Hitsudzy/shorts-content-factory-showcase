#!/usr/bin/env python3
"""CF-0567: the proof-quote cap, and the «демо» pattern's own footage.

A vendor's official channel (`official_channels[]` of the channel's
footage-origin.json with `role: proof_quote` - OpenAI, Google DeepMind,
NVIDIA ... on ExampleTech) is a source of short *quotes*: the vendor saying or
showing the thing in its own words, never the base of a video (the root's
`docs/tech-footage.md`, «Official channels - proof quotes only»). The channel
writes the caps in `proof_quotes`:

    max_seconds_per_quote   5.0   one quote on screen at most this long
    max_quotes_per_video    2     at most this many quotes
    max_seconds_per_video   8.0   all quotes together at most this long
    never_the_base          true  quotes are never most of the footage

What a quote is, measured on the finished blocks (the same reading of what is
on screen as the two-source gate, `source_gate.block_source_seconds`):

  * a block's source is a **quote source** when its rights record (01b
    `fetched[].rights`, else the pool's shots.json `source_rights`) carries
    `role: proof_quote`, or names a `footage_origin` that a `proof_quote`
    official channel has (`vendor_official`), or a `channel_id` /
    `official_channel` that is one of those channels' ids. Our own recording
    (`own_capture`) is never one;
  * **one quote** is a run of consecutive, touching blocks showing the same
    quote source - one cut of the vendor's clip, however many blocks it
    spans; its length is the seconds that source is on screen in the run;
  * **the base** is the footage a video is laid over: quotes are the base
    when their seconds are more than half of all footage seconds on screen
    (borrowed and own, `block_source_seconds` summed) - `never_the_base`
    refuses that.

And the «демо» pattern (`patterns/demo.json`): the recording is the footage
from the first block to the last, a quote may stand in once. A plan of
pattern `demo` whose own recordings (`own_capture-<id>`) are not more than
half of its footage seconds is not a demo - refused as undeliverable.

CF-0689: the factory's own graphics (`asset.kind: "own_graphic"`) are
footage too - ours: their seconds join `footage_seconds` (so a quote over a
graphic-based video is measured against the whole base) and the own share
of a demo (`own_capture_seconds + own_graphic_seconds` more than half). A
demo still needs a recording on screen (`own_capture_seconds > 0`, the
driver's decision of 12.10: a demo shows the tool) - graphics alone are not
a demo.

CF-0690: ... or the tool's own answer - an `api_chat` graphic (a model's
real answer through its API, on the record of the call) shows the real tool
at work, so its seconds (`api_demo_seconds`, part of `own_graphic_seconds`)
stand where a recording would: a demo passes when `own_capture_seconds +
api_demo_seconds` is above zero and capture + graphics are more than half of
the footage (the driver's decision of 12.10). Other graphics without a chat
or a recording are still not a demo.

Two gates of build_render_plan.py, both before the expensive layers:

    gate id            funnel code             refused_because
    proof_quote_cap    held_back               quote_too_long, too_many_quotes,
                                               quotes_over_video_total,
                                               quote_is_the_base
    demo_own_capture   pattern_undeliverable   demo_not_own_capture

A channel whose footage-origin.json has no `proof_quotes` (ExampleFilm,
ExampleScience) is not measured at all: `applies: false`, nothing read,
nothing refused - its plans are built exactly as before. Stdlib only.
"""
import _clip_names
import source_gate

API_CHAT = "api_chat"   # = own_graphic.API_CHAT (CF-0690)

FIELD = "proof_quote_cap"
PROOF_QUOTE = "proof_quote"
PATTERN_DEMO = "demo"

CODE_QUOTE_TOO_LONG = "quote_too_long"
CODE_TOO_MANY_QUOTES = "too_many_quotes"
CODE_QUOTES_OVER_VIDEO = "quotes_over_video_total"
CODE_QUOTE_IS_BASE = "quote_is_the_base"
CODE_DEMO_NOT_OWN = "demo_not_own_capture"
CAP_CODES = (CODE_QUOTE_TOO_LONG, CODE_TOO_MANY_QUOTES, CODE_QUOTES_OVER_VIDEO,
             CODE_QUOTE_IS_BASE)

# A run of blocks is one quote when the next block starts within this of the
# last one's end (the plan's timings are rounded to the millisecond).
TOUCH_SECONDS = 0.05
EPS = 1e-6


def caps_of(doc):
    """The channel's `proof_quotes` block, or None (the cap does not apply)."""
    pq = (doc or {}).get("proof_quotes") if isinstance(doc, dict) else None
    return pq if isinstance(pq, dict) else None


def quote_channels(doc):
    """-> (channel ids, origin ids) of the `proof_quote` official channels."""
    ids, origins = set(), set()
    for entry in (doc or {}).get("official_channels") or []:
        if not isinstance(entry, dict) or entry.get("role") != PROOF_QUOTE:
            continue
        if entry.get("origin"):
            origins.add(str(entry["origin"]))
        for ch in entry.get("channels") or []:
            if isinstance(ch, dict) and ch.get("id"):
                ids.add(str(ch["id"]))
    return ids, origins


def is_quote(vid, rights, doc):
    """True when source `vid` is a vendor's quote (see the docstring)."""
    if _clip_names.is_own_capture(vid):
        return False
    r = rights if isinstance(rights, dict) else {}
    if r.get("licence") == "own_capture" or r.get("footage_origin") == "own_capture":
        return False
    if r.get("role") == PROOF_QUOTE:
        return True
    ids, origins = quote_channels(doc)
    if r.get("footage_origin") and str(r["footage_origin"]) in origins:
        return True
    ch = r.get("channel_id") or r.get("official_channel")
    if isinstance(ch, dict):
        ch = ch.get("id") or ch.get("channel_id")
    return bool(ch) and str(ch) in ids


def quote_runs(plan, quote_of):
    """[{video_id, blocks, start_s, end_s, seconds}] - every quote on screen,
    in order. `quote_of(vid) -> bool`."""
    runs, open_runs = [], {}
    for i, block in enumerate(source_gate._blocks_of(plan)):
        secs = source_gate.block_source_seconds(block)
        start = float(block.get("start", 0.0) or 0.0)
        end = float(block.get("end", 0.0) or 0.0)
        still = {}
        for vid, s in secs.items():
            if not quote_of(vid):
                continue
            run = open_runs.get(vid)
            if run and run["blocks"][-1] == i - 1 and abs(start - run["end_s"]) <= TOUCH_SECONDS:
                run["blocks"].append(i)
                run["end_s"] = round(end, 3)
                run["seconds"] = round(run["seconds"] + s, 3)
            else:
                run = {"video_id": vid, "blocks": [i], "start_s": round(start, 3),
                       "end_s": round(end, 3), "seconds": round(s, 3)}
                runs.append(run)
            still[vid] = run
        open_runs = still
    return runs


def api_demo_seconds(plan):
    """CF-0690: seconds the `api_chat` graphics are on screen (own graphics
    whose template is the chat - the tool's real answer)."""
    total = 0.0
    for b in source_gate._blocks_of(plan):
        a = b.get("asset") if isinstance(b, dict) else None
        if isinstance(a, dict) and a.get("kind") == source_gate.OWN_GRAPHIC_KIND \
                and a.get("template") == API_CHAT:
            try:
                total += max(0.0, float(b.get("end", 0.0)) - float(b.get("start", 0.0)))
            except (TypeError, ValueError):
                continue
    return round(total, 3)


def judge(plan, read_rights=None, doc=None, pattern_id=None):
    """The record that goes on the plan (`plan["proof_quote_cap"]`):
    {applies, passed, refused_because, refusals[{code, text}], gate, caps,
    quotes, quote_count, quote_seconds, footage_seconds, own_capture_seconds,
    pattern_id, note}. `read_rights(vid) -> (record | None, where)`."""
    caps = caps_of(doc)
    demo = pattern_id == PATTERN_DEMO
    base = {"applies": bool(caps) or demo, "passed": True, "refused_because": [],
            "refusals": [], "gate": None, "caps": caps, "quotes": [], "quote_count": 0,
            "quote_seconds": 0.0, "footage_seconds": 0.0, "own_capture_seconds": 0.0,
            "own_graphic_seconds": 0.0, "api_demo_seconds": 0.0,
            "pattern_id": pattern_id}
    if not base["applies"]:
        return {**base, "note": "the channel has no `proof_quotes` and the pattern is not "
                                "a demo - not measured (CF-0567)"}
    cache = {}

    def quote_of(vid):
        if vid not in cache:
            rights = read_rights(vid)[0] if read_rights else None
            cache[vid] = is_quote(vid, rights, doc)
        return cache[vid]

    runs = quote_runs(plan, quote_of) if caps else []
    footage = own = 0.0
    for block in source_gate._blocks_of(plan):
        for vid, s in source_gate.block_source_seconds(block).items():
            footage += s
            if _clip_names.is_own_capture(vid):
                own += s
    # CF-0689: our own graphics are footage on screen, and ours.
    graphic = source_gate.own_graphic_seconds(plan)
    chat = api_demo_seconds(plan)
    footage += graphic
    quote_s = round(sum(r["seconds"] for r in runs), 3)
    rec = {**base, "quotes": runs, "quote_count": len(runs), "quote_seconds": quote_s,
           "footage_seconds": round(footage, 3), "own_capture_seconds": round(own, 3),
           "own_graphic_seconds": round(graphic, 3),
           "api_demo_seconds": chat}
    refusals = []
    if caps:
        per = caps.get("max_seconds_per_quote")
        most = caps.get("max_quotes_per_video")
        total = caps.get("max_seconds_per_video")
        for r in runs:
            if isinstance(per, (int, float)) and r["seconds"] > per + EPS:
                refusals.append({"code": CODE_QUOTE_TOO_LONG, "text": (
                    f"the quote of {r['video_id']} on block(s) {r['blocks']} is "
                    f"{r['seconds']:.2f}s - over max_seconds_per_quote {per:g}s")})
        if isinstance(most, int) and len(runs) > most:
            refusals.append({"code": CODE_TOO_MANY_QUOTES, "text": (
                f"{len(runs)} vendor quotes on screen - over max_quotes_per_video {most}")})
        if isinstance(total, (int, float)) and quote_s > total + EPS:
            refusals.append({"code": CODE_QUOTES_OVER_VIDEO, "text": (
                f"the vendor quotes are {quote_s:.2f}s in all - over "
                f"max_seconds_per_video {total:g}s")})
        if caps.get("never_the_base") is True and footage > 0 and quote_s > footage / 2 + EPS:
            refusals.append({"code": CODE_QUOTE_IS_BASE, "text": (
                f"the vendor quotes are {quote_s:.2f}s of {footage:.2f}s of footage - "
                f"most of it; a quote is never the base of a video (never_the_base)")})
    if demo and not (own + chat > EPS and footage > 0 and own + graphic > footage / 2 + EPS):
        refusals.append({"code": CODE_DEMO_NOT_OWN, "text": (
            f"a demo whose own recording is {own:.2f}s"
            + (f" (and own graphics {graphic:.2f}s"
               + (f", of them the API chat {chat:.2f}s" if chat > EPS else "") + ")"
               if graphic > EPS else "")
            + f" of {footage:.2f}s of footage - the recording is the footage of a demo "
            f"from the first block to the last (patterns/demo.json); not more than half "
            f"is not a demo"
            + (", and a demo with no recording at all and no API chat shows no tool "
               "(CF-0689, CF-0690)" if own + chat <= EPS else ""))})
    rec["refusals"] = refusals
    rec["refused_because"] = [r["code"] for r in refusals]
    rec["passed"] = not refusals
    if refusals:
        rec["gate"] = ("proof_quote_cap" if any(c in CAP_CODES for c in rec["refused_because"])
                       else "demo_own_capture")
    rec["note"] = ("; ".join(r["text"] for r in refusals) if refusals else (
        f"{len(runs)} vendor quote(s), {quote_s:.2f}s of {footage:.2f}s of footage"
        + (f" (caps {caps.get('max_seconds_per_quote')}s a quote, "
           f"{caps.get('max_quotes_per_video')} quotes, "
           f"{caps.get('max_seconds_per_video')}s in all)" if caps else "")
        + (f"; own recording {own:.2f}s" + (f" and the API chat {chat:.2f}s" if chat > EPS
                                             else "") + " - a demo" if demo else "")
        + (f"; own graphics {graphic:.2f}s" if graphic > EPS else "")))
    return rec


def report_lines(rec):
    """The stderr lines: the verdict, then every quote."""
    verdict = "passed" if rec.get("passed") else "REFUSED"
    lines = [f"proof-quote cap {verdict}: {rec.get('note')}"]
    for r in rec.get("quotes") or []:
        lines.append(f"  quote {r['video_id']}: {r['start_s']:.2f}-{r['end_s']:.2f}s "
                     f"block(s) {r['blocks']} ({r['seconds']:.2f}s)")
    return lines


def stage_fields(plan):
    """`videos[].proof_quote_cap`: the plan's record, `null` on a plan built
    before CF-0567 (not measured, never read as passed)."""
    rec = (plan or {}).get(FIELD)
    return rec if isinstance(rec, dict) else None
