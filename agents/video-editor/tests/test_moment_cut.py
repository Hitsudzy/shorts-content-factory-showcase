#!/usr/bin/env python3
"""CF-0106: a shot with a `moment_at` mark is cut from the mark, not from
its head; a shot without one is cut exactly as before; a mark outside the
shot is refused with a clear error rather than clamped.

The mark is set by the describer (footage-indexer's skill step) and reaches
this script on the matcher's own match record, alongside `start`/`end`/
`score`. The clip starts MOMENT_LEAD_SECONDS ahead of the mark - the moment
near the head of the window, not on its first frame - and the window never
leaves the shot's own bounds.

Pure asserts against cut_start() / available_seconds() / moment_of(), plus
cut_usable() with the ffmpeg cut and the gate stubbed - no ffmpeg, no
Vision, no index on disk.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_render_plan  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402

LEAD = ra.MOMENT_LEAD_SECONDS


def cand(moment_at="absent", start=10.0, end=25.0, card=False):
    """One match record as match() hands it on: the matcher's keys plus the
    index/source this script adds. `moment_at="absent"` leaves the key out
    entirely - an index written before CF-0106."""
    c = {"shot": 7, "start": start, "end": end, "score": 0.31, "card": card,
         "promoted": False, "index": "/idx/shots.json", "source": "/src/clip.mp4"}
    if moment_at != "absent":
        c["moment_at"] = moment_at
    return c


ARGS = SimpleNamespace(min_short_side=720, min_coverage=0.65, max_black=0.9)


@contextlib.contextmanager
def stubbed_cut():
    """cut_usable() with everything past the window stubbed: records what
    the cut was asked for, passes the gate, captures stderr."""
    calls, err = [], io.StringIO()
    saved = (ra.cut, ra.usable, ra.probably_unusable)

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        # `card` (CF-0092) picks the caption-crop policy inside the real cut();
        # it is recorded so a test can check that the moment-aware start and
        # the card flag reach cut() together - two concerns, one call.
        calls.append({"source": source, "start": start, "duration": duration,
                      "card": card})
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    ra.cut = fake_cut
    ra.usable = lambda *a, **k: (True, [])
    ra.probably_unusable = lambda *a, **k: False
    try:
        with contextlib.redirect_stderr(err):
            yield calls, err
    finally:
        ra.cut, ra.usable, ra.probably_unusable = saved


def run_cut_usable(c, need=3.0):
    with tempfile.TemporaryDirectory() as tmp, stubbed_cut() as (calls, err):
        rec = ra.cut_usable(c, need, Path(tmp) / "a00_clip_s007.mp4", {}, ARGS)
        return rec, calls, err.getvalue()


# --- no mark: the head, exactly as before -----------------------------------

def test_a_shot_without_a_mark_cuts_from_its_head():
    for c in (cand(), cand(moment_at=None)):
        assert ra.moment_of(c) is None
        assert ra.cut_start(c) == (10.0, "head")
        assert ra.available_seconds(c) == 15.0


def test_a_shot_without_a_mark_is_cut_exactly_as_before():
    """Regression: same start, same span, no moment line, and the record
    says `head` so the storyboard can tell the two apart."""
    rec, calls, err = run_cut_usable(cand(), need=3.0)
    assert calls == [{"source": "/src/clip.mp4", "start": 10.0, "duration": 3.0,
                      "card": False}], calls
    assert rec["cut_at"] == 10.0 and rec["cut_origin"] == "head", rec
    assert rec["moment_at"] is None
    assert rec["seconds"] == 3.0
    assert "CUT FROM MOMENT" not in err and "MOMENT REJECTED" not in err, err


# --- a mark: a lead ahead of it, clamped to the shot -------------------------

def test_the_lead_is_the_anchor_lead_not_a_second_number():
    """The moment sits near the head of the window but not on its first
    frame; the amount is the 0.35s the anchor timing already uses."""
    assert LEAD == rhythm.LEAD_SECONDS
    assert 0.0 < LEAD < 1.0, LEAD


def test_a_marked_shot_cuts_a_lead_ahead_of_the_mark():
    c = cand(moment_at=14.0)
    at, origin = ra.cut_start(c)
    assert origin == "moment"
    assert abs(at - (14.0 - LEAD)) < 1e-9, at
    assert abs(ra.available_seconds(c) - (25.0 - at)) < 1e-9
    # The mark is inside the window, after its first frame.
    assert at < 14.0 < at + 1.0


def test_a_mark_near_the_head_is_clamped_to_the_head():
    """A mark closer to the shot's start than the lead: the window may not
    begin before the shot, so it begins at the shot - still a moment cut."""
    c = cand(moment_at=10.2)
    assert ra.cut_start(c) == (10.0, "moment")
    c = cand(moment_at=10.0)
    assert ra.cut_start(c) == (10.0, "moment")


def test_the_window_never_runs_past_the_shot_end():
    """A mark near the end: the span is what the shot has left after the
    cut point, not the block's full need."""
    rec, calls, err = run_cut_usable(cand(moment_at=24.5), need=3.0)
    assert len(calls) == 1, calls
    assert abs(calls[0]["start"] - (24.5 - LEAD)) < 1e-9, calls
    assert abs(calls[0]["duration"] - (25.0 - (24.5 - LEAD))) < 1e-9, calls
    assert calls[0]["start"] + calls[0]["duration"] <= 25.0 + 1e-9
    assert rec["cut_origin"] == "moment"


def test_a_mark_at_the_very_end_leaves_nothing_to_cut():
    """Mark == end: the lead alone is under the 0.7s minimum, so the
    candidate is skipped the way any too-short candidate is - not cut from
    the head instead, which would show the wrong picture."""
    rec, calls, err = run_cut_usable(cand(moment_at=25.0), need=3.0)
    assert rec is None and calls == [], (rec, calls)


