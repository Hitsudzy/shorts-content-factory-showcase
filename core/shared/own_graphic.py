#!/usr/bin/env python3
"""CF-0689: the graphics the factory draws itself from the script's facts -
ExampleTech's base footage (the user's decision of 12.10: no rights risk,
fully automatic, nothing invented).

A script orders its graphics in a top-level `graphics[]`:

    {"graphic_id": "g1",
     "template": "benchmark",
     "data": {"metric": "SWE-bench Verified",
              "rows": [{"name": "Gemini 2.5 Pro", "score": "63.8%"}, ...]},
     "values": [{"path": "data.rows[0].score", "text": "63.8%", "claim_ids": ["c4"]}, ...],
     "source_label": "Google"}

and places each on the narration through a `visual_anchors[]` entry that
carries `graphic_id` instead of a pool `phrase` (the Content Researcher's
`graphic_not_placed`; the Video Editor renders it in Remotion, its
`asset_kind` is `own_graphic`).

The rule this module holds - the template adds nothing, every value stands
on the script's facts:

* `TEMPLATES` - the templates (six on claims, CF-0690's `api_chat` on a
  call's record), each with its `data` fields: their kind
  (`name` / `number` / `date` / `text`), whether they are required, how long a
  string may be and how many items a list may hold - small enough to read on a
  phone in a Short.
* `order_problems(graphic)` / `order_errors(graphic)` - the shape: known
  keys, a known template, every `data` string a field of it within its caps,
  every `values[]` entry naming a string of `data` by its `path` with that
  string as its `text`; a benchmark carries its `source_label`.
* `value_problems(graphic, claims, pieces=None)` - every value is backed by
  declared claims of the script (`claim_ids`, each a claim with `where:
  "graphic:<graphic_id>"` - so CF-0552's mechanics and CF-0553's judge read
  the graphic like any other viewer text), and every number, name and date
  in it is in one of those claims' `support[].quote` (numbers compared as
  numbers: thousands separators, a comma decimal, `%`, currency signs and
  `million`/`billion`/`K`/`M`/`B` read; dates with month names read as
  dates; names compared word for word through `claims.norm`).
* `adds_text(graphic)` - every string of `data` that no value names: words
  the template would put on the frame with nothing behind them.
* `viewer_text(graphic)` - what the viewer reads on the frame, line by line;
  `shared/factrule/claims.py` `viewer_texts()` carries it under
  `graphic:<graphic_id>`, and a graphic's claim `text` is copied from it.
* `check_graphics(script, pieces=None, protocols=None, config=None)` - all
  of the above over a script's `graphics[]`, one problem dict per finding
  with its code and its fix.

CF-0690 - the seventh template, `api_chat` ("a demo via API", the user's
decision of 12.10, Q30): a chat bubble pair in the factory's own neutral
animation - the label "<model> · via API", the prompt the factory sent and
the model's REAL answer (`shared/gemini/gemini_api.py`). It stands on no
claim (the answer is never a fact, `values` stays empty) but on the record
of the call: the graphic names the topic's `api_demo_record` by its
top-level `record_id` ("api-demo-<id>"), and `shared/api_demo.py`
`chat_problems` replaces the number / name / date footing check - the prompt
and the answer verbatim (the answer may be cut by `api_demo.shown_answer`),
the label from the API's own modelVersion. `check_graphics` hands it the
`protocols` ({record_id: protocol}) and the channel's `api_demo` `config`;
a caller that hands no protocols gets `api_demo_no_record` for every chat -
a chat is never passed unread. The asset kind stays `own_graphic`.

Codes: `graphic_malformed`, `graphic_unknown_template`,
`graphic_value_unbacked`, `graphic_value_not_in_footing`,
`graphic_benchmark_unattributed`, `graphic_adds_text` (the Content
Researcher adds `graphic_not_placed` itself).

Stdlib only, no network; loadable by path from any repository (the Video
Editor's `_root_shared.root_module("own_graphic")`, the Content Researcher's
loader of the root's `shared/`). It loads `shared/factrule/claims.py` beside
it by path for the normalising it shares with the claim rule.
"""
import importlib.util
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

RULE = "CF-0689"
GRAPHICS_FIELD = "graphics"
KIND = "own_graphic"                 # = footage_licence.OWN_GRAPHIC, the VE's asset_kind
WHERE_PREFIX = "graphic:"            # a claim's `where` for a graphic's value
ANCHOR_KEY = "graphic_id"            # a visual_anchors[] entry that places a graphic

GRAPHIC_KEYS = ("graphic_id", "template", "data", "values")
GRAPHIC_OPTIONAL_KEYS = ("source_label", "record_id")    # record_id: api_chat only (CF-0690)
VALUE_KEYS = ("path", "text", "claim_ids")
GRAPHIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")   # = claims.CLAIM_ID_RE

