#!/usr/bin/env python3
"""CF-0747: the publication card from the command center - built by itself on
the acceptance, built again on the user's press, and taken by the user's
ruling when only the video's own words failed the claim check.

Why (13.10): five Reel videos were accepted in the center and none had a card,
because only the operator ran `publish_card.py build` (a model draft and the
claim check of CF-0555); the center's card/place answered «карточки нет -
сначала её собирают». One card came out not ready only from a failed claim of
the video's own narration (the-social-reckoning) - the user said «ролик мы
берем, описание и название подогнать под правду», and the driver had to copy
the card into publish/ by hand, because `place` refuses a card that is not
ready.

**The build** is `publish_card.py build` run as a detached process with its
own log (the pattern of `agents/analyst/studio_center.py`): `card_build_launch`
starts it and answers at once, `card_build_result` reads how it ended. One
build per video at a time (`running`); on the automatic path a card already
ready (or ruled) for the same script is not built again (`skipped`). The
build is the operator's own: the model drafts the title/description/tags and
the claim check runs; a draft `{title, about, hashtags, tags}` from the
center/user goes in as `--draft` (the model then only checks the claims).

**On the acceptance** (`shared/runlog/acceptance.py` `_queue_verdict`: where
CF-0738 puts an accepted video into `publish/<channel>/_queue/`) `on_accepted`
starts the build - never raises, never holds the verdict. `PUBLISH_CARD_AUTOBUILD=0`
switches the automatic start off (the test runners do: no test starts a
model by accident). CF-0891: the row being recorded is passed along
(`accepted_row`) - a video refused after its render (`05 -> refusals[]`) that
the user accepted all the same is built from its refusal record
(`publish_card.refused_video`) although the record on disk does not carry the
verdict yet; a build that does not start says why (stderr, `short()["why"]`,
and `acceptance.card_not_started` in the acceptance's commit and CLI).

**The user's ruling** (`ruling_plan` / `ruling_confirm`): a card built not
ready ONLY because claims of the video's own narration/on-screen text failed
(`publish_card.ruling_check`: never when a title/description/tag claim failed
or for any other problem) is taken by the user's words: `## Решение
пользователя` (words, by, via, time, the failing claims) is written into the
card, and the card goes next to the video in publish/ (its `## Публикация` kept
when a note was already there). `publish_card.card_status` then says `ruled`,
and the placing paths (`publish_card.place`, `publish_stash.py`,
`studio_fields.py`, `upload.py`) take it like a ready one.

Python (the center's api/ loads this file by path):

    card_build_launch(channel, slug, by, via, batch_id=None, draft=None, root=None,
                      auto=False, batch_dir=None, now=None, environ=None, python=None)
        -> {ok, launched, skipped, task, channel, slug, batch_id, batch_dir, by,
            via, run_id, pid, log, argv, draft, card {state, path}, refusals
            [{code, line}], lines}
        refusal codes: BUILD_REFUSALS; `skipped` (ok, nothing started):
        BUILD_SKIPS - `running` (a build of this video is going; only on the
        automatic path - a press while one runs is the refusal `running`),
        `ready` / `ruled` (the card of this script is already there; only on
        the automatic path - a press builds it again).
    card_build_result(ref, root=None, environ=None)
        -> {run_id, log, code, done, line, detail, exit, state, reasons, path,
            channel, slug, batch_id, started_at, finished_at}
        ref: the run id the launch answered, or its log's path. Codes:
        OUTCOMES - ready (готова), not_ready (собрана, не готова), refused
        (не собрана), not_asked (модель не ответила), error, running.
    card_info(channel, slug, batch_id=None, root=None, batch_dir=None)
        -> {channel, slug, batch_id, path, state, placeable, why, reasons,
            ruling, build}   state: none | building | ready | ruled | not_ready
    ruling_plan(channel, slug, batch_id, by=None, via=None, words=None, root=None, now=None)
    ruling_confirm(channel, slug, batch_id, base_sha256, by, via, words, root=None, now=None)
        -> the CF-0726 shape: {ok, written, dry_run, task, channel, slug,
           batch_id, by, via, words, base_sha256, sha256, new_sha256, commit
           (None), failing [{code, where, video, text}], card (the batch's
           card), path (the note in publish/), state, refusals [{code, line}],
           lines, touched [path]}
        refusal codes: RULING_REFUSALS.

CLI:

    python3 agents/publisher/card_center.py build --channel C --batch B SLUG --by WHO --via WHAT
        [--draft FILE.json] [--root DIR] [--json]
    python3 agents/publisher/card_center.py result RUN_ID|LOG [--root DIR] [--json]
    python3 agents/publisher/card_center.py state --channel C --batch B SLUG [--root DIR]
    python3 agents/publisher/card_center.py ruling-plan --channel C --batch B SLUG
        [--by WHO --via WHAT --words TEXT] [--root DIR] [--json]
    python3 agents/publisher/card_center.py ruling-confirm --channel C --batch B SLUG
        --base-sha256 H --by WHO --via WHAT --words TEXT [--root DIR] [--json]
        # exit 0 ok, 1 refused, 2 bad call

**State** (gitignored, `<root>/schedule/publish-card/`, or
`PUBLISH_CARD_STATE_DIR`): `runs/<run_id>.json` (who, when, pid, the video),
`runs/<run_id>.log` (the build's output), `runs/<run_id>.draft.json` (the
center's draft), `runs/<run_id>.result.json` (how it ended), `.lock`.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import acceptance                                               # noqa: E402
import publish_card as pc                                       # noqa: E402
import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402

TASK = "CF-0747"
STATE_ENV = "PUBLISH_CARD_STATE_DIR"
STATE_DIR = Path("schedule") / "publish-card"
RUNS_DIR = "runs"
LOCK_FILE = ".lock"
AUTOBUILD_ENV = "PUBLISH_CARD_AUTOBUILD"      # 0/off/no: the acceptance starts no build
PYTHON_ENV = "PUBLISH_CARD_PYTHON"            # the interpreter of the detached build
WHO_MAX = 40
WORDS_MAX = 1000
AUTO_BY, AUTO_VIA = "приёмка", "acceptance"

BUILD_REFUSALS = ("bad_who", "unknown_channel", "batch_missing", "unknown_video",
                  "bad_draft", "running", "spawn_failed")
BUILD_SKIPS = ("running", "ready", "ruled", "off")
OUTCOMES = ("ready", "not_ready", "refused", "not_asked", "error", "running")
OUTCOME_WORDS = {"ready": "карточка готова", "not_ready": "карточка собрана, но не готова",
                 "refused": "карточка не собрана", "not_asked": "модель не ответила",
                 "error": "ошибка сборки", "running": "карточка собирается"}
EXIT_CODES = {pc.EXIT_READY: "ready", pc.EXIT_NOT_READY: "not_ready",
              pc.EXIT_REFUSED: "refused", pc.EXIT_NOT_ASKED: "not_asked"}
RULING_REFUSALS = ("bad_who", "bad_words", "unknown_channel", "batch_missing", "unknown_video",
                   "not_accepted", "building", "no_card", "card_ready", "claims_not_failed",
                   "failing_unknown", "note_claim_failed", "card_problem", "no_video",
                   "check_changed", "place_failed")
RESULT_RE = re.compile(r"^PUBLISH_CARD_RESULT:\s*(ready|not_ready|refused|not_asked|error)\b"
                       r"\s*[-—:]*\s*(.*)$", re.M)
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$")


# ------------------------------------------------------------------ helpers

def _root(root=None):
    return Path(root or ROOT).absolute()


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc)
    return datetime.fromisoformat(str(now).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel(path, root):
    if path is None:
        return None
    try:
        return str(Path(path).absolute().relative_to(Path(root).absolute()))
    except ValueError:
        try:
            return str(Path(path).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            return str(path)


def state_dir(root=None, environ=None):
    env = os.environ if environ is None else environ
    if env.get(STATE_ENV):
        return Path(env[STATE_ENV]).expanduser()
    return _root(root) / STATE_DIR


@contextlib.contextmanager
def _locked(root=None, environ=None):
    d = state_dir(root, environ)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / LOCK_FILE, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read_json(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _write_json_atomic(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _who(value, what):
    if not isinstance(value, str) or not value.strip():
        return f"{what}={value!r}: a press is somebody's - a short non-empty string"
    if len(value.strip()) > WHO_MAX or any(c in value for c in "\r\n\t"):
        return f"{what}={value!r}: at most {WHO_MAX} characters on one line"
    return None


def _channel(channel, root):
    """Today's id of `channel`, or None when it has no `channels/<id>.json`."""
    spec = importlib.util.spec_from_file_location("channel_ids_card_center",
                                                  ROOT / "shared" / "channel_ids.py")
    ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ids)
    cid = ids.resolve_channel(channel, root)
    return cid if cid and ids.channel_config_path(cid, root).is_file() else None


