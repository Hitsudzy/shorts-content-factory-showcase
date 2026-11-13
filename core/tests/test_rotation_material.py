#!/usr/bin/env python3
"""CF-0775: the rotation never offers `demo` to a topic with no demo base.

ExampleTech, batch 2026-10-16T0839Z: of six topics only -008 had a recording
of our own; none had an api_demo_record. The rotation drew demo/hold for
iPhone Duo (-005) and Muse Spark Open (-013). -005's rejection was upheld and
handed back demo/even, whose rejection R3 denied; -013's was denied by R4
because -005 had refused demo/hold for the same missing base. Both topics left
as pattern_undeliverable.

Offline: the channel config is the repository's, the batch files and the
ledger are stand-ins in a tmp directory shaped like 0839Z's.

Run: python3 tests/test_rotation_material.py
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "rotation"))
sys.path.insert(0, str(ROOT / "shared"))

import rotate  # noqa: E402
import material  # noqa: E402
from ledger import (Ledger, ledger_path, mark_pattern_undeliverable,  # noqa: E402
                    mark_rhythm_excluded, rejection_prose, excluded_rhythm,
                    undeliverable_pattern, validate)

CHANNEL = "example-tech"
BATCH = "2026-10-16T0839Z"
REASON = ("no own capture: proof_quotes_only - the topic's footage is the vendor's own "
          "uploads only, no recording of ours and no api_demo_record, so demo has no base")


def _quotes_only(n):
    return {"base": None, "own_captures": 0, "proof_quotes": n, "other": 0,
            "only_proof_quotes": True,
            "note": f"proof_quotes_only: {n} vendor proof quote(s) and no own capture"}


def _topic(tid, base, candidates=()):
    return {"topic_id": tid, "evidence": {"footage_base": base,
                                          "footage_candidates": list(candidates)}}


CAPTURE = {"kind": "own_capture", "video_id": "own_capture:ysharma/chatgpt4"}
OK_CALL = {"record_id": "api-demo-x", "protocol": {"status": "ok", "model_version": "m"}}


def topics_0839z():
    """The six topics of 0839Z, reduced to what decides a demo's base."""
    return [
        _topic("lf-2026-10-16-001", _quotes_only(2)),
        _topic("lf-2026-10-16-004", _quotes_only(2)),
        _topic("lf-2026-10-16-005", _quotes_only(4)),
        _topic("lf-2026-10-16-008",
               {"base": "own_capture", "own_captures": 2, "proof_quotes": 4,
                "only_proof_quotes": False, "note": "2 own capture(s)"}, [CAPTURE]),
        _topic("lf-2026-10-16-010", _quotes_only(1)),
        _topic("lf-2026-10-16-013",
               {"base": None, "own_captures": 0, "proof_quotes": 0, "other": 0,
                "only_proof_quotes": False,
                "note": "no own capture and no vendor proof quote - nothing for a demo"}),
    ]


def sid(n):
    return f"lf-2026-10-16-{n:03d}-script1"


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cf0775-"))
        self.pipeline = self.tmp / "pipeline"
        self.ledger_dir = self.tmp / "ledger"
        self.ledger_dir.mkdir()
        self.batch = self.pipeline / CHANNEL / BATCH
        self.batch.mkdir(parents=True)
        self.write_batch(topics_0839z())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_batch(self, topics, pool=None):
        (self.batch / "01-trend-hunter.json").write_text(json.dumps(
            {"batch_id": BATCH, "channel": CHANNEL, "topics": topics}))
        if pool is None:
            pool = {t["topic_id"]: (["own_capture-ysharma_chatgpt4"]
                                    if t["topic_id"].endswith("-008") else ["yt-abc"])
                    for t in topics}
        (self.batch / "01b-footage-index.json").write_text(json.dumps(
            {"sources_by_topic": pool}))

    def ledger(self):
        return Ledger(ledger_path(CHANNEL, self.ledger_dir))

    def append(self, n, pattern, rhythm, by="rotation"):
        return self.ledger().append(channel=CHANNEL, batch_id=BATCH, script_id=sid(n),
                                    pattern_id=pattern, rhythm_id=rhythm, assigned_by=by,
                                    assigned_at="2026-10-16T10:22:05Z")

    def assign(self, *ns):
        return rotate.assign(CHANNEL, BATCH, [sid(n) for n in ns], self.ledger_dir,
                             now="2026-10-16T10:22:05Z", pipeline_dir=self.pipeline,
                             despite_shortage=True)

    def reject(self, n, reason=REASON, **kw):
        return rotate.reject(CHANNEL, sid(n), reason, self.ledger_dir,
                             now="2026-10-16T10:22:16Z", batch_id=BATCH,
                             pipeline_dir=self.pipeline, **kw)


