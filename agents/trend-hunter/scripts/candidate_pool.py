#!/usr/bin/env python3
"""CF-0772: the candidate pool from every news entry that names something.

Where it was found. ExampleTech's batch `2026-10-16T0702Z`: the feeds gave 236
entries, the operator read them and wrote a pool of 21 candidates
(`work/candidate-pool.json`) - the stories two outlets had both carried and a
handful of single ones. Twelve were scored, the refill (CF-0756,
`refill_topics.py`) took the other nine in one round and stopped `pool_empty`.
Some two hundred entries that named a product, a model or a company never
became candidates at all: what went into the pool was the model's choice of
the moment. The user, 16.10: «делай их сейчас».

**What this script decides, and the operator does not.** Which entries become
candidates and which entries are one candidate. Every entry of the RSS output
(`fetch_rss_news.py`) that names something - a product, a model, a company -
is a candidate; entries naming the same subject are one candidate. Nothing
here judges whether a story is good; the scoring does that, with the same
ruler as before (`score_candidates.popularity_score`).

**The name** (`names_in`). Off the headline: the runs of capitalised words,
words with a capital inside (`HomeView`, `ChatGPT`, `iPhone`) and words with
a digit and a letter (`GPT-5`, `WH-1000XM6`), a number carried on when it
follows one (`Gemini 4 Argon`, `OpenCode 2.0`). A possessive, a quote, a
colon, a comma or a dash ends a run. Capitals carry no information in a
Title Case headline (WIRED, Hacker News) or on a headline's first word, so
there a word counts only when the batch never writes it in lower case
(`common_words`: every word the batch's titles and summaries use in lower
case, plus a short list of function words) - "Launches", "Review", "Best" are
in that list; "Withings", "Volvo" are not. Words that name nothing on their
own (`GENERIC`: AI, US, CEO, the months...) may be part of a name but are
never one alone; the feed's own brand ("TechCrunch Disrupt 2026" on
TechCrunch) is no subject.

Each entry's subject (`subject_of`), in this order:
  * `product`  - the first name that is not a company: a name of several
                 words, or one word with a capital inside or a digit in it;
  * `names`    - else the first two names together (`Volvo Nvidia`);
  * `company`  - else the one name (`ExampleStream`, `Flock`).
A company is a name equal to a tier-1 host's label of the channel's
`fact-sources.json` (`apple.com` -> Apple, `openai.com` -> OpenAI) - the list
says who is a company; this file does not.

**One subject, one candidate** (`group_entries`). Entries are joined when
their subjects are the same (case and punctuation aside), or when one
product name is a run of words inside another (`HomeView` inside `Apple
HomeView`) - products only: two stories about Apple are two candidates. The
candidate's name is its entries' most frequent subject (the longer on a tie).

**Houses** (step 4's count). A house is the owner of the *feed* that carried
the entry (`sources.rss.feeds[].house`), not the domain of its link: Hacker
News links to the company's page and is still Hacker News. A company's own
feed (`kind: "vendor"` on the feed - OpenAI News, Google DeepMind and the
newsrooms CF-0770 added: Apple, The Keyword, Microsoft, NVIDIA, Meta, Amazon,
Samsung) is **not** a house of the news: it never adds to
`distinct_rss_houses` (the root's rule, `sources.rss.house_ceil_note`). A
candidate only a company's own feed carries counts **0** houses - it scores
on its views alone - and says so in `vendor_only`.
Its links stay in `rss_links` (and in `vendor_links`, every link on a tier-1
host), so `vendor_page.py` (CF-0757) finds the company's post as the topic's
own lead.

**Dropped, counted, never silently**: an entry with no name (`no_name`) and a
shop offer (`deal`: promo codes, coupons, "$50 off") - `dropped` in the file.
Whether a story is in the channel's `scope.content_type` and outside its
`scope.exclude` is not decided by words here: the operator marks a
candidate out of scope (`mark --out-of-scope`), with the reason, and the mark
stays in the file; the refill never takes it.

**The order** of `candidates[]` is the order the first scoring pass and the
refill take them in: houses, entries, `product` before `names` before
`company`, the newest entry, the name.

Usage:

    candidate_pool.py build <batch-dir> --rss <fetch_rss_news output> [--channel <id>] --write
    candidate_pool.py list  <batch-dir> [--all] [--limit N] [--json]
    candidate_pool.py mark  <batch-dir> [--score KEY=SCORE ...] [--topic KEY=TOPIC_ID ...]
                                        [--out-of-scope KEY=REASON ...]

KEY is a candidate's `pool_id` (`p001`) or its `name`. `build` without
`--write` prints the pool and writes nothing; over a pool that already carries
marks it refuses (exit 2) unless `--force`. The channel is the batch's
(`01-trend-hunter.json` `channel`) unless `--channel` names it; only the
channels of `CHANNELS` are built here - another channel's step 2 is the
operator's, as before (SKILL.md).

Stdlib only; reads the channel's config and fact-sources list from the factory
root (`FACTORY_ROOT`), nothing from the network.
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

TASK = "CF-0772"
POOL_REL = Path("work") / "candidate-pool.json"
BATCH_FILE = "01-trend-hunter.json"
#: the channels whose step 2 is this script (CF-0772: ExampleTech's sentence-
#: case tech headlines). ExampleFilm's Title Case trade headlines name works
#: in quotes, not by capitals - its pool stays the operator's until measured.
CHANNELS = ("example-tech",)

VENDOR_KIND = "vendor"            # sources.rss.feeds[].kind of a company's own newsroom (CF-0770)
KIND_PRODUCT = "product"
KIND_NAMES = "names"
KIND_COMPANY = "company"
KIND_RANK = {KIND_PRODUCT: 0, KIND_NAMES: 1, KIND_COMPANY: 2}

DROP_NO_NAME = "no_name"
DROP_DEAL = "deal"

FUNCTION_WORDS = frozenset("""
a an the and or but nor of to in on at by for from with without into onto over under up down out
off about after before as is are was were be been being am it its it's this that these those there
here how why what when where who whom whose which while if then than so not no yes can could will
would should may might must do does did done has have had having get gets got new now more most
less least best first last next just all any some every each one two three four five six seven
eight nine ten your you we our us their they them his her he she my i me let lets meet inside
behind beyond against amid among via vs per like
""".split())

#: names that name nothing on their own - they may be part of a name.
GENERIC = frozenset("""
ai a.i agi llm llms api apis gpu gpus cpu cpus npu app apps tech us u.s usa uk eu un ceo cto cfo
coo ipo hn show ask tv pc pcs vr ar xr os ui ux faq ev evs hr pr q1 q2 q3 q4 review reviews
report exclusive update updates live breaking podcast video watch day days week weeks year years
january february march april may june july august september october november december jan feb mar
apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday
inc corp co ltd llc
""".split())

#: a single unit-like token is no name (`4K`, `5G`, `3D`, `24B`, `10GB`).
_UNIT_RE = re.compile(r"^\d+(?:\.\d+)?[A-Za-z]{1,3}$")
_DEAL_RE = re.compile(
    r"promo codes?|coupons?\b|coupon codes?|discount codes?|\b\d{1,3}\s?% off\b|"
    r"[$€£]\s?\d[\d,.]*\s+off\b|\bdeals? of the day\b|\bprime day\b", re.I)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+&/'\-]*[A-Za-z0-9+]|[A-Za-z0-9]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_BOUNDARY = " | "


# ------------------------------------------------------------------ names
def norm(name):
    """A name's key: lower case, letters and digits only, one space."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split())


