"""CF-0695: every finished video lands at -14 LUFS / true peak <= -1 dBTP,
by a static gain, on every channel (the user's Q35, 2026-10-12).

What is pinned here, all on synthetic audio made by ffmpeg / numpy in a temp
dir (nothing live, nothing on the network):

  * a quiet mix is raised to the target, a loud one lowered, and the true
    peak ends up at or under the ceiling either way;
  * the loudness range is not compressed - it is a gain, not loudnorm (the
    preview loudnorm took LRA 11.9 -> 5.6 LU);
  * a mix that would need the limiter to take more than 4 dB off its peaks
    is brought only as far as that cap and the shortfall is recorded;
  * the channel key `video_editor.loudness` is read, absent means -14/-1, and
    a broken value refuses by name before anything is mixed;
  * build_soundtrack.py records before/after/gain on the plan and its mix
    measures at the target; the ending clip gets a matching static volume and
    the render wires it to EndCard;
  * qc_render.py measures the finished file and notes a miss.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
RENDER_SRC = AGENT_ROOT / "render" / "src"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import build_soundtrack as bs  # noqa: E402
import loudness  # noqa: E402
from repo_paths import VENV_PY3  # noqa: E402

import test_ambient_bed as ambtest  # noqa: E402
import test_bed_audibility as bedtest  # noqa: E402

PY = str(VENV_PY3) if Path(VENV_PY3).exists() else sys.executable
SR = 44100


def _wav(path, samples):
    """float samples in [-1, 1] -> 16-bit mono wav at SR. Every fixture here
    stays under 0 dBFS, so 16 bits lose nothing a loudness meter would see."""
    import wave
    x = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


def _speechish(seconds=12.0, level=0.05, seed=3):
    """A tone stack gated into 0.3 s 'words' - speech-like crest and gating."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    carrier = (np.sin(2 * np.pi * 220 * t) + 0.6 * np.sin(2 * np.pi * 700 * t)
               + 0.3 * np.sin(2 * np.pi * 1800 * t) + 0.1 * rng.standard_normal(n))
    gate = ((t % 0.36) < 0.30).astype(float)
    return level * carrier * gate


