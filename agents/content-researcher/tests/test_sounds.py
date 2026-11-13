#!/usr/bin/env python3
"""CF-0068: the writer's half of the sound layer is held to inserts/sound.json.

Content Researcher writes `sounds[]` - an intent on a beat of the commentary,
no query - and only when both gates are on: the channel's
`insert_layers.sound.enabled` and the pattern's `sound_layer.allowed`. These
tests pin that `scripts/check_sounds.py` reads the vocabulary and the ceiling
from the root spec (no twin of the list in this repo), validates the shape
the Video Editor will read, refuses a writer choosing the file, and names the
gate when a request was written past one.

The channel config and the patterns are SYNTHETIC dicts here on purpose: a
shape test must hold whichever way the real channel's switch happens to be
set, so a valid request is exercised on a test config - the same rule
tests/test_reactions.py and the root's tests/test_insert_layers.py follow.
The vocabulary is the real one, read from inserts/sound.json, because that is
the contract. On example-film the layer is off today, and CF-0189 rewrote why:
shared/inserts/sounds/index.json carries entries: [] and the Video Editor's
half is unbuilt (executable_today: false, blocked_by CF-0068), with the
licensing question standing beside them on its own legs. The old reason "for
tone" went with the analyst-skeptic position CF-0181 replaced.
"""
import json
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-sounds-")
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import check_sounds as cs  # noqa: E402

ROOT = cs.find_root()
SPEC_FILE = ROOT / "inserts" / "sound.json"
SPEC = cs.load_spec(ROOT)
VOCAB = SPEC["vocabulary"]

CHANNEL = "test-channel"
CHANNEL_ON = {"insert_layers": {"sound": {"enabled": True}}}
CHANNEL_OFF = {"insert_layers": {"sound": {"enabled": False}}}
# a channel with only the meme switched on has not switched the sound on
CHANNEL_MEME_ONLY = {"insert_layers": {"meme": {"enabled": True}}}
PATTERNS = {
    "explainer": {"sound_layer": {"allowed": True, "reason": "synthetic: tolerates it"},
                  "meme_layer": {"allowed": True, "reason": "synthetic"}},
    "contrast": {"sound_layer": {"allowed": False, "reason": "synthetic: refuses it"}},
    "meme-only": {"meme_layer": {"allowed": True, "reason": "synthetic: says nothing about sound"}},
    "unanswered": {},
}

COMMENTARY = ("Deadline says September sixteenth. The trailer's only date card says "
              "this summer. So the date is the outlet's, not the studio's. Which is "
              "a strange thing to print as news.")


def _sound(**over):
    s = {"beat_id": "s1", "intent": VOCAB[0],
         "beat_text": "Which is a strange thing to print as news."}
    s.update(over)
    return s


def _script(sounds=None, pattern_id="explainer", script_id="s1", commentary=COMMENTARY, **extra):
    s = {"script_id": script_id, "hook": "A date nobody announced.",
         "commentary": commentary, "payoff": "Check the card, not the headline.",
         "pattern": {"pattern_id": pattern_id}}
    if sounds is not None:
        s["sounds"] = sounds
    s.update(extra)
    return s


def _problems(script, channel_cfg=CHANNEL_ON, patterns=PATTERNS):
    return cs.check_batch_data({"scripts": [script]}, SPEC, channel_cfg, patterns,
                               CHANNEL, out=lambda *_: None)


def _one_problem_naming(script, field, **kw):
    problems = _problems(script, **kw)
    assert problems, f"expected a problem naming {field!r}, got none"
    assert any(field in p for p in problems), (field, problems)
    return problems


# --------------------------------------------------------------------------
# where the vocabulary comes from
# --------------------------------------------------------------------------

def test_vocabulary_and_ceiling_come_from_the_root_spec_not_from_this_repo():
    raw = json.loads(SPEC_FILE.read_text())
    sel = raw["selection"]
    assert VOCAB == sorted(sel["intent_vocabulary"])
    assert SPEC["max"] == sel["max_sounds_per_script"]
    assert SPEC["field"] == sel["script_field"] == "sounds"
    assert list(SPEC["protected"]) == raw["placement"]["protected_sections"]
    src = (AGENT_ROOT / "scripts" / "check_sounds.py").read_text()
    code = src.split('"""', 2)[2]  # everything after the module docstring
    for intent in sel["intent_vocabulary"]:
        assert f'"{intent}"' not in code and f"'{intent}'" not in code, \
            f"{intent} is hardcoded in check_sounds.py"


def test_the_spec_is_the_one_the_task_named():
    # The fifteen intents of the 2026-09-05 decision; if the spec grows, this
    # test grows with it - the checker itself must not care.
    for intent in ("slip", "record_scratch", "vine_boom", "airhorn"):
        assert intent in VOCAB, (intent, VOCAB)
    assert SPEC["max"] >= 1
    assert "hook" in SPEC["protected"] and "payoff" in SPEC["protected"]


# --------------------------------------------------------------------------
# a valid script, and the two ways of asking for nothing
# --------------------------------------------------------------------------

def test_a_valid_request_passes_on_a_channel_with_the_layer_on():
    s = _script([_sound(), _sound(beat_id="s2", intent=VOCAB[1],
                                  beat_text="Deadline says September sixteenth.")])
    assert _problems(s) == []


def test_absent_field_and_empty_list_pass_whatever_the_gates_say():
    for cfg in (CHANNEL_ON, CHANNEL_OFF, CHANNEL_MEME_ONLY, {}):
        for pid in PATTERNS:
            assert _problems(_script(None, pattern_id=pid), cfg) == []
            assert _problems(_script([], pattern_id=pid), cfg) == []


