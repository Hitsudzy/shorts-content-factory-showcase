#!/usr/bin/env python3
"""CF-0593: the affiliate-link slot of a channel's description.

Grill 2026-10-06 (CF-0560, Q13): money beyond the Shorts ads comes from
affiliate programmes (Amazon Associates, a SaaS referral). The **user**
registers the programmes and writes the links; the machine puts a link into a
video's description only when the video is about that very product, and only
on a channel the user has switched on (when the channel has views). Nothing
here invents a link, a tag or a product: a table the user did not fill places
nothing.

Two pieces of data, both the channel's (docs/channel-data.md «Affiliate
links»):

* the switch and the words - `channels/<id>.json` -> `affiliate` (a
  top-level block, not under `publisher`: a channel without a pipeline may
  not carry `publisher` - `shared/channel_ids.NO_PIPELINE_FORBIDDEN` - and
  ExampleTech gets its slot, switched off, before it gets its pipeline)::

      "affiliate": {
        "enabled": false,
        "link_line": "Link to {product} (affiliate): {url}",
        "disclosure": {
          "amazon_associates": "As an Amazon Associate I earn from qualifying purchases.",
          "default": "This is an affiliate link: the channel may earn a commission from it."
        },
        "note": "..."
      }

  Absent = off. `link_line` carries `{product}` and `{url}` and nothing else
  to fill, and says `affiliate` in its own words; `disclosure` is one line
  per network (`default` for every other one) - the FTC-style line that goes
  right under the link. Every word of both is checked claim-free here
  (`claim_words`): no "best price", "cheapest", "deal", "save", ...

* the programmes and the links - `channels/<id>/affiliate.json` (list
  `affiliate` of `shared/channel_data.LISTS`)::

      {"channel_id": "<id>", "note": "...",
       "programmes": [{"id", "name", "network", "tag" | "ref",
                       "added_by": "user", "added_at": "YYYY-MM-DD"}],
       "products":   [{"id", "names": [..], "aliases": [..], "url",
                       "programme", "added_by": "user", "added_at": "YYYY-MM-DD"}]}

  `names[0]` is how the link line names the product; `names` and `aliases`
  are what a topic must *be* to get the link. `url` is the user's affiliate
  link and carries the programme's `tag` / `ref`. Shipped empty.

**The match** (`decide`). A link goes into a video's description only when:

1. the channel's `affiliate.enabled` is true and its table reads;
2. the topic's subject *is* the product - one of the topic's own names
   (`title_ref.tool`, `model`, `name`, `aliases` - the Trend Hunter's forms
   of what the topic is about, `fetch_own_capture.queries_of`) equals one of
   the product's `names` / `aliases` as a whole name. Equal means the same
   letters and digits in the same order, case, accents, spaces and
   punctuation aside ("GPT-6" = "gpt 6" = "GPT6"). A name *containing* the
   other is not equal: "iPhone 17" is not "iPhone 16 case", and not
   "iPhone 17 case" either - a case is another product. A word in common is
   recorded as a near miss, never placed;
3. the script's fact names the product - its record (`production_fact.text`,
   else `fact.text`) carries one of the product's names as a run of whole
   words: the video says what it is about, not only its topic's label;
4. the filled link line and its disclosure carry no claim word;
5. one link per video at most - the table may not give two products one
   name (`table_errors`), so a subject matches at most one product.

The decision - placed or not, and why - is returned as a record the card
keeps (`publish_card` marker `affiliate`).

Stdlib only; loaded by path (`inserts/validate_inserts.py`,
`agents/publisher/publish_card.py`).
"""
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

RULE = "CF-0593"
KEY = "affiliate"                       # channels/<id>.json -> affiliate
LIST_NAME = "affiliate"                 # shared/channel_data.LISTS
FILENAME = "affiliate.json"             # channels/<id>/affiliate.json
NOTE_KEY, NOTE_SUFFIX = "note", "_note"
BLOCK_KEYS = ("enabled", "link_line", "disclosure")
LINK_FIELDS = ("{product}", "{url}")
DEFAULT_NETWORK = "default"
ADDED_BY = "user"
SUBJECT_FIELDS = ("tool", "model", "name")
SUBJECT_ALIASES = "aliases"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELD_RE = re.compile(r"\{([^{}]*)\}")

