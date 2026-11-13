#!/usr/bin/env python3
"""CF-0020: the thin adapter between the Analyst and the YouTube Analytics API v2.

`AnalyticsClient.query(**params)` is the only call that reaches Google -
`reports.query` - and it makes no decisions. The decisions are here, in plain
functions the tests drive with a stand-in client and stand-in errors:

* `classify(exc)` - what a failure means:
    retry      429, 5xx, a dropped connection, a 403 whose reason is a quota or
               rate limit (`quotaExceeded`, `rateLimitExceeded`, ...);
    reauth     401, or `invalid_grant` while the library refreshes the token
               -> `publisher_auth.TokenExpiredError`;
    scope      403 `insufficientPermissions` / `ACCESS_TOKEN_SCOPE_INSUFFICIENT`
               -> `publisher_auth.MissingScopeError` (yt-analytics.readonly);
    disabled   (CF-0623) 403 `accessNotConfigured` / `SERVICE_DISABLED`, or the
               text "has not been used in project ... or it is disabled": the
               API is switched off in the Google Cloud project - an error of the
               whole run, never a video's; `ApiError.activation_url` carries
               the page that switches it on (from the answer);
    bad        400 - the request itself is wrong (e.g. a metric the report does
               not support): never retried;
    forbidden  any other 403 - typically a video the token's channel does not
               own: never retried, the video is skipped with a mark (a run in
               which every video is refused is not ok - metrics.py);
    fatal      anything else.
* `call_with_retry(fn)` - runs `fn`, waits `PAUSES` seconds between the retries
  of a `retry` failure, and after the last one raises `ApiError` (the run stops
  with a non-zero code, no stack). The Analytics API has its own quota,
  separate from the Data API's upload and search buckets; a day of collection
  is two queries per live video for the daily rows, plus two per window still
  open (CF-0624, `metrics.py`).

The Google library is imported only when a real client is built, so
`--dry-run` and the tests run on the system python without it.
"""
import json
import re
import time

PAUSES = (5, 20, 60)          # seconds before the 1st, 2nd, 3rd retry
RETRY_STATUS = {429, 500, 502, 503, 504}
QUOTA_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded",
                 "dailyLimitExceeded", "RESOURCE_EXHAUSTED"}
SCOPE_REASONS = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
DISABLED_REASONS = {"accessNotConfigured", "SERVICE_DISABLED"}
DISABLED_TEXT = re.compile(r"has not been used in project .{0,80}?(before )?or it is disabled",
                           re.IGNORECASE | re.DOTALL)
CONSOLE_URL = re.compile(r"https://console\.(?:developers|cloud)\.google\.com/[^\s\"'<>]+")
CONNECTION_ERRORS = {"HttpLib2Error", "ConnectionError", "TimeoutError", "IncompleteRead",
                     "BrokenPipeError", "ServerNotFoundError", "socket.timeout"}


class ApiError(Exception):
    """A query that failed for good. `kind` is the `classify()` verdict."""

    def __init__(self, msg, kind="fatal", status=None, reason=None, activation_url=None):
        super().__init__(msg)
        self.kind, self.status, self.reason = kind, status, reason
        self.activation_url = activation_url


def http_status(exc):
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _error_body(exc):
    """The `error` object of a Google error body (`exc.content`), or {}."""
    content = getattr(exc, "content", None)
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    try:
        err = json.loads(content or "").get("error", {})
    except (ValueError, AttributeError):
        return {}
    return err if isinstance(err, dict) else {}


def error_reasons(exc):
    """The `reason`/`status` strings of a Google error body (`exc.content`),
    best effort; an empty set when there is no parsable body."""
    out = set()
    err = _error_body(exc)
    if isinstance(err, dict):
        if err.get("status"):
            out.add(str(err["status"]))
        for item in err.get("errors") or []:
            if isinstance(item, dict) and item.get("reason"):
                out.add(str(item["reason"]))
        for item in err.get("details") or []:
            if isinstance(item, dict) and item.get("reason"):
                out.add(str(item["reason"]))
    return out


def activation_url(exc):
    """CF-0623: the page that switches a disabled API on - the ErrorInfo's
    `metadata.activationUrl`, else the console URL in the message; None."""
    err = _error_body(exc)
    for item in err.get("details") or []:
        url = isinstance(item, dict) and (item.get("metadata") or {}).get("activationUrl")
        if url:
            return str(url)
    for text in (err.get("message"), str(exc)):
        m = CONSOLE_URL.search(str(text or ""))
        if m:
            return m.group(0).rstrip(".,;)")
    return None


def is_disabled(exc, reasons=None):
    """CF-0623: the API is switched off in the token's Google Cloud project."""
    reasons = error_reasons(exc) if reasons is None else reasons
    if reasons & DISABLED_REASONS:
        return True
    return bool(DISABLED_TEXT.search(f"{_error_body(exc).get('message') or ''} {exc}"))


