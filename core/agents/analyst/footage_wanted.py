#!/usr/bin/env python3
"""CF-0023: what the written scripts asked for and the footage did not give -
across every batch of a channel, one list of footage to get next.

    python3 agents/analyst/footage_wanted.py collect [--channel C] [--since YYYY-MM-DD]
        [--archive DIR] [--root DIR] [--out DIR] [--print] [--no-write]

Writes `analytics/<channel>/footage-wanted.md` (people) and `.json` (machine)
per channel - both rewritten whole. `--out DIR` writes `<DIR>/<channel>/...`
instead (a trial run that must not touch `analytics/`).

**What counts as an unmet need** - only what a stage of a batch wrote down
(nothing is guessed from a video):

    code                    stage        record
    anchor_no_picture       editor       05 videos[].unresolved_anchors: every candidate failed a gate
    anchor_short            editor       05 videos[].unresolved_anchors: candidates cover only part of the block
    frame_contradicts       frame-judge  06 videos[].verdicts: the narration names a picture that is not on screen
    frame_foreign           frame-judge  06 videos[].verdicts: the block is filled with footage of something else
    visual_claim_uncovered  scripts      03 warnings[]: a line points at a picture no usable shot answers
    pool_too_thin           scripts      03 warnings[] / 03 skipped[] / 05 refusals[]: the pool cannot carry the script
    no_second_source        scripts      same three places: every block resolves from one source
    event_footage_short     scripts      03 warnings[]: too few samples of the event's own footage (CF-0575)
    no_source               hunter       01 skipped_topics[]: the topic got no footage at all

`03` warnings are the pool's state after the thin-pool supplement step
(`docs/pipeline.md`, CF-0345), so a need that step filled is not counted. The
step's outcome for the topic (`wall_ceiling`, `nothing_to_try`, `sources`) and
the request it laid (`work/supplement-requests/[consumed/]<topic>.json`) are
read beside it: the request's `entities` say what was searched, its
`candidates` are uploads the hunter already found.

**One row per thing to get.** A topic-level need (the pool as a whole) is the
topic's work (`title_ref`, or a person topic's person; the event's `scene`
entity for `event_footage_short`). An anchor-level need (one picture) is a
person when the anchor names one (the coverage gate's `supplement.anchors[]
.entities`), else a scene of the topic's work. Names are compared casefolded,
accents and punctuation dropped; the same name from many batches is one row
with counters: `topics` (distinct topic ids - a rebuild of the same topic is
not a second one), `batches`, `misses` (single records). Rows go most topics
first, then most recent, then name.

**Where to get it - only what the factory already knows**: candidates of the
supplement requests (video id, title, channel, official or not), and the
official channels of the channel's own `channels/<id>/footage-origin.json`
(CF-0561/CF-0631, read through `shared/channel_data.footage_origin`; a former
id resolves) whose pattern or owner is in the work's `network` /
`rights_holder`. Nothing else is suggested. A channel without that file, or
with a file that does not parse, gets a note saying so - never a silent empty
list and never another channel's list.
**In the pool now**: `shared/footage/index.json` (read only) entries whose
title or note carries the name as a run of words, and candidates whose id is
there.

**Packed batches.** A batch older than 30 days lives in one zip per channel
and month on Archive (`scripts/monthly_archive.py`:
`<volume>/shorts-content-factory-pipeline/<group>/<YYYY-MM>.zip`, members
`<batch>/<path>`). They are read in place, member by member, never unpacked to
disk; a folder that is not there (Archive not mounted, nothing packed yet) is one
line in the list (`archive: ... is not there`), not an error. A batch both on disk and in a zip is read once
(the disk copy).

Exit codes: 0 - written (or printed); 2 - unknown channel / unreadable root.
"""
import argparse
import importlib.util
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent


def _by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


channel_data = _by_path("channel_data_footage_wanted", ROOT / "shared" / "channel_data.py")

