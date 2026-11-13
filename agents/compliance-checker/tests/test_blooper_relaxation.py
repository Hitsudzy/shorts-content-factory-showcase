#!/usr/bin/env python3
"""CF-0190 part 2: the Compliance Checker's half of the blooper relaxation.

What this file demonstrates, in the order the contract states it
(`tasks/CF-0190-blooper-rights-relaxation.md`, `## Контракт маркера и границ`):

* the switch decides - off, there is no relaxation at all; on, marked
  material and nothing else is relaxed. Both sides are proven on configs of
  this file's own (a copy with the switch set, and a temporary root for the
  command line): the channel's real config is never edited by a test, and no
  check here asserts which way it points today, so the change that turns the
  switch on does not have to edit this file;
* the marker is read from the config by name, fails closed in every form of
  absence the contract names, and is never guessed from a description, a tag
  or a filename;
* a rights-holder `review` on marked material is capped at `caution` and the
  cap is written down where a reader will find it;
* and the four things the relaxation does not do - the acceptance criteria of
  the task - each have their own test here.

No pytest dependency - plain asserts, dual-mode, same style as
tests/test_check_contribution.py.
"""
import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _tmproot import tmp_root  # noqa: E402  CF-0489: removed at exit
_TMP = tmp_root("blooper-relax-")

import blooper_relaxation as brx  # noqa: E402

# CF-0614: one process-wide audit hook (a hook cannot be removed), handing
# every event to whatever watcher a test has put here for its own span.
WATCHERS = []
sys.addaudithook(lambda event, args: [w(event, args) for w in list(WATCHERS)])

CHANNEL = "example-film"
# The channel config is a tracked file of the root repository, and this
# reader's whole subject: if it is gone, this file fails loudly rather than
# skipping. A skipped check on a missing config is how five checks in a
# neighbouring repo passed while checking nothing (CF-0180).
REAL_CFG_PATH = brx.REPO / "channels" / f"{CHANNEL}.json"
REAL_CFG = json.loads(REAL_CFG_PATH.read_text())
ROOT_VALIDATOR = brx.REPO / "patterns" / "validate_patterns.py"

# A well-formed marker: the three keys the config requires, with an
# attestation long enough not to be a stub.
MARKER = {
    "marked_by": "CF-0190 part 2 test fixture",
    "marked_at": "2026-09-14",
    "not_whole_gag": ("Two seconds of the flubbed line only - the setup and "
                      "the cast's reaction after it stay in the source."),
}


def enabled_cfg():
    """The channel's real block with the switch on, in memory - whatever the
    file on disk says. The switch is flipped on disk in a change of its own;
    nothing here does that."""
    cfg = copy.deepcopy(REAL_CFG)
    cfg[brx.CHANNEL_KEY]["enabled"] = True
    return cfg


def relax():
    r = brx.relaxation(enabled_cfg())
    assert r is not None, "the real block with the switch on must be readable"
    return r


def a_topic(marker=None, scene_extra=None):
    """A Trend Hunter topic whose one scene carries (or does not carry) a
    marker - `topics[].scenes[]`, where the contract puts it."""
    scene = {"scene_id": "t1-s1", "description": "A take that went wrong.",
             "tags": ["funny"]}
    if marker is not None:
        scene["blooper"] = marker
    if scene_extra:
        scene.update(scene_extra)
    return {"topic_id": "t1", "title_ref": {"name": "Spire-Runner",
                                            "rights_holder": "Example Pictures"},
            "scenes": [scene]}


def a_result(verdict="review", matched=True, flagged=False, extra=None):
    """A written verdict of the shape SKILL.md's output block defines."""
    result = {
        "topic_id": "t1",
        "verdict": verdict,
        "rights_holder_check": {
            "matched": matched,
            "risk_level": "high" if matched else None,
            "reason": ("Example Pictures - film_tv, high risk, tentpole IP"
                       if matched else None),
        },
        "content_sensitivity_check": {
            "flagged": flagged,
            "notes": "treatment reads exploitative" if flagged else None,
        },
    }
    if extra:
        result.update(extra)
    return result


