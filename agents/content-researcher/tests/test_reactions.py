#!/usr/bin/env python3
"""CF-0067: the writer's half of the meme layer is held to inserts/meme.json.

Content Researcher writes `reactions[]` - an intent on a beat of the
commentary - and only when both gates are on: the channel's
`insert_layers.meme.enabled` and the pattern's `meme_layer.allowed`. These
tests pin that `scripts/check_reactions.py` reads the vocabulary and the
ceiling from the root spec (no twin of the list in this repo), validates the
shape the Video Editor will read, and names the gate when a request was
written past one.

The channel config and the patterns are SYNTHETIC dicts here on purpose: a
shape test must hold whichever way the real channel's switch happens to be
set that week, so both gates are exercised on test configs - the same rule
the root's tests/test_insert_layers.py follows. The vocabulary is the real
one, read from inserts/meme.json, because that is the contract. Only the one
CLI test at the bottom touches the real channel, and it reads that switch off
disk rather than pinning a value (CF-0189: example-film's meme layer went on
2026-09-11, and the pinned `False` here went red the same day).
"""
import json
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-reactions-")
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import check_reactions as cr  # noqa: E402

ROOT = cr.find_root()
SPEC_FILE = ROOT / "inserts" / "meme.json"
SPEC = cr.load_spec(ROOT)
VOCAB = SPEC["vocabulary"]

CHANNEL = "test-channel"
CHANNEL_ON = {"insert_layers": {"meme": {"enabled": True}}}
CHANNEL_OFF = {"insert_layers": {"meme": {"enabled": False}}}
PATTERNS = {
    "explainer": {"meme_layer": {"allowed": True, "reason": "synthetic: tolerates it"}},
    "contrast": {"meme_layer": {"allowed": False, "reason": "synthetic: refuses it"}},
    "unanswered": {},
}

COMMENTARY = ("Deadline says September sixteenth. The trailer's only date card says "
              "this summer. So the date is the outlet's, not the studio's. Which is "
              "a strange thing to print as news. Nobody at the studio has said a word "
              "about it since.")
# CF-0811: the default beat ("Which is a strange ...") has 20 words of
# commentary after its first word - room for a 3 s block at any rate up to
# 6.6 w/s; the sentence after it is there for that.


def _reaction(**over):
    r = {"beat_id": "r1", "intent": VOCAB[0],
         "beat_text": "Which is a strange thing to print as news.", "query": None}
    r.update(over)
    return r


def _script(reactions=None, pattern_id="explainer", script_id="s1", commentary=COMMENTARY):
    s = {"script_id": script_id, "hook": "A date nobody announced.",
         "commentary": commentary, "payoff": "Check the card, not the headline.",
         "pattern": {"pattern_id": pattern_id}}
    if reactions is not None:
        s["reactions"] = reactions
    return s


def _problems(script, channel_cfg=CHANNEL_ON, patterns=PATTERNS, library_ids=()):
    return cr.check_batch_data({"scripts": [script]}, SPEC, channel_cfg, patterns,
                               CHANNEL, library_ids, out=lambda *_: None)


def _one_problem_naming(script, field, **kw):
    problems = _problems(script, **kw)
    assert problems, f"expected a problem naming {field!r}, got none"
    assert any(field in p for p in problems), (field, problems)
    return problems


# --------------------------------------------------------------------------
# where the vocabulary comes from
# --------------------------------------------------------------------------

def test_vocabulary_and_ceiling_come_from_the_root_spec_not_from_this_repo():
    raw = json.loads(SPEC_FILE.read_text())["selection"]
    assert VOCAB == sorted(raw["intent_vocabulary"])
    assert SPEC["max"] == raw["max_reactions_per_script"]
    assert SPEC["field"] == raw["script_field"] == "reactions"
    src = (AGENT_ROOT / "scripts" / "check_reactions.py").read_text()
    code = src.split('"""', 2)[2]  # everything after the module docstring
    for intent in raw["intent_vocabulary"]:
        assert f'"{intent}"' not in code and f"'{intent}'" not in code, \
            f"{intent} is hardcoded in check_reactions.py"


