#!/usr/bin/env python3
"""CF-0325: what the footage pool already holds for a topic, asked before the
shortlist is cut.

The failure (grill of 2026-09-22, Q4): `shared/footage` held 133 downloaded,
cut and described sources, and not one production path of this stage read it.
Topics were chosen on RSS and popularity alone, and the indexer then fetched
footage for them from scratch - with `no_second_source`, `pool_too_thin` and
`fetch_failed` as the price. The decision of 2026-09-29 (grill "формат канала",
Q8): the hunter ranks topics by **hype x pool**; the fact is a threshold.

What this module answers, per topic
-----------------------------------
`coverage(topics)` -> one record per topic, written onto it as `topics[].pool`:

  sources   - pool sources matched to the topic
  shots     - their shots, minus the retired ones
  retired   - shots already spent on a finished video (CF-0397,
              `pipeline/<channel>/retired-shots.json`): a retired shot is
              refused by the Editor for every other video, so it is not pool
  usable    - of `shots`, what the Video Editor's pre-cut gate leaves standing
              (`footage-indexer/scripts/pool_depth.screen_shots`, the CF-0304
              number, run in `pool_screen.py` under the indexer's venv); null
              when that gate could not be run
  matched[] - which sources, and **how** each was matched (`by`)
  coverage  - 0..1, see RANKING below
  factor, rank_score - what the cut sorts on

Matching is by title, never by video_id (the task's own words: "по
тайтлу/франшизе"). A topic is asked under its phrases: `title_ref.name`, its
`parent_work` / `parent`, the `person` of a person topic, and the franchise -
the part of the name before a `:` or ` - ` ("Rennick: Quill" -> "Rennick").
A source matches a phrase

  * `title`: the phrase stands as whole words in the source's title in
    `shared/footage/index.json` ("The Diplomat" in "The Diplomat: Season 4 |
    Official Trailer | ExampleStream");
  * `topic`: the source was fetched for an earlier topic (`note`: "batch X,
    topic Y") whose own name carries the phrase - the fan upload titled "WHY
    DO YOU HATE the new series?" was fetched for "Wren Hollow" and is
    Wren Hollow footage although its title does not say so. The earlier
    topic's name is read from `pipeline/*/X/01-trend-hunter.json` (every
    channel: the pool is shared).

A phrase shorter than MIN_PHRASE characters is not asked: "It" or "Up" would
match half the pool.

Somebody else's host show is not pool (CF-0817)
-----------------------------------------------
A matched source that is somebody else's podcast, interview or talk show -
Fallon with Tom Carver for Delver (`ZLXL1L0TfsI`), Zenith's own Doomsday
podcast (`xe3qx0kXArA`, `nSWnovHSDaY`) - is refused by the Footage Indexer's
pool reuse (`pool_sources.vet()`), so it is no footage for the topic and
earns it no bonus here. Each match is asked `host_show.judge()` with the
indexer's own inputs: the pool's title and uploader (`index.json` `title`,
`uploader` as `channel_title`), no nature, `official` from the channel's
footage_origin list (CF-0631), and the topic's `title_ref` for the two
exceptions (`subject_is_guest`, `topic_is_the_show`). A refused source is
left out of `sources`, `shots`, `usable` and `matched[]` and listed under
`host_show_skipped` (its video ids), so the ranking stays explainable; a
source kept under an exception counts and its `matched[]` row says which
(`host_show`). A topic whose only match was a host show keeps factor 1. A
verdict that cannot be had (the classifier raised) never counts the source -
it is skipped too and `host_show_error` says why. The channel's official list
or the host-show config that cannot be loaded makes `Pool.load()` an empty
pool with an `error` - coverage 0 for everyone, today's hype order.

RANKING - hype x pool, and why it is a bonus and never a zero
-------------------------------------------------------------
    coverage   = min(1, usable / POOL_DEPTH_FLOOR)      (pool_depth's floor, 60)
               = min(1, sources / SOURCE_FLOOR)          when `usable` is null
    factor     = 1 + POOL_WEIGHT * coverage             (POOL_WEIGHT = 0.5)
    rank_score = popularity_score * factor

The pool is a **multiplier bounded at 1.5 and never below 1**:

  * a fresh hot topic with nothing in the pool keeps its whole hype score -
    `factor` is 1, not 0 - so the pool never takes a topic off the batch and
    the factory does not start chewing its archive (the user's objection in
    the task). The pool only reorders **today's** topics: every topic here
    already came in on today's RSS and cleared `min_popularity_score`; a
    source in the pool with no news today is never a topic.
  * a topic whose pool is already at the depth the indexer stops fetching at
    outranks a pool-less one only when its hype is at least 2/3 of the other's
    (1 / 1.5). The views come from the hype (AHS 1.4k, Widow's Bay 1k), so the
    pool is allowed to break a near-tie and to lift a topic across the
    shortlist line, not to overturn a clear hype lead.
  * the scale is the indexer's own: at 60 usable shots the indexer stops
    fetching (CF-0304), so a pool at that depth is one that costs no download
    at all, and coverage saturates there.

Freshness is not this module's job and it waits for nothing: the pool is
filled by the ingest queue (CF-0324) with what this stage finds today; the run
asks what is already there and moves on. The pool is transient (CF-0358, from
1.5 sources are deleted after publication) - a topic whose sources are gone
simply reads a thinner pool.

A pool that cannot be read never costs a topic: `coverage()` answers with an
`error` and coverage 0 for everyone, which is today's order exactly.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

RULE = "CF-0325"
POOL_KEY = "pool"
POOL_WEIGHT = 0.5
POOL_DEPTH_FLOOR = 60        # fallback only - pool_screen.py reports pool_depth's own
SOURCE_FLOOR = 2             # CF-0129: two canonical sources, when usable is unknown
MIN_PHRASE = 4
MATCHED_KEEP = 12

FOOTAGE_REL = Path("shared") / "footage"
INDEX_NAME = "index.json"
INDEXER_SCRIPTS_REL = Path("agents") / "footage-indexer" / "scripts"
INDEXER_VENV_REL = Path("agents") / "footage-indexer" / ".venv" / "bin" / "python"
PIPELINE_REL = Path("pipeline")
RETIRED_NAME = "retired-shots.json"
SCREEN_TIMEOUT = 180

_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_NOTE = re.compile(r"batch\s+(\S+?),\s*topic\s+(\S+)")


def normalise(text):
    """Lower case, apostrophes folded and dropped, everything but letters and
    digits a single space. `"Stuart Fails to Save the Universe's"` ->
    `"stuart fails to save the universes"`."""
    text = (text or "").translate(_APOSTROPHES).lower().replace("'", "")
    return " ".join(re.findall(r"[^\W_]+", text))


def has_phrase(phrase, text):
    """Whole-word containment of one normalised phrase in another."""
    return bool(phrase) and f" {phrase} " in f" {text} "


def phrases_of(topic):
    """The names a topic is looked up under, normalised, longest first."""
    ref = topic.get("title_ref") or {}
    raw = [ref.get("name"), ref.get("parent_work"), ref.get("parent"), ref.get("person")]
    name = ref.get("name") or ""
    for sep in (":", " - ", " – "):
        if sep in name:
            raw.append(name.split(sep, 1)[0])
    out = []
    for r in raw:
        p = normalise(r if isinstance(r, str) else "")
        if len(p) >= MIN_PHRASE and p not in out:
            out.append(p)
    return sorted(out, key=len, reverse=True)


# --------------------------------------------------------------------------
# what the pool holds
# --------------------------------------------------------------------------

def load_index(root):
    """`shared/footage/index.json` entries whose index file exists (a source
    without `shots.json` is not cut yet and not pool)."""
    footage = Path(root) / FOOTAGE_REL
    entries = (json.load(open(footage / INDEX_NAME)) or {}).get("entries") or []
    return [e for e in entries
            if e.get("id") and (footage / f"{e['id']}.shots.json").exists()]


def topic_names(root):
    """{(batch_id, topic_id): name} over every earlier batch of every channel
    (the pool is shared, `shared/footage`, and a channel renamed by CF-0180
    keeps its old batches under the old id) - carried topics and reserve rows
    both, since either can have been fetched."""
    names = {}
    for f in sorted((Path(root) / PIPELINE_REL).glob("*/*/01-trend-hunter.json")):
        try:
            b = json.load(open(f))
        except Exception:
            continue
        bid = f.parent.name
        rows = list(b.get("topics") or [])
        rows += [r.get("topic") or r for r in b.get("skipped_topics") or []
                 if isinstance(r, dict)]
        for t in rows:
            name = (t.get("title_ref") or {}).get("name") or t.get("title")
            if t.get("topic_id") and name:
                names[(bid, t["topic_id"])] = name
    return names


def retired_shots(root, channel, before=None):
    """{video_id: [shot index, ...]} spent on this channel's finished videos
    (retired before `before`, when given - the replay's view)."""
    path = Path(root) / PIPELINE_REL / channel / RETIRED_NAME
    try:
        videos = (json.load(open(path)) or {}).get("videos") or {}
    except Exception:
        return {}
    out = {}
    for rec in videos.values():
        if before and ((rec or {}).get("retired_at") or "") >= before:
            continue
        for ref in (rec or {}).get("shots") or ():
            vid, _, idx = str(ref).rpartition(":")
            if vid and idx.isdigit():
                out.setdefault(vid, set()).add(int(idx))
    return {k: sorted(v) for k, v in out.items()}


def screen(root, sources, retired):
    """Run `pool_screen.py` over these video ids. Returns its answer; never
    raises (a failure comes back as `error` with no per-source numbers)."""
    root = Path(root)
    venv = root / INDEXER_VENV_REL
    python = str(venv if venv.exists() else sys.executable)
    req = {"cache": str(root / FOOTAGE_REL),
           "indexer_scripts": str(root / INDEXER_SCRIPTS_REL),
           "sources": {v: retired.get(v, []) for v in sources}}
    try:
        cp = subprocess.run([python, str(HERE / "pool_screen.py")], input=json.dumps(req),
                            text=True, capture_output=True, timeout=SCREEN_TIMEOUT)
        return json.loads(cp.stdout)
    except subprocess.TimeoutExpired:
        return {"error": f"pool screening did not answer within {SCREEN_TIMEOUT}s",
                "sources": {}}
    except Exception as exc:
        return {"error": f"pool screening failed: {type(exc).__name__}: {exc}",
                "sources": {}}


def pool_video(entry):
    """An `index.json` entry in the shape `host_show.judge()` reads - the
    indexer's own (`pool_sources.vet()`): the uploader is the channel."""
    return {"video_id": entry.get("id"), "title": entry.get("title") or "",
            "channel_title": entry.get("uploader") or "", "description": ""}


def host_judge(root, channel):
    """CF-0817: -> `judge(entry, topic)` -> Trend Hunter's host-show verdict
    (None: no host show) on one pool source for one topic, asked exactly as
    the Footage Indexer's pool reuse asks it (`pool_work_check.host_show_of`):
    no nature, `official` from the channel's footage_origin list, the topic's
    `title_ref`. Raises when the channel's list or the host-show config cannot
    be loaded - `Pool.load()` turns that into an error, never a quiet pass."""
    # Imported here: host_show imports fact_probe_topics, which imports this module.
    import footage_origin
    import host_show
    origin_cfg = footage_origin.load_config(channel, root=root)
    hs_cfg = host_show.load_config()

    def judge(entry, topic):
        video = pool_video(entry)
        return host_show.judge(video, nature=None,
                               official=bool(footage_origin.is_official(video, origin_cfg)),
                               title_ref=(topic or {}).get("title_ref") or {},
                               config=hs_cfg)
    return judge


class Pool:
    """The pool as this stage sees it. `entries`, `names`, `retired` and the
    host-show judge (`host_judge(entry, topic)`, CF-0817) are injectable so
    tests and the replay run on frozen data; without a judge no source is
    asked whether it is a host show."""

    def __init__(self, entries, names=None, retired=None, screener=None, error=None,
                 host_judge=None):
        self.entries = list(entries or [])
        self.names = dict(names or {})
        self.retired = dict(retired or {})
        self.screener = screener
        self.error = error
        self.host_judge = host_judge

    @classmethod
    def load(cls, root, channel):
        try:
            entries = load_index(root)
        except Exception as exc:
            return cls([], error=f"no pool index ({FOOTAGE_REL / INDEX_NAME}): "
                                 f"{type(exc).__name__}: {exc}")
        try:
            judge = host_judge(root, channel)
        except Exception as exc:
            return cls([], error=f"no host-show check for the pool (CF-0817): "
                                 f"{type(exc).__name__}: {exc}")
        return cls(entries, topic_names(root), retired_shots(root, channel),
                   screener=lambda vids, retired: screen(root, vids, retired),
                   host_judge=judge)

    def host_sieve(self, topic, matched):
        """CF-0817: -> (kept [(entry, by, verdict)], skipped [video_id], error).
        A refused host show is skipped; one whose verdict could not be had is
        skipped too - an unchecked source never earns a bonus."""
        if self.host_judge is None:
            return [(e, by, None) for e, by in matched], [], None
        kept, skipped, error = [], [], None
        for e, by in matched:
            try:
                verdict = self.host_judge(e, topic)
            except Exception as exc:
                error = f"host-show check failed: {type(exc).__name__}: {exc}"
                skipped.append(e["id"])
                continue
            if isinstance(verdict, dict) and verdict.get("refused"):
                skipped.append(e["id"])
                continue
            kept.append((e, by, verdict))
        return kept, skipped, error

    def matches(self, topic, before=None):
        """[(entry, by)] for this topic. `before` (ISO time) keeps only sources
        fetched earlier - the replay's view of the pool a past batch had."""
        phrases = phrases_of(topic)
        out = []
        for e in self.entries:
            if before and (e.get("fetched_at") or "") >= before:
                continue
            by = []
            title = normalise(e.get("title"))
            if any(has_phrase(p, title) for p in phrases):
                by.append("title")
            m = _NOTE.search(e.get("note") or "")
            if m:
                other = normalise(self.names.get((m.group(1), m.group(2))))
                if other and any(has_phrase(p, other) for p in phrases):
                    by.append("topic")
            if by:
                out.append((e, by))
        return out

    def coverage(self, topics, before=None):
        """{topic_id: pool record} for these topics, with one screening for
        the union of their matched sources."""
        sieved = {t.get("topic_id"): self.host_sieve(t, self.matches(t, before))
                  for t in topics}
        found = {tid: [(e, by) for e, by, _ in kept] for tid, (kept, _, _) in sieved.items()}
        vids = sorted({e["id"] for m in found.values() for e, _ in m})
        answer = {"sources": {}, "floor": None, "error": self.error}
        if vids and self.screener is not None:
            answer = self.screener(vids, self.retired) or answer
        floor = answer.get("floor") or POOL_DEPTH_FLOOR
        per = answer.get("sources") or {}
        measured_all = not answer.get("error")
        out = {}
        for t in topics:
            m = found.get(t.get("topic_id")) or []
            kept, skipped, hs_error = sieved.get(t.get("topic_id")) or ([], [], None)
            verdict_of = {e["id"]: v for e, _, v in kept}
            recs = [per.get(e["id"]) or {} for e, _ in m]
            measured = measured_all and all(r.get("usable") is not None for r in recs)
            usable = sum(r.get("usable") or 0 for r in recs) if measured else None
            if measured:
                coverage = min(1.0, usable / floor) if floor else 0.0
                coverage_by = "usable"
            else:
                coverage = min(1.0, len(m) / SOURCE_FLOOR)
                coverage_by = "sources"
            out[t.get("topic_id")] = {
                "rule": RULE,
                "phrases": phrases_of(t),
                "sources": len(m),
                "shots": sum(r.get("shots") or 0 for r in recs),
                "retired": sum(r.get("retired") or 0 for r in recs),
                "usable": usable,
                "measured": measured,
                "floor": floor,
                "coverage": round(coverage, 3),
                "coverage_by": coverage_by,
                "matched": [dict({"video_id": e["id"], "title": e.get("title"), "by": by,
                                  "usable": (per.get(e["id"]) or {}).get("usable")},
                                 **({"host_show": verdict_of[e["id"]].get("exception")}
                                    if verdict_of.get(e["id"]) else {}))
                            for e, by in m][:MATCHED_KEEP],
                "host_show_skipped": skipped,
                "host_show_error": hs_error,
                "error": answer.get("error"),
            }
        return out


def factor_of(coverage):
    return 1.0 + POOL_WEIGHT * max(0.0, min(1.0, float(coverage or 0.0)))


def rank_score(score, pool):
    """Hype x pool. A topic with no score keeps it (a negative / missing score
    is not multiplied into something that looks like a ranking)."""
    if score is None or score < 0:
        return score
    return round(score * factor_of((pool or {}).get("coverage")), 3)


def main(argv=None):
    """`pool_coverage.py <name> [<name> ...]` - what the pool holds for a title."""
    import argparse
    sys.path.insert(0, str(HERE))
    from _runlog import factory_root
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="+")
    # CF-0213: required - the retired shots are the channel's own, and a
    # default would read the first channel's for every other one.
    ap.add_argument("--channel", required=True,
                    help="channel id whose retired shots are left out (no default)")
    args = ap.parse_args(argv)
    pool = Pool.load(factory_root(), args.channel)
    topics = [{"topic_id": n, "title_ref": {"name": n}} for n in args.names]
    print(json.dumps(pool.coverage(topics), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
