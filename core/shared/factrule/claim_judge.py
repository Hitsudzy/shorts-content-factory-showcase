#!/usr/bin/env python3
"""CF-0553: an independent reader lists every claim of the finished text, and
a second, separate reader decides whether each claim follows from its footing.

The grill of 2026-10-05 (CF-0546, Q13 / Q6 / Q3). CF-0552 made the writer
declare `script.claims[]` with a verbatim quote of the topic's support_text
(or a shot under the words) and `claims.py` checks the mechanics - the quote
is in its piece, the shot is under the words. Two questions are left that no
mechanics answers, and both must not be answered by the writer:

* **Q13 - completeness.** The list of claims is not the writer's. A separate
  model call reads the FINISHED viewer text - the narrator (hook, commentary,
  payoff), the on-screen wording, and the title / description when they are
  handed in - and writes out every checkable statement by the Q2 rule
  (who / what / when / how many, "first", "only", "nobody knew", "before";
  an exaggeration is a claim; only an explicit opinion is not). It never sees
  `claims[]` nor the sources. Each statement it lists is matched to a
  declared claim (same field, the words overlap); a statement with no
  declared claim is `claim_undeclared` - a claim with no footing. One
  exception crosses fields (CF-0758): a bare presentation of a name -
  "here's RTX Spark", "meet X", "this is the X", "X." - says nothing but the
  name, so it is matched to a declared claim that is itself only that name
  (a card's title "Nvidia RTX Spark", judged against its footing like any
  other claim) wherever it stands. ExampleTech 1854Z lost its only script
  to its hook "here's RTX Spark" while `c1` "Nvidia RTX Spark" followed.
  Anything more than the name ("here's the fastest chip", "meet RTX Spark,
  Nvidia's new chip") is not a bare name and is matched in its own field
  only, as before. A second crosses to the video's fact (CF-0780): a change
  frame around a bare name - "here's what actually changed in Gemini 4
  Argon", "here's what's new in X" - says only "X changed", so it is matched
  to the declared claims of the production fact when that fact is a change
  (up from / previous / dropped / than ...) and names X. ExampleTech 0839Z's
  gemini-4-argon card was refused on that hook while its fact was "all 12
  solved, up from five". "Here's why X is the fastest", a frame with more
  after it, or the frame over a fact that changes nothing stay undeclared.
* **Q6 - entailment.** One more call per declared claim, with no context of
  the writer: the judge sees the claim and its footing only - each quote with
  the paragraph around it (or, Q8, the Indexer's description of a shot,
  which backs only what is visible; a reading of the picture needs text) -
  and answers `follows`, `does_not_follow` or `not_enough`. Anything but
  `follows` is `claim_not_entailed` / `claim_not_enough`.
* **The line before a pointing claim** (CF-0728). A claim that points back
  ("That award came years before it.", "She launched...", "That spacewalk
  lasted...") cannot be read alone: sophie-adenot's payoff, a contrast pair
  whose first half is "The flight is the headline.", was struck at the card
  as `claim_not_enough` - the judge could not tell what "it" was. Such a
  claim (`points_back`: a pronoun or a pointing word - `ANAPHORA`) goes to
  the judge with `context`: the line the viewer hears right before it (the
  sentence before it in hook -> commentary -> payoff, or in its own title /
  description; the on-screen words have none) and the start of its own
  sentence when the claim begins mid-sentence. The context is the video's
  own words only, marked "not a claim, not footing": it tells what the
  pointing words refer to; every checkable part of the claim still has to
  be stated by the footing, and a fact said only in the context is not
  stated. An answer other than `follows` names what is missing
  (`missing`, required of the real model since prompt v4) - it is in the
  row and in the violation's detail.
  CF-0808: one line was too little. example-tech 2026-10-19T0844Z topic 023
  ("It began as Project Tailwind...", list narration "One. ... Two. ...")
  reached the judge with "Two." or a line about a feature as its only
  context and was struck - the subject, named in the hook, was out of sight.
  The context is now the last `CONTEXT_BEFORE` (3) substantive sentences
  before the claim - a fragment of `FRAGMENT_WORDS` (2) words or fewer
  ("Two.", "First,", a numeral) does not count and is left out - and, for a
  spoken claim outside the hook, the hook's sentences first (the video's
  subject is named there). Prompt v5; the context is in the request's
  payload, so the cache key of every changed context is new anyway.
* **A second opinion before a strike** (CF-0579). The CF-0556 exam saw the
  judge's verdict on a borderline claim ("twice", a cause "on the strength
  of", "John Stewart / Skyman") change from run to run, while plain lies
  and numbers / dates held - and one stray "no" strikes a true claim, or,
  for the video's own fact, the whole video. So an answer other than
  `follows` is never final on its own: the same question is put once more
  as a separate call (`opinion: 2` in the request - another cache key, the
  same prompt, no shared context). Both say "no" - struck (the more common
  of the two "no" verdicts, the first on a tie); they part - a third call
  (`opinion: 3`) and the majority of the three decides on follows / does
  not follow. Every answer is in the verdict's row (`opinions[]`); the
  price is in the report - `opinion_calls` (+1 per claim, +2 where they
  parted), `second_opinions`, `third_opinions`. The news question of a
  reveal (Q10 below) is asked the same way.
  CF-0872: a `follows` is confirmed the same way (`CONFIRM_FOLLOWS`). A
  stray "yes" passed a borderline claim as surely as a stray "no" struck a
  true one: the writer's check drew one `follows` ("a reasonable reader would
  take them to be the same person", "a loose reading") and the claim went to
  the voice and the render; the card, asking the same question again, drew
  `not_enough` twice and the finished video stood (example-film 0841Z
  i-play-rocky, 1514Z coyote-vs-acme, example-tech 1448Z android-tv - every
  `claim_not_enough` of an accepted video from 10.10 to 26.10). The decision
  is now made once, at the writer's check, before the render, on two
  concurring answers; the card reads those answers
  (`Asker(read_first=...)`) and does not draw them again.
* **Q3 - no footing, no claim.** The verdict asks the writer for one edit:
  rewrite the text without the struck claims ("reportedly" is no way out -
  `hedged_statement`). A struck claim that is the video's own fact
  (`production_fact`: its `beat_text` or its `on_screen`) leaves nothing to
  rewrite around: `fact_claim` is set, and so are `fact_struck` and
  `refuse_now` - this verdict alone does not stand the video. The stage's
  ladder (CF-0580) then gives the fact its one edit as a REWORDING, not a
  strike: the same fact on the same quote in the quote's own words (the
  CF-0556 exam: Endgame's "announced as one single project", Harbourlights'
  "Berlanti pitched" were true facts said past their quotes), judged again,
  and drops the topic - `claim_unsupported` (SKIP_REASON_CODE) - only if it
  still does not follow; a fact struck as `reveal_too_fresh`, or a topic
  without text, is dropped at once. The ladder itself is the stage's
  (`agents/content-researcher/scripts/check_claims.py`); compliance-checker's
  second pass runs the same judge as a gate
  (`agents/compliance-checker/scripts/check_claims_gate.py`).

* **Q10 - a reveal stands on settled text or on a second source** (CF-0554).
  The judge also says whether the claim is a plot reveal (who killed / turned
  out to be / died / survived / betrayed / how it ended; `reveal` in its
  answer - required of the real model since prompt v2; the CF-0543 lexicon
  that left a `reveal_hint` beside it was retired after the CF-0556 exam,
  where it never saw a reveal the judge missed). A reveal that follows
  passes only if every Wikipedia quote under it has stood 6 hours without
  being taken out (`reveal_age.py`: the page's revision history through the
  shared client, `<batch>/work/wikipedia-cache/`) or, failing that, the same
  entailment question put against the topic's news items alone (its
  `rss_summary` pieces: headline and summary, nothing of Wikipedia - and,
  since CF-0636, its `tvmaze_episode` pieces: TVmaze's description of the
  episode, `SECOND_SOURCE_KINDS`; never a Wikidata statement, CF-0637) answers
  `follows`. Otherwise it is struck like any other claim -
  `reveal_too_fresh` - and the row carries `reveal: {age_h, stable,
  second_source, quotes[], ...}`. `now` is the moment of the check (`--now`
  for a replay).

**How the model is asked** (the shape of the indexer's sieve answerer,
CF-0478). Every call is a command run once per request: a JSON request file
in, a JSON answer file out. The command is a template with `{request}`,
`{answer}`, `{log}`, `{model}`, `{timeout}`, `{python}` - `--answer-cmd`, else
`$CLAIM_JUDGE_ANSWER_CMD`, else this directory's `claim_answer_claude.py`
(headless `claude -p --model sonnet`, no tools, run in an empty directory, its
whole process group killed on the ceiling, `NOT_LOGGED_IN` said, not waited
for). The two kinds of call are separate processes with no shared context;
the judge never sees the script. The answer is checked against its schema
before it counts - a partial answer is a failure (CannotAsk), never a
guess - and one more try is made. Answers are cached by the hash of the
request (kind, model, prompt version, payload) in the cache directory
(default `<batch>/work/claim-judge-cache/`), with the request and the call's
log beside each: a rerun on unchanged words asks nothing.

Command line (read-only, never writes the 03):

    python3 shared/factrule/claim_judge.py <03-content-researcher.json>
        [--script-id ID] [--title T] [--description D] [--answer-cmd CMD]
        [--model sonnet] [--timeout S] [--jobs N] [--cache-dir DIR] [--now ISO] [--json]

exit 0 every script passes, 1 a violation, 3 the question could not be put
(no batch, or the model could not be asked - `NOT_LOGGED_IN` on stderr when
the console claude has no session).
"""
import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path