def test_the_spec_is_the_one_the_task_named():
    # The eleven intents of the 2026-09-05 decision; if the spec grows, this
    # test grows with it - the checker itself must not care.
    for intent in ("facepalm", "disbelief", "shock", "iceberg"):
        assert intent in VOCAB, (intent, VOCAB)
    assert SPEC["max"] >= 1


# --------------------------------------------------------------------------
# a valid script, and the two ways of asking for nothing
# --------------------------------------------------------------------------

def test_a_valid_request_passes_on_a_channel_with_the_layer_on():
    s = _script([_reaction(), _reaction(beat_id="r2", intent=VOCAB[1],
                                        beat_text="Deadline says September sixteenth.",
                                        query="a person squinting at a newspaper")])
    assert _problems(s) == []


def test_absent_field_and_empty_list_pass_where_a_gate_is_closed():
    # CF-0811: zero is clean on its own only where a gate answers it - the
    # switch off, or a pattern that refuses (or cannot be read).
    for cfg, pid in ((CHANNEL_OFF, "explainer"), (CHANNEL_OFF, "contrast"),
                     (CHANNEL_OFF, "unanswered"), (CHANNEL_ON, "contrast"),
                     (CHANNEL_ON, "unanswered")):
        assert _problems(_script(None, pattern_id=pid), cfg) == [], (cfg, pid)
        assert _problems(_script([], pattern_id=pid), cfg) == [], (cfg, pid)


def test_zero_with_both_gates_open_and_no_reason_fails_meme_missing():
    for empty in (None, []):
        problems = _problems(_script(empty))
        assert len(problems) == 1 and cr.CODE_MISSING in problems[0], problems
        assert cr.NONE_REASON_KEY in problems[0]


def _with_reason(reason, reactions=None, **kw):
    s = _script(reactions, **kw)
    s[cr.NONE_REASON_KEY] = reason
    return s


def test_zero_with_a_judgment_reason_passes():
    for reason in (cr.REASON_NO_FITTING_MEME, cr.REASON_TONE):
        assert _problems(_with_reason(reason)) == [], reason
        assert _problems(_with_reason(reason, [])) == [], reason


def test_the_reason_set_is_closed():
    problems = _problems(_with_reason("not_funny"))
    assert len(problems) == 1 and "not one of" in problems[0], problems
    assert set(cr.NONE_REASONS) == {"layer_off", "pattern_forbids", "no_room",
                                    "no_fitting_meme", "tone"}


def test_a_gate_reason_on_an_open_gate_fails():
    for reason in cr.GATE_REASONS:
        problems = _problems(_with_reason(reason))
        assert problems and cr.CODE_MISSING in problems[0], (reason, problems)


def test_a_gate_reason_must_name_the_gate_that_is_closed():
    assert _problems(_with_reason("layer_off"), CHANNEL_OFF) == []
    assert _problems(_with_reason("pattern_forbids", pattern_id="contrast")) == []
    assert _problems(_with_reason("pattern_forbids"), CHANNEL_OFF)       # the switch is the gate
    assert _problems(_with_reason("layer_off", pattern_id="contrast"))   # the pattern is
    # a judgment code where a gate is closed is not wrong, only replaced by --write
    assert _problems(_with_reason("tone"), CHANNEL_OFF) == []


def test_no_room_is_checked_against_the_commentary():
    assert any("there is room" in p for p in _problems(_with_reason("no_room")))
    short = _with_reason("no_room", commentary="Deadline says September sixteenth.")
    assert _problems(short) == []


def test_a_reason_beside_reactions_fails():
    problems = _problems(_with_reason("tone", [_reaction()]))
    assert len(problems) == 1 and "beside 1 reaction" in problems[0], problems


def test_more_than_two_still_fails_and_one_or_two_pass():
    assert _problems(_script([_reaction()])) == []
    many = [_reaction(beat_id=f"r{i}") for i in range(3)]
    assert any("max_reactions_per_script" in p for p in _problems(_script(many)))


# --------------------------------------------------------------------------
# CF-0811: the spot - a block of the floor after the beat's first word
# --------------------------------------------------------------------------

def test_a_beat_too_close_to_the_end_of_the_commentary_fails():
    late = _reaction(beat_text="Nobody at the studio has said a word")   # 11 words to the end
    problems = _problems(_script([late]))
    assert len(problems) == 1 and cr.CODE_SPOT_SHORT in problems[0], problems
    assert "needs 12" in problems[0] and "fallback" in problems[0], problems


