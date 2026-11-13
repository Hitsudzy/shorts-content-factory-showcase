#!/usr/bin/env python3
"""CF-0557: what an outlet's robots.txt says to AI bots, and the record of it.

The factory's rule (grill CF-0546 Q9 of 05.10, grill 07.10 Q8; narrowed by
the user's decision of 08.10, CF-0635): an outlet is closed - verdict
`forbidden` - only when its robots.txt disallows the checked path to one of
Anthropic's own bots (`anthropic-ai`, `ClaudeBot`, `Claude-Web`, `Claude-User`,
`Claude-SearchBot`) or to every agent (`*`). A ban on another company's AI bot
(GPTBot, CCBot, Google-Extended, ...) is recorded in the report but does not
close the site: "if the site did not write a ban on the Anthropic bot, there is
none". A closed outlet's own RSS feed may still be read for topic selection -
headline and link, no excerpt to the writer (`headline_only`) - as long as the
feed is open to every agent, and it may be *named* as the outlet a fact stands
on (`cite_only`); only an outlet whose verdict is `allowed` may have its text
read (`read_text`). robots.txt is not the whole answer: terms of use that
forbid AI use still close an outlet (a person records them in `terms_note`).
The rule that ties `use` and the verdict is `shared/channel_data.py`
(`source_policy_errors`); this module produces the verdict.

    ANTHROPIC_AGENTS          the bots whose ban closes a site (with `*`)
    AI_AGENTS                 every AI bot the report lists as blocked or not -
                              Anthropic's first, then the others (information)
    parse_robots(text)        robots.txt -> groups (RFC 9309)
    allowed(groups, agent, path)
                              may `agent` fetch `path` (longest match, Allow
                              wins a tie, `*` and `$` patterns)
    read_robots(text, path)   one robots.txt for one path -> `{any_agent,
                              anthropic_blocked, ai_agents_blocked}`
    verdict_of(read)          that read -> `allowed` | `forbidden`
    policy(checks, today)     the `ai_policy` block of an entry
    check_channel(channel, fetch, today, root)
                              every outlet and feed of the channel, checked

CLI (it goes to the network - robots.txt only, one request per host; never
run by the test suite, whose cases hand in a stand-in `fetch`):

    python3 shared/source_policy.py check <channel> [--write]

prints a table of verdicts; `--write` puts `ai_policy` into
`channels/<id>/fact-sources.json` (tiers) and `channels/<id>.json`
(`sources.rss.feeds`), keeping what a person wrote there (`terms_url`,
`terms_note`, `terms_read`, `terms_verdict`, `check_paths`). A row whose
terms were not read (`ai_policy.terms_read` false, CF-0810) is never written `allowed`: its
robots.txt read open, it stays `unknown` and `ai_policy.held` says why; a row
whose terms ban AI use, robots or scraping (`ai_policy.terms_verdict`
forbidden, CF-0816) stays `forbidden`.

Which path is checked: a feed - the feed's path on the publisher's host
(`site`; for a feed served elsewhere, FeedBurner, the publisher's site root,
the CF-0060 position); an outlet of the tiers - `/` on every host it lists, or
the entry's `ai_policy.check_hosts` / `check_paths` when a person named them
(Wikipedia: `api.wikimedia.org` has no robots.txt - it answers an HTML page -
so the outlet is checked on `en.wikipedia.org`, whose file covers the
Wikimedia sites). A host that
answers robots.txt with 404/410 has none (everything allowed, RFC 9309); 401,
403, 5xx, an HTML page instead of robots.txt or no answer at all is `unknown`
- not permission.

Stdlib only; loads `channel_data.py` by path from beside this file.
"""
import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The bots whose ban closes a site (the factory runs on Claude): the user's
#: decision of 08.10 (CF-0635) - a robots.txt that disallows the checked path
#: to one of these, or to every agent (`*`), makes the verdict `forbidden`.
ANTHROPIC_AGENTS = ("anthropic-ai", "ClaudeBot", "Claude-Web", "Claude-User",
                    "Claude-SearchBot")
#: The other training / retrieval crawlers a publisher names when it opts out
#: of AI use. Their ban is recorded (`ai_agents_blocked`) and does not change
#: the verdict (until CF-0635 it did - CF-0557 closed a site on any of them).
OTHER_AI_AGENTS = (
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "CCBot", "Google-Extended",
    "PerplexityBot", "Perplexity-User", "Bytespider", "Applebot-Extended",
    "meta-externalagent", "cohere-ai", "Diffbot",
)
#: every AI bot the report lists. Change the lists here only - the verdict
#: records which rule and set it was taken against (`AI_AGENTS_VERSION`).
AI_AGENTS = ANTHROPIC_AGENTS + OTHER_AI_AGENTS
AI_AGENTS_VERSION = "CF-0635 2026-10-08 (Anthropic agents or *)"
USER_AGENT = ("shorts-content-factory-source-policy/1.0 "
              "(robots.txt check; https://example.com/shorts-content-factory)")
