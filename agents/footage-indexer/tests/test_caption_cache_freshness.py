#!/usr/bin/env python3
"""CF-0055: a cached caption crop is used only if this code measured it.

`crop_bottom_cached` is the second of the two caches CF-0029 put in
`shots.json`, and the one CF-0048 deliberately left alone. It ages the same
way - it is the output of code, and the index recorded nothing about which
code - but it is read differently: `resolve_anchors.cut()` hands it straight
to `prepare_clip.py --crop-bottom`, so it does not merely pre-filter, it
decides how much of a real clip's frame survives into the video.

That is why the failure direction here is the opposite of CF-0048's. There, an
unrecognised stamp costs a `cut()` and never correctness. Here there is no free
honest fallback: measuring fresh per candidate costs a measured 3.19s -> 13.32s
per cut, which is the saving CF-0029 exists for, so an unrecognised stamp stops
the run instead. What is pinned below is that direction - a stamp this checkout
did not make must refuse, and a stamp it did make must still be used, because a
mechanism that refuses everything would quietly hand that cost back.

Checks run cheapest first:
  - the rule itself, on synthetic shots (instant);
  - the fingerprint list and what it is and is not sensitive to (instant);
  - the matcher really refuses a stale index, as a subprocess (seconds);
  - every index in the pool carries this checkout's stamp (milliseconds);
  - on real shots of real footage the cached crop still equals what the probe
    returns today (slow; the only check that can catch a measurement drifting
    without any source file changing - a macOS Vision update, say).

The last two read `shared/footage/`, which is not in git. Without it they are
vacuous and say so out loud rather than passing quietly.

No pytest dependency - plain asserts, run directly.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import caption_cache  # noqa: E402
import caption_probe  # noqa: E402
import cache_fingerprint  # noqa: E402 - on sys.path via caption_cache
import code_reach  # noqa: E402 - CF-0711: keys over git objects

REPO = Path(__file__).resolve().parent.parent
from _fi_paths import factory_root, venv_bin  # noqa: E402 - CF-0267
from _live_monitors import live_only  # noqa: E402
VENV_PY = venv_bin("python")
MATCHER = SCRIPTS / "match_anchors.py"

# Real numbers from ZZ_urA56pJE, the Wren Hollow trailer every one of these
# tasks was found on:
#   50 - a title card whose own bottom ribbon reads as burned-in subtitles,
#        cropped by a third (CF-0053's example, and the largest real crop in
#        the pool that is not clamped);
#   3  - a card with no caption band at all, i.e. 0.0 as a *measurement*
#        rather than as a missing value;
#   57 - ordinary live-action, the candlelit hall that opens the finished
#        video.
LIVE_PROBE_SOURCE = "ZZ_urA56pJE"
LIVE_PROBE_SHOTS = [3, 50, 57]

FOREIGN = "0123456789ab"


def shot(value=None, stamp=None, index=50):
    s = {"index": index, "start": 10.0, "end": 12.0}
    if value is not None:
        s[caption_cache.VALUE_KEY] = value
    if stamp is not None:
        s[caption_cache.STAMP_KEY] = stamp
    return s


def _live_pool():
    """CF-0505: a live monitor (the caption stamp of the whole live pool, a live re-probe of real shots). None in the suite, which prints why;
    FI_TESTS_LIVE=1 (or a real batch's RUNLOG_BATCH) reads the live pool."""
    if live_only("test_caption_cache_freshness.py::_live_pool"):
        return None
    return factory_root() / "shared" / "footage"


def indexes():
    pool = _live_pool()
    return sorted(pool.glob("*.shots.json")) if pool and pool.is_dir() else []


# --- the rule ---------------------------------------------------------------

def test_a_crop_this_code_measured_is_used():
    """CF-0029's saving itself. If this ever stops holding, every cut pays
    +10s for a fresh scan and the mechanism has cost more than the defect."""
    fresh = shot(0.3272, caption_cache.captions_fingerprint())
    assert caption_cache.stale_stamp(fresh) is None
    assert caption_cache.require_fresh([]) is None


def test_a_crop_other_code_measured_is_refused():
    """The defect. Same number, made by some other build of the detector:
    it may not be used to crop a real clip."""
    assert caption_cache.stale_stamp(shot(0.3272, FOREIGN)) == FOREIGN


def test_an_unstamped_crop_is_refused():
    """The state every index in shared/footage was in when this task was
    written: a CF-0029-era crop with no record of what produced it. It cannot
    be shown to be current, so it is not treated as current."""
    assert caption_cache.stale_stamp(shot(0.3272)) == "unstamped"


def test_a_zero_crop_is_a_measurement_like_any_other():
    """`0.0` means "measured, no caption band" - the commonest answer in the
    pool (152 of 257 cached shots). Skipping the check for it because it looks
    like a default would leave most of the pool unguarded, and a detector
    change that starts finding a band where it found none is exactly the
    change worth catching."""
    assert caption_cache.stale_stamp(shot(0.0)) == "unstamped"
    assert caption_cache.stale_stamp(shot(0.0, FOREIGN)) == FOREIGN
    assert caption_cache.stale_stamp(
        shot(0.0, caption_cache.captions_fingerprint())) is None


def test_a_shot_with_no_cached_crop_is_not_refused():
    """CF-0029's own rule, unchanged and load-bearing: 11 of the 19 indexes in
    the pool were built before the cache existed and hold no crop at all.
    `cut()` sends those to `--auto-crop`, a fresh measurement that is always
    right - there is nothing stale about them, and refusing them would block
    the pipeline over indexes that are already correct."""
    assert caption_cache.stale_stamp(shot()) is None
    assert caption_cache.stale_stamp(shot(stamp=FOREIGN)) is None


def test_a_null_stamp_is_refused_like_any_other():
    """A checkout that cannot read the measuring code fingerprints as `None`,
    and `None` must equal nothing, not even a stored literal null - otherwise
    the one state in which nothing can be verified is the one state that
    verifies."""
    caption_cache._MEMO["captions"] = None
    try:
        assert caption_cache.stale_stamp(shot(0.3272, None)) == "unstamped"
        assert caption_cache.stale_stamp(shot(0.3272, FOREIGN)) == FOREIGN
        # Including against itself: two checkouts that both cannot read the
        # detector do not thereby agree about what measured anything.
        assert caption_cache.stale_stamp(shot(0.3272, None)) is not None
    finally:
        caption_cache.captions_fingerprint(refresh=True)


def test_the_refusal_names_the_command_that_fixes_it():
    """A refusal that does not say how to clear it gets worked around instead
    of acted on, and the next person reaches for --allow-stale-captions."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.shots.json"
        p.write_text(json.dumps({"shots": [shot(0.3272, FOREIGN),
                                           shot(0.0, index=51)]}))
        stale = caption_cache.survey([p])
        assert list(stale) == [str(p)] and len(stale[str(p)]) == 2
        try:
            caption_cache.require_fresh([p])
            assert False, "a stale index must not be allowed through"
        except SystemExit as e:
            message = str(e)
        assert "remeasure_captions.py" in message
        assert FOREIGN in message and "unstamped" in message
        assert "50" in message and "51" in message


# --- the stamp gets written at all ------------------------------------------

def test_measuring_writes_the_value_and_the_stamp_together():
    """Two keys, one fact. A value written without its stamp reads as stale
    below - safe, but a refusal nobody meant to cause - so nothing writes one
    without the other. The detector is stubbed out; this is bookkeeping."""
    original = caption_probe.probe_captions
    caption_probe.probe_captions = lambda *a, **k: 0.3272
    try:
        s = caption_cache.measure({"start": 1.0, "end": 2.0}, "nowhere.mp4")
    finally:
        caption_probe.probe_captions = original
    assert s[caption_cache.VALUE_KEY] == 0.3272
    assert s[caption_cache.STAMP_KEY] == caption_cache.captions_fingerprint()
    assert s[caption_cache.STAMP_KEY] is not None
    assert caption_cache.stale_stamp(s) is None


def test_a_probe_failure_leaves_the_shot_exactly_as_it_was():
    """An index whose probe failed keeps whatever it had - it does not acquire
    a stamp it has not earned, and it does not lose a value it has."""
    original = caption_probe.probe_captions

    def boom(*a, **k):
        raise RuntimeError("ffmpeg gone")
    caption_probe.probe_captions = boom
    try:
        s = shot(0.3272, FOREIGN)
        try:
            caption_cache.measure(s, "nowhere.mp4")
            assert False, "a failed probe must not be swallowed here"
        except RuntimeError:
            pass
        assert s == shot(0.3272, FOREIGN)
    finally:
        caption_probe.probe_captions = original


# --- the fingerprint --------------------------------------------------------

def test_fingerprint_is_taken_over_what_the_probe_reaches():
    """CF-0387: `captions_fingerprint()` digests the code the roots reach, not
    the files' bytes. On a two-file toy: an edit inside the reach moves it, a
    comment, a docstring or an unreached definition does not, and the memo
    can be refreshed."""
    import code_reach
    saved = (caption_cache.CAPTION_SOURCES, caption_cache.CAPTION_ROOTS,
             caption_cache.CAPTION_WHOLE, caption_cache.CAPTION_OPAQUE)
    with tempfile.TemporaryDirectory() as tmp:
        probe, det = Path(tmp) / "probe.py", Path(tmp) / "detector.py"
        probe.write_text("from detector import detect\n\n"
                         "def run(p):\n    return detect(p)\n")
        det.write_text('"""doc"""\nLOWER_REGION = 0.55\nUNUSED = 1\n\n'
                       "def detect(p):\n    return LOWER_REGION\n\n"
                       "def main():\n    print(UNUSED)\n")
        caption_cache.CAPTION_SOURCES = (probe, det)
        caption_cache.CAPTION_ROOTS = (("probe", "run"),)
        caption_cache.CAPTION_WHOLE = caption_cache.CAPTION_OPAQUE = ()
        try:
            before = caption_cache.captions_fingerprint(refresh=True)
            assert before and before == code_reach.reach_digest(
                (probe, det), (("probe", "run"),))
            det.write_text(det.read_text().replace('"""doc"""', '"""other"""')
                           .replace("UNUSED = 1", "UNUSED = 2  # a comment"))
            assert caption_cache.captions_fingerprint(refresh=True) == before
            det.write_text(det.read_text().replace("0.55", "0.50"))
            assert caption_cache.captions_fingerprint(refresh=True) != before
            # ...and does not churn on its own, or every run would refuse.
            assert (caption_cache.captions_fingerprint(refresh=True)
                    == caption_cache.captions_fingerprint(refresh=True))
            # Fails closed: a root the code no longer defines is None, not
            # a digest of less code.
            probe.write_text("def renamed(p):\n    return 0\n")
            assert caption_cache.captions_fingerprint(refresh=True) is None
        finally:
            (caption_cache.CAPTION_SOURCES, caption_cache.CAPTION_ROOTS,
             caption_cache.CAPTION_WHOLE, caption_cache.CAPTION_OPAQUE) = saved
            caption_cache.captions_fingerprint(refresh=True)


def _insert_into(text, func, stmt):
    """`stmt` as the first line of top-level `func`'s body (after its
    docstring), indented to match - an edit the verdict path executes."""
    import ast
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            first = node.body[1] if (len(node.body) > 1 and isinstance(node.body[0], ast.Expr)
                                     and isinstance(node.body[0].value, ast.Constant)) else node.body[0]
            lines = text.splitlines(keepends=True)
            indent = " " * first.col_offset
            lines.insert(first.lineno - 1, f"{indent}{stmt}\n")
            return "".join(lines)
    raise AssertionError(f"{func}() not found")


def _drop_unreached_assignment(text, module):
    """Delete one top-level constant of `module` the probe does not reach -
    CF-0392's kind of edit (two dead meme constants out of common.py)."""
    import ast
    import code_reach
    sources = {Path(p).stem: Path(p).read_text() for p in caption_cache.CAPTION_SOURCES}
    mods, taken = code_reach.reach(sources, caption_cache.CAPTION_ROOTS,
                                   caption_cache.CAPTION_WHOLE,
                                   caption_cache.CAPTION_OPAQUE)
    for i, unit in enumerate(mods[module].units):
        if isinstance(unit, ast.Assign) and i not in taken[module]:
            lines = text.splitlines(keepends=True)
            del lines[unit.lineno - 1:unit.end_lineno]
            return "".join(lines)
    raise AssertionError(f"no unreached constant in {module}")


