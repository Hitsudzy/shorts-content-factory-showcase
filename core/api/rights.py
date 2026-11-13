"""Read-only routes over a channel's configuration lists: the advisory
rights-holder list, the footage origins, the fact sources and the affiliate
slot. Only through the factory's own functions (`api/factory.py`), nothing of
the API's own on top:

    shared/channel_data.py       rights_holders, footage_origin, fact_sources,
                                 channel_list_path
    shared/footage_licence.py    footage_origin_errors

Every list answer carries `sha256` - the file's as read
(`channel_list_write.list_sha256`; null without a file), the base a write of the
list is planned from (`api/channel_lists.py`). A channel without the file is
`doc: null` with the factory's line in `missing`.

Every refusal is a `BatchFault` (`{message, code, details}`). `FACTORY_KW`
holds the factory's clock (`now`) - empty in production; the tests put a fixed
one there.
"""
from pathlib import Path

from . import factory, paths
from .batches import BatchFault, _channel

#: The factory's own injection points - empty in production.
FACTORY_KW = {}


def _fault(status, code, e):
    return BatchFault(status, code, str(e), [f"{type(e).__name__}: {e}"])


def _rel(root, p):
    """Relative to the root, `.../<its last part>` outside it - never the
    absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


# ---------------------------------------------------------------- a channel's lists
def _channel_list(root, channel, name, read, code):
    cid = _channel(root, channel)
    cd = factory.channel_data()
    try:
        path = cd.channel_list_path(cid, name, Path(root))
    except cd.ChannelDataError as e:
        raise _fault(409, code, e) from e
    rel = _rel(root, path)
    if not path.is_file():
        try:
            read(cid, Path(root))
        except cd.ChannelDataError as e:
            return cid, rel, None, str(e)
    try:
        return cid, rel, read(cid, Path(root)), None
    except cd.ChannelDataError as e:
        raise _fault(409, code, e) from e


def _sha(root, cid, name):
    """CC-0114: the list file's sha256 as the factory's writer takes it back
    (`channel_list_write.list_sha256`), None without a file."""
    return factory.channel_list_write().list_sha256(cid, name, Path(root))


def rights_holders(root, channel):
    """`channel_data.rights_holders`: the channel's advisory rights-holder list
    and its sha256."""
    cd = factory.channel_data()
    cid, rel, doc, missing = _channel_list(root, channel, "rights-holders", cd.rights_holders,
                                           "rights_holders_unreadable")
    return paths.clean({"channel": cid, "path": rel, "doc": doc, "missing": missing,
                        "sha256": _sha(root, cid, "rights-holders")}, root)


def footage_origin(root, channel):
    """`channel_data.footage_origin` and `footage_licence.footage_origin_errors`."""
    cd, fl = factory.channel_data(), factory.footage_licence()
    cid, rel, doc, missing = _channel_list(root, channel, "footage-origin", cd.footage_origin,
                                           "footage_origin_unreadable")
    return {"channel": cid, "path": rel, "doc": doc, "missing": missing,
            "sha256": _sha(root, cid, "footage-origin"),
            "errors": fl.footage_origin_errors(doc) if doc is not None else []}


def _lines(errs):
    return [str(e) for e in errs]


def fact_sources(root, channel):
    """`channel_data.fact_sources` with its kinds and the fact rule's,
    the AI-bot rule's and the attribution terms' errors."""
    cd, fr = factory.channel_data(), factory.fact_rule()
    cid, rel, doc, missing = _channel_list(root, channel, "fact-sources", cd.fact_sources,
                                           "fact_sources_unreadable")
    out = {"channel": cid, "path": rel, "doc": doc, "missing": missing, "kinds": None,
           "sha256": _sha(root, cid, "fact-sources"), "errors": []}
    if doc is not None:
        errs = _lines(fr.validate_sources(doc))
        try:
            errs += _lines(cd.source_policy_errors(cid, Path(root)))
        except cd.ChannelDataError as e:
            errs.append(str(e))
        errs += _lines(cd.attribution_terms_errors(doc))
        try:
            out["kinds"] = list(cd.fact_kinds(cid, Path(root)))
        except cd.ChannelDataError:
            pass                                    # validate_sources says why
        out["errors"] = errs
    return paths.clean(out, root)


def affiliate(root, channel):
    """The channel's affiliate slot: the config's block and switch, the table
    beside it (`read_table`), `channel_errors` over both."""
    cid = _channel(root, channel)
    cd, af = factory.channel_data(), factory.affiliate()
    cfg_path = Path(root) / factory.CHANNELS_SUBDIR / f"{cid}.json"
    try:
        cfg = cd._channel_config(cid, Path(root))
    except cd.ChannelDataError as e:
        raise _fault(409, "affiliate_unreadable", e) from e
    if not isinstance(cfg, dict):
        raise BatchFault(409, "affiliate_unreadable", f"Конфиг канала {cid} - не объект JSON.",
                         [f"{factory.CHANNELS_SUBDIR}/{cid}.json is not a JSON object"])
    table, why = af.read_table(cfg_path)
    if table is None and af.table_path(cfg_path).is_file():
        raise BatchFault(409, "affiliate_unreadable", f"Таблица партнёрских ссылок канала "
                                                      f"{cid} не читается как JSON.",
                         _lines(why))
    block = cfg.get(af.KEY)
    out = {"channel": cid, "path": _rel(root, af.table_path(cfg_path)),
           "enabled": af.enabled(cfg), "block": block if isinstance(block, dict) else None,
           "doc": table, "missing": None if table is not None else (why[0] if why else None),
           "sha256": _sha(root, cid, "affiliate"),
           "errors": _lines(af.channel_errors(cfg, cfg_path))}
    return paths.clean(out, root)

