#!/usr/bin/env python3
"""CF-0047: telling a legitimately dark title/end card from a dead frame.

`black_fraction` and `mean_luma` cannot do it, and that was measured, not
guessed: the real "Wren Hollow" card (ZZ_urA56pJE shot 50) reads 0.951/4.9
and the dead frames read 0.987-1.000 / 0.0-2.6. Both classes are black by
that measure, so there is no constant to move. What separates them is the
share of the frame's *own recognised text* that is actually lit.

Fixtures are the real luma histograms of the text Vision found on those exact
probe frames (same PROBE_OFFSET, same letterbox crop the indexer and
prepare_clip.py apply), bucketed 8 luma levels wide to stay readable. The
bucketing is exact for every level tested here, because 32/48/64/96 all fall
on a bucket boundary - no fixture rounds a verdict into existence.

Pure asserts against ink_fraction() and evaluate(), no Vision, no images, no
subprocess. Run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import qc_asset  # noqa: E402

# Luma histogram of every pixel inside the accurate-mode Vision text boxes of
# each real probe frame, in buckets of 8 (index i covers luma 8i..8i+7).
#
# ZZ_urA56pJE shot 50 - the gold "Wren Hollow / 20th Anniversary / Return to
# Hogwarts" card on black, the frame this whole task exists for. 124861 text
# pixels over 5 boxes.
WREN_HOLLOW_CARD = [81779, 5999, 4570, 4530, 4968, 4287, 3392, 3194, 2999,
                     2663, 2755, 2291, 1089, 276, 66, 2, 1] + [0] * 15
# f_bKjZeJBBI shot 7 - "FROM CHRISTOPHER NOLAN" caught mid-fade-in, navy on
# black. Vision reads the lettering, but its brightest pixel reaches luma 46.
NOLAN_FADE = [61735, 1322, 2197, 8312, 16658, 1224] + [0] * 26
# f_bKjZeJBBI shot 19 - "ON JULY 17", same fade, brightest pixel luma 58.
JULY_FADE = [51473, 455, 411, 333, 6460, 5221, 25, 2] + [0] * 24
# Ho10_4IX1jE shot 52 - the dimmest of the 19 legitimate dark cards in the
# pool, and so the one that decides how low the floor may sit.
DIMMEST_REAL_CARD = [75024, 68098, 35158, 15478, 8172, 5384, 2266, 853, 886,
                     1708, 1913, 1874, 2764, 543, 325, 206, 196, 192, 171,
                     174, 165, 282, 254, 303, 301, 1220, 1013, 3981, 4186,
                     73, 0, 0]


def pixels(buckets):
    """Expand a bucketed histogram back into luma samples, each at its
    bucket's lower edge - exact for any threshold on a bucket boundary."""
    out = []
    for i, count in enumerate(buckets):
        out += [i * 8] * count
    return out


# --- the measurement itself -------------------------------------------------

def test_lit_card_and_dead_frames_separate_at_the_chosen_level():
    """The gap the whole fix rests on: ~10% of the real card's text is lit,
    and none at all of either dead frame's."""
    assert round(qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD)), 4) == 0.0972
    assert qc_asset.ink_fraction(pixels(NOLAN_FADE)) == 0.0
    assert qc_asset.ink_fraction(pixels(JULY_FADE)) == 0.0


def test_the_floor_sits_inside_the_measured_gap():
    """MIN_CARD_INK_FRACTION is not fitted to either side: it clears the
    dead frames by the whole of their zero and the real card by ~5x."""
    dead = max(qc_asset.ink_fraction(pixels(NOLAN_FADE)),
               qc_asset.ink_fraction(pixels(JULY_FADE)))
    card = qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD))
    dimmest = qc_asset.ink_fraction(pixels(DIMMEST_REAL_CARD))
    assert dead < qc_asset.MIN_CARD_INK_FRACTION < min(card, dimmest)
    assert min(card, dimmest) / qc_asset.MIN_CARD_INK_FRACTION > 4


def test_separation_holds_across_the_level_plateau():
    """CARD_INK_LEVEL was chosen from a plateau, not a knife edge: at every
    level from 48 to 96 the dead frames stay far under the floor - zero
    everywhere except one reading of 0.0004 at level 48 - while the real card
    stays positive. The constant is bracketed by real data on both sides -
    the brightest pixel any dead frame's text reaches is 58, the real card's
    reaches 129 - rather than tuned to one point."""
    for level in (48, 56, 64, 72, 80, 96):
        assert qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD), level) > 0, level
        for dead in (NOLAN_FADE, JULY_FADE):
            dead_ink = qc_asset.ink_fraction(pixels(dead), level)
            assert dead_ink < 0.1 * qc_asset.MIN_CARD_INK_FRACTION, (level, dead_ink)