# ------------------------------------------------------------- templates
NAME, NUMBER, DATE, TEXT = "name", "number", "date", "text"
FIELD_KINDS = (NAME, NUMBER, DATE, TEXT)
LIST = "list"
# How long a string of each kind may be: one line of a phone screen.
MAX_CHARS = {NAME: 32, NUMBER: 16, DATE: 24, TEXT: 44}
SOURCE_LABEL_MAX_CHARS = 32


def _f(kind, required=True, max_chars=None, multiline=False):
    out = {"kind": kind, "required": required, "max_chars": max_chars or MAX_CHARS[kind]}
    if multiline:
        out["multiline"] = True        # a model's answer keeps its own line breaks (CF-0690)
    return out


def _list(item, lo, hi):
    return {"kind": LIST, "required": True, "min": lo, "max": hi, "item": item}


# Each template: what it draws, its `data` fields (a field is a scalar
# {kind, required, max_chars}, or a list {kind: "list", min, max, item},
# where `item` is a scalar field or {field: scalar}), and `one_of` - fields
# of which at least one must be there.
TEMPLATES = {
    "spec_card": {
        "what": "a product and up to four of its specs, one row each (label: value)",
        "fields": {"product": _f(NAME),
                   "rows": _list({"label": _f(TEXT, max_chars=24), "value": _f(TEXT, max_chars=20)},
                                 1, 4)},
    },
    "comparison": {
        "what": "two things side by side - before / after, or two products - and up to three "
                "rows, each the same point on both sides (an optional label: left | right)",
        "fields": {"left": _f(TEXT, max_chars=24), "right": _f(TEXT, max_chars=24),
                   "rows": _list({"label": _f(TEXT, required=False, max_chars=24),
                                  "left": _f(TEXT, max_chars=20),
                                  "right": _f(TEXT, max_chars=20)}, 1, 3)},
    },
    "price_date": {
        "what": "a product with its price and / or its release date (and one short note)",
        "fields": {"product": _f(NAME),
                   "price": _f(NUMBER, required=False),
                   "date": _f(DATE, required=False),
                   "note": _f(TEXT, required=False, max_chars=36)},
        "one_of": ("price", "date"),
    },
    "benchmark": {
        "what": "one metric, two to five contenders as bars (name: score), and the source line "
                "«according to <source_label>» - always (CF-0566: a vendor's number is its claim)",
        "fields": {"metric": _f(TEXT, max_chars=32),
                   "rows": _list({"name": _f(NAME, max_chars=24), "score": _f(NUMBER)}, 2, 5)},
        "needs_source_label": True,
    },
    "timeline": {
        "what": "two to five dated events in order (date: label)",
        "fields": {"events": _list({"date": _f(DATE, max_chars=16),
                                    "label": _f(TEXT, max_chars=32)}, 2, 5)},
    },
    "how_it_works": {
        "what": "two to five boxes joined by arrows, in order (an optional title above)",
        "fields": {"title": _f(TEXT, required=False, max_chars=32),
                   "steps": _list(_f(TEXT, max_chars=28), 2, 5)},
    },
    # CF-0690: the model's real answer through its API - on the call's record,
    # not on claims (`shared/api_demo.py`); caps = api_demo's.
    "api_chat": {
        "what": "a neutral chat: the label «<model> · via API», the prompt the factory sent and "
                "the model's real answer, verbatim or cut with «…» (shared/api_demo.py) - "
                "on the record of the call (`record_id`), never a fact",
        "fields": {"model_label": _f(TEXT, max_chars=48),
                   "prompt": _f(TEXT, max_chars=160, multiline=True),
                   "answer": _f(TEXT, max_chars=280, multiline=True),
                   "date": _f(DATE, required=False)},
        "on_record": True,
    },
}
API_CHAT = "api_chat"

# The caption a `source_label` is drawn as, by the channel's language; the
# template's only words, and only for whose numbers they are (CF-0566).
SOURCE_CAPTION = {"en": "According to {}", "ru": "По данным {}"}
DEFAULT_LANG = "en"

# ------------------------------------------------------------------ codes
FAIL_MALFORMED = "graphic_malformed"
FAIL_UNKNOWN_TEMPLATE = "graphic_unknown_template"
FAIL_VALUE_UNBACKED = "graphic_value_unbacked"
FAIL_VALUE_NOT_IN_FOOTING = "graphic_value_not_in_footing"
FAIL_BENCHMARK_UNATTRIBUTED = "graphic_benchmark_unattributed"
FAIL_ADDS_TEXT = "graphic_adds_text"
FAIL_CODES = (FAIL_MALFORMED, FAIL_UNKNOWN_TEMPLATE, FAIL_VALUE_UNBACKED,
              FAIL_VALUE_NOT_IN_FOOTING, FAIL_BENCHMARK_UNATTRIBUTED, FAIL_ADDS_TEXT)

