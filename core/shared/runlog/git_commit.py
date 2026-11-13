#!/usr/bin/env python3
"""CF-0675: write a few files of the factory root and commit exactly those - one
commit, nothing else of the index or the tree swept in.

The shape is the command center's (CC-0006/CC-0008, `api/channels.py`
`_write_and_commit`): write each file through a temp name and `os.replace`,
`git add` + `git commit --only -- <paths>`, and on any failure put every file
back as it was and unstage it - a refused commit leaves the tree as it found it.
The first user here is the acceptance record (`acceptance.record_and_commit`,
`acceptance.commit_pending`); the center may call the same function.

CF-0847: a writer that has already written its files (the meme desk's
background jobs) takes `status` of its paths before the work and after, and
commits the ones that moved with `commit_paths` - the shape of the center's
`publish_stash.commit_paths` / `root_commit` (CC-0153), here for the factory.

The environment's `GIT_*` variables are dropped (a hook or a worktree of the
caller must not redirect the commit) and the prompt is off. The post-commit hook
(the push, CF-0502) runs inside `git commit`, hence the long timeout.
"""
import os
import subprocess
import sys
from pathlib import Path

GIT_TIMEOUT = 120


class CommitError(Exception):
    """git did not do what was asked; `details` carries its words."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = list(details or [])


def _git_read():
    """git_read.py beside this file (CF-0717); this module is also loaded by
    path (the center's `factory.git_commit`), its folder maybe not on sys.path."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)
    import git_read                                             # noqa: PLC0415
    return git_read


def git(root, *args, input=None, check=True, timeout=GIT_TIMEOUT):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    # CF-0717: the reads (status, rev-parse) with optional locks off; add/commit/reset as before
    cp = _git_read().run(["-C", str(root), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", input=input, env=env,
                         timeout=timeout)
    if check and cp.returncode != 0:
        raise CommitError(f"git {' '.join(args)}: exit {cp.returncode}",
                          [(cp.stderr or cp.stdout).strip()])
    return cp


def is_repo(root):
    try:
        cp = git(root, "rev-parse", "--is-inside-work-tree", check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return cp.returncode == 0 and cp.stdout.strip() == "true"


def rel(root, path):
    """`path` relative to `root`; a path outside the root is refused - the commit
    would have nothing to do with this repository."""
    root, p = Path(root).resolve(), Path(path)
    p = p.resolve() if p.is_absolute() else (root / p).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        raise CommitError(f"{p} is outside {root} - not a file of this repository") from None


def dirty(root, rels):
    """`git status --porcelain` lines of `rels` - changes git does not have yet."""
    cp = git(root, "status", "--porcelain", "--untracked-files=all", "--", *rels)
    return [line for line in cp.stdout.splitlines() if line.strip()]


def head(root):
    return git(root, "rev-parse", "HEAD").stdout.strip()


def write_and_commit(root, writes, message):
    """Write `{path: bytes}` and commit those files only, with `message`. The
    sha of the new commit. On a failed write or commit every file is put back as
    it was (a file that did not exist is removed) and unstaged, and the error is
    raised again."""
    root = Path(root)
    paths = {Path(p) if Path(p).is_absolute() else root / p: data for p, data in writes.items()}
    rels = [rel(root, p) for p in paths]
    if not is_repo(root):
        raise CommitError(f"{root} is not a git repository - nothing can be committed there")
    before = {p: (p.read_bytes() if p.is_file() else None) for p in paths}
    try:
        for p, data in paths.items():
            tmp = p.with_name(p.name + ".commit-tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        git(root, "add", "--", *rels)
        git(root, "commit", "-q", "-F", "-", "--only", "--", *rels, input=message)
    except BaseException:
        for p, data in before.items():
            if data is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(data)
        git(root, "reset", "-q", "--", *rels, check=False)
        raise
    return head(root)


def status(root, rels):
    """{path: XY} of `git status --porcelain -z --no-renames` over `rels`
    (untracked files one by one, ignored ones never) - git's word on what is
    changed there now (CF-0847; the center's `publish_stash._status`)."""
    cp = git(root, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all",
             "--", *rels)
    out = {}
    for rec in cp.stdout.split("\0"):
        if len(rec) > 3:
            out[rec[3:]] = rec[:2]
    return out


def commit_paths(root, rels, message):
    """Commit exactly `rels` (from the root, files already written) in one
    commit (CF-0847; the center's `publish_stash.commit_paths`): present files
    `git add`, gone ones `git rm --cached`, gitignored ones left out, then
    `git commit --only`. `(sha, committed rels)`, `(None, [])` when nothing is
    left to commit. On a refusal the paths are unstaged again (the files stay
    as they are) and CommitError goes up. Never `add -A`."""
    rels = sorted(set(rels))
    if not rels:
        return None, []
    ignored = set(git(root, "check-ignore", "--", *rels, check=False).stdout.splitlines())
    rels = [r for r in rels if r not in ignored]
    present = [r for r in rels if (Path(root) / r).exists()]
    gone = [r for r in rels if r not in present]
    if gone:
        known = set(git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", *gone,
                        check=False).stdout.splitlines())
        known |= set(git(root, "ls-files", "--", *gone, check=False).stdout.splitlines())
        gone = [r for r in gone if r in known]
    rels = sorted(present + gone)
    if not rels:
        return None, []
    try:
        if present:
            git(root, "add", "--", *present)
        if gone:
            git(root, "rm", "--cached", "-q", "--ignore-unmatch", "--", *gone)
        git(root, "commit", "-q", "-F", "-", "--only", "--", *rels, input=message)
    except CommitError:
        git(root, "reset", "-q", "--", *rels, check=False)
        raise
    return head(root), rels
