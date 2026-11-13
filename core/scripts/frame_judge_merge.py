#!/usr/bin/env python3
"""CF-0800: the frame judge's second pass - judge only the videos `06` has no
row for and fold them into `06-frame-judge.json`, never rewriting a judgement
that is already there.

Why (CF-0798, the user's yes of 2026-10-18): after the frame judge refuses a
video, footage-indexer hands its slot to a reserve topic
(`01b reserve_substitution.substitutions[]`, `at: "frame_judge_refusal"`,
CF-0799), the Researcher writes its script, compliance judges only it
(`agents/compliance-checker/scripts/merge_verdicts.py`), the Editor renders
it, and the judge has to look at it. A gate that wrote `06` whole would score
every video again - a video already passed (and already the user's) could
come back with another score or another gate. In this mode the rows of the
first pass are frozen: the pass judges only what `pending` names, the gate
writes those rows to a staging file, and `merge` appends them.

    frame_judge_merge.py pending <batch>/06-frame-judge.json
    frame_judge_merge.py merge <batch>/06-frame-judge.json <staging.json>
                         [--reason TEXT] [--dry-run] [--keep]

The gate runs both itself (`frame_judge_gate.py --batch B --new-only`); this
CLI is the same code for the operator and the tests.

`pending` prints, one per line, the `script_id`s of the videos of
`05-video-editor.json` (beside `06`) that the judge owes a verdict on
(`frame_judge_gate.deliverable`, the funnel's own predicate) and that `06`
names neither in `videos[]` nor in `not_judged[]`, in `05`'s order. Nothing
pending prints nothing but the count line (exit 0).

`merge` appends the staging file's `videos[]` (and `not_judged[]`) to `06`:

* every row already in `06` stays as it was - same values and, on a `06`
  written by the gate (`json.dumps(indent=2, ensure_ascii=False)`), the same
  bytes; the top-level `counts` are recounted over all rows (they are a sum
  of the rows, and the funnel counts the rows anyway);
* a staging row whose `script_id` is already in `06` is **refused, not
  skipped** - the whole merge is, exit 2, nothing written: a second score of a
  judged video is the defect this mode exists to stop;
* a staging row for a video `05` does not owe the judge, a duplicate id, a row
  without `script_id`/`gate`, or a staging file of another batch is refused
  the same way;
* an empty staging is a no-op - `06` is not touched;
* `merges[]` at the top level of `06` gets one record per merge: when, why
  (`--reason`, default "after frame judge reserve"), which videos were added
  with their gate, reason code and score line and, from `01b`, the reserve
  substitution that brought each topic in, and the counts before and after;
* the staging file is removed after it has been consumed (`--keep` keeps it).

Exit codes: 0 merged / nothing to merge / pending listed; 2 refused or bad
usage (nothing written). Pure Python over JSON files - no model call.
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0800"
JUDGE_FILE = "06-frame-judge.json"
EDITOR_FILE = "05-video-editor.json"
SCRIPTS_FILE = "03-content-researcher.json"
FOOTAGE_FILE = "01b-footage-index.json"
# The name the gate writes the new rows under, beside `06`.
STAGING_NAME = "06-frame-judge.added.json"
DEFAULT_REASON = "after frame judge reserve"
MERGES_KEY = "merges"
MODE = "new-only"
EXIT_OK, EXIT_REFUSED = 0, 2
USAGE = ("usage: frame_judge_merge.py pending <06-frame-judge.json>\n"
         "       frame_judge_merge.py merge <06-frame-judge.json> <staging.json> "
         "[--reason TEXT] [--dry-run] [--keep]")
_SCRIPT_SUFFIX = re.compile(r"-script\d+$")


class Refused(Exception):
    """The merge would change or invent a judgement, or its input is not the
    batch's; nothing is written."""


def _gate():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import frame_judge_gate  # noqa: PLC0415
    return frame_judge_gate


def _read(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"no {what} at {path}")
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read {what} {path}: {exc}")


def dump(doc):
    """The gate's own layout - the one the old rows' bytes are kept in."""
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(doc, key, where, required=True):
    rows = doc.get(key) if isinstance(doc, dict) else None
    if rows is None and not required:
        return []
    if not isinstance(rows, list):
        raise Refused(f"{where} has no {key}[] list")
    return rows


def judged_ids(doc):
    """`script_id`s `06` already speaks for: judged (`videos[]`) or recorded as
    not judged (`not_judged[]`)."""
    return [r.get("script_id") for key in ("videos", "not_judged")
            for r in _rows(doc, key, JUDGE_FILE, required=key == "videos")
            if isinstance(r, dict) and r.get("script_id")]


