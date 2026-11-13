#!/usr/bin/env python3
"""CF-0542: how many figures the narrator has to say - the measuring stick.

**Why.** The user, 2026-10-05, on `vanguards-endgame`
(`pipeline/example-film/2026-10-05T0701Z`): "fine, it can go out - though the
narration is heavy going, the narrator says a lot of numbers". The video was
accepted; the remark is about listening. Its commentary opens on "two billion
nine hundred twenty five point five million to Avatar's two billion nine
hundred twenty three point seven, a gap under two million" - three amounts in
one breath, then a date, then three years. A viewer of a Short hears every
figure once, with no page to look back at.

**What counts as a figure** - something the listener has to hold, read the
way the narrator speaks it, whether the script writes it in digits or in
words (the Endgame script spells its sums out, the Delver one writes "$160
million"; both are spoken the same):

    money    "$8 million", "160 million dollars", "$2.9255B"
    amount   a spelled or written quantity with a magnitude or above ten:
             "two billion nine hundred twenty five point five million",
             "nineteen years", "a hundred-year-old", "106"
    percent  "50%", "fifty percent"
    date     a month with a day or a year: "October 2014", "December eighteenth"
    year     "2019", "back in 2007", "the 1990s"
    decimal  "2.5", "two point five" (with no magnitude after it)

A run of number words with nothing between them is **one** figure: "two
billion nine hundred twenty five point five million" is one amount, as the ear
takes it. A month joins its day and year, "percent" and "dollars" join the
number before them.

**What is not a figure** (counted apart as `small_numbers`, never in the
rule): a lone small cardinal up to ten with no money / percent / magnitude on
it ("one question", "two different segments", "number one spot", "a
two-part sequel") and an ordinal outside a date ("First: ...", "the third
time"). They are words the sentence is built of, not data the viewer has to
remember.

**The readings**, over the visible narration - `hook`, `commentary`,
`payoff`, in that order, the words the voice reads:

    figures             how many figures in all
    words               the narration's words (whitespace-separated)
    per_10_words        figures / words * 10
    max_per_sentence    the most figures in one sentence (a sentence ends at
                        . ! ? ; or : followed by a space - "2.799" stays whole)
    max_run             the longest chain of figures in one sentence where no
                        more than RUN_GAP_WORDS words stand between two of them
    heavy_sentences     every sentence with more than one figure, its field,
                        its text and its figures

This module only measures; the rule and its mode are the check's
(`check_number_density.py`), and the price of a threshold over the channel's
accepted videos is `python3 scripts/number_density.py history`.

Usage:

    python3 scripts/number_density.py text "Endgame made $2.799 billion in 2019."
    python3 scripts/number_density.py batch <03-content-researcher.json>
    python3 scripts/number_density.py history [--root R] [--channel C] [--json]

Stdlib only; no model, no network.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197: a former channel id

FIELDS = ("hook", "commentary", "payoff")
RUN_GAP_WORDS = 4
SMALL_MAX = 10

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_MAGNITUDES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6,
               "billion": 10 ** 9, "trillion": 10 ** 12}
_ORDINALS = {
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
    "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth",
    "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth", "seventieth",
    "eightieth", "ninetieth", "hundredth", "thousandth", "millionth",
}
_MONTHS = {"january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december",
           "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
           "oct", "nov", "dec"}
_PERCENT = {"percent", "per-cent", "percentage"}
_CURRENCY_AFTER = {"dollars", "dollar", "bucks", "euros", "pounds"}
NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_MAGNITUDES)

# A token: a figure written in digits (with its currency sign, separators,
# decimals, suffix - "$2.9255B", "1,000", "50%", "1990s", "18th"), a word
# (apostrophes kept, hyphens split later), or one punctuation mark that ends a
# figure's run.
_TOKEN = re.compile(r"[$€£]?\d(?:[\d,.]*\d)?%?[A-Za-z]*|[A-Za-z]+(?:['’][A-Za-z]+)*|[,()\"“”—–]")
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
_DIGIT = re.compile(r"\d")


def sentences(text):
    """The sentences of one field: split after . ! ? ; : followed by a space,
    so "2.799" and "$2.9255B" stay whole."""
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip()]


def _tokens(sentence):
    # a hyphenated word ("twenty-five", "two-part", "eight-million-dollar")
    # comes out as its parts: [A-Za-z]+ stops at "-"
    return _TOKEN.findall(sentence)


def _low(t):
    return t.lower().replace("’", "'")


def _is_numeric(t):
    lt = _low(t)
    return bool(_DIGIT.search(t)) or lt in NUMBER_WORDS or lt in _ORDINALS


def _digit_value(t):
    m = re.match(r"[$€£]?(\d[\d,]*(?:\.\d+)?)", t)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _spans(tokens):
    """Group the tokens into figure spans: lists of token indexes."""
    spans, i, n = [], 0, len(tokens)
    while i < n:
        t, lt = tokens[i], _low(tokens[i])
        starts = _is_numeric(t)
        # "a hundred-year-old", "a million viewers": the article is the number
        if lt == "a" and i + 1 < n and _low(tokens[i + 1]) in _MAGNITUDES:
            starts = True
        # a month opens a date when a number follows it
        if lt in _MONTHS and i + 1 < n and _is_numeric(tokens[i + 1]) \
                and (lt != "may" or t[0].isupper()):
            starts = True
        if not starts:
            i += 1
            continue
        span = [i]
        j = i + 1
        while j < n:
            lj = _low(tokens[j])
            prev = _low(tokens[span[-1]])
            if _is_numeric(tokens[j]):
                # two numbers written in digits side by side are two figures
                # ("2019 2021" never happens in speech without a pause)
                if _DIGIT.search(tokens[j]) and _DIGIT.search(tokens[span[-1]]) \
                        and lj not in _MAGNITUDES:
                    break
                span.append(j)
            elif lj == "point" and j + 1 < n and _is_numeric(tokens[j + 1]) \
                    and (prev in NUMBER_WORDS):
                span.append(j)
            elif lj == "and" and prev in _MAGNITUDES and j + 1 < n \
                    and _low(tokens[j + 1]) in NUMBER_WORDS:
                span.append(j)
            elif lj in _PERCENT or lj in _CURRENCY_AFTER:
                span.append(j)
                j += 1
                break
            elif lj in _MONTHS and (lj != "may" or tokens[j][0].isupper()):
                span.append(j)  # "18 December", "eighteenth of" is rare
            else:
                break
            j += 1
        spans.append(span)
        i = span[-1] + 1
    return spans


def _classify(words):
    """`(kind, heavy)` for one span's words."""
    low = [_low(w) for w in words]
    text = " ".join(words)
    has_digit = bool(_DIGIT.search(text))
    if any(w in _MONTHS for w in low):
        return "date", True
    if "%" in text or any(w in _PERCENT for w in low):
        return "percent", True
    if re.search(r"[$€£]", text) or any(w in _CURRENCY_AFTER for w in low):
        return "money", True
    if any(w in _MAGNITUDES for w in low) or re.search(r"\d[BbMmKk]\b", text):
        return "amount", True
    if has_digit:
        if re.fullmatch(r"(1[89]|20)\d\d(s|'s)?", words[0]) and len(words) == 1:
            return "year", True
        if "." in words[0] and len(words) == 1:
            return "decimal", True
        v = _digit_value(words[0])
        if len(words) == 1 and v is not None and v <= SMALL_MAX \
                and not re.search(r"\d(st|nd|rd|th)$", words[0]):
            return "count", False
        if len(words) == 1 and re.search(r"\d(st|nd|rd|th)$", words[0]) \
                and v is not None and v <= SMALL_MAX:
            return "ordinal", False
        return "amount", True
    if "point" in low:
        return "decimal", True
    if all(w in _ORDINALS for w in low):
        return "ordinal", False
    if len(low) == 1 and low[0] in _UNITS and _UNITS[low[0]] <= SMALL_MAX:
        return "count", False
    return "amount", True