class TheBase(unittest.TestCase):
    def test_demo_base_reading(self):
        by = {t["topic_id"][-3:]: t for t in topics_0839z()}
        self.assertIsNone(material.demo_base(by["008"], ["own_capture-x"]))
        self.assertIsNone(material.demo_base(by["008"], None))
        self.assertIn("never reached the topic's pool", material.demo_base(by["008"], ["yt-1"]))
        self.assertIn("proof_quotes_only", material.demo_base(by["005"]))
        self.assertIn("no own capture", material.demo_base(by["013"]))
        with_api = dict(by["013"], api_demo_record=OK_CALL)
        self.assertIsNone(material.demo_base(with_api))
        skipped = dict(by["013"], api_demo_record={
            "record_id": "api-demo-x", "protocol": {"status": "skipped"}})
        self.assertIsNotNone(material.demo_base(skipped))

    def test_unreadable_batch_excludes_nothing(self):
        m = material.BatchMaterial(Path(tempfile.gettempdir()) / "cf0775-no-such-batch")
        self.assertFalse(m.known)
        self.assertEqual(m.undeliverable(sid(5), ["demo"]), {})

    def test_topic_id_of(self):
        self.assertEqual(material.topic_id_of(sid(5)), "lf-2026-10-16-005")


class Assign(Scratch):
    def test_0839z_batch_draws_no_demo_without_a_base(self):
        out = self.assign(1, 4, 5, 8, 10, 13)
        by = {a["script_id"]: a for a in out}
        for n in (1, 4, 5, 10, 13):
            a = by[sid(n)]
            self.assertNotEqual(a["pattern_id"], "demo", a)
            self.assertIn("demo", a["material_excluded"])
        self.assertNotIn("material_excluded", by[sid(8)])

    def test_topic_with_capture_still_gets_demo_when_it_is_due(self):
        # demo is the least-used pattern after the base-less topics passed it by
        self.assign(1, 4, 5, 10)
        a = self.assign(8)[0]
        self.assertEqual(a["pattern_id"], "demo")

    def test_api_demo_record_is_a_base(self):
        topics = topics_0839z()
        topics[5]["api_demo_record"] = OK_CALL
        self.write_batch(topics)
        self.assign(1, 4, 5, 10)
        self.assertEqual(self.assign(13)[0]["pattern_id"], "demo")

    def test_batch_not_on_disk_draws_as_before(self):
        shutil.rmtree(self.batch)
        out = self.assign(1, 4, 5, 10, 13)
        self.assertIn("demo", {a["pattern_id"] for a in out})
        self.assertFalse(any("material_excluded" in a for a in out))


