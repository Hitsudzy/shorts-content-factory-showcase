#!/usr/bin/env python3
"""CF-0106: the optional time marks on a shot - `moment_at` and `tile_at`.

Second step of CF-0081. After CF-0105 splits heterogeneous long shots, a
homogeneous long shot can still hold its moment (a card after seconds of the
same scene) away from the head, and `resolve_anchors` cuts from the head.
The fix on the video-editor side needs a place to read "cut from here"
from; this file pins down the footage-indexer side of that contract:

  - `moment_at` / `tile_at` are absolute source timecodes in seconds, and
    when present must lie inside the shot's own [start, end];
  - absent and null both mean "no mark" - every index written before this
    change is valid untouched, and the default stays "cut from the head";
  - a mark outside its shot, or one that is not a number, is refused with
    the shot named - by the schema, by the matcher before CLIP is loaded
    (so nothing is spent), and never relayed to a cut;
  - `match_anchors.rank_phrase` relays the mark in `matches`, which is the
    list resolve_anchors builds its candidates from, so the video-editor
    side reads it there and does not have to open shots.json for it;
  - `index_footage.py` records `tile_at` (the midpoint the tile and
    embedding were sampled from) and does not invent `moment_at`.

Plain asserts, no pytest (see run_tests.py).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage  # noqa: E402
import match_anchors  # noqa: E402
import shot_schema  # noqa: E402

from _fi_paths import factory_root, venv_bin  # noqa: E402 - CF-0267

VENV_PY = venv_bin("python3")
MATCHER = SCRIPTS / "match_anchors.py"
from _live_monitors import live_only  # noqa: E402


def _live_pool():
    """CF-0505: a live monitor (a 20-index sample of the live pool). None in the suite, which prints why;
    FI_TESTS_LIVE=1 (or a real batch's RUNLOG_BATCH) reads the live pool."""
    if live_only("test_moment_at_schema.py::_live_pool"):
        return None
    return factory_root() / "shared" / "footage"


def shot(index, start, end, **extra):
    return {"index": index, "start": start, "end": end, "embedding": [0.1] * 4,
            "description": "", "is_card": False, **extra}


def index_of(*shots):
    return {"source": "x.mp4", "model": "m", "shots": list(shots)}


# --- the schema -------------------------------------------------------------

def test_absent_and_null_are_no_mark():
    assert shot_schema.moment_at(shot(0, 0.0, 2.0)) is None
    assert shot_schema.moment_at(shot(0, 0.0, 2.0, moment_at=None)) is None
    assert shot_schema.index_problems(index_of(
        shot(0, 0.0, 2.0), shot(1, 2.0, 5.0, moment_at=None))) == []


def test_mark_inside_bounds_is_accepted_inclusive():
    for at in (3.0, 4.2, 6.0, 3):
        s = shot(7, 3.0, 6.0, moment_at=at)
        assert shot_schema.shot_problems(s) == [], at
        assert shot_schema.moment_at(s) == at
    assert shot_schema.shot_problems(shot(7, 3.0, 6.0, tile_at=4.5)) == []


def test_mark_outside_bounds_is_refused_naming_the_shot():
    for at in (2.999, 6.001, -1, 100):
        problems = shot_schema.shot_problems(shot(7, 3.0, 6.0, moment_at=at))
        assert len(problems) == 1, at
        assert "shot 7" in problems[0] and "moment_at" in problems[0], problems
        assert "[3.0, 6.0]" in problems[0], problems
        try:
            shot_schema.moment_at(shot(7, 3.0, 6.0, moment_at=at))
        except ValueError as e:
            assert "shot 7" in str(e)
        else:
            raise AssertionError(f"moment_at={at} must not be relayed")
    assert shot_schema.shot_problems(shot(7, 3.0, 6.0, tile_at=9.0))


def test_mark_that_is_not_a_timecode_is_refused():
    for bad in ("4.5", True, float("nan"), float("inf"), [4.5], {"at": 4.5}):
        problems = shot_schema.shot_problems(shot(2, 3.0, 6.0, moment_at=bad))
        assert len(problems) == 1, bad
        assert "shot 2" in problems[0], problems


def test_require_valid_lists_every_bad_mark_and_returns_a_good_index():
    good = index_of(shot(0, 0.0, 2.0, moment_at=1.0), shot(1, 2.0, 5.0))
    assert shot_schema.require_valid(good, "good.json") is good
    bad = index_of(shot(0, 0.0, 2.0, moment_at=5.0),
                   shot(1, 2.0, 5.0),
                   shot(2, 5.0, 8.0, moment_at="x"))
    try:
        shot_schema.require_valid(bad, "bad.shots.json")
    except ValueError as e:
        msg = str(e)
        assert msg.startswith("bad.shots.json")
        assert "shot 0" in msg and "shot 2" in msg and "shot 1" not in msg
    else:
        raise AssertionError("an index with a bad mark must be refused")


def test_old_index_without_marks_stays_valid():
    """The field is optional: nothing written before CF-0106 has it, and
    all of it must keep loading. Synthetic here; the real pool below."""
    old = index_of(*(shot(i, i * 2.0, i * 2.0 + 2.0) for i in range(5)))
    for s in old["shots"]:
        assert "moment_at" not in s and "tile_at" not in s
    assert shot_schema.index_problems(old) == []
    assert shot_schema.require_valid(old) is old


def test_the_real_pool_is_valid():
    """Every index beside the footage loads and carries no bad mark - a
    hand-edited description pass that put a mark outside its shot would
    show up here before it shows up in a render. Sampled, not the whole
    pool: this suite has to stay fast."""
    pool = _live_pool()
    if pool is None:
        return
    paths = sorted(pool.glob("*.shots.json"))[:20] if pool.is_dir() else []
    if not paths:
        print("  NOTE: no shared/footage indexes present - nothing checked")
        return
    for p in paths:
        problems = shot_schema.index_problems(json.load(open(p)))
        assert problems == [], f"{p.name}: {problems}"
    print(f"  checked {len(paths)} index(es)")


# --- the indexer ------------------------------------------------------------

def test_tile_at_is_the_sampled_midpoint_and_lies_inside_the_shot():
    """`extract_frames` samples the midpoint; `tile_at` must be that same
    number (one function feeds both), and it is a valid mark by
    construction."""
    s = {"start": 12.5, "end": 20.0}
    assert index_footage.tile_time(s) == 16.25
    s["tile_at"] = index_footage.tile_time(s)
    s["index"] = 0
    assert shot_schema.shot_problems(s) == []
    # A shot of MIN_SHOT_SECONDS still gets a mark inside itself.
    tiny = {"index": 1, "start": 0.0, "end": index_footage.MIN_SHOT_SECONDS}
    tiny["tile_at"] = index_footage.tile_time(tiny)
    assert shot_schema.shot_problems(tiny) == []


def test_sub_shots_from_a_split_get_valid_tile_at():
    """CF-0105 re-cuts a merged long shot into sub-shots *inside*
    build_shots(), so by the time main() stamps `tile_at` the list is
    already the final one - every sub-shot is an ordinary shot and gets its
    own mark, inside its own bounds. Checked on CF-0105's synthetic
    fade-through-black source, the one the detector reads as a single shot."""
    if not Path(index_footage.FFMPEG).exists():
        print("  NOTE: ffmpeg absent - nothing checked")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_split_merged_shots import make_source
    with tempfile.TemporaryDirectory() as tmp:
        src = make_source(Path(tmp) / "merged.mp4", "merged")
        stats = {}
        shots = index_footage.build_shots(src, 0.25, 60, stats=stats)
    assert stats["split"] == 1 and len(shots) >= 2, (stats, shots)
    for i, s in enumerate(shots):
        s["index"] = i
        s["tile_at"] = index_footage.tile_time(s)
        assert s["start"] < s["tile_at"] < s["end"], s
        assert shot_schema.shot_problems(s) == [], s
    index = {"source": str(src), "model": "m", "split_stats": stats, "shots": shots}
    assert shot_schema.require_valid(index, "merged.shots.json") is index
    # The stamp happens after the split in the indexer itself, not before.
    src_text = (SCRIPTS / "index_footage.py").read_text()
    assert src_text.index("shots = build_shots(") < src_text.index("shot[shot_schema.TILE_AT]")


def test_indexer_does_not_invent_moment_at():
    """The indexer records where the tile came from; it does not decide the
    moment. The decision is the describer's (SKILL.md), and stamping every
    midpoint would move every cut to the middle of its shot."""
    src = (SCRIPTS / "index_footage.py").read_text()
    assert 'shot[shot_schema.TILE_AT]' in src
    assert 'shot[shot_schema.MOMENT_AT]' not in src
    assert 'shot["moment_at"]' not in src


# --- the matcher, where the mark is handed to the video editor --------------

def test_rank_phrase_relays_moment_at_and_none_for_unmarked():
    shots = [shot(0, 0.0, 2.0, moment_at=1.5),
             shot(1, 2.0, 5.0),
             shot(2, 5.0, 9.0, moment_at=None)]
    r = match_anchors.rank_phrase("a dog on a lawn", shots, [0.30, 0.25, 0.24],
                                  3, 0.22, 0.05, cards="auto")
    by_shot = {m["shot"]: m for m in r["matches"]}
    assert set(by_shot) == {0, 1, 2}
    assert by_shot[0]["moment_at"] == 1.5
    assert by_shot[1]["moment_at"] is None
    assert by_shot[2]["moment_at"] is None
    # Everything the caller already read is still there, unchanged.
    assert by_shot[0]["start"] == 0.0 and by_shot[0]["end"] == 2.0
    assert set(by_shot[0]) >= {"shot", "start", "end", "score", "card", "promoted"}


def test_rank_phrase_never_relays_a_mark_outside_its_shot():
    shots = [shot(0, 0.0, 2.0, moment_at=7.0), shot(1, 2.0, 5.0)]
    try:
        match_anchors.rank_phrase("a dog", shots, [0.30, 0.25], 3, 0.22, 0.05,
                                  cards="auto")
    except ValueError as e:
        assert "shot 0" in str(e) and "moment_at" in str(e)
    else:
        raise AssertionError("a mark outside its shot must not reach a cut")


def test_the_matcher_refuses_a_bad_mark_before_loading_clip():
    """The wiring, not the rule: resolve_anchors runs match_anchors.py as a
    subprocess and exits on non-zero, so this is what turns a bad mark into
    a stopped run with the shot named - and before CLIP is loaded, which
    is what keeps this test fast (and the refusal cheap)."""
    if not VENV_PY.exists():
        print(f"  NOTE: no {VENV_PY} - matcher subprocess check skipped")
        return
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "marked.shots.json"
        p.write_text(json.dumps(index_of(
            dict(shot(0, 0.0, 2.0, moment_at=9.0), embedding=[0.1] * 512))))
        out = subprocess.run([str(VENV_PY), str(MATCHER), "--index", str(p),
                              "a wooden lake house", "--json"],
                             capture_output=True, text=True, timeout=120)
        assert out.returncode != 0, "a bad mark must stop the run"
        assert "shot 0" in out.stderr and "moment_at" in out.stderr, out.stderr
        assert "[0.0, 2.0]" in out.stderr, out.stderr
        assert not out.stdout.strip(), "nothing may be spent on a refused index"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
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
