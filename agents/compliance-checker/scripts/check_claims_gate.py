#!/usr/bin/env python3
"""CF-0553: the claim judge as the second compliance pass' gate.

The writer runs the root's `shared/factrule/claim_judge.py` at the end of its
step 6 (`agents/content-researcher/scripts/check_claims.py`): an independent
reader lists every checkable claim of the finished text, a separate Sonnet
call per declared claim says whether its quote (or shot description) says it,
and a claim without footing is struck or the topic refused as
`claim_unsupported`. This pass does not take the writer's record on trust: it
runs the same judge over the words `03` holds now. The answers are cached per
batch by the hash of each request (`<batch>/work/claim-judge-cache/`), so a
script whose words did not change since the writer's check asks nothing; a
script edited after it (a later gate's rewrite, a hand edit) is judged anew.

A script that does not pass is **blocked**: with `--write` its row of
`04-compliance-checker.json` gets `contribution_check.verdict: block` with a
failure `{"reason_code": "claim_unsupported", "detail": ...}` beside any the
contribution check wrote, and `claims_gate` - the judge's codes, the struck
claims, the calls asked / cached (`opinion_calls` - how many of them were the
judge's second / third opinions on a strike, CF-0579). A block is a block
(CF-0187): the Editor is not handed the script, and the funnel counts a
block whose only failure is this one as `claim_unsupported`. A script that passes gets `claims_gate`
with `action: pass` and nothing else changes. This pass judges no claim by
hand and softens nothing.

Run it over the written file, like `rights_holder_info.py`:

    python3 scripts/check_claims_gate.py <batch>/04-compliance-checker.json [--write]
        [--answer-cmd CMD] [--model sonnet] [--timeout S] [--jobs N] [--partial]

A row of 04 is keyed by `script_id` - the `scripts[].script_id` of 03
(`<topic_id>-script1`), never the topic id. Over the full file
(`04-compliance-checker.json`) every script of 03 must have its row: a script
with none is **04 not done** (CF-0917 - batch example-tech/2026-11-04T0835Z,
04 keyed by topic id, the gate wrote nothing and the batch made 0 videos).
What can be written is still written, the ids without a row go to stderr and
the exit is 4. The new-only staging file (`04-compliance-checker.added.json`,
CF-0800, or any file with `--partial`) holds only the new rows by design:
there a missing row is the expected note and does not change the exit.

exit 0 every script passes, 1 a script blocked, 3 the question could not be
put (no 03 / 04, no judge in the root, or the model could not be asked -
`NOT_LOGGED_IN` when the console claude has no session); nothing is written
on 3. 4 a script of 03 has no row in the full 04 (wins over 1: fix the keys,
run again).
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _runlog import runlog, factory_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "claim_judge.py"
SCRIPTS_FILE = "03-content-researcher.json"
GATE_KEY = "claims_gate"
CONTRIBUTION_KEY = "contribution_check"          # = funnel.CONTRIBUTION_KEY
BLOCK = "block"
REASON_CODE = "claim_unsupported"                # = claim_judge.SKIP_REASON_CODE
EXIT_OK, EXIT_BLOCKED, EXIT_CANNOT_ANSWER, EXIT_NO_ROW = 0, 1, 3, 4
PARTIAL_SUFFIX = ".added.json"                 # CF-0800 new-only staging file


class CannotAnswer(RuntimeError):
    pass


def is_partial(batch04, partial=False):
    """True for a file that holds only some of 03's rows by design."""
    return bool(partial) or Path(batch04).name.endswith(PARTIAL_SUFFIX)


