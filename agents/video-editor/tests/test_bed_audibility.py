#!/usr/bin/env python3
"""CF-0025: the background bed has to be audible, and the gate has to say so.

Two failures shipped together for a whole milestone and this file locks both.

  1. `qc_render.bed_audibility_db()` returned None whenever the narration had
     no inter-word pause over 0.4 s - four of the eight videos in
     2026-09-03T2037Z and 2026-08-31T2155Z - and None gated on nothing at all,
     so `bed_rms_db: null` shipped and nobody was told.
  2. It measured broadband, and 95.2% of the generated bed's energy sat under
     100 Hz, which no phone or laptop speaker radiates. A bed reading a healthy
     -32 dBFS on that meter was -58 dBFS in the band anyone can hear, so the
     meter and the user's ear disagreed and the meter won.

Everything here runs on synthetic audio through the *real* filter graph -
build_soundtrack.py's own main(), one ffmpeg mix per test, seconds each. The
voice is a formant-ish tone stack chopped into "words", because the defect is
about which band the energy is in: a bare sine at 300 Hz would let a bed that
is all sub-bass pass a highpassed measurement by luck.

The files are 8 s, not 3: the bed fades 1.5 s in and 1.5 s out, and the gate
measures the body between those fades, so a 3 s file has no body to measure
and would exercise the short-file fallback instead of the real path.
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

import build_soundtrack as bs  # noqa: E402
import qc_render as qc  # noqa: E402
from common import BED_AUDIBLE_BAND_HZ, BED_FADE_SECONDS  # noqa: E402
from repo_paths import VENV_PY3  # noqa: E402 - CF-0125: resolved against the main checkout

VENV_PY = Path(VENV_PY3)
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
SECONDS = 8.0
VOICE_RMS_DB = -22.0     # where the real voiceovers sit; the bed is judged against it


def voice_wav(path, gap_at=None, gap_seconds=1.0):
    """A synthetic voiceover and the word list that matches it.

    Words of 0.30 s separated by 0.06 s - so nothing that the gate would call
    a pause - unless `gap_at` asks for one longer gap, which is how the two
    measurement windows are told apart. The tone stack is 220/700/1800 Hz with
    a little noise: energy on both sides of the 200 Hz measurement edge, like
    speech, so a highpassed measurement is not trivially satisfied.
    """
    n = int(SECONDS * bs.SR)
    t = np.linspace(0, SECONDS, n, endpoint=False)
    rng = np.random.default_rng(3)
    carrier = (np.sin(2 * np.pi * 220 * t) + 0.7 * np.sin(2 * np.pi * 700 * t)
               + 0.4 * np.sin(2 * np.pi * 1800 * t) + 0.15 * rng.normal(0, 1, n))
    envelope = np.zeros(n)
    words, at, gap_done = [], 0.4, gap_at is None
    while at + 0.30 < SECONDS - 0.4:
        words.append({"word": f"w{len(words)}", "start": round(at, 3),
                      "end": round(at + 0.30, 3)})
        lo, hi = int(at * bs.SR), int((at + 0.30) * bs.SR)
        envelope[lo:hi] = np.hanning(hi - lo) ** 0.5
        at += 0.36
        if not gap_done and words[-1]["end"] >= gap_at:
            at += gap_seconds
            gap_done = True
    assert gap_done, "the requested pause did not fit in the fixture"
    samples = carrier * envelope
    rms = math.sqrt(float(np.mean(samples ** 2)))
    samples *= 10 ** (VOICE_RMS_DB / 20) / (rms + 1e-12)
    bs.write_wav(path, samples)
    return words


def plan_for(words, **extra):
    plan = {
        "audio": {"src": None, "duration": SECONDS},
        "duration": {"actual": SECONDS},
        "output": {"width": 1080, "height": 1920},
        "words": words,
        "blocks": [{"start": 0.0}, {"start": 3.0}, {"start": 5.5}],
        "notes": [],
    }
    plan.update(extra)
    return plan


def mixed(tmp, gap_at=None, plan_extra=None, argv_extra=(), bed_samples=None):
    """One real mix: synthetic voice -> build_soundtrack.main() -> mix.wav.
    Returns (mix path, plan path, the plan as build_soundtrack left it)."""
    tmp = Path(tmp)
    words = voice_wav(tmp / "voice.wav", gap_at=gap_at)
    plan = plan_for(words, **(plan_extra or {}))
    plan["audio"]["src"] = str(tmp / "voice.wav")
    (tmp / "plan.json").write_text(json.dumps(plan))
    argv = sys.argv
    sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                str(tmp / "plan.json"), str(tmp / "mix.wav"), *argv_extra]
    # `bed_samples` replaces the *generator*, not the --music input. It used
    # to go in through --music, and CF-0153 took that route away: a supplied
    # file is now looped and normalised to the generated bed's own level in
    # the audible band (ambient_bed.prepare()), so a bed pushed through it
    # arrives at the level the mixer aims at whatever its spectrum was - which
    # is the point of the normaliser and the opposite of what the one caller
    # here needs. Patching bed() is also the more literal reading of that
    # caller's own sentence: "the same graph, the same level, the old
    # generator".
    original_bed = bs.bed
    if bed_samples is not None:
        bs.bed = lambda seconds, **kw: np.array(bed_samples[:int(seconds * bs.SR)])
    try:
        bs.main()
    finally:
        sys.argv = argv
        bs.bed = original_bed
    return tmp / "mix.wav", tmp / "plan.json", json.loads((tmp / "plan.json").read_text())


def band_db(path, spans=None):
    """RMS in dBFS above BED_AUDIBLE_BAND_HZ, by the gate's own instrument."""
    x = qc._audible_band(qc._samples(str(path)))
    if spans:
        parts = [x[int(a * qc.MEASURE_SR):int(b * qc.MEASURE_SR)] for a, b in spans]
        x = np.concatenate([p for p in parts if p.size])
    return qc._power_db(float(np.mean(x ** 2)))


