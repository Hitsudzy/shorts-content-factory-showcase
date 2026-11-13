#!/usr/bin/env python3
"""CF-0554: how long the Wikipedia text a plot reveal stands on has stood.

The grill of 2026-10-05 (CF-0546, Q10). A plot reveal - who killed whom, who
turned out to be whom, who died, who survived, who betrayed whom, how it
ended - is the one kind of claim whose source is written in a hurry: the
description of an episode appears on Wikipedia ~2-3 hours after the
broadcast and is edited, argued over and reverted for hours after that (the
Harbourlights finale: no description at 00:40 UTC on 05.10, the right killer,
sheriff Kerry Kane, by 03:13; at 09:27 an editor "added Hal Garrett's killer"
to the cast list and it was undone 19 minutes later; the 0701Z batch started
at 07:01, ~4 hours after the description). So a reveal passes only when the
text it quotes has stood in the article for `STABLE_HOURS` (6) without being
taken out, or another resource (a publication's headline / summary among the
topic's RSS pieces) says it too - the second half is `claim_judge.py`'s; this
module answers the first.

**What "stood for 6 hours" means here.** `now` is the moment of the check
(a replay passes the batch's own time; revisions after `now` do not exist
for it). The revision in effect at `now - 6 h` (the *base*) carries the
quote, and so does every revision since, up to the one in effect at `now`.
The quote is looked for as words: the revision's wikitext is read as a reader
sees it (comments and references out, links as their words, bold / italic
marks off, a few wrapping templates unwrapped) and the quote's words must be
a contiguous run of its words - the same words in the same order, the
CF-0552 verbatim rule, minus punctuation.

States of one quote (`state`):

  stable      - in the base and in every revision since (`age_h` is the age of
                the base revision: at least, `age_at_least`);
  fresh       - not in the base: written inside the window (`age_h` from the
                first revision of the window that has it - found by halving,
                the number is for the report, the verdict does not need it);
                a page created inside the window is fresh too;
  reverted    - in the base and now, but some revision in between did not
                have it (`since` - the revision that put it back);
  gone        - not in the revision in effect at `now` (taken out after the
                hunter read it); a replay before the revision the hunter read
                finds the words not written yet - `fresh`, `age_h` 0;
  unsettled   - more than `MAX_REVISION_READS` revisions in the window, or
                the history ran past `MAX_HISTORY_PAGES` pages before
                reaching the base: an article edited that much is not
                settled, and reading all of it is not this check's job;
  unreadable  - the quote is not found even in the revision the hunter read
                (the piece's `revision_id`): this reader cannot follow the
                page's markup, so it cannot say how long the words stood;
  unreachable - Wikipedia could not be asked (`WikipediaError`);
  no_page     - the piece is not a Wikipedia piece with a page key.

Only `stable` is stable. Every other state leaves the reveal to the second
source; with none, `claim_judge.py` strikes it (`reveal_too_fresh`, Q3).

**On the network** (the client's etiquette is `shared/wikipedia/
wikipedia_api.py`'s, CF-0237; this adds two endpoints of the same Core REST
API on the same host, GET only): `/page/<title>/history` (20 revisions a
page, `older_than` for the next) and `/revision/<id>` (one revision's
wikitext). Asked only for a claim the judge called a reveal, only for the
pages its quotes come from. Answers go through the batch's Wikipedia cache
(`<batch>/work/wikipedia-cache/`, `cached_transport`): a revision never
changes, so it is kept for good; a history page is asked again after
`HISTORY_MAX_AGE_SECONDS`.

Stdlib only; the client is loaded by path under its one module name.
"""
import datetime as dt
import html
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RULE = "CF-0554"
WIKIPEDIA_API_REL = Path("shared") / "wikipedia" / "wikipedia_api.py"
MODULE_NAME = "factory_wikipedia_api"     # = wikipedia_api.MODULE_NAME
TOOL_NAME = "shorts-content-factory-claim-judge"

STABLE_HOURS = 6.0
MAX_HISTORY_PAGES = 5                     # 20 revisions a page, from the time of the check back
MAX_LATER_PAGES = 20                      # pages after it, which a replay walks past
MAX_REVISION_READS = 40
HISTORY_MAX_AGE_SECONDS = 600
REVISION_PATH = "/revision/{id}"

STATE_STABLE = "stable"
STATE_FRESH = "fresh"
STATE_REVERTED = "reverted"
STATE_GONE = "gone"
STATE_UNSETTLED = "unsettled"
STATE_UNREADABLE = "unreadable"
STATE_UNREACHABLE = "unreachable"
STATE_NO_PAGE = "no_page"
STATES = (STATE_STABLE, STATE_FRESH, STATE_REVERTED, STATE_GONE, STATE_UNSETTLED,
          STATE_UNREADABLE, STATE_UNREACHABLE, STATE_NO_PAGE)