TASK = "CF-0023"
OUT_NAME = "footage-wanted"
# scripts/monthly_archive.py: DEFAULT_VOLUME / BATCH_ARCHIVE_DIR (pinned by the tests)
DEFAULT_ARCHIVE = "/Volumes/Archive/shorts-content-factory-pipeline"
REBUILDS = "rebuilds"
NOT_A_CHANNEL = ("backfill", "rebuilds")       # shared/runlog/gate_price.NOT_CHANNELS
BATCH_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T\d{4}Z$")

KINDS = ("work", "person", "event", "scene")
KIND_TITLES = {"work": "Работы", "person": "Персоны", "event": "События", "scene": "Сцены"}
REASONS = {
    "anchor_no_picture": "монтаж: ни один кадр пула не прошёл порог для якоря",
    "anchor_short": "монтаж: кадров якоря хватило не на весь блок",
    "frame_contradicts": "судья кадров: диктор называет то, чего нет в кадре",
    "frame_foreign": "судья кадров: блок закрыт чужим кадром",
    "visual_claim_uncovered": "сценарий: строка указывает на кадр, которого нет в пуле",
    "pool_too_thin": "пул тоньше сценария",
    "no_second_source": "все блоки из одного источника",
    "event_footage_short": "мало кадров самого события",
    "no_source": "у темы не нашлось футажа",
}
TOPIC_CODES = ("pool_too_thin", "no_second_source", "event_footage_short")
HUNTER_CODES = ("no_source",)
NEEDED_JSON = ("01-trend-hunter.json", "03-content-researcher.json", "05-video-editor.json",
               "06-frame-judge.json", "work/supplement-step.json")
REQUESTS = "work/supplement-requests/"
MAX_EXAMPLES = 3
MAX_WHERE = 5


class WantedError(Exception):
    pass


# --------------------------------------------------------------------- names
def norm(name):
    """Casefolded, accents and punctuation dropped, spaces collapsed."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    s = re.sub(r"[^\w]+", " ", s.replace("_", " "))
    return " ".join(s.split())


def has_run(haystack, name):
    """`name` (normalized) is a whole run of words inside `haystack`."""
    n = norm(name)
    return bool(n) and f" {n} " in f" {norm(haystack)} "


def batch_date(name):
    m = BATCH_RE.match(name)
    return m.group(1) if m else None


# ------------------------------------------------------------------- batches
class Batch:
    """One batch's records, from a folder or from members of a zip."""

    def __init__(self, name, group, files, packed=None):
        self.name, self.group, self.packed = name, group, packed
        self.date = batch_date(name)
        self._files = files                     # rel path -> callable returning bytes

    def json(self, rel):
        f = self._files.get(rel)
        if f is None:
            return None
        try:
            return json.loads(f())
        except (OSError, ValueError, zipfile.BadZipFile, KeyError):
            return None

    def rels(self, prefix):
        return sorted(r for r in self._files if r.startswith(prefix))

    @property
    def channel(self):
        for rel in ("01-trend-hunter.json", "03-content-researcher.json", "05-video-editor.json"):
            d = self.json(rel)
            if isinstance(d, dict) and d.get("channel"):
                return d["channel"]
        return None if self.group == REBUILDS else self.group


def _wanted(rel):
    return rel in NEEDED_JSON or (rel.startswith(REQUESTS) and rel.endswith(".json"))


def folder_batch(group, bdir):
    files = {}
    for rel in NEEDED_JSON:
        p = bdir / rel
        if p.is_file():
            files[rel] = p.read_bytes
    req = bdir / REQUESTS
    if req.is_dir():
        for p in req.rglob("*.json"):
            files[str(p.relative_to(bdir))] = p.read_bytes
    return Batch(bdir.name, group, files)


def zip_batches(group, zpath):
    """Batches of one month's zip, read member by member (nothing unpacked)."""
    out = {}
    zf = zipfile.ZipFile(zpath)
    for info in zf.infolist():
        if "/" not in info.filename or info.is_dir():
            continue
        bname, rel = info.filename.split("/", 1)
        if batch_date(bname) and _wanted(rel):
            out.setdefault(bname, {})[rel] = (lambda n=info.filename: zf.read(n))
    return [Batch(b, group, f, packed=zpath.name) for b, f in sorted(out.items())]


