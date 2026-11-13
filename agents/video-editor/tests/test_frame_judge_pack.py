#!/usr/bin/env python3
"""CF-0298 item 1: the pack the frame judge is handed.

`frame_judge_pack.py` turns a finished mp4 and its plan into contact sheets
plus a manifest that has to stand on its own - the judge is an LLM operator
that sees those two things and nothing else. So what is checked here is not
"a PNG was written" but everything a verdict could go wrong over:

  * the words the judge compares the picture against are the words heard over
    that picture, straddling words included;
  * the anchor phrase is the one the writer wrote, without the resolver's
    "(shot 26, score 0.335)" tail;
  * a typographic block and the end card are in the manifest and say, in
    words, that they are not a picture under a phrase;
  * an insert (a proof card) is an entry of its own and the block under it
    is sampled where its own footage is actually on screen;
  * our own text on the picture - captions, watermark, comparison line - is
    written down, because the same judge answers DoD item 2 and must not
    convict a block for our own caption band.

Measured 2026-09-20 on the real thing - `2026-09-18T2232Z` delver.mp4 with
`work/delver/plan.json`, the render CF-0290 was filed over:

    8 blocks + the end card -> 9 entries, 20 frames, 4 sheets
    sheets 1.0-1.2 MB each, 1128x1430 px, 6+5+5+5 tiles of 360x640
    27.5 s wall (20 seeks into a 49.3 s mp4), manifest 16 KB

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import frame_judge_pack as pack  # noqa: E402

WORDS = [{"word": "Tom", "start": 0.2, "end": 0.6},
         {"word": "Cruise", "start": 0.6, "end": 1.4},
         {"word": "sat", "start": 1.4, "end": 2.0},
         {"word": "down", "start": 2.0, "end": 3.2},
         {"word": "and", "start": 3.2, "end": 3.6},
         {"word": "talked", "start": 3.6, "end": 4.4}]


def _block(start, end, kind="clip", intent="a man at a podium (shot 18, score 0.200)",
           **extra):
    asset = {"kind": kind}
    if kind in ("clip", "still"):
        asset.update({"src": f"clips/a_{kind}.mp4", "focus": {"x": 0.5, "y": 0.3},
                      "fit": "cover", "coverage": 1.0, "roi_source": "faces"})
    block = {"start": start, "end": end, "intent": intent, "asset": asset,
             "shot": "fkuxNGbx1qk:18", "rhythm_role": "punctuation"}
    block.update(extra)
    return block


def _plan(blocks, **extra):
    plan = {"style": "motion", "output": {"width": 1080, "height": 1920, "fps": 30},
            "words": WORDS, "blocks": blocks,
            "watermark": {"text": "EXAMPLE_FILM", "position": "top-left"}}
    plan.update(extra)
    return plan


def test_narration_is_every_word_heard_over_the_picture():
    """A word straddling the cut is heard over both blocks: the judge needs
    the whole phrase, not the part that fits inside the span."""
    text, span = pack.narration(WORDS, 1.0, 3.4)
    assert text == "Cruise sat down and", text
    assert span == [1, 4], span


def test_a_span_with_no_words_says_so_rather_than_inventing_one():
    assert pack.narration(WORDS, 10.0, 12.0) == ("", None)


def test_the_anchor_phrase_drops_the_resolver_bookkeeping():
    assert pack.anchor_phrase("a man at a podium (shot 18, score 0.200)") == \
        "a man at a podium"
    assert pack.anchor_phrase("a wide shot (shot 45, score 0.354, held frame)") == \
        "a wide shot"
    assert pack.anchor_phrase("count card: '4' (opening_block count_card)") == \
        "count card: '4'"


def test_the_anchor_is_named_when_the_resolver_file_is_beside_the_plan():
    """`word_index` is the index of the block's first word, so the anchor
    whose word falls inside the block's words is the block's anchor - and its
    id is what a verdict quotes back."""
    anchors = {"anchors": [{"anchor_id": "v1", "phrase": "first", "word_index": 0},
                           {"anchor_id": "v2", "phrase": "second", "word_index": 3}]}
    got = pack.anchor_for(_block(2.0, 4.0), [2, 5], anchors)
    assert got == {"id": "v2", "phrase": "second", "source": "anchors.json"}, got
    # No file, no match: the phrase still comes back, off the intent.
    got = pack.anchor_for(_block(2.0, 4.0), [2, 5], None)
    assert got["source"] == "intent" and got["phrase"] == "a man at a podium", got


def test_one_two_or_three_frames_by_how_long_the_picture_is_up():
    assert len(pack.sample_times(0.0, 2.0)) == 1
    assert len(pack.sample_times(0.0, 4.0)) == 2
    assert len(pack.sample_times(0.0, 9.0)) == 3
    # In time order, inside the span, and never on the cut.
    times = pack.sample_times(10.0, 20.0)
    assert times == sorted(times) and times[0] > 10.0 and times[-1] < 20.0, times
    # An entry that is not judged gets one tile, whatever its length.
    assert len(pack.sample_times(0.0, 9.0, most=1)) == 1
    assert pack.sample_times(5.0, 5.0) == []


def test_typography_and_the_end_card_carry_their_own_refusal_to_be_judged():
    plan = _plan([_block(0.0, 4.0), _block(4.0, 8.0, kind="procedural")],
                 end_card={"path": "/channels/x/ending.mp4", "start_s": 8.0,
                           "seconds": 5.0, "variant": "clip", "channel_name": "X"})
    entries = pack.entries_for(plan, 13.0)
    kinds = [(e["kind"], e["judged"]) for e in entries]
    assert kinds == [("clip", True), ("typography", False), ("end_card", False)], kinds
    # The reason is the sentence the judge reads, not a code it has to look
    # up: it says what the picture is instead of a picture under a phrase.
    assert "the picture IS the words" in entries[1]["not_judged_reason"], entries[1]
    assert "not a picture chosen for anything the narrator says" in \
        entries[2]["not_judged_reason"], entries[2]


def test_an_end_card_the_render_never_carried_is_not_in_the_pack():
    """The plan plans the ending; a file that stops before it does not have
    one, and a tile grabbed past the end is the last frame held."""
    plan = _plan([_block(0.0, 8.0)],
                 end_card={"path": "/channels/x/ending.mp4", "start_s": 8.0,
                           "seconds": 5.0})
    assert [e["kind"] for e in pack.entries_for(plan, 8.1)] == ["clip"]
    assert [e["kind"] for e in pack.entries_for(plan, 13.2)] == ["clip", "end_card"]


def test_an_insert_is_judged_as_itself_and_the_block_under_it_where_it_shows():
    """CF-0244's proof card is up for part of the block; a frame grabbed under
    it shows the captured page, not the shot the anchor was resolved to."""
    insert = {"kind": "proof", "proof_id": "p1", "start_s": 2.0, "end_s": 6.0,
              "capture_path": "/w/proof-p1.png", "capture_method": "headless_browser",
              "source_url": "https://variety.com/x", "author_or_outlet": "Variety",
              "captions": "hidden"}
    plan = _plan([_block(0.0, 10.0, insert=insert)],
                 proof={"proofs": [{"proof_id": "p1", "verbatim_text": "headline",
                                    "claim_supported": "the claim"}]})
    entries = pack.entries_for(plan, 10.0)
    assert [e["kind"] for e in entries] == ["clip", "proof"], entries
    block, proof = entries
    # 6.0-10.0 is the longer of the two stretches the block's own footage has.
    assert block["frames_from"] == [6.0, 10.0], block["frames_from"]
    assert proof["frames_from"] == [2.0, 6.0], proof["frames_from"]
    assert proof["source"]["source_url"] == "https://variety.com/x"
    assert proof["anchor"]["phrase"] == "the claim"
    assert block["overlays"][0] == {"kind": "captions", "state": "hidden",
                                    "note": "captions are off under this insert "
                                            "(Video.jsx)"}, block["overlays"]


def test_a_proof_that_shows_our_captions_is_judged_for_them():
    """CF-0390: proof_layer.py writes `captions: shown` now, and the judge is
    told our words are on the frame under the card - DoD item 1 is checked on
    the card's frames as on any other."""
    insert = {"kind": "proof", "proof_id": "p1", "start_s": 2.0, "end_s": 6.0,
              "capture_path": "/w/proof-p1.png", "captions": "shown"}
    plan = _plan([_block(0.0, 10.0, insert=insert)],
                 proof={"proofs": [{"proof_id": "p1", "verbatim_text": "headline",
                                    "claim_supported": "the claim"}]})
    block = pack.entries_for(plan, 10.0)[0]
    cap = block["overlays"][0]
    assert cap["kind"] == "captions" and cap["state"] == "shown", cap
    assert "proof" in cap["note"] and "stay on" in cap["note"], cap


