#!/usr/bin/env python3
"""CF-0583: `score.fact_anchor_early` in the video's own score log.

The rule (CF-0538 -> CF-0547, signed by the user 2026-10-06 «цену за кадр
раньше слов подтверждаю»): a visual anchor whose `beat_text` begins before
the script's `production_fact.beat_text` and runs into it asks for the fact's
picture while the narrator is still saying something else. It is never a
refusal - the user, 2026-10-05: «не сошлись картинка с текстом на пару секунд
- это не крит» - it is a price: -2 per second of the anchor's lead over the
fact's first word in the voice (`words.json`) over the 2 s allowance, cap 10
(`shared/gate-prices.json#rules`).

The Content Researcher measures the same thing at step 6b
(`agents/content-researcher/scripts/check_production_fact.py`,
`fact_anchor_record`) and records it on the script in 03. That repo is not on
this one's path and its module imports its own `_score`, so the measurement
is mirrored here, function for function - the same anchors (first occurrence
in `commentary`, begins before the fact, runs into it), the same token rule,
the same locating of a character position in the alignment (6, 4, 3, 2 tokens,
the hit nearest the expected position) - so that the two stages charge the
same seconds for the same script and voice. A change to one is a change to
both; `tests/test_fact_anchor_early.py` pins the shared numbers.

Pure: no I/O but `script_of()` (reads `--script`) and `allowance()` (the
root's price table through `_score`).
"""
import json
import re

import _score

RULE = "score.fact_anchor_early"
FIELD = "production_fact"
COMMENTARY_KEY = "commentary"
ANCHORS_KEY = "visual_anchors"
SPOKEN_SECTIONS = ("hook", COMMENTARY_KEY, "payoff")
LOCATE_TOKENS = (6, 4, 3, 2)
# The signed row's allowance, used only when the table cannot be read (and
# then `has_rule` is False and nothing is charged anyway).
ALLOW_SECONDS = 2
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower().replace("’", "'"))


def alignment_tokens(words):
    """`words.json` as comparable tokens and the word each came from (a word
    that normalises to nothing takes no place, a compound takes two)."""
    toks, owner = [], []
    for i, w in enumerate(words or []):
        for t in _tokens((w or {}).get("word") if isinstance(w, dict) else None):
            toks.append(t)
            owner.append(i)
    return toks, owner


def early_fact_anchors(script):
    """The anchors whose beat begins before the fact beat and runs into it:
    `[{anchor_id, index, words_early, anchor_char, fact_char}]`."""
    fact = (script or {}).get(FIELD)
    commentary = (script or {}).get(COMMENTARY_KEY)
    if not isinstance(fact, dict) or not isinstance(commentary, str):
        return []
    beat = fact.get("beat_text")
    if not isinstance(beat, str) or not beat.strip():
        return []
    f0 = commentary.find(beat)
    if f0 < 0:
        return []
    out = []
    for i, a in enumerate(script.get(ANCHORS_KEY) or []):
        bt = a.get("beat_text") if isinstance(a, dict) else None
        if not isinstance(bt, str) or not bt.strip():
            continue
        a0 = commentary.find(bt)
        if a0 < 0 or a0 >= f0 or a0 + len(bt.rstrip()) <= f0:
            continue
        out.append({"anchor_id": a.get("anchor_id"), "index": i,
                    "words_early": len(commentary[a0:f0].split()),
                    "anchor_char": a0, "fact_char": f0})
    return out


def word_at(script, words, at, section=COMMENTARY_KEY):
    """The index in `words` of the spoken word at character `at` of
    `section`, or None."""
    toks, owner = alignment_tokens(words)
    if not toks:
        return None
    before = 0
    for name in SPOKEN_SECTIONS:
        if name == section:
            break
        before += len(_tokens(script.get(name) if isinstance(script.get(name), str) else ""))
    text = script.get(section) or ""
    expected = before + len(_tokens(text[:at]))
    want = _tokens(text[at:])
    for n in LOCATE_TOKENS:
        seq = want[:n]
        if len(seq) < n:
            continue
        hits = [k for k in range(len(toks) - n + 1) if toks[k:k + n] == seq]
        if hits:
            return owner[min(hits, key=lambda k: (abs(k - expected), k))]
    return None


def leads(script, words):
    """`early_fact_anchors()` with `lead_s` (seconds of voice the anchor's
    first word stands ahead of the fact's first word; None when either is not
    in the alignment) and `anchor_t`."""
    out = []
    for e in early_fact_anchors(script):
        ia = word_at(script, words, e["anchor_char"])
        jf = word_at(script, words, e["fact_char"])
        lead = None
        if ia is not None and jf is not None and jf >= ia:
            try:
                lead = round(float(words[jf]["start"]) - float(words[ia]["start"]), 2)
            except (KeyError, TypeError, ValueError):
                lead = None
        out.append(dict(e, lead_s=lead, anchor_t=None if ia is None else words[ia].get("start")))
    return out


def allowance():
    """The signed row's `allow_seconds` from the root's table, else 2."""
    mod = _score.module()
    try:
        row = ((mod.read_ledger(None) if mod else {}).get("rules") or {}).get(RULE) or {}
        allow = (row.get("penalty") or {}).get("allow_seconds")
        return float(allow) if allow is not None else float(ALLOW_SECONDS)
    except Exception:  # noqa: BLE001 - an unreadable table: the code's own number
        return float(ALLOW_SECONDS)


def findings(script, words, allow=None):
    """One `score.fact_anchor_early` finding (units = seconds of the longest
    lead over the allowance, to 0.1 s - the Researcher's rounding) or []."""
    found = leads(script, words)
    measured = [e["lead_s"] for e in found if e["lead_s"] is not None]
    if not measured:
        return []
    lead = round(max(measured), 2)
    allow = allowance() if allow is None else float(allow)
    units = round(max(0.0, lead - allow), 1)
    if units <= 0:
        return []
    first = min(found, key=lambda e: e["index"])
    t = first.get("anchor_t")
    return [_score.finding(
        RULE, {"anchor": first["anchor_id"], **({"t": t} if t is not None else {})},
        units=units, hook=_score.in_hook(t),
        note=f"{first['anchor_id']}'s picture {lead} s ahead of the fact's first word "
             f"({first['words_early']} word(s)), {units} s over the {allow:g} s allowance")]


def script_of(path, script_id):
    """The script `script_id` of a 03 file, or None (no file, unreadable, not
    there). A plan built without `--script` has no fact to measure."""
    if not path:
        return None
    try:
        batch = json.load(open(path))
    except (OSError, ValueError):
        return None
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    return next((s for s in scripts or []
                 if isinstance(s, dict) and s.get("script_id") == script_id), None)
