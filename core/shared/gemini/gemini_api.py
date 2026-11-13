#!/usr/bin/env python3
"""CF-0690: the factory's Gemini API client - "a demo via API" for ExampleTech.

**Why** (the user's decision of 2026-10-12, Q30; the paid way was refused). A
story about a new model shows that model's REAL answer to a neutral prompt,
drawn in the factory's own chat animation and labelled "<model> · via API"
(`shared/api_demo.py`, the `api_chat` template of `shared/own_graphic.py`).
The answer is never a fact of the story and nothing of it is rewritten: the
protocol this client returns is the record the frame is checked against.

**Terms** (read 2026-10-12, https://ai.google.dev/gemini-api/terms): the free
tier is available in Serbia (in the EEA, the UK and Switzerland only the paid
tier is), its outputs may be published, programmatic use is what the API is
for. On the free tier Google may read the inputs - so only public text is
sent: the channel's own neutral prompts (`channels/example-tech/
footage-origin.json` `api_demo.prompts`), never a person's data, never a
script or a batch file.

**What this client does on the network**, in full:

* one host, ``https://generativelanguage.googleapis.com``, POST only, one
  endpoint: ``/v1beta/models/{model}:generateContent``;
* the key goes ONLY in the ``x-goog-api-key`` header - never in the URL, a
  log line, an exception or a returned value (every text that leaves this
  module is scrubbed of it, and of anything that looks like a secret,
  `shared/notify.py` `scrub`);
* serial requests, at least ``min_interval`` seconds apart (the channel's
  ``api_demo.min_interval_seconds``; ``MIN_INTERVAL_SECONDS`` by default);
* a 429 or a 5xx is retried after ``Retry-After`` or the error's
  ``RetryInfo.retryDelay`` (else ``RETRY_BACKOFF_SECONDS`` x attempt), at most
  ``MAX_RETRIES`` attempts in all; a wait longer than ``MAX_RETRY_WAIT_SECONDS``
  (the free tier's daily quota) is not waited out. Then the call is
  ``skipped`` - ``rate_limited`` (429) or ``unavailable: HTTP <n>`` (5xx) - a
  batch goes on without the demo, it does not fail.

**The key**: ``GEMINI_API_KEY`` from the environment, else from
``<factory root>/.env`` (read by `shared/notify.py` `read_env_file`; the root
is ``FACTORY_ROOT`` or this checkout). `key_source()` says where it came from
- ``"environment"`` | ``".env"`` | None - and is the only thing about the key
that is ever logged. No key: the call is ``skipped`` with ``NO_KEY_REASON``.

**The protocol** (`ask`) - one dict per call, the footing record of the frame:

    provider, endpoint (no key), model_requested, model_version
    (response.modelVersion), prompt, generation_config, answer (verbatim:
    candidates[0].content.parts[].text joined, thought parts left out),
    finish_reason, prompt_feedback, citation (bool), usage, response_id,
    requested_at, answered_at, key_source, status (ok | skipped | refused),
    skip_reason (why it is not ok; None when ok)

``refused`` - the model's answer is not one to show: a finishReason other
than STOP (SAFETY, RECITATION, MAX_TOKENS ...), a prompt the API blocked
(``promptFeedback.blockReason``), an empty answer, an answer with citation
metadata (a recitation of someone's text), or one that reads as a refusal
(`refusal_phrase`: "I can't", "I cannot", "I'm unable", "As an AI" ...).

A transport failure (no answer at all) and a status the API will not change
by being asked again (400, 401, 403, 404) raise `GeminiError`, its text
scrubbed.

Stdlib only. Loaded by path (`spec_from_file_location`) and registered under
`MODULE_NAME`, like `shared/tvmaze/tvmaze_api.py`; the tests hand recorded
answers through `transport` and never reach the network.
"""
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RULE = "CF-0690"
PROVIDER = "gemini_api"
API_BASE = "https://generativelanguage.googleapis.com"
GENERATE_PATH = "/v1beta/models/{model}:generateContent"
TERMS_URL = "https://ai.google.dev/gemini-api/terms"
KEY_ENV = "GEMINI_API_KEY"
KEY_HEADER = "x-goog-api-key"
FACTORY_ROOT_ENV = "FACTORY_ROOT"
NO_KEY_REASON = f"no {KEY_ENV} (environment or .env)"
RATE_LIMITED = "rate_limited"

TOOL_NAME = "shorts-content-factory"
TOOL_VERSION = "2.3"

