#!/usr/bin/env python3
"""CF-0914: `scripts/vendor_feed_replay.py` replays the vendor-feed path on
batch records - a stand-in factory root in a temp directory, a stand-in list
and a saved feed; nothing leaves the machine and no live record is read.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import test_vendor_feed as tf  # noqa: E402  - the stand-in list and feeds
import vendor_feed_replay as vr  # noqa: E402

REASON = ("no fact: wikipedia answered 'no_article' (article: -); searched "
          "wikipedia=no_article(0), rss_pool=ok(0), vendor_page={}(0)[x]; 0 candidate(s)")


def skipped(tid, title, outcome="no_link", memory=False):
    rec = {"topic_id": tid, "reason_code": "no_fact", "reason": REASON.format(outcome),
           "title": title, "fact_probe": {"asked": {"name": title}, "source": "wikipedia"}}
    if memory:
        rec["fact_probe"] = {"source": "no_fact_memory"}
    return rec


def make_root(tmp):
    batch = Path(tmp) / "pipeline" / "somechannel" / "2026-11-02T0838Z"
    (batch / "work").mkdir(parents=True)
    (batch / "01-trend-hunter.json").write_text(json.dumps({"skipped_topics": [
        skipped("t-1", "GM Smart Driver"),
        skipped("t-2", "GM Ultium battery"),
        skipped("t-3", "Intel 18A"),
        skipped("t-4", "Apple HomeView"),
        skipped("t-5", "Starlink Ukraine"),
        skipped("t-6", "GM Smart Driver", memory=True),           # the memory's repeat
        skipped("t-7", "OpenAI AI compute campuses", outcome="closed"),   # not a refusal here
    ]}))
    lead = {"title": "GM to pay $220 million after selling customer Smart Driver data",
            "link": tf.LEAD}
    (batch / "work" / "rss.json").write_text(json.dumps({"entries": [
        dict(lead, summary="A settlement.", feed_url="https://arstechnica.com/feed/")]}))
    (batch / "work" / "candidate-pool.json").write_text(json.dumps({"candidates": [
        {"name": "GM Smart Driver", "topic_id": "t-1", "headlines": [lead]},
        {"name": "GM Ultium battery", "topic_id": "t-2",
         "headlines": [{"title": "GM shows its Ultium battery", "link": tf.LEAD + "u"}]},
        {"name": "Intel 18A", "topic_id": "t-3",
         "headlines": [{"title": "Intel ships 18A chips", "link": tf.LEAD + "i"}]},
        {"name": "Apple HomeView", "topic_id": "t-4",
         "headlines": [{"title": "Apple's HomeView could add cameras", "link": tf.LEAD + "a"}]},
    ]}))
    saved = Path(tmp) / "gm.xml"
    saved.write_text(tf.GM_RSS)
    return batch.parent, {tf.GM_FEED: str(saved)}


def test_the_replay_sorts_the_refused_topics_by_what_the_path_would_do():
    with tempfile.TemporaryDirectory() as tmp:
        channel_dir, feeds = make_root(tmp)
        rows = vr.replay([channel_dir / "2026-11-02T0838Z"], tf.SOURCES, vr.load_saved(feeds))
    now = {r["title"]: r["now"] for r in rows}
    assert now == {"GM Smart Driver": "feed_match", "GM Ultium battery": "feed_no_match",
                   "Intel 18A": "named_unindexed", "Apple HomeView": "named_closed",
                   "Starlink Ukraine": "unnamed"}, now
    gm = next(r for r in rows if r["title"] == "GM Smart Driver")
    assert gm["detail"] == [tf.GM_POST] and gm["was"] == "no_link"
    assert vr.summary(rows)["refused"] == 5


def test_an_unsaved_index_is_feed_unsaved_and_assumed_rows_join_the_list():
    with tempfile.TemporaryDirectory() as tmp:
        channel_dir, _feeds = make_root(tmp)
        sources = vr.with_rows(tf.SOURCES, [tf.outlet("intel", ["intel.com"], "allowed",
                                                       newsroom=["https://intel.com/news/feed/"])])
        rows = vr.replay([channel_dir / "2026-11-02T0838Z"], sources, {})
    now = {r["title"]: r["now"] for r in rows}
    assert now["Intel 18A"] == "feed_unsaved" and now["GM Smart Driver"] == "feed_unsaved"
    assert len([r for r in sources["tiers"]["1"] if r["id"] == "intel"]) == 1


def test_the_cli_reads_the_root_and_prints_the_summary():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as tmp:
        make_root(tmp)
        src = Path(tmp) / "sources.json"
        src.write_text(json.dumps(tf.SOURCES))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert vr.main(["--root", tmp, "--channel", "somechannel", "--sources", str(src),
                            "--since", "2026-11-01", "--until", "2026-11-02"]) == 0
    data = json.loads(out.getvalue())
    assert data["refused"] == 5 and data["batches"] == ["2026-11-02T0838Z"]
    assert data["by_verdict"]["feed_unsaved"] == 2 and "rows" not in data


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
