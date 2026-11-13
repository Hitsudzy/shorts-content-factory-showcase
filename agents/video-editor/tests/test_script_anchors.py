#!/usr/bin/env python3
"""CF-0140: the anchors are the script's, and this stage may not invent them.

`scripts/script_anchors.py` is the Video Editor's side of the contract the
Content Researcher writes: `visual_anchors[]` in `03-content-researcher.json`,
checked against the footage pool before TTS. What this file pins is the three
places where the mechanism could quietly turn back into the old one:

  * a script with no `visual_anchors` must be handed back, never filled in
    here - a silent fallback to writing anchors at step 4 is exactly the
    pre-CF-0140 behaviour, and it would leave the preflight guarding phrases
    nobody uses;
  * `beat_text` -> `word_index` is the seam everything rests on. An unlocatable
    beat drops that anchor and is said out loud; no index is ever guessed, and
    a script that loses all of them goes back;
  * the preflight run here answers, it does not repair. It asks with the
    resolver's own constants (no `--min-score`, no `--top` at this seam), and a
    refusal stops the run before synthesis instead of falling into the CF-0137
    ladder.

Plus the thing that makes any of it worth doing: the phrase reaches the matcher
byte for byte as the writer wrote it.

No pytest - plain asserts, run directly. No CLIP, no ffmpeg, no footage.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

TMP = tmp_root("ve-script-anchors-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import meme_layer  # noqa: E402
import script_anchors as sa  # noqa: E402

PASSED = FAILED = 0


def check(name, fn):
    global PASSED, FAILED
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - a test runner
        FAILED += 1
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    else:
        PASSED += 1
        print(f"ok   {name}")


# --------------------------------------------------------------------------
# fixtures - a script, its alignment, and the files on disk
# --------------------------------------------------------------------------

HOOK = "Two people sit on a deck."
COMMENTARY = "The trailer shows a lake house at dusk. Nobody says why."
PAYOFF = "And that is why two people sit on a deck."

ANCHORS = [
    {"anchor_id": "v1", "phrase": "two people sitting on a deck overlooking a lake",
     "beat_text": "Two people sit on a deck", "side": None},
    {"anchor_id": "v2", "phrase": "a wooden house at the edge of a lake at dusk",
     "beat_text": "a lake house at dusk"},
]


# CF-0356: the Researcher's cadence gate passed this script and recorded it -
# the preflight asks the text gates first and runs nothing for a passing record
# (tests/test_text_gates.py is where the missing record is exercised).
CADENCE_PASSED = {"layout": {"asked": True, "blocks": 2}, "verdict": "fits", "action": "pass"}


def script(anchors=ANCHORS, script_id="001"):
    s = {"script_id": script_id, "hook": HOOK, "commentary": COMMENTARY, "payoff": PAYOFF,
         "anchor_cadence": dict(CADENCE_PASSED)}
    if anchors is not None:
        s["visual_anchors"] = json.loads(json.dumps(anchors))
    return s


def words(text=None):
    text = text if text is not None else " ".join((HOOK, COMMENTARY, PAYOFF))
    return [{"word": w, "start": round(0.3 * i, 2), "end": round(0.3 * i + 0.25, 2)}
            for i, w in enumerate(text.split())]


def batch_file(scripts, name):
    path = TMP / name
    path.write_text(json.dumps({"batch_id": "T", "scripts": scripts}))
    return path


def words_file(name, wordlist=None):
    path = TMP / name
    path.write_text(json.dumps({"words": wordlist if wordlist is not None else words()}))
    return path


def run(argv):
    """`main(argv)` with stderr captured: (exit code, stderr)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = sa.main(argv)
    return code, err.getvalue()


# --------------------------------------------------------------------------
# 1. the script's anchors, not the Editor's
# --------------------------------------------------------------------------

def test_a_script_without_visual_anchors_is_handed_back():
    """The one fallback that must not exist: writing the anchors here anyway.
    That is the pre-CF-0140 behaviour, and it is invisible in a run log."""
    src = batch_file([script(anchors=None)], "no-field.json")
    out = TMP / "no-field.anchors.json"
    code, err = run(["spec", str(src), "--script-id", "001",
                     "--words", str(words_file("w1.json")), "--out", str(out)])
    assert code == sa.EXIT_HAND_BACK, code
    assert not out.exists(), "an anchors file was written for a script that declared none"
    assert "visual_anchors" in err and "Content Researcher" in err, err


