#!/usr/bin/env python3
"""CF-0690 (TH step of the root's docs/tech-footage.md «API demo») - "a demo
via API": the topic's own model, asked one of the channel's approved neutral
prompts through the Gemini API free tier, its verbatim answer kept as the
topic's `api_demo_record` - the footing of an `api_chat` graphic the script
may order (the CF-0689 own-graphic path). **The answer is never a fact.**

Why. The user's decision of 2026-10-12 (Q30; the paid way refused): a
ExampleTech story about a new model may show that model's real answer to a
neutral prompt, drawn in the factory's own chat animation and labelled
"<model> · via API". The frame is held to the record of the real call
(root `shared/api_demo.py` `chat_problems`), so the record is made here, at
topic time, once.

For every topic of a channel whose footage origins name `api_demo` (ExampleFilm
and ExampleScience: "nothing to ask", nothing written) this script

  1. **matches the topic's model** - `title_ref.tool` / `model` / `name`, then
     `aliases` (`forms_of`) - against the channel's list (`api_demo.models[]`,
     `id` and `matches`, through the root's `api_demo.display_name_for`, the
     same reading the frame's label gets: a version suffix allowed, the longest
     match wins, a leading "Google"/"DeepMind" dropped). A topic whose model
     is not on the list gets no call - a GPT topic never gets a Gemini demo;
     the first form that names a listed model decides (`model_for`);
  2. **refuses to call while the prompts are not approved**: the user
     approves the list (Q33). Approved = the block's `prompts_approved: true`
     or this script's `--prompts-approved`; anything else - the block's
     `prompts_note` "awaiting the user's approval" included - is a note
     `prompts_not_approved` and no call;
  3. **picks a prompt** of `api_demo.prompts[]`, deterministic per topic
     (`pick_prompt`: sha256 of the topic id) - a rerun asks the same;
  4. **reads the cache** `<batch>/work/api_demo/api-demo-<topic>.json`: a call
     that was answered (`ok` or `refused`) with the same model and a prompt
     still on the list is never made again - not for a nicer answer, not on a
     rerun. A `skipped` protocol (no key, rate limited, unavailable) was not
     answered and is asked again next time;
  5. **asks** (`gemini_api.GeminiClient(min_interval=min_interval_seconds,
     timeout=timeout_seconds)`, serial) - at most `max_calls_per_batch` calls
     that reached the API per batch - the topics whose cache file says
     `called`, earlier runs included (`--max-calls` may lower it, never raise
     it); a `rate_limited` answer stops the pass for the batch (the free tier's
     quota is spent), the rest of the topics get a note;
  6. **keeps** `topic["api_demo_record"] = {"record_id": "api-demo-<topic>",
     "protocol": <the protocol>}` for an `ok` call whose protocol is whole
     (`api_demo.protocol_problems`) and whose `modelVersion` the channel's list
     reads as the model asked (`display_name_for`) - nothing else. Skipped
     (no key: `NO_KEY_REASON`), refused (SAFETY, RECITATION, a refusal phrase,
     citation metadata ...), a `GeminiError` or a model the API answered as
     another: no record (an old one is taken off), a note, never a failed
     batch. Every topic gets `evidence.api_demo_read` (`status`, `model`,
     `display_name`, `prompt`, `record_id`, `cached`, `called`, `skip_reason`,
     `note`).

When the topic already has `support_text` (step 5a), the record's
`api_demo_record` piece is merged into it here too (`api_demo_text.merge`);
`footage_candidates.py` (step 5b) merges it again, idempotently.

**The key** is the client's business (`GEMINI_API_KEY` from the environment,
else `<factory root>/.env`); only `key_source` ("environment" | ".env" | None)
is ever printed - never the key, never in the record, the cache or a note.

Usage (from the agent root):
  scripts/fetch_api_demo.py --batch <batch-dir> [--topic <id>] [--prompts-approved] \\
      [--max-calls N]
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _api_demo import api_demo as _rule, gemini_api as _client  # noqa: E402
from _footage_licence import footage_licence  # noqa: E402
from _runlog import runlog  # noqa: E402
import api_demo_text  # noqa: E402
import footage_origin  # noqa: E402

SOURCE = "api_demo"
RECORD_FIELD = "api_demo_record"            # = root api_demo.RECORD_FIELD
READ_KEY = "api_demo_read"                  # evidence of what this pass did per topic
APPROVED_KEY = "prompts_approved"
ID_HEAD = "api-demo-"
WORK_DIR = Path("work") / "api_demo"
ANSWERED = ("ok", "refused")                # a protocol of a call the API answered
LEADING_VENDOR = {"google", "googles", "s", "deepmind", "google deepmind"}
TOOL_NAME = "shorts-content-factory-trend-hunter"

# The notes' codes - what `evidence.api_demo_read.status` says.
OK = "ok"
NOT_LISTED = "model_not_listed"
NOT_APPROVED = "prompts_not_approved"
NO_BLOCK = "no_api_demo_block"
NO_CLIENT = "no_client"
CAP_SPENT = "cap_spent"
STOPPED = "stopped"
SKIPPED = "skipped"
REFUSED = "refused"
MODEL_MISMATCH = "model_version_mismatch"
BAD_PROTOCOL = "bad_protocol"
ERROR = "error"


def slug(topic_id):
    """A topic id as the record id's tail: lower case, [a-z0-9_-] only."""
    s = re.sub(r"[^a-z0-9_-]+", "-", str(topic_id or "").lower()).strip("-_")
    return s or "topic"


