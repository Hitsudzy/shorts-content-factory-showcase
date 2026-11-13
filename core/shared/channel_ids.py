#!/usr/bin/env python3
"""CF-0197: the names one channel has had, and what still answers to them.

A channel can be renamed (CF-0180: `legacy-film` -> `example-film`), and
when it is, the batch directories it already wrote are deliberately *not*
renamed with it: `pipeline/legacy-film/` is a dated record of what
happened and is correct under the name it happened under. The convention that
follows from that is written once, in the root `README.md` ("Renamed channels
and their batch directories"), and this module is its machine half:

    new batches   are only ever written under the channel's current id, by the
                  agents that glue `pipeline/<channel>/<batch-id>` in their
                  SKILL.md;
    reading       a channel's batches live in every directory the channel has
                  ever used, so a reader looks in all of them, current first;
    naming        a former id arriving from outside - a directory name found
                  on disk, a `channel` field frozen into a batch file written
                  before the rename, an operator typing the old name - resolves
                  to the current id before anything is looked up under it.

The mapping itself is *data*, not code: `channels/<id>.json` ->
`former_channel_ids` is the list of names that channel used to have. It lives
next to the channel it describes because a rename is a fact about a channel,
and because a second rename must not need a code change in five repositories.
This module is the only reader of that field, and every repository that needs
the answer loads this module by path rather than keeping a copy of the mapping
(CF-0159: a rule written down twice is a rule that will disagree with itself).

Stdlib only, and it imports no neighbour: `agents/*/scripts/_channel_ids.py`
loads it with `spec_from_file_location` from a process that has nothing of
this checkout on `sys.path` (the form pinned by `tests/
test_module_path_loading.py`, where `shared/` is listed in GUARDED).
"""
import json
import os
import re
from pathlib import Path

# The two children that identify the checkout root, the same pair every
# agent's `find_root()` already uses.
ROOT_MARKERS = ("channels", "patterns/validate_patterns.py")

# The field in a channel config that lists the ids that channel used to carry,
# oldest or newest first - order is not read, only membership.
FORMER_IDS_KEY = "former_channel_ids"

CHANNELS_SUBDIR = "channels"
PIPELINE_SUBDIR = "pipeline"

# {root: (signature, mapping)}. The signature is the (name, size, mtime_ns) of
# every channel config, so an edit - or a different root in a test tree - is
# picked up, and a loop asking a hundred times still reads the files once.
_CACHE = {}


class ChannelIdError(Exception):
    pass


# CF-0562: a channel that exists (its YouTube channel, its brand) but has no
# pipeline yet - none today (ExampleScience until CF-0659, ExampleTech until CF-0686). Its config
# says so in one key, `"status": "no_pipeline"` (+ `status_note`), and carries
# no `run_plan` and no `publisher`; `batch_schedule.enabled` is false. A
# config without `status` is a channel with a pipeline. Every reader that
# walks `channels/*.json` asks `no_pipeline_reason` first and says «конвейера
# нет - батча не будет» for such a channel instead of failing on the keys it
# lacks or skipping it in silence.
STATUS_KEY = "status"
NO_PIPELINE = "no_pipeline"
STATUSES = (NO_PIPELINE,)
NO_PIPELINE_LINE = "конвейера нет - батча не будет"
# What a no-pipeline config may not carry, and why.
NO_PIPELINE_FORBIDDEN = {
    "run_plan": "a run plan is a pipeline - drop `status` when the channel gets one",
    "publisher": "no pipeline, no videos to publish - no slot, no queue",
}