# (file stem, what the edit is, edit, should the key move). The first group
# is today's incidents and their kind; the second is the verdict code, where
# a miss would be a silently wrong crop.
EDITS = [
    ("common", "CF-0392: drop a dead top-level constant",
     lambda t: _drop_unreached_assignment(t, "common"), False),
    ("common", "a new proof/meme constant", lambda t: t + "\nPROOF_NEW_CF0387 = 3\n", False),
    ("_runlog", "CF-0316: touch the no-root stand-in",
     lambda t: t.replace("class _Silent:", "class _Silent:  # stub\n    VERSION = 2\n"), False),
    ("detect_text_band", "CF-0177 kind: an edit to the CLI entry point",
     lambda t: _insert_into(t, "main", "pass"), False),
    ("detect_text_band", "CF-0159 kind: a CLI-only name on a reached import line",
     lambda t: t.replace("from common import grab_frames, media_duration",
                         "from common import grab_frames, media_duration, MIN_SHORT_SIDE"), False),
    ("common", "everything shifted down by blank lines",
     lambda t: t.replace("\nimport ", "\n\n\n\nimport ", 1), False),
    ("detect_text_band", "comment and docstring only",
     lambda t: t.replace('"""', '""" CF-0387 ', 1) + "\n# trailing comment\n", False),
    ("caption_probe", "SAMPLES 8 -> 9", lambda t: t.replace("SAMPLES = 8", "SAMPLES = 9"), True),
    ("detect_text_band", "LOWER_REGION threshold",
     lambda t: t.replace("LOWER_REGION = 0.55", "LOWER_REGION = 0.5"), True),
    ("detect_text_band", "band_from_frames() body",
     lambda t: _insert_into(t, "band_from_frames", "frames = list(frames)"), True),
    ("common", "grab_frames() body",
     lambda t: _insert_into(t, "grab_frames", "count = int(count)"), True),
    ("common", "an ffmpeg timeout",
     lambda t: t.replace("FFMPEG_BASE_TIMEOUT_SECONDS = ", "FFMPEG_BASE_TIMEOUT_SECONDS = 1 + "), True),
    ("vision_client", "text_boxes() transport",
     lambda t: _insert_into(t, "text_boxes", "image_path = str(image_path)"), True),
    ("vision_worker", "worker main()", lambda t: _insert_into(t, "main", "pass"), True),
    ("repo_paths", "which venv answers Vision",
     lambda t: _insert_into(t, "venv_python", "pass"), True),
]


