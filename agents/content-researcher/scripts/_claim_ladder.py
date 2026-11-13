"""CF-0807: the pieces of the claims ladder (`check_claims.py`) that need no
model - the pronoun lint before the judge and the one deletion-only edit.

Evidence (`example-tech/2026-10-19T0844Z`, three topics lost as
`claim_unsupported`, each with 32 of 33 claims supported):

* 023 - the payoff "It began as Project Tailwind, a notebook that learns from
  documents." was struck `claim_not_enough`: the judge reads the claim alone
  and could not tell what "It" is; the first round had failed the same way on
  "These make…", "That computer runs…", "Now it runs code on them". A claim
  sentence that opens on a pronoun is now reported before the judge
  (`claim_subject_pronoun`), with no model call and no attempt spent, the way
  `attribution_forbidden` already is.
* 006 - graphic g15 "Replaces: Windows 11 Home" was the last unsupported line
  after the one rewrite; the topic was dropped for one deletable line. After
  the rewrite, when the only strikes left are claims that do not follow (not
  the video's own fact, no undeclared claim, no mechanics), the writer gets
  ONE more edit that only deletes: the sentences holding the struck claims,
  the struck graphics, the claims that stood on them. Nothing is added
  anywhere - `deletion_problems` holds the edit to that, sentence by sentence,
  against the snapshot taken when the pass was granted.

Stdlib only; the root's modules are not needed here.
"""
import hashlib
import json
import re

WHERE_SPOKEN = ("hook", "commentary", "payoff")      # = claims.WHERE_SPOKEN
WHERE_ON_SCREEN = "on_screen"                        # = claims.WHERE_ON_SCREEN
GIVEN_BY_CALLER = ("title", "description")           # = claims.GIVEN_BY_CALLER
GRAPHIC_PREFIX = "graphic:"                          # = claims.WHERE_GRAPHIC_PREFIX
GRAPHICS_FIELD = "graphics"
GRAPHIC_ID_KEY = "graphic_id"
CLAIMS_FIELD = "claims"

# ------------------------------------------------------------ pronoun lint
PRONOUN_CODE = "claim_subject_pronoun"
PRONOUN_FIX = ("name the subject in the sentence itself - the judge reads the claim alone, "
               "with no line before it: write the thing's name where the pronoun stands "
               "(\"NotebookLM began as Project Tailwind\", not \"It began as…\"), in the text "
               "and in the claim's `text`")
PRONOUN_RU = ("Утверждение начинается с местоимения - судья читает его отдельно и не знает, "
              "о ком речь; назовите предмет по имени.")
# A list numeral before the sentence ("Two. It runs…", "1) These…", "First, it…").
_NUMERAL_RE = re.compile(
    r"^\s*(?:\(?\d+\s*[.):]|(?:one|two|three|four|five|six|seven|eight|nine|ten|first|second|"
    r"third|fourth|fifth|next|last|finally)\s*[.:,!;\-—–]|[-–—•*]\s)\s*", re.I)
_OPEN_PUNCT = "\"'“”‘’«([ \t\n"
# The pronoun heads of CF-0807 (It / These / That / This / Those / They / Both
# / "Now it"), with a linking word before them ("And it", "But they") read the
# same way; a contraction ("It's", "They're") is its pronoun.
_HEAD_RE = re.compile(
    r"(?:(?:now|and|but|so|then|yet)\s*,?\s+)?(it|these|that|this|those|they|both)"
    r"(?:['’](?:s|re|ll|d|ve))?(?![\w'’-])", re.I)
_SENTENCE_END_RE = re.compile(r"[.!?…][\"'”’)\]]*\s+")


def _strip_head(text):
    """The text with its list numerals and opening quotes taken off."""
    t = (text or "").lstrip(_OPEN_PUNCT)
    while True:
        m = _NUMERAL_RE.match(t)
        if not m or not m.group(0).strip():
            return t
        t = t[m.end():].lstrip(_OPEN_PUNCT)


def pronoun_head(text):
    """The pronoun head a sentence opens on ("It", "Now it", "These"), or None."""
    m = _HEAD_RE.match(_strip_head(text))
    return m.group(0) if m else None


def _sentence_prefix(field_text, claim_text):
    """The words of the claim's sentence in its field that stand before the
    claim text ("It " for the claim "began as Project Tailwind" in "It began as
    Project Tailwind."); None when the claim is not found in the field."""
    if not (isinstance(field_text, str) and isinstance(claim_text, str) and claim_text.strip()):
        return None
    at = field_text.lower().find(claim_text.strip().lower())
    if at < 0:
        return None
    start = 0
    for m in _SENTENCE_END_RE.finditer(field_text, 0, at):
        start = m.end()
    return field_text[start:at]


