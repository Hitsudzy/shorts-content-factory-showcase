#!/usr/bin/env python3
"""CF-0533: hold every claim the retelling makes about a real person to the
rule the `fact` field is held to (CF-0438), before the voice.

**Why.** The published `coach-hale` (example-film/2026-10-01T1313Z) said
"Anthony Hart, the actor who played her [Mae], died this year". Anthony Hart
played Rupert; Mae is Annette Bramwell. Every gate of step 6 judged the
script's `fact`; the retelling around it - a model's synthesis of two
Deadline headlines - went through as a given. The user's decision of
2026-10-05: the writer declares every claim `commentary` makes about a real
person in `script.story_claims[]` (step 4), and this check holds them:

    {"kind": "cast", "text", "beat_text",
     "source_url"?, "attribution"?, "actor"?, "character"?}

The rule itself is the root's, one copy: `shared/factrule/story_claims.py`
(`check_story_claims`) - the cast pair against the work's Wikipedia cast
list, every cast actor named in `commentary` covered by a claim (a cast
claim, or a quoted `claims[]` entry naming them). A death / arrest /
departure of a real person is a `claims[]` entry with a quote since CF-0556,
judged by `check_claims.py` - a `person_event` here is `claim_malformed`. This
script loads it by path (as `_factrule.py` loads `fact_rule.py`), hands it
this repo's own CF-0237 client (`wikipedia_api.py`), and does the stage's
half: the record on the script, the one rewrite, the refusal.

**The cache.** `check_story_claims` reads Wikipedia through a disk cache at
the transport seam; without one every call is a request. The cache lives in
the batch: `<batch>/work/wikipedia-cache/` (`--cache-dir` overrides). Per
batch, because (1) a rewrite and the reruns after every later gate's rewrite
ask the same articles again, and they are then answered from disk; (2) the
verdict is made against a cast list somebody can read afterwards - the exact
answer stays beside the `03` it judged; (3) nothing is shared between
batches, so a cast list that changed since last week is read fresh by the
next batch without any expiry rule being trusted, and the batch's own clean-up
takes the cache with it.

**The ladder** - the same "one rewrite" every counting gate of step 6 gives:

    ok        `story_claims_check.action == "pass"`; nothing to do.
    REWRITE   (exit 1) the first failure: the violations are printed with
              what each one asks for; edit the sentence in `commentary` (or
              the claim) and run again. `failed_attempts` becomes 1.
    UNCHANGED (exit 1) the script and its claims are the ones the last run
              sent back (CF-0430): nothing is judged, nothing is spent.
    REFUSE    (exit 4) the second failure of an edited script: with `--write`
              the topic leaves `scripts[]` for `skipped[]` as
              `story_claim_failed`, stage `scripts`, the record beside it.
    FAIL      (exit 1) `story_claims` missing or not a list - the field, not
              a verdict; nothing is recorded and no attempt is spent.
    exit 3    the question could not be put (no batch, no rule in the root).

With `--write` the record goes onto every judged script as
`story_claims_check` - the module's answer verbatim (the root's contract for
`03` reads it) plus `failed_attempts` and `script_hash`, the counter and the
CF-0430 stamp. The stamp covers the spoken text, the anchors and
`story_claims` itself: declaring a missed claim is an edit.

**CF-0543's plot half was retired by CF-0556.** `plot_claims[]` (who killed /
betrayed whom, held to one clause of a headline) is no longer judged here: a
plot claim is a `claims[]` entry with a verbatim quote of the topic's support
text, and `check_claims.py` (the root's claim judge) decides whether the quote
says it - the exam of 2026-10-06 struck Harbourlights' "Zorvath is behind the
kill" there, on the finale's own summary.

Usage:

    python3 scripts/check_story_claims.py <03-content-researcher.json> --write
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402

import _rewrite_guard as rg  # noqa: E402
import wikipedia_api  # noqa: E402
from check_narration_budget import find_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "story_claims.py"
CLAIMS_FIELD = "story_claims"           # = story_claims.CLAIMS_FIELD, pinned by the tests
RECORD_KEY = "story_claims_check"       # = story_claims.CHECK_FIELD
CACHE_REL = Path("work") / "wikipedia-cache"

# The code the funnel and the root's contract have to know
# (shared/runlog/funnel.py FUNNEL_CODES, tests/test_pipeline_contracts.py
# SKIP_CODES) - a code neither knows is a loss recorded as `unexplained`.
SKIP_REASON_CODE = "story_claim_failed"
FUNNEL_STAGE = "scripts"
REWRITES_ALLOWED = 1

EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED = 0, 1, 3, 4

ACTION_PASS, ACTION_FAIL = "pass", "fail"

# What each violation asks of the writer - one edit, printed beside it.
FIXES = {
    "cast_mismatch": "the pair is not on one line of the work's Wikipedia cast list - say the "
                     "pair the list holds (the line is in the detail) or drop the sentence",
    "cast_unverifiable": "the cast list could not be read, and a pair nobody could check is "
                         "not said - take the cast sentence out of `commentary` and its claim "
                         "out of `story_claims`",
    "person_claim_undeclared": "a cast member is named in `commentary` with no claim - declare "
                               "what the sentence says about them (a cast pair here, anything "
                               "else in `claims[]` with its quote), or take the name out",
    "beat_text_not_in_commentary": "`beat_text` must be copied verbatim from `commentary`",
    "claim_malformed": "a claim is an object with `kind: cast`, `text` and `beat_text`; a "
                       "person's death / arrest / departure goes to `claims[]` with its quote "
                       "(CF-0556), not here",
}


class CannotAnswer(RuntimeError):
    """The question could not be put. Never a verdict on a script."""


def load_rule(root=None):
    """The root's `story_claims.py`, loaded by path. This repo keeps no copy
    (`_factrule.py` says why for its sibling); a root without it is an error."""
    root = Path(root) if root else find_root()
    path = root / SHARED_REL
    if not path.is_file():
        raise CannotAnswer(f"{path} not found - the people-claims rule lives in the factory "
                           f"root and this repository keeps no copy of it (CF-0533)")
    spec = importlib.util.spec_from_file_location("story_claims", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


def cache_dir_of(batch_file):
    """`<batch>/work/wikipedia-cache/` - see the module docstring."""
    return Path(batch_file).resolve().parent / CACHE_REL


def claims_hash(script):
    """`sha256:` of what the writer controls here: the spoken text and anchors
    (`_rewrite_guard.script_hash`) and the declared claims."""
    blob = json.dumps({"script": rg.script_hash(script), "claims": script.get(CLAIMS_FIELD)},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def previous_failures(script):
    """Failures already recorded on this script. A failed record with no count
    is one failure: it only exists because a run wrote it."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def unchanged(script):
    """The last record, when it sent back exactly the script there is now."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("action") != ACTION_FAIL:
        return None
    if record.get(rg.HASH_KEY) != claims_hash(script):
        return None
    return record


def violation_lines(record):
    out = []
    for v in record.get("violations") or []:
        where = "commentary" if v.get("claim_index") is None else f"claim {v['claim_index']}"
        detail = v.get("detail")
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        out.append(f"      {v['code']} ({where}{': ' + repr(v['text']) if v.get('text') else ''})"
                   f" - {detail}")
        out.append(f"        -> {FIXES.get(v['code'], 'fix the claim')}")
    return out


def skip_code(rule, record):
    """`story_claim_failed` - the root's `skip_code`."""
    return rule.skip_code(record)


