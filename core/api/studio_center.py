"""CC-0120: the Studio read on the user's actions in the center (CF-0735) -
is a read due, the button «Прочитать Studio» (plan, then confirm), and what
the reading session came to. Only through the factory's own functions,
`agents/analyst/studio_center.py` loaded by path (`factory.studio_center`):

    studio_read_due(channel, hook, root)     GET /api/studio/due - due or not,
                                             why, the last read, each channel's
                                             row, a session still reading
    studio_read_launch(by="user", via="center", confirmed=False)
                                             POST /api/studio/read/plan - what
                                             would start, nothing started
    studio_read_launch(..., confirmed=True)  POST /api/studio/read {confirm} -
                                             the session started detached
    studio_read_result(run_id)               GET /api/studio/read/{run_id} -
                                             read / no_extension / login_needed
                                             / error / running

**The hook `center-first-open-of-day`** records the center's open (the
factory's small state file `schedule/studio-read/center-opens.json`, under its
lock) - the one write of the due read, so that hook asks may the API write
here (CC-0058, `require_writes` in the route); the other hooks and none only
read.

**The switch** (`STUDIO_READ_LAUNCH`, as `SIGNING` of `api/gate_prices.py`):
the first real `claude -p --chrome` is started only with the user present and
on his direct «да» (CF-0735). Until the switch is turned on here, by hand,
the confirm refuses 409 `launch_off` (LAUNCH_OFF_WHY) before a token is even
looked at, and the plan gives no token; the due read and the plan work and say
`launch: {available: false, why}`. It ships OFF; the test pins it.

**The confirm**: the token (action `studio_read_launch`, CONFIRM_TTL s, single
use) spent, the plan again (the same channels and command, else
`check_changed`), then the launch in a child of `api/child.py` (`_LAUNCHER`:
the factory's `studio_read_launch(confirmed=True)` with the plan's channels,
one JSON line out) - the factory starts the session in a session of its own
with the prompt on stdin and the log `schedule/studio-read/runs/<run_id>.log`,
and the child ends at once; the center never waits on the session nor signals
it. `run_launcher` is the seam of the tests: no test starts a real `claude`.

A factory refusal (`refusals[].code`: bad_who, no_channels, running,
no_claude, spawn_failed) is said in Russian (`REFUSALS`), its code in its own
field, the factory's line in `details`. Every refusal is a `BatchFault`
(`{message, code, details}`), every answer goes out through `api/paths.clean`.
`FACTORY_KW` holds the factory's injection points (`now`, `environ`,
`claude`) - empty in production.
"""
import json
import os
import re
import sys
import threading

from . import batches, child, factory, paths
from .batches import BatchFault, _digest, _issue, _spend

#: The switch: may the center start a real Studio read. Shipped OFF until the
#: user's «да» (CF-0735); ON since 2026-10-17 - the first read was made with the
#: user through the factory's chat, and his «включай чтение Studio из центра»,
#: confirmed «Да» in Telegram 17.10 09:07 MSK (hotfix v2.8.1).
STUDIO_READ_LAUNCH = True
LAUNCH_OFF_WHY = ("запуск чтения Studio из центра ещё не включён — первый запуск делается "
                  "вместе с пользователем")
ACTION = "studio_read_launch"
KEY = "factory"
batches.register_actions({ACTION: ("план чтения Studio", "чтение Studio не запущено",
                                   "запуска чтения Studio")})
BY, VIA = "user", "center"
LAUNCH_TIMEOUT_S = 30
POLL_S = 5
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$")
_LAUNCH = threading.Lock()  # one confirm at a time
#: The factory's injection points (now, environ, claude) - empty in production.
FACTORY_KW = {}

#: A refusal's code -> (HTTP status of a confirm, the Russian line).
REFUSALS = {
    "bad_who": (422, "Чтение Studio не запущено: не сказано, кто нажал кнопку и откуда "
                     "(by / via) - запуск должен быть чьим-то."),
    "no_channels": (409, "Читать нечего: ни у одного канала нет настроек чтения Studio "
                         "(analyst.studio_read в конфиге) или пайплайна."),
    "running": (409, "Чтение Studio уже идёт - дождитесь итога запуска, что идёт сейчас."),
    "no_claude": (409, "Не найден исполняемый claude - чтение Studio запустить нечем."),
    "spawn_failed": (500, "Сессия чтения Studio не стартовала - подробности ниже."),
}
#: The center's own refusals of these routes.
BAD_HOOK = "Неизвестный повод проверки «{hook}»: batch-start, upload, " \
           "center-first-open-of-day или без повода."
