#!/usr/bin/env python3
"""CF-0261: the text that went to the voice is on disk, and the rate tool reads it.

`narration_budget.words_per_second` is a measurement of one voice at one speed -
and, as CF-0261 found the hard way, of one LAYOUT of the narration: Kokoro
synthesizes a chunk per line, so the same 181 words read 58.9 s as five
paragraphs and 44.5 s as one. That makes the exact text a wav was made from
evidence, and until this task nothing kept it: the editor built the narration,
handed it to `synthesize_voiceover.py` on the command line and to
`align_words.py` in a temp file, and neither survived the run. A batch could
therefore not be re-measured after the fact, and `measure_speaking_rate.py` -
the tool CF-0188 measured the rate with - exited 2 on every batch made after
the pipeline stopped writing `work/<slug>/narration.txt`.

Two halves, in that order: the TTS step records what it read, and the rate
tool reads that recording when it is there and rebuilds the narration from the
batch's scripts when it is not.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure_speaking_rate as rate  # noqa: E402
import meme_layer  # noqa: E402


# The three videos of example-film/2026-09-17T1901Z, in the shape the batch has
# them: no slug anywhere in the JSON, because the editor invents it per video.
SCRIPTS_JSON = {
    "batch_id": "2026-09-17T1901Z",
    "scripts": [
        {"script_id": "lf-2026-09-17-004-script1",
         "title_ref": {"name": "The Late Show With Stephen Colbert"},
         "hook": "The opening titles changed and nobody said a word.",
         "commentary": "Watch the skyline behind the desk. It is painted.",
         "payoff": "So next time you see that skyline - never real."},
        {"script_id": "lf-2026-09-17-009-script1",
         "title_ref": {"name": "Statute & Order: Special Cases"},
         "hook": "SVU wrote a whole episode around Taylor Sterling.",
         "commentary": "The case file is a fan theory with a badge on it.",
         "payoff": "And the credits never say her name once."},
        {"script_id": "lf-2026-09-17-012-script1",
         "title_ref": {"name": "The Secret Lives of Lake Wives"},
         "hook": "A castmate just quit over the comeback.",
         "commentary": "Five seasons in, the cast is half of what it was.",
         "payoff": "So that is the comeback - a few minutes of credits."},
    ],
}
SLUGS = {"colbert-titles": "lf-2026-09-17-004-script1",
         "svu-taylor-sterling": "lf-2026-09-17-009-script1",
         "mormon-wives-comeback": "lf-2026-09-17-012-script1"}


def _batch(tmp, slugs=SLUGS, scripts=SCRIPTS_JSON, files=None):
    """A batch directory: the researcher's file and one work/<slug>/ per video."""
    batch = Path(tmp) / "2026-09-17T1901Z"
    (batch / "work").mkdir(parents=True)
    if scripts is not None:
        (batch / "03-content-researcher.json").write_text(json.dumps(scripts))
    for slug in slugs:
        d = batch / "work" / slug
        d.mkdir()
        for name, body in (files or {}).get(slug, {}).items():
            (d / name).write_text(body if isinstance(body, str) else json.dumps(body))
    return batch


def _script(script_id):
    return next(s for s in SCRIPTS_JSON["scripts"] if s["script_id"] == script_id)


# --------------------------------------------------------------------------
# The recording: synthesize_voiceover.py leaves the text beside the wav.
# --------------------------------------------------------------------------

def test_the_tts_step_records_what_it_read():
    """The text handed to Kokoro is written as narration.txt next to the wav.

    Recorded verbatim - the line breaks are the point, since they are what the
    rate depends on - and without the synthesis having to succeed first, so a
    wav and its narration are never a pair only half of which exists."""
    import synthesize_voiceover
    text = "One.\n\nTwo lines, and a blank one between them.\n\nThree."
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "work" / "widows-bay" / "voice.wav"
        wav.parent.mkdir(parents=True)
        written = synthesize_voiceover.record_narration(text, wav)
        assert written == wav.parent / "narration.txt", written
        assert written.read_text(encoding="utf-8") == text, repr(written.read_text())


