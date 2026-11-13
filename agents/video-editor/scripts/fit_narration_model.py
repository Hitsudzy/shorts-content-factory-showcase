#!/usr/bin/env python3
"""CF-0279: check the narration estimate against every wav the channel has.

`measure_speaking_rate.py` answers "how many words a second does this voice
read", which is the question the flat rate is built on. This script answers
the question that replaced it: **does `estimate_narration.py` predict the
length of the wavs we already have** - and, for the record, how far the two
word-based models it replaces are off on the same points.

It is the reproducible half of CF-0279's finding. One command:

    scripts/fit_narration_model.py --channel example-film
    scripts/fit_narration_model.py --channel example-film \\
        --write-fixture tests/fixtures/narration-estimate-2026-09.json

The corpus is every directory under `pipeline/<channel>/<batch>/work/` that
holds a `voice.wav` and a text to go with it:

  * `narration.txt` beside the wav - what `synthesize_voiceover.py` recorded
    itself reading (CF-0261). Nested attempt directories count as their own
    point: `work/famine-trials-reaping/pass1/` is a different script from the
    rewrite that replaced it, and both were read.
  * otherwise the batch's `03-content-researcher.json` rebuilt through
    `meme_layer.narration_text()`, exactly as measure_speaking_rate.py does
    it - the same join the TTS is handed.

ONLY THE CURRENT VOICE COUNTS. The predicted length is a property of a voice
at a speed, so a wav read by another one is not evidence about this one. The
batch's own metadata says which voice read it (`voice_profile_used`,
`voice_profile`, in whatever shape that batch's writer used); a batch whose
profile does not match `--voice/--speed`, or that does not say, is SKIPPED
and named on stderr with the reason. That is why the corpus is the batches of
2026-09-16 onward and not the whole pipeline directory: everything before
that was read at am_puck@0.95, or as paragraphs rather than one line, or both.

Three models are reported on the same points:

    predictor  what estimate_narration.py computes - Kokoro's own duration
               predictor, summed. This is the one the pipeline uses.
    flat       seconds = words / rate, the model CF-0261 installed and
               CF-0279 removes; `rate` is the median of the corpus.
    chunks     seconds = words / a + b * (chunks - 1), the triage analyst's
               fit - words plus a cost per chunk boundary, least squares.

Exit 0 when every point is inside `--tolerance` of the predictor (default
`estimate_narration.TOLERANCE_SECONDS`), 1 when any point is outside it, 2
when the corpus is empty or unreadable, 3 when kokoro is unavailable.
"""
import argparse
import json
import re
import statistics
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate_narration  # noqa: E402
import measure_speaking_rate as msr  # noqa: E402 - the corpus walk and the join
import meme_layer  # noqa: E402
import voice_profile  # noqa: E402
from repo_paths import FACTORY_ROOT  # noqa: E402

SCRIPTS_JSON = msr.SCRIPTS_JSON

#: Where a batch records which voice read it. The pipeline has written this
#: three different ways in three weeks, so the match is done on the numbers
#: pulled out of any of them rather than on a shape.
PROFILE_PATTERN = re.compile(r"([a-z]{2}_[a-z]+)\D{0,12}([01]\.\d+)")


def batch_profile(batch_dir):
    """`(voice, speed)` the batch says it was read in, or None.

    Reads the batch's own top-level JSON records - `05-video-editor.json` and
    the run metadata - and pulls the first `<voice> ... <speed>` pair out of
    whatever shape they used: `"am_puck (speed 1.10)"`, `"am_puck@1.10"`,
    `"kokoro/am_puck@1.10"` and the `voice_profile` object all answer.
    """
    for path in sorted(Path(batch_dir).glob("*.json")):
        try:
            raw = path.read_text()
        except OSError:
            continue
        for key in ("voice_profile_used", "voice_profile"):
            if key not in raw:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            found = _profile_in(data, key)
            if found:
                return found
    return None


