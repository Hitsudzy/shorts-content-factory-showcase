#!/usr/bin/env python3
"""CF-0800: the second pass over the scripts - judge only the new ones and
merge their verdicts into `04-compliance-checker.json`, never rewriting a
verdict that is already there.

Why (CF-0798, the user's yes of 2026-10-18): after the frame judge refuses a
video, footage-indexer hands its slot to a reserve topic
(`01b reserve_substitution.substitutions[]`, `at: "frame_judge_refusal"`),
the researcher adds that topic's script to `03` (`merge_batch_file.py --add`),
and the script stage of compliance has to judge it. Until now a second pass
wrote `04` whole: every script judged again, every verdict a fresh model
reading - a script the editor already rendered could come back with another
verdict than the one its video was made under. In this mode the verdicts of
the first pass are frozen: the pass judges only the scripts `04` has no row
for, writes them to a staging file, and this script folds them in.

    merge_verdicts.py pending <batch>/04-compliance-checker.json
    merge_verdicts.py merge <batch>/04-compliance-checker.json <staging.json>
                      [--reason TEXT] [--dry-run] [--keep]

`pending` prints, one per line, the `script_id`s of `03-content-researcher.json`
(beside `04`) that `04` has no verdict for, in `03`'s order - the list the
pass judges and nothing else. Nothing pending prints nothing (exit 0).

`merge` appends the staging file's `results[]` to `04` and records the merge:

* every row already in `04` stays as it was - same values, and on a `04`
  written the usual way (`json.dumps(indent=2, ensure_ascii=False)`, every
  batch since 2026-10-05 but one) the same bytes;
* a staging row whose `script_id` already has a verdict in `04` is
  **refused, not skipped** - the whole merge is, exit 2, nothing written: a
  verdict changed by a second pass is the defect this mode exists to stop,
  and a quiet skip would hide a pass that judged what it was not given;
* a staging row for a script that is not in `03`, a duplicate id, a row
  without `script_id`/`verdict`, or a staging file of another batch or
  another pass is refused the same way;
* an empty staging `results[]` is a no-op - `04` is not touched;
* `merges[]` at the top level of `04` gets one record per merge: when, why
  (`--reason`, default "after frame judge reserve"), which scripts were added
  with their verdicts and, from `01b`, the reserve substitution that brought
  each topic in, and the counts before and after;
* the staging file is removed after it has been consumed (`--keep` keeps it).

The verdict keys of `04` are not recomputed because `04` carries none: the
counts readers use (`shared/runlog/funnel.py`, `gate_price.py`, the stage's
`--note "<N> verdicts, <K> blocked"`) are counted from `results[]` every time,
so an appended row is counted the moment it is there. The script prints the
note line for the stage-done marker.

Exit codes: 0 merged / nothing to merge / pending listed; 2 refused or bad
usage (nothing written). Pure Python over JSON files - no model call.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _channel_ids import resolve_channel  # noqa: E402
from _runlog import runlog  # noqa: E402
from _cli import screen  # noqa: E402

TASK = "CF-0800"
VERDICTS_FILE = "04-compliance-checker.json"
SCRIPTS_FILE = "03-content-researcher.json"
FOOTAGE_FILE = "01b-footage-index.json"
STAGE_CHECKED = "03-content-researcher"
# The name the skill writes the new verdicts under, beside `04`.
STAGING_NAME = "04-compliance-checker.added.json"
DEFAULT_REASON = "after frame judge reserve"
MERGES_KEY = "merges"
BLOCK = "block"
EXIT_OK, EXIT_REFUSED = 0, 2

USAGE = ("usage: merge_verdicts.py pending <04-compliance-checker.json>\n"
         "       merge_verdicts.py merge <04-compliance-checker.json> <staging.json> "
         "[--reason TEXT] [--dry-run] [--keep]")
CLI_FLAGS = ("--dry-run", "--keep")
CLI_VALUED = ("--reason",)


class Refused(Exception):
    """The merge would change or invent a verdict, or its input is not the
    batch's; nothing is written."""


def _read(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"no {what} at {path}")
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read {what} {path}: {exc}")