BAD_CHANNEL = "Канал «{channel}» не читается в Studio - подробности ниже."

# The launcher: the factory's confirmed launch with the plan's channels, one JSON line out.
_LAUNCHER = r"""
import importlib.util, json, sys
mod_path, root, claude, channels = sys.argv[1:4] + [json.loads(sys.argv[4])]
spec = importlib.util.spec_from_file_location("studio_center_for_the_center", mod_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = mod.studio_read_launch("user", "center", confirmed=True, root=root, channels=channels,
                             claude=claude or None)
print(json.dumps(out, ensure_ascii=False))
"""


def _sc():
    return factory.studio_center()


def _kw():
    return {"now": FACTORY_KW.get("now"), "environ": FACTORY_KW.get("environ")}


def launch_block():
    """{available, why, switch}: may the center start a read at all."""
    return {"available": bool(STUDIO_READ_LAUNCH),
            "why": None if STUDIO_READ_LAUNCH else LAUNCH_OFF_WHY,
            "switch": "STUDIO_READ_LAUNCH"}


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой: {what} - посмотрите "
                                             f"schedule/studio-read/, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


# ---------------------------------------------------------------- due
def due(root, channel=None, hook=None):
    """`studio_read_due(channel, hook)` + the switch. A bad hook or channel
    (`CenterError`) is 422 in Russian, the factory's line in `details`."""
    sc = _sc()
    channel = channel or None
    hook = hook or None
    try:
        got = sc.studio_read_due(channel, hook, root, **_kw())
    except sc.CenterError as e:
        if hook not in sc.HOOKS + (None,):
            raise BatchFault(422, "bad_hook", BAD_HOOK.format(hook=hook),
                             [str(e)]) from None
        raise BatchFault(422, "bad_channel", BAD_CHANNEL.format(channel=channel),
                         paths.clean([str(e)], root)) from None
    except OSError as e:
        raise _broken(e, "«пора ли» чтения Studio") from e
    return paths.clean(dict(got, hook_words={k or "none": v for k, v in sc.HOOK_WORDS.items()},
                            launch=launch_block()), root)


# ---------------------------------------------------------------- the plan
def _refusals(raw):
    return [{"code": r.get("code"), "line": r.get("line"),
             "message": REFUSALS.get(r.get("code"), (409, r.get("line") or ""))[1]}
            for r in raw or []]


def _plan_now(root):
    sc = _sc()
    try:
        return sc.studio_read_launch(BY, VIA, confirmed=False, root=root,
                                     claude=FACTORY_KW.get("claude"), **_kw())
    except OSError as e:
        raise _broken(e, "план чтения Studio") from e


def _fingerprint(got):
    return _digest({"action": ACTION, "channels": got.get("channels"), "argv": got.get("argv"),
                    "by": got.get("by"), "via": got.get("via")})


