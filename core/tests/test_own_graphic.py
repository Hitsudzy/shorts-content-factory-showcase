#!/usr/bin/env python3
"""CF-0689: the graphics the factory draws itself from the script's facts -
`shared/own_graphic.py` (the templates, the order, the values against the
claims, the text a template must not add, what the viewer reads), what
`shared/factrule/claims.py` gained for them (`where: graphic:<id>`,
`viewer_texts`), the `own_graphic` licence and origin of
`shared/footage_licence.py` and ExampleTech's footage-origin document, and
that the other channels are judged as before.

Stand-in scripts only; reads the tracked channel files as a contract
(docs/test-hygiene.md); no network, nothing written.
"""
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


og = _load("_own_graphic_t", ROOT / "shared" / "own_graphic.py")
cl = _load("_claims_og_t", ROOT / "shared" / "factrule" / "claims.py")
fl = _load("_footage_licence_og_t", ROOT / "shared" / "footage_licence.py")
cd = _load("_channel_data_og_t", ROOT / "shared" / "channel_data.py")

PIECE_TEXT = ("Google released Gemini 2.5 Pro on March 25, 2025. On SWE-bench Verified "
              "Gemini 2.5 Pro scores 63.8%, while OpenAI o3-mini scores 49.3%. "
              "The model costs $1.25 per million input tokens and has a context "
              "window of 1,000,000 tokens.")
TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"},
         "support_text": [{"id": "news:1", "kind": "rss_summary", "title": "Gemini 2.5",
                           "text": PIECE_TEXT}]}


def _q(quote):
    return [{"source": "news:1", "quote": quote}]


BENCH = {
    "graphic_id": "g1", "template": "benchmark",
    "data": {"metric": "SWE-bench Verified",
             "rows": [{"name": "Gemini 2.5 Pro", "score": "63.8%"},
                      {"name": "OpenAI o3-mini", "score": "49.3%"}]},
    "values": [
        {"path": "data.metric", "text": "SWE-bench Verified", "claim_ids": ["c1"]},
        {"path": "data.rows[0].name", "text": "Gemini 2.5 Pro", "claim_ids": ["c1"]},
        {"path": "data.rows[0].score", "text": "63.8%", "claim_ids": ["c1"]},
        {"path": "data.rows[1].name", "text": "OpenAI o3-mini", "claim_ids": ["c2"]},
        {"path": "data.rows[1].score", "text": "49.3%", "claim_ids": ["c2"]},
    ],
    "source_label": "Google",
}
CLAIMS = [
    {"claim_id": "c1", "text": "Gemini 2.5 Pro: 63.8%", "where": "graphic:g1",
     "support": _q("On SWE-bench Verified Gemini 2.5 Pro scores 63.8%")},
    {"claim_id": "c2", "text": "OpenAI o3-mini: 49.3%", "where": "graphic:g1",
     "support": _q("OpenAI o3-mini scores 49.3%")},
]
SCRIPT = {"script_id": "s1", "topic_id": "t1",
          "hook": "Google just put Gemini 2.5 Pro on top.",
          "commentary": "According to Google, it scores 63.8% on SWE-bench Verified.",
          "payoff": "That is the number to beat.",
          "graphics": [BENCH], "claims": CLAIMS}


def _bench():
    return copy.deepcopy(BENCH)


def _g(template, data, values, source_label=None, gid="g2"):
    return {"graphic_id": gid, "template": template, "data": data, "values": values,
            "source_label": source_label}


def _v(path, text, *ids):
    return {"path": path, "text": text, "claim_ids": list(ids)}


