#!/usr/bin/env python3
"""CF-0690: the factory's own record of an API demo call as a `support_text`
piece - which prompt was sent to which model, through which API, when, and
what the model answered, verbatim.

Why. A script that orders an `api_chat` graphic says aloud what it shows
("we asked Gemini 2.5 Flash through the Gemini API ...") and every sentence
of a script is footed by a verbatim quote of a piece of the topic's
`support_text` (the root's `shared/factrule/claims.py`: `{source: <piece
id>, quote}`). The piece is written in plain sentences out of the topic's
`api_demo_record` (`fetch_api_demo.py`), so such a sentence has a quote to
copy word for word - the way `own_capture_text.py` gives a demo's "running in
a public Hugging Face Space" its quote.

The shape - the keys every piece has (`support_text.py`: `id`, `kind`,
`source`, `title`, `url`, `revision_id`, `revised_at`, `text`) plus its own:

    id             api-demo-<topic>          (= the record's record_id)
    kind           api_demo_record
    source         api_demo                  (the factory's own record)
    title          "API demo of <display name>" (a label, not quotable text)
    url            the endpoint asked (https, never a key)
    revision_id    null, revised_at null     (no page revision to age)
    fetched_at     the protocol's answered_at
    requested_at, model_requested, model_version, display_name, prompt,
    record_id
    not_a_fact     true
    text           "On <date> the factory sent this prompt to <display name>
                   through the Gemini API: «<prompt>». <display name>
                   answered: «<answer>»."

The display name is the channel's (`api_demo.models[].display_name` through
the root's `api_demo.display_name_for(model_version)`) - the API's own
`modelVersion`, never the answer's text. A record that is not an `ok`, whole
protocol, or whose model the channel's list does not name, gives no piece.

It is **never a fact**: what the model answered is the model's output, not
the story's. The piece is written after the fact probe (step 5a) chose the
fact, and nothing that selects or counts a fact reads it - the own-graphics
floor (`footage_candidates.quotable_facts`) leaves it out, so a number in
the answer never counts toward the three quotable facts. It never changes
`support_check.state` and is no second source of anything.
"""
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _api_demo import api_demo as _rule  # noqa: E402

KIND = "api_demo_record"
SOURCE = "api_demo"
ID_HEAD = "api-demo-"
RECORD_FIELD = "api_demo_record"
API_NAME = "the Gemini API"


def _day(stamp):
    """'2026-10-12T09:30:00Z' -> '2026-10-12', or the stamp as it is."""
    try:
        return datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return str(stamp) if stamp else None


def records_of(topic):
    """The topic's `api_demo_record` as a list of {record_id, protocol}."""
    rec = (topic or {}).get(RECORD_FIELD)
    if isinstance(rec, dict):
        return [rec]
    return [r for r in rec if isinstance(r, dict)] if isinstance(rec, list) else []


def piece(record, block, rule=None):
    """The `api_demo_record` piece of one record, or None."""
    rule = rule if rule is not None else _rule
    if rule is None or not isinstance(record, dict):
        return None
    rid, proto = record.get("record_id"), record.get("protocol")
    if not (isinstance(rid, str) and rule.RECORD_ID_RE.match(rid)) or not isinstance(proto, dict):
        return None
    if proto.get("status") != "ok" or rule.protocol_problems(proto):
        return None
    display = rule.display_name_for(proto.get("model_version"), block)
    if not display:
        return None
    day = _day(proto.get("answered_at"))
    text = (f"On {day} the factory sent this prompt to {display} through {API_NAME}: "
            f"«{proto['prompt']}». {display} answered: «{proto['answer']}».")
    return {
        "id": rid,
        "kind": KIND,
        "source": SOURCE,
        "title": f"API demo of {display}",
        "url": proto.get("endpoint"),
        "revision_id": None,
        "revised_at": None,
        "fetched_at": proto.get("answered_at"),
        "requested_at": proto.get("requested_at"),
        "model_requested": proto.get("model_requested"),
        "model_version": proto.get("model_version"),
        "display_name": display,
        "prompt": proto.get("prompt"),
        "record_id": rid,
        "not_a_fact": True,
        "text": text,
    }


def merge(pieces, topic, block, rule=None):
    """-> (support_text with this topic's api-demo pieces replaced by one per
    record of `topic["api_demo_record"]`, the pieces written). Idempotent: a
    second pass rewrites them, never doubles them; a topic whose record is
    gone loses its piece."""
    kept = [p for p in pieces or [] if not (isinstance(p, dict) and p.get("kind") == KIND)]
    new = [p for p in (piece(r, block, rule) for r in records_of(topic)) if p]
    return kept + new, new
