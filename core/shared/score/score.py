#!/usr/bin/env python3
"""CF-0432: the score model - one source of truth for every agent.

The grill of 2026-09-29 ("делать из того, что дают", Q6, Q10-Q14, Q17, Q18,
Q23-Q25): until now every check of the factory either refused a video or kept
quiet about it. The model replaces that with two kinds of rule:

* the **hard list** refuses. Foreign text; footage of someone else's work (by
  the sieve's decision); a video shorter than 30 s or longer than 60 s; more
  than half of the running time in pictures (CF-0418); a broken sound; a
  forbidden topic or a platform policy; a technically broken render (a file
  that does not open, not 9:16 / 1080, voice and subtitles out of sync).
* every other rule is a **penalty**: a price per violation (per block, per
  shot, per second, ...), a multiplier for the hook (the first 5 s) where the
  rule has one, and a cap per rule.

The still share (CF-0418, the user's calls of 2026-09-28 and 2026-09-30) is
two shares of the running time, both measured by the Video Editor's
`scripts/still_share.py` on the plan:

* the **picture share** - images, posters, cards, a meme picture over the
  whole frame (ken burns over a picture is still a picture); a frame held off
  a video does NOT count (variant (a)). Over 50 % (the channel's
  `video_editor.max_still_share`) it is the hard list; 25-50 % is the
  zero-priced `score.still_share`.
* the **stretched share** - the pictures plus the frames held off a video
  that stand more than twice as long as their shot runs in its source and
  longer than 2 s. Over 50 % it costs `score.stretched_still_share` per p.p.,
  capped - a penalty, never a refusal.

A video starts at 100 points; the penalties are subtracted; the result is
graded S, A, B, C, D, E or F against the threshold N (F is below N). A video
that hits the hard list is F whatever its points.

Only **real** penalties count (Q17): a finding marked `source: forecast` - a
prediction of what the render might do - is left out of the score and only
counted in the log, so a forecast can never be what kills a video.

The prices live in `shared/gate-prices.json` (the ledger of CF-0320): the
`score` block holds the start, the threshold and the tiers; every rule of the
model is a row of `rules` with `mode` = `hard` or `penalty`, and a penalty row
carries `penalty: {price, per, hook_mult, cap}`. This module never writes that
file - the prices are the user's to sign (docs/score-model.md). The user signed
the table as it stood on 2026-09-30 (`score.status: signed`, `score.signature`,
and a `signature` on every `score.*` row); the signature changed no price.

The log is the format `05` (the editor), the run summary and the message to
the user (CF-0434) read:

    {"start": 100, "score": 83, "tier": "B", "threshold": 60, "passed": true,
     "hard": [ {rule, where, note, note_ru?} ... ],
     "log": [ {"rule", "where": {"block"|"shot"|"t"|...}, "price": -6,
               "units", "hook", "capped", "source", "note", "note_ru"?} ... ],
     "by_rule": {rule: {"raw": -30, "charged": -24, "cap": 24}},
     "forecast_ignored": 0}

`summary_line(block)` is the same log as one line (CF-0434) - the form `05`,
`RUN_SUMMARY` and the message to the user carry:

    B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts

and `stages_block(stages)` is the log of a video across its stages (`plan`,
`render`, `qc`, `judge`: the `plan.score.json` beside its plan), with the stage
after which the points first fell under N (`stopped_at`) - the early stop.

`note` is the detector's English; `note_ru` (CF-0751) is the same note in
short Russian for the command center, present only where a template of
NOTE_TEMPLATES covers the note (`note_ru()`, `with_note_ru()` for an old log).

`price` in the log is what that finding actually cost after the rule's cap:
the entries of the log always sum to `score - start` (before the floor at 0).
"""
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "shared" / "gate-prices.json"

HARD, PENALTY = "hard", "penalty"
# `score.status` of the price table: `draft` until the user signs it, `signed`
# after (the user signed the table as it stood on 2026-09-30). The status
# changes nothing in the arithmetic; a `signed` table must carry the user's
# hand-written `score.signature` ({user, date, note}) - nothing here writes one.
STATUS_DRAFT, STATUS_SIGNED = "draft", "signed"
STATUSES = (STATUS_DRAFT, STATUS_SIGNED)
MODES = (HARD, PENALTY)
FORECAST = "forecast"
HOOK_SECONDS = 5.0

# The hard list of the grill, by name. A ledger that drops one of these is
# refused when it is loaded: the hard list is the user's decision, and a
# price table is not the place it can be quietly shortened.
HARD_RULES = (
    "score.hard.foreign_text",          # чужой текст в кадре
    "score.hard.foreign_work_footage",  # кадры чужого фильма, по решению сита
    "score.hard.duration_out_of_range",  # короче 30 с или длиннее 60 с
    "score.hard.still_share_over_half",  # больше 50 % картинок (CF-0418, вариант (а))
    "score.hard.sound_broken",          # проблемы со звуком
    "score.hard.forbidden_topic",       # запретные темы, политика площадки
    "score.hard.render_defect",         # битый файл, не 9:16 / 1080, рассинхрон
)

