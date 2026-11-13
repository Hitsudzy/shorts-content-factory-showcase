#!/usr/bin/env python3
"""CF-0567: an own capture (ExampleTech's own screen recording,
`own_capture-<id>`) is exempt from the cinema cam-rip rule (CF-0451,
`screen_recording.py`) by its kind, and is not sieved.

The detector itself is untouched: a third party's clip filmed off a screen is
caught exactly as before - by the describer's flag and by its sentence, warned
without a signed price and hard under a signed one. Pinned offline, on
stand-in shots and indexes:

  - the kind: by id, by a media path, by a rights record, by an index's
    `source` / `source_rights`, by a shot's `source_kind`; `mark_kind` writes
    the kind on every shot of an own capture and on no other source's;
  - `shot_verdict` / `shot_usability.assess`: an own capture's shot that says
    "a screen recording" (flag or sentence) is not flagged, under the signed
    hard price too; the same shot of another source is, unchanged;
  - `source_summary` and the sieve's warning: nothing for an own capture;
  - `stamp_index` marks the kind first;
  - the sieve keeps an own capture whatever its flags (no `unsieved`, no
    off-topic refusal), and the flag backfill never asks about one;
  - the driver's decision (CF-0567): `burned_text` is not a hard rule on an own
    capture's shot (listed in `usability.exempt[]`, the flag kept) and its
    shots are never title cards (`is_card` false, the probe's answer kept as
    `card_detected`); a third-party clip with burned text is still hard and
    its card still a card.

No pytest dependency - plain asserts, run directly.
"""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root            # noqa: E402
from _temp_pool import fence_cache_index  # noqa: E402

TMP = tmp_root("cf0567x-")
fence_cache_index(TMP / "pool")

import backfill_sieve_flags as backfill  # noqa: E402
import screen_recording as sc            # noqa: E402
import shot_usability as su              # noqa: E402
import source_sieve                      # noqa: E402

FID = "own_capture-acme-fox-demo-20261011t120000z"
CID = "own_capture:acme-fox-demo-20261011t120000z"
HARD = {"mode": sc.MODE_HARD, "price": None, "price_key": sc.HARD_PRICE_KEY, "signed": True}
WARN = {"mode": sc.MODE_WARN, "price": None, "price_key": sc.PRICE_KEY, "signed": False}

BY_SENTENCE = {"index": 0, "start": 0.0, "end": 2.0,
               "description": "A phone recording of a cinema screen, heads in the "
                              "foreground; filmed off the big screen"}
BY_FLAG = {"index": 1, "start": 2.0, "end": 4.0, "screen_recording": True,
           "description": "A browser window shows the demo page"}
CLEAN = {"index": 2, "start": 4.0, "end": 6.0, "description": "A fox runs"}


def shots():
    return [copy.deepcopy(s) for s in (BY_SENTENCE, BY_FLAG, CLEAN)]


def own_index():
    return {"source": f"/pool/{FID}.mp4", "shots": shots(),
            "source_rights": {"licence": "own_capture", "footage_origin": "own_capture"}}


def other_index():
    return {"source": "/pool/L2NAh3CIdig.mp4", "shots": shots(), "source_rights": None}


def test_the_kind():
    assert sc.source_kind(FID) == sc.OWN_CAPTURE
    assert sc.source_kind(CID) == sc.OWN_CAPTURE
    assert sc.source_kind(f"/pool/{FID}.mp4") == sc.OWN_CAPTURE
    assert sc.source_kind(rights={"licence": "own_capture"}) == sc.OWN_CAPTURE
    assert sc.source_kind(rights={"footage_origin": "own_capture"}) == sc.OWN_CAPTURE
    assert sc.source_kind(index={"source": f"/p/{FID}.mp4", "shots": []}) == sc.OWN_CAPTURE
    assert sc.source_kind(index={"source": "/p/x.mp4",
                                 "source_rights": {"licence": "own_capture"}}) == sc.OWN_CAPTURE
    for vid in ("L2NAh3CIdig", "nasa-own_capture", "own_capture-", "own_capture:", None):
        assert sc.source_kind(vid) is None, vid
    assert sc.source_kind(rights={"licence": "cc_by", "footage_origin": "nasa"}) is None
    assert sc.source_kind(index=other_index()) is None
    assert sc.exempt({"source_kind": "own_capture"}) and not sc.exempt(dict(CLEAN))


