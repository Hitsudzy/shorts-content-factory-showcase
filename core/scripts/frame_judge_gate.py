#!/usr/bin/env python3
"""CF-0298: the machine half of the frame judge - the gate over DoD item 3.

The judge (`.claude/skills/frame-judge/SKILL.md`) is an LLM operator: it reads
the contact sheets the Editor's `frame_judge_pack.py` builds and writes one
verdict per judged entry into `<batch>/work/<slug>/frame-judge/verdicts.json`.
This script reads those verdicts against the packs they were written from,
executes the rule, and writes `<batch>/06-frame-judge.json`.

**The rule is here and not in the judge's head**, deliberately. The judge's job
is to say what it sees - `backs` / `neutral` / `contradicts` / `foreign`, plus
any foreign text burned into the picture (DoD item 2) - one entry at a time,
without knowing what it costs. Deciding readiness from those verdicts is
arithmetic, and arithmetic a model performs while it can see the consequence is
arithmetic that drifts. The rule (CF-0434, grill 2026-09-29, task item 4 - it
replaced the user's rule of 2026-09-20, "any `contradicts` / `foreign` / foreign
text refuses"):

    every `contradicts`, `neutral`, `foreign`
        -> a penalty of the score model: `score.judge_contradicts`,
           `score.judge_neutral`, `score.judge_foreign` per entry, priced and
           capped in shared/gate-prices.json (never here)
    foreign on-screen text on an entry (`foreign_text`)
        -> priced as `foreign` on that entry, until the grill on burned-in text
           (ROADMAP 1.4.7); an entry that is both is charged once
    those penalties
        -> the stage `judge` of the video's score log,
           `work/<slug>/plan.score.json` (the file the Editor's
           `scripts/score_log.py` writes `plan`, `render`, `qc` into; for a
           video with no file, the stages its `05` record carries)
    the score after the judge under N
        -> the video is not ready: `score_below_threshold`
    at or over N
        -> ready, whatever the words were; its tier is shown, never decided on
    an entry of the pack with no verdict
        -> the judgement is unfinished, and an unfinished judgement cannot
           call a video ready either (`frame_judge_failed`, only this now)
    a `contradicts` with no `mismatch` out of MISMATCHES (CF-0450)
        -> unfinished too: a contradiction is a claim the frame breaks - an
           identifiably other person or moment, a pointer at the picture that
           the picture fails, a refuted fact - and a judge that cannot name
           which one has seen a frame that does not carry the line, which is
           `neutral`. The user accepted and published videos this stage had
           pushed under N for asking every word of a scene list on screen.
    a `footage_defect` (CF-0450: `screen_recording`, `smeared`; CF-0646:
    `thin_strip`, `cut_subject`)
        -> recorded per video, never charged in points. An unknown kind is
           unfinished. `thin_strip`, `cut_subject` and `smeared` are on the
           hard list (`score.hard.footage_defect`, the user 2026-10-09: the
           video is not shown to the user, it is rebuilt once): the video is
           refused whatever its score (`judge_footage_defect`), and the
           reason names the entry, its seconds, the kind and the judge's line
           so the operator knows what to rebuild. `screen_recording` stays
           recorded only (its hard rule is at the shot level, CF-0451).
    a `foreign` in the hook, or `foreign` over 15 % of the judged time
    (CF-0539, `frame_judge.foreign_core`, funnel.foreign_core())
        -> a video at or over N refused anyway (`judge_foreign_core`) when the
           channel's `frame_judge.foreign_core.mode` is `fail`; under `warn`
           (the default, until the user signs the refusal) recorded on the
           video with a warning and passed. A price alone never refuses the
           wrong show under the story's opening words.
    a `contradicts` with `mismatch: person` - the line names someone, the frame
    shows another person (CF-0877, `wrong_person_on_name`: wicker 0841Z,
    the-gilded-age 0836Z)
        -> its own kind, `score.judge_wrong_person` (x2 in the hook), charged
           on that entry in place of `score.judge_contradicts` - while the row
           is in the price table's `rules` (signed by the user 2026-10-27).
           A table without it (a row back in `proposals`) charges the entry
           `score.judge_contradicts` and only records the entries
           (`wrong_person` on the video, a `[wrong person]` line in the report).
    the picture standing as a narrow strip on its blurred ground, summed
    over the video from the plan's geometry (CF-0878, `narrow_strip_on_blur`:
    the-gilded-age 0836Z, 10.2 s of 16:9 pieces none of which any check saw)
        -> recorded on every video (`strip_on_blur`, a `[strip]` line in the
           report) by shared/strip_on_blur.py; charged at this stage as
           `score.narrow_strip_on_blur` (seconds over the allowance that
           `score.thin_picture` does not already charge) while the row is in
           the price table's `rules` (signed by the user 2026-10-27) and no
           earlier stage charged it. A table without it (a row back in
           `proposals`) only records the strip and charges nothing.
    a shot cut from an upload whose title is about another work - the
    film or series topic's name only as a credit ("... from the producer of
    Jon Marrow"), or an official upload of another film ("Karōshi (2027)
    Official Trailer" on Example Pictures) (CF-0927, CF-0924's rule in
    shared/other_work_source.py, read through shared/judge_sources.py from
    the batch's `01`: 08.11 jon-marrow, nine `neutral`s on Karōshi's trailer
    "from Example Pictures's own upload", refused by the user `wrong_work_footage`)
        -> the entry is `contradicts` with `mismatch: work` whatever the model
           wrote (`backs`, `neutral`; a `foreign` or another named mismatch
           is kept, it already says the frame is not this), charged
           `score.judge_contradicts`; the row keeps the judge's own word
           (`other_work.judge_verdict`) and the video records the entries
           (`other_work`, an `[other work]` line in the report). Official
           says whose cut it is, never which work.

How a rejected video is marked, and what is *not* done to it: nothing is moved
and nothing is deleted. The batch already has one form for a video refused after
the render - QC's (`videos[].qc.passed` is false, the mp4 stays in `videos/`,
and shared/runlog/funnel.py stops counting it at the `ready` step) - and this is
the same form one step further along: the record is `06-frame-judge.json`, the
funnel's `frame_judge` step drops it under its `reason_code`, and the file,
the pack, the sheets and the judge's one-line reasons all stay on disk so the
decision can be read back. A `videos/rejected/` directory was considered and
rejected: it would make the batch's own artifacts disagree with its directory
(`05-video-editor.json` records an `output_path` that no longer exists), and it
would be a second place to look for the answer to "was this video ready".

This script also never edits `05-video-editor.json`. That artifact is the
Editor's record of what the Editor did, and a later stage rewriting it would
make the run's own history depend on who read it last. The score after the
judge is in `06` (`videos[].score`, `videos[].score_line`) and in the video's
own `plan.score.json`; the run summary and the message to the user read it
from there.

**Nothing to judge** (CF-0707, batch example-science/2026-10-12T2001Z: the
only script was refused at QC, the judge closed its stage with a note and no
`06`, and the triage filed a broken contract). A batch whose `05` names no
video the judge owes a verdict on still gets its `06`: `videos: []` and a
sentence in `nothing_to_judge` saying why. The file is written by this script,
not by a model's goodwill: the run plan's machine stage `frame-judge-empty`
runs it with `--nothing-to-judge` exactly when `run_checks` condition
`nothing_to_judge` holds, and the LLM stage `frame-judge` runs only when
`judge_candidates` holds. `--nothing-to-judge` refuses (exit 2) a batch that
does have a video to judge, so that stage can never pass a half record off as
a judgement.

Usage:

    python3 scripts/frame_judge_gate.py --batch <batch dir> [--json] [--quiet]
    python3 scripts/frame_judge_gate.py --batch <batch dir> --nothing-to-judge
    python3 scripts/frame_judge_gate.py --batch <batch dir> --new-only [--record-incomplete]
    python3 scripts/frame_judge_gate.py --batch <batch dir> --repair [--record-incomplete]

**Repair** (CF-0881): `--repair [--record-incomplete]` - the one repair pass
of a video refused for a defect in one or two blocks (shared/judge_repair.py):
the Editor re-picked those blocks and re-rendered (`work/repair-results.json`),
the judge wrote `verdicts.repair.json` for the changed entries only, the first
pass's verdicts are carried for the rest (same span), and the video is judged
again by this gate's own `judge_video`. Ready -> its row in `06` is replaced
(the refused row kept in the record); not ready -> the refusal stands. Either
way `06 -> repairs[]` says `repaired` / `repair_failed`.

**New only** (CF-0800, part of CF-0798: the reserve round after the judge).
`--new-only` judges just the videos of `05` that `06` has no row for
(`scripts/frame_judge_merge.py pending`), writes their rows to
`06-frame-judge.added.json` and merges that into `06`: the rows already there
stay byte for byte (and their `plan.score.json` is not rewritten), `counts` is
recounted, `merges[]` records what was added. An unfinished new judgement keeps
the staging file and leaves `06` alone (exit 1) until the judge fixes its
`verdicts.json`, or `--record-incomplete` records it `incomplete`. The default
full pass is unchanged.

Exit 0: every video QC passed carries a complete judgement and the gate ran.
Exit 1: something is missing or malformed - a video with no `verdicts.json`, a
        judged entry with no verdict, a verdict for an entry that is not in the
        pack, an unknown verdict word, a pack that will not parse. The artifact
        is still written (the state of a half-judged batch is a fact worth
        recording); the sentences say what to fix.
Exit 2: bad usage - no batch directory, or no `05-video-editor.json` in it;
        with `--nothing-to-judge`, a batch that has a video to judge.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "score"))
import channel_ids                                                 # noqa: E402
import funnel                                                      # noqa: E402
import runlog                                                      # noqa: E402
import score as score_model                                        # noqa: E402
import strip_on_blur                                               # noqa: E402
import judge_sources                                               # noqa: E402
import other_work_source                                           # noqa: E402

PACK_DIRNAME = "frame-judge"
PLAN_FILE = "plan.json"
MANIFEST = "manifest.json"
VERDICTS = "verdicts.json"
VIDEO_EDITOR_FILE = "05-video-editor.json"

# CF-0450: what a `contradicts` has to name (SKILL step 3), and what the judge
# may say about the footage itself (SKILL step 4a)
MISMATCHES = ("person", "moment", "pointer", "fact", other_work_source.MISMATCH)
FOOTAGE_DEFECTS = ("screen_recording", "smeared", "thin_strip", "cut_subject")
# CF-0646 (the user 2026-10-09, «да ок на оба»): the kinds that keep a video from
# the user whatever its score - a hard finding of FOOTAGE_DEFECT_RULE in the
# stage `judge` of its score log, refused under funnel.JUDGE_FOOTAGE_DEFECT
REFUSING_DEFECTS = ("thin_strip", "cut_subject", "smeared")
FOOTAGE_DEFECT_RULE = "score.hard.footage_defect"
# CF-0877: the mismatch that is its own kind with its own price
WRONG_PERSON_MISMATCH = "person"
WRONG_PERSON_RULE = funnel.JUDGE_WRONG_PERSON_RULE
# CF-0878: the strip time of the whole video, read off its plan
STRIP_RULE = strip_on_blur.RULE
# CF-0927: the verdicts the gate turns into `contradicts`, `mismatch: work`
# when the shot's upload is about another work; `foreign` and a `contradicts`
# that already names its mismatch say "not this" on their own and are kept
OTHER_WORK_OVERRIDES = ("backs", "neutral")


def _now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path):
    """(parsed, error sentence). A file that is not there is (None, None) - the
    caller decides whether absence is silence or a defect."""
    if not path.is_file():
        return None, None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{path.name} will not parse ({e.__class__.__name__}: {e})"
    if not isinstance(d, dict):
        return None, f"{path.name} is not a JSON object"
    return d, None


def _rows(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _slug(v):
    return Path(v.get("output_path") or "").stem or v.get("script_id") or "?"


def _text(x):
    return x.strip() if isinstance(x, str) and x.strip() else None


def deliverable(ve):
    """The videos of `05-video-editor.json` the judge owes a verdict on: the
    ones the Editor rendered and QC passed, with no NEEDS-YOU line, and - since
    CF-0416 - the ones the Editor admitted to the judge in writing
    (`judge_admitted_despite`: QC refused them only on rules the channel counts
    as cosmetic), whatever `qc.passed` and `needs_you` say. The same set the
    funnel's `ready` step counts (`funnel.judge_candidate`, one predicate for
    both) - a video QC refused for real left the batch one step earlier and
    judging it would be judging something nobody will publish.
    """
    return [v for v in _rows(ve, "videos")
            if v.get("script_id") and funnel.judge_candidate(v)]


def nothing_to_judge(ve):
    """CF-0707: the sentence saying why a readable `05-video-editor.json` owes
    the judge nothing, or None when it names at least one video to judge."""
    if deliverable(ve):
        return None
    rendered = _rows(ve, "videos")
    refused = _rows(ve, "refusals")
    bits = [f"{len(rendered)} video(s) in videos[]"]
    if rendered:
        bits[-1] += ", none QC passed without NEEDS-YOU or admitted to the judge"
    if refused:
        named = ", ".join(f"{r.get('script_id') or r.get('slug') or '?'}"
                          + (f" ({r.get('reason_code') or r.get('code')})"
                             if r.get("reason_code") or r.get("code") else "")
                          for r in refused[:5])
        bits.append(f"{len(refused)} refused before the judge: {named}"
                    + (" ..." if len(refused) > 5 else ""))
    return f"nothing to judge - {VIDEO_EDITOR_FILE}: " + "; ".join(bits)


def batch_judge_set(batch_dir):
    """CF-0707: (state, sentence) of a batch for the run plan's conditions -
    `missing` (no readable 05: the judge's own SKILL says so in its note),
    `none` (05 names no video to judge: the gate writes the empty 06) or
    `some` (the LLM judge has work)."""
    ve, err = _load(Path(batch_dir) / VIDEO_EDITOR_FILE)
    if ve is None:
        return "missing", err or f"no {VIDEO_EDITOR_FILE}"
    why = nothing_to_judge(ve)
    if why:
        return "none", why
    n = len(deliverable(ve))
    return "some", f"{n} video(s) in {VIDEO_EDITOR_FILE} to judge"


# --------------------------------------------------------------------------
# the score (CF-0434)

def footage_defect(x):
    """(the judge's `footage_defect` as recorded, or None; a problem sentence or
    None). CF-0450, SKILL step 4a: `null`, or {kind, why} with kind out of
    FOOTAGE_DEFECTS and a line saying what shows it."""
    if x is None:
        return None, None
    if not isinstance(x, dict) or x.get("kind") not in FOOTAGE_DEFECTS:
        kind = x.get("kind") if isinstance(x, dict) else x
        return None, (f"footage_defect {kind!r} is outside {list(FOOTAGE_DEFECTS)} "
                      f"(or null when the footage is fine)")
    why = _text(x.get("why"))
    if not why:
        return None, f"a footage_defect {x['kind']!r} with no line saying what shows it"
    return {"kind": x["kind"], "why": why}, None


def refusing_defects(rows):
    """The verdict rows whose `footage_defect` is one of REFUSING_DEFECTS."""
    return [r for r in rows if (r.get("footage_defect") or {}).get("kind") in REFUSING_DEFECTS]


def defect_findings(rows):
    """CF-0646: one hard finding of FOOTAGE_DEFECT_RULE per entry the judge
    named a refusing footage defect on. Hard findings cost no points; they
    make the tier F and this gate refuses the video on them."""
    out = []
    for r in refusing_defects(rows):
        where = {"block": r["entry"]}
        if isinstance(r.get("start"), (int, float)):
            where["t"] = r["start"]
        d = r["footage_defect"]
        out.append(score_model.finding(FOOTAGE_DEFECT_RULE, where, source="metric",
                                       note=f"{d['kind']}: {d['why']}"[:160]))
    return out


def wrong_person_priced(ledger=None):
    """CF-0877: True when `score.judge_wrong_person` is a penalty row of the
    price table's `rules` - i.e. the user signed it. A row waiting in
    `proposals` (or a table that cannot be read) is not a price."""
    try:
        return score_model.mode_of(WRONG_PERSON_RULE, ledger) == score_model.PENALTY
    except score_model.ScoreModelError:
        return False


def strip_priced(ledger=None):
    """CF-0878: True when `score.narrow_strip_on_blur` is a penalty row of the
    price table's `rules` (the user signed it); a row in `proposals` is not."""
    try:
        return score_model.mode_of(STRIP_RULE, ledger) == score_model.PENALTY
    except score_model.ScoreModelError:
        return False


def strip_record(plan_path, priced):
    """CF-0878: the video's strip reading (shared/strip_on_blur.py) from the
    plan it was rendered from, or None when the plan is not there."""
    plan, _err = _load(Path(plan_path))
    if plan is None:
        return None
    rec = strip_on_blur.reading(plan)
    return {"rule": STRIP_RULE, "priced": bool(priced), "charged": False,
            "line": strip_on_blur.line(rec),
            **{k: rec[k] for k in ("share_below", "seconds", "video_seconds",
                                   "share_of_video", "longest", "thin_charged_seconds",
                                   "uncharged_seconds", "allow_seconds", "over_seconds")},
            "runs": [{"start": r["start"], "end": r["end"], "seconds": r["seconds"]}
                     for r in rec["runs"]]}


def strip_findings(rec, stages):
    """The judge-stage finding of the strip price for `rec`: none when
    there is nothing over the allowance, the price is not signed, or an
    earlier stage (the Editor's plan) already charged the rule."""
    if not rec or not rec.get("priced") or not rec.get("over_seconds"):
        return []
    if any(isinstance(f, dict) and f.get("rule") == STRIP_RULE
           for s in stages for f in s.get("findings") or []):
        return []
    f = strip_on_blur.finding(rec, score_model)
    return [f] if f else []


def is_wrong_person(r):
    """A verdict row that is `contradicts` with `mismatch: person` (CF-0877)."""
    return r.get("verdict") == "contradicts" and r.get("mismatch") == WRONG_PERSON_MISMATCH


def wrong_person_record(rows, priced):
    """CF-0877: the entries where the line names a person and the frame shows
    another one, recorded on the video whatever the price table says."""
    hit = [r for r in rows if is_wrong_person(r)]
    return {"rule": WRONG_PERSON_RULE, "priced": bool(priced),
            "entries": [r["entry"] for r in hit],
            "hook_entries": [r["entry"] for r in hit if score_model.in_hook(r.get("start"))]}


def other_work_entries(batch_dir, slug, entries):
    """CF-0927: `{entry id: hit}` of the judged pack entries whose shot's
    upload is about another work than the video's film or series topic
    (shared/judge_sources.py over the batch's `01`). A batch with no `01`, a
    topic of another kind, an upload nobody recorded: nothing."""
    try:
        return judge_sources.other_work_map(batch_dir, slug, entries)
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def apply_other_work(row, hit):
    """CF-0927: one verdict row under a shot of another work's upload ->
    `contradicts`, `mismatch: work` when the judge wrote `backs`/`neutral`;
    the judge's own word and line stay in `other_work`. Returns True when the
    verdict was turned."""
    turned = row["verdict"] in OTHER_WORK_OVERRIDES
    row["other_work"] = {"rule": other_work_source.RULE, "task": other_work_source.TASK,
                         "branch": hit.get("branch"),
                         "title_subject": hit.get(other_work_source.SUBJECT_KEY),
                         "work": hit.get("work"), "video_id": hit.get("video_id"),
                         "title": hit.get("title"), "channel_title": hit.get("channel_title"),
                         "judge_verdict": row["verdict"], "judge_mismatch": row["mismatch"],
                         "turned": turned}
    if turned:
        row["verdict"] = "contradicts"
        row["mismatch"] = other_work_source.MISMATCH
        row["why"] = (f"{other_work_source.TASK}: the shot is cut from {hit.get('video_id')} - "
                      f"{hit.get('why')} ({other_work_source.ACCEPTANCE_CODE}); the judge "
                      f"wrote {row['other_work']['judge_verdict']!r}: {row['why'] or ''}")
    return turned


def other_work_record(rows):
    """CF-0927: the entries cut from another work's upload, recorded on the
    video - and the ones whose verdict the gate turned."""
    hit = [r for r in rows if r.get("other_work")]
    if not hit:
        return None
    return {"rule": other_work_source.RULE, "task": other_work_source.TASK,
            "mismatch": other_work_source.MISMATCH,
            "acceptance_code": other_work_source.ACCEPTANCE_CODE,
            "entries": [r["entry"] for r in hit],
            "turned": [r["entry"] for r in hit if r["other_work"]["turned"]],
            "title_subjects": sorted({r["other_work"]["title_subject"] for r in hit
                                      if r["other_work"]["title_subject"]}),
            "work": hit[0]["other_work"]["work"]}


def judge_findings(rows, wrong_person=False):
    """The judge's verdict rows as findings of the score model, in entry order.
    `backs` costs nothing; foreign on-screen text is `foreign` on that entry
    unless the verdict already is one (charged once). Each finding carries the
    entry it came from, so the charged price can be read back per entry.
    `wrong_person` (CF-0877, `wrong_person_priced`): a `contradicts` with
    `mismatch: person` is charged `score.judge_wrong_person` in its place,
    marked as in the hook when the entry starts there."""
    out = []
    for r in rows:
        rules = []
        hook = False
        if wrong_person and is_wrong_person(r):
            rules.append(WRONG_PERSON_RULE)
            hook = score_model.in_hook(r.get("start"))
        elif r["verdict"] in funnel.JUDGE_RULES:
            rules.append(funnel.JUDGE_RULES[r["verdict"]])
        if r["foreign_text"] and r["verdict"] != "foreign":
            rules.append(funnel.JUDGE_RULES["foreign"])
        where = {"block": r["entry"]}
        if isinstance(r.get("start"), (int, float)):
            where["t"] = r["start"]
        for rule in rules:
            note = (f"foreign on-screen text: {r['foreign_text']}"
                    if rule == funnel.JUDGE_RULES["foreign"] and r["verdict"] != "foreign"
                    else r["why"])
            out.append(score_model.finding(rule, where, source="metric",
                                           hook=hook and rule == WRONG_PERSON_RULE,
                                           note=(note or "")[:160] or None))
    return out


def plan_path_of(video, bd):
    """The plan the video was rendered from: `<batch>/work/<slug>/plan.json`,
    the directory its pack sits in."""
    return bd / "work" / _slug(video) / PLAN_FILE


def earlier_stages(video, plan_path):
    """(the video's score stages before the judge, where they came from). The
    log file beside the plan first; a video with none, the stages (or the plan
    findings) its `05` record carries; neither - nothing, and the judge's own
    penalties are the whole score (`judge_only`)."""
    before = score_model.STAGES.index(score_model.STAGE_JUDGE)

    def keep(stages):
        return [{"stage": s.get("stage"), "at": s.get("at"),
                 "findings": list(s.get("findings") or [])}
                for s in stages if isinstance(s, dict) and s.get("stage") in score_model.STAGES
                and score_model.STAGES.index(s["stage"]) < before]

    doc = score_model.read_log(plan_path)
    if doc is not None:
        return keep(doc["stages"]), "log"
    sc = video.get("score") if isinstance(video.get("score"), dict) else {}
    if isinstance(sc.get("stages"), list) and sc["stages"]:
        return keep(sc["stages"]), "05"
    if isinstance(sc.get("findings"), list):
        return [{"stage": score_model.STAGE_PLAN, "at": None,
                 "findings": list(sc["findings"])}], "05"
    return [], "judge_only"


def write_log(plan_path, stages, block, script_id):
    """The video's `plan.score.json` with the judge stage last, in the shape
    the Editor's `score_log.record()` writes (schema `cf0434.score_log/1`).
    Returns an error sentence, or None."""
    old = score_model.read_log(plan_path) or {}
    doc = {"schema": score_model.LOG_SCHEMA,
           "script_id": old.get("script_id") or script_id,
           "plan": Path(plan_path).name,
           "stages": stages,
           "score": {k: v for k, v in block.items() if k != "stages"},
           "stage_scores": block["stages"],
           score_model.LINE_FIELD: score_model.summary_line(block)}
    try:
        if not Path(plan_path).parent.is_dir():
            return f"no work directory {Path(plan_path).parent}"
        score_model.log_path(plan_path).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        return f"{e.__class__.__name__}: {e}"
    return None


def _span(r):
    return (f" [{r['start']:g}-{r['end']:g}s]"
            if isinstance(r.get("start"), (int, float))
            and isinstance(r.get("end"), (int, float)) else "")


def foreign_core_mode(channel, override=None, root=None):
    """(mode, where it came from) of `frame_judge.foreign_core` (CF-0539): the
    caller's override (`--foreign-core-mode`), else the channel config's
    `frame_judge.foreign_core` (`"fail"` or `{"mode": "fail"}`), else `warn` -
    the default of an unsigned refusal (CF-0320). A value outside the modes
    is read as the default, never as a refusal."""
    if override:
        if override not in funnel.FOREIGN_CORE_MODES:
            raise SystemExit(f"frame-judge gate: --foreign-core-mode {override!r} is outside "
                             f"{list(funnel.FOREIGN_CORE_MODES)}")
        return override, "override"
    try:
        path = channel_ids.channel_config_path(channel, root=root or ROOT) if channel else None
        cfg = json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError, TypeError):
        cfg = None
    d = cfg
    for part in funnel.FOREIGN_CORE_RULE.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    mode = d.get("mode") if isinstance(d, dict) else d
    if mode in funnel.FOREIGN_CORE_MODES:
        return mode, "channel"
    return funnel.FOREIGN_CORE_DEFAULT_MODE, "default"


