#!/usr/bin/env python3
"""CF-0188: how many words a second this voice actually reads, on real scripts.

`narration_budget.words_per_second` in the channel config is the number the
whole length of a video hangs on: Content Researcher sizes the script from it,
patterns/validate_patterns.py refuses an unplayable block order by it, and
narration_length.py gates the finished wav against it. It is a MEASUREMENT of
one voice at one speed - `am_puck @0.95` over the four videos of batch
`2026-09-03T2037Z` (CF-0087) - which means changing the voice invalidates it.
This script is how it gets measured again, by the same method, so that two
numbers taken a milestone apart are comparable.

The method, unchanged from CF-0087:

  * the material is the narration of every video of a batch - whole
    narratives, hook + commentary + payoff, prosody marks included, exactly
    as the editor hands them to the TTS;
  * the word count is that text's whitespace tokens (verified equal to what
    the forced aligner counted in `words.json` on all four videos of the
    2026-09-03T2037Z batch);
  * the duration is the whole synthesized wav, exactly as
    `synthesize_voiceover.py` writes it, with no lead silence;
  * the rate of a video is words / seconds, and the batch's rate is the
    MEDIAN of the videos', rounded to two decimals.

Same scripts, same method, one variable changed - so a difference between two
runs of this script is the voice and not the material.

CF-0261: WHERE the narration comes from is now two answers, because the rate
turned out to depend on the SHAPE of that text and not on the voice alone.
`synthesize_voiceover.py` records what it read as `work/<slug>/narration.txt`,
and that recording is what this script measures whenever it is there - the
text the wav beside it actually says, line breaks and all. For a batch made
before that recording existed (every batch up to 2026-09-18) the file is
absent, and the narration is rebuilt from `<batch>/03-content-researcher.json`
through `meme_layer.narration_text()` - the same single-line join the editor
hands to Kokoro, so the rebuild is the reading and not an approximation of it.
That fallback is what made this script runnable on a live batch again: between
CF-0188 and CF-0261 the pipeline stopped writing narration.txt, and the tool
that guards the rate exited 2 on every batch of that period.

Usage:
    measure_speaking_rate.py <batch-dir> [--voice am_fenrir] [--speed 1.05]
      [--channel example-film] [--lang a] [--keep-wavs <dir>] [--json <file>]

A run with neither --voice/--speed nor --channel re-measures the default
voice, which is how you check this script against the 2.75 already on record.
"""
import argparse
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meme_layer  # noqa: E402 - CF-0261: the join the TTS is handed
import voice_profile  # noqa: E402


SCRIPTS_JSON = "03-content-researcher.json"
NOISE_TOKENS = {"the", "and", "for", "with", "script", "s1", "s2", "s3"}


def work_dir(batch_dir):
    """The directory holding one `<slug>/` per video of the batch."""
    work = Path(batch_dir) / "work"
    return work if work.is_dir() else Path(batch_dir)


def load_scripts(batch_dir):
    """The batch's scripts, or [] when the file is not beside the work dir."""
    work = work_dir(batch_dir)
    for candidate in (Path(batch_dir) / SCRIPTS_JSON, work.parent / SCRIPTS_JSON):
        if candidate.is_file():
            data = json.loads(candidate.read_text())
            scripts = data.get("scripts", []) if isinstance(data, dict) else data
            return [s for s in scripts if isinstance(s, dict)]
    return []


def _tokens(text):
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def recorded_script_id(slug_dir):
    """A `script_id` the editor already wrote into this video's work dir.

    `anchors.json`, `anchors-preflight.json` and `plan.refusal.json` all carry
    it at the top level; whichever exists answers exactly, with no guessing.
    """
    for name in ("anchors.json", "anchors-preflight.json", "plan.refusal.json",
                 "plan.assetless-rung.json"):
        path = slug_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(data, dict) and isinstance(data.get("script_id"), str):
            return data["script_id"]
    return None


def match_script(slug, scripts):
    """Which script a `work/<slug>/` belongs to when the slug is all there is.

    Nothing in the batch records the slug - the editor invents it per video -
    so the link is the wording: a slug's tokens are drawn from the title and
    the narration (`mormon-wives-comeback` <- "The Secret Lives of Mormon
    Wives"). The best-scoring script wins only if it scores strictly better
    than every other one; a tie is left unresolved and said out loud, because
    a rate measured on the wrong script is worse than a rate not measured.
    """
    wanted = [t for t in _tokens(slug) if len(t) >= 3 and t not in NOISE_TOKENS]
    scored = []
    for script in scripts:
        if script.get("script_id") == slug or script.get("id") == slug:
            return script
        hay = set(_tokens(" ".join([
            (script.get("title_ref") or {}).get("name") or "",
            narration_text_of(script), script.get("script_id") or ""])))
        score = sum(1 for t in wanted
                    if t in hay or (len(t) >= 4 and any(h.startswith(t) for h in hay)))
        scored.append((score, script))
    scored.sort(key=lambda row: row[0], reverse=True)
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def narration_text_of(script):
    """The text the TTS is handed - the editor's own join, not a copy of it."""
    return meme_layer.narration_text(script)


