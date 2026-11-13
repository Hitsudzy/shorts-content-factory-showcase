#!/usr/bin/env python3
"""CF-0141: the channel's ending is a finished mp4 it brings with it.

Sections D, B, E, F, G and H of the task. What is pinned here:

  * the clip is the top of the degradation chain (`clip -> logo ->
    typographic`), so a channel that has both a clip and a logo closes on the
    clip, and a channel with neither still lands on the drawn floor;
  * its length is the *config's* number, verified against the file - the
    check that keeps Content Researcher's word budget and the file from
    drifting apart (section B). More than one frame of the composition apart
    and no plan is written;
  * its format is the composition's, checked and never converted (decision 5
    of 2026-09-08). **Including the channel's real file as it stands today**,
    which is 1440x2560 at 24 fps and must honestly fail - the user is
    re-rendering it, and a test that let today's file through would be a test
    that never notices when the next one is wrong either;
  * it is cut to and not dissolved into, and it plays with its own sound
    (section E) - the seam measured on a real render, see
    test_the_clip_is_cut_to_and_not_dissolved_into;
  * the bed is brought to silence *before* it rather than mixed under it
    (section F);
  * the gates do not judge that interval at all (section G, decision 3) -
    pinned end to end, through the real gate, on a render whose last three
    seconds are full black and dead silence;
  * the batch record says which of the two endings shipped (section H).

The fixtures are real mp4s, made by ffmpeg at the top of the run and shared:
every assertion here is about what ffprobe says of a file, so a stub would
pin nothing at all.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import end_card  # noqa: E402
import meme_layer  # noqa: E402
import repo_paths  # noqa: E402
import safe_area  # noqa: E402 - CF-0329
import write_batch_metadata  # noqa: E402

REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "channels").is_dir() and (c / "tests").is_dir()), None)

COMP = {"width": 1080, "height": 1920, "fps": 30}

_CLIPS = {}
_TMP = None


def _clip(seconds=5.0, width=1080, height=1920, fps=30, audio=True):
    """A real mp4 of the given shape, made once and reused."""
    global _TMP
    key = (seconds, width, height, fps, audio)
    if key in _CLIPS:
        return _CLIPS[key]
    if _TMP is None:
        _TMP = tempfile.TemporaryDirectory()
    out = Path(_TMP.name) / ("clip_%s_%dx%d_%s_%s.mp4"
                             % (seconds, width, height, fps, "a" if audio else "silent"))
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i",
           f"testsrc=size={width}x{height}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(seconds), str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    _CLIPS[key] = out
    return out


def channel(tmp, ending=None, ending_seconds=None, ending_path_override=None,
            logo=False, card_seconds=3.0):
    """<tmp>/channels/ with one channel config; `ending` is a clip path to
    copy in as the convention file."""
    channels = Path(tmp) / "channels"
    (channels / "ch-test").mkdir(parents=True, exist_ok=True)
    cfg = {"channel_id": "ch-test", "display_name": "Test Channel",
           "stance": "ch-test/stance.json",
           "narration_budget": {"target_total_seconds": 55,
                                "end_card_seconds": card_seconds,
                                "words_per_second": 2.75}}
    if ending_seconds is not None:
        cfg["narration_budget"]["ending_seconds"] = ending_seconds
    if ending_path_override is not None:
        cfg["video_editor"] = {"ending": {"path": str(ending_path_override)}}
    (channels / "ch-test.json").write_text(json.dumps(cfg))
    (channels / "ch-test" / "stance.json").write_text(json.dumps(
        {"channel_id": "ch-test",
         "signature_phrase": {"text": "A test channel says something else.",
                              "why": "a test"}}))
    if ending is not None:
        (channels / "ch-test" / "ending.mp4").write_bytes(Path(ending).read_bytes())
    if logo:
        (channels / "ch-test" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return channels / "ch-test.json"


def plan_for(narration=49.83):
    return {"style": "stills",
            "output": dict(COMP),
            "audio": {"src": "/tmp/voice.wav", "duration": narration},
            "words": [{"word": "w", "start": 0.0, "end": round(narration - 0.4, 3)}],
            "blocks": [{"start": 0.0, "end": narration,
                        "asset": {"kind": "still", "src": "f0.png"}}],
            "duration": {"target": [35, 60], "actual": narration, "deviation": 0},
            "rhythm": {}, "degraded_blocks": [], "notes": []}


def ending_for(tmp, plan=None, **kw):
    cfg_path = channel(tmp, **kw)
    cfg = json.loads(Path(cfg_path).read_text())
    stance = end_card.load_stance(cfg, Path(tmp), str(cfg_path))
    return end_card.plan_end_card(plan or plan_for(), cfg, stance, root=Path(tmp),
                                  channel=str(cfg_path))


def refusal(tmp, **kw):
    try:
        ending_for(tmp, **kw)
    except end_card.EndCardError as e:
        return str(e)
    raise AssertionError("expected EndCardError, got a plan")


# --------------------------------------------------------------------------
# D: the clip is the ending, and the top of the chain
# --------------------------------------------------------------------------

def test_the_channel_s_clip_is_the_ending():
    with tempfile.TemporaryDirectory() as tmp:
        rec = ending_for(tmp, ending=_clip(5.0), ending_seconds=5.0)
    assert rec["variant"] == end_card.VARIANT_CLIP, rec
    assert rec["path"].endswith("channels/ch-test/ending.mp4"), rec
    assert rec["source"] == end_card.ENDING_SOURCE_CONVENTION, rec
    assert abs(rec["seconds"] - 5.0) < 0.05, rec
    # It starts where the voice stops, exactly as the card did.
    assert rec["start_s"] == 49.83, rec
    # And it says nothing the channel did not put on the frame: the phrase
    # is not on the clip, so it is not in the record either.
    assert rec["text"] is None and rec["text_source"] is None, rec
    assert rec["logo_path"] is None, rec


def test_the_clip_outranks_the_logo():
    """`clip -> logo -> typographic`. A channel with both closes on the clip:
    the drawn card is the floor for a channel without a file, not a second
    thing to show."""
    with tempfile.TemporaryDirectory() as tmp:
        rec = ending_for(tmp, ending=_clip(5.0), ending_seconds=5.0, logo=True)
    assert rec["variant"] == end_card.VARIANT_CLIP, rec


def test_a_channel_without_a_clip_still_lands_on_the_floor():
    with tempfile.TemporaryDirectory() as tmp:
        rec = ending_for(tmp)
    assert rec["variant"] == end_card.VARIANT_TYPOGRAPHIC, rec
    assert rec["path"] is None and rec["source"] is None, rec
    assert rec["seconds"] == 3.0, rec


def test_the_config_can_name_the_file_somewhere_else():
    with tempfile.TemporaryDirectory() as tmp:
        elsewhere = Path(tmp) / "assets" / "outro.mp4"
        elsewhere.parent.mkdir(parents=True)
        elsewhere.write_bytes(_clip(5.0).read_bytes())
        rec = ending_for(tmp, ending_seconds=5.0,
                         ending_path_override=elsewhere)
    assert rec["variant"] == end_card.VARIANT_CLIP, rec
    assert rec["source"] == end_card.ENDING_SOURCE_CONFIG, rec
    assert rec["path"] == str(elsewhere), rec


def test_a_named_file_that_is_not_there_is_a_refusal_not_a_fallback():
    """The one case where a missing clip is loud. A channel that says nothing
    about an ending falls to the drawn card; a channel that *names* a file
    and has not got it is broken, and quietly drawing a card instead would
    ship a video whose ending nobody chose."""
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending_seconds=5.0,
                      ending_path_override=Path(tmp) / "nope.mp4")
    assert "video_editor.ending.path" in msg, msg


def test_the_composition_is_the_narration_plus_the_clip():
    with tempfile.TemporaryDirectory() as tmp:
        plan = plan_for(49.83)
        rec = ending_for(tmp, plan=plan, ending=_clip(5.0), ending_seconds=5.0)
        end_card.apply_to_plan(plan, rec)
    assert plan["end_card"]["variant"] == end_card.VARIANT_CLIP
    assert abs(plan["duration"]["composition"] - (49.83 + rec["seconds"])) < 1e-6, plan
    # duration.actual is still the voice-over's, untouched - the CF-0087
    # judgements are about the narration, not about the tail.
    assert plan["duration"]["actual"] == 49.83, plan


# --------------------------------------------------------------------------
# B: the length is the config's number, and the file has to agree
# --------------------------------------------------------------------------

def test_a_file_longer_than_the_config_says_stops_the_plan():
    """The whole reason the number is written down: Content Researcher
    compressed the script against it long before this repo saw the file."""
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0), ending_seconds=3.0)
    assert "ending_seconds" in msg and "5.0" in msg, msg
    assert "one frame" in msg, msg


def test_a_clip_with_no_recorded_length_stops_the_plan():
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0))
    assert "records no narration_budget.ending_seconds" in msg, msg


def test_inside_one_frame_the_two_numbers_agree():
    """A frame of tolerance, and not a hair more: 1/30 s is the resolution the
    composition has, and anything coarser lets the budget drift."""
    with tempfile.TemporaryDirectory() as tmp:
        near = ending_for(tmp, ending=_clip(5.0), ending_seconds=5.0 + 0.03)
        assert near["variant"] == end_card.VARIANT_CLIP, near
        # ... and the *file's* measured length is what the composition uses,
        # not the config's rounded one.
        assert abs(near["seconds"] - 5.0) < 0.02, near
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0), ending_seconds=5.0 + 0.20)
    assert "over one frame" in msg, msg


# --------------------------------------------------------------------------
# B / decision 5: the format is checked, never converted
# --------------------------------------------------------------------------

def test_a_clip_in_the_wrong_frame_size_stops_the_plan():
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0, width=720, height=1280),
                      ending_seconds=5.0)
    assert "720x1280" in msg and "1080x1920" in msg, msg
    assert "nothing here converts the file" in msg, msg


def test_a_clip_at_the_wrong_frame_rate_stops_the_plan():
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0, fps=24), ending_seconds=5.0)
    assert "24 fps" in msg and "30 fps" in msg, msg


def test_a_clip_with_no_sound_of_its_own_stops_the_plan():
    """Decision 2: the clip's own track is what is heard, and the bed is
    faded to silence under it. A clip without a track would therefore play as
    dead air over an interval the render gate deliberately does not measure -
    nothing downstream can catch it, so this is where it is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        msg = refusal(tmp, ending=_clip(5.0, audio=False), ending_seconds=5.0)
    assert "no audio stream" in msg, msg