def test_a_sound_may_share_a_beat_and_a_beat_id_with_a_reaction():
    # sounds[] is its own namespace: the same beat_id and the same words as a
    # reactions[] entry are fine, and the checker never reads reactions[]
    reaction = {"beat_id": "s1", "intent": "facepalm",
                "beat_text": "Which is a strange thing to print as news.", "query": None}
    assert _problems(_script([_sound()], reactions=[reaction])) == []


# --------------------------------------------------------------------------
# the gates
# --------------------------------------------------------------------------

def test_sounds_on_a_channel_with_the_switch_off_fail_naming_layer_off():
    problems = _one_problem_naming(_script([_sound()]), "insert_layers.sound.enabled",
                                   channel_cfg=CHANNEL_OFF)
    assert any(cs.GATE_LAYER_OFF in p for p in problems), problems


def test_a_channel_without_the_block_counts_as_off():
    assert _one_problem_naming(_script([_sound()]), cs.GATE_LAYER_OFF, channel_cfg={})
    # the meme switch is not the sound switch
    assert _one_problem_naming(_script([_sound()]), cs.GATE_LAYER_OFF,
                               channel_cfg=CHANNEL_MEME_ONLY)


def test_sounds_on_a_pattern_that_refuses_fail_naming_pattern_refused():
    problems = _one_problem_naming(_script([_sound()], pattern_id="contrast"),
                                   "sound_layer.allowed")
    assert any(cs.GATE_PATTERN_REFUSED in p for p in problems), problems
    # a pattern that never answered is refused, not assumed - and a pattern
    # that answered only for the meme has not answered for the sound
    for pid in ("unanswered", "meme-only"):
        assert any(cs.GATE_PATTERN_REFUSED in p
                   for p in _problems(_script([_sound()], pattern_id=pid))), pid


def test_a_script_without_a_pattern_cannot_be_gated_and_fails():
    s = _script([_sound()])
    del s["pattern"]
    _one_problem_naming(s, "pattern.pattern_id")


def test_both_gates_off_name_both():
    problems = _problems(_script([_sound()], pattern_id="contrast"), CHANNEL_OFF)
    assert any(cs.GATE_LAYER_OFF in p for p in problems), problems
    assert any(cs.GATE_PATTERN_REFUSED in p for p in problems), problems


# --------------------------------------------------------------------------
# the shape, one violation at a time, each message naming the field
# --------------------------------------------------------------------------

def test_not_a_list_fails():
    _one_problem_naming(_script({"beat_id": "s1"}), "sounds: must be a list")


def test_more_than_the_ceiling_fails():
    many = [_sound(beat_id=f"s{i}") for i in range(SPEC["max"] + 1)]
    _one_problem_naming(_script(many), "max_sounds_per_script")


def test_unknown_intent_fails_naming_the_field():
    _one_problem_naming(_script([_sound(intent="eyeroll")]), "sounds[0].intent")
    # a tag of an intent is not the intent
    _one_problem_naming(_script([_sound(intent="slide_whistle")]), "sounds[0].intent")


def test_duplicate_beat_id_fails():
    s = _script([_sound(), _sound(beat_text="Deadline says September sixteenth.")])
    problems = _one_problem_naming(s, "sounds[1].beat_id")
    assert any("not unique" in p for p in problems), problems


def test_malformed_beat_id_fails():
    for bad in ("S1", "-s1", "s 1", "", 7, None):
        _one_problem_naming(_script([_sound(beat_id=bad)]), "sounds[0].beat_id")


def test_beat_text_must_be_a_verbatim_substring_of_the_commentary():
    _one_problem_naming(_script([_sound(beat_text="Which is a strange thing to print as NEWS.")]),
                        "sounds[0].beat_text")
    _one_problem_naming(_script([_sound(beat_text="")]), "sounds[0].beat_text")
    _one_problem_naming(_script([_sound(beat_text=None)]), "sounds[0].beat_text")


def test_a_beat_on_the_hook_or_the_payoff_is_named_as_protected():
    for words, section in (("A date nobody announced.", "hook"),
                           ("Check the card, not the headline.", "payoff")):
        problems = _one_problem_naming(_script([_sound(beat_text=words)]), "sounds[0].beat_text")
        assert any(f"`{section}`" in p and "protected" in p for p in problems), problems


def test_missing_required_keys_are_named_one_by_one():
    problems = _problems(_script([{}]))
    for k in cs.REQUIRED_KEYS:
        assert any(f"sounds[0].{k}: missing" in p for p in problems), (k, problems)


def test_a_query_a_file_name_or_an_id_in_the_script_fails():
    # there is no query for a sound, and no key that names the file
    for extra in ({"query": "slide whistle"}, {"query": None}, {"asset_id": "boing-01"},
                  {"file": "boing.wav"}, {"path": "sounds/boing.wav"}, {"tags": ["boing"]}):
        problems = _one_problem_naming(_script([_sound(**extra)]), "unknown key")
        assert any("Video Editor" in p for p in problems), problems
    # and a good entry stays good
    assert _problems(_script([_sound()])) == []


def test_a_non_object_entry_fails():
    _one_problem_naming(_script(["bonk"]), "sounds[0]: must be an object")


# --------------------------------------------------------------------------
# the CLI on the real root: the real channel is off, so the exit code follows
# --------------------------------------------------------------------------

def _tmp(data):
    p = Path(tempfile.mkdtemp(dir=_TMP)) / "03-content-researcher.json"
    p.write_text(json.dumps(data))
    return p




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
