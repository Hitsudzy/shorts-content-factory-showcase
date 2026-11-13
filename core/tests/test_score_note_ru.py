#!/usr/bin/env python3
"""CF-0751: the Russian of a finding's `note` (`note_ru`) for the command
center.

Every detector of the factory writes its finding's `note` in English; the
score model (`shared/score/score.py`) puts `note_ru` beside it on every `hard`
and `log` entry a template of NOTE_TEMPLATES covers. The checks:

* the real notes of the batches (as they stood in the 05/06 logs on
  2026-10-14, copied here as text) come out in the Russian expected;
* the frame judge's own prose gets no `note_ru` - not a half-translation;
* `score()` and `with_note_ru()` put the field where the center reads it;
* **every place in the factory that writes a finding with a note** (root
  `shared/`, `scripts/`, each agent's `scripts/`: a call of `finding`,
  `_score_finding` or the alias `F` with a note) is named in SITES with the
  shapes its note takes, each shape of an f-string must be one of them, and
  each must have its Russian. A new detector, or a changed note, without a
  template is a red here.

Only the source files are read (as text, with `ast`) - no batch, no pool.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "score"))
sys.path.insert(0, str(ROOT))

import score as S   # noqa: E402

from _pinned_prices import pinned_table as pinned   # noqa: E402


# --------------------------------------------------------------------------
# the real notes
# --------------------------------------------------------------------------

REAL = [
    ("clip block rendered as a still (qc_render frozen_blocks)", "видеоблок вышел стоп-кадром"),
    ("43.6 s: 1 x 3 s under 45 s", "43,6 с — короче 45 с (1 × 3 с)"),
    ("72.8 s, outside 30-60 s", "72,8 с — вне 30–60 с"),
    ("face under proof + comparison_line",
     "лицо под карточкой: доказательство + строка сравнения"),
    ("framed on a face, none in the picture: the source has 1 face(s) here and the window "
     "keeps 68% of the best-served one", "кадр выстроен по лицу, а лица в кадре нет"),
    ("a sliver of an inset panel: 31% in frame", "от вставки в кадре лишь полоска: 31 %"),
    ("inset panel partly in frame: 34%", "вставка видна частично: 34 %"),
    ("held frames: 12.40 s, all off one source wIM1PDRvKSE (stretched 9.03 s) "
     "(score.held_one_source)",
     "удержанные кадры: 12,40 с, все из одного источника wIM1PDRvKSE (растянуто 9,03 с)"),
    ("block 6 cut 2: held frame sharpness 0.4762 under 0.53 for 1.71 s (CF-0465)",
     "блок 6, нарезка 2: резкость удержанного кадра 0,4762 ниже 0,53, 1,71 с"),
    ("block 9 held 4.41s, 0.91s over contrast's hold band top 3.5s",
     "блок 9 держится 4,41 с — на 0,91 с дольше верха полосы шаблона contrast (3,5 с)"),
    ("luma_lift x1.274 left mean luma 27.3 on the render",
     "подъём яркости ×1,274 оставил среднюю яркость 27,3 на рендере"),
    ("shot L2NAh3CIdig:15: low resolution - the best the pool had (CF-0435)",
     "шот L2NAh3CIdig:15: низкое разрешение — лучшее, что было в пуле"),
    ("shot xiEmt197Bk8:19 scores 0.1805 against the 0.22 floor - the best the pool had for "
     "'a group of men in suits gathered around a table'",
     "шот xiEmt197Bk8:19: похожесть 0,1805 при пороге 0,22 — лучшее, что было в пуле"),
    ("a meme block with none of our captions under it", "мем без наших субтитров"),
    ("15.01 blocks/min under explainer's floor 15.39: 0.38 short, 1 started block(s)/min",
     "темп 15,01 блоков/мин ниже пола шаблона explainer (15,39): не хватает 0,38"),
    ("25 blocks against list's drawn band 12-24 blocks, 1 block(s) over the top",
     "25 блоков при полосе шаблона list 12–24, лишних блоков: 1"),
    ("shot /x/pipeline/example-film/2026-10-13T1411Z/work/blade-runner-2099/clips/"
     "a03_AwK5KxoJsvk_s023.mp4: shown blur fill instead of low framing (CF-0436)",
     "шот a03_AwK5KxoJsvk_s023.mp4: размытый фон вместо плохого кадрирования"),
    ("shot xe3qx0kXArA:8: shown luma lift instead of low brightness (CF-0436)",
     "шот xe3qx0kXArA:8: подъём яркости вместо тёмной картинки"),
    ("near_duplicate of block 9 (0.869)", "почти повтор блока 9 (0,869)"),
    ("85.1 % with stretched held frames (35.1 p.p. over 50.0 %): block 0 held_frame x2.37 "
     "5.94 s, block 1 held_frame x3.25 5.97 s",
     "картинки и растянутые кадры — 85,1 %: на 35,1 п. п. больше 50,0 %"),
    ("last speech block 11 held 5.29s, 1.79s over contrast's hold band top 3.5s (the last "
     "word ends at 31.2s) (CF-0472)",
     "последний блок речи 11 держится 5,29 с — на 1,79 с дольше верха полосы шаблона "
     "contrast (3,5 с); последнее слово кончается на 31,2 с"),
    ("block 12: picture 24% of the screen's height (< 25%) for 3.38 s (CF-0646)",
     "блок 12: картинка — 24 % высоты экрана (< 25 %), 3,38 с"),
    ("thin_strip: tile 12: a wide aurora shot stands as a strip about a quarter of the height",
     "брак футажа: картинка тонкой полосой"),
    ("foreign on-screen text: small white text at top-left reading \"Now streaming\"",
     "чужой текст в кадре"),
]

# The frame judge's prose: the model's words, no template.
PROSE = [
    "tile 9: a warmly lit, smiling woman's face; the narration says \"human, lit in cold teal\"",
    "tiles 5-6: a reaction meme over the narration about the $160M budget",
    "tile9: close-up of a mounted prop gun against a green/blue screen - BTS rig",
]


def test_the_real_notes_come_out_in_russian():
    bad = [(n, S.note_ru(n), want) for n, want in REAL if S.note_ru(n) != want]
    assert not bad, bad


def test_the_judges_prose_gets_no_russian_and_nothing_is_half_translated():
    assert [S.note_ru(p) for p in PROSE] == [None] * len(PROSE)
    assert S.note_ru(None) is None and S.note_ru("") is None
    # a template matches the whole note, never a head of it
    assert S.note_ru("no video stream and more") is None
    for _, ru in REAL:
        assert not re.search(r"\b(the|of|over|under|shot|block)\b", ru), ru


def test_score_puts_note_ru_beside_note_on_the_log_and_the_hard_list():
    m = S.load_model(pinned())
    res = S.score([
        S.finding("score.frozen_block", {"block": 3},
                  note="clip block rendered as a still (qc_render frozen_blocks)"),
        S.finding("score.hard.render_defect", {}, note="no audio stream"),
        S.finding("score.judge_neutral", {"block": 1}, note=PROSE[0]),
        S.finding("score.low_framing", {"block": 2}),
    ], m)
    log = {e["rule"]: e for e in res["log"]}
    assert log["score.frozen_block"]["note_ru"] == "видеоблок вышел стоп-кадром", log
    assert log["score.frozen_block"]["note"].startswith("clip block"), log
    assert "note_ru" not in log["score.judge_neutral"], log
    assert "note_ru" not in log["score.low_framing"], log
    assert res["hard"][0]["note_ru"] == "нет звуковой дорожки", res["hard"]
    # the stages block (plan.score.json, 05) carries the same entries
    st = S.stages_block([{"stage": "qc", "at": "t", "findings": [
        S.finding("score.frozen_block", {"block": 3},
                  note="clip block rendered as a still (qc_render frozen_blocks)")]}], m)
    assert st["log"][0]["note_ru"] == "видеоблок вышел стоп-кадром", st


def test_with_note_ru_fills_an_old_log_without_changing_it():
    old = {"score": 90, "hard": [{"rule": "score.hard.sound_broken", "note": "no audio stream"}],
           "log": [{"rule": "score.repeated_shot", "note": "repeat of block 2 (1.0)"},
                   {"rule": "score.judge_neutral", "note": PROSE[1]}]}
    new = S.with_note_ru(old)
    assert new["hard"][0]["note_ru"] == "нет звуковой дорожки", new
    assert new["log"][0]["note_ru"] == "повтор блока 2 (1,0)", new
    assert "note_ru" not in new["log"][1], new
    assert "note_ru" not in old["hard"][0] and "note_ru" not in old["log"][0], old
    assert S.with_note_ru(None) is None


# --------------------------------------------------------------------------
# every note the code can write
# --------------------------------------------------------------------------

# Where findings are written: the root's shared/ and scripts/, every agent's
# scripts/ (each its own repo, checked out under agents/).
SCAN = [ROOT / "shared", ROOT / "scripts"] + sorted(
    p / "scripts" for p in (ROOT / "agents").glob("*") if (p / "scripts").is_dir())
SKIP_PARTS = {"tests", ".venv", ".claude", "node_modules", "build"}
# constructor name -> the index of `note` when passed by position
CONSTRUCTORS = {"finding": 5, "F": 5, "_score_finding": 4}
# content-researcher's `_score.finding(rule, where, units, hook, note, ...)`
CR_FINDING_POS = 4
# Files whose findings never reach a score log the center reads, and why.
EXEMPT_FILES = {
    "scripts/score_calibration.py": "the calibration of videos already made (CF-0432), "
                                    "scored into its own report, never into a batch log",
}
WILD = "\x00"   # a part of the note the source cannot spell (a name, a call)

# `<file>::<function>` -> the shapes of the notes written there: one sample per
# shape, real where a batch has shown it. A sample of None means the place's
# note is the frame judge's prose (no template by design).
SITES = {
    "shared/score/score.py::duration_findings": [
        "72.8 s, outside 30-60 s", "43.6 s: 1 x 3 s under 45 s"],
    "shared/score/score.py::still_share_findings": [
        "55.0 % of the running time in pictures", "30.7 % in pictures: 5.7 p.p. over 25 %"],
    "shared/score/score.py::stretched_still_findings": [
        "61.2 % in pictures and stretched held frames: 11.2 p.p. over 50 %"],
    "scripts/frame_judge_gate.py::defect_findings": [
        "thin_strip: tile 12: a wide aurora shot stands as a strip",
        "smeared: tile 25: the whole picture is a heavy out-of-focus smear",
        "cut_subject: tile 3: the head is out of frame",
        "screen_recording: tile 4: a phone screen with a browser"],
    "scripts/frame_judge_gate.py::judge_findings": [
        "foreign on-screen text: burned-in English subtitle \"Don't worry,\" at bottom-center",
        None],
    "agents/content-researcher/scripts/check_production_fact.py::fact_anchor_record": [
        "a03's picture 1.4 s ahead of the fact's first word (3 word(s))"],
    "agents/content-researcher/scripts/check_block_capacity.py::similarity_findings": [
        "block 4 (anchor a03) takes xiEmt197Bk8:19 at 0.18 under the 0.22 floor"],
    "agents/content-researcher/scripts/check_block_capacity.py::picture_finding": [
        "27 picture(s) replayed = 27 blocks against list's drawn band 12-24 blocks, 3 block(s) "
        "over the top (replay estimate, CF-0365)"],
    "agents/content-researcher/scripts/check_anchor_cadence.py::block_band_finding": [
        "27 block(s) = 27 blocks against list's drawn band 12-24 blocks, 3 block(s) over the "
        "top (layout estimate). Axis: cut the list to 24 items",
        "27 block(s) = 27 against contrast's ordered floor 12 / observed ceiling 24, 3 block(s) "
        "over the top (layout estimate)."],
    "agents/content-researcher/scripts/check_anchor_cadence.py::score_findings": [
        "block 7 1.2s over the band top 3.5s (layout estimate)",
        "9.4s of speech between two anchors (estimate)"],
    "agents/video-editor/scripts/build_render_plan.py::similarity_findings": [
        "shot xiEmt197Bk8:19 scores 0.1805 against the 0.22 floor - the best the pool had for "
        "'a group of men in suits'",
        "picture scores 0.19 against the 0.22 floor"],
    "agents/video-editor/scripts/fact_anchor.py::findings": [
        "a03's picture 1.4 s ahead of the fact's first word (3 word(s)), 0.4 s over the 1 s "
        "allowance"],
    "agents/video-editor/scripts/held_motion.py::findings": [
        "3.20 s of faces held still out of moving shots, 1.20 s over 2 s (CF-0481)"],
    "shared/strip_on_blur.py::finding": [
        "10.2 s as a strip under 33% of the screen's height, longest 3.33 s, 5.2 s over 5 s "
        "(CF-0878)"],
    "agents/video-editor/scripts/held_screen.py::findings": [
        "block 12: held picture 24% of the screen's height (< 25%) for 3.38 s (CF-0646)",
        "block 3.1: held picture shows 2 body(ies) with the head out of frame and no face "
        "(CF-0646)",
        "block 5: held 4.20 s at 0.31 on screen (< 0.35) from a source keeping 0.8 of its "
        "detail at half scale (>= 0.6) (CF-0646)",
        "block 12: picture 24% of the screen's height (< 25%) for 3.38 s (CF-0646)",
        "block 8.2: clip standing nearly still (frame-to-frame 0.004 < 0.01 at 0.5 s steps) as "
        "a picture 40% of the screen's height (< 50%) for 4.10 s (CF-0650) (CF-0646)"],
    "agents/video-editor/scripts/held_sharpness.py::findings": [
        "block 5: held frame sharpness 0.5244 under 0.53 for 2.35 s (CF-0465)",
        "block 6 cut 2: held frame sharpness 0.4762 under 0.53 for 1.71 s (CF-0465)"],
    "agents/video-editor/scripts/rhythm.py::pace_findings": [
        "15.01 blocks/min under explainer's floor 15.39: 0.38 short, 1 started block(s)/min"],
    "agents/video-editor/scripts/rhythm.py::block_band_findings": [
        "25 blocks against list's drawn band 12-24 blocks, 1 block(s) over the top",
        "31.5 blocks/min against list's drawn band 14-28 blocks/min, 3 block(s) over the top"],
    "agents/video-editor/scripts/rhythm.py::block_too_short_findings": [
        "block of 0.9s, under the 1.2s a picture needs to read - built and shown (CF-0453)"],
    "agents/video-editor/scripts/rhythm.py::hold_band_findings": [
        "block 9 held 4.41s, 0.91s over contrast's hold band top 3.5s"],
    "agents/video-editor/scripts/rhythm.py::held_frame_over_band_findings": [
        "block 4 holds one picture 10.1s, 2.1s over list's observed hold top 8.0s (CF-0859)"],
    "agents/video-editor/scripts/rhythm.py::tail_over_band_top_findings": [
        "last speech block 11 held 5.29s, 1.79s over contrast's hold band top 3.5s (the last "
        "word ends at 31.2s) (CF-0472)"],
    "agents/video-editor/scripts/score_log.py::render_findings": [
        "frame 720x1280, not 1080x1920"],
    "agents/video-editor/scripts/score_log.py::qc_findings": [
        "clip block rendered as a still (qc_render frozen_blocks)",
        "framed on a face, none in the picture: the source has 2 face(s) here",
        "a sliver of an inset panel: 31% in frame",
        "inset panel partly in frame: 34%", "inset panel partly in frame",
        "face under meme + comparison_line", "face under a card",
        "block on the procedural background",
        "near_duplicate of block 9 (0.869)", "repeat of block 2 (1.0)",
        # qc_render.py's failures, routed by their words (cut at 160)
        "shot with burned-in text: block 4 (xe3qx0kXArA:19) - CF-0351: burned-in text",
        "supplement shot without the entity: block 7 (d7b1ilF5290:46) - CF-0348: no entity",
        "2 silent stretch(es) over 1.5s: 2.10s at 12.00s - dead air",
        "audio peaks at 0.10 dB - clipping",
        "no video stream", "no audio stream",
        "resolution 720x1280 != requested 1080x1920",
        "picture runs 44.10s but the plan says 43.50s (the voiceover) (+0.60s adrift)",
        "luma_lift x1.274 left mean luma 27.3 on the render",
        "no bed in the mix (qc_render)",
        "a meme block with none of our captions under it"],
    "agents/video-editor/scripts/shot_score.py::plan_findings": [
        "shot L2NAh3CIdig:15: low resolution - the best the pool had (CF-0435)",
        "shot L2NAh3CIdig:9: low brightness - the best the pool had (CF-0435)",
        "shot commons-187156855:2: low framing - the best the pool had (CF-0435)",
        "shot xe3qx0kXArA:19: off topic shot - the best the pool had (CF-0435)",
        "shot xe3qx0kXArA:21: low sharpness - the best the pool had (CF-0435)"],
    "agents/video-editor/scripts/shot_score.py::presentation_findings": [
        "shot wIM1PDRvKSE:40: shown blur fill instead of low framing (CF-0436)",
        "shot /x/work/harbourlights/clips/a03_-05WmSAmLK4_s019.mp4: shown luma lift instead of low "
        "brightness (CF-0436)"],
    "agents/video-editor/scripts/still_share.py::one_source_findings": [
        "held frames: 6.78 s, all off one source gM4LkaXwGuY (stretched 0.00 s) "
        "(score.held_one_source)"],
    "agents/video-editor/scripts/still_share.py::findings": [
        "55.3 % of the running time in pictures, over 50 % - 55.3 % (24.00 of 43.39 s): "
        "block 5 proof 5.38 s",
        "30.7 % in pictures: 5.7 p.p. over 25 %",
        "85.1 % with stretched held frames (35.1 p.p. over 50.0 %): block 0 held_frame x2.37 "
        "5.94 s"],
}


def _func_of(tree):
    """node -> the name of the innermost function holding it."""
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            n = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            owner[child] = n
            visit(child, n)
    visit(tree, "<module>")
    return owner


def _skeletons(expr):
    """The shapes a note expression spells, as lists of parts (str literal, or
    WILD). An `a or b` / `a if c else b` gives one shape per branch."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [[expr.value]]
    if isinstance(expr, ast.JoinedStr):
        out = [[]]
        for v in expr.values:
            parts = [[v.value]] if isinstance(v, ast.Constant) else [[WILD]]
            out = [a + b for a in out for b in parts]
        return out
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return [a + b for a in _skeletons(expr.left) for b in _skeletons(expr.right)]
    if isinstance(expr, ast.BoolOp):
        return [s for v in expr.values for s in _skeletons(v)]
    if isinstance(expr, ast.IfExp):
        return _skeletons(expr.body) + _skeletons(expr.orelse)
    if isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Slice):
        return _skeletons(expr.value)      # `note[:160]`: the cut keeps the head
    return [[WILD]]


