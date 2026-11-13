#!/usr/bin/env python3
"""CF-0083: rank_phrase() must not crash with ZeroDivisionError when the
offered pool has no ordinary (non-card) candidate and the phrase is not
card-shaped, so `promoted + ordinary` is empty.

Two real cases from the 2026-09-03T2037Z batch, both reproduced here:

1. Ink (004): a source index filtered by compliance-2 down to a single shot,
   and that shot is is_card. RUN_LOG.txt:17 - "matcher CRASHED
   (ZeroDivisionError match_anchors.py:127 rank_phrase, empty ordinary pool)
   on a one-shot filtered copy of BROAzK8oP9U index".
2. Clooney (003): index ScKvReYRZ-A (Le Monde) is a single shot end to end,
   and that shot is is_card - not a filtered copy, the index itself has only
   ever had one shot. RUN_LOG.txt:46,60 - "its single shot is is_card and
   match_anchors.py crashes ZeroDivisionError rank_phrase:127 on every
   ordinary phrase". Le Monde dropped out of the video over this, not over
   its content.

Pure ranking check against rank_phrase() - no torch, no model, no index file.
No pytest dependency - plain asserts, run directly.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import match_anchors  # noqa: E402

TOP, MIN_SCORE, MIN_MARGIN = 10, 0.22, 0.050

# A phrase with no card vocabulary in it (see CARD_PHRASE_WORDS) - an
# ordinary scripted line, not one asking for on-screen graphics.
ORDINARY_PHRASE = "a man walks across a quiet street at dusk"


def one_card_shot_index():
    """A source index reduced to exactly one shot, and that shot is_card -
    the shape both RUN_LOG.txt cases share, whether it got there by
    compliance filtering (Ink) or was never more than one shot (Clooney)."""
    shots = [{"index": 0, "start": 0.0, "end": 2.0, "is_card": True}]
    sims = [0.25]  # above MIN_SCORE - a crash here cannot be blamed on score
    return shots, sims


def test_ordinary_phrase_against_single_card_shot_does_not_crash():
    """CF-0083's core repro: promoted is empty (phrase is not card-shaped)
    and ordinary is empty (the only shot is_card) - `rank_phrase` must
    return cleanly instead of raising ZeroDivisionError at the pool-mean
    division."""
    shots, sims = one_card_shot_index()
    assert not match_anchors.card_phrase(ORDINARY_PHRASE)  # confirms the setup
    r = match_anchors.rank_phrase(ORDINARY_PHRASE, shots, sims, TOP,
                                  MIN_SCORE, MIN_MARGIN, cards="auto")
    assert r["matches"] == []
    assert r["found"] is False
    assert r["discriminative"] is False
    assert r["margin"] is None
    assert r["advice"]  # a stated reason, not a silent empty list


def test_same_repro_under_drop_mode():
    """--cards drop never promotes, so the same empty-pool shape is reachable
    there too - the ScKvReYRZ-A crash was independent of --cards mode."""
    shots, sims = one_card_shot_index()
    r = match_anchors.rank_phrase(ORDINARY_PHRASE, shots, sims, TOP,
                                  MIN_SCORE, MIN_MARGIN, cards="drop")
    assert r["matches"] == []
    assert r["found"] is False


def test_include_mode_is_unaffected_by_this_fix():
    """--cards include treats every shot (cards too) as ordinary, so the
    single is_card shot fills the pool and ranking proceeds as normal - this
    mode was never able to hit the crash, and must still not be broken by
    the guard."""
    shots, sims = one_card_shot_index()
    r = match_anchors.rank_phrase(ORDINARY_PHRASE, shots, sims, TOP,
                                  MIN_SCORE, MIN_MARGIN, cards="include")
    assert len(r["matches"]) == 1
    assert r["matches"][0]["shot"] == 0
    assert r["found"] is True  # 0.25 >= MIN_SCORE


def test_card_shaped_phrase_against_single_card_shot_still_promotes():
    """A card-shaped phrase against the same one-shot index is the case this
    fix must not touch: promoted is non-empty, so the pool was never empty
    and behaviour is unchanged from before CF-0083."""
    shots, sims = one_card_shot_index()
    card_phrase = "a title card reading BREAKING NEWS"
    assert match_anchors.card_phrase(card_phrase)
    r = match_anchors.rank_phrase(card_phrase, shots, sims, TOP, MIN_SCORE,
                                  MIN_MARGIN, cards="auto")
    assert len(r["matches"]) == 1
    assert r["matches"][0]["promoted"] is True
    assert r["found"] is True


def test_downstream_empty_matches_is_a_clean_no_candidates_signal():
    """agents/video-editor/scripts/resolve_anchors.py (~line 887) already
    turns an empty `candidates` list into an explicit unresolved-anchor
    entry ("no shot in any index") rather than a crash. `matches: []` here
    is exactly the shape that merge step expects - this pins that the fixed
    rank_phrase output stays compatible with it without needing to import
    or run the video-editor repo."""
    shots, sims = one_card_shot_index()
    r = match_anchors.rank_phrase(ORDINARY_PHRASE, shots, sims, TOP,
                                  MIN_SCORE, MIN_MARGIN, cards="auto")
    candidates = [{**m} for m in r["matches"]]
    assert candidates == []
    assert not (bool(candidates) and max((c["score"] for c in candidates),
                                          default=0) >= MIN_SCORE)


def test_the_human_printout_survives_its_own_empty_pool_record():
    """CF-0227: the non-`--json` printout in main() formatted `r["matches"][0]`
    and `r["margin"]` unconditionally, so the record this file is about killed
    the human mode - IndexError on the empty matches, and a None formatted as
    `.3f` behind it. The JSON mode reported the same index cleanly, which is
    why it went unnoticed: nobody reads this printout on an all-card source.

    Checked on the printing code itself rather than by running main() (which
    would load CLIP): the matches list has to be tested before it is indexed.
    """
    import ast
    tree = ast.parse((SCRIPTS / "match_anchors.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    src = ast.get_source_segment((SCRIPTS / "match_anchors.py").read_text(), fn)
    guard = src.index('if not r["matches"]')
    index_into = src.index('r["matches"][0]')
    assert guard < index_into, (
        "match_anchors.py's printout indexes matches[0] before checking the "
        "empty-pool record (CF-0227)")


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
