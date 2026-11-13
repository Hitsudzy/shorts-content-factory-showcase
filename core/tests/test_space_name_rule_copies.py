#!/usr/bin/env python3
"""CF-0832: one answer to "does this Hugging Face Space name the topic?".

ExampleTech `2026-10-20T1448Z` -013 (OpenCode) was recorded off the Space
`OpenCoder-LLM/OpenCoder-8B-Instruct` and lost as `pattern_undeliverable`. The
whole-word rule that tells "OpenCode" from "OpenCoder" now stands in three
places, each where its stage has to ask it:

  * the root's `rotation/material.py` `names_in()` - `demo_base()` does not
    count a recording of another product as the topic's demo base, so the
    rotation never draws `demo` for it (CF-0832);
  * the Trend Hunter's `scripts/fetch_own_capture.py` `word_run()` - it does not
    record a foreign Space in the first place (CF-0831);
  * the Content Researcher's `scripts/demo_base.py` `space_names()` - its step 2
    verdict (CF-0827).

The root and each agent are separate checkouts that land on separate days, so
the agents keep their own copies (no import across repositories). Three copies
of one predicate drift apart unless something holds them together; this file
is that something: the three answer one shared set of examples, and any
disagreement is a failure naming the example and who said what.

The genre is `tests/test_fact_rule_copies.py`'s: a fact that spans
repositories, checked from the root, skipped out loud when the neighbouring
checkout is not here. Nothing of an agent is imported: the copy's functions
(and the module constants they read) are cut out of the file with `ast` and
run in a namespace of their own, so no agent module or its imports land in
this process. Offline, no live data.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rotation"))
sys.path.insert(0, str(ROOT / "shared"))

import material  # noqa: E402

HUNTER = ROOT / "agents" / "trend-hunter" / "scripts" / "fetch_own_capture.py"
RESEARCHER = ROOT / "agents" / "content-researcher" / "scripts" / "demo_base.py"

# (name, Space id or title, does it name it)
EXAMPLES = [
    ("OpenCode", "OpenCoder-LLM/OpenCoder-8B-Instruct", False),   # 1448Z -013
    ("OpenCode", "sst/opencode", True),
    ("OpenCode", "someone/open-code-web", True),
    ("OpenCode", "OpenCoder 8B Instruct", False),
    ("ChatGPT", "ysharma/ChatGPT4", True),
    ("ChatGPT", "x/ChatGPTizer", False),
    ("ChatGPT", "x/chat-gpt-v2", True),
    ("ChatGPT", "x/chatgptv2beta", True),
    ("GPT", "openai/gpt4o", True),
    ("GPT-4o", "openai/gpt4o-mini", True),
    ("GPT-4", "openai/gpt4o", False),
    ("gpt4", "x/gpt4o", False),
    ("DeepSeek", "deepseek-ai/deepseek-vl2-small", True),
    ("DeepSeek", "someone/deep-seek-chat", True),
    ("DeepSeek", "someone/deepseeker", False),
    ("Gemini", "google/gemma-2", False),
    ("Gemma", "google/gemma-3-demo", True),
    ("Gemma 3", "google/gemma-3-demo", True),
    ("Gemma 3", "google/gemma3n", False),
    ("Sora", "someone/sorabot-ui", False),
    ("Sora", "someone/sora", True),
    ("Tesla Roadster", "x/tesla-roadster-lander", True),
    ("Tesla Roadster", "x/roadster-tesla", False),
    ("Muse Spark", "meta/musespark-demo", True),
    ("Muse Spark", "meta/muse", False),
    ("Qwen", "Qwen/Qwen2.5-VL", True),
    ("Qwen", "x/qwenlm", False),
    ("Llama", "x/llama-v3", True),
    ("Llama", "x/llamav3", True),
    ("Llama", "x/llamavision", False),
    ("Флюкс", "x/flux", False),
    ("", "a/b", False),
    ("Muse", "", False),
]


def _cut(path, names):
    """The module-level functions and assignments `names` of `path`, run in a
    namespace of their own (with `re`). Nothing else of the file executes."""
    tree = ast.parse(path.read_text())
    keep, found = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            keep.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & set(names):
                keep.append(node)
                found |= targets & set(names)
    missing = set(names) - found
    assert not missing, (f"{path.relative_to(ROOT)} no longer defines {sorted(missing)} - "
                         f"the rule moved or was renamed: point this test at its new home")
    ns = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(path), "exec"), ns)  # noqa: S102
    return ns


def holders():
    """{who: answer(name, text)} for every copy present in this checkout."""
    out = {"root rotation/material.py names_in": material.names_in}
    if HUNTER.is_file():
        ns = _cut(HUNTER, ["_VERSION_TAIL", "tokens", "word_run"])
        out["trend-hunter fetch_own_capture.py word_run"] = (
            lambda name, text, ns=ns: ns["word_run"](ns["tokens"](name), ns["tokens"](text)))
    else:
        print(f"   no {HUNTER.relative_to(ROOT)} here - the hunter's copy not compared")
    if RESEARCHER.is_file():
        ns = _cut(RESEARCHER, ["_WORD", "_VERSION_TAIL", "words", "space_names"])
        out["content-researcher demo_base.py space_names"] = ns["space_names"]
    else:
        print(f"   no {RESEARCHER.relative_to(ROOT)} here - the researcher's copy not compared")
    return out


def disagreements(answers):
    bad = []
    for name, text, want in EXAMPLES:
        said = {who: bool(fn(name, text)) for who, fn in answers.items()}
        if any(v != want for v in said.values()):
            bad.append(f"{name!r} in {text!r}: expected {want}, "
                       + ", ".join(f"{who} -> {v}" for who, v in said.items()))
    return bad


def test_every_copy_answers_the_examples_alike():
    bad = disagreements(holders())
    assert not bad, (
        "the Space-names-the-topic rule (CF-0832) answers differently in its copies - "
        "port the change to all three (root rotation/material.py, trend-hunter "
        "fetch_own_capture.py, content-researcher demo_base.py) or fix the example:\n     "
        + "\n     ".join(bad))


def test_the_root_rule_is_the_one_demo_base_reads():
    topic = {"title_ref": {"name": "OpenCode"},
             "evidence": {"footage_base": {"base": "own_capture"},
                          "footage_candidates": [{
                              "kind": "own_capture",
                              "video_id": "own_capture:opencoder",
                              "capture": {"space": "OpenCoder-LLM/OpenCoder-8B-Instruct"}}]}}
    assert material.demo_base(topic, ["own_capture-opencoder"]), \
        "demo_base took a recording of OpenCoder as OpenCode's demo base"
    topic["evidence"]["footage_candidates"][0]["capture"]["space"] = "sst/opencode"
    assert material.demo_base(topic, ["own_capture-opencoder"]) is None


def test_the_guard_fires_when_one_copy_is_edited_alone():
    """A copy that takes a prefix as the name (the pre-CF-0831 hunter) is caught."""
    def prefix_rule(name, text):
        flat = "".join(material.name_words(name))
        return bool(flat) and flat in "".join(material.name_words(text))
    bad = disagreements({"root": material.names_in, "drifted": prefix_rule})
    assert any("OpenCoder-LLM" in line and "drifted -> True" in line for line in bad), bad


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