def _load_claims():
    name = "factory_claims_cf0552"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "claims.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


claims = _load_claims()


def wikipedia_api(root=None):
    """The shared client module under its one `sys.modules` name (CF-0551)."""
    path = ((Path(root) if root else ROOT) / WIKIPEDIA_API_REL).resolve()
    held = sys.modules.get(MODULE_NAME)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ time
def parse_time(value):
    """An aware UTC datetime out of an ISO string (`...Z`), a datetime, or
    None."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    try:
        t = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def hours(a, b):
    return round((a - b).total_seconds() / 3600.0, 2)


# ------------------------------------------------------------------ words
_WRAPPERS = ("nowrap", "nobr", "small", "big", "em", "strong", "smallcaps", "noitalic",
             "lang", "transl", "abbr", "sic")
_WRAP_RE = re.compile(r"\{\{\s*(?:%s)\s*\|(?:[a-z-]{2,8}\|)?([^{}|]*)(?:\|[^{}]*)?\}\}"
                      % "|".join(_WRAPPERS), re.I)


def reader_text(wikitext):
    """The wikitext as a reader would see its words - enough for a quote of
    the plain text the hunter wrote to be found in it again."""
    text = re.sub(r"<!--.*?-->", " ", wikitext or "", flags=re.S)
    text = re.sub(r"<ref[^>]*/>", " ", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref\s*>", " ", text, flags=re.S | re.I)
    text = re.sub(r"\{\{\s*'\s*\}\}", "'", text)
    for _ in range(3):
        text = _WRAP_RE.sub(r"\1", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _run(words):
    return " " + " ".join(words) + " "


def contains(wikitext, quote):
    """The quote's words are a contiguous run of the revision's words."""
    q = claims.words(claims.norm_quote(quote or ""))
    if not q:
        return False
    return _run(q) in _run(claims.words(reader_text(wikitext)))


def page_key(piece):
    """The page a Wikipedia piece was read from: `wikipedia:<key>[#ep8]`."""
    if not isinstance(piece, dict) or piece.get("source", "wikipedia") != "wikipedia":
        return None
    pid = piece.get("id") or ""
    if not pid.startswith("wikipedia:"):
        return None
    key = pid[len("wikipedia:"):].split("#", 1)[0].strip()
    return key or None


# ------------------------------------------------------------------ source
class Revisions:
    """History pages and revision texts through one (cached) client; the
    same page or revision is asked once per process."""

    def __init__(self, client, wp=None):
        self.client = client
        self.wp = wp or wikipedia_api()
        self._history = {}
        self._source = {}
        self.reads = 0

    def history(self, key, older_than=None):
        """One page of the history, newest first: [{id, at, comment, delta}]
        and the id to continue from (None at the end)."""
        memo = (key, older_than)
        if memo not in self._history:
            params = {"older_than": older_than} if older_than else None
            data = self.client.get(self.wp.page_path(key) + "/history", params,
                                   missing_ok=True) or {}
            revs = [{"id": r.get("id"), "at": parse_time(r.get("timestamp")),
                     "comment": r.get("comment"), "delta": r.get("delta")}
                    for r in data.get("revisions") or [] if r.get("id")]
            more = revs[-1]["id"] if data.get("older") and revs else None
            self._history[memo] = (revs, more)
        return self._history[memo]

    def source(self, rev_id):
        if rev_id not in self._source:
            data = self.client.get(REVISION_PATH.format(id=int(rev_id)), missing_ok=True) or {}
            self._source[rev_id] = data.get("source")
            self.reads += 1
        return self._source[rev_id]


def _routing_transport(cache_dir, wp, transport=None):
    """History pages kept `HISTORY_MAX_AGE_SECONDS`, revisions for good."""
    short = wp.cached_transport(cache_dir, transport, max_age_seconds=HISTORY_MAX_AGE_SECONDS)
    forever = wp.cached_transport(cache_dir, transport, max_age_seconds=None)

    def _transport(url, headers, timeout=wp.DEFAULT_TIMEOUT):
        return (short if "/history" in url else forever)(url, headers, timeout)
    return _transport


def revisions_for(cache_dir=None, transport=None, root=None, **kw):
    """A `Revisions` on the shared client, through the batch's cache."""
    wp = wikipedia_api(root)
    if cache_dir:
        transport = _routing_transport(cache_dir, wp, transport)
    return Revisions(wp.WikipediaClient(transport=transport, tool_name=TOOL_NAME, **kw), wp)


