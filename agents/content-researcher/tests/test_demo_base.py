#!/usr/bin/env python3
"""CF-0827: `scripts/demo_base.py` - can each topic be a «демо», asked at
step 2 from the Trend Hunter's output, before the rotation draws.

Pinned here: a topic with no demo base is `nodemo` by the rotation's own rule
(`rotation/material.py`, loaded from the root - the reading cannot drift from
the draw's); a recording in the pool whose Space carries the topic's name is
`demo`; a recording of another product (`2026-10-20T1448Z` -013: OpenCode
against `OpenCoder-LLM/OpenCoder-8B-Instruct`) is `nodemo` - since CF-0832 the
root's reading no longer counts it as a base; `LOOK` (exit 1) is the safeguard
where the root still counts a base the Space id does not name (the name only in
the Space's card title); a recording
missing from the pool with an ok API record is a demo via API; a channel that
does not list `demo` has nothing to decide; no 01 is exit 3; the skill runs it
at step 2 before the first `rotate.py assign`.

Offline: synthetic topics in a temp batch, a stand-in channel config in a temp
root whose `rotation/` points at the checkout's (the rule's code, not data).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import demo_base as db  # noqa: E402

REAL_ROOT = db.find_root()
_TMP = tmp_root("cr-demo-base-")
SKILL = HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md"
CHANNEL = "test-tech"


def _root(allowed=("demo", "list")):
    root = _TMP / f"root-{'-'.join(allowed) or 'none'}"
    if not root.exists():
        (root / "channels").mkdir(parents=True)
        (root / "channels" / f"{CHANNEL}.json").write_text(json.dumps(
            {"patterns": {"allowed_pattern_ids": list(allowed)}}))
        (root / "rotation").symlink_to(REAL_ROOT / "rotation", target_is_directory=True)
    return root


def _capture_topic(tid, name, space, how="card_names", card=None):
    cid = space.lower().replace("/", "-")
    cand = {"kind": "own_capture", "video_id": f"own_capture:{cid}",
            "capture": {"space": space, "subject_match": how}}
    if card:
        cand["title"] = f"{card} - own capture ({space})"
    return {"topic_id": tid, "title_ref": {"name": name, "kind": "work"},
            "evidence": {
                "footage_base": {"base": "own_capture", "own_captures": 1,
                                 "only_proof_quotes": False, "note": "stand-in"},
                "footage_candidates": [cand]}}


def _quotes_topic(tid, name):
    return {"topic_id": tid, "title_ref": {"name": name},
            "evidence": {"footage_base": {"base": None, "only_proof_quotes": True,
                                          "proof_quotes": 3, "note": "vendor quotes"},
                         "footage_candidates": []}}


def _pool(topic):
    cands = topic["evidence"]["footage_candidates"]
    return ["own_capture-" + c["video_id"].split(":", 1)[1] for c in cands]


def bench(name, topics, pools=None):
    d = _TMP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / db.TREND_FILE).write_text(json.dumps({"channel": CHANNEL, "topics": topics}))
    if pools is not None:
        (d / db.INDEX_FILE).write_text(json.dumps({"sources_by_topic": pools}))
    return d


def run(batch, root=None, topics=None):
    lines = []
    res = db.check_batch(batch, topics, root or _root(), out=lines.append)
    return res, "\n".join(lines)


OPENCODE = _capture_topic("t-013", "OpenCode", "OpenCoder-LLM/OpenCoder-8B-Instruct")
DEEPSEEK = _capture_topic("t-005", "DeepSeek", "deepseek-ai/deepseek-vl2-small", "official")
CHATGPT = _capture_topic("t-008", "ChatGPT", "ysharma/ChatGPT4")
QUOTES = _quotes_topic("t-001", "iPhone Duo")
# the name only in the Space's card title: the root counts a base, the id does not name it
CARD_ONLY = _capture_topic("t-021", "OpenCode", "someone/coder-ui", card="OpenCode web")


def test_the_three_verdicts_on_one_batch():
    topics = [OPENCODE, DEEPSEEK, CHATGPT, QUOTES, CARD_ONLY]
    batch = bench("three", topics, {t["topic_id"]: _pool(t) for t in topics})
    res, text = run(batch)
    # 1448Z -013: a recording of another product is no base at the root (CF-0832)
    assert res["t-013"][0] == db.VERDICT_NODEMO, text
    assert "OpenCoder-LLM/OpenCoder-8B-Instruct" in res["t-013"][1], res["t-013"]
    assert "CF-0832" in res["t-013"][1], res["t-013"]
    assert res["t-021"][0] == db.VERDICT_LOOK, text
    assert "someone/coder-ui" in res["t-021"][1] and "CF-0832" in res["t-021"][1]
    assert res["t-005"][0] == db.VERDICT_DEMO and "subject_match official" in res["t-005"][1]
    assert res["t-008"][0] == db.VERDICT_DEMO, res["t-008"]
    assert res["t-001"][0] == db.VERDICT_NODEMO and "CF-0775" in res["t-001"][1]


def test_nodemo_is_the_rotations_own_reading():
    material = db.load_material(_root())
    for topic in (QUOTES, OPENCODE, CARD_ONLY, DEEPSEEK, CHATGPT):
        pool = _pool(topic)
        v, _ = db.verdict(topic, pool, material)
        assert (v == db.VERDICT_NODEMO) == bool(material.demo_base(topic, pool)), topic


def test_look_is_only_where_the_root_counts_a_base():
    """`LOOK` is the safeguard, not a second rule: never on a topic the root
    already refuses; on the card-title case the root counts a base and the
    Space id does not name the topic."""
    material = db.load_material(_root())
    assert material.demo_base(CARD_ONLY, _pool(CARD_ONLY)) is None
    assert not db.space_names("OpenCode", "someone/coder-ui")
    assert db.verdict(CARD_ONLY, _pool(CARD_ONLY), material)[0] == db.VERDICT_LOOK
    assert db.verdict(OPENCODE, _pool(OPENCODE), material)[0] == db.VERDICT_NODEMO


def test_a_recording_missing_from_the_pool_is_no_base():
    batch = bench("not-in-pool", [DEEPSEEK], {"t-005": ["yt-somevendorclip"]})
    res, text = run(batch)
    assert res["t-005"][0] == db.VERDICT_NODEMO and "never reached" in res["t-005"][1], text


def test_the_name_rule():
    yes = [("OpenCode", "sst/opencode"), ("DeepSeek", "deepseek-ai/deepseek-vl2-small"),
           ("DeepSeek", "someone/deep-seek-chat"), ("ChatGPT", "ysharma/ChatGPT4"),
           ("Gemma", "google/gemma-3-demo"), ("Tesla Roadster", "x/tesla-roadster-lander"),
           ("GPT-4o", "openai/gpt4o-mini")]
    no = [("OpenCode", "OpenCoder-LLM/OpenCoder-8B-Instruct"), ("Gemini", "google/gemma-2"),
          ("Sora", "someone/sorabot-ui"), ("", "a/b"), ("Muse", "")]
    for name, space in yes:
        assert db.space_names(name, space), (name, space)
    for name, space in no:
        assert not db.space_names(name, space), (name, space)


def test_exit_codes_and_the_topic_filter():
    topics = [OPENCODE, DEEPSEEK, CARD_ONLY]
    batch = bench("exit", topics, {t["topic_id"]: _pool(t) for t in topics})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert db.main([str(batch), "--root", str(_root())]) == db.EXIT_LOOK
        # OpenCode against OpenCoder-LLM is nodemo now (CF-0832): nothing owed
        assert db.main([str(batch), "--root", str(_root()), "--topic", "t-013",
                        "--topic", "t-005"]) == db.EXIT_OK
        assert db.main([str(batch), "--root", str(_root()), "--topic", "t-005"]) == db.EXIT_OK
        assert db.main([str(batch / db.TREND_FILE), "--root", str(_root()),
                        "--topic", "t-005"]) == db.EXIT_OK
        assert db.main([str(batch), "--root", str(_root()), "--topic", "nope"]) == \
            db.EXIT_CANNOT_ANSWER
        assert db.main([str(_TMP / "no-such-batch"), "--root", str(_root())]) == \
            db.EXIT_CANNOT_ANSWER
    assert "t-013" in buf.getvalue() and "t-021" in buf.getvalue()


def test_a_channel_without_demo_has_nothing_to_decide():
    batch = bench("no-demo", [OPENCODE], {"t-013": _pool(OPENCODE)})
    res, text = run(batch, root=_root(("list", "contrast")))
    assert res == {} and text.startswith("none"), text


def test_the_script_writes_its_run_event_under_its_step():
    src = (HERE.parent / "scripts" / "demo_base.py").read_text()
    assert '@runlog.script("content-researcher", "demo-base", name="demo_base.py")' in src
    assert "subprocess" not in src and "urllib" not in src and "requests" not in src
    assert src.rstrip().endswith('if __name__ == "__main__":\n    cli()')


def test_the_skill_asks_it_at_step_2_before_the_rotation():
    text = SKILL.read_text()
    start = text.index("\n2. **Take the fact")
    step2 = text[start:text.index("\n3. **Take the assigned", start)]
    assert "scripts/demo_base.py" in step2 and "CF-0827" in step2
    assert "`demo-base`" in text
    assert text.index("scripts/demo_base.py") < text.index("rotate.py assign")
    for verdict in ("`nodemo`", "`LOOK`"):
        assert verdict in step2, verdict


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
