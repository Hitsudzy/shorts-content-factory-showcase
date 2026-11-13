#!/usr/bin/env python3
"""CF-0609: the shared half of "a test does not go to the network and does not
read live data" - what every repository's `tests/run_tests.py` does the same
way. The rule is in docs/test-hygiene.md; the root runner and each agent's
runner load this file by path (`spec_from_file_location`, from the factory
checkout - `_runlog.factory_root()` in an agent), as they load
shared/timeout_guard.py and shared/summary_line_guard.py: one copy of the rule
(the CF-0159 drift).

  * network: `network_off_env` - the environment of a file that runs with the
    network off (shared/no_network first on PYTHONPATH, its switch, its log,
    the proxy trap in every proxy variable, loopback exempt, the libraries'
    offline switches); `ProxyTrap` - the listener the proxies point at;
    `network_reaches` - what a file reached for (the guard's log + the trap),
    non-empty = FAILED; `network_open_env` - `--live`, the guard off;
  * live tree (CF-0621): `live_tree_env` - the part of `network_off_env` that
    hands the child the live directories (`pipeline/`, `publish/`,
    `shared/footage/` of every checkout that is the factory's working disk) for
    the audit hook in shared/no_network/sitecustomize.py; `live_tree_reads` -
    what a file opened or listed there, non-empty = FAILED;
  * live tests: `live_marks` (`LIVE_TEST = "why"` / `LIVE_ENV = "SWITCH"` in the
    file, read by AST), `live_registry` (the live-monitor registry beside the
    tests: `_real_batches.py` at the root, `_live_monitors.py` in an agent),
    `plan` - what a plain run and a `--live` run start, with which switches,
    and the `skipped live:` lines.

Stdlib only, nothing imported from beside this file.
"""
import ast
import json
import os
import socketserver
import threading
from pathlib import Path

# The network guard. The directory goes first on the PYTHONPATH of
# every file the plain run starts; its sitecustomize refuses what leaves the
# machine and writes it to NET_LOG_ENV. The proxy variables point the children
# that are not Python at the trap below; loopback is exempt from the proxies.
NET_GUARD_DIR = Path(__file__).resolve().parent / "no_network"
NET_SWITCH_ENV = "RUN_TESTS_NO_NETWORK"
NET_LOG_ENV = "RUN_TESTS_NET_LOG"
NET_FILE_ENV = "RUN_TESTS_FILE"
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
NO_PROXY = "localhost,127.0.0.1,::1"
OFFLINE_SWITCHES = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
NET_HINT = "mock it, or mark the test live (LIVE_TEST / LIVE_ENV, docs/test-hygiene.md)"
# The live-monitor registries a runner reads by AST: the root's and an agent's.
LIVE_REGISTRIES = ("_real_batches.py", "_live_monitors.py")

# CF-0621: the live tree, watched by an audit hook in the child (the open, not
# the spelling - shared/live_tree_guard.py reads only the syntax and misses a
# path built through a variable: `for root in (FACTORY_ROOT, ...): Path(root) /
# "pipeline/..."`). The same directories and tracked tables as
# live_tree_guard.LIVE_CHAIN_DIRS / TRACKED_TABLES (not imported: this file
# stands alone).
LIVE_DIRS = ("pipeline", "publish", "shared/footage")
LIVE_TRACKED = ("pipeline/runs.jsonl", "pipeline/RUNS.md")
LIVE_ROOTS_ENV = "RUN_TESTS_LIVE_ROOTS"          # the child's: directories the hook watches
LIVE_EXEMPT_ENV = "RUN_TESTS_LIVE_EXEMPT"        # the child's: tracked files inside them
LIVE_CHECKOUTS_ENV = "RUN_TESTS_LIVE_CHECKOUTS"  # the runner's: which checkouts are live (a self-test's fake one)
# The verdict: "strict" (the default since 2026-10-11, CF-0683 - the debt of
# the existing tests is zero in the root and all five agents) - a file that
# opened the live tree is FAILED; "report" - the kill switch,
# `RUN_TESTS_LIVE_TREE=report`: a `LIVE-TREE` line per file and a count before
# TOTAL, the file not FAILED. Every repository's runner reads the mode through
# live_tree_strict() here, so this one line decides it for all of them.
LIVE_TREE_MODE_ENV = "RUN_TESTS_LIVE_TREE"
LIVE_TREE_DEFAULT = "strict"
LIVE_HINT = ("point the code at a temp root or a frozen copy, or mark the test live "
             "(LIVE_TEST / LIVE_ENV, docs/test-hygiene.md)")


