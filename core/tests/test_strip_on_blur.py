#!/usr/bin/env python3
"""CF-0878: the strip time of a whole video, read off its plan
(`shared/strip_on_blur.py`).

the-gilded-age 0836Z (B 82, gate pass) showed its picture as a 16:9 strip on a
blurred ground for about 10 s in pieces of 0.96-2.49 s; `score.thin_picture`
reads one piece at a time (moving: under 25 % and 3 s+) and the judge's
`thin_strip` is a still sliver, so nothing saw it. The stand-in below is that
plan's geometry, written out by hand - no real plan is read.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "score"))

import strip_on_blur as S                                            # noqa: E402
import score as score_model                                          # noqa: E402

STRIP_16_9 = {"blur_fill": {"rect": {"x": 0, "y": 306, "width": 1080, "height": 608}}}


def strip(seconds=None, **extra):
    """A 16:9 clip shown whole on its blurred frame (0.317 of the height)."""
    c = {"kind": "clip", "fit": "contain", "presentation": STRIP_16_9, **extra}
    if seconds is not None:
        c["seconds"] = seconds
    return c


def cover(seconds=None, kind="clip"):
    c = {"kind": kind, "fit": "cover", "presentation": {}}
    if seconds is not None:
        c["seconds"] = seconds
    return c


def seq(start, end, cuts, **extra):
    return {"start": start, "end": end, "asset": {"kind": "sequence", "cuts": cuts}, **extra}


def gilded_age():
    """example-film/2026-10-27T0836Z/the-gilded-age, its blocks' geometry: a
    16:9 strip in block 0, cuts 2, 3, 5 of block 1 (under a cut-out meme),
    cuts 0, 1 of block 2 and cut 0 of block 7; everything else cover."""
    meme = {"kind": "meme", "asset_id": "futurama-fry", "placement": "cutout_on_subject"}
    return {"audio": {"duration": 42.025}, "blocks": [
        {"start": 0.0, "end": 2.49, "asset": strip()},
        seq(2.49, 14.65, [cover(1.92), cover(0.96), strip(1.08), strip(2.25), cover(1.92),
                          strip(1.0), cover(1.33), cover(1.7, "still")], insert=meme),
        seq(14.65, 19.65, [strip(1.17), strip(1.25), cover(2.58)]),
        seq(19.65, 23.65, [cover(1.17), cover(1.04), cover(1.79, "still")]),
        seq(23.65, 29.66, [cover(1.13), cover(0.92), cover(2.0), cover(1.96, "still")]),
        seq(29.66, 34.65, [cover(3.25), cover(1.08), cover(0.66, "still")]),
        seq(34.65, 38.36, [cover(1.79), cover(1.92)]),
        seq(38.36, 42.025, [strip(0.96), cover(1.58), cover(1.125, "still")]),
    ]}


def test_the_gilded_age_strip_is_ten_seconds_nobody_saw():
    rec = S.reading(gilded_age())
    assert rec["seconds"] == 10.2, rec["seconds"]
    assert [(r["start"], r["end"]) for r in rec["runs"]] == [
        (0.0, 2.49), (5.37, 8.7), (10.62, 11.62), (14.65, 17.07), (38.36, 39.32)], rec["runs"]
    assert rec["longest"] == 3.33 and rec["share_of_video"] == 0.243
    assert rec["thin_charged_seconds"] == 0 and rec["over_seconds"] == 5.2
    assert "10.2 s as a strip under 33% of the height" in S.line(rec)
    assert S.note(rec) == ("10.2 s as a strip under 33% of the screen's height, longest 3.33 s, "
                           "5.2 s over 5 s (CF-0878)")


def test_back_to_back_pieces_are_one_run_across_cuts_and_blocks():
    plan = {"blocks": [{"start": 0.0, "end": 2.0, "asset": strip()},
                       seq(2.0, 5.0, [strip(1.5), strip(1.5)]),
                       {"start": 5.0, "end": 6.0, "asset": cover()},
                       {"start": 6.0, "end": 7.0, "asset": strip()}]}
    rec = S.reading(plan)
    assert [(r["start"], r["end"], r["seconds"]) for r in rec["runs"]] == [
        (0.0, 5.0, 5.0), (6.0, 7.0, 1.0)]
    assert rec["longest"] == 5.0 and rec["seconds"] == 6.0 and rec["over_seconds"] == 1.0


def test_what_counts_as_a_strip():
    """Under STRIP_SHARE (0.33): 16:9 (0.317) and 2.39:1 (0.235) on blur, a
    contained picture fitted whole, a held frame alike; not 5:3 (0.338), not
    a cover crop, not a picture hidden under an opaque card."""
    five_three = {"kind": "clip", "fit": "contain", "presentation": {
        "blur_fill": {"rect": {"x": 0, "y": 286, "width": 1080, "height": 648}}}}
    scope = {"kind": "clip", "fit": "contain", "presentation": {
        "blur_fill": {"rect": {"x": 0, "y": 384, "width": 1080, "height": 452}}}}
    contained = {"kind": "clip", "fit": "contain", "source_size": {"width": 1920, "height": 1080}}
    held = {"kind": "still", "fit": "contain", "held_frame": True, "presentation": STRIP_16_9}
    proof = {"kind": "proof", "placement": None}
    plan = {"blocks": [
        {"start": 0, "end": 1, "asset": five_three},
        {"start": 1, "end": 2, "asset": cover()},
        {"start": 2, "end": 3, "asset": scope},
        {"start": 3, "end": 4, "asset": contained},
        {"start": 4, "end": 5, "asset": held},
        {"start": 5, "end": 6, "asset": strip(), "insert": proof},
        {"start": 6, "end": 7, "asset": strip(), "insert": {"kind": "meme", "placement": "whole"}},
    ]}
    assert S.picture_share(five_three) == 0.338 and S.picture_share(scope) == 0.235
    assert S.picture_share(contained) == 0.316 and S.picture_share(cover()) == 1.0
    rec = S.reading(plan)
    assert [(r["start"], r["end"]) for r in rec["runs"]] == [(2, 5)], rec["runs"]
    assert rec["seconds"] == 3.0


def test_what_thin_picture_already_charges_is_counted_but_not_charged_again():
    """resident-dread 0836Z: 15.07 s of 2.39:1 strip, all of it already
    `score.thin_picture`'s (-25) - the reading names it, the price leaves it."""
    plan = {"blocks": [{"start": 0.0, "end": 7.2, "asset": strip()},
                       {"start": 7.2, "end": 15.07, "asset": strip()},
                       {"start": 15.07, "end": 22.0, "asset": strip()}],
            "held_screen": {"findings": [
                {"rule": "score.thin_picture", "block": 0, "cut": None},
                {"rule": "score.thin_picture", "block": 1, "cut": None},
                {"rule": "score.held_cut_subject", "block": 2, "cut": None}]}}
    rec = S.reading(plan)
    assert rec["seconds"] == 22.0 and rec["thin_charged_seconds"] == 15.07
    assert rec["uncharged_seconds"] == 6.93 and rec["over_seconds"] == 1.93
    assert S.reading({"blocks": plan["blocks"][:2], "held_screen": plan["held_screen"]}
                     )["over_seconds"] == 0