FIXES = {
    FAIL_MALFORMED: "a graphic is {graphic_id, template, data, values: [{path, text, claim_ids}], "
                    "source_label} - `data` holds only the template's fields (strings, within "
                    "their caps), every value names a string of `data` by its path and copies it",
    FAIL_UNKNOWN_TEMPLATE: "`template` is one of " + ", ".join(TEMPLATES),
    FAIL_VALUE_UNBACKED: "every value names in `claim_ids` the declared claims it stands on - "
                         "claims of `claims[]` with `where: \"graphic:<graphic_id>\"`",
    FAIL_VALUE_NOT_IN_FOOTING: "every number, name and date on the graphic is in a quote of its "
                               "claims (`support[].quote`) - copy it from the source as the "
                               "source writes it, or drop it",
    FAIL_BENCHMARK_UNATTRIBUTED: "a benchmark says whose numbers they are: `source_label` names "
                                 "the owner (\"Google\") - drawn as \"According to Google\"",
    FAIL_ADDS_TEXT: "the template draws nothing of its own: every string of `data` is a value "
                    "(`values[]` names its path) backed by a claim, or it goes",
}
REFUSALS_RU = {
    FAIL_MALFORMED: "Графика записана не по форме: поля шаблона, лимиты длины, значения со ссылкой "
                    "на путь в данных.",
    FAIL_UNKNOWN_TEMPLATE: "Такого шаблона графики нет.",
    FAIL_VALUE_UNBACKED: "Значение на графике не опирается на заявленное утверждение сценария "
                         "(`claims[]` с `where: graphic:<id>`).",
    FAIL_VALUE_NOT_IN_FOOTING: "Числа, имени или даты с графики нет в цитате-опоре её утверждения.",
    FAIL_BENCHMARK_UNATTRIBUTED: "У графика бенчмарка нет подписи, чьи это данные («according "
                                 "to X»).",
    FAIL_ADDS_TEXT: "Шаблон выводит на кадр текст, которого нет среди значений с опорой.",
}

# ---------------------------------------------------- the claim rule's words
_HERE = Path(__file__).resolve().parent
CLAIMS_PATH = _HERE / "factrule" / "claims.py"
API_DEMO_PATH = _HERE / "api_demo.py"


