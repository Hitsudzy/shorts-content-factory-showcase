#!/usr/bin/env python3
"""CF-0118: the gate of two independent footage sources.

A video whose entire picture comes from one upload is a "compilation with
no original content added" - the thing YouTube's policy names as not even
eligible for the Creator Pool. What makes the gate honest is the definition
under it: "one source" is CF-0080's *canonical* source, so the three
re-uploads of one trailer that a search returns count once, not three
times. That is the case these tests exist for - the arithmetic 2 >= 2 is
not the hard part, the dedup is.

Synthetic and fast (a couple of seconds): the unit tests build plan dicts
and alias tables by hand, and the two end-to-end runs go through
`build_render_plan.main()` in-process with `subprocess.run` replaced for
the asset tools, the way tests/test_asset_tool_timeout.py does - this suite
is about the gate, not about qc_asset.py's verdicts.

Real batches are measured by hand, not here: see SKILL.md (the two-source
gate) and the CF-0118 report for the numbers that keep the channel default
on `measure`.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import source_gate  # noqa: E402
import build_render_plan as brp  # noqa: E402
import write_batch_metadata  # noqa: E402

REAL_RUN = subprocess.run

# Two ids of the same shape a real one has (11 chars). A and B are two
# different trailers; B2 is a re-upload of B - which is exactly what
# `2026-09-03T2037Z`'s Wren Hollow teaser was (the RUN_LOG calls
# GyEpwGQIEZw / SJVmeJaS44s "two uploads of ONE teaser").
A = "AAAAAAAAAAA"
B = "BBBBBBBBBBB"
B2 = "BBBBBBBBBB2"


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"ok: {msg}")


def clip_block(vid, shot=1, kind="clip", index=0, with_shot=True):
    """A plan block the way build_render_plan.py writes one: the `shot` key
    the rhythm needs, and the cut clip's own filename under `asset.src`."""
    b = {"start": index * 2.0, "end": index * 2.0 + 2.0, "intent": "",
         "asset": {"kind": kind, "src": f"/w/clips/a{index:02d}_{vid}_s{shot:03d}.mp4"}}
    if with_shot:
        b["shot"] = f"{vid}:{shot}"
    return b


def typographic_block(index=0, shot=None):
    b = {"start": index * 2.0, "end": index * 2.0 + 2.0, "intent": "",
         "asset": {"kind": "typographic", "text": "a card of our own"}}
    if shot:
        b["shot"] = shot
    return b


def plan_of(*blocks):
    return {"style": "motion", "blocks": list(blocks)}


# --------------------------------------------------------------------------
# item 1: what an independent source is
# --------------------------------------------------------------------------

def test_two_sources_pass():
    plan = plan_of(clip_block(A, 1, index=0), clip_block(B, 4, index=1),
                   clip_block(A, 2, index=2))
    rec = source_gate.judge(plan)
    _check(rec["canonical_ids"] == [A, B], f"both sources counted: {rec['canonical_ids']}")
    _check(rec["count"] == 2 and rec["passed"] is True, "two sources pass the gate")
    _check(rec["blocks_by_source"] == {A: [0, 2], B: [1]},
           f"which blocks came from which source: {rec['blocks_by_source']}")
    _check(rec["aliased_away"] == [], "nothing was collapsed")


def test_one_source_fails():
    plan = plan_of(*[clip_block(A, i, index=i) for i in range(5)])
    rec = source_gate.judge(plan)
    _check(rec["count"] == 1 and rec["passed"] is False, "one source fails the gate")
    _check("compilation with no original content added" in rec["note"],
           "the note says why, in the policy's own words")
    d = source_gate.deficit(rec)
    _check(d["kind"] == "two_source_gate", "the deficit is machine-readable by kind")
    _check(d["missing_sources"] == 1 and d["blocks"] == [0, 1, 2, 3, 4],
           f"the deficit says how short and over which blocks: {d}")


