#!/usr/bin/env python3
"""CF-0567: the own-capture recorder (scripts/capture_tool.py + .mjs) - every
refusal decided before a page is opened, the sidecar's shape, the cap, the
frame arithmetic, and one recording of a local file:// page when Chrome is
installed.

Stand-ins only: a hand-made footage-origin document in the channel's shape
(hosts `tools.example`, `closed.example`, `login.example`, `hf.space`),
injected robots.txt / Space card / browser / assembler. No network, no real
channel data (the CLI reads a temp factory root), no real site recorded.
"""
import _isolated_runlog  # noqa: F401 - CF-0482: run accounting never lands in a real batch
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _clip_names  # noqa: E402
import capture_page  # noqa: E402
import capture_tool as ct  # noqa: E402


def _policy(verdict="allowed", terms="allowed"):
    return {"verdict": verdict, "checked_on": "2026-10-11", "checks": [
        {"robots_url": "https://x/robots.txt", "verdict": verdict}],
        "terms_url": "https://x/terms", "terms_verdict": terms, "terms_note": "read"}


DOC = {"capture_hosts": [
    {"host": "tools.example", "what": "a public demo", "sign_in": False, "use": "capture",
     "ai_policy": _policy()},
    {"host": "closed.example", "what": "a vendor page", "sign_in": False, "use": "closed",
     "why_closed": "terms forbid automated access", "ai_policy": _policy(terms="forbidden")},
    {"host": "login.example", "what": "a playground behind a login", "sign_in": True,
     "use": "capture", "ai_policy": _policy()},
    {"host": "hf.space", "what": "a Space's own app", "sign_in": False, "use": "capture",
     "ai_policy": _policy()},
]}
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
OPEN = (200, "text/plain", "User-agent: *\nAllow: /\n")
CARD = {"id": "acme/fox-demo", "author": "acme", "sdk": "gradio", "private": False,
        "cardData": {"license": "apache-2.0"}, "tags": ["gradio"]}


class Calls:
    def __init__(self, robots=OPEN, card=CARD, rec=None):
        self.robots, self.card, self.rec = robots, card, rec
        self.robots_urls, self.cards, self.records, self.assembled = [], [], [], []

    def fetch_robots(self, url):
        self.robots_urls.append(url)
        return self.robots

    def fetch_card(self, space):
        self.cards.append(space)
        return self.card

    def record(self, url, frames_dir, steps, secs):
        self.records.append({"url": url, "steps": steps, "secs": secs})
        return self.rec or {"ok": True, "reason": None, "status": 200, "final_url": url,
                            "frames": 40, "duration_s": 4.2, "capped": False,
                            "steps_done": [{"index": 0, "do": "wait", "ok": True}]}

    def assemble(self, frames_dir, out_mp4):
        self.assembled.append(str(out_mp4))
        Path(out_mp4).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return True, None


def _tool(calls, doc=DOC):
    return ct.OwnCapture(doc, channel="techstand", fetch_robots=calls.fetch_robots,
                         fetch_card=calls.fetch_card, record=calls.record,
                         assemble=calls.assemble, sleep=lambda s: None, now=lambda: NOW)


def _refused(url, code, calls=None, **kw):
    calls = calls or Calls()
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture(url, tmp, **kw)
        assert not res.ok and res.reason == code, (url, res.reason, res.detail)
        assert not res.requested and not calls.records, "a refused page was opened"
        assert not list(Path(tmp).iterdir()), "a refusal left a file behind"
    return res, calls


def test_the_root_rule_is_found():
    assert ct.root_module("footage_licence") is not None
    assert ct.root_module("source_policy") is not None


def test_unlisted_host_is_refused_before_anything_is_read():
    res, calls = _refused("https://elsewhere.example/app", ct.REFUSE_HOST_NOT_LISTED)
    assert not calls.robots_urls, "robots.txt read for a host the channel never listed"
    # a dot boundary: notools.example is not tools.example
    _refused("https://notools.example/", ct.REFUSE_HOST_NOT_LISTED)


def test_http_and_file_pages_are_refused():
    _refused("http://tools.example/app", ct.REFUSE_NOT_HTTPS)
    _refused("file:///tmp/page.html", ct.REFUSE_NOT_HTTPS)


def test_closed_host_is_refused():
    res, _ = _refused("https://www.closed.example/x", ct.REFUSE_HOST_CLOSED)
    assert "closed" in res.detail


def test_sign_in_host_is_refused_even_when_marked_capture():
    _refused("https://app.login.example/play", ct.REFUSE_SIGN_IN)
    doc = {"capture_hosts": [dict(DOC["capture_hosts"][0], sign_in=True)]}
    calls = Calls()
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls, doc).capture("https://tools.example/", tmp)
    assert res.reason == ct.REFUSE_SIGN_IN and not calls.records