def _load_claims():
    spec = importlib.util.spec_from_file_location("_claims_for_own_graphic", CLAIMS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


claims = _load_claims()


def _load_api_demo():
    spec = importlib.util.spec_from_file_location("_api_demo_for_own_graphic", API_DEMO_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


api_demo = _load_api_demo()
# CF-0690: the codes an `api_chat` is refused with (shared/api_demo.py); not in
# FAIL_CODES - those are the claim-backed graphics' own.
CHAT_CODES = api_demo.FAIL_CODES


def where_of(graphic_id):
    """The `where` of a claim that backs a value of this graphic."""
    return f"{WHERE_PREFIX}{graphic_id}"


def graphic_id_of(where):
    """The graphic id a claim's `where` names, or None."""
    if isinstance(where, str) and where.startswith(WHERE_PREFIX):
        gid = where[len(WHERE_PREFIX):]
        return gid if GRAPHIC_ID_RE.match(gid) else None
    return None


def graphics_of(script):
    g = (script or {}).get(GRAPHICS_FIELD)
    return g if isinstance(g, list) else []


# ------------------------------------------------------------------ paths
_PATH_RE = re.compile(r"^data(?:\.[a-z_]+|\[\d+\])+$")
_STEP_RE = re.compile(r"\.([a-z_]+)|\[(\d+)\]")


def resolve(graphic, path):
    """The value at `path` ("data.rows[0].score") of a graphic, or None."""
    if not (isinstance(path, str) and _PATH_RE.match(path)):
        return None
    node = (graphic or {}).get("data")
    for key, idx in _STEP_RE.findall(path[len("data"):]):
        if key:
            node = node.get(key) if isinstance(node, dict) else None
        else:
            i = int(idx)
            node = node[i] if isinstance(node, list) and i < len(node) else None
        if node is None:
            return None
    return node


def leaves(graphic):
    """[(path, value, field)] of every leaf of a graphic's `data` the template
    knows (field None for a leaf it does not)."""
    tpl = TEMPLATES.get((graphic or {}).get("template")) or {}
    out = []

    def walk(node, path, spec):
        if isinstance(node, dict):
            fields = spec if isinstance(spec, dict) and "kind" not in spec else {}
            for k, v in node.items():
                walk(v, f"{path}.{k}", fields.get(k))
        elif isinstance(node, list):
            item = spec.get("item") if isinstance(spec, dict) and spec.get("kind") == LIST else None
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", item)
        else:
            out.append((path, node, spec if isinstance(spec, dict) and "kind" in spec
                        and spec["kind"] != LIST else None))

    data = (graphic or {}).get("data")
    if isinstance(data, dict):
        walk(data, "data", tpl.get("fields") or {})
    return out


def field_of(graphic, path):
    """The template's field spec of the leaf at `path`, or None."""
    for p, _, spec in leaves(graphic):
        if p == path:
            return spec
    return None


# ------------------------------------------------------------------ shape
def _problem(code, graphic_id=None, detail=None, **extra):
    p = {"code": code, "graphic_id": graphic_id, "detail": detail,
         "fix": FIXES[code], "text_ru": REFUSALS_RU[code]}
    p.update(extra)
    return p


def _scalar_errors(value, spec, ctx):
    if not isinstance(value, str) or not value.strip():
        return [f"{ctx} must be a non-empty string"]
    errs = []
    if len(value) > spec["max_chars"]:
        errs.append(f"{ctx} is {len(value)} characters, over {spec['max_chars']} - "
                    f"not read on a phone")
    if "\n" in value and not spec.get("multiline"):
        errs.append(f"{ctx} is one line")
    if spec["kind"] == NUMBER and not re.search(r"\d", value):
        errs.append(f"{ctx} is a number field and holds no number")
    return errs


def _field_errors(node, spec, ctx):
    if spec["kind"] != LIST:
        return _scalar_errors(node, spec, ctx)
    if not isinstance(node, list):
        return [f"{ctx} must be a list"]
    errs = []
    if not spec["min"] <= len(node) <= spec["max"]:
        errs.append(f"{ctx} holds {len(node)} item(s), not {spec['min']}..{spec['max']}")
    item = spec["item"]
    for i, it in enumerate(node):
        ictx = f"{ctx}[{i}]"
        if "kind" in item:
            errs += _scalar_errors(it, item, ictx)
        elif not isinstance(it, dict):
            errs.append(f"{ictx} must be an object")
        else:
            errs += _object_errors(it, item, ictx)
    return errs


def _object_errors(node, fields, ctx):
    errs = []
    unknown = sorted(set(node) - set(fields))
    if unknown:
        errs.append(f"{ctx}: unknown field(s) {unknown} - the template has {sorted(fields)}")
    for name, spec in fields.items():
        if name not in node or node[name] is None:
            if spec.get("required"):
                errs.append(f"{ctx}.{name} is missing")
            continue
        errs += _field_errors(node[name], spec, f"{ctx}.{name}")
    return errs


def _template_fields(template, config=None):
    """The template's fields; an `api_chat`'s answer cap is the channel's
    `api_demo.max_answer_chars` when its config is given (CF-0690)."""
    tpl = TEMPLATES.get(template) or {}
    fields = tpl.get("fields") or {}
    if template == API_CHAT and config is not None:
        fields = dict(fields)
        fields["answer"] = dict(fields["answer"], max_chars=api_demo.max_answer_chars(config))
    return fields


def order_problems(graphic, config=None):
    """What is wrong with one graphic's order, as problem dicts ([] when it is
    well formed): `graphic_malformed`, `graphic_unknown_template`,
    `graphic_benchmark_unattributed`. `config` - the channel's `api_demo`
    block - sets an `api_chat`'s answer cap (CF-0690)."""
    if not isinstance(graphic, dict):
        return [_problem(FAIL_MALFORMED, None, f"not an object: {graphic!r}")]
    gid = graphic.get("graphic_id")
    gid_out = gid if isinstance(gid, str) else None
    errs = []
    missing = [k for k in GRAPHIC_KEYS if k not in graphic
               and not (k == "values" and graphic.get("template") == API_CHAT)]
    if missing:
        errs.append(f"missing {missing}")
    extra = sorted(set(graphic) - set(GRAPHIC_KEYS) - set(GRAPHIC_OPTIONAL_KEYS))
    if extra:
        errs.append(f"unknown key(s) {extra}")
    if "graphic_id" in graphic and not (isinstance(gid, str) and GRAPHIC_ID_RE.match(gid)):
        errs.append(f"graphic_id {gid!r} is not [a-z0-9][a-z0-9_-]*")
    label = graphic.get("source_label")
    if label is not None and not (isinstance(label, str) and label.strip()
                                  and len(label) <= SOURCE_LABEL_MAX_CHARS):
        errs.append(f"source_label {label!r} is a name of at most {SOURCE_LABEL_MAX_CHARS} "
                    f"characters, or null")
    out = []
    template = graphic.get("template")
    tpl = TEMPLATES.get(template)
    if "template" in graphic and tpl is None:
        out.append(_problem(FAIL_UNKNOWN_TEMPLATE, gid_out, f"template {template!r}"))
    on_record = bool(tpl and tpl.get("on_record"))
    rid = graphic.get("record_id")
    if "record_id" in graphic and not on_record:
        errs.append(f"record_id is an {API_CHAT}'s only - a {template} stands on claims")
    elif rid is not None and not (isinstance(rid, str) and api_demo.RECORD_ID_RE.match(rid)):
        errs.append(f"record_id {rid!r} is not api-demo-<id>")
    if on_record and label is not None:
        errs.append(f"an {API_CHAT} has no source_label - its label is the model's")
    data = graphic.get("data")
    if "data" in graphic and not isinstance(data, dict):
        errs.append("data must be an object")
    elif tpl is not None and isinstance(data, dict):
        errs += _object_errors(data, _template_fields(template, config), "data")
        one_of = tpl.get("one_of")
        if one_of and not any(data.get(k) is not None for k in one_of):
            errs.append(f"data needs at least one of {list(one_of)}")
    values = graphic.get("values")
    if on_record:
        if values not in (None, []):
            errs.append(f"an {API_CHAT} has no values - it stands on the call's record, and "
                        f"the model's answer is never a fact (values: [])")
    elif "values" in graphic:
        if not isinstance(values, list) or not values:
            errs.append("values must be a non-empty list - a graphic with no value says nothing")
        else:
            seen = set()
            for j, v in enumerate(values):
                ctx = f"values[{j}]"
                if not isinstance(v, dict) or set(v) != set(VALUE_KEYS):
                    errs.append(f"{ctx}: exactly {{path, text, claim_ids}}, got {v!r}")
                    continue
                if not (isinstance(v["claim_ids"], list)
                        and all(isinstance(c, str) for c in v["claim_ids"])):
                    errs.append(f"{ctx}: claim_ids must be a list of claim ids")
                path = v["path"]
                if path in seen:
                    errs.append(f"{ctx}: path {path!r} twice")
                seen.add(path)
                at = resolve(graphic, path)
                if not isinstance(at, str):
                    errs.append(f"{ctx}: path {path!r} names no string of `data`")
                elif v["text"] != at:
                    errs.append(f"{ctx}: text {v['text']!r} is not the string at {path} ({at!r})")
    if errs:
        out.insert(0, _problem(FAIL_MALFORMED, gid_out, "; ".join(errs)))
    if tpl is not None and tpl.get("needs_source_label") and \
            not (isinstance(label, str) and label.strip()):
        out.append(_problem(FAIL_BENCHMARK_UNATTRIBUTED, gid_out,
                            f"a {template} without `source_label`"))
    return out


def order_errors(graphic, config=None):
    """The same as `order_problems`, as sentences "<code>: <detail>"."""
    return [f"{p['code']}: {p['detail']}" for p in order_problems(graphic, config)]


# ---------------------------------------------------------------- numbers
# A thin / no-break space or an apostrophe between digit groups is a
# thousands separator ("1 000", "1'000"); read before NFKC turns it into a
# plain space.
_GROUP_SPACE_RE = re.compile(r"(?<=\d)[    '’](?=\d{3}(?!\d))")
_NUM_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)*)(?:\s?(thousand|million|billion|trillion|"
                     r"mln|bln|mn|bn|tn|k|m|b|t|тыс|млн|млрд|трлн)(?![a-zа-яё]))?")
_SCALES = {"thousand": 3, "k": 3, "тыс": 3, "million": 6, "mln": 6, "mn": 6, "m": 6, "млн": 6,
           "billion": 9, "bln": 9, "bn": 9, "b": 9, "млрд": 9, "trillion": 12, "tn": 12,
           "t": 12, "трлн": 12}


def _plain(text):
    text = _GROUP_SPACE_RE.sub(",", str(text or ""))
    return unicodedata.normalize("NFKC", text).casefold()


def _number(token):
    """The digits of one token as a canonical decimal string, or the token
    itself when it is no single number (a version "2.5.1")."""
    commas, dots = token.count(","), token.count(".")
    groups = re.split(r"[.,]", token)
    if commas and dots:
        dec = "," if token.rfind(",") > token.rfind(".") else "."
        whole, frac = token.rsplit(dec, 1)
        digits = re.sub(r"[.,]", "", whole) + "." + frac
    elif commas or dots:
        sep = "," if commas else "."
        thousands = len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])
        if commas + dots > 1:
            if not thousands:
                return token
            digits = "".join(groups)
        elif sep == "," and thousands:
            digits = "".join(groups)            # 1,000 - a thousands comma
        else:
            digits = groups[0] + "." + groups[1]   # 92.3, 92,3 - a decimal
    else:
        digits = token
    try:
        return format(Decimal(digits).normalize(), "f")
    except InvalidOperation:
        return token


