#!/usr/bin/env python3
"""CF-0775: a pattern whose base footage a topic does not have is never drawn
for that topic.

ExampleTech, batch `2026-10-16T0839Z`: the rotation drew `demo` for iPhone Duo
(`lf-2026-10-16-005`) and Muse Spark Open (`-013`). Neither topic had a
demo's base - no recording of our own (`evidence.footage_base.base` is not
`own_capture`) and no `api_demo_record` of an `ok` call (CF-0690) - so the
writer rejected the draw, exactly as its skill says. The guard then ruled on
that rejection as if it were taste: for -005 the replacement was the same
pattern on the other rhythm (`demo/even`) and the second rejection was denied
by R3; for -013 the rejection was denied by R4 because `demo/hold` had been
refused once already inside the window (by -005, for the same missing
material). Both topics left the batch as `pattern_undeliverable`.

Whether a topic has a demo's base is not an opinion about the pair - it is a
fact on disk in the batch's own `01-trend-hunter.json` (and the pool in
`01b-footage-index.json`), known before the draw. So it is the draw's input,
the way a rhythm that is not executable today is (`eligible_pairs`): a pattern
the topic has no base for is excluded from that topic's draw, and a rejection
that names it (an older row, or a batch the rotation could not read when it
drew) is upheld as a missing-material case, not judged by the taste rules.

`RULES` maps a pattern to the check of its base. Only `demo` has one today
(`patterns/demo.json`: the factory's own recording is the footage; CF-0690: or
a chat via API on the topic's real call). The reading mirrors the writer's
`agents/content-researcher/scripts/check_demo.py` (`demo_without_capture`) so
the two cannot disagree about which topic is a demo:

  * own capture - `evidence.footage_base.base == "own_capture"`, an own-capture
    candidate in `evidence.footage_candidates`, and, when the batch has a
    footage index, an `own_capture-<id>` in the topic's pool
    (`01b` -> `sources_by_topic`);
  * or a demo via API - an `api_demo_record` with a protocol of `status: ok`.

CF-0832: a recording is the topic's base only when it is a recording of the
topic. ExampleTech `2026-10-20T1448Z` -013 (OpenCode) had a recording of the
Hugging Face Space `OpenCoder-LLM/OpenCoder-8B-Instruct` - another product -
so the reading above saw a base, the rotation drew `demo`, and the writer's
rejection was denied by R4. Now the recording's Space has to carry the topic's
name (`title_ref.name`) by `space_names()`, the factory's one copy of the
whole-word rule: the name's words stand consecutively among the Space's words
(its `owner/name` id, or its card title), or the name written together is a
run of them written together, and only a version may follow it - "OpenCode" is
not `OpenCoder`, "ChatGPT" is in `ChatGPT4`, "GPT-4o" is in `gpt4o-mini`. A
topic with no name or a capture with no Space recorded cannot be judged, and
what cannot be read is not a verdict: it stays a base. The rule's other
holders - the Trend Hunter's `fetch_own_capture.py` `word_run` (CF-0831) and
the Content Researcher's `demo_base.py` `space_names` (CF-0827) - are checked
against this one by `tests/test_space_name_rule_copies.py`.

What cannot be read is not a verdict: a batch with no readable
`01-trend-hunter.json`, or a topic missing from it, excludes nothing (the
draw is what it was before this task) - the writer's checker and the
Editor's gates stay the line behind it.

Stdlib only, no network; `shared/api_demo.py` is the one import, for the
record's shape.
"""
import json
import re
import sys
from pathlib import Path

