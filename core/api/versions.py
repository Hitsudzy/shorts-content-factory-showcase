"""CC-0030: versions and the agents - one read-only view of what the factory
says about its own checkout (`GET /api/versions`).

Every fact is the factory's, read through its own functions, none of the
API's own on top:

* the agents and the modules against the lock: `shared/agents_lock.py`
  `status` and `module_status` (CF-0479, CF-0651) - pin, the sha it resolves
  to, HEAD, branch, the modified tracked files, ok / why; a module's build
  stamp (`build_stamp`: what `frontend/dist` was built from, read from the
  file `sync` wrote - nothing is executed);
* `scripts/agents status` itself, run as the user runs it, its lines kept
  verbatim (only the factory root's prefix is cut) with the exit code: the
  lines the rows above have no field for - a broken link of `links.root`
  (`DIFF shared/inserts/... -> ...: its target is missing`), ignored paths
  not linked yet - are said as the CLI says them, never hidden. A line's
  `mark` is its first word, the CLI's own `ok` / `DIFF` / `WARN`;
* the factory's version: `runlog.readme_version` (README's first heading,
  what every run header carries) and `runlog.repo_state` of the root (HEAD,
  branch, `main`'s sha, the modified code files - records left out as
  `batch-start` leaves them), `runlog.root_branch_ok` (the root may carry a
  batch: `main` or `release/*`); CC-0119 (CF-0716): `runlog.release_tag` - the
  greatest release tag `vN(.N)*` reachable from the branch `main` (not from
  HEAD: any checkout answers the same), None when there is none - and
  `agents_lock.versions_in_work` - the `release/<v>` branches a live worktree
  of the root's repo has checked out (a prunable one left out), in version
  order;
* the center: `factory.center_version` (`frontend/package.json` `version`,
  whether `dist/index.html` is there) and the module row of the lock.

Both `scripts/agents status` and `status()` walk every agent repo with git
(about two seconds on the factory), so the answer is kept `TTL_S` per root,
one check at a time (a second request waits for the first and takes its
answer); `?fresh=true` checks again. `checked_at` is when the kept answer
was made. No absolute path leaves: the factory root's, the working copy's
and this checkout's prefixes are cut, the home directory is `~`, any other
absolute path is `.../<its last part>`.
"""
import sys
import threading
import time
from pathlib import Path

from . import API_VERSION, child, factory, paths
from .settings import CODE

TTL_S = 30.0
CLI_TIMEOUT_S = 120
AGENTS_CLI = "scripts/agents"
MARKS = ("ok", "DIFF", "WARN")
STAMP_KEYS = ("rev", "sha", "contract", "contract_sha256", "built_by")

_KEPT = {}
_LOCK = threading.Lock()
_ROOT_LOCKS = {}


# -------------------------------------------------------------------- no absolute path
# the API's one cutter (`api/paths.py`, CC-0097)
_ABS = paths.ABS
_prefixes = paths.prefixes
_scrub = paths.scrub


# ------------------------------------------------------------------------ the CLI
def run_status(root):
    """`scripts/agents status --root <root>` as the user runs it, started
    (`child.start`, bounded by CLI_TIMEOUT_S): a run whose output `cli_result`
    reads. A seam of the tests. Its git reads take no optional lock (CC-0098,
    `factory.git_env`): `git status` does not rewrite the factory's
    `.git/index`."""
    return child.start([sys.executable, str(CODE / AGENTS_CLI), "status", "--root", str(root)],
                       timeout=CLI_TIMEOUT_S, env=factory.git_env())


def cli_result(proc):
    """{exit_code, lines, stderr, error} of the started CLI. A run that did not
    answer is already ended by `child` (the center signals nothing itself)."""
    try:
        out, err = proc.communicate(timeout=CLI_TIMEOUT_S)
    except child.Timeout:
        return {"exit_code": None, "lines": [], "stderr": None,
                "error": f"`{AGENTS_CLI} status` did not answer in {CLI_TIMEOUT_S} s"}
    except OSError as e:
        return {"exit_code": None, "lines": [], "stderr": None,
                "error": f"`{AGENTS_CLI} status` did not start ({e})"}
    return {"exit_code": proc.returncode, "lines": [ln for ln in (out or "").splitlines() if ln],
            "stderr": (err or "").strip() or None, "error": None}


def _line(text):
    words = text.split()
    mark = words[0] if words and words[0] in MARKS else None
    return {"text": text, "mark": mark, "of": "root", "subject": None,
            "_path": words[1] if mark and len(words) > 1 else None}


