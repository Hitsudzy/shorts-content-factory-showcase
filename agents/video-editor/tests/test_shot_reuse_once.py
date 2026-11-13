#!/usr/bin/env python3
"""CF-0121: one sample, one use.

The operator's decision in CF-0074 (2026-09-05) is "no repeats by frame - a
sample is used once in a video". CF-0026 had measured the defect (one clip
carrying 40% of a runtime) and capped reuse at 3 with the caveat "2-3 times,
and only when the script asks for it"; the decision withdrew the caveat's
licence, and this suite is what holds the code to it.

The interesting part is not the constant - it is that a repeat used to be the
resolver's *sink*. When the pool ran dry the shortage drained into showing a
shot again, and only the fourth showing surfaced as an unresolved anchor. With
the sink closed, an anchor whose best candidate is already spent must fall
through to the next distinct sample, and, failing that, into
`unresolved_anchors` and a typographic block - the shortage visible as a
missing picture instead of hidden as a familiar one. So both halves of that
sentence are tested here, on the real fill loop.

Four selection paths could each have kept their own idea of "already used", and
before this task three of them did. They now share `rhythm.ShotLedger`:

  1. an ordinary block's fill loop (`resolve_anchors.main`),
  2. the `even` fill that puts several cuts inside one anchor's stretch
     (CF-0028),
  3. the `side_by_side` opening's two sides and each side's own run of cuts
     (CF-0075),
  4. clip -> still degradation, which is not a fourth chooser at all and is
     pinned here as exactly that.

The last test greps the sources, because "one shared check" is a property of
the codebase rather than of any run: a future caller (CF-0120's multi-shot
swing block is the one in the queue) must not be able to compare against the
constant on its own.

Synthetic and fast - the matcher, the cutter and the gate are doubles, nothing
here touches ffmpeg or CLIP.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402

IDX = "/nowhere/pool.shots.json"
SRC = "/nowhere/pool.mp4"
MIN_SCORE = 0.22


# --------------------------------------------------------------------------
# the ledger itself
# --------------------------------------------------------------------------

def test_the_cap_is_one_and_a_second_showing_is_blocked():
    assert rhythm.MAX_SHOT_REUSE == 1, (
        "CF-0074's decision is one sample, one use - if this is being raised "
        "again, it is a decision to re-take with the operator, not a threshold "
        "to tune")
    led = rhythm.ShotLedger()
    key = (SRC, 7)
    assert not led.blocked(key) and led.count(key) == 0
    assert led.take(key) == 1
    assert led.blocked(key), "the sample is spent after one showing"
    assert led.distinct == 1 and led.total == 1


def test_a_measurement_cap_is_the_only_way_to_get_the_old_behaviour():
    """The flag exists for CF-0121's own before/after measurement, and it has
    to be passed explicitly - the default is the rule."""
    led = rhythm.ShotLedger(3)
    key = (SRC, 7)
    for _ in range(3):
        assert not led.blocked(key)
        led.take(key)
    assert led.blocked(key) and led.count(key) == 3
    assert rhythm.ShotLedger().max_uses == 1


def test_a_fork_never_writes_back():
    """A `side_by_side` opening is resolved before it is known to be
    deliverable, and a discarded half's shots were never on screen. So the
    opening resolves against a fork, and only the delivered cuts are taken on
    the video's own ledger."""
    led = rhythm.ShotLedger()
    led.take((SRC, 1))
    fork = led.fork()
    assert fork.blocked((SRC, 1)), "a fork starts from what is already spent"
    fork.take((SRC, 2))
    assert not led.blocked((SRC, 2)), "the fork wrote back into the real ledger"
    assert led.uses() == {(SRC, 1): 1}


def test_the_reasons_say_which_rule_turned_the_candidate_away():
    one, three = rhythm.ShotLedger(), rhythm.ShotLedger(3)
    assert "one sample, one use" in one.reason((SRC, 1))
    assert "CF-0121" in one.reason((SRC, 1))
    assert "3x" in three.reason((SRC, 1)) and "CF-0026" in three.reason((SRC, 1))
    # The pool-wide wording keeps the opening `gate_verdict()` has always had,
    # because tests and operators read reports by that prefix.
    assert one.exhausted_reason().startswith("every remaining candidate was already used")
    assert three.exhausted_reason().startswith("every remaining candidate was already used")