# `shared/api_demo.py`, found from this file rather than from whoever loaded
# it (CF-0159's rule, as rotate.py registers its own directory).
_SHARED = str(Path(__file__).resolve().parent.parent / "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import api_demo  # noqa: E402

TREND_FILE = "01-trend-hunter.json"
INDEX_FILE = "01b-footage-index.json"

OWN_CAPTURE = "own_capture"                        # = check_demo.OWN_CAPTURE
OWN_CAPTURE_HEADS = ("own_capture-", "own_capture:")  # = check_demo.OWN_CAPTURE_HEADS

_SCRIPT_SUFFIX = re.compile(r"-script\d+$")


def topic_id_of(script_id):
    """`lf-2026-10-16-005-script1` -> `lf-2026-10-16-005`."""
    return _SCRIPT_SUFFIX.sub("", str(script_id or ""))


def _is_own_capture(video_id):
    return isinstance(video_id, str) and video_id.startswith(OWN_CAPTURE_HEADS)


def _has_capture_candidate(topic):
    return any(True for _c in _capture_candidates(topic))


_WORD = re.compile(r"[a-z0-9]+")
_VERSION_TAIL = re.compile(r"^(v?\d+[a-z0-9]*)?$")
CAPTURE_TITLE_TAIL = " - own capture ({space})"   # = fetch_own_capture.capture_record


def name_words(text):
    """`OpenCoder-LLM/OpenCoder-8B` -> ['opencoder', 'llm', 'opencoder', '8b']."""
    return _WORD.findall(str(text or "").lower())


def names_in(name, text):
    """Whether `text` carries `name` as whole words (CF-0832).

    The name's words stand consecutively among the text's words, or the name
    written together ("DeepSeek" / "deep-seek") is a run of the text's words
    written together - optionally followed by a version ("ChatGPT" in
    `ChatGPT4`, "GPT-4o" in `gpt4o-mini`). A longer word that only starts
    with the name is another name: "OpenCode" is not in
    `OpenCoder-LLM/OpenCoder-8B-Instruct`, "ChatGPT" is not in `ChatGPTizer`."""
    want, have = name_words(name), name_words(text)
    if not want or not have:
        return False
    flat = "".join(want)
    for i in range(len(have)):
        if have[i:i + len(want)] == want:
            return True
        run = ""
        for w in have[i:]:
            run += w
            if run == flat:
                return True
            if run.startswith(flat) and _VERSION_TAIL.match(run[len(flat):]):
                return True
            if len(run) >= len(flat):
                break
    return False


def space_names(name, space, title=None):
    """Whether a Space - its `owner/name` id or its card title - names `name`."""
    return names_in(name, space) or names_in(name, title)


def _capture_candidates(topic):
    for c in ((topic or {}).get("evidence") or {}).get("footage_candidates") or []:
        if isinstance(c, dict) and (c.get("kind") == OWN_CAPTURE
                                    or c.get("footage_origin") == OWN_CAPTURE
                                    or _is_own_capture(c.get("video_id"))):
            yield c


def _card_title(candidate, space):
    """The Space's card title, out of the candidate's `<card title> - own
    capture (<space>)`; None when the title is not of that shape."""
    title = candidate.get("title")
    tail = CAPTURE_TITLE_TAIL.format(space=space)
    if isinstance(title, str) and title.endswith(tail) and len(title) > len(tail):
        return title[:-len(tail)]
    return None


def foreign_capture(topic):
    """Why the topic's recordings are of another product (CF-0832), or None.

    None as soon as one recording's Space names the topic, or one cannot be
    judged (no `title_ref.name`, no `capture.space` recorded)."""
    name = ((topic or {}).get("title_ref") or {}).get("name")
    if not isinstance(name, str) or not name_words(name):
        return None
    spaces = []
    for c in _capture_candidates(topic):
        space = (c.get("capture") or {}).get("space")
        if not isinstance(space, str) or not name_words(space):
            return None
        if space_names(name, space, _card_title(c, space)):
            return None
        spaces.append(space)
    if not spaces:
        return None
    return (f"the own recording's Space {', '.join(spaces)} does not carry the topic's "
            f"name {name!r} as a word - a recording of another product is not this "
            f"topic's demo (CF-0832)")


def _has_ok_api_call(topic):
    records = api_demo.protocols_by_record((topic or {}).get(api_demo.RECORD_FIELD))
    return any(p.get("status") == "ok" for p in records.values())


def demo_base(topic, pool_ids=None):
    """None when the topic has a demo's base, else why it has none."""
    base = ((topic or {}).get("evidence") or {}).get("footage_base") or {}
    has_api = _has_ok_api_call(topic)
    if base.get("base") == OWN_CAPTURE and _has_capture_candidate(topic):
        foreign = foreign_capture(topic)
        if foreign:
            if has_api:
                return None
            return (f"{foreign}, and the topic has no api_demo_record of an ok call - "
                    f"a demo has no base footage")
        if pool_ids is None or any(_is_own_capture(v) for v in pool_ids):
            return None
        if has_api:
            return None
        return ("the recording never reached the topic's pool (01b sources_by_topic: "
                f"{', '.join(map(str, pool_ids)) or 'none'}) and the topic has no "
                f"api_demo_record of an ok call - a demo has no base footage")
    if has_api:
        return None
    if not base:
        what = "no evidence.footage_base on the topic"
    elif base.get("only_proof_quotes"):
        what = f"proof_quotes_only: {base.get('proof_quotes', 0)} vendor proof quote(s)"
    else:
        what = f"footage_base.base is {base.get('base')!r}"
    return (f"no own capture ({what}) and no api_demo_record of an ok call - a demo has "
            f"no base footage (patterns/demo.json; CF-0690)")


RULES = {"demo": demo_base}


def patterns_with_rules(pairs):
    """The patterns among `pairs` whose base this module checks."""
    return sorted({p for p, _r in pairs if p in RULES})


class BatchMaterial:
    """One batch's topics and pool, read once. `known` is False when the
    batch's trend file could not be read - then nothing is excluded."""

    def __init__(self, batch_dir):
        self.batch_dir = Path(batch_dir) if batch_dir else None
        self.topics, self.pool, self.known = {}, None, False
        if self.batch_dir is None:
            return
        trend = _read(self.batch_dir / TREND_FILE)
        if not isinstance(trend, dict):
            return
        self.topics = {t.get("topic_id"): t for t in trend.get("topics") or []
                       if isinstance(t, dict) and t.get("topic_id")}
        self.known = True
        index = _read(self.batch_dir / INDEX_FILE)
        if isinstance(index, dict) and isinstance(index.get("sources_by_topic"), dict):
            self.pool = index["sources_by_topic"]

    def undeliverable(self, script_id, patterns):
        """{pattern: why} for every pattern of `patterns` this script's topic
        has no base for. Empty when the topic or the batch cannot be read."""
        if not self.known:
            return {}
        tid = topic_id_of(script_id)
        topic = self.topics.get(tid)
        if topic is None:
            return {}
        pool_ids = None
        if self.pool is not None:
            pool_ids = self.pool.get(tid)
            if not isinstance(pool_ids, list):
                pool_ids = []
        out = {}
        for pattern in patterns:
            rule = RULES.get(pattern)
            why = rule(topic, pool_ids) if rule else None
            if why:
                out[pattern] = why
        return out


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