# ------------------------------------------------------------------ shape
def test_the_templates_and_their_caps():
    """The six of CF-0689 on claims, and CF-0690's `api_chat` on a call's record
    (tests/test_api_demo.py holds it)."""
    assert set(og.TEMPLATES) == {"spec_card", "comparison", "price_date", "benchmark",
                                 "timeline", "how_it_works", "api_chat"}
    assert [t for t, tpl in og.TEMPLATES.items() if tpl.get("on_record")] == ["api_chat"]
    for name, tpl in og.TEMPLATES.items():
        assert tpl["what"] and tpl["fields"], name
        for field, spec in tpl["fields"].items():
            assert spec["kind"] in og.FIELD_KINDS + (og.LIST,), (name, field)
            if spec["kind"] == og.LIST:
                assert 1 <= spec["min"] <= spec["max"] <= 5, (name, field)
    assert og.TEMPLATES["benchmark"]["needs_source_label"] is True
    assert set(og.FAIL_CODES) == set(og.FIXES) == set(og.REFUSALS_RU)
    assert og.FAIL_CODES == ("graphic_malformed", "graphic_unknown_template",
                             "graphic_value_unbacked", "graphic_value_not_in_footing",
                             "graphic_benchmark_unattributed", "graphic_adds_text")


def test_a_good_benchmark_stands():
    assert og.order_problems(BENCH) == [] and og.order_errors(BENCH) == []
    assert og.check_graphics(SCRIPT) == []
    assert og.check_graphics(SCRIPT, cl.support_pieces(TOPIC)) == []


def test_each_template_well_formed():
    cases = [
        _g("spec_card", {"product": "Pixel 10", "rows": [{"label": "Battery", "value": "4,970 mAh"}]},
           [_v("data.product", "Pixel 10", "c"), _v("data.rows[0].label", "Battery", "c"),
            _v("data.rows[0].value", "4,970 mAh", "c")]),
        _g("comparison", {"left": "iPhone 15", "right": "iPhone 16",
                          "rows": [{"label": "Price", "left": "$799", "right": "$829"},
                                   {"left": "A16", "right": "A18"}]},
           [_v(p, t, "c") for p, t in (("data.left", "iPhone 15"), ("data.right", "iPhone 16"),
                                       ("data.rows[0].label", "Price"),
                                       ("data.rows[0].left", "$799"),
                                       ("data.rows[0].right", "$829"),
                                       ("data.rows[1].left", "A16"),
                                       ("data.rows[1].right", "A18"))]),
        _g("price_date", {"product": "Vision Pro", "date": "February 2, 2024"},
           [_v("data.product", "Vision Pro", "c"), _v("data.date", "February 2, 2024", "c")]),
        _g("timeline", {"events": [{"date": "2023", "label": "GPT-4"},
                                   {"date": "May 2024", "label": "GPT-4o"}]},
           [_v(f"data.events[{i}].{k}", t, "c") for i, k, t in
            ((0, "date", "2023"), (0, "label", "GPT-4"), (1, "date", "May 2024"),
             (1, "label", "GPT-4o"))]),
        _g("how_it_works", {"steps": ["Prompt", "Model", "Image"]},
           [_v(f"data.steps[{i}]", t, "c") for i, t in enumerate(("Prompt", "Model", "Image"))]),
    ]
    for g in cases:
        assert og.order_problems(g) == [], (g["template"], og.order_errors(g))
        assert og.adds_text(g) == [], g["template"]


