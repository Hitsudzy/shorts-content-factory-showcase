#!/usr/bin/env python3
"""CF-0552: the writer's half of `claims[]` - what SKILL.md tells the writer
to write is what the root's mechanics (`shared/factrule/claims.py`) accept.

Pinned here: the example entries of the 03 shape in SKILL.md are well formed
by the root's own `shape_problems`; every violation code the root can print
is explained in step 6, so a `FAIL` line never names a code the writer was
not told about; the command step 6 gives exists at the root; and the rule's
cases of the grill (East of Eden's "before anyone outside the production
knew", hearsay) are in the text. Offline, no batch is read."""
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from check_narration_budget import find_root  # noqa: E402

ROOT = find_root()
SKILL = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text(
    encoding="utf-8")
RULE_PATH = ROOT / "shared" / "factrule" / "claims.py"


def _rule():
    spec = importlib.util.spec_from_file_location("claims_cr_pin", RULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _example_claims():
    m = re.search(r'^( +)"claims": (\[.*?^\1\]),?$', SKILL, re.S | re.M)
    assert m, "no `\"claims\": [...]` in the 03 example of SKILL.md"
    return json.loads(m.group(2))


def test_the_example_is_what_the_rule_accepts():
    cl = _rule()
    claims = _example_claims()
    assert len(claims) >= 2
    kinds = set()
    for c in claims:
        assert cl.shape_problems(c) == [], (c, cl.shape_problems(c))
        kinds |= {"quote" if "quote" in s else "shot" for s in c["support"]}
    assert kinds == {"quote", "shot"}, "the example shows both footings"


def test_every_code_the_check_prints_is_explained():
    cl = _rule()
    missing = [c for c in cl.FAIL_CODES if f"`{c}`" not in SKILL]
    assert not missing, f"codes the check prints that SKILL.md never explains: {missing}"
    assert f"`{cl.PENDING_NO_PLAN}`" in SKILL or "pending no_plan" in SKILL
    # CF-0689: a claim on a graphic is checked by the root's own-graphic rule
    # too (`scripts/check_graphics.py`), and its codes are explained the same way.
    og_path = ROOT / "shared" / "own_graphic.py"
    if og_path.is_file():
        spec = importlib.util.spec_from_file_location("own_graphic_cr_pin", og_path)
        og = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(og)
        missing = [c for c in og.FAIL_CODES if f"`{c}`" not in SKILL]
        assert not missing, f"graphic codes SKILL.md never explains: {missing}"
        assert "graphic:<graphic_id>" in SKILL
        # CF-0690: an `api_chat` is held to its call's record - every chat code
        # (the claim rule's `api_demo_answer_is_fact` among them) is explained too.
        missing = [c for c in getattr(og, "CHAT_CODES", ()) if f"`{c}`" not in SKILL]
        assert not missing, f"api_chat codes SKILL.md never explains: {missing}"
    missing = [c for c in getattr(cl, "API_DEMO_CODES", ()) if f"`{c}`" not in SKILL]
    assert not missing, f"API-demo claim codes SKILL.md never explains: {missing}"


def test_the_command_and_the_rule_are_there():
    assert RULE_PATH.is_file(), RULE_PATH
    assert "shared/factrule/claims.py" in SKILL
    for words in ("before anyone outside the production knew", "An exaggeration is a claim",
                  "reportedly", "copied, never reworded", "on screen under those words",
                  "CF-0553"):
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