# ------------------------------------------------------------------------ the check
def _rows(al, root):
    """(agents, modules, error) of the lock; LockError is the answer's error."""
    try:
        agents = al.status(root)
        modules = al.module_status(root)
    except al.LockError as e:
        return [], [], str(e)
    return agents, modules, None


def _pair(rows, lines, of):
    """The CLI's line of each row: the first line not yet taken whose second
    word is the row's path (the CLI prints `<mark> <path> ...`)."""
    for r in rows:
        r["line"], r["mark"] = None, None
        for ln in lines:
            if ln["of"] == "root" and ln["_path"] == r["path"]:
                ln["of"], ln["subject"] = of, r[of]
                r["line"], r["mark"] = ln["text"], ln["mark"]
                break


def _agent(r):
    keep = ("agent", "path", "rev", "sha", "head", "branch", "dirty", "ok", "why")
    return {k: r.get(k) for k in keep}


def _module(al, root, r):
    keep = ("module", "path", "rev", "sha", "head", "branch", "dirty", "built", "api", "ok",
            "why")
    out = {k: r.get(k) for k in keep}
    stamp = al.build_stamp(root, r["path"])
    out["build"] = {k: stamp.get(k) for k in STAMP_KEYS} if stamp is not None else None
    return out


def _factory(al, root):
    rl = factory.runlog()
    st = rl.repo_state(rl.ROOT_REPO, root)
    return {"version": rl.readme_version(root), "git": bool(st.get("git")),
            "commit": st.get("head"), "branch": st.get("branch"), "main": st.get("main"),
            "dirty": st.get("dirty"), "branch_ok": bool(rl.root_branch_ok(st.get("branch"))),
            # CC-0119 (CF-0716): the factory's own answers, none of the API's
            "release_tag": rl.release_tag(root),
            "versions_in_work": list(al.versions_in_work(root))}


def _center(root, dist):
    c = factory.center_version(dist)
    d = Path(dist).resolve()
    rel = None
    for base in (Path(root).resolve(), CODE.resolve()):
        if d.is_relative_to(base):
            rel = d.relative_to(base).as_posix()
            break
    return {"version": c.get("version"), "built": bool(c.get("built")),
            "built_at": c.get("built_at"), "dist": rel}


def check(root, dist):
    """One check, now: the CLI started first, the factory's rows read while it
    runs, the two paired."""
    root = Path(root)
    checked = time.time()
    al = factory.agents_lock()
    try:
        proc = run_status(root)
    except OSError as e:
        proc, cli = None, {"exit_code": None, "lines": [], "stderr": None,
                           "error": f"`{AGENTS_CLI} status` did not start ({e})"}
    with factory.git_reads():                   # CC-0098: the index is not rewritten
        agents, modules, err = _rows(al, root)
        fac = _factory(al, root)
        mods = [dict(_module(al, root, r)) for r in modules]
    if proc is not None:
        cli = cli_result(proc)
    lines = [_line(t) for t in cli["lines"]]
    _pair(agents, lines, "agent")
    _pair(modules, lines, "module")
    for ln in lines:
        del ln["_path"]
    ans = {
        "checked_at": factory.utc_iso(checked), "cached": False, "ttl_s": TTL_S,
        "api": API_VERSION,
        "factory": fac,
        "lock": {"path": al.LOCK_NAME, "error": err},
        "agents": [dict(_agent(r), line=r["line"], mark=r["mark"]) for r in agents],
        "modules": [dict(m, line=r["line"], mark=r["mark"]) for m, r in zip(mods, modules)],
        "status": {"command": f"{AGENTS_CLI} status", "exit_code": cli["exit_code"],
                   "ok": cli["exit_code"] == 0, "lines": lines, "stderr": cli["stderr"],
                   "error": cli["error"]},
        "center": _center(root, dist),
    }
    return _scrub(ans, _prefixes(root))


def versions(root, dist, fresh=False, now=None):
    """The kept check of `root` when younger than TTL_S (and not `fresh`), else
    a new one; one check of a root at a time."""
    key = str(Path(root).absolute())
    asked = time.monotonic() if now is None else now
    with _LOCK:
        lock = _ROOT_LOCKS.setdefault(key, threading.Lock())
    with lock:
        with _LOCK:
            got = _KEPT.get(key)
        t = time.monotonic() if now is None else now
        if got is not None and (got[0] >= asked or (not fresh and t - got[0] < TTL_S)):
            return dict(got[1], cached=True)
        ans = check(root, dist)
        with _LOCK:
            _KEPT[key] = (time.monotonic() if now is None else now, ans)
        return ans


def forget():
    """Drop the kept checks (tests)."""
    with _LOCK:
        _KEPT.clear()