def test_a_block_an_insert_covers_whole_gets_no_picture_of_its_own():
    insert = {"kind": "meme", "capture_path": "/w/meme.png"}
    entries = pack.entries_for(_plan([_block(0.0, 4.0, insert=insert)]), 4.0)
    assert entries[0]["frames_from"] is None
    assert "never on screen alone" in entries[0]["note"], entries[0]["note"]
    assert entries[1]["kind"] == "meme" and entries[1]["frames_from"] == [0.0, 4.0]


def test_our_own_text_on_the_picture_is_written_down_for_the_judge():
    """DoD item 2 is the same judge's business, and our caption band, our
    watermark and our fact panel are not the violation - somebody else's
    burned-in subtitles are."""
    lines = [{"text": "Shoot halted 2 days", "start_s": 19.22, "end_s": 26.24,
              "block_index": 1, "publisher": "Wikipedia"}]
    plan = _plan([_block(0.0, 19.0), _block(19.0, 27.0)], comparison_lines=lines)
    entries = pack.entries_for(plan, 27.0)
    assert [o["kind"] for o in entries[0]["overlays"]] == ["captions"]
    assert [o["kind"] for o in entries[1]["overlays"]] == ["captions", "comparison_line"]
    assert entries[1]["overlays"][1]["text"] == "Shoot halted 2 days"


