#!/usr/bin/env python3
"""CF-0437 item 1-2: the topic's pool laid out for the writer before the text.

`scripts/pool_layout.py` lists every shot of the topic's own sources the Video
Editor can put on screen (clean and weak - never a shot a hard rule of
`shot_usability` takes out, never one the pre-cut gate refuses), in the order
a sequence is built in (source order, then time), and says how long the pool
lets the video be: the band, what the pool holds (30-45 s is written short,
not stretched), or the hard floor.

The verdicts are the indexer's `shot_usability.of()` and the Editor's
`precut_refusal()` - real modules of the sibling checkouts, not stubs.
"""
import json
import os
import subprocess
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-pool-layout-")
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import pool_layout as pl  # noqa: E402

SCRIPT = HERE.parent / "scripts" / "pool_layout.py"
CHANNEL = "example-film"


def _fingerprint():
    try:
        _su, pd = pl.indexer_modules()
        editor = pd.editor_module()
        return editor.cache_fingerprint.usability_fingerprint()
    except Exception:  # noqa: BLE001 - the black-frame case is then skipped
        return None


FP = _fingerprint()


def _cached(**over):
    c = {"measured_by": FP, "short_side": 1080, "width": 1920, "height": 1080,
         "roi_source": "faces", "roi_coverage": 1.0, "black_fraction": 0.05,
         "mean_luma": 80.0, "text_regions": 0, "text_area": 0.0,
         "text_outside_crop": 1.0, "text_cut_by_crop": 0.0, "text_cut_area": 0.0}
    c.update(over)
    return c


def _shot(i, start, end, desc, **over):
    s = {"index": i, "start": start, "end": end, "description": desc,
         "is_card": False, "burned_text": False, "on_topic": True}
    if FP:
        s["usable_cached"] = _cached()
    s.update(over)
    return s


A_SHOTS = [
    # deliberately out of time order in the file
    _shot(3, 9.0, 12.0, "a crowd outside a cinema at night"),
    _shot(0, 0.0, 2.5, "a woman on a rooftop at dusk"),
    _shot(1, 2.5, 5.0, "a title card with burned-in foreign subtitles", burned_text=True),
    _shot(2, 5.0, 5.3, "a flash frame"),                                   # under MIN_CUT
    _shot(4, 12.0, 15.0, "a press conference podium", on_topic=False),     # weak
]
B_SHOTS = [
    _shot(0, 0.0, 4.0, "an interview close-up against a dark backdrop"),
    _shot(1, 4.0, 8.0, "the actor laughing on a talk-show couch", shows_entity=True),
]
if FP:
    A_SHOTS.append(_shot(5, 15.0, 18.0, "a black fade", usable_cached=_cached(black_fraction=0.97)))
    B_SHOTS.append(_shot(2, 8.0, 11.0, "a dim corridor", usable_cached=_cached(mean_luma=12.0)))


class Bench:
    def __init__(self, sources=None, fetched_next_to=True, extra_topics=None):
        self.dir = Path(tempfile.mkdtemp(dir=_TMP)) / "pipeline" / CHANNEL / "2026-09-30T0000Z"
        self.dir.mkdir(parents=True)
        self.pool = self.dir.parent.parent / "footage"
        self.pool.mkdir()
        sources = sources if sources is not None else {"A": A_SHOTS, "B": B_SHOTS}
        fetched = []
        for vid, shots in sources.items():
            (self.pool / f"{vid}.shots.json").write_text(json.dumps(
                {"source": str(self.pool / f"{vid}.mp4"), "shots": shots}))
            if fetched_next_to:
                fetched.append({"video_id": vid, "path": str(self.pool / f"{vid}.mp4"),
                                "topic_id": "t1"})
        by_topic = {"t1": list(sources)}
        by_topic.update(extra_topics or {})
        (self.dir / "01b-footage-index.json").write_text(json.dumps(
            {"fetched": fetched, "sources_by_topic": by_topic}))
        (self.dir / "01-trend-hunter.json").write_text(json.dumps({"channel": CHANNEL}))

    def layout(self, **kw):
        kw.setdefault("footage_dir", str(self.pool))
        return pl.layout(self.dir, **kw)


def _topic(doc, tid="t1"):
    return [t for t in doc["topics"] if t["topic_id"] == tid][0]


# --------------------------------------------------------------------------
# what is in the layout

def test_no_hard_shot_and_no_precut_refusal_reaches_the_layout():
    lay = _topic(Bench().layout())
    descs = [s["description"] for s in lay["shots"]]
    assert "a title card with burned-in foreign subtitles" not in descs, descs
    assert "a flash frame" not in descs, "shorter than MIN_CUT_SECONDS"
    assert "a black fade" not in descs, descs
    out = lay["counts"]["left_out"]
    assert out.get("hard", 0) >= 1 and out.get("precut", 0) >= 1, out
    for s in lay["shots"]:
        assert s["score"] > 0 and s["class"] in (pl.CLEAN, pl.WEAK), s