# ------------------------------------------------------------------ the age
def _window(revisions, key, now, cutoff):
    """(revisions after the cutoff up to now, newest first; the base - the
    one in effect at the cutoff - or None; complete). Revisions after `now`
    are not there for a check made at `now`."""
    window, older, pages, skipped = [], None, 0, 0
    while pages < MAX_HISTORY_PAGES and skipped < MAX_LATER_PAGES:
        revs, more = revisions.history(key, older)
        if any(r["at"] is not None and r["at"] <= now for r in revs):
            pages += 1
        else:
            skipped += 1                       # a replay walks past what came after it
        for r in revs:
            if r["at"] is None or r["at"] > now:
                continue
            if r["at"] <= cutoff:
                return window, r, True
            window.append(r)
        if not more:
            return window, None, True          # the page was created inside the window
        older = more
    return window, None, False


def quote_age(revisions, piece, quote, now=None, stable_hours=STABLE_HOURS):
    """How long `quote` has stood in the page of `piece` at `now` - see the
    module docstring for the states. Returns {page, revision_id, state,
    stable, age_h, age_at_least, since, since_revision, reads, detail}."""
    now = parse_time(now) or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=stable_hours)
    key = page_key(piece)
    out = {"page": key, "revision_id": (piece or {}).get("revision_id"), "state": None,
           "stable": False, "age_h": None, "age_at_least": False, "since": None,
           "since_revision": None, "reads": 0, "detail": None}

    def done(state, since=None, detail=None, at_least=False):
        out.update(state=state, stable=state == STATE_STABLE, detail=detail,
                   age_at_least=at_least)
        if since is not None:
            out.update(since=iso(since["at"]), since_revision=since["id"],
                       age_h=hours(now, since["at"]))
        out["reads"] = revisions.reads - reads0
        return out

    if key is None:
        reads0 = revisions.reads
        return done(STATE_NO_PAGE, detail="not a Wikipedia piece")
    reads0 = revisions.reads
    wp_error = getattr(revisions.wp, "WikipediaError", RuntimeError)
    try:
        window, base, complete = _window(revisions, key, now, cutoff)
        if not complete:
            return done(STATE_UNSETTLED, detail=f"more than {MAX_HISTORY_PAGES} history "
                                                f"pages inside {stable_hours:g} h")
        current = window[0] if window else base
        if current is None:
            return done(STATE_GONE, detail="no revision of the page at the time of the check")
        has = lambda r: contains(revisions.source(r["id"]), quote)  # noqa: E731
        if not has(current):
            own = out["revision_id"]
            if own and own != current["id"] and contains(revisions.source(own), quote):
                if own > current["id"]:
                    # A replay before the revision the hunter read: the words
                    # were written after the moment of the check.
                    out["age_h"] = 0.0
                    return done(STATE_FRESH, detail=f"written after the time of the check "
                                                    f"(revision {own})")
                return done(STATE_GONE, detail=f"taken out by revision {current['id']} "
                                               f"({iso(current['at'])})")
            return done(STATE_UNREADABLE, detail="the quote is not found in the page's "
                                                 "wikitext by this reader")
        if base is None or not has(base):
            # Written inside the window: the first revision of the window that
            # has it, by halving (oldest .. newest; the last one has it).
            chron = list(reversed(window))
            lo, hi = 0, len(chron) - 1
            while lo < hi and revisions.reads - reads0 < MAX_REVISION_READS:
                mid = (lo + hi) // 2
                if has(chron[mid]):
                    hi = mid
                else:
                    lo = mid + 1
            what = "the page was created" if base is None else "the quote was written"
            return done(STATE_FRESH, since=chron[hi],
                        detail=f"{what} inside the {stable_hours:g} h before the check")
        middle = window[1:]
        if len(middle) + 2 > MAX_REVISION_READS:
            return done(STATE_UNSETTLED, since=base, at_least=True,
                        detail=f"{len(window)} revisions inside {stable_hours:g} h - more "
                               f"than {MAX_REVISION_READS} to read")
        newer = current
        for r in middle:                       # newest first
            if not has(r):
                return done(STATE_REVERTED, since=newer,
                            detail=f"revision {r['id']} ({iso(r['at'])}) did not have it")
            newer = r
        return done(STATE_STABLE, since=base, at_least=True)
    except wp_error as exc:
        return done(STATE_UNREACHABLE, detail=str(exc)[:300])
