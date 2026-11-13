#!/usr/bin/env python3
"""CF-0614 (the root's CF-0609 self-test, docs/test-hygiene.md §6): the runner turns the network off and keeps the live tests apart.

Points tests/run_tests.py (as a subprocess, `--dir`) at a temp directory of
probe files and reads its output, as test_run_tests_timeout does for the
ceiling:

  test_a_local.py  - a TCP server on 127.0.0.1 and a unix socket: loopback is
                     allowed, the file passes;
  test_b_net.py    - a name lookup, a connect to a TEST-NET address and urllib
                     to a made-up host, every refusal swallowed and `1/1
                     passed` printed anyway: the runner still makes it FAILED
                     with every address;
  test_c_curl.py   - curl (not Python) to a made-up host: the proxy trap
                     writes the host down, FAILED;
  test_d_live.py   - `LIVE_TEST = "..."`: skipped in the plain run with one line,
                     run by `--live`;
  test_e_part.py   - `LIVE_ENV = "CF0609_PROBE_LIVE"`: runs in the plain run
                     with its switch forced off (even when the shell set it)
                     and the network off; `--live` runs it with the switch on
                     and the network open.

Nothing here leaves the machine: the made-up hosts are refused before any
lookup (Python) or sent to the runner's trap on loopback (curl).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_tests.py"
SWITCH = "CF0609_PROBE_LIVE"

LOCAL = '''\
import os, socket, socketserver, tempfile, threading
class H(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"hi")
srv = socketserver.TCPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with socket.create_connection(("localhost", srv.server_address[1]), timeout=5) as c:
    assert c.recv(2) == b"hi"
srv.shutdown(); srv.server_close()
d = tempfile.mkdtemp(dir="/tmp")
p = os.path.join(d, "s")
u = socket.socket(socket.AF_UNIX); u.bind(p); u.listen(1)
v = socket.socket(socket.AF_UNIX); v.connect(p); v.close(); u.close()
os.remove(p); os.rmdir(d)
print("loopback ok")
print("1/1 passed")
'''

NET = '''\
import socket, urllib.request
for attempt in (lambda: socket.getaddrinfo("cf0609-lookup.example", 443),
                lambda: socket.socket().connect(("203.0.113.7", 443)),
                lambda: urllib.request.urlopen("http://cf0609-urllib.example/x", timeout=5)):
    try:
        attempt()
    except Exception as exc:
        print("swallowed:", type(exc).__name__)
print("1/1 passed")
'''

CURL = '''\
import subprocess
subprocess.run(["curl", "-sS", "--max-time", "5", "http://cf0609-curl.example/"],
               capture_output=True, timeout=20)
print("1/1 passed")
'''

LIVE_BODY = '''\
from pathlib import Path
LIVE_TEST = "probe: talks to the world"
Path(__file__).with_name("d_ran").write_text("yes")
print("1/1 passed")
'''

PART = '''\
import os, socket
LIVE_ENV = "%s"
print("switch", os.environ.get(LIVE_ENV) == "1" and "on" or "off")
print("guard", hasattr(socket, "NetworkBlocked") and "on" or "off")
print("1/1 passed")
''' % SWITCH

_RUNS = {}


def _probe_dir():
    d = Path(tempfile.mkdtemp(prefix="cf0609-net-"))
    for name, body in (("test_a_local.py", LOCAL), ("test_b_net.py", NET),
                       ("test_c_curl.py", CURL), ("test_d_live.py", LIVE_BODY),
                       ("test_e_part.py", PART)):
        (d / name).write_text(body, encoding="utf-8")
    return d


def run(*flags):
    """(returncode, output, d_ran) of the runner over a fresh probe directory."""
    if flags in _RUNS:
        return _RUNS[flags]
    d = _probe_dir()
    try:
        env = dict(os.environ, **{SWITCH: "1"})       # the shell "forgot" it on
        proc = subprocess.run([sys.executable, str(RUNNER), "--dir", str(d), *flags],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env, timeout=120)
        print(proc.stdout)
        _RUNS[flags] = (proc.returncode, proc.stdout, (d / "d_ran").exists())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return _RUNS[flags]


def test_loopback_is_allowed():
    _rc, out, _ = run()
    assert "PASS test_a_local.py: 1/1" in out, out


def test_a_file_that_reaches_out_is_red_with_every_address_even_if_it_swallowed_the_refusal():
    rc, out, _ = run()
    assert rc == 1, rc
    line = [l for l in out.splitlines() if l.startswith("FAIL test_b_net.py:")]
    assert line, out
    for addr in ("cf0609-lookup.example:443", "203.0.113.7:443", "cf0609-urllib.example"):
        assert addr in line[0], (addr, line[0])
    assert "reached for the network" in line[0] and "docs/test-hygiene.md" in line[0], line[0]
    assert "FAILED test_b_net.py: reached for the network" in out, out


def test_a_child_that_is_not_python_lands_in_the_proxy_trap():
    if not shutil.which("curl"):
        print("     no curl on this machine - the trap check has nothing to drive")
        return
    _rc, out, _ = run()
    line = [l for l in out.splitlines() if l.startswith("FAIL test_c_curl.py:")]
    assert line and "cf0609-curl.example" in line[0] and "(proxy)" in line[0], out


def test_the_plain_run_skips_the_live_file_with_one_line():
    _rc, out, d_ran = run()
    assert "skipped live: test_d_live.py - probe: talks to the world" in out, out
    assert "--- test_d_live.py ---" not in out and not d_ran, out


def test_the_plain_run_turns_a_live_switch_off_and_keeps_the_guard_on():
    _rc, out, _ = run()
    assert f"skipped live: test_e_part.py - the part behind {SWITCH}=1" in out, out
    part = out.split("--- test_e_part.py ---", 1)[1]
    assert "switch off" in part and "guard on" in part, part


def test_the_total_counts_only_the_files_that_ran():
    _rc, out, _ = run()
    assert "TOTAL 4/4 passed in 4 files - 2 FAILED" in out, out
    assert "skipped live: 2 (python3 tests/run_tests.py --live)" in out, out


def test_live_runs_only_the_live_files_switch_on_network_open():
    rc, out, d_ran = run("--live")
    assert rc == 0, out
    assert d_ran and "PASS test_d_live.py: 1/1" in out, out
    part = out.split("--- test_e_part.py ---", 1)[1]
    assert "switch on" in part and "guard off" in part, part
    for other in ("test_a_local.py", "test_b_net.py", "test_c_curl.py"):
        assert f"--- {other} ---" not in out, other
    assert "TOTAL 2/2 passed in 2 files" in out, out


def test_list_plans_and_runs_nothing():
    rc, out, d_ran = run("--live", "--list")
    assert rc == 0 and not d_ran, out
    assert "would run: test_d_live.py" in out and f"would run: test_e_part.py ({SWITCH}=1)" in out, out
    assert "---" not in out and "TOTAL" not in out, out


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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
