#!/usr/bin/env python3
"""CF-0432: the score model - a hard list that refuses, every other rule a
priced penalty with a cap and a hook multiplier, a start of 100, a threshold
N and tiers S-F, and a log of real penalties only.

The checks are about the arithmetic the grill of 2026-09-29 decided, and about
the committed price table standing as a usable model: it is read by every
agent, so a table the module cannot load is a red here, not a crash in a run.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "score"))
sys.path.insert(0, str(ROOT))

import score as S   # noqa: E402

from _tmproot import tmp_root   # noqa: E402
from _pinned_prices import pinned_table as pinned, pinned_ledger_file   # noqa: E402

TMP = tmp_root("score-model-test-")


def model(**over):
    d = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    for k, v in over.items():
        d["score"][k] = v
    return d


# The checks of the arithmetic (tiers, the hook multiplier, the CLI, the
# judge's line, the stages) run on the model as it stood before 2026-10-01
# (tests/_pinned_prices.py: N 60, neutral 1 per block, cap 8), so a price the
# user changes later (CF-0462: neutral 0, N 40) moves only the checks of the
# live table, not the mechanics.
def pinned_model(**over):
    return S.load_model(pinned(**over))


def test_the_committed_table_loads_with_the_whole_hard_list_and_the_grill_tiers():
    """The live signed table. 2026-10-01 (CF-0462) the user moved N 60 -> 40
    and E with it (the lowest passing tier starts at N): «judge_neutral = 0,
    N = 40»; the threshold carries its own signature beside the table's."""
    m = S.load_model()
    assert m["start"] == 100 and m["threshold"] == 40, m
    assert dict(m["tiers"]) == {"S": 92, "A": 85, "B": 78, "C": 71, "D": 65, "E": 40}
    thr_sig = model()["score"]["threshold_signature"]
    assert thr_sig["user"] == "Example Reviewer" and thr_sig["date"] == "2026-10-01"
    assert thr_sig["threshold"] == m["threshold"] and thr_sig["tiers"] == dict(m["tiers"])
    assert "judge_neutral = 0, N = 40" in thr_sig["note"]
    neutral = m["rules"]["score.judge_neutral"]
    assert (neutral["mode"], neutral["price"], neutral["cap"]) == (S.PENALTY, 0, 0), neutral
    for h in S.HARD_RULES:
        assert m["rules"][h]["mode"] == S.HARD, h
    pen = [n for n, r in m["rules"].items() if r["mode"] == S.PENALTY]
    assert len(pen) >= 19, pen
    assert m["status"] == S.STATUS_SIGNED
    assert m["signature"] == {"user": "Example Reviewer", "date": "2026-09-30",
                              "note": "таблица цен модели очков подписана как есть, 2026-09-30"}


# Rows whose price the user changed after signing the table: the row's
# signature is rewritten to the new price, same date, with the user's words.
CHANGED_AFTER_SIGNING = {
    "score.stretched_still_share": "цена изменена пользователем после калибровки: "
                                   "−0,5 за п.п., потолок −20 (paper-dragon был 57,6 F при −1/п.п.)",
}

# Rows the user signed one by one after the table, in the chat, each with the
# date and the words of the decision (CF-0320).
SIGNED_AFTER_TABLE = {
    "score.hard.screen_recording": ("2026-10-01", "да, шоты с экранкой отклонить"),
    "score.judge_neutral": ("2026-10-01", "judge_neutral = 0, N = 40"),
    "score.held_soft_frame": ("2026-10-01", "согласен с рекомендациями"),
    "score.frozen_block": ("2026-10-01", "«подписываю»"),
    "score.repeated_shot": ("2026-10-01", "«подписываю»"),
    "score.crop_cuts_subject": ("2026-10-01", "«подписываю»"),
    "score.held_moving_face": ("2026-10-02", "«Согласен со всеми»"),
    "score.tail_over_band_top": ("2026-10-02", "«Согласен со всеми»"),
    "score.held_one_source": ("2026-10-02", "«Согласен со всеми»"),
    # CF-0583: CF-0547's proposal, signed the day it was offered
    "score.fact_anchor_early": ("2026-10-06", "«цену за кадр раньше слов подтверждаю»"),
    # CF-0493: the boundary of the row, not its price (-4 a case, cap 12, as of 30.09)
    "score.panel_partly_cut": ("2026-10-03", "«Да, 27,5%, до релиза»"),
    # CF-0646: the Editor's held-screen rows, signed the day they were offered
    "score.thin_picture": ("2026-10-09", "«да ок на оба»"),
    "score.held_cut_subject": ("2026-10-09", "«да ок на оба»"),
    "score.held_soft_stretch": ("2026-10-09", "«да ок на оба»"),
    # CF-0646: the frame judge's thin strip / cut people / soap refuse the video
    "score.hard.footage_defect": ("2026-10-09", "«да ок на оба»"),
    # CF-0877: the frame judge's person mismatch, signed the day it was offered
    "score.judge_wrong_person": ("2026-10-27", "«да, подписываю»"),
    # CF-0878: the strip on its blurred ground over the video, signed the same day
    "score.narrow_strip_on_blur": ("2026-10-27", "«да, подписываю.»"),
}