def apply_to(result, material, relaxation=None):
    return brx.relax_result(result, material,
                            relax() if relaxation is None else relaxation,
                            CHANNEL)


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------
def test_whatever_the_shipped_config_says_today_this_reader_follows_it():
    """The one check that reads the real file as it stands - as an implication.

    Whichever way the switch points, the block on disk is legal whole, its
    borders are no looser than the decision, and what this reader does with
    marked material follows from the file rather than from the day the test
    was written. The switch is flipped on in a change of its own (part 5,
    together with the Editor's gate); nothing here has to be edited when it
    is, and nothing here edits the real config to see the other side - the
    other side is proven on copies by the tests below.
    """
    # A missing config is a failure, never a skip: a check that quietly
    # passes on an absent subject is how five checks in a neighbouring repo
    # passed while checking nothing (CF-0180).
    assert REAL_CFG_PATH.is_file(), f"{REAL_CFG_PATH} - this file's subject is gone"
    block = REAL_CFG.get(brx.CHANNEL_KEY)
    assert isinstance(block, dict), "the shipped config lost its relaxation block"

    # True on both sides of the switch: a relaxation is recorded whole or not
    # at all, and a channel may be stricter than the decision, never looser.
    assert brx.structural_errors(block) == []
    assert block["max_fragment_seconds"] <= brx.MAX_FRAGMENT_CEILING
    assert block["narration_over_fragment"]["max_silent_seconds"] \
        <= brx.MAX_SILENT_CEILING
    assert block["narration_over_fragment"]["required"] is True
    field = block["marker"]["field"]
    assert isinstance(field, str) and field.strip(), "the marker has no name"
    assert brx.ATTESTATION_KEY in block["marker"]["required_keys"]

    relaxation = brx.relaxation(REAL_CFG)
    assert relaxation == brx.load_relaxation(CHANNEL), (
        "reading the config by channel id and reading this dict must give the "
        "same answer - they are the same file")
    marked = a_topic(MARKER)
    marked["scenes"][0][field] = marked["scenes"][0].pop("blooper")
    if relaxation is None:
        # The switch is off (this block being legal, that is the only reading
        # left): marked material is not even recognised as marked, and the
        # ordinary rights-holder `review` takes the topic off the batch.
        assert block.get("enabled", brx.DEFAULT_ENABLED) is not True
        assert brx.marker_field(relaxation) is None
        assert brx.marked_material(marked, relaxation) == []
        out, record = brx.relax_result(a_result(), marked, relaxation, CHANNEL)
        assert record is None
        assert out == a_result(), "nothing is written where nothing applied"
    else:
        # The switch is on: the marker is read by the name the config gives
        # it, and a rights-holder `review` on marked material is capped.
        assert block["enabled"] is True
        assert brx.marker_field(relaxation) == field
        assert [ident for ident, _ in brx.marked_material(marked, relaxation)] \
            == ["t1-s1"]
        out, record = brx.relax_result(a_result(), marked, relaxation, CHANNEL)
        assert out["verdict"] == brx.CAP_VERDICT
        assert record is not None and record["applied"] is True
        assert out["rights_holder_check"] == a_result()["rights_holder_check"], (
            "the match itself is written exactly as before")
    # True on both branches, and the acceptance criterion of the task: a topic
    # with no marker on it is taken off the batch whichever way the switch
    # points, and the real config never gains a relaxation for it.
    plain = a_topic()
    out, record = brx.relax_result(a_result(), plain, relaxation, CHANNEL)
    assert record is None and out == a_result()


def test_only_a_literal_true_switches_it_on():
    """Fail closed on the switch itself: anything that is not the boolean
    `true` is off, including the shapes that read as true in Python."""
    assert brx.relaxation(enabled_cfg()) is not None
    for value in (False, None, "true", "yes", 1, [], {}):
        cfg = enabled_cfg()
        cfg[brx.CHANNEL_KEY]["enabled"] = value
        assert brx.relaxation(cfg) is None, f"{value!r} switched it on"
    cfg = enabled_cfg()
    del cfg[brx.CHANNEL_KEY]
    assert brx.relaxation(cfg) is None, "a channel with no block has none"
    for not_a_config in (None, [], "channel", 7, {brx.CHANNEL_KEY: "on"}):
        assert brx.relaxation(not_a_config) is None


