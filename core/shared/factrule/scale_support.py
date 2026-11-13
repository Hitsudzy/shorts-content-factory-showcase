#!/usr/bin/env python3
"""CF-0673: the footing of a `scale` comparison's two other numbers - the
reference it is scaled against and the familiar stand-in's own size - as
pieces of the topic's support text.

**The defect** (found by CF-0565's worker, 10.10). A scale script declares
its comparison in `claims[]` with a quote for each of three numbers: the
video's fact (the quantity), the reference (the Sun's diameter, when the Sun
becomes a grapefruit) and the familiar size (a grapefruit, 10 to 15 cm). The
claim rule (`claims.py`) takes a quote only from a piece of the topic's
`support_text`, and the Trend Hunter's text is the topic's own - the work's
article, its news - so the Sun's and the grapefruit's numbers were never in
it: every scale script would leave as `claim_unsupported`
(`source_not_in_support_text`). Safe, and the pattern dead.

**The choice** (variant A of the task, the driver's decision of 10.10, by
the rule «no invented facts»): the missing text is *read*, not trusted. This
step takes the stand-ins the writer means to use - each with its
`source_url` - reads that page through the channel's door, and keeps the
passage where the number stands as it is written; that passage becomes a
piece of support text like any other. The claim rule stays what it was -
offline, a quote is good only when it is verbatim in a piece - and a number
the page does not carry gets no piece, so the writer has to change the
stand-in (`patterns/scale.json`: «change the stand-in, never the number»).
Variant B (`claims.py` takes `script.scale.*` as footing after a check
against the page) was not taken: it would put the network into the claim
rule and let a quote the writer typed stand as footing.

**Where the pieces go: an explicit continuation of the topic's support
text.** The stand-ins are the writer's choice, so the step runs at the
Content Researcher, after `01-trend-hunter.json` is written by another stage;
the pieces go to `<batch>/01-scale-support.json`
(`CONTINUATION_FILE`, `attach`) and `claims.topics_of` - the one reader of
topics every claim check goes through (`claims.check_batch_file`,
`claim_judge`, the Researcher's `check_claims.py`) - appends them to the
topic's `support_text`. The 01 is never rewritten.

**What this module does not do: the network.** Everything that leaves the
machine is handed in:

    gate(url)        raises when the URL may not be read - the channel's door
                     (`channel_gate(sources)` below, or the hunter's
                     `source_gate.check` bound to the list); called before
                     every read, and a step without a gate reads nothing;
    read_page(url)   -> {"title", "url", "text", "source", "revision_id",
                     "revised_at"} with `text` the page as plain text, None
                     when there is no such page; raises when it cannot be
                     reached. `wikipedia_reader(client)` builds one over the
                     factory's Wikipedia client and `wikipedia_api.
                     plain_text` - the plain text that unwraps `{{val}}` and
                     `{{convert}}` into «N UNIT» / «A to B UNIT», so the
                     number survives (the Sun's diameter, the grapefruit's
                     size are written in those templates).

**Which pages may be read.** Only an outlet of the channel's own
`fact-sources.json` with `use: read_text` and `ai_policy.verdict: allowed`
(the rule of 08.10, CF-0635: closed only when robots.txt closes it to
Anthropic's bots or to every agent, or its terms forbid AI use - a person
records those as `forbidden`). `channel_gate` asks the root's own pieces of
that rule - `fact_rule.source_of` finds the outlet, `channel_data.
entry_policy_errors` with `TEXT_USES` judges it - exactly as the hunter's
`source_gate.refusal` does; it keeps no copy of the rule. For example-science
that is Wikipedia alone today (NASA, ESA, the journals are `cite_only`).

API:

    channel_gate(sources)                          -> gate(url)
    wikipedia_reader(client, to_text=None)         -> read_page(url)
    gather(requests, read_page, gate, existing=()) -> {"pieces", "requests"}
    attach(batch_dir, topic_id, result)            -> path of the continuation
    continuation_of(batch_dir)                     -> {topic_id: {...}}
    merged_support(topic, entry)                   -> support_text with the pieces

A request is `{"part": "reference" | "familiar", "name", "source_url",
"value", "unit"}` (the shape of `script.scale.<part>` before its quote is
written) and may carry `quote` instead of / as well as the value: then the
passage is the one that holds that quote verbatim. A request's outcome is one
of `STATES`; only `ok` names a piece (`piece_id`).

Stdlib only, no network, loadable by path from any repository.
"""
import importlib.util
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