def test_the_user_signed_every_row_of_the_table_as_it_stands():
    """2026-09-30: the user signed the price table of the score model as is -
    every `score.*` row, the drafts (meme captions, the presentations) and the
    rows of CF-0418 / CF-0447 too. A row's signature names the mode and, for a
    penalty, the price, the unit, the cap and the hook multiplier it covers."""
    d = model()
    rows = {n: r for n, r in d["rules"].items() if n.startswith("score.")}
    assert "score.stretched_still_share" in rows and "score.block_band_exceeded" in rows
    for name, row in rows.items():
        sig = row["signature"]
        assert sig["mode"] == row["mode"], name
        if name in SIGNED_AFTER_TABLE:
            date, words = SIGNED_AFTER_TABLE[name]
            assert sig["user"] == "Example Reviewer" and sig["date"] == date, name
            assert words in sig["note"], name
        else:
            assert sig["user"] == "Example Reviewer" and sig["date"] == "2026-09-30", name
            assert (CHANGED_AFTER_SIGNING.get(name) or
                    "таблица цен модели очков подписана как есть, 2026-09-30") in sig["note"], name
        if row["mode"] == S.PENALTY:
            pen = row["penalty"]
            assert (sig["price"], sig["per"], sig["cap"], sig["hook_mult"]) == (
                pen["price"], pen["per"], pen["cap"], pen["hook_mult"]), name


def test_a_status_the_model_does_not_know_or_a_signed_status_with_no_signature_is_refused():
    for over in ({"status": "approved"}, {"status": "signed", "signature": None},
                 {"status": "signed", "signature": {"user": "u"}}):
        try:
            S.load_model(model(**over))
        except S.ScoreModelError:
            continue
        raise AssertionError(f"loaded a table with {over}")
    m = pinned_model(status="draft", signature=None)
    assert m["status"] == S.STATUS_DRAFT and m["signature"] is None
    # the status changes nothing in the arithmetic
    f = [S.finding("score.judge_neutral", {"block": 0})]
    assert S.score(f, m)["score"] == S.score(f, pinned_model())["score"] == 99


def test_a_clean_video_is_100_and_s():
    r = S.score([], S.load_model())
    assert r["score"] == 100 and r["tier"] == "S" and r["passed"] and r["log"] == []


def test_tiers_follow_the_floors_and_f_is_below_n():
    m = pinned_model()
    for pts, tier in [(92, "S"), (91, "A"), (85, "A"), (78, "B"), (71, "C"), (65, "D"),
                      (60, "E"), (59, "F"), (0, "F")]:
        assert S.tier_of(pts, m) == tier, (pts, tier)
    # the live table: E from N = 40 (2026-10-01, CF-0462)
    live = S.load_model()
    assert [S.tier_of(p, live) for p in (65, 64, 40, 39)] == ["D", "E", "E", "F"]


def test_the_hook_multiplier_applies_only_in_the_hook_and_only_where_the_rule_has_one():
    m = pinned_model()
    r = S.score([S.finding("score.frozen_block", {"block": 0}, hook=True),
                 S.finding("score.frozen_block", {"block": 5})], m)
    assert [e["price"] for e in r["log"]] == [-40, -20] and r["score"] == 40, r
    r = S.score([S.finding("score.judge_neutral", {"block": 0}, hook=True)], m)
    assert r["log"][0]["price"] == -1 and not r["log"][0]["hook"], r


def test_a_cap_stops_a_rule_and_the_log_still_sums_to_the_score():
    m = S.load_model()
    fs = [S.finding("score.judge_contradicts", {"block": i}) for i in range(5)]
    r = S.score(fs, m)
    assert [e["price"] for e in r["log"]] == [-10, -10, -10, 0, 0], r["log"]
    assert r["log"][3]["capped"] and r["by_rule"]["score.judge_contradicts"] == {
        "raw": -50, "charged": -30, "cap": 30}
    assert r["score"] == 70 == r["start"] + sum(e["price"] for e in r["log"])