def test_an_illegal_block_relaxes_nothing():
    """Legality is the root's to enforce, but an illegal block must not grant
    a relaxation on this side either - the safe direction. One mutation per
    rule this reader stands on."""
    mutations = {
        "fragment ceiling widened": ("max_fragment_seconds", 5.0),
        "fragment length zero": ("max_fragment_seconds", 0),
        "fragment length not a number": ("max_fragment_seconds", "3s"),
        "marker not an object": ("marker", "blooper"),
        "unknown key past the schema": ("blooper_bonus", True),
    }
    for name, (key, value) in mutations.items():
        cfg = enabled_cfg()
        cfg[brx.CHANNEL_KEY][key] = value
        assert brx.relaxation(cfg) is None, f"{name} still granted a relaxation"

    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["narration_over_fragment"]["max_silent_seconds"] = 1.0
    assert brx.relaxation(cfg) is None, "silence ceiling widened past 0.5"
    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["narration_over_fragment"]["required"] = False
    assert brx.relaxation(cfg) is None, "narration made optional"
    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["not_the_whole_gag"]["machine_checkable"] = True
    assert brx.relaxation(cfg) is None, "a check that does not exist was claimed"
    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["marker"]["required_keys"] = ["marked_by", "marked_at"]
    assert brx.relaxation(cfg) is None, "the attestation dropped from the marker"
    for key in brx.BLOCK_KEYS:
        cfg = enabled_cfg()
        del cfg[brx.CHANNEL_KEY][key]
        assert brx.relaxation(cfg) is None, f"block without {key!r} was accepted"


