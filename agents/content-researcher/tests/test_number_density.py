#!/usr/bin/env python3
"""CF-0542: the figures the narrator says - `number_density.py` (the stick)
and `check_number_density.py` (step 6's check, `measure` until the user signs).

Pinned here:

* what is one figure: a spelled amount is one figure however many words it
  takes, a month joins its day / year, `$`/`percent`/`dollars` join their
  number, digits and words count the same;
* what is not: small cardinals up to ten and ordinals outside a date;
* sentences split at . ! ? ; : before a space, "2.799" stays whole;
* the Endgame 0701Z commentary sentence reads 3 figures, the same fact
  rewritten by the rule ("almost three billion", the difference) reads 1;
* the check in `measure` warns and exits 0, `--write` records the reading on
  every script and a `numbers_heavy` warning, and drops it on a rerun once the
  script is within; `enforce` exits 1 (a rewrite, never a drop); `off`
  measures nothing; the channel's block overrides the defaults; a channel
  with no file runs on the defaults;
* `history` reads accepted rows of `publish/acceptance-log.json` to their
  `03` and `price` counts what a threshold flags.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import number_density as nd  # noqa: E402
import check_number_density as cnd  # noqa: E402

_TMP = tmp_root("cr-number-density-")
CHANNEL = "testchan"

ENDGAME = ("First, the new numbers: Endgame reclaims the number one spot on the "
           "all-time global chart, two billion nine hundred twenty five point five "
           "million to Avatar's two billion nine hundred twenty three point seven, "
           "a gap under two million.")
ROUNDED = ("Endgame is back on top of the all-time chart, less than two million "
           "dollars ahead of Avatar.")


def kinds(text):
    heavy, small = nd.figures_in(text)
    return [(f["text"], f["kind"]) for f in heavy], [f["text"] for f in small]


def test_a_spelled_amount_is_one_figure():
    heavy, _ = kinds("It made two billion nine hundred twenty five point five million worldwide.")
    assert heavy == [("two billion nine hundred twenty five point five million", "amount")], heavy


def test_digits_and_words_count_the_same():
    a = nd.measure_text("The budget was $160 million.")
    b = nd.measure_text("The budget was one hundred sixty million dollars.")
    assert a["figures"] == b["figures"] == 1, (a, b)
    assert a["figure_list"][0]["kind"] == b["figure_list"][0]["kind"] == "money"


def test_dates_years_percent_money():
    heavy, _ = kinds("Announced in October 2014, out December eighteenth, 50% of fans, "
                     "fifty percent of critics, $8 million domestic, back in 2007.")
    got = dict((t, k) for t, k in heavy)
    assert got == {"October 2014": "date", "December eighteenth": "date", "50%": "percent",
                   "fifty percent": "percent", "$8 million": "money", "2007": "year"}, got


def test_small_cardinals_and_ordinals_are_not_figures():
    heavy, small = kinds("First, one question: two segments, the third time, a two-part sequel.")
    assert heavy == [], heavy
    assert len(small) == 5, small
    heavy, small = kinds("The lowest opening in nineteen years and a hundred-year-old novel.")
    assert [t for t, _ in heavy] == ["nineteen", "a hundred"], heavy


def test_may_the_verb_is_not_a_month():
    heavy, _ = kinds("Fans may 2 times rewatch it.")
    assert heavy == [], heavy
    heavy, _ = kinds("It opened on May 3.")
    assert heavy == [("May 3", "date")], heavy


def test_sentences_split_before_a_space_only():
    assert nd.sentences("It made $2.799 billion. Then 2.5 more: yes; no! Why?") == [
        "It made $2.799 billion.", "Then 2.5 more:", "yes;", "no!", "Why?"]


def test_endgame_sentence_and_its_rewrite():
    m = nd.measure_text(ENDGAME)
    assert m["figures"] == 3 and m["max_per_sentence"] == 3 and m["max_run"] == 3, m
    assert m["heavy_sentences"][0]["figures"][2] == "two million"
    r = nd.measure_text(ROUNDED)
    assert r["figures"] == 1 and r["max_per_sentence"] == 1, r


def test_run_counts_figures_close_together():
    m = nd.measure_text("In 2019 and 2021, and long after that the studio said nothing "
                        "until 2024.")
    assert m["max_per_sentence"] == 3 and m["max_run"] == 2, m


def test_script_reads_the_three_visible_fields_only():
    s = {"hook": "Back in 2014.", "commentary": "It made $2 billion.", "payoff": "In 2019.",
         "fact": "1999 2000 2001", "scene_direction": "at 00:12"}
    m = nd.measure_script(s)
    assert m["figures"] == 3 and [f["field"] for f in m["figure_list"]] == list(nd.FIELDS), m


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def make_root(block=None, channel_file=True):
    root = Path(tempfile.mkdtemp(dir=_TMP))
    (root / "channels").mkdir()
    (root / "pipeline" / CHANNEL).mkdir(parents=True)
    if channel_file:
        cr = {"plan_check_rounds": 3}
        if block is not None:
            cr["number_density"] = block
        (root / "channels" / f"{CHANNEL}.json").write_text(json.dumps(
            {"channel_id": CHANNEL, "content_researcher": cr}))
    return root


def write_03(root, scripts, batch_id="2026-10-06T1000Z", warnings=None):
    d = root / "pipeline" / CHANNEL / batch_id
    d.mkdir(parents=True, exist_ok=True)
    f = d / "03-content-researcher.json"
    f.write_text(json.dumps({"batch_id": batch_id, "channel": CHANNEL,
                             "warnings": warnings or [], "scripts": scripts}))
    return f


# a narration of the real length (150-180 words): the density is per 10 words
FILLER = " ".join(["The cast kept the scene quiet and the crew kept rolling."] * 12)


def script(i, commentary):
    return {"script_id": f"t{i}-script1", "topic_id": f"t{i}", "hook": "A hook.",
            "commentary": f"{commentary} {FILLER}", "payoff": "A payoff."}


def run(root, f, *extra):
    lines = []
    rc = cnd.main([str(f), *extra], root=root, out=lines.append)
    return rc, "\n".join(lines)


def test_measure_warns_and_exits_zero():
    root = make_root()
    f = write_03(root, [script(1, ENDGAME), script(2, ROUNDED)])
    before = f.read_text()
    rc, out = run(root, f)
    assert rc == 0, out
    assert "WARN t1-script1" in out and "ok   t2-script1" in out, out
    assert "`measure` (defaults" in out and "not recorded" in out, out
    assert f.read_text() == before


def test_write_records_reading_and_warning_then_clears_it():
    root = make_root()
    f = write_03(root, [script(1, ENDGAME), script(2, ROUNDED)],
                 warnings=[{"topic_id": "t9", "warning_code": "pool_too_thin",
                            "gate": "block_capacity"}])
    rc, out = run(root, f, "--write")
    assert rc == 0, out
    data = json.loads(f.read_text())
    s1, s2 = data["scripts"]
    assert s1["number_density"]["verdict"] == "warn" and s1["number_density"]["figures"] == 3
    assert s2["number_density"]["verdict"] == "ok"
    mine = [w for w in data["warnings"] if w.get("gate") == cnd.GATE]
    assert len(mine) == 1 and mine[0]["warning_code"] == "numbers_heavy" \
        and mine[0]["severity"] == "warn" and mine[0]["topic_id"] == "t1", mine
    assert mine[0]["decision"].startswith("CF-0542")
    assert any(w.get("gate") == "block_capacity" for w in data["warnings"])
    # the rewrite by the rule: the warning goes, the foreign one stays
    data["scripts"][0]["commentary"] = f"{ROUNDED} {FILLER}"
    f.write_text(json.dumps(data))
    rc, out = run(root, f, "--write")
    data = json.loads(f.read_text())
    assert not [w for w in data["warnings"] if w.get("gate") == cnd.GATE], data["warnings"]
    assert len(data["warnings"]) == 1


def test_enforce_is_a_rewrite_of_the_narration():
    root = make_root({"mode": "enforce"})
    f = write_03(root, [script(1, ENDGAME)])
    rc, out = run(root, f, "--write")
    assert rc == 1 and "REWRITE t1-script1" in out and "not the topic" in out, out
    data = json.loads(f.read_text())
    assert data["scripts"] and data["warnings"] == [], data


def test_off_measures_nothing():
    root = make_root({"mode": "off"})
    f = write_03(root, [script(1, ENDGAME)])
    rc, out = run(root, f, "--write")
    assert rc == 0 and "off - nothing measured" in out, out
    assert "number_density" not in json.loads(f.read_text())["scripts"][0]


def test_channel_thresholds_override_defaults():
    root = make_root({"max_figures_per_sentence": 3, "max_figures_per_10_words": 2})
    f = write_03(root, [script(1, ENDGAME)])
    rc, out = run(root, f)
    assert rc == 0 and "ok   t1-script1" in out and "(channel)" in out, out


def test_no_channel_file_runs_on_defaults():
    root = make_root(channel_file=False)
    f = write_03(root, [script(1, ENDGAME)])
    rc, out = run(root, f)
    assert rc == 0 and "WARN t1-script1" in out, out


def test_unknown_mode_falls_back_to_measure():
    cfg, _ = cnd.settings({"content_researcher": {"number_density": {"mode": "loud"}}})
    assert cfg["mode"] == "measure"


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------

def test_history_and_price():
    root = make_root()
    write_03(root, [script(1, ENDGAME), script(2, ROUNDED)], batch_id="2026-10-05T0701Z")
    (root / "publish").mkdir()
    rows = [{"entry_id": f"{CHANNEL}/2026-10-05T0701Z/v{i}", "slug": f"v{i}",
             "channel": CHANNEL, "batch_id": "2026-10-05T0701Z", "topic_id": f"t{i}",
             "verdict": v} for i, v in ((1, "accepted"), (2, "accepted"), (3, "accepted"),
                                         (4, "rejected"))]
    (root / "publish" / "acceptance-log.json").write_text(json.dumps({"acceptances": rows}))
    got = nd.history(root)
    assert len(got) == 3 and got[2].get("missing"), got
    assert got[0]["max_per_sentence"] == 3 and got[1]["max_per_sentence"] == 1
    flagged, measured = nd.price(got, max_per_sentence=1)
    assert len(measured) == 2 and [r["slug"] for r in flagged] == ["v1"]
    flagged, _ = nd.price(got, max_per_10_words=10)
    assert flagged == []
    assert len(nd.history(root, verdicts=None)) == 4


def test_skill_carries_the_rule_and_the_check():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    assert "| `check_number_density.py` (CF-0542" in skill and "`check-number-density`" in skill
    assert "**One figure to a sentence** (`CF-0542`" in skill
    for words in ("round", "the difference instead of the two sums", "a year only where",
                  "A difference needs **both** sums in its footing"):
        assert words in skill, words
    assert "scripts/check_number_density.py" in skill
    assert "**In `measure` a `WARN` is exit 0 and asks for nothing**" in skill
    assert "the number-density reading from step 6" in skill
    assert "`content_researcher.number_density`" in skill
    for k in cnd.DEFAULTS:
        assert k in skill, k


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