RULE = "CF-0553"
HERE = Path(__file__).resolve().parent


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


def _load_by_path(name, file):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reveal_age = _load_by_path("factory_reveal_age_cf0554", "reveal_age.py")
# CF-0737: where a sentence ends - the factory's one reading (the same module
# object `fact_rule` loads, keyed by its path).
_sentences = _load_by_path("factory_sentences_cf0737@" + str(HERE / "sentences.py"), "sentences.py")

CHECK_FIELD = claims.CHECK_FIELD            # "claims_check" - the record on the script
SKIP_REASON_CODE = "claim_unsupported"      # the topic's way out of the batch (funnel)
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 240                       # seconds, one call
DEFAULT_JOBS = 4                            # judge calls at once
ATTEMPTS = 2                                # a schema-failing answer is asked once more
PROMPT_VERSION = 5                          # 5: the hook and up to three lines before a pointing claim, fragments out (CF-0808); 2: the judge says whether the claim is a reveal (CF-0554); 3: a quote carries its section (CF-0556); 4: the line before a pointing claim, `missing` (CF-0728)
CACHE_REL = Path("work") / "claim-judge-cache"
WIKIPEDIA_CACHE = "wikipedia-cache"          # beside it: <batch>/work/wikipedia-cache (CF-0551)
RSS_KIND = "rss_summary"                     # = trend-hunter support_text.KIND_RSS
TVMAZE_KIND = claims.TVMAZE_KIND             # = shared/tvmaze/tvmaze_api.KIND_EPISODE (CF-0636)
# The pieces that are a reveal's second source (Q10): text that is not
# Wikipedia's - the topic's news items and, since CF-0636, TVmaze's episode
# description. Their quotes have no revision history to age.
SECOND_SOURCE_KINDS = (RSS_KIND, TVMAZE_KIND)
# CF-0637: a Wikidata statement is quotable footing for a claim (a date, a
# cast member, a studio, an award) but not a reveal's second source - its
# statements are entered from the same coverage Wikipedia is written from and
# say nothing of a plot - and its quote is not aged (`reveal_age.quote_age`
# answers `no_page`): a reveal standing on it alone asks the topic's news.
WIKIDATA_KIND = claims.WIKIDATA_KIND        # = shared/wikidata/wikidata_api.KIND_STATEMENT
ANSWER_CMD_ENV = "CLAIM_JUDGE_ANSWER_CMD"
DEFAULT_ANSWERER = HERE / "claim_answer_claude.py"
NOT_LOGGED_IN = "NOT_LOGGED_IN"             # = claim_answer_claude.NOT_LOGGED_IN
EXIT_NOT_LOGGED_IN = 4                      # = claim_answer_claude.EXIT_NOT_LOGGED_IN

KIND_EXTRACT = "extract"
KIND_ENTAIL = "entail"

FOLLOWS = "follows"
DOES_NOT_FOLLOW = "does_not_follow"
NOT_ENOUGH = "not_enough"
VERDICTS = (FOLLOWS, DOES_NOT_FOLLOW, NOT_ENOUGH)
OPINION_KEY = "opinion"                      # CF-0579: the request's opinion number (2, 3)
OPINIONS_MAX = 3                            # a split of two is settled by a third
CONFIRM_FOLLOWS = True                      # CF-0872: a `follows` is asked twice as well

FAIL_UNDECLARED = "claim_undeclared"
FAIL_NOT_ENTAILED = "claim_not_entailed"
FAIL_NOT_ENOUGH = "claim_not_enough"
FAIL_REVEAL_TOO_FRESH = "reveal_too_fresh"   # CF-0554
FAIL_CODES = (FAIL_UNDECLARED, FAIL_NOT_ENTAILED, FAIL_NOT_ENOUGH, FAIL_REVEAL_TOO_FRESH)
# The mechanics' violations a rewrite cannot cure: no text, no script.
FATAL_MECHANICS = (claims.FAIL_TOPIC_WITHOUT_TEXT,)

FIXES = {
    FAIL_UNDECLARED: "the finished text says this and no claim backs it - take it out of the "
                     "text (rewrite the sentence without it), or declare it in `claims[]` with "
                     "a verbatim quote of the topic's support_text that says it",
    FAIL_NOT_ENTAILED: "the footing does not say this - strike it: rewrite the sentence without "
                       "the claim (never \"reportedly\"); the video's own fact is not struck but "
                       "said once more in its quote's own words (CF-0580), and the topic is "
                       "dropped if it still does not follow",
    FAIL_NOT_ENOUGH: "the footing is not enough to say this - strike it: rewrite the sentence "
                     "without the claim, or keep only what the quote says (the video's own "
                     "fact: its verb and qualifiers, CF-0580)",
    FAIL_REVEAL_TOO_FRESH: "a plot reveal (who killed / turned out to be / died / survived / "
                           "betrayed / how it ended) stands on Wikipedia text that has not "
                           "stood 6 hours without being taken out, and no news item of the "
                           "topic says it - strike it: say what is certain (\"the finale "
                           "reveals who killed Hal\"), never \"reportedly\"; if the video has "
                           "no fact without it, the topic is dropped",
}

ACTION_PASS, ACTION_FAIL = claims.ACTION_PASS, claims.ACTION_FAIL
STATE_SUPPORTED = "supported"
STATE_STRUCK = "struck"
STATE_MECHANICS = "mechanics_failed"
STATE_PENDING = "pending"

# ------------------------------------------------------------------ prompts
EXTRACT_PROMPT = """You read the finished text of a short video and list every CHECKABLE CLAIM in it.

A claim is anything that could be checked against a source: who did what, who plays whom, what happened, when, how many, a number, a date, a name tied to an event, "first", "only", "never", "nobody knew", "before X", "months before anyone", a cause ("because"), a result. An exaggeration is a claim. A statement about what is visible in the picture ("watch her on the porch") is a claim too.
NOT a claim: an explicit opinion or judgement ("bold", "the best scene", "it works"), an instruction to the viewer with nothing checkable in it, a question, a rhetorical flourish with no checkable content.

The text is given as fields. List the claims of every field. Each item's "text" must be copied VERBATIM from its field - a contiguous span of the field's words, nothing added, nothing reworded - and should be the shortest span that carries the whole claim (usually a clause or a sentence). One item per claim; a sentence with two claims gives two items.

Answer with ONLY a JSON object, no prose, no code fence:
{"claims": [{"where": "<field name>", "text": "<verbatim span>"}]}
An empty list is a valid answer when there is no claim.

FIELDS:
"""

