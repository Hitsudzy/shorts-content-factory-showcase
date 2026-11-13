#!/usr/bin/env python3
"""CF-0881: repair instead of refusal - a video the frame judge refused for a
defect that sits in one or two blocks gets one repair pass: the Editor re-picks
the picture of just those blocks (the defective shot excluded, the topic's own
already indexed pool, no YouTube search), re-renders, the judge looks at the
changed blocks only, and the gate decides again.

Why (the funnel of 20-27.10, the user's "мне нужен результат" of 27.10): Reel
lost 13 of 20 videos after the render; 3 of the 7 `judge_footage_defect`
refusals were one bad block out of 16-20 (tulsa-king 1514Z block-14
thin_strip, resident-dread 0836Z block-10 thin_strip, two-and-a-half-men 0836Z
block-5-meme smeared), and the whole video went, the topic with it, the quota
spent. `reserve_after_judge` (shared/run_checks.py) replaces the topic rather
than mending the video, and held M=0 in 7 batches of 7.

    python3 shared/judge_repair.py candidates <batch> [--json]
    python3 shared/judge_repair.py request    <batch>
    python3 shared/judge_repair.py run-editor <batch> --editor-dir DIR [--python PY]
    python3 shared/judge_repair.py pending    <batch>

**What is repairable** (`assess`). A row of `06-frame-judge.json` with
`gate: reject` whose defects sit in at most MAX_BLOCKS blocks:

* `judge_footage_defect` - the entries of `footage_defects[]` of a refusing
  kind (`thin_strip`, `smeared`, `cut_subject`; `screen_recording` refuses
  nothing here);
* `contradicts` with `mismatch: person` - the line names someone, the frame
  shows another person (CF-0877);
* `foreign` in the hook (`foreign_core.hook_entries`, CF-0539); a
  `judge_foreign_core` refusal on the share of foreign time is repairable only
  when every foreign entry is a target.

Every defect of those kinds on the video is a target (mending one and leaving
the other would only move the refusal), and the video is repairable only when
mending them can turn the gate: the score after the judge plus what the
targets were charged reaches the threshold (a video under N for twenty
`neutral` blocks is not a two-block repair). Each target block needs something
to exclude: a shot of its own (`source.shot` of the pack entry, else the
plan's block `shot`), or a meme card (entry kind `meme`: the card is dropped or
swapped, the footage under it stays). A topic with another video through the
gate needs nothing; a video already in `06 -> repairs[]` had its pass.

**The request** (`request`) is `<batch>/work/repair-requests.json`
(REQUEST_SCHEMA), the Editor's input; its exact contract is in the task file
(tasks/CF-0881-..., "Спецификация для video-editor") and in docs/pipeline.md.
The file's existence is the round: one pass per batch.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0881"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

JUDGE_FILE = "06-frame-judge.json"
EDITOR_FILE = "05-video-editor.json"
SCRIPTS_FILE = "03-content-researcher.json"
PACK_DIRNAME = "frame-judge"
MANIFEST = "manifest.json"
PLAN_FILE = "plan.json"

MAX_BLOCKS = 2
GATE_PASS, GATE_REJECT = "pass", "reject"
# The reason codes of the gate (scripts/frame_judge_gate.py / funnel) a repair
# can answer.
FOOTAGE_DEFECT_CODE = "judge_footage_defect"
FOREIGN_CORE_CODE = "judge_foreign_core"
BELOW_N_CODE = "score_below_threshold"
REPAIRABLE_CODES = (FOOTAGE_DEFECT_CODE, FOREIGN_CORE_CODE, BELOW_N_CODE)
REFUSING_DEFECTS = ("thin_strip", "cut_subject", "smeared")   # frame_judge_gate.REFUSING_DEFECTS
WRONG_PERSON = "wrong_person"
FOREIGN_HOOK = "foreign_in_hook"
FOREIGN_SHARE = "foreign_share"
TARGET_SHOT, TARGET_MEME = "shot", "meme"

REPAIRED, REPAIR_FAILED = "repaired", "repair_failed"
OUTCOMES = (REPAIRED, REPAIR_FAILED)
REPAIRS_KEY = "repairs"                 # 06 top level: one record per repaired video

# The contract with the Video Editor (task file, "Спецификация для video-editor").
REQUEST_FILE = "work/repair-requests.json"
REQUEST_SCHEMA = "judge-repair-request/1"
RESULT_FILE = "work/repair-results.json"
RESULT_SCHEMA = "judge-repair-result/1"
EDITOR_ENTRY = "scripts/repair_blocks.py"
EDITOR_TIMEOUT_S = 90 * 60
RENDERED = "rendered"
EDITOR_OUTCOMES = (RENDERED, "no_replacement", "render_failed", "qc_failed", "failed",
                   "not_attempted")
# What the judge writes in mode `repair`: the verdicts of the changed entries only.
REPAIR_VERDICTS = "verdicts.repair.json"

_BLOCK_ID = re.compile(r"^block-(\d+)(?:-(.+))?$")
_SCRIPT_SUFFIX = re.compile(r"-script\d+$")


def _read(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _rows(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(row):
    return row.get("slug") or Path(row.get("output_path") or "").stem or row.get("script_id")


# --------------------------------------------------------------------------
# what is repairable


def defect_targets(row):
    """`(targets, share_refusal)` - the defects of one `06` row a repair can
    answer, one per entry (`{entry, kind, why, start, end, charged}`), in the
    row's entry order; `share_refusal` is True when the row's foreign core
    refuses on the share of foreign time (not only on the hook)."""
    verdicts = {r.get("entry"): r for r in _rows(row, "verdicts") if r.get("entry")}
    found = {}

    def add(entry, kind, why):
        if entry and entry not in found:
            v = verdicts.get(entry) or {}
            found[entry] = {"entry": entry, "kind": kind, "why": why,
                            "start": v.get("start"), "end": v.get("end"),
                            "charged": v.get("charged") or 0}

    for d in _rows(row, "footage_defects"):
        if d.get("kind") in REFUSING_DEFECTS:
            add(d.get("entry"), d["kind"], d.get("why"))
    for e, v in verdicts.items():
        if v.get("verdict") == "contradicts" and v.get("mismatch") == "person":
            add(e, WRONG_PERSON, v.get("why"))
    core = row.get("foreign_core") if isinstance(row.get("foreign_core"), dict) else {}
    for e in core.get("hook_entries") or []:
        add(e, FOREIGN_HOOK, (verdicts.get(e) or {}).get("why"))
    share = core.get("share")
    share_refusal = bool(isinstance(share, (int, float)) and isinstance(core.get("share_max"), (int, float))
                         and share >= core["share_max"])
    if share_refusal:
        for e in core.get("foreign_entries") or []:
            add(e, FOREIGN_SHARE, (verdicts.get(e) or {}).get("why"))
    order = list(verdicts)
    return sorted(found.values(), key=lambda t: (order.index(t["entry"]) if t["entry"] in order
                                                 else len(order))), share_refusal


def block_of(entry_id, manifest_entry=None):
    """The plan block index of a pack entry (`block` on the entry, else the
    number in `block-N[-kind]`), or None."""
    if isinstance(manifest_entry, dict) and isinstance(manifest_entry.get("block"), int):
        return manifest_entry["block"]
    m = _BLOCK_ID.match(str(entry_id or ""))
    return int(m.group(1)) if m else None


def target_of(entry_id, manifest_entry, plan_blocks):
    """`(target kind, shot or None, why not)` - what the Editor would exclude
    on this entry's block."""
    me = manifest_entry if isinstance(manifest_entry, dict) else {}
    m = _BLOCK_ID.match(str(entry_id or ""))
    kind = me.get("kind") or (m.group(2) if m and m.group(2) else None)
    if kind == TARGET_MEME:
        return TARGET_MEME, None, None
    if not m:
        return None, None, f"{entry_id} is not a block of the plan (only blocks are re-picked)"
    src = me.get("source") if isinstance(me.get("source"), dict) else {}
    if src.get("own_graphic") or src.get("own_capture"):
        return None, None, f"{entry_id} shows our own graphic or capture, not a pool shot"
    shot = src.get("shot")
    if not shot:
        i = block_of(entry_id, me)
        pb = plan_blocks[i] if i is not None and 0 <= i < len(plan_blocks) else {}
        shot = pb.get("shot") if isinstance(pb, dict) else None
    if not shot:
        return None, None, f"{entry_id} shows no shot of its own (a card or a split)"
    return TARGET_SHOT, shot, None