RULE = "CF-0673"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

CONTINUATION_FILE = "01-scale-support.json"   # = claims.SCALE_SUPPORT_FILE
SUPPORT_KEY = "support_text"            # = claims / trend-hunter support_text.SUPPORT_KEY
REQUESTS_KEY = "requests"
PIECE_KIND = "scale_reference"
PIECE_ID_PREFIX = "scale"
PARTS = ("reference", "familiar")       # = validate_patterns.SCALE_PARTS minus the quantity

STATE_OK = "ok"                         # the number (or quote) stands on the page: a piece
STATE_CLOSED = "closed"                 # the channel's door refused the URL - nothing read
STATE_NO_GATE = "no_gate"               # no door handed in - nothing read
STATE_NO_PAGE = "no_page"               # the page does not exist
STATE_UNREACHABLE = "unreachable"       # the page could not be read
STATE_NOT_ON_PAGE = "not_on_page"       # read, and the number is not written there
STATE_MALFORMED = "malformed"           # the request lacks its URL, or a value / quote
STATES = (STATE_OK, STATE_CLOSED, STATE_NO_GATE, STATE_NO_PAGE, STATE_UNREACHABLE,
          STATE_NOT_ON_PAGE, STATE_MALFORMED)

MAX_PASSAGES = 3                        # paragraphs kept per request
WIKIPEDIA_SOURCE = "wikipedia"
WIKIPEDIA_HOST_RE = re.compile(r"^(?:[a-z-]+\.)?(?:m\.)?wikipedia\.org$")

# How a unit of `validate_patterns.SCALE_UNITS` is written in running text.
UNIT_WORDS = {
    "mm": ("mm", "millimetre", "millimetres", "millimeter", "millimeters"),
    "cm": ("cm", "centimetre", "centimetres", "centimeter", "centimeters"),
    "m": ("m", "metre", "metres", "meter", "meters"),
    "km": ("km", "kilometre", "kilometres", "kilometer", "kilometers"),
    "au": ("au", "astronomical unit", "astronomical units"),
    "light-year": ("light-year", "light-years", "light year", "light years", "ly"),
    "ly": ("light-year", "light-years", "light year", "light years", "ly"),
    "s": ("s", "second", "seconds", "sec"),
    "min": ("min", "minute", "minutes"),
    "h": ("h", "hour", "hours", "hr"),
    "day": ("day", "days"),
    "year": ("year", "years", "yr"),
    "g": ("g", "gram", "grams", "gramme", "grammes"),
    "kg": ("kg", "kilogram", "kilograms", "kilogramme", "kilogrammes"),
    "t": ("t", "tonne", "tonnes", "ton", "tons", "metric ton", "metric tons"),
    "m/s": ("m/s", "metres per second", "meters per second"),
    "km/s": ("km/s", "kilometres per second", "kilometers per second"),
    "km/h": ("km/h", "kilometres per hour", "kilometers per hour", "kph"),
}
NUMBER_REL = 0.005                      # = validate_patterns._number_in_quote's tolerance


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


claims = _load("factory_claims_cf0552", HERE / "claims.py")
# CF-0737: where a sentence ends - the factory's one reading (the same module
# object `fact_rule` loads, keyed by its path).
sentences = _load("factory_sentences_cf0737@" + str(HERE / "sentences.py"), HERE / "sentences.py")


def _vp():
    """The pattern rule's number reader (`numbers_in`, digits and words) - one
    reading of a number for the record's check and for this passage search."""
    return _load("factory_validate_patterns_cf0673", ROOT / "patterns" / "validate_patterns.py")