def refusal_reason(script, record, code=SKIP_REASON_CODE):
    codes = ", ".join(sorted({v["code"] for v in record.get("violations") or []}))
    return (f"{script.get('script_id')}: the retelling's claims about real people did not pass "
            f"the CF-0438 rule twice - the second failure came after the one rewrite "
            f"({codes}). A sentence about who plays whom, or a death / arrest / departure, that "
            f"cannot be checked against the work's cast list or a major outlet's attributed "
            f"report is not said (CF-0533: the published coach-hale told the viewer Anthony "
            f"Head played Mae); the topic is dropped rather than voiced.")


def skip_entry(script, record, code=SKIP_REASON_CODE):
    return {"topic_id": script.get("topic_id"), "reason_code": code,
            "reason": refusal_reason(script, record, code), "stage": FUNNEL_STAGE,
            RECORD_KEY: record}


def judge(script, rule, client, wp):
    """One script's record: the rule's answer, the counter, the stamp."""
    record = rule.check_story_claims(script, client=client, wp=wp)
    failed_before = previous_failures(script)
    record["failed_attempts"] = failed_before + (record["action"] == ACTION_FAIL)
    record["rewrites_allowed"] = REWRITES_ALLOWED
    record[rg.HASH_KEY] = claims_hash(script)
    return record