def _profile_in(node, key):
    if isinstance(node, dict):
        value = node.get(key)
        if isinstance(value, str):
            m = PROFILE_PATTERN.search(value)
            if m:
                return m.group(1), float(m.group(2))
        if isinstance(value, dict) and isinstance(value.get("voice"), str):
            try:
                return value["voice"], float(value.get("speed"))
            except (TypeError, ValueError):
                pass
        for child in node.values():
            found = _profile_in(child, key)
            if found:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _profile_in(child, key)
            if found:
                return found
    return None


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def points_of_batch(batch_dir):
    """`[(id, text, source, wav)]` for every wav of one batch.

    A recorded `narration.txt` beside the wav wins; a slug without one is
    rebuilt from the batch's scripts by measure_speaking_rate's own matcher,
    so the two tools read the same corpus the same way.
    """
    batch = Path(batch_dir)
    # The corpus is `<batch>/work/<slug>/` and nothing else. measure_speaking
    # _rate.work_dir() falls back to the batch directory itself when there is
    # no work/, which is right for a hand-pointed directory and wrong here: a
    # batch that kept no per-video work dir (2026-09-15T1034Z) has no wav to
    # measure, and the fallback made it walk the batch's `videos/` instead.
    work = batch / "work"
    if not work.is_dir():
        print(f"{batch.name}: skipped - no work/ directory, so no voice.wav to "
              f"measure", file=sys.stderr)
        return []
    rebuilt = {}
    try:
        rebuilt = {slug: (text, source) for slug, text, source in msr.narration_files(batch)}
    except Exception as e:  # noqa: BLE001 - a batch with no scripts file
        print(f"{batch.name}: scripts not readable ({e})", file=sys.stderr)
    out = []
    for wav in sorted(work.rglob("voice.wav")):
        rel = wav.parent.relative_to(work)
        recorded = wav.parent / "narration.txt"
        if recorded.is_file():
            out.append((f"{batch.name}/{rel}", recorded.read_text(),
                        "narration.txt", wav))
            continue
        slug = rel.parts[0]
        if len(rel.parts) == 1 and slug in rebuilt:
            text, source = rebuilt[slug]
            out.append((f"{batch.name}/{rel}", text, source, wav))
            continue
        print(f"{batch.name}/{rel}: no narration.txt and nothing to rebuild it "
              f"from - skipped", file=sys.stderr)
    return out


def corpus(pipeline_dir, voice, speed, keep_unlabelled=False):
    """Every point of every batch read by this voice at this speed."""
    out = []
    for batch in sorted(p for p in Path(pipeline_dir).iterdir() if p.is_dir()):
        profile = batch_profile(batch)
        if profile is None:
            if not keep_unlabelled:
                print(f"{batch.name}: skipped - the batch does not record which "
                      f"voice read it", file=sys.stderr)
                continue
        elif (profile[0], round(profile[1], 3)) != (voice, round(speed, 3)):
            print(f"{batch.name}: skipped - read by {profile[0]}@{profile[1]:g}, "
                  f"not {voice}@{speed:g}", file=sys.stderr)
            continue
        out.extend(points_of_batch(batch))
    return out


# --------------------------------------------------------------------------
# the two word-based models, for the record
# --------------------------------------------------------------------------
def flat_model(rows):
    """`words / rate` with the corpus median rate - CF-0261's model."""
    rate = round(statistics.median(r["words"] / r["wav_seconds"] for r in rows), 2)
    return {"name": "flat", "words_per_second": rate,
            "formula": f"seconds = words / {rate}",
            "predict": lambda r: r["words"] / rate}


def chunk_model(rows):
    """`words / a + b * (chunks - 1)`, least squares over the corpus."""
    import numpy as np
    A = np.array([[r["words"], r["chunks"] - 1] for r in rows], dtype=float)
    y = np.array([r["wav_seconds"] for r in rows], dtype=float)
    (per_word, per_boundary), *_ = np.linalg.lstsq(A, y, rcond=None)
    rate = round(1.0 / per_word, 3) if per_word else float("inf")
    per_boundary = round(float(per_boundary), 3)
    return {"name": "chunks", "words_per_second": rate, "seconds_per_boundary": per_boundary,
            "formula": f"seconds = words / {rate} + {per_boundary} x (chunks - 1)",
            "predict": lambda r: r["words"] / rate + per_boundary * (r["chunks"] - 1)}


def residuals(rows, model):
    out = []
    for r in rows:
        predicted = model["predict"](r)
        out.append(round(predicted - r["wav_seconds"], 3))
    return out


def summary(res):
    absolute = [abs(x) for x in res]
    return {"max_abs": round(max(absolute), 3),
            "mean_abs": round(sum(absolute) / len(absolute), 3),
            "min": round(min(res), 3), "max": round(max(res), 3)}


