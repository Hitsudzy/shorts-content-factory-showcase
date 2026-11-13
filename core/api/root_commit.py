"""CC-0153 / CC-0156: a center write commits what it changed in the root, so
the production tree stays clean. Moved here from `api/publish.py` (CC-0153)
unchanged, so every writer of the API commits the same way:

    snap(root, scope)               git's word on `scope` before a write -
                                    {path: (XY, sha256 of the bytes | None)};
                                    None when the root is not a git work tree
    changed(root, scope, before)    what the write changed: changed in git's
                                    eyes now and not as it was before (a file
                                    already dirty counts only when its bytes
                                    moved - a stray hand edit stays out)
    commit(root, cid, action, rels, subject, body, done)
                                    one `git commit --only` of exactly `rels`
                                    (`git_commit.commit_paths`, the factory's
                                    git helper, CF-0847) with the `Cc-Channel` /
                                    `Cc-Action: <action>` trailers; git's
                                    refusal is 409 `refused` with the
                                    `commit_refused` line, nothing staged
    rels(root, files)               the files as paths from the root (outside
                                    ones left out) - a scope
    commit_changed(root, cid, action, scope, before, message, done)
                                    `changed` then `commit` - (None, []) when
                                    nothing changed (or no git work tree)

A write that raised commits nothing - the callers take `snap` before the write
and call `commit_changed` only after it returned. A root that is not a git
work tree commits nothing and the write proceeds. Never `git add -A`: only the
paths of the write's own scope, as git sees them, and of those only the ones
whose bytes moved.

`cid` None (a write of the factory's, not of one channel - the API Data): the `Cc-Action` trailer alone, no `Cc-Channel`.
"""
import hashlib
from pathlib import Path

from . import channels, factory, paths
from .batches import BatchFault

COMMIT_REFUSED = ("{done} в дереве фабрики, но git не принял коммит - файлы остались "
                  "изменёнными (см. подробности); посмотрите git status, прежде чем повторять.")


def snap(root, scope):
    """{path: (XY, sha256 of the bytes or None)} of what git calls changed
    under `scope` (`publish_stash._status`: untracked one by one, ignored
    never). None when the root is not a git work tree - nothing to commit to."""
    from . import publish_stash                                 # noqa: PLC0415
    if not factory.git_commit().is_repo(root):
        return None
    out = {}
    for rel, xy in publish_stash._status(root, list(scope)).items():
        p = Path(root) / rel
        out[rel] = (xy, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return out


def rels(root, files):
    """`files` (absolute, or from the root) as paths from the root, posix; a
    path outside the root is left out - the root's git has nothing of it."""
    base = Path(root).resolve()
    out = []
    for f in files:
        p = Path(f)
        p = p.resolve() if p.is_absolute() else (base / p).resolve()
        try:
            out.append(p.relative_to(base).as_posix())
        except ValueError:
            continue
    return out


def changed(root, scope, before):
    """The paths the write changed: changed in git's eyes now and not as they
    were before it (a file already dirty counts only when its bytes moved)."""
    if before is None:
        return []
    after = snap(root, scope) or {}
    return sorted(p for p, v in after.items() if before.get(p) != v)


def trailers(cid, action):
    """`Cc-Channel` / `Cc-Action` (`channels._trailers`); `Cc-Action` alone
    for a write that is not one channel's (`cid` None)."""
    if cid is None:
        return f"{channels.ACTION_TRAILER}: {action}"
    return channels._trailers(cid, action)


def commit(root, cid, action, rels, subject, body, done):
    """CC-0153: one commit of exactly `rels` (from the root) through
    `git_commit.commit_paths` (the factory's git helper, `git commit --only`;
    CC-0160: the same body as `publish_stash.commit_paths`), the message
    `subject`, `body`, the `Cc-Channel` / `Cc-Action` trailers - the idiom of the stash placement (CC-0122) and the card ruling
    (CC-0127). `(sha, committed)`; git's refusal is 409 `refused` with the
    commit_refused line (the write stays in the tree, nothing staged - `done`
    says what was written): the code is the contract's own, `commit_refused`
    is not a problem code and the contract stays as it is."""
    gc = factory.git_commit()
    message = f"{subject}\n\n{body}\n\n{trailers(cid, action)}\n"
    try:
        return gc.commit_paths(root, rels, message)
    except gc.CommitError as e:
        raise BatchFault(409, "refused", COMMIT_REFUSED.format(done=done),
                         paths.clean(["commit_refused", str(e), *e.details,
                                      "touched: " + ", ".join(sorted(rels))], root)) from e


def commit_changed(root, cid, action, scope, before, message, done):
    """What the write changed under `scope` since `before` (`snap`), committed
    (`commit`); `message` - `() -> (subject, body)`, asked only when there is
    something to commit. `(sha, committed)`, `(None, [])` when nothing moved."""
    touched = changed(root, scope, before)
    if not touched:
        return None, []
    subject, body = message()
    return commit(root, cid, action, touched, subject, body, done)
