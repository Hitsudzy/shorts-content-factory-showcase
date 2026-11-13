#!/usr/bin/env python3
"""CF-0153: the bed is the channel's own file, and the generator is the floor.

What is locked here:

  * the file is found where the channel keeps its other assets, and a config
    that names one and has none refuses instead of falling back;
  * a file too short for the video *loops*, seamlessly - the seam neither
    clicks nor dips (section B, decided for looping);
  * whatever the file was mastered at, it arrives at the mixer's own targets,
    because it is levelled against the bed this same mix would have generated
    (section C) - measured through the real filter graph and read back with
    the gate's own instrument, exactly as test_bed_audibility.py does;
  * a channel with no file mixes byte-identically to before CF-0153;
  * the plan and the batch record say which file played (section E).

**The ambient files here are test fixtures and nothing else.** They are noise
shaped in three lines of numpy, generated inside each test. Decision 1 of
2026-09-08 is that a channel's real ambient is brought by the user by hand;
nothing in this repository may produce one, and a synthetic bed is not
evidence that a channel's bed sounds right - only that the machinery around it
does what it says.

The voice fixture, the plan fixture and the band meter are
test_bed_audibility.py's: the bed is judged against the narration, and two
files judging it against two different narrations would be two gates.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AGENT_ROOT / "tests"))

import ambient_bed as ab  # noqa: E402
import build_soundtrack as bs  # noqa: E402
import qc_render as qc  # noqa: E402
import write_batch_metadata  # noqa: E402
from common import BED_AUDIBLE_BAND_HZ  # noqa: E402
from repo_paths import VENV_PY3  # noqa: E402

# Imported under an alias on purpose: a name starting with `test_` in this
# module's globals would be picked up by the runner at the bottom and called.
import test_bed_audibility as bedtest  # noqa: E402

VENV_PY = Path(VENV_PY3)
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def ambient_wav(path, seconds=12.0, seed=5, kind="rain"):
    """A test fixture, not a channel asset (see the module docstring).

    `rain` is noise with the top and bottom rolled off and a slow drift over
    it - stationary texture with energy where a phone speaker radiates, which
    is the class of file this mechanism is for. `sub` is a 60 Hz sine: a file
    with nothing in the audible band at all, the CF-0025 defect as a file.
    `loud` is `rain` mastered 20 dB hotter, which is what the normaliser is
    for; `steady` is `rain` without the swell, for the seam measurement.
    """
    n = int(seconds * ab.SR)
    t = np.linspace(0, seconds, n, endpoint=False)
    if kind == "sub":
        return _write(path, 0.5 * np.sin(2 * np.pi * 60 * t))
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    f = np.fft.rfftfreq(n, 1 / ab.SR)
    env = (f / 300) / np.sqrt(1 + (f / 300) ** 2) / np.sqrt(1 + (f / 6000) ** 2)
    x = np.fft.irfft(spectrum * env, n=n)
    x /= np.abs(x).max() + 1e-9
    if kind != "steady":
        # a slow swell, so the fixture is not a stationary process the way a
        # test signal would be. `steady` leaves it out: the seam test measures
        # level against time, and a fixture that changes level on its own
        # would be measuring itself.
        x *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.11 * t)
    return _write(path, x * (0.9 if kind == "loud" else 0.09))


def _write(path, samples):
    bs.write_wav(path, samples)
    return Path(path)


def channel_root(tmp, channel_id="chan", ambient=None, video_editor=None):
    """A factory root with one channel in it: `channels/<id>.json` and the
    channel's own directory beside it, the layout end_card.py already reads."""
    root = Path(tmp) / "root"
    (root / "channels" / channel_id).mkdir(parents=True, exist_ok=True)
    cfg = {"channel_id": channel_id}
    if video_editor is not None:
        cfg["video_editor"] = video_editor
    (root / "channels" / f"{channel_id}.json").write_text(json.dumps(cfg))
    if ambient is not None:
        ambient_wav(root / "channels" / channel_id / ambient)
    return root