def _log_path(root):
    return _root(root) / acceptance.ACCEPTANCE_LOG_REL


def _vouched(row):
    """CF-0891: the row of a verdict `accepted` being recorded right now."""
    return isinstance(row, dict) and row.get("verdict") == acceptance.ACCEPTED


def _video(channel, slug, batch_id, root, batch_dir=None, accepted_row=None):
    """`(cid, batch_dir, row, script_id, refusal)` of one video - refusal is
    `(code, line)` or None. `accepted_row`: the row whose verdict `accepted`
    is being recorded right now (`on_accepted` - the record on disk does not
    carry it yet); a video refused after its render then still gets its card
    (CF-0891, `publish_card.refused_video`)."""
    cid = _channel(channel, root)
    if cid is None:
        return None, None, None, None, ("unknown_channel", f"{channel!r}: no channels/<id>.json")
    row = None
    if batch_id:
        try:
            row = acceptance.find(cid, batch_id, slug, path=_log_path(root))
        except acceptance.AcceptanceError:
            row = None
    if row is None and _vouched(accepted_row):
        row = accepted_row
    b = acceptance.batch_dir_of_row(row or {"channel": cid, "batch_id": batch_id, "slug": slug},
                                    root=root, batch_dir=batch_dir)
    if b is None:
        return cid, None, row, None, ("batch_missing", f"{slug}: the batch {batch_id} is not "
                                                       f"on disk (pipeline/*/{batch_id})")
    try:
        _ch, script, _v, real = pc.batch_video(b, slug, root=root,
                                                accepted=_vouched(accepted_row) or None)
    except pc.CardError as e:
        return cid, b, row, None, ("unknown_video", str(e))
    if real != slug:
        return cid, b, row, None, ("unknown_video", f"{slug}: the batch's video is {real!r}")
    return cid, b, row, script.get("script_id"), None


