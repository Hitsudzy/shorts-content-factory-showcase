"""CF-0197: the one place in this repo that finds the factory's channel-id
library (`<root>/shared/channel_ids.py`) and hands it to the scripts:

    from _channel_ids import resolve_channel

    channel = resolve_channel(channel or data.get("channel"))

In this repository the reader is `ingest_batch.py` (CF-0253): the channel of a
batch is its `pipeline/<channel>/<batch-id>` directory name, or the `channel`
field of `01-trend-hunter.json` frozen into the batch - both arrive from
outside and both are resolved here, at the line that reads them, before
`channels/<id>.json` is opened for its settings.

Why a shim and not three lines of mapping here. A channel can be renamed
(CF-0180: `legacy-film` -> `example-film`), and the batch files written
before the rename carry the old id frozen in their `"channel"` field forever -
they are a dated record and are not rewritten. A script that takes that field
at face value looks for `channels/legacy-film.json`, which does not exist,
and a frozen batch stops being re-checkable. The mapping that fixes it is data
in the root (`channels/<id>.json` -> `former_channel_ids`) with exactly one
reader (`shared/channel_ids.py`); this file only *finds* that reader. A copy of
the mapping in each repository is the defect class CF-0159 names: the next
rename would have to be remembered in five places. The convention itself is
written once, in the root `README.md`, "Renamed channels and their batch
directories".

Root lookup and loading are the same mechanism `_runlog.py` beside this file
already uses (CF-0231, and deliberately not a second one): `FACTORY_ROOT` wins,
otherwise walk this file's ancestors for `shared/channel_ids.py` - which works
from the normal checkout and from a `.claude/worktrees/<x>/scripts/` alike.

If the root cannot be found (this repo copied somewhere on its own), every
function degrades to the identity - which is exactly what these scripts did
before CF-0197 - and one line on stderr says so. It is not silent-and-wrong:
the caller's very next step is opening `channels/<id>.json`, and its own error
names the file it could not find.
"""
import os
import sys
from pathlib import Path

LIB_REL = Path("shared") / "channel_ids.py"


def factory_root():
    """The factory root: FACTORY_ROOT if set, else the nearest ancestor of
    this file that holds shared/channel_ids.py."""
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for p in Path(__file__).resolve().parents:
        if (p / LIB_REL).is_file():
            return p
    raise RuntimeError("factory root not found: set FACTORY_ROOT")


class _Passthrough:
    """The library's surface with no mapping behind it (root not found)."""

    @staticmethod
    def resolve_channel(name, root=None):
        return name

    @staticmethod
    def channel_names(channel, root=None):
        return (channel,)

    @staticmethod
    def former_channel_ids(root=None):
        return {}

    @staticmethod
    def is_former_id(name, root=None):
        return False

    @staticmethod
    def channel_config_path(channel, root=None):
        return Path(root or ".") / "channels" / f"{channel}.json"

    @staticmethod
    def channel_batch_dirs(channel, pipeline_dir=None, root=None):
        base = Path(pipeline_dir) if pipeline_dir else Path(root or ".") / "pipeline"
        return [base / channel] if (base / channel).is_dir() else []

    @staticmethod
    def batch_dir(channel, batch_id, pipeline_dir=None, root=None):
        base = Path(pipeline_dir) if pipeline_dir else Path(root or ".") / "pipeline"
        d = base / channel / batch_id
        return d if d.is_dir() else None


def _load():
    try:
        root = factory_root()
    except RuntimeError as exc:
        sys.stderr.write(f"[channel-ids] {exc}; a former channel id will not be "
                         f"resolved (CF-0197)\n")
        return None, _Passthrough()
    # A `FACTORY_ROOT` that holds no library is the normal shape of a test
    # root - a temp tree with a `channels/` and nothing else - and the answer
    # there is the identity, not an ImportError out of an import line.
    lib_dir = str(root / LIB_REL.parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    try:
        import channel_ids as mod
    except ImportError as exc:
        sys.stderr.write(f"[channel-ids] no {LIB_REL} under {root} ({exc}); a former "
                         f"channel id will not be resolved (CF-0197)\n")
        return root, _Passthrough()
    return root, mod


ROOT, channel_ids = _load()


def resolve_channel(name, root=None):
    """The current id of a channel that may be named by a former one."""
    return channel_ids.resolve_channel(name, root=root or ROOT)


def channel_names(channel, root=None):
    """Every name this channel's directories have carried, current first."""
    return channel_ids.channel_names(channel, root=root or ROOT)


def channel_config_path(channel, root=None):
    """`channels/<id>.json`, with a former id resolved first."""
    return channel_ids.channel_config_path(channel, root=root or ROOT)


def channel_batch_dirs(channel, pipeline_dir=None, root=None):
    """Every directory under `pipeline/` holding this channel's batches."""
    return channel_ids.channel_batch_dirs(channel, pipeline_dir, root=root or ROOT)


def batch_dir(channel, batch_id, pipeline_dir=None, root=None):
    """One batch's directory, searched under every name the channel has had."""
    return channel_ids.batch_dir(channel, batch_id, pipeline_dir, root=root or ROOT)
