"""CC-0003: what the API reads from the factory - only through the factory's
own functions, loaded by path from this checkout (as
`shared/factory_state.py` does), no logic of the API's own on top:

* the factory's version: `shared/runlog/runlog.py` `readme_version` (the line
  of README's first heading - what every run header carries) and `_git`
  (commit, dirty);
* the agents' pins: `shared/agents_lock.py` `status` (the rev of the lock,
  the sha it resolves to, HEAD, ok/why - what `scripts/agents status` prints);
* the questions to the user (CF-0652): `shared/needs_you.py` `questions`,
  `answer`, `resolve` - the journal `<factory root>/needs-you/questions.jsonl`;
* a path the API serves under the root (CC-0053): `contained` - a symlink
  out is taken only when the lock declares it (`agents_lock` `load`,
  `root_links`, `working_copy`, what `scripts/agents sync` links);
* a new channel (CC-0008): `shared/new_channel.py` `template`, `check` - the
  factory's template `shared/channel_template/` and its checks;
* may the API write here (CC-0058): `shared/agents_lock.py`
  `is_working_factory` (CF-0677) - the main checkout on `main`, kept a few
  seconds (`working_factory`);
* a check's line in Russian (CC-0054, CF-0657): `inserts/validate_inserts.py`
  `channel_config_findings`, `check_findings` - the reason code and the human
  line of each check's row in CHECK_REASONS_RU.

The center's version is the API's to read (it is not the factory's): the
`version` of `package.json` next to the built `dist/`, and whether the build
is there at all. An absent build is an answer, not an error.
"""
import contextlib
import fnmatch
import importlib.util
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from .settings import CODE

# ---------------------------------------------------------------- git reads (CC-0098)
#: The center reads the factory's git while a batch runs: `git status` (the
#: factory's `agents_lock.status`, `runlog._git`, `scripts/agents status`)
#: refreshes `.git/index` and takes `index.lock` unless optional locks are off
#: - the center would write into the factory's `.git`, and an index.lock held
#: at the wrong moment fails a commit of the batch. Every git read of the API
#: runs with GIT_OPTIONAL_LOCKS=0 (git(1): "no optional locks" - the index is
#: not rewritten; a commit still takes the locks it needs). CF-0717: the
#: factory's own door for that, `shared/runlog/git_read.py`, is the one source.
_GIT_READS = threading.Lock()
_git_reads = {"depth": 0, "saved": None}


def git_read():
    """`shared/runlog/git_read.py` (CF-0717): every git child of the factory."""
    return _mod("git_read", "shared/runlog/git_read.py")


def git_env(env=None):
    """`env` (os.environ by default) for a git-reading child: optional locks off."""
    return git_read().read_env(env)


@contextlib.contextmanager
def git_reads():
    """The factory's own functions that run git in this process (they pass no
    env, the child inherits os.environ): GIT_OPTIONAL_LOCKS=0 for the time of
    the read, as it was after (nested and concurrent reads counted - the last
    one out puts it back)."""
    key = "GIT_OPTIONAL_LOCKS"
    value = git_read().GIT_READ_ENV[key]
    with _GIT_READS:
        if _git_reads["depth"] == 0:
            _git_reads["saved"] = os.environ.get(key)
            os.environ[key] = value
        _git_reads["depth"] += 1
    try:
        yield
    finally:
        with _GIT_READS:
            _git_reads["depth"] -= 1
            if _git_reads["depth"] == 0:
                if _git_reads["saved"] is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = _git_reads["saved"]

_MODS = {}
# CC-0039: FastAPI runs the sync routes in a threadpool, so two first requests
# can reach `_mod` at once. Without the lock the second one found the module
# the first was still executing (it is in `sys.modules` from before
# `exec_module`, as a module must be while it runs) and failed on a name not
# yet defined - `module 'validate_inserts' has no attribute
# 'channel_config_errors'`. Reentrant: a module being loaded may itself reach
# `_mod`.
_MODS_LOCK = threading.RLock()


def _mod(name, rel):
    """A module of this checkout, loaded once by path.

    Thread-safe: one loader at a time, and a module is handed out (`_MODS`)
    only fully executed. An exec that fails leaves nothing behind - the name is
    taken out of `sys.modules` again (what was there before goes back) - and
    the error goes up; the next call loads it afresh."""
    m = _MODS.get(name)
    if m is not None:
        return m
    with _MODS_LOCK:
        m = _MODS.get(name)
        if m is not None:
            return m
        path = (CODE / rel).resolve()
        have = sys.modules.get(name)
        if have is not None and Path(getattr(have, "__file__", "") or "").resolve() == path:
            have = _finished(name, have)
            if have is not None:
                _MODS[name] = have
                return have
            have = sys.modules.get(name)
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[name] = m
        try:
            spec.loader.exec_module(m)
        except BaseException:
            if sys.modules.get(name) is m:
                if have is not None:
                    sys.modules[name] = have
                else:
                    del sys.modules[name]
            raise
        _MODS[name] = m
        return m


def _finished(name, have):
    """`have` once an import of it the import system is running in another
    thread is done (a factory module may `import runlog` the plain way while a
    route reaches `_mod("runlog")`); None if that import failed."""
    if not getattr(getattr(have, "__spec__", None), "_initializing", False):
        return have
    try:
        importlib.import_module(name)  # waits on the import system's lock of `name`
    except Exception:                                   # noqa: BLE001
        pass
    return have if sys.modules.get(name) is have else None


def runlog():
    return _mod("runlog", "shared/runlog/runlog.py")


def git_commit():
    """`shared/runlog/git_commit.py` (CF-0675): write a few files and commit
    exactly those - the channel edits' commit and the acceptance record's."""
    return _mod("git_commit", "shared/runlog/git_commit.py")


def agents_lock():
    return _mod("agents_lock", "shared/agents_lock.py")


