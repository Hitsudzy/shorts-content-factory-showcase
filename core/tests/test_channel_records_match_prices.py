#!/usr/bin/env python3
"""CF-0528: a channel config never says something about a rule that the price
table (`shared/gate-prices.json`) says differently.

Two records of one rule that disagree are the class of CF-0159 (a copy of a
rule). The guide of CF-0133 found two:

1. `channels/example-film.json` -> `video_editor.max_still_share_note` quoted
   the price of `score.stretched_still_share` as -1 per p.p., cap -40; the
   row the user re-priced on 2026-09-30 says -0.5 and -20. The leading record
   is the ledger: `shared/score/score.py` (LEDGER) prices the finding that
   `agents/video-editor/scripts/still_share.py` emits, and no code reads the
   note. The copy is gone from the note; the guard below fails any channel
   string that names a priced `score.*` rule next to a price or cap that is
   not the ledger's.

2. `video_editor.two_source_gate` is `measure` in the channel and `warn` in
   the ledger's `decision`. Both are read, by different code, and they say the
   same thing in two vocabularies: the channel switch is what the Editor
   (`source_gate.mode_from_channel`), the Researcher's preflight
   (`check_two_sources.mode_from_config`) and the Indexer's sieve
   (`ingest_batch`, the editor key as fallback) run - `measure` records the
   verdict, writes a warning and refuses nothing; the ledger's
   `decision.mode` is what the triage (`shared/runlog/triage.mode_of`) reads
   FIRST, before the channel, to decide whether the rule refuses in
   production. So the ledger leads (it carries the user's decision of
   2026-09-23, CF-0330) and the channel must stay inside it: a channel switch
   turned to a refusing mode while the decision says `warn` and nothing is
   signed would refuse in production and the triage would still read `warn`
   - the unpriced refusal of CF-0320 that nobody sees.

Prices and decisions are factory-wide (one ledger); switches are per channel
(`channels/<id>.json`). The guard walks every channel config: a channel that
carries no switch (example-tech / example-science, `no_pipeline`) runs the
code's default, which is non-refusing for every rule that has a decision.

The real files are read as repository data (tracked config), never anything
live; the detector's own cases run on stand-ins.
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "shared" / "gate-prices.json"

# The modes of a switch that refuse nothing. A decision row in the ledger only
# ever records one of these (`warn`); `enforce` / `fail` are what a signature
# lifts a rule to (CF-0320).
NON_REFUSING = ("measure", "warn")

RULE_MENTION = re.compile(r"score\.[a-z0-9_]+(?:\.[a-z0-9_]+)*")
PRICE_NEAR = re.compile(r"[-−]?\s?(\d+(?:[.,]\d+)?)\s*(?:per|/\s*p\.?\s?p|за)\b", re.I)
CAP_NEAR = re.compile(r"(?:cap|ceiling|потолок)\s*[-−]?\s?(\d+(?:[.,]\d+)?)", re.I)
WINDOW = 160


def _ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8"))






def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{path}[{i}]")


def _num(s):
    return float(s.replace(",", "."))


def price_copy_errors(text, rules):
    """Errors for a free text that names a priced rule next to a price or cap
    that is not the ledger's. `rules` is the ledger's `rules`. The text after a
    mention, up to the next mention or WINDOW characters, is the rule's."""
    errs = []
    hits = list(RULE_MENTION.finditer(text))
    for i, m in enumerate(hits):
        row = rules.get(m.group(0))
        pen = row.get("penalty") if isinstance(row, dict) else None
        if not isinstance(pen, dict):
            continue
        end = min(m.end() + WINDOW, hits[i + 1].start() if i + 1 < len(hits) else len(text))
        tail = text[m.end():end]
        p = PRICE_NEAR.search(tail)
        if p and pen.get("price") is not None and _num(p.group(1)) != float(pen["price"]):
            errs.append(f"{m.group(0)}: the text says {p.group(1)} per unit, the ledger {pen['price']}")
        c = CAP_NEAR.search(tail)
        if c and pen.get("cap") is not None and _num(c.group(1)) != float(pen["cap"]):
            errs.append(f"{m.group(0)}: the text says cap {c.group(1)}, the ledger {pen['cap']}")
    return errs


