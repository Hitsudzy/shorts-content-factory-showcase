"""CF-0629 (CF-0561): the one place in this repo that finds the factory's
channel-data contract (`<root>/shared/channel_data.py`) and hands it to the
scripts:

    from _channel_data import channel_data

    doc = channel_data.rights_holders(channel, root)    # the batch's channel

Why. The rights holders a channel is careful with are the *channel's* list
(`channels/<id>/rights-holder-blacklist.json`, `docs/channel-data.md` of the
root), not this stage's and not the factory's: a science channel's rights
holders are not a film channel's studios, and the Analyst writes each
channel's own YouTube claims into that channel's file. The root holds the one
reader; this file only *finds* it - the way `_channel_ids` finds
`shared/channel_ids.py` and the Trend Hunter's / Content Researcher's
`scripts/_channel_data.py` find this same module (CF-0627, CF-0628) - and
never keeps a list of its own.

Lookup, in order:

  1. `<factory_root()>/shared/channel_data.py` (`FACTORY_ROOT` wins, as
     everywhere in this repo);
  2. the nearest ancestor of this file that holds `shared/channel_data.py` -
     a test's root is a temp tree with `channels/` and nothing else, and it is
     the *data* that comes from there, not the reader.

The module is loaded by path (`spec_from_file_location`), so nothing of the
root goes onto `sys.path`. Every function here passes `root=factory_root()`
when the caller names none; step 4b (`rights_holder_info.py`) always names
one.

There is no fallback list. If no reader can be found at all (this repo copied
somewhere on its own) every call raises `ChannelDataError` naming what is
missing: the evidence step without its channel's list adds no evidence and
says why, it does not borrow another channel's list.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

LIB_REL = Path("shared") / "channel_data.py"


def library_path():
    """Where the reader is, or None."""
    try:
        path = factory_root() / LIB_REL
        if path.is_file():
            return path
    except RuntimeError:
        pass
    for p in HERE.parents:
        if (p / LIB_REL).is_file():
            return p / LIB_REL
    return None


class _Missing:
    """The contract's surface with no reader behind it: every list refuses."""

    class ChannelDataError(Exception):
        pass

    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise self.ChannelDataError(
                f"no {LIB_REL} found (FACTORY_ROOT or an ancestor of {HERE}); the "
                f"channel's lists live in the factory root and there is no copy "
                f"here to fall back to (CF-0561)")
        return refuse


def _load():
    path = library_path()
    if path is None:
        return _Missing()
    spec = importlib.util.spec_from_file_location("channel_data_for_compliance_checker",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LIB = _load()
ChannelDataError = _LIB.ChannelDataError


def _root(root):
    return Path(root) if root else factory_root()


class _Contract:
    """`shared/channel_data.py` with `root` defaulting to this repo's
    `factory_root()` (not the library's own `find_root`, which does not read
    `FACTORY_ROOT`)."""

    ChannelDataError = ChannelDataError

    @staticmethod
    def rights_holders(channel, root=None):
        return _LIB.rights_holders(channel, _root(root))

    @staticmethod
    def channel_list_path(channel, name, root=None):
        return _LIB.channel_list_path(channel, name, _root(root))

    @staticmethod
    def channel_id(channel, root=None):
        return _LIB.channel_id(channel, _root(root))


channel_data = _Contract()
