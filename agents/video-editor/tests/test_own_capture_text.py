#!/usr/bin/env python3
"""CF-0567 (after FI 14c4ff4): a shot of the factory's own screen recording
keeps its interface text - the burned-text refusal (CF-0351), the unanswered
card (CF-0354) and the text-cut refusal (CF-0275) exempt it by its kind
(`own_capture-<id>` or `source_kind: own_capture`), with the reason on the
record; every other source is refused exactly as before.

Stand-ins only: hand-made shots.json entries, matches and plans. No network,
no pool, no batch.
"""
import _isolated_runlog  # noqa: F401 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _clip_names  # noqa: E402
import entity_guard as eg  # noqa: E402
import resolve_anchors as ra  # noqa: E402

OWN = "own_capture-acme-fox-demo-20261011t120000z"
YT = "H6RXVb_J5J4"
POOL = "/pool/shared/footage"
# what the Footage Indexer writes for a recording's shot (FI 14c4ff4)
OWN_SHOT = {"index": 3, "burned_text": True, "is_card": False, "card_detected": True,
            "source_kind": "own_capture"}
THEIR_SHOT = {"index": 3, "burned_text": True, "is_card": False}
THEIR_CARD = {"index": 4, "is_card": True}            # burned_text never answered
OWN_CARD = {"index": 4, "is_card": True, "source_kind": "own_capture"}
CUT = {"text_cut_area": 0.30, "text_outside_crop": 0.0, "text_regions": 3}


def test_who_is_an_own_capture_shot():
    for src in (OWN, f"{OWN}:3", f"{POOL}/{OWN}.mp4", f"/w/a00_{OWN}_s003.mp4",
                "own_capture:acme-1"):
        assert _clip_names.is_own_capture_shot(None, src), src
    assert _clip_names.is_own_capture_shot({"source_kind": "own_capture"}, f"{YT}:1")
    for src in (YT, f"{YT}:3", f"{POOL}/{YT}.mp4", f"/w/a00_{YT}_s003.mp4", None, ""):
        assert not _clip_names.is_own_capture_shot({"source_kind": "youtube"}, src), src


def test_third_party_burned_text_is_still_refused():
    why = eg.refusal(f"{POOL}/{YT}.mp4", 3, THEIR_SHOT, {})
    assert why and "CF-0351" in why, why
    why = eg.refusal(f"{YT}:4", 4, THEIR_CARD, {})
    assert why and "CF-0354" in why, why
    assert eg.own_capture_exemption(f"{YT}:3", 3, THEIR_SHOT) is None


def test_own_capture_text_passes_by_its_kind():
    for src, shot in ((f"{POOL}/{OWN}.mp4", OWN_SHOT), (f"{OWN}:3", THEIR_SHOT),
                      (f"{YT}:3", OWN_SHOT), (f"{OWN}:4", OWN_CARD)):
        assert eg.refusal(src, shot["index"], shot, {}) is None, (src, shot)
        ex = eg.own_capture_exemption(src, shot["index"], shot)
        assert ex and "own_capture" in ex and "CF-0567" in ex, ex
    # nothing to exempt on a clean shot
    assert eg.own_capture_exemption(OWN, 1, {"burned_text": False}) is None


def test_the_screen_keeps_own_capture_and_records_why():
    index_data = {"a": {"source": f"{POOL}/{YT}.mp4", "shots": [THEIR_SHOT]},
                  "b": {"source": f"{POOL}/{OWN}.mp4", "shots": [OWN_SHOT]}}
    matches = [{"phrase": "the tool answers", "found": True, "candidates": [
        {"index": "a", "shot": 3, "score": 0.31, "source": f"{POOL}/{YT}.mp4"},
        {"index": "b", "shot": 3, "score": 0.29, "source": f"{POOL}/{OWN}.mp4"}]}]
    exempted = []
    refused = eg.screen_matches(matches, index_data, {}, 0.2, exempted=exempted)
    assert [r["shot"] for r in refused] == [3] and "CF-0351" in refused[0]["reason"]
    assert [c["index"] for c in matches[0]["candidates"]] == ["b"], matches
    assert len(exempted) == 1 and exempted[0]["exempt"] == "own_capture", exempted
    # the old call (no `exempted`) behaves as it always did
    matches2 = [{"phrase": "x", "candidates": [
        {"index": "a", "shot": 3, "score": 0.3, "source": f"{POOL}/{YT}.mp4"}]}]
    assert len(eg.screen_matches(matches2, index_data, {})) == 1


def test_the_finished_plan_is_not_convicted_for_its_recording():
    plan = {"blocks": [{"shot": f"{YT}:3", "asset": {"kind": "clip"}},
                       {"shot": f"{OWN}:3", "asset": {"kind": "clip"}}]}
    entries = {YT: THEIR_SHOT, OWN: OWN_SHOT}
    exempted = []
    out = eg.plan_violations(plan, {}, shots_of=lambda vid, n: entries.get(vid),
                             exempted=exempted)
    assert [v["block"] for v in out] == [0], out
    assert [e["block"] for e in exempted] == [1], exempted


def test_text_cut_refusal_exempts_own_capture_only():
    why = ra.text_cut_refusal(THEIR_SHOT, CUT)
    assert why and why.startswith(ra.REASON_TEXT_CUT_BY_CROP), why
    assert ra.text_cut_refusal(OWN_SHOT, CUT) is None
    assert ra.text_cut_refusal({**THEIR_SHOT, "source": f"{POOL}/{OWN}.mp4"}, CUT) is None
    # a native 1080x1920 recording measured honestly cuts nothing anyway
    assert ra.text_cut_refusal({"index": 1}, {"text_cut_area": 0.0, "text_outside_crop": 0.0,
                                              "text_regions": 40}) is None


def test_the_storyboard_carries_the_exemptions():
    src = (HERE.parent / "scripts" / "resolve_anchors.py").read_text()
    assert '"own_capture_exempt": own_capture_exempt' in src
    assert "exempted=own_capture_exempt" in src


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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
