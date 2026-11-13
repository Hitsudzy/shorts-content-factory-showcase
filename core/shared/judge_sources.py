#!/usr/bin/env python3
"""CF-0884: whose upload each judged block of a video comes from - the frame
judge's answer to "is this picture about the title at all?" on a channel whose
footage is the subject's own videos.

Why: over every Tech batch on disk (9 batches, 18 judged videos, 20-25.10)
all four `foreign` verdicts sat on shots of the topic company's own official
upload (`footage_origin: vendor_official` - Anthropic's lab video and its
philosopher Q&A under "Anthropic ...", OpenAI's DevDay 2026 keynote under
"ChatGPT ..."). The judge's pack (`work/<slug>/frame-judge/manifest.json`)
carries a block's `source.video_id` and nothing about whose video it is, so a
scientist, a presenter on a stage or two people on a bench read as "stock of
something else" - two `judge_foreign_core` refusals and one score refusal,
all three accepted by the user. This prints, per judged entry, the channel,
the title and the origin of the upload its shot was cut from, read from the
batch's `01-trend-hunter.json` (the footage candidates the Trend Hunter
found for each topic), and the topic of the video, so the judge can tell the
title's own footage from footage of something else (SKILL frame-judge, step 2
and step 3 "The topic's own upload").

    python3 shared/judge_sources.py <batch> <slug> [--json]

Read-only: the batch's `01-trend-hunter.json`, `03-content-researcher.json`,
`05-video-editor.json` and the video's pack manifest. No network, no pool.
A batch without `01` (or a shot not found there) prints the entry with
`origin: unknown` - the judge then judges the picture alone, as before.

CF-0927: for a film or series topic each row also says whether the upload is
about **another work** (`other_work`, shared/other_work_source.py - CF-0924's
rule: the title names the work only as a credit, or an official upload's
title is about another film). 08.11 Jon Marrow was cut whole from Example Pictures's
"Karōshi (2027) Official Trailer"; this printed "official - channel 'Example Pictures
Movies'" and the judge wrote `neutral` nine times. Such a row is printed
`OTHER WORK`, and the gate (scripts/frame_judge_gate.py) records the entry
`contradicts`, `mismatch: work`, whatever verdict was written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import other_work_source                                           # noqa: E402

TASK = "CF-0884"
TREND_FILE = "01-trend-hunter.json"
SCRIPTS_FILE = "03-content-researcher.json"
EDITOR_FILE = "05-video-editor.json"
MANIFEST = Path("frame-judge") / "manifest.json"
UNKNOWN = "unknown"
# The origin of the subject's own upload (agents/trend-hunter: an official
# channel of the company or product the topic is about).
VENDOR_OFFICIAL = "vendor_official"
_SCRIPT_SUFFIX = re.compile(r"-script\d+$")
_SHOT = re.compile(r"^(?P<vid>[^:]+):\d+$")
_KEEP = ("video_id", "channel_title", "title", "footage_origin", "origin", "role", "kind",
         "rule", other_work_source.SUBJECT_KEY)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _candidates(node, out):
    """Every dict under `node` that names an upload (`video_id` + `channel_title`)."""
    if isinstance(node, dict):
        if isinstance(node.get("video_id"), str) and "channel_title" in node:
            out.append(node)
        for v in node.values():
            _candidates(v, out)
    elif isinstance(node, list):
        for v in node:
            _candidates(v, out)
    return out


def footage_index(trend, topic_id=None):
    """`{video_id: upload}` from `01`: the video's own topic first, then every
    other topic, then `footage_candidates_shared` - the first record of an id
    wins."""
    idx = {}
    if not isinstance(trend, dict):
        return idx
    topics = [t for t in trend.get("topics") or [] if isinstance(t, dict)]
    own = [t for t in topics if topic_id and t.get("topic_id") == topic_id]
    rest = [t for t in topics if t not in own]
    for node in own + rest + [trend.get("footage_candidates_shared") or []]:
        for c in _candidates(node, []):
            idx.setdefault(c["video_id"], {k: c.get(k) for k in _KEEP})
    return idx


def topic_of(batch, slug):
    """`(topic_id, topic name)` of the video `slug` of the batch, or Nones."""
    tid, ref = topic_ref(batch, slug)
    return tid, ref.get("name") if isinstance(ref, dict) else None


def topic_ref(batch, slug):
    """`(topic_id, title_ref as a dict)` of the video `slug`, or Nones (a bare
    string `title_ref` reads as `{"name": ...}`)."""
    batch = Path(batch)
    sid = None
    for v in (_read(batch / EDITOR_FILE) or {}).get("videos") or []:
        if isinstance(v, dict) and Path(str(v.get("output_path") or "")).stem == slug:
            sid = v.get("script_id")
            break
    tid = None
    if sid:
        for s in (_read(batch / SCRIPTS_FILE) or {}).get("scripts") or []:
            if isinstance(s, dict) and s.get("script_id") == sid:
                tid = s.get("topic_id")
                break
        tid = tid or _SCRIPT_SUFFIX.sub("", sid)
    ref = None
    for t in (_read(batch / TREND_FILE) or {}).get("topics") or []:
        if isinstance(t, dict) and tid and t.get("topic_id") == tid:
            raw = t.get("title_ref")
            ref = dict(raw) if isinstance(raw, dict) else ({"name": raw} if isinstance(raw, str) else None)
            break
    return tid, ref


def ready_subjects(trend, topic_id):
    """CF-0927: `{video_id: title_subject}` of the uploads the Trend Hunter
    itself read as another work for this topic (CF-0924's drop record:
    `rule: other_work_title`). Another topic's flag says nothing about this
    one."""
    out = {}
    if not isinstance(trend, dict) or not topic_id:
        return out
    for t in trend.get("topics") or []:
        if isinstance(t, dict) and t.get("topic_id") == topic_id:
            for c in _candidates(t, []):
                subject = c.get(other_work_source.SUBJECT_KEY)
                if c.get("rule") == other_work_source.TREND_RULE and subject:
                    out.setdefault(c["video_id"], subject)
    return out


def other_work_map(batch, slug, entries, trend=None):
    """CF-0927: `{entry id: hit}` for the judged `entries` (pack manifest
    entries) whose shot's upload is about another work than the video's
    screen-work topic (shared/other_work_source.py). Empty for any other
    topic, and for a shot whose upload `01` does not know."""
    batch = Path(batch)
    tid, ref = topic_ref(batch, slug)
    if not other_work_source.is_screen_work(ref):
        return {}
    trend = _read(batch / TREND_FILE) if trend is None else trend
    idx = footage_index(trend, tid)
    ready = ready_subjects(trend, tid)
    forms = other_work_source.work_forms(ref)
    out = {}
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("judged") or not e.get("id"):
            continue
        src = e.get("source") if isinstance(e.get("source"), dict) else {}
        if src.get("own_graphic") or src.get("own_capture"):
            continue
        vid = _video_id(src)
        if not vid:
            continue
        up = idx.get(vid) or ({"video_id": vid} if vid in ready else None)
        hit = other_work_source.check(up, ref, forms, ready.get(vid))
        if hit:
            out[e["id"]] = hit
    return out


def _video_id(source):
    if not isinstance(source, dict):
        return None
    if source.get("video_id"):
        return source["video_id"]
    m = _SHOT.match(str(source.get("shot") or ""))
    return m.group("vid") if m else None


def sources(batch, slug):
    """`{topic_id, topic, entries: [...]}` - one row per judged pack entry:
    `{entry, start, end, ours, video_id, shot, channel_title, title, origin,
    role}`. `ours` is `own_graphic` / `own_capture` for a picture the factory
    made (no upload behind it); `origin` is the upload's `footage_origin`
    (`vendor_official` - the subject's own channel), else its `origin`, else
    `unknown`."""
    batch = Path(batch)
    tid, ref = topic_ref(batch, slug)
    name = (ref or {}).get("name")
    manifest = _read(batch / "work" / slug / MANIFEST)
    if not isinstance(manifest, dict):
        return {"topic_id": tid, "topic": name, "title_ref": ref, "entries": [],
                "refusal": f"no pack manifest at work/{slug}/{MANIFEST}"}
    trend = _read(batch / TREND_FILE)
    idx = footage_index(trend, tid)
    other = other_work_map(batch, slug, manifest.get("entries") or [], trend)
    rows = []
    for e in manifest.get("entries") or []:
        if not isinstance(e, dict) or not e.get("judged"):
            continue
        src = e.get("source") if isinstance(e.get("source"), dict) else {}
        ours = "own_graphic" if src.get("own_graphic") else ("own_capture" if src.get("own_capture") else None)
        vid = None if ours else _video_id(src)
        up = idx.get(vid) if vid else None
        rows.append({
            "entry": e.get("id"), "start": e.get("start"), "end": e.get("end"),
            "ours": ours, "video_id": vid, "shot": src.get("shot"),
            "channel_title": (up or {}).get("channel_title"),
            "title": (up or {}).get("title"),
            "origin": ((up or {}).get("footage_origin") or (up or {}).get("origin") or UNKNOWN) if vid else None,
            "role": (up or {}).get("role"),
            # CF-0927: the upload is about another work (None: it is not, or
            # nobody can tell)
            "other_work": other.get(e.get("id")),
        })
    return {"topic_id": tid, "topic": name, "title_ref": ref, "entries": rows, "refusal": None}


def render(doc, slug):
    out = [f"{slug}: topic {doc.get('topic') or '?'} ({doc.get('topic_id') or '?'})"]
    if doc.get("refusal"):
        return out + [f"  {doc['refusal']}"]
    for r in doc["entries"]:
        if r["ours"]:
            what = f"ours ({r['ours']})"
        elif not r["video_id"]:
            what = "no upload (a card or a split)"
        elif r["origin"] == UNKNOWN and not r["channel_title"]:
            what = f"{r['video_id']} - origin unknown (not in {TREND_FILE})"
        else:
            what = f"{r['video_id']} {r['origin']} - channel {r['channel_title']!r}, \"{r['title']}\""
        if r.get("other_work"):
            what += (f" - OTHER WORK ({other_work_source.TASK}): {r['other_work']['why']} -> "
                     f"the gate records it contradicts, mismatch work")
        out.append(f"  {r['entry']}\t{what}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch")
    ap.add_argument("slug")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    doc = sources(a.batch, a.slug)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(render(doc, a.slug)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