def _dump(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _results(doc, where):
    rows = doc.get("results") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise Refused(f"{where} has no results[] list")
    return rows


def judged_ids(doc):
    return [r.get("script_id") for r in _results(doc, VERDICTS_FILE)
            if isinstance(r, dict) and r.get("script_id")]


def script_ids(p04):
    """`script_id`s of `03` beside `04`, in `03`'s order."""
    d03 = _read(Path(p04).resolve().parent / SCRIPTS_FILE, SCRIPTS_FILE)
    scripts = d03.get("scripts") if isinstance(d03, dict) else None
    if not isinstance(scripts, list):
        raise Refused(f"{SCRIPTS_FILE} has no scripts[] list")
    return [s.get("script_id") for s in scripts if isinstance(s, dict) and s.get("script_id")]


def pending(p04):
    """The scripts of `03` that `04` has no verdict for - what the pass judges."""
    done = set(judged_ids(_read(p04, VERDICTS_FILE)))
    return [sid for sid in script_ids(p04) if sid not in done]


def substitutions(p04):
    """{topic_id: substitution record} from `01b` beside `04`; {} without one."""
    p01b = Path(p04).resolve().parent / FOOTAGE_FILE
    try:
        d = json.loads(p01b.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rs = d.get("reserve_substitution") if isinstance(d, dict) else None
    subs = rs.get("substitutions") if isinstance(rs, dict) else None
    out = {}
    for s in subs or []:
        if isinstance(s, dict) and s.get("topic_id"):
            out[s["topic_id"]] = s  # the last one that brought the topic in
    return out


def _same_batch(d04, staged):
    for key in ("batch_id", "stage_checked"):
        if staged.get(key) != d04.get(key):
            raise Refused(f"the staging file's {key} is {staged.get(key)!r}, "
                          f"{VERDICTS_FILE}'s is {d04.get(key)!r} - not this batch's pass")
    if d04.get("stage_checked") != STAGE_CHECKED:
        raise Refused(f"{VERDICTS_FILE} is a pass over {d04.get('stage_checked')!r}; "
                      f"only the pass over {STAGE_CHECKED!r} merges new scripts")
    a, b = resolve_channel(d04.get("channel") or ""), resolve_channel(staged.get("channel") or "")
    if a != b:
        raise Refused(f"the staging file's channel is {b!r}, {VERDICTS_FILE}'s is {a!r}")


def merge_docs(d04, staged, in_03, subs, reason=DEFAULT_REASON, when=None):
    """`(merged doc, added rows)`; `(d04, [])` unchanged when there is nothing
    to add. Raises Refused before anything is changed."""
    _same_batch(d04, staged)
    old = _results(d04, VERDICTS_FILE)
    new = _results(staged, "the staging file")
    judged = set(judged_ids(d04))
    known = set(in_03)
    seen = set()
    for row in new:
        if not isinstance(row, dict) or not row.get("script_id"):
            raise Refused("a staging row has no script_id")
        sid = row["script_id"]
        if not row.get("verdict"):
            raise Refused(f"{sid}: the staging row has no verdict")
        if sid in judged:
            raise Refused(f"{sid} already has a verdict in {VERDICTS_FILE}; this mode "
                          f"adds verdicts for new scripts and never changes one "
                          f"(CF-0800) - nothing merged")
        if sid in seen:
            raise Refused(f"{sid} appears twice in the staging file")
        if sid not in known:
            raise Refused(f"{sid} is not a script of {SCRIPTS_FILE}")
        seen.add(sid)
    if not new:
        return d04, []
    added = []
    for row in new:
        cc = row.get("contribution_check") if isinstance(row.get("contribution_check"), dict) else {}
        sub = subs.get(row.get("topic_id"))
        added.append({
            "script_id": row["script_id"],
            "topic_id": row.get("topic_id"),
            "verdict": row["verdict"],
            "contribution_verdict": cc.get("verdict"),
            "substitution": ({k: sub.get(k) for k in ("at", "replaced", "replaced_reason_code",
                                                      "replaced_stage", "reason_code")}
                             if sub else None),
        })
    out = dict(d04)  # top-level order kept; old rows are the same objects
    out["results"] = list(old) + list(new)
    merges = list(out.get(MERGES_KEY) or [])
    merges.append({
        "task": TASK,
        "at": when or _now(),
        "mode": "new-only",
        "reason": reason,
        "added": added,
        "results_before": len(old),
        "results_after": len(out["results"]),
        "blocked_added": sum(1 for a in added if a["contribution_verdict"] == BLOCK),
    })
    out[MERGES_KEY] = merges
    return out, added


def note_line(doc):
    rows = [r for r in doc.get("results") or [] if isinstance(r, dict)]
    blocked = sum(1 for r in rows
                  if isinstance(r.get("contribution_check"), dict)
                  and r["contribution_check"].get("verdict") == BLOCK)
    return f"{len(rows)} verdicts, {blocked} blocked (after 03-content-researcher)"


def _write_atomic(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge(p04, staging, reason=DEFAULT_REASON, dry_run=False, keep=False, out=print,
          when=None):
    """Merge the staging file into `04`; returns the added rows."""
    p04, staging = Path(p04), Path(staging)
    if p04.resolve() == staging.resolve():
        raise Refused(f"the staging file is {VERDICTS_FILE} itself")
    original = p04.read_text(encoding="utf-8") if p04.is_file() else None
    if original is None:
        raise Refused(f"no {VERDICTS_FILE} at {p04} - with no first pass there is "
                      f"nothing to merge into; run the full pass")
    try:
        d04 = json.loads(original)
    except ValueError as exc:
        raise Refused(f"cannot read {p04}: {exc}")
    staged = _read(staging, "staging file")
    merged, added = merge_docs(d04, staged, script_ids(p04), substitutions(p04),
                               reason=reason, when=when)
    if not added:
        out(f"{staging.name}: no new verdicts - {p04.name} not touched")
    else:
        for a in added:
            sub = a["substitution"]
            out(f"  + {a['script_id']}: {a['verdict']}"
                + (f", contribution {a['contribution_verdict']}" if a["contribution_verdict"] else "")
                + (f" (takes the slot of {sub.get('replaced')}, {sub.get('at')})" if sub else ""))
        if not dry_run:
            text = _dump(merged)
            # The old rows' bytes: on a canonically written 04 the merged text
            # starts with the same rows, written the same way.
            _write_atomic(p04, text)
        out(f"{p04.name}: {len(added)} verdict(s) added after {len(d04['results'])} "
            f"kept unchanged ({reason})" + (" (dry run, nothing written)" if dry_run else ""))
    if not dry_run and not keep and staging.exists():
        staging.unlink()
    out(f"note: {note_line(merged)}")
    return added


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen(argv, USAGE, flags=CLI_FLAGS, valued=CLI_VALUED)
    if rc is not None:
        return rc
    reason = DEFAULT_REASON
    if "--reason" in argv:
        i = argv.index("--reason")
        if i + 1 >= len(argv) or not argv[i + 1].strip():
            print(USAGE, file=sys.stderr)
            return EXIT_REFUSED
        reason = argv[i + 1]
        del argv[i:i + 2]
    dry_run = "--dry-run" in argv
    keep = "--keep" in argv
    argv = [a for a in argv if a not in CLI_FLAGS]
    try:
        if len(argv) == 2 and argv[0] == "pending":
            ids = pending(argv[1])
            for sid in ids:
                print(sid)
            print(f"{len(ids)} script(s) of {SCRIPTS_FILE} without a verdict in "
                  f"{VERDICTS_FILE}", file=sys.stderr)
            return EXIT_OK
        if len(argv) == 3 and argv[0] == "merge":
            merge(argv[1], argv[2], reason=reason, dry_run=dry_run, keep=keep)
            return EXIT_OK
    except Refused as exc:
        print(f"merge_verdicts.py: refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(USAGE, file=sys.stderr)
    return EXIT_REFUSED


@runlog.script("compliance-checker", "merge-verdicts", name="merge_verdicts.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