def old_bed(seconds, seed=7):
    """The bed exactly as build_soundtrack.py generated it before CF-0025: one
    low voicing and a noise layer smoothed with a 512-tap boxcar (a low-pass
    whose first null is at 86 Hz). Kept here, and only here, so the gate can be
    shown to fail the thing it exists to catch rather than only to pass the
    thing that replaced it."""
    rng = np.random.default_rng(seed)
    n = int(seconds * bs.SR)
    t = np.linspace(0, seconds, n, endpoint=False)
    out = np.zeros(n)
    for i, semi in enumerate(bs.SEMITONES):
        f = bs.ROOT_HZ * (2 ** (semi / 12))
        detune = 1 + rng.uniform(-0.0015, 0.0015)
        drift = 0.55 + 0.45 * np.sin(2 * np.pi * (0.031 + i * 0.017) * t + i)
        out += (0.5 ** i) * drift * np.sin(2 * np.pi * f * detune * t)
        out += 0.22 * (0.5 ** i) * drift * np.sin(2 * np.pi * f * 2 * detune * t)
    noise = np.convolve(rng.normal(0, 1, n), np.ones(512) / 512, mode="same")
    out += 0.35 * noise / (np.abs(noise).max() + 1e-9)
    out /= np.abs(out).max() + 1e-9
    fade = int(bs.SR * BED_FADE_SECONDS)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


# --------------------------------------------------------------------------
# 1. The gate always produces a number, and says which window produced it.
# --------------------------------------------------------------------------

def test_a_narration_with_no_pause_is_still_measured():
    """The live example's failure: no inter-word gap over 0.4 s anywhere, so
    the old gate returned None and checked nothing. Now it falls back to the
    ducked body under speech, names that window, and clears its own floor."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, _, plan = mixed(tmp)
        assert not qc._word_gaps(plan, (BED_FADE_SECONDS, SECONDS - BED_FADE_SECONDS)), \
            "the fixture is supposed to have no gap the gate would use"
        bed = qc.bed_audibility_db(str(mix), plan)
        assert bed is not None, "a mixed bed must never measure as None"
        assert bed["window"] == "under_speech", bed
        assert bed["voice_subtracted"] is True, bed
        assert math.isfinite(bed["rms_db"]), bed
        assert bed["floor_db"] == qc.MIN_BED_DUCKED_RMS_DB, bed
        assert bed["rms_db"] > qc.MIN_BED_DUCKED_RMS_DB, bed


def test_a_narration_with_a_pause_is_measured_in_the_pause():
    """Where there is a real gap, that is still the window - it is where a
    listener notices the bed, and the duck has released into it."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, _, plan = mixed(tmp, gap_at=3.0)
        bed = qc.bed_audibility_db(str(mix), plan)
        assert bed["window"] == "word_gaps", bed
        assert bed["voice_subtracted"] is False, bed
        assert bed["floor_db"] == qc.MIN_BED_RMS_DB, bed
        assert bed["rms_db"] > qc.MIN_BED_RMS_DB, bed


