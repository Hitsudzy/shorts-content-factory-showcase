#!/usr/bin/env python3
"""CF-0421: the Publisher's configuration - paths to the secrets, never the secrets.

`agents/publisher/.env` (gitignored; `.env.example` beside it is the committed
shape) carries four things: where the OAuth client secret lies, where the
refresh token is kept, which channel the token must belong to, and the category
and language the uploads go out with - plus the OAuth app's publishing status
(`PUBLISHER_OAUTH_MODE`, CF-0607) and the token's reminder settings. The process environment overrides the
file, key by key.

The one rule this module enforces rather than documents: **a secret path inside
a git working tree is refused.** A client secret or a token that sits in a
checkout is one `git add -A` away from the remote - this repository's own
post-commit hook pushes on every commit - so the check is not about this
checkout only: any directory with a `.git` above the file refuses it.
"""
import os
from dataclasses import dataclass
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
ENV_FILE = AGENT / ".env"

DEFAULT_SECRETS_DIR = "~/.config/content-factory/publisher"
DEFAULTS = {
    "PUBLISHER_CLIENT_SECRET_FILE": f"{DEFAULT_SECRETS_DIR}/client_secret.json",
    "PUBLISHER_TOKEN_FILE": f"{DEFAULT_SECRETS_DIR}/youtube.oauth-token.json",
    "PUBLISHER_CHANNEL_ID": "",
    "PUBLISHER_CATEGORY_ID": "24",
    "PUBLISHER_LANGUAGE": "en",
    # CF-0607: the publishing status of the OAuth app in Google Auth Platform -
    # `testing` (the default) or `production` (after Audience -> Publish app).
    # It decides the refresh token's term: Testing - PUBLISHER_TOKEN_LIFETIME_DAYS;
    # Production - no fixed term (it lives until revoked or unused for six months,
    # https://developers.google.com/identity/protocols/oauth2#expiration).
    "PUBLISHER_OAUTH_MODE": "testing",
    # CF-0589: the OAuth app is in Testing - Google lets its refresh token live
    # 7 days from the consent; the reminder comes this many hours before.
    # Used only in the `testing` mode (CF-0607).
    "PUBLISHER_TOKEN_LIFETIME_DAYS": "7",
    "PUBLISHER_TOKEN_REMIND_HOURS": "24",
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    client_secret_file: Path
    token_file: Path
    channel_id: str
    category_id: str
    language: str
    env_file: Path
    token_lifetime_days: float = 7.0
    token_remind_hours: float = 24.0
    oauth_mode: str = "testing"


def read_env_file(path):
    """KEY=VALUE lines; `#` comments and blank lines skipped, one pair of
    surrounding quotes stripped. A missing file is an empty mapping."""
    p = Path(path)
    if not p.is_file():
        return {}
    out = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def inside_git_tree(path):
    """The working tree (a directory holding `.git`) that contains `path`, or None."""
    p = Path(path).expanduser().resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _secret_path(key, value):
    if not value:
        raise ConfigError(f"{key} is empty - set it in {ENV_FILE} (see .env.example)")
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ConfigError(f"{key}={value}: give an absolute path (or ~/...), outside any git tree")
    tree = inside_git_tree(p)
    if tree is not None:
        raise ConfigError(f"{key}={p}: lies inside the git working tree {tree} - a secret there "
                          f"is one commit away from the remote. Keep it outside, e.g. "
                          f"{DEFAULT_SECRETS_DIR}/")
    return p


def _positive(key, value):
    try:
        n = float(str(value).strip())
    except ValueError:
        raise ConfigError(f"{key}={value!r}: give a positive number") from None
    if n <= 0:
        raise ConfigError(f"{key}={value!r}: give a positive number")
    return n


OAUTH_MODES = ("testing", "production")


def _oauth_mode(value):
    mode = str(value or "").strip().lower() or "testing"
    if mode not in OAUTH_MODES:
        raise ConfigError(f"PUBLISHER_OAUTH_MODE={value!r}: testing or production - the publishing "
                          f"status of the OAuth app in Google Auth Platform (CF-0607)")
    return mode


def load(env_file=None, environ=None):
    """The configuration: defaults <- the .env file <- the process environment."""
    env_path = Path(env_file) if env_file else ENV_FILE
    values = dict(DEFAULTS)
    values.update({k: v for k, v in read_env_file(env_path).items() if k in DEFAULTS})
    env = os.environ if environ is None else environ
    values.update({k: env[k] for k in DEFAULTS if env.get(k)})
    return Config(
        client_secret_file=_secret_path("PUBLISHER_CLIENT_SECRET_FILE",
                                        values["PUBLISHER_CLIENT_SECRET_FILE"]),
        token_file=_secret_path("PUBLISHER_TOKEN_FILE", values["PUBLISHER_TOKEN_FILE"]),
        channel_id=values["PUBLISHER_CHANNEL_ID"].strip(),
        category_id=values["PUBLISHER_CATEGORY_ID"].strip() or "24",
        language=values["PUBLISHER_LANGUAGE"].strip() or "en",
        env_file=env_path,
        token_lifetime_days=_positive("PUBLISHER_TOKEN_LIFETIME_DAYS",
                                      values["PUBLISHER_TOKEN_LIFETIME_DAYS"]),
        token_remind_hours=_positive("PUBLISHER_TOKEN_REMIND_HOURS",
                                     values["PUBLISHER_TOKEN_REMIND_HOURS"]),
        oauth_mode=_oauth_mode(values["PUBLISHER_OAUTH_MODE"]),
    )
