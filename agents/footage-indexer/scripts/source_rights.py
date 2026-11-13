"""CF-0663 (FI-2 of the root's docs/science-footage.md): the rights record of
every source this stage takes, and the licence refusal before a download.

What a source may be taken under is decided upstream: the Trend Hunter judges
every footage candidate's licence against the channel's lists
(`channels/<id>/footage-origin.json` `licences`, CF-0564) with the factory's
common rule (`shared/footage_licence.py` `licence_of`) and writes the verdict
on the candidate (CF-0662):

    evidence.footage_candidates[].licence = {id, accepted, judged, short_name,
        read_from, yt_license, origin, attribution, share_alike, license_url,
        reason}
    evidence.footage_candidates[].footage_origin = <footage_origins[].id> | None

(`origin` of the candidate itself is CF-0297's official / unknown upload, a
different thing, kept here as `upload_origin`.)

This module turns that block into one `rights` record per source:

    {judged, accepted, licence, short_name, license_url, attribution,
     share_alike, footage_origin, credit, credit_from, on_screen, where,
     source_url, upload_origin, reason, read_from}

`credit` / `on_screen` / `where` are the candidate's own per-file credit when
it carries one (`credit`, an archive's Artist line - TH-3), else the origin's
`footage_origins[].attribution` of the channel's footage-origin.json. Nothing
is invented: a candidate without a block (ExampleFilm, a batch written before
CF-0662, a thin-pool supplement) gets `judged: false`, `accepted: null`, the
licence fields null and only what the candidate does say (`footage_origin`,
`upload_origin`). The record goes into

  * the cache entry (`shared/footage/index.json`, beside `official_channel`) -
    `fetch_footage.py --rights-json`, `merge_into_entry()`;
  * `01b-footage-index.json` -> `fetched[].rights` - `ingest_batch.ingest()`;
  * `<id>.shots.json` -> `source_rights` (top level: `source` there has always
    been the media path, a string) - `index_footage.py` reads it from the
    cache entry when it writes the index. An index written before CF-0663
    has no key, which a reader takes as `null` - not invented.

CF-0567 (ExampleTech, the root's docs/tech-footage.md), two kinds more:

  * an own capture (`own_capture-<id>`, the factory's own screen recording) -
    `own_capture_rights()`: decided by its kind, not by a candidate's block:
    `judged: true, accepted: true, licence: own_capture, footage_origin:
    own_capture`, no credit (`credit: null`, attribution `none`), and from the
    recorder's sidecar the page (`url`, `source_url`), `host`, `capture_host`,
    `captured_at` and the `candidate_id` (`own_capture:<id>`);
  * a vendor's official upload - a candidate whose `channel_id` is one of the
    channel's `official_channels[].channels[].id` with `role: proof_quote`:
    `rights_of()` adds `footage_origin: vendor_official` (the entry's
    `origin`), `role: proof_quote`, `channel_id` and `channel_title`, and the
    credit is that origin's. A document with no `proof_quote` channel
    (ExampleFilm, ExampleScience) changes nothing: the keys are not added.

The refusal (`refusal()`) is defence in depth: the Trend Hunter already drops
a refused licence into `footage_candidates_dropped`, so a candidate that still
reaches this stage with `accepted: false`, or whose licence the channel's own
lists refuse, or whose name says NC / ND / non-free, is refused here before
anything is asked of YouTube (`licence_refused`, no attempt spent).

The root module is loaded by path (`_fi_paths.root_candidates()`, then this
checkout's ancestors), under this repo's own name - nothing of the root goes
onto `sys.path`. No copy of the rule lives here; without the root module the
channel's lists cannot be re-read and only the candidate's own verdict and
the NC/ND/non-free floor below decide.
"""
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _fi_paths import root_candidates  # noqa: E402 - CF-0267

LIB_REL = Path("shared") / "footage_licence.py"
MODULE_NAME = "footage_licence_for_footage_indexer"
ORIGIN_FILE = "footage-origin.json"

RIGHTS_KEY = "rights"                 # the cache entry and `fetched[]`
SHOTS_KEY = "source_rights"           # `<id>.shots.json`, top level
LICENCE_REFUSED_CODE = "licence_refused"   # the Trend Hunter's word (CF-0662)
LICENCE_KEY = "licence"
FOOTAGE_ORIGIN_KEY = "footage_origin"
YOUTUBE_URL = "https://www.youtube.com/watch?v={vid}"