ENTAIL_PROMPT = """You judge ONE claim against its footing and nothing else. You know nothing about the work or the people except what the footing says; do not use your own knowledge.

The footing is one or more items:
- "quote": a verbatim quote of a source text, with the paragraph around it ("context"), the heading path of the section it stands under ("section", when the source has headings - it is part of what the source says), the source's kind and title;
- "news": a news item as its publication put it out - the headline ("title") and the summary;
- "shot": the description of a video shot as an indexer saw it. A shot description supports ONLY what is visible in the frame (who/what is on screen, what they do). It never supports a reading of the picture: who someone is beyond what is visible, why something happens, what it means, what happened before or after.

Answer:
- "follows" - the footing, read together, says the claim: every checkable part of it (who, what, when, how many, "first", "only", "before") is stated there. Paraphrase is fine; a reasonable reader would agree the footing says it.
- "does_not_follow" - the footing says something else, or contradicts it (a different person, number, date, relation), or the claim adds a link the footing does not make.
- "not_enough" - the footing is about the subject but does not say this much (an exaggeration, an added detail, a stronger word than the source uses).

CONTEXT, when it is given, is what the viewer hears before the claim - the video's opening line(s) (the hook, where the video names its subject) and the few lines right before the claim, in order - the video's own words, NOT a source. It is not a claim to judge and it is not footing: use it ONLY to tell what the claim's pronouns and pointing words ("it", "that award", "she", "this", "they") refer to. The claim with those references filled in is then judged against the footing like any other claim: every checkable part must be stated by the footing; something said only in the context is not stated. Without a context, read the pointing words as the footing best supports them.

Read the claim in its plain sense, as a viewer would; do not demand the footing use the claim's words. Putting items of the footing together, and simple arithmetic on what it states (a difference of two numbers, the order of two dated events, counting how many times something it describes happened), is reading the footing, not adding to it. A claim is "not_enough" or "does_not_follow" only because of a checkable part the footing does not state or states otherwise - name that part in the reason.

Also say whether the claim is a PLOT REVEAL of a story (a series, film, book, game): who killed or attacked whom, who someone turns out to be (a hidden identity, a secret relation), who dies or survives, who betrays whom, how the story ends. Cast, production, dates, numbers, reception and the premise are not reveals. Say it from the claim alone, whatever the verdict.

Answer with ONLY a JSON object, no prose, no code fence:
{"reason": "<one or two sentences: the claim's checkable parts, and for each whether the footing states it>", "verdict": "follows" | "does_not_follow" | "not_enough", "missing": "<when the verdict is not follows: exactly what the footing does not state (the part of the claim, or the referent that cannot be told); empty when it follows>", "reveal": true | false}

CLAIM:
"""

CONTEXT_HEAD = ("\n\nCONTEXT (the lines the viewer hears before the claim, in order: the opening "
                "line(s), then the ones right before it - not a claim to judge, not footing; "
                "only for what the claim's pointing words refer to):\n")


def extract_prompt(texts):
    return EXTRACT_PROMPT + json.dumps(texts, ensure_ascii=False, indent=2) + "\n"


def entail_prompt(claim_text, footing, context=None):
    ctx = (CONTEXT_HEAD + json.dumps(list(context), ensure_ascii=False, indent=2)) if context else ""
    return (ENTAIL_PROMPT + json.dumps(claim_text, ensure_ascii=False) + ctx + "\n\nFOOTING:\n"
            + json.dumps(footing, ensure_ascii=False, indent=2) + "\n")


# ------------------------------------------------------------------ answers
def check_extract_answer(answer, texts):
    """Problems with the extractor's answer against the fields it read; []
    when every item is a verbatim span of its field."""
    if not isinstance(answer, dict) or not isinstance(answer.get("claims"), list):
        return ["no `claims` list"]
    problems = []
    for i, item in enumerate(answer["claims"]):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) \
                or not item["text"].strip():
            problems.append(f"item {i}: not {{where, text}}")
            continue
        where = item.get("where")
        if where not in texts:
            problems.append(f"item {i}: where {where!r} is not a field it was given")
            continue
        span = claims.norm(item["text"]).strip(claims._EDGE_PUNCT)
        if span not in claims.norm(texts[where]):
            problems.append(f"item {i}: {item['text']!r} is not verbatim in {where}")
    return problems


def check_entail_answer(answer, require_reveal=False):
    """`reveal` (CF-0554) is required of the default answerer; a stand-in
    answer command may give the v1 shape - no `reveal` is "not a reveal"."""
    if not isinstance(answer, dict) or answer.get("verdict") not in VERDICTS:
        return [f"verdict not one of {', '.join(VERDICTS)}"]
    if not isinstance(answer.get("reason"), str):
        return ["no `reason` string"]
    if "reveal" in answer and not isinstance(answer["reveal"], bool):
        return ["`reveal` is not true / false"]
    if require_reveal and "reveal" not in answer:
        return ["no `reveal` true / false"]
    if "missing" in answer and not isinstance(answer["missing"], str):
        return ["`missing` is not a string"]
    if require_reveal and answer["verdict"] != FOLLOWS and not (answer.get("missing") or "").strip():
        return ["no `missing` for a verdict that is not follows"]     # CF-0728
    return []


# ------------------------------------------------------------------ asking
class CannotAsk(RuntimeError):
    """The model could not be asked (no command, not logged in, the ceiling,
    an answer that never met its schema). Never a verdict on a claim."""

    def __init__(self, msg, not_logged_in=False):
        super().__init__(msg)
        self.not_logged_in = not_logged_in