def test_an_edit_moves_the_key_exactly_when_the_verdict_runs_it():
    """CF-0387 item 3, on copies of the real seven files: today's incidents
    (CF-0392, CF-0316, CF-0177's kind) leave the key where it is, and each
    part of the verdict path still moves it. Every row also moves the
    pre-CF-0387 whole-file digest - that column is what the pool used to pay."""
    saved = caption_cache.CAPTION_SOURCES
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        copies = []
        for p in saved:
            c = Path(tmp) / Path(p).name
            c.write_text(Path(p).read_text())
            copies.append(c)
        by_stem = {c.stem: c for c in copies}
        caption_cache.CAPTION_SOURCES = tuple(copies)
        try:
            base = caption_cache.captions_fingerprint(refresh=True)
            base_bytes = caption_cache.legacy_fingerprint()
            assert base is not None
            for stem, what, edit, moves in EDITS:
                f = by_stem[stem]
                original = f.read_text()
                edited = edit(original)
                assert edited != original, f"{what}: edit did not apply"
                f.write_text(edited)
                try:
                    key = caption_cache.captions_fingerprint(refresh=True)
                    assert caption_cache.legacy_fingerprint() != base_bytes
                    rows.append((stem, what, key != base, moves))
                finally:
                    f.write_text(original)
        finally:
            caption_cache.CAPTION_SOURCES = saved
            caption_cache.captions_fingerprint(refresh=True)
    for stem, what, moved, _ in rows:
        print(f"    {'moves' if moved else 'keeps'}  {stem}.py: {what}")
    wrong = [(s, w) for s, w, moved, want in rows if moved != want]
    assert not wrong, f"key moved the wrong way on: {wrong}"


def test_the_reached_code_names_what_it_calls():
    """The walk follows names; it cannot follow a name built at run time. If
    the verdict path ever dispatches through `getattr`, `globals()`, `exec`
    or `importlib`, the key can miss code it runs - this is where that is
    found, so the walk gets taught (or the file listed whole) before a stale
    crop reads as fresh."""
    import ast
    import code_reach
    sources = {Path(p).stem: Path(p).read_text() for p in caption_cache.CAPTION_SOURCES}
    mods, taken = code_reach.reach(sources, caption_cache.CAPTION_ROOTS,
                                   caption_cache.CAPTION_WHOLE,
                                   caption_cache.CAPTION_OPAQUE)
    dynamic = []
    for name, ix in taken.items():
        for i in ix:
            for node in ast.walk(mods[name].units[i]):
                f = node.func if isinstance(node, ast.Call) else None
                called = (f.id if isinstance(f, ast.Name) else
                          f.attr if isinstance(f, ast.Attribute) else None)
                if called in {"getattr", "globals", "vars", "exec", "eval",
                              "__import__", "import_module"}:
                    dynamic.append(f"{name}.py:{node.lineno} {called}()")
    assert not dynamic, f"dynamic lookups on the caption verdict path: {dynamic}"


