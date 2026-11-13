"""CF-0609: the network is off for a test - the Python half of the guard.

`tests/run_tests.py` puts this directory first on the PYTHONPATH of every test
file it starts, so the interpreter imports this module at start-up (`site`
imports `sitecustomize`), before the test's first line - and so does every
Python child the test starts, since the environment is inherited. With
`RUN_TESTS_NO_NETWORK=1` it replaces

    socket.socket.connect / connect_ex / sendto   (AF_INET, AF_INET6)
    socket.getaddrinfo / gethostbyname / gethostbyname_ex

with versions that let loopback through (127.0.0.0/8, ::1, `localhost`,
0.0.0.0, the machine's own host name; AF_UNIX is never touched - the console
and the server tests talk to localhost) and refuse everything else with
`NetworkBlocked` (an OSError, so production code takes its offline path rather
than dying somewhere odd).

A refusal alone is not a verdict: code that catches OSError would turn it into
a quiet "offline" and the test would stay green. So every refusal is also
written, one JSON line, to `$RUN_TESTS_NET_LOG` with the file
(`$RUN_TESTS_FILE`), the address and what was tried; the runner reads that log
after the file and makes the file FAILED with the address, whatever the file
itself printed. The other half - for children that are not Python (curl, git,
the `claude` CLI) - is the proxy trap in the runner (HTTP(S)_PROXY / ALL_PROXY
point at a listener of the runner's own that writes down the host and answers
403). See docs/test-hygiene.md.

CF-0621: the same start-up installs the live-tree watch when the runner names
the live directories (`$RUN_TESTS_LIVE_ROOTS`, with the tracked tables inside
them in `$RUN_TESTS_LIVE_EXEMPT` - `test_hygiene.live_tree_env`): an audit hook
(`sys.addaudithook`) on `open` (the builtin, `io.open_code`, `os.open`) that
writes every file opened inside them into the same log (`"kind": "live"`, one line per path, at
most 50 per process). It refuses nothing - the runner makes the file FAILED
from the log, as for the network. This is the open, not the spelling: a path
built through a loop variable or a production default is caught as well as
`ROOT / "pipeline"` (shared/live_tree_guard.py, the static half, reads only
the syntax).

Agents load the same file: their runner puts `<factory>/shared/no_network`
first on PYTHONPATH (one copy of the rule - the CF-0159 drift).

Whatever `sitecustomize` would have been imported without this directory (a
venv's, a distribution's) is imported after the guard, so shadowing it costs
nothing.
"""
import os
import sys

ENV_SWITCH = "RUN_TESTS_NO_NETWORK"
ENV_LOG = "RUN_TESTS_NET_LOG"
ENV_FILE = "RUN_TESTS_FILE"
HINT = "mock the call, or mark the test live (LIVE_TEST / LIVE_ENV, docs/test-hygiene.md)"


class NetworkBlocked(OSError):
    """A test reached past loopback while the network is off (CF-0609)."""


