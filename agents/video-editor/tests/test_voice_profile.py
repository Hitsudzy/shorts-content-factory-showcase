#!/usr/bin/env python3
"""CF-0188: `voice_profile` is a field the channel is actually read in.

Before this, `"voice_profile": "default-v1"` in the channel config was the
string's only occurrence in the factory and nothing read it; the voice lived
as `--voice am_puck` / `--speed 0.95` in synthesize_voiceover.py and as the
literal `"am_puck (speed 0.95)"` in write_batch_metadata.py. Changing the
host's voice was an edit to scripts, not to a config.

What is locked here:

  * an object in the channel config decides the voice, the speed and the
    Kokoro lang_code, and synthesize_voiceover.py reads it;
  * the legacy string `"default-v1"`, a null and a missing key all read as
    today's voice - this is the state the root repository is in between the
    two commits of CF-0188, and it has to work in both;
  * an explicit `--voice`/`--speed` on the command line still wins, because
    that is how a voice is auditioned;
  * a profile that declares something unusable - a speed that is not a
    number, an engine that is not Kokoro - refuses by name instead of quietly
    reading the channel in a voice it did not ask for;
  * the batch record's `voice_profile_used` is built from the same resolver,
    so the record cannot claim a voice the synthesis did not use.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
_TMP = tmp_root("ve-voice-")
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import voice_profile as vp                      # noqa: E402
import synthesize_voiceover as sv               # noqa: E402


def channel_root(profile="__absent__"):
    """A factory root with one channel whose voice_profile is as given."""
    root = Path(tempfile.mkdtemp(dir=_TMP))
    (root / "channels").mkdir()
    cfg = {"channel_id": "test", "display_name": "Test"}
    if profile != "__absent__":
        cfg["voice_profile"] = profile
    (root / "channels" / "test.json").write_text(json.dumps(cfg))
    return root


# --- the pre-CF-0188 states all read as today's voice ------------------------

def test_the_legacy_string_reads_as_todays_voice():
    """`"voice_profile": "default-v1"` is what the root repository carries
    while this code lands. It is not an error and it is not a new voice."""
    got = vp.resolve({"voice_profile": "default-v1"})
    assert got["voice"] == "am_puck", got
    assert got["speed"] == 0.95, got
    assert got["lang"] == "a", got
    assert got["source"] == vp.SOURCE_DEFAULT, got


def test_a_missing_key_a_null_and_no_config_all_read_the_same():
    for cfg in ({}, {"voice_profile": None}, None):
        got = vp.resolve(cfg)
        assert (got["voice"], got["speed"]) == ("am_puck", 0.95), (cfg, got)
        assert got["source"] == vp.SOURCE_DEFAULT, (cfg, got)


def test_the_defaults_are_the_voice_every_published_batch_was_read_in():
    """The voice CF-0087 measured `words_per_second` on. If these move, the
    rate in channels/<id>.json is describing a voice nobody reads in."""
    assert vp.DEFAULT_VOICE == "am_puck", vp.DEFAULT_VOICE
    assert vp.DEFAULT_SPEED == 0.95, vp.DEFAULT_SPEED
    assert vp.DEFAULT_ENGINE == "kokoro", vp.DEFAULT_ENGINE


# --- the object decides ------------------------------------------------------

def test_the_object_decides_voice_speed_and_lang():
    got = vp.resolve({"voice_profile": {"engine": "kokoro", "voice": "am_fenrir",
                                        "speed": 1.05, "lang": "b"}})
    assert got["voice"] == "am_fenrir", got
    assert got["speed"] == 1.05, got
    assert got["lang"] == "b", got
    assert got["source"] == vp.SOURCE_CHANNEL, got


def test_keys_the_object_does_not_mention_keep_the_default():
    got = vp.resolve({"voice_profile": {"voice": "am_michael"}})
    assert got["voice"] == "am_michael", got
    assert got["speed"] == 0.95, got
    assert got["lang"] == "a", got


def test_note_keys_beside_the_values_are_prose_and_are_ignored():
    got = vp.resolve({"voice_profile": {"voice": "am_fenrir", "speed": 1.05,
                                        "voice_note": "why this voice",
                                        "speed_note": "why this speed"}})
    assert (got["voice"], got["speed"]) == ("am_fenrir", 1.05), got


def test_an_int_speed_is_a_speed():
    assert vp.resolve({"voice_profile": {"speed": 1}})["speed"] == 1.0


# --- a profile that says something wrong refuses -----------------------------

def test_a_speed_that_is_not_a_number_refuses_by_name():
    for bad in ("fast", None, 0, -1, True, [1.05]):
        try:
            vp.resolve({"voice_profile": {"speed": bad}})
        except vp.VoiceProfileError as e:
            assert "speed" in str(e), (bad, str(e))
        else:
            raise AssertionError(f"speed={bad!r} was accepted")


def test_a_voice_that_is_not_a_name_refuses():
    for bad in ("", "  ", 7, None):
        try:
            vp.resolve({"voice_profile": {"voice": bad}})
        except vp.VoiceProfileError as e:
            assert "voice" in str(e), (bad, str(e))
        else:
            raise AssertionError(f"voice={bad!r} was accepted")


def test_another_engine_is_refused_rather_than_handed_to_kokoro():
    try:
        vp.resolve({"voice_profile": {"engine": "elevenlabs", "voice": "rachel"}})
    except vp.VoiceProfileError as e:
        assert "elevenlabs" in str(e), str(e)
    else:
        raise AssertionError("a non-Kokoro engine was accepted")


def test_kokoro_spelled_with_capitals_is_still_kokoro():
    assert vp.resolve({"voice_profile": {"engine": "Kokoro"}})["engine"] == "kokoro"


# --- loading by channel id ---------------------------------------------------

def test_load_reads_the_channel_file():
    root = channel_root({"voice": "am_fenrir", "speed": 1.05})
    got = vp.load("test", root)
    assert (got["voice"], got["speed"]) == ("am_fenrir", 1.05), got


def test_a_channel_with_no_file_reads_the_defaults():
    root = channel_root()
    got = vp.load("nosuchchannel", root)
    assert (got["voice"], got["speed"]) == ("am_puck", 0.95), got
    assert vp.load(None, root)["voice"] == "am_puck"


def test_the_real_channel_config_is_readable_in_either_state():
    """The root repository's own file, whichever state CF-0188 has it in: it
    resolves either way, and the two legal readings are today's voice (the
    legacy string) or the object's."""
    cfg_path = AGENT_ROOT.parents[1] / "channels" / "example-film.json"
    if not cfg_path.exists():
        return                                  # not the factory checkout
    cfg = json.loads(cfg_path.read_text())
    raw = cfg.get("voice_profile")
    assert raw is None or isinstance(raw, (str, dict)), \
        f"voice_profile is a {type(raw).__name__}"
    got = vp.resolve(cfg)
    assert isinstance(got["voice"], str) and got["voice"], got
    assert got["speed"] > 0, got
    if isinstance(raw, dict):
        assert got["source"] == vp.SOURCE_CHANNEL, got
    else:
        assert (got["voice"], got["speed"]) == ("am_puck", 0.95), got


