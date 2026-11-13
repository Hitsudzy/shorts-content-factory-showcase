#!/usr/bin/env python3
"""CF-0479: the agents are libraries of the root, pinned in `agents.lock.json`.

The user's decision of 2026-10-02 (backlog grill, Q16): the code of a version
stays off `main` until its release, for every version. The model is the one of
`package.json`: the root is the consumer, the five agent repos under
`agents/<name>` are its libraries, and the root holds the pins. `main` of the
root pins release tags of the agents (`v1.4`), so work on an agent's own `main`
never reaches the user's batch. A version is built in a root worktree on branch
`release/<version>` (`.worktrees/release-<version>/`), whose lock pins the
agents' branch or sha under development.

This module is the one reader and writer of the lock - scripts
(`scripts/agents`), the tests and `runlog batch-start` all go through it - and
the checkout tool (the analogue of `npm install`):

  sync    put `<root>/agents/<name>` on the lock's revision. In the working copy
          (the checkout whose `.git` is a directory) that is a checkout of the pin
          in the agent's own repo; in a root worktree it is a `git worktree add`
          of the working copy's agent repo, so no history is copied. A tag or sha
          pin is checked out detached (the agent's `main` stays free for a version
          worktree to check out); a branch pin is checked out as the branch, so a
          worker's commits land on it - unless another worktree already holds
          the branch (a second root worktree such as `.worktrees/cc-api`,
          CF-0651): then the branch's sha, detached, moved on each sync. Refused - never forced - when the agent's
          tree has modified or staged tracked files, or when moving would orphan
          a commit no branch or tag holds, or when the pin tracks a path the
          checkout holds ignored (a venv, the pool: `--no-overwrite-ignore`,
          CF-0584). In a worktree it also links the ignored things the code
          needs from the working copy (`links` in the lock: the footage pool,
          `.env`, venvs, real batches, ...) - absolute symlinks, created only
          where git ignores the path as the file a symlink is to git (a
          `.venv/` pattern does not cover it) and nothing exists yet. The
          working copy links nothing to itself. CF-0705: and it removes the
          links it made that now lead nowhere because their file left the
          working copy (a meme dropped in the center) - only such a symlink,
          never a file or a target, never in the working factory; a link loop
          is left for `status` to name. `--dry-run` prints them.
  status  where the checkout differs from the lock (exit 1 when it does): also a
          `links` path that git tracks or that is a broken or self-pointing
          symlink (CF-0584).
  pin     set an agent's rev in the lock (checked to resolve first) and rewrite
          the README's pin table from the lock in the same action (CF-0702).
  readme  rewrite the pin table of the README (`<!-- agents-lock -->` markers)
          from the lock; `--check` only says whether it differs (exit 1).
  versions  the `release/<v>` branches that have a worktree, by version
          (`versions_in_work`, CF-0716 - the command center's /api/versions);
          `--json` -> {"versions_in_work": [...]}.
  api-check  whether the live command-center API runs the code of DIR (CF-0841):
          `GET <url>/api/version` (default http://127.0.0.1:8790) - its `api`
          against `API_VERSION` of `DIR/api/__init__.py`, its `factory.commit`
          against `git rev-parse HEAD` of DIR. Exit 0 - the same; 1 - the live
          API is behind (the line names the restart, outside a batch only);
          3 - no answer; 4 - an answer that is not a version (401, not JSON).
          The one command here that goes to the network - `status` never does,
          it runs in tests and in release trees.

CF-0651: `modules` of the lock are pinned like the agents but are no part of a
batch - the command center (`frontend`, its own repo example/command-center).
`main` of the root pins a tag of the center, `release/<v>` the center's `main`.
`sync` checks a module out as it does an agent and then builds it (`npm ci &&
npm run build` -> `<module>/dist`), stamping into `dist/` the commit and the
sha256 of the API contract (`api/openapi.json` of the root) it was built under;
it rebuilds only when either moved. No Node on PATH is a problem of the
module, named, after the agents are done. `status` prints a module's rows as
`ok`/`WARN` - not built, behind its pin, built under another contract - and
`no API` while the root has no contract yet; a WARN never changes the exit
code (`--strict` makes it), because `runlog batch-start` and a driver's check
vouch for the agents a batch runs on, and the center is not one of them.

Stdlib only, like shared/runlog: runlog imports this file by path.
"""
import argparse
import ast
import errno
import fnmatch
import glob
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

LOCK_NAME = "agents.lock.json"
FACTORY_ROOT_ENV = "FACTORY_ROOT"
GIT_TIMEOUT_S = 120
# Never linked even when a pattern matches them: caches of the working copy's
# own interpreter and Finder, which a checkout rebuilds or does not need.
LINK_SKIP_PARTS = {"__pycache__", ".DS_Store", ".pytest_cache", ".git"}
# CF-0651: how a module of the lock is built - the npm steps run in its checkout
MODULE_BUILDS = {"npm": [["ci"], ["run", "build"]]}
MODULE_TOOLS = {"npm": ("node", "npm")}
BUILD_DIR = "dist"
BUILD_STAMP = ".factory-build.json"     # in <module>/dist: what the build was made from
BUILD_TIMEOUT_S = 900
DEFAULT_CONTRACT = "api/openapi.json"
TOOL_PATH = None                        # PATH to find node/npm on; None - the process's
# CF-0841: the live command-center API (launchd com.example-film.cc-api)
CC_API_URL_DEFAULT = "http://127.0.0.1:8790"
API_MAIN = "api/__main__.py"             # its LABEL is the launchd job's (read, not copied)
API_CHECK_TIMEOUT_S = 10
API_INIT = "api/__init__.py"
API_CHECK_SAME, API_CHECK_BEHIND, API_CHECK_NO_ANSWER, API_CHECK_BAD_ANSWER = 0, 1, 3, 4