def test_accounting_does_not_touch_what_the_child_returns():
    """Why `_runlog` may be opaque to the key: the measuring code reaches it
    only through `runlog.run_child(cmd, **popen_kw)` and `runlog.child()`, and
    the contract is that what the child returns is `subprocess.run`'s answer.
    Checked on the `runlog` the measuring modules actually hold."""
    import common
    import detect_text_band
    for rl in {id(common.runlog): common.runlog,
               id(detect_text_band.runlog): detect_text_band.runlog}.values():
        cmd = [sys.executable, "-c", "import sys; sys.stdout.write('x' * 3); sys.exit(3)"]
        got = rl.run_child(cmd, capture_output=True, text=True, timeout=30)
        want = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert (got.returncode, got.stdout, got.stderr) == (
            want.returncode, want.stdout, want.stderr)
        with rl.child("vision", argv=["vision", "t"], step="probe"):
            pass


def test_a_legacy_stamp_is_fresh_only_while_its_code_is_current():
    saved = dict(caption_cache.LEGACY_STAMPS)
    try:
        current = caption_cache.captions_fingerprint()
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS[FOREIGN] = current
        assert caption_cache.stale_stamp(shot(0.3, FOREIGN)) is None
        caption_cache.LEGACY_STAMPS[FOREIGN] = "fedcba987654"
        assert caption_cache.stale_stamp(shot(0.3, FOREIGN)) == FOREIGN
    finally:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(saved)


def test_restamp_rewrites_only_a_legacy_stamp_of_current_code_and_is_idempotent():
    saved = dict(caption_cache.LEGACY_STAMPS)
    current = caption_cache.captions_fingerprint()
    try:
        caption_cache.LEGACY_STAMPS[FOREIGN] = current
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.shots.json"
            p.write_text(json.dumps({"shots": [
                shot(0.3, FOREIGN, index=1), shot(0.1, "fedcba987654", index=2),
                shot(0.2, current, index=3), shot(None, FOREIGN, index=4)]}))
            assert caption_cache.restamp(p, dry_run=True) == 1
            assert json.loads(p.read_text())["shots"][0][caption_cache.STAMP_KEY] == FOREIGN
            assert caption_cache.restamp(p) == 1
            after = json.loads(p.read_text())["shots"]
            assert [s.get(caption_cache.STAMP_KEY) for s in after] == [
                current, "fedcba987654", current, FOREIGN]
            assert [s.get(caption_cache.VALUE_KEY) for s in after] == [0.3, 0.1, 0.2, None]
            assert caption_cache.restamp(p) == 0
    finally:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(saved)


# --- CF-0711: pairs of keys, chained, and the device-pin pair proven -------

def test_the_pair_table_is_one_table():
    """LEGACY_STAMPS is exactly the same-code pairs plus the neutral ones, and
    no stamp has two provenances."""
    same, neutral = caption_cache.SAME_CODE_STAMPS, caption_cache.NEUTRAL_EDITS
    assert not set(same) & set(neutral)
    assert set(caption_cache.LEGACY_STAMPS) == set(same) | set(neutral)
    for old, edit in neutral.items():
        assert caption_cache.LEGACY_STAMPS[old] == edit["after"], old
        assert str(edit.get("why", "")).strip(), f"{old}: no reason written"


def test_a_stamp_is_current_through_a_chain_of_pairs():
    """A -> B -> today's key: A and B are current; break the last link and
    neither is; a chain only runs forward (today's key does not make A's
    code current) and a loop ends."""
    saved = dict(caption_cache.LEGACY_STAMPS)
    current = caption_cache.captions_fingerprint()
    a, b = FOREIGN, "fedcba987654"
    try:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update({a: b, b: current})
        assert caption_cache.stale_stamp(shot(0.3, a)) is None
        assert caption_cache.stale_stamp(shot(0.3, b)) is None
        assert not caption_cache.stamp_is_current(current, "aaaaaaaaaaaa")
        caption_cache.LEGACY_STAMPS[b] = "aaaaaaaaaaaa"
        assert caption_cache.stale_stamp(shot(0.3, a)) == a
        caption_cache.LEGACY_STAMPS["aaaaaaaaaaaa"] = a      # a loop
        assert caption_cache.stale_stamp(shot(0.3, a)) == a
        assert not caption_cache.stamp_is_current(None, current)
    finally:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(saved)


def test_the_real_chain_ends_at_todays_key():
    """5dd306686131 (whole-file) -> 7337012cb1b6 (before the pin) ->
    c0c904ae5145 (before CF-0815's decoding) -> the end of the chain: the
    pool's crops stay current while today's key is that end. CF-0819: the
    chain is followed rather than one pair's `after` read, so a new pair at
    the end keeps this a check instead of a NOTE."""
    current = caption_cache.captions_fingerprint()
    chain = ["5dd306686131"]
    while chain[-1] in caption_cache.LEGACY_STAMPS and len(chain) < 20:
        chain.append(caption_cache.LEGACY_STAMPS[chain[-1]])
    assert chain[:4] == ["5dd306686131", "7337012cb1b6", "c0c904ae5145",
                         "e69cab16582e"], chain
    if current != chain[-1]:
        # CF-0829: no quiet NOTE any more. The only way past the chain's end
        # is a recorded STALE_MOVES entry (test_todays_key_is_on_record says
        # what to write), and then the chain's stamps are rightly stale.
        assert caption_cache.unrecorded_key_move(current) is None, \
            caption_cache.unrecorded_key_move(current)
        for stamp in chain:
            assert caption_cache.stale_stamp(shot(0.3, stamp)) == stamp, stamp
        return
    for stamp in chain:
        assert caption_cache.stale_stamp(shot(0.3, stamp)) is None, stamp