TIMEOUT = 20
NO_ROBOTS_STATUSES = (404, 410)

#: what a person writes into `ai_policy` and a re-check keeps: which hosts
#: and paths stand for the outlet when its listed ones do not (an API host
#: with no robots.txt of its own), and the terms.
KEPT_KEYS = ("check_hosts", "check_paths", "terms_url", "terms_note", "terms_read",
             "terms_verdict")
#: CF-0810: a row whose terms were not read (`terms_read` false - named only)
#: is never turned `allowed` by a re-check: robots.txt open, it stays
#: `unknown` and the block says why here
HELD_KEY = "held"
_VERDICT_ORDER = {"allowed": 0, "unknown": 1, "forbidden": 2}


def _channel_data():
    spec = importlib.util.spec_from_file_location("_channel_data_for_source_policy",
                                                  HERE / "channel_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------ robots.txt
def _token(value):
    """The product token of a User-agent line: `ClaudeBot/1.0` -> `claudebot`."""
    return re.split(r"[/\s]", value.strip(), maxsplit=1)[0].lower()


def parse_robots(text):
    """robots.txt -> [{"agents": [token, ...], "rules": [(allow, pattern)]}].
    RFC 9309: consecutive User-agent lines open one group; Allow/Disallow
    lines belong to the group above; an empty Disallow allows everything and
    is no rule; other lines (Sitemap, Crawl-delay) neither open nor close a
    group's agents."""
    groups, cur, in_agents = [], None, False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key in ("user-agent", "useragent"):
            if cur is None or not in_agents:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(_token(value))
            in_agents = True
        elif key in ("allow", "disallow"):
            in_agents = False
            if cur is None or (key == "disallow" and not value):
                continue
            cur["rules"].append((key == "allow", value))
    return groups


def _pattern(pattern):
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(rx + ("$" if anchored else ""))


def _rules_for(groups, agent):
    token = _token(agent)
    named = [g for g in groups if token in g["agents"]]
    chosen = named or [g for g in groups if "*" in g["agents"]]
    return [r for g in chosen for r in g["rules"]]


def allowed(groups, agent, path):
    """May `agent` fetch `path`? The group(s) naming the agent's product token
    (case-insensitive), else the `*` group(s), else everything; the longest
    matching pattern wins, Allow wins a tie; /robots.txt is always allowed."""
    path = path or "/"
    if path == "/robots.txt":
        return True
    best = None  # (length, allow)
    for allow, pattern in _rules_for(groups, agent):
        if _pattern(pattern).match(path):
            key = (len(pattern), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def read_robots(text, path):
    """One robots.txt for one path: is it open to every agent (`*`), which of
    Anthropic's agents it is closed to (they decide), and which of all
    AI_AGENTS (the report)."""
    groups = parse_robots(text)
    blocked = [a for a in AI_AGENTS if not allowed(groups, a, path)]
    return {"any_agent": allowed(groups, "*", path),
            "anthropic_blocked": [a for a in blocked if a in ANTHROPIC_AGENTS],
            "ai_agents_blocked": blocked}


def verdict_of(read):
    """A `read_robots` answer -> `forbidden` when the path is closed to every
    agent or to one of Anthropic's, else `allowed`; the other AI bots do not
    count (CF-0635)."""
    return "forbidden" if read["any_agent"] is False or read["anthropic_blocked"] else "allowed"


# ------------------------------------------------------------ the network
def fetch_robots(robots_url, timeout=TIMEOUT):
    """-> (status, content_type, text). Network: the CLI only."""
    req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return (resp.status, resp.headers.get("Content-Type", ""),
                    resp.read(500_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def check_url(robots_url, path, fetch):
    """One robots.txt read for one path -> a `checks[]` row with its verdict."""
    status, ctype, text = fetch(robots_url)
    row = {"robots_url": robots_url, "path": path, "status": status}
    looks_html = "html" in (ctype or "").lower() or (text or "").lstrip()[:1] == "<"
    if status in NO_ROBOTS_STATUSES:
        row.update(any_agent=True, anthropic_blocked=[], ai_agents_blocked=[],
                   verdict="allowed",
                   note="no robots.txt: everything allowed (RFC 9309)")
    elif status != 200 or looks_html:
        why = (f"answered {status}" if status not in (None, 200)
               else "an HTML page instead of robots.txt" if status == 200
               else f"no answer ({text})" if text else "no answer")
        row.update(any_agent=None, anthropic_blocked=None, ai_agents_blocked=None,
                   verdict="unknown", note=why)
    else:
        row.update(read_robots(text, path))
        row["verdict"] = verdict_of(row)
    return row


def policy(checks, today, keep=None):
    """The `ai_policy` block: the worst verdict of the reads, the day, the
    agent set, and what a person wrote (`terms_url`, `terms_note`,
    `terms_read`, `terms_verdict`, `check_paths`) carried over from `keep`.
    CF-0810: robots.txt alone never makes a row whose terms were not read
    (`terms_read` false) readable - an `allowed` read stays `unknown`, and
    `held` says why. CF-0816: a row whose terms ban AI use, robots or
    scraping (`terms_verdict` forbidden) stays `forbidden` whatever robots.txt
    says, and `held` says why."""
    keep = keep if isinstance(keep, dict) else {}
    verdict = max((c["verdict"] for c in checks), key=_VERDICT_ORDER.__getitem__)
    held = None
    if keep.get("terms_verdict") == "forbidden" and verdict != "forbidden":
        verdict = "forbidden"
        held = ("robots.txt reads open, but the terms ban AI use, robots or scraping "
                "(`terms_verdict` forbidden, the clause in `terms_note`): the verdict "
                "stays forbidden - the row is named only (the rule of 08.10, CF-0816)")
    elif verdict == "allowed" and keep.get("terms_read") is False:
        verdict = "unknown"
        held = ("robots.txt reads allowed, but the terms were not read (`terms_read` "
                "false): the verdict stays unknown - the row is named only - until a "
                "person reads the terms (`terms_url`, `terms_note`) and writes "
                "terms_read true (CF-0810)")
    out = {"verdict": verdict, "checked_on": today, "agents": AI_AGENTS_VERSION,
           "checks": checks}
    for key in KEPT_KEYS:
        if key in keep:
            out[key] = keep[key]
    out.setdefault("terms_url", None)
    if held:
        out[HELD_KEY] = held
    return out


# ------------------------------------------------------------ the channel
def _host_url(host):
    return f"https://{host}/robots.txt"


def entry_targets(entry, is_feed):
    """[(robots_url, path)] an entry is checked on."""
    keep = (entry.get("ai_policy") or {}) if isinstance(entry, dict) else {}
    paths = keep.get("check_paths") or None
    if is_feed:
        feed = urllib.parse.urlsplit(entry["url"])
        site = (entry.get("site") or feed.hostname or "").lower()
        feed_host = (feed.hostname or "").lower()
        same = feed_host == site or feed_host.endswith("." + site)
        host = feed_host if same else site
        path = (feed.path or "/") if same else "/"
        return [(_host_url(host), p) for p in (paths or [path])]
    hosts = keep.get("check_hosts") or entry.get("hosts") or []
    return [(_host_url(h), p) for h in hosts for p in (paths or ["/"])]


def check_channel(channel, fetch=fetch_robots, today=None, root=None):
    """Check every outlet of the channel's tiers and every feed. -> (report
    rows, fact-sources document updated, channel config updated). Each
    robots.txt is fetched once per run."""
    cd = _channel_data()
    root = Path(root) if root else cd.find_root()
    current = cd.channel_id(channel, root)
    today = today or dt.date.today().isoformat()
    cache = {}

    def cached(url):
        if url not in cache:
            cache[url] = fetch(url)
        return cache[url]

    rows = []
    sources = None
    if current in cd.channels_with("fact-sources", root):
        sources = cd.fact_sources(current, root)
        for tier, entries in sorted((sources.get("tiers") or {}).items()):
            for entry in entries:
                checks = [check_url(u, p, cached) for u, p in entry_targets(entry, False)]
                entry["ai_policy"] = policy(checks, today, entry.get("ai_policy"))
                rows.append({"what": f"tiers.{tier}", "id": entry.get("id"),
                             "use": entry.get("use"), **_summary(entry["ai_policy"])})
    config_path = root / cd.CHANNELS_SUBDIR / f"{current}.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    node = config
    for key in cd.FEEDS_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    for feed in node or []:
        checks = [check_url(u, p, cached) for u, p in entry_targets(feed, True)]
        feed["ai_policy"] = policy(checks, today, feed.get("ai_policy"))
        rows.append({"what": "feed", "id": feed.get("site"), "use": feed.get("use"),
                     **_summary(feed["ai_policy"])})
    return rows, sources, config


def _summary(pol):
    blocked = sorted({a for c in pol["checks"] for a in (c.get("ai_agents_blocked") or [])})
    star = [c.get("any_agent") for c in pol["checks"]]
    return {"verdict": pol["verdict"], "any_agent": None if None in star else all(star),
            "blocked": len(blocked),
            "anthropic_blocked": [a for a in blocked if a in ANTHROPIC_AGENTS],
            "held": bool(pol.get(HELD_KEY))}


# ------------------------------------------------------------ writing
def dumps(obj, indent=2, ensure_ascii=True, width=100, level=0, list_width=0):
    """json.dumps(indent=2) except that a short object of plain values stays
    on one line - the way the channel files keep their small rows
    (`procedural_palettes`), so a rewrite changes only what changed."""
    def enc(o, level):
        pad, inner = " " * (indent * level), " " * (indent * (level + 1))
        if isinstance(o, dict) and o:
            one = json.dumps(o, ensure_ascii=ensure_ascii)
            if level and len(one) + len(inner) <= width and \
                    not any(isinstance(v, (dict, list)) for v in o.values()):
                return one
            items = [f"{inner}{json.dumps(k, ensure_ascii=ensure_ascii)}: {enc(v, level + 1)}"
                     for k, v in o.items()]
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        if isinstance(o, list) and o:
            one = json.dumps(o, ensure_ascii=ensure_ascii)
            if level and len(one) + len(inner) <= list_width and \
                    not any(isinstance(v, (dict, list)) for v in o):
                return one
            return "[\n" + ",\n".join(inner + enc(v, level + 1) for v in o) + "\n" + pad + "]"
        return json.dumps(o, ensure_ascii=ensure_ascii)
    return enc(obj, level) + "\n"


#: a list of plain values (hosts, the blocked agents) written by
#: `replace_value` stays on one line up to this width
LIST_WIDTH = 400
_DECODER = json.JSONDecoder()
_WS = re.compile(r"\s*")


def value_span(text, keypath):
    """(start, end) of the value at `keypath` (object keys) in a JSON text,
    found by walking the text itself - so the rest of the file is not
    re-serialised (the channel files mix escaped and raw non-ASCII)."""
    pos = _WS.match(text, 0).end()
    for depth, want in enumerate(keypath):
        if text[pos] != "{":
            raise ValueError(f"{'.'.join(keypath[:depth]) or 'the document'} is not an object")
        pos = _WS.match(text, pos + 1).end()
        while True:
            if text[pos] == "}":
                raise KeyError(".".join(keypath[:depth + 1]))
            key, pos = _DECODER.raw_decode(text, pos)
            pos = _WS.match(text, pos).end() + 1          # past ':'
            pos = _WS.match(text, pos).end()
            if key == want:
                break
            _, pos = _DECODER.raw_decode(text, pos)
            pos = _WS.match(text, pos).end()
            if text[pos] == ",":
                pos = _WS.match(text, pos + 1).end()
    _, end = _DECODER.raw_decode(text, pos)
    return pos, end


def replace_value(path, keypath, value):
    """Put `value` at `keypath` of the JSON file at `path`, touching only that
    value's text; it is written in the file's style (`dumps`, indented to its
    depth, ASCII-escaped when the old value was)."""
    text = Path(path).read_text(encoding="utf-8")
    start, end = value_span(text, keypath)
    ascii_only = all(ord(ch) < 128 for ch in text[start:end])
    body = dumps(value, ensure_ascii=ascii_only, level=len(keypath),
                 list_width=LIST_WIDTH).rstrip("\n")
    new = text[:start] + body + text[end:]
    json.loads(new)
    Path(path).write_text(new, encoding="utf-8")


def main(argv=None, fetch=fetch_robots, today=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="read robots.txt of every outlet and feed (network)")
    c.add_argument("channel")
    c.add_argument("--write", action="store_true",
                   help="write ai_policy into the channel's files")
    c.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    cd = _channel_data()
    root = Path(args.root) if args.root else cd.find_root()
    rows, sources, config = check_channel(args.channel, fetch=fetch, today=today, root=root)
    for r in rows:
        print(f"{r['what']:<9} {str(r['id']):<22} use={str(r['use']):<20} "
              f"verdict={r['verdict']:<9} *={r['any_agent']!s:<5} "
              f"ai_blocked={r['blocked']:<2} anthropic={','.join(r['anthropic_blocked']) or '-'}"
              + (("  held: the terms forbid it (terms_verdict) - stays forbidden"
                  if r["verdict"] == "forbidden" else
                  "  held: terms not read (terms_read false) - stays unknown")
                 if r.get("held") else ""))
    if args.write:
        current = cd.channel_id(args.channel, root)
        if sources is not None:
            replace_value(cd.channel_list_path(current, "fact-sources", root), ("tiers",),
                          sources["tiers"])
        node = config
        for key in cd.FEEDS_PATH:
            node = node.get(key) if isinstance(node, dict) else None
        if node:
            replace_value(root / cd.CHANNELS_SUBDIR / f"{current}.json", cd.FEEDS_PATH, node)
        errs = cd.source_policy_errors(current, root)
        for e in errs:
            print(f"RULE: {e}", file=sys.stderr)
        return 1 if errs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