def test_cut_usable_threads_the_moment_into_the_cut_the_record_and_the_log():
    rec, calls, err = run_cut_usable(cand(moment_at=14.0), need=3.0)
    assert len(calls) == 1
    assert abs(calls[0]["start"] - (14.0 - LEAD)) < 1e-9, calls
    assert calls[0]["duration"] == 3.0
    assert rec["cut_origin"] == "moment" and rec["moment_at"] == 14.0, rec
    assert abs(rec["cut_at"] - (14.0 - LEAD)) < 1e-3, rec
    assert "CUT FROM MOMENT a00_clip_s007.mp4" in err, err
    assert "moment_at=14.00s" in err and "[10.00, 25.00]" in err, err


def test_a_marked_card_reaches_cut_with_both_the_moment_and_the_card_flag():
    """Two concerns, one call: CF-0092/CF-0103's caption-crop policy needs
    `card=` and CF-0106 needs the moment-aware start. A marked title card
    hands cut() both - neither mechanism displaces the other."""
    rec, calls, _ = run_cut_usable(cand(moment_at=14.0, card=True), need=3.0)
    assert len(calls) == 1
    assert calls[0]["card"] is True, calls
    assert abs(calls[0]["start"] - (14.0 - LEAD)) < 1e-9, calls
    assert rec["card"] is True and rec["cut_origin"] == "moment", rec
    _, plain_calls, _ = run_cut_usable(cand(moment_at=14.0), need=3.0)
    assert plain_calls[0]["card"] is False, plain_calls


def test_a_long_enough_first_sort_reads_the_span_after_the_mark():
    """The "long enough for the block" preference an ordered rhythm makes
    has to see what is left after the cut point: a 15s shot marked at 24.5s
    is not long enough for a 3s block any more."""
    marked_late, plain_short = cand(moment_at=24.5), cand(start=10.0, end=12.5)
    pool = sorted([marked_late, plain_short, cand(moment_at=14.0)],
                  key=lambda c: ra.available_seconds(c) < 3.0)
    assert pool[0].get("moment_at") == 14.0, pool


# --- a mark outside the shot: refused in writing -----------------------------

def test_a_mark_outside_the_shot_is_rejected_with_a_clear_error():
    for bad in (9.9, 25.1, -1.0):
        c = cand(moment_at=bad)
        try:
            ra.moment_of(c)
        except ra.MomentOutOfBounds as e:
            msg = str(e)
            assert "outside the shot" in msg and "[10.00, 25.00]" in msg, msg
            assert f"moment_at={bad:.2f}s" in msg and "shot 7" in msg, msg
            assert "CF-0106" in msg
        else:
            raise AssertionError(f"moment_at={bad} was accepted")
        assert isinstance(ra.MomentOutOfBounds(""), ValueError)
        # Never raises from a sort key; sorts last instead.
        assert ra.available_seconds(c) == 0.0


def test_a_mark_that_is_not_a_number_is_rejected_too():
    try:
        ra.moment_of(cand(moment_at="soon"))
    except ra.MomentOutOfBounds as e:
        assert "not a timecode" in str(e), str(e)
    else:
        raise AssertionError("a non-numeric moment_at was accepted")


def test_cut_usable_refuses_a_bad_mark_without_cutting_or_clamping():
    rec, calls, err = run_cut_usable(cand(moment_at=30.0), need=3.0)
    assert rec is None and calls == [], (rec, calls)
    assert "MOMENT REJECTED" in err and "outside the shot" in err, err


def test_the_block_loop_cuts_from_the_same_window():
    """main()'s fill() is a closure over the block loop, so the source has to
    say it: both cut sites take the window's start, none the shot's head,
    and a bad mark lands on `rejected_candidates` rather than aborting."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    assert src.count('cut(cand["source"], at, span,') == 2, "both cut sites use the window"
    assert 'cut(cand["source"], cand["start"]' not in src, "a cut site still uses the head"
    # CF-0140: the window and the bad-mark refusal moved out of fill() into
    # resolve_anchors.precut_refusal(), which is now the one place either is
    # written and which fill(), cut_usable() and the coverage preflight all
    # ask. So the pin follows it: `at` still comes from cut_start(), the two
    # cut sites still take it, and a bad mark is still a rejected_candidates
    # entry rather than an abort - just in one function instead of two copies.
    # CF-0137 gave fill() a `reuse_key` parameter (the one emergency repeat);
    # the signature is matched loosely so the check stays about the cut site.
    assert 'precut_refusal(' in src.split("def fill(pool")[1], \
        "fill() no longer takes its window from the shared pre-cut gate"
    gate = src.split("def precut_refusal(")[1].split("\ndef ")[0]
    assert 'cut_start(cand)' in gate
    assert '"reason": f"moment_at rejected: {e}"' in gate
    assert src.count("def precut_refusal(") == 1, "a second copy of the pre-cut gate"


# --- the plan carries the cut point through to QC -----------------------------

def test_the_plan_carries_the_cut_point():
    carried = build_render_plan.carry_rhythm(
        {"rhythm_role": "beat", "side": None, "shot": "clip:7", "held_frame": False,
         "cut_at": 13.65, "cut_origin": "moment", "moment_at": 14.0})
    assert carried["cut_at"] == 13.65 and carried["cut_origin"] == "moment"
    assert carried["moment_at"] == 14.0
    head = build_render_plan.carry_rhythm(
        {"shot": "clip:7", "cut_at": 10.0, "cut_origin": "head", "moment_at": None})
    assert head["cut_origin"] == "head" and "moment_at" not in head


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    passed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"PASS {name}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
