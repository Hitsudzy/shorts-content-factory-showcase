#!/usr/bin/env python3
"""CF-0035: what promotion actually does to a real phrase's candidate list.

Numbers below are real: the CLIP text-image cosine similarity of every one of
`ZZ_urA56pJE.shots.json`'s 60 shots against three real anchor phrases from
`wren-hollow-lockhart` (batch 2026-08-31T2155Z), produced with the same model
`match_anchors.py` itself uses. Card flags are that index's own `is_card`.

The two logo phrases are CF-0034's finding: shot 3 ("purple Example Max logo splash
screen") scores 0.3896 and shot 50 ("gold ornate 'Wren Hollow' logo card on
black background") scores 0.3331, while the shots that actually reached the
finished video scored 0.2400 and 0.2295. CLIP was never wrong about these -
cards were simply not in the pool. The third phrase is an ordinary
photographic anchor from the same video, kept here to pin down that its
ranking does not move at all.

Pure ranking checks against rank_phrase() - no torch, no model, no index file.

No pytest dependency - plain asserts, run directly.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import match_anchors  # noqa: E402

CARD_SHOTS = {3, 8, 26, 33, 50, 52, 53, 59}
SHOTS = [{"index": i, "start": float(i), "end": float(i) + 2.0,
          "is_card": i in CARD_SHOTS} for i in range(60)]

Example_Network = "a purple Example Max streaming logo on screen"
Example_Network_SIMS = [
    0.2122, 0.2156, 0.2320, 0.3896, 0.1533, 0.2063, 0.2186, 0.2137, 0.2201,
    0.2216, 0.2369, 0.1621, 0.2235, 0.1949, 0.2064, 0.2164, 0.1987, 0.2088,
    0.2082, 0.1495, 0.2097, 0.2027, 0.1829, 0.2024, 0.2140, 0.1999, 0.2580,
    0.2072, 0.2004, 0.1266, 0.2009, 0.1949, 0.2143, 0.2686, 0.1932, 0.2166,
    0.2346, 0.1641, 0.1732, 0.1977, 0.1932, 0.2136, 0.1677, 0.2400, 0.1738,
    0.2140, 0.2079, 0.1933, 0.2058, 0.2261, 0.2258, 0.2184, 0.2173, 0.3481,
    0.2255, 0.1899, 0.2128, 0.1958, 0.2045, 0.3466]

GOLD = "a gold ornate Wren Hollow logo on a black background"
GOLD_SIMS = [
    0.2216, 0.2153, 0.1698, 0.2049, 0.1800, 0.1787, 0.2122, 0.1628, 0.1945,
    0.1428, 0.1306, 0.1009, 0.1549, 0.2105, 0.1858, 0.2228, 0.2005, 0.1574,
    0.1999, 0.1566, 0.2134, 0.2278, 0.1685, 0.1203, 0.1682, 0.2027, 0.2190,
    0.1945, 0.1854, 0.1608, 0.1804, 0.1810, 0.2254, 0.2494, 0.1505, 0.1706,
    0.2178, 0.1110, 0.1951, 0.1730, 0.1523, 0.2013, 0.2226, 0.2216, 0.1131,
    0.1677, 0.2200, 0.1477, 0.1602, 0.1212, 0.3331, 0.2080, 0.1750, 0.2337,
    0.1925, 0.2267, 0.2118, 0.2295, 0.2154, 0.2321]

PLAIN = "a boy in a black school robe and glasses standing in a tiled corridor"
PLAIN_SIMS = [
    0.1652, 0.1966, 0.1813, 0.1363, 0.1697, 0.1873, 0.2362, 0.1537, 0.1402,
    0.0978, 0.1530, 0.1742, 0.1489, 0.1736, 0.1255, 0.1796, 0.1740, 0.0992,
    0.2381, 0.1402, 0.3421, 0.2611, 0.1499, 0.1613, 0.2729, 0.2357, 0.1495,
    0.2074, 0.1909, 0.1696, 0.2056, 0.1749, 0.1954, 0.1686, 0.1634, 0.2254,
    0.2357, 0.1769, 0.2070, 0.1810, 0.1666, 0.1923, 0.2126, 0.2819, 0.1699,
    0.1620, 0.1651, 0.1638, 0.1570, 0.1550, 0.1767, 0.2147, 0.1483, 0.1737,
    0.2118, 0.2500, 0.1639, 0.1999, 0.1981, 0.1718]

TOP, MIN_SCORE, MIN_MARGIN = 10, 0.22, 0.050


def rank(phrase, sims, cards="auto"):
    return match_anchors.rank_phrase(phrase, SHOTS, sims, TOP, MIN_SCORE,
                                     MIN_MARGIN, cards)


def test_the_premise_cards_outscore_the_shots_that_shipped():
    """Not a hypothetical: on both phrases the right card outscores the shot
    the finished video actually used, by a wide margin."""
    assert Example_Network_SIMS[3] == 0.3896 and Example_Network_SIMS[43] == 0.2400
    assert GOLD_SIMS[50] == 0.3331 and GOLD_SIMS[57] == 0.2295


def test_drop_mode_reproduces_the_defect():
    """The behaviour before CF-0035, kept reachable as --cards drop: both
    phrases land on the wrong photographic shot, and both read as flat."""
    for phrase, sims, wrong in ((Example_Network, Example_Network_SIMS, 43), (GOLD, GOLD_SIMS, 57)):
        r = rank(phrase, sims, cards="drop")
        assert r["matches"][0]["shot"] == wrong, r["matches"][0]
        assert not r["discriminative"], (
            f"{phrase!r} was flagged flat in the real run (margin 0.0382 / "
            f"0.0476); the drop-mode path must still reproduce that")


def test_auto_puts_the_right_card_first_on_both_logo_phrases():
    assert rank(Example_Network, Example_Network_SIMS)["matches"][0]["shot"] == 3
    assert rank(GOLD, GOLD_SIMS)["matches"][0]["shot"] == 50


def test_auto_promotes_at_most_three_cards_and_only_above_min_score():
    for phrase, sims in ((Example_Network, Example_Network_SIMS), (GOLD, GOLD_SIMS)):
        promoted = [m for m in rank(phrase, sims)["matches"] if m["promoted"]]
        assert len(promoted) <= match_anchors.MAX_PROMOTED_CARDS
        assert all(m["card"] for m in promoted)
        assert all(m["score"] >= MIN_SCORE for m in promoted), promoted
    # Concretely: Example Max's three splash-screen cards, in score order.
    assert [m["shot"] for m in rank(Example_Network, Example_Network_SIMS)["matches"] if m["promoted"]] \
        == [3, 53, 59]


def test_promotion_only_prepends_never_replaces():
    """The safety property the whole design rests on: a card-shaped phrase
    keeps every ordinary candidate it had before, in the same order. Nothing
    the reuse cap (CF-0026) or the usability gate might have to fall back to
    is taken away."""
    for phrase, sims in ((Example_Network, Example_Network_SIMS), (GOLD, GOLD_SIMS)):
        before = [m["shot"] for m in rank(phrase, sims, cards="drop")["matches"]]
        after = [m["shot"] for m in rank(phrase, sims)["matches"]]
        assert after[len(after) - len(before):] == before, (after, before)
        assert len(after) == len(before) + sum(
            1 for m in rank(phrase, sims)["matches"] if m["promoted"])


def test_ordinary_phrase_is_untouched():
    """An anchor that resolves correctly today must be bit-for-bit unchanged:
    same candidates, same order, same margin, same verdicts."""
    assert not match_anchors.card_phrase(PLAIN)
    auto = rank(PLAIN, PLAIN_SIMS)
    drop = rank(PLAIN, PLAIN_SIMS, cards="drop")
    assert auto["matches"] == drop["matches"]
    assert auto["margin"] == drop["margin"]
    assert auto["found"] == drop["found"]
    assert auto["discriminative"] == drop["discriminative"]
    assert auto["matches"][0]["shot"] == 20  # the shot the real run used
    assert not any(m["promoted"] for m in auto["matches"])


def test_promotion_repairs_the_flat_phrase_warning_honestly():
    """Both logo phrases were recorded as `discriminative: false` in the real
    storyboard - correct at the time (nothing photographic depicted them) and
    noise once a card resolves them. The margin is measured against the pool
    the phrase was allowed to draw from, so it moves for exactly these two."""
    assert rank(Example_Network, Example_Network_SIMS)["discriminative"]
    assert rank(GOLD, GOLD_SIMS)["discriminative"]
    assert rank(Example_Network, Example_Network_SIMS)["margin"] > rank(Example_Network, Example_Network_SIMS, cards="drop")["margin"]


def test_include_mode_is_the_unconditional_variant_and_is_not_the_default():
    """--cards include ranks cards on score alone. It fixes the Example_Network phrase too,
    but it was measured to change ordinary anchors elsewhere in the repo (a
    card taking top-1 from a photographic shot on The Long Voyage and on Coyote vs
    Acme), which is why `auto` is the default."""
    r = rank(Example_Network, Example_Network_SIMS, cards="include")
    assert r["matches"][0]["shot"] == 3
    assert not any(m["promoted"] for m in r["matches"])
    # It also truncates: with cards competing for the same --top slots, the
    # Example_Network phrase keeps 10 candidates where `auto` hands back 13.
    assert len(r["matches"]) < len(rank(Example_Network, Example_Network_SIMS)["matches"])
    # And an ordinary phrase no longer draws from the pool it used to: even
    # where no card is good enough to reach its top 10 (as here), the cards
    # are in the field its margin is measured against.
    assert rank(PLAIN, PLAIN_SIMS, cards="include")["margin"] \
        != rank(PLAIN, PLAIN_SIMS)["margin"]


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