VOCABULARY = HERE.parent / "config" / "common_words.txt"
ROLE_WORDS = frozenset("ceo cto cfo coo founder cofounder co-founder chief boss head".split())


def _vocabulary():
    try:
        lines = VOCABULARY.read_text().splitlines()
    except OSError:
        return set()
    return {w.strip().lower() for w in lines if w.strip() and not w.startswith("#")}


def common_words(entries):
    """Every word the batch writes in lower case (titles and summaries), the
    shipped vocabulary (`config/common_words.txt`) and the function words: a
    capitalised word that is one of these says nothing in a Title Case
    headline or as a headline's first word."""
    out = set(FUNCTION_WORDS) | _vocabulary()
    for entry in entries:
        for field in ("title", "summary"):
            for word in _WORD_RE.findall(str(entry.get(field) or "")):
                if word[0].islower():
                    out.add(word.lower().strip("'-"))
    return out


def _segments(title):
    text = str(title or "")
    for mark in ("‘", "“", "”", '"', "«", "»", "|", "│", "/", "?", "!"):
        text = text.replace(mark, _BOUNDARY)
    text = re.sub(r"(\w)[’']s\b", r"\1" + _BOUNDARY, text)          # possessive
    text = re.sub(r"(?<=[A-Za-z])[’'](?=[A-Za-z])", "'", text)        # don't
    text = text.replace("’", _BOUNDARY).replace("'", "'")
    text = re.sub(r"(?:^|(?<=\s))'|'(?=\s|$)", _BOUNDARY, text)
    return [s for s in re.split(r"\s*(?:[:;,!?()\[\]{}]|\s[-–—]\s|—|–|\|)\s*", text) if s.strip()]