def card_path(batch_dir, slug):
    return Path(batch_dir) / pc.CARD_DIR / f"{slug}.md"


# ------------------------------------------------------------------ the runs

def _alive(pid):
    if not pid:
        return False
    try:
        got, _status = os.waitpid(int(pid), os.WNOHANG)     # our own child: reap it
        if got:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _runs(root=None, environ=None):
    d = state_dir(root, environ) / RUNS_DIR
    if not d.is_dir():
        return []
    rows = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith((".result.json", ".draft.json")):
            continue
        doc = _read_json(p)
        if doc and doc.get("task") == TASK and doc.get("run_id") == p.stem:
            rows.append(doc)
    rows.sort(key=lambda r: (str(r.get("started_at") or ""), r["run_id"]))
    return rows


def _log_text(log):
    if not log:
        return ""
    try:
        return Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _finished(rec):
    return _read_json(Path(rec["log"]).with_suffix(".result.json")) if rec.get("log") else None


def _is_running(rec):
    return _finished(rec) is None and not RESULT_RE.search(_log_text(rec.get("log"))) \
        and _alive(rec.get("pid"))


def _same_video(rec, batch_dir, slug):
    return rec.get("slug") == slug and \
        Path(str(rec.get("batch_dir") or "")).resolve() == Path(batch_dir).resolve()


def running_build(batch_dir, slug, root=None, environ=None):
    """The run id of a build of this video still going, or None."""
    for r in reversed(_runs(root, environ)):
        if _same_video(r, batch_dir, slug) and _is_running(r):
            return r["run_id"]
    return None


def last_run(batch_dir, slug, root=None, environ=None):
    """The last build of this video from here: `{run_id, log, code, started_at,
    by, via, auto}` or None."""
    for r in reversed(_runs(root, environ)):
        if _same_video(r, batch_dir, slug):
            res = card_build_result(r["run_id"], root, environ)
            return {"run_id": r["run_id"], "log": r.get("log"), "code": res["code"],
                    "started_at": r.get("started_at"), "by": r.get("by"), "via": r.get("via"),
                    "auto": bool(r.get("auto"))}
    return None


def _new_run_id(d, slug, now):
    base = f"{slug}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    run_id, n = base, 1
    while (d / f"{run_id}.json").exists() or (d / f"{run_id}.log").exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


def _python(python=None, environ=None):
    env = os.environ if environ is None else environ
    return str(python or env.get(PYTHON_ENV) or sys.executable)


