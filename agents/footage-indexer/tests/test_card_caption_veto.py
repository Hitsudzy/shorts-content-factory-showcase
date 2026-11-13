#!/usr/bin/env python3
"""CF-0093: index_footage.card_verdict() and probe_card_text() without
Vision, ffmpeg or footage.

card_verdict() is the whole is_card decision for one shot - CLIP similarity
plus the two rates probe_card_text() returns. The fix is one clause: a shot
above CARD_THRESHOLD is no longer a card on CLIP alone when at least
CAPTION_VETO_RATE of its frames read as a caption on a picture and fewer
than CARD_TEXT_MIN_HIT_RATE read as card text. Every other path is the
CF-0010 rule unchanged, and the tests say so explicitly.

probe_card_text() is exercised with its collaborators stubbed - ffmpeg
replaced by a function that writes a synthetic frame, Vision by a function
that returns scripted boxes, cropdetect by a constant - so what is checked
is the aggregation: which per-frame verdicts land in which rate, the
letterbox crop reaching ffmpeg's command line, and the empty case.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402
from index_footage import (  # noqa: E402
    CAPTION_VETO_RATE, CARD_TEXT_MIN_HIT_RATE, CARD_THRESHOLD,
    CARD_THRESHOLD_LOW, card_verdict)

HIGH = CARD_THRESHOLD + 0.03        # comfortably a card on CLIP alone
BETWEEN = (CARD_THRESHOLD + CARD_THRESHOLD_LOW) / 2
LOW = CARD_THRESHOLD_LOW - 0.01


def test_thresholds_are_ordered_as_the_rule_assumes():
    assert 0.0 < CARD_THRESHOLD_LOW < CARD_THRESHOLD < 1.0
    assert 0.0 < CARD_TEXT_MIN_HIT_RATE < CAPTION_VETO_RATE <= 1.0
    # The veto asks for the caption reading to be the shot's *dominant*
    # one, not the occasional one the card rate is allowed to be.
    assert CAPTION_VETO_RATE == 0.5


# --- the CF-0010 rule, unchanged ------------------------------------------

def test_high_sim_without_caption_evidence_is_a_card():
    """A logo animation or a card whose text Vision never caught: no
    text of either kind, CLIP alone decides - as before CF-0093."""
    assert card_verdict(HIGH, 0.0, 0.0) is True
    assert card_verdict(HIGH, 0.0) is True  # caption_rate defaults to 0.0
    assert card_verdict(HIGH, 1.0, 0.0) is True


def test_between_thresholds_needs_card_text():
    assert card_verdict(BETWEEN, CARD_TEXT_MIN_HIT_RATE, 0.0) is True
    assert card_verdict(BETWEEN, 1.0, 0.0) is True
    assert card_verdict(BETWEEN, CARD_TEXT_MIN_HIT_RATE - 0.01, 0.0) is False
    assert card_verdict(BETWEEN, 0.0, 0.0) is False


def test_below_low_threshold_is_never_a_card():
    """Whatever the text probe says - a book page filling the frame gets
    a card text rate of 1.0 and is still not a card at this similarity."""
    assert card_verdict(LOW, 1.0, 0.0) is False
    assert card_verdict(LOW, 1.0, 1.0) is False
    assert card_verdict(0.0, 1.0, 0.0) is False


# --- the CF-0093 veto -----------------------------------------------------

def test_le_monde_talking_head_is_vetoed():
    """ScKvReYRZ-A s0: a vertical Le Monde talking head with French
    subtitles, CLIP 0.2631 - a hair over CARD_THRESHOLD - and every sampled
    frame reading as a caption on a picture. This is the shot that was its
    source's only shot, tagged is_card, and crashed match_anchors (CF-0083).
    """
    sim = 0.2631
    assert sim >= CARD_THRESHOLD
    assert card_verdict(sim, 0.0, 1.0) is False
    # Same shot under the pre-CF-0093 rule (no caption rate): a card.
    assert card_verdict(sim, 0.0) is True


def test_captioned_trailer_wide_is_vetoed():
    """1RnyZgfN-JY s11: a captioned trailer wide, CLIP 0.2674, remeasured
    at card 0.0 / caption 1.0."""
    assert card_verdict(0.2674, 0.0, 1.0) is False


def test_veto_needs_caption_rate_at_least_the_veto_rate():
    """Below CAPTION_VETO_RATE the caption reading is not the shot's
    dominant one and CLIP keeps its say."""
    assert card_verdict(HIGH, 0.0, CAPTION_VETO_RATE) is False
    assert card_verdict(HIGH, 0.0, CAPTION_VETO_RATE - 0.01) is True
    assert card_verdict(HIGH, 0.0, 0.25) is True
    assert card_verdict(HIGH, 0.0, 0.0) is True


def test_veto_needs_card_rate_below_the_hit_rate():
    """A shot with captions on some frames *and* card text on enough
    others (a card whose subtitle track keeps running, ZZ_urA56pJE s33
    remeasured at card 0.75 / caption 0.25) is not vetoed: the card
    evidence is there, and the CF-0010 rule says it counts from
    CARD_TEXT_MIN_HIT_RATE up."""
    assert card_verdict(HIGH, CARD_TEXT_MIN_HIT_RATE, 1.0) is True
    assert card_verdict(HIGH, 0.75, 0.25) is True
    assert card_verdict(HIGH, CARD_TEXT_MIN_HIT_RATE - 0.01, 1.0) is False
    # Both rates from the same sampled frames: a shot cannot exceed 1.0
    # in total, so card 0.25 / caption 0.75 is the tightest real case.
    assert card_verdict(HIGH, 0.25, 0.75) is True
    assert card_verdict(HIGH, 0.2, 0.8) is False


def test_veto_does_not_reach_below_card_threshold():
    """The veto is an exception to "high CLIP is sufficient alone"; the
    between-thresholds path never trusted CLIP alone, so a caption rate
    there changes nothing either way."""
    assert card_verdict(BETWEEN, 1.0, 1.0) is True      # card text present: card
    assert card_verdict(BETWEEN, 0.0, 1.0) is False     # absent: not a card, as before
    assert card_verdict(BETWEEN, 0.0, 0.0) is False


def test_verdict_at_the_exact_thresholds():
    assert card_verdict(CARD_THRESHOLD, 0.0, 0.0) is True
    assert card_verdict(CARD_THRESHOLD, 0.0, CAPTION_VETO_RATE) is False
    assert card_verdict(CARD_THRESHOLD_LOW, CARD_TEXT_MIN_HIT_RATE, 0.0) is True
    assert card_verdict(CARD_THRESHOLD_LOW, CARD_TEXT_MIN_HIT_RATE, 1.0) is True


# --- probe_card_text() aggregation, collaborators stubbed -------------------

class Stubs:
    """Replace ffmpeg, cropdetect and Vision inside index_footage for one
    probe run; restore on exit whatever happened."""

    def __init__(self, frame_regions, bars="", person=None):
        # frame_regions[i] is what Vision 'sees' on the i-th sampled frame.
        self.frame_regions = frame_regions
        self.bars = bars
        # CF-0413: what Vision's faces say about a card-reading frame - None
        # (no face) unless a test says otherwise; `person_calls` counts how
        # often the probe asked.
        self.person = person
        self.person_calls = 0
        self.commands = []
        self.saved = {}

    def __enter__(self):
        self.saved = {"run": ix.subprocess.run,
                      "letterbox": ix.detect_letterbox,
                      "regions": ix.detect_text_band.sample_text_regions,
                      "person": ix.person_in_frame}
        ix.subprocess.run = self.fake_ffmpeg
        ix.person_in_frame = self.fake_person
        ix.detect_letterbox = lambda *a, **k: self.bars
        ix.detect_text_band.sample_text_regions = self.fake_vision
        return self

    def __exit__(self, *exc):
        ix.subprocess.run = self.saved["run"]
        ix.detect_letterbox = self.saved["letterbox"]
        ix.detect_text_band.sample_text_regions = self.saved["regions"]
        ix.person_in_frame = self.saved["person"]
        return False

    def fake_person(self, frame):
        self.person_calls += 1
        return self.person

    def fake_ffmpeg(self, cmd, **kwargs):
        """CF-0331: one call a shot writing `ct%02d.png`, not one a frame.
        It writes as many frames as ffmpeg would: `-frames:v` of them, or
        fewer when `frame_regions` says the source ran out - the probe's
        "ffmpeg wrote fewer than asked" path."""
        self.commands.append(cmd)
        pattern = Path(cmd[-1])
        asked = int(cmd[cmd.index("-frames:v") + 1])
        for i in range(min(asked, len(self.frame_regions))):
            # The picture ground: noisy for every frame; the regions decide
            # the verdict via headline size, so no flat frames are needed.
            rng = np.random.RandomState(i)
            px = rng.randint(0, 256, size=(90, 160, 3), dtype=np.uint8)
            Image.fromarray(px, "RGB").save(pattern.parent / f"ct{i:02d}.png")
        # CF-0331: the call goes through runlog.run_child now, which records
        # the return code, so the stub answers like subprocess.run does.
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def fake_vision(self, frame, level=0):
        i = int(Path(frame).stem[2:])
        return self.frame_regions[i]


def box(top, left, width, height):
    return {"top": top, "bottom": top + height, "left": left,
            "width": width, "height": height}


HEADLINE = [box(0.4, 0.1, 0.8, 0.15)]      # card-sized
SUBTITLE = [box(0.85, 0.2, 0.6, 0.05)]     # caption-sized, on a noisy ground
NOTHING = []


def test_probe_splits_frames_into_the_two_rates():
    """8 frames: 2 card, 4 caption, 2 silent -> card 0.25, caption 0.5 -
    exactly the pair that makes card_verdict() keep the shot a card (the
    card rate reaches CARD_TEXT_MIN_HIT_RATE), and would veto it one card
    frame fewer."""
    frames = [HEADLINE, SUBTITLE, NOTHING, SUBTITLE, HEADLINE, SUBTITLE, NOTHING, SUBTITLE]
    with Stubs(frames) as s:
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    assert rates == {"card": 0.25, "caption": 0.5, "branding": 0.0}, rates
    # CF-0331: one ffmpeg for the whole shot, asked for all 8 frames.
    assert len(s.commands) == 1, s.commands
    assert s.commands[0][s.commands[0].index("-frames:v") + 1] == "8"
    assert card_verdict(HIGH, rates["card"], rates["caption"]) is True
    frames[0] = SUBTITLE
    with Stubs(frames):
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    assert rates == {"card": 0.125, "caption": 0.625, "branding": 0.0}, rates
    assert card_verdict(HIGH, rates["card"], rates["caption"]) is False


def test_probe_rates_are_over_frames_actually_sampled():
    """Frames ffmpeg failed to write are not in the denominator (as
    before CF-0093): 4 of 8 written, all captions -> caption 1.0."""
    frames = [SUBTITLE] * 4
    with Stubs(frames):
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    assert rates == {"card": 0.0, "caption": 1.0, "branding": 0.0}, rates


def test_probe_with_no_frames_is_zero_zero():
    with Stubs([]):
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    assert rates == {"card": 0.0, "caption": 0.0, "branding": 0.0}, rates
    # And CLIP alone decides for such a shot, as before.
    assert card_verdict(HIGH, **{"card_text_rate": rates["card"], "caption_rate": rates["caption"]}) is True


def test_probe_crops_bars_before_measuring():
    """The letterbox/pillarbox crop reaches ffmpeg as -vf on every sample
    when cropdetect found bars, and is absent when it did not."""
    with Stubs([SUBTITLE] * 8, bars="crop=748:1080:586:0") as s:
        ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    for cmd in s.commands:
        vf = cmd[cmd.index("-vf") + 1]
        # CF-0331: the crop leads the filter chain, so it still happens
        # before anything else looks at the frame.
        assert vf.startswith("crop=748:1080:586:0,"), cmd
        assert cmd.index("-vf") < cmd.index("-frames:v"), cmd
    with Stubs([SUBTITLE] * 8, bars="") as s:
        ix.probe_card_text("/nonexistent.mp4", 0.0, 8.0, samples=8)
    for cmd in s.commands:
        assert "crop=" not in cmd[cmd.index("-vf") + 1], cmd


def test_probe_default_sample_count_scales_with_duration():
    """samples=None keeps the CF-0010 rule: max(8, min(20, round(s)))."""
    def asked_for(start, end):
        with Stubs([NOTHING] * 20) as s:
            ix.probe_card_text("/nonexistent.mp4", start, end)
        # CF-0331: the count is what the single call asks for, not how many
        # calls there were.
        assert len(s.commands) == 1, s.commands
        cmd = s.commands[0]
        return int(cmd[cmd.index("-frames:v") + 1])

    assert asked_for(0.0, 3.0) == 8
    assert asked_for(10.0, 24.0) == 14
    assert asked_for(0.0, 90.0) == 20


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