def test_the_level_sits_where_the_margin_is_widest_not_merely_where_it_works():
    """Why 64 and not the top of the plateau: by level 96 the real card is
    down to 0.0115, *below* the floor, so a higher level would reject it. 64
    keeps the card ~5x clear of the floor while the dead frames are still at
    zero - the middle of the usable range, not its edge."""
    assert qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD), 96) < \
        qc_asset.MIN_CARD_INK_FRACTION
    assert qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD), 64) > \
        4 * qc_asset.MIN_CARD_INK_FRACTION


def test_low_levels_do_not_separate_which_is_why_a_looser_constant_fails():
    """At level 32 the dead frames read 0.1955/0.1819 against the card's
    0.2241 - the classes overlap. This is the measured reason a card cannot
    simply be handed a lower MIN_MEAN_LUMA."""
    card = qc_asset.ink_fraction(pixels(WREN_HOLLOW_CARD), 32)
    for dead in (NOLAN_FADE, JULY_FADE):
        assert qc_asset.ink_fraction(pixels(dead), 32) > 0.75 * card


def test_no_text_at_all_is_not_lit_text():
    """6fcoM7Q348Q shot 0 and f_bKjZeJBBI shot 1 have no recognised text on
    the probe frame at all. An empty sample must read as zero ink, never as
    a vacuous pass."""
    assert qc_asset.ink_fraction([]) == 0.0


# --- what evaluate() does with it -------------------------------------------

def vision(coverage=1.0, short_side=720, roi_source="saliency"):
    return {"source_size": {"width": short_side, "height": short_side},
            "roi_source": roi_source, "roi_coverage": coverage}


def verdict(black, luma, ink=None, coverage=1.0, short_side=720):
    return qc_asset.evaluate(vision(coverage, short_side), black, luma,
                             720, 0.65, 0.90, qc_asset.MIN_MEAN_LUMA,
                             card_ink=ink)


# The real cached measurements of the five frames this task is judged on.
def test_wren_hollow_card_passes_once_its_ink_is_known():
    v = verdict(0.951, 4.9, ink=0.0972)
    assert v["usable"], v["failures"]
    # And it may not pass quietly: both excusals are on the record.
    assert len(v["relaxations"]) == 2
    assert any("dead pixels" in r for r in v["relaxations"])
    assert any("too dark" in r for r in v["relaxations"])


def test_the_same_card_still_fails_without_the_measurement():
    """No ink measured means no excusal - the flag alone never relaxes
    anything. This is what keeps an un-measured card exactly as gated as it
    was before CF-0047."""
    v = verdict(0.951, 4.9, ink=None)
    assert not v["usable"]
    assert v["failed"] == ["black", "luma"]
    assert v["relaxations"] == []


def test_dead_frames_stay_rejected():
    """The four frames CF-0047 must not let through, at their real numbers:
    two with unlit text, two with no text at all (ink None)."""
    for name, black, luma, ink in [
            ("6fcoM7Q348Q#0", 1.000, 0.9, None),
            ("f_bKjZeJBBI#1", 1.000, 0.0, None),
            ("f_bKjZeJBBI#7", 0.987, 2.6, 0.0),
            ("f_bKjZeJBBI#19", 0.993, 2.3, 0.0)]:
        v = verdict(black, luma, ink=ink)
        assert not v["usable"], name
        assert "black" in v["failed"] and "luma" in v["failed"], name
        assert v["relaxations"] == [], name


def test_a_card_is_excused_darkness_and_nothing_else():
    """Resolution, subject and framing apply to a lit card unchanged. A card
    that is dark *and* too small is still rejected - for being too small."""
    v = verdict(0.951, 4.9, ink=0.0972, short_side=694, coverage=0.30)
    assert not v["usable"]
    assert v["failed"] == ["resolution", "coverage"]
    assert len(v["relaxations"]) == 2


def test_ink_never_rescues_a_frame_that_failed_for_another_reason():
    """A frame with plenty of lit text but no subject at all still fails:
    the ink measurement is not a general override."""
    v = qc_asset.evaluate(vision(roi_source="none"), 0.99, 2.0,
                          720, 0.65, 0.90, qc_asset.MIN_MEAN_LUMA, card_ink=0.5)
    assert not v["usable"]
    assert v["failed"] == ["subject"]


def test_ordinary_frames_are_untouched_by_the_new_argument():
    """The default path has to be byte-for-byte what it was: a normal frame
    passes, a genuinely dark non-card frame fails, and neither has an
    opinion about ink."""
    ok = verdict(0.232, 50.0)
    assert ok["usable"] and ok["relaxations"] == [] and ok["card_ink"] is None
    bad = verdict(0.99, 2.0)
    assert not bad["usable"] and bad["failed"] == ["black", "luma"]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            passed += 1
    print(f"\n{passed}/{passed} passed  # card-ink checks")
