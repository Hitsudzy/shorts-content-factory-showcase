#!/usr/bin/env python3
"""CF-0358: a published video releases its sources from the footage pool.

The user's decision of 2026-09-23: "once the video is published its sources are
no longer needed" - the pool must not hold disk for finished topics. Conditions
agreed with him, and where each one lives below:

* **the moment is publication, not the render.** After a "no" the rebuild uses
  the same sources (`widows-bay`, 2026-09-23, was rebuilt twice out of three
  videos), so a rejected video keeps its topic alive (`STATUS_REJECTED`). A video
  the user took off for good is an end too (`everyday-sorcery-2`, 2026-09-23) -
  but only on his word, recorded here as a `withdrawn` row (`--record-withdrawal`);
  a rejection in `publish/acceptance-log.json` is never read as one.
* **a source another live topic needs goes only when both are finished.** A
  source is released when *every* topic that references it, in every batch and
  rebuild still on this disk, is finished; one reference from anything else
  keeps it, and the plan names that reference.
* **the published video does not suffer**: its full copy is in `publish/`.

Where "published" is written down (CF-0328, CF-0421, CF-0475)
--------------------------------------------------------------
1. `publish/uploads.json` (CF-0421, `agents/publisher/upload_records.py`) - the
   machine record: one row per upload, `entry_id` `<channel>/<batch>/<slug>`,
   `topic_id`, `publish_at` (UTC). A row whose `publish_at` has passed (or that
   has none) is a published video (`EVIDENCE_JOURNAL`). The Studio uploads
   before 2026-10-06 were carried into it by `agents/publisher/backfill_uploads.py`
   (CF-0586, `source: backfill`); `publish_at` there is ISO with its offset.
2. Also the table of `publish/README.md` - prose, but in the layout of
   CF-0475: a row whose first cell names `<channel>/<YYYY-MM-DD>/<slug>.mp4` (or
   its Archive archive path `...zip#<YYYY-MM-DD>/<slug>.mp4`), whose second cell names
   the batch, and which carries a `youtube.com/shorts/<id>` link, is a video that
   is on YouTube; it counts as published once its day (MSK) has come
   (`EVIDENCE_README`). The plan always says which of the two each topic rests on.
3. `publish/acceptance-log.json` (CF-0328) is *not* a publication: an acceptance
   is a verdict, the button is a human's (CF-0018). It is read only to tell a
   live topic (accepted and waiting, or rejected and waiting for a rebuild) from
   one that never reached the user.

What belongs to a source
------------------------
The pool is flat: `shared/footage/<video_id>.mp4` and its sidecars
`.shots.json`, `.contact.jpg`, `.fingerprint.json` - the same four
`agents/footage-indexer/scripts/fetch_footage.py:sidecars()` evicts together - and
the source's entry in `shared/footage/index.json`. A topic's sources are what
the footage stage of its batch recorded in `01b-footage-index.json`:
`sources_by_topic`, `fetched[]`, the `counted` sources of `pool_sources`
(CF-0325), and both ids of every dedup alias.

What protects a source
----------------------
* any reference from a topic that is not finished - accepted and not yet
  published, rejected and not withdrawn, or never shown to the user at all
  (`STATUS_NO_VIDEO`: the strict default; what to do with those is the user's
  question, see `variants()`);
* any open batch or working rebuild (`runlog.open_batches`): `--delete` refuses
  to run at all while one is open - the footage stage of a running batch writes
  the same `index.json`.

The journal of what was removed is `shared/footage/release-log.jsonl`
(append-only, one JSON object per line, next to the pool it describes and,
like it, outside git): a `released` row per source with every file and its size,
the topics and the evidence; a `withdrawn` row per video the user took off.

Nothing is deleted without `--delete`; the default is the plan (dry run).

Since 2026-10-04 (the user's decision) it runs inside the monthly archive
(`scripts/monthly_archive.py`, step "pool"), with the 14-day rule for topics that
never became a video (`STALE_DAYS`) and before old batches leave the disk - a
batch's `01b` is what names its sources.

CLI: `runlog pool-release [--root DIR] [--json] [--variants] [--stale-days N] [--delete]
[--record-withdrawal CHANNEL/BATCH/SLUG --answer TEXT] [--by WHO] [--via WHERE] [--dry-run]`.

CF-0720 (the command center's asks 8 and 11 of 2026-10-13): `delete(p, root,
by=, via=, dry_run=)` and `record_withdrawal(root, entry, answer, by=, via=,
dry_run=)` put `by` / `via` on their rows (checked by `_who`, only when
given - the rows of the old callers are unchanged) and have a dry run that
returns the same answer with nothing written; `check_answer(entry, answer)`
is the answer's rule alone (`{ok, entry_id, slug, why}`), no root needed.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

SIDECAR_SUFFIXES = (".mp4", ".shots.json", ".contact.jpg", ".fingerprint.json")
POOL_REL = Path("shared") / "footage"
INDEX_NAME = "index.json"
JOURNAL_NAME = "release-log.jsonl"


def _footage_ids():
    path = ROOT / "shared" / "footage_ids.py"
    spec = importlib.util.spec_from_file_location("footage_ids", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# CF-0665: a pool source is a YouTube video (11 characters) or an archive file
# the indexer fetched directly (`nasa-<id>` / `commons-<pageid>`); the rule is
# the root's one copy in shared/footage_ids.py. An id this does not match is
# never listed, so it is never released - which is what `{11}` did to every
# archive file.
VIDEO_ID_RE = _footage_ids().POOL_FILE_ID_RE
NOT_A_CHANNEL = ("backfill",)          # synthetic runs (CF-0111), never a topic

EVIDENCE_JOURNAL, EVIDENCE_README = "uploads.json", "README.md"

STATUS_PUBLISHED = "published"
STATUS_WITHDRAWN = "withdrawn"
STATUS_ACCEPTED = "accepted_not_published"
STATUS_REJECTED = "rejected_not_withdrawn"
STATUS_NO_VIDEO = "no_video"           # never reached the user's verdict
FINISHED = (STATUS_PUBLISHED, STATUS_WITHDRAWN)
# The user's rule of 2026-10-04 for topics that never became a video: a topic
# that did not reach the user (`no_video`) or was rejected and not withdrawn
# no longer protects its sources once *every* batch it appears in is older
# than this many days (`plan(stale_days=...)`, `--stale-days`; the monthly
# archive passes it, see scripts/monthly_archive.py). Accepted-and-waiting is
# never stale: that video is still going out.
STALE_DAYS = 14
STALE_STATUSES = (STATUS_NO_VIDEO, STATUS_REJECTED)

MSK = timezone(timedelta(hours=3))
SCRIPT_SUFFIX_RE = re.compile(r"-script\d+$")
README_PATH_RE = re.compile(
    r"(?:^|[/#])(?:(?P<chan>[a-z0-9-]+)/)?(?P<day>\d{4}-\d{2}-\d{2})/(?P<slug>[a-z0-9][a-z0-9-]*)\.mp4$")
README_LINK_RE = re.compile(r"youtube\.com/shorts/([\w-]+)")


def factory_root():
    env = os.environ.get("FACTORY_ROOT")
    return Path(env).expanduser().resolve() if env else ROOT


def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _utc(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# The batches on this disk: which topic references which source
# --------------------------------------------------------------------------

def batch_dirs(root):
    pipe = Path(root) / "pipeline"
    if not pipe.is_dir():
        return []
    return sorted(p for p in pipe.glob("*/*")
                  if p.is_dir() and p.parent.name not in NOT_A_CHANNEL)


def batch_key(bdir):
    return f"{bdir.parent.name}/{bdir.name}"


def topic_sources(idx):
    """{topic_id: set(video_id)} out of one `01b-footage-index.json`."""
    out = {}

    def add(topic, vid):
        if topic and vid:
            out.setdefault(topic, set()).add(vid)

    for topic, vids in (idx.get("sources_by_topic") or {}).items():
        for v in vids or ():
            add(topic, v)
    for row in idx.get("fetched") or ():
        add(row.get("topic_id"), row.get("video_id"))
    for row in idx.get("aliases") or ():
        add(row.get("topic_id"), row.get("video_id"))
        add(row.get("topic_id"), row.get("alias_of"))
    pool = (idx.get("pool_sources") or {}).get("topics") or {}
    for topic, rec in pool.items():
        for s in (rec or {}).get("sources") or ():
            if s.get("outcome") == "counted":
                add(topic, s.get("video_id"))
    return out


def topic_candidates(idx):
    """{topic_id: set(video_id)} the footage stage looked at for a topic and did
    not take: `failed[]` (fetched, then refused - sieve, duration, metadata),
    the not-counted `pool_sources`, and the candidates of `skipped_topics[]`.
    Not a source of the topic's video - the п.3 question, never released by
    the default rule."""
    out = {}

    def add(topic, vid):
        if topic and isinstance(vid, str) and VIDEO_ID_RE.match(vid):
            out.setdefault(topic, set()).add(vid)

    for row in idx.get("failed") or ():
        add(row.get("topic_id"), row.get("video_id"))
    pool = (idx.get("pool_sources") or {}).get("topics") or {}
    for topic, rec in pool.items():
        for s in (rec or {}).get("sources") or ():
            if s.get("outcome") != "counted":
                add(topic, s.get("video_id"))
    for row in idx.get("skipped_topics") or ():
        t = row.get("topic_id")
        for key in ("candidates", "tried"):
            for v in row.get(key) or ():
                add(t, v if isinstance(v, str) else (v or {}).get("video_id"))
        for v in row.get("sieved") or ():
            add(t, (v or {}).get("video_id"))
    return out


def references(root, kind="sources"):
    """{video_id: {(batch_key, topic_id), ...}} over every batch and rebuild:
    `sources` - what a topic took (the release rule); `candidates` - what it
    looked at and refused; `untopiced` - `fetched[]` rows with no topic at all
    (the legacy-film batches before 2026-09-09), topic None."""
    refs = {}
    for bdir in batch_dirs(root):
        idx = _load(bdir / "01b-footage-index.json")
        if not isinstance(idx, dict):
            continue
        if kind == "untopiced":
            for row in idx.get("fetched") or ():
                if row.get("video_id") and not row.get("topic_id"):
                    refs.setdefault(row["video_id"], set()).add((batch_key(bdir), None))
            continue
        pick = topic_sources if kind == "sources" else topic_candidates
        for topic, vids in pick(idx).items():
            for v in vids:
                refs.setdefault(v, set()).add((batch_key(bdir), topic))
    return refs


def slug_topics(bdir):
    """{slug: topic_id} of the videos one batch rendered (05-video-editor.json)."""
    out = {}
    doc = _load(bdir / "05-video-editor.json") or {}
    for v in doc.get("videos") or ():
        name = Path(v.get("output_path") or "").name
        sid = v.get("script_id") or ""
        if name.endswith(".mp4") and sid:
            out[name[:-4]] = v.get("topic_id") or SCRIPT_SUFFIX_RE.sub("", sid)
    return out


def script_topics(bdir):
    doc = _load(bdir / "03-content-researcher.json") or {}
    return {s.get("topic_id") for s in doc.get("scripts") or () if s.get("topic_id")}


class Resolver:
    """`<channel>/<batch>/<slug>` -> topic_id. The batch's own render record
    first; a rebuild that kept no 05-video-editor.json (2026-09-23T1053Z) is
    resolved through the slug's topic in any other batch, narrowed to the
    topics this rebuild's scripts carry."""

    def __init__(self, root):
        self.root = Path(root)
        self._slugs = {}
        self._all = None

    def _batch(self, chan, batch):
        return self.root / "pipeline" / chan / batch

    def topic(self, entry_id, topic_id=None):
        if topic_id:
            return topic_id
        parts = (entry_id or "").split("/")
        if len(parts) != 3:
            return None
        chan, batch, slug = parts
        bdir = self._batch(chan, batch)
        if bdir not in self._slugs:
            self._slugs[bdir] = slug_topics(bdir)
        hit = self._slugs[bdir].get(slug)
        if hit:
            return hit
        if not bdir.is_dir():
            return None
        if self._all is None:
            self._all = {}
            for b in batch_dirs(self.root):
                for s, t in slug_topics(b).items():
                    self._all.setdefault(s, set()).add(t)
        cands = self._all.get(slug, set()) & script_topics(bdir)
        return next(iter(cands)) if len(cands) == 1 else None