def record_id(topic_id):
    return f"{ID_HEAD}{slug(topic_id)}"


def forms_of(title_ref):
    """The topic's names of its model: `tool`, `model`, `name`, then
    `aliases` - distinct, in that order (`fetch_own_capture.queries_of`'s
    reading without `subjects`, which name fields, not the model)."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    out, seen = [], set()
    for f in [ref.get("tool"), ref.get("model"), ref.get("name")] + \
            list(ref.get("aliases") or []):
        f = str(f or "").strip()
        if f and f.casefold() not in seen:
            seen.add(f.casefold())
            out.append(f)
    return out


def _clean(form):
    """A form as `display_name_for` reads a modelVersion: its words, a
    leading vendor ("Google's", "DeepMind") off."""
    words = re.findall(r"[0-9a-z]+(?:\.[0-9a-z]+)*", str(form or "").lower().replace("’", "'"))
    while words and words[0] in LEADING_VENDOR:
        words = words[1:]
    return " ".join(words)


def model_for(title_ref, block, rule=None):
    """-> (the `models[]` entry of the topic's model, the form that named it)
    or (None, None). The same reading as the frame's label: the root's
    `api_demo.display_name_for` over the channel's list."""
    rule = rule if rule is not None else _rule
    if rule is None or not isinstance(block, dict):
        return None, None
    models = [m for m in block.get("models") or [] if isinstance(m, dict)]
    for form in forms_of(title_ref):
        cleaned = _clean(form)
        if not cleaned:
            continue
        name = rule.display_name_for(cleaned, block)
        if name:
            for m in models:
                if m.get("display_name") == name:
                    return m, form
    return None, None


def prompts_approved(block, flag=False):
    """-> (approved, why). Approved only by the user: the block's
    `prompts_approved: true`, or `--prompts-approved` on this run."""
    if flag:
        return True, "--prompts-approved on this run"
    if (block or {}).get(APPROVED_KEY) is True:
        return True, f"api_demo.{APPROVED_KEY}: true"
    note = (block or {}).get("prompts_note")
    return False, ("the channel's prompts are not approved"
                   + (f" (prompts_note: {note!r})" if note else "")
                   + f" - the user approves the list (api_demo.{APPROVED_KEY}: true or "
                     f"--prompts-approved); no call")


def pick_prompt(topic_id, prompts):
    """One of `prompts`, the same for the same topic on every run."""
    prompts = [p for p in prompts or [] if isinstance(p, str) and p.strip()]
    if not prompts:
        return None
    h = int(hashlib.sha256(str(topic_id).encode("utf-8")).hexdigest(), 16)
    return prompts[h % len(prompts)]


def cache_path(work_dir, topic_id):
    return Path(work_dir) / f"{record_id(topic_id)}.json"


def read_cache(path, model_id, prompts):
    """The protocol of an answered call kept for this topic, when it asked
    the same model a prompt still on the list; else None."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    proto = (doc or {}).get("protocol")
    if not isinstance(proto, dict) or proto.get("status") not in ANSWERED:
        return None
    if proto.get("model_requested") != model_id or proto.get("prompt") not in (prompts or []):
        return None
    return proto


def write_cache(path, topic_id, proto, called):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"record_id": record_id(topic_id), "topic_id": topic_id,
                                "source": SOURCE, "called": bool(called), "protocol": proto},
                               ensure_ascii=False, indent=2) + "\n")


def calls_on_record(work_dir):
    """How many topics of this batch already have a call that reached the API
    (an earlier run of this script): they count against the batch's cap, so
    a rerun never asks past it."""
    n = 0
    for p in Path(work_dir).glob(f"{ID_HEAD}*.json"):
        try:
            n += bool(json.loads(p.read_text()).get("called"))
        except (OSError, ValueError, AttributeError):
            continue
    return n


def block_problems(block):
    """Why the channel's `api_demo` block may not be used ([] when it may):
    the root's `footage_licence.api_demo_errors`, when the rule is there."""
    if not isinstance(block, dict):
        return ["the channel's footage-origin.json has no `api_demo` block"]
    if footage_licence is None or not hasattr(footage_licence, "api_demo_errors"):
        return []
    return list(footage_licence.api_demo_errors({"api_demo": block}))


class Budget:
    """The batch's calls: `max_calls_per_batch` that reached the API."""

    def __init__(self, calls, spent_before=0):
        self.calls = max(0, int(calls))
        self.before = max(0, int(spent_before))
        self.spent = 0
        self.stopped = None

    def left(self):
        return self.calls - self.before - self.spent


def _read(topic_id, **kw):
    out = {"record_id": record_id(topic_id), "status": None, "model": None,
           "display_name": None, "prompt": None, "cached": False, "called": False,
           "key_source": None, "skip_reason": None, "note": None}
    out.update(kw)
    return out


def topic_demo(topic, block, client, *, work_dir, budget, approved, rule=None):
    """One topic: -> (the record or None, `evidence.api_demo_read`)."""
    rule = rule if rule is not None else _rule
    tid = topic.get("topic_id")
    model, form = model_for(topic.get("title_ref") or {}, block, rule)
    if model is None:
        return None, _read(tid, status=NOT_LISTED,
                           note="the topic's model is not on the channel's api_demo list - "
                                "no call (a demo only ever shows the topic's own model)")
    base = dict(model=model["id"], display_name=model["display_name"])
    if not approved[0]:
        return None, _read(tid, status=NOT_APPROVED, note=approved[1], **base)
    prompts = list(block.get("prompts") or [])
    prompt = pick_prompt(tid, prompts)
    base["prompt"] = prompt
    path = cache_path(work_dir, tid)
    proto = read_cache(path, model["id"], prompts)
    cached = proto is not None
    called = False
    if proto is None:
        if budget.stopped:
            return None, _read(tid, status=STOPPED, note=budget.stopped, **base)
        if budget.left() <= 0:
            return None, _read(tid, status=CAP_SPENT,
                               note=f"the batch's {budget.calls} call(s) are spent "
                                    f"(api_demo.max_calls_per_batch) - no call", **base)
        before = getattr(client, "request_count", 0)
        had_call = _had_call(path)
        try:
            proto = client.ask(model["id"], prompt)
        except Exception as exc:  # noqa: BLE001 - GeminiError (400/401/403/404/transport)
            if not had_call:
                budget.spent += 1
            return None, _read(tid, status=ERROR, called=True,
                               key_source=_safe_key_source(client),
                               note=f"the API could not be asked: {exc} - no demo", **base)
        called = getattr(client, "request_count", 0) > before
        if called and not had_call:
            budget.spent += 1
        write_cache(path, tid, proto, called or had_call)
        if proto.get("status") == SKIPPED and proto.get("skip_reason") == \
                getattr(_client, "RATE_LIMITED", "rate_limited"):
            budget.stopped = ("the Gemini API rate-limited this batch (the free tier's quota) - "
                              "no more calls in this pass")
    read = _read(tid, cached=cached, called=called, key_source=proto.get("key_source"),
                 skip_reason=proto.get("skip_reason"), **base)
    status = proto.get("status")
    if status == SKIPPED:
        read.update(status=SKIPPED, note=f"call skipped: {proto.get('skip_reason')} - no demo")
        return None, read
    if status == REFUSED:
        read.update(status=REFUSED, note=f"answer refused: {proto.get('skip_reason')} - no demo")
        return None, read
    problems = rule.protocol_problems(proto)
    if problems:
        read.update(status=BAD_PROTOCOL, note="the protocol is not whole: " + "; ".join(problems))
        return None, read
    shown = rule.display_name_for(proto.get("model_version"), block)
    if shown != model["display_name"]:
        read.update(status=MODEL_MISMATCH,
                    note=f"the API answered as {proto.get('model_version')!r}, which the "
                         f"channel's list reads as {shown!r}, not {model['display_name']!r} - "
                         f"no demo")
        return None, read
    read.update(status=OK, note=f"{model['display_name']} answered (record {read['record_id']}"
                                + (", from the cache" if cached else "") + ") - never a fact")
    return {"record_id": record_id(tid), "protocol": proto}, read


def _had_call(path):
    """Whether the topic's cache file records a call that reached the API
    (a `skipped` one - rate limited, unavailable - asked again counts once)."""
    try:
        return bool(json.loads(Path(path).read_text()).get("called"))
    except (OSError, ValueError, AttributeError):
        return False


def _safe_key_source(client):
    try:
        return client.key_source()
    except Exception:  # noqa: BLE001
        return None


def make_client(block, log=None):
    """The factory's Gemini client with the block's interval and timeout."""
    return _client.GeminiClient(min_interval=float(block.get("min_interval_seconds") or
                                                   _client.MIN_INTERVAL_SECONDS),
                                timeout=block.get("timeout_seconds") or _client.DEFAULT_TIMEOUT,
                                tool_name=TOOL_NAME, log=log)


def apply(topic, record, read, block):
    """Write the pass's result into the topic: the record (or none), the
    evidence, and - when step 5a has written `support_text` - the piece."""
    if record is not None:
        topic[RECORD_FIELD] = record
    else:
        topic.pop(RECORD_FIELD, None)
    topic.setdefault("evidence", {})[READ_KEY] = read
    if isinstance(topic.get("support_text"), list):
        topic["support_text"], _ = api_demo_text.merge(topic["support_text"], topic, block)


def summary_line(tid, read):
    return (f"api-demo {tid}: {read['status']}"
            + (f" ({read['display_name']})" if read.get("display_name") else "")
            + (f", key from {read['key_source']}" if read.get("key_source") else "")
            + (f" - {read['note']}" if read.get("note") else ""))


@runlog.script("trend-hunter", "api-demo", name="fetch_api_demo.py")
def main(argv=None, client=None):
    import footage_candidates as fc
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--batch", required=True, help="batch dir or 01-trend-hunter.json")
    ap.add_argument("--topic", action="append", help="only these topic ids")
    ap.add_argument("--channel", help="the channel (default: the batch's `channel`)")
    ap.add_argument("--prompts-approved", action="store_true",
                    help="the user approved the channel's api_demo.prompts for this run")
    ap.add_argument("--max-calls", type=int, help="lower the batch's call cap")
    ap.add_argument("--work-dir", help="where api-demo-<topic>.json go "
                                       "(default <batch>/work/api_demo)")
    args = ap.parse_args(argv)
    path = Path(fc._batch_path(args.batch))
    batch = json.loads(path.read_text())
    channel = args.channel or fc._batch_channel(batch)
    try:
        config = footage_origin.load_config(channel)
    except footage_origin.ConfigError as exc:
        print(json.dumps({"error": f"footage origin: {exc}"}), file=sys.stderr)
        return 2
    if not footage_origin.has_api_demo(config):
        print(json.dumps({"channel": config["channel"], "calls": 0, "topics": [],
                          "not_asked": "the channel's footage origins name no api_demo - "
                                       "nothing to ask, nothing written"}, indent=2))
        return 0
    block = footage_origin.api_demo_block(config)
    why_not = block_problems(block)
    if not why_not and (_rule is None or _client is None):
        why_not = ["the root's shared/api_demo.py or shared/gemini/gemini_api.py was not "
                   "found - no call"]
    if why_not:
        # A channel that cannot ask is a note for the step-8 report, never a
        # failed batch: the topics go on without a demo.
        print(json.dumps({"channel": config["channel"], "calls": 0, "topics": [],
                          "not_asked": "; ".join(why_not)}, ensure_ascii=False, indent=2))
        return 0
    approved = prompts_approved(block, args.prompts_approved)
    cap = int(block.get("max_calls_per_batch") or 0)
    if args.max_calls is not None:
        cap = min(cap, max(0, args.max_calls))
    work_dir = Path(args.work_dir) if args.work_dir else path.parent / WORK_DIR
    budget = Budget(cap, calls_on_record(work_dir))
    if client is None and approved[0]:
        client = make_client(block, log=lambda line: print(line, file=sys.stderr))
    wanted = set(args.topic or [])
    summary = []
    for topic in batch.get("topics") or []:
        tid = topic.get("topic_id")
        if wanted and tid not in wanted:
            continue
        record, read = topic_demo(topic, block, client, work_dir=work_dir, budget=budget,
                                  approved=approved)
        apply(topic, record, read, block)
        print(summary_line(tid, read), file=sys.stderr)
        summary.append({"topic_id": tid, **{k: read[k] for k in (
            "status", "record_id", "model", "cached", "called", "key_source", "note")}})
    path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"channel": config["channel"], "calls": budget.spent,
                      "calls_before": budget.before, "cap": budget.calls,
                      "prompts_approved": approved[0], "stopped": budget.stopped,
                      "records": sum(1 for s in summary if s["status"] == OK),
                      "work_dir": str(work_dir), "topics": summary},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
