#!/usr/bin/env python3
"""CF-0690: "a demo via API" - the rule that holds an `api_chat` graphic to
the record of the real call it shows.

The user's decision of 2026-10-12 (Q30): a ExampleTech story about a new
model may show that model's REAL answer to one of the channel's neutral
prompts, asked through the model's official API (the Gemini API free tier,
`shared/gemini/gemini_api.py`) and drawn in the factory's own chat animation
(`shared/own_graphic.py` template `api_chat`), labelled
"<model> · via API". The answer is never a fact of the story, and nothing of
it is rewritten - only cut, at a sentence or a word, with "…".

**The record.** Every call leaves a protocol (`gemini_api.ask`): provider,
endpoint, model_requested, model_version, prompt, generation_config,
answer (verbatim), finish_reason, prompt_feedback, citation, usage,
response_id, requested_at, answered_at, key_source, status, skip_reason.
The Trend Hunter keeps it as the topic's `api_demo_record`
(`{record_id: "api-demo-<id>", protocol}`, `RECORD_FIELD`); a script's
`api_chat` graphic names it by its top-level `record_id`.

**What a frame must be** (`chat_problems`):

* `api_demo_no_record` - the graphic names no record, or a record that is
  not there or is not a protocol (`protocol_problems`);
* `api_demo_bad_finish` - the call was not `ok` (skipped, refused);
* `api_demo_prompt_mismatch` - `data.prompt` is not the protocol's prompt,
  character for character;
* `api_demo_answer_rewritten` - `data.answer` is neither the answer nor
  `shown_answer(answer, max_answer_chars)`;
* `api_demo_model_mismatch` - `data.model_label` is not
  `model_label(display_name_for(protocol.model_version, config))`: the name
  comes from the API's own `modelVersion` through the channel's list, never
  from the answer's text, and an unknown model has no label.

`api_demo_answer_is_fact` is the Content Researcher's code (a script that
states the demo's answer as a fact, or backs a claim on it) - named here so
every repository spells it the same.

`config` is the channel's `api_demo` block (`channels/example-tech/
footage-origin.json`, checked by `shared/footage_licence.py`
`api_demo_errors`): `models[] {id, display_name, matches[]}`,
`default_model`, `prompts[]`, `max_calls_per_batch`, `min_interval_seconds`,
`timeout_seconds`, `max_answer_chars`.

Stdlib only, no network, imports nothing of the checkout but
`factrule/sentences.py` beside it, by path (CF-0737: an answer is not cut at
«Bros.» or an initial): loadable by path from any repository
(`shared/own_graphic.py` loads it beside itself).
"""
import importlib.util
import re
import sys
from pathlib import Path


def _load_sentences():
    path = Path(__file__).resolve().parent / "factrule" / "sentences.py"
    name = "factory_sentences_cf0737@" + str(path)    # = fact_rule's own load
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return sys.modules[name]


_sentences = _load_sentences()

RULE = "CF-0690"
KIND = "own_graphic"                 # the asset kind stays own_graphic (CF-0689 path)
TEMPLATE = "api_chat"                # = own_graphic's template
ORIGIN = "api_demo"                  # = footage_licence.API_DEMO
RECORD_FIELD = "api_demo_record"     # a topic's record of its call(s)
RECORD_KEY = "record_id"             # an api_chat graphic's top-level key
RECORD_ID_RE = re.compile(r"^api-demo-[a-z0-9][a-z0-9_-]*$")
CONFIG_KEY = "api_demo"              # the block of the channel's footage-origin.json

LABEL_SUFFIX = " · via API"
ELLIPSIS = "…"
DEFAULT_MAX_ANSWER_CHARS = 280
PROMPT_MAX_CHARS = 160
LABEL_MAX_CHARS = 48

PROVIDERS = ("gemini_api",)
STATUSES = ("ok", "skipped", "refused")
PROTOCOL_KEYS = ("provider", "endpoint", "model_requested", "model_version", "prompt",
                 "generation_config", "answer", "finish_reason", "prompt_feedback", "citation",
                 "usage", "response_id", "requested_at", "answered_at", "key_source", "status",
                 "skip_reason")
KEY_SOURCES = ("environment", ".env", None)

# ------------------------------------------------------------------ codes
FAIL_NO_RECORD = "api_demo_no_record"
FAIL_PROMPT_MISMATCH = "api_demo_prompt_mismatch"
FAIL_ANSWER_REWRITTEN = "api_demo_answer_rewritten"
FAIL_MODEL_MISMATCH = "api_demo_model_mismatch"
FAIL_BAD_FINISH = "api_demo_bad_finish"
FAIL_ANSWER_IS_FACT = "api_demo_answer_is_fact"      # the Content Researcher's
FAIL_CODES = (FAIL_NO_RECORD, FAIL_PROMPT_MISMATCH, FAIL_ANSWER_REWRITTEN, FAIL_MODEL_MISMATCH,
              FAIL_BAD_FINISH, FAIL_ANSWER_IS_FACT)

