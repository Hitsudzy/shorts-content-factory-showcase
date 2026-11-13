#!/usr/bin/env python3
"""CF-0566: a vendor's benchmark is said as the vendor's, and a leak only as
the report of the outlet that published it (grill «Каналы ИИ и Наука» Q17,
ExampleTech).

Two flags of a channel's fact-sources list, carried the way CF-0660 carries
`preprint` -> `needs_caveat`:

* `attributed_kinds` - shared/factrule/fact_rule.py gives a fact of such a
  kind `needs_attribution: true` (check and record, ranked after a fact that
  needs none); shared/factrule/claims.py refuses the script
  (`fact_without_attribution`) unless its narration or plate names the owner
  beside "according to", "says", "по данным" ...;
* `leaks_need_source: true` - every check carries it; claims.py refuses a
  sentence that tells a leak without naming who reported it
  (`leak_without_source`).

A channel whose list has neither (ExampleFilm, ExampleScience) is untouched:
no flag, no new violation. Stand-in lists and scripts only - no network, no
channel file read but ExampleTech's tracked list for the last case.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fact_rule = _load("fact_rule_for_owner_claims", ROOT / "shared" / "factrule" / "fact_rule.py")
claims = _load("claims_for_owner_claims", ROOT / "shared" / "factrule" / "claims.py")


def _sources(**extra):
    src = {
        "kinds": ["spec", "price", "benchmark", "other"],
        "tiers": {"1": [{"id": "vendor", "hosts": ["vendor.example"], "major_outlet": True}],
                  "2": [{"id": "press", "hosts": ["press.example"], "major_outlet": True}]},
        "do_not_take": [{"id": "social", "hosts": ["social.example"]}],
    }
    src.update(extra)
    return src


TECH = _sources(attributed_kinds=["benchmark"], leaks_need_source=True)


def _cand(kind="benchmark", url="https://vendor.example/news/model", **k):
    return {"text": "Model X scores 87.5% on the MMLU test, released March 2026.",
            "kind": kind, "source": "Vendor", "url": url, **k}


def test_the_list_validates_its_two_flags():
    assert fact_rule.validate_sources(TECH) == []
    assert any("attributed_kinds" in p for p in
               fact_rule.validate_sources(_sources(attributed_kinds=["rumour"])))
    assert any("attributed_kinds" in p for p in
               fact_rule.validate_sources(_sources(attributed_kinds="benchmark")))
    assert any("leaks_need_source" in p for p in
               fact_rule.validate_sources(_sources(leaks_need_source="yes")))


def test_a_benchmark_passes_flagged_and_ranks_after_an_unflagged_fact():
    check = fact_rule.check_candidate(_cand(), TECH)
    assert check["passes"] and check["needs_attribution"] is True
    assert check["leaks_need_source"] is True
    spec = fact_rule.check_candidate(_cand(kind="spec"), TECH)
    assert spec["passes"] and "needs_attribution" not in spec
    assert spec["leaks_need_source"] is True, "the channel's leak rule rides on every fact"
    ranked = fact_rule.check_candidates([_cand(), _cand(kind="spec")], TECH)
    assert [c["kind"] for c in ranked] == ["spec", "benchmark"]
    rec = fact_rule.fact_record(ranked[1])
    assert rec["needs_attribution"] is True and rec["leaks_need_source"] is True


def test_a_list_without_the_flags_changes_nothing():
    plain = _sources()
    for kind in ("benchmark", "spec"):
        check = fact_rule.check_candidate(_cand(kind=kind), plain)
        assert "needs_attribution" not in check and "leaks_need_source" not in check, check
        rec = fact_rule.fact_record({**_cand(kind=kind), "check": check})
        assert "needs_attribution" not in rec and "leaks_need_source" not in rec


def test_a_leak_is_never_the_fact():
    """A leak has no tier-1 original: the press retelling it without a primary
    fails, the social host where leakers post is banned."""
    leak = _cand(kind="spec", url="https://press.example/iphone-leak")
    assert fact_rule.check_candidate(leak, TECH)["failures"] == ["tier2_without_primary"]
    leak = _cand(kind="spec", url="https://social.example/leaker/1")
    assert fact_rule.check_candidate(leak, TECH)["failures"] == ["source_banned"]


def _script(hook, commentary="It ships in May.", plate="", **fact):
    rec = {"text": "x", "kind": "benchmark", "source": "Google DeepMind",
           "url": "https://vendor.example/x", **fact}
    return {"fact": rec, "hook": hook, "commentary": commentary, "payoff": "That is the news.",
            "production_fact": {"on_screen": plate}, "claims": []}


def _codes(script, extra=None):
    return claims.codes(claims.check_claims(script, extra_texts=extra))


def test_the_vendors_benchmark_is_said_as_the_vendors():
    flag = {"needs_attribution": True}
    bad = _script("Gemini scores 87.5% on MMLU.", **flag)
    assert _codes(bad) == ["fact_without_attribution"]
    v = claims.check_claims(bad)["violations"][0]
    assert v["fix"] and v["text_ru"]
    for good in ("According to Google DeepMind, Gemini scores 87.5% on MMLU.",
                 "Gemini scores 87.5% on MMLU, Google says.",
                 "DeepMind claims Gemini scores 87.5% on MMLU.",
                 "Gemini scores 87.5% on MMLU per Google.",
                 "По данным Google, Gemini набирает 87,5% на MMLU.",
                 "Google заявляет, что Gemini набирает 87,5%."):
        assert _codes(_script(good, **flag)) == [], good
    # the plate may carry it too
    assert _codes(_script("Gemini scores 87.5%.", plate="87.5% - according to Google", **flag)) == []
    # a name with no marker, or a marker with no name, is not it
    assert _codes(_script("Google's Gemini scores 87.5% on MMLU.", **flag)) == \
        ["fact_without_attribution"]
    assert _codes(_script("Gemini scores 87.5%, the report says.", **flag)) == \
        ["fact_without_attribution"]
    assert _codes(_script("Google's Gemini runs at 200 tokens per second.", **flag)) == \
        ["fact_without_attribution"], "a bare «per» is not «per Google»"
    # the title and the description are not the video
    assert _codes(_script("Gemini scores 87.5%.", **flag),
                  extra={"title": "According to Google, 87.5%", "description": ""}) == \
        ["fact_without_attribution"]
    assert _codes(_script("Gemini scores 87.5% on MMLU.")) == [], "no flag, no rule"


def test_a_leak_is_told_only_with_its_outlet():
    flag = {"leaks_need_source": True}
    for bad in ("Leaked renders show the iPhone 18.", "The specs leaked last week.",
                "The leak was reported last week.", "Слили характеристики iPhone 18.",
                "Утечка показала новый чип."):
        assert _codes(_script(bad, **flag)) == ["leak_without_source"], bad
    for good in ("According to The Verge, leaked renders show the iPhone 18.",
                 "As The Verge reported, the specs leaked last week.",
                 "The specs leaked, Bloomberg reports.",
                 "Leaked renders were first published by 9to5Mac, reported by The Verge.",
                 "По данным The Verge, утечка показала новый чип.",
                 "Как пишет Bloomberg, характеристики слили на прошлой неделе."):
        assert _codes(_script(good, **flag)) == [], good
    # the title and the description are viewer text: the rule reads them
    assert _codes(_script("It ships in May.", **flag),
                  extra={"title": "iPhone 18 specs leaked", "description": ""}) == \
        ["leak_without_source"]
    assert _codes(_script("Leaked renders show the iPhone 18.")) == [], "no flag, no rule"


def test_hearsay_is_refused_on_every_channel_already():
    """«Говорят, что Apple...», «Apple is said to» - CF-0552 Q3, unchanged."""
    for h in ("Говорят, что Apple готовит iPhone 18.", "Apple is said to ship it in May.",
              "Sources say Apple will ship it in May."):
        assert _codes(_script(h)) == ["hedged_statement"], h




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
    sys.exit(1 if failed else 0)
