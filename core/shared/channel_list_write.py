#!/usr/bin/env python3
"""CF-0726: the checked writers of a channel's lists - one way to write
`channels/<id>/<list>.json` for the command center (its ask 16 of 2026-10-13)
and anyone else who edits a channel list by hand.

The lists are `shared/channel_data.LISTS`: `fact-sources`, `footage-origin`,
`affiliate`, `rights-holders`. Every checked write here goes the same way:

1. **who** - `by` and `via` (the CF-0720 shape: a short single-line string;
   both are required here - a checked write is always somebody's);
2. **the channel** - resolved through `channel_data.channel_id` (a former id
   is the same channel); an unknown one is refused;
3. **the schema** - the list's own validator (`errors`, given by the named
   writer: `fact_rule.validate_sources` and the AI-bot / attribution rules,
   `footage_licence.footage_origin_errors`, `affiliate.table_errors`); every problem is a refusal line;
4. **no batch of the channel is open** - `runlog.open_batches`, the fresh rows
   (what `runlog batch-active` counts) whose channel (`runlog.batch_channel`)
   is this one, or cannot be told (a rebuild): a running stage reads the list;
5. **the base** - `base_sha256` is the sha256 of the file as the caller read
   it (None: the caller saw no file). A file that changed since is refused
   (`check_changed`) - nobody's edit is overwritten unseen;
6. **the lock** - one exclusive `fcntl.flock` on `<root>/channels/.lists.lock`
   for every channel list of the root (`lock()`), so two checked writes never interleave. Not free within `lock_wait` seconds:
   `locked`. Steps 4 and 5 are checked again under the lock;
7. **the write** - with `commit=True` (the default) through the factory's
   committer `shared/runlog/git_commit.write_and_commit` (temp file +
   `os.replace`, one commit of exactly this file; a refused commit puts the
   file back - `commit_refused`); with `commit=False` a temp file and
   `os.replace` alone. A root that is not a git repository refuses a commit
   before anything is written (`not_repo`).

`dry_run=True` checks 1-5 and answers the same, nothing written and no lock
taken. A document that is byte for byte the file already there is `ok` with
`written: false` (nothing to write, nothing committed).

The answer is a dict, never an exception for a refusal:

    {"ok": bool, "written": bool, "dry_run": bool, "task": "CF-0726",
     "channel": id, "list": name, "path": "channels/<id>/<file>",
     "by": .., "via": .., "base_sha256": .., "sha256": <the file now, or None>,
     "new_sha256": <what would be / was written>, "commit": <sha or None>,
     "refusals": [{"code": .., "line": ..}, ...], "lines": [..]}

Refusal codes (`REFUSALS`): `bad_who`, `unknown_channel`, `unknown_list`,
`invalid`, `batch_open`, `check_changed`, `locked`, `not_repo`,
`commit_refused`, `write_failed`.

The named writers: `write_fact_sources`, `write_footage_origin` (here),
`affiliate.write_table` (shared/affiliate.py). Stdlib only; neighbours are loaded by path.
"""
import contextlib
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = "CF-0726"
LOCK_FILE = ".lists.lock"                 # under <root>/channels/ (gitignored)
LOCK_WAIT = 60.0                          # a commit's post-commit hook pushes - give it time
LOCK_POLL = 0.1
WHO_MAX = 40                              # pool_release.WHO_MAX

BAD_WHO, UNKNOWN_CHANNEL, UNKNOWN_LIST = "bad_who", "unknown_channel", "unknown_list"
INVALID, BATCH_OPEN, CHECK_CHANGED, LOCKED = "invalid", "batch_open", "check_changed", "locked"
NOT_REPO, COMMIT_REFUSED, WRITE_FAILED = "not_repo", "commit_refused", "write_failed"
REFUSALS = (BAD_WHO, UNKNOWN_CHANNEL, UNKNOWN_LIST, INVALID, BATCH_OPEN, CHECK_CHANGED, LOCKED,
            NOT_REPO, COMMIT_REFUSED, WRITE_FAILED)


