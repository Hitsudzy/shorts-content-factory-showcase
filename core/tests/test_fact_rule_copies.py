#!/usr/bin/env python3
"""CF-0323: one production-fact rule, and the root's side of the guard that it
stays one.

`no_production_fact` is the funnel's first killer - 29 topics of 101 across ten
instrumented runs - and the reason is not that the rule is wrong but that there
were two of them: the Trend Hunter's cheap probe at selection and the Content
Researcher's expensive refusal after the footage is indexed, written six weeks
apart from the same idea and disagreeing in both directions. CF-0323 makes them
one module, `shared/factrule/fact_rule.py`, and the agents load it from here.

Why a *copy* still exists, and why that is deliberate. The root and each agent
are separate checkouts that land on separate days, so
`agents/trend-hunter/scripts/_factrule.py` loads the root's module when the
root has it and its own `scripts/fact_rule.py` when it has not, and writes
which one answered into `fact_rule.ORIGIN`. Two files holding one predicate is
exactly the defect this task is about, so both ends check that they have not
drifted:

  * the hunter's side is `agents/trend-hunter/tests/
    test_fact_rule.py::test_the_root_s_copy_of_the_rule_is_this_one_to_the_byte`;
  * this file is the root's side, and it is the one that matters more - the
    root is the checkout where someone can edit the shared copy without ever
    opening the hunter's repository, and then every batch keeps running on the
    fallback while the two answers quietly separate.

The genre is `tests/test_cross_repo_constant_names.py`'s: a fact that spans two
repositories, checked from the root, skipped out loud when the neighbouring
checkout is not here (a worktree of the root has no `agents/` at all, CF-0196)
rather than passing mute. Everything is offline; nothing imports an agent's
code.
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHARED = ROOT / "shared" / "factrule" / "fact_rule.py"
# CF-0737: the rule loads `sentences.py` from its own directory by path, so a
# copy of the rule carries a copy of it beside itself.
SENTENCES = SHARED.with_name("sentences.py")

# Every repository that keeps its own copy of the rule, and why it may. A copy
# not listed here is a copy nobody has reviewed: add the path and the reason,
# or delete the file.
COPIES = {
    "agents/trend-hunter/scripts/fact_rule.py":
        "the fallback scripts/_factrule.py loads when the root has no module "
        "yet - the hunter authored the rule and must keep running if it is "
        "checked out alone (CF-0323).",
    "agents/trend-hunter/scripts/sentences.py":
        "the sentence rules the fallback copy of the rule loads from its own "
        "directory (CF-0737: `check_candidate` refuses a fact cut short).",
}
# The shared file each copy has to equal; the rule unless said otherwise.
SHARED_OF = {
    "agents/trend-hunter/scripts/sentences.py": SENTENCES,
}

# The surface both stages call. A name that leaves this module does not just
# break an import: it sends one of the two stages back to spelling the
# predicate itself, which is the whole defect.
CONTRACT = ("RULE_ID", "RULE_VERSION", "ORIGIN", "STATES", "STATE_FOUND",
            "STATE_NOT_FOUND", "STATE_UNREACHABLE", "STATE_NO_RULE",
            "STATUS_OK", "NOT_FOUND_STATUSES", "STATUS_WRONG_ARTICLE",
            "UNREACHABLE_STATUSES", "UNREACHABLE_KEYS", "REFUSAL_CODE",
            "WARNING_CODE", "answer_of_probe", "answer_of_lookup",
            "is_unreachable", "classify", "drops", "usable", "settled",
            "decision", "judge", "re_ask",
            # CF-0438: the fact itself - kinds, candidates, sources
            "LEGACY_REFUSAL_CODES", "canonical_code",
            # CF-0627: the kinds are the channel's (`kinds` of its list);
            # CF-0631: no transitional FACT_KINDS, no common SOURCES_REL -
            # `load_sources(path)` takes the channel's file
            "KINDS_KEY", "kinds_of",
            "PERSON_KINDS", "CANDIDATE_KEYS", "CANDIDATES_FIELD", "CHECK_KEY",
            "FACT_KEYS", "FAIL_CODES", "load_sources",
            "validate_sources", "source_of", "normalize_kind",
            "check_candidate", "check_candidates", "best_candidate",
            "answer_of_candidates", "fact_record",
            # CF-0660: the preprint flag of an outlet, the caveat flag of a fact
            "PREPRINT_KEY", "NEEDS_CAVEAT_KEY",
            # CF-0737: a fact cut short at an abbreviation fails
            "FAIL_CUT_SHORT", "CUT_SHORT_KEY")


def load_by_path(path, name="fact_rule_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def present_copies():
    """The listed copies that are actually checked out here."""
    return {rel: ROOT / rel for rel in sorted(COPIES) if (ROOT / rel).is_file()}


# --------------------------------------------------------------------------
# 1. the rule is one file
# --------------------------------------------------------------------------

def test_every_agent_copy_of_the_rule_is_the_shared_one_to_the_byte():
    """The migration's guard, from the side that can break it alone."""
    assert SHARED.is_file(), (
        f"{SHARED} is gone - the shared rule is the home CF-0323 moved it to, "
        f"and without it every stage falls back to its own copy, which is the "
        f"state the task exists to end")
    here = present_copies()
    if not here:
        print("   no agents/ checkout here - copies not compared")
        return
    drifted = []
    for rel, path in here.items():
        shared = SHARED_OF.get(rel, SHARED)
        if path.read_bytes() != shared.read_bytes():
            drifted.append(f"{rel} != {shared.relative_to(ROOT)}\n        {COPIES[rel]}")
    assert not drifted, (
        "a copy of the production-fact rule (or of the sentence rules it "
        "loads, CF-0737) has drifted from the shared file. One predicate means one file: port the "
        "change to the shared module and copy it back verbatim, or - if the "
        "copy is no longer needed - delete it and drop its entry from COPIES. "
        "Do not settle it by leaving two rules that nearly agree; that is "
        "CF-0323.\n     " + "\n     ".join(drifted))


