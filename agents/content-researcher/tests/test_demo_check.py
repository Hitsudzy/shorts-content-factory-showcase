#!/usr/bin/env python3
"""CF-0567: the «демо» pattern at the writer's stage.

`scripts/check_demo.py` is the writer's early warning on a `demo` script -
the topic has our own recording (`demo_without_capture`), the vendor's quotes
stay inside the channel's `proof_quotes` cap (`demo_quote_over_cap`), what
the tool does on screen stands on the recording (`demo_base_not_capture`),
and a spoken line says where the tool ran (`demo_space_not_named`). The
Video Editor's `proof_quote_cap` / `demo_own_capture` gates stay the line
after the plan; this file asks nothing they measure.

And the stage's data-driven checks read `demo` from the root's pattern file
like any other pattern: the meme and sound gates refuse it, the proof gate
admits it, the cadence ceiling and the two-source floor are its hold band,
the voice fit and the block planner take its order.

Every batch here is built in a temp directory from a fake Tech topic (a
Hugging Face Space recording and a vendor's quote) - no pipeline, no pool, no
network. The root's channel and pattern files are read as code.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-demo-")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import check_demo as cd  # noqa: E402
import check_reactions as crx  # noqa: E402
import check_sounds as csn  # noqa: E402
import check_proofs as cpr  # noqa: E402
import check_anchor_cadence as cad  # noqa: E402
import check_two_sources as cts  # noqa: E402
import check_narration_budget as cnb  # noqa: E402

ROOT = cnb.find_root()
SKILL = (REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
README = (REPO / "README.md").read_text()

TECH = "example-tech"
TOPIC = "tech-001"
CID = "own_capture:acme-fox-demo-1"          # the Trend Hunter's candidate name
FID = "own_capture-acme-fox-demo-1"          # the Footage Indexer's file id
VENDOR = "VEND0R0001x"                        # a vendor's official upload
SPACE = "acme/fox-demo"
RATE = 2.0                                     # words a second, so seconds = words / 2


def _own_candidate():
    return {"video_id": CID, "kind": "own_capture", "nature": "demo", "role": "base",
            "footage_origin": "own_capture",
            "capture_file": f"/tmp/nowhere/{FID}.mp4",
            "capture": {"space": SPACE, "page": "https://acme-fox-demo.hf.space/",
                        "final_url": "https://acme-fox-demo.hf.space/",
                        "space_licence": "mit", "steps_variant": "gradio-examples",
                        "steps": [{"do": "wait"}, {"do": "click"}, {"do": "submit"}],
                        "steps_done": [{"index": 0, "do": "wait", "ok": True, "at_s": 1.0},
                                       {"index": 1, "do": "click", "ok": True, "at_s": 2.5},
                                       {"index": 2, "do": "submit", "ok": True, "at_s": 4.0}],
                        "sidecar": f"/tmp/nowhere/{FID}.own_capture.json",
                        "captured_at": "2026-10-12T08:00:00Z", "id": "acme-fox-demo-1",
                        "file_id": FID}}


def _quote_candidate():
    return {"video_id": VENDOR, "kind": "keynote", "role": "proof_quote",
            "footage_origin": "vendor_official", "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx"}


def _topic(own=True, quotes=True):
    cands = ([_own_candidate()] if own else []) + ([_quote_candidate()] if quotes else [])
    n_own, n_q = int(own), int(quotes)
    base = {"base": "own_capture" if own else None, "own_captures": n_own,
            "proof_quotes": n_q, "other": 0, "only_proof_quotes": bool(quotes) and not own,
            "note": ("1 own capture(s) lead the list" if own else
                     "proof_quotes_only: 1 vendor proof quote(s) and no own capture - not a "
                     "demo")}
    return {"topic_id": TOPIC, "evidence": {"footage_candidates": cands, "footage_base": base}}


def _claim(cid, text, shot):
    return {"claim_id": cid, "where": "commentary", "text": text,
            "support": [{"shot_id": shot}]}


def _script(pattern="demo", **extra):
    s = {"script_id": "tech-001-script1", "topic_id": TOPIC,
         "pattern": {"pattern_id": pattern, "rhythm_id": "even",
                     "parameters": {"block_count": 10}},
         "hook": "Acme just opened its fox model - and here it is drawing.",
         "commentary": ("It runs in a public Hugging Face Space, acme/fox-demo. "
                        "The prompt box takes the words. "
                        "The model draws the fox in four seconds. "
                        "The sketch fills in. Acme says it is fast."),
         "payoff": "You can try it free, no sign-in.",
         "narration": {"estimated_words_per_second": RATE},
         "claims": [
             _claim("c1", "The prompt box takes the words.", f"{FID}:1"),
             _claim("c2", "The model draws the fox in four seconds.", f"{FID}:2"),
             _claim("c3", "The sketch fills in.", f"{FID}:3"),
             _claim("c4", "Acme says it is fast.", f"{VENDOR}:4"),
         ]}
    s.update(extra)
    return s


class Bench:
    def __init__(self, scripts, topic=None, pool=(FID, VENDOR), channel=TECH, index=True):
        self.dir = Path(tempfile.mkdtemp(dir=_TMP))
        self.batch = self.dir / "03-content-researcher.json"
        self.batch.write_text(json.dumps({"channel": channel, "scripts": scripts}))
        (self.dir / "01-trend-hunter.json").write_text(
            json.dumps({"topics": [topic if topic is not None else _topic()]}))
        if index:
            (self.dir / "01b-footage-index.json").write_text(
                json.dumps({"sources_by_topic": {TOPIC: list(pool)}}))
        self.lines = []

    def check(self):
        return cd.check_batch(self.batch, root=ROOT, out=self.lines.append)

    def codes(self):
        return [c for found in self.check().values() for c, _d in found]

    def run(self):
        return cd.main([str(self.batch), "--root", str(ROOT)])

    def text(self):
        return "\n".join(self.lines)


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def test_a_demo_on_its_own_recording_passes():
    b = Bench([_script()])
    assert b.check() == {"tech-001-script1": []}, b.text()
    assert "ok    tech-001-script1" in b.text()
    assert "quote caps 2 quote(s), 5.0 s each, 8.0 s in all" in b.text(), b.text()
    assert b.run() == cd.EXIT_OK


def test_a_topic_of_vendor_quotes_only_is_not_a_demo():
    b = Bench([_script()], topic=_topic(own=False, quotes=True), pool=(VENDOR,))
    found = b.check()["tech-001-script1"]
    assert [c for c, _ in found] == [cd.CODE_WITHOUT_CAPTURE], found
    assert "only_proof_quotes" in found[0][1]
    assert "rotate.py reject" in b.text() and "another pattern" in b.text()
    assert b.run() == cd.EXIT_FINDING


def test_a_topic_with_no_footage_base_is_not_a_demo():
    t = _topic()
    del t["evidence"]["footage_base"]
    assert Bench([_script()], topic=t).codes() == [cd.CODE_WITHOUT_CAPTURE]


def test_a_recording_that_never_reached_the_pool_is_not_a_demo():
    b = Bench([_script()], pool=(VENDOR,))
    found = b.check()["tech-001-script1"]
    assert [c for c, _ in found] == [cd.CODE_WITHOUT_CAPTURE] and "pool" in found[0][1], found
    # without a footage index the pool half is not asked
    assert Bench([_script()], index=False).codes() == []


def test_too_many_quotes_is_over_the_cap():
    s = _script()
    s["claims"] += [_claim("c5", "It is fast.", f"{VENDOR}:5"),
                    _claim("c6", "Acme says it.", f"{VENDOR}:6"),
                    _claim("c7", "The sketch fills in.", f"{FID}:4"),
                    _claim("c8", "The prompt box takes the words.", f"{FID}:5")]
    found = Bench([s]).check()["tech-001-script1"]
    assert [c for c, _ in found] == [cd.CODE_QUOTE_OVER_CAP], found
    assert "max_quotes_per_video 2" in found[0][1], found


def test_a_long_quote_is_over_the_cap_per_quote_and_in_all():
    s = _script()
    # 12 words at 2 w/s is 6 s over one quote shot: over 5 s; with the 4-word
    # quote (2 s) that is 8 s ... make it 18 words = 9 s, over 8 s in all too.
    s["claims"][3] = _claim("c4", " ".join(["fast"] * 18), f"{VENDOR}:4")
    found = Bench([s]).check()["tech-001-script1"]
    details = [d for c, d in found if c == cd.CODE_QUOTE_OVER_CAP]
    assert any("max_seconds_per_quote 5.0" in d for d in details), found
    assert any("max_seconds_per_video 8.0" in d for d in details), found


def test_base_not_the_recording_is_sent_back():
    s = _script()
    s["claims"] = [c for c in s["claims"] if VENDOR in c["support"][0]["shot_id"]]
    found = Bench([s]).check()["tech-001-script1"]
    assert cd.CODE_BASE_NOT_CAPTURE in [c for c, _ in found], found
    s = _script()
    s["claims"] = s["claims"][:1] + [s["claims"][3], _claim("c5", "Acme says it.", f"{VENDOR}:5")]
    found = Bench([s]).check()["tech-001-script1"]
    assert [c for c, _ in found] == [cd.CODE_BASE_NOT_CAPTURE], found
    assert "not more than half" in found[0][1]


def test_the_space_has_to_be_named_aloud():
    s = _script(commentary="The prompt box takes the words. The model draws the fox in four "
                           "seconds. The sketch fills in. Acme says it is fast.")
    found = Bench([s]).check()["tech-001-script1"]
    assert [c for c, _ in found] == [cd.CODE_SPACE_NOT_NAMED], found
    assert SPACE in found[0][1]
    # "Hugging Face" and the owner (the vendor the hook names) are not where it ran
    s = _script(commentary=s["commentary"] + " It is on Hugging Face, by acme.")
    assert Bench([s]).codes() == [cd.CODE_SPACE_NOT_NAMED]
    # the Space's name said aloud is - its hyphen read as a space
    s = _script(commentary=s["commentary"] + " The Space is called fox demo.")
    assert Bench([s]).codes() == []


def test_an_own_capture_shot_named_by_its_candidate_name_counts():
    s = _script()
    for c in s["claims"][:3]:
        c["support"][0]["shot_id"] = c["support"][0]["shot_id"].replace(FID, CID)
    assert Bench([s]).codes() == []


def test_other_patterns_and_other_channels_are_untouched():
    b = Bench([_script(pattern="explainer"), _script(pattern="scale")], channel="example-film",
              topic={"topic_id": TOPIC})
    assert b.check() == {}, b.text()
    assert "no `demo` script" in b.text()
    assert b.run() == cd.EXIT_OK
    # a mixed batch judges only the demo
    other = _script(pattern="list", script_id="tech-002-script1", topic_id="tech-002")
    b = Bench([other, _script()])
    assert list(b.check()) == ["tech-001-script1"]


def test_cannot_answer_without_the_trend_file_or_the_batch():
    b = Bench([_script()])
    (b.dir / "01-trend-hunter.json").unlink()
    assert b.run() == cd.EXIT_CANNOT_ANSWER
    assert cd.main([str(b.dir / "nope.json"), "--root", str(ROOT)]) == cd.EXIT_CANNOT_ANSWER




# --------------------------------------------------------------------------
# the SKILL and the README say it
# --------------------------------------------------------------------------

def test_every_code_is_explained_in_the_skill_with_its_fix():
    for code in cd.CODES:
        assert f"`{code}`" in SKILL, code
    assert "check_demo.py" in SKILL and "`check-demo`" in SKILL
    for words in ("evidence.footage_base", "only_proof_quotes", "steps_done", "duration_s",
                  "Hugging Face Space", "max_seconds_per_quote", "never_the_base",
                  "fact_without_attribution", "patterns/demo.json"):
        assert words in SKILL, words


def test_the_readme_lists_the_check():
    assert "`check_demo.py`" in README and "CF-0567" in README


# --------------------------------------------------------------------------
# the stage's data-driven checks read `demo` from the root
# --------------------------------------------------------------------------

def _demo_order(rhythm="even", hold=3.8):
    return {"pattern_id": "demo", "rhythm_id": rhythm,
            "parameters": {"block_count": 10, "key_frame_hold_seconds": hold,
                           "opening_block": "hook_over_footage",
                           "acceleration_to_payoff": {"enabled": False, "strength": None}}}


def test_the_layers_follow_the_pattern_file():
    patterns = crx.load_patterns(ROOT)
    assert "demo" in patterns
    demo = patterns["demo"]
    assert crx.pattern_gate(demo) is False, "no memes on a demo"
    assert csn.pattern_gate(demo) is False, "no sounds on a demo"
    assert cpr.pattern_gate(demo) is True, "the fact's plate, on the fact's beat"


def test_the_hold_band_is_read_by_cadence_and_two_sources():
    top, src = cad.hold_ceiling("demo", ROOT)
    floor, src2 = cts.hold_floor("demo", ROOT)
    band = json.loads((ROOT / "patterns" / "demo.json").read_text())[
        "parameters"]["key_frame_hold_seconds"]
    assert (floor, top) == (band["min"], band["max"]) == (3.5, 8.0)
    assert "patterns/demo.json" in src and "patterns/demo.json" in src2


def test_the_voice_fit_takes_a_demo_order():
    vp = cnb.validator(ROOT)
    patterns = vp.load_patterns()
    budget = cnb.load_budget(TECH, ROOT)
    words = budget["narration_words_target"]
    for rhythm in ("even", "hold"):
        band = vp.hold_draw_band(patterns["demo"], rhythm)
        hold = band[0] if isinstance(band, (list, tuple)) and band else 3.8
        try:
            fitted = vp.fit_order_to_voice(_demo_order(rhythm, hold), patterns["demo"], words,
                                           channel=budget)
        except vp.OrderDoesNotFitVoice as exc:     # a verdict, not a crash
            assert exc.reason, rhythm
            continue
        assert fitted["pattern_id"] == "demo" and "voice_fit" in fitted, fitted


def test_the_block_planner_lays_out_a_demo_with_the_editors_rhythm():
    editor = ROOT / "agents" / "video-editor" / "scripts"
    if not (editor / "rhythm.py").exists():      # the suite runs without the Editor's checkout
        return
    import plan_blocks as pb
    rhythm = pb.load_rhythm(editor)
    starts = [0.0, 4.0, 8.5, 13.0, 18.0, 23.0, 28.0, 33.0, 38.0, 43.0]
    plan = pb.plan_one(rhythm, {"script_id": "d", "anchor_starts": starts, "total": 48.0,
                                "order": _demo_order()}, str(ROOT / "patterns"))
    assert plan["pattern_read"] is True and plan["blocks"], plan
    assert plan["blocks"][0]["start"] == 0.0



# --------------------------------------------------------------------------
# CF-0690: a demo via API - the chat on the topic's api_demo_record
# --------------------------------------------------------------------------

sys.path.insert(0, str(HERE))
import _api_demo_stand_in as sd  # noqa: E402

API_COMMENTARY = ("We sent Gemini 2.5 Flash one question through the Gemini API. "
                  "Here is its real answer, word for word. It took a second.")


def _api_topic(own=False, record=True, **proto):
    t = _topic(own=own, quotes=False)
    if record:
        t["api_demo_record"] = sd.record(**proto)
    return t


def _api_script(commentary=API_COMMENTARY, place=True, **extra):
    s = _script(hook="Google's newest small model is out - so we asked it something.",
                commentary=commentary, payoff="Fast, plain, and on the record.",
                claims=[], graphics=[sd.chat()],
                visual_anchors=([{"anchor_id": "a1", "graphic_id": "g9",
                                  "beat_text": "Here is its real answer, word for word."}]
                                if place else []))
    s.update(extra)
    return s


def test_a_demo_on_an_api_chat_and_its_record_passes_with_no_capture():
    b = Bench([_api_script()], topic=_api_topic(), pool=())
    assert b.check() == {"tech-001-script1": []}, b.text()
    assert "shows the real tool" in b.text() and "the model and the API named" in b.text()
    assert b.run() == cd.EXIT_OK
    # with no footage index at all, too
    b = Bench([_api_script()], topic=_api_topic(), index=False)
    assert b.codes() == [], b.text()


def test_a_chat_without_the_record_or_unplaced_or_not_ok_is_no_demo():
    assert Bench([_api_script()], topic=_api_topic(record=False)).codes() == [
        cd.CODE_WITHOUT_CAPTURE]
    assert Bench([_api_script(place=False)], topic=_api_topic()).codes() == [
        cd.CODE_WITHOUT_CAPTURE]
    t = _api_topic(status="refused", skip_reason="safety", answer=None, finish_reason="SAFETY")
    assert Bench([_api_script()], topic=t).codes() == [cd.CODE_WITHOUT_CAPTURE]
    s = _api_script()
    s["graphics"][0]["record_id"] = "api-demo-other"
    assert Bench([s], topic=_api_topic()).codes() == [cd.CODE_WITHOUT_CAPTURE]


def test_demo_api_not_named():
    nameless = ("We sent the new model one question. "
                "Here is its real answer, word for word. It took a second.")
    b = Bench([_api_script(commentary=nameless)], topic=_api_topic())
    assert b.codes() == [cd.CODE_API_NOT_NAMED], b.text()
    assert cd.FIX[cd.CODE_API_NOT_NAMED] in b.text()
    no_api = ("We sent Gemini 2.5 Flash one question. "
              "Here is its real answer, word for word. It took a second.")
    assert Bench([_api_script(commentary=no_api)], topic=_api_topic()).codes() == [
        cd.CODE_API_NOT_NAMED]
    # a model the channel's list does not name cannot be named
    t = _api_topic(model_version="gemini-9-ultra")
    b = Bench([_api_script()], topic=t)
    assert b.codes() == [cd.CODE_API_NOT_NAMED] and "gemini-9-ultra" in b.text(), b.text()


def test_a_capture_demo_with_a_chat_keeps_every_capture_rule():
    t = _topic()
    t["api_demo_record"] = sd.record()
    s = _script(graphics=[sd.chat()])
    s["visual_anchors"] = [{"anchor_id": "a1", "graphic_id": "g9",
                            "beat_text": "The sketch fills in."}]
    # the recording's rules hold, and the chat has to be named too
    assert Bench([s], topic=t).codes() == [cd.CODE_API_NOT_NAMED]
    s["commentary"] += " We also asked Gemini 2.5 Flash through the Gemini API."
    assert Bench([s], topic=t).codes() == []
    s2 = _script(graphics=[sd.chat()], commentary=s["commentary"].replace(
        "It runs in a public Hugging Face Space, acme/fox-demo. ", ""))
    s2["visual_anchors"] = s["visual_anchors"]
    assert Bench([s2], topic=t).codes() == [cd.CODE_SPACE_NOT_NAMED]


def test_a_demo_with_no_chat_is_judged_as_before():
    t = _topic(own=False)
    t["api_demo_record"] = sd.record()          # a record, but the script orders no chat
    assert Bench([_script()], topic=t).codes() == [cd.CODE_WITHOUT_CAPTURE]

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
