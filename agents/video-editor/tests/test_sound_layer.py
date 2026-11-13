#!/usr/bin/env python3
"""CF-0068: the sound insert layer, on a test config with the switch on.

inserts/sound.json's exit criterion never runs on example-film (the
layer is off there), so everything here is a temp factory root under
FACTORY_ROOT - the convention underlay.py set - with the real spec, the real
inserts_lib, the real explainer/contrast patterns, a channel config with the
switch on, a blacklist with one high-risk holder and a small library of
stdlib-written WAVs: one over the 1.5 s ceiling, one held by the high-risk
holder. No footage, no Vision, no torch; ffmpeg only for the mix and the
QC gate. The real shared/inserts/sounds/index.json is empty until CF-0115
and is never read.

What is checked, per the task's exit criterion:
  - layer_off on the real example-film config, pattern_refused on contrast
  - the two beat diagnoses CF-0235 split `beat_not_found` into, each with
    its evidence; no_slot for a gap under 4.0 s and for a slot crossing
    into the payoff; no_asset on an empty library and when every candidate
    is skipped (blacklist, ceiling)
  - placed with at_seconds = the beat's first word start and block_index
    recorded; the high-risk holder's file skipped and recorded; matched_tags
  - S3's negative half (a spoken word equal to a matched tag skips the file)
  - distinct per video; degradation identity (a refused request changes no
    block; a placed one adds `sound` and nothing else)
  - the pair passes the root's check_sound_pair / check_insert_provenance
  - the same through build_render_plan.py, and the pair + provenance through
    write_batch_metadata.video_record (merge beside meme/underlay records)
  - build_soundtrack.py: the mix gains energy in the slot, is unchanged
    outside it, and a plan with no sound mixes the way it did before the
    layer; qc_render's MIN_SOUND_RMS_DB gate hears the one and not the other
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import copy
import importlib.util
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import meme_layer as ml  # noqa: E402
import sound_layer as sl  # noqa: E402
import write_batch_metadata  # noqa: E402
from common import SOUND_MIN_GAP_SECONDS  # noqa: E402
from repo_paths import VENV_PY3  # noqa: E402 - CF-0125: resolved against the main checkout

REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "inserts" / "sound.json").exists()), None)
assert REAL_ROOT is not None, "the factory root (inserts/sound.json) is not reachable"
SPEC = json.load(open(REAL_ROOT / "inserts" / "sound.json"))
VENV_PY = Path(VENV_PY3)
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def tone_wav(path, seconds, hz=880.0, rate=8000, amp=0.8):
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(32767 * amp * math.sin(2 * math.pi * hz * i / rate)))
                               for i in range(n)))


def entry(eid, file, holder, tags, description, duration, medium=None):
    return {"id": eid, "file": file, "kind": "sound", "description": description,
            "tags": tags, "source_url": f"https://example.org/{eid}", "rights_holder": holder,
            "licence": None, "medium": medium, "duration_s": duration, "added": "2026-09-01"}


# The library: `oof` and `mario-hit` both answer `damage` on two tags (the
# blacklist decides between them; `oof` also matches `hurt` through its
# description), `oof-two` answers it on one tag (distinct-per-video's second
# choice), `long-fail` answers `fail` but is over the ceiling, `buzzer`
# answers `fail` under it, `fanfare` answers `win` at 0.9 s (the payoff test).
ENTRIES = [
    entry("oof", "oof.wav", "Someone Else", ["damage", "oof"], "the hurt grunt", 0.4),
    entry("mario-hit", "mario-hit.wav", "Nintendo", ["damage", "hit"], "a hit taken", 0.4,
          medium="games_ip"),
    entry("oof-two", "oof-two.wav", "Someone Else", ["damage"], "another grunt", 0.5),
    entry("long-fail", "long-fail.wav", "Someone Else", ["fail", "sad_trombone"],
          "a long sad trombone", 2.0),
    entry("buzzer", "buzzer.wav", "Someone Else", ["buzzer"], "wrong answer buzzer", 0.3),
    entry("fanfare", "fanfare.wav", "Someone Else", ["fanfare"], "a short fanfare", 0.9),
]
DURATIONS = {e["file"]: e["duration_s"] for e in ENTRIES}


def channel_list(root, channel):
    """CF-0630: where a channel's rights-holder list lives in a stand-in root
    (`channels/<id>/rights-holder-blacklist.json`, the channel's own data -
    the layers read it through the root's shared/channel_data.py)."""
    d = Path(root) / "channels" / channel
    d.mkdir(parents=True, exist_ok=True)
    return d / "rights-holder-blacklist.json"


def make_root(tmp, entries=ENTRIES):
    """A factory root under tmp with the real spec, lib and patterns."""
    root = Path(tmp) / "factory"
    (root / "inserts").mkdir(parents=True)
    for spec in ("sound.json", "meme.json"):
        shutil.copy(REAL_ROOT / "inserts" / spec, root / "inserts" / spec)
    sounds = root / "shared" / "inserts" / "sounds"
    sounds.mkdir(parents=True)
    (root / "shared" / "inserts" / "memes").mkdir()
    shutil.copy(REAL_ROOT / "shared" / "inserts" / "inserts_lib.py",
                root / "shared" / "inserts" / "inserts_lib.py")
    (root / "patterns").mkdir()
    for pid in ("explainer", "contrast"):
        shutil.copy(REAL_ROOT / "patterns" / f"{pid}.json", root / "patterns" / f"{pid}.json")
    (root / "channels").mkdir()
    json.dump({"channel_id": "test", "display_name": "Test Channel", "theme": STAND_IN_THEME, "insert_layers": {"sound": {"enabled": True, "reason": "CF-0068 test config"},
                                 "meme": {"enabled": False, "reason": "not under test"}},
               # CF-0137: the storyboards below are deliberately unfilled
               # blocks, and a block with no picture now refuses the plan
               # unless the channel allows the per-block assetless rung. Test
               # config only - the refusal is pinned in
               # tests/test_assetless_rung_gate.py.
               "assetless_block_rung": {"enabled": True,
                                        "reason": "CF-0137 test config"}},
              open(root / "channels" / "test.json", "w"))
    json.dump({"schema_note": "test", "last_updated": "2026-09-01", "entries": [
        {"rights_holder": "Nintendo / The Pokemon Company", "medium": "games_ip",
         "risk_level": "high", "reason": "test"}]},
        open(channel_list(root, "test"), "w"))
    json.dump({"schema_note": "test", "kind": "sound", "embedding_model": None,
               "entries": entries}, open(sounds / "index.json", "w"))
    json.dump({"schema_note": "test", "kind": "meme", "embedding_model": None, "entries": []},
              open(root / "shared" / "inserts" / "memes" / "index.json", "w"))
    for e in entries:
        tone_wav(sounds / e["file"], DURATIONS[e["file"]])
    return root


# hook (3 words) + commentary (16) + payoff (3), one word per 0.5s.
HOOK = "The hook here"
COMMENTARY = ("and then the commentary says this is absurd, frankly, again "
              "and more words follow right here")
PAYOFF = "and the payoff"
WORDS = [{"word": w, "start": round(i * 0.5, 2), "end": round(i * 0.5 + 0.45, 2)}
         for i, w in enumerate((HOOK + " " + COMMENTARY + " " + PAYOFF).replace(",", "").split())]
VOICE_END = 11.0
# "this is absurd" is words 8..10 -> anchor 4.0s; "more words" 14..15 -> 7.0s
# (3.0s after 4.0: inside the gap); "follow right here" 16..18 -> 8.0s
# (exactly the gap); "here" -> 9.0s, 0.5s before the payoff's first word
# (word 19 at 9.5s).


def script(sounds):
    return {"script_id": "s1", "hook": HOOK, "commentary": COMMENTARY, "payoff": PAYOFF,
            "sounds": sounds}


S_DAMAGE = {"beat_id": "s1", "intent": "damage", "beat_text": "this is absurd"}
S_FAIL_NEAR = {"beat_id": "s2", "intent": "fail", "beat_text": "more words"}
S_FAIL_FAR = {"beat_id": "s2", "intent": "fail", "beat_text": "follow right here"}
S_WIN_LATE = {"beat_id": "s2", "intent": "win", "beat_text": "here"}
S_DAMAGE_FAR = {"beat_id": "s2", "intent": "damage", "beat_text": "follow right here"}


def block(start, end, kind="clip", **extra):
    b = {"start": start, "end": end, "intent": f"{start}-{end}",
         "asset": {"kind": kind, **({"src": f"/nowhere/{start}.mp4"} if kind == "clip" else {})}}
    b.update(extra)
    return b


BLOCKS = [block(0.0, 2.0, "still"), block(2.0, 5.3, "clip"), block(5.3, VOICE_END, "procedural")]


def run(sounds, blocks=BLOCKS, root=None, channel="test", pattern="explainer", words=WORDS, **kw):
    return sl.plan_sounds(script(sounds), words, blocks, ml.load_channel(channel, root),
                          ml.load_pattern(pattern, root), root=root, voice_end=VOICE_END, **kw)


def outcomes(res):
    return [a["outcome"] for a in res["sound_delivered"]]


def skips(res):
    return {(r["id"], r.get("skip_reason")) for r in res["inserts"] if r["skipped"]}


# --------------------------------------------------------------------------
# the root's own checks, imported when reachable
# --------------------------------------------------------------------------

def check_sound_pair(v, ctx):
    path = REAL_ROOT / "tests" / "test_pipeline_contracts.py"
    if path.exists():
        spec = importlib.util.spec_from_file_location("test_pipeline_contracts", path)
        mod = importlib.util.module_from_spec(spec)
        # CF-0482: the root file imports its own helpers (_tmproot, CF-0378)
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(mod)
        mod.check_sound_pair(v, ctx)
        mod.check_insert_provenance(v, ctx)
        return
    # Replica of the root check for a checkout without tests/.
    req, dlv = v["sound_requested"], v["sound_delivered"]
    assert len(req) == len(dlv)
    for r, a in zip(req, dlv):
        assert a["beat_id"] == r["beat_id"] and a["outcome"] in SPEC["metadata"]["outcomes"]
        if a["outcome"] == "placed":
            used = [p for p in v["inserts"] if p["id"] == a["asset_id"] and p["layer"] == "sound"]
            assert used and not used[0]["skipped"] and used[0]["block"] == a["block_index"]
            assert used[0]["at_seconds"] == a["at_seconds"]
        else:
            assert a["block_index"] is None and a["asset_id"] is None and a["at_seconds"] is None


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------





def test_pattern_refused_on_contrast():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([S_DAMAGE, S_FAIL_FAR], root=root, pattern="contrast")
        assert outcomes(res) == ["pattern_refused", "pattern_refused"], res["sound_delivered"]
        assert res["inserts"] == []
        assert outcomes(run([S_DAMAGE], root=root, pattern="no-such-pattern")) == ["pattern_refused"]


def test_a_lost_beat_says_which_of_the_two_faults_it_is():
    """CF-0235: S1 has no moment without a beat, but "the video never says
    this sentence" and "the video says it and our aligner lost it" are
    different news and used to arrive as one word. Same `beat_failure()` and
    same three codes as the proof and meme layers - a second vocabulary for
    one question is the CF-0159 defect."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        bad = {**S_DAMAGE, "beat_text": "words the narration never says"}
        res = run([bad, S_FAIL_FAR], root=root)
        assert outcomes(res) == [ml.BEAT_MISSING_IN_SCRIPT, "placed"], res["sound_delivered"]
        a = res["sound_delivered"][0]
        assert {k: a[k] for k in ("beat_id", "outcome", "block_index", "asset_id",
                                  "at_seconds")} == {
            "beat_id": "s1", "outcome": ml.BEAT_MISSING_IN_SCRIPT, "block_index": None,
            "asset_id": None, "at_seconds": None}
        assert a["evidence"]["code"] == ml.BEAT_MISSING_IN_SCRIPT
        assert a["evidence"]["searched"].startswith("words the narration")
        assert "evidence" not in res["sound_delivered"][1], "a placed answer diagnoses nothing"

        # The other fault: the beat is in the script character for character
        # and the alignment - here, a voiceover that stops after the hook -
        # does not have it. Ours to fix, and the evidence says so.
        short = [{"word": w, "start": round(i * 0.5, 2), "end": round(i * 0.5 + 0.45, 2)}
                 for i, w in enumerate(HOOK.split())]
        res2 = run([S_DAMAGE], root=root, words=short)
        assert outcomes(res2) == [ml.BEAT_UNMATCHED_IN_ALIGNMENT], res2["sound_delivered"]
        ev = res2["sound_delivered"][0]["evidence"]
        assert ev["in_script_coverage"] == 1.0 and ev["nearest"]["text"]
        assert ev["alignment_words"] == len(short)
        assert sl.OUTCOME_BEAT_NOT_FOUND not in outcomes(res) + outcomes(res2)


def test_no_slot_inside_the_gap_and_crossing_into_the_payoff():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        # S4: the second anchor is 3.0s after the first - inside the 4.0s gap.
        res = run([S_DAMAGE, S_FAIL_NEAR], root=root)
        assert outcomes(res) == ["placed", "no_slot"], res["sound_delivered"]
        assert res["sound_delivered"][1]["asset_id"] is None
        assert not any(r["beat_id"] == "s2" for r in res["inserts"]), "no file was looked at"
        # Exactly the gap is allowed.
        assert outcomes(run([S_DAMAGE, S_FAIL_FAR], root=root)) == ["placed", "placed"]
        assert SOUND_MIN_GAP_SECONDS == SPEC["placement"]["min_gap_seconds"]
        # S2: "here" at 9.0s leaves 0.5s before the payoff's first word; the
        # only `win` file is 0.9s long - refused by the moment, recorded as
        # such, and never moved earlier.
        res = run([S_WIN_LATE], root=root)
        assert outcomes(res) == ["no_slot"], res["sound_delivered"]
        assert ("fanfare", sl.SKIP_SLOT) in skips(res), skips(res)
        # ... beside the blacklist skip every request records (eligible() first).
        assert skips(res) - {("mario-hit", sl.SKIP_BLACKLIST)} == {("fanfare", sl.SKIP_SLOT)}
        # A request in the hook is refused too (protected section).
        res = run([{"beat_id": "s1", "intent": "damage", "beat_text": "hook here"}], root=root)
        assert outcomes(res) == ["no_slot"], res["notes"]


def test_no_asset_on_an_empty_library_and_when_every_candidate_is_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        # The real library's state until CF-0115: every request is no_asset.
        root = make_root(tmp, entries=[])
        res = run([S_DAMAGE, S_FAIL_FAR], root=root)
        assert outcomes(res) == ["no_asset", "no_asset"], res["sound_delivered"]
        assert res["inserts"] == []
    with tempfile.TemporaryDirectory() as tmp:
        # Only the blacklisted file answers `damage`; only the over-ceiling
        # file answers `fail`. Both skips are recorded with the moment.
        root = make_root(tmp, entries=[e for e in ENTRIES if e["id"] in ("mario-hit", "long-fail")])
        res = run([S_DAMAGE, S_FAIL_FAR], root=root)
        assert outcomes(res) == ["no_asset", "no_asset"], res["sound_delivered"]
        assert skips(res) == {("mario-hit", sl.SKIP_BLACKLIST), ("long-fail", sl.SKIP_DURATION)}
        for r in res["inserts"]:
            assert r["layer"] == "sound" and r["beat_id"] in ("s1", "s2")
            assert isinstance(r["at_seconds"], float) and isinstance(r["block"], int)
            assert isinstance(r["matched_tags"], list)
        # An intent no file answers on any tag: no_asset, nothing recorded for it.
        res = run([{"beat_id": "s1", "intent": "crickets", "beat_text": "this is absurd"}], root=root)
        assert outcomes(res) == ["no_asset"]


def test_placed_at_the_first_word_with_block_recorded_and_the_blacklist_skip():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([S_DAMAGE, S_FAIL_FAR], root=root)
        assert outcomes(res) == ["placed", "placed"], res["sound_delivered"]
        a, b = res["sound_delivered"]
        # S1: the start of "this" (word 8) - no offset, no better word.
        assert a == {"beat_id": "s1", "outcome": "placed", "block_index": 1,
                     "asset_id": "oof", "at_seconds": 4.0}, a
        assert b["asset_id"] == "buzzer" and b["at_seconds"] == 8.0 and b["block_index"] == 2
        # `oof` and `mario-hit` tie on two tags; the blacklist skip decides,
        # and is recorded next to the file used, with the same moment.
        rec = {r["id"]: r for r in res["inserts"] if r["beat_id"] == "s1"}
        rec.update({r["id"]: r for r in res["inserts"] if r["beat_id"] == "s2" and r["id"] != "mario-hit"})
        assert not rec["oof"]["skipped"] and rec["oof"]["block"] == 1
        assert rec["oof"]["at_seconds"] == 4.0 and rec["oof"]["matched_tags"] == ["damage", "hurt", "oof"]
        assert rec["mario-hit"]["skipped"] and rec["mario-hit"]["blacklist_check"]["skip"]
        # CF-0236: "cut before the ranking" is said by the one key every
        # record carries, not by that key's absence - and the placed file
        # carries it too, as null.
        assert rec["mario-hit"]["skip_reason"] == sl.SKIP_BLACKLIST, rec["mario-hit"]
        assert rec["oof"]["skip_reason"] is None and rec["buzzer"]["skip_reason"] is None
        assert all(("skip_reason" in r) and (r["skipped"] == (r["skip_reason"] is not None))
                   for r in res["inserts"]), res["inserts"]
        assert rec["mario-hit"]["block"] == 1 and rec["mario-hit"]["at_seconds"] == 4.0
        assert rec["mario-hit"]["matched_tags"] == ["damage", "hit"]
        # `buzzer` (tags: wrong via its description, buzzer) ties `long-fail`
        # (fail, sad_trombone) on count and wins on id; the walk stops at the
        # first pass, so the over-ceiling file is never looked at here (its
        # duration_floor skip is recorded in the no_asset test above).
        assert not rec["buzzer"]["skipped"] and rec["buzzer"]["matched_tags"] == ["wrong", "buzzer"]
        assert "long-fail" not in rec
        # The blacklist skip is recorded once per request that reached selection.
        assert [r["beat_id"] for r in res["inserts"] if r["id"] == "mario-hit"] == ["s1", "s2"]
        # The block records for the mix.
        assert [p["block_index"] for p in res["placed"]] == [1, 2]
        p = res["placed"][0]["record"]
        assert p["kind"] == "sound" and p["asset_id"] == "oof" and p["duration_s"] == 0.4
        assert Path(p["file"]).exists() and p["at_seconds"] == 4.0
        assert any("oof at 4.00s on block 1" in n for n in res["notes"])


def test_ranking_is_by_tag_count_then_id():
    vocab = SPEC["selection"]["intent_vocabulary"]
    tags = sl.intent_tags(SPEC, "damage")
    assert tags == [t.lower() for t in vocab["damage"]["tags"]]
    ranked = sl.rank_by_tags(ENTRIES, tags, SPEC["selection"]["min_tag_matches"])
    assert [e["id"] for _, e in ranked] == ["oof", "mario-hit", "oof-two"]
    # Whole words only, underscores as spaces, case-insensitive.
    e = entry("x", "x.wav", "h", [], "A Sad Trombone, badly played", 0.3)
    assert sl.matched_tags(e, sl.intent_tags(SPEC, "fail")) == ["sad_trombone"]
    e = entry("y", "y.wav", "h", ["WIN"], "the dinging of bells", 0.3)
    assert sl.matched_tags(e, sl.intent_tags(SPEC, "win")) == ["win"], "no stemming: 'dinging' != 'ding'"


def test_s3_negative_half_skips_a_file_whose_tag_the_words_speak():
    """'oof' spoken at the anchor: the `oof` file would caption the words,
    so it is skipped (meaning_negative_half) and the walk goes on to the
    next candidate, whose matched tags the words do not say."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        words = copy.deepcopy(WORDS)
        words[8]["word"] = "oof"     # "this is absurd" -> "oof is absurd", still located
        res = run([S_DAMAGE], root=root, words=words)
        assert outcomes(res) == ["placed"], res["sound_delivered"]
        assert res["sound_delivered"][0]["asset_id"] == "oof-two"
        assert ("oof", sl.SKIP_MEANING) in skips(res)
        # The positive half is not measured: the spec says so and so do we.
        assert SPEC["meaning_rule"]["status"] == "not verified"


def test_distinct_per_video():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([S_DAMAGE, S_DAMAGE_FAR], root=root)
        assert outcomes(res) == ["placed", "placed"], res["sound_delivered"]
        assert [a["asset_id"] for a in res["sound_delivered"]] == ["oof", "oof-two"]
        assert ("oof", sl.SKIP_DISTINCT) in skips(res)
        # Two placed sounds in one video is the ceiling; a third request is
        # cut by the spec's max_sounds_per_script before it is answered.
        res = run([S_DAMAGE, S_DAMAGE_FAR, {**S_FAIL_FAR, "beat_id": "s3"}], root=root)
        assert len(res["sound_requested"]) == 2 == SPEC["selection"]["max_sounds_per_script"]


def test_the_rights_holder_list_is_the_channels_own_and_a_channel_without_one_gets_no_sound():
    """CF-0630: the list is `channels/<id>/rights-holder-blacklist.json` of the
    channel the plan is for (`channel_id` of its config). A former id reads
    the same channel's list. A channel with no list of its own - or a config
    that names no channel - takes no sound at all: every file of this library
    is a checked kind, and a holder that cannot be checked is refused; the
    old common path is not a fallback, and the notes say why."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        # A former id of `test` is the same channel and reads the same list.
        cfg = json.load(open(root / "channels" / "test.json"))
        cfg["former_channel_ids"] = ["old-test"]
        json.dump(cfg, open(root / "channels" / "test.json", "w"))
        res = run([S_DAMAGE], root=root, channel=str(root / "channels" / "test.json"))
        assert outcomes(res) == ["placed"] and ("mario-hit", sl.SKIP_BLACKLIST) in skips(res)
        former = dict(cfg, channel_id="old-test")
        res = sl.plan_sounds(script([S_DAMAGE]), WORDS, BLOCKS, former,
                             ml.load_pattern("explainer", root), root=root, voice_end=VOICE_END)
        assert outcomes(res) == ["placed"] and ("mario-hit", sl.SKIP_BLACKLIST) in skips(res)

        # A config that names no channel: no default channel is picked.
        nameless = {k: v for k, v in cfg.items() if k != "channel_id"}
        res = sl.plan_sounds(script([S_DAMAGE, S_FAIL_FAR]), WORDS, BLOCKS, nameless,
                             ml.load_pattern("explainer", root), root=root, voice_end=VOICE_END)
        assert outcomes(res) == ["no_asset", "no_asset"], res["sound_delivered"]
        assert res["placed"] == [] and res["inserts"] == []
        assert any("no rights-holder list for channel None" in n for n in res["notes"]), res["notes"]

        # The channel's file gone, an old common file present: still nothing.
        channel_list(root, "test").unlink()
        json.dump({"schema_note": "test", "last_updated": "2026-09-01", "entries": []},
                  open(root / "shared" / "rights-holder-blacklist.json", "w"))
        res = run([S_DAMAGE, S_FAIL_FAR], root=root)
        assert outcomes(res) == ["no_asset", "no_asset"], res["sound_delivered"]
        assert res["placed"] == [] and res["inserts"] == []
        note = next(n for n in res["notes"] if n.startswith("sound: no rights-holder list"))
        assert "'test'" in note and "rights-holder-blacklist.json" in note, note
        assert [n for n in res["notes"] if n.startswith("sound s")] == [
            "sound s1: no_asset - the channel has no rights-holder list, no file is "
            "checked or taken (CF-0630)",
            "sound s2: no_asset - the channel has no rights-holder list, no file is "
            "checked or taken (CF-0630)"]
        # The moment-side refusals still come first: a layer that is off says so.
        off = dict(cfg, insert_layers={"sound": {"enabled": False, "reason": "test"}})
        res = sl.plan_sounds(script([S_DAMAGE]), WORDS, BLOCKS, off,
                             ml.load_pattern("explainer", root), root=root, voice_end=VOICE_END)
        assert outcomes(res) == ["layer_off"]

def test_apply_to_plan_adds_sound_only_and_degradation_is_identity():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        before = copy.deepcopy(BLOCKS)
        plan = {"blocks": copy.deepcopy(BLOCKS), "style": "motion"}
        sl.apply_to_plan(plan, run([S_DAMAGE, S_FAIL_NEAR], root=root))
        assert plan["blocks"][1]["sound"]["asset_id"] == "oof"
        assert plan["blocks"][1]["sound"]["kind"] == "sound"
        stripped = [{k: v for k, v in b.items() if k != "sound"} for b in plan["blocks"]]
        assert stripped == before, "a sound changes nothing else on any block"
        assert "sound" not in plan["blocks"][0] and "sound" not in plan["blocks"][2]
        assert [p["asset_id"] for p in sl.placed_sounds(plan)] == ["oof"]
        # A refused request: every block byte-identical, the pair still written.
        plan = {"blocks": copy.deepcopy(BLOCKS)}
        sl.apply_to_plan(plan, run([S_FAIL_NEAR], root=root, pattern="contrast"))
        assert plan["blocks"] == before
        assert plan["sound"]["sound_delivered"][0]["outcome"] == "pattern_refused"
        assert plan["sound"]["placed"] == [] and sl.placed_sounds(plan) == []
        # A plan built before the layer existed carries no sound at all.
        assert sl.placed_sounds({"blocks": before}) == []
        assert sl.stage_fields({"blocks": before}) == ([], [], [])


def test_the_pair_passes_the_root_contract_check():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        for sounds in ([S_DAMAGE, S_FAIL_FAR], [S_DAMAGE, S_FAIL_NEAR], [S_WIN_LATE], []):
            res = run(sounds, root=root)
            check_sound_pair({"script_id": "s1", "output_path": "x.mp4", "inserts": res["inserts"],
                              "sound_requested": res["sound_requested"],
                              "sound_delivered": res["sound_delivered"]}, "s1")


def _silent_wav(path, seconds, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def test_build_render_plan_carries_the_sound_on_its_block():
    """Through the real script: --script/--script-id/--channel. The block
    holding the anchor keeps its own asset and gains `sound`; plan["sound"]
    carries the pair; stderr says SOUND s1: placed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = make_root(tmp)
        _silent_wav(tmp / "voice.wav", VOICE_END)
        (tmp / "words.json").write_text(json.dumps(WORDS))
        (tmp / "03.json").write_text(json.dumps({"scripts": [script([S_DAMAGE, S_FAIL_FAR])]}))
        sb = [
            {"word_range": [0, 3], "intent": "count card", "asset_kind": "card",
             "card": {"kind": "count_card", "text": "3"}, "emphasis_words": [],
             "rhythm_role": "opening_card", "side": None, "shot": None, "held_frame": False},
            {"word_range": [4, 11], "intent": "step", "asset_kind": "typographic",
             "unfilled_reason": "no shot in any index", "emphasis_words": [],
             "rhythm_role": "beat", "side": None, "shot": None, "held_frame": False},
            {"word_range": [12, 21], "intent": "step", "asset_kind": "typographic",
             "unfilled_reason": "no shot in any index", "emphasis_words": [],
             "rhythm_role": "beat", "side": None, "shot": None, "held_frame": False},
        ]
        story = {"script_id": "s1", "style": "motion", "resolved_from_anchors": True,
                 "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "hold",
                            "rhythm_built": "hold",
                            "parameters": {"block_count": 3, "key_frame_hold_seconds": 4.0},
                            "opening_requested": "count_card", "opening_delivered": "count_card",
                            "anchor_count": 3},
                 "blocks": sb, "unresolved_anchors": [], "rejected_candidates": []}
        (tmp / "storyboard.json").write_text(json.dumps(story))
        out = tmp / "plan.json"
        env = dict(os.environ, FACTORY_ROOT=str(root))
        cmd = [PY, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
               str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
               "--style", "motion", "--target-duration", "1", "60"]
        result = subprocess.run(
            cmd + ["--script", str(tmp / "03.json"), "--script-id", "s1",
                   "--channel", str(root / "channels" / "test.json")],
            capture_output=True, text=True, cwd=tmp, env=env, timeout=120)
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        pair = plan["sound"]
        assert [a["outcome"] for a in pair["sound_delivered"]] == ["placed", "placed"], pair
        a, b = pair["sound_delivered"]
        assert (a["asset_id"], a["at_seconds"]) == ("oof", 4.0) and b["asset_id"] == "buzzer"
        ba, bb = plan["blocks"][a["block_index"]], plan["blocks"][b["block_index"]]
        assert ba["start"] <= 4.0 < ba["end"] and bb["start"] <= 8.0 < bb["end"]
        assert ba["sound"]["asset_id"] == "oof" and ba["asset"]["kind"] == "procedural"
        assert "SOUND s1 (damage): placed - oof at 4.00s on block" in result.stderr, result.stderr[-800:]
        assert "SOUND s2 (fail): placed - buzzer at 8.00s" in result.stderr, result.stderr[-800:]
        assert any(r["id"] == "mario-hit" and r["skipped"] for r in pair["inserts"])
        assert plan["meme"]["meme_requested"] == [], "no reactions[]: the meme layer wrote the empty pair"
        check_sound_pair({"sound_requested": pair["sound_requested"],
                          "sound_delivered": pair["sound_delivered"],
                          "inserts": pair["inserts"]}, "plan")
        assert [p["asset_id"] for p in sl.placed_sounds(plan)] == ["oof", "buzzer"]
        # The same plan without --script: the empty pair, nothing else different.
        out2 = tmp / "plan2.json"
        # CF-0137: --channel stays on this run too - what is dropped here is
        # the script (what the sound layer reads), not the permission that
        # lets an unfilled block be planned at all.
        result = subprocess.run(
            cmd[:-6] + [str(out2)] + cmd[-5:]
            + ["--channel", str(root / "channels" / "test.json")],
            capture_output=True, text=True, cwd=tmp, env=env, timeout=120)
        assert result.returncode == 0, result.stderr[-2000:]
        plan2 = json.loads(out2.read_text())
        assert plan2["sound"] == {"sound_requested": [], "sound_delivered": [], "inserts": [],
                                  "placed": [], "notes": []}
        stripped = [{k: v for k, v in b.items() if k != "sound"} for b in plan["blocks"]]
        assert stripped == plan2["blocks"]
        return plan