FIXES = {
    FAIL_NO_RECORD: "an api_chat graphic names by `record_id` (\"api-demo-<id>\") the topic's "
                    "`api_demo_record` - the protocol of the real call it shows; no record, "
                    "no chat",
    FAIL_PROMPT_MISMATCH: "`data.prompt` is the protocol's `prompt`, character for character",
    FAIL_ANSWER_REWRITTEN: "`data.answer` is the protocol's `answer` verbatim, or "
                           "`api_demo.shown_answer(answer, max_answer_chars)` - cut at a "
                           "sentence or a word with \"…\", never reworded",
    FAIL_MODEL_MISMATCH: "`data.model_label` is `api_demo.model_label(display_name_for("
                         "protocol.model_version, config))` - \"<display name> · via API\" "
                         "from the API's own modelVersion; a model the channel's list does "
                         "not know is not shown",
    FAIL_BAD_FINISH: "only a call whose protocol says `status: ok` is shown - a skipped or "
                     "refused call has no chat",
    FAIL_ANSWER_IS_FACT: "the demo's answer is never a fact of the story: no claim stands on it "
                         "and the narration does not state what it says as true",
}
REFUSALS_RU = {
    FAIL_NO_RECORD: "У чата «через API» нет протокола настоящего вызова (record_id).",
    FAIL_PROMPT_MISMATCH: "Запрос в чате не совпадает с запросом из протокола вызова.",
    FAIL_ANSWER_REWRITTEN: "Ответ модели в чате переписан: допустим только дословный ответ "
                           "или его начало, обрезанное по предложению или слову с «…».",
    FAIL_MODEL_MISMATCH: "Подпись модели не совпадает с modelVersion из протокола "
                         "(или модели нет в списке канала).",
    FAIL_BAD_FINISH: "Вызов API не завершился нормально (пропущен или отказ) - такой чат "
                     "не показывается.",
    FAIL_ANSWER_IS_FACT: "Ответ модели из демо подан как факт ролика.",
}


def _problem(code, graphic_id=None, detail=None, **extra):
    p = {"code": code, "graphic_id": graphic_id, "detail": detail,
         "fix": FIXES[code], "text_ru": REFUSALS_RU[code]}
    p.update(extra)
    return p


def _str(v):
    return isinstance(v, str) and v.strip() != ""


# --------------------------------------------------------------- protocol
def protocol_problems(p):
    """Why `p` is not a protocol of `gemini_api.ask` ([] when it is)."""
    if not isinstance(p, dict):
        return [f"not an object: {type(p).__name__}"]
    errs = []
    missing = [k for k in PROTOCOL_KEYS if k not in p]
    if missing:
        errs.append(f"missing {missing}")
    if p.get("provider") not in PROVIDERS:
        errs.append(f"provider {p.get('provider')!r} is not one of {PROVIDERS}")
    status = p.get("status")
    if status not in STATUSES:
        errs.append(f"status {status!r} is not one of {STATUSES}")
    if not _str(p.get("prompt")):
        errs.append("prompt must be a non-empty string")
    if not _str(p.get("model_requested")):
        errs.append("model_requested must be a model id")
    if p.get("key_source") not in KEY_SOURCES:
        errs.append(f"key_source {p.get('key_source')!r} is not one of {KEY_SOURCES}")
    ep = p.get("endpoint")
    if ep is not None and not (isinstance(ep, str) and ep.startswith("https://")):
        errs.append("endpoint must be an https URL")
    elif isinstance(ep, str) and re.search(r"[?&]key=", ep):
        errs.append("endpoint carries a key - a key never goes in a URL")
    if not isinstance(p.get("citation"), bool):
        errs.append("citation must be true or false")
    if status == "ok":
        if not _str(p.get("answer")):
            errs.append("an ok call has its answer")
        if not _str(p.get("model_version")):
            errs.append("an ok call has the API's modelVersion")
        if p.get("finish_reason") != "STOP":
            errs.append(f"an ok call finished with STOP, not {p.get('finish_reason')!r}")
        if p.get("citation"):
            errs.append("an ok call has no citation")
        if not _str(p.get("answered_at")):
            errs.append("an ok call says when it was answered")
        if p.get("skip_reason") is not None:
            errs.append("an ok call has no skip_reason")
    elif status in ("skipped", "refused") and not _str(p.get("skip_reason")):
        errs.append(f"a {status} call says why in skip_reason")
    return errs


def protocols_by_record(records):
    """{record_id: protocol} of a topic's `api_demo_record` - one record
    {record_id, protocol} or a list of them; anything malformed is left out."""
    if isinstance(records, dict):
        records = [records]
    out = {}
    for r in records or []:
        if isinstance(r, dict) and isinstance(r.get(RECORD_KEY), str) \
                and RECORD_ID_RE.match(r[RECORD_KEY]) and isinstance(r.get("protocol"), dict):
            out.setdefault(r[RECORD_KEY], r["protocol"])
    return out


# ---------------------------------------------------------------- answer
_SENTENCE_END_RE = re.compile(r"[.!?…][\"'”’)\]]*(?=\s)")


