#!/usr/bin/env python3
"""CF-0565: hold every `scale` script's comparison to its own arithmetic,
before the voice - the Content Researcher's half of the «масштаб» pattern.

**Why.** A comparison sounds true whether or not its numbers are. Writing
the pattern's own example the first time, «Voyager is past Moscow» came out
of an intuition and was wrong by a factor of a thousand
(`patterns/scale.json` `writing_instruction`). So a scale script carries its
arithmetic as a record, `script.scale` (`scale_footing.fields`:
`quantity` / `reference` / `familiar` / `result`), and the record is
recomputed here, the way `validate_patterns.py check-pairs` measures a
`contrast` script's halves.

**The rule is the root's, one copy:** `patterns/validate_patterns.py`
`check_scale_footing` (every number in its own quote, the quantity's quote in
`script.fact`, the result recomputed within the pattern's tolerance, the
voice's `said_as` spoken and not overstated). This script loads it from the
factory root and adds the one thing only this stage can ask - **the
comparison is declared in `claims[]`** (step 4), so the claim judge of step 6
(`check_claims.py`) holds it to a footing and does not strike it as
undeclared:

    scale_claim_undeclared      no `claims[]` entry whose `text` holds the
                                result's `said_as` (or is held by it)
    scale_claim_number_unquoted that claim's `support` has no quote carrying
                                the number of `scale.quantity` / `reference` /
                                `familiar` - all three numbers stand on a quote

**The ladder** - the same "one rewrite" every counting gate of step 6 gives:

    ok        `scale_check.action == "pass"`; nothing to do.
    REWRITE   (exit 1) the first failure: each finding is printed; fix the
              record or the sentence (change the stand-in, never the source's
              number) and run again. `failed_attempts` becomes 1.
    UNCHANGED (exit 1) the script, its `scale` and its `claims` are the ones
              the last run sent back (CF-0430): nothing judged, nothing spent.
    REFUSE    (exit 4) the second failure of an edited script: with `--write`
              the topic leaves `scripts[]` for `skipped[]` as
              `scale_unsupported`, stage `scripts`, the record beside it.
    FAIL      (exit 1) a scale script with no `script.scale` at all - the
              field, not a verdict; nothing is recorded, no attempt is spent.
    exit 3    the question could not be put (no batch, no rule in the root).

A script of any other pattern is not this check's business: it is listed as
`n/a`, gets no record and is never refused here.

Usage:

    python3 scripts/check_scale.py <03-content-researcher.json> --write
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402

import _rewrite_guard as rg  # noqa: E402
from check_narration_budget import find_root  # noqa: E402

RULE_REL = Path("patterns") / "validate_patterns.py"
PATTERN_ID = "scale"                    # = validate_patterns.SCALE_PATTERN_ID
SCALE_FIELD = "scale"                   # = scale.json scale_footing.record "script.scale"
CLAIMS_FIELD = "claims"
RECORD_KEY = "scale_check"

# The code the funnel and the root's contract have to know
# (shared/runlog/funnel.py FUNNEL_CODES, tests/test_pipeline_contracts.py
# SKIP_CODES) - a code neither knows is a loss recorded as `unexplained`.
SKIP_REASON_CODE = "scale_unsupported"
FUNNEL_STAGE = "scripts"
REWRITES_ALLOWED = 1

EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED = 0, 1, 3, 4
ACTION_PASS, ACTION_FAIL = "pass", "fail"

CLAIM_UNDECLARED = "scale_claim_undeclared"
CLAIM_NUMBER_UNQUOTED = "scale_claim_number_unquoted"

# What each finding asks of the writer - one edit, printed beside it.
FIXES = {
    "scale_record_missing": "write `script.scale` (patterns/scale.json scale_footing.fields)",
    "scale_field_missing": "fill the part the note names: value, unit, quote (and source_url "
                           "for reference / familiar); result needs value, unit and said_as",
    "scale_unit_unknown": "use a unit the recompute knows (scale_footing.rules.note), "
                          "quantity and reference in one kind of measure, familiar and "
                          "result in another",
    "scale_number_not_quoted": "the value has to be a number its own quote says - copy the "
                               "source's sentence, do not retype the number",
    "scale_quantity_not_from_fact": "copy `scale.quantity.quote` out of `fact.quote` / "
                                    "`fact.text` - the scaled number is the video's fact",
    "scale_result_off": "recompute: quantity / reference x familiar; if the result lands "
                        "nowhere a viewer knows, change the stand-in, never the number",
    "scale_overstated": "round toward the less dramatic side and say «about»",
    "scale_said_as_not_spoken": "`said_as` is copied verbatim from hook / commentary / payoff",
    CLAIM_UNDECLARED: "declare the comparison in `claims[]`: its `text` holds `said_as`, its "
                      "`support` quotes all three numbers (step 4)",
    CLAIM_NUMBER_UNQUOTED: "add a `{source, quote}` to the comparison's `support` whose quote "
                           "carries that number, from the topic's support_text - for the "
                           "reference and the familiar size, run scripts/"
                           "scale_support_step.py first and quote the piece it names "
                           "(`piece_id`, in <batch>/01-scale-support.json); a number it "
                           "finds `not_on_page` means another stand-in (CF-0673)",
}


class CannotAnswer(RuntimeError):
    """The question could not be put. Never a verdict on a script."""


def load_rule(root=None):
    """The root's `validate_patterns.py` and its scale pattern. This repo keeps
    no copy of the arithmetic; a root without it cannot answer."""
    root = Path(root) if root else find_root()
    path = root / RULE_REL
    if not path.is_file():
        raise CannotAnswer(f"{path} not found - the scale arithmetic lives in the factory root "
                           f"and this repository keeps no copy of it (CF-0565)")
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    import validate_patterns as vp  # noqa: E402
    if not hasattr(vp, "check_scale_footing"):
        raise CannotAnswer(f"{path} has no check_scale_footing - the root predates CF-0565")
    try:
        pattern = vp.load_patterns()[PATTERN_ID]
    except KeyError:
        raise CannotAnswer(f"no patterns/{PATTERN_ID}.json in {root}")
    return vp, pattern


def is_scale(script):
    return ((script.get("pattern") or {}).get("pattern_id")) == PATTERN_ID


def scale_hash(script):
    """`sha256:` of what the writer controls here: the spoken text and anchors
    (`_rewrite_guard.script_hash`), the arithmetic record and the claims."""
    blob = json.dumps({"script": rg.script_hash(script), SCALE_FIELD: script.get(SCALE_FIELD),
                       CLAIMS_FIELD: script.get(CLAIMS_FIELD)},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def previous_failures(script):
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def unchanged(script):
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("action") != ACTION_FAIL:
        return None
    if record.get(rg.HASH_KEY) != scale_hash(script):
        return None
    return record


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def claim_findings(script, vp):
    """The comparison declared in `claims[]` with a quote for every number."""
    sc = script.get(SCALE_FIELD) or {}
    said = _norm((sc.get("result") or {}).get("said_as"))
    if not said:
        return []           # the rule already returned scale_field_missing for it
    claims = script.get(CLAIMS_FIELD)
    claims = claims if isinstance(claims, list) else []
    match = None
    for c in claims:
        text = _norm(c.get("text")) if isinstance(c, dict) else ""
        if text and (said in text or text in said):
            match = c
            break
    if match is None:
        return [{"kind": CLAIM_UNDECLARED,
                 "note": f"no `claims[]` entry holds the result's said_as {said!r} - the claim "
                         f"judge reads the comparison as a claim and strikes it undeclared"}]
    quotes = [s.get("quote") for s in match.get("support") or []
              if isinstance(s, dict) and isinstance(s.get("quote"), str)]
    out = []
    for name in vp.SCALE_PARTS:
        part = sc.get(name)
        if not isinstance(part, dict) or not isinstance(part.get("value"), (int, float)):
            continue
        if not any(vp._number_in_quote(part["value"], q) for q in quotes):
            out.append({"kind": CLAIM_NUMBER_UNQUOTED,
                        "note": f"claim {match.get('claim_id')!r}: no support quote carries "
                                f"scale.{name}.value {part['value']:g} - every number of the "
                                f"comparison stands on a quote"})
    return out


def judge(script, vp, pattern):
    """One script's record: the root's answer, the claim half, the counter,
    the stamp."""
    report = vp.check_scale_footing(script, pattern)
    findings = list(report["findings"]) + claim_findings(script, vp)
    failed = bool(findings)
    record = {"action": ACTION_FAIL if failed else ACTION_PASS,
              "verdict": "return_for_rewrite" if failed else "ok",
              "computed": report.get("computed"), "findings": findings,
              "rule": f"{RULE_REL} check_scale_footing + claims[] (CF-0565)",
              "reason": report.get("reason")}
    record["failed_attempts"] = previous_failures(script) + failed
    record["rewrites_allowed"] = REWRITES_ALLOWED
    record[rg.HASH_KEY] = scale_hash(script)
    return record


def finding_lines(record):
    out = []
    for f in record.get("findings") or []:
        out.append(f"      {f['kind']}: {f['note']}")
        out.append(f"        -> {FIXES.get(f['kind'], 'fix the record')}")
    return out


def refusal_reason(script, record):
    codes = ", ".join(sorted({f["kind"] for f in record.get("findings") or []}))
    return (f"{script.get('script_id')}: the scale comparison did not hold twice - the second "
            f"failure came after the one rewrite ({codes}). A comparison whose numbers are not "
            f"sourced or whose arithmetic does not recompute is not said (CF-0565: «Voyager is "
            f"past Moscow» was wrong by a factor of a thousand); the topic is dropped rather "
            f"than voiced.")


def skip_entry(script, record):
    return {"topic_id": script.get("topic_id"), "reason_code": SKIP_REASON_CODE,
            "reason": refusal_reason(script, record), "stage": FUNNEL_STAGE,
            RECORD_KEY: record}


def check_batch(batch_file, root=None, write=False, out=print, rule=None):
    """Judge every scale script of the batch. Returns `(problems, records,
    refused)` as the other counting gates do."""
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    vp, pattern = rule or load_rule(root)
    scripts = data.get("scripts") or []
    scale = [s for s in scripts if is_scale(s)]
    out(f"{batch_file}: {len(scale)} scale script(s) of {len(scripts)}; arithmetic under "
        f"{RULE_REL} check_scale_footing; one rewrite, then the topic is refused as "
        f"`{SKIP_REASON_CODE}`")

    problems, records, refused, bumped = [], {}, [], 0
    for script in scripts:
        sid = script.get("script_id")
        if not is_scale(script):
            continue
        if not isinstance(script.get(SCALE_FIELD), dict):
            out(f"  FAIL      {sid}: `{SCALE_FIELD}` missing on a scale script")
            problems.append(f"{sid}: `{SCALE_FIELD}` missing - write the arithmetic "
                            f"(patterns/scale.json scale_footing.fields, step 5); nothing was "
                            f"judged and no attempt was spent")
            continue
        held = unchanged(script)
        if held is not None:
            out(f"  UNCHANGED {sid}: {rg.UNCHANGED} - the text, anchors, `{SCALE_FIELD}` and "
                f"`{CLAIMS_FIELD}` are the ones the last run sent back; nothing judged, nothing "
                f"spent (failed_attempts stays {held.get('failed_attempts')})")
            problems.append(f"{sid}: {rg.UNCHANGED}")
            if write:
                n = held.get(rg.RERUNS_KEY)
                held[rg.RERUNS_KEY] = (n if isinstance(n, int) and not isinstance(n, bool)
                                       else 0) + 1
                bumped += 1
            continue
        record = records[sid] = judge(script, vp, pattern)
        if record["action"] == ACTION_PASS:
            out(f"  ok        {sid}: {record['reason']}")
            continue
        if record["failed_attempts"] > REWRITES_ALLOWED:
            out(f"  REFUSE    {sid}: {SKIP_REASON_CODE} - failed again after the rewrite")
            for line in finding_lines(record):
                out(line)
            refused.append(script)
            continue
        out(f"  REWRITE   {sid}: {len(record['findings'])} finding(s) - you get one rewrite")
        for line in finding_lines(record):
            out(line)
        problems.append(f"{sid}: " + "; ".join(sorted({f['kind'] for f in record['findings']})))

    # A batch with no scale script (every Reel batch) is left byte for byte as
    # it was: there is nothing to record, so nothing is rewritten.
    if write and (records or refused or bumped):
        for script in scripts:
            record = records.get(script.get("script_id"))
            if record is not None:
                script[RECORD_KEY] = record
        if refused:
            ids = {id(s) for s in refused}
            data["scripts"] = [s for s in scripts if id(s) not in ids]
            data.setdefault("skipped", [])
            for script in refused:
                data["skipped"].append(skip_entry(script, records[script.get("script_id")]))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {batch_file}: `{RECORD_KEY}` on {len(records)} script(s)"
            + (f", {len(refused)} topic(s) moved to skipped[] ({SKIP_REASON_CODE})"
               if refused else ""))
    elif refused:
        out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but nothing "
            f"was recorded - re-run with --write so the funnel sees the loss")
    return problems, records, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--write", action="store_true",
                    help=f"write `{RECORD_KEY}` onto every judged scale script and move a "
                         f"refused topic to skipped[] as `{SKIP_REASON_CODE}`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else find_root()
    try:
        problems, _, refused = check_batch(args.batch_file, root=root, write=args.write)
    except CannotAnswer as exc:
        print(f"check_scale.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts on this run", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} script(s) to rewrite or fix:")
        for p in problems:
            print(f"  - {p}")
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}`"
              + ("" if args.write else " and nothing was recorded (--write)"))
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-scale", name="check_scale.py")
def cli():
    """The command-line entry (CF-0107): 1 = rewrite / fix the field, 3 = the
    question could not be put, 4 = a topic refused - each recorded as
    `failed`. Arithmetic over the file and the root's pattern; no external
    binary, no model, no network, so no `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