def test_an_empty_or_malformed_field_is_handed_back_too():
    for anchors, why in [([], "empty"),
                         ([{"anchor_id": "v1", "beat_text": "Two people sit on a deck"}], "no phrase"),
                         ([{"anchor_id": "v1", "phrase": "a deck"}], "no beat_text"),
                         ([{"anchor_id": "v1", "phrase": "  ", "beat_text": "a deck"}], "blank phrase")]:
        try:
            sa.visual_anchors(script(anchors=anchors))
        except sa.HandBack:
            continue
        raise AssertionError(f"{why} was accepted")


def test_the_phrase_reaches_the_matcher_byte_for_byte():
    """A rephrased anchor is a different question, and the preflight answered
    the writer's. So: no strip-and-title-case, no punctuation tidy, no
    dedup - the same string in the spec and in the preflight call."""
    weird = [{"anchor_id": "v1", "phrase": "  a 98% black frame, \"as shot\"  ",
              "beat_text": "Two people sit on a deck"}]
    assert sa.phrases(weird) == ['a 98% black frame, "as shot"']
    kept, _ = sa.spec_anchors(sa.visual_anchors(script(anchors=weird)),
                              script(anchors=weird), words())
    assert kept[0]["phrase"] == weird[0]["phrase"], kept[0]["phrase"]


def test_nothing_is_added_and_the_side_is_carried_as_written():
    anchors = [dict(ANCHORS[0], side="b"), dict(ANCHORS[1], side="a")]
    kept, dropped = sa.spec_anchors(anchors, script(anchors=anchors), words())
    assert len(kept) == len(anchors) and not dropped
    assert [a["side"] for a in kept] == ["b", "a"], kept
    assert [a["anchor_id"] for a in kept] == ["v1", "v2"], kept


# --------------------------------------------------------------------------
# 2. beat_text -> word_index
# --------------------------------------------------------------------------

def test_the_word_index_is_the_first_word_of_the_beat():
    kept, dropped = sa.spec_anchors(ANCHORS, script(), words())
    assert not dropped, dropped
    aligned = words()
    for a in kept:
        assert 0 <= a["word_index"] < len(aligned)
    assert aligned[kept[0]["word_index"]]["word"] == "Two"
    # "a lake house at dusk" - the commentary's "a", not the hook's "a deck"
    assert aligned[kept[1]["word_index"] + 1]["word"] == "lake"


def test_the_spec_is_sorted_by_word_index_as_the_resolver_expects():
    reversed_order = [ANCHORS[1], ANCHORS[0]]
    kept, _ = sa.spec_anchors(reversed_order, script(anchors=reversed_order), words())
    assert [a["word_index"] for a in kept] == sorted(a["word_index"] for a in kept)
    assert kept[0]["anchor_id"] == "v1", kept


def test_the_spec_is_read_back_by_the_resolvers_own_code():
    """Not "the shape looks right": the resolver's own readers are run over it.
    `resolve_anchors.main()` sorts by `word_index`, indexes `words.json` with
    it and asks `declared_anchor_sides()` for the sides."""
    import resolve_anchors  # already imported by anchor_coverage; free here

    anchors = [dict(ANCHORS[0], side="a"), dict(ANCHORS[1], side="b")]
    kept, _ = sa.spec_anchors(anchors, script(anchors=anchors), words())
    spec = sa.build_spec(script(anchors=anchors), kept, opening_card="A CARD")
    aligned = words()
    ordered = sorted(spec["anchors"], key=lambda a: a["word_index"])
    assert [words()[a["word_index"]]["start"] for a in ordered]  # no IndexError
    assert resolve_anchors.declared_anchor_sides(ordered) == ["a", "b"], ordered
    assert [a["phrase"] for a in ordered] == [a["phrase"] for a in anchors]
    assert (spec["opening_card"] or {}).get("text") == "A CARD"
    assert spec["script_id"] == "001" and spec["style"] == "motion"
    assert max(a["word_index"] for a in ordered) < len(aligned)


