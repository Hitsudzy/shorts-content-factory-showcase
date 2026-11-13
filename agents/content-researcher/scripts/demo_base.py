#!/usr/bin/env python3
"""CF-0827: can each topic be a «демо» - asked at step 2, before the rotation
is asked for a pattern and before a word is written.

ExampleTech 04-20.10 lost three topics as the writer's `pattern_undeliverable`:
the rotation drew `demo`, the topic had nothing a demo could stand on, the
writer rejected the draw after the fact and the guard denied it (R3/R4). Two of
them (`2026-10-16T0839Z` -005, -013: no recording, no API record) are closed at
the root since CF-0775 - `rotation/material.py` reads the batch's own 01/01b and
never draws `demo` for a topic with no demo base. The third
(`2026-10-20T1448Z` -013, OpenCode) had a recording - of another product, the
Hugging Face Space `OpenCoder-LLM/OpenCoder-8B-Instruct` - so the material
reading saw a base, the rotation drew `demo`, and the writer found out only
when it sat down to write. Since CF-0832 the root's reading no longer counts a
recording of another product as a base (`material.foreign_capture`: no Space
id or card title names the topic, and no `api_demo_record` of an ok call), so
that topic is `nodemo` here and the rotation never draws `demo` for it.

Everything this question needs is on the Trend Hunter's output, so it is asked
first, for every topic at once:

    demo    the topic has a demo base - its own recording in the pool, or an
            `api_demo_record` of an `ok` call (CF-0690) - and the recording's
            Space carries the topic's name: a demo if the rotation draws one.
    nodemo  no demo base. The base reading is the rotation's own
            (`rotation/material.py` `demo_base`, loaded from the root - one copy
            of the rule, so the two cannot disagree): the rotation never draws
            `demo` for this topic (CF-0775), a recording of another product
            included (CF-0832: OpenCode against `OpenCoder-LLM/...`). Nothing
            to reject, nothing to do.
    LOOK    (exit 1) the safeguard for where the two readings part: the root
            counts a base, yet the recording in the pool has a Space id that
            does not carry the topic's name (`title_ref.name`) as a word - the
            root saw the name only in the Space's card title, or stands the
            base on an ok `api_demo_record` beside a recording of another
            product (or an older root without CF-0832 is loaded). A longer word
            that merely starts with the name is not the name; a version number
            after it is. Watch that recording now, at step 2: if it does not
            show this topic's tool, it is not this topic's demo footage - say
            so in the step 7 report with this line, and if the rotation draws
            `demo` and nothing else (no API chat) carries it, the rejection
            reason is this line (`rotate.py reject ... --reason`).
    none    the channel does not list `demo` (`patterns.allowed_pattern_ids`):
            nothing to decide.

Read-only, no network, no model. Exit 0 nothing owed, 1 a LOOK line, 3 the
question could not be put (no 01, no root).

Usage:

    python3 scripts/demo_base.py <batch dir | a file in it> [--topic TID ...]
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
from check_narration_budget import find_root  # noqa: E402
from check_demo import (PATTERN_DEMO, capture_of, topics_by_id,  # noqa: E402
                        API_RECORD_FIELD, is_own_capture)

TREND_FILE = "01-trend-hunter.json"
INDEX_FILE = "01b-footage-index.json"
MATERIAL_REL = Path("rotation") / "material.py"

VERDICT_DEMO, VERDICT_NODEMO, VERDICT_LOOK = "demo", "nodemo", "LOOK"
EXIT_OK, EXIT_LOOK, EXIT_CANNOT_ANSWER = 0, 1, 3

_WORD = re.compile(r"[a-z0-9]+")
_VERSION_TAIL = re.compile(r"^(v?\d+[a-z0-9]*)?$")


class CannotAnswer(Exception):
    """The question could not be put. Never a verdict on a topic."""


def load_material(root):
    """The root's `rotation/material.py` - the rotation's own demo-base rule."""
    path = Path(root) / MATERIAL_REL
    if not path.is_file():
        raise CannotAnswer(f"no {MATERIAL_REL} in {root} - the rotation's demo-base rule "
                           f"(CF-0775) is what this check mirrors")
    spec = importlib.util.spec_from_file_location("_rotation_material", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def words(text):
    return _WORD.findall(str(text or "").lower())


def space_names(name, space):
    """True when the Space id carries the topic's name as a word.

    A copy of the root's `rotation/material.py` `names_in` (CF-0832), kept here
    on purpose: the root's `tests/test_space_name_rule_copies.py` cuts this
    function out of this file and holds it to the root's answers. Here it reads
    the Space id only - the root also reads the card title, and the gap is
    exactly what `LOOK` is for.

    The name's words stand consecutively among the Space id's words, or the
    name written together ("DeepSeek" / "deep-seek") is a run of them written
    together - optionally followed by a version ("ChatGPT" in `ChatGPT4`).
    A longer word that only starts with the name is another name: "OpenCode"
    is not in `OpenCoder-LLM/OpenCoder-8B-Instruct`."""
    want = words(name)
    have = words(space)
    if not want or not have:
        return False
    compact = "".join(want)
    for i in range(len(have)):
        if have[i:i + len(want)] == want:
            return True
        run = ""
        for w in have[i:]:
            run += w
            if run == compact:
                return True
            if run.startswith(compact) and _VERSION_TAIL.match(run[len(compact):]):
                return True
            if len(run) >= len(compact):
                break
    return False


def demo_allowed(channel, root):
    """True / False from the channel's `patterns.allowed_pattern_ids`; None
    when the config cannot be read (then every topic is asked)."""
    try:
        cfg = json.loads((Path(root) / "channels" / f"{channel}.json").read_text())
    except (OSError, ValueError, TypeError):
        return None
    ids = (cfg.get("patterns") or {}).get("allowed_pattern_ids")
    return PATTERN_DEMO in ids if isinstance(ids, list) else None


def verdict(topic, pool_ids, material):
    """`(verdict, detail)` for one topic. `nodemo` is the root's reading
    verbatim; `LOOK` only where the root counts a base that the in-pool
    recording's Space id does not name (the safeguard, CF-0832)."""
    why = material.demo_base(topic, pool_ids)
    if why:
        return VERDICT_NODEMO, (f"{why} - the rotation never draws `demo` for it (CF-0775); "
                                f"nothing to reject")
    capture = capture_of(topic)
    space = ((capture or {}).get("capture") or {}).get("space")
    in_pool = capture is not None and (pool_ids is None
                                       or any(is_own_capture(v) for v in pool_ids))
    if not in_pool:
        record = (topic or {}).get(API_RECORD_FIELD) or {}
        rid = record.get("record_id") if isinstance(record, dict) else None
        return VERDICT_DEMO, f"a demo via API on {rid or 'its api_demo_record'} (CF-0690)"
    name = ((topic or {}).get("title_ref") or {}).get("name")
    how = ((capture or {}).get("capture") or {}).get("subject_match")
    if name and space and not space_names(name, space):
        return VERDICT_LOOK, (
            f"the recording's Space {space} does not carry the topic's name {name!r} as a "
            f"word (subject_match {how or 'not recorded'}), yet the rotation's reading "
            f"counts a base (card title or api_demo_record; CF-0832) - watch it now: if it "
            f"is not this topic's tool it is not this topic's demo footage; if the rotation "
            f"draws `demo` and nothing else carries it, this line is the rejection reason "
            f"(rotate.py reject)")
    return VERDICT_DEMO, (f"own recording {space or capture.get('video_id')} in the pool"
                          + (f" (subject_match {how})" if how else "")
                          + " - a demo if the rotation draws one")