def test_the_spot_is_read_at_the_script_s_own_rate():
    late = _reaction(beat_text="Nobody at the studio has said a word")
    s = _script([late])
    s["narration"] = {"estimated_words_per_second": 3.3, "words_per_second": 3.66}
    assert _problems(s) == []                      # ceil(3.0 * 3.3) = 10 <= 11
    s["narration"] = {"estimated_words_per_second": None, "words_per_second": 3.9}
    assert any("needs 12" in p and "narration.words_per_second" in p for p in _problems(s))
    assert cr.spot_words(s, SPEC)[0] == 12
    assert cr.spot_words(_script(None), dict(SPEC, min_block_seconds=3.0))[0] == 12


def test_the_floor_comes_from_the_spec_placement():
    raw = json.loads(SPEC_FILE.read_text())
    assert SPEC["min_block_seconds"] == float(raw["placement"]["min_block_seconds"])


def test_two_beats_too_close_together_fail():
    r1 = _reaction(beat_text="Deadline says September sixteenth.")
    r2 = _reaction(beat_id="r2", beat_text="The trailer's only date card says")   # 4 words on
    problems = _problems(_script([r1, r2]))
    assert len(problems) == 1 and cr.CODE_TOO_CLOSE in problems[0], problems


# --------------------------------------------------------------------------
# CF-0811: --write stamps the gate codes, and only those
# --------------------------------------------------------------------------

def test_write_stamps_the_closed_gate_and_nothing_else():
    data = {"scripts": [
        _script(None, script_id="off"),
        _script([], pattern_id="contrast", script_id="refused"),
        _with_reason("tone", script_id="judged"),
        _script([_reaction()], script_id="asked"),
        _script(None, pattern_id="no-such-pattern", script_id="unknown"),
    ]}
    changed = cr.stamp_gate_reasons(data, SPEC, CHANNEL_ON, PATTERNS)
    by = {s["script_id"]: s for s in data["scripts"]}
    assert changed == ["refused"], changed
    assert by["refused"][cr.NONE_REASON_KEY] == "pattern_forbids"
    assert by["judged"][cr.NONE_REASON_KEY] == "tone"
    for sid in ("off", "asked", "unknown"):
        assert cr.NONE_REASON_KEY not in by[sid], sid
    changed = cr.stamp_gate_reasons(data, SPEC, CHANNEL_OFF, PATTERNS)
    assert set(changed) == {"off", "refused", "judged", "unknown"}, changed
    assert all(by[x][cr.NONE_REASON_KEY] == "layer_off" for x in changed)
    assert cr.NONE_REASON_KEY not in by["asked"]


def test_query_may_be_omitted_entirely():
    r = _reaction()
    del r["query"]
    assert _problems(_script([r])) == []


# --------------------------------------------------------------------------
# the gates
# --------------------------------------------------------------------------

def test_reactions_on_a_channel_with_the_switch_off_fail_naming_layer_off():
    problems = _one_problem_naming(_script([_reaction()]), "insert_layers.meme.enabled",
                                   channel_cfg=CHANNEL_OFF)
    assert any(cr.GATE_LAYER_OFF in p for p in problems), problems


def test_a_channel_without_the_block_counts_as_off():
    problems = _one_problem_naming(_script([_reaction()]), cr.GATE_LAYER_OFF, channel_cfg={})
    assert problems


def test_reactions_on_a_pattern_that_refuses_fail_naming_pattern_refused():
    problems = _one_problem_naming(_script([_reaction()], pattern_id="contrast"),
                                   "meme_layer.allowed")
    assert any(cr.GATE_PATTERN_REFUSED in p for p in problems), problems
    # and a pattern that never answered is refused, not assumed
    assert any(cr.GATE_PATTERN_REFUSED in p
               for p in _problems(_script([_reaction()], pattern_id="unanswered")))


def test_a_script_without_a_pattern_cannot_be_gated_and_fails():
    s = _script([_reaction()])
    del s["pattern"]
    _one_problem_naming(s, "pattern.pattern_id")