def test_weak_shots_stay_with_their_rules_and_score():
    lay = _topic(Bench().layout())
    by = {s["description"]: s for s in lay["shots"]}
    podium = by["a press conference podium"]
    assert podium["class"] == pl.WEAK and "off_topic_shot" in podium["soft"], podium
    assert podium["score"] < 1.0
    clean = by["a woman on a rooftop at dusk"]
    assert clean["class"] == pl.CLEAN and clean["soft"] == [] and clean["score"] == 1.0, clean
    if FP:
        assert "low_brightness" in by["a dim corridor"]["soft"], by["a dim corridor"]
    assert lay["counts"]["weak"] == sum(1 for s in lay["shots"] if s["class"] == pl.WEAK)


def test_each_shot_carries_what_the_writer_builds_the_sequence_from():
    lay = _topic(Bench().layout())
    s = [x for x in lay["shots"] if x["shows_entity"]][0]
    assert s["ref"] == "B:1" and s["description"].startswith("the actor laughing"), s
    for key in ("ref", "video_id", "start", "end", "seconds", "description", "is_card",
                "shows_entity", "score", "soft", "class"):
        assert key in s, key
    assert s["seconds"] == 4.0


def test_the_layout_is_ordered_source_by_source_in_time():
    lay = _topic(Bench().layout())
    refs = [s["ref"] for s in lay["shots"]]
    assert refs[:3] == ["A:0", "A:3", "A:4"], refs
    assert refs.index("B:0") > refs.index("A:4"), "sources in sources_by_topic order"
    starts = [s["start"] for s in lay["shots"] if s["video_id"] == "A"]
    assert starts == sorted(starts), starts


def test_only_the_topics_own_sources_are_laid_out():
    b = Bench(extra_topics={"t2": ["B"]})
    t2 = _topic(b.layout(topic="t2"), "t2")
    assert {s["video_id"] for s in t2["shots"]} == {"B"}, t2["shots"]
    assert [t["topic_id"] for t in b.layout(topic="t2")["topics"]] == ["t2"]


def test_the_shared_pool_is_found_without_a_fetched_path():
    lay = _topic(Bench(fetched_next_to=False).layout())
    assert lay["counts"]["available"] >= 4, lay["counts"]


# --------------------------------------------------------------------------
# how long the pool lets the video be (item 2)

def _many(n):
    return [_shot(i, i * 3.0, i * 3.0 + 3.0, f"shot {i}") for i in range(n)]


def test_a_deep_pool_is_written_to_the_band():
    length = _topic(Bench({"A": _many(30)}).layout())["length"]
    assert length["target"] == pl.TARGET_BAND and length["target_video_seconds"] == [45, 60], length


def test_a_pool_that_holds_30_to_45_is_written_short_not_stretched():
    # 12 shots x 3 s = 36 s of narration + the channel's tail: inside 30..45
    lay = _topic(Bench({"A": _many(12)}).layout())
    length = lay["length"]
    assert length["target"] == pl.TARGET_POOL, length
    lo, _hi = length["band"]
    t = length["target_video_seconds"][0]
    assert length["hard_min"] <= t < lo, length
    line = pl.target_line(length)
    assert "do NOT stretch" in line and "short_length" in line, line


def test_a_thin_pool_is_written_to_the_hard_floor():
    length = _topic(Bench({"A": _many(4)}).layout())["length"]
    assert length["target"] == pl.TARGET_FLOOR, length
    assert length["target_video_seconds"] == [length["hard_min"]] * 2, length
    assert "THIN POOL" in pl.target_line(length)


def test_the_drawn_hold_changes_what_the_pool_holds():
    b = Bench({"A": _many(12)})
    short = _topic(b.layout(hold=1.5))["length"]
    long_ = _topic(b.layout(hold=6.0))["length"]
    assert short["holds_narration_seconds"] == 18.0 and long_["holds_narration_seconds"] == 72.0
    assert long_["target"] == pl.TARGET_BAND and short["target"] == pl.TARGET_FLOOR


# --------------------------------------------------------------------------
# the command line

def test_the_cli_prints_the_layout_and_exits_zero():
    b = Bench()
    env = dict(os.environ, FOOTAGE_DIR=str(b.pool))
    r = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(b.dir)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == pl.EXIT_OK, r.stderr
    assert "POOL t1:" in r.stdout and "A:0" in r.stdout and "length:" in r.stdout, r.stdout
    assert "burned-in" not in r.stdout, r.stdout
    out = b.dir / "work" / "pool-layout.json"
    r = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(b.dir), "--json",
                        "--out", str(out)], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and json.loads(out.read_text())["topics"][0]["topic_id"] == "t1"


def test_no_footage_index_cannot_answer():
    d = Path(tempfile.mkdtemp(dir=_TMP))
    r = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(d)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == pl.EXIT_CANNOT_ANSWER, (r.returncode, r.stderr)
    assert "nothing laid out" in r.stderr


# --------------------------------------------------------------------------
# the skill

def test_the_skill_puts_the_layout_before_the_text():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    for needle in ("pool_layout.py", "CF-0437", "Build the sequence of frames from that list first",
                   "not a reason to stretch the text", "SHORT VIDEO KEPT",
                   "`REWRITE … visual claim`", "visual_claim_check",
                   "rotate.py reject --batch <dir> <script_id> --reason"):
        assert needle in skill, needle
    # the layout is read before step 3 draws the pattern and again with the hold
    assert skill.index("pool_layout.py") < skill.index("3. **Take the assigned pattern")
    assert "--hold" in skill


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