def parse_numbers(text):
    """[(bare, scaled)] of the numbers in a text: `bare` the number as
    written (canonical: "1,000" and "1 000" are "1000", "92,3" is "92.3",
    "92.30" is "92.3"), `scaled` times its word ("1.5 billion" -> 1500000000,
    "128K" -> 128000; None without one). `%`, currency signs and units are
    not part of a number. The Video Editor reads a bar's length from it."""
    out = []
    for m in _NUM_RE.finditer(_plain(text)):
        bare = _number(m.group(1))
        scaled = None
        if m.group(2) and re.fullmatch(r"[\d.]+", bare):
            scaled = format((Decimal(bare) * (Decimal(10) ** _SCALES[m.group(2)])).normalize(), "f")
        out.append((bare, scaled))
    return out


def number_found(value_number, quote_numbers):
    """Is one number of a value among a quote's? Scaled numbers compare by
    their size ("1.5B" = "1,500 million"); a value's bare number (no scale
    word) matches the same bare number of the quote ("1.5" of "1.5 billion")."""
    bare, scaled = value_number
    for qb, qs in quote_numbers:
        if scaled is not None and scaled == (qs if qs is not None else qb):
            return True
        if scaled is None and bare in (qb, qs):
            return True
    return False


# ------------------------------------------------------------------ dates
# Each month as whole words: the English name or its short form, the Russian
# stem with any ending ("марта", "мае").
MONTHS = {
    1: ("january", "jan", "январ[а-яё]*"), 2: ("february", "feb", "феврал[а-яё]*"),
    3: ("march", "mar", "март[а-яё]*"), 4: ("april", "apr", "апрел[а-яё]*"),
    5: ("may", "ма[йяюе]"), 6: ("june", "jun", "июн[а-яё]*"), 7: ("july", "jul", "июл[а-яё]*"),
    8: ("august", "aug", "август[а-яё]*"), 9: ("september", "sept", "sep", "сентябр[а-яё]*"),
    10: ("october", "oct", "октябр[а-яё]*"), 11: ("november", "nov", "ноябр[а-яё]*"),
    12: ("december", "dec", "декабр[а-яё]*"),
}
_MONTH_ALT = "|".join(f"(?P<m{n}>{'|'.join(forms)})" for n, forms in MONTHS.items())
_MON = rf"(?:{_MONTH_ALT})\.?(?![a-zа-яё])"
_DAY = r"(?P<d>\d{1,2})(?:st|nd|rd|th|-?(?:го|е))?(?!\d)"
_YEAR = r"(?P<y>(?:19|20)\d{2})(?!\d)"
_DATE_RES = (
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})-(?P<mn>\d{1,2})(?:-(?P<d>\d{1,2}))?(?!\d)"),
    re.compile(rf"(?<!\d){_DAY}\s(?:of\s)?{_MON}(?:,?\s{_YEAR})?"),
    re.compile(rf"(?<![a-zа-яё]){_MON}\s{_DAY}(?:,?\s{_YEAR})?"),
    re.compile(rf"(?<![a-zа-яё]){_MON},?\s{_YEAR}"),
    re.compile(rf"(?<![\d.,]){_YEAR}(?![.,]\d)"),
)