def test_a_broken_order_is_named():
    def codes_of(g):
        return og.codes(og.order_problems(g))
    bad = _bench()
    bad["template"] = "pie_chart"
    assert codes_of(bad) == ["graphic_unknown_template"]
    for mutate, part in (
        (lambda g: g.pop("values"), "missing ['values']"),
        (lambda g: g.update(extra=1), "unknown key(s) ['extra']"),
        (lambda g: g.update(graphic_id="G 1"), "graphic_id"),
        (lambda g: g["data"].update(logo="x"), "unknown field(s) ['logo']"),
        (lambda g: g["data"]["rows"].pop(), "holds 1 item(s), not 2..5"),
        (lambda g: g["data"]["rows"].extend([{"name": "X", "score": "1"}] * 4), "not 2..5"),
        (lambda g: g["data"].update(metric="A metric name far too long to read on a phone"),
         "not read on a phone"),
        (lambda g: g["data"]["rows"][0].update(score="high"), "holds no number"),
        (lambda g: g["data"]["rows"][0].update(score=63.8), "non-empty string"),
        (lambda g: g["values"][2].update(text="64%"), "is not the string at"),
        (lambda g: g["values"][2].update(path="data.rows[9].score"), "names no string"),
        (lambda g: g["values"].append(dict(g["values"][0])), "twice"),
        (lambda g: g["values"][0].pop("claim_ids"), "exactly {path, text, claim_ids}"),
    ):
        g = _bench()
        mutate(g)
        probs = og.order_problems(g)
        assert og.codes(probs)[:1] == ["graphic_malformed"], (part, probs)
        assert part in probs[0]["detail"], (part, probs[0]["detail"])
    pd = _g("price_date", {"product": "Vision Pro"}, [_v("data.product", "Vision Pro", "c")])
    assert "at least one of ['price', 'date']" in og.order_errors(pd)[0]
    assert og.order_errors("x")[0].startswith("graphic_malformed")


def test_a_benchmark_says_whose_numbers():
    g = _bench()
    g["source_label"] = None
    assert og.codes(og.order_problems(g)) == ["graphic_benchmark_unattributed"]
    g.pop("source_label")
    assert og.codes(og.order_problems(g)) == ["graphic_benchmark_unattributed"]
    assert og.caption(BENCH) == "According to Google"
    assert og.caption(BENCH, "ru") == "По данным Google"
    # any other template may go without one
    tl = _g("how_it_works", {"steps": ["Prompt", "Image"]},
            [_v("data.steps[0]", "Prompt", "c"), _v("data.steps[1]", "Image", "c")])
    assert og.order_problems(tl) == []


# ----------------------------------------------------------------- values
def test_values_backed_and_unbacked():
    g = _bench()
    g["values"][2]["claim_ids"] = []
    g["values"][3]["claim_ids"] = ["c9"]
    other = [dict(CLAIMS[0]), dict(CLAIMS[1], where="commentary")]
    probs = og.value_problems(g, other)
    assert [(p["code"], p["path"]) for p in probs] == [
        ("graphic_value_unbacked", "data.rows[0].score"),
        ("graphic_value_unbacked", "data.rows[1].name"),
        ("graphic_value_unbacked", "data.rows[1].score")]
    assert "not `where: graphic:g1`" in probs[2]["detail"]
    assert og.value_problems(BENCH, {c["claim_id"]: c for c in CLAIMS}) == []


def test_a_value_not_in_its_footing():
    g = _bench()
    g["data"]["rows"][0]["score"] = g["values"][2]["text"] = "68.3%"
    g["data"]["rows"][1]["name"] = g["values"][3]["text"] = "OpenAI o4"
    probs = og.value_problems(g, CLAIMS)
    assert [(p["code"], p["path"]) for p in probs] == [
        ("graphic_value_not_in_footing", "data.rows[0].score"),
        ("graphic_value_not_in_footing", "data.rows[1].name")]
    assert probs[0]["missing"] == ["68.3"]


def test_a_shot_or_a_quote_off_its_piece_backs_no_value():
    claims = copy.deepcopy(CLAIMS)
    claims[1]["support"] = [{"shot_id": "VID:1"}]
    assert og.codes(og.value_problems(BENCH, claims)) == ["graphic_value_not_in_footing"] * 2
    claims = copy.deepcopy(CLAIMS)
    claims[1]["support"] = _q("OpenAI o3-mini scores 49.3% on everything")   # not in the piece
    assert og.value_problems(BENCH, claims) == []
    pieces = cl.support_pieces(TOPIC)
    assert og.codes(og.value_problems(BENCH, claims, pieces)) == \
        ["graphic_value_not_in_footing"] * 2