def test_robots_disallow_refuses():
    for text in ("User-agent: *\nDisallow: /\n",
                 "User-agent: ClaudeBot\nDisallow: /app\n",
                 f"User-agent: {capture_page.PROOF_USER_AGENT.split('/')[0]}\nDisallow: /\n"):
        res, calls = _refused("https://tools.example/app", ct.REFUSE_ROBOTS,
                              Calls(robots=(200, "text/plain", text)))
        assert calls.robots_urls == ["https://tools.example/robots.txt"], calls.robots_urls
        assert res.checks["robots"]["robots_url"] == "https://tools.example/robots.txt"
    # the exact host is read, not the listed parent
    res, calls = _refused("https://deep.tools.example/app", ct.REFUSE_ROBOTS,
                          Calls(robots=(200, "text/plain", "User-agent: *\nDisallow: /\n")))
    assert calls.robots_urls == ["https://deep.tools.example/robots.txt"]


def test_unreadable_robots_is_not_permission():
    _refused("https://tools.example/app", ct.REFUSE_ROBOTS_UNREAD,
             Calls(robots=(500, "text/html", "")))
    _refused("https://tools.example/app", ct.REFUSE_ROBOTS_UNREAD, Calls(robots=(None, "", "")))


def test_no_robots_file_is_open():
    calls = Calls(robots=(404, "text/html", ""))
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture("https://tools.example/app", tmp)
    assert res.ok, res.detail
    assert res.record["robots"]["verdict"] == "allowed"


def test_space_needs_its_name_and_a_licence_on_its_card():
    url = "https://acme-fox-demo.hf.space/"
    _refused(url, ct.REFUSE_SPACE_NOT_NAMED)
    _refused(url, ct.REFUSE_SPACE_NOT_NAMED, space="other/thing")
    _refused(url, ct.REFUSE_SPACE_CARD_UNREAD, Calls(card=None), space="acme/fox-demo")
    _refused(url, ct.REFUSE_SPACE_NOT_PUBLIC, Calls(card={**CARD, "private": True}),
             space="acme/fox-demo")
    res, calls = _refused(url, ct.REFUSE_SPACE_NO_LICENCE,
                          Calls(card={**CARD, "cardData": {}, "tags": ["gradio"]}),
                          space="acme/fox-demo")
    assert calls.cards == ["acme/fox-demo"]
    assert res.checks["space"]["api_url"] == "https://huggingface.co/api/spaces/acme/fox-demo"


def test_space_licence_reading():
    assert ct.space_licence(CARD) == "apache-2.0"
    assert ct.space_licence({"tags": ["license:mit", "gradio"]}) == "mit"
    assert ct.space_licence({"cardData": {"license": ["mit", "cc-by-4.0"]}}) == "mit, cc-by-4.0"
    assert ct.space_licence({"cardData": {"license": ""}, "tags": []}) is None
    assert ct.space_subdomain("Black-Forest-Labs/FLUX.1-dev") == "black-forest-labs-flux-1-dev"


def test_bad_steps_are_refused_before_the_page():
    for steps in ([{"do": "login"}], [{"do": "type", "selector": "#password", "text": "x"}],
                  [{"do": "type", "selector": "#q"}], [{"do": "press", "key": "Escape"}],
                  [{"do": "wait", "seconds": 999}], [{"do": "scroll"}], {"do": "wait"},
                  [{"do": "wait", "seconds": 1}] * (ct.MAX_STEPS + 1)):
        _refused("https://tools.example/app", ct.REFUSE_BAD_STEPS, steps=steps)
    assert ct.step_errors([{"do": "wait", "seconds": 1}, {"do": "scroll", "by": 400},
                           {"do": "type", "selector": "textarea", "text": "a red fox"},
                           {"do": "click", "selector": "#run"}, {"do": "press", "key": "Enter"},
                           {"do": "wait_for", "selector": ".out", "seconds": 10}]) == []