def _regex(skel):
    return "".join(".*?" if p == WILD else re.escape(p) for p in skel)


def note_sites():
    """[(key, line, [skeleton, ...])] - every call of a finding constructor
    that passes a note, in the scanned trees."""
    out = []
    for base in SCAN:
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if SKIP_PARTS & set(f.relative_to(base).parts[:-1]) or rel in EXEMPT_FILES:
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            owner = _func_of(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name not in CONSTRUCTORS:
                    continue
                note = next((k.value for k in node.keywords if k.arg == "note"), None)
                if note is None:
                    pos = CR_FINDING_POS if "content-researcher" in rel else CONSTRUCTORS[name]
                    if len(node.args) > pos:
                        note = node.args[pos]
                if note is None or (isinstance(note, ast.Constant) and note.value is None):
                    continue
                out.append((f"{rel}::{owner.get(node, '<module>')}", node.lineno,
                            _skeletons(note)))
    return out


def test_the_scan_finds_the_known_writers():
    keys = {k for k, _, _ in note_sites()}
    # the walk itself works: the root's own and the editor's writers are found
    assert "shared/score/score.py::duration_findings" in keys, sorted(keys)
    if (ROOT / "agents" / "video-editor" / "scripts").is_dir():
        assert "agents/video-editor/scripts/score_log.py::qc_findings" in keys, sorted(keys)


def test_every_note_the_code_writes_is_named_and_has_its_russian():
    sites = note_sites()
    found = {k for k, _, _ in sites}
    unnamed = sorted({f"{k} (line {ln})" for k, ln, _ in sites if k not in SITES})
    assert not unnamed, ("a finding with a note no template was checked for (CF-0751) - add "
                         "its shapes to SITES and a template to score.NOTE_TEMPLATES: "
                         f"{unnamed}")
    unseen = []
    for k, ln, skels in sites:
        for skel in skels:
            if skel == [WILD] or not "".join(p for p in skel if p != WILD):
                continue        # spelled elsewhere (a describe(), a QC line): SITES holds
                                # it; an empty `''` is no note at all
            rx = _regex(skel)
            if not any(s is not None and re.fullmatch(rx, s, re.S) for s in SITES[k]):
                unseen.append(f"{k} line {ln}: {''.join('{}' if p == WILD else p for p in skel)}")
    assert not unseen, f"a note shape with no sample in SITES: {unseen}"
    no_ru = [(k, s) for k, samples in SITES.items() for s in samples
             if s is not None and not S.note_ru(s)]
    assert not no_ru, f"a note shape without its Russian in score.NOTE_TEMPLATES: {no_ru}"
    # the agents may be checked out or not; the root's own sites always are
    stale = sorted(k for k in SITES if k not in found and (ROOT / k.split("::")[0]).is_file())
    assert not stale, f"SITES names a writer the code no longer has: {stale}"


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
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:600]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
