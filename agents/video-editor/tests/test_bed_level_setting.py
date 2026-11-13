#!/usr/bin/env python3
"""CF-0165: the bed's level is a channel setting, not a flag.

The user auditioned three levels on 2026-09-09 and chose -25 dB for
example-film's own ambient file. That choice lived in one command line:
`--bed-db` was `default=-18.0` in build_soundtrack.py, there was nowhere in
the channel config to write the answer down, and the next run would have
mixed at -18 again without anybody noticing until the video was finished.

What is locked here:

  * the level comes from `video_editor.ambient.bed_db`, and the plan says
    both what it was and where it came from (`bed_db_source`);
  * `--bed-db` still wins - it is how a level is auditioned, not where one is
    kept;
  * a channel without the key mixes at the number the flag used to default
    to, so nothing that exists today moves;
  * **the channel's number applies to the file the channel brought and not to
    the generator** (step 2). BED_TARGET_GAPS_DB / BED_TARGET_SPEECH_DB were
    calibrated on the generator's flat carpet; a brought-in file is
    structural, which is why the same number reads louder on it. A run forced
    back to the generator stays where CF-0025 measured it;
  * a key that is present and is not a level refuses by name instead of
    quietly mixing 7 dB louder than the channel asked for;
  * the number does what it says in the finished mix, measured through the
    real graph with qc_render.py's own instrument.

The fixtures here are test fixtures and nothing else - the same rule as
test_ambient_bed.py, whose channel_root()/mixed_with_channel() this file
reuses so that the two never drift apart on what a channel looks like.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

import ambient_bed as ab  # noqa: E402
import qc_render as qc  # noqa: E402

import test_ambient_bed as ambtest  # noqa: E402

CHANNEL_LEVEL_DB = -25.0  # what example-film chose, used here as a fixture


def mixed_at(tmp, video_editor=None, ambient="ambient.wav", argv_extra=(),
             music=None):
    """One real mix through the mixer, with a channel that may carry a level."""
    root = ambtest.channel_root(tmp, ambient=ambient, video_editor=video_editor)
    work = Path(tmp) / "work"
    work.mkdir(exist_ok=True)
    extra = tuple(argv_extra) + (("--music", music) if music else ())
    return ambtest.mixed_with_channel(work, root=root, channel="chan",
                                      argv_extra=extra)


# --------------------------------------------------------------------------
# where the number comes from
# --------------------------------------------------------------------------


def test_the_level_is_read_from_the_channel_config():
    """The mechanical half of the task: the number the user chose is in the
    channel config, the mixer obeys it, and the plan records both it and its
    provenance - a level nobody can trace is how the choice got lost once."""
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp, video_editor={"ambient": {"bed_db": CHANNEL_LEVEL_DB}})
        bed = plan["audio"]["bed"]
        assert bed["source"] == "supplied", bed
        assert bed["bed_db"] == CHANNEL_LEVEL_DB, bed
        assert bed["bed_db_source"] == ab.BED_DB_SOURCE_CONFIG, bed
        # the graph's own number is still the level plus the file's lift
        assert bed["bed_volume_db"] == round(CHANNEL_LEVEL_DB + bed["ambient"]["gain_db"], 3)


def test_the_flag_still_overrides_the_channel():
    """`--bed-db` is the debug flag it always was. It stays, it wins, and the
    plan says `cli` so a mix made while auditioning is never mistaken for the
    channel's decision."""
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp, video_editor={"ambient": {"bed_db": CHANNEL_LEVEL_DB}},
                           argv_extra=("--bed-db", "-16"))
        bed = plan["audio"]["bed"]
        assert bed["bed_db"] == -16.0, bed
        assert bed["bed_db_source"] == ab.BED_DB_SOURCE_CLI, bed


def test_a_channel_without_the_key_mixes_where_it_always_did():
    """The default is today's number, so every channel that has not been
    listened to yet keeps the level CF-0025 calibrated."""
    assert ab.DEFAULT_BED_DB == -18.0
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp)
        bed = plan["audio"]["bed"]
        assert bed["bed_db"] == ab.DEFAULT_BED_DB, bed
        assert bed["bed_db_source"] == ab.BED_DB_SOURCE_DEFAULT, bed


def test_the_loader_answers_off_the_config_alone():
    """The three answers, without a mix: flag, channel, default."""
    cfg = {"video_editor": {"ambient": {"bed_db": CHANNEL_LEVEL_DB}}}
    assert ab.bed_db(cfg) == (CHANNEL_LEVEL_DB, ab.BED_DB_SOURCE_CONFIG)
    assert ab.bed_db(cfg, cli_value=-16.0) == (-16.0, ab.BED_DB_SOURCE_CLI)
    assert ab.bed_db(None) == (ab.DEFAULT_BED_DB, ab.BED_DB_SOURCE_DEFAULT)
    # a channel that names a file but no level, and one with no video_editor
    assert ab.bed_db({"video_editor": {"ambient": {"path": "a.wav"}}})[1] == \
        ab.BED_DB_SOURCE_DEFAULT
    assert ab.bed_db({"channel_id": "chan"})[1] == ab.BED_DB_SOURCE_DEFAULT


