#!/usr/bin/env python3
"""CF-0567: the own-capture recorder - the factory's own screen recording of
the tool a Tech story is about, working on a public page (the root's
`docs/tech-footage.md`, «Own capture - the main footage»; the «демо» pattern's
footage).

The policy half. Everything that decides whether a page may be recorded runs
here, before a browser is started, in one class a test can drive without a
network and without Chrome:

    the channel's rule   the URL must pass the root's
                         `footage_licence.capture_allowed(url, footage_origin(channel))`
                         - an https page on a `capture_hosts` host whose `use`
                         is `capture` (there is no default host)
    no sign-in           a host whose `sign_in` is true is refused whatever
                         its `use` says - signed-in capture is CF-0688 (Q26),
                         not this recorder
    robots.txt           re-read at capture time for the exact host and the
                         exact path: the 08.10 rule (`source_policy.check_url`
                         of the root - closed to `*` or to one of Anthropic's
                         agents is `forbidden`, an unreadable file is
                         `unknown`; only `allowed` records) and the factory's
                         own User-Agent (capture_page.robots_allows' reading)
    the Space's card     a Hugging Face Space (`hf.space`) is recorded only
                         when its card names a licence:
                         https://huggingface.co/api/spaces/<owner>/<space>,
                         public, no key; a private or disabled Space is not
                         public
    the steps            a small JSON list (wait / scroll / click / type /
                         press / wait_for), checked before anything runs
    the cap              CAPTURE_MAX_SECONDS whatever the caller asks
    rate                 PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST between
                         two recordings of one host (clock and sleep
                         injectable)

The browser half is capture_tool.mjs (Remotion's chrome-headless-shell over
CDP, as capture_page.mjs): it loads the page signed out, starts
`Page.startScreencast`, plays the steps and writes the frames; this file
assembles them into an mp4 with ffmpeg (540x960 CSS px at 2x - 1080x1920, the
delivered frame, so the editor crops nothing). A redirect off the capture host
discards the take.

What comes out, in `<out_dir>`:

    own_capture-<id>.mp4               the recording
    own_capture-<id>.own_capture.json  the sidecar (SIDECAR_FIELDS below):
                                       url, host, captured_at, steps,
                                       duration, the capture_allowed verdict,
                                       the robots read, the Space's licence,
                                       origin `own_capture`, found_by
                                       {how: screen_capture}

`own_capture-<id>` is the source's file id (`_clip_names.OWN_CAPTURE_PREFIX`);
the Footage Indexer ingests it as `own_capture:<id>` (its FI step), as it does
`nasa:<id>` -> `nasa-<id>`. `<id>` is `<page slug>-<UTC stamp>`.

Usage:
    capture_tool.py <https url> <out_dir> --channel <channel id>
        [--steps steps.json] [--space <owner>/<space>] [--max-seconds 30]
        [--id <id>] [--root <factory root>] [--chrome <binary>]
Prints the result as JSON; exit 0 = recorded, 1 = refused or failed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from common import PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST, PROOF_USER_AGENT, SCRIPTS
import _clip_names
from _root_shared import root_module
from capture_page import NODE_ENV, find_chrome, host_of
from _runlog import runlog, video_script  # noqa: E402 - CF-0107 run accounting

SCHEMA = "own-capture/1"
OWN_CAPTURE = "own_capture"            # footage_licence.OWN_CAPTURE, the kind's name
FOUND_BY = {"how": "screen_capture", "ref": "capture_hosts"}
SIDECAR_SUFFIX = _clip_names.OWN_CAPTURE_SIDECAR_SUFFIX
CAPTURE_MJS = SCRIPTS / "capture_tool.mjs"

# The recording. 540x960 CSS px at 2x is the delivered 1080x1920.
VIEWPORT_WIDTH = 540
VIEWPORT_HEIGHT = 960
DEVICE_SCALE = 2
FRAME_WIDTH = VIEWPORT_WIDTH * DEVICE_SCALE
FRAME_HEIGHT = VIEWPORT_HEIGHT * DEVICE_SCALE
FPS = 30
CAPTURE_MAX_SECONDS = 60.0     # the hard cap: no take is longer, whatever is asked
CAPTURE_DEFAULT_SECONDS = 30.0
CAPTURE_TAIL_SECONDS = 1.0     # the result held after the last step
LOAD_TIMEOUT_SECONDS = 30.0
ASSEMBLY_TIMEOUT_SECONDS = 240
ROBOTS_TIMEOUT = 10
API_TIMEOUT = 15

# A Hugging Face Space's own app host and its public card.
SPACE_HOST = "hf.space"
SPACE_API = "https://huggingface.co/api/spaces/{space}"

# The steps the browser half plays, and their bounds.
STEP_KINDS = ("wait", "scroll", "click", "type", "press", "wait_for")
STEP_KEYS = ("Enter", "Tab")
MAX_STEPS = 24
MAX_STEP_SECONDS = 20.0
MAX_TYPED_CHARS = 200
MAX_SCROLL_PX = 20000

# Refusals - every one decided before a page is opened - and failures.
REFUSE_NOT_HTTPS = "not_https"
REFUSE_HOST_NOT_LISTED = "host_not_listed"
REFUSE_HOST_CLOSED = "host_closed"
REFUSE_SIGN_IN = "sign_in_host"
REFUSE_NO_RULE = "no_capture_rule"
REFUSE_ROBOTS = "robots_disallowed"
REFUSE_ROBOTS_UNREAD = "robots_unread"
REFUSE_SPACE_NOT_NAMED = "space_not_named"
REFUSE_SPACE_CARD_UNREAD = "space_card_unread"
REFUSE_SPACE_NOT_PUBLIC = "space_not_public"
REFUSE_SPACE_NO_LICENCE = "space_no_licence"
REFUSE_BAD_STEPS = "bad_steps"
REFUSE_REDIRECT = "redirect_off_host"
FAIL_NO_BROWSER = "no_browser"
FAIL_ASSEMBLY = "assembly_failed"

SIDECAR_FIELDS = ("schema", "id", "file_id", "file", "origin", "licence", "found_by",
                  "url", "final_url", "host", "capture_host", "host_entry",
                  "capture_allowed", "robots", "space", "steps", "steps_done",
                  "duration_s", "max_seconds", "capped", "fps", "width", "height",
                  "frames", "captured_at", "user_agent", "channel", "recorder")


@dataclass
class CaptureResult:
    ok: bool
    reason: str | None
    detail: str | None = None
    file: str | None = None
    sidecar: str | None = None
    record: dict | None = None
    requested: bool = False          # whether the page itself was opened
    checks: dict = field(default_factory=dict)


# ------------------------------------------------------------ small readers
def sidecar_path(mp4):
    """`<dir>/own_capture-<id>.mp4` -> `<dir>/own_capture-<id>.own_capture.json`."""
    p = Path(mp4)
    return p.with_name(p.stem + SIDECAR_SUFFIX)


def read_sidecar(mp4_or_sidecar):
    """The sidecar beside a recording (or at the path given), or None."""
    p = Path(mp4_or_sidecar)
    if not p.name.endswith(SIDECAR_SUFFIX):
        p = sidecar_path(p)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("origin") == OWN_CAPTURE else None


def _slug(text, most=48):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:most].strip("-") or "page"


def capture_id(url, space=None, now=None):
    """`<page slug>-<UTC stamp>`: the Space's `owner-name`, else the host's
    first label, and the second the recording started."""
    now = now or datetime.now(timezone.utc)
    base = space.replace("/", "-") if space else (host_of(url).split(".")[0] or "page")
    return f"{_slug(base)}-{now.strftime('%Y%m%dt%H%M%Sz')}"


def space_subdomain(space):
    """The app host's first label Hugging Face gives `<owner>/<space>`:
    lower case, `/`, `_` and `.` as `-`."""
    return re.sub(r"[/_.]+", "-", str(space or "").lower()).strip("-")


def space_licence(card):
    """The licence a Space's card names (`cardData.license`, else a
    `license:<id>` tag), or None."""
    if not isinstance(card, dict):
        return None
    lic = (card.get("cardData") or {}).get("license")
    if isinstance(lic, list):
        lic = ", ".join(str(x) for x in lic if str(x).strip())
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    for tag in card.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("license:") and tag[8:].strip():
            return tag[8:].strip()
    return None


def step_errors(steps):
    """Why a script of steps may not be played ([] when it may)."""
    if steps is None:
        return []
    if not isinstance(steps, list):
        return ["the steps are a JSON list"]
    if len(steps) > MAX_STEPS:
        return [f"{len(steps)} steps - at most {MAX_STEPS}"]
    errs = []
    for i, s in enumerate(steps):
        ctx = f"step {i}"
        if not isinstance(s, dict) or s.get("do") not in STEP_KINDS:
            errs.append(f"{ctx}: `do` must be one of {STEP_KINDS}")
            continue
        kind = s["do"]
        secs = s.get("seconds")
        if secs is not None and (isinstance(secs, bool) or not isinstance(secs, (int, float))
                                 or not 0 <= secs <= MAX_STEP_SECONDS):
            errs.append(f"{ctx}: seconds must be 0..{MAX_STEP_SECONDS}")
        if kind in ("click", "type", "wait_for"):
            if not isinstance(s.get("selector"), str) or not s["selector"].strip():
                errs.append(f"{ctx}: {kind} needs a CSS `selector`")
        if kind == "wait" and secs is None:
            errs.append(f"{ctx}: wait needs `seconds`")
        if kind == "scroll":
            by = s.get("by")
            if isinstance(by, bool) or not isinstance(by, (int, float)) or abs(by) > MAX_SCROLL_PX:
                errs.append(f"{ctx}: scroll needs `by` (CSS px, at most {MAX_SCROLL_PX})")
        if kind == "type":
            text = s.get("text")
            if not isinstance(text, str) or not text or len(text) > MAX_TYPED_CHARS:
                errs.append(f"{ctx}: type needs `text` (1..{MAX_TYPED_CHARS} chars)")
            if re.search(r"password|passwd|login|sign.?in", str(s.get("selector") or ""), re.I):
                errs.append(f"{ctx}: a sign-in field is never typed into (Q26)")
        if kind == "press" and s.get("key") not in STEP_KEYS:
            errs.append(f"{ctx}: press takes one of {STEP_KEYS}")
    return errs


# ------------------------------------------------------------ the network
def fetch_robots(robots_url, user_agent=PROOF_USER_AGENT, timeout=ROBOTS_TIMEOUT):
    """-> (status, content_type, text), the shape `source_policy.check_url`
    takes. Sent under our own name."""
    req = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return (resp.status, resp.headers.get("Content-Type", ""),
                    resp.read(500_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.headers.get("Content-Type", "") if exc.headers else ""), ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def fetch_space_card(space, user_agent=PROOF_USER_AGENT, timeout=API_TIMEOUT):
    """The Space's public card (no key), or None when it cannot be read."""
    req = urllib.request.Request(SPACE_API.format(space=space),
                                 headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            d = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
            return d if isinstance(d, dict) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def record_with_chrome(url, frames_dir, steps, max_seconds, user_agent=PROOF_USER_AGENT,
                       chrome=None, timeout=LOAD_TIMEOUT_SECONDS):
    """Run capture_tool.mjs once -> its JSON dict (or ok False with a reason)."""
    chrome = chrome or find_chrome()
    if not chrome:
        return {"ok": False, "reason": FAIL_NO_BROWSER,
                "detail": "no chrome-headless-shell under render/node_modules/.remotion; "
                          "set $PROOF_CHROME"}
    steps_file = Path(frames_dir) / "steps.json"
    steps_file.write_text(json.dumps(steps or []))
    cmd = [os.environ.get(NODE_ENV, "node"), str(CAPTURE_MJS), "--chrome", chrome,
           "--url", url, "--frames-dir", str(frames_dir), "--steps", str(steps_file),
           "--max-seconds", str(max_seconds), "--tail", str(CAPTURE_TAIL_SECONDS),
           "--user-agent", user_agent, "--timeout", str(timeout),
           "--width", str(VIEWPORT_WIDTH), "--height", str(VIEWPORT_HEIGHT),
           "--scale", str(DEVICE_SCALE)]
    try:
        out = runlog.run_child(cmd, tool="chrome", capture_output=True, text=True,
                               timeout=timeout + max_seconds + 30)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "detail": "capture_tool.mjs did not return"}
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