def is_title_case(title):
    """Capitals carry no information: a function word capitalised after the
    first word ("Has", "Of", "With"), or most words capitalised."""
    words = _WORD_RE.findall(str(title or ""))
    if any(w[0].isupper() and w.lower() in FUNCTION_WORDS and not w.isupper()
           for w in words[1:]):
        return True
    long_words = [w for w in words if len(w) >= 4]
    return len(long_words) >= 3 and \
        sum(1 for w in long_words if w[0].isupper()) / len(long_words) >= 0.6


def _is_common(word, common):
    low = word.lower()
    if low in common:
        return True
    for suffix, back in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"),
                         ("ing", ""), ("ing", "e"), ("ly", "")):
        if low.endswith(suffix) and len(low) - len(suffix) >= 3 \
                and low[:-len(suffix)] + back in common:
            return True
    return False


def _has_inner_capital(tok):
    return any(c.isupper() for c in tok[1:]) and not tok.isupper()


def _has_digit_and_letter(tok):
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def _proper(tok, first, title_case, common):
    if "'" in tok:                                   # Don't, Can't
        return False
    parts = tok.split("-")
    if len(parts) > 1 and parts[-1].isalpha() and parts[-1].islower() and len(parts[-1]) >= 3:
        return False                                 # AI-powered, SpaceX-powered, High-speed
    if _has_digit_and_letter(tok) or _has_inner_capital(tok):
        return True
    if not tok[0].isupper():
        return False
    if tok.isupper() and len(tok) >= 2:
        return True
    if first or title_case:
        low = tok.lower()
        if len(low) >= 5 and (low.endswith("ing") or low.endswith("ed")):
            return False                             # Comparing, Celebrating, Ranked
        return not _is_common(tok, common)
    return True


def _generic(tok):
    low = tok.lower()
    return low in GENERIC or bool(_UNIT_RE.match(tok)) or low in FUNCTION_WORDS \
        or bool(re.fullmatch(r"\d+(?:\.\d+)*", tok))


def names_in(title, common, brand=()):
    """The names a headline gives, in order, each once: runs of proper words
    (a number carried on after one). A run of generic words only, or the
    feed's own brand, is no name."""
    title_case = is_title_case(title)
    out, seen = [], set()
    first = True
    for seg in _segments(title):
        run = []

        def close():
            words = list(run)
            while words and words[0].lower() in FUNCTION_WORDS:
                words.pop(0)
            while len(words) > 1 and words[-1].lower() in ROLE_WORDS:
                words.pop()                          # Flock CEO -> Flock
            run.clear()
            if not words or all(_generic(w) for w in words):
                return
            if len(words) == 1 and _UNIT_RE.match(words[0]):
                return
            key = norm(" ".join(words))
            if not key or key in seen:
                return
            if brand and (key in brand or any(key.startswith(b + " ") for b in brand)):
                return
            seen.add(key)
            out.append(" ".join(words))

        for tok in _TOKEN_RE.findall(seg):
            if _proper(tok, first, title_case, common):
                run.append(tok)
            elif run and re.fullmatch(r"\d+(?:\.\d+)*", tok):
                run.append(tok)
            else:
                close()
            first = False
        close()
    return out


