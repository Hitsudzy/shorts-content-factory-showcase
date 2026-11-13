#!/usr/bin/env python3
"""CF-0774: the vendor's quotes stay quotes on every script of a capped channel.

`example-tech/2026-10-16T0839Z`: four scripts (explainer, list, contrast)
ordered no graphic and put every anchor on the vendor's clips; the Video
Editor's `proof_quote_cap` refused all four after the voice (8-32 s a quote,
up to 32 s of 32 s). `scripts/check_proof_quotes.py` asks the same before the
voice, on the script's own stretches or on the block layout
`check_block_capacity.py` recorded for it.

Every batch is built in a temp directory from shapes copied from 0839Z (a
HomePod-like topic with one Apple clip in its pool; a ChatGPT-like topic with
our recordings and an OpenAI clip) - no pipeline, no pool, no network. The
root's channel files are read as code.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489)
_TMP = tmp_root("cr-pq-")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import check_proof_quotes as cpq  # noqa: E402
import check_narration_budget as cnb  # noqa: E402
import _rewrite_guard as rg  # noqa: E402

ROOT = cnb.find_root()
SKILL = (REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
README = (REPO / "README.md").read_text()

TECH = "example-tech"
TOPIC = "tech-010"
SID = "tech-010-script1"
VENDOR = "xLL4UnrLNWs0"                       # an Apple upload (0839Z HomePod's pool)
VENDOR2 = "QeQAXuQpGEA0"
OWN = "own_capture-acme-prompt-generator-1"   # our recording
RATE = 2.0                                    # words a second: seconds = words / 2
SECTIONS = ("hook", "commentary", "payoff")

# 10 + 10 + 10 + 10 words of commentary, 4 of hook, 6 of payoff - 50 words, 25 s.
HOOK = "HomePod now runs four."
S1 = "Paired with an Apple TV the refreshed HomePod supports theater."
S2 = "It comes in five colors from white to deep blue."
S3 = "The mini two ships on October twenty first in stores."
S4 = "It costs ninety nine dollars, the same as the first."
PAYOFF = "Same price, more speakers, new colors."
COMMENTARY = " ".join([S1, S2, S3, S4])


def _phrase(aid, beat, side=None):
    return {"anchor_id": aid, "phrase": f"HomePod mini tops from above, shot {aid}",
            "beat_text": beat, "side": side}


def _graphic(aid, gid, beat):
    return {"anchor_id": aid, "graphic_id": gid, "beat_text": beat}


def _script(anchors, **extra):
    s = {"script_id": SID, "topic_id": TOPIC,
         "pattern": {"pattern_id": "explainer", "rhythm_id": "even", "parameters": {}},
         "hook": HOOK, "commentary": COMMENTARY, "payoff": PAYOFF,
         "narration": {"estimated_words_per_second": RATE},
         "visual_anchors": anchors}
    s.update(extra)
    return s


def _all_on_the_vendor():
    """0839Z HomePod: five pool phrases, one Apple clip, no graphic."""
    return _script([_phrase("v1", HOOK), _phrase("v2", S1), _phrase("v3", S2),
                    _phrase("v4", S3), _phrase("v5", S4)])


PROOF = "the refreshed HomePod supports theater."   # the second half of S1


def _on_graphics():
    """The same story on its own graphics, one quote under the words it proves:
    the Apple clip on "Paired with an Apple TV" (5 words, 2.5 s), a graphic
    from "the refreshed HomePod ..." on."""
    return _script([_graphic("v1", "g1", HOOK), _phrase("v2", S1),
                    _graphic("v3", "g2", PROOF), _graphic("v4", "g3", S3),
                    _graphic("v5", "g4", S4)],
                   graphics=[{"graphic_id": g} for g in ("g1", "g2", "g3", "g4")])


def _topic(own=False):
    cands = [{"video_id": VENDOR, "role": "proof_quote", "footage_origin": "vendor_official"}]
    if own:
        cands.insert(0, {"video_id": "own_capture:acme-prompt-generator-1",
                         "kind": "own_capture", "role": "base"})
    return {"topic_id": TOPIC, "evidence": {"footage_candidates": cands}}


def _layout(script, blocks, stamp=True):
    """A `block_capacity` record as check_block_capacity.py writes it:
    `blocks` is `[(anchor index, seconds, shots, own_graphic)]`."""
    rec = {"blocks": [{"block": i, "anchor": a, "seconds": sec, "shots": list(shots),
                       **({"own_graphic": True} if g else {})}
                      for i, (a, sec, shots, g) in enumerate(blocks)]}
    if stamp:
        rg.stamp(rec, script, SECTIONS)
    script["block_capacity"] = rec
    return script


class Bench:
    def __init__(self, scripts, pool=(VENDOR,), topic=None, channel=TECH, index=True,
                 trend=True):
        self.dir = Path(tempfile.mkdtemp(dir=_TMP))
        self.batch = self.dir / "03-content-researcher.json"
        self.batch.write_text(json.dumps({"channel": channel, "scripts": scripts}))
        if trend:
            (self.dir / "01-trend-hunter.json").write_text(
                json.dumps({"topics": [topic if topic is not None else _topic()]}))
        if index:
            (self.dir / "01b-footage-index.json").write_text(
                json.dumps({"sources_by_topic": {TOPIC: list(pool)}}))
        self.lines = []

    def check(self):
        return cpq.check_batch(self.batch, root=ROOT, out=self.lines.append)

    def codes(self):
        return [c for found in self.check().values() for c, _d in found]

    def run(self):
        return cpq.main([str(self.batch), "--root", str(ROOT)])

    def text(self):
        return "\n".join(self.lines)


# --------------------------------------------------------------------------
# the 0839Z shape: every anchor on the vendor's clip
# --------------------------------------------------------------------------

def test_a_script_all_on_the_vendors_clip_is_refused_before_the_voice():
    b = Bench([_all_on_the_vendor()])
    codes = b.codes()
    assert codes == [cpq.CODE_TOO_LONG, cpq.CODE_OVER_TOTAL, cpq.CODE_IS_BASE], b.text()
    assert "25.0 s of 25.0 s" in b.text() and "0 graphic anchor(s)" in b.text(), b.text()
    assert "measured on anchor_stretches" in b.text()
    assert "«Own graphics»" in b.text() and "graphics[]" in b.text()
    assert b.run() == cpq.EXIT_FINDING


def test_the_same_story_on_its_own_graphics_with_one_quote_passes():
    b = Bench([_on_graphics()])
    assert b.check() == {SID: []}, b.text()
    assert "ok    " in b.text() and "4 graphic anchor(s)" in b.text(), b.text()
    assert "quotes 2.5 s in 1 of 25.0 s, own 22.5 s" in b.text(), b.text()
    assert b.run() == cpq.EXIT_OK


def test_a_quote_under_more_words_than_its_cap_is_too_long():
    s = _on_graphics()
    # move the graphic after the quote one sentence later: the quote stands 10 s
    s["visual_anchors"][2] = _graphic("v3", "g2", S3)
    s["visual_anchors"][3] = _graphic("v4", "g3", S4)
    del s["visual_anchors"][4]
    found = Bench([s]).check()[SID]
    assert [c for c, _ in found] == [cpq.CODE_TOO_LONG, cpq.CODE_OVER_TOTAL], found
    assert "v2" in found[0][1] and "10.0 s" in found[0][1], found


def test_the_estimate_margin_refuses_a_quote_right_on_the_cap():
    # S1 is 10 words: 5.0 s at 2 w/s - exactly the cap, over it less the margin
    s = _script([_graphic("v1", "g1", HOOK), _phrase("v2", S1), _graphic("v3", "g2", S2)],
                graphics=[{"graphic_id": "g1"}, {"graphic_id": "g2"}])
    reading = cpq.judge(s, {"max_seconds_per_quote": 5.0}, RATE, SECTIONS, [VENDOR])
    assert [c for c, _ in reading[0]] == [cpq.CODE_TOO_LONG], reading
    reading = cpq.judge(s, {"max_seconds_per_quote": 5.5}, RATE, SECTIONS, [VENDOR])
    assert reading[0] == [], reading


def test_two_quotes_back_to_back_are_one_quote_unless_the_layout_names_two_clips():
    s = _script([_graphic("v1", "g1", HOOK), _phrase("v2", S1), _phrase("v3", S2),
                 _graphic("v4", "g2", S3)], graphics=[{"graphic_id": "g1"}, {"graphic_id": "g2"}])
    found, reading = cpq.judge(s, {"max_seconds_per_quote": 30.0}, RATE, SECTIONS, [VENDOR])
    assert len(reading["quotes"]) == 1 and reading["quotes"][0]["anchors"] == ["v2", "v3"]
    # the Editor's layout names two different clips: two quotes
    _layout(s, [(0, 2.0, [], True), (1, 5.0, [f"{VENDOR}:1"], False),
                (2, 5.0, [f"{VENDOR2}:3"], False), (3, 13.0, [], True)])
    found, reading = cpq.judge(s, {"max_seconds_per_quote": 30.0}, RATE, SECTIONS, [VENDOR])
    assert reading["measured_on"] == "block_capacity"
    assert [q["sources"] for q in reading["quotes"]] == [[VENDOR], [VENDOR2]], reading


def test_quotes_over_the_count_are_too_many():
    s = _script([_phrase("v1", HOOK), _graphic("v2", "g1", S1), _phrase("v3", S2),
                 _graphic("v4", "g2", S3), _phrase("v5", S4), _graphic("v6", "g3", PAYOFF)],
                graphics=[{"graphic_id": g} for g in ("g1", "g2", "g3")])
    found, reading = cpq.judge(s, {"max_quotes_per_video": 2}, RATE, SECTIONS, [VENDOR])
    assert [c for c, _ in found] == [cpq.CODE_TOO_MANY] and len(reading["quotes"]) == 3, found


# --------------------------------------------------------------------------
# the Editor's layout (check_block_capacity.py) when it is current
# --------------------------------------------------------------------------

def test_a_mixed_pool_is_read_off_the_recorded_layout():
    """0839Z ChatGPT: our recordings and an OpenAI clip in the pool - the
    layout names which blocks get the vendor's clip (here 3 of 5, 15 s)."""
    s = _script([_phrase("v1", HOOK), _phrase("v2", S1), _phrase("v3", S2),
                 _phrase("v4", S3), _phrase("v5", S4)])
    _layout(s, [(0, 2.0, [f"{OWN}:0"], False), (1, 5.0, [f"{VENDOR}:1"], False),
                (2, 5.0, [f"{VENDOR}:2"], False), (3, 5.0, [f"{OWN}:1"], False),
                (4, 8.0, [f"{VENDOR}:0", f"{VENDOR}:9"], False)])
    b = Bench([s], pool=(OWN, VENDOR), topic=_topic(own=True))
    found = b.check()[SID]
    assert [c for c, _ in found] == [cpq.CODE_TOO_LONG, cpq.CODE_TOO_LONG,
                                     cpq.CODE_OVER_TOTAL, cpq.CODE_IS_BASE], b.text()
    assert "measured on block_capacity" in b.text()
    assert "block(s) [1, 2]" in b.text() and "block(s) [4]" in b.text(), b.text()


