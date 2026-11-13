#!/usr/bin/env python3
"""CF-0325: the pool sources Trend Hunter matched to a topic, counted as the
topic's own before anything is downloaded - once they pass "is it the work?".

The failure this closes (grill of 2026-09-22, Q4, and the replay of CF-0325
part 1): the indexer fetched every topic's footage from scratch while
`shared/footage` already held it. Over the frozen batches 15 topics were lost
to `no_second_source` / `pool_too_thin`, and for 11 of them the pool already
had the footage - Wren Hollow was refused `pool_too_thin` twice with 195 and
215 usable shots of the franchise sitting in the pool. Part 1 (Trend Hunter,
`scripts/pool_coverage.py`) writes what the pool holds for a topic onto the
topic itself, `topics[].pool.matched[]`; this module is the half that makes
the indexer *use* it: a matched source that passes the checks below is
registered to the topic before the CF-0129 walk starts (`ingest(pooled=...)`),
so it counts toward the two-source floor and toward the CF-0304 depth floor,
and the walk downloads only what is still missing.

The pool's match is by title, and a title can be wrong - so a source is
counted only after the checks the project already has for "is this the
topic's work", asked in this order, and a source that fails one is not counted
and is written down with the check and the reason:

  media      the file and its finished index are still in the cache
             (`shared/footage/<id>.mp4` + `<id>.shots.json`): the pool is
             transient (CF-0358) and a source whose media is gone cannot be
             cut. Code `pool_media_gone`.
  work       Trend Hunter's own candidate checks - CF-0272 `wrong_work`,
             CF-0309 `not_the_works_footage`, CF-0297 `unofficial_source` -
             and this task's `other_installment` (named only by the
             franchise stem: an Vanguards: Endgame trailer for Vanguards:
             Doomsday, batch 2026-09-29T0705Z). Run by `pool_work_check.py`
             in its own process under Trend Hunter's venv. A source nobody
             could check is **not counted** (`pool_not_checked`): an
             unverified source is exactly what this module exists to keep
             from being counted.
  sieve      the CF-0299 sieve's verdict over the source's own shot flags
             (`source_sieve.judge`): a source the describer found to be mostly
             somebody else's material is refused here with the sieve's own
             code (`source_foreign`). Since CF-0435 burned-in text no longer
             refuses a source whole - its burned shots stay out one by one and
             the source is counted. A source not yet sieved is counted - the
             batch's sieve pass (CF-0359 backfill) answers for it like for any
             other source of the batch.

  host_show  CF-0817: somebody else's podcast, interview or talk show is not
             backdrop under our voice (the user, 2026-10-20, after a viewer
             wrote under vanguards-doomsday). Asked of a source the work check
             let through, by the same process and Trend Hunter's own
             `host_show.judge()` over the pool title and uploader (the
             Fallon interview `ZLXL1L0TfsI` for Delver, Zenith's
             "Countdown to Vanguards: Doomsday Official Podcast"), with its two
             exceptions read off the topic's `title_ref`: the topic is about
             the person the title names (`subject_is_guest`), or the topic is
             the show (`topic_is_the_show`). Trend Hunter's own verdict on
             the same id - a candidate it dropped or kept with `host_show` -
             is read too, and a refusal there refuses here. Code `host_show`,
             with the verdict and its signals on the record. A verdict with
             no host-show answer at all is "not checked" (never counted); a
             pool entry with no title or uploader that the lists cannot call
             a host show is counted as before and marked `host_show_unknown`
             (counted per topic in the block).

A source refused for what it *is* (every code but the two above that say
nothing about the video) is also barred from this topic's CF-0129 walk: when
Trend Hunter offered the same id as a candidate (it did, for Doomsday), the
walk would otherwise admit through the front door what the check just turned
away at the back.

Nothing here is ever a refusal of a topic, and nothing here downloads: with no
`pool` on the topic, or `--no-pool`, the stage is exactly what it was.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

RULE = "CF-0325"
POOL_KEY = "pool"                    # topics[].pool, written by Trend Hunter
BLOCK_KEY = "pool_sources"           # the block of 01b-footage-index.json
FETCHED_MARK = "from_pool"           # on fetched[] / aliases[] records

COUNTED = "counted"
REFUSED = "refused"
ALIASED = "aliased"                  # a re-upload of a source the topic holds
NOT_WALKED = "not_walked"            # the topic was not fetched at all (CF-0265)

MEDIA_GONE = "pool_media_gone"
NOT_CHECKED = "pool_not_checked"
HOST_SHOW = "host_show"              # CF-0817, Trend Hunter's reason_code
                                     # (= ingest_batch.HOST_SHOW_CODE)
HOST_SHOW_UNKNOWN = "host_show_unknown"
CHECK_MEDIA, CHECK_WORK, CHECK_SIEVE = "media", "work", "sieve"
CHECK_HOST_SHOW = "host_show"
# The codes that say nothing about the video itself - the source is not
# counted, and still not barred from the walk.
NOT_ABOUT_THE_VIDEO = (MEDIA_GONE, NOT_CHECKED)

CHECK_TIMEOUT = 120
TREND_HUNTER_REL = Path("agents") / "trend-hunter"
REFUSED_LINE = "POOL {vid} not counted for {tid} ({code}, {check}): {reason}"
COUNTED_LINE = "POOL {tid} counts {n} pool source(s) before any download: {ids}"


def matched_of(topic):
    """`topics[].pool.matched[]` as a list of dicts with a `video_id`. A topic
    with no pool record (a batch before CF-0325, or a hunter whose pool read
    failed) has none, which is "nothing to count", never an error."""
    pool = (topic or {}).get(POOL_KEY)
    rows = pool.get("matched") if isinstance(pool, dict) else None
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else ():
        if isinstance(r, dict) and isinstance(r.get("video_id"), str) \
                and r["video_id"] not in seen:
            seen.add(r["video_id"])
            out.append(r)
    return out


def trend_hunter_host_show(topic, vid):
    """CF-0817: Trend Hunter's own `host_show` verdict on this id for this
    topic, when it judged it as a candidate - kept under an exception in
    `evidence.footage_candidates[]`, or dropped with `reason_code: host_show`
    in `evidence.footage_candidates_dropped[]`. None when it said nothing."""
    ev = (topic or {}).get("evidence") or {}
    for key in ("footage_candidates_dropped", "footage_candidates"):
        for r in ev.get(key) or ():
            if isinstance(r, dict) and r.get("video_id") == vid:
                v = r.get(HOST_SHOW)
                if isinstance(v, dict):
                    return v
                if r.get("reason_code") == HOST_SHOW:
                    return {"refused": True, "exception": None, "signals": [],
                            "reason": r.get("reason") or "a host show (Trend Hunter)"}
    return None


def _pool_entries(cache):
    """{video_id: index.json entry} - the uploader is what the checks read as
    the channel. Never raises."""
    try:
        doc = json.load(open(Path(cache) / "index.json")) or {}
    except Exception:
        return {}
    return {e.get("id"): e for e in doc.get("entries") or [] if isinstance(e, dict)}


def trend_hunter_python(root):
    venv = Path(root) / TREND_HUNTER_REL / ".venv" / "bin" / "python"
    return str(venv if venv.exists() else sys.executable)


def run_work_check(payload, root, channel=None, channel_root=None, timeout=CHECK_TIMEOUT):
    """`pool_work_check.py` in its own process. Never raises.

    CF-0631: `channel` is the batch's channel - its official footage channels
    are its own list under `channel_root` (default `root`, the factory root
    Trend Hunter sits in). No channel is an `error` answer, never a guess."""
    req = {"trend_hunter_scripts": str(Path(root) / TREND_HUNTER_REL / "scripts"),
           "channel": channel, "factory_root": str(channel_root or root),
           "topics": payload}
    try:
        cp = subprocess.run([trend_hunter_python(root), str(SCRIPTS / "pool_work_check.py")],
                            input=json.dumps(req), text=True, capture_output=True,
                            timeout=timeout)
        ans = json.loads(cp.stdout)
        if not isinstance(ans, dict):
            raise ValueError("not an object")
        return ans
    except subprocess.TimeoutExpired:
        return {"error": f"the work check did not answer within {timeout}s", "topics": {}}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"the work check failed: {type(exc).__name__}: {exc}", "topics": {}}


def sieve_verdict(shots_path):
    """The CF-0299 sieve's answer over one index, or None when the index cannot
    be read. Imported late: `source_sieve` imports `ingest_batch`, which
    imports this module."""
    import source_sieve
    try:
        index = json.load(open(shots_path))
    except Exception:
        return None
    return source_sieve.judge(index)


def vet(topics, cache, root=None, checker=None, judge=sieve_verdict, log=print,
        channel=None):
    """{topic_id: {"matched": n, "counted": [rec], "refused": [rec],
    "error": str|None}} for every topic that carries a pool match.

    `channel` is the batch's channel (CF-0631): the work check reads its
    official footage channels; without one every source is "not checked".
    `checker(payload) -> {"error", "topics": {tid: {vid: verdict}}}` and
    `judge(shots_path) -> sieve record | None` are the seams the tests use.
    """
    cache = Path(cache)
    entries = _pool_entries(cache)
    todo = [(t, matched_of(t)) for t in topics or [] if t.get("topic_id")]
    todo = [(t, m) for t, m in todo if m]
    if not todo:
        return {}
    payload = []
    for t, m in todo:
        payload.append({"topic_id": t["topic_id"], "title_ref": t.get("title_ref") or {},
                        "sources": [{"video_id": r["video_id"],
                                     "title": r.get("title")
                                     or (entries.get(r["video_id"]) or {}).get("title"),
                                     "channel_title": (entries.get(r["video_id"]) or {})
                                     .get("uploader")} for r in m]})
    if checker is None:
        answer = run_work_check(payload, root or cache.parent.parent, channel=channel)
    else:
        answer = checker(payload)
    error = (answer or {}).get("error")
    verdicts = (answer or {}).get("topics") or {}
    out = {}
    for t, m in todo:
        tid = t["topic_id"]
        counted, refused = [], []
        for r in m:
            vid = r["video_id"]
            mp4, shots = cache / f"{vid}.mp4", cache / f"{vid}.shots.json"
            rec = {"video_id": vid,
                   "title": r.get("title") or (entries.get(vid) or {}).get("title"),
                   "by": list(r.get("by") or []), "usable": r.get("usable"),
                   "path": str(mp4), "outcome": COUNTED, "check": None,
                   "reason_code": None, "reason": None}

            def refuse(code, check, reason):
                rec.update(outcome=REFUSED, reason_code=code, check=check, reason=reason)
                refused.append(rec)
                log(REFUSED_LINE.format(vid=vid, tid=tid, code=code, check=check,
                                        reason=reason))

            if not mp4.exists() or not shots.exists():
                gone = [p.name for p in (mp4, shots) if not p.exists()]
                refuse(MEDIA_GONE, CHECK_MEDIA,
                       f"{', '.join(gone)} no longer in the cache (the pool is transient, "
                       f"CF-0358) - nothing to cut from")
                continue
            v = (verdicts.get(tid) or {}).get(vid)
            if not isinstance(v, dict):
                refuse(NOT_CHECKED, CHECK_WORK,
                       f"nobody could say whether it is the topic's work "
                       f"({error or 'no verdict for it'}) - an unchecked pool source "
                       f"is never counted ({RULE})")
                continue
            if not v.get("ok"):
                rec["rule"] = v.get("rule")
                refuse(v.get("reason_code") or v.get("rule") or "wrong_work", CHECK_WORK,
                       v.get("reason") or "not the topic's work")
                continue
            s = judge(shots) if judge else None
            # CF-0817: somebody else's host show. Trend Hunter's verdict on
            # the same id as a candidate first (it saw the nature), then the
            # one the work check asked of the pool's title and uploader.
            if "host_show" not in v:
                refuse(NOT_CHECKED, CHECK_HOST_SHOW,
                       f"no host-show verdict for it ({error or 'the check gave none'}) "
                       f"- a pool source is never counted unchecked (CF-0817)")
                continue
            hs = trend_hunter_host_show(t, vid)
            if not (isinstance(hs, dict) and hs.get("refused")):
                hs = v.get("host_show") or hs
            if isinstance(hs, dict):
                rec[HOST_SHOW] = hs
                if hs.get("refused"):
                    refuse(HOST_SHOW, CHECK_HOST_SHOW, hs.get("reason") or "a host show")
                    continue
            if v.get(HOST_SHOW_UNKNOWN):
                rec[HOST_SHOW_UNKNOWN] = list(v[HOST_SHOW_UNKNOWN])
            s = judge(shots) if judge else None
            if isinstance(s, dict) and s.get("verdict") == "refused":
                refuse(s.get("reason_code"), CHECK_SIEVE, s.get("reason") or "")
                continue
            if isinstance(s, dict):
                rec["sieve"] = s.get("verdict")
            counted.append(rec)
        out[tid] = {"matched": len(m), "counted": counted, "refused": refused,
                    "error": error}
    if error and HOST_SHOW_RULE_TAG in str(error):
        # CF-0817: loud - the classifier is missing, so nothing was counted.
        log(f"POOL host-show check unavailable, no pool source counted: {error}",
            file=sys.stderr)
    return out


HOST_SHOW_RULE_TAG = "CF-0817"


def stamp_fetched(fetched, vetted):
    """CF-0817: put the pool check's host-show marks on the `fetched[]`
    records of the pool sources it counted (`from_pool: true`) - an exception
    it was kept under (`host_show`), or the metadata it lacked
    (`host_show_unknown`) - so the sieve stage reads them off the report."""
    marks = {}
    for tid, v in (vetted or {}).items():
        for r in v["counted"]:
            m = {k: r[k] for k in (HOST_SHOW, HOST_SHOW_UNKNOWN) if r.get(k)}
            if m:
                marks[(tid, r["video_id"])] = m
    for f in fetched or ():
        m = marks.get((f.get("topic_id"), f.get("video_id")))
        if m and f.get(FETCHED_MARK):
            f.update(m)
    return fetched


def pooled_paths(vetted):
    """{topic_id: [(video_id, path)]} of the counted sources - `ingest(pooled=)`."""
    return {tid: [(r["video_id"], r["path"]) for r in v["counted"]]
            for tid, v in (vetted or {}).items() if v["counted"]}


def barred_ids(vetted):
    """{topic_id: [video_id]} the walk must not admit for this topic."""
    out = {}
    for tid, v in (vetted or {}).items():
        ids = [r["video_id"] for r in v["refused"]
               if r["reason_code"] not in NOT_ABOUT_THE_VIDEO]
        if ids:
            out[tid] = ids
    return out


def report_block(vetted, sources_by_topic, aliases):
    """The `pool_sources` block of `01b-footage-index.json`: per topic, which
    pool sources were counted, which were refused and why, which turned out to
    be a re-upload of another one (CF-0080)."""
    topics = {}
    counted = refused = host_show = host_unknown = 0
    for tid, v in (vetted or {}).items():
        held = (sources_by_topic or {}).get(tid)
        alias_of = {a["video_id"]: a.get("alias_of") for a in aliases or ()
                    if a.get("topic_id") == tid and a.get(FETCHED_MARK)}
        rows = []
        for r in v["counted"]:
            r = dict(r)
            if held is None:
                r["outcome"] = NOT_WALKED
            elif r["video_id"] in alias_of:
                r["outcome"] = ALIASED
                r["alias_of"] = alias_of[r["video_id"]]
            elif r["video_id"] not in held:
                r["outcome"] = NOT_WALKED
            rows.append(r)
        n = sum(1 for r in rows if r["outcome"] == COUNTED)
        counted += n
        refused += len(v["refused"])
        hosts = [r["video_id"] for r in v["refused"] if r["reason_code"] == HOST_SHOW]
        unknown = [r["video_id"] for r in v["counted"] if r.get(HOST_SHOW_UNKNOWN)]
        host_show += len(hosts)
        host_unknown += len(unknown)
        topics[tid] = {"matched": v["matched"], "counted": n,
                       "sources": rows + [dict(r) for r in v["refused"]],
                       HOST_SHOW: hosts, HOST_SHOW_UNKNOWN: len(unknown),
                       "error": v.get("error")}
    return {
        "rule": RULE,
        "counted": counted,
        "refused": refused,
        HOST_SHOW: host_show,
        HOST_SHOW_UNKNOWN: host_unknown,
        "topics": topics,
        "note": ("Sources Trend Hunter matched to the topic in shared/footage "
                 "(topics[].pool.matched), counted as the topic's own before the "
                 "CF-0129 walk - toward the two-source and the CF-0304 depth floor - "
                 "once they passed the checks media -> work (CF-0272/0309/0297 and "
                 "other_installment) -> host_show (CF-0817: somebody else's podcast, "
                 "interview or talk show; `host_show_unknown` counts the counted "
                 "sources whose pool entry had no title or uploader) -> sieve "
                 "(CF-0299). `outcome: refused` names the "
                 "check and the reason; a source refused for what it is is also barred "
                 "from the topic's walk. Counted sources are in fetched[] with "
                 "`from_pool: true` and were not downloaded or indexed again."),
    }