def _switch(cfg, rule_name):
    """The channel's switch at the rule's own path, as the triage reads it
    (`shared/runlog/triage.mode_of`): a string, or `mode` of a block. None when
    the channel carries none."""
    d = cfg
    for part in rule_name.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    if isinstance(d, dict):
        d = d.get("mode")
    return d if isinstance(d, str) else (None if d is None else repr(d))


def mode_errors(cfg, ledger_rules):
    """Errors for one channel config against the ledger's decisions: a rule the
    user left at a non-refusing decision, with nothing signed, may not be
    switched to a refusing mode in the channel."""
    errs = []
    for name, row in sorted(ledger_rules.items()):
        dec = row.get("decision") if isinstance(row, dict) else None
        if not isinstance(dec, dict) or row.get("signature"):
            continue
        if str(dec.get("mode", "")).strip().lower() not in NON_REFUSING:
            continue
        sw = _switch(cfg, name)
        if sw is not None and sw.strip().lower() not in NON_REFUSING:
            errs.append(f"{name}: the channel switch is {sw!r}, the ledger's decision is "
                        f"{dec['mode']!r} ({dec.get('task', '?')}) and nothing is signed")
    return errs


# --------------------------------------------------------------------------
# the detectors, on stand-ins
# --------------------------------------------------------------------------

STAND_IN_RULES = {
    "score.stretched_still_share": {"mode": "penalty",
                                    "penalty": {"price": 0.5, "per": "p.p. over 50 %", "cap": 20}},
    "score.still_share": {"mode": "penalty", "penalty": {"price": 0, "per": "p.p. over 25 %", "cap": 25}},
    "video_editor.two_source_gate": {"signature": None,
                                     "decision": {"mode": "warn", "task": "CF-0330"}},
}


def test_the_stale_note_of_cf0418_is_caught():
    old = ("held frames ... count with the pictures toward the soft "
           "`score.stretched_still_share` (-1 per p.p. over 50 %, cap -40, shared/gate-prices.json).")
    errs = price_copy_errors(old, STAND_IN_RULES)
    assert len(errs) == 2, errs
    assert "1 per unit" in errs[0] and "cap 40" in errs[1], errs


def test_a_copy_that_matches_the_ledger_or_names_no_number_passes():
    for text in ("`score.stretched_still_share` (−0.5 per p.p. over 50 %, cap −20)",
                 "`score.stretched_still_share` (-0,5 за п.п., потолок -20)",
                 "toward the soft `score.stretched_still_share` - its price is in shared/gate-prices.json",
                 "`score.unknown_rule` (-9 per p.p., cap -99)"):
        assert price_copy_errors(text, STAND_IN_RULES) == [], text


def test_a_number_after_the_next_mention_belongs_to_that_rule():
    text = ("`score.stretched_still_share` is soft; `score.still_share` costs 0 per p.p. over 25 %, "
            "cap 25")
    assert price_copy_errors(text, STAND_IN_RULES) == []


def test_a_refusing_switch_under_a_warn_decision_is_caught():
    for sw in ("enforce", "Enforce ", {"mode": "enforce", "required": 3}, {"mode": "fail"}):
        errs = mode_errors({"video_editor": {"two_source_gate": sw}}, STAND_IN_RULES)
        assert len(errs) == 1 and "CF-0330" in errs[0], (sw, errs)


def test_a_non_refusing_or_absent_switch_passes():
    for cfg in ({"video_editor": {"two_source_gate": "measure"}},
                {"video_editor": {"two_source_gate": {"mode": "warn"}}},
                {"video_editor": {}}, {"channel_id": "example-tech", "status": "no_pipeline"}):
        assert mode_errors(cfg, STAND_IN_RULES) == [], cfg


def test_a_signed_rule_may_be_switched_on():
    rules = {"video_editor.two_source_gate": {"signature": {"user": "u", "price": 2},
                                              "decision": {"mode": "warn"}}}
    assert mode_errors({"video_editor": {"two_source_gate": "enforce"}}, rules) == []


# --------------------------------------------------------------------------
# the real records (tracked config)
# --------------------------------------------------------------------------









if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
