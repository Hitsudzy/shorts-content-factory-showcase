#!/usr/bin/env python3
"""CF-0841: `scripts/agents api-check` says whether the live command-center API
(launchd com.example-film.cc-api) runs the code of a tree.

After the 2.21 release the live API stayed on 2.19.1's code for a day:
`/api/version` answered api 0.68.0 while main had 0.69.0, and nothing in the
release ritual looked. Now `api-check` asks `GET <url>/api/version` and
compares its `api` with `API_VERSION` of `<root>/api/__init__.py` and its
`factory.commit` with `git rev-parse HEAD` of the root. Pinned, against a
stand-in HTTP server on a free loopback port and a temp git tree (never the
live API, never the real checkout):

* the same api and commit - exit 0, an `ok` line;
* the live api behind - exit 1, the line names both versions and the restart
  (`launchctl kickstart -k ...`, outside a batch only);
* the live commit behind - exit 1, both commits;
* nobody listening - exit 3, a `DOWN` line, no traceback;
* an answer that is not a version (401, not JSON) - exit 4;
* `status` never goes to the network: it runs with no server and does not
  mention the API.

CF-0848 (contract 0.70.0, CC-0155): the API says its own age - `started_at`,
`commit_at_start`, `stale`, `stale_paths`:

* `stale` true - exit 1 even with the same api and commit, a `DIFF ... runs
  stale code (живой API на старом коде)` line with the start time, the short
  start commit, the paths and the restart;
* `stale` false - exit 0, the `ok` line says `process current`;
* `stale` null or no field (an API before 0.70.0) - the old api/commit check,
  the `ok` line says `process age not checked`; behind is still exit 1.
"""
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from _tmproot import tmp_root   # noqa: E402

import agents_lock  # noqa: E402

TMP = tmp_root("agents-api-check-test-")
CLI = [sys.executable, str(ROOT / "scripts" / "agents")]
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def tree(api_version="0.69.0"):
    """A root repo with api/__init__.py and a lock -> (dir, HEAD sha)."""
    _n[0] += 1
    d = TMP / f"t{_n[0]}"
    (d / "api").mkdir(parents=True)
    git(d, "init", "-q")
    git(d, "config", "user.email", "t@example.test")
    git(d, "config", "user.name", "t")
    (d / "api" / "__init__.py").write_text(
        f'"""doc"""\n\n#: the contract\nAPI_VERSION = "{api_version}"  # CC-0000: notes\n')
    (d / "api" / "__main__.py").write_text('"""doc"""\nLABEL = "com.example.cc-api"\n')
    (d / "agents.lock.json").write_text(json.dumps(
        {"agents": {"ve": {"path": "agents/ve", "rev": "v1.4"}}}) + "\n")
    git(d, "add", ".")
    git(d, "commit", "-qm", "c1")
    return d, git(d, "rev-parse", "HEAD")


class Stand:
    """A stand-in API on 127.0.0.1:<free port> answering /api/version."""

    def __init__(self, status=200, body=None):
        stand = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                stand.paths.append(self.path)
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.paths = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()


def version_body(api, commit, **process):
    """A /api/version answer; `process` - CC-0155's started_at, commit_at_start,
    stale, stale_paths (left out: an API before 0.70.0)."""
    return {"api": api, "writes": True, "writes_reason": None, "writes_dev": False,
            "factory": {"version": "2.21", "commit": commit, "dirty": False},
            "agents": [], "agents_error": None, "center": {}, **process}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def cli(*args):
    env = dict(os.environ)
    env.pop("FACTORY_ROOT", None)
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env,
                          timeout=60)


# ------------------------------------------------------------------ tests

def test_code_api_version_is_read_from_the_tree_without_fastapi():
    d, _ = tree("1.2.3")
    assert agents_lock.code_api_version(d) == "1.2.3"
    assert agents_lock.code_api_version(ROOT).count(".") == 2   # this tree's own
    assert agents_lock.cc_api_label(ROOT).endswith(".cc-api")
    assert agents_lock.cc_api_label(d) == "com.example.cc-api"
    (d / "api" / "__init__.py").write_text("X = 1\n")
    try:
        agents_lock.code_api_version(d)
        raise AssertionError("no API_VERSION must be a LockError")
    except agents_lock.LockError as e:
        assert "API_VERSION" in str(e)


def test_the_same_api_and_commit_is_exit_0():
    d, head = tree()
    with Stand(body=version_body("0.69.0", head)) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
        assert s.paths == ["/api/version"], s.paths
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert cp.stdout.startswith("ok ") and "0.69.0" in cp.stdout and head[:12] in cp.stdout


def test_a_live_api_behind_main_is_exit_1_with_the_restart():
    d, head = tree("0.69.0")
    with Stand(body=version_body("0.68.0", head)) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 1, (cp.stdout, cp.stderr)
    out = cp.stdout
    assert out.startswith("DIFF ") and "api 0.68.0 != 0.69.0" in out, out
    assert "commit" not in out.split("restart")[0], out
    # the label is the tree's own api/__main__.py LABEL, not a copy
    assert "launchctl kickstart -k gui/$(id -u)/com.example.cc-api" in out, out
    assert "outside a batch" in out and "живой API отстаёт" in out, out