# --------------------------------------------------------------------------
# The facts: published, withdrawn, accepted, rejected
# --------------------------------------------------------------------------

def journal_path(root):
    return Path(root) / POOL_REL / JOURNAL_NAME


def read_journal(root):
    p = journal_path(root)
    rows = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def append_journal(root, row):
    p = journal_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def published_from_uploads(root, now):
    """[(entry_id, topic_id, at)] of `publish/uploads.json` rows whose
    publication time has come."""
    doc = _load(Path(root) / "publish" / "uploads.json") or {}
    out = []
    for row in doc.get("uploads") or ():
        if isinstance(row, dict) and row.get("withdrawn"):
            continue        # CF-0918: taken back into the копилка - on the channel, not published
        at = _utc(row.get("publish_at")) or _utc(row.get("uploaded_at"))
        if row.get("publish_at") and at and at > now:
            continue
        out.append((row.get("entry_id"), row.get("topic_id"), row.get("publish_at") or row.get("uploaded_at")))
    return out


def published_from_readme(root, now):
    """[(entry_id, day)] of the rows of `publish/README.md` that name a day
    folder, a batch and a YouTube link, and whose day (MSK) has come."""
    p = Path(root) / "publish" / "README.md"
    if not p.is_file():
        return []
    today = now.astimezone(MSK).date().isoformat()
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or not README_LINK_RE.search(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        first = re.findall(r"`([^`]+)`", cells[0])
        batch = re.findall(r"`([^`]+)`", cells[1])
        if not first or not batch:
            continue
        m = README_PATH_RE.search(first[0])
        if not m or m.group("day") > today:
            continue
        b = batch[0].strip("/")
        if b.count("/") != 1:
            continue
        out.append((f"{b}/{m.group('slug')}", m.group("day")))
    return out


def acceptance_rows(root, default_root):
    if Path(root) == Path(default_root):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import acceptance                                   # noqa: E402
            path = acceptance.default_log()
        except Exception:                                       # noqa: BLE001
            path = Path(root) / "publish" / "acceptance-log.json"
    else:
        path = Path(root) / "publish" / "acceptance-log.json"
    doc = _load(path) or {}
    return doc.get("acceptances") or []


def topic_status(root, now=None, extra_withdrawn=(), default_root=None):
    """{topic_id: {"status", "evidence": [...]}} for every topic the records
    name. A topic absent from the result never reached the user (no_video)."""
    now = now or datetime.now(timezone.utc)
    res = Resolver(root)
    out = {}

    def mark(topic, status, evidence):
        if not topic:
            return
        rec = out.setdefault(topic, {"status": None, "evidence": []})
        rec["evidence"].append(evidence)
        rank = (STATUS_PUBLISHED, STATUS_WITHDRAWN, STATUS_ACCEPTED, STATUS_REJECTED)
        if rec["status"] is None or rank.index(status) < rank.index(rec["status"]):
            rec["status"] = status

    unresolved = []
    for entry, tid, at in published_from_uploads(root, now):
        t = res.topic(entry, tid)
        (mark(t, STATUS_PUBLISHED, f"{EVIDENCE_JOURNAL}: {entry} ({at})") if t
         else unresolved.append((EVIDENCE_JOURNAL, entry)))
    for entry, day in published_from_readme(root, now):
        t = res.topic(entry)
        (mark(t, STATUS_PUBLISHED, f"{EVIDENCE_README}: {entry} ({day})") if t
         else unresolved.append((EVIDENCE_README, entry)))
    withdrawn = [(r.get("entry_id"), r.get("topic_id"), r.get("answer"))
                 for r in read_journal(root) if r.get("event") == "withdrawn"]
    withdrawn += [(e, None, "--withdrawn (plan only, not recorded)") for e in extra_withdrawn]
    for entry, tid, answer in withdrawn:
        t = res.topic(entry, tid)
        (mark(t, STATUS_WITHDRAWN, f"withdrawn: {entry} ({answer})") if t
         else unresolved.append(("withdrawn", entry)))
    for row in acceptance_rows(root, default_root or factory_root()):
        entry = row.get("entry_id")
        t = res.topic(entry, row.get("topic_id"))
        if not t:
            continue
        st = STATUS_ACCEPTED if row.get("verdict") == "accepted" else STATUS_REJECTED
        mark(t, st, f"acceptance-log: {entry} {row.get('verdict')} ({row.get('answered_at')})")
    return out, unresolved


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------

def pool_sources(root):
    """{video_id: [(name, bytes)]} of the media and sidecars in the pool."""
    pool = Path(root) / POOL_REL
    out = {}
    if not pool.is_dir():
        return out
    for f in pool.iterdir():
        if not f.is_file():
            continue
        for suf in SIDECAR_SUFFIXES:
            if f.name.endswith(suf):
                vid = f.name[: -len(suf)]
                if VIDEO_ID_RE.match(vid):
                    out.setdefault(vid, []).append((f.name, f.stat().st_size))
                break
    return out


def open_batch_keys(root):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runlog                                               # noqa: E402
    return {batch_key(Path(d)) for d, _last, _fresh in runlog.open_batches(root=root)}


def batch_time(bkey):
    m = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z$", bkey)
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00+00:00")


def stale(status, batches, now, stale_days):
    """True when the user's 14-day rule lets a topic go: it never became a
    published video (`no_video`, or rejected and not withdrawn) and every batch
    it appears in is older than `stale_days`."""
    if not stale_days or status not in STALE_STATUSES:
        return False
    cut = now - timedelta(days=stale_days)
    times = [batch_time(b) for b in batches]
    return bool(times) and all(t is not None and t < cut for t in times)


def plan(root=None, now=None, extra_withdrawn=(), open_keys=None, stale_days=None):
    root = Path(root) if root else factory_root()
    now = now or datetime.now(timezone.utc)
    status, unresolved = topic_status(root, now, extra_withdrawn, default_root=factory_root())
    refs = references(root)
    cand = references(root, "candidates")
    untop = references(root, "untopiced")
    files = pool_sources(root)
    if open_keys is None:
        open_keys = open_batch_keys(root)
    release, keep, orphan = [], [], []
    for vid in sorted(files):
        size = sum(b for _n, b in files[vid])
        entry = {"video_id": vid, "files": [n for n, _b in sorted(files[vid])], "bytes": size}
        rs = sorted(refs.get(vid, ()))
        if not rs:
            cands = sorted(cand.get(vid, ()))
            entry["candidate_of"] = {t: {"batches": sorted(b for b, tt in cands if tt == t),
                                         "status": (status.get(t) or {}).get("status") or STATUS_NO_VIDEO}
                                     for t in sorted({t for _b, t in cands})}
            entry["untopiced_in"] = sorted(b for b, _t in untop.get(vid, ()))
            mentions = [b for b, _t in cands] + entry["untopiced_in"]
            entry["newest_batch"] = max(mentions) if mentions else None
            entry["kind"] = ("refused_candidate" if cands else
                             "untopiced" if entry["untopiced_in"] else "unmentioned")
            orphan.append(entry)
            continue
        topics = {}
        for bkey, topic in rs:
            topics.setdefault(topic, []).append(bkey)
        entry["topics"] = {t: {"batches": sorted(b),
                               "status": (status.get(t) or {}).get("status") or STATUS_NO_VIDEO,
                               "evidence": (status.get(t) or {}).get("evidence", [])}
                           for t, b in sorted(topics.items())}
        entry["newest_batch"] = max(b for b, _t in rs)
        for v in entry["topics"].values():
            if stale(v["status"], v["batches"], now, stale_days):
                v["stale"] = True
                v["evidence"] = v["evidence"] + [
                    f"stale: {v['status']}, every batch older than {stale_days} d"]
        open_hit = sorted({b for b, _t in rs} & set(open_keys))
        blockers = sorted({v["status"] for v in entry["topics"].values()
                           if v["status"] not in FINISHED and not v.get("stale")})
        if open_hit:
            blockers = ["open_batch"] + blockers
            entry["open_batches"] = open_hit
        entry["blocked_by"] = blockers
        (keep if blockers else release).append(entry)
    return {"root": str(root), "at": now.isoformat(timespec="seconds"),
            "stale_days": stale_days,
            "open_batches": sorted(open_keys), "release": release, "keep": keep,
            "orphan": orphan, "unresolved": unresolved,
            "pool": {"sources": len(files), "bytes": sum(e["bytes"] for e in release + keep + orphan)}}


def variants(p, now=None, days=(7, 14, 30)):
    """The user's question of п.3, as numbers: which further sources a rule for
    topics that never reached a video would free. Nothing here deletes - a
    variant becomes a rule only by his word."""
    now = now or datetime.fromisoformat(p["at"])
    out = []
    for n in days:
        cut = now - timedelta(days=n)
        for label, dead in (("no_video", {STATUS_NO_VIDEO}),
                            ("no_video+rejected", {STATUS_NO_VIDEO, STATUS_REJECTED})):
            hit = [e for e in p["keep"]
                   if "open_batch" not in e["blocked_by"]
                   and all(v["status"] in FINISHED or
                           (v["status"] in dead and all((batch_time(b) or now) < cut for b in v["batches"]))
                           for v in e["topics"].values())]
            out.append({"rule": f"{label} older than {n} d", "sources": len(hit),
                        "bytes": sum(e["bytes"] for e in hit)})
    orph = p["orphan"]

    def row(rule, hit):
        out.append({"rule": rule, "sources": len(hit), "bytes": sum(e["bytes"] for e in hit)})

    row("orphan: refused candidate of finished topics only",
        [e for e in orph if e["kind"] == "refused_candidate"
         and all(v["status"] in FINISHED for v in e["candidate_of"].values())])
    for n in days:
        cut = now - timedelta(days=n)
        row(f"orphan: refused candidate, last batch older than {n} d",
            [e for e in orph if e["kind"] == "refused_candidate"
             and (batch_time(e["newest_batch"]) or now) < cut])
    row("orphan: untopiced (early batches, fetched[] without a topic)",
        [e for e in orph if e["kind"] == "untopiced"])
    row("orphan: no batch on disk mentions it", [e for e in orph if e["kind"] == "unmentioned"])
    row("orphan: all", orph)
    return out


def gb(n):
    return f"{n / 1024 ** 3:.2f} GB"


def render(p, show_variants=False):
    lines = [f"pool-release plan (CF-0358) at {p['at']}, root {p['root']}",
             f"pool: {p['pool']['sources']} sources, {gb(p['pool']['bytes'])}",
             f"open batches: {', '.join(p['open_batches']) or 'none'}"]
    if p.get("stale_days"):
        lines.append(f"stale rule: a no_video / rejected-not-withdrawn topic whose every batch is "
                     f"older than {p['stale_days']} d is finished too")
    for name, rows in (("release (every topic published or withdrawn)", p["release"]),
                       ("keep (a live or undecided topic references it)", p["keep"]),
                       ("orphan (no batch on this disk references it)", p["orphan"])):
        lines.append(f"{name}: {len(rows)} sources, {gb(sum(e['bytes'] for e in rows))}")
    kinds = {}
    for e in p["orphan"]:
        k = kinds.setdefault(e["kind"], [0, 0])
        k[0] += 1
        k[1] += e["bytes"]
    if kinds:
        lines.append("orphan by kind: " + ", ".join(f"{k} {n} ({gb(b)})" for k, (n, b) in sorted(kinds.items())))
    for e in p["release"]:
        ev = "; ".join(sorted({x for v in e["topics"].values() for x in v["evidence"]
                               if x.startswith((EVIDENCE_JOURNAL, EVIDENCE_README, "withdrawn",
                                                "stale"))}))
        lines.append(f"  RELEASE {e['video_id']} {gb(e['bytes'])} topics {','.join(e['topics'])} - {ev}")
    counts = {}
    for e in p["keep"]:
        for b in e["blocked_by"]:
            counts[b] = counts.get(b, 0) + 1
    if counts:
        lines.append("kept because: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for kind, entry in p["unresolved"]:
        lines.append(f"  UNRESOLVED {kind}: {entry} - its batch is not on this disk or names no such video")
    if show_variants:
        lines.append("variants for topics that never reached a video (the user's question, not a rule):")
        for v in variants(p):
            lines.append(f"  {v['rule']}: +{v['sources']} sources, +{gb(v['bytes'])}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The deletion - only with --delete
# --------------------------------------------------------------------------

WHO_MAX = 40                # CF-0720: `by` / `via` (the shape of notify._who, CF-0700)


def _who(value, what):
    """CF-0720: `by` / `via` - None (not given) or a short non-empty
    single-line string; anything else is a ValueError and nothing is written."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                         f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise ValueError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def _stamp(row, by, via):
    """`by` / `via` on a journal row - only when given (the rows of a caller
    that names no one stay as they were)."""
    if by is not None:
        row["by"] = by
    if via is not None:
        row["via"] = via
    return row


def released_row(e, removed, now, by=None, via=None):
    """The `released` journal row of one source (`delete` writes it, the dry
    run returns it)."""
    return _stamp({"event": "released", "video_id": e["video_id"], "removed": removed,
                   "bytes": sum(r["bytes"] for r in removed),
                   "topics": {t: {"status": v["status"], "evidence": v["evidence"],
                                  "stale": bool(v.get("stale"))}
                              for t, v in e["topics"].items()},
                   "at": now.isoformat(timespec="seconds"), "task": "CF-0358"}, by, via)


def delete(p, root=None, now=None, by=None, via=None, dry_run=False, rows=None):
    """Remove every `release` source: its files, then its index entry; one
    journal row per source, written after its files are gone. Refused while a
    batch is open. Returns the video ids gone.

    CF-0720: `by` / `via` (checked by `_who` before anything is touched) go
    on every `released` row. `dry_run=True` is the same run with nothing
    removed and nothing written: the same refusal, the same ids returned.
    `rows` (a list) gets the journal rows - written, or on a dry run the rows
    that would be written (`removed` lists the files there now with their
    sizes)."""
    by, via = _who(by, "by"), _who(via, "via")
    root = Path(root) if root else Path(p["root"])
    if p["open_batches"]:
        raise RuntimeError("open batch(es) " + ", ".join(p["open_batches"]) +
                           ": the footage stage writes the same pool - nothing deleted")
    pool = root / POOL_REL
    now = now or datetime.now(timezone.utc)
    gone = []
    for e in p["release"]:
        removed = []
        for name in e["files"]:
            f = pool / name
            if f.is_file():
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                removed.append({"file": name, "bytes": size})
        row = released_row(e, removed, now, by, via)
        if not dry_run:
            append_journal(root, row)
        if rows is not None:
            rows.append(row)
        gone.append(e["video_id"])
    if dry_run:
        return gone
    idx_path = pool / INDEX_NAME
    idx = _load(idx_path)
    if gone and isinstance(idx, dict) and isinstance(idx.get("entries"), list):
        drop = set(gone)
        idx["entries"] = [x for x in idx["entries"] if x.get("id") not in drop]
        tmp = idx_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(idx, indent=2), encoding="utf-8")
        os.replace(tmp, idx_path)
    return gone


def check_answer(entry_id, answer):
    """CF-0720: the factory's rule for a withdrawal's answer, without a root
    and without writing: `{ok, entry_id, slug, why}` - `ok` when `entry_id`
    is CHANNEL/BATCH/SLUG and the answer names the slug (`why` None), else
    `why` says what is wrong (the very text `record_withdrawal` raises)."""
    parts = (entry_id or "").split("/") if isinstance(entry_id, str) else []
    if len(parts) != 3 or not all(parts):
        return {"ok": False, "entry_id": entry_id, "slug": None,
                "why": f"{entry_id!r}: expected CHANNEL/BATCH/SLUG"}
    slug = parts[2]
    if not isinstance(answer, str) or not answer or slug.lower() not in answer.lower():
        return {"ok": False, "entry_id": entry_id, "slug": slug,
                "why": f"the answer does not name {slug!r} - a withdrawal is filed only "
                       "under the video the user named"}
    return {"ok": True, "entry_id": entry_id, "slug": slug, "why": None}


def record_withdrawal(root, entry_id, answer, now=None, by=None, via=None, dry_run=False):
    """The user's word that a video is off for good. Like an acceptance
    (CF-0328), the answer must name the video (`check_answer`).

    CF-0720: `by` / `via` (checked by `_who`) go on the row when given;
    `dry_run=True` returns the very row and appends nothing."""
    by, via = _who(by, "by"), _who(via, "via")
    got = check_answer(entry_id, answer)
    if not got["ok"]:
        raise ValueError(got["why"])
    topic = Resolver(root).topic(entry_id)
    row = _stamp({"event": "withdrawn", "entry_id": entry_id, "topic_id": topic,
                  "answer": answer,
                  "at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                  "task": "CF-0358"}, by, via)
    if not dry_run:
        append_journal(root, row)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runlog pool-release", description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="factory root (default: $FACTORY_ROOT or this checkout)")
    ap.add_argument("--json", action="store_true", help="the plan as JSON")
    ap.add_argument("--variants", action="store_true",
                    help="also count what rules for topics that never reached a video would free")
    ap.add_argument("--withdrawn", action="append", default=[], metavar="CHANNEL/BATCH/SLUG",
                    help="plan as if this video were withdrawn (not recorded)")
    ap.add_argument("--delete", action="store_true", help="delete the `release` sources (default: plan only)")
    ap.add_argument("--stale-days", type=int, default=None, metavar="N",
                    help="the user's rule of 2026-10-04: a no_video or rejected-not-withdrawn "
                         f"topic whose every batch is older than N days is finished too "
                         f"(the monthly archive passes {STALE_DAYS})")
    ap.add_argument("--record-withdrawal", metavar="CHANNEL/BATCH/SLUG")
    ap.add_argument("--answer", help="the user's answer naming the video (with --record-withdrawal)")
    ap.add_argument("--by", help="CF-0720: who asked (e.g. user) - on the journal rows")
    ap.add_argument("--via", help="CF-0720: from where (e.g. center, cli) - on the journal rows")
    ap.add_argument("--dry-run", action="store_true",
                    help="CF-0720: with --record-withdrawal or --delete - the rows that would "
                         "be written, nothing written or removed")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve() if a.root else factory_root()
    if a.record_withdrawal:
        try:
            row = record_withdrawal(root, a.record_withdrawal, a.answer, by=a.by, via=a.via,
                                    dry_run=a.dry_run)
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        print(json.dumps(row, ensure_ascii=False))
        return 0
    if a.delete and a.withdrawn:
        print("refused: --withdrawn is a what-if; record the user's word with --record-withdrawal",
              file=sys.stderr)
        return 2
    try:
        _who(a.by, "by"), _who(a.via, "via")
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    p = plan(root, extra_withdrawn=a.withdrawn, stale_days=a.stale_days)
    if a.json:
        out = dict(p)
        if a.variants:
            out["variants"] = variants(p)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(p, a.variants))
    if a.delete:
        try:
            gone = delete(p, root, by=a.by, via=a.via, dry_run=a.dry_run)
        except RuntimeError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 3
        if a.dry_run:
            print(f"dry run: would delete {len(gone)} sources; nothing removed, nothing written")
        else:
            print(f"deleted {len(gone)} sources; journal {journal_path(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