def judge_video(video, pack_dir, bd=None, ledger=None, foreign_mode=None):
    """One `videos[]` record of `06-frame-judge.json` for one finished video, or
    (None, sentence) when there is no judgement to record at all. `ledger` is
    the price table (a path or a read dict); None is the live
    shared/gate-prices.json. `foreign_mode` is the mode of
    `frame_judge.foreign_core` (CF-0539); None is the default, `warn`."""
    foreign_mode = foreign_mode or funnel.FOREIGN_CORE_DEFAULT_MODE
    slug, sid = _slug(video), video["script_id"]
    manifest, err = _load(pack_dir / MANIFEST)
    if manifest is None:
        why = err or (f"no pack: {pack_dir / MANIFEST} is not there - build it with "
                      f"agents/video-editor/scripts/frame_judge_pack.py before judging")
        return None, why
    if _text(manifest.get("refusal")):
        return None, f"the pack builder refused this video: {manifest['refusal']}"
    if manifest.get("schema") != funnel.FRAME_JUDGE_PACK_SCHEMA:
        return None, (f"the pack says schema {manifest.get('schema')!r}, this gate reads "
                      f"{funnel.FRAME_JUDGE_PACK_SCHEMA!r}")

    entries = [e for e in _rows(manifest, "entries") if e.get("id")]
    judged = {e["id"]: e for e in entries if e.get("judged") is True}
    not_judged = [{"entry": e["id"], "reason": _text(e.get("not_judged_reason"))
                   or "the pack does not judge this entry"}
                  for e in entries if e.get("judged") is not True]

    verdicts_doc, err = _load(pack_dir / VERDICTS)
    if verdicts_doc is None and err is None:
        return None, (f"no judgement: {pack_dir / VERDICTS} is not there. The pack is built "
                      f"and nobody judged it - not a refusal, but not a check that ran")
    problems = list(filter(None, [err]))
    if verdicts_doc is not None and verdicts_doc.get("schema") != funnel.FRAME_JUDGE_VERDICTS_SCHEMA:
        problems.append(f"{VERDICTS} says schema {(verdicts_doc or {}).get('schema')!r}, this "
                        f"gate reads {funnel.FRAME_JUDGE_VERDICTS_SCHEMA!r}")

    rows, seen = [], {}
    for r in _rows(verdicts_doc, "verdicts"):
        entry_id = _text(r.get("entry"))
        word = r.get("verdict")
        if not entry_id:
            problems.append("a verdict row names no entry")
            continue
        if entry_id not in judged:
            problems.append(f"verdict for {entry_id!r}, which the pack does not judge"
                            if entry_id in {e["id"] for e in entries} else
                            f"verdict for {entry_id!r}, which is not in the pack")
            continue
        if entry_id in seen:
            problems.append(f"{entry_id}: judged twice ({seen[entry_id]!r} and {word!r})")
            continue
        seen[entry_id] = word
        if word not in funnel.FRAME_VERDICTS:
            problems.append(f"{entry_id}: verdict {word!r} is outside "
                            f"{list(funnel.FRAME_VERDICTS)}")
            continue
        why = _text(r.get("why"))
        if not why:
            problems.append(f"{entry_id}: a {word!r} with no line of reasoning - a verdict "
                            f"nobody can audit afterwards is a frame that merely passed")
        foreign_text = _text(r.get("foreign_text"))
        mismatch = _text(r.get("mismatch")) if word == "contradicts" else None
        if word == "contradicts" and mismatch not in MISMATCHES:
            problems.append(f"{entry_id}: a 'contradicts' with mismatch {mismatch!r} - it has to "
                            f"name one of {list(MISMATCHES)} (CF-0450); a frame that only "
                            f"lacks what the line describes is 'neutral'")
        defect, bad = footage_defect(r.get("footage_defect"))
        if bad:
            problems.append(f"{entry_id}: {bad}")
        entry = judged[entry_id]
        rows.append({"entry": entry_id, "tile": r.get("tile"), "verdict": word, "why": why,
                     "mismatch": mismatch, "footage_defect": defect,
                     "foreign_text": foreign_text, "rules": [], "charged": 0,
                     "start": entry.get("start"), "end": entry.get("end"),
                     "narration": entry.get("narration")})
    for entry_id in judged:
        if entry_id not in seen:
            problems.append(f"{entry_id}: judged by the pack and carries no verdict")
    # CF-0927: a shot of another work's upload is not the topic's own footage,
    # whatever the model read off "official"
    other = other_work_entries(Path(bd) if bd else pack_dir.parent.parent.parent, slug,
                               list(judged.values()))
    for r in rows:
        if r["entry"] in other:
            apply_other_work(r, other[r["entry"]])

    counts = dict.fromkeys(funnel.FRAME_VERDICTS, 0)
    counts["foreign_text"] = 0
    counts.update(dict.fromkeys(FOOTAGE_DEFECTS, 0))
    for r in rows:
        counts[r["verdict"]] += 1
        if r["foreign_text"]:
            counts["foreign_text"] += 1
        if r["footage_defect"]:
            counts[r["footage_defect"]["kind"]] += 1

    # the score: the judge's penalties as the last stage of the video's log
    block, basis, log_error = None, None, None
    plan_path = plan_path_of(video, Path(bd) if bd else pack_dir.parent.parent.parent)
    wp_priced = wrong_person_priced(ledger)
    strip = strip_record(plan_path, strip_priced(ledger))
    if not problems:
        found = judge_findings(rows, wrong_person=wp_priced)
        stages, basis = earlier_stages(video, plan_path)
        # CF-0878: the strip price (signed only) goes first, so the log's tail
        # below is still exactly the penalties of `found`; the hard findings
        # go after the penalties and add no row to the log
        strip_f = strip_findings(strip, stages)
        if strip is not None:
            strip["charged"] = bool(strip_f)
        stages.append({"stage": score_model.STAGE_JUDGE, "at": _now_z(),
                       "findings": strip_f + found + defect_findings(rows)})
        try:
            block = score_model.stages_block(stages, ledger)
        except score_model.ScoreModelError as e:
            problems.append(f"the score after the judge could not be computed ({e}) - "
                            f"without it this gate cannot call the video ready")
        else:
            charged = block["log"][len(block["log"]) - len(found):] if found else []
            for f, e in zip(found, charged):
                row = next(r for r in rows if r["entry"] == f["where"]["block"])
                row["rules"].append(f["rule"])
                row["charged"] = score_model._round(row["charged"] + e["price"])
            log_error = write_log(plan_path, stages, block, sid)
    line = score_model.summary_line(block, ledger) if block else None
    # CF-0539: the picture of something else under the core of the story
    core = None
    if not problems:
        core = dict(funnel.foreign_core(rows), mode=foreign_mode)
        core["warning"] = (f"{slug}: {core['why']} - mode `{foreign_mode}`: recorded, not "
                           f"refused, until the user signs the refusal (CF-0320)"
                           if core["refuses"] and foreign_mode != funnel.FOREIGN_CORE_FAIL
                           else None)

    if problems:
        gate = funnel.GATE_INCOMPLETE
        code = funnel.FRAME_JUDGE_FAILED
        reason = (f"the judgement of {slug} is unfinished: " + "; ".join(problems[:4])
                  + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else "")
                  + ". An unfinished judgement cannot call a video ready")
    elif refusing_defects(rows):
        gate = funnel.GATE_REJECT
        code = funnel.JUDGE_FOOTAGE_DEFECT
        reason = (f"{slug}: the frame judge saw footage the user does not want shown - "
                  f"`{FOOTAGE_DEFECT_RULE}` (hard list, signed 2026-10-09): " + "; ".join(
                      f"{r['entry']}{_span(r)} {r['footage_defect']['kind']} - "
                      f"{r['footage_defect']['why']}" for r in refusing_defects(rows))
                  + f". Refused whatever the score ({line}); rebuild the topic once (CF-0646)")
    elif score_model.stops(block):
        gate = funnel.GATE_REJECT
        code = funnel.SCORE_BELOW_THRESHOLD
        charged_rows = [r for r in rows if r["charged"]]
        reason = (f"{slug}: {block['score']} < {block['threshold']} after the frame judge "
                  f"(CF-0434) - {line}. The judge charged: " + ("; ".join(
                      f"{r['entry']} {r['verdict']}{_span(r)} {r['charged']}"
                      + (f" - {r['why']}" if r["why"] else "")
                      + (f"; foreign on-screen text: {r['foreign_text']}"
                         if r["foreign_text"] else "")
                      for r in charged_rows) or "nothing"))
    elif core["refuses"] and foreign_mode == funnel.FOREIGN_CORE_FAIL:
        gate = funnel.GATE_REJECT
        code = funnel.JUDGE_FOREIGN_CORE
        reason = (f"{slug}: {core['why']}; the score after the judge ({line}) does not "
                  f"save it - `{funnel.FOREIGN_CORE_RULE}`, mode `fail`. Foreign: " + "; ".join(
                      f"{r['entry']}{_span(r)} - {r['why']}" for r in rows
                      if r["verdict"] == "foreign"))
    else:
        gate = funnel.GATE_PASS
        code = None
        reason = None

    pack_counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    return {
        "script_id": sid,
        "slug": slug,
        "output_path": video.get("output_path"),
        "gate": gate,
        "reason_code": code,
        "reason": reason,
        # CF-0434: the video's score after the judge - the whole block with its
        # stages, the one line, and where the stages before the judge came from
        "score": block,
        "score_line": line,
        "score_basis": basis,
        "score_log": str(score_model.log_path(plan_path)) if block and not log_error else None,
        "score_log_error": log_error,
        "pack": {"dir": str(pack_dir), "schema": manifest.get("schema"),
                 "built_at": manifest.get("built_at"),
                 "entries": pack_counts.get("entries"), "judged": pack_counts.get("judged"),
                 "frames": pack_counts.get("frames"), "sheets": pack_counts.get("sheets"),
                 "unreadable_frames": len(_rows(manifest, "unreadable_frames"))},
        "counts": counts,
        # CF-0450: what the judge said about the footage itself - never charged
        # in points; REFUSING_DEFECTS (CF-0646) refuse the video, the rest
        # (screen_recording) are recorded only
        "footage_defects": [dict(r["footage_defect"], entry=r["entry"])
                            for r in rows if r["footage_defect"]],
        # CF-0539: `frame_judge.foreign_core` on this video, whatever its mode
        "foreign_core": core,
        # CF-0877: the line names a person, the frame shows another - priced as
        # its own kind once signed (`priced`), recorded either way
        "wrong_person": wrong_person_record(rows, wp_priced) if not problems else None,
        # CF-0878: how long the picture stands as a narrow strip on its blurred
        # ground over the whole video (the plan's geometry); charged only once
        # signed (`priced`) and when nothing earlier charged it (`charged`)
        "strip_on_blur": strip,
        # CF-0927: the entries cut from an upload about another work (None:
        # none) - turned `contradicts`, `mismatch: work` where the judge wrote
        # backs/neutral
        "other_work": other_work_record(rows),
        "verdicts": rows,
        "not_judged_entries": not_judged,
        "problems": problems,
    }, None