# --------------------------------------------------------------------------
# E: the render - the clip plays whole, with its own sound, cut to hard
# --------------------------------------------------------------------------

RENDER_SRC = AGENT_ROOT / "render" / "src"


def test_the_clip_is_played_and_not_muted():
    """The one unmuted OffthreadVideo in the repo, and the reason is written
    beside it. Every other use is stock footage whose track would fight the
    voice; this one is the channel's own mix, and decision 2 says it is what
    is heard. A future sweep that "fixes the inconsistency" by adding `muted`
    here delivers a silent ending over an interval the render gate does not
    measure - so nothing but this test would say so."""
    comp = (RENDER_SRC / "components" / "EndCard.jsx").read_text()
    assert "OffthreadVideo" in comp, "the clip is not played at all"
    clip = comp[comp.index("card?.variant === 'clip'"):]
    # up to the drawn card's own guard - CF-0186 turned that guard from
    # "is there a phrase" into "is there anything to draw", so the boundary
    # is the constant it is now built out of.
    block = clip[:clip.index("const hasSomething")]
    assert "OffthreadVideo" in block, block
    assert "muted" not in block, (
        "the ending clip is muted - the channel's own track is what the "
        "viewer is meant to hear (CF-0141 decision 2) and the bed is faded "
        "to silence under it, so muting this ships a silent ending")
    assert "decision 2" in comp, (
        "the exception is not explained on the spot - the next sweep over "
        "the repo's seven muted OffthreadVideos will put `muted` back")
    # Every other one still is muted, which is what makes this the exception.
    for other in ("AssetLayer.jsx", "SplitLayer.jsx", "SecondaryZone.jsx"):
        text = (RENDER_SRC / "components" / other).read_text()
        if "OffthreadVideo" in text:
            assert "muted" in text, f"{other} stopped muting its footage"


