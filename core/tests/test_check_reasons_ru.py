"""CF-0657: every check of a channel config has a stable code and a Russian
text for the command center (`inserts/validate_inserts.py` CHECK_REASONS_RU).

The English line stays what it was - journals, tests and `main()` read it;
the center shows `text_ru`. A check added to CHANNEL_CHECKS or to
`validate_vocabulary()` without its Russian row fails here, and fails at run
time too (`check_findings` raises KeyError). Stand-ins only: the configs are
copies in a tmp tree.
"""
import copy
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inserts"))
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "tests"))

import validate_inserts as vi  # noqa: E402
from _tmproot import tmp_root  # noqa: E402

TMP = tmp_root("check-reasons-ru-")

CYRILLIC = re.compile(r"[а-яё]", re.I)


def test_every_check_has_a_russian_row():
    names = set(vi.VOCABULARY_CHECKS) | {c for _, c, _ in vi.CHANNEL_CHECKS} | {
        vi.CONFIG_IS_OBJECT, vi.FACT_SOURCES_PARSE, vi.RUN_PLAN_CHECK} | set(vi.NEW_CHANNEL_CHECKS)
    missing = sorted(names - set(vi.CHECK_REASONS_RU))
    assert not missing, f"checks without a Russian text: {missing}"
    stray = sorted(set(vi.CHECK_REASONS_RU) - names)
    assert not stray, f"Russian rows of no check: {stray}"


def test_vocabulary_checks_cover_the_channel_table():
    assert set(c for _, c, _ in vi.CHANNEL_CHECKS) <= set(vi.VOCABULARY_CHECKS)


def test_rows_are_short_russian_and_codes_stable():
    codes = [row[0] for row in vi.CHECK_REASONS_RU.values()]
    assert len(codes) == len(set(codes)), "a code names one check"
    for check, (code, title, reason) in vi.CHECK_REASONS_RU.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), (check, code)
        for part in (title, reason):
            assert part.strip() and CYRILLIC.search(part), (check, part)
            assert not re.search(r"\b(?:CF|CC)-\d", part), (check, part)
            assert "/" not in part and ".py" not in part, (check, part)
        assert len(title) + len(reason) < 200, check


def test_a_check_without_its_row_cannot_report():
    try:
        vi.check_findings("validate_brand_new_block", [])
    except KeyError:
        return
    raise AssertionError("a check with no Russian row reported")




def _cfg(path):
    return json.loads(path.read_text(encoding="utf-8"))








def test_other_lines_of_the_vocabulary():
    ins = vi.check_finding("validate_insert", "insert proof: missing required field(s) ['x']")
    assert ins["code"] == "insert_invalid" and "слой proof" in ins["text_ru"]
    pat = vi.check_finding("validate_pattern_layer_fields",
                           "patterns/explainer.json.meme_layer: needs a reason")
    assert "explainer.json" in pat["text_ru"] and "meme_layer" in pat["text_ru"]
    rp = vi.check_finding(vi.RUN_PLAN_CHECK, "run_plan.stages[2]: bad")
    assert rp["code"] == "run_plan_invalid" and "run_plan.stages[2]" in rp["text_ru"]


# --------------------------------------------------------------------------
# CF-0672: the new channel's and the position's checks (shared/new_channel.py)
# --------------------------------------------------------------------------

def _nc():
    spec = importlib.util.spec_from_file_location("new_channel_reasons_test",
                                                  ROOT / "shared" / "new_channel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_position_s_lines_have_a_code_and_russian():
    nc = _nc()
    (obj,) = nc.stance_findings("abc", ["not", "an", "object"])
    assert obj["check"] == vi.STANCE_CHECK and obj["code"] == "stance_invalid"
    assert obj["text"] == "stance.json: is not a JSON object" and CYRILLIC.search(obj["text_ru"])
    (wrong,) = nc.stance_findings("abc", {"channel_id": "xyz"})
    assert wrong["code"] == "stance_invalid"
    assert "поле channel_id" in wrong["text_ru"] and "'xyz'" in wrong["text_ru"]
    assert nc.stance_findings("abc", {"channel_id": "abc"}) == []
    stance, (bad,) = nc.stance_text_findings("abc", "{not json")
    assert stance is None and bad["check"] == vi.STANCE_PARSE_CHECK
    assert bad["code"] == "stance_unreadable" and "файл stance.json" in bad["text_ru"]
    stance, found = nc.stance_text_findings("abc", '{"channel_id": "abc"}')
    assert stance == {"channel_id": "abc"} and found == []


def test_the_template_s_own_lines_have_a_code_and_russian():
    nc = _nc()
    assert nc.stance_path_errors("abc", {"stance": "abc/stance.json"}) == []
    for cfg in ({}, {"stance": ""}, {"stance": "other/stance.json"}):
        (line,) = nc.stance_path_errors("abc", cfg)
        (f,) = vi.check_findings(vi.TEMPLATE_STANCE_PATH_CHECK, [line])
        assert f["code"] == "template_stance_path" and f["text_ru"].startswith("Шаблон нового канала")
    stub = vi.check_finding(vi.TEMPLATE_STUB_CHECK,
                            "abc.json: the template made a channel with a pipeline - a new "
                            "channel starts without one (status: no_pipeline)")
    assert stub["code"] == "template_has_pipeline" and CYRILLIC.search(stub["text_ru"])


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