def owed_ids(batch):
    """The `script_id`s of `05` the judge owes a verdict on, in `05`'s order."""
    ve = _read(Path(batch) / EDITOR_FILE, EDITOR_FILE)
    return [v["script_id"] for v in _gate().deliverable(ve)]


def pending_of(batch, d06):
    done = set(judged_ids(d06))
    return [sid for sid in owed_ids(batch) if sid not in done]


def pending(p06):
    """The videos of `05` that `06` has no row for - what the pass judges."""
    p06 = Path(p06)
    return pending_of(p06.resolve().parent, _read(p06, JUDGE_FILE))


def _topic_of(batch):
    """{script_id: topic_id} from `03` beside `06`; {} without one."""
    try:
        d = json.loads((Path(batch) / SCRIPTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {s["script_id"]: s.get("topic_id") for s in (d or {}).get("scripts") or []
            if isinstance(s, dict) and s.get("script_id")}


def substitutions(batch):
    """{topic_id: the substitution record that brought it in} from `01b`."""
    try:
        d = json.loads((Path(batch) / FOOTAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rs = d.get("reserve_substitution") if isinstance(d, dict) else None
    out = {}
    for s in (rs or {}).get("substitutions") or [] if isinstance(rs, dict) else []:
        if isinstance(s, dict) and s.get("topic_id"):
            out[s["topic_id"]] = s
    return out


def _same_batch(d06, staged):
    a, b = d06.get("batch_id"), staged.get("batch_id")
    if a and b and a != b:
        raise Refused(f"the staging file's batch_id is {b!r}, {JUDGE_FILE}'s is {a!r} - "
                      f"not this batch's judgement")
    # A batch written before a rename carries the former id; compare current ids.
    ids = _gate().channel_ids
    ca, cb = ids.resolve_channel(d06.get("channel")), ids.resolve_channel(staged.get("channel"))
    if ca and cb and ca != cb:
        raise Refused(f"the staging file's channel is {cb!r}, {JUDGE_FILE}'s is {ca!r}")


def recount(doc):
    """`counts` over every row, in the gate's own shape and key order."""
    gate = _gate()
    funnel = gate.funnel
    videos = [r for r in doc.get("videos") or [] if isinstance(r, dict)]
    skipped = [r for r in doc.get("not_judged") or [] if isinstance(r, dict)]
    counts = {"videos": len(videos) + len(skipped),
              "judged": len(videos),
              "passed": sum(1 for v in videos if v.get("gate") == funnel.GATE_PASS),
              "rejected": sum(1 for v in videos if v.get("gate") == funnel.GATE_REJECT),
              "incomplete": sum(1 for v in videos if v.get("gate") == funnel.GATE_INCOMPLETE),
              "not_judged": len(skipped)}
    for word in funnel.FRAME_VERDICTS + ("foreign_text",) + gate.FOOTAGE_DEFECTS:
        counts[word] = sum((v.get("counts") or {}).get(word, 0) for v in videos)
    counts["foreign_core"] = sum(1 for v in videos if (v.get("foreign_core") or {}).get("refuses"))
    # CF-0927: the entries cut from an upload about another work
    counts["other_work"] = sum(len((v.get("other_work") or {}).get("entries") or [])
                               for v in videos)
    return counts


def merge_docs(d06, staged, owed, subs, topic_of, reason=DEFAULT_REASON, when=None):
    """`(merged doc, added records)`; `(d06, [])` unchanged when there is
    nothing to add. Raises Refused before anything is changed."""
    _same_batch(d06, staged)
    old_v = _rows(d06, "videos", JUDGE_FILE)
    old_n = _rows(d06, "not_judged", JUDGE_FILE, required=False)
    new_v = _rows(staged, "videos", "the staging file")
    new_n = _rows(staged, "not_judged", "the staging file", required=False)
    judged = set(judged_ids(d06))
    known = set(owed)
    seen = set()
    for row in list(new_v) + list(new_n):
        if not isinstance(row, dict) or not row.get("script_id"):
            raise Refused("a staging row has no script_id")
        sid = row["script_id"]
        if row in new_v and not row.get("gate"):
            raise Refused(f"{sid}: the staging row has no gate")
        if sid in judged:
            raise Refused(f"{sid} is already in {JUDGE_FILE}; this mode adds judgements of "
                          f"new videos and never changes one (CF-0800) - nothing merged")
        if sid in seen:
            raise Refused(f"{sid} appears twice in the staging file")
        if sid not in known:
            raise Refused(f"{sid} is not a video {EDITOR_FILE} owes the judge")
        seen.add(sid)
    if not new_v and not new_n:
        return d06, []
    added = []
    for row in new_v:
        tid = topic_of.get(row["script_id"]) or _SCRIPT_SUFFIX.sub("", row["script_id"])
        sub = subs.get(tid)
        added.append({
            "script_id": row["script_id"], "slug": row.get("slug"), "topic_id": tid,
            "gate": row.get("gate"), "reason_code": row.get("reason_code"),
            "score_line": row.get("score_line"),
            "substitution": ({k: sub.get(k) for k in ("at", "replaced", "replaced_reason_code",
                                                      "replaced_stage", "reason_code")}
                             if sub else None)})
    for row in new_n:
        added.append({"script_id": row["script_id"], "slug": row.get("slug"),
                      "gate": None, "not_judged": row.get("reason")})
    out = dict(d06)  # top-level order kept; old rows are the same objects
    before = dict(d06.get("counts") or {})
    out["videos"] = list(old_v) + list(new_v)
    if new_n or "not_judged" in d06:
        out["not_judged"] = list(old_n) + list(new_n)
    out["counts"] = recount(out)
    if out["videos"] and out.get("nothing_to_judge"):
        # CF-0707's sentence said the first pass had nothing to judge; it is
        # kept, word for word, in the merge record below
        out["nothing_to_judge"] = None
    merges = list(out.get(MERGES_KEY) or [])
    merges.append({
        "task": TASK, "at": when or _now(), "mode": MODE, "reason": reason,
        "judged_at": staged.get("judged_at"),
        "added": added,
        "videos_before": len(old_v), "videos_after": len(out["videos"]),
        "counts_before": {k: before.get(k) for k in ("videos", "judged", "passed",
                                                     "rejected", "incomplete", "not_judged")},
        "nothing_to_judge_before": d06.get("nothing_to_judge"),
    })
    out[MERGES_KEY] = merges
    return out, added


def note_line(doc):
    c = doc.get("counts") or {}
    return (f"{c.get('judged', 0)} video(s) judged, {c.get('passed', 0)} passed, "
            f"{c.get('rejected', 0)} rejected, {c.get('neutral', 0)} neutral")


def write_atomic(path, text):
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


def merge(p06, staging, reason=DEFAULT_REASON, dry_run=False, keep=False, out=print,
          when=None):
    """Merge the staging file into `06`; returns the added records."""
    p06, staging = Path(p06), Path(staging)
    if p06.resolve() == staging.resolve():
        raise Refused(f"the staging file is {JUDGE_FILE} itself")
    if not p06.is_file():
        raise Refused(f"no {JUDGE_FILE} at {p06} - with no first pass there is nothing to "
                      f"merge into; run the full pass")
    d06 = _read(p06, JUDGE_FILE)
    staged = _read(staging, "staging file")
    batch = p06.resolve().parent
    merged, added = merge_docs(d06, staged, owed_ids(batch), substitutions(batch),
                               _topic_of(batch), reason=reason, when=when)
    if not added:
        out(f"{staging.name}: no new judgement - {p06.name} not touched")
    else:
        for a in added:
            sub = a.get("substitution")
            out(f"  + {a['script_id']}: "
                + (f"{a['gate']}" + (f" ({a['reason_code']})" if a.get("reason_code") else "")
                   if a.get("gate") else f"not judged - {a.get('not_judged')}")
                + (f" (takes the slot of {sub.get('replaced')}, {sub.get('at')})" if sub else ""))
        if not dry_run:
            write_atomic(p06, dump(merged))
        out(f"{p06.name}: {len(added)} video(s) added after {len(d06.get('videos') or [])} "
            f"kept unchanged ({reason})" + (" (dry run, nothing written)" if dry_run else ""))
    if not dry_run and not keep and staging.exists():
        staging.unlink()
    out(f"note: {note_line(merged)}")
    return added


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
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
    argv = [a for a in argv if a not in ("--dry-run", "--keep")]
    if any(a.startswith("-") for a in argv):
        print(USAGE, file=sys.stderr)
        return EXIT_REFUSED
    try:
        if len(argv) == 2 and argv[0] == "pending":
            ids = pending(argv[1])
            for sid in ids:
                print(sid)
            print(f"{len(ids)} video(s) of {EDITOR_FILE} without a row in {JUDGE_FILE}",
                  file=sys.stderr)
            return EXIT_OK
        if len(argv) == 3 and argv[0] == "merge":
            merge(argv[1], argv[2], reason=reason, dry_run=dry_run, keep=keep)
            return EXIT_OK
    except Refused as exc:
        print(f"frame_judge_merge: refused - {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(USAGE, file=sys.stderr)
    return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