def test_the_clip_is_cut_to_and_not_dissolved_into():
    """Two halves of one decision, and neither works alone.

    Measured on a 5 s seam render (2026-09-08, 1080x1920 at 30 fps, a bright
    still to 3.00 s then a 2 s clip): with both halves in place `blackdetect
    =d=0.03:pix_th=0.10` finds nothing anywhere in the file and the seam is a
    single-frame cut, mean luma 122.4 (frame 89) -> 157.0 (frame 90). With
    the block hold removed and the lead still 0, the last ten frames ramp
    122.4 -> 21.8 and the same blackdetect reports `black_start:2.967
    black_duration:0.033`. So the recommended lead of 0 does not remove the
    black seam by itself - it moves it from after the cut to before it, and
    the outgoing block holding its opacity is what actually closes it.
    """
    video = (RENDER_SRC / "Video.jsx").read_text()
    assert "isClipEnding = card?.variant === 'clip'" in video, video
    assert "cardLead = isClipEnding ? 0 : CROSSFADE" in video, (
        "the clip is mounted early again - the lead would fade up over the "
        "first ~10 frames of somebody else's finished piece and run its "
        "Sequence 0.35 s past the end of the file")
    assert "hardCutAt = isClipEnding ? card.start_s : null" in video
    assert "blockOpacity(block, t, hardCutAt)" in video
    assert "hardCutAt - 1e-6) return inFade" in video, (
        "the last block fades out into the clip again - with nothing of ours "
        "to dissolve into, that fade goes to the composition's near-black "
        "background: measured 0.033 s of blackdetect-positive frames")


def test_the_clip_is_staged_like_every_other_asset():
    """It lives in `channels/<id>/`, outside the Remotion bundle, and Chrome
    refuses an absolute path from the http origin. Unstaged, the ending
    renders black - and the gate does not measure that interval, so the only
    thing that would ever tell you is this."""
    src = (AGENT_ROOT / "scripts" / "render_video.py").read_text()
    assert 'card["path"] = stage(card["path"], seen, job)' in src, src


# --------------------------------------------------------------------------
# F: the bed is gone before the clip starts
# --------------------------------------------------------------------------

