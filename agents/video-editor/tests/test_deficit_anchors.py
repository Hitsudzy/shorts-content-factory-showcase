#!/usr/bin/env python3
"""CF-0139: what a refused plan leaves behind, and whether the rotation can
read it.

The refusal is decided here (CF-0137 rung 4, `judge()` -> exit 2) and
recorded there (`rotation/ledger/<channel>.shortages.jsonl`), so the file
that crosses the boundary - `plan.assetless-rung.json` - is the whole of the
contract. Until this task it carried the gate's own record only: block
indices and a line of prose each. Two things it did not carry, and both were
already computed:

  * `hole_fill.refused[]` - the library rung's per-block outcome codes
    (CF-0138), a closed list, printed to stderr on exactly the runs that end
    in a refusal and therefore have no plan file to keep them in;
  * the block's `intent` and span, without which an entry is an index into a
    document that was never written.

So this file pins both halves. The unit half is pure over `assetless_rung`.
The join half runs the *real* `rotation/shortage.py` over the file this
repository writes - not a copy of it and not a description of it - because
the failure this is guarding against is precisely the one that a copy cannot
see: both sides green, agreeing about nothing. When the factory checkout is
not there (this repo cloned on its own) the join tests return rather than
fail; the end-to-end proof that the file is written at all lives in
tests/test_insert_fills_hole.py, which needs no factory.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
_TMP = tmp_root("ve-cf0139-")
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assetless_rung  # noqa: E402
import meme_layer  # noqa: E402

# agents/video-editor -> agents -> the factory checkout.
FACTORY = AGENT_ROOT.parent.parent
SHORTAGE_PY = FACTORY / "rotation" / "shortage.py"

BLOCKS = [
    {"start": 0.0, "end": 4.2, "intent": "a bundle of newspapers tied with string"},
    {"start": 4.2, "end": 9.0, "intent": "an iceberg photographed at the waterline"},
    {"start": 9.0, "end": 12.5, "intent": ""},
]

# The two shapes of degradation record build_render_plan.py actually produces:
# `from: <a real kind>` (a frame was designated and lost) and `from: unfilled`
# (the anchor resolved to nothing at all).
ASSETLESS = [
    {"index": 0, "from": "clip",
     "reason": "BROAzK8oP9U s2 fails the asset gate after its cached 44% caption crop"},
    {"index": 2, "from": "unfilled",
     "reason": "no usable footage for this block (CF-0085)"},
]

# `meme.hole_fill` as meme_layer.plan_memes() leaves it when the layer ran and
# closed nothing: block 0 was offered the library and nothing cleared the M4
# floors, block 2 was never refused by name.
HOLE_FILL = {
    "attempted": True, "holes": [0, 2], "at_floor": [0, 2], "filled": [],
    "refused": [{"block_index": 0, "outcome": "no_asset",
                 "note": "nothing in the library answers 'a bundle of newspapers tied "
                         "with string' clear of the field (M4: 0.26 / 0.02 at rank 3)"}],
    "note": "0 of 2 hole(s) filled from the library",
}


def rotation_shortage():
    """The rotation's real reader, or None when the factory is not here."""
    if not SHORTAGE_PY.exists():
        return None
    spec = importlib.util.spec_from_file_location("cf0139_shortage", SHORTAGE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_KEEP = object()


def refused(blocks=_KEEP, assetless=None):
    return assetless_rung.judge(assetless if assetless is not None else ASSETLESS,
                                None, style="montage",
                                blocks=BLOCKS if blocks is _KEEP else blocks)


def written(rec, hole_fill=None):
    """The deficit file as the planner writes it, read back."""
    tmp = Path(tempfile.mkdtemp(prefix="e-", dir=_TMP))
    assetless_rung.write_deficit(tmp / "plan.json", rec, hole_fill=hole_fill)
    return json.loads((tmp / "plan.assetless-rung.json").read_text())


# --------------------------------------------------------------------------
# 1. the anchors
# --------------------------------------------------------------------------

def test_every_refused_block_becomes_an_anchor_with_its_span_and_intent():
    rec = refused()
    assert [a["block_index"] for a in rec["anchors"]] == [0, 2], rec["anchors"]
    a0, a2 = rec["anchors"]
    assert a0["intent"] == "a bundle of newspapers tied with string", a0
    assert (a0["start"], a0["end"]) == (0.0, 4.2), a0
    assert a0["from"] == "clip" and "asset gate" in a0["reason"], a0
    # `from` was read off the degradation record and dropped on the floor
    # before CF-0139; it is the one machine-readable thing the Editor knows
    # about *why* the block is a hole - "unfilled" is an anchor that resolved
    # to nothing, any other value is a frame that existed and was lost.
    assert a2["from"] == "unfilled", a2
    assert a2["intent"] == "" and (a2["start"], a2["end"]) == (9.0, 12.5), a2


def test_the_anchors_are_added_beside_the_two_lists_and_never_instead():
    """`blocks`/`reasons` stay: report_lines() zips them, and the rotation's
    own test pins them as the shape it reads. A record written on every
    refusal is not the place to break a reader for tidiness."""
    rec = refused()
    assert rec["blocks"] == [0, 2], rec
    assert [a["reason"] for a in rec["anchors"]] == rec["reasons"], rec
    assert [a["block_index"] for a in rec["anchors"]] == rec["blocks"], rec
    lines = assetless_rung.report_lines(rec)
    assert any("block 0:" in ln for ln in lines), lines


def test_an_anchor_survives_a_judge_that_was_given_no_blocks():
    """`blocks=None` is a legal call (the gate is asked before the block list
    exists in one caller's tests). The anchor is then poorer, not absent, and
    poorer in a way that reads as unknown rather than as zero."""
    rec = refused(blocks=None)
    a0 = rec["anchors"][0]
    assert a0["start"] is None and a0["end"] is None and a0["intent"] == "", a0
    assert a0["block_index"] == 0 and a0["from"] == "clip", a0


def test_a_plan_that_predates_the_gate_says_so_about_anchors_too():
    """stage_fields()'s promise: absence never has to be interpreted. A plan
    built before this gate existed must not read as a video that had no
    unresolved anchors."""
    rec = assetless_rung.stage_fields({})
    assert rec["anchors"] == [] and rec["passed"] is None, rec


# --------------------------------------------------------------------------
# 2. the file
# --------------------------------------------------------------------------

def test_the_insert_rungs_record_rides_along_with_the_deficit():
    doc = written(refused(), hole_fill=HOLE_FILL)
    assert doc["assetless_rung"]["blocks"] == [0, 2], doc["assetless_rung"]
    assert doc["hole_fill"]["refused"][0]["outcome"] == "no_asset", doc["hole_fill"]


def test_a_caller_with_nothing_to_say_leaves_the_node_out_rather_than_empty():
    """An absent node is "the layer was never asked"; an empty one would be
    "the layer was asked and refused nothing", which is a different and
    false sentence. meme_layer.empty_hole_fill() exists to keep those two
    apart and this file must not fold them back together."""
    doc = written(refused())
    assert "hole_fill" not in doc, doc
    probe = {**meme_layer.empty_hole_fill(), "note": "the insert rung did not run: x"}
    doc = written(refused(), hole_fill=probe)
    assert doc["hole_fill"]["attempted"] is False, doc["hole_fill"]
    assert doc["hole_fill"]["refused"] == [], doc["hole_fill"]


def test_both_refusals_in_the_planner_hand_the_record_over():
    """Structural, and it is the whole of the fix: the codes existed before
    this task and went to stderr because neither call site passed them on.
    A third refusal added later must not quietly go back to that.

    CF-0190 added a refusal of another gate entirely (`blooper_gate`, the
    relaxation's two borders), whose deficit has no holes in it and so nothing
    of the insert rung's to carry. So the count is taken on *this* gate's call
    sites by name rather than on every line mentioning `write_deficit(`, and
    the other gates' calls are checked to be exactly that - another module's -
    so a rung deficit cannot slip the rule by being written through something
    that is not called `assetless_rung`.
    """
    text = (SCRIPTS / "build_render_plan.py").read_text()
    calls = [ln for ln in text.splitlines() if "write_deficit(" in ln]
    rung = [ln for ln in calls if "assetless_rung.write_deficit(" in ln]
    assert len(rung) == 2, calls
    for ln in rung:
        assert "hole_fill=" in ln, ln
    for ln in calls:
        if ln in rung:
            continue
        assert "assetless" not in ln and "hole_fill" not in ln, (
            f"a deficit carrying the rung's record is written outside "
            f"assetless_rung.write_deficit(): {ln}")
        # CF-0418: still_share.py is the still-share gate's module (its
        # deficit carries a share and spans, never a hole).
        assert "_gate.write_deficit(" in ln or "still_share.write_deficit(" in ln, (
            f"an unnamed write_deficit() call site in the planner: {ln}")


# --------------------------------------------------------------------------
# 3. the join - the rotation's real reader over the file this repo writes
# --------------------------------------------------------------------------

def test_the_rotation_reads_the_enriched_form_and_not_the_prose():
    mod = rotation_shortage()
    if mod is None:
        return
    anchors = mod.anchors_from_deficit(written(refused(), hole_fill=HOLE_FILL))
    assert [a["block_index"] for a in anchors] == [0, 2], anchors
    a0, a2 = anchors
    # Nothing below this line is reachable from the old form: the block
    # indices are all it carried. If the enriched path stopped being taken,
    # these are the assertions that would say so.
    assert a0["intent"] == "a bundle of newspapers tied with string", a0
    assert a0["seconds"] == 4.2 and a2["seconds"] == 3.5, anchors
    assert a0["degraded_from"] == "clip" and a2["degraded_from"] == "unfilled", anchors
    # And the outcome code reaches the classification: block 0 had a
    # `refused[]` entry, block 2 did not. `insert_outcome` is the same value
    # `classify()` is handed, so this pins that the code crossed the boundary
    # at all - and crossed for the block it was written about and no other.
    # Which cause it then produces is the rotation's policy, not this
    # repository's: since CF-0139 the footage fact answers ahead of it.
    assert a0["insert_outcome"] == "no_asset", a0
    assert a2["insert_outcome"] == "", a2
    # The other half of that policy is what this side does care about: the
    # `from` written here is not decorative over there. A block with a
    # degradation record stays a footage shortage - the family CF-0023's
    # shopping list is built from - instead of being answered by the rescue
    # code, which would file a video with no picture in it under
    # "configuration". The family is read from the rotation's own table.
    assert a0["cause"] in mod.FOOTAGE_CAUSES, a0
    assert a2["cause"] in mod.FOOTAGE_CAUSES, a2


def test_a_hole_the_layer_never_saw_is_not_given_an_insert_cause():
    """The early refusal - the probe said the rung cannot reach these holes,
    so the layer never ran. The record hands over an honest empty
    `refused[]`, and the rotation must therefore classify from what the
    footage prose says. An invented code here would be read as fact and
    would beat the prose, turning "no material" into "configuration"."""
    mod = rotation_shortage()
    if mod is None:
        return
    probe = {**meme_layer.empty_hole_fill(),
             "holes": [0, 2], "at_floor": [],
             "note": "the insert rung did not run: block(s) [0, 2] last under the 3.0s"}
    anchors = mod.anchors_from_deficit(written(refused(), hole_fill=probe))
    assert not any(a["cause"].startswith("insert_") for a in anchors), anchors
    # At the field as well as at the cause: since CF-0139 a degradation
    # record would keep an invented code out of `cause` on its own, so the
    # cause alone no longer proves that none was invented.
    assert not any(a["insert_outcome"] for a in anchors), anchors
    assert all(a["intent"] is not None and a["degraded_from"] for a in anchors), anchors


def test_the_old_form_still_reads_so_a_stale_deficit_is_not_a_crash():
    """A `plan.assetless-rung.json` left on disk by a build from before this
    change has no anchors and no hole_fill node. The rotation falls back to
    blocks/reasons for it, and this repository must not make that path
    unreachable by, say, making `anchors` mandatory."""
    mod = rotation_shortage()
    if mod is None:
        return
    old = {"assetless_rung": {"kind": assetless_rung.DEFICIT_KIND, "blocks": [0, 2],
                              "reasons": [a["reason"] for a in ASSETLESS],
                              "passed": False}}
    anchors = mod.anchors_from_deficit(old)
    assert [a["block_index"] for a in anchors] == [0, 2], anchors
    assert all(a["intent"] == "" and a["seconds"] is None for a in anchors), anchors


def test_the_kind_the_rotation_refuses_anything_else_by_is_still_ours():
    mod = rotation_shortage()
    if mod is None:
        return
    assert assetless_rung.DEFICIT_KIND == mod.KIND, (
        f"the deficit kind moved to {assetless_rung.DEFICIT_KIND!r} and the "
        f"rotation refuses anything that is not {mod.KIND!r}")


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
