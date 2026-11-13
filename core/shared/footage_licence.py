"""CF-0564: the common rule that reads a piece of footage's licence against a
channel's licence lists, and the shape check of a channel's footage-origin
document.

The lists are the channel's data - `licences` of `channels/<id>/footage-origin.json`
(read through `shared/channel_data.py` `footage_origin(channel)`): which
licences the channel takes, which it refuses, and what each asks for in
credit. This module is the rule that reads them, common to every channel, the
way `shared/factrule/fact_rule.py` reads a channel's fact sources:

  * a licence is a short name as the origin writes it - Commons'
    `extmetadata.LicenseShortName` («CC BY-SA 4.0», «Public domain»,
    «PD-USGov-NASA»), ESA's LICENCE line, YouTube's `status.license`;
  * a refused token wins over everything: a licence naming NC or ND is
    refused even when it also matches an accepted family (CC BY-NC-SA is
    not CC BY-SA), and so is a file its archive marks non-free;
  * otherwise the longest accepted match on whole leading words decides
    («cc by sa 4.0» is `cc_by_sa`, not `cc_by`);
  * anything else - an empty name, an unknown licence - is refused with the
    name in the reason. There is no default licence.

Nobody calls `licence_of` yet: the Trend Hunter and Footage Indexer changes
of docs/science-footage.md do. `footage_origin_errors` is what a reader (and
tests/test_example_science_footage.py) checks a document with before it trusts
it.

CF-0567 (ExampleTech): an origin under the `own_capture` licence is the
factory's own screen recording of a public page - no licence is granted
because none is needed, so it has no `terms_url` of its own. What it has
instead is the channel's `capture_hosts`: the hosts a recording may be made
on, each with its robots.txt verdict and its terms on record (the 08.10
source rule), and `capture_host_errors` holds that list whole.
`capture_allowed(url, doc)` is the one question the recorder asks before it
opens a page. An official channel whose `role` is `proof_quote` is a source
of short quotes only, and the document then carries `proof_quotes` - the
caps a Video Editor holds a quote to. A channel without `own_capture` or
`proof_quote` (ExampleScience, ExampleFilm) is judged exactly as before.

CF-0689 (ExampleTech): an origin under the `own_graphic` licence is the
graphics the factory draws itself (Remotion) from the script's own facts
(`shared/own_graphic.py`) - nothing borrowed, no credit, no terms page, and,
unlike `own_capture`, no host either: it is found by `drawn` only, and a
`drawn` origin is never anything but `own_graphic`. A document without an
`own_graphic` origin is judged exactly as before.

CF-0690 (ExampleTech): an origin under the `api_demo` licence is a model's
REAL answer, asked by the factory through the model's official API (the
Gemini API free tier, `shared/gemini/gemini_api.py`) and drawn in the
factory's own chat animation (`shared/own_graphic.py` template `api_chat`,
held to the call's record by `shared/api_demo.py`). It is found by
`api_call` only, and an `api_call` origin is never anything but `api_demo`;
unlike our own drawing it has an https `terms_url` (the API's terms, under
which its outputs may be published) and an `ai_policy` record of them. The
document then carries the `api_demo` block - the models the channel names,
its neutral prompts, the call caps (`api_demo_errors`). A document without an
`api_demo` origin is judged exactly as before.

Loads nothing of the checkout by name; an agent loads it by path
(`spec_from_file_location`), like `channel_data.py`.
"""
import re

REFUSED_KEY = "refused"
ACCEPTED_KEY = "accepted"
ATTRIBUTION_VALUES = ("required", "requested", "none")
# How an origin's footage is found (`footage_origins[].found_by[].how`).
FOUND_BY = ("youtube_channels", "youtube_search", "archive_api", "archive_page", "stock_api",
            # CF-0567: the factory's own recording of a page on a `capture_hosts` host
            "screen_capture",
            # CF-0689: the factory's own graphic, drawn from the script's facts
            "drawn",
            # CF-0690: a model's real answer, asked through its official API
            "api_call")