# Words that make a line around a link a claim - about price, quality, rank,
# urgency or certainty. Per language; a channel whose language has no list
# cannot switch the slot on (nothing would check its words).
CLAIM_WORDS = {
    "en": ("best", "better", "cheapest", "cheaper", "cheap", "lowest", "lower", "price",
           "prices", "priced", "pricing", "deal", "deals", "discount", "discounts",
           "discounted", "sale", "sales", "save", "saves", "saving", "savings", "bargain",
           "offer", "offers", "free", "top", "greatest", "ultimate", "perfect", "favorite",
           "favourite", "recommend", "recommended", "recommends", "must", "guaranteed",
           "guarantee", "exclusive", "limited", "hurry", "now", "today", "only", "official",
           "officially", "confirmed", "proven", "value", "worth", "coupon", "promo",
           "lifetime", "unbeatable", "fastest", "leading", "number", "trusted"),
}
CLAIM_SIGNS_RE = re.compile(r"[%$€£¥₽]|#\s*1\b|\bno\.?\s*1\b", re.I)

# The reasons of a decision.
PLACED = "placed"
OFF = "off"                              # the block is absent or enabled: false
SLOT_INVALID = "slot_invalid"            # switched on, the block or the table invalid
NO_PRODUCTS = "no_products"
NO_SUBJECT = "topic_has_no_subject"
NO_MATCH = "no_match"
NEAR_MISS = "near_miss"
FACT_SILENT = "fact_does_not_name_product"
LINE_CLAIM = "line_carries_claim"
REASONS = (PLACED, OFF, SLOT_INVALID, NO_PRODUCTS, NO_SUBJECT, NO_MATCH, NEAR_MISS,
           FACT_SILENT, LINE_CLAIM)


# ------------------------------------------------------------------ names
def tokens(text):
    """Lower-case letters/digits runs of a text, accents folded."""
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return [t for t in re.split(r"[^0-9a-z]+", folded.casefold()) if t]


def compact(text):
    """A name with case, accents, spaces and punctuation aside: the form two
    names are compared in ("GPT-6" -> "gpt6")."""
    return "".join(tokens(text))


def subject_forms(title_ref):
    """The topic's own names - `tool`, `model`, `name`, then `aliases` -
    distinct, as written."""
    ref = title_ref if isinstance(title_ref, dict) else {}
    raw = [ref.get(k) for k in SUBJECT_FIELDS]
    al = ref.get(SUBJECT_ALIASES)
    raw += list(al) if isinstance(al, list) else []
    out, seen = [], set()
    for f in raw:
        if isinstance(f, str) and compact(f) and compact(f) not in seen:
            seen.add(compact(f))
            out.append(f.strip())
    return out


def product_forms(product):
    """A product's `names` then `aliases`, as written."""
    out = []
    for k in ("names", "aliases"):
        v = product.get(k) if isinstance(product, dict) else None
        out += [x.strip() for x in v if isinstance(x, str) and compact(x)] if isinstance(v, list) else []
    return out


def names_in(text, form):
    """Whether `text` carries `form` as a run of whole words (its compact
    form equal to the joined run - "GPT-6" is in "OpenAI's GPT 6 shipped")."""
    want = compact(form)
    if not want:
        return False
    toks = tokens(text)
    for i in range(len(toks)):
        run = ""
        for j in range(i, len(toks)):
            run += toks[j]
            if run == want:
                return True
            if len(run) >= len(want) or not want.startswith(run):
                break
    return False


def claim_words(text, language="en"):
    """The claim words and signs a line carries ([] when none); None when
    the language has no list."""
    words = CLAIM_WORDS.get(language)
    if words is None:
        return None
    have = set(re.findall(r"[a-z0-9]+", str(text or "").casefold()))
    hits = sorted(w for w in words if w in have)
    hits += [m.group(0) for m in CLAIM_SIGNS_RE.finditer(str(text or ""))]
    return hits


# ------------------------------------------------------------------ the block
def _iso_day(value):
    if not isinstance(value, str) or not ISO_DAY_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _https(url):
    if not isinstance(url, str) or url != url.strip() or " " in url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.netloc)


