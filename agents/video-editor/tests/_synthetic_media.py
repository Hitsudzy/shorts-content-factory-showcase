"""CF-0522: media of the shape the 2155Z regressions were found on, built in a
temp directory by the test that needs it.

The JSON of the 2155Z runs is frozen (tests/fixtures/frozen_batches, CF-0519);
its media - the batch's clips, voice.wav, held PNGs and rendered mp4s - is not,
and since CF-0500 carried that batch to the archive the live monitors that
read it checked nothing. These builders make the same SHAPE (a clip of a given
length that moves or holds, a voice whose speech starts after a given lead, a
PNG of a given size, a short mp4) with ffmpeg's lavfi sources and `wave`, so
the regressions run in the ordinary suite: no network, no live data, a few
seconds of encoding.

    import _synthetic_media as syn
    syn.moving_clip(tmp / "a.mp4", 3.0)          # testsrc2, moves everywhere
    syn.held_clip(tmp / "h.mp4", 1.1)            # one frame held: a drawn pose
    syn.voice(tmp / "voice.wav", 8.0, lead=0.9)  # silence, then a speech-like tone
    syn.png(tmp / "f.png", 1280, 720)
    syn.words(12, start=0.5, step=0.6)           # words.json rows
    syn.storyboard_block(src, 0.0, 1.2)          # one storyboard block on a clip
    syn.env(tmp)                                 # subprocess env: FOOTAGE_DIR -> tmp
"""
import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import FFMPEG  # noqa: E402

SIZE = "640x360"   # 16:9 source, like the trailers the pool cuts from
RATE = 25


def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *args],
                   check=True, capture_output=True)


def moving_clip(path, seconds, size=SIZE, rate=RATE):
    """A clip of exactly `seconds` that moves everywhere (testsrc2): a probe
    that lands on it can never read as held footage."""
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size={size}:rate={rate}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path))
    return str(path)


def held_clip(path, seconds, size=SIZE, rate=RATE):
    """A clip of exactly `seconds` whose every frame is the same textured frame
    - a drawn held pose (CF-0004): the source itself does not move."""
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=duration=0.04:size={size}:rate={rate}",
            "-vf", f"tpad=stop_mode=clone:stop_duration={seconds}",
            "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "ultrafast", str(path))
    return str(path)


def video_with_audio(path, seconds, size="540x960", rate=RATE):
    """A short rendered-video stand-in (picture and a sound track)."""
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size={size}:rate={rate}",
            "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
            "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", str(path))
    return str(path)


def png(path, width, height):
    """A PNG of `width` x `height` with texture in it (a held frame)."""
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=1",
            "-frames:v", "1", str(path))
    return str(path)


def voice(path, seconds, lead=0.0, rate=16000, amplitude=6000):
    """A mono 16-bit wav of `seconds`: `lead` seconds of digital silence, then
    a speech-like tone (a 220 Hz sine under a 4 Hz syllable envelope) to the
    end. `common.leading_silence()` measures `lead` off it."""
    import math
    n_lead = int(round(lead * rate))
    n = int(round(seconds * rate))
    frames = bytearray()
    for i in range(n):
        if i < n_lead:
            v = 0
        else:
            t = (i - n_lead) / rate
            env = 0.55 + 0.45 * math.sin(2 * math.pi * 4 * t)
            v = int(amplitude * env * math.sin(2 * math.pi * 220 * t))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return str(path)


def words(n, start=0.5, step=0.6, length=0.4):
    return [{"word": f"w{i}", "start": round(start + i * step, 3),
             "end": round(start + i * step + length, 3)} for i in range(n)]


def storyboard_block(src, start, end, word_range=(0, 0), shot=None, **extra):
    block = {"word_range": list(word_range), "intent": f"clip {Path(src).name}",
             "asset_kind": "clip", "asset": str(src), "emphasis_words": [],
             "rhythm_role": "beat", "side": None,
             "shot": shot or Path(src).stem, "held_frame": False,
             "_start": start, "_end": end}
    block.update(extra)
    return block


def storyboard(blocks, **extra):
    story = {"script_id": "synthetic", "style": "motion",
             "resolved_from_anchors": True, "blocks": blocks,
             "unresolved_anchors": [], "rejected_candidates": []}
    story.update(extra)
    return story


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=1))
    return Path(path)


def env(tmp):
    """The environment for a planner subprocess: the pool it reads for shot
    lengths (FOOTAGE_DIR) is an empty dir under `tmp`, never the live one."""
    e = dict(os.environ)
    pool = Path(tmp) / "pool"
    pool.mkdir(exist_ok=True)
    e["FOOTAGE_DIR"] = str(pool)
    return e