def gate(batch_dir, ledger=None, foreign_mode=None, only_if_nothing=False, only=None):
    """The whole artifact for one batch, plus the sentences for the operator.
    `only` (CF-0800): judge just these `script_id`s of the deliverable set -
    the second pass after the reserve, whose rows are merged into `06` by
    `frame_judge_merge.py` and never replace a row already there.
    `ledger`: the price table to score with (None: the live
    shared/gate-prices.json; the tests pin their own, CF-0462).
    `foreign_mode`: an override of the channel's `frame_judge.foreign_core`
    mode (CF-0539); None reads the channel config.
    `only_if_nothing` (CF-0707): refuse a batch that has a video to judge."""
    bd = Path(batch_dir)
    ve, err = _load(bd / VIDEO_EDITOR_FILE)
    if ve is None:
        raise SystemExit(f"frame-judge gate: {err or f'{bd / VIDEO_EDITOR_FILE} is not there'} - "
                         f"nothing names the finished videos of this batch")
    empty_why = nothing_to_judge(ve)
    if only_if_nothing and not empty_why:
        raise SystemExit(f"frame-judge gate: --nothing-to-judge, but {VIDEO_EDITOR_FILE} names "
                         f"{len(deliverable(ve))} video(s) to judge - that is the LLM stage "
                         f"`frame-judge`'s work, not an empty record")
    channel = channel_ids.resolve_channel(ve.get("channel"), root=ROOT)
    core_mode, core_from = foreign_core_mode(channel, foreign_mode)
    videos, skipped = [], []
    for v in deliverable(ve):
        if only is not None and v["script_id"] not in only:
            continue
        row, why = judge_video(v, bd / "work" / _slug(v) / PACK_DIRNAME, bd, ledger, core_mode)
        if row is None:
            skipped.append({"script_id": v["script_id"], "slug": _slug(v), "reason": why})
        else:
            videos.append(row)
    counts = {"videos": len(videos) + len(skipped),
              "judged": len(videos),
              "passed": sum(1 for v in videos if v["gate"] == funnel.GATE_PASS),
              "rejected": sum(1 for v in videos if v["gate"] == funnel.GATE_REJECT),
              "incomplete": sum(1 for v in videos if v["gate"] == funnel.GATE_INCOMPLETE),
              "not_judged": len(skipped)}
    for word in funnel.FRAME_VERDICTS + ("foreign_text",) + FOOTAGE_DEFECTS:
        counts[word] = sum(v["counts"].get(word, 0) for v in videos)
    # CF-0539: the videos `frame_judge.foreign_core` refuses (or, under `warn`, would)
    counts["foreign_core"] = sum(1 for v in videos if (v.get("foreign_core") or {}).get("refuses"))
    # CF-0877: the entries where the line names a person and the frame shows another
    counts["wrong_person"] = sum(len((v.get("wrong_person") or {}).get("entries") or [])
                                 for v in videos)
    # CF-0927: the entries cut from an upload about another work
    counts["other_work"] = sum(len((v.get("other_work") or {}).get("entries") or [])
                               for v in videos)
    doc = {
        "schema": funnel.FRAME_JUDGE_SCHEMA,
        "batch_id": ve.get("batch_id"),
        # Resolved at the door (CF-0197): `05-video-editor.json` is a dated
        # record and a batch written before a rename carries the former id
        # frozen in this field, so a reader of ours would look for a config
        # that no longer exists. The resolver is the one in shared/, called -
        # never a second copy of the mapping.
        "channel": channel,
        # CF-0416: a rebuild's own 05 names the batch it rebuilt; carried over
        # as read, so every record of the run says what this judgement is of.
        # `null` for an ordinary batch.
        "rebuild_of": ve.get("rebuild_of") if isinstance(ve.get("rebuild_of"), dict) else None,
        "stage": runlog.S_FRAME_JUDGE,
        "judged_at": _now_z(),
        "rule": {"charges": dict(funnel.JUDGE_RULES),
                 "foreign_text": funnel.JUDGE_RULES["foreign"],
                 "rejects_on": "the score after the judge under N",
                 "states": list(funnel.GATE_STATES),
                 "reason_code": funnel.SCORE_BELOW_THRESHOLD,
                 "incomplete_code": funnel.FRAME_JUDGE_FAILED,
                 "prices": str(ledger) if isinstance(ledger, (str, Path)) else "shared/gate-prices.json",
                 "contradicts_names": list(MISMATCHES),
                 "foreign_core": {"rule": funnel.FOREIGN_CORE_RULE, "mode": core_mode,
                                  "mode_from": core_from,
                                  "hook_seconds": funnel.FOREIGN_HOOK_SECONDS,
                                  "share_max": funnel.FOREIGN_SHARE_MAX,
                                  "reason_code": funnel.JUDGE_FOREIGN_CORE,
                                  "note": "CF-0539: a `foreign` entry starting in the hook, "
                                          "or `foreign` over share_max of the judged time, "
                                          "refuses a video at or over N in mode `fail`; in "
                                          "`warn` it is recorded on the video and passed"},
                 "wrong_person": {"rule": WRONG_PERSON_RULE,
                                  "mismatch": WRONG_PERSON_MISMATCH,
                                  "priced": wrong_person_priced(ledger),
                                  "note": "CF-0877: a `contradicts` with mismatch `person` "
                                          "(the line names someone, the frame shows another "
                                          "person) is charged score.judge_wrong_person in "
                                          "place of score.judge_contradicts, x2 in the hook, "
                                          "once the row is signed into `rules`; until then "
                                          "(`priced: false`) it is charged as contradicts and "
                                          "recorded per video"},
                 "strip_on_blur": {"rule": STRIP_RULE, "priced": strip_priced(ledger),
                                   "share_below": strip_on_blur.STRIP_SHARE,
                                   "allow_seconds": strip_on_blur.ALLOW_SECONDS,
                                   "note": "CF-0878: the seconds the plan shows a picture "
                                           "under share_below of the screen's height on its "
                                           "blurred ground (moving or not, under no opaque "
                                           "card), summed over the video; charged at this "
                                           "stage per second over allow_seconds that "
                                           "score.thin_picture does not charge, once the row "
                                           "is signed into `rules`"},
                 "other_work": {"rule": other_work_source.RULE,
                                "mismatch": other_work_source.MISMATCH,
                                "turns": list(OTHER_WORK_OVERRIDES),
                                "acceptance_code": other_work_source.ACCEPTANCE_CODE,
                                "note": "CF-0927: a shot whose upload's title names the film or "
                                        "series topic only as a credit, or an official upload "
                                        "whose title is about another work (CF-0924's rule, "
                                        "shared/other_work_source.py), is `contradicts` with "
                                        "mismatch `work` whatever the judge wrote (backs or "
                                        "neutral; foreign and a named mismatch are kept) and "
                                        "is charged score.judge_contradicts - official says "
                                        "whose cut it is, not which work"},
                 "footage_defects": {"kinds": list(FOOTAGE_DEFECTS), "priced": False,
                                     "refuses": list(REFUSING_DEFECTS),
                                     "rule": FOOTAGE_DEFECT_RULE,
                                     "reason_code": funnel.JUDGE_FOOTAGE_DEFECT,
                                     "note": "CF-0450: recorded per video, never charged in "
                                             "points. CF-0646 (the user 2026-10-09): "
                                             "`refuses` kinds refuse the video whatever its "
                                             "score - not shown to the user, rebuilt once by "
                                             "the operator; screen_recording is recorded only"},
                 "note": "CF-0434 (grill 2026-09-29): every contradicts, neutral and foreign "
                         "is a penalty of the score model, written as the stage `judge` of "
                         "the video's score log; the video is refused only when the score "
                         "after it is under N. Foreign on-screen text is priced as foreign "
                         "until the grill on burned-in text. A small corner logo of a studio "
                         "or streaming service in official footage is not written down at "
                         "all (CF-0298). A rejected video is not moved and not deleted - this "
                         "file is the record and shared/runlog/funnel.py stops counting it "
                         "as ready."},
        "counts": counts,
        # CF-0707: why `videos` is empty when 05 owed the judge nothing; null
        # whenever there was at least one video to judge.
        "nothing_to_judge": empty_why,
        "videos": videos,
        "not_judged": skipped,
    }
    return doc