def test_the_recording_is_what_the_rate_tool_measures():
    """A wav's own narration.txt wins over anything rebuilt from the scripts.

    The recording is the only witness to the layout the wav was made from: a
    batch whose editor pressed the sections apart into paragraphs reads ~25 %
    slower than the join below, and rebuilding would silently measure the fast
    shape of a slow wav."""
    with tempfile.TemporaryDirectory() as tmp:
        paragraphs = "Hook line.\n\nCommentary line.\n\nPayoff line."
        batch = _batch(tmp, files={"colbert-titles": {"narration.txt": paragraphs}})
        videos = dict((slug, (text, src)) for slug, text, src in rate.narration_files(batch))
        assert videos["colbert-titles"] == (paragraphs, "narration.txt"), videos
        other, src = videos["svu-taylor-sterling"]
        assert src.startswith("03-content-researcher.json:"), src
        assert "\n" not in other, repr(other)


def test_a_take_that_is_not_voice_wav_gets_its_own_record():
    """Auditions share a directory; three takes must leave three records."""
    import synthesize_voiceover
    with tempfile.TemporaryDirectory() as tmp:
        a = synthesize_voiceover.record_narration("take one", Path(tmp) / "fenrir.wav")
        b = synthesize_voiceover.record_narration("take two", Path(tmp) / "puck.wav")
        assert a.name == "fenrir.narration.txt" and b.name == "puck.narration.txt", (a, b)
        assert a.read_text() == "take one" and b.read_text() == "take two"


def test_an_unwritable_directory_costs_a_warning_not_the_voiceover():
    """The record is evidence, not a precondition: no wav is lost over it."""
    import synthesize_voiceover
    with tempfile.TemporaryDirectory() as tmp:
        blocked = Path(tmp) / "afile"
        blocked.write_text("not a directory")
        assert synthesize_voiceover.record_narration("x", blocked / "voice.wav") is None


# --------------------------------------------------------------------------
# The fallback: a batch that has only the scripts and the empty work dirs.
# --------------------------------------------------------------------------

def test_a_batch_without_narration_files_is_still_measurable():
    """The case that broke the tool: every work/<slug>/ empty, scripts on disk.

    Every video is found, and each one's word count is the count of the text
    the TTS is actually handed - `meme_layer.narration_text()`, the editor's
    own single-line join, called rather than re-implemented here."""
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch(tmp)
        videos = rate.narration_files(batch)
        assert len(videos) == len(SLUGS), videos
        for slug, text, source in videos:
            script = _script(SLUGS[slug])
            expected = meme_layer.narration_text(script)
            assert text == expected, (slug, text, expected)
            assert rate.word_count(text) == len(expected.split()), slug
            assert source == f"03-content-researcher.json:{SLUGS[slug]}", source


def test_a_script_id_in_the_work_dir_is_used_before_the_slug():
    """A slug that says nothing is fine when the editor left a script_id.

    `anchors.json`, `anchors-preflight.json` and `plan.refusal.json` all carry
    it, so on a real batch the match is exact and the wording heuristic below
    never has to run."""
    slugs = {"video-2": "lf-2026-09-17-009-script1"}
    files = {"video-2": {"anchors.json": {"script_id": "lf-2026-09-17-009-script1"}}}
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch(tmp, slugs=slugs, files=files)
        videos = rate.narration_files(batch)
        assert len(videos) == 1, videos
        slug, text, source = videos[0]
        assert text == meme_layer.narration_text(_script(slugs["video-2"])), text
        assert source.endswith("lf-2026-09-17-009-script1"), source


def test_an_unmatchable_slug_is_skipped_and_not_guessed():
    """A rate measured on the wrong script is worse than one not measured.

    So a slug nothing in the batch answers to is dropped - loudly, on stderr -
    and the videos that did resolve are still measured."""
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch(tmp, slugs=dict(SLUGS, **{"take-2": None}))
        found = {slug for slug, _, _ in rate.narration_files(batch)}
        assert found == set(SLUGS), found


def test_a_slug_that_is_the_script_id_resolves():
    """How CF-0261's own re-measurement was laid out, and the root's full-run
    command still is: one directory per script, named by the script."""
    slugs = {"lf-2026-09-17-012-script1": "lf-2026-09-17-012-script1"}
    with tempfile.TemporaryDirectory() as tmp:
        videos = rate.narration_files(_batch(tmp, slugs=slugs))
        assert len(videos) == 1 and videos[0][0] == "lf-2026-09-17-012-script1", videos


def test_no_scripts_and_no_narration_is_an_empty_answer():
    """Nothing to measure is nothing to measure - main() turns this into the
    exit 2 that names both places it looked, not a median over zero videos."""
    with tempfile.TemporaryDirectory() as tmp:
        assert rate.narration_files(_batch(tmp, scripts=None)) == []


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