def test_numbers_are_read_as_numbers():
    assert og.parse_numbers("1,000,000 tokens") == [("1000000", None)]
    assert og.parse_numbers("92,3 %") == [("92.3", None)]
    assert og.parse_numbers("63.80%") == [("63.8", None)]
    assert og.parse_numbers("1.234,5") == [("1234.5", None)]
    assert og.parse_numbers("1 000 users") == [("1000", None)]
    assert og.parse_numbers("€1 299") == [("1299", None)]
    assert og.parse_numbers("$1.5 billion") == [("1.5", "1500000000")]
    assert og.parse_numbers("128K tokens") == [("128", "128000")]
    assert og.parse_numbers("5 minutes") == [("5", None)]
    found = og.number_found
    assert found(og.parse_numbers("$1.5B")[0], og.parse_numbers("1,500,000,000 dollars"))
    assert found(og.parse_numbers("1.5")[0], og.parse_numbers("a $1.5 billion deal"))
    assert found(og.parse_numbers("1M")[0], og.parse_numbers("1,000,000 tokens"))
    assert not found(og.parse_numbers("1.5 million")[0], og.parse_numbers("1.5 billion"))
    assert not found(og.parse_numbers("63.9%")[0], og.parse_numbers("63.8 percent"))
    # a spec value with a comma decimal and a currency sign, backed by its quote
    spec = _g("spec_card", {"product": "Gemini 2.5 Pro",
                            "rows": [{"label": "Input price", "value": "$1,25 / 1M"},
                                     {"label": "Context", "value": "1M tokens"}]},
              [_v("data.product", "Gemini 2.5 Pro", "p"), _v("data.rows[0].label", "Input price", "p"),
               _v("data.rows[0].value", "$1,25 / 1M", "p"), _v("data.rows[1].label", "Context", "p"),
               _v("data.rows[1].value", "1M tokens", "p")])
    claim = {"claim_id": "p", "where": "graphic:g2", "text": "x", "support": _q(
        "Google released Gemini 2.5 Pro on March 25, 2025") + _q(
        "The model costs $1.25 per million input tokens and has a context window of "
        "1,000,000 tokens")}
    assert og.value_problems(spec, [claim]) == []


def test_dates_are_read_as_dates():
    assert og.parse_dates("March 25, 2025") == [(2025, 3, 25)]
    assert og.parse_dates("25 March 2025") == [(2025, 3, 25)]
    assert og.parse_dates("Mar. 2025") == [(2025, 3, None)]
    assert og.parse_dates("2025-03-25") == [(2025, 3, 25)]
    assert og.parse_dates("25 марта 2025 года") == [(2025, 3, 25)]
    assert og.parse_dates("the market in 2025") == [(2025, None, None)]
    found = og.date_found
    q = og.parse_dates("Google released Gemini 2.5 Pro on March 25, 2025.")
    for value in ("March 2025", "25 March", "2025", "Mar 25, 2025", "2025-03-25"):
        assert found(og.parse_dates(value)[0], q), value
    for value in ("April 2025", "March 26, 2025", "2024"):
        assert not found(og.parse_dates(value)[0], q), value
    tl = _g("timeline", {"events": [{"date": "Mar 2025", "label": "Gemini 2.5 Pro"},
                                    {"date": "Jan 2025", "label": "o3-mini"}]},
            [_v("data.events[0].date", "Mar 2025", "d"), _v("data.events[0].label", "Gemini 2.5 Pro", "d"),
             _v("data.events[1].date", "Jan 2025", "d"), _v("data.events[1].label", "o3-mini", "d")])
    claim = {"claim_id": "d", "where": "graphic:g2", "text": "x",
             "support": _q("Google released Gemini 2.5 Pro on March 25, 2025")}
    probs = og.value_problems(tl, [claim])
    assert [(p["code"], p["path"], p["missing"]) for p in probs] == [
        ("graphic_value_not_in_footing", "data.events[1].date", ["2025-1-?"])]