def assess(row, manifest=None, plan=None):
    """`(blocks or None, why)` for one `06` row: the blocks a repair re-picks
    (`[{block, entry, target, exclude_shot, kind, why, start, end}]`), or None
    and the sentence why the row is not repairable."""
    slug = _slug(row)
    if row.get("gate") != GATE_REJECT:
        return None, f"{slug}: gate {row.get('gate')!r}, not a refusal"
    code = row.get("reason_code")
    if code not in REPAIRABLE_CODES:
        return None, f"{slug}: refused for {code!r}, which no block repair answers"
    targets, _share = defect_targets(row)
    if not targets:
        return None, f"{slug}: refused for {code}, with no defect in a block a repair re-picks"
    entries = {e.get("id"): e for e in _rows(manifest, "entries") if e.get("id")}
    plan_blocks = [b for b in (plan or {}).get("blocks") or []] if isinstance(plan, dict) else []
    blocks = {}
    for t in targets:
        me = entries.get(t["entry"])
        i = block_of(t["entry"], me)
        if i is None:
            return None, f"{slug}: {t['entry']} ({t['kind']}) is not a block of the plan"
        kind, shot, why_not = target_of(t["entry"], me, plan_blocks)
        if kind is None:
            return None, f"{slug}: {why_not}"
        blocks.setdefault(i, []).append({
            "block": i, "entry": t["entry"], "target": kind, "exclude_shot": shot,
            "kind": t["kind"], "why": t["why"], "start": t["start"], "end": t["end"],
            "charged": t["charged"]})
    if len(blocks) > MAX_BLOCKS:
        return None, (f"{slug}: defects in {len(blocks)} blocks ("
                      + ", ".join(f"block-{i}" for i in sorted(blocks))
                      + f") - over {MAX_BLOCKS}, a rebuild and not a repair")
    sc = row.get("score") if isinstance(row.get("score"), dict) else {}
    score, n = sc.get("score"), sc.get("threshold")
    if isinstance(score, (int, float)) and isinstance(n, (int, float)):
        # `charged` is the price as the score model writes it (negative)
        lift = sum(abs(t["charged"] or 0) for t in targets)
        if score + lift < n:
            return None, (f"{slug}: {score} + {lift:g} charged on the defect blocks < {n} - "
                          f"mending them cannot lift the score to N")
    out = [x for i in sorted(blocks) for x in blocks[i]]
    return out, (f"{slug}: {code} in {len(blocks)} block(s): "
                 + ", ".join(f"{x['entry']} {x['kind']}" for x in out))


