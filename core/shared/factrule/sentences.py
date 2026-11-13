"""CF-0737: where a sentence ends, and a fact that was cut short - one reading
for the whole factory.

`example-film/2026-10-13T1411Z`, Justice League: the article's sentence «In
February 2007, it was announced that Example Studios had hired ...» was
split at «Bros.», and the hunter carried «In February 2007, it was announced
that Example Studios» as a passing fact. The same cut left «Delver is a 2026
satirical black comedy film directed by Alejandro G.» (1313Z, at an initial)
and «... merged in April 2022 to become Example Studios» (1824Z). A full stop
after an abbreviation or an initial is not the end of the sentence, and a fact
that still ends like a cut one is refused.

The rules are the Trend Hunter's (`agents/trend-hunter/scripts/_sentences.py`,
where the bug was found), moved here so that every reader of a sentence asks
the same question:
  - `fact_rule.check_candidate` refuses a cut fact (`cut_short`) - the hunter
    at selection and the researcher re-running the check both;
  - `scale_support` (a number and its unit in one sentence of the passage),
    `claim_judge.sentences` (the claim and its context, CF-0728) and
    `api_demo.shown_answer` (where a long answer may be cut) split with
    `split_at` and their own boundary.

`fact_rule.py` loads this file by path from its own directory, so a
repository that keeps a copy of the rule keeps a copy of this file beside it
(`tests/test_fact_rule_copies.py`, COPIES).

Stdlib only, no I/O, imports nothing of the checkout: loadable by path from
any repository.
"""
import re

# A title or a short form a name or a number follows - never the last word of
# a sentence («Dr.», «St.», «No.», «vs.», «Oct.»).
TITLES = ("Mr", "Mrs", "Ms", "Mx", "Dr", "Prof", "St", "Mt", "Ft", "Gen", "Gov", "Sen",
          "Rep", "Lt", "Col", "Capt", "Cmdr", "Sgt", "Rev", "Hon", "Pres", "No", "Nos",
          "Vol", "Vols", "Ch", "Pt", "Fig", "Op", "approx", "vs", "v",
          "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec")
# The end of a company's or a person's name - «Example Studios», «Robert
# Downey Jr. as», «Discovery, Inc. and». Mid-sentence much more often than at
# its end, so the splitter goes on after it; a sentence that does end on one
# is kept whole by `cut_short` unless its "that" clause is left without a verb.
NAME_ENDS = ("Bros", "Inc", "Co", "Corp", "Cos", "Ltd", "Plc", "LLC", "Jr", "Sr",
             "Assn", "Dept", "Univ", "Ave", "Blvd", "etc", "al")

_TITLE_END_RE = re.compile(r"(?:^|[\s(\"'“‘])(?:" + "|".join(TITLES) + r")\.$")
_NAME_END_RE = re.compile(r"(?:^|[\s(\"'“‘,])(?:" + "|".join(NAME_ENDS) + r")\.$")
# «U.S.», «U.K.», «D.C.», «a.k.a.», «e.g.», «i.e.»
_DOTTED_RE = re.compile(r"(?:^|[\s(\"'“‘])(?:[A-Za-z]\.){2,}$")
# «Alejandro G.», «J. K.» - one capital letter; «I» is the Roman one
# («World War I.»), which does end sentences.
_INITIAL_RE = re.compile(r"(?:^|[\s(\"'“‘])[A-HJ-Z]\.$")
# A word a letter names a kind of - «Generation Z.», «Plan B.», «Vitamin C.»
# end a sentence; «Alejandro G.» and «Samuel L.» do not (`cut_short`).
LETTER_NOUNS = ("Generation", "Plan", "Vitamin", "Type", "Model", "Class", "Grade",
                "Section", "Part", "Phase", "Area", "Zone", "Wing", "Block", "Building",
                "Gate", "Group", "Team", "Unit", "Channel", "Version", "Exhibit",
                "Appendix", "Category", "Level", "Stage", "Series", "Division", "Pool",
                "Studio", "Lot", "Hall", "Floor", "Room", "Row", "Track", "Side",
                "Book", "Volume", "Act", "Scene", "Disc", "Format", "Option", "Route")
_LETTER_NOUN_RE = re.compile(r"\b(?:" + "|".join(LETTER_NOUNS) + r")\s+[A-Z]\.$", re.I)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_THAT_RE = re.compile(r"\bthat\b")


def abbreviation_end(chunk):
    """True when the full stop that ends `chunk` belongs to an abbreviation or
    an initial - the sentence goes on after it."""
    chunk = (chunk or "").rstrip()
    return bool(_TITLE_END_RE.search(chunk) or _NAME_END_RE.search(chunk)
                or _DOTTED_RE.search(chunk) or _INITIAL_RE.search(chunk))


# The gap between two sentences: a stop, then a space, then anything but a
# word in lower case or a number («... in 2007. 15 films» stays one).
_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[^a-z0-9])")
# Quotes and brackets that close a sentence after its stop («... said "no."»).
_CLOSERS = "\"'\u201d\u2019)]"


def split_at(text, boundary):
    """`text` cut at every match of `boundary` - a regex whose match is the
    gap between two sentences, starting right after the stop (and its closing
    quotes) - except where the stop belongs to an abbreviation or an initial
    (`abbreviation_end`): the sentence goes on there. Every piece is kept as
    it stands, empty ones included, the way `re.split` keeps them."""
    text = text or ""
    out, start = [], 0
    for m in boundary.finditer(text):
        chunk = text[start:m.start()]
        if abbreviation_end(chunk.rstrip().rstrip(_CLOSERS)):
            continue
        out.append(chunk)
        start = m.end()
    out.append(text[start:])
    return out


def split_sentences(text):
    """A text's sentences, one per line or full stop - never at an
    abbreviation's or an initial's stop (`abbreviation_end`)."""
    out = []
    for line in re.split(r"\n+", text or ""):
        out.extend(split_at(line, _BOUNDARY_RE))
    return [s for s in out if s.strip()]


def cut_short(text):
    """The reason a fact's text reads as a sentence cut short, or None.

    Two shapes, both seen on a passing fact (CF-0737):
      - it ends on a title or an initial («... directed by Alejandro G.»), a
        word a name always follows;
      - its last "that" clause has no word in lower case after it - no verb
        («it was announced that Example Studios»), the clause stops at a name.
    A sentence that ends on a company's name in a clause of its own («...
    distributed by Example Studios») is whole and is not refused."""
    text = (text or "").strip().rstrip("\"'”’)]").rstrip()
    if not text:
        return None
    if _TITLE_END_RE.search(text) or (_INITIAL_RE.search(text)
                                       and not _LETTER_NOUN_RE.search(text)):
        return "ends on an abbreviation or an initial a name follows"
    thats = list(_THAT_RE.finditer(text))
    if thats:
        tail = text[thats[-1].end():]
        words = _WORD_RE.findall(tail)
        if words and not any(w[:1].islower() for w in words):
            return "its \"that\" clause has no verb - the sentence stops at a name"
    return None