def test_a_partial_step_under_the_cap_is_charged_up_to_it():
    m = S.load_model()
    rule = m["rules"]["score.speech_without_picture"]
    units = rule["cap"] / rule["price"] + 0.5          # half a unit over the cap
    r = S.score([S.finding("score.speech_without_picture", {"t": 40}, units=units)], m)
    assert r["log"][0]["price"] == -rule["cap"] and r["log"][0]["capped"], r


def test_a_hard_rule_refuses_whatever_the_points():
    m = S.load_model()
    r = S.score(S.duration_findings(62.0), m)
    assert r["tier"] == "F" and not r["passed"] and r["score"] == 100, r
    assert r["hard"][0]["rule"] == "score.hard.duration_out_of_range"


def test_a_forecast_never_enters_the_score():
    m = S.load_model()
    r = S.score([S.finding("score.frozen_block", {"block": 1}, source="forecast"),
                 S.finding("score.hard.still_share_over_half", source="forecast")], m)
    assert r["score"] == 100 and r["passed"] and r["forecast_ignored"] == 2 and not r["hard"], r


def test_an_unknown_rule_is_an_error_and_not_a_free_pass():
    try:
        S.score([S.finding("score.nobody_priced_this")], S.load_model())
    except S.ScoreModelError:
        return
    raise AssertionError("an unpriced rule scored nothing silently")


def test_duration_and_still_share_split_between_the_hard_list_and_the_penalty():
    assert S.duration_findings(29.9)[0]["rule"] == "score.hard.duration_out_of_range"
    assert S.duration_findings(45.0) == [] and S.duration_findings(50) == []
    f = S.duration_findings(38.0)[0]
    assert f["rule"] == "score.short_length" and f["units"] == 3, f
    assert S.still_share_findings(0.51)[0]["rule"] == "score.hard.still_share_over_half"
    assert S.still_share_findings(0.50)[0]["units"] == 25.0
    assert S.still_share_findings(0.25) == [] and S.still_share_findings(0.1) == []


def test_the_stretched_share_is_a_capped_penalty_over_half_and_never_a_refusal():
    """CF-0418, the user 2026-09-30: pictures + stretched held frames over 50 %
    cost a penalty per p.p. over it, never a refusal. The signed price was 1 per
    p.p., cap 40; the user changed it after the calibration the same day to 0.5
    per p.p., cap 20 - kaijura v3 (88.1 %) pays 19.05."""
    m = S.load_model()
    rule = m["rules"]["score.stretched_still_share"]
    assert rule["mode"] == S.PENALTY and rule["price"] == 0.5 and rule["cap"] == 20, rule
    assert S.stretched_still_findings(0.5) == [] and S.stretched_still_findings(None) == []
    f = S.stretched_still_findings(0.8809)
    assert f[0]["rule"] == "score.stretched_still_share" and f[0]["units"] == 38.1, f
    r = S.score(f, m)
    assert r["score"] == 80.95 and not r["hard"], r
    r = S.score(S.stretched_still_findings(0.99), m)
    assert r["score"] == 80 and r["log"][0]["capped"], r
    assert S.LABELS["stretched_still_share"] == "растянутые кадры"


def test_blocks_over_the_top_of_the_band_are_a_capped_penalty_and_never_a_refusal():
    """CF-0447, the user 2026-09-30: more blocks than the top of the pattern's
    band costs 2 per block over it, capped at 10 - primetime (25 at 12-24)
    pays 2, Famine Trials (42 at 12-24) pays the cap."""
    m = S.load_model()
    rule = m["rules"]["score.block_band_exceeded"]
    assert rule["mode"] == S.PENALTY and rule["price"] == 2 and rule["cap"] == 10, rule
    assert rule["per"] == "block" and rule["hook_mult"] is None, rule
    r = S.score([S.finding("score.block_band_exceeded", {"blocks": 25}, units=1)], m)
    assert r["score"] == 98 and not r["hard"] and r["passed"], r
    r = S.score([S.finding("score.block_band_exceeded", {"blocks": 42}, units=18)], m)
    assert r["score"] == 90 and r["log"][0]["capped"], r
    assert S.LABELS["block_band_exceeded"] == "лишние блоки"
    line = S.summary_line(S.score([S.finding("score.block_band_exceeded", {"block": 24})], m), m)
    assert "−2 лишние блоки (1 блок)" in line, line


def test_a_table_that_drops_a_hard_rule_or_breaks_f_below_n_is_refused_on_load():
    d = model()
    del d["rules"]["score.hard.sound_broken"]
    for bad in (d, model(tiers={"S": 92, "E": 50})):
        try:
            S.load_model(bad)
        except S.ScoreModelError:
            continue
        raise AssertionError("a broken price table loaded")