def block_errors(block, language="en", ctx="affiliate"):
    """Why a channel's `affiliate` block is not valid ([] when it is)."""
    if not isinstance(block, dict):
        return [f"{ctx}: must be an object (`enabled`, `link_line`, `disclosure`), "
                f"got {type(block).__name__}"]
    errs = []
    for k in block:
        if k not in BLOCK_KEYS and k != NOTE_KEY and not k.endswith(NOTE_SUFFIX):
            errs.append(f"{ctx}.{k}: unknown key (known: {', '.join(BLOCK_KEYS)}, `note`)")
    for k in [NOTE_KEY] + [k for k in block if k.endswith(NOTE_SUFFIX)]:
        if k in block and not isinstance(block[k], str):
            errs.append(f"{ctx}.{k}: prose for a human, must be a string")
    if not isinstance(block.get("enabled"), bool):
        errs.append(f"{ctx}.enabled: must be true or false (the user switches the slot "
                    f"on), got {block.get('enabled')!r}")
    words = CLAIM_WORDS.get(language)
    if words is None:
        errs.append(f"{ctx}: no claim-word list for language {language!r} - the words "
                    f"around a link cannot be checked (shared/affiliate.py CLAIM_WORDS)")
    line = block.get("link_line")
    if not isinstance(line, str) or not line.strip():
        errs.append(f"{ctx}.link_line: must be a string with {', '.join(LINK_FIELDS)}")
    else:
        fields = ["{" + f + "}" for f in FIELD_RE.findall(line)]
        missing = [f for f in LINK_FIELDS if f not in fields]
        extra = sorted(set(fields) - set(LINK_FIELDS))
        if missing:
            errs.append(f"{ctx}.link_line: no {', '.join(missing)} in it")
        if extra:
            errs.append(f"{ctx}.link_line: unknown field(s) {', '.join(extra)} (only "
                        f"{', '.join(LINK_FIELDS)} are filled)")
        if "affiliate" not in tokens(line):
            errs.append(f"{ctx}.link_line: must say `affiliate` in its own words - the "
                        f"viewer is told the link is one")
        bare = FIELD_RE.sub(" ", line)
        hits = claim_words(bare, language)
        if hits:
            errs.append(f"{ctx}.link_line: carries claim word(s) {', '.join(hits)} - the line "
                        f"around a link is plain")
    disc = block.get("disclosure")
    if not isinstance(disc, dict) or not disc:
        errs.append(f"{ctx}.disclosure: must be an object of network -> line, with "
                    f"`{DEFAULT_NETWORK}`")
    else:
        if DEFAULT_NETWORK not in disc:
            errs.append(f"{ctx}.disclosure: no `{DEFAULT_NETWORK}` line - a network without "
                        f"its own needs one")
        for net, text in disc.items():
            if not SLUG_RE.match(str(net)):
                errs.append(f"{ctx}.disclosure.{net}: a network id is lower-case "
                            f"letters, digits, `_`, `-`")
            if not isinstance(text, str) or not text.strip():
                errs.append(f"{ctx}.disclosure.{net}: must be a non-empty line")
                continue
            if FIELD_RE.search(text):
                errs.append(f"{ctx}.disclosure.{net}: a disclosure is said as written, "
                            f"nothing is filled into it")
            hits = claim_words(text, language)
            if hits:
                errs.append(f"{ctx}.disclosure.{net}: carries claim word(s) "
                            f"{', '.join(hits)}")
    return errs


def enabled(cfg):
    """Whether the channel's slot is switched on (absent = off)."""
    block = cfg.get(KEY) if isinstance(cfg, dict) else None
    return isinstance(block, dict) and block.get("enabled") is True


