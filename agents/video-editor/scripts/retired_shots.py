#!/usr/bin/env python3
"""CF-0397: a shot that reached a ready video is retired - for the channel,
across batches.

What was missing
----------------
DoD item 6 (CF-0026, CF-0121's `rhythm.ShotLedger`) forbids one sample twice
*inside* one video. Nothing forbade it across videos: 133 sources and 8.7 GB
in `shared/footage/`, and one good shot of a source could reach every video
the channel ever made. This module is the channel's memory of what it already
showed.

The rule
--------
* **A shot retires when the video it is in goes to the user** - the moment
  `write_batch_metadata.py` puts that video into `videos[]` of the batch's
  `05-video-editor.json` *and* the video is one the user will be shown
  (CF-0443): the frame judge takes it (`qc.passed` with no `needs_you`, or a
  `judge_admitted_despite`, CF-0416 - the root's `funnel.judge_candidate`),
  its score is not under N (`score.passed` is not false, CF-0434) and the
  judge, once its `06-frame-judge.json` is there, did not `reject` it. Since
  CF-0434 every video is in `videos[]` with its score, so "in videos[]" alone
  retired the shots of a QC-failed, NEEDS-YOU or tier-F video too
  (`harbourlights`, 0705Z). Not at acceptance or publication: the verdict comes
  days later and the next batch is resolved before it, so a shot would go into
  a second video while the first still waits, and both would reach the
  channel. A video the batch later drops (CF-0270 `supersedes_video`) gives
  its shots back - the registry is synced to `videos[]`, not appended to.
* **What the user sends back returns** (CF-0443). Every write of the registry
  reads `publish/acceptance-log.json` (CF-0328): a video the user rejected
  moves from `videos{}` to `returned{}` (`returned_at`, `returned_by`,
  `reason`) and its shots are on offer again; a video the user accepted stays
  retired - and retires even when the rule above held it (the user saw it and
  took it, it will be on the channel). With no verdict, a frame-judge
  `reject` of an earlier batch returns its shots the same way. A verdict that
  changes moves the entry back.
* **The source never retires.** A retired `MLwTyQOhBkw:53` leaves every other
  shot of `MLwTyQOhBkw` on offer; a per-source cap would choke the pool.
* **A video never refuses its own shots.** A re-render of the same video
  (another attempt, `--exclude-candidate`) resolves against the registry minus
  its own entry (`<channel>/<batch>/<slug>`); a `pipeline/rebuilds/<ts>`
  rebuild of it minus its own entry and the entry of the video it rebuilds
  (`rebuild_of` of its 05, else the batch its copied 03/01 name, CF-0416): a
  rebuild replaces the video, it does not add a second one. Only those - not
  every entry of the same slug (CF-0532): a later batch's video on the same
  work (`delver` 1313Z, then `delver` 1825Z) is a second video, and with the
  slug exempt it got the first one's footage back, "literally the same
  footage, new text on top".
* A block the rule leaves without a shot falls down the resolver's existing
  ladder (topic rung, emergency repeat, unfilled block) - it is one more gate
  refusal, recorded in `rejected_candidates` with its own reason.

Shot identity
-------------
`<video_id>:<shot>` - the name the storyboard and the render plan already give
every picture (`block["shot"]`), `video_id` being the stem of the source in
`shared/footage/`. CF-0080's aliases (the same material re-uploaded under
another id, `footage-aliases.json`) are not merged here.

Where it lives
--------------
`pipeline/<channel>/retired-shots.json`, beside the channel's batches and not
inside any of them: `scripts/archive_old_batches.sh` moves timestamp-named
batch folders off the disk and leaves this file where it is. One entry per
ready video (`<channel>/<batch>/<slug>`, the acceptance log's `entry_id`) with
the shots it shows; the retired set is their union.

CLI
---
  retired_shots.py backfill <channel_dir> [--also pipeline/rebuilds]
      rebuild from the ready videos on disk (idempotent)
  retired_shots.py cost <channel_dir> [--last 5] [--also pipeline/rebuilds]
      what the rule would have cost (CF-0320)
"""
import argparse
import contextlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import _clip_names  # CF-0665
import rhythm
from _channel_ids import batch_dir as channel_batch_dir  # CF-0443
from _channel_ids import channel_batch_dirs, resolve_channel  # CF-0197

