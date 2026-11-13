#!/usr/bin/env python3
"""CF-0345: the thin-pool supplement step - its order is the code's.

CF-0385: the house runner `tests/run_tests.py` is the measure of the root
suite, so this file runs on the house harness like its neighbours (`python3
<file>` prints `N/N passed`) and needs no pytest. It was written pytest-only
(an autouse fixture, monkeypatch, capsys) and the runner counted zero of its
checks. The per-check environment is `setup_function`/`teardown_function`,
which the harness below calls and pytest also honours natively.

What is held here:

* the order of the machine steps: hunter -> indexer -> (the request moves to
  `consumed/`) -> [descriptions: exit 10] -> sieve -> the three pool gates;
* a batch with no request skips the step - nothing runs, nothing is refused;
* the pool gates' `--write` in the recheck rewrites the skeleton, and the
  hunter's `candidates` survive it in `consumed/` (the driver's note on
  CF-0342), while the fresh skeleton is not a second round;
* sources still unsieved keep the step in `describing`, no recheck;
* a supplement never drops a topic: no candidate, a failed hunter - the step
  ends `done` with a warning;
* `runlog stage-start` of the stages after the Researcher is refused with
  exit 2 while the step is pending or describing, the reserve loop's stages
  are not, and `--anyway` is recorded;
* CF-0350: the hunter gets `YOUTUBE_API_KEY` from the environment or from
  `agents/trend-hunter/.env`; with neither it is not started (exit 4). A
  tool failure keeps the request out of `consumed/` (exit 3), is retried at
  most `MAX_TOOL_ATTEMPTS` times, then the topic goes on with a warning.
* CF-0426: the step's wall-clock ceiling (`supplement.max_wall_seconds`,
  default 1800) on a fake clock - spent before the hunter, between the ingest
  and the descriptions, after them, at an ingest/sieve timeout: the topics
  are `skipped` `wall_ceiling`, never dropped, and a supplement source not
  yet sieved leaves the pool the sieve's way.
* CF-0429: the indexer gets `--deadline` = start + ceiling - reserve and a
  process timeout a little past it; past the deadline neither the hunter nor
  the indexer is started; what a cut ingest wrote to 01b (`wall_ceiling`,
  `in_progress`) goes on to the descriptions and the sieve - only a cut with
  nothing in closes the step at the indexer.

The agents' scripts are never run: `advance()` takes a recorder that plays
their effect on the batch's files. Everything is written in a temp dir.
"""
import json
import os
import contextlib
import io
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import supplement  # noqa: E402

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("supplement-step-test-")
_n = [0]
FAKE_KEY = "fake-key-CF0350-not-real"
(TMP / supplement.HUNTER_ENV).parent.mkdir(parents=True, exist_ok=True)
(TMP / supplement.HUNTER_ENV).write_text(
    f"# test\n{supplement.API_KEY}={FAKE_KEY}\nOTHER=1\n")
NO_KEY_ROOT = TMP / "no-key-root"
NO_KEY_ROOT.mkdir(exist_ok=True)


_SAVED = {}


@contextlib.contextmanager
def env(**values):
    """Set (str) or remove (None) environment variables, restored on exit."""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def setup_function(fn=None):
    """The step reads the hunter's `.env` under FACTORY_ROOT - a fake one
    here, never the checkout's real key. Run before every check."""
    _SAVED.clear()
    _SAVED.update({k: os.environ.get(k) for k in ("FACTORY_ROOT", supplement.API_KEY)})
    _SAVED["cwd"] = os.getcwd()
    os.environ["FACTORY_ROOT"] = str(TMP)
    os.environ.pop(supplement.API_KEY, None)


def teardown_function(fn=None):
    os.chdir(_SAVED.pop("cwd"))
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _SAVED.clear()


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def batch(topics=("t1", "t2"), thin=("t1",), channel="example-film"):
    _n[0] += 1
    b = TMP / "pipeline" / channel / f"2026-09-23T00{_n[0]:02d}Z"
    b.mkdir(parents=True)
    (b / "01b-footage-index.json").write_text(json.dumps(
        {"sources_by_topic": {t: [f"{t}-a", f"{t}-b"] for t in topics},
         "fetched": [], "failed": [], "skipped_topics": []}))
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"scripts": [{"script_id": f"s-{t}", "topic_id": t} for t in topics],
         "skipped": [],
         "warnings": [{"topic_id": t, "warning_code": "pool_too_thin",
                       "gate": "check_anchor_coverage", "supplement": {}} for t in thin]}))
    d = b / supplement.REQUEST_DIR
    d.mkdir(parents=True)
    for t in thin:
        (d / f"{t}.json").write_text(json.dumps(skeleton(t)))
    return b


def skeleton(t):
    return {"kind": supplement.KIND, "topic_id": t, "reason_code": "pool_too_thin",
            "entities": [{"name": "Sandra Birch", "kind": "person"}],
            "shots_wanted": 5, "max_attempts": 3}


class Agents:
    """Plays the agents' scripts on the batch: records the order of the calls
    and does to the files what the real script does."""

    def __init__(self, bdir, found=True, unsieved=(), hunter_exit=0, still_thin=True,
                 search_failed=False, indexer_exit=0):
        self.b, self.found, self.unsieved = bdir, found, list(unsieved)
        self.hunter_exit, self.still_thin = hunter_exit, still_thin
        self.search_failed, self.indexer_exit = search_failed, indexer_exit
        self.calls, self.envs = [], []

    def step_of(self, argv):
        s = " ".join(argv)
        for name, mark in (("hunter", "footage_candidates.py"), ("indexer", "ingest_batch.py"),
                           ("sieve", "source_sieve.py"),
                           ("recheck-coverage", "check_anchor_coverage.py"),
                           ("recheck-sides", "check_alternate_sides.py"),
                           ("recheck-blocks", "check_block_capacity.py")):
            if mark in s:
                return name
        raise AssertionError(s)

    def __call__(self, argv, cwd, env=None, timeout=None):
        name = self.step_of(argv)
        self.calls.append(name)
        self.envs.append(env)
        if name == "hunter" and self.hunter_exit not in (0, 1):
            return self.hunter_exit          # crashed before writing anything
        if name == "indexer" and self.indexer_exit:
            return self.indexer_exit
        getattr(self, name.replace("-", "_"))(argv)
        return self.hunter_exit if name == "hunter" else 0

    def _reqs(self, argv):
        return [Path(argv[i + 1]) for i, a in enumerate(argv) if a == "--supplement"]

    def hunter(self, argv):
        for p in self._reqs(argv):
            r = json.loads(p.read_text())
            if self.search_failed:
                # no network / a refused key: fetch_youtube_signal.py failed
                r["candidates"] = []
                r["search"] = {"searches": [], "searches_unrun": [
                    {"query": "Sandra Birch", "reason_code": "search_failed",
                     "reason": "fetch_youtube_signal.py: URLError"}]}
                p.write_text(json.dumps(r))
                continue
            r["candidates"] = ([{"video_id": f"{r['topic_id']}-new", "entity": "Sandra Birch"}]
                               if self.found else [])
            p.write_text(json.dumps(r))

    def indexer(self, argv):
        i = argv.index("--supplement")
        idx = json.loads((self.b / "01b-footage-index.json").read_text())
        for p in argv[i + 1:]:
            r = json.loads(Path(p).read_text())
            new = [c["video_id"] for c in r.get("candidates") or []]
            idx.setdefault("supplements", []).append(
                {"topic_id": r["topic_id"], "new_sources": new,
                 "outcome": "sources" if new else "nothing_to_try",
                 "shots_added": 7 if new else 0})
            # CF-0338a: the new sources join the topic's pool and `fetched`.
            idx["sources_by_topic"][r["topic_id"]] += new
            idx["fetched"] += [{"video_id": v, "topic_id": r["topic_id"],
                                "supplement": {"entity": "Sandra Birch"}} for v in new]
        (self.b / "01b-footage-index.json").write_text(json.dumps(idx))

    def sieve(self, argv):
        idx = json.loads((self.b / "01b-footage-index.json").read_text())
        srcs = [{"video_id": v, "topic_id": t,
                 "verdict": "unsieved" if v in self.unsieved else "kept"}
                for t, vs in idx["sources_by_topic"].items() for v in vs]
        idx["source_sieve"] = {"ran": True, "sources": srcs, "refused": [],
                               "unsieved": list(self.unsieved)}
        (self.b / "01b-footage-index.json").write_text(json.dumps(idx))

    def recheck_coverage(self, argv):
        # The researcher's `sync()`: a still-thin topic's skeleton is written
        # whole (no candidates), a covered one's warning goes away.
        s03 = json.loads((self.b / "03-content-researcher.json").read_text())
        if not self.still_thin:
            s03["warnings"] = []
        s03.setdefault("warnings", [])
        (self.b / "03-content-researcher.json").write_text(json.dumps(s03))
        for w in s03["warnings"]:
            p = self.b / supplement.REQUEST_DIR / f"{w['topic_id']}.json"
            p.write_text(json.dumps(skeleton(w["topic_id"])))

    def recheck_sides(self, argv):
        pass

    def recheck_blocks(self, argv):
        pass


def quiet(*a, **k):
    pass


# --------------------------------------------------------------------------

def test_no_request_skips_the_step():
    b = batch(thin=())
    agents = Agents(b)
    assert supplement.verdict(b)["state"] == supplement.NONE
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and v["state"] == supplement.NONE
    assert agents.calls == []
    assert not (b / supplement.RECORD).exists()
    assert supplement.blocks("video-editor", b) is None