def classify(exc):
    status = http_status(exc)
    reasons = error_reasons(exc)
    if "invalid_grant" in str(exc):
        return "reauth"
    if status == 401:
        return "reauth"
    if status == 403:
        if reasons & SCOPE_REASONS:
            return "scope"
        if is_disabled(exc, reasons):
            return "disabled"
        if reasons & QUOTA_REASONS:
            return "retry"
        return "forbidden"
    if status in RETRY_STATUS:
        return "retry"
    if status == 400:
        return "bad"
    if status is None:
        names = {c.__name__ for c in type(exc).__mro__}
        if names & CONNECTION_ERRORS:
            return "retry"
    return "fatal"


def _short(exc, limit=300):
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[:limit] + "..."


def call_with_retry(fn, sleep=time.sleep, pauses=PAUSES, auth=None):
    """`fn()`; a `retry` failure is repeated after each of `pauses`, then the
    last one becomes `ApiError`. `reauth`/`scope` raise the CF-0589 exceptions
    of `auth` (the publisher_auth module), everything else `ApiError` at once."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:                                  # noqa: BLE001
            kind = classify(e)
            status = http_status(e)
            reason = ",".join(sorted(error_reasons(e))) or None
            if kind == "reauth" and auth is not None:
                raise auth.TokenExpiredError(
                    f"YouTube Analytics refused the token ({_short(e)}) - the user re-authorizes: "
                    f"`{auth.AUTHORIZE_COMMAND}`") from e
            if kind == "scope" and auth is not None:
                raise auth.MissingScopeError([auth.ANALYTICS_SCOPE]) from e
            if kind == "retry" and attempt < len(pauses):
                sleep(pauses[attempt])
                attempt += 1
                continue
            what = f"HTTP {status}" if status else type(e).__name__
            url = activation_url(e) if kind == "disabled" else None
            if kind == "disabled":
                msg = (f"{what} ({reason}): YouTube Analytics API is disabled in the Google Cloud "
                       f"project of the token - not a refusal of a video"
                       + (f"; switch it on: {url}" if url else "") + f" ({_short(e, 200)})")
            elif kind == "retry":
                msg = f"{what}{f' ({reason})' if reason else ''} after {attempt} retries: {_short(e)}"
            else:
                msg = f"{what}{f' ({reason})' if reason else ''}: {_short(e)}"
            raise ApiError(msg, kind=kind, status=status, reason=reason,
                           activation_url=url) from e


def parse_report(resp):
    """{day: {metric: value}} of a `reports.query` answer with `dimensions=day`.
    No rows (a video too fresh for data) is an empty dict."""
    if not isinstance(resp, dict):
        raise ApiError(f"the API answered with {type(resp).__name__}, not a result table", "fatal")
    headers = [h.get("name") for h in resp.get("columnHeaders") or []]
    if "day" not in headers:
        raise ApiError(f"no `day` column in the answer (columns: {headers})", "fatal")
    out = {}
    for row in resp.get("rows") or []:
        if len(row) != len(headers):
            raise ApiError(f"a row of {len(row)} values under {len(headers)} columns: {row!r}",
                           "fatal")
        rec = dict(zip(headers, row))
        day = str(rec.pop("day"))
        out[day] = {k: v for k, v in rec.items() if k != "video"}
    return out


def parse_total(resp):
    """CF-0624: {metric: value} of a `reports.query` answer without
    `dimensions` - one row, YouTube's own totals and averages over the period.
    No rows (no data for the period yet) is an empty dict."""
    if not isinstance(resp, dict):
        raise ApiError(f"the API answered with {type(resp).__name__}, not a result table", "fatal")
    headers = [h.get("name") for h in resp.get("columnHeaders") or []]
    rows = resp.get("rows") or []
    if not rows:
        return {}
    if "day" in headers:
        raise ApiError(f"a `day` column in a window answer (columns: {headers}) - the window "
                       f"is asked without dimensions", "fatal")
    if len(rows) != 1:
        raise ApiError(f"{len(rows)} rows in a window answer without dimensions, not one", "fatal")
    if len(rows[0]) != len(headers):
        raise ApiError(f"a row of {len(rows[0])} values under {len(headers)} columns: {rows[0]!r}",
                       "fatal")
    return {k: v for k, v in zip(headers, rows[0]) if k != "video"}


class AnalyticsClient:
    """The only place that calls Google. Built from credentials carrying
    yt-analytics.readonly (`publisher_auth.analytics_credentials`)."""

    def __init__(self, credentials, build=None):
        if build is None:
            try:
                from googleapiclient.discovery import build as _build    # noqa: PLC0415
            except ImportError as e:
                raise ApiError(f"google-api-python-client is not installed ({e.name}) - run "
                               f"with agents/publisher/.venv/bin/python", "fatal") from e
            build = _build
        self._ya = build("youtubeAnalytics", "v2", credentials=credentials,
                         cache_discovery=False)

    def query(self, **params):
        return self._ya.reports().query(**params).execute()