# --------------------------------------------------------------------------
# main(): the real fill loop, with the matcher / cutter / gate replaced
# --------------------------------------------------------------------------

def _index(n, seconds=3.0):
    return {"source": SRC,
            "shots": [{"index": i, "start": i * 100.0, "end": i * 100.0 + seconds}
                      for i in range(n)]}


@contextlib.contextmanager
def _patched(candidates, gate, index_data, words, duration):
    saved = {k: getattr(ra, k) for k in
             ("match", "cut", "usable", "hold_frame", "audio_duration",
              "leading_silence", "load_words")}
    shot_span = {s["index"]: (s["start"], s["end"]) for s in index_data[IDX]["shots"]}

    def fake_match(indexes, phrases, min_score, top, python):
        out = []
        for ph in phrases:
            cands = [{"shot": s, "score": sc, "start": shot_span[s][0],
                      "end": shot_span[s][1], "card": False, "promoted": False,
                      "index": IDX, "source": SRC} for s, sc in candidates]
            out.append({"phrase": ph, "found": True, "discriminative": True,
                        "margin": 0.1, "candidates": cands})
        return out, index_data

    def fake_cut(source, start, duration_, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, **kw):
        return gate(int(Path(clip).stem.rsplit("_s", 1)[1]))

    def fake_hold_frame(clip, seconds, dest, used=None):
        Path(dest).write_bytes(b"")
        return True

    ra.match, ra.cut, ra.usable, ra.hold_frame = (
        fake_match, fake_cut, fake_usable, fake_hold_frame)
    ra.audio_duration = lambda path: duration
    ra.leading_silence = lambda path: 0.0
    ra.load_words = lambda path: words
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(ra, k, v)


def _run(anchors, candidates, gate=lambda s: (True, []), extra_args=(),
         n_shots=6, shot_seconds=3.0, n_words=14, duration=8.0):
    words = [{"word": "w", "start": 0.4 + 0.5 * i, "end": 0.8 + 0.5 * i}
             for i in range(n_words)]
    index_data = {IDX: _index(n_shots, shot_seconds)}
    with tempfile.TemporaryDirectory() as tmp, \
            _patched(candidates, gate, index_data, words, duration):
        tmp = Path(tmp)
        spec = tmp / "anchors.json"
        spec.write_text(json.dumps({"script_id": "t", "anchors": anchors}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(spec), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", str(MIN_SCORE),
                *extra_args]
        err = io.StringIO()
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                ra.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text()), err.getvalue()


def anchor(word_index, phrase, side=None):
    a = {"word_index": word_index, "phrase": phrase, "emphasis_words": []}
    if side:
        a["side"] = side
    return a


def shots_of(story):
    return [b["shot"] for b in story["blocks"] if b.get("shot")]


def test_the_second_anchor_takes_the_next_candidate_rather_than_the_used_one():
    """Two anchors with the same ranked pool. The first takes the best shot;
    the second must not, and falls through to a candidate further down - which
    is what the rule costs and all it costs when the pool has depth. (One
    stretch outlasts a single 3s shot, so `even` covers its tail with the next
    candidate again - three distinct pictures, no repeat. Which stretch that is
    moved with CF-0276: block 0 now opens at 0.00s in the layout instead of
    being dragged there afterwards, so the first anchor's stretch is the long
    one and the second anchor lands on pool:3. The claim here is about the
    sample the first anchor spent, not about which rank answers second.)"""
    story, err = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                      [(1, 0.31), (2, 0.25), (3, 0.24)])
    assert shots_of(story) == ["pool:1", "pool:2", "pool:3"], story["blocks"]
    second = [b for b in story["blocks"] if b["word_range"] == [7, 7]]
    assert second[0]["shot"] != "pool:1", (
        "the second anchor opened on the sample the first one spent")
    turned_away = [r for r in story["rejected_candidates"]
                   if "one sample, one use" in r["reason"]]
    # Everything the rule turned away was already on screen, and nothing else
    # was. Stated that way rather than as a literal list: how many samples the
    # earlier anchors have spent by then is a property of the layout, and
    # CF-0276 changed it (block 0 opens at 0.00s, so the first anchor's
    # stretch takes two pictures here); what may never change is that a
    # rejection is always about a sample this video has shown.
    spent = {s for s in shots_of(story)}
    assert turned_away, story["rejected_candidates"]
    assert all(f"pool:{r['shot']}" in spent for r in turned_away), \
        story["rejected_candidates"]
    assert not [u for u in story["unresolved_anchors"]
                if "already used" in u["reason"]], story["unresolved_anchors"]