def test_names_are_compared_word_for_word():
    assert og.name_found("Gemini 2.5 Pro", "Google's Gemini 2.5 Pro scores")
    assert og.name_found("Google", "Google's new model")
    assert og.name_found("OpenAI o3-mini", "while OpenAI o3‑mini scores")
    assert not og.name_found("Gemini 2.5", "Gemini 2.0 Flash")
    assert not og.name_found("Gemini Pro", "Gemini 2.5 Pro")


def test_the_template_adds_no_text():
    g = _bench()
    dropped = g["values"].pop(0)
    assert og.adds_text(g) == [{"path": "data.metric", "text": "SWE-bench Verified"}]
    script = dict(SCRIPT, graphics=[g])
    assert og.codes(og.check_graphics(script)) == ["graphic_adds_text"]
    g["values"].insert(0, dropped)
    assert og.adds_text(g) == []


def test_check_graphics_over_a_script():
    assert og.check_graphics({"hook": "x"}) == []
    assert og.codes(og.check_graphics({"graphics": {}})) == ["graphic_malformed"]
    two = dict(SCRIPT, graphics=[_bench(), _bench()])
    assert og.codes(og.check_graphics(two)) == ["graphic_malformed"]
    broken = _bench()
    broken["template"] = "pie"
    broken["values"][0]["claim_ids"] = []
    # a graphic that is not well formed is not read further
    assert og.codes(og.check_graphics(dict(SCRIPT, graphics=[broken]))) == \
        ["graphic_unknown_template"]


# ------------------------------------------------------------ viewer text
def test_viewer_text():
    assert og.viewer_text(BENCH) == ("SWE-bench Verified\nGemini 2.5 Pro: 63.8%\n"
                                     "OpenAI o3-mini: 49.3%\nAccording to Google")
    cmp_ = _g("comparison", {"left": "iPhone 15", "right": "iPhone 16",
                             "rows": [{"label": "Price", "left": "$799", "right": "$829"},
                                      {"left": "A16", "right": "A18"}]}, [])
    assert og.viewer_text(cmp_) == "iPhone 15 | iPhone 16\nPrice: $799 | $829\nA16 | A18"
    hiw = _g("how_it_works", {"title": "Inside", "steps": ["Prompt", "Model"]}, [])
    assert og.viewer_text(hiw) == "Inside\nPrompt\nModel"
    pd = _g("price_date", {"product": "Vision Pro", "price": "$3,499"}, [], "Apple")
    assert og.viewer_text(pd) == "Vision Pro\n$3,499\nAccording to Apple"
    assert og.viewer_texts(SCRIPT) == {"graphic:g1": og.viewer_text(BENCH)}
    assert og.where_of("g1") == "graphic:g1" and og.graphic_id_of("graphic:g1") == "g1"
    assert og.graphic_id_of("hook") is None


# --------------------------------------------------------- the claim rule
def test_claims_read_a_graphic_like_any_viewer_text():
    texts = cl.viewer_texts(SCRIPT)
    assert texts["graphic:g1"] == og.viewer_text(BENCH)
    assert set(texts) == {"hook", "commentary", "payoff", "graphic:g1"}
    rep = cl.check_claims(SCRIPT, topic=TOPIC)
    assert rep["action"] == "pass", cl.render("s1", rep)
    assert cl.shape_problems(CLAIMS[0]) == []
    assert cl.is_graphic_where("graphic:g1") and not cl.is_graphic_where("graphic:")
    assert "graphic:<graphic_id>" in " ".join(cl.shape_problems(dict(CLAIMS[0], where="graphic")))
    # a claim on a graphic the script does not draw, or text the graphic does not show
    lost = dict(SCRIPT, claims=[dict(CLAIMS[0], where="graphic:g9"),
                                dict(CLAIMS[1], text="OpenAI o3-mini: 50%")])
    assert cl.codes(cl.check_claims(lost, topic=TOPIC)) == ["claim_text_not_in_field"] * 2
    # a shot backs only a spoken claim - never a graphic's
    shot = dict(SCRIPT, claims=[CLAIMS[0], dict(CLAIMS[1], support=[{"shot_id": "VID:1"}])])
    assert "shot_support_not_spoken" in cl.codes(cl.check_claims(shot, topic=TOPIC, pool={}))
    # hedged words on a graphic are hedged words
    hedged = copy.deepcopy(SCRIPT)
    hedged["graphics"][0]["data"]["metric"] = "Reportedly SWE-bench"
    assert "hedged_statement" in cl.codes(cl.check_claims(hedged, topic=TOPIC))