def _month_of(m):
    for n in MONTHS:
        if m.groupdict().get(f"m{n}"):
            return n
    mn = m.groupdict().get("mn")
    return int(mn) if mn else None


def parse_dates(text):
    """[(year, month, day)] of the dates in a text (a part not said is None):
    "March 25, 2025", "25 March 2025", "Mar 2025", "2025-03-25", "2025",
    "25 марта 2025". A span read as a longer date is not read again as a
    shorter one."""
    t = _plain(text)
    out, taken = [], []
    for rx in _DATE_RES:
        for m in rx.finditer(t):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            month = _month_of(m)
            gd = m.groupdict()
            day = int(gd["d"]) if gd.get("d") else None
            year = int(gd["y"]) if gd.get("y") else None
            if month is not None and not 1 <= month <= 12:
                continue
            if day is not None and not 1 <= day <= 31:
                continue
            taken.append((m.start(), m.end()))
            out.append((year, month, day))
    return out


def date_found(value_date, quote_dates):
    """Is a value's date among a quote's? Every part the value says is the
    quote's ("March 2025" is in "March 25, 2025"; "2025" is in any date of
    2025)."""
    return any(all(v is None or v == q for v, q in zip(value_date, qd)) for qd in quote_dates)


# ------------------------------------------------------------------ names
def _name_words(text):
    return [w[:-2] if w.endswith("'s") else w for w in claims.words(text)]


def name_found(name, quote):
    """Is the name in the quote, word for word (claims.norm; a possessive
    's is the same name)?"""
    n, q = _name_words(name), _name_words(quote)
    return bool(n) and any(q[k:k + len(n)] == n for k in range(len(q) - len(n) + 1))


# ----------------------------------------------------------------- values
def _claims_by_id(claim_list):
    if isinstance(claim_list, dict):
        return {k: v for k, v in claim_list.items() if isinstance(v, dict)}
    return {c["claim_id"]: c for c in claim_list or []
            if isinstance(c, dict) and isinstance(c.get("claim_id"), str)}


def _quotes(claim, pieces):
    """The quotes of a claim's footings - with `pieces` ({id: piece} of the
    topic's support_text), only those that are verbatim in their piece."""
    out = []
    for s in claim.get("support") or []:
        if not (isinstance(s, dict) and isinstance(s.get("quote"), str) and s["quote"].strip()):
            continue
        if pieces is not None:
            rec, code = claims.judge_quote(s, pieces)
            if code or not rec.get("found"):
                continue
        out.append(s["quote"])
    return out