def groups_for(channel):
    return (channel, REBUILDS)


def load_batches(root, channel, archive, since=None):
    """(batches oldest first, notes)."""
    notes, seen, out = [], set(), []
    pipe = Path(root) / "pipeline"
    for g in groups_for(channel):
        gdir = pipe / g
        if not gdir.is_dir():
            continue
        for b in sorted(p for p in gdir.iterdir() if p.is_dir() and batch_date(p.name)):
            out.append(folder_batch(g, b))
            seen.add((g, b.name))
    packed = 0
    if archive is not None:
        adir = Path(archive)
        if not adir.is_dir():
            notes.append(f"archive: {adir} is not there (Archive not mounted or nothing packed yet)"
                         " - packed batches not read")
        else:
            for g in groups_for(channel):
                for z in sorted((adir / g).glob("*.zip")) if (adir / g).is_dir() else []:
                    try:
                        zb = zip_batches(g, z)
                    except (OSError, zipfile.BadZipFile) as e:
                        notes.append(f"archive: {g}/{z.name} unreadable ({e}) - skipped")
                        continue
                    for b in zb:
                        if (g, b.name) not in seen:
                            out.append(b)
                            seen.add((g, b.name))
                            packed += 1
    keep = []
    for b in out:
        if b.channel != channel:
            continue
        if since and (b.date or "") < since:
            continue
        keep.append(b)
    keep.sort(key=lambda b: (b.date or "", b.name, b.group))
    return keep, packed, notes


# ------------------------------------------------------------------- extract
def _title_refs(b):
    refs = {}
    d1 = b.json("01-trend-hunter.json") or {}
    for t in d1.get("topics") or []:
        if isinstance(t, dict) and isinstance(t.get("title_ref"), dict):
            refs[t.get("topic_id")] = t["title_ref"]
    for t in d1.get("skipped_topics") or []:
        if isinstance(t, dict) and t.get("topic_id") not in refs and t.get("title"):
            refs[t["topic_id"]] = {"name": t["title"], "kind": t.get("kind") or "work"}
    d3 = b.json("03-content-researcher.json") or {}
    for s in d3.get("scripts") or []:
        if isinstance(s, dict) and isinstance(s.get("title_ref"), dict):
            refs.setdefault(s.get("topic_id"), s["title_ref"])
    return refs


def _script_topics(b):
    m = {}
    d3 = b.json("03-content-researcher.json") or {}
    for s in d3.get("scripts") or []:
        if isinstance(s, dict):
            m[s.get("script_id")] = s.get("topic_id")
    return m


def _topic_of(script_id, scripts):
    if script_id in scripts:
        return scripts[script_id]
    return re.sub(r"-script\d+$", "", str(script_id or "")) or None


def _requests(b):
    """topic_id -> request (a pending one over a consumed one)."""
    out = {}
    for rel in sorted(b.rels(REQUESTS), key=lambda r: "/consumed/" not in r):
        d = b.json(rel)
        if isinstance(d, dict) and d.get("topic_id"):
            out[d["topic_id"]] = d
    return out


def _anchor_entities(b):
    """(script_id, anchor_id or phrase) -> [entity] from the coverage gate's
    supplement anchors (03 warnings) and the requests."""
    m = {}

    def put(sid, a):
        ents = [e for e in a.get("entities") or [] if isinstance(e, dict) and e.get("name")]
        for k in (a.get("anchor_id"), norm(a.get("phrase"))):
            if k:
                m[(sid, k)] = ents

    d3 = b.json("03-content-researcher.json") or {}
    for w in d3.get("warnings") or []:
        for a in ((w.get("supplement") or {}).get("anchors") or []) if isinstance(w, dict) else []:
            if isinstance(a, dict):
                put(w.get("script_id"), a)
    return m


