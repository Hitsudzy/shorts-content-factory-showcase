#!/usr/bin/env python3
"""CF-0117: the end card - the channel's logo and signature phrase.

Seconds and dicts, plus one real ffmpeg mix (a 4 s tone and a 2 s card,
about a second of work) and two real runs of build_render_plan.py. No
Remotion, no Vision, no footage.

What is checked:
  the phrase has one source (item 1):
  - the text comes out of the stance document CF-0063 named, field
    `signature_phrase.text`, and `text_source` says which file and field.
    Proven on a temp channel whose stance carries a phrase of its own - a
    phrase hard-coded in scripts/ would pass a test against the real config
    and fail this one - and then on the real config, where the check is now
    that there is no phrase and that the cancelled one (CANCELLED_PHRASE
    below) survives nowhere.
  - a stance file that is named and missing, or unreadable: EndCardError,
    and through build_render_plan.py no plan at all. Never a default.
  - CF-0186: a stance document that carries no phrase (or a blank one) is
    *not* that case any more. The channel signs with its logo or its name,
    the card is drawn without a phrase, and `text`/`text_source` are None.
    With no phrase, no logo and no name there is nothing to draw and no card
    is planned at all. The real channel is checked for having no phrase and
    for the cancelled wording surviving nowhere (DoD 1.4.1 item 1).
  - the one soft case: a config that names no `stance` document never joined
    CF-0063, so it gets a note and a plan - there is no phrase to have lost.
  the length is the channel's constant (item 2):
  - `seconds` == narration_budget.end_card_seconds, 3.0 on the real channel
    and whatever a temp config says; a config without it raises.
  - the card starts at the end of the voice-over, and the composition is the
    narration plus the card while `duration.actual` stays the narration's.
  the logo and its floor (item 3):
  - channels/<id>/logo.png -> variant "logo" carrying the path; nothing there
    -> variant "typographic"; the `video_editor.end_card.logo` override.
  the bed (item 4):
  - the mix runs to the end of the card, the voice is padded rather than the
    mix cut, the graph fades the bed across the card, and the last quarter
    second is quieter than the first quarter of the card.
  the provenance (item 5):
  - videos[].end_card_delivered carries the six keys off the plan, is
    null-filled on a plan without a card, survives a rerun unchanged, and the
    root's own check_* functions still pass on the record.
  the card in the composition (item 2 of the render):
  - EndCard.jsx exists, Video.jsx mounts it over its own frame range, hides
    the watermark under it and adds its span to the captions' hidden ranges,
    Root.jsx sizes the composition from duration.composition, and
    qc_render.py measures the picture against that same number.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import copy
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import end_card  # noqa: E402
import meme_layer  # noqa: E402
import write_batch_metadata  # noqa: E402

RENDER_SRC = AGENT_ROOT / "render" / "src"
REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "channels").is_dir() and (c / "tests").is_dir()), None)

# The phrase the real channel used to carry. CF-0181 removed it from
# channels/example-film/stance.json with the position it belonged to, and
# CF-0186 made its absence legal here. It is kept in this file for one job
# only: to be the string that must appear *nowhere* - not in the stance, not
# in scripts/, not on a card. A cancelled position surviving as a default is
# exactly what DoD 1.4.1 item 1 is about.
CANCELLED_PHRASE = "The frame doesn't have a publicist."

# Deliberately not that phrase. Every test that can uses this one, so a card
# that quietly knew the answer would fail rather than pass.
OTHER_PHRASE = "A test channel says something else entirely."


# --------------------------------------------------------------------------
# a temp channel: a config, its stance document, optionally a logo
# --------------------------------------------------------------------------

def temp_channel(tmp, phrase=OTHER_PHRASE, seconds=2.0, logo=False,
                 stance_rel="ch-test/stance.json", display="Test Channel",
                 stance_body=None, budget=True):
    """<tmp>/channels/ with one channel config, laid out the way the factory
    root lays it out: `stance` relative to the channel directory, the logo
    under channels/<channel_id>/."""
    channels = Path(tmp) / "channels"
    (channels / "ch-test").mkdir(parents=True, exist_ok=True)
    cfg = {"channel_id": "ch-test", "display_name": display, "theme": STAND_IN_THEME,
           "stance": stance_rel}
    if budget:
        cfg["narration_budget"] = {"target_total_seconds": 55,
                                   "end_card_seconds": seconds,
                                   "words_per_second": 2.75}
    (channels / "ch-test.json").write_text(json.dumps(cfg))
    if stance_body is None:
        stance_body = {"channel_id": "ch-test",
                       "signature_phrase": {"text": phrase, "why": "a test"}}
    if stance_rel:
        path = channels / stance_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stance_body))
    if logo:
        _png(channels / "ch-test" / "logo.png")
    return channels / "ch-test.json"


def _png(path):
    """A 4x4 PNG, written by hand - the card never opens the file, it only
    has to exist, and this keeps Pillow out of the test."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + b"\xff\x20\x30" * 4 for _ in range(4))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))
    return path