def test_a_graphic_is_not_the_attribution_nor_the_caveat():
    """A benchmark's source line does not stand in for the narrator's
    «according to X» (CF-0566), and WHERES / WHERE_ATTRIBUTION are what they
    were."""
    assert cl.WHERES == ("hook", "commentary", "payoff", "on_screen", "title", "description")
    assert cl.WHERE_ATTRIBUTION == ("hook", "commentary", "payoff", "on_screen")
    script = dict(SCRIPT, commentary="It scores 63.8% on SWE-bench Verified.",
                  fact={"needs_attribution": True, "source": "Google", "kind": "benchmark"})
    assert "fact_without_attribution" in cl.codes(cl.check_claims(script, topic=TOPIC))


def test_a_script_without_graphics_is_read_as_before():
    plain = {k: v for k, v in SCRIPT.items() if k != "graphics"}
    assert set(cl.viewer_texts(plain)) == {"hook", "commentary", "payoff"}
    assert set(cl.viewer_texts(dict(plain, graphics=[]))) == {"hook", "commentary", "payoff"}


# -------------------------------------------------------- licence, origin
def test_the_licence_and_the_origin():
    doc = cd.footage_origin("example-tech", ROOT)
    assert fl.footage_origin_errors(doc) == []
    assert fl.OWN_GRAPHIC == og.KIND == "own_graphic" and fl.DRAWN in fl.FOUND_BY
    got = fl.licence_of("own graphic", doc["licences"])
    assert got["accepted"] and got["id"] == "own_graphic" and got["attribution"] == "none"
    drawn = fl.origin(doc, "own_graphic")
    assert drawn["terms_url"] is None and drawn["found_by"][0]["how"] == "drawn"
    assert drawn["attribution"]["required"] is False and drawn["attribution"]["on_screen"] is False
    assert "video_editor" not in drawn


def test_a_broken_own_graphic_origin_is_named():
    doc = cd.footage_origin("example-tech", ROOT)
    bad = json.loads(json.dumps(doc))
    fl.origin(bad, "own_graphic")["terms_url"] = "https://example.com/terms"
    fl.origin(bad, "vendor_official")["found_by"].append({"how": "drawn", "works_now": True})
    errs = "\n".join(fl.footage_origin_errors(bad))
    assert "an `own_graphic` origin has no `terms_url`" in errs, errs
    assert "(vendor_official): found_by[1]: `drawn` is the way of the `own_graphic`" in errs, errs
    worse = json.loads(json.dumps(doc))
    fl.origin(worse, "own_graphic")["found_by"][0]["how"] = "screen_capture"
    assert "(own_graphic): found_by[0]: `drawn`" in "\n".join(fl.footage_origin_errors(worse))


def test_the_other_channels_are_judged_as_before():
    sci = cd.footage_origin("example-science", ROOT)
    assert fl.footage_origin_errors(sci) == []
    assert not fl.licence_of("own graphic", sci["licences"])["accepted"]
    for ch in ("example-film", "example-science"):
        doc = cd.footage_origin(ch, ROOT)
        assert fl.origin(doc, "own_graphic") is None, ch
        blob = json.dumps({k: doc.get(k) for k in ("licences", "footage_origins")})
        assert "own_graphic" not in blob and '"drawn"' not in blob, ch


if __name__ == "__main__":
    import traceback
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:                               # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