def repaired_ids(d06):
    """`script_id`s `06 -> repairs[]` already holds a record of."""
    return {r.get("script_id") for r in _rows(d06, REPAIRS_KEY) if r.get("script_id")}


def _topic_map(batch):
    d = _read(Path(batch) / SCRIPTS_FILE) or {}
    return {s["script_id"]: s.get("topic_id") for s in _rows(d, "scripts") if s.get("script_id")}


def topic_of(row, topics):
    sid = row.get("script_id")
    return row.get("topic_id") or topics.get(sid) or (_SCRIPT_SUFFIX.sub("", sid) if sid else None)


def candidates(batch):
    """`(repairable, skipped)` over the batch's `06`: `repairable` is
    `[{script_id, slug, topic_id, reason_code, score_line, blocks}]` in `06`'s
    order, `skipped` `[{script_id, slug, why}]` for every refused row that is
    not. No `06`: `([], [])`."""
    batch = Path(batch)
    d06 = _read(batch / JUDGE_FILE)
    if d06 is None:
        return [], []
    topics = _topic_map(batch)
    rows = _rows(d06, "videos")
    passed = {topic_of(r, topics) for r in rows if r.get("gate") == GATE_PASS}
    done = repaired_ids(d06)
    ok, skipped = [], []
    for r in rows:
        if r.get("gate") == GATE_PASS:
            continue
        sid, slug, tid = r.get("script_id"), _slug(r), topic_of(r, topics)
        if sid in done:
            skipped.append({"script_id": sid, "slug": slug, "why": f"{slug}: already had its repair pass"})
            continue
        if tid in passed:
            skipped.append({"script_id": sid, "slug": slug,
                            "why": f"{slug}: topic {tid} has another video through the gate"})
            continue
        work = batch / "work" / slug
        blocks, why = assess(r, _read(work / PACK_DIRNAME / MANIFEST), _read(work / PLAN_FILE))
        if blocks is None:
            skipped.append({"script_id": sid, "slug": slug, "why": why})
            continue
        ok.append({"script_id": sid, "slug": slug, "topic_id": tid,
                   "reason_code": r.get("reason_code"), "score_line": r.get("score_line"),
                   "blocks": blocks, "why": why})
    return ok, skipped


# --------------------------------------------------------------------------
# the measurement after the fact (task item 4): read-only over a batch's own
# artifacts - no pool, no index, no search


def pool_alternatives(batch, cand):
    """For each block of a candidate, what the topic's pool offered besides
    the shot shown: `{block, entry, target, basis, others, long_enough}`.
    `basis` says where it is read: `length_supply` (the plan block's walk over
    the anchor's candidates: `offered` - 1, `long_enough` without the shown
    shot), `candidate_supply` (the anchor's `offered` less `used`), or
    `pool_unused` (the storyboard's `pool_capacity.unused`: eligible shots of
    the topic's pool no block shows - any picture, not the anchor's match).
    A meme target always has one (the card is dropped; the footage under it
    stays). `others` None: nothing says."""
    work = Path(batch) / "work" / cand["slug"]
    plan = _read(work / PLAN_FILE) or {}
    pblocks = plan.get("blocks") if isinstance(plan.get("blocks"), list) else []
    sb = _read(work / "storyboard.json") or {}
    cap = sb.get("pool_capacity") if isinstance(sb.get("pool_capacity"), dict) else {}
    out = []
    for b in cand["blocks"]:
        rec = {"block": b["block"], "entry": b["entry"], "target": b["target"],
               "basis": None, "others": None, "long_enough": None}
        pb = pblocks[b["block"]] if 0 <= b["block"] < len(pblocks) else {}
        pb = pb if isinstance(pb, dict) else {}
        ls, cs = pb.get("length_supply"), pb.get("candidate_supply")
        if b["target"] == TARGET_MEME:
            rec.update(basis="meme", others=1, long_enough=1)
        elif isinstance(ls, dict) and isinstance(ls.get("offered"), int):
            le = ls.get("long_enough")
            rec.update(basis="length_supply", others=max(ls["offered"] - 1, 0),
                       long_enough=(len([x for x in le if not (isinstance(x, dict) and
                                                              x.get("shot") == b["exclude_shot"])])
                                    if isinstance(le, list) else ls.get("long_enough_offered")))
        elif isinstance(cs, dict) and isinstance(cs.get("offered"), int):
            rec.update(basis="candidate_supply",
                       others=max(cs["offered"] - (cs.get("used") or 1), 0))
        elif isinstance(cap.get("unused"), list):
            rec.update(basis="pool_unused", others=len(cap["unused"]))
        out.append(rec)
    return out