# --- CF-0829: every move of the key is on record ------------------------------

def test_todays_key_is_on_record():
    """The plain suite's guard for the pool's caption cache: the recorded key
    history (KEY_ROOT, proven pairs, then recorded stale moves) ends at
    today's key. On 20.10 the key moved c0c904ae5145 -> e69cab16582e, this
    suite stayed green and the live pool monitor stopped a batch instead.
    Deterministic: source files only, no pool, no network."""
    current = caption_cache.captions_fingerprint()
    assert current is not None, caption_cache.unrecorded_key_move(None)
    verdict = caption_cache.unrecorded_key_move(current)
    assert verdict is None, verdict
    assert caption_cache.key_history()[-1] == current


def test_a_stale_move_is_a_record_and_never_a_pair():
    """The two tables do not overlap, a stale move names a task and a reason,
    and no LEGACY_STAMPS pair is also a stale move."""
    moves = caption_cache.STALE_MOVES
    assert not set(moves) & set(caption_cache.LEGACY_STAMPS), moves
    for old, move in moves.items():
        assert set(move) >= {"after", "task", "why"}, old
        assert str(move["why"]).strip() and str(move["task"]).startswith("CF-"), old
        assert move["after"] != old, old


def _with_tables(legacy, moves, fn):
    saved_l = dict(caption_cache.LEGACY_STAMPS)
    saved_m = dict(caption_cache.STALE_MOVES)
    try:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(legacy)
        caption_cache.STALE_MOVES.clear()
        caption_cache.STALE_MOVES.update(moves)
        return fn()
    finally:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(saved_l)
        caption_cache.STALE_MOVES.clear()
        caption_cache.STALE_MOVES.update(saved_m)


def test_an_unrecorded_move_is_red_and_says_what_to_write():
    """The 20.10 shape on synthetic keys: the history ends at one key, the
    code computes another - red, naming both keys and both ways to record it."""
    root, end, today = caption_cache.KEY_ROOT, "c0c904ae5145", "e69cab16582e"
    msg = _with_tables({root: end}, {},
                       lambda: caption_cache.unrecorded_key_move(today))
    assert msg, "an unrecorded key move passed"
    for needle in (today, end, f'NEUTRAL_EDITS["{end}"]', f'STALE_MOVES["{end}"]',
                   "never a bulk re-measure", "caption_cache.py"):
        assert needle in msg, (needle, msg)
    # A key that went back to an older one of the history is a move too.
    back = _with_tables({root: end}, {},
                        lambda: caption_cache.unrecorded_key_move(root))
    assert back and "went back" in back, back
    # A key nobody can compute is never "on record".
    saved = caption_cache._MEMO.get("captions")
    caption_cache._MEMO["captions"] = None
    try:
        unreadable = caption_cache.unrecorded_key_move()
    finally:
        caption_cache._MEMO["captions"] = saved
    assert unreadable and "cannot be computed" in unreadable, unreadable


def test_a_recorded_move_is_green_and_only_a_pair_keeps_the_pool_fresh():
    """A neutral pair at the end: green, and the old stamps are current. A
    stale move at the end: green too (it is on record), but the old stamps are
    stale - the record is an acknowledgement, not a pair."""
    root, end = caption_cache.KEY_ROOT, "c0c904ae5145"
    today = caption_cache.captions_fingerprint()

    def check():
        return (caption_cache.unrecorded_key_move(today),
                caption_cache.stale_stamp(shot(0.3, end)),
                caption_cache.key_history())

    verdict, stale, history = _with_tables({root: end, end: today}, {}, check)
    assert verdict is None and stale is None and history[-1] == today
    verdict, stale, history = _with_tables(
        {root: end}, {end: {"after": today, "task": "CF-0000", "why": "x"}}, check)
    assert verdict is None and history == [root, end, today]
    assert stale == end, "a stale move made the old stamps current"
    # A loop in the records ends the history instead of hanging it.
    history = _with_tables(
        {root: end}, {end: {"after": root, "task": "CF-0000", "why": "x"}},
        caption_cache.key_history)
    assert history == [root, end]


def test_restamp_does_not_cross_a_neutral_pair():
    """A whole-file stamp is carried to the last key of the same code, never
    across a neutral pair: the shot keeps the stamp of the code that measured
    it, so deleting the pair (the strict standard) still stales it."""
    saved_l = dict(caption_cache.LEGACY_STAMPS)
    saved_n = dict(caption_cache.NEUTRAL_EDITS)
    current = caption_cache.captions_fingerprint()
    old, mid = FOREIGN, "fedcba987654"
    try:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update({old: mid, mid: current})
        caption_cache.NEUTRAL_EDITS.clear()
        caption_cache.NEUTRAL_EDITS[mid] = {"after": current, "kind": "device-pin"}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.shots.json"
            p.write_text(json.dumps({"shots": [
                shot(0.3, old, index=1), shot(0.1, mid, index=2)]}))
            assert caption_cache.restamp(p) == 1
            after = json.loads(p.read_text())["shots"]
            assert [s[caption_cache.STAMP_KEY] for s in after] == [mid, mid]
            assert caption_cache.restamp(p) == 0
            del caption_cache.LEGACY_STAMPS[mid]               # pair deleted
            assert caption_cache.stale_stamp(after[0]) == mid
    finally:
        caption_cache.LEGACY_STAMPS.clear()
        caption_cache.LEGACY_STAMPS.update(saved_l)
        caption_cache.NEUTRAL_EDITS.clear()
        caption_cache.NEUTRAL_EDITS.update(saved_n)


