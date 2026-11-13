#!/usr/bin/env python3
"""CF-0140: the coverage preflight judges a pool exactly as the resolver does.

The preflight (`scripts/anchor_coverage.py`) exists so that "there is nothing
to show here" is discovered before TTS instead of after it. That is only worth
anything if its answer is the answer `resolve_anchors.py` will give an hour
later: a preflight that is more lenient passes a script straight into the hole
it exists to prevent, and one that is stricter throws away scripts that would
have worked. So this file tests the *sameness*, not the preflight on its own.

Two halves, and they are different kinds of proof:

  * one gate, three callers. The mark / span / cached-usability chain lives in
    `resolve_anchors.precut_refusal()` and nowhere else; `fill()`,
    `cut_usable()` and the preflight all ask it. Pinned in the source (a
    second copy would be a second rule) and behaviourally: replacing that one
    function moves the resolver's answer and the preflight's answer together,
    which is what "cannot diverge" actually means.
  * the same verdict on the same pool. A real `resolve_anchors.main()` run,
    with the matcher, the cutter and the clip gate replaced by doubles, next
    to `anchor_coverage.assess()` on the same matcher output. The resolver's
    own `unresolved_anchors` records and the preflight's per-anchor verdicts
    have to agree, anchor for anchor, across the pool shapes that make a hole.

The clip gate double always passes, deliberately: the real `usable()` runs on
a cut clip and needs ffmpeg and the source file, so it is the one check the
preflight cannot make and cannot be tested for agreement on. `anchor_coverage`
says so in its docstring - `absent` is certain, `covered` is necessary and not
sufficient - and these runs are about everything that is decidable from an
index alone.

No pytest - plain asserts, run directly. No footage, no CLIP, no ffmpeg.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import anchor_coverage  # noqa: E402
import cache_fingerprint  # noqa: E402
import resolve_anchors  # noqa: E402

MIN_SCORE = 0.22
SRC = "/nowhere/pool.mp4"
IDX = "/nowhere/pool.shots.json"

# Cached vision numbers that clear every check comfortably - a shot the
# pre-filter has no opinion about.
FINE = {"roi_source": "face", "roi_coverage": 0.90, "black_fraction": 0.0,
        "mean_luma": 120.0, "short_side": 1080, "width": 1080, "height": 1920}
# ... and the same shot measured black. `probably_unusable()` condemns this
# one without cutting it, which is the pre-cut refusal the preflight can see.
DOOMED = {**FINE, "black_fraction": 0.99, "mean_luma": 2.0}


def _cached(numbers):
    return {"measured_by": cache_fingerprint.usability_fingerprint(), **numbers}


def _pool(specs):
    """`specs`: {shot number: (seconds, cached numbers or None)}."""
    shots = []
    for n, (seconds, numbers) in sorted(specs.items()):
        s = {"index": n, "start": n * 30.0, "end": n * 30.0 + seconds}
        if numbers is not None:
            s["usable_cached"] = _cached(numbers)
        shots.append(s)
    return {IDX: {"source": SRC, "shots": shots}}


def _candidates(index_data, offers):
    """`offers`: [(shot number, score, extra fields)] -> matcher candidates."""
    spans = {s["index"]: (s["start"], s["end"]) for s in index_data[IDX]["shots"]}
    return [{"shot": n, "score": sc, "start": spans[n][0], "end": spans[n][1],
             "card": False, "promoted": False, "index": IDX, "source": SRC, **extra}
            for n, sc, extra in offers]


def _matches(index_data, per_anchor):
    """One matcher result per anchor - the shape `resolve_anchors.match()`
    hands back, built by its own `order_candidates()` so the order the
    preflight and the resolver walk is the same order."""
    out = []
    for phrase, offers in per_anchor:
        cands = resolve_anchors.order_candidates(_candidates(index_data, offers), 0)
        out.append({"phrase": phrase,
                    "found": bool(cands) and max(c["score"] for c in cands) >= MIN_SCORE,
                    "discriminative": True, "margin": 0.1, "candidates": cands})
    return out


# --------------------------------------------------------------------------
# one gate, three callers
# --------------------------------------------------------------------------

def test_the_pre_cut_gate_is_written_once_and_the_preflight_owns_no_copy():
    """A second copy of the mark / span / usability chain is a second rule,
    and a second rule is exactly the failure this task is about. So: one
    definition in resolve_anchors.py, both of its cut paths asking it, and
    nothing gate-shaped in anchor_coverage.py at all."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    assert src.count("def precut_refusal(") == 1, "a second copy of the pre-cut gate"
    assert "precut_refusal(" in src.split("def fill(pool")[1], "fill() bypasses the gate"
    assert "precut_refusal(" in src.split("def cut_usable(")[1].split("\ndef ")[0], \
        "cut_usable() bypasses the gate"

    pre = (SCRIPTS / "anchor_coverage.py").read_text()
    body = pre.split('"""', 2)[2]  # past the module docstring, which names them
    for own in ("probably_unusable(", "cut_start(", "cached_verdict(", "MIN_CUT_SECONDS"):
        assert own not in body, f"anchor_coverage.py screens with its own {own}"
    assert "resolve_anchors.precut_refusal(" in body
    assert "resolve_anchors.gate_verdict(" in body
    assert "resolve_anchors.screen_pool(" in body, \
        "CF-0290: both floors are the resolver's one screen, not a copy here"
    assert "resolve_anchors.candidate_supply(" in body, \
        "the weak/absent split is the resolver's own supply vocabulary"


def test_replacing_the_one_gate_moves_both_answers_together():
    """The behavioural half of the same claim. Refuse everything at the one
    gate: the preflight must call every anchor absent *and* the resolver must
    end up with no picture. Neither can be made to disagree with the other by
    changing one place, because there is only one place."""
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [("a lake house", [(1, 0.31, {})])])

    assert anchor_coverage.assess(matches, index_data)["anchors"][0]["verdict"] == "covered"
    story, _ = _run_main(matches, index_data, lambda s: (True, []))
    assert story["blocks"] and story["blocks"][0]["shot"] == "pool:1"

    saved = resolve_anchors.precut_refusal
    resolve_anchors.precut_refusal = lambda *a, **kw: (
        None, None, None, {"cause": resolve_anchors.CAUSE_FOOTAGE_UNUSABLE,
                           "record": {"score": 0.0, "reason": "refused by the test"},
                           "log": None})
    try:
        rec = anchor_coverage.assess(matches, index_data)
        story, _ = _run_main(matches, index_data, lambda s: (True, []))
    finally:
        resolve_anchors.precut_refusal = saved

    assert rec["anchors"][0]["verdict"] == "absent"
    assert "refused by the test" in rec["anchors"][0]["detail"]
    assert story["blocks"] == [], "the resolver did not go through the same gate"