def test_the_gap_window_reads_louder_than_the_ducked_one():
    """The duck is the difference between the two floors, so the two windows
    have to differ by roughly the duck's depth on the same material - if they
    did not, one of the two floors would be arbitrary."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, _, plan = mixed(tmp, gap_at=3.0)
        gaps = qc.bed_audibility_db(str(mix), plan)
        stripped = dict(plan, words=[dict(w) for w in plan["words"]])
        # the same mix, measured as if the narration had no gap
        for i, w in enumerate(stripped["words"][1:], 1):
            w["start"] = stripped["words"][i - 1]["end"] + 0.06
            w["end"] = w["start"] + 0.30
        ducked = qc.bed_audibility_db(str(mix), stripped)
        assert ducked["window"] == "under_speech", ducked
        assert gaps["rms_db"] > ducked["rms_db"], (gaps, ducked)
        assert (qc.MIN_BED_RMS_DB - qc.MIN_BED_DUCKED_RMS_DB) == 6.0, \
            "the two floors are one duck apart on purpose"


# --------------------------------------------------------------------------
# 2. A bed that was mixed and cannot be measured is a failure, not a null.
# --------------------------------------------------------------------------

def test_null_with_a_declared_bed_fails_qc():
    """`bed_rms_db: null` is the symptom the task was filed on. With
    audio.bed on the plan - which build_soundtrack.py now writes - a gate that
    cannot produce a number has to say so out loud instead of passing."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, plan_path, plan = mixed(tmp)
        assert plan["audio"]["bed"]["source"] == "generated", plan["audio"]
        # No gap to sample and no voice on disk to subtract: unmeasurable.
        # (CF-0695: neither the bare voice nor the compressed stem the mix
        # was built on - the gate subtracts the stem when it is there.)
        plan["audio"]["src"] = str(Path(tmp) / "gone.wav")
        Path(plan["audio"]["loudness"]["voice"]["path"]).unlink()
        Path(plan_path).write_text(json.dumps(plan))
        assert qc.bed_audibility_db(str(mix), plan) is None
        out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix),
                              str(plan_path), "--audio-only", "--json"],
                             capture_output=True, text=True)
        result = json.loads(out.stdout)
        assert result["passed"] is False, result
        assert any("bed not measured" in f for f in result["failures"]), result["failures"]
        assert result["measured"]["bed_rms_db"] is None
        assert result["measured"]["bed_declared"] is True
        assert qc.failed_gates(result["failures"]) == ["bed"], result["failures"]


def test_a_plan_with_no_bed_is_not_failed_for_one():
    """The other half: nothing here invents a bed. A plan that never had one
    measured is not accused of having lost it."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, plan_path, plan = mixed(tmp)
        del plan["audio"]["bed"]
        plan["audio"]["src"] = str(Path(tmp) / "gone.wav")
        Path(plan_path).write_text(json.dumps(plan))
        out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix),
                              str(plan_path), "--audio-only", "--json"],
                             capture_output=True, text=True)
        result = json.loads(out.stdout)
        assert not any("bed" in f for f in result["failures"]), result["failures"]
        assert result["measured"]["bed_declared"] is False
        # and it is not measured either: measuring means decoding the plan's
        # voice, and there is nothing here for the answer to be compared to
        assert result["measured"]["bed_rms_db"] is None
        assert result["measured"]["bed_rms_window"] is None
        assert any("no bed is recorded on the plan" in n for n in result["notes"]), \
            result["notes"]


# --------------------------------------------------------------------------
# 3. The levels themselves, through the real graph.
# --------------------------------------------------------------------------

def test_the_bed_hits_its_targets_through_the_real_graph():
    """The mixer's own targets, measured on the mix it produced. The tolerance
    is 4 dB because the synthetic voice is not one of the eight real ones the
    targets were measured on - the point is the level, not a golden number."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, _, plan = mixed(tmp, gap_at=3.0)
        body = (BED_FADE_SECONDS, SECONDS - BED_FADE_SECONDS)
        # CF-0695: the targets describe the bed in the graph's own output, so
        # they are read on the premaster the graph wrote; the loudness pass
        # then moves the whole mix by one static gain and writes it as
        # dual-mono stereo (which a mono fold-down reads 3 dB hotter).
        mix = Path(mix).parent / "_premaster.wav"
        gain = 0.0
        gaps = qc.bed_audibility_db(str(mix), plan)
        assert abs(gaps["rms_db"] - gain - bs.BED_TARGET_GAPS_DB) < 4.0, (gaps, gain)
        stripped = dict(plan, words=[{"word": "x", "start": w["start"], "end": w["end"]}
                                     for w in plan["words"]])
        stripped["words"] = [dict(w) for w in stripped["words"]]
        for i, w in enumerate(stripped["words"][1:], 1):
            w["start"] = stripped["words"][i - 1]["end"] + 0.06
            w["end"] = w["start"] + 0.30
        under = qc.bed_audibility_db(str(mix), stripped)
        # CF-0695: 5 dB under speech, not 4. The voice now enters the graph
        # through the stem compressor and keys the duck from there; an evened
        # envelope ducks the bed slightly less inside words (this synthetic
        # voice: -34.4 -> -33.5 dB, the target is -38).
        assert abs(under["rms_db"] - gain - bs.BED_TARGET_SPEECH_DB) < 5.0, (under, gain)
        assert body[1] > body[0]


