#!/usr/bin/env python3
"""CF-0567: the `own_capture` source kind through the editor - no credit row
and no on-screen credit, the page on the plan's record (`own_captures`), the
two-source gate's reading of our own recording, and the frame judge told that
a recording's interface text is the footage.

Stand-ins only: hand-made plans, a tmp pool with a recorder sidecar, a tmp
batch and factory root. No network, no real batch, no pool, no render.
"""
import _isolated_runlog  # noqa: F401 - CF-0482: run accounting never lands in a real batch
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import footage_credits as fc  # noqa: E402
import frame_judge_pack as pack  # noqa: E402
import source_gate  # noqa: E402
import write_batch_metadata  # noqa: E402

OWN_A = "own_capture-acme-fox-demo-20261011t120000z"
OWN_B = "own_capture-acme-fox-demo-20261011t121500z"
VENDOR = "vendorQuote"      # an 11-char YouTube id - a vendor's official upload
YT_A, YT_B = "trailerAAAA", "trailerBBBB"

RIGHTS = {
    VENDOR: {"judged": True, "accepted": True, "licence": "youtube_official_upload",
             "footage_origin": "vendor_official", "credit": "the channel's name and the link",
             "credit_from": "footage_origins", "on_screen": False, "where": "description",
             "source_url": f"https://www.youtube.com/watch?v={VENDOR}"},
    # what the Footage Indexer may write for a recording (FI step): judged,
    # licence own_capture - still never a credit row
    OWN_A: {"judged": True, "accepted": True, "licence": "own_capture",
            "footage_origin": "own_capture", "attribution": "none", "on_screen": False,
            "credit": None, "source_url": "https://acme-fox-demo.hf.space/"},
}
ORIGINS = {"licences": {"accepted": [{"id": "own_capture"}, {"id": "youtube_official_upload"}]},
           "footage_origins": [{"id": "own_capture", "who": "the factory itself"},
                               {"id": "vendor_official", "who": "the vendors' own channels"}]}
SIDECAR = {"schema": "own-capture/1", "origin": "own_capture", "id": "own_capture:x",
           "url": "https://acme-fox-demo.hf.space/", "final_url": "https://acme-fox-demo.hf.space/",
           "host": "acme-fox-demo.hf.space", "capture_host": "hf.space",
           "host_entry": {"host": "hf.space", "use": "capture", "sign_in": False},
           "space": {"id": "acme/fox-demo", "licence": "apache-2.0"},
           "captured_at": "2026-10-11T12:00:00Z", "duration_s": 14.2}


def _reader(rights=RIGHTS):
    return lambda vid: (rights.get(vid), "01b") if vid in rights else (None, None)


def _block(start, end, vid, kind="clip"):
    return {"start": start, "end": end, "shot": f"{vid}:2",
            "asset": {"kind": kind, "src": f"/nonexistent/a00_{vid}_s002.mp4"}}


def _plan(blocks):
    return {"style": "motion", "blocks": blocks, "words": [],
            "duration": {"actual": blocks[-1]["end"], "composition": blocks[-1]["end"] + 3},
            "watermark": {"text": "EXAMPLE_TECH", "position": "top-left"}}


def _demo_plan():
    return _plan([_block(0.0, 6.0, OWN_A), _block(6.0, 10.0, VENDOR),
                  _block(10.0, 20.0, OWN_A), _block(20.0, 26.0, OWN_B)])


def test_own_capture_gets_no_credit_row_no_overlay_and_no_note():
    rows, overlays, notes = fc.plan_credits(_demo_plan(), _reader(), ORIGINS)
    assert [r["video_id"] for r in rows] == [VENDOR], rows
    assert "own_capture" not in json.dumps(overlays), overlays
    assert not any("own_capture" in n for n in notes), notes
    # an id without the prefix whose rights say own_capture is ours too
    other = "ownRecord01"
    rights = {**RIGHTS, other: dict(RIGHTS[OWN_A])}
    rows, overlays, notes = fc.plan_credits(_plan([_block(0.0, 5.0, other)]),
                                            _reader(rights), ORIGINS)
    assert rows == [] and overlays == [] and notes == [], (rows, overlays, notes)
    assert fc.is_own_capture(OWN_B) and fc.is_own_capture("x", {"licence": "own_capture"})
    assert not fc.is_own_capture(VENDOR, RIGHTS[VENDOR])