def test_the_order_of_the_steps():
    b = batch()
    agents = Agents(b)
    assert supplement.verdict(b)["state"] == supplement.PENDING
    code, v = supplement.advance(b, run=agents, out=quiet)
    # First half: hunter, then indexer, then the descriptions are owed.
    assert code == supplement.EXIT_DESCRIBE, code
    assert agents.calls == ["hunter", "indexer"]
    assert v["state"] == supplement.DESCRIBING
    assert not (b / supplement.REQUEST_DIR / "t1.json").exists()
    assert (b / supplement.REQUEST_DIR / supplement.CONSUMED / "t1.json").exists()
    rec = json.loads((b / supplement.RECORD).read_text())
    assert [r["step"] for r in rec["runs"][0]["steps"]] == ["hunter", "indexer", "consumed"]
    assert rec["awaiting_descriptions"] == ["t1-new"]
    # Second half: sieve, then the three pool gates in the researcher's order.
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE, code
    assert agents.calls == ["hunter", "indexer", "sieve", "recheck-coverage",
                            "recheck-sides", "recheck-blocks"]
    # The recorded order is the documented one, descriptions in between.
    seen = [s for s in supplement.STEPS if s in agents.calls or s in ("consumed", "descriptions")]
    assert seen == list(supplement.STEPS)
    assert v["state"] == supplement.DONE and v["done"] == ["t1"]


def test_the_step_runs_only_the_pending_requests():
    b = batch(thin=("t1", "t2"))
    agents = Agents(b)
    supplement.advance(b, run=agents, out=quiet)
    rec = json.loads((b / supplement.RECORD).read_text())
    hunter = next(r for r in rec["runs"][0]["steps"] if r["step"] == "hunter")
    assert sum(a == "--supplement" for a in hunter["argv"]) == 2
    assert set(rec["topics"]) == {"t1", "t2"}


def test_hunter_candidates_survive_the_recheck():
    """The driver's note on CF-0342: the gates' `--write` rewrites the
    skeleton whole and would erase the hunter's candidates."""
    b = batch()
    agents = Agents(b, still_thin=True)
    supplement.advance(b, run=agents, out=quiet)
    supplement.advance(b, run=agents, out=quiet)
    consumed = json.loads((b / supplement.REQUEST_DIR / supplement.CONSUMED / "t1.json").read_text())
    assert consumed["candidates"] == [{"video_id": "t1-new", "entity": "Sandra Birch"}]
    fresh = json.loads((b / supplement.REQUEST_DIR / "t1.json").read_text())
    assert "candidates" not in fresh
    # The fresh skeleton is not a second round: one round per topic per batch.
    v = supplement.verdict(b)
    assert v["state"] == supplement.DONE and v["pending"] == []
    calls = list(agents.calls)
    code, _ = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and agents.calls == calls


def test_unsieved_sources_keep_the_step_describing():
    b = batch()
    agents = Agents(b, unsieved=["t1-new"])
    supplement.advance(b, run=agents, out=quiet)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DESCRIBE and v["state"] == supplement.DESCRIBING
    assert "recheck-coverage" not in agents.calls
    agents.unsieved = []
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and v["state"] == supplement.DONE
    assert agents.calls.count("sieve") == 2


def test_nothing_found_ends_done_without_a_recheck_and_keeps_the_topic():
    b = batch()
    # CF-0414: an empty request after searches that ran is exit 0 and an
    # answer - no `hunter exit` pinned on the topic.
    agents = Agents(b, found=False, hunter_exit=0)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and v["state"] == supplement.DONE
    assert agents.calls == ["hunter", "indexer"]
    rec = json.loads((b / supplement.RECORD).read_text())
    t = rec["topics"]["t1"]
    assert t["outcome"] == "nothing_to_try"
    assert not any("hunter" in w for w in t["warnings"])
    s03 = json.loads((b / "03-content-researcher.json").read_text())
    assert [s["topic_id"] for s in s03["scripts"]] == ["t1", "t2"]
    assert s03["skipped"] == []


class TwoTopicHunter(Agents):
    """The hunter over two requests: t1 has candidates, t2 per `t2`:
    'all_failed' (every search failed, the run exits 1), 'partly_failed'
    (one search failed, one ran, nothing found) or 'empty' (searches ran,
    nothing found, exit 0)."""

    def __init__(self, bdir, t2, **kw):
        super().__init__(bdir, **kw)
        self.t2 = t2

    def hunter(self, argv):
        for p in self._reqs(argv):
            r = json.loads(p.read_text())
            if r["topic_id"] == "t1":
                r["candidates"] = [{"video_id": "t1-new", "entity": "Sandra Birch"}]
                r["search"] = {"searches": [{"query": "Sandra Birch"}], "searches_unrun": []}
            else:
                r["candidates"] = []
                bad = {"query": "Keanu Reeves", "reason_code": "search_failed",
                       "reason": "fetch_youtube_signal.py: URLError"}
                ran = [{"query": "Keanu Reeves interview"}]
                r["search"] = {"all_failed": {"searches": [], "searches_unrun": [bad]},
                               "partly_failed": {"searches": ran, "searches_unrun": [bad]},
                               "empty": {"searches": ran, "searches_unrun": []}}[self.t2]
            p.write_text(json.dumps(r))


def test_hunter_exit_1_is_pinned_only_on_the_topic_whose_searches_all_failed():
    b = batch(thin=("t1", "t2"))
    agents = TwoTopicHunter(b, "all_failed", hunter_exit=1)
    supplement.advance(b, run=agents, out=quiet)
    topics = json.loads((b / supplement.RECORD).read_text())["topics"]
    assert topics["t1"]["phase"] == supplement.PH_FETCHED
    assert not any("hunter" in w for w in topics["t1"]["warnings"])
    assert topics["t2"]["phase"] == supplement.PH_FAILED
    assert "every search failed" in topics["t2"]["tool_failures"][0]["reason"]


def test_a_partly_failed_empty_request_warns_its_own_topic_only():
    b = batch(thin=("t1", "t2"))
    agents = TwoTopicHunter(b, "partly_failed", hunter_exit=0)
    supplement.advance(b, run=agents, out=quiet)
    topics = json.loads((b / supplement.RECORD).read_text())["topics"]
    assert not any("hunter" in w for w in topics["t1"]["warnings"])
    assert topics["t2"]["phase"] == supplement.PH_FETCHED
    assert any(w.startswith("hunter: 1 search(es) failed") for w in topics["t2"]["warnings"])


def test_exit_0_with_an_empty_request_warns_nobody():
    b = batch(thin=("t1", "t2"))
    agents = TwoTopicHunter(b, "empty", hunter_exit=0)
    supplement.advance(b, run=agents, out=quiet)
    topics = json.loads((b / supplement.RECORD).read_text())["topics"]
    for tid in ("t1", "t2"):
        assert topics[tid]["phase"] == supplement.PH_FETCHED
        assert not any("hunter" in w for w in topics[tid]["warnings"])


def test_a_covered_pool_drops_the_warning():
    b = batch()
    agents = Agents(b, still_thin=False)
    supplement.advance(b, run=agents, out=quiet)
    supplement.advance(b, run=agents, out=quiet)
    t = json.loads((b / supplement.RECORD).read_text())["topics"]["t1"]
    assert t["warnings_before"] == ["check_anchor_coverage"] and t["warnings_after"] == []
    assert not (b / supplement.REQUEST_DIR / "t1.json").exists()


def test_the_event_footage_warning_is_a_pool_warning_of_the_step():
    """CF-0575: `event_footage_short` lays a request like `pool_too_thin`, so
    the step's recheck counts it before and after."""
    assert supplement.WARNING_CODES == ("pool_too_thin", "event_footage_short")
    b = batch()
    p = b / "03-content-researcher.json"
    d = json.loads(p.read_text())
    d["warnings"].append({"topic_id": "t1", "warning_code": "event_footage_short",
                          "gate": "event_footage", "supplement": {}})
    d["warnings"].append({"topic_id": "t2", "warning_code": "plan_unassembled",
                          "gate": "other"})
    p.write_text(json.dumps(d))
    assert supplement._warnings(b, ["t1", "t2"]) == {
        "t1": ["check_anchor_coverage", "event_footage"], "t2": []}


def test_commands_come_from_the_agents():
    b = batch()
    cmds = supplement.commands(b, ROOT, [b / supplement.REQUEST_DIR / "t1.json"])
    argv, cwd = cmds["hunter"]
    assert argv[1:] == ["scripts/footage_candidates.py", "--supplement",
                        str(b / supplement.REQUEST_DIR / "t1.json"), "--search", "--write"]
    assert cwd == ROOT / "agents" / "trend-hunter"
    argv, cwd = cmds["indexer"]
    assert argv[1:4] == ["scripts/ingest_batch.py", str(b), "--supplement"]
    assert cmds["recheck-sides"][0][-3:] == [
        "--reports", str(b / supplement.RECHECK_DIR / "coverage.json"), "--write"]


def test_the_steps_sieve_judges_and_fetches_nothing():
    """CF-0454: run 1248Z - the step's sieve re-walked another topic under the
    depth floor, downloaded and indexed a source for 11 min and was killed at
    the ceiling with both described supplement sources. The step's sieve runs
    with the sieve's own no-fetch switch (no top-up, no reserve)."""
    b = batch()
    argv, cwd = supplement.commands(b, ROOT)["sieve"]
    assert argv[1:] == ["scripts/source_sieve.py", str(b), "--no-top-up"]
    assert supplement.SIEVE_NO_FETCH == "--no-top-up"
    assert cwd == ROOT / "agents" / "footage-indexer"
    # The switch is one the sieve knows (read from the checkout when the
    # footage-indexer is there - a root worktree has no agents/ checkouts).
    for base in (ROOT, Path.home() / "shorts-content-factory"):
        script = base / "agents" / "footage-indexer" / "scripts" / "source_sieve.py"
        if script.is_file():
            text = script.read_text()
            assert '"--no-top-up"' in text and "not args.no_top_up" in text
            break