# CF-0567: the licence of the factory's own screen recording. Not
# `screen_recording`: that name is footage-indexer's cinema cam-rip defect
# (shared/gate-prices.json rules["score.hard.screen_recording"]).
OWN_CAPTURE = "own_capture"
CAPTURE_HOSTS_KEY = "capture_hosts"
# CF-0689: the licence of the graphics the factory draws itself from the
# script's facts (shared/own_graphic.py), and the one way they are found.
OWN_GRAPHIC = "own_graphic"
DRAWN = "drawn"
# CF-0690: the licence of a model's answer asked through its official API
# (shared/api_demo.py), the one way it is found, and the document's block.
API_DEMO = "api_demo"
API_CALL = "api_call"
API_DEMO_KEY = "api_demo"
API_DEMO_PROVIDERS = ("gemini_api",)
API_DEMO_LABEL_SUFFIX = " · via API"         # = api_demo.LABEL_SUFFIX
API_DEMO_LABEL_MAX = 48                      # = api_demo.LABEL_MAX_CHARS
API_DEMO_PROMPT_MAX = 160                    # = api_demo.PROMPT_MAX_CHARS
API_DEMO_ANSWER_MAX = 400                    # a channel's max_answer_chars at most
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
CAPTURE_USES = ("capture", "closed")
# The verdicts a capture host's terms are recorded with: only `allowed` lets a
# host be `capture`; `unread` is not permission and `ambiguous` reads as a ban
# (the user's rule of 08.10).
TERMS_VERDICTS = ("allowed", "forbidden", "ambiguous", "unread")
# An official channel's role: `footage` (its uploads are the video's footage,
# the default - ExampleFilm, ExampleScience) or `proof_quote` (a short quote
# only, never the base of a video - ExampleTech, CF-0567).
CHANNEL_ROLES = ("footage", "proof_quote")
PROOF_QUOTE = "proof_quote"
PROOF_QUOTES_KEY = "proof_quotes"
# An origin whose licence is decided per file by its archive, not once for it.
PER_FILE = "per_file"
CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
HANDLE_RE = re.compile(r"^@[0-9A-Za-z_.-]{3,30}$")


def _words(text):
    """'CC BY-SA 4.0' -> ['cc', 'by', 'sa', '4.0']; 'PD-USGov-NASA' -> ['pd', 'usgov', 'nasa']."""
    return re.findall(r"[0-9a-z]+(?:\.[0-9a-z]+)*", str(text or "").lower())


def _phrase_in(words, phrase):
    p = _words(phrase)
    return bool(p) and any(words[k:k + len(p)] == p for k in range(len(words) - len(p) + 1))


def licence_of(short_name, licences, non_free=False):
    """-> {"accepted", "id", "reason", "attribution", "share_alike",
    "license_url", "short_name"} for one licence name against a channel's
    `licences` block.

    `non_free` is the archive's own flag (Commons `extmetadata.NonFree`); a
    true value refuses whatever the name says.
    """
    words = _words(short_name)
    out = {"accepted": False, "id": None, "reason": None, "attribution": None,
           "share_alike": None, "license_url": None, "short_name": short_name}
    if non_free:
        out.update(id="non_free", reason=f"the archive marks {short_name!r} non-free")
        return out
    if not words:
        out["reason"] = "no licence named - there is no default licence"
        return out
    for entry in (licences or {}).get(REFUSED_KEY) or []:
        for token in entry.get("tokens") or []:
            if _phrase_in(words, token):
                out.update(id=entry.get("id"),
                           reason=f"{short_name!r} names {token!r}: {entry.get('what')}")
                return out
    best, best_len = None, 0
    for entry in (licences or {}).get(ACCEPTED_KEY) or []:
        for match in entry.get("matches") or []:
            m = _words(match)
            if m and words[:len(m)] == m and len(m) > best_len:
                best, best_len = entry, len(m)
    if best is None:
        out["reason"] = (f"{short_name!r} is not a licence this channel takes "
                         f"(footage-origin.json `licences.accepted`)")
        return out
    out.update(accepted=True, id=best.get("id"), attribution=best.get("attribution"),
               share_alike=bool(best.get("share_alike")), license_url=best.get("license_url"))
    return out


def origin(doc, origin_id):
    """The `footage_origins` entry named `origin_id`, or None."""
    for o in (doc or {}).get("footage_origins") or []:
        if isinstance(o, dict) and o.get("id") == origin_id:
            return o
    return None


def _str(v):
    return isinstance(v, str) and v.strip() != ""


