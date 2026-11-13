#!/usr/bin/env python3
"""CF-0035: the cross-index merge must not sort the matcher's promotion away.

`match_anchors.py` puts the best few title/end cards in front of the ordinary
candidates for an anchor phrase that names on-screen graphics, and it does that
once per index. `resolve_anchors.match()` then merges every index's matches
into one list - by score, before this fix - and caps the promotion again for
the phrase as a whole.

Every candidate below is real matcher output for real anchor phrases from
`wren-hollow-lockhart` (batch 2026-08-31T2155Z) against the two indexes that
run actually used, `ZZ_urA56pJE` and `iJz9yl4ljys`:

  * "a blond man's portrait with a German-language headline graphic overlay" -
    the case a score sort gets wrong. The card that depicts the phrase almost
    verbatim (iJz9yl4ljys shot 0, "portrait of a blond man with a
    German-language headline graphic overlay") scores 0.265, below the 0.296
    photographic portrait that has no headline in it.
  * "a purple Example Max streaming logo on screen" - the case a score sort gets
    right anyway (shot 3 at 0.390 leads the field), kept so the merge is
    pinned on both.

Pure ordering checks - no CLIP, no subprocess, no index file.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402

MAX_PROMOTED = 3  # what match_anchors.py reports as max_promoted_cards

ZZ = "/x/ZZ_urA56pJE.mp4"
IJ = "/x/iJz9yl4ljys.mp4"


def cand(source, shot, score, card=False, promoted=False):
    return {"shot": shot, "score": score, "card": card, "promoted": promoted,
            "source": source, "index": source + ".shots.json"}


# Real merged input for the German-headline phrase: each index promoted its own
# best cards (three from ZZ_urA56pJE, one from iJz9yl4ljys - the only card that
# index has), and each contributed its ordinary top matches.
GERMAN = [
    cand(ZZ, 33, 0.2550, card=True, promoted=True),
    cand(ZZ, 8, 0.2340, card=True, promoted=True),
    cand(ZZ, 53, 0.2240, card=True, promoted=True),
    cand(ZZ, 47, 0.2960),
    cand(ZZ, 40, 0.2940),
    cand(ZZ, 34, 0.2920),
    cand(IJ, 0, 0.2650, card=True, promoted=True),
    cand(IJ, 5, 0.2410),
]

# Real merged input for the Example Max phrase.
Example_Network = [
    cand(ZZ, 3, 0.3896, card=True, promoted=True),
    cand(ZZ, 53, 0.3481, card=True, promoted=True),
    cand(ZZ, 59, 0.3466, card=True, promoted=True),
    cand(ZZ, 43, 0.2400),
    cand(ZZ, 10, 0.2370),
    cand(IJ, 0, 0.2200, card=True, promoted=True),
    cand(IJ, 2, 0.2160),
]

# An ordinary anchor from the same video: no card anywhere, nothing promoted.
PLAIN = [
    cand(ZZ, 20, 0.3421),
    cand(ZZ, 43, 0.2819),
    cand(IJ, 2, 0.2220),
    cand(ZZ, 24, 0.2729),
]


def test_the_promoted_card_leads_even_when_it_loses_on_score():
    ordered = resolve_anchors.order_candidates(list(GERMAN), MAX_PROMOTED)
    first = ordered[0]
    assert (first["source"], first["shot"]) == (IJ, 0), (
        "the German-headline card must lead; a plain score sort puts the "
        "headline-less 0.296 portrait first, which is the CF-0035 defect")
    assert first["score"] < ordered[3]["score"], (
        "this test is worthless unless the promoted card really does lose on "
        "score to an ordinary candidate behind it")


def test_merged_promotion_is_capped_across_indexes():
    """Two indexes promoting up to three cards each is up to six; the phrase
    still gets at most three in front."""
    ordered = resolve_anchors.order_candidates(list(GERMAN), MAX_PROMOTED)
    promoted = [c for c in ordered if c["promoted"]]
    assert len(promoted) == MAX_PROMOTED
    assert [(c["source"], c["shot"]) for c in promoted] == [(IJ, 0), (ZZ, 33), (ZZ, 8)]
    assert ordered[:MAX_PROMOTED] == promoted, "promoted cards must be the head of the list"


def test_demoted_cards_are_kept_as_candidates():
    """Over the cap means "not in front", never "dropped" - CF-0026's reuse
    cap and the usability gate both work by falling through to the next
    candidate, so the list must never get shorter than it was."""
    ordered = resolve_anchors.order_candidates(list(GERMAN), MAX_PROMOTED)
    assert len(ordered) == len(GERMAN)
    demoted = next(c for c in ordered if (c["source"], c["shot"]) == (ZZ, 53))
    assert not demoted["promoted"] and demoted in ordered


def test_behind_the_promotion_the_order_is_still_score():
    for candidates in (GERMAN, Example_Network, PLAIN):
        ordered = resolve_anchors.order_candidates(list(candidates), MAX_PROMOTED)
        tail = [c["score"] for c in ordered if not c["promoted"]]
        assert tail == sorted(tail, reverse=True), tail


def test_an_anchor_with_no_cards_is_ordered_exactly_as_before():
    ordered = resolve_anchors.order_candidates(list(PLAIN), MAX_PROMOTED)
    assert ordered == sorted(PLAIN, key=lambda c: -c["score"])


def test_a_matcher_that_reports_no_promotion_is_pure_score_order():
    """Belt and braces for an older matcher, or --cards drop/include: with
    max_promoted 0 and no promoted flags, this is the pre-CF-0035 sort."""
    plain = [dict(c, promoted=False) for c in Example_Network]
    assert resolve_anchors.order_candidates(plain, 0) == \
        sorted(plain, key=lambda c: -c["score"])


def test_shot_reuse_cap_is_untouched_by_the_fix():
    """The cap is a property of the fill loop, not of candidate order, and this
    fix must not have moved it. CF-0121 lowered it from CF-0026's 3 to 1 - one
    sample, one use - which is a decision about the rule, not about promotion:
    the demotion above still has to keep every card in the list, and now it
    matters more, because a demoted card is one of the distinct samples the
    anchor has left to fall through to."""
    assert resolve_anchors.MAX_SHOT_REUSE == 1


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
