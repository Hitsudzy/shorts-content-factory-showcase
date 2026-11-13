"""CF-0360: the one place in this repo that finds `YOUTUBE_API_KEY`.

    from _apikey import youtube_api_key

    key = youtube_api_key()      # None when there is none

Order: the environment first, else this repository's own `.env`
(`agents/trend-hunter/.env`, the file `README.md` step 1 fills in). Batch
`example-film/2026-09-23T1722Z` lost its hunter stage to "missing
YOUTUBE_API_KEY" while the key sat in that file: the SKILL said "from
environment" and the environment was the orchestrator's memory to
`set -a; source .env`. What is held by prose and memory is a hole (CF-0317),
so every script that talks to the API reads the key through here and the
file is found by the script itself - the same order the root's supplement step
uses for the hunter (`shared/runlog/supplement.py`, `hunter_env`, CF-0350).

The value is never printed, logged or written anywhere: this module only
returns it. `key_source()` says *where* it came from, for messages.

`TREND_HUNTER_ROOT` points the lookup at another repository root - tests use it
with a temporary `.env`, so the real one is never read or touched by them.
"""
import os
from pathlib import Path

API_KEY = "YOUTUBE_API_KEY"
REPO = Path(__file__).resolve().parents[1]


def repo_root():
    env = os.environ.get("TREND_HUNTER_ROOT")
    return Path(env) if env else REPO


def env_file():
    return repo_root() / ".env"


def read_env_file(path):
    """`KEY=VALUE` lines of a dotenv file as `set -a; source` reads the plain
    ones: comments, blanks and `export ` skipped, one layer of quotes off.
    A missing or unreadable file is an empty dict."""
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def _lookup(name=API_KEY):
    value = os.environ.get(name)
    if value:
        return value, "environment"
    value = read_env_file(env_file()).get(name)
    if value:
        return value, str(env_file())
    return None, None


def youtube_api_key(name=API_KEY):
    """The key from the environment, else from the repo's `.env`; None if neither."""
    return _lookup(name)[0]


def key_source(name=API_KEY):
    """`"environment"`, the `.env` path, or None - never the value."""
    return _lookup(name)[1]


MISSING = f"missing {API_KEY}: not in the environment nor in this repo's .env"
