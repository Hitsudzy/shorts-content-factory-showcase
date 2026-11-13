#!/usr/bin/env python3
"""CF-0150: the third fact - whether the pool ever offered this anchor a
picture - from the resolver to `plan.assetless-rung.json`.

After CF-0139 fixed the classifier, all 15 unique shortage records of batch
`2026-09-03T2037Z` came out `footage_unusable` - "a frame exists and cannot
be taken". One of them was not that. Clooney, block 9: the only water-taxi
candidate the pool could rank scored 0.116 against a 0.22 floor, and the
prose said "nothing in the available footage actually depicts this". Its
`degraded_from` was `clip`, exactly like the QC degradations beside it, so
nothing machine-readable told the two apart and the shopping list would have
said "we have the frame" about a frame nobody has.

The fact is taken where the candidates are actually enumerated
(`resolve_anchors.candidate_supply()`), rides the storyboard block, is
copied onto the plan block by `build_render_plan.py`, and lands on
`assetless_rung.anchor_records()`'s anchors. Three codes, in the shape
CF-0193 gave `meme_layer.beat_failure()`: a diagnosis with the evidence to
check it by, and `None` when there is nothing to diagnose.

Pure checks on the helper, real `main()` runs with the matcher/cutter/gate
replaced by doubles, and one end-to-end run of the real
`build_render_plan.py` down to the refusal record. No footage, no CLIP, no
ffmpeg. No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assetless_rung  # noqa: E402
import repo_paths  # noqa: E402
import resolve_anchors  # noqa: E402

MIN_SCORE = 0.22
SRC = "/nowhere/pool.mp4"
IDX = "/nowhere/pool.shots.json"

NOTHING = resolve_anchors.POOL_OFFERED_NOTHING
OFF_TOPIC = resolve_anchors.POOL_OFFERED_OFF_TOPIC
REFUSED = resolve_anchors.POOL_OFFERED_REFUSED


def cand(shot, score):
    return {"shot": shot, "score": score, "source": SRC, "index": IDX}


def rej(shot, score, reason="failed usable() on the cut clip: dark"):
    return {"phrase": "p", "shot": shot, "score": score, "reason": reason}


def supply(candidates, used=(), rejected=(), phrase="a wooden water taxi"):
    return resolve_anchors.candidate_supply(phrase, list(candidates), list(used),
                                            list(rejected), MIN_SCORE)


# --------------------------------------------------------------------------
# candidate_supply(): pure
# --------------------------------------------------------------------------

def test_an_empty_pool_is_its_own_code_and_not_a_refusal():
    s = supply([])
    assert s["code"] == NOTHING, s
    assert s["offered"] == 0 and s["on_topic_offered"] == 0
    assert s["best_offered_score"] is None and s["nearest"] is None
    assert s["searched"].startswith("a wooden water taxi"), s


def test_the_clooney_block_9_shape_is_off_topic_even_though_a_frame_was_used():
    """The single water-taxi offer scores 0.116, under the 0.22 floor, and a
    0.110 frame was used anyway. The block has a picture; the pool has
    nothing that depicts the anchor. Buying material is the remedy."""
    s = supply([cand(2, 0.110), cand(5, 0.116)], used=[{"shot": 2, "score": 0.110}])
    assert s["code"] == OFF_TOPIC, s
    assert s["on_topic_offered"] == 0 and s["offered"] == 2
    assert s["best_offered_score"] == 0.116 and s["best_used_score"] == 0.11
    assert s["used"] == 1, "a filled block can still be a pool that offered nothing on topic"
    assert s["nearest"] == {"shot": "pool:5", "score": 0.116, "source": SRC}, s["nearest"]
    assert s["min_score"] == MIN_SCORE


def test_good_candidates_taken_away_by_the_gates_are_a_different_code():
    """The QC neighbours: the frames exist, score over the floor, and every
    one of them was refused. Nothing to buy - this is ours to fix."""
    s = supply([cand(38, 0.31), cand(24, 0.28)],
               rejected=[rej(38, 0.31), rej(24, 0.28, "pre-filtered by cached usability")])
    assert s["code"] == REFUSED, s
    assert s["on_topic_offered"] == 2 and s["used"] == 0 and s["refused"] == 2
    assert s["best_offered_score"] == 0.31 and s["best_used_score"] is None
    assert s["nearest"]["shot"] == "pool:38"


def test_a_delivered_anchor_has_no_diagnosis_at_all():
    assert supply([cand(1, 0.31)], used=[{"shot": 1, "score": 0.31}]) is None
    assert supply([cand(1, 0.31), cand(2, 0.15)],
                  used=[{"shot": 1, "score": 0.27}], rejected=[rej(9, 0.4)]) is None, \
        "a refusal ahead of a usable on-topic frame is not a supply problem"


def test_a_weak_survivor_behind_refused_strong_offers_is_refused_not_off_topic():
    """CF-0088's Wren Hollow shape: 0.31 and 0.28 were taken by the gates,
    a 0.15 frame filled the block. The pool *did* have the picture, so this
    is not a shortage of material - and the two must not collapse."""
    s = supply([cand(38, 0.31), cand(24, 0.28), cand(7, 0.15)],
               used=[{"shot": 7, "score": 0.15}],
               rejected=[rej(38, 0.31), rej(24, 0.28)])
    assert s["code"] == REFUSED, s
    assert s["on_topic_offered"] == 2 and s["best_used_score"] == 0.15


def test_every_code_is_declared_and_the_record_shape_is_the_same_for_all_three():
    seen = {supply([])["code"],
            supply([cand(1, 0.1)])["code"],
            supply([cand(1, 0.9)], rejected=[rej(1, 0.9)])["code"]}
    assert seen == set(resolve_anchors.CANDIDATE_SUPPLY_CODES), seen
    keys = None
    for s in (supply([]), supply([cand(1, 0.1)]),
              supply([cand(1, 0.9)], rejected=[rej(1, 0.9)])):
        assert keys is None or set(s) == keys, "the three codes carry different fields"
        keys = set(s)
    assert keys == {"code", "searched", "min_score", "offered", "best_offered_score",
                    "on_topic_offered", "used", "best_used_score", "refused",
                    "nearest"}, keys


def test_the_evidence_is_clipped_but_the_anchor_stays_recognisable():
    long_phrase = "a wooden water taxi pulling away from a dock with spray, " * 5
    s = supply([], phrase=long_phrase)
    assert len(s["searched"]) == resolve_anchors.SUPPLY_EVIDENCE_CHARS
    assert s["searched"].startswith("a wooden water taxi pulling away")


# --------------------------------------------------------------------------
# main(): the wiring, with the matcher / cutter / gate replaced
# --------------------------------------------------------------------------

def _index(n_plain, source=SRC):
    return {"source": source,
            "shots": [{"index": i, "start": i * 3.0, "end": i * 3.0 + 3.0}
                      for i in range(n_plain)]}


@contextlib.contextmanager
def _patched(candidates, gate, n_plain_shots=40):
    saved = {k: getattr(resolve_anchors, k) for k in
             ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")}
    index_data = {IDX: _index(n_plain_shots)}
    shot_len = {s["index"]: (s["start"], s["end"]) for s in index_data[IDX]["shots"]}

    def fake_match(indexes, phrases, min_score, top, python):
        cands = [{"shot": s, "score": sc, "start": shot_len[s][0], "end": shot_len[s][1],
                  "card": False, "promoted": False, "index": IDX, "source": SRC}
                 for s, sc in candidates]
        cands = resolve_anchors.order_candidates(cands, 0)
        return [{"phrase": ph,
                 "found": bool(cands) and max(c["score"] for c in cands) >= min_score,
                 "discriminative": True, "margin": 0.1, "candidates": list(cands)}
                for ph in phrases], index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, **kw):
        return gate(int(Path(clip).stem.rsplit("_s", 1)[1]))

    resolve_anchors.match = fake_match
    resolve_anchors.cut = fake_cut
    resolve_anchors.usable = fake_usable
    resolve_anchors.audio_duration = lambda path: 6.0
    resolve_anchors.leading_silence = lambda path: 0.0
    resolve_anchors.load_words = lambda path: [{"word": "w", "start": 0.4 + 0.5 * i,
                                                "end": 0.8 + 0.5 * i} for i in range(10)]
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(resolve_anchors, k, v)


def _run_main(candidates, gate, extra_args=()):
    with tempfile.TemporaryDirectory() as tmp, _patched(candidates, gate):
        tmp = Path(tmp)
        anchors = tmp / "anchors.json"
        anchors.write_text(json.dumps({"script_id": "t", "anchors": [
            {"word_index": 1, "phrase": "a wooden water taxi", "emphasis_words": []}]}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(anchors), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", str(MIN_SCORE),
                *extra_args]
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                resolve_anchors.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text())


def test_every_block_carries_the_key_even_when_the_pool_delivered():
    """`null` is an answer - "the pool had it" - and it has to be told apart
    from a storyboard that predates the fact. So the key is on every block."""
    story = _run_main([(1, 0.31), (2, 0.15)], lambda s: (True, []))
    assert story["blocks"], story
    # CF-0290: shot 2 is under the floor and is never offered, so the block is
    # filled by shot 1 alone - and the pool still delivered, so the key is null.
    for b in story["blocks"]:
        assert "candidate_supply" in b, b
        assert b["candidate_supply"] is None, b["candidate_supply"]


def test_a_gated_out_pool_reaches_the_block_as_refused():
    """An ordered rhythm, so the segment nothing could fill stays a bounded
    block of its own (CF-0085) - which is the block the shortage record is
    eventually built from."""
    story = _run_main([(1, 0.31), (2, 0.25)],
                      lambda s: (False, [f"mean luma too low on shot {s}"]),
                      extra_args=["--rhythm", "staccato"])
    assert all(b["asset_kind"] == "typographic" for b in story["blocks"]), story["blocks"]
    marks = [b["candidate_supply"] for b in story["blocks"]]
    assert marks and all(m and m["code"] == REFUSED for m in marks), marks
    assert marks[0]["on_topic_offered"] == 2 and marks[0]["refused"] == 2
    assert marks[0]["nearest"]["shot"] == "pool:1"


def test_a_pool_with_nothing_on_topic_reaches_the_block_as_off_topic():
    """The Clooney run end to end: a 0.116 pool, and a record that says the
    pool is not about this anchor.

    CF-0290 changed the second half of this test and not the first. Until then
    the block "still gets a picture" - the 0.116 frame went on screen under a
    phrase it does not depict, which is the delver defect - and the assertion
    here was `used >= 1`. The supply code is unchanged, because it was never a
    statement about the block: `pool_offered_off_topic` says the material is
    not about the anchor, and it is exactly as true now that the block is left
    without a picture. What changed is `used`, which is 0, and `blocks`, which
    on the default `even` rhythm holds nothing at all - a single anchor with no
    next one to carry into settles as a stretch (CF-0028/CF-0124).
    """
    story = _run_main([(2, 0.110), (5, 0.116)], lambda s: (True, []))
    marks = [a["supply"] for a in story["anchor_supply"]]
    assert all(m and m["code"] == OFF_TOPIC for m in marks), marks
    assert marks[0]["best_offered_score"] == 0.116
    floored = [r["reason"] for r in story["rejected_candidates"]]
    assert all("under the 0.22 similarity floor" in r for r in floored), floored
    # CF-0433 (grill 2026-09-29): the best the pool had goes on screen again,
    # by rank, and is marked for the plan's price (`score.low_similarity`).
    # No second, lower floor was invented - `--score-floor` is the run's own
    # outright refusal and stays unset in production - so 0.116 is used; the
    # supply code above still says the pool is not about this anchor.
    assert marks[0]["used"] >= 1, marks[0]
    assert story["blocks"] and story["blocks"][0]["below_floor"]["score"] == 0.116, \
        story["blocks"]


def test_the_score_floor_taking_the_whole_pool_is_not_an_empty_pool():
    """`--score-floor` is a gate like any other. A pool it emptied still
    offered those shots, and must not read as a pool that had none."""
    story = _run_main([(1, 0.31), (2, 0.25)], lambda s: (True, []),
                      extra_args=["--score-floor", "0.9", "--rhythm", "staccato"])
    marks = [b["candidate_supply"] for b in story["blocks"]]
    assert marks and all(m and m["code"] == REFUSED for m in marks), marks
    assert all(m["offered"] == 2 for m in marks), marks


def test_an_anchor_that_left_no_block_behind_is_still_answered():
    """On `even` a segment nothing could fill is carried into the next anchor
    (CF-0124) and has no block of its own - which is precisely the anchor the
    pool failed hardest. A record living only on blocks would be silent about
    it, so `anchor_supply` answers per anchor, `block_index: null` and all."""
    story = _run_main([(1, 0.31), (2, 0.25)], lambda s: (False, ["dark"]))
    assert story["blocks"] == [], story["blocks"]
    assert len(story["anchor_supply"]) >= 1, story["anchor_supply"]
    a = story["anchor_supply"][0]
    assert a["block_index"] is None and a["block_count"] == 0, a
    assert a["supply"]["code"] == REFUSED, a
    assert a["phrase"] == "a wooden water taxi" and a["end"] > a["start"]


def test_anchor_supply_and_the_block_copy_are_the_same_answer():
    # CF-0290: an off-topic pool no longer fills a block, so the anchor needs
    # an ordered rhythm to leave a block behind at all - `staccato` settles it
    # as its own typographic block (CF-0085), which is what carries the copy.
    story = _run_main([(2, 0.110), (5, 0.116)], lambda s: (True, []),
                      extra_args=["--rhythm", "staccato"])
    per_block = {b["candidate_supply"]["code"] for b in story["blocks"]}
    per_anchor = {a["supply"]["code"] for a in story["anchor_supply"] if a["supply"]}
    assert per_block == per_anchor == {OFF_TOPIC}, (per_block, per_anchor)
    assert all(a["block_index"] is not None for a in story["anchor_supply"]), \
        story["anchor_supply"]


def test_a_block_saved_by_the_emergency_repeat_still_says_the_pool_was_short():
    """CF-0137's one repeat puts a picture on screen; it does not put one in
    the pool. The fact is taken before the rescue for exactly that reason."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    head = src.split("verdict = gate_verdict(")[1].split("emergency = None")[0]
    assert "supply_by_segment[si] = candidate_supply(" in head, \
        "the supply fact moved past the emergency repeat - a repeated picture " \
        "would then read as a pool that delivered"


# --------------------------------------------------------------------------
# the deficit record: assetless_rung.py, and the whole chain end to end
# --------------------------------------------------------------------------

def test_anchor_records_carry_the_fact_when_it_is_known():
    mark = supply([cand(5, 0.116)])
    blocks = [{"intent": "a wooden water taxi", "start": 1.0, "end": 3.0}]
    recs = assetless_rung.anchor_records(
        [{"index": 0, "from": "clip", "reason": "r", "candidate_supply": mark}], blocks)
    assert recs[0]["candidate_supply"]["code"] == OFF_TOPIC, recs
    assert recs[0]["from"] == "clip", "the second fact is untouched by the third"


def test_anchor_records_leave_the_key_out_when_nobody_asked():
    """A plan built before CF-0150 has no such key, and the rotation reads
    historic records. Absent must not be manufactured into `null`."""
    recs = assetless_rung.anchor_records([{"index": 0, "from": "clip", "reason": "r"}],
                                         [{"intent": "i", "start": 0.0, "end": 1.0}])
    assert "candidate_supply" not in recs[0], recs[0]
    # ...while a delivered pool *is* recorded, as an explicit null.
    recs = assetless_rung.anchor_records(
        [{"index": 0, "from": "clip", "reason": "r", "candidate_supply": None}],
        [{"intent": "i", "start": 0.0, "end": 1.0}])
    assert "candidate_supply" in recs[0] and recs[0]["candidate_supply"] is None


def _silent_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += int(2000 if (i // 40) % 2 else -2000).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _unfilled_story(supplies):
    segs = [(0.0, 2.0), (2.0, 4.0)]
    blocks = []
    for i, (seg, mark) in enumerate(zip(segs, supplies)):
        b = resolve_anchors.unfilled_block(
            {"word_index": i, "phrase": f"anchor {i}", "emphasis_words": []},
            {"role": "beat"}, *seg, "every candidate failed to cut")
        if mark is not ...:
            b["candidate_supply"] = mark
        blocks.append(b)
    return {"script_id": "cf-0150", "style": "motion", "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "staccato",
                       "rhythm_built": "staccato",
                       "parameters": {"block_count": 2, "key_frame_hold_seconds": 2.0},
                       "opening_requested": None, "opening_delivered": None,
                       "anchor_count": 2},
            "blocks": blocks, "unresolved_anchors": [], "rejected_candidates": []}


def test_the_refusal_record_carries_the_fact_for_every_anchor():
    """End to end through the real `build_render_plan.py`: the rung is off
    (every real channel), the gate warns (CF-0330), and the deficit record beside
    it now answers "was there ever a picture for this anchor" per anchor -
    one that the pool never had anything on topic for, and one that the
    gates took a good frame away from."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    off_topic = supply([cand(5, 0.116)])
    refused = supply([cand(38, 0.31)], rejected=[rej(38, 0.31)])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        (tmp / "words.json").write_text(json.dumps(
            [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]))
        (tmp / "storyboard.json").write_text(json.dumps(_unfilled_story([off_topic, refused])))
        out = tmp / "plan.json"
        r = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60"],
            capture_output=True, text=True, cwd=tmp)
        # CF-0330: the gate warns and the plan is written; the deficit record
        # beside it is the same file the rotation reads
        assert r.returncode == 0, (r.returncode, r.stderr[-2000:])
        deficit = json.loads((tmp / "plan.assetless-rung.json").read_text())
        anchors = deficit["assetless_rung"]["anchors"]
        assert len(anchors) == 2, anchors
        assert [a["block_index"] for a in anchors] == [0, 1], anchors
        codes = [a["candidate_supply"]["code"] for a in anchors]
        assert codes == [OFF_TOPIC, REFUSED], codes
        assert anchors[0]["candidate_supply"]["nearest"]["shot"] == "pool:5"
        # The two older facts are untouched.
        assert all(a["from"] == "unfilled" for a in anchors), anchors
        assert all(a["reason"] for a in anchors), anchors


def test_a_storyboard_from_before_cf_0150_still_builds_and_says_nothing():
    """The regression that matters for the rotation: an old storyboard has no
    such key anywhere, and nothing downstream invents one."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        (tmp / "words.json").write_text(json.dumps(
            [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]))
        (tmp / "storyboard.json").write_text(json.dumps(_unfilled_story([..., ...])))
        out = tmp / "plan.json"
        r = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60"],
            capture_output=True, text=True, cwd=tmp)
        # CF-0330: the gate warns and the plan is written; the deficit record
        # beside it is the same file the rotation reads
        assert r.returncode == 0, (r.returncode, r.stderr[-2000:])
        deficit = json.loads((tmp / "plan.assetless-rung.json").read_text())
        anchors = deficit["assetless_rung"]["anchors"]
        assert anchors and all("candidate_supply" not in a for a in anchors), anchors


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
