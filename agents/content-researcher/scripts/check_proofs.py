#!/usr/bin/env python3
"""CF-0071 (part 3): hold a written batch's `proofs` to the proof layer's contract.

CF-0223 (2026-09-15) moved the anchor this file resolves. It used to be
`comparison.checks[].check_id`, the cancelled position's field; the root's
inserts/proof.json now anchors a proof on `script.production_fact` - the
field CF-0186 named and CF-0183 writes - and the request carries no id for
what it supports, because a script has exactly one production fact. This
file moved with it, in the same change: the contract is the root's, and half
a migration is two checkers disagreeing.

The proof insert - the document a production fact was taken from, shown on
screen for the seconds in which the voice says the fact - is a factory
mechanism switched per channel (inserts/proof.json). Content Researcher
writes the *request*: the exact words the document carries and where those
words came from. The Video Editor captures the page or
typesets the quotation, measures the block and answers. The contract for the
writer's half is the `script_contract` block of the root spec, and this
script reads it from there rather than carrying a copy:

    inserts/proof.json -> script_contract
        script_field               "proofs"
        max_verbatim_chars         72   (= placement.max_reading_seconds * reading_rate_cps)
    inserts/proof.json -> placement.max_inserts_per_video   2
    inserts/proof.json -> capture_priority.order            the accepted methods
    inserts/proof.json -> capture_methods[].rejected        the methods a hint may never name
    channels/<channel>.json -> insert_layers.proof.enabled + capture_method   the channel switch
    patterns/<pattern_id>.json -> proof_layer.allowed                          the pattern gate

Per script the field is:

    "proofs": [
      {"proof_id": "p1",                        # [a-z0-9][a-z0-9_-]*, unique in proofs[]
       "verbatim_text": "<the headline, or the load-bearing sentence of the document>",
       "source": {"url": ..., "publication": ..., "title": ..., "published_at": ..., "handle": ...},
       "capture_method_hint": null | "rendered_quote"}
    ]

There is no `beat_text` and no id: the proof sits on `production_fact
.beat_text` (CF-0186), which is already a verbatim substring of the script's
own prose, and nowhere else. `source.url` is `production_fact.source_url`
and nothing else - the proof shows the document the fact was taken from, so
a proof pointing anywhere else is evidence for a sentence nobody wrote. When
that url is also one of the topic's `evidence.sources[]` records
(01-trend-hunter.json) the three headline fields are copied from it field for
field - never retyped; when it is not, and on today's facts it usually is not
(CF-0184/CF-0237 take them from a reference work's section or the primary
source its footnote names), the writer carries the document's own shown name,
title and date. A post source carries `url`, `handle` (with its @) and
`published_at` from the post, with `publication` and `title` null. With
`--trend <01-trend-hunter.json>` a source url that is in that file is
compared against its record. `--trend` defaults to the 01-trend-hunter.json
beside the batch file (CF-0869); only with no such file anywhere is just the
shape checked.

Absent or `[]` asks for no proof. The field may only be written when BOTH
gates are on; a request on a channel with the switch off, or on a pattern
that refuses, is flagged here with the gate's name (`layer_off` /
`pattern_refused`) - the Video Editor would answer it the same way and
count it, but a writer who wrote it did not read the config.

The time half of the placement rule (the beat's block lasts >= 3.0 s and
>= len(verbatim_text) / 12 s) is the Video Editor's, after alignment; this
script enforces the character half (<= max_verbatim_chars), which is the
same rule stated in text.

Usage:

    python3 scripts/check_proofs.py <03-content-researcher.json | batch folder>
    python3 scripts/check_proofs.py <03-content-researcher.json> --channel <id> --root <checkout> \\
        --trend <01-trend-hunter.json>

The batch is named by its file or by its folder (CF-0869); `--trend` takes
the trend file, or the batch folder / batch file it sits beside, and a path
spelled `<03-content-researcher.json>/../01-trend-hunter.json` is resolved by
text. A value that names no trend file is a usage error (exit 2).

Prints one line per script; exit 0 when every script is clean, 1 otherwise.
Read-only: nothing is written back.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)
import _no_waiting as nw  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

from check_narration_budget import find_root
from check_reactions import load_channel_config, load_patterns

SPEC_PATH = ("inserts", "proof.json")

# CF-0317: the two register points a missing file can end this checker in. An
# insert library that is not in the checkout is a defect of the machine that
# will be there for every batch until somebody fixes it, so it is raised once
# as a standing note and not asked once per run.
POINT_ASSET = "researcher_missing_repo_asset"
POINT_CHANNEL = "researcher_missing_channel_config"
PROOF_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
REQUIRED_KEYS = ("proof_id", "verbatim_text", "source", "capture_method_hint")
SOURCE_KEYS = ("url", "publication", "title", "published_at", "handle")
HEADLINE_COPIED = ("publication", "title", "published_at")
GATE_LAYER_OFF, GATE_PATTERN_REFUSED = "layer_off", "pattern_refused"
GATE_FACT_NOT_FOUND = "fact_not_found"
# The Video Editor's outcome names for the two gates (inserts/proof.json
# metadata.outcomes); the checker names the gate the same way so that a
# reviewer reads one vocabulary on both sides of the hand-off.


def load_spec(root=None):
    """The `script_contract` block of inserts/proof.json plus the ceiling,
    the accepted methods and the rejected ones. Raises when the spec is
    missing - this script carries no contract of its own."""
    root = root or find_root()
    path = root.joinpath(*SPEC_PATH)
    if not path.exists():
        raise nw.CannotAnswer(f"no proof spec at {path}", point=POINT_ASSET, file='inserts/proof.json')
    spec = json.loads(path.read_text())
    sc = spec.get("script_contract")
    if not isinstance(sc, dict) or "max_verbatim_chars" not in sc:
        raise nw.CannotAnswer(f"{path}: script_contract.max_verbatim_chars is missing", point=POINT_ASSET, file='inserts/proof.json')
    placement = spec.get("placement") or {}
    methods = spec.get("capture_methods") or []
    accepted = list((spec.get("capture_priority") or {}).get("order") or [])
    # The hint exists for a post: the method that applies to a post and is
    # not rejected. A headline's chain is the channel's capture_method, not
    # the writer's to pick.
    post_hints = [m["method"] for m in methods
                  if not m.get("rejected") and m["method"] in accepted
                  and "post" in ((m.get("decision") or {}).get("applies_to") or [])]
    return {
        "field": sc.get("script_field", "proofs"),
        "max": int(placement.get("max_inserts_per_video", sc.get("max_proofs_per_script", 2))),
        "max_chars": int(sc["max_verbatim_chars"]),
        "accepted": accepted,
        "rejected": [m["method"] for m in methods if m.get("rejected")],
        "hints": post_hints,
        "min_block": float(placement.get("min_block_seconds", 3.0)),
        "cps": float(placement.get("reading_rate_cps", 12.0)),
        "source": "inserts/proof.json#script_contract",
    }


def channel_switch(channel_cfg):
    """`insert_layers.proof.enabled` with a `capture_method` named, False when
    either is missing - a channel that has not said which chain to start
    has not switched the layer on (inserts/validate_inserts.py reads the
    switch the same way)."""
    layer = (channel_cfg.get("insert_layers") or {}).get("proof") or {}
    return layer.get("enabled") is True and bool(layer.get("capture_method"))


def pattern_gate(pattern):
    """`proof_layer.allowed`, False when absent for the same reason."""
    return ((pattern or {}).get("proof_layer") or {}).get("allowed") is True


def load_trend_sources(path):
    """{topic_id: evidence.sources[]} from a 01-trend-hunter.json; topics
    without `sources` (a Trend Hunter before CF-0071 part 2) map to None."""
    data = json.loads(Path(path).read_text())
    out = {}
    for t in data.get("topics", []):
        out[t.get("topic_id")] = (t.get("evidence") or {}).get("sources")
    return out


def check_source(src, p, fact, spec, evidence):
    """Problems with one proof's `source`. Which kind it is follows from
    `handle`: a post carries one, a page does not. `fact` is the script's
    `production_fact` - its `source_url` is the one url a proof may show."""
    problems = []
    if not isinstance(src, dict):
        return [f"{p}.source: must be an object with keys {list(SOURCE_KEYS)}"]
    missing = [k for k in SOURCE_KEYS if k not in src]
    extra = sorted(set(src) - set(SOURCE_KEYS))
    if missing or extra:
        problems.append(f"{p}.source: keys must be exactly {list(SOURCE_KEYS)}"
                        + (f"; missing {missing}" if missing else "")
                        + (f"; unknown {extra}" if extra else ""))
        return problems
    url = src["url"]
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        problems.append(f"{p}.source.url: must be an http(s) URL, got {url!r}")
    fact_url = (fact or {}).get("source_url")
    if isinstance(fact_url, str) and fact_url and isinstance(url, str) and url != fact_url:
        problems.append(f"{p}.source.url: {url!r} is not the script's production_fact"
                        f".source_url {fact_url!r} - the proof shows the document the fact "
                        f"was taken from and no other (inserts/proof.json "
                        f"script_contract.source_rule)")
    pub = src["published_at"]
    if not isinstance(pub, str) or not ISO_DATE_RE.match(pub):
        problems.append(f"{p}.source.published_at: {pub!r} is not an ISO 8601 date or datetime")
    handle = src["handle"]
    is_post = handle is not None
    if is_post:
        if not isinstance(handle, str) or not handle.startswith("@") or len(handle) < 2:
            problems.append(f"{p}.source.handle: {handle!r} must be the account handle with its @")
        for k in ("publication", "title"):
            if src[k] is not None:
                problems.append(f"{p}.source.{k}: must be null for a post - a post carries a "
                                f"handle, a headline carries publication and title, never both")
        return problems
    # a headline: publication and title are the feed's, and copied
    for k in ("publication", "title"):
        if not isinstance(src[k], str) or not src[k].strip():
            problems.append(f"{p}.source.{k}: a headline needs a non-null {k} (and a post needs "
                            f"a handle) - neither is `source_incomplete`; a record whose title "
                            f"or published_at the feed did not give is unusable, pick another "
                            f"or drop the proof")
    if evidence is not None and isinstance(url, str):
        match = [e for e in evidence if isinstance(e, dict) and e.get("url") == url]
        # Only a url the feed pool actually carries is held to the copy rule.
        # The fact's source is usually outside that pool (CF-0184/CF-0237 read
        # a reference work or the primary source its footnote names), and a
        # document the Trend Hunter never saw has nothing to be copied from.
        if match:
            rec = match[0]
            if rec.get("title") is None or rec.get("published_at") is None:
                problems.append(f"{p}.source: the evidence.sources[] record for this url has a "
                                f"null title or published_at - the feed did not carry it, and "
                                f"a value typed in its place is not the feed's; drop the proof "
                                f"or cite another record")
            for k in HEADLINE_COPIED:
                if src[k] != rec.get(k):
                    problems.append(f"{p}.source.{k}: {src[k]!r} was not copied from the "
                                    f"evidence.sources[] record ({rec.get(k)!r}) - copy it "
                                    f"unchanged, never retype a title or a date")
    return problems


def check_proof(pr, i, script, spec, seen_ids, evidence):
    """Problems with one entry; every message names the field it is about."""
    field = spec["field"]
    p = f"{field}[{i}]"
    problems = []
    if not isinstance(pr, dict):
        return [f"{p}: must be an object, got {type(pr).__name__}"]
    for k in REQUIRED_KEYS:
        if k not in pr:
            problems.append(f"{p}.{k}: missing")
    extra = sorted(set(pr) - set(REQUIRED_KEYS))
    if extra:
        problems.append(f"{p}: unknown key(s) {extra} - a proof names the words and their "
                        f"source; it has no beat_text of its own and no id for what it "
                        f"supports (it sits on the script's production_fact beat), no file "
                        f"and no block - those are the Video Editor's (inserts/proof.json "
                        f"script_contract)")
    proof_id = pr.get("proof_id")
    if "proof_id" in pr:
        if not isinstance(proof_id, str) or not PROOF_ID_RE.match(proof_id):
            problems.append(f"{p}.proof_id: {proof_id!r} must match {PROOF_ID_RE.pattern}")
        elif proof_id in seen_ids:
            problems.append(f"{p}.proof_id: {proof_id!r} is not unique in this script's {field}[]")
        seen_ids.add(proof_id)
    fact = script.get("production_fact") if isinstance(script.get("production_fact"), dict) else None
    if "verbatim_text" in pr:
        vt = pr["verbatim_text"]
        if not isinstance(vt, str) or not vt.strip():
            problems.append(f"{p}.verbatim_text: must be a non-empty string")
        elif len(vt) > spec["max_chars"]:
            problems.append(f"{p}.verbatim_text: {len(vt)} chars, {spec['source']} "
                            f"max_verbatim_chars is {spec['max_chars']} "
                            f"({spec['cps']:g} cps x {spec['max_chars'] / spec['cps']:g} s) - "
                            f"trim to the load-bearing sentence or drop the proof (too_long)")
        elif isinstance(pr.get("source"), dict) and pr["source"].get("handle") is None \
                and isinstance(pr["source"].get("title"), str) and vt not in pr["source"]["title"]:
            problems.append(f"{p}.verbatim_text: not a contiguous substring of source.title - "
                            f"for a headline the words shown are the feed's title, cropped at "
                            f"most, never reworded (inserts/proof.json honesty_rules)")
    if "source" in pr:
        problems += check_source(pr["source"], p, fact, spec, evidence)
    if "capture_method_hint" in pr:
        hint = pr["capture_method_hint"]
        is_post = isinstance(pr.get("source"), dict) and pr["source"].get("handle") is not None
        if hint in spec["rejected"]:
            problems.append(f"{p}.capture_method_hint: {hint!r} is a rejected method "
                            f"(inserts/proof.json capture_methods[].rejected: {spec['rejected']}) "
                            f"- a hint never names one")
        elif hint is not None and hint not in spec["hints"]:
            problems.append(f"{p}.capture_method_hint: {hint!r} must be null or one of "
                            f"{spec['hints']} - the hint exists for a post; a headline's chain "
                            f"is the channel's capture_method, not the writer's to pick")
        elif is_post and hint is None:
            problems.append(f"{p}.capture_method_hint: null on a post - write "
                            f"{spec['hints'][0]!r}: headless_browser does not apply to X, and "
                            f"the chain starts at the quotation")
    return problems


def check_script(script, spec, channel_cfg, patterns, channel="<channel>", evidence_by_topic=None):
    """Problems with one script's `proofs`. Absent or [] is clean."""
    field = spec["field"]
    proofs = script.get(field)
    if proofs is None or proofs == []:
        return []
    if not isinstance(proofs, list):
        return [f"{field}: must be a list, got {type(proofs).__name__}"]
    problems = []
    if not channel_switch(channel_cfg):
        problems.append(f"{field}: written while channels/{channel}.json insert_layers.proof.enabled "
                        f"is not true or capture_method is not set - the layer is off on this "
                        f"channel ({GATE_LAYER_OFF}); drop the field")
    order = script.get("pattern") or {}
    pid = order.get("pattern_id")
    if pid is None:
        problems.append(f"{field}: the script carries no pattern.pattern_id, so the pattern "
                        f"gate proof_layer.allowed cannot be read ({GATE_PATTERN_REFUSED})")
    elif pid not in patterns:
        problems.append(f"{field}: pattern {pid!r} is unknown, so proof_layer.allowed cannot "
                        f"be read ({GATE_PATTERN_REFUSED})")
    elif not pattern_gate(patterns[pid]):
        problems.append(f"{field}: written on pattern {pid!r} whose patterns/{pid}.json "
                        f"proof_layer.allowed is not true ({GATE_PATTERN_REFUSED}); drop the field")
    fact = script.get("production_fact")
    fact_url = fact.get("source_url") if isinstance(fact, dict) else None
    if not isinstance(fact_url, str) or not fact_url.strip():
        problems.append(f"{field}: written on a script whose production_fact carries no "
                        f"source_url - there is no fact for the document to be evidence of "
                        f"and no beat for it to sit on ({GATE_FACT_NOT_FOUND}); drop the "
                        f"field or source the fact")
    elif not isinstance((fact or {}).get("beat_text"), str) or not fact["beat_text"].strip():
        problems.append(f"{field}: the script's production_fact carries no beat_text, so the "
                        f"proof has no block to take (inserts/proof.json "
                        f"script_contract.anchor)")
    if len(proofs) > spec["max"]:
        problems.append(f"{field}: {len(proofs)} entries, inserts/proof.json "
                        f"placement.max_inserts_per_video is {spec['max']}")
    evidence = None
    if evidence_by_topic is not None:
        evidence = evidence_by_topic.get(script.get("topic_id"))
    seen = set()
    for i, pr in enumerate(proofs):
        problems += check_proof(pr, i, script, spec, seen, evidence)
    return problems