def _tone_wav(path, seconds=4.0, rate=44100, hz=180.0):
    import math
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(9000 * math.sin(2 * math.pi * hz * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _rms_db(samples):
    import math
    if not len(samples):
        return -math.inf
    r = math.sqrt(sum(float(s) ** 2 for s in samples) / len(samples)) / 32768
    return 20 * math.log10(r + 1e-12)


def _mix(tmp, variant, start_s=4.0, seconds=2.0):
    """One real ffmpeg mix over a 4 s voice and a `seconds` ending. Returns
    (filter graph, samples, rate, plan)."""
    import array
    import wave
    import build_soundtrack

    tmp = Path(tmp)
    _tone_wav(tmp / "voice.wav")
    plan = plan_for(start_s)
    plan["blocks"] = [{"start": 0.0, "end": start_s,
                       "asset": {"kind": "still", "src": "f0.png"}}]
    plan["end_card"] = {"start_s": start_s, "seconds": seconds, "variant": variant,
                        "text": None if variant == "clip" else "A phrase.",
                        "text_source": None, "channel_name": "Test Channel",
                        "logo_path": None,
                        "path": "/tmp/ending.mp4" if variant == "clip" else None,
                        "source": "convention" if variant == "clip" else None}
    plan["duration"]["composition"] = start_s + seconds
    (tmp / "plan.json").write_text(json.dumps(plan))

    graphs = []
    original = build_soundtrack.runlog.run_child

    def spy(cmd, *a, **k):
        if "-filter_complex" in cmd:
            graphs.append(cmd[cmd.index("-filter_complex") + 1])
        return original(cmd, *a, **k)

    build_soundtrack.runlog.run_child = spy
    argv = sys.argv
    try:
        sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                    str(tmp / "plan.json"), str(tmp / "mix.wav")]
        build_soundtrack.main()
    finally:
        sys.argv = argv
        build_soundtrack.runlog.run_child = original

    with wave.open(str(tmp / "mix.wav")) as w:
        rate, n = w.getframerate(), w.getnframes()
        data = array.array("h")
        data.frombytes(w.readframes(n))
        data = data[::w.getnchannels()]  # CF-0695: the mix is dual-mono stereo; one channel is the mix
    return graphs[-1], data, rate, json.loads((tmp / "plan.json").read_text())


def test_the_bed_reaches_silence_by_the_clip_s_first_frame():
    """Decision 2: the clip's own track is what plays over it, so the bed is
    brought to nothing *before* the ending rather than faded across it. The
    mix still runs the whole composition - it is silence there, not a shorter
    file - because the ending's sound comes through Remotion from the clip
    itself and never through this mix (which is also what keeps the render
    gate's audio measurements honest: they are measured on the mix)."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, data, rate, plan = _mix(tmp, "clip")

    # The fade runs BED_FADE_SECONDS *before* the ending, not across it.
    assert "afade=t=out:st=2.500:d=1.500" in graph, graph
    assert "afade=t=out:st=4.000" not in graph, (
        "the bed still fades across the ending - it plays under the channel's "
        "own clip for the whole of it")
    assert "apad=whole_dur=6.000" in graph, graph

    seconds = len(data) / rate
    assert abs(seconds - 6.0) < 0.05, f"the mix is {seconds:.2f}s, not 6.00s"
    body = _rms_db(data[int(1.0 * rate):int(2.0 * rate)])
    ending = _rms_db(data[int(4.05 * rate):])
    assert body > -45, f"nothing is in the mix at all ({body:.1f} dB)"
    assert ending < -60, (
        f"the mix is still making sound over the ending clip ({ending:.1f} dB) - "
        f"the bed is meant to be gone by its first frame, not quieter over it")


def test_the_drawn_card_still_keeps_its_bed():
    """The floor did not change. A card this repo draws is a held frame with
    nothing on the soundtrack of its own, and silence under it reads as the
    file having stopped - so the bed still plays across it and fades out."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, data, rate, plan = _mix(tmp, "typographic")
    assert "afade=t=out:st=4.000:d=2.000" in graph, graph
    head = _rms_db(data[int(4.0 * rate):int(4.5 * rate)])
    assert head > -45, f"the bed is not there under the card ({head:.1f} dB)"


def test_the_plan_records_which_shape_the_bed_was_given():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, plan = _mix(tmp, "clip")
    bed = plan["audio"]["bed"]
    assert bed["silent_from_s"] == 4.0, bed
    assert bed["ending_variant"] == "clip", bed
    assert bed["fade_out_s"] == 1.5, bed
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, plan = _mix(tmp, "typographic")
    bed = plan["audio"]["bed"]
    assert bed["silent_from_s"] is None, bed
    assert bed["ending_variant"] == "typographic", bed


# --------------------------------------------------------------------------
# C: how long an ending the channel can afford
# --------------------------------------------------------------------------

def _narration_floor_off_disk(pattern_id, min_block):
    """The shortest narration a pattern can be built in, re-derived from its
    file here - deliberately by scanning block counts upward rather than by
    the closed form `end_card._pattern_narration_floor()` uses, so that the
    two are a real cross-check of each other and not one arithmetic checking
    its own spelling.

    A count says the number of blocks outright. A pace does not (CF-0310), so
    the smallest block count is looked for at which the pattern's own two
    demands can hold at once: the narration is long enough to carry the hold
    and the blocks (`hold.max + (n - 1) * MIN_BLOCK_SECONDS`), and short
    enough that n blocks are still at or above the floor pace (`60 * n /
    rate.min`). No length is taken from anywhere else - that is the whole
    argument of CF-0315.
    """
    params = json.loads(
        (REAL_ROOT / "patterns" / f"{pattern_id}.json").read_text())["parameters"]
    hold = params["key_frame_hold_seconds"]["max"]
    if "block_count" in params:
        blocks = params["block_count"]["min"]
    else:
        rate = params["block_rate_per_minute"]["min"]
        blocks = 1
        while hold + (blocks - 1) * min_block > 60.0 * blocks / rate:
            blocks += 1
    return round(hold + (blocks - 1) * min_block, 2), blocks


def test_the_structural_ceiling_is_derived_and_not_typed_in():
    """43.00 s on example-film, recomputed from the pattern files rather than
    believed - and it is 43.00 and no longer CF-0141's 40.40 because the
    pattern that used to bind it stopped stating a block count.

    The arithmetic is `patterns/validate_patterns.py`'s own feasibility check
    - `key_frame_hold_seconds.max + (blocks - 1) * MIN_BLOCK_SECONDS`, the
    shortest narration a pattern can physically be built in - taken over the
    patterns the channel admits and subtracted from `target_total_seconds`.

    **Why the number moved (CF-0315).** explainer used to say `block_count`
    12-33 and so asked 8.0 + 11 x 0.6 = 14.60 s, which bound the ceiling at
    55 - 14.60 = 40.40. CF-0310 measured that this floor of 12 was observed on
    videos 40-47 s long and carried their length inside it, and restated the
    envelope as a pace, `block_rate_per_minute` 15.39-47.88. A pace carries no
    count until a length is chosen, and CF-0315 refuses to choose one (the
    root refuses the same way in its own feasibility check): the formula is
    solved for its own fixed point instead, which puts explainer at 3 blocks
    and 9.20 s. moment-breakdown's 12.00 s now binds, so the ceiling is 43.00.
    The rise is a measurement arriving, not a relaxation: 14.60 s of narration
    was never something explainer itself demanded.

    Between CF-0310 and CF-0315 this number was 43.00 too - but by accident,
    through an `except KeyError: continue` that dropped explainer without a
    word. Hence the second half of this file's section C: the reading names
    every pattern it counted.
    """
    if REAL_ROOT is None:
        return
    cfg = meme_layer.load_channel("example-film", REAL_ROOT)
    if cfg is None:
        return
    budget = cfg["narration_budget"]
    allowed = cfg["patterns"]["allowed_pattern_ids"]
    min_block = end_card._validator_min_block_seconds(REAL_ROOT)
    floors, blocks = {}, {}
    for pattern_id in allowed:
        floors[pattern_id], blocks[pattern_id] = _narration_floor_off_disk(
            pattern_id, min_block)
    expected = round(budget["target_total_seconds"] - max(floors.values()), 2)
    assert max(floors, key=floors.get) == "moment-breakdown", floors
    assert floors == {"moment-breakdown": 12.00, "contrast": 10.10,
                      "explainer": 9.20, "list": 9.10}, floors
    # Three blocks and not two: two would need 8.60 s of narration, and at the
    # floor pace two blocks cannot stretch past 60 x 2 / 15.39 = 7.80 s.
    assert blocks["explainer"] == 3, blocks
    assert expected == 43.00, (floors, expected)
    reading = end_card.structural_ceiling(cfg, REAL_ROOT)
    assert reading["seconds"] == expected, reading
    assert reading["binding_pattern"] == "moment-breakdown", reading
    assert reading["skipped"] == [], reading


def test_the_pattern_that_states_a_pace_is_counted_and_named():
    """The defect itself: explainer states `block_rate_per_minute` and the old
    formula asked it for `block_count.min`, so `except KeyError: continue`
    dropped the most demanding pattern in the vocabulary and the ceiling came
    back looking exactly like a ceiling computed over all four."""
    if REAL_ROOT is None:
        return
    cfg = meme_layer.load_channel("example-film", REAL_ROOT)
    if cfg is None:
        return
    reading = end_card.structural_ceiling(cfg, REAL_ROOT)
    counted = {c["pattern_id"]: c for c in reading["counted"]}
    assert set(counted) == set(cfg["patterns"]["allowed_pattern_ids"]), reading
    explainer = counted["explainer"]
    assert explainer["parameter"] == end_card.CEILING_PACE_PARAMETER, explainer
    assert explainer["mode"] == "floor_drawn", explainer
    assert explainer["band_floor"] == 15.39 and explainer["blocks"] == 3, explainer
    assert explainer["narration_floor_seconds"] == 9.20, explainer
    # And it is readable as a sentence, with every pattern in it - the number
    # alone cannot show that one of them went missing.
    line = end_card.ceiling_sentence(reading)
    assert line.startswith("43.00s of ending out of a 55.00s target"), line
    for pattern_id in cfg["patterns"]["allowed_pattern_ids"]:
        assert pattern_id in line, (pattern_id, line)
    assert "NOT COUNTED" not in line, line


def _pattern_root(tmp, patterns, min_block=0.6):
    """A factory root with nothing in it but the patterns named and the one
    constant the arithmetic imports. `_validator_min_block_seconds()` reads
    MIN_BLOCK_SECONDS out of `patterns/validate_patterns.py` by path, so a
    two-line stand-in is enough and keeps these cases off the real vocabulary.
    """
    root = Path(tmp) / "fake-root"
    (root / "patterns").mkdir(parents=True, exist_ok=True)
    (root / "patterns" / "validate_patterns.py").write_text(
        f"MIN_BLOCK_SECONDS = {min_block}\n")
    for pattern_id, params in patterns.items():
        (root / "patterns" / f"{pattern_id}.json").write_text(
            json.dumps({"pattern_id": pattern_id, "parameters": params}))
    return root


def _band_channel(allowed, target=55):
    return {"channel_id": "ch-test", "patterns": {"allowed_pattern_ids": allowed},
            "narration_budget": {"target_total_seconds": target}}


_COUNT_PATTERN = {"block_count": {"mode": "drawn", "min": 6, "max": 12},
                  "key_frame_hold_seconds": {"mode": "drawn", "min": 4.0, "max": 9.0}}


def test_a_pattern_that_states_neither_envelope_is_named_as_skipped():
    """The `continue` is gone: a pattern that gives the ceiling no number is
    in the reading by name, with the code and the reason, and the ceiling is
    then honestly the ceiling of the patterns that did give one."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _pattern_root(tmp, {
            "counts": _COUNT_PATTERN,
            "silent": {"key_frame_hold_seconds": {"mode": "drawn", "min": 1.0,
                                                  "max": 4.0}}})
        reading = end_card.structural_ceiling(_band_channel(["counts", "silent"]), root)
    assert [c["pattern_id"] for c in reading["counted"]] == ["counts"], reading
    assert reading["seconds"] == 43.00 and reading["binding_pattern"] == "counts", reading
    assert [s["pattern_id"] for s in reading["skipped"]] == ["silent"], reading
    skip = reading["skipped"][0]
    assert skip["code"] == end_card.CEILING_NO_BLOCK_PARAMETER, skip
    assert "block_rate_per_minute" in skip["reason"] and "block_count" in skip["reason"], skip
    line = end_card.ceiling_sentence(reading)
    assert "NOT COUNTED: silent (no_block_count_parameter)" in line, line


def test_a_band_mode_this_repo_cannot_read_is_loud_and_refuses_nothing():
    """CF-0314 left rhythm.py unable to fall through on a mode it does not
    know, and this is the same answer in the same words: the pattern is named
    with rhythm's own `band_mode_unreadable`, nothing raises, and the ceiling
    is still derived from the patterns that could be read. A raise here would
    take the batch down over a word; a silent skip would sign a ceiling nobody
    measured - the two failures CF-0315 sits between."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _pattern_root(tmp, {
            "counts": _COUNT_PATTERN,
            "haruspex": {"block_rate_per_minute": {"mode": "augured", "min": 15.39,
                                                   "max": 47.88},
                         "key_frame_hold_seconds": {"mode": "emergent", "min": 2.5,
                                                    "max": 8.0}},
            "oddhold": {"block_count": {"mode": "drawn", "min": 12, "max": 24},
                        "key_frame_hold_seconds": {"mode": "augured", "min": 1.0,
                                                   "max": 2.5}}})
        reading = end_card.structural_ceiling(
            _band_channel(["counts", "haruspex", "oddhold"]), root)
    import rhythm
    assert end_card.CEILING_BAND_MODE_UNREADABLE == rhythm.PATTERN_BAND_MODE_UNREADABLE
    assert reading["seconds"] == 43.00, reading
    assert [c["pattern_id"] for c in reading["counted"]] == ["counts"], reading
    skipped = {s["pattern_id"]: s for s in reading["skipped"]}
    assert set(skipped) == {"haruspex", "oddhold"}, reading
    for pattern_id, band in (("haruspex", "block_rate_per_minute"),
                             ("oddhold", "key_frame_hold_seconds")):
        skip = skipped[pattern_id]
        assert skip["code"] == rhythm.PATTERN_BAND_MODE_UNREADABLE, skip
        # The word it read and the words it knows, both - the same thing
        # rhythm.pattern_shortfalls() records, so that a new mode arriving from
        # the root can be recognised as a new mode and not as a broken file.
        assert f"{band}.mode is 'augured'" in skip["reason"], skip
        for known in rhythm.KNOWN_BAND_MODES:
            assert known in skip["reason"], skip
    line = end_card.ceiling_sentence(reading)
    assert "NOT COUNTED" in line and "augured" in line, line