def test_mark_kind_only_on_an_own_capture():
    own, other = own_index(), other_index()
    assert sc.mark_kind(own) == 3 and sc.mark_kind(own) == 0
    assert all(s["source_kind"] == "own_capture" for s in own["shots"])
    assert sc.mark_kind(other) == 0
    assert not any("source_kind" in s for s in other["shots"])
    # by the id or the rights a caller hands in (index_footage.py's call)
    bare = {"source": "/tmp/x.mp4", "shots": shots()}
    assert sc.mark_kind(bare, video_id=FID) == 3
    bare = {"source": "/tmp/x.mp4", "shots": shots()}
    assert sc.mark_kind(bare, rights={"licence": "own_capture"}) == 3


def test_the_detector_still_catches_a_third_party_clip():
    a, b, c = shots()
    assert sc.shot_verdict(a)["by"] == sc.BY_DESCRIPTION
    assert sc.shot_verdict(b) == {"by": sc.BY_FLAG, "match": None}
    assert sc.shot_verdict(c) is None
    u = su.assess(a, rule_mode=HARD)
    assert [v["rule"] for v in u["hard"]] == ["screen_recording"] and u["score"] == 0.0, u
    u = su.assess(b, rule_mode=WARN)
    assert [v["rule"] for v in u["warn"]] == ["screen_recording"], u
    s = sc.source_summary(other_index(), title="Endgame IMAX audience reaction")
    assert s["flagged"] == [0, 1] and s["title_hit"], s
    assert sc.warning("001", "L2NAh3CIdig", s, "sieve", rule_mode=WARN) is not None


def test_an_own_capture_is_exempt_by_its_kind():
    idx = own_index()
    sc.mark_kind(idx)
    a, b, _c = idx["shots"]
    assert sc.shot_verdict(a) is None and sc.shot_verdict(b) is None
    for mode in (HARD, WARN):
        for shot in (a, b):
            u = su.assess(shot, rule_mode=mode)
            rules = [v["rule"] for v in u["hard"] + u["soft"] + u["warn"]]
            assert "screen_recording" not in rules, (mode, u)
            assert u["score"] == 1.0, u
    s = sc.source_summary(own_index(), title="Endgame IMAX audience reaction")
    assert s["flagged"] == [] and s["title_hit"] is None and s["exempt"] == "own_capture", s
    assert sc.warning("001", FID, s, "sieve", rule_mode=WARN) is None
    # the flag and the sentence are still on the shots - nothing was rewritten
    assert b["screen_recording"] is True and "filmed off" in a["description"]


def test_stamp_index_marks_the_kind_first():
    idx = own_index()
    assert su.stamp_index(idx) >= 3
    assert all(s["source_kind"] == "own_capture" for s in idx["shots"])
    assert not any(v["rule"] == "screen_recording" for s in idx["shots"]
                   for v in s["usability"]["hard"] + s["usability"]["warn"])
    other = other_index()
    su.stamp_index(other)
    assert not any("source_kind" in s for s in other["shots"])


def test_the_sieve_keeps_an_own_capture_and_backfill_skips_it():
    idx = own_index()
    for s in idx["shots"]:
        s["on_topic"], s["burned_text"] = False, True      # would refuse anyone else
    report = {"sources_by_topic": {"001": [FID]},
              "fetched": [{"video_id": FID, "topic_id": "001"},
                          {"video_id": "L2NAh3CIdig", "topic_id": "001"}]}
    out = source_sieve.sieve_report(report, load=lambda vid: idx)
    [rec] = out["sources"]
    assert rec["verdict"] == source_sieve.KEPT and rec["judged_by"] == "own_capture", rec
    assert rec["video_id"] == FID and out["refused"] == {}, out
    # no index at all is not `unsieved` either
    out = source_sieve.sieve_report(report, load=lambda vid: None)
    assert out["sources"][0]["verdict"] == source_sieve.KEPT, out
    assert source_sieve.screen_warnings(dict(report, warnings=[]), out,
                                        log=lambda m: None, rule_mode=WARN) == []
    assert backfill.batch_sources(report) == ["L2NAh3CIdig"]