def test_the_bed_before_cf0025_fails_the_gate():
    """The regression this file exists for. The same graph, the same level, the
    old generator - and it has to fail, or the gate is decorative. Measured on
    the shipped batches the difference is 15 to 26 dB; here it only has to be
    on the wrong side of the floor."""
    with tempfile.TemporaryDirectory() as tmp:
        old = old_bed(SECONDS)
        mix, _, plan = mixed(tmp, gap_at=3.0, bed_samples=old,
                             argv_extra=("--bed-db", "-16"))
        bed = qc.bed_audibility_db(str(mix), plan)
        assert bed["window"] == "word_gaps", bed
        assert bed["rms_db"] < qc.MIN_BED_RMS_DB, \
            f"the pre-CF-0025 bed reads {bed['rms_db']:.1f} dB and would pass"


def test_the_generated_bed_puts_real_energy_in_the_audible_band():
    """The generator's own invariant, independent of any mix: a fifth of the
    bed's power has to be in the band a speaker can radiate. The old bed had
    0.26% there, which is the whole defect in one number."""
    def share_above_band(samples):
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(samples.size))) ** 2
        freqs = np.fft.rfftfreq(samples.size, 1 / bs.SR)
        return float(spectrum[freqs >= BED_AUDIBLE_BAND_HZ].sum() / spectrum.sum())

    now, before = bs.bed(SECONDS), old_bed(SECONDS)
    assert share_above_band(now) > 0.20, share_above_band(now)
    assert share_above_band(before) < 0.02, share_above_band(before)


# --------------------------------------------------------------------------
# 4. The neighbours: nothing else about the mix moved.
# --------------------------------------------------------------------------

def test_the_end_card_fade_still_ends_quiet():
    """CF-0117: under the end card there is no voice, the duck releases and the
    bed comes up - then fades to nothing across the card. A louder bed must not
    turn the tail of every video into an audible cut-off."""
    with tempfile.TemporaryDirectory() as tmp:
        card = {"start_s": SECONDS, "seconds": 2.0, "text": "x",
                "text_source": "t", "channel_name": "c", "variant": "typographic",
                "logo_path": None}
        mix, _, plan = mixed(tmp, gap_at=3.0, plan_extra={
            "end_card": card, "duration": {"actual": SECONDS, "composition": SECONDS + 2.0}})
        total = qc.media_duration(str(mix))
        assert abs(total - (SECONDS + 2.0)) < 0.05, total
        tail = band_db(mix, [(total - 0.25, total)])
        assert tail <= -40.0, f"the mix ends at {tail:.1f} dB, not faded out"
        # and the card itself is not silent - the bed is up under it
        under_card = band_db(mix, [(SECONDS + 0.2, SECONDS + 1.0)])
        assert under_card > qc.MIN_BED_RMS_DB, under_card


