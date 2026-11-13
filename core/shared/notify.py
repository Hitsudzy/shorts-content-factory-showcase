#!/usr/bin/env python3
"""CF-0591: the notification bus - one line to the user at each of his gates,
with a link to the command center (CF-0735) or to the card.

Grill 2026-10-06 (Q11). The orchestrator of 2.2 is a program (`claude -p`),
so the `PushNotification` tool of an interactive Claude Code session is not
there for it: the factory has its own bus. A source hands it an event

    kind     accept | upload | token | empty_slot
             | run_halted | run_done | needs_human | batch_started (CF-0592)
             | reminder (the user's own, CF-0606) | test (`test --send`)
             | request_answer (the operator's answer to the user's free
               request, shared/operator_requests.py, CF-0684)
             | hold_released (a publication hold lifted by itself: its flag
               rests on a scene the script did not take - runlog
               scene-holds, CF-0846)
             | accepted (CF-0925: the user's verdicts on a batch, one
               message per batch - runlog acceptance)
             | uploaded (CF-0925: a video put into Studio on its slot -
               agents/publisher/studio_fields.py record)
             | studio_read (CF-0926: the planned Studio read came to «прочитано» -
               agents/analyst/studio_center.py scheduled_read; a failure the
               user must fix goes as needs_human)
    channel  the channel it is about (None: the whole factory - the token)
    key      the event's identity: one notification per key, a second send of
             the same key is a no-op. A reminder that must go again (the
             token's next term) is a new key - the token's key carries its
             term and its state.
    text     one line (newlines and runs of spaces collapsed, cut at
             TEXT_MAX); anything that looks like a secret is masked.
             CF-0925: `multiline=True` keeps the lines for Telegram - the
             event's `body` (cut at TELEGRAM_MAX), sent as it is with the
             center's link as its last line; the journal's `text` is still
             one line (the lines joined with « · », cut at MULTILINE_TEXT_MAX)
    link     a page of the command center (`http://127.0.0.1:8790/publishing?channel=<c>`,
             CF-0735; built from the old console's anchors by `link_of`)
             or a path (the card, the file to drag into Studio)

and the bus writes one row to the journal and hands the line to every backend
that is switched on.

**The journal** `<root>/notify/sent.jsonl` (gitignored; `NOTIFY_STATE_DIR`
puts it elsewhere): one JSON row per event - `at, kind, channel, key, text,
link, backends {name: "ok" | "error: ..." | "skipped: ..."}`. The key is
looked up there under an exclusive lock, so two processes sending one event
send it once.

**Backends** are chosen by `NOTIFY_BACKENDS` (comma-separated; the
environment first, then `<root>/.env`, which is not in git). The default is
`log` alone.

* `log` - the journal row and one line on stderr (stdout of the sources is
  read by programs: `--json`, the Studio fields' JSON, the orchestrator's
  status lines - a notice there would break them);
* `macos` - `osascript display notification`: a banner on this Mac, nothing
  leaves the machine. Off until the user switches it on;
* `telegram` (CF-0606) - `sendMessage` as plain text (no parse_mode, so
  nothing to escape), a center link named by its page and followed by its
  address (CF-0735: the user opens it on the Mac), cut at Telegram's 4096; the bot token never reaches the
  journal, stderr, an exception or the CLI's output;
* `ntfy`, `telegram`, `webhook` - frames for a phone. Off, and each also needs
  its own address in `.env` (`NOTIFY_NTFY_URL`; `NOTIFY_TELEGRAM_TOKEN` +
  `NOTIFY_TELEGRAM_CHAT`; `NOTIFY_WEBHOOK_URL`). **Switching one on sends the
  line - a channel name, a video title, a slot - to an outside service; that
  is the user's decision** (docs/notifications.md), never a default.

**A notification is never on the critical path.** `send()` does not raise: a
backend that fails is written as `error: ...` in its row and the source goes
on; a journal that cannot be written is said on stderr and the source goes on.

    python3 shared/notify.py send --kind K --key KEY --text "..." [--channel C]
        [--link URL|PATH | --anchor ANCHOR] [--again TAG] [--root DIR]
        # exit 0 sent or already sent (said on the line), 2 bad call
    python3 shared/notify.py list [--kind K] [--channel C] [--limit N] [--root DIR]
    python3 shared/notify.py test [--root DIR]
        # which backends are on and what each would get - through a stand-in
        # backend: nothing is shown, nothing is sent, the journal is untouched
    python3 shared/notify.py remind --at "ЧЧ:ММ | YYYY-MM-DD ЧЧ:ММ [МСК]" TEXT
    python3 shared/notify.py remind --list [--all] | --cancel ID | --due
        # CF-0606: the user's reminders - queued (nothing sent), sent when due
        # by `--due` or by every tick of shared/batch_schedule.py; CF-0617: a
        # reminder no outside backend took is `failed` and goes again next
        # time, `exhausted` after REMINDER_MAX_ATTEMPTS tries (exit 1 for both)
    python3 shared/notify.py test --send [--by WHO] [--via WHERE] [--root DIR]
        # CF-0606: a probe event (kind `test`, a new key each run) to every
        # backend that is on - Telegram included when it is; exit 1 when a
        # backend did not say ok
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0591"
ROOT = Path(__file__).resolve().parent.parent

KINDS = ("accept", "upload", "token", "empty_slot", "run_halted", "run_done",
         "needs_human", "batch_started", "reminder", "test", "request_answer",
         "hold_released", "accepted", "uploaded", "studio_read")
DEFAULT_BACKENDS = ("log",)
EXTERNAL = ("ntfy", "telegram", "webhook")      # the ones that send text off this machine
STATE_ENV = "NOTIFY_STATE_DIR"
BACKENDS_ENV = "NOTIFY_BACKENDS"
DASHBOARD_ENV = "NOTIFY_DASHBOARD_URL"           # legacy name of CENTER_ENV, still read
CENTER_ENV = "NOTIFY_CENTER_URL"
# CF-0735: every link goes to the command center (api/settings.py DEFAULT_PORT,
# CC_BASE_PATH "/"). CC-0035 (center 1.0): the 2.2 console that held 8790 is
# retired and the center took its port; the center's old port 8791 is legacy.
CENTER_URL = "http://127.0.0.1:8790/"
DASHBOARD_URL = CENTER_URL                       # the old name, the same address
OLD_CONSOLE_URL = "http://127.0.0.1:8790/"       # the retired console: `8790/#anchor` links
LEGACY_CENTER_URL = "http://127.0.0.1:8791/"     # the center before CC-0035: `8791/<route>` links
JOURNAL = "sent.jsonl"
TEXT_MAX = 200
MULTILINE_TEXT_MAX = 1000        # CF-0925: the journal's line of a multi-line message
TITLE = "Фабрика"
HTTP_TIMEOUT_S = 10

# What a line must never carry (the token's value, the client secret, a key in
# a URL). The token's own line says its kind and term, never a value - this is
# the second line under that.
SECRET_RES = (
    re.compile(r"ya29\.[0-9A-Za-z_\-]+"),                       # Google access token
    re.compile(r"1//[0-9A-Za-z_\-]{10,}"),                      # Google refresh token
    re.compile(r"GOCSPX-[0-9A-Za-z_\-]+"),                      # Google client secret
    re.compile(r"\b\d{6,}:[0-9A-Za-z_\-]{30,}"),                # a Telegram bot token
    re.compile(r"(?i)\b((?:access_|refresh_)?token|secret|password|api[_-]?key|key)"
               r"(\s*[=:]\s*)[^\s,;&]+"),
    # a long opaque string: mixed case with a digit (a slug is lower case)
    re.compile(r"(?<![0-9A-Za-z_\-])(?=[0-9A-Za-z_\-]*\d)(?=[0-9A-Za-z_\-]*[a-z])"
               r"(?=[0-9A-Za-z_\-]*[A-Z])[0-9A-Za-z_\-]{32,}"),
)
MASK = "***"

# The anchors of the retired 2.2 console: the whole factory's sections, and
# each channel's. The sources still name a place by them, and old journal rows
# hold `8790/#<anchor>`; since CF-0735 `link_of` / `dashboard_url` /
# `center_link` turn them into the command center's routes.
GLOBAL_ANCHORS = ("token", "needs-you", "schedule", "reminders")
CHANNEL_SECTIONS = ("feed", "batch", "acceptance")
# CF-0735: anchor -> the center's route (frontend/src/app/areas.ts); a channel's
# section carries `?channel=<c>` (Publishing and Stats read it).
GLOBAL_ROUTES = {"token": "tokens", "needs-you": "questions", "schedule": "batches",
                 "reminders": "notifications"}
CHANNEL_ROUTES = {"feed": "publishing", "batch": "batches", "acceptance": "videos",
                  "schedule": "batches"}
# The center's areas by route, as its tabs name them.
CENTER_AREAS = {"": "Главная", "channels": "Каналы", "batches": "Батчи", "videos": "Ролики",
                "publishing": "Публикация", "questions": "Вопросы", "stats": "Статистика",
                "memes": "Мемы", "notifications": "Уведомления",
                "tokens": "Токены", "versions": "Версии", "maintenance": "Обслуживание"}
CENTER_NAME = "центр"


# ------------------------------------------------------------------ helpers
def now_iso(now=None):
    if now:
        return str(now)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_env_file(path):
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def settings(root=None, environ=None):
    """The bus's settings: the environment over `<root>/.env`."""
    env = os.environ if environ is None else environ
    vals = read_env_file(Path(root or ROOT) / ".env")
    vals.update({k: v for k, v in env.items() if k.startswith("NOTIFY_")})
    return vals


