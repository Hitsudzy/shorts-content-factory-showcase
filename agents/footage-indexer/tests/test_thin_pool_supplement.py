#!/usr/bin/env python3
"""CF-0338: a thin topic pool is added to from a supplement request.

The user's ruling of 2026-09-23 (`widows-bay`): when the topic's sources hold
no footage of the anchor's entity - "the actor's Emmy, and no frame of the
actor" - the pool is added to with the entity's highlights, trailers and other
work, fetched before the Video Editor. Trend Hunter searches; this stage takes
the request it writes and walks it through the same `ingest()` as any source.

Offline: fetch, index and fingerprint are stand-ins, and the pool depth is
measured over synthetic `shots.json` files in a temporary cache (the same
seam `test_pool_depth_floor.py` uses).
"""
import io
import json
import shutil
import sys
import tempfile
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import ingest_batch as ib           # noqa: E402
import pool_depth as pd             # noqa: E402

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0338-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
TOPIC = "example-film-2026-09-23-001"

# Real-shaped YouTube ids (11 characters); each stands for its own cut unless
# CUT says otherwise. USABLE is how many usable shots each one's index holds.
HELD = "hG2tH_gTvRI"
B, C, D = "BBBBBBBBBB1", "CCCCCCCCCC1", "DDDDDDDDDD1"
REUPLOAD = "RRRRRRRRRR1"      # a re-upload of HELD
LONG = "LLLLLLLLLL1"          # a 2-hour "trailer"
USABLE = {HELD: 10, B: 8, C: 12, D: 20, REUPLOAD: 10, LONG: 30}
CUT = {REUPLOAD: HELD}


class Cuts:
    @staticmethod
    def compare(a, b):
        return {"distance": 0.0 if a["cut"] == b["cut"] else 30.0,
                "offset_seconds": 0.0, "overlap_frames": 120, "kind": "cut"}

    @staticmethod
    def is_duplicate(cmp):
        return cmp["distance"] <= 12


def fingerprint(path):
    vid = Path(path).stem
    return {"kind": "cut", "cut": CUT.get(vid, vid)}


def measure(vid, record=None):
    sec = (record or {}).get("duration_seconds")
    return ib.Measured(float(sec) if sec else None, "candidate", None)


def synthetic_index(cache, vid):
    json.dump({"source": str(cache / f"{vid}.mp4"),
               "shots": [{"start": i * 4.0, "end": i * 4.0 + 3.0, "index": i,
                          "description": "x"} for i in range(USABLE[vid])]},
              open(cache / f"{vid}.shots.json", "w"))


class Fetcher:
    def __init__(self, cache, gone=()):
        self.cache, self.gone, self.calls = cache, set(gone), []

    def __call__(self, vid, note):
        self.calls.append(vid)
        if vid in self.gone:
            raise RuntimeError(f"ERROR: [youtube] {vid}: Video unavailable")
        return ib.FetchResult(str(self.cache / f"{vid}.mp4"), False)

    def index(self, path):
        synthetic_index(self.cache, Path(path).stem)


def seams(fetcher):
    return dict(fetch=fetcher, index=fetcher.index, fingerprint=fingerprint,
                sleep=lambda s: None, pause=0, is_cached=lambda vid: False,
                measure=measure)


def quiet(fn, *a, **kw):
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return fn(*a, **kw)
    finally:
        ib.source_fingerprint = real


