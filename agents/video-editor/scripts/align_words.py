#!/usr/bin/env python3
"""Force-align a script's known text against its own synthesized voiceover
using whisper-cpp — since the audio IS a clean TTS reading of the text, this
gives accurate word-level timestamps without needing true forced alignment.

Usage: align_words.py <voiceover.wav> <output.json>
Requires models/ggml-base.en.bin (download: README, section "How to run").

CF-0050: nothing here needs to be told that the file opens on a silent beat -
the timings come out of this same file, so they are already shifted by it. One
correction is needed and it is whisper's, not the beat's: whisper hands its
first token the *segment's* start time, so a word that is really spoken at 0.94s
comes back starting at 0.00 and its caption would appear over the held frame the
beat exists to show. push_past_lead() clamps that against the audio's own onset.
"""
import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

# CF-0132: whisper.cpp is a binary, not a sibling script, so it goes
# through run_tool() - the alignment of one video is the slowest single
# child the run ledger records (the tts+align step tops out at 843 s),
# which is the case SIBLING_SCRIPT_TIMEOUT_SECONDS was sized for.
from common import leading_silence, run_tool
from repo_paths import MODELS_DIR  # CF-0125: models/ is gitignored, so it
# exists in the main checkout only - a worktree has no whisper model of its own
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

WHISPER_CLI = "/usr/local/bin/whisper-cli"
MODEL = str(MODELS_DIR / "ggml-base.en.bin")



def _norm(w):
    return "".join(c for c in w.lower() if c.isalnum())


def reconcile(whisper_words, truth_text):
    """Move whisper's timings onto the words we actually asked Kokoro to say.

    align_words works by transcribing the TTS output, on the assumption that a
    clean synthetic reading comes back word-for-word. Proper nouns break that:
    "Rink Rivals" came back as "He did rivalry", and since these tokens are
    what gets burned on screen, the caption would have shown the misheard text.
    Spelled-out numbers come back as digits for the same reason.

    The true text is known, so whisper is used only for *when*, never for
    *what*. Timings are transferred across a token-level diff; a run of true
    words matched against a differently-sized run of heard words shares that
    run's span in proportion to word length.
    """
    truth = truth_text.split()
    if not truth:
        return whisper_words

    a = [_norm(w["word"]) for w in whisper_words]
    b = [_norm(t) for t in truth]
    out = [None] * len(truth)

    for tag, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                w = whisper_words[i1 + k]
                out[j1 + k] = {"word": truth[j1 + k], "start": w["start"], "end": w["end"]}
        elif tag in ("replace", "delete") and j2 > j1:
            span_start = whisper_words[i1]["start"] if i1 < len(whisper_words) else None
            span_end = whisper_words[i2 - 1]["end"] if i2 - 1 < len(whisper_words) else None
            if span_start is None or span_end is None or span_end <= span_start:
                continue
            weights = [max(1, len(truth[j])) for j in range(j1, j2)]
            total = sum(weights)
            t = span_start
            for idx, j in enumerate(range(j1, j2)):
                dur = (span_end - span_start) * weights[idx] / total
                out[j] = {"word": truth[j], "start": round(t, 3), "end": round(t + dur, 3)}
                t += dur

    # Words whisper never produced a span for: slot them into the gap between
    # their settled neighbours rather than dropping them off the caption track.
    for j, w in enumerate(out):
        if w is not None:
            continue
        prev = next((out[k]["end"] for k in range(j - 1, -1, -1) if out[k]), 0.0)
        nxt = next((out[k]["start"] for k in range(j + 1, len(out)) if out[k]), prev + 0.3)
        out[j] = {"word": truth[j], "start": round(prev, 3),
                  "end": round(max(prev + 0.05, nxt), 3)}
    return out


def push_past_lead(words, lead):
    """No word may start before the audio does.

    Only ever moves a word later, and only inside the leading silence, so a file
    that opens on speech is untouched. The words that need it are the first one
    or two: whisper's first token inherits its segment's boundary, which is
    zero, and a caption that appears while the frame is still silent is the one
    thing a cold-frame opening cannot survive.
    """
    for w in words:
        if w["start"] >= lead:
            break
        w["start"] = round(lead, 3)
        # Its end is left alone unless the clamp swallowed it: whisper's end for
        # a mistimed first token is usually already past the lead and correct,
        # and lengthening it would push this word over the next one's start.
        if w["end"] <= w["start"]:
            w["end"] = round(w["start"] + 0.05, 3)
    return words


def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("output")
    p.add_argument("--text", default=None,
                   help="path to the narration text actually synthesized; timings are "
                        "reconciled onto it so captions never show a mis-transcription")
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.output))  # CF-0107: slug from work/<slug>/words.json

    json_path = args.wav + ".json"
    cmd = [
        WHISPER_CLI, "-m", MODEL, "-f", args.wav,
        "-ml", "1", "-sow", "-oj",
    ]
    result = run_tool(cmd, tool="whisper.cpp", target=args.wav)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    with open(json_path) as f:
        data = json.load(f)

    words = []
    for seg in data.get("transcription", []):
        text = seg["text"].strip()
        if not text:
            continue
        start = seg["offsets"]["from"] / 1000.0
        end = seg["offsets"]["to"] / 1000.0
        words.append({"word": text, "start": start, "end": end})

    heard = len(words)
    if args.text:
        truth = Path(args.text).read_text().strip()
        words = reconcile(words, truth)
        print(f"reconciled {heard} heard tokens onto {len(words)} written words")

    lead = leading_silence(args.wav)
    if lead:
        moved = sum(1 for w in words if w["start"] < lead)
        push_past_lead(words, lead)
        if moved:
            print(f"the audio starts at {lead:.2f}s; pushed {moved} word(s) that "
                  f"whisper timed before it")

    with open(args.output, "w") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    print(f"{len(words)} words -> {args.output}")


@video_script("video-editor", "align", name="align_words.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()