def _report(doc, out_path):
    c = doc["counts"]
    L = [f"frame-judge gate -> {out_path}",
         f"  {c['judged']} of {c['videos']} video(s) judged: {c['passed']} pass, "
         f"{c['rejected']} reject, {c['incomplete']} incomplete, {c['not_judged']} not judged",
         "  entries: " + ", ".join(f"{c[w]} {w}" for w in funnel.FRAME_VERDICTS)
         + f", {c['foreign_text']} with foreign on-screen text"]
    if doc.get("nothing_to_judge"):
        L.append(f"  {doc['nothing_to_judge']}")
    for v in doc["videos"]:
        if v.get("score_line"):
            L.append(f"  SCORE {v['slug']}: {v['score_line']}")
        for d in v.get("footage_defects") or []:
            tag = "hard" if d["kind"] in REFUSING_DEFECTS else "unpriced"
            L.append(f"  [footage, {tag}] {v['slug']} {d['entry']}: {d['kind']} - {d['why']}")
        if (v.get("foreign_core") or {}).get("warning"):
            L.append(f"  [warn] {v['foreign_core']['warning']}")
        wp = v.get("wrong_person") or {}
        if wp.get("entries"):
            how = ("priced as score.judge_wrong_person" if wp.get("priced") else
                   "charged as contradicts - score.judge_wrong_person awaits the "
                   "user's signature (CF-0877)")
            L.append(f"  [wrong person] {v['slug']}: {', '.join(wp['entries'])}"
                     + (f" (hook: {', '.join(wp['hook_entries'])})" if wp.get("hook_entries")
                        else "") + f" - {how}")
        ow = v.get("other_work") or {}
        if ow.get("entries"):
            L.append(f"  [other work] {v['slug']}: {', '.join(ow['entries'])} cut from an upload "
                     f"about {', '.join(repr(t) for t in ow['title_subjects']) or 'another work'}, "
                     f"not {ow['work']!r} - contradicts, mismatch work"
                     + (f" (turned from the judge's word: {', '.join(ow['turned'])})"
                        if ow.get("turned") else "") + f" ({other_work_source.TASK})")
        st = v.get("strip_on_blur") or {}
        if st.get("seconds"):
            how = ("charged as score.narrow_strip_on_blur" if st.get("charged") else
                   "signed, nothing to charge here" if st.get("priced") else
                   "recorded - score.narrow_strip_on_blur awaits the user's signature "
                   "(CF-0878)")
            L.append(f"  [strip] {v['slug']}: {st['line']} - {how}")
        if v["gate"] != funnel.GATE_PASS:
            L.append(f"  [{v['gate']}] {v['slug']}: {v['reason']}")
    for s in doc["not_judged"]:
        L.append(f"  [not judged] {s['slug']}: {s['reason']}")
    return "\n".join(L)