def request_key(kind, model, payload):
    blob = json.dumps({"kind": kind, "model": model, "v": PROMPT_VERSION, "payload": payload},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def answer_cmd_template(flag=None, env=None):
    env = os.environ if env is None else env
    return flag or env.get(ANSWER_CMD_ENV) or (
        "{python} " + shlex.quote(str(DEFAULT_ANSWERER)) + " --request {request} "
        "--answer {answer} --log {log} --model {model} --timeout {timeout}")


KILL_GRACE_S = 5.0                 # SIGTERM -> SIGKILL of the group past the ceiling


def _proc_group():
    """`shared/proc_group.py` by path (CF-0655), loaded only when a kill is needed."""
    import importlib.util  # noqa: PLC0415
    name = "factory_proc_group_cf0655"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent.parent / "proc_group.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _kill_group(p):
    """SIGTERM to the group, SIGKILL when anything in it - not only the direct
    child - is still there after `KILL_GRACE_S` (CF-0655)."""
    _proc_group().kill_group(p.pid, KILL_GRACE_S, reap=p.poll)
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


class Asker:
    """Runs the answer command once per uncached request; one per run.

    `read_first` (CF-0872): cache directories whose answers are taken before
    this one's and never written - the card's asker reads the writer's
    `<batch>/work/claim-judge-cache/` there, so the very question the stage
    already put (the same key: the same claim, footing, context, opinion) is
    answered as the stage was answered, not drawn again from the model."""

    def __init__(self, cache_dir, answer_cmd=None, model=DEFAULT_MODEL,
                 timeout=DEFAULT_TIMEOUT, read_first=None):
        self.cache_dir = Path(cache_dir)
        self.read_first = [Path(d) for d in read_first or [] if Path(d) != Path(cache_dir)]
        self.template = answer_cmd_template(answer_cmd)
        # The default answerer is the real model: its answer must carry every
        # field of the current prompt (`reveal`, CF-0554).
        self.default_answerer = not (answer_cmd or os.environ.get(ANSWER_CMD_ENV))
        self.model = model
        self.timeout = timeout
        self.asked = 0
        self.cached = 0

    def _paths(self, key):
        d = self.cache_dir
        return d / f"{key}.request.json", d / f"{key}.answer.json", d / f"{key}.log"

    def ask(self, kind, payload, prompt, validate):
        """The answer of one request: cached, else asked (at most ATTEMPTS
        times until it meets `validate`)."""
        key = request_key(kind, self.model, payload)
        req, ans, log = self._paths(key)
        for found in [d / ans.name for d in self.read_first] + [ans]:
            if not found.is_file():
                continue
            try:
                answer = json.loads(found.read_text(encoding="utf-8"))
                if not validate(answer):
                    self.cached += 1
                    return answer, key
            except (OSError, ValueError):
                pass
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        req.write_text(json.dumps({"rule": RULE, "kind": kind, "model": self.model,
                                   "prompt_version": PROMPT_VERSION, "payload": payload,
                                   "prompt": prompt}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        problems = []
        for _ in range(ATTEMPTS):
            if ans.exists():
                ans.unlink()
            self._run(req, ans, log)
            self.asked += 1
            try:
                answer = json.loads(ans.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems = [f"no readable answer ({exc.__class__.__name__})"]
                continue
            problems = validate(answer)
            if not problems:
                return answer, key
        if ans.exists():
            ans.rename(ans.with_suffix(".rejected.json"))
        raise CannotAsk(f"{kind} {key}: the answer did not meet its schema "
                        f"({'; '.join(problems[:3])}); log {log}")

    def _run(self, req, ans, log):
        cmd = self.template.format(
            request=shlex.quote(str(req)), answer=shlex.quote(str(ans)),
            log=shlex.quote(str(log)), model=shlex.quote(self.model),
            timeout=int(self.timeout), python=shlex.quote(sys.executable))
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, env=env, start_new_session=True,
                             text=True)
        try:
            _, err = p.communicate(timeout=self.timeout + 30)
        except subprocess.TimeoutExpired:
            _kill_group(p)
            raise CannotAsk(f"the answer command ran past {self.timeout + 30}s and was "
                            f"stopped; log {log}")
        if p.returncode == EXIT_NOT_LOGGED_IN or NOT_LOGGED_IN in (err or ""):
            raise CannotAsk(f"{NOT_LOGGED_IN} - the console claude is not logged in "
                            f"(`claude`, then /login); log {log}", not_logged_in=True)
        if p.returncode != 0:
            tail = (err or "").strip().splitlines()[-1:] or [""]
            raise CannotAsk(f"the answer command exited {p.returncode}: {tail[0][:300]}; "
                            f"log {log}")


# ------------------------------------------------------------ the opinions
def _opinion(n, answer, key):
    o = {"n": n, "verdict": answer["verdict"], "reason": answer.get("reason"), "key": key}
    if answer.get("reveal") is not None:
        o["reveal"] = answer["reveal"]
    if (answer.get("missing") or "").strip():
        o["missing"] = answer["missing"]
    return o


def decide(opinions):
    """The verdict of one, two or three opinions (CF-0579): the majority on
    follows / does not follow; among the "no" answers the more common verdict,
    the first one's on a tie. Returns the index of the opinion that speaks
    for the decision (its reason and `reveal` go into the row)."""
    yes = [i for i, o in enumerate(opinions) if o["verdict"] == FOLLOWS]
    no = [i for i, o in enumerate(opinions) if o["verdict"] != FOLLOWS]
    if len(yes) > len(no):
        return yes[0]
    counts = {}
    for i in no:
        counts[opinions[i]["verdict"]] = counts.get(opinions[i]["verdict"], 0) + 1
    best = max(counts.values())
    return next(i for i in no if counts[opinions[i]["verdict"]] == best)


def ask_entailment(asker, claim_text, footing, validate, context=None):
    """One entailment question with its second opinion (CF-0579): every first
    answer - a `follows` too since CF-0872 (`CONFIRM_FOLLOWS`) - is asked once
    more as a separate call; two that agree decide, a split is settled by a
    third. Returns (answer, key, opinions[]) - `answer` the
    deciding opinion's answer with the decided verdict, `key` the first
    call's cache key (the one a run before CF-0579 wrote). `context` - the
    line(s) before a pointing claim (CF-0728), in the payload only when there
    is one."""
    payload = {"claim": claim_text, "footing": footing}
    if context:
        payload["context"] = list(context)
    prompt = entail_prompt(claim_text, footing, context)
    answer, key = asker.ask(KIND_ENTAIL, payload, prompt, validate)
    answers, opinions = [answer], [_opinion(1, answer, key)]
    n = 1
    while n < OPINIONS_MAX:
        if n == 1 and opinions[0]["verdict"] == FOLLOWS and not CONFIRM_FOLLOWS:
            break
        if n >= 2 and len({o["verdict"] == FOLLOWS for o in opinions}) == 1:
            break                                   # the two agree
        n += 1
        a, k = asker.ask(KIND_ENTAIL, dict(payload, **{OPINION_KEY: n}), prompt, validate)
        answers.append(a)
        opinions.append(_opinion(n, a, k))
    i = decide(opinions)
    return answers[i], key, opinions


def extra_calls(opinions):
    return max(0, len(opinions or []) - 1)


# ------------------------------------------------------------------ matching
_STOP = frozenset("""a an the and or but of in on at to for by with from as is are was were be
been being it its this that these those he she they his her their him them we our you your
i me my who whom whose which what when where how than then so not no do does did has have
had will would can could just also into out up about over after before there here""".split())


def _content(text):
    return [w for w in claims.words(text) if w not in _STOP]


def overlap(a, b):
    """Shared content words of two spans over the shorter one's count."""
    wa, wb = set(_content(a)), set(_content(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def coverage(listed, declared):
    """The share of the listed claim's content words the declared one has -
    measured on the reader's span, so a short declared claim cannot cover a
    long statement that says more than it does."""
    want = set(_content(listed))
    if not want:
        return 0.0
    return len(want & set(_content(declared))) / len(want)


MATCH_MIN = 0.6           # one declared claim covers a listed one
UNION_MIN = 0.75          # several declared claims of the field cover it together


# CF-0758: a bare presentation of a name. The words that only present what
# follows them, then the name: every word of it capitalised (or a number),
# connectors between them lower case, no clause punctuation inside.
_INTROS = tuple(tuple(x.split()) for x in (
    "here's", "here is", "heres", "meet", "this is", "this's", "that's", "that is",
    "it's", "it is", "introducing", "presenting", "say hello to", "say hi to"))
_NAME_LINKS = frozenset("the of and for de del der la le von van & + x".split())
_NAME_PUNCT = re.compile(r"[,;:!?()\"\[\]]")
NAME_MAX_WORDS = 6


def bare_name(text):
    """The name a span only presents ("here's RTX Spark" -> "RTX Spark",
    "Nvidia RTX Spark." -> itself), None when the span says anything else."""
    if not isinstance(text, str):
        return None
    t = text.replace("\u2019", "'").replace("\u2018", "'").strip(claims._EDGE_PUNCT + "-")
    if not t or _NAME_PUNCT.search(t):
        return None
    toks = t.split()
    low = [w.lower() for w in toks]
    for intro in sorted(_INTROS, key=len, reverse=True):
        if tuple(low[:len(intro)]) == intro:
            toks = toks[len(intro):]
            break
    if toks and toks[0].lower() == "the":
        toks = toks[1:]
    if not toks or len(toks) > NAME_MAX_WORDS:
        return None
    if toks[-1].lower() in _NAME_LINKS or not toks[0][:1].isupper():
        return None
    for w in toks:
        if w.lower() in _NAME_LINKS:
            continue
        if not (w[:1].isupper() or w[:1].isdigit()):
            return None
    return " ".join(toks)


def name_match(item, declared):
    """CF-0758: the declared claims - of any field - that are only the name
    the listed span barely presents (its words all among theirs)."""
    name = bare_name(item.get("text"))
    if name is None:
        return []
    want = set(_content(name))
    if not want:
        return []
    hits = []
    for c in declared:
        if not isinstance(c, dict) or not isinstance(c.get("text"), str):
            continue
        theirs = bare_name(c["text"])
        if theirs is not None and want <= set(_content(theirs)):
            hits.append(c["claim_id"])
    return hits


# CF-0780: a change frame. "Here's what actually changed in Gemini 4 Argon."
# says no more than "X changed" - what changed is what the video then says.
# It is that video's fact when the fact is a change (a comparison with
# before) and names X; it says nothing the fact does not. Only the frame and
# a bare name (CF-0758): "here's why X is the fastest", "here's what changed
# in X: it beat Y" or "here's what X changed" are claims of their own.
_CHANGE_FRAME_RE = re.compile(
    r"^(?:here's|here is|heres|this is)\s+what(?:'s|\s+is|\s+has)?\s+"
    r"(?:(?:actually|really|just|now)\s+)?(?:changed|new|different|improved)\s+"
    r"(?:in|with|for|about)\s+(?P<name>\S.*)$", re.I)
# The words of a fact that set it against before: "up from five", "the
# previous generation managed five", "dropped to two percent", "than".
_CHANGE_WORDS = frozenset("""previous previously earlier before prior predecessor than
compared versus vs rose risen fell fallen dropped drop increased increase decreased decrease
doubled tripled quadrupled halved jumped grew grown climbed improved improvement changed
now anymore longer""".split())
_CHANGE_PHRASE_RE = re.compile(r"\b(?:up|down) from\b|\bno longer\b|\bused to\b", re.I)


def change_frame_name(text):
    """The name a change frame is about ("here's what actually changed in
    Gemini 4 Argon" -> "Gemini 4 Argon"), None for anything else."""
    if not isinstance(text, str):
        return None
    t = text.replace("’", "'").replace("‘", "'").strip(claims._EDGE_PUNCT + "-")
    m = _CHANGE_FRAME_RE.match(t)
    return bare_name(m.group("name")) if m else None


def is_change(text):
    """Does the text set something against how it was before?"""
    if not isinstance(text, str):
        return False
    return bool(_CHANGE_PHRASE_RE.search(text)) or any(
        w in _CHANGE_WORDS for w in claims.words(text))


def frame_match(item, declared, script):
    """CF-0780: the declared claims of the video's fact that back a change
    frame - only when that fact is a change and names the frame's subject."""
    name = change_frame_name(item.get("text"))
    if name is None:
        return []
    pf = (script or {}).get("production_fact")
    if not isinstance(pf, dict):
        return []
    facts = [t for t in (pf.get("text"), pf.get("beat_text"), pf.get("on_screen"))
             if isinstance(t, str) and t]
    want = set(_content(name))
    have = set()
    for t in facts:
        have |= set(_content(t))
    if not want or not want <= have or not any(is_change(t) for t in facts):
        return []
    return [c["claim_id"] for c in declared if isinstance(c, dict)
            and isinstance(c.get("text"), str) and c.get("claim_id")
            and is_fact_claim(c, script)]


def match_extracted(extracted, declared, script=None):
    """For each listed claim, the ids of the declared claims (same field)
    that cover it; a bare presentation of a name, the declared claims that
    are that name in any field (CF-0758); a change frame, the claims of the
    video's fact when that fact is a change about the same name (CF-0780,
    needs `script`); [] - undeclared."""
    out = []
    for item in extracted:
        same = [c for c in declared if isinstance(c, dict) and c.get("where") == item["where"]
                and isinstance(c.get("text"), str)]
        hits = [c["claim_id"] for c in same if coverage(item["text"], c["text"]) >= MATCH_MIN]
        if not hits and same:
            want = set(_content(item["text"]))
            parts = [c for c in same if set(_content(c["text"])) & want]
            have = set()
            for c in parts:
                have |= set(_content(c["text"])) & want
            if want and len(have) / len(want) >= UNION_MIN:
                hits = [c["claim_id"] for c in parts]
        if not hits:
            hits = name_match(item, declared)
        if not hits and script is not None:
            hits = frame_match(item, declared, script)
        out.append(hits)
    return out


def fact_texts(script):
    """The words of the video's own fact - a claim among them that has no
    footing leaves no video to rewrite."""
    pf = (script or {}).get("production_fact")
    if not isinstance(pf, dict):
        return []
    return [t for t in (pf.get("beat_text"), pf.get("on_screen")) if isinstance(t, str) and t]


def is_fact_claim(claim, script):
    if claim.get("where") == claims.WHERE_ON_SCREEN:
        return True
    return any(overlap(claim.get("text") or "", t) >= MATCH_MIN for t in fact_texts(script))


# ------------------------------------------------------------------ footing
def footing_of(result, pieces=None):
    """What the judge sees of one claim's footing - nothing of the script:
    each quote with its paragraph and the kind / title of its piece, each
    shot's description (a shot not looked up yet gives nothing to judge)."""
    pieces = pieces or {}
    out = []
    for s in result.get("supports") or []:
        if s.get("kind") == "quote":
            piece = pieces.get(s.get("source")) or {}
            item = {"kind": "quote", "quote": s.get("quote"),
                    "context": s.get("context"), "source_kind": s.get("piece_kind"),
                    "source_title": piece.get("title")}
            if s.get("section"):
                item["section"] = s["section"]      # CF-0556: the heading above the paragraph
            out.append(item)
        elif s.get("kind") == "shot" and isinstance(s.get("description"), str) \
                and s["description"].strip():
            out.append({"kind": "shot", "description": s["description"]})
    return out + name_lines(result.get("text"), result.get("supports"), pieces, out)


# CF-0872: a person the quote names in part ("Sylvester's co-star") and the
# claim in full ("Sylvester Stallone's co-star") - the line of the same source
# that names them in full goes to the judge beside the quote.
NAME_LINES_MAX = 2
NAME_PART_MIN = 3                       # letters of a name part looked for in the quote
_NAME_RE = re.compile(r"[A-Z][\w’'\-]*(?:[ \t]+[A-Z][\w’'\-]*)+")
_POSSESSIVE_RE = re.compile(r"['’]s$")


def claim_names(text):
    """The names of a claim: runs of two or more capitalised words, a leading
    function word ("And", "In") and a possessive "'s" off ("Sylvester
    Stallone's co-star" -> "Sylvester Stallone")."""
    out = []
    for m in _NAME_RE.finditer(text or ""):
        ws = m.group(0).split()
        while ws and ws[0].casefold() in _STOP:
            ws = ws[1:]
        if ws:
            ws[-1] = _POSSESSIVE_RE.sub("", ws[-1])
        if len(ws) >= 2 and ws not in out:
            out.append(ws)
    return [" ".join(ws) for ws in out]


def _has_words(hay_n, phrase_n):
    return re.search(r"(?<![\w'])" + re.escape(phrase_n) + r"(?![\w])", hay_n) is not None


def name_lines(claim_text, supports, pieces, footing):
    """CF-0872 (example-film 0841Z i-play-rocky): the claim names a person in
    full ("Sylvester Stallone's co-star"), its quote only in part ("Stephan
    James as Carl Weathers, Sylvester's co-star playing Apollo Creed") and the
    same piece of the source names them in full elsewhere ("Anthony Ippolito
    as Sylvester Stallone, ..."). That line is footing too - the source's
    own words, read together with the quote: it is added as one more quote
    item of the same piece (its sentence, its section). Only the quote's own
    piece is searched - never another source, never what the model knows;
    a name with no part in the quote (a person the footing does not mention)
    gets nothing, and neither does a name the footing already gives whole.
    At most `NAME_LINES_MAX` lines a claim."""
    pieces = pieces or {}
    quotes = [s for s in supports or [] if s.get("kind") == "quote"]
    if not claim_text or not quotes:
        return []
    have_n = claims.norm(" ".join(f"{f.get('quote') or ''} {f.get('context') or ''}"
                                  for f in footing if f.get("kind") == "quote"))
    have_words = {_POSSESSIVE_RE.sub("", w) for w in claims.words(have_n)}
    out, seen = [], {claims.norm(f.get("quote") or "") for f in footing}
    for name in claim_names(claim_text):
        if len(out) >= NAME_LINES_MAX:
            break
        name_n = claims.norm(name)
        if _has_words(have_n, name_n):
            continue
        parts = [w for w in claims.words(name) if len(w) >= NAME_PART_MIN and w not in _STOP]
        if not any(w in have_words for w in parts):
            continue
        line = _name_line(name_n, quotes, pieces)
        if line and claims.norm(line["quote"]) not in seen:
            seen.add(claims.norm(line["quote"]))
            out.append(line)
    return out


def _name_line(name_n, quotes, pieces):
    """The sentence of a quote's own piece that names `name_n` in full - under
    the quote's section when one is there, else the nearest to the quote."""
    for s in quotes:
        piece = pieces.get(s.get("source")) or {}
        body = claims.quotable_text(piece)
        if not body:
            continue
        lines = body.splitlines()
        q_n = claims.norm_quote(s.get("quote") or "")
        at = next((i for i, ln in enumerate(lines) if q_n and q_n in claims.norm(ln)), 0)
        best = None
        for i, ln in enumerate(lines):
            if claims.HEADING_RE.match(ln.strip()):
                continue
            for sent in claims._sentences(ln):
                sent_n = claims.norm(sent)
                if not _has_words(sent_n, name_n):
                    continue
                section = claims.quote_section(body, claims.norm_quote(sent))
                rank = (section != s.get("section"), abs(i - at))
                if best is None or rank < best[0]:
                    best = (rank, sent.strip(), section)
        if best:
            item = {"kind": "quote", "quote": best[1], "context": best[1],
                    "source_kind": piece.get("kind"), "source_title": piece.get("title")}
            if best[2]:
                item["section"] = best[2]
            return item
    return None


# ------------------------------------------------------------------ context
# CF-0728: the words that point back to something said before - a claim with
# one of them is read with the lines before it.
# CF-0808: how many substantive sentences before the claim the judge reads,
# and the length (in words) of a fragment that is not one ("Two.", "First,").
CONTEXT_BEFORE = 3
FRAGMENT_WORDS = 2
ANAPHORA = frozenset("""it its itself this that these those they them their theirs themselves
he him his himself she her hers herself then there such same former latter""".split())
CONTEXT_FIELDS = (claims.WHERE_SPOKEN, (claims.WHERE_TITLE,), (claims.WHERE_DESCRIPTION,))
# The gap after a stop (and up to two closing quotes or brackets) - not inside
# «$27.5» or «2.5 million», and not after «Bros.», «Dr.» or an initial
# (CF-0737, `sentences.split_at`).
_SENTENCE_GAP_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"'”’)\]])"
                              r"|(?<=[.!?…][\"'”’)\]]{2}))\s+")


def points_back(text):
    """Does the claim point back (a pronoun, "that ...", "then")? CF-0728."""
    return any(w in ANAPHORA for w in claims.words(text))


def is_fragment(sentence):
    """A list marker or a numeral standing as a sentence ("Two.", "First,",
    "Number one.") - nothing a pointing word can refer to (CF-0808)."""
    return len(claims.words(sentence)) <= FRAGMENT_WORDS


def sentences(text):
    """The sentences of a text, each stripped, the closing quotes kept with
    its stop."""
    return [s.strip() for s in _sentences.split_at(text or "", _SENTENCE_GAP_RE) if s.strip()]


def script_pairs(script):
    """The contrast pairs of the script (`pattern.sides.pairs[]`, {a, b})."""
    sides = ((script or {}).get("pattern") or {}).get("sides") or {}
    pairs = sides.get("pairs") if isinstance(sides, dict) else None
    return [x for x in pairs or [] if isinstance(x, dict)
            and isinstance(x.get("a"), str) and isinstance(x.get("b"), str)]


def claim_context(claim_text, where, texts, pairs=None):
    """The lines the viewer meets before a pointing claim (CF-0728, CF-0808):
    the last `CONTEXT_BEFORE` substantive sentences before the one it is in -
    across hook -> commentary -> payoff for the narrator, inside its own
    field for the title and the description; a fragment (`is_fragment`:
    "Two.", "First,") is left out and not counted - with, for a spoken claim
    outside the hook, the hook's sentences first (where the video names its
    subject), and the start of its own sentence when the claim begins
    mid-sentence; for the second line of a contrast pair (`pairs`, spoken
    lines only) its first line too, when it is not among them already. In
    the order the viewer hears them. [] for a claim that does not point
    back, the on-screen words, a graphic, or a claim not found in its text.
    Only the video's own words; never a source."""
    if not isinstance(claim_text, str) or not points_back(claim_text):
        return []
    group = next((g for g in CONTEXT_FIELDS if where in g), None)
    if group is None:
        return []
    texts = texts or {}
    tagged = [(w, s) for w in group for s in sentences(texts.get(w))]
    seq = [s for _, s in tagged]
    want = claims.norm(claim_text).strip(claims._EDGE_PUNCT)
    if not want:
        return []
    for i, s in enumerate(seq):
        ns = claims.norm(s)
        at = ns.find(want)
        if at < 0:
            # a claim over two sentences: it starts in this one
            joined = claims.norm(" ".join(seq[i:i + 3]))
            if not (joined.find(want) >= 0 and joined.find(want) < len(ns)):
                continue
            at = joined.find(want)
        out = [x for x in seq[:i] if not is_fragment(x)][-CONTEXT_BEFORE:]
        head = 0                                    # the hook's lines put in front
        if where in claims.WHERE_SPOKEN and tagged[i][0] != claims.WHERE_SPOKEN[0]:
            seen = {claims.norm(x) for x in out}
            hook = [x for w, x in tagged if w == claims.WHERE_SPOKEN[0]
                    and not is_fragment(x) and claims.norm(x) not in seen]
            out = hook + out
            head = len(hook)
        if where in claims.WHERE_SPOKEN:
            for pair in pairs or []:
                if claims.norm(pair["b"]).strip(claims._EDGE_PUNCT) == \
                        ns.strip(claims._EDGE_PUNCT) and pair["a"].strip() \
                        and claims.norm(pair["a"]) not in {claims.norm(x) for x in out}:
                    out.insert(head, pair["a"].strip())
                    break
        if at > 0:
            raw = s.casefold().find(claim_text.strip(claims._EDGE_PUNCT).casefold())
            if raw > 0:
                prefix = s[:raw]
            else:                                   # the words differ only by norm()
                n = len(claims.norm(s)[:at].split())
                prefix = " ".join(s.split()[:n])
            prefix = prefix.strip().rstrip(" ,;:-—–").strip()
            if prefix:
                out.append(prefix)
        return out
    return []


# ------------------------------------------------------------------ reveals
def entail_validator(asker):
    strict = bool(getattr(asker, "default_answerer", False))
    return lambda a: check_entail_answer(a, require_reveal=strict)


def episode_heading(p):
    """`Harbourlights S1E8 «Dirt and Stars» (aired 2026-10-04)` - a TVmaze piece's
    line as the second source sees it (the item's `title`)."""
    code = ""
    if p.get("season") is not None and p.get("episode") is not None:
        code = f"S{p['season']}E{p['episode']}"
    head = " ".join(x for x in (p.get("show"), code) if x)
    if p.get("title"):
        head = f"{head} «{p['title']}»".strip()
    if p.get("air_date"):
        head = f"{head} (aired {p['air_date']})"
    return head or None


def news_footing(pieces):
    """The topic's second-source pieces as the second source sees them -
    nothing of Wikipedia, nothing of the script: each RSS item as its
    headline and summary, each TVmaze episode description (CF-0636) as an
    item of the publication `TVmaze` whose headline is the episode
    (`episode_heading`) and whose summary is the description. The shape -
    `kind: news` - is the one the judge's prompt already knows, so the
    prompt and its cache keys stay as they were."""
    out = []
    for p in pieces.values():
        kind = p.get("kind")
        if kind == RSS_KIND:
            if not (p.get("title") or p.get("text")):
                continue
            out.append({"kind": "news", "publication": p.get("publication"),
                        "title": p.get("title"), "summary": p.get("text")})
        elif kind == TVMAZE_KIND:
            if not (p.get("text") or "").strip():
                continue
            out.append({"kind": "news", "publication": p.get("publication") or "TVmaze",
                        "title": episode_heading(p), "summary": p.get("text")})
    return out


def check_reveal(result, topic, pieces, revisions, asker, now=None, validate=None,
                 context=None):
    """Q10 for one reveal the judge said follows: the age of each Wikipedia
    quote under it (`reveal_age.quote_age`) and, unless all are stable, the
    same entailment question put against the topic's news items alone.

    {stable_hours, now, quotes[], age_h, stable, second_source,
    second_source_verdict?, second_source_reason?, second_source_key?,
    second_source_opinions?}"""
    now_t = reveal_age.parse_time(now) or reveal_age.dt.datetime.now(reveal_age.dt.timezone.utc)
    quotes, second_only, second_kinds = [], True, set()
    for s in result.get("supports") or []:
        if s.get("kind") != "quote":
            continue
        piece = pieces.get(s.get("source")) or {}
        if piece.get("kind") in SECOND_SOURCE_KINDS:
            second_kinds.add(piece.get("kind"))
            continue
        second_only = False
        age = reveal_age.quote_age(revisions, piece, s.get("quote"), now_t)
        age["source"] = s.get("source")
        quotes.append(age)
    ages = [q["age_h"] for q in quotes if q.get("age_h") is not None]
    out = {"rule": reveal_age.RULE, "stable_hours": reveal_age.STABLE_HOURS,
           "now": reveal_age.iso(now_t), "quotes": quotes,
           "age_h": min(ages) if ages else None,
           "stable": bool(quotes) and all(q["stable"] for q in quotes),
           "second_source": False}
    if out["stable"]:
        return out
    if second_only and any(s.get("kind") == "quote" for s in result.get("supports") or []):
        # The footing the judge already found sufficient is the second source
        # itself: the news, or TVmaze's episode description (CF-0636).
        out["second_source"] = True
        out["second_source_verdict"] = FOLLOWS
        out["second_source_reason"] = (
            "the claim's own footing is the topic's news items" if second_kinds <= {RSS_KIND}
            else "the claim's own footing is not Wikipedia's: "
                 + ", ".join("the topic's news items" if k == RSS_KIND
                             else "TVmaze's episode description" for k in sorted(second_kinds)))
        return out
    news = news_footing(pieces)
    if not news:
        out["second_source_reason"] = "the topic has no news item or TVmaze episode description to ask"
        return out
    answer, key, opinions = ask_entailment(asker, result.get("text"), news,
                                           validate or entail_validator(asker), context)
    out.update(second_source=answer["verdict"] == FOLLOWS,
               second_source_verdict=answer["verdict"],
               second_source_reason=answer.get("reason"), second_source_key=key,
               second_source_opinions=opinions)
    return out


# ------------------------------------------------------------------ verdict
def _violation(code, claim_id=None, detail=None, **extra):
    v = {"code": code, "claim_id": claim_id, "detail": detail, "fix": FIXES[code]}
    v.update(extra)
    return v


def judge_script(script, topic=None, pool=None, plan=None, extra_texts=None, asker=None,
                 jobs=DEFAULT_JOBS, revisions=None, now=None):
    """The full verdict on one script: the mechanics of CF-0552, the
    independent list of claims (Q13), the entailment of each declared
    claim (Q6) and, for a plot reveal that follows, the age of its Wikipedia
    text or a second source (Q10, CF-0554 - `revisions` is a
    `reveal_age.Revisions`, by default the batch's cached client; `now` the
    moment of the check, by default the clock). Raises CannotAsk when the
    model could not be asked.

    Returns {rule, action, mechanics, extracted[], verdicts[], violations[],
    struck[], fact_struck, refuse_now, asked, cached, opinion_calls,
    second_opinions, third_opinions}; each judged row carries `opinions[]`
    (CF-0579)."""
    mech = claims.check_claims(script, topic=topic, pool=pool, plan=plan,
                               extra_texts=extra_texts)
    report = {"rule": RULE, "action": ACTION_PASS, "model": asker.model if asker else None,
              "mechanics": mech, "extracted": [], "verdicts": [], "violations": [],
              "struck": [], "fact_struck": False, "refuse_now": False}
    declared = (script or {}).get(claims.CLAIMS_FIELD)
    declared = declared if isinstance(declared, list) else []
    texts = claims.viewer_texts(script, extra_texts)
    if asker is None:
        raise CannotAsk("no answer command")
    asked0, cached0 = asker.asked, asker.cached
    if any(c in FATAL_MECHANICS for c in claims.codes(mech)):
        # CF-0556: a topic without its text is refused whatever the model would
        # say - nothing is asked (the exam's coach-hale 1313Z spent 7 calls here).
        report.update(refuse_now=True, action=ACTION_FAIL, asked=0, cached=0,
                      **opinion_price([]))
        return report

    # Q13: the independent list, out of the finished text only.
    if texts:
        answer, key = asker.ask(KIND_EXTRACT, {"texts": texts}, extract_prompt(texts),
                                lambda a: check_extract_answer(a, texts))
        listed = [{"where": i["where"], "text": i["text"]} for i in answer["claims"]]
        for item, hits in zip(listed, match_extracted(listed, declared, script)):
            item["matched"] = hits
            report["extracted"].append(item)
            if not hits:
                report["violations"].append(_violation(
                    FAIL_UNDECLARED, None, f"{item['where']}: {item['text']!r}",
                    where=item["where"], text=item["text"]))
        report["extract_key"] = key

    # Q6: one call per declared claim whose mechanics hold.
    failed_mech = {r.get("claim_id") for r in mech["results"] if r.get("state") == "fail"}
    todo = []
    for r in mech["results"]:
        if r.get("claim_id") in failed_mech or r.get("state") == "fail":
            report["verdicts"].append({"claim_id": r.get("claim_id"), "text": r.get("text"),
                                       "where": r.get("where"), "state": STATE_MECHANICS})
            continue
        footing = footing_of(r, claims.support_pieces(topic))
        if not footing:
            report["verdicts"].append({"claim_id": r.get("claim_id"), "text": r.get("text"),
                                       "where": r.get("where"), "state": STATE_PENDING,
                                       "reason": "no footing to show the judge yet (a shot "
                                                 "not looked up)"})
            continue
        todo.append((r, footing))

    validate = entail_validator(asker)

    pairs = script_pairs(script)

    def context_of(r):
        return claim_context(r.get("text"), r.get("where"), texts, pairs)

    def one(item):
        r, footing = item
        answer, key, opinions = ask_entailment(asker, r.get("text"), footing, validate,
                                               context_of(r))
        return r, answer, key, opinions

    with cf.ThreadPoolExecutor(max_workers=max(1, int(jobs or 1))) as ex:
        answered = list(ex.map(one, todo))
    by_id = {c.get("claim_id"): c for c in declared if isinstance(c, dict)}
    pieces = claims.support_pieces(topic)
    for r, answer, key, opinions in answered:
        v = answer["verdict"]
        row = {"claim_id": r.get("claim_id"), "text": r.get("text"), "where": r.get("where"),
               "verdict": v, "reason": answer.get("reason"), "key": key,
               "state": STATE_SUPPORTED if v == FOLLOWS else STATE_STRUCK,
               "opinions": opinions}
        ctx = context_of(r)
        if ctx:
            row["context"] = ctx                    # CF-0728: what the judge read it with
        if v != FOLLOWS and (answer.get("missing") or "").strip():
            row["missing"] = answer["missing"]
        if answer.get("reveal") is not None:
            row["reveal_claim"] = answer["reveal"]
        report["verdicts"].append(row)
        too_fresh = False
        if v == FOLLOWS and answer.get("reveal") is True:
            if revisions is None:
                revisions = reveal_age.revisions_for(asker.cache_dir.parent / WIKIPEDIA_CACHE)
            row["reveal"] = check_reveal(r, topic, pieces, revisions, asker, now, validate, ctx)
            too_fresh = not (row["reveal"]["stable"] or row["reveal"]["second_source"])
            if too_fresh:
                row["state"] = STATE_STRUCK
        if too_fresh:
            claim = by_id.get(r.get("claim_id")) or {}
            fact = is_fact_claim(claim, script)
            row["fact_claim"] = fact
            report["struck"].append({"claim_id": r.get("claim_id"), "where": r.get("where"),
                                     "text": r.get("text"), "fact_claim": fact})
            report["fact_struck"] = report["fact_struck"] or fact
            rv = row["reveal"]
            report["violations"].append(_violation(
                FAIL_REVEAL_TOO_FRESH, r.get("claim_id"),
                f"{r.get('where')}: {r.get('text')!r} - Wikipedia text "
                f"{rv.get('age_h') if rv.get('age_h') is not None else '?'} h old "
                f"({', '.join(sorted({q['state'] for q in rv['quotes']})) or 'no Wikipedia quote'}"
                f"), no second source of the topic (a news item, TVmaze's episode description) "
                f"says it", fact_claim=fact))
        elif v != FOLLOWS:
            claim = by_id.get(r.get("claim_id")) or {}
            fact = is_fact_claim(claim, script)
            row["fact_claim"] = fact
            report["struck"].append({"claim_id": r.get("claim_id"), "where": r.get("where"),
                                     "text": r.get("text"), "fact_claim": fact})
            report["fact_struck"] = report["fact_struck"] or fact
            report["violations"].append(_violation(
                FAIL_NOT_ENTAILED if v == DOES_NOT_FOLLOW else FAIL_NOT_ENOUGH,
                r.get("claim_id"), f"{r.get('where')}: {r.get('text')!r} - {answer.get('reason')}"
                + (f" Missing: {row['missing']}" if row.get("missing") else ""),
                fact_claim=fact))
    order = {c.get("claim_id"): i for i, c in enumerate(declared) if isinstance(c, dict)}
    report["verdicts"].sort(key=lambda x: order.get(x.get("claim_id"), 1 << 30))

    mech_codes = claims.codes(mech)
    report["refuse_now"] = report["fact_struck"] or any(c in FATAL_MECHANICS for c in mech_codes)
    report.update(opinion_price(report["verdicts"]))
    report["asked"] = asker.asked - asked0
    report["cached"] = asker.cached - cached0
    if mech["action"] != ACTION_PASS or report["violations"]:
        report["action"] = ACTION_FAIL
    return report


def opinion_price(verdicts):
    """CF-0579: what the second opinions cost - {opinion_calls, second_opinions,
    third_opinions} over the verdict rows (a reveal's news question counted
    with its claim). The calls are in `asked` / `cached` too."""
    calls = second = third = 0
    for row in verdicts or []:
        for ops in (row.get("opinions"), (row.get("reveal") or {}).get("second_source_opinions")):
            k = extra_calls(ops)
            calls += k
            second += k >= 1
            third += k >= 2
    return {"opinion_calls": calls, "second_opinions": second, "third_opinions": third}


def all_codes(report):
    """Every violation code of the verdict, the mechanics' first."""
    return claims.codes(report.get("mechanics")) + [
        v.get("code") for v in report.get("violations") or []]


# ------------------------------------------------------------ batch reading
def cache_dir_of(batch_file):
    return Path(batch_file).resolve().parent / CACHE_REL


def judge_batch_file(path, script_id=None, extra_texts=None, asker=None, jobs=DEFAULT_JOBS,
                     root=None, revisions=None, now=None):
    """[(script_id, report)] for the scripts of one 03. The reveals' history
    is read through `<batch>/work/wikipedia-cache/` unless `revisions` is
    given."""
    path = Path(path)
    data = claims._read(path)
    if not isinstance(data, dict):
        raise FileNotFoundError(f"{path}: not a readable 03")
    batch = path.resolve().parent
    topics = claims.topics_of(batch)
    out = []
    if revisions is None:
        revisions = _LazyRevisions(batch / "work" / WIKIPEDIA_CACHE)
    for s in data.get("scripts") or []:
        if script_id and s.get("script_id") != script_id:
            continue
        out.append((s.get("script_id"), judge_script(
            s, topic=topics.get(s.get("topic_id")),
            pool=claims.pool_of(s, batch, root or claims.ROOT),
            plan=claims.plan_of(s, batch), extra_texts=extra_texts, asker=asker, jobs=jobs,
            revisions=revisions, now=now)))
    return out


class _LazyRevisions:
    """A `reveal_age.Revisions` made on first use - a batch with no reveal
    builds no client."""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self._real = None

    def __getattr__(self, name):
        if self._real is None:
            self._real = reveal_age.revisions_for(self.cache_dir)
        return getattr(self._real, name)


def _price_note(report):
    if not report.get("opinion_calls"):
        return ""
    return (f" ({report['opinion_calls']} second-opinion call(s): "
            f"{report.get('second_opinions', 0)} re-asked, "
            f"{report.get('third_opinions', 0)} split)")


def render(script_id, report):
    mech = report["mechanics"]
    n_ok = sum(1 for v in report["verdicts"] if v.get("state") == STATE_SUPPORTED)
    lines = [f"{'ok  ' if report['action'] == ACTION_PASS else 'FAIL'} {script_id}: "
             f"{mech['claims']} declared, {n_ok} follow, {len(report['extracted'])} listed by "
             f"the reader, {len(report['violations']) + len(mech['violations'])} violation(s)"
             f"{' - the fact itself has no footing' if report['fact_struck'] else ''}"
             f"{_price_note(report)}"]
    for v in mech["violations"]:
        who = f" {v['claim_id']}" if v.get("claim_id") else ""
        lines.append(f"  {v['code']}{who}: {v.get('detail') or ''}")
        lines.append(f"      -> {v['fix']}")
    for v in report["violations"]:
        who = f" {v['claim_id']}" if v.get("claim_id") else ""
        lines.append(f"  {v['code']}{who}: {v.get('detail') or ''}")
        lines.append(f"      -> {v['fix']}")
    for p in mech["pending"]:
        lines.append(f"  pending {p['code']} {p.get('claim_id') or ''}: {p.get('detail') or ''}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file")
    ap.add_argument("--script-id")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--answer-cmd", default=None,
                    help=f"the answer command template (default ${ANSWER_CMD_ENV}, else "
                         f"{DEFAULT_ANSWERER.name})")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--cache-dir", default=None, help=f"default <batch>/{CACHE_REL}")
    ap.add_argument("--now", default=None,
                    help="the moment of the check for the reveals' 6 hours (ISO, UTC; "
                         "default the clock) - a replay passes the batch's own time")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    extra = {k: v for k, v in (("title", args.title), ("description", args.description)) if v}
    asker = Asker(args.cache_dir or cache_dir_of(args.batch_file), args.answer_cmd,
                  args.model, args.timeout)
    try:
        results = judge_batch_file(args.batch_file, args.script_id, extra, asker, args.jobs,
                                   now=args.now)
    except FileNotFoundError as exc:
        print(f"CLAIM JUDGE: cannot answer - {exc}", file=sys.stderr)
        return 3
    except CannotAsk as exc:
        print(f"CLAIM JUDGE: cannot answer - {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({sid: rep for sid, rep in results}, ensure_ascii=False, indent=2))
    else:
        for sid, rep in results:
            print(render(sid, rep))
        print(f"({asker.asked} call(s) asked, {asker.cached} answered from the cache)")
    if not results:
        print("CLAIM JUDGE: no script to judge", file=sys.stderr)
        return 3
    return 0 if all(r["action"] == ACTION_PASS for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