def test_two_reuploads_of_one_trailer_count_as_one_source():
    """The case the whole task turns on. Two ids, two different files on
    disk, one trailer - the gate must not read that as two sources."""
    plan = plan_of(clip_block(B, 1, index=0), clip_block(B2, 7, index=1),
                   clip_block(B, 3, index=2))
    naive = source_gate.judge(plan)
    _check(naive["count"] == 2 and naive["passed"] is True,
           "without an alias table the two ids are two sources (the CF-0080 bug)")

    aliases = source_gate.load_aliases({"aliases": [
        {"topic_id": "t1", "video_id": B2, "alias_of": B, "distance": 3.4}]})
    rec = source_gate.judge(plan, aliases=aliases)
    _check(rec["count"] == 1 and rec["passed"] is False,
           "with CF-0080's table the re-upload collapses and the gate fails")
    _check(rec["canonical_ids"] == [B], f"the canonical id survives: {rec['canonical_ids']}")
    _check(rec["aliased_away"] == [{"video_id": B2, "alias_of": B}],
           f"what was collapsed is written down, not assumed: {rec['aliased_away']}")
    _check(rec["blocks_by_source"] == {B: [0, 1, 2]},
           "all three blocks are attributed to the canonical source")


def test_the_three_alias_shapes_and_a_chain():
    """`01b-footage-index.json`, `work/footage-aliases.json` and a plain
    --alias-groups file all mean the same thing to the gate; an alias of an
    alias resolves to the head of the group."""
    plan = plan_of(clip_block(B, 1, index=0), clip_block(B2, 2, index=1))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        index_json = tmp / "01b-footage-index.json"
        index_json.write_text(json.dumps(
            {"batch": str(tmp), "fetched": [{"video_id": B}],
             "aliases": [{"topic_id": "t1", "video_id": B2, "alias_of": B,
                          "distance": 5.1}]}))
        by_topic = tmp / "footage-aliases.json"
        by_topic.write_text(json.dumps(
            {"t1": [{"video_id": B2, "alias_of": B, "distance": 5.1}]}))
        groups = tmp / "groups.json"
        groups.write_text(json.dumps([[B, B2, "CCCCCCCCCCC"]]))
        mapping = tmp / "mapping.json"
        mapping.write_text(json.dumps({B: [B2]}))

        for path in (index_json, by_topic, groups, mapping):
            rec = source_gate.judge(plan, aliases=source_gate.load_aliases(path))
            _check(rec["count"] == 1 and not rec["passed"],
                   f"{path.name}: the re-upload collapses")

        # an alias of an alias, and a cycle that must not hang
        chain = source_gate.load_aliases([["x", "y"], ["y", "z"]])
        _check(source_gate.canonical("z", chain) == "x", "a chain resolves to the head")
        _check(source_gate.canonical("p", {"p": "q", "q": "p"}) in ("p", "q"),
               "a cycle terminates instead of hanging")

        # a table that is not there at all means "no known duplicates"
        _check(source_gate.load_aliases(tmp / "nope.json") == {},
               "a missing alias table is not an error")


def test_the_source_is_read_from_whatever_names_it():
    """A block's `shot` key, a cut clip's filename, a held frame's, a
    shots.json `source` header - and an old batch's nameless clip, which is
    reported as unidentified rather than guessed at."""
    ids = {
        "W4mvmBXg9Nc:8": "W4mvmBXg9Nc",
        "/w/clips/a00_6fcoM7Q348Q_s005.mp4": "6fcoM7Q348Q",
        "/w/clips/nc01_W4mvmBXg9Nc_s008.mp4": "W4mvmBXg9Nc",
        "/w/clips/s01_held_a01_eokBqEFiVHs_s011.png": "eokBqEFiVHs",
        # ids that contain the separator themselves
        "/w/clips/a02_f_bKjZeJBBI_s010.mp4": "f_bKjZeJBBI",
        "/w/clips/a00_ZZ_urA56pJE_s057.mp4": "ZZ_urA56pJE",
        "/shared/footage/-xSxaE1ClEE.mp4": "-xSxaE1ClEE",
        "/w/clips/s0.mp4": None,
    }
    for value, want in ids.items():
        got = source_gate.source_id(value)
        _check(got == want, f"source_id({value!r}) -> {got!r} (wanted {want!r})")

    plan = plan_of({"start": 0, "end": 2, "asset": {"kind": "clip", "src": "/w/s0.mp4"}})
    rec = source_gate.judge(plan)
    _check(rec["unidentified_blocks"] == [0] and rec["count"] == 0,
           "footage with no nameable source counts towards nothing and is listed")
    _check(rec["passed"] is False, "and cannot pass the gate")