def test_this_reader_is_no_looser_than_the_root_schema():
    """The numbers and key lists are a copy of `patterns/validate_patterns.py`
    (the root may not be imported by an agent, and an agent may not import the
    root), so they are read back out of its source here and compared. A block
    the root would refuse must not be one this reader accepts."""
    tree = ast.parse(ROOT_VALIDATOR.read_text())
    root = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.startswith("BLOOPER_"):
                try:
                    root[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    assert root, f"no BLOOPER_* constants found in {ROOT_VALIDATOR}"
    assert root["BLOOPER_KEY"] == brx.CHANNEL_KEY
    assert tuple(root["BLOOPER_READ_KEYS"]) == brx.BLOCK_KEYS
    assert tuple(root["BLOOPER_MARKER_KEYS"]) == brx.MARKER_KEYS
    assert tuple(root["BLOOPER_NARRATION_KEYS"]) == brx.NARRATION_KEYS
    assert tuple(root["BLOOPER_GAG_KEYS"]) == brx.GAG_KEYS
    assert root["BLOOPER_MAX_FRAGMENT_CEILING"] == brx.MAX_FRAGMENT_CEILING
    assert root["BLOOPER_MAX_SILENT_CEILING"] == brx.MAX_SILENT_CEILING
    assert root["BLOOPER_ATTESTATION_KEY"] == brx.ATTESTATION_KEY
    assert root["BLOOPER_DEFAULT_ENABLED"] == brx.DEFAULT_ENABLED is False


# --------------------------------------------------------------------------
# The marker
# --------------------------------------------------------------------------
def test_the_marker_field_name_is_read_from_the_config():
    """`marker.field` names the object; nothing here hardcodes 'blooper'."""
    rx = relax()
    assert brx.marker_field(rx) == "blooper"
    assert brx.marker_of({"blooper": MARKER}, rx) == MARKER

    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["marker"]["field"] = "outtake"
    cfg[brx.CHANNEL_KEY]["not_the_whole_gag"]["attested_by"] = \
        f"outtake.{brx.ATTESTATION_KEY}"
    renamed = brx.relaxation(cfg)
    assert renamed is not None
    assert brx.marker_of({"outtake": MARKER}, renamed) == MARKER
    assert brx.marker_of({"blooper": MARKER}, renamed) is None, (
        "the old field name kept working - the name is hardcoded somewhere")


def test_the_required_keys_are_read_from_the_config():
    """`marker.required_keys` is the list; a config that asks for a fourth key
    gets a fourth key, without this reader changing."""
    cfg = enabled_cfg()
    cfg[brx.CHANNEL_KEY]["marker"]["required_keys"] = \
        list(MARKER) + ["source_url"]
    stricter = brx.relaxation(cfg)
    assert stricter is not None
    assert brx.marker_of({"blooper": MARKER}, stricter) is None
    full = dict(MARKER, source_url="https://example.test/take-3")
    assert brx.marker_of({"blooper": full}, stricter) == full


def test_every_form_of_a_missing_marker_is_not_a_blooper():
    """The contract's list, item by item: absent, null, false, not an object,
    missing a required key, or carrying an empty one."""
    rx = relax()
    assert brx.marker_of({"blooper": MARKER}, rx) == MARKER, "the control case"
    assert brx.marker_of({}, rx) is None, "absent"
    for value in (None, False, True, "blooper", ["blooper"], 1, {}):
        assert brx.marker_of({"blooper": value}, rx) is None, f"{value!r}"
    for key in MARKER:
        short = {k: v for k, v in MARKER.items() if k != key}
        assert brx.marker_of({"blooper": short}, rx) is None, f"without {key}"
        for empty in ("", "   ", None, 0, False, []):
            assert brx.marker_of({"blooper": dict(MARKER, **{key: empty})},
                                 rx) is None, f"{key}={empty!r}"
    assert brx.marker_of(None, rx) is None
    assert brx.marker_of({"blooper": MARKER}, None) is None, (
        "no relaxation means no marker to read, whatever the material says")


def test_a_stub_attestation_is_not_a_marker():
    """`not_the_whole_gag.min_chars` is the one thing a machine can check
    about that border: that the claim was made and is not filler."""
    rx = relax()
    min_chars = rx["not_the_whole_gag"]["min_chars"]
    assert min_chars >= 1
    stub = dict(MARKER, not_whole_gag="x" * (min_chars - 1))
    assert brx.marker_of({"blooper": stub}, rx) is None
    just_enough = dict(MARKER, not_whole_gag="y" * min_chars)
    assert brx.marker_of({"blooper": just_enough}, rx) == just_enough


def test_the_kind_of_material_is_never_guessed():
    """Not from the description, not from the tags, not from a filename. An
    unmarked piece of studio footage that talks about bloopers all over is
    still unmarked, and keeps the ordinary verdict."""
    rx = relax()
    loud = a_topic(scene_extra={
        "description": "On-set blooper reel: the whole cast breaking character.",
        "tags": ["blooper", "bloopers", "behind_the_scenes"],
        "footage_file": "spirerunner_bloopers_take3.mp4",
        "is_blooper": True,
        "blooper_note": "this is a blooper, honest",
    })
    assert brx.marked_material(loud, rx) == []
    out, record = apply_to(a_result(), loud, rx)
    assert record is None
    assert out["verdict"] == "review"


def test_the_marker_is_read_on_both_stages_of_the_pass():
    """`topics[].scenes[]` in the Trend Hunter pass, the `scripts[]` record
    itself in the Content Researcher pass."""
    rx = relax()
    found = brx.marked_material(a_topic(MARKER), rx)
    assert [ident for ident, _ in found] == ["t1-s1"]
    script = {"script_id": "s1", "hook": "...", "blooper": MARKER}
    found = brx.marked_material(script, rx)
    assert [ident for ident, _ in found] == ["s1"]
    assert found[0][1] == MARKER
    mixed = {"topic_id": "t1", "scenes": [{"scene_id": "a"},
                                          {"scene_id": "b", "blooper": MARKER}]}
    assert [ident for ident, _ in brx.marked_material(mixed, rx)] == ["b"]


# --------------------------------------------------------------------------
# What the relaxation does
# --------------------------------------------------------------------------
def test_a_rights_holder_review_on_marked_material_is_capped_at_caution():
    """The case the task is about: batch 2026-09-09T2031Z lost a topic at
    `review` on a Sony/Spire-Runner match. Marked, it proceeds at `caution`."""
    before = a_result()
    out, record = apply_to(before, a_topic(MARKER))
    assert out["verdict"] == "caution"
    assert record is not None and record["applied"] is True
    assert before["verdict"] == "review", "the input must not be mutated"
    assert out["rights_holder_check"] == before["rights_holder_check"], (
        "the match itself is written exactly as before")
    assert out["content_sensitivity_check"] == before["content_sensitivity_check"]


def test_the_record_names_the_block_and_the_marker_that_earned_it():
    """Visible, not hidden: a reader of the output file can get from the
    verdict back to the config block and to the marker."""
    out, record = apply_to(a_result(), a_topic(MARKER))
    assert out[brx.RECORD_KEY] is record
    assert set(record) == {"applied", "relaxed_check", "verdict_before",
                           "verdict_after", "granted_by", "marker_field",
                           "marked_material", "note", "recorded_by_reader"}
    assert record["relaxed_check"] == "rights_holder_check"
    assert (record["verdict_before"], record["verdict_after"]) == ("review", "caution")
    granted = record["granted_by"]
    assert granted["config"] == "channels/example-film.json :: blooper_rights_relaxation"
    assert granted["decided_on"] == REAL_CFG[brx.CHANNEL_KEY]["decided_on"]
    assert granted["recorded_by"] == REAL_CFG[brx.CHANNEL_KEY]["recorded_by"]
    assert granted["applies_to"] == REAL_CFG[brx.CHANNEL_KEY]["applies_to"]
    assert record["marker_field"] == "blooper"
    assert record["marked_material"] == [{"id": "t1-s1", "marker": MARKER}]
    assert "rights-holder-blacklist.json" in record["note"]
    assert "blooper_relaxation.py" in record["recorded_by_reader"]
    json.dumps(record)  # the record has to survive the output file


def test_it_does_not_lower_a_review_the_rights_holder_check_did_not_raise():
    """Criterion one. No match, no relaxation - whatever the marker says."""
    out, record = apply_to(a_result(matched=False), a_topic(MARKER))
    assert (out["verdict"], record) == ("review", None)
    no_check = a_result()
    del no_check["rights_holder_check"]
    out, record = apply_to(no_check, a_topic(MARKER))
    assert (out["verdict"], record) == ("review", None)
    for matched in ("true", None, 1, {}):
        result = a_result()
        result["rights_holder_check"]["matched"] = matched
        out, record = apply_to(result, a_topic(MARKER))
        assert (out["verdict"], record) == ("review", None), f"matched={matched!r}"


def test_it_does_not_soften_content_sensitivity_or_a_contribution_block():
    """Criterion two. Neither is a rights-holder check. A flagged result keeps
    its `review` even with a match and a marker on it; a `block` from the
    contribution-substance check (CF-0066/CF-0187) is a separate verdict and
    is carried through untouched."""
    out, record = apply_to(a_result(flagged=True), a_topic(MARKER))
    assert (out["verdict"], record) == ("review", None), (
        "a review that content sensitivity had a hand in was relaxed")

    blocked = a_result(extra={"contribution_check": {
        "verdict": "block", "checked_against": "channels/example-film/stance.json",
        "failures": [{"reason_code": "fact_in_the_story",
                      "detail": "the fact is what the lead already said"}],
        "reason": "fact_in_the_story"}})
    out, record = apply_to(blocked, a_topic(MARKER))
    assert record is not None, "the rights verdict is the one thing capped"
    assert out["verdict"] == "caution"
    assert out["contribution_check"] == blocked["contribution_check"], (
        "the contribution verdict must be carried through unchanged")
    assert out["contribution_check"]["verdict"] == "block"


def test_it_never_produces_clear():
    """Criterion three. `caution` is the ceiling, `review` the only verdict it
    applies to, and no verdict is ever raised."""
    assert brx.CAP_VERDICT == "caution" and brx.RELAXABLE_VERDICT == "review"
    for verdict in ("clear", "caution"):
        out, record = apply_to(a_result(verdict=verdict), a_topic(MARKER))
        assert out["verdict"] == verdict, f"{verdict} was moved"
        assert record is None, f"{verdict} got a relaxation record"
        assert brx.RECORD_KEY not in out
    out, record = apply_to(a_result(), a_topic(MARKER))
    assert out["verdict"] != "clear" and record["verdict_after"] != "clear"


def test_an_unmarked_topic_is_taken_off_the_batch_exactly_as_before():
    """Criterion four, and the acceptance criterion of CF-0190: the result is
    not merely still `review`, it is byte-for-byte the result that was
    written."""
    before = a_result()
    out, record = apply_to(before, a_topic())
    assert record is None
    assert json.dumps(out, sort_keys=True) == json.dumps(before, sort_keys=True)
    out, record = apply_to(before, None)
    assert record is None and out["verdict"] == "review"


def test_the_blacklist_is_neither_read_nor_touched():
    """The channel's rights-holder list (`channels/<channel>/rights-holder-blacklist.json`,
    CF-0629) is not this module's business at
    all: it never names the file, and the match object it was given comes back
    identical."""
    source = (SCRIPTS / "blooper_relaxation.py").read_text()
    name = "rights-holder-blacklist"
    in_prose = sum(node.value.count(name)
                   for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.Constant) and isinstance(node.value, str))
    assert in_prose > 0, "the module should say that it leaves the blacklist alone"
    assert source.count(name) == in_prose, (
        "the blacklist is named outside prose - this reader must not open, "
        "filter or re-score it")

    before = a_result()
    match_as_written = copy.deepcopy(before["rights_holder_check"])
    out, _ = apply_to(before, a_topic(MARKER))
    assert out["rights_holder_check"] == match_as_written
    # CF-0614: watched by an audit hook, not by the live file's mtime - the
    # test reads no factory registry; the pass must open no path by that name.
    opened = []

    def _watch(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)) \
                and name in os.fsdecode(args[0]):
            opened.append(os.fsdecode(args[0]))
    WATCHERS.append(_watch)
    try:
        apply_to(a_result(), a_topic(MARKER))
    finally:
        WATCHERS.remove(_watch)
    assert opened == [], opened