def figures_in(sentence):
    """`(heavy, small)`: the figures of one sentence and its small numbers,
    each `{"text", "kind", "word_index"}` (the index of its first token among
    the sentence's word tokens, punctuation left out)."""
    tokens = _tokens(sentence)
    word_pos, k = {}, 0
    for i, t in enumerate(tokens):
        if t.isalnum() or _DIGIT.search(t) or t[0].isalpha():
            word_pos[i] = k
            k += 1
    heavy, small = [], []
    for span in _spans(tokens):
        words = [tokens[i] for i in span]
        kind, is_heavy = _classify(words)
        rec = {"text": " ".join(words), "kind": kind,
               "word_index": word_pos.get(span[0], 0),
               "end_index": word_pos.get(span[-1], 0)}
        (heavy if is_heavy else small).append(rec)
    return heavy, small


def _max_run(figs):
    """The longest chain of figures with <= RUN_GAP_WORDS words between two."""
    best = run = 0
    last_end = None
    for f in figs:
        if last_end is not None and f["word_index"] - last_end - 1 <= RUN_GAP_WORDS:
            run += 1
        else:
            run = 1
        best = max(best, run)
        last_end = f["end_index"]
    return best


def measure_fields(fields):
    """The readings over `[(field, text), ...]`, in speaking order."""
    figures = small = words = max_per = max_run = 0
    heavy_sentences, all_figs = [], []
    for field, text in fields:
        text = text or ""
        words += len(text.split())
        for s in sentences(text):
            heavy, sm = figures_in(s)
            figures += len(heavy)
            small += len(sm)
            max_per = max(max_per, len(heavy))
            max_run = max(max_run, _max_run(heavy))
            for f in heavy:
                all_figs.append({"field": field, "text": f["text"], "kind": f["kind"]})
            if len(heavy) > 1:
                heavy_sentences.append({"field": field, "sentence": s,
                                        "figures": [f["text"] for f in heavy]})
    return {
        "figures": figures,
        "words": words,
        "per_10_words": round(figures * 10.0 / words, 3) if words else 0.0,
        "max_per_sentence": max_per,
        "max_run": max_run,
        "small_numbers": small,
        "figure_list": all_figs,
        "heavy_sentences": heavy_sentences,
    }


