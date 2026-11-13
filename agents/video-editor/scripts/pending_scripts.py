#!/usr/bin/env python3
"""CF-0802: the scripts this stage still owes the batch - what the `new-only`
mode renders.

Why (CF-0798, the user's yes of 2026-10-18): after the frame judge refuses a
video, the reserve round brings a substitute topic in, the Researcher writes
its script into `03` (`merge_batch_file.py --add`), compliance judges only it
(`merge_verdicts.py pending`, merged into `04`), and this stage renders it -
and only it. Every video and every refusal already in `05-video-editor.json`
is the first pass's and is final: re-rendering one would hand the frame judge
a different video under an id it has already judged.

    pending_scripts.py <batch>

prints, one per line, the `script_id`s of `03-content-researcher.json` whose
`04-compliance-checker.json` row clears them for production and that `05`
names in neither `videos[]` nor `refusals[]` - in `03`'s order. Nothing
pending prints nothing on stdout (exit 0); the count line goes to stderr.

"Cleared" is the root funnel's own predicate (`shared/runlog/funnel.py`
`_goes_on` plus the contribution step, CF-0318 / CF-0181), copied here and
pinned against the root's by `tests/test_pending_scripts.py`:

* `verdict` `clear` or `caution` goes on; `review` goes on only with a
  `publication_hold` record on the row (made, and held from publication);
  anything else (`reject`, an old `review`, no verdict) does not;
* a row whose `contribution_check.verdict` is `block` does not, whatever the
  rights verdict;
* a script with no `04` row is not listed - compliance has not judged it, and
  an unjudged script is not this stage's to render.

Exit codes: 0 listed (possibly nothing); 2 when `05` does not exist (no first
pass - the full mode is the one to run), or `03`/`04`/`05` cannot be read.
Pure Python over JSON files - no model call, no render.

CF-0902: the full mode had no such listing - the operator took "the
compliance-cleared scripts" by reading `04` - and batch
`example-film/2026-10-30T1033Z` rendered `lf-2026-10-30-017-script1`
(pine-park) whose `04` row the claims gate had blocked
(`contribution_check.verdict: block`, `claim_unsupported`,
`shot_not_under_words`) a minute before the stage began. Two answers:

    pending_scripts.py <batch> --first-pass

prints the cleared scripts of `03` (the same rule) with no `05` needed - the
list the full mode renders; and `render_video.py` asks `render_refusal()`
before an attempt begins, so a script whose `04` row does not clear it is
never rendered whatever the operator read (exit 5, `NOT CLEARED`). A plan
whose script `04` has no row for (a plan outside a batch, a measurement)
renders as before: the stop enforces compliance's verdict, it adds none.
"""
import json
import sys
from pathlib import Path

SCRIPTS_FILE = "03-content-researcher.json"
VERDICTS_FILE = "04-compliance-checker.json"
EDITOR_FILE = "05-video-editor.json"

# shared/runlog/funnel.py: PUBLISH_VERDICTS, PRODUCTION_VERDICTS,
# PUBLICATION_HOLD_KEY, CONTRIBUTION_KEY, CONTRIBUTION_BLOCK.
PUBLISH_VERDICTS = ("clear", "caution")
PRODUCTION_VERDICTS = ("clear", "caution", "review")
PUBLICATION_HOLD_KEY = "publication_hold"
CONTRIBUTION_KEY = "contribution_check"
CONTRIBUTION_BLOCK = "block"

USAGE = "usage: pending_scripts.py <batch> [--first-pass]"
FIRST_PASS_FLAG = "--first-pass"
TASK = "CF-0902"
SCORE_LOG_SUFFIX = ".score.json"      # score_log.py: <plan stem>.score.json
PLAN_VERDICT = "plan_check.json"       # plan_check.py's verdict beside the plan


class Refused(Exception):
    """A file this listing needs is missing or not what it should be."""


def cleared(row):
    """Whether a `04` row lets its script be rendered (the funnel's rule)."""
    if not isinstance(row, dict):
        return False
    verdict = row.get("verdict") or ""
    if verdict in PUBLISH_VERDICTS:
        goes_on = True
    else:
        goes_on = (verdict in PRODUCTION_VERDICTS
                   and isinstance(row.get(PUBLICATION_HOLD_KEY), dict))
    if not goes_on:
        return False
    contribution = row.get(CONTRIBUTION_KEY)
    contribution = contribution if isinstance(contribution, dict) else {}
    return (contribution.get("verdict") or "") != CONTRIBUTION_BLOCK


def why_not(row):
    """The reason a `04` row does not clear its script, in one line."""
    if not isinstance(row, dict):
        return "no row"
    contribution = row.get(CONTRIBUTION_KEY)
    if isinstance(contribution, dict) and contribution.get("verdict") == CONTRIBUTION_BLOCK:
        codes = [f.get("reason_code") for f in contribution.get("failures") or []
                 if isinstance(f, dict) and f.get("reason_code")]
        return (f"contribution_check blocked it ({', '.join(codes) or 'block'}: "
                f"{contribution.get('reason') or '-'})")
    verdict = row.get("verdict") or "none"
    if verdict in PRODUCTION_VERDICTS:
        return f"verdict '{verdict}' without a `{PUBLICATION_HOLD_KEY}` record"
    return f"verdict '{verdict}'"


