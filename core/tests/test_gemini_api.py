#!/usr/bin/env python3
"""CF-0690: the factory's Gemini API client (`shared/gemini/gemini_api.py`)
on canned answers - never the network: every transport here is a Recorder of
answers written in this file, and the key is a made-up string in a temp
`.env` or a stand-in environment (the real `.env` is never read).

* the key goes only in the `x-goog-api-key` header - never the URL, a log
  line, an exception or the protocol;
* no key -> `skipped`; the environment wins over `<root>/.env`;
* 429 with Retry-After / RetryInfo is retried, then `rate_limited`;
* SAFETY, RECITATION, a blocked prompt, citation metadata, an empty answer
  and a refusal phrase are `refused`; a good answer is `ok`, verbatim.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="gemini-test-"))
KEY = "AIzaTESTkey0000ThisIsNotARealKey12345678"


def _load():
    path = HERE.parent / "shared" / "gemini" / "gemini_api.py"
    spec = importlib.util.spec_from_file_location("gemini_api_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ga = _load()


class Recorder:
    """A transport of canned answers that keeps what it was asked."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, headers, body, timeout=None):
        self.calls.append((url, dict(headers), json.loads(body.decode("utf-8")), timeout))
        status, payload, hdrs = self.answers.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return ga.HttpResponse(status, text, hdrs)


def answer(text="A rainbow forms when sunlight is refracted. It splits into colours.",
           finish="STOP", **extra):
    cand = {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish,
            "index": 0}
    cand.update(extra.pop("candidate", {}))
    out = {"candidates": [cand], "modelVersion": "gemini-2.5-flash",
           "responseId": "resp-1", "usageMetadata": {"promptTokenCount": 9,
                                                     "candidatesTokenCount": 20}}
    out.update(extra)
    return out


def root_with_env(text):
    d = Path(tempfile.mkdtemp(dir=TMP))
    if text is not None:
        (d / ".env").write_text(text, encoding="utf-8")
    return d


def client(answers, env=None, root=None, **kw):
    rec = Recorder(answers)
    lines = []
    sleeps = []
    c = ga.GeminiClient(transport=rec, environ={"GEMINI_API_KEY": KEY} if env is None else env,
                        root=root if root is not None else root_with_env(None),
                        sleep=sleeps.append, clock=lambda: 0.0, wall=lambda: 1760270400.0,
                        log=lines.append, **kw)
    return c, rec, lines, sleeps


def no_key_anywhere(*things):
    for t in things:
        assert KEY not in json.dumps(t, default=str), t


# ------------------------------------------------------------------ the key
def test_the_key_goes_only_in_the_header():
    c, rec, lines, _ = client([(200, answer(), {})])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    url, headers, body, timeout = rec.calls[0]
    assert headers["x-goog-api-key"] == KEY
    assert url == ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "gemini-2.5-flash:generateContent")
    assert KEY not in url and "key=" not in url
    assert body == {"contents": [{"role": "user", "parts": [
        {"text": "Explain how a rainbow forms in two sentences."}]}]}
    assert timeout == ga.DEFAULT_TIMEOUT
    assert p["endpoint"] == url and p["key_source"] == "environment"
    no_key_anywhere(p, lines)
    assert any("key from environment" in ln for ln in lines)


def test_no_key_is_skipped_without_a_request():
    c, rec, lines, _ = client([], env={})
    p = c.ask("gemini-2.5-flash", "Write a four-line poem about a robot learning to paint.")
    assert p["status"] == "skipped" and p["skip_reason"] == "no GEMINI_API_KEY (environment or .env)"
    assert p["skip_reason"] == ga.NO_KEY_REASON and p["key_source"] is None
    assert rec.calls == [] and p["answer"] is None
    assert set(p) == set(ga.PROTOCOL_KEYS)