def _record(what, address):
    """One JSON line into the runner's log; never raises (the log is advisory
    to the code path, binding to the verdict)."""
    path = os.environ.get(ENV_LOG)
    if not path:
        return
    try:
        import json
        line = json.dumps({"file": os.environ.get(ENV_FILE) or os.path.basename(sys.argv[0] or "?"),
                           "pid": os.getpid(), "argv0": (sys.argv[0] if sys.argv else ""),
                           "what": what, "address": address}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def install():
    import ipaddress
    import socket

    try:
        own = {socket.gethostname().lower()}
    except Exception:
        own = set()
    own |= {h + ".local" for h in own if not h.endswith(".local")}
    names = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", ""} | own

    def loopback(host):
        if host is None:
            return True
        if isinstance(host, (bytes, bytearray)):
            host = bytes(host).decode("ascii", "replace")
        h = str(host).strip().strip("[]").lower()
        if h in names or h.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(h.split("%", 1)[0])
        except ValueError:
            return False
        return ip.is_loopback or ip.is_unspecified

    def refuse(what, host, port=None):
        address = f"{host}:{port}" if port is not None else str(host)
        _record(what, address)
        raise NetworkBlocked(f"CF-0609: the network is off in tests - "
                             f"{os.environ.get(ENV_FILE) or sys.argv[0]} tried {what} {address}; {HINT}")

    def judged(sock, address):
        """(host, port) when this address leaves the machine, else None."""
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return None
        if not isinstance(address, tuple) or not address:
            return None
        host = address[0]
        port = address[1] if len(address) > 1 else None
        return None if loopback(host) else (host, port)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    real_gethostbyname_ex = socket.gethostbyname_ex

    def connect(self, address):
        bad = judged(self, address)
        if bad:
            refuse("connect", *bad)
        return real_connect(self, address)

    def connect_ex(self, address):
        bad = judged(self, address)
        if bad:
            refuse("connect", *bad)
        return real_connect_ex(self, address)

    def sendto(self, data, *rest):
        address = rest[-1] if rest else None
        bad = judged(self, address)
        if bad:
            refuse("sendto", *bad)
        return real_sendto(self, data, *rest)

    def getaddrinfo(host, port, *args, **kwargs):
        if not loopback(host):
            refuse("getaddrinfo", host, port)
        return real_getaddrinfo(host, port, *args, **kwargs)

    def gethostbyname(host):
        if not loopback(host):
            refuse("gethostbyname", host)
        return real_gethostbyname(host)

    def gethostbyname_ex(host):
        if not loopback(host):
            refuse("gethostbyname_ex", host)
        return real_gethostbyname_ex(host)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname_ex
    socket.NetworkBlocked = NetworkBlocked


LIVE_ROOTS = "RUN_TESTS_LIVE_ROOTS"
LIVE_EXEMPT = "RUN_TESTS_LIVE_EXEMPT"
LIVE_EVENT = "open"
LIVE_CAP = 50


def install_live_watch(roots, exempt):
    """CF-0621: the audit hook that writes down every file opened inside the
    live directories (read or write). A listing and a directory are not judged
    (a walk over the checkout, `shutil.rmtree`'s directory descriptors); the
    file opened from it is. Cheap on the hot path: one comparison per audit
    event, a normpath and a tuple `startswith` per open."""
    roots = tuple(r.rstrip(os.sep) for r in roots if r)
    if not roots:
        return
    prefixes = tuple(r + os.sep for r in roots)
    rootset = frozenset(roots)
    exempt = frozenset(exempt)
    seen = set()
    fspath, fsdecode, isabs = os.fspath, os.fsdecode, os.path.isabs
    join, normpath, getcwd, isdir = os.path.join, os.path.normpath, os.getcwd, os.path.isdir

    def hook(event, args):
        if event != LIVE_EVENT:
            return
        path, mode = args[0], args[1]
        if path is None or isinstance(path, int):     # a descriptor: its own open was judged
            return
        try:
            path = fspath(path)
            if isinstance(path, bytes):
                path = fsdecode(path)
            if not isabs(path):
                if mode is None:
                    # os.open: the name may be relative to a dir_fd the event
                    # does not carry (shutil.rmtree of a temp tree) - not judged
                    return
                path = join(getcwd(), path)
            path = normpath(path)
        except Exception:
            return
        if not (path in rootset or path.startswith(prefixes)):
            return
        if path in exempt or path in seen or len(seen) >= LIVE_CAP or isdir(path):
            return                                    # a directory is a listing, not a read
        seen.add(path)
        _record_live(event, path, _where())

    sys.addaudithook(hook)


def _where():
    """`file:line` of the innermost frame outside the standard library and
    this file - the code that opened the path, for the runner's line."""
    try:
        import sysconfig
        std = tuple(os.path.realpath(sysconfig.get_paths()[k]) + os.sep
                    for k in ("stdlib", "platstdlib"))
        f = sys._getframe(2)
        while f is not None:
            name = f.f_code.co_filename
            if (name != __file__ and not name.startswith("<")
                    and not os.path.realpath(name).startswith(std)):
                return f"{os.path.basename(name)}:{f.f_lineno}"
            f = f.f_back
    except Exception:
        pass
    return None


def _record_live(what, path, where=None):
    log = os.environ.get(ENV_LOG)
    if not log:
        return
    try:
        import json
        line = json.dumps({"kind": "live", "file": os.environ.get(ENV_FILE)
                           or os.path.basename(sys.argv[0] if sys.argv else "?"),
                           "pid": os.getpid(), "what": what, "path": path, "where": where}, ensure_ascii=False)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _chain():
    """Import the sitecustomize this directory shadows, if there is one."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        import importlib.machinery
        import importlib.util
        rest = [p for p in sys.path if os.path.abspath(p or ".") != here]
        spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules["_shadowed_sitecustomize"] = module
        spec.loader.exec_module(module)
    except Exception as exc:          # a broken foreign sitecustomize is not ours to die of
        print(f"[no_network] the shadowed sitecustomize failed: {exc!r}", file=sys.stderr)


if os.environ.get(ENV_SWITCH) == "1":
    install()
if os.environ.get(LIVE_ROOTS) and os.environ.get(ENV_LOG):
    install_live_watch(os.environ[LIVE_ROOTS].split(os.pathsep),
                       os.environ.get(LIVE_EXEMPT, "").split(os.pathsep))
_chain()