def check_batch_data(data, spec, channel_cfg, patterns, channel="<channel>", out=print,
                     evidence_by_topic=None):
    """The whole batch against synthetic or real config dicts. Returns the
    problems, each prefixed with the script id."""
    field = spec["field"]
    problems = []
    for s in data.get("scripts", []):
        sid = s.get("script_id")
        found = check_script(s, spec, channel_cfg, patterns, channel, evidence_by_topic)
        n = len(s.get(field) or []) if isinstance(s.get(field), list) else 0
        if found:
            out(f"  FAIL {sid}: {len(found)} problem(s)")
            problems += [f"{sid}: {p}" for p in found]
        elif n:
            items = ", ".join(
                f"{r.get('proof_id')}="
                f"{(r.get('source') or {}).get('handle') or (r.get('source') or {}).get('publication')}"
                for r in s[field])
            out(f"  ok   {sid}: {n} proof(s) - {items}")
        else:
            out(f"  none {sid}: no proofs requested")
    return problems


def check_batch(path, root=None, channel=None, trend=None):
    root = root or find_root()
    data = json.loads(Path(path).read_text())
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in this field - the file is a dated record and is not
    # rewritten - so resolve it before anything is looked up under it.
    channel = resolve_channel(channel or data.get("channel"), root)
    if not channel:
        raise ValueError(f"{path}: no `channel` field and no --channel given")
    spec = load_spec(root)
    channel_cfg = load_channel_config(channel, root)
    patterns = load_patterns(root)
    evidence = load_trend_sources(trend) if trend else None
    print(f"{path}: {len(data.get('scripts', []))} script(s); channel switch "
          f"insert_layers.proof.enabled={'true' if channel_switch(channel_cfg) else 'false'}, "
          f"max {spec['max']} per script, <= {spec['max_chars']} chars, contract from "
          f"{spec['source']}"
          + (f", sources from {trend}" if trend else ", no --trend: headline sources checked for shape only"))
    return check_batch_data(data, spec, channel_cfg, patterns, channel, evidence_by_topic=evidence)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--channel", default=None, help="override the file's `channel`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--trend", default=None, type=_batch_arg.beside(_batch_arg.TREND_FILE),
                    help="the batch's 01-trend-hunter.json (default: the one beside the batch "
                         "file); headline sources are compared against its "
                         "topics[].evidence.sources[]")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    # CF-0869: the trend file is the batch's own unless told otherwise - the
    # operator no longer has to spell its path (and cannot spell it wrong).
    trend = args.trend or _batch_arg.default_beside(args.batch_file, _batch_arg.TREND_FILE)
    try:
        problems = check_batch(args.batch_file, root=root, channel=args.channel, trend=trend)
    except nw.CannotAnswer as exc:
        # CF-0317: the library or the channel config is not there. That is a
        # fact about this checkout, not about this batch, and it will not
        # change inside the run - so the check names the code the stage
        # records and exits, instead of raising a traceback at a person who
        # is not at the machine.
        print(f"{Path(__file__).name}: {exc}", file=sys.stderr)
        print(nw.refuse(exc.point, **exc.note_fields()), file=sys.stderr)
        return nw.EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


@runlog.script("content-researcher", "check-proofs", name="check_proofs.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = at least one line is not
    ok, 2 = usage) is recorded as `failed` (CF-0107). The check - the proof spec -
    is pure Python over the batch file, the channel config and the specs: no
    external binary, no model call, so no `child` events. Without a batch
    (no RUNLOG_BATCH, no batch-shaped path) the library warns once on stderr
    and records nothing; the check itself is unchanged."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