import ast  # noqa: E402

REPOS = {"footage-indexer": REPO,
         "video-editor": caption_cache.VIDEO_EDITOR_SCRIPTS.parent}


def _git_show(rev, rel, repo):
    r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=repo, capture_output=True)
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


def _rev_exists(rev, repo):
    return subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=repo,
                          capture_output=True).returncode == 0


def _sources_at(revs):
    """{module stem: source text} of CAPTION_SOURCES, each file from its repo
    at revs[repo], in the key's order; None when a git object is gone. A
    listed file the revision did not have yet is left out (vision_compute.py
    before CF-0711): the code of that revision is what it had, and if it had
    needed the file the walk could not resolve it and the key would be None."""
    out = {}
    for src in caption_cache.CAPTION_SOURCES:
        src = Path(src)
        repo = "footage-indexer" if src.parent == SCRIPTS else "video-editor"
        text = _git_show(revs[repo], f"scripts/{src.name}", REPOS[repo])
        if text is None:
            if _rev_exists(revs[repo], REPOS[repo]):
                continue
            return None
        out[src.stem] = text
    return out


def _key(sources):
    """The caption key over source texts - what captions_fingerprint() is
    over files."""
    return code_reach.digest_sources(
        sources, list(sources), caption_cache.CAPTION_ROOTS,
        caption_cache.CAPTION_WHOLE, caption_cache.CAPTION_OPAQUE)


class _UndoDevicePin(ast.NodeTransformer):
    """Undoes exactly a "device-pin" edit: `import <module>` (that module
    alone, no alias) and bare statements `<module>.<call>(...)` whose result
    nobody uses come out. A pin whose result is assigned, a call by another
    name, `from <module> import ...` - none of it is the documented edit, so
    it stays and shows up as a different key."""

    def __init__(self, module, calls):
        self.module, self.calls = module, set(calls)
        self.undone = 0

    def visit_Import(self, node):
        if all(a.name == self.module and a.asname is None for a in node.names):
            self.undone += 1
            return None
        return node

    def visit_Expr(self, node):
        f = node.value.func if isinstance(node.value, ast.Call) else None
        if (isinstance(f, ast.Attribute) and f.attr in self.calls
                and isinstance(f.value, ast.Name) and f.value.id == self.module):
            self.undone += 1
            return None
        return self.generic_visit(node)


class _UndoDecodeReplace(ast.NodeTransformer):
    """Undoes exactly a "decode-replace" edit (CF-0819): the keyword
    `errors="replace"` comes out of a call that also passes `text=True`. Any
    other `errors=` value, or one on a call that does not decode as text, is
    not the documented edit and stays."""

    def __init__(self):
        self.undone = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        text, errors = kw.get("text"), kw.get("errors")
        if (isinstance(text, ast.Constant) and text.value is True
                and isinstance(errors, ast.Constant) and errors.value == "replace"):
            node.keywords = [k for k in node.keywords if k.arg != "errors"]
            self.undone += 1
        return node


UNDO = {"device-pin": lambda edit: _UndoDevicePin(edit["module"], edit["calls"]),
        "decode-replace": lambda edit: _UndoDecodeReplace()}


def _undo(sources, edit):
    """(sources with the documented edit undone, how many places it undid).
    A "device-pin" also takes its module out of the key: the code before the
    edit did not have it."""
    out, undone = {}, 0
    sources = dict(sources)
    if edit["kind"] == "device-pin" and sources.pop(edit["module"], None) is not None:
        undone += 1
    for stem, text in sources.items():
        undo = UNDO[edit["kind"]](edit)
        tree = undo.visit(ast.parse(text))
        undone += undo.undone
        out[stem] = ast.unparse(ast.fix_missing_locations(tree)) if undo.undone else text
    return out, undone


def _neutral(before, after, old, edit):
    """None when `after` is `before` plus the documented edit and nothing else
    the probe reaches, with the keys the pair claims; else why not."""
    if edit.get("kind") not in UNDO:
        return f"unknown kind of edit {edit.get('kind')!r} - no undo to prove it with"
    if not str(edit.get("why", "")).strip():
        return "no reason written for the pair"
    if _key(before) != old:
        return f"the parent's key is {_key(before)}, not {old}"
    if _key(after) != edit["after"]:
        return f"the commit's key is {_key(after)}, not {edit['after']}"
    undone_after, n_after = _undo(after, edit)
    undone_before, n_before = _undo(before, edit)
    if n_after <= n_before:
        return f"the commit adds no {edit['kind']} edit to undo"
    if _key(undone_after) != _key(undone_before):
        return (f"with the {edit['kind']} edit undone the commit still reaches "
                f"other code ({_key(undone_after)} vs {_key(undone_before)})")
    return None


def _neutral_pair_verdict(old, edit, current):
    """None when the pair is proven (or dead and unprovable - says so); else
    why it is refused. A pair the pool's stamps still lean on (its chain ends
    at today's key) has to be proven: a commit nobody can show is a pair
    nobody can check."""
    repo, rev = edit["commit"]
    side, side_rev = edit["beside"]
    if {repo, side} != set(REPOS):
        return f"commit {repo} beside {side}: not the two repos of the key"
    before = _sources_at({repo: edit.get("parent", f"{rev}^"), side: side_rev})
    after = _sources_at({repo: rev, side: side_rev})
    if before is None or after is None:
        if caption_cache.stamp_is_current(old, current):
            return f"{repo} {rev} (beside {side} {side_rev}) is not in git"
        print(f"  NOTE: {old} -> {edit['after']}: git objects gone and the "
              f"pair no longer leads to today's key - nothing checked")
        return None
    return _neutral(before, after, old, edit)