def test_a_relative_batch_path_reaches_the_agents_absolute():
    """CF-0366 (batch 1722Z): the step was called with a relative batch path,
    the hunter runs from its own directory and did not find the request.
    Every path the agents get must resolve from their own `cwd`."""
    b = batch()
    os.chdir(b.parent)                   # teardown_function goes back
    rel = Path(b.name)
    agents = Agents(b)
    seen = []

    def runner(argv, cwd, env=None, timeout=None):
        name = agents.step_of(argv)
        paths = [a for a in argv if "pipeline" in a or a.endswith(".json")]
        for a in paths:
            assert Path(a).is_absolute(), (name, a)
            assert (Path(cwd) / a).exists(), (name, a)
        seen.append(name)
        return agents(argv, cwd, env)

    cmds = supplement.commands(rel, None, [rel / supplement.REQUEST_DIR / "t1.json"])
    for argv, cwd in cmds.values():
        assert all(Path(a).is_absolute() for a in argv
                   if "pipeline" in a or a.endswith(".json")), argv
    supplement.advance(rel, run=runner, out=quiet)
    assert "hunter" in seen and "indexer" in seen
    rec = json.loads((b / supplement.RECORD).read_text())
    assert rec["topics"]["t1"]["outcome"] == "sources"


# --------------------------------------------------------------------------
# the marker gate
# --------------------------------------------------------------------------

def runlog_cli(bdir, *args):
    env = dict(os.environ, RUNLOG_BATCH=str(bdir), FACTORY_ROOT=str(TMP),
               RUNLOG_STATE_DIR=str(TMP / "state"))
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog")] + list(args),
                          capture_output=True, text=True, env=env, timeout=120)


def test_stage_start_after_the_researcher_waits_for_the_step():
    b = batch()
    assert runlog_cli(b, "batch-start", "--note", "t").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 2, p.stderr
        assert "thin-pool supplement" in p.stderr and "CF-0345" in p.stderr
        assert runlog_cli(b, "stage-start", "video-editor").returncode == 2
        # The CF-0306 reserve loop runs the indexer and the writer again.
        p = runlog_cli(b, "stage-start", "footage-indexer")
        assert p.returncode == 0, p.stderr
        assert runlog_cli(b, "stage-done", "footage-indexer").returncode == 0
        # The step's own stage opens.
        assert runlog_cli(b, "stage-start", supplement.STAGE).returncode == 0
        agents = Agents(b)
        supplement.advance(b, run=agents, out=quiet)
        assert runlog_cli(b, "stage-start", "video-editor").returncode == 2   # describing
        supplement.advance(b, run=agents, out=quiet)
        assert runlog_cli(b, "stage-done", supplement.STAGE).returncode == 0
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
    finally:
        runlog_cli(b, "batch-done")


def test_anyway_is_recorded():
    b = batch()
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "video-editor", "--anyway", "quota spent")
        assert p.returncode == 0, p.stderr
        ev = [json.loads(l) for l in (b / "RUN_EVENTS.jsonl").read_text().splitlines()
              if l.strip()]
        start = [e for e in ev if e.get("status") == "stage-start"][-1]
        assert start["supplement_override"]["reason"] == "quota spent"
        assert start["supplement_override"]["state"] == supplement.PENDING
    finally:
        runlog_cli(b, "batch-done")


def test_a_batch_without_requests_is_not_refused():
    b = batch(thin=())
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        assert runlog_cli(b, "stage-start", "video-editor").returncode == 0
    finally:
        runlog_cli(b, "batch-done")


# --------------------------------------------------------------------------
# CF-0350: the key, and a tool failure is not an answer
# --------------------------------------------------------------------------

def _left(b, tid="t1"):
    return (b / supplement.REQUEST_DIR / f"{tid}.json").exists()


def _consumed(b, tid="t1"):
    return (b / supplement.REQUEST_DIR / supplement.CONSUMED / f"{tid}.json").exists()


def test_the_key_comes_from_the_hunters_env_file_and_is_never_written():
    b = batch()
    agents = Agents(b)
    lines = []
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        supplement.advance(b, run=agents, out=lines.append)
    assert agents.calls[0] == "hunter"
    assert agents.envs[0][supplement.API_KEY] == FAKE_KEY
    assert agents.envs[1] is None               # the indexer runs in the plain env
    rec_text = (b / supplement.RECORD).read_text()
    assert FAKE_KEY not in rec_text and FAKE_KEY not in "\n".join(lines)
    assert FAKE_KEY not in stdout.getvalue()
    hunter = json.loads(rec_text)["runs"][0]["steps"][0]
    assert hunter["key_from"] == str(supplement.HUNTER_ENV)


def test_the_environment_key_wins():
    with env(**{supplement.API_KEY: "from-env"}):
        e, source = supplement.hunter_env()
        assert source == "environment" and e[supplement.API_KEY] == "from-env"
    e, source = supplement.hunter_env()
    assert e[supplement.API_KEY] == FAKE_KEY and e["OTHER"] == "1"


def test_no_key_starts_nothing_keeps_the_request_and_gives_up_after_the_retries():
    os.environ["FACTORY_ROOT"] = str(NO_KEY_ROOT)     # teardown_function restores it
    b = batch()
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_NO_KEY
    assert agents.calls == []                    # not even the hunter
    assert _left(b) and not _consumed(b)
    assert v["state"] == supplement.PENDING and v["failed"] == ["t1"]
    assert supplement.blocks("compliance-checker", b) is not None
    t = json.loads((b / supplement.RECORD).read_text())["topics"]["t1"]
    assert t["phase"] == supplement.PH_FAILED and t["attempts"] == 1
    assert t["tool_failures"][0]["reason"].startswith(supplement.NO_KEY)
    # The last attempt lets the topic go on: a warning, never a drop.
    for _ in range(supplement.MAX_TOOL_ATTEMPTS - 1):
        code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and agents.calls == []
    assert v["state"] == supplement.DONE and v["skipped"] == ["t1"]
    assert supplement.blocks("video-editor", b) is None
    assert _left(b) and not _consumed(b)
    t = json.loads((b / supplement.RECORD).read_text())["topics"]["t1"]
    assert t["phase"] == supplement.PH_SKIPPED and t["outcome"] == "tool_failed"
    assert "goes on without it" in t["warnings"][0]
    s03 = json.loads((b / "03-content-researcher.json").read_text())
    assert [s["topic_id"] for s in s03["scripts"]] == ["t1", "t2"] and s03["skipped"] == []
    # Done stays done: no further round.
    assert supplement.advance(b, run=agents, out=quiet)[0] == supplement.EXIT_DONE


def test_failed_searches_keep_the_request_and_a_later_answer_is_taken():
    b = batch()
    agents = Agents(b, search_failed=True, hunter_exit=1)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_TOOL_FAILED
    assert agents.calls == ["hunter"]            # no indexer on a failed hunt
    assert _left(b) and not _consumed(b) and v["state"] == supplement.PENDING
    agents.search_failed, agents.hunter_exit = False, 0
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DESCRIBE and _consumed(b) and not _left(b)
    t = json.loads((b / supplement.RECORD).read_text())["topics"]["t1"]
    assert t["phase"] == supplement.PH_FETCHED
    assert any(w.startswith("tool failed before") for w in t["warnings"])


def test_a_crashed_hunter_twice_skips_the_topic():
    b = batch()
    agents = Agents(b, hunter_exit=2)
    assert supplement.advance(b, run=agents, out=quiet)[0] == supplement.EXIT_TOOL_FAILED
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and v["skipped"] == ["t1"]
    assert agents.calls == ["hunter", "hunter"] and _left(b)


def test_a_failed_indexer_does_not_spend_the_hunt_again():
    b = batch()
    agents = Agents(b, indexer_exit=1)
    code, _ = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_TOOL_FAILED and _left(b) and not _consumed(b)
    agents.indexer_exit = 0
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DESCRIBE and _consumed(b)
    assert agents.calls == ["hunter", "indexer", "indexer"]


def test_a_failed_tool_holds_the_gate_until_the_retries_run_out():
    b = batch()
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        agents = Agents(b, indexer_exit=1)
        supplement.advance(b, run=agents, out=quiet)
        assert runlog_cli(b, "stage-start", "compliance-checker").returncode == 2
        supplement.advance(b, run=agents, out=quiet)
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
    finally:
        runlog_cli(b, "batch-done")


# --------------------------------------------------------------------------
# CF-0426: the wall-clock ceiling of the step (the user's decision, 2026-09-28)
# --------------------------------------------------------------------------

class Clock:
    """A wall clock the test moves by hand."""

    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _rec(b):
    return json.loads((b / supplement.RECORD).read_text())


def test_the_first_call_stamps_the_start_and_the_default_ceiling():
    b = batch()
    clock = Clock()
    supplement.advance(b, run=Agents(b), out=quiet, clock=clock)
    rec = _rec(b)
    assert rec["started_epoch"] == clock.t and rec["started_at"].endswith("Z")
    # No channels/example-film.json under this FACTORY_ROOT: the default.
    assert rec["wall_ceiling_seconds"] == supplement.DEFAULT_WALL_SECONDS == 1800
    assert rec["wall_ceiling_from"] == "default"
    # A second call keeps the first stamp: the ceiling is per batch.
    clock.t += 60
    supplement.advance(b, run=Agents(b), out=quiet, clock=clock)
    assert _rec(b)["started_epoch"] == clock.t - 60


def test_the_ceiling_comes_from_the_channel_config():
    cdir = TMP / "channels"
    cdir.mkdir(exist_ok=True)
    (cdir / "ceilingchan.json").write_text(json.dumps(
        {"channel_id": "ceilingchan", "supplement": {"max_wall_seconds": 600}}))
    b = batch(channel="ceilingchan")
    assert supplement.batch_channel(b) == "ceilingchan"
    assert supplement.wall_ceiling_seconds(b)[0] == 600
    # 01-trend-hunter.json names the channel before the directory does.
    (b / "01-trend-hunter.json").write_text(json.dumps({"channel": "elsewhere"}))
    assert supplement.batch_channel(b) == "elsewhere"
    assert supplement.wall_ceiling_seconds(b) == (1800, "default")
    (b / "01-trend-hunter.json").unlink()
    # A value the schema refuses is read as the default, never a stop.
    (cdir / "ceilingchan.json").write_text(json.dumps(
        {"channel_id": "ceilingchan", "supplement": {"max_wall_seconds": "600"}}))
    assert supplement.wall_ceiling_seconds(b)[0] == 1800




