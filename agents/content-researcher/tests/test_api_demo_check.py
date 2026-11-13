#!/usr/bin/env python3
"""CF-0690: "a demo via API" at the writer's stage.

ExampleTech may show the topic's own model's real answer to one approved
prompt, asked through the Gemini API by the Trend Hunter (the topic's
`api_demo_record`), drawn as the factory's own `api_chat` graphic labelled
"<display name> · via API". The answer is never our fact. Pinned here:

* `scripts/check_graphics.py` - a good chat passes; every chat code of the
  root (`own_graphic.CHAT_CODES`) comes through with its fix and Russian
  line; a chat on a channel that draws but has no `api_demo` origin is
  `api_demo_on_channel_without_origin`; Reel / Science as before;
* `scripts/check_claims.py` (`api_demo_footing`) - a sentence footed on the
  model's answer, a claim on the chat and a production fact footed on a
  `not_a_fact` piece are `api_demo_answer_is_fact`; the report of the demo
  ("we asked Gemini 2.5 Flash through the Gemini API") stands;
* `scripts/check_production_fact.py` - the record of the fact taken
  never names a `not_a_fact` piece;
* `scripts/check_demo.py` - a demo stands on a chat + record with no own
  capture; `demo_api_not_named` when the voice never names the model and
  "API"; every own-capture rule as before;
* SKILL.md explains the codes and the order.

Every batch is built in a temp directory from stand-ins
(`tests/_api_demo_stand_in.py`) - no pipeline, no key, no network, no model.
The root's rules and channel files are read as code.
"""
import copy
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489)
_TMP = tmp_root("cr-api-demo-")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import _api_demo_stand_in as sd  # noqa: E402
import check_graphics as cg  # noqa: E402
import _own_graphic as ogl  # noqa: E402
import check_narration_budget as cnb  # noqa: E402