# ------------------------------------------------------------------ the table
def table_errors(table, language="en", ctx=FILENAME):
    """Why a channel's programmes-and-links table is not valid ([] when it is)."""
    if not isinstance(table, dict):
        return [f"{ctx}: must be an object with `programmes` and `products`"]
    errs = []
    for k in table:
        if k not in ("channel_id", "programmes", "products", NOTE_KEY) \
                and not k.endswith(NOTE_SUFFIX):
            errs.append(f"{ctx}.{k}: unknown key")
    progs, prods = table.get("programmes"), table.get("products")
    if not isinstance(progs, list):
        errs.append(f"{ctx}.programmes: must be a list (empty until the user registers one)")
        progs = []
    if not isinstance(prods, list):
        errs.append(f"{ctx}.products: must be a list (empty until the user adds a link)")
        prods = []

    def who(e, c):
        if e.get("added_by") != ADDED_BY:
            errs.append(f"{c}.added_by: must be `{ADDED_BY}` - the machine never adds a "
                        f"programme or a link, got {e.get('added_by')!r}")
        if not _iso_day(e.get("added_at")):
            errs.append(f"{c}.added_at: must be a day YYYY-MM-DD, got {e.get('added_at')!r}")

    known = {}
    for i, p in enumerate(progs):
        c = f"{ctx}.programmes[{i}]"
        if not isinstance(p, dict):
            errs.append(f"{c}: must be an object")
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not SLUG_RE.match(pid):
            errs.append(f"{c}.id: a slug, got {pid!r}")
        elif pid in known:
            errs.append(f"{c}.id: `{pid}` twice")
        else:
            known[pid] = p
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            errs.append(f"{c}.name: must be a non-empty string")
        if not isinstance(p.get("network"), str) or not SLUG_RE.match(p["network"]):
            errs.append(f"{c}.network: a network id (e.g. `amazon_associates`), "
                        f"got {p.get('network')!r}")
        marks = [p.get(k) for k in ("tag", "ref") if p.get(k) is not None]
        if not marks or not all(isinstance(m, str) and m.strip() for m in marks):
            errs.append(f"{c}: needs its `tag` or `ref` (the user's id in the programme), "
                        f"a non-empty string")
        who(p, c)
    forms = {}
    ids = set()
    for i, p in enumerate(prods):
        c = f"{ctx}.products[{i}]"
        if not isinstance(p, dict):
            errs.append(f"{c}: must be an object")
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not SLUG_RE.match(pid):
            errs.append(f"{c}.id: a slug, got {pid!r}")
        elif pid in ids:
            errs.append(f"{c}.id: `{pid}` twice")
        ids.add(pid)
        names = p.get("names")
        if not isinstance(names, list) or not names or not all(
                isinstance(n, str) and compact(n) for n in names):
            errs.append(f"{c}.names: a non-empty list of the product's names (the first is "
                        f"how the link line names it)")
        al = p.get("aliases", [])
        if not isinstance(al, list) or not all(isinstance(n, str) and compact(n) for n in al):
            errs.append(f"{c}.aliases: a list of names")
        for f in product_forms(p):
            other = forms.get(compact(f))
            if other is not None and other != pid:
                errs.append(f"{c}: name {f!r} is also product `{other}`'s - one name, one "
                            f"product (one link per video)")
            forms.setdefault(compact(f), pid)
        if isinstance(names, list) and names and isinstance(names[0], str):
            hits = claim_words(names[0], language) or []
            if hits:
                errs.append(f"{c}.names[0]: {names[0]!r} carries claim word(s) "
                            f"{', '.join(hits)} - it goes into the link line")
            if "{" in names[0] or "}" in names[0] or "<" in names[0] or ">" in names[0]:
                errs.append(f"{c}.names[0]: no braces or angle brackets in a name")
        url = p.get("url")
        if not _https(url):
            errs.append(f"{c}.url: must be a full https URL (the user's affiliate link), "
                        f"got {url!r}")
        prog = known.get(p.get("programme"))
        if prog is None:
            errs.append(f"{c}.programme: {p.get('programme')!r} is not a programme of the table")
        elif _https(url):
            marks = [prog.get(k) for k in ("tag", "ref") if isinstance(prog.get(k), str)]
            if marks and not any(m in url for m in marks):
                errs.append(f"{c}.url: does not carry programme `{prog['id']}`'s "
                            f"{'tag' if prog.get('tag') else 'ref'} - a link without it earns "
                            f"nothing, one with another is somebody else's")
        who(p, c)
    return errs


def table_path(cfg_path):
    """`channels/<id>/affiliate.json` beside `channels/<id>.json`."""
    cfg_path = Path(cfg_path)
    return cfg_path.parent / cfg_path.stem / FILENAME