REGISTRY_NAME = "retired-shots.json"
VIDEO_EDITOR_RECORD = "05-video-editor.json"
SHOT_NAME = re.compile(r"^[^:\s]+:\d+$")
# CF-0665: a cut clip's file name - `<prefix>_<source id>_sNNN.<ext>`; the id
# itself is read by _clip_names (a YouTube id or an archive `nasa-`/`commons-`).
ASSET_FILE = re.compile(r"([^/\\]+)\.[A-Za-z0-9]+$")
BATCH_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}Z$")
NOTE = ("CF-0397. A shot (<video_id>:<shot>, as plan.json names it) of a video that "
        "went to the user - in videos[] of a batch's 05-video-editor.json, taken by "
        "the frame judge, score not under N, not rejected by the judge (CF-0443) - is "
        "retired for this channel: resolve_anchors.py refuses it for every other "
        "video. Written by write_batch_metadata.py, synced to the batch's videos[] "
        "on every call (a video the batch drops gives its shots back); the source "
        "itself never retires. `returned` holds the videos whose shots came back: "
        "rejected by the user in publish/acceptance-log.json, or by the frame judge "
        "with no verdict (CF-0443); an accepted video stays retired. Rebuild with "
        "`retired_shots.py backfill`.")


class RegistryError(ValueError):
    """The registry exists and cannot be read - refuse rather than forget."""


def registry_path(channel_dir):
    return Path(channel_dir) / REGISTRY_NAME


def locate(batch_dir, channel=None):
    """(registry path, channel, batch key) for a batch at `pipeline/<group>/<batch>`,
    else None - a batch parked anywhere else (a test's temp dir) has no
    channel memory to read or write.

    The group is the channel for an ordinary batch. A rebuild
    (`pipeline/rebuilds/<ts>`) names its channel in 05-video-editor.json /
    `--channel`; its videos then retire into that channel's registry under the
    batch key `rebuilds/<ts>`."""
    batch_dir = Path(batch_dir).resolve()
    group = batch_dir.parent
    if group.parent.name != "pipeline":
        return None
    # CF-0197: a batch written before a rename (`pipeline/legacy-film/`,
    # or a 05 record whose `channel` is the former id) retires into the
    # channel's current registry, never into one for a name that is gone.
    channel = resolve_channel(channel or group.name)
    key = batch_dir.name if group.name == channel else f"{group.name}/{batch_dir.name}"
    return registry_path(group.parent / channel), channel, key


def entry_id(channel, batch_id, slug):
    return f"{channel}/{batch_id}/{slug}"


REBUILD_FIELD = "rebuild_of"
REBUILD_SOURCE_RECORDS = ("03-content-researcher.json", "01-trend-hunter.json")