def test_a_beat_that_is_not_in_the_alignment_drops_that_anchor_and_says_so():
    """Never a guessed index: a frame put on a moment the writer did not ask
    for is the same lie as a rewritten phrase, only harder to see."""
    anchors = ANCHORS + [{"anchor_id": "v3", "phrase": "a red car",
                          "beat_text": "words that were never spoken here at all"}]
    src = batch_file([script(anchors=anchors)], "lost-beat.json")
    out = TMP / "lost-beat.anchors.json"
    code, err = run(["spec", str(src), "--script-id", "001",
                     "--words", str(words_file("w2.json")), "--out", str(out)])
    assert code == sa.EXIT_OK, (code, err)
    assert "ANCHOR DROPPED" in err and meme_layer.BEAT_MISSING_IN_SCRIPT in err and "v3" in err, err
    spec = json.loads(out.read_text())
    assert [a["anchor_id"] for a in spec["anchors"]] == ["v1", "v2"], spec
    kept, dropped = sa.spec_anchors(anchors, script(anchors=anchors), words())
    assert [d["reason"] for d in dropped] == [meme_layer.BEAT_MISSING_IN_SCRIPT]
    assert dropped[0]["anchor_id"] == "v3" and dropped[0]["beat_text"]


def test_a_drop_says_whether_the_script_or_the_alignment_lost_the_words():
    """CF-0235: `ANCHOR DROPPED [beat_not_found]` was printed both when the
    writer pinned a picture to a sentence the video never says - the script
    goes back - and when our own forced alignment lost a sentence the script
    has character for character, which costs the writer nothing and is ours to
    fix. Same three codes and the same `meme_layer.beat_failure()` evidence as
    the proof, meme and sound layers; no fourth vocabulary for one question."""
    # the script does not say it
    never = [{"anchor_id": "v3", "phrase": "a red car",
              "beat_text": "words that were never spoken here at all"}]
    kept, dropped = sa.spec_anchors(never, script(anchors=never), words())
    assert kept == [] and dropped[0]["reason"] == meme_layer.BEAT_MISSING_IN_SCRIPT
    ev = dropped[0]["evidence"]
    assert ev["code"] == meme_layer.BEAT_MISSING_IN_SCRIPT
    assert ev["in_script_coverage"] < meme_layer.BEAT_MATCH_MIN_RATIO
    assert "goes back to the writer" in dropped[0]["detail"], dropped[0]["detail"]

    # the script says it and the alignment stops after the hook
    kept, dropped = sa.spec_anchors(ANCHORS[1:], script(), words(HOOK))
    assert kept == [] and dropped[0]["reason"] == meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT
    ev = dropped[0]["evidence"]
    assert ev["in_script_coverage"] == 1.0 and ev["nearest"]["text"]
    assert "ours to fix" in dropped[0]["detail"], dropped[0]["detail"]

    # and the hand-back names which of the two took the whole script
    code, err = run(["spec", str(batch_file([script(anchors=ANCHORS[1:])], "aligner-lost.json")),
                     "--script-id", "001",
                     "--words", str(words_file("w-hook-only.json", words(HOOK))),
                     "--out", str(TMP / "aligner-lost.anchors.json")])
    assert code == sa.EXIT_HAND_BACK, (code, err)
    assert meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT in err and "ours to fix" in err, err
    assert "beat_not_found" not in err, err


def test_a_script_whose_every_beat_is_lost_goes_back_and_writes_no_spec():
    anchors = [{"anchor_id": "v1", "phrase": "a red car",
                "beat_text": "nothing of this sentence was ever said"}]
    src = batch_file([script(anchors=anchors)], "all-lost.json")
    out = TMP / "all-lost.anchors.json"
    code, err = run(["spec", str(src), "--script-id", "001",
                     "--words", str(words_file("w3.json")), "--out", str(out)])
    assert code == sa.EXIT_HAND_BACK, (code, err)
    assert not out.exists(), "a spec with no anchors was written"
    assert "Content Researcher" in err, err