def test_env_wins_over_dotenv_and_dotenv_is_read():
    root = root_with_env(f"# a comment\nOTHER=1\nGEMINI_API_KEY=\"{KEY}\"\n")
    assert ga.key_source(root=root, environ={}) == ".env"
    assert ga.api_key(root=root, environ={}) == KEY
    assert ga.key_source(root=root, environ={"GEMINI_API_KEY": "envkey"}) == "environment"
    assert ga.api_key(root=root, environ={"GEMINI_API_KEY": "envkey"}) == "envkey"
    assert ga.key_source(root=root_with_env("GEMINI_API_KEY=\n"), environ={}) is None
    c, rec, lines, _ = client([(200, answer(), {})], env={}, root=root)
    p = c.ask("gemini-2.5-flash", "Give three tips for packing a carry-on bag.")
    assert rec.calls[0][1]["x-goog-api-key"] == KEY and p["key_source"] == ".env"
    no_key_anywhere(p, lines)


def test_factory_root_from_the_environment():
    root = root_with_env(f"GEMINI_API_KEY={KEY}\n")
    assert ga.key_source(environ={"FACTORY_ROOT": str(root)}) == ".env"
    assert ga.factory_root(environ={"FACTORY_ROOT": str(root)}) == root


# --------------------------------------------------------------- the answer
def test_a_good_answer_is_ok_and_verbatim():
    text = "  Sunlight enters a raindrop,\nbends and splits.  "
    c, _, _, _ = client([(200, answer(text), {})])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.",
              generation_config={"temperature": 0.7})
    assert p["status"] == "ok" and p["skip_reason"] is None
    assert p["answer"] == text, "verbatim - nothing stripped, nothing rewritten"
    assert p["model_requested"] == "gemini-2.5-flash" and p["model_version"] == "gemini-2.5-flash"
    assert p["finish_reason"] == "STOP" and p["citation"] is False
    assert p["usage"]["promptTokenCount"] == 9 and p["response_id"] == "resp-1"
    assert p["generation_config"] == {"temperature": 0.7}
    assert p["provider"] == "gemini_api"
    assert p["requested_at"] == p["answered_at"] == "2025-10-12T12:00:00Z"
    assert set(p) == set(ga.PROTOCOL_KEYS)


def test_generation_config_is_sent():
    c, rec, _, _ = client([(200, answer(), {})])
    c.ask("gemini-2.5-flash-lite", "Explain how a rainbow forms in two sentences.",
          generation_config={"maxOutputTokens": 256})
    assert rec.calls[0][2]["generationConfig"] == {"maxOutputTokens": 256}


def test_parts_are_joined_and_thoughts_left_out():
    resp = answer()
    resp["candidates"][0]["content"]["parts"] = [{"text": "secret plan", "thought": True},
                                                 {"text": "Line one. "}, {"text": "Line two."}]
    c, _, _, _ = client([(200, resp, {})])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    assert p["answer"] == "Line one. Line two." and p["status"] == "ok"


def test_what_is_refused():
    cases = [
        (answer(finish="SAFETY"), "finish_reason SAFETY"),
        (answer(finish="RECITATION"), "finish_reason RECITATION"),
        (answer(finish="MAX_TOKENS"), "finish_reason MAX_TOKENS"),
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "prompt blocked: SAFETY"),
        ({"candidates": []}, "no candidate"),
        (answer(""), "empty answer"),
        (answer(candidate={"citationMetadata": {"citationSources": [
            {"startIndex": 0, "endIndex": 20, "uri": "https://example.org"}]}}), "citation"),
        (answer("I can't help with that request."), "refusal"),
        (answer("I’m unable to write that."), "refusal"),
        (answer("Sure. As an AI, I do not paint."), "refusal"),
    ]
    for resp, why in cases:
        c, _, _, _ = client([(200, resp, {})])
        p = c.ask("gemini-2.5-flash", "Write a four-line poem about a robot learning to paint.")
        assert p["status"] == "refused" and why in p["skip_reason"], (why, p)
    c, _, _, _ = client([(200, answer(candidate={"citationMetadata": {"citationSources": [
        {"uri": "https://example.org"}]}}), {})])
    assert c.ask("gemini-2.5-flash", "Explain how a rainbow forms.")["citation"] is True
    # a refusal phrase in the middle of a poem is not a refusal
    c, _, _, _ = client([(200, answer("The robot sighs: I can't hold the brush,\n"
                                      "yet paint runs bright."), {})])
    assert c.ask("gemini-2.5-flash", "Write a poem.")["status"] == "ok"
    assert ga.refusal_phrase("I cannot do that") == "i cannot"
    assert ga.refusal_phrase("Rainbows form from light.") is None