def companies_of(sources):
    """Tier-1 hosts' labels of the channel's list (`apple.com` -> `apple`,
    `deepmind.google` -> `deepmind`, `about.fb.com` -> `fb`): a name equal to
    one is a company, not a product."""
    out = set()
    for row in ((sources or {}).get("tiers") or {}).get("1") or []:
        for host in (row or {}).get("hosts") or []:
            labels = [p for p in str(host).lower().split(".") if p]
            if len(labels) >= 2:
                out.add(norm(labels[-2]))
                out.add(norm(labels[0]))
    out.discard("")
    for generic in ("www", "about", "blog", "news", "ai", "research", "aws", "dx", "doi"):
        out.discard(generic)
    return out


def _specific(name, companies):
    key = norm(name)
    if key in companies or key.replace(" ", "") in companies:
        return False
    words = name.split()
    if len(words) >= 2:
        return any(not _generic(w) for w in words)
    tok = words[0]
    return (_has_inner_capital(tok) or _has_digit_and_letter(tok)) and not _UNIT_RE.match(tok)


def subject_of(names, companies):
    """(subject, kind) of an entry's names - see the module docstring."""
    usable = [n for n in names if not all(_generic(w) for w in n.split())]
    for name in usable:
        if _specific(name, companies):
            return name, KIND_PRODUCT
    if len(usable) >= 2:
        return f"{usable[0]} {usable[1]}", KIND_NAMES
    if usable:
        return usable[0], KIND_COMPANY
    return None, None


# ------------------------------------------------------------------ feeds
def _host(url):
    m = re.match(r"^[a-z][a-z0-9+.\-]*://([^/?#]+)", str(url or "").strip(), re.I)
    host = (m.group(1) if m else str(url or "")).lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _tier(url, sources):
    import fact_rule
    if not url or not sources:
        return None
    where = fact_rule.source_of(url if "://" in str(url) else f"https://{url}/", sources)
    return None if where.get("banned") else where.get("tier")


def feed_table(config, sources):
    """feed url -> {"house", "vendor", "site"} from the channel config's
    `sources.rss.feeds[]`. `vendor`: the feed is a company's own newsroom
    (`kind: "vendor"`, the root's CF-0770 marker)."""
    out = {}
    for feed in (((config or {}).get("sources") or {}).get("rss") or {}).get("feeds") or []:
        if not isinstance(feed, dict) or not feed.get("url"):
            continue
        vendor = str(feed.get("kind") or "").lower() == VENDOR_KIND
        out[feed["url"]] = {"house": feed.get("house"), "vendor": bool(vendor),
                            "site": feed.get("site")}
    return out


_BRAND_DROP = frozenset("news blog the review technology feed rss".split())


def brand_of(feed_name, vendor):
    """The feed's own brand as name keys - dropped as a subject on a news
    feed (`TechCrunch Disrupt 2026` on TechCrunch). A company's own feed keeps
    its name: there the company *is* the subject."""
    if vendor:
        return ()
    words = [w for w in norm(feed_name).split() if w not in _BRAND_DROP]
    return tuple({" ".join(words)} | ({words[0]} if words else set())) if words else ()


# ------------------------------------------------------------------ build
def _published(entry):
    return str(entry.get("published_at") or "")