def test_a_stale_layout_is_not_read_and_a_mixed_pool_is_left_to_the_editor():
    s = _script([_phrase("v1", HOOK), _phrase("v2", S1), _phrase("v3", S2)])
    _layout(s, [(0, 25.0, [f"{VENDOR}:1"], False)], stamp=False)
    s["block_capacity"]["script_hash"] = "sha256:not-this-script"
    b = Bench([s], pool=(OWN, VENDOR), topic=_topic(own=True))
    assert b.check() == {SID: []}, b.text()
    assert "measured on anchor_stretches" in b.text()
    assert "25.0 s left to the Editor" in b.text()
    assert "check_block_capacity.py --write" in b.text()


def test_an_empty_block_on_a_quotes_only_pool_is_a_quote():
    """0839Z HomePod: blocks 3 and 4 had no shot left - the Editor still cut the
    one Apple clip there (32.23 s of 32.23 s)."""
    s = _all_on_the_vendor()
    _layout(s, [(0, 7.0, [f"{VENDOR}:4"], False), (1, 5.5, [f"{VENDOR}:6"], False),
                (2, 4.3, [f"{VENDOR}:4"], False), (3, 7.7, [], False), (4, 0.5, [], False)])
    found, reading = cpq.judge(s, {"never_the_base": True, "max_seconds_per_quote": 5.0},
                               RATE, SECTIONS, [VENDOR])
    assert reading["quote_seconds"] == 25.0 and len(reading["quotes"]) == 1, reading
    assert [c for c, _ in found] == [cpq.CODE_TOO_LONG, cpq.CODE_IS_BASE], found