def needs_you():
    return _mod("needs_you", "shared/needs_you.py")


# ---------------------------------------------------------------- CC-0058: writes only here
#: How long the answer of `is_working_factory` is kept: the branch of the
#: checkout can change under a running API (a `git checkout` by hand), so not
#: for the process's life - but a poll of `/api/health` every few seconds
#: should not run git each time.
WORKING_FACTORY_TTL_S = 5.0
_WF = {}
_WF_LOCK = threading.Lock()


def working_factory(root, now=None):
    """CC-0058: `agents_lock.is_working_factory(root)` (CF-0677) -> (bool,
    reason in Russian, "" when True), kept `WORKING_FACTORY_TTL_S` per root.
    The factory's rule, none of the API's own: the main checkout on `main`.
    A rule that fails to answer is a no (the API stays read-only)."""
    import time
    key = str(Path(root).absolute())
    t = time.monotonic() if now is None else now
    with _WF_LOCK:
        got = _WF.get(key)
        if got is not None and t - got[0] < WORKING_FACTORY_TTL_S:
            return got[1]
    try:
        with git_reads():
            ok, why = agents_lock().is_working_factory(root)
        ans = (bool(ok), "" if ok else str(why or "не рабочая фабрика"))
    except Exception as e:                      # noqa: BLE001 - fail closed, say why
        ans = (False, f"не удалось проверить, рабочая ли это фабрика ({type(e).__name__}: {e})")
    with _WF_LOCK:
        _WF[key] = (t, ans)
    return ans


def forget_working_factory():
    """Drop the kept answers (tests; a checkout switched on purpose)."""
    with _WF_LOCK:
        _WF.clear()


# ---------------------------------------------------------------- CC-0053: a path inside
# In a root worktree (`.worktrees/cc-api`, `.worktrees/release-<v>`) the real
# batches are not there: `scripts/agents sync` links `pipeline/<channel>` and
# `pipeline/rebuilds` to the working copy (`links.root` of `agents.lock.json`).
# A path the API serves is checked against the lock as `sync` reads it - the
# factory's `agents_lock.load` / `root_links` / `working_copy` - not a parse of
# the API's own.
_WC = {}
_WC_LOCK = threading.Lock()


def _working_copy(root):
    """`agents_lock.working_copy(root)`, kept per root (a git call; a checkout
    does not move to another working copy while the API runs)."""
    key = str(Path(root).absolute())
    with _WC_LOCK:
        if key not in _WC:
            _WC[key] = Path(agents_lock().working_copy(root)).resolve()
        return _WC[key]


