#!/usr/bin/env python3
"""CF-0811 (part c): RUN_SUMMARY's MEMES line - memes requested by the writer,
placed by the editor, why the rest were not, and two warnings at zero.

Synthetic batches in temp directories (no live batch, no live channel config):

* the counts: «поставлено» is the `meme_delivered` answers with
  `outcome: placed`, not the blocks a span meme covers;
* the not-placed breakdown by outcome, `no_block` split by its `reason`;
* «без мема» by `meme_none_reason`;
* hole fills counted apart from the requests;
* warning (i): zero written with a script that has no reason, or with the
  channel's meme layer on; none when every zero has a reason and the layer is
  off;
* warning (ii): requested and none placed;
* an old batch without the fields reads «нет данных», never as a zero, and a
  batch dir with neither artifact is silent;
* the line reaches the rendered RUN_SUMMARY and `compute()["memes"]`.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmproot import tmp_root                                        # noqa: E402

import memes                                                         # noqa: E402
import summary                                                       # noqa: E402

# CF-0378: every temp tree under one root that goes at interpreter exit.
TMP = tmp_root("cf0811-memes-test-")

OFF = ("testch", False)
ON = ("testch", True)


def _batch(scripts=None, videos=None):
    bd = Path(tempfile.mkdtemp(prefix="cf0811-memes-", dir=TMP)) / "testch" / "2026-10-19T0000Z"
    bd.mkdir(parents=True)
    if scripts is not None:
        (bd / memes.SCRIPTS_FILE).write_text(json.dumps({"channel": "testch", "scripts": scripts}))
    if videos is not None:
        (bd / memes.VIDEOS_FILE).write_text(json.dumps({"channel": "testch", "videos": videos}))
    return bd


def _req(beat):
    return {"beat_id": beat, "intent": "disbelief", "beat_text": "and then it happened",
            "query": None}


def _video(sid, answers, hole=0):
    return {"script_id": sid,
            "meme_requested": [_req(f"b{i}") for i in range(len(answers))],
            "meme_delivered": [dict({"beat_id": f"b{i}"}, **a) for i, a in enumerate(answers)],
            "meme_hole_fill": {"filled": [{"block_index": 9 + k, "asset_id": "m",
                                           "score": 0.3, "lead": "x"} for k in range(hole)]}}


PLACED_SPAN = {"outcome": "placed", "block_index": 3,
               "span": {"blocks": [3, 4, 5], "start_s": 10.0, "end_s": 13.2,
                        "seconds": 3.2, "beat_start_s": 10.0}}


def full_batch():
    scripts = [
        {"script_id": "a", "reactions": [_req("b0"), _req("b1")]},
        {"script_id": "b", "reactions": [_req("b0"), _req("b1")]},
        {"script_id": "c", "reactions": [], "meme_none_reason": "tone"},
        {"script_id": "d", "meme_none_reason": "tone"},
        {"script_id": "e", "meme_none_reason": "pattern_forbids"},
    ]
    videos = [
        _video("a", [PLACED_SPAN, {"outcome": "no_block", "reason": "no_room_before_payoff"}],
               hole=1),
        _video("b", [{"outcome": "placed", "block_index": 7}, {"outcome": "no_asset"}]),
        _video("c", []), _video("d", []), _video("e", []),
    ]
    return _batch(scripts, videos)


def test_counts_breakdown_and_hole_fill_apart():
    m = memes.collect(full_batch(), layer=ON)
    assert (m["requested"], m["placed"], m["hole_fill"], m["written"]) == (4, 2, 1, 4), m
    assert m["not_placed"] == {"no_asset": 1, "no_block/no_room_before_payoff": 1}, m
    assert m["none_reasons"] == {"tone": 2, "pattern_forbids": 1}, m
    assert m["warnings"] == [], m
    text = memes.line(m)
    assert text == ("MEMES: запрошено 4 · поставлено 2 (+1 hole fill) · не поставлено: "
                    "no_asset×1, no_block/no_room_before_payoff×1 · без мема: tone×2, "
                    "pattern_forbids×1"), text
    print("   ", text)


def test_a_span_meme_is_one_meme_not_three_blocks():
    m = memes.collect(_batch([{"script_id": "a", "reactions": [_req("b0")]}],
                             [_video("a", [PLACED_SPAN])]), layer=ON)
    assert (m["requested"], m["placed"]) == (1, 1), m


def test_warning_zero_written_when_a_zero_has_no_reason():
    bd = _batch([{"script_id": "a", "meme_none_reason": "tone"}, {"script_id": "b"}],
                [_video("a", []), _video("b", [])])
    m = memes.collect(bd, layer=OFF)
    assert m["warnings"] == [memes.WARN_ZERO_WRITTEN], m
    text = memes.line(m)
    assert "**НОЛЬ МЕМОВ" in text and "у 1 без meme_none_reason" in text, text
    assert "без мема: tone×1, без причины×1" in text, text


def test_warning_zero_written_when_the_layer_is_on_and_every_script_is_zero():
    bd = _batch([{"script_id": "a", "meme_none_reason": "tone"},
                 {"script_id": "b", "meme_none_reason": "no_fitting_meme"}],
                [_video("a", []), _video("b", [])])
    m = memes.collect(bd, layer=ON)
    assert m["warnings"] == [memes.WARN_ZERO_WRITTEN], m
    assert "слой мемов включён (channels/testch.json)" in memes.line(m), memes.line(m)
    # the same batch on a channel with the layer off: every zero explained, no warning
    m = memes.collect(bd, layer=OFF)
    assert m["warnings"] == [] and "**" not in memes.line(m), m


def test_warning_zero_placed():
    bd = _batch([{"script_id": "a", "reactions": [_req("b0")]}],
                [_video("a", [{"outcome": "no_block", "reason": "pinned_block_in_span"}])])
    m = memes.collect(bd, layer=ON)
    assert m["warnings"] == [memes.WARN_ZERO_PLACED], m
    text = memes.line(m)
    assert text.startswith("MEMES: запрошено 1 · поставлено 0 · не поставлено: "
                           "no_block/pinned_block_in_span×1 - **НОЛЬ ПОСТАВЛЕНО"), text


def test_old_batch_reads_no_data_and_never_crashes():
    bd = _batch([{"script_id": "a"}, {"script_id": "b"}],
                [{"script_id": "a"}, {"script_id": "b"}])
    m = memes.collect(bd, layer=ON)
    assert m["available"] is False and m["warnings"] == [], m
    assert memes.line(m).startswith("MEMES: нет данных"), memes.line(m)
    # pre-CF-0811: reactions and the pair exist, meme_none_reason never did
    bd = _batch([{"script_id": "a", "reactions": [_req("b0")]}, {"script_id": "b"}],
                [_video("a", [{"outcome": "no_block"}]), {"script_id": "b"}])
    m = memes.collect(bd, layer=OFF)
    text = memes.line(m)
    assert "не поставлено: no_block×1" in text and "причина не записывалась" in text, text
    # an unreadable / non-object artifact and a dir with neither artifact
    bd = _batch()
    assert memes.collect(bd) is None and memes.line(None) is None
    (bd / memes.VIDEOS_FILE).write_text("[1, 2]")
    assert memes.collect(bd) is None
    assert memes.collect(None) is None


def test_layer_is_read_from_the_channel_config_of_a_temp_root():
    root = Path(tempfile.mkdtemp(prefix="cf0811-root-", dir=TMP))
    (root / "channels").mkdir()
    (root / "channels" / "testch.json").write_text(json.dumps(
        {"insert_layers": {"meme": {"enabled": True}}}))
    bd = _batch([{"script_id": "a"}], [_video("a", [])])
    assert memes.layer_on(bd, ({"channel": "testch"},), root=root) == ("testch", True)
    m = memes.collect(bd, root=root)
    assert m["layer_on"] is True and m["warnings"] == [memes.WARN_ZERO_WRITTEN], m
    (root / "channels" / "testch.json").write_text(json.dumps({"insert_layers": {}}))
    assert memes.layer_on(bd, ({"channel": "testch"},), root=root) == ("testch", None)


def test_the_line_reaches_the_rendered_summary_and_compute():
    bd = full_batch()
    c = summary.compute(bd, events=[])
    assert c["memes"]["placed"] == 2 and c["memes_line"].startswith("MEMES: запрошено 4"), c
    text = summary.render(bd, events=[])
    lines = text.splitlines()
    assert any(x.startswith("FUNNEL:") for x in lines[:4]), lines[:4]
    assert c["memes_line"] in lines, text[:1500]
    assert not any(x.startswith("MEMES:") for x in summary.render(_batch(), events=[])
                   .splitlines()), "a batch with no 03/05 prints no MEMES line"


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