def test_a_graphic_block_in_the_layout_is_ours():
    s = _on_graphics()
    _layout(s, [(0, 2.0, [], True), (1, 4.0, [f"{VENDOR}:1"], False),
                (2, 5.0, [], True), (3, 5.0, [], True), (4, 9.0, [], True)])
    found, reading = cpq.judge(s, {"never_the_base": True, "max_seconds_per_quote": 5.0,
                                   "max_quotes_per_video": 2, "max_seconds_per_video": 8.0},
                               RATE, SECTIONS, [VENDOR])
    assert found == [] and reading["own_seconds"] == 21.0 and reading["quote_seconds"] == 4.0


# --------------------------------------------------------------------------
# where it does not apply, and what it cannot answer
# --------------------------------------------------------------------------

def test_a_channel_without_proof_quotes_is_untouched():
    for ch in ("example-film", "example-science"):
        b = Bench([_all_on_the_vendor()], channel=ch)
        assert b.check() == {}, b.text()
        assert "no proof_quotes on channel" in b.text()
        assert b.run() == cpq.EXIT_OK


def test_without_the_pool_files_a_stretch_with_no_shot_is_unknown():
    b = Bench([_all_on_the_vendor()], index=False, trend=False)
    assert b.check() == {SID: []}, b.text()
    assert "25.0 s left to the Editor" in b.text()
    # the Trend Hunter's candidates stand in for the pool when 01b is missing
    assert Bench([_all_on_the_vendor()], index=False).codes() != []


