#!/usr/bin/env python3
"""CF-0041: `executable_today` has to mean something the code can do.

Cross-agent, so it lives here rather than in agents/video-editor: the claim is
made in patterns/rhythms.json, which the factory owns, and it is acted on by the
rotation (CF-0040), which will assign a pair the moment the flag says yes. The
executor is in one agent. Nobody owns both ends, so the join is checked here.

The failure this prevents is specific and it has already been designed against
twice: a rhythm written into the vocabulary, flagged executable because it looks
finished, assigned by the rotation, and then silently ignored by Video Editor -
leaving a rhythm in the metadata that is not in the video. rotate.py's docstring
names it, patterns/rhythms.json carries the flag for it, and this is the test
that makes the flag a fact rather than an intention.

Deliberately shallow, not thorough: it asserts an executor and a verifier exist
for every rhythm and opening the vocabulary claims, not that they are any good.
What the four rhythms actually produce is measured on real material in
agents/video-editor/tests/test_rhythm_execution.py, where the fixtures are.

The openings are asked behaviourally rather than structurally (CF-0050) for a
reason worth keeping: the previous version compared the flag against a set of
names copied into this file, which is a second place for the answer to live and
therefore a second place for it to be wrong. `rhythm.resolve_opening()` is the
executor's own answer, so asking it is asking the code that actually decides.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "agents" / "video-editor" / "scripts"))

import validate_patterns as vp  # noqa: E402
import rhythm  # noqa: E402


def executable_rhythms():
    return [r["rhythm_id"] for r in vp.load_rhythms()["rhythms"] if r["executable_today"]]


def executable_openings():
    return [o["kind"] for o in vp.load_rhythms()["opening_block_kinds"]
            if o["executable_today"]]


def test_every_executable_rhythm_has_a_planner():
    """A rhythm the vocabulary says is buildable must have something that
    builds it - not a branch that falls through to the default."""
    for rid in executable_rhythms():
        assert rid in rhythm.RHYTHMS, (
            f"patterns/rhythms.json says {rid!r} is executable today, but "
            f"rhythm.py does not know the id at all")
        assert rid in rhythm._PLANNERS, (
            f"{rid!r} is flagged executable with no planner - the rotation will "
            f"assign it and Video Editor will quietly build something else")


def test_every_executable_rhythm_has_a_verifier():
    """And something that can say afterwards whether it actually happened.

    A planner without a verifier is worse than no rhythm: `rhythm_delivered`
    would report the order back as if it were the outcome, which is the exact
    confusion CF-0015's requested/delivered pairs exist to prevent.
    """
    blocks = [{"start": 0.0, "end": 2.0, "asset": {"kind": "clip"}},
              {"start": 2.0, "end": 4.0, "asset": {"kind": "clip"}},
              {"start": 4.0, "end": 6.0, "asset": {"kind": "clip"}}]
    for rid in executable_rhythms():
        order = {"pattern_id": "explainer", "rhythm_id": rid, "parameters": {}}
        delivered, reasons = rhythm.verify_rhythm(order, blocks)
        assert delivered in (rid, None), (
            f"verify_rhythm({rid!r}) answered {delivered!r} - it may only confirm "
            f"the ordered rhythm or refuse it")
        assert delivered is not None or reasons, (
            f"verify_rhythm refused {rid!r} without saying why - an unexplained "
            f"refusal is indistinguishable from a missing verifier")


# Everything each opening needs before it can be built, as the arguments
# rhythm.resolve_opening() asks for. A new opening kind that this file does not
# know about fails the test below rather than being skipped by it - "no
# preconditions listed" must not read as "nothing to check".
OPENING_PRECONDITIONS = {
    "hook_over_footage": {},
    "count_card": {"card_text": "SIX THINGS"},
    "cold_frame": {"lead_silence": rhythm.COLD_FRAME_MIN_LEAD_SECONDS},
    "side_by_side": {"sides_resolved": 2},
}


def test_every_executable_opening_is_one_the_editor_builds():
    """The openings are on the same flag and the same hook.

    All four are executable since CF-0050. Asked behaviourally rather than
    against a list of names copied into this file: given everything the opening
    needs, the executor has to answer with that opening. A flag flipped on an
    opening nobody builds comes back as `hook_over_footage` here, which is
    exactly what the video would do - the rotation would hand out a pattern
    whose opening is quietly replaced.
    """
    for kind in executable_openings():
        assert kind in rhythm.OPENING_KINDS, f"rhythm.py does not know {kind!r}"
        assert kind in OPENING_PRECONDITIONS, (
            f"opening {kind!r} is flagged executable and this test does not know "
            f"what it needs - add it to OPENING_PRECONDITIONS with the arguments "
            f"rhythm.resolve_opening() wants, or the check silently passes it")
        delivered, reason = rhythm.resolve_opening(
            kind, **OPENING_PRECONDITIONS[kind])
        assert delivered == kind, (
            f"opening {kind!r} is flagged executable, but with everything it "
            f"needs the editor still delivers {delivered!r} ({reason}) - flip it "
            f"back or implement it")


def test_an_opening_that_cannot_be_built_falls_back_in_writing():
    """The other half of the same join, and the reason the fallback is safe.

    `validate_patterns.draw_order()` picks from a pattern's `choices` at random
    with no executability filter, so an opening whose precondition is missing on
    this particular script has to come back as `hook_over_footage` *with a
    reason* rather than as itself. A silent fallback would put an opening in
    `05-video-editor.json` that is not in the video, which is the same defect
    class the executable flag exists to prevent.
    """
    for kind in executable_openings():
        if kind == "hook_over_footage":
            continue  # nothing to be missing; it is the fallback itself
        delivered, reason = rhythm.resolve_opening(kind)
        assert delivered == "hook_over_footage", (
            f"opening {kind!r} with none of its preconditions met came back as "
            f"{delivered!r} - it would be recorded as delivered when it was not")
        assert reason, (
            f"opening {kind!r} fell back without saying why - an unexplained "
            f"fallback is indistinguishable from the opening having been built")


def test_a_blocked_rhythm_or_opening_still_names_a_real_open_task():
    """The other half: what is not executable has to say who owes it."""
    r = vp.load_rhythms()
    for item in r["rhythms"] + r["opening_block_kinds"]:
        if item["executable_today"]:
            assert not item["blocked_by"], (
                f"{item.get('rhythm_id') or item.get('kind')!r} is executable but "
                f"still names a blocker {item['blocked_by']!r}")
            continue
        blocker = item["blocked_by"]
        files = sorted((ROOT / "tasks").rglob(f"{blocker}-*.md"))
        assert files, (
            f"{item.get('rhythm_id') or item.get('kind')!r} is blocked by "
            f"{blocker}, which has no task file")
        status = ""
        for line in files[0].read_text().splitlines():
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
                break
        assert status not in ("done", "closed"), (
            f"{blocker} is {status} but "
            f"{item.get('rhythm_id') or item.get('kind')!r} is still flagged "
            f"un-executable - flip executable_today or reopen the task")




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