def test_the_log_renders_as_a_table_a_summary_can_paste():
    r = S.score([S.finding("score.repeated_shot", {"shot": 2, "t": 1.5}, hook=True)],
                S.load_model(pinned()))
    lines = S.render(r, "wolfhame")
    assert lines[0] == "**wolfhame**: 90 / 100 - A", lines
    assert any("`score.repeated_shot` | shot 2, t 1.5 | -10 (hook)" in l for l in lines), lines


def test_the_cli_exits_zero_on_a_pass_and_one_below_n():
    p, ledger = TMP / "f.json", pinned_ledger_file(TMP)
    p.write_text(json.dumps([S.finding("score.frozen_block", {"block": 3})]))
    assert S.main([str(p), "--ledger", str(ledger)]) == 0
    p.write_text(json.dumps([S.finding("score.frozen_block", {"block": i}) for i in range(3)]))
    assert S.main([str(p), "--ledger", str(ledger)]) == 1


def test_the_package_import_and_the_path_import_are_one_module():
    from shared.score import score as via_package
    assert via_package.HARD_RULES == S.HARD_RULES


# ---------------------------------------------------------------- CF-0434

def test_the_line_is_the_task_example_counts_by_unit_and_judge_as_one_item():
    m = S.load_model()
    fs = ([S.finding("score.low_similarity", {"block": i}) for i in range(3)]
          + [S.finding("score.pace_below_floor", {}, units=3)]
          + [S.finding("score.low_framing", {"shot": j}) for j in range(2)]
          + [S.finding("score.judge_contradicts", {"block": 4})])
    r = S.score(fs, m)
    line = S.summary_line(r, m)
    assert line == (f"{r['tier']} · {r['score']} — −9 похожесть (3 блока), −6 темп, "
                    f"−6 кадрирование (2 шота), −10 судья: 1 contradicts"), line
    assert r["score"] == 69 and line.startswith("D · 69 — "), line


def test_the_line_merges_the_three_judge_rules_and_leaves_zero_prices_out():
    m = pinned_model()
    r = S.score([S.finding("score.judge_contradicts", {"block": 1}),
                 S.finding("score.judge_neutral", {"block": 2}),
                 S.finding("score.judge_neutral", {"block": 3}),
                 S.finding("score.judge_foreign", {"block": 5}),
                 S.finding("score.card_over_face", {"block": 4})], m)
    line = S.summary_line(r, m)
    assert line.endswith("— −24 судья: 1 contradicts, 2 neutral, 1 foreign"), line
    assert "карточка" not in line
    # live table (2026-10-01, CF-0462): neutral costs 0 but stays in the judge's
    # count - the rule is kept in the log as information
    live = S.load_model()
    r = S.score([S.finding("score.judge_contradicts", {"block": 1}),
                 S.finding("score.judge_neutral", {"block": 2}),
                 S.finding("score.judge_neutral", {"block": 3}),
                 S.finding("score.judge_foreign", {"block": 5})], live)
    assert S.summary_line(r, live).endswith("— −22 судья: 1 contradicts, 2 neutral, 1 foreign")


def test_the_line_opens_with_the_hard_list_and_says_so_when_clean_or_unscored():
    m = S.load_model()
    r = S.score([S.finding("score.hard.render_defect", {}),
                 S.finding("score.no_lofi_bed", {})], m)
    assert S.summary_line(r, m) == "F · 97 — жёсткий: брак рендера; −3 нет подложки"
    assert S.summary_line(S.score([], m), m) == "S · 100 — без штрафов"
    assert S.summary_line({"score": None, "error": "no model"}) == "очки не посчитаны: no model"
    assert S.summary_line(None) == "очки не посчитаны: нет лога"


def test_the_line_counts_seconds_hooks_and_russian_plurals():
    m = S.load_model(pinned())
    r = S.score([S.finding("score.speech_without_picture", {"t": 40}, units=2.5),
                 S.finding("score.frozen_block", {"block": 0, "t": 1}, hook=True)], m)
    line = S.summary_line(r, m)
    assert "−7,5 речь без кадра (2,5 с)" in line and "−40 зависший кадр (1 блок, хук)" in line, line
    assert [S.plural(n, S.NOUNS["block"]) for n in (1, 2, 5, 11, 12, 21, 22, 25)] == [
        "блок", "блока", "блоков", "блоков", "блоков", "блок", "блока", "блоков"]



# ---------------------------------------------------------------- CF-0455