def test_two_anchors_on_one_word_are_not_both_kept():
    """The resolver derives block boundaries from anchor starts; two anchors on
    one word ask for two pictures in a stretch of zero seconds."""
    anchors = [ANCHORS[0], {"anchor_id": "v9", "phrase": "a different frame",
                            "beat_text": "Two people sit on a deck"}]
    kept, dropped = sa.spec_anchors(anchors, script(anchors=anchors), words())
    assert [a["anchor_id"] for a in kept] == ["v1"], kept
    assert dropped and dropped[0]["reason"] == sa.DROP_BEAT_COLLISION, dropped
    assert "v1" in dropped[0]["detail"], dropped


def test_a_payoff_beat_that_echoes_the_hook_lands_on_the_payoff():
    """The payoff is *required* to echo the hook's wording (Content Researcher
    SKILL.md), so identical windows are a normal case and not a curiosity.
    Without the section the words came from, the beat lands on the hook."""
    beat = "two people sit on a deck"
    assert beat.lower() in PAYOFF.lower() and beat.lower() in HOOK.lower()
    anchors = [{"anchor_id": "v1", "phrase": "the closing frame",
                "beat_text": "two people sit on a deck"}]
    kept, dropped = sa.spec_anchors(anchors, script(anchors=anchors), words())
    assert not dropped, dropped
    hook_words = len(meme_layer.norm_tokens(HOOK))
    assert kept[0]["word_index"] >= hook_words, (kept, hook_words)
    # and the shared locator's own callers are unchanged: with no expectation
    # passed, it still guesses from the commentary alone.
    plain = meme_layer.locate_beat("Two people sit on a deck", script(), words())
    assert plain == (0, 5), plain


# --------------------------------------------------------------------------
# 3. the preflight: it answers, it does not repair
# --------------------------------------------------------------------------

class Recorder:
    """Stands in for anchor_coverage.preflight() - the only expensive call."""

    def __init__(self, passed=True):
        self.calls = []
        self.passed = passed

    def __call__(self, phrases, indexes, *args, **kwargs):
        self.calls.append({"phrases": list(phrases), "indexes": list(indexes),
                           "args": args, "kwargs": dict(kwargs)})
        return {"kind": "anchor_coverage_preflight", "passed": self.passed,
                "refused_because": [] if self.passed else ["absent_anchors"],
                "note": "double", "anchors": [], "absent": [], "weak": [],
                "contention": {"note": "double"}}


@contextlib.contextmanager
def preflight_double(passed=True):
    real, rec = anchor_coverage_preflight(), Recorder(passed)
    sa.anchor_coverage.preflight = rec
    try:
        yield rec
    finally:
        sa.anchor_coverage.preflight = real


def anchor_coverage_preflight():
    return sa.anchor_coverage.preflight


def test_the_preflight_asks_about_the_writers_phrases_and_that_pool():
    src = batch_file([script()], "pre-ok.json")
    with preflight_double(passed=True) as rec:
        code, err = run(["preflight", str(src), "--script-id", "001",
                         "--index", "/pool/a.shots.json", "--index", "/pool/b.shots.json",
                         "--out", str(TMP / "pre-ok.report.json")])
    assert code == sa.EXIT_OK, (code, err)
    call = rec.calls[0]
    assert call["phrases"] == [a["phrase"] for a in ANCHORS], call["phrases"]
    assert call["indexes"] == ["/pool/a.shots.json", "/pool/b.shots.json"], call["indexes"]
    report = json.loads((TMP / "pre-ok.report.json").read_text())
    assert report["script_id"] == "001" and report["anchor_ids"] == ["v1", "v2"], report


def test_no_matcher_knob_is_settable_at_this_seam():
    """`--min-score` / `--top` exist on anchor_coverage.py and are deliberately
    unreachable from here: both sides take resolve_anchors' constants, and a
    flag at this seam is how the two answers drift apart."""
    src = batch_file([script()], "pre-knobs.json")
    for flag in (["--min-score", "0.1"], ["--top", "40"]):
        try:
            with preflight_double():
                run(["preflight", str(src), "--script-id", "001",
                     "--index", "/pool/a.shots.json"] + flag)
        except SystemExit as exc:  # argparse: unrecognized arguments
            assert exc.code != 0
            continue
        raise AssertionError(f"{flag[0]} was accepted")
    with preflight_double() as rec:
        run(["preflight", str(src), "--script-id", "001", "--index", "/pool/a.shots.json"])
    kwargs, args = rec.calls[0]["kwargs"], rec.calls[0]["args"]
    assert not args, args
    assert set(kwargs) <= {"matcher_python", "strict"}, kwargs