MIN_SECONDS, MAX_SECONDS = 30.0, 60.0
STILL_SHARE_HARD = 0.50     # above it: the hard list
STILL_SHARE_SOFT = 0.25     # from it up to the hard line: a penalty per p.p.
STRETCHED_STILL_FROM = 0.50  # pictures + stretched held frames: a penalty per p.p. over it
SHORT_LENGTH_BELOW = 45.0   # 30-45 s: a penalty per started 3 s under 45
SHORT_LENGTH_STEP = 3.0


class ScoreModelError(ValueError):
    """The price table cannot be used as it stands."""


# --------------------------------------------------------------------------
# the model, read out of the ledger
# --------------------------------------------------------------------------

def read_ledger(path=None):
    p = Path(path or LEDGER)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScoreModelError(f"cannot read the price table {p}: {e}") from e
    if not isinstance(d, dict):
        raise ScoreModelError(f"{p}: not an object")
    return d


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def load_model(ledger=None):
    """The model as a plain dict: {start, threshold, tiers: [(name, floor)],
    status, signature, rules: {name: {mode, price, per, hook_mult, cap, ...}}}.

    `ledger` is a path or an already-read dict."""
    d = ledger if isinstance(ledger, dict) else read_ledger(ledger)
    s = d.get("score")
    if not isinstance(s, dict):
        raise ScoreModelError("the price table has no `score` block")
    start, thr = _num(s.get("start")), _num(s.get("threshold"))
    if start is None or thr is None:
        raise ScoreModelError("`score.start` and `score.threshold` must be numbers")
    tiers = s.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise ScoreModelError("`score.tiers` must map a tier to its floor")
    order = sorted(((str(k), _num(v)) for k, v in tiers.items()),
                   key=lambda kv: -(kv[1] if kv[1] is not None else -1e9))
    if any(v is None for _, v in order):
        raise ScoreModelError("every tier floor must be a number")
    if order[-1][1] != thr:
        raise ScoreModelError(f"the lowest passing tier must start at the threshold "
                              f"{thr}, not {order[-1][1]} - F is exactly `below N`")
    status = s.get("status")
    if status not in STATUSES:
        raise ScoreModelError(f"`score.status` is one of {list(STATUSES)}, not {status!r}")
    sig = s.get("signature")
    if status == STATUS_SIGNED and not (isinstance(sig, dict) and sig.get("user")
                                        and sig.get("date")):
        raise ScoreModelError("a `signed` price table needs the user's `score.signature` "
                              "({user, date, note}) - a status is not a signature")
    rules = {}
    for name, row in (d.get("rules") or {}).items():
        if not isinstance(row, dict) or row.get("mode") not in MODES:
            continue
        r = {"mode": row["mode"], "what": row.get("what"), "note": row.get("note"),
             "detector": row.get("detector")}
        if row["mode"] == PENALTY:
            p = row.get("penalty")
            if not isinstance(p, dict) or _num(p.get("price")) is None:
                raise ScoreModelError(f"{name}: a penalty rule needs `penalty.price`")
            cap = p.get("cap")
            mult = p.get("hook_mult")
            if cap is not None and (_num(cap) is None or cap < 0):
                raise ScoreModelError(f"{name}: `penalty.cap` is a non-negative number or null")
            if mult is not None and (_num(mult) is None or mult < 1):
                raise ScoreModelError(f"{name}: `penalty.hook_mult` is a number >= 1 or null")
            if p["price"] < 0:
                raise ScoreModelError(f"{name}: `penalty.price` is written as a positive cost")
            r.update(price=p["price"], per=p.get("per"), cap=cap, hook_mult=mult)
        rules[name] = r
    missing = [h for h in HARD_RULES if rules.get(h, {}).get("mode") != HARD]
    if missing:
        raise ScoreModelError(f"the hard list is short of {', '.join(missing)}")
    return {"start": start, "threshold": thr, "tiers": order,
            "status": status, "signature": sig if isinstance(sig, dict) else None,
            "rules": rules}


def mode_of(name, ledger=None):
    """`hard`, `penalty` or None for a rule the model does not know."""
    d = ledger if isinstance(ledger, dict) else read_ledger(ledger)
    row = (d.get("rules") or {}).get(name)
    m = row.get("mode") if isinstance(row, dict) else None
    return m if m in MODES else None


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

def finding(rule, where=None, units=1, hook=False, source="metric", note=None):
    """One violation. `where` is {"block": i} / {"shot": j} / {"t": seconds} or
    any mix; `units` is how many of the rule's `per` it counts (seconds of
    speech with no picture, percentage points of stills ...); `hook` marks
    the first 5 s; `source` is `metric`, `user_verdict` (a defect the user saw
    and no detector sees yet - recorded honestly as such) or `forecast`."""
    return {"rule": rule, "where": dict(where or {}), "units": units, "hook": bool(hook),
            "source": source, "note": note}


def in_hook(t):
    return t is not None and _num(t) is not None and t < HOOK_SECONDS


def duration_findings(seconds, where=None):
    """The hard line (30-60 s) and the short-length penalty (30-45 s)."""
    if _num(seconds) is None:
        return []
    w = {"t": round(seconds, 2), **(where or {})}
    if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
        return [finding("score.hard.duration_out_of_range", w,
                        note=f"{seconds:.1f} s, outside {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} s")]
    if seconds < SHORT_LENGTH_BELOW:
        n = math.ceil(round((SHORT_LENGTH_BELOW - seconds) / SHORT_LENGTH_STEP, 6))
        return [finding("score.short_length", w, units=n,
                        note=f"{seconds:.1f} s: {n} x {SHORT_LENGTH_STEP:.0f} s under "
                             f"{SHORT_LENGTH_BELOW:.0f} s")]
    return []