def _need(b, kind, name, code, stage, topic, script, what="", detail="", topic_name=None,
          searched=None, step=None):
    key = f"{kind}:{norm(name)}" if norm(name) else None
    return {"kind": kind, "name": str(name).strip(), "key": key,
            "reason": code, "stage": stage, "batch": b.name, "group": b.group,
            "packed": b.packed, "date": b.date, "topic_id": topic, "script_id": script,
            "topic_name": topic_name, "what": str(what or "")[:240],
            "detail": str(detail or "")[:240], "searched": searched or [],
            "supplement_outcome": step}


def extract(b):
    """Every unmet footage need one batch recorded."""
    refs, scripts = _title_refs(b), _script_topics(b)
    reqs, aents = _requests(b), _anchor_entities(b)
    step = ((b.json("work/supplement-step.json") or {}).get("topics") or {})
    out = []

    def subject(topic):
        r = refs.get(topic) or {}
        name = r.get("person") if r.get("kind") == "person" and r.get("person") else r.get("name")
        kind = "person" if r.get("kind") == "person" else "work"
        return kind, name

    def topic_need(code, stage, topic, script, detail):
        req = reqs.get(topic) or {}
        ents = [e for e in req.get("entities") or [] if isinstance(e, dict) and e.get("name")]
        searched = [e["name"] for e in ents]
        outcome = (step.get(topic) or {}).get("outcome")
        kind, name = subject(topic)
        if code == "event_footage_short":
            sc = [e for e in ents if e.get("kind") == "scene"]
            if sc:
                kind, name = "event", sc[0]["name"]
        if not name:
            wk = [e for e in ents if e.get("kind") == "work"]
            if wk:
                kind, name = "work", wk[0]["name"]
        if not name:                    # the topic is in no 01/03 record and laid no request
            out.append(_need(b, "work", "", code, stage, topic, script, detail=detail))
            return
        out.append(_need(b, kind, name, code, stage, topic, script, detail=detail,
                         topic_name=subject(topic)[1] or name, searched=searched, step=outcome))

    def anchor_need(code, stage, script, what, detail, anchor_id=None):
        topic = _topic_of(script, scripts)
        ents = aents.get((script, anchor_id)) if anchor_id else None
        if ents is None:
            ents = aents.get((script, norm(what))) or []
        tkind, tname = subject(topic)
        persons = [e for e in ents if e.get("kind") == "person"]
        if persons:
            for e in persons:
                out.append(_need(b, "person", e["name"], code, stage, topic, script, what,
                                 detail, topic_name=tname))
        elif tname:
            out.append(_need(b, "scene", tname, code, stage, topic, script, what, detail,
                             topic_name=tname))

    d1 = b.json("01-trend-hunter.json") or {}
    for t in d1.get("skipped_topics") or []:
        if isinstance(t, dict) and t.get("reason_code") in HUNTER_CODES:
            topic_need(t["reason_code"], "hunter", t.get("topic_id"), None, t.get("reason"))

    d3 = b.json("03-content-researcher.json") or {}
    topic_seen = set()
    for w in d3.get("warnings") or []:
        if not isinstance(w, dict):
            continue
        code, sid = w.get("warning_code"), w.get("script_id")
        if code in TOPIC_CODES:
            k = (code, w.get("topic_id"))
            if k not in topic_seen:
                topic_seen.add(k)
                topic_need(code, "scripts", w.get("topic_id"), sid, w.get("detail"))
        elif code == "visual_claim_uncovered":
            for c in (w.get("numbers") or {}).get("claims") or []:
                for a in c.get("anchors") or []:
                    if isinstance(a, dict) and a.get("status") == "absent":
                        anchor_need(code, "scripts", sid, a.get("phrase") or c.get("claim"),
                                    f"[{c.get('section')}] {c.get('claim')}", a.get("anchor_id"))
    for s in d3.get("skipped") or []:
        if isinstance(s, dict) and s.get("reason_code") in TOPIC_CODES:
            topic_need(s["reason_code"], "scripts", s.get("topic_id"), None, s.get("reason"))

    d5 = b.json("05-video-editor.json") or {}
    for v in d5.get("videos") or []:
        if not isinstance(v, dict):
            continue
        for a in v.get("unresolved_anchors") or []:
            a = a if isinstance(a, dict) else {"phrase": str(a), "reason": ""}
            why = str(a.get("reason") or "")
            code = "anchor_short" if "cover only" in why else "anchor_no_picture"
            anchor_need(code, "editor", v.get("script_id"), a.get("phrase"), why,
                        a.get("anchor_id"))
    for r in d5.get("refusals") or []:
        if isinstance(r, dict) and r.get("reason_code") in TOPIC_CODES:
            sid = r.get("script_id")
            topic_need(r["reason_code"], "editor", _topic_of(sid, scripts), sid, r.get("reason"))

    d6 = b.json("06-frame-judge.json") or {}
    for v in d6.get("videos") or []:
        if not isinstance(v, dict):
            continue
        for x in v.get("verdicts") or []:
            if isinstance(x, dict) and x.get("verdict") in ("contradicts", "foreign"):
                anchor_need(f"frame_{x['verdict']}", "frame-judge", v.get("script_id"),
                            x.get("narration"), x.get("why"))
    return out