def test_every_neutral_pair_names_the_commit_that_made_it():
    current = caption_cache.captions_fingerprint()
    for old, edit in caption_cache.NEUTRAL_EDITS.items():
        verdict = _neutral_pair_verdict(old, edit, current)
        assert verdict is None, f"{old} -> {edit['after']}: {verdict}"


def test_the_device_pin_is_proven_and_nothing_more():
    """CF-0711: the device-pin pair is proven over git objects (not left
    vacuous while they exist), and goes red on a pin that does anything else:
    a request setting changed beside it, a pin whose result is used, or a
    parent that is not the code the old stamp names."""
    pins = {old: e for old, e in caption_cache.NEUTRAL_EDITS.items()
            if e["kind"] == "device-pin"}
    assert pins, "CF-0711's pair is gone from NEUTRAL_EDITS"
    current = caption_cache.captions_fingerprint()
    old, real = next(iter(pins.items()))
    repo, rev = real["commit"]
    side, side_rev = real["beside"]
    before = _sources_at({repo: real["parent"], side: side_rev})
    after = _sources_at({repo: rev, side: side_rev})
    if before is None or after is None:
        print("  NOTE: CF-0711 commits not in git - device-pin controls skipped")
        return
    assert real["module"] not in before and real["module"] in after
    assert _neutral(before, after, old, real) is None
    # One commit too late for a parent: 7337012cb1b6 is not that code's key.
    assert _neutral_pair_verdict(old, {**real, "parent": rev}, current)
    # A pair with no reason is not a pair.
    assert _neutral(before, after, old, {**real, "why": " "})

    def doctored(edit_text):
        a = dict(after)
        a["detect_text_band"] = edit_text(a["detect_text_band"])
        assert a["detect_text_band"] != after["detect_text_band"]
        return a, {**real, "after": _key(a)}

    # The pin plus a recognition setting of its own: the measurement moved.
    a, e = doctored(lambda s: s.replace(
        "vision_compute.pin(req)",
        "vision_compute.pin(req)\n    req.setUsesLanguageCorrection_(False)", 1))
    assert "other code" in (_neutral(before, a, old, e) or ""), "extra setting passed"
    # A pin whose result replaces the request is not the documented edit.
    a, e = doctored(lambda s: s.replace(
        "    vision_compute.pin(req)", "    req = vision_compute.pin(req)", 1))
    assert _neutral(before, a, old, e), "a pin whose result is used passed"
    # A pin plus a changed recognition level is caught too.
    a, e = doctored(lambda s: s.replace(
        "req.setRecognitionLevel_(level)", "req.setRecognitionLevel_(0)", 1))
    assert _neutral(before, a, old, e), "a moved recognition level passed"


def test_the_decode_replace_is_proven_and_nothing_more():
    """CF-0819: the c0c904ae5145 -> e69cab16582e pair (video-editor 8209783,
    CF-0815's `errors="replace"` on ffprobe's text) is proven over git objects,
    and goes red on an edit that does anything more: another `errors=` value,
    the keyword on a call that does not decode as text, or a sample setting
    changed beside it."""
    pairs = {old: e for old, e in caption_cache.NEUTRAL_EDITS.items()
             if e["kind"] == "decode-replace"}
    assert set(pairs) == {"c0c904ae5145"}, pairs
    old, real = next(iter(pairs.items()))
    assert real["after"] == "e69cab16582e"
    repo, rev = real["commit"]
    side, side_rev = real["beside"]
    before = _sources_at({repo: real["parent"], side: side_rev})
    after = _sources_at({repo: rev, side: side_rev})
    if before is None or after is None:
        print("  NOTE: CF-0815 commits not in git - decode-replace controls skipped")
        return
    assert (before["common"].count('errors="replace"')
            < after["common"].count('errors="replace"'))
    assert _neutral(before, after, old, real) is None
    # The first half of CF-0815 (809a030) also touched common.ffmpeg(): that
    # is not this pair's code, and the pair does not stretch over it.
    mid = _sources_at({repo: "809a030", side: side_rev})
    if mid is not None:
        assert _key(mid) != real["after"]

    def doctored(edit_text):
        a = dict(after)
        a["common"] = edit_text(a["common"])
        assert a["common"] != after["common"]
        return a, {**real, "after": _key(a)}

    marker = 'text=True, errors="replace",'
    assert marker in after["common"], "ffprobe() no longer carries the edit"
    # errors="ignore" drops bytes instead of marking them: not the edit.
    a, e = doctored(lambda s: s.replace(marker, 'text=True, errors="ignore",', 1))
    assert _neutral(before, a, old, e), "errors='ignore' passed"
    # The keyword on a call that returns bytes is not the documented edit.
    a, e = doctored(lambda s: s.replace(marker, 'errors="replace",', 1))
    assert _neutral(before, a, old, e), "errors= without text=True passed"
    # The edit plus a moved ffprobe ceiling: the measurement's code moved.
    a, e = doctored(lambda s: s.replace(
        "FFPROBE_TIMEOUT_SECONDS = ", "FFPROBE_TIMEOUT_SECONDS = 1 + ", 1))
    assert "other code" in (_neutral(before, a, old, e) or ""), "extra edit passed"


def test_the_two_caches_age_independently():
    """Two fingerprints over two file lists is the whole point of a second one
    existing. A change to `smart_crop.py` or `qc_asset.py` must not invalidate
    caption crops - the caption detector never calls either - and a change to
    `detect_text_band.py` must invalidate both, because `card_ink()` measures
    inside it. Getting this wrong in the safe direction (one list for both)
    would make every future edit anywhere invalidate everything, and a
    mechanism that cries wolf gets bypassed."""
    captions = {Path(p).name for p in caption_cache.CAPTION_SOURCES}
    usability = {Path(p).name for p in cache_fingerprint.USABILITY_SOURCES}
    assert captions != usability
    assert {"smart_crop.py", "qc_asset.py", "prepare_clip.py",
            "usability_probe.py"} <= usability - captions
    assert "caption_probe.py" in captions - usability
    assert "detect_text_band.py" in captions & usability
    assert caption_cache.captions_fingerprint() != cache_fingerprint.usability_fingerprint()