def test_a_split_block_has_two_sources():
    """CF-0050's side_by_side opening: two halves, two sources, in one
    block - the block that most obviously is not single-source."""
    plan = plan_of({"start": 0, "end": 4, "asset": {
        "kind": "split",
        "halves": [{"src": f"/w/clips/a00_{A}_s001.mp4", "shot": f"{A}:1"},
                   {"src": f"/w/clips/a00_{B}_s002.mp4", "shot": f"{B}:2"}]}})
    rec = source_gate.judge(plan)
    _check(rec["count"] == 2 and rec["passed"], f"both halves counted: {rec['canonical_ids']}")


def test_a_degraded_block_does_not_carry_its_old_source_on_screen():
    """CF-0031: a block dropped to `typographic` keeps its `shot` for the
    rhythm's sake. What it shows is our own type, so it must not be counted
    as somebody's footage - otherwise a video of nothing but cards could
    claim two trailers it never put on screen."""
    plan = plan_of(clip_block(A, 1, index=0),
                   typographic_block(index=1, shot=f"{B}:4"))
    rec = source_gate.judge(plan)
    _check(rec["canonical_ids"] == [A], f"only the block that shows footage counts: {rec}")
    _check(rec["passed"] is False, "and one source on screen fails")


def test_a_video_with_no_footage_at_all_is_not_a_compilation():
    """The bottom rung of the degradation chain: every block typographic.
    Nothing was borrowed, so the single-source rule has nothing to bite on -
    failing it would refuse the pipeline's own fallback."""
    plan = plan_of(typographic_block(index=0), typographic_block(index=1))
    rec = source_gate.judge(plan, mode=source_gate.MODE_ENFORCE)
    _check(rec["applies"] is False, "the gate does not apply")
    _check(rec["passed"] is True and rec["count"] == 0,
           f"and does not reject a video with no borrowed footage: {rec['note']}")


def test_indexes_name_the_media_behind_each_id():
    with tempfile.TemporaryDirectory() as tmp:
        shots = Path(tmp) / f"{A}.shots.json"
        shots.write_text(json.dumps(
            {"source": f"/shared/footage/{A}.mp4", "fingerprint": {"kind": "dhash9x8"},
             "shots": []}))
        found = source_gate.independent_sources(
            plan_of(clip_block(A, 1)), [str(shots), "/nope/missing.json"])
        _check(found["index_sources"][A]["source"] == f"/shared/footage/{A}.mp4",
               "the shots.json header is read for the media path")
        _check(found["index_sources"][A]["fingerprint"] == {"kind": "dhash9x8"},
               "and CF-0080's fingerprint header rides with it")
        _check(len(found["index_sources"]) == 1, "an unreadable index is skipped, not fatal")


def test_the_mode_comes_from_the_channel_and_defaults_to_measure():
    _check(source_gate.mode_from_channel(None) == "measure",
           "no channel config at all -> measure")
    _check(source_gate.mode_from_channel({"video_editor": {}}) == "measure",
           "a channel that says nothing -> measure (the CF-0118 default)")
    _check(source_gate.mode_from_channel(
        {"video_editor": {"two_source_gate": "enforce"}}) == "enforce",
        "the channel key flips it")
    _check(source_gate.mode_from_channel(
        {"video_editor": {"two_source_gate": {"mode": "enforce", "required": 3}}}) == "enforce",
        "the block form works too")
    _check(source_gate.required_from_channel(
        {"video_editor": {"two_source_gate": {"mode": "enforce", "required": 3}}}) == 3,
        "and can raise the floor")
    _check(source_gate.mode_from_channel(
        {"video_editor": {"two_source_gate": "ENFORCE!"}}) == "measure",
        "a typo falls back to measure rather than rejecting every plan")