MIN_INTERVAL_SECONDS = 5.0
DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
MAX_RETRY_WAIT_SECONDS = 60
RETRY_STATUS = (429, 500, 502, 503, 504)

STATUS_OK, STATUS_SKIPPED, STATUS_REFUSED = "ok", "skipped", "refused"
STATUSES = (STATUS_OK, STATUS_SKIPPED, STATUS_REFUSED)
PROTOCOL_KEYS = ("provider", "endpoint", "model_requested", "model_version", "prompt",
                 "generation_config", "answer", "finish_reason", "prompt_feedback", "citation",
                 "usage", "response_id", "requested_at", "answered_at", "key_source", "status",
                 "skip_reason")

# An answer that opens like this, or says it is an AI, is a refusal - not a
# demo of what the model can do.
REFUSAL_OPENINGS = ("i can't", "i cannot", "i can not", "i'm unable", "i am unable",
                    "i'm not able", "i am not able", "i won't", "i will not",
                    "i'm sorry", "i am sorry", "sorry,", "unfortunately, i")
REFUSAL_ANYWHERE = ("as an ai", "as a language model", "as a large language model",
                    "i'm just an ai", "i am just an ai")

MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")

# The one name every loader registers this file under.
MODULE_NAME = "factory_gemini_api"

_HERE = Path(__file__).resolve().parent
NOTIFY_PATH = _HERE.parent / "notify.py"