# ------------------------------------------------------------------ the build

def _card_state(batch_dir, slug):
    p = card_path(batch_dir, slug)
    if not p.is_file():
        return {"state": "none", "path": None, "script_id": None}
    text = p.read_text(encoding="utf-8")
    st = pc.card_status(text)
    return {"state": st["state"], "path": str(p),
            "script_id": (pc.mark_of(text) or {}).get("script_id")}


def card_build_launch(channel, slug, by, via, batch_id=None, draft=None, root=None, auto=False,
                      batch_dir=None, now=None, environ=None, python=None, accepted_row=None):
    """Start `publish_card.py build` for one video as a detached process with
    its own log. The answer is a dict, never an exception for a refusal (see
    the module's docstring). `accepted_row`: see `_video` (CF-0891) - the run
    record keeps `accepted: true` and the detached build is told so."""
    root = _root(root)
    now = _now(now)
    out = {"ok": False, "launched": False, "skipped": None, "task": TASK, "channel": channel,
           "slug": slug, "batch_id": batch_id, "batch_dir": None, "by": by, "via": via,
           "run_id": None, "pid": None, "log": None, "argv": None, "draft": None,
           "card": None, "refusals": [], "lines": []}

    def refuse(code, line):
        out["refusals"].append({"code": code, "line": line})

    def done():
        if out["refusals"]:
            out["lines"].insert(0, "отказ: " + out["refusals"][0]["line"])
        return out

    for why in (_who(by, "by"), _who(via, "via")):
        if why:
            refuse("bad_who", why)
    cid, b, _row, script_id, bad = _video(channel, slug, batch_id, root, batch_dir,
                                          accepted_row=accepted_row)
    if cid:
        out["channel"] = cid
    if bad:
        refuse(*bad)
    if draft is not None:
        problems = pc.validate_draft(draft) if isinstance(draft, dict) else \
            ["the draft is an object {title, about, hashtags, tags}"]
        if problems:
            refuse("bad_draft", "the draft: " + "; ".join(problems))
    if out["refusals"]:
        return done()
    out["batch_dir"] = _rel(b, root)
    if batch_id is None:
        out["batch_id"] = b.name
    with _locked(root, environ) as d:
        card = _card_state(b, slug)
        out["card"] = {"state": card["state"], "path": _rel(card["path"], root)}
        going = running_build(b, slug, root, environ)
        if going:
            if auto:
                out.update(ok=True, skipped="running")
                out["lines"].append(f"{slug}: карточка уже собирается (запуск {going})")
                return out
            refuse("running", f"{slug}: карточка уже собирается (запуск {going}) - "
                              f"дождитесь итога")
            return done()
        if auto and card["state"] in (pc.READY, pc.RULED) and card["script_id"] == script_id:
            out.update(ok=True, skipped=card["state"])
            out["lines"].append(f"{slug}: карточка этого сценария уже "
                                + ("готова" if card["state"] == pc.READY
                                   else "принята решением пользователя") + " - не пересобираю")
            return out
        runs = d / RUNS_DIR
        runs.mkdir(parents=True, exist_ok=True)
        run_id = _new_run_id(runs, slug, now)
        log = runs / f"{run_id}.log"
        draft_path = None
        if draft is not None:
            draft_path = runs / f"{run_id}.draft.json"
            _write_json_atomic(draft_path, draft)
        out["argv"] = [_python(python, environ), str(Path(__file__).resolve()), "run", run_id]
        rec = {"run_id": run_id, "task": TASK, "started_at": _iso(now), "by": by.strip(),
               "via": via.strip(), "auto": bool(auto), "channel": cid, "slug": slug,
               "batch_id": out["batch_id"], "batch_dir": str(b), "root": str(root),
               "script_id": script_id, "draft": str(draft_path) if draft_path else None,
               **({"accepted": True} if _vouched(accepted_row) else {}),
               "pid": None, "argv": out["argv"], "log": str(log)}
        _write_json_atomic(runs / f"{run_id}.json", rec)
        env = dict(os.environ if environ is None else environ)
        env[STATE_ENV] = str(d)
        try:
            with open(log, "ab") as fh:
                proc = subprocess.Popen(out["argv"], stdin=subprocess.DEVNULL, stdout=fh,
                                        stderr=subprocess.STDOUT, cwd=str(root), env=env,
                                        start_new_session=True, close_fds=True)
        except OSError as e:
            (runs / f"{run_id}.json").unlink(missing_ok=True)
            refuse("spawn_failed", f"сборка не стартовала ({e})")
            return done()
        rec["pid"] = proc.pid
        _write_json_atomic(runs / f"{run_id}.json", rec)
    out.update(ok=True, launched=True, run_id=run_id, pid=proc.pid, log=str(log),
               draft=str(draft_path) if draft_path else None)
    out["lines"].append(f"{slug}: карточка собирается (pid {proc.pid}, журнал {log})"
                        + (" из черновика центра" if draft_path else ""))
    return out