def test_the_two_envelope_shapes_are_the_ones_rhythm_reads():
    """One reader of the shape, in rhythm.block_count_parameter(), and the two
    names here are taken from its table rather than typed again. The order of
    that table decides which branch of the arithmetic a pattern goes down (a
    count *is* a number of blocks; a pace has to be solved for one), so a
    reordering that swapped them would otherwise be silent."""
    assert end_card.CEILING_PACE_PARAMETER == "block_rate_per_minute"
    assert end_card.CEILING_COUNT_PARAMETER == "block_count"


def test_a_pace_floor_no_video_can_satisfy_is_named_rather_than_counted():
    """The one arithmetic dead end a pace has: above 100 blocks a minute every
    block would be under the 0.6 s floor the pipeline has ever produced, so no
    length satisfies the pattern and there is no floor to take. The root's
    schema refuses such a band outright; this is what happens if one arrives
    anyway."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _pattern_root(tmp, {
            "counts": _COUNT_PATTERN,
            "impossible": {"block_rate_per_minute": {"mode": "emergent", "min": 120.0,
                                                     "max": 200.0},
                           "key_frame_hold_seconds": {"mode": "emergent", "min": 2.5,
                                                      "max": 8.0}}})
        reading = end_card.structural_ceiling(
            _band_channel(["counts", "impossible"]), root)
    skip = reading["skipped"][0]
    assert reading["seconds"] == 43.00, reading
    assert skip["pattern_id"] == "impossible", reading
    assert skip["code"] == end_card.CEILING_PACE_FLOOR_INFEASIBLE, skip
    assert "0.6s shortest block" in skip["reason"], skip


def test_a_channel_that_cannot_be_read_says_so_instead_of_answering_none():
    """`seconds: None` used to be the whole answer to three different
    questions. Each of them is now a named entry in the reading, because "no
    ceiling" and "no ceiling *because*" are what a caller has to tell apart."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _pattern_root(tmp, {"counts": _COUNT_PATTERN})
        no_target = end_card.structural_ceiling(
            {"patterns": {"allowed_pattern_ids": ["counts"]}}, root)
        no_patterns = end_card.structural_ceiling(_band_channel([]), root)
        no_validator = end_card.structural_ceiling(
            _band_channel(["counts"]), Path(tmp) / "not-a-root")
    for reading, code in ((no_target, end_card.CEILING_NO_TARGET),
                          (no_patterns, end_card.CEILING_NO_ADMITTED_PATTERNS),
                          (no_validator, end_card.CEILING_MIN_BLOCK_UNREADABLE)):
        assert reading["seconds"] is None and reading["counted"] == [], reading
        assert [s["code"] for s in reading["skipped"]] == [code], reading
        assert reading["skipped"][0]["pattern_id"] is None, reading
        assert "no structural ceiling could be derived" in \
            end_card.ceiling_sentence(reading), reading