def plan_for(narration=10.0, blocks=2):
    step = narration / blocks
    return {"style": "stills",
            "output": {"width": 1080, "height": 1920, "fps": 30},
            "audio": {"src": "/tmp/voice.wav", "duration": narration},
            "words": [{"word": "w", "start": 0.0, "end": round(narration - 0.4, 3)}],
            "blocks": [{"start": round(i * step, 3), "end": round((i + 1) * step, 3),
                        "asset": {"kind": "still", "src": f"f{i}.png"}}
                       for i in range(blocks)],
            "duration": {"target": [35, 60], "actual": narration, "deviation": 0},
            "rhythm": {}, "degraded_blocks": [], "notes": []}


def card_for(tmp, **kw):
    cfg_path = temp_channel(tmp, **kw)
    cfg = json.loads(Path(cfg_path).read_text())
    root = Path(tmp)
    stance = end_card.load_stance(cfg, root, str(cfg_path))
    return end_card.plan_end_card(plan_for(), cfg, stance, root=root,
                                  channel=str(cfg_path))


# --------------------------------------------------------------------------
# the phrase (item 1)
# --------------------------------------------------------------------------

def test_the_phrase_comes_out_of_the_stance_document():
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp)
        assert card["text"] == OTHER_PHRASE, (
            "the card must read the channel's own stance file, not a phrase "
            "it knows")
        assert card["text"] != CANCELLED_PHRASE
        assert card["text_source"].endswith("#signature_phrase.text"), card
        assert "ch-test/stance.json" in card["text_source"].replace("\\", "/")
        # and the source really is a file that says so
        path = card["text_source"].split("#")[0]
        p = Path(path) if Path(path).is_absolute() else Path(tmp) / path
        assert json.loads(p.read_text())["signature_phrase"]["text"] == card["text"]


def test_the_real_channel_signs_with_nothing():
    """CF-0186, replacing the check that pinned the cancelled phrase.

    CF-0181 removed `signature_phrase` from channels/example-film/stance.json
    outright - not blanked, removed - because the channel's ending clip
    already carries its slogans drawn into it. So what the real channel is
    checked for now is the opposite of what it was: the stance carries no
    phrase, reading it is not an error, and the cancelled wording survives
    nowhere. `channel_name` is still read from the config, because that is
    what a phraseless card would be drawn out of.

    CF-0141 still applies: this channel closes on its own clip and draws no
    card at all, so the read goes through signature_phrase() directly. The
    drawn path stays exercised by the temp channels below.
    """
    if REAL_ROOT is None:
        return
    cfg = meme_layer.load_channel("example-film", REAL_ROOT)
    if cfg is None:
        return
    stance = end_card.load_stance(cfg, REAL_ROOT)
    assert "signature_phrase" not in stance, (
        "CF-0181 removed the key; a stance that has it again is a channel "
        "that decided something new, and this file has to be read before the "
        "card is")
    text, source = end_card.signature_phrase(
        stance, "channels/example-film/stance.json")
    assert (text, source) == (None, None), (text, source)
    assert end_card.channel_name(cfg) == "ExampleFilm", cfg
    # DoD 1.4.1 item 1: the cancelled phrase is not hiding in the stance
    # under another key either.
    assert CANCELLED_PHRASE not in json.dumps(stance), (
        "the cancelled signature phrase is still somewhere in the stance "
        "document")


