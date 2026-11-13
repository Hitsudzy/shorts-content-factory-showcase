#!/usr/bin/env python3
"""CF-0317: in an autonomous run this stage never waits for a human.

Seven of the ten points of the root register (`shared/runlog/no_waiting.py`)
live in this repository, and all seven used to end in a person - "stop and say
so", "say so and stop", "stop and report it". `example-film/2026-09-19T0116Z`
stood 6 h 19 m 36 s of a 39 h 42 m wall on two *other* points, which is the
whole argument: nobody was at the machine, and a step whose only exit is a
human answer does not fail, it simply stops being a pipeline.

What this file holds, in the order the points are listed in the register:

  * the codes, asserted against `no_waiting.CODES` **letter for letter** rather
    than spelled a second time here - a second spelling does not fail loudly,
    it files the record under nothing at all;
  * the notes, run through the root's own `classify()` - with seven points
    under one stage name, the words of the `stage-done` note are the only thing
    that tells the record which of them fired, so a note that reads well and
    classifies as its neighbour is a silent defect;
  * the exits themselves: three checkers used to die of `FileNotFoundError`
    inside `load_spec()`, and a traceback in an unattended run is a wait with
    extra steps;
  * the one repair this stage may run by itself - the stale pool - bounded to
    a single retry;
  * and the bans that do **not** soften: no invented verdicts or shots, no
    invented budget number, and never a word count divided by
    `words_per_second` (`CF-0279`).

Tests that need the factory root, or a sibling repository, skip rather than
fail when it is not there.
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))

import _no_waiting as nw  # noqa: E402
import _runlog  # noqa: E402
import check_anchor_coverage as cac  # noqa: E402
import check_narration_budget as cnb  # noqa: E402
import check_proofs as cp  # noqa: E402
import check_reactions as cr  # noqa: E402
import check_sounds as cs  # noqa: E402

SKILL = REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md"
STAGE = "content-researcher"

# What fills each note's blanks in a test. Real values, because the point of
# the exercise is that the note a run would actually write classifies right.
FIELDS = {
    "researcher_empty_shortlist": {},
    "researcher_missing_upstream": {"file": "01b-footage-index.json"},
    "researcher_missing_repo_asset": {"file": "inserts/meme.json"},
    "researcher_stale_cache": {},
    "researcher_env_broken": {"cause": "the Video Editor's venv is missing"},
    "researcher_missing_channel_config": {"channel": "example-film"},
    "researcher_estimator_unavailable": {},
}


def _skip(what, why):
    print(f"  skip {what} ({why})")


def root():
    """The factory root, or None."""
    try:
        r = _runlog.factory_root()
    except RuntimeError:
        return None
    return r if (r / "shared" / "runlog" / "no_waiting.py").is_file() else None


def register():
    """The root's register module, loaded by path - this repo must never grow
    a copy of it, and importing it by name would find whatever is on the path
    first."""
    r = root()
    if r is None:
        return None
    path = r / "shared" / "runlog" / "no_waiting.py"
    spec = importlib.util.spec_from_file_location("_root_no_waiting", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_root_no_waiting", mod)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# the vocabulary is the root's
# --------------------------------------------------------------------------

def test_every_code_this_repo_spells_is_the_roots_own():
    reg = register()
    if reg is None:
        return _skip("test_every_code_this_repo_spells_is_the_roots_own", "no root")
    for point, code in sorted(nw.CODES.items()):
        entry = reg.point(point)
        assert entry, f"{point} is not in the root register"
        assert entry["code"] == code, (f"{point}: this repo says {code!r}, the register says "
                                       f"{entry['code']!r} - one of the two is unreadable to "
                                       f"no_waiting.classify()")
        assert code in reg.CODES, f"{code} is not in no_waiting.CODES"
        assert entry["repo"] == "agents/content-researcher", (
            f"{point} belongs to {entry['repo']}, not to this repository")


def test_every_researcher_point_of_the_register_is_covered_here():
    reg = register()
    if reg is None:
        return _skip("test_every_researcher_point_of_the_register_is_covered_here", "no root")
    theirs = {p["id"] for p in reg.points(stage=STAGE)}
    assert theirs == set(nw.CODES), (f"the register has {sorted(theirs - set(nw.CODES))} that this "
                                     f"repo does not answer, and this repo answers "
                                     f"{sorted(set(nw.CODES) - theirs)} that the register has not")
    assert len(theirs) == 7, f"the task says seven points for this stage, the register has {len(theirs)}"


def test_no_point_of_this_stage_still_blocks_the_run():
    reg = register()
    if reg is None:
        return _skip("test_no_point_of_this_stage_still_blocks_the_run", "no root")
    for p in reg.points(stage=STAGE):
        assert not reg.blocks(p), f"{p['id']} has no automatic outcome"


# --------------------------------------------------------------------------
# the note is as much of a contract as the code
# --------------------------------------------------------------------------

def test_each_note_files_the_record_under_its_own_point():
    reg = register()
    if reg is None:
        return _skip("test_each_note_files_the_record_under_its_own_point", "no root")
    for point in sorted(nw.CODES):
        note = nw.note(point, **FIELDS[point])
        got = reg.classify(STAGE, note=note)
        assert got is not None, f"{point}: the note {note!r} classifies as nothing"
        assert got["id"] == point, (f"{point}: the note {note!r} files the record under "
                                    f"{got['id']!r} - the wait would be read as another point")


def test_the_two_wordings_of_an_unconfigured_channel_both_land_on_it():
    reg = register()
    if reg is None:
        return _skip("test_the_two_wordings_of_an_unconfigured_channel_both_land_on_it", "no root")
    point = "researcher_missing_channel_config"
    for what in ("narration_budget", "channel config"):
        note = nw.note(point, what=what, channel="example-film")
        assert reg.classify(STAGE, note=note)["id"] == point, note


def test_the_refusal_line_names_the_code_and_the_note():
    for point, code in sorted(nw.CODES.items()):
        line = nw.refuse(point, **FIELDS[point])
        assert line.startswith(f"{nw.PREFIX}: {code} "), line
        assert nw.note(point, **FIELDS[point]) in line, line
        assert "stage-done content-researcher --note" in line, line


def test_a_note_with_a_blank_nobody_filled_is_an_error_and_not_a_note():
    try:
        nw.note("researcher_missing_upstream")
    except KeyError as exc:
        assert "file" in str(exc), exc
    else:
        raise AssertionError("a template with an unfilled blank came back as a note")


# --------------------------------------------------------------------------
# the exits: what the checkers actually do now
# --------------------------------------------------------------------------

def _batch(tmp, channel="example-film", scripts=None):
    path = Path(tmp) / "03-content-researcher.json"
    path.write_text(json.dumps({"channel": channel, "scripts": scripts or []}))
    return path


def _run(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = fn(argv)
    return code, buf.getvalue()


def test_a_missing_insert_library_exits_with_the_code_and_not_a_traceback():
    for mod, lib in ((cr, "inserts/meme.json"), (cs, "inserts/sound.json"),
                     (cp, "inserts/proof.json")):
        with tempfile.TemporaryDirectory() as tmp:
            # A root with nothing in it: no inserts/, no channels/.
            code, out = _run(mod.main, [str(_batch(tmp)), "--root", tmp])
            assert code == nw.EXIT_CANNOT_ANSWER, (mod.__name__, code, out)
            assert f"{nw.PREFIX}: {nw.CODES['researcher_missing_repo_asset']}" in out, out
            assert f"{lib} is missing, no scripts written" in out, out
            assert "Traceback" not in out, out


def test_a_missing_channel_config_exits_with_its_own_code():
    with tempfile.TemporaryDirectory() as tmp:
        r = root()
        if r is None:
            return _skip("test_a_missing_channel_config_exits_with_its_own_code", "no root")
        # The real inserts, so the library is not what is missing; a channel id
        # no config exists for.
        (Path(tmp) / "inserts").symlink_to(r / "inserts")
        (Path(tmp) / "channels").mkdir()
        code, out = _run(cr.main, [str(_batch(tmp, channel="no-such-channel")), "--root", tmp])
        assert code == nw.EXIT_CANNOT_ANSWER, (code, out)
        assert f"{nw.PREFIX}: {nw.CODES['researcher_missing_channel_config']}" in out, out
        assert "no channel config for no-such-channel, nothing judged" in out, out


def test_the_budget_check_closes_on_an_unconfigured_channel():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "channels").mkdir()
        code, out = _run(cnb.main, [str(_batch(tmp, channel="no-such-channel")), "--root", tmp])
        assert code == cnb.EXIT_CANNOT_JUDGE, (code, out)
        assert f"{nw.PREFIX}: {nw.CODES['researcher_missing_channel_config']}" in out, out
        assert "Traceback" not in out, out


def test_a_missing_footage_index_is_the_upstream_point_and_not_the_machine():
    r = root()
    if r is None or not (r / "agents" / "video-editor" / ".venv").exists():
        return _skip("test_a_missing_footage_index_is_the_upstream_point_and_not_the_machine",
                     "no root, or no Video Editor checkout beside it")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run(cac.main, [str(_batch(tmp)), "--root", str(r),
                                    "--footage-index", str(Path(tmp) / "nowhere.json")])
        assert code == cac.EXIT_CANNOT_ANSWER, (code, out)
        assert f"{nw.PREFIX}: {nw.CODES['researcher_missing_upstream']}" in out, out
        assert "01b-footage-index.json is missing, no scripts written" in out, out


# --------------------------------------------------------------------------
# the one repair this stage runs by itself
# --------------------------------------------------------------------------

# The two sentences the other repositories print when a cached measurement was
# not made by the code running now. Copied here because this gate matches
# against them; `test_the_wording_the_other_repositories_print_has_not_drifted`
# is what keeps the copy honest.
CAPTION_REFUSAL = ("caption-band cache is stale: 12 shot(s) in 3 index(es) carry a "
                   "`crop_bottom_cached` this checkout did not measure (it measures abc123).")
USABILITY_WARNING = ("  cached usability was measured by f1368d57d8b1, this checkout measures "
                     "5dd306686131 - not trusting it, checking those candidates for real "
                     "(CF-0048). Re-stamp with: footage-indexer/scripts/remeasure_usability.py "
                     "<video>")


def test_the_remeasure_is_recognised_by_the_words_the_other_repos_print():
    assert cac.remeasure_script(CAPTION_REFUSAL) == "remeasure_captions.py"
    assert cac.remeasure_script(USABILITY_WARNING) == "remeasure_usability.py"
    # Everything else is the machine, and the machine is not repaired here.
    for other in ("", "anchor_coverage.py: no such file or directory",
                  "the preflight judged at min_score=0.30 while resolve_anchors says 0.22",
                  "ModuleNotFoundError: No module named 'torch'"):
        assert cac.remeasure_script(other) is None, other


def test_the_wording_the_other_repositories_print_has_not_drifted():
    """The copy above is a copy, so it is compared to the source. When the day
    comes that one of the two repositories rewords its refusal, this goes red -
    instead of the repair quietly never firing again."""
    r = root()
    if r is None:
        return _skip("test_the_wording_the_other_repositories_print_has_not_drifted", "no root")
    sources = {
        r / "agents" / "footage-indexer" / "scripts" / "caption_cache.py":
            "caption-band cache is stale",
        r / "agents" / "video-editor" / "scripts" / "resolve_anchors.py":
            "cached usability was measured by",
    }
    seen = 0
    for path, phrase in sources.items():
        if not path.is_file():
            continue
        seen += 1
        assert phrase in path.read_text(), (
            f"{path} no longer prints {phrase!r} - check_anchor_coverage.py matches on it to "
            f"know a stale cache from a broken machine, and would now read it as the machine")
    if not seen:
        _skip("test_the_wording_the_other_repositories_print_has_not_drifted", "no sibling repos")


class _Failing:
    """A `check_batch` that refuses the first N asks and then answers."""

    def __init__(self, failures, point=cac.POINT_STALE):
        self.left, self.point, self.asked = failures, point, 0

    def __call__(self, *a, **kw):
        self.asked += 1
        if self.left > 0:
            self.left -= 1
            raise cac.CannotAnswer("anchor_coverage.py exited 1:\n  | " + CAPTION_REFUSAL,
                                   point=self.point, remeasure="remeasure_captions.py",
                                   indexes=["a.shots.json", "b.shots.json"])
        return [], {}, {}, []


def _with_fakes(check_batch, remeasure_result):
    """Swap `check_batch` and `remeasure` for the length of one main()."""
    calls = []

    def fake_remeasure(script, indexes, root=None, timeout=None):
        calls.append((script, list(indexes)))
        return remeasure_result

    real = (cac.check_batch, cac.remeasure)
    cac.check_batch, cac.remeasure = check_batch, fake_remeasure
    try:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run(cac.main, [str(_batch(tmp))])
    finally:
        cac.check_batch, cac.remeasure = real
    return code, out, calls


def test_the_stale_pool_is_remeasured_once_and_the_question_asked_again():
    asker = _Failing(failures=1)
    code, out, calls = _with_fakes(asker, (True, "`remeasure_captions.py` re-measured 2 index(es)"))
    assert calls == [("remeasure_captions.py", ["a.shots.json", "b.shots.json"])], calls
    assert asker.asked == 2, f"the question was put {asker.asked} time(s), not twice"
    assert code == cac.EXIT_OK, (code, out)
    # Nothing is closed when the retry passes: there is no wait to record.
    assert nw.PREFIX not in out, out


def test_a_second_refusal_after_a_fresh_measurement_is_not_a_stale_cache():
    asker = _Failing(failures=2)
    code, out, calls = _with_fakes(asker, (True, "re-measured"))
    assert len(calls) == 1, f"the pool was re-measured {len(calls)} times inside one batch"
    assert asker.asked == 2, asker.asked
    assert code == cac.EXIT_CANNOT_ANSWER, (code, out)
    assert f"{nw.PREFIX}: {nw.CODES['researcher_stale_cache']}" in out, out
    assert "stale pool measurements, remeasured once and retried, still refused" in out, out


def test_a_repair_that_fell_over_closes_the_stage_instead_of_asking():
    asker = _Failing(failures=1)
    code, out, calls = _with_fakes(asker, (False, "`remeasure_captions.py` exited 2"))
    assert len(calls) == 1 and asker.asked == 1, (calls, asker.asked)
    assert code == cac.EXIT_CANNOT_ANSWER, (code, out)
    assert f"{nw.PREFIX}: {nw.CODES['researcher_stale_cache']}" in out, out


def test_the_repair_is_labelled_pool_maintenance_and_writes_no_marker():
    src = (REPO / "scripts" / "check_anchor_coverage.py").read_text()
    assert 'MAINTENANCE_STAGE = "pool-maintenance"' in src
    assert "stage=MAINTENANCE_STAGE" in src, "the repair's events would be labelled this stage"
    assert "RUNLOG_STAGE=MAINTENANCE_STAGE" in src, ("the remeasure's own script "
                                                     "events would carry this stage")
    # The markers stay the operator's: this gate never writes one (README,
    # "RUNLOG_STAGE renames the events, not the markers").
    assert "runlog.marker(" not in src, "the gate writes a marker inside an open stage"


def test_the_repair_runs_the_indexers_own_script_on_the_indexers_own_venv():
    r = root()
    if r is None:
        return _skip("test_the_repair_runs_the_indexers_own_script_on_the_indexers_own_venv",
                     "no root")
    with tempfile.TemporaryDirectory() as tmp:
        # A root that holds neither: the repair reports it and never raises.
        ok, detail = cac.remeasure("remeasure_captions.py", ["a.shots.json"], root=tmp)
        assert ok is False and "is missing" in detail, detail
    ok, detail = cac.remeasure("remeasure_captions.py", [], root=r)
    assert ok is False and "named no index" in detail, detail


# --------------------------------------------------------------------------
# the procedure says it too, and the bans it does not soften
# --------------------------------------------------------------------------

def test_the_skill_names_every_code_of_this_stage():
    text = SKILL.read_text()
    for point, code in sorted(nw.CODES.items()):
        assert code in text, f"{code} ({point}) is nowhere in the skill"
    assert "no stage may block on a decision that needs a human" in text


def test_no_point_of_this_stage_still_ends_in_a_person():
    """The seven sentences the task names, gone by their own words. `stop and
    say so` may still appear where it is not one of the seven - exit 3 of the
    cadence gate, for one - so the check is per point, on the line that carries
    it."""
    lines = SKILL.read_text().splitlines()
    for needle in ("If no topic is left to write",
                   "If Compliance Checker's file is missing",
                   "If the footage index is missing",
                   "check_reactions.py` cannot find",
                   "check_sounds.py` cannot find",
                   "check_proofs.py` cannot find",
                   "If `check_anchor_coverage.py` exits 3",
                   "If `check_narration_budget.py` cannot find the channel config"):
        line = next((l for l in lines if needle in l), None)
        assert line is not None, f"the skill no longer has the line about {needle!r}"
        for asking in ("stop and say so", "say so and stop", "stop and tell the user"):
            assert asking not in line, f"{needle!r} still says {asking!r}: {line[:160]}"


def test_the_bans_that_do_not_soften_are_still_there_word_for_word():
    text = SKILL.read_text()
    # CF-0279: the estimator's refusal may not become a word count.
    assert "Do not divide the word count by `words_per_second`" in text
    # CF-0087: the band is not a number this stage invents.
    assert "carries no default range" in text
    assert "the number is not yours to invent" in text
    # The upstream artifacts are not guessed at either.
    assert "Don't assume everything is clear" in text
    assert "the shots are not yours to invent" in text
    src = (REPO / "scripts" / "check_narration_budget.py").read_text()
    assert "does not fall " in src and "back to dividing words by words_per_second" in src


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