def test_a_recording_and_its_sidecar():
    calls = Calls()
    steps = [{"do": "type", "selector": "textarea", "text": "a red fox"},
             {"do": "click", "selector": "#run"}]
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture("https://acme-fox-demo.hf.space/?tab=1", tmp, steps=steps,
                                   space="acme/fox-demo", max_seconds=12)
        assert res.ok, (res.reason, res.detail)
        mp4 = Path(res.file)
        assert mp4.name == "own_capture-acme-fox-demo-20261011t120000z.mp4", mp4.name
        assert _clip_names.is_own_capture(mp4.stem) and _clip_names.is_source_id(mp4.stem)
        side = json.loads(Path(res.sidecar).read_text())
        assert Path(res.sidecar).name == mp4.stem + ct.SIDECAR_SUFFIX
        assert set(ct.SIDECAR_FIELDS) <= set(side), set(ct.SIDECAR_FIELDS) - set(side)
        assert side["origin"] == "own_capture" and side["licence"] == "own_capture"
        assert side["found_by"]["how"] == "screen_capture"
        assert side["id"] == "own_capture:acme-fox-demo-20261011t120000z"
        assert side["file_id"] == mp4.stem and side["file"] == mp4.name
        assert side["url"] == "https://acme-fox-demo.hf.space/?tab=1"
        assert side["host"] == "acme-fox-demo.hf.space" and side["capture_host"] == "hf.space"
        assert side["capture_allowed"] == {"allowed": True, "host": "hf.space"}
        assert side["robots"]["verdict"] == "allowed" and side["robots"]["factory_ua_allowed"]
        assert side["robots"]["robots_url"] == "https://acme-fox-demo.hf.space/robots.txt"
        assert side["space"]["licence"] == "apache-2.0" and side["space"]["id"] == "acme/fox-demo"
        assert side["steps"] == steps and side["duration_s"] == 4.2
        assert side["captured_at"] == "2026-10-11T12:00:00Z" and side["channel"] == "techstand"
        assert side["host_entry"]["sign_in"] is False and side["host_entry"]["use"] == "capture"
        assert (side["width"], side["height"]) == (1080, 1920)
        assert ct.read_sidecar(mp4)["id"] == side["id"]
        assert calls.records[0]["secs"] == 12.0


def test_the_cap_holds_whatever_is_asked():
    calls = Calls()
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture("https://tools.example/app", tmp, max_seconds=600)
    assert res.ok and calls.records[0]["secs"] == ct.CAPTURE_MAX_SECONDS
    assert res.record["max_seconds"] == ct.CAPTURE_MAX_SECONDS


def test_a_redirect_off_the_host_discards_the_take():
    calls = Calls(rec={"ok": True, "final_url": "https://closed.example/landing", "frames": 3})
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture("https://tools.example/app", tmp)
        assert res.reason == ct.REFUSE_REDIRECT and res.requested
        assert not calls.assembled and not list(Path(tmp).iterdir())


def test_a_failed_browser_is_a_failure_not_a_file():
    calls = Calls(rec={"ok": False, "reason": "step_failed", "detail": "no element #run"})
    with tempfile.TemporaryDirectory() as tmp:
        res = _tool(calls).capture("https://tools.example/app", tmp)
        assert not res.ok and res.reason == "step_failed" and not list(Path(tmp).iterdir())


def test_frame_sequence_holds_each_frame_until_the_next():
    frames = [{"file": "a", "t": 10.0}, {"file": "b", "t": 10.5}, {"file": "c", "t": 11.0}]
    seq = ct.frame_sequence(frames, 12.0, fps=4)
    assert seq == ["a", "a", "b", "b", "c", "c", "c", "c"], seq
    assert ct.frame_sequence([], 1.0) == []


def test_cli_refuses_an_unlisted_host_from_the_channels_own_document():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "channels" / "techstand").mkdir(parents=True)
        (root / "channels" / "techstand.json").write_text(json.dumps({"channel_id": "techstand"}))
        (root / "channels" / "techstand" / "footage-origin.json").write_text(json.dumps(DOC))
        out = root / "out"
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ct.main(["https://elsewhere.example/", str(out), "--channel", "techstand",
                          "--root", str(root)])
        got = json.loads(buf.getvalue())
        assert rc == 1 and got["reason"] == ct.REFUSE_HOST_NOT_LISTED, got
        assert not out.exists()


def test_records_a_local_page_when_chrome_is_installed():
    """The browser half end to end on a file:// page of this test's own (the
    policy half is bypassed on purpose - it refuses every non-https page)."""
    chrome = capture_page.find_chrome()
    if not chrome or not shutil.which("ffmpeg") or not shutil.which("node"):
        print("  (skipped: no chrome-headless-shell / ffmpeg / node)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text("<!doctype html><html><body style='font:20px sans-serif'>"
                        "<textarea id='q'></textarea><button id='run' onclick=\""
                        "document.getElementById('out').textContent='done: '+"
                        "document.getElementById('q').value\">Run</button>"
                        "<div id='out'>-</div></body></html>")
        frames = Path(tmp) / "frames"
        frames.mkdir()
        steps = [{"do": "type", "selector": "#q", "text": "fox", "delay_ms": 30},
                 {"do": "click", "selector": "#run"}, {"do": "wait", "seconds": 0.5}]
        res = ct.record_with_chrome(page.as_uri(), frames, steps, 8, chrome=chrome, timeout=20)
        assert res.get("ok"), res
        assert [s["ok"] for s in res["steps_done"]] == [True, True, True], res["steps_done"]
        mp4 = Path(tmp) / "own_capture-local-test.mp4"
        ok, why = ct.assemble(frames, mp4)
        assert ok, why
        probe = capture_page.subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, timeout=30)
        assert probe.stdout.strip() == "1080,1920", probe.stdout


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