class TimedAgents(Agents):
    """The agents on a fake clock: each step takes `durations[step]` seconds;
    a step handed a `timeout` shorter than that is killed at it."""

    def __init__(self, bdir, clock, durations, honour_timeout=True, **kw):
        super().__init__(bdir, **kw)
        self.clock, self.durations = clock, dict(durations)
        self.honour_timeout = honour_timeout
        self.timeouts, self.argvs = {}, {}

    def __call__(self, argv, cwd, env=None, timeout=None):
        name = self.step_of(argv)
        self.timeouts[name] = timeout
        self.argvs[name] = list(argv)
        d = self.durations.get(name, 0)
        if self.honour_timeout and timeout is not None and d > timeout:
            self.calls.append(name)
            self.clock.t += timeout
            raise subprocess.TimeoutExpired(argv, timeout)
        self.clock.t += d
        return super().__call__(argv, cwd, env)


def _seed_started(b, clock, ago, ceiling=1800):
    (b / supplement.RECORD).parent.mkdir(parents=True, exist_ok=True)
    (b / supplement.RECORD).write_text(json.dumps(
        {"started_epoch": clock.t - ago, "started_at": "2026-09-29T00:00:00Z",
         "wall_ceiling_seconds": ceiling, "topics": {}, "runs": []}))


def _topic_goes_on(b, v, tid="t1"):
    """The ceiling never drops a topic: done, nothing held, 03 untouched."""
    assert v["state"] == supplement.DONE and tid in v["skipped"]
    assert supplement.blocks("compliance-checker", b) is None
    s03 = json.loads((b / "03-content-researcher.json").read_text())
    assert [s["topic_id"] for s in s03["scripts"]] == ["t1", "t2"] and s03["skipped"] == []
    t = _rec(b)["topics"][tid]
    assert t["phase"] == supplement.PH_SKIPPED and t["outcome"] == supplement.WALL_CEILING
    assert any(supplement.WALL_CEILING in w for w in t["warnings"])
    return t


def test_a_spent_ceiling_before_the_hunter_runs_nothing_and_keeps_the_topic():
    b = batch(thin=("t1", "t2"))
    clock = Clock()
    _seed_started(b, clock, ago=1800)
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == []
    for tid in ("t1", "t2"):
        _topic_goes_on(b, v, tid)
        assert _left(b, tid) and not _consumed(b, tid)     # the request stays
    assert _rec(b)["wall_ceiling"]["at"] == "start"
    # Done stays done.
    assert supplement.advance(b, run=agents, out=quiet, clock=clock)[0] == supplement.EXIT_DONE
    assert agents.calls == []


def test_a_retry_after_the_ceiling_is_not_run():
    b = batch()
    clock = Clock()
    agents = Agents(b, indexer_exit=1)
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_TOOL_FAILED
    clock.t += 1801
    agents.indexer_exit = 0
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == ["hunter", "indexer"]
    t = _topic_goes_on(b, v)
    assert t["hunted"] is True and t["attempts"] == 1 and _left(b)


def test_a_hunter_that_spends_the_ceiling_stops_the_step_before_the_indexer():
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"hunter": 1800})
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and "indexer" not in agents.calls
    t = _topic_goes_on(b, v)
    assert t["hunted"] is True and _left(b) and not _consumed(b)
    assert _rec(b)["wall_ceiling"]["at"] == "indexer"


def test_a_hunter_killed_at_the_ceiling_closes_the_step():
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"hunter": 1900})
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == ["hunter"]
    t = _topic_goes_on(b, v)
    assert t["hunted"] is False and _left(b) and "tool_failures" not in t
    assert _rec(b)["wall_ceiling"]["at"] == "hunter"


def test_the_ceiling_between_the_ingest_and_the_descriptions_closes_the_step():
    b = batch()
    clock = Clock()
    # An indexer that returns only at the ceiling (past its deadline and its
    # process timeout - what the net is for; here nothing kills it).
    agents = TimedAgents(b, clock, {"indexer": 1700, "hunter": 100}, honour_timeout=False)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    # Not exit 10: nobody is asked to describe what there is no time for.
    assert code == supplement.EXIT_DONE, code
    assert agents.calls == ["hunter", "indexer"]
    t = _topic_goes_on(b, v)
    assert t["fetch_outcome"] == "sources" and t["new_sources"] == ["t1-new"]
    assert "awaiting_descriptions" not in _rec(b)
    assert _rec(b)["wall_ceiling"]["at"] == "descriptions"
    _assert_withdrawn(b, "t1", ["t1-new"])
    assert t["withdrawn_sources"] == ["t1-new"]


def _assert_withdrawn(b, tid, vids, kept=()):
    """Taken out the sieve's way: out of the pool the resolve reads and out of
    `fetched`, into `failed[]` (so no walk takes it again); the topic keeps
    what it held before the supplement."""
    idx = json.loads((b / "01b-footage-index.json").read_text())
    pool = idx["sources_by_topic"][tid]
    assert pool == [f"{tid}-a", f"{tid}-b", *kept], pool
    assert not any(f["video_id"] in vids for f in idx["fetched"])
    rows = [f for f in idx["failed"] if f["video_id"] in vids]
    assert sorted(f["video_id"] for f in rows) == sorted(vids)
    for f in rows:
        assert f["topic_id"] == tid and f["reason_code"] == supplement.WITHDRAWN_CODE
        assert f["refused_at"] == supplement.WALL_CEILING == f["withdrawn"]
        assert "CF-0426" in f["error"]
    entry = [e for e in idx["supplements"] if e["topic_id"] == tid][-1]
    assert entry["withdrawn"] == list(vids) and entry["withdrawn_code"] == "wall_ceiling"
    assert not set(vids) & set((idx.get("source_sieve") or {}).get("unsieved") or [])


class TwoNewAgents(Agents):
    """The hunter brings two sources for each request."""

    def hunter(self, argv):
        for p in self._reqs(argv):
            r = json.loads(p.read_text())
            r["candidates"] = [{"video_id": f"{r['topic_id']}-{n}", "entity": "Sandra Birch"}
                               for n in ("new", "new2")]
            p.write_text(json.dumps(r))


def test_at_the_ceiling_a_kept_source_stays_and_an_unsieved_one_is_withdrawn():
    b = batch()
    clock = Clock()
    agents = TwoNewAgents(b, unsieved=["t1-new2"])
    assert supplement.advance(b, run=agents, out=quiet, clock=clock)[0] == supplement.EXIT_DESCRIBE
    clock.t += 900
    # The sieve kept t1-new and still owes t1-new2 its descriptions.
    assert supplement.advance(b, run=agents, out=quiet, clock=clock)[0] == supplement.EXIT_DESCRIBE
    clock.t += 900
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    # CF-0454: past the ceiling the sieve still judges what was described;
    # only the source still undescribed is withdrawn, the kept one stays and
    # its topic finishes (the recheck runs), not skipped.
    assert code == supplement.EXIT_DONE and agents.calls.count("sieve") == 2
    assert "recheck-coverage" in agents.calls
    assert v["state"] == supplement.DONE and "t1" in v["done"]
    t = _rec(b)["topics"]["t1"]
    assert t["phase"] == supplement.PH_DONE
    _assert_withdrawn(b, "t1", ["t1-new2"], kept=["t1-new"])
    assert t["withdrawn_sources"] == ["t1-new2"]
    assert any("CF-0454" in w and "t1-new" in w for w in t["warnings"])
    rec = _rec(b)
    assert rec["wall_ceiling"]["at"] == "sieve" and rec["wall_ceiling"]["topics"] == []
    assert rec["wall_ceiling"]["withdrawn_sources"] == {"t1": ["t1-new2"]}
    assert rec["finished_past_ceiling"]["topics"] == ["t1"]
    assert "awaiting_descriptions" not in rec
    # The other topic's pool is untouched.
    idx = json.loads((b / "01b-footage-index.json").read_text())
    assert idx["sources_by_topic"]["t2"] == ["t2-a", "t2-b"]


class KilledAfterWrite(TimedAgents):
    """An ingest killed after it wrote 01b and before it exited."""

    def __call__(self, argv, cwd, env=None, timeout=None):
        if self.step_of(argv) == "indexer":
            self.calls.append("indexer")
            self.indexer(argv)
            self.clock.t += timeout
            raise subprocess.TimeoutExpired(argv, timeout)
        return super().__call__(argv, cwd, env, timeout)


def test_an_ingest_killed_after_its_write_carries_its_source_on_and_an_overrun_withdraws_it():
    b = batch()
    clock = Clock()
    code, v = supplement.advance(b, run=KilledAfterWrite(b, clock, {}), out=quiet, clock=clock)
    # CF-0429: killed at its timeout (past its deadline), but 01b holds a
    # finished answer - its source goes on to the descriptions.
    assert code == supplement.EXIT_DESCRIBE, code
    t = _rec(b)["topics"]["t1"]
    assert t["phase"] == supplement.PH_FETCHED and t["new_sources"] == ["t1-new"]
    assert _consumed(b) and not _left(b)
    # The reserve left after the kill (600 - 60 s) is spent describing: the
    # source that was never described (the sieve still calls it unsieved,
    # CF-0454) is withdrawn at the ceiling, as before.
    clock.t += 600
    agents = KilledAfterWrite(b, clock, {}, unsieved=["t1-new"])
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == ["sieve"]
    assert agents.timeouts["sieve"] == supplement.SIEVE_GRACE_SECONDS
    t = _topic_goes_on(b, v)
    _assert_withdrawn(b, "t1", ["t1-new"])
    assert t["withdrawn_sources"] == ["t1-new"] and _rec(b)["wall_ceiling"]["at"] == "sieve"
    assert "recheck-coverage" not in agents.calls


def test_a_ceiling_with_nothing_fetched_touches_no_pool():
    b = batch()
    clock = Clock()
    _seed_started(b, clock, ago=1800)
    before = (b / "01b-footage-index.json").read_text()
    supplement.advance(b, run=Agents(b), out=quiet, clock=clock)
    assert (b / "01b-footage-index.json").read_text() == before
    assert "withdrawn_sources" not in _rec(b)["topics"]["t1"]


