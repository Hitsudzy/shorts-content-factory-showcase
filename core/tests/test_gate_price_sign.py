#!/usr/bin/env python3
"""CF-0721: the user's signature and decision on a gate's price, written from
the command center - `gate_price.sign` / `gate_price.decide`.

Every root is a temp dir (a git repo where a commit is pinned) with a small
ledger of its own; the live ledger, pipeline/ and the batches are never read
or written. No network.

What is pinned:

* `sign` writes `rules.<rule>.signature = {user, date, price, note, via}` and
  nothing else of the ledger, as one commit of exactly that file; `decide`
  writes `rules.<rule>.decision = {user, date, mode, task, note, via}`;
* the refusals: by/via missing or malformed (`bad_who`), a `by` that reads as
  a model/agent/script (`not_human`), a `via` that is not the center
  (`bad_via`), no note (`empty_note`), a bad date, an unknown rule, a
  score-model row (`not_signable`), a price under the measured one or not a
  number, a rule nothing measured, a signature that already covers the price,
  a decision mode that would refuse, a bad task id;
* any fresh open batch (any channel) refuses `batch_open`; a stale one does not;
* a ledger that changed since the caller read it is `check_changed`;
* the ledger lock held by somebody else is `locked`; `write_ledger` takes it too;
* dry_run writes nothing; commit=False writes atomically without a commit; a
  root that is not a repository refuses a commit (`not_repo`);
* the source guard: outside `_write_block` (called by `sign` and `decide`
  only) gate_price.py sets a `signature` / `decision` to nothing but None.
"""
import inspect
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import gate_price as gp            # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("gate-price-sign-test-")
_n = [0]
WHO = {"by": "Example Reviewer", "via": "center"}
NO_BATCH = {"open_rows": []}
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

LEDGER = {
    "note": "a test ledger",
    "rules": {
        "gate.unsigned": {"what": "video", "measured": {"price": 2, "verdict": "warn"},
                          "signature": None},
        "gate.stale": {"what": "video", "measured": {"price": 3, "verdict": "warn"},
                       "signature": {"user": "u", "date": "2026-09-01", "price": 1,
                                     "note": "old"}},
        "gate.covered": {"what": "video", "measured": {"price": 1, "verdict": "enforce"},
                         "signature": {"user": "u", "date": "2026-09-01", "price": 1,
                                       "note": "mine"}},
        "gate.blind": {"what": "topic", "measured": {"price": None, "verdict": "warn"},
                       "signature": None},
        "score.some": {"mode": "penalty", "signature": {"user": "u", "date": "2026-09-30",
                                                        "mode": "penalty", "price": 3,
                                                        "note": "table"}},
    },
}


