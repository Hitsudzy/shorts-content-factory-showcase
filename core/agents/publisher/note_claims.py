#!/usr/bin/env python3
"""CF-0555: the publication's title and description are claims too, and the
note shows the user a quote and a link for every claim the video makes.

The grill of 2026-10-05 (CF-0546). Q4: what the viewer meets is all checked -
the narrator, the on-screen words, **and the title and the description of the
upload**; East of Eden's description went out with «months before anyone
outside the production knew the shape of the show» and «rather than a
courtroom drama» in it (cleaned by hand, commit 64f55f2 of the root's main),
no source said either. Q5: the machine checks everything; the user does not
have to - the note `publish/<channel>/<day>/<slug>.md` carries, for each key
claim, the quote it stands on and a link to it (the Wikipedia revision, the
news item's URL, the shot).

What this module does with one note:

1. **Reads the note** (`publish_note.py`): the title without its hashtags
   (`#shorts`) and the description's first block - the prose about the video;
   the source line and the hashtags (docs/publisher-metadata-rules.md, blocks
   2 and 3) are not claims about the story.
2. **Finds the video's script** - the batch on the note's `Батч
   \\`pipeline/<channel>/<batch>\\`` line and the script on its `сценарий
   \\`<id>\\`` (or `--batch` / `--script-id`).
3. **Judges the title and the description with the video** - CF-0553's
   `claim_judge.judge_script` with `extra_texts={title, description}`: the
   independent reader lists every claim of the finished text, the title and
   the description included (Q13). A listed claim of the title or the
   description is **declared on behalf of the note** from the script's own
   claims whose words cover it (`claim_judge.coverage`, the same 0.6 / 0.75
   as the reader's match) - it inherits their *quotes* only: a shot backs
   spoken words under it, never a title (Q8, `shot_not_spoken`). Then the
   judge sees each such claim in the note's own words against that footing
   (Q6) - "Built Around Florence Pugh" is a stronger sentence than the
   script's, and it is the title's sentence that is judged. A claim of the
   note no script claim covers stays undeclared - `claim_undeclared`, no
   footing.
4. **One edit** (Q3). Nothing that fails is let through silently. A failing
   span of the description is struck out of it - the clause, when a comma /
   dash / semicolon sets it off, else its whole sentence; never
   reworded, never hedged - and the note is judged again once. A failing
   title is not cut (a title with a hole is no title): the note is refused
   with the claim named, the writer of the note rewrites it. The video's own
   claims failing (narrator, on-screen) are the video's problem, not the
   note's: refused, nothing edited - the video is rebuilt, not its note.
5. **The block «Утверждения»** (`--write`, only when everything passed):
   every claim that follows - narrator, on-screen, title, description - with
   its quote and a link: `https://en.wikipedia.org/w/index.php?oldid=<rev>`
   for a Wikipedia piece (the revision the text was read from), the item's
   URL for a news summary, the episode page and the moment it was read for
   a TVmaze episode description (CF-0636), the page and the moment it was read
   for a company's own page (`vendor_page`, CF-0771), the shot id and its description
   for a shot; a
   reveal says how long its text had stood or which news item confirmed it
   (CF-0554). What the edit struck is named in the block. The block's marker
   carries the fingerprint of the title and the whole description as they
   go to YouTube; `upload.py` refuses a note without the block or with a
   stale one (the title or the description changed after the check).

The model is asked through CF-0553's answer command and cache (`<batch>/
work/claim-judge-cache/`, so the script's own claims judged at the stage
are answered from it): one reader call for the text with the note in it,
one judge call per claim of the note.

Command line:

    python3 agents/publisher/note_claims.py publish/<channel>/<day>/<slug>.md
        [--batch DIR] [--script-id ID] [--root DIR] [--write] [--no-edit]
        [--answer-cmd CMD] [--model sonnet] [--timeout S] [--jobs N]
        [--cache-dir DIR] [--now ISO] [--json]
    python3 agents/publisher/note_claims.py <note> --check-block   # the block is there and fresh

exit 0 the note passes (and with --write the block is written), 1 it does
not (the reason and the fix printed), 3 the question could not be put (no
batch / script, or the model could not be asked - `NOT_LOGGED_IN`).
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import publish_note                                             # noqa: E402

RULE = "CF-0555"
SECTION = "Утверждения"
MARKER = "note_claims"
MARK_RE = re.compile(r"<!--\s*" + MARKER + r"\s+(\{.*?\})\s*-->")
BATCH_RE = re.compile(r"Батч\s+`pipeline/([^/`]+)/([^/`]+)/?`")
SCRIPT_RE = re.compile(r"сценарий\s+`([^`]+)`")
SOURCE_LINE_RE = re.compile(r"^\s*The fact in this video comes from\b", re.I)
URL_LINE_RE = re.compile(r"https?://\S", re.I)
HASHTAG_LINE_RE = re.compile(r"^\s*(#[^\s#]+\s*)+$")
HASHTAG_RE = re.compile(r"(?<!\S)#[^\s#]+")
CLAUSE_DELIM_RE = re.compile(r"\s*(,|;|—|–|\s-)\s*$")
SENTENCE_END_RE = re.compile(r"[.!?…](?=[\"'”’)\]]*(\s|$))")

TITLE, DESCRIPTION = "title", "description"
NOTE_FIELDS = (TITLE, DESCRIPTION)
WHERE_RU = {"hook": "диктор", "commentary": "диктор", "payoff": "диктор",
            "on_screen": "надпись", TITLE: "название", DESCRIPTION: "описание"}

FAIL_TITLE = "title_claim_failed"
FAIL_DESCRIPTION_EMPTY = "description_struck_empty"
FAIL_VIDEO = "video_claims_failed"
FAIL_PENDING = "claim_pending"
FAIL_SECOND = "description_failed_after_edit"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CJ = None


def judge_module():
    """`shared/factrule/claim_judge.py`, loaded by path once."""
    global _CJ
    if _CJ is None:
        _CJ = _load("claim_judge_note_claims", ROOT / "shared" / "factrule" / "claim_judge.py")
    return _CJ


class NoteClaimsError(Exception):
    """The note cannot be checked at all (no batch, no script)."""


# ------------------------------------------------------------------ the note
def note_texts(text):
    """`{title, description}` as the judge reads them: the title without its
    hashtags, the description's first block (up to the source line, a line
    carrying a URL - a channel's own source line, CF-0017 - or a line of
    hashtags)."""
    title, description = publish_note.title_and_description(publish_note.sections(text))
    title = re.sub(r"\s+", " ", HASHTAG_RE.sub("", title)).strip()
    prose = []
    for line in description.splitlines():
        if SOURCE_LINE_RE.match(line) or URL_LINE_RE.search(line) or HASHTAG_LINE_RE.match(line):
            break
        prose.append(line)
    return {TITLE: title, DESCRIPTION: "\n".join(prose).strip()}


CARD_MARK_RE = re.compile(r"<!--\s*publish_card\s+(\{.*?\})\s*-->", re.S)


def affiliate_labels(text, given=None):
    """CF-0593: the words of the affiliate link line the card put into the
    description's second block (the line without its URL) - the claim check
    reads them with the first block, so no claim rides in beside a link.
    `given`: the labels the card builder hands in (its card section is not
    written yet); else the card's own marker (`publish_card` -> `affiliate`,
    placed). Only a label the description really carries counts."""
    if given is None:
        given = []
        m = CARD_MARK_RE.search(text)
        try:
            aff = (json.loads(m.group(1)) if m else {}).get("affiliate") or {}
        except ValueError:
            aff = {}
        if isinstance(aff, dict) and aff.get("placed") and isinstance(aff.get("label"), str):
            given = [aff["label"]]
    _, description = publish_note.title_and_description(publish_note.sections(text))
    return [g for g in given if isinstance(g, str) and g.strip() and g in description]


def judged_texts(texts, labels):
    """What the judge reads: the note's texts with the affiliate labels
    after the description's prose (the edit strikes in the prose only)."""
    if not labels:
        return texts
    return dict(texts, description="\n".join([texts.get(DESCRIPTION) or ""] + list(labels))
                .strip())