# --------------------------------------------------------------------------
# the generator is not the file (step 2)
# --------------------------------------------------------------------------


def test_the_generator_keeps_its_own_calibrated_level():
    """A channel with a level but no file falls back to the generator, and the
    generator is mixed where CF-0025 put it - not at a number chosen by ear on
    a different sound. Otherwise a missing file would silently drop the
    generated bed 7 dB, straight through qc_render.py's floor."""
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp, ambient=None,
                           video_editor={"ambient": {"bed_db": CHANNEL_LEVEL_DB}})
        bed = plan["audio"]["bed"]
        assert bed["source"] == "generated", bed
        assert bed["bed_db"] == ab.DEFAULT_BED_DB, bed
        assert bed["bed_db_source"] == ab.BED_DB_SOURCE_DEFAULT, bed


def test_music_generated_ab_test_is_not_moved_by_the_channels_level():
    """`--music generated` is how the channel's file is A/B'd against the
    floor. It has to stay comparable to every measurement made on the
    generator, so the channel's number does not reach it either."""
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp, video_editor={"ambient": {"bed_db": CHANNEL_LEVEL_DB}},
                           music="generated")
        bed = plan["audio"]["bed"]
        assert bed["source"] == "generated", bed
        assert bed["bed_db"] == ab.DEFAULT_BED_DB, bed


def test_the_batch_record_carries_the_level_and_its_provenance():
    """The batch record is where a finished run is reviewed. Before CF-0165 it
    said which bed played and not at what level, so "was this mixed at the
    level the channel chose?" meant opening the plan on disk."""
    assert "bed_db" in ab.BED_RECORD_KEYS and "bed_db_source" in ab.BED_RECORD_KEYS
    with tempfile.TemporaryDirectory() as tmp:
        _, plan = mixed_at(tmp, video_editor={"ambient": {"bed_db": CHANNEL_LEVEL_DB}})
        record = ab.bed_record_fields(plan)
        assert record["bed_db"] == CHANNEL_LEVEL_DB, record
        assert record["bed_db_source"] == ab.BED_DB_SOURCE_CONFIG, record
    # a plan with no bed at all still answers in every key
    empty = ab.bed_record_fields({})
    assert set(empty) == set(ab.BED_RECORD_KEYS) and all(v is None for v in empty.values())


# --------------------------------------------------------------------------
# a broken level refuses
# --------------------------------------------------------------------------


def test_a_level_that_is_not_a_level_refuses_by_name():
    """ambient_path()'s doctrine, applied to the number: a channel that states
    a level and states it wrongly is a broken channel. Falling back would mix
    7 dB louder than the channel asked for, and nobody hears that until the
    video is finished."""
    for bad in ("-25", True, 5.0, -80.0, float("nan")):
        try:
            ab.bed_db({"video_editor": {"ambient": {"bed_db": bad}}})
        except ab.AmbientBedError as e:
            assert ab.CHANNEL_BED_DB_KEY in str(e), e
        else:
            raise AssertionError(f"{bad!r} was accepted as a bed level")


def test_a_broken_level_stops_the_mix_before_ffmpeg_runs():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mixed_at(tmp, video_editor={"ambient": {"bed_db": "quiet"}})
        except ab.AmbientBedError as e:
            assert ab.CHANNEL_BED_DB_KEY in str(e), e
        else:
            raise AssertionError("a mix ran with a bed level of 'quiet'")
        assert not (Path(tmp) / "work" / "mix.wav").exists(), \
            "the refusal came after the mix was already written"


# --------------------------------------------------------------------------
# the number does what it says, in the finished mix
# --------------------------------------------------------------------------


def test_the_channels_number_moves_the_finished_bed_by_what_it_says():
    """Measured, not asserted from the graph: the same file mixed at the
    default and at the channel's level, read back with qc_render.py's own
    instrument in the same window, has to differ by the difference between the
    two numbers. This is what makes -25 in a config a level and not a label.

    The tolerance is 1 dB: the duck is a compressor, so a quieter bed is
    ducked slightly less hard and does not move quite one-for-one."""
    levels = {}
    for setting in (None, CHANNEL_LEVEL_DB):
        with tempfile.TemporaryDirectory() as tmp:
            ve = None if setting is None else {"ambient": {"bed_db": setting}}
            mix, plan = mixed_at(tmp, video_editor=ve)
            measured = qc.bed_audibility_db(str(mix), plan)
            assert measured["window"] == "word_gaps", measured
            levels[setting] = measured["rms_db"]
    asked = ab.DEFAULT_BED_DB - CHANNEL_LEVEL_DB
    got = levels[None] - levels[CHANNEL_LEVEL_DB]
    assert abs(got - asked) < 1.0, (levels, asked, got)


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
