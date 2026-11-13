#!/usr/bin/env python3
"""CF-0424: the channel's hook-opener formulas, and which of them a batch may use.

**The decision.** The user, 2026-09-28: a video that opens on a formula - "the
most talked-about ...", "the most important ...", "nobody noticed ..." - holds
the viewer better. The channel keeps a library of such openers
(`channels/<channel>.json` -> `content_researcher.hook_openers`, a list of
`{"id", "template"}`), the writer picks the one that fits the topic and fills
its slots (`{x}`, `{fact}`, ... - free names) with the topic's specifics, and
one formula is used at most once per `hook_opener_min_gap_videos` videos, so
the channel does not read as a template (YouTube's reused / repetitive-content
policy). `0` switches the rotation off. No library in the channel file means
the opener is free, exactly as before CF-0424.

**Where the use is recorded.** `03-content-researcher.json` ->
`scripts[].hook_opener_id`, beside `hook`: the template's id, or `null` for an
opener of the writer's own. A batch written before CF-0424 has no key; that is
read as `null`.

**The rotation.** The history is the `03` of the channel's past batches -
every directory the channel's batches have lived in (a renamed channel keeps
its old directories, CF-0197), batch directories ordered by batch id, and
inside a batch `scripts[]` in file order. Only the batches whose id sorts
before the batch being written count, so a re-check of an old batch sees the
history that batch saw. Of that history, the last N scripts that carry a
non-empty `hook_opener_id` are the window, and every id in it is barred. A
script that opened on its own words takes no place in the window: the rule is
about formulas repeating, and a free opener repeats none. Inside the batch
being written a formula is used at most once as well.

This module is both the library the gate (`check_hook_opener.py`) reads and
the operator's helper: before writing the hooks of a batch, print the formulas
it may use, with their templates, and choose by meaning:

    python3 scripts/hook_openers.py ~/shorts-content-factory/pipeline/<channel>/<batch-id>
    python3 scripts/hook_openers.py <batch-dir> --topic <topic_id>   # rewriting one hook

`--topic` leaves that topic's own script out of the batch's used set - the
formula it holds now is the one being replaced, not one taken by a neighbour.
`--json` prints the same answer as one object. The batch directory does not
need a `03` yet; the channel is read off the `03` when there is one, else off
the directory's parent name, and `--channel` overrides both.

Stdlib only; no event is written - this is a lookup the writer makes, not a
gate (the gate is `check_hook_opener.py`, step `check-hook-opener`).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
from _channel_ids import channel_batch_dirs, resolve_channel  # noqa: E402

BATCH_FILE = "03-content-researcher.json"
BLOCK = "content_researcher"
LIBRARY_KEY = "hook_openers"
GAP_KEY = "hook_opener_min_gap_videos"
FIELD = "hook_opener_id"
DEFAULT_GAP = 5          # the user's default, used when the library has no gap key

_SLOT_RE = re.compile(r"(\{[^{}]*\})")
_APOSTROPHES = re.compile(r"['’‘`]")
_NON_WORD = re.compile(r"[^0-9a-z]+")
_SLOT = "SLOT"
# One or more tokens of the normalized hook, as few as will do.
_SLOT_RX = r"\S+(?: \S+)*?"
# A slot the template opens on (`{x} was never supposed to ...`, `{number} -
# that's the number behind ...`) is a name or a number, not a sentence: bounded, so a
# hook that says "was never supposed to" somewhere in its middle is not read
# as opening on the formula.
LEAD_SLOT_MAX_WORDS = 8
_LEAD_SLOT_RX = r"\S+(?: \S+){0,%d}?" % (LEAD_SLOT_MAX_WORDS - 1)


class ConfigError(Exception):
    """The channel file is missing or unreadable."""


# --------------------------------------------------------------------------
# matching a hook against a template
# --------------------------------------------------------------------------

def normalize(text):
    """Lower case, apostrophes dropped ("that's" = "that’s" = "thats"),
    every other run of non-alphanumerics one space. The comparison the gate
    makes is on words, not on punctuation."""
    text = _APOSTROPHES.sub("", (text or "").lower())
    return " ".join(_NON_WORD.sub(" ", text).split())


def template_pattern(template):
    """The regex a normalized hook has to match at its start to open on this
    template: the template's own words in order, each slot one or more words
    of anything. Adjacent slots (`{x}: {fact}`) are one slot."""
    elements = []
    for piece in _SLOT_RE.split(template or ""):
        if not piece:
            continue
        if _SLOT_RE.fullmatch(piece):
            if not elements or elements[-1] != _SLOT:
                elements.append(_SLOT)
            continue
        elements.extend(re.escape(tok) for tok in normalize(piece).split())
    body = " ".join((_LEAD_SLOT_RX if i == 0 else _SLOT_RX) if e == _SLOT else e
                    for i, e in enumerate(elements))
    return re.compile("^" + body + r"(?= |$)")


def opens_with(hook, template):
    """Whether the hook starts with this template (its non-slot words, in
    order, case and punctuation aside, each slot filled with something)."""
    return bool(template_pattern(template).match(normalize(hook)))


def matching_ids(hook, library):
    """Ids of every template of the library the hook opens with."""
    return [o["id"] for o in library if opens_with(hook, o.get("template"))]


# --------------------------------------------------------------------------
# the channel's library
# --------------------------------------------------------------------------

def find_root():
    from check_narration_budget import find_root as _find_root
    return _find_root()


def load_config(channel, root=None):
    root = Path(root) if root else find_root()
    path = root / "channels" / f"{resolve_channel(channel, root)}.json"
    if not path.is_file():
        raise ConfigError(f"no channel config {path}")
    try:
        return json.loads(path.read_text())
    except ValueError as exc:
        raise ConfigError(f"{path} is not JSON: {exc}") from None


def library_of(config):
    """`(library, gap)`: the channel's opener templates (a list of
    `{"id", "template"}`, `[]` when the channel has none) and N, the
    rotation's window (0 = off)."""
    block = (config or {}).get(BLOCK) or {}
    lib = [o for o in (block.get(LIBRARY_KEY) or [])
           if isinstance(o, dict) and o.get("id") and o.get("template")]
    gap = block.get(GAP_KEY, DEFAULT_GAP)
    gap = gap if isinstance(gap, int) and gap >= 0 else DEFAULT_GAP
    return lib, gap