def test_a_stance_with_no_phrase_still_gets_a_card():
    """CF-0186 item 2: absence of a phrase is a state, not a fault.

    Three ways to have no phrase in a stance document that exists. Each one
    gets a card - without text, with the channel's own name on it - because a
    channel may decide it signs with nothing. Nothing is defaulted: `text` is
    None and `text_source` with it, so a reader of the batch record can tell
    "no phrase" from "some phrase we did not record".
    """
    with tempfile.TemporaryDirectory() as tmp:
        for kw in ({"stance_body": {"channel_id": "ch-test"}},           # no phrase
                   {"stance_body": {"signature_phrase": {"why": "x"}}},   # no text
                   {"stance_body": {"signature_phrase": {"text": "  "}}}):  # blank
            card = card_for(tmp, **kw)
            assert card is not None, f"no card at all for {kw}"
            assert card["text"] is None and card["text_source"] is None, card
            assert card["variant"] == end_card.VARIANT_TYPOGRAPHIC, card
            assert card["channel_name"] == "Test Channel", card
            assert card["seconds"] == 2.0, card
            assert CANCELLED_PHRASE not in json.dumps(card), card


def test_a_phraseless_channel_with_a_logo_gets_the_logo_card():
    """The other half of the same decision: with no phrase but a logo, the
    logo is what the channel signs with and the variant stays `logo`."""
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp, logo=True, stance_body={"channel_id": "ch-test"})
        assert card["variant"] == end_card.VARIANT_LOGO, card
        assert card["logo_path"].endswith("logo.png"), card
        assert card["text"] is None, card


def test_with_nothing_to_draw_there_is_no_card():
    """CF-0186 item 2, the other branch: no phrase, no logo and no name
    leaves an empty slate, and an empty slate held for three seconds is worse
    than no card. `plan_end_card()` returns None and the seconds go back to
    the narration."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp, stance_body={"channel_id": "ch-test"},
                                display="")
        cfg = json.loads(Path(cfg_path).read_text())
        cfg.pop("channel_id", None)
        stance = end_card.load_stance(cfg, Path(tmp), str(cfg_path))
        card = end_card.plan_end_card(plan_for(), cfg, stance, root=Path(tmp),
                                      channel=str(cfg_path))
        assert card is None, card


def test_a_stance_document_that_is_named_and_missing_is_still_a_refusal():
    """What CF-0186 did *not* relax. A channel that points at a stance
    document it does not have is broken, and so is a config that names none
    at all - neither is a channel that decided to sign with nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            card_for(tmp, stance_rel=None)
        except end_card.EndCardError:
            pass
        else:
            raise AssertionError("a missing stance document got a card anyway")
    # a config that names no stance document at all
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp)
        cfg = json.loads(Path(cfg_path).read_text())
        cfg.pop("stance")
        try:
            end_card.load_stance(cfg, Path(tmp), str(cfg_path))
        except end_card.EndCardError:
            return
        raise AssertionError("a channel with no `stance` field got a stance anyway")


# --------------------------------------------------------------------------
# the length and where it sits (item 2)
# --------------------------------------------------------------------------

def test_the_seconds_are_the_channel_constant():
    with tempfile.TemporaryDirectory() as tmp:
        assert card_for(tmp, seconds=4.5)["seconds"] == 4.5
    with tempfile.TemporaryDirectory() as tmp:
        try:
            card_for(tmp, budget=False)
        except end_card.EndCardError:
            pass
        else:
            raise AssertionError("a card was given a length the channel never set")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            card_for(tmp, seconds=0)
        except end_card.EndCardError:
            return
        raise AssertionError("a card of no length is not a card")