def pronoun_violations(script, texts):
    """CF-0807: `[violation]` of the declared claims whose sentence opens on a
    pronoun - the claim text itself, or the words of its sentence before it.
    `texts` - {where: text} the viewer meets (claims.viewer_texts)."""
    out = []
    for claim in (script or {}).get(CLAIMS_FIELD) or []:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            continue
        text, where = claim["text"], claim.get("where")
        head = pronoun_head(text)
        if head is None:
            prefix = _sentence_prefix((texts or {}).get(where), text)
            if prefix and prefix.strip():
                m = _HEAD_RE.fullmatch(_strip_head(prefix).strip().rstrip(","))
                head = m.group(0) if m else None
        if head is None:
            continue
        out.append({"code": PRONOUN_CODE, "claim_id": claim.get("claim_id"),
                    "where": where, "text": text,
                    "detail": f"{where}: {text!r} opens on {head!r} - the judge reads the claim "
                              f"alone and cannot tell what {head.split()[-1]!r} is",
                    "fix": PRONOUN_FIX, "text_ru": PRONOUN_RU})
    return out


# ------------------------------------------------------------ deletion pass
DELETION_KEY = "deletion_pass"
DELETION_RULE = "CF-0807"
STATE_GRANTED = "granted"          # asked for, the snapshot taken
STATE_JUDGED = "judged"            # the deletion was checked and the script judged again
STATE_NOT_DELETION = "not_deletion_only"
# The strikes a deletion can answer: a claim the judge did not find in its
# quote, or a reveal too fresh (the sentence goes, the reveal with it).
DELETABLE_CODES = ("claim_not_entailed", "claim_not_enough", "reveal_too_fresh")


def _canon(obj):
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _ws(text):
    return " ".join(text.split()) if isinstance(text, str) else text


def sentences(text):
    """The sentences of a field, each as its words (a space is not an edit)."""
    if not isinstance(text, str) or not text.strip():
        return []
    out, start = [], 0
    for m in _SENTENCE_END_RE.finditer(text):
        out.append(text[start:m.end()])
        start = m.end()
    out.append(text[start:])
    return [_ws(s) for s in out if s.strip()]


def _loose(text):
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def _holds(sentence, claim_text):
    a, b = _loose(sentence), _loose(claim_text)
    return bool(a and b) and (b in a or a in b)


def _texts(script, extra=None):
    s = script or {}
    out = {w: s.get(w) for w in WHERE_SPOKEN if isinstance(s.get(w), str)}
    pf = s.get("production_fact")
    if isinstance(pf, dict) and isinstance(pf.get(WHERE_ON_SCREEN), str):
        out[WHERE_ON_SCREEN] = pf[WHERE_ON_SCREEN]
    for k, v in (extra or {}).items():
        if k in GIVEN_BY_CALLER and isinstance(v, str) and v.strip():
            out[k] = v
    return out


def _graphics(script):
    return {g.get(GRAPHIC_ID_KEY): _canon(g) for g in (script or {}).get(GRAPHICS_FIELD) or []
            if isinstance(g, dict) and g.get(GRAPHIC_ID_KEY)}


def _claims(script):
    return [{"claim_id": c.get("claim_id"), "hash": _canon(c)}
            for c in (script or {}).get(CLAIMS_FIELD) or [] if isinstance(c, dict)]


