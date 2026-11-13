#!/usr/bin/env python3
"""CF-0634: the one door through which the hunter reads text from a host
that is not Wikipedia.

The factory's AI-bot rule (CF-0557, narrowed by CF-0635; the root's
`docs/channel-data.md` «Sources and the AI-bot rule»): an outlet's text is
read, and may reach the writer, only when the channel's own
`channels/<id>/fact-sources.json` lists it with `use: read_text` and its
`ai_policy.verdict` is `allowed` (robots.txt does not close it to Anthropic's
bots, nor to every agent). `cite_only` - every example-film outlet but
Wikipedia - is a name a fact may stand on and is never downloaded; an outlet
the list does not name, or names under `do_not_take`, is not read at all.

    import source_gate
    text = source_gate.read_text(url, sources, fetch)   # sources: the channel's list

`read_text` checks first and only then calls `fetch(url)`; a refusal raises
`SourceClosed` with the reason, and nothing is asked. `refusal(url, sources)`
is the same check as a value (None = may be read). The check is the root's
own: `shared/factrule/scale_support.channel_gate(sources).refusal(url)`
(CF-0673, through `_scale_support.py`), which finds the outlet with
`fact_rule.source_of` and judges it with `channel_data.entry_policy_errors`
and the text uses - so the hunter, the scale step of the Content Researcher
and the root validator answer the same, and this file keeps no copy of the
rule. `outlet_of` stays here only to hand a caller the listed row itself
(`support_text.wikidata_outlet`).

Wikipedia is read through the factory's one client (`_wikipedia.py`), under
its own entry of the same list (`use: read_text`, `allowed`, checked by the
root validator). The first host past Wikipedia is TVmaze (CF-0636): the
shared client (`_tvmaze.py`) takes `check(url, sources)` with the channel's
list as its gate and calls it before every request, a cached answer included
(`support_text.tvmaze_client_for`); Wikidata (CF-0637) the same way
(`_wikidata.py`, `support_text.wikidata_client_for` - the `wikidata` outlet is
asked before the gateway's search too). `tests/test_source_rule.py` holds that
`support_text.py` and `fact_search.py` reach the network past those clients
and this door by no path.

How a readable outlet comes in (as TVmaze did): one entry in the channel's
`fact-sources.json` tiers - `id`, `hosts` (`api.tvmaze.com`), `use:
read_text`, and the `ai_policy` that `python3 shared/source_policy.py check
<channel> --write` writes (it must come out `allowed`) - and a reader that
fetches through `source_gate.read_text(url, sources, fetch)` or hands `check`
to its client as the gate. Nothing in this file changes: the list says what
may be read.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _factrule import fact_rule  # noqa: E402


class SourceClosed(RuntimeError):
    """The outlet may not be read under the channel's AI-bot rule."""


def outlet_of(url, sources):
    """The tier entry of the channel's list whose `hosts` hold the URL's host
    (`fact_rule.source_of`), or None (not listed, or under `do_not_take`)."""
    where = fact_rule.source_of(url, sources)
    if where["banned"] or where["tier"] is None:
        return None
    for row in ((sources or {}).get("tiers") or {}).get(str(where["tier"])) or []:
        if isinstance(row, dict) and row.get("id") == where["id"]:
            return row
    return None


def channel_gate(sources):
    """The root's gate over the channel's list (`shared/factrule/
    scale_support.channel_gate`, CF-0673), loaded on first use through
    `_scale_support.py` - importing this module does not load it."""
    from _scale_support import scale_support
    return scale_support.channel_gate(sources)


def refusal(url, sources):
    """Why `url` may not be read as text under the channel's list `sources`
    (a fact-sources document) - None when it may.

    The answer is the root's `channel_gate(sources).refusal(url)` (CF-0673):
    the hunter keeps no copy of the rule, nor of its words - the empty-list
    refusal's tail (CF-0634's «no outlet is readable without one») is the
    root's too."""
    return channel_gate(sources).refusal(url)


def check(url, sources):
    """Raise `SourceClosed` unless `url` may be read as text."""
    why = refusal(url, sources)
    if why:
        raise SourceClosed(why)


def read_text(url, sources, fetch, *args, **kwargs):
    """`fetch(url, *args, **kwargs)` after the check - the only way a text of
    a host other than Wikipedia is read by this stage."""
    check(url, sources)
    return fetch(url, *args, **kwargs)


# --------------------------------------------------------------------------
# CF-0757: a company's own page (tier 1), read for a fact
# --------------------------------------------------------------------------
# The user's decision of 15.10 (hotfix 2.4.1, «берём»): when Wikipedia and the
# feeds give no fact, the hunter reads the official post of the company the
# story is about - the primary source the channel's list names in tier 1
# (example-tech: apple.com, blog.google, openai.com...). That door is narrower
# than `read_text` in one way and wider in one: only a **tier-1** outlet of
# the list, and only one whose `ai_policy.verdict` is `allowed` (the source
# rule of 08.10: robots.txt does not close the path to Anthropic's agents or
# to `*`; terms that forbid AI write `forbidden`), whatever its `use` - a
# vendor page is the fact's own source, read for that fact and nothing else.
# `unknown` is not permission, `forbidden` is never asked, `do_not_take` and
# an unlisted host are never asked. The list is data: a verdict the root
# re-checks to `allowed` opens the outlet with no change here.
VENDOR_TIER = 1


def vendor_page_refusal(url, sources):
    """Why `url` may not be read as a company's own page under the channel's
    list `sources` - None when it may (tier 1, `ai_policy.verdict: allowed`)."""
    if not sources:
        return f"{url}: no fact-sources list of the channel was given - no page is read without one"
    where = fact_rule.source_of(url, sources)
    if not where["host"]:
        return f"{url!r} is not a URL with a host"
    if where["banned"]:
        return f"{where['host']}: the channel's list does not take it ({where['banned']})"
    if where["tier"] != VENDOR_TIER:
        return (f"{where['host']}: not a tier-{VENDOR_TIER} outlet of the channel's list "
                f"(tier {where['tier']}) - only a company's own page is read for a fact")
    row = outlet_of(url, sources) or {}
    verdict = (row.get("ai_policy") or {}).get("verdict") if isinstance(row, dict) else None
    if verdict != "allowed":
        return (f"{where['host']}: outlet {where['id']} has ai_policy.verdict "
                f"{verdict or 'missing'!r} - read only when it is 'allowed'")
    return None


def read_vendor_page(url, sources, fetch, *args, **kwargs):
    """`fetch(url, ...)` after `vendor_page_refusal` - the only way the hunter
    reads a company's own page (`vendor_page.py`)."""
    why = vendor_page_refusal(url, sources)
    if why:
        raise SourceClosed(why)
    return fetch(url, *args, **kwargs)