# --------------------------------------------------------------------------
# the same verdict on the same pool
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _patched(matches, index_data, gate):
    saved = {k: getattr(resolve_anchors, k) for k in
             ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")}

    def fake_match(indexes, phrases, min_score, top, python):
        return matches, index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, **kw):
        return gate(int(Path(clip).stem.rsplit("_s", 1)[1]))

    resolve_anchors.match = fake_match
    resolve_anchors.cut = fake_cut
    resolve_anchors.usable = fake_usable
    resolve_anchors.audio_duration = lambda path: 24.0
    resolve_anchors.leading_silence = lambda path: 0.0
    resolve_anchors.load_words = lambda path: [
        {"word": "w", "start": 0.4 + 1.0 * i, "end": 0.9 + 1.0 * i} for i in range(24)]
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(resolve_anchors, k, v)


def _run_main(matches, index_data, gate):
    with tempfile.TemporaryDirectory() as tmp, _patched(matches, index_data, gate):
        tmp = Path(tmp)
        anchors = tmp / "anchors.json"
        anchors.write_text(json.dumps({"script_id": "t", "anchors": [
            {"word_index": 1 + 4 * i, "phrase": m["phrase"], "emphasis_words": []}
            for i, m in enumerate(matches)]}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(anchors), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", str(MIN_SCORE)]
        err = io.StringIO()
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                resolve_anchors.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text()), err.getvalue()


def _resolver_verdicts(story):
    """What the resolver's own post-gate records say, phrase by phrase, in the
    preflight's three words. A phrase with no `found_after_gate` record is one
    `gate_verdict()` had nothing to say about - a covered anchor."""
    verdicts = {}
    for u in story["unresolved_anchors"]:
        if u.get("reason") == "no shot in any index":
            # The one hole the resolver settles before `gate_verdict()` is
            # reached at all: with no candidate there is nothing to take a
            # post-gate verdict on, so the record carries the resolver's own
            # wording and no `found_after_gate`. Still an absent anchor, and
            # the preflight has to call it that - see `screen_anchor()`, which
            # writes the same sentence for the same case.
            verdicts.setdefault(u["phrase"], "absent")
            continue
        if "found_after_gate" not in u:
            continue  # CF-0009's margin note, CF-0124's carry - not this verdict
        # CF-0290: the resolver no longer fills a block under the floor, so
        # "weak" is no longer a filled block with a low score - it is an anchor
        # whose pool was ranked and had nothing on topic. The resolver says
        # exactly that in `anchor_supply` (`pool_offered_off_topic`), which is
        # the same vocabulary `screen_anchor()` now splits weak from absent by,
        # so that is what this reads.
        verdicts[u["phrase"]] = "absent"
    for a in story.get("anchor_supply", []):
        supply = a.get("supply")
        if supply and supply["code"] == "pool_offered_off_topic":
            verdicts[a["phrase"]] = "weak"
    return verdicts


def _agree(per_anchor, pool, expected):
    """Run both over one pool and assert they say the same thing."""
    index_data = _pool(pool)
    matches = _matches(index_data, per_anchor)
    rec = anchor_coverage.assess(matches, index_data)
    story, _ = _run_main(matches, index_data, lambda s: (True, []))

    pre = {a["phrase"]: a["verdict"] for a in rec["anchors"]}
    resolved = _resolver_verdicts(story)
    for phrase, verdict in pre.items():
        theirs = resolved.get(phrase, "covered")
        assert verdict == theirs, \
            f"{phrase!r}: preflight says {verdict}, the resolver says {theirs}"
    assert pre == expected, pre
    return rec, story


def test_a_healthy_pool_is_covered_on_both_sides():
    _agree([("a lake house", [(1, 0.31, {})])],
           {1: (30.0, FINE)}, {"a lake house": "covered"})


def test_nothing_in_the_pool_is_absent_on_both_sides_and_is_no_footage():
    rec, story = _agree([("a lake house", [])], {1: (30.0, FINE)},
                        {"a lake house": "absent"})
    a = rec["anchors"][0]
    assert a["cause"] == "no_footage", a
    assert a["detail"] == "no shot in any index", a["detail"]
    assert story["blocks"] == [] or not story["blocks"][0].get("shot")


def test_every_candidate_condemned_by_cached_usability_is_absent_on_both_sides():
    """The pre-filter (CF-0029) is the gate that decides most real holes, and
    it is decidable from the index alone - which is what makes a preflight
    possible at all."""
    rec, _ = _agree([("a lake house", [(1, 0.31, {}), (2, 0.28, {})])],
                    {1: (30.0, DOOMED), 2: (30.0, DOOMED)},
                    {"a lake house": "absent"})
    a = rec["anchors"][0]
    assert a["cause"] == "footage_unusable", a
    assert len(a["refusals"]) == 2 and a["survivors"] == 0
    assert all("pre-filtered by cached shot usability" in r["reason"]
               for r in a["refusals"]), a["refusals"]


def test_a_shot_too_short_to_cut_is_absent_on_both_sides():
    rec, _ = _agree([("a lake house", [(1, 0.31, {})])], {1: (0.4, FINE)},
                    {"a lake house": "absent"})
    assert rec["anchors"][0]["cause"] == "footage_unusable"
    assert "too short to read" in rec["anchors"][0]["refusals"][0]["reason"]


def test_a_mark_outside_its_shot_is_absent_on_both_sides():
    """CF-0106's refusal, seen from the preflight."""
    rec, _ = _agree([("a lake house", [(1, 0.31, {"moment_at": 999.0})])],
                    {1: (30.0, FINE)}, {"a lake house": "absent"})
    assert rec["anchors"][0]["cause"] == "footage_unusable"
    assert "moment_at rejected" in rec["anchors"][0]["detail"]


def test_a_sub_threshold_survivor_is_weak_on_both_sides():
    """A hole since CF-0290: the resolver refuses the frame in front of
    `fill()` instead of using it anyway, so the anchor gets no picture on
    either side. It keeps its own verdict name because the remedy is its own -
    footage that depicts the phrase - and the preflight now refuses the
    script for it."""
    rec, _ = _agree([("a lake house", [(1, 0.15, {})])], {1: (30.0, FINE)},
                    {"a lake house": "weak"})
    a = rec["anchors"][0]
    assert a["covered"] is False and a["cause"] == "no_footage", a
    assert a["best_score"] is None and a["best_offered_score"] == 0.15, a
    assert anchor_coverage.assess(_matches(_pool({1: (30.0, FINE)}),
                                           [("a lake house", [(1, 0.15, {})])]),
                                  _pool({1: (30.0, FINE)}))["passed"] is False


def test_a_mixed_script_agrees_anchor_for_anchor():
    """Four anchors, one of each kind, in one run - the shape the Content
    Researcher's validator will actually hand over."""
    rec, _ = _agree(
        [("a lake house", [(1, 0.31, {})]),
         ("an idea", []),
         ("a dark room", [(2, 0.30, {})]),
         ("something vague", [(3, 0.16, {})])],
        {1: (30.0, FINE), 2: (30.0, DOOMED), 3: (30.0, FINE)},
        {"a lake house": "covered", "an idea": "absent",
         "a dark room": "absent", "something vague": "weak"})
    assert rec["absent"] == [1, 2] and rec["weak"] == [3]
    assert rec["covered_count"] == 1 and rec["anchor_count"] == 4
    # CF-0290: the weak anchor is a refusal of its own now, and both causes
    # are named rather than the first one standing for the script.
    assert rec["passed"] is False
    assert rec["refused_because"] == ["absent_anchors", "weak_anchors"], \
        rec["refused_because"]


# --------------------------------------------------------------------------
# the script-wide part: one sample, one use
# --------------------------------------------------------------------------

def test_two_anchors_on_one_sample_are_short_by_one_and_the_repeat_absorbs_it():
    """CF-0121's cap is a fact about a video, not about a candidate, so it is
    reported script-wide rather than blamed on an anchor. One spare hole is
    what CF-0137's single emergency repeat exists for, so it does not refuse."""
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [("first", [(1, 0.31, {})]),
                                    ("second", [(1, 0.31, {})])])
    rec = anchor_coverage.assess(matches, index_data)
    assert [a["verdict"] for a in rec["anchors"]] == ["covered", "covered"]
    c = rec["contention"]
    assert (c["anchors"], c["distinct_samples"], c["matched"]) == (2, 1, 1)
    assert c["short_by"] == 1 and c["short_after_repeat"] == 0
    assert rec["passed"] is True