def test_the_ceiling_after_the_descriptions_still_sieves_the_described_sources():
    """CF-0454: the ceiling stops new work, it does not throw away work done.
    A source fetched and described is judged by the sieve even when the
    describing ran past the ceiling, and a kept one stays in the pool."""
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"sieve": 2})
    assert supplement.advance(b, run=agents, out=quiet, clock=clock)[0] == supplement.EXIT_DESCRIBE
    clock.t += 1800                            # the orchestrator described for 30 min
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE
    assert agents.calls[-4:] == ["sieve", "recheck-coverage", "recheck-sides", "recheck-blocks"]
    # Nothing left of the ceiling, and the sieve still gets its grace.
    assert agents.timeouts["sieve"] == supplement.SIEVE_GRACE_SECONDS
    assert "--no-top-up" in agents.argvs["sieve"]
    assert v["state"] == supplement.DONE and v["done"] == ["t1"]
    rec = _rec(b)
    t = rec["topics"]["t1"]
    assert t["phase"] == supplement.PH_DONE and "withdrawn_sources" not in t
    assert "wall_ceiling" not in rec and rec["finished_past_ceiling"]["task"] == "CF-0454"
    idx = json.loads((b / "01b-footage-index.json").read_text())
    assert idx["sources_by_topic"]["t1"] == ["t1-a", "t1-b", "t1-new"]
    assert not [f for f in idx["failed"] if f["video_id"] == "t1-new"]


def test_run_1248z_two_described_sources_survive_a_spent_ceiling():
    """Run 2026-09-30T1248Z replayed: three topics asked, two brought a source
    each, one nothing; the describing ended with the ceiling spent. Before
    CF-0454 the sieve was killed (854 s re-walking another topic) and both
    described sources were withdrawn `index_failed`; now both reach the pool."""
    b = batch(topics=("t1", "t2", "t3"), thin=("t1", "t2", "t3"))

    class ThreeAsked(Agents):
        def hunter(self, argv):
            for p in self._reqs(argv):
                r = json.loads(p.read_text())
                r["candidates"] = ([] if r["topic_id"] == "t3" else
                                   [{"video_id": f"{r['topic_id']}-new",
                                     "entity": "Sandra Birch"}])
                p.write_text(json.dumps(r))

    clock = Clock()
    agents = ThreeAsked(b)
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DESCRIBE
    assert _rec(b)["awaiting_descriptions"] == ["t1-new", "t2-new"]
    clock.t += 1900
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and v["state"] == supplement.DONE
    rec = _rec(b)
    for tid in ("t1", "t2"):
        assert rec["topics"][tid]["phase"] == supplement.PH_DONE
    assert rec["topics"]["t3"]["phase"] == supplement.PH_DONE
    idx = json.loads((b / "01b-footage-index.json").read_text())
    assert "t1-new" in idx["sources_by_topic"]["t1"]
    assert "t2-new" in idx["sources_by_topic"]["t2"]
    assert not [f for f in idx["failed"] if f.get("refused_at") == supplement.WALL_CEILING]


def test_a_spent_ceiling_skips_a_waiting_retry_and_still_sieves_the_fetched_topic():
    """CF-0454 at the start of a call: what still waits (a retry) is skipped
    `wall_ceiling`, the topic already fetched and described is sieved."""
    b = batch(thin=("t1", "t2"))
    clock = Clock()
    agents = TwoTopicHunter(b, "all_failed", hunter_exit=1)
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_TOOL_FAILED
    clock.t += 1300
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DESCRIBE           # t1 described, t2 skipped at the deadline
    # The orchestrator's describing overran the ceiling; t2 was re-queued by hand.
    rec = _rec(b)
    rec["topics"]["t2"]["phase"] = supplement.PH_FAILED
    (b / supplement.RECORD).write_text(json.dumps(rec))
    clock.t += 600
    n = len(agents.calls)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE
    assert agents.calls[n:] == ["sieve", "recheck-coverage", "recheck-sides", "recheck-blocks"]
    rec = _rec(b)
    assert rec["topics"]["t1"]["phase"] == supplement.PH_DONE
    assert rec["topics"]["t2"]["phase"] == supplement.PH_SKIPPED
    assert rec["topics"]["t2"]["outcome"] == supplement.WALL_CEILING
    assert _left(b, "t2")


def test_the_ingest_runs_to_its_deadline_and_a_kill_with_nothing_written_closes_the_step():
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"hunter": 100, "indexer": 42 * 60})
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE
    # CF-0429: the timeout is the net a little behind the deadline
    # (1800 - 600 reserve - 100 hunter = 1100 s, + 60 s grace), not the ceiling.
    assert approx(agents.timeouts["indexer"], 1160)
    assert approx(agents.timeouts["hunter"], 1800)
    t = _topic_goes_on(b, v)
    # A killed ingest writes no 01b: nothing was consumed, the request stays.
    assert _left(b) and not _consumed(b) and t["hunted"] is True
    rec = _rec(b)
    assert rec["wall_ceiling"]["at"] == "indexer"
    row = next(r for r in rec["runs"][-1]["steps"] if r["step"] == "indexer")
    assert row["timed_out"] is True and row["exit"] is None
    # Not counted as a tool failure: the ceiling is not the tool's fault.
    assert "tool_failures" not in t


def test_a_sieve_killed_at_the_ceiling_closes_the_step():
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"sieve": 4000})
    assert supplement.advance(b, run=agents, out=quiet, clock=clock)[0] == supplement.EXIT_DESCRIBE
    clock.t += 600
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and approx(agents.timeouts["sieve"], 1200)
    assert "recheck-coverage" not in agents.calls
    _topic_goes_on(b, v)


# --------------------------------------------------------------------------
# CF-0429: the indexer's deadline inside the ceiling
# --------------------------------------------------------------------------

def _deadline_arg(argv):
    return int(argv[argv.index("--deadline") + 1])


def test_the_reserve_is_a_third_of_the_ceiling_at_least_ten_minutes_at_most_half():
    assert supplement.indexer_reserve(1800) == 600
    assert supplement.indexer_reserve(3600) == 1200
    assert supplement.indexer_reserve(900) == 450          # capped at half
    assert supplement.indexer_reserve(600) == 300
    assert supplement.indexer_deadline({}) is None
    rec = {"started_epoch": 1000.0, "wall_ceiling_seconds": 1800}
    assert supplement.indexer_deadline(rec) == 1000.0 + 1800 - 600


def test_the_indexer_is_handed_its_deadline_and_a_timeout_past_it():
    b = batch()
    clock = Clock()
    start = clock.t
    agents = TimedAgents(b, clock, {"hunter": 100, "indexer": 300})
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DESCRIBE
    argv = agents.argvs["indexer"]
    deadline = start + 1800 - supplement.indexer_reserve(1800)
    assert _deadline_arg(argv) == int(deadline)
    # --deadline stands before the requests: `--supplement` takes the rest.
    assert argv.index("--deadline") < argv.index("--supplement")
    # The timeout ends past the deadline and inside the ceiling.
    t = agents.timeouts["indexer"]
    assert (start + 100) + t > deadline and (start + 100) + t < start + 1800
    row = next(r for r in _rec(b)["runs"][-1]["steps"] if r["step"] == "indexer")
    assert row["deadline_epoch"] == int(deadline) and row["reserve_seconds"] == 600
    # Without a deadline the argv is the plain one.
    assert "--deadline" not in supplement.commands(b, ROOT, [b / "x.json"])["indexer"][0]


def test_no_indexer_is_started_past_its_deadline():
    b = batch()
    clock = Clock()
    agents = TimedAgents(b, clock, {"hunter": 1250})     # the window is 1200 s
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == ["hunter"]
    t = _topic_goes_on(b, v)
    assert t["hunted"] is True and _left(b) and not _consumed(b)
    rec = _rec(b)
    assert rec["wall_ceiling"]["at"] == "indexer"
    assert rec["wall_ceiling"]["elapsed_seconds"] < 1800   # the ceiling itself is not spent
    assert "CF-0429" in t["warnings"][-1] and "deadline" in t["warnings"][-1]


def test_past_the_deadline_nothing_is_searched_for():
    b = batch()
    clock = Clock()
    _seed_started(b, clock, ago=1300)
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and agents.calls == []   # no quota spent
    _topic_goes_on(b, v)
    assert _rec(b)["wall_ceiling"]["at"] == "hunter" and _left(b)


def test_a_retry_past_the_deadline_is_skipped_and_the_fetched_topic_goes_on():
    b = batch(thin=("t1", "t2"))
    clock = Clock()
    agents = TwoTopicHunter(b, "all_failed", hunter_exit=1)
    code, _ = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_TOOL_FAILED
    clock.t += 1300                           # past the deadline, inside the ceiling
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    # t2's retry is not run; t1's source still gets its descriptions.
    assert code == supplement.EXIT_DESCRIBE and agents.calls == ["hunter", "indexer"]
    rec = _rec(b)
    assert rec["topics"]["t2"]["phase"] == supplement.PH_SKIPPED
    assert rec["topics"]["t2"]["outcome"] == supplement.WALL_CEILING
    assert rec["topics"]["t1"]["phase"] == supplement.PH_FETCHED
    assert rec["awaiting_descriptions"] == ["t1-new"] and "wall_ceiling" not in rec
    idx = json.loads((b / "01b-footage-index.json").read_text())
    assert "t1-new" in idx["sources_by_topic"]["t1"]


