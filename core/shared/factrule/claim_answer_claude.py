#!/usr/bin/env python3
"""CF-0553: the default answerer of the claim judge - one request of
`claim_judge.py`, answered by a headless `claude -p` (the shape of the
indexer's sieve answerer, CF-0478).

The request file (`<key>.request.json`, written by `claim_judge.Asker`)
carries the whole prompt; this script sends it to `claude -p --model <model>`
with no tools, from an empty temporary directory (no project, no CLAUDE.md of
the factory, no session kept), so the call knows only what the prompt says -
the extractor the finished text, the judge one claim and its footing. What it
prints is read as JSON (prose or a fence around the object is cut away; of two objects -
a model correcting itself - the last counts) and written to the answer file; the schema is the caller's to check.

* the model and the ceiling are parameters (`--model`, `--timeout`);
* the whole `claude` process group is killed on the ceiling;
* everything the call printed lands in the log (`--log`);
* **not logged in is said, not waited for**: exit 4 and `NOT_LOGGED_IN` on
  stderr, which the judge turns into "cannot answer" - no verdict, no spent
  attempt.

Exit codes: 0 answered; 2 bad arguments / unreadable request; 3 no JSON object
in what claude printed; 4 not logged in; 5 the ceiling; 6 claude failed
otherwise. Stdlib only.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

TASK = "CF-0553"
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 240
CLAUDE_ENV = "CLAIM_JUDGE_CLAUDE"
DEFAULT_CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"
NOT_LOGGED_IN = "NOT_LOGGED_IN"
EXIT_OK, EXIT_USAGE, EXIT_NO_JSON, EXIT_NOT_LOGGED_IN, EXIT_TIMEOUT, EXIT_FAILED = 0, 2, 3, 4, 5, 6
NOT_LOGGED_IN_RE = re.compile(
    r"not logged in|please run /login|run /login|/login\b|"
    r"oauth[^\n]{0,60}(expired|revoked|invalid)|session expired|"
    r"invalid api key|authentication_error", re.I)
SYSTEM = ("You are a careful reader. You answer only with the JSON object the user asks for, "
          "and you use nothing but the text you are given.")


def claude_binary(flag=None, env=None):
    env = os.environ if env is None else env
    for c in (flag, env.get(CLAUDE_ENV)):
        if c:
            return str(c)
    return shutil.which("claude") or str(DEFAULT_CLAUDE_FALLBACK)


def claude_argv(claude, model):
    # The prompt goes in on stdin: a long footing is no argv problem.
    return [claude, "-p", "--model", model, "--tools", "", "--no-session-persistence",
            "--output-format", "text", "--system-prompt", SYSTEM]


def json_object(text):
    """The JSON object in what the model printed, or None. A model that
    corrects itself prints two; the last one is its answer."""
    text = text or ""
    dec = json.JSONDecoder()
    found, i = None, 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return found
        try:
            doc, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(doc, dict):
            found = doc
        i = end


KILL_GRACE_S = 5.0                 # SIGTERM -> SIGKILL of the group past the ceiling


def _proc_group():
    """`shared/proc_group.py` by path (CF-0655), loaded only when a kill is needed."""
    import importlib.util  # noqa: PLC0415
    name = "factory_proc_group_cf0655"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent.parent / "proc_group.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def kill_group(p):
    """SIGTERM to the group, SIGKILL when anything in it - not only the direct
    child - is still there after `KILL_GRACE_S` (CF-0655)."""
    _proc_group().kill_group(p.pid, KILL_GRACE_S, reap=p.poll)
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run(argv, prompt, timeout, log_path):
    """(returncode | None on the ceiling, stdout, stderr)."""
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    with tempfile.TemporaryDirectory(prefix="claim-judge-") as cwd:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=cwd, env=env, text=True,
                             start_new_session=True)
        try:
            out, err = p.communicate(prompt, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            kill_group(p)
            out, err, rc = "", "", None
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"# {TASK} {dt.datetime.now().isoformat(timespec='seconds')} "
                  f"timeout={timeout}s\n# argv: {' '.join(argv[:-1])} <system>\n"
                  f"# --- stdout\n{out}\n# --- stderr\n{err}\n"
                  f"# exit {rc if rc is not None else 'TIMEOUT'}\n")
    return rc, out, err


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--request", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--claude", default=None)
    a = ap.parse_args(argv)
    log = a.log or str(Path(a.answer).with_suffix(".log"))
    try:
        req = json.loads(Path(a.request).read_text(encoding="utf-8"))
        prompt = req["prompt"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"claim answerer: cannot read the request {a.request} ({exc})", file=sys.stderr)
        return EXIT_USAGE
    claude = claude_binary(a.claude)
    try:
        rc, out, err = run(claude_argv(claude, a.model), prompt, a.timeout, log)
    except OSError as exc:
        print(f"claim answerer: cannot start {claude} ({exc})", file=sys.stderr)
        return EXIT_FAILED
    if rc is None:
        print(f"claim answerer: claude ran past {a.timeout}s and was stopped; log {log}",
              file=sys.stderr)
        return EXIT_TIMEOUT
    if rc != 0:
        if NOT_LOGGED_IN_RE.search((out or "") + (err or "")):
            print(f"claim answerer: {NOT_LOGGED_IN} - the console claude is not logged in; "
                  f"log {log}", file=sys.stderr)
            return EXIT_NOT_LOGGED_IN
        print(f"claim answerer: claude exited {rc}; log {log}", file=sys.stderr)
        return EXIT_FAILED
    doc = json_object(out)
    if doc is None:
        print(f"claim answerer: no JSON object in the answer; log {log}", file=sys.stderr)
        return EXIT_NO_JSON
    Path(a.answer).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