# ------------------------------------------------------------------ fold/sort
def fold(needs):
    rows = {}
    for n in needs:
        r = rows.get(n["key"])
        if r is None:
            r = rows[n["key"]] = {"kind": n["kind"], "name": n["name"], "key": n["key"],
                                  "names": Counter(), "name_seen": {}, "topics": set(), "batches": set(),
                                  "misses": 0, "reasons": Counter(), "stages": Counter(),
                                  "first_seen": n["date"], "last_seen": n["date"],
                                  "examples": [], "searched": [], "supplement": Counter(),
                                  "works": Counter(), "packed": set()}
        r["names"][n["name"]] += 1
        r["name_seen"][n["name"]] = max(r["name_seen"].get(n["name"], ""), n["date"] or "")
        r["topics"].add(n["topic_id"] or f"{n['batch']}?")
        r["batches"].add(n["batch"])
        r["misses"] += 1
        r["reasons"][n["reason"]] += 1
        r["stages"][n["stage"]] += 1
        if n["date"]:
            r["first_seen"] = min(filter(None, (r["first_seen"], n["date"])))
            r["last_seen"] = max(filter(None, (r["last_seen"], n["date"])))
        if n["what"] and n["what"] not in r["examples"]:
            r["examples"].append(n["what"])
        for s in n["searched"]:
            if s not in r["searched"]:
                r["searched"].append(s)
        if n["supplement_outcome"]:
            r["supplement"][n["supplement_outcome"]] += 1
        if n["topic_name"] and n["kind"] != "work":
            r["works"][n["topic_name"]] += 1
        if n["packed"]:
            r["packed"].add(n["batch"])
    out = []
    for r in rows.values():
        # the spelling used most, then the most recent one, then name order
        r["name"] = max(sorted(r["names"]), key=lambda nm: (r["names"][nm], r["name_seen"][nm]))
        out.append({
            "kind": r["kind"], "name": r["name"], "key": r["key"],
            "topics": len(r["topics"]), "batches": len(r["batches"]), "misses": r["misses"],
            "first_seen": r["first_seen"], "last_seen": r["last_seen"],
            "reasons": dict(sorted(r["reasons"].items(), key=lambda kv: (-kv[1], kv[0]))),
            "stages": dict(sorted(r["stages"].items())),
            "examples": r["examples"][-MAX_EXAMPLES:][::-1],
            "searched": r["searched"],
            "supplement_outcomes": dict(sorted(r["supplement"].items())),
            "of_topics": sorted(r["works"]),
            "topic_ids": sorted(r["topics"]), "batch_ids": sorted(r["batches"]),
            "packed_batches": sorted(r["packed"]),
        })
    return sort_rows(out)


