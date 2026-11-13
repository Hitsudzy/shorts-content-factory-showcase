"""CC-0003: `python3 -m api serve|openapi|launchd` (run from the root of the
factory, or with it on PYTHONPATH).

    python3 -m api serve                  # CC_API_HOST:CC_API_PORT (127.0.0.1:8790)
    python3 -m api openapi                # rewrite api/openapi.json from the app
    python3 -m api openapi --check        # exit 1 when api/openapi.json is not the app's
    python3 -m api launchd --print        # the launchd plist on stdout, how to install on
                                          # stderr - installed only on the user's word
    python3 -m api password               # CC-0036: a password (getpass, or stdin's first
                                          # line) -> `CC_PASSWORD_HASH=...` for the environment

`serve` says whether it writes (CC-0058): only in the working factory - the
main checkout on `main` - or with the developer's `CC_API_WRITES=dev` (a
warning then, and one per write).

Stdlib up to the point it needs FastAPI: without it, it re-runs itself under
the root's `.venv/bin/python3` (requirements.txt), and says how to make one
when there is none. Exit 0; 1 on a failed --check; 2 on a bad call.
"""
import argparse
import getpass
import importlib.util
import json
import os
import sys
from pathlib import Path

from . import API_VERSION, auth
from .settings import CODE, Settings, SettingsError

VENV_PY = CODE / ".venv" / "bin" / "python3"
OPENAPI = CODE / "api" / "openapi.json"
LABEL = "com.example-film.cc-api"
TEMPLATE = CODE / "scripts" / "launchd" / f"{LABEL}.plist.template"
TASK = "CC-0003"


def _need_fastapi():
    """Return when FastAPI imports here; else re-exec under the root venv or stop."""
    if importlib.util.find_spec("fastapi") and importlib.util.find_spec("uvicorn"):
        return
    # sys.prefix, not sys.executable: a venv's python3 is a symlink to the base
    # interpreter, so the two resolve to the same file
    in_venv = Path(sys.prefix).resolve() == VENV_PY.parent.parent.resolve()
    if VENV_PY.exists() and not in_venv and os.environ.get("CC_API_REEXEC") != "1":
        env = dict(os.environ, CC_API_REEXEC="1",
                   PYTHONPATH=os.pathsep.join([str(CODE)] + [p for p in
                                              os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]))
        os.execve(str(VENV_PY), [str(VENV_PY), "-m", "api", *sys.argv[1:]], env)
    sys.stderr.write(f"api: FastAPI is not installed for {sys.executable} and there is no "
                     f"root venv ({VENV_PY}). Make it:\n"
                     f"  python3 -m venv .venv && .venv/bin/python3 -m pip install -r requirements.txt\n")
    sys.exit(2)


def openapi_text(app=None):
    """The contract as the app gives it - the default settings, never the
    environment's (the file in git is one for everybody)."""
    if app is None:
        from .app import create_app
        app = create_app(Settings(), token="openapi")
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plist_text(settings, python=None, path_env=None, log=None):
    text = TEMPLATE.read_text(encoding="utf-8")
    root = Path(settings.factory_root)
    subst = {"LABEL": LABEL, "PYTHON": python or str(VENV_PY), "CODE": str(CODE),
             "HOST": settings.host, "PORT": str(settings.port), "ROOT": str(root),
             "DIST": str(settings.frontend_dist), "BASE": settings.base_path,
             "LOG": log or str(CODE / "api" / "serve.log"),
             # CC-0036: the password's hash only when the environment has one
             "AUTH_ENV": (f"<key>CC_PASSWORD_HASH</key>\n        <string>"
                          f"{_xml(settings.password_hash)}</string>"
                          if settings.password_hash else ""),
             "PATH": path_env if path_env is not None else os.environ.get("PATH", "/usr/bin:/bin")}
    for k, v in subst.items():
        text = text.replace("{{" + k + "}}", v if k == "AUTH_ENV" else _xml(v))
    return text