def still_share_findings(share):
    """The hard line above 50 % of pictures (CF-0418, variant (a): a frame
    held off a video does not count) and the per-p.p. penalty from 25 % up to
    it. `share` is a fraction 0..1 - `share` of the Video Editor's
    `still_share.measure()`."""
    if _num(share) is None:
        return []
    pct = round(share * 100, 1)
    if share > STILL_SHARE_HARD:
        return [finding("score.hard.still_share_over_half", {},
                        note=f"{pct} % of the running time in pictures")]
    pp = round((share - STILL_SHARE_SOFT) * 100, 1)
    if pp > 0:
        return [finding("score.still_share", {}, units=pp,
                        note=f"{pct} % in pictures: {pp} p.p. over 25 %")]
    return []


def stretched_still_findings(share, note=None):
    """CF-0418 (the user, 2026-09-30): pictures + frames held off a video and
    stretched past twice their shot and 2 s, over 50 % of the running time -
    `score.stretched_still_share` per p.p. over. `share` is a fraction 0..1
    of the Video Editor's `still_share.measure()` (`stretched.share`)."""
    if _num(share) is None:
        return []
    pp = round((share - STRETCHED_STILL_FROM) * 100, 1)
    if pp <= 0:
        return []
    return [finding("score.stretched_still_share", {}, units=pp,
                    note=note or f"{round(share * 100, 1)} % in pictures and stretched held "
                                 f"frames: {pp} p.p. over {STRETCHED_STILL_FROM * 100:.0f} %")]


# --------------------------------------------------------------------------
# the score
# --------------------------------------------------------------------------

def tier_of(points, model):
    for name, floor in model["tiers"]:
        if points >= floor:
            return name
    return "F"


def score(findings, model=None):
    """The score and its log. Unknown rules are refused rather than silently
    costing nothing - a detector that reports a rule the price table does not
    carry is a bug the log must not hide."""
    m = model if (isinstance(model, dict) and "rules" in model) else load_model(model)
    log, hard, by_rule, ignored = [], [], {}, 0
    for f in findings:
        name = f["rule"]
        r = m["rules"].get(name)
        if r is None:
            raise ScoreModelError(f"no such rule in the price table: {name}")
        if f.get("source") == FORECAST:
            ignored += 1
            continue
        if r["mode"] == HARD:
            hard.append(_with_note_ru({"rule": name, "where": f.get("where") or {},
                                       "note": f.get("note"), "source": f.get("source")}))
            continue
        units = _num(f.get("units"))
        units = 1 if units is None else units
        mult = r.get("hook_mult") if f.get("hook") and r.get("hook_mult") else 1
        raw = r["price"] * units * mult
        agg = by_rule.setdefault(name, {"raw": 0, "charged": 0, "cap": r.get("cap")})
        room = (r["cap"] - (-agg["charged"])) if r.get("cap") is not None else raw
        charged = max(0, min(raw, room))
        agg["raw"] -= raw
        agg["charged"] -= charged
        log.append(_with_note_ru({
            "rule": name, "where": f.get("where") or {}, "price": -_round(charged),
            "units": units, "hook": bool(f.get("hook")) and mult != 1,
            "capped": charged < raw, "source": f.get("source"), "note": f.get("note")}))
    for agg in by_rule.values():
        agg["raw"], agg["charged"] = _round(agg["raw"]), _round(agg["charged"])
    total = m["start"] + sum(e["price"] for e in log)
    points = _round(max(0, total))
    passed = not hard and points >= m["threshold"]
    tier = "F" if hard else tier_of(points, m)
    return {"start": m["start"], "score": points, "tier": tier, "threshold": m["threshold"],
            "passed": passed, "hard": hard, "log": log, "by_rule": by_rule,
            "forecast_ignored": ignored, "prices_status": m.get("status")}


def _round(x):
    x = round(x, 2)
    return int(x) if float(x).is_integer() else x


def render(res, title=None):
    """The log as markdown lines - the form a run summary pastes."""
    head = f"{res['score']} / {res['start']} - {res['tier']}"
    if res["hard"]:
        head += " (hard list: " + ", ".join(h["rule"].split(".")[-1] for h in res["hard"]) + ")"
    out = [f"**{title}**: {head}" if title else f"**{head}**", ""]
    if res["log"] or res["hard"]:
        out += ["| rule | where | price |", "|---|---|---|"]
        for h in res["hard"]:
            out.append(f"| `{h['rule']}` | {_where(h['where'])} | refused |")
        for e in res["log"]:
            p = f"{e['price']}" + (" (hook)" if e["hook"] else "") + (" (cap)" if e["capped"] else "")
            out.append(f"| `{e['rule']}` | {_where(e['where'])} | {p} |")
    return out


def _where(w):
    return ", ".join(f"{k} {v}" for k, v in (w or {}).items()) or "video"


# --------------------------------------------------------------------------
# the log of a video across its stages, and its one line (CF-0434)
# --------------------------------------------------------------------------