def sort_rows(rows):
    """Most topics first, then the most recent, then most misses, then name."""
    rows = sorted(rows, key=lambda r: (r["kind"], norm(r["name"])))
    rows.sort(key=lambda r: r["misses"], reverse=True)
    rows.sort(key=lambda r: r["last_seen"] or "", reverse=True)
    rows.sort(key=lambda r: r["topics"], reverse=True)
    return rows


# ------------------------------------------------------------ pool and where
def load_pool(root):
    p = Path(root) / "shared" / "footage" / "index.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ents = d.get("entries") if isinstance(d, dict) else d
    return [e for e in ents or [] if isinstance(e, dict) and e.get("id")]


def load_official(root, channel):
    """(entries, note) - the official footage channels of `channel`'s own
    footage-origin list (CF-0631). The channel is always named (CF-0213); a
    channel without the list, or a list without `official_channels`, is a
    note, not a silent empty "where"."""
    try:
        d = channel_data.footage_origin(channel, Path(root))
    except channel_data.ChannelDataError as e:
        return [], f"official channels: not read - {e}"
    ocs = d.get("official_channels") if isinstance(d, dict) else None
    if not isinstance(ocs, list):
        return [], (f"official channels: the footage-origin list of {channel!r} has no "
                    "`official_channels` list - «где добыть» without official channels")
    out = [e for e in ocs if isinstance(e, dict) and e.get("pattern")]
    if not out:
        return [], (f"official channels: the footage-origin list of {channel!r} is empty - "
                    "«где добыть» without official channels")
    return out, None


def known_sources(batches):
    """norm(name) -> {network, rights_holder, candidates[]} from what the batches recorded."""
    k = {}
    for b in batches:
        for ref in _title_refs(b).values():
            n = norm(ref.get("name"))
            if n:
                e = k.setdefault(n, {"networks": [], "candidates": []})
                for f in ("network", "rights_holder"):
                    if ref.get(f) and ref[f] not in e["networks"]:
                        e["networks"].append(ref[f])
        for req in _requests(b).values():
            names = [norm(x.get("name")) for x in req.get("entities") or [] if isinstance(x, dict)]
            for c in req.get("candidates") or []:
                if not isinstance(c, dict) or not c.get("video_id"):
                    continue
                for n in {norm(c.get("entity"))} | set(names[:1]):
                    if not n:
                        continue
                    e = k.setdefault(n, {"networks": [], "candidates": []})
                    if all(x["video_id"] != c["video_id"] for x in e["candidates"]):
                        e["candidates"].append({f: c.get(f) for f in (
                            "video_id", "title", "channel_title", "origin", "nature")})
    return k


def where_to_get(row, known, official, pool_ids):
    names = {norm(row["name"])} | {norm(w) for w in row.get("of_topics") or []}
    out = {"official_channels": [], "candidates": []}
    for n in sorted(names):
        e = known.get(n) or {}
        for c in e.get("candidates") or []:
            if all(x["video_id"] != c["video_id"] for x in out["candidates"]):
                out["candidates"].append(dict(c, in_pool=c["video_id"] in pool_ids))
        for net in e.get("networks") or []:
            for oc in official:
                words = [oc["pattern"]] + list(oc.get("owners") or [])
                if any(has_run(net, w) for w in words):
                    for ch in oc.get("channels") or []:
                        item = {"title": ch.get("title"), "id": ch.get("id"), "for": net}
                        if ch.get("id") and all(x["id"] != ch["id"] for x in out["official_channels"]):
                            out["official_channels"].append(item)
    out["candidates"].sort(key=lambda c: (c.get("origin") != "official", c["in_pool"]))
    out["candidates"] = out["candidates"][:MAX_WHERE]
    out["official_channels"] = out["official_channels"][:MAX_WHERE]
    return out