__all__ = ["LOCK_NAME", "LockError", "factory_root", "lock_path", "load", "save", "entries",
           "module_entries", "contract_sha", "build_stamp", "module_status", "agent_links", "root_links", "resolve", "is_repo", "working_copy", "dirty",
           "bad_links", "dead_links", "tracked_links", "status", "sync", "pin",
           "readme_pins_table", "write_readme_pins", "code_api_version", "cc_api_label", "api_check",
           "api_check_line", "main"]


class LockError(Exception):
    """The lock is missing, unreadable or names something that does not exist."""


def factory_root():
    env = os.environ.get(FACTORY_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def lock_path(root):
    return Path(root) / LOCK_NAME


# --------------------------------------------------------------------- the lock

def load(root, required=True):
    """The lock of `root` as a dict, validated; None when it is missing and not
    `required`. Every agent entry has a relative `path` (default
    `agents/<name>`) and a non-empty `rev`."""
    p = lock_path(root)
    if not p.is_file():
        if required:
            raise LockError(f"no {LOCK_NAME} in {root}")
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LockError(f"{p}: unreadable ({e})")
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, dict) or not agents:
        raise LockError(f"{p}: no `agents` object")
    for name, ent in agents.items():
        if not isinstance(ent, dict) or not isinstance(ent.get("rev"), str) or not ent["rev"].strip():
            raise LockError(f"{p}: agent {name!r} has no `rev`")
        rel = ent.setdefault("path", f"agents/{name}")
        if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise LockError(f"{p}: agent {name!r} has a path outside the root: {rel!r}")
    modules = data.setdefault("modules", {})
    if not isinstance(modules, dict):
        raise LockError(f"{p}: `modules` is not an object")
    for name, ent in modules.items():
        if name in agents:
            raise LockError(f"{p}: {name!r} is both an agent and a module")
        if not isinstance(ent, dict) or not isinstance(ent.get("rev"), str) or not ent["rev"].strip():
            raise LockError(f"{p}: module {name!r} has no `rev`")
        for key, default in (("path", name), ("contract", DEFAULT_CONTRACT)):
            rel = ent.setdefault(key, default)
            if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise LockError(f"{p}: module {name!r} has a {key} outside the root: {rel!r}")
        if ent.setdefault("build", "npm") not in MODULE_BUILDS:
            raise LockError(f"{p}: module {name!r}: unknown `build` {ent['build']!r} "
                            f"(known: {', '.join(sorted(MODULE_BUILDS))})")
    links = data.setdefault("links", {})
    if not isinstance(links, dict):
        raise LockError(f"{p}: `links` is not an object")
    return data


def save(root, data):
    p = lock_path(root)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def entries(lock):
    """[(name, relative path, rev)] in name order."""
    return [(n, e["path"], e["rev"]) for n, e in sorted(lock["agents"].items())]


def module_entries(lock):
    """CF-0651: [(name, relative path, rev, entry)] of `modules`, in name order."""
    return [(n, e["path"], e["rev"], e) for n, e in sorted((lock.get("modules") or {}).items())]


def agent_links(lock, name):
    """Link patterns of one agent: the `*` list plus its own."""
    a = (lock.get("links") or {}).get("agents") or {}
    return list(a.get("*") or []) + list(a.get(name) or [])


def root_links(lock):
    return list((lock.get("links") or {}).get("root") or [])


# ------------------------------------------------------------------------- git

def _git_read():
    """shared/runlog/git_read.py (CF-0717): a git read runs with optional locks
    off - `status` beside a batch's commit does not take `.git/index.lock`.
    Loaded by path: this module is imported with only shared/ on sys.path."""
    mod = sys.modules.get("git_read")
    if mod is None:
        import importlib.util                                   # noqa: PLC0415
        path = Path(__file__).resolve().parent / "runlog" / "git_read.py"
        spec = importlib.util.spec_from_file_location("git_read", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod = sys.modules.setdefault("git_read", mod)
    return mod


def _git(d, *args, timeout=GIT_TIMEOUT_S, input_=None):
    try:
        return _git_read().run(["-C", str(d), *args], capture_output=True, text=True,
                               timeout=timeout, input=input_)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 128, "", str(e))


def _out(d, *args, timeout=GIT_TIMEOUT_S):
    cp = _git(d, *args, timeout=timeout)
    return cp.stdout.strip() if cp.returncode == 0 else None


def _err(cp):
    lines = (cp.stderr or cp.stdout or "git failed").strip().splitlines()
    return lines[-1] if lines else "git failed"


def is_repo(d):
    """A git repo of its own at d: `.git` is a directory (a clone) or a file (a
    worktree). A plain directory would otherwise answer with its parent's repo."""
    return os.path.lexists(Path(d) / ".git")


def resolve(repo, rev):
    """The commit sha `rev` names in the repo at `repo`, or None."""
    if not is_repo(repo):
        return None
    return _out(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}", timeout=10)


def _is_branch(repo, rev):
    return _out(repo, "rev-parse", "--verify", "-q", f"refs/heads/{rev}", timeout=10) is not None


def _head(d):
    return _out(d, "rev-parse", "HEAD", timeout=10)


def _branch(d):
    return _out(d, "symbolic-ref", "--short", "-q", "HEAD", timeout=10)


def _common_dir(d):
    v = _out(d, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=10)
    return Path(v).resolve() if v else None


def _branch_holder(repo, branch, dst):
    """The path of another worktree of `repo` that has `branch` checked out, or
    None. CF-0651: a second root worktree (`.worktrees/cc-api` beside
    `.worktrees/release-<v>`) pins the agents to the same `main` - git lets one
    worktree hold a branch, so the second gets the branch's sha detached."""
    cp = _git(repo, "worktree", "list", "--porcelain", timeout=30)
    if cp.returncode != 0:
        return None
    me = os.path.realpath(str(dst))
    path = None
    for line in cp.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path and os.path.realpath(path) != me:
            return path
    return None