def shown_answer(answer, max_chars=DEFAULT_MAX_ANSWER_CHARS):
    """The answer as the frame may show it: the whole answer when it fits
    `max_chars`, else its verbatim beginning cut at the last sentence end
    (when that keeps at least half of the room; the stop of an abbreviation
    or an initial is not one, CF-0737) or else at the last word
    boundary, trailing spaces off, and "…" - at most `max_chars` in all."""
    answer = "" if answer is None else str(answer)
    max_chars = int(max_chars)
    if len(answer) <= max_chars:
        return answer
    room = max(1, max_chars - len(ELLIPSIS))
    head = answer[:room + 1]          # one more: a boundary right at the edge counts
    cut = None
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)
            if m.end() <= room and not _sentences.abbreviation_end(head[:m.start() + 1])]
    if ends and ends[-1] >= room // 2:
        cut = ends[-1]
    else:
        spaces = [m.start() for m in re.finditer(r"\s", head) if m.start() <= room]
        if spaces and spaces[-1] > 0:
            cut = spaces[-1]
    if cut is None:
        cut = room
    return answer[:cut].rstrip() + ELLIPSIS


def model_label(display_name):
    """"<display name> · via API" - the chat's only words of its own."""
    return f"{display_name}{LABEL_SUFFIX}"


def _words(text):
    return re.findall(r"[0-9a-z]+(?:\.[0-9a-z]+)*", str(text or "").lower())


_VERSION_SUFFIX_RE = re.compile(r"^(?:\d+|preview|latest|exp|stable)$")


def display_name_for(model_version, config):
    """The display name the channel's list (`config.models[]`) gives the
    API's `modelVersion`, or None. A model matches by its `id` or by one of
    its `matches` word for word, a version suffix ("-preview-05-20",
    "-001", "-latest") allowed after it; the longest match wins, so
    "gemini-2.5-flash-lite" is never "Gemini 2.5 Flash". Never read from the
    answer's text."""
    if not _str(model_version):
        return None
    mv = model_version.strip().lower()
    if mv.startswith("models/"):
        mv = mv[len("models/"):]
    words = _words(mv)
    best, best_len = None, 0
    for m in (config or {}).get("models") or []:
        if not (isinstance(m, dict) and _str(m.get("display_name"))):
            continue
        if isinstance(m.get("id"), str) and m["id"].lower() == mv:
            return m["display_name"]
        for phrase in [m.get("id")] + list(m.get("matches") or []):
            p = _words(phrase)
            if p and words[:len(p)] == p and all(_VERSION_SUFFIX_RE.match(w)
                                                 for w in words[len(p):]) \
                    and len(p) > best_len:
                best, best_len = m["display_name"], len(p)
    return best


def max_answer_chars(config):
    v = (config or {}).get("max_answer_chars")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 \
        else DEFAULT_MAX_ANSWER_CHARS


# ------------------------------------------------------------------ check
def chat_problems(graphic, protocol, config):
    """The problems of one `api_chat` graphic against the protocol of the
    call it shows (None: no record) and the channel's `api_demo` config:
    problem dicts {code, graphic_id, detail, fix, text_ru}; [] - it stands."""
    g = graphic if isinstance(graphic, dict) else {}
    gid = g.get("graphic_id") if isinstance(g.get("graphic_id"), str) else None
    rid = g.get(RECORD_KEY)
    if protocol is None:
        return [_problem(FAIL_NO_RECORD, gid, f"record {rid!r}: no protocol", record_id=rid)]
    shape = protocol_problems(protocol)
    if shape:
        return [_problem(FAIL_NO_RECORD, gid, f"record {rid!r} is no protocol: "
                                              + "; ".join(shape), record_id=rid)]
    out = []
    if protocol["status"] != "ok":
        out.append(_problem(FAIL_BAD_FINISH, gid, f"record {rid!r}: status "
                                                  f"{protocol['status']} - "
                                                  f"{protocol.get('skip_reason')}",
                            record_id=rid))
    data = g.get("data") if isinstance(g.get("data"), dict) else {}
    if data.get("prompt") != protocol["prompt"]:
        out.append(_problem(FAIL_PROMPT_MISMATCH, gid,
                            f"data.prompt {data.get('prompt')!r} is not the protocol's "
                            f"{protocol['prompt']!r}", record_id=rid))
    answer = protocol.get("answer")
    if isinstance(answer, str) and answer:
        allowed = {answer, shown_answer(answer, max_answer_chars(config))}
        if data.get("answer") not in allowed:
            out.append(_problem(FAIL_ANSWER_REWRITTEN, gid,
                                f"data.answer {str(data.get('answer'))[:60]!r}... is neither the "
                                f"answer nor its cut", record_id=rid))
    display = display_name_for(protocol.get("model_version"), config)
    if display is None:
        out.append(_problem(FAIL_MODEL_MISMATCH, gid,
                            f"modelVersion {protocol.get('model_version')!r} is not a model of "
                            f"the channel's list", record_id=rid))
    elif data.get("model_label") != model_label(display):
        out.append(_problem(FAIL_MODEL_MISMATCH, gid,
                            f"data.model_label {data.get('model_label')!r} is not "
                            f"{model_label(display)!r}", record_id=rid))
    return out


def codes(problems):
    return [p.get("code") for p in problems or []]
