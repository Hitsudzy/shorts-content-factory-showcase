#!/usr/bin/env python3
"""CF-0876: the channel's memory of works refused with `pool_too_thin` at
zero clean shots.

Mudform was refused `pool_too_thin` with 0 usable shots of 102 weak in four
ExampleFilm batches running (24-26.10), with the same three sources each
time. These tests hold the memory to what the task asks: such a refusal of
the last N days (the channel's `scope.thin_pool_memory_days`, 3 by default)
holds the work back; a source the pool took in since lets it through; an
older refusal does not hold; a work with one clean shot or more - or with no
source indexed at all - is not remembered. The batches are stand-ins written
into a temp root; the pool is a stand-in function - no live batch, pool or
channel is read.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

from _tmproot import tmp_root  # noqa: E402
import thin_pool_memory as tpm  # noqa: E402

TMP = tmp_root("th-thinpool-")
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
CHANNEL = "example-film"
_N = [0]


def root():
    _N[0] += 1
    base = TMP / f"root-{_N[0]}"
    base.mkdir()
    return base


def write_batch(base, batch, refused, channel=CHANNEL):
    """One earlier batch on disk: `refused` is [(topic_id, name, usable,
    weak, [video ids], matched pool ids)] - each a `pool_too_thin` row in 03,
    its measure in 01b and its topic in 01."""
    d = base / "pipeline" / channel / batch
    d.mkdir(parents=True)
    topics, depth, skipped, by_topic = [], [], [], {}
    for tid, name, usable, weak, vids, matched in refused:
        topics.append({"topic_id": tid, "title_ref": {"name": name, "kind": "work"},
                       "pool": {"sources": len(matched),
                                "matched": [{"video_id": v} for v in matched],
                                "host_show_skipped": []}})
        depth.append({"topic_id": tid, "sources": len(vids), "usable_shots": usable,
                      "weak_shots": weak,
                      "per_source": [{"video_id": v, "usable_shots": 0} for v in vids]})
        by_topic[tid] = list(vids)
        skipped.append({"topic_id": tid, "reason_code": "pool_too_thin", "stage": "scripts",
                        "reason": f"{usable} usable shot(s)", "usable_shots": usable})
    (d / tpm.HUNTER_FILE).write_text(json.dumps({"channel": channel, "topics": topics,
                                                 "skipped_topics": []}))
    (d / tpm.INDEX_FILE).write_text(json.dumps({"pool_depth": {"topics": depth},
                                                "sources_by_topic": by_topic}))
    (d / tpm.RESEARCHER_FILE).write_text(json.dumps({"skipped": skipped, "scripts": []}))
    return d


def pool(mapping):
    """A stand-in for the shared pool's matcher: {name: {video id: batch}}."""
    def ids(topic):
        return dict(mapping.get((topic.get("title_ref") or {}).get("name"), {}))
    return ids


MUDFORM = ("t-001", "Mudform", 0, 102, ["OGO4Mqvo3jI", "ObJuQsYq09o", "z4BT5bpVl5s"],
            ["OGO4Mqvo3jI", "ObJuQsYq09o", "z4BT5bpVl5s", "qWHFW8luMt8"])


def load(base, days=None, batch="2026-10-27T0840Z", pool_ids=None, now=NOW):
    config = {} if days is None else {"scope": {tpm.DAYS_KEY: days}}
    return tpm.load(base, CHANNEL, config, now=now, batch=batch,
                    pool_ids=pool_ids or pool({}))


def test_the_days_are_the_channels_and_three_by_default():
    assert tpm.days_of({}) == (3, "default", None)
    assert tpm.days_of({"scope": {"thin_pool_memory_days": 5}})[:2] == (5, "channel")
    days, origin, note = tpm.days_of({"scope": {"thin_pool_memory_days": -1}})
    assert (days, origin) == (3, "default") and "thin_pool_memory_days" in note
    # the no-fact memory still reads its own key
    import no_fact_memory as nfm
    assert nfm.days_of({"scope": {"thin_pool_memory_days": 9}}) == (3, "default", None)


def test_a_work_refused_at_zero_clean_shots_is_held_back_by_its_name():
    base = root()
    write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    mem = load(base)
    entry = mem.hit({"topic_id": "new-1", "title_ref": {"name": "Mudform"}})
    assert entry is not None and entry["batch"] == "2026-10-26T1514Z"
    assert entry["weak_shots"] == 102 and entry["usable_shots"] == 0
    # every source the batch had: indexed, registered, matched in the pool
    assert entry["video_ids"] == sorted(set(MUDFORM[4]) | set(MUDFORM[5]))
    # the key is the work's, as the no-fact memory keys it - not the headline
    assert mem.hit({"name": "mudform"}) is not None
    assert mem.hit({"title_ref": {"name": "Mudform 2"}}) is None
    assert mem.block()["live_entries"] == 1 and mem.block()["batches_read"] == 1


def test_a_work_with_one_clean_shot_or_no_source_at_all_is_not_remembered():
    base = root()
    write_batch(base, "2026-10-26T1514Z", [
        ("t-1", "Tulsa King", 1, 40, ["a1", "a2"], ["a1"]),
        ("t-2", "Spotify", 0, 0, [], []),
    ])
    mem = load(base)
    assert mem.live == {}
    assert mem.hit({"title_ref": {"name": "Tulsa King"}}) is None
    assert mem.hit({"title_ref": {"name": "Spotify"}}) is None