def no_pipeline_reason(cfg, channel=None):
    """`None` for a channel with a pipeline; the one line «конвейера нет -
    батча не будет (...)» for a no-pipeline one. An unknown `status`, or a
    no-pipeline config that still carries what it must not, raises
    ChannelIdError - a stub that half-says it is a channel is not passed over."""
    if not isinstance(cfg, dict):
        raise ChannelIdError(f"channels/{channel}.json is not a JSON object")
    status = cfg.get(STATUS_KEY)
    if status is None:
        return None
    if status not in STATUSES:
        raise ChannelIdError(f"channels/{channel or cfg.get('channel_id')}.json: unknown "
                             f"`{STATUS_KEY}` {status!r} (known: {', '.join(STATUSES)})")
    errs = no_pipeline_errors(cfg)
    if errs:
        raise ChannelIdError(f"channels/{channel or cfg.get('channel_id')}.json: "
                             + "; ".join(errs))
    note = cfg.get("status_note") or ""
    where = re.search(r"milestone (\d+(?:\.\d+)+)", note)
    return NO_PIPELINE_LINE + (f" (конвейер - веха {where.group(1)})" if where else "")


def no_pipeline_errors(cfg):
    """Why a `status: no_pipeline` config is not a valid stub ([] when it is)."""
    if not isinstance(cfg, dict) or cfg.get(STATUS_KEY) != NO_PIPELINE:
        return []
    errs = [f"`{k}` in a no-pipeline config ({why})"
            for k, why in NO_PIPELINE_FORBIDDEN.items() if k in cfg]
    bs = cfg.get("batch_schedule")
    if not isinstance(bs, dict) or bs.get("enabled") is not False:
        errs.append("a no-pipeline config needs `batch_schedule.enabled: false` (it never "
                    "takes the factory's daily batch)")
    for k in ("channel_id", "display_name"):
        if not cfg.get(k):
            errs.append(f"no `{k}`")
    return errs


# CF-0659: a channel with a pipeline may still not be startable - its voice is
# a placeholder until the user chooses it by ear (ExampleScience, CF-0565).
# The mark is the word `TODO` in `voice_profile_note` or in a value of
# `voice_profile` (the placeholder keeps a valid profile so the readers of the
# block - agents/video-editor/scripts/voice_profile.py - load it; the note says
# it is not the choice). While it stands, no batch starts: the executor refuses
# `run` (`run_plan.start_refusal`), the schedule does not plan the channel and
# the console's launch check fails its `voice` guard (shared/batch_schedule.py).
VOICE_TODO_RE = re.compile(r"\bTODO\b(?:\s+(CF-\d+))?")


def voice_placeholder_reason(cfg, channel=None):
    """None when the channel's voice is chosen; the one line why a batch may not
    start when `voice_profile` is still a placeholder (`TODO` in the block or
    in `voice_profile_note`)."""
    if not isinstance(cfg, dict):
        return None
    vp = cfg.get("voice_profile")
    texts = [cfg.get("voice_profile_note")]
    if isinstance(vp, dict):
        texts += list(vp.values())
    elif isinstance(vp, str):
        texts.append(vp)
    for text in texts:
        m = VOICE_TODO_RE.search(text) if isinstance(text, str) else None
        if m:
            task = f" ({m.group(1)})" if m.group(1) else ""
            who = channel or cfg.get("channel_id") or "канал"
            return (f"голос {who} не выбран{task}: `voice_profile` - заглушка (TODO в "
                    f"channels/{who}.json), батч не стартует, пока голос не выбран на слух")
    return None


def channel_no_pipeline(channel, root=None):
    """`no_pipeline_reason` of `channels/<channel>.json` (a former id resolves);
    None when the channel has a pipeline. A missing or broken file raises -
    the caller's own reader would fail on it anyway, with its own words."""
    path = channel_config_path(channel, root)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return no_pipeline_reason(cfg, resolve_channel(channel, root))