def load_judge(root=None):
    try:
        root = Path(root) if root else factory_root()
    except RuntimeError as exc:
        raise CannotAnswer(str(exc))
    path = root / SHARED_REL
    if not path.is_file():
        raise CannotAnswer(f"{path} not found - the claim judge lives in the factory root")
    spec = importlib.util.spec_from_file_location("factory_claim_judge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


def gate_record(judge, report):
    codes = judge.all_codes(report)
    return {"rule": judge.RULE, "action": report["action"], "codes": sorted(set(codes)),
            "struck": report.get("struck") or [],
            "undeclared": [e["text"] for e in report.get("extracted") or []
                           if not e.get("matched")],
            "asked": report.get("asked", 0), "cached": report.get("cached", 0),
            # CF-0579: of the calls, the second / third opinions on a strike
            "opinion_calls": report.get("opinion_calls", 0),
            "model": report.get("model")}


def block(row, record):
    cc = row.get(CONTRIBUTION_KEY)
    if not isinstance(cc, dict):
        cc = row[CONTRIBUTION_KEY] = {"verdict": BLOCK, "judged": True, "failures": [],
                                      "reason": None, "note": None}
    failures = [f for f in cc.get("failures") or [] if f.get("reason_code") != REASON_CODE]
    what = [f"{s.get('claim_id')} {s.get('text')!r}" for s in record["struck"]] + \
           [f"undeclared {t!r}" for t in record["undeclared"]]
    detail = (f"claims gate ({record['rule']}): {', '.join(record['codes'])}"
              + (f" - {'; '.join(what)}" if what else ""))
    failures.append({"reason_code": REASON_CODE, "detail": detail})
    cc["failures"] = failures
    cc["verdict"] = BLOCK
    reason = cc.get("reason")
    cc["reason"] = (f"{reason}; " if reason else "") + (
        "a claim of the script has no footing in the topic's text (CF-0553) - " + detail)


def check(batch04, root=None, write=False, out=print, judge=None, answer_cmd=None,
          model=None, timeout=None, jobs=None, cache_dir=None, partial=False,
          missing=None):
    """(blocked script ids, {script_id: gate record}).

    `missing`, a list when given, gets the script ids of 03 without a row in
    the file - in the full pass that is 04 not done (CF-0917)."""
    partial = is_partial(batch04, partial)
    p04 = Path(batch04)
    p03 = p04.resolve().parent / SCRIPTS_FILE
    try:
        d04 = json.loads(p04.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {p04}: {exc}")
    if not p03.is_file():
        raise CannotAnswer(f"no {SCRIPTS_FILE} beside {p04}")
    judge = judge or load_judge(root)
    asker = judge.Asker(cache_dir or judge.cache_dir_of(p03), answer_cmd,
                        model or judge.DEFAULT_MODEL, timeout or judge.DEFAULT_TIMEOUT)
    try:
        results = judge.judge_batch_file(p03, asker=asker, jobs=jobs or judge.DEFAULT_JOBS,
                                         root=root)
    except judge.CannotAsk as exc:
        raise CannotAnswer(str(exc))
    except FileNotFoundError as exc:
        raise CannotAnswer(str(exc))
    rows = {r.get("script_id"): r for r in d04.get("results") or [] if isinstance(r, dict)}
    blocked, records = [], {}
    out(f"{p03}: {len(results)} script(s) judged under {judge.RULE} "
        f"({getattr(judge, 'ORIGIN', SHARED_REL)}), {asker.asked} call(s) asked, "
        f"{asker.cached} from the cache, "
        f"{sum(r.get('opinion_calls', 0) for _, r in results)} of them second opinions "
        f"on a strike")
    for sid, report in results:
        rec = records[sid] = gate_record(judge, report)
        if report["action"] == judge.ACTION_PASS:
            out(f"  pass  {sid}")
        else:
            blocked.append(sid)
            out(f"  BLOCK {sid}: {REASON_CODE} ({', '.join(rec['codes'])})")
            for line in judge.render(sid, report).splitlines()[1:]:
                out("    " + line)
        row = rows.get(sid)
        if row is None and missing is not None:
            missing.append(sid)
        if write and row is not None:
            row[GATE_KEY] = rec
            if rec["action"] != judge.ACTION_PASS:
                block(row, rec)
        elif row is None and partial:
            if write:
                out(f"  note: {sid} has no row in {p04.name} - nothing written for it")
        elif row is None:
            out(f"  NO ROW {sid}: 03 has the script, {p04.name} has no row keyed by it"
                f" - 04 is not done (CF-0917)")
    if write:
        p04.write_text(json.dumps(d04, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out(f"  wrote {p04}: `{GATE_KEY}` on {len(records)} row(s), {len(blocked)} blocked")
    return blocked, records


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch04", help="pipeline/<channel>/<batch>/04-compliance-checker.json")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--answer-cmd", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--partial", action="store_true",
                    help="the file holds only some of 03's rows (new-only staging); "
                         f"implied by a name ending in {PARTIAL_SUFFIX}")
    a = ap.parse_args(argv)
    partial = is_partial(a.batch04, a.partial)
    missing = []
    try:
        blocked, _ = check(a.batch04, root=a.root, write=a.write, answer_cmd=a.answer_cmd,
                           model=a.model, timeout=a.timeout, jobs=a.jobs,
                           cache_dir=a.cache_dir, partial=partial, missing=missing)
    except CannotAnswer as exc:
        print(f"check_claims_gate.py: {exc}", file=sys.stderr)
        print("nothing is said about the scripts' claims on this run", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if missing and not partial:
        print(f"check_claims_gate.py: 04 is not done - {len(missing)} script(s) of "
              f"{SCRIPTS_FILE} have no row in {Path(a.batch04).name}: "
              f"{', '.join(missing)}", file=sys.stderr)
        print("results[].script_id must be 03's scripts[].script_id (<topic_id>-script1), "
              "not the topic id; fix the keys (topic_id beside it) and run this again",
              file=sys.stderr)
        return EXIT_NO_ROW
    return EXIT_BLOCKED if blocked else EXIT_OK


@runlog.script("compliance-checker", "check-claims-gate", name="check_claims_gate.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