def frame_sequence(frames, stopped_at, fps=FPS):
    """The screencast's frames as a constant-rate sequence: output frame k
    (at k / fps from the first frame) is the last frame that had arrived by
    then. A screencast sends a frame only when the picture changes, so a
    frame stands until the next one, and the last until the stop."""
    if not frames:
        return []
    t0 = float(frames[0]["t"])
    total = max(1, int(round((float(stopped_at) - t0) * fps)))
    out, j = [], 0
    for k in range(total):
        at = t0 + k / fps
        while j + 1 < len(frames) and float(frames[j + 1]["t"]) <= at + 1e-9:
            j += 1
        out.append(frames[j]["file"])
    return out


def assemble(frames_dir, out_mp4, fps=FPS):
    """The screencast's frames -> an H.264 mp4 at `fps`, 1080x1920 (scaled to
    fit and padded when a page sent another size), TV range. The constant-rate
    sequence is laid out as numbered links to the frames and read as an image
    sequence, so the duration is exact. -> (ok, detail)."""
    frames_dir = Path(frames_dir)
    try:
        meta = json.loads((frames_dir / "frames.json").read_text())
    except (OSError, ValueError) as e:
        return False, f"no frames.json ({e})"
    frames = meta.get("frames") or []
    if not frames:
        return False, "no frames"
    seq_dir = frames_dir / "seq"
    seq_dir.mkdir(exist_ok=True)
    for k, name in enumerate(frame_sequence(frames, meta.get("stopped_at") or frames[-1]["t"],
                                            fps)):
        (seq_dir / f"{k:06d}.jpg").symlink_to(frames_dir / name)
    vf = (f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease"
          f":in_range=pc:out_range=tv,"
          f"pad={FRAME_WIDTH}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", str(seq_dir / "%06d.jpg"), "-vf", vf, "-an", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-color_range", "tv",
           "-movflags", "+faststart", str(out_mp4)]
    try:
        out = runlog.run_child(cmd, tool="ffmpeg", capture_output=True, text=True,
                               timeout=ASSEMBLY_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False, "ffmpeg did not return"
    except OSError as e:
        return False, str(e)
    if out.returncode != 0 or not Path(out_mp4).is_file():
        return False, (out.stderr or "").strip()[-400:] or f"exit {out.returncode}"
    return True, None


_fetch_robots_default = fetch_robots
_assemble_default = assemble


# ------------------------------------------------------------ the policy
class OwnCapture:
    """One instance per run. `origin_doc` is the channel's footage-origin.json
    (`channel_data.footage_origin(channel)`). Every outside call is
    injectable: fetch_robots(robots_url) -> (status, ctype, text);
    fetch_card(space) -> dict | None; record(url, frames_dir, steps,
    max_seconds) -> the mjs dict; assemble(frames_dir, out_mp4) -> (ok, detail);
    clock / sleep / now for the rate and the stamp."""

    def __init__(self, origin_doc, channel=None, user_agent=PROOF_USER_AGENT,
                 fetch_robots=None, fetch_card=None, record=None, assemble=None,
                 licence_rule=None, robots_rule=None, clock=time.monotonic,
                 sleep=time.sleep, now=None, min_gap=PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST,
                 chrome=None):
        self.doc = origin_doc if isinstance(origin_doc, dict) else {}
        self.channel = channel
        self.user_agent = user_agent
        self._fetch_robots = fetch_robots or (lambda u: _fetch_robots_default(u, user_agent))
        self._fetch_card = fetch_card or (lambda s: fetch_space_card(s, user_agent))
        self._record = record or (lambda url, d, steps, secs: record_with_chrome(
            url, d, steps, secs, user_agent=user_agent, chrome=chrome))
        self._assemble = assemble or _assemble_default
        self.fl = licence_rule if licence_rule is not None else root_module("footage_licence")
        self.sp = robots_rule if robots_rule is not None else root_module("source_policy")
        self.clock, self.sleep = clock, sleep
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.min_gap = min_gap
        self.last_request_at = {}

    # -- the channel's rule ------------------------------------------------
    def host_entry(self, netloc):
        """The `capture_hosts` entry the host falls under (longest match), or None."""
        best = None
        for h in self.doc.get("capture_hosts") or []:
            if isinstance(h, dict) and self.fl._host_matches(h.get("host"), netloc):
                if best is None or len(h["host"]) > len(best["host"]):
                    best = h
        return best

    def check_url(self, url):
        """-> (None, entry) when the channel's rule lets `url` be recorded,
        else (refusal code, reason)."""
        if self.fl is None:
            return REFUSE_NO_RULE, "the root's shared/footage_licence.py cannot be found"
        parts = urlsplit(str(url or ""))
        if parts.scheme != "https" or not parts.netloc:
            return REFUSE_NOT_HTTPS, f"{url!r} is not an https page"
        if not self.doc.get("capture_hosts"):
            return REFUSE_NO_RULE, (f"the channel's footage-origin.json has no capture_hosts - "
                                    f"it records nowhere")
        entry = self.host_entry(parts.netloc)
        # No sign-in, whatever the entry's `use` says: signed-in capture is
        # CF-0688 (Q26), never this recorder.
        if entry is not None and entry.get("sign_in") is not False:
            return REFUSE_SIGN_IN, f"{entry['host']} needs a sign-in - out until the user decides (Q26)"
        ok, why = self.fl.capture_allowed(url, self.doc)
        if not ok:
            code = REFUSE_HOST_NOT_LISTED if entry is None else REFUSE_HOST_CLOSED
            return code, str(why)
        return None, why

    def check_robots(self, url):
        """The exact host's robots.txt for the exact path, read now -> (None
        | refusal code, the read)."""
        if self.sp is None:
            return REFUSE_NO_RULE, {"note": "the root's shared/source_policy.py cannot be found"}
        parts = urlsplit(url)
        robots_url = f"https://{parts.netloc}/robots.txt"
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        status, ctype, text = self._fetch_robots(robots_url)
        row = self.sp.check_url(robots_url, path, lambda _u: (status, ctype, text))
        ua_allowed = any_allowed = None
        if status == 200 and row.get("verdict") != "unknown":
            rp = urllib.robotparser.RobotFileParser()
            rp.parse((text or "").splitlines())
            ua_allowed = rp.can_fetch(self.user_agent, url)
            any_allowed = rp.can_fetch("*", url)
        elif row.get("verdict") == "allowed":
            ua_allowed = any_allowed = True
        read = {**row, "factory_ua": self.user_agent, "factory_ua_allowed": ua_allowed,
                "any_agent_allowed": any_allowed,
                "read_at": self.now().strftime("%Y-%m-%dT%H:%M:%SZ")}
        if row.get("verdict") == "unknown":
            return REFUSE_ROBOTS_UNREAD, read
        if row.get("verdict") != "allowed" or ua_allowed is False or any_allowed is False:
            return REFUSE_ROBOTS, read
        return None, read

    def check_space(self, url, entry, space):
        """A Space (`hf.space`) is recorded only when its card names a
        licence -> (None | refusal code, the record or None)."""
        if (entry or {}).get("host") != SPACE_HOST:
            return None, None
        label = (host_of(url).split(".")[0] if host_of(url) else "")
        if not space or "/" not in str(space):
            return REFUSE_SPACE_NOT_NAMED, {
                "note": f"{host_of(url)} is a Space's app - name it as --space <owner>/<space> "
                        f"so its card can be read (the host does not split owner from name)"}
        if space_subdomain(space) != label:
            return REFUSE_SPACE_NOT_NAMED, {
                "id": space, "note": f"Space {space} is served on {space_subdomain(space)}."
                                     f"{SPACE_HOST}, not on {host_of(url)}"}
        card = self._fetch_card(space)
        rec = {"id": space, "api_url": SPACE_API.format(space=space),
               "read_at": self.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "licence": None}
        if not isinstance(card, dict):
            return REFUSE_SPACE_CARD_UNREAD, {**rec, "note": "the card could not be read - "
                                                             "unread is not permission"}
        rec.update(sdk=card.get("sdk"), author=card.get("author"),
                   private=card.get("private"), disabled=card.get("disabled"))
        if card.get("private") or card.get("disabled"):
            return REFUSE_SPACE_NOT_PUBLIC, {**rec, "note": "a private or disabled Space is "
                                                            "not a public page"}
        rec["licence"] = space_licence(card)
        if not rec["licence"]:
            return REFUSE_SPACE_NO_LICENCE, {**rec, "note": "the card names no licence - a "
                                                            "Space with none is not recorded"}
        return None, rec

    # -- the one public call ------------------------------------------------
    def capture(self, url, out_dir, steps=None, space=None, max_seconds=CAPTURE_DEFAULT_SECONDS,
                capture_id_=None):
        checks = {}
        code, entry = self.check_url(url)
        checks["capture_allowed"] = ({"allowed": True, "host": entry.get("host")} if code is None
                                     else {"allowed": False, "code": code, "reason": entry})
        if code:
            return CaptureResult(False, code, detail=str(entry), checks=checks)
        errs = step_errors(steps)
        if errs:
            return CaptureResult(False, REFUSE_BAD_STEPS, detail="; ".join(errs), checks=checks)
        code, robots = self.check_robots(url)
        checks["robots"] = robots
        if code:
            return CaptureResult(False, code, detail=f"robots.txt of {host_of(url)}: "
                                 f"{robots.get('verdict') or robots.get('note')}", checks=checks)
        code, space_rec = self.check_space(url, entry, space)
        checks["space"] = space_rec
        if code:
            return CaptureResult(False, code, detail=(space_rec or {}).get("note"), checks=checks)

        secs = max(1.0, min(float(max_seconds or CAPTURE_DEFAULT_SECONDS), CAPTURE_MAX_SECONDS))
        host = host_of(url)
        last = self.last_request_at.get(host)
        if last is not None:
            wait = self.min_gap - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self.last_request_at[host] = self.clock()

        started = self.now()
        cid = capture_id_ or capture_id(url, space, started)
        file_id = _clip_names.own_capture_file_id(cid)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        mp4 = out_dir / f"{file_id}.mp4"
        with tempfile.TemporaryDirectory(prefix="own-capture-frames-") as frames_dir:
            res = self._record(url, frames_dir, steps or [], secs) or {}
            if not res.get("ok"):
                return CaptureResult(False, str(res.get("reason") or "browser_error"),
                                     detail=res.get("detail"), requested=True, checks=checks)
            final = res.get("final_url") or url
            fcode, fwhy = self.check_url(final)
            if fcode:
                return CaptureResult(False, REFUSE_REDIRECT,
                                     detail=f"the page ended on {final}: {fwhy}",
                                     requested=True, checks=checks)
            ok, why = self._assemble(frames_dir, mp4)
            if not ok:
                return CaptureResult(False, FAIL_ASSEMBLY, detail=why, requested=True,
                                     checks=checks)
        record = {
            "schema": SCHEMA,
            "id": f"{_clip_names.OWN_CAPTURE_NAME}{file_id[len(_clip_names.OWN_CAPTURE_PREFIX):]}",
            "file_id": file_id,
            "file": mp4.name,
            "origin": OWN_CAPTURE,
            "licence": OWN_CAPTURE,
            "found_by": dict(FOUND_BY),
            "url": url,
            "final_url": final,
            "host": host,
            "capture_host": entry.get("host"),
            "host_entry": {"host": entry.get("host"), "use": entry.get("use"),
                           "sign_in": entry.get("sign_in"),
                           "ai_policy": {k: (entry.get("ai_policy") or {}).get(k)
                                         for k in ("verdict", "checked_on", "terms_url",
                                                   "terms_verdict")}},
            "capture_allowed": checks["capture_allowed"],
            "robots": robots,
            "space": space_rec,
            "steps": list(steps or []),
            "steps_done": res.get("steps_done") or [],
            "duration_s": res.get("duration_s"),
            "max_seconds": secs,
            "capped": bool(res.get("capped")),
            "fps": FPS,
            "width": FRAME_WIDTH,
            "height": FRAME_HEIGHT,
            "frames": res.get("frames"),
            "captured_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "user_agent": self.user_agent,
            "channel": self.channel,
            "recorder": "capture_tool.py (CF-0567)",
        }
        side = sidecar_path(mp4)
        side.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return CaptureResult(True, None, file=str(mp4.resolve()), sidecar=str(side.resolve()),
                             record=record, requested=True, checks=checks)


def load_origin_doc(channel, root=None):
    from _channel_data import channel_data
    return channel_data.footage_origin(channel, root)


def main(argv=None):
    ap = argparse.ArgumentParser(description="record a public page as the factory's own "
                                             "footage, within the channel's capture rule")
    ap.add_argument("url")
    ap.add_argument("out_dir")
    ap.add_argument("--channel", required=True, help="channel id (its footage-origin.json)")
    ap.add_argument("--steps", help="a JSON list of steps (wait/scroll/click/type/press/wait_for)")
    ap.add_argument("--space", help="<owner>/<space> of a Hugging Face Space recorded on hf.space")
    ap.add_argument("--max-seconds", type=float, default=CAPTURE_DEFAULT_SECONDS)
    ap.add_argument("--id", dest="capture_id", help="the capture id (default: slug + UTC stamp)")
    ap.add_argument("--root", help="the factory root whose channels/ is read")
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args(argv)
    try:
        doc = load_origin_doc(a.channel, a.root)
    except Exception as e:  # noqa: BLE001 - no document, no recording
        print(json.dumps({"ok": False, "reason": REFUSE_NO_RULE, "detail": str(e)}, indent=2))
        return 1
    steps = None
    if a.steps:
        try:
            steps = json.loads(Path(a.steps).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(json.dumps({"ok": False, "reason": REFUSE_BAD_STEPS, "detail": str(e)}, indent=2))
            return 1
    cap = OwnCapture(doc, channel=a.channel, chrome=a.chrome)
    res = cap.capture(a.url, a.out_dir, steps=steps, space=a.space,
                      max_seconds=a.max_seconds, capture_id_=a.capture_id)
    print(json.dumps(res.__dict__, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


@video_script("video-editor", "capture", name="capture_tool.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