class DeadlineIndexer(TwoNewAgents):
    """The indexer as footage-indexer 2843668 plays a deadline: it stops at
    `--deadline`, and per request writes what got in and a `wall_ceiling`
    block for the candidates the deadline took. `got` - how many of a
    request's candidates got in (an int, or `{topic: int}`)."""

    def __init__(self, bdir, clock, got=1, hunter_s=100, **kw):
        super().__init__(bdir, **kw)
        self.clock, self.got, self.hunter_s = clock, got, hunter_s
        self.timeouts, self.argvs = {}, {}

    def __call__(self, argv, cwd, env=None, timeout=None):
        name = self.step_of(argv)
        self.timeouts[name], self.argvs[name] = timeout, list(argv)
        if name == "hunter":
            self.clock.t += self.hunter_s
        if name == "indexer":
            self.deadline = _deadline_arg(argv)
            assert self.clock.t + timeout > self.deadline
        out = super().__call__(argv, cwd, env)
        if name == "indexer":
            self.clock.t = self.deadline + 3      # the in-flight child killed at it
        return out

    def indexer(self, argv):
        i = argv.index("--supplement")
        path = self.b / "01b-footage-index.json"
        idx = json.loads(path.read_text())
        for p in argv[i + 1:]:
            r = json.loads(Path(p).read_text())
            tid = r["topic_id"]
            n = self.got.get(tid, 0) if isinstance(self.got, dict) else self.got
            cands = [c["video_id"] for c in r.get("candidates") or []]
            new, cut = cands[:n], cands[n:]
            e = {"topic_id": tid, "key": f"{tid}:" + ",".join(sorted(cands)),
                 "new_sources": new, "outcome": "sources" if new else "wall_ceiling",
                 "shots_added": 7 if new else 0}
            if cut:
                e["wall_ceiling"] = {
                    "deadline": "2026-09-29T00:20:00Z", "deadline_epoch": self.deadline,
                    "cause": "deadline", "task": "CF-0429",
                    "reached_at": "2026-09-29T00:20:00Z",
                    "candidates": [{"video_id": v, "entity": "Sandra Birch",
                                    "outcome": "wall_ceiling", "refused_at": "wall_ceiling",
                                    "at": "download", "task": "CF-0429",
                                    "attempt_spent": False} for v in cut]}
            idx.setdefault("supplements", []).append(e)
            idx["sources_by_topic"][tid] += new
            idx["fetched"] += [{"video_id": v, "topic_id": tid,
                                "supplement": {"entity": "Sandra Birch"}} for v in new]
        path.write_text(json.dumps(idx))


def test_a_deadline_cut_keeps_what_got_in_and_it_reaches_the_pool():
    b = batch()
    clock = Clock()
    agents = DeadlineIndexer(b, clock, got=1)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    # Not closed at the ceiling: what got in goes on to be described.
    assert code == supplement.EXIT_DESCRIBE, code
    rec = _rec(b)
    t = rec["topics"]["t1"]
    assert t["phase"] == supplement.PH_FETCHED and t["new_sources"] == ["t1-new"]
    assert t["outcome"] == "sources"
    assert t["indexer_cut"]["candidates"] == ["t1-new2"]
    assert t["indexer_cut"]["cause"] == "deadline"
    assert any("CF-0429" in w for w in t["warnings"])
    assert rec["awaiting_descriptions"] == ["t1-new"] and "wall_ceiling" not in rec
    assert rec["indexer_deadline"]["carried_forward"] == {"t1": ["t1-new"]}
    assert _consumed(b) and not _left(b)
    # The describing fits the reserve: the sieve and the recheck run, the
    # source is in the pool the Editor reads, nothing withdrawn.
    clock.t += 400
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE and v["state"] == supplement.DONE
    assert agents.calls[-4:] == ["sieve", "recheck-coverage", "recheck-sides", "recheck-blocks"]
    t = _rec(b)["topics"]["t1"]
    assert t["phase"] == supplement.PH_DONE and "withdrawn_sources" not in t
    idx = json.loads((b / "01b-footage-index.json").read_text())
    assert idx["sources_by_topic"]["t1"] == ["t1-a", "t1-b", "t1-new"]
    assert idx["failed"] == []


def test_a_deadline_cut_with_nothing_in_closes_the_step_as_at_the_ceiling():
    b = batch()
    clock = Clock()
    code, v = supplement.advance(b, run=DeadlineIndexer(b, clock, got=0), out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE
    t = _topic_goes_on(b, v)
    assert t["hunted"] is True and "tool_failures" not in t
    assert _left(b) and not _consumed(b)
    assert _rec(b)["wall_ceiling"]["at"] == "indexer"


def test_a_deadline_cut_splits_topics_by_what_got_in():
    b = batch(thin=("t1", "t2"))
    clock = Clock()
    agents = DeadlineIndexer(b, clock, got={"t1": 2, "t2": 0})
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DESCRIBE
    rec = _rec(b)
    assert rec["topics"]["t1"]["phase"] == supplement.PH_FETCHED
    assert "indexer_cut" not in rec["topics"]["t1"]          # t1 was not cut
    t2 = rec["topics"]["t2"]
    assert t2["phase"] == supplement.PH_SKIPPED and t2["outcome"] == supplement.WALL_CEILING
    assert t2["indexer_cut"]["candidates"] == ["t2-new", "t2-new2"]
    assert "tool_failures" not in t2
    # Both answered requests are consumed: the recheck that runs for t1 would
    # rewrite a left skeleton whole and lose t2's candidates.
    assert _consumed(b, "t1") and _consumed(b, "t2")
    assert rec["indexer_deadline"]["skipped"] == ["t2"]
    assert rec["awaiting_descriptions"] == ["t1-new", "t1-new2"]
    assert v["state"] == supplement.DESCRIBING


def test_a_hunter_failure_in_a_call_that_ran_to_the_deadline_is_not_retried():
    b = batch(thin=("t1", "t2"))
    clock = Clock()
    agents = DeadlineIndexer(b, clock, got=1, hunter_exit=1)
    agents.t2 = "all_failed"
    agents.hunter = lambda argv: TwoTopicHunter.hunter(agents, argv)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    # Not exit 3: the retry could not be fetched any more; t1 goes on.
    assert code == supplement.EXIT_DESCRIBE, code
    rec = _rec(b)
    t2 = rec["topics"]["t2"]
    assert t2["phase"] == supplement.PH_SKIPPED and t2["outcome"] == supplement.WALL_CEILING
    assert len(t2["tool_failures"]) == 1 and _left(b, "t2")
    assert rec["topics"]["t1"]["phase"] == supplement.PH_FETCHED


class InProgressKilled(TimedAgents):
    """An indexer killed at the root's timeout after it flushed one source:
    its entry is `in_progress`."""

    def __call__(self, argv, cwd, env=None, timeout=None):
        if self.step_of(argv) != "indexer":
            return super().__call__(argv, cwd, env, timeout)
        self.calls.append("indexer")
        path = self.b / "01b-footage-index.json"
        idx = json.loads(path.read_text())
        idx.setdefault("supplements", []).append(
            {"topic_id": "t1", "new_sources": ["t1-new"], "outcome": "in_progress"})
        idx["sources_by_topic"]["t1"] += ["t1-new"]
        idx["fetched"] += [{"video_id": "t1-new", "topic_id": "t1"}]
        path.write_text(json.dumps(idx))
        self.clock.t += timeout
        raise subprocess.TimeoutExpired(argv, timeout)


def test_an_in_progress_entry_of_a_killed_indexer_is_carried_on():
    b = batch()
    clock = Clock()
    code, v = supplement.advance(b, run=InProgressKilled(b, clock, {}), out=quiet, clock=clock)
    assert code == supplement.EXIT_DESCRIBE
    t = _rec(b)["topics"]["t1"]
    assert t["phase"] == supplement.PH_FETCHED and t["new_sources"] == ["t1-new"]
    assert t["outcome"] == "sources" and t["fetch_outcome"] == "in_progress"
    assert t["indexer_cut"]["cause"] == "root_timeout"
    row = next(r for r in _rec(b)["runs"][-1]["steps"] if r["step"] == "indexer")
    assert row["timed_out"] is True and "tool_failures" not in t


def test_a_stale_entry_is_not_read_as_this_calls_answer():
    """A killed call that wrote nothing is not answered by an entry an
    earlier call left for the same topic."""
    b = batch()
    idx = json.loads((b / "01b-footage-index.json").read_text())
    idx["supplements"] = [{"topic_id": "t1", "new_sources": [], "outcome": "no_new_source"}]
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    clock = Clock()
    agents = TimedAgents(b, clock, {"indexer": 5000})
    code, v = supplement.advance(b, run=agents, out=quiet, clock=clock)
    assert code == supplement.EXIT_DONE
    _topic_goes_on(b, v)
    assert _left(b)


def test_the_real_runner_kills_the_whole_group_at_its_timeout():
    tmp_path = Path(tempfile.mkdtemp(dir=TMP))
    pidfile = tmp_path / "child.pid"
    code = ("import subprocess, sys, time; "
            "c = subprocess.Popen(['sleep', '60']); "
            f"open({str(pidfile)!r}, 'w').write(str(c.pid)); time.sleep(60)")
    import time as _t
    t0 = _t.time()
    try:
        supplement._run([sys.executable, "-c", code], tmp_path, timeout=2)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("no TimeoutExpired at the timeout")
    assert _t.time() - t0 < 20
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        _t.sleep(0.1)
    else:
        raise AssertionError(f"the grandchild {pid} outlived the timeout")


# --------------------------------------------------------------------------
# CF-0494: a verification rerun that may not search
# --------------------------------------------------------------------------

def _events(b):
    return [json.loads(l) for l in (b / "RUN_EVENTS.jsonl").read_text().splitlines()
            if l.strip()]


def test_a_no_search_rerun_closes_every_request_without_a_tool_or_a_question():
    b = batch(thin=("t1", "t2"))
    p = runlog_cli(b, "batch-start", "--rerun", "no-search", "--note", "verification rerun")
    assert p.returncode == 0, p.stderr
    try:
        start = [e for e in _events(b) if e.get("status") == "batch-start"][-1]
        assert start["rerun"]["mode"] == supplement.RERUN_NO_SEARCH_MODE, start
        assert supplement.rerun_mode(b) == supplement.RERUN_NO_SEARCH_MODE
        lines = []
        agents = Agents(b)
        code, v = supplement.advance(b, run=agents, out=lines.append)
        assert code == supplement.EXIT_DONE, code
        assert agents.calls == [], agents.calls          # no hunter, no indexer
        assert v["state"] == supplement.DONE and v["skipped"] == ["t1", "t2"], v
        rec = _rec(b)
        for t in ("t1", "t2"):
            x = rec["topics"][t]
            assert x["phase"] == supplement.PH_SKIPPED, x
            assert x["outcome"] == supplement.RERUN_NO_SEARCH, x
            assert "CF-0494" in x["warnings"][0], x
            assert _left(b, t) and not _consumed(b, t)   # the request stays where it lies
        assert "started_epoch" not in rec                # no clock: nothing was run
        assert [r["half"] for r in rec["runs"]] == ["rerun-no-search"], rec["runs"]
        assert rec["runs"][0]["steps"][0]["topics"] == ["t1", "t2"]
        assert any(supplement.RERUN_NO_SEARCH in l for l in lines), lines
        # the stages after the step open, with no --anyway
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
        # a second call is a no-op
        code, v = supplement.advance(b, run=agents, out=quiet)
        assert code == supplement.EXIT_DONE and agents.calls == []
    finally:
        runlog_cli(b, "batch-done")


def test_without_the_flag_the_step_searches_as_before():
    b = batch()
    assert runlog_cli(b, "batch-start", "--note", "a no-search verification rerun").returncode == 0
    try:
        # the note says "no-search" - a note is not the mode
        assert supplement.rerun_mode(b) is None
        agents = Agents(b)
        code, _ = supplement.advance(b, run=agents, out=quiet)
        assert agents.calls == ["hunter", "indexer"], agents.calls
    finally:
        runlog_cli(b, "batch-done")


def test_a_record_written_by_hand_is_not_the_mode():
    b = batch()
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        (b / supplement.RECORD).write_text(json.dumps(
            {"task": "CF-0345", "topics": {}, "runs": [], "rerun": "no_search"}))
        agents = Agents(b)
        supplement.advance(b, run=agents, out=quiet)
        assert agents.calls == ["hunter", "indexer"], agents.calls
    finally:
        runlog_cli(b, "batch-done")


def test_the_rerun_flag_belongs_to_batch_start_only():
    b = batch(thin=())
    p = runlog_cli(b, "batch-start", "--rerun", "everything")
    assert p.returncode == 2 and "invalid choice" in p.stderr, p.stderr
    assert not (b / "RUN_EVENTS.jsonl").exists()
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "video-editor", "--rerun", "no-search")
        assert p.returncode == 2, p.stderr
        import runlog
        try:
            runlog.marker("stage-start", stage="video-editor", batch_dir=b,
                          rerun="no-search")
            raise AssertionError("a stage-start took --rerun")
        except runlog.RunlogError as e:
            assert "CF-0494" in str(e), e
        assert supplement.rerun_mode(b) is None
    finally:
        runlog_cli(b, "batch-done")