def test_the_plan_keeps_the_page_of_each_recording():
    with tempfile.TemporaryDirectory() as tmp:
        pool = Path(tmp)
        (pool / f"{OWN_A}.own_capture.json").write_text(json.dumps(SIDECAR))
        rows = fc.plan_own_captures(_demo_plan(), _reader(), [str(pool)])
    by = {r["video_id"]: r for r in rows}
    assert list(by) == [OWN_A, OWN_B], rows
    a = by[OWN_A]
    assert a["record_from"] == "sidecar" and a["url"] == SIDECAR["url"]
    assert a["capture_host"] == "hf.space" and a["space_licence"] == "apache-2.0"
    assert a["blocks"] == [0, 2] and a["seconds_on_screen"] == 16.0, a
    assert a["credit"] is None and a["first_at_s"] == 0.0
    # no sidecar, no rights record: listed with nulls, nothing invented
    b = by[OWN_B]
    assert b["record_from"] is None and b["url"] is None and b["space_licence"] is None, b
    plan = {**_demo_plan(), fc.OWN_CAPTURES_FIELD: rows}
    assert fc.own_capture_stage_fields(plan)[0]["video_id"] == OWN_A
    assert fc.own_capture_stage_fields({}) is None


def test_build_own_captures_reads_the_pool():
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = tmp / "root"
        (root / "channels" / "techstand").mkdir(parents=True)
        (root / "channels" / "techstand.json").write_text(json.dumps({"channel_id": "techstand"}))
        (root / "channels" / "techstand" / "footage-origin.json").write_text(json.dumps(ORIGINS))
        batch = tmp / "batch"
        (batch / "work" / "slug").mkdir(parents=True)
        pool = tmp / "pool"
        pool.mkdir()
        (pool / f"{OWN_A}.shots.json").write_text(json.dumps({"shots": []}))
        (pool / f"{OWN_A}.own_capture.json").write_text(json.dumps(SIDECAR))
        args = argparse.Namespace(footage_index=None, index=[str(pool / f"{OWN_A}.shots.json")],
                                  channel="techstand",
                                  output=str(batch / "work" / "slug" / "plan.json"))
        env = {k: os.environ.get(k) for k in ("FACTORY_ROOT", "FOOTAGE_DIR")}
        os.environ["FACTORY_ROOT"] = str(root)
        os.environ["FOOTAGE_DIR"] = str(tmp / "empty-pool")
        try:
            rows, notes = brp.build_own_captures(args, _demo_plan())
            credit_rows, overlays, _ = brp.build_footage_credits(args, _demo_plan())
        finally:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    assert notes == [] and [r["video_id"] for r in rows] == [OWN_A, OWN_B], (rows, notes)
    assert rows[0]["url"] == SIDECAR["url"]
    assert not any(r["video_id"].startswith("own_capture-") for r in credit_rows), credit_rows


def test_two_recordings_are_not_two_sources():
    rec = source_gate.judge(_plan([_block(0.0, 6.0, OWN_A), _block(6.0, 12.0, OWN_B)]))
    assert rec["count"] == 0 and rec["canonical_ids"] == [], rec
    assert rec["own_capture_ids"] == [OWN_A, OWN_B] and rec["own_capture_blocks"] == [0, 1]
    # nothing borrowed: the rule does not apply, and it says it is our recording
    assert rec["applies"] is False and rec["passed"] is True and "own_capture" in rec["note"]


