"""CF-0446: what the rotation's `speech_fit` asks of the draw and of the words.

Since CF-0446 every assignment `rotation/rotate.py assign` prints (and the
`assignment` of an upheld rejection) carries a `speech_fit` record - the
rotation's own reading of whether the pair can carry the channel's expected
speech inside the pattern's block band (`rotate._speech_fit_record`). The
writer copies it verbatim into the script's `pattern.speech_fit`. Two of its
fields are orders to this stage:

* `hold_floor_seconds` - on a pair that fits, the lowest
  `key_frame_hold_seconds` at which the expected speech is still cut into no
  more blocks than the band's top. AHS, batch 2026-09-27T0929Z: list on
  staccato (band 12-24), a hold drawn at 1.8 s, ~49.8 s of speech - at least
  28 blocks, the script went to `skipped`. The pair itself fitted: from 2.08 s
  the speech goes into 24. A draw under the floor is raised to it here, inside
  the window the pair draws from (`validate_patterns.hold_draw_band`); a floor
  over the window's top takes the top and says so in the record.
* `speech_target_seconds` / `speech_target_words` - on a pair issued with no
  compatible pair left (`no_compatible_pair`), the speech length the script has
  to be written to for the pair to be cut inside its band. It is an order to
  the writer, not a refusal: the reading is recorded beside the estimate and
  printed, it stops nothing.

An order with no `speech_fit` (assignments older than CF-0446) is left exactly
as it was: nothing here invents a floor or a target.
"""
import json

SPEECH_FIT_KEY = "speech_fit"
FLOOR_RECORD_KEY = "hold_floor"
TARGET_RECORD_KEY = "speech_target"
HOLD_KEY = "key_frame_hold_seconds"

FLOOR_RAISED = "raised_to_floor"
FLOOR_ABOVE_WINDOW = "floor_above_window"
FLOOR_KEPT = "at_or_above_floor"

TARGET_AT_MOST, TARGET_AT_LEAST = "at_most", "at_least"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def speech_fit_of(order):
    fit = (order or {}).get(SPEECH_FIT_KEY)
    return fit if isinstance(fit, dict) else None


def hold_floor_of(order):
    """The rotation's `hold_floor_seconds` for this order, or None."""
    fit = speech_fit_of(order)
    v = fit.get("hold_floor_seconds") if fit else None
    return float(v) if _num(v) else None


def apply_hold_floor(order, window):
    """`(order, record)` - the order with its drawn hold raised to the floor.

    `window` is `(lo, hi)` the pair draws `key_frame_hold_seconds` from, or
    None. The record is None when there is nothing to apply (no speech_fit, no
    floor, no drawn hold); otherwise it says what the floor was, what was drawn,
    what stands now and why, and is also written onto the returned order under
    `hold_floor`. The input is never mutated.
    """
    floor = hold_floor_of(order)
    params = (order or {}).get("parameters") or {}
    drawn = params.get(HOLD_KEY)
    if floor is None or not _num(drawn):
        return order, None
    out = json.loads(json.dumps(order))
    drawn = float(drawn)
    rec = {"hold_floor_seconds": floor, "drawn_seconds": drawn,
           "draw_window": list(window) if window else None,
           "source": f"pattern.{SPEECH_FIT_KEY}.hold_floor_seconds (rotate.py assign, CF-0446)"}
    if drawn >= floor - 1e-9:
        rec.update(finding=FLOOR_KEPT, key_frame_hold_seconds=drawn,
                   reason=f"the drawn hold {drawn:.2f}s is at or above the rotation's floor "
                          f"{floor:.2f}s - left as drawn")
    else:
        target, finding = floor, FLOOR_RAISED
        if window and floor > float(window[1]) + 1e-9:
            target, finding = round(float(window[1]), 2), FLOOR_ABOVE_WINDOW
        target = round(max(target, drawn), 2)
        out["parameters"][HOLD_KEY] = target
        if finding == FLOOR_RAISED:
            why = (f"the drawn hold {drawn:.2f}s is under the rotation's floor {floor:.2f}s - "
                   f"under it the channel's expected speech needs more blocks than the "
                   f"pattern's band allows; raised to {target:.2f}s")
        else:
            why = (f"the rotation's floor {floor:.2f}s is over the top of the window "
                   f"{float(window[0]):.2f}-{float(window[1]):.2f}s this pair draws from; the "
                   f"hold {drawn:.2f}s is raised to the window's top {target:.2f}s and the "
                   f"speech may still need more blocks than the band's top")
        rec.update(finding=finding, key_frame_hold_seconds=target, reason=why)
    out[FLOOR_RECORD_KEY] = rec
    return out, rec


def hold_under_floor(order):
    """`(drawn, floor)` when this order's drawn hold is under its floor, else None."""
    floor = hold_floor_of(order)
    drawn = ((order or {}).get("parameters") or {}).get(HOLD_KEY)
    if floor is None or not _num(drawn) or float(drawn) >= floor - 1e-9:
        return None
    return float(drawn), floor


def speech_target_of(order):
    """The writer's speech target from `speech_fit`, or None.

    `{"seconds", "words", "direction", "expected_speech_seconds"}`; the
    direction is `at_most` when the target is under the channel's expected
    speech (the pair's band top cannot hold it) and `at_least` otherwise."""
    fit = speech_fit_of(order)
    if not fit or not _num(fit.get("speech_target_seconds")):
        return None
    seconds = float(fit["speech_target_seconds"])
    expected = fit.get("expected_speech_seconds")
    direction = (TARGET_AT_MOST if not _num(expected) or seconds < float(expected)
                 else TARGET_AT_LEAST)
    words = fit.get("speech_target_words")
    return {"seconds": seconds, "words": int(words) if _num(words) else None,
            "direction": direction,
            "expected_speech_seconds": float(expected) if _num(expected) else None}


def target_reading(order, estimated_seconds, words, tolerance=0.0):
    """The estimate of this script's speech against its `speech_fit` target,
    or None when the order carries no target. Never a refusal."""
    t = speech_target_of(order)
    if t is None or not _num(estimated_seconds):
        return None
    est, tol = float(estimated_seconds), float(tolerance or 0.0)
    if t["direction"] == TARGET_AT_MOST:
        met = est <= t["seconds"] + tol
        side = "at most"
    else:
        met = est >= t["seconds"] - tol
        side = "at least"
    in_words = f" (~{t['words']} words)" if t["words"] else ""
    reason = (f"the rotation issued this pair with a speech target of {side} "
              f"{t['seconds']:g}s{in_words} (pattern.{SPEECH_FIT_KEY}, no compatible pair "
              f"for the channel's expected speech); this reading is {est:g}s, {words} words - "
              + ("on target" if met else
                 f"{'cut' if t['direction'] == TARGET_AT_MOST else 'add'} "
                 f"{abs(est - t['seconds']):.1f}s to reach it, or the layout runs "
                 f"{'over the top' if t['direction'] == TARGET_AT_MOST else 'under the floor'} "
                 f"of the pattern's block band"))
    return {"speech_target_seconds": t["seconds"], "speech_target_words": t["words"],
            "direction": t["direction"], "estimated_seconds": est, "words": words,
            "tolerance_seconds": tol, "met": met, "reason": reason}