# ---------------------------------------------------------------- the retries
def test_429_with_retry_after_is_retried_then_rate_limited():
    busy = (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, {"Retry-After": "7"})
    c, rec, lines, sleeps = client([busy] * ga.MAX_RETRIES)
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    assert len(rec.calls) == ga.MAX_RETRIES
    assert sleeps == [7.0] * (ga.MAX_RETRIES - 1)
    assert p["status"] == "skipped" and p["skip_reason"] == "rate_limited"
    assert p["answer"] is None
    no_key_anywhere(p, lines)


def test_retry_info_then_success():
    busy = (429, {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}}, {})
    c, rec, _, sleeps = client([busy, (503, "{}", {}), (200, answer(), {})])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    assert p["status"] == "ok" and len(rec.calls) == 3
    assert sleeps[0] == 12.0 and sleeps[1] == ga.RETRY_BACKOFF_SECONDS * 2


def test_a_long_wait_is_not_waited_out():
    busy = (429, "{}", {"Retry-After": str(ga.MAX_RETRY_WAIT_SECONDS + 3600)})
    c, rec, _, sleeps = client([busy, busy, busy])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    assert len(rec.calls) == 1 and sleeps == [] and p["skip_reason"] == "rate_limited"


def test_5xx_exhausted_is_unavailable():
    c, _, _, _ = client([(503, "{}", {})] * ga.MAX_RETRIES)
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    assert p["status"] == "skipped" and p["skip_reason"] == "unavailable: HTTP 503"


def test_min_interval_between_calls():
    now = [0.0]
    rec = Recorder([(200, answer(), {}), (200, answer(), {})])
    sleeps = []
    c = ga.GeminiClient(transport=rec, environ={"GEMINI_API_KEY": KEY},
                        root=root_with_env(None), min_interval=5, sleep=sleeps.append,
                        clock=lambda: now[0])
    c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    now[0] = 2.0
    c.ask("gemini-2.5-flash", "Give three tips for packing a carry-on bag.")
    assert sleeps == [3.0] and c.request_count == 2


# ---------------------------------------------------------------- the errors
def test_errors_never_carry_the_key():
    leaky = (400, {"error": {"code": 400, "message": f"API key {KEY} not valid. key={KEY}"}}, {})
    c, _, lines, _ = client([leaky])
    try:
        c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    except ga.GeminiError as e:
        assert KEY not in str(e) and "HTTP 400" in str(e), str(e)
    else:
        raise AssertionError("a 400 must raise GeminiError")
    no_key_anywhere(lines)

    def boom(url, headers, body, timeout=None):
        raise OSError(f"connection reset while sending {headers['x-goog-api-key']}")
    c = ga.GeminiClient(transport=boom, environ={"GEMINI_API_KEY": KEY}, root=root_with_env(None),
                        sleep=lambda s: None)
    try:
        c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    except ga.GeminiError as e:
        assert KEY not in str(e) and KEY not in repr(e.__cause__), str(e)
    else:
        raise AssertionError("a transport failure must raise GeminiError")


def test_an_echoed_key_is_scrubbed_from_the_protocol():
    c, _, lines, _ = client([(200, answer(f"Your key is {KEY}."), {})])
    p = c.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.")
    no_key_anywhere(p, lines)


def test_bad_input():
    c, _, _, _ = client([])
    for model, prompt in (("gemini-2.5-flash", ""), ("../x?key=1", "hi"), (None, "hi")):
        try:
            c.ask(model, prompt)
        except ValueError:
            pass
        else:
            raise AssertionError((model, prompt))


def test_module_ask_and_names():
    rec = Recorder([(200, answer(), {})])
    p = ga.ask("gemini-2.5-flash", "Explain how a rainbow forms in two sentences.",
               transport=rec, environ={"GEMINI_API_KEY": KEY}, root=root_with_env(None))
    assert p["status"] == "ok"
    assert ga.MODULE_NAME == "factory_gemini_api" and ga.TERMS_URL.startswith("https://")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    try:
        for t in tests:
            try:
                t()
                print(f"ok   {t.__name__}")
            except Exception:
                failed += 1
                print(f"FAIL {t.__name__}")
                traceback.print_exc()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
