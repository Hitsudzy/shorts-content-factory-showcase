#!/usr/bin/env python3
"""CC-0053: a batch read from a root worktree, whose `pipeline/<channel>` is a
link `scripts/agents sync` made to the working copy (`links.root` of
`agents.lock.json`).

CC-0051's live check found the API of `.worktrees/cc-api` answering 404
`unknown_batch` for every real batch: `batch_dir` resolved the path and
refused anything outside `pipeline/`, and in a worktree `pipeline/example-film`
and `pipeline/rebuilds` are symlinks to the main checkout. Now one guard,
`factory.contained`, takes a symlink out only when the lock declares it (the
factory's own `agents_lock.load` / `root_links` / `working_copy`) and its
target is the same path of the working copy.

Stand-ins only: a temp git repository (the working copy, the stand-in factory
of `tests/test_cc_api_batches.py` plus a lock) and a `git worktree` of it,
the links planted by the test as `sync` makes them. No batch is started,
nothing of the live factory is read.

What is pinned:

* a declared link `pipeline/reel` -> the working copy's: the stages, a log's
  tail, the batch, its events all read (200);
* refused (404): a link of `pipeline/*` whose target is not the working
  copy's same path, a link of a path no pattern names, `..`, a batch dir that
  is a symlink out of a declared channel, a log symlinked out of the batch;
  in the working copy itself a symlink out is never declared;
* the questions' module not loading: the batch answers `questions: []` and
  `questions_error`, not a 500; with it, `questions_error` is null;
* the contract: `BatchDetail.questions_error`, version 0.12.0;
* a channel's position (`channels._stance_path`) goes through the same guard:
  `..`, an absolute path, a symlink out of `channels/` are None.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import (                    # noqa: E402
    TMP, _N, _a_batch, _w, client, factory_tree, git)

import api                                           # noqa: E402
from api import batches, channels, factory           # noqa: E402

BID = "2026-10-09T0900Z"
LOCK = {"agents": {"x": {"path": "agents/x", "rev": "main"}},
        "links": {"root": [".env", "pipeline/*"]}}


def _tree(patterns=None):
    """(working copy, worktree): the stand-in factory with a lock, one batch
    of `reel` in the working copy, a worktree of it on branch `wt`."""
    wc = factory_tree()
    lock = dict(LOCK, links={"root": patterns if patterns is not None
                             else LOCK["links"]["root"]})
    _w(wc / "agents.lock.json", json.dumps(lock))
    _w(wc / ".gitignore", "/schedule/\n/pipeline/\n")
    git(wc, "add", "-A")
    git(wc, "commit", "-q", "-m", "the lock")
    _a_batch(wc)
    wt = TMP / f"wt-{_N[0]}"
    git(wc, "worktree", "add", "-q", "-b", f"wt-{_N[0]}", str(wt))
    (wt / "pipeline").mkdir()
    return wc.resolve(), wt


def _link(wt, rel, target):
    (wt / rel).symlink_to(target)


def _reads(c, chan, bid=BID):
    return [c.get(f"/api/batches/{chan}/{bid}{what}").status_code
            for what in ("/stages", "/logs/batch-start.s0.a0.log", "", "/events")]


def test_a_declared_link_reads():
    wc, wt = _tree()
    _link(wt, "pipeline/reel", wc / "pipeline" / "reel")        # as sync makes it
    assert factory.declared_link(wt, "pipeline/reel")
    c = client(wt)
    assert _reads(c, "reel") == [200, 200, 200, 200]
    st = c.get(f"/api/batches/reel/{BID}/stages").json()
    assert [m["marker"] for m in st["markers"]][:2] == ["batch-start", "stage-start"], st
    assert {x["name"] for x in st["logs"]} == {"slug-attempt-1.log", "batch-start.s0.a0.log"}
    tail = c.get(f"/api/batches/reel/{BID}/logs/slug-attempt-1.log", params={"bytes": 10}).json()
    assert tail["text"] == "line 999\n" and tail["truncated"], tail["text"][:80]
    one = c.get(f"/api/batches/reel/{BID}").json()
    assert one["channel"] == "reel" and one["questions"] == [] \
        and one["questions_error"] is None, one
    assert one["dir"] == f"pipeline/reel/{BID}", one                # the factory's path form
    # the path stays the worktree's: the link is in it, only the root resolved
    assert batches.batch_dir(wt, "reel", BID) == wt.resolve() / "pipeline" / "reel" / BID


def test_undeclared_links_and_traversal_are_refused():
    wc, wt = _tree()
    _link(wt, "pipeline/reel", wc / "pipeline" / "reel")
    # a link `pipeline/*` names, but not to the working copy's same path
    other = TMP / f"elsewhere-{_N[0]}"
    _a_batch(other)
    _link(wt, "pipeline/demo", other / "pipeline" / "reel")
    # a batch of a declared channel that is a symlink out of it
    (wc / "pipeline" / "reel" / "LINKED").symlink_to(other / "pipeline" / "reel" / BID)
    # a log symlinked out of the batch
    (wc / "pipeline" / "reel" / BID / "logs" / "escape.log").symlink_to(
        other / "pipeline" / "reel" / BID / "logs" / "batch-start.s0.a0.log")
    c = client(wt)
    assert not factory.declared_link(wt, "pipeline/demo")
    assert _reads(c, "demo") == [404] * 4
    assert _reads(c, "reel", "LINKED") == [404] * 4
    names = [x["name"] for x in c.get(f"/api/batches/reel/{BID}/stages").json()["logs"]]
    assert "escape.log" not in names, names
    r = c.get(f"/api/batches/reel/{BID}/logs/escape.log")
    assert r.status_code == 404 and r.json()["code"] == "unknown_log", r.text
    for ch_, b in (("..", BID), ("reel", ".."), ("reel", "..%2F.."), ("..%2Freel", BID)):
        r = c.get(f"/api/batches/{ch_}/{b}/stages")
        assert r.status_code == 404, (ch_, b, r.text)
    for parts in (("..",), ("reel", ".."), ("reel/x",), ("",), ("reel", BID, "..", "..")):
        assert factory.contained(wt, "pipeline", *parts) is None, parts


def test_a_link_no_pattern_names_is_refused():
    wc, wt = _tree(patterns=["pipeline/rebuilds"])
    _link(wt, "pipeline/reel", wc / "pipeline" / "reel")        # right target, not declared
    assert not factory.declared_link(wt, "pipeline/reel")
    assert _reads(client(wt), "reel") == [404] * 4


def test_the_working_copy_declares_nothing_to_itself():
    wc, _wt = _tree()
    out = TMP / f"out-{_N[0]}"
    _a_batch(out)
    (wc / "pipeline" / "demo").symlink_to(out / "pipeline" / "reel")
    assert not factory.declared_link(wc, "pipeline/demo")
    c = client(wc)
    assert _reads(c, "demo") == [404] * 4
    assert _reads(c, "reel") == [200] * 4                            # a real dir, as before


def test_the_patterns_match_as_glob_does():
    m = factory._matches
    assert m(("pipeline", "reel"), ("pipeline", "*"))
    assert not m(("pipeline", "reel", BID), ("pipeline", "*"))      # `*` is one segment
    assert not m(("pipeline",), ("pipeline", "*"))
    assert m(("publish", "a", "b", "x.mp4"), ("publish", "**", "*.mp4"))
    assert m(("publish", "x.mp4"), ("publish", "**", "*.mp4"))


def test_no_questions_module_is_a_soft_answer():
    wc, wt = _tree()
    _link(wt, "pipeline/reel", wc / "pipeline" / "reel")
    orig = factory.needs_you
    # what `_mod` does for a checkout with no shared/needs_you.py (the root's
    # main before 2.3)
    factory.needs_you = lambda: factory._mod("needs_you_cc0053", "shared/no_such_needs_you.py")
    try:
        try:
            factory.needs_you()
            raise AssertionError("the missing module loaded")
        except FileNotFoundError:
            pass
        r = client(wt).get(f"/api/batches/reel/{BID}")
    finally:
        factory.needs_you = orig
    assert r.status_code == 200, r.text
    one = r.json()
    assert one["questions"] == [] and "FileNotFoundError" in one["questions_error"], one
    assert one["channel"] == "reel" and one["batch_id"] == BID, one


def test_the_contract_says_questions_error():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    props = spec["components"]["schemas"]["BatchDetail"]["properties"]
    assert "questions_error" in props and "questions" in props, sorted(props)


def test_a_position_outside_channels_is_none():
    root = factory_tree()
    out = TMP / f"pos-{_N[0]}"
    out.mkdir()
    (root / "channels" / "far").symlink_to(out)
    sp = channels._stance_path
    assert sp(root, "reel", {"stance": "reel/stance.json"}) == \
        (root / "channels" / "reel" / "stance.json").resolve()
    assert sp(root, "reel", {"stance": "./reel/stance.json"}) == \
        (root / "channels" / "reel" / "stance.json").resolve()
    for rel in ("../x.json", "/etc/passwd", "far/stance.json", "reel/../../x.json"):
        assert sp(root, "reel", {"stance": rel}) is None, rel


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
