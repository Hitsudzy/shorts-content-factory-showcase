"""CC-0003: the API's settings - from the environment only, never a path of
this machine in the code (the factory moves to Linux/Docker later, ROADMAP).

| variable | default | what |
|---|---|---|
| `CC_API_HOST` | `127.0.0.1` | the address it listens on |
| `CC_BIND` | - | CC-0036: the same address, the name of the home-network opt-in (wins over `CC_API_HOST`; both set and different - refused) |
| `CC_PASSWORD_HASH` | - | CC-0036: the hash of the center's password (`python3 -m api password` prints the line; never the password itself) - a client that is not this machine logs in (`api/auth.py`); a bind that is not loopback without it: refused |
| `CC_API_PORT` | `8790` | the port (CC-0035: the center took 8790 from the retired 2.2 console; 8791 was its port before) |
| `CC_FACTORY_ROOT` | `FACTORY_ROOT`, else this checkout | the factory it reads |
| `CC_FRONTEND_DIST` | `<factory root>/frontend/dist` | the built center it serves |
| `CC_BASE_PATH` | `/` | the path the center is built for (`frontend`: the same variable) |
| `CC_API_ALLOWED_HOSTS` | - | more `host[:port]` the Host check lets in, comma-separated (a name of a container, say) |
| `CC_API_ALLOWED_ORIGINS` | - | more origins a POST may come from (`http://localhost:5173` - the Vite dev server) |
| `CC_API_WRITES` | - | `dev`: the developer's flag (CC-0058) - a development copy (`.worktrees/cc-api`, `release-<v>`) writes too; anything but empty or `dev` is refused |

Stdlib only: `python3 -m api` reads this before it knows whether FastAPI is
there.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Tuple

from .auth import HashError, parse_hash

#: The checkout this package lives in (the code, not necessarily the data).
CODE = Path(__file__).resolve().parents[1]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790
LOOPBACK = ("127.0.0.1", "localhost", "::1")


class SettingsError(ValueError):
    """A variable of the environment has a value the API cannot use."""


def _list(raw):
    return tuple(x.strip() for x in (raw or "").split(",") if x.strip())


def _base(raw):
    b = (raw or "/").strip() or "/"
    if not b.startswith("/"):
        b = "/" + b
    return b if b.endswith("/") else b + "/"


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    factory_root: Path = CODE
    frontend_dist: Path = CODE / "frontend" / "dist"
    base_path: str = "/"
    extra_hosts: Tuple[str, ...] = field(default_factory=tuple)
    extra_origins: Tuple[str, ...] = field(default_factory=tuple)
    #: CC-0058: `CC_API_WRITES=dev` - write outside the working factory too
    writes_dev: bool = False
    #: CC-0036: `CC_PASSWORD_HASH` - a client from elsewhere logs in (`api/auth.py`)
    password_hash: Optional[str] = None

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if environ is None else environ
        bind = (env.get("CC_BIND") or "").strip()
        old = (env.get("CC_API_HOST") or "").strip()
        if bind and old and bind != old:
            raise SettingsError(f"CC_BIND={bind!r} и CC_API_HOST={old!r}: это один адрес "
                                f"под двумя именами - оставьте одно")
        host = bind or old or DEFAULT_HOST
        pw = (env.get("CC_PASSWORD_HASH") or "").strip() or None
        if pw:
            try:
                parse_hash(pw)
            except HashError as e:
                raise SettingsError(str(e))
        raw_port = (env.get("CC_API_PORT") or str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError:
            raise SettingsError(f"CC_API_PORT={raw_port!r}: not a number")
        if not 0 < port < 65536:
            raise SettingsError(f"CC_API_PORT={port}: not a port")
        raw_root = env.get("CC_FACTORY_ROOT") or env.get("FACTORY_ROOT")
        root = Path(raw_root).expanduser().resolve() if raw_root else CODE
        raw_dist = env.get("CC_FRONTEND_DIST")
        dist = Path(raw_dist).expanduser().resolve() if raw_dist else root / "frontend" / "dist"
        raw_writes = (env.get("CC_API_WRITES") or "").strip()
        if raw_writes not in ("", "dev"):
            raise SettingsError(f"CC_API_WRITES={raw_writes!r}: only `dev` (the developer's "
                                f"flag: a development copy writes too) or nothing")
        out = cls(host=host, port=port, factory_root=root, frontend_dist=dist,
                  writes_dev=raw_writes == "dev", password_hash=pw,
                  base_path=_base(env.get("CC_BASE_PATH")),
                  extra_hosts=_list(env.get("CC_API_ALLOWED_HOSTS")),
                  extra_origins=tuple(o.rstrip("/") for o in _list(env.get("CC_API_ALLOWED_ORIGINS"))))
        out.check_bind()
        return out

    def check_bind(self):
        """CC-0036: a bind that is not loopback needs the password's hash -
        SettingsError (in Russian) otherwise; the API does not start."""
        if not self.loopback_only and not self.password_hash:
            raise SettingsError(
                f"адрес {self.host!r} не локальный, а пароля нет: центр открылся бы всей "
                f"сети без входа. Задайте CC_PASSWORD_HASH (строку печатает "
                f"`python3 -m api password`) или слушайте 127.0.0.1")

    # ------------------------------------------------------------ derived
    @property
    def api_prefix(self) -> str:
        """Where the API's routes sit: `<base>api` (`/api` by default)."""
        return self.base_path + "api"

    @property
    def loopback_only(self) -> bool:
        """Listening on loopback: then a request from anywhere else is refused
        too (a proxy on this machine would be the only way in)."""
        return self.host in LOOPBACK or self.host.startswith("127.")

    def allowed_hosts(self) -> Tuple[str, ...]:
        """`Host` values a request may carry - this address only (a DNS
        rebinding name gets 403, GET too - as the retired 2.2 console did)."""
        names = ["127.0.0.1", "localhost", "[::1]"]
        if self.host not in ("0.0.0.0", "::", "") and self.host not in LOOPBACK:
            names.append(f"[{self.host}]" if ":" in self.host else self.host)
        hosts = [f"{n}:{self.port}" for n in names]
        if self.port == 80:
            hosts += names
        return tuple(dict.fromkeys(hosts + list(self.extra_hosts)))

    def allowed_origins(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys([f"http://{h}" for h in self.allowed_hosts()]
                                   + list(self.extra_origins)))