def footage_origin_errors(doc):
    """Why a footage-origin document with `footage_origins` is not one a
    reader may trust ([] when it is): every licence has an id and its
    attribution; every origin says how it is found, which licence it is
    under (an accepted id, or `per_file`), where its terms are (a URL, or
    None only for an origin under `youtube_upload`, which has no terms of its
    own) and how it is credited; every official channel names a known origin
    and carries a well-formed channel id, its handle and how it was resolved."""
    errs = []
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    lic = doc.get("licences")
    if not isinstance(lic, dict):
        return ["no `licences` block"]
    accepted = lic.get(ACCEPTED_KEY) or []
    acc_ids = set()
    for i, a in enumerate(accepted):
        ctx = f"licences.accepted[{i}]"
        if not _str(a.get("id")):
            errs.append(f"{ctx}: no id")
            continue
        if a["id"] in acc_ids:
            errs.append(f"{ctx}: id {a['id']!r} twice")
        acc_ids.add(a["id"])
        if a.get("attribution") not in ATTRIBUTION_VALUES:
            errs.append(f"{ctx} ({a['id']}): attribution must be one of {ATTRIBUTION_VALUES}")
        if not a.get("matches") or not all(_str(m) for m in a["matches"]):
            errs.append(f"{ctx} ({a['id']}): no `matches`")
        if not isinstance(a.get("share_alike"), bool):
            errs.append(f"{ctx} ({a['id']}): `share_alike` must be true or false")
    if not acc_ids:
        errs.append("licences.accepted is empty")
    for i, r in enumerate(lic.get(REFUSED_KEY) or []):
        if not _str(r.get("id")) or not _str(r.get("what")):
            errs.append(f"licences.refused[{i}]: needs `id` and `what`")
        if not r.get("tokens") and not _str(r.get("terms_url")):
            errs.append(f"licences.refused[{i}]: neither `tokens` to refuse by nor the "
                        f"`terms_url` that refuses it")
    origins = doc.get("footage_origins")
    if not isinstance(origins, list) or not origins:
        errs.append("no `footage_origins` list")
        origins = []
    ids = set()
    for i, o in enumerate(origins):
        ctx = f"footage_origins[{i}]"
        oid = o.get("id") if isinstance(o, dict) else None
        if not _str(oid):
            errs.append(f"{ctx}: no id")
            continue
        ctx = f"{ctx} ({oid})"
        if oid in ids:
            errs.append(f"{ctx}: id twice")
        ids.add(oid)
        licence = o.get("licence")
        if licence != PER_FILE and licence not in acc_ids:
            errs.append(f"{ctx}: licence {licence!r} is neither an accepted licence nor "
                        f"{PER_FILE!r}")
        terms = o.get("terms_url")
        if licence == OWN_CAPTURE:
            # our own recording: no licence page; the hosts' terms are on record
            if terms is not None:
                errs.append(f"{ctx}: an `{OWN_CAPTURE}` origin has no `terms_url` of its "
                            f"own - the terms that matter are each host's, in "
                            f"`{CAPTURE_HOSTS_KEY}`")
            errs.extend(capture_host_errors(doc))
        elif licence == OWN_GRAPHIC:
            # our own drawing: no licence page, no host - nothing is fetched
            if terms is not None:
                errs.append(f"{ctx}: an `{OWN_GRAPHIC}` origin has no `terms_url` - the "
                            f"graphic is drawn by the factory from the script's own facts")
        elif not (_str(terms) and terms.startswith("https://")) and licence != "youtube_upload":
            errs.append(f"{ctx}: no https `terms_url` - the page its licence was read on")
        how = o.get("found_by")
        if not isinstance(how, list) or not how:
            errs.append(f"{ctx}: no `found_by`")
        else:
            for j, h in enumerate(how):
                if (h or {}).get("how") not in FOUND_BY:
                    errs.append(f"{ctx}: found_by[{j}].how must be one of {FOUND_BY}")
                if not isinstance((h or {}).get("works_now"), bool):
                    errs.append(f"{ctx}: found_by[{j}] does not say `works_now`")
                if ((h or {}).get("how") == DRAWN) != (licence == OWN_GRAPHIC):
                    errs.append(f"{ctx}: found_by[{j}]: `{DRAWN}` is the way of the "
                                f"`{OWN_GRAPHIC}` origin and its only one")
                if ((h or {}).get("how") == API_CALL) != (licence == API_DEMO):
                    errs.append(f"{ctx}: found_by[{j}]: `{API_CALL}` is the way of the "
                                f"`{API_DEMO}` origin and its only one")
        if licence == API_DEMO:
            errs.extend(f"{ctx}: {e}" for e in api_demo_policy_errors(o))
        att = o.get("attribution")
        if not isinstance(att, dict) or not _str(att.get("credit")) or \
                att.get("where") not in ("description", "description+on_screen") or \
                not isinstance(att.get("on_screen"), bool):
            errs.append(f"{ctx}: `attribution` needs `credit`, `where` "
                        f"(description | description+on_screen) and `on_screen`")
        elif (att["where"] == "description+on_screen") != att["on_screen"]:
            errs.append(f"{ctx}: `attribution.where` and `on_screen` disagree")
    seen = set()
    for i, entry in enumerate(doc.get("official_channels") or []):
        ctx = f"official_channels[{i}] ({(entry or {}).get('pattern')})"
        if (entry or {}).get("origin") not in ids:
            errs.append(f"{ctx}: origin {(entry or {}).get('origin')!r} is not a footage origin")
        for j, ch in enumerate((entry or {}).get("channels") or []):
            cid = (ch or {}).get("id")
            if not (isinstance(cid, str) and CHANNEL_ID_RE.match(cid)):
                errs.append(f"{ctx} channels[{j}]: {cid!r} is not a YouTube channel id")
            elif cid in seen:
                errs.append(f"{ctx} channels[{j}]: {cid} listed twice")
            seen.add(cid)
            if not (isinstance(ch.get("handle"), str) and HANDLE_RE.match(ch["handle"])):
                errs.append(f"{ctx} channels[{j}]: no @handle it was resolved from")
            if not _str(ch.get("resolved_by")):
                errs.append(f"{ctx} channels[{j}]: says nothing about how it was resolved")
        role = (entry or {}).get("role", "footage")
        if role not in CHANNEL_ROLES:
            errs.append(f"{ctx}: role {role!r} is not one of {CHANNEL_ROLES}")
    if any((e or {}).get("role") == PROOF_QUOTE for e in doc.get("official_channels") or []):
        errs.extend(proof_quote_errors(doc))
    if any(isinstance(o, dict) and o.get("licence") == API_DEMO for o in origins):
        errs.extend(api_demo_errors(doc))
    return errs