def world(name, refused=False):
    """A batch whose first pass left TOPIC with one source, HELD."""
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    batch, cache = root / "batch", root / "cache"
    batch.mkdir(parents=True)
    cache.mkdir()
    synthetic_index(cache, HELD)
    pd.forget()
    json.dump({"channel": "example-film", "topics": [
        {"topic_id": TOPIC, "evidence": {"youtube_video_ids": [HELD]}}]},
        open(batch / "01-trend-hunter.json", "w"))
    json.dump({"results": [{"topic_id": TOPIC, "verdict": "clear"}],
               "reserve": []},
              open(batch / "02-compliance-checker.json", "w"))
    report = ib.build_report(
        batch, [{"video_id": HELD, "topic_id": TOPIC,
                 "path": str(cache / f"{HELD}.mp4")}], [],
        [ib.topic_skip(TOPIC, "no_second_source", "x")] if refused else [],
        [], {TOPIC: [HELD]}, depth_floor=0)
    ib.write_report(batch, report)
    return batch, cache


def cand(vid, entity="Sandra Birch", **kw):
    return {"video_id": vid, "entity": entity, "nature": "trailer",
            "duration_seconds": 150, **kw}


def request(cands, shots_wanted=15, **kw):
    return {"kind": ib.SUPPLEMENT_KIND, "topic_id": TOPIC,
            "reason_code": "pool_too_thin",
            "entities": [{"name": "Sandra Birch", "kind": "person"}],
            "shots_wanted": shots_wanted, "candidates": cands, **kw}


def run(batch, cache, *docs, gone=()):
    """`ingest_batch.py <batch> --supplement <files>`, offline."""
    reqdir = batch / "work" / "supplement-requests"
    reqdir.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs):
        path = reqdir / f"{i:02d}.json"
        if isinstance(doc, str):
            path.write_text(doc)
        else:
            json.dump(doc, open(path, "w"))
    fetcher = Fetcher(cache, gone)
    args = types.SimpleNamespace(supplement=[str(reqdir)], skip_index=False)
    lines = []
    quiet(ib.supplement_mode, batch, args, log=lines.append,
          depth_cache=cache, ceiling=None, **seams(fetcher))
    return json.load(open(batch / ib.REPORT_FILE)), fetcher, "\n".join(lines)


# ---------------------------------------------------------------------------
# The request

def test_a_request_without_an_entity_or_of_another_kind_is_refused():
    for bad in ({"kind": "other", "topic_id": TOPIC, "entities": ["x"]},
                {"kind": ib.SUPPLEMENT_KIND, "topic_id": TOPIC, "entities": []},
                {"kind": ib.SUPPLEMENT_KIND, "entities": ["x"]},
                {"kind": ib.SUPPLEMENT_KIND, "topic_id": TOPIC,
                 "entities": ["x"], "candidates": "abc"}):
        try:
            ib.read_supplement(bad)
        except ib.SupplementRefused:
            continue
        raise AssertionError(f"accepted {bad}")
    req = ib.read_supplement({"kind": ib.SUPPLEMENT_KIND, "topic_id": TOPIC,
                              "entities": ["Sandra Birch"]})
    assert req["candidates"] == [] and req["shots_wanted"] is None
    assert req["max_attempts"] == ib.SUPPLEMENT_MAX_ATTEMPTS


def test_the_request_checks_host_entity_and_upstream_drops():
    req = ib.read_supplement(request([
        cand("https://vimeo.com/1"), cand(B, entity="Nora Kingsley"),
        cand(C, drop_reason="unofficial_source"), cand(HELD), cand(D),
        cand(D)]))
    ok, bad = ib.supplement_candidates(req, tried=[HELD])
    assert [c["video_id"] for c in ok] == [D]
    assert [(r["video_id"], r["reason_code"]) for r in bad] == [
        ("https://vimeo.com/1", ib.SUPPLEMENT_REJECT_NOT_YOUTUBE),
        (B, ib.SUPPLEMENT_REJECT_NO_ENTITY),
        (C, ib.SUPPLEMENT_REJECT_DROPPED),
        (HELD, ib.SUPPLEMENT_REJECT_TRIED)]


# ---------------------------------------------------------------------------
# The walk