def state_dir(root=None, environ=None):
    env = os.environ if environ is None else environ
    if env.get(STATE_ENV):
        return Path(env[STATE_ENV]).expanduser()
    return Path(root or ROOT) / "notify"


def journal_path(root=None, environ=None):
    return state_dir(root, environ) / JOURNAL


def enabled(root=None, environ=None):
    raw = settings(root, environ).get(BACKENDS_ENV)
    if raw is None or not raw.strip():
        return list(DEFAULT_BACKENDS)
    return [b.strip().lower() for b in raw.split(",") if b.strip()]


def scrub(text):
    text = str(text or "")
    for rx in SECRET_RES:
        if rx.groups >= 2:
            text = rx.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
        else:
            text = rx.sub(MASK, text)
    return text


def one_line(text, limit=TEXT_MAX):
    text = " ".join(scrub(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# ------------------------------------------------------------------ CF-0925: words for a human
CHANNELS_DIR = "channels"


def _display_names(root=None):
    """{channel id: display_name} of `<root>/channels/*.json`, else this checkout's."""
    for base in ([Path(root)] if root else []) + [ROOT]:
        d = base / CHANNELS_DIR
        if not d.is_dir():
            continue                        # a root with its own channels/ answers alone
        out = {}
        for f in sorted(d.glob("*.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = doc.get("display_name") if isinstance(doc, dict) else None
            if isinstance(name, str) and name.strip():
                out[f.stem] = name.strip()
        return out
    return {}


def _brand_prefix(names):
    """The brand every display name starts with (`Example` of ExampleFilm,
    ExampleTech), cut back so that each name's rest starts with a capital; ""
    when there is none (one channel, or names with nothing in common)."""
    names = [n for n in names if n]
    if len(names) < 2:
        return ""
    pre = os.path.commonprefix(names)
    while pre and not all(len(n) > len(pre) and n[len(pre)].isupper() for n in names):
        pre = pre[:-1]
    return pre if len(pre) >= 3 else ""


def channel_label(channel, root=None):
    """CF-0925: how a message names a channel - its display name without the
    brand (`Reel` for example-film, `Tech` for example-tech); the id itself when
    the channel has no display name. The one place of the rule."""
    if not channel:
        return ""
    try:
        names = _display_names(root)
    except Exception:                                            # noqa: BLE001
        names = {}
    name = names.get(str(channel))
    if not name:
        return str(channel)
    pre = _brand_prefix(list(names.values()))
    return name[len(pre):] if pre and name.startswith(pre) else name


def msk_short(when):
    """`12.11 01:00` (Moscow) for a UTC ISO time or an aware datetime; "" for nothing."""
    if not when:
        return ""
    try:
        return _utc(when).astimezone(msk_zone()).strftime("%d.%m %H:%M")
    except (TypeError, ValueError):
        return str(when)


def msk_day_short(when):
    """`12.11` (Moscow) for a UTC ISO time, an aware datetime or a `YYYY-MM-DD` day."""
    if not when:
        return ""
    s = str(when)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return f"{s[8:10]}.{s[5:7]}"
    try:
        return _utc(when).astimezone(msk_zone()).strftime("%d.%m")
    except (TypeError, ValueError):
        return s


def center_base(environ=None):
    """The command center's address with a trailing slash: NOTIFY_CENTER_URL,
    else the legacy NOTIFY_DASHBOARD_URL, else CENTER_URL."""
    env = os.environ if environ is None else environ
    base = (env.get(CENTER_ENV) or env.get(DASHBOARD_ENV) or CENTER_URL).split("#")[0]
    base = base.split("?")[0]
    return base if base.endswith("/") else base + "/"


def center_route(anchor_=None, root=None):
    """CF-0735: the console's anchor -> `(route, channel)` of the command center
    (frontend/src/app/areas.ts): `ch-<c>-batch` -> ("batches", c), `token` ->
    ("tokens", None), `ch-<c>` -> ("channels/<c>", None), none -> ("", None).

    An anchor the map does not know falls back: a per-channel one with an
    unknown section, `ch-<c>-<anything>`, goes to the channel's page
    `channels/<c>`; anything else to the center's main page (""). A channel id
    may itself hold a hyphen (`old-reel`), so `<c>` is the longest
    hyphen-bounded head of the anchor that has a `channels/<id>.json` (`root`,
    else the factory's); when none has one, the head before the first hyphen."""
    a = (anchor_ or "").strip().lstrip("#")
    if not a:
        return "", None
    if a in GLOBAL_ROUTES:
        return GLOBAL_ROUTES[a], None
    if a.startswith("ch-") and len(a) > 3:
        rest = a[3:]
        for sec in sorted(CHANNEL_ROUTES, key=len, reverse=True):
            if rest.endswith(f"-{sec}") and len(rest) > len(sec) + 1:
                return CHANNEL_ROUTES[sec], rest[:-len(sec) - 1]
        if "-" not in rest:
            return f"channels/{rest}", None
        return _channel_head(rest, root), None
    return "", None


def _channel_head(rest, root=None):
    """The channel page of `ch-<rest>` whose tail is no known section (see
    `center_route`): the longest head of `rest` with a channel config, else the
    part before the first hyphen; "" when there is no head at all."""
    parts = rest.split("-")
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.append(here)
        import channel_ids                  # shared/, beside this file
        for n in range(len(parts), 0, -1):
            head = "-".join(parts[:n])
            if head and channel_ids.channel_config_path(head, root).is_file():
                return f"channels/{head}"
    except Exception:                                            # noqa: BLE001
        pass
    return f"channels/{parts[0]}" if parts[0] else ""


def dashboard_url(anchor=None, environ=None):
    """The center's page for a console anchor (CF-0735; the name stays)."""
    route, channel = center_route(anchor)
    return center_base(environ) + route + (f"?channel={channel}" if channel else "")


def center_url(route="", channel=None, environ=None):
    """A page of the center by its route (`""`, `batches`, `questions`, ...)."""
    return center_base(environ) + str(route or "").lstrip("/") + (
        f"?channel={channel}" if channel else "")


def center_link(link, environ=None):
    """A stored link on this machine -> the center's page (CF-0735, CC-0035).

    * the retired console's link - the main path with an anchor,
      `http://127.0.0.1:8790/#ch-alpha-batch` (a stored question, an old
      journal row) -> the anchor's route, `<center>/batches?channel=alpha`;
    * the center's link from before it moved, `http://127.0.0.1:8791/<route>`
      -> the same route and query on the center, `<center>/<route>`;
    * anything else - a center link with a path (`:8790/videos?channel=x`),
      the center's main page, an outside URL, a file - as it is."""
    if not link or not str(link).startswith(("http://", "https://")):
        return link
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(link))
        port = parts.port
    except ValueError:
        return link
    if (parts.hostname or "").lower() not in LOCAL_HOSTS:
        return link
    legacy = urlsplit(LEGACY_CENTER_URL).port
    if port not in (urlsplit(OLD_CONSOLE_URL).port, legacy):
        return link
    if parts.path in ("", "/") and parts.fragment:
        return dashboard_url(parts.fragment, environ)
    if port == legacy:
        return center_base(environ) + parts.path.lstrip("/") + (
            f"?{parts.query}" if parts.query else "") + (
            f"#{parts.fragment}" if parts.fragment else "")
    return link


def anchor(channel=None, section=None):
    """`ch-<channel>-<section>`, `ch-<channel>`, or a global anchor."""
    if channel:
        return f"ch-{channel}" + (f"-{section}" if section else "")
    return section or ""


def link_of(channel=None, section=None):
    return dashboard_url(anchor(channel, section) or None)


# ------------------------------------------------------------------ backends
def _log(ev, cfg):
    where = f" {ev['channel']}" if ev["channel"] else ""          # make_event sets it
    print(mask_secrets(f"NOTIFY {ev['kind']}{where}: {ev['text']}"
                       + (f" -> {ev['link']}" if ev.get("link") else ""), cfg),
          file=sys.stderr, flush=True)


def _osa_quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_argv(ev):
    body = ev["text"]
    sub = ev.get("link") or ""
    script = (f"display notification {_osa_quote(body)} with title {_osa_quote(TITLE)}"
              + (f" subtitle {_osa_quote(sub)}" if sub else ""))
    return ["osascript", "-e", script]


def _macos(ev, cfg):
    if sys.platform != "darwin":
        raise RuntimeError("not macOS")
    cp = subprocess.run(macos_argv(ev), capture_output=True, text=True, timeout=HTTP_TIMEOUT_S)
    if cp.returncode != 0:
        raise RuntimeError(f"osascript exited {cp.returncode}: {(cp.stderr or '').strip()[:120]}")


def _post(url, data, headers):
    """POST and return the response body (bytes). An HTTP error is raised as
    `RuntimeError("HTTP <code>: <body head>")` - never with the URL in it (a
    Telegram URL carries the bot token)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:    # noqa: S310
            body = r.read(65536)
            if r.status >= 300:
                raise RuntimeError(f"HTTP {r.status}")
            return body
    except urllib.error.HTTPError as e:
        try:
            head = e.read(400).decode("utf-8", "replace")
        except Exception:                                        # noqa: BLE001
            head = ""
        raise RuntimeError(f"HTTP {e.code}: {' '.join(head.split())[:200]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"network: {e.reason}") from None


def _need(cfg, *names):
    missing = [n for n in names if not cfg.get(n)]
    if missing:
        raise Skip(f"no {', '.join(missing)} in .env")


def _ntfy(ev, cfg):
    _need(cfg, "NOTIFY_NTFY_URL")
    headers = {"Title": "Factory", "Tags": ev["kind"]}
    if ev.get("link", "").startswith("http"):
        headers["Click"] = ev["link"]
    _post(cfg["NOTIFY_NTFY_URL"], ev["text"].encode("utf-8"), headers)


TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX = 4096                     # Telegram's limit on one message's text
TELEGRAM_CUT = "\n… (обрезано, полностью - в журнале notify/sent.jsonl)"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def center_label(link, environ=None):
    """CF-0735: `центр → Батчи · канал alpha` for the center's
    `.../batches?channel=alpha`; `центр` for its main page."""
    from urllib.parse import parse_qs, urlsplit
    try:
        parts = urlsplit(str(link))
    except ValueError:
        return CENTER_NAME
    base_path = urlsplit(center_base(environ)).path or "/"
    path = parts.path or "/"
    if path.startswith(base_path):
        path = path[len(base_path):]
    path = path.strip("/")
    head, _, rest = path.partition("/")
    label = CENTER_NAME
    if path:
        name = CENTER_AREAS.get(head, head)
        label += f" → {name}" + (f" → {rest}" if rest else "")
    channel = (parse_qs(parts.query).get("channel") or [None])[0]
    if channel:
        label += f" · канал {channel_label(channel)}"       # CF-0925: Reel, not example-film
    return label


def is_console_link(link, environ=None):
    """A link to the center (or to any page on this machine): a phone cannot open it."""
    from urllib.parse import urlsplit
    if not link or not str(link).startswith(("http://", "https://")):
        return False
    base = center_base(environ)
    if str(link).split("#")[0].split("?")[0].startswith(base):
        return True
    try:
        host = (urlsplit(str(link)).hostname or "").lower()
    except ValueError:
        return False
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def phone_link(link, environ=None):
    """What a phone backend says with the line: the center's page by name and
    its address (CF-0735 - the user opens it on the Mac; an old console link is
    turned into the center's first); a file on this Mac by its name; an outside
    URL as it is."""
    if not link:
        return ""
    link = str(center_link(str(link), environ))
    if is_console_link(link, environ):
        return f"{center_label(link, environ)}: {link}"
    if link.startswith(("http://", "https://")):
        return link
    return f"файл на Mac: {Path(link).name}"


def telegram_text(ev, environ=None, limit=TELEGRAM_MAX):
    """Plain text (no parse_mode: nothing in it is markup, so nothing needs
    escaping). Head line, the event's text, where to look; cut at `limit` with
    a mark. CF-0925: an event with a `body` (its lines kept, `multiline`) is
    that body as it is - it says what happened in its own first line - and
    the center's link as the last line."""
    if ev.get("body"):
        parts = [str(ev["body"])]
        tail = phone_link(ev.get("link"), environ)
        if tail:
            parts.append(tail)
        text = "\n".join(parts)
        if len(text) > limit:
            text = text[:limit - len(TELEGRAM_CUT)].rstrip() + TELEGRAM_CUT
        return text
    where = f" · {channel_label(ev['channel'])}" if ev.get("channel") else ""
    head = TELEGRAM_HEADS.get(ev.get("kind")) or f"{TITLE} · {ev.get('kind')}"
    head += where if ev.get("kind") != "reminder" else ""
    parts = [head, str(ev.get("text") or "")]
    tail = phone_link(ev.get("link"), environ)
    if tail:
        parts.append(tail)
    text = "\n".join(parts)
    if len(text) > limit:
        text = text[:limit - len(TELEGRAM_CUT)].rstrip() + TELEGRAM_CUT
    return text


def mask_token(text, token):
    """The bot token never reaches a log line, an exception or the CLI's output."""
    text = str(text)
    if token:
        text = text.replace(str(token), MASK)
    return scrub(text)


#: CF-0720: the settings whose values never reach the journal, stderr or the
#: CLI's output - the bot token and every address (the chat id, the ntfy and
#: webhook URLs); a value shorter than SECRET_SHORTEST is not cut (it would
#: cut words).
SECRET_SETTINGS = ("NOTIFY_TELEGRAM_TOKEN", "NOTIFY_TELEGRAM_CHAT", "NOTIFY_NTFY_URL",
                   "NOTIFY_WEBHOOK_URL")
SECRET_SHORTEST = 4
#: A Telegram bot URL whatever the token (one that is not in the settings any more).
BOT_URL_RE = re.compile(r"(api\.telegram\.org/(?:file/)?bot)[^/\s?#]+")


def mask_secrets(text, cfg=None):
    """CF-0720: `text` with every secret of the settings `cfg` cut (the token,
    the chat id, the ntfy and webhook URLs - SECRET_SETTINGS), a Telegram bot
    URL's token cut whatever it is, then `scrub`. Idempotent."""
    text = str(text)
    cut = sorted({str(v) for k, v in (cfg or {}).items()
                  if k in SECRET_SETTINGS and v and len(str(v)) >= SECRET_SHORTEST},
                 key=len, reverse=True)
    for v in cut:
        text = text.replace(v, MASK)
    text = BOT_URL_RE.sub(lambda m: m.group(1) + MASK, text)
    return scrub(text)


def mask_doc(doc, cfg=None):
    """`mask_secrets` over every string of a row (keys stay)."""
    if isinstance(doc, str):
        return mask_secrets(doc, cfg)
    if isinstance(doc, dict):
        return {k: mask_doc(v, cfg) for k, v in doc.items()}
    if isinstance(doc, list):
        return [mask_doc(v, cfg) for v in doc]
    return doc


def _telegram(ev, cfg):
    _need(cfg, "NOTIFY_TELEGRAM_TOKEN", "NOTIFY_TELEGRAM_CHAT")
    from urllib.parse import urlencode
    token = cfg["NOTIFY_TELEGRAM_TOKEN"]
    body = urlencode({"chat_id": cfg["NOTIFY_TELEGRAM_CHAT"],
                      "text": telegram_text(ev, cfg),
                      "disable_web_page_preview": "true"}).encode()
    try:
        got = _post(TELEGRAM_API.format(token=token), body,
                    {"Content-Type": "application/x-www-form-urlencoded"})
    except Exception as e:                                       # noqa: BLE001
        # `from None`: the chained exception (a URL, a urllib request) stays out
        raise RuntimeError(mask_token(f"{type(e).__name__}: {e}", token)) from None
    try:
        doc = json.loads((got or b"{}").decode("utf-8", "replace"))
    except ValueError:
        doc = {}
    if isinstance(doc, dict) and doc.get("ok") is False:
        raise RuntimeError(mask_token(f"Telegram: {doc.get('description') or 'not ok'}", token))


def _webhook(ev, cfg):
    _need(cfg, "NOTIFY_WEBHOOK_URL")
    body = json.dumps({k: ev.get(k) for k in ("kind", "channel", "key", "text", "link", "at")},
                      ensure_ascii=False).encode("utf-8")
    _post(cfg["NOTIFY_WEBHOOK_URL"], body, {"Content-Type": "application/json"})


class Skip(Exception):
    """A backend that is on but has no address: said in the row, not an error."""


BACKENDS = {"log": _log, "macos": _macos, "ntfy": _ntfy, "telegram": _telegram,
            "webhook": _webhook}


# ------------------------------------------------------------------ journal
@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "sent.lock", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def rows(root=None, environ=None):
    """The journal's rows, oldest first. CF-0720: every string masked with the
    settings' secrets (`mask_secrets`) - a row written before the masking
    does not show them either."""
    path = journal_path(root, environ)
    try:
        cfg = settings(root, environ)
    except Exception:                                            # noqa: BLE001
        cfg = {}
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            doc = json.loads(ln)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(mask_doc(doc, cfg))
    return out


def was_sent(key, root=None, environ=None):
    return any(r.get("key") == key for r in rows(root, environ))


# ------------------------------------------------------------------ send
def multiline_body(text, limit=TELEGRAM_MAX):
    """CF-0925: the lines of a message as Telegram gets them - each line
    masked, runs of spaces inside it collapsed, one empty line kept between
    blocks, the whole cut at `limit`."""
    lines, blank = [], False
    for raw in str(text or "").splitlines():
        line = " ".join(scrub(raw).split())
        if not line:
            blank = bool(lines)
            continue
        if blank:
            lines.append("")
            blank = False
        lines.append(line)
    body = "\n".join(lines)
    return body if len(body) <= limit else body[:limit - 1].rstrip() + "…"


def flat_text(text):
    """The journal's one line of a multi-line message: its lines joined with « · »."""
    return " · ".join(ln.strip() for ln in str(text or "").splitlines() if ln.strip())


def make_event(kind, key, text, channel=None, link=None, again=None, now=None,
               multiline=False):
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r} (one of {', '.join(KINDS)})")
    if not key or not str(key).strip():
        raise ValueError("an event needs a key")
    key = " ".join(str(key).split())
    if again:
        key = f"{key}#again:{again}"
    if multiline:
        return {"at": now_iso(now), "kind": kind, "channel": channel or None, "key": key,
                "text": one_line(flat_text(text), MULTILINE_TEXT_MAX),
                "body": multiline_body(text),
                "link": scrub(center_link(link)) if link else None, "task": TASK}
    return {"at": now_iso(now), "kind": kind, "channel": channel or None, "key": key,
            "text": one_line(text, REMINDER_TEXT_MAX if kind in LONG_TEXT_KINDS else TEXT_MAX),
            "link": scrub(center_link(link)) if link else None, "task": TASK}


def send(kind, key, text, channel=None, link=None, again=None, root=None, now=None,
         backends=None, environ=None, by=None, via=None, multiline=False, local_only=False):
    """Send one event once. Returns `{status, key, backends}`; status is `sent`,
    `duplicate` (the key is in the journal: nothing is called) or `error` (the
    event could not be made or the journal not written). Never raises.

    `backends` replaces the registry (tests: stand-ins); which of them are
    called is still the setting's.

    CF-0720: `by` / `via` (checked by `_who`; a bad one is `error`, nothing
    sent) go on the journal row only when given. The event - key, text, link -
    and each backend's answer are masked with the settings' secrets
    (`mask_secrets`: the token, the chat id, the URLs) before a backend, the
    journal or stderr sees them.

    CF-0925: `multiline` keeps the text's lines for Telegram (`make_event`:
    the row's `body`); `local_only` calls only the backends that keep the line
    on this machine (not EXTERNAL) - an event the center reads in the journal
    that the user's phone has no use for."""
    try:
        by, via = _who(by, "by"), _who(via, "via")
        ev = make_event(kind, key, text, channel, link, again, now, multiline=multiline)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY refused: {e}", file=sys.stderr)
        return {"status": "error", "key": key, "error": str(e), "backends": {}}
    try:
        cfg = settings(root, environ)
        ev = mask_doc(ev, cfg)
        names = enabled(root, environ)
        if local_only:
            names = [n for n in names if n not in EXTERNAL]
        registry = BACKENDS if backends is None else backends
        directory = state_dir(root, environ)
        with _locked(directory):
            if was_sent(ev["key"], root, environ):
                return {"status": "duplicate", "key": ev["key"], "backends": {}}
            results = {}
            for name in names:
                fn = registry.get(name)
                if fn is None:
                    results[name] = "skipped: unknown backend"
                    continue
                try:
                    fn(ev, cfg)
                    results[name] = "ok"
                except Skip as e:
                    results[name] = f"skipped: {e}"
                except Exception as e:                           # noqa: BLE001
                    results[name] = mask_secrets(
                        one_line(f"error: {e.__class__.__name__}: {e}", 160), cfg)
                    print(f"NOTIFY {name} {results[name]} (key {ev['key']}) - the source goes on",
                          file=sys.stderr, flush=True)
            results = mask_doc(results, cfg)
            row = dict(ev, backends=results)
            row.update({k: v for k, v in (("by", by), ("via", via)) if v is not None})
            with open(directory / JOURNAL, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"status": "sent", "key": ev["key"], "backends": results}
    except Exception as e:                                       # noqa: BLE001
        err = mask_secrets(str(e), locals().get("cfg"))
        print(f"NOTIFY: not sent ({e.__class__.__name__}: {err}) - the source goes on",
              file=sys.stderr)
        return {"status": "error", "key": ev["key"], "error": err, "backends": {}}


# ------------------------------------------------------------------ the sources' hooks
# Each is what a source calls; each is safe to call from anywhere (no raise).

def on_token(st, root=None, now=None, **kw):
    """publisher_auth.NOTIFIERS: a TokenStatus that is not ok. The key is the
    term and the state (`TokenStatus.key`), so "expires tomorrow" and then
    "expired" are two notifications, the same state of the same term is one."""
    try:
        kind = getattr(st, "kind", "?")
        # the kinds of publisher_auth (OK, SOON, EXPIRED, NO_AUTH, NO_SCOPE, UNKNOWN)
        text = {"expires-soon": "токен YouTube скоро истекает - переразрешите доступ (~30 с)",
                "expired": "токен YouTube истёк - загрузка и метрики стоят, переразрешите доступ",
                "no-auth": "токена YouTube нет - разрешите доступ",
                "no-scope": "у токена YouTube нет нужного scope - переразрешите доступ",
                "unknown-expiry": "срок токена YouTube неизвестен - проверьте",
                }.get(kind, f"токен YouTube: {kind} - проверьте")
        return send("token", f"token:{st.key}", text, link=link_of(None, "token"),
                    root=root, now=now, **kw)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY token: {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)}


# ------------------------------------------------------------------ reminders (CF-0606)
# The user's own one-shot reminders («напомни в 21:00 ...»), sent through the
# bus as kind `reminder`. The queue `<state>/reminders.jsonl` is an append-only
# log of operations - `add`, `sent`, `failed` (CF-0617), `cancel` - folded
# into the reminders' state; every write is under `reminders.lock`. Time is
# given in Moscow time and kept in UTC ISO. Queuing sends nothing: `send_due` sends what has come
# due (`remind --due`, and every tick of shared/batch_schedule.py - whether the
# schedule's switch is on or off).
REMINDERS = "reminders.jsonl"
REMINDERS_LOCK = "reminders.lock"
REMINDER_TEXT_MAX = 1000
# CF-0684: the kinds whose text is the user's own words or an answer to them -
# cut at REMINDER_TEXT_MAX, not at the one-line TEXT_MAX of a gate's notice.
LONG_TEXT_KINDS = ("reminder", "request_answer")
# The head line of a Telegram message of these kinds instead of «Фабрика · kind».
TELEGRAM_HEADS = {"reminder": "Напоминание", "request_answer": "Ответ на просьбу"}
# CF-0925: the head of every other kind in words - «Батч остановился · Reel», not
# «Фабрика · run_halted · example-film» (a kind missing here keeps the old head)
TELEGRAM_HEADS.update({
    "accept": "Ждёт приёмки", "upload": "Файл для Studio",
    "token": "Токен YouTube", "empty_slot": "Пустой слот", "run_halted": "Батч остановился",
    "run_done": "Батч закончен", "needs_human": "Нужен человек",
    "batch_started": "Батч запущен", "test": "Проверка уведомлений",
    "hold_released": "Холд снят", "accepted": "Приёмка", "uploaded": "Залито в Studio",
    "studio_read": "Чтение Studio"})
# CF-0617: a reminder no outside backend took is tried again at the next
# `remind --due` / tick (every 15 minutes, docs/batch-schedule.md), up to this
# many tries in all - ~1 h 45 min of an outage at the tick's pace; after the
# last one it is `exhausted`: no more tries, shown in the center until the
# user cancels it.
REMINDER_MAX_ATTEMPTS = 8
REASON_MAX = 300
WHO_MAX = 40                # CF-0700: `by` / `via` of a reminder op (CF-0692's rule)
FACTORY_TZ = "Europe/Moscow"


def msk_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(FACTORY_TZ)
    except Exception:                                            # noqa: BLE001
        from datetime import timedelta
        return timezone(timedelta(hours=3), "MSK")


def _utc(now=None):
    if now is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(now, datetime):
        dt = now
    else:
        dt = datetime.fromisoformat(str(now).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"a time without a zone: {now!r}")
    return dt.astimezone(timezone.utc)


def _utc_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def msk_text(iso_utc):
    """`2026-10-07 21:00 МСК` for a UTC ISO time."""
    try:
        return _utc(iso_utc).astimezone(msk_zone()).strftime("%Y-%m-%d %H:%M МСК")
    except (TypeError, ValueError):
        return str(iso_utc)


_WHEN_RE = re.compile(r"^\s*(?:(\d{4}-\d{2}-\d{2})[ T])?(\d{1,2}):(\d{2})\s*(?:МСК|MSK|мск|msk)?\s*$")


def parse_when(text, now=None):
    """Moscow time -> an aware UTC datetime. `ЧЧ:ММ` is the next such time
    (today, or tomorrow when today's has passed); `YYYY-MM-DD ЧЧ:ММ` must not
    be in the past. A trailing `МСК`/`MSK` is allowed (and is the only zone)."""
    m = _WHEN_RE.match(str(text or ""))
    if not m:
        raise ValueError(f"--at {text!r}: expected «ЧЧ:ММ» or «YYYY-MM-DD ЧЧ:ММ», Moscow time")
    day, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    if hh > 23 or mm > 59:
        raise ValueError(f"--at {text!r}: no such time")
    zone = msk_zone()
    now_ = _utc(now)
    local_now = now_.astimezone(zone)
    if day:
        try:
            d = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"--at {text!r}: no such date") from None
        due = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
        if due.astimezone(timezone.utc) < now_:
            raise ValueError(f"--at {text!r}: that time has passed ({local_now:%Y-%m-%d %H:%M} МСК now)")
    else:
        from datetime import timedelta
        due = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if due <= local_now:
            due = (local_now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            due = datetime(due.year, due.month, due.day, hh, mm, tzinfo=zone)
    return due.astimezone(timezone.utc)


def reminders_path(root=None, environ=None):
    return state_dir(root, environ) / REMINDERS


@contextmanager
def _reminders_locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / REMINDERS_LOCK, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _reminder_ops(root=None, environ=None):
    out = []
    try:
        lines = reminders_path(root, environ).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            doc = json.loads(ln)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("id"):
            out.append(doc)
    return out


def reminders(root=None, environ=None):
    """Every reminder, oldest first: `{id, due, text, created, by, via, status,
    sent_at, cancelled_at, cancelled_by, cancelled_via, backends, attempts,
    last_try, reason}`.

    CF-0700: `via` (the add's), `cancelled_by` / `cancelled_via` (the
    cancel's) are None where the op does not carry them - every row written
    before CF-0700, and a CLI add / cancel.

    CF-0617: status is `pending` (not tried yet), `failed` (tried, no outside
    backend took it - it goes again at the next `remind --due` / tick),
    `exhausted` (failed REMINDER_MAX_ATTEMPTS times - no more tries; it stays
    in the center until cancelled), `sent` or `cancelled`."""
    by_id = {}
    for op in _reminder_ops(root, environ):
        rid = op["id"]
        kind = op.get("op")
        if kind == "add":
            by_id[rid] = {"id": rid, "due": op.get("due"), "text": op.get("text"),
                          "created": op.get("at"), "by": op.get("by"), "via": op.get("via"),
                          "status": "pending", "sent_at": None, "cancelled_at": None,
                          "cancelled_by": None, "cancelled_via": None, "backends": None,
                          "attempts": 0, "last_try": None, "reason": None}
            continue
        r = by_id.get(rid)
        if r is None or r["status"] in ("sent", "cancelled"):
            continue
        if kind == "sent" and r["status"] in ("pending", "failed"):
            r.update(status="sent", sent_at=op.get("at"), backends=op.get("backends"),
                     attempts=op.get("attempt") or r["attempts"] + 1, last_try=op.get("at"))
        elif kind == "failed" and r["status"] in ("pending", "failed"):
            r.update(status="exhausted" if op.get("exhausted") else "failed",
                     attempts=op.get("attempt") or r["attempts"] + 1, last_try=op.get("at"),
                     reason=op.get("reason"), backends=op.get("backends"))
        elif kind == "cancel":
            r.update(status="cancelled", cancelled_at=op.get("at"),
                     cancelled_by=op.get("by"), cancelled_via=op.get("via"))
    return list(by_id.values())


def pending_reminders(root=None, environ=None):
    """The ones still to go: never tried (`pending`) or to be tried again
    (`failed`), by due time."""
    return sorted((r for r in reminders(root, environ) if r["status"] in ("pending", "failed")),
                  key=lambda r: (str(r["due"]), r["id"]))


def unsent_reminders(root=None, environ=None):
    """CF-0617: the ones that were tried and did not go - `failed` (another try
    comes) and `exhausted` (no more tries) - by due time."""
    return sorted((r for r in reminders(root, environ) if r["status"] in ("failed", "exhausted")),
                  key=lambda r: (str(r["due"]), r["id"]))


def _append_op(op, root=None, environ=None):
    with open(reminders_path(root, environ), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(op, task="CF-0606"), ensure_ascii=False) + "\n")


def _next_id(ops):
    n = 0
    for op in ops:
        m = re.match(r"^R(\d+)$", str(op.get("id")))
        if m:
            n = max(n, int(m.group(1)))
    return f"R{n + 1}"


def _who(value, what):
    """CF-0700 (the shape of CF-0692's `studio_read._who`): `by` / `via` of a reminder op - None (not given)
    or a short non-empty single-line string; anything else is a ValueError
    and nothing is written."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                         f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise ValueError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def add_reminder(when, text, root=None, now=None, by="user", environ=None, via=None):
    """Queue one reminder (nothing is sent). `(reminder, created)`: the same
    text at the same time already pending is that one, not a second.

    CF-0700: `via` (optional - e.g. `center`) goes into the op `add` only when
    given, so an add without it is byte for byte the row it always was; `by`
    and `via` are checked (`_who`) before anything is written."""
    by, via = _who(by, "by"), _who(via, "via")
    text = one_line(text, REMINDER_TEXT_MAX)
    if not text:
        raise ValueError("a reminder needs a text")
    due = _utc_iso(parse_when(when, now))
    with _reminders_locked(state_dir(root, environ)):
        for r in pending_reminders(root, environ):
            if r["due"] == due and r["text"] == text:
                return r, False
        rid = _next_id(_reminder_ops(root, environ))
        op = {"op": "add", "id": rid, "due": due, "text": text, "by": by,
              "at": _utc_iso(_utc(now))}
        if via is not None:
            op["via"] = via
        _append_op(op, root, environ)
    return next(r for r in reminders(root, environ) if r["id"] == rid), True


def cancel_reminder(rid, root=None, now=None, environ=None, by=None, via=None):
    """Cancel one reminder that is still to go (pending, failed, exhausted).

    CF-0700: `by` / `via` (optional, e.g. `user` / `center`) go into the op
    `cancel` only when given - a cancel without them is byte for byte the row
    it always was - and come back as `cancelled_by` / `cancelled_via`; they are
    checked (`_who`) before anything is written."""
    by, via = _who(by, "by"), _who(via, "via")
    rid = str(rid or "").strip().upper()
    with _reminders_locked(state_dir(root, environ)):
        got = {r["id"]: r for r in reminders(root, environ)}
        if rid not in got:
            raise ValueError(f"no reminder {rid}")
        if got[rid]["status"] in ("sent", "cancelled"):
            raise ValueError(f"reminder {rid} is already {got[rid]['status']}")
        at = _utc_iso(_utc(now))
        op = {"op": "cancel", "id": rid, "at": at}
        op.update({k: v for k, v in (("by", by), ("via", via)) if v is not None})
        _append_op(op, root, environ)
    return dict(got[rid], status="cancelled", cancelled_at=at, cancelled_by=by,
                cancelled_via=via)


def delivery(backends):
    """CF-0617: did a send reach the user? `(ok, reason)`. It did when an
    outside backend (EXTERNAL) said `ok`, or when no outside backend was tried
    (none is on, or each that is on is `skipped: ...` for want of its address -
    the local ones are then all there is). It did not when every outside
    backend that was tried said `error: ...`; the reason is their answers."""
    tried = {k: str(v) for k, v in (backends or {}).items()
             if k in EXTERNAL and not str(v).startswith("skipped")}
    if not tried or any(v == "ok" for v in tried.values()):
        return True, None
    return False, one_line("; ".join(f"{k}: {v}" for k, v in tried.items()), REASON_MAX)


def _reminder_key(rid, attempt):
    """The bus key of a reminder's try: the first is `reminder:<id>`, a retry
    `reminder:<id>#again:try<n>` - a new key, so the bus does send it."""
    return f"reminder:{rid}" + (f"#again:try{attempt}" if attempt > 1 else "")


def send_due(root=None, now=None, environ=None, backends=None):
    """Send every reminder whose time has come and that is still to go
    (`pending`, or `failed` and to be tried again): under the queue's lock,
    through the bus, one try each per call. Never raises; `[{id, text, status,
    attempt, reason, backends}]`.

    CF-0617: a try counts as sent only when an outside backend took it
    (`delivery`) - then the op `sent`. Otherwise - every outside backend said
    `error`, or the bus could not send at all - the op `failed` with the reason
    and the try's number; the next call tries again with a new bus key, and
    the REMINDER_MAX_ATTEMPTS-th failure is `exhausted` (status of that entry
    too). A key the journal already has (`duplicate`: a process died between
    the journal and the queue) is judged by that journal row."""
    out = []
    try:
        now_ = _utc(now)
        cfg = settings(root, environ)
        with _reminders_locked(state_dir(root, environ)):
            for r in pending_reminders(root, environ):
                if _utc(r["due"]) > now_:
                    continue
                attempt = int(r.get("attempts") or 0) + 1
                key = _reminder_key(r["id"], attempt)
                res = send("reminder", key, r["text"], link=dashboard_url("reminders", cfg),
                           root=root, now=_utc_iso(now_), environ=environ, backends=backends)
                got = res.get("backends") or {}
                if res["status"] == "duplicate":
                    row = next((x for x in rows(root, environ) if x.get("key") == key), {})
                    got = row.get("backends") or {}
                if res["status"] in ("sent", "duplicate"):
                    ok, reason = delivery(got)
                else:
                    ok, reason = False, one_line(f"bus: {res.get('error') or res['status']}",
                                                 REASON_MAX)
                at = _utc_iso(now_)
                if ok:
                    _append_op({"op": "sent", "id": r["id"], "at": at, "status": res["status"],
                                "attempt": attempt, "backends": got}, root, environ)
                    status = res["status"]
                else:
                    reason = scrub(reason)
                    exhausted = attempt >= REMINDER_MAX_ATTEMPTS
                    _append_op({"op": "failed", "id": r["id"], "at": at, "attempt": attempt,
                                "reason": reason, "exhausted": exhausted, "backends": got},
                               root, environ)
                    status = "exhausted" if exhausted else "failed"
                    print(f"NOTIFY reminder {r['id']}: not delivered (try {attempt} of "
                          f"{REMINDER_MAX_ATTEMPTS}: {reason})"
                          + (" - no more tries" if exhausted else " - tried again next tick"),
                          file=sys.stderr, flush=True)
                out.append({"id": r["id"], "text": r["text"], "status": status,
                            "attempt": attempt, "reason": None if ok else reason,
                            "backends": got})
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY reminders: not sent ({type(e).__name__}: {scrub(e)}) - the source goes on",
              file=sys.stderr)
        out.append({"id": None, "status": "error", "error": scrub(e), "backends": {}})
    return out


EXTERNAL_NEEDS = {"ntfy": ("NOTIFY_NTFY_URL",),
                  "telegram": ("NOTIFY_TELEGRAM_TOKEN", "NOTIFY_TELEGRAM_CHAT"),
                  "webhook": ("NOTIFY_WEBHOOK_URL",)}
PREVIEW_UNKNOWN = "unknown backend"


# CF-0925: what `test` shows - the probe's words and a message of the new look
# (shared/notify_human.py), the lines kept as Telegram gets them
PREVIEW_TEXT = ("проверка уведомлений фабрики — так выглядит сообщение:\n"
                "✅ Reel: батч готов — 2 ролика из 6 тем, судья кадров пропустил 1\n"
                "• Jon Marrow — C 75, судья кадров пропустил\n"
                "• Melania — E 49,85, отклонён судьёй кадров: брак футажа (смазанный кадр)")


def test_preview(root=None, environ=None):
    """CF-0700: the dry check of the backends as data - what `notify.py test`
    (without --send) prints, one dict per backend that is on, in the order of
    NOTIFY_BACKENDS: `{name, known, external, ready, skip_reason, would_get}`.

    known        the bus has such a backend (an unknown one is ignored by
                 `send`: not ready, `skip_reason` PREVIEW_UNKNOWN, `would_get`
                 None)
    external     it sends the text off this machine (EXTERNAL)
    ready        it would take the line: a local one always, an outside one
                 when its addresses are in the settings (EXTERNAL_NEEDS)
    skip_reason  why an outside one would be skipped (`no NOTIFY_... in .env`,
                 the very text of its `skipped: ...` row), else None
    would_get    the text it would get - Telegram's own plain text with the
                 center's page name with its link, the others
                 `<text> -> <link>`

    Nothing is sent, the network is not touched, nothing is written; the
    settings are `environ` (default os.environ) over `<root>/.env`."""
    cfg = settings(root, environ)
    ev = make_event("run_done", "test", PREVIEW_TEXT, multiline=True,
                    link=dashboard_url(None, environ))      # = link_of(None, None) on os.environ
    out = []
    for name in enabled(root, environ):
        if name not in BACKENDS:
            out.append({"name": name, "known": False, "external": name in EXTERNAL,
                        "ready": False, "skip_reason": PREVIEW_UNKNOWN, "would_get": None})
            continue
        skip = None
        if name in EXTERNAL:
            try:
                _need(cfg, *EXTERNAL_NEEDS[name])
            except Skip as e:
                skip = str(e)
        shown = telegram_text(ev, cfg) if name == "telegram" else f"{ev['text']} -> {ev['link']}"
        out.append({"name": name, "known": True, "external": name in EXTERNAL,
                    "ready": skip is None, "skip_reason": skip, "would_get": shown})
    return out


TEST_TEXT = "пробное сообщение фабрики ({stamp}): уведомления доходят"
DRY_WOULD = "would send"


def test_key(now=None):
    """A new key for each probe: `test:<UTC ISO, microseconds>`."""
    at = datetime.now(timezone.utc) if now is None else _utc(now)
    return f"test:{at.isoformat(timespec='microseconds')}"


def send_test(root=None, by=None, via=None, now=None, backends=None, environ=None,
              dry_run=False):
    """CF-0720 (the center's ask 10): the probe of `test --send` - kind
    `test`, a new key each run (`test_key`), TEST_TEXT, the center's link -
    to every backend that is on, one journal row carrying `by` / `via` when
    given (checked by `_who`: a bad one is ValueError, nothing sent).

    Returns `send`'s answer `{status, key, backends}` plus `by`, `via`,
    `text` and `delivered` / `delivery_reason` (`delivery`). `dry_run=True`
    sends nothing and writes nothing: the same shape, `status` `dry_run`,
    each backend `would send` or the very `skipped: ...` the send would write
    (`test_preview`); `delivered` is what a send would say if every ready
    backend took the line."""
    by, via = _who(by, "by"), _who(via, "via")
    key = test_key(now)
    text = one_line(TEST_TEXT.format(stamp=now_iso(now)), TEXT_MAX)
    if dry_run:
        got = {}
        for b in test_preview(root, environ):
            got[b["name"]] = (DRY_WOULD if b["ready"] else f"skipped: {b['skip_reason']}")
        cfg = settings(root, environ)
        res = {"status": "dry_run", "key": key, "backends": mask_doc(got, cfg)}
        ok, why = delivery({k: ("ok" if v == DRY_WOULD else v) for k, v in got.items()})
    else:
        res = send("test", key, text, root=root, now=now, link=dashboard_url(None, environ),
                   backends=backends, environ=environ, by=by, via=via)
        ok, why = delivery(res.get("backends") or {})
    return dict(res, by=by, via=via, text=text, delivered=ok, delivery_reason=why)


def _main_argv(argv):
    ap = argparse.ArgumentParser(prog="notify.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="send one event once")
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--key", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--channel")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--link")
    g.add_argument("--anchor", help="an anchor (of the retired console, mapped to the center): token, needs-you, ch-<channel>[-feed|-batch|"
                                    "-acceptance]")
    s.add_argument("--again", help="send a reminder of an event already sent: a new key")
    s.add_argument("--root")
    li = sub.add_parser("list", help="the journal, newest last")
    li.add_argument("--kind", choices=KINDS)
    li.add_argument("--channel")
    li.add_argument("--limit", type=int, default=20)
    li.add_argument("--root")
    r = sub.add_parser("remind", help="the user's one-shot reminders (CF-0606): queue, list, "
                                      "cancel, send what is due")
    rg = r.add_mutually_exclusive_group(required=True)
    rg.add_argument("--at", help="«ЧЧ:ММ» or «YYYY-MM-DD ЧЧ:ММ», Moscow time (a trailing МСК is fine)")
    rg.add_argument("--list", action="store_true", help="the pending ones (--all: every one)")
    rg.add_argument("--cancel", metavar="ID")
    rg.add_argument("--due", action="store_true", help="send the ones whose time has come")
    r.add_argument("text", nargs="*")
    r.add_argument("--all", action="store_true")
    r.add_argument("--now", help=argparse.SUPPRESS)                  # tests
    r.add_argument("--root")
    t = sub.add_parser("test", help="what each backend that is on would get (a stand-in sends); "
                                    "--send: a probe event to every backend that is on")
    t.add_argument("--send", action="store_true",
                   help="really send the probe (Telegram etc. when on) - one new event each run")
    t.add_argument("--by", help="CF-0720: who sends the probe (e.g. user) - on the journal row")
    t.add_argument("--via", help="CF-0720: from where (e.g. cli, center) - on the journal row")
    t.add_argument("--root")
    return ap.parse_args(argv)


def _remind(args, root, out):
    try:
        if args.at:
            if not args.text:
                print("error: remind --at needs the text", file=out)
                return 2
            r, created = add_reminder(args.at, " ".join(args.text), root=root, now=args.now)
            print(f"{'queued' if created else 'already queued'}: {r['id']} {msk_text(r['due'])} - "
                  f"{r['text']} (nothing sent now; it goes at its time: remind --due / the tick)",
                  file=out)
            return 0
        if args.cancel:
            r = cancel_reminder(args.cancel, root=root, now=args.now)
            print(f"cancelled: {r['id']} {msk_text(r['due'])} - {r['text']}", file=out)
            return 0
        if args.due:
            got = send_due(root=root, now=args.now)
            for g in got:
                tries = (f" (try {g['attempt']} of {REMINDER_MAX_ATTEMPTS})"
                         if g.get("attempt") and g["status"] not in ("sent", "duplicate") else "")
                print(f"{g['status']}: {g.get('id')} {g.get('text') or g.get('error')}{tries}"
                      + "".join(f"\n  {k}: {v}" for k, v in g["backends"].items())
                      + (f"\n  reason: {g['reason']}" if g.get("reason") else ""), file=out)
            if not got:
                print("nothing due", file=out)
            return 1 if any(g["status"] not in ("sent", "duplicate") for g in got) else 0
        rows_ = reminders(root) if args.all else [
            r for r in reminders(root) if r["status"] not in ("sent", "cancelled")]
        for r in rows_:
            tries = (f" [try {r['attempts']} of {REMINDER_MAX_ATTEMPTS}: {r['reason']}]"
                     if r["status"] in ("failed", "exhausted") else "")
            print(f"{r['id']:<5} {msk_text(r['due'])}  {r['status']:<9} {r['text']}{tries}",
                  file=out)
        print(f"{len(rows_)} reminder(s){'' if args.all else ' pending'} in {reminders_path(root)}",
              file=out)
        return 0
    except ValueError as e:
        print(f"error: {e}", file=out)
        return 2


def main(argv=None, out=sys.stdout):
    try:
        args = _main_argv(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    root = Path(args.root).absolute() if args.root else None
    if args.cmd == "send":
        link = dashboard_url(args.anchor) if args.anchor else args.link
        res = send(args.kind, args.key, args.text, channel=args.channel, link=link,
                   again=args.again, root=root)
        if res["status"] == "error":
            print(f"error: {res.get('error')}", file=out)
            return 2
        print(f"{res['status']}: {res['key']}"
              + "".join(f"\n  {k}: {v}" for k, v in res["backends"].items()), file=out)
        return 0
    if args.cmd == "list":
        got = [r for r in rows(root) if (not args.kind or r.get("kind") == args.kind)
               and (not args.channel or r.get("channel") == args.channel)]
        for r in got[-args.limit:] if args.limit > 0 else got:
            print(f"{r.get('at')} {r.get('kind'):<11} {r.get('channel') or '-':<14} "
                  f"{r.get('text')}" + (f" -> {r['link']}" if r.get("link") else "")
                  + f"  [{', '.join(f'{k}: {v}' for k, v in (r.get('backends') or {}).items())}]",
                  file=out)
        print(f"{len(got)} event(s) in {journal_path(root)}", file=out)
        return 0
    if args.cmd == "remind":
        return _remind(args, root, out)
    if args.send:
        try:
            res = send_test(root, by=args.by, via=args.via)
        except ValueError as e:
            print(f"error: {e}", file=out)
            return 2
        print(f"{res['status']}: {res.get('key')}"
              + "".join(f"\n  {k}: {v}" for k, v in res["backends"].items()), file=out)
        bad = [k for k, v in res["backends"].items() if not str(v).startswith("ok")]
        return 0 if res["status"] == "sent" and not bad else 1
    names = enabled(root)
    print(f"journal: {journal_path(root)}", file=out)
    print(f"backends on: {', '.join(names)} ({BACKENDS_ENV}; default {','.join(DEFAULT_BACKENDS)})",
          file=out)
    for b in test_preview(root):
        if not b["known"]:
            print(f"  {b['name']}: unknown backend - ignored", file=out)
            continue
        note = ""
        if b["external"]:
            note = (" - SENDS THE TEXT TO AN OUTSIDE SERVICE" if b["ready"]
                    else f" - would be skipped ({b['skip_reason']})")
        print(f"  {b['name']}: would get {b['would_get']!r}{note}", file=out)
    print("nothing sent (a stand-in backend; the journal is untouched)", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