def test_build_render_plan_answers_no_asset_when_the_root_has_no_sound_spec():
    """A factory root without inserts/sound.json (the meme suite's roots, a
    bare checkout): the plan is still written, every request is counted
    and answered no_asset, and the reason is a note - never a failed render."""
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "03.json").write_text(json.dumps({"scripts": [script([S_DAMAGE, S_FAIL_FAR])]}))
        args = type("A", (), {"script": str(tmp / "03.json"), "script_id": "s1",
                              "channel": "test"})()
        os.environ["FACTORY_ROOT"] = str(tmp / "nowhere")
        try:
            res = brp.build_sound_layer(args, WORDS, copy.deepcopy(BLOCKS), "explainer", VOICE_END)
        finally:
            del os.environ["FACTORY_ROOT"]
        assert outcomes(res) == ["no_asset", "no_asset"], res
        assert res["sound_requested"] == [{"beat_id": "s1", "intent": "damage"},
                                          {"beat_id": "s2", "intent": "fail"}]
        assert res["placed"] == [] and res["inserts"] == [] and "unreadable" in res["notes"][0]
        check_sound_pair({"inserts": [], "sound_requested": res["sound_requested"],
                          "sound_delivered": res["sound_delivered"]}, "bare")


def test_write_batch_metadata_writes_the_pair_and_merges_provenance():
    plan = test_build_render_plan_carries_the_sound_on_its_block()
    qc = {"passed": True, "failures": [], "notes": []}
    v = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion")
    assert v["sound_requested"] == plan["sound"]["sound_requested"]
    assert v["sound_delivered"] == plan["sound"]["sound_delivered"]
    assert v["meme_requested"] == [] and v["meme_delivered"] == []
    placed_block = v["sound_delivered"][0]["block_index"]
    assert v["assets"][placed_block]["sound"] == "oof" and v["assets"][0]["sound"] is None
    check_sound_pair(v, "s1")
    # Underlay and meme records already there survive; a stale sound record
    # does not; the rerun is idempotent.
    other = {"kind": "loop", "id": "loop-1", "file": "l.mp4", "source_url": "https://x",
             "rights_holder": "y", "licence": None, "blacklist_check": {"skip": False},
             "skipped": False, "block": None, "layer": "underlay", "applied": True}
    meme = {**other, "kind": "meme", "id": "meme-1", "layer": "meme", "block": 1, "score": 0.3}
    stale = {**plan["sound"]["inserts"][0], "id": "stale-sound"}
    # CF-0127: the plan is handed in without its `underlay` key, because a
    # plan that ran that layer replaces its records the same way this one
    # replaces the sound's - an underlay record is foreign provenance only
    # on a plan built before that wiring (test_underlay_wiring.py has the
    # other direction).
    no_underlay = {k: val for k, val in plan.items() if k != "underlay"}
    v2 = write_batch_metadata.video_record("s1", no_underlay, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=[other, meme, stale])
    ids = [(r["layer"], r["id"]) for r in v2["inserts"]]
    assert ids[0] == ("underlay", "loop-1"), ids
    # The meme record is the meme layer's to replace - this plan ran that
    # layer and placed nothing, so its stale record goes the same way.
    assert ("meme", "meme-1") not in ids and ("sound", "stale-sound") not in ids
    assert ("sound", "oof") in ids and ("sound", "buzzer") in ids
    v3 = write_batch_metadata.video_record("s1", no_underlay, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=v2["inserts"])
    assert v3["inserts"] == v2["inserts"]
    check_sound_pair(v3, "s1")
    # A plan built before the layer existed: the empty pair, not a missing one.
    old = {k: val for k, val in plan.items() if k != "sound"}
    v4 = write_batch_metadata.video_record("s1", old, "/nowhere/s1.mp4", qc, "motion")
    assert v4["sound_requested"] == [] and v4["sound_delivered"] == []


