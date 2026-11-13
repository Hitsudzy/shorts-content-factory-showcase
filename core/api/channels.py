"""CC-0006: a channel's config and position - read, check, save as a commit,
history, revert one edit.

    channels/<id>.json            the config (no formal schema - the factory's
                                  code is the check, `api/factory.py`)
    channels/<id>/stance.json     the position - the path is the config's
                                  `stance` field, relative to `channels/`

**Saving** is: the factory's checks of the candidate (`factory.config_errors`),
the write, then one commit of the touched file(s) only, in the git repository
at `CC_FACTORY_ROOT`, on its current branch:

    Канал <display_name>: изменено <поле> (из центра)

with the trailers `Cc-Channel: <id>` / `Cc-Action: edit|revert`
(`Cc-Reverts: <sha>` on a revert) - what the history reads back. Refused,
with nothing written:

* a batch of this channel is going (`factory.open_batches` - what
  `runlog batch-active` counts - scanned afresh for every write; a read
  answers the last scan, `BATCH_TTL`), or a rebuild, which names no channel;
* the file(s) have changes git does not have yet (a hand edit is never
  overwritten, nor committed by the center);
* the files changed since the client read them (`base` is not the
  `revision` now);
* the factory's checks refuse the candidate, or nothing changed;
* `channel_id` or `stance` (the path) changed - a rename is not an edit.

**Reverting** one commit of the history: only a commit that touched nothing
but this channel's config / position (every edit of the center is one); its
reverse patch is applied to copies of the files, the result checked like a
save, then written and committed as above. A later edit of the same lines
makes it refuse with the reason.

**Creating** a channel (CC-0008): the factory's template and checks
(`factory.new_channel_check` - `shared/new_channel.py`, the template
`shared/channel_template/`), then the new files written and committed as one
commit `Канал <display_name>: создан (из центра)` (`Cc-Action: create`). A dry
run says what would be written and what the checks say, writing nothing,
under no lock. `stance_text` (the wizard's position) takes the place of the
template's skeleton, checked as a save checks it (CC-0041).
Refused while **any** batch or rebuild is going - the commit moves the root's
HEAD, which runlog records as `code_drift` in a running batch.

Every refusal is a `ChannelFault`: a message for a human in Russian (the
center shows it as is), a `code`, the technical `details` the center hides
behind «подробнее», and the checker's lines with the field each names.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import factory

CENTER_TRAILER = "Cc-Channel"
ACTION_TRAILER = "Cc-Action"
REVERTS_TRAILER = "Cc-Reverts"
GIT_TIMEOUT = 120          # a post-commit hook (the push, CF-0502) runs inside `git commit`
SUBJECT_FIELDS = 3         # names in the subject before «и ещё N»
HISTORY_LIMIT = 200
#: The open batches (`factory.open_batches`, what `runlog batch-active` counts)
#: are one scan of the whole `pipeline/` - 36-55 s on this machine under load
#: (CC-0041, 2026-10-10). A **read** (the list, a channel, the template, a dry
#: run) never waits for one: it answers the last known result with its time
#: (`checked_at`, `age_s`) and, when that is older than `BATCH_TTL`, starts one
#: refresh in the background - one at a time per factory root, every other
#: read meanwhile gets the same last result (`checking: true`). Only the very
#: first read of a root (nothing known yet) waits for the scan, once; `serve`
#: starts that scan at boot (`warm`). A **write** (create, PUT, revert) always
#: scans afresh itself, under `_WRITE`, before it commits.
BATCH_TTL = 30.0
#: Seconds a read waits for the refresh it started (or found going) before it
#: answers the last known result - 0: never. The tests set it high to read
#: synchronously.
BATCH_WAIT = 0.0
_SCANS = {}                # str(root) -> _Scan
_SCAN_COND = threading.Condition()


class _Scan:
    """What one factory root's open batches were when last scanned."""
    def __init__(self):
        self.rows = None        # [{dir, channel, rebuild, last}] or None: never scanned
        self.started = None     # time.monotonic() the scan of `rows` began
        self.at = None          # the same moment, UTC - `checked_at`
        self.error = None       # the last scan's failure, if it failed
        self.begun = 0          # refreshes started / finished (a read waits for its own)
        self.done = 0

    @property
    def running(self):
        return self.begun > self.done


_WRITE = threading.Lock()  # one save or revert at a time in this process