def in_pool(row, pool):
    if pool is None:
        return None
    hits = []
    for e in pool:
        if has_run(f"{e.get('title', '')} {e.get('note', '')}", row["name"]):
            hits.append({"id": e["id"], "title": e.get("title")})
    return hits


# ------------------------------------------------------------------ build
def build(root, channel, archive=DEFAULT_ARCHIVE, since=None, now=None):
    batches, packed, notes = load_batches(root, channel, archive, since)
    needs, unnamed = [], []
    for b in batches:
        for n in extract(b):
            (needs if n["key"] else unnamed).append(n)
    if unnamed:
        notes.append(f"{len(unnamed)} need(s) without a name (topic in no 01/03 record, no "
                     "request): " + ", ".join(sorted({f"{n['batch']}/{n['topic_id']} {n['reason']}"
                                                      for n in unnamed})[:10]))
    rows = fold(needs)
    pool = load_pool(root)
    if pool is None:
        notes.append("pool: shared/footage/index.json unreadable - `in_pool` not marked")
    pool_ids = {e["id"] for e in pool or []}
    known = known_sources(batches)
    official, note = load_official(root, channel)
    if note:
        notes.append(note)
    for r in rows:
        r["in_pool_now"] = in_pool(r, pool)
        r["where"] = where_to_get(r, known, official, pool_ids)
    return {
        "task": TASK, "channel": channel,
        "built_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": since,
        "batches": {"read": len(batches), "packed": packed,
                    "first": batches[0].name if batches else None,
                    "last": batches[-1].name if batches else None},
        "notes": notes, "needs": len(needs),
        "by_reason": dict(sorted(Counter(n["reason"] for n in needs).items())),
        "rows": rows,
    }