def test_the_four_input_graph_still_carries_the_bed():
    """CF-0068's fourth input ducks the bed a second time. None of the eight
    real plans places a sound, so this is the only place the louder bed meets
    that graph: the sound is still heard over its slot, and the bed still
    clears its floor with the extra duck on top of the voice's."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        hit = np.zeros(int(1.2 * bs.SR))
        t = np.linspace(0, 1.2, hit.size, endpoint=False)
        hit += 0.8 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 3)
        bs.write_wav(tmp / "hit.wav", hit)
        sound = {"sound": {"placed": [{"beat_id": "b1", "asset_id": "hit",
                                       "file": str(tmp / "hit.wav"),
                                       "at_seconds": 3.2, "duration_s": 1.2,
                                       "block_index": 1}]}}
        mix, _, plan = mixed(tmp, gap_at=3.0, plan_extra=sound)
        assert (tmp / "_inserts.wav").exists(), "the fourth input was not built"
        bed = qc.bed_audibility_db(str(mix), plan)
        assert bed["rms_db"] > bed["floor_db"], bed
        heard = qc.sound_audibility_db(str(mix), plan)
        assert len(heard) == 1 and heard[0]["rms_db"] > qc.MIN_SOUND_RMS_DB, heard


def test_audio_only_is_narrower_and_says_so():
    """--audio-only exists so a mix can be checked without a render. It must
    not become a second, looser verdict: the same floors, the picture gates
    skipped, and the result carries the flag that says which run it was."""
    with tempfile.TemporaryDirectory() as tmp:
        mix, plan_path, _ = mixed(tmp, gap_at=3.0)
        out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix),
                              str(plan_path), "--audio-only", "--json"],
                             capture_output=True, text=True)
        result = json.loads(out.stdout)
        assert result["audio_only"] is True, result
        assert result["passed"] is True, result["failures"]
        assert result["measured"]["bed_rms_window"] == "word_gaps"
        assert result["measured"]["bed_rms_floor_db"] == qc.MIN_BED_RMS_DB
        # the picture gates did not run and did not invent results
        assert result["measured"]["frozen_clip_blocks"] == []
        assert result["measured"]["caption_contrast"] is None
        # a mix peaks at 0 dBFS by construction; that is a note here, not a fail
        assert not any("clipping" in f for f in result["failures"]), result["failures"]


def test_an_audio_only_run_does_not_close_a_render_attempt():
    """--audio-only checks a mix; it is not a verdict on a render. Run on a
    real batch's plan it must leave the attempt ledger exactly as it found it,
    or a re-measured mix would mark an attempt finished with nothing rendered."""
    import attempts

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        batch = root / "pipeline" / "chan" / "b1"
        work = batch / "work" / "vid"
        work.mkdir(parents=True)
        mix, plan_path, _ = mixed(work, gap_at=3.0)
        attempts.begin(batch, "vid", "first")
        before = json.dumps(attempts.load(batch, "vid"), sort_keys=True)
        out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix),
                              str(plan_path), "--audio-only", "--json"],
                             capture_output=True, text=True)
        assert json.loads(out.stdout)["passed"] is True, out.stdout[-500:]
        assert json.dumps(attempts.load(batch, "vid"), sort_keys=True) == before, \
            "an audio-only run wrote to the attempt ledger"
        assert "attempt" not in json.loads(out.stdout)


def test_the_batch_record_carries_the_bed_measurement():
    """The live example read `bed_rms_db: null` in all four entries of the
    batch report while two of the four had a real number in the slug's own
    qc.log - the merged record never carried the field at all. It does now, so
    absent, null and measured are three visibly different things."""
    import write_batch_metadata

    with tempfile.TemporaryDirectory() as tmp:
        mix, plan_path, plan = mixed(tmp, gap_at=3.0)
        out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix),
                              str(plan_path), "--audio-only", "--json"],
                             capture_output=True, text=True)
        result = json.loads(out.stdout)
        # video_record() reads the asset side of every block; the mix is
        # already built, so the blocks have done their job here.
        plan["blocks"], plan["style"] = [], "motion"
        record = write_batch_metadata.video_record("s1", plan, str(mix), result, None)
        bed = record["qc"]["bed"]
        assert bed["bed_declared"] is True, bed
        assert bed["bed_rms_window"] == "word_gaps", bed
        assert bed["bed_rms_floor_db"] == qc.MIN_BED_RMS_DB, bed
        assert bed["bed_rms_db"] > qc.MIN_BED_RMS_DB, bed
        # and a report with no measurement at all still has the four keys
        empty = write_batch_metadata.video_record(
            "s2", plan, str(mix), {"passed": True, "failures": [], "notes": []}, None)
        assert set(empty["qc"]["bed"]) == set(bed) and \
            all(v is None for v in empty["qc"]["bed"].values())


def test_the_two_modules_agree_on_where_the_band_starts():
    """The mixer aims at a target and the gate reads a floor; if they measured
    in different bands the pair would be meaningless. One constant, one home."""
    assert bs.BED_AUDIBLE_BAND_HZ is BED_AUDIBLE_BAND_HZ
    assert qc.BED_AUDIBLE_BAND_HZ is BED_AUDIBLE_BAND_HZ
    assert bs.BED_TARGET_GAPS_DB > qc.MIN_BED_RMS_DB
    assert bs.BED_TARGET_SPEECH_DB > qc.MIN_BED_DUCKED_RMS_DB


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
