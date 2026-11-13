#!/usr/bin/env python3
"""CF-0127: the brainrot underlay in the second plane of the composition.

The decision half lives in the factory (`shared/inserts/underlay.py`, CF-0014,
covered by the root's tests/test_underlay_layer.py). What is checked here is
the *wiring*: that the answer reaches the frame, and that no answer leaves the
plan exactly as it was.

Everything runs on a temp FACTORY_ROOT - the convention underlay.py set - with
the real inserts_lib and the real underlay module copied in, a loops/index.json
of three entries (a 1 s lavfi mp4, a small PNG, and one held by a blacklisted
rights holder), and a channel config with `insert_layers.underlay.enabled`
true. The real shared/inserts/loops/index.json is empty until CF-0115 and is
never read; the real channels/example-film.json is read only for
its switch, as an implication (CF-0220).

What is checked:
  - layer_disabled on a copy of the real config with the switch off, and
    the real example-film switch read as an implication, not pinned
  - a video loop fills the band: `layout.secondary`, `secondary_source` with
    muted true, loop true, kind "clip", fit loop_or_trim and loops_needed
    covering the narration's span; an image stands as a still (loop false)
  - every not-applied answer (switch off, empty library, all blacklisted,
    file missing, a factory root with no underlay.py) leaves the band empty,
    writes no `secondary_source`, and leaves the plan identical apart from
    `plan["underlay"]` - and none of them raises
  - the same end to end through build_render_plan.py, and a build with the
    layer unreachable that is byte-identical to a build with it present and
    off, apart from the record
  - write_batch_metadata.video_record: `videos[].underlay` + the provenance
    in `inserts[]`, merged beside meme/sound records, idempotent on a rerun,
    and accepted by the root's own check_insert_provenance
  - the composition mounts the band only when the plan asks for it, muted,
    and stops it where the end card is mounted (CF-0117)
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import base64
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
RENDER_SRC = AGENT_ROOT / "render" / "src"
sys.path.insert(0, str(SCRIPTS))

import meme_layer as ml  # noqa: E402
import underlay_layer as ul  # noqa: E402
import write_batch_metadata  # noqa: E402
from common import FFMPEG  # noqa: E402
from repo_paths import VENV_PY3  # noqa: E402 - CF-0125: resolved against the main checkout

REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "shared" / "inserts" / "underlay.py").exists()), None)
assert REAL_ROOT is not None, "the factory root (shared/inserts/underlay.py) is not reachable"
VENV_PY = Path(VENV_PY3)
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

# 8x8 solid PNG, written byte for byte so the still case needs no encoder.
PNG_8x8 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAHUlEQVR42mP8z8Dwn4"
    "GKgHHUwFEDRw0cNXDUQEoBAP//AwAI/AL+Xob0GgAAAABJRU5ErkJggg==")

BLACKLISTED_HOLDER = "Nintendo / The Pokemon Company"

CLIP = {"id": "gameplay-loop", "file": "gameplay.mp4", "kind": "loop",
        "description": "endless runner gameplay, no audio", "tags": ["gameplay"],
        "source_url": "https://example.invalid/gameplay", "rights_holder": "A Studio",
        "added": "2026-09-06", "duration_s": 1.0}
STILL = {"id": "paint-still", "file": "paint.png", "kind": "loop",
         "description": "paint mixing, a single frame", "tags": ["oddly-satisfying"],
         "source_url": "https://example.invalid/paint", "rights_holder": "B Studio",
         "added": "2026-09-06"}
BLOCKED = {"id": "blocked-loop", "file": "blocked.mp4", "kind": "loop",
           "description": "gameplay from a holder on the blacklist", "tags": ["gameplay"],
           "source_url": "https://example.invalid/blocked", "rights_holder": BLACKLISTED_HOLDER,
           "added": "2026-09-06", "medium": "games_ip", "duration_s": 1.0}
ENTRIES = [CLIP, STILL, BLOCKED]

# CF-0137: this suite plans storyboards whose blocks are deliberately unfilled
# (that is the shape the layers under test attach to), and since CF-0137 a
# block with no picture refuses the plan unless the channel allows the
# per-block assetless rung. Test configs only - the refusal itself is pinned
# in tests/test_assetless_rung_gate.py, and the real channel file keeps the
# rung off.
RUNG_ON = {"enabled": True, "reason": "CF-0137 test config"}

CHANNEL_ON = {"channel_id": "test", "display_name": "Test Channel", "theme": STAND_IN_THEME, "insert_layers": {"underlay": {"enabled": True, "reason": "CF-0127 test config"},
                               "meme": {"enabled": False, "reason": "not under test"}},
              "assetless_block_rung": RUNG_ON}
CHANNEL_OFF = {"channel_id": "off", "display_name": "Test Channel", "theme": STAND_IN_THEME, "insert_layers": {"underlay": {"enabled": False, "reason": "not on this channel"},
                                "meme": {"enabled": False, "reason": "not under test"}},
               "assetless_block_rung": RUNG_ON}


def lavfi_mp4(path, seconds=1.0, size="240x240"):
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"testsrc2=size={size}:rate=15", "-t", str(seconds),
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=60)


def channel_list(root, channel):
    """CF-0630: where a channel's rights-holder list lives in a stand-in root
    (`channels/<id>/rights-holder-blacklist.json`, the channel's own data)."""
    d = Path(root) / "channels" / channel
    d.mkdir(parents=True, exist_ok=True)
    return d / "rights-holder-blacklist.json"


def make_root(tmp, entries=ENTRIES, with_underlay=True, name="factory", media=True):
    """A factory root under tmp with the real inserts_lib and underlay."""
    root = Path(tmp) / name
    inserts = root / "shared" / "inserts"
    loops = inserts / "loops"
    loops.mkdir(parents=True)
    shutil.copy(REAL_ROOT / "shared" / "inserts" / "inserts_lib.py", inserts / "inserts_lib.py")
    if with_underlay:
        shutil.copy(REAL_ROOT / "shared" / "inserts" / "underlay.py", inserts / "underlay.py")
    # CF-0630: the channel's rights-holder list is read through the root's
    # channel-data contract (underlay.py loads shared/channel_data.py from
    # beside its own folder, and that loads channel_ids.py from beside itself).
    for mod in ("channel_data.py", "channel_ids.py"):
        shutil.copy(REAL_ROOT / "shared" / mod, root / "shared" / mod)
    json.dump({"schema_note": "test", "kind": "loop", "embedding_model": None,
               "entries": entries}, open(loops / "index.json", "w"))
    if media:
        for e in entries:
            dest = loops / e["file"]
            if dest.suffix == ".png":
                dest.write_bytes(PNG_8x8)
            else:
                lavfi_mp4(dest)
    json.dump({"schema_note": "test", "last_updated": "2026-09-01",
               "entries": [{"rights_holder": BLACKLISTED_HOLDER, "medium": "games_ip",
                            "risk_level": "high", "reason": "test"}]},
              open(channel_list(root, "test"), "w"))
    json.dump(CHANNEL_ON, open(root / "channels" / "test.json", "w"))
    json.dump(CHANNEL_OFF, open(root / "channels" / "off.json", "w"))
    (root / "patterns").mkdir()
    for pid in ("explainer",):
        shutil.copy(REAL_ROOT / "patterns" / f"{pid}.json", root / "patterns" / f"{pid}.json")
    return root


def ids_for(root, wanted_id, span=20):
    """A video id whose rotation lands on `wanted_id` - the mapping is
    sha256(video_id) over the eligible entries, so the test asks the library
    which id it wants rather than hard-coding one."""
    sys.path.insert(0, str(Path(root) / "shared" / "inserts"))
    import inserts_lib
    for i in range(span * 10):
        vid = f"s{i:03d}"
        entry, _ = inserts_lib.choose_loop(vid, Path(root) / "shared" / "inserts",
                                           ul._module(root).load_blacklist(root, "test"))
        if entry and entry["id"] == wanted_id:
            return vid
    raise AssertionError(f"no video id in {span * 10} lands on {wanted_id}")


# --------------------------------------------------------------------------
# a plan to merge into, and the root's own contract check
# --------------------------------------------------------------------------

NARRATION = 8.0


def bare_plan():
    return {
        "style": "motion",
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "layout": {"main": {"fit": "cover"}, "secondary": None},
        "blocks": [{"start": 0.0, "end": NARRATION, "intent": "one",
                    "asset": {"kind": "still", "src": "/nowhere/a.png"}}],
        "duration": {"actual": NARRATION, "target": [1, 60]},
        "notes": [],
        "words": [],
    }


def check_provenance(v, ctx):
    """The root's own check, when the checkout is reachable."""
    path = REAL_ROOT / "tests" / "test_pipeline_contracts.py"
    if not path.exists():
        return
    spec = importlib.util.spec_from_file_location("test_pipeline_contracts", path)
    mod = importlib.util.module_from_spec(spec)
    # CF-0482: the root file imports its own helpers (_tmproot, CF-0378)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    mod.check_insert_provenance(v, ctx)


# --------------------------------------------------------------------------
# the decision, as this repo sees it
# --------------------------------------------------------------------------



def test_a_video_loop_fills_the_band_muted_and_looped():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        vid = ids_for(root, "gameplay-loop")
        rec = ul.plan_underlay(vid, CHANNEL_ON, root=root, video_seconds=NARRATION)
        assert rec["applied"] and rec["reason"] == "applied", rec
        assert rec["treatment"]["audio"] == "muted"
        assert rec["treatment"]["fit"] == "loop_or_trim"
        # 8 s of narration over a 1 s loop.
        assert rec["treatment"]["loops_needed"] == 8, rec["treatment"]

        plan = bare_plan()
        ul.apply_to_plan(plan, rec)
        assert plan["layout"]["secondary"] == {"height": ul.SECONDARY_HEIGHT, "kind": "underlay"}
        src = plan["secondary_source"]
        assert src["kind"] == "clip" and src["muted"] is True and src["loop"] is True
        assert src["src"] == rec["path"] and Path(src["src"]).exists()
        assert src["object_fit"] == "cover" and src["span"] == "narration"
        assert src["loops_needed"] == 8 and src["fit"] == "loop_or_trim"
        # The file the renderer stages, recorded on the plan's own record.
        assert plan["underlay"]["render_src"] == rec["path"]
        # The band takes its height out of main, exactly as layout.js does.
        main_h = 1920 - round(1920 * ul.SECONDARY_HEIGHT)
        import build_render_plan as brp
        assert brp.main_zone_height(1920, plan["layout"]) == main_h


def test_an_image_loop_stands_as_a_still():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        vid = ids_for(root, "paint-still")
        rec = ul.plan_underlay(vid, CHANNEL_ON, root=root, video_seconds=NARRATION)
        assert rec["applied"] and rec["media"] == "image"
        assert rec["treatment"]["fit"] == "still" and rec["treatment"]["loops_needed"] is None
        src = ul.secondary_source(rec)
        assert src["kind"] == "still" and src["loop"] is False and src["muted"] is True


def test_the_blacklisted_holder_is_never_the_underlay():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        for i in range(30):
            rec = ul.plan_underlay(f"v{i}", CHANNEL_ON, root=root, video_seconds=NARRATION)
            assert (rec["entry"] or {}).get("id") != "blocked-loop"
            skipped = [r for r in rec["inserts"] if r["skipped"]]
            assert [r["id"] for r in skipped] == ["blocked-loop"], rec["inserts"]


def _not_applied_cases(tmp):
    """(label, record) for every way the second plane stays empty."""
    root = make_root(tmp)
    empty = make_root(tmp, entries=[], name="empty")
    allskip = make_root(tmp, entries=[BLOCKED], name="allskip")
    missing = make_root(tmp, entries=[CLIP], name="missing", media=False)
    nomodule = make_root(tmp, entries=[CLIP], with_underlay=False, name="nomodule")
    vid = ids_for(root, "gameplay-loop")
    return [
        ("layer_disabled", ul.plan_underlay(vid, CHANNEL_OFF, root=root, video_seconds=NARRATION)),
        ("no switch at all", ul.plan_underlay(vid, {}, root=root, video_seconds=NARRATION)),
        ("library_empty", ul.plan_underlay(vid, CHANNEL_ON, root=empty, video_seconds=NARRATION)),
        ("all_skipped", ul.plan_underlay(vid, CHANNEL_ON, root=allskip, video_seconds=NARRATION)),
        ("file_missing", ul.plan_underlay(vid, CHANNEL_ON, root=missing, video_seconds=NARRATION)),
        ("no underlay.py", ul.plan_underlay(vid, CHANNEL_ON, root=nomodule, video_seconds=NARRATION)),
    ]


def test_nothing_applied_leaves_the_plan_as_it_was():
    """Every not-applied answer: no crash, an empty band, and a plan
    identical to the one the layer never touched apart from its record."""
    with tempfile.TemporaryDirectory() as tmp:
        cases = _not_applied_cases(tmp)
        reasons = {rec["reason"] for _, rec in cases}
        assert reasons == {"layer_disabled", "library_empty", "all_skipped", "file_missing"}, reasons
        for label, rec in cases:
            assert rec["applied"] is False, label
            before = bare_plan()
            plan = copy.deepcopy(before)
            ul.apply_to_plan(plan, rec)
            assert "secondary_source" not in plan, label
            assert plan["layout"]["secondary"] is None, label
            assert plan.pop("underlay")["reason"] == rec["reason"], label
            assert plan == before, f"{label}: the layer changed the plan it did not apply to"
            # A summary line is written for the empty slot too - a video with
            # no underlay is a fact, not a silence.
            assert "UNDERLAY: none" in ul.report_line(rec), label


# --------------------------------------------------------------------------
# end to end through build_render_plan.py
# --------------------------------------------------------------------------

def _silent_wav(path, seconds, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


WORDS = [{"word": w, "start": round(i * 0.5, 2), "end": round(i * 0.5 + 0.45, 2)}
         for i, w in enumerate(
             "the hook here and then the commentary says this is absurd frankly again "
             "and more words follow right here".split())]


def build_plan(tmp, root, channel, out_name="plan.json", video_id="s000"):
    """One real build_render_plan.py run on a typographic storyboard (no
    footage, no Vision), against the given factory root and channel."""
    tmp = Path(tmp)
    _silent_wav(tmp / "voice.wav", NARRATION)
    (tmp / "words.json").write_text(json.dumps(WORDS))
    # CF-0314: three blocks and not two. `explainer`'s pace band now orders its
    # floor (15.39 blocks/min), and two blocks over 8s of narration is 15 - so
    # the two-block storyboard this file used to build would be refused before
    # the render, by a gate that has nothing to do with the underlay layer.
    # Three blocks over the same narration is ~22 blocks/min, inside the band.
    def _block(first, last):
        return {"word_range": [first, last], "intent": "step",
                "asset_kind": "typographic",
                "unfilled_reason": "no shot in any index", "emphasis_words": [],
                "rhythm_role": "beat", "side": None, "shot": None,
                "held_frame": False}

    sb = [_block(0, 6), _block(7, 12), _block(13, len(WORDS) - 1)]
    story = {"script_id": video_id, "style": "motion", "resolved_from_anchors": False,
             "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "even",
                        "rhythm_built": "even", "parameters": {"block_count": 3},
                        "opening_requested": None, "opening_delivered": None,
                        "anchor_count": 0},
             "blocks": sb, "unresolved_anchors": [], "rejected_candidates": []}
    (tmp / "storyboard.json").write_text(json.dumps(story))
    out = tmp / out_name
    env = dict(os.environ, FACTORY_ROOT=str(root))
    cmd = [PY, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
           str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
           "--style", "motion", "--target-duration", "1", "60",
           "--channel", str(channel)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp, env=env, timeout=240)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(out.read_text()), result.stderr


def test_build_render_plan_puts_the_loop_in_the_second_plane():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        vid = ids_for(root, "gameplay-loop")
        plan, err = build_plan(tmp, root, root / "channels" / "test.json", video_id=vid)
        rec = plan["underlay"]
        assert rec["applied"] and rec["entry"]["id"] == "gameplay-loop", rec
        assert plan["layout"]["secondary"] == {"height": ul.SECONDARY_HEIGHT, "kind": "underlay"}
        src = plan["secondary_source"]
        assert src["kind"] == "clip" and src["muted"] is True and src["loop"] is True
        assert Path(src["src"]).exists()
        # Sized against the narration, not the composition (CF-0117).
        assert rec["treatment"]["loops_needed"] == int(-(-plan["duration"]["actual"] // 1.0))
        assert "UNDERLAY: gameplay-loop in the second plane" in err, err[-800:]
        assert rec["inserts"] and rec["inserts"][-1]["applied"] is True
        return plan


def test_a_build_with_the_layer_off_is_identical_to_one_without_the_layer():
    """The promise the acceptance criterion makes for example-film: with
    the switch off nothing about the render changes. Checked against a root
    where the layer cannot run at all - the two plans differ in exactly one
    key, `underlay`, and in nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        bare = make_root(tmp, with_underlay=False, name="nolayer")
        off, _ = build_plan(tmp, root, root / "channels" / "off.json", "plan_off.json")
        none, _ = build_plan(tmp, bare, bare / "channels" / "off.json", "plan_none.json")
        assert off["underlay"]["reason"] == "layer_disabled"
        assert none["underlay"]["reason"] == "layer_disabled"
        assert off["layout"]["secondary"] is None and "secondary_source" not in off
        off.pop("underlay")
        none.pop("underlay")
        # CF-0415: build_inputs.digest hashes the build's arguments with the
        # roots' paths still in them (`--channel` names factory/... here and
        # nolayer/... there), so it differs for the same reason the text
        # below needs <ROOT> - and a hash cannot be normalised. What it was
        # taken over, build_inputs.inputs, stays in and is compared like the
        # rest of the plan.
        assert off["build_inputs"]["digest"] and none["build_inputs"]["digest"]
        del off["build_inputs"]["digest"], none["build_inputs"]["digest"]
        # Byte for byte, with the two roots' own paths normalised away - they
        # are named in the end-card note, and which temp directory the run
        # read its channel out of is not what this test is about.
        a = json.dumps(off, indent=2).replace(str(root), "<ROOT>")
        b = json.dumps(none, indent=2).replace(str(bare), "<ROOT>")
        assert a == b, "the layer changed a plan it did not apply to"


# --------------------------------------------------------------------------
# 05-video-editor.json
# --------------------------------------------------------------------------

def test_metadata_carries_the_record_and_the_provenance():
    plan = test_build_render_plan_puts_the_loop_in_the_second_plane()
    qc = {"passed": True, "failures": [], "notes": []}
    v = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion")
    assert v["underlay"]["applied"] is True and v["underlay"]["reason"] == "applied"
    assert v["underlay"]["id"] == "gameplay-loop" and v["underlay"]["file"] == "gameplay.mp4"
    assert v["underlay"]["treatment"]["audio"] == "muted"
    used = [r for r in v["inserts"] if r["layer"] == "underlay" and not r["skipped"]]
    assert [r["id"] for r in used] == ["gameplay-loop"], v["inserts"]
    assert all(r["source_url"] and r["rights_holder"] for r in v["inserts"])
    check_provenance(v, "s1")

    # A stale underlay record from a previous write is this layer's to
    # replace; another layer's records are not this layer's to touch.
    meme = {"kind": "meme", "id": "meme-1", "file": "m.png", "source_url": "https://x",
            "rights_holder": "y", "licence": None, "blacklist_check": {"skip": False},
            "skipped": False, "block": 1, "layer": "meme", "applied": True, "score": 0.3}
    stale = {**meme, "kind": "loop", "id": "old-loop", "layer": "underlay", "block": None}
    merged = ul.merge_inserts([meme, stale], plan["underlay"]["inserts"])
    assert [(r["layer"], r["id"]) for r in merged][0] == ("meme", "meme-1")
    assert ("underlay", "old-loop") not in [(r["layer"], r["id"]) for r in merged]
    # Through the whole record: the meme record here goes too, but by the
    # meme layer's own merge - this plan ran that layer and placed nothing.
    v2 = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=[meme, stale],
                                           existing_underlay={"applied": True, "id": "old-loop"})
    ids = [(r["layer"], r["id"]) for r in v2["inserts"]]
    assert ("underlay", "old-loop") not in ids, ids
    assert ("underlay", "gameplay-loop") in ids
    assert v2["underlay"]["id"] == "gameplay-loop", "the plan answers for its own layer"
    v3 = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=v2["inserts"],
                                           existing_underlay=v2["underlay"])
    assert v3["inserts"] == v2["inserts"] and v3["underlay"] == v2["underlay"]
    check_provenance(v3, "s1")


def test_metadata_of_a_video_with_no_underlay():
    """An empty second plane is recorded as one, and a plan built before the
    layer existed keeps whatever the record already carried."""
    qc = {"passed": True, "failures": [], "notes": []}
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        plan, _ = build_plan(tmp, root, root / "channels" / "off.json")
    v = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion")
    assert v["underlay"]["applied"] is False and v["underlay"]["reason"] == "layer_disabled"
    assert [r for r in v["inserts"] if r["layer"] == "underlay"] == []
    check_provenance(v, "s1")

    old = {k: val for k, val in plan.items() if k != "underlay"}
    kept = {"applied": True, "reason": "applied", "id": "old-loop", "file": "o.mp4",
            "treatment": {"audio": "muted", "fit": "loop_or_trim", "loops_needed": 2},
            "library": {}, "note": ""}
    v2 = write_batch_metadata.video_record("s1", old, "/nowhere/s1.mp4", qc, "motion",
                                           existing_underlay=kept)
    assert v2["underlay"] == kept, "a plan that never ran the layer answers for nothing"


# --------------------------------------------------------------------------
# the composition
# --------------------------------------------------------------------------

def test_the_composition_mounts_the_band_only_when_the_plan_asks():
    """The three invariants the JSX owes the plan, read off the source: the
    band is mounted only for a non-null `zones.secondary` (so an unapplied
    layer draws nothing at all), the clip is always muted whatever the prop
    says, and the band stops where the end card is mounted."""
    video = (RENDER_SRC / "Video.jsx").read_text()
    zone = (RENDER_SRC / "components" / "SecondaryZone.jsx").read_text()
    assert "{zones.secondary && underlayFrames > 0 ? (" in video, (
        "the band is mounted unconditionally")
    assert "const underlayFrames = card ? cardFrom : durationInFrames;" in video, (
        "the band does not stop where the end card is mounted (CF-0117)")
    assert "<Sequence from={0} durationInFrames={underlayFrames} layout=\"none\">" in video
    assert "<SecondaryZone zone={zones.secondary} source={plan.secondary_source} />" in video
    assert "<OffthreadVideo src={src(source.src)} muted loop={source.loop !== false}" in zone, (
        "the underlay clip is not unconditionally muted")
    assert "if (!zone) return null;" in zone
    # And the plan's own prop names are the ones the component switches on.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        rec = ul.plan_underlay(ids_for(root, "gameplay-loop"), CHANNEL_ON,
                               root=root, video_seconds=NARRATION)
        src = ul.secondary_source(rec)
    assert src["kind"] == "clip" and "source.kind === 'clip'" in zone
    for key, read_as in (("src", "source.src"), ("loop", "source.loop"),
                         ("object_fit", "source?.object_fit")):
        assert key in src and read_as in zone, key


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