# --------------------------------------------------------------------------


def test_the_steps_children_get_the_batch_env_absolute():
    """CF-0541 (batch 0701Z): `RUNLOG_BATCH` relative in the operator's shell,
    the hunter and the indexer run from their own directories - the step
    hands them the absolute path, so their events reach the batch journal."""
    b = batch()
    os.chdir(b.parent.parent)            # teardown_function goes back
    rel = str(Path(b.parent.name) / b.name)
    saved = os.environ.get("RUNLOG_BATCH")
    os.environ["RUNLOG_BATCH"] = rel
    try:
        env = supplement.child_env()
        assert env["RUNLOG_BATCH"] == str(b.resolve()), env["RUNLOG_BATCH"]
        assert env["RUNLOG_STAGE"] == supplement.STAGE
        # the hunter's own environment goes through the same door
        assert supplement.child_env(dict(os.environ))["RUNLOG_BATCH"] == str(b.resolve())
        elsewhere = TMP / "agents" / "trend-hunter"
        elsewhere.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = supplement._run([sys.executable, "-c",
                                    "import os; print(os.environ['RUNLOG_BATCH'])"],
                                   elsewhere, timeout=60)
        assert code == 0
        assert buf.getvalue().strip() == str(b.resolve()), buf.getvalue()
    finally:
        if saved is None:
            os.environ.pop("RUNLOG_BATCH", None)
        else:
            os.environ["RUNLOG_BATCH"] = saved


# --------------------------------------------------------------------------
# CF-0826: a topic gone from 03's scripts[] is not searched for
# --------------------------------------------------------------------------

def _drop(b, tid, reason_code="score_below_threshold"):
    """03 takes the topic out of `scripts[]` the way a gate does: into
    `skipped[]` with its reason (reason_code None: just gone from scripts[])."""
    p = b / "03-content-researcher.json"
    s03 = json.loads(p.read_text())
    s03["scripts"] = [s for s in s03["scripts"] if s["topic_id"] != tid]
    if reason_code:
        s03["skipped"].append({"topic_id": tid, "reason_code": reason_code})
    p.write_text(json.dumps(s03))


def test_a_dropped_topic_is_closed_without_a_search_or_a_clock():
    b = batch(thin=("t1",))
    _drop(b, "t1", "score_below_threshold")
    agents, lines = Agents(b), []
    code, v = supplement.advance(b, run=agents, out=lines.append, clock=Clock())
    assert code == supplement.EXIT_DONE, code
    assert agents.calls == [], agents.calls             # no hunter: no search.list spent
    assert v["state"] == supplement.DONE and v["skipped"] == ["t1"], v
    rec = _rec(b)
    x = rec["topics"]["t1"]
    assert x["phase"] == supplement.PH_SKIPPED and x["outcome"] == supplement.TOPIC_DROPPED, x
    assert supplement.TOPIC_DROPPED == "topic_dropped"
    assert x["dropped"] == "03 skipped[] score_below_threshold", x
    assert "CF-0826" in x["warnings"][0], x
    assert "started_epoch" not in rec                   # no clock: nothing was run
    assert [r["half"] for r in rec["runs"]] == ["topic-dropped"], rec["runs"]
    assert rec["runs"][0]["steps"][0]["topics"] == ["t1"]
    assert _left(b) and not _consumed(b)                # the request stays where it lies
    assert any(supplement.TOPIC_DROPPED in l for l in lines), lines
    assert supplement.blocks("video-editor", b) is None
    # done stays done
    assert supplement.advance(b, run=agents, out=quiet)[0] == supplement.EXIT_DONE
    assert agents.calls == []


def test_only_the_live_topics_request_reaches_the_hunter():
    b = batch(topics=("t1", "t2"), thin=("t1", "t2"))
    _drop(b, "t2", None)                                # gone from scripts[], no skipped row
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DESCRIBE and agents.calls == ["hunter", "indexer"], code
    rec = _rec(b)
    hunter = next(r for r in rec["runs"][-1]["steps"] if r["step"] == "hunter")
    reqs = [hunter["argv"][i + 1] for i, a in enumerate(hunter["argv"]) if a == "--supplement"]
    assert [Path(r).name for r in reqs] == ["t1.json"], reqs
    assert rec["topics"]["t2"]["outcome"] == supplement.TOPIC_DROPPED
    assert rec["topics"]["t2"]["dropped"] == "not in 03 scripts[]"
    assert rec["topics"]["t1"]["phase"] == supplement.PH_FETCHED
    assert v["skipped"] == ["t2"] and v["describing"] == ["t1"], v


def test_a_deferred_script_is_alive_and_searched_for():
    """CF-0422: a script deferred at 6b for the supplement stays in scripts[]."""
    b = batch(thin=("t1",))
    p = b / "03-content-researcher.json"
    s03 = json.loads(p.read_text())
    s03["scripts"][0]["plan_check"] = {"deferred_for_supplement": {"check": 1}}
    p.write_text(json.dumps(s03))
    agents = Agents(b)
    supplement.advance(b, run=agents, out=quiet)
    assert agents.calls == ["hunter", "indexer"], agents.calls


def test_without_a_readable_03_the_step_searches_as_before():
    b = batch(thin=("t1",))
    (b / "03-content-researcher.json").unlink()
    agents = Agents(b)
    supplement.advance(b, run=agents, out=quiet)
    assert agents.calls == ["hunter", "indexer"], agents.calls
    assert supplement.live_topics(b) is None


def test_a_failed_retry_of_a_topic_dropped_since_is_not_run_again():
    os.environ["FACTORY_ROOT"] = str(NO_KEY_ROOT)       # teardown_function restores it
    b = batch(thin=("t1",))
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_NO_KEY and v["failed"] == ["t1"]
    _drop(b, "t1", "plan_unassembled")
    code, v = supplement.advance(b, run=agents, out=quiet)
    assert code == supplement.EXIT_DONE and agents.calls == [], (code, agents.calls)
    x = _rec(b)["topics"]["t1"]
    assert x["outcome"] == supplement.TOPIC_DROPPED and x["attempts"] == 1, x
    assert x["tool_failures"][0]["reason"].startswith(supplement.NO_KEY), x



# --------------------------------------------------------------------------
# CF-0842: a channel switches the step off
# --------------------------------------------------------------------------

def _chan(name, block):
    cdir = TMP / "channels"
    cdir.mkdir(exist_ok=True)
    (cdir / f"{name}.json").write_text(json.dumps({"channel_id": name, "supplement": block}))