# --------------------------------------------------------------- the door
# The words that end the refusal of an empty list: a reader of the log learns
# why nothing at all was read (the hunter's `source_gate` wording since
# CF-0634, moved here so the hunter keeps no wrapper of its own).
NO_LIST_TAIL = " - no outlet is readable without one"


def channel_gate(sources):
    """`gate(url)` over the channel's fact-sources list: raises
    `PermissionError` with the reason unless the outlet is listed with `use:
    read_text` and `ai_policy.verdict: allowed`. The root's own rule
    (`fact_rule.source_of`, `channel_data.entry_policy_errors`), asked the way
    the hunter's `source_gate.refusal` asks it."""
    fact_rule = _load("factory_fact_rule_cf0673", HERE / "fact_rule.py")
    channel_data = _load("factory_channel_data_cf0673", ROOT / "shared" / "channel_data.py")

    def refusal(url):
        if not sources:
            return f"{url}: no fact-sources list of the channel was given{NO_LIST_TAIL}"
        where = fact_rule.source_of(url, sources)
        if not where["host"]:
            return f"{url!r} is not a URL with a host"
        if where["banned"]:
            return f"{where['host']}: the channel's list does not take it ({where['banned']})"
        row = None
        for r in ((sources.get("tiers") or {}).get(str(where["tier"])) or []
                  if where["tier"] is not None else []):
            if isinstance(r, dict) and r.get("id") == where["id"]:
                row = r                     # the first row of that id, as the hunter's door had it
                break
        if row is None:
            return (f"{where['host']}: not an outlet of the channel's fact-sources list - "
                    f"an outlet is read only when the list names it with `use: read_text`")
        errs = channel_data.entry_policy_errors(row, f"outlet {row.get('id')}",
                                                channel_data.TEXT_USES)
        return "; ".join(errs) if errs else None

    def gate(url):
        why = refusal(url)
        if why:
            raise PermissionError(why)

    gate.refusal = refusal
    return gate


# ------------------------------------------------------------- the reader
def wikipedia_title(url):
    """`https://en.wikipedia.org/wiki/Grapefruit#Description` -> "Grapefruit";
    None for a URL that is not an English Wikipedia article."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not WIKIPEDIA_HOST_RE.match(host) or not host.startswith(("en.", "en.m.")):
        return None
    if not parts.path.startswith("/wiki/"):
        return None
    title = urllib.parse.unquote(parts.path[len("/wiki/"):]).replace("_", " ").strip()
    return title or None


def wikipedia_api():
    """The factory's one Wikipedia module, under its one `sys.modules` name
    (`wikipedia_api.MODULE_NAME`, CF-0551)."""
    path = (ROOT / "shared" / "wikipedia" / "wikipedia_api.py").resolve()
    held = sys.modules.get("factory_wikipedia_api")
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    sys.modules.pop("factory_wikipedia_api", None)
    return _load("factory_wikipedia_api", path)


def wikipedia_reader(client, to_text=None):
    """`read_page(url)` over the factory's Wikipedia client
    (`shared/wikipedia/wikipedia_api.WikipediaClient` or its cached form).
    The text is `wikipedia_api.plain_text` unless the caller hands in its own
    (CF-0673: it keeps the numbers `{{val}}` / `{{convert}}` write - a reader
    that strips every template loses the very number this step looks for). A
    URL that is not an English Wikipedia article is no page of this reader."""
    if to_text is None:
        to_text = wikipedia_api().plain_text

    def read_page(url):
        title = wikipedia_title(url)
        if not title:
            return None
        article = client.page(title)
        if not article:
            return None
        return {"title": article.get("title"), "url": article.get("url"),
                "source": WIKIPEDIA_SOURCE, "revision_id": article.get("revision_id"),
                "revised_at": article.get("revised_at"),
                "text": to_text(article.get("wikitext") or "")}
    return read_page


# ------------------------------------------------------------ the passage
_HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")
# The gap between two sentences of a passage; a stop of an abbreviation or an
# initial («Example Studios», «J. K. Rowling») is not one (CF-0737,
# `sentences.split_at`).
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _paragraphs(text):
    """[(heading lines above it, paragraph)] of a plain-text page; the
    headings are `== Heading ==` lines as the hunter's plain text keeps them."""
    out, path = [], []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _HEADING_RE.match(s)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, s)]
            continue
        out.append(([h for _, h in path], s))
    return out