def test_the_finding_counts_seconds_over_the_allowance():
    rec = S.reading(gilded_age())
    f = S.finding(rec, score_model)
    assert f["rule"] == S.RULE == "score.narrow_strip_on_blur"
    assert f["units"] == 5.2 and f["where"] == {"t": 0.0} and f["hook"] is False
    assert S.finding(S.reading({"blocks": [{"start": 0, "end": 4, "asset": strip()}]}),
                     score_model) is None
    assert S.reading({}) ["seconds"] == 0 and S.line(S.reading({})).startswith("no picture")


def test_the_signed_price_is_the_row_this_module_proposed():
    """CF-0320/CF-0721: a new price was a proposal until the user signed it -
    signed 2026-10-27 22:06 МСК («да, подписываю.»): the row in `rules` is
    the one this module proposed, its signature covers that price, and
    `proposals.rows` no longer carries it."""
    d = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    row = d["rules"][S.RULE]
    assert S.RULE not in d["proposals"]["rows"] and row["task"] == "CF-0878"
    want = S.proposed_row()
    assert {k: row[k] for k in want if k != "signature"} == \
        {k: v for k, v in want.items() if k != "signature"}, row
    assert row["penalty"] == {"price": 2, "per": "second", "cap": 30, "hook_mult": None,
                              "allow_seconds": 5.0}
    sig = row["signature"]
    assert sig["user"] == "Example Reviewer" and sig["date"] == "2026-10-27"
    assert "«да, подписываю.»" in sig["note"]
    assert {k: sig[k] for k in row["penalty"]} == row["penalty"] and sig["mode"] == "penalty"
    assert row["note"].startswith("CF-0878") and "CF-0878" in d["proposals"]["note"]
    assert S.RULE in score_model.load_model(d)["rules"]
    assert score_model.LABELS["narrow_strip_on_blur"]


def test_the_price_charges_the_gilded_age():
    """Signed into `rules`, the model charges the finding at -2/s on the live
    table: the-gilded-age 82 -> 71.6 (5.2 s over 5 s)."""
    d = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    res = score_model.score([S.finding(S.reading(gilded_age()), score_model)],
                            score_model.load_model(d))
    assert res["score"] == 100 - 10.4, res


def test_unsigned_the_model_does_not_know_the_price():
    """The table as it stood before the signature (the row back in
    `proposals`, unsigned): the score model does not know the rule."""
    d = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    row = dict(d["rules"].pop(S.RULE))
    row.pop("task", None)
    row["signature"] = None
    d["proposals"]["rows"][S.RULE] = row
    assert S.RULE not in score_model.load_model(d)["rules"]


def test_the_editors_strip_take_back_reads_this_modules_numbers():
    """CF-0903: the Video Editor takes record-only blur_fills back to the crop
    past this module's allowance, measured with this module's share - one
    pair of numbers, two copies, pinned equal here."""
    import importlib.util
    scripts = ROOT / "agents" / "video-editor" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("shot_score_cf0903", scripts / "shot_score.py")
        ss = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ss)
    finally:
        sys.path.remove(str(scripts))
    assert ss.STRIP_SHARE == S.STRIP_SHARE
    assert ss.STRIP_ALLOW_SECONDS == S.ALLOW_SECONDS == S.PROPOSED["allow_seconds"]
    for target in (strip(), {"kind": "clip", "fit": "cover"},
                   {"kind": "clip", "fit": "contain",
                    "source_size": {"width": 1920, "height": 804}}):
        assert ss.strip_share(target) == S.picture_share(target), target


if __name__ == "__main__":
    import traceback
    tests = [(k, x) for k, x in sorted(globals().items())
             if k.startswith("test_") and callable(x)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