def test_with_no_second_candidate_the_anchor_is_unresolved_not_a_repeat():
    """The other half of the sentence: a pool of one. The second anchor gets
    no picture at all, and the report says the cap is why - the shortage is
    visible instead of drained into a second showing."""
    story, err = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                      [(1, 0.31)])
    assert shots_of(story) == ["pool:1"], story["blocks"]
    reasons = [u["reason"] for u in story["unresolved_anchors"]]
    assert any(r.startswith("every remaining candidate was already used")
               and "one sample, one use" in r for r in reasons), reasons
    assert any("one sample, one use" in r["reason"]
               for r in story["rejected_candidates"]), story["rejected_candidates"]
    assert "UNRESOLVED: the lake - every remaining candidate was already used" in err, err


def test_the_measurement_cap_reproduces_the_repeat_it_is_there_to_measure():
    """The control arm of CF-0121's before/after has to actually differ, or
    the measured growth in `unresolved_anchors` is measuring nothing. Same
    inputs as the test above, at the cap those batches were cut under."""
    story, err = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                      [(1, 0.31)], extra_args=["--max-shot-reuse", "3"])
    assert shots_of(story) == ["pool:1", "pool:1"], (
        "at the old cap the same sample is shown twice - if this no longer "
        "happens, the before/after table compares two identical runs")
    assert not [u for u in story["unresolved_anchors"]
                if "already used" in u["reason"]], story["unresolved_anchors"]


def test_the_even_fill_never_repeats_inside_one_anchors_stretch():
    """CF-0028: on `even` one anchor's stretch is covered by as many cuts as it
    takes. Every one of them is a picture the viewer sees, so the cap counts
    them - a stretch cannot be papered over by playing one shot twice."""
    story, err = _run([anchor(1, "the long hall")],
                      [(s, 0.4 - 0.01 * s) for s in range(1, 6)],
                      shot_seconds=1.2, n_words=14, duration=8.0)
    shots = shots_of(story)
    assert len(shots) >= 3, f"the stretch was covered by too few cuts to test: {shots}"
    assert len(set(shots)) == len(shots), f"a sample is on screen twice: {shots}"


def test_the_openings_two_sides_never_share_a_shot_with_each_other_or_the_body():
    """CF-0075 cut the `side_by_side` opening to distinct shots per side; the
    ledger extends that to the whole video. What the opening spends, the body
    may not show again - a comparison of a thing with itself states no axis,
    and the frame that just left the screen is not a new picture."""
    story, err = _run([anchor(1, "the old house", side="a"),
                       anchor(4, "the new house", side="b"),
                       anchor(8, "the street", side="a"),
                       anchor(11, "the yard", side="b")],
                      [(s, 0.4 - 0.01 * s) for s in range(1, 8)],
                      extra_args=["--opening", "side_by_side"],
                      n_shots=8, shot_seconds=1.6, n_words=16, duration=9.0)
    opening = story["blocks"][0]
    assert opening["asset_kind"] == "split", story["blocks"][0]
    opening_shots = [c["shot"] for h in opening["split"] for c in h["cuts"]]
    assert len(set(opening_shots)) == len(set(
        c["shot"] for h in opening["split"] for c in h["cuts"] if not c["held_frame"])), \
        opening_shots
    distinct_opening = {f"pool:{s}" for s in opening_shots}
    assert len(distinct_opening) >= 2, f"the opening built on one shot: {opening_shots}"
    body = shots_of(story)
    assert len(set(body)) == len(body), f"the body shows a sample twice: {body}"
    assert not (distinct_opening & set(body)), (
        f"the body re-shows an opening sample: {distinct_opening & set(body)}")


