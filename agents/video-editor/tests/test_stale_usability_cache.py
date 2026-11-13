#!/usr/bin/env python3
"""CF-0048: a cached usability measurement is believed only if this code made it.

The pre-filter's whole licence to exist (CF-0011, CF-0029) is that it "only
ever skips a candidate before it is cut - it never decides which candidate is
chosen". It keeps that promise only while the numbers it reads are numbers
this code would produce today. They were not: every index in the pool was
measured on 2026-09-01 01:01-01:49, and CF-0004's animation-aware fallback
landed at 08:57 the same morning, after which two of ten re-probed shots
flipped from "doomed" to "fine" - both of them title cards, i.e. the class
CF-0035 had just taught the matcher to find. The pre-filter was deciding, and
nothing could see it.

What is pinned here is the direction of the failure: an unrecognised stamp
must cost a cut(), never a skip. Every case below is written so that the naive
regression - trusting the cache anyway - flips the assertion.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import ast
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cache_fingerprint  # noqa: E402
import resolve_anchors  # noqa: E402
from repo_paths import INDEXER_SCRIPTS  # noqa: E402 - CF-0125: resolved against the main checkout

# Real numbers, from ZZ_urA56pJE shot 3 ("purple Example Max logo splash screen")
# as the index actually stores them: measured before CF-0004, so Vision's own
# too-wide saliency box keeps only 64.1% of the subject and the shot reads as
# doomed. Re-probed today the same frame reads animation_center / 1.0.
# CF-0435: numbers the pre-filter still acts on - a dead frame (black over
# MAX_BLACK_CLIPS). Framing under its floor, which these numbers used to
# carry (0.641), only ranks a candidate now, so it cannot show whether a
# stamp is believed.
STALE_NUMBERS = {
    "short_side": 720,
    "roi_source": "saliency",
    "roi_coverage": 0.9,
    "black_fraction": 0.97,
    "mean_luma": 3.1,
}
THRESHOLDS = (720, 0.65, resolve_anchors.MAX_BLACK_CLIPS)


def shot(cached=None, **extra):
    s = {"index": 3, "start": 10.0, "end": 12.0, **extra}
    if cached is not None:
        s["usable_cached"] = cached
    return s


def test_cache_this_code_made_is_believed():
    """The CF-0029 speedup itself: a current stamp on doomed numbers still
    skips the candidate without paying for a cut. Nothing here is meant to
    make the pre-filter useless, only honest."""
    fresh = {**STALE_NUMBERS, "measured_by": cache_fingerprint.usability_fingerprint()}
    assert resolve_anchors.probably_unusable(shot(fresh), *THRESHOLDS) is True


def test_cache_another_version_made_is_not_believed():
    """The defect itself. Same numbers, stamped by some other build of the
    measuring code: the candidate must reach cut() and the real usable()."""
    foreign = {**STALE_NUMBERS, "measured_by": "0123456789ab"}
    assert resolve_anchors.probably_unusable(shot(foreign), *THRESHOLDS) is False


def test_unstamped_cache_is_not_believed():
    """The state every index in shared/footage was actually in when CF-0048
    was written: a CF-0029-era cache with no record of what measured it. It
    cannot be shown to be current, so it is not treated as current."""
    assert resolve_anchors.probably_unusable(shot(dict(STALE_NUMBERS)), *THRESHOLDS) is False


def test_no_cache_at_all_still_costs_what_it_always_cost():
    """CF-0029's own rule, unchanged: no cache means no pre-filtering."""
    assert resolve_anchors.probably_unusable(shot(), *THRESHOLDS) is False
    assert resolve_anchors.probably_unusable(None, *THRESHOLDS) is False


def test_staleness_only_ever_spares_a_candidate():
    """The one-way property, checked over every shape of cache in the pool -
    passing, failing, card, non-card. An unrecognised stamp may turn a `skip`
    into a `cut and check`; it may never turn a `keep` into a `skip`, because
    then a stale cache could still remove a shot from the montage."""
    numbers = [
        STALE_NUMBERS,
        {**STALE_NUMBERS, "roi_coverage": 1.0},
        {**STALE_NUMBERS, "roi_source": "none"},
        {**STALE_NUMBERS, "short_side": 480},
        {**STALE_NUMBERS, "black_fraction": 0.99, "mean_luma": 4.9,
         "card_ink_fraction": 0.31},
        {**STALE_NUMBERS, "black_fraction": 0.99, "mean_luma": 0.0,
         "card_ink_fraction": None},
    ]
    for card in (False, True):
        for n in numbers:
            stale = {**n, "measured_by": "0123456789ab"}
            assert resolve_anchors.probably_unusable(
                shot(stale, is_card=card), *THRESHOLDS) is False


