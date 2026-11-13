#!/usr/bin/env python3
"""Synthesize voiceover audio via Kokoro TTS (local, free, Apache-2.0 licensed).
Why Kokoro over paid providers was never recorded; the voice and speed
within Kokoro were chosen by measurement, recorded in CF-0188 and in
`voice_profile_note` of channels/example-film.json.

Usage: synthesize_voiceover.py "<text>" <output.wav> [--channel example-film]
       [--voice am_puck] [--speed 0.95] [--lang a] [--lead-silence 0.7]

CF-0188: which voice and how fast is the channel's, not this script's.
`--channel` reads `voice_profile` out of `channels/<id>.json` (see
scripts/voice_profile.py for the shape and for why the legacy string reads as
am_puck @0.95). `--voice`/`--speed`/`--lang` still win when given - that is how
a voice is auditioned - and a call with no `--channel` at all reads in the same
voice it always did.

Text should already be written with prosody in mind: short sentences, commas
for breath, "..." for a dramatic pause, "—" for a light parenthetical break,
numbers spelled out. Kokoro's only real prosody controls are punctuation and
chunk length — see SKILL.md Notes for why this matters more than voice choice.

CF-0261: the text read here is written out beside the wav as `narration.txt`,
verbatim. It is evidence, not a convenience. Kokoro synthesizes a chunk per
line, so the LAYOUT of this text sets the speaking rate as much as the voice
does — the same 181 words read 58.9 s as five paragraphs and 44.5 s on one
line — and `narration_budget.words_per_second`, which the whole word budget
and every length gate hang on, is a measurement of one voice reading one
layout. Without the file on disk a finished batch cannot be re-measured at
all: that is how the rate stayed at 3.02 while the pipeline had moved to 3.88,
and two videos went under the 45 s floor before anyone could check.
`measure_speaking_rate.py` reads this file first, and rebuilds the join from
the batch's scripts only when it is missing.
"""
import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
import voice_profile  # noqa: E402 - CF-0188: the channel's voice, not this script's

warnings.filterwarnings("ignore")


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("text")
    p.add_argument("output")
    p.add_argument("--channel", default=None,
                   help="channel id (or path to a channels/<id>.json) whose "
                        "voice_profile says which voice reads this and how fast "
                        "(CF-0188). Without it the built-in default voice reads.")
    p.add_argument("--voice", default=None,
                   help=f"Kokoro voice id; overrides the channel's "
                        f"voice_profile.voice (default {voice_profile.DEFAULT_VOICE})")
    p.add_argument("--speed", type=float, default=None,
                   help=f"overrides the channel's voice_profile.speed "
                        f"(default {voice_profile.DEFAULT_SPEED})")
    p.add_argument("--lang", default=None,
                   help="'a' = American English, 'b' = British English, see Kokoro docs "
                        "for others; overrides the channel's voice_profile.lang")
    p.add_argument("--lead-silence", type=float, default=0.0,
                   help="seconds of silence before the first word (CF-0050). This is "
                        "the cold_frame opening: the frame is held alone for this "
                        "long before the hook lands on it. Spent from the duration "
                        "budget, not added to it.")
    return p


def resolve_voice(args, root=None):
    """CF-0188: the channel's profile, with any explicit flag laid over it.

    Returns the resolved `{engine, voice, speed, lang, source}`; `source` says
    whether the channel chose the voice or inherited the default, and the log
    line below says so out loud so that a wav can be traced to a config."""
    resolved = voice_profile.load(args.channel, root)
    for key in ("voice", "speed", "lang"):
        given = getattr(args, key)
        if given is not None:
            resolved[key] = given
            resolved["source"] = "command line"
    return resolved


def record_narration(text, output):
    """CF-0261: write the text this run reads beside the wav it reads it into.

    `work/<slug>/voice.wav` gets `work/<slug>/narration.txt`, the name
    `measure_speaking_rate.py` looks for; any other output name gets
    `<stem>.narration.txt`, so auditioning three takes into one directory
    leaves three records rather than one overwritten three times.

    Written before the synthesis, not after it: a wav whose narration is
    missing because the run died late is exactly the batch that most needs
    re-measuring. Verbatim, with the line breaks - they are the variable this
    file exists to preserve. A directory that cannot be written to costs a
    warning, never the voiceover.
    """
    out = Path(output)
    dest = out.parent / ("narration.txt" if out.stem == "voice"
                         else f"{out.stem}.narration.txt")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"TTS: WARNING: narration not recorded ({dest}): {e}", file=sys.stderr)
        return None
    return dest


def main():
    p = build_parser()
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.output))  # CF-0107: slug from work/<slug>/voice.wav
    if args.lead_silence < 0:
        p.error("--lead-silence cannot be negative")
    try:
        voice = resolve_voice(args)
    except voice_profile.VoiceProfileError as e:
        # A channel that says something unusable about its voice is not read
        # in some other voice - the run stops and says which key is wrong.
        print(f"TTS: ERROR: channel {args.channel!r}: {e}", file=sys.stderr)
        sys.exit(2)
    args.voice, args.speed, args.lang = voice["voice"], voice["speed"], voice["lang"]
    print(f"voice {voice['voice']} @ speed {voice['speed']:g} "
          f"(lang {voice['lang']}, from {voice['source']})", file=sys.stderr)
    recorded = record_narration(args.text, args.output)
    if recorded:
        print(f"narration -> {recorded}", file=sys.stderr)

    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    # CF-0107: the model load and the synthesis are the two `kokoro` children -
    # the load is the cold-start cost, the synthesis scales with the text.
    with runlog.child("kokoro", argv=["kokoro", "load", args.lang], params={"lang": args.lang}):
        pipeline = KPipeline(lang_code=args.lang)
    with runlog.child("kokoro", argv=["kokoro", "synth", args.voice],
                      params={"voice": args.voice, "speed": args.speed, "chars": len(args.text)}):
        chunks = [audio for _, _, audio in pipeline(args.text, voice=args.voice, speed=args.speed)]
    full = np.concatenate(chunks)
    if args.lead_silence:
        # Real samples, not a container-level offset: whisper-cli, ffprobe and
        # ffmpeg's silencedetect all have to see the same beat, and only actual
        # zero samples are visible to all three.
        lead = np.zeros(int(round(args.lead_silence * 24000)), dtype=full.dtype)
        full = np.concatenate([lead, full])
    sf.write(args.output, full, 24000)
    print(f"{len(full) / 24000:.2f}s -> {args.output}"
          + (f" ({args.lead_silence:.2f}s of it a silent lead)"
             if args.lead_silence else ""))


@video_script("video-editor", "tts", name="synthesize_voiceover.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()
