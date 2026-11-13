#!/usr/bin/env python3
"""CF-0673: read a `scale` comparison's two other numbers - the reference
and the familiar stand-in's own size - off their pages before they are
quoted, the Content Researcher's half of `shared/factrule/scale_support.py`.

**Why.** A scale script declares its comparison in `claims[]` with a quote
for each of three numbers (step 5, `check_scale.py`): the video's fact, the
reference (the Sun's diameter when the Sun becomes a grapefruit) and the
familiar size (a grapefruit, 10 cm - the end of the page's «from 10 to 15 cm»
that keeps the result the smaller). The claim rule takes a quote only
from a piece of the topic's `support_text`, and the Trend Hunter's text is
the topic's own - the Sun and the grapefruit are not in it - so every scale
script left as `claim_unsupported` (`source_not_in_support_text`).

**What this step does.** It takes the stand-ins the writer chose, each with
its `source_url`, and hands them to the root's module: the page is read
through the channel's door (`fact-sources.json`: an outlet with `use:
read_text` and `ai_policy.verdict: allowed` - Wikipedia for example-science
today) by the factory's Wikipedia client, cached in
`<batch>/work/wikipedia-cache/`; the passage where the number is written
becomes a piece of the topic's support text in `<batch>/01-scale-support.json`
(`claims.topics_of` appends it, so `check_claims.py` and `check_scale.py`
see it). The 01 is never rewritten. This repository keeps no copy of the
rule: the module is loaded from the factory root by path.

**The answer, per stand-in** (`scale_support.STATES`):

    ok            the number stands on the page: quote it from the piece
                  `piece_id` (copy the sentence, do not retype the number)
    not_on_page   the page was read and does not write that number - change
                  the stand-in, never the number («no invented facts»)
    closed        the channel does not read that outlet - take the number
                  from a page it reads, or change the stand-in
    no_page       no such article (or not an English Wikipedia article)
    unreachable   the page could not be read now - run again
    malformed     the request lacks its `source_url`, or a value / quote
    no_gate       no door - nothing is read (never on this CLI)

Exit 0 every stand-in `ok`; 1 at least one not confirmed (each printed with
what it asks for); 3 the question could not be put (no batch, no topic, no
rule in the root, the channel's list cannot be had). Usage errors are 2.

Usage:

    python3 scripts/scale_support_step.py <batch-dir> --topic <topic_id> \\
        --reference https://en.wikipedia.org/wiki/Sun 1391400 km \\
        --familiar https://en.wikipedia.org/wiki/Grapefruit 10 cm \\
        [--reference-name "the Sun's diameter"] [--familiar-name grapefruit] \\
        [--reference-quote TEXT] [--familiar-quote TEXT] [--channel <id>]

    python3 scripts/scale_support_step.py <batch-dir> --topic <topic_id> \\
        --requests requests.json      # [{part, name, source_url, value, unit[, quote]}]
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402

from check_narration_budget import find_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "scale_support.py"
MODULE_NAME = "factory_scale_support"
CACHE_REL = Path("work") / "wikipedia-cache"
TOPICS_FILE = "01-trend-hunter.json"

EXIT_OK, EXIT_UNCONFIRMED, EXIT_CANNOT_ANSWER = 0, 1, 3

# What each outcome asks of the writer - printed under it.
HINTS = {
    "ok": "quote from the piece `{piece_id}`: copy the sentence that holds the number into "
          "`scale.{part}.quote` and into the comparison's claim as "
          "{{\"source\": \"{piece_id}\", \"quote\": ...}} - do not retype the number",
    "not_on_page": "the page does not write this number: change the stand-in (another "
                   "familiar object, another reference) and run again - never the number",
    "closed": "the channel does not read this outlet (fact-sources.json): take the number "
              "from a page it reads (Wikipedia), or change the stand-in",
    "no_page": "no such article: give the stand-in's English Wikipedia URL "
               "(https://en.wikipedia.org/wiki/...), or change the stand-in",
    "unreachable": "the page could not be read now: run the step again; a number nobody read "
                   "is not quoted - if it stays unreachable, change the stand-in",
    "malformed": "a request needs `source_url` and a positive `value` with its `unit` "
                 "(or a `quote`)",
    "no_gate": "nothing was read: the step reads a page only through the channel's door",
}


class CannotAnswer(RuntimeError):
    """The question could not be put. Never a verdict on a stand-in."""


def load_module(root=None):
    """The root's `scale_support.py`, loaded by path; this repo keeps no copy."""
    root = Path(root) if root else find_root()
    path = (root / SHARED_REL).resolve()
    held = sys.modules.get(MODULE_NAME)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    if not path.is_file():
        raise CannotAnswer(f"{path} not found - the scale stand-ins are read by the factory "
                           f"root's module and this repository keeps no copy of it (CF-0673)")
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def channel_of(batch_dir, channel=None, root=None):
    """The channel the batch belongs to: `--channel`, else the directory
    above the batch (`pipeline/<channel>/<batch>`), a former id resolved."""
    from _channel_ids import resolve_channel
    name = channel or Path(batch_dir).resolve().parent.name
    try:
        return resolve_channel(name, root)
    except Exception as exc:            # an unknown name is the channel's list's to refuse
        raise CannotAnswer(f"the batch's channel {name!r} cannot be resolved: {exc}")


