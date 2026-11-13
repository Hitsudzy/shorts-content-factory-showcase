#!/usr/bin/env python3
"""CF-0075: the `side_by_side` opening never stands still past a short ceiling.

On `wren-hollow-lockhart` (batch 2026-08-31T2155Z, storyboard_sbs.json) the
opening was laid over the script's first run - 12.12s - and no clip on either
side was that long (1.09s and 3.8s), so both halves were held frames for all
of it. Same mechanism as CF-0074: no clip of the needed length -> freeze. Now
a half plays its distinct clips back to back, holds its last frame for at most
rhythm.OPENING_MAX_STATIC_SECONDS, and the opening ends where the first side
runs out of both; the rest of the run goes to the ordinary block chain, and
`rhythm_shortfalls` carries an `opening_static_held` entry the Analyst can see.

Synthetic: cutting and frame-lifting are stubbed on the module, so nothing
here touches ffmpeg.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402

SRC = "/footage/ZZ_urA56pJE.mp4"


def cand(shot, length, score=0.3):
    return {"source": SRC, "shot": shot, "start": 100.0, "end": 100.0 + length,
            "score": score}


def fake_cut_usable(cand, need, dest, shots_lut, args):
    span = min(need, cand["end"] - cand["start"])
    if span < 0.7:
        return None
    Path(dest).write_bytes(b"clip")
    return {"clip": str(dest), "shot": cand["shot"], "source": cand["source"],
            "key": (cand["source"], cand["shot"]), "score": cand["score"],
            "seconds": round(span, 2), "card": False, "cut_at": cand["start"],
            "cut_origin": "head", "moment_at": None, "crop_bottom": 0.0,
            "frame_before_crop": None}


def fake_hold_frame(clip, seconds, dest, used=None):
    Path(dest).write_bytes(b"png")
    return True


ra.cut_usable = fake_cut_usable
ra.hold_frame = fake_hold_frame
MATCHES = {0: {"phrase": "the great hall"}, 3: {"phrase": "the fur cloak in the snow"}}


def build(run, a, b):
    with tempfile.TemporaryDirectory() as tmp:
        halves = ra.build_split_opening(
            None, MATCHES, {}, {"a": (0, a), "b": (3, b)}, Path(tmp),
            {"start": 0.0, "end": run}, None)
        files = sorted(p.name for p in Path(tmp).iterdir())
    return halves, files


def plan_block(halves, run, start=0.0):
    """The split block as build_render_plan.py writes it, minus the framing."""
    length = halves[0]["seconds"]
    return {"start": start, "end": round(start + length, 3), "side": "both",
            "shot": None, "opening_run_seconds": run,
            "asset": {"kind": "split", "sides": [
                {"side": h["side"], "kind": h["kind"], "src": h["asset"],
                 "held_frame": h["held_frame"],
                 "cuts": [{"kind": c["kind"], "src": c["asset"], "shot": c["shot"],
                           "from_seconds": c["at"], "seconds": c["seconds"],
                           "held_frame": c["held_frame"]}
                          for c in (ra.split_cut_record(c) for c in h["cuts"])]}
                for h in halves]}}


def order(**params):
    return {"pattern_id": "contrast", "rhythm_id": "alternate",
            "parameters": {"block_count": 16, "key_frame_hold_seconds": 3.0,
                           "opening_block": "side_by_side", **params}}


def keys(halves):
    return [c["key"] for h in halves for c in h["cuts"] if not c["held_frame"]]


def test_an_opening_within_the_ceiling_is_untouched():
    """A run both sides can carry, or finish with a hold inside the ceiling,
    is exactly the block it was before: full length, no deficit."""
    assert rhythm.opening_length(6.0, {"a": 6.0, "b": 5.9}) == (6.0, {"a": 0.0, "b": 0.0})
    halves, files = build(6.0, [cand(54, 6.0)], [cand(48, 5.9)])
    assert [h["seconds"] for h in halves] == [6.0, 6.0], halves
    assert all(len(h["cuts"]) == 1 and not h["held_frame"] for h in halves), halves
    assert not any(f.endswith(".png") for f in files), files

    # A short hold that finishes the run is the ceiling working as designed.
    halves, files = build(5.0, [cand(54, 3.0)], [cand(48, 5.0)])
    a = next(h for h in halves if h["side"] == "a")
    assert a["seconds"] == 5.0 and a["static_seconds"] == 2.0 and a["held_frame"], a
    assert [c["kind"] for c in a["cuts"]] == ["clip", "still"], a["cuts"]
    assert a["cuts"][1]["at"] == 3.0 and a["cuts"][1]["seconds"] == 2.0, a["cuts"]
    assert a["kind"] == "clip" and a["asset"] == a["cuts"][0]["asset"], (
        "the half itself has to keep describing its first picture - that is the "
        "shape every reader of a split half knew before CF-0075")
    short = rhythm.rhythm_shortfalls(order(), [plan_block(halves, 5.0)])
    assert short == [], short
    rep = rhythm.opening_report([plan_block(halves, 5.0)])
    assert rep["truncated_seconds"] == 0.0 and not rep["static_over_ceiling"], rep


def test_over_the_ceiling_the_opening_cuts_to_distinct_shots_and_never_reuses_one():
    """The real run, 12.12s, with footage that adds up: each side plays its
    clips back to back and no sample is on screen twice - not on the other
    side, not later on its own."""
    # The scores descend to say "best match first" and nothing more; since
    # CF-0290 they also have to stay above the 0.22 similarity floor, or the
    # half would be built out of frames that depict neither side.
    a = [cand(54, 1.1), cand(57, 6.7, 0.29), cand(47, 2.4, 0.27), cand(9, 3.0, 0.25)]
    b = [cand(48, 3.8), cand(7, 3.8, 0.29), cand(57, 6.7, 0.27), cand(20, 5.0, 0.25)]
    halves, files = build(12.12, a, b)
    assert [h["seconds"] for h in halves] == [12.12, 12.12], halves
    assert not any(h["held_frame"] for h in halves), halves
    used = keys(halves)
    assert len(used) == len(set(used)), f"a shot is on screen twice: {used}"
    assert (SRC, 57) in used and used.count((SRC, 57)) == 1, used
    for h in halves:
        t = 0.0
        for c in h["cuts"]:
            assert c["at"] == round(t, 3), (h["side"], h["cuts"])
            t += c["seconds"]
        assert abs(t - 12.12) < 0.02, (h["side"], t)
    assert not any(f.endswith(".png") for f in files), files
    short = rhythm.rhythm_shortfalls(order(), [plan_block(halves, 12.12)])
    assert short == [], short


def test_over_the_ceiling_with_no_distinct_shots_each_side_degrades_and_the_deficit_is_recorded():
    """The real pools: one clip per side, 1.1s and 3.8s, over a 12.12s run.
    Side a moves for 1.1s and holds for the ceiling; side b is trimmed to the
    opening; the opening ends at 3.6s and hands 8.52s back to the run - and
    that is written down as an `opening_static_held` shortfall."""
    halves, files = build(12.12, [cand(54, 1.1)], [cand(48, 3.8)])
    a = next(h for h in halves if h["side"] == "a")
    b = next(h for h in halves if h["side"] == "b")
    assert a["seconds"] == b["seconds"] == 3.6, halves
    assert [(c["kind"], c["at"], c["seconds"]) for c in a["cuts"]] == \
        [("clip", 0.0, 1.1), ("still", 1.1, 2.5)], a["cuts"]
    assert a["static_seconds"] == rhythm.OPENING_MAX_STATIC_SECONDS, a
    assert [(c["kind"], c["at"], c["seconds"]) for c in b["cuts"]] == \
        [("clip", 0.0, 3.6)], b["cuts"]
    assert b["static_seconds"] == 0.0 and not b["held_frame"], b
    assert "open_a_held_open_a_ZZ_urA56pJE_s054.png" in files, files

    block = plan_block(halves, 12.12)
    short = rhythm.rhythm_shortfalls(order(), [block])
    assert [s["kind"] for s in short] == ["opening_static_held"], short
    s = short[0]
    assert s["seconds"] == 3.6 and s["run_seconds"] == 12.12, s
    assert s["truncated_seconds"] == 8.52, s
    assert s["longest_static_seconds"] == 2.5 and s["over_by_seconds"] == 0.0, s
    assert s["sides"]["a"] == {"cuts": 2, "shots": ["ZZ_urA56pJE:54", "ZZ_urA56pJE:54"],
                               "motion_seconds": 1.1, "static_seconds": 2.5,
                               "longest_static_seconds": 2.5}, s["sides"]
    assert s["sides"]["b"]["motion_seconds"] == 3.6 and \
        s["sides"]["b"]["static_seconds"] == 0.0, s["sides"]
    assert "8.52s went to the ordinary blocks" in s["note"], s["note"]

    # Whatever rhythm was ordered: the deficit is the opening's, not alternate's.
    even = {**order(), "rhythm_id": "even"}
    assert [x["kind"] for x in rhythm.rhythm_shortfalls(even, [block])] == \
        ["opening_static_held"]


def test_the_deficit_record_and_the_side_runs_field():
    """The record's shape, on the block the batch actually delivered: a plan
    from before CF-0075, two held stills and no `cuts`, is read as one picture
    per side for the whole 12.12s - over the ceiling by 9.62s. The opening's
    entry sits first in `rhythm_shortfalls`, ahead of CF-0057's side runs, and
    `side_runs.opening` carries the same per-side numbers."""
    legacy = {"start": 0.0, "end": 12.12, "side": "both", "shot": None,
              "asset": {"kind": "split", "sides": [
                  {"side": "a", "kind": "still", "src": "a.png", "held_frame": True,
                   "shot": "ZZ_urA56pJE:54"},
                  {"side": "b", "kind": "still", "src": "b.png", "held_frame": True,
                   "shot": "ZZ_urA56pJE:48"}]}}
    held_run = {"start": 12.12, "end": 27.29, "side": "b", "shot": "ZZ:7",
                "held_frame": True, "asset": {"kind": "still", "src": "s7.png"}}
    blocks = [legacy, held_run]
    short = rhythm.rhythm_shortfalls(order(), blocks)
    assert [s["kind"] for s in short] == ["opening_static_held", "long_side_run_held"], short
    s = short[0]
    for key, typ in (("kind", str), ("opening", str), ("side", str), ("blocks", list),
                     ("start", float), ("end", float), ("seconds", float),
                     ("run_seconds", float), ("truncated_seconds", float),
                     ("ceiling_seconds", float), ("longest_static_seconds", float),
                     ("over_by_seconds", float), ("sides", dict), ("shots", list),
                     ("note", str)):
        assert isinstance(s.get(key), typ), (key, s.get(key))
    assert s["side"] == rhythm.BOTH_SIDES and s["blocks"] == [0], s
    assert s["seconds"] == s["run_seconds"] == 12.12 and s["truncated_seconds"] == 0.0, s
    assert s["longest_static_seconds"] == 12.12 and s["over_by_seconds"] == 9.62, s
    assert s["ceiling_seconds"] == rhythm.OPENING_MAX_STATIC_SECONDS == 2.5, s
    assert s["sides"]["a"]["motion_seconds"] == 0.0 and \
        s["sides"]["a"]["static_seconds"] == 12.12, s["sides"]
    assert "CF-0075" in s["note"] and "12.12s" in s["note"], s["note"]
    json.dumps(short)  # it has to be writable into 05-video-editor.json as is

    runs = rhythm.side_run_report(blocks, 3.0)
    assert runs["opening"]["block"] == 0 and runs["opening"]["static_over_ceiling"], runs
    assert runs["opening"]["sides"] == s["sides"], runs["opening"]
    assert rhythm.side_run_report([held_run], 3.0)["opening"] is None


def test_a_sliver_of_run_is_folded_into_the_opening_and_recorded():
    """A remainder under MIN_ORDERED_BLOCK_SECONDS is no block anyone can cut,
    so it joins the opening - and the overshoot past the ceiling is then in
    the record rather than hidden by the rounding."""
    length, static = rhythm.opening_length(12.0, {"a": 9.0, "b": 12.0})
    assert length == 12.0 and static == {"a": 3.0, "b": 0.0}, (length, static)
    halves, _ = build(12.0, [cand(54, 9.0)], [cand(48, 12.0)])
    short = rhythm.rhythm_shortfalls(order(), [plan_block(halves, 12.0)])
    assert len(short) == 1 and short[0]["over_by_seconds"] == 0.5, short


def test_a_side_under_the_similarity_floor_is_no_side_at_all():
    """CF-0290: a comparison half filled with a frame that depicts neither
    thing states no axis, so the floor screens this path too - and a side left
    with nothing above it leaves `halves` short, which contrast.json already
    answers by not building the opening at all."""
    halves, files = build(6.0, [cand(54, 6.0)], [cand(48, 6.0, 0.21)])
    assert halves == [], halves
    assert not files, files


def test_one_side_with_nothing_is_still_no_opening():
    """contrast.json's rule survives the rewrite: a half-built side-by-side is
    not built, and the clips cut for the surviving side are deleted."""
    halves, files = build(6.0, [cand(54, 6.0)], [cand(48, 0.5)])
    assert halves == [] and files == [], (halves, files)


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