# The stages a video's score log is written by, in the order they happen. The
# Editor's `scripts/score_log.py` writes `plan`, `render` and `qc` into
# `work/<slug>/plan.score.json`; the frame judge (`scripts/frame_judge_gate.py`)
# writes `judge`. Recording a stage replaces it and forgets every later one.
STAGE_PLAN, STAGE_RENDER, STAGE_QC, STAGE_JUDGE = "plan", "render", "qc", "judge"
STAGES = (STAGE_PLAN, STAGE_RENDER, STAGE_QC, STAGE_JUDGE)
LOG_SCHEMA = "cf0434.score_log/1"
LOG_SUFFIX = ".score.json"
LINE_FIELD = "score_line"

# Russian labels of the line. A rule missing here is printed by its own short
# name - never dropped; the command center shows the line as it is, so every
# rule of the ledger has one (CF-0749, tests/test_score_model.py).
LABELS = {
    "low_similarity": "похожесть",
    "pace_below_floor": "темп",
    "hold_band_exceeded": "полоса удержания",
    "block_band_exceeded": "лишние блоки",
    "low_framing": "кадрирование",
    "low_resolution": "разрешение",
    "low_brightness": "яркость",
    "frozen_block": "зависший кадр",
    "crop_cuts_subject": "кроп режет героя",
    "panel_partly_cut": "вставка обрезана",
    "abstract_background": "абстрактный фон",
    "repeated_shot": "повтор кадра",
    "speech_without_picture": "речь без кадра",
    "still_share": "доля картинок",
    "stretched_still_share": "растянутые кадры",
    "held_soft_frame": "мягкий удержанный кадр",
    "held_moving_face": "застывшее лицо из движения",
    "tail_over_band_top": "хвост сверх полосы",
    "held_one_source": "удержания из одного источника",
    "fact_anchor_early": "кадр раньше слов",
    "thin_picture": "тонкая картинка",
    "narrow_strip_on_blur": "полоса на размытом фоне",
    "held_cut_subject": "удержание режет героя",
    "held_soft_stretch": "растянутый мягкий кадр",
    "off_topic_shot": "шот не по теме",
    "short_length": "длина",
    "no_lofi_bed": "нет подложки",
    "card_over_face": "карточка на лице",
    "meme_caption_blank": "мем без субтитров",
    "presentation_blur_fill": "подача: размытый фон",
    "presentation_luma_lift": "подача: подъём яркости",
}
HARD_LABELS = {
    "foreign_text": "чужой текст",
    "foreign_work_footage": "кадры чужого фильма",
    "duration_out_of_range": "длина вне 30–60 с",
    "still_share_over_half": "картинок больше половины",
    "sound_broken": "звук",
    "forbidden_topic": "запретная тема",
    "render_defect": "брак рендера",
    "screen_recording": "запись с экрана",
    "footage_defect": "брак футажа",
}
# --------------------------------------------------------------------------
# CF-0751: the Russian of a finding's `note`
# --------------------------------------------------------------------------

# A finding's `note` is the detector's English (it stays in the log as is). The
# command center shows the user `note_ru`: the same note in short plain
# Russian, the variable parts (blocks, shots, files, seconds, sizes) kept and
# the English free text a detector appends (a reason, the describer's phrase,
# a task number) left out. One table, applied where the log is assembled
# (`score()`): a note no template matches gets no `note_ru` - never a wrong
# one. The frame judge's own prose (`judge_*` and `footage_defect` evidence,
# its description of foreign text) is the model's words and has no template;
# a footage defect still gets its kind, foreign text its rule.
# tests/test_score_note_ru.py walks every place in the factory that
# writes a finding with a note and fails on a shape no template covers.
_N = r"[+-]?\d+(?:\.\d+)?"
_CF = r"(?: \(CF-\d+\))*"

SOFT_RU = {"low framing": "плохое кадрирование", "low brightness": "тёмная картинка",
           "low resolution": "низкое разрешение", "off topic shot": "шот не по теме",
           "low sharpness": "нерезкая картинка"}
PRESENTATION_RU = {"blur fill": "размытый фон", "luma lift": "подъём яркости"}
FIX_RU = {"low framing": "плохого кадрирования", "low brightness": "тёмной картинки"}
CARD_RU = {"comparison_line": "строка сравнения", "meme": "мем", "proof": "доказательство",
           "end_card": "финальная карточка", "insert": "вставка", "a card": "карточка",
           "own_graphic": "своя графика", "fact": "карточка факта"}
REPEAT_RU = {"repeat": "повтор", "near_duplicate": "почти повтор"}
DEFECT_RU = {"screen_recording": "запись с экрана", "smeared": "смазанная картинка",
             "thin_strip": "картинка тонкой полосой", "cut_subject": "герой обрезан"}
UNIT_RU = {"blocks": "блоков", "blocks/min": "блоков/мин"}


def _shot_ru(s):
    """A shot id as is; a clip path by its file name."""
    return s.rsplit("/", 1)[-1] if "/" in s else s


def _block_ru(g):
    return f"блок {g['b']}" + (f".{g['c']}" if g.get("c") else "")