def test_the_agent_that_authored_the_rule_still_carries_its_fallback():
    """The copy is not an oversight. `_factrule.py` falls back to it when the
    root is not reachable, so its disappearance is a change of design and has
    to be made on purpose, not by a tidy-up."""
    if not (ROOT / "agents" / "trend-hunter").is_dir():
        print("   no trend-hunter checkout here - fallback not checked")
        return
    fallback = ROOT / "agents/trend-hunter/scripts/fact_rule.py"
    assert fallback.is_file(), (
        f"{fallback} is gone but scripts/_factrule.py still falls back to it - "
        f"either restore the file or change the loader first")
    beside = fallback.with_name(SENTENCES.name)
    assert beside.is_file(), (
        f"{beside} is missing: the rule loads {SENTENCES.name} from its own "
        f"directory (CF-0737), so the hunter's fallback copy cannot load "
        f"without a copy of {SENTENCES.relative_to(ROOT)} beside it")


# --------------------------------------------------------------------------
# 2. the shared copy is the one the root loads
# --------------------------------------------------------------------------

def test_the_shared_rule_is_reachable_both_ways_and_is_one_module():
    """`shared/runlog`'s two roads, and the root takes them too: the package
    import for root code, the by-path load for every repository that has only
    a file path to go on."""
    from shared.factrule import fact_rule as via_package

    sys.path.insert(0, str(SHARED.parent))
    import fact_rule as via_path                                   # noqa: E402

    assert Path(via_package.__file__).resolve() == SHARED
    assert Path(via_path.__file__).resolve() == SHARED
    for name in CONTRACT:
        assert hasattr(via_package, name), f"{name} left the shared module"
        assert hasattr(via_path, name), f"{name} left the shared module"
    # Same answer on the same question, whichever road got there.
    answer = {"status": "no_candidates", "candidates": 0}
    assert (via_package.judge(answer, stage="root")[0]
            == via_path.judge(answer, stage="root")[0]
            == via_package.STATE_NOT_FOUND)


def test_the_package_import_says_the_root_answered():
    """`ORIGIN` is documented as "which copy answered", and the file's own
    default names the hunter's path because the file *is* the hunter's, byte
    for byte. The package sets it the way `_factrule.py` does, so root code
    reporting an origin does not report a path it did not load."""
    from shared.factrule import fact_rule as via_package

    assert Path(via_package.ORIGIN).resolve() == SHARED, via_package.ORIGIN
    raw = load_by_path(SHARED, name="fact_rule_raw")
    assert raw.ORIGIN == "agents/trend-hunter/scripts/fact_rule.py", (
        "the shared file's ORIGIN default was edited - that edit is a byte "
        "the hunter's copy does not have, and both byte checks go red")