def test_both_gates_off_name_both():
    problems = _problems(_script([_reaction()], pattern_id="contrast"), CHANNEL_OFF)
    assert any(cr.GATE_LAYER_OFF in p for p in problems), problems
    assert any(cr.GATE_PATTERN_REFUSED in p for p in problems), problems


# --------------------------------------------------------------------------
# the shape, one violation at a time, each message naming the field
# --------------------------------------------------------------------------

def test_not_a_list_fails():
    _one_problem_naming(_script({"beat_id": "r1"}), "reactions: must be a list")


def test_more_than_the_ceiling_fails():
    many = [_reaction(beat_id=f"r{i}") for i in range(SPEC["max"] + 1)]
    _one_problem_naming(_script(many), "max_reactions_per_script")


def test_unknown_intent_fails_naming_the_field():
    _one_problem_naming(_script([_reaction(intent="eyeroll")]), "reactions[0].intent")


def test_duplicate_beat_id_fails():
    s = _script([_reaction(), _reaction(beat_text="Deadline says September sixteenth.")])
    problems = _one_problem_naming(s, "reactions[1].beat_id")
    assert any("not unique" in p for p in problems), problems


def test_malformed_beat_id_fails():
    for bad in ("R1", "-r1", "r 1", "", 7, None):
        _one_problem_naming(_script([_reaction(beat_id=bad)]), "reactions[0].beat_id")


def test_beat_text_must_be_a_verbatim_substring_of_the_commentary():
    _one_problem_naming(_script([_reaction(beat_text="Which is a strange thing to print as NEWS.")]),
                        "reactions[0].beat_text")
    _one_problem_naming(_script([_reaction(beat_text="")]), "reactions[0].beat_text")
    # the hook is not the commentary: a beat on it is not anchorable
    _one_problem_naming(_script([_reaction(beat_text="A date nobody announced.")]),
                        "reactions[0].beat_text")


def _warnings(script):
    lines = []
    problems = cr.check_batch_data({"scripts": [script]}, SPEC, CHANNEL_ON, PATTERNS,
                                   CHANNEL, (), out=lines.append)
    return problems, [ln for ln in lines if ln.startswith("  warn ")]


def test_beat_text_length_outside_three_to_eight_words_warns_but_does_not_fail():
    # CF-0388: the beat is the meme's selection key; a whole sentence is a
    # warning, not a failure - old batches wrote whole sentences.
    long_beat = "The trailer's only date card says this summer. So"   # 9 words
    problems, warns = _warnings(_script([_reaction(beat_text=long_beat)]))
    assert problems == [] and len(warns) == 1, (problems, warns)
    assert "reactions[0].beat_text: 9 words, too long" in warns[0]
    problems, warns = _warnings(_script([_reaction(beat_text="strange thing")]))
    assert problems == [] and len(warns) == 1 and "too short" in warns[0], (problems, warns)
    for ok in ("strange thing to print", "strange thing to print as news."):
        problems, warns = _warnings(_script([_reaction(beat_text=ok)]))
        assert problems == [] and warns == [], (ok, problems, warns)


def test_a_malformed_beat_text_is_a_problem_not_also_a_warning():
    problems, warns = _warnings(_script([_reaction(beat_text="")]))
    assert problems and warns == []


def test_missing_required_keys_are_named_one_by_one():
    problems = _problems(_script([{}]))
    for k in cr.REQUIRED_KEYS:
        assert any(f"reactions[0].{k}: missing" in p for p in problems), (k, problems)


def test_a_file_name_or_id_in_the_script_fails():
    # a query that is a file, a path, or an id-shaped token
    for q in ("facepalm.png", "memes/picard.gif", "meme-0007", "img_12"):
        problems = _one_problem_naming(_script([_reaction(query=q)]), "reactions[0].query")
        assert any("Video Editor" in p for p in problems), problems
    # a query equal to a library id, when the checker knows the library
    _one_problem_naming(_script([_reaction(query="chelovechek")]), "reactions[0].query",
                        library_ids=frozenset({"chelovechek"}))
    # a key that names a file outright
    _one_problem_naming(_script([_reaction(asset_id="chelovechek")]), "unknown key")
    _one_problem_naming(_script([_reaction(file="x.gif")]), "unknown key")