# --------------------------------------------------------------------------
# The document pass and the command line
# --------------------------------------------------------------------------
def _temp_root(enabled):
    """A factory root holding one channel config, for the command line to
    read through FACTORY_ROOT. The real config is never edited by a test."""
    tmp = Path(tempfile.mkdtemp(prefix="blooper-relax-", dir=_TMP))
    (tmp / "channels").mkdir()
    (tmp / "patterns").mkdir()
    # `FACTORY_ROOT` is the whole root to every reader that honours it,
    # `scripts/_runlog.py` included - it looks for shared/runlog/runlog.py
    # under it and dies on import if the root it was handed has none. The
    # symlink keeps this miniature root a plausible one. There is deliberately
    # no channel rights-holder list under it: the command line runs
    # here and relaxes a verdict without a blacklist existing at all.
    (tmp / "shared").mkdir()
    (tmp / "shared" / "runlog").symlink_to(brx.REPO / "shared" / "runlog")
    # The switch is set here, explicitly, either way: this fixture must not
    # inherit whatever the real config happens to say today, or the "off"
    # case would stop testing anything the day part 5 flips it.
    cfg = copy.deepcopy(REAL_CFG)
    cfg[brx.CHANNEL_KEY]["enabled"] = bool(enabled)
    (tmp / "channels" / f"{CHANNEL}.json").write_text(
        json.dumps(cfg, ensure_ascii=False))
    return tmp