def test_three_anchors_on_one_sample_are_refused_for_contention():
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [(p, [(1, 0.31, {})]) for p in ("a", "b", "c")])
    rec = anchor_coverage.assess(matches, index_data)
    assert rec["refused_because"] == ["sample_contention"] and rec["passed"] is False
    assert rec["contention"]["short_after_repeat"] == 1
    assert rec["absent"] == [], "contention is not blamed on any one anchor"


def test_distinct_samples_for_everyone_is_no_contention():
    index_data = _pool({1: (30.0, FINE), 2: (30.0, FINE), 3: (30.0, FINE)})
    matches = _matches(index_data, [("a", [(1, 0.31, {}), (2, 0.30, {})]),
                                    ("b", [(1, 0.31, {}), (3, 0.29, {})]),
                                    ("c", [(1, 0.31, {})])])
    c = anchor_coverage.assess(matches, index_data)["contention"]
    # The greedy read of this is 1 short (everyone wants shot 1); the matching
    # is not greedy, and there really is an assignment that serves all three.
    assert c["matched"] == 3 and c["short_by"] == 0, c


def test_absent_anchors_are_not_counted_twice_in_the_contention():
    """An anchor with nothing behind it is already a hole; letting it into the
    matching would report it as a second, contention-shaped hole as well."""
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [("a", [(1, 0.31, {})]), ("b", [])])
    rec = anchor_coverage.assess(matches, index_data)
    assert rec["contention"]["anchors"] == 1 and rec["contention"]["short_by"] == 0
    assert rec["refused_because"] == ["absent_anchors"]


