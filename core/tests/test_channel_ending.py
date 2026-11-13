#!/usr/bin/env python3
"""CF-0722: the channel's ending as data - `channels/<id>/brand.json` ->
`ending` (shared/channel_data.py `ending`, `ending_errors`, `ending_file`) and
`scripts/brand_ending.py <channel>` reading it when its flags are not given.

What is pinned:

  * the section's rule (`ending_errors`) and the reader: no brand.json or no
    section is None (the readers keep their old defaults), a broken one is a
    refusal with a code;
  * a file the section names is used only when its bytes are the recorded
    sha256: a swapped track or clip is `ending_sha256_mismatch`, an absent
    one `ending_file_missing`;
  * compatibility, per channel that has a generator (example-science,
    example-tech): the ffmpeg command brand_ending.py runs with the flags the
    channel's SOURCES.md records ("the command that made the file") is the
    command it runs with no flags at all, from the data - byte for byte, and
    both are the command of the CF-0565 code before this change (a frozen
    copy below). example-film has no generator (made by hand, CF-0141) and
    carries the clip and its sha256 only;
  * the real brand.json files are valid, record the sha256 SOURCES.md records
    for the track, and the sha256 of the clip in the tree.

Every render-path case runs on a stand-in root in a temp directory (a
stand-in track, empty font files) and stops at the ffmpeg call - nothing is
rendered, no network.
"""
import contextlib
import importlib.util
import io
import json
import re
import shlex
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANNELS = ("example-film", "example-science", "example-tech")
GENERATED = ("example-science", "example-tech")
SOURCES_DOC = {"example-science": "beds/SOURCES.md", "example-tech": "SOURCES.md"}


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load(ROOT / "shared" / "channel_data.py", "channel_data_for_ending_test")
be = _load(ROOT / "scripts" / "brand_ending.py", "brand_ending_for_ending_test")


def old_command(audio, audio_start, audio_gain_db, out):
    """Frozen copy of brand_ending.main()'s command before CF-0722 (0f2519c),
    with argparse's float() of the flags."""
    FRAMES, FPS, W, H = 155, 30, 1080, 1920
    audio_start, audio_gain_db = float(audio_start), float(audio_gain_db)
    seconds = FRAMES / FPS
    af = (f"volume={audio_gain_db}dB,afade=t=in:st=0:d=0.4,"
          f"afade=t=out:st={seconds - 1.4:.3f}:d=1.4")
    return ["ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-ss", str(audio_start), "-t", f"{seconds:.6f}", "-i", str(audio),
            "-map", "0:v", "-map", "1:a", "-af", af,
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "18",
            "-preset", "slow", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-map_metadata", "-1", "-movflags", "+faststart", "-shortest", str(out)]






class _Stop(Exception):
    pass


def command_of_main(argv, root):
    """The ffmpeg command main() would start - Popen is stopped at the call."""
    seen = []

    def fake_popen(cmd, *a, **kw):
        seen.append(list(cmd))
        raise _Stop()

    saved = be.subprocess.Popen
    be.subprocess.Popen = fake_popen
    try:
        be.main(argv, root=root)
    except _Stop:
        pass
    finally:
        be.subprocess.Popen = saved
    assert len(seen) == 1, (argv, seen)
    return seen[0]


def refusal_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except (cd.EndingError, be.EndingRefused) as e:
        return e
    raise AssertionError("expected a refusal")


# ------------------------------------------------------------ the data rule
GOOD = {"clip": "channels/x/ending.mp4", "clip_sha256": "a" * 64,
        "render": {"fonts": "shared/brand/fonts", "track": "channels/x/brand/t.mp3",
                   "track_sha256": "b" * 64, "audio_start": 120, "audio_gain_db": 0.2}}


def test_the_section_rule():
    assert cd.ending_errors(GOOD) == []
    assert cd.ending_errors(dict(GOOD, render=None)) == []
    assert cd.ending_errors({k: v for k, v in GOOD.items() if k != "render"}) == []
    bad = json.loads(json.dumps(GOOD))
    bad["clip"] = "/home/me/ending.mp4"
    bad["clip_sha256"] = "XYZ"
    bad["extra"] = 1
    bad["render"]["track"] = "../outside.mp3"
    bad["render"]["audio_start"] = -1
    bad["render"]["audio_gain_db"] = "loud"
    del bad["render"]["track_sha256"]
    errs = " | ".join(cd.ending_errors(bad))
    for part in ("ending.clip", "clip_sha256", "unknown key `extra`", "ending.render.track",
                 "no `track_sha256`", "audio_start", "audio_gain_db"):
        assert part in errs, (part, errs)
    assert cd.ending_errors([]) == ["`ending` is not an object"]
    assert "neither an object nor null" in cd.ending_errors(dict(GOOD, render=3))[0]




def test_a_swapped_or_absent_file_is_refused_by_name():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / "channels" / "x" / "ending.mp4"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"the recorded clip")
        sha = cd.file_sha256(f)
        assert cd.ending_file("channels/x/ending.mp4", sha, root) == f
        f.write_bytes(b"somebody else's clip")
        e = refusal_of(cd.ending_file, "channels/x/ending.mp4", sha, root, what="ending clip")
        assert e.code == cd.ENDING_SHA256_MISMATCH == "ending_sha256_mismatch"
        assert str(e).startswith("ending_sha256_mismatch: the ending clip") and sha in str(e)
        f.unlink()
        e = refusal_of(cd.ending_file, "channels/x/ending.mp4", sha, root)
        assert e.code == cd.ENDING_FILE_MISSING == "ending_file_missing", str(e)


# ------------------------------------------------------------ the real data


# ------------------------------------------------------------ compatibility










if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