def read_table(cfg_path):
    """`(table, errors)` of the channel's table; (None, [why]) when it is
    missing or does not parse."""
    path = table_path(cfg_path)
    if not path.is_file():
        return None, [f"{path}: missing - the channel's affiliate table "
                      f"(docs/channel-data.md «Affiliate links»)"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as exc:
        return None, [f"{path}: does not parse: {exc}"]


def channel_errors(cfg, cfg_path, ctx=None):
    """Every error of a channel's affiliate slot: the block, and the table
    beside the config - required when the slot is on, checked whenever it is
    there. [] for a channel with no block and no table."""
    ctx = ctx or Path(cfg_path).name
    language = cfg.get("language") or "en"
    errs = []
    has_block = KEY in cfg
    if has_block:
        errs += block_errors(cfg[KEY], language, ctx=f"{ctx}.{KEY}")
    path = table_path(cfg_path)
    if path.is_file() or enabled(cfg):
        table, read = read_table(cfg_path)
        errs += read
        if table is not None:
            errs += table_errors(table, language, ctx=f"{path.parent.name}/{FILENAME}")
            if not has_block:
                errs.append(f"{ctx}: `{path.parent.name}/{FILENAME}` is there and the config "
                            f"has no `{KEY}` block - the table is read through the switch")
    return errs


# ------------------------------------------------------------------ the decision
def disclosure_of(block, network):
    disc = block.get("disclosure") or {}
    return disc.get(network) or disc.get(DEFAULT_NETWORK)


def link_label(line, url):
    """The link line without its URL - the words the claim check reads."""
    return re.sub(r"[\s:·—–-]+$", "", line.replace(url, "")).strip()


def decide(cfg, table, title_ref, script, table_problems=()):
    """The decision for one video: `{rule, enabled, placed, reason, detail,
    subject, product, programme, network, url, line, label, disclosure,
    near_miss}`. `table` the parsed table (None when it could not be read),
    `table_problems` its errors; `title_ref` the topic's (else the script's)."""
    block = cfg.get(KEY) if isinstance(cfg, dict) else None
    out = {"rule": RULE, "enabled": enabled(cfg), "placed": False, "reason": None,
           "detail": None, "subject": [], "product": None, "programme": None,
           "network": None, "url": None, "line": None, "label": None, "disclosure": None,
           "near_miss": []}

    def no(reason, detail):
        out.update(reason=reason, detail=detail)
        return out

    if not out["enabled"]:
        return no(OFF, "the channel's affiliate slot is off (`affiliate.enabled` is not true)")
    language = cfg.get("language") or "en"
    problems = block_errors(block, language) + list(table_problems)
    if table is None or problems:
        return no(SLOT_INVALID, "; ".join(problems) or "the table could not be read")
    products = [p for p in table.get("products") or [] if isinstance(p, dict)]
    if not products:
        return no(NO_PRODUCTS, "the channel's table has no product links yet")
    subject = subject_forms(title_ref)
    out["subject"] = subject
    if not subject:
        return no(NO_SUBJECT, "the topic names no tool, model, name or alias - nothing to "
                              "match a product to")
    want = {compact(f) for f in subject}
    hit = [p for p in products if want & {compact(f) for f in product_forms(p)}]
    if not hit:
        mine = {t for f in subject for t in tokens(f)}
        near = [p.get("id") for p in products
                if mine & {t for f in product_forms(p) for t in tokens(f)}]
        out["near_miss"] = near
        if near:
            return no(NEAR_MISS, f"the topic is {subject[0]!r}; product(s) "
                                 f"{', '.join(map(str, near))} share a word with it but are "
                                 f"not it - no link")
        return no(NO_MATCH, f"the topic is {subject[0]!r}; no product of the table is it")
    product = hit[0]
    out["product"] = product.get("id")
    script = script if isinstance(script, dict) else {}
    pf = script.get("production_fact") if isinstance(script.get("production_fact"), dict) else {}
    fact = script.get("fact") if isinstance(script.get("fact"), dict) else {}
    texts = [t for t in (pf.get("text"), fact.get("text")) if isinstance(t, str) and t.strip()]
    if not any(names_in(t, f) for t in texts for f in product_forms(product)):
        return no(FACT_SILENT, f"the topic is {product.get('id')}, but the script's fact does "
                               f"not name it - the video is not shown to be about it")
    prog = next((p for p in table.get("programmes") or []
                 if isinstance(p, dict) and p.get("id") == product.get("programme")), {})
    name = product["names"][0].strip()
    url = product["url"]
    line = block["link_line"].replace("{product}", name).replace("{url}", url)
    disclosure = disclosure_of(block, prog.get("network")).strip()
    out.update(programme=prog.get("id"), network=prog.get("network"), url=url, line=line,
               label=link_label(line, url), disclosure=disclosure)
    hits = claim_words(out["label"] + " " + disclosure, language)
    if hits:
        out.update(line=None, label=None, disclosure=None)
        return no(LINE_CLAIM, f"the link line or its disclosure would carry claim word(s) "
                              f"{', '.join(hits)} - no link")
    out.update(placed=True, reason=PLACED,
               detail=f"the topic is {product.get('id')} and the fact names it")
    return out


def decide_for(cfg, cfg_path, title_ref, script):
    """`decide` with the table read beside `cfg_path` - read only when the
    slot is on (a switched-off channel's table is not opened)."""
    table, problems = None, []
    if enabled(cfg):
        table, problems = read_table(cfg_path)
        if table is not None:
            problems += table_errors(table, cfg.get("language") or "en")
    return decide(cfg, table, title_ref, script, problems)


def labels_of(decision):
    """The words the claim check reads for a placed decision: the link line
    without its URL. The disclosure is not among them - it is a fixed line
    of the channel's config, checked claim-free here (`block_errors`), and a
    sentence about the channel, not the story: the claim judge would find it
    no footing in the video's sources and strike it, leaving a link without
    its disclosure."""
    if not decision or not decision.get("placed"):
        return []
    return [decision["label"]]


def lines_of(decision):
    """The description lines a placed decision adds (link, then disclosure)."""
    if not decision or not decision.get("placed"):
        return []
    return [decision["line"], decision["disclosure"]]


# ------------------------------------------------------------------ CF-0726: the checked write
def _list_write():
    """`shared/channel_list_write.py`, loaded by path when first needed - the
    readers of this module (the card, the channel check) load nothing more."""
    import importlib.util                                       # noqa: PLC0415
    import sys                                                  # noqa: PLC0415
    name = "_channel_list_write_for_affiliate"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parent / "channel_list_write.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def write_errors(table, channel, root):
    """CF-0726: why `table` may not become `channels/<channel>/affiliate.json`
    ([] when it may): `table_errors` in the channel's language, the table's
    `channel_id` (when it names one) is the channel's, and the config has the
    `affiliate` block the table is read through (`channel_errors`)."""
    cfg_path = Path(root) / "channels" / f"{channel}.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"channels/{channel}.json: cannot be read: {exc}"]
    if not isinstance(cfg, dict):
        return [f"channels/{channel}.json: not an object"]
    errs = table_errors(table, cfg.get("language") or "en", ctx=f"{channel}/{FILENAME}")
    if isinstance(table, dict) and table.get("channel_id") not in (None, channel):
        errs.append(f"{channel}/{FILENAME}.channel_id: {table.get('channel_id')!r} is not "
                    f"{channel!r} - the table is this channel's")
    if KEY not in cfg:
        errs.append(f"channels/{channel}.json: no `{KEY}` block - the table is read through "
                    f"the switch; a table without it is an error of the channel check")
    return errs


def write_table(channel, table, *, base_sha256, by, via, root=None, dry_run=False,
                commit=True, lock_wait=None, now=None, open_rows=None):
    """CF-0726: the checked write of the channel's programmes-and-links table
    (`channels/<id>/affiliate.json`) - `write_errors` as the schema, then the
    common checked write (`shared/channel_list_write.write_list`: by/via, no
    batch of the channel open, `base_sha256` the file's as the caller read it -
    None for no file -, the channel lists' lock, an atomic write committed
    alone). The answer dict of `write_list`; a refusal is never raised.
    The table is the user's (`added_by: user` on every row): the machine never
    adds a programme or a link, this function only writes what it is given."""
    lw = _list_write()
    return lw.write_list(channel, LIST_NAME, table, base_sha256=base_sha256, by=by, via=via,
                         errors=write_errors, root=root, dry_run=dry_run, commit=commit,
                         lock_wait=lw.LOCK_WAIT if lock_wait is None else lock_wait,
                         now=now, open_rows=open_rows)