def classify(entries, config, sources):
    """-> (rows, dropped): one row per entry that names something."""
    common = common_words(entries)
    companies = companies_of(sources)
    feeds = feed_table(config, sources)
    rows, dropped = [], Counter()
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        if not title or not entry.get("link"):
            dropped[DROP_NO_NAME] += 1
            continue
        if _DEAL_RE.search(title):
            dropped[DROP_DEAL] += 1
            continue
        feed = feeds.get(entry.get("feed_url")) or {}
        names = names_in(title, common, brand_of(entry.get("feed"), feed.get("vendor")))
        subject, kind = subject_of(names, companies)
        if not subject:
            dropped[DROP_NO_NAME] += 1
            continue
        rows.append({"entry": entry, "names": names, "subject": subject, "kind": kind,
                     "is_company": norm(subject) in companies
                     or norm(subject).replace(" ", "") in companies,
                     "house": feed.get("house"), "vendor": bool(feed.get("vendor")),
                     "tier1_link": _tier(entry.get("link"), sources) == 1})
    return rows, dropped


def _contains(outer, inner):
    o, i = norm(outer).split(), norm(inner).split()
    if not i or len(i) > len(o):
        return False
    return any(o[k:k + len(i)] == i for k in range(len(o) - len(i) + 1))


def group_entries(rows):
    """Union of rows naming the same subject: equal keys, or one product name
    a run of words inside another."""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_key = {}
    for i, row in enumerate(rows):
        key = norm(row["subject"])
        if key in by_key:
            union(i, by_key[key])
        else:
            by_key[key] = i
    products = [(norm(r["subject"]), i) for i, r in enumerate(rows) if r["kind"] == KIND_PRODUCT]
    singles = [(norm(r["subject"]), i) for i, r in enumerate(rows)
               if r["kind"] == KIND_COMPANY and not r.get("is_company")]
    for ka, a in products:
        for kb, b in products + singles:
            if a != b and ka != kb and _contains(ka, kb):
                union(a, b)
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(rows[i])
    return list(groups.values())


def _candidate(group):
    counts = Counter(r["subject"] for r in group)
    kinds = {}
    for r in group:
        if r["subject"] not in kinds or KIND_RANK[r["kind"]] < KIND_RANK[kinds[r["subject"]]]:
            kinds[r["subject"]] = r["kind"]
    name = sorted(counts, key=lambda s: (-counts[s], KIND_RANK[kinds[s]], -len(s), s))[0]
    group = sorted(group, key=lambda r: _published(r["entry"]), reverse=True)
    links, vendor_links, headlines, names = [], [], [], []
    news_houses, vendor_houses = set(), set()
    for row in group:
        e = row["entry"]
        if e["link"] not in links:
            links.append(e["link"])
            headlines.append({"title": e.get("title"), "feed": e.get("feed"),
                              "link": e["link"], "published_at": e.get("published_at")})
        if row["tier1_link"] and e["link"] not in vendor_links:
            vendor_links.append(e["link"])
        (vendor_houses if row["vendor"] else news_houses).add(row["house"] or e.get("feed"))
        for n in row["names"]:
            if norm(n) != norm(name) and n not in names:
                names.append(n)
    houses = sorted(h for h in news_houses if h)
    return {
        "name": name,
        "name_kind": kinds[name],
        "popularity_score": None,
        "distinct_rss_houses": len(houses),
        "distinct_rss_entries": len(links),
        "houses": houses,
        "vendor_only": not houses and bool(vendor_houses),
        "vendor_feeds": sorted(h for h in vendor_houses if h),
        "rss_links": links,
        "vendor_links": vendor_links,
        "headline": headlines[0]["title"] if headlines else None,
        "headlines": headlines[:6],
        "other_names": names[:8],
        "newest_at": _published(group[0]["entry"]) or None,
        "topic_id": None,
    }


def order_key(cand):
    newest = cand.get("newest_at") or ""
    return (-int(cand.get("distinct_rss_houses") or 0), -int(cand.get("distinct_rss_entries") or 0),
            KIND_RANK.get(cand.get("name_kind"), 3), _neg_text(newest), norm(cand["name"]))


def _neg_text(text):
    return tuple(-ord(c) for c in text)