# The floor when the channel's lists cannot be read (ExampleFilm has none, or
# the root module is missing): words in a licence's name or id that no
# channel takes - the root rule's `refused` families, matched on whole words.
REFUSED_WORDS = (("nc",), ("nd",), ("non", "free"), ("noncommercial",),
                 ("noderivatives",))


def _lib_path():
    for root in root_candidates():
        if (root / LIB_REL).is_file():
            return (root / LIB_REL).resolve()
    for p in HERE.parents:
        if (p / LIB_REL).is_file():
            return (p / LIB_REL).resolve()
    return None


# CF-0706: the ingest walks topics in a thread pool and each walk asks about
# its first candidate at once. The rule used to be looked up in sys.modules
# without a lock and put there before it was executed, so a second thread got
# the half-executed module and died on `licence_of` (example-science
# 2026-10-12T2001Z). Now a module is handed out only from `_LOADED`, which
# holds nothing but whole modules (executed to the end, `licence_of`
# callable); loading is serialised by `_LOAD_LOCK`.
_LOAD_LOCK = threading.Lock()
_LOADED = {}            # resolved path -> the whole module


def _whole(mod, path):
    return (mod is not None and callable(getattr(mod, "licence_of", None))
            and Path(getattr(mod, "__file__", "") or "").resolve() == path)


def _forget_loaded():
    """Tests: drop what was loaded, so the next call loads again."""
    with _LOAD_LOCK:
        _LOADED.clear()


def licence_rule():
    """-> the root's `footage_licence` module, or None when it is not there
    (or does not execute to the end, or has no `licence_of`). Never a
    half-executed module, from any thread (CF-0706)."""
    path = _lib_path()
    if path is None:
        return None
    mod = _LOADED.get(path)
    if mod is not None:
        return mod
    with _LOAD_LOCK:
        mod = _LOADED.get(path)
        if mod is not None:
            return mod
        held = sys.modules.get(MODULE_NAME)
        if _whole(held, path):
            _LOADED[path] = held
            return held
        try:
            spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
            mod = importlib.util.module_from_spec(spec)
            # in sys.modules while it executes (what an import would do); no
            # reader of this name looks there outside the lock
            sys.modules[MODULE_NAME] = mod
            spec.loader.exec_module(mod)
        except Exception:
            mod = None
        if not _whole(mod, path):
            sys.modules.pop(MODULE_NAME, None)
            return None
        _LOADED[path] = mod
        return mod


def load_origins(channel, root=None):
    """The channel's footage-origin.json as a dict; {} when there is none or
    it does not read (a channel without one is ExampleFilm's footing)."""
    roots = [Path(root)] if root else root_candidates()
    for r in roots:
        p = Path(r) / "channels" / str(channel) / ORIGIN_FILE
        if p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return doc if isinstance(doc, dict) else {}
    return {}


OWN_GRAPHIC = "own_graphic"           # CF-0689, = footage_licence.OWN_GRAPHIC


def own_graphic_origin(origins):
    """CF-0689: the id of the channel's origin under the `own_graphic` licence
    (the graphics the Video Editor draws from the script - never fetched,
    never in the pool, never indexed), or None when the channel has none.
    Its presence in footage-origin.json is the channel's switch: only there
    may a topic stand on the graphics instead of two pool sources. The
    licence's name is the root rule's (`footage_licence.OWN_GRAPHIC`) when
    the root module is there."""
    lib = licence_rule()
    name = getattr(lib, "OWN_GRAPHIC", None) or OWN_GRAPHIC
    for o in (origins or {}).get("footage_origins") or []:
        if isinstance(o, dict) and o.get(LICENCE_KEY) == name:
            return _str(o.get("id")) or name
    return None


def _origin_entry(origins, origin_id):
    if not origin_id:
        return None
    for o in (origins or {}).get("footage_origins") or []:
        if isinstance(o, dict) and o.get("id") == origin_id:
            return o
    return None


def _str(v):
    return v if isinstance(v, str) and v.strip() else None


PROOF_QUOTE = "proof_quote"           # official_channels[].role (CF-0567)
OWN_CAPTURE = "own_capture"           # the licence and the origin (CF-0567)
OWN_CAPTURE_HEAD = "own_capture-"
OWN_CAPTURE_NAME = "own_capture:"