def narration_files(batch_dir):
    """The narration of every video of the batch: `[(slug, text, source)]`.

    Two sources, in this order (CF-0261):

      * `work/<slug>/narration.txt`, what `synthesize_voiceover.py` recorded
        itself reading - preferred whenever it exists, because it is the only
        witness to the line breaks the wav was actually made from;
      * `<batch>/03-content-researcher.json` through `narration_text_of()`,
        for the batches made before that file was recorded.

    A video whose narration cannot be found either way is skipped with a line
    on stderr naming it, and the remaining videos are still measured.
    """
    scripts = load_scripts(batch_dir)
    out = []
    for slug_dir in sorted(p for p in work_dir(batch_dir).iterdir() if p.is_dir()):
        recorded = slug_dir / "narration.txt"
        if recorded.is_file():
            out.append((slug_dir.name, recorded.read_text(), "narration.txt"))
            continue
        if not scripts:
            continue
        script_id = recorded_script_id(slug_dir)
        script = None
        if script_id:
            script = next((s for s in scripts
                           if script_id in (s.get("script_id"), s.get("id"))), None)
        if script is None:
            script = match_script(slug_dir.name, scripts)
        if script is None:
            print(f"no narration for {slug_dir.name}: no narration.txt, and no "
                  f"script of {SCRIPTS_JSON} matches the slug", file=sys.stderr)
            continue
        out.append((slug_dir.name, narration_text_of(script),
                    f"{SCRIPTS_JSON}:{script.get('script_id') or script.get('id')}"))
    return out


def word_count(text):
    """CF-0087's count: whitespace tokens of the written narrative."""
    return len(text.split())


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def synthesize(pipeline, text, voice, speed, dest):
    import soundfile as sf
    import numpy as np
    chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=speed)]
    full = np.concatenate(chunks)
    sf.write(str(dest), full, 24000)
    return len(full) / 24000.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("batch_dir", help="a pipeline batch directory (the one holding work/)")
    p.add_argument("--channel", default=None,
                   help="read the voice and speed from this channel's voice_profile")
    p.add_argument("--voice", default=None)
    p.add_argument("--speed", type=float, default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--keep-wavs", default=None,
                   help="directory to leave the synthesized wavs in (default: a temp dir "
                        "that is kept, so the measurement can be listened to)")
    p.add_argument("--json", dest="json_out", default=None,
                   help="write the per-video table and the median here")
    args = p.parse_args()

    profile = voice_profile.load(args.channel)
    for key in ("voice", "speed", "lang"):
        if getattr(args, key) is not None:
            profile[key] = getattr(args, key)
            profile["source"] = "command line"

    videos = narration_files(args.batch_dir)
    if not videos:
        print(f"no narration under {args.batch_dir}: no work/<slug>/narration.txt "
              f"and no {SCRIPTS_JSON} to rebuild it from", file=sys.stderr)
        return 2

    out_dir = Path(args.keep_wavs) if args.keep_wavs else \
        Path(args.batch_dir) / f"_rate_{profile['voice']}_{profile['speed']:g}"
    out_dir.mkdir(parents=True, exist_ok=True)

    from kokoro import KPipeline
    pipeline = KPipeline(lang_code=profile["lang"])

    rows = []
    for slug, text, source in videos:
        words = word_count(text)
        wav = out_dir / f"{slug}.wav"
        t0 = time.time()
        seconds = synthesize(pipeline, text, profile["voice"], profile["speed"], wav)
        rows.append({"slug": slug, "words": words, "seconds": round(seconds, 3),
                     "words_per_second": round(words / seconds, 3),
                     "narration_source": source,
                     "synth_seconds": round(time.time() - t0, 1)})
        print(f"{slug}: {words} words / {seconds:.2f}s = "
              f"{words / seconds:.3f} w/s (from {source}) -> {wav}", flush=True)

    rates = sorted(r["words_per_second"] for r in rows)
    median = round(statistics.median(rates), 2)
    report = {
        "voice": profile["voice"],
        "speed": profile["speed"],
        "lang": profile["lang"],
        "batch": str(Path(args.batch_dir).name),
        "videos": len(rows),
        "rows": rows,
        "min": min(rates),
        "max": max(rates),
        "median": median,
        "spread_pct": round(100 * (max(rates) - min(rates)) / median, 1),
        "wavs": str(out_dir),
    }
    print(f"\n{profile['voice']} @ {profile['speed']:g}: median {median} w/s "
          f"over {len(rows)} video(s), {min(rates)}-{max(rates)} "
          f"(spread {report['spread_pct']}% of the median)")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"-> {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