def test_the_card_starts_where_the_narration_ends():
    plan = plan_for(12.0)
    assert end_card.narration_end(plan) == 12.0, "the voice-over's own length"
    # no audio record: the last block, which build_render_plan.py runs to the
    # end of the audio anyway
    no_audio = copy.deepcopy(plan)
    no_audio.pop("audio")
    assert end_card.narration_end(no_audio) == 12.0
    # neither: the last aligned word
    no_blocks = copy.deepcopy(no_audio)
    no_blocks["blocks"] = []
    assert end_card.narration_end(no_blocks) == 11.6
    bare = {"blocks": [], "words": []}
    try:
        end_card.narration_end(bare)
    except end_card.EndCardError:
        return
    raise AssertionError("a plan that says nothing about its length got a card anyway")


def test_the_composition_is_the_narration_plus_the_card():
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp, seconds=3.0)
        plan = plan_for(10.0)
        end_card.apply_to_plan(plan, card)
        assert plan["end_card"]["start_s"] == 10.0
        assert plan["duration"]["composition"] == 13.0
        # the narration's own number is untouched: the target band, the
        # deviation and the comparison line's window are all about the voice
        assert plan["duration"]["actual"] == 10.0
        assert plan["duration"]["deviation"] == 0
        once = copy.deepcopy(plan["end_card"])
        end_card.apply_to_plan(plan, card)
        assert plan["end_card"] == once and plan["duration"]["composition"] == 13.0


# --------------------------------------------------------------------------
# the logo and its floor (item 3)
# --------------------------------------------------------------------------

def test_without_a_logo_the_card_is_typographic():
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp)
        assert card["variant"] == end_card.VARIANT_TYPOGRAPHIC
        assert card["logo_path"] is None
        assert card["channel_name"] == "Test Channel", (
            "the typographic card puts the channel's name under the phrase")


def test_with_a_logo_the_card_names_it():
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp, logo=True)
        assert card["variant"] == end_card.VARIANT_LOGO
        assert Path(card["logo_path"]).name == "logo.png"
        assert Path(card["logo_path"]).exists()
        assert card["text"] == OTHER_PHRASE, "the phrase is on both variants"


def test_the_logo_can_be_named_by_the_config():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp)
        cfg = json.loads(Path(cfg_path).read_text())
        elsewhere = _png(Path(tmp) / "brand.png")
        cfg["video_editor"] = {"end_card": {"logo": str(elsewhere)}}
        stance = end_card.load_stance(cfg, Path(tmp), str(cfg_path))
        card = end_card.plan_end_card(plan_for(), cfg, stance, root=Path(tmp),
                                      channel=str(cfg_path))
        assert card["variant"] == end_card.VARIANT_LOGO
        assert card["logo_path"] == str(elsewhere)
        # a named file that is not there is no logo, not a crash at the end
        # of a render
        cfg["video_editor"]["end_card"]["logo"] = str(Path(tmp) / "gone.png")
        card = end_card.plan_end_card(plan_for(), cfg, stance, root=Path(tmp),
                                      channel=str(cfg_path))
        assert card["variant"] == end_card.VARIANT_TYPOGRAPHIC


# --------------------------------------------------------------------------
# build_render_plan.py writes one into every plan
# --------------------------------------------------------------------------