def mixed_with_channel(tmp, root=None, channel=None, argv_extra=(), gap_at=3.0):
    """One real mix through build_soundtrack.main(), with a channel to ask."""
    tmp = Path(tmp)
    words = bedtest.voice_wav(tmp / "voice.wav", gap_at=gap_at)
    plan = bedtest.plan_for(words)
    plan["audio"]["src"] = str(tmp / "voice.wav")
    (tmp / "plan.json").write_text(json.dumps(plan))
    argv = sys.argv
    sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"), str(tmp / "plan.json"),
                str(tmp / "mix.wav"),
                *(["--channel", str(channel)] if channel else []),
                *(["--root", str(root)] if root else []), *argv_extra]
    try:
        bs.main()
    finally:
        sys.argv = argv
    return tmp / "mix.wav", json.loads((tmp / "plan.json").read_text())


# --------------------------------------------------------------------------
# A. where the file lives
# --------------------------------------------------------------------------


def test_the_file_is_found_beside_the_channels_other_assets():
    """`channels/<channel_id>/ambient.<ext>` - the directory that already holds
    stance.json and ending.mp4 - and the extension order is the one the
    constant declares."""
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp, ambient="ambient.wav")
        cfg = json.loads((root / "channels" / "chan.json").read_text())
        path, source = ab.ambient_path(cfg, root)
        assert path == root / "channels" / "chan" / "ambient.wav", path
        assert source == ab.AMBIENT_SOURCE_CONVENTION
        # a second file later in AMBIENT_EXTS does not displace the first
        ambient_wav(root / "channels" / "chan" / "ambient.mp3")
        assert ab.ambient_path(cfg, root)[0].suffix == ".wav"


def test_a_channel_with_no_file_is_not_an_error():
    """Decision 2: no file is the channel that gets the generator, not a
    channel that is broken."""
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp)
        cfg = json.loads((root / "channels" / "chan.json").read_text())
        assert ab.ambient_path(cfg, root) == (None, None)
        assert ab.ambient_path({}, root) == (None, None)