def _merger():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import frame_judge_merge  # noqa: PLC0415
    return frame_judge_merge


def _new_only(bd, a):
    """CF-0800: the second pass - only the videos `06` has no row for.

    The new rows go to the staging file first; they are merged into `06` when
    every one of them is a finished judgement (or with `--record-incomplete`).
    An unfinished one keeps the staging file and `06` as they are, exit 1: the
    judge fixes its `verdicts.json` and runs this again - once merged, a row is
    never judged a second time."""
    fm = _merger()
    p06 = bd / funnel.FRAME_JUDGE_FILE
    if a.nothing_to_judge:
        raise SystemExit("frame-judge gate: --new-only and --nothing-to-judge do not go together")
    if not p06.is_file():
        raise SystemExit(f"frame-judge gate: --new-only, but there is no {p06.name} in {bd} - "
                         f"with no first pass there is nothing to add to; run the full pass")
    try:
        todo = fm.pending(p06)
    except fm.Refused as e:
        raise SystemExit(f"frame-judge gate: --new-only: {e}")
    staging = Path(a.out) if a.out else bd / fm.STAGING_NAME
    if not todo:
        if not a.quiet:
            print(f"frame-judge gate: --new-only - every video {VIDEO_EDITOR_FILE} owes the "
                  f"judge already has a row in {p06.name}; nothing judged, {p06.name} not "
                  f"touched", file=sys.stderr)
        return 0
    doc = gate(bd, a.ledger, a.foreign_core_mode, only=set(todo))
    doc["mode"] = fm.MODE
    staging.write_text(fm.dump(doc), encoding="utf-8")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    if not a.quiet:
        print(_report(doc, staging), file=sys.stderr)
    c = doc["counts"]
    unfinished = bool(c["incomplete"] or c["not_judged"])
    if unfinished and not a.record_incomplete:
        print(f"frame-judge gate: --new-only - {c['incomplete']} incomplete, {c['not_judged']} "
              f"not judged among {', '.join(todo)}: {staging.name} kept, {p06.name} not "
              f"touched; fix verdicts.json and run again (or --record-incomplete to record "
              f"them as they are)", file=sys.stderr)
        return 1
    say = (lambda *x: None) if a.quiet else (lambda line: print(line, file=sys.stderr))
    try:
        fm.merge(p06, staging, reason=a.reason or fm.DEFAULT_REASON, out=say)
    except fm.Refused as e:
        raise SystemExit(f"frame-judge gate: --new-only, merge refused - {e}")
    return 1 if unfinished else 0