# --------------------------------------------------------------------------
# item 2: through build_render_plan.main()
# --------------------------------------------------------------------------

USABLE = {"usable": True, "failures": [], "failed": [], "relaxations": [],
          "short_side": 1080, "upscale_factor": 1.0}
CROP = {"roi": {"x": 660, "y": 240, "width": 600, "height": 600},
        "source_size": {"width": 1920, "height": 1080},
        "roi_coverage": 0.95, "roi_source": "saliency", "zoom": 1.0}


@contextlib.contextmanager
def stub_asset_tools():
    """qc_asset.py and smart_crop.py answer "fine" without running. Same
    device as tests/test_asset_tool_timeout.py's `hanging()`: these tests
    are about the gate, and a real Vision pass per block would make them
    minutes instead of seconds."""
    def fake(cmd, *a, **kw):
        if any("qc_asset.py" in str(p) for p in cmd):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(USABLE), "")
        if any("smart_crop.py" in str(p) for p in cmd):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(CROP), "")
        return REAL_RUN(cmd, *a, **kw)

    subprocess.run = fake
    try:
        yield
    finally:
        subprocess.run = REAL_RUN


def _silent_wav(path, seconds=4.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += int(2000 if (i // 40) % 2 else -2000).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _fixture(tmp, sources):
    """A storyboard of one still per entry of `sources`, named the way
    resolve_anchors.py names a held frame."""
    from PIL import Image
    tmp = Path(tmp)
    _silent_wav(tmp / "voice.wav")
    words = [{"word": f"w{i}", "start": round(0.2 + i * 0.5, 2),
              "end": round(0.6 + i * 0.5, 2)} for i in range(2 * len(sources))]
    (tmp / "words.json").write_text(json.dumps(words))
    blocks = []
    for i, vid in enumerate(sources):
        still = tmp / f"s{i:02d}_held_a{i:02d}_{vid}_s{i + 1:03d}.png"
        Image.new("RGB", (1920, 1080), (100 + 10 * i, 140, 160)).save(still)
        blocks.append({"word_range": [2 * i, 2 * i + 1], "intent": f"block {i}",
                       "asset_kind": "still", "asset": str(still),
                       "shot": f"{vid}:{i + 1}", "held_frame": True,
                       "emphasis_words": []})
    (tmp / "storyboard.json").write_text(json.dumps(
        {"script_id": "cf-0118", "style": "motion", "blocks": blocks}))
    return tmp / "storyboard.json", tmp / "words.json", tmp / "voice.wav"


def _run_main(tmp, sources, extra=()):
    story, words, voice = _fixture(tmp, sources)
    out = Path(tmp) / "plan.json"
    argv = sys.argv
    sys.argv = ["build_render_plan.py", str(story), str(words), str(voice), str(out),
                "--style", "motion", "--target-duration", "1", "60", *extra]
    err, code = io.StringIO(), 0
    try:
        with stub_asset_tools(), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                brp.main()
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = argv
    return code, err.getvalue(), out


def test_measure_records_the_verdict_and_rejects_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        code, err, out = _run_main(tmp, [A, A, A])
        _check(code == 0, f"a single-source plan is still written in measure mode\n{err[-1500:]}")
        _check(out.exists(), "plan.json is on disk")
        plan = json.loads(out.read_text())
        rec = plan["two_source_gate"]
        _check(rec["passed"] is False and rec["count"] == 1 and rec["mode"] == "measure",
               f"the verdict is recorded: {rec}")
        _check(rec["canonical_ids"] == [A], f"and names the source: {rec['canonical_ids']}")
        _check("two-source gate FAILED (measure)" in err, "one line on stderr either way")
        # The verdict is the whole of what a measured gate reports. It must
        # not turn up in `rhythm_shortfalls`: that list is CF-0057's record
        # of *rhythm* deficits, and a run that returns nobody's script has
        # not produced a deficit for the Analyst to act on. (The real
        # `wren-hollow-lockhart` plan is pinned block by block against that
        # list in tests/test_openings_and_sides.py; a measured gate that
        # appends to it silently rewrites that plan's rhythm record.)
        kinds = [s["kind"] for s in plan["rhythm"]["rhythm_shortfalls"]]
        _check("two_source_gate" not in kinds,
               f"measure adds no deficit to the CF-0057 shortfall list: {kinds}")
        _check(plan["rhythm"]["rhythm_delivered_fully"] is True,
               "and does not flip the rhythm's own verdict - a delivered rhythm "
               "stays delivered when the footage sourcing is what failed")
        # CF-0136 re-check: `rhythm_delivered_fully` is True here for a
        # reason that survives the new shortfall kinds, not by luck. Every
        # block of this plan carries a clip, so there is nothing on the
        # assetless rung for `picture_absent_blocks` to record. If a change
        # ever puts a stub in this fixture, the True above is wrong and this
        # line says which of the two facts moved.
        _check(plan["rhythm"]["picture"]["assetless_blocks"] == 0,
               f"every block of this plan has a picture: {plan['rhythm']['picture']}")
        _check("picture_absent_blocks" not in kinds,
               f"and so nothing is recorded as absent: {kinds}")
        _check(not any("compilation" in d for d in plan["rhythm"]["deviations"]),
               "nor does it turn up as a rhythm deviation")
        _check(not (Path(tmp) / "plan.two-source-gate.json").exists(),
               "measure writes no rejection sidecar")
        # CF-0330: and the failure is a warning record like the other warned
        # gates', with the gate's code and numbers.
        ws = [w for w in plan.get("warnings") or [] if w["gate"] == "two_source_gate"]
        _check(len(ws) == 1, f"one two-source warning on the plan: {plan.get('warnings')}")
        _check(ws[0]["reason_code"] == "no_second_source" and ws[0]["severity"] == "warn"
               and ws[0]["numbers"]["count"] == 1 and ws[0]["numbers"]["required"] == 2
               and ws[0]["numbers"]["mode"] == "measure",
               f"the warning carries the code and the numbers: {ws[0]}")


def test_measure_passes_two_sources_and_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        code, err, out = _run_main(tmp, [A, B, A])
        _check(code == 0, f"plan written\n{err[-1500:]}")
        plan = json.loads(out.read_text())
        rec = plan["two_source_gate"]
        _check(rec["passed"] is True and rec["count"] == 2, f"two sources pass: {rec}")
        _check(rec["blocks_by_source"] == {A: [0, 2], B: [1]},
               f"the plan records which block came from where: {rec['blocks_by_source']}")
        _check("two-source gate passed (measure)" in err, "the passing line is on stderr too")
        _check([s["kind"] for s in plan["rhythm"]["rhythm_shortfalls"]] == [],
               "a passing gate adds no deficit")


def test_the_shortfall_list_stays_the_rhythms_own_in_either_mode():
    """The same plan built twice - `measure` and a passing `enforce` - and
    neither leaves a `two_source_gate` record in `rhythm_shortfalls`. The
    failing `enforce` case cannot be checked here because it writes no plan
    at all; its deficit is the sidecar, and the test below reads it there."""
    for extra, label in (([], "measure"),
                         (["--two-source-gate", "enforce"], "enforce (passing)")):
        with tempfile.TemporaryDirectory() as tmp:
            code, err, out = _run_main(tmp, [A, A, B], extra=extra)
            _check(code == 0, f"{label}: plan written\n{err[-1200:]}")
            plan = json.loads(out.read_text())
            _check(not any(s.get("kind") == source_gate.DEFICIT_KIND
                           for s in plan["rhythm"]["rhythm_shortfalls"]),
                   f"{label}: the rhythm's shortfall list is the rhythm's alone: "
                   f"{plan['rhythm']['rhythm_shortfalls']}")
            _check(isinstance(plan["two_source_gate"], dict)
                   and plan["two_source_gate"]["mode"] in ("measure", "enforce"),
                   f"{label}: and the verdict is on the plan where it belongs")


def test_enforce_refuses_the_plan_with_the_deficit_and_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        code, err, out = _run_main(tmp, [A, A], extra=["--two-source-gate", "enforce"])
        _check(code == 2, f"exit 2, the same path a rejected asset takes - got {code!r}\n{err[-1500:]}")
        _check("TWO-SOURCE GATE FAILED - plan not written" in err, "the refusal line")
        _check(not out.exists(), "no plan.json")
        _check("Traceback" not in err, "no traceback")
        side = Path(tmp) / "plan.two-source-gate.json"
        _check(side.exists(), "the deficit is written where the plan would have been")
        rec = json.loads(side.read_text())
        _check(rec["deficit"]["kind"] == "two_source_gate", "machine-readable by kind")
        _check(rec["deficit"]["missing_sources"] == 1 and rec["deficit"]["blocks"] == [0, 1],
               f"it says how short, and over which blocks: {rec['deficit']}")
        _check(rec["two_source_gate"]["mode"] == "enforce", "and in which mode")
        # The returned script's deficit lives here and only here: there is no
        # plan file to carry it, and `measure` never produces one.
        _check(set(rec["deficit"]) >= {"kind", "count", "required", "canonical_ids",
                                       "blocks", "missing_sources", "note"},
               f"in the CF-0057 shortfall shape: {sorted(rec['deficit'])}")


def test_enforce_lets_two_real_sources_through_and_the_alias_file_collapses_them():
    """The same two-id plan, twice: with no alias table it passes, with
    CF-0080's table (fed in as a --alias-groups file, the way a pre-CF-0080
    batch is measured) the two ids are one trailer and it is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        code, err, out = _run_main(tmp, [B, B2], extra=["--two-source-gate", "enforce"])
        _check(code == 0, f"two ids, no known duplicate -> the plan is built\n{err[-1200:]}")
        _check(json.loads(out.read_text())["two_source_gate"]["passed"] is True, "and passes")

    with tempfile.TemporaryDirectory() as tmp:
        groups = Path(tmp) / "groups.json"
        groups.write_text(json.dumps([[B, B2]]))
        code, err, out = _run_main(tmp, [B, B2], extra=[
            "--two-source-gate", "enforce", "--alias-groups", str(groups)])
        _check(code == 2, f"the same plan is refused once the re-upload is known\n{err[-1200:]}")
        _check(f"{B2} counted as {B}" in err, "and stderr says which id was collapsed")
        side = json.loads((Path(tmp) / "plan.two-source-gate.json").read_text())
        _check(side["deficit"]["aliased_away"] == [{"video_id": B2, "alias_of": B}],
               f"the deficit carries the collapse: {side['deficit']['aliased_away']}")


# --------------------------------------------------------------------------
# item 2: the batch metadata
# --------------------------------------------------------------------------

def _root_checks():
    for p in AGENT_ROOT.resolve().parents:
        path = p / "tests" / "test_pipeline_contracts.py"
        if path.exists():
            spec = importlib.util.spec_from_file_location("test_pipeline_contracts", path)
            mod = importlib.util.module_from_spec(spec)
            # CF-0482: the root file imports its own helpers (_tmproot, CF-0378)
            if str(path.parent) not in sys.path:
                sys.path.insert(0, str(path.parent))
            spec.loader.exec_module(mod)
            return mod
    return None


ROOT_CHECKS = _root_checks()


def test_the_batch_record_carries_the_gate():
    qc = {"passed": True, "failures": [], "notes": []}
    with tempfile.TemporaryDirectory() as tmp:
        code, err, out = _run_main(tmp, [A, B])
        _check(code == 0, f"plan written\n{err[-1200:]}")
        plan = json.loads(out.read_text())
        mp4 = Path(tmp) / "video.mp4"
        mp4.write_bytes(b"\x00")
        rec = write_batch_metadata.video_record("s1", plan, str(mp4), qc, "motion")
        g = rec["two_source_gate"]
        _check(g["passed"] is True and g["count"] == 2 and g["mode"] == "measure",
               f"videos[].two_source_gate copies the plan's record: {g}")
        _check(g["canonical_ids"] == [A, B], "with the sources named")

        # a plan that predates the gate: present, and null - never `true`
        bare = copy.deepcopy(plan)
        bare.pop("two_source_gate")
        empty = write_batch_metadata.video_record("s1", bare, str(mp4), qc, "motion")
        _check(empty["two_source_gate"]["passed"] is None,
               "an unmeasured plan cannot claim it had two sources")
        _check(empty["two_source_gate"]["mode"] is None
               and empty["two_source_gate"]["required"] == 2,
               f"and the key is there all the same: {empty['two_source_gate']}")

        if ROOT_CHECKS is not None:
            for v in (rec, empty):
                ctx = f"video {v['script_id']}"
                ROOT_CHECKS.require(v, ["script_id", "output_path"], ctx)
                ROOT_CHECKS.check_insert_provenance(v, ctx)
                ROOT_CHECKS.check_meme_pair(v, ctx)
                ROOT_CHECKS.check_sound_pair(v, ctx)
                ROOT_CHECKS.check_proof_provenance(v, ctx)
                ROOT_CHECKS.check_proof_pair(v, ctx)
            print("ok: the record still satisfies the root's 05-video-editor.json checks")
        else:
            print("SKIP root contract checks (factory root not reachable)")


# ---------------------------------------------------------------- CF-0689
def _graphic_block(start, end, gid="g1"):
    return {"start": start, "end": end, "shot": None,
            "asset": {"kind": "own_graphic", "graphic_id": gid, "template": "spec_card"}}


def _clip_block(start, end, vid):
    return {"start": start, "end": end, "shot": f"{vid}:1",
            "asset": {"kind": "clip", "src": f"/nonexistent/a00_{vid}_s001.mp4"}}


def test_an_own_graphic_names_no_source_cf0689():
    b = _graphic_block(0.0, 4.0)
    _check(source_gate.block_sources(b) == [], source_gate.block_sources(b))
    _check(source_gate.block_source_seconds(b) == {}, "a graphic is no borrowed footage")
    _check("own_graphic" not in source_gate.FOOTAGE_KINDS, source_gate.FOOTAGE_KINDS)


def test_a_graphic_only_plan_is_all_ours_cf0689():
    rec = source_gate.judge({"blocks": [_graphic_block(0, 6), _graphic_block(6, 12, "g2")]},
                            mode=source_gate.MODE_ENFORCE)
    _check(rec["passed"] and rec["applies"] is False, rec)
    _check(rec["own_graphic_seconds"] == 12.0 and rec["own_graphic_blocks"] == [0, 1], rec)
    _check(rec["count"] == 0 and rec["canonical_ids"] == [], rec)


def test_graphics_as_the_base_pass_one_borrowed_source_cf0689():
    plan = {"blocks": [_graphic_block(0, 8), _clip_block(8, 12, "trailerAAAA"),
                       _graphic_block(12, 20, "g2")]}
    rec = source_gate.judge(plan, mode=source_gate.MODE_ENFORCE)
    _check(rec["passed"] and rec["count"] == 1, rec)
    _check("own_graphic" in rec["note"], rec["note"])
    # the same one source as most of the video still fails
    plan = {"blocks": [_graphic_block(0, 2), _clip_block(2, 12, "trailerAAAA")]}
    rec = source_gate.judge(plan, mode=source_gate.MODE_ENFORCE)
    _check(not rec["passed"], rec)


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