def test_no_storyboard_this_resolver_writes_ever_shows_a_sample_twice():
    """The property everything above adds up to, on a run with more anchors
    than distinct shots - the case where the old sink used to open. Blocks
    without a picture are the price, and they are typographic blocks
    (CF-0085), not repeats.

    On `even`, which this run is: CF-0137 opened exactly one deliberate,
    recorded exception to the property, and it is only reachable on an
    ordered rhythm - see
    test_one_emergency_repeat_is_allowed_on_an_ordered_rhythm_and_only_one
    below. The rule for every other block is unchanged."""
    story, err = _run([anchor(1 + 3 * i, f"beat {i}") for i in range(5)],
                      [(s, 0.4 - 0.01 * s) for s in range(1, 4)],
                      n_shots=4, n_words=20, duration=11.0)
    shots = shots_of(story)
    assert shots, story["blocks"]
    assert len(set(shots)) == len(shots), f"a sample is on screen twice: {shots}"
    assert len(shots) <= 3, f"more pictures than distinct samples offered: {shots}"


# --------------------------------------------------------------------------
# CF-0137: the one exception, and the fact that it is one
# --------------------------------------------------------------------------

def test_one_emergency_repeat_is_allowed_on_an_ordered_rhythm_and_only_one():
    """CF-0123 refused the assetless rung, so a block an ordered rhythm cannot
    fill climbs one rung first: a single repetition of a shot already on
    screen. The point of this test is the *second* one - the next block that
    would want a repeat gets none, and falls to the assetless rung under it
    (which build_render_plan.py then refuses, unless the channel allows it -
    tests/test_assetless_rung_gate.py).

    Four staccato blocks, two distinct shots. Blocks 0 and 1 take one each;
    block 2 has nothing new and spends the video's one repeat; block 3 asks
    and is refused."""
    story, err = _run([anchor(1 + 3 * i, f"beat {i}") for i in range(4)],
                      [(1, 0.40), (2, 0.39)],
                      n_shots=3, n_words=16, duration=12.0,
                      extra_args=["--rhythm", "staccato"])
    reused = [b for b in story["blocks"] if b.get("emergency_reuse")]
    assert len(reused) == 1, (
        f"expected exactly one emergency repeat, got {len(reused)}: "
        f"{[b.get('shot') for b in reused]}")
    rec = reused[0]["emergency_reuse"]
    assert rec["shot"] == reused[0]["shot"], rec
    assert rec["reason"], "the repeat has to say what shortage it covered"

    # It is a repeat of something already on screen, and not of the block
    # right before it (CF-0074 / CF-0034: a repeated adjacent pair).
    i = story["blocks"].index(reused[0])
    assert reused[0]["shot"] in [b.get("shot") for b in story["blocks"][:i]], story["blocks"]
    assert story["blocks"][i - 1].get("shot") != reused[0]["shot"], (
        "the repeat landed next to its own first use")

    # And the video's budget really is spent: some later block went to the
    # assetless rung rather than getting a second repeat.
    later = story["blocks"][i + 1:]
    assert any(b.get("asset_kind") == "typographic" for b in later), (
        f"a second block was patched instead of refused: {later}")
    assert "EMERGENCY REPEAT" in err, err[-800:]


def test_a_swing_block_is_refused_a_repeat_rather_than_given_one():
    """CF-0074 does not unwind inside a swing: with `alternate` ordered and
    nothing new on the side, the block goes to the assetless rung (and from
    there to the planner's refusal), never to a repeated shot."""
    story, err = _run([anchor(1 + 3 * i, f"beat {i}", side="ab"[i % 2])
                       for i in range(4)],
                      [(1, 0.40), (2, 0.39)],
                      n_shots=3, n_words=16, duration=12.0,
                      extra_args=["--rhythm", "alternate"])
    swings = [b for b in story["blocks"] if b.get("rhythm_role") == "swing"]
    assert swings, "the fixture stopped producing swing blocks"
    assert not any(b.get("emergency_reuse") for b in swings), (
        f"a swing block was filled with a repeat: {swings}")
    assert len(shots_of(story)) == len(set(shots_of(story))), (
        f"a sample is on screen twice inside an alternation: {shots_of(story)}")