def channel_sources(channel, root=None):
    """The channel's `fact-sources.json` through `_channel_data.py`."""
    from _channel_data import channel_data
    try:
        return channel_data.fact_sources(channel, root)
    except channel_data.ChannelDataError as exc:
        raise CannotAnswer(f"the fact-sources list of {channel!r} cannot be had: {exc}")


def requests_of(args):
    """The requests from `--requests` or the inline stand-ins."""
    reqs = []
    if args.requests:
        try:
            data = json.loads(Path(args.requests).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CannotAnswer(f"cannot read {args.requests}: {exc}")
        if isinstance(data, dict):
            data = data.get("requests")
        if not isinstance(data, list):
            raise CannotAnswer(f"{args.requests}: a list of requests (or {{\"requests\": [...]}})")
        reqs.extend(data)
    for part in ("reference", "familiar"):
        given = getattr(args, part)
        if not given:
            continue
        url, value, unit = given
        try:
            number = float(value.replace(",", ""))
        except ValueError:
            number = None
        req = {"part": part, "name": getattr(args, f"{part}_name") or part,
               "source_url": url, "value": number, "unit": unit}
        quote = getattr(args, f"{part}_quote")
        if quote:
            req["quote"] = quote
        reqs.append(req)
    return reqs


def topic_of(ss, batch_dir, topic_id):
    """The topic as the claim rule sees it (`claims.topics_of`: its own text
    and the continuation already written)."""
    if not (Path(batch_dir) / TOPICS_FILE).is_file():
        raise CannotAnswer(f"no {TOPICS_FILE} in {batch_dir} - the topic's support text is "
                           f"the Trend Hunter's")
    topic = ss.claims.topics_of(batch_dir).get(topic_id)
    if topic is None:
        raise CannotAnswer(f"no topic {topic_id!r} in {Path(batch_dir) / TOPICS_FILE}")
    return topic


def step(batch_dir, topic_id, requests, sources, client=None, ss=None, root=None,
         cache_dir=None):
    """Read the stand-ins, write the continuation, return `gather`'s result
    and the path written. `client` is the Wikipedia client (the tests hand
    in a stub; the default is the factory's, cached in the batch)."""
    ss = ss or load_module(root)
    batch_dir = Path(batch_dir)
    topic = topic_of(ss, batch_dir, topic_id)
    if client is None:
        wp = ss.wikipedia_api()
        client = wp.cached_client(Path(cache_dir) if cache_dir else batch_dir / CACHE_REL,
                                  tool_name=wp.TOOL_NAME)
    gate = ss.channel_gate(sources)
    read = ss.wikipedia_reader(client)
    result = ss.gather(requests, read, gate, existing=topic.get("support_text") or [])
    path = ss.attach(batch_dir, topic_id, result)
    return result, path


def report_lines(result):
    """One line per stand-in, its hint under it; an `ok` shows the passage
    its quote is copied from."""
    pieces = {p.get("id"): p for p in result.get("pieces") or []}
    out = []
    for r in result.get("requests") or []:
        state = r.get("state")
        what = r.get("name") or r.get("part") or "?"
        value = r.get("value")
        number = (f"{value:g} {r.get('unit') or ''}".strip()
                  if isinstance(value, (int, float)) and not isinstance(value, bool) else "-")
        label = "ok" if state == "ok" else (state or "?").upper()
        out.append(f"  {label:<12}{r.get('part')}: {what} = {number} <- {r.get('source_url')}")
        if r.get("piece_id"):
            out.append(f"      piece_id: {r['piece_id']}")
        if r.get("detail"):
            out.append(f"      {r['detail']}")
        out.append("        -> " + HINTS.get(state, "fix the request").format(
            piece_id=r.get("piece_id"), part=r.get("part")))
        piece = pieces.get(r.get("piece_id"))
        if state == "ok" and piece and piece.get("text"):
            for line in piece["text"].splitlines():
                out.append(f"      | {line}")
    return out


def main(argv=None, sources=None, client=None, out=print):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_dir", help="pipeline/<channel>/<batch>")
    ap.add_argument("--topic", required=True, help="the scale script's topic_id")
    ap.add_argument("--channel", default=None,
                    help="channel id (default: the directory above the batch)")
    ap.add_argument("--requests", default=None,
                    help="JSON file: [{part, name, source_url, value, unit[, quote]}]")
    for part in ("reference", "familiar"):
        ap.add_argument(f"--{part}", nargs=3, metavar=("URL", "VALUE", "UNIT"), default=None,
                        help=f"the {part} stand-in: its page, its number, its unit")
        ap.add_argument(f"--{part}-name", default=None)
        ap.add_argument(f"--{part}-quote", default=None,
                        help="the sentence to find verbatim (it must say the number)")
    ap.add_argument("--cache-dir", default=None,
                    help=f"Wikipedia answer cache (default: <batch>/{CACHE_REL})")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    if not args.requests and not args.reference and not args.familiar:
        ap.error("give --reference / --familiar, or --requests")
    root = Path(args.root).resolve() if args.root else find_root()
    batch_dir = Path(args.batch_dir)
    try:
        if not batch_dir.is_dir():
            raise CannotAnswer(f"{batch_dir} is not a batch directory")
        reqs = requests_of(args)
        ss = load_module(root)
        if sources is None:
            sources = channel_sources(channel_of(batch_dir, args.channel, root), root)
        result, path = step(batch_dir, args.topic, reqs, sources, client=client, ss=ss,
                            root=root, cache_dir=args.cache_dir)
    except CannotAnswer as exc:
        print(f"scale_support_step.py: {exc}", file=sys.stderr)
        print("nothing was read and nothing was written on this run", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    outcomes = result.get("requests") or []
    bad = [r for r in outcomes if r.get("state") != "ok"]
    out(f"{batch_dir} topic {args.topic}: {len(outcomes)} stand-in(s), "
        f"{len(outcomes) - len(bad)} on their pages; pieces in {path}")
    for line in report_lines(result):
        out(line)
    if bad:
        out(f"\n{len(bad)} number(s) not confirmed - no quote of them stands; change the "
            f"stand-in, never the number (CF-0673)")
        return EXIT_UNCONFIRMED
    return EXIT_OK


@runlog.script("content-researcher", "scale-support", name="scale_support_step.py")
def cli():
    """The command-line entry (CF-0107): 1 = a number not confirmed, 3 = the
    question could not be put - each recorded as `failed`."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