class ChannelFault(Exception):
    def __init__(self, status, code, message, details=None, errors=None, batches=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = [str(d) for d in (details or [])]
        self.errors = errors or []
        self.batches = batches or []

    def body(self):
        return {"message": self.message, "code": self.code, "details": self.details,
                "errors": self.errors, "batches": self.batches}


# ---------------------------------------------------------------- reading
def _channel(root, name):
    cid = factory.resolve_channel(root, name)
    if cid not in factory.channel_list(root):
        raise ChannelFault(404, "unknown_channel", f"Канала «{name}» нет в фабрике.",
                           [f"no {factory.CHANNELS_SUBDIR}/{cid}.json under {root}"])
    return cid


def _config_path(root, cid):
    return Path(root) / factory.CHANNELS_SUBDIR / f"{cid}.json"


def _stance_path(root, cid, cfg):
    """The position's file (it may not exist), or None when the config names none.
    It has to sit under `channels/` (`factory.contained`, the one guard of the
    API's paths, CC-0053)."""
    rel = cfg.get("stance") if isinstance(cfg, dict) else None
    if not isinstance(rel, str) or not rel.strip():
        return None
    if rel.startswith(("/", "\\")) or Path(rel).is_absolute():
        return None
    p = factory.contained(root, factory.CHANNELS_SUBDIR,
                          *[x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")])
    return p.resolve() if p is not None else None


def _read(path):
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def _parse(raw, what):
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise ChannelFault(422, "not_json", f"{what} - не JSON: {e}.", [str(e)])
    if not isinstance(doc, dict):
        raise ChannelFault(422, "not_json", f"{what} должен быть JSON-объектом {{…}}.",
                           [f"top level is {type(doc).__name__}"])
    return doc


def _revision(cfg_raw, stance_raw):
    h = hashlib.sha256(cfg_raw or b"")
    h.update(b"\0")
    h.update(stance_raw or b"")
    return h.hexdigest()[:16]


def _state(root, cid):
    """(config bytes, config, stance path, stance bytes, revision) on disk now."""
    raw = _read(_config_path(root, cid))
    cfg = _parse(raw, f"Конфиг канала {cid}")
    sp = _stance_path(root, cid, cfg)
    sraw = _read(sp) if sp else None
    return raw, cfg, sp, sraw, _revision(raw, sraw)


def _rel(root, path):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _utc(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else None


def _scan_now(root, st, fn=None):
    """One scan; its result is kept unless a scan begun later already landed.
    `fn(root)`: what is scanned - `factory.open_batches` unless told."""
    t0, at = time.monotonic(), datetime.now(timezone.utc)
    rows = (fn or factory.open_batches)(root)
    with _SCAN_COND:
        if st.started is None or t0 >= st.started:
            st.rows, st.started, st.at, st.error = rows, t0, at, None
    return rows, t0, at


def _refresh(root, st, fn=None):
    try:
        _scan_now(root, st, fn)
    except BaseException as e:          # kept, the last result stands; the next read retries
        with _SCAN_COND:
            st.error = e
    finally:
        with _SCAN_COND:
            st.done += 1
            _SCAN_COND.notify_all()


def _start_refresh(root, st, fn=None, name="cc-open-batches"):
    """Under `_SCAN_COND`: one refresh at a time; returns the number to wait for."""
    if not st.running:
        st.begun += 1
        threading.Thread(target=_refresh, args=(root, st, fn), daemon=True,
                         name=name).start()
    return st.begun


def warm(root, scans=None, fn=None, name="cc-open-batches"):
    """Start the first scan of `root` in the background (`serve` at boot).
    `scans` / `fn`: another kept scan (`cached_scan`) - the open batches by
    default."""
    scans = _SCANS if scans is None else scans
    with _SCAN_COND:
        st = scans.setdefault(str(Path(root).resolve()), _Scan())
        if st.rows is None:
            _start_refresh(root, st, fn, name)


def cached_scan(root, fresh, scans, fn, ttl, wait, name="cc-open-batches"):
    """(result, {checked_at, age_s, checking}) of a slow scan of a factory
    root, kept per root in `scans` and refreshed in the background past `ttl`
    seconds - see BATCH_TTL; `wait`: as BATCH_WAIT. The open batches use it
    (`_open_batches`), and so does the list of the batches going
    (`api/batches.py`, CC-0045). `fn(root)`: the scan (None: open_batches)."""
    key = str(Path(root).resolve())
    if fresh:
        with _SCAN_COND:
            st = scans.setdefault(key, _Scan())
        rows, t0, at = _scan_now(root, st, fn)
        return rows, {"checked_at": _utc(at), "age_s": round(time.monotonic() - t0, 1),
                      "checking": False}
    with _SCAN_COND:
        st = scans.setdefault(key, _Scan())
        stale = st.rows is None or time.monotonic() - st.started > ttl
        if stale:
            mine = _start_refresh(root, st, fn, name)
            if st.rows is None:                 # nothing known yet: wait once
                _SCAN_COND.wait_for(lambda: st.done >= mine)
            elif wait > 0:
                _SCAN_COND.wait_for(lambda: st.done >= mine, timeout=wait)
        if st.rows is None:
            raise st.error or RuntimeError("open batches: no scan result")
        return st.rows, {"checked_at": _utc(st.at),
                         "age_s": round(time.monotonic() - st.started, 1),
                         "checking": st.running}


def _open_batches(root, fresh):
    """(rows, {checked_at, age_s, checking}) - see BATCH_TTL."""
    rows, meta = cached_scan(root, fresh, _SCANS, None, BATCH_TTL, BATCH_WAIT)
    return list(rows), meta


def lock(root, cid, fresh=False, scan=None):
    """{locked, message, batches, checked_at, age_s, checking}: the batches going
    that block an edit of `cid`, as of `checked_at`. `scan`: an `_open_batches`
    result already in hand (the list reads it once for every channel)."""
    found, meta = scan or _open_batches(root, fresh)
    rows = [b for b in found if b["rebuild"] or b["channel"] == cid]
    if not rows:
        return dict(meta, locked=False, message=None, batches=[])
    mine = [b for b in rows if not b["rebuild"]]
    if mine:
        msg = (f"Идёт батч канала {cid} ({Path(mine[0]['dir']).name}): пока он не закончится, "
               f"конфиг и позицию менять нельзя - батч читает их по ходу работы.")
    else:
        msg = ("Идёт пересборка роликов: пока она не закончится, конфиги каналов менять "
               "нельзя - пересборка читает их по ходу работы.")
    return dict(meta, locked=True, message=msg, batches=rows)


def _error_rows(cid, errs):
    """The checker's findings as CheckLine rows: {text, field, code, text_ru} -
    `field` the dotted path the English line names (`<id>.json.<path>: ...`),
    `code`/`text_ru` the factory's (`factory.config_errors`, CC-0054; the
    position's and the template's checks, CC-0056); a bare line - none is
    made today - would come as `factory.unfound`."""
    ctx = f"{cid}.json"
    out = []
    for f in errs:
        f = factory.unfound(f) if isinstance(f, str) else f
        e = f["text"]
        head, sep, _ = e.partition(":")
        field = None
        if sep and (head == ctx or head.startswith(ctx + ".")):
            field = head[len(ctx) + 1:] or None
        elif sep and (head == "run_plan" or head.startswith("run_plan.")):
            field = "run_plan"
        elif sep and head.startswith("stance.json"):
            field = "stance" + head[len("stance.json"):]
        out.append({"text": e, "field": field, "code": f["code"], "text_ru": f["text_ru"]})
    return out


def _input_rows(rows):
    """`new_channel.input_errors` ({field, text}, the text the factory's own
    Russian) as CheckLine rows: no reason code, `text_ru` the same line."""
    return [{"text": r["text"], "field": r["field"], "code": None, "text_ru": r["text"]}
            for r in rows]


def listing(root):
    """{channels, checked_at, age_s, checking}: every channel, and how fresh
    its `locked` is (one scan of the open batches for all of them)."""
    scan = _open_batches(root, False)
    return dict(scan[1], channels=summaries(root, scan))


def summaries(root, scan=None):
    scan = scan or _open_batches(root, False)
    out = []
    for cid in factory.channel_list(root):
        row = {"id": cid, "display_name": None, "former_ids": [], "no_pipeline": None,
               "stance": False, "locked": False, "error": None}
        try:
            raw, cfg, sp, sraw, rev = _state(root, cid)
        except ChannelFault as f:
            row["error"] = f.message
            out.append(row)
            continue
        line, err = factory.no_pipeline(cfg, cid)
        formers = cfg.get("former_channel_ids") or []
        row.update(display_name=cfg.get("display_name") if isinstance(cfg.get("display_name"), str)
                   else None,
                   former_ids=[formers] if isinstance(formers, str) else [str(x) for x in formers],
                   no_pipeline=line, stance=sraw is not None, locked=lock(root, cid, scan=scan)["locked"],
                   error=err, revision=rev)
        out.append(row)
    return out


def _fields(cfg, stance):
    rows = [dict(r, file="config") for r in factory.config_fields(cfg)]
    if isinstance(stance, dict):
        rows += [dict(r, file="stance", checked_by=[]) for r in factory.config_fields(stance)]
    return rows


def detail(root, name):
    cid = _channel(root, name)
    raw, cfg, sp, sraw, rev = _state(root, cid)
    stance = None
    if sraw is not None:
        try:
            stance = json.loads(sraw)
        except ValueError:
            stance = None
    line, _ = factory.no_pipeline(cfg, cid)
    errs = _check(root, cid, cfg, stance, sraw)
    return {"id": cid, "display_name": cfg.get("display_name"), "no_pipeline": line,
            "revision": rev,
            "config": cfg, "config_text": raw.decode("utf-8"),
            "config_path": _rel(root, _config_path(root, cid)),
            "stance": stance, "stance_text": sraw.decode("utf-8") if sraw is not None else None,
            "stance_path": _rel(root, sp) if sp else None,
            "fields": _fields(cfg, stance), "checks": factory.config_checks(),
            "errors": _error_rows(cid, errs), "lock": lock(root, cid)}


# ---------------------------------------------------------------- checking
def _check(root, cid, cfg, stance, sraw):
    """Every finding of a candidate: the config's (`factory.config_errors`),
    then the position's when there is one - `stance` parsed, or else its bytes
    `sraw` (a file that does not parse is the factory's `stance_unreadable`).
    The position's checks are the factory's (`new_channel.stance_findings`,
    `stance_text_findings`, CF-0672)."""
    errs = factory.config_errors(root, cid, cfg)
    if stance is not None:
        errs += factory.stance_findings(cid, stance)
    elif sraw is not None:
        errs += factory.stance_text_findings(cid, sraw)[1]
    return errs


def _candidate(body, cfg_now, sraw_now, cid=None):
    """(config bytes, config, stance bytes|None, stance|None) the client sends;
    a part it leaves out stays as it is on disk. A position that is not a JSON
    object is refused `not_json` with the factory's row of it in `errors`
    (`stance_unreadable` / `stance_invalid`, CC-0056) when `cid` is given."""
    def part(text, obj, now, what, rows=None):
        if text is not None:
            raw = text.encode("utf-8")
            try:
                return raw, _parse(raw, what)
            except ChannelFault as f:
                f.errors = rows(raw) if rows else f.errors
                raise
        if obj is not None:
            if not isinstance(obj, dict):
                raise ChannelFault(422, "not_json", f"{what} должен быть JSON-объектом {{…}}.",
                                   errors=rows(obj) if rows else None)
            raw = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            return raw, obj
        return now, None

    def stance_rows(given):
        if isinstance(given, bytes):
            _, found = factory.stance_text_findings(cid, given)
        else:
            found = factory.stance_findings(cid, given)
        return _error_rows(cid, found)
    craw, cfg = part(body.get("config_text"), body.get("config"), cfg_now, "Конфиг")
    sraw, stance = part(body.get("stance_text"), body.get("stance"), sraw_now, "Позиция",
                        stance_rows if cid else None)
    return craw, cfg, sraw, stance


def _paths_changed(old, new, prefix=""):
    """The dotted paths where `new` differs from `old` (objects walked, an
    array is one value) - the names in the commit's subject."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in list(old) + [k for k in new if k not in old]:
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in old or k not in new:
                out.append(p)
            elif old[k] != new[k]:
                out += _paths_changed(old[k], new[k], p)
        return out
    return [] if old == new else [prefix or "(весь файл)"]


def check(root, name, body):
    """The factory's verdict on a candidate, nothing written: {ok, errors}."""
    cid = _channel(root, name)
    raw, cfg_now, sp, sraw_now, rev = _state(root, cid)
    craw, cfg, sraw, stance = _candidate(body, raw, sraw_now, cid)
    cfg = cfg if cfg is not None else cfg_now
    if stance is None and sraw is not None:
        try:
            stance = json.loads(sraw)
        except ValueError:
            stance = None
    errs = _check(root, cid, cfg, stance, sraw)
    return {"ok": not errs, "errors": _error_rows(cid, errs)}


# ---------------------------------------------------------------- git
def _git(root, *args, input=None, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    gr = factory.git_read()                                  # CF-0717: the one door
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C", **gr.GIT_READ_ENV)   # CC-0098
    cp = gr.run(["-C", str(root), *args], capture_output=True, text=True,
                encoding="utf-8", errors="replace", input=input, env=env,
                timeout=GIT_TIMEOUT)
    if check and cp.returncode != 0:
        raise ChannelFault(500, "git_failed", "Git не выполнил операцию - правка не сохранена.",
                           [f"git {' '.join(args)}: exit {cp.returncode}",
                            (cp.stderr or cp.stdout).strip()])
    return cp


def _require_repo(root):
    cp = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    if cp.returncode != 0 or cp.stdout.strip() != "true":
        raise ChannelFault(500, "not_a_repo",
                           "Каталог фабрики - не git-репозиторий: правку нельзя сохранить "
                           "коммитом.", [f"{root}: {cp.stderr.strip()}"])


def _dirty(root, rels):
    cp = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *rels)
    return [line for line in cp.stdout.splitlines() if line.strip()]


def _trailers(cid, action, reverts=None):
    lines = [f"{CENTER_TRAILER}: {cid}", f"{ACTION_TRAILER}: {action}"]
    if reverts:
        lines.append(f"{REVERTS_TRAILER}: {reverts}")
    return "\n".join(lines)


def _names(paths):
    if len(paths) <= SUBJECT_FIELDS:
        return ", ".join(paths)
    return ", ".join(paths[:SUBJECT_FIELDS - 1]) + f" и ещё {len(paths) - SUBJECT_FIELDS + 1}"


def _write_and_commit(root, cid, writes, message):
    """Write {path: bytes} and commit those files only - the factory's helper
    (`shared/runlog/git_commit.write_and_commit`, CF-0675, the same shape this
    function had: a temp name and `os.replace`, `git add` + `git commit --only`,
    every file put back and unstaged on a failure). Its refusal is the
    API's `git_failed`, git's words behind. The message (its `Cc-*` trailers)
    goes in as given; the dirty-file refusal stays in `_guard_write`."""
    gc = factory.git_commit()
    try:
        return gc.write_and_commit(root, writes, message)
    except gc.CommitError as e:
        raise ChannelFault(500, "git_failed", "Git не выполнил операцию - правка не сохранена.",
                           [str(e), *e.details])


def _guard_write(root, cid, base, rev_now, rels):
    lk = lock(root, cid, fresh=True)
    if lk["locked"]:
        raise ChannelFault(409, "batch_running", lk["message"],
                           [b["dir"] for b in lk["batches"]], batches=lk["batches"])
    if base is not None and base != rev_now:
        raise ChannelFault(409, "conflict",
                           "Конфиг изменился, пока вы его правили. Обновите страницу и "
                           "повторите правку.", [f"base {base} != revision {rev_now}"])
    _require_repo(root)
    dirty = _dirty(root, rels)
    if dirty:
        raise ChannelFault(409, "dirty",
                           "В файлах канала есть изменения, которых нет в git (правка руками?). "
                           "Центр не будет их перезаписывать: сохраните их коммитом или "
                           "отмените, потом повторите.", dirty)


def _refuse_invalid(cid, errs):
    rows = _error_rows(cid, errs)
    raise ChannelFault(422, "invalid",
                       f"Фабрика не приняла правку: {len(errs)} "
                       f"{'ошибка' if len(errs) == 1 else 'ошибки' if len(errs) < 5 else 'ошибок'}"
                       f" проверки. Ничего не сохранено.", [r["text"] for r in rows],
                       errors=rows)


def _identity_errors(cfg_now, cfg):
    bad = []
    for key, why in (("channel_id", "имя канала меняется переименованием, не правкой"),
                     ("stance", "путь к файлу позиции меняется в репозитории, не из центра")):
        if cfg_now.get(key) != cfg.get(key):
            bad.append(f"{key}: {why}")
    return bad


def save(root, name, body):
    """Check -> write -> one commit. Returns the commit and the channel now."""
    cid = _channel(root, name)
    with _WRITE:
        raw, cfg_now, sp, sraw_now, rev = _state(root, cid)
        craw, cfg, sraw, stance = _candidate(body, raw, sraw_now, cid)
        cfg = cfg if cfg is not None else cfg_now
        if stance is not None and sp is None:
            raise ChannelFault(422, "no_stance",
                               "У канала нет файла позиции (поле «stance» конфига) - "
                               "сохранять позицию некуда.")
        bad = _identity_errors(cfg_now, cfg)
        if bad:
            raise ChannelFault(422, "forbidden_change",
                               "Эти поля из центра не меняются: " + "; ".join(bad) + ".", bad)
        old_stance = json.loads(sraw_now) if sraw_now is not None else None
        changed = _paths_changed(cfg_now, cfg) if craw != raw else []
        if sraw != sraw_now and stance is not None:
            changed += [f"позиция.{p}" if p != "(весь файл)" else "позиция"
                        for p in _paths_changed(old_stance, stance)]
        writes = {}
        if craw != raw:
            writes[_config_path(root, cid)] = craw
        if sraw != sraw_now:
            writes[sp] = sraw
        if not writes:
            raise ChannelFault(400, "nothing_changed", "Изменений нет - сохранять нечего.")
        rels = [_rel(root, p) for p in writes]
        _guard_write(root, cid, body.get("base"), rev, rels)
        errs = _check(root, cid, cfg, stance if stance is not None else old_stance, sraw)
        if errs:
            _refuse_invalid(cid, errs)
        changed = changed or ["форматирование"]
        label = cfg.get("display_name") or cid
        subject = f"Канал {label}: изменено {_names(changed)} (из центра)"
        body_text = "Изменено:\n" + "\n".join(f"- {p}" for p in changed)
        note = (body.get("note") or "").strip()
        if note:
            body_text += f"\n\n{note}"
        message = f"{subject}\n\n{body_text}\n\n{_trailers(cid, 'edit')}\n"
        sha = _write_and_commit(root, cid, writes, message)
    return {"commit": sha, "subject": subject, "changed": changed, "files": rels,
            "channel": detail(root, cid)}


# ---------------------------------------------------------------- history
def _channel_rels(root, cid):
    """The files whose commits are the channel's history: the config, the position."""
    _, cfg, sp, _, _ = _state(root, cid)
    rels = [_rel(root, _config_path(root, cid))]
    if sp:
        rels.append(_rel(root, sp))
    return rels


def _log(root, rels, limit, rev=None):
    fmt = (f"%x1e%H%x1f%h%x1f%aI%x1f%an%x1f%s%x1f%(trailers:key={ACTION_TRAILER},valueonly,"
           f"separator=%x2C)%x1f%(trailers:key={REVERTS_TRAILER},valueonly,separator=%x2C)%x1f")
    args = ["log", f"-n{int(limit)}", f"--format={fmt}", "--name-only", "--full-diff",
            "--relative"]
    if rev:
        args.append(rev)
    cp = _git(root, *args, "--", *rels, check=False)
    if cp.returncode != 0:
        return []
    out = []
    for chunk in cp.stdout.split("\x1e")[1:]:
        parts = chunk.split("\x1f")
        if len(parts) < 8:
            continue
        sha, short, at, author, subject, action, reverts, files = parts[:8]
        out.append({"commit": sha, "short": short, "at": at, "author": author,
                    "subject": subject, "action": action.strip() or None,
                    "reverts": reverts.strip() or None,
                    "files": [f for f in files.strip().splitlines() if f.strip()]})
    return out


def history(root, name, limit=50):
    cid = _channel(root, name)
    rels = _channel_rels(root, cid)
    _require_repo(root)
    limit = max(1, min(int(limit), HISTORY_LIMIT))
    rows = _log(root, rels, limit)
    reverted = {r["reverts"]: r["commit"] for r in rows if r["reverts"]}
    mine = set(rels)
    entries = []
    for r in rows:
        only_mine = bool(r["files"]) and set(r["files"]) <= mine
        created = r["action"] == "create"
        entries.append(dict(r, from_center=r["action"] is not None,
                            revertible=only_mine and not created and r["commit"] not in reverted,
                            why_not=None if only_mine and not created else
                            "этим коммитом канал создан - отменять нечего; удаляется канал в "
                            "репозитории, не из центра" if created else
                            "в этом коммите менялись и другие файлы фабрики - отменить "
                            "только правку канала нельзя",
                            reverted_by=reverted.get(r["commit"])))
        if r["commit"] in reverted and only_mine:
            entries[-1]["why_not"] = "уже возвращено"
    return {"id": cid, "files": rels, "entries": entries}


def revert(root, name, commit, base=None):
    """One commit of the channel's history undone by a new commit."""
    cid = _channel(root, name)
    with _WRITE:
        raw, cfg_now, sp, sraw_now, rev = _state(root, cid)
        rels = _channel_rels(root, cid)
        _require_repo(root)
        cp = _git(root, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", check=False)
        sha = cp.stdout.strip()
        rows = _log(root, rels, 1, rev=sha) if sha else []
        if not rows or rows[0]["commit"] != sha:
            raise ChannelFault(404, "unknown_commit",
                               "Такой правки нет в истории этого канала.",
                               [f"{commit}: not a commit touching {', '.join(rels)}"])
        row = rows[0]
        if not set(row["files"]) <= set(rels):
            raise ChannelFault(409, "not_revertible",
                               "В этом коммите менялись и другие файлы фабрики - отменить только "
                               "правку канала нельзя. Это делается в репозитории.", row["files"])
        if _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^", check=False).returncode:
            raise ChannelFault(409, "not_revertible",
                               "Это первая версия файла - отменять её нечем.", [sha])
        status = _git(root, "diff", "--name-status", "--relative", f"{sha}^", sha, "--",
                      *rels).stdout.split()
        if any(s not in ("M",) for s in status[0::2]):
            raise ChannelFault(409, "not_revertible",
                               "Этот коммит создал или удалил файл канала - вернуть его из центра "
                               "нельзя.", status)
        _guard_write(root, cid, base, rev, rels)
        new = _reverse_merge(root, rels, sha)
        craw = new.get(rels[0], raw)
        cfg = _parse(craw, "Конфиг после отмены")
        sraw = new.get(rels[1]) if len(rels) > 1 and rels[1] in new else sraw_now
        try:
            stance = json.loads(sraw) if sraw is not None else None
        except ValueError:
            stance = None                   # `_check` says it: stance_unreadable
        bad = _identity_errors(cfg_now, cfg)
        if bad:
            raise ChannelFault(422, "forbidden_change",
                               "Отмена изменила бы поля, которые из центра не меняются: "
                               + "; ".join(bad) + ".", bad)
        errs = _check(root, cid, cfg, stance, sraw)
        if errs:
            _refuse_invalid(cid, errs)
        changed = _paths_changed(cfg_now, cfg)
        if sraw != sraw_now and stance is not None:
            changed += [f"позиция.{p}" for p in _paths_changed(json.loads(sraw_now), stance)]
        writes = {}
        if craw != raw:
            writes[_config_path(root, cid)] = craw
        if sraw != sraw_now:
            writes[sp] = sraw
        if not writes:
            raise ChannelFault(400, "nothing_changed",
                               "Файлы канала уже такие, какими были до этой правки.")
        changed = changed or ["форматирование"]
        label = cfg.get("display_name") or cid
        subject = (f"Канал {label}: возвращено {_names(changed)} - отмена правки "
                   f"{row['short']} (из центра)")
        message = (f"{subject}\n\nОтменена правка «{row['subject']}».\n"
                   f"This reverts commit {sha}.\n\n{_trailers(cid, 'revert', sha)}\n")
        new_sha = _write_and_commit(root, cid, writes, message)
    return {"commit": new_sha, "subject": subject, "changed": changed,
            "files": [_rel(root, p) for p in writes], "channel": detail(root, cid)}


def _reverse_merge(root, rels, sha):
    """{rel: bytes} - the files as they are now with the change of `sha` taken
    back: `git merge-file` of (now, as of sha, as before sha) - the three-way
    merge `git revert` does - on copies, the tree untouched. A conflict (the
    same lines changed again later) is a refusal."""
    out = {}
    with tempfile.TemporaryDirectory(prefix="cc-revert-") as tmp:
        for i, rel in enumerate(rels):
            at = _git(root, "show", f"{sha}:./{rel}", check=False)
            before = _git(root, "show", f"{sha}^:./{rel}", check=False)
            if at.returncode or before.returncode or at.stdout == before.stdout:
                continue
            ours, base, theirs = (Path(tmp) / f"{i}.{n}" for n in ("now", "at", "before"))
            ours.write_bytes(_read(Path(root) / rel) or b"")
            base.write_text(at.stdout, encoding="utf-8")
            theirs.write_text(before.stdout, encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env.update(factory.git_read().GIT_READ_ENV)   # CC-0119: no optional locks either
            cp = subprocess.run(["git", "merge-file", "-p", "-q", str(ours), str(base), str(theirs)],
                                capture_output=True, env=env, timeout=GIT_TIMEOUT)
            if cp.returncode != 0:
                raise ChannelFault(409, "not_revertible",
                                   "Эту правку нельзя отменить отдельно: те же строки потом "
                                   "менялись ещё раз. Сначала верните более поздние правки.",
                                   [f"git merge-file {rel}: exit {cp.returncode} "
                                    f"(conflicts or error)"])
            out[rel] = cp.stdout
    return out


# ---------------------------------------------------------------- a new channel (CC-0008)
#: Names a channel cannot take: the routes of this API under /channels/.
RESERVED_IDS = ("template", "new")   # `new`: the center's /channels/new is the wizard
CREATE_INPUTS = ("channel_id", "display_name", "language")


def create_lock(root, fresh=False):
    """{locked, message, batches, checked_at, age_s, checking}: any batch or
    rebuild going blocks a new channel."""
    rows, meta = _open_batches(root, fresh)
    if not rows:
        return dict(meta, locked=False, message=None, batches=[])
    first = rows[0]
    what = ("пересборка роликов" if first["rebuild"] else
            f"батч канала {first['channel']} ({Path(first['dir']).name})")
    return dict(meta, locked=True, batches=rows,
                message=f"Идёт {what}: пока не закончится, канал не создать - коммит "
                        f"нового канала сдвинул бы код фабрики под идущим батчем "
                        f"(runlog записал бы это как code_drift).")


def _created(res, rows, lk, dry):
    files = [{"path": rel, "text": data.decode("utf-8")} for rel, data in res["files"].items()]
    return {"ok": not rows, "dry_run": dry, "channel_id": res["channel_id"], "files": files,
            "errors": rows, "lock": lk, "commit": None, "subject": None, "channel": None}


def template(root):
    """What the wizard needs: the factory's template, and whether a channel can
    be created right now."""
    return dict(factory.channel_template(), lock=create_lock(root))


def _created_dirs(root, rels):
    """The directories a write of `rels` would make, deepest first."""
    out = []
    for rel in rels:
        d = (Path(root) / rel).parent
        while not d.exists() and d not in out:
            out.append(d)
            d = d.parent
    return sorted(out, key=lambda p: len(p.parts), reverse=True)


def _new_channel(root, body):
    """The factory's check of a new channel, nothing written: (res, rows) -
    `res` of `factory.new_channel_check` with the position the wizard sends
    (`stance_text`, CC-0041) in place of the template's, `rows` every refusal."""
    values = {k: body.get(k) for k in CREATE_INPUTS}
    res = factory.new_channel_check(root, values, reserved=RESERVED_IDS)
    cid = res["channel_id"]
    errs = list(res["errors"])
    text = body.get("stance_text")
    if text is not None and res["files"]:
        cfg_rel = next(iter(res["files"]))
        cfg = json.loads(res["files"][cfg_rel])
        sp = _stance_path(root, cid, cfg)
        rel = _rel(root, sp) if sp else None
        if rel not in res["files"]:
            # the API's own guard; the factory's line when it has one (it is
            # already among the findings then), else the API's under its check
            if not any(e["code"] == "template_stance_path" for e in errs):
                errs += factory.stance_path_findings(
                    cid, cfg, f"stance.json: the template's config names no position file "
                              f"({rel!r}) - nowhere to write the position")
        else:
            raw = text.encode("utf-8")
            errs = [e for e in errs if not factory.is_stance_check(e)]
            errs += factory.stance_text_findings(cid, raw)[1]
            res = dict(res, files=dict(res["files"], **{rel: raw}))
    return res, _input_rows(res["input_errors"]) + _error_rows(cid, errs)


def create(root, body):
    """Check -> (dry run: say it) -> write -> one commit. A dry run takes no
    lock and reads the last known open batches (`BATCH_TTL`); a create checks
    again under `_WRITE`, the open batches scanned afresh."""
    dry = bool(body.get("dry_run"))
    if dry:
        res, rows = _new_channel(root, body)
        return _created(res, rows, create_lock(root), dry=True)
    with _WRITE:
        res, rows = _new_channel(root, body)
        cid = res["channel_id"]
        lk = create_lock(root, fresh=True)
        out = _created(res, rows, lk, dry=False)
        if lk["locked"]:
            raise ChannelFault(409, "batch_running", lk["message"],
                               [b["dir"] for b in lk["batches"]], batches=lk["batches"])
        if rows:
            raise ChannelFault(422, "invalid",
                               f"Фабрика не приняла новый канал: {len(rows)} "
                               f"{'ошибка' if len(rows) == 1 else 'ошибки' if len(rows) < 5 else 'ошибок'}"
                               f" проверки. Ничего не создано.",
                               [r["text"] for r in rows], errors=rows)
        _require_repo(root)
        rels = list(res["files"])
        dirty = _dirty(root, rels)
        if dirty:
            raise ChannelFault(409, "dirty", "На месте файлов нового канала уже что-то есть "
                               "(не в git?). Центр не будет это перезаписывать.", dirty)
        label = res["values"]["display_name"]
        subject = f"Канал {label}: создан (из центра)"
        message = (f"{subject}\n\nСоздан по шаблону фабрики (shared/channel_template, "
                   f"shared/new_channel.py). Конвейера нет, в расписании выключен "
                   f"(batch_schedule.enabled: false).\n\nФайлы:\n"
                   + "\n".join(f"- {r}" for r in rels)
                   + ("\n\nПозиция - из мастера центра." if body.get("stance_text") is not None
                      else "")
                   + f"\n\n{_trailers(cid, 'create')}\n")
        made = _created_dirs(root, rels)
        for d in reversed(made):
            d.mkdir()
        try:
            sha = _write_and_commit(root, cid, {Path(root) / r: res["files"][r] for r in rels},
                                    message)
        except BaseException:
            for d in made:
                try:
                    d.rmdir()
                except OSError:
                    pass
            raise
    return dict(out, ok=True, commit=sha, subject=subject, channel=detail(root, cid))