def _read_json(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def rebuild_source(batch_dir):
    """CF-0532: (channel or None, [batch key, ...]) of the batch a rebuild at
    `pipeline/rebuilds/<ts>` was copied from - its 05's `rebuild_of`
    (CF-0416) when the Editor already wrote one, else the `channel`/`batch_id`
    of the copied 03/01 (the resolver runs before the 05 exists). The keys are
    the source's registry batch keys: `<ts>`, and `<former dir>/<ts>` when
    `rebuild_of.path` names a directory under a former channel id (CF-0197).
    None for a batch that is not a rebuild or names no source."""
    batch_dir = Path(batch_dir).resolve()
    if batch_dir.parent.name != REBUILDS_GROUP:
        return None
    rec = _read_json(batch_dir / VIDEO_EDITOR_RECORD) or {}
    src = rec.get(REBUILD_FIELD)
    if isinstance(src, dict) and src.get("batch_id"):
        channel = resolve_channel(str(src.get("channel") or rec.get("channel") or ""))
        ts = str(src["batch_id"])
        keys = [ts]
        parts = str(src.get("path") or "").strip("/").split("/")
        if len(parts) >= 2 and parts[-1] == ts and channel and parts[-2] != channel:
            keys.append(f"{parts[-2]}/{ts}")
        return channel or None, keys
    for name in REBUILD_SOURCE_RECORDS:
        doc = _read_json(batch_dir / name)
        if doc and doc.get("batch_id"):
            channel = resolve_channel(str(doc.get("channel") or ""))
            return channel or None, [str(doc["batch_id"])]
    return None


def empty(channel=None):
    return {"note": NOTE, "task": "CF-0397", "channel": channel, "videos": {}}


def load(path):
    path = Path(path)
    if not path.exists():
        return empty()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"{path}: {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("videos"), dict):
        raise RegistryError(f"{path}: not a retired-shots registry (no videos{{}})")
    return doc


def write_atomic(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------
# What a video shows
# --------------------------------------------------------------------------

def _named(shot):
    return isinstance(shot, str) and bool(SHOT_NAME.match(shot))


def block_shots(block):
    """Every shot a plan (or storyboard) block puts on screen.

    The block's own `shot`, a sequence's cuts (`rhythm.block_shots`), a swing
    chain's `swing_block_shots`, and both halves of a `side_by_side` opening -
    on the storyboard (`split[]`) and on the plan (`asset.sides[]`). Never a
    nested `shot` of a record *about* the block (`candidate_supply.nearest` is
    an offer that was not shown)."""
    out = [block.get("shot")] + list(rhythm.block_shots(block) or []) + \
        list(block.get("swing_block_shots") or [])
    asset = block.get("asset") if isinstance(block.get("asset"), dict) else {}
    for half in list(block.get("split") or []) + list(asset.get("sides") or []):
        if not isinstance(half, dict):
            continue
        out.append(half.get("shot"))
        out.extend(c.get("shot") for c in half.get("cuts") or [] if isinstance(c, dict))
    named = [s for s in dict.fromkeys(out) if _named(s)]
    if named:
        return named
    # A plan from before blocks carried `shot` (legacy-film, August):
    # the clip's own file name says which shot it was cut from.
    key = asset_shot(asset.get("src") or block.get("asset"))
    return [key] if key else []


def asset_shot(value):
    """`<source id>:<shot>` named by a cut clip's path (`.../a00_<id>_s009.mp4`
    -> `<id>:9`), or None - the fallback for a block that carries no `shot`."""
    m = ASSET_FILE.search(str(value or ""))
    hit = _clip_names.clip_shot(m.group(1), min_digits=3) if m else None
    return f"{hit[0]}:{int(hit[1])}" if hit else None


def plan_shots(plan):
    """Every shot of a plan, in first-shown order, each once."""
    out = []
    for b in (plan or {}).get("blocks") or []:
        out.extend(block_shots(b))
    return list(dict.fromkeys(out))


def read_plan_shots(plan_path):
    """plan_shots() of a plan file, or None when there is no readable plan."""
    try:
        return plan_shots(json.loads(Path(plan_path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def record_shots(record):
    """The shots of a videos[] record read off its `assets[].src` clip names
    (`..._<video_id>_s053.mp4`) - for a batch whose work/ is gone, so there is
    no plan to read. None when no asset names a shot."""
    out = []
    for a in record.get("assets") or []:
        key = asset_shot((a or {}).get("src"))
        if key:
            out.append(key)
    return list(dict.fromkeys(out)) or None


def video_slug(record):
    """The work/<slug>/ of a videos[] record - its mp4's stem."""
    out = record.get("output_path")
    return Path(out).stem if out else None


# --------------------------------------------------------------------------
# Who goes to the user (CF-0443)
# --------------------------------------------------------------------------

JUDGE_RECORD = "06-frame-judge.json"
JUDGE_ADMITTED_KEY = "judge_admitted_despite"
FUNNEL_REL = Path("shared") / "runlog" / "funnel.py"
ACCEPTANCE_LOG_REL = Path("publish") / "acceptance-log.json"
ACCEPTED, REJECTED = "accepted", "rejected"
REBUILDS_GROUP = "rebuilds"
BY_ACCEPTANCE, BY_JUDGE = "acceptance", "frame_judge"


def _local_judge_candidate(v):
    """shared/runlog/funnel.py's judge_candidate(), for a checkout of this repo
    without the root. Kept equal to the root's by
    tests/test_retired_shots.py::test_local_judge_candidate_matches_the_root."""
    v = v or {}
    clean = (v.get("qc") or {}).get("passed") is True and not v.get("needs_you")
    admitted = v.get(JUDGE_ADMITTED_KEY)
    admitted = [r for r in admitted if isinstance(r, str) and r.strip()] \
        if isinstance(admitted, list) else []
    return clean or bool(admitted)


def _root_file(rel):
    """<root>/<rel> - FACTORY_ROOT when it holds the file, else the nearest
    ancestor of this checkout that does (a worktree finds the real root), or
    None. The same walk as _runlog / _score."""
    env = os.environ.get("FACTORY_ROOT")
    if env and (Path(env).expanduser() / rel).is_file():
        return Path(env).expanduser().resolve() / rel
    for p in Path(__file__).resolve().parents:
        if (p / rel).is_file():
            return p / rel
    return None


_FUNNEL = []


def root_judge_candidate():
    """The root's funnel.judge_candidate, or None when it cannot be loaded."""
    if not _FUNNEL:
        fn = None
        path = _root_file(FUNNEL_REL)
        if path is not None:
            try:
                spec = importlib.util.spec_from_file_location("_cf0443_funnel", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                fn = getattr(mod, "judge_candidate", None)
            except Exception:  # a broken root must not lose the registry
                fn = None
        _FUNNEL.append(fn)
    return _FUNNEL[0]


def judge_candidate(v):
    """A video the frame judge takes: the root's rule (one rule for the judge,
    the funnel and this registry), the local copy when the root is away."""
    fn = root_judge_candidate()
    return bool((fn or _local_judge_candidate)(v))


def judge_gates(batch_dir):
    """{slug: (gate, reason_code)} of the batch's 06-frame-judge.json, {} when
    the judge has not run (or its record does not parse)."""
    try:
        doc = json.loads((Path(batch_dir) / JUDGE_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for v in (doc or {}).get("videos") or []:
        if isinstance(v, dict) and v.get("slug"):
            out[v["slug"]] = (v.get("gate"), v.get("reason_code"))
    return out


def not_delivered(record, gates=None):
    """None when this videos[] record goes to the user for review; else why not.

    It goes when the frame judge takes it (QC passed with no NEEDS-YOU, or a
    `judge_admitted_despite`, CF-0416), its score is not under N (CF-0434:
    `score.passed` false is tier F - a video stopped earlier is in refusals[]
    and never here) and the judge, when it has run (`gates`, the batch's 06),
    did not reject it. A record with no score (built before CF-0434) is not
    held on the score."""
    if not judge_candidate(record):
        if record.get("needs_you"):
            return f"needs_you: {str(record['needs_you'])[:120]}"
        return "qc failed (qc.passed is not true, no judge_admitted_despite)"
    sc = record.get("score")
    if isinstance(sc, dict) and sc.get("passed") is False:
        return (f"score {sc.get('score')} under N {sc.get('threshold')} "
                f"(tier {sc.get('tier')})")
    gate = (gates or {}).get(video_slug(record))
    if gate and gate[0] == "reject":
        return f"frame judge rejected ({gate[1] or 'no code'})"
    return None


ACCEPTANCE_LOG_ENV = "ACCEPTANCE_LOG"


def default_acceptance_log():
    """`$ACCEPTANCE_LOG` when it is set (CF-0523: the file itself - a test
    names a temp path, a missing file reads as no verdicts; FACTORY_ROOT cannot
    be moved for that, it is also the inserts root), else
    <root>/publish/acceptance-log.json: FACTORY_ROOT's when it is set (a test
    root without a log reads as no verdicts), else the checkout's root."""
    log = os.environ.get(ACCEPTANCE_LOG_ENV)
    if log:
        return Path(log).expanduser()
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve() / ACCEPTANCE_LOG_REL
    for p in Path(__file__).resolve().parents:
        if (p / "shared" / "runlog").is_dir():
            return p / ACCEPTANCE_LOG_REL
    return None


def acceptance_verdicts(path):
    """{key: row} of the user's standing verdicts (publish/acceptance-log.json,
    CF-0328). Every row answers to its stored `entry_id` and to
    `<channel today>/<batch_id>/<slug>`. {} when there is no log; a log that
    does not parse raises RegistryError - a return decided on a log nobody
    could read is not decided."""
    if path is None or not Path(path).exists():
        return {}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"{path}: the acceptance log does not parse ({e})")
    rows = doc.get("acceptances") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise RegistryError(f"{path}: no `acceptances` list")
    out = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("verdict") not in (ACCEPTED, REJECTED):
            continue
        keys = [str(r.get("entry_id") or "")]
        if r.get("channel") and r.get("batch_id") and r.get("slug"):
            keys.append(f"{resolve_channel(r['channel'])}/{r['batch_id']}/{r['slug']}")
        for k in keys:
            if k:
                out.setdefault(k, r)
    return out


def _split_eid(eid):
    """(channel, batch key, slug) of a registry entry id."""
    channel, rest = str(eid).split("/", 1)
    key, slug = rest.rsplit("/", 1)
    return channel, key, slug


def acceptance_keys(eid):
    """The acceptance-log keys a registry entry answers to. A rebuild is
    `example-film/rebuilds/<ts>/<slug>` here and `rebuilds/<ts>/<slug>` in the
    log; a batch under a former channel directory (CF-0197) is
    `<channel>/<group>/<ts>/<slug>` here and `<channel>/<ts>/<slug>` there."""
    channel, key, slug = _split_eid(eid)
    out = [eid]
    if "/" in key:
        group, ts = key.split("/", 1)
        out += [f"{group}/{ts}/{slug}"] if group == REBUILDS_GROUP else \
            [f"{channel}/{ts}/{slug}", f"{group}/{ts}/{slug}"]
    return out


def verdict_of(eid, verdicts):
    for k in acceptance_keys(eid):
        if k in verdicts:
            return verdicts[k]
    return None


def _batch_dir_of(eid, pipeline_dir):
    if pipeline_dir is None:
        return None
    channel, key, _ = _split_eid(eid)
    if "/" in key:
        return Path(pipeline_dir) / key
    return channel_batch_dir(channel, key, pipeline_dir=pipeline_dir) or \
        Path(pipeline_dir) / channel / key


# --------------------------------------------------------------------------
# Writing: one batch's delivered videos, and what came back
# --------------------------------------------------------------------------

class Synced(tuple):
    """(path, added, removed), with `held` ({slug: reason} of this batch's
    videos whose shots did not retire) and `returned` (entry ids that moved to
    `returned{}` on this write)."""
    held = {}
    returned = []


def _return_reason(eid, verdicts, gates_of):
    """(by, reason) when this entry's shots go back to the pool, else None.
    The user's verdict wins: rejected returns them, accepted keeps them
    retired even over a judge's reject; with no verdict a frame-judge reject
    returns them."""
    row = verdict_of(eid, verdicts)
    if row is not None:
        if row.get("verdict") == REJECTED:
            why = row.get("reason_code") or row.get("reason") or "no reason"
            when = f" {row['answered_at']}" if row.get("answered_at") else ""
            return BY_ACCEPTANCE, f"rejected by the user{when} ({why})"
        return None
    gate = gates_of(eid)
    if gate and gate[0] == "reject":
        return BY_JUDGE, f"frame judge rejected ({gate[1] or 'no code'})"
    return None


def sync_batch(path, channel, batch_id, ready, now=None, held=None,
               acceptance_log=None, pipeline_dir=None):
    """Make the registry's entries for this batch exactly the videos that went
    to the user, then give back what the user (or the judge) sent back.

    `ready` is {slug: [shot, ...] or None} of the videos that went to the user
    (not_delivered() is None); None keeps whatever the registry already says
    for that video (its plan is not on disk any more). `held` is {slug:
    (shots, reason)} of the batch's other videos: their shots do not retire -
    unless the user accepted the video anyway, which puts it on the channel.
    Entries of this batch in neither are the videos the batch dropped and are
    removed. Other batches are untouched by that step.

    Then, over the whole registry (CF-0443): an entry whose video the user
    rejected (the acceptance log) - or, with no verdict, the frame judge
    rejected (its batch's 06) - moves from `videos{}` to `returned{}` with the
    reason, and its shots are on offer again; one no longer rejected moves
    back. Writes only on a change. Returns (added, removed) entry ids of this
    batch in `videos{}`; the ids returned on this write are `sync_batch.last`."""
    held = held or {}
    doc = load(path)
    original = json.loads(json.dumps(doc))
    doc["note"] = NOTE
    doc["channel"] = resolve_channel(doc.get("channel") or channel)
    videos = doc["videos"]
    returned = doc.get("returned") if isinstance(doc.get("returned"), dict) else {}
    verdicts = acceptance_verdicts(acceptance_log)
    prefix = entry_id(channel, batch_id, "")
    before = {k: v for k, v in videos.items() if k.startswith(prefix)}
    before_ret = {k: v for k, v in returned.items() if k.startswith(prefix)}
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    wanted = dict(ready)
    for slug, (shots, _why) in held.items():
        row = verdict_of(entry_id(channel, batch_id, slug), verdicts)
        if row is not None and row.get("verdict") == ACCEPTED:
            wanted[slug] = shots
    after = {}
    for slug, shots in wanted.items():
        eid = entry_id(channel, batch_id, slug)
        old = before.get(eid) or before_ret.get(eid)
        if shots is None:
            if old is not None:
                after[eid] = {"shots": old.get("shots") or [],
                              "retired_at": old.get("retired_at") or stamp}
            continue
        shots = list(dict.fromkeys(shots))
        if old is not None and old.get("shots") == shots:
            after[eid] = {"shots": shots, "retired_at": old.get("retired_at") or stamp}
        else:
            after[eid] = {"shots": shots, "retired_at": stamp}
    for k in list(before) + list(before_ret):
        videos.pop(k, None)
        returned.pop(k, None)
    # this batch's entries start retired; the pass below decides what returns
    videos.update(after)

    gates_cache = {}

    def gates_of(eid):
        bdir = _batch_dir_of(eid, pipeline_dir)
        if bdir is None:
            return None
        if bdir not in gates_cache:
            gates_cache[bdir] = judge_gates(bdir)
        return gates_cache[bdir].get(_split_eid(eid)[2])

    newly = []
    for eid in list(videos) + list(returned):
        rec = videos.get(eid) or returned.get(eid)
        why = _return_reason(eid, verdicts, gates_of)
        if why is None:
            if eid in returned:
                returned.pop(eid)
                videos[eid] = {"shots": rec.get("shots") or [], "retired_at": stamp}
            continue
        by, reason = why
        old = returned.get(eid) or before_ret.get(eid)
        if old is not None and old.get("returned_by") == by and old.get("reason") == reason:
            returned[eid] = dict(old, shots=rec.get("shots") or [])
        else:
            returned[eid] = {"shots": rec.get("shots") or [],
                             "retired_at": rec.get("retired_at"),
                             "returned_at": stamp, "returned_by": by, "reason": reason}
            if eid not in (original.get("returned") or {}):
                newly.append(eid)
        videos.pop(eid, None)

    doc["videos"] = dict(sorted(videos.items()))
    doc["returned"] = dict(sorted(returned.items()))
    batch_after = {k for k in doc["videos"] if k.startswith(prefix)}
    added = sorted(batch_after - set(before))
    removed = sorted(set(before) - batch_after)
    sync_batch.last = sorted(newly)
    if doc == original and path is not None and Path(path).exists():
        return added, removed
    write_atomic(path, doc)
    return added, removed


sync_batch.last = []


def batch_split(batch_dir, videos, plans=None):
    """({slug: shots} of the batch's videos that went to the user,
    {slug: (shots, reason)} of the rest). `plans` maps a script_id to the plan
    path the caller rendered from; the rest are read from the conventional
    <batch>/work/<slug>/plan.json. The judge's verdicts are read off the
    batch's 06-frame-judge.json when it is there."""
    plans = plans or {}
    gates = judge_gates(batch_dir)
    ready, held = {}, {}
    for v in videos:
        slug = video_slug(v)
        if not slug:
            continue
        plan = plans.get(v.get("script_id")) or Path(batch_dir) / "work" / slug / "plan.json"
        # A plan that names no shot at all (unreadable, or every block
        # typographic) falls back to the record's asset names.
        shots = read_plan_shots(plan) or record_shots(v)
        why = not_delivered(v, gates)
        if why is None:
            ready[slug] = shots
        else:
            held[slug] = (shots, why)
    return ready, held


def batch_ready(batch_dir, videos, plans=None):
    """{slug: shots} of the batch's videos that went to the user."""
    return batch_split(batch_dir, videos, plans)[0]


def _pipeline_of(registry):
    reg = Path(registry).resolve()
    return reg.parent.parent if reg.parent.parent.name == "pipeline" else None


def sync_from_batch(batch_dir, videos, plans=None, registry=None, channel=None,
                    batch_id=None, acceptance_log=None):
    """write_batch_metadata.py's hook. Returns Synced (path, added, removed)
    with `.held` / `.returned`, or None when the batch is not under
    pipeline/<channel>/ and no registry was named."""
    batch_dir = Path(batch_dir)
    found = locate(batch_dir, channel)
    if registry is None:
        if found is None:
            return None
        registry = found[0]
    channel = found[1] if found else resolve_channel(channel or batch_dir.resolve().parent.name)
    batch_id = batch_id or (found[2] if found else batch_dir.name)
    ready, held = batch_split(batch_dir, videos, plans)
    if acceptance_log is None:
        acceptance_log = default_acceptance_log()
    added, removed = sync_batch(registry, channel, batch_id, ready, held=held,
                                acceptance_log=acceptance_log,
                                pipeline_dir=_pipeline_of(registry))
    out = Synced((Path(registry), added, removed))
    out.held = {slug: why for slug, (_, why) in held.items()}
    out.returned = list(sync_batch.last)
    return out


# --------------------------------------------------------------------------
# Reading: the resolver's view
# --------------------------------------------------------------------------

def slug_of(eid):
    return str(eid).rsplit("/", 1)[-1]


class Retired:
    """The shots this video may not take, and why. `exempt` is the video's own
    entry id and `also_exempt` the entries a rebuild replaces (the video it
    rebuilds): those, and only those, refuse nothing - a re-render or a
    rebuild never refuses the pictures the video already had, while another
    video on the same slug in another batch does (CF-0532)."""

    def __init__(self, doc=None, exempt=None, path=None, also_exempt=()):
        self.path = str(path) if path else None
        self.exempt = exempt
        self.also_exempt = [e for e in dict.fromkeys(also_exempt or ()) if e and e != exempt]
        own = {e for e in [exempt, *self.also_exempt] if e}
        self._by = {}
        for eid, rec in ((doc or {}).get("videos") or {}).items():
            if eid in own:
                continue
            for s in rec.get("shots") or []:
                self._by.setdefault(s, []).append(eid)

    @classmethod
    def for_output(cls, output, registry=None, channel=None):
        """The registry a storyboard at <batch>/work/<slug>/<file> resolves
        against, with that video exempt - and, for a rebuild
        (`pipeline/rebuilds/<ts>`), the video it rebuilds; a rebuild with no
        `channel` given takes its channel off its own records (rebuild_source)
        rather than the directory name `rebuilds`. Empty outside
        pipeline/<group>/ unless `registry` names one."""
        out = Path(output).resolve()
        found, exempt, also = None, None, []
        if out.parent.parent.name == "work":
            bdir, slug = out.parent.parent.parent, out.parent.name
            src = rebuild_source(bdir)
            if src and channel is None:
                channel = src[0]
            found = locate(bdir, channel)
            if found:
                exempt = entry_id(found[1], found[2], slug)
                if src:
                    also = [entry_id(found[1], k, slug) for k in src[1]]
        if registry is None:
            if found is None:
                return cls(exempt=exempt, also_exempt=also)
            registry = found[0]
        return cls(load(registry), exempt=exempt, path=registry, also_exempt=also)

    def __len__(self):
        return len(self._by)

    def by(self, name):
        return list(self._by.get(name, ()))

    def reason(self, name):
        """The refusal line for a retired shot, or None when it is on offer."""
        who = self._by.get(name)
        if not who:
            return None
        more = f" (+{len(who) - 1} more)" if len(who) > 1 else ""
        return (f"retired - already in ready video {who[0]}{more}; a shot is shown "
                f"once per channel, its source stays on offer (CF-0397)")


def shot_name(key):
    """ShotLedger's (source path, shot number) -> `<video_id>:<shot>`."""
    source, shot = key
    return f"{Path(str(source)).stem}:{shot}"


# --------------------------------------------------------------------------
# Backfill and the CF-0320 price
# --------------------------------------------------------------------------

def _batches(channel_dir, also=()):
    """(batch key, batch dir) of the channel's own batches - under every name
    it has had (CF-0197: `pipeline/legacy-film/` is example-film's too) -
    and of the batches under `also` (e.g. pipeline/rebuilds) whose
    05-video-editor.json names this channel; oldest first by timestamp."""
    channel_dir = Path(channel_dir)
    channel = resolve_channel(channel_dir.name)
    found = []
    for d in channel_batch_dirs(channel, pipeline_dir=channel_dir.parent) or [channel_dir]:
        prefix = "" if d.name == channel else f"{d.name}/"
        found += [(f"{prefix}{p.name}", p) for p in Path(d).iterdir()
                  if p.is_dir() and BATCH_NAME.match(p.name)]
    for extra in also or ():
        extra = Path(extra)
        for p in extra.iterdir():
            rec = p / VIDEO_EDITOR_RECORD
            if not (p.is_dir() and BATCH_NAME.match(p.name) and rec.exists()):
                continue
            try:
                ch = resolve_channel(
                    json.loads(rec.read_text(encoding="utf-8")).get("channel"))
            except (OSError, ValueError):
                continue
            if ch == channel:
                found.append((f"{extra.name}/{p.name}", p))
    return sorted(found, key=lambda kp: (kp[1].name, kp[0]))


def batch_videos(channel_dir, also=()):
    """[(batch key, ready, held)] of every batch on disk with a readable
    05-video-editor.json, oldest first - `ready`/`held` as batch_split() gives
    them, inside a batch in the order the stage wrote them (merge_log)."""
    out = []
    for key, batch in _batches(channel_dir, also):
        rec = batch / VIDEO_EDITOR_RECORD
        if not rec.exists():
            continue
        try:
            doc = json.loads(rec.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"RETIRED: skipped unreadable {rec}", file=sys.stderr)
            continue
        order = {}
        for i, m in enumerate(doc.get("merge_log") or []):
            for sid in m.get("videos") or []:
                order.setdefault(sid, i)
        vids = doc.get("videos") or []
        vids = sorted(vids, key=lambda v: (order.get(v.get("script_id"), 1 << 30),
                                           v.get("script_id") or ""))
        ready, held = batch_split(batch, vids)
        out.append((key, ready, held))
    return out


def ready_videos(channel_dir, also=()):
    """[(batch key, slug, shots or None)] of every video on disk that went to
    the user (CF-0443), oldest batch first."""
    return [(key, slug, shots) for key, ready, _ in batch_videos(channel_dir, also)
            for slug, shots in ready.items()]


def backfill(channel_dir, registry=None, also=(), acceptance_log=None):
    """Sync every batch on disk into the registry - the delivered videos, the
    held ones the user accepted anyway, and the returns of the acceptance log
    and the judges' 06. Idempotent: a second run changes nothing. Returns
    {batch_id: (added, removed)}."""
    channel_dir = Path(channel_dir)
    channel = resolve_channel(channel_dir.name)
    registry = registry or registry_path(channel_dir.parent / channel)
    if acceptance_log is None:
        acceptance_log = default_acceptance_log()
    pipeline_dir = _pipeline_of(registry) or channel_dir.parent
    return {b: sync_batch(registry, channel, b, ready, held=held,
                          acceptance_log=acceptance_log, pipeline_dir=pipeline_dir)
            for b, ready, held in batch_videos(channel_dir, also)}


def _plan_blocks(channel_dir, batch_key, slug, also):
    channel = resolve_channel(Path(channel_dir).name)
    bases = [Path(channel_dir).parent / channel, Path(channel_dir).parent] + \
        [Path(a).parent for a in also or ()]
    for base in bases:
        plan = base / batch_key / "work" / slug / "plan.json"
        if plan.exists():
            try:
                return json.loads(plan.read_text(encoding="utf-8")).get("blocks") or []
            except (OSError, ValueError):
                return None
    return None


def _own_entries(channel, channel_dir, batch_key, slug, also):
    """The entries a video at `batch_key`/`slug` never refuses (CF-0532): its
    own, and for a rebuild the video it rebuilds."""
    own = {entry_id(channel, batch_key, slug)}
    head, _, ts = str(batch_key).rpartition("/")
    if head == REBUILDS_GROUP:
        for base in [Path(a).parent for a in also or ()] + [Path(channel_dir).parent]:
            src = rebuild_source(base / batch_key)
            if src:
                own.update(entry_id(channel, k, slug) for k in src[1])
                break
    return own


def cost(channel_dir, last=5, also=()):
    """What the rule would have cost the last `last` batches that have a ready
    video: every block shot that an earlier ready video had already shown.

    Walks every ready video on disk oldest first (so the history before the
    window counts) and reports only the window. Returns a dict."""
    seen = {}
    videos = ready_videos(channel_dir, also)
    batches = list(dict.fromkeys(b for b, _, _ in videos))
    window = set(batches[-last:])
    report = {"batches": sorted(window), "ready_videos": 0, "affected_videos": [],
              "blocks_lost": 0, "blocks": 0, "unreadable_plans": []}
    channel = resolve_channel(Path(channel_dir).name)
    for batch_id, slug, shots in videos:
        eid = entry_id(channel, batch_id, slug)
        own = _own_entries(channel, channel_dir, batch_id, slug, also)
        if batch_id in window:
            report["ready_videos"] += 1
            if shots is None:
                report["unreadable_plans"].append(eid)
        blocks = _plan_blocks(channel_dir, batch_id, slug, also)
        if blocks is None:
            # No plan any more: one pseudo-block per shot the record names.
            blocks = [{"shot": s} for s in shots or []]
        if batch_id in window:
            lost = []
            for i, b in enumerate(blocks):
                hit = [s for s in block_shots(b)
                       if any(e not in own for e in seen.get(s, ()))]
                if block_shots(b):
                    report["blocks"] += 1
                if hit:
                    lost.append({"block": i, "shots": hit,
                                 "first_in": [next(e for e in seen[s]
                                                   if e not in own)
                                              for s in hit]})
            if lost:
                report["affected_videos"].append({"video": eid, "blocks": lost})
                report["blocks_lost"] += len(lost)
        for s in shots or []:
            seen.setdefault(s, []).append(eid)
    return report


def cli(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("channel_dir")
    b.add_argument("--registry", default=None)
    b.add_argument("--also", action="append", default=[],
                   help="another pipeline group (pipeline/rebuilds) whose batches "
                        "name this channel in 05-video-editor.json")
    b.add_argument("--acceptance-log", default=None,
                   help="the user's verdicts (default $ACCEPTANCE_LOG, else <root>/publish/acceptance-log.json)")
    c = sub.add_parser("cost")
    c.add_argument("channel_dir")
    c.add_argument("--last", type=int, default=5)
    c.add_argument("--also", action="append", default=[])
    args = p.parse_args(argv)
    if args.cmd == "backfill":
        res = backfill(args.channel_dir, args.registry, args.also, args.acceptance_log)
        reg = args.registry or registry_path(
            Path(args.channel_dir).parent / resolve_channel(Path(args.channel_dir).name))
        doc = load(reg)
        shots = {s for v in doc["videos"].values() for s in v.get("shots") or []}
        for batch_id, (added, removed) in res.items():
            if added or removed:
                print(f"{batch_id}: +{len(added)} -{len(removed)}")
        print(f"registry {reg}: {len(doc['videos'])} delivered video(s), "
              f"{len(shots)} retired shot(s), "
              f"{len(doc.get('returned') or {})} returned video(s)")
        return 0
    print(json.dumps(cost(args.channel_dir, args.last, args.also), indent=2,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