def _unit_in(sentence, unit):
    words = UNIT_WORDS.get(unit) or (unit,)
    low = sentence.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in words)


def _number_stands(value, unit, paragraph):
    """Does one sentence of the paragraph write `value` (digits or words, at
    the record check's own tolerance) together with its unit?"""
    numbers_in = _vp().numbers_in
    for sentence in sentences.split_at(paragraph, _SENTENCE_RE):
        if any(abs(n - value) <= NUMBER_REL * max(abs(value), 1e-12)
               for n in numbers_in(sentence)) and (not unit or _unit_in(sentence, unit)):
            return True
    return False


def _malformed(req):
    if not isinstance(req, dict):
        return "a request is an object"
    if not str(req.get("source_url") or "").strip():
        return "a request needs its `source_url`"
    has_quote = bool(str(req.get("quote") or "").strip())
    v = req.get("value")
    has_value = isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    if not (has_quote or has_value):
        return "a request needs a positive `value` (with its `unit`) or a `quote`"
    return None


def passages(page_text, req):
    """The paragraphs of the page that carry the request: the one holding its
    `quote` verbatim (normalised as the claim rule does), else those where
    its value stands with its unit - at most MAX_PASSAGES, each with the
    headings above it."""
    paras = _paragraphs(page_text)
    quote = str(req.get("quote") or "").strip()
    found = []
    if quote:
        q = claims.norm_quote(quote)
        found = [p for p in paras if q and q in claims.norm(p[1])]
        v = req.get("value")
        if found and isinstance(v, (int, float)) and not isinstance(v, bool):
            numbers_in = _vp().numbers_in
            if not any(abs(n - v) <= NUMBER_REL * max(abs(v), 1e-12)
                       for n in numbers_in(quote)):
                return []          # the quote is on the page but does not say the number
    else:
        found = [p for p in paras if _number_stands(req["value"], req.get("unit"), p[1])]
    return found[:MAX_PASSAGES]


def _piece_text(found):
    lines, last_heads = [], None
    for heads, para in found:
        if heads != last_heads:
            lines.extend(heads)
            last_heads = heads
        lines.append(para)
    return "\n".join(lines)


def piece_id(page):
    key = (page.get("url") or "").rsplit("/wiki/", 1)[-1] if page.get("url") else page.get("title")
    return f"{PIECE_ID_PREFIX}:{page.get('source') or 'page'}:{key}"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- the step