def measure_text(text, field="text"):
    return measure_fields([(field, text)])


def measure_script(script):
    """The readings over one script's visible narration."""
    return measure_fields([(f, script.get(f) or "") for f in FIELDS])


# --------------------------------------------------------------------------
# history: the channel's accepted videos
# --------------------------------------------------------------------------

def find_root():
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "channels").is_dir() and (p / "pipeline").is_dir():
            return p
    for p in here.parents:
        if (p / "channels").is_dir():
            return p
    return here.parents[3]


def _script_for(data, topic_id, slug=None):
    scripts = [s for s in data.get("scripts") or [] if isinstance(s, dict)]
    same = [s for s in scripts if s.get("topic_id") == topic_id]
    return same[0] if same else None


def history(root=None, channel=None, verdicts=("accepted",)):
    """One row per acceptance-log entry with a findable script: the entry's
    name, verdict and the readings of its `03` script. Rows whose script is
    gone are returned with `missing` set."""
    root = Path(root) if root else find_root()
    log = json.loads((root / "publish" / "acceptance-log.json").read_text())
    rows = []
    for e in log.get("acceptances") or []:
        if verdicts and e.get("verdict") not in verdicts:
            continue
        # CF-0197: an entry logged before a rename names the channel by its
        # former id; the batch lives under the current one.
        ch = resolve_channel(e.get("channel"), root) if e.get("channel") else e.get("channel")
        if channel and ch != resolve_channel(channel, root):
            continue
        f = root / "pipeline" / str(ch) / str(e.get("batch_id")) \
            / "03-content-researcher.json"
        row = {"entry_id": e.get("entry_id"), "slug": e.get("slug"),
               "verdict": e.get("verdict"), "batch_id": e.get("batch_id")}
        try:
            script = _script_for(json.loads(f.read_text()), e.get("topic_id"), e.get("slug"))
        except (OSError, ValueError):
            script = None
        if not script:
            row["missing"] = str(f)
        else:
            m = measure_script(script)
            row.update({k: m[k] for k in ("figures", "words", "per_10_words",
                                           "max_per_sentence", "max_run", "small_numbers")})
            row["heavy_sentences"] = m["heavy_sentences"]
        rows.append(row)
    return rows


def price(rows, max_per_sentence=None, max_per_10_words=None):
    """How many of `rows` a threshold would flag: `(flagged, measured)`."""
    measured = [r for r in rows if "missing" not in r]
    flagged = [r for r in measured
               if (max_per_sentence is not None and r["max_per_sentence"] > max_per_sentence)
               or (max_per_10_words is not None and r["per_10_words"] > max_per_10_words)]
    return flagged, measured


def _print_history(rows):
    measured = [r for r in rows if "missing" not in r]
    print(f"{'video':<34} {'verdict':<9} {'fig':>3} {'words':>5} {'/10w':>5} "
          f"{'max/s':>5} {'run':>3}")
    for r in sorted(measured, key=lambda r: -r["per_10_words"]):
        print(f"{(r['batch_id'] or '')[:16] + ' ' + (r['slug'] or '')[:17]:<34} "
              f"{r['verdict']:<9} {r['figures']:>3} {r['words']:>5} "
              f"{r['per_10_words']:>5.2f} {r['max_per_sentence']:>5} {r['max_run']:>3}")
    for r in rows:
        if "missing" in r:
            print(f"  (no script: {r['entry_id']} - {r['missing']})")
    if not measured:
        return
    print(f"\nprice over {len(measured)} video(s) - how many a threshold flags:")
    for k in (0, 1, 2, 3):
        fl, _ = price(measured, max_per_sentence=k)
        print(f"  max_per_sentence > {k}: {len(fl)}/{len(measured)}")
    for x in (0.25, 0.4, 0.5, 0.6, 0.8, 1.0):
        fl, _ = price(measured, max_per_10_words=x)
        print(f"  per_10_words > {x}: {len(fl)}/{len(measured)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("text")
    t.add_argument("text")
    b = sub.add_parser("batch")
    b.add_argument("batch_file")
    h = sub.add_parser("history")
    h.add_argument("--root")
    h.add_argument("--channel")
    h.add_argument("--all-verdicts", action="store_true",
                   help="rejected videos too, for contrast")
    h.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "text":
        print(json.dumps(measure_text(args.text), indent=1, ensure_ascii=False))
    elif args.cmd == "batch":
        data = json.loads(Path(args.batch_file).read_text())
        for s in data.get("scripts") or []:
            m = measure_script(s)
            print(f"{s.get('script_id')}: {m['figures']} figure(s) / {m['words']} words = "
                  f"{m['per_10_words']} per 10 words, max {m['max_per_sentence']} in a "
                  f"sentence, run {m['max_run']}")
            for hs in m["heavy_sentences"]:
                print(f"    [{hs['field']}] {hs['figures']}")
    else:
        rows = history(args.root, args.channel,
                       verdicts=None if args.all_verdicts else ("accepted",))
        if args.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
        else:
            _print_history(rows)
    return 0


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