# (regex over the whole note, Russian: a format string over the groups or a
# function of them). Numbers are printed with a decimal comma.
NOTE_TEMPLATES = (
    # the length (score.duration_findings)
    (rf"(?P<s>{_N}) s, outside (?P<a>{_N})-(?P<b>{_N}) s", "{s} с — вне {a}–{b} с"),
    (rf"(?P<s>{_N}) s: (?P<n>\d+) x (?P<step>{_N}) s under (?P<below>{_N}) s",
     "{s} с — короче {below} с ({n} × {step} с)"),
    # pictures and held frames (score.still_share_findings, still_share.py)
    (rf"(?P<p>{_N}) % of the running time in pictures", "картинки — {p} % хронометража"),
    (rf"(?P<p>{_N}) % of the running time in pictures, over (?P<x>{_N}) % - .*",
     "картинки — {p} % хронометража, больше {x} %"),
    (rf"(?P<p>{_N}) % in pictures: (?P<pp>{_N}) p\.p\. over (?P<x>{_N}) %",
     "картинки — {p} %: на {pp} п. п. больше {x} %"),
    (rf"(?P<p>{_N}) % in pictures and stretched held frames: (?P<pp>{_N}) p\.p\. over "
     rf"(?P<x>{_N}) %", "картинки и растянутые кадры — {p} %: на {pp} п. п. больше {x} %"),
    (rf"(?P<p>{_N}) % with stretched held frames \((?P<pp>{_N}) p\.p\. over (?P<x>{_N}) %\)"
     r"(?:: .*)?", "картинки и растянутые кадры — {p} %: на {pp} п. п. больше {x} %"),
    (rf"held frames: (?P<s>{_N}) s, all off one source (?P<src>\S+) \(stretched "
     rf"(?P<st>{_N}) s\)(?: \(score\.held_one_source\))?",
     "удержанные кадры: {s} с, все из одного источника {src} (растянуто {st} с)"),
    # the render and QC (score_log.py: render_findings, qc_findings)
    (r"frame (?P<w>\w+)x(?P<h>\w+), not (?P<W>\d+)x(?P<H>\d+)", "кадр {w}×{h}, а нужен {W}×{H}"),
    (r"clip block rendered as a still \(qc_render frozen_blocks\)", "видеоблок вышел стоп-кадром"),
    (r"framed on a face, none in the picture(?:: .*)?", "кадр выстроен по лицу, а лица в кадре нет"),
    (r"a sliver of an inset panel: (?P<p>\d+)% (?:of it )?in frame",
     "от вставки в кадре лишь полоска: {p} %"),
    (r"inset panel partly in frame(?:: (?P<p>\d+)%)?",
     lambda g: "вставка видна частично" + (f": {g['p']} %" if g.get("p") else "")),
    (r"face under (?P<k>.+)",
     lambda g: "лицо под карточкой: " + " + ".join(
         CARD_RU.get(k, k.replace("_", " ")) for k in g["k"].split(" + "))),
    (r"block on the procedural background", "блок на абстрактном фоне"),
    (r"(?P<k>\w+) of block (?P<b>\w+) \((?P<sim>[^)]*)\)",
     lambda g: f"{REPEAT_RU.get(g['k'], 'повтор')} блока {g['b']} ({g['sim']})"),
    (r"luma_lift x(?P<g>\S+) left mean luma (?P<l>\S+) on the render",
     "подъём яркости ×{g} оставил среднюю яркость {l} на рендере"),
    (r"no bed in the mix \(qc_render\)", "в миксе нет музыкальной подложки"),
    (r"a meme block with none of our captions under it", "мем без наших субтитров"),
    # qc_render.py failures, as score_log.qc_findings routes them (cut at 160)
    (r"shot with burned-in text: block (?P<b>\d+) \((?P<shot>[^)]*)\).*",
     lambda g: f"чужой вшитый текст: блок {g['b']} ({_shot_ru(g['shot'])})"),
    (r"supplement shot without the entity: block (?P<b>\d+) \((?P<shot>[^)]*)\).*",
     lambda g: f"шот из добавочного источника без героя темы: блок {g['b']} "
               f"({_shot_ru(g['shot'])})"),
    (rf"(?P<n>\d+) silent stretch\(es\) over (?P<x>{_N})s(?:: .*)?",
     "участков тишины дольше {x} с: {n}"),
    (rf"audio peaks at (?P<p>{_N}) dB - clipping", "пик звука {p} дБ — перегруз"),
    (r"no video stream", "нет видеодорожки"),
    (r"no audio stream", "нет звуковой дорожки"),
    (r"resolution (?P<w>\d+)x(?P<h>\d+) != requested (?P<W>\d+)x(?P<H>\d+)",
     "разрешение {w}×{h}, а заказано {W}×{H}"),
    (rf"picture runs (?P<v>{_N})s but the plan says (?P<e>{_N})s.*",
     "картинка идёт {v} с, а по плану {e} с"),
    # the shots (shot_score.py, build_render_plan.py)
    (r"shot (?P<shot>.+?): (?P<w>" + "|".join(SOFT_RU) + r") - the best the pool had"
     + _CF, lambda g: f"шот {_shot_ru(g['shot'])}: {SOFT_RU[g['w']]} — лучшее, что было в пуле"),
    (r"shot (?P<shot>.+?): shown (?P<m>" + "|".join(PRESENTATION_RU) + r") instead of (?P<f>"
     + "|".join(FIX_RU) + r")" + _CF,
     lambda g: f"шот {_shot_ru(g['shot'])}: {PRESENTATION_RU[g['m']]} вместо {FIX_RU[g['f']]}"),
    (r"shot (?P<shot>\S+) scores (?P<x>\S+) against the (?P<f>\S+) floor - the best the pool "
     r"had for .*", lambda g: f"шот {_shot_ru(g['shot'])}: похожесть {g['x']} при пороге "
                              f"{g['f']} — лучшее, что было в пуле"),
    (r"picture scores (?P<x>\S+) against the (?P<f>\S+) floor",
     "картинка: похожесть {x} при пороге {f}"),
    # a fact's picture ahead of its words (fact_anchor.py, check_production_fact.py)
    (rf"(?P<a>.+?)'s picture (?P<lead>{_N}|None) s ahead of the fact's first word "
     rf"\((?P<n>\d+) word\(s\)\)(?:, (?P<u>{_N}) s over the (?P<al>{_N}) s allowance)?",
     lambda g: f"кадр {g['a']} на {g['lead']} с раньше первого слова факта (слов: {g['n']})"
               + (f", на {g['u']} с сверх допуска {g['al']} с" if g.get("u") else "")),
    # held frames (held_motion.py, held_sharpness.py, held_screen.py)
    (rf"(?P<x>{_N}) s of faces held still out of moving shots, (?P<y>{_N}) s over "
     rf"(?P<a>{_N}) s" + _CF, "застывшие лица из движущихся шотов: {x} с, на {y} с больше {a} с"),
    (rf"block (?P<b>\d+)(?: cut (?P<c>\d+))?: held frame sharpness (?P<v>{_N}) under "
     rf"(?P<f>{_N}) for (?P<s>{_N}) s" + _CF,
     lambda g: f"блок {g['b']}" + (f", нарезка {g['c']}" if g.get("c") else "")
               + f": резкость удержанного кадра {g['v']} ниже {g['f']}, {g['s']} с"),
    (rf"block (?P<b>\d+)(?:\.(?P<c>\d+))?: held picture (?P<p>\d+)% of the screen's height "
     rf"\(< (?P<t>\d+)%\) for (?P<s>{_N}) s" + _CF,
     lambda g: f"{_block_ru(g)}: удержанная картинка — {g['p']} % высоты экрана "
               f"(< {g['t']} %), {g['s']} с"),
    (r"block (?P<b>\d+)(?:\.(?P<c>\d+))?: held picture shows (?P<n>\d+) body\(ies\) with the "
     r"head out of frame and no face" + _CF,
     lambda g: f"{_block_ru(g)}: в удержанном кадре тела без головы ({g['n']}), лица нет"),
    (rf"block (?P<b>\d+)(?:\.(?P<c>\d+))?: held (?P<s>{_N}) s at (?P<ss>\S+) on screen "
     r"\(< (?P<f>\S+)\) from a source keeping .*",
     lambda g: f"{_block_ru(g)}: растянутый кадр {g['s']} с мягкий на экране "
               f"({g['ss']} < {g['f']})"),
    (rf"block (?P<b>\d+)(?:\.(?P<c>\d+))?: picture (?P<p>\d+)% of the screen's height "
     rf"\(< (?P<t>\d+)%\) for (?P<s>{_N}) s" + _CF,
     lambda g: f"{_block_ru(g)}: картинка — {g['p']} % высоты экрана (< {g['t']} %), {g['s']} с"),
    (rf"block (?P<b>\d+)(?:\.(?P<c>\d+))?: clip standing nearly still .* as a picture "
     rf"(?P<p>\d+)% of the screen's height \(< (?P<t>\d+)%\) for (?P<s>{_N}) s" + _CF,
     lambda g: f"{_block_ru(g)}: почти неподвижный клип — {g['p']} % высоты экрана "
               f"(< {g['t']} %), {g['s']} с"),
    # the strip on its blurred ground over the whole video (strip_on_blur.py, CF-0878)
    (rf"(?P<s>{_N}) s as a strip under (?P<p>\d+)% of the screen's height, longest "
     rf"(?P<l>{_N}) s, (?P<o>{_N}) s over (?P<a>{_N}) s" + _CF,
     "{s} с картинки полосой на размытом фоне (ниже {p} % высоты экрана), самая длинная "
     "{l} с; на {o} с больше {a} с"),
    # the rhythm (rhythm.py)
    (r"(?P<m>\S+) blocks/min under (?P<pid>\S+?)'s floor (?P<min>\S+): (?P<gap>\S+) short, "
     r"\S+ started block\(s\)/min",
     "темп {m} блоков/мин ниже пола шаблона {pid} ({min}): не хватает {gap}"),
    (r"(?P<m>\S+) (?P<u>blocks(?:/min)?) against (?P<pid>\S+?)'s drawn band (?P<a>[^-\s]+)-"
     r"(?P<b>\S+) blocks(?:/min)?, (?P<over>\S+) block\(s\) over the top",
     lambda g: f"{g['m']} {UNIT_RU[g['u']]} при полосе шаблона {g['pid']} {g['a']}–{g['b']}, "
               f"лишних блоков: {g['over']}"),
    (rf"block of (?P<s>{_N})s, under the (?P<g>{_N})s a picture needs to read - built and "
     r"shown" + _CF, "блок {s} с — короче {g} с, нужных картинке, чтобы прочитаться"),
    (rf"block (?P<i>\d+) held (?P<d>{_N})s, (?P<o>{_N})s over (?P<pid>\S+?)'s hold band top "
     rf"(?P<top>{_N})s",
     "блок {i} держится {d} с — на {o} с дольше верха полосы шаблона {pid} ({top} с)"),
    (rf"block (?P<i>\d+) holds one picture (?P<d>{_N})s, (?P<o>{_N})s over (?P<pid>\S+?)'s "
     rf"observed hold top (?P<top>{_N})s" + _CF,
     "блок {i} держит одну картинку {d} с — на {o} с дольше наблюдаемого верха удержания "
     "шаблона {pid} ({top} с)"),
    (rf"last speech block (?P<i>\d+) held (?P<d>{_N})s, (?P<o>{_N})s over (?P<pid>\S+?)'s "
     rf"hold band top (?P<top>{_N})s \(the last word ends at (?P<w>{_N})s\)" + _CF,
     "последний блок речи {i} держится {d} с — на {o} с дольше верха полосы шаблона {pid} "
     "({top} с); последнее слово кончается на {w} с"),
    # the writer's layout (content-researcher: check_block_capacity, check_anchor_cadence)
    (r"block (?P<b>\S+) \(anchor (?P<a>[^)]*)\) takes (?P<shot>\S+) at (?P<x>\S+) under the "
     r"(?P<f>\S+) floor", lambda g: f"блок {g['b']} (якорь {g['a']}): шот {_shot_ru(g['shot'])}, "
                                    f"похожесть {g['x']} ниже порога {g['f']}"),
    (r"(?P<n>\S+) picture\(s\) replayed = (?P<m>\S+).* against (?P<pid>\S+?)'s \S+ band .*, "
     r"(?P<over>\S+) block\(s\) over the top \(replay estimate" + r"(?:, CF-\d+)?\)",
     "картинок с повтором: {n} — сверх полосы шаблона {pid} на {over} бл. (оценка)"),
    (r"(?P<n>\S+) block\(s\) = (?P<m>\S+).* against (?P<pid>\S+?)'s .*, (?P<over>\S+) "
     r"block\(s\) over the top \(layout estimate\)\.(?: .*)?",
     "блоков: {n} — сверх полосы шаблона {pid} на {over} (оценка по раскладке)"),
    (rf"block (?P<b>\S+) (?P<s>{_N})s over the band top (?P<m>{_N})s \(layout estimate\)",
     "блок {b}: на {s} с дольше верха полосы {m} с (оценка по раскладке)"),
    (rf"(?P<s>{_N})s of speech between two anchors \(estimate\)",
     "{s} с речи между двумя якорями (оценка)"),
    # the frame judge (scripts/frame_judge_gate.py): the kind, never the prose
    (r"foreign on-screen text: .*", "чужой текст в кадре"),
    (r"(?P<k>" + "|".join(DEFECT_RU) + r"): .*", lambda g: f"брак футажа: {DEFECT_RU[g['k']]}"),
)
_NOTE_RES = tuple((re.compile(rx, re.S), ru) for rx, ru in NOTE_TEMPLATES)
_DECIMAL = re.compile(r"[+-]?\d+\.\d+")