def measure(batches, out=print):
    """The retro count over finished batches: refused videos, the repairable
    ones (with why the rest are not), and per block whether the pool had
    another candidate. Returns the summary dict."""
    tot = {"batches": 0, "refused": 0, "repairable": 0, "with_alternatives": 0,
           "by_code": {}, "not_repairable": {}}
    for bd in batches:
        bd = Path(bd)
        d06 = _read(bd / JUDGE_FILE)
        if d06 is None:
            continue
        tot["batches"] += 1
        refused = [r for r in _rows(d06, "videos") if r.get("gate") == GATE_REJECT]
        tot["refused"] += len(refused)
        for r in refused:
            tot["by_code"][r.get("reason_code")] = tot["by_code"].get(r.get("reason_code"), 0) + 1
        ok, skipped = candidates(bd)
        for s in skipped:
            key = re.sub(r"^[^:]*: ", "", s["why"])
            key = re.sub(r"[0-9.]+", "N", key)[:70]
            tot["not_repairable"][key] = tot["not_repairable"].get(key, 0) + 1
        for c in ok:
            tot["repairable"] += 1
            alts = pool_alternatives(bd, c)
            has = all((a["others"] or 0) > 0 for a in alts)
            tot["with_alternatives"] += has
            out(f"{bd.parent.name}/{bd.name} {c['slug']} ({c['reason_code']}): " + "; ".join(
                f"{a['entry']} {a['target']} {a['basis']} others={a['others']} "
                f"long_enough={a['long_enough']}"
                for a in alts) + (" -> pool has a replacement" if has else " -> no replacement"))
    out(json.dumps(tot, ensure_ascii=False, indent=1))
    return tot


# --------------------------------------------------------------------------
# the request to the Editor and the seam that calls it (task item 3)


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def request_doc(batch, ok, when=None):
    d06 = _read(Path(batch) / JUDGE_FILE) or {}
    return {"schema": REQUEST_SCHEMA, "task": TASK, "batch_id": d06.get("batch_id"),
            "channel": _channel_ids().resolve_channel(d06.get("channel"), ROOT),
            "at": when or _now_z(),
            # the judgement this round answers: a re-judged 06 (a rerun from the
            # judge) makes the request stale, and the round may run again
            "judged_at": d06.get("judged_at"),
            "rules": {"max_blocks": MAX_BLOCKS, "search": False, "one_pass": True,
                      "pool": "the topic's own indexed pool only - no YouTube search, "
                              "no new source; the defective shot is excluded on its block",
                      "result": RESULT_FILE, "result_schema": RESULT_SCHEMA},
            "videos": [{k: c[k] for k in ("script_id", "slug", "topic_id", "reason_code",
                                          "score_line")}
                       | {"blocks": [{k: b[k] for k in ("block", "entry", "target",
                                                        "exclude_shot", "kind", "why",
                                                        "start", "end")}
                                     for b in c["blocks"]]}
                       for c in ok]}


def round_ran(batch):
    """The request of this judgement is there: REQUEST_FILE whose `judged_at`
    is `06`'s. One written for an earlier judgement (a rerun from the judge
    wrote `06` anew) is stale and does not count."""
    batch = Path(batch)
    req = _read(batch / REQUEST_FILE)
    d06 = _read(batch / JUDGE_FILE) or {}
    return req is not None and req.get("judged_at") == d06.get("judged_at")


def request(batch, out=print, when=None):
    """Write the round's request (REQUEST_FILE) from `candidates`; returns it.
    A second call never rewrites it - the file is the round (one pass); a
    stale one (`round_ran` false) is replaced, its result file removed."""
    batch = Path(batch)
    p = batch / REQUEST_FILE
    if round_ran(batch):
        out(f"{REQUEST_FILE} is already there - one repair pass per batch, not rewritten")
        return _read(p)
    if (batch / RESULT_FILE).exists():
        (batch / RESULT_FILE).unlink()
    ok, skipped = candidates(batch)
    _print_candidates(ok, skipped, out)
    doc = request_doc(batch, ok, when)
    _write_json(p, doc)
    out(f"{REQUEST_FILE}: {len(ok)} video(s) for the Editor to repair")
    return doc