# --------------------------------------------------------------------------
# the rotation's history
# --------------------------------------------------------------------------

def _read_scripts(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    return [s for s in (data.get("scripts") or []) if isinstance(s, dict)]


def history(channel, pipeline_dir, before_batch=None):
    """Every past script of the channel that carries an opener id, oldest
    first: `(batch_id, script_id, hook_opener_id)`. Only batches whose id
    sorts before `before_batch` (all, when it is None)."""
    dirs = {}
    for base in channel_batch_dirs(channel, pipeline_dir=pipeline_dir):
        for d in base.iterdir():
            if d.is_dir() and (d / BATCH_FILE).is_file():
                dirs.setdefault(d.name, d)          # current name wins (listed first)
    out = []
    for batch_id in sorted(dirs):
        if before_batch is not None and batch_id >= before_batch:
            continue
        for s in _read_scripts(dirs[batch_id] / BATCH_FILE):
            oid = s.get(FIELD)
            if oid:
                out.append((batch_id, s.get("script_id"), oid))
    return out


def barred_by_history(hist, gap):
    """`{id: (batch_id, script_id)}` of the last `gap` openers used - the
    formulas the rotation bars. Empty when the rotation is off."""
    if gap <= 0:
        return {}
    barred = {}
    for batch_id, script_id, oid in hist[-gap:]:
        barred[oid] = (batch_id, script_id)
    return barred


def batch_context(batch_dir, channel=None, root=None):
    """`(channel, pipeline_dir, batch_id, scripts)` for a batch directory
    (or a file inside it). The channel is resolved through a rename: a batch
    written before it names the former id (CF-0431). `scripts` is the batch's own `scripts[]` when its
    `03` exists, else `[]`."""
    p = Path(batch_dir).expanduser().resolve()
    if p.is_file():
        p = p.parent
    scripts, data = [], {}
    f = p / BATCH_FILE
    if f.is_file():
        try:
            data = json.loads(f.read_text())
        except ValueError:
            data = {}
        scripts = [s for s in (data.get("scripts") or []) if isinstance(s, dict)]
    channel = resolve_channel(channel or data.get("channel") or p.parent.name, root)
    batch_id = data.get("batch_id") or p.name
    return channel, p.parent.parent, batch_id, scripts


def allowed(library, barred, used_in_batch):
    """The library's templates neither barred by the window nor used in the
    batch, in library order."""
    return [o for o in library if o["id"] not in barred and o["id"] not in used_in_batch]


# --------------------------------------------------------------------------
# the helper
# --------------------------------------------------------------------------

def answer(batch_dir, channel=None, topic=None, root=None):
    """The whole lookup as one object (what `--json` prints)."""
    channel, pipeline_dir, batch_id, scripts = batch_context(batch_dir, channel, root)
    library, gap = library_of(load_config(channel, root))
    hist = history(channel, pipeline_dir, before_batch=batch_id)
    barred = barred_by_history(hist, gap) if library else {}
    used = {}
    if gap > 0:
        for s in scripts:
            if topic and s.get("topic_id") == topic:
                continue
            if s.get(FIELD):
                used.setdefault(s[FIELD], s.get("script_id"))
    return {
        "channel": channel,
        "batch_id": batch_id,
        "library": bool(library),
        "min_gap_videos": gap,
        "barred": {k: {"batch_id": b, "script_id": sid} for k, (b, sid) in barred.items()},
        "used_in_batch": used,
        "allowed": allowed(library, barred, used),
    }


def render(ans, out=print):
    if not ans["library"]:
        out(f"{ans['channel']}: no `{BLOCK}.{LIBRARY_KEY}` in the channel file - the "
            f"opener is free; write `{FIELD}: null`")
        return
    gap = ans["min_gap_videos"]
    head = (f"{ans['channel']} {ans['batch_id']}: {len(ans['allowed'])} opener(s) allowed")
    if gap > 0:
        head += f" (one formula at most once in {gap} videos; barred by the last {gap}: "
        head += (", ".join(sorted(ans["barred"])) or "none") + ")"
    else:
        head += " (rotation off: min_gap_videos 0)"
    out(head)
    for oid, sid in sorted(ans["used_in_batch"].items()):
        out(f"  used in this batch: {oid} ({sid})")
    for o in ans["allowed"]:
        out(f"  {o['id']:<22} {o['template']}")
    out(f"Pick the one that fits the topic by meaning, fill its slots with the topic's "
        f"specifics, and write its id into `{FIELD}`.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch", help="pipeline/<channel>/<batch-id> (or a file inside it)")
    ap.add_argument("--channel", help="override the channel read off the batch")
    ap.add_argument("--topic", help="a topic whose hook is being rewritten: its own "
                                    "script is left out of the batch's used set")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    args = ap.parse_args(argv)
    try:
        ans = answer(args.batch, args.channel, args.topic)
    except ConfigError as exc:
        print(f"hook_openers: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(ans, ensure_ascii=False, indent=2))
    else:
        render(ans)
    return 0


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
