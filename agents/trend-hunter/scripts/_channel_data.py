"""CF-0627 (CF-0561): the one place in this repo that finds the factory's
channel-data contract (`<root>/shared/channel_data.py`) and hands it to the
scripts:

    from _channel_data import channel_data

    sources = channel_data.fact_sources(channel)          # the batch's channel
    official = channel_data.footage_origin(channel)["official_channels"]
    ceil = channel_data.rss_house_ceil(channel)
    feeds = channel_data.feed_urls(channel)              # what fetch_rss_news reads
    text_feeds = channel_data.support_feed_urls(channel) # whose excerpt may reach the writer

Why. The outlets a fact may be taken from (and the kinds of fact), the
official YouTube channels of footage and the ceiling of publishing houses in
the trend score are a *channel's* lists (`channels/<id>/...`,
`docs/channel-data.md` of the root), not the hunter's and not the factory's:
a science channel takes its facts from Nature, not from Variety. The root
holds the one reader; this file only *finds* it - the same way `_channel_ids`
finds `shared/channel_ids.py` - and never keeps a list of its own.

Lookup, in order:

  1. `<factory_root()>/shared/channel_data.py` (`FACTORY_ROOT` wins, as
     everywhere in this repo);
  2. the nearest ancestor of this file that holds `shared/channel_data.py` -
     a test's `FACTORY_ROOT` is a temp tree with `channels/` and nothing else,
     and it is the *data* that comes from there, not the reader.

The module is loaded by path (`spec_from_file_location`), so nothing of the
root goes onto `sys.path`. Every function here passes `root=factory_root()`
when the caller names none, so the data is always the root this repo runs
against (a test's stand-in root included).

There is no fallback list. If no reader can be found at all (this repo copied
somewhere on its own) every call raises `ChannelDataError` naming what is
missing: a stage without its channel's list has nothing to judge by and must
say so, not judge by an empty one or by another channel's.
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
    spec = importlib.util.spec_from_file_location("channel_data_for_trend_hunter", path)
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
    #: CF-0634: the uses that let an outlet's text be read (`read_text`) - the
    #: root's, so the gate (`source_gate.py`) and the root validator agree
    TEXT_USES = getattr(_LIB, "TEXT_USES", ("read_text",))

    @staticmethod
    def fact_sources(channel, root=None):
        return _LIB.fact_sources(channel, _root(root))

    @staticmethod
    def fact_kinds(channel, root=None):
        return _LIB.fact_kinds(channel, _root(root))

    @staticmethod
    def footage_origin(channel, root=None):
        return _LIB.footage_origin(channel, _root(root))

    @staticmethod
    def rss_house_ceil(channel, root=None):
        return _LIB.rss_house_ceil(channel, _root(root))

    @staticmethod
    def feed_urls(channel, root=None):
        """CF-0634: every feed the collector reads for the channel
        (`sources.rss.feeds[].url`); a channel whose feeds break the AI-bot
        rule is a refusal (`ChannelDataError`), not a shorter list."""
        return _LIB.feed_urls(channel, _root(root))

    @staticmethod
    def support_feed_urls(channel, root=None):
        """CF-0634: the feeds whose excerpt may go into a topic's support
        text (`rss_summary`) - `use: read_text` only; a `headline_only` feed
        chooses topics and nothing of it reaches the writer (CF-0635)."""
        return _LIB.support_feed_urls(channel, _root(root))

    @staticmethod
    def entry_policy_errors(entry, ctx, uses):
        """CF-0634: one outlet or feed against the AI-bot rule - the root's
        judgement (`use` among `uses`, a well-formed `ai_policy`, `allowed`
        for a text use, not closed to every agent); [] when it stands."""
        return _LIB.entry_policy_errors(entry, ctx, uses)

    @staticmethod
    def channel_id(channel, root=None):
        return _LIB.channel_id(channel, _root(root))


channel_data = _Contract()