def _load_notify():
    spec = importlib.util.spec_from_file_location("_notify_for_gemini_api", NOTIFY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


notify = _load_notify()
MASK = notify.MASK


class GeminiError(RuntimeError):
    """The API could not be asked: no answer at all, or a status that asking
    again will not change. Its text never carries the key."""


class HttpResponse:
    """What a transport hands back: a status, a body, the headers."""

    def __init__(self, status, body, headers=None):
        self.status = int(status)
        self.body = body
        self.headers = headers or {}

    def header(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


# ------------------------------------------------------------------ the key
def factory_root(environ=None):
    env = os.environ if environ is None else environ
    if env.get(FACTORY_ROOT_ENV):
        return Path(env[FACTORY_ROOT_ENV]).expanduser()
    return _HERE.parents[1]


def _lookup(root=None, environ=None):
    env = os.environ if environ is None else environ
    value = (env.get(KEY_ENV) or "").strip()
    if value:
        return value, "environment"
    base = Path(root) if root is not None else factory_root(env)
    value = (notify.read_env_file(base / ".env").get(KEY_ENV) or "").strip()
    if value:
        return value, ".env"
    return None, None


def api_key(root=None, environ=None):
    """The key, or None. Only this module's request header ever holds it."""
    return _lookup(root, environ)[0]


def key_source(root=None, environ=None):
    """``"environment"``, ``".env"`` or None - never the value."""
    return _lookup(root, environ)[1]


def scrub(text, key=None):
    """`text` with the key (when given) and anything secret-looking masked."""
    text = str(text if text is not None else "")
    if key:
        text = text.replace(str(key), MASK)
    return notify.scrub(text)


def _scrub_obj(obj, key):
    """Every string of a decoded answer scrubbed of the key (the API never
    echoes it - this is the second line under that)."""
    if not key:
        return obj
    if isinstance(obj, str):
        return obj.replace(key, MASK)
    if isinstance(obj, list):
        return [_scrub_obj(v, key) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub_obj(v, key) for k, v in obj.items()}
    return obj


# ------------------------------------------------------------- the network
def user_agent(tool_name=None):
    return (f"{tool_name or TOOL_NAME}/{TOOL_VERSION} "
            f"python-urllib/{sys.version_info.major}.{sys.version_info.minor}")


def urllib_transport(url, headers, body, timeout=DEFAULT_TIMEOUT):
    """The real network: POST `body` (bytes). An HttpResponse for any HTTP
    status; GeminiError only when there was no answer at all - its text names
    the host, never the headers."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read().decode("utf-8", "replace"),
                                dict(response.headers))
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace") if error.fp else ""
        return HttpResponse(error.code, text, dict(error.headers or {}))
    except (urllib.error.URLError, OSError) as error:
        raise GeminiError(f"could not reach {urllib.parse.urlsplit(url).netloc}: "
                          f"{type(error).__name__}") from None


def endpoint(model, api_base=API_BASE):
    """The URL of one model's generateContent - it never carries the key."""
    if not (isinstance(model, str) and MODEL_RE.match(model)):
        raise ValueError(f"model {model!r} is not a model id")
    return api_base.rstrip("/") + GENERATE_PATH.format(model=model)


def _retry_info_seconds(body):
    """RetryInfo.retryDelay ("37s", "1.5s") of an error body, or None."""
    try:
        payload = json.loads(body or "")
    except ValueError:
        return None
    for d in ((payload or {}).get("error") or {}).get("details") or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(d.get("retryDelay") or ""))
            if m:
                return float(m.group(1))
    return None


# ------------------------------------------------------------- the answer
def answer_text(response):
    """candidates[0].content.parts[].text joined verbatim (thought parts left
    out), or ""."""
    cands = (response or {}).get("candidates") or []
    first = cands[0] if cands and isinstance(cands[0], dict) else {}
    parts = (first.get("content") or {}).get("parts") or []
    return "".join(p["text"] for p in parts
                   if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought"))


def has_citation(candidate):
    """Does the candidate carry citation metadata (a recited source)?"""
    meta = (candidate or {}).get("citationMetadata")
    if not isinstance(meta, dict):
        return False
    return any(bool(v) for v in meta.values())


def refusal_phrase(answer):
    """The refusal phrase an answer opens with or carries ("as an AI"), or None."""
    text = " ".join(str(answer or "").replace("’", "'").split()).casefold()
    for phrase in REFUSAL_OPENINGS:
        if text.startswith(phrase):
            return phrase
    for phrase in REFUSAL_ANYWHERE:
        if phrase in text:
            return phrase
    return None


def judge(response):
    """(status, reason) of a decoded generateContent answer: ``ok`` with None,
    or ``refused`` with why."""
    response = response if isinstance(response, dict) else {}
    feedback = response.get("promptFeedback") or {}
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return STATUS_REFUSED, f"prompt blocked: {feedback['blockReason']}"
    cands = response.get("candidates") or []
    first = cands[0] if cands and isinstance(cands[0], dict) else None
    if first is None:
        return STATUS_REFUSED, "no candidate in the answer"
    finish = first.get("finishReason")
    if finish != "STOP":
        return STATUS_REFUSED, f"finish_reason {finish}"
    if has_citation(first):
        return STATUS_REFUSED, "citation metadata - the answer recites a source"
    answer = answer_text(response)
    if not answer.strip():
        return STATUS_REFUSED, "empty answer"
    phrase = refusal_phrase(answer)
    if phrase:
        return STATUS_REFUSED, f"reads as a refusal ({phrase!r})"
    return STATUS_OK, None


def blank_protocol(model, prompt, generation_config=None, *, endpoint_url=None,
                   key_source_=None, requested_at=None):
    return {"provider": PROVIDER, "endpoint": endpoint_url, "model_requested": model,
            "model_version": None, "prompt": prompt, "generation_config": generation_config,
            "answer": None, "finish_reason": None, "prompt_feedback": None, "citation": False,
            "usage": None, "response_id": None, "requested_at": requested_at,
            "answered_at": None, "key_source": key_source_, "status": STATUS_SKIPPED,
            "skip_reason": None}


# ------------------------------------------------------------- the client
class GeminiClient:
    """Serial, rate-limited, retrying client of one endpoint.

    `transport` - ``(url, headers, body_bytes, timeout) -> HttpResponse`` - is
    the seam the tests hand recorded answers through. `log` - a callable of one
    line, or None - gets scrubbed lines only, and of the key only its source."""

    def __init__(self, transport=None, api_base=API_BASE, min_interval=MIN_INTERVAL_SECONDS,
                 timeout=DEFAULT_TIMEOUT, max_retries=MAX_RETRIES, sleep=time.sleep,
                 clock=time.monotonic, wall=time.time, root=None, environ=None,
                 tool_name=None, log=None):
        self.transport = transport or urllib_transport
        self.api_base = api_base.rstrip("/")
        self.min_interval = float(min_interval)
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.tool_name = tool_name
        self._sleep = sleep
        self._clock = clock
        self._wall = wall
        self._root = root
        self._environ = environ
        self._log = log
        self._last_request_at = None
        self.request_count = 0
        self.waited_seconds = 0.0

    def key_source(self):
        return key_source(self._root, self._environ)

    def log(self, line, key=None):
        if self._log is not None:
            self._log(scrub(line, key))

    def _respect_interval(self):
        if self._last_request_at is None:
            return
        remaining = self.min_interval - (self._clock() - self._last_request_at)
        if remaining > 0:
            self.waited_seconds += remaining
            self._sleep(remaining)

    def _retry_delay(self, response, attempt):
        after = response.header("Retry-After")
        if after:
            try:
                return max(0.0, float(str(after).strip()))
            except ValueError:
                pass
        info = _retry_info_seconds(response.body)
        if info is not None:
            return info
        return float(RETRY_BACKOFF_SECONDS * attempt)

    def ask(self, model, prompt, *, generation_config=None):
        """One prompt to one model -> the protocol dict (see the module's
        docstring). Raises GeminiError only when the API could not be asked."""
        if not (isinstance(prompt, str) and prompt.strip()):
            raise ValueError("prompt must be a non-empty string")
        url = endpoint(model, self.api_base)
        key, source = _lookup(self._root, self._environ)
        proto = blank_protocol(model, prompt, generation_config, endpoint_url=url,
                               key_source_=source, requested_at=iso(self._wall()))
        if not key:
            proto["skip_reason"] = NO_KEY_REASON
            self.log(f"gemini_api {model}: skipped - {NO_KEY_REASON}")
            return proto
        self.log(f"gemini_api {model}: asking (key from {source})")
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if generation_config:
            payload["generationConfig"] = generation_config
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {KEY_HEADER: key, "Content-Type": "application/json",
                   "Accept": "application/json", "User-Agent": user_agent(self.tool_name)}
        last = None
        for attempt in range(1, self.max_retries + 1):
            if attempt == 1:
                self._respect_interval()     # a retry has waited at least as long
            try:
                response = self.transport(url, headers, body, self.timeout)
            except GeminiError as error:
                raise GeminiError(scrub(error, key)) from None
            except Exception as error:          # a transport's own failure
                raise GeminiError(f"could not ask {model}: {type(error).__name__}: "
                                  f"{scrub(error, key)}") from None
            finally:
                self._last_request_at = self._clock()
                self.request_count += 1
            if response.status == 200:
                try:
                    decoded = json.loads(response.body)
                except ValueError:
                    raise GeminiError(f"{model}: the API answered something that is not "
                                      f"JSON") from None
                return self._protocol(proto, _scrub_obj(decoded, key), model)
            if response.status not in RETRY_STATUS:
                raise GeminiError(scrub(f"HTTP {response.status} from {url}: "
                                        f"{_error_message(response.body)}", key))
            last = response.status
            if attempt >= self.max_retries:
                break
            delay = max(self._retry_delay(response, attempt), self.min_interval)
            if delay > MAX_RETRY_WAIT_SECONDS:
                self.log(f"gemini_api {model}: HTTP {last}, retry in {delay:.0f}s is past "
                         f"{MAX_RETRY_WAIT_SECONDS}s - not waited")
                break
            self.log(f"gemini_api {model}: HTTP {last}, retry {attempt} in {delay:.1f}s")
            self.waited_seconds += delay
            self._sleep(delay)
        proto["skip_reason"] = RATE_LIMITED if last == 429 else f"unavailable: HTTP {last}"
        proto["answered_at"] = iso(self._wall())
        self.log(f"gemini_api {model}: skipped - {proto['skip_reason']}")
        return proto

    def _protocol(self, proto, response, model):
        cands = response.get("candidates") or []
        first = cands[0] if cands and isinstance(cands[0], dict) else {}
        proto.update(
            model_version=response.get("modelVersion"),
            answer=answer_text(response),
            finish_reason=first.get("finishReason"),
            prompt_feedback=response.get("promptFeedback"),
            citation=has_citation(first),
            usage=response.get("usageMetadata"),
            response_id=response.get("responseId"),
            answered_at=iso(self._wall()))
        status, reason = judge(response)
        proto["status"], proto["skip_reason"] = status, reason
        self.log(f"gemini_api {model}: {status}" + (f" - {reason}" if reason else ""))
        return proto


def _error_message(body):
    """The API's own error message (`error.message`), shortened."""
    try:
        msg = ((json.loads(body or "") or {}).get("error") or {}).get("message")
    except (ValueError, AttributeError):
        msg = None
    return " ".join(str(msg or body or "").split())[:200]


def ask(model, prompt, *, generation_config=None, client=None, **client_kw):
    """One call with a client of its own (or `client`): the protocol dict."""
    return (client or GeminiClient(**client_kw)).ask(model, prompt,
                                                     generation_config=generation_config)