ROOT = cnb.find_root()
OG = ogl.own_graphic(ROOT)
AD = OG.api_demo
SKILL = (REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()

TECH, REEL, SCIENCE = "example-tech", "example-film", "example-science"
HOOK = "Google's newest small model is out, and we asked it something."
COMMENTARY = ("We sent Gemini 2.5 Flash one question through the Gemini API. "
              "Here is its real answer, word for word.")
PAYOFF = "Fast, plain, and on the record."


def _script(**extra):
    s = {"script_id": "tech-001-script1", "topic_id": sd.TOPIC,
         "pattern": {"pattern_id": "explainer", "rhythm_id": "even"},
         "hook": HOOK, "commentary": COMMENTARY, "payoff": PAYOFF,
         "graphics": [sd.chat()], "claims": [],
         "visual_anchors": [{"anchor_id": "a1", "graphic_id": "g9",
                             "beat_text": "Here is its real answer, word for word."}]}
    s.update(extra)
    return s


def _bench(scripts, channel=TECH, topic=None, trend=True):
    d = Path(tempfile.mkdtemp(dir=_TMP))
    batch = d / "03-content-researcher.json"
    batch.write_text(json.dumps({"channel": channel, "scripts": scripts}))
    if trend:
        (d / "01-trend-hunter.json").write_text(json.dumps(
            {"topics": [topic if topic is not None else sd.topic()]}))
    return batch


def _run_graphics(batch):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cg.main([str(batch), "--root", str(ROOT)])
    return code, buf.getvalue()


def _graphic_codes(script, channel=TECH, topic=None, trend=True):
    batch = _bench([script], channel, topic, trend)
    res = cg.check_batch(batch, root=ROOT, out=lambda *_: None)
    return [p["code"] for p in res.get(script["script_id"], [])]


# --------------------------------------------------------------------------
# the stand-ins are what the root accepts
# --------------------------------------------------------------------------

def test_the_stand_in_protocol_is_a_protocol_and_its_chat_is_exact():
    assert AD.protocol_problems(sd.protocol()) == []
    assert AD.display_name_for(sd.MODEL_VERSION, sd.CONFIG) == sd.DISPLAY
    assert sd.chat()["data"]["answer"] == AD.shown_answer(sd.ANSWER, sd.CONFIG["max_answer_chars"])
    assert sd.chat()["data"]["model_label"] == AD.model_label(sd.DISPLAY)
    assert AD.protocols_by_record(sd.record()) == {sd.RECORD_ID: sd.protocol()}


def test_tech_has_the_api_demo_origin_and_reel_science_have_not():
    has, block = ogl.channel_api_demo(TECH, ROOT)
    assert has is True and isinstance(block, dict) and block.get("models")
    for ch in (REEL, SCIENCE, "no-such-channel"):
        assert ogl.channel_api_demo(ch, ROOT) == (False, None), ch


# --------------------------------------------------------------------------
# check_graphics.py
# --------------------------------------------------------------------------

def test_a_good_chat_passes():
    code, out = _run_graphics(_bench([_script()]))
    assert code == cg.EXIT_OK, out
    assert "api_chat(s) held to the topics' api_demo_record" in out


def test_a_chat_with_no_record_on_the_topic():
    assert _graphic_codes(_script(), topic=sd.topic(with_record=False)) == [AD.FAIL_NO_RECORD]
    # no 01 read - no record either
    assert _graphic_codes(_script(), trend=False) == [AD.FAIL_NO_RECORD]
    s = _script()
    s["graphics"][0]["record_id"] = "api-demo-other"
    assert _graphic_codes(s) == [AD.FAIL_NO_RECORD]


def test_each_chat_code():
    t = sd.topic()
    t["api_demo_record"] = sd.record(status="refused", skip_reason="safety", answer=None,
                                     finish_reason="SAFETY")
    assert AD.FAIL_BAD_FINISH in _graphic_codes(_script(), topic=t)
    s = _script()
    s["graphics"][0]["data"]["prompt"] = "Explain how a rainbow forms."
    assert _graphic_codes(s) == [AD.FAIL_PROMPT_MISMATCH]
    s = _script()
    s["graphics"][0]["data"]["answer"] = "Sunlight bends in raindrops and spreads into colours."
    assert _graphic_codes(s) == [AD.FAIL_ANSWER_REWRITTEN]
    s = _script()
    s["graphics"][0]["data"]["model_label"] = "Gemini · via API"
    assert _graphic_codes(s) == [AD.FAIL_MODEL_MISMATCH]
    t = sd.topic()
    t["api_demo_record"] = sd.record(model_version="gemini-9-ultra")
    assert _graphic_codes(_script(), topic=t) == [AD.FAIL_MODEL_MISMATCH]
    s = _script()
    s["graphics"][0]["data"]["date"] = "2026-10-11"
    assert _graphic_codes(s) == [OG.FAIL_VALUE_NOT_IN_FOOTING]


def test_a_chat_carries_no_values_and_no_source_label():
    s = _script()
    s["graphics"][0]["source_label"] = "Google"
    assert OG.FAIL_MALFORMED in _graphic_codes(s)
    s = _script()
    s["graphics"][0]["values"] = [{"path": "data.answer", "text": sd.ANSWER, "claim_ids": ["c1"]}]
    assert OG.FAIL_MALFORMED in _graphic_codes(s)


def test_every_chat_finding_has_its_fix_and_its_russian_line():
    s = _script()
    s["graphics"][0]["data"].update(prompt="Something else entirely.", model_label="X · via API")
    batch = _bench([s])
    res = cg.check_batch(batch, root=ROOT, out=lambda *_: None)
    assert res[s["script_id"]]
    for p in res[s["script_id"]]:
        assert p.get("fix") and p.get("text_ru"), p
    code, out = _run_graphics(batch)
    assert code == cg.EXIT_FINDING and "fix:" in out and "отказ:" in out


def test_a_chat_on_a_channel_without_the_api_demo_origin():
    pieces = {p["id"]: p for p in sd.topic()["support_text"]}
    protocols = AD.protocols_by_record(sd.record())
    good = cg.judge(_script(), OG, True, pieces, protocols, sd.CONFIG, api_origin=True)
    assert good == []
    s = _script()
    s["graphics"][0]["data"]["prompt"] = "Not the prompt."
    found = cg.judge(s, OG, True, pieces, protocols, sd.CONFIG, api_origin=False)
    assert [p["code"] for p in found] == [cg.CODE_API_NO_ORIGIN], found
    assert found[0]["fix"] and found[0]["text_ru"]


def test_a_chat_on_reel_or_science_is_a_graphic_without_origin():
    for ch in (REEL, SCIENCE):
        assert _graphic_codes(_script(), channel=ch) == [cg.CODE_NO_ORIGIN], ch


def test_the_check_names_every_chat_code_it_can_print():
    codes = cg.all_codes(OG)
    for c in OG.CHAT_CODES:
        if c != AD.FAIL_ANSWER_IS_FACT:
            assert c in codes, c
    assert AD.FAIL_ANSWER_IS_FACT not in codes
    assert cg.CODE_API_NO_ORIGIN in codes



# --------------------------------------------------------------------------
# check_claims.py / check_production_fact.py: the answer is never our fact
# --------------------------------------------------------------------------

import check_claims as cc  # noqa: E402
import check_production_fact as cpf  # noqa: E402

JUDGE = cc.load_judge(ROOT)
CL = JUDGE.claims
REPORT_QUOTE = "the factory sent this prompt to Gemini 2.5 Flash through the Gemini API"
ANSWER_QUOTE = "A rainbow forms when sunlight enters raindrops, bends"
WIKI = {"id": "p1", "kind": "rss_summary", "url": "https://example.org/a",
        "text": "Google released Gemini 2.5 Flash to developers on Tuesday."}


def _report_claim(cid="c1"):
    return {"claim_id": cid, "where": "commentary",
            "text": "We sent Gemini 2.5 Flash one question through the Gemini API",
            "support": [{"source": sd.RECORD_ID, "quote": REPORT_QUOTE}]}


def _footing(claims, script_over=None, is_fact=None):
    s = _script(claims=claims, **(script_over or {}))
    return cc.api_demo_footing(s, sd.topic(extra_pieces=[WIKI]), CL,
                               is_fact or JUDGE.is_fact_claim)


def test_the_code_is_the_roots():
    assert cc.API_DEMO_CODE == CL.FAIL_API_DEMO_IS_FACT == AD.FAIL_ANSWER_IS_FACT
    assert cpf.NOT_A_FACT_RULE == AD.FAIL_ANSWER_IS_FACT
    assert cc.API_DEMO_CODE in CL.API_DEMO_CODES


def test_the_report_of_the_demo_stands():
    assert _footing([_report_claim()]) == []
    # the model's name before "answered" is still the report
    c = _report_claim()
    c["support"] = [{"source": sd.RECORD_ID, "quote": "Gemini 2.5 Flash answered"}]
    c["text"] = "We sent Gemini 2.5 Flash one question"
    assert _footing([c]) == []
    # a claim on an ordinary piece is not this check's
    c = {"claim_id": "c2", "where": "hook", "text": "Google's newest small model is out",
         "support": [{"source": "p1", "quote": "Google released Gemini 2.5 Flash to developers"}]}
    assert _footing([c]) == []


def test_report_part_ends_before_the_answer():
    part = cc.report_part(sd.piece())
    assert part.endswith("answered: ") and sd.ANSWER not in part and sd.PROMPT in part
    other = {"id": "own-capture-x", "kind": "own_capture_record", "not_a_fact": True,
             "text": "The factory recorded acme/fox-demo running in a public Hugging Face Space."}
    assert cc.report_part(other) == other["text"]


def test_a_sentence_footed_on_the_answer_is_refused():
    c = {"claim_id": "c3", "where": "commentary",
         "text": "Here is its real answer, word for word",
         "support": [{"source": sd.RECORD_ID, "quote": ANSWER_QUOTE}]}
    found = _footing([_report_claim(), c])
    assert [(v["code"], v["claim_id"]) for v in found] == [(cc.API_DEMO_CODE, "c3")], found
    assert found[0]["fix"] and found[0]["text_ru"]


def test_a_claim_on_the_chat_is_refused():
    c = {"claim_id": "c4", "where": "graphic:g9", "text": sd.ANSWER[:40],
         "support": [{"source": sd.RECORD_ID, "quote": ANSWER_QUOTE}]}
    found = _footing([c])
    assert [v["code"] for v in found] == [cc.API_DEMO_CODE]
    assert "api_chat" in found[0]["detail"]


def test_the_videos_fact_on_a_not_a_fact_piece_is_refused():
    pf = {"text": "Google sent the prompt", "beat_text": "We sent Gemini 2.5 Flash one question",
          "source_url": "https://example.org/a", "on_screen": "Asked through the Gemini API"}
    c = {"claim_id": "c5", "where": "on_screen", "text": "Asked through the Gemini API",
         "support": [{"source": sd.RECORD_ID, "quote": REPORT_QUOTE}]}
    found = _footing([c], {"production_fact": pf})
    assert [v["code"] for v in found] == [cc.API_DEMO_CODE]
    # the own capture's record is not a fact either
    cap = {"id": "own-capture-x", "kind": "own_capture_record", "source": "own_capture",
           "not_a_fact": True, "url": "https://acme-fox-demo.hf.space/",
           "text": "The factory recorded acme/fox-demo running in a public Hugging Face Space."}
    c = {"claim_id": "c6", "where": "on_screen", "text": "Runs on Hugging Face",
         "support": [{"source": "own-capture-x",
                      "quote": "running in a public Hugging Face Space"}]}
    s = _script(claims=[c], production_fact=pf)
    found = cc.api_demo_footing(s, sd.topic(extra_pieces=[cap]), CL, JUDGE.is_fact_claim)
    assert [v["code"] for v in found] == [cc.API_DEMO_CODE]


def test_check_claims_refuses_before_the_judge_and_spends_nothing():
    d = Path(tempfile.mkdtemp(dir=_TMP))
    c = {"claim_id": "c3", "where": "commentary",
         "text": "Here is its real answer, word for word",
         "support": [{"source": sd.RECORD_ID, "quote": ANSWER_QUOTE}]}
    (d / "01-trend-hunter.json").write_text(json.dumps({"topics": [sd.topic()]}))
    batch = d / "03-content-researcher.json"
    batch.write_text(json.dumps({"scripts": [_script(claims=[_report_claim(), c])],
                                 "skipped": []}))
    never = d / "never.py"
    never.write_text("import sys; sys.exit('the judge must not be asked')\n")
    lines = []
    problems, records, refused = cc.check_batch(
        batch, root=ROOT, write=True, out=lines.append, judge=JUDGE,
        answer_cmd=f"{sys.executable} {never} {{request}} {{answer}}", terms=[])
    text = "\n".join(lines)
    assert problems and records == {} and refused == [], text
    assert cc.API_DEMO_CODE in text and "отказ:" in text and "no attempt spent" in text
    data = json.loads(batch.read_text())
    assert "claims_check" not in data["scripts"][0]


def _fact_script(**over):
    s = {"script_id": "tech-001-script1", "topic_id": sd.TOPIC,
         "fact": {"text": "x", "kind": "launch", "source": "Google", "url": "https://example.org/a"},
         "production_fact": {"source_url": "https://example.org/a"}}
    s.update(over)
    return s


def test_the_fact_record_never_names_a_not_a_fact_piece():
    topics = [sd.topic(extra_pieces=[WIKI])]
    assert cpf.not_a_fact_lines(_fact_script(), topics) == []
    endpoint = sd.piece()["url"]
    bad = _fact_script(fact={"text": "x", "kind": "launch", "source": "api_demo",
                             "url": endpoint},
                       production_fact={"source_url": endpoint})
    lines = cpf.not_a_fact_lines(bad, topics)
    assert len(lines) == 1 and cpf.NOT_A_FACT_RULE in lines[0], lines
    assert "fact.source is 'api_demo'" in lines[0] and "production_fact.source_url" in lines[0]
    assert cpf.not_a_fact_lines(bad, None)          # the source alone, with no 01
    assert cpf.not_a_fact_lines(_fact_script(), None) == []


# --------------------------------------------------------------------------
# SKILL.md
# --------------------------------------------------------------------------

def test_the_skill_says_how_to_order_a_chat_and_explains_every_code():
    import check_demo as cd
    for code in tuple(OG.CHAT_CODES) + (cg.CODE_API_NO_ORIGIN, cd.CODE_API_NOT_NAMED,
                                        OG.FAIL_VALUE_NOT_IN_FOOTING):
        assert f"`{code}`" in SKILL, code
    for words in ("A demo via API: the `api_chat`", "shown_answer", "display_name_for",
                  "model_label", "\"record_id\": \"api-demo-<topic>\"", "No `values`",
                  "no claim on the chat", "The narration reports the demo",
                  "not_a_fact", "Or a demo via API"):
        assert words in SKILL, words

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