def _repair(bd, a):
    """CF-0881: the repair pass (shared/judge_repair.py `apply`)."""
    if a.nothing_to_judge or a.new_only:
        raise SystemExit("frame-judge gate: --repair goes alone (not with --new-only or "
                         "--nothing-to-judge)")
    sys.path.insert(0, str(ROOT / "shared"))
    import judge_repair  # noqa: PLC0415
    say = (lambda *x: None) if a.quiet else (lambda line: print(line, file=sys.stderr))
    return judge_repair.apply(bd, a.ledger, a.foreign_core_mode,
                              record_incomplete=a.record_incomplete, out=say)


@runlog.script(runlog.S_FRAME_JUDGE, "gate")
def main(argv=None):
    ap = argparse.ArgumentParser(description="CF-0298: execute the frame judge's gate over a "
                                             "batch and write 06-frame-judge.json")
    ap.add_argument("--batch", default=os.environ.get(runlog.BATCH_ENV),
                    help="batch directory (default: $RUNLOG_BATCH)")
    ap.add_argument("--out", default=None,
                    help="where to write the artifact (default: <batch>/06-frame-judge.json)")
    ap.add_argument("--json", action="store_true", help="print the artifact on stdout")
    ap.add_argument("--quiet", action="store_true", help="no report on stderr")
    ap.add_argument("--ledger", default=None,
                    help="the price table to score with (default: shared/gate-prices.json)")
    ap.add_argument("--foreign-core-mode", default=None, choices=funnel.FOREIGN_CORE_MODES,
                    help="CF-0539: the mode of frame_judge.foreign_core (default: the "
                         "channel config's, else warn)")
    ap.add_argument("--nothing-to-judge", action="store_true",
                    help="CF-0707: write the empty record of a batch whose 05 owes the "
                         "judge nothing; refuse (exit 2) a batch with a video to judge")
    ap.add_argument("--new-only", action="store_true",
                    help="CF-0800: judge only the videos of 05 that 06 has no row for, "
                         "write them to 06-frame-judge.added.json (or --out) and merge "
                         "that into 06 - every row already in 06 stays byte for byte")
    ap.add_argument("--record-incomplete", action="store_true",
                    help="CF-0800, with --new-only: merge even when a new video's "
                         "judgement is unfinished (it is recorded `incomplete`, not ready)")
    ap.add_argument("--reason", default=None,
                    help="CF-0800, with --new-only: the merge record's reason")
    ap.add_argument("--repair", action="store_true",
                    help="CF-0881: the repair pass - the re-rendered videos of "
                         "work/repair-results.json judged on their changed blocks "
                         "(verdicts.repair.json) with the first pass's verdicts carried "
                         "for the rest; 06 gets repairs[] (repaired / repair_failed)")
    a = ap.parse_args(argv)
    if not a.batch:
        raise SystemExit("frame-judge gate: no batch directory - pass --batch DIR or set "
                         f"{runlog.BATCH_ENV}")
    bd = Path(a.batch)
    if not bd.is_dir():
        raise SystemExit(f"frame-judge gate: {bd} is not a directory")
    if a.new_only:
        return _new_only(bd, a)
    if a.repair:
        return _repair(bd, a)
    doc = gate(bd, a.ledger, a.foreign_core_mode, only_if_nothing=a.nothing_to_judge)
    out = Path(a.out) if a.out else bd / funnel.FRAME_JUDGE_FILE
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    if not a.quiet:
        print(_report(doc, out), file=sys.stderr)
    c = doc["counts"]
    return 1 if (c["incomplete"] or c["not_judged"]) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(2)
        raise