def test_verdict_rule_is_the_one_the_remeasure_tool_reports_with():
    """`cached_verdict()` is split out for remeasure_usability.py, which
    reports what a remeasure changes. If the two ever stop being the same
    function, that report stops describing the pipeline."""
    fresh = {**STALE_NUMBERS, "measured_by": cache_fingerprint.usability_fingerprint()}
    s = shot(fresh)
    assert (resolve_anchors.probably_unusable(s, *THRESHOLDS)
            is resolve_anchors.cached_verdict(s, fresh, *THRESHOLDS))
    # CF-0435: on a shot that only misses a soft floor the two part, on
    # purpose - the bundle still calls it doomed, the pre-filter ranks it.
    weak = {**fresh, "black_fraction": 0.0, "mean_luma": 63.1, "roi_coverage": 0.641}
    s = shot(weak)
    assert resolve_anchors.cached_verdict(s, weak, *THRESHOLDS) is True
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


# --- the fingerprint itself -------------------------------------------------

def write(dirpath, name, text):
    p = Path(dirpath) / name
    p.write_text(text)
    return p


def test_fingerprint_moves_when_the_measuring_code_moves():
    """The mutation this whole mechanism exists to catch: a constant changes
    inside a measuring file, and the digest must not stay the same."""
    with tempfile.TemporaryDirectory() as tmp:
        a = write(tmp, "m.py", "MIN_COVERAGE = 0.65\n")
        before = cache_fingerprint.digest([a])
        write(tmp, "m.py", "MIN_COVERAGE = 0.50\n")
        assert cache_fingerprint.digest([a]) != before
        assert before is not None


def test_fingerprint_moves_on_a_comment_only_change():
    """`digest()` is over raw bytes, so a comment moves it. Since CF-0406 it
    is not the usability key any more (that is `code_reach`'s AST walk, which
    the parser - not a judgement - decides) but it still proves LEGACY_STAMPS
    and `caption_cache.legacy_fingerprint()`, which must name exact bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        a = write(tmp, "m.py", "MIN_COVERAGE = 0.65\n")
        before = cache_fingerprint.digest([a])
        write(tmp, "m.py", "# why 0.65: see CF-0003\nMIN_COVERAGE = 0.65\n")
        assert cache_fingerprint.digest([a]) != before


def test_fingerprint_is_stable_for_unchanged_files():
    """The other half: it must not churn on its own, or every run would fall
    back to the slow path and the stamp would mean nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        a = write(tmp, "m.py", "MIN_COVERAGE = 0.65\n")
        assert cache_fingerprint.digest([a]) == cache_fingerprint.digest([a])
    assert (cache_fingerprint.usability_fingerprint()
            == cache_fingerprint.usability_fingerprint(refresh=True))


def test_swapping_two_files_contents_is_not_the_same_digest():
    """Name and length go into the hash, so two files trading contents - or a
    file being renamed - cannot look like no change at all."""
    with tempfile.TemporaryDirectory() as tmp:
        a = write(tmp, "a.py", "A = 1\n")
        b = write(tmp, "b.py", "B = 2\n")
        before = cache_fingerprint.digest([a, b])
        write(tmp, "a.py", "B = 2\n")
        write(tmp, "b.py", "A = 1\n")
        assert cache_fingerprint.digest([a, b]) != before


def test_missing_source_is_unknown_not_current():
    """A checkout that cannot read the measuring code cannot vouch for any
    cache. None must compare unequal to every stamp, including a stored
    literal `null`, so the reader falls into the real check."""
    with tempfile.TemporaryDirectory() as tmp:
        assert cache_fingerprint.digest([Path(tmp) / "gone.py"]) is None
    assert resolve_anchors.probably_unusable(
        shot({**STALE_NUMBERS, "measured_by": None}), *THRESHOLDS) is False


# --- CF-0406: the key is what the probe reaches -----------------------------