def repair_after_judge(batch):
    """`(holds, why)` of the run plan's condition `repair_after_judge`: `06` is
    there, no repair round ran yet (no REQUEST_FILE), and a refused video is
    repairable."""
    batch = Path(batch)
    if _read(batch / JUDGE_FILE) is None:
        return False, f"no {JUDGE_FILE}: the frame judge has not run, nothing to repair"
    if round_ran(batch):
        return False, f"one repair pass only: {REQUEST_FILE} is already there"
    ok, skipped = candidates(batch)
    if not ok:
        return False, (f"no refused video is a block repair ({len(skipped)} refused: "
                       + "; ".join(s["why"] for s in skipped[:3])
                       + (" ..." if len(skipped) > 3 else "") + ")" if skipped else
                       "the frame judge refused no video")
    return True, f"{len(ok)} video(s) to repair: " + "; ".join(c["why"] for c in ok)


def _result_rows(doc):
    return {r["script_id"]: r for r in _rows(doc, "videos") if r.get("script_id")}


def normalise_result(req, res, why_missing):
    """The Editor's result over the request: one row per requested video, an
    unknown outcome or a missing row made `failed` with the sentence."""
    got = _result_rows(res) if isinstance(res, dict) and res.get("schema") == RESULT_SCHEMA else {}
    rows = []
    for v in _rows(req, "videos"):
        r = dict(got.get(v["script_id"]) or {})
        if not r:
            r = {"script_id": v["script_id"], "slug": v["slug"], "outcome": "failed",
                 "reason": why_missing}
        elif r.get("outcome") not in EDITOR_OUTCOMES:
            r.update(outcome="failed", reason=f"the Editor's outcome {r.get('outcome')!r} is "
                                              f"outside {list(EDITOR_OUTCOMES)}")
        r.setdefault("slug", v["slug"])
        r.setdefault("changed_blocks", [])
        rows.append(r)
    return {"schema": RESULT_SCHEMA, "task": TASK, "batch_id": (req or {}).get("batch_id"),
            "request_at": (req or {}).get("at"),
            "at": (res or {}).get("at") if isinstance(res, dict) else None, "videos": rows}


def run_editor(batch, editor_dir, python=None, timeout=EDITOR_TIMEOUT_S, out=print, runner=None):
    """Hand the request to the Video Editor (`<editor>/scripts/repair_blocks.py
    <batch> --request R --result S`) and leave a normalised RESULT_FILE.
    An Editor with no such entry point, a crash, a timeout or a result that
    leaves a video out - every one is `repair_failed` for that video, never a
    broken batch. With nothing rendered the outcome goes into `06` at once
    (there is nothing for the judge to look at). Returns the result doc.
    `runner(argv, timeout)` -> returncode stands in for the subprocess in the
    tests."""
    batch = Path(batch)
    req = _read(batch / REQUEST_FILE)
    if req is None or not _rows(req, "videos"):
        out(f"no video to repair ({REQUEST_FILE} {'empty' if req else 'not there'})")
        return None
    rp = batch / RESULT_FILE
    old = _read(rp)
    if old is not None and old.get("request_at") == req.get("at"):
        out(f"{RESULT_FILE} is already there - the Editor's one pass ran")
        return old
    if rp.exists():
        rp.unlink()                     # a result of an earlier request
    entry = Path(editor_dir) / EDITOR_ENTRY
    if not entry.is_file():
        res = normalise_result(req, None, (
            f"the Video Editor at {editor_dir} has no {EDITOR_ENTRY} (CF-0881's agent half "
            f"is not in) - nothing was re-picked"))
        for r in res["videos"]:
            r["outcome"] = "not_attempted"
    else:
        argv = [python or sys.executable, str(entry), str(batch),
                "--request", str(batch / REQUEST_FILE), "--result", str(rp)]
        try:
            code = (runner or _run)(argv, timeout)
        except Exception as e:                                  # noqa: BLE001
            code, err = None, f"{type(e).__name__}: {e}"
        else:
            err = f"exit {code}" if code else None
        raw = _read(rp)
        res = normalise_result(req, raw, (
            f"the Editor's repair left no result for this video"
            + (f" ({err})" if err else "")))
    _write_json(rp, res)
    for r in res["videos"]:
        out(f"  {r['slug']}: {r['outcome']}" + (f" - {r.get('reason')}" if r.get("reason") else ""))
    if not any(r["outcome"] == RENDERED for r in res["videos"]):
        out("nothing re-rendered - the refusals stand; recording the pass in 06")
        apply(batch, out=out)
    return res


def _run(argv, timeout):
    import subprocess  # noqa: PLC0415
    return subprocess.run(argv, timeout=timeout).returncode