def test_the_config_can_name_the_file_and_may_not_name_a_missing_one():
    """`video_editor.ambient.path`, resolved against the factory root when
    relative - the same shape as `video_editor.ending.path` (CF-0141). A
    channel that names a file it does not have stops the mix instead of
    quietly getting the fan noise the user rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp, ambient="ambient.wav",
                            video_editor={"ambient": {"path": "shared/rain.wav"}})
        (root / "shared").mkdir()
        ambient_wav(root / "shared" / "rain.wav")
        cfg = json.loads((root / "channels" / "chan.json").read_text())
        path, source = ab.ambient_path(cfg, root)
        assert path == root / "shared" / "rain.wav", path
        assert source == ab.AMBIENT_SOURCE_CONFIG
        (root / "shared" / "rain.wav").unlink()
        try:
            ab.ambient_path(cfg, root)
        except ab.AmbientBedError as e:
            assert "video_editor.ambient.path" in str(e), e
        else:
            raise AssertionError("a named file that is not there passed silently")


# --------------------------------------------------------------------------
# B. what happens to a file that is not as long as the video
# --------------------------------------------------------------------------


def test_a_short_file_loops_and_the_seam_neither_clicks_nor_dips():
    """Section B, decided for looping. The prepared bed is exactly as long as
    the composition, and its level is stationary across the seams: an
    equal-power crossfade neither leaves a step (a click) nor a 3 dB hole (the
    linear crossfade's breath, once per loop)."""
    with tempfile.TemporaryDirectory() as tmp:
        src_seconds, total = 12.0, 45.0
        src = ambient_wav(Path(tmp) / "ambient.wav", seconds=src_seconds, kind="steady")
        record = ab.prepare(src, total, Path(tmp) / "prepared.wav",
                            bs.bed(total), fade_out_seconds=0.0)
        assert record["loops"] >= 4, record
        assert record["crossfade_s"] == ab.AMBIENT_CROSSFADE_SECONDS
        prepared, sr = _read(Path(tmp) / "prepared.wav")
        assert sr == ab.SR
        assert abs(prepared.size / sr - total) < 0.01, prepared.size / sr
        # level over the body, in half-second windows, fades excluded
        body = prepared[int(2 * sr):]
        frames = body[:body.size // (sr // 2) * (sr // 2)].reshape(-1, sr // 2)
        rms = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-12)
        assert rms.max() - rms.min() < 1.5, (rms.max(), rms.min())
        # and the seams themselves, where a splice would show: a quarter of a
        # second centred on each crossfade has to read the same as the body
        # around it. Equal power is exactly the claim that it does.
        stride = int(src_seconds * sr) - int(ab.AMBIENT_CROSSFADE_SECONDS * sr)
        c = int(ab.AMBIENT_CROSSFADE_SECONDS * sr)
        whole = 20 * math.log10(math.sqrt(float(np.mean(body ** 2))))
        for k in range(1, record["loops"]):
            centre = k * stride + c // 2
            window = prepared[centre - sr // 8:centre + sr // 8]
            level = 20 * math.log10(math.sqrt(float(np.mean(window ** 2))))
            assert abs(level - whole) < 1.5, (k, level, whole)


def test_a_file_shorter_than_the_floor_is_refused_by_name():
    """The other half of section B. Under AMBIENT_MIN_SECONDS the file is not
    looped - it would repeat often enough under a 60 s narration to read as a
    pulse - and the refusal names the file, the length and the floor, before
    ffmpeg is asked to mix anything."""
    with tempfile.TemporaryDirectory() as tmp:
        src = ambient_wav(Path(tmp) / "ambient.wav", seconds=3.0)
        try:
            ab.prepare(src, 20.0, Path(tmp) / "prepared.wav", bs.bed(20.0))
        except ab.AmbientBedError as e:
            assert "3.00s" in str(e) and "8s" in str(e), e
        else:
            raise AssertionError("a 3 s file was accepted as a bed")
        assert not (Path(tmp) / "prepared.wav").exists(), \
            "the refusal came after something was already written"


def test_a_file_at_least_as_long_as_the_video_is_not_looped_at_all():
    with tempfile.TemporaryDirectory() as tmp:
        src = ambient_wav(Path(tmp) / "ambient.wav", seconds=30.0)
        record = ab.prepare(src, 20.0, Path(tmp) / "prepared.wav", bs.bed(20.0),
                            fade_out_seconds=0.0)
        assert record["loops"] == 1, record
        assert record["crossfade_s"] == 0.0, record


def test_a_file_that_is_not_audio_at_all_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "ambient.wav"
        bad.write_text("this is not a wav")
        try:
            ab.probe_ambient(bad)
        except ab.AmbientBedError as e:
            assert str(bad) in str(e), e
        else:
            raise AssertionError("a text file passed as an ambient bed")


# --------------------------------------------------------------------------
# C. the level
# --------------------------------------------------------------------------


def test_the_supplied_file_lands_where_the_generated_bed_lands():
    """Section C, through the real graph and the real gate. Two mixes of the
    same voice - one with the channel's file, one with the generator - and the
    bed has to read the same in both windows, at the targets the mixer states.
    Which is the whole point: the mix graph and qc_render.py's floors are
    untouched by CF-0153 (decision 3), and they can only stay untouched if the
    supplied file arrives at the level the generator arrives at."""
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp, ambient="ambient.wav")
        supplied_dir = Path(tmp) / "supplied"
        supplied_dir.mkdir()
        mix, plan = mixed_with_channel(supplied_dir, root=root, channel="chan")
        # CF-0695: the targets are levels in the graph's own output, so they
        # are read on the premaster the graph wrote. The delivered mix is that
        # premaster moved by one static gain to -14 LUFS, and on this synthetic
        # voice the limiter takes 1.7 dB off its peaks - a non-linearity the
        # under-speech window's voice subtraction then counts as bed (it read
        # 0.7 dB over premaster + gain). The floors below are still checked on
        # the delivered mix, which is what the gate reads.
        premaster = Path(mix).parent / "_premaster.wav"
        gaps = qc.bed_audibility_db(str(premaster), plan)
        assert gaps["window"] == "word_gaps", gaps
        assert abs(gaps["rms_db"] - bs.BED_TARGET_GAPS_DB) < 4.0, gaps
        stripped = json.loads(json.dumps(plan))
        stripped["words"] = []
        under = qc.bed_audibility_db(str(premaster), stripped)
        assert under["window"] == "under_speech", under
        # CF-0695: 5 dB under speech, not 4. The voice now enters the graph
        # through the stem compressor and keys the duck from there; an evened
        # envelope ducks the bed slightly less inside words (this synthetic
        # voice: -34.4 -> -33.5 dB, the target is -38).
        assert abs(under["rms_db"] - bs.BED_TARGET_SPEECH_DB) < 5.0, under
        gaps = qc.bed_audibility_db(str(mix), plan)
        under = qc.bed_audibility_db(str(mix), stripped)
        assert gaps["rms_db"] > qc.MIN_BED_RMS_DB and under["rms_db"] > qc.MIN_BED_DUCKED_RMS_DB


def test_a_file_mastered_20_db_hotter_lands_in_the_same_place():
    """The reason the normaliser exists: without it the finished level would
    be a property of how the user's file happened to be mixed."""
    levels = []
    for kind in ("rain", "loud"):
        with tempfile.TemporaryDirectory() as tmp:
            root = channel_root(tmp)
            ambient_wav(root / "channels" / "chan" / "ambient.wav", kind=kind)
            work = Path(tmp) / "work"
            work.mkdir()
            mix, plan = mixed_with_channel(work, root=root, channel="chan")
            levels.append(qc.bed_audibility_db(str(mix), plan)["rms_db"])
    assert abs(levels[0] - levels[1]) < 1.0, levels


def test_a_file_with_nothing_in_the_audible_band_is_refused():
    """A sub-bass-only file is the CF-0025 defect as a file, and lifting it to
    the target would only raise its own noise floor. Refused, with the ceiling
    named."""
    with tempfile.TemporaryDirectory() as tmp:
        src = ambient_wav(Path(tmp) / "ambient.wav", seconds=12.0, kind="sub")
        try:
            ab.prepare(src, 20.0, Path(tmp) / "prepared.wav", bs.bed(20.0))
        except ab.AmbientBedError as e:
            assert f"{ab.AMBIENT_MAX_GAIN_DB:.0f} dB" in str(e), e
        else:
            raise AssertionError("a 60 Hz sine was accepted as a bed")


# --------------------------------------------------------------------------
# The floor: a channel with no file
# --------------------------------------------------------------------------


# The energy of the difference between two mixes that have to be "the same
# mix", as dBFS. Not equal bytes: this graph is not bit-reproducible. Eight
# runs of the *identical* command were measured here, and five of them
# differed from the first on about 4 000 samples out of 352 800 - peak 0.014
# full scale, difference RMS -66.6 dB at worst, the other three bit-identical.
# So the run-to-run noise floor is -66 dB and the threshold is 11 dB over it.
# It still discriminates by a mile: swapping the generated bed for the
# channel's file moves the same measurement to about -30 dB, which the test
# below asserts so that this number cannot quietly grow until it means
# nothing.
SAME_MIX_RMS_DB = -55.0


def test_a_channel_without_a_file_mixes_as_it_did_before():
    """Decision 2 as a test. Four routes that must all be the same mix: no
    --channel at all (every caller that predates CF-0153), a channel that has
    no ambient file, --music generated on a channel that has one, and the
    bare-channel route again.

    "The same mix" is the energy of the difference, not equal bytes, because
    this graph is not bit-reproducible: two runs of the *identical* command
    through amix/sidechaincompress/alimiter differ here on a few hundred
    samples out of 352 800 (see SAME_MIX_RMS_DB). Equal bytes would be a test
    that fails at random on a machine under load. The resolution is checked
    rather than assumed: route 2, the channel's own file, has to read as a
    different mix by the same measurement.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp, ambient="ambient.wav")
        digests, plans = [], []
        for kwargs in ({}, {"root": root, "channel": "chan"},
                       {"root": root, "channel": "chan",
                        "argv_extra": ("--music", "generated")}):
            work = Path(tmp) / f"w{len(digests)}"
            work.mkdir()
            # the same voice fixture every time: voice_wav() is deterministic
            mix, plan = mixed_with_channel(work, **kwargs)
            digests.append(_read(mix)[0])
            plans.append(plan["audio"]["bed"])
        # route 2 is a channel with no file at all
        assert _same_mix(digests[0], digests[2]), "--music generated moved the mix"
        assert plans[0]["source"] == "generated" and plans[0]["ambient"] is None
        assert plans[2]["source"] == "generated" and plans[2]["ambient"] is None
        assert plans[1]["source"] == "supplied", "the channel's file was not used"
        assert not _same_mix(digests[0], digests[1]), \
            "the measurement cannot tell the channel's file from the generator"
        with tempfile.TemporaryDirectory() as tmp2:
            bare = channel_root(tmp2)
            work = Path(tmp2) / "w"
            work.mkdir()
            mix, plan = mixed_with_channel(work, root=bare, channel="chan")
            assert _same_mix(_read(mix)[0], digests[0]), \
                "a channel with no ambient file did not mix as it did before"
            assert plan["audio"]["bed"]["source"] == "generated"


# --------------------------------------------------------------------------
# E. provenance
# --------------------------------------------------------------------------


def test_the_plan_and_the_batch_record_name_the_file_that_played():
    with tempfile.TemporaryDirectory() as tmp:
        root = channel_root(tmp, ambient="ambient.wav")
        work = Path(tmp) / "work"
        work.mkdir()
        mix, plan = mixed_with_channel(work, root=root, channel="chan")
        bed = plan["audio"]["bed"]
        ambient = bed["ambient"]
        assert bed["source"] == "supplied"
        assert ambient["name"] == "ambient.wav"
        assert ambient["path"] == str((root / "channels" / "chan" / "ambient.wav").resolve())
        assert ambient["source"] == ab.AMBIENT_SOURCE_CONVENTION
        assert ambient["loops"] >= 1 and math.isfinite(ambient["gain_db"])
        assert bed["bed_volume_db"] == round(bed["bed_db"] + ambient["gain_db"], 3)

        record = ab.bed_record_fields(plan)
        assert set(record) == set(ab.BED_RECORD_KEYS)
        assert record["ambient_name"] == "ambient.wav"
        assert record["ambient_source"] == ab.AMBIENT_SOURCE_CONVENTION
        # and the shape write_batch_metadata.py puts on videos[]
        plan["blocks"], plan["style"] = [], "motion"
        video = write_batch_metadata.video_record(
            "s1", plan, str(mix), {"passed": True, "failures": [], "notes": []}, None)
        assert video["bed"] == record, video["bed"]
        # a plan that records no bed at all: the same six keys, all null
        empty = write_batch_metadata.video_record(
            "s2", {**plan, "audio": {}}, str(mix),
            {"passed": True, "failures": [], "notes": []}, None)
        assert set(empty["bed"]) == set(ab.BED_RECORD_KEYS)
        assert all(v is None for v in empty["bed"].values()), empty["bed"]


def test_the_two_modules_agree_on_the_sample_rate_and_the_band():
    """ambient_bed.py states SR itself to avoid an import cycle with its only
    caller; if the two ever disagreed the prepared bed would play at the wrong
    speed and the level would be measured in the wrong band."""
    assert ab.SR == bs.SR
    assert ab.band_rms_db(np.zeros(10)) == -math.inf
    assert BED_AUDIBLE_BAND_HZ == qc.BED_AUDIBLE_BAND_HZ


def _same_mix(a, b):
    if a.size != b.size:
        return False
    return 20 * math.log10(math.sqrt(float(np.mean((a - b) ** 2))) + 1e-12) < SAME_MIX_RMS_DB


def _read(path):
    import wave
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        data = data[::w.getnchannels()]  # CF-0695: the mix is dual-mono stereo; one channel is the mix
        return data.astype(np.float64) / 32768.0, w.getframerate()


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