def test_the_shot_the_picture_came_from_is_named_by_video_id():
    source = pack.source_of(_block(0.0, 4.0))
    assert source["video_id"] == "fkuxNGbx1qk" and source["shot_index"] == 18


def test_the_last_sheet_is_never_one_lonely_tile():
    assert pack.sheet_grid(21) == [6, 5, 5, 5]
    assert pack.sheet_grid(7) == [4, 3]
    assert pack.sheet_grid(6) == [6]
    assert pack.sheet_grid(1) == [1]
    assert sum(pack.sheet_grid(13)) == 13


def test_a_tile_says_out_loud_when_it_is_not_judged():
    entry = {"block": None, "kind": "end_card", "judged": False, "start": 44.1,
             "end": 49.3, "source": {}}
    head, tail = pack.tile_label(20, entry, 45.4)
    assert head.startswith("#20  end card  end_card  44.10-49.30s  @ 45.40s"), head
    assert tail == "NOT judged as a picture under a phrase", tail
    head, _ = pack.tile_label(3, {"block": 1, "kind": "clip", "judged": True,
                                  "start": 5.63, "end": 11.17,
                                  "source": {"shot": "fkuxNGbx1qk:18"}}, 7.02)
    assert "block 1" in head and "@ 7.02s" in head, head


def _tiny_video(path, seconds=9):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc=size=108x192:rate=10:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def test_the_whole_pack_off_a_real_file():
    """End to end on a generated 9 s video: the frames are grabbed from the
    finished file, the sheets are written, and every frame in the manifest
    points at the sheet that actually carries its tile."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        video = tmp / "v.mp4"
        _tiny_video(video)
        plan_path = tmp / "work" / "slug" / "plan.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(json.dumps(_plan(
            [_block(0.0, 4.0), _block(4.0, 6.0, kind="procedural"),
             _block(6.0, 9.0, kind="still")])))
        out = tmp / "pack"
        manifest = pack.build(video, plan_path, out)

        assert manifest["refusal"] is None, manifest.get("refusal")
        assert manifest["counts"] == {"entries": 3, "judged": 2, "not_judged": 1,
                                      "frames": 2 + 1 + 2, "sheets": 1}, \
            manifest["counts"]
        assert manifest["video"]["width"] == 108
        assert manifest["video"]["seconds"] == 9.0, manifest["video"]
        assert manifest["plan"]["slug"] == "slug"
        sheets = {s["file"] for s in manifest["sheets"]}
        tiles = [f["tile"] for e in manifest["entries"] for f in e["frames"]]
        assert tiles == list(range(1, 6)), tiles
        for entry in manifest["entries"]:
            for frame in entry["frames"]:
                assert frame["sheet"] in sheets, frame
                assert entry["start"] <= frame["at"] <= entry["end"], frame
        assert (out / "manifest.json").is_file()
        for name in sheets:
            assert (out / name).stat().st_size > 10_000, name
        # The manifest on disk is the one the judge gets: same thing, as JSON.
        assert json.loads((out / "manifest.json").read_text()) == manifest


# ---------------------------------------------------------------- CF-0689
GRAPHIC_ASSET = {"kind": "own_graphic", "graphic_id": "g1", "template": "benchmark",
                 "data": {"metric": "SWE-bench Verified",
                          "rows": [{"name": "Gemini 2.5 Pro", "score": "63.8%"},
                                   {"name": "Claude 3.7", "score": "62.3%"}]},
                 "source_label": "Google", "caption": "According to Google", "lang": "en",
                 "offset_seconds": 0.0}


def test_an_own_graphic_is_ours_on_screen_cf0689():
    b = {"start": 0.0, "end": 3.0, "intent": "own graphic g1", "asset": GRAPHIC_ASSET,
         "shot": None, "rhythm_role": "beat"}
    plan = _plan([b, _block(3.0, 4.4)])
    entry = pack.entries_for(plan, 4.4)[0]
    assert entry["kind"] == "own_graphic" and entry["judged"], entry
    assert entry["source"]["own_graphic"] is True and entry["source"]["graphic_id"] == "g1"
    ov = [o for o in entry["overlays"] if o["kind"] == "own_graphic"]
    assert len(ov) == 1, entry["overlays"]
    assert ov[0]["text"] == ("SWE-bench Verified\nGemini 2.5 Pro: 63.8%\n"
                             "Claude 3.7: 62.3%\nAccording to Google"), ov[0]["text"]
    assert "foreign_text" in ov[0]["note"]
    ours = pack.ours_on_screen(plan)["own_graphic"]
    assert ours["blocks"] == [0], ours
    assert ours["graphics"][0]["graphic_id"] == "g1" and "63.8%" in ours["graphics"][0]["text"]
    # a footage block carries no such overlay, and a plan without graphics an empty key
    assert not [o for o in pack.entries_for(plan, 4.4)[1]["overlays"]
                if o["kind"] == "own_graphic"]
    assert pack.ours_on_screen(_plan([_block(0.0, 4.4)]))["own_graphic"]["blocks"] == []


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