def changed_entries(batch, res_row, req_row):
    """The pack entries the judge looks at again: every judged entry of the
    new pack on a block the request named or the Editor says changed."""
    blocks = {b["block"] for b in req_row.get("blocks") or []} | \
        {b for b in res_row.get("changed_blocks") or [] if isinstance(b, int)}
    man = _read(Path(batch) / "work" / res_row["slug"] / PACK_DIRNAME / MANIFEST) or {}
    return [e["id"] for e in _rows(man, "entries")
            if e.get("id") and e.get("judged") is True and block_of(e["id"], e) in blocks]


def pending(batch):
    """`[{script_id, slug, entries}]` - the re-rendered videos the judge owes
    verdicts on (mode `repair`) that `06 -> repairs[]` does not hold yet."""
    batch = Path(batch)
    req, res = _read(batch / REQUEST_FILE), _read(batch / RESULT_FILE)
    if not req or not res:
        return []
    done = repaired_ids(_read(batch / JUDGE_FILE) or {})
    by_req = {v["script_id"]: v for v in _rows(req, "videos")}
    return [{"script_id": r["script_id"], "slug": r["slug"],
             "entries": changed_entries(batch, r, by_req.get(r["script_id"]) or {})}
            for r in _rows(res, "videos")
            if r.get("outcome") == RENDERED and r["script_id"] not in done
            and r["script_id"] in by_req]


def repair_judge_pending(batch):
    """`(holds, why)` of the condition `repair_judge_pending`."""
    p = pending(batch)
    if not p:
        return False, "no re-rendered video waits for the judge"
    return True, "; ".join(f"{x['slug']}: {', '.join(x['entries']) or 'no entry'}" for x in p)


# --------------------------------------------------------------------------
# the gate's answer (task item 4): `frame_judge_gate.py --repair`

SPAN_TOLERANCE_S = 0.05
_CARRY_KEYS = ("entry", "tile", "verdict", "why", "mismatch", "footage_defect", "foreign_text")


def _channel_ids():
    """shared/channel_ids.py, beside this file: a 06 written before a channel
    was renamed carries the former id frozen in `channel` (CF-0197), so it is
    resolved where it is read."""
    p = str(HERE)
    if p not in sys.path:
        sys.path.append(p)
    import channel_ids  # noqa: PLC0415
    return channel_ids