def build_pool(rss, config, sources):
    """The pool document from the RSS output `rss` ({"entries": [...]})."""
    entries = list((rss or {}).get("entries") or [])
    rows, dropped = classify(entries, config, sources)
    cands = sorted((_candidate(g) for g in group_entries(rows)), key=order_key)
    seen = Counter()
    for i, cand in enumerate(cands, 1):
        cand["pool_id"] = f"p{i:03d}"
        seen[norm(cand["name"])] += 1
    for cand in cands:  # two groups that ended with one name: tell them apart
        if seen[norm(cand["name"])] > 1:
            cand["name"] = f"{cand['name']} ({cand['pool_id']})"
    kinds = Counter(c["name_kind"] for c in cands)
    return {
        "task": TASK,
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rss": {"generated_at": (rss or {}).get("generated_at"), "entries": len(entries)},
        "entries_named": len(rows),
        "dropped": dict(sorted(dropped.items())),
        "counts": {"candidates": len(cands), "by_kind": dict(sorted(kinds.items())),
                   "two_or_more_houses": sum(1 for c in cands if c["distinct_rss_houses"] >= 2),
                   "vendor_only": sum(1 for c in cands if c["vendor_only"]),
                   "with_vendor_link": sum(1 for c in cands if c["vendor_links"])},
        "candidates": cands,
    }


# ------------------------------------------------------------------ marks
MARK_FIELDS = ("popularity_score", "topic_id", "out_of_scope")


def is_marked(cand):
    return cand.get("popularity_score") is not None or bool(cand.get("topic_id")) \
        or bool(cand.get("out_of_scope"))


def find_candidate(pool, key):
    key = str(key).strip()
    for cand in pool["candidates"]:
        if cand.get("pool_id") == key:
            return cand
    hits = [c for c in pool["candidates"] if norm(c.get("name")) == norm(key)]
    if len(hits) == 1:
        return hits[0]
    raise PoolError(f"no candidate {key!r} in the pool" if not hits
                    else f"{key!r} names {len(hits)} candidates - use the pool_id")


def _pairs(values, what):
    out = []
    for raw in values or ():
        if "=" not in raw:
            raise PoolError(f"--{what} wants KEY=VALUE, got {raw!r}")
        key, value = raw.split("=", 1)
        out.append((key.strip(), value.strip()))
    return out


def apply_marks(pool, scores=(), topics=(), out_of_scope=()):
    changed = []
    for key, value in _pairs(scores, "score"):
        try:
            score = float(value)
        except ValueError:
            raise PoolError(f"--score {key}={value!r}: not a number")
        cand = find_candidate(pool, key)
        cand["popularity_score"] = score
        changed.append(cand["pool_id"])
    for key, value in _pairs(topics, "topic"):
        cand = find_candidate(pool, key)
        cand["topic_id"] = value or None
        changed.append(cand["pool_id"])
    for key, value in _pairs(out_of_scope, "out-of-scope"):
        if not value:
            raise PoolError(f"--out-of-scope {key}: the reason is required")
        cand = find_candidate(pool, key)
        cand["out_of_scope"] = value
        changed.append(cand["pool_id"])
    pool.setdefault("counts", {})["out_of_scope"] = sum(
        1 for c in pool["candidates"] if c.get("out_of_scope"))
    return sorted(set(changed))


# ------------------------------------------------------------------ cli
class PoolError(RuntimeError):
    pass


def pool_path(batch_dir):
    return Path(batch_dir).expanduser() / POOL_REL


def load(path):
    path = Path(path)
    if not path.is_file():
        raise PoolError(f"no candidate pool at {path} - `candidate_pool.py build` writes it")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise PoolError(f"{path}: no `candidates` list")
    return data


def save(path, pool):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pool, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def batch_channel(batch_dir):
    f = Path(batch_dir).expanduser() / BATCH_FILE
    if f.is_file():
        from _channel_ids import resolve_channel   # a batch from before a rename
        try:
            data = json.loads(f.read_text()) or {}
        except ValueError:
            return None
        return (resolve_channel(data.get("channel")) if str(data.get("channel") or "").strip()
                else None)
    return None