def _dynamic(seconds=24.0):
    """Alternating loud and quiet 4 s passages - a real loudness range."""
    x = _speechish(seconds, level=0.08)
    t = np.arange(x.size) / SR
    x[(t // 4) % 2 == 1] *= 0.12          # -18 dB passages
    return x


def _peak_ok(got, ceiling=-1.0):
    """The mix is the file the render plays as it is (dual-mono stereo), so
    its own true peak is the delivered one."""
    return got["true_peak_db"] <= ceiling


def _master(tmp, samples, target=-14.0, tp=-1.0):
    src = _wav(Path(tmp) / "pre.wav", samples)
    out = Path(tmp) / "out.wav"
    rec = loudness.master(src, out, target, tp, SR, seconds=len(samples) / SR)
    return rec, loudness.measure(out)


# --------------------------------------------------------------------------
# the pass itself
# --------------------------------------------------------------------------


def test_a_quiet_mix_is_raised_to_the_target():
    with tempfile.TemporaryDirectory() as tmp:
        rec, got = _master(tmp, _speechish(level=0.02))
        assert rec["before"]["integrated_lufs"] < -20, rec
        assert rec["gain_db"] > 5, rec
        assert abs(got["integrated_lufs"] - -14.0) <= 0.5, got
        assert _peak_ok(got), got
        assert rec["shortfall_db"] == 0.0, rec


def test_a_loud_mix_is_lowered_to_the_target():
    with tempfile.TemporaryDirectory() as tmp:
        rng = np.random.default_rng(1)
        hot = np.clip(0.5 * rng.standard_normal(int(10 * SR)), -0.97, 0.97)
        rec, got = _master(tmp, hot)
        assert rec["before"]["integrated_lufs"] > -10, rec
        assert rec["gain_db"] < -3, rec
        assert abs(got["integrated_lufs"] - -14.0) <= 0.5, got
        assert _peak_ok(got), got


def test_the_loudness_range_is_not_compressed():
    """A static gain moves every passage by the same number, so the range
    between the loud and quiet passages survives - loudnorm's dynamic mode
    took 11.9 LU to 5.6 LU on the preview."""
    with tempfile.TemporaryDirectory() as tmp:
        rec, got = _master(tmp, _dynamic())
        assert rec["before"]["lra_lu"] > 10, rec["before"]
        assert abs(got["lra_lu"] - rec["before"]["lra_lu"]) <= 1.0, (rec["before"], got)
        assert abs(got["integrated_lufs"] - -14.0) <= 0.5, got


def test_the_limiter_cap_records_a_shortfall_instead_of_squashing():
    """A quiet bed with sparse full-scale clicks: reaching -14 would need the
    limiter to take ~20 dB off the clicks. It takes at most the cap, the mix
    lands short, and the record says by how much."""
    with tempfile.TemporaryDirectory() as tmp:
        x = _speechish(level=0.01)
        for at in np.arange(0.5, 11.5, 1.0):
            i = int(at * SR)
            x[i:i + 40] = 0.95
        rec, got = _master(tmp, x)
        assert rec["shortfall_db"] > 3.0, rec
        assert rec["limiter_gr_db"] <= loudness.MAX_LIMITER_GR_DB + 0.05, rec
        assert got["integrated_lufs"] < -14.0 - 1.0, got
        assert _peak_ok(got), got
        assert loudness.qc_verdict(got, -14.0, -1.0, rec["shortfall_db"]), \
            "a capped mix should read as a miss to QC"


def test_a_channel_target_is_honoured():
    with tempfile.TemporaryDirectory() as tmp:
        rec, got = _master(tmp, _speechish(level=0.05), target=-16.0, tp=-2.0)
        assert abs(got["integrated_lufs"] - -16.0) <= 0.5, got
        assert _peak_ok(got, -2.0), got


# --------------------------------------------------------------------------
# the key
# --------------------------------------------------------------------------


def test_the_default_when_the_key_is_absent():
    for cfg in (None, {}, {"video_editor": {}}, {"video_editor": {"loudness": {}}}):
        assert loudness.settings(cfg) == (-14.0, -1.0, loudness.SOURCE_DEFAULT), cfg


def test_the_key_is_read_and_a_half_block_keeps_the_other_default():
    cfg = {"video_editor": {"loudness": {"target_lufs": -16}}}
    assert loudness.settings(cfg) == (-16.0, -1.0, loudness.SOURCE_CONFIG)
    cfg = {"video_editor": {"loudness": {"true_peak_db": -2, "note": "why"}}}
    assert loudness.settings(cfg) == (-14.0, -2.0, loudness.SOURCE_CONFIG)


def test_a_broken_value_refuses_by_name():
    for block in ("-14", {"target_lufs": "loud"}, {"target_lufs": 3},
                  {"true_peak_db": 1.5}, {"target_lufs": True}):
        try:
            loudness.settings({"video_editor": {"loudness": block}})
        except loudness.LoudnessConfigError as e:
            assert loudness.CHANNEL_LOUDNESS_KEY in str(e), e
        else:
            raise AssertionError(f"accepted {block!r}")


def test_a_broken_key_stops_the_mix_before_ffmpeg_runs():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav",
                                    video_editor={"loudness": {"target_lufs": "loud"}})
        work = Path(tmp) / "work"
        work.mkdir()
        try:
            ambtest.mixed_with_channel(work, root=root, channel="chan")
        except loudness.LoudnessConfigError:
            pass
        else:
            raise AssertionError("a mix ran with a target of 'loud'")
        assert not (work / "mix.wav").exists()
        assert not (work / "_premaster.wav").exists()


# --------------------------------------------------------------------------
# through build_soundtrack.py
# --------------------------------------------------------------------------


def test_the_soundtrack_lands_at_the_target_and_records_it():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        work = Path(tmp) / "work"
        work.mkdir()
        mix, plan = ambtest.mixed_with_channel(work, root=root, channel="chan")
        rec = plan["audio"]["loudness"]
        for key in ("before", "after", "gain_db", "limiter_gr_db", "shortfall_db",
                    "target_lufs", "true_peak_db", "source", "ending", "voice"):
            assert key in rec, (key, rec)
        assert rec["source"] == loudness.SOURCE_DEFAULT
        assert rec["ending"] is None              # no clip ending in this plan
        got = loudness.measure(mix)
        assert abs(got["integrated_lufs"] - -14.0) <= 0.5, got
        assert _peak_ok(got), got
        # the voice went in compressed, and the stem is on disk for QC
        assert rec["voice"]["path"] == str(work / "_voice.wav")
        assert (work / "_voice.wav").exists()
        # the premaster is the graph's own output, kept beside the mix,
        # measured as the render will play it (both channels)
        pre = loudness.measure(work / "_premaster.wav", dualmono=True)
        assert abs(pre["integrated_lufs"] - rec["before"]["integrated_lufs"]) < 0.11


def test_the_channel_key_reaches_the_mix():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav",
                                    video_editor={"loudness": {"target_lufs": -18}})
        work = Path(tmp) / "work"
        work.mkdir()
        mix, plan = ambtest.mixed_with_channel(work, root=root, channel="chan")
        assert plan["audio"]["loudness"]["source"] == loudness.SOURCE_CONFIG
        assert abs(loudness.measure(mix)["integrated_lufs"] - -18.0) <= 0.5