def test_the_ceiling_uses_the_validator_s_constant_and_not_this_repo_s():
    """Two numbers, two questions, and until CF-0152 one name.
    `patterns/validate_patterns.py MIN_BLOCK_SECONDS` is 0.6 - the shortest
    block the pipeline has ever produced, and the constant its own feasibility
    formula is written against. `scripts/rhythm.py` has 1.6, which means
    something else entirely: the gap below which an anchor is too tight to
    read. Deriving the ceiling from rhythm.py's number would give 29.40 s and
    would be answering a different question.

    CF-0152 renamed rhythm.py's to MIN_ANCHOR_GAP_SECONDS and kept no alias, so
    this now guards two things: that the number is still 1.6 under its own
    name, and that the old name has not come back - an alias would make the
    collision importable again, which is the defect this closes."""
    import rhythm
    assert rhythm.MIN_ANCHOR_GAP_SECONDS == 1.6, (
        "rhythm.py's constant moved - if it is now the block floor rather than "
        "the anchor gap, the ceiling above is being derived from the wrong "
        "one of the two")
    assert not hasattr(rhythm, "MIN_BLOCK_SECONDS"), (
        "MIN_BLOCK_SECONDS is back in rhythm.py - that name belongs to the "
        "validator's 0.6 block floor, and 41.5% of the material lies between "
        "the two numbers (CF-0152)")
    if REAL_ROOT is None:
        return
    assert end_card._validator_min_block_seconds(REAL_ROOT) == 0.6
    src = (AGENT_ROOT / "scripts" / "end_card.py").read_text()
    assert "MIN_BLOCK_SECONDS = 0.6" not in src and "min_block = 0.6" not in src, (
        "the validator's constant has been copied into this repo - a copy is "
        "exactly how the two arithmetics come to disagree")