def channel_inputs(channel, root=None):
    """(id, config, fact-sources list) of the channel, from the factory root
    (`root`, else `FACTORY_ROOT` / the nearest root)."""
    from _channel_data import channel_data, factory_root
    from _channel_ids import resolve_channel
    cid = resolve_channel(channel)
    base = Path(root) if root else factory_root()
    path = base / "channels" / f"{cid}.json"
    if not path.is_file():
        raise PoolError(f"no channel config at {path}")
    return cid, json.loads(path.read_text()), channel_data.fact_sources(cid, root=base)


def line(cand):
    mark = ""
    if cand.get("out_of_scope"):
        mark = f"  [out of scope: {cand['out_of_scope']}]"
    elif cand.get("popularity_score") is not None:
        mark = f"  [score {cand['popularity_score']}]"
    vend = " vendor" if cand.get("vendor_links") else ""
    return (f"{cand['pool_id']}  h{cand['distinct_rss_houses']} e{cand['distinct_rss_entries']}"
            f"  {cand['name_kind']:7}{vend}  {cand['name']} - {cand.get('headline') or ''}{mark}")


def main(argv=None, root=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("batch_dir")
    b.add_argument("--rss", required=True, help="fetch_rss_news.py output (JSON)")
    b.add_argument("--channel", help="the batch's channel (default: 01-trend-hunter.json's)")
    b.add_argument("--write", action="store_true")
    b.add_argument("--force", action="store_true", help="rebuild over a pool with marks")
    l_ = sub.add_parser("list")
    l_.add_argument("batch_dir")
    l_.add_argument("--all", action="store_true", help="the marked ones too")
    l_.add_argument("--limit", type=int)
    l_.add_argument("--json", action="store_true")
    m = sub.add_parser("mark")
    m.add_argument("batch_dir")
    m.add_argument("--score", action="append", default=[], metavar="KEY=SCORE")
    m.add_argument("--topic", action="append", default=[], metavar="KEY=TOPIC_ID")
    m.add_argument("--out-of-scope", action="append", default=[], metavar="KEY=REASON")
    args = ap.parse_args(argv)
    path = pool_path(args.batch_dir)
    try:
        if args.cmd == "build":
            channel = args.channel or batch_channel(args.batch_dir)
            if not channel:
                raise PoolError("no channel: the batch file names none and --channel was not given")
            cid, config, sources = channel_inputs(channel, root)
            if cid not in CHANNELS:
                print(f"candidate_pool: {cid}: step 2 of this channel is the operator's "
                      f"(CF-0772 builds the pool for {', '.join(CHANNELS)} only)", file=sys.stderr)
                return 2
            rss = json.loads(Path(args.rss).expanduser().read_text())
            pool = build_pool(rss, config, sources)
            pool["channel"] = cid
            pool["rss"]["path"] = str(Path(args.rss).expanduser())
            if args.write:
                if path.is_file() and not args.force:
                    old = load(path)
                    if any(is_marked(c) for c in old["candidates"]):
                        raise PoolError(f"{path} already carries marks (scores, topics, scope) - "
                                        f"not rebuilt; --force throws them away")
                save(path, pool)
            summary = {k: pool[k] for k in ("task", "channel", "rss", "entries_named",
                                            "dropped", "counts")}
            summary["path"] = str(path) if args.write else None
            summary["first"] = [line(c) for c in pool["candidates"][:25]]
            print(json.dumps(summary, indent=1, ensure_ascii=False))
            return 0
        pool = load(path)
        if args.cmd == "list":
            rows = [c for c in pool["candidates"] if args.all or not is_marked(c)]
            rows = rows[:args.limit] if args.limit else rows
            if args.json:
                print(json.dumps(rows, indent=1, ensure_ascii=False))
            else:
                print("\n".join(line(c) for c in rows))
            return 0
        changed = apply_marks(pool, args.score, args.topic, args.out_of_scope)
        save(path, pool)
        print(json.dumps({"marked": changed, "out_of_scope": pool["counts"]["out_of_scope"],
                          "path": str(path)}))
        return 0
    except PoolError as exc:
        print(f"candidate_pool: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