# --------------------------------------------------------------------------
# clip -> still degradation is not a fourth chooser
# --------------------------------------------------------------------------

def test_clip_to_still_degradation_lifts_the_frame_from_its_own_block():
    """`--degrade-block N:still` sounds like it could re-show a sample, and it
    cannot: the frame it delivers is probed out of *that block's own* asset and
    replaces it, so the sample goes from moving to motionless in the one place
    it was already going to be. Pinned on the source rather than by rendering,
    because what makes it safe is that this code has no candidate pool to pick
    another block's shot from - and because the rung below (typographic) is
    what a block with nothing left of its own drops to.

    Together with the storyboard property above - no two blocks carry the same
    sample - this is why degradation cannot produce a second showing.
    """
    src = (SCRIPTS / "build_render_plan.py").read_text()
    block = re.search(r'frame_name = \(f"_degraded_still_.*?'
                      r'asset\["src"\] = probe_path', src, re.S)
    assert block, ("the degraded still no longer replaces its own block's clip "
                   "- if the chain now sources a still from somewhere else, "
                   "CF-0121 needs the ledger here too")
    assert 'probe_frame(sb["asset"]' in block.group(0), (
        "the degraded still is no longer lifted from the block's own asset: "
        + block.group(0))


# --------------------------------------------------------------------------
# one shared check
# --------------------------------------------------------------------------

STRINGS = re.compile(r"""(['"]).*?\1""", re.S)


def _code_lines_reading_the_cap():
    """Every line of every script that reads MAX_SHOT_REUSE as code - comments
    and string literals (help text, reasons) removed first."""
    found = []
    for path in sorted(SCRIPTS.glob("*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            code = STRINGS.sub("", line.split("#")[0])
            if "MAX_SHOT_REUSE" in code:
                found.append((path.name, n, code.strip()))
    return found


def test_the_ledger_is_the_only_place_the_cap_is_read():
    """One shared check, so a new shot-choice path cannot bypass the rule.

    CF-0120's multi-shot swing block is the next caller due to arrive, and the
    cheapest thing for it to write is its own `>= MAX_SHOT_REUSE`. There is
    exactly one comparison in the codebase and it is inside ShotLedger; every
    other file may only import the name (resolve_anchors.py re-exports it,
    because callers have read it off that module for two versions).
    """
    lines = _code_lines_reading_the_cap()
    by_file = {}
    for name, n, code in lines:
        by_file.setdefault(name, []).append(code)
    assert set(by_file) == {"rhythm.py", "resolve_anchors.py"}, by_file
    assert by_file["rhythm.py"] == [
        "MAX_SHOT_REUSE = 1",
        "self.max_uses = MAX_SHOT_REUSE if max_uses is None else int(max_uses)",
    ], by_file["rhythm.py"]
    assert len(by_file["resolve_anchors.py"]) == 1, by_file["resolve_anchors.py"]
    assert by_file["resolve_anchors.py"][0].startswith("from rhythm import ("), \
        by_file["resolve_anchors.py"]


def test_every_shot_choice_path_asks_the_ledger():
    """The other side of the same pin: the two places that choose a sample -
    the block fill loop and the `side_by_side` opening - both ask, and neither
    keeps a private set of its own."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    assert src.count("ledger.blocked(") == 2, (
        "a shot-choice path stopped asking the ledger, or a new one arrived "
        "without asking")
    assert src.count("ledger.take(") == 4, (
        "every accepted sample is taken exactly once per path: the opening's "
        "own cuts, the delivered opening on the video's ledger, the fill loop - "
        "plus CF-0537's restore, which re-takes only what its give_back() gave")
    assert src.count("ledger.give_back(") == 1, (
        "CF-0537: one place gives a take back (soft cuts traded for a sharp "
        "shot under the floor), and it is the one place that restores it")
    assert "shot_uses" not in src, "the fill loop kept its own count again"
    assert re.search(r"halves, taken = ", src) is None, \
        "build_split_opening kept its own `taken` set again"


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