def note_ru(note):
    """The Russian of a finding's `note` (CF-0751), or None when no template
    of NOTE_TEMPLATES matches it whole - a note is never half-translated."""
    if not isinstance(note, str) or not note.strip():
        return None
    for rx, ru in _NOTE_RES:
        m = rx.fullmatch(note.strip())
        if m is None:
            continue
        g = {k: (v.replace(".", ",") if v and _DECIMAL.fullmatch(v) else v)
             for k, v in m.groupdict().items()}
        return ru(g) if callable(ru) else ru.format(**g)
    return None


def _with_note_ru(entry):
    ru = note_ru(entry.get("note"))
    return {**entry, "note_ru": ru} if ru else entry


def with_note_ru(block):
    """A score block (`score()` / `stages_block()` / a 05 `score`) with
    `note_ru` on every `hard` and `log` entry a template covers - for a log
    written before CF-0751. The block itself is not changed."""
    if not isinstance(block, dict):
        return block
    out = dict(block)
    for key in ("hard", "log"):
        if isinstance(block.get(key), list):
            out[key] = [_with_note_ru(e) if isinstance(e, dict) else e for e in block[key]]
    return out


JUDGE_PREFIX = "judge_"          # score.judge_contradicts / _foreign / _neutral
NOUNS = {"block": ("блок", "блока", "блоков"),
         "shot": ("шот", "шота", "шотов"),
         "case": ("случай", "случая", "случаев"),
         "repeat": ("повтор", "повтора", "повторов")}
