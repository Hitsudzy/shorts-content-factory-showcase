"""CF-0883: what the claims reader lists in a hook that is not a claim of
its own - the words of the channel's opener formula, and a work's title
with a subtitle colon.

Evidence (the Reel funnel of 2026-10-20..27): 4 of the 5 `claim_unsupported`
losses were one `claim_undeclared` on the hook or the payoff while every
declared claim (8-16 of them) followed. Two of them were the factory's own
words, not the writer's facts:

* `example-film/2026-10-26T0841Z` -008: the hook "Before you watch Vanguards:
  Doomsday, know this: four quick things, one at a time." (the channel's
  `before-you-watch` opener). The reader listed "Vanguards: Doomsday" - the
  title - as a claim. The root's CF-0758 reads a bare name as no more than
  the name (`claim_judge.bare_name`), but the colon of a subtitle makes it
  "not a name" there, and a name is matched only to a declared claim that is
  itself only the name - while `c8` ("... the one the studio called Vanguards
  5 now had a new title: Doomsday") had followed.
* `example-film/2026-10-25T1819Z` -008: "Everyone missed the part of Wildwood
  where the film was already shooting, before anyone had announced it." (the
  `everyone-missed` opener). The opener's own words ("everyone missed the
  part of") count against the coverage of a declared hook claim (the root's
  `coverage` is measured on the reader's span): a hook claim that says the
  fact word for word can still fall under `MATCH_MIN` on the formula's words.

The channel's note on the library (CF-0424, the user's decision of
2026-09-28): the opener's own words are free - "that relaxation covers the
opener's own words only". So here, after the judge and with no model call:

* a listed hook statement that opens on one of the HYPE_FRAMES formulas is
  read without the formula's words - the slots only - and matched by the
  root's own rule (`claim_judge.match_extracted`: same field, coverage,
  union, bare name, change frame) against the declared claims the judge read
  as following. A formula that states something checkable in its own words
  ("{x} almost didn't happen, because ...", "The real reason {x} ...",
  "{x} was never supposed to ...", "People are still arguing ...") is not
  in HYPE_FRAMES and is matched as the reader listed it;
* a listed hook / payoff statement that is a bare name once a subtitle colon
  is read as a space ("Vanguards: Doomsday") is matched to a declared claim
  that follows and holds every content word of the name.

The fact check is not weakened: every fact still needs a declared claim that
the judge read as following from its quote; what is dropped is the formula
and the bare title, which assert nothing a source could support. A slot that
says more than the supported claims stays `claim_undeclared`.
"""
import re

import hook_openers as ho

RULE = "CF-0883"
RELIEF_KEY = "not_claims"               # on the record: what was read as no claim, and why
WHERES = ("hook", "payoff")
UNDECLARED = "claim_undeclared"         # = claim_judge.FAIL_UNDECLARED
SUPPORTED = "supported"                 # = claim_judge.STATE_SUPPORTED
ACTION_PASS, ACTION_FAIL = "pass", "fail"
# The formulas of the channels' libraries whose own words only point at what
# follows (attention, a superlative the note leaves free) - ids of
# `channels/<channel>.json` -> content_researcher.hook_openers. An id not here
# is matched as the reader listed it.
HYPE_FRAMES = frozenset((
    "most-talked-about", "most-important", "nobody-noticed", "everyone-missed",
    "what-nobody-tells-you", "strangest-thing", "one-detail", "before-you-watch",
    "sounds-made-up", "wildest-fact"))
_SLOT_RE = re.compile(r"\{[^{}]*\}")
WHY_FRAME, WHY_NAME = "opener_frame", "bare_title"


def _tokens(text):
    """[(normalized word, index of the original token)] of a text."""
    out, orig = [], (text or "").split()
    for i, tok in enumerate(orig):
        for w in ho.normalize(tok).split():
            out.append((w, i))
    return out, orig