def run(run_id, environ=None):
    """The detached build itself (`card_center.py run RUN_ID`): `publish_card.py
    build` in this process, then the result file and the marker line."""
    d = state_dir(None, environ) / RUNS_DIR
    rec = _read_json(d / f"{run_id}.json")
    if not rec:
        print(f"PUBLISH_CARD_RESULT: error - no run {run_id} in {d}")
        return 2
    argv = ["build", rec["batch_dir"], rec["slug"], "--root", rec["root"], "--json"]
    if rec.get("draft"):
        argv += ["--draft", rec["draft"]]
    print(f"card_center: {' '.join(argv)}", flush=True)
    try:
        code = EXIT_CODES.get(pc.main(argv, accepted=True if rec.get("accepted") else None),
                              "error")
        detail = ""
    except SystemExit as e:                 # argparse
        code, detail = "error", f"exit {e.code}"
    except Exception as e:                                      # noqa: BLE001
        code, detail = "error", f"{e.__class__.__name__}: {e}"
    sys.stdout.flush()
    card = _card_state(rec["batch_dir"], rec["slug"])
    st = {"why": None, "reasons": []}
    if card["path"]:
        st = pc.card_status(Path(card["path"]).read_text(encoding="utf-8"))
    res = {"run_id": run_id, "code": code, "detail": detail, "state": card["state"],
           "why": st["why"], "reasons": st["reasons"], "path": card["path"],
           "finished_at": _iso(_now())}
    _write_json_atomic(d / f"{run_id}.result.json", res)
    print(f"PUBLISH_CARD_RESULT: {code}" + (f" - {detail}" if detail else ""), flush=True)
    return 0 if code in ("ready", "not_ready") else 1


def _run_of(ref, root=None, environ=None):
    ref = str(ref or "").strip()
    if not ref:
        return None, None
    runs = state_dir(root, environ) / RUNS_DIR
    if RUN_ID_RE.match(ref):
        rec = _read_json(runs / f"{ref}.json")
        return rec, Path(rec["log"]) if rec and rec.get("log") else runs / f"{ref}.log"
    p = Path(ref).expanduser()
    rec = _read_json(p.with_suffix(".json")) if p.suffix == ".log" else None
    return (rec if rec and rec.get("task") == TASK else None), p


def card_build_result(ref, root=None, environ=None):
    """How one build ended (see OUTCOMES)."""
    rec, log = _run_of(ref, root, environ)
    rec = rec or {}
    out = {"run_id": rec.get("run_id"), "log": str(log) if log else None, "code": "error",
           "done": True, "line": "", "detail": "", "exit": None, "state": None, "reasons": [],
           "path": None, "channel": rec.get("channel"), "slug": rec.get("slug"),
           "batch_id": rec.get("batch_id"), "started_at": rec.get("started_at"),
           "finished_at": None}
    text = _log_text(log)
    if log is None or (not text and not Path(log).exists()):
        out["detail"] = f"нет журнала сборки {ref!r}"
        out["line"] = f"{OUTCOME_WORDS['error']}: {out['detail']}"
        return out
    res = _read_json(Path(log).with_suffix(".result.json"))
    found = list(RESULT_RE.finditer(text))
    if res:
        code, detail = res.get("code") or "error", res.get("detail") or ""
        out.update(state=res.get("state"), reasons=res.get("reasons") or [],
                   path=_rel(res.get("path"), rec.get("root") or root or ROOT),
                   finished_at=res.get("finished_at"))
        if res.get("why") and code != "ready":
            detail = detail or res["why"]
    elif found:
        code, detail = found[-1].group(1), found[-1].group(2).strip()
    elif _alive(rec.get("pid")):
        code, detail = "running", "сборка ещё идёт"
    else:
        tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-1:] or ["журнал пуст"]
        code, detail = "error", f"сборка закончилась без итога ({tail[0][:160]})"
    if code == "refused" and not detail:
        lines = [ln for ln in text.splitlines() if ln.startswith("PUBLISH CARD:")]
        detail = lines[-1][len("PUBLISH CARD:"):].strip() if lines else ""
    out.update(code=code, done=code != "running", detail=detail)
    out["line"] = OUTCOME_WORDS[code] + (f": {detail}" if detail else "")
    return out


