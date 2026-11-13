#!/usr/bin/env python3
"""CF-0553: the independent check of what a script says, and the writer's
one edit - the stage's half of `shared/factrule/claim_judge.py`.

**Why.** CF-0552 made the writer declare every claim in `claims[]` with a
verbatim quote of the topic's support_text, and `claims.py` checks that the
quote is there. Whether the quote *says* the claim, and whether the writer
declared every claim, must not be the writer's word (the grill of 2026-10-05,
CF-0546: the accepted `harbourlights` 0701Z said "Zorvath is behind the kill" -
Hal Garrett is killed by Sheriff Kerry Kane; `east-of-eden` 0701Z said "months
before anyone outside the production knew" while Variety had announced the
cast). So the root's judge makes two kinds of model call, each with no
context of the writer:

* Q13 - a reader lists every checkable claim of the FINISHED text (hook,
  commentary, payoff, `production_fact.on_screen`, and the title / the
  description when handed in with `--title` / `--description`); a listed
  claim no declared claim covers is `claim_undeclared`;
* Q6 - a judge (Sonnet), one call per declared claim, sees the claim and its
  footing only and answers follows / does_not_follow / not_enough
  (`claim_not_entailed` / `claim_not_enough`).

The mechanics of CF-0552 run first in the same verdict; a claim whose quote is
not in its piece is not sent to the judge.

**The ladder** (Q3 - no footing, no claim; one edit):

    ok        `claims_check.action == "pass"`; nothing to do.
    REWRITE   (exit 1) the first failure: the struck claims and the
              undeclared ones are printed - rewrite the text WITHOUT them
              (never "reportedly": `hedged_statement`), take them out of
              `claims[]`, run again. `failed_attempts` becomes 1.
    UNCHANGED (exit 1) the text and `claims[]` are the ones the last run sent
              back (CF-0430): nothing is judged, nothing is spent.
    REWORD    (exit 1) the first failure, and a struck claim is the video's
              own fact (`production_fact.beat_text` / `on_screen`: no video
              without it) - CF-0580. The CF-0556 exam: Endgame's "announced as
              one single project" (Feige: "two distinct" films) and Harbourlights'
              on-screen "Berlanti pitched" (the source: "announced that he was
              developing") were true facts worded past their quotes, and each
              refused its whole video. So the fact is not struck: the one edit
              is a rewording of the SAME fact on the SAME quote in the quote's
              words (its verb, its qualifiers, no cause it does not state);
              the record carries `fact_reword` (the claims and their quotes).
              Run again: the reworded fact is judged like any claim, and if it
              still does not follow, the topic is refused. Other struck claims
              of the run are taken out in the same edit, as under REWRITE.
    DELETE    (exit 1) CF-0807: the second failure, and every strike left is a
              declared claim that does not follow (`claim_not_entailed`,
              `claim_not_enough`, `reveal_too_fresh`) - not the video's own
              fact, nothing undeclared, no mechanics - in a spoken section or
              on a graphic. One more edit that ONLY deletes: the sentences
              holding the struck claims, the struck graphics whole, the claims
              that stood on them. The record carries `deletion_pass` (what to
              delete and a snapshot of the text); the next run holds the edit
              to it mechanically - a section is the old one with whole
              sentences out, a graphic / a claim is kept as it was or removed,
              `production_fact` untouched - and refuses the topic when the
              edit did anything else; then the judge reads it again and a
              failure refuses the topic. `deletion_pass.removed` says what went.
              The text is shorter: run check_narration_budget.py again.
    PHRASE    (exit 1) CF-0883: the second failure, and all that is left is
              `claim_undeclared` on the hook or the payoff - every declared
              claim followed, nothing struck, no mechanics (the Reel funnel of
              2026-10-20..27 lost 4 topics so: "Here's what nobody tells you
              about Tulsa King ...", "the number one opening is only the first
              answer"). One more edit of THOSE sentences only: said without the
              statement, or kept and declared with a verbatim quote. The record
              carries `phrase_pass` (the sentences and a snapshot); the next
              run holds every other sentence, graphic, `production_fact` and
              the claims of other sections to it mechanically and refuses the
              topic when the edit went further; then the judge reads the whole
              text again and a failure refuses the topic.
              CF-0886: the same edit for a hook / payoff claim struck
              `claim_not_enough` that is its section's only sentence (DELETE
              would empty the section; Reel 27.10 lost "Six things about Tulsa
              King to know before you argue about the casting." so): say only
              what its quote says, or say it without the statement. A struck
              video's own fact takes it only as its one rewording (CF-0580 -
              never reworded before) and only when the fact on screen followed.
              Before any rung (CF-0883, `_hook_frame.py`): an undeclared hook
              statement that opens on one of the channel's hype opener
              formulas is read without the formula's words, and a bare title
              with a subtitle colon ("Vanguards: Doomsday") as a name, each
              matched by the root's rule to a claim that FOLLOWED - recorded
              under `not_claims`; what still says more stays undeclared.
    REFUSE    (exit 4) the second failure of an edited script (a reworded
              fact that still does not follow among them) - or at once, when
              the fact cannot be reworded: it is a reveal too fresh to stand
              (`reveal_too_fresh` - no wording ages the text), the script was
              already edited once when its fact was struck, or the topic has no
              support text: with `--write` the topic leaves `scripts[]` for
              `skipped[]` as `claim_unsupported`, stage `scripts`, the record
              beside it.
    FROZEN    (CF-0902) the round after the frame judge is on (`01b` carries a
              substitution at `frame_judge_refusal`) and the script is not one
              of its substitute topics': a first-pass script compliance, the
              Editor and the judge already decided. Nothing is asked and its
              record is not touched - a later plan under the same words used to
              stamp a failing record nobody would ever rewrite.
    NOT OWNED (CF-0933) the reserve round before compliance is on (`01b`
              carries a substitution at `researcher_refusal`, the late round
              alike) and the script is not one of its substitute topics': a
              first-pass script whose records its own step 6b settled. The
              free mechanics of CF-0552 still run against its plan and the
              line says what they find - `NOT OWNED <id> (fails:
              shot_not_under_words c7, ...)` - but nothing is asked, nothing is
              written and the exit code does not move (example-tech
              `2026-11-11T0956Z`: that round stamped a failing record onto
              nvidia's first-pass script and compliance blocked the video).
    SKIPPED   the script's topic already stands in `skipped[]` (an earlier
              gate refused it - `check_source_hosts.py` runs before this one,
              CF-0827): nothing is asked and nothing is written for it.
    FAIL      (exit 1) `claims` missing or not a list - the field, not a
              verdict; nothing is judged and no attempt is spent.
              Also (CF-0671) `attribution_forbidden`: the text carries a
              phrasing an outlet's terms forbid in an AI product (NASA: "according
              to NASA", "NASA says / confirms", "NASA-approved" ...; the bans are
              the channel's `fact-sources.json` -> `ai_output_terms`). Matched
              before the judge, with no model call, in what the viewer hears and
              reads (`check_production_fact.attribution_fields`, the title and
              the description included) on every run - so a REWORD or a REWRITE
              that writes "according to NASA" back in is caught on the rerun.
              It is a wording, not a claim: nothing is judged, no attempt is
              spent, the topic stays; say it in the video's voice and run again.
              Also (CF-0690) `api_demo_answer_is_fact`: a model's answer
              shown through its API (an `api_chat` graphic, the topic's
              `api_demo_record`) is never a fact of the video. Matched before
              the judge, with no model call (`api_demo_footing`): a claim
              on the chat (`where: graphic:<chat id>`), a claim whose quote
              takes words from the model's answer in the Trend Hunter's
              `api_demo_record` piece, and the video's own fact
              (`production_fact`, `claim_judge.is_fact_claim`) footed on
              ANY piece marked `not_a_fact` (the API demo's or the own
              capture's record). The report of the demo - "we sent Gemini
              2.5 Flash one question through the Gemini API", quoted from
              the piece's first sentence - stands as any claim. Nothing is
              judged, no attempt is spent, the topic stays; take the claim
              (and its words) out, or say it as the report, and run again.
              Also (CF-0807), before the judge and with no model call, the
              mechanics of CF-0552 (`claim_text_not_in_field` ...) and
              `claim_subject_pronoun` (a claim sentence that opens on It /
              These / That / This / Those / They / Both / "Now it", after a
              list numeral: name the subject). No attempt is spent; a script
              has FREE_FIXES_ALLOWED such runs, then it goes to the judge as
              before (`free_fixes` on the record).
    exit 3    the question could not be put (no batch, no judge in the root,
              or the model could not be asked - `NOT_LOGGED_IN` when the
              console claude has no session). Nothing is written.

With `--write` the record goes onto every judged script as `claims_check` -
the judge's answer verbatim (the root's contract for `03` reads it) plus
`failed_attempts`, `rewrites_allowed` and `script_hash` (the spoken text,
the anchors, the on-screen wording, the title / description handed in and
`claims[]`: declaring a missed claim is an edit).

The model calls are cached in `<batch>/work/claim-judge-cache/` by the hash
of each request, so a rerun on unchanged words - after a later gate's
rewrite elsewhere, or at step 6b - asks only what changed.

Usage:

    python3 scripts/check_claims.py <03-content-researcher.json> --write
        [--script-id ID ...] [--title T --description D] [--answer-cmd CMD]
        [--model sonnet]

`--script-id` (repeatable) judges only the scripts named; every other one is
passed over silently and its record is not touched (CF-0933: step 6b's
`plan_check_loop.py` judges the claims of the one script whose plan it just
built).
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _runlog import runlog  # noqa: E402

import _rewrite_guard as rg  # noqa: E402
from check_narration_budget import find_root  # noqa: E402
import check_production_fact as cpf  # noqa: E402 - CF-0671: the outlets' terms
import _claim_ladder as ladder  # noqa: E402 - CF-0807: pronoun lint, deletion pass
import _hook_frame as hf  # noqa: E402 - CF-0883: the opener's words and a title are no claim
import hook_openers as ho  # noqa: E402 - CF-0883: the channel's opener formulas
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197
import _judge_round as jr  # noqa: E402 - CF-0902: the first pass is decided after the judge

SHARED_REL = Path("shared") / "factrule" / "claim_judge.py"
CLAIMS_FIELD = "claims"                 # = claims.CLAIMS_FIELD
RECORD_KEY = "claims_check"             # = claims.CHECK_FIELD = claim_judge.CHECK_FIELD
# The code the funnel and the root's contract know (shared/runlog/funnel.py
# FUNNEL_CODES, tests/test_pipeline_contracts.py SKIP_CODES).
SKIP_REASON_CODE = "claim_unsupported"  # = claim_judge.SKIP_REASON_CODE
FUNNEL_STAGE = "scripts"
REWRITES_ALLOWED = 1

EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED = 0, 1, 3, 4
# CF-0580: the verdicts a rewording in the source's words can answer. A reveal
# too fresh (CF-0554) is about the age of the text, not its words.
REWORDABLE_CODES = ("claim_not_entailed", "claim_not_enough")  # = claim_judge.FAIL_NOT_*
FACT_REWORD_KEY = "fact_reword"
FACT_REWORDED_KEY = "fact_reworded"   # the last run's `fact_reword`, kept on the rerun
ACTION_PASS, ACTION_FAIL = "pass", "fail"

# CF-0807: what is found without a model call spends no attempt. The mechanics
# of CF-0552 (`claims.check_claims` - claim_text_not_in_field, quote_not_in_source,
# hedged_statement ...; all but the fatal `topic_without_support_text`) and the
# pronoun lint run before the judge; a finding there is printed as `FAIL`,
# nothing is asked, `failed_attempts` does not move. The 022 slip of
# example-tech/2026-10-19T0844Z: claims passed, the hook was reworded for
# check-hook-opener, the claim text no longer matched the hook, and that pure
# mechanics run took the topic as a second failure.
# The loop guard: a script gets FREE_FIXES_ALLOWED such runs in all (counted on
# the record as `free_fixes`, never reset). Past them the pre-check is not run
# and the script goes to the judge as before CF-0807 - its mechanics then
# count as a failure, and a pronoun is the judge's to read.
FREE_FIXES_KEY = "free_fixes"
FREE_FIXES_ALLOWED = 3
PREJUDGE_KEY = "prejudge"              # the record of a run stopped before the judge
PRONOUN_CODE = ladder.PRONOUN_CODE     # "claim_subject_pronoun"
# CF-0807 (the user, 2026-10-19 14:17): after the one rewrite, one edit that only
# deletes - when every strike left is a claim that does not follow.
DELETION_KEY = ladder.DELETION_KEY     # "deletion_pass"
# CF-0883: after the one rewrite, when all that is left is an undeclared
# statement on the hook or the payoff, one edit of those sentences only.
PHRASE_KEY = ladder.PHRASE_KEY         # "phrase_pass"
RELIEF_KEY = hf.RELIEF_KEY             # "not_claims"
CARRIED_KEYS = (FACT_REWORD_KEY, FACT_REWORDED_KEY, DELETION_KEY, PHRASE_KEY)


# CF-0690: "a demo via API" - the model's answer is never our fact.
API_DEMO_CODE = "api_demo_answer_is_fact"   # = claims.FAIL_API_DEMO_IS_FACT = api_demo.FAIL_ANSWER_IS_FACT
API_DEMO_PIECE_KIND = "api_demo_record"     # = trend-hunter api_demo_text.KIND
API_DEMO_PIECE_SOURCE = "api_demo"          # = trend-hunter api_demo_text.SOURCE
NOT_A_FACT_KEY = "not_a_fact"               # the factory's own records (api demo, own capture)
ANSWER_HEAD = "answered: «"                 # api_demo_text.piece: "<display> answered: «<answer>»."
API_DEMO_RU = {
    "chat": "Утверждение опирается на чат «через API» - ответ модели не факт ролика.",
    "answer": "Фраза ролика опирается на ответ модели из демо «через API» - это вывод модели, "
              "а не факт.",
    "fact": "Факт ролика опирается на собственную запись фабрики (not_a_fact) - это не факт.",
}
API_DEMO_FIX = {
    "chat": "a chat is on the call's record, never on claims: take the claim `where: "
            "graphic:<chat id>` out (the chat's words are checked by check_graphics.py)",
    "answer": "the narration reports the demo (\"we asked <model> through the Gemini API\", "
              "quoted from the piece's first sentence) and never says what the answer says as "
              "true: take the sentence and its claim out, or reword it as the report",
    "fact": "the video's own fact stands on a primary source of the channel's list "
            "(fact-sources.json), never on the factory's own record of a demo or a capture: "
            "take the fact from step 2's candidates",
}


def is_api_demo_piece(piece):
    return isinstance(piece, dict) and (piece.get("kind") == API_DEMO_PIECE_KIND
                                        or piece.get("source") == API_DEMO_PIECE_SOURCE)


def report_part(piece):
    """The words of a `not_a_fact` piece that are the factory's report: all
    of it, except the model's answer of an `api_demo_record` piece - the text
    from "<display> answered: «" on (found after the prompt, so a prompt that
    says "answered" does not move it)."""
    text = (piece or {}).get("text") or ""
    if not is_api_demo_piece(piece):
        return text
    after = 0
    prompt = piece.get("prompt")
    if isinstance(prompt, str) and prompt:
        at = text.find(f"«{prompt}»")
        if at >= 0:
            after = at + len(prompt) + 2
    at = text.find(ANSWER_HEAD, after)
    return text if at < 0 else text[:at + len(ANSWER_HEAD) - 1]


def api_demo_footing(script, topic, cl, is_fact=None):
    """CF-0690: `[violation]` of the claims that make the model's answer (or
    the factory's own record) a fact: {code, claim_id, detail, fix, text_ru}.
    `cl` - the root's claims module; `is_fact(claim, script)` - the judge's
    `is_fact_claim` (default: only `on_screen` is the fact)."""
    claims_list = (script or {}).get(CLAIMS_FIELD)
    if not isinstance(claims_list, list):
        return []
    pieces = cl.support_pieces(topic)
    chats = cl.api_chat_wheres(script)
    out = []

    def bad(kind, claim, detail):
        out.append({"code": API_DEMO_CODE, "claim_id": claim.get("claim_id"),
                    "detail": detail, "fix": API_DEMO_FIX[kind], "text_ru": API_DEMO_RU[kind]})

    for claim in claims_list:
        if not isinstance(claim, dict):
            continue
        where = claim.get("where")
        if where in chats:
            bad("chat", claim, f"{where} is an api_chat - the model's answer on our record")
            continue
        for sup in claim.get("support") or []:
            if not (isinstance(sup, dict) and "quote" in sup):
                continue
            piece = pieces.get(sup.get("source"))
            if not (isinstance(piece, dict) and piece.get(NOT_A_FACT_KEY) is True):
                continue
            fact = is_fact(claim, script) if is_fact else where == "on_screen"
            if fact:
                bad("fact", claim, f"the video's own fact {claim.get('text')!r} stands on "
                                   f"{piece.get('id')} ({piece.get('kind')}, not_a_fact)")
                break
            if is_api_demo_piece(piece):
                q = cl.norm_quote(sup.get("quote") or "")
                if q and q in cl.norm(piece.get("text") or "") \
                        and q not in cl.norm(report_part(piece)):
                    bad("answer", claim, f"{where}: {claim.get('text')!r} quotes the model's "
                                         f"answer in {piece.get('id')}: {sup.get('quote')!r}")
                    break
    return out


class CannotAnswer(RuntimeError):
    """The question could not be put. Never a verdict on a script."""


def load_judge(root=None):
    """The root's `claim_judge.py`, loaded by path; this repo keeps no copy."""
    root = Path(root) if root else find_root()
    path = root / SHARED_REL
    if not path.is_file():
        raise CannotAnswer(f"{path} not found - the claim judge lives in the factory root "
                           f"and this repository keeps no copy of it (CF-0553)")
    spec = importlib.util.spec_from_file_location("factory_claim_judge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


def claims_hash(script, extra=None):
    """`sha256:` of what the writer controls here - the spoken text, the
    anchors and (CF-0689) the graphics through `rg.script_hash`, the claims,
    the plate. An edited graphic is an edit: its lines are viewer text the
    judge reads."""
    pf = script.get("production_fact")
    blob = json.dumps({"script": rg.script_hash(script), "claims": script.get(CLAIMS_FIELD),
                       "on_screen": pf.get("on_screen") if isinstance(pf, dict) else None,
                       "extra": extra or {}},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def previous_failures(script):
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def unchanged(script, extra=None):
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict) or record.get("action") != ACTION_FAIL:
        return None
    if record.get(rg.HASH_KEY) != claims_hash(script, extra):
        return None
    return record


def violation_lines(record, reword=False):
    out = []
    for v in (record.get("mechanics") or {}).get("violations") or []:
        who = f" {v['claim_id']}" if v.get("claim_id") else ""
        out.append(f"      {v['code']}{who}: {v.get('detail') or ''}")
        out.append(f"        -> {v.get('fix')}")
    for v in record.get("violations") or []:
        who = f" {v['claim_id']}" if v.get("claim_id") else ""
        fact = " [the video's own fact]" if v.get("fact_claim") else ""
        out.append(f"      {v['code']}{who}{fact}: {v.get('detail') or ''}")
        out.append("        -> not struck: reword it in its quote's words (below, CF-0580)"
                   if reword and v.get("fact_claim") else f"        -> {v.get('fix')}")
    return out


def codes_of(record):
    return sorted({v.get("code") for v in ((record.get("mechanics") or {}).get("violations")
                                           or []) + (record.get("violations") or [])})


def fact_violations(record):
    return [v for v in record.get("violations") or [] if v.get("fact_claim")]


def fact_rewordable(record, judge=None):
    """CF-0580: the judge refused the video because its own fact does not
    follow - and only for that: every fact violation is a wording verdict
    (not entailed / not enough), the topic has its text. Then one rewording
    in the quote's words is the edit, not a refusal."""
    if not record.get("fact_struck"):
        return False
    codes = getattr(judge, "FAIL_NOT_ENTAILED", None), getattr(judge, "FAIL_NOT_ENOUGH", None)
    codes = tuple(c for c in codes if c) or REWORDABLE_CODES
    fatal = tuple(getattr(judge, "FATAL_MECHANICS", ()) or ())
    if any(c in fatal for c in codes_of({"mechanics": record.get("mechanics")})):
        return False
    facts = fact_violations(record)
    return bool(facts) and all(v.get("code") in codes for v in facts)


def fact_reword_entry(script, record):
    """What the rewording has to keep: each struck fact claim with the quotes
    it rests on (the writer rewords against these, it does not change them)."""
    by_id = {c.get("claim_id"): c for c in script.get(CLAIMS_FIELD) or [] if isinstance(c, dict)}
    out = []
    for v in fact_violations(record):
        claim = by_id.get(v.get("claim_id")) or {}
        out.append({"claim_id": v.get("claim_id"), "where": claim.get("where"),
                    "text": claim.get("text"), "code": v.get("code"),
                    "quotes": [{"source": s.get("source"), "quote": s.get("quote")}
                               for s in claim.get("support") or []
                               if isinstance(s, dict) and s.get("quote")]})
    return {"rule": "CF-0580", "claims": out}


def batch_terms(data, root):
    """CF-0671: the batch's channel's outlets' terms for AI output, [] for a
    batch that names no channel (the channel is check_production_fact's to
    demand). A block that cannot be matched is not a verdict: CannotAnswer."""
    try:
        # a former id, frozen in an old batch, resolved at the door (CF-0197)
        channel = resolve_channel(data["channel"], root) if data.get("channel") else None
        if not channel:
            return []
        return cpf.channel_data.attribution_terms(channel, root)
    except cpf.channel_data.ChannelDataError as exc:
        raise CannotAnswer(f"the outlets' terms of the batch's channel cannot be had "
                           f"(CF-0671): {exc}")


def reword_lines(entry):
    out = ["      the video's own fact, worded past its quote - reword it ONCE in the quote's "
           "words (its verb, its qualifiers, no cause or \"first\" / \"one\" it does not "
           "state), the same fact on the same quote, everywhere it stands (commentary, "
           "beat_text, on_screen, production_fact.text, the claim's text). The quote's "
           "words, not its attribution: never \"according to <outlet>\" / \"<outlet> "
           "says / confirms\" - an outlet's terms may forbid it (CF-0671, "
           "`attribution_forbidden`):"]
    for c in entry.get("claims") or []:
        out.append(f"        {c.get('claim_id')} ({c.get('where')}): {c.get('text')!r}")
        for q in c.get("quotes") or []:
            out.append(f"          quote [{q.get('source')}]: {q.get('quote')!r}")
    return out


def refusal_reason(script, record, now=False):
    codes = ", ".join(codes_of(record))
    struck = "; ".join(repr(s.get("text")) for s in record.get("struck") or [])
    deletion = record.get(DELETION_KEY) if isinstance(record.get(DELETION_KEY), dict) else {}
    phrase = record.get(PHRASE_KEY) if isinstance(record.get(PHRASE_KEY), dict) else {}
    if phrase.get("state") == ladder.STATE_NOT_PHRASE:
        return (f"{script.get('script_id')}: the one phrase pass (CF-0883) went past its "
                f"sentences - " + "; ".join(phrase.get("problems") or []) + ". After the one "
                f"rewrite the only edit left redoes the hook / payoff sentences it names; the "
                f"topic is dropped rather than voiced.")
    if phrase.get("state") == ladder.STATE_JUDGED:
        return (f"{script.get('script_id')}: a claim of the finished text has no footing "
                f"({codes}) after the one rewrite and the one phrase pass (CF-0883) - "
                f"{struck or codes}. A claim the topic's text does not say is not voiced; the "
                f"topic is dropped rather than voiced.")
    if deletion.get("state") == ladder.STATE_NOT_DELETION:
        return (f"{script.get('script_id')}: the one deletion pass (CF-0807) was not a "
                f"deletion - " + "; ".join(deletion.get("problems") or []) + ". After the one "
                f"rewrite the only edit left takes whole sentences out and adds nothing; the "
                f"topic is dropped rather than voiced.")
    if deletion.get("state") == ladder.STATE_JUDGED:
        why = (f"a claim still has no footing after the one rewrite and the one deletion pass "
               f"(CF-0807) - {struck or codes}")
    elif record.get("fact_struck") and record.get(FACT_REWORDED_KEY):
        why = (f"the video's own fact still does not follow from its quote after its one "
               f"rewording in the source's words (CF-0580) - {struck}")
    elif now and record.get("fact_struck"):
        why = (f"the video's own fact has no footing - the judge read its quote and it does "
               f"not say {struck}; there is no video to rewrite around it")
    elif now:
        why = "the topic has no support text - no claim of it has a footing"
    else:
        why = "the second failure came after the one rewrite"
    return (f"{script.get('script_id')}: a claim of the finished text has no footing ({codes})"
            f" - {why}. A claim the topic's text does not say is not voiced, and not softened "
            f"to \"reportedly\" either (CF-0553: the accepted harbourlights said \"Zorvath is "
            f"behind the kill\"); the topic is dropped rather than voiced.")


def deletion_lines(entry):
    out = ["      delete, and nothing else (CF-0807): take out each sentence below whole, "
           "each graphic below whole (and its graphic anchor), and every `claims[]` entry "
           "that stood on what you deleted; keep every other sentence, graphic, claim and "
           "`production_fact` exactly as it is:"]
    for where, sents in sorted((entry.get("sentences") or {}).items()):
        for sentence in sents:
            out.append(f"        {where}: {sentence!r}")
    for gid in entry.get("graphics") or []:
        out.append(f"        graphic:{gid} (the whole entry)")
    return out


def deletion_summary(removed):
    n = sum(len(v) for v in (removed.get("sentences") or {}).values())
    return (f"{n} sentence(s), {len(removed.get('graphics') or [])} graphic(s) and "
            f"{len(removed.get('claims') or [])} claim(s) removed")


def phrase_lines(entry):
    out = ["      redo these sentences, and nothing else (CF-0883): say each one WITHOUT the "
           "statement listed - the subject's name and what the video goes on to show, with "
           "no \"nobody\" / \"everyone\" / \"only\" / \"first\" / \"the real reason\" it "
           "cannot quote - or keep the statement and declare it in `claims[]` (where: the "
           "section) with a verbatim quote of the topic's support_text that says it. Never "
           "\"reportedly\"; never a fact the support_text does not state. Every other "
           "sentence, graphic, claim of another section and `production_fact` stays exactly "
           "as it is; the whole text is judged again and a failure refuses the topic:"]
    for p in entry.get("phrases") or []:
        out.append(f"        {p.get('where')}: undeclared {p.get('text')!r}")
    if entry.get("strikes"):
        out.append("      a claim below is the only sentence of its section and its quote does "
                   "not say all of it (CF-0886): say only what the quote says, in the quote's "
                   "words (its verb, its qualifiers - no \"long before\", \"all\", \"six\", "
                   "\"most talked-about\" it does not state), and make the claim's `text` the "
                   "same words - or say the sentence without the statement and take the claim "
                   "out. The video's own fact keeps the same fact on the same quote:")
    for c in entry.get("strikes") or []:
        fact = " [the video's own fact]" if c.get("fact_claim") else ""
        out.append(f"        {c.get('where')}: {c.get('claim_id')}{fact} {c.get('code')} "
                   f"{c.get('text')!r}")
        for q in c.get("quotes") or []:
            out.append(f"          quote [{q.get('source')}]: {q.get('quote')!r}")
    for where, sents in sorted((entry.get("sentences") or {}).items()):
        for sentence in sents:
            out.append(f"          redo {where}: {sentence!r}")
    return out


def batch_openers(data, root):
    """CF-0883: the channel's opener formulas (`[]` for a batch that names no
    channel or a channel with none - then no formula is read away)."""
    try:
        channel = resolve_channel(data["channel"], root) if data.get("channel") else None
        if not channel:
            return []
        return ho.library_of(ho.load_config(channel, root))[0]
    except (ho.ConfigError, OSError, ValueError, KeyError):
        return []


def skipped_topics(data):
    """{topic_id: reason_code} of every topic the batch's `skipped[]` already
    holds at the scripts stage (CF-0827). A gate that refuses a topic moves it
    out of `scripts[]` with `--write`; this is the guard for the file where it
    did not (or a script was written back by hand): the judge is paid per
    call, and a topic that is already lost is not worth one."""
    out = {}
    for entry in data.get("skipped") or []:
        if isinstance(entry, dict) and entry.get("topic_id") \
                and entry.get("stage", FUNNEL_STAGE) == FUNNEL_STAGE:
            out[entry["topic_id"]] = entry.get("reason_code") or "skipped"
    return out


def skip_entry(script, record, now=False):
    return {"topic_id": script.get("topic_id"), "reason_code": SKIP_REASON_CODE,
            "reason": refusal_reason(script, record, now), "stage": FUNNEL_STAGE,
            RECORD_KEY: record}


def free_fixes(record):
    n = (record or {}).get(FREE_FIXES_KEY)
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def carry(prev, record):
    """The ladder's state the next run reads (the fact's rewording, the
    deletion pass), kept across a record written before the judge."""
    for key in CARRIED_KEYS:
        if (prev or {}).get(key) is not None:
            record[key] = prev[key]
    return record


def prejudge_record(judge, script, mech, lint, extra, prev):
    """CF-0807: the record of a run stopped before the judge - nothing asked,
    `failed_attempts` as it was, one more of `free_fixes`."""
    record = {"rule": getattr(judge, "RULE", None), "action": ACTION_FAIL, "model": None,
              "mechanics": mech, "extracted": [], "verdicts": [], "violations": lint,
              "struck": [], "fact_struck": False, "refuse_now": False, "asked": 0, "cached": 0,
              PREJUDGE_KEY: True, FREE_FIXES_KEY: free_fixes(prev) + 1,
              "failed_attempts": previous_failures(script),
              "rewrites_allowed": REWRITES_ALLOWED, rg.HASH_KEY: claims_hash(script, extra)}
    return carry(prev, record)


def not_owned_fails(judge, script, batch, root, topics):
    """CF-0933: what the free mechanics of CF-0552 find on a script the round
    does not own, judged against its plan - `["shot_not_under_words c7", ...]`
    (no model call, nothing written)."""
    try:
        mech = judge.claims.check_claims(
            script, topic=topics.get(script.get("topic_id")),
            pool=judge.claims.pool_of(script, batch, root),
            plan=judge.claims.plan_of(script, batch))
    except Exception as exc:  # noqa: BLE001 - a line to read, never a crash of the round
        return [f"mechanics unreadable ({exc.__class__.__name__}: {exc})"]
    return [f"{v.get('code')} {v.get('claim_id')}" if v.get("claim_id") else str(v.get("code"))
            for v in (mech or {}).get("violations") or []]


def check_batch(batch_file, root=None, write=False, out=print, judge=None, asker=None,
                extra=None, answer_cmd=None, model=None, timeout=None, jobs=None,
                cache_dir=None, terms=None, openers=None, script_ids=None, own=None):
    """Judge every script of the batch. Returns `(problems, records, refused)`.
    `terms`: the outlets' terms for AI output (CF-0671; default: the batch's
    channel's, read in `root`). `script_ids`: judge only these (CF-0933; the
    rest are passed over silently, their records untouched). `own`: script ids
    the caller vouches this run owns although the reserve round does not
    (`plan_check_loop.py --after-supplement` settling a first-pass script 6b
    deferred) - they are judged and written; the round after the frame judge
    stays frozen whatever the caller says."""
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    root = Path(root) if root else find_root()
    if terms is None:
        terms = batch_terms(data, root)
    judge = judge or load_judge(root)
    if openers is None:
        openers = batch_openers(data, root)
    extra = {k: v for k, v in (extra or {}).items() if v}
    if asker is None:
        asker = judge.Asker(cache_dir or judge.cache_dir_of(path), answer_cmd,
                            model or judge.DEFAULT_MODEL, timeout or judge.DEFAULT_TIMEOUT)
    batch = path.resolve().parent
    topics = judge.claims.topics_of(batch)
    scripts = data.get("scripts") or []
    wanted = set(script_ids or ())
    out(f"{batch_file}: {len(scripts)} script(s)"
        + (f", judging {', '.join(sorted(wanted))} only" if wanted else "")
        + f"; claims under {judge.RULE} "
        f"({getattr(judge, 'ORIGIN', SHARED_REL)}), model {asker.model}, answers cached in "
        f"{asker.cache_dir}; one rewrite (then, when only struck claims are left, one "
        f"deletion-only edit - CF-0807), then the topic is refused as `{SKIP_REASON_CODE}`")

    problems, records, refused, now = [], {}, [], set()
    gone = skipped_topics(data)
    decided = jr.frozen(batch, scripts)
    unowned = {k: v for k, v in jr.not_owned(batch, scripts).items()
               if k not in decided and k not in set(own or ())}
    for script in scripts:
        sid = script.get("script_id")
        if wanted and sid not in wanted:
            continue
        if sid in decided:
            # CF-0902: the round after the frame judge judges its substitutes
            # only; a first-pass script keeps the record it went on with.
            out(f"  FROZEN    {sid}: {decided[sid]} - not sent to the judge, nothing asked, "
                f"nothing written")
            continue
        if sid in unowned:
            # CF-0933: the reserve round judges its substitutes only; what it
            # finds on a first-pass script is said, never stamped.
            fails = not_owned_fails(judge, script, batch, root, topics)
            out(f"  NOT OWNED {sid} "
                + (f"(fails: {', '.join(fails)})" if fails else "(the mechanics pass)")
                + f": {unowned[sid]} - not sent to the judge, nothing asked, nothing written")
            continue
        if script.get("topic_id") in gone:
            # CF-0827: a topic an earlier gate already took out (the free host
            # check runs before this one) is never sent to the paid judge.
            out(f"  SKIPPED   {sid}: topic {script.get('topic_id')} already stands in "
                f"skipped[] ({gone[script.get('topic_id')]}) - not sent to the judge, "
                f"nothing asked, nothing written (CF-0827)")
            continue
        claims = script.get(CLAIMS_FIELD)
        if not isinstance(claims, list):
            what = "missing" if CLAIMS_FIELD not in script else f"not a list ({claims!r})"
            out(f"  FAIL      {sid}: `{CLAIMS_FIELD}` {what}")
            problems.append(f"{sid}: `{CLAIMS_FIELD}` {what} - declare every checkable claim "
                            f"of the text with its footing (step 4); nothing was judged and no "
                            f"attempt was spent")
            continue
        prev = script.get(RECORD_KEY) if isinstance(script.get(RECORD_KEY), dict) else {}
        deletion = prev.get(DELETION_KEY) if isinstance(prev.get(DELETION_KEY), dict) else None
        deleted = None
        if deletion and deletion.get("state") == ladder.STATE_GRANTED:
            # CF-0807: the edit after DELETE is held to the snapshot before anything else.
            bad, deleted = ladder.deletion_problems(script, deletion, extra)
            if bad:
                record = dict(prev, action=ACTION_FAIL,
                              failed_attempts=previous_failures(script) + 1)
                record.pop(PREJUDGE_KEY, None)
                record[DELETION_KEY] = dict(deletion, state=ladder.STATE_NOT_DELETION,
                                            problems=bad, removed=deleted)
                record[DELETION_KEY].pop("base", None)
                record[rg.HASH_KEY] = claims_hash(script, extra)
                records[sid] = record
                out(f"  REFUSE    {sid}: {SKIP_REASON_CODE} - the deletion pass was not a "
                    f"deletion (CF-0807)")
                for line in bad:
                    out(f"      {line}")
                refused.append(script)
                continue
        phrase = prev.get(PHRASE_KEY) if isinstance(prev.get(PHRASE_KEY), dict) else None
        redone = None
        if phrase and phrase.get("state") == ladder.STATE_GRANTED:
            # CF-0883: the edit after PHRASE is held to its sentences before anything else.
            bad, redone = ladder.phrase_problems(script, phrase, extra)
            if bad:
                record = dict(prev, action=ACTION_FAIL,
                              failed_attempts=previous_failures(script) + 1)
                record.pop(PREJUDGE_KEY, None)
                record[PHRASE_KEY] = dict(phrase, state=ladder.STATE_NOT_PHRASE,
                                          problems=bad, changed=redone)
                record[PHRASE_KEY].pop("base", None)
                record[rg.HASH_KEY] = claims_hash(script, extra)
                records[sid] = record
                out(f"  REFUSE    {sid}: {SKIP_REASON_CODE} - the phrase pass went past its "
                    f"sentences (CF-0883)")
                for line in bad:
                    out(f"      {line}")
                refused.append(script)
                continue
        banned = cpf.attribution_lines(script, terms, extra)
        if banned:
            out(f"  FAIL      {sid}: {len(banned)} {cpf.ATTRIBUTION_RULE} - a phrasing an "
                f"outlet's terms forbid; nothing judged, no attempt spent (CF-0671)")
            for line in banned:
                out(f"      {line}")
            problems += [f"{sid}: {line}" for line in banned]
            continue
        demo = api_demo_footing(script, topics.get(script.get("topic_id")), judge.claims,
                                getattr(judge, "is_fact_claim", None))
        if demo:
            out(f"  FAIL      {sid}: {len(demo)} {API_DEMO_CODE} - the demo's answer (or the "
                f"factory's own record) used as a fact; nothing judged, no attempt spent "
                f"(CF-0690)")
            for v in demo:
                who = f" {v['claim_id']}" if v.get("claim_id") else ""
                out(f"      {v['code']}{who}: {v['detail']}")
                out(f"        -> {v['fix']}")
                out(f"        отказ: {v['text_ru']}")
            problems += [f"{sid}: {v['code']} {v.get('claim_id')}: {v['detail']}" for v in demo]
            continue
        held = unchanged(script, extra)
        if held is not None:
            out(f"  UNCHANGED {sid}: {rg.UNCHANGED} - the text and `{CLAIMS_FIELD}` are the "
                f"ones the last run sent back; nothing judged, nothing spent "
                f"(failed_attempts stays {held.get('failed_attempts')})")
            problems.append(f"{sid}: {rg.UNCHANGED}")
            if write:
                n = held.get(rg.RERUNS_KEY)
                held[rg.RERUNS_KEY] = (n if isinstance(n, int) and not isinstance(n, bool)
                                       else 0) + 1
            continue
        topic = topics.get(script.get("topic_id"))
        pool = judge.claims.pool_of(script, batch, root)
        plan = judge.claims.plan_of(script, batch)
        if free_fixes(prev) < FREE_FIXES_ALLOWED:
            # CF-0807: the mechanics and the pronoun lint, before any model call.
            mech = judge.claims.check_claims(script, topic=topic, pool=pool, plan=plan,
                                             extra_texts=extra)
            fatal = set(getattr(judge, "FATAL_MECHANICS", ()) or ())
            if not fatal & set(judge.claims.codes(mech)):
                # A claim the judge already read as following (the same words, an
                # earlier run) is not sent back for its pronoun: 6b's rerun on
                # frozen text must not turn into a text edit.
                held_ok = {(v.get("claim_id"), v.get("text"))
                           for v in prev.get("verdicts") or []
                           if isinstance(v, dict) and v.get("state") == "supported"}
                lint = [v for v in ladder.pronoun_violations(
                            script, judge.claims.viewer_texts(script, extra))
                        if (v.get("claim_id"), v.get("text")) not in held_ok]
                if mech.get("action") != ACTION_PASS or lint:
                    record = prejudge_record(judge, script, mech, lint, extra, prev)
                    records[sid] = record
                    left = FREE_FIXES_ALLOWED - record[FREE_FIXES_KEY]
                    out(f"  FAIL      {sid}: {len(codes_of(record))} kind(s) of violation found "
                        f"before the judge - nothing asked, no attempt spent (CF-0807; "
                        f"failed_attempts stays {record['failed_attempts']}, {left} such "
                        f"run(s) left before they count)")
                    for line in violation_lines(record):
                        out(line)
                    problems.append(f"{sid}: " + "; ".join(codes_of(record)))
                    continue
        try:
            record = judge.judge_script(
                script, topic=topic, pool=pool, plan=plan, extra_texts=extra, asker=asker,
                jobs=jobs or judge.DEFAULT_JOBS)
        except judge.CannotAsk as exc:
            raise CannotAnswer(str(exc))
        for r in hf.relieve(record, script, judge, openers):
            # CF-0883: the opener's own words / a title read as a claim by the reader.
            out(f"      not a claim ({r['why']}, CF-0883): {r['where']} {r['text']!r} - read as "
                f"{r['read_as']!r}, matched to {', '.join(r['matched'])}")
        if phrase:
            record[PHRASE_KEY] = phrase
            if redone is not None:               # the run right after PHRASE
                record[PHRASE_KEY] = dict(phrase, state=ladder.STATE_JUDGED, changed=redone)
                record[PHRASE_KEY].pop("base", None)
        if prev.get(FACT_REWORD_KEY) or prev.get(FACT_REWORDED_KEY):
            record[FACT_REWORDED_KEY] = prev.get(FACT_REWORD_KEY) or prev.get(FACT_REWORDED_KEY)
        if deletion:
            record[DELETION_KEY] = deletion
            if deleted is not None:              # the run right after DELETE
                record[DELETION_KEY] = dict(deletion, state=ladder.STATE_JUDGED,
                                            removed=deleted)
                record[DELETION_KEY].pop("base", None)
        if free_fixes(prev):
            record[FREE_FIXES_KEY] = free_fixes(prev)
        record["failed_attempts"] = previous_failures(script) + (record["action"] == ACTION_FAIL)
        record["rewrites_allowed"] = REWRITES_ALLOWED
        record[rg.HASH_KEY] = claims_hash(script, extra)
        records[sid] = record
        summary = (f"{record['mechanics']['claims']} claim(s), {len(record['extracted'])} "
                   f"listed by the reader, {record.get('asked', 0)} asked / "
                   f"{record.get('cached', 0)} cached"
                   + (f", {record['opinion_calls']} of them second opinions on a strike "
                      f"(CF-0579: {record.get('third_opinions', 0)} split, settled by a third)"
                      if record.get("opinion_calls") else ""))
        if record["action"] == ACTION_PASS:
            out(f"  ok        {sid}: {summary}")
            if deleted is not None:
                out(f"      after the deletion pass (CF-0807): {deletion_summary(deleted)} - the "
                    f"text is shorter: run check_narration_budget.py --write again")
            continue
        if record.get("refuse_now") and record["failed_attempts"] <= REWRITES_ALLOWED \
                and fact_rewordable(record, judge):
            # CF-0580: a true fact worded past its quote - one rewording, not a refusal.
            entry = fact_reword_entry(script, record)
            record[FACT_REWORD_KEY] = entry
            out(f"  REWORD    {sid}: the video's own fact does not follow from its quote as "
                f"worded - you get one rewording in the source's words, then it is judged "
                f"again ({summary})")
            for line in violation_lines(record, reword=True):
                out(line)
            for line in reword_lines(entry):
                out(line)
            problems.append(f"{sid}: reword the fact - " + "; ".join(codes_of(record)))
            continue
        if record["failed_attempts"] > REWRITES_ALLOWED and not deletion and not phrase:
            grant = None if record.get("refuse_now") else ladder.grant(script, record, extra)
            if grant is not None:
                # CF-0807: one more edit, deleting only (the user, 2026-10-19 14:17).
                record[DELETION_KEY] = grant
                out(f"  DELETE    {sid}: failed again after the one rewrite, and every strike "
                    f"left is a claim that does not follow - one more edit that ONLY deletes "
                    f"({summary}); no word is added or changed anywhere, then it is judged "
                    f"again, and a failure refuses the topic")
                for line in violation_lines(record):
                    out(line)
                for line in deletion_lines(grant):
                    out(line)
                problems.append(f"{sid}: delete only - " + "; ".join(codes_of(record)))
                continue
            # CF-0886: a struck fact may take this edit as its one rewording (CF-0580)
            # when it was never reworded - the ladder also wants the fact on screen
            # to have followed.
            fact_ok = fact_rewordable(record, judge) and not record.get(FACT_REWORDED_KEY)
            pgrant = ladder.phrase_grant(script, record, extra, fact_ok=fact_ok)
            if pgrant is not None:
                # CF-0883 / CF-0886: only the hook / payoff sentence is left - one edit of it.
                record[PHRASE_KEY] = pgrant
                out(f"  PHRASE    {sid}: failed again after the one rewrite, and all that is "
                    f"left is the hook / payoff sentence (an undeclared statement, or a claim "
                    f"not enough on its quote that is its section's only sentence) - one more "
                    f"edit of those sentences only ({summary}); then the whole text is judged "
                    f"again, and a failure refuses the topic")
                for line in violation_lines(record):
                    out(line)
                for line in phrase_lines(pgrant):
                    out(line)
                problems.append(f"{sid}: redo the phrase - " + "; ".join(codes_of(record)))
                continue
        if record.get("refuse_now") or record["failed_attempts"] > REWRITES_ALLOWED:
            why = ("still failing after the one deletion pass (CF-0807)" if deletion else
                   "still failing after the one phrase pass (CF-0883)" if phrase else
                   "the video's own fact still does not follow after its one rewording"
                   if record.get("fact_struck") and record.get(FACT_REWORDED_KEY) else
                   "the video's own fact has no footing" if record.get("fact_struck") else
                   "no support text" if record.get("refuse_now") else
                   "failed again after the rewrite")
            out(f"  REFUSE    {sid}: {SKIP_REASON_CODE} - {why} ({summary})")
            for line in violation_lines(record):
                out(line)
            refused.append(script)
            if record.get("refuse_now"):
                now.add(sid)
            continue
        out(f"  REWRITE   {sid}: {len(codes_of(record))} kind(s) of violation - you get one "
            f"rewrite: take the struck and undeclared claims OUT of the text ({summary})")
        for line in violation_lines(record):
            out(line)
        problems.append(f"{sid}: " + "; ".join(codes_of(record)))

    if write:
        for script in scripts:
            record = records.get(script.get("script_id"))
            if record is not None:
                script[RECORD_KEY] = record
        if refused:
            ids = {id(s) for s in refused}
            data["scripts"] = [s for s in scripts if id(s) not in ids]
            data.setdefault("skipped", [])
            for script in refused:
                sid = script.get("script_id")
                data["skipped"].append(skip_entry(script, records[sid], sid in now))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {batch_file}: `{RECORD_KEY}` on {len(records)} script(s)"
            + (f", {len(refused)} topic(s) moved to skipped[] ({SKIP_REASON_CODE})"
               if refused else ""))
    elif refused:
        out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but nothing "
            f"was recorded - re-run with --write so the funnel sees the loss")
    return problems, records, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--write", action="store_true",
                    help=f"write `{RECORD_KEY}` onto every judged script and move a refused "
                         f"topic to skipped[] as `{SKIP_REASON_CODE}`")
    ap.add_argument("--script-id", action="append", default=[],
                    help="judge only this script (repeatable; CF-0933) - the others are passed "
                         "over and their records stay as they are")
    ap.add_argument("--title", default=None, help="the publication's title (CF-0555)")
    ap.add_argument("--description", default=None, help="the publication's description")
    ap.add_argument("--answer-cmd", default=None,
                    help="the answer command (default: $CLAIM_JUDGE_ANSWER_CMD, else the "
                         "root's claim_answer_claude.py)")
    ap.add_argument("--model", default=None, help="default sonnet")
    ap.add_argument("--timeout", type=int, default=None, help="ceiling on one call, seconds")
    ap.add_argument("--jobs", type=int, default=None, help="judge calls at once")
    ap.add_argument("--cache-dir", default=None, help="default <batch>/work/claim-judge-cache")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else find_root()
    try:
        problems, _, refused = check_batch(
            args.batch_file, root=root, write=args.write,
            extra={"title": args.title, "description": args.description},
            answer_cmd=args.answer_cmd, model=args.model, timeout=args.timeout,
            jobs=args.jobs, cache_dir=args.cache_dir, script_ids=args.script_id)
    except CannotAnswer as exc:
        print(f"check_claims.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts on this run", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} script(s) to rewrite or fix:")
        for p in problems:
            print(f"  - {p}")
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}`"
              + ("" if args.write else " and nothing was recorded (--write)"))
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-claims", name="check_claims.py")
def cli():
    """The command-line entry (CF-0107): 1 = rewrite / fix the field, 3 = the
    question could not be put, 4 = a topic refused - each recorded as
    `failed`. The model calls are the root judge's answer command, one
    process per request."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
