#!/usr/bin/env python3
"""CF-0717: every git child of the factory's root code starts here, and a read
runs with GIT_OPTIONAL_LOCKS=0.

`git status` (and `diff`, `describe --dirty`, ...) refreshes the stat cache of
`.git/index` and to do so takes `.git/index.lock` - an "optional lock" (git(1),
GIT_OPTIONAL_LOCKS). A read that runs beside a batch, a stage commit or the
command center (`agents_lock.status`, `runlog.repo_state`, the stage code guard
CF-0713, ...) then races the writer for that lock, and the writer that loses
fails its commit. With the variable at 0 git does the read without the optional
lock and leaves the index as it found it; a write (commit, add, mv, checkout,
worktree add, ...) still takes every lock it needs - for a write the caller's
env goes through untouched.

    run(args, timeout=, env=None, **kw)
                                subprocess.run(["git", *args], ...) - env with
                                optional locks off when `args` is a read
    read_env(env=None)          `env` (os.environ by default) + GIT_OPTIONAL_LOCKS=0
    env_for(args, env=None)     read_env(env) for a read, `env` as given for a write
    is_read(args)               whether `args` (what follows "git") only reads

The command center's API reuses the same constant (`api/factory.GIT_READ_ENV`,
CC-0098). `tests/test_git_read.py` keeps new code from starting a git read
past this module.
"""
import os
import subprocess

GIT_READ_ENV = {"GIT_OPTIONAL_LOCKS": "0"}

#: Subcommands that only read the repository. A subcommand missing here is
#: treated as a write - it keeps the old behaviour, nothing is lost.
READ_SUBCOMMANDS = frozenset({
    "status", "rev-parse", "log", "show", "diff", "diff-index", "diff-tree",
    "diff-files", "ls-files", "ls-tree", "ls-remote", "describe", "for-each-ref",
    "cat-file", "merge-base", "rev-list", "show-ref", "check-ignore", "check-attr",
    "blame", "grep", "shortlog", "name-rev", "var", "count-objects", "symbolic-ref",
    "verify-commit", "whatchanged", "cherry",
})

#: Subcommands that read in one form and write in another: a read only when
#: one of these words follows the subcommand.
_READ_FORMS = {
    "worktree": {"list"},
    "branch": {"--show-current", "--list", "-l", "--contains", "-a", "-r", "-v", "-vv"},
    "config": {"--get", "--get-all", "--get-regexp", "--list", "-l"},
    "remote": {"-v", "get-url", "show"},
    "stash": {"list", "show"},
    "tag": {"-l", "--list", "--contains", "--points-at"},
}

#: Global options of git that take a value as the next word.
_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                      "--exec-path", "--config-env"}


def subcommand(args):
    """(subcommand, the words after it) of `args` - what follows "git" - with
    the global options (`-C <dir>`, `-c k=v`, `--no-pager`, ...) skipped;
    (None, []) when there is none."""
    args = [str(a) for a in args]
    i = 0
    while i < len(args):
        a = args[i]
        if a in _GLOBAL_WITH_VALUE:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return None, []


def is_read(args):
    """Whether git `args` only read the repository (`symbolic-ref` with a
    target, `config k v` and the like are writes)."""
    sub, rest = subcommand(args)
    if sub is None:
        return False
    if sub == "symbolic-ref":
        return len([a for a in rest if not a.startswith("-")]) <= 1
    if sub in READ_SUBCOMMANDS:
        return True
    forms = _READ_FORMS.get(sub)
    return bool(forms) and bool(rest) and rest[0] in forms


def read_env(env=None):
    """`env` (os.environ by default) for a git-reading child: optional locks
    off, everything else as the caller had it."""
    return dict(os.environ if env is None else env, **GIT_READ_ENV)


def env_for(args, env=None):
    """The env for a git child running `args`: `read_env(env)` for a read; for
    a write the caller's `env` untouched (None - the child inherits os.environ)."""
    return read_env(env) if is_read(args) else env


def run(args, *, timeout, env=None, **kw):
    """`subprocess.run(["git", *args], timeout=..., env=..., **kw)` - a read with
    optional locks off (see `env_for`). The ceiling is required (CF-0229: no
    root code waits on a child without one). `subprocess.run` is looked up at
    call time, so a test that swaps it sees these children too."""
    args = list(args)
    return subprocess.run(["git", *args], env=env_for(args, env), timeout=timeout, **kw)