def test_another_source_is_still_sieved():
    idx = other_index()
    for s in idx["shots"]:
        s["on_topic"], s["burned_text"] = False, False
    report = {"sources_by_topic": {"001": ["L2NAh3CIdig"]}}
    out = source_sieve.sieve_report(report, load=lambda vid: idx)
    [rec] = out["sources"]
    assert rec["verdict"] == source_sieve.REFUSED, rec
    assert rec["screen_recording"]["flagged"] == [0, 1], rec


# --------------------------------------------------------------------------
# CF-0567, the driver's decision: burned_text and the card treatment too
# --------------------------------------------------------------------------

UI = {"index": 3, "start": 6.0, "end": 8.0, "burned_text": True, "on_topic": True,
      "is_card": True, "card_text_hit_rate": 0.9,
      "description": "The tool's page: a prompt typed in the field, the Generate "
                     "button, the answer text below"}


def test_burned_text_is_not_a_rejection_on_an_own_capture():
    shot = dict(UI, source_kind="own_capture")
    u = su.assess(shot, rule_mode=HARD)
    assert u["hard"] == [] and u["score"] == 1.0, u
    assert u["exempt"] == [{"rule": "burned_text", "value": True,
                            "exempt": "own_capture"}], u
    assert not su.is_hard(shot) and not su.is_weak(shot)
    assert su.summary([shot])["clean"] == 1
    # the flag stays on the shot, on the record
    assert shot["burned_text"] is True


def test_burned_text_still_rejects_a_third_party_clip():
    shot = dict(UI)
    u = su.assess(shot, rule_mode=HARD)
    assert [v["rule"] for v in u["hard"]] == ["burned_text"] and u["score"] == 0.0, u
    assert "exempt" not in u, u
    assert su.is_hard(shot)
    # a source whose rights say youtube is not an own capture either
    idx = {"source": "/pool/abcDEF12345.mp4", "shots": [dict(UI)],
           "source_rights": {"licence": "youtube_official_upload",
                             "footage_origin": "vendor_official"}}
    su.stamp_index(idx)
    [s] = idx["shots"]
    assert s["is_card"] is True and "card_detected" not in s, s
    assert [v["rule"] for v in s["usability"]["hard"]] == ["burned_text"], s
    # and a clean third-party record keeps its old shape (no `exempt` key)
    assert "exempt" not in su.assess(dict(CLEAN))


def test_an_own_capture_shot_is_never_a_card():
    idx = {"source": f"/pool/{FID}.mp4", "shots": [dict(UI), dict(CLEAN, is_card=False)]}
    assert su.exempt_cards(idx) == 0            # not marked yet: the kind first
    sc.mark_kind(idx)
    assert su.exempt_cards(idx) == 1 and su.exempt_cards(idx) == 0
    ui, clean = idx["shots"]
    assert ui["is_card"] is False and ui["card_detected"] is True, ui
    assert ui["card_text_hit_rate"] == 0.9, ui          # the measurement stays
    assert clean["is_card"] is False and "card_detected" not in clean, clean
    # stamp_index does both, and the stamp is clean
    idx = {"source": f"/pool/{FID}.mp4", "shots": [dict(UI)]}
    su.stamp_index(idx)
    [s] = idx["shots"]
    assert s["source_kind"] == "own_capture" and s["is_card"] is False, s
    assert s["usability"]["hard"] == [] and s["usability"]["exempt"], s
    # another source's card stays a card
    other = {"source": "/pool/L2NAh3CIdig.mp4", "shots": [dict(UI)]}
    assert su.exempt_cards(other) == 0 and other["shots"][0]["is_card"] is True


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")
             and callable(v) and v.__module__ == __name__]
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
