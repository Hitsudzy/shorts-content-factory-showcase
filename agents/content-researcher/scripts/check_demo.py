#!/usr/bin/env python3
"""CF-0567: is a «демо» script a demo - asked at the writer's stage.

The «демо» pattern (`patterns/demo.json`, ExampleTech) is a news story shown
working: the factory's own screen recording of the tool (`own_capture`) is the
footage from the first block to the last, and a vendor's official clip may
stand in as a short proof quote, capped by the channel's
`channels/<channel>/footage-origin.json` -> `proof_quotes`. The Video Editor
holds the line after the plan is built (`proof_quote_cap.py`: the gates
`proof_quote_cap` and `demo_own_capture`); this is the writer's early warning,
on what the script itself says, before a second of voice is paid for. It
duplicates none of the Editor's measuring - it reads the topic's record, the
script's own shot claims and its words.

CF-0690 - "a demo via API": a demo may instead stand on the topic's own
model's real answer through its API - the Trend Hunter asked one approved
prompt through the Gemini API and kept the call as the topic's
`api_demo_record`, and the script orders and places an `api_chat` graphic
(`graphics[]` + a `visual_anchors[]` entry naming it) whose `record_id` is
that record's, of an `ok` call (the chat shows the real tool). Such a demo
needs no own capture: `demo_without_capture` is not said, and the
recording's rules (`demo_base_not_capture`, `demo_space_not_named`) are not
asked when there is no recording to stand on. The chat's own words are
`check_graphics.py`'s (`api_demo_*`), its answer as a fact `check_claims.py`'s.

Five codes, each with what to do:

    demo_without_capture   the topic has no own capture (and no chat on its
                           `api_demo_record`, CF-0690): the Trend Hunter's
                           `evidence.footage_base.base` is not `own_capture`
                           (vendor quotes only - `only_proof_quotes` - or
                           nothing recorded), or the Footage Indexer's pool
                           for the topic (`01b` -> `sources_by_topic`) holds
                           no `own_capture-<id>`. Not a demo: another pattern
                           of the channel, or a written rejection.
    demo_quote_over_cap    the shots the script names from a vendor's quote
                           source (`claims[].support[].shot_id` on a candidate
                           with `role: proof_quote`) are more quotes than
                           `max_quotes_per_video`, or the voice over one of
                           them runs past `max_seconds_per_quote`, or over all
                           of them past `max_seconds_per_video`.
    demo_base_not_capture  what the tool does on screen is not footed on the
                           recording: no shot claim names an own-capture shot,
                           or own-capture shots are not more than half of the
                           script's shot claims.
    demo_space_not_named   no spoken line says where the tool ran: "Hugging
                           Face" and the Space's name (`capture.space` is
                           `<owner>/<name>`; the owner is usually the vendor
                           the hook already names, so it does not count).
    demo_api_not_named     a demo standing on an `api_chat` (CF-0690) whose
                           spoken lines never say the model's display name
                           (the channel's name for the record's
                           `model_version`, as the chat's label reads it) and
                           "API" - the counterpart of `demo_space_not_named`:
                           the viewer is told what was asked, of whom, how.

The seconds of a quote are the seconds of the words the script lays over it:
the claim's `text` (verbatim from the narration) at this script's own reading
rate (`check_anchor_cadence.speech_rate`, CF-0279). The picture under those
words is on screen at least that long, so a quote said over longer words is
over the cap whatever the cut.

Only `demo` scripts are judged; every other pattern prints nothing and is
untouched, and a channel with no `proof_quotes` (ExampleFilm, ExampleScience)
never has a `demo` script (the pattern is admitted on ExampleTech only).
Read-only: no `--write`, no attempt counter - a finding is fixed in the script
(or the topic is re-drawn) before the file leaves the stage; the Editor's
gates are the backstop.

Usage:
    python3 scripts/check_demo.py <03-content-researcher.json> \\
        [--trend <01-trend-hunter.json>] [--footage-index <01b-footage-index.json>]

`--trend` and `--footage-index` default to the files of the same name beside
the batch file; the footage index is optional (without it the pool half of
`demo_without_capture` is not asked).

Exit codes: 0 every demo script passes (or there is none), 1 a finding,
3 cannot answer (no batch file, a demo script and no readable
01-trend-hunter.json, a channel with no words-per-second). Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0869: --trend spelled any usable way)
from _channel_ids import resolve_channel  # noqa: E402
from check_narration_budget import find_root  # noqa: E402
from check_anchor_cadence import CannotJudge, speech_rate  # noqa: E402
import _own_graphic as og_loader  # noqa: E402 - CF-0690: the chat a demo may stand on

PATTERN_DEMO = "demo"
OWN_CAPTURE = "own_capture"
OWN_CAPTURE_HEADS = ("own_capture-", "own_capture:")
PROOF_QUOTE = "proof_quote"
FOOTAGE_BASE_KEY = "footage_base"
SPOKEN = ("hook", "commentary", "payoff")

CODE_WITHOUT_CAPTURE = "demo_without_capture"
CODE_QUOTE_OVER_CAP = "demo_quote_over_cap"
CODE_BASE_NOT_CAPTURE = "demo_base_not_capture"
CODE_SPACE_NOT_NAMED = "demo_space_not_named"
CODE_API_NOT_NAMED = "demo_api_not_named"          # CF-0690
CODES = (CODE_WITHOUT_CAPTURE, CODE_QUOTE_OVER_CAP, CODE_BASE_NOT_CAPTURE,
         CODE_SPACE_NOT_NAMED, CODE_API_NOT_NAMED)
API_RECORD_FIELD = "api_demo_record"               # = api_demo.RECORD_FIELD

FIX = {
    CODE_WITHOUT_CAPTURE: (
        "not a demo - there is no recording of the tool to show. Reject the draw "
        "(`rotation/rotate.py reject`, step 3) and write the topic on another pattern of the "
        "channel (explainer, list, contrast), or reject the assignment in writing; never "
        "describe a tool nobody sees, and never build the video on the vendor's quotes"),
    CODE_QUOTE_OVER_CAP: (
        "cut the vendor's quote back to the channel's cap "
        "(footage-origin.json `proof_quotes`): fewer quote shots in `claims[]`, or fewer "
        "words over one - the recording carries the video, a quote stands in once"),
    CODE_BASE_NOT_CAPTURE: (
        "foot what the tool does on screen on the recording: a shot claim on "
        "`own_capture-<id>:<n>` for each step the voice describes, more than half of the "
        "script's shot claims; a sentence the recording does not show is taken out"),
    CODE_SPACE_NOT_NAMED: (
        "say in one spoken line where the tool ran, in the block that first shows the page: "
        "\"... running in a public Hugging Face Space, <owner>/<name>\" (the Space is "
        "`capture.space` of the topic's own capture); not on the fact's plate"),
    CODE_API_NOT_NAMED: (
        "say in one spoken line what was asked of whom and how, in the block that first "
        "shows the chat: \"we sent <display name> one question through the Gemini API\" - "
        "the model's display name as the chat's label reads it (\"<display name> · via "
        "API\") and \"API\", footed on the first sentence of the topic's api_demo_record "
        "piece; never what the answer says as a fact"),
}

EXIT_OK, EXIT_FINDING, EXIT_CANNOT_ANSWER = 0, 1, 3


class CannotAnswer(Exception):
    """The question could not be put. Never a verdict on a script."""


def is_own_capture(video_id):
    """`own_capture-<id>` (file id, shot keys) or `own_capture:<id>` (the
    Trend Hunter's candidate name) - by the id alone."""
    return isinstance(video_id, str) and video_id.startswith(OWN_CAPTURE_HEADS)


def file_id(video_id):
    """`own_capture:<id>` -> `own_capture-<id>` (the Footage Indexer's rule:
    every character outside [A-Za-z0-9_-] becomes `_`); anything else as is."""
    if isinstance(video_id, str) and video_id.startswith("own_capture:"):
        return "own_capture-" + re.sub(r"[^A-Za-z0-9_-]", "_", video_id[len("own_capture:"):])
    return video_id


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {path}: {exc}")


def proof_quote_caps(channel, root):
    """The channel's `proof_quotes` block, or None (no cap on this channel)."""
    path = Path(root) / "channels" / str(channel) / "footage-origin.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        return None
    caps = doc.get("proof_quotes")
    return caps if isinstance(caps, dict) else None


def topics_by_id(trend):
    return {t.get("topic_id"): t for t in (trend or {}).get("topics") or []
            if isinstance(t, dict)}


def capture_of(topic):
    """The topic's first own-capture candidate, or None."""
    for c in ((topic or {}).get("evidence") or {}).get("footage_candidates") or []:
        if isinstance(c, dict) and (c.get("kind") == OWN_CAPTURE
                                    or c.get("footage_origin") == OWN_CAPTURE
                                    or is_own_capture(c.get("video_id"))):
            return c
    return None


def quote_sources(topic):
    """Video ids of the topic's vendor proof-quote candidates."""
    return {c.get("video_id") for c in
            ((topic or {}).get("evidence") or {}).get("footage_candidates") or []
            if isinstance(c, dict) and c.get("role") == PROOF_QUOTE and c.get("video_id")}


def shot_source(shot_id):
    """`<video_id>:<n>` -> `<video_id>` (the shot number is after the last
    colon, so `own_capture:<id>:<n>` keeps its id whole)."""
    return file_id(str(shot_id).rsplit(":", 1)[0])


def shot_claims(script):
    """`[(shot_id, claim)]` - every shot the script's `claims[]` stands on."""
    out = []
    for claim in script.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for sup in claim.get("support") or []:
            if isinstance(sup, dict) and isinstance(sup.get("shot_id"), str):
                out.append((sup["shot_id"], claim))
    return out


def _norm(text):
    return " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip() + " "


def space_named(script, space):
    """True when a spoken field says "Hugging Face" and the Space's name -
    the part after the slash of `<owner>/<name>`, separators read as spaces
    ("fox-demo" is said "fox demo")."""
    spoken = _norm(" ".join(str(script.get(f) or "") for f in SPOKEN))
    if " hugging face " not in spoken and " huggingface " not in spoken:
        return False
    if not space:
        return True
    name = _norm(str(space).rsplit("/", 1)[-1])
    return not name.strip() or name in spoken


def api_chat_demo(script, topic, api_demo, config):
    """CF-0690: `{graphic_id, record_id, protocol, display}` of the first
    `api_chat` the script orders AND places whose `record_id` is a record of
    the topic's `api_demo_record` of an `ok` call - the chat a demo can stand
    on - or None. `api_demo` is the root's `shared/api_demo.py`; `display` is
    the channel's name for the record's `model_version` (None: the list names
    no such model - check_graphics.py refuses the chat)."""
    records = api_demo.protocols_by_record((topic or {}).get(API_RECORD_FIELD))
    if not records:
        return None
    placed = {a.get(og_loader.ANCHOR_KEY) for a in og_loader.graphic_anchors(script)}
    for g in og_loader.api_chats(script):
        protocol = records.get(g.get("record_id"))
        if g.get("graphic_id") in placed and isinstance(protocol, dict) \
                and protocol.get("status") == "ok":
            return {"graphic_id": g.get("graphic_id"), "record_id": g.get("record_id"),
                    "protocol": protocol,
                    "display": api_demo.display_name_for(protocol.get("model_version"), config)}
    return None


def api_named(script, display):
    """True when a spoken field says the model's display name and "API"."""
    if not display:
        return False
    spoken = _norm(" ".join(str(script.get(f) or "") for f in SPOKEN))
    return " api " in spoken and _norm(display) in spoken


def judge(script, topic, pool_ids, caps, rate, chat=None):
    """`[(code, detail)]` for one demo script - empty when it passes.
    `chat` - `api_chat_demo` of the script (CF-0690), or None."""
    out = []
    base = ((topic or {}).get("evidence") or {}).get(FOOTAGE_BASE_KEY) or {}
    capture = capture_of(topic)
    if topic is None:
        out.append((CODE_WITHOUT_CAPTURE,
                    f"topic {script.get('topic_id')!r} is not in 01-trend-hunter.json"))
        return out
    on_capture = True
    if base.get("base") != OWN_CAPTURE or capture is None:
        if chat is None:
            why = (base.get("note") or "no `evidence.footage_base` on the topic - the Trend "
                   "Hunter recorded nothing for a demo")
            if base.get("only_proof_quotes"):
                why = f"only_proof_quotes: {why}"
            out.append((CODE_WITHOUT_CAPTURE, why))
            return out
        on_capture = False
    elif pool_ids is not None and not any(is_own_capture(v) for v in pool_ids):
        if chat is None:
            out.append((CODE_WITHOUT_CAPTURE,
                        f"the recording {capture.get('video_id')} never reached the topic's "
                        f"pool (01b sources_by_topic: {', '.join(pool_ids) or 'none'})"))
            return out
        on_capture = False

    shots = shot_claims(script)
    quotes = {file_id(v) for v in quote_sources(topic)}
    own_shots = [s for s, _c in shots if is_own_capture(shot_source(s))]
    if not on_capture:
        pass                    # CF-0690: the demo stands on the chat, not on a recording
    elif not own_shots:
        out.append((CODE_BASE_NOT_CAPTURE,
                    f"none of the script's {len(shots)} shot claim(s) stands on the recording "
                    f"({file_id(capture.get('video_id'))})"))
    elif len(own_shots) * 2 <= len(shots):
        out.append((CODE_BASE_NOT_CAPTURE,
                    f"{len(own_shots)} of {len(shots)} shot claim(s) stand on the recording - "
                    f"not more than half"))

    if caps:
        per_shot = {}
        for shot, claim in shots:
            if shot_source(shot) in quotes:
                words = len(str(claim.get("text") or "").split())
                per_shot[shot] = per_shot.get(shot, 0.0) + words / rate
        most_n = caps.get("max_quotes_per_video")
        most_one = caps.get("max_seconds_per_quote")
        most_all = caps.get("max_seconds_per_video")
        if isinstance(most_n, int) and len(per_shot) > most_n:
            out.append((CODE_QUOTE_OVER_CAP,
                        f"{len(per_shot)} quote shot(s) ({', '.join(sorted(per_shot))}) against "
                        f"max_quotes_per_video {most_n}"))
        if isinstance(most_one, (int, float)):
            for shot, secs in sorted(per_shot.items()):
                if secs > most_one + 1e-9:
                    out.append((CODE_QUOTE_OVER_CAP,
                                f"{shot}: about {secs:.1f} s of voice over it against "
                                f"max_seconds_per_quote {most_one}"))
        total = sum(per_shot.values())
        if isinstance(most_all, (int, float)) and total > most_all + 1e-9:
            out.append((CODE_QUOTE_OVER_CAP,
                        f"about {total:.1f} s of voice over quote shots in all against "
                        f"max_seconds_per_video {most_all}"))

    space = (capture.get("capture") or {}).get("space") if on_capture else None
    if on_capture and not space_named(script, space):
        out.append((CODE_SPACE_NOT_NAMED,
                    f"no spoken line names \"Hugging Face\" and the Space {space or '(unknown)'} "
                    f"by its name"))
    if chat is not None and not api_named(script, chat.get("display")):
        out.append((CODE_API_NOT_NAMED,
                    f"chat {chat.get('graphic_id')} on {chat.get('record_id')}: no spoken line "
                    f"says " + (f"{chat['display']!r} and \"API\"" if chat.get("display") else
                                f"the model - the channel's list names no model "
                                f"{chat['protocol'].get('model_version')!r}")))
    return out


def chat_of(script, topic, root, config):
    """`api_chat_demo` with the root's rule loaded only when it can matter:
    the topic has a record and the script orders a chat."""
    if not ((topic or {}).get(API_RECORD_FIELD) and og_loader.api_chats(script)):
        return None
    try:
        api_demo = og_loader.own_graphic(root).api_demo
    except RuntimeError as exc:
        raise CannotAnswer(str(exc))
    return api_chat_demo(script, topic, api_demo, config)


def check_batch(batch_file, trend_file=None, footage_index=None, root=None, out=print):
    """Judge every `demo` script. Returns `{script_id: [(code, detail)]}`."""
    batch_path = Path(batch_file)
    data = _load(batch_path)
    root = Path(root) if root else find_root()
    channel = resolve_channel(data.get("channel"), root)
    demos = [s for s in data.get("scripts") or []
             if ((s.get("pattern") or {}).get("pattern_id")) == PATTERN_DEMO]
    if not demos:
        out(f"none  {batch_file}: no `demo` script - nothing to judge")
        return {}
    trend_path = Path(trend_file) if trend_file else batch_path.parent / "01-trend-hunter.json"
    topics = topics_by_id(_load(trend_path))
    index_path = (Path(footage_index) if footage_index
                  else batch_path.parent / "01b-footage-index.json")
    sbt = None
    if index_path.is_file():
        sbt = (_load(index_path).get("sources_by_topic") or {})
    caps = proof_quote_caps(channel, root)
    _api_origin, api_config = og_loader.channel_api_demo(channel, root)
    out(f"{batch_file}: {len(demos)} demo script(s); topics from {trend_path.name}"
        + (f", pool from {index_path.name}" if sbt is not None else ", no footage index")
        + (f"; quote caps {caps.get('max_quotes_per_video')} quote(s), "
           f"{caps.get('max_seconds_per_quote')} s each, {caps.get('max_seconds_per_video')} s "
           f"in all (channels/{channel}/footage-origin.json proof_quotes)" if caps else
           f"; no proof_quotes on channel {channel!r}"))
    results = {}
    for script in demos:
        sid = script.get("script_id")
        try:
            rate, _src = speech_rate(script, channel, root)
        except CannotJudge as exc:
            raise CannotAnswer(str(exc))
        tid = script.get("topic_id")
        pool = sbt.get(tid) if sbt is not None else None
        if sbt is not None and not isinstance(pool, list):
            pool = []
        chat = chat_of(script, topics.get(tid), root, api_config)
        found = results[sid] = judge(script, topics.get(tid), pool, caps, rate, chat)
        if not found:
            out(f"  ok    {sid}: " + (
                f"the chat {chat['graphic_id']} on {chat['record_id']} shows the real tool, "
                f"quotes within the cap, the model and the API named" if chat is not None
                and capture_of(topics.get(tid)) is None else
                "the recording is the footage, quotes within the cap, the Space named"
                + (", the model and the API named" if chat is not None else "")))
            continue
        out(f"  FAIL  {sid}: {len(found)} finding(s)")
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
        print(f"\n{len(bad)} demo script(s) to fix (codes and fixes above)")
        return EXIT_FINDING
    return EXIT_OK


@runlog.script("content-researcher", "check-demo", name="check_demo.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event (1 = a finding, 2 = usage, 3 = cannot answer). Pure
    Python over the batch files: no external binary, no model call, so no
    `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