def _batch_files(tmp):
    stage = {"batch_id": "2026-09-09T2031Z", "channel": CHANNEL,
             "topics": [a_topic(MARKER),
                        {"topic_id": "t2", "scenes": [{"scene_id": "t2-s1"}]}]}
    doc = {"batch_id": "2026-09-09T2031Z", "channel": CHANNEL,
           "stage_checked": "01-trend-hunter",
           "results": [a_result(), a_result()]}
    doc["results"][1]["topic_id"] = "t2"
    stage_path = tmp / "01-trend-hunter.json"
    out_path = tmp / "02-compliance-checker.json"
    stage_path.write_text(json.dumps(stage, ensure_ascii=False))
    out_path.write_text(json.dumps(doc, ensure_ascii=False))
    return stage_path, out_path


def test_a_whole_document_is_relaxed_per_result():
    """The join the command line makes: results by `topic_id`/`script_id`
    against `topics[]`/`scripts[]` of the stage file it judged."""
    tmp = _temp_root(enabled=True)
    stage_path, out_path = _batch_files(tmp)
    doc = json.loads(out_path.read_text())
    stage = json.loads(stage_path.read_text())
    new_doc, applied = brx.relax_document(doc, stage, relax(), CHANNEL)
    assert list(applied) == ["t1"], "only the marked topic"
    verdicts = {r["topic_id"]: r["verdict"] for r in new_doc["results"]}
    assert verdicts == {"t1": "caution", "t2": "review"}
    assert brx.RECORD_KEY not in new_doc["results"][1]
    assert doc["results"][0]["verdict"] == "review", "input document untouched"


