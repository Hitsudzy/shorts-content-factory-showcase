#!/usr/bin/env python3
"""CF-0279: how long Kokoro will read this narration, before it reads it.

THE DEFECT THIS REPLACES. Until now the length of a script was `words /
narration_budget.words_per_second` - one constant, 3.88 w/s, measured under
CF-0261 on three scripts of 144-152 words. Kokoro does not read at a constant
rate. It cuts the text into chunks at a 510-phoneme ceiling
(`KPipeline.en_tokenize`) and synthesizes each chunk on its own, and every
chunk boundary costs its own phrase-final lengthening and padding. The three
calibration scripts were all 2 chunks; the 182-200 word budget CF-0261 derived
from them is 3 chunks. Batch 2026-09-18T1058Z read at 3.38-3.66 w/s instead of
3.88, one video went over the 60 s ceiling, and the rescue rewrite - 183 words,
inside the budget, estimated at 47.2 s - came out at 55.67 s and went over the
ceiling again. A word budget cannot be made safe by moving its ends: at 183
words this corpus holds both a 51.77 s reading and a 55.67 s one.

WHAT THIS MODULE DOES INSTEAD. It asks Kokoro. The synthesis has two halves:
a duration predictor that says how many frames each phoneme gets, and a
decoder/vocoder that turns those frames into samples. Only the second half is
expensive, and only the first half decides the length. So this module runs
the same g2p, the same `en_tokenize` chunking and the same prosody-predictor
forward pass that `synthesize_voiceover.py` runs, stops before the decoder,
and sums the predicted frames:

    seconds = sum(pred_dur) * SAMPLES_PER_FRAME / SAMPLE_RATE

That is not a model of the synthesis, it IS the synthesis's own arithmetic -
`KModel.forward_with_tokens` builds the alignment matrix from exactly this
`pred_dur`, so the wav is exactly this many samples long. Measured against
every video on disk read by the current voice (seven, `scripts/
fit_narration_model.py`, fixture `tests/fixtures/narration-estimate-2026-09.
json`): predicted equals the wav on all seven, to the centisecond, including
the two 183-word scripts 3.9 s apart that no words-and-chunks fit can tell
apart. The stated tolerance is TOLERANCE_SECONDS below, and it covers
rounding and nothing else.

WHAT INVALIDATES IT. The voice, the speed and the weights - the estimate is
computed for the channel's `voice_profile`, so it follows a voice change by
itself, which the constant never did. A kokoro upgrade can move both the
chunking and the predictor: `tests/test_narration_estimate.py` pins the
version, the 510-phoneme ceiling inside `en_tokenize`, and the frame
arithmetic, so the upgrade fails a test instead of a batch.

A CHUNK OVER THE CEILING (CF-0931). `en_tokenize` can let a chunk through
one phoneme over 510; the synthesis then reads `ps[:510]` of it. The
estimate measures that same truncated chunk (it never crashes on it) and
marks the record: `overflow` / `overflow_words_lost` always, and
`overflow_chunks` - `[{"chunk", "text", "phonemes", "limit", "dropped",
"words_lost"}]` - when there is one. `words_lost: true` means the reading
would clip spoken words: the script goes back to be split, it is not read.

WHAT IT DOES NOT DO. It does not judge the finished wav - that stays
`narration_length.py`, on the real audio, unloosened. This is the estimate
the script is written against; that is the gate the audio is held to.

Usage (see `## Contract` in the CF-0279 report for the caller's side):

    estimate_narration.py --channel example-film --text "Hook. Commentary. Payoff."
    estimate_narration.py --channel example-film --text-file narration.txt
    estimate_narration.py --channel example-film --batch 03-content-researcher.json
    ... --batch -            # the same JSON on stdin

Batch input is any of: a list of strings, a list of `{"id", "text"}`, or a
Content Researcher document `{"scripts": [...]}` - in which case the text of
each script is built HERE, by `meme_layer.narration_text()`, the same join
the TTS is handed, so the estimate and the synthesis cannot drift apart over
a separator.

Exit codes:
    0  an estimate was produced (nothing is judged: `verdict` is advice)
    2  bad usage or bad config (unreadable text, unusable voice_profile)
    3  the engine is not available here (no kokoro, no torch, no weights).
       A caller that gets 3 refuses; it does NOT fall back to dividing by a
       constant, because that constant is the defect this file replaces.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meme_layer  # noqa: E402 - the join the TTS is handed (CF-0261)
import voice_profile  # noqa: E402 - the channel's voice, not this script's

#: Kokoro's chunk ceiling, `KPipeline.en_tokenize`: a chunk is closed as soon
#: as the next token would take the phoneme count past this. Not used to
#: chunk anything here - `en_tokenize` itself does that - but pinned by the
#: tests against the library's own source, so an upgrade that moves it is a
#: failed test and not a batch of long videos.
CHUNK_PHONEME_LIMIT = 510

#: CF-0931: `en_tokenize`'s ceiling is not airtight. After a cut it re-counts
#: the carried-over tokens from their STRIPPED phoneme string, losing the
#: space before the token that triggered the cut, so the next chunk can come
#: out one phoneme over the ceiling (batch example-tech/2026-11-11T0841Z,
#: lf-2026-11-11-050-script1: a 511-phoneme chunk). `KPipeline.__call__` -
#: what `synthesize_voiceover.py` reads through - does not crash on that: it
#: logs "Unexpected len(ps)" and synthesizes `ps[:510]`. The voice pack has
#: exactly 510 rows (`pack[len(ps) - 1]`), which is where the estimator used
#: to crash. The estimator now does what the synthesis does - measures the
#: first CHUNK_PHONEME_LIMIT phonemes - and says what was cut off.
#:
#: Kokoro's own punctuation (`kokoro.model`'s vocab): a cut that drops only
#: these and spaces loses no spoken word, only a pause/intonation mark.
NON_WORD_PHONEMES = set(';:,.!?¡¿—…"«»“”()') | {" "}

#: The frame arithmetic of `KModel`: the decoder emits SAMPLES_PER_FRAME
#: samples per predicted frame, and `synthesize_voiceover.py` writes the wav
#: at SAMPLE_RATE. 40 frames of prediction = one second of wav.
SAMPLE_RATE = 24000
SAMPLES_PER_FRAME = 600
FRAMES_PER_SECOND = SAMPLE_RATE / SAMPLES_PER_FRAME  # 40.0

#: What this estimate may be off by. The predictor is deterministic and the
#: decoder cannot change the length, so the only error is the rounding of
#: `pred_dur` to whole frames, which is already inside the number: the seven
#: videos on disk all come out exact. A hundredth of a second is what a wav
#: length is reported to; a twentieth is stated so that a caller's margin is
#: not built on a claim of zero.
TOLERANCE_SECONDS = 0.05

#: `KPipeline.__call__`'s own segmentation of the text before chunking.
SPLIT_PATTERN = r"\n+"

REPO_ID = "hexgrad/Kokoro-82M"


class EngineUnavailable(RuntimeError):
    """kokoro, torch or the weights are not reachable from this interpreter."""


class Estimator:
    """One loaded voice, reusable across scripts.

    Cold (import + weights + voice pack) is ~7-9 s on this machine; each
    script after that is ~1.0-1.3 s of predictor forward. That asymmetry is
    why `--batch` exists: a caller with five scripts pays the cold start once.
    """

    def __init__(self, voice=voice_profile.DEFAULT_VOICE,
                 speed=voice_profile.DEFAULT_SPEED,
                 lang=voice_profile.DEFAULT_LANG, repo_id=REPO_ID):
        self.voice, self.speed, self.lang, self.repo_id = voice, speed, lang, repo_id
        self._pipeline = None
        self._model = None
        self._pack = None
        self._torch = None

    # -- the engine ------------------------------------------------------
    def load(self):
        """Build the pipeline, the weights and the voice pack. Raises
        EngineUnavailable rather than a library-specific error, so callers
        have one thing to catch and one exit code to map it to."""
        if self._pipeline is not None:
            return
        try:
            import torch
            from kokoro import KPipeline, KModel
        except Exception as e:  # noqa: BLE001 - any import failure is the same answer
            raise EngineUnavailable(f"kokoro/torch not importable: {e}") from e
        try:
            model = KModel(repo_id=self.repo_id).eval()
            pipeline = KPipeline(lang_code=self.lang, model=model, repo_id=self.repo_id)
            pack = pipeline.load_voice(self.voice)
        except Exception as e:  # noqa: BLE001 - missing weights, unknown voice
            raise EngineUnavailable(
                f"kokoro could not load {self.voice!r} from {self.repo_id}: {e}") from e
        self._torch, self._model, self._pipeline, self._pack = torch, model, pipeline, pack

    @property
    def kokoro_version(self):
        try:
            import kokoro
            return getattr(kokoro, "__version__", None)
        except Exception:  # noqa: BLE001
            return None

    # -- the two halves --------------------------------------------------
    def chunks(self, text):
        """`[(graphemes, phonemes)]` - the chunks Kokoro will synthesize.

        `KPipeline.__call__` splits the text on `\\n+` first and chunks each
        segment with `en_tokenize`; both steps are the library's, called here
        rather than reimplemented. A text with no newlines - which is what
        `meme_layer.narration_text()` produces - is one segment, and the
        chunking is then the 510-phoneme cut alone.
        """
        self.load()
        out = []
        for segment in re.split(SPLIT_PATTERN, (text or "").strip()):
            if not segment.strip():
                continue
            _, tokens = self._pipeline.g2p(segment)
            for graphemes, ps, _tks in self._pipeline.en_tokenize(tokens):
                if not ps:
                    continue
                out.append((graphemes, ps))
        return out

    def chunk_frames(self, ps):
        """The predicted length of one chunk, in frames.

        The first eight lines of `KModel.forward_with_tokens`, stopping
        before F0/N and the decoder: bert -> bert_encoder -> the prosody
        predictor's text encoder -> lstm -> duration_proj. `speed` divides
        the durations there exactly as it does in the synthesis, which is why
        an estimate follows `voice_profile.speed` without a second constant.
        """
        torch = self._torch
        model = self._model
        # CF-0931: `KPipeline.__call__` synthesizes `ps[:510]` of an overlong
        # chunk; the length measured is the length of THAT, and the voice pack
        # (510 rows) is indexed the way the synthesis indexes it.
        ps = spoken_phonemes(ps)
        ref_s = self._pack[len(ps) - 1]
        if ref_s.dim() == 1:
            ref_s = ref_s.unsqueeze(0)
        ids = [i for i in (model.vocab.get(c) for c in ps) if i is not None]
        with torch.no_grad():
            input_ids = torch.LongTensor([[0, *ids, 0]]).to(model.device)
            input_lengths = torch.full((1,), input_ids.shape[-1],
                                       device=model.device, dtype=torch.long)
            text_mask = torch.arange(int(input_lengths.max())).unsqueeze(0) \
                .expand(1, -1).type_as(input_lengths)
            text_mask = torch.gt(text_mask + 1, input_lengths.unsqueeze(1)).to(model.device)
            bert_dur = model.bert(input_ids, attention_mask=(~text_mask).int())
            d_en = model.bert_encoder(bert_dur).transpose(-1, -2)
            s = ref_s.to(model.device)[:, 128:]
            d = model.predictor.text_encoder(d_en, s, input_lengths, text_mask)
            x, _ = model.predictor.lstm(d)
            duration = model.predictor.duration_proj(x)
            duration = torch.sigmoid(duration).sum(axis=-1) / self.speed
            pred_dur = torch.round(duration).clamp(min=1).long().squeeze()
            return int(pred_dur.sum())

    # -- the answer ------------------------------------------------------
    def estimate(self, text, script_id=None):
        """The whole record for one narration: what it is cut into, how long
        each piece reads, and the total."""
        text = text or ""
        chunks = self.chunks(text)
        per_chunk = []
        overflow_chunks = []
        for index, (graphemes, ps) in enumerate(chunks):
            frames = self.chunk_frames(ps)
            per_chunk.append({
                "phonemes": len(ps),
                "frames": frames,
                "seconds": round(frames / FRAMES_PER_SECOND, 3),
                "words": len(str(graphemes).split()),
            })
            over = chunk_overflow(ps)
            if over is not None:
                over["chunk"] = index
                over["text"] = str(graphemes)
                overflow_chunks.append(over)
        frames = sum(c["frames"] for c in per_chunk)
        seconds = round(frames / FRAMES_PER_SECOND, 3)
        record = {
            "engine": "kokoro",
            "kokoro_version": self.kokoro_version,
            "model": "duration-predictor",
            "voice": self.voice,
            "speed": self.speed,
            "lang": self.lang,
            "words": len(text.split()),
            "chunks": len(per_chunk),
            "chunk_phonemes": [c["phonemes"] for c in per_chunk],
            "chunk_seconds": [c["seconds"] for c in per_chunk],
            "frames": frames,
            "estimated_seconds": seconds,
            "tolerance_seconds": TOLERANCE_SECONDS,
            # CF-0931: a chunk over the 510-phoneme ceiling is read cut off
            # at 510 (`KPipeline.__call__`). `overflow` says whether any
            # chunk was; `overflow_words_lost` whether the cut takes spoken
            # words with it (not just a final full stop) - that script has to
            # go back to its writer: split the sentence.
            "overflow": bool(overflow_chunks),
            "overflow_words_lost": any(c["words_lost"] for c in overflow_chunks),
        }
        if overflow_chunks:
            record["overflow_chunks"] = overflow_chunks
        if script_id is not None:
            record["id"] = script_id
        return record


def spoken_phonemes(ps):
    """The phonemes the synthesis actually reads out of one chunk:
    `KPipeline.__call__` keeps `ps[:CHUNK_PHONEME_LIMIT]` of an overlong one
    (CF-0931). A chunk within the ceiling is returned as it is."""
    return ps[:CHUNK_PHONEME_LIMIT] if len(ps) > CHUNK_PHONEME_LIMIT else ps


def chunk_overflow(ps):
    """None for a chunk within the ceiling; otherwise what the synthesis
    drops from it: `{"phonemes", "limit", "dropped", "words_lost"}`, where
    `dropped` is the cut-off phoneme tail and `words_lost` is False only when
    that tail is punctuation and spaces (CF-0931)."""
    if len(ps) <= CHUNK_PHONEME_LIMIT:
        return None
    dropped = ps[CHUNK_PHONEME_LIMIT:]
    return {
        "phonemes": len(ps),
        "limit": CHUNK_PHONEME_LIMIT,
        "dropped": dropped,
        "words_lost": any(ch not in NON_WORD_PHONEMES for ch in dropped),
    }


# --------------------------------------------------------------------------
# The channel's arithmetic - asked for, never copied (CF-0158/CF-0279)
# --------------------------------------------------------------------------
def with_channel_verdict(record, channel):
    """Add the finished video's length and the band's verdict to a record.

    The addition, the band and the verdict are all `narration_length.py`'s,
    which in turn asks `patterns/validate_patterns.py` - so the estimate and
    the post-TTS gate cannot come to disagree about what 60 seconds means.
    A checkout that cannot reach the factory root gets the estimate and no
    verdict, never a second opinion invented here.
    """
    if not channel:
        return record
    try:
        import narration_length as nl
    except Exception:  # noqa: BLE001
        return record
    budget = nl.load_narration_budget(channel)
    if budget is None:
        return record
    seconds = record["estimated_seconds"]
    record["tail_seconds"] = nl.tail_seconds(budget)[0]
    record["estimated_total_seconds"] = nl.total_seconds(seconds, budget)
    band = nl.narration_band(budget)
    if band:
        record["narration_band"] = [band[0], band[1]]
    judged = nl.video_length(seconds, budget)
    if judged:
        # Advice, not a gate: this is an estimate of a wav that does not
        # exist yet. `verdict` is what the script's author should act on;
        # the refusal is narration_length.py's, on the real audio.
        record["verdict"] = judged.get("verdict")
        record["action"] = judged.get("action")
    return record


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def read_batch(source):
    """`[(id, text)]` out of one of the three shapes `--batch` accepts."""
    raw = sys.stdin.read() if source == "-" else Path(source).read_text()
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("scripts", [])
    if not isinstance(data, list):
        raise ValueError("batch input is not a list of scripts")
    out = []
    for i, item in enumerate(data):
        if isinstance(item, str):
            out.append((str(i), item))
            continue
        if not isinstance(item, dict):
            raise ValueError(f"batch item {i} is neither a string nor an object")
        ident = item.get("script_id") or item.get("id") or str(i)
        text = item.get("text")
        if not isinstance(text, str):
            # A Content Researcher script: the join is made here, by the
            # editor's own function, so nobody re-implements the separator.
            text = meme_layer.narration_text(item)
        out.append((str(ident), text))
    return out


def build_parser():
    p = argparse.ArgumentParser(
        description="how long Kokoro will read this narration (CF-0279)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="the narration, as one argument")
    src.add_argument("--text-file", help="a file holding the narration ('-' for stdin)")
    src.add_argument("--batch", help="JSON of several scripts ('-' for stdin); "
                                     "a list of strings, a list of {id,text}, or a "
                                     "Content Researcher {\"scripts\": [...]} document")
    p.add_argument("--channel", default=None,
                   help="channel id (or path to channels/<id>.json) whose voice_profile "
                        "reads this and whose narration_budget judges it")
    p.add_argument("--voice", default=None, help="overrides the channel's voice")
    p.add_argument("--speed", type=float, default=None, help="overrides the channel's speed")
    p.add_argument("--lang", default=None, help="overrides the channel's lang_code")
    p.add_argument("--indent", type=int, default=2,
                   help="JSON indent; 0 for one line (default 2)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        profile = voice_profile.load(args.channel)
    except voice_profile.VoiceProfileError as e:
        print(f"estimate: ERROR: channel {args.channel!r}: {e}", file=sys.stderr)
        return 2
    for key in ("voice", "speed", "lang"):
        if getattr(args, key) is not None:
            profile[key] = getattr(args, key)

    try:
        if args.batch:
            items = read_batch(args.batch)
        elif args.text_file:
            raw = sys.stdin.read() if args.text_file == "-" \
                else Path(args.text_file).read_text()
            items = [(None, raw)]
        else:
            items = [(None, args.text)]
    except (OSError, ValueError) as e:
        print(f"estimate: ERROR: cannot read the narration: {e}", file=sys.stderr)
        return 2
    if not items:
        print("estimate: ERROR: nothing to estimate", file=sys.stderr)
        return 2

    estimator = Estimator(profile["voice"], profile["speed"], profile["lang"])
    try:
        records = [with_channel_verdict(estimator.estimate(text, ident), args.channel)
                   for ident, text in items]
    except EngineUnavailable as e:
        # Exit 3, and say what is missing. The caller refuses over this; it
        # must not divide words by a constant instead (CF-0279).
        print(f"estimate: ERROR: kokoro is not available here: {e}", file=sys.stderr)
        return 3

    indent = args.indent or None
    if args.batch:
        out = {"engine": "kokoro", "kokoro_version": estimator.kokoro_version,
               "voice": profile["voice"], "speed": profile["speed"],
               "lang": profile["lang"], "results": records}
    else:
        out = records[0]
    print(json.dumps(out, indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