def test_the_count_in_brackets_is_the_units_charged_not_the_log_rows():
    """Replay 2026-09-30T1248Z, AHS/day-drinker: one `block_band_exceeded`
    row carried 4 blocks over the band and the line read `−8 лишние блоки
    (1 блок)`. The count is the sum of `units`; the other rules that put more
    than one unit on one row either print their own unit (seconds) or no count
    at all - never a count of rows."""
    m = S.load_model()
    line = S.summary_line(S.score([S.finding("score.block_band_exceeded", {"blocks": 28},
                                             units=4)], m), m)
    assert "−8 лишние блоки (4 блока)" in line, line
    # capped: the count stays the real one, the points stop at the cap
    line = S.summary_line(S.score([S.finding("score.block_band_exceeded", {"blocks": 42},
                                             units=18)], m), m)
    assert "−10 лишние блоки (18 блоков)" in line, line
    # rows and units add up across rows of one rule
    r = S.score([S.finding("score.low_framing", {"shot": 1}, units=2),
                 S.finding("score.low_framing", {"shot": 2})], m)
    assert "−9 кадрирование (3 шота)" in S.summary_line(r, m)
    # the rest of the multi-unit rules: no row count leaks into the brackets
    r = S.score([S.finding("score.pace_below_floor", {}, units=3),
                 S.finding("score.speech_without_picture", {"t": 40}, units=4),
                 S.finding("score.stretched_still_share", {}, units=10)], m)
    line = S.summary_line(r, m)
    assert "−6 темп" in line and "темп (" not in line, line
    assert "речь без кадра (4 с)" in line, line
    assert S.LABELS["stretched_still_share"] in line, line
    assert f"{S.LABELS['stretched_still_share']} (" not in line, line
    assert "(1 " not in line, line

def test_the_stages_block_charges_each_stage_and_names_where_it_fell_under_n():
    m = pinned_model()
    stages = [
        {"stage": "judge", "findings": [S.finding("score.judge_contradicts", {"block": i})
                                        for i in range(3)]},
        {"stage": "plan", "findings": [S.finding("score.low_similarity", {"block": 0})]},
        {"stage": "qc", "findings": [S.finding("score.frozen_block", {"block": 2})]},
    ]
    b = S.stages_block(stages, m)
    assert [s["stage"] for s in b["stages"]] == ["plan", "qc", "judge"]
    assert [s["charged"] for s in b["stages"]] == [-3, -20, -30]
    assert [s["score_after"] for s in b["stages"]] == [97, 77, 47]
    assert b["score"] == 47 and b["tier"] == "F" and b["stopped_at"] == "judge"
    assert S.stops(b) and not S.stops(S.stages_block(stages[1:], m))
    assert S.stages_block([], m)["score"] == 100 and S.stages_block([], m)["stopped_at"] is None
    assert not S.stops({"score": None, "threshold": 60})


def test_the_log_path_sits_beside_the_plan():
    assert S.log_path(TMP / "work" / "x" / "plan.json") == TMP / "work" / "x" / "plan.score.json"
    assert S.read_log(TMP / "nowhere" / "plan.json") is None


def test_every_rule_the_score_can_charge_has_a_russian_label():
    """CF-0749: the command center showed «−16,9 thin_picture» - the three
    CF-0646 rules came into the ledger without a label. Every `score.*` rule
    of the ledger (signed or proposed) has its label in `LABELS`, every hard
    one (and the grill's `HARD_RULES`) in `HARD_LABELS`; the judge's three go
    as one `судья:` item and need none."""
    d = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    codes = set(d["rules"]) | set(k for k in (d.get("proposals") or {})
                                  if isinstance(k, str) and "." in k)
    codes |= set(S.HARD_RULES)
    missing = []
    for code in sorted(codes):
        if not code.startswith("score."):
            continue
        short = code.split(".", 1)[1]
        if short.startswith("hard."):
            if short.rsplit(".", 1)[-1] not in S.HARD_LABELS:
                missing.append(code)
        elif not short.startswith(S.JUDGE_PREFIX) and short not in S.LABELS:
            missing.append(code)
    assert not missing, f"no Russian label: {missing}"
    assert all(v.strip() and not v.isascii() for v in S.LABELS.values())
    assert all(v.strip() and not v.isascii() for v in S.HARD_LABELS.values())
    log = [{"rule": "score.thin_picture", "price": -16.9, "units": 5.03}]
    line = S.summary_line({"score": 83.1, "tier": "B", "log": log, "hard": []})
    assert "тонкая картинка" in line and "thin_picture" not in line, line


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
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
