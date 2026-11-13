#!/usr/bin/env python3
"""CF-0188: the channel's voice, read from the channel's config.

`voice_profile` used to be a dead field. `channels/<id>.json` carried
`"voice_profile": "default-v1"` and that string was its only occurrence in
the whole factory - nothing read it. The real voice was three hard-coded
defaults in three places: `--voice am_puck` / `--speed 0.95` in
synthesize_voiceover.py, the literal `"am_puck (speed 0.95)"` written into
every batch record by write_batch_metadata.py, and the rate constant behind
`words_per_second`. "Make the host sound faster" was therefore not an edit to
a config - it was an edit to the scripts, in three places, with nothing
holding them together.

This module is the one place that answers "which voice does this channel read
in, and how fast". Everything that needs the answer asks here.

The shape it reads (in `channels/<id>.json`):

    "voice_profile": {
      "engine": "kokoro",
      "voice": "am_fenrir",
      "speed": 1.05,
      "lang": "a"
    }

`engine` is the TTS this factory runs; `kokoro` is the only one it knows, and
a profile naming another is refused rather than handed to Kokoro anyway.
`voice` is a Kokoro voice id, `speed` its speed multiplier, `lang` its
`lang_code` ('a' American English, 'b' British). Any `*_note` key beside them
is prose for the reader and is ignored here.

**The legacy string is legal, deliberately.** A channel whose `voice_profile`
is still the old `"default-v1"` - or has no such key at all - reads in the
defaults below, which are exactly the voice and speed every video published so
far was read in. That is not a soft fallback "just in case": the object lands
in the channel config as a separate commit in a separate repository from this
code, and between the two commits both states have to work. It stays legal
afterwards too, because it is what an old batch record means when it says the
voice was am_puck.

What is NOT forgiven is a profile that says something and says it wrong: an
object whose `voice` is not a name, whose `speed` is not a positive number, or
whose `engine` is not Kokoro is a config error and is refused in writing.
Falling back to am_puck there would read a channel in a voice its config
explicitly did not ask for, and the mistake would only surface as a finished
video that sounds wrong.
"""
import json
from pathlib import Path

FIELD = "voice_profile"

#: What a channel that does not (yet) carry an object is read in - the voice
#: and speed of every batch published up to CF-0188, and the provenance of
#: `words_per_second` as `channels/<id>.json` records it.
DEFAULT_ENGINE = "kokoro"
DEFAULT_VOICE = "am_puck"
DEFAULT_SPEED = 0.95
DEFAULT_LANG = "a"

DEFAULTS = {
    "engine": DEFAULT_ENGINE,
    "voice": DEFAULT_VOICE,
    "speed": DEFAULT_SPEED,
    "lang": DEFAULT_LANG,
}

#: Where a resolved profile came from, so a caller can say so in a log or a
#: record instead of leaving the reader to guess whether the channel chose
#: the voice or inherited it.
SOURCE_CHANNEL = "channel voice_profile"
SOURCE_DEFAULT = "built-in default (channel carries no voice_profile object)"


class VoiceProfileError(ValueError):
    """A `voice_profile` object that declares something unusable."""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def resolve(channel_cfg):
    """The voice this channel is read in: `{engine, voice, speed, lang, source}`.

    `channel_cfg` is a loaded channel config (or None - a caller with no
    channel gets the defaults, which is what every call site did before this
    module existed). A `voice_profile` that is absent, null or a string is the
    pre-CF-0188 state and reads as the defaults; an object is read key by key,
    with the defaults filling in the keys it does not mention.
    """
    profile = (channel_cfg or {}).get(FIELD) if isinstance(channel_cfg, dict) else None
    if not isinstance(profile, dict):
        # Absent, null, or the legacy "default-v1" string. Both the state the
        # config is in before the object lands and what an old record means.
        return dict(DEFAULTS, source=SOURCE_DEFAULT)

    resolved = dict(DEFAULTS, source=SOURCE_CHANNEL)

    if "engine" in profile:
        engine = profile["engine"]
        if not isinstance(engine, str) or engine.strip().lower() != DEFAULT_ENGINE:
            raise VoiceProfileError(
                f"{FIELD}.engine is {engine!r}; this factory synthesizes with "
                f"{DEFAULT_ENGINE!r} and nothing else. Remove the key or say "
                f"{DEFAULT_ENGINE!r} - it will not hand another engine's voice to Kokoro.")
        resolved["engine"] = DEFAULT_ENGINE

    if "voice" in profile:
        voice = profile["voice"]
        if not isinstance(voice, str) or not voice.strip():
            raise VoiceProfileError(
                f"{FIELD}.voice is {voice!r}, which is not a Kokoro voice id. "
                f"Write a name (e.g. {DEFAULT_VOICE!r}) or drop the key to read "
                f"in {DEFAULT_VOICE!r}.")
        resolved["voice"] = voice.strip()

    if "speed" in profile:
        speed = profile["speed"]
        if not _is_number(speed) or speed <= 0:
            raise VoiceProfileError(
                f"{FIELD}.speed is {speed!r}, which is not a speed. Write a "
                f"positive number (today's voice reads at {DEFAULT_SPEED}) or "
                f"drop the key.")
        resolved["speed"] = float(speed)

    if "lang" in profile:
        lang = profile["lang"]
        if not isinstance(lang, str) or not lang.strip():
            raise VoiceProfileError(
                f"{FIELD}.lang is {lang!r}, which is not a Kokoro lang_code "
                f"('a' American English, 'b' British). Drop the key to read in "
                f"{DEFAULT_LANG!r}.")
        resolved["lang"] = lang.strip()

    return resolved


def load(channel, root=None):
    """resolve() for a caller that has a channel id rather than a loaded config.

    `channel` is a channel id or a path to a `.json`; a channel whose file is
    missing or unreadable reads as no channel at all - the defaults - which is
    the same reading meme_layer.load_channel() gives every other layer.
    """
    if not channel:
        return resolve(None)
    if root is None:
        import meme_layer
        root = meme_layer.factory_root()
    path = Path(channel) if str(channel).endswith(".json") \
        else Path(root) / "channels" / f"{channel}.json"
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        cfg = None
    return resolve(cfg)


def describe(profile):
    """`am_puck (speed 0.95)` - the one-line form batch records carry.

    Takes a resolved profile or a whole channel config, so a caller that has
    either can write the line without resolving twice.
    """
    if not isinstance(profile, dict) or "voice" not in profile:
        profile = resolve(profile)
    return f"{profile['voice']} (speed {float(profile['speed']):.2f})"
