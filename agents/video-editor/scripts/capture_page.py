#!/usr/bin/env python3
"""CF-0071: `headless_browser` - the policy half of capturing a publisher's
article header (inserts/proof.json capture_methods[headless_browser]).

Everything the contract's `behaviour` block decides *before* a browser is
started lives here, in one class, so that a test can exercise every rule
without a network and without Chrome:

    allowed hosts     the channel's sources.rss.feeds[].site and their www.
                      aliases, nothing else; x.com / twitter.com / t.co are
                      never fetched whatever the pool says
    robots.txt        the CF-0045 stance: our honest User-Agent (never a
                      browser's, never a named crawler's), the `User-agent: *`
                      rules honoured, a disallowed path is a fetch failure
    rate              PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST between two
                      requests to one host (the clock and the sleep are
                      injectable)
    budget            PROOF_MAX_REQUESTS_PER_HOST_PER_BATCH page requests per
                      host per batch, PROOF_MAX_ATTEMPTS_PER_URL per URL
    telemetry         requests_by_host and fetch_failures[{url, reason}] -
                      the `proof_capture_telemetry` the plan and the batch
                      metadata carry, so the ceiling can be re-derived from
                      a measurement

The browser half is capture_page.mjs, driven through `fetch_page` - the
default runs Node against the chrome-headless-shell Remotion installs under
render/node_modules/.remotion (no new browser dependency); a test injects a
function that returns the same dict shape. Every failure is a *fetch*
failure in the contract's sense (`fetch_failure_means`): the caller moves
to the next capture method. A capture that comes back is never judged here
- the legibility gate is proof_layer.check_proof_gates(), and failing it
stops the chain (degradation.never_substitute).

Usage:
    capture_page.py <url> <out.png> --site variety.com [--site ...]
        [--region article_header] [--chrome <binary>]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from common import (AGENT_ROOT, PROOF_DEVICE_SCALE_FACTOR, PROOF_MAX_ATTEMPTS_PER_URL,
                    PROOF_MAX_REQUESTS_PER_HOST_PER_BATCH,
                    PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST, PROOF_NOT_FOR_HOSTS,
                    PROOF_REGION_DEFAULT, PROOF_REGION_MAX_HEIGHT_PX, PROOF_REGIONS,
                    PROOF_REGION_STANDFIRST, PROOF_TEXT_SIDECAR_SUFFIX,
                    PROOF_TIMEOUT_SECONDS, PROOF_USER_AGENT, PROOF_VIEWPORT_HEIGHT,
                    PROOF_VIEWPORT_WIDTH, SCRIPTS)
import repo_paths  # CF-0125: node_modules/ is gitignored, so it is main-checkout-only
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

CHROME_ENV = "PROOF_CHROME"
NODE_ENV = "PROOF_NODE"
CAPTURE_MJS = SCRIPTS / "capture_page.mjs"
ROBOTS_TIMEOUT = 10

# Fetch-failure reasons (fetch_failure_means, one name each). Closed list;
# the telemetry's `reason` is one of these or the browser's own http_<n> /
# no_h1 / timeout / navigation_error / headline_below_region_max.
FAIL_HOST_NOT_ALLOWED = "host_not_allowed"
FAIL_HOST_NOT_FOR = "host_not_for"
FAIL_ROBOTS = "robots_disallowed"
FAIL_BUDGET = "host_budget_spent"
FAIL_ATTEMPTED = "url_already_attempted"
FAIL_REDIRECT = "redirect_off_pool"
FAIL_NO_BROWSER = "no_browser"
FAIL_NO_FILE = "no_file"


@dataclass
class CaptureResult:
    ok: bool
    reason: str | None
    file: str | None = None
    status: int | None = None
    final_url: str | None = None
    h1_text: str | None = None
    region: str | None = None
    proof_text: dict | None = None   # {h1, standfirst} as written to the sidecar (ok only)
    width: int | None = None
    height: int | None = None
    requested: bool = False   # whether a page request actually went out


def proof_text_path(capture_path):
    """The sidecar beside a capture: <capture>.proof_text.json, i.e. the PNG
    path with its suffix replaced - proof-p1-headless_browser.proof_text.json."""
    return Path(capture_path).with_suffix(PROOF_TEXT_SIDECAR_SUFFIX)


def write_proof_text(capture_path, h1_text, standfirst_text=None, region=None):
    """inserts/proof.json legibility.gating_lines.headless_browser.proof_text_shape:
    {h1: str, standfirst: str|null} from the rendered DOM, written beside the
    file by the capture step so the gate takes it as input and never re-fetches.
    The standfirst is carried only for the article_header_with_standfirst
    region - on any other region it was not captured and must not gate."""
    h1 = " ".join(str(h1_text or "").split())
    sf = " ".join(str(standfirst_text or "").split()) or None
    if region != PROOF_REGION_STANDFIRST:
        sf = None
    proof_text = {"h1": h1, "standfirst": sf}
    proof_text_path(capture_path).write_text(json.dumps(proof_text, ensure_ascii=False, indent=1))
    return proof_text


def read_proof_text(capture_path):
    """The sidecar's content, or None when there is none beside the capture."""
    path = proof_text_path(capture_path)
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not str(d.get("h1") or "").strip():
        return None
    return {"h1": str(d["h1"]), "standfirst": (str(d["standfirst"]) if d.get("standfirst") else None)}


