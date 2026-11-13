#!/usr/bin/env python3
"""CF-0271: the channel brings three beds, and the generator stops playing
in silence.

The user listened to one lofi bed under a run of videos on 2026-09-20 and
asked for a rotation of three. What is locked here is the machinery around
that decision, in the order a video meets it:

  * `video_editor.ambient.beds` is read as a list, every file in it has to be
    on disk, and a config that says both `beds` and `path` has not decided;
  * **which** of them plays is a pure function of the video's key - the same
    video draws the same bed on its second render attempt, in another process,
    on another machine, which is why the choice is sha256 and not the salted
    built-in `hash()`;
  * the choice is made once, in the plan (`audio.bed_rotation`), and the mixer
    executes it - a rotating channel under a plan that never chose refuses
    rather than choosing a second time;
  * and the two paths to the generated bed, which until this task were silent,
    now say so: `runlog.annotate(bed="GENERATED <code>")`, a `SUBSTITUTED`
    line in the report and `bed.substituted` on the plan, which reaches
    `05-video-editor.json` as `bed_substituted`.

What is *not* locked here: that the generator mixes at -18 dB and a supplied
file at the channel's -25. That split is CF-0165's recorded decision, it was
re-examined on 2026-09-21 and kept, and it is pinned by
test_bed_level_setting.py. This task's complaint was never "-18 is the wrong
level" - it was "the video shipped with it and nobody was told".

**The bed files here are test fixtures**, noise from numpy, for the reason
test_ambient_bed.py's docstring gives: nothing in this repository may produce
a channel's real bed, and a synthetic one proves only that the machinery
works. The channel's three real beds and their loudness are the root's, in
`tests/test_channel_bed_rotation.py`.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

import ambient_bed as ab  # noqa: E402
import build_soundtrack as bs  # noqa: E402
import write_batch_metadata  # noqa: E402

# Aliased so the runner at the bottom does not call their tests as if they
# were this file's - the same precaution test_ambient_bed.py takes.
import test_ambient_bed as ambtest  # noqa: E402
import test_bed_audibility as bedtest  # noqa: E402

BEDS = ("beds/kids.wav", "beds/morning.wav", "beds/tokyo.wav")


def rotating_root(tmp, names=BEDS, extra_ambient=None, make=True):
    """A factory root whose channel rotates `names`, written as the real
    config writes them: paths relative to the factory root."""
    root = ambtest.channel_root(
        tmp, video_editor={"ambient": dict({"beds": [f"channels/chan/{n}" for n in names]},
                                           **(extra_ambient or {}))})
    if make:
        (root / "channels" / "chan" / "beds").mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(names):
            ambtest.ambient_wav(root / "channels" / "chan" / n, seed=5 + i)
    return root


def cfg_of(root, channel_id="chan"):
    return json.loads((root / "channels" / f"{channel_id}.json").read_text())


def refused(fn, needle):
    try:
        got = fn()
    except ab.AmbientBedError as e:
        assert needle in str(e), f"the refusal does not say {needle!r}: {e}"
        return str(e)
    raise AssertionError(f"passed instead of refusing: {got!r}")


# --------------------------------------------------------------------------
# A. reading the list
# --------------------------------------------------------------------------


def test_the_channel_may_name_a_list_and_it_is_read_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        beds = ab.ambient_beds(cfg_of(root), root, "chan")
        assert [p.name for p, _ in beds] == ["kids.wav", "morning.wav", "tokyo.wav"], beds
        assert {s for _, s in beds} == {ab.AMBIENT_SOURCE_ROTATION}
        # relative to the factory root, exactly as `ambient.path` is
        assert beds[0][0] == root / "channels" / "chan" / "beds" / "kids.wav"


def test_a_rotation_with_a_hole_in_it_is_refused_by_name():
    """The doctrine `ambient_path()` already has, applied to every entry: a
    named file that is not there stops the video. A rotation that quietly
    shrank would put a bed nobody chose under every video whose hash lands on
    the hole - the same class of fault this task was raised about, and harder
    to see."""
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        (root / "channels" / "chan" / "beds" / "morning.wav").unlink()
        e = refused(lambda: ab.ambient_beds(cfg_of(root), root, "chan"),
                    "video_editor.ambient.beds[1]")
        assert "morning.wav" in e


def test_naming_one_file_and_a_rotation_at_once_is_refused():
    """The root refuses this too (VIDEO_EDITOR_EXCLUSIVE_KEYS). The Editor
    checks it again rather than trusting that someone validated the config -
    which of the two played would otherwise be decided by the order this code
    happens to read them in."""
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp, extra_ambient={"path": "channels/chan/ambient.wav"})
        ambtest.ambient_wav(root / "channels" / "chan" / "ambient.wav")
        refused(lambda: ab.ambient_beds(cfg_of(root), root, "chan"),
                "video_editor.ambient.path")


def test_a_list_that_is_not_a_list_of_files_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        cfg = cfg_of(root)
        for bad, needle in (("channels/chan/beds/kids.wav", "not a list"),
                            (3, "not a list"),
                            ({"0": "x"}, "not a list"),
                            ([], "empty list"),
                            (["channels/chan/beds/kids.wav", 7], "beds[1]"),
                            (["channels/chan/beds/kids.wav", "  "], "beds[1]")):
            cfg["video_editor"]["ambient"]["beds"] = bad
            refused(lambda: ab.ambient_beds(cfg, root, "chan"), needle)


def test_a_channel_that_does_not_rotate_reads_exactly_as_it_did():
    """Three shapes that predate this task and may not have moved: the single
    `path` override, the convention file, and a channel with no bed at all."""
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        cfg = cfg_of(root)
        beds = ab.ambient_beds(cfg, root, "chan")
        assert beds == [(root / "channels" / "chan" / "ambient.wav",
                         ab.AMBIENT_SOURCE_CONVENTION)], beds

        named = ambtest.channel_root(
            tmp + "/named", ambient="ambient.wav",
            video_editor={"ambient": {"path": "channels/chan/ambient.wav"}})
        got = ab.ambient_beds(cfg_of(named), named, "chan")
        assert [s for _, s in got] == [ab.AMBIENT_SOURCE_CONFIG], got

        bare = ambtest.channel_root(tmp + "/bare")
        assert ab.ambient_beds(cfg_of(bare), bare, "chan") == []
        assert ab.ambient_beds({}, bare) == []


# --------------------------------------------------------------------------
# B. which one plays
# --------------------------------------------------------------------------

# The three scripts of batch example-film/2026-09-18T2232Z, and the bed each of
# them draws from a three-bed rotation. Pinned as literals - not recomputed
# from the same function the test is checking - so that a change to the rule
# shows up here as a failing test and has to be argued for, rather than
# silently re-shuffling every video that has already shipped.
GOLDEN = {"lf-2026-09-18-006-script1": 0,
          "lf-2026-09-18-008-script1": 1,
          "lf-2026-09-18-009-script1": 2}


def test_the_rule_is_pinned_and_a_key_always_draws_the_same_bed():
    for key, index in GOLDEN.items():
        assert ab.bed_index(3, key) == index, key
    assert ab.bed_index(1, "anything") == 0
    refused(lambda: ab.bed_index(0, "k"), "no beds")


def test_the_same_video_draws_the_same_bed_in_another_process():
    """`hash()` on a string is salted by PYTHONHASHSEED, so a rotation built
    on it would hand the same video a different bed on its second render
    attempt (max_attempts_per_video is 3 and qc_render sends videos back to
    the mix) and a third one on a remix next month. sha256 is the whole reason
    no registry is needed, so it is worth a subprocess to prove."""
    import subprocess
    keys = list(GOLDEN)
    code = ("import sys; sys.path.insert(0, %r); import ambient_bed as ab; "
            "print([ab.bed_index(3, k) for k in %r])" % (str(SCRIPTS), keys))
    seen = set()
    for seed in ("0", "1", "12345"):
        out = subprocess.run([ambtest.PY, "-c", code], capture_output=True, text=True,
                             env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"})
        assert out.returncode == 0, out.stderr
        seen.add(out.stdout.strip())
    assert seen == {str([GOLDEN[k] for k in keys])}, seen


def test_the_rotation_is_used_whole_even_though_it_is_not_round_robin():
    """The choice is a hash, so the spread is binomial (90 videos over three
    beds is 30 +/- 4.5) and not a cycle. What must hold is that no bed is
    effectively unreachable - a rotation of three that plays two would be the
    bug this looks like when it happens."""
    counts = [0, 0, 0]
    for i in range(300):
        counts[ab.bed_index(3, f"lf-2026-09-{i:03d}-script1")] += 1
    assert sum(counts) == 300
    assert min(counts) > 60, counts   # 100 +/- 8.2 expected; 60 is five sigma out


def test_the_record_says_enough_to_recheck_the_choice():
    """`index: 2` says which file played and nothing about why. The key and
    the rule are written beside it so a reader can recompute the choice
    instead of believing the record."""
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        beds = ab.ambient_beds(cfg_of(root), root, "chan")
        rec = ab.rotation_record(beds, "lf-2026-09-18-008-script1")
        assert rec["chosen_by"] == ab.BED_CHOSEN_BY_SCRIPT_ID == "sha256(script_id)"
        assert rec["key"] == "lf-2026-09-18-008-script1"
        assert rec["index"] == GOLDEN[rec["key"]]
        assert rec["chosen"] == rec["beds"][rec["index"]]
        assert rec["beds"] == [str(p.resolve()) for p, _ in beds]
        assert ab.bed_index(len(rec["beds"]), rec["key"]) == rec["index"]
        # `.resolve()` on both sides: the record stores resolved paths (the
        # plan's house style, `audio.src` and `ambient.path` are resolved too)
        # and a temporary directory on macOS is reached through a symlink.
        assert ab.choose_bed(beds, rec["key"])[0].resolve() == Path(rec["chosen"])


def test_a_plan_that_never_chose_is_refused_and_a_stale_choice_too():
    """Both halves of "the mixer executes, it does not decide". A plan built
    before this task carries no choice; a plan built when the rotation held
    other files carries one that is no longer offered. Guessing in either case
    would mean a rebuilt plan could change the sound of a video that was
    already approved."""
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        beds = ab.ambient_beds(cfg_of(root), root, "chan")
        assert ab.bed_from_rotation(ab.rotation_record(beds, "k"), beds).name in \
            {"kids.wav", "morning.wav", "tokyo.wav"}
        for absent in (None, {}, {"index": 1}):
            refused(lambda: ab.bed_from_rotation(absent, beds), "rebuild the plan")
        stale = dict(ab.rotation_record(beds, "k"),
                     chosen=str(root / "channels" / "chan" / "beds" / "gone.wav"))
        refused(lambda: ab.bed_from_rotation(stale, beds), "does not offer it any more")


# --------------------------------------------------------------------------
# C. the mix, end to end
# --------------------------------------------------------------------------


def mixed(tmp, root, channel="chan", key=None, argv_extra=(), rotation="from-key"):
    """One real mix with the choice on the plan, the way the pipeline does it:
    build_render_plan.py writes `audio.bed_rotation`, build_soundtrack.py
    reads it. Returns (the plan as the mixer left it, what the runlog was
    told)."""
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    words = bedtest.voice_wav(tmp / "voice.wav")
    plan = bedtest.plan_for(words)
    plan["audio"]["src"] = str(tmp / "voice.wav")
    if rotation == "from-key":
        beds = ab.ambient_beds(cfg_of(Path(root), channel), root, channel)
        plan["audio"]["bed_rotation"] = ab.rotation_record(beds, key) if beds else None
    elif rotation is not None:
        plan["audio"]["bed_rotation"] = rotation
    (tmp / "plan.json").write_text(json.dumps(plan))

    class Spy:
        params = {}

        @staticmethod
        def annotate(**kw):
            Spy.params.update(kw)

    argv, real = sys.argv, bs.runlog
    sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"), str(tmp / "plan.json"),
                str(tmp / "mix.wav"), "--channel", str(channel), "--root", str(root),
                *argv_extra]
    bs.runlog = Spy
    try:
        bs.main()
    finally:
        sys.argv, bs.runlog = argv, real
    return json.loads((tmp / "plan.json").read_text()), Spy.params


def test_the_mixer_plays_the_bed_the_plan_chose_and_the_record_says_which():
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        for key, index in GOLDEN.items():
            plan, annotated = mixed(Path(tmp) / f"w{index}", root, key=key)
            bed = plan["audio"]["bed"]
            ambient = bed["ambient"]
            assert bed["source"] == "supplied" and bed["substituted"] is None
            assert ambient["name"] == BEDS[index].split("/")[-1], (key, ambient["name"])
            assert ambient["source"] == ab.AMBIENT_SOURCE_ROTATION
            assert ambient["rotation_index"] == index
            assert ambient["rotation_size"] == 3
            assert ambient["chosen_by"] == ab.BED_CHOSEN_BY_SCRIPT_ID
            assert bed["rotation"]["key"] == key
            # the run's own accounting names the file that played
            assert annotated["bed"] == f"{ambient['name']} [{index + 1}/3]", annotated

            record = ab.bed_record_fields(plan)
            assert set(record) == set(ab.BED_RECORD_KEYS)
            assert record["ambient_rotation_index"] == index
            assert record["ambient_rotation_size"] == 3
            assert record["ambient_chosen_by"] == ab.BED_CHOSEN_BY_SCRIPT_ID
            assert record["bed_substituted"] is None
            plan["blocks"], plan["style"] = [], "motion"
            video = write_batch_metadata.video_record(
                "s1", plan, str(Path(tmp) / f"w{index}" / "mix.wav"),
                {"passed": True, "failures": [], "notes": []}, None)
            assert video["bed"] == record, video["bed"]


def test_a_rotating_channel_under_an_unchosen_plan_stops_the_mix():
    with tempfile.TemporaryDirectory() as tmp:
        root = rotating_root(tmp)
        refused(lambda: mixed(Path(tmp) / "w", root, rotation=None),
                "rebuild the plan")
        assert not (Path(tmp) / "w" / "mix.wav").exists(), \
            "the mix was written before the bed was resolved"


def test_a_single_file_channel_mixes_as_it_did_and_says_nothing_new():
    """The regression this task must not cause: every other channel, and every
    batch built before it, mixes exactly as before - the rotation keys are
    null, not absent, and nothing is marked substituted."""
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        plan, annotated = mixed(Path(tmp) / "w", root, rotation=None)
        bed = plan["audio"]["bed"]
        assert bed["source"] == "supplied" and bed["substituted"] is None
        assert bed["rotation"] is None
        assert bed["ambient"]["source"] == ab.AMBIENT_SOURCE_CONVENTION
        assert bed["ambient"]["rotation_index"] is None
        assert bed["ambient"]["rotation_size"] is None
        record = ab.bed_record_fields(plan)
        assert set(record) == set(ab.BED_RECORD_KEYS)
        assert record["ambient_rotation_index"] is None
        assert record["ambient_rotation_size"] is None
        assert record["ambient_chosen_by"] is None
        assert record["bed_substituted"] is None
        assert annotated["bed"] == "ambient.wav", annotated


# --------------------------------------------------------------------------
# D. the substitution nobody heard
# --------------------------------------------------------------------------


def test_the_generated_bed_no_longer_plays_in_silence():
    """The fault the task was filed for: `example-film/2026-09-17T1901Z` shipped
    with the generator at -18 dB where the channel had chosen -25, and the only
    trace was a `source: "generated"` field that looks the same on an ordinary
    run. Both routes to the generator now carry a reason code - into the
    runlog, into the plan and into `05-video-editor.json`."""
    with tempfile.TemporaryDirectory() as tmp:
        # 1. the channel has no bed at all
        bare = ambtest.channel_root(tmp + "/bare")
        plan, annotated = mixed(Path(tmp) / "w1", bare, rotation=None)
        assert plan["audio"]["bed"]["source"] == "generated"
        assert plan["audio"]["bed"]["substituted"] == ab.BED_SUBSTITUTED_NO_CHANNEL_BED
        assert annotated["bed"] == "GENERATED no_channel_bed", annotated
        assert ab.bed_record_fields(plan)["bed_substituted"] == "no_channel_bed"

        # 2. the operator asked for the generator by hand, on a channel that
        #    has three beds ready
        root = rotating_root(tmp)
        plan, annotated = mixed(Path(tmp) / "w2", root, key="k",
                                argv_extra=("--music", "generated"))
        assert plan["audio"]["bed"]["substituted"] == ab.BED_SUBSTITUTED_OPERATOR
        assert annotated["bed"] == "GENERATED operator_forced_generated", annotated
        assert ab.bed_record_fields(plan)["bed_substituted"] == "operator_forced_generated"
        # and the level is still the generator's own, not the channel's: that
        # split is CF-0165's decision, re-examined and kept on 2026-09-21
        assert plan["audio"]["bed"]["bed_db"] == ab.DEFAULT_BED_DB
        assert plan["audio"]["bed"]["bed_db_source"] == ab.BED_DB_SOURCE_DEFAULT


def test_the_reason_codes_are_constants_and_the_annotation_is_one_shape():
    """Codes somebody typed twice in two spellings are codes nobody can grep
    the runlog for."""
    assert set(ab.BED_SUBSTITUTION_CODES) == {"no_channel_bed",
                                              "operator_forced_generated"}
    for code in ab.BED_SUBSTITUTION_CODES:
        assert ab.substitution_annotation(code) == f"GENERATED {code}"
    assert "bed_substituted" in ab.BED_RECORD_KEYS


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