def missing_in(text, kind, quotes):
    """The parts of a value's text that no quote carries: for a `name` the
    name; for a `date` its date (or the words, when it is no date the reader
    knows); otherwise every number and every date in it."""
    if kind == NAME:
        return [] if any(name_found(text, q) for q in quotes) else [text]
    missing = []
    dates = parse_dates(text)
    qdates = [d for q in quotes for d in parse_dates(q)]
    for d in dates:
        if not date_found(d, qdates):
            missing.append("-".join("?" if p is None else str(p) for p in d))
    if kind == DATE:
        if not dates:
            n = claims.norm(text).strip(claims._EDGE_PUNCT)
            if not any(n and n in claims.norm(q) for q in quotes):
                missing.append(text)
        return missing
    qnums = [n for q in quotes for n in parse_numbers(q)]
    for num in parse_numbers(text):
        if not number_found(num, qnums):
            missing.append(num[1] or num[0])
    return missing


def value_problems(graphic, claims_list, pieces=None):
    """The value problems of one well-formed graphic against the script's
    `claims[]` (a list, or {claim_id: claim}): `graphic_value_unbacked` - a
    value with no claim id, an id that is no claim, or a claim that is not
    this graphic's (`where: "graphic:<graphic_id>"`); and
    `graphic_value_not_in_footing` - a number / name / date of the value that
    none of its claims' quotes carries. `pieces` ({id: piece} of the topic's
    support_text) makes a quote count only when it is verbatim in its piece."""
    gid = (graphic or {}).get("graphic_id")
    where = where_of(gid)
    by_id = _claims_by_id(claims_list)
    out = []
    for v in (graphic or {}).get("values") or []:
        if not isinstance(v, dict) or not isinstance(resolve(graphic, v.get("path")), str):
            continue
        ids = v.get("claim_ids") if isinstance(v.get("claim_ids"), list) else []
        ctx = {"path": v.get("path"), "text": v.get("text"), "claim_ids": ids}
        if not ids:
            out.append(_problem(FAIL_VALUE_UNBACKED, gid, f"{v.get('path')}: no claim_ids", **ctx))
            continue
        unknown = [c for c in ids if c not in by_id]
        elsewhere = [c for c in ids if c in by_id and by_id[c].get("where") != where]
        if unknown or elsewhere:
            why = []
            if unknown:
                why.append(f"no claim {unknown}")
            if elsewhere:
                why.append(f"{elsewhere} not `where: {where}`")
            out.append(_problem(FAIL_VALUE_UNBACKED, gid, f"{v.get('path')}: " + "; ".join(why),
                                **ctx))
            continue
        quotes = [q for c in ids for q in _quotes(by_id[c], pieces)]
        spec = field_of(graphic, v["path"]) or {}
        missing = missing_in(v["text"], spec.get("kind", TEXT), quotes)
        if missing:
            out.append(_problem(FAIL_VALUE_NOT_IN_FOOTING, gid,
                                f"{v['path']} {v['text']!r}: {missing} in no quote of "
                                f"{ids}", missing=missing, **ctx))
    return out


def adds_text(graphic):
    """[{path, text}] of every string of `data` that no value names - text
    the template would draw with no claim behind it. An `api_chat` draws
    exactly its `data` strings, each held to the call's record by
    `api_demo.chat_problems` instead (CF-0690): [] for it."""
    if (graphic or {}).get("template") == API_CHAT:
        return []
    named = {v.get("path") for v in (graphic or {}).get("values") or [] if isinstance(v, dict)}
    return [{"path": p, "text": val} for p, val, _ in leaves(graphic)
            if isinstance(val, str) and val.strip() and p not in named]


# ------------------------------------------------------------ viewer text
def caption(graphic, lang=DEFAULT_LANG):
    """The source line of a graphic ("According to Google"), or None."""
    label = (graphic or {}).get("source_label")
    if not (isinstance(label, str) and label.strip()):
        return None
    return SOURCE_CAPTION.get(lang, SOURCE_CAPTION[DEFAULT_LANG]).format(label.strip())


def _s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _pair(a, b):
    a, b = _s(a), _s(b)
    return f"{a}: {b}" if a and b else (a or b)