def test_cannot_answer_without_the_batch_or_with_a_beat_not_spoken():
    assert cpq.main([str(_TMP / "nope.json"), "--root", str(ROOT)]) == cpq.EXIT_CANNOT_ANSWER
    s = _all_on_the_vendor()
    s["visual_anchors"][2]["beat_text"] = "words nobody says"
    assert Bench([s]).run() == cpq.EXIT_CANNOT_ANSWER


def test_the_codes_are_the_video_editors_words():
    assert cpq.CODES == ("quote_too_long", "too_many_quotes", "quotes_over_video_total",
                         "quote_is_the_base")


# --------------------------------------------------------------------------
# the SKILL and the README say it
# --------------------------------------------------------------------------

def test_the_skill_runs_the_check_and_explains_every_code():
    assert "check_proof_quotes.py" in SKILL and "`check-proof-quotes`" in SKILL
    for code in cpq.CODES:
        assert f"`{code}`" in SKILL, code
    for words in ("CF-0774", "max_seconds_per_quote", "never_the_base", "2026-10-16T0839Z",
                  "block_capacity"):
        assert words in SKILL, words


def test_the_skill_makes_graphics_the_base_on_a_capped_channel():
    flat = " ".join(SKILL.split())
    assert "the base of the video is our own footage" in flat
    assert "a pool `phrase` on a vendor's clip is a quote" in flat
    assert "**graphics first**" in flat


def test_the_readme_lists_the_check():
    assert "`check_proof_quotes.py`" in README and "CF-0774" in README


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
