#!/usr/bin/env python3
"""CF-0490 (CF-0472's price, signed by the user 2026-10-02):
`score.tail_over_band_top` - the last block that still carries speech, held
longer than its pattern's drawn hold band top, priced per second over.

The named defect is everyday-sorcery-2 (example-film/2026-09-15T1034Z,
rejected, `tail_after_last_anchor`): its last block ran 13.52 s against
list's 2.5 s top - 11.02 s over, -66 at the cap. Pinned here: which block is
"the last that speaks" (starts before the last word ends; a block after the
voice is not it), no drawn band - nothing measured, units are seconds over,
the price comes from the root's table (signed row), the finding adds to
`score.hold_band_exceeded` on the same block, and the plan builder asks it
next to hold_band_findings() only under `_score.has_rule`.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import rhythm  # noqa: E402

LIST = {"pattern_id": "list",
        "parameters": {"key_frame_hold_seconds": {"mode": "drawn", "min": 1.0, "max": 2.5}}}
EXPLAINER = {"pattern_id": "explainer",
             "parameters": {"key_frame_hold_seconds": {"mode": "emergent", "max": 6.0}}}


def blocks(*secs):
    out, t = [], 0.0
    for s in secs:
        out.append({"start": round(t, 3), "end": round(t + s, 3)})
        t += s
    return out


def words_until(end):
    return [{"word": "a", "start": 0.0, "end": 0.4}, {"word": "z", "start": end - 0.3, "end": end}]


def everyday_sorcery_like():
    # 12 blocks of 2.4 s, then the spoken tail: 13.52 s, the voice ends inside it
    b = blocks(*([2.4] * 12), 13.52)
    return b, words_until(b[-1]["start"] + 3.1)


def test_the_named_defect_is_eleven_seconds_over():
    b, w = everyday_sorcery_like()
    got = rhythm.tail_over_band_top_findings(b, LIST, w)
    assert len(got) == 1, got
    f = got[0]
    assert f["rule"] == rhythm.SCORE_TAIL_OVER_BAND_TOP == "score.tail_over_band_top"
    assert f["where"]["block"] == 12 and f["units"] == 11.02, f
    assert f["hook"] is False and f["source"] == "metric"


def test_the_last_speaking_block_is_the_one_that_starts_before_the_last_word_ends():
    # a long block after the voice (end card) is not the speech tail
    b = blocks(2.0, 2.0, 2.4, 9.0)
    w = words_until(6.3)          # last word ends inside block 2
    assert rhythm.tail_over_band_top_findings(b, LIST, w) == []
    # the same long block, the voice reaching into it: charged
    w = words_until(6.5)
    got = rhythm.tail_over_band_top_findings(b, LIST, w)
    assert [(f["where"]["block"], f["units"]) for f in got] == [(3, 6.5)], got


def test_within_the_top_or_without_a_drawn_band_nothing_is_found():
    b = blocks(2.0, 2.0, 2.5)
    assert rhythm.tail_over_band_top_findings(b, LIST, words_until(5.0)) == []
    b, w = everyday_sorcery_like()
    assert rhythm.tail_over_band_top_findings(b, EXPLAINER, w) == []
    assert rhythm.tail_over_band_top_findings(b, None, w) == []
    assert rhythm.tail_over_band_top_findings(b, LIST, []) == []


def test_a_storyboard_shaped_block_is_read_too():
    b, w = everyday_sorcery_like()
    sb = [{"_start": x["start"], "_end": x["end"]} for x in b]
    assert rhythm.tail_over_band_top_findings(sb, LIST, w)[0]["units"] == 11.02


def test_it_adds_to_hold_band_exceeded_and_the_signed_price_takes_a_clean_video_under_n():
    if not _score.has_rule(rhythm.SCORE_TAIL_OVER_BAND_TOP):
        print("  skip: the root's table does not carry the signed row")
        return
    b, w = everyday_sorcery_like()
    band = rhythm.hold_band_findings(b, LIST)
    tail = rhythm.tail_over_band_top_findings(b, LIST, w)
    assert [f["where"]["block"] for f in band] == [12]
    alone = _score.score_block(tail)
    assert alone["score"] == 100 - 66, alone          # 11.02 s x 6 = 66.12 -> cap 66
    both = _score.score_block(band + tail)
    assert both["score"] == 100 - 66 - 2, both        # the flat -2 rides on top
    assert both["score"] < 40


def test_the_plan_builder_asks_it_beside_hold_band_findings_under_has_rule():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    at_band = src.index("+ rhythm.hold_band_findings(blocks, pattern)")
    at_tail = src.index("rhythm.tail_over_band_top_findings(blocks, pattern, words)")
    assert 0 < at_tail - at_band < 600
    seg = src[at_tail:at_tail + 200]
    assert "_score.has_rule(rhythm.SCORE_TAIL_OVER_BAND_TOP)" in seg, seg


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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