def api_demo_policy_errors(o):
    """CF-0690: what an `api_demo` origin keeps on record of the API's terms -
    `ai_policy {checked_on, terms_url (https), terms_verdict, terms_note}`; the
    terms must have been read and found `allowed` (the 08.10 rule: unread is
    not permission, an ambiguous clause is a ban)."""
    pol = (o or {}).get("ai_policy")
    if not isinstance(pol, dict):
        return ["no `ai_policy` - the API's terms on record (when read, what they say)"]
    errs = []
    if not _str(pol.get("checked_on")):
        errs.append("ai_policy.checked_on missing")
    if not (_str(pol.get("terms_url")) and pol["terms_url"].startswith("https://")):
        errs.append("ai_policy.terms_url - the https terms page that was read")
    if pol.get("terms_verdict") != "allowed":
        errs.append(f"ai_policy.terms_verdict {pol.get('terms_verdict')!r} - only terms read "
                    f"and found `allowed` let the factory call the API")
    if not _str(pol.get("terms_note")):
        errs.append("ai_policy.terms_note - what the terms say, and when read")
    return errs


def _pos_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _pos_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def api_demo_errors(doc):
    """CF-0690: why the document's `api_demo` block may not be trusted ([]
    when it may): the provider, the models the channel names
    (`{id, display_name, matches[]}` - the label "<display_name> · via API"
    within the chat's cap), the default model among them, the neutral
    prompts (each within the chat's prompt cap), and the caps of the calls
    (`max_calls_per_batch`, `min_interval_seconds`, `timeout_seconds`,
    `max_answer_chars`)."""
    block = (doc or {}).get(API_DEMO_KEY)
    if not isinstance(block, dict):
        return [f"`{API_DEMO_KEY}` missing - an `{API_DEMO}` origin calls an API, and the "
                f"models, the prompts and the caps of its calls live there"]
    errs = []
    k = API_DEMO_KEY
    if block.get("provider") not in API_DEMO_PROVIDERS:
        errs.append(f"{k}.provider must be one of {API_DEMO_PROVIDERS}")
    models = block.get("models")
    ids = set()
    if not isinstance(models, list) or not models:
        errs.append(f"{k}.models must list the models the channel names")
        models = []
    for i, m in enumerate(models):
        ctx = f"{k}.models[{i}]"
        if not isinstance(m, dict):
            errs.append(f"{ctx}: not an object")
            continue
        mid = m.get("id")
        if not (isinstance(mid, str) and MODEL_ID_RE.match(mid)):
            errs.append(f"{ctx}: id {mid!r} is not a model id")
        elif mid in ids:
            errs.append(f"{ctx}: id {mid!r} twice")
        else:
            ids.add(mid)
        name = m.get("display_name")
        if not _str(name):
            errs.append(f"{ctx}: no display_name")
        elif len(name + API_DEMO_LABEL_SUFFIX) > API_DEMO_LABEL_MAX:
            errs.append(f"{ctx}: the label {name + API_DEMO_LABEL_SUFFIX!r} is over "
                        f"{API_DEMO_LABEL_MAX} characters")
        matches = m.get("matches")
        if not isinstance(matches, list) or not matches or not all(_str(x) for x in matches):
            errs.append(f"{ctx}: `matches` - the modelVersion words it is named by")
    if block.get("default_model") not in ids:
        errs.append(f"{k}.default_model {block.get('default_model')!r} is not one of the models")
    prompts = block.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        errs.append(f"{k}.prompts must list the channel's neutral prompts")
        prompts = []
    seen = set()
    for i, p in enumerate(prompts):
        if not _str(p):
            errs.append(f"{k}.prompts[{i}] must be a non-empty string")
        elif len(p) > API_DEMO_PROMPT_MAX:
            errs.append(f"{k}.prompts[{i}] is {len(p)} characters, over {API_DEMO_PROMPT_MAX}")
        elif p in seen:
            errs.append(f"{k}.prompts[{i}] twice")
        else:
            seen.add(p)
    if not _pos_int(block.get("max_calls_per_batch")):
        errs.append(f"{k}.max_calls_per_batch must be a whole number >= 1")
    for key in ("min_interval_seconds", "timeout_seconds"):
        if not _pos_number(block.get(key)):
            errs.append(f"{k}.{key} must be a positive number of seconds")
    mac = block.get("max_answer_chars")
    if not (_pos_int(mac) and mac <= API_DEMO_ANSWER_MAX):
        errs.append(f"{k}.max_answer_chars must be a whole number 1..{API_DEMO_ANSWER_MAX}")
    return errs


