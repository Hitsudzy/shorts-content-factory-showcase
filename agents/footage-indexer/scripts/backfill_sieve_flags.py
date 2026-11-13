#!/usr/bin/env python3
"""Answer the two sieve flags on shots nobody asked (CF-0355).

CF-0299 put `burned_text` / `on_topic` on every shot a describer writes, but
the pool described before it carries neither: 2821 shots in 84 sources of
`shared/footage` on 2026-09-23, 2383 of them not cards. The editor's
foreign-text filter drops exactly what is flagged (CF-0351) and a card with
no answer (CF-0354); an unflagged ordinary shot goes through, which is how
`vCOn4RibD1g:19` ("the same name captions visible") reached block 0 of
everyday-sorcery-2.

This is the description pass reduced to the two questions. It never
re-indexes and never touches `description`: the flags are the *describer's*
answer (shot_schema.py, CF-0299), so they are answered by a model looking at
the same frame the describer looked at - not by a heuristic over the words of
the old descriptions. The words are used for one thing only, the order of the
queue (`text_hint`).

Three steps, one source at a time:

    backfill_sieve_flags.py queue [--json]
        Every source with a shot whose `burned_text` is not a boolean, with its
        topic(s) out of the batch reports and a text hint for ordering.

    backfill_sieve_flags.py sheet <video_id> --out DIR
        The frames of the unanswered shots, taken at `tile_at` exactly as
        `index_footage.py` takes the contact-sheet tile (same extraction, same
        numbered tile, labelled with the shot's own index), as
        DIR/<id>.sheet.jpg, and DIR/<id>.questions.json - the rules, the
        topic and the shots to answer. The model reads both and writes
        DIR/<id>.answers.json.

    backfill_sieve_flags.py apply DIR/<id>.answers.json [--backup-dir B]
        Writes the answers into <id>.shots.json atomically
        (shot_schema.write_index). Only a flag that has no boolean yet is
        set - an answer somebody already gave is never overwritten. Every
        shot it touches carries `sieve_flags_by: "CF-0355"`, and a
        `burned_text: true` keeps the quoted text in `burned_text_quote`.

    backfill_sieve_flags.py batch <batch-dir> --out DIR [--answer-cmd CMD]
        CF-0359: the three steps above over one batch and nothing else. The
        sources of `01b-footage-index.json` that carry an unanswered shot get
        a sheet, an answer and an apply, one source at a time; the rest of the
        pool is not touched (the user's ruling of 2026-09-23 - the old pool
        belongs to dead topics and is not marked wholesale, only what a batch
        takes again). `source_sieve.py` runs this itself before it judges, so
        a batch that reuses an old source does not stop the stage on the
        CF-0355 exit code.

answers.json: {"video_id": "...", "answers": [{"index": 19, "burned_text":
true, "on_topic": true, "text": "SANDRA BIRCH"}, ...]}. `on_topic` may be
null (not answered); `text` is the burned-in text as seen, for `true`.

**Who answers, in the batch step.** The answer is a model's, looking at the
frame (above), and this file will not invent one. So the answerer is handed
in: `--answer-cmd` is a command run once per source with the questions, the
sheet and the path its answers belong at (`{questions}` / `{sheet}` /
`{answers}` / `{video_id}`, also in the environment as `SIEVE_FLAGS_*`) - the
frame subagent of the CF-0355 pilot, however the operator dispatches it. With
no command the step applies the answers that are already in the directory,
which is the pilot's own order of work: the subagents write
`DIR/<id>.answers.json`, the step applies them. A source left unanswered
either way is a *recorded failure* of this step and never a guess: CF-0359
has the sieve take such a source out of the batch with a code and go on.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402
from _fi_paths import factory_root  # noqa: E402 - CF-0267: unique name, see _fi_paths.py
import shot_schema  # noqa: E402

ROOT = factory_root()  # CF-0267: the root, not parent.parent.parent
FOOTAGE = ROOT / "shared" / "footage"
PIPELINE = ROOT / "pipeline"

SOURCE_TAG = "CF-0355"
PROVENANCE = "sieve_flags_by"
QUOTE = "burned_text_quote"

# CF-0359: the batch step. The report that says which sources a batch took,
# named here rather than imported - this file must not pull `ingest_batch.py`
# in, it is imported *by* the sieve which imports that already.
REPORT_FILE = "01b-footage-index.json"
ANSWERS_SUFFIX = ".answers.json"
QUESTIONS_SUFFIX = ".questions.json"
# The answerer command, when it is not passed on the command line. One place,
# so the sieve and this CLI read the same setting.
ANSWER_CMD_ENV = "SIEVE_FLAGS_ANSWER_CMD"
# Ceiling on one source's answerer, seconds. A frame subagent answers a
# source's shots in well under a minute; a command that sits longer than this
# is hung, and a hung answerer must not hold the stage - the source is
# recorded unanswered and the run goes on (DoD 1).
ANSWER_TIMEOUT_SECONDS = 240
BATCH_NOTE = (
    "CF-0359: the sieve flags of the sources this batch took, answered on the "
    "spot before the sieve judged them. Only the batch's own sources: the old "
    "pool is not marked wholesale (the user, 2026-09-23). A source with "
    "`ok: false` was not answered - the sieve takes it out of the batch with a "
    "code and a record in `failed[]`, and the run goes on.")

# Ordering only, never a verdict: an old description that mentions text is
# the likelier place for a `true`, so such sources go first.
TEXT_HINT_RE = re.compile(
    r"\b(caption|captions|subtitle|subtitles|text|title|titles|logo|words|"
    r"lettering|letters|credits?|card|onscreen|on-screen|overlay|banner|"
    r"headline|website|screenshot|tweet|reads)\b", re.I)

RULES = {
    "burned_text": (
        "true when somebody else's text is burned into this frame and will "
        "still be there after a 9:16 crop that removes the bottom band of the "
        "frame: a caption or subtitle anywhere outside the bottom band (the "
        "middle, the top), a title card, an end card, a credits card, a "
        "screenshot of a website, a lower-third name caption, a date or "
        "release-date card. false for a subtitle that sits in the bottom band "
        "only, false for a studio's or channel's small corner logo, false for "
        "text that is part of the pictured world (a sign on a wall, a name on "
        "a prop, a newspaper held by an actor), false for no text at all."),
    "on_topic": (
        "true when the frame pictures the topic's own work - its scenes, its "
        "people, its making, its own title card. false for a frame of "
        "something else entirely: another film or show, a comic-universe "
        "trailer, an app's website, a channel's own branding card."),
    # CF-0451: optional - asked, never required; a null leaves the describer's
    # sentence to answer (`screen_recording.shot_verdict`).
    "screen_recording": (
        "true when the frame is a screen filmed from the room - a cinema "
        "screen seen from the stalls with the audience's heads across it, "
        "the dark auditorium around it, the screen's edge or its keystoned "
        "perspective, moire, a phone pointed at a TV. false for the work's "
        "own image, including a scene the work sets in a cinema. null when "
        "you cannot tell."),
}


def unanswered(shot):
    return not isinstance(shot.get(shot_schema.BURNED_TEXT), bool)


def sieve_open(shot):
    """A shot the *sieve* cannot count: one of its two flags is not a boolean.

    `unanswered()` above asks about `burned_text` alone, which is the question
    the CF-0355 queue was built around (`on_topic` may honestly be left null
    there). The sieve is stricter - `shot_schema.sieve_counts()` calls a source
    complete only when every shot carries **both** flags, and an index one
    `on_topic` short stays `unsieved` however much text was answered for. So
    the batch step of CF-0359, whose whole purpose is to leave the sieve
    something it can judge, asks this instead.
    """
    return not all(isinstance(shot.get(k), bool) for k in shot_schema.SIEVE_FLAGS)


def load_index(video_id, footage=FOOTAGE):
    path = Path(footage) / f"{video_id}.shots.json"
    return path, json.loads(path.read_text())


def topics_by_source(pipeline=PIPELINE):
    """{video_id: [{topic_id, name, type, year, batch}]} from every batch's
    01b-footage-index.json `fetched[]` and its 01-trend-hunter.json topics."""
    out = {}
    for rep in sorted(Path(pipeline).glob(f"*/*/{REPORT_FILE}")):
        batch = rep.parent
        try:
            report = json.loads(rep.read_text())
        except (OSError, ValueError):
            continue
        titles, dumps = {}, {}
        th = batch / "01-trend-hunter.json"
        if th.exists():
            try:
                for t in json.loads(th.read_text()).get("topics") or []:
                    titles[t.get("topic_id")] = t.get("title_ref") or {}
                    dumps[t.get("topic_id")] = json.dumps(t)
            except (OSError, ValueError):
                pass
        pairs = []
        for f in report.get("fetched") or []:
            if not isinstance(f, dict):
                continue
            vid, tid = f.get("video_id"), f.get("topic_id")
            if tid is None and vid:
                # Reports before 2026-09 kept no topic on `fetched[]`; the
                # topic that offered the id as a candidate names it.
                tid = next((k for k, d in dumps.items() if f'"{vid}"' in d),
                           None)
            pairs.append((vid, tid))
        for tid, vids in (report.get("sources_by_topic") or {}).items():
            pairs.extend((v, tid) for v in vids or [])
        for vid, tid in pairs:
            if not vid:
                continue
            ref = titles.get(tid) or {}
            rec = {"topic_id": tid, "name": ref.get("name"),
                   "type": ref.get("type"), "year": ref.get("year"),
                   "batch": f"{batch.parent.name}/{batch.name}"}
            lst = out.setdefault(vid, [])
            if not any(r["topic_id"] == tid for r in lst):
                lst.append(rec)
    return out


def queue(footage=FOOTAGE, pipeline=PIPELINE):
    """One record per source with an unanswered shot, likeliest-text first."""
    topics = topics_by_source(pipeline)
    out = []
    for path in sorted(Path(footage).glob("*.shots.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        shots = [s for s in data.get("shots") or [] if isinstance(s, dict)]
        todo = [s for s in shots if unanswered(s)]
        if not todo:
            continue
        vid = path.name[: -len(".shots.json")]
        out.append({
            "video_id": vid,
            "shots": len(shots),
            "unanswered": len(todo),
            "unanswered_cards": sum(1 for s in todo if s.get("is_card")),
            "on_topic_unanswered": sum(
                1 for s in todo
                if not isinstance(s.get(shot_schema.ON_TOPIC), bool)),
            "text_hint": sum(1 for s in todo
                             if TEXT_HINT_RE.search(s.get("description") or "")),
            "topics": topics.get(vid, []),
        })
    out.sort(key=lambda r: (-r["text_hint"], r["video_id"]))
    return out


def topic_line(topics):
    names = []
    for t in topics:
        n = str(t.get("name") or t.get("topic_id") or "?")
        extra = ", ".join(str(x) for x in (t.get("type"), t.get("year")) if x)
        n = f"{n} ({extra})" if extra else n
        if n not in names:
            names.append(n)
    return "; ".join(names)


def questions(video_id, data, topics, open_test=unanswered):
    shots = [s for s in data.get("shots") or [] if isinstance(s, dict)]
    both = open_test is sieve_open
    return {
        "video_id": video_id,
        "task": SOURCE_TAG,
        "topic": topic_line(topics) or None,
        "rules": RULES,
        "both_flags_required": both,
        "how_to_answer": (
            "Answer both flags with a boolean on every shot listed: a source "
            "one `on_topic` short is not judged by the sieve at all and is "
            "taken out of the batch (CF-0359)." if both else
            "`on_topic` may be null when you cannot tell; `burned_text` is "
            "always a boolean."),
        "answer_format": {"video_id": video_id, "answers": [
            {"index": 0, "burned_text": False, "on_topic": True,
             "screen_recording": False, "text": None}]},
        "shots": [{"index": s.get("index"), "tile_at": s.get("tile_at"),
                   "is_card": bool(s.get("is_card")),
                   "old_description": s.get("description") or ""}
                  for s in shots if open_test(s)],
    }


def sheet(video_id, out_dir, footage=FOOTAGE, pipeline=PIPELINE,
          open_test=unanswered):
    """Build DIR/<id>.sheet.jpg and DIR/<id>.questions.json."""
    import index_footage  # heavy-ish imports; only the sheet needs them
    path, data = load_index(video_id, footage)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    q = questions(video_id, data, topics_by_source(pipeline).get(video_id, []),
                  open_test=open_test)
    todo = [s for s in data["shots"] if open_test(s)]
    video = Path(data.get("source") or path.with_name(f"{video_id}.mp4"))
    if not video.exists():
        video = path.with_name(f"{video_id}.mp4")
    with tempfile.TemporaryDirectory(prefix=f"cf0355-{video_id}-") as tmp:
        # The describer's frame: index_footage takes it at tile_time(shot),
        # which is what `tile_at` recorded - so the frame is asked for at
        # `tile_at` itself (a shot of an old index without it: tile_time).
        probes = [{"start": s["start"], "end": s["end"]} for s in todo]
        for p, s in zip(probes, todo):
            t = s.get(shot_schema.TILE_AT)
            if isinstance(t, (int, float)):
                p["start"] = p["end"] = t
        frames = index_footage.extract_frames(video, probes, Path(tmp))
        # contact_sheet labels a tile with its position in the list, so the
        # list is laid out by shot index with holes for the answered shots.
        width = max(s["index"] for s in todo) + 1
        by_index = [None] * width
        for s, f in zip(todo, frames):
            by_index[s["index"]] = f
        dest = out_dir / f"{video_id}.sheet.jpg"
        got = index_footage.contact_sheet(by_index, dest)
    missing = [s["index"] for s, f in zip(todo, frames) if f is None]
    q["sheet"] = str(got) if got else None
    q["frames_missing"] = missing
    (out_dir / f"{video_id}.questions.json").write_text(
        json.dumps(q, indent=2, ensure_ascii=False))
    return q


def apply_answers(data, answers):
    """Set the flags from `answers` on the shots that have none. Returns
    (data, counts). Raises ValueError on an answer that is not a boolean or
    names a shot the index does not have - nothing is written then."""
    by_index = {s.get("index"): s for s in data.get("shots") or []
                if isinstance(s, dict)}
    problems = []
    for a in answers:
        i = a.get("index")
        if i not in by_index:
            problems.append(f"shot {i!r}: not in the index")
        if not isinstance(a.get(shot_schema.BURNED_TEXT), bool):
            problems.append(f"shot {i!r}: burned_text must be true or false")
        v = a.get(shot_schema.ON_TOPIC)
        if v is not None and not isinstance(v, bool):
            problems.append(f"shot {i!r}: on_topic must be true, false or null")
        v = a.get(shot_schema.SCREEN_RECORDING)
        if v is not None and not isinstance(v, bool):
            problems.append(f"shot {i!r}: screen_recording must be true, "
                            f"false or null")
    if problems:
        raise ValueError("; ".join(problems))
    counts = {"burned_text_set": 0, "on_topic_set": 0, "true": 0,
              "kept_existing": 0, "screen_recording_set": 0}
    for a in answers:
        s = by_index[a["index"]]
        touched = False
        if isinstance(s.get(shot_schema.BURNED_TEXT), bool):
            counts["kept_existing"] += 1
        else:
            s[shot_schema.BURNED_TEXT] = a[shot_schema.BURNED_TEXT]
            counts["burned_text_set"] += 1
            touched = True
            if a[shot_schema.BURNED_TEXT]:
                counts["true"] += 1
                text = " ".join(str(a.get("text") or "").split())
                if text:
                    s[QUOTE] = text
        v = a.get(shot_schema.ON_TOPIC)
        if isinstance(v, bool) and not isinstance(s.get(shot_schema.ON_TOPIC), bool):
            s[shot_schema.ON_TOPIC] = v
            counts["on_topic_set"] += 1
            touched = True
        v = a.get(shot_schema.SCREEN_RECORDING)
        if (isinstance(v, bool)
                and not isinstance(s.get(shot_schema.SCREEN_RECORDING), bool)):
            s[shot_schema.SCREEN_RECORDING] = v
            counts["screen_recording_set"] += 1
            touched = True
        if touched:
            s[PROVENANCE] = SOURCE_TAG
    return data, counts


def apply_file(answers_path, footage=FOOTAGE, backup_dir=None,
               open_test=unanswered):
    doc = json.loads(Path(answers_path).read_text())
    vid = doc["video_id"]
    path, data = load_index(vid, footage)
    data, counts = apply_answers(data, doc.get("answers") or [])
    shot_schema.require_valid(data, str(path))
    if backup_dir:
        b = Path(backup_dir) / path.name
        b.parent.mkdir(parents=True, exist_ok=True)
        if not b.exists():
            shutil.copy2(path, b)
    if counts["burned_text_set"] or counts["on_topic_set"]:
        shot_schema.write_index(path, data)
    left = sum(1 for s in data["shots"] if open_test(s))
    counts.update(video_id=vid, left=left)
    return counts


# ---------------------------------------------------------------------------
# The batch step (CF-0359)
#
# `CF-0355` gave the sieve an exit code over a source with no answer on
# `burned_text`, and the stage does not close until the answer is there. The
# full pool was never going to be marked - 2708 shots in 82 sources belonging
# to dead topics, and after publication the sources are deleted (CF-0358) - so
# the answer is taken where it is needed: the sources *this* batch took, at the
# moment the batch is being sieved. Everything below is the three steps above
# driven over that list, one source at a time, and nothing about the rest of
# the pool.


def batch_sources(report):
    """The ids one batch took, in the report's own order and without repeats.

    `sources_by_topic` first - those are the ones the sieve judges - then
    anything in `fetched` that is not in it, because a fetched source is in
    the batch whatever the floor did with it afterwards. CF-0567: never an
    own capture - the sieve keeps it by its kind.
    """
    out = []
    for vids in (report.get("sources_by_topic") or {}).values():
        for v in vids or []:
            if v and v not in out and not _own_capture(v):
                out.append(v)
    for f in report.get("fetched") or []:
        if not isinstance(f, dict):
            continue
        v = f.get("video_id")
        if v and v not in out and not _own_capture(v):
            out.append(v)
    return out


def _own_capture(vid):
    """CF-0567: an own capture is not sieved (`source_sieve.own_capture_kept`),
    so nobody is asked for its flags."""
    return isinstance(vid, str) and vid.startswith("own_capture-")


def read_report(batch):
    """The loaded `01b-footage-index.json` of a batch directory."""
    return json.loads((Path(batch) / REPORT_FILE).read_text())


def batch_queue(report, footage=FOOTAGE):
    """One record per batch source that still owes an answer.

    A source whose index cannot be read is in the list with `error` set and
    nothing else: it owes an answer nobody can give, and the caller has to see
    it rather than mistake it for a source that was never asked (CF-0281 owns
    the missing index itself).
    """
    rows = []
    for vid in batch_sources(report):
        try:
            _, data = load_index(vid, footage)
        except (OSError, ValueError) as e:
            rows.append({"video_id": vid, "shots": 0, "unanswered": 0,
                         "error": f"no readable index for it "
                                  f"({type(e).__name__}), so its flags cannot "
                                  f"be answered here"})
            continue
        shots = [x for x in data.get("shots") or [] if isinstance(x, dict)]
        todo = [x for x in shots if sieve_open(x)]
        if not todo:
            continue
        rows.append({"video_id": vid, "shots": len(shots),
                     "unanswered": len(todo), "error": None})
    return rows


def answer_cmd_setting(cmd=None):
    """The answerer command: the one passed, else the environment's, else
    None - "apply whatever answers are already in the directory"."""
    return cmd or (os.environ.get(ANSWER_CMD_ENV) or "").strip() or None


def answer_by_cmd(cmd, q, answers_path, timeout=ANSWER_TIMEOUT_SECONDS,
                  out_dir=None):
    """Run the configured answerer over one source's questions.

    The command is expected to write `answers_path`. It gets the three paths
    and the id both as `{questions}` / `{sheet}` / `{answers}` / `{video_id}`
    in its text and as `SIEVE_FLAGS_QUESTIONS` / `_SHEET` / `_ANSWERS` /
    `_VIDEO_ID` in its environment, so a one-liner and a script are both
    possible. Raises on a non-zero exit, on the ceiling, and on a command that
    ran and wrote nothing - all three are "not answered", which is a recorded
    failure and never a guess.

    CF-0478: two more words, so the channel's config can name the repo's own
    answerer without knowing where this checkout lives or which directory the
    stage was started from: `{python}` is the interpreter running this file
    (the indexer's .venv) and `{scripts}` is this file's directory. The paths
    are shell-quoted; a command that needs them unquoted reads the
    environment instead.
    """
    vid = q["video_id"]
    out_dir = Path(out_dir) if out_dir else Path(answers_path).parent
    paths = {"questions": str(out_dir / f"{vid}{QUESTIONS_SUFFIX}"),
             "sheet": str(q.get("sheet") or ""),
             "answers": str(answers_path), "video_id": vid,
             "python": sys.executable, "scripts": str(HERE)}
    line = cmd
    for k, v in paths.items():
        line = line.replace("{" + k + "}", shlex.quote(v))
    env = dict(os.environ)
    env.update({f"SIEVE_FLAGS_{k.upper()}": v for k, v in paths.items()
                if k not in ("python", "scripts")})
    r = subprocess.run(line, shell=True, env=env, timeout=timeout,
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = " ".join((r.stderr or r.stdout or "").split())[-300:]
        raise RuntimeError(f"the answerer exited {r.returncode}"
                           + (f": {tail}" if tail else ""))
    if not Path(answers_path).exists():
        raise RuntimeError("the answerer wrote no "
                           f"{Path(answers_path).name}")


def backfill_source(video_id, out_dir, footage=FOOTAGE, pipeline=PIPELINE,
                    answer=None, backup_dir=None, make_sheet=None):
    """Sheet, answer and apply for one source. Never raises.

    Returns the record that goes into the report: what was asked, what was
    set, what is left, `ok` and - when it is false - the sentence that says
    why, which is what the sieve's refusal of this source will quote. Every
    failure of every step lands there: no mp4 to take the frames from
    (CF-0358 deletes them), an answerer that timed out, an answer file that
    is not valid. The run is not allowed to stop for any of it (DoD 1).
    """
    rec = {"video_id": video_id, "asked": 0, "burned_text_set": 0,
           "on_topic_set": 0, "left": None, "sheet": None, "ok": False,
           "error": None}
    build = make_sheet or sheet
    try:
        q = build(video_id, out_dir, footage, pipeline, sieve_open)
        rec["asked"] = len(q.get("shots") or [])
        rec["sheet"] = q.get("sheet")
        path = Path(out_dir) / f"{video_id}{ANSWERS_SUFFIX}"
        if answer is not None:
            answer(q, path)
        if not path.exists():
            raise RuntimeError(
                f"no answers for it ({path.name}): nothing answered the "
                f"{rec['asked']} open shot(s) of this source")
        c = apply_file(path, footage, backup_dir, open_test=sieve_open)
        rec.update(burned_text_set=c["burned_text_set"],
                   on_topic_set=c["on_topic_set"], left=c["left"])
        if c["left"]:
            raise RuntimeError(
                f"{c['left']} of its shot(s) are still unanswered after the "
                f"answers were applied")
        rec["ok"] = True
    except Exception as e:                      # noqa: BLE001 - see docstring
        rec["error"] = f"{type(e).__name__}: {e}" if not isinstance(
            e, RuntimeError) else str(e)
    return rec


def backfill_batch(report, out_dir, footage=FOOTAGE, pipeline=PIPELINE,
                   answer=None, answer_cmd=None, backup_dir=None, log=None,
                   only=None, timeout=ANSWER_TIMEOUT_SECONDS,
                   make_sheet=None):
    """The batch step: every source of `report` that owes an answer, answered.

    `answer` is a callable `(questions, answers_path) -> None`; with none, an
    `answer_cmd` (or `SIEVE_FLAGS_ANSWER_CMD`) is run per source, and with
    neither the answers already in `out_dir` are applied. `only` narrows the
    list further - the sieve passes the ids it is about to judge.

    Returns the block that goes into the report under `sieve_backfill`.
    """
    log = log or (lambda *a, **k: None)
    cmd = answer_cmd_setting(answer_cmd)
    if answer is None and cmd:
        def answer(q, path, _cmd=cmd, _t=timeout, _d=out_dir):
            answer_by_cmd(_cmd, q, path, timeout=_t, out_dir=_d)
    rows = batch_queue(report, footage)
    if only is not None:
        keep = set(only)
        rows = [r for r in rows if r["video_id"] in keep]
    records = []
    for r in rows:
        if r.get("error"):
            records.append({"video_id": r["video_id"], "asked": 0,
                            "burned_text_set": 0, "on_topic_set": 0,
                            "left": None, "sheet": None, "ok": False,
                            "error": r["error"]})
        else:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            records.append(backfill_source(
                r["video_id"], out_dir, footage, pipeline, answer=answer,
                backup_dir=backup_dir, make_sheet=make_sheet))
        rec = records[-1]
        log(f"BACKFILL {rec['video_id']}: "
            + (f"{rec['burned_text_set']} shot(s) answered"
               if rec["ok"] else f"not answered - {rec['error']}"))
    return {
        "ran": True,
        "task": "CF-0359",
        "answerer": cmd or ("callable" if answer is not None else "answers in "
                            "the directory"),
        "out_dir": str(out_dir),
        "sources": records,
        "answered": [r["video_id"] for r in records if r["ok"]],
        "failed": [r["video_id"] for r in records if not r["ok"]],
        "note": BATCH_NOTE,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--footage", default=str(FOOTAGE))
    p.add_argument("--pipeline", default=str(PIPELINE))
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--json", action="store_true")
    s = sub.add_parser("sheet")
    s.add_argument("video_id", nargs="+")
    s.add_argument("--out", required=True)
    a = sub.add_parser("apply")
    a.add_argument("answers", nargs="+")
    a.add_argument("--backup-dir")
    b = sub.add_parser("batch")
    b.add_argument("batch")
    b.add_argument("--out", required=True)
    b.add_argument("--answer-cmd",
                   help="command run once per source over its sheet; it is "
                        "given {questions} {sheet} {answers} {video_id} (and "
                        f"SIEVE_FLAGS_* in its environment) and must write "
                        f"{{answers}}. Default: ${ANSWER_CMD_ENV}, and with "
                        f"neither, the answers already in --out are applied")
    b.add_argument("--answer-timeout", type=int,
                   default=ANSWER_TIMEOUT_SECONDS)
    b.add_argument("--backup-dir")
    b.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "queue":
        rows = queue(args.footage, args.pipeline)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for r in rows:
                print(f"{r['video_id']}\t{r['unanswered']}/{r['shots']}\t"
                      f"cards {r['unanswered_cards']}\thint {r['text_hint']}\t"
                      f"{topic_line(r['topics']) or '-'}")
            print(f"{sum(r['unanswered'] for r in rows)} shot(s) unanswered "
                  f"in {len(rows)} source(s)")
        return 0
    if args.cmd == "sheet":
        for vid in args.video_id:
            q_ = sheet(vid, args.out, args.footage, args.pipeline)
            print(f"{vid}: {len(q_['shots'])} shot(s) -> {q_['sheet']}"
                  + (f" (no frame for {q_['frames_missing']})"
                     if q_["frames_missing"] else ""))
        return 0
    if args.cmd == "batch":
        report = read_report(args.batch)
        block = backfill_batch(report, args.out, args.footage, args.pipeline,
                               answer_cmd=args.answer_cmd,
                               backup_dir=args.backup_dir, log=print,
                               timeout=args.answer_timeout)
        if args.json:
            print(json.dumps(block, indent=2, ensure_ascii=False))
        print(f"{len(block['answered'])} source(s) answered, "
              f"{len(block['failed'])} not "
              + (f"({', '.join(block['failed'])})" if block["failed"] else ""))
        # A source left unanswered is a failure of this step - the sieve takes
        # it out of the batch and the run goes on (CF-0359), but the step that
        # could not answer it did not succeed.
        return 1 if block["failed"] else 0
    bad = 0
    for path in args.answers:
        try:
            c = apply_file(path, args.footage, args.backup_dir)
        except (OSError, ValueError, KeyError) as e:
            bad += 1
            print(f"{path}: not applied - {e}")
            continue
        print(f"{c['video_id']}: burned_text set on {c['burned_text_set']} "
              f"({c['true']} true), on_topic on {c['on_topic_set']}, "
              f"{c['kept_existing']} already answered, {c['left']} left")
    return 1 if bad else 0


@runlog.script("footage-indexer", "backfill-sieve-flags",
               name="backfill_sieve_flags.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