def test_the_gates_number_wins_and_the_measure_is_the_fallback():
    base = root()
    d = write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    doc = json.loads((d / tpm.RESEARCHER_FILE).read_text())
    doc["skipped"][0].pop("usable_shots")
    (d / tpm.RESEARCHER_FILE).write_text(json.dumps(doc))
    assert load(base).hit({"title_ref": {"name": "Mudform"}}) is not None
    # another loss of the same work is not this memory's
    doc["skipped"][0]["reason_code"] = "plan_unassembled"
    (d / tpm.RESEARCHER_FILE).write_text(json.dumps(doc))
    assert load(base).live == {}


def test_a_refusal_older_than_the_days_holds_nothing_and_zero_turns_it_off():
    base = root()
    write_batch(base, "2026-10-23T0840Z", [MUDFORM])
    assert load(base).hit({"title_ref": {"name": "Mudform"}}) is None       # 4 days ago
    assert load(base, days=5).hit({"title_ref": {"name": "Mudform"}}) is not None
    write_batch(base, "2026-10-26T0841Z", [MUDFORM])
    off = load(base, days=0)
    assert off.live == {} and off.read == []


def test_the_batch_being_run_is_not_read():
    base = root()
    write_batch(base, "2026-10-27T0840Z", [MUDFORM])
    assert load(base, batch="2026-10-27T0840Z").live == {}
    assert load(base, batch="2026-10-27T1500Z").hit(
        {"title_ref": {"name": "Mudform"}}) is not None


def test_a_new_source_in_the_pool_lets_the_work_through():
    base = root()
    write_batch(base, "2026-10-25T1819Z", [MUDFORM])
    write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    same = {"Mudform": {v: "2026-10-24T0840Z" for v in MUDFORM[5]}}
    held = load(base, pool_ids=pool(same))
    assert held.hit({"title_ref": {"name": "Mudform"}}) is not None
    assert held.live[" mudform "]["refusals"] == ["2026-10-25T1819Z", "2026-10-26T1514Z"]
    # a source one of the refusing batches fetched (and its sieve dropped) is not new
    sieved = dict(same["Mudform"], Xw000000001="2026-10-25T1819Z")
    assert load(base, pool_ids=pool({"Mudform": sieved})).hit(
        {"title_ref": {"name": "Mudform"}}) is not None
    # a trailer the pool took in since - for this work or another topic - is
    grown = dict(same["Mudform"], NEWtrailer01="2026-10-27T0200Z", NEWfanedit2=None)
    mem = load(base, pool_ids=pool({"Mudform": grown}))
    assert mem.hit({"topic_id": "t-9", "title_ref": {"name": "Mudform"}}) is None
    assert mem.block()["released"] == [{"name": "Mudform", "topic_id": "t-9",
                                        "remembered_batch": "2026-10-26T1514Z",
                                        "new_sources": ["NEWfanedit2", "NEWtrailer01"]}]


def test_an_unreadable_pool_lets_nobody_through_and_a_cut_list_asks_for_a_count():
    base = root()
    write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    assert load(base, pool_ids=lambda topic: None).hit(
        {"title_ref": {"name": "Mudform"}}) is not None
    # the remembered matched list was cut short (pool.sources 20, 4 listed): an
    # id not on it is new only when the pool holds more than the 20 it held
    d = base / "pipeline" / CHANNEL / "2026-10-26T1514Z"
    doc = json.loads((d / tpm.HUNTER_FILE).read_text())
    doc["topics"][0]["pool"]["sources"] = 20
    (d / tpm.HUNTER_FILE).write_text(json.dumps(doc))
    twenty = {f"v{i:02d}": None for i in range(20)}
    assert load(base, pool_ids=pool({"Mudform": twenty})).hit(
        {"title_ref": {"name": "Mudform"}}) is not None
    twenty_one = dict(twenty, v20=None)
    assert load(base, pool_ids=pool({"Mudform": twenty_one})).hit(
        {"title_ref": {"name": "Mudform"}}) is None


def test_the_row_of_a_held_work_is_a_pool_too_thin_before_scoring():
    base = root()
    write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    mem = load(base)
    topic = {"topic_id": "t-5", "title_ref": {"name": "Mudform", "kind": "work"}}
    row = tpm.remembered_refusal(topic, mem.hit(topic), mem.days)
    assert row["reason_code"] == "pool_too_thin" and row["stage"] == "trend-hunter"
    assert row["before_scoring"] is True and row["topic_id"] == "t-5"
    assert row["thin_pool_memory"]["batch"] == "2026-10-26T1514Z"
    assert "CF-0876" in row["reason"] and "0 clean shots" in row["reason"]


def test_the_cli_prints_the_memory():
    import contextlib
    import io
    base = root()
    write_batch(base, "2026-10-26T1514Z", [MUDFORM])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert tpm.main([CHANNEL, "--root", str(base), "--days", "400", "--json"]) == 0
    doc = json.loads(out.getvalue())
    assert [e["name"] for e in doc["live"]] == ["Mudform"]


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