def test_the_rule_loads_with_nothing_of_this_checkout_on_sys_path():
    """The load the agents actually perform. `tests/test_module_path_loading.py`
    holds this rule for every guarded directory; pinned here as well because a
    failure of it reads as a CF-0231 form problem, and here as "the hunter
    cannot load the root's rule", which is the consequence."""
    probe = (
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        "checkout = str(Path(sys.argv[2]).resolve())\n"
        "sys.path[:] = [p for p in sys.path if p and not "
        "str(Path(p).resolve()).startswith(checkout)]\n"
        "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print(m.classify({'status': 'ok', 'candidates': 1}))\n")
    with tempfile.TemporaryDirectory(prefix="cf0323-") as cwd:
        proc = subprocess.run([sys.executable, "-c", probe, str(SHARED), str(ROOT)],
                              capture_output=True, text=True, cwd=cwd, timeout=120)
    assert proc.returncode == 0, proc.stderr.strip()[-400:]
    assert proc.stdout.strip() == "found", proc.stdout


# --------------------------------------------------------------------------
# 3. the guard is a guard
# --------------------------------------------------------------------------

def test_the_shared_rule_holds_the_vocabulary_the_two_stages_share():
    """A byte comparison passes just as well between two empty files. Pin the
    handful of strings the Researcher's `fact_refusal.py` and the funnel are
    about to be held to, so an emptied or renamed module fails here rather than
    three batches later."""
    rule = load_by_path(SHARED)
    assert rule.RULE_ID == "production_fact_refusal"
    assert rule.STATES == ("found", "not_found", "source_unreachable", "no_rule")
    assert rule.NOT_FOUND_STATUSES == ("no_article", "no_section", "no_candidates")
    assert rule.STATUS_WRONG_ARTICLE == "wrong_article"
    assert rule.REFUSAL_CODE == "no_fact"                       # CF-0438
    assert rule.LEGACY_REFUSAL_CODES == ("no_production_fact",)
    assert rule.canonical_code("no_production_fact") == "no_fact"

    # The refusal the rule names has to be a code the funnel can read, or the
    # loss lands in the run accounting as an unknown word (CF-0107).
    from shared.runlog import funnel
    assert rule.REFUSAL_CODE in funnel.FUNNEL_CODES, (
        f"{rule.REFUSAL_CODE} is not in shared/runlog/funnel.py FUNNEL_CODES")

    # And the predicate answers: found / not_found / unreachable, with the
    # third never dropping a topic in either switch position (CF-0185).
    assert rule.classify({"status": "ok", "candidates": 1}) == rule.STATE_FOUND
    assert rule.classify({"status": "no_article", "candidates": 0}) == rule.STATE_NOT_FOUND
    assert rule.classify({"status": "unreachable"}) == rule.STATE_UNREACHABLE
    assert rule.drops(rule.STATE_NOT_FOUND, enabled=True) is True
    assert rule.drops(rule.STATE_NOT_FOUND, enabled=False) is False
    assert rule.drops(rule.STATE_UNREACHABLE, enabled=True) is False


def test_the_guard_fires_when_one_copy_is_edited_alone():
    """A negative control over a synthetic pair: the comparison must report a
    one-byte edit, and must stay quiet when the copies agree."""
    with tempfile.TemporaryDirectory(prefix="cf0323-") as tmp:
        tmp = Path(tmp)
        shared = tmp / "shared.py"
        copy = tmp / "copy.py"
        shared.write_text("NOT_FOUND_STATUSES = ('no_article',)\n")
        copy.write_text("NOT_FOUND_STATUSES = ('no_article',)\n")
        assert shared.read_bytes() == copy.read_bytes()

        shared.write_text("NOT_FOUND_STATUSES = ('no_article', 'no_section')\n")
        assert shared.read_bytes() != copy.read_bytes(), (
            "the byte comparison cannot see an edit - the guard above is a "
            "pair of equal empty reads")


def test_every_listed_copy_is_reviewed_and_no_unlisted_copy_exists():
    """COPIES is the review, so it must describe what is on disk. An agent
    that quietly grows its own `fact_rule.py` is the defect re-appearing under
    the name of the fix."""
    for rel, reason in COPIES.items():
        assert reason.strip(), f"{rel} is listed with no reason"
    agents = ROOT / "agents"
    if not agents.is_dir():
        print("   no agents/ checkout here - unlisted copies not scanned")
        return
    found = sorted(str(p.relative_to(ROOT)) for name in ("fact_rule.py", "sentences.py")
                   for p in agents.glob(f"*/scripts/{name}"))
    unlisted = [p for p in found if p not in COPIES]
    assert not unlisted, (
        "a repository holds a copy of the production-fact rule that nobody "
        "reviewed - it should be loading shared/factrule/fact_rule.py through "
        "a shim, the way scripts/_runlog.py loads the run log:\n     "
        + "\n     ".join(unlisted))


# --------------------------------------------------------------------------

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