def _gate():
    p = str(ROOT / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import frame_judge_gate  # noqa: PLC0415
    return frame_judge_gate


def _same_span(a, b):
    try:
        return (abs(float(a.get("start")) - float(b.get("start"))) <= SPAN_TOLERANCE_S
                and abs(float(a.get("end")) - float(b.get("end"))) <= SPAN_TOLERANCE_S)
    except (TypeError, ValueError):
        return False


def compose_verdicts(old_row, manifest, fresh, to_judge):
    """`(verdict rows for verdicts.json, carried entry ids)`: the judge's fresh
    rows (REPAIR_VERDICTS) for what it looked at, and the first pass's verdict
    for every other judged entry of the new pack whose span did not move. An
    entry neither answered nor carried stays unanswered - the gate then calls
    the judgement unfinished, which is what it is."""
    old = {r.get("entry"): r for r in _rows(old_row, "verdicts") if r.get("entry")}
    fresh_rows = {r.get("entry"): r for r in _rows(fresh, "verdicts") if r.get("entry")}
    rows, carried = [], []
    for e in _rows(manifest, "entries"):
        eid = e.get("id")
        if not eid or e.get("judged") is not True:
            continue
        if eid in fresh_rows:
            rows.append(fresh_rows.pop(eid))
        elif eid not in to_judge and eid in old and _same_span(old[eid], e):
            rows.append({k: old[eid].get(k) for k in _CARRY_KEYS})
            carried.append(eid)
    return rows + list(fresh_rows.values()), carried


EDITOR_DIR_ENV = "CF0881_EDITOR_DIR"


def _retired_shots(editor_dir=None):
    """The Video Editor's own registry module (agents/video-editor/scripts/
    retired_shots.py, stdlib only) - the one rule of what retires, called, not
    copied. None when that checkout has no such file."""
    import importlib.util  # noqa: PLC0415
    d = Path(editor_dir or os.environ.get(EDITOR_DIR_ENV) or ROOT / "agents" / "video-editor")
    path = d / "scripts" / "retired_shots.py"
    if not path.is_file():
        return None
    name = "_cf0881_retired_shots"
    mod = sys.modules.get(name)
    if mod is not None and Path(mod.__file__).resolve() == path.resolve():
        return mod
    sp = str(path.parent)
    added = sp not in sys.path
    if added:
        sys.path.insert(0, sp)              # its own siblings (rhythm, _clip_names, ...)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        if added and sp in sys.path:        # never shadow the root's own modules after
            sys.path.remove(sp)
    return mod


def resync_retired(batch, out=print, registry=None, editor_dir=None, acceptance_log=None):
    """CF-0881: after a `repaired` outcome the video goes to the user, so its
    shots retire now - not at the next 05 write. The Editor's `--repair` wrote
    the 05 row while 06 still said reject (its shots were held); this is the
    same sync `write_batch_metadata.py` runs on every 05 write
    (`retired_shots.sync_from_batch` over 05's `videos[]`, reading the 06 just
    written). Returns the sentence; never raises - a registry that cannot be
    written is said out loud and does not cost the batch its 06."""
    batch = Path(batch)
    try:
        rs = _retired_shots(editor_dir)
        if rs is None or not hasattr(rs, "sync_from_batch"):
            why = ("retired shots not re-synced: the Video Editor checkout has no "
                   "scripts/retired_shots.py sync_from_batch")
            out(why)
            return why
        ve = _read(batch / EDITOR_FILE) or {}
        synced = rs.sync_from_batch(batch, _rows(ve, "videos"), registry=registry,
                                    channel=_channel_ids().resolve_channel(ve.get("channel"), ROOT),
                                    acceptance_log=acceptance_log)
    except Exception as e:                                  # noqa: BLE001
        why = f"retired shots NOT re-synced (CF-0397): {type(e).__name__}: {e}"
        out(why)
        return why
    if synced is None:
        why = "retired shots: the batch is not under pipeline/<channel>/ - no registry to sync"
    else:
        reg, added, removed = synced
        why = (f"retired shots re-synced -> {reg} (+{len(added)} delivered, -{len(removed)} "
               f"dropped, {len(synced.held)} held)")
    out(why)
    return why


def _summary(row):
    return {k: (row or {}).get(k) for k in ("gate", "reason_code", "score_line")}


def apply(batch, ledger=None, foreign_mode=None, record_incomplete=False, out=print, when=None,
          retired_registry=None, editor_dir=None, acceptance_log=None):
    """Put the repair pass into `06-frame-judge.json`: per requested video one
    record in `repairs[]` (`repaired` / `repair_failed`); a re-rendered video
    judged ready replaces its row (the refused row is kept in the record), one
    that is not leaves the refusal as it was. Returns 0, or 1 when a judgement
    is unfinished and `record_incomplete` is off (nothing written)."""
    batch = Path(batch)
    req = _read(batch / REQUEST_FILE)
    if not req or not _rows(req, "videos"):
        out(f"no repair round in this batch ({REQUEST_FILE} {'empty' if req else 'not there'})")
        return 0
    p06 = batch / JUDGE_FILE
    d06 = _read(p06)
    if d06 is None:
        raise SystemExit(f"judge repair: no readable {JUDGE_FILE} in {batch}")
    res = normalise_result(req, _read(batch / RESULT_FILE),
                           f"no {RESULT_FILE}: the Editor's repair did not run")
    g = _gate()
    ve = _read(batch / EDITOR_FILE) or {}
    by_sid = {v.get("script_id"): v for v in _rows(ve, "videos")}
    core_mode = g.foreign_core_mode(
        _channel_ids().resolve_channel(d06.get("channel"), ROOT), foreign_mode)[0]
    rows = list(_rows(d06, "videos"))
    index = {r.get("script_id"): i for i, r in enumerate(rows)}
    req_by = {v["script_id"]: v for v in _rows(req, "videos")}
    done = repaired_ids(d06)
    records, unfinished = [], []
    for r in res["videos"]:
        sid = r["script_id"]
        if sid in done or sid not in index:
            continue
        old = rows[index[sid]]
        rq = req_by.get(sid) or {}
        rec = {"task": TASK, "at": when or _now_z(), "script_id": sid, "slug": r["slug"],
               "topic_id": rq.get("topic_id"), "blocks": rq.get("blocks") or [],
               "editor": {k: r.get(k) for k in ("outcome", "reason", "changed_blocks", "replaced")},
               "before": _summary(old), "after": None, "judged_entries": [],
               "carried_entries": []}
        if r["outcome"] != RENDERED:
            rec.update(outcome=REPAIR_FAILED,
                       reason=f"the Editor: {r['outcome']}" + (f" - {r['reason']}"
                                                              if r.get("reason") else ""))
            records.append(rec)
            continue
        pack_dir = batch / "work" / r["slug"] / PACK_DIRNAME
        man = _read(pack_dir / MANIFEST) or {}
        to_judge = changed_entries(batch, r, rq)
        fresh = _read(pack_dir / REPAIR_VERDICTS)
        rec["judged_entries"] = to_judge
        if fresh is None:
            if not record_incomplete:
                unfinished.append(f"{r['slug']}: no {REPAIR_VERDICTS} (owes {', '.join(to_judge)})")
                continue
            rec.update(outcome=REPAIR_FAILED,
                       reason=f"the judge left no {REPAIR_VERDICTS} for {', '.join(to_judge)}")
            records.append(rec)
            continue
        verdicts, carried = compose_verdicts(old, man, fresh, set(to_judge))
        rec["carried_entries"] = carried
        vp = pack_dir / "verdicts.json"
        if vp.exists() and not (pack_dir / "verdicts.before-repair.json").exists():
            os.replace(vp, pack_dir / "verdicts.before-repair.json")
        _write_json(vp, {"schema": g.funnel.FRAME_JUDGE_VERDICTS_SCHEMA, "slug": r["slug"],
                         "verdicts": verdicts,
                         "repair": {"task": TASK, "judged": to_judge, "carried": carried}})
        video = by_sid.get(sid)
        if video is None or not g.funnel.judge_candidate(video):
            rec.update(outcome=REPAIR_FAILED,
                       reason=f"{EDITOR_FILE} holds no deliverable row for {sid} after the repair")
            records.append(rec)
            continue
        new, why = g.judge_video(video, pack_dir, batch, ledger, core_mode)
        if new is None:
            rec.update(outcome=REPAIR_FAILED, reason=f"not judged: {why}")
        elif new["gate"] == GATE_PASS:
            rec.update(outcome=REPAIRED, reason=None, after=_summary(new), row_before=old)
            rows[index[sid]] = new
        elif new["gate"] == g.funnel.GATE_INCOMPLETE and not record_incomplete:
            unfinished.append(f"{r['slug']}: {new['reason']}")
            continue
        else:
            rec.update(outcome=REPAIR_FAILED, after=_summary(new),
                       reason=new.get("reason") or new["gate"])
        records.append(rec)
    if unfinished:
        out("judge repair: unfinished - " + "; ".join(unfinished)
            + f" - {JUDGE_FILE} not touched; write {REPAIR_VERDICTS} and run again "
              f"(or --record-incomplete)")
        return 1
    if not records:
        out(f"judge repair: nothing new to record - {JUDGE_FILE} not touched")
        return 0
    doc = dict(d06)
    doc["videos"] = rows
    counts = _merger().recount(doc)
    counts["wrong_person"] = sum(len((v.get("wrong_person") or {}).get("entries") or [])
                                 for v in rows)
    counts[REPAIRED] = sum(1 for x in _rows(d06, REPAIRS_KEY) + records
                           if x.get("outcome") == REPAIRED)
    counts[REPAIR_FAILED] = sum(1 for x in _rows(d06, REPAIRS_KEY) + records
                                if x.get("outcome") == REPAIR_FAILED)
    doc["counts"] = counts
    doc[REPAIRS_KEY] = _rows(d06, REPAIRS_KEY) + records
    _write_json(p06, doc)
    for x in records:
        out(f"  {x['slug']}: {x['outcome']}" + (f" - {x['reason']}" if x.get("reason") else "")
            + (f" ({x['after']['score_line']})" if x.get("after") else ""))
    n_ok = sum(1 for x in records if x["outcome"] == REPAIRED)
    out(f"{JUDGE_FILE}: {len(records)} repair record(s), {n_ok} repaired")
    if n_ok:
        resync_retired(batch, out=out, registry=retired_registry, editor_dir=editor_dir,
                       acceptance_log=acceptance_log)
    return 0


def _merger():
    p = str(ROOT / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import frame_judge_merge  # noqa: PLC0415
    return frame_judge_merge


# --------------------------------------------------------------------------
# CLI


def _print_candidates(ok, skipped, out=print):
    out(f"repair candidates: {len(ok)} repairable, {len(skipped)} not")
    for c in ok:
        out(f"  + {c['why']}")
    for s in skipped:
        out(f"  - {s['why']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="the refused videos a block repair can answer")
    c.add_argument("batch")
    c.add_argument("--json", action="store_true")
    for name, hlp in (("request", "write the round's request to the Editor (one pass)"),
                      ("pending", "the re-rendered videos and the entries the judge owes")):
        x = sub.add_parser(name, help=hlp)
        x.add_argument("batch")
    e = sub.add_parser("run-editor", help="hand the request to the Video Editor")
    e.add_argument("batch")
    e.add_argument("--editor-dir", required=True)
    e.add_argument("--python", default=None)
    e.add_argument("--timeout", type=int, default=EDITOR_TIMEOUT_S)
    m = sub.add_parser("measure", help="read-only retro count over finished batches")
    m.add_argument("batches", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "measure":
        measure(a.batches)
        return 0
    batch = Path(a.batch)
    if not batch.is_dir():
        print(f"judge_repair: no batch directory {batch}", file=sys.stderr)
        return 2
    if a.cmd == "request":
        request(batch)
        return 0
    if a.cmd == "run-editor":
        run_editor(batch, a.editor_dir, a.python, a.timeout)
        return 0
    if a.cmd == "pending":
        p = pending(batch)
        for x in p:
            print(f"{x['slug']}\t{' '.join(x['entries'])}")
        print(f"{len(p)} re-rendered video(s) for the judge (mode repair)")
        return 0
    if a.cmd == "candidates":
        ok, skipped = candidates(batch)
        if a.json:
            print(json.dumps({"repairable": ok, "skipped": skipped}, ensure_ascii=False, indent=2))
        else:
            _print_candidates(ok, skipped)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