def test_the_pool_grows_until_the_missing_shots_are_there_and_stops():
    batch, cache = world("grows")
    report, fetcher, log = run(batch, cache, request([cand(B), cand(C), cand(D)]))
    assert fetcher.calls == [B, C], fetcher.calls      # 10 -> 18 -> 30 >= 25
    assert report["sources_by_topic"][TOPIC] == [HELD, B, C]
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["outcome"] == "sources" and e["new_sources"] == [B, C]
    assert e["shots_before"]["usable_shots"] == 10
    assert e["shots_after"]["usable_shots"] == 30
    assert e["shots_added"] == 20 and e["covers_shortfall"] is True
    added = [f for f in report["fetched"] if f.get("supplement")]
    assert [f["supplement"]["entity"] for f in added] == ["Sandra Birch"] * 2
    assert "usable shots 10 -> 30" in log


def test_without_a_shot_count_one_new_source_is_the_answer():
    batch, cache = world("one-source")
    report, fetcher, _ = run(batch, cache,
                             request([cand(B), cand(C)], shots_wanted=None))
    assert fetcher.calls == [B]
    assert report["sources_by_topic"][TOPIC] == [HELD, B]


def test_a_reupload_of_a_held_source_is_an_alias_not_more_footage():
    batch, cache = world("reupload")
    report, fetcher, _ = run(batch, cache, request([cand(REUPLOAD), cand(B)],
                                                   shots_wanted=None))
    assert fetcher.calls == [REUPLOAD, B]
    assert report["sources_by_topic"][TOPIC] == [HELD, B]
    assert [a["video_id"] for a in report["aliases"]] == [REUPLOAD]
    assert report[ib.SUPPLEMENT_KEY][0]["aliases"] == [REUPLOAD]


def test_the_length_ceiling_holds_for_a_supplement_too():
    batch, cache = world("ceiling")
    report, fetcher, _ = run(batch, cache, request(
        [cand(LONG, duration_seconds=7200), cand(B)], shots_wanted=None))
    assert LONG not in fetcher.calls
    assert [(f["video_id"], f["reason_code"]) for f in report["failed"]] == [
        (LONG, ib.TOO_LONG_CODE)]


def test_a_supplement_that_finds_nothing_never_refuses_the_topic():
    batch, cache = world("nothing")
    report, fetcher, _ = run(batch, cache, request([cand(B)]), gone=[B])
    assert report["skipped_topics"] == []
    assert report["sources_by_topic"][TOPIC] == [HELD]
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["outcome"] == "no_new_source" and e["shots_added"] == 0
    assert e["failed"] == [{"video_id": B, "reason_code": "fetch_failed"}]


def test_a_topic_this_stage_refused_is_not_walked():
    batch, cache = world("refused", refused=True)
    report, fetcher, _ = run(batch, cache, request([cand(B)]))
    assert fetcher.calls == []
    assert report[ib.SUPPLEMENT_KEY][0]["outcome"] == "topic_refused"


def test_the_same_request_twice_is_walked_once():
    batch, cache = world("twice")
    run(batch, cache, request([cand(B), cand(C)]))
    report, fetcher, log = run(batch, cache, request([cand(B), cand(C)]))
    assert fetcher.calls == []
    assert len(report[ib.SUPPLEMENT_KEY]) == 1
    assert report["sources_by_topic"][TOPIC] == [HELD, B, C]
    assert "already answered" in log


def test_an_unreadable_request_is_named_and_the_others_still_run():
    batch, cache = world("unreadable")
    report, fetcher, log = run(batch, cache, "{not json",
                               request([cand(B)], shots_wanted=None))
    assert fetcher.calls == [B]
    assert "SUPPLEMENT refused" in log and "1 unreadable" in log


def test_the_cli_carries_the_flag():
    src = (HERE.parent / "scripts" / "ingest_batch.py").read_text()
    assert '"--supplement"' in src and "= supplement_mode(batch, args," in src


if __name__ == "__main__":
    fails = total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                fails += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{total - fails}/{total} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if fails else 0)
