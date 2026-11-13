#!/usr/bin/env python3
"""CF-0434: the score line of every video of one batch, read from its artifacts.

The grill of 2026-09-29 (Q11, Q17, Q20-Q21, Q28; DoD 1.4.7 item 2): each video
carries its score log and tier - in `05-video-editor.json`, in the run summary
and in the message the video comes to the user with. The log is written by the
stages themselves (the Editor's `scripts/score_log.py`: plan, render, QC; the
Researcher's 6b; the frame judge, `scripts/frame_judge_gate.py`), each as one
line of `shared/score/score.py::summary_line()`:

    B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts

This module computes nothing. It reads the line the last stage that scored the
video wrote, in this order:

    06-frame-judge.json  videos[].score_line   the score after the judge
    05-video-editor.json videos[].score_line   the score after QC
    05-video-editor.json refusals[]            a video the score stopped at the
                                               Editor (`score_line`, the stage in
                                               `numbers.stage`)
    03-content-researcher.json skipped[]       a script the score stopped at 6b

and says, per video, where it stands: `ready` (QC passed and the judge, if it
ran, did not refuse), `stopped` (the score put it under N - at `6b`, at the
Editor's stage, or at `judge`), `refused` (another gate took it), or
`not_ready` (QC failed, a NEEDS-YOU line, an unfinished judgement).

Nothing here decides anything either (Q14): every video at or over N still
goes to the user, and its tier is only shown.

    runlog scores [--batch DIR] [--json]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

_funnel = runlog.sibling("funnel")

__all__ = ["READY", "STOPPED", "REFUSED", "NOT_READY", "NO_LINE", "collect", "line_of",
           "lines", "main"]

READY, STOPPED, REFUSED, NOT_READY = "ready", "stopped", "refused", "not_ready"
# What a video with no score line anywhere shows - never an empty place.
NO_LINE = "очки не посчитаны: нет лога"
STAGE_6B = "6b"


def _load(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _rows(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _slug(v):
    return Path(v.get("output_path") or "").stem or v.get("script_id") or "?"


def _score_of(rec):
    sc = rec.get("score")
    if isinstance(sc, dict):
        return sc.get("score"), sc.get("tier"), sc.get("threshold")
    s6 = rec.get("score_after_6b")
    if isinstance(s6, dict):
        return s6.get("score"), s6.get("tier"), s6.get("threshold")
    return None, rec.get("tier"), None


def collect(batch_dir):
    """`[{script_id, slug, state, stage, code, score, tier, threshold,
    score_line, source}]` - one row per video (or script) the batch scored or
    delivered, delivered ones first in the Editor's order."""
    bd = Path(batch_dir)
    ve = _load(bd / "05-video-editor.json")
    cr = _load(bd / "03-content-researcher.json")
    fj = _load(bd / _funnel.FRAME_JUDGE_FILE)
    judged = {}
    for r in _rows(fj, "videos"):
        for k in (r.get("script_id"), r.get("slug")):
            if k:
                judged[k] = r
    out, seen = [], set()
    for v in _rows(ve, "videos"):
        sid = v.get("script_id")
        if not sid:
            continue
        seen.add(sid)
        slug = _slug(v)
        j = judged.get(sid) or judged.get(slug)
        qc_ok = _funnel.judge_candidate(v)   # CF-0416: or admitted to the judge
        row = {"script_id": sid, "slug": slug, "stage": None, "code": None,
               "output_path": v.get("output_path")}
        if j is not None and j.get("score_line"):
            rec, row["source"] = j, _funnel.FRAME_JUDGE_FILE
        else:
            rec, row["source"] = v, "05-video-editor.json"
        row["score"], row["tier"], row["threshold"] = _score_of(rec)
        row["score_line"] = rec.get("score_line") or NO_LINE
        if not qc_ok:
            row["state"] = NOT_READY
        elif j is None or j.get("gate") == _funnel.GATE_PASS:
            row["state"] = READY
        else:
            code = _funnel.code_of(j)
            row["code"] = code
            row["state"] = STOPPED if code == _funnel.SCORE_BELOW_THRESHOLD else NOT_READY
            row["stage"] = "judge" if row["state"] == STOPPED else None
        out.append(row)
    for r in _rows(ve, "refusals"):
        sid = r.get("script_id")
        code = _funnel.code_of(r)
        if not sid or sid in seen or (code != _funnel.SCORE_BELOW_THRESHOLD
                                      and not r.get("score_line")):
            continue
        seen.add(sid)
        score, tier, thr = _score_of(r)
        stage = ((r.get("numbers") or {}).get("stage")
                 or (r.get("score") or {}).get("stopped_at"))
        out.append({"script_id": sid, "slug": sid, "output_path": None,
                    "state": STOPPED if code == _funnel.SCORE_BELOW_THRESHOLD else REFUSED,
                    "stage": stage, "code": code, "score": score, "tier": tier,
                    "threshold": thr, "score_line": r.get("score_line") or NO_LINE,
                    "source": "05-video-editor.json"})
    for r in _rows(cr, "skipped"):
        sid = r.get("script_id") or r.get("topic_id")
        code = _funnel.code_of(r)
        if not sid or sid in seen or (code != _funnel.SCORE_BELOW_THRESHOLD
                                      and not r.get("score_line")):
            continue
        seen.add(sid)
        score, tier, thr = _score_of(r.get("plan_check") or {})
        out.append({"script_id": sid, "slug": sid, "output_path": None,
                    "state": STOPPED if code == _funnel.SCORE_BELOW_THRESHOLD else REFUSED,
                    "stage": STAGE_6B, "code": code, "score": score,
                    "tier": r.get("tier") or tier, "threshold": thr,
                    "score_line": r.get("score_line") or NO_LINE,
                    "source": "03-content-researcher.json"})
    return out


def line_of(batch_dir, slug):
    """The score line of one video by its name (the stem of its mp4), or None
    when the batch has no record of that video."""
    for r in collect(batch_dir):
        if slug in (r["slug"], r["script_id"]):
            return r["score_line"]
    return None


def lines(rows):
    """The block the run summary prints under its headlines: one line per
    video, `ready` first. Empty when the batch scored nothing and delivered
    nothing - a batch before CF-0434 prints no block at all."""
    if not rows or all(r["score_line"] == NO_LINE for r in rows):
        return []
    ready = [r for r in rows if r["state"] == READY]
    stopped = [r for r in rows if r["state"] == STOPPED]
    L = [f"**score (CF-0434)**: {len(ready)} ready, {len(stopped)} stopped under N"
         + (f", {len(rows) - len(ready) - len(stopped)} other" if len(rows) > len(ready)
            + len(stopped) else "") + " - the tier is shown, nothing is decided on it (Q14):"]
    order = {READY: 0, STOPPED: 1, NOT_READY: 2, REFUSED: 3}
    for r in sorted(rows, key=lambda r: order.get(r["state"], 9)):
        tag = {READY: "", STOPPED: f" (stopped at {r['stage'] or '?'})",
               NOT_READY: f" ({r['code'] or 'not ready'})",
               REFUSED: f" ({r['code']})"}.get(r["state"], "")
        L.append(f"- `{r['slug']}`{tag}: {r['score_line']}")
    return L


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog scores",
                                 description="the score line of every video of a batch (CF-0434)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bd = runlog.find_batch_dir(ns.batch)
    if bd is None:
        sys.stderr.write("runlog scores: error: no batch directory (use --batch DIR)\n")
        return 2
    rows = collect(bd)
    if ns.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines(rows)) or "no video of this batch carries a score")
    return 0


if __name__ == "__main__":
    sys.exit(main())