# --------------------------------------------------------------------------
# the interface the Content Researcher's validator uses
# --------------------------------------------------------------------------

def test_the_three_input_shapes_all_load():
    assert anchor_coverage.load_anchors(
        {"anchors": [{"phrase": "a lake house", "word_index": 3}]}) == ["a lake house"]
    assert anchor_coverage.load_anchors({"phrases": ["a", "b"]}) == ["a", "b"]
    assert anchor_coverage.load_anchors(["a", {"phrase": " b "}]) == ["a", "b"]


def test_a_broken_input_says_what_is_wrong_instead_of_guessing():
    for bad, marker in (({}, "no `anchors`"), ({"anchors": 3}, "has to be a list"),
                        ([], "no anchors"), ([{"side": "a"}], "no `phrase`"),
                        ("nope", "expected a JSON object")):
        try:
            anchor_coverage.load_anchors(bad)
        except ValueError as e:
            assert marker in str(e), (bad, str(e))
        else:
            raise AssertionError(f"{bad!r} was accepted")


def test_a_weak_anchor_is_refused_with_or_without_strict():
    """CF-0290 turned this test around. It used to assert that the default
    *passed* a weak anchor and only `--strict` refused it, on the reading that
    "the resolver uses it anyway and records it as unresolved". The resolver
    does not use it any more, so passing the script here would send it through
    the TTS to a block with no picture. The verdict keeps its own name - the
    remedy for `weak` is footage that depicts the phrase, not footage that
    survives the gates - and `--strict` has nothing left to tighten."""
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [("a lake house", [(1, 0.15, {})])])
    for strict in (False, True):
        rec = anchor_coverage.assess(matches, index_data, strict=strict)
        assert rec["passed"] is False, rec["note"]
        assert rec["refused_because"] == ["weak_anchors"], rec["refused_because"]
        assert rec["anchors"][0]["verdict"] == "weak", rec["anchors"][0]
        assert rec["anchors"][0]["covered"] is False, rec["anchors"][0]
        assert "0.22 similarity floor" in rec["anchors"][0]["refusals"][0]["reason"]