def test_the_double_is_calling_the_real_signature():
    """The preflight is stubbed in every test above, so the one thing a double
    can hide - a call the real function would not accept - is checked here."""
    import inspect
    sig = inspect.signature(sa.anchor_coverage.preflight)
    sig.bind(["a phrase"], ["/pool/a.shots.json"], matcher_python=None, strict=False)
    assert "min_score" in sig.parameters and "top" in sig.parameters, sig


def test_an_uncovered_pool_warns_and_the_run_goes_on():
    """CF-0330 (the user, 2026-09-23): the pool verdict is a warning. It still
    answers the question and still does not repair anything - but it no
    longer stops the synthesis, and it says so."""
    src = batch_file([script()], "pre-refused.json")
    with preflight_double(passed=False):
        code, err = run(["preflight", str(src), "--script-id", "001",
                         "--index", "/pool/a.shots.json"])
    assert code == sa.EXIT_OK, code
    assert "ANCHORS NOT COVERED - WARNING" in err and "pool_too_thin" in err, err
    assert "do not synthesize" not in err, err


def test_a_script_with_no_anchors_never_reaches_the_matcher():
    src = batch_file([script(anchors=None)], "pre-blind.json")
    with preflight_double() as rec:
        code, err = run(["preflight", str(src), "--script-id", "001",
                         "--index", "/pool/a.shots.json"])
    assert code == sa.EXIT_HAND_BACK, (code, err)
    assert not rec.calls, "the pool was asked about a script that named no frames"


# --------------------------------------------------------------------------
# 4. "could not answer" is not a verdict on a script
# --------------------------------------------------------------------------

def test_an_unknown_script_id_or_unreadable_file_exits_one():
    src = batch_file([script()], "codes.json")
    out = TMP / "codes.anchors.json"
    code, err = run(["spec", str(src), "--script-id", "404",
                     "--words", str(words_file("w4.json")), "--out", str(out)])
    assert code == sa.EXIT_CANNOT_ANSWER, (code, err)
    assert "404" in err, err
    code, err = run(["spec", str(TMP / "nope.json"), "--script-id", "001",
                     "--words", str(words_file("w5.json")), "--out", str(out)])
    assert code == sa.EXIT_CANNOT_ANSWER, (code, err)
    empty = TMP / "empty-words.json"
    empty.write_text(json.dumps({"words": []}))
    code, err = run(["spec", str(src), "--script-id", "001",
                     "--words", str(empty), "--out", str(out)])
    assert code == sa.EXIT_CANNOT_ANSWER, (code, err)
    assert not out.exists()


# --------------------------------------------------------------------------
# 5. the skill says the same thing the code does
# --------------------------------------------------------------------------

SKILL = REPO / ".claude" / "skills" / "video-editor" / "SKILL.md"


def test_the_skill_puts_the_preflight_before_the_synthesis():
    text = SKILL.read_text()
    procedure = text[text.index("### Procedure"):]
    pre = procedure.index("script_anchors.py preflight")
    tts = procedure.lower().index("**synthesize voiceover**")
    assert pre < tts, "the preflight is documented after the TTS it exists to save"
    assert "visual_anchors" in procedure, "step 4 does not name the field it reads"
    step4 = procedure[procedure.index("4. **"):procedure.index("5. **")]
    assert "script_anchors.py spec" in step4, step4[:400]


for name, fn in sorted(list(globals().items())):
    if name.startswith("test_") and callable(fn):
        check(name[5:].replace("_", " "), fn)

print(f"\n{PASSED}/{PASSED + FAILED} passed" + (f", {FAILED} FAILED" if FAILED else ""))
sys.exit(1 if FAILED else 0)