def host_of(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host


def bare_host(host):
    return host[4:] if host.startswith("www.") else host


def pool_hosts(channel_cfg):
    """The publisher pool: sources.rss.feeds[].site of a channel config."""
    feeds = (((channel_cfg or {}).get("sources") or {}).get("rss") or {}).get("feeds") or []
    return sorted({bare_host(str(f.get("site", "")).lower()) for f in feeds if f.get("site")})


def find_chrome():
    """The chrome-headless-shell Remotion installed: $PROOF_CHROME, this
    checkout's render/node_modules/.remotion, or the main checkout's (a
    worktree has no node_modules of its own - node_modules/ is gitignored;
    repo_paths asks git which checkout is the main one, CF-0125)."""
    override = os.environ.get(CHROME_ENV)
    if override:
        return override if Path(override).exists() else None
    roots = [AGENT_ROOT, repo_paths.MAIN_CHECKOUT]
    for r in roots:
        base = r / "render" / "node_modules" / ".remotion" / "chrome-headless-shell"
        if base.is_dir():
            for cand in sorted(base.rglob("chrome-headless-shell")):
                if cand.is_file() and os.access(cand, os.X_OK):
                    return str(cand)
    return None


def fetch_page_with_chrome(url, dest, region, user_agent=PROOF_USER_AGENT,
                           timeout=PROOF_TIMEOUT_SECONDS, chrome=None):
    """Run capture_page.mjs once. Returns its JSON dict, or a dict with
    ok False and a reason when the browser could not be run at all."""
    chrome = chrome or find_chrome()
    if not chrome:
        return {"ok": False, "reason": FAIL_NO_BROWSER,
                "detail": f"no chrome-headless-shell under render/node_modules/.remotion; set ${CHROME_ENV}"}
    cmd = [os.environ.get(NODE_ENV, "node"), str(CAPTURE_MJS),
           "--chrome", chrome, "--url", url, "--out", str(dest), "--region", region,
           "--user-agent", user_agent, "--timeout", str(timeout),
           "--max-height", str(PROOF_REGION_MAX_HEIGHT_PX),
           "--width", str(PROOF_VIEWPORT_WIDTH), "--height", str(PROOF_VIEWPORT_HEIGHT),
           "--scale", str(PROOF_DEVICE_SCALE_FACTOR)]
    try:
        out = runlog.run_child(cmd, tool="chrome", capture_output=True, text=True,
                               timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "detail": "capture_page.mjs did not return"}
    except OSError as e:
        return {"ok": False, "reason": FAIL_NO_BROWSER, "detail": str(e)}
    line = next((ln for ln in reversed(out.stdout.splitlines()) if ln.startswith("{")), None)
    if not line:
        return {"ok": False, "reason": "browser_error",
                "detail": (out.stderr or "").strip()[-400:] or f"exit {out.returncode}"}
    try:
        return json.loads(line)
    except ValueError:
        return {"ok": False, "reason": "browser_error", "detail": line[:200]}


def fetch_robots_txt(host, user_agent=PROOF_USER_AGENT, timeout=ROBOTS_TIMEOUT):
    """The host's robots.txt text, or None when there is none (404 - open by
    default) or it could not be read. Sent under our own name, like every
    other request this method makes."""
    req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read(256 * 1024).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def robots_allows(robots_text, url):
    """`User-agent: *` rules of robots.txt over the URL's path. No file is
    an open site; a file that names no rule for `*` is open too."""
    if not robots_text:
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(robots_text.splitlines())
    return rp.can_fetch("*", url)


class HeadlessCapture:
    """One instance per batch: the per-host counters are the batch's budget.

    allowed_hosts: bare hostnames (no www.) - pool_hosts(channel_cfg).
    fetch_page(url, dest, region) -> dict like capture_page.mjs prints.
    fetch_robots(host) -> robots.txt text or None.
    clock() -> seconds; sleep(seconds). Both injectable for a test.
    """

    def __init__(self, allowed_hosts, user_agent=PROOF_USER_AGENT, fetch_page=None,
                 fetch_robots=None, clock=time.monotonic, sleep=time.sleep,
                 min_gap=PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST,
                 max_per_host=PROOF_MAX_REQUESTS_PER_HOST_PER_BATCH,
                 max_attempts_per_url=PROOF_MAX_ATTEMPTS_PER_URL, chrome=None):
        self.allowed = {bare_host(h.lower()) for h in allowed_hosts if h}
        self.user_agent = user_agent
        self._fetch_page = fetch_page or (
            lambda url, dest, region: fetch_page_with_chrome(url, dest, region,
                                                             user_agent=self.user_agent,
                                                             chrome=chrome))
        self._fetch_robots = fetch_robots or (lambda host: fetch_robots_txt(host, self.user_agent))
        self.clock = clock
        self.sleep = sleep
        self.min_gap = min_gap
        self.max_per_host = max_per_host
        self.max_attempts_per_url = max_attempts_per_url
        self.robots_cache = {}
        self.last_request_at = {}
        self.attempts_by_url = {}
        self.telemetry = {"requests_by_host": {}, "fetch_failures": []}

    # -- policy -----------------------------------------------------------

    def host_allowed(self, host):
        bare = bare_host(host)
        if not bare or bare in PROOF_NOT_FOR_HOSTS or host in PROOF_NOT_FOR_HOSTS:
            return False, FAIL_HOST_NOT_FOR
        if bare not in self.allowed:
            return False, FAIL_HOST_NOT_ALLOWED
        return True, None

    def robots_ok(self, host, url):
        if host not in self.robots_cache:
            self.robots_cache[host] = self._fetch_robots(host)
        return robots_allows(self.robots_cache[host], url)

    def _fail(self, url, reason, **extra):
        self.telemetry["fetch_failures"].append({"url": url, "reason": reason})
        return CaptureResult(ok=False, reason=reason, **extra)

    # -- the one public call ------------------------------------------------

    def capture(self, url, dest, region=PROOF_REGION_DEFAULT):
        if region not in PROOF_REGIONS:
            region = PROOF_REGION_DEFAULT
        host = host_of(url)
        ok, why = self.host_allowed(host)
        if not ok:
            return self._fail(url, why)
        bare = bare_host(host)
        if self.attempts_by_url.get(url, 0) >= self.max_attempts_per_url:
            return self._fail(url, FAIL_ATTEMPTED)
        if self.telemetry["requests_by_host"].get(bare, 0) >= self.max_per_host:
            return self._fail(url, FAIL_BUDGET)
        if not self.robots_ok(host, url):
            return self._fail(url, FAIL_ROBOTS)

        # Rate: never two requests to one host closer than min_gap.
        last = self.last_request_at.get(bare)
        if last is not None:
            wait = self.min_gap - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self.attempts_by_url[url] = self.attempts_by_url.get(url, 0) + 1
        self.telemetry["requests_by_host"][bare] = self.telemetry["requests_by_host"].get(bare, 0) + 1
        self.last_request_at[bare] = self.clock()

        res = self._fetch_page(url, str(dest), region) or {}
        common = {"status": res.get("status"), "final_url": res.get("final_url"),
                  "h1_text": res.get("h1_text"), "region": region, "requested": True}
        if not res.get("ok"):
            return self._fail(url, str(res.get("reason") or "browser_error"), **common)
        final_host = host_of(res.get("final_url") or url)
        if final_host and bare_host(final_host) not in self.allowed:
            return self._fail(url, FAIL_REDIRECT, **common)
        if not Path(dest).exists():
            return self._fail(url, FAIL_NO_FILE, **common)
        proof_text = write_proof_text(dest, res.get("h1_text"), res.get("standfirst_text"), region)
        return CaptureResult(ok=True, reason=None, file=str(Path(dest).resolve()),
                             width=res.get("width"), height=res.get("height"),
                             proof_text=proof_text, **common)


def main(argv=None):
    ap = argparse.ArgumentParser(description="capture a publisher's article header, within policy")
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--site", action="append", default=[], help="allowed host (repeatable)")
    ap.add_argument("--channel", help="channel config .json whose sources.rss.feeds[].site is the pool")
    ap.add_argument("--region", default=PROOF_REGION_DEFAULT, choices=PROOF_REGIONS)
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.out))  # CF-0107
    hosts = list(a.site)
    if a.channel:
        hosts += pool_hosts(json.load(open(a.channel)))
    cap = HeadlessCapture(hosts, chrome=a.chrome)
    res = cap.capture(a.url, a.out, a.region)
    print(json.dumps({**res.__dict__, "telemetry": cap.telemetry}, indent=2))
    return 0 if res.ok else 1


@video_script("video-editor", "capture", name="capture_page.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