def _git(root, *args):
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def _root(repo=True):
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    (r / "shared").mkdir(parents=True)
    (r / ".gitignore").write_text("shared/.gate-prices.lock\n")
    gp.ledger_path(r).write_text(json.dumps(LEDGER, ensure_ascii=False, indent=2) + "\n")
    if repo:
        _git(r, "init", "-q")
        _git(r, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(r, "config", "user.email", "t@example.test")
        _git(r, "config", "user.name", "t")
        _git(r, "add", "-A")
        _git(r, "commit", "-qm", "c1")
    return r


def _doc(r):
    return json.loads(gp.ledger_path(r).read_text(encoding="utf-8"))


def _codes(res):
    return [x["code"] for x in res["refusals"]]


def _sign(r, rule="gate.unsigned", price=2, note="подписываю", **kw):
    args = {**WHO, **NO_BATCH, "now": NOW, "base_sha256": gp.ledger_sha256(r), "root": r, **kw}
    return gp.sign(rule, price, note, args.pop("by"), args.pop("via"), **args)


def _decide(r, rule="gate.unsigned", mode="warn", task="CF-0330", note="предупреждение", **kw):
    args = {**WHO, **NO_BATCH, "now": NOW, "base_sha256": gp.ledger_sha256(r), "root": r, **kw}
    return gp.decide(rule, mode, task, note, args.pop("by"), args.pop("via"), **args)


def _lock_file(r):
    return r / "shared" / ".gate-prices.lock"


# ------------------------------------------------------------------ the writes
def test_sign_writes_only_the_signature_and_commits_the_ledger_alone():
    r = _root()
    (r / "other.txt").write_text("somebody else's\n")
    _git(r, "add", "other.txt")
    head, before = _git(r, "rev-parse", "HEAD"), _doc(r)
    res = _sign(r, note="  подписываю  ")
    assert res["ok"] and res["written"] and not res["refusals"], res
    sig = {"user": WHO["by"], "date": "2026-10-13", "price": 2, "note": "подписываю",
           "via": "center"}
    assert res["block"] == sig and res["task"] == "CF-0721" and res["key"] == "signature", res
    after = _doc(r)
    assert after["rules"]["gate.unsigned"]["signature"] == sig
    after["rules"]["gate.unsigned"]["signature"] = None
    assert after == before, "something else of the ledger changed"
    assert res["sha256"] == res["new_sha256"] == gp.ledger_sha256(r)
    assert _git(r, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert _git(r, "show", "--name-only", "--format=", "HEAD").splitlines() == [
        "shared/gate-prices.json"]
    assert res["commit"] == _git(r, "rev-parse", "HEAD")
    msg = _git(r, "log", "-1", "--format=%B")
    assert "gate.unsigned signature by" in msg and "via center" in msg and "CF-0721" in msg
    assert _git(r, "status", "--porcelain") == "A  other.txt"
    assert not _lock_file(r).exists()
    # the reader sees it, and the verdict logic reads it as before
    assert gp.signature_of("gate.unsigned", gp.ledger_path(r)) == sig


def test_a_stale_signature_is_replaced_by_a_new_one_at_or_above_the_price():
    r = _root()
    res = _sign(r, rule="gate.stale", price=3, date="2026-10-12")
    assert res["ok"] and res["written"], res
    assert _doc(r)["rules"]["gate.stale"]["signature"]["price"] == 3
    assert _doc(r)["rules"]["gate.stale"]["signature"]["date"] == "2026-10-12"


def test_decide_writes_only_the_decision():
    r = _root()
    before = _doc(r)
    res = _decide(r, mode="measure")
    assert res["ok"] and res["written"] and res["key"] == "decision", res
    dec = {"user": WHO["by"], "date": "2026-10-13", "mode": "measure", "task": "CF-0330",
           "note": "предупреждение", "via": "center"}
    after = _doc(r)
    assert after["rules"]["gate.unsigned"].pop("decision") == dec
    assert after == before
    assert gp.decision_of("gate.unsigned", gp.ledger_path(r)) == dec
    assert "decide gate.unsigned" in _git(r, "log", "-1", "--format=%B")
    # a later decision replaces it
    res = _decide(r, mode="warn", task="CF-0721")
    assert res["ok"] and _doc(r)["rules"]["gate.unsigned"]["decision"]["mode"] == "warn"


# ------------------------------------------------------------------ who
def test_who_signs_is_a_human_through_the_center():
    r = _root()
    before = gp.ledger_path(r).read_bytes()
    for by, via, codes in (
            (None, "center", ["bad_who"]), ("", "center", ["bad_who"]),
            ("user", None, ["bad_who"]), ("a\nb", "center", ["bad_who"]),
            ("x" * 41, "center", ["bad_who"]),
            ("claude", "center", ["not_human"]), ("Claude Opus", "center", ["not_human"]),
            ("auto-dev worker", "center", ["not_human"]), ("orchestrator", "center", ["not_human"]),
            ("AI", "center", ["not_human"]), ("агент", "center", ["not_human"]),
            ("оркестратором", "center", ["not_human"]), ("cc-bot", "center", ["not_human"]),
            ("user", "cli", ["bad_via"]), ("user", "agent", ["bad_via"]),
            ("model", "auto", ["not_human", "bad_via"])):
        for res in (_sign(r, by=by, via=via), _decide(r, by=by, via=via)):
            assert _codes(res) == codes, (by, via, res)
            assert not res["written"] and res["block"] is None
    for by in ("user", "Kai", "Example Reviewer", "Brian"):
        assert _sign(r, by=by, dry_run=True)["ok"], by
    assert gp.ledger_path(r).read_bytes() == before


def test_a_note_and_a_date_are_required_in_shape():
    r = _root()
    assert _codes(_sign(r, note="   ")) == ["empty_note"]
    assert _codes(_decide(r, note=None)) == ["empty_note"]
    assert _codes(_sign(r, date="13.10.2026")) == ["bad_date"]


# ------------------------------------------------------------------ the row
def test_the_rows_that_may_not_be_signed():
    r = _root()
    before = gp.ledger_path(r).read_bytes()
    assert _codes(_sign(r, rule="no.such")) == ["no_such_rule"]
    assert _codes(_decide(r, rule="no.such")) == ["no_such_rule"]
    assert _codes(_sign(r, rule="score.some", price=5)) == ["not_signable"]
    assert _codes(_decide(r, rule="score.some")) == ["not_signable"]
    assert _codes(_sign(r, rule="gate.blind", price=0)) == ["not_measured"]
    assert _codes(_sign(r, price=1)) == ["below_measured"]
    for bad in (-1, "2", None, True, float("nan")):
        assert _codes(_sign(r, price=bad)) == ["bad_price"], bad
    assert _codes(_sign(r, rule="gate.covered", price=4)) == ["already_signed"]
    assert _codes(_decide(r, rule="gate.covered")) == ["already_signed"]
    assert _codes(_decide(r, mode="hard")) == ["bad_mode"]
    assert _codes(_decide(r, mode="enforce")) == ["bad_mode"]
    assert _codes(_decide(r, task="0330")) == ["bad_task"]
    assert _codes(_decide(r, task=None)) == ["bad_task"]
    assert gp.ledger_path(r).read_bytes() == before


def test_an_unreadable_or_missing_ledger_is_refused():
    r = _root(repo=False)
    gp.ledger_path(r).write_text("{not json")
    assert _codes(_sign(r, commit=False)) == ["ledger_unreadable"]
    gp.ledger_path(r).write_text("[]")
    assert _codes(_sign(r, commit=False)) == ["ledger_unreadable"]
    gp.ledger_path(r).unlink()
    assert _codes(_sign(r, commit=False, base_sha256=None)) == ["ledger_unreadable"]


# ------------------------------------------------------------------ batch, base, lock
def test_any_fresh_open_batch_refuses_and_a_stale_one_does_not():
    r = _root()
    before = gp.ledger_path(r).read_bytes()
    for ch in ("example-film", "example-tech", "rebuilds"):
        rows = [(r / "pipeline" / ch / "2026-10-13T1411Z", NOW, True)]
        for res in (_sign(r, open_rows=rows), _decide(r, open_rows=rows)):
            assert _codes(res) == ["batch_open"], res
            assert "is open" in res["refusals"][0]["line"]
    assert gp.ledger_path(r).read_bytes() == before
    stale = [(r / "pipeline" / "example-film" / "2026-10-01T1000Z", NOW, False)]
    assert _sign(r, open_rows=stale)["written"]


def test_a_real_open_batch_in_the_root_refuses():
    """Without `open_rows` the writer asks runlog.open_batches of the root."""
    r = _root()
    d = r / "pipeline" / "example-film" / "2026-10-13T1411Z"
    d.mkdir(parents=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (d / "RUN_EVENTS.jsonl").write_text(json.dumps(
        {"ts": ts, "event": "batch-start", "batch": d.name}) + "\n")
    args = {**WHO, "base_sha256": gp.ledger_sha256(r), "root": r}
    res = gp.sign("gate.unsigned", 2, "n", args.pop("by"), args.pop("via"), dry_run=True, **args)
    assert _codes(res) == ["batch_open"], res


def test_a_ledger_changed_since_the_caller_read_it_is_refused():
    r = _root()
    before = gp.ledger_path(r).read_bytes()
    assert _codes(_sign(r, base_sha256="0" * 64)) == ["check_changed"]
    assert _codes(_decide(r, base_sha256=None)) == ["check_changed"]
    assert gp.ledger_path(r).read_bytes() == before


def test_a_held_lock_refuses_and_write_ledger_takes_the_same_lock():
    r = _root()
    before = gp.ledger_path(r).read_bytes()
    with gp.ledger_lock(gp.ledger_path(r)):
        assert _lock_file(r).exists()
        res = _sign(r, lock_wait=0.3)
        assert _codes(res) == ["locked"] and not res["written"], res
        try:
            with gp.ledger_lock(gp.ledger_path(r), wait=0.1):
                raise AssertionError("a second holder got the ledger lock")
        except gp._list_write().Locked:
            pass
    assert gp.ledger_path(r).read_bytes() == before and not _lock_file(r).exists()
    src = inspect.getsource(gp.write_ledger)
    assert "with ledger_lock(p):" in src, "write_ledger no longer takes the ledger lock"


# ------------------------------------------------------------------ modes of writing
def test_dry_run_commit_false_and_not_repo():
    r = _root()
    head, before = _git(r, "rev-parse", "HEAD"), gp.ledger_path(r).read_bytes()
    res = _sign(r, dry_run=True)
    assert res["ok"] and not res["written"] and res["dry_run"] and res["new_sha256"], res
    assert gp.ledger_path(r).read_bytes() == before and _git(r, "rev-parse", "HEAD") == head
    res = _sign(r, commit=False)
    assert res["ok"] and res["written"] and res["commit"] is None, res
    assert _git(r, "rev-parse", "HEAD") == head and _doc(r)["rules"]["gate.unsigned"]["signature"]
    assert not list((r / "shared").glob("*tmp*"))
    r2 = _root(repo=False)
    assert _codes(_sign(r2)) == ["not_repo"]
    assert _sign(r2, commit=False)["written"]


# ------------------------------------------------------------------ the source guard
WRITES = tuple(
    rx for key in ("signature", "decision") for rx in (
        re.compile(r'"%s"\s*:\s*([^,}\n]+)' % key),
        re.compile(r'\[\s*"%s"\s*\]\s*=(?!=)\s*([^\n]+)' % key),
        re.compile(r'setdefault\(\s*"%s"\s*,\s*([^)\n]+)' % key),
        re.compile(r'[(,]\s*%s\s*=(?!=)\s*([^,)\n]+)' % key)))


def test_only_sign_and_decide_write_a_signature_or_a_decision():
    """CF-0320 with the CF-0721 exception: outside `_write_block` the module
    sets a signature / decision only as None, and `_write_block` is called by
    `sign` and `decide` alone - on the user's action in the center."""
    src = (ROOT / "shared" / "runlog" / "gate_price.py").read_text(encoding="utf-8")
    body = inspect.getsource(gp._write_block)
    assert src.count(body) == 1
    assert re.search(r"row\[key\]\s*=\s*out\[\"block\"\]", body), "the write moved"
    outside = src.replace(body, "")
    # `price()` hands the reader the blocks it read (`"signature": sig`) - a
    # reading, not a write to the ledger; nowhere else
    reading = inspect.getsource(gp.price)
    assert '"signature": sig' in reading and '"decision": dec' in reading
    outside = outside.replace(reading, "")
    bad = [m.group(0) for rx in WRITES for m in rx.finditer(outside)
           if m.group(1).strip() != "None"]
    assert not bad, f"something in gate_price.py other than sign/decide writes a block: {bad}"
    callers = [name for name, fn in inspect.getmembers(gp, inspect.isfunction)
               if fn.__module__ == gp.__name__ and name != "_write_block"
               and "_write_block(" in inspect.getsource(fn)]
    assert sorted(callers) == ["decide", "sign"], callers
    assert outside.count("_write_block(") == 2
    assert '_write_block("signature"' in inspect.getsource(gp.sign)
    assert '_write_block("decision"' in inspect.getsource(gp.decide)


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