def grant(script, record, extra=None, fatal=()):
    """The deletion pass for this verdict, or None when it cannot be given:
    every violation is a strike of a declared claim that is not the video's own
    fact (`DELETABLE_CODES`), nothing undeclared, no mechanics, and each struck
    claim stands in a spoken section (where deleting its sentence leaves the
    section a sentence) or on a graphic of the script. The entry carries what
    to delete and the snapshot the next run holds the edit to."""
    mech = [v for v in (record.get("mechanics") or {}).get("violations") or []]
    if mech or record.get("refuse_now") or record.get("fact_struck"):
        return None
    violations = record.get("violations") or []
    if not violations or any(v.get("code") not in DELETABLE_CODES or v.get("fact_claim")
                             or not v.get("claim_id") for v in violations):
        return None
    texts = _texts(script, extra)
    graphics = _graphics(script)
    by_id = {c.get("claim_id"): c for c in (script or {}).get(CLAIMS_FIELD) or []
             if isinstance(c, dict)}
    remove, hit = [], {}
    for v in violations:
        claim = by_id.get(v["claim_id"]) or {}
        where, text = claim.get("where"), claim.get("text")
        if not isinstance(text, str):
            return None
        if where in WHERE_SPOKEN:
            sents = [s for s in sentences(texts.get(where)) if _holds(s, text)]
            if not sents:
                return None
            hit.setdefault(where, set()).update(sents)
        elif isinstance(where, str) and where.startswith(GRAPHIC_PREFIX):
            if where[len(GRAPHIC_PREFIX):] not in graphics:
                return None
        else:
            return None
        remove.append({"claim_id": v["claim_id"], "where": where, "text": text,
                       "code": v.get("code")})
    for where, sents in hit.items():
        if set(sentences(texts.get(where))) <= sents:
            return None                      # the section would be left with nothing
    pf = (script or {}).get("production_fact")
    return {"rule": DELETION_RULE, "state": STATE_GRANTED, "remove": remove,
            "sentences": {w: sorted(s) for w, s in hit.items()},
            "graphics": sorted({r["where"][len(GRAPHIC_PREFIX):] for r in remove
                                if r["where"].startswith(GRAPHIC_PREFIX)}),
            "base": {"texts": texts, "graphics": graphics, "claims": _claims(script),
                     "production_fact": _canon(pf)}}


def deletion_problems(script, entry, extra=None):
    """`(problems, removed)`: what the edit since the grant did beyond deleting
    (empty when it only deleted) and what it removed - {sentences: {where:
    [...]}, graphics: [...], claims: [...]}. A section is the old one with
    whole sentences taken out, a graphic is kept as it was or removed whole,
    a claim is kept as it was or removed, `production_fact` is untouched; a
    removed sentence holds a struck claim, a removed graphic carried one."""
    base = entry.get("base") or {}
    remove = entry.get("remove") or []
    problems = []
    removed = {"sentences": {}, "graphics": [], "claims": []}
    now = _texts(script, extra)
    old_texts = base.get("texts") or {}
    for where in sorted(set(old_texts) | set(now)):
        old, new = old_texts.get(where), now.get(where)
        if where in GIVEN_BY_CALLER and (old is None or new is None):
            continue                         # handed in on one run only - not the script's
        if old is None:
            problems.append(f"{where}: a section the script did not have when the pass was "
                            f"granted")
            continue
        old_s, new_s = sentences(old), sentences(new)
        j, gone = 0, []
        for s in old_s:
            if j < len(new_s) and new_s[j] == s:
                j += 1
            else:
                gone.append(s)
        if j < len(new_s):
            problems.append(f"{where}: {new_s[j]!r} is not a sentence of the text the pass was "
                            f"granted on - a deletion pass adds and rewords nothing")
            continue
        if old_s and not new_s:
            problems.append(f"{where}: emptied - the pass deletes sentences, not a section")
        struck_here = [r["text"] for r in remove if r.get("where") == where]
        for s in gone:
            if not any(_holds(s, t) for t in struck_here):
                problems.append(f"{where}: {s!r} was deleted and holds no struck claim")
        if gone:
            removed["sentences"][where] = gone
    old_g, new_g = base.get("graphics") or {}, _graphics(script)
    struck_g = set(entry.get("graphics") or [])
    for gid, h in new_g.items():
        if gid not in old_g:
            problems.append(f"graphic:{gid}: a graphic the pass was not granted on")
        elif old_g[gid] != h:
            problems.append(f"graphic:{gid}: changed - a graphic is kept as it was or removed "
                            f"whole")
    for gid in sorted(set(old_g) - set(new_g)):
        if gid not in struck_g:
            problems.append(f"graphic:{gid}: removed and carries no struck claim")
        removed["graphics"].append(gid)
    old_c = base.get("claims") or []
    hashes = {c["hash"] for c in old_c}
    now_c = _claims(script)
    for c in now_c:
        if c["hash"] not in hashes:
            problems.append(f"claims[] {c['claim_id']}: not an entry of the claims the pass was "
                            f"granted on (claims are kept as they were or removed)")
    kept = {c["hash"] for c in now_c}
    removed["claims"] = [c["claim_id"] for c in old_c if c["hash"] not in kept]
    if _canon((script or {}).get("production_fact")) != base.get("production_fact"):
        problems.append("production_fact: changed - the deletion pass does not touch the fact")
    return problems, removed


