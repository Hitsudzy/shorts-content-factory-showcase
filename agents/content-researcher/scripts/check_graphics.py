#!/usr/bin/env python3
"""CF-0689: the graphics a script orders - asked at the writer's stage.

ExampleTech's base footage is graphics the factory draws itself (Remotion, in
the Video Editor) from the script's own facts: the user's decision of 12.10 -
no rights risk, fully automatic, nothing invented. A script orders them in a
top-level `graphics[]` and places each on its narration with a
`visual_anchors[]` entry that carries `graphic_id` instead of a pool
`phrase`. The rule of what a graphic may say is the root's
(`shared/own_graphic.py`, loaded by path through `scripts/_own_graphic.py`);
this file runs it over the batch and adds what only the writer's stage can
see - the placement and the channel's switch.

Codes, each printed with what to do (and its Russian line for the refusal):

    graphic_malformed, graphic_unknown_template, graphic_value_unbacked,
    graphic_value_not_in_footing, graphic_benchmark_unattributed,
    graphic_adds_text
                          the root's `own_graphic.check_graphics(script,
                          pieces)` - the order's shape, every value backed by
                          a declared claim `where: "graphic:<id>"`, every
                          number / name / date of it in that claim's quote
                          (verbatim in the topic's support_text when the
                          Trend Hunter's file is there), a benchmark's
                          `source_label`, and no text of the template's own.
    graphic_not_placed    a graphic is ordered and no `visual_anchors[]`
                          entry names it - it would never be on screen, and
                          the claims behind it would stand on nothing.
    graphic_not_ordered   an anchor names a `graphic_id` that `graphics[]`
                          does not order - the Video Editor refuses the plan
                          (its own `graphic_not_ordered`).
    graphic_on_channel_without_origin
                          the script orders graphics (or places one) on a
                          channel whose `channels/<channel>/footage-origin.json`
                          has no `own_graphic` origin - ExampleFilm and
                          ExampleScience: graphics are not their footage.

CF-0690 - "a demo via API": an `api_chat` graphic shows the topic's own
model's real answer to one approved prompt, asked through the Gemini API by
the Trend Hunter and kept as the topic's `api_demo_record`
({record_id, protocol}). It stands on that record, never on claims:

    api_demo_no_record, api_demo_bad_finish, api_demo_prompt_mismatch,
    api_demo_answer_rewritten, api_demo_model_mismatch
                          the root's `own_graphic.check_graphics(script,
                          pieces, protocols, config)` with `protocols` =
                          `api_demo.protocols_by_record(topic
                          ["api_demo_record"])` of the topic in
                          01-trend-hunter.json (none read - every chat has no
                          record) and `config` = the channel's `api_demo`
                          block (the models' display names,
                          `max_answer_chars`); a `data.date` that is not the
                          day the call was answered is
                          `graphic_value_not_in_footing`.
    api_demo_on_channel_without_origin
                          an `api_chat` on a channel that draws graphics but
                          whose footage-origin has no `api_demo` origin - the
                          chat is not this channel's footage (the chat codes
                          are not asked there). On a channel with no
                          `own_graphic` origin at all the whole order is
                          `graphic_on_channel_without_origin`, as before.

(`api_demo_answer_is_fact` - a claim on the chat, or a sentence footed on the
model's answer - is `check_claims.py`'s.)

Only scripts that order or place a graphic are judged; every other script
prints nothing and is untouched, on any channel. Read-only: no `--write`, no
attempt counter - a finding is fixed in the script before the file leaves the
stage (the claims behind the graphic are `check_claims.py`'s, which reads the
graphic's text like any other viewer text); the Video Editor's `own_graphic`
refusal is the backstop after the plan.

Usage:
    python3 scripts/check_graphics.py <03-content-researcher.json> \\
        [--trend <01-trend-hunter.json>] [--root <checkout>]

`--trend` defaults to the file beside the batch file (with the scale-support
continuation, as the claim rule reads it); without one the quotes are taken
as written and their being in the source is `check_claims.py`'s question.

Exit codes: 0 every graphic stands (or no script has one), 1 a finding,
3 cannot answer (no batch file, no rule at the root). Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0869: --trend spelled any usable way)
from _channel_ids import resolve_channel  # noqa: E402
from check_narration_budget import find_root  # noqa: E402
import _own_graphic as og_loader  # noqa: E402

ANCHORS_FIELD = "visual_anchors"

CODE_NOT_PLACED = "graphic_not_placed"
CODE_NOT_ORDERED = "graphic_not_ordered"
CODE_NO_ORIGIN = "graphic_on_channel_without_origin"
CODE_API_NO_ORIGIN = "api_demo_on_channel_without_origin"     # CF-0690
OWN_CODES = (CODE_NOT_PLACED, CODE_NOT_ORDERED, CODE_NO_ORIGIN, CODE_API_NO_ORIGIN)

OWN_FIXES = {
    CODE_NOT_PLACED: (
        "place it: a `visual_anchors[]` entry {anchor_id, graphic_id, beat_text} on the words "
        "it shows (at least 3 s of voice before the next anchor), or take the graphic and the "
        "claims that stand only on it out"),
    CODE_NOT_ORDERED: (
        "order the graphic the anchor names in `graphics[]`, or give the anchor a pool "
        "`phrase` instead of `graphic_id`"),
    CODE_NO_ORIGIN: (
        "this channel's footage has no `own_graphic` origin: take `graphics[]` out, write "
        "every anchor as a pool `phrase`, and the claims `where: graphic:<id>` with them"),
    CODE_API_NO_ORIGIN: (
        "this channel's footage has no `api_demo` origin: take the `api_chat` graphic out "
        "(and its anchor) - a model's answer through its API is shown only on a channel "
        "whose footage-origin.json admits it (ExampleTech)"),
}
OWN_REFUSALS_RU = {
    CODE_NOT_PLACED: "Графика заказана, но ни один визуальный якорь её не ставит.",
    CODE_NOT_ORDERED: "Якорь ставит графику, которой нет в заказе `graphics[]`.",
    CODE_NO_ORIGIN: "На этом канале нет происхождения own_graphic - своя графика здесь не футаж.",
    CODE_API_NO_ORIGIN: "На этом канале нет происхождения api_demo - чат «через API» здесь не "
                        "футаж.",
}

EXIT_OK, EXIT_FINDING, EXIT_CANNOT_ANSWER = 0, 1, 3


class CannotAnswer(Exception):
    """The question could not be put. Never a verdict on a script."""


def _problem(code, graphic_id=None, detail=None):
    return {"code": code, "graphic_id": graphic_id, "detail": detail,
            "fix": OWN_FIXES[code], "text_ru": OWN_REFUSALS_RU[code]}


def all_codes(og):
    """Every code this check can print: the root's graphic codes, the chat
    codes of CF-0690 (`og.CHAT_CODES`, less `api_demo_answer_is_fact`, which
    is check_claims.py's) and the stage's own."""
    chat = tuple(c for c in getattr(og, "CHAT_CODES", ()) if c != "api_demo_answer_is_fact")
    return tuple(og.FAIL_CODES) + chat + OWN_CODES


def orders_graphics(script):
    """Does the script order or place a graphic at all?"""
    return bool(og_loader.graphics_of(script)) or bool(og_loader.graphic_anchors(script))


def placement_problems(script):
    """`graphic_not_placed` / `graphic_not_ordered` of one script."""
    ordered = [g.get("graphic_id") for g in og_loader.graphics_of(script)
               if isinstance(g, dict) and isinstance(g.get("graphic_id"), str)]
    placed = [a.get(og_loader.ANCHOR_KEY) for a in og_loader.graphic_anchors(script)]
    out = []
    for gid in dict.fromkeys(ordered):
        if gid not in placed:
            out.append(_problem(CODE_NOT_PLACED, gid,
                                f"graphic {gid!r} is ordered and no anchor names it"))
    for a in og_loader.graphic_anchors(script):
        gid = a.get(og_loader.ANCHOR_KEY)
        if gid not in ordered:
            out.append(_problem(CODE_NOT_ORDERED, gid if isinstance(gid, str) else None,
                                f"anchor {a.get('anchor_id')!r} names graphic {gid!r}, which "
                                f"`graphics[]` does not order"))
    return out


def judge(script, og, draws, pieces=None, protocols=None, config=None, api_origin=True):
    """Every problem of one script's graphics - [] when they all stand.
    CF-0690: `protocols` - {record_id: protocol} of the topic's
    `api_demo_record` (None: none read, every chat has no record); `config` -
    the channel's `api_demo` block; `api_origin` - the channel admits the
    `api_demo` origin."""
    if not orders_graphics(script):
        return []
    if not draws:
        return [_problem(CODE_NO_ORIGIN, None,
                         f"{len(og_loader.graphics_of(script))} graphic(s) ordered, "
                         f"{len(og_loader.graphic_anchors(script))} anchor(s) place one")]
    out = list(og.check_graphics(script, pieces, protocols, config))
    chats = [g.get("graphic_id") for g in og_loader.api_chats(script)]
    if chats and not api_origin:
        chat_codes = set(getattr(og, "CHAT_CODES", ())) | {og.FAIL_VALUE_NOT_IN_FOOTING}
        out = [p for p in out if not (p.get("graphic_id") in chats
                                      and p.get("code") in chat_codes)]
        out += [_problem(CODE_API_NO_ORIGIN, gid if isinstance(gid, str) else None,
                         f"graphic {gid!r} is an api_chat") for gid in chats]
    for p in out:
        p.setdefault("text_ru", og.REFUSALS_RU.get(p.get("code")))
        p.setdefault("fix", og.FIXES.get(p.get("code")))
    return out + placement_problems(script)


def _topics(og, batch_path, trend_file=None):
    """{topic_id: topic} of the Trend Hunter's file, or None when there is
    none to read."""
    cl = og.claims
    if trend_file:
        try:
            data = json.loads(Path(trend_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CannotAnswer(f"cannot read {trend_file}: {exc}")
        topics = {t.get("topic_id"): t for t in data.get("topics") or [] if isinstance(t, dict)}
    else:
        if not (batch_path.parent / cl.TOPICS_FILE).is_file():
            return None
        topics = cl.topics_of(batch_path.parent)
    return topics


def _pieces_by_topic(og, topics):
    """{topic_id: {piece_id: piece}} of the topics' support_text, or None."""
    if topics is None:
        return None
    return {tid: og.claims.support_pieces(t) for tid, t in topics.items()}


def _protocols_by_topic(og, topics):
    """CF-0690: {topic_id: {record_id: protocol}} of the topics'
    `api_demo_record`, or None (no Trend Hunter file read)."""
    if topics is None:
        return None
    ad = og.api_demo
    return {tid: ad.protocols_by_record((t or {}).get(ad.RECORD_FIELD))
            for tid, t in topics.items()}


def check_batch(batch_file, trend_file=None, root=None, out=print):
    """Judge every script that orders a graphic. `{script_id: [problem]}`."""
    batch_path = Path(batch_file)
    try:
        data = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    root = Path(root) if root else find_root()
    channel = resolve_channel(data.get("channel"), root)
    scripts = [s for s in data.get("scripts") or [] if isinstance(s, dict) and orders_graphics(s)]
    if not scripts:
        out(f"none  {batch_file}: no script orders a graphic - nothing to judge")
        return {}
    try:
        og = og_loader.own_graphic(root)
    except RuntimeError as exc:
        raise CannotAnswer(str(exc))
    draws = og_loader.channel_draws(channel, root)
    api_origin, api_config = og_loader.channel_api_demo(channel, root)
    topics = _topics(og, batch_path, trend_file) if draws else None
    pieces = _pieces_by_topic(og, topics)
    protocols = _protocols_by_topic(og, topics)
    n_chats = sum(len(og_loader.api_chats(s)) for s in scripts)
    out(f"{batch_file}: {len(scripts)} script(s) with graphics; rule {og.ORIGIN}; channel "
        f"{channel!r} " + ("has the own_graphic origin" if draws else
                           "has NO own_graphic origin (channels/<channel>/footage-origin.json)")
        + ("" if not draws else
           (f"; quotes checked against the topics' support_text" if pieces is not None else
            "; no 01-trend-hunter.json - quotes taken as written"))
        + ("" if not (draws and n_chats) else
           f"; {n_chats} api_chat(s) held to the topics' api_demo_record"
           + ("" if protocols is not None else " (none read - no record)")
           + ("" if api_origin else " - the channel has NO api_demo origin")))
    results = {}
    for script in scripts:
        sid = script.get("script_id")
        topic_pieces = None if pieces is None else pieces.get(script.get("topic_id"), {})
        topic_protocols = None if protocols is None else protocols.get(script.get("topic_id"), {})
        found = results[sid] = judge(script, og, draws, topic_pieces, topic_protocols,
                                     api_config, api_origin)
        n = len(og_loader.graphics_of(script))
        if not found:
            out(f"  ok    {sid}: {n} graphic(s), every value on a declared claim and its "
                f"quote, every one placed")
            continue
        out(f"  FAIL  {sid}: {len(found)} finding(s) over {n} graphic(s)")
        for p in found:
            who = f" [{p['graphic_id']}]" if p.get("graphic_id") else ""
            out(f"    {p['code']}{who}: {p.get('detail') or ''}")
            out(f"      fix: {p.get('fix')}")
            if p.get("text_ru"):
                out(f"      отказ: {p['text_ru']}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--trend", type=_batch_arg.beside(_batch_arg.TREND_FILE),  # CF-0869
                    help="01-trend-hunter.json (default: beside the batch file)")
    ap.add_argument("--root", help="the factory checkout (default: found from this file)")
    args = ap.parse_args(argv)
    try:
        results = check_batch(args.batch_file, args.trend, args.root)
    except CannotAnswer as exc:
        print(f"cannot answer: {exc}")
        return EXIT_CANNOT_ANSWER
    bad = {sid: f for sid, f in results.items() if f}
    if bad:
        print(f"\n{len(bad)} script(s) with graphics to fix (codes and fixes above)")
        return EXIT_FINDING
    return EXIT_OK


@runlog.script("content-researcher", "check-graphics", name="check_graphics.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event (1 = a finding, 2 = usage, 3 = cannot answer). Pure
    Python over the batch files: no external binary, no model call, so no
    `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