def test_a_live_commit_behind_head_is_exit_1():
    d, head = tree("0.69.0")
    old = "0123456789ab" + "0" * 28
    with Stand(body=version_body("0.69.0", old)) as s:
        res = agents_lock.api_check(d, s.url, timeout=5)
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert res["code"] == agents_lock.API_CHECK_BEHIND
    assert res["live"] == {"api": "0.69.0", "commit": old}
    assert res["want"] == {"api": "0.69.0", "commit": head}
    assert cp.returncode == 1 and f"commit 0123456789ab != {head[:12]}" in cp.stdout, cp.stdout
    # a short sha of the same commit is the same commit; a null commit is not
    with Stand(body=version_body("0.69.0", head[:12])) as s:
        assert agents_lock.api_check(d, s.url, timeout=5)["code"] == 0
    with Stand(body=version_body("0.69.0", None)) as s:
        assert agents_lock.api_check(d, s.url, timeout=5)["code"] == 1


def test_a_stale_process_is_exit_1_even_on_the_same_api_and_commit():
    d, head = tree("0.70.0")
    start = "fedcba987654" + "1" * 28
    body = version_body("0.70.0", head, started_at="2026-10-22T02:15:07Z",
                        commit_at_start=start, stale=True,
                        stale_paths=["shared/agents_lock.py", "api/factory.py"])
    with Stand(body=body) as s:
        res = agents_lock.api_check(d, s.url, timeout=5)
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert res["code"] == agents_lock.API_CHECK_BEHIND, res
    assert res["live"] == {"api": "0.70.0", "commit": head}
    assert res["process"]["stale"] is True
    assert cp.returncode == 1, (cp.stdout, cp.stderr)
    out = cp.stdout
    assert out.startswith("DIFF the live API runs stale code (живой API на старом коде)"), out
    assert "2026-10-22T02:15:07Z" in out and "fedcba987654" in out and start not in out, out
    assert "shared/agents_lock.py, api/factory.py" in out, out
    assert "launchctl kickstart -k gui/$(id -u)/com.example.cc-api" in out, out
    assert "outside a batch" in out, out
    # stale and behind on the contract: both reasons in the one line
    with Stand(body={**body, "api": "0.69.0"}) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 1 and "api 0.69.0 != 0.70.0" in cp.stdout, cp.stdout
    assert "runs stale code" in cp.stdout, cp.stdout


def test_a_current_process_is_exit_0_and_says_so():
    d, head = tree("0.70.0")
    body = version_body("0.70.0", head, started_at="2026-10-22T02:15:07Z",
                        commit_at_start=head, stale=False, stale_paths=[])
    with Stand(body=body) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert cp.stdout.startswith("ok ") and "process current, started 2026-10-22T02:15:07Z" \
        in cp.stdout, cp.stdout
    assert "not checked" not in cp.stdout
    # stale false does not excuse an older contract
    with Stand(body={**body, "api": "0.69.0"}) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 1 and "api 0.69.0 != 0.70.0" in cp.stdout, cp.stdout
    assert cp.stdout.startswith("DIFF the live API is behind"), cp.stdout


def test_stale_null_or_absent_falls_back_to_the_api_and_commit_check():
    d, head = tree("0.70.0")
    null = version_body("0.70.0", head, started_at="2026-10-22T02:15:07Z",
                        commit_at_start=None, stale=None, stale_paths=None)
    with Stand(body=null) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "process age not checked (stale is null)" in cp.stdout, cp.stdout
    with Stand(body=version_body("0.70.0", head)) as s:     # an API before 0.70.0
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "process age not checked (no stale field)" in cp.stdout, cp.stdout
    # the old checks still hold without the field: behind api, behind commit
    with Stand(body=version_body("0.69.0", head)) as s:
        assert agents_lock.api_check(d, s.url, timeout=5)["code"] == 1
    with Stand(body={**null, "factory": {"commit": "0" * 40}}) as s:
        res = agents_lock.api_check(d, s.url, timeout=5)
    assert res["code"] == 1 and "commit 000000000000" in res["why"], res
    # a stale that is not a bool is not trusted as one
    with Stand(body={**null, "stale": "yes"}) as s:
        res = agents_lock.api_check(d, s.url, timeout=5)
    assert res["code"] == 0 and res["process"]["stale"] is None, res


def test_nobody_listening_is_exit_3_not_a_traceback():
    d, _ = tree()
    url = f"http://127.0.0.1:{free_port()}"
    cp = cli("api-check", "--root", str(d), "--url", url, "--timeout", "3")
    assert cp.returncode == 3, (cp.stdout, cp.stderr)
    assert cp.stderr.startswith("DOWN ") and url in cp.stderr, cp.stderr
    assert "launchctl print gui/$(id -u)/com.example.cc-api" in cp.stderr, cp.stderr
    assert "Traceback" not in cp.stderr and cp.stdout == ""


def test_an_answer_that_is_not_a_version_is_exit_4():
    d, _ = tree()
    with Stand(status=401, body={"detail": "x", "code": "auth_required"}) as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 4 and "HTTP 401" in cp.stderr, (cp.stdout, cp.stderr)
    with Stand(body=b"<html>not json</html>") as s:
        cp = cli("api-check", "--root", str(d), "--url", s.url)
    assert cp.returncode == 4 and "not a /api/version answer" in cp.stderr, cp.stderr
    assert "Traceback" not in cp.stderr


def test_a_tree_without_the_api_is_exit_2():
    d, _ = tree()
    (d / "api" / "__init__.py").unlink()
    cp = cli("api-check", "--root", str(d), "--url", f"http://127.0.0.1:{free_port()}")
    assert cp.returncode == 2 and "api/__init__.py" in cp.stderr, cp.stderr


def test_status_does_not_ask_the_api():
    d, _ = tree()
    cp = cli("status", "--root", str(d))
    # the agent is not checked out: a DIFF row (exit 1), and nothing about the API
    assert cp.returncode == 1 and cp.stdout.startswith("DIFF agents/ve"), (cp.stdout, cp.stderr)
    assert "API" not in cp.stdout + cp.stderr and "8790" not in cp.stdout + cp.stderr


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