def gather(requests, read_page, gate, existing=()):
    """Read each request's page through `gate` and keep the passage where its
    number stands. Returns `{"pieces": [...], "requests": [...]}`: one piece
    per page read (its passages for every request that found one), and one
    outcome per request (`STATES`; `piece_id` on `ok`).

    `existing` is the topic's support text so far: a page whose piece is
    already there (the hunter read it, or an earlier run of this step) and
    already carries the passage is not read again - the request names that
    piece."""
    existing = [p for p in existing or () if isinstance(p, dict)]
    pages, pieces, outcomes = {}, {}, []
    for req in requests or []:
        why = _malformed(req)
        out = {"part": (req or {}).get("part") if isinstance(req, dict) else None,
               "name": (req or {}).get("name") if isinstance(req, dict) else None,
               "source_url": (req or {}).get("source_url") if isinstance(req, dict) else None,
               "value": (req or {}).get("value") if isinstance(req, dict) else None,
               "unit": (req or {}).get("unit") if isinstance(req, dict) else None,
               "state": None, "piece_id": None, "detail": None}
        outcomes.append(out)
        if why:
            out.update(state=STATE_MALFORMED, detail=why)
            continue
        url = req["source_url"].strip()
        held = next((p for p in existing
                     if p.get("url") and p["url"].split("#")[0] == url.split("#")[0]
                     and passages(p.get("text") or "", req)), None)
        if held is not None:
            out.update(state=STATE_OK, piece_id=held.get("id"),
                       detail="already in the topic's support text")
            continue
        if gate is None:
            out.update(state=STATE_NO_GATE,
                       detail="no gate was handed in - a page is read only through the "
                              "channel's door")
            continue
        try:
            gate(url)
        except Exception as error:          # the door's refusal, whatever its class
            out.update(state=STATE_CLOSED, detail=str(error))
            continue
        key = url.split("#")[0]
        if key not in pages:
            try:
                pages[key] = read_page(url)
            except Exception as error:
                pages[key] = error
        page = pages[key]
        if isinstance(page, Exception):
            out.update(state=STATE_UNREACHABLE, detail=f"{type(page).__name__}: {page}")
            continue
        if not page or not page.get("text"):
            out.update(state=STATE_NO_PAGE, detail=f"{url}: no such page, or no text on it")
            continue
        found = passages(page["text"], req)
        if not found:
            what = (f"the quote {req['quote']!r}" if req.get("quote")
                    else f"{req['value']:g} {req.get('unit') or ''}".strip())
            out.update(state=STATE_NOT_ON_PAGE,
                       detail=f"{what} is not written on {page.get('url') or url} - change "
                              f"the stand-in, never the number")
            continue
        pid = piece_id(page)
        piece = pieces.get(pid)
        if piece is None:
            piece = pieces[pid] = {
                "id": pid, "kind": PIECE_KIND, "source": page.get("source"),
                "title": page.get("title"), "url": page.get("url") or url,
                "revision_id": page.get("revision_id"), "revised_at": page.get("revised_at"),
                "fetched_at": _now(), "rule": RULE, "_found": []}
        for f in found:
            if f not in piece["_found"]:
                piece["_found"].append(f)
        out.update(state=STATE_OK, piece_id=pid)
    for piece in pieces.values():
        piece["text"] = _piece_text(piece.pop("_found"))
    return {"pieces": list(pieces.values()), "requests": outcomes}


# -------------------------------------------------------- the continuation
def continuation_path(batch_dir):
    return Path(batch_dir) / CONTINUATION_FILE


def continuation_of(batch_dir):
    """{topic_id: {"support_text": [...], "requests": [...]}} of the batch's
    continuation file; {} when there is none or it cannot be read."""
    try:
        data = json.loads(continuation_path(batch_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    topics = data.get("topics") if isinstance(data, dict) else None
    return {k: v for k, v in (topics or {}).items() if isinstance(v, dict)}


def attach(batch_dir, topic_id, result):
    """Write `gather`'s result for one topic into the batch's continuation:
    its pieces replace those of the same id, its request outcomes are
    appended. Returns the path."""
    path = continuation_path(batch_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["rule"] = RULE
    topics = data.setdefault("topics", {})
    entry = topics.setdefault(str(topic_id), {})
    pieces = [p for p in entry.get(SUPPORT_KEY) or [] if isinstance(p, dict)]
    new = {p["id"]: p for p in result.get("pieces") or []}
    pieces = [new.pop(p.get("id")) if p.get("id") in new else p for p in pieces]
    pieces.extend(new.values())
    entry[SUPPORT_KEY] = pieces
    entry[REQUESTS_KEY] = (entry.get(REQUESTS_KEY) or []) + list(result.get("requests") or [])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def merged_support(topic, entry):
    """The topic's support text with the continuation's pieces after it - a
    piece whose id the topic already has is not added twice."""
    base = list((topic or {}).get(SUPPORT_KEY) or [])
    ids = {p.get("id") for p in base if isinstance(p, dict)}
    for p in (entry or {}).get(SUPPORT_KEY) or []:
        if isinstance(p, dict) and p.get("id") and p["id"] not in ids:
            base.append(p)
            ids.add(p["id"])
    return base
