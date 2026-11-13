#!/usr/bin/env python3
"""CF-0567: the factory's own record of an own capture as a `support_text`
piece - what was recorded, where, when, and which steps the take completed.

Why. A «демо» script says aloud where the tool ran ("... running in a public
Hugging Face Space, <owner>/<name>", content-researcher `check_demo.py`
`demo_space_not_named`), and every sentence of a script is footed by a
verbatim quote of a piece of the topic's `support_text` (the root's
`shared/factrule/claims.py`: `{source: <piece id>, quote}`). Until this piece
the capture was only a shot description, so the sentence had no quote to
stand on. The piece is written in plain sentences out of the candidate's
`capture` record (the recorder's sidecar as `fetch_own_capture.py` carried
it), so a quote can be copied from it word for word.

The shape - the keys every piece has (`support_text.py`: `id`, `kind`,
`source`, `title`, `url`, `revision_id`, `revised_at`, `text`) plus its own:

    id           own-capture-<capture id>    (stable: the recording's id)
    kind         own_capture_record
    source       own_capture                 (the factory's own record)
    title        "Own capture of <owner>/<name>" (a label, not quotable text)
    url          the page recorded (https://<sub>.hf.space/)
    revision_id  null, revised_at null        (no page revision to age)
    fetched_at   the capture's time           (claims.py records it, as TVmaze's)
    captured_at, space, space_licence, video_id, capture_file, steps_done
    not_a_fact   true
    text         the sentences below

It is **never the video's fact**: the fact is the primary source's
(fact-sources.json); what a Space outputs is the tool's answer. The piece is
written by `footage_candidates.py` (step 5b), after the fact probe (step 5a)
chose the fact, and nothing that selects a fact reads it; it never changes
`support_check.state`. It is not a second source for a reveal
(`claim_judge.SECOND_SOURCE_KINDS` names RSS and TVmaze only) and it is not a
Wikipedia piece, so the reveal age never reads it.
"""
from datetime import datetime

KIND = "own_capture_record"
SOURCE = "own_capture"
ID_HEAD = "own-capture-"
CANDIDATE_HEAD = "own_capture:"

# How a step of the recorder reads in a sentence. The selectors are
# `fetch_own_capture.py`'s template; anything else is named by its selector.
EXAMPLE_HINT = "gallery"
SUBMIT_HINT = "primary"


def piece_id(candidate):
    """`own-capture-<capture id>` of an own-capture candidate."""
    vid = str((candidate or {}).get("video_id") or "")
    cid = ((candidate or {}).get("capture") or {}).get("id") or \
        (vid[len(CANDIDATE_HEAD):] if vid.startswith(CANDIDATE_HEAD) else vid)
    return f"{ID_HEAD}{cid}"


def _when(stamp):
    """'2026-10-11T12:00:00Z' -> ('2026-10-11', '12:00'), or (stamp, None)."""
    try:
        t = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return (str(stamp) if stamp else None), None
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def _seconds(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return f"{v:g}"


def step_sentence(step):
    """One completed step of the take as words."""
    step = step or {}
    do, sel = step.get("do"), str(step.get("selector") or "")
    secs = _seconds(step.get("seconds"))
    if do == "wait_for":
        return "waited for the app to load"
    if do == "wait":
        return f"waited {secs} seconds" if secs else "waited"
    if do == "click":
        if EXAMPLE_HINT in sel:
            return "clicked the first example"
        if SUBMIT_HINT in sel:
            return "clicked the run button"
        return f"clicked {sel}"
    if do == "type":
        return f"typed \"{step.get('text')}\" into the text box"
    if do == "press":
        return f"pressed {step.get('key')}"
    if do == "scroll":
        return f"scrolled the page by {_seconds(step.get('by'))} pixels"
    return str(do or "an unnamed step")


def completed_steps(capture):
    """The steps of `capture.steps` the recorder reports done with `ok:
    true` (`capture.steps_done`), in order."""
    capture = capture or {}
    steps = capture.get("steps") or []
    out = []
    for done in capture.get("steps_done") or []:
        if not isinstance(done, dict) or done.get("ok") is not True:
            continue
        i = done.get("index")
        step = steps[i] if isinstance(i, int) and 0 <= i < len(steps) else {"do": done.get("do")}
        out.append(step)
    return out


def piece(candidate):
    """The `own_capture_record` piece of one own-capture candidate, or None
    when it names no Space or page."""
    candidate = candidate or {}
    cap = candidate.get("capture") or {}
    space = cap.get("space")
    page = cap.get("page") or candidate.get("source_url")
    if not space or not page:
        return None
    stamp = cap.get("captured_at") or candidate.get("published_at")
    day, hour = _when(stamp)
    steps = completed_steps(cap)
    lines = [f"The factory recorded the tool running in a public Hugging Face Space, {space}, "
             f"at {page}."]
    if day:
        lines.append(f"The recording was made on {day}" + (f" at {hour} UTC." if hour else "."))
    if cap.get("space_licence"):
        lines.append(f"The Space's card names the licence {cap['space_licence']}.")
    if steps:
        lines.append(f"The recording shows {len(steps)} completed step(s).")
        lines += [f"Step {n}: {step_sentence(s)}." for n, s in enumerate(steps, 1)]
    else:
        lines.append("The recording shows the page; no step is reported completed.")
    return {
        "id": piece_id(candidate),
        "kind": KIND,
        "source": SOURCE,
        "title": f"Own capture of {space}",
        "url": page,
        "revision_id": None,
        "revised_at": None,
        "fetched_at": stamp,
        "captured_at": stamp,
        "space": space,
        "space_licence": cap.get("space_licence"),
        "video_id": candidate.get("video_id"),
        "capture_file": candidate.get("capture_file"),
        "steps_done": [step_sentence(s) for s in steps],
        "not_a_fact": True,
        "text": "\n".join(lines),
    }


def merge(pieces, candidates, is_own):
    """-> (support_text with this topic's own-capture pieces replaced by one
    per own capture of `candidates`, the pieces written). Idempotent: a
    second pass over the batch rewrites them, never doubles them."""
    kept = [p for p in pieces or [] if not (isinstance(p, dict) and p.get("kind") == KIND)]
    new = [p for p in (piece(c) for c in candidates or [] if is_own(c)) if p]
    return kept + new, new