def test_the_ending_clip_gets_a_matching_static_volume():
    """The clip's own track is played by the render over silence in our mix;
    it is levelled to the same target by one volume number. A hot clip is
    turned down; a quiet clip is turned up only as far as its own true peak
    allows (no limiter in the render)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        hot = _wav(tmp / "hot.wav", 0.9 * np.sin(2 * np.pi * 300 * np.arange(5 * SR) / SR))
        rec = loudness.ending_level(hot, -14.0, -1.0)
        assert rec["gain_db"] < 0 and rec["volume"] < 1.0, rec
        assert abs(rec["before"]["integrated_lufs"] + rec["gain_db"] - -14.0) <= 0.2, rec
        # quiet but peaky: the gain stops at the peak
        x = 0.01 * np.sin(2 * np.pi * 300 * np.arange(5 * SR) / SR)
        x[SR:SR + 30] = 0.7
        quiet = _wav(tmp / "quiet.wav", x)
        rec = loudness.ending_level(quiet, -14.0, -1.0)
        assert rec["shortfall_db"] > 0, rec
        assert rec["before"]["true_peak_db"] + rec["gain_db"] <= rec["ceiling_db"] + 0.01, rec


def test_the_soundtrack_records_the_ending_volume():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        words = bedtest.voice_wav(tmp / "voice.wav", gap_at=3.0)
        clip = _wav(tmp / "ending.wav",
                    0.9 * np.sin(2 * np.pi * 300 * np.arange(2 * SR) / SR))
        plan = bedtest.plan_for(words)
        plan["audio"]["src"] = str(tmp / "voice.wav")
        start = bedtest.SECONDS
        plan["end_card"] = {"start_s": start, "seconds": 2.0, "variant": "clip",
                            "path": str(clip), "text": None}
        plan["duration"]["composition"] = start + 2.0
        (tmp / "plan.json").write_text(json.dumps(plan))
        argv = sys.argv
        sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                    str(tmp / "plan.json"), str(tmp / "mix.wav")]
        try:
            bs.main()
        finally:
            sys.argv = argv
        rec = json.loads((tmp / "plan.json").read_text())["audio"]["loudness"]
        assert rec["ending"] and rec["ending"]["volume"] < 1.0, rec
        assert rec["ending"]["path"] == str(clip)
        # levelled to where the mix landed (the target, when it is reached)
        assert rec["ending"]["target_lufs"] == min(-14.0, rec["after"]["integrated_lufs"])
        # the mix itself is still at the target: the silent ending interval
        # is gated out of the integrated measurement
        assert abs(loudness.measure(tmp / "mix.wav")["integrated_lufs"] - -14.0) <= 0.5


def test_a_short_mix_takes_the_ending_down_with_it():
    """When the limiter cap leaves the mix short of the target, the ending is
    levelled to the mix's landed loudness rather than to the target - one
    level through the video, no jump in the last seconds."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        words = bedtest.voice_wav(tmp / "voice.wav", gap_at=3.0)
        clip = _wav(tmp / "ending.wav",
                    0.9 * np.sin(2 * np.pi * 300 * np.arange(2 * SR) / SR))
        plan = bedtest.plan_for(words)
        plan["audio"]["src"] = str(tmp / "voice.wav")
        start = bedtest.SECONDS
        plan["end_card"] = {"start_s": start, "seconds": 2.0, "variant": "clip",
                            "path": str(clip), "text": None}
        plan["duration"]["composition"] = start + 2.0
        (tmp / "plan.json").write_text(json.dumps(plan))
        saved = loudness.MAX_LIMITER_GR_DB, loudness.ENCODE_MARGIN_DB
        # force a short mix: no limiter work allowed, and a ceiling far down
        loudness.MAX_LIMITER_GR_DB, loudness.ENCODE_MARGIN_DB = 0.0, 8.0
        argv = sys.argv
        sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                    str(tmp / "plan.json"), str(tmp / "mix.wav")]
        try:
            bs.main()
        finally:
            sys.argv = argv
            loudness.MAX_LIMITER_GR_DB, loudness.ENCODE_MARGIN_DB = saved
        rec = json.loads((tmp / "plan.json").read_text())["audio"]["loudness"]
        assert rec["shortfall_db"] > 0.2 and rec["after"]["integrated_lufs"] < -14.2, rec
        landed = rec["after"]["integrated_lufs"]
        assert rec["ending"]["target_lufs"] == landed, rec["ending"]
        assert abs(rec["ending"]["before"]["integrated_lufs"] + rec["ending"]["gain_db"]
                   - landed) <= 0.2, rec["ending"]