def find_root(start=None):
    """The shorts-content-factory checkout this file lives in.

    `SHORTS_FACTORY_ROOT` when set; otherwise the nearest ancestor holding
    both `channels/` and `patterns/validate_patterns.py`; otherwise the
    `~/shorts-content-factory` of the SKILL.md convention.
    """
    env = os.environ.get("SHORTS_FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if all((candidate / m).exists() for m in ROOT_MARKERS):
            return candidate
    return Path.home() / "shorts-content-factory"


def _channels_dir(root=None):
    return Path(root or find_root()) / CHANNELS_SUBDIR


def _signature(channels_dir):
    out = []
    for path in sorted(channels_dir.glob("*.json")):
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((path.name, st.st_size, st.st_mtime_ns))
    return tuple(out)


def former_channel_ids(root=None):
    """{current id: (former id, ...)} for every channel that was renamed.

    Read from `channels/*.json`; a channel that was never renamed, or a
    checkout with no `channels/` at all, contributes nothing. A config that
    cannot be parsed is skipped rather than raised on: this module is called
    from the middle of other people's checks, and a broken channel file is
    their error to report, with their own message.
    """
    channels_dir = _channels_dir(root)
    key = str(channels_dir)
    signature = _signature(channels_dir)
    cached = _CACHE.get(key)
    if cached and cached[0] == signature:
        return cached[1]

    mapping = {}
    for path in sorted(channels_dir.glob("*.json")):
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        formers = cfg.get(FORMER_IDS_KEY)
        if not formers:
            continue
        if isinstance(formers, str):
            formers = [formers]
        current = cfg.get("channel_id") or path.stem
        mapping[current] = tuple(str(f) for f in formers if f)

    _CACHE[key] = (signature, mapping)
    return mapping


def channel_names(channel, root=None):
    """Every name this channel's directories may carry, current one first.

    The answer does not depend on which of its names you ask by: a former id
    is resolved first, so `channel_names("legacy-film")` and
    `channel_names("example-film")` are the same tuple.
    """
    current = resolve_channel(channel, root)
    return (current,) + tuple(former_channel_ids(root).get(current, ()))


def resolve_channel(name, root=None):
    """The current id of a channel that may have been named by a former one.

    A name that is nobody's former id comes back unchanged - including a
    channel id this checkout has never heard of, because deciding that is the
    caller's job and it has a better error message for it than this file does.
    """
    if not name:
        return name
    for current, formers in former_channel_ids(root).items():
        if name in formers:
            return current
    return name


def is_former_id(name, root=None):
    """True when `name` is a name some channel used to carry."""
    return bool(name) and resolve_channel(name, root) != name


def channel_config_path(channel, root=None):
    """`channels/<id>.json` for a channel that may be named by a former id.

    This is the one place the second half of CF-0197 is fixed: a batch file
    frozen before the rename carries `"channel": "legacy-film"`, and a
    reader that takes that field at face value looks for a config that no
    longer exists.
    """
    root = Path(root or find_root())
    return root / CHANNELS_SUBDIR / f"{resolve_channel(channel, root)}.json"


def channel_batch_dirs(channel, pipeline_dir=None, root=None):
    """The directories on disk that hold this channel's batches, newest name
    first. Only directories that exist are returned, so a channel that was
    never renamed gets a list of one and a fresh checkout gets none."""
    root = Path(root or find_root())
    base = Path(pipeline_dir or (root / PIPELINE_SUBDIR))
    return [base / n for n in channel_names(channel, root) if (base / n).is_dir()]


def batch_dir(channel, batch_id, pipeline_dir=None, root=None):
    """The directory of one batch, searched under every name the channel has
    had. Returns None when no directory holds it; the caller says what that
    means, since "not produced yet" and "archived off disk" look the same here
    (the distinction CF-0056 left to the ledger).
    """
    for d in channel_batch_dirs(channel, pipeline_dir, root):
        candidate = d / batch_id
        if candidate.is_dir():
            return candidate
    return None


if __name__ == "__main__":  # a one-line answer for a shell caller
    import sys

    if len(sys.argv) != 2:
        print("usage: channel_ids.py <channel-id>   # prints the current id",
              file=sys.stderr)
        raise SystemExit(2)
    print(resolve_channel(sys.argv[1]))