MINUS = "−"


def plural(n, forms):
    """The Russian form of a count: 1 блок, 2 блока, 5 блоков, 21 блок."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


_plural = plural


def _fmt(x):
    x = _round(x)
    return str(x).replace(".", ",") if isinstance(x, float) else str(x)


def _model_of(ledger):
    """A loaded model out of a loaded model, a raw price table (dict) or a
    path; None when the table cannot be read (the line then prints no counts
    rather than failing)."""
    if isinstance(ledger, dict) and "threshold" in ledger and "rules" in ledger:
        return ledger
    try:
        return load_model(ledger)
    except (ScoreModelError, OSError, ValueError):
        return None


def per_of(rule, ledger=None):
    """What one unit of `rule` is (`block`, `shot`, `second`, ...), or None."""
    m = _model_of(ledger)
    return (((m or {}).get("rules") or {}).get(rule) or {}).get("per")


_per_of = per_of


def summary_line(block, ledger=None):
    """One line: `<tier> · <score> — <items>`, items in the order the log
    first charged them, each `−<points> <label>` with a count where the rule
    is priced per block / shot / case / repeat (`(3 блока)` - the sum of the
    rows' `units`, not the number of rows), seconds where it
    is priced per second, `хук` when a hook multiplier applied; the three judge
    rules as one item (`−6 судья: 1 contradicts`). Zero-priced findings are
    left out. A hard finding opens the items: `F · 89 — жёсткий: брак
    рендера; −3 ...`. A block with no score: `очки не посчитаны: <why>`.

        B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts
    """
    if not block or block.get("score") is None:
        return f"очки не посчитаны: {(block or {}).get('error') or 'нет лога'}"
    model = _model_of(ledger)
    head = f"{block.get('tier')} · {_fmt(block['score'])}"
    order, agg = [], {}
    for e in block.get("log") or []:
        rule = str(e.get("rule") or "")
        short = rule.split(".", 1)[1] if rule.startswith("score.") else rule
        key = "judge" if short.startswith(JUDGE_PREFIX) else short
        a = agg.get(key)
        if a is None:
            a = agg[key] = {"price": 0, "n": 0, "units": 0, "hook": False, "rule": rule,
                            "judge": {}}
            order.append(key)
        a["price"] += e.get("price") or 0
        a["n"] += 1
        a["units"] += e.get("units") or 0
        a["hook"] = a["hook"] or bool(e.get("hook"))
        if key == "judge":
            v = short[len(JUDGE_PREFIX):]
            a["judge"][v] = a["judge"].get(v, 0) + 1
    items = []
    for key in order:
        a = agg[key]
        if not a["price"]:
            continue
        pts = f"{MINUS}{_fmt(-a['price'])}"
        if key == "judge":
            items.append(f"{pts} судья: " + ", ".join(f"{n} {v}" for v, n in a["judge"].items()))
            continue
        extra = []
        per = per_of(a["rule"], model) if model else None
        if per in NOUNS:
            # the count is the units charged, not the log rows: one
            # `block_band_exceeded` finding carries every block over the band
            # (CF-0455: `−8 лишние блоки (1 блок)` was 4 blocks in one row)
            extra.append(f"{_fmt(a['units'])} {plural(a['units'], NOUNS[per])}")
        elif per == "second":
            extra.append(f"{_fmt(a['units'])} с")
        if a["hook"]:
            extra.append("хук")
        items.append(f"{pts} {LABELS.get(key, key)}" + (f" ({', '.join(extra)})" if extra else ""))
    hard = []
    for h in block.get("hard") or []:
        short = str(h.get("rule") or "").rsplit(".", 1)[-1]
        lab = HARD_LABELS.get(short, short)
        if lab not in hard:
            hard.append(lab)
    body = ", ".join(items)
    if hard:
        body = "жёсткий: " + ", ".join(hard) + (f"; {body}" if body else "")
    return f"{head} — {body or 'без штрафов'}"


def stops(block):
    """The early stop (CF-0434, Q20-Q21): True when the score was computed and
    its points are under N. The hard list is not this - a hard finding makes
    the tier F in the log, and the gate that found it refuses its own way."""
    if not block or block.get("score") is None or block.get("threshold") is None:
        return False
    return block["score"] < block["threshold"]


def stages_block(stages, ledger=None):
    """The score block of a video's stage records (`[{stage, at, findings}]`,
    the `stages` of a `plan.score.json`): `score()` of every finding in stage
    order, the findings themselves, plus `stages` (per stage: its findings,
    what it charged, the score and tier after it) and `stopped_at` (the first
    stage after which the points were under N, or None)."""
    m = _model_of(ledger) if ledger is not None else load_model()
    if m is None:
        raise ScoreModelError(f"cannot load the price table {ledger!r}")
    rows = [s for s in stages or [] if isinstance(s, dict)]
    rows.sort(key=lambda s: STAGES.index(s["stage"]) if s.get("stage") in STAGES else 99)
    so_far, summary, stopped_at, res = [], [], None, None
    for s in rows:
        found = list(s.get("findings") or [])
        so_far += found
        res = score(so_far, m)
        before = summary[-1]["score_after"] if summary else res["start"]
        summary.append({"stage": s.get("stage"), "at": s.get("at"), "findings": found,
                        "charged": _round(res["score"] - before),
                        "score_after": res["score"], "tier_after": res["tier"]})
        if stopped_at is None and stops(res):
            stopped_at = s.get("stage")
    if res is None:
        res = score([], m)
    return {"findings": so_far, **res, "stages": summary, "stopped_at": stopped_at}


def log_path(plan_path):
    """`work/<slug>/plan.json` -> `work/<slug>/plan.score.json`."""
    p = Path(plan_path)
    return p.with_name(f"{p.stem}{LOG_SUFFIX}")


def read_log(plan_path):
    """The score log file beside a plan, as a dict, or None."""
    try:
        d = json.loads(log_path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("stages"), list) else None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="score", description="score a list of findings (CF-0432)")
    ap.add_argument("findings", help="a JSON file holding a list of findings")
    ap.add_argument("--ledger", default=None)
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    res = score(json.loads(Path(ns.findings).read_text(encoding="utf-8")), ns.ledger)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