def proof_quote_errors(doc):
    """CF-0567: the caps a `proof_quote` channel's clip is held to - a quote
    of at most `max_seconds_per_quote`, at most `max_quotes_per_video` of
    them and `max_seconds_per_video` in all, never the base of a video."""
    pq = (doc or {}).get(PROOF_QUOTES_KEY)
    if not isinstance(pq, dict):
        return [f"`{PROOF_QUOTES_KEY}` missing - an official channel of role "
                f"`{PROOF_QUOTE}` is a short quote, and the caps it is held to live there"]
    errs = []
    nums = {}
    for key in ("max_seconds_per_quote", "max_seconds_per_video"):
        v = pq.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            errs.append(f"{PROOF_QUOTES_KEY}.{key} must be a positive number of seconds")
        else:
            nums[key] = float(v)
    n = pq.get("max_quotes_per_video")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        errs.append(f"{PROOF_QUOTES_KEY}.max_quotes_per_video must be a whole number >= 1")
    if len(nums) == 2 and nums["max_seconds_per_quote"] > nums["max_seconds_per_video"]:
        errs.append(f"{PROOF_QUOTES_KEY}: one quote may not be longer than all of them together")
    if pq.get("never_the_base") is not True:
        errs.append(f"{PROOF_QUOTES_KEY}.never_the_base must be true - a quote is never "
                    f"the footage a video is laid over (grill Q18)")
    return errs


def _host_matches(host, netloc):
    """`netloc` is `host` or a subdomain of it, on a dot boundary."""
    host, netloc = (host or "").lower().strip("."), (netloc or "").lower().split(":")[0]
    return bool(host) and (netloc == host or netloc.endswith("." + host))