def test_the_score_floor_is_the_resolvers_own_rule_and_reads_as_no_footage():
    index_data = _pool({1: (30.0, FINE)})
    matches = _matches(index_data, [("a lake house", [(1, 0.31, {})])])
    rec = anchor_coverage.assess(matches, index_data, score_floor=0.40)
    a = rec["anchors"][0]
    assert a["verdict"] == "absent" and a["cause"] == "no_footage", a
    assert "under --score-floor 0.4" in a["refusals"][0]["reason"]
    assert rec["score_floor"] == 0.40


def test_the_report_names_itself_and_carries_the_knobs_it_judged_under():
    index_data = _pool({1: (30.0, FINE)})
    rec = anchor_coverage.assess(_matches(index_data, [("a", [(1, 0.31, {})])]),
                                 index_data, indexes=[IDX])
    assert rec["kind"] == anchor_coverage.KIND
    assert rec["min_score"] == resolve_anchors.DEFAULT_MIN_SCORE
    assert rec["indexes"] == [IDX] and rec["pool"] == {"sources": 1, "shots": 1}
    assert set(a["verdict"] for a in rec["anchors"]) <= set(anchor_coverage.VERDICTS)
    assert json.loads(json.dumps(rec)) == rec, "the report has to be JSON"


def test_the_preflight_and_the_resolver_share_the_matcher_knobs():
    """A preflight run against a different `--top` screens a different pool,
    so the defaults are one constant read by both, not two literals."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    assert 'default=DEFAULT_TOP' in src and 'default=DEFAULT_MIN_SCORE' in src
    assert anchor_coverage.DEFAULT_TOP is resolve_anchors.DEFAULT_TOP
    assert anchor_coverage.DEFAULT_MIN_SCORE is resolve_anchors.DEFAULT_MIN_SCORE


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