# ------------------------------------------------------------ phrase pass
# CF-0883: the Reel funnel of 2026-10-20..27 lost 4 topics as `claim_unsupported`
# whose second failure was only an undeclared statement on the hook or the
# payoff, every declared claim (8-16) following: "the number one opening is only
# the first answer" (Street Fighter 21.10 -003), "Everyone missed the part of
# Wildwood where ..." (25.10 -008), "Here's what nobody tells you about Tulsa
# King and the Stallone family." (27.10 -019). The topic died for one sentence
# of framing. After the one rewrite, when that is all that is left, the writer
# gets ONE more edit of those sentences only: say the sentence without the
# statement (the name and what the video will show, no "nobody" / "everyone"
# / "only" / "first"), or keep it and declare it with a verbatim quote. The rest
# of the script is held to the snapshot; the judge reads the whole text again
# and a failure refuses the topic. Nothing is let through unread.
PHRASE_KEY = "phrase_pass"
PHRASE_RULE = "CF-0883"
STATE_NOT_PHRASE = "not_phrase_only"
PHRASE_WHERES = ("hook", "payoff")
UNDECLARED_CODE = "claim_undeclared"
# CF-0886: the same window lost 4 more topics (Reel 27.10 -028 / -001 / -023,
# Tech 22.10 -033) to `claim_not_enough` on a hook or a payoff that is the only
# sentence of its section - "Six things about Tulsa King to know before you
# argue about the casting.", "Anthropic's funding came in Series E, F and G
# rounds." DELETE cannot take it (the section would be left empty), and the
# phrase pass took only `claim_undeclared`. Such a strike gets the same one
# edit of that sentence: said without what the quote does not state, in the
# quote's words, or without the statement. A strike of the video's own fact
# (-028: the payoff restated the 2012 announcement "long before Hader was
# cast") gets it only when the caller says the fact may take its one rewording
# (`fact_ok`: CF-0580's rewordable verdict, never reworded before) and the fact
# as shown on screen followed - the payoff's restatement overreached, not the
# fact. The judge reads the redone text again; nothing passes unread.
PHRASE_STRIKE_RULE = "CF-0886"
NOT_ENOUGH_CODE = "claim_not_enough"     # = claim_judge.FAIL_NOT_ENOUGH


def _fact_shown(record):
    """The video's own fact as shown (`production_fact.on_screen`) followed."""
    return any(isinstance(v, dict) and v.get("where") == WHERE_ON_SCREEN
               and v.get("state") == "supported" for v in record.get("verdicts") or [])


def phrase_grant(script, record, extra=None, fact_ok=False):
    """The phrase pass for this verdict, or None: every violation is an
    undeclared statement on the hook or the payoff (CF-0883) or a declared
    hook / payoff claim struck `claim_not_enough` whose sentences are all of
    their section (CF-0886: DELETE would empty it); nothing else struck, no
    mechanics, and each statement stands in a sentence of its section. A
    struck claim that is the video's own fact needs `fact_ok` and the fact
    on screen followed. The entry carries the sentences to redo and the
    snapshot of everything else."""
    mech = [v for v in (record.get("mechanics") or {}).get("violations") or []]
    if mech:
        return None
    violations = record.get("violations") or []
    if not violations:
        return None
    texts = _texts(script, extra)
    by_id = {c.get("claim_id"): c for c in (script or {}).get(CLAIMS_FIELD) or []
             if isinstance(c, dict) and c.get("claim_id")}
    hit, phrases, strikes, lone = {}, [], [], set()
    for v in violations:
        code = v.get("code")
        if code == UNDECLARED_CODE and v.get("where") in PHRASE_WHERES \
                and isinstance(v.get("text"), str):
            where, text = v["where"], v["text"]
            phrases.append({"where": where, "text": text})
        elif code == NOT_ENOUGH_CODE and v.get("claim_id") in by_id:
            claim = by_id[v["claim_id"]]
            where, text = claim.get("where"), claim.get("text")
            if where not in PHRASE_WHERES or not isinstance(text, str):
                return None
            if v.get("fact_claim") and not (fact_ok and _fact_shown(record)):
                return None
            strikes.append({"claim_id": v["claim_id"], "where": where, "text": text,
                            "code": code, "fact_claim": bool(v.get("fact_claim")),
                            "quotes": [{"source": q.get("source"), "quote": q.get("quote")}
                                       for q in claim.get("support") or []
                                       if isinstance(q, dict) and q.get("quote")]})
            lone.add(where)
        else:
            return None
        sents = [s for s in sentences(texts.get(where)) if _holds(s, text)]
        if not sents:
            return None
        hit.setdefault(where, set()).update(sents)
    for where in lone:
        if not set(sentences(texts.get(where))) <= hit[where]:
            return None              # a sentence of the section stays: DELETE's, not this
    struck_ids = {s.get("claim_id") for s in record.get("struck") or [] if isinstance(s, dict)}
    if not struck_ids <= {s["claim_id"] for s in strikes}:
        return None
    if record.get("fact_struck") and not (fact_ok and any(s["fact_claim"] for s in strikes)):
        return None
    if record.get("refuse_now") and not record.get("fact_struck"):
        return None
    pf = (script or {}).get("production_fact")
    claims = [{"claim_id": c.get("claim_id"), "where": c.get("where"), "hash": _canon(c)}
              for c in (script or {}).get(CLAIMS_FIELD) or [] if isinstance(c, dict)]
    entry = {"rule": PHRASE_RULE, "state": STATE_GRANTED, "phrases": phrases,
             "sentences": {w: sorted(s) for w, s in hit.items()},
             "base": {"texts": texts, "graphics": _graphics(script), "claims": claims,
                      "production_fact": _canon(pf)}}
    if strikes:
        entry["strikes"] = strikes
        entry["strike_rule"] = PHRASE_STRIKE_RULE
    return entry