def capture_host_errors(doc):
    """Why the `capture_hosts` list may not be trusted ([] when it may): every
    host says what is recorded there, that no sign-in is needed, its `use`
    (`capture` | `closed`) and its `ai_policy` - the robots.txt verdict with
    the reads it came from, the day, the terms page and what they say
    (`terms_verdict`, `terms_note`). A `capture` host needs the robots verdict
    `allowed`, the terms verdict `allowed` and no sign-in (the 08.10 rule:
    unread is not permission, an ambiguous clause is a ban); a `closed` host
    says why."""
    hosts = (doc or {}).get(CAPTURE_HOSTS_KEY)
    if not isinstance(hosts, list) or not hosts:
        return [f"no `{CAPTURE_HOSTS_KEY}` list - an `{OWN_CAPTURE}` origin records only "
                f"on hosts whose robots.txt and terms are on record"]
    errs, seen = [], set()
    for i, h in enumerate(hosts):
        ctx = f"{CAPTURE_HOSTS_KEY}[{i}] ({(h or {}).get('host')})"
        if not isinstance(h, dict) or not _str(h.get("host")):
            errs.append(f"{CAPTURE_HOSTS_KEY}[{i}]: no host")
            continue
        if h["host"] in seen:
            errs.append(f"{ctx}: host twice")
        seen.add(h["host"])
        if not _str(h.get("what")):
            errs.append(f"{ctx}: no `what` - what is recorded there")
        if not isinstance(h.get("sign_in"), bool):
            errs.append(f"{ctx}: `sign_in` must say true or false")
        use = h.get("use")
        if use not in CAPTURE_USES:
            errs.append(f"{ctx}: use {use!r} is not one of {CAPTURE_USES}")
        pol = h.get("ai_policy")
        if not isinstance(pol, dict):
            errs.append(f"{ctx}: no `ai_policy` - robots.txt and terms on record")
            continue
        if pol.get("verdict") not in ("allowed", "forbidden", "unknown"):
            errs.append(f"{ctx}: ai_policy.verdict must be allowed | forbidden | unknown")
        if not _str(pol.get("checked_on")):
            errs.append(f"{ctx}: ai_policy.checked_on missing")
        checks = pol.get("checks")
        if not isinstance(checks, list) or not checks or not all(
                isinstance(c, dict) and _str(c.get("robots_url")) and "verdict" in c
                for c in checks):
            errs.append(f"{ctx}: ai_policy.checks must hold the robots.txt reads")
        if not (_str(pol.get("terms_url")) and pol["terms_url"].startswith("https://")):
            errs.append(f"{ctx}: ai_policy.terms_url - the https terms page that was read")
        if pol.get("terms_verdict") not in TERMS_VERDICTS:
            errs.append(f"{ctx}: ai_policy.terms_verdict must be one of {TERMS_VERDICTS}")
        if not _str(pol.get("terms_note")):
            errs.append(f"{ctx}: ai_policy.terms_note - what the terms say, and when read")
        if use == "capture":
            if h.get("sign_in") is not False:
                errs.append(f"{ctx}: `capture` behind a sign-in - logged-in tools are out "
                            f"until the user decides (Q26)")
            if pol.get("verdict") != "allowed":
                errs.append(f"{ctx}: `capture` with robots verdict {pol.get('verdict')!r} - "
                            f"only `allowed` records (the 08.10 rule)")
            if pol.get("terms_verdict") != "allowed":
                errs.append(f"{ctx}: `capture` with terms {pol.get('terms_verdict')!r} - "
                            f"unread is not permission, an ambiguous clause is a ban")
        elif use == "closed" and not _str(h.get("why_closed")):
            errs.append(f"{ctx}: `closed` without `why_closed`")
    if not any((h or {}).get("use") == "capture" for h in hosts if isinstance(h, dict)):
        errs.append(f"{CAPTURE_HOSTS_KEY}: no host is `capture` - the origin can record nothing")
    return errs


def capture_allowed(url, doc):
    """-> (True, host entry) when `url` may be recorded: an https page on a
    `capture` host of the channel's `capture_hosts` (the host or a subdomain
    of it), else (False, the reason). A host this list does not name is
    refused - there is no default host. The recorder still reads the exact
    host's robots.txt for the exact path at capture time; this answers only
    what the channel decided."""
    from urllib.parse import urlsplit
    parts = urlsplit(str(url or ""))
    if parts.scheme != "https" or not parts.netloc:
        return False, f"{url!r} is not an https page"
    best = None
    for h in (doc or {}).get(CAPTURE_HOSTS_KEY) or []:
        if isinstance(h, dict) and _host_matches(h.get("host"), parts.netloc):
            if best is None or len(h["host"]) > len(best["host"]):
                best = h
    if best is None:
        return False, (f"{parts.netloc} is not on `{CAPTURE_HOSTS_KEY}` - a host is "
                       f"recorded on only after its robots.txt and terms are on record")
    if best.get("use") != "capture":
        return False, f"{best['host']} is closed for recording: {best.get('why_closed')}"
    if best.get("sign_in") is not False:
        return False, f"{best['host']} needs a sign-in (Q26)"
    return True, best