def quote_channel(candidate, origins):
    """CF-0567: the `official_channels` entry (with `role: proof_quote`) whose
    channel id is the candidate's `channel_id`, as `{origin, role, channel_id,
    channel_title}`, else None. Only a listed id counts - a title or a role
    the candidate claims is never enough."""
    cid = _str((candidate or {}).get("channel_id")) if isinstance(candidate, dict) else None
    if not cid:
        return None
    for entry in (origins or {}).get("official_channels") or []:
        if not isinstance(entry, dict) or entry.get("role") != PROOF_QUOTE:
            continue
        for ch in entry.get("channels") or []:
            if isinstance(ch, dict) and ch.get("id") == cid:
                return {"origin": _str(entry.get("origin")), "role": PROOF_QUOTE,
                        "channel_id": cid,
                        "channel_title": _str(ch.get("title")) or _str(entry.get("seen_as"))}
    return None


def rights_of(vid, candidate=None, origins=None):
    """-> the `rights` record of source `vid` from its candidate record (or
    None) and the channel's footage-origin document (or None)."""
    cand = candidate if isinstance(candidate, dict) else {}
    block = cand.get(LICENCE_KEY)
    block = block if isinstance(block, dict) else None
    fo = _str(cand.get(FOOTAGE_ORIGIN_KEY)) or _str((block or {}).get("origin"))
    quote = quote_channel(cand, origins)              # CF-0567
    if quote and quote["origin"]:
        fo = quote["origin"]
    out = {
        "judged": False, "accepted": None, "licence": None, "short_name": None,
        "license_url": None, "attribution": None, "share_alike": None,
        "footage_origin": fo, "credit": None, "credit_from": None,
        "on_screen": None, "where": None,
        "source_url": _str(cand.get("source_url")) or _str(cand.get("download_url"))
        or YOUTUBE_URL.format(vid=vid),
        "upload_origin": _str(cand.get("origin")),
        "reason": None,
        "read_from": "candidate" if block else "none",
    }
    if block is None:
        out["reason"] = ("the candidate carries no licence block (a channel without "
                         "`licences`, a batch written before CF-0662, or a source not "
                         "offered by the Trend Hunter) - no licence judgement")
    else:
        out.update(judged=bool(block.get("judged")),
                   accepted=block.get("accepted") if block.get("judged") else None,
                   licence=block.get("id"), short_name=block.get("short_name"),
                   license_url=block.get("license_url"),
                   attribution=block.get("attribution"),
                   share_alike=block.get("share_alike"), reason=block.get("reason"))
    credit = _str(cand.get("credit"))
    entry = _origin_entry(origins, fo)
    att = (entry or {}).get("attribution") if isinstance((entry or {}).get("attribution"),
                                                         dict) else None
    if credit:
        out.update(credit=credit, credit_from="candidate")
    elif att and _str(att.get("credit")):
        out.update(credit=att["credit"], credit_from="footage_origins")
    if att:
        out.update(on_screen=att.get("on_screen") if isinstance(att.get("on_screen"), bool)
                   else None, where=att.get("where"))
    if quote:
        out.update(role=quote["role"], channel_id=quote["channel_id"],
                   channel_title=quote["channel_title"])
    return out


def own_capture_rights(vid, candidate=None, sidecar=None, origins=None):
    """CF-0567: the `rights` record of own capture `vid` (`own_capture-<id>` or
    `own_capture:<id>`) - by its kind, with the page and the host read from
    the recorder's `sidecar` (`<id>.own_capture.json`) when there is one, else
    from the candidate. No credit: the footage is ours."""
    cand = candidate if isinstance(candidate, dict) else {}
    side = sidecar if isinstance(sidecar, dict) else {}
    s = str(vid or "")
    tail = (s[len(OWN_CAPTURE_NAME):] if s.startswith(OWN_CAPTURE_NAME)
            else s[len(OWN_CAPTURE_HEAD):] if s.startswith(OWN_CAPTURE_HEAD) else s)
    url = _str(side.get("url")) or _str(cand.get("url")) or _str(cand.get("source_url"))
    entry = _origin_entry(origins, OWN_CAPTURE)
    att = (entry or {}).get("attribution") if isinstance((entry or {}).get("attribution"),
                                                         dict) else None
    space = side.get("space") if isinstance(side.get("space"), dict) else {}
    return {
        "judged": True, "accepted": True, "licence": OWN_CAPTURE,
        "short_name": "own capture", "license_url": None, "attribution": "none",
        "share_alike": False, "footage_origin": OWN_CAPTURE,
        "credit": None, "credit_from": None,
        "on_screen": False,
        "where": (att or {}).get("where") if att else None,
        "source_url": url,
        "upload_origin": None,
        "reason": ("the factory's own screen recording (CF-0567): no licence is "
                   "needed and none is granted; decided by the source's kind"),
        "read_from": "sidecar" if side else "candidate",
        "url": url,
        "final_url": _str(side.get("final_url")),
        "host": _str(side.get("host")) or _str(cand.get("host")),
        "capture_host": _str(side.get("capture_host")) or _str(cand.get("capture_host")),
        "captured_at": _str(side.get("captured_at")),
        "space_licence": _str(space.get("licence")),
        "candidate_id": OWN_CAPTURE_NAME + re.sub(r"[^A-Za-z0-9_-]", "_", tail),
    }