# --- the one-line form the batch record carries ------------------------------

def test_describe_writes_the_line_the_records_have_always_carried():
    assert vp.describe(vp.resolve(None)) == "am_puck (speed 0.95)", \
        vp.describe(vp.resolve(None))
    assert vp.describe({"voice": "am_fenrir", "speed": 1.05}) == "am_fenrir (speed 1.05)"
    assert vp.describe({"voice_profile": {"voice": "am_michael", "speed": 1.0}}) \
        == "am_michael (speed 1.00)"


def test_write_batch_metadata_builds_the_line_from_the_resolver():
    """Not a second copy of the string: the record is built from the same
    module, so a channel that changes its voice cannot end up with a record
    naming the old one."""
    src = (SCRIPTS / "write_batch_metadata.py").read_text()
    assert '"am_puck (speed' not in src, \
        "write_batch_metadata.py still writes the voice as a literal"
    assert "voice_profile.describe" in src, \
        "write_batch_metadata.py does not build the line from voice_profile"


# --- synthesize_voiceover reads the channel ----------------------------------

def test_synthesize_voiceover_no_longer_hard_codes_the_voice():
    src = (SCRIPTS / "synthesize_voiceover.py").read_text()
    assert 'default="am_puck"' not in src, \
        "synthesize_voiceover.py still defaults --voice to am_puck"
    assert "voice_profile" in src, "synthesize_voiceover.py does not read voice_profile"


def resolved(root, argv):
    """What synthesize_voiceover.py would hand Kokoro, without synthesizing."""
    return sv.resolve_voice(sv.build_parser().parse_args(argv), root=root)


def test_the_channel_decides_when_the_command_line_does_not():
    root = channel_root({"voice": "am_fenrir", "speed": 1.05, "lang": "b"})
    got = resolved(root, ["some text", "/tmp/out.wav", "--channel", "test"])
    assert (got["voice"], got["speed"], got["lang"]) == ("am_fenrir", 1.05, "b"), got
    assert got["source"] == vp.SOURCE_CHANNEL, got


def test_an_explicit_flag_still_wins_because_that_is_how_a_voice_is_auditioned():
    root = channel_root({"voice": "am_fenrir", "speed": 1.05})
    got = resolved(root, ["t", "/tmp/o.wav", "--channel", "test",
                          "--voice", "am_michael", "--speed", "1.2"])
    assert (got["voice"], got["speed"]) == ("am_michael", 1.2), got


def test_no_channel_on_the_command_line_is_todays_call_and_todays_voice():
    root = channel_root({"voice": "am_fenrir", "speed": 1.05})
    got = resolved(root, ["t", "/tmp/o.wav"])
    assert (got["voice"], got["speed"], got["lang"]) == ("am_puck", 0.95, "a"), got


def test_a_broken_profile_stops_the_synthesis_instead_of_reading_it_aloud():
    root = channel_root({"voice": "am_fenrir", "speed": "fast"})
    out = subprocess.run([sys.executable, str(SCRIPTS / "synthesize_voiceover.py"),
                          "hello", str(Path(tempfile.mkdtemp(dir=_TMP)) / "o.wav"),
                          "--channel", "test"],
                         capture_output=True, text=True,
                         env={**os.environ, "FACTORY_ROOT": str(root)})
    assert out.returncode != 0, f"exit={out.returncode}"
    assert "speed" in (out.stderr + out.stdout), (out.returncode, out.stderr[-400:])


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