def card_info(channel, slug, batch_id=None, root=None, batch_dir=None, environ=None):
    """The card of one video as the center shows it (see the module's docstring)."""
    root = _root(root)
    cid, b, _row, _sid, bad = _video(channel, slug, batch_id, root, batch_dir)
    out = {"channel": cid or channel, "slug": slug, "batch_id": batch_id or (b.name if b else None),
           "path": None, "state": "none", "placeable": False, "why": None, "reasons": [],
           "ruling": None, "build": None, "refusals": []}
    if bad:
        out["refusals"].append({"code": bad[0], "line": bad[1]})
        if b is None:
            return out
    p = card_path(b, slug)
    if p.is_file():
        st = pc.card_status(p.read_text(encoding="utf-8"))
        out.update(path=_rel(p, root), state=st["state"], placeable=st["placeable"],
                   why=st["why"], reasons=st["reasons"],
                   ruling=st["ruling"] if st["state"] == pc.RULED else None)
    out["build"] = last_run(b, slug, root, environ)
    if out["build"] and out["build"]["code"] == "running":
        out["state"] = "building"
    return out


# ------------------------------------------------------------------ on the acceptance

def autobuild_on(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get(AUTOBUILD_ENV, "1")).strip().lower() not in ("0", "off", "no", "false")


def on_accepted(row, root=None, batch_dir=None, environ=None):
    """CF-0747: the accepted video's card is built by itself - a detached build
    (`card_build_launch(auto=True)`). Never raises: a failure is the answer."""
    try:
        if not autobuild_on(environ):
            return {"ok": True, "launched": False, "skipped": "off", "task": TASK,
                    "refusals": [], "lines": [f"{AUTOBUILD_ENV}=0: карточка сама не собирается"]}
        ans = card_build_launch(row.get("channel"), row.get("slug"), AUTO_BY, AUTO_VIA,
                                batch_id=row.get("batch_id"), root=root, auto=True,
                                batch_dir=batch_dir, environ=environ, accepted_row=row)
        if ans.get("refusals"):
            # CF-0891: a build that did not start says why, not silence
            print(f"CARD BUILD {row.get('channel')}/{row.get('batch_id')}/{row.get('slug')}: "
                  f"not started - {refusal_line(ans)}", file=sys.stderr)
        return ans
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "launched": False, "skipped": None, "task": TASK,
                "refusals": [{"code": "spawn_failed", "line": f"{e.__class__.__name__}: {e}"}],
                "lines": [f"сборка карточки не запущена: {e.__class__.__name__}: {e}"]}


def refusal_line(answer):
    """CF-0891: the refusals of a launch answer as one line, or None."""
    lines = [f"{r.get('code')}: {r.get('line')}" for r in (answer or {}).get("refusals") or []
             if isinstance(r, dict)]
    return "; ".join(lines) or None


def short(answer):
    """The launch answer in a few fields - what the acceptance's answer carries.
    CF-0891: `why` - the refusal's own line (a code alone told nobody why the
    card of an accepted video did not start)."""
    if not isinstance(answer, dict):
        return None
    return {k: answer.get(k) for k in ("ok", "launched", "skipped", "run_id", "log")} | {
        "refusals": [r.get("code") for r in answer.get("refusals") or []],
        "why": refusal_line(answer)}


# ------------------------------------------------------------------ the ruling

def _sha(card, note):
    h = hashlib.sha256()
    for p in (card, note):
        h.update(b"\0")
        if p is not None and Path(p).is_file():
            h.update(Path(p).read_bytes())
    return h.hexdigest()


