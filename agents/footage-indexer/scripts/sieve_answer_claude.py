#!/usr/bin/env python3
"""The sieve-flag answerer of a run: one source's frames, answered by a
headless `claude -p` (CF-0478).

CF-0374 made *who answers* a setting of the run -
`channels/<channel>.json` -> `footage_indexer.sieve_flags_answer_cmd` - and
`backfill_sieve_flags.answer_by_cmd()` runs that command once per source with
`{questions}` / `{sheet}` / `{answers}` / `{video_id}`. What was missing was a
command: the answerer of the CF-0355 pilot was a frame subagent dispatched by
hand, and on batch 2026-10-01T1313Z the indexer's operator marked 5 old
sources (230 shots) himself. The orchestrator then wrote the answerer as a
shell one-off around `claude -p --model sonnet` and checked it on
`_m4e4oWFmac` (27 shots: exit 0, 27/27 answers, every flag a boolean). This is
that answerer, in the repo, with what the one-off did not have:

* the model and the ceiling are parameters (`--model`, `--timeout`);
* the question names `screen_recording` too (signed hard on 2026-10-01,
  CF-0451) - it is optional in the answers, as `RULES` says;
* the whole `claude` process group is killed on the ceiling, so a hung model
  does not outlive the source it was answering (the indexer's own
  `subprocess.run(timeout=)` would kill only the shell in front of it);
* the answers are checked before the command says "done": every listed shot,
  `burned_text` a boolean, `on_topic` a boolean when the questions require
  both - a partial file is a failure the sieve records, never a guess;
* the log of the call lands beside the answers, `<dir>/<id>.answerer.log`;
* **not logged in is said, not waited for.** When the console `claude` has no
  session (2026-10-01 afternoon: "OAuth session expired") the source fails the
  way any unanswered source fails - the sieve takes it out with a record and
  the run goes on (DoD 1) - the stderr line carries `NOT_LOGGED_IN` (which the
  sieve's `sieve_answers` summary line repeats), and one question goes into
  the factory's journal of questions (`shared/needs_you.py` of the root,
  CF-0652) asking for a login - one per fact, never one per source, resolved
  by the next call claude answers. A root without the journal is a line in
  the log, not a failure.

Exit codes: 0 answered; 2 bad arguments / unreadable questions; 3 the answers
are missing or do not cover the questions; 4 the console claude is not logged
in; 5 the ceiling; 6 claude failed otherwise.

Stdlib only (and the root's stdlib-only `shared/needs_you.py`): the sieve
runs it through the shell under whatever python the config names
(`{python}`, the indexer's own interpreter).
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

TASK = "CF-0478"
DEFAULT_MODEL = "sonnet"
# Ceiling on one call, seconds. Below the indexer's own ceiling on the command
# (the config's `timeout_seconds`) so that this script, not the indexer, is the
# one that stops claude - and stops all of it.
DEFAULT_TIMEOUT = 270
KILL_GRACE_SECONDS = 5
LOG_SUFFIX = ".answerer.log"
CLAUDE_ENV = "SIEVE_ANSWERER_CLAUDE"
DEFAULT_CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BAD_ANSWERS = 3
EXIT_NOT_LOGGED_IN = 4
EXIT_TIMEOUT = 5
EXIT_CLAUDE_FAILED = 6

# What the indexer's record of a failed source carries (the stderr tail), and
# what `source_sieve.answers_summary_line()` looks for. One word, so the
# 300-character tail the indexer keeps cannot cut it in half.
NOT_LOGGED_IN = "NOT_LOGGED_IN"

# What claude prints when it has no session. Only read when the call failed -
# a model's own text may say anything.
NOT_LOGGED_IN_RE = re.compile(
    r"not logged in|please run /login|run /login|/login\b|"
    r"oauth[^\n]{0,60}(expired|revoked|invalid)|session expired|"
    r"invalid api key|authentication_error", re.I)

# The question to the user (CF-0652, see "The question to the user" below).
# The text names no source: it is the same question whichever source met the
# logout first, so a second failing source does not reword it.
NEEDS_YOU_MODULE_REL = Path("shared") / "needs_you.py"
NEEDS_YOU_SOURCE = "footage-indexer"
NEEDS_YOU_KEY = "sieve-answerer:not-logged-in"
NEEDS_YOU_TEXT = (
    "войдите в консольный claude (`claude`, затем /login): отвечающий сита "
    "не может разметить источники - каждый уходит из батча с записью "
    "(NOT_LOGGED_IN в строке sieve_answers), прогон продолжается "
    "(CF-0478, footage-indexer/scripts/sieve_answer_claude.py)")

PROMPT = (
    "You answer the sieve flags for the shots of YouTube source {vid}. Read "
    "the questions file {questions} (rules, topic, shots to answer) and look "
    "at the contact sheet image {sheet} (numbered tiles, each labelled with "
    "the shot's index). For every shot listed in the questions answer exactly "
    "as the rules say: burned_text (true if the frame carries burned-in text "
    "that is not ours: captions, another channel's graphics, titles; false "
    "otherwise), on_topic (true/false; null only if the questions allow it), "
    "screen_recording (true if the frame is a screen filmed from the room, "
    "false if it is the work's own image, null when you cannot tell) and for "
    "burned_text true the text as seen. Write ONLY the JSON file {answers} in "
    "the form {{\"video_id\": \"{vid}\", \"answers\": [{{\"index\": N, "
    "\"burned_text\": bool, \"on_topic\": bool|null, \"screen_recording\": "
    "bool|null, \"text\": \"...\"}}]}} covering every listed shot. Do nothing "
    "else.")


def claude_binary(flag=None, env=None):
    env = os.environ if env is None else env
    for c in (flag, env.get(CLAUDE_ENV)):
        if c:
            return str(c)
    return shutil.which("claude") or str(DEFAULT_CLAUDE_FALLBACK)


def claude_argv(claude, model, prompt, dirs):
    # The order of the checked one-off: the variadic options (`--allowedTools`,
    # `--add-dir`) are closed by `--permission-mode`, then the prompt.
    argv = [claude, "-p", "--model", model, "--allowedTools", "Read", "Write"]
    for d in dict.fromkeys(str(d) for d in dirs):
        argv += ["--add-dir", d]
    return argv + ["--permission-mode", "acceptEdits", prompt]


def run_claude(argv, log_path, timeout, env=None):
    """Run claude in its own process group, everything it prints into the log.
    Returns (returncode | None on the ceiling, log text)."""
    env = dict(os.environ if env is None else env)
    # A batch started from a Claude Code session must not look nested to the
    # child; the child is a separate, headless call.
    env.pop("CLAUDECODE", None)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"# {TASK} {dt.datetime.now().isoformat(timespec='seconds')}"
                  f" timeout={timeout}s\n# argv: "
                  + " ".join(argv[:-1]) + " <prompt>\n")
        log.flush()
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env,
                             start_new_session=True)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(p)
            rc = None
        log.write(f"\n# exit {rc if rc is not None else 'TIMEOUT'}\n")
    return rc, log_path.read_text(encoding="utf-8", errors="replace")


GROUP_POLL_SECONDS = 0.05


def group_gone(pgid):
    """True once process group `pgid` has no live member.

    `killpg(pgid, 0)` answers ESRCH (ProcessLookupError) for a group with no
    member at all. macOS answers EPERM (PermissionError) for a group whose
    only members are zombies (CF-0504) - read the same way: nothing left to
    signal. On Linux a zombie still counts until reaped, which is why the
    caller reaps its own child (the leader) before asking; an orphaned
    grandchild is reaped by launchd/init at once."""
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return True
    return False


def kill_group(p, grace=None):
    """CF-0655: SIGTERM the whole group `p` leads (start_new_session=True),
    wait up to `grace` s for the *group* - not just `p` - to empty, then
    SIGKILL the group and wait again. Waiting on `p` alone let a grandchild
    that ignores SIGTERM outlive the ceiling: `p` died, the wait ended, and
    SIGKILL was never sent. `p` itself is reaped on every poll so its zombie
    does not keep the group looking alive."""
    grace = KILL_GRACE_SECONDS if grace is None else grace
    pgid = p.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            break
        deadline = time.monotonic() + grace
        while True:
            p.poll()
            if group_gone(pgid):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(GROUP_POLL_SECONDS)
        if group_gone(pgid):
            break
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


def check_answers(questions, answers_path):
    """The problems with the answers file against its questions, [] when it
    covers them."""
    path = Path(answers_path)
    if not path.exists():
        return [f"claude wrote no {path.name}"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{path.name} is not JSON ({e})"]
    if not isinstance(doc, dict) or not isinstance(doc.get("answers"), list):
        return [f"{path.name} has no answers list"]
    problems = []
    if doc.get("video_id") != questions.get("video_id"):
        problems.append(f"video_id {doc.get('video_id')!r} is not "
                        f"{questions.get('video_id')!r}")
    both = bool(questions.get("both_flags_required"))
    by_index = {a.get("index"): a for a in doc["answers"] if isinstance(a, dict)}
    missing, bad = [], []
    for s in questions.get("shots") or []:
        a = by_index.get(s.get("index"))
        if a is None:
            missing.append(s.get("index"))
            continue
        if not isinstance(a.get("burned_text"), bool):
            bad.append(f"{s.get('index')}: burned_text")
        v = a.get("on_topic")
        if (both and not isinstance(v, bool)) or (
                v is not None and not isinstance(v, bool)):
            bad.append(f"{s.get('index')}: on_topic")
        v = a.get("screen_recording")
        if v is not None and not isinstance(v, bool):
            bad.append(f"{s.get('index')}: screen_recording")
    if missing:
        problems.append(f"{len(missing)} listed shot(s) unanswered "
                        f"({', '.join(str(i) for i in missing[:8])})")
    if bad:
        problems.append("not a boolean: " + ", ".join(bad[:8]))
    return problems


# ---------------------------------------------------------------------------
# The question to the user (CF-0652): the factory's journal of questions,
# `shared/needs_you.py` of the root, not a line in a note. One question per
# fact, not per source: "the console claude is not logged in" is one state of
# this machine, every source of a run fails on it at once, and one /login
# answers all of them - a key per source would be N questions and N Telegram
# messages for one act. The sources themselves are named where they belong,
# in the sieve's records and its `sieve_answers` line. The journal's `add`
# asks once while the question stands; a claude that answers again (exit 0)
# resolves it, and the next logout asks anew.

def needs_you_module(roots=None):
    """`shared/needs_you.py` of the first factory root that has it - roots
    asked the way the agent asks for the root's other code (`_fi_paths`:
    FACTORY_ROOT, then the nearest ancestor holding the run log). Returns
    (module, None), or (None, why) when no root has it (a root older than 2.3)
    or it does not load; the caller says why, the sieve never falls over it."""
    if roots is None:
        try:
            from _fi_paths import root_candidates
            roots = root_candidates()
        except Exception as e:                                  # noqa: BLE001
            return None, f"no factory root ({e.__class__.__name__}: {e})"
    tried = []
    for root in roots:
        path = Path(root) / NEEDS_YOU_MODULE_REL
        if not path.is_file():
            tried.append(str(root))
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                "_fi_needs_you", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:                                  # noqa: BLE001
            return None, f"{path} does not load ({e.__class__.__name__}: {e})"
        return mod, None
    return None, ("no " + str(NEEDS_YOU_MODULE_REL) + " under "
                  + (", ".join(tried) if tried else "any factory root"))


def _note(log_path, msg):
    """A line about the question that could not be asked: on stderr (before
    the final line the indexer quotes) and at the end of the answerer's log."""
    line = f"sieve answerer: {msg}"
    print(line, file=sys.stderr)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def remind(log_path=None, module=None, **kw):
    """Ask the user to log in (once while the question stands). Returns the
    question, or None when it could not be asked - said in the log, never
    raised: the exit code and the summary line still say NOT_LOGGED_IN."""
    mod, why = (module, None) if module is not None else needs_you_module()
    if mod is None:
        _note(log_path, f"the login question was not asked: {why}")
        return None
    try:
        q, _ = mod.add(NEEDS_YOU_SOURCE, NEEDS_YOU_KEY, NEEDS_YOU_TEXT, **kw)
        return q
    except Exception as e:                                      # noqa: BLE001
        _note(log_path, f"the login question was not asked "
                        f"({e.__class__.__name__}: {e})")
        return None