def check_batch(batch, topic_ids=None, root=None, out=print):
    """`{topic_id: (verdict, detail)}` for the batch's topics (or `topic_ids`)."""
    batch = Path(batch)
    batch_dir = batch if batch.is_dir() else batch.parent
    try:
        trend = json.loads((batch_dir / TREND_FILE).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_dir / TREND_FILE}: {exc}")
    root = Path(root) if root else find_root()
    channel = resolve_channel(trend.get("channel"), root)
    allowed = demo_allowed(channel, root)
    if allowed is False:
        out(f"none  {batch_dir}: `{PATTERN_DEMO}` is not a pattern of channel {channel} - "
            f"nothing to decide")
        return {}
    material = load_material(root)
    topics = topics_by_id(trend)
    sbt = None
    index = batch_dir / INDEX_FILE
    if index.is_file():
        try:
            sbt = json.loads(index.read_text()).get("sources_by_topic") or {}
        except ValueError as exc:
            raise CannotAnswer(f"cannot read {index}: {exc}")
    wanted = list(topic_ids) if topic_ids else list(topics)
    out(f"{batch_dir}: {len(wanted)} topic(s) of channel {channel}; the demo base asked "
        f"before the rotation draws (CF-0827), base rule {MATERIAL_REL} (CF-0775)"
        + ("" if sbt is not None else "; no footage index - the pool is not asked"))
    results = {}
    for tid in wanted:
        topic = topics.get(tid)
        if topic is None:
            raise CannotAnswer(f"topic {tid!r} is not in {TREND_FILE}")
        pool = None
        if sbt is not None:
            pool = sbt.get(tid) if isinstance(sbt.get(tid), list) else []
        v, detail = results[tid] = verdict(topic, pool, material)
        out(f"  {v:<6} {tid}: {detail}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch", help="pipeline/<channel>/<batch> (or any file in it)")
    ap.add_argument("--topic", action="append", dest="topics", default=None,
                    help="only this topic (repeatable); default every topic of 01")
    ap.add_argument("--root", help="the factory checkout (default: found from this file)")
    args = ap.parse_args(argv)
    try:
        results = check_batch(args.batch, args.topics, args.root)
    except CannotAnswer as exc:
        print(f"cannot answer: {exc}")
        return EXIT_CANNOT_ANSWER
    look = [t for t, (v, _d) in results.items() if v == VERDICT_LOOK]
    if look:
        print(f"\n{len(look)} topic(s) to look at before the rotation is asked: "
              + ", ".join(look))
        return EXIT_LOOK
    return EXIT_OK


@runlog.script("content-researcher", "demo-base", name="demo_base.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event (1 = a LOOK line, 2 = usage, 3 = cannot answer).
    Pure Python over the batch files: no external binary, no model call."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