def test_a_switched_off_channel_closes_every_request_without_a_search_or_a_clock():
    _chan("offchan", {"max_wall_seconds": 1800, "enabled": False})
    b = batch(thin=("t1", "t2"), channel="offchan")
    assert supplement.supplement_enabled(b) == (
        False, "channels/offchan.json supplement.enabled")
    agents, lines = Agents(b), []
    code, v = supplement.advance(b, run=agents, out=lines.append, clock=Clock())
    assert code == supplement.EXIT_DONE, code
    assert agents.calls == [], agents.calls             # no hunter: no search.list spent
    assert v["state"] == supplement.DONE and v["skipped"] == ["t1", "t2"], v
    rec = _rec(b)
    for t in ("t1", "t2"):
        x = rec["topics"][t]
        assert x["phase"] == supplement.PH_SKIPPED, x
        assert x["outcome"] == supplement.SUPPLEMENT_DISABLED == "supplement_disabled", x
        assert x["disabled_by"] == "channels/offchan.json supplement.enabled", x
        assert "CF-0842" in x["warnings"][0], x
        assert _left(b, t) and not _consumed(b, t)      # the request stays where it lies
    assert "started_epoch" not in rec                   # no clock: nothing was run
    assert [r["half"] for r in rec["runs"]] == ["supplement-disabled"], rec["runs"]
    assert rec["runs"][0]["steps"][0]["topics"] == ["t1", "t2"]
    assert any(supplement.SUPPLEMENT_DISABLED in l for l in lines), lines
    for stage in supplement.GATED_STAGES:               # the stages after it open
        assert supplement.blocks(stage, b) is None, stage
    # done stays done
    assert supplement.advance(b, run=agents, out=quiet)[0] == supplement.EXIT_DONE
    assert agents.calls == []
    # a later round's request (CF-0645 late, CF-0802 after the judge) is closed the same way
    d = b / supplement.REQUEST_DIR
    (d / "t3.json").write_text(json.dumps(skeleton("t3")))
    s03 = json.loads((b / "03-content-researcher.json").read_text())
    s03["scripts"].append({"script_id": "s-t3", "topic_id": "t3"})
    (b / "03-content-researcher.json").write_text(json.dumps(s03))
    code, v = supplement.advance(b, run=agents, out=quiet, clock=Clock())
    assert code == supplement.EXIT_DONE and agents.calls == [], (code, agents.calls)
    assert _rec(b)["topics"]["t3"]["outcome"] == supplement.SUPPLEMENT_DISABLED
    assert "started_epoch" not in _rec(b)


def test_the_dry_run_says_the_step_is_off():
    _chan("offchan", {"enabled": False})
    b = batch(channel="offchan")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert supplement.main([str(b), "--dry-run", "--json"]) == supplement.EXIT_DONE
    plan = json.loads(buf.getvalue())
    assert plan["enabled"] is False and plan["verdict"]["state"] == supplement.PENDING, plan
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        supplement.main([str(b), "--dry-run"])
    assert supplement.SUPPLEMENT_DISABLED in buf.getvalue(), buf.getvalue()
    assert not (b / supplement.RECORD).exists()         # a dry run writes nothing


def test_only_a_literal_false_switches_the_step_off():
    for name, block in (("onchan", {"enabled": True}), ("nokeychan", {"max_wall_seconds": 900}),
                        ("strchan", {"enabled": "false"}), ("zerochan", {"enabled": 0})):
        _chan(name, block)
        b = batch(channel=name)
        assert supplement.supplement_enabled(b) == (True, "default"), name
        agents = Agents(b)
        supplement.advance(b, run=agents, out=quiet, clock=Clock())
        assert agents.calls[:1] == ["hunter"], (name, agents.calls)   # searched as before
    # no config at all: on
    b = batch(channel="nosuchchannel")
    assert supplement.supplement_enabled(b) == (True, "default")


def test_the_schema_takes_a_boolean_switch_only():
    sys.path.insert(0, str(ROOT / "patterns"))
    import validate_patterns as vp
    for ok in (True, False):
        assert vp.validate_supplement_block({"supplement": {"enabled": ok}}) == [], ok
    assert vp.validate_supplement_block(
        {"supplement": {"enabled": False, "enabled_note": "why"}}) == []
    for bad in ("false", 0, 1, None, []):
        errs = vp.validate_supplement_block({"supplement": {"enabled": bad}})
        assert errs and "CF-0842" in errs[0], (bad, errs)





# --------------------------------------------------------------------------
# CF-0845: a topic under the channel's floor of usable shots is not searched for
# --------------------------------------------------------------------------

def _depth(b, usable):
    """Write the indexer's `pool_depth.topics[]` into the batch's 01b:
    `{topic: usable_shots | None (unmeasured)}`."""
    p = b / "01b-footage-index.json"
    idx = json.loads(p.read_text())
    idx["pool_depth"] = {"floor": 60, "thin": [], "topics": [
        {"topic_id": t, "usable_shots": n or 0, "measured": n is not None}
        for t, n in usable.items()]}
    p.write_text(json.dumps(idx))


def _cr_chan(name, floor):
    cdir = TMP / "channels"
    cdir.mkdir(exist_ok=True)
    (cdir / f"{name}.json").write_text(json.dumps(
        {"channel_id": name, "content_researcher": {"min_usable_shots_for_script": floor}}))


def test_a_topic_under_the_floor_is_closed_too_thin_and_the_rest_is_searched():
    _cr_chan("floorchan", 10)
    b = batch(thin=("t1", "t2"), channel="floorchan")
    _depth(b, {"t1": 2, "t2": 40})
    agents, lines = Agents(b), []
    hunted = []
    real_hunter = agents.hunter
    agents.hunter = lambda argv: (hunted.extend(p.stem for p in agents._reqs(argv)),
                                  real_hunter(argv))
    supplement.advance(b, run=agents, out=lines.append, clock=Clock())
    assert agents.calls[:1] == ["hunter"] and hunted == ["t2"], (agents.calls, hunted)
    x = _rec(b)["topics"]["t1"]
    assert x["phase"] == supplement.PH_SKIPPED, x
    assert x["outcome"] == supplement.TOO_THIN == "too_thin", x
    assert x["usable_shots_before"] == 2 and x["min_usable_shots"] == 10, x
    assert x["floor_from"] == "channels/floorchan.json content_researcher.min_usable_shots_for_script"
    assert "CF-0845" in x["warnings"][0], x
    assert _left(b, "t1") and not _consumed(b, "t1")    # the request stays where it lies
    assert _rec(b)["topics"]["t2"].get("outcome") != supplement.TOO_THIN
    runs = [r for r in _rec(b)["runs"] if r["half"] == "too-thin"]
    assert runs and runs[0]["steps"][0]["topics"] == ["t1"], _rec(b)["runs"]
    assert runs[0]["steps"][0]["usable_shots"] == {"t1": 2}, runs
    assert any(supplement.TOO_THIN in l and "t1" in l for l in lines), lines


def test_only_thin_topics_close_the_step_without_a_tool_or_a_clock():
    _cr_chan("floorchan", 10)
    b = batch(thin=("t1", "t2"), channel="floorchan")
    _depth(b, {"t1": 0, "t2": 9})
    agents = Agents(b)
    code, v = supplement.advance(b, run=agents, out=quiet, clock=Clock())
    assert code == supplement.EXIT_DONE and agents.calls == [], (code, agents.calls)
    assert v["state"] == supplement.DONE and v["skipped"] == ["t1", "t2"], v
    assert "started_epoch" not in _rec(b)               # no clock: nothing was run
    for stage in supplement.GATED_STAGES:               # the stages after it open
        assert supplement.blocks(stage, b) is None, stage


def test_at_the_floor_unmeasured_or_with_the_rule_off_it_searches_as_before():
    _cr_chan("floorchan", 10)
    _cr_chan("nofloor", 0)
    for channel, usable in (("floorchan", {"t1": 10}),       # at the floor: not under it
                            ("floorchan", {"t1": None}),     # never measured
                            ("floorchan", {}),               # no row at all
                            ("nofloor", {"t1": 0})):         # 0 switches the rule off
        b = batch(thin=("t1",), channel=channel)
        _depth(b, usable)
        agents = Agents(b)
        supplement.advance(b, run=agents, out=quiet, clock=Clock())
        assert agents.calls[:1] == ["hunter"], (channel, usable, agents.calls)
        assert _rec(b)["topics"]["t1"].get("outcome") != supplement.TOO_THIN, (channel, usable)


def test_the_default_floor_is_10_without_the_key():
    b = batch(thin=("t1",), channel="nosuchchannel")
    _depth(b, {"t1": 7})
    agents = Agents(b)
    supplement.advance(b, run=agents, out=quiet, clock=Clock())
    assert agents.calls == [] and _rec(b)["topics"]["t1"]["outcome"] == supplement.TOO_THIN


def test_example_film_closes_a_topic_of_0_usable_shots():
    """The real tracked config (10, the user's signature of 2026-10-21, Q8);
    the batch is a stand-in under the temp root - the case of Reel 21.10,
    topics 001 and 005 with 0 usable shots each."""
    b = batch(thin=("t1", "t2"), channel="example-film")
    _depth(b, {"t1": 0, "t2": 0})
    agents = Agents(b)
    code, v = supplement.advance(b, root=ROOT, run=agents, out=quiet, clock=Clock())
    assert code == supplement.EXIT_DONE and agents.calls == [], (code, agents.calls)
    assert v["skipped"] == ["t1", "t2"], v
    rec = _rec(b)
    assert {rec["topics"][t]["outcome"] for t in ("t1", "t2")} == {supplement.TOO_THIN}
    assert rec["topics"]["t1"]["floor_from"] == (
        "channels/example-film.json content_researcher.min_usable_shots_for_script")


def test_example_tech_calls_no_topic_too_thin():
    """CF-0863: the real tracked Tech config switches the floor off (0) - a
    topic of 0 usable shots is not `too_thin` there (Reel above keeps 10)."""
    b = batch(thin=("t1", "t2"), channel="example-tech")
    _depth(b, {"t1": 0, "t2": 3})
    assert supplement.too_thin_topics(b, ROOT) == {}

def test_the_dry_run_names_the_thin_topics():
    _cr_chan("floorchan", 10)
    b = batch(thin=("t1", "t2"), channel="floorchan")
    _depth(b, {"t1": 1, "t2": 50})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert supplement.main([str(b), "--dry-run", "--json"]) == supplement.EXIT_DONE
    assert json.loads(buf.getvalue())["too_thin"] == ["t1"], buf.getvalue()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        supplement.main([str(b), "--dry-run"])
    assert supplement.TOO_THIN in buf.getvalue() and "t1" in buf.getvalue(), buf.getvalue()
    assert not (b / supplement.RECORD).exists()         # a dry run writes nothing


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items()
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        setup_function(fn)
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
        finally:
            teardown_function(fn)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