def test_a_recording_base_carries_one_borrowed_quote():
    rec = source_gate.judge(_demo_plan())
    assert rec["applies"] and rec["count"] == 1 and rec["canonical_ids"] == [VENDOR], rec
    assert rec["own_capture_seconds"] == 22.0 and rec["borrowed_seconds"] == 4.0, rec
    assert rec["passed"] is True and "base" in rec["note"], rec["note"]
    assert any("own capture" in line for line in source_gate.report_lines(rec))


def test_a_recording_under_the_borrowed_footage_does_not_save_one_source():
    plan = _plan([_block(0.0, 2.0, OWN_A), _block(2.0, 12.0, YT_A)])
    rec = source_gate.judge(plan)
    assert rec["passed"] is False and rec["count"] == 1, rec


def test_reel_and_science_plans_read_exactly_as_before():
    plan = _plan([_block(0.0, 4.0, YT_A), _block(4.0, 8.0, YT_B), _block(8.0, 12.0, YT_A)])
    rec = source_gate.judge(plan)
    assert rec["passed"] and rec["count"] == 2 and rec["canonical_ids"] == [YT_A, YT_B]
    assert rec["own_capture_ids"] == [] and rec["own_capture_seconds"] == 0.0
    assert rec["footage_blocks"] == [0, 1, 2]
    one = source_gate.judge(_plan([_block(0.0, 4.0, YT_A)]))
    assert one["passed"] is False and "compilation" in one["note"]


def test_seconds_by_source_reads_cuts_and_halves():
    seq = {"start": 0.0, "end": 6.0, "asset": {"kind": "sequence", "cuts": [
        {"src": f"/x/a00_{OWN_A}_s001.mp4", "seconds": 4.0},
        {"src": f"/x/a01_{VENDOR}_s002.mp4", "seconds": 2.0}]}}
    assert source_gate.block_source_seconds(seq) == {OWN_A: 4.0, VENDOR: 2.0}
    split = {"start": 0.0, "end": 5.0, "asset": {"kind": "split", "halves": [
        {"shot": f"{OWN_A}:1"}, {"shot": f"{YT_A}:2"}]}}
    assert source_gate.block_source_seconds(split) == {OWN_A: 5.0, YT_A: 5.0}
    typo = {"start": 0.0, "end": 5.0, "shot": f"{YT_A}:1", "asset": {"kind": "typographic"}}
    assert source_gate.block_source_seconds(typo) == {}


def test_the_judge_reads_a_recordings_interface_as_the_footage():
    plan = _demo_plan()
    entries = pack.entries_for(plan, 26.0)
    by = {e["block"]: e for e in entries}
    for i in (0, 2, 3):
        kinds = [o["kind"] for o in by[i]["overlays"]]
        assert "own_capture_ui" in kinds, by[i]["overlays"]
        assert by[i]["source"]["own_capture"] is True and by[i]["judged"] is True
    assert "own_capture_ui" not in [o["kind"] for o in by[1]["overlays"]]
    assert by[1]["source"]["own_capture"] is False
    ours = pack.ours_on_screen({**plan, fc.OWN_CAPTURES_FIELD: [
        {"video_id": OWN_A, "url": SIDECAR["url"]}]})
    assert ours["own_capture"]["blocks"] == [0, 2, 3], ours["own_capture"]
    assert ours["own_capture"]["sources"] == [OWN_A, OWN_B]
    assert ours["own_capture"]["pages"] == [{"video_id": OWN_A, "url": SIDECAR["url"]}]
    assert "foreign_text" in ours["own_capture"]["note"]
    # a plan with no recording: the key is there and empty
    reel = pack.ours_on_screen(_plan([_block(0.0, 4.0, YT_A)]))
    assert reel["own_capture"]["blocks"] == [] and reel["own_capture"]["sources"] == []


def test_the_stage_record_carries_own_captures():
    src = Path(write_batch_metadata.__file__).read_text()
    assert "footage_credits.OWN_CAPTURES_FIELD: footage_credits.own_capture_stage_fields(plan)" \
        in src


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