def _cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def _short(s, n=90):
    s = _cell(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def render_md(rep):
    L = [f"# Футаж «что добыть» — {rep['channel']}", ""]
    bt = rep["batches"]
    L.append(f"Собрано {rep['built_at']} ({TASK}) по {bt['read']} батчам канала"
             + (f" ({bt['first']} … {bt['last']})" if bt["read"] else "")
             + (f", из них упакованных в zip: {bt['packed']}" if bt["packed"] else "")
             + (f"; с {rep['since']}" if rep.get("since") else "") + ".")
    L.append(f"Незакрытых потребностей: {rep['needs']}, строк: {len(rep['rows'])}. "
             "Строка — одна вещь, которую добыть; «тем» — сколько разных тем её не получили, "
             "«батчей» — в скольких батчах, «промахов» — сколько записей стадий.")
    for n in rep["notes"]:
        L.append(f"- {n}")
    L.append("")
    for kind in KINDS:
        rows = [r for r in rep["rows"] if r["kind"] == kind]
        if not rows:
            continue
        L += [f"## {KIND_TITLES[kind]} ({len(rows)})", "",
              "| # | Что добыть | Тем | Батчей | Промахов | Последний раз | Почему | В пуле сейчас | Где добыть (известно фабрике) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(rows, 1):
            what = r["name"]
            if r["of_topics"] and kind != "scene":
                what += f" (в темах: {', '.join(r['of_topics'][:3])})"
            if r["examples"]:
                what += "<br>кадр: «" + _short(r["examples"][0]) + "»"
            if r["searched"]:
                what += "<br>искали: " + _short(", ".join(r["searched"][:6]))
            why = ", ".join(f"{k}×{v}" for k, v in r["reasons"].items())
            if r["supplement_outcomes"]:
                why += "<br>добор: " + ", ".join(f"{k}×{v}" for k, v in r["supplement_outcomes"].items())
            pool = r["in_pool_now"]
            pool_s = "?" if pool is None else (
                "нет" if not pool else f"{len(pool)}: " + ", ".join(p["id"] for p in pool[:3]))
            w = r["where"]
            ws = []
            if w["official_channels"]:
                ws.append("офиц. каналы: " + ", ".join(c["title"] for c in w["official_channels"][:3]))
            for c in w["candidates"][:2]:
                ws.append(f"{c['video_id']} «{_short(c.get('title') or '', 50)}» "
                          f"({c.get('channel_title') or '?'}, {c.get('origin') or '?'}"
                          + (", уже в пуле" if c["in_pool"] else "") + ")")
            L.append(f"| {i} | {_cell(what)} | {r['topics']} | {r['batches']} | {r['misses']} | "
                     f"{r['last_seen'] or '?'} | {_cell(why)} | {_cell(pool_s)} | "
                     f"{_cell('<br>'.join(ws) or '—')} |")
        L.append("")
    L += ["## Коды причин", ""]
    for k, v in REASONS.items():
        L.append(f"- `{k}` — {v}")
    L += ["", "«Где добыть» — только кандидаты, уже найденные охотником для запросов добора, и "
          "официальные каналы из `channels/<канал>/footage-origin.json` по сети/правообладателю "
          "работы; «—» значит, фабрике это неизвестно. «В пуле сейчас» — совпадение имени в "
          "названии/заметке `shared/footage/index.json` (пул временный, CF-0358).", ""]
    return "\n".join(L)


def total_line(rep):
    bt = rep["batches"]
    kinds = Counter(r["kind"] for r in rep["rows"])
    return (f"TOTAL channel={rep['channel']} batches={bt['read']} packed={bt['packed']} "
            f"needs={rep['needs']} rows={len(rep['rows'])} "
            + " ".join(f"{k}={kinds.get(k, 0)}" for k in KINDS)
            + (f" notes={len(rep['notes'])}" if rep["notes"] else ""))


def write(rep, out_dir):
    d = Path(out_dir) / rep["channel"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{OUT_NAME}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    (d / f"{OUT_NAME}.md").write_text(render_md(rep), encoding="utf-8")
    return d


def channels(root):
    root = Path(root)
    names = {p.stem for p in (root / "channels").glob("*.json")}
    pipe = root / "pipeline"
    if pipe.is_dir():
        names |= {p.name for p in pipe.iterdir() if p.is_dir() and p.name not in NOT_A_CHANNEL
                  and not p.name.startswith(".")}
    return sorted(names)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="footage_wanted.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect", help="build the list for every channel (or one)")
    s.add_argument("--channel")
    s.add_argument("--since", help="only batches from this day on (YYYY-MM-DD)")
    s.add_argument("--archive", default=DEFAULT_ARCHIVE,
                   help="where the packed batches are (monthly_archive.py's Archive folder)")
    s.add_argument("--no-archive", action="store_true", help="do not look for packed batches")
    s.add_argument("--root", help="the factory root (tests)")
    s.add_argument("--out", help="write <out>/<channel>/ instead of analytics/<channel>/")
    s.add_argument("--now", help="the build time written into the list (tests)")
    s.add_argument("--print", action="store_true", help="print the markdown")
    s.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root or ROOT)
    if not root.is_dir():
        print(f"ERROR root {root} is not a directory", file=out)
        return 2
    if a.since and not re.match(r"^\d{4}-\d{2}-\d{2}$", a.since):
        print(f"ERROR --since {a.since!r}: want YYYY-MM-DD", file=out)
        return 2
    known = channels(root)
    if a.channel and a.channel not in known:
        print(f"ERROR channel {a.channel!r}: no channels/{a.channel}.json and no "
              f"pipeline/{a.channel}/ (known: {', '.join(known) or 'none'})", file=out)
        return 2
    archive = None if a.no_archive else a.archive
    out_root = Path(a.out) if a.out else root / "analytics"
    for ch in ([a.channel] if a.channel else known):
        rep = build(root, ch, archive=archive, since=a.since, now=a.now)
        if a.print:
            print(render_md(rep), file=out)
        if not a.no_write:
            d = write(rep, out_root)
            print(f"WROTE {d / OUT_NAME}.md (+ .json)", file=out)
        for n in rep["notes"]:
            print(f"NOTE {ch}: {n}", file=out)
        print(total_line(rep), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