def fingerprint(text):
    """sha256 (16 hex) of the title and the whole description as they go to
    YouTube - any change of either makes the block stale."""
    title, description = publish_note.title_and_description(publish_note.sections(text))
    body = json.dumps([title, description], ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def block_of(text):
    """The marker of the note's block «Утверждения» (dict) or None."""
    body = publish_note.sections(text).get(SECTION)
    if body is None:
        return None
    m = MARK_RE.search(body)
    if not m:
        return {}
    try:
        mark = json.loads(m.group(1))
    except ValueError:
        return {}
    return mark if isinstance(mark, dict) else {}


def check_block(text):
    """None when the note carries a block «Утверждения» written by this
    module for exactly its current title and description; else why not."""
    mark = block_of(text)
    if mark is None:
        return (f"the note has no `## {SECTION}` - its title and description were not "
                f"checked against the sources ({RULE}): run "
                f"`python3 agents/publisher/note_claims.py <note> --write`")
    if not mark or mark.get("rule") != RULE or not mark.get("fingerprint"):
        return f"`## {SECTION}` has no readable `<!-- {MARKER} {{...}} -->` marker - rerun the check"
    if mark["fingerprint"] != fingerprint(text):
        return (f"the title or the description changed after the claim check "
                f"({mark.get('checked_at') or '?'}) - rerun "
                f"`python3 agents/publisher/note_claims.py <note> --write`")
    return None


def data_root(note_path, root=None):
    if root:
        return Path(root)
    for p in Path(note_path).resolve().parents:
        if (p / "pipeline").is_dir() and (p / "publish").is_dir():
            return p
    return ROOT


def batch_and_script(text, note_path, batch=None, script_id=None, root=None):
    """`(batch_dir, script_id)` the note names (or the arguments)."""
    if batch is None:
        m = BATCH_RE.search(text)
        if not m:
            raise NoteClaimsError(f"{note_path}: the note names no batch "
                                  f"(`Батч \\`pipeline/<канал>/<батч>\\``) - pass --batch")
        batch = data_root(note_path, root) / "pipeline" / m.group(1) / m.group(2)
    batch = Path(batch)
    if not batch.is_dir():
        raise NoteClaimsError(f"{batch}: no such batch")
    if script_id is None:
        m = SCRIPT_RE.search(text)
        script_id = m.group(1) if m else None
    return batch, script_id


def script_of(batch_dir, script_id, slug=None):
    cj = judge_module()
    data = cj.claims._read(Path(batch_dir) / "03-content-researcher.json")
    scripts = [s for s in (data or {}).get("scripts") or [] if isinstance(s, dict)]
    if script_id:
        hit = [s for s in scripts if s.get("script_id") == script_id]
    else:
        hit = [s for s in scripts if re.sub(r"[^a-z0-9]+", "-", str(
            ((s.get("title_ref") or {}).get("name") or "")).lower()).strip("-") == slug]
    if len(hit) != 1:
        raise NoteClaimsError(f"{batch_dir}: no single script {script_id or slug!r} in 03 - "
                              f"pass --script-id")
    return hit[0]


# ------------------------------------------------------------- the judgement
def _declared(script):
    c = (script or {}).get(judge_module().claims.CLAIMS_FIELD)
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []


def _quotes(claim):
    return [s for s in claim.get("support") or [] if isinstance(s, dict)
            and isinstance(s.get("quote"), str) and s["quote"].strip()]


def claim_words(claim):
    """CF-0728: the words a claim of the script speaks for - its own and the
    words of the quotes it stands on. The draft is told to say what the
    narration *and the source's sentence* say (`publish_card.draft_request`),
    so a description that restates the source's sentence ("was awarded ...
    as an inspiring ambassador") is the video's claim in its footing's
    words, not a claim of its own."""
    cj = judge_module()
    out = set(cj._content(claim.get("text") or ""))
    for s in _quotes(claim):
        out |= set(cj._content(s["quote"]))
    return out


def derive_note_claims(extracted, declared):
    """Claims of the title / description declared on the note's behalf: for
    each listed claim of the note no declared claim of its own field covers,
    the script's claims whose words (CF-0728: their text and their quotes,
    `claim_words`) cover it - one at ≥ MATCH_MIN, or several together at ≥
    UNION_MIN. The claims are taken one at a time, the one that brings the
    most of the words still not covered first, until none brings any
    (CF-0728: "The 2021 Award Before Her Spaceflight" was covered at 2/3 by
    the award's claim alone and judged without the flight's quote - the order
    could not be judged; now the claim that brings "spaceflight" is in too). Their quotes are the footing - only quotes the video's own
    claims stand on, nothing new. A listed claim covered by none, or only by
    shots, gets no claim - it stays undeclared."""
    cj = judge_module()
    story = [c for c in declared if c.get("where") not in NOTE_FIELDS
             and isinstance(c.get("text"), str)]
    words = [claim_words(c) for c in story]
    out, n = [], {}
    for item in extracted:
        if item.get("where") not in NOTE_FIELDS or item.get("matched"):
            continue
        want = set(cj._content(item["text"]))
        if not want:
            continue
        picked, covered = [], set()
        while True:
            gain, best = max(((len((w & want) - covered), -i) for i, w in enumerate(words)
                              if i not in picked), default=(0, 0))
            if not gain:
                break
            picked.append(-best)
            covered |= words[-best] & want
        if not picked or (len(covered) / len(want) < cj.UNION_MIN
                          and not any(len(words[i] & want) / len(want) >= cj.MATCH_MIN
                                      for i in picked)):
            continue
        hits = [story[i] for i in picked]
        support, seen = [], set()
        for c in hits:
            for s in _quotes(c):
                key = (s.get("source"), s.get("quote"))
                if key not in seen:
                    seen.add(key)
                    support.append({"source": s.get("source"), "quote": s.get("quote")})
        if not support:
            continue
        n[item["where"]] = n.get(item["where"], 0) + 1
        out.append({"claim_id": f"note-{item['where']}-{n[item['where']]}",
                    "where": item["where"], "text": item["text"], "support": support,
                    "from": [c.get("claim_id") for c in hits]})
    return out


def _where_of(report):
    """{claim_id: where} over the verdict's declared claims."""
    out = {}
    for r in (report.get("mechanics") or {}).get("results") or []:
        out[r.get("claim_id")] = r.get("where")
    for v in report.get("verdicts") or []:
        out.setdefault(v.get("claim_id"), v.get("where"))
    return out


def split_problems(report):
    """`(video, note)` - the verdict's problems, by whose words they are in."""
    where = _where_of(report)
    video, note = [], []
    mech = report.get("mechanics") or {}
    items = [dict(v, layer="mechanics") for v in mech.get("violations") or []] + \
            [dict(v, layer="judge") for v in report.get("violations") or []] + \
            [dict(p, layer="pending", fix="the claim is not checked yet - nothing is published "
                                          "on an unchecked claim")
             for p in mech.get("pending") or []]
    for v in items:
        w = v.get("where") or where.get(v.get("claim_id"))
        v["where"] = w
        if v.get("text") is None and v.get("claim_id") in where:
            v["text"] = next((r.get("text") for r in report.get("verdicts") or []
                              if r.get("claim_id") == v.get("claim_id")), None)
        (note if w in NOTE_FIELDS else video).append(v)
    return video, note


def judge_with_note(script, texts, topic, pool, plan, asker, jobs=None, revisions=None,
                    now=None):
    """The verdict on the video with the note's title and description in it:
    the reader's pass, the note's claims declared from the script's, the
    verdict again (the reader and the script's claims answered from the
    cache). `(report, derived)`."""
    cj = judge_module()
    extra = {k: v for k, v in texts.items() if v}
    jobs = jobs or cj.DEFAULT_JOBS
    first = cj.judge_script(script, topic=topic, pool=pool, plan=plan, extra_texts=extra,
                            asker=asker, jobs=jobs, revisions=revisions, now=now)
    derived = derive_note_claims(first.get("extracted") or [], _declared(script))
    if not derived:
        return first, []
    s2 = dict(script)
    s2[cj.claims.CLAIMS_FIELD] = _declared(script) + [
        {k: v for k, v in d.items() if k != "from"} for d in derived]
    second = cj.judge_script(s2, topic=topic, pool=pool, plan=plan, extra_texts=extra,
                             asker=asker, jobs=jobs, revisions=revisions, now=now)
    return second, derived


# ----------------------------------------------------------------- the edit
def _span_at(prose, span):
    """(start, end) of the reader's span in the prose: as written, else its
    words in order with anything but letters / digits between them."""
    at = prose.find(span)
    if at >= 0:
        return at, at + len(span)
    low = prose.casefold().find(span.casefold())
    if low >= 0:
        return low, low + len(span)
    words = re.findall(r"[\w']+", span)
    if not words:
        return None
    pat = r"\W+".join(re.escape(w).replace("'", "['’]") for w in words)
    m = re.search(pat, prose, re.I)
    return (m.start(), m.end()) if m else None


def _sentence_bounds(prose, start, end):
    s = 0
    for m in re.finditer(r"(?<=[.!?…])[\"'”’)\]]*\s+|\n+", prose[:start]):
        s = m.end()
    m = SENTENCE_END_RE.search(prose, end)
    e = m.end() if m else len(prose)
    nl = prose.find("\n", end)
    if 0 <= nl < e:
        e = nl
    return s, e


def strike(prose, span):
    """The prose with `span` struck out: the clause from the delimiter that
    sets it off (`, ; — –`) to the span's end, or - when no delimiter sets
    it off (it starts its sentence, follows a colon that introduces it, or
    sits inside one clause) - its whole sentence. None when the span is not in the prose."""
    at = _span_at(prose, span)
    if at is None:
        return None
    start, end = at
    s, e = _sentence_bounds(prose, start, end)
    before = prose[s:start]
    m = CLAUSE_DELIM_RE.search(before)
    if before.strip() and m:
        cut_from = s + m.start()
        rest = prose[end:]
        out = prose[:cut_from] + rest
    else:
        out = prose[:s] + prose[e:].lstrip(" ")
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
    out = re.sub(r"([,;:—–])\s*([.!?])", r"\2", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def strike_all(prose, spans):
    """`(prose, struck[])` with every span struck in turn (a span inside an
    already struck sentence is gone with it)."""
    struck = []
    for span in spans:
        if not span or _span_at(prose, span) is None:
            continue
        new = strike(prose, span)
        if new is not None and new != prose:
            prose = new
            struck.append(span)
    return prose, struck


def note_spans(problems, prose):
    """`[(span, code)]` of the description the edit strikes: the reader's
    span of an undeclared claim, the claim's text of a struck one, the
    sentence of a hedge."""
    cj = judge_module()
    out = []
    for v in problems:
        if v.get("where") != DESCRIPTION:
            continue
        if v.get("code") == cj.claims.FAIL_HEDGED:
            for sentence in cj.claims._sentences(prose):
                if cj.claims.hedges_in(sentence):
                    out.append((sentence, v.get("code")))
        elif v.get("text"):
            out.append((v["text"], v.get("code")))
    seen, uniq = set(), []
    for span, code in out:
        if span not in seen:
            seen.add(span)
            uniq.append((span, code))
    return uniq


# ------------------------------------------------------------------- checking
def check_note(note_path, asker, batch=None, script_id=None, root=None, edit=True,
               jobs=None, revisions=None, now=None, affiliate=None):
    """The verdict on one note: `{rule, action, note, batch, script_id, texts,
    problems[{code, where, text, detail, fix}], struck[], edited, text, lines[],
    report}` - `text` the note as it would be written (the edit applied),
    `lines` what the block shows. `affiliate`: the affiliate link labels
    (CF-0593, `affiliate_labels`) - None reads them off the card's marker.
    Raises NoteClaimsError / CannotAsk."""
    cj = judge_module()
    note_path = Path(note_path)
    text = note_path.read_text(encoding="utf-8")
    batch_dir, sid = batch_and_script(text, note_path, batch, script_id, root)
    script = script_of(batch_dir, sid, note_path.stem)
    topic = cj.claims.topics_of(batch_dir).get(script.get("topic_id"))
    pool = cj.claims.pool_of(script, batch_dir, Path(root) if root else data_root(note_path))
    plan = cj.claims.plan_of(script, batch_dir)
    texts = note_texts(text)
    labels = affiliate_labels(text, affiliate)
    out = {"rule": RULE, "action": cj.ACTION_FAIL, "note": str(note_path),
           "batch": str(batch_dir), "script_id": script.get("script_id"), "texts": texts,
           "problems": [], "struck": [], "edited": False, "text": text, "lines": [],
           "affiliate_labels": labels}

    def judge(t):
        return judge_with_note(script, judged_texts(t, labels), topic, pool, plan, asker, jobs,
                               revisions, now)

    report, derived = judge(texts)
    video, note = split_problems(report)
    if not video and note and edit and not any(v["where"] == TITLE for v in note):
        spans = note_spans(note, texts[DESCRIPTION])
        codes = dict(spans)
        prose, struck = strike_all(texts[DESCRIPTION], [span for span, _ in spans])
        if struck:
            out["struck"] = [{"text": s, "code": codes.get(s)} for s in struck]
            if not prose:
                out["problems"] = [{"code": FAIL_DESCRIPTION_EMPTY, "where": DESCRIPTION,
                                    "text": texts[DESCRIPTION],
                                    "detail": "nothing of the description's first block "
                                              "is left once its unsupported claims are out",
                                    "fix": "write the description again from the script's "
                                           "supported claims and rerun"}]
                out["report"] = report
                return out
            texts2 = dict(texts, description=prose)
            report, derived = judge(texts2)
            video, note2 = split_problems(report)
            for v in note2:
                v["after_edit"] = True
            note = note2
            texts = texts2
            out["texts"] = texts
            out["edited"] = True
            out["text"] = replace_prose(text, out["struck"] and prose)
    out["report"] = report
    out["derived"] = derived
    problems = []
    for v in video:
        problems.append(dict(_problem(v), video=True))
    for v in note:
        p = _problem(v)
        if v.get("where") == TITLE:
            p["fix"] = ("the title is not cut: write it again so it says only what a claim of "
                        "the script with a quote says, and rerun - " + (p.get("fix") or ""))
        elif v.get("after_edit"):
            p["fix"] = ("the one edit is spent: rewrite the description by hand from the "
                        "script's supported claims and rerun")
        problems.append(p)
    out["problems"] = problems
    if not problems:
        out["action"] = cj.ACTION_PASS
        # the batch is pipeline/<channel>/<batch>: the channel names its outlets
        out["lines"] = block_lines(report, topic, outlet_names(Path(batch_dir).parent.name))
    return out


def _problem(v):
    return {"code": v.get("code"), "where": v.get("where"), "claim_id": v.get("claim_id"),
            "text": v.get("text"), "detail": v.get("detail"), "fix": v.get("fix")}


def replace_prose(text, new_prose):
    """The note with its description's first block replaced."""
    old = note_texts(text)[DESCRIPTION]
    sec = re.search(r"^##\s+Описание\s*$", text, re.M)
    if not new_prose or not old or not sec:
        return text
    at = text.find(old, sec.end())
    return text if at < 0 else text[:at] + new_prose + text[at + len(old):]


# ------------------------------------------------------------------ the block
def _wiki_link(url, revision_id):
    if not url or not revision_id:
        return url
    parts = urlsplit(url)
    if not parts.netloc.endswith("wikipedia.org"):
        return url
    return f"{parts.scheme or 'https'}://{parts.netloc}/w/index.php?oldid={revision_id}"


# CF-0771: a company's own page read by Trend Hunter when the topic has no
# Wikipedia article (`agents/trend-hunter`, piece `vendor_page:<outlet>:<n>`:
# `publication` = the page's og:site_name, `outlet` = the fact-sources row id,
# no revision, `fetched_at` = the batch's time). It is credited to the company,
# never to Wikipedia - the old fall-through named it «Википедия, <title>».
VENDOR_KIND = "vendor_page"
OUTLET_NAME_MAX = 32


def _outlet_name(row):
    """A fact-sources row's own name: `name` when the row has one, else, for a
    company's row (`kind: vendor`), the head of its `note` ("Apple - newsroom
    ..." -> "Apple") when that head is a short name, not a description of a
    group ("The chipmakers' own pages" - the host names those)."""
    if isinstance(row.get("name"), str) and row["name"].strip():
        return row["name"].strip()
    if row.get("kind") != "vendor":
        return None
    note = str(row.get("note") or "")
    head = note.split(" - ", 1)[0].strip()
    if " - " in note and head and len(head) <= OUTLET_NAME_MAX \
            and not any(c in head for c in "'.;:()"):
        return head
    return None


def outlet_names(channel, root=None):
    """{outlet id: name} of `channels/<channel>/fact-sources.json`; {} when the
    channel or its file is not there."""
    if not channel:
        return {}
    path = Path(root or ROOT) / "channels" / str(channel) / "fact-sources.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for rows in ((data if isinstance(data, dict) else {}).get("tiers") or {}).values():
        for row in rows or []:
            if isinstance(row, dict) and row.get("id"):
                name = _outlet_name(row)
                if name:
                    out[row["id"]] = name
    return out


def _host_of(url):
    host = urlsplit(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _ref(sup, pieces, outlets=None):
    """One support as the block shows it: `{kind, quote, label, link}`.
    `outlets` - {fact-sources id: name} of the channel, for a company page
    with no `publication` of its own (CF-0771)."""
    if sup.get("kind") == "shot":
        return {"kind": "shot", "shot_id": sup.get("shot_id"),
                "description": (sup.get("description") or "").strip()}
    piece = pieces.get(sup.get("source")) or {}
    if VENDOR_KIND in (piece.get("source"), piece.get("kind"), sup.get("piece_kind")) \
            or str(sup.get("source") or "").startswith(VENDOR_KIND + ":"):
        # CF-0771: the company's own page - its site's name (else the
        # outlet's name in the channel's fact-sources, else the host), the
        # page's title, the moment it was read; the page itself is the link
        link = piece.get("url") or sup.get("url")
        who = (str(piece.get("publication") or "").strip()
               or (outlets or {}).get(piece.get("outlet") or "")
               or _host_of(link) or "страница компании")
        title = str(piece.get("title") or "").strip()
        read = str(sup.get("fetched_at") or piece.get("fetched_at") or "")[:16].replace("T", " ")
        label = ", ".join(x for x in (who, f"«{title}»" if title else "",
                                      f"прочитано {read} UTC" if read else "") if x)
        return {"kind": VENDOR_KIND, "quote": sup.get("quote"), "label": label, "link": link}
    if (piece.get("source") or "") == "tvmaze" or sup.get("piece_kind") == "tvmaze_episode":
        # CF-0636: TVmaze's description of the episode - no revision; the
        # moment it was read stands in the label, the episode page is the link
        code = ""
        if piece.get("season") is not None and piece.get("episode") is not None:
            code = f"S{piece['season']}E{piece['episode']}"
        what = " ".join(x for x in (piece.get("show"), code) if x)
        if piece.get("title"):
            what = f"{what} «{piece['title']}»".strip()
        read = str(sup.get("fetched_at") or piece.get("fetched_at") or "")[:16].replace("T", " ")
        label = ", ".join(x for x in ("TVmaze", what, f"прочитано {read} UTC" if read else "") if x)
        return {"kind": "tvmaze", "quote": sup.get("quote"), "label": label,
                "link": piece.get("url") or sup.get("url")}
    if (piece.get("source") or "") == "wikidata" or sup.get("piece_kind") == "wikidata_statement":
        # CF-0637: a Wikidata statement - the item, its property and the
        # revision it was read in; the link is that revision of the item
        rev = sup.get("revision_id") or piece.get("revision_id")
        item = piece.get("entity")
        what = ", ".join(x for x in (
            f"{piece.get('entity_label')} ({item})" if piece.get("entity_label") and item else item,
            piece.get("property_label")) if x)
        label = ", ".join(x for x in ("Wikidata", what, f"ревизия {rev}" if rev else "") if x)
        link = (f"https://www.wikidata.org/w/index.php?title={item}&oldid={rev}"
                if item and rev else piece.get("url") or sup.get("url"))
        return {"kind": "wikidata", "quote": sup.get("quote"), "label": label, "link": link}
    if (piece.get("source") or "") == "rss" or sup.get("piece_kind") == "rss_summary":
        day = str(piece.get("published_at") or "")[:10]
        label = ", ".join(x for x in (piece.get("publication"), day) if x) or "новость"
        return {"kind": "news", "quote": sup.get("quote"), "label": label,
                "link": piece.get("url") or sup.get("url")}
    title = piece.get("article") or piece.get("title") or sup.get("source")
    rev = sup.get("revision_id") or piece.get("revision_id")
    label = f"Википедия, {title}" + (f", ревизия {rev}" if rev else "")
    return {"kind": "wikipedia", "quote": sup.get("quote"), "label": label,
            "link": _wiki_link(sup.get("url") or piece.get("url"), rev)}


def block_lines(report, topic, outlets=None):
    """Every claim that follows, with its references, in the order of the
    viewer's text (narrator and on-screen first, then title, description).
    `outlets` - the channel's {fact-sources id: name} (`outlet_names`)."""
    cj = judge_module()
    pieces = cj.claims.support_pieces(topic)
    results = {r.get("claim_id"): r for r in (report.get("mechanics") or {}).get("results") or []}
    order = {w: i for i, w in enumerate(("hook", "commentary", "payoff", "on_screen",
                                         TITLE, DESCRIPTION))}
    lines = []
    for v in report.get("verdicts") or []:
        if v.get("state") != cj.STATE_SUPPORTED:
            continue
        r = results.get(v.get("claim_id")) or {}
        refs = [_ref(s, pieces, outlets) for s in r.get("supports") or []]
        lines.append({"claim_id": v.get("claim_id"), "where": v.get("where"),
                      "text": v.get("text"), "refs": refs, "reveal": v.get("reveal")})
    lines.sort(key=lambda x: order.get(x["where"], 99))
    return lines


def _q(text):
    return "«" + re.sub(r"\s+", " ", str(text or "")).strip() + "»"


def render_block(result, checked_at, model=None):
    """The section `## Утверждения` (heading included)."""
    mark = {"rule": RULE, "fingerprint": fingerprint(result["text"]),
            "checked_at": checked_at, "model": model,
            "batch": Path(result["batch"]).name, "script_id": result["script_id"],
            "claims": len(result["lines"]), "struck": result.get("struck") or []}
    out = [f"## {SECTION}",
           f"<!-- {MARKER} {json.dumps(mark, ensure_ascii=False)} -->",
           f"Проверено машиной ({RULE}, судья CF-0553): каждое утверждение ролика, названия и "
           f"описания следует из своей опоры. Ниже — утверждение → цитата → ссылка; "
           f"проверять не обязательно."]
    if result.get("struck"):
        out.append("Вычеркнуто из описания (опоры нет): "
                   + "; ".join(f"{_q(s['text'])} (`{s.get('code') or '?'}`)"
                               for s in result["struck"]) + ".")
    out.append("")
    for ln in result["lines"]:
        head = f"- **{WHERE_RU.get(ln['where'], ln['where'])}:** {_q(ln['text'])}"
        refs = []
        for r in ln["refs"]:
            if r["kind"] == "shot":
                refs.append(f"шот `{r['shot_id']}`: {_q(r['description'][:200])}")
            else:
                link = f"[{r['label']}]({r['link']})" if r.get("link") else r["label"]
                refs.append(f"{_q(r['quote'])} — {link}")
        rv = ln.get("reveal")
        if isinstance(rv, dict):
            if rv.get("stable"):
                refs.append(f"раскрытие: текст держится {rv.get('age_h')} ч")
            elif rv.get("second_source"):
                refs.append("раскрытие: подтверждено " + (
                    "описанием эпизода на TVmaze" if "TVmaze" in str(
                        rv.get("second_source_reason") or "") else "новостью темы"))
        out.append(head + "".join(f"\n  → {x}" for x in refs))
    return "\n".join(out) + "\n"


def put_block(text, block):
    """The note with `## Утверждения` replaced, or put after `## Описание`."""
    lines = text.splitlines(keepends=True)
    heads = [(i, re.match(r"^##\s+(.+?)\s*$", ln).group(1)) for i, ln in enumerate(lines)
             if re.match(r"^##\s+(.+?)\s*$", ln) and not ln.startswith("###")]

    def section_end(i):
        nxt = [j for j, _ in heads if j > i]
        return nxt[0] if nxt else len(lines)

    ours = [i for i, name in heads if name == SECTION]
    blk = block if block.endswith("\n") else block + "\n"
    if ours:
        i = ours[0]
        end = section_end(i)
        tail = "\n" if end < len(lines) else ""
        return "".join(lines[:i]) + blk + tail + "".join(lines[end:])
    desc = [i for i, name in heads if name == "Описание"]
    if desc:
        end = section_end(desc[0])
        pre = "".join(lines[:end])
        if not pre.endswith("\n\n"):
            pre = pre.rstrip("\n") + "\n\n"
        return pre + blk + ("\n" + "".join(lines[end:]) if end < len(lines) else "")
    return text.rstrip("\n") + "\n\n" + blk


def write_note(note_path, result, model=None, now=None):
    """Writes the edited description and the block; only a passing verdict."""
    if result["action"] != judge_module().ACTION_PASS:
        raise NoteClaimsError("a note that did not pass gets no block")
    when = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not result.get("struck"):
        # a rerun on a note the edit already cut still names what was cut
        before = (block_of(result["text"]) or {}).get("struck")
        if isinstance(before, list):
            result = dict(result, struck=[s for s in before if isinstance(s, dict)
                                          and s.get("text")])
    text = put_block(result["text"], render_block(result, when, model))
    Path(note_path).write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------- the command
def render(result):
    ok = result["action"] == judge_module().ACTION_PASS
    lines = [f"{'ok  ' if ok else 'FAIL'} {result['note']}: script {result['script_id']}, "
             f"{len(result['lines'])} claim(s) with their footing"
             + (f", {len(result['struck'])} struck out of the description" if result["struck"]
                else "")]
    for s in result["struck"]:
        lines.append(f"  struck ({s.get('code')}): {s['text']!r}")
    for p in result["problems"]:
        who = "video" if p.get("video") else p.get("where")
        lines.append(f"  {p.get('code')} [{who}] {p.get('text') or p.get('detail') or ''}")
        if p.get("fix"):
            lines.append(f"      -> {p['fix']}")
    if any(p.get("video") for p in result["problems"]):
        lines.append(f"  {FAIL_VIDEO}: the video's own words fail their footing - the video "
                     f"is rebuilt, the note is not the place to fix it")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("note")
    ap.add_argument("--batch")
    ap.add_argument("--script-id")
    ap.add_argument("--root", help="the data root (pipeline/, publish/) - default the note's")
    ap.add_argument("--write", action="store_true",
                    help="write the edited description and the block (only on a pass)")
    ap.add_argument("--no-edit", action="store_true", help="judge only, strike nothing")
    ap.add_argument("--check-block", action="store_true",
                    help="only say whether the block is there and fresh (no model)")
    ap.add_argument("--answer-cmd", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--now", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    note = Path(args.note)
    if args.check_block:
        try:
            why = check_block(note.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"NOTE CLAIMS: cannot read {note} ({exc})", file=sys.stderr)
            return 3
        print(f"ok   {note}: the block is fresh" if why is None else f"FAIL {note}: {why}")
        return 0 if why is None else 1
    cj = judge_module()
    try:
        text = note.read_text(encoding="utf-8")
        batch_dir, _ = batch_and_script(text, note, args.batch, args.script_id, args.root)
        asker = cj.Asker(args.cache_dir or (batch_dir / cj.CACHE_REL), args.answer_cmd,
                         args.model or cj.DEFAULT_MODEL, args.timeout or cj.DEFAULT_TIMEOUT)
        result = check_note(note, asker, batch_dir, args.script_id, args.root,
                            edit=not args.no_edit, jobs=args.jobs, now=args.now)
    except (OSError, NoteClaimsError) as exc:
        print(f"NOTE CLAIMS: cannot answer - {exc}", file=sys.stderr)
        return 3
    except cj.CannotAsk as exc:
        print(f"NOTE CLAIMS: cannot answer - {exc}", file=sys.stderr)
        return 3
    if args.write and result["action"] == cj.ACTION_PASS:
        write_note(note, result, model=asker.model)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k not in ("text",)},
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(render(result))
        print(f"({asker.asked} call(s) asked, {asker.cached} answered from the cache)"
              + (" - the block is written" if args.write and result["action"] == cj.ACTION_PASS
                 else ""))
    return 0 if result["action"] == cj.ACTION_PASS else 1


if __name__ == "__main__":
    sys.exit(main())