def test_the_render_plays_the_ending_at_the_recorded_volume():
    video = (RENDER_SRC / "Video.jsx").read_text()
    assert "volume={plan.audio?.loudness?.ending?.volume ?? 1}" in video, (
        "Video.jsx no longer hands EndCard the volume build_soundtrack.py "
        "recorded - the ending clip would play at its own (hotter) level")
    card = (RENDER_SRC / "components" / "EndCard.jsx").read_text()
    clip = card[card.index("card?.variant === 'clip'"):card.index("const hasSomething")]
    assert "volume={volume}" in clip, clip
    assert "muted" not in clip


# --------------------------------------------------------------------------
# qc_render.py
# --------------------------------------------------------------------------


def _qc(mix, plan_path):
    out = subprocess.run([PY, str(SCRIPTS / "qc_render.py"), str(mix), str(plan_path),
                          "--audio-only", "--json"], capture_output=True, text=True)
    return json.loads(out.stdout)


def test_qc_measures_the_file_and_is_quiet_on_target():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        work = Path(tmp) / "work"
        work.mkdir()
        mix, _ = ambtest.mixed_with_channel(work, root=root, channel="chan")
        result = _qc(mix, work / "plan.json")
        got = result["measured"]["loudness"]
        assert got and abs(got["integrated_lufs"] - -14.0) <= 0.5, got
        assert not any("loudness" in n for n in result["notes"]), result["notes"]


def test_qc_flags_a_miss_as_a_note():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        work = Path(tmp) / "work"
        work.mkdir()
        mix, _ = ambtest.mixed_with_channel(work, root=root, channel="chan")
        # the same mix 8 dB down: a file that missed its target
        low = work / "low.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mix), "-af",
                        "volume=-8dB", str(low)], check=True)
        result = _qc(low, work / "plan.json")
        notes = [n for n in result["notes"] if n.startswith("loudness off target")]
        assert notes and "LU off" in notes[0], result["notes"]
        assert not any("loudness" in f for f in result["failures"]), result["failures"]


