#!/usr/bin/env python3
"""CF-0713: the one way a stage changes a sieve flag somebody already answered.

Batch example-science/2026-10-12T2001Z: the footage-indexer stage flipped nine
NASA mission-control shots of three ESA interview sources from `on_topic:
false` to `true` by hand - "as `false` they would have sunk those sources as
another work" - and nothing but its own last message said so. The flags are
the describer's answer from the frame (CF-0299); the sieve refuses a source on
them. Overruling that answer may be right, but it may not be silent.

    sieve_flag_override.py <batch-dir> <video_id> --shots 3,4,9 --flag on_topic \\
        --to true --why "the frames show the ESA mission's own control room" \\
        [--by WHO] [--footage DIR] [--dry-run]

What it does, for every listed shot whose flag is not already `--to`:

* sets the flag in `<footage>/<video_id>.shots.json` (shot_schema.write_index:
  whole or not at all) and appends to the shot's `flag_overrides[]`
  `{flag, was, to, why, by, at, batch, task}` - the shot carries its history;
* appends one line to `<batch>/work/sieve-flag-overrides.jsonl` (the batch's
  own record, read by nothing but people and tests);
* writes one `sieve_flag_override` event into the batch's RUN_EVENTS.jsonl
  (`video`, `flag`, `to`, `shots`, `was`, `note` = the reason, `by`): the
  root's triage lists every one in TRIAGE.md under its own heading.

It refuses (exit 2, nothing written) a flag that is not one of the
describer's booleans, a shot the index does not have, and a reason shorter
than `MIN_WHY` characters: the reason is the point. A shot already at `--to`
is left alone and counted. It does not run the sieve: run `source_sieve.py`
again afterwards, as the SKILL says.

Exit 0 written (or nothing to change), 2 refused.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402
from _fi_paths import pool_dir  # noqa: E402
import shot_schema  # noqa: E402

TASK = "CF-0713"
EVENT_KIND = "sieve_flag_override"
RECORD = Path("work") / "sieve-flag-overrides.jsonl"
HISTORY = "flag_overrides"
MIN_WHY = 15
DEFAULT_BY = "footage-indexer stage"


def now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_shots(text):
    out = []
    for part in str(text).split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def override(batch, video_id, shots, flag, to, why, by=DEFAULT_BY, footage=None,
             dry_run=False):
    """-> {"video_id", "flag", "to", "changed": [{index, was}], "unchanged": [...]}.
    Raises ValueError (nothing written) on a bad call."""
    why = " ".join(str(why or "").split())
    problems = []
    if flag not in shot_schema.BOOL_FLAGS:
        problems.append(f"--flag {flag!r}: one of {', '.join(shot_schema.BOOL_FLAGS)}")
    if not isinstance(to, bool):
        problems.append("--to must be true or false")
    if len(why) < MIN_WHY:
        problems.append(f"--why: say why the describer's answer is wrong (at least {MIN_WHY} "
                        f"characters) - the reason is what makes the override not silent")
    if not shots:
        problems.append("--shots: name at least one shot index")
    path = Path(footage or pool_dir()) / f"{video_id}.shots.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: not readable ({e})") from None
    by_index = {s.get("index"): s for s in data.get("shots") or [] if isinstance(s, dict)}
    missing = [i for i in shots if i not in by_index]
    if missing:
        problems.append(f"shot(s) {missing} not in {path.name}")
    if problems:
        raise ValueError("; ".join(problems))
    at, changed, unchanged = now_z(), [], []
    for i in shots:
        s = by_index[i]
        was = s.get(flag)
        if was is to:
            unchanged.append(i)
            continue
        s[flag] = to
        s.setdefault(HISTORY, []).append({"flag": flag, "was": was, "to": to, "why": why,
                                          "by": by, "at": at, "batch": str(batch), "task": TASK})
        changed.append({"index": i, "was": was})
    res = {"video_id": video_id, "flag": flag, "to": to, "why": why, "by": by, "at": at,
           "changed": changed, "unchanged": unchanged}
    if dry_run or not changed:
        return res
    shot_schema.require_valid(data, str(path))
    shot_schema.write_index(path, data)
    rec = Path(batch) / RECORD
    rec.parent.mkdir(parents=True, exist_ok=True)
    with open(rec, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(res, task=TASK), ensure_ascii=False) + "\n")
    emit = getattr(runlog, "emit", None)
    if emit is not None:
        emit(batch, EVENT_KIND, os.environ.get("RUNLOG_STAGE") or "footage-indexer",
             video=video_id, status="applied", note=why, flag=flag, to=to, by=by,
             shots=[c["index"] for c in changed], was=[c["was"] for c in changed], task=TASK)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch")
    ap.add_argument("video_id")
    ap.add_argument("--shots", required=True, help="comma list of shot indexes")
    ap.add_argument("--flag", required=True)
    ap.add_argument("--to", required=True, choices=("true", "false"))
    ap.add_argument("--why", required=True)
    ap.add_argument("--by", default=DEFAULT_BY)
    ap.add_argument("--footage", default=None, help="the pool (default <root>/shared/footage)")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)
    try:
        res = override(ns.batch, ns.video_id, parse_shots(ns.shots), ns.flag, ns.to == "true",
                       ns.why, by=ns.by, footage=ns.footage, dry_run=ns.dry_run)
    except ValueError as e:
        print(f"sieve_flag_override: refused - {e}", file=sys.stderr)
        return 2
    print(f"{res['video_id']}: {res['flag']} -> {str(res['to']).lower()} on "
          f"{len(res['changed'])} shot(s) {[c['index'] for c in res['changed']]}, "
          f"{len(res['unchanged'])} already so{' (dry run, nothing written)' if ns.dry_run else ''}; "
          f"why: {res['why']} - run source_sieve.py again")
    return 0


@runlog.script("footage-indexer", "sieve-flag-override", name="sieve_flag_override.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
