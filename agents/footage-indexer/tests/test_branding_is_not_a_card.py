#!/usr/bin/env python3
"""CF-0413: a person with branding at the edge of the frame is not a card.

The backrooms rebuild of batch 0929Z (pipeline/rebuilds/2026-09-27T1757Z)
laid three blocks as letterboxed cards on interview close-ups from the
podcast 3oy35kY7guU: the podcast's logo and a name plate sit in the lower
corners of every interview shot, the logo line is headline-sized, so every
sampled frame read as card text and nine of the guest's close-ups came out
`is_card: true`. The user's rule of 2026-09-28: branding of an interview is
not a card. The branding stays foreign text on the shot (`burned_text`,
judged as before); what changes is only the card flag.

Four layers, cheapest first:
  - card_frame.is_branding() on the geometry measured on real frames of that
    source (Vision's boxes and faces, copied from the measurement run) -
    pure, no Vision;
  - card_verdict() with the new branding rate;
  - probe_card_text()'s aggregation with Vision, ffmpeg and faces stubbed
    (test_card_caption_veto.Stubs), including that faces are asked only on
    card-reading frames;
  - the regression on the real footage: the nine shots the orchestrator
    unflagged by hand, from the pre-fix index kept in the rebuild, go
    card -> not card, and the same source's real cards keep card text. The
    pool is transient (sources are deleted after publishing), so this part
    prints a NOTE and passes when the footage or the backup is gone - the
    same convention as test_card_probe_real_footage.py.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import card_frame  # noqa: E402
import index_footage as ix  # noqa: E402
from card_frame import BRANDING_MAX_KEPT, PERSON_MIN_FACE_HEIGHT  # noqa: E402
from index_footage import (  # noqa: E402
    CAPTION_VETO_RATE, CARD_TEXT_MIN_HIT_RATE, CARD_THRESHOLD,
    CARD_THRESHOLD_LOW, card_verdict)
from test_card_caption_veto import HEADLINE, SUBTITLE, Stubs  # noqa: E402

HIGH = CARD_THRESHOLD + 0.03
BETWEEN = (CARD_THRESHOLD + CARD_THRESHOLD_LOW) / 2
SIZE = (1920, 1080)


def box(top, left, width, height):
    return {"top": top, "bottom": top + height, "left": left,
            "width": width, "height": height}


def person(face):
    """What index_footage.person_in_frame() hands is_branding() for one face
    (x, y, w, h as fractions): the real smart_crop window, not a copy."""
    w, h = SIZE
    info = {"roi_source": "faces", "source_size": {"width": w, "height": h},
            "roi": {"x": face[0] * w, "y": face[1] * h,
                    "width": face[2] * w, "height": face[3] * h}}
    x, y, cw, ch = ix.smart_crop.delivered_window(
        SIZE, ix.smart_crop.focus_point(info), 1.0, 1080, 1920, "cover")
    return {"face_height": face[3], "window": (x / w, y / h, cw / w, ch / h)}


# Measured on 3oy35kY7guU (Vision accurate-mode boxes, find_roi faces).
# s25, the guest's close-up: logo lower right, name plate lower left.
GUEST_TEXT = [box(0.69, 0.0, 0.038, 0.025), box(0.807, 0.0, 0.14, 0.053),
              box(0.867, 0.028, 0.157, 0.052), box(0.618, 0.702, 0.142, 0.181),
              box(0.769, 0.725, 0.273, 0.151), box(0.93, 0.803, 0.195, 0.072)]
GUEST_FACE = (0.265, 0.124, 0.113, 0.214)
# s15, the other guest's close-up: same overlay, bigger face.
HOST_FACE = (0.241, 0.14, 0.147, 0.277)
# s59, the podcast's outro card: the host's photo, the logo on the left and
# 'with Christina Jeurling Birro' running under her.
OUTRO_TEXT = [box(0.088, 0.013, 0.174, 0.214), box(0.27, 0.045, 0.349, 0.181),
              box(0.47, 0.136, 0.251, 0.084), box(0.68, 0.401, 0.425, 0.131),
              box(0.821, 0.535, 0.425, 0.158)]
OUTRO_FACE = (0.487, 0.203, 0.233, 0.414)
# s4, the 'Backrooms' film title over a scene with a woman in it.
TITLE_TEXT = [box(0.064, 0.221, 0.555, 0.163), box(0.917, 0.792, 0.16, 0.044),
              box(0.956, 0.754, 0.234, 0.039)]
TITLE_FACE = (0.482, 0.4, 0.078, 0.139)


# --- card_frame.is_branding() ----------------------------------------------

def test_the_constants_are_the_measured_ones():
    assert PERSON_MIN_FACE_HEIGHT == 0.15
    assert BRANDING_MAX_KEPT == 0.2


def test_interview_close_up_with_corner_branding_is_branding():
    # Both routes into "card" are there - the logo line is headline-sized -
    # and none of that text is inside the window the reel shows.
    assert card_frame.has_headline(GUEST_TEXT)
    p = person(GUEST_FACE)
    assert card_frame.kept_in_window(card_frame.card_text(GUEST_TEXT), p["window"]) == 0.0
    assert card_frame.is_branding(GUEST_TEXT, p) is True
    assert card_frame.is_branding(GUEST_TEXT, person(HOST_FACE)) is True


def test_no_face_is_never_branding():
    assert card_frame.is_branding(GUEST_TEXT, None) is False


def test_a_small_face_is_not_the_frames_subject():
    """The same corner text beside a face below PERSON_MIN_FACE_HEIGHT - a
    figure in a wide picture - leaves the frame the card it read as."""
    small = GUEST_FACE[:3] + (PERSON_MIN_FACE_HEIGHT - 0.01,)
    assert card_frame.is_branding(GUEST_TEXT, person(small)) is False
    at = GUEST_FACE[:3] + (PERSON_MIN_FACE_HEIGHT,)
    assert card_frame.is_branding(GUEST_TEXT, person(at)) is True


def test_outro_card_text_under_the_host_stays_a_card():
    p = person(OUTRO_FACE)
    kept = card_frame.kept_in_window(card_frame.card_text(OUTRO_TEXT), p["window"])
    assert kept > BRANDING_MAX_KEPT, kept
    assert card_frame.is_branding(OUTRO_TEXT, p) is False


def test_title_over_a_scene_stays_a_card():
    # The real face is under the floor ...
    assert card_frame.is_branding(TITLE_TEXT, person(TITLE_FACE)) is False
    # ... and at the tallest this shot's face measured (0.169) the title
    # still runs through its window.
    tall = TITLE_FACE[:3] + (0.169,)
    assert card_frame.is_branding(TITLE_TEXT, person(tall)) is False


def test_card_text_is_the_headline_when_there_is_one():
    """A subtitle under the person does not rescue branding into a card:
    only the headline lines made the frame a card, so only they are asked
    where they sit."""
    under = GUEST_TEXT + [box(0.85, 0.2, 0.2, 0.05)]
    assert card_frame.card_text(under) == [r for r in under if r["height"] >= 0.10
                                           and r["width"] >= r["height"]]
    assert card_frame.is_branding(under, person(GUEST_FACE)) is True
    # Without a headline the whole text is the card text (the flat route).
    small = [box(0.85, 0.2, 0.2, 0.05)]
    assert card_frame.card_text(small) == small


def test_kept_in_window_arithmetic():
    assert card_frame.kept_in_window([box(0.0, 0.0, 0.5, 0.5)], (0.0, 0.0, 0.25, 1.0)) == 0.5
    assert card_frame.kept_in_window([box(0.0, 0.6, 0.2, 0.2)], (0.0, 0.0, 0.5, 1.0)) == 0.0
    assert card_frame.kept_in_window([], (0.0, 0.0, 1.0, 1.0)) is None


# --- card_verdict() with the branding rate ---------------------------------

def test_branding_frames_do_not_carry_a_shot_over_the_text_bar():
    # The nine shots' own picture: every frame branding, no card text.
    assert card_verdict(BETWEEN, 0.0, 0.0, 1.0) is False
    # Under the pre-CF-0413 reading the same frames were card text.
    assert card_verdict(BETWEEN, 1.0, 0.0) is True


def test_branding_joins_captions_in_the_high_clip_veto():
    assert card_verdict(HIGH, 0.0, 0.0, 1.0) is False
    assert card_verdict(HIGH, 0.0, 0.25, 0.25) is False    # 0.5 together
    assert card_verdict(HIGH, 0.0, 0.25, 0.24) is True     # under the veto rate
    # Card text on enough frames still wins, as it does over captions.
    assert card_verdict(HIGH, CARD_TEXT_MIN_HIT_RATE, 0.0, 0.75) is True
    assert card_verdict(BETWEEN, CARD_TEXT_MIN_HIT_RATE, 0.0, 0.75) is True
    assert CAPTION_VETO_RATE == 0.5


def test_branding_rate_defaults_to_zero():
    assert card_verdict(HIGH, 0.0, 0.0) is True
    assert card_verdict(BETWEEN, 1.0, 0.0) is True


# --- probe_card_text() aggregation, stubbed --------------------------------

def test_probe_counts_branding_frames_apart_from_card_frames():
    frames = [HEADLINE] * 4
    beside = {"face_height": 0.25, "window": (0.0, 0.0, 0.05, 1.0)}   # text is at 0.1-0.9
    with Stubs(frames, person=beside) as s:
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 4.0, samples=4)
    assert rates == {"card": 0.0, "caption": 0.0, "branding": 1.0}, rates
    assert s.person_calls == 4
    over = {"face_height": 0.25, "window": (0.3, 0.0, 0.32, 1.0)}     # text runs through it
    with Stubs(frames, person=over):
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 4.0, samples=4)
    assert rates == {"card": 1.0, "caption": 0.0, "branding": 0.0}, rates


def test_faces_are_asked_only_on_card_reading_frames():
    frames = [SUBTITLE, [], HEADLINE, SUBTITLE]
    with Stubs(frames, person=None) as s:
        rates = ix.probe_card_text("/nonexistent.mp4", 0.0, 4.0, samples=4)
    assert s.person_calls == 1
    assert rates == {"card": 0.25, "caption": 0.5, "branding": 0.0}, rates


# --- the skill says what the code does ---------------------------------------

def test_skill_states_the_rule_with_the_codes_numbers():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer" / "SKILL.md").read_text()
    section = skill[skill.index("## A person with branding at the edge is not a card (CF-0413"):]
    section = section[:section.index("\n## ", 1)]
    assert f"**{PERSON_MIN_FACE_HEIGHT}**" in section, section
    assert f"**{BRANDING_MAX_KEPT}**" in section, section
    assert "`branding_hit_rate`" in section
    # The describer's flag is untouched and the pool is not re-indexed.
    assert "`burned_text` is yours and is judged exactly as before" in section
    assert "do not re-index the old pool" in section


# --- the regression on the real footage -------------------------------------

from _fi_paths import factory_root  # noqa: E402 - CF-0267: the root, not parents[N]
from _live_monitors import live_only  # noqa: E402
SOURCE = "3oy35kY7guU"
# The nine shots the orchestrator unflagged by hand (backup vs the pool's
# index): the guest's close-ups, blocks 7/11/13 of the rebuild.
UNFLAGGED = [25, 27, 32, 36, 38, 41, 45, 48, 50]
# The same source's real cards: the podcast's intro/outro title cards and
# the 'Backrooms' film title.
KEPT_CARDS = [1, 4, 59]
SAMPLES = 4


def _real():
    """CF-0505: a live monitor - the real mp4 and the rebuild's pre-fix index.
    In the suite it steps aside (FI_TESTS_LIVE=1 runs it)."""
    if live_only("test_branding_is_not_a_card.py::_real"):
        return None, None
    ROOT = factory_root()
    FOOTAGE = Path(os.environ.get("FOOTAGE_DIR") or ROOT / "shared" / "footage")
    BACKUP = Path(os.environ.get("CF0413_BACKUP") or ROOT / "pipeline" / "rebuilds"
                  / "2026-09-27T1757Z" / "work" / "backrooms" / f"{SOURCE}.shots.before-orch.json")
    video = FOOTAGE / f"{SOURCE}.mp4"
    if not (video.exists() and BACKUP.exists()):
        print(f"  NOTE: {SOURCE} footage or the rebuild's pre-fix index absent - "
              f"real-footage regression not run")
        return None, None
    return video, json.load(open(BACKUP))["shots"]


def _new_flag(video, s):
    rates = ix.probe_card_text(video, s["start"], s["end"], samples=SAMPLES)
    i = s["index"]
    flag = ix.flag_cards({i: s["embedding"]}, {i: rates["card"]},
                         {i: rates["caption"]}, {i: rates["branding"]})[i]
    print(f"  {SOURCE} s{i}: stored is_card={s.get('is_card')} -> {flag} {rates}")
    return flag, rates


def test_the_nine_unflagged_shots_are_not_cards():
    video, shots = _real()
    if video is None:
        return
    for i in UNFLAGGED:
        s = shots[i]
        assert s["is_card"] is True, i          # the defect, as indexed
        flag, rates = _new_flag(video, s)
        assert flag is False, (i, rates)
        assert rates["branding"] >= CAPTION_VETO_RATE, (i, rates)


def test_the_sources_real_cards_keep_the_flag():
    video, shots = _real()
    if video is None:
        return
    for i in KEPT_CARDS:
        s = shots[i]
        assert s["is_card"] is True, i
        flag, rates = _new_flag(video, s)
        assert flag is True, (i, rates)


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