def test_fingerprint_covers_exactly_the_caption_measuring_code():
    """The list is the mechanism's one hand-maintained part, so it is checked
    against the import graph rather than trusted.

    Two deliberate differences from what the graph says, both the same kinds
    the usability list has. `vision_worker.py` is not reachable by import - it
    is spawned as a subprocess - and yet it is what actually runs the text
    scan in the warm path. `smart_crop.py` *is* reachable, but only through
    `vision_client.find_roi`'s local fallback, and caption detection calls
    `text_boxes()`, never `find_roi` - hashing it would tie caption crops to a
    file that cannot change them.
    """
    import ast
    VE = caption_cache.VIDEO_EDITOR_SCRIPTS  # CF-0267

    def local_file(name):
        for d in (SCRIPTS, VE):
            p = d / f"{name}.py"
            if p.exists():
                return p
        return None

    reachable, queue = set(), [SCRIPTS / "caption_probe.py"]
    while queue:
        f = queue.pop()
        if f in reachable:
            continue
        reachable.add(f)
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            queue += [p for p in (local_file(n) for n in names) if p]

    expected = (reachable - {VE / "smart_crop.py"}) | {VE / "vision_worker.py"}
    listed = {Path(p) for p in caption_cache.CAPTION_SOURCES}
    assert listed == expected, (
        f"missing from CAPTION_SOURCES: {sorted(str(p) for p in expected - listed)}; "
        f"listed but not part of the measurement: "
        f"{sorted(str(p) for p in listed - expected)}")


def test_the_probe_file_does_not_import_its_own_bookkeeping():
    """`caption_probe.py` is hashed; `caption_cache.py` is not. If the probe
    imported the cache, the import-graph check above would have to start
    excusing files, and worse, a change to the refusal message would
    invalidate every crop in the pool."""
    import ast
    imported = set()
    for node in ast.walk(ast.parse((SCRIPTS / "caption_probe.py").read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            imported.add(node.module.split(".")[0])
    assert "caption_cache" not in imported
    # ...and the dependency runs the other way, so there is one place that
    # writes a measurement and its stamp.
    assert "caption_probe" in caption_cache.__dict__


# --- the refusal actually fires in the pipeline -----------------------------

def test_the_matcher_refuses_a_stale_index():
    """The wiring, not the rule: `resolve_anchors.py` runs `match_anchors.py`
    as a subprocess and exits on a non-zero return, so this is what turns a
    stale pool into a stopped run - before a single clip is cut, and before
    CLIP is even loaded. Checked by running it, because a check that is only
    unit-tested can be true of a function nobody calls."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "stale.shots.json"
        p.write_text(json.dumps({"shots": [
            dict(shot(0.3272, FOREIGN), embedding=[0.1] * 512)]}))
        out = subprocess.run([str(VENV_PY), str(MATCHER), "--index", str(p),
                              "a wooden lake house", "--json"],
                             capture_output=True, text=True)
        assert out.returncode != 0, "a stale index must stop the run"
        assert "caption-band cache is stale" in out.stderr
        assert "remeasure_captions.py" in out.stderr
        # Before CLIP: the point of putting it here is that nothing is spent.
        assert not out.stdout.strip()


# --- the pool ---------------------------------------------------------------

def test_every_cached_crop_in_the_pool_is_current():
    """The whole pool, in milliseconds. A failure here is not a bug in this
    repo - it means the detector moved and the indexes are owed a remeasure,
    which is a decision (it changes the geometry of clips in every future
    video), so it is surfaced rather than done automatically. It is also
    exactly what the pipeline will refuse to run on."""
    if not indexes():
        print("  NOTE: no shared/footage indexes present - nothing checked")
        return
    stale = caption_cache.survey(indexes())
    assert not stale, caption_cache.complaint(stale)


def test_the_cache_agrees_with_a_live_probe_on_real_shots():
    """The check the stamp cannot make: run the detector again, now, on real
    frames of real footage and compare with what is stored. A stamp only says
    the source files match; this says the measurement does.

    Slow on purpose (eight Vision scans per shot) and small on purpose - three
    shots covering a real caption band, a measured absence of one, and an
    ordinary live-action shot."""
    pool = _live_pool()
    if pool is None:
        return
    index_path = pool / f"{LIVE_PROBE_SOURCE}.shots.json"
    video = pool / f"{LIVE_PROBE_SOURCE}.mp4"
    if not (index_path.exists() and video.exists()):
        print(f"  NOTE: {LIVE_PROBE_SOURCE} footage absent - nothing checked")
        return
    by_index = {s["index"]: s for s in json.load(open(index_path))["shots"]}
    picked = [by_index[i] for i in LIVE_PROBE_SHOTS if i in by_index]
    assert len(picked) == len(LIVE_PROBE_SHOTS), "index no longer has those shots"

    for s in picked:
        cached = s.get(caption_cache.VALUE_KEY)
        assert cached is not None, (
            f"shot {s['index']} has no cached crop - that is safe (cut() falls "
            f"back to --auto-crop) but the index is not what it should be")
        live = caption_probe.probe_captions(video, s["start"], s["end"])
        assert cached == live, (
            f"shot {s['index']}: the cache says {cached}, the detector says "
            f"{live} today, and the stamp claims the same code made both.\n"
            f"If `{caption_cache.STAMP_KEY}` differs from "
            f"{caption_cache.captions_fingerprint()}, the pool is owed a "
            f"remeasure ({caption_cache.REMEASURE} {video}). If it matches and "
            f"the number still moved, the measurement drifted without any of "
            f"its source files changing - the case a fingerprint cannot see, "
            f"and it needs looking at by hand.")


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