def clear_reminder(vid, log_path=None, module=None, **kw):
    """The console claude answered: the login question, if one stands, is
    resolved. Returns the questions resolved ([] when none stood or the journal
    is out of reach - silence: a working answer has nothing to tell)."""
    mod, _ = (module, None) if module is not None else needs_you_module()
    if mod is None:
        return []
    try:
        return mod.resolve(key=NEEDS_YOU_KEY, by=NEEDS_YOU_SOURCE,
                           note=f"claude answered {vid}", **kw)
    except Exception as e:                                      # noqa: BLE001
        _note(log_path, f"the login question was not resolved "
                        f"({e.__class__.__name__}: {e})")
        return []


def fail(code, msg):
    # The last line of stderr is what the indexer quotes in the source's
    # record (a 300-character tail), so it is short and says everything.
    print(f"sieve answerer: {msg}", file=sys.stderr)
    return code


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--questions", required=True)
    p.add_argument("--sheet", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--video-id", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help="ceiling on the claude call, seconds")
    p.add_argument("--claude", help=f"the claude binary (default: "
                                    f"${CLAUDE_ENV}, else claude on PATH, "
                                    f"else {DEFAULT_CLAUDE_FALLBACK})")
    p.add_argument("--log", help=f"default: <answers dir>/<id>{LOG_SUFFIX}")
    a = p.parse_args(argv)

    vid = a.video_id
    answers = Path(a.answers)
    log_path = Path(a.log) if a.log else answers.parent / f"{vid}{LOG_SUFFIX}"
    try:
        questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return fail(EXIT_USAGE, f"cannot read the questions {a.questions} ({e})")
    if not questions.get("shots"):
        return fail(EXIT_USAGE, f"{a.questions} lists no shot to answer")
    if a.timeout <= 0:
        return fail(EXIT_USAGE, "--timeout must be > 0")

    claude = claude_binary(a.claude)
    prompt = PROMPT.format(vid=vid, questions=a.questions, sheet=a.sheet,
                           answers=str(answers))
    dirs = [answers.parent, Path(a.questions).parent]
    if a.sheet:
        dirs.append(Path(a.sheet).parent)
    try:
        rc, text = run_claude(claude_argv(claude, a.model, prompt, dirs),
                              log_path, a.timeout)
    except OSError as e:
        return fail(EXIT_CLAUDE_FAILED, f"cannot start {claude} ({e}); "
                                        f"log {log_path}")
    if rc is None:
        return fail(EXIT_TIMEOUT, f"claude ran past {a.timeout}s on {vid} and "
                                  f"was stopped; log {log_path}")
    if rc == 0:
        # claude ran with a session: the login question no longer holds,
        # whatever the answers turn out to be.
        clear_reminder(vid, log_path)
    problems = check_answers(questions, answers)
    if rc != 0 or problems:
        if rc != 0 and NOT_LOGGED_IN_RE.search(text):
            remind(log_path)
            return fail(EXIT_NOT_LOGGED_IN,
                        f"{NOT_LOGGED_IN} - the console claude is not logged "
                        f"in, {vid} not answered; log {log_path}")
        if rc != 0:
            return fail(EXIT_CLAUDE_FAILED, f"claude exited {rc} on {vid}; "
                                            f"log {log_path}")
        return fail(EXIT_BAD_ANSWERS, f"{vid}: " + "; ".join(problems)
                    + f"; log {log_path}")
    print(f"sieve answerer: {vid} answered ({len(questions['shots'])} "
          f"shot(s), {a.model})")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