def is_own_capture_rights(rights):
    """CF-0567: a rights record that names the licence or the origin `own_capture`."""
    r = rights if isinstance(rights, dict) else {}
    return OWN_CAPTURE in (r.get(LICENCE_KEY), r.get(FOOTAGE_ORIGIN_KEY))


def _words(text):
    return re.findall(r"[0-9a-z]+", str(text or "").lower())


def _names_refused(*names):
    for name in names:
        w = _words(name)
        for phrase in REFUSED_WORDS:
            n = len(phrase)
            if any(tuple(w[k:k + n]) == phrase for k in range(len(w) - n + 1)):
                return name
    return None


def refusal(vid, candidate=None, origins=None, rule="auto"):
    """-> the reason (a sentence) why candidate `vid` may not be downloaded on
    its licence, or None. Asked before anything is asked of YouTube.

    In order: the candidate's own verdict (`licence.judged` and `accepted`
    false); the channel's lists, re-read by the root rule when the channel has
    any and the candidate names a licence; the NC / ND / non-free floor on the
    licence's name and id. A candidate with no licence block is never refused
    here - nothing was said about it (ExampleFilm's footing)."""
    cand = candidate if isinstance(candidate, dict) else {}
    block = cand.get(LICENCE_KEY)
    if not isinstance(block, dict):
        return None
    name = block.get("short_name")
    if block.get("judged") and block.get("accepted") is False:
        return (f"the Trend Hunter refused licence {name!r} of {vid}: "
                f"{block.get('reason') or 'no reason given'}")
    lists = (origins or {}).get("licences")
    if lists and _str(name):
        mod = licence_rule() if rule == "auto" else rule
        if mod is not None:
            v = mod.licence_of(name, lists, non_free=bool(cand.get("licence_non_free")))
            if not v.get("accepted"):
                return (f"licence {name!r} of {vid} is not one this channel takes: "
                        f"{v.get('reason')} (footage-origin.json `licences`, re-read "
                        f"by the indexer)")
    if cand.get("licence_non_free") or block.get("id") == "non_free":
        return f"licence {name!r} of {vid} is marked non-free by its archive"
    hit = _names_refused(name, block.get("id"))
    if hit:
        return (f"licence {hit!r} of {vid} names a family no channel takes "
                f"(NC / ND / non-free)")
    return None


def merge_into_entry(entry, rights):
    """Put `rights` on a cache entry. A judged record already there is not
    replaced by an unjudged one (a ExampleFilm batch reusing a source a
    Science batch judged says less about it, not something else). Returns
    whether the entry changed."""
    if not isinstance(rights, dict) or not isinstance(entry, dict):
        return False
    held = entry.get(RIGHTS_KEY)
    if isinstance(held, dict) and held.get("judged") and not rights.get("judged"):
        return False
    if held == rights:
        return False
    entry[RIGHTS_KEY] = rights
    return True


def from_cache(video, entries):
    """The `rights` of the cache entry whose file is `video` (or whose id is
    its stem), else None - never invented."""
    video = Path(video)
    try:
        want = video.resolve()
    except OSError:
        want = video
    for e in entries or ():
        if not isinstance(e, dict):
            continue
        p = e.get("path")
        same = False
        if p:
            try:
                same = Path(p).resolve() == want
            except OSError:
                same = Path(p) == video
        if same or (not p and e.get("id") == video.stem):
            r = e.get(RIGHTS_KEY)
            return r if isinstance(r, dict) else None
    return None