def phrase_problems(script, entry, extra=None):
    """`(problems, changed)`: what the edit since the grant did beyond the
    granted sentences (empty when it kept to them) and what it changed -
    {sentences: {where: {"was": [...], "now": [...]}}}. Every other sentence of
    every section is kept in order, a granted sentence is redone or removed, a
    section is not emptied, graphics and `production_fact` are untouched, a
    claim of another section is kept as it was (a claim of the redone sections
    may change: it is judged again)."""
    base = entry.get("base") or {}
    granted = {w: set(s) for w, s in (entry.get("sentences") or {}).items()}
    problems, changed = [], {"sentences": {}}
    now = _texts(script, extra)
    old_texts = base.get("texts") or {}
    for where in sorted(set(old_texts) | set(now)):
        old, new = old_texts.get(where), now.get(where)
        if where in GIVEN_BY_CALLER and (old is None or new is None):
            continue
        if old is None:
            problems.append(f"{where}: a section the script did not have when the pass was "
                            f"granted")
            continue
        old_s, new_s = sentences(old), sentences(new)
        if where not in granted:
            if old_s != new_s:
                problems.append(f"{where}: changed - the phrase pass redoes only the sentences "
                                f"it names")
            continue
        if not new_s:
            problems.append(f"{where}: emptied - the pass redoes a sentence, it does not "
                            f"remove the section")
            continue
        kept = [s for s in old_s if s not in granted[where]]
        j = 0
        for s in new_s:
            if j < len(kept) and s == kept[j]:
                j += 1
        if j < len(kept):
            problems.append(f"{where}: {kept[j]!r} is not kept as it was - the phrase pass "
                            f"redoes only {sorted(granted[where])!r}")
            continue
        extra_s = [s for s in new_s if s not in kept]
        if len(extra_s) > 2 * len(granted[where]):
            problems.append(f"{where}: {len(extra_s)} new sentence(s) for "
                            f"{len(granted[where])} granted - the pass redoes the sentence, "
                            f"it does not write new ones")
        changed["sentences"][where] = {"was": sorted(granted[where]), "now": extra_s}
    old_g, new_g = base.get("graphics") or {}, _graphics(script)
    if old_g != new_g:
        problems.append("graphics: changed - the phrase pass does not touch the graphics")
    if _canon((script or {}).get("production_fact")) != base.get("production_fact"):
        problems.append("production_fact: changed - the phrase pass does not touch the fact")
    redone = set(granted)
    old_other = sorted(c["hash"] for c in base.get("claims") or []
                       if c.get("where") not in redone)
    now_other = sorted(_canon(c) for c in (script or {}).get(CLAIMS_FIELD) or []
                       if isinstance(c, dict) and c.get("where") not in redone)
    if old_other != now_other:
        problems.append("claims[]: a claim outside " + "/".join(sorted(redone)) + " changed, "
                        "was added or removed - only the redone sections' claims may change")
    return problems, changed