def _matches(parts, pat):
    """`parts` (a path relative to the root) is a match of the glob `pat` as
    `Path.glob` takes it: one segment per `*` / `?` / `[...]`, `**` any number."""
    if not pat:
        return not parts
    if pat[0] == "**":
        return any(_matches(parts[i:], pat[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pat[0]) and _matches(parts[1:], pat[1:])


def declared_link(root, rel):
    """Is `<root>/<rel>` a link `scripts/agents sync` made: `rel` a match of a
    `links.root` pattern of the root's lock and the symlink's target the same
    path of the working copy (`root` is a worktree of it, not the copy itself)."""
    root = Path(root)
    link = root / rel
    if not link.is_symlink():
        return False
    al = agents_lock()
    try:
        lock = al.load(root, required=False)
    except al.LockError:
        return False
    parts = Path(rel).parts
    if not lock or not any(_matches(parts, Path(p).parts) for p in al.root_links(lock)):
        return False
    try:
        wc = _working_copy(root)
        if wc == root.resolve():
            return False
        return link.resolve() == (wc / rel).resolve()
    except (OSError, RuntimeError):
        return False


def contained(root, top, *parts):
    """`<root>/<top>/<parts...>` as a path under the resolved root (the rest
    not resolved: a linked `pipeline/<channel>` stays in the path), or None
    when it leads out. Every part is one name (no separator, no `..`). The
    base is where `<top>` resolves; a symlink on the way that resolves outside
    the base is taken only when it is a declared link (`declared_link`), and
    the base moves to its target - so `pipeline/<channel>` linked by `sync` is
    in, an undeclared symlink, one inside a batch pointing out, or `..` is not.
    Paths that do not exist yet are not refused here."""
    root = Path(root)
    names = [top, *parts]
    for n in names:
        if not isinstance(n, str) or n in ("", ".", "..") or "/" in n or "\\" in n \
                or "\0" in n:
            return None
    try:
        base = root.resolve()
        cur, rel = base, Path()
        for i, n in enumerate(names):
            cur, rel = cur / n, rel / n
            if cur.is_symlink():
                target = cur.resolve()
                if not target.is_relative_to(base):
                    if not declared_link(root, rel):
                        return None
                    base = target
            elif not cur.resolve().is_relative_to(base):
                return None
            if i == 0:
                base = cur.resolve()
    except (OSError, RuntimeError):
        return None
    return cur


# ---------------------------------------------------------------- CF-0652: questions
QUESTION_STATUSES = ("live", "open", "answered", "resolved", "all")


def questions(root, status="live", channel=None):
    """The questions of the factory's journal (`shared/needs_you.py`), oldest
    first; `live` - open and answered. `channel`: only that channel's (under
    its current id - needs_you resolves it)."""
    qs = needs_you().questions(root, status=status, channel=channel)
    return [dict(q, link=center_link(q.get("link"))) if isinstance(q, dict) and q.get("link")
            else q for q in qs]


def center_link(link):
    """CF-0735, CC-0035: a stored link of the retired console
    (127.0.0.1:8790/#anchor) or of the center before it moved (127.0.0.1:8791/
    <route>) as the center's route (`notify.center_link`, NOTIFY_CENTER_URL of the API's
    environment); any other link as it is."""
    return notify().center_link(link) if link else link


def _folded(text):
    """A text as the journal keeps it (`needs_you._clean` folds every run of
    white space into one space) - so an answer typed with a trailing space is
    still the suggestion."""
    return " ".join(str(text or "").split())


def answer_question(root, qid, text, by, via=None, accept=False, suggested_at=None):
    """(question, None) or (None, (http code, why[, code])): 404 no such
    question, 409 already resolved, 422 an empty answer.

    CC-0086 (CF-0703): `via` - where the answer came from (the center's routes
    pass `center`). `accepted_suggestion` is decided here on a fresh read of
    the question, never on the client's word: `accept` - the answer is the
    question's current suggestion (none: 409 `no_suggestion`; the client
    names the one it saw by `suggested_at` and the question has another now:
    409 `check_changed`, nothing written) and `needs_you.answer` takes the
    suggestion itself under its lock (the text left out); a text - accepted
    when it is the current suggestion, white space folded as the journal
    folds it."""
    ny = needs_you()
    q = ny.get(qid, root)
    if not q:
        return None, (404, f"no question {qid}")
    current = q.get("suggestion")
    if accept:
        if q.get("status") == "resolved":
            return None, (409, f"question {q['id']} is already resolved")
        if not current:
            return None, (409, f"question {q['id']} has no suggestion to accept", "no_suggestion")
        if suggested_at is not None and suggested_at != q.get("suggested_at"):
            return None, (409, f"the suggestion of {q['id']} changed since it was shown "
                               f"(shown {suggested_at}, now {q.get('suggested_at')}) - nothing "
                               f"written", "check_changed")
        text, accepted = None, True
    else:
        accepted = bool(current) and _folded(text) == current
    try:
        return ny.answer(qid, text, by=by, root=root, via=via,
                         accepted_suggestion=accepted), None
    except ny.QuestionError as e:
        return None, (409 if "resolved" in str(e) or "no suggestion" in str(e) else 422, str(e))


def resolve_question(root, qid, note, by):
    ny = needs_you()
    if not ny.get(qid, root):
        return None, (404, f"no question {qid}")
    try:
        return ny.resolve(qid, by=by, note=note, root=root)[0], None
    except ny.QuestionError as e:
        return None, (409, str(e))


# ---------------------------------------------------------------- CF-0684: requests to the operator
def operator_requests():
    """`shared/operator_requests.py` (CF-0684) - not `requests`: that name
    would shadow the HTTP library in `sys.modules`."""
    return _mod("operator_requests", "shared/operator_requests.py")


#: CC-0018: what `GET /api/requests?status=` takes (the factory judges it).
REQUEST_STATUSES = ("live", "open", "taken", "answered", "closed", "cancelled", "all")
#: CC-0018: `RequestError.code` -> HTTP. 404 - no such request; 422 - the
#: input; every other code (a step the request's state does not allow) - 409.
REQUEST_HTTP_404 = frozenset({"not_found"})
REQUEST_HTTP_422 = frozenset({"text_empty", "text_too_long", "answer_empty", "answer_too_long",
                              "by_missing", "context_invalid", "status_unknown"})


def request_http(code):
    if code in REQUEST_HTTP_404:
        return 404
    return 422 if code in REQUEST_HTTP_422 else 409


def _request_call(fn, *a, **k):
    """(result, None) or (None, (http code, {detail, code, text_ru})) - the
    factory's `RequestError` as the center reads it."""
    opr = operator_requests()
    try:
        return fn(*a, **k), None
    except opr.RequestError as e:
        d = e.as_dict()
        return None, (request_http(e.code), {"detail": d["text"], "code": d["code"],
                                             "text_ru": d["text_ru"]})


def requests_list(root, status="live"):
    """The requests of the queue, oldest first (`operator_requests.list`)."""
    opr = operator_requests()
    return _request_call(opr.list, status, root=root)


def request_get(root, rid):
    """One request; `not_found` (the factory's refusal) when there is none."""
    opr = operator_requests()

    def one():
        r = opr.get(rid, root=root)
        if r is None:
            raise opr.RequestError(f"no request {rid or '(empty id)'}", code="not_found", id=rid)
        return r
    return _request_call(one)


def request_add(root, text, by="user", channel=None, context=None):
    opr = operator_requests()
    return _request_call(opr.add, text, by, channel=channel, context=context, root=root)


def request_close(root, rid, by="user"):
    opr = operator_requests()
    return _request_call(opr.close, rid, by=by, root=root)


def request_cancel(root, rid, by="user"):
    opr = operator_requests()
    return _request_call(opr.cancel, rid, by=by, root=root)


def factory_version(root):
    rl = runlog()
    with git_reads():
        git = rl._git(root) or {}
    return {"version": rl.readme_version(root), "commit": git.get("commit"),
            "dirty": git.get("dirty")}


def process_start(root, now=None):
    """CC-0155 (CF-0841): what this API process runs - read once, when the app
    is built: {started_at (UTC ISO, Z), commit_at_start (the root's HEAD, as
    `factory_version` reads it - GIT_OPTIONAL_LOCKS=0; null outside git)}."""
    now = now or datetime.now(timezone.utc)
    return {"started_at": now.astimezone(timezone.utc).isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "commit_at_start": factory_version(root).get("commit")}


#: CC-0155: what the API process runs - its code and the pins it reads; a commit
#: of data only (the center's own Cc-Action writes, a batch's records) leaves a
#: process current. No file of another kind is read at import (looked: api/,
#: shared/ - module-level reads none; `_mod` loads .py; frontend/dist is served
#: from disk per request).
CODE_PATHS = ("*.py", "agents.lock.json")
STALE_PATHS_MAX = 10


def process_stale(root, started, live):
    """CC-0155: (stale, stale_paths) - the code changed since the process
    started: `git diff --name-only <commit_at_start> <live HEAD> -- CODE_PATHS`
    (GIT_OPTIONAL_LOCKS=0) is not empty; its first STALE_PATHS_MAX paths.
    (False, []) when the two commits are the same (no diff run) or only data
    changed; (None, None) when either commit is unknown or the diff failed."""
    a, b = started.get("commit_at_start"), (live or {}).get("commit")
    if not a or not b:
        return None, None
    if a == b:
        return False, []
    # runlog's git read (git_read.run, optional locks off): None on a failed
    # or timed-out git - no child of its own here (tests/test_cc_api_batches_going.py)
    with git_reads():
        out = runlog()._git_out(root, "diff", "--name-only", a, b, "--", *CODE_PATHS,
                                timeout=10)
    if out is None:
        return None, None
    changed = [ln for ln in out.splitlines() if ln.strip()]
    return bool(changed), changed[:STALE_PATHS_MAX]


def agent_pins(root):
    """(rows, error): the rows of `agents_lock.status`, or why there are none."""
    al = agents_lock()
    try:
        with git_reads():
            rows = al.status(root)
    except al.LockError as e:
        return [], str(e)
    keep = ("agent", "path", "rev", "sha", "head", "branch", "ok", "why")
    return [{k: r.get(k) for k in keep} for r in rows], None


def center_version(dist):
    dist = Path(dist)
    index = dist / "index.html"
    built = index.is_file()
    built_at = None
    if built:
        built_at = datetime.fromtimestamp(index.stat().st_mtime, timezone.utc) \
            .isoformat(timespec="seconds").replace("+00:00", "Z")
    version = None
    try:
        pkg = json.loads((dist.parent / "package.json").read_text(encoding="utf-8"))
        v = pkg.get("version") if isinstance(pkg, dict) else None
        version = v if isinstance(v, str) else None
    except (OSError, ValueError):
        pass
    return {"version": version, "built": built, "built_at": built_at, "dist": str(dist)}


# ------------------------------------------------------------- channels (CC-0006)
# A channel's config is checked by the factory's own code only: the table of
# checks of one config (`inserts/validate_inserts.py` CHANNEL_CHECKS /
# `channel_config_findings`, the body of the loop `validate_vocabulary` runs over
# every channel, which calls the `validate_*_block` checks of
# `patterns/validate_patterns.py`) and the run plan's reader
# (`shared/run_plan.py` `validate` - what `run_plan.py validate <channel>`
# says). Whether a batch of the channel is going: `runlog.open_batches` - what
# `scripts/runlog batch-active` prints - with the batch directory's channel
# named through `channel_ids.resolve_channel` (a former id is the same channel).

CHANNELS_SUBDIR = "channels"


def validate_inserts():
    return _mod("validate_inserts", "inserts/validate_inserts.py")


def run_plan():
    return _mod("run_plan", "shared/run_plan.py")


def channel_ids():
    return _mod("channel_ids", "shared/channel_ids.py")


def channel_list(root):
    """The channel ids: `channels/*.json`, the files `validate_vocabulary` walks."""
    d = Path(root) / CHANNELS_SUBDIR
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def resolve_channel(root, name):
    return channel_ids().resolve_channel(name, root)


def no_pipeline(cfg, channel):
    """(line, error): `channel_ids.no_pipeline_reason` - «конвейера нет...» for a
    stub, None for a channel with a pipeline; error when the stub is broken."""
    ids = channel_ids()
    try:
        return ids.no_pipeline_reason(cfg, channel), None
    except ids.ChannelIdError as e:
        return None, str(e)


def run_plan_errors(root, channel, cfg):
    """`run_plan.py validate <channel>` on a config in hand: the plan's errors,
    the reader's own refusal when a channel with a pipeline has none."""
    rp = run_plan()
    line, err = no_pipeline(cfg, channel)
    if line or err:
        return []
    if rp.KEY not in cfg:
        return [f"channels/{channel}.json: no `{rp.KEY}` key - this channel has no run plan"]
    return [e if e.startswith(rp.KEY) else f"{rp.KEY}: {e}"
            for e in rp.validate(cfg[rp.KEY], Path(root))]


# CC-0054 (CF-0657): a check's line comes to the center as the factory's
# *finding* - {check, code, text, text_ru}: `text` the English line as before
# (behind «подробнее»), `code` a stable reason, `text_ru` the human line with
# the field and the value put in (`validate_inserts.check_finding`, one row per
# check in CHECK_REASONS_RU). The Russian is the factory's, never the API's.
# CC-0056 (CF-0672): the position's checks and the new-channel template's own
# two are the factory's too (`new_channel.stance_findings`,
# `stance_text_findings`, `config_findings`) - every line the API gives has its
# row; `unfound` stays for a bare line only (none is made today).

def unfound(line):
    """A line no check of the factory gives a reason code and Russian text for."""
    return {"check": None, "code": None, "text": line, "text_ru": None}


def stance_findings(cid, stance):
    """`new_channel.stance_findings`: the parsed position of `cid` checked -
    an object of this channel (STANCE_CHECK, code `stance_invalid`)."""
    return new_channel().stance_findings(cid, stance)


def stance_text_findings(cid, raw):
    """`new_channel.stance_text_findings`: (position | None, findings) of the
    position as text or bytes - not JSON is `stance.json: does not parse:
    <error>` (STANCE_PARSE_CHECK, `stance_unreadable`)."""
    return new_channel().stance_text_findings(cid, raw)


def stance_path_findings(cid, cfg, line=None):
    """The template's config names no position file it writes
    (TEMPLATE_STANCE_PATH_CHECK, `template_stance_path`): the factory's lines
    (`new_channel.stance_path_errors`); when the factory sees none but the
    API's own path guard refused, `line` under the same check."""
    lines = new_channel().stance_path_errors(cid, cfg) or ([line] if line else [])
    vi = validate_inserts()
    return vi.check_findings(vi.TEMPLATE_STANCE_PATH_CHECK, lines)


def is_stance_check(finding):
    """A finding of the position itself (parse or content), not of a template."""
    vi = validate_inserts()
    return finding.get("check") in (vi.STANCE_CHECK, vi.STANCE_PARSE_CHECK)


def config_errors(root, channel, cfg):
    """Every finding of a candidate config of `channel` - the factory's checks
    of one channel config (`channel_config_findings`), then its run plan
    (`check_findings` under RUN_PLAN_CHECK). [] - the factory takes it."""
    vi = validate_inserts()
    path = Path(root) / CHANNELS_SUBDIR / f"{channel}.json"
    errs = vi.channel_config_findings(cfg, path)
    if isinstance(cfg, dict):
        errs = errs + vi.check_findings(vi.RUN_PLAN_CHECK, run_plan_errors(root, channel, cfg),
                                        f"{channel}.json")
    return errs


def config_checks():
    """What checks a config: CHANNEL_CHECKS, plus the run plan's reader."""
    vi = validate_inserts()
    rows = [{"block": b, "check": c, "on_stub": s} for b, c, s in vi.CHANNEL_CHECKS]
    rows.append({"block": run_plan().KEY, "check": vi.RUN_PLAN_CHECK, "on_stub": False})
    return rows


def config_fields(cfg):
    """`validate_inserts.channel_fields`: the config described by its own prose."""
    return validate_inserts().channel_fields(cfg)


# ------------------------------------------------------------- a new channel (CC-0008)
# The template and its checks are the factory's: `shared/new_channel.py`
# (`shared/channel_template/` - the one source of a new channel's files).

def new_channel():
    """`shared/new_channel.py`, its own neighbours loaded. The module loads
    them by path itself (`_load`: `<name>_for_new_channel`, put in
    `sys.modules` before it runs), which is not safe for parallel first
    requests - a channel's detail reads the position's check through it
    (CC-0056) - so they are loaded here, under `_mod`'s lock: every caller gets
    the module with its neighbours whole."""
    nc = _mod("new_channel", "shared/new_channel.py")
    with _MODS_LOCK:
        nc._ids(), nc._validate_inserts(), nc._not_a_batch()
    return nc


def channel_template():
    """`new_channel.template()`: the inputs, their defaults and notes, the files."""
    return new_channel().template()


def new_channel_check(root, values, reserved=()):
    """`new_channel.check`: {ok, channel_id, values, files {rel: bytes},
    input_errors [{field, text}], errors [finding]} - nothing written. The
    findings are the factory's own (`new_channel.check()["findings"]`,
    CF-0672): the rendered config's, the template's two (a stub; the position
    file named), the position's - each with its check, code and Russian."""
    res = new_channel().check(root, values, reserved=reserved)
    return dict(res, errors=list(res["findings"]))


def open_batches(root):
    """The batches going now - `runlog.open_batches`, the fresh ones only (what
    `runlog batch-active` counts): [{dir, channel, rebuild, last}]. A rebuild
    (`pipeline/rebuilds/<ts>`) names no channel: `channel` is None."""
    rl = runlog()
    out = []
    for d, last, fresh in rl.open_batches(root):
        if not fresh:
            continue
        chan = Path(d).parent.name
        rebuild = chan in rl.NOT_A_BATCH
        out.append({"dir": str(d), "channel": None if rebuild else resolve_channel(root, chan),
                    "rebuild": rebuild,
                    "last": last.isoformat(timespec="seconds").replace("+00:00", "Z")
                    if last else None})
    return out


# ------------------------------------------------------------- the schedule and the batches (CC-0044)
# The plan, the switch, a channel's schedule settings, the launch journal:
# `shared/batch_schedule.py` (CF-0592/CF-0605). It loads its neighbours
# (`shared/factory_state.py` and what that loads) by path itself; `collect`
# goes in first here, under the lock, so its loader finds the finished module.
# The runs: `shared/runlog/runs_table.py` `read_rows`.

def batch_schedule():
    _mod("factory_state", "shared/factory_state.py")
    return _mod("batch_schedule", "shared/batch_schedule.py")


def runs_table():
    runlog()
    return _mod("runs_table", "shared/runlog/runs_table.py")


# ------------------------------------------------------------- the batches going (CC-0045)
# What the factory's state says of a batch going (once the 2.2 console's): `shared/factory_state.py`
# `batches` / `_batch` / `mean_wall`. It loads its neighbours by its own
# loader, which takes a module already in `sys.modules` from the same file -
# so runlog, run_plan and channel_ids go in first here, under the lock.
# A batch's processes: `shared/run_executor.py` `pid_alive` (`ps`, no signal).

def collect():
    runlog()
    run_plan()
    channel_ids()
    return _mod("factory_state", "shared/factory_state.py")


def funnel():
    """CC-0091: `shared/runlog/funnel.py` - `read_artifacts` (a batch's stage
    files, never raising), PRODUCTION_VERDICTS, `_pool_depth`, `_substitutions`.
    It imports runlog the plain way, so runlog goes in first."""
    runlog()
    return _mod("funnel", "shared/runlog/funnel.py")


def below_shortlist():
    """CC-0171 (CF-0882): `shared/below_shortlist.py` - RECORD_FILE (the
    refill's `work/below-shortlist-refill.json`) and REFILL_MARK (the key on the
    01 topics[] / 02 reserve[] rows it moved). Only the standard library at
    import - nothing of it runs."""
    return _mod("below_shortlist", "shared/below_shortlist.py")


def reason_ru(code):
    """CC-0113 (CF-0714): the Russian line of a funnel code -
    `funnel.reason_ru` (the row of its current name, `canonical_code`); None
    for no code, a code outside the vocabulary, or a factory without the
    dictionary. The API never words a code itself."""
    if not code or not isinstance(code, str):
        return None
    fn = getattr(funnel(), "reason_ru", None)
    return fn(code) if fn else None


def with_reason_ru(obj):
    """CC-0113: `obj` copied with `reason_ru` (`reason_ru`) beside every
    `reason_code` of every object in it, recursively; an object that already
    carries `reason_ru` keeps its own. The input is never written."""
    memo = {}

    def ru(code):
        if code not in memo:
            memo[code] = reason_ru(code)
        return memo[code]

    def walk(x):
        if isinstance(x, dict):
            out = {k: walk(v) for k, v in x.items()}
            if "reason_code" in out and "reason_ru" not in out:
                c = out["reason_code"]
                out["reason_ru"] = ru(c) if isinstance(c, str) else None
            return out
        if isinstance(x, (list, tuple)):
            return [walk(v) for v in x]
        return x
    return walk(obj)


def reasons_ru(codes):
    """CC-0113: {code: reason_ru(code)} of every code given (strings only)."""
    return {c: reason_ru(c) for c in codes if isinstance(c, str) and c}


# ------------------------------------------------- the flag's scenes (CC-0169, CF-0846)
#: `sensitivity_scenes.WHOLE_TOPIC` - the flag rests on the topic as such.
WHOLE_TOPIC = "whole_topic"


def sensitivity_scenes(check):
    """CC-0169 (CF-0846): `content_sensitivity_check.scenes` in one of the two
    forms the contract types - a clean non-empty list of the topic's scene ids
    or `"whole_topic"`; None when the check or the field is absent (a row
    written before CF-0846). Anything else - `null`, `[]`, a stray value - is
    `"whole_topic"`, as `sensitivity_scenes.flagged_scenes` reads it (fail
    closed: a doubt is never "another scene")."""
    if not isinstance(check, dict) or "scenes" not in check:
        return None
    v = check.get("scenes")
    if isinstance(v, list) and v and all(isinstance(s, str) and s.strip() for s in v):
        return list(v)
    return WHOLE_TOPIC


def short_scene(scene_id, topic_id):
    """`lf-2026-10-21-006-s2` -> `s2` (the topic's prefix taken off) -
    `shared/runlog/scene_holds.short_scene`."""
    s = str(scene_id or "")
    pre = f"{topic_id}-"
    return s[len(pre):] if topic_id and s.startswith(pre) and len(s) > len(pre) else s


def footage_progress():
    """CC-0119: `shared/runlog/footage_progress.py` (CF-0715) - `footage_progress`
    (the Footage Indexer's collection per topic: the progress file, RUN_EVENTS
    or the 01b report), PROGRESS_REL, REPORT_FILE, TREND_FILE, STATES; its
    `write_progress` / `Tracker` / `main` are never called here. It imports
    runlog the plain way and takes its neighbours by `runlog.sibling`, so
    runlog goes in first."""
    runlog()
    return _mod("footage_progress", "shared/runlog/footage_progress.py")


def run_summary():
    """CC-0099: `shared/runlog/summary.py` (CF-0110) - `compute` (what `runlog
    summary --json` prints) and SUMMARY_FILE; its `write` / `main` are never
    called here. It imports runlog the plain way and takes its neighbours by
    `runlog.sibling`, so runlog goes in first; the name is the one `sibling`
    gives it."""
    runlog()
    return _mod("summary", "shared/runlog/summary.py")


def score_model():
    """CC-0125: `shared/score/score.py` (CF-0432 / CF-0434) - load_model (the
    tiers and their floors), LABELS / HARD_LABELS / JUDGE_PREFIX (the Russian
    words `summary_line` prints), STAGES, LOG_SUFFIX, HARD_RULES. Stdlib only,
    read only; loaded as `score`, the name the Editor's `_score.module()`
    imports it by, so both share one copy."""
    return _mod("score", "shared/score/score.py")


def run_executor():
    run_plan()                       # its own `import run_plan` finds this one
    return _mod("run_executor", "shared/run_executor.py")


# ------------------------------------------------------------- stop and resume (CC-0047)
# «остановить батч» / «продолжить батч»: `shared/batch_control.py` (CF-0667)
# `stop_check` / `stop`, `resume_check` / `resume`. It imports batch_schedule,
# run_executor, run_plan and channel_ids the plain way (shared/ on sys.path),
# so they go in first here, under the lock, and its imports find these.

def batch_control():
    batch_schedule()
    run_executor()
    channel_ids()
    return _mod("batch_control", "shared/batch_control.py")


def stage_code_guard():
    """CC-0111: `shared/stage_code_guard.py` (CF-0713) - EVENT_KIND
    (`stage_code_edit`), `describe(edits)`, the one line of what a batch
    stage changed in the factory's tracked code (what the executor writes
    into the stage-done note and the event's `note`). Its runlog is loaded by
    path on use (`_runlog`), so it is runlog's first."""
    runlog()
    return _mod("stage_code_guard", "shared/stage_code_guard.py")


def executor_lock():
    """CC-0110: `shared/runlog/executor_lock.py` (CF-0670) - `holder` / `why`, who
    holds a batch's `run-executor.lock` and the line why it keeps the run open.
    Runlog's sibling, the one copy `batch_control` and `runlog.open_batches`
    take."""
    return runlog().sibling("executor_lock")


# ------------------------------------------------------------- publication (CC-0064)
# The publisher's side, read only (`api/publish.py`). The queue, the pause, the
# card, the journal and the API-upload switch are `collect`'s own loaders
# (`queue`, `pause`, `card`, `note`, `journal`, `api_switch`) - one copy each,
# as the console and `api/videos.py` take them. The three below are loaded by
# path here: each imports its neighbours the plain way, so what they import
# goes in first (under the lock) and their imports find these copies.

def publish_layout():
    """`shared/runlog/publish_layout.py` - the layout `publish/<channel>/<day>/`
    (CF-0475); `publish_queue` imports it the plain way."""
    collect().queue()
    return _mod("publish_layout", "shared/runlog/publish_layout.py")


def publish_stash():
    """`agents/publisher/publish_stash.py` (CF-0738): stash, place_plan,
    place_confirm, state_sha256 - the channel's копилка (CC-0122). Its plain
    imports (`acceptance`, `publish_card`, `publish_layout`, `publish_queue`)
    are collect's copies, loaded first."""
    c = collect()
    c.acceptance()
    c.card()
    c.queue()
    publish_layout()
    card_center()                   # CF-0747: its `import card_center` finds this copy
    return _mod("publish_stash", "agents/publisher/publish_stash.py")


def publish_move():
    """`agents/publisher/publish_move.py` (CF-0856): move_plan / move_confirm -
    moving a placed video to another day or taking it back into the копилка
    (CC-0165). Its plain imports (`acceptance`, `publish_layout`,
    `publish_queue`, `publish_stash`, `upload_records`, `git_commit`) are
    collect's / this module's copies, loaded first."""
    collect().journal()
    publish_stash()
    git_commit()
    return _mod("publish_move", "agents/publisher/publish_move.py")


def card_center():
    """`agents/publisher/card_center.py` (CF-0747): card_info, card_build_launch
    (a detached `publish_card.py build` with its log), card_build_result,
    ruling_plan / ruling_confirm, BUILD_REFUSALS, RULING_REFUSALS, OUTCOMES,
    OUTCOME_WORDS (CC-0127). Its plain imports (`acceptance`, `publish_card`,
    `publish_layout`, `publish_note`) are collect's copies, loaded first."""
    c = collect()
    c.acceptance()
    c.card()
    c.note()
    publish_layout()
    return _mod("card_center", "agents/publisher/card_center.py")


def studio_fields():
    """`agents/publisher/studio_fields.py` (CF-0018): `locate`, `prepare`,
    `form_fields`, `streak` - its imports (`publish_card`, `publish_layout`,
    `publish_note`, `upload_gate`, `upload_records`) are collect's copies."""
    c = collect()
    c.card()
    c.note()
    c.journal()
    c.queue()
    c.pause()
    return _mod("studio_fields", "agents/publisher/studio_fields.py")


def upload():
    """`agents/publisher/upload.py` (CF-0421/CF-0607): `run` - the API upload
    (CC-0066, `api/publish_net.py`). Its imports (`api_switch`, `publish_card`,
    `publish_note`, `publisher_auth`, `publisher_config`, `upload_records`,
    `publish_layout`) are collect's copies; `youtube_client` touches Google
    only inside `YouTubeClient`, which only `upload.default_client` makes."""
    c = collect()
    c.card()
    c.note()
    c.journal()
    c.queue()
    c.pause()
    c.auth()
    c.pubcfg()
    c.api_switch()
    publish_layout()
    studio_fields()
    return _mod("upload", "agents/publisher/upload.py")


def publication_hold():
    """`agents/compliance-checker/scripts/publication_hold.py` (CF-0318):
    `read_ledger`, `open_holds` - `publish/publication-holds.json`."""
    runlog()
    channel_ids()
    return _mod("publication_hold", "agents/compliance-checker/scripts/publication_hold.py")


def rotate():
    """`rotation/rotate.py` (CF-0015): `distribution_report`, `awaiting_material`
    - what `rotate.py status` prints."""
    channel_ids()
    return _mod("rotate", "rotation/rotate.py")


# ------------------------------------------------------------- the analyst (CC-0020)
# `agents/analyst/` - read only here (`api/analytics.py`). Each module puts its
# own folder (and the publisher's) on sys.path and imports its neighbours the
# plain way, so they go in first under the lock: the journal and the
# acceptance record are collect's copies, the store and the client this
# checkout's. `summary.py` loads as `analyst_summary` - `shared/runlog/` has a
# `summary.py` of its own, and `sys.modules["summary"]` must stay that one.

def metrics_store():
    """`agents/analyst/metrics_store.py` (CF-0020/CF-0588/CF-0624): read_daily,
    read_windows, window, read_runs, read_studio, latest_studio, last_visit -
    `analytics/<channel>/*.jsonl`."""
    collect().journal()
    return _mod("metrics_store", "agents/analyst/metrics_store.py")


def analyst_metrics():
    """`agents/analyst/metrics.py` (CF-0020): default_day - the Pacific
    yesterday every collection and summary counts to. `analytics_client`
    touches Google only inside its client - never made here."""
    metrics_store()
    _mod("analytics_client", "agents/analyst/analytics_client.py")
    return _mod("metrics", "agents/analyst/metrics.py")


def analyst_summary():
    """`agents/analyst/summary.py` (CF-0021): build - the videos beside their
    style, the groups' statistics; channels_of."""
    collect().acceptance()
    analyst_metrics()
    return _mod("analyst_summary", "agents/analyst/summary.py")


def footage_wanted():
    """`agents/analyst/footage_wanted.py` (CF-0023): build - what the scripts
    asked for and the footage did not give."""
    return _mod("footage_wanted", "agents/analyst/footage_wanted.py")


def pool_release():
    """CC-0107: `shared/runlog/pool_release.py` (CF-0358) - Resolver,
    read_journal, topic_status, open_batch_keys, plan (the what-if,
    `extra_withdrawn`) and record_withdrawal (only in api/withdrawal.py); its
    `delete` and `main` are never called here. It imports runlog the plain way
    (`open_batch_keys`), so runlog goes in first."""
    runlog()
    return _mod("pool_release", "shared/runlog/pool_release.py")


def publish_profile():
    """CC-0108: `shared/runlog/publish_profile.py` (CF-0440) - `diversity`,
    `render_diversity`, AXES, DEFAULT_LAST and its `_load` of the acceptance
    log: what `runlog diversity` prints. Its `fill` / `stamp_md` (the
    profile's writes) are never called here. Its neighbours (acceptance,
    scores) import runlog the plain way, so runlog goes in first."""
    runlog()
    return _mod("publish_profile", "shared/runlog/publish_profile.py")


def gate_price():
    """CC-0100: `shared/runlog/gate_price.py` (CF-0320) - RULES, rule, price,
    headline, batches, read_ledger, proposals, proposal_line: what `runlog
    gate-price --json` prints (api/gate_prices.py); CC-0114: ledger_sha256,
    sign and decide (CF-0721, by user via center, after the user's button).
    Its `write_ledger`, `write_stats` and `main` (`--write`) are never called
    here. It imports
    funnel and stopcock the plain way, and they import runlog, so those go in
    first."""
    funnel()
    _mod("stopcock", "shared/runlog/stopcock.py")
    return _mod("gate_price", "shared/runlog/gate_price.py")


def studio_read():
    """`agents/analyst/studio_read.py` (CF-0588): studio_settings, last_videos,
    due, no_pipeline (api/analytics.py, read only); parse_read and
    record(by, via) - CF-0692 - only in api/studio_entry.py (CC-0074)."""
    metrics_store()
    return _mod("studio_read", "agents/analyst/studio_read.py")


def studio_center():
    """`agents/analyst/studio_center.py` (CF-0735): studio_read_due,
    studio_read_launch (the plan in process; the confirmed launch only in the
    child of api/studio_center.py, behind its switch), studio_read_result,
    CenterError, HOOKS, HOOK_WORDS, OUTCOME_WORDS (CC-0120). Its
    `studio_insurance_notify` is never called by the API (the tick's and the
    batch's). It imports studio_read the plain way, so that goes in first."""
    studio_read()
    return _mod("studio_center", "agents/analyst/studio_center.py")


# ------------------------------------------------------------- a channel's lists (CC-0022)
def channel_data():
    """`shared/channel_data.py` (CF-0561): channel_list_path, rights_holders,
    footage_origin - a channel's own lists."""
    return _mod("channel_data", "shared/channel_data.py")


def fact_rule():
    """`shared/factrule/fact_rule.py` (1.8): validate_sources - the fact rule's
    own check of a fact-sources list (CC-0102)."""
    return _mod("fact_rule", "shared/factrule/fact_rule.py")


FACT_RULE_RU_REL = "shared/factrule/fact_rule_ru.py"


def fact_rule_ru():
    """CC-0119: `shared/factrule/fact_rule_ru.py` (CF-0752) - FAIL_CODES_RU
    (the Russian reason of every `fact_rule.FAIL_CODES` code) and `reason_ru`
    (an unknown code comes back as it is). It puts its directory on sys.path
    and imports `fact_rule` the plain way, so `fact_rule` goes in first under
    that name and both share one copy. None for a factory without the file."""
    if not (CODE / FACT_RULE_RU_REL).is_file():
        return None
    fact_rule()
    return _mod("fact_rule_ru", FACT_RULE_RU_REL)


def fact_failures_ru(codes):
    """CC-0119: `[{code, ru}]` parallel to a fact candidate's `failures` (same
    order, same length). `ru` is `fact_rule_ru.reason_ru(code)`, or None when
    the factory has no word for the code (`reason_ru` gave the code back, or
    no dictionary) - the center then says the reason has no description. The
    API never words a code itself."""
    mod = fact_rule_ru()
    fn = getattr(mod, "reason_ru", None) if mod is not None else None
    out = []
    for c in codes:
        ru = fn(c) if fn is not None else None
        out.append({"code": c, "ru": ru if isinstance(ru, str) and ru and ru != c else None})
    return out


def affiliate():
    """`shared/affiliate.py` (CF-0593): enabled, table_path, read_table,
    channel_errors - the channel's affiliate slot and table (CC-0102);
    write_table (CF-0726) only in `api/channel_lists.py`'s confirm and plan."""
    return _mod("affiliate", "shared/affiliate.py")


def footage_licence():
    """`shared/footage_licence.py` (CF-0564): footage_origin_errors."""
    return _mod("footage_licence", "shared/footage_licence.py")


def channel_list_write():
    """`shared/channel_list_write.py` (CF-0726): list_sha256 (a list's base),
    write_fact_sources, write_footage_origin - the checked writers of a
    channel's lists (`api/channel_lists.py` only; affiliate.write_table and
    write_table is the same write)."""
    return _mod("channel_list_write", "shared/channel_list_write.py")


# ------------------------------------------------------------- the meme desk (CC-0024)
def meme_desk():
    """`scripts/meme_desk.py` (CF-0693): desk_state, save_marks, plan_apply,
    apply_marks, thumb, resolve_bank, MemeDeskError - the desk as functions,
    the bank a parameter (never the module's `BANK`), nothing printed."""
    return _mod("meme_desk", "scripts/meme_desk.py")


# ------------------------------------------------------------- notifications (CC-0026)
def notify():
    """`shared/notify.py` (CF-0591, CF-0606, CF-0617): rows (the journal),
    reminders, parse_when, one_line, msk_text, add_reminder(by), settings,
    enabled, mask_token, and `main(["test"], out)` - the CLI's dry `test`
    (a stand-in: nothing sent, the journal untouched). `send_due` is never
    called by the API; `cancel_reminder` only in the cancel's confirm; `send`
    only in api/notify_send.py's `test_send` (CC-0109) - the call `main()`
    makes for `test --send`, once, after the user's confirm."""
    return _mod("notify", "shared/notify.py")


def utc_iso(ts):
    """A POSIX time as UTC ISO, seconds."""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") \
        .replace("+00:00", "Z")
