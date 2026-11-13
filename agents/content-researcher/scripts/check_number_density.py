#!/usr/bin/env python3
"""CF-0542: how many figures the narrator says - measured on every script.

**The remark.** The user, 2026-10-05, accepting `vanguards-endgame`
(`example-film/2026-10-05T0701Z`): "the narration is heavy going, the narrator
says a lot of numbers". Its commentary put three amounts in one sentence
("two billion nine hundred twenty five point five million to Avatar's two
billion nine hundred twenty three point seven, a gap under two million") and
seven figures in 166 words. The measuring stick is `number_density.py`,
beside this file; this is the check step 6 runs on it.

**The rule is the user's to sign** - until then the check runs in `measure`:
it prints and records, refuses nothing, costs no score, asks for no rewrite.
The mode and the two thresholds are the channel's:

    channels/<channel>.json -> content_researcher.number_density =
        {"mode": "measure" | "enforce" | "off",
         "max_figures_per_sentence": 1,
         "max_figures_per_10_words": 0.4}

Absent (as on every channel today) the check runs on the defaults below:
`measure`, at most one figure in a sentence, at most 0.4 figures per ten
words of narration. Each threshold is a proposal priced on the channel's
accepted videos (`number_density.py history`), not a measured limit.

**What it says per script**, in file order:

    ok       no sentence carries more figures than the threshold and the
             density is within it.
    WARN     (`measure`) over a threshold: the readings, the sentences that
             carry more than one figure, and what would change them. Exit 0.
             With `--write` the script gets `number_density` and the batch's
             `warnings[]` gets a `numbers_heavy` entry (gate
             `number_density`, severity `warn`); nothing else is touched.
    REWRITE  (`enforce`, not signed) the same reading, exit 1: a rewrite of
             the narration's sentences it names - never a drop of the topic.

With `--write` every script judged carries `number_density` (the readings,
the thresholds, the mode and the verdict), and an earlier warning of this
gate for a script that is now within the thresholds is removed.

Usage:

    python3 scripts/check_number_density.py <03-content-researcher.json> [--write]

Exit 0 unless `enforce` found a script to rewrite (1); 2 on bad usage.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)

import _gate_warning as gw  # noqa: E402
import number_density as nd  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

BLOCK = "content_researcher"
KEY = "number_density"
FIELD = "number_density"
GATE = "number_density"
WARNING_CODE = "numbers_heavy"
MODES = ("measure", "enforce", "off")
DEFAULTS = {"mode": "measure", "max_figures_per_sentence": 1,
            "max_figures_per_10_words": 0.4}
DECISION = ("CF-0542: measure until the user signs the rule (remark of 2026-10-05 "
            "on vanguards-endgame 0701Z) - a warning, no rewrite, no score")
OK, WARN, REWRITE = "ok", "WARN", "REWRITE"

ADVICE = ("keep one figure to a sentence; round what the quote gives exactly "
          "(\"almost three billion\" for $2.799 billion); say the difference instead "
          "of two sums (\"under two million apart\"); a year only where the date is "
          "the point")


def settings(config):
    """`(settings, source)`: the channel's `number_density` over the
    defaults, and where they came from."""
    block = ((config or {}).get(BLOCK) or {}).get(KEY)
    out = dict(DEFAULTS)
    if not isinstance(block, dict):
        return out, "defaults (no content_researcher.number_density in the channel)"
    for k in DEFAULTS:
        if k in block:
            out[k] = block[k]
    if out["mode"] not in MODES:
        out["mode"] = DEFAULTS["mode"]
    return out, "channel"


def load_channel_config(channel, root=None):
    """The channel's config, or None when there is none to read."""
    root = Path(root) if root else nd.find_root()
    try:
        path = root / "channels" / f"{resolve_channel(channel, root)}.json"
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return None


def over(reading, cfg):
    """The thresholds this reading is over, as short sentences ([] = within)."""
    out = []
    k = cfg["max_figures_per_sentence"]
    if k is not None and reading["max_per_sentence"] > k:
        out.append(f"{reading['max_per_sentence']} figures in one sentence (> {k})")
    x = cfg["max_figures_per_10_words"]
    if x is not None and reading["per_10_words"] > x:
        out.append(f"{reading['per_10_words']} figures per 10 words (> {x}: "
                   f"{reading['figures']} in {reading['words']} words)")
    return out