def _voice_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += int(2000 if (i // 40) % 2 else -2000).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _build_plan(tmp, channel_arg, extra=()):
    py = Path(repo_paths.VENV_PY3)
    py = str(py) if py.exists() else sys.executable
    tmp = Path(tmp)
    _voice_wav(tmp / "voice.wav")
    words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
    (tmp / "words.json").write_text(json.dumps(words))
    story = {"script_id": "cf-0117", "style": "typographic",
             "blocks": [{"word_range": [0, 4], "intent": "hook", "asset_kind": "text",
                         "asset_query": "", "emphasis_words": []},
                        {"word_range": [5, 9], "intent": "payoff", "asset_kind": "text",
                         "asset_query": "", "emphasis_words": []}]}
    (tmp / "storyboard.json").write_text(json.dumps(story))
    out = tmp / "plan.json"
    cmd = [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
           str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
           "--style", "typographic", "--target-duration", "1", "60", *extra]
    if channel_arg:
        cmd += ["--channel", channel_arg]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
    return result, out


def test_build_render_plan_puts_a_card_in_the_plan():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp, seconds=3.0, logo=True)
        result, out = _build_plan(tmp, str(cfg_path))
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        card = plan["end_card"]
        assert card["text"] == OTHER_PHRASE, card
        assert card["seconds"] == 3.0
        assert card["variant"] == "logo" and card["logo_path"].endswith("logo.png")
        assert card["start_s"] == plan["audio"]["duration"] == plan["duration"]["actual"]
        assert plan["duration"]["composition"] == round(card["start_s"] + 3.0, 3)
        assert "END CARD logo" in result.stderr, result.stderr[-1500:]
        assert "composition" in result.stderr


def test_a_channel_with_no_phrase_gets_a_plan_and_a_phraseless_card():
    """CF-0186 through the real entry point: a stance document with no
    `signature_phrase` is a channel that signs with nothing, so the plan is
    written and the card is drawn without a phrase. This is the acceptance
    criterion "the render passes with `signature_phrase` absent from
    stance.json", measured where the render actually starts."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp, seconds=3.0, stance_body={"channel_id": "ch-test"})
        result, out = _build_plan(tmp, str(cfg_path))
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        card = plan["end_card"]
        assert card["text"] is None and card["text_source"] is None, card
        assert card["variant"] == "typographic" and card["channel_name"] == "Test Channel"
        assert plan["duration"]["composition"] == round(card["start_s"] + 3.0, 3)
        assert "no signature phrase" in result.stderr, result.stderr[-1500:]
        assert CANCELLED_PHRASE not in out.read_text()


def test_a_named_stance_document_that_is_missing_gets_no_plan_at_all():
    """The card still does not degrade to a note the way the insert layers
    do. A channel that points at a stance document it does not have is
    broken, and the plan is refused the way a rejected asset refuses one -
    exit 2, nothing written. CF-0186 narrowed this to the missing document;
    a document present and phraseless is the test above."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp)
        # the config still names it; the file is gone
        (Path(tmp) / "channels" / "ch-test" / "stance.json").unlink()
        result, out = _build_plan(tmp, str(cfg_path))
        assert result.returncode == 2, (result.returncode, result.stderr[-1500:])
        assert not out.exists(), "a plan was written without a card"
        assert "END CARD NOT PLANNED" in result.stderr, result.stderr[-1500:]


def test_a_config_outside_the_stance_system_gets_a_note_and_a_plan():
    """A channel config that names no `stance` document at all never joined
    CF-0063 - there is no phrase to have lost, so the plan is written with a
    note. The refusal above is for a channel that *says* it has a position
    and then cannot produce it."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = temp_channel(tmp, stance_rel=None)
        cfg = json.loads(Path(cfg_path).read_text())
        cfg.pop("stance")
        Path(cfg_path).write_text(json.dumps(cfg))
        result, out = _build_plan(tmp, str(cfg_path))
        assert result.returncode == 0, result.stderr[-1500:]
        plan = json.loads(out.read_text())
        assert "end_card" not in plan
        assert any("names no `stance` document" in n for n in plan["notes"]), plan["notes"]


def test_without_a_channel_the_plan_says_why_it_has_no_card():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = _build_plan(tmp, None)
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert "end_card" not in plan
        assert "composition" not in plan["duration"]
        assert any("no --channel" in n for n in plan["notes"]), plan["notes"]


# --------------------------------------------------------------------------
# the bed under the card (item 4)
# --------------------------------------------------------------------------

def _tone_wav(path, seconds=4.0, rate=44100, hz=180.0):
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
    if not len(samples):
        return -math.inf
    r = math.sqrt(sum(float(s) ** 2 for s in samples) / len(samples)) / 32768
    return 20 * math.log10(r + 1e-12)


def test_the_mix_runs_under_the_card_and_the_bed_fades_out():
    """One real ffmpeg mix: 4 s of voice, a 2 s card. The mix has to reach
    6 s (silence under the card is a video that sounds like it stalled), and
    the bed has to be on its way out by the end of it."""
    import build_soundtrack

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _tone_wav(tmp / "voice.wav")
        plan = plan_for(4.0)
        plan["end_card"] = {"start_s": 4.0, "seconds": 2.0, "text": OTHER_PHRASE,
                            "text_source": "x#signature_phrase.text",
                            "channel_name": "Test Channel", "variant": "typographic",
                            "logo_path": None}
        plan["duration"]["composition"] = 6.0
        (tmp / "plan.json").write_text(json.dumps(plan))

        graphs = []
        original = build_soundtrack.runlog.run_child

        def spy(cmd, *a, **k):
            if "-filter_complex" in cmd:
                graphs.append(cmd[cmd.index("-filter_complex") + 1])
            return original(cmd, *a, **k)

        build_soundtrack.runlog.run_child = spy
        try:
            argv = sys.argv
            sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                        str(tmp / "plan.json"), str(tmp / "mix.wav")]
            try:
                build_soundtrack.main()
            finally:
                sys.argv = argv
        finally:
            build_soundtrack.runlog.run_child = original

        assert graphs, "no filter graph was built"
        graph = graphs[-1]
        # the voice is padded to the composition, never the mix cut to the voice
        assert "apad=whole_dur=6.000" in graph, graph
        # and the bed fades across the card, from its first frame to the last
        assert "afade=t=out:st=4.000:d=2.000" in graph, graph
        assert "duration=first" in graph, "the mix still takes its length from the voice input"

        with wave.open(str(tmp / "mix.wav")) as w:
            rate, n = w.getframerate(), w.getnframes()
            import array
            data = array.array("h")
            data.frombytes(w.readframes(n))
            data = data[::w.getnchannels()]  # CF-0695: the mix is dual-mono stereo; one channel is the mix
        seconds = n / rate
        assert abs(seconds - 6.0) < 0.05, f"the mix is {seconds:.2f}s, not the card's 6.00s"
        # the card's own two seconds: the bed alone, and quieter at the end
        head = _rms_db(data[int(4.0 * rate):int(4.5 * rate)])
        tail = _rms_db(data[int(5.75 * rate):])
        assert head > -45, f"the bed is not there under the card ({head:.1f} dB)"
        assert tail < head - 10, (
            f"the bed does not fade across the card ({head:.1f} dB -> {tail:.1f} dB)")


def test_a_plan_without_a_card_mixes_exactly_as_before():
    import build_soundtrack

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _tone_wav(tmp / "voice.wav", seconds=2.0)
        (tmp / "plan.json").write_text(json.dumps(plan_for(2.0)))
        graphs = []
        original = build_soundtrack.runlog.run_child

        def spy(cmd, *a, **k):
            if "-filter_complex" in cmd:
                graphs.append(cmd[cmd.index("-filter_complex") + 1])
            return original(cmd, *a, **k)

        build_soundtrack.runlog.run_child = spy
        argv = sys.argv
        sys.argv = ["build_soundtrack.py", str(tmp / "voice.wav"),
                    str(tmp / "plan.json"), str(tmp / "mix.wav")]
        try:
            build_soundtrack.main()
        finally:
            sys.argv = argv
            build_soundtrack.runlog.run_child = original
        assert "apad" not in graphs[-1] and "afade" not in graphs[-1], graphs[-1]
        with wave.open(str(tmp / "mix.wav")) as w:
            assert abs(w.getnframes() / w.getframerate() - 2.0) < 0.05


# --------------------------------------------------------------------------
# the provenance (item 5)
# --------------------------------------------------------------------------

def _root_checks():
    if REAL_ROOT is None:
        return None
    path = REAL_ROOT / "tests" / "test_pipeline_contracts.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("test_pipeline_contracts", path)
    mod = importlib.util.module_from_spec(spec)
    # CF-0482: the root file imports its own helpers (_tmproot, CF-0378)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


ROOT_CHECKS = _root_checks()


def test_the_batch_record_carries_the_card():
    qc = {"passed": True, "failures": [], "notes": []}
    with tempfile.TemporaryDirectory() as tmp:
        card = card_for(tmp, seconds=3.0, logo=True)
        plan = plan_for(10.0)
        end_card.apply_to_plan(plan, card)
        mp4 = Path(tmp) / "video.mp4"
        mp4.write_bytes(b"\x00")
        rec = write_batch_metadata.video_record("s1", plan, str(mp4), qc, "stills")
        rec2 = write_batch_metadata.video_record("s1", plan, str(mp4), qc, "stills",
                                                 existing_inserts=rec.get("inserts"))
        field = end_card.DELIVERED_FIELD
        assert field in rec, f"{field} is written on every video"
        assert set(rec[field]) == set(end_card.DELIVERED_KEYS), rec[field]
        assert rec[field]["text"] == OTHER_PHRASE
        assert rec[field]["text_source"].endswith("#signature_phrase.text")
        assert rec[field]["seconds"] == 3.0 and rec[field]["start_s"] == 10.0
        assert rec[field]["variant"] == "logo" and rec[field]["logo_path"]
        assert rec2[field] == rec[field], "a rerun writes the same card"
        assert rec["duration"]["composition"] == 13.0

        # a plan that predates the card: the six keys, all null
        bare = copy.deepcopy(plan)
        bare.pop("end_card")
        empty = write_batch_metadata.video_record("s1", bare, str(mp4), qc, "stills")
        assert empty[field] == {k: None for k in end_card.DELIVERED_KEYS}, empty[field]

        if ROOT_CHECKS is not None:
            for v in (rec, empty):
                ctx = f"video {v['script_id']}"
                ROOT_CHECKS.require(v, ["script_id", "output_path"], ctx)
                ROOT_CHECKS.check_insert_provenance(v, ctx)
                ROOT_CHECKS.check_meme_pair(v, ctx)
                ROOT_CHECKS.check_sound_pair(v, ctx)
                ROOT_CHECKS.check_proof_provenance(v, ctx)
                ROOT_CHECKS.check_proof_pair(v, ctx)


# --------------------------------------------------------------------------
# the card in the composition
# --------------------------------------------------------------------------

def test_the_card_is_its_own_layer_and_owns_the_frame():
    comp = (RENDER_SRC / "components" / "EndCard.jsx").read_text()
    video = (RENDER_SRC / "Video.jsx").read_text()
    root = (RENDER_SRC / "Root.jsx").read_text()

    assert "export const EndCard" in comp
    # both variants, and the typographic one needs no file
    assert "card.variant === 'logo'" in comp and "card.logo_path" in comp
    assert "card.channel_name" in comp
    # the phrase is drawn as the stance wrote it
    assert "toUpperCase" not in comp.split("channel_name")[0]
    # a fade in, and no fade out onto black at the end of the video
    assert "FADE_IN_SECONDS = 0.3" in comp
    # mounted over its own frame range, off the plan's field
    assert "EndCard" in video and "plan.end_card" in video
    # CF-0141: the lead is a variable now (0 for the channel's own clip,
    # CROSSFADE for a card this repo draws) - but it is still CROSSFADE for
    # the card, which is what this test is about.
    assert "card.start_s - cardLead) * fps" in video
    assert "card.seconds + cardLead) * fps" in video
    assert "cardLead = isClipEnding ? 0 : CROSSFADE" in video
    # the watermark stops under it, and no caption can be caught over it
    assert "onCard ? null : (" in video, "the watermark still draws over the card"
    assert "cardRanges" in video and "hiddenRanges={cardRanges}" in video
    # the composition is as long as the plan says, not as long as the voice
    assert "duration?.composition" in root, root


def test_the_two_faults_the_first_render_found():
    """Both were found by CF-0117's first real render and both would have
    shipped silently otherwise."""
    captions = (RENDER_SRC / "components" / "Captions.jsx").read_text()
    memo = captions.index("React.useMemo")
    guard = captions.index("hiddenRanges ?? []")
    assert memo < guard, (
        "Captions.jsx returns null for a hidden range before its useMemo runs - "
        "the frame the range opens on renders fewer hooks than the one before "
        "it and React throws #300, which killed the whole render the first time "
        "the end card came up")

    video = (RENDER_SRC / "Video.jsx").read_text()
    # CF-0141 kept this fix and gave it a second form. A *drawn* card is
    # still mounted CROSSFADE early - `cardLead` is CROSSFADE unless the
    # ending is a clip - and the clip, which cannot be mounted early without
    # spending somebody else's opening frames under our dissolve, gets the
    # other half of the same fix: the outgoing block holds instead of fading.
    # Measured on a 5 s seam render, 2026-09-08: with the hold, no black run
    # anywhere in the file (blackdetect d=0.03 pix_th=0.10 silent) and the
    # cut is one frame, mean luma 122.4 -> 157.0; with the hold removed the
    # last ten frames ramp 122.4 -> 21.8 and blackdetect reports
    # black_start:2.967 black_duration:0.033. The lead alone does not fix the
    # seam - it moves it.
    assert "cardLead = isClipEnding ? 0 : CROSSFADE" in video, (
        "the card is mounted exactly at start_s again - its fade-in then "
        "follows the last block's fade-out instead of covering it, and the "
        "first render measured 0.17s of full black between the last frame of "
        "the video and the channel's signature")
    assert "hardCutAt - 1e-6) return inFade" in video, (
        "the block before the channel's ending clip fades out again - with "
        "no dissolve of ours over the clip, that fade goes to the "
        "composition's near-black background and puts a black run under the "
        "gate exactly where CF-0117's did")


def test_nothing_of_ours_survives_into_the_card_s_fade_in():
    """The card is mounted CROSSFADE before `start_s` (the fault above), so
    every range that used to end at `start_s` now ends 0.35 s too late. Both
    of our own text layers are clipped to the frame the card mounts on -
    `cardFrom` - and not to the phrase's nominal start.

    The captions' range is the cheap half: the last word ends before the
    narration does, so it suppresses nothing today. The comparison line is
    the half that actually bites - comparison_line.py clamps a line to
    `duration.actual`, which IS `card.start_s` (end_card.narration_end reads
    the same `audio.duration`), and holds it to a 2.0 s floor besides, so the
    last beat's annotation reliably runs to the narration's last frame and
    would sit over the signature for the whole dissolve.
    """
    video = (RENDER_SRC / "Video.jsx").read_text()

    # the captions' hidden range opens on the mount frame, not at start_s
    card_range = video.split("const cardRanges = card")[1].split("hiddenCaptionRanges;")[0]
    assert "start: cardFrom / fps" in card_range, (
        "the card's hidden caption range starts at the phrase's nominal "
        f"start again, 0.35s after the card is on screen: {card_range!r}")
    assert "start: card.start_s" not in card_range, card_range

    # the comparison line cannot outlive that same frame
    lines = video.split("plan.comparison_lines ?? []")[1].split("<Captions")[0]
    assert "cardFrom" in lines, (
        "CF-0116's comparison line is not clipped to the card - the last "
        "beat's line is clamped to duration.actual == card.start_s and the "
        "card now mounts 0.35s before that, so our annotation is drawn over "
        "the channel's signature for the whole fade-in")
    assert "Math.min(" in lines and "until <= from" in lines, (
        "the line's window is clipped but a line left with nothing before "
        f"the card is still mounted: {lines!r}")
    # and the clip must not be read off the un-shifted start
    assert "card.start_s" not in lines, lines


def test_the_render_gate_measures_the_composition():
    src = (SCRIPTS / "qc_render.py").read_text()
    head = src.split("v_dur = float(")[1].split("blacks = detect(")[0]
    assert '"composition"' in head, (
        "qc_render.py still measures the picture against the voice alone - "
        "every video with an end card would fail as adrift")
    assert "end card" in head


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