def password_line(stdin=None, ask=None, out=None):
    """CC-0036: `CC_PASSWORD_HASH=<hash>` for a password typed twice (a terminal)
    or read from stdin's first line (a pipe). The password is never printed."""
    stdin = stdin or sys.stdin
    out = out or sys.stdout
    if ask is None and stdin.isatty():
        ask = getpass.getpass
    if ask is not None:
        pw = ask("Пароль центра: ")
        if pw != ask("Ещё раз: "):
            print("api password: пароли не совпали - ничего не напечатано", file=sys.stderr)
            return 2
    else:
        pw = stdin.readline().rstrip("\r\n")
    if not pw:
        print("api password: пустой пароль - ничего не напечатано", file=sys.stderr)
        return 2
    out.write(f"CC_PASSWORD_HASH={auth.hash_password(pw)}\n")
    print("api password: строку - в окружение сервера (CC_PASSWORD_HASH, вместе с CC_BIND); "
          "сам пароль нигде не хранится", file=sys.stderr)
    return 0


def install_commands():
    dest = f"~/Library/LaunchAgents/{LABEL}.plist"
    return [f"# {TASK}: the command center's API as a launchd agent - printed, NOT installed.",
            "# Install only on the user's word:",
            f"#   python3 -m api launchd --print > {dest}",
            f"#   launchctl bootstrap gui/$(id -u) {dest}",
            "# Remove:",
            f"#   launchctl bootout gui/$(id -u)/{LABEL} && rm {dest}"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m api", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="serve the API and the built center")
    o = sub.add_parser("openapi", help="write or check api/openapi.json")
    o.add_argument("--check", action="store_true")
    ld = sub.add_parser("launchd", help="print the launchd plist (never installs)")
    ld.add_argument("--print", dest="print_", action="store_true")
    sub.add_parser("version", help="the API's contract version")
    sub.add_parser("password", help="CC-0036: print CC_PASSWORD_HASH for a password "
                                    "(getpass or stdin)")
    ns = ap.parse_args(argv)
    if ns.cmd == "password":       # before the settings: they may be the thing being fixed
        return password_line()
    try:
        settings = Settings.from_env()
    except SettingsError as e:
        print(f"api: {e}", file=sys.stderr)
        return 2

    if ns.cmd == "version":
        print(API_VERSION)
        return 0
    if ns.cmd == "launchd":
        if not ns.print_:
            print("api launchd: only --print - the agent is installed by the user", file=sys.stderr)
            return 2
        sys.stdout.write(plist_text(settings))
        print("\n".join(install_commands()), file=sys.stderr)
        return 0

    _need_fastapi()
    if ns.cmd == "openapi":
        text = openapi_text()
        if ns.check:
            have = OPENAPI.read_text(encoding="utf-8") if OPENAPI.is_file() else ""
            if have != text:
                print(f"api: {OPENAPI.relative_to(CODE)} is not what the app gives - "
                      f"`python3 -m api openapi` and commit it", file=sys.stderr)
                return 1
            print(f"api: {OPENAPI.relative_to(CODE)} matches the app")
            return 0
        OPENAPI.write_text(text, encoding="utf-8")
        print(f"api: wrote {OPENAPI.relative_to(CODE)}")
        return 0

    import uvicorn
    from .app import create_app
    from . import batches, channels
    app = create_app(settings)
    channels.warm(settings.factory_root)   # CC-0041: the first scan of the open batches, now
    batches.warm(settings.factory_root)    # CC-0045: and of the list of the batches going
    print(f"api: http://{settings.host}:{settings.port}{settings.base_path} "
          f"(API {settings.api_prefix}/, center {settings.frontend_dist}, "
          f"factory {settings.factory_root})", flush=True)
    if settings.password_hash:                                    # CC-0036
        print(f"api: login - a client that is not this machine logs in with the password "
              f"(CC_PASSWORD_HASH; sessions in memory, a restart logs everybody out)", flush=True)
    from . import factory
    ok, why = factory.working_factory(settings.factory_root)     # CC-0058
    if ok:
        print("api: writes - the working factory (the main checkout on main)", flush=True)
    elif settings.writes_dev:
        print(f"api: WARNING CC_API_WRITES=dev - writes although {why}; every such write is "
              f"logged (api.writes)", file=sys.stderr, flush=True)
    else:
        print(f"api: read-only - {why} (writes: the working factory, or CC_API_WRITES=dev)",
              flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=False,
                server_header=False, date_header=True, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
