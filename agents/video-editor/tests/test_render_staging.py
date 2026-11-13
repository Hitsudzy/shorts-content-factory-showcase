#!/usr/bin/env python3
"""CF-0301: every file a block mounts is staged, a `sequence` block's cuts too.

Batch 2026-09-21T0358Z: the first live plan with a multi-shot swing block
(CF-0120, `asset.kind == "sequence"`) never rendered. `render_video.py` staged
`asset.src` and the cuts under `sides[]`, but a sequence block keeps its cuts
on `asset.cuts`, so the second cut stayed an absolute path, AssetLayer.jsx
turned it into `file:///...`, Chrome refused it, and the attempt cap was spent
on three identical failures. What is pinned here is the list of holders, on
the shapes the plan really writes.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import render_video  # noqa: E402


def _srcs(block):
    return [h["src"] for h in render_video.src_holders(block) if h.get("src")]


def test_a_sequence_block_offers_every_cut():
    block = {"asset": {"kind": "sequence", "src": "/w/a06_s009.mp4",
                       "cuts": [{"kind": "clip", "src": "/w/a06_s009.mp4"},
                                {"kind": "clip", "src": "/w/a06_s008.mp4"}]}}
    assert set(_srcs(block)) == {"/w/a06_s009.mp4", "/w/a06_s008.mp4"}


def test_a_split_block_still_offers_both_halves_and_their_cuts():
    block = {"asset": {"kind": "side_by_side", "sides": [
        {"src": "/w/l.mp4", "cuts": [{"src": "/w/l1.mp4"}, {"src": "/w/l2.mp4"}]},
        {"src": "/w/r.mp4"}]}}
    assert set(_srcs(block)) == {"/w/l.mp4", "/w/l1.mp4", "/w/l2.mp4", "/w/r.mp4"}


def test_a_procedural_block_offers_nothing():
    assert _srcs({"asset": {"kind": "typographic"}}) == []


def test_staging_leaves_no_absolute_path_in_a_sequence_block():
    """End to end through stage(): after staging, nothing AssetLayer.jsx would
    turn into `file://` is left in the block, and the shared first cut is
    copied once."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        a, b = tmp / "a.mp4", tmp / "b.mp4"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        job = render_video.new_job("seq", jobs=tmp / "jobs")
        block = {"asset": {"kind": "sequence", "src": str(a),
                           "cuts": [{"src": str(a)}, {"src": str(b)}]}}
        seen = {}
        for holder in render_video.src_holders(block):
            if holder.get("src"):
                holder["src"] = render_video.stage(holder["src"], seen, job)
        assert not any(h["src"].startswith("/") for h in [block["asset"], *block["asset"]["cuts"]])
        assert block["asset"]["src"] == block["asset"]["cuts"][0]["src"]
        assert len(list((job / "public" / "job").iterdir())) == 2


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