def working_copy(root):
    """The working copy `root` belongs to: root itself when it is the main
    checkout (or no git repo), else the checkout whose `.git` holds the
    worktree."""
    root = Path(root).resolve()
    if not (root / ".git").is_file():
        return root
    cd = _common_dir(root)
    return cd.parent if cd is not None and cd.name == ".git" else root


WORKING_BRANCH = "main"
VERSION_BRANCH_PREFIX = "release/"


def _version_key(version):
    """Version order of "2.4" / "2.10" / "2.3.1": numbers compare as numbers;
    a part that is no number sorts after them, as text."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p)
                 for p in re.split(r"[.\-]", version))


def versions_in_work(root=None):
    """CF-0716: the version branches in work - `release/<v>` branches that a
    worktree of the root's repo has checked out - sorted by version:
    ["release/2.4"]; [] when none (or `root` is no git repo, or git fails).

    Read from `git worktree list --porcelain` of the root's repo, so any of its
    checkouts answers the same. A worktree git marks `prunable` (its directory
    is gone) is no work; a `release/*` branch without a worktree is not in
    work either. A git read with optional locks off (CF-0717)."""
    root = Path(root if root is not None else factory_root())
    if not is_repo(root):
        return []
    cp = _git(root, "worktree", "list", "--porcelain", timeout=30)
    if cp.returncode != 0:
        return []
    found = set()
    for block in cp.stdout.split("\n\n"):
        lines = block.splitlines()
        if any(ln == "prunable" or ln.startswith("prunable ") for ln in lines):
            continue
        for ln in lines:
            ref = ln[len("branch refs/heads/"):] if ln.startswith("branch refs/heads/") else None
            if ref and ref.startswith(VERSION_BRANCH_PREFIX) and len(ref) > len(VERSION_BRANCH_PREFIX):
                found.add(ref)
    return sorted(found, key=lambda b: _version_key(b[len(VERSION_BRANCH_PREFIX):]))


def is_working_factory(root=None):
    """CF-0677: `root` is the working factory - the main checkout (not a
    worktree) on branch `main` - or not. -> (bool, reason in Russian, "" when
    True). The command center's API writes only here (CC-0058); a development
    copy (`.worktrees/release-<v>`, `cc-api`) writes only with the developer's
    `CC_API_WRITES=dev`. The branch is read as `runlog.repo_state` reads it
    for `batch-start` (`symbolic-ref --short -q HEAD`, CF-0398/0400); a detached
    HEAD is no working factory - the production is always on `main`. A dirty
    tree is `batch-start`'s business, not this rule's."""
    root = Path(root if root is not None else factory_root()).resolve()
    if not is_repo(root) or _head(root) is None:
        return False, f"не git-репозиторий ({root})"
    if working_copy(root) != root:
        return False, f"это рабочая копия разработки ({root}), а не рабочая фабрика"
    branch = _branch(root)
    if not branch:
        return False, f"HEAD отделён ({(_head(root) or '?')[:12]})"
    if branch != WORKING_BRANCH:
        return False, f"основной чекаут не на {WORKING_BRANCH} ({branch})"
    return True, ""


def dirty(d):
    """Modified or staged tracked files of the repo at d ([] when clean), None
    when `git status` failed. Untracked files never count."""
    cp = _git(d, "status", "--porcelain", "--untracked-files=no", timeout=30)
    if cp.returncode != 0:
        return None
    out = []
    for line in cp.stdout.splitlines():
        if len(line) >= 4:
            out.append(line[3:].split(" -> ")[-1].strip().strip('"'))
    return out


def _reachable(d, sha):
    """True when a branch, tag or remote ref holds the commit."""
    v = _out(d, "for-each-ref", "--count=1", "--contains", sha, "refs/heads", "refs/tags",
             "refs/remotes", timeout=30)
    return bool(v)


# ---------------------------------------------------------------------- status

def bad_links(base, patterns):
    """[(relative path, target, why)] of the symlinks among the matches of
    `patterns` under `base` that lead nowhere - a missing target or a loop (a
    link to its own path, CF-0584). Paths that do not exist are not bad."""
    base = Path(base)
    out, seen = [], set()
    for pat in patterns:
        for m in sorted(glob.glob(os.path.join(glob.escape(str(base)), pat), recursive=True)):
            if m in seen or not os.path.islink(m):
                continue
            seen.add(m)
            rel = Path(m).relative_to(base)
            if LINK_SKIP_PARTS & set(rel.parts):
                continue
            try:
                os.stat(m)
                continue
            except OSError as e:
                why = ("points at itself (a link loop)" if e.errno == errno.ELOOP
                       else "its target is missing")
            try:
                target = os.readlink(m)
            except OSError:
                target = "?"
            out.append((rel.as_posix(), target, why))
    return out


def tracked_links(repo, patterns):
    """The paths git tracks at `repo` that match `patterns` of `links` - things
    a checkout must hold ignored (a committed `.venv` symlink is what wiped the
    working copy's venvs at the v1.8 release, CF-0584). None when git failed."""
    if not patterns:
        return []
    cp = _git(repo, "ls-files", "-z", "--", *patterns, timeout=30)
    if cp.returncode != 0:
        return None
    return sorted({p for p in cp.stdout.split("\0") if p
                   and any(fnmatch.fnmatchcase(p, pat) for pat in patterns)})


def status(root=None):
    """[{agent, path, rev, sha, head, branch, dirty, ok, why}] for every agent of
    the lock of `root`. `ok` means HEAD is the pinned commit and no tracked file
    is modified or staged - what a batch needs. Raises LockError without a lock."""
    root = Path(root).resolve() if root else factory_root()
    lock = load(root)
    wc = working_copy(root)
    rows = []
    for name, rel, rev in entries(lock):
        dst = root / rel
        src = dst if is_repo(dst) else wc / rel
        row = {"agent": name, "path": rel, "rev": rev, "sha": resolve(src, rev), "head": None,
               "branch": None, "dirty": [], "ok": False, "why": None}
        if not is_repo(dst):
            row["why"] = "not checked out"
        elif row["sha"] is None:
            row["why"] = f"{rev!r} is not a revision of this repo (git fetch --tags?)"
        else:
            row.update(head=_head(dst), branch=_branch(dst), dirty=dirty(dst))
            if row["head"] != row["sha"]:
                at = row["branch"] or "detached"
                row["why"] = f"HEAD {str(row['head'])[:12]} ({at}) is not {rev} {row['sha'][:12]}"
            elif row["dirty"] is None:
                row["why"] = "`git status` failed, the tree cannot be vouched for"
            elif row["dirty"]:
                shown = ", ".join(row["dirty"][:5]) + (" ..." if len(row["dirty"]) > 5 else "")
                row["why"] = f"{len(row['dirty'])} uncommitted tracked file(s) ({shown})"
            else:
                pats = agent_links(lock, name)
                tracked = tracked_links(dst, pats)
                bad = bad_links(dst, pats)
                if tracked:
                    row["why"] = (f"git tracks {', '.join(tracked[:5])}, a path of `links` the "
                                  f"checkout holds ignored - a committed link? `git rm --cached` "
                                  f"it in the agent and write it into .gitignore without a "
                                  f"trailing slash (CF-0584)")
                elif bad:
                    row["why"] = "broken link(s): " + "; ".join(
                        f"{p} -> {t} {w}" for p, t, w in bad[:5])
                else:
                    row["ok"] = True
        rows.append(row)
    return rows


# --------------------------------------------------------------------- modules

def contract_sha(root, contract=DEFAULT_CONTRACT):
    """sha256 of the root's API contract, None when the root has none yet."""
    try:
        return hashlib.sha256((Path(root) / contract).read_bytes()).hexdigest()
    except OSError:
        return None


def build_stamp(root, rel):
    """What `<root>/<rel>/dist` was built from (the stamp sync writes), or None."""
    try:
        data = json.loads((Path(root) / rel / BUILD_DIR / BUILD_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _build_reason(root, rel, ent, head):
    """Why the module's build is out of date (a string), or None when it is not."""
    stamp = build_stamp(root, rel)
    if stamp is None:
        return "not built"
    if stamp.get("sha") != head:
        return f"built from {str(stamp.get('sha'))[:12]}, not HEAD {str(head)[:12]}"
    if stamp.get("contract_sha256") != contract_sha(root, ent["contract"]):
        return f"built under another {ent['contract']} than the root's"
    return None


def module_status(root=None):
    """CF-0651: [{module, path, rev, sha, head, branch, dirty, built, api, ok, why}]
    for every module of the lock. `ok` - on the pin, clean, built from HEAD
    under the root's contract; `api` False when the root has no contract yet
    (that is no fault). Advisory: the CLI prints a WARN, not a DIFF."""
    root = Path(root).resolve() if root else factory_root()
    lock = load(root)
    wc = working_copy(root)
    rows = []
    for name, rel, rev, ent in module_entries(lock):
        dst = root / rel
        src = dst if is_repo(dst) else wc / rel
        row = {"module": name, "path": rel, "rev": rev, "sha": resolve(src, rev), "head": None,
               "branch": None, "dirty": [], "built": False,
               "api": contract_sha(root, ent["contract"]) is not None, "ok": False, "why": None}
        if not is_repo(dst):
            row["why"] = "not checked out (scripts/agents sync)"
        elif row["sha"] is None:
            row["why"] = f"{rev!r} is not a revision of this repo (git fetch --tags?)"
        else:
            row.update(head=_head(dst), branch=_branch(dst), dirty=dirty(dst))
            reason = _build_reason(root, rel, ent, row["head"])
            row["built"] = reason is None
            if row["head"] != row["sha"]:
                at = row["branch"] or "detached"
                row["why"] = (f"HEAD {str(row['head'])[:12]} ({at}) is not {rev} "
                              f"{row['sha'][:12]} (scripts/agents sync)")
            elif row["dirty"]:
                row["why"] = f"{len(row['dirty'])} uncommitted tracked file(s)"
            elif row["dirty"] is None:
                row["why"] = "`git status` failed, the tree cannot be vouched for"
            elif reason:
                row["why"] = reason + " (scripts/agents sync builds it)"
            else:
                row["ok"] = True
        rows.append(row)
    return rows


def _tool(name):
    return shutil.which(name, path=TOOL_PATH) if TOOL_PATH is not None else shutil.which(name)


def _build(root, rel, ent, dry_run):
    """Build the checked-out module when its stamp is out of date. -> (actions,
    problems without the `rel: ` prefix)."""
    dst = root / rel
    head = _head(dst)
    reason = _build_reason(root, rel, ent, head)
    if reason is None:
        return [], []
    steps = MODULE_BUILDS[ent["build"]]
    tools = MODULE_TOOLS[ent["build"]]
    act = f"build {dst} ({reason}): " + " && ".join(" ".join([tools[-1], *s]) for s in steps)
    if dry_run:
        return [act], []
    found = {t: _tool(t) for t in tools}
    missing = [t for t, v in found.items() if not v]
    if missing:
        return [], [f"not built - {', '.join(missing)} not found on PATH: install Node.js "
                    f"(the version `engines` of {rel}/package.json asks for) and run "
                    f"`scripts/agents sync` again; the agents are synced, only the center "
                    f"is not built"]
    env = dict(os.environ)
    if TOOL_PATH is not None:
        env["PATH"] = TOOL_PATH + os.pathsep + env.get("PATH", "")
    for s in steps:
        cmd = [found[tools[-1]], *s]
        try:
            cp = subprocess.run(cmd, cwd=str(dst), capture_output=True, text=True, env=env,
                                timeout=BUILD_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as e:
            return [], [f"`{tools[-1]} {' '.join(s)}` failed: {e}"]
        if cp.returncode != 0:
            tail = " | ".join((cp.stderr or cp.stdout or "").strip().splitlines()[-4:])
            return [], [f"`{tools[-1]} {' '.join(s)}` failed (exit {cp.returncode}): {tail}"]
    out = dst / BUILD_DIR
    if not out.is_dir():
        return [], [f"the build made no {BUILD_DIR}/"]
    stamp = {"module": rel, "rev": ent["rev"], "sha": head, "contract": ent["contract"],
             "contract_sha256": contract_sha(root, ent["contract"]),
             "built_by": "scripts/agents sync (CF-0651)"}
    (out / BUILD_STAMP).write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return [act], []


# ------------------------------------------------------------------------ sync

def _place(dst, src, rev, sha, in_wc, dry_run):
    """Move an existing checkout at dst onto the pin. -> (actions, problems)."""
    if not is_repo(dst):
        return [], [f"{dst}: exists but is not a git repo - move it away first"]
    if not in_wc and _common_dir(dst) != _common_dir(src):
        return [], [f"{dst}: is not a worktree of {src} - move it away first"]
    d = dirty(dst)
    if d is None:
        return [], [f"{dst}: `git status` failed - not touched"]
    if d:
        shown = ", ".join(d[:5]) + (" ..." if len(d) > 5 else "")
        return [], [f"{dst}: {len(d)} uncommitted tracked file(s) ({shown}) - commit or move "
                    f"them first; sync never overwrites work"]
    branch = rev if _is_branch(dst, rev) else None
    if branch and _branch(dst) != branch and _branch_holder(dst, branch, dst):
        branch = None                     # CF-0651: held by another worktree - its sha, detached
    head, cur = _head(dst), _branch(dst)
    if head == sha and cur == branch:
        return [], []
    if cur is None and head != sha and not _reachable(dst, head):
        return [], [f"{dst}: HEAD {str(head)[:12]} is a commit no branch or tag holds - "
                    f"leaving it would lose it; put a branch on it first"]
    # CF-0584: git silently overwrites ignored files on a checkout by default -
    # a pin that tracks `.venv` replaced the working copy's venv with that link
    args = ["checkout", "-q", "--no-overwrite-ignore"] + ([branch] if branch
                                                         else ["--detach", sha])
    act = f"git -C {dst} {' '.join(args)}"
    if dry_run:
        return [act], []
    cp = _git(dst, *args)
    if cp.returncode != 0:
        lines = [x.strip() for x in (cp.stderr or cp.stdout or "").splitlines()
                 if x.strip() and x.strip() != "Aborting"]
        why = "; ".join(lines[:4]) or "git failed"
        if "untracked" in why or "ignored" in why:
            why += (f" - {rev} tracks a path this checkout holds ignored (a venv, the pool?); "
                    f"nothing was overwritten: untrack it in the agent (CF-0584)")
        return [], [f"{dst}: {act} failed: {why}"]
    return [act], []


def _link(src_base, dst_base, patterns, dry_run):
    """Symlink every match of `patterns` under src_base to the same relative
    path under dst_base, where git ignores that path in dst_base and nothing
    exists there yet (a broken symlink is replaced). -> (actions, problems).

    CF-0584: nothing is linked when both bases are one directory (the working
    copy itself) - the link would point at its own path. And a symlink is a
    file to git whatever it points at: a path ignored only as a directory
    (`.venv/`) would show its link as an untracked file that `git add -A`
    commits - such a path is not linked, it is a problem naming the fix."""
    src_base, dst_base = Path(src_base), Path(dst_base)
    if src_base.resolve() == dst_base.resolve():
        return [], []
    cand = []
    for pat in patterns:
        for m in sorted(src_base.glob(pat)):
            rel = m.relative_to(src_base)
            if LINK_SKIP_PARTS & set(rel.parts):
                continue
            if not os.path.exists(m):
                continue                  # CF-0705: a dead link of the working copy is not lent on
            t = dst_base / rel
            if t.is_symlink():
                if t.exists() or os.readlink(t) == str(m):
                    continue
            elif t.exists():
                continue
            cand.append((rel.as_posix(), m, t))
    if not cand:
        return [], []
    # asked without a slash - as git will see the link; a directory is also
    # asked with its slash, only to name the pattern that does not cover a link
    asked = [c[0] for c in cand] + [c[0] + "/" for c in cand if c[1].is_dir()]
    cp = _git(dst_base, "check-ignore", "--stdin", input_="\n".join(asked) + "\n", timeout=60)
    if cp.returncode not in (0, 1):
        return [], [f"{dst_base}: git check-ignore failed: {_err(cp)}"]
    ignored = set(cp.stdout.splitlines())
    acts, probs = [], []
    for rel, m, t in cand:
        if rel not in ignored:
            if rel + "/" in ignored:
                probs.append(f"{t}: not linked - git ignores {rel} only as a directory "
                             f"(`{rel}/`), a link there is an untracked file `git add -A` "
                             f"commits; write `{rel}` without the slash into .gitignore "
                             f"(CF-0584)")
            continue
        acts.append(f"link {t} -> {m}")
        if dry_run:
            continue
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            if t.is_symlink():
                t.unlink()
            os.symlink(str(m), str(t))
        except OSError as e:
            acts.pop()
            probs.append(f"{t}: link failed ({e})")
    return acts, probs


def dead_links(src_base, dst_base, patterns):
    """CF-0705: [(relative path, target)] of the links `sync` made under
    dst_base that now lead nowhere because their file left the working copy
    (src_base) - a meme the user dropped in the center, a batch archived.

    Only a symlink (never a file, a directory or the target) that matches
    `patterns`, whose target is exactly `src_base/<its path>` (what `_link`
    writes) and gone without a trace (not even a link there), and that lives
    in dst_base itself - not reached through a directory link into the working
    copy. A loop (a link to its own path, CF-0584) never qualifies: `status`
    keeps naming it. Nothing when both bases are one directory."""
    src_base, dst_base = Path(src_base), Path(dst_base)
    real_dst = dst_base.resolve()
    if src_base.resolve() == real_dst:
        return []
    srcs = {str(src_base), str(src_base.resolve())}
    out, seen = [], set()
    for pat in patterns:
        for m in sorted(glob.glob(os.path.join(glob.escape(str(dst_base)), pat), recursive=True)):
            if m in seen or not os.path.islink(m):
                continue
            seen.add(m)
            rel = Path(m).relative_to(dst_base)
            if LINK_SKIP_PARTS & set(rel.parts):
                continue
            try:
                os.stat(m)
                continue                                  # leads somewhere
            except OSError as e:
                if e.errno != errno.ENOENT:
                    continue                              # a loop and the like: status names it
            try:
                target = os.readlink(m)
            except OSError:
                continue
            if not any(target == os.path.join(s, rel.as_posix()) for s in srcs):
                continue                                  # not a link sync made
            if os.path.lexists(target):
                continue
            parent = Path(os.path.realpath(os.path.dirname(m)))
            if parent != real_dst and real_dst not in parent.parents:
                continue                                  # reached through a directory link
            out.append((rel.as_posix(), target))
    return out


def _prune(src_base, dst_base, patterns, dry_run):
    """CF-0705: remove the dead links of `dead_links` -> (actions, problems)."""
    acts, probs = [], []
    for rel, target in dead_links(src_base, dst_base, patterns):
        t = Path(dst_base) / rel
        acts.append(f"unlink {t} (its target {target} is gone)")
        if dry_run:
            continue
        try:
            if os.path.islink(t):                         # checked again just before
                os.unlink(t)
        except OSError as e:
            acts.pop()
            probs.append(f"{t}: unlink failed ({e})")
    return acts, probs


def _checkout(root, wc, in_wc, rel, rev, dry_run):
    """Put `<root>/<rel>` on `rev` (an agent or a module). -> (actions, problems
    without the `rel: ` prefix, sha or None)."""
    dst, src = root / rel, wc / rel
    if not is_repo(src):
        return [], [f"no git repo at {src} - clone it there first"], None
    sha = resolve(src, rev)
    if sha is None:
        return [], [f"{rev!r} is not a revision of {src} (git fetch --tags?)"], None
    if in_wc or os.path.lexists(dst):
        a, p = _place(dst, src, rev, sha, in_wc, dry_run)
        return a, p, sha
    branch = rev if _is_branch(src, rev) else None
    if branch and _branch_holder(src, branch, dst):
        branch = None                     # CF-0651: held by another worktree - its sha, detached
    args = ["worktree", "add", "-q"] + ([str(dst), branch] if branch
                                         else ["--detach", str(dst), sha])
    act = f"git -C {src} {' '.join(args)}"
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        cp = _git(src, *args)
        if cp.returncode != 0:
            return [], [f"{act} failed: {_err(cp)}"], sha
    return [act], [], sha


def sync(root=None, dry_run=False):
    """Bring `<root>/agents/*` to the lock. -> (actions, problems); nothing is
    forced, a problem leaves that agent as it was and the rest go on. The links
    are made whatever an agent's problem (CF-0651): the root's first, then each
    agent's that is checked out."""
    root = Path(root).resolve() if root else factory_root()
    lock = load(root)
    wc = working_copy(root)
    in_wc = wc == root
    # CF-0705: dead links are removed only in a development copy, never in the
    # working factory (belt and braces: in_wc already covers it)
    prune = not in_wc and not is_working_factory(root)[0]
    actions, problems = [], []
    if not in_wc:
        a, p = _link(wc, root, root_links(lock), dry_run)
        actions += a
        problems += p
    if prune:
        a, p = _prune(wc, root, root_links(lock), dry_run)
        actions += a
        problems += p
    for name, rel, rev in entries(lock):
        a, p, _ = _checkout(root, wc, in_wc, rel, rev, dry_run)
        actions += a
        problems += [f"{rel}: {x}" for x in p]
        if not in_wc and is_repo(root / rel):
            a, p = _link(wc / rel, root / rel, agent_links(lock, name), dry_run)
            actions += a
            problems += p
            if prune:
                a, p = _prune(wc / rel, root / rel, agent_links(lock, name), dry_run)
                actions += a
                problems += p
    for name, rel, rev, ent in module_entries(lock):      # CF-0651: after every agent
        a, p, _ = _checkout(root, wc, in_wc, rel, rev, dry_run)
        actions += a
        problems += [f"{rel}: {x}" for x in p]
        if p:
            continue
        if not is_repo(root / rel):                     # a dry run: the checkout is only planned
            actions.append(f"build {root / rel} (after the checkout)")
            continue
        a, p = _build(root, rel, ent, dry_run)
        actions += a
        problems += [f"{rel}: {x}" for x in p]
    return actions, problems


# ------------------------------------------------------------------------- pin

def pin(root, name, rev, path=None):
    """Set `rev` for agent `name` in the lock of `root` (a new agent needs
    `path`, default `agents/<name>`). The rev must resolve in the agent's repo
    of the working copy. -> the sha it resolves to."""
    root = Path(root).resolve()
    lock = load(root)
    if name in lock["modules"]:                           # CF-0651: a module, e.g. frontend
        ent = lock["modules"][name]
        if path:
            ent["path"] = path
        sha = resolve(working_copy(root) / ent["path"], rev)
        if sha is None:
            raise LockError(f"{rev!r} is not a revision of {working_copy(root) / ent['path']}")
        ent["rev"] = rev
        save(root, lock)
        write_readme_pins(root)
        return sha
    ent = lock["agents"].get(name)
    if ent is None:
        ent = lock["agents"][name] = {"path": path or f"agents/{name}", "rev": rev}
    elif path:
        ent["path"] = path
    repo = working_copy(root) / ent["path"]
    sha = resolve(repo, rev)
    if sha is None:
        raise LockError(f"{rev!r} is not a revision of {repo}")
    ent["rev"] = rev
    lock["agents"] = dict(sorted(lock["agents"].items()))
    save(root, lock)
    write_readme_pins(root)
    return sha


# ------------------------------------------------------------- README pins

README_PINS = re.compile(r"(<!-- agents-lock:begin -->\n)(.*?)(<!-- agents-lock:end -->)", re.S)


def readme_pins_table(lock):
    """The README's pin table for `lock`: the agents in name order, then the
    modules (CF-0651) - the rows `tests/test_readme_layout.py` reads back."""
    rows = [(n, rev) for n, _, rev in entries(lock)]
    rows += [(n, e["rev"]) for n, e in sorted((lock.get("modules") or {}).items())]
    return "| agent | pin |\n|---|---|\n" + "".join(f"| `{n}` | `{r}` |\n" for n, r in rows)


def write_readme_pins(root, check=False):
    """CF-0702: rewrite the table between the `agents-lock` markers of
    `root/README.md` from the lock. The release ritual moves the pins to tags with
    `pin`, and at 2.3 the lock went to `v2.3` while the README stayed on `main`
    (be071dc) - so `pin` calls this itself. -> True when the table changed (or,
    with `check`, would change), False when it already is the lock, None when
    the root has no README or the README no markers (a test tree)."""
    p = Path(root) / "README.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    m = README_PINS.search(text)
    if not m:
        return None
    table = readme_pins_table(load(root))
    if m.group(2) == table:
        return False
    if not check:
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text[:m.start(2)] + table + text[m.end(2):], encoding="utf-8")
        os.replace(tmp, p)
    return True


# ------------------------------------------------------------------------- CLI

# ------------------------------------------------------------ the live API

def _module_str(path, name):
    """The string constant `name = "..."` at the top of the Python file `path`,
    read as text (nothing imported - no FastAPI needed); None when there is
    none; OSError / SyntaxError / ValueError when the file is unreadable."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


def code_api_version(root):
    """`API_VERSION` of `<root>/api/__init__.py`; LockError when the tree has none."""
    path = Path(root) / API_INIT
    try:
        v = _module_str(path, "API_VERSION")
    except (OSError, SyntaxError, ValueError) as e:
        raise LockError(f"{path}: {e}") from e
    if v is None:
        raise LockError(f"{path}: no API_VERSION = \"...\"")
    return v


def cc_api_label(root):
    """The launchd label of the center's API - `LABEL` of `<root>/api/__main__.py`
    (`python3 -m api launchd`), or None."""
    try:
        return _module_str(Path(root) / API_MAIN, "LABEL")
    except (OSError, SyntaxError, ValueError):
        return None


def api_check(root=None, url=None, timeout=API_CHECK_TIMEOUT_S):
    """CF-0841: does the live API run the code of `root`? A dict: `code`
    (API_CHECK_*), `want` {api, commit} - the tree's, `live` {api, commit} or
    None, `process` {stale, started_at, commit_at_start, stale_paths} or None
    (CF-0848: the API's own word on its age, contract 0.70.0+; `stale` is None
    for an older API or an unknown answer), `why` - what differs or why there
    is no answer, `url`.

    CF-0848: `factory.commit` is read from git on every request, so an old
    process on an unchanged contract looked current; `stale` true (code changed
    between the process's start and HEAD) is now a DIFF of its own. The commit
    comparison stays - with `stale` known it says the API serves another tree."""
    root = Path(root) if root else factory_root()
    url = (url or CC_API_URL_DEFAULT).rstrip("/")
    want = {"api": code_api_version(root), "commit": _head(root)}
    out = {"url": url, "want": want, "live": None, "process": None, "why": None}
    try:
        # no proxy: the API is this machine's, a system proxy must not answer for it
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/api/version", timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        return {**out, "code": API_CHECK_BAD_ANSWER, "why": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        return {**out, "code": API_CHECK_NO_ANSWER, "why": str(reason)}
    try:
        data = json.loads(body.decode("utf-8"))
        live = {"api": data["api"], "commit": (data.get("factory") or {}).get("commit")}
    except (ValueError, UnicodeDecodeError, TypeError, KeyError, AttributeError) as e:
        return {**out, "code": API_CHECK_BAD_ANSWER, "why": f"not a /api/version answer: {e}"}
    out["live"] = live
    stale = data.get("stale")
    paths = data.get("stale_paths")
    out["process"] = proc = {
        "stale": stale if isinstance(stale, bool) else None,
        "field": "stale" in data,
        "started_at": data.get("started_at"),
        "commit_at_start": data.get("commit_at_start"),
        "stale_paths": [str(p) for p in paths] if isinstance(paths, list) else []}
    diffs = []
    if proc["stale"] is True:
        diffs.append(f"started {proc['started_at'] or '-'} at commit "
                     f"{(proc['commit_at_start'] or '-')[:12]}, code changed since: "
                     f"{', '.join(proc['stale_paths']) or '-'}")
    if live["api"] != want["api"]:
        diffs.append(f"api {live['api']} != {want['api']}")
    lc, wc = live["commit"] or "", want["commit"] or ""
    if not (lc and wc and (lc.startswith(wc) or wc.startswith(lc))):
        diffs.append(f"commit {lc[:12] or '-'} != {wc[:12] or '-'}")
    out["why"] = "; ".join(diffs) or None
    out["code"] = API_CHECK_BEHIND if diffs else API_CHECK_SAME
    return out


def api_check_line(res, root):
    """The one line `scripts/agents api-check` prints for `api_check`'s dict."""
    label = cc_api_label(root) or "<LABEL of api/__main__.py>"
    restart = (f"restart: launchctl kickstart -k gui/$(id -u)/{label} "
               f"(outside a batch only: `pgrep -f run_executor` empty)")
    w = res["want"]
    proc = res.get("process") or {}
    if res["code"] == API_CHECK_SAME:
        if proc.get("stale") is False:
            age = f"process current, started {proc.get('started_at') or '-'}"
        elif proc.get("field"):
            age = "process age not checked (stale is null)"
        else:
            age = "process age not checked (no stale field)"
        return (f"ok   live API {res['url']} = {root}: api {w['api']}, "
                f"commit {(w['commit'] or '-')[:12]}; {age}")
    if res["code"] == API_CHECK_BEHIND and proc.get("stale") is True:
        return (f"DIFF the live API runs stale code (живой API на старом коде): "
                f"{res['why']}; {restart}")
    if res["code"] == API_CHECK_BEHIND:
        return (f"DIFF the live API is behind {root} (живой API отстаёт): {res['why']}; "
                f"{restart}")
    if res["code"] == API_CHECK_NO_ANSWER:
        return (f"DOWN no live API at {res['url']} (живой API не отвечает): {res['why']}; "
                f"is {label} loaded? `launchctl print gui/$(id -u)/{label}`")
    return (f"BAD  {res['url']}/api/version answered, but not with a version "
            f"(ответ не версия): {res['why']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agents", description="CF-0479: the agents' checkout "
                                 "against agents.lock.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="put agents/* on the lock (and link ignored deps in a worktree)")
    s.add_argument("--root", default=None)
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("status", help="where the checkout differs from the lock (exit 1)")
    s.add_argument("--root", default=None)
    s.add_argument("--strict", action="store_true",
                   help="a module's WARN (the center not built, behind, another API) exits 1 too")
    s = sub.add_parser("pin", help="set an agent's rev in the lock")
    s.add_argument("agent")
    s.add_argument("rev")
    s.add_argument("--path", default=None)
    s.add_argument("--root", default=None)
    s = sub.add_parser("versions", help="the release/<v> branches that have a worktree (CF-0716)")
    s.add_argument("--root", default=None)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("api-check", help="does the live command-center API run this tree's "
                       "code - GET /api/version (CF-0841; exit 1 behind, 3 no answer)")
    s.add_argument("--root", default=None)
    s.add_argument("--url", default=None, help=f"the API (default {CC_API_URL_DEFAULT})")
    s.add_argument("--timeout", type=float, default=API_CHECK_TIMEOUT_S)
    s = sub.add_parser("readme", help="rewrite the README's pin table from the lock")
    s.add_argument("--root", default=None)
    s.add_argument("--check", action="store_true", help="only say whether it differs (exit 1)")
    ns = ap.parse_args(argv)
    root = Path(ns.root).resolve() if ns.root else factory_root()
    try:
        if ns.cmd == "sync":
            actions, problems = sync(root, dry_run=ns.dry_run)
            for a in actions:
                print(("would: " if ns.dry_run else "") + a)
            for p in problems:
                print(f"agents sync: {p}", file=sys.stderr)
            if not actions and not problems:
                print("agents sync: already on the lock")
            return 2 if problems else 0
        if ns.cmd == "status":
            rows = status(root)
            ok = all(r["ok"] for r in rows)
            for r in rows:
                mark = "ok  " if r["ok"] else "DIFF"
                at = r["branch"] or "detached"
                print(f"{mark} {r['path']:<28} {r['rev']:<12} "
                      f"{(r['head'] or '-')[:12]:<12} {at:<10} {r['why'] or ''}".rstrip())
            for r in module_status(root):
                if not r["ok"] and ns.strict:
                    ok = False
                at = r["branch"] or ("detached" if r["head"] else "-")
                note = r["why"] or ""
                if not r["api"]:
                    note = (note + "; " if note else "") + "no API (the root has no contract yet)"
                print(f"{'ok  ' if r['ok'] else 'WARN'} {r['path']:<28} {r['rev']:<12} "
                      f"{(r['head'] or '-')[:12]:<12} {at:<10} {note}".rstrip())
            wc = working_copy(root)
            dead = ({r for r, _ in dead_links(wc, root, root_links(load(root)))}
                    if wc != root else set())
            for rel, target, why in bad_links(root, root_links(load(root))):
                ok = False
                fix = "; scripts/agents sync removes it (CF-0705)" if rel in dead else ""
                print(f"DIFF {rel} -> {target}: {why} (CF-0584){fix}")
            if working_copy(root) != root:
                acts, probs = _link_preview(root)
                if acts:
                    print(f"DIFF {len(acts)} ignored path(s) not linked yet (scripts/agents sync)")
                for p in probs:
                    ok = False
                    print(f"DIFF {p}")
            return 0 if ok else 1
        if ns.cmd == "api-check":
            res = api_check(root, ns.url, timeout=ns.timeout)
            print(api_check_line(res, root),
                  file=sys.stdout if res["code"] in (API_CHECK_SAME, API_CHECK_BEHIND)
                  else sys.stderr)
            return res["code"]
        if ns.cmd == "versions":
            vs = versions_in_work(root)
            print(json.dumps({"versions_in_work": vs}) if ns.json else "\n".join(vs))
            return 0
        if ns.cmd == "readme":
            moved = write_readme_pins(root, check=ns.check)
            if moved is None:
                print(f"agents readme: {root / 'README.md'} has no agents-lock table", file=sys.stderr)
                return 2
            if ns.check:
                print("agents readme: the pin table " + ("differs from the lock" if moved
                                                         else "is the lock"))
                return 1 if moved else 0
            print("agents readme: " + ("pin table rewritten from the lock" if moved
                                       else "pin table already is the lock"))
            return 0
        sha = pin(root, ns.agent, ns.rev, path=ns.path)
        note = "" if write_readme_pins(root, check=True) is None else "; README pin table = the lock"
        print(f"{ns.agent}: {ns.rev} ({sha[:12]}) in {lock_path(root)}{note}; "
              f"run `scripts/agents sync`")
        return 0
    except LockError as e:
        print(f"agents {ns.cmd}: {e}", file=sys.stderr)
        return 2


def _link_preview(root):
    lock = load(root)
    wc = working_copy(root)
    acts, probs = _link(wc, root, root_links(lock), True)
    for name, rel, _ in entries(lock):
        if (root / rel).exists():
            a, p = _link(wc / rel, root / rel, agent_links(lock, name), True)
            acts += a
            probs += p
    return acts, probs


if __name__ == "__main__":
    sys.exit(main())