class ProxyTrap:
    """CF-0609: a listener on loopback that the proxy variables of every test
    point at. A child that honours them (curl, git, the claude CLI, urllib,
    requests) sends its first line here instead of out; the line is written
    down against the file that is running - `CONNECT host:443` or `GET
    http://host/...` - and answered 403. Nothing leaves the machine."""

    def __init__(self):
        trap = self
        self.current = None
        self.hits = []
        self.lock = threading.Lock()

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.settimeout(5)
                    data = b""
                    while b"\n" not in data and len(data) < 8192:
                        chunk = self.request.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                    first = data.split(b"\n", 1)[0].decode("latin-1").strip()
                    parts = first.split()
                    target = parts[1] if len(parts) > 1 else (first or "(no request line)")
                    with trap.lock:
                        trap.hits.append((trap.current, f"{target} (proxy)"))
                    self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n"
                                         b"Connection: close\r\n\r\n")
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def begin(self, name):
        with self.lock:
            self.current = name

    def take(self, name):
        with self.lock:
            mine = [what for who, what in self.hits if who == name]
            self.hits = [h for h in self.hits if h[0] != name]
            self.current = None
        return mine

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def network_off_env(env, trap, log_path, name):
    """The environment of a file that runs with the network off (CF-0609)."""
    env = dict(env)
    env["PYTHONPATH"] = os.pathsep.join([str(NET_GUARD_DIR)] + (
        [env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env[NET_SWITCH_ENV] = "1"
    env[NET_LOG_ENV] = str(log_path)
    env[NET_FILE_ENV] = name
    for var in PROXY_VARS:
        env[var] = trap.url
    env["NO_PROXY"] = env["no_proxy"] = NO_PROXY
    # The libraries' own offline switches: a model already in the local cache
    # is a dependency like an installed package; asking the hub whether it
    # changed is the network (CF-0609: test_insert_library's CLIP HEAD).
    env.update(OFFLINE_SWITCHES)
    return live_tree_env(env)


def network_open_env(env):
    """`--live`: the guard is off even if the shell (or an outer run) left it
    on - its switch gone, its directory off the PYTHONPATH."""
    env = dict(env)
    for var in (NET_SWITCH_ENV, NET_LOG_ENV, NET_FILE_ENV, LIVE_ROOTS_ENV, LIVE_EXEMPT_ENV):
        env.pop(var, None)
    if env.get("PYTHONPATH"):
        kept = [p for p in env["PYTHONPATH"].split(os.pathsep) if p and Path(p) != NET_GUARD_DIR]
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            env.pop("PYTHONPATH")
    return env


def network_reaches(log_path, trap, name):
    """Sorted addresses a file reached for: the guard's log and the trap's."""
    out = []
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("kind") == "live":         # the live-tree hook's line (CF-0621)
            continue
        out.append(f"{rec.get('address')} ({rec.get('what')})")
    if trap is not None:
        out.extend(trap.take(name))
    return sorted(set(out))


def live_checkouts(env=None):
    """The checkouts whose live directories a plain run watches (CF-0621):
    `$RUN_TESTS_LIVE_CHECKOUTS` when the runner's environment names them (a
    self-test's fake checkout), else the checkout this file is in, the main
    checkout above it when it is a worktree (`<main>/.worktrees/<name>`), and
    `~/shorts-content-factory` - the factory's working disk."""
    env = os.environ if env is None else env
    given = env.get(LIVE_CHECKOUTS_ENV)
    if given is not None:
        return [Path(p) for p in given.split(os.pathsep) if p]
    here = Path(__file__).resolve().parent.parent
    out = [here]
    if ".worktrees" in here.parts:
        out.append(Path(*here.parts[:here.parts.index(".worktrees")]))
    home = Path.home() / "shorts-content-factory"
    if home.is_dir():
        out.append(home)
    return list({c.resolve(): c for c in reversed(out)}.values())[::-1]


def live_tree_env(env, checkouts=None):
    """`env` with the live directories for the child's audit hook (CF-0621):
    `pipeline/`, `publish/`, `shared/footage/` of every live checkout (each as
    written and as resolved), and the tracked tables inside them that a test
    may read. Called by `network_off_env`; `network_open_env` drops both."""
    env = dict(env)
    roots, exempt = [], []
    for c in (live_checkouts(env) if checkouts is None else checkouts):
        for form in (os.path.abspath(c), os.path.realpath(c)):
            roots.extend(os.path.join(form, *d.split("/")) for d in LIVE_DIRS)
            exempt.extend(os.path.join(form, *t.split("/")) for t in LIVE_TRACKED)
    env[LIVE_ROOTS_ENV] = os.pathsep.join(dict.fromkeys(roots))
    env[LIVE_EXEMPT_ENV] = os.pathsep.join(dict.fromkeys(exempt))
    return env


def live_tree_strict(env=None):
    """True when a live-tree open makes the file FAILED: `$RUN_TESTS_LIVE_TREE`
    unset, empty or `strict` (LIVE_TREE_DEFAULT); False under the kill switch
    `RUN_TESTS_LIVE_TREE=report`."""
    env = os.environ if env is None else env
    return (env.get(LIVE_TREE_MODE_ENV) or LIVE_TREE_DEFAULT).strip().lower() == "strict"


def live_tree_reads(log_path):
    """Sorted `path (event)` the file (or a Python child of it) opened or
    listed inside the live tree - the hook's lines in the network log."""
    out = []
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("kind") == "live":
            by = f", {rec['where']}" if rec.get("where") else ""
            out.append(f"{rec.get('path')} ({rec.get('what')}{by})")
    return sorted(set(out))


def _top_level_strings(path, names):
    """{name: str} for top-level `NAME = "literal"` (and dict literals) in a
    file, read by AST - a live marker is found without importing the file."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def live_marks(test_file):
    """(why or None, switch or None): `LIVE_TEST = "why"` makes the whole file live;
    `LIVE_ENV = "SWITCH"` names the switch of its live part (CF-0609)."""
    lit = _top_level_strings(test_file, ("LIVE_TEST", "LIVE_ENV"))
    why, switch = lit.get("LIVE_TEST"), lit.get("LIVE_ENV")
    return (why if isinstance(why, str) and why.strip() else None,
            switch if isinstance(switch, str) and switch.strip() else None)


def live_registry(where):
    """(switch, {file names}) of the live-monitor registry beside the tests -
    `_real_batches.py` at the root, `_live_monitors.py` in an agent."""
    for reg in LIVE_REGISTRIES:
        lit = _top_level_strings(where / reg, ("LIVE_ENV", "LIVE_MONITORS"))
        switch, mons = lit.get("LIVE_ENV"), lit.get("LIVE_MONITORS")
        if isinstance(switch, str) and isinstance(mons, dict):
            return switch, {str(k).split("::")[0] for k in mons}
    return None, set()


def plan(where, test_files, live_mode):
    """[(file, {switch: "1"}, why-live or None)] to run, [skip lines], {all switches}.

    Plain run: every file but the whole-live ones, all switches off, a `skipped
    live:` line per live part left out. `--live`: only files with a live part,
    their switches on."""
    reg_switch, reg_files = live_registry(where)
    switches = {reg_switch} if reg_switch else set()
    marks = {}
    for f in test_files:
        why, switch = live_marks(f)
        own = [switch] if switch else []
        if f.name in reg_files:
            own.append(reg_switch)
        marks[f] = (why, own)
        switches.update(own)
    runs, skipped = [], []
    for f in test_files:
        why, own = marks[f]
        if live_mode:
            if why or own:
                runs.append((f, {s: "1" for s in own}, why or "the part behind " +
                             " and ".join(f"{s}=1" for s in own)))
            continue
        if why:
            skipped.append(f"skipped live: {f.name} - {why}")
            continue
        runs.append((f, {}, None))
        if own:
            skipped.append(f"skipped live: {f.name} - the part behind "
                           f"{' and '.join(f'{s}=1' for s in own)}")
    return runs, skipped, switches