def check_batch(batch_file, root=None, write=False, out=print, rule=None, client=None,
                cache_dir=None, wp=None):
    """Judge every script of the batch. Returns `(problems, records, refused)`:
    `problems` are the scripts to rewrite or fix, `refused` the scripts whose
    topic leaves the batch (written to `skipped[]` with `write`)."""
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    root = Path(root) if root else find_root()
    rule = rule or load_rule(root)
    wp = wp or wikipedia_api
    cache_dir = Path(cache_dir) if cache_dir else cache_dir_of(path)
    # CF-0628: no fact-source list is read. `check_story_claims` takes
    # `sources` and does not use it (the person_event half went to claims[],
    # CF-0556), and the list is a channel's since CF-0561 - reading one here
    # would need the batch's channel for nothing, and a channel without the
    # list would fail a check that never looks at it.
    if client is None:
        client = rule.wikipedia_client(cache_dir=cache_dir, wp=wp)
    scripts = data.get("scripts") or []
    out(f"{batch_file}: {len(scripts)} script(s); people claims under {rule.RULE} "
        f"({getattr(rule, 'ORIGIN', SHARED_REL)}), cast lists cached in {cache_dir}; one "
        f"rewrite, then the topic is refused as `{SKIP_REASON_CODE}`")

    problems, records, refused = [], {}, []
    for script in scripts:
        sid = script.get("script_id")
        claims = script.get(CLAIMS_FIELD)
        if not isinstance(claims, list):
            what = "missing" if CLAIMS_FIELD not in script else f"not a list ({claims!r})"
            out(f"  FAIL      {sid}: `{CLAIMS_FIELD}` {what}")
            problems.append(f"{sid}: `{CLAIMS_FIELD}` {what} - declare every claim "
                            f"`commentary` makes about a real person, `[]` when it makes none "
                            f"(step 4); nothing was judged and no attempt was spent")
            continue
        held = unchanged(script)
        if held is not None:
            out(f"  UNCHANGED {sid}: {rg.UNCHANGED} - the text, anchors and `{CLAIMS_FIELD}` "
                f"are the ones the last run sent back; nothing judged, nothing spent "
                f"(failed_attempts stays {held.get('failed_attempts')})")
            problems.append(f"{sid}: {rg.UNCHANGED}")
            if write:
                n = held.get(rg.RERUNS_KEY)
                held[rg.RERUNS_KEY] = (n if isinstance(n, int) and not isinstance(n, bool)
                                       else 0) + 1
            continue
        record = records[sid] = judge(script, rule, client, wp)
        state = (record.get("cast_source") or {}).get("state")
        if record["action"] == ACTION_PASS:
            out(f"  ok        {sid}: {record['claims']} claim(s) about real people pass "
                f"(cast list: {state})")
            continue
        if record["failed_attempts"] > REWRITES_ALLOWED:
            out(f"  REFUSE    {sid}: {skip_code(rule, record)} - failed again after the rewrite "
                f"(cast list: {state})")
            for line in violation_lines(record):
                out(line)
            refused.append(script)
            continue
        out(f"  REWRITE   {sid}: {len(record['violations'])} violation(s) - you get one "
            f"rewrite (cast list: {state})")
        for line in violation_lines(record):
            out(line)
        problems.append(f"{sid}: " + "; ".join(sorted({v['code'] for v in record['violations']})))

    if write:
        for script in scripts:
            record = records.get(script.get("script_id"))
            if record is not None:
                script[RECORD_KEY] = record
        if refused:
            ids = {id(s) for s in refused}
            data["scripts"] = [s for s in scripts if id(s) not in ids]
            data.setdefault("skipped", [])
            for script in refused:
                rec = records[script.get("script_id")]
                data["skipped"].append(skip_entry(script, rec, skip_code(rule, rec)))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {batch_file}: `{RECORD_KEY}` on {len(records)} script(s)"
            + (f", {len(refused)} topic(s) moved to skipped[] ("
               + ", ".join(sorted({skip_code(rule, records[s.get('script_id')]) for s in refused}))
               + ")" if refused else ""))
    elif refused:
        out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but nothing "
            f"was recorded - re-run with --write so the funnel sees the loss")
    return problems, records, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--write", action="store_true",
                    help=f"write `{RECORD_KEY}` onto every judged script and move a refused "
                         f"topic to skipped[] as `{SKIP_REASON_CODE}`")
    ap.add_argument("--cache-dir", default=None,
                    help=f"Wikipedia answer cache (default: <batch>/{CACHE_REL})")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else find_root()
    try:
        problems, _, refused = check_batch(args.batch_file, root=root, write=args.write,
                                           cache_dir=args.cache_dir)
    except CannotAnswer as exc:
        print(f"check_story_claims.py: {exc}", file=sys.stderr)
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


@runlog.script("content-researcher", "check-story-claims", name="check_story_claims.py")
def cli():
    """The command-line entry (CF-0107): 1 = rewrite / fix the field, 3 = the
    question could not be put, 4 = a topic refused - each recorded as
    `failed`. Wikipedia is read through this repo's CF-0237 client, cached in
    the batch; no external binary and no model, so no `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