def _by_path(name, path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def channel_data():
    return _by_path("_channel_data_for_list_write", HERE / "channel_data.py")


def git_commit():
    return _by_path("_git_commit_for_list_write", HERE / "runlog" / "git_commit.py")


def fact_rule():
    return _by_path("_fact_rule_for_list_write", HERE / "factrule" / "fact_rule.py")


def footage_licence():
    return _by_path("_footage_licence_for_list_write", HERE / "footage_licence.py")


def runlog():
    """`shared/runlog/runlog.py` - the module already imported as `runlog`
    when there is one (its `sibling()` finds its neighbours either way), else
    loaded by path under a name of its own (a `shared/` on sys.path makes
    `runlog` the package, not the module)."""
    mod = sys.modules.get("runlog")
    if mod is not None and hasattr(mod, "open_batches"):
        return mod
    return _by_path("_runlog_for_list_write", HERE / "runlog" / "runlog.py")


class Locked(Exception):
    """The channel lists' lock was not free in time."""


# ------------------------------------------------------------------ small parts
def refusal(code, line):
    return {"code": code, "line": line}


def who(value, what):
    """`by` / `via`: a short non-empty single-line string - else the line why
    (a str), never an exception."""
    if not isinstance(value, str) or not value.strip():
        return (f"{what}={value!r}: a checked write is somebody's - a short non-empty "
                f"string (e.g. by='user', via='center')")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        return f"{what}={value!r}: at most {WHO_MAX} characters on one line"
    return None


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_of(path):
    """The file's sha256, None when there is no file."""
    try:
        return sha256_bytes(Path(path).read_bytes())
    except FileNotFoundError:
        return None


def encode(doc):
    """The bytes a channel list is written as."""
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def root_of(root=None):
    return Path(root) if root else channel_data().find_root()


def list_path(channel, name, root=None):
    return channel_data().channel_list_path(channel, name, root_of(root))


def list_sha256(channel, name, root=None):
    """The `base_sha256` a caller passes back: the list's file as it is now
    (None when the channel has no such file)."""
    return sha256_of(list_path(channel, name, root))


def lock_path(root=None):
    return root_of(root) / channel_data().CHANNELS_SUBDIR / LOCK_FILE


@contextlib.contextmanager
def lock(root=None, wait=LOCK_WAIT):
    """The one exclusive lock of a root's channel lists. Raises `Locked` when
    it is not free within `wait` seconds. The lock file is removed while it is
    still held (and a waiter that locked a removed file tries again), so no
    file stays behind in `channels/` for git to see."""
    with file_lock(lock_path(root), wait, "the channel lists") as path:
        yield path


@contextlib.contextmanager
def file_lock(path, wait=LOCK_WAIT, what="the file"):
    """`lock()` on any lock file `path` (CF-0721: the gate-price ledger's own
    lock uses it too). Raises `Locked` naming `what` when it is not free within
    `wait` seconds; the file is removed while still held."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        raise
                    if time.monotonic() >= deadline:
                        raise Locked(f"{path}: another writer of {what} holds the "
                                     f"lock (not free in {wait:g} s) - nothing written") from None
                    time.sleep(LOCK_POLL)
            try:
                same = os.stat(path).st_ino == os.fstat(fd).st_ino
            except FileNotFoundError:
                same = False
        except BaseException:
            os.close(fd)
            raise
        if same:
            break
        os.close(fd)                     # the holder before us removed it: lock the new one
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"pid {os.getpid()} since "
                     f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n".encode())
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def open_batches_of(channel, root=None, now=None, open_rows=None):
    """The fresh open runs (`runlog.open_batches`, what `runlog batch-active`
    counts) whose channel is `channel` or cannot be told (a rebuild): [(dir,
    why)]. `open_rows`: the rows in hand (tests, a caller that already has
    them)."""
    rl = runlog()
    root = root_of(root)
    rows = open_rows if open_rows is not None else rl.open_batches(root, now=now)
    out = []
    for row in rows:
        d, _last, fresh = row[0], row[1], row[2]
        if not fresh:
            continue
        ch = rl.batch_channel(d, root)
        if ch is None or ch == channel:
            out.append((Path(d), getattr(row, "why", None)))
    return out


def _rel(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _write_plain(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{TASK}-tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ the writer
def write_list(channel, name, doc, *, base_sha256, by, via, errors=None, root=None,
               dry_run=False, commit=True, lock_wait=LOCK_WAIT, now=None, open_rows=None,
               message=None):
    """The checked write of the list `name` of `channel` (see the module's
    text). `errors(doc, channel_id, root)` -> [str]: the list's own schema
    rule. Returns the answer dict; a refusal is never raised."""
    cd = channel_data()
    root = root_of(root)
    out = {"ok": False, "written": False, "dry_run": bool(dry_run), "task": TASK,
           "channel": channel, "list": name, "path": None, "by": by, "via": via,
           "base_sha256": base_sha256, "sha256": None, "new_sha256": None, "commit": None,
           "refusals": [], "lines": []}
    refs = out["refusals"]
    for value, what in ((by, "by"), (via, "via")):
        why = who(value, what)
        if why:
            refs.append(refusal(BAD_WHO, why))
    if name not in cd.LISTS:
        refs.append(refusal(UNKNOWN_LIST, f"{name!r} is not a channel list "
                                          f"({sorted(cd.LISTS)})"))
        return out
    try:
        cid = cd.channel_id(channel, root)
    except cd.ChannelDataError as e:
        refs.append(refusal(UNKNOWN_CHANNEL, str(e)))
        return out
    out["channel"] = cid
    if refs:
        return out
    by, via = by.strip(), via.strip()
    out.update(by=by, via=via)
    path = cd.channel_list_path(cid, name, root)
    out["path"] = _rel(path, root)
    try:
        data = encode(doc)
    except (TypeError, ValueError) as e:
        refs.append(refusal(INVALID, f"{out['path']}: not a JSON document ({e})"))
        return out
    out["new_sha256"] = sha256_bytes(data)
    for line in (errors(doc, cid, root) if errors else []):
        refs.append(refusal(INVALID, str(line)))

    def gate():
        """Steps 4 and 5 - before the lock and again under it."""
        got = []
        for d, why in open_batches_of(cid, root, now=now, open_rows=open_rows):
            got.append(refusal(BATCH_OPEN, f"{_rel(d, root)} is open"
                                           + (f" ({why})" if why else "")
                                           + f" - {cid}'s lists are not written while a "
                                             f"batch of the channel runs"))
        out["sha256"] = sha256_of(path)
        if out["sha256"] != base_sha256:
            got.append(refusal(CHECK_CHANGED, f"{out['path']}: sha256 {out['sha256']} on disk, "
                                              f"{base_sha256} read by the caller - it changed "
                                              f"since; read it again"))
        return got

    refs.extend(gate())
    if not refs and commit and not dry_run and not git_commit().is_repo(root):
        refs.append(refusal(NOT_REPO, f"{root} is not a git repository - the list cannot be "
                                      f"committed (commit=False writes without a commit)"))
    if refs:
        return out
    if out["sha256"] == out["new_sha256"]:
        out.update(ok=True)
        out["lines"].append(f"{out['path']}: no change - nothing written ({TASK})")
        return out
    if dry_run:
        out.update(ok=True)
        out["lines"].append(f"{out['path']}: would be written by {by} via {via} - dry run, "
                            f"nothing written ({TASK})")
        return out
    try:
        with lock(root, wait=lock_wait):
            again = gate()
            if again:
                refs.extend(again)
                return out
            try:
                if commit:
                    gc = git_commit()
                    msg = message or (f"{name}: {cid} - written by {by} via {via} ({TASK})\n\n"
                                      f"shared/channel_list_write.py write_list {cid} {name}\n")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    out["commit"] = gc.write_and_commit(root, {path: data}, msg)
                else:
                    _write_plain(path, data)
            except Exception as e:                              # noqa: BLE001
                gc = git_commit()
                if isinstance(e, gc.CommitError):
                    refs.append(refusal(COMMIT_REFUSED, f"the commit was refused, the file put "
                                                        f"back as it was: {e} "
                                                        f"{' '.join(e.details)}".rstrip()))
                    return out
                if isinstance(e, OSError):
                    refs.append(refusal(WRITE_FAILED, f"{out['path']}: {type(e).__name__}: {e}"))
                    return out
                raise
    except Locked as e:
        refs.append(refusal(LOCKED, str(e)))
        return out
    out.update(ok=True, written=True, sha256=out["new_sha256"])
    out["lines"].append(f"{out['path']}: written by {by} via {via}"
                        + (f", committed {out['commit'][:12]}" if out["commit"] else "")
                        + f" ({TASK})")
    return out


# ------------------------------------------------------------------ fact-sources
def fact_sources_errors(doc, channel, root=None):
    """`fact_rule.validate_sources`, the AI-bot rule over the outlets and the
    channel's feeds (`channel_data.policy_errors_of`) and the outlets' AI
    output terms (`attribution_terms_errors`) - what the center shows as the
    list's errors (api/rights.py `fact_sources`)."""
    cd = channel_data()
    errs = [str(e) for e in fact_rule().validate_sources(doc)]
    if not isinstance(doc, dict):
        return errs
    try:
        feed_list = cd.feeds(channel, root_of(root))
    except cd.ChannelDataError as e:
        errs.append(str(e))
        feed_list = None
    errs += [str(e) for e in cd.policy_errors_of(channel, doc, feed_list)]
    errs += [str(e) for e in cd.attribution_terms_errors(doc)]
    return errs


def write_fact_sources(channel, doc, *, base_sha256, by, via, root=None, dry_run=False,
                       commit=True, lock_wait=LOCK_WAIT, now=None, open_rows=None):
    """The checked write of `channels/<id>/fact-sources.json`."""
    return write_list(channel, "fact-sources", doc, base_sha256=base_sha256, by=by, via=via,
                      errors=fact_sources_errors, root=root, dry_run=dry_run, commit=commit,
                      lock_wait=lock_wait, now=now, open_rows=open_rows)


# ------------------------------------------------------------------ footage-origin
def footage_origin_errors(doc, channel=None, root=None):
    """A footage-origin document with `footage_origins` (or `licences`) -
    `footage_licence.footage_origin_errors`, the whole rule. The film channel's
    shape (only `official_channels`, read by the hunter's scoring and the
    Analyst's footage list) - the shape those readers rely on: a list of
    objects, each with its `pattern`, and every channel of it a YouTube
    channel id."""
    fl = footage_licence()
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    if "footage_origins" in doc or "licences" in doc:
        return [str(e) for e in fl.footage_origin_errors(doc)]
    errs = []
    ocs = doc.get("official_channels")
    if not isinstance(ocs, list):
        return ["no `official_channels` list"]
    for i, entry in enumerate(ocs):
        if not isinstance(entry, dict):
            errs.append(f"official_channels[{i}]: not an object")
            continue
        ctx = f"official_channels[{i}] ({entry.get('pattern')})"
        if not isinstance(entry.get("pattern"), str) or not entry["pattern"].strip():
            errs.append(f"{ctx}: no `pattern`")
        chans = entry.get("channels", [])
        if not isinstance(chans, list):
            errs.append(f"{ctx}: `channels` is not a list")
            continue
        for j, ch in enumerate(chans):
            cid = ch.get("id") if isinstance(ch, dict) else None
            if not (isinstance(cid, str) and fl.CHANNEL_ID_RE.match(cid)):
                errs.append(f"{ctx}: channels[{j}].id {cid!r} is not a YouTube channel id")
    return errs


def write_footage_origin(channel, doc, *, base_sha256, by, via, root=None, dry_run=False,
                         commit=True, lock_wait=LOCK_WAIT, now=None, open_rows=None):
    """The checked write of `channels/<id>/footage-origin.json`."""
    return write_list(channel, "footage-origin", doc, base_sha256=base_sha256, by=by, via=via,
                      errors=footage_origin_errors, root=root, dry_run=dry_run, commit=commit,
                      lock_wait=lock_wait, now=now, open_rows=open_rows)