def frame_slots(text, template):
    """The words of the text that fill the formula's slots (in the text's own
    case and punctuation, joined by a space), or None when the text does not
    open on the formula. Adjacent slots are one; the last one runs to the end."""
    elements = []
    for piece in re.split(r"(\{[^{}]*\})", template or ""):
        if not piece:
            continue
        if _SLOT_RE.fullmatch(piece):
            if not elements or elements[-1] is not None:
                elements.append(None)
            continue
        elements.extend(ho.normalize(piece).split())
    if None not in elements:
        return None
    toks, orig = _tokens(text)
    words = [w for w, _ in toks]
    joined = " ".join(words)
    parts, n_slots = [], 0
    for i, e in enumerate(elements):
        if e is None:
            last = all(x is None for x in elements[i + 1:])
            parts.append(r"(\S+(?: \S+)*)" if last else r"(\S+(?: \S+)*?)")
            n_slots += 1
        else:
            parts.append(re.escape(e))
    m = re.match("^" + " ".join(parts) + r"(?= |$)", joined)
    if not m:
        return None
    pieces = []
    for g in range(1, n_slots + 1):
        a, b = m.span(g)
        first = len(joined[:a].split())
        last = first + len(joined[a:b].split()) - 1
        lo, hi = toks[first][1], toks[last][1]
        pieces.append(" ".join(orig[lo:hi + 1]))
    return " ".join(pieces)


def frames_of(script, library):
    """The HYPE_FRAMES templates the script's hook may stand on: its
    `hook_opener_id`, else every hype formula the hook opens with."""
    lib = {o["id"]: o["template"] for o in library or []
           if isinstance(o, dict) and o.get("id") in HYPE_FRAMES and o.get("template")}
    oid = (script or {}).get(ho.FIELD)
    if oid in lib:
        return [lib[oid]]
    hook = (script or {}).get("hook") or ""
    return [t for t in lib.values() if ho.opens_with(hook, t)]


def title_name(judge, text):
    """CF-0758's bare name with a subtitle colon read as a space
    ("Vanguards: Doomsday" -> "Vanguards Doomsday"), None for anything else."""
    bare = getattr(judge, "bare_name", None)
    if bare is None or not isinstance(text, str) or ":" not in text:
        return None
    return bare(re.sub(r"\s*:\s*", " ", text.strip()))


def _supported(record, script):
    ok = {v.get("claim_id") for v in record.get("verdicts") or []
          if isinstance(v, dict) and v.get("state") == SUPPORTED}
    return [c for c in (script or {}).get("claims") or []
            if isinstance(c, dict) and c.get("claim_id") in ok and isinstance(c.get("text"), str)]


def relieve(record, script, judge, library):
    """Read the undeclared hook / payoff statements of a judged record again
    without the opener's formula and with a titled name as a name. Each one
    matched to a claim that followed leaves `violations[]` for
    `record[RELIEF_KEY]`, its `extracted[]` row gets the match; a record left
    with nothing struck, nothing undeclared and its mechanics clean passes.
    Returns the entries moved (empty: the record is untouched)."""
    if record.get("refuse_now"):
        return []
    match = getattr(judge, "match_extracted", None)
    content = getattr(judge, "_content", None)
    if match is None or content is None:
        return []
    supported = _supported(record, script)
    if not supported:
        return []
    frames = frames_of(script, library)
    moved, kept = [], []
    for v in record.get("violations") or []:
        hit = None
        if v.get("code") == UNDECLARED and v.get("where") in WHERES \
                and isinstance(v.get("text"), str):
            hit = _match(v, frames, supported, script, match, content, judge)
        if hit is None:
            kept.append(v)
            continue
        why, rest, ids = hit
        moved.append({"rule": RULE, "where": v["where"], "text": v["text"], "why": why,
                      "read_as": rest, "matched": ids})
        for item in record.get("extracted") or []:
            if item.get("where") == v["where"] and item.get("text") == v["text"] \
                    and not item.get("matched"):
                item["matched"] = ids
                item["matched_by"] = f"{RULE}:{why}"
    if not moved:
        return []
    record["violations"] = kept
    record.setdefault(RELIEF_KEY, []).extend(moved)
    mech = record.get("mechanics") or {}
    if not kept and not record.get("struck") and mech.get("action", ACTION_PASS) == ACTION_PASS:
        record["action"] = ACTION_PASS
    return moved


def _name_hit(name, supported, content):
    want = set(content(name))
    if not want:
        return []
    return [c["claim_id"] for c in supported if want <= set(content(c["text"]))]


def _match(v, frames, supported, script, match, content, judge):
    """(why, the text read, [claim ids]) or None."""
    text = v["text"]
    if v["where"] == "hook":
        for template in frames:
            rest = frame_slots(text, template)
            if not rest:
                continue
            ids = match([{"where": "hook", "text": rest}], supported, script)[0]
            if not ids:
                name = title_name(judge, rest)
                ids = _name_hit(name, supported, content) if name else []
            if ids:
                return WHY_FRAME, rest, ids
    name = title_name(judge, text)
    if name:
        ids = _name_hit(name, supported, content)
        if ids:
            return WHY_NAME, name, ids
    return None