def judge_script(script, cfg):
    """`(verdict, reading, reasons)` for one script."""
    reading = nd.measure_script(script)
    reasons = over(reading, cfg)
    if not reasons:
        return OK, reading, []
    return (REWRITE if cfg["mode"] == "enforce" else WARN), reading, reasons


def record_of(reading, cfg, verdict, reasons):
    """What `--write` puts on the script."""
    keep = ("figures", "words", "per_10_words", "max_per_sentence", "max_run",
            "small_numbers", "heavy_sentences")
    rec = {k: reading[k] for k in keep}
    rec.update({"mode": cfg["mode"],
                "max_figures_per_sentence": cfg["max_figures_per_sentence"],
                "max_figures_per_10_words": cfg["max_figures_per_10_words"],
                "verdict": verdict.lower(), "over": reasons, "decision": DECISION})
    return rec


def check_batch_data(data, cfg, write=False, out=print):
    """Judge every script; returns `(rewrites, warnings)`. With `write`, the
    batch dict is updated in place."""
    rewrites, warnings, judged = [], [], []
    for s in data.get("scripts") or []:
        if not isinstance(s, dict):
            continue
        sid, tid = s.get("script_id"), s.get("topic_id")
        verdict, reading, reasons = judge_script(s, cfg)
        judged.append(tid)
        head = (f"{sid}: {reading['figures']} figure(s) in {reading['words']} words "
                f"({reading['per_10_words']}/10), max {reading['max_per_sentence']} in a "
                f"sentence")
        if verdict == OK:
            out(f"  ok   {head}")
        else:
            out(f"  {verdict} {head} - {'; '.join(reasons)}")
            for hs in reading["heavy_sentences"]:
                out(f"      [{hs['field']}] {len(hs['figures'])}: {', '.join(hs['figures'])}")
            out(f"      what to change: {ADVICE}")
            detail = f"{'; '.join(reasons)}; {ADVICE}"
            if verdict == REWRITE:
                rewrites.append(f"{sid}: {detail}")
            else:
                e = gw.entry(tid, sid, GATE, WARNING_CODE, detail, numbers={
                    k: reading[k] for k in ("figures", "words", "per_10_words",
                                            "max_per_sentence", "max_run")})
                e["decision"] = DECISION
                warnings.append(e)
        if write:
            s[FIELD] = record_of(reading, cfg, verdict, reasons)
    if write:
        gw.clear(data, judged, GATE)
        gw.record(data, warnings)
    return rewrites, warnings


def check_batch(path, root=None, write=False, out=print):
    path = Path(path)
    data = json.loads(path.read_text())
    cfg, source = settings(load_channel_config(resolve_channel(data.get("channel"), root), root))
    n = len(data.get("scripts") or [])
    out(f"{path}: {n} script(s); number density in `{cfg['mode']}` ({source}): at most "
        f"{cfg['max_figures_per_sentence']} figure(s) in a sentence, "
        f"{cfg['max_figures_per_10_words']} per 10 words")
    if cfg["mode"] == "off":
        out("  off - nothing measured")
        return [], []
    rewrites, warnings = check_batch_data(data, cfg, write=write, out=out)
    if write:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    elif warnings:
        out(gw.NOT_RECORDED.format(n=len(warnings)))
    return rewrites, warnings


def main(argv=None, root=None, out=print):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--write", action="store_true",
                    help="record `number_density` on every script and the warnings in warnings[]")
    args = ap.parse_args(argv)
    rewrites, _ = check_batch(args.batch_file, root=root, write=args.write, out=out)
    if rewrites:
        out(f"\n{len(rewrites)} narration(s) to rewrite (the sentences, not the topic):")
        for r in rewrites:
            out(f"  - {r}")
        return 1
    return 0


@runlog.script("content-researcher", "check-number-density", name="check_number_density.py")
def cli():
    """Pure Python over the batch file and the channel config: no external
    binary, no model call, so no `child` events. In `measure` the exit is 0
    whatever it found (CF-0107: only a non-zero exit is `failed`)."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