def reach_copy(tmp, edits=None):
    """USABILITY_SOURCES copied into `tmp` (same file names, so the same
    module names) with `edits` {file name: text -> text} applied; returns
    the paths in USABILITY_SOURCES order."""
    out = []
    for src in cache_fingerprint.USABILITY_SOURCES:
        text = Path(src).read_text()
        if edits and Path(src).name in edits:
            changed = edits[Path(src).name](text)
            assert changed != text, f"edit to {Path(src).name} did not apply"
            text = changed
        out.append(write(tmp, Path(src).name, text))
    return out


def test_the_key_is_the_reach_digest_of_the_real_files():
    """The key is computed at all (code_reach is beside the checkout), and a
    byte-identical copy of the files gives the same key - the walk depends on
    module names and content, not on where the files live."""
    current = cache_fingerprint.usability_fingerprint(refresh=True)
    assert current is not None, "code_reach.py or a measuring file unreadable"
    assert current != cache_fingerprint.legacy_fingerprint()
    with tempfile.TemporaryDirectory() as tmp:
        assert cache_fingerprint.usability_digest(reach_copy(tmp)) == current


def test_an_edit_the_probe_cannot_reach_does_not_move_the_key():
    """The three incidents, replayed on today's files: a dead constant in
    `common.py` (CF-0392's MEME_*), a new function in `smart_crop.py` no probe
    calls (CF-0367's faces_in_rect - the one that staled 3229 shots in batch
    0929Z), a comment and a docstring edit in a reached function."""
    current = cache_fingerprint.usability_fingerprint()
    edits = {
        "common.py": lambda t: t + "\nDEAD_MEME_KNOB = 480  # nobody reads this\n",
        "smart_crop.py": lambda t: t.replace(
            "\ndef _clamp_rect(",
            "\ndef faces_somewhere(path):\n    return []\n\n\ndef _clamp_rect(", 1),
        "qc_asset.py": lambda t: t.replace(
            "MAX_BLACK_FRACTION = 0.35",
            "# a remark\nMAX_BLACK_FRACTION = 0.35  # and another", 1),
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name, edit in edits.items():
            key = cache_fingerprint.usability_digest(reach_copy(tmp, {name: edit}))
            assert key == current, f"an unreached edit to {name} moved the key"


def test_an_edit_the_probe_reaches_moves_the_key():
    """The direction that matters: a threshold or constant the measurement
    runs on - the frame offset, the animation fallback's trigger, the black
    ceiling that decides whether ink is probed - moves the key, so the pool
    is re-measured rather than read with numbers today's code would not make."""
    current = cache_fingerprint.usability_fingerprint()
    edits = {
        "common.py": [lambda t: t.replace("PROBE_OFFSET = 0.5", "PROBE_OFFSET = 0.6", 1),
                      lambda t: t.replace("MIN_COVERAGE = 0.65", "MIN_COVERAGE = 0.60", 1)],
        "qc_asset.py": [lambda t: t.replace("MAX_BLACK_FRACTION = 0.35",
                                            "MAX_BLACK_FRACTION = 0.30", 1)],
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name, fns in edits.items():
            for edit in fns:
                key = cache_fingerprint.usability_digest(reach_copy(tmp, {name: edit}))
                assert key is not None and key != current, (
                    f"a reached threshold edit in {name} left the key at {current}")


def test_a_walk_that_cannot_answer_trusts_nothing():
    """Failing closed, as CF-0048 did: a syntax error or a missing file is
    no key, and no key makes no stamp current - not even a stored null."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = reach_copy(tmp, {"common.py": lambda t: t + "\ndef (:\n"})
        assert cache_fingerprint.usability_digest(broken) is None
        assert cache_fingerprint.usability_digest(
            [*broken[:-1], Path(tmp) / "gone.py"]) is None
    saved = dict(cache_fingerprint._MEMO)
    try:
        cache_fingerprint._MEMO["usability"] = None
        for stamp in (None, "c8a4a9661e70", "edcd5ade6f17"):
            assert cache_fingerprint.stamp_is_current(stamp) is False
    finally:
        cache_fingerprint._MEMO.clear()
        cache_fingerprint._MEMO.update(saved)


def test_a_legacy_stamp_is_believed_only_while_its_code_is_today_s():
    """The alias is conditional on the *current* key: a legacy stamp is fresh
    exactly while today's key equals the one it was paired with. Pinned
    through resolve_anchors, where the belief turns into a skipped cut()."""
    current = cache_fingerprint.usability_fingerprint()
    foreign = "0123456789ab"
    saved = dict(cache_fingerprint.LEGACY_STAMPS)
    try:
        cache_fingerprint.LEGACY_STAMPS[foreign] = current
        s = shot({**STALE_NUMBERS, "measured_by": foreign})
        assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is True
        cache_fingerprint.LEGACY_STAMPS[foreign] = "fedcba987654"
        assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False
    finally:
        cache_fingerprint.LEGACY_STAMPS.clear()
        cache_fingerprint.LEGACY_STAMPS.update(saved)


REPOS = {"video-editor": SCRIPTS.parent, "footage-indexer": INDEXER_SCRIPTS.parent}


def _git_show(rev, rel, repo=SCRIPTS.parent):
    import subprocess
    r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=repo,
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _rev_exists(rev, repo):
    import subprocess
    return subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=repo,
                          capture_output=True).returncode == 0


def _sources_at(revs):
    """{module stem: source text} of USABILITY_SOURCES, each file from its
    repo at revs[repo], in the key's order; None when a git object is gone.

    A listed file the revision does not have is left out, not a reason for
    None: the source list grows (CF-0711 added vision_compute.py), and the
    code of an older revision is what it had. If that code needed the file,
    the walk cannot resolve it and the key is None anyway."""
    out = {}
    for src in cache_fingerprint.USABILITY_SOURCES:
        src = Path(src)
        repo = "footage-indexer" if src.parent == INDEXER_SCRIPTS else "video-editor"
        data = _git_show(revs[repo], f"scripts/{src.name}", REPOS[repo])
        if data is None:
            if _rev_exists(revs[repo], REPOS[repo]):
                continue
            return None
        out[src.stem] = data.decode("utf-8")
    return out


def _key(sources):
    """The usability key over source texts - what usability_digest() is over
    files."""
    return cache_fingerprint.code_reach().digest_sources(
        sources, list(sources), cache_fingerprint.USABILITY_ROOTS,
        cache_fingerprint.USABILITY_WHOLE)


def test_the_legacy_stamps_name_the_same_code():
    """Each SAME_CODE_STAMPS pair re-derived from real bytes: this repo's
    files at the commit the stamp was written from, plus the indexer's probe
    as it was then (366b2c9 - CF-0506 moved it since). When those bytes
    reproduce the old whole-file stamp, the reach key over the same bytes
    must be the paired new key. Vacuous (and says so) once the git objects
    are gone."""
    revs = {"c8a4a9661e70": ("db3f68c", "366b2c9"),
            "dfe991a344df": ("094976c", "366b2c9")}
    assert set(revs) == set(cache_fingerprint.SAME_CODE_STAMPS)
    # One table, two provenances, no pair without one (CF-0506).
    neutral = cache_fingerprint.NEUTRAL_EDITS
    assert not set(revs) & set(neutral)
    assert set(cache_fingerprint.LEGACY_STAMPS) == set(revs) | set(neutral)
    for old, edit in neutral.items():
        assert cache_fingerprint.LEGACY_STAMPS[old] == edit["after"], old
    checked = 0
    for stamp, (ve_rev, fi_rev) in revs.items():
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for src in cache_fingerprint.USABILITY_SOURCES:
                src = Path(src)
                rev, repo = ((fi_rev, INDEXER_SCRIPTS.parent)
                             if src.parent == INDEXER_SCRIPTS
                             else (ve_rev, SCRIPTS.parent))
                data = _git_show(rev, f"scripts/{src.name}", repo)
                if data is None:
                    if _rev_exists(rev, repo):
                        continue    # a file added to the list since (CF-0711)
                    break
                p = Path(tmp) / src.name
                p.write_bytes(data)
                paths.append(p)
            else:
                assert cache_fingerprint.digest(paths) == stamp, (stamp, ve_rev, fi_rev)
                assert (cache_fingerprint.usability_digest(paths)
                        == cache_fingerprint.LEGACY_STAMPS[stamp]), stamp
                checked += 1
    if not checked:
        print("  NOTE: no legacy stamp reproducible from these bytes - nothing checked")
    # And today's own whole-file stamp, when it is one of them.
    legacy = cache_fingerprint.legacy_fingerprint()
    if legacy in cache_fingerprint.SAME_CODE_STAMPS:
        assert stamp_leads_to_today(legacy)


def stamp_leads_to_today(stamp):
    return cache_fingerprint.stamp_is_current(
        stamp, cache_fingerprint.usability_fingerprint())


# --- CF-0506: pairs of the second kind - an edit that cannot move a number ---

def _is_timeout_expired(node):
    return ((isinstance(node, ast.Attribute) and node.attr == "TimeoutExpired"
             and isinstance(node.value, ast.Name) and node.value.id == "subprocess")
            or (isinstance(node, ast.Name) and node.id == "TimeoutExpired"))


class _UndoCeiling(ast.NodeTransformer):
    """Undoes exactly a "ceiling" edit: `timeout=<ceiling>` (that name, not
    any timeout) comes off every call, and a `try:` around one statement that
    carries it - handlers catching TimeoutExpired only, no else/finally - is
    replaced by that statement. Anything else the commit did stays in the
    tree and shows up as a different key."""

    def __init__(self, ceiling):
        self.ceiling = ceiling
        self.undone = 0

    def _is_ceiling(self, kw):
        return (kw.arg == "timeout" and isinstance(kw.value, ast.Name)
                and kw.value.id == self.ceiling)

    def visit_Call(self, node):
        self.generic_visit(node)
        kept = [kw for kw in node.keywords if not self._is_ceiling(kw)]
        if len(kept) != len(node.keywords):
            node.keywords = kept
            self.undone += 1
        return node

    def visit_Try(self, node):
        if (len(node.body) == 1 and not node.orelse and not node.finalbody
                and node.handlers
                and all(_is_timeout_expired(h.type) for h in node.handlers)
                and any(isinstance(n, ast.Call) and any(map(self._is_ceiling, n.keywords))
                        for n in ast.walk(node.body[0]))):
            self.undone += 1
            return self.visit(node.body[0])
        return self.generic_visit(node)


class _UndoDevicePin(ast.NodeTransformer):
    """Undoes exactly a "device-pin" edit (CF-0711): `import <module>` (that
    module alone, no alias) and bare statements `<module>.<call>(...)` whose
    result nobody uses come out. A pin whose result is assigned, a call by
    another name, `from <module> import ...` - none of it is the documented
    edit, so it stays and shows up as a different key."""

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


UNDO = {"ceiling": lambda edit: _UndoCeiling(edit["ceiling"]),
        "device-pin": lambda edit: _UndoDevicePin(edit["module"], edit["calls"])}


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
    # Both sides are undone alike: Video Editor's own grabs already carry
    # ceilings of the same name, and those are not the commit's edit.
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
    at today's key) has to be proven: a commit that cannot be shown is a
    pair nobody can check."""
    repo, rev = edit["commit"]
    side, side_rev = edit["beside"]
    if {repo, side} != set(REPOS):
        return f"commit {repo} beside {side}: not the two repos of the key"
    before = _sources_at({repo: edit.get("parent", f"{rev}^"), side: side_rev})
    after = _sources_at({repo: rev, side: side_rev})
    if before is None or after is None:
        if cache_fingerprint.stamp_is_current(old, current):
            return f"{repo} {rev} (beside {side} {side_rev}) is not in git"
        print(f"  NOTE: {old} -> {edit['after']}: git objects gone and the "
              f"pair no longer leads to today's key - nothing checked")
        return None
    return _neutral(before, after, old, edit)


def test_a_neutral_edit_names_the_commit_that_made_it():
    """Every NEUTRAL_EDITS pair proven over git objects: the parent of its
    commit keys to the old stamp, the commit to the new key, and undoing the
    documented edit leaves the same reached code on both sides."""
    current = cache_fingerprint.usability_fingerprint()
    for old, edit in cache_fingerprint.NEUTRAL_EDITS.items():
        verdict = _neutral_pair_verdict(old, edit, current)
        assert verdict is None, f"{old} -> {edit['after']}: {verdict}"


def test_a_made_up_neutral_pair_is_refused():
    """The negative controls: the proof goes red on a pair nobody can show,
    on keys the commit does not produce, and on a commit that did more than
    its documented edit."""
    current = cache_fingerprint.usability_fingerprint()
    real_old, real = next(iter(cache_fingerprint.NEUTRAL_EDITS.items()))
    # A pair invented so the cache does not go stale: no such commit.
    invented = {**real, "commit": ("footage-indexer", "0123456")}
    assert _neutral_pair_verdict(real_old, invented, current), "invented commit passed"
    # The right commit, a new key it does not produce.
    assert _neutral_pair_verdict(real_old, {**real, "after": "0123456789ab"}, current)
    # The right commit, an old stamp its parent does not key to.
    assert _neutral_pair_verdict("c8a4a9661e70", real, current)
    # Another kind of edit than the one written, or no reason.
    assert _neutral_pair_verdict(real_old, {**real, "kind": "refactor"}, current)
    assert _neutral_pair_verdict(real_old, {**real, "why": " "}, current)

    repo, rev = real["commit"]
    side, side_rev = real["beside"]
    before = _sources_at({repo: f"{rev}^", side: side_rev})
    after = _sources_at({repo: rev, side: side_rev})
    if before is None or after is None:
        print("  NOTE: CF-0506 commit not in git - source-level controls skipped")
        return
    assert _neutral(before, after, real_old, real) is None
    # Round trip: unparsing does not move a key (the undo rewrites text).
    assert _key({k: ast.unparse(ast.parse(v)) for k, v in before.items()}) == real_old

    def doctored(edit_text):
        a = dict(after)
        a["usability_probe"] = edit_text(a["usability_probe"])
        assert a["usability_probe"] != after["usability_probe"]
        return a, {**real, "after": _key(a)}

    # The ceiling plus a second frame grabbed: the measurement moved.
    a, e = doctored(lambda t: t.replace('"-frames:v", "1"', '"-frames:v", "2"'))
    assert "other code" in (_neutral(before, a, real_old, e) or ""), "extra edit passed"
    # A ceiling by a literal, not the named constant: not the documented edit.
    a, e = doctored(lambda t: t.replace("timeout=PROBE_FRAME_TIMEOUT_SECONDS", "timeout=5"))
    assert _neutral(before, a, real_old, e), "literal ceiling passed"
    # A handler that also swallows other errors is not the documented edit.
    a, e = doctored(lambda t: t.replace("except subprocess.TimeoutExpired:",
                                        "except (subprocess.TimeoutExpired, OSError):"))
    assert _neutral(before, a, real_old, e), "wider handler passed"
    # A `finally` that runs on every grab is not either.
    a, e = doctored(lambda t: t.replace(
        "            f.unlink(missing_ok=True)\n",
        "            f.unlink(missing_ok=True)\n        finally:\n            f.touch()\n", 1))
    assert _neutral(before, a, real_old, e), "finally passed"


def test_a_device_pin_is_proven_and_nothing_more():
    """CF-0711: the device-pin pair is proven over git objects (not left
    vacuous while they exist), and goes red on a pin that does anything else:
    a request setting changed beside it, a pin whose result is used, or a
    parent that is not the code the old stamp names."""
    pins = {old: e for old, e in cache_fingerprint.NEUTRAL_EDITS.items()
            if e["kind"] == "device-pin"}
    assert pins, "CF-0711's pair is gone from NEUTRAL_EDITS"
    current = cache_fingerprint.usability_fingerprint()
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
    # The chain from the pair ends at today's key on today's code.
    assert cache_fingerprint.stamp_is_current(old, current)
    # One commit too late for a parent: c883fbad1183 is not that code's key.
    assert _neutral_pair_verdict(old, {**real, "parent": rev}, current)

    def doctored(stem, edit_text):
        a = dict(after)
        a[stem] = edit_text(a[stem])
        assert a[stem] != after[stem]
        return a, {**real, "after": _key(a)}

    # The pin plus a recognition level of its own: the measurement moved.
    a, e = doctored("detect_text_band", lambda s: s.replace(
        "vision_compute.pin(req)", "vision_compute.pin(req)\n    req.setUsesLanguageCorrection_(False)", 1))
    assert "other code" in (_neutral(before, a, old, e) or ""), "extra setting passed"
    # A pin whose result replaces the request is not the documented edit.
    a, e = doctored("smart_crop", lambda s: s.replace(
        "    vision_compute.pin(request)", "    request = vision_compute.pin(request)", 1))
    assert _neutral(before, a, old, e), "a pin whose result is used passed"


def test_a_stamp_is_current_through_a_chain_of_pairs():
    """CF-0506: the pairs are followed - a whole-file stamp names edcd5ade6f17's
    code, whose measurements a neutral edit carried on to today's key - and
    only forward: a newer stamp is not current on older code, and a loop in
    the table ends in "not current", not in a hang."""
    is_current = cache_fingerprint.stamp_is_current
    for stamp in ("c8a4a9661e70", "dfe991a344df", "edcd5ade6f17", "c883fbad1183"):
        assert is_current(stamp, "c883fbad1183"), stamp
    assert is_current("c8a4a9661e70", "edcd5ade6f17")
    assert not is_current("c883fbad1183", "edcd5ade6f17")
    assert not is_current("0123456789ab", "c883fbad1183")
    assert not is_current(None, "c883fbad1183")
    saved = dict(cache_fingerprint.LEGACY_STAMPS)
    try:
        cache_fingerprint.LEGACY_STAMPS.update({"aaaaaaaaaaaa": "bbbbbbbbbbbb",
                                                "bbbbbbbbbbbb": "aaaaaaaaaaaa"})
        assert not is_current("aaaaaaaaaaaa", "c883fbad1183")
    finally:
        cache_fingerprint.LEGACY_STAMPS.clear()
        cache_fingerprint.LEGACY_STAMPS.update(saved)


def _live_pool():
    """Every index of the live pool (CF-0519: a live monitor - see
    tests/_live_monitors.py)."""
    import repo_paths
    footage = repo_paths.FACTORY_ROOT / "shared" / "footage"
    return sorted(footage.glob("*.shots.json")) if footage.is_dir() else []


def test_the_pool_s_stamps_are_current():
    """The pool on disk, read not re-measured: every `usable_cached` stamp in
    `shared/footage/` is today's key or a legacy stamp of the same reached
    code. On 2026-09-28 that is 5550 shots in 163 indexes, of which the
    whole-file key read 3229 as stale; this key reads none. Red here means a
    change moved code the probe runs - a remeasure is owed, which is a
    decision (remeasure_usability.py), not something a test does."""
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _live_monitors import live_only
    if live_only("test_stale_usability_cache.py::_live_pool"):
        return
    paths = _live_pool()
    if not paths:
        print("  NOTE: no shared/footage indexes present - nothing checked")
        return
    current = cache_fingerprint.usability_fingerprint()
    stale = []
    for path in paths:
        try:
            shots = json.load(open(path)).get("shots", [])
        except (OSError, ValueError):
            continue
        for s in shots:
            cached = s.get("usable_cached")
            if cached and not cache_fingerprint.stamp_is_current(
                    cached.get("measured_by"), current):
                stale.append(f"{path.name}#{s.get('index')} "
                             f"({cached.get('measured_by') or 'unstamped'})")
    assert not stale, (
        f"{len(stale)} cached usability measurements were made by code the "
        f"probe no longer runs (key {current}): {stale[:5]}"
        f"{' ...' if len(stale) > 5 else ''}")


def test_fingerprint_covers_exactly_the_measuring_code():
    """The list is the mechanism's one hand-maintained part, so it is checked
    against the import graph rather than trusted: every local module the probe
    can reach must be in it, and nothing stale may linger in it.

    Four deliberate exceptions. `cache_fingerprint.py` is reachable (the probe
    stamps with it) but hashing the hasher measures nothing about the picture.
    `_runlog.py` (either agent's CF-0107 shim, reachable from every script
    that writes run events) is accounting, not measurement, for the same
    reason. `repo_paths.py` (CF-0125) is the third of that kind: it decides
    *where* the measuring code lives, never what is measured, and a
    fingerprint over its bytes would drop the whole cached pool on a comment
    in a path helper. `vision_worker.py` is *not* reachable by import - it is
    spawned as a subprocess - and yet it is what actually runs find_roi in the
    warm path, which is precisely the kind of dependency an import-graph check
    alone would miss.
    """
    def local_file(name):
        for d in (INDEXER_SCRIPTS, SCRIPTS):
            p = d / f"{name}.py"
            if p.exists():
                return p
        return None

    reachable, queue = set(), [INDEXER_SCRIPTS / "usability_probe.py"]
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

    accounting = {p for p in reachable if p.name in ("_runlog.py", "repo_paths.py")}
    expected = (reachable - {SCRIPTS / "cache_fingerprint.py"} - accounting) | {SCRIPTS / "vision_worker.py"}
    listed = {Path(p) for p in cache_fingerprint.USABILITY_SOURCES}
    assert listed == expected, (
        f"missing from USABILITY_SOURCES: {sorted(str(p) for p in expected - listed)}; "
        f"listed but not part of the measurement: {sorted(str(p) for p in listed - expected)}")


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