def _ruling(channel, slug, batch_id, by, via, words, root, now, confirm, environ=None):
    """(answer, context) - the shared reading of plan and confirm."""
    out = {"ok": False, "written": False, "dry_run": not confirm, "task": TASK,
           "channel": channel, "slug": slug, "batch_id": batch_id, "by": by, "via": via,
           "words": words, "base_sha256": None, "sha256": None, "new_sha256": None,
           "commit": None, "failing": [], "card": None, "path": None, "state": None,
           "refusals": [], "lines": [], "touched": []}

    def refuse(code, line):
        out["refusals"].append({"code": code, "line": line})
    if confirm or by is not None or via is not None:
        for why in (_who(by, "by"), _who(via, "via")):
            if why:
                refuse("bad_who", why)
    if confirm or words is not None:
        if not isinstance(words, str) or not words.strip():
            refuse("bad_words", "words: the user's own words of the ruling - a non-empty text")
        elif len(words) > WORDS_MAX:
            refuse("bad_words", f"words: at most {WORDS_MAX} characters")
    cid, b, row, _sid, bad = _video(channel, slug, batch_id, root)
    if cid:
        out["channel"] = cid
    ctx = {"cid": cid, "batch_dir": b, "card": None, "note": None, "text": None, "entry": None}
    if bad:
        refuse(*bad)
        return out, ctx
    if (row or {}).get("verdict") != acceptance.ACCEPTED:
        refuse("not_accepted", f"{slug}: {(row or {}).get('verdict') or 'no verdict'} in the "
                               f"acceptance record - the ruling takes the card of an accepted "
                               f"video")
    going = running_build(b, slug, root, environ)
    if going:
        refuse("building", f"{slug}: the card is being built (run {going}) - wait for it")
    card = card_path(b, slug)
    ctx["card"] = card
    out["card"] = _rel(card, root)
    if not card.is_file():
        refuse("no_card", f"{slug}: no card - build it first")
    else:
        text = card.read_text(encoding="utf-8")
        ctx["text"] = text
        chk = pc.ruling_check(text)
        out["failing"] = chk["failing"]
        out["state"] = pc.card_status(text)["state"]
        out["refusals"] += chk["refusals"]
    # CF-0857: the video of THIS batch - a channel reuses names, the latest
    # place of the name may be another batch's video (23.10 Tech `anthropic`)
    try:
        entry, where = publish_layout.of_batch(slug, batch_id, root / "publish", cid, None,
                                               log_path=_log_path(root))
    except acceptance.AcceptanceError as e:
        entry, where = None, str(e)
    if not entry or not entry.get("mp4") or not Path(entry["mp4"]).is_file():
        refuse("no_video", f"{slug}: no video of batch {batch_id} in publish/{cid}/ - the card "
                           f"follows the accepted video (its place in the копилка)"
                           + (f" ({where})" if where else ""))
    else:
        ctx["entry"] = entry
        ctx["note"] = Path(entry["mp4"]).with_suffix(".md")
        out["path"] = _rel(ctx["note"], root)
    out["sha256"] = _sha(card, ctx["note"])
    return out, ctx


def _lines(out):
    if out["refusals"]:
        return ["отказ: " + r["line"] for r in out["refusals"]]
    head = ("решение записано" if out["written"] else "план: ничего не записано")
    lines = [f"{out['slug']}: {head} - карточка не готова только из-за утверждений самого "
             f"ролика:"]
    lines += [f"  `{f.get('code')}` [{f.get('where')}] {f.get('text') or ''}".rstrip()
              for f in out["failing"]]
    if out["path"]:
        lines.append(f"  карточка {'положена' if out['written'] else 'ляжет'} рядом с роликом: "
                     f"{out['path']}")
    return lines


def ruling_plan(channel, slug, batch_id, by=None, via=None, words=None, root=None, now=None,
                environ=None):
    """What the ruling would do - nothing written. `sha256` of the answer is the
    base `ruling_confirm` takes."""
    root = _root(root)
    out, _ctx = _ruling(channel, slug, batch_id, by, via, words, root, now, False, environ)
    out["base_sha256"] = out["sha256"]
    out["ok"] = not out["refusals"]
    out["lines"] = _lines(out)
    return out