def read_plan(root):
    """What «Прочитать Studio» would start (the factory's plan, nothing
    started), the switch, and a confirm token when both say yes."""
    got = _plan_now(root)
    refusals = _refusals(got.get("refusals"))
    block = launch_block()
    ok = bool(got.get("ok")) and not refusals
    why = refusals[0]["message"] if refusals else block["why"]
    fp = _fingerprint(got)
    out = dict(got, action=ACTION, ok=ok, refusals=refusals, why=why, launch=block,
               fingerprint=fp, confirm=None, expires_in_s=None)
    if ok and block["available"]:
        out.update(confirm=_issue(root, ACTION, KEY, fp), expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


# ---------------------------------------------------------------- the confirm
def run_launcher(cmd, cwd, env):
    """The launch child (`child.run`, bounded by LAUNCH_TIMEOUT_S): (returncode,
    stdout, stderr). A seam of the tests - none of them starts a real claude."""
    return child.run(cmd, cwd=cwd, env=env, timeout=LAUNCH_TIMEOUT_S)


def _env():
    env = FACTORY_KW.get("environ")
    return None if env is None else {**os.environ, **env}


def _refuse(refusals, root):
    first = refusals[0]
    status = REFUSALS.get(first["code"], (409, ""))[0]
    raise BatchFault(status, first["code"], first["message"],
                     paths.clean([r["line"] for r in refusals if r.get("line")], root))


def read(root, token):
    """The confirmed launch: the switch first, the token spent, the plan again
    (the same channels and command), then the factory's launch in a child -
    {ok, launched, run_id, pid, log, channels, argv, by, via, lines, poll_s}."""
    if not STUDIO_READ_LAUNCH:
        raise BatchFault(409, "launch_off", LAUNCH_OFF_WHY,
                         ["api/studio_center.py STUDIO_READ_LAUNCH is False; the token is "
                          "not spent"])
    if not _LAUNCH.acquire(blocking=False):
        raise BatchFault(409, "busy", "Идёт другой запуск чтения Studio - подождите и "
                                      "запросите план заново.", ["one Studio confirm at a time"])
    try:
        tok = _spend(root, ACTION, KEY, token)
        got = _plan_now(root)
        refusals = _refusals(got.get("refusals"))
        if refusals:
            _refuse(refusals, root)
        if _fingerprint(got) != tok["fingerprint"]:
            raise BatchFault(409, "check_changed", "План чтения Studio изменился с момента "
                                                   "подтверждения - ничего не запущено; "
                                                   "посмотрите план заново.",
                             ["the channels or the command differ from the confirmed plan"])
        sc = _sc()
        cmd = [sys.executable, "-c", _LAUNCHER, str(sc.__file__), str(root),
               str(FACTORY_KW.get("claude") or ""), json.dumps(got["channels"])]
        try:
            rc, out, err = run_launcher(cmd, str(root), _env())
            res = json.loads((out or "").strip().splitlines()[-1]) if rc == 0 else None
        except (child.Timeout, OSError, ValueError, IndexError) as e:
            raise BatchFault(500, "launch_failed", "Запуск чтения Studio не ответил - "
                                                   "неизвестно, стартовала ли сессия; посмотрите "
                                                   "schedule/studio-read/runs, прежде чем "
                                                   "повторять.",
                             paths.clean([f"{type(e).__name__}: {e}"], root)) from None
        if not isinstance(res, dict):
            raise BatchFault(500, "launch_failed", "Запуск чтения Studio не ответил - "
                                                   "неизвестно, стартовала ли сессия; посмотрите "
                                                   "schedule/studio-read/runs, прежде чем "
                                                   "повторять.",
                             paths.clean([f"exit {rc}"] + (err or "").splitlines()[-5:], root))
        refusals = _refusals(res.get("refusals"))
        if refusals:
            _refuse(refusals, root)
        return paths.clean({"ok": True, "launched": bool(res.get("launched")),
                            "run_id": res.get("run_id"), "pid": res.get("pid"),
                            "log": res.get("log"), "channels": res.get("channels") or [],
                            "argv": res.get("argv") or [], "by": res.get("by"),
                            "via": res.get("via"), "lines": res.get("lines") or [],
                            "poll_s": POLL_S}, root)
    finally:
        _LAUNCH.release()


# ---------------------------------------------------------------- the outcome
def result(root, run_id):
    """`studio_read_result(run_id)` + its Russian word and a poll hint."""
    if not RUN_ID.match(run_id or ""):
        raise BatchFault(422, "bad_run", f"«{run_id}» - не номер запуска чтения Studio "
                                         f"(ГГГГММДДTЧЧММССZ).",
                         [f"run id {run_id!r}: {RUN_ID.pattern}"])
    sc = _sc()
    try:
        got = sc.studio_read_result(run_id, root, environ=FACTORY_KW.get("environ"))
    except OSError as e:
        raise _broken(e, "итог чтения Studio") from e
    if got.get("run_id") is None and got.get("code") == "error" and \
            str(got.get("detail") or "").startswith("нет журнала"):
        raise BatchFault(404, "unknown_run", f"Запуска чтения Studio «{run_id}» нет.",
                         paths.clean([got.get("detail") or ""], root))
    code = got.get("code")
    return paths.clean(dict(got, word=sc.OUTCOME_WORDS.get(code, code),
                            poll_s=None if got.get("done") else POLL_S), root)