class Reject(Scratch):
    def setUp(self):
        super().setUp()
        # 0839Z's ledger as the old rotation wrote it (seq 1-5).
        self.append(1, "contrast", "alternate")
        self.append(4, "demo", "even")
        self.append(5, "demo", "hold")
        self.append(8, "explainer", "alternate")
        self.append(10, "explainer", "even")

    def test_undeliverable_demo_rejection_is_upheld_with_no_demo_back(self):
        r = self.reject(5)
        self.assertEqual(r["verdict"], "upheld", r["explanation"])
        self.assertEqual(r["undeliverable_pattern"], "demo")
        self.assertNotEqual(r["assignment"]["pattern_id"], "demo")
        row = [x for x in self.ledger().rows() if x["seq"] == "3"][0]
        self.assertEqual(undeliverable_pattern(row), "demo")
        self.assertEqual(rejection_prose(row), REASON)
        self.assertEqual(validate(ledger_path(CHANNEL, self.ledger_dir)), [])

    def test_r4_does_not_count_a_material_refusal(self):
        # -005 refused demo/hold for the missing base; -013 then drawn demo/hold
        self.reject(5)
        self.append(13, "demo", "hold")
        r = self.reject(13, reason="no own capture: footage_base.base is null and no "
                                   "api_demo_record; demo cannot be delivered")
        self.assertEqual(r["verdict"], "upheld", r["explanation"])
        self.assertNotEqual(r["assignment"]["pattern_id"], "demo")

    def test_r4_still_holds_for_a_topic_with_a_base_after_a_taste_refusal(self):
        # two more topics with their own recording; -014 refused demo/hold as taste
        topics = topics_0839z()
        for n in (14, 15):
            topics.append(dict(topics[3], topic_id=f"lf-2026-10-16-{n:03d}"))
        pool = {t["topic_id"]: ["own_capture-x"] for t in topics}
        self.write_batch(topics, pool)
        row = self.append(14, "demo", "hold")
        self.ledger().enrich(int(row["seq"]),
                             rejection_reason="taste reason long enough to be a reason",
                             rejection_verdict="upheld", rejected_at="2026-10-16T10:22:10Z")
        self.append(15, "demo", "hold")
        r = self.reject(15, reason="I would rather not hold on this result screen")
        self.assertEqual((r["verdict"], r["rule"]), ("denied", "R4"))

    def test_r3_does_not_block_the_old_demo_even_replacement(self):
        # 0839Z's -005: an old upheld rejection (no marker) handed back demo/even
        led = self.ledger()
        led.enrich(3, rejection_reason="taste reason long enough to be a reason",
                   rejection_verdict="upheld", rejected_at="2026-10-16T10:22:10Z")
        self.append(5, "demo", "even", by="rotation-after-rejection")
        r = self.reject(5)
        self.assertEqual(r["verdict"], "upheld", r["explanation"])
        self.assertNotEqual(r["assignment"]["pattern_id"], "demo")

    def test_a_second_rejection_of_the_replacement_is_taste_again(self):
        self.reject(5)
        r = self.reject(5, reason="the replacement pair does not suit this story at all")
        self.assertEqual(r["verdict"], "denied")
        self.assertEqual(r["rule"], "R3")

    def test_demo_with_a_base_is_judged_as_taste(self):
        led = self.ledger()
        led.enrich(3, rejection_reason="taste reason long enough to be a reason",
                   rejection_verdict="upheld", rejected_at="2026-10-16T10:22:10Z")
        topics = topics_0839z()
        topics[2] = dict(topics[2], api_demo_record=OK_CALL)
        self.write_batch(topics)
        self.append(5, "demo", "even", by="rotation-after-rejection")
        r = self.reject(5)
        self.assertEqual((r["verdict"], r["rule"]), ("denied", "R3"))

    def test_rhythm_and_pattern_markers_together(self):
        r = self.reject(5, rejects_rhythm=True)
        self.assertEqual(r["verdict"], "upheld", r["explanation"])
        row = [x for x in self.ledger().rows() if x["seq"] == "3"][0]
        self.assertEqual(excluded_rhythm(row), "hold")
        self.assertEqual(undeliverable_pattern(row), "demo")
        self.assertEqual(rejection_prose(row), REASON)
        self.assertNotIn(r["assignment"]["rhythm_id"], ("hold",))


OPENCODER = "OpenCoder-LLM/OpenCoder-8B-Instruct"


def _with_capture(topic, name, space, title=None):
    """`topic` renamed to `name`, its own capture a recording of `space`."""
    topic["title_ref"] = {"name": name, "kind": "work"}
    for c in topic["evidence"]["footage_candidates"]:
        c["capture"] = {"space": space, "subject_match": "card_names"}
        if title is not None:
            c["title"] = f"{title} - own capture ({space})"
    return topic


def topics_1448z(space=OPENCODER, title=None):
    """0839Z's six with -008 turned into 1448Z's -013: OpenCode, recorded
    off another product's Space."""
    topics = topics_0839z()
    _with_capture(topics[3], "OpenCode", space, title)
    return topics