def test_free_text_queries_pass():
    for q in ("a person covering their face", "iceberg", "two doors, one figure torn"):
        assert _problems(_script([_reaction(query=q)])) == [], q


def test_empty_or_non_string_query_fails():
    for q in ("", "   ", 3):
        _one_problem_naming(_script([_reaction(query=q)]), "reactions[0].query")


# --------------------------------------------------------------------------
# the CLI on the real root: whatever the real channel's switch says today,
# the exit code follows it
# --------------------------------------------------------------------------

def _tmp(data):
    p = Path(tempfile.mkdtemp(dir=_TMP)) / "03-content-researcher.json"
    p.write_text(json.dumps(data))
    return p




def test_cli_write_stamps_the_gate_into_the_file_and_only_then_rewrites_it():
    """CF-0811: `--write` puts the closed gate's code on a zero script; a
    batch with nothing to stamp is left byte for byte."""
    real = "example-film"
    on_disk = cr.channel_switch(cr.load_channel_config(real, ROOT))
    path = _tmp({"channel": real, "scripts": [_script(None, pattern_id="contrast")]})
    assert cr.main([str(path), "--root", str(ROOT)]) == 0
    assert cr.NONE_REASON_KEY not in json.loads(path.read_text())["scripts"][0]
    assert cr.main([str(path), "--root", str(ROOT), "--write"]) == 0
    got = json.loads(path.read_text())["scripts"][0][cr.NONE_REASON_KEY]
    assert got == ("pattern_forbids" if on_disk else "layer_off"), got
    before = path.read_text()
    assert cr.main([str(path), "--root", str(ROOT), "--write"]) == 0
    assert path.read_text() == before


def test_the_skill_documents_every_reason_code_and_runs_the_check_with_write():
    """CF-0811: the writer reads the closed set and the codes the check
    prints in SKILL.md, and step 6 runs the check with --write so the gate
    codes land in the file."""
    skill = (AGENT_ROOT / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    for code in list(cr.NONE_REASONS) + [cr.CODE_MISSING, cr.CODE_SPOT_SHORT, cr.CODE_TOO_CLOSE,
                                         cr.NONE_REASON_KEY]:
        assert f"`{code}`" in skill, code
    assert "03-content-researcher.json --write" in skill.split("check_reactions.py \\")[1][:200]


def test_library_ids_are_read_when_the_index_is_on_disk():
    ids = cr.library_asset_ids(ROOT)
    index = ROOT / "shared" / "inserts" / "memes" / "index.json"
    if not index.exists():
        assert ids == ()
        return
    entries = json.loads(index.read_text())["entries"]
    assert all(e["id"] in ids for e in entries if "id" in e)


def test_a_channel_bank_is_the_library_whose_ids_are_read():
    """CF-0393: a channel that names its own bank (insert_layers.meme.bank)
    has its ids read from that bank, not from the default folder; a named
    bank missing on a channel whose layer is on ends the check (the Video
    Editor would refuse it); a malformed name always does."""
    root = Path(tempfile.mkdtemp(dir=_TMP))
    for name, ids in (("memes", ["cinema-only"]), ("memes-tech", ["tech-only"])):
        (root / "shared" / "inserts" / name).mkdir(parents=True)
        (root / "shared" / "inserts" / name / "index.json").write_text(json.dumps(
            {"entries": [{"id": i, "file": f"{i}.png"} for i in ids]}))
    tech = {"insert_layers": {"meme": {"enabled": True, "bank": "shared/inserts/memes-tech/"}}}
    got = cr.library_asset_ids(root, tech)
    assert "tech-only" in got and "cinema-only" not in got, got
    assert "cinema-only" in cr.library_asset_ids(root, CHANNEL_ON)
    gone_on = {"insert_layers": {"meme": {"enabled": True, "bank": "memes-gone"}}}
    gone_off = {"insert_layers": {"meme": {"enabled": False, "bank": "memes-gone"}}}
    assert cr.library_asset_ids(root, gone_off) == ()
    for bad in (gone_on, {"insert_layers": {"meme": {"enabled": False, "bank": "shared/footage/"}}}):
        try:
            cr.library_asset_ids(root, bad)
        except cr.nw.CannotAnswer:
            continue
        raise AssertionError(f"{bad} was read")


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