def viewer_text(graphic, lang=DEFAULT_LANG):
    """What the viewer reads on the frame, one line per item in the order the
    template draws it (": " joins a label to its value, " | " the two sides of
    a comparison), the source line last. A claim of the graphic copies its
    `text` from here."""
    g = graphic if isinstance(graphic, dict) else {}
    d = g.get("data") if isinstance(g.get("data"), dict) else {}
    t = g.get("template")

    def rows(key):
        return [r for r in d.get(key) or [] if isinstance(r, dict)]

    lines = []
    if t == "spec_card":
        lines = [_s(d.get("product"))] + [_pair(r.get("label"), r.get("value")) for r in rows("rows")]
    elif t == "comparison":
        lines = [" | ".join(x for x in (_s(d.get("left")), _s(d.get("right"))) if x)]
        for r in rows("rows"):
            sides = " | ".join(x for x in (_s(r.get("left")), _s(r.get("right"))) if x)
            lines.append(_pair(r.get("label"), sides))
    elif t == "price_date":
        lines = [_s(d.get(k)) for k in ("product", "price", "date", "note")]
    elif t == "benchmark":
        lines = [_s(d.get("metric"))] + [_pair(r.get("name"), r.get("score")) for r in rows("rows")]
    elif t == "timeline":
        lines = [_pair(r.get("date"), r.get("label")) for r in rows("events")]
    elif t == "how_it_works":
        lines = [_s(d.get("title"))] + [_s(x) for x in d.get("steps") or []]
    elif t == API_CHAT:
        # the label line, the prompt line, the answer line - each as written
        lines = [_s(d.get("model_label")), _s(d.get("prompt")), _s(d.get("answer"))]
    lines.append(caption(g, lang))
    return "\n".join(x for x in lines if x)


def viewer_texts(script, lang=DEFAULT_LANG):
    """{"graphic:<graphic_id>": viewer_text} of a script's graphics with a
    well-formed id (the first of a repeated id). Every graphic, `api_chat`
    included; the claim rule leaves the chats out itself
    (`claims.api_chat_wheres`, CF-0690)."""
    out = {}
    for g in graphics_of(script):
        gid = g.get("graphic_id") if isinstance(g, dict) else None
        if isinstance(gid, str) and GRAPHIC_ID_RE.match(gid) and where_of(gid) not in out:
            text = viewer_text(g, lang)
            if text:
                out[where_of(gid)] = text
    return out


# ------------------------------------------------------------------ check
def chat_problems(graphic, protocols=None, config=None):
    """CF-0690: an `api_chat` graphic against the record of its call -
    `api_demo.chat_problems` with the protocol its `record_id` names in
    `protocols` ({record_id: protocol}; None - the caller handed none, so
    there is no record), and its `data.date`, when there is one, the day the
    call was answered (`graphic_value_not_in_footing` otherwise)."""
    g = graphic if isinstance(graphic, dict) else {}
    protocol = (protocols or {}).get(g.get("record_id")) if g.get("record_id") else None
    out = api_demo.chat_problems(g, protocol, config)
    date = (g.get("data") or {}).get("date") if isinstance(g.get("data"), dict) else None
    if protocol is not None and isinstance(date, str) and date.strip():
        answered = parse_dates(str(protocol.get("answered_at") or "")[:10])
        said = parse_dates(date)
        if not said or not all(date_found(d, answered) for d in said):
            out.append(_problem(FAIL_VALUE_NOT_IN_FOOTING, g.get("graphic_id"),
                                f"data.date {date!r} is not the day the call was answered "
                                f"({protocol.get('answered_at')!r})", path="data.date",
                                text=date))
    return out


def check_graphics(script, pieces=None, protocols=None, config=None):
    """Every problem of a script's `graphics[]` (placement is the Content
    Researcher's own `graphic_not_placed`): the order of each, its values
    against `claims[]` (a graphic that is not well formed is not read
    further) and the text it would add. [] - all of them stand.

    CF-0690: an `api_chat` is held to its call's record instead
    (`chat_problems`): `protocols` - {record_id: protocol} of the topic's
    `api_demo_record` (`api_demo.protocols_by_record`) - and `config` - the
    channel's `api_demo` block. Without `protocols` every chat has no record."""
    out = []
    raw = (script or {}).get(GRAPHICS_FIELD)
    if raw is None:
        return out
    if not isinstance(raw, list):
        return [_problem(FAIL_MALFORMED, None, f"`{GRAPHICS_FIELD}` is {type(raw).__name__}, "
                                               f"not a list")]
    claim_list = (script or {}).get(claims.CLAIMS_FIELD)
    seen = set()
    for g in raw:
        order = order_problems(g, config)
        gid = g.get("graphic_id") if isinstance(g, dict) else None
        if isinstance(gid, str) and gid in seen:
            order.insert(0, _problem(FAIL_MALFORMED, gid, f"graphic_id {gid!r} twice"))
        seen.add(gid)
        out += order
        if any(p["code"] in (FAIL_MALFORMED, FAIL_UNKNOWN_TEMPLATE) for p in order):
            continue
        if g.get("template") == API_CHAT:
            out += chat_problems(g, protocols, config)
            continue
        out += value_problems(g, claim_list, pieces)
        for leaf in adds_text(g):
            out.append(_problem(FAIL_ADDS_TEXT, gid, f"{leaf['path']} {leaf['text']!r} is no value",
                                path=leaf["path"], text=leaf["text"]))
    return out


def codes(problems):
    return [p.get("code") for p in problems or []]