class ForeignSpace(Scratch):
    """CF-0832: a recording of another product is no demo base."""

    def test_the_name_rule(self):
        yes = [("OpenCode", "sst/opencode"), ("DeepSeek", "deepseek-ai/deepseek-vl2-small"),
               ("DeepSeek", "someone/deep-seek-chat"), ("ChatGPT", "ysharma/ChatGPT4"),
               ("GPT", "openai/gpt4o"), ("GPT-4o", "openai/gpt4o-mini"),
               ("Tesla Roadster", "x/tesla-roadster-lander"), ("Gemma", "google/gemma-3-demo")]
        no = [("OpenCode", OPENCODER), ("ChatGPT", "x/ChatGPTizer"), ("Sora", "a/sorabot-ui"),
              ("Gemini", "google/gemma-2"), ("", "a/b"), ("Muse", ""), ("Muse", None)]
        for name, space in yes:
            self.assertTrue(material.names_in(name, space), (name, space))
        for name, space in no:
            self.assertFalse(material.names_in(name, space), (name, space))
        self.assertTrue(material.space_names("OpenCode", "someone/coder-ui", "OpenCode demo"))
        self.assertFalse(material.space_names("OpenCode", OPENCODER, "OpenCoder 8B"))

    def test_a_foreign_space_is_no_base(self):
        topic = topics_1448z()[3]
        why = material.demo_base(topic, ["own_capture-x"])
        self.assertIn(OPENCODER, why)
        self.assertIn("CF-0832", why)
        self.assertIsNotNone(material.demo_base(topic, None))
        topic["api_demo_record"] = OK_CALL
        self.assertIsNone(material.demo_base(topic, ["own_capture-x"]))

    def test_a_space_that_names_the_topic_is_a_base(self):
        for space, title in (("sst/opencode", None), ("someone/coder-ui", "OpenCode web"),
                             ("x/opencode2", None)):
            topic = topics_1448z(space, title)[3]
            self.assertIsNone(material.demo_base(topic, ["own_capture-x"]), space)

    def test_what_cannot_be_judged_stays_a_base(self):
        no_name = topics_1448z()[3]
        no_name["title_ref"] = {}
        no_space = topics_1448z()[3]
        no_space["evidence"]["footage_candidates"][0]["capture"] = {}
        for topic in (no_name, no_space, topics_0839z()[3]):
            self.assertIsNone(material.demo_base(topic, ["own_capture-x"]), topic)

    def test_one_recording_of_the_topic_is_enough(self):
        topic = topics_1448z()[3]
        topic["evidence"]["footage_candidates"].append(
            {"kind": "own_capture", "video_id": "own_capture:sst/opencode",
             "capture": {"space": "sst/opencode"}})
        self.assertIsNone(material.demo_base(topic, ["own_capture-x"]))

    def test_a_card_title_of_another_shape_is_not_read(self):
        topic = topics_1448z()[3]
        topic["evidence"]["footage_candidates"][0]["title"] = "OpenCode, recorded"
        self.assertIsNotNone(material.demo_base(topic, ["own_capture-x"]))

    def test_the_draw_leaves_demo_out_for_a_foreign_recording(self):
        self.write_batch(topics_1448z())
        self.assign(1, 4, 5, 10)
        a = self.assign(8)[0]
        self.assertNotEqual(a["pattern_id"], "demo", a)
        self.assertIn("demo", a["material_excluded"])

    def test_the_draw_still_offers_demo_for_the_topic_s_own_recording(self):
        self.write_batch(topics_1448z("sst/opencode"))
        self.assign(1, 4, 5, 10)
        self.assertEqual(self.assign(8)[0]["pattern_id"], "demo")

    def test_a_rejection_of_demo_on_a_foreign_recording_is_upheld(self):
        self.write_batch(topics_1448z())
        self.append(5, "demo", "hold")
        self.reject(5)
        self.append(8, "demo", "hold")
        r = self.reject(8, reason="the recording is of OpenCoder, not OpenCode - "
                                  "no demo base")
        self.assertEqual(r["verdict"], "upheld", r["explanation"])
        self.assertNotEqual(r["assignment"]["pattern_id"], "demo")


class Markers(unittest.TestCase):
    def test_marker_order_and_prose(self):
        s = mark_pattern_undeliverable(mark_rhythm_excluded("why", "hold"), "demo")
        self.assertEqual(s, "[excluded rhythm: hold] [undeliverable pattern: demo] why")
        self.assertEqual(excluded_rhythm(s), "hold")
        self.assertEqual(undeliverable_pattern(s), "demo")
        self.assertEqual(rejection_prose(s), "why")
        self.assertEqual(mark_pattern_undeliverable("why", None), "why")

    def test_denied_row_marker_is_not_trusted(self):
        row = {"rejection_verdict": "denied", "rejected_at": "",
               "rejection_reason": "[undeliverable pattern: demo] why"}
        self.assertIsNone(undeliverable_pattern(row))


def _run(case):
    """Each class's checks run as one house-style test; a failure names them."""
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(case))
    bad = result.failures + result.errors
    assert not bad, "; ".join(str(t) for t, _ in bad)


def test_the_demo_base_is_read_from_the_batch():
    _run(TheBase)


def test_the_draw_leaves_demo_out_without_a_base():
    _run(Assign)


def test_a_missing_material_rejection_is_upheld():
    _run(Reject)


def test_the_ledger_markers():
    _run(Markers)


def test_a_recording_of_another_product_is_no_demo_base():
    _run(ForeignSpace)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
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