def _run_cli(tmp, args):
    env = dict(os.environ, FACTORY_ROOT=str(tmp))
    env.pop("RUNLOG_BATCH", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "blooper_relaxation.py"), *args],
        capture_output=True, text=True, env=env, timeout=60)


def test_the_command_line_writes_the_relaxation_into_the_file():
    tmp = _temp_root(enabled=True)
    stage_path, out_path = _batch_files(tmp)
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL])
    assert proc.returncode == 0, proc.stderr
    assert "t1: review -> caution" in proc.stdout, proc.stdout
    assert "1 relaxed" in proc.stdout
    written = json.loads(out_path.read_text())
    assert written["results"][0]["verdict"] == "caution"
    assert written["results"][0][brx.RECORD_KEY]["applied"] is True
    assert written["results"][1]["verdict"] == "review"
    assert brx.RECORD_KEY not in written["results"][1]


def test_the_command_line_leaves_the_file_alone_on_a_dry_run():
    tmp = _temp_root(enabled=True)
    stage_path, out_path = _batch_files(tmp)
    before = out_path.read_text()
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL, "--dry-run"])
    assert proc.returncode == 0, proc.stderr
    assert "nothing written" in proc.stdout
    assert out_path.read_text() == before


def test_the_command_line_relaxes_nothing_while_the_switch_is_off():
    """With the switch off: a perfectly marked blooper, a high-risk match,
    and the verdict stands. The switch is set on this test's own config, so
    this stays the off case whatever the real one says."""
    tmp = _temp_root(enabled=False)
    stage_path, out_path = _batch_files(tmp)
    before = out_path.read_text()
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL])
    assert proc.returncode == 0, proc.stderr
    assert "no relaxation" in proc.stdout
    assert out_path.read_text() == before
    assert json.loads(before)["results"][0]["verdict"] == "review"


def test_an_unreadable_or_absent_config_grants_nothing():
    tmp = _temp_root(enabled=True)
    assert brx.load_relaxation(CHANNEL, repo=tmp) is not None
    assert brx.load_relaxation("no-such-channel", repo=tmp) is None
    (tmp / "channels" / f"{CHANNEL}.json").write_text("{not json")
    assert brx.load_relaxation(CHANNEL, repo=tmp) is None


def test_the_skill_retires_the_script_from_both_passes():
    """CF-0420 (user, 2026-09-28): a rights-holder match no longer earns a
    `review`, so there is nothing left for the relaxation to cap. The pass no
    longer runs it - a step that can only ever print `no relaxation` is noise -
    and the SKILL says so in so many words, so its absence reads as a decision
    rather than a loss. This module and its tests stay as the record."""
    skill = (AGENT_ROOT / ".claude" / "skills" / "compliance-checker"
             / "SKILL.md").read_text()
    assert "scripts/blooper_relaxation.py/" not in skill
    assert "blooper_relaxation.py \\" not in skill, (
        "the SKILL still runs the relaxation as a step")
    assert "retired from this procedure" in skill
    assert "blooper_rights_relaxation" in skill, (
        "the retirement should name the config block it leaves behind")


def test_a_usage_error_exits_2():
    tmp = _temp_root(enabled=True)
    proc = _run_cli(tmp, [])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "usage:" in proc.stdout


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
