#!/usr/bin/env python3
"""What the CF-0451 screen-recording detector would have marked on frozen
batches - the measurement a price is proposed from (CF-0320). Read-only: it
reads `01-trend-hunter.json`, `01b-footage-index.json`, the videos'
`work/<slug>/storyboard.json`, the pool's `<id>.shots.json` and the
acceptance log, and writes nothing. It never re-describes or re-measures a
shot (the pool is transient, CF-0410): a source whose index is gone is
counted as `index_gone`, not guessed.

Usage:
    measure_screen_recording.py [--channel example-film] [--last 5] [batch-dir ...]
        [--json]

Per batch: the sources the batch kept, how many of them hold filmed-screen
shots (the describer's flag or sentence) or carry cam words in the candidate
title; the videos whose storyboard cut such a shot, with the seconds on screen
and whether they fell in the hook; and the user's verdict on those videos
from `publish/acceptance-log.json`.
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import archive_source  # noqa: E402 - CF-0665: archive candidates by their file id
import screen_recording  # noqa: E402

from _fi_paths import checkout_root  # noqa: E402 - CF-0620

ROOT = checkout_root()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout
POOL = ROOT / "shared" / "footage"
ACCEPTANCE = ROOT / "publish" / "acceptance-log.json"
HOOK_SECONDS = 5.0


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def last_batches(channel, n, root=ROOT):
    d = root / "pipeline" / channel
    runs = sorted(p for p in d.iterdir()
                  if p.is_dir() and (p / "01b-footage-index.json").exists())
    return runs[-n:] if n else runs


def verdicts(path=ACCEPTANCE):
    out = {}
    for a in (_load(path) or {}).get("acceptances") or []:
        out[a.get("entry_id")] = (a.get("verdict"), a.get("reason_code"))
    return out


def titles_of(batch):
    th = _load(batch / "01-trend-hunter.json") or {}
    out = {}
    for t in th.get("topics") or []:
        for c in (t.get("evidence") or {}).get("footage_candidates") or []:
            if isinstance(c, dict) and c.get("video_id") and c.get("title"):
                # CF-0665: an archive candidate is reported under its file id
                out.setdefault(archive_source.file_id(c["video_id"]), c["title"])
    return out


def measure_batch(batch, pool=POOL, accepted=None):
    batch = Path(batch)
    report = _load(batch / "01b-footage-index.json") or {}
    titles = titles_of(batch)
    accepted = accepted if accepted is not None else verdicts()
    sources, flagged_by_vid = [], {}
    for tid, vids in (report.get("sources_by_topic") or {}).items():
        for vid in vids or []:
            index = _load(pool / f"{vid}.shots.json")
            rec = {"topic_id": tid, "video_id": vid,
                   "title": titles.get(vid)}
            if index is None:
                rec["index_gone"] = True
                hit = screen_recording.title_hit(titles.get(vid))
                rec["title_hit"] = hit
                rec["flagged"] = []
            else:
                s = screen_recording.source_summary(index, title=titles.get(vid))
                rec.update({"shots": s["shots"], "flagged": s["flagged"],
                            "by": s["by"], "title_hit": s["title_hit"],
                            "examples": s["examples"]})
                flagged_by_vid[vid] = set(s["flagged"])
            sources.append(rec)
    videos = []
    work = batch / "work"
    for sb in sorted(work.glob("*/storyboard.json")) if work.exists() else []:
        slug = sb.parent.name
        board = _load(sb) or {}
        hits, seconds, hook = [], 0.0, False
        for b in board.get("blocks") or []:
            ref = b.get("shot")
            if not isinstance(ref, str) or ":" not in ref:
                continue
            vid, _, idx = ref.rpartition(":")
            try:
                idx = int(idx)
            except ValueError:
                continue
            if idx in flagged_by_vid.get(vid, ()):
                start, end = b.get("_start") or 0.0, b.get("_end") or 0.0
                hits.append({"shot": ref, "start": start, "end": end})
                seconds += max(0.0, end - start)
                hook = hook or start < HOOK_SECONDS
        verdict = accepted.get(f"{report.get('batch') or batch.parent.name + '/' + batch.name}/{slug}")
        if verdict is None:
            verdict = accepted.get(f"{batch.parent.name}/{batch.name}/{slug}")
        videos.append({"slug": slug, "flagged_blocks": hits,
                       "seconds": round(seconds, 2), "in_hook": hook,
                       "verdict": verdict})
    return {"batch": f"{batch.parent.name}/{batch.name}", "sources": sources,
            "videos": videos}


def totals(measured):
    t = {"batches": len(measured), "sources": 0, "index_gone": 0,
         "sources_flagged": 0, "title_hits": 0, "shots": 0,
         "shots_flagged": 0, "videos": 0, "videos_flagged": 0,
         "videos_flagged_in_hook": 0, "videos_flagged_rejected_cam": 0}
    for m in measured:
        for s in m["sources"]:
            t["sources"] += 1
            t["index_gone"] += bool(s.get("index_gone"))
            t["sources_flagged"] += bool(s.get("flagged"))
            t["title_hits"] += bool(s.get("title_hit"))
            t["shots"] += s.get("shots") or 0
            t["shots_flagged"] += len(s.get("flagged") or [])
        for v in m["videos"]:
            t["videos"] += 1
            if v["flagged_blocks"]:
                t["videos_flagged"] += 1
                t["videos_flagged_in_hook"] += v["in_hook"]
                t["videos_flagged_rejected_cam"] += (
                    (v["verdict"] or (None, None))[1] == "cam_rip_footage")
    return t


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("batches", nargs="*")
    p.add_argument("--channel", default="example-film")
    p.add_argument("--last", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    runs = ([Path(b) for b in a.batches] if a.batches
            else last_batches(a.channel, a.last))
    accepted = verdicts()
    measured = [measure_batch(b, accepted=accepted) for b in runs]
    t = totals(measured)
    if a.json:
        print(json.dumps({"batches": measured, "totals": t}, indent=2,
                         ensure_ascii=False))
        return 0
    for m in measured:
        print(f"== {m['batch']}")
        for s in m["sources"]:
            if s.get("flagged") or s.get("title_hit"):
                print(f"  source {s['video_id']} ({s['topic_id']}): "
                      f"{len(s['flagged'])}/{s.get('shots')} shot(s) "
                      f"{s['flagged']} by {s.get('by')}, title_hit="
                      f"{s.get('title_hit')!r} - {s.get('title')!r}")
        for v in m["videos"]:
            if v["flagged_blocks"]:
                print(f"  video {v['slug']}: {len(v['flagged_blocks'])} "
                      f"block(s), {v['seconds']} s, hook={v['in_hook']}, "
                      f"verdict={v['verdict']}")
    print("totals:", json.dumps(t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