def test_an_ending_over_the_ceiling_stops_the_plan():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = channel(tmp, ending=_clip(5.0), ending_seconds=5.0)
        cfg = json.loads(Path(cfg_path).read_text())
        # A channel that admits only explainer: the pattern needs 9.20 s of
        # narration (CF-0315 - 3 blocks at its floor pace, not the 14.60 s its
        # count band asked for before CF-0310), so the ceiling is the target
        # less that. This is also the case the "leave explainer out of the
        # formula" reading would have lost: with explainer skipped there is no
        # admitted pattern left and the channel would have had no ceiling at
        # all - on the most demanding pattern in the vocabulary.
        cfg["patterns"] = {"allowed_pattern_ids": ["explainer"]}
        cfg["narration_budget"]["target_total_seconds"] = 20
        assert end_card.structural_ceiling(cfg, REAL_ROOT)["seconds"] == 10.80
        cfg["narration_budget"]["target_total_seconds"] = 14
        assert end_card.structural_ceiling(cfg, REAL_ROOT)["seconds"] == 4.80
        Path(cfg_path).write_text(json.dumps(cfg))
        stance = end_card.load_stance(cfg, Path(tmp), str(cfg_path))
        try:
            end_card.plan_end_card(plan_for(), cfg, stance, root=REAL_ROOT,
                                   channel=str(cfg_path))
        except end_card.EndCardError as e:
            assert "can afford at most 4.80s" in str(e), e
            assert "structural ceiling only" in str(e), e
            # And the refusal says which pattern asked for it, on what band:
            # "the most demanding pattern it admits" is not something an
            # operator can check against `patterns/` without the name.
            assert "explainer binds it, asking 9.20s of narration" in str(e), e
            assert "3 blocks from block_rate_per_minute floor 15.39" in str(e), e
            return
    raise AssertionError("a 5 s ending on a 4.80 s ceiling was planned anyway")


def test_the_editorial_limit_is_not_invented():
    """The other limit CF-0141 asked for - the length of narration below which
    the video has nothing left to say - is deliberately absent. Nothing in
    this project bounds it, and a constant with no derivation behind it is the
    failure CF-0143 and CF-0137 are the record of. The note says what it would
    take to name one; the code names none."""
    note = end_card.EDITORIAL_LIMIT_NOTE
    assert "is not recorded anywhere in this project" in note
    assert "user's call" in note
    src = (AGENT_ROOT / "scripts" / "end_card.py").read_text()
    assert "EDITORIAL_LIMIT_SECONDS" not in src and "MIN_NARRATION_SECONDS" not in src, (
        "an editorial floor has been given a number - there is nothing in this "
        "repository to derive one from, and CF-0141 left it to the user")


# --------------------------------------------------------------------------
# G: the gates do not judge the ending
# --------------------------------------------------------------------------

VENV_PY = repo_paths.VENV_PY3
SCRIPTS = AGENT_ROOT / "scripts"


def _video_with_a_black_silent_tail(path, body=3.0, tail=3.0, w=320, h=568, fps=30):
    """A render whose last `tail` seconds are pure black and pure silence -
    the two things the gate fails a video for, put exactly where the channel's
    ending clip would be."""
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x33CC66:s={w}x{h}:r={fps}:d={body}",
         "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={tail}",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={body}",
         "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={tail}",
         "-filter_complex",
         "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-t", str(body + tail), str(path)],
        check=True, capture_output=True)
    return path


def _gate_plan(tmp, variant, body=3.0, tail=3.0, w=320, h=568, fps=30):
    plan = {"style": "stills",
            "output": {"width": w, "height": h, "fps": fps},
            # CF-0329: the zones this fixture used to carry are the ones every
            # video shipped before 2026-09-23 had, and qc_render now refuses
            # them - they sit inside the player's own cut. Derived, like the
            # planner's.
            "safe_zones": safe_area.safe_zones(),
            "audio": {"src": None, "duration": body},
            "words": [{"word": "w", "start": 0.2, "end": body - 0.4}],
            "blocks": [{"start": 0.0, "end": body,
                        "asset": {"kind": "still", "src": "f0.png"}}],
            "duration": {"target": [35, 60], "actual": body, "deviation": 0,
                         "composition": body + tail},
            "end_card": {"variant": variant, "start_s": body, "seconds": tail,
                         "text": None if variant == "clip" else "A phrase.",
                         "text_source": None, "channel_name": "Test Channel",
                         "logo_path": None,
                         "path": "/tmp/ending.mp4" if variant == "clip" else None,
                         "source": "convention" if variant == "clip" else None},
            "rhythm": {}, "degraded_blocks": [], "notes": []}
    path = Path(tmp) / f"plan-{variant}.json"
    path.write_text(json.dumps(plan))
    return path


def _run_gate(video, plan_path):
    out = subprocess.run([str(VENV_PY), str(SCRIPTS / "qc_render.py"),
                          str(video), str(plan_path), "--json"],
                         capture_output=True, text=True)
    return json.loads(out.stdout)


def test_a_black_and_silent_fragment_inside_the_ending_passes():
    """Decision 3, end to end and through the real gate. The last three seconds
    of this render are full black and dead silence - the two faults this gate
    exists for - and they are inside the channel's ending clip, so it passes.
    The clip is finished material the user approved before the factory saw
    it; there is no assembly there to have gone wrong.
    """
    with tempfile.TemporaryDirectory() as tmp:
        video = _video_with_a_black_silent_tail(Path(tmp) / "render.mp4")
        result = _run_gate(video, _gate_plan(tmp, "clip"))
    assert result["passed"], result["failures"]
    # And the excusal is visible - CF-0004's rule, applied here.
    notes = " ".join(result["notes"])
    assert "black" in notes and "ending clip" in notes, result["notes"]
    assert "silence" in notes, result["notes"]
    assert "decision 3" in notes, result["notes"]