def _read(path):
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
        step = 2 * w.getnchannels()  # CF-0695: the mix is dual-mono stereo; one channel is the mix
    return [struct.unpack("<h", raw[i:i + 2])[0] / 32767.0 for i in range(0, len(raw), step)]


def _db(samples):
    return 10 * math.log10(sum(x * x for x in samples) / max(1, len(samples)) + 1e-12)


def test_soundtrack_mixes_the_sound_as_a_fourth_input_and_qc_hears_it():
    """A 6s synthetic voice (220 Hz bursts with gaps) and one 0.4s sound at
    2.0s: the mix gains energy over the slot and is unchanged outside it; a
    plan with no placed sound mixes as before the layer existed (no
    _inserts.wav, same graph, samples within ffmpeg's own run-to-run
    noise); qc_render's gate hears the placed sound and not the missing one."""
    import numpy as np
    sys.path.insert(0, str(SCRIPTS))
    import build_soundtrack as bs
    import qc_render as qc
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sr = bs.SR
        t = np.arange(int(6 * sr)) / sr
        voice = 0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 1.0) < 0.6)
        bs.write_wav(tmp / "voice.wav", voice)
        ts = np.arange(int(0.4 * sr)) / sr
        bs.write_wav(tmp / "oof.wav", 0.9 * np.sin(2 * np.pi * 880 * ts))
        blocks = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}]
        placed = {"kind": "sound", "beat_id": "s1", "intent": "damage", "asset_id": "oof",
                  "file": str(tmp / "oof.wav"), "at_seconds": 2.0, "duration_s": 0.4,
                  "block_index": 0}
        plans = {"with": {"blocks": blocks, "sound": {"placed": [placed]}},
                 "without": {"blocks": blocks, "sound": {"placed": []}},
                 "old": {"blocks": blocks},
                 "gone": {"blocks": blocks, "sound": {"placed": [
                     {**placed, "file": str(tmp / "missing.wav")}]}}}
        outs = {}
        for name, plan in plans.items():
            plan["audio"] = {"src": str(tmp / "voice.wav")}
            (tmp / f"{name}.json").write_text(json.dumps(plan))
            work = tmp / name
            work.mkdir()
            r = subprocess.run([PY, str(SCRIPTS / "build_soundtrack.py"), str(tmp / "voice.wav"),
                                str(tmp / f"{name}.json"), str(work / "mix.wav")],
                               capture_output=True, text=True, timeout=120)
            assert r.returncode == 0, r.stderr[-1500:]
            outs[name] = (r.stdout, _read(work / "mix.wav"), (work / "_inserts.wav").exists())
        assert "1 sound(s) placed by the plan, mixed as the fourth input" in outs["with"][0]
        assert outs["with"][2] and not outs["without"][2] and not outs["old"][2]
        assert "none mixed" in outs["gone"][0] and "not mixed" in outs["gone"][0], outs["gone"][0]
        assert not outs["gone"][2], "a file gone from disk leaves the three-input graph alone"
        a, b = outs["with"][1], outs["without"][1]
        assert len(a) == len(b) == int(6 * sr)
        s0, s1 = int(2.0 * sr), int(2.4 * sr)
        assert _db(a[s0:s1]) > _db(b[s0:s1]) + 1.0, (_db(a[s0:s1]), _db(b[s0:s1]))
        outside = max(abs(x - y) for x, y in zip(a[:s0 - sr // 2] + a[s1 + sr:], b[:s0 - sr // 2] + b[s1 + sr:]))
        assert outside < 0.02, f"the mix outside the slot moved by {outside}"
        # The level: the sound sits SOUND_LEVEL_REL_VOICE_DB under the voice.
        assert "-3.0" in str(bs.SOUND_LEVEL_REL_VOICE_DB)
        line = next(l for l in outs["with"][0].splitlines() if "sound s1: oof" in l)
        sound_db, voice_db = [float(x) for x in
                              [line.split(", ")[-1].split(" dB")[0], line.split("voice ")[-1].split(" dB")[0]]]
        assert abs((sound_db - voice_db) - bs.SOUND_LEVEL_REL_VOICE_DB) < 0.3, line
        # Degradation: no sound == the mix from before the layer, within
        # ffmpeg's own run-to-run noise (no bit-exactness to lean on).
        c = outs["old"][1]
        assert max(abs(x - y) for x, y in zip(b, c)) < 0.02
        # QC: the gate hears the placed sound and fails the missing one.
        plan = json.loads((tmp / "with.json").read_text())
        heard = qc.sound_audibility_db(str(tmp / "with" / "mix.wav"), plan)
        assert len(heard) == 1 and heard[0]["voice_subtracted"] and heard[0]["rms_db"] > qc.MIN_SOUND_RMS_DB, heard
        silent = qc.sound_audibility_db(str(tmp / "without" / "mix.wav"), plan)
        assert silent[0]["rms_db"] is None or silent[0]["rms_db"] < qc.MIN_SOUND_RMS_DB, silent
        assert qc.sound_audibility_db(str(tmp / "old" / "mix.wav"), plans["old"]) == []
        assert qc.MIN_SOUND_RMS_DB == SPEC["mix"]["audibility"]["min_rms_db"]


def test_constants_match_the_spec():
    from common import (SOUND_DUCKS_BED, SOUND_DUCKS_VOICE, SOUND_FADE_IN_MS, SOUND_FADE_OUT_MS,
                        SOUND_LEVEL_REL_VOICE_DB, SOUND_MAX_PER_VIDEO, SOUND_PEAK_CEILING_DBFS)
    c = SPEC["mix"]["constants"]
    assert (SOUND_LEVEL_REL_VOICE_DB, SOUND_DUCKS_BED, SOUND_DUCKS_VOICE, SOUND_FADE_IN_MS,
            SOUND_FADE_OUT_MS, SOUND_PEAK_CEILING_DBFS, SOUND_MIN_GAP_SECONDS, SOUND_MAX_PER_VIDEO) == (
        c["SOUND_LEVEL_REL_VOICE_DB"], c["SOUND_DUCKS_BED"], c["SOUND_DUCKS_VOICE"],
        c["SOUND_FADE_IN_MS"], c["SOUND_FADE_OUT_MS"], c["SOUND_PEAK_CEILING_DBFS"],
        c["SOUND_MIN_GAP_SECONDS"], c["SOUND_MAX_PER_VIDEO"])
    sys.path.insert(0, str(REAL_ROOT / "shared" / "inserts"))
    import inserts_lib
    assert inserts_lib.MAX_SOUND_SECONDS == c["MAX_SOUND_SECONDS"] == SPEC["placement"]["max_insert_seconds"]
    assert tuple(sl.OUTCOMES) == tuple(SPEC["metadata"]["outcomes"])


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