def test_qc_judges_nothing_on_a_plan_without_a_loudness_record():
    with tempfile.TemporaryDirectory() as tmp:
        root = ambtest.channel_root(tmp, ambient="ambient.wav")
        work = Path(tmp) / "work"
        work.mkdir()
        mix, plan = ambtest.mixed_with_channel(work, root=root, channel="chan")
        del plan["audio"]["loudness"]
        (work / "plan.json").write_text(json.dumps(plan))
        result = _qc(mix, work / "plan.json")
        assert result["measured"]["loudness"] is None
        assert not any("loudness" in n for n in result["notes"])


def test_the_verdict_flags_a_true_peak_over_the_ceiling():
    v = loudness.qc_verdict({"integrated_lufs": -14.2, "true_peak_db": -0.3,
                             "lra_lu": 5.0}, -14.0, -1.0)
    assert v and "true peak" in v, v
    assert loudness.qc_verdict({"integrated_lufs": -14.6, "true_peak_db": -1.6,
                                "lra_lu": 5.0}, -14.0, -1.0) is None


def test_the_mix_is_dual_mono_stereo_at_unity():
    """The render used to up-mix the mono mix at -3 dB per channel and lose
    3 dB of peak room (render -4.4 vs mix -1.5 dBTP on the demo). The master
    pass writes both channels itself, each one the whole mix at 0 dB."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _wav(Path(tmp) / "pre.wav", _speechish(level=0.05))
        out = Path(tmp) / "out.wav"
        rec = loudness.master(src, out, -14.0, -1.0, SR, seconds=12.0)
        import wave
        with wave.open(str(out)) as w:
            assert w.getnchannels() == 2, w.getnchannels()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
        assert np.array_equal(x[:, 0], x[:, 1]), "the two channels differ"
        # the premaster is measured as it will sound duplicated: +3 LU on a
        # plain mono reading
        mono = loudness.measure(src)
        assert abs(rec["before"]["integrated_lufs"] - (mono["integrated_lufs"] + 3.0)) <= 0.2
        assert abs(loudness.measure(out)["integrated_lufs"] - -14.0) <= 0.5


def test_the_voice_stem_is_compressed_gently_and_keeps_its_loudness():
    """compress_voice(): 3:1 over a threshold set from the voice's own
    loudness, the loudness it took given back as makeup, and how hard it
    worked recorded."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # speech-like, with a louder half-second every two seconds - the
        # passages a voice compressor exists for
        x = _speechish(12.0, level=0.03)
        t = np.arange(x.size) / SR
        x[(t % 2.0) < 0.5] *= 5.0
        voice = _wav(tmp / "voice.wav", x)
        rec = loudness.compress_voice(voice, tmp / "_voice.wav", SR, seconds=12.0)
        assert rec["params"]["ratio"] == loudness.VOICE_RATIO
        assert abs(rec["params"]["threshold_db"]
                   - (rec["before"]["integrated_lufs"] + loudness.VOICE_THRESHOLD_REL_LU)) < 0.01
        assert abs(rec["after"]["integrated_lufs"] - rec["before"]["integrated_lufs"]) <= 0.3, rec
        assert rec["makeup_db"] > 0, rec
        gr = rec["gr"]
        assert 0 < gr["compressed_share"] <= 1 and gr["max_gr_db"] > 1.0, gr
        assert gr["mean_gr_db"] < gr["max_gr_db"]
        # the loud passages are turned down relative to the quiet ones: the
        # loudness range shrinks a little, it does not collapse
        assert rec["after"]["lra_lu"] <= rec["before"]["lra_lu"] + 0.2, rec
        assert not (tmp / "_voice_nomakeup.wav").exists()


def test_a_silent_voice_is_passed_through_uncompressed():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        voice = _wav(tmp / "voice.wav", np.zeros(3 * SR))
        rec = loudness.compress_voice(voice, tmp / "_voice.wav", SR, seconds=3.0)
        assert rec.get("skipped") and (tmp / "_voice.wav").exists(), rec


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