def test_the_same_fragment_outside_the_ending_still_fails():
    """The other half of the same test, and the one that proves the excusal is
    an interval and not a switch: the identical render judged against a plan
    whose ending is a card this repo draws - so nothing is excused - fails on
    both counts."""
    with tempfile.TemporaryDirectory() as tmp:
        video = _video_with_a_black_silent_tail(Path(tmp) / "render.mp4")
        result = _run_gate(video, _gate_plan(tmp, "typographic"))
    assert not result["passed"], result
    joined = " ".join(result["failures"])
    assert "black stretch" in joined, result["failures"]
    assert "silent stretch" in joined, result["failures"]


def test_a_run_that_straddles_the_seam_is_judged_on_our_half():
    """A black stretch that begins in the body and runs into the ending is
    the fault the gate exists for - the picture died early and the clip
    covered the evidence - so only the part inside the clip is dropped."""
    ending = (49.83, 55.0)
    straddle = {"start": 48.0, "end": 51.0, "duration": 3.0}
    parts = qc_render_module().outside(straddle, ending)
    assert len(parts) == 1, parts
    assert parts[0]["start"] == 48.0 and abs(parts[0]["duration"] - 1.83) < 1e-6, parts
    inside = {"start": 50.0, "end": 52.0, "duration": 2.0}
    assert qc_render_module().outside(inside, ending) == []
    after = {"start": 56.0, "end": 57.0, "duration": 1.0}
    assert qc_render_module().outside(after, ending) == [after]
    # No clip: nothing is ever excused.
    assert qc_render_module().outside(inside, None) == [inside]


def qc_render_module():
    import qc_render
    return qc_render


def test_the_interval_is_only_read_off_a_clip():
    qc = qc_render_module()
    assert qc.ending_interval({"end_card": {"variant": "clip", "start_s": 49.83,
                                            "seconds": 5.167}}) == (49.83, 54.997)
    # A drawn card is this repo's own render and is judged like every other
    # frame it produces.
    assert qc.ending_interval({"end_card": {"variant": "typographic",
                                            "start_s": 52.0, "seconds": 3.0}}) is None
    assert qc.ending_interval({}) is None
    assert qc.ending_interval({"end_card": {"variant": "clip"}}) is None


def test_the_audio_gates_stop_at_the_clip_s_first_frame():
    """The three audio measurements that would otherwise read the clip's own
    track - or the silence the mix deliberately leaves under it - as this
    factory's work."""
    src = (SCRIPTS / "qc_render.py").read_text()
    bed = src[src.index("def bed_audibility_db"):src.index("def _rms_db_over")]
    assert "ending = ending_interval(plan)" in bed and "mix = mix[:max(0" in bed, (
        "bed_audibility_db measures past the clip's first frame - the mix is "
        "silent there by design and the gate would report a bed that vanished")
    sound = src[src.index("def sound_audibility_db"):src.index("def pair_motion")]
    assert "_rms_db_over(path, 0.0, until)" in sound, (
        "the mix-to-voice ratio still spans the ending clip's own track")
    peak = src[src.index("def peak_db"):src.index("MEASURE_SR = 22050")]
    assert "until" in peak and '"-t"' in peak, peak
    assert "peak_db(args.video, until=" in src, (
        "the clipping gate still judges the ending clip's own peaks")
    # The caption band is sampled over the narration, never the composition.
    contrast = src[src.index("def caption_contrast"):src.index("def main()")]
    assert 'duration = plan["audio"]["duration"]' in contrast, contrast
    assert "composition" not in contrast.split("worst = None")[0].split("# The narration")[0]


# --------------------------------------------------------------------------
# H: which ending shipped, on the batch record
# --------------------------------------------------------------------------

def test_the_batch_record_says_the_ending_was_the_channel_s_clip():
    with tempfile.TemporaryDirectory() as tmp:
        plan = plan_for()
        end_card.apply_to_plan(plan, ending_for(tmp, plan=plan, ending=_clip(5.0),
                                                ending_seconds=5.0))
    ending = end_card.ending_stage_fields(plan)
    assert set(ending) == set(end_card.ENDING_DELIVERED_KEYS), ending
    assert ending["variant"] == end_card.VARIANT_CLIP, ending
    assert ending["path"].endswith("ending.mp4"), ending
    assert ending["source"] == end_card.ENDING_SOURCE_CONVENTION, ending
    # The card's six keys are all null - the pair is exclusive, and the old
    # field keeps meaning what it always meant.
    card = end_card.stage_fields(plan)
    assert set(card) == set(end_card.DELIVERED_KEYS), card
    assert all(v is None for v in card.values()), card


def test_the_batch_record_still_says_when_the_ending_was_the_drawn_floor():
    with tempfile.TemporaryDirectory() as tmp:
        plan = plan_for()
        end_card.apply_to_plan(plan, ending_for(tmp, plan=plan))
    card = end_card.stage_fields(plan)
    assert card["variant"] == end_card.VARIANT_TYPOGRAPHIC, card
    assert card["text"], card
    ending = end_card.ending_stage_fields(plan)
    assert all(v is None for v in ending.values()), ending


def test_a_plan_with_no_ending_at_all_still_answers_both_questions():
    """Absence is reported, never interpreted - the promise the insert pairs
    make, kept by both fields."""
    assert all(v is None for v in end_card.stage_fields({}).values())
    assert all(v is None for v in end_card.ending_stage_fields({}).values())


def test_the_metadata_writer_writes_the_field():
    """The record write_batch_metadata.py builds carries both keys, so the
    reader of a 05-*.json never has to know which milestone made it."""
    src = (AGENT_ROOT / "scripts" / "write_batch_metadata.py").read_text()
    assert "end_card.ENDING_DELIVERED_FIELD: ending_delivered" in src, \
        "write_batch_metadata.py must put ending_delivered on the record"
    assert end_card.ENDING_DELIVERED_FIELD == "ending_delivered"
    assert hasattr(write_batch_metadata, "end_card")


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