def _read(path, what):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"{what} does not exist ({path})") from None
    except (OSError, ValueError) as e:
        raise Refused(f"{what} cannot be read ({path}): {e}") from None
    if not isinstance(doc, dict):
        raise Refused(f"{what}: top level is {type(doc).__name__}, not an object")
    return doc


def _rows(doc, key, what):
    rows = doc.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise Refused(f"{what}: `{key}` is {type(rows).__name__}, not a list")
    return [r for r in rows if isinstance(r, dict)]


def owned_ids(d05):
    """`script_id`s `05` already speaks for: a video or a refusal."""
    return {r.get("script_id") for key in ("videos", "refusals")
            for r in _rows(d05, key, EDITOR_FILE) if r.get("script_id")}


def pending(batch):
    """The cleared scripts of the batch that `05` has no entry for, in `03`'s
    order. Raises Refused when `05` is not there (no first pass) or a file
    cannot be read."""
    batch = Path(batch)
    p05 = batch / EDITOR_FILE
    if not p05.exists():
        raise Refused(f"{EDITOR_FILE} does not exist in {batch} - no first pass; "
                      f"`new-only` renders after one, the full mode is the one to run")
    done = owned_ids(_read(p05, EDITOR_FILE))
    d04 = _read(batch / VERDICTS_FILE, VERDICTS_FILE)
    verdicts = {r["script_id"]: r for r in _rows(d04, "results", VERDICTS_FILE)
                if r.get("script_id")}
    d03 = _read(batch / SCRIPTS_FILE, SCRIPTS_FILE)
    out = []
    for s in _rows(d03, "scripts", SCRIPTS_FILE):
        sid = s.get("script_id")
        if not sid or sid in done or sid in out:
            continue
        if cleared(verdicts.get(sid)):
            out.append(sid)
    return out


def first_pass(batch):
    """CF-0902: the cleared scripts of `03` in its order - what the full mode
    renders. `05` is not read. Raises Refused when `03` or `04` cannot be
    read; prints to stderr nothing, the caller does."""
    batch = Path(batch)
    d04 = _read(batch / VERDICTS_FILE, VERDICTS_FILE)
    verdicts = {r["script_id"]: r for r in _rows(d04, "results", VERDICTS_FILE)
                if r.get("script_id")}
    d03 = _read(batch / SCRIPTS_FILE, SCRIPTS_FILE)
    out, held = [], []
    for s in _rows(d03, "scripts", SCRIPTS_FILE):
        sid = s.get("script_id")
        if not sid or sid in out or sid in [h for h, _ in held]:
            continue
        if cleared(verdicts.get(sid)):
            out.append(sid)
        else:
            held.append((sid, why_not(verdicts.get(sid))))
    return out, held


def _script_id_of(plan_path):
    """The script a plan under <batch>/work/<slug>/ was built for: the score
    log's `script_id`, else the plan check's verdict beside it; None when
    neither says."""
    plan = Path(plan_path)
    for p in (plan.with_name(plan.stem + SCORE_LOG_SUFFIX), plan.with_name(PLAN_VERDICT)):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("script_id"):
            return doc["script_id"]
    return None


def render_refusal(plan_path):
    """CF-0902: `(script_id, why)` when the plan lies at
    <batch>/work/<slug>/ and the batch's `04` has a row for its script that
    does not clear it; None otherwise (no batch, no `04`, no row, an unknown
    script, a cleared row) - render_video.py's stop before an attempt."""
    plan = Path(plan_path).resolve()
    if plan.parent.parent.name != "work":
        return None
    batch = plan.parent.parent.parent
    try:
        d04 = json.loads((batch / VERDICTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sid = _script_id_of(plan)
    if not sid or not isinstance(d04, dict) or not isinstance(d04.get("results"), list):
        return None
    rows = [r for r in d04["results"] if isinstance(r, dict) and r.get("script_id") == sid]
    if not rows or cleared(rows[-1]):
        return None
    return sid, why_not(rows[-1])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    first = FIRST_PASS_FLAG in argv
    argv = [a for a in argv if a != FIRST_PASS_FLAG]
    if len(argv) != 1 or argv[0].startswith("-"):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if first:
            ids, held = first_pass(argv[0])
        else:
            ids, held = pending(argv[0]), []
    except Refused as e:
        print(f"PENDING: ERROR: {e}", file=sys.stderr)
        return 2
    for sid in ids:
        print(sid)
    if first:
        for sid, why in held:
            print(f"PENDING: not cleared, not rendered: {sid} - {why} ({TASK})", file=sys.stderr)
        print(f"PENDING: {len(ids)} script(s) to render (first pass, {TASK}), "
              f"{len(held)} not cleared by 04", file=sys.stderr)
    else:
        print(f"PENDING: {len(ids)} script(s) to render (new-only, CF-0802)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