def main(argv=None):
    p = argparse.ArgumentParser()
    # CF-0212: no channel by default - a fit run for another channel that
    # forgot the flag would have measured example-film's voice.
    p.add_argument("--channel", required=True)
    p.add_argument("--pipeline", default=None,
                   help="the pipeline directory of the channel (default: "
                        "<factory root>/pipeline/<channel>)")
    p.add_argument("--voice", default=None)
    p.add_argument("--speed", type=float, default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--tolerance", type=float,
                   default=estimate_narration.TOLERANCE_SECONDS)
    p.add_argument("--keep-unlabelled", action="store_true",
                   help="also take batches that do not record their voice "
                        "(off by default: an unlabelled wav is not evidence)")
    p.add_argument("--write-fixture", default=None,
                   help="write the corpus - text, words, chunks, wav seconds - "
                        "as the JSON the tests pin the estimate against")
    p.add_argument("--json", dest="json_out", default=None)
    args = p.parse_args(argv)

    try:
        profile = voice_profile.load(args.channel)
    except voice_profile.VoiceProfileError as e:
        print(f"fit: ERROR: channel {args.channel!r}: {e}", file=sys.stderr)
        return 2
    for key in ("voice", "speed", "lang"):
        if getattr(args, key) is not None:
            profile[key] = getattr(args, key)

    pipeline_dir = Path(args.pipeline) if args.pipeline \
        else Path(FACTORY_ROOT) / "pipeline" / args.channel
    if not pipeline_dir.is_dir():
        print(f"fit: ERROR: no pipeline directory at {pipeline_dir}", file=sys.stderr)
        return 2

    points = corpus(pipeline_dir, profile["voice"], profile["speed"],
                    args.keep_unlabelled)
    if not points:
        print(f"fit: ERROR: no narration+voice.wav pair under {pipeline_dir} "
              f"read by {profile['voice']}@{profile['speed']:g}", file=sys.stderr)
        return 2

    estimator = estimate_narration.Estimator(profile["voice"], profile["speed"],
                                             profile["lang"])
    rows = []
    try:
        for ident, text, source, wav in points:
            record = estimator.estimate(text, ident)
            rows.append({
                "id": ident,
                "source": source,
                "words": record["words"],
                "chunks": record["chunks"],
                "chunk_phonemes": record["chunk_phonemes"],
                "predicted_seconds": record["estimated_seconds"],
                "wav_seconds": round(wav_seconds(wav), 3),
                "wav": str(wav),
                "text": text,
            })
    except estimate_narration.EngineUnavailable as e:
        print(f"fit: ERROR: kokoro is not available here: {e}", file=sys.stderr)
        return 3

    for r in rows:
        r["residual_seconds"] = round(r["predicted_seconds"] - r["wav_seconds"], 3)
        r["words_per_second"] = round(r["words"] / r["wav_seconds"], 3)

    models = [{"name": "predictor",
               "formula": "seconds = sum(pred_dur) / 40  (estimate_narration.py)",
               "predict": lambda r: r["predicted_seconds"]},
              flat_model(rows), chunk_model(rows)]
    table = []
    for model in models:
        res = residuals(rows, model)
        entry = {k: v for k, v in model.items() if k != "predict"}
        entry["residuals"] = res
        entry["residual_summary"] = summary(res)
        table.append(entry)

    width = max(len(r["id"]) for r in rows)
    header = f"{'point'.ljust(width)}  words  chunks   wav      " + \
             "   ".join(m["name"].ljust(9) for m in models)
    print(header)
    print("-" * len(header))
    for i, r in enumerate(rows):
        cells = "   ".join(f"{table[j]['residuals'][i]:+9.2f}" for j in range(len(models)))
        print(f"{r['id'].ljust(width)}  {r['words']:5d}  {r['chunks']:6d}  "
              f"{r['wav_seconds']:6.2f}   {cells}")
    print("-" * len(header))
    for entry in table:
        s = entry["residual_summary"]
        print(f"{entry['name']:10s} {entry['formula']}")
        print(f"{'':10s} residual max |{s['max_abs']:.2f}| s, mean |{s['mean_abs']:.2f}| s, "
              f"range {s['min']:+.2f}..{s['max']:+.2f} s")

    worst = table[0]["residual_summary"]["max_abs"]
    ok = worst <= args.tolerance
    print(f"\n{len(rows)} point(s), {profile['voice']}@{profile['speed']:g}: the "
          f"estimate is off by at most {worst:.3f} s "
          f"({'inside' if ok else 'OUTSIDE'} the stated {args.tolerance} s)")

    report = {"channel": args.channel, "voice": profile["voice"],
              "speed": profile["speed"], "lang": profile["lang"],
              "kokoro_version": estimator.kokoro_version,
              "tolerance_seconds": args.tolerance,
              "points": [{k: v for k, v in r.items() if k != "text"} for r in rows],
              "models": table}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"-> {args.json_out}")
    if args.write_fixture:
        fixture = {
            "note": "CF-0279: every video on disk read by this voice, with the "
                    "text that went to the TTS, what Kokoro cut it into, and how "
                    "long the wav came out. Rebuilt by scripts/"
                    "fit_narration_model.py --write-fixture; the wavs live in "
                    "pipeline/<channel>/ and are not in this repo, which is why "
                    "the text and the measured seconds are.",
            "channel": args.channel,
            "voice": profile["voice"], "speed": profile["speed"],
            "lang": profile["lang"],
            "kokoro_version": estimator.kokoro_version,
            "frames_per_second": estimate_narration.FRAMES_PER_SECOND,
            "tolerance_seconds": args.tolerance,
            "points": [{"id": r["id"], "source": r["source"], "words": r["words"],
                        "chunks": r["chunks"], "chunk_phonemes": r["chunk_phonemes"],
                        "wav_seconds": r["wav_seconds"],
                        "predicted_seconds": r["predicted_seconds"],
                        "text": r["text"]} for r in rows],
        }
        Path(args.write_fixture).write_text(json.dumps(fixture, indent=2) + "\n")
        print(f"-> {args.write_fixture}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