def ruling_confirm(channel, slug, batch_id, base_sha256, by, via, words, root=None, now=None,
                   environ=None):
    """Write the ruling into the card and put the card next to the video in
    publish/ (its `## Публикация` kept when a note was there)."""
    root = _root(root)
    now = _now(now)
    with _locked(root, environ):
        out, ctx = _ruling(channel, slug, batch_id, by, via, words, root, now, True, environ)
        out["base_sha256"] = base_sha256
        if base_sha256 != out["sha256"] and not any(r["code"] in ("unknown_channel",
                                                                  "batch_missing",
                                                                  "unknown_video")
                                                    for r in out["refusals"]):
            out["refusals"].append({"code": "check_changed",
                                    "line": f"{slug}: the card or its note changed since the "
                                            f"plan ({base_sha256} -> {out['sha256']}) - plan "
                                            f"again"})
        if out["refusals"]:
            out["lines"] = _lines(out)
            return out
        text = ctx["text"]
        mark = pc.mark_of(text) or {}
        ruling = {"rule": pc.RULING_TASK, "words": words.strip(), "by": by.strip(),
                  "via": via.strip(), "at": _iso(now), "failing": out["failing"],
                  "channel": ctx["cid"], "slug": slug, "batch": mark.get("batch"),
                  "script_id": mark.get("script_id"), "built_at": mark.get("built_at"),
                  "fingerprint": pc.note_claims.fingerprint(text)}
        ruled = pc._replace_section(text, pc.RULING_SECTION, pc.ruling_section(ruling))
        note = ctx["note"]
        placed = ruled
        if note.is_file():
            body = publish_note.sections(note.read_text(encoding="utf-8")).get("Публикация")
            if body:
                placed = pc._replace_section(ruled, "Публикация", body)
        if pc.card_status(placed)["state"] != pc.RULED:
            out["refusals"].append({"code": "place_failed",
                                    "line": f"{slug}: the ruled card does not read as ruled "
                                            f"({pc.card_status(placed)['why']}) - nothing written"})
            out["lines"] = _lines(out)
            return out
        try:
            ctx["card"].write_text(ruled, encoding="utf-8")
            note.write_text(placed, encoding="utf-8")
        except OSError as e:
            out["refusals"].append({"code": "place_failed", "line": f"{slug}: {e}"})
            out["lines"] = _lines(out)
            return out
        out.update(written=True, state=pc.RULED, new_sha256=_sha(ctx["card"], note),
                   touched=sorted({_rel(ctx["card"], root), _rel(note, root)}))
        out["ok"] = True
        out["lines"] = _lines(out)
        return out


# ------------------------------------------------------------------ CLI

def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="card_center.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "result", "state", "ruling-plan", "ruling-confirm", "run"):
        p = sub.add_parser(name)
        if name == "run":
            p.add_argument("run_id")
            continue
        p.add_argument("--root", default=None)
        p.add_argument("--json", action="store_true")
        if name == "result":
            p.add_argument("ref", help="the run id or its log")
            continue
        p.add_argument("--channel", required=True)
        p.add_argument("--batch", required=True)
        p.add_argument("slug")
        if name == "build":
            p.add_argument("--by", required=True)
            p.add_argument("--via", required=True)
            p.add_argument("--draft", default=None, help="a JSON file {title, about, hashtags, tags}")
        if name.startswith("ruling"):
            req = name == "ruling-confirm"
            p.add_argument("--by", required=req)
            p.add_argument("--via", required=req)
            p.add_argument("--words", required=req)
            p.add_argument("--now", default=None)
            if req:
                p.add_argument("--base-sha256", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args.run_id)
    if args.cmd == "build":
        draft = None
        if args.draft:
            try:
                draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                out.write(f"refused: --draft {args.draft}: {e}\n")
                return 2
        res = card_build_launch(args.channel, args.slug, args.by, args.via, args.batch,
                                draft=draft, root=args.root)
    elif args.cmd == "result":
        res = card_build_result(args.ref, args.root)
    elif args.cmd == "state":
        res = card_info(args.channel, args.slug, args.batch, args.root)
    elif args.cmd == "ruling-plan":
        res = ruling_plan(args.channel, args.slug, args.batch, args.by, args.via, args.words,
                          args.root, args.now)
    else:
        res = ruling_confirm(args.channel, args.slug, args.batch, args.base_sha256, args.by,
                             args.via, args.words, args.root, args.now)
    if args.json:
        out.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    elif args.cmd == "result":
        out.write(f"{res['code']}: {res['line']}\n")
    elif args.cmd == "state":
        out.write(f"{res['slug']}: {res['state']}" + (f" ({res['why']})" if res["why"] else "")
                  + (f", журнал {res['build']['log']}" if res["build"] else "") + "\n")
    else:
        out.write("\n".join(res["lines"]) + "\n")
        if args.cmd == "ruling-plan":
            out.write(f"base_sha256 {res['sha256']}\n")
    if args.cmd == "result":
        return 0
    return 0 if res.get("ok", not res.get("refusals")) else 1


if __name__ == "__main__":
    sys.exit(main())
