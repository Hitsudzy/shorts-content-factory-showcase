#!/usr/bin/env python3
"""CF-0320: what a refusal costs, in ready videos, before it is switched on.

The defect, from the grill of 2026-09-22. The loop is a ratchet: a run finds a
defect -> a task is filed -> the task closes by adding a refusal -> the next run
has one more way to lose a topic. Nothing in the ring ever removes a refusal or
counts what one costs. The proof sat unread in `pipeline/RUNS.md` for six days:
`video_editor.two_source_gate` went from `measure` to `enforce` on 2026-09-16
(CF-0129) and the yield went from **1.0 to 0.2 ready videos per batch**.

So a rule that drops a topic or a video has to answer one number before it is
allowed to drop anything: **how many already-ready videos would it have killed**
on the frozen artifacts of the last WINDOW batches. Zero, and it lands as a
refusal. More than zero, and it lands as a warning until the user signs it
(`shared/gate-prices.json`). The check is machine-run - a step of the triage
script of CF-0319, which is why everything here is a function with a plain
input and a plain output and nothing here asks a human anything.

**A rule is a replay over one batch's frozen artifacts.** Not a predicate over
the live pool: the batch directories under `pipeline/<channel>/<batch>/` are
dated records that no later run rewrites, which is exactly what makes a price
reproducible (CF-0308 is the same point about `shared/footage/`, which is not
frozen and must not be read from here). A rule is:

    Rule(name, what, replay)      what: WHAT_VIDEO | WHAT_TOPIC
    replay(A) -> Replay           A: funnel.read_artifacts(batch_dir)

and it answers with `basis(reason, refused)` or `no_basis(reason)`.

**`no_basis` is the whole point, and it is not zero.** A batch that already ran
under the rule cannot price it: the rule has already taken everything it takes,
so counting its survivors gives 0 and that 0 means "measured nothing", not
"costs nothing". Priced over the five batches before it was switched on,
`two_source_gate` killed 2 of the 5 ready videos those batches produced; priced
over the last five batches - all of which ran under `enforce` - it reads `no
basis` five times. A rule that reports a price of 0 because nothing could be
measured would be a free pass rubber-stamped by arithmetic, which is the class
of misreading `shared/runlog/funnel.py` exists to stop. Here it comes out as
`price: None` and the verdict is a warning, never a refusal.

`ready` means what the funnel means by it - the same module, the same
vocabulary, one definition of a finished video (rendered, QC passed, and past
the frame judge when the batch was judged). This module never counts a video of
its own.

CLI: `runlog gate-price [--rule NAME] [--window N] [--before DATE] [--pool DIR]
[--json] [--write]`.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# CF-0231 / tests/test_module_path_loading.py: register our own directory from
# `__file__` and then import the neighbour by name - the one mechanism every
# module of shared/runlog/ uses, so that a loader outside this checkout gets
# the same module a `runlog` subcommand does.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import funnel  # noqa: E402
import stopcock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# The window the rule is priced over. The user's decision of 2026-09-22, in
# ROADMAP `## Versioning`: five batches, not "all of them" - a rule is judged
# against the pipeline as it runs now, and a corpus reaching back to August
# would let a gate pay for itself with videos built by a different factory.
WINDOW = 5

# The ledger. `rules.<name>.measured` is written by this module; `signature` and
# `decision` are the user's, written only by `sign` / `decide` (CF-0721) on the
# user's own press of the button in the command center - never by a measurement.
LEDGER = ROOT / "shared" / "gate-prices.json"
STATS = ROOT / "docs" / "gate-prices.md"

WHAT_VIDEO = "video"     # the rule refuses a rendered video, by script_id
WHAT_TOPIC = "topic"     # the rule refuses a topic; its scripts die with it
WHATS = (WHAT_VIDEO, WHAT_TOPIC)

ENFORCE, WARN = "enforce", "warn"
# CF-0432: a rule the score model holds in `penalty` mode costs points and never
# refuses - whatever its price, its verdict is this and never `enforce`.
PENALTY = "penalty"

BATCH_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}Z$")

# The key under which `price_of_batch` hands a replay the batch directory
# itself (CF-0329), for a rule that reads a frozen file no stage artifact
# carries. Underscored like the funnel's own `_missing` / `_errors`.
BATCH_DIR_KEY = "_batch_dir"


# --------------------------------------------------------------------------
# the rule protocol
# --------------------------------------------------------------------------

# CF-0472: what the code of a registered rule does when neither the user's
# decision nor a channel switch says otherwise. Only modes that refuse
# nothing may be written here: a registry entry may say "the code records"
# or "the code warns", never "the code refuses" - that is the default the
# triage falls back to (`hard-wired`) and only a signature lifts it.
# `content_researcher.tail_after_last_anchor` was filed as an авария because
# the triage read it as hard-wired while its code had stopped refusing at
# CF-0433/CF-0447 (`anchor_cadence.verdict: priced`, the tail spends no
# rewrite): coach-hale of example-film/2026-10-01T1313Z carried a failing tail
# record and was rendered, judged and accepted.
CODE_MEASURE = "measure"   # the code records the reading and refuses nothing
CODE_WARN = "warn"         # the code writes a warning and goes on
CODE_MODES = (CODE_MEASURE, CODE_WARN)


class Rule:
    """One refusal, replayable over one batch's frozen artifacts.

    `mode` (CF-0472): what the rule's code does in production when nothing
    else says - CODE_MEASURE or CODE_WARN, or None for "the code refuses"
    (the triage's `hard-wired`).

    `replay(A)` is handed the dict `funnel.read_artifacts()` returns and gives
    back `basis(...)` or `no_basis(...)`. It may read nothing else: a rule that
    reaches for the live pool prices itself against a corpus that grew since
    the batch ran, and stops being reproducible."""

    def __init__(self, name, what, replay, note="", mode=None):
        if what not in WHATS:
            raise ValueError(f"{name}: what must be one of {WHATS}, got {what!r}")
        if mode is not None and mode not in CODE_MODES:
            raise ValueError(f"{name}: mode must be one of {CODE_MODES} or None, got {mode!r}")
        self.name, self.what, self.replay, self.note = name, what, replay, note
        self.mode = mode

    def __repr__(self):                                             # pragma: no cover
        return f"<Rule {self.name} ({self.what})>"


def basis(reason, refused, undone=None):
    """The batch can price this rule. `refused` is {item_id: why} - every item
    the rule would have dropped, whether or not it ever became a video.

    `undone` (CF-0767) is {artifact_name: document} - the batch's frozen
    artifacts with the rule's own refusals taken back, for a rule that already
    refused here but recorded every victim beside the record of everything
    else it was judged on. `price_of_batch` reads the ready videos off the
    artifacts with these laid over them: the batch as it would have ended
    without the rule. A replay may hand it only when the undo is exact - the
    rule was the last word on each video it refused, so taking it back leaves
    the video as every other check left it - and never as a guess."""
    return {"basis": reason, "no_basis": None, "refused": dict(refused),
            "undone": dict(undone or {})}


def no_basis(reason):
    """The batch cannot price this rule, and the reason is part of the answer:
    the artifacts do not carry what the rule judges, or the rule was already
    enforcing here and has taken its victims before anything was rendered."""
    return {"basis": None, "no_basis": reason, "refused": {}, "undone": {}}


# --------------------------------------------------------------------------
# the batches
# --------------------------------------------------------------------------

def pool_root(pool=None):
    """The directory the batch records live in. `pipeline/` is gitignored, so a
    worktree has none of them; $RUNLOG_POOL points the reader at a checkout
    that does, and nothing is ever written there."""
    if pool:
        return Path(pool)
    return Path(os.environ.get("RUNLOG_POOL") or (ROOT / "pipeline"))


# Directories under pipeline/ that are not a channel's batches.
NOT_CHANNELS = ("backfill", "rebuilds")


def batches(pool=None, window=WINDOW, before=None):
    """The last `window` batch directories, newest last, oldest first.

    A batch is a `pipeline/<channel>/<id>/` carrying at least one of the stage
    artifacts - a run that produced nothing readable is not a batch anything
    can be priced against. `before` (a `YYYY-MM-DD` day or a batch id) takes
    the window as it stood at that moment, which is how a gate already standing
    is priced the way it should have been priced on the day it went in.
    `pipeline/backfill/` is left out: those are synthetic events reconstructed
    from a hand-written log (CF-0111) and carry no stage artifact at all.
    `pipeline/rebuilds/` is left out too (CF-0330): a rebuild copies a real
    batch's artifacts 01-04 byte for byte and renders on today's code, so it
    carries every stage artifact and would read as the newest batch - pricing
    a rule over it would count the same topics twice, under the gates of a
    different day."""
    root = pool_root(pool)
    found = []
    for ch in sorted(p for p in root.glob("*") if p.is_dir() and p.name not in NOT_CHANNELS):
        for b in sorted(p for p in ch.glob("*") if p.is_dir() and BATCH_ID.match(p.name)):
            if any((b / n).is_file() for n in funnel.ARTIFACTS):
                found.append(b)
    found.sort(key=lambda p: (p.name, p.parent.name))
    if before:
        cut = before if BATCH_ID.match(before) else f"{before}T0000Z"
        found = [b for b in found if b.name < cut]
    return found[-window:] if window else found


# --------------------------------------------------------------------------
# reading one batch
# --------------------------------------------------------------------------

def _topic_of(A):
    """{script_id: topic_id}, from the Researcher first and the second
    compliance pass second - the two artifacts that carry both ids."""
    out = {}
    for name, keys in (("03-content-researcher.json", ("scripts", "skipped")),
                       ("04-compliance-checker.json", ("results",))):
        d = A.get(name) or {}
        for key in keys:
            for row in d.get(key) or []:
                if isinstance(row, dict) and row.get("script_id") and row.get("topic_id"):
                    out.setdefault(row["script_id"], row["topic_id"])
    return out


def price_of_batch(rule, batch_dir=None, artifacts=None):
    """What `rule` would have cost this one batch:

        {"batch", "basis", "no_basis", "ready", "refused", "killed", "price"}

    `killed` is the intersection the whole module exists to compute - the ready
    videos the rule refuses. `price` is None exactly when there is no basis.
    `ready` is read off the batch without the rule when the replay undid its
    refusals (CF-0767), so a video the rule took is counted as the ready video
    it would have been."""
    A = artifacts if artifacts is not None else funnel.read_artifacts(batch_dir)
    if batch_dir is not None and BATCH_DIR_KEY not in A:
        # CF-0329: a rule whose evidence is a frozen file beside the stage
        # artifacts (the render plans under `work/`) is handed the directory
        # too. The stage artifacts stay the only thing the funnel reads.
        A = {**A, BATCH_DIR_KEY: Path(batch_dir)}
    rep = rule.replay(A)
    # CF-0767: a rule that already refused here and recorded what it refused
    # is priced against the batch without it (`basis(..., undone=)`); every
    # other rule against the batch as it ended.
    f = funnel.funnel(artifacts={**A, **(rep.get("undone") or {})})
    ready = [(r["item"], r.get("slug")) for r in f.get("ready") or []]
    row = {"batch": _name(batch_dir), "basis": rep["basis"], "no_basis": rep["no_basis"],
           "ready": [item for item, _ in ready], "refused": sorted(rep["refused"]),
           "killed": [], "price": None}
    if rep["no_basis"]:
        return row
    refused = rep["refused"]
    topic_of = _topic_of(A) if rule.what == WHAT_TOPIC else {}
    for item, slug in ready:
        key = topic_of.get(item) if rule.what == WHAT_TOPIC else item
        if key in refused:
            row["killed"].append({"item": item, "slug": slug, "key": key,
                                  "reason": refused[key]})
    row["price"] = len(row["killed"])
    return row


def _name(batch_dir):
    if batch_dir is None:
        return None
    p = Path(batch_dir)
    return f"{p.parent.name}/{p.name}"


# --------------------------------------------------------------------------
# the price, and the verdict that follows from it
# --------------------------------------------------------------------------

def price(rule, dirs=None, pool=None, window=WINDOW, before=None, ledger=None):
    """The number a task adding this refusal has to answer with.

        {"rule", "what", "window", "batches": [...], "ready", "price",
         "measured_on", "of", "verdict", "why", "signature"}

    `price` is the count of already-ready videos the rule would have killed
    across the batches that could price it, and None when none of them could.
    `verdict` is `enforce` only for a measured, signed-off zero-or-less; every
    other answer is `warn`, including the unmeasurable one."""
    dirs = list(dirs) if dirs is not None else batches(pool, window, before)
    rows = [price_of_batch(rule, b) for b in dirs]
    with_basis = [r for r in rows if r["price"] is not None]
    total = sum(r["price"] for r in with_basis) if with_basis else None
    ready = sum(len(r["ready"]) for r in with_basis)
    sig = signature_of(rule.name, ledger)
    verdict, why = _verdict(total, sig, len(with_basis), len(rows))
    if ledger_mode_of(rule.name, ledger) == PENALTY:
        verdict, why = PENALTY, ("a penalty of the score model (shared/score, CF-0432): it "
                                 "costs points and never refuses, so its price is a reading, "
                                 "not a licence to refuse")
    dec = decision_of(rule.name, ledger)
    return {"rule": rule.name, "what": rule.what, "note": rule.note, "before": before,
            "window": [r["batch"] for r in rows], "batches": rows,
            "ready": ready, "price": total,
            "measured_on": len(with_basis), "of": len(rows),
            "verdict": verdict, "why": why, "signature": sig, "decision": dec}


def _verdict(total, sig, measured_on, of):
    if total is None:
        return WARN, (f"no basis: none of the {of} batch(es) in the window could carry a "
                      f"video this rule refuses, so nothing was measured - and nothing "
                      f"measured is not a price of zero")
    if total == 0:
        return ENFORCE, (f"0 of {measured_on} priceable batch(es) in the window lost a ready "
                         f"video to this rule - it lands as a refusal")
    if sig and _num(sig.get("price")) is not None and _num(sig["price"]) >= total:
        who = sig.get("user") or "the user"
        return ENFORCE, (f"{total} ready video(s) would have died, and {who} signed the rule "
                         f"at a price of {sig['price']} on {sig.get('date', '?')}")
    if sig:
        return WARN, (f"{total} ready video(s) would have died - more than the {sig.get('price')} "
                      f"the signature of {sig.get('date', '?')} covers; it needs a new one")
    return WARN, (f"{total} ready video(s) would have died across {measured_on} priceable "
                  f"batch(es) - it lands as a warning until the user signs it")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

LEDGER_NOTE = (
    "CF-0320. `measured` is written by `runlog gate-price --write` and is a reading of the "
    "frozen batch artifacts named in `window`; `price` is how many already-ready videos the "
    "rule would have killed there, and `null` means no batch in the window could price it at "
    "all - which is not a price of zero. `signature` is the only block a human writes: a "
    "signature written by the code that needs it is not a signature. The one writer is "
    "`sign` (and `decide` for a `decision`, CF-0721), called by the command center after the "
    "user pressed the button, with the user's name and note - never while a batch is open, "
    "never by a measurement. It is {\"user\", \"date\", \"price\", \"note\"}, and it "
    "covers the rule only while the measured price stays at or under the price signed - a "
    "re-measurement that comes out worse un-signs the rule by itself."
)


def read_ledger(path=None):
    p = Path(path or LEDGER)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rules": {}}
    return d if isinstance(d, dict) else {"rules": {}}


def signature_of(name, path=None):
    """The user's signature under this rule's price, or None. A signature is
    the user's block; nothing in this module writes one but `sign` (CF-0721),
    on the user's own action, because a signature written by the code that
    needs it is not a signature."""
    row = (read_ledger(path).get("rules") or {}).get(name) or {}
    sig = row.get("signature")
    return sig if isinstance(sig, dict) else None


def ledger_mode_of(name, path=None):
    """The rule's mode in the score model (CF-0432): `hard`, `penalty` or None.
    Only `penalty` changes anything here - such a rule never lands as a
    refusal, whatever it would have cost."""
    d = path if isinstance(path, dict) else read_ledger(path)
    row = (d.get("rules") or {}).get(name) or {}
    m = row.get("mode")
    return m if m in ("hard", PENALTY) else None


def decision_of(name, path=None):
    """The user's recorded decision on this rule's mode, or None (CF-0330).

    A `decision` block is hand-written like a signature and is its opposite:
    {"user", "date", "mode", "task", "note"} with `mode` = `warn` records that
    the user was asked to sign the price and chose a warning instead. It never
    turns a rule into a refusal - only a signature does that - and nothing here
    writes one but `decide` (CF-0721), for the same reason as `sign`."""
    row = (read_ledger(path).get("rules") or {}).get(name) or {}
    dec = row.get("decision")
    return dec if isinstance(dec, dict) else None


def decision_line(dec):
    if not dec:
        return None
    return (f"Decision: {dec.get('user', 'the user')}, {dec.get('date', '?')} "
            f"({dec.get('task', '?')}): {dec.get('mode', '?')}. {dec.get('note', '')}").rstrip()


def write_ledger(results, path=None):
    """Record each measurement under `rules.<name>.measured`, leaving every
    `signature` block exactly as it was found."""
    p = Path(path or LEDGER)
    with ledger_lock(p):      # CF-0721: never between a `sign`'s read and its write
        d = {"note": LEDGER_NOTE, **{k: v for k, v in read_ledger(p).items() if k != "note"}}
        d.setdefault("rules", {})
        for res in results:
            row = d["rules"].setdefault(res["rule"], {})
            row["what"] = res["what"]
            if res.get("note"):
                row["note"] = res["note"]
            row["measured"] = {
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ"),
                "before": res.get("before"),
                "window": res["window"], "ready": res["ready"], "price": res["price"],
                "measured_on": res["measured_on"], "of": res["of"],
                "verdict": res["verdict"], "why": res["why"],
            }
            row.setdefault("signature", None)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# the user's signature and decision, from the command center (CF-0721)
# --------------------------------------------------------------------------
# Until CF-0721 a signature or a decision was a hand edit of the ledger (the
# orchestrator writing down the user's words). `sign` and `decide` are the
# center's two buttons for it - the same rule as `sign_hold` (CF-0687,
# agents/compliance-checker/scripts/publication_hold.py): the center calls them
# only after the user pressed the button, with the user's name (`by`) and note,
# and records itself as `via`. The code never calls them on its own: outside
# `_write_block`, which only these two call, this module sets a `signature` or a
# `decision` to nothing but None (tests/test_gate_price_sign.py reads the source).
#
# The answer is a dict, never an exception for a refusal - the CF-0726 shape:
#   {"ok", "written", "dry_run", "task": "CF-0721", "rule", "key", "path",
#    "by", "via", "base_sha256", "sha256", "new_sha256", "commit", "block",
#    "refusals": [{"code", "line"}], "lines": [..]}
# `base_sha256` is the ledger's sha256 as the caller read it (`ledger_sha256`);
# the ledger lock is `shared/.gate-prices.lock` (`ledger_lock`, gitignored).

SIGN_TASK = "CF-0721"
SIGN_VIA = "center"                   # the only `via`: the user pressed the center's button
SCORE_MODES = ("hard", PENALTY)       # rows of the score model, signed with their table
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TASK_RE = re.compile(r"^[A-Z]{2,4}-\d{3,5}$")
# `by` is the human who pressed the button. A name that reads as a model, an
# agent or a script is refused - a signature by the machinery is not one.
NOT_HUMAN = re.compile(
    r"(?i)\b(?:claude|anthropic|opus|sonnet|haiku|fable|gpt\w*|openai|gemini|codex|llm|ai"
    r"|models?|agents?|bots?|assistants?|orchestrators?|operators?|drivers?|workers?"
    r"|auto-?dev|scripts?|cron|system|модел\w*|агент\w*|бот\w*|оркестратор\w*"
    r"|ассистент\w*|скрипт\w*)\b")

BAD_WHO, NOT_HUMAN_BY, BAD_VIA = "bad_who", "not_human", "bad_via"
NO_SUCH_RULE, NOT_SIGNABLE, LEDGER_UNREADABLE = "no_such_rule", "not_signable", "ledger_unreadable"
BAD_PRICE, NOT_MEASURED, BELOW_MEASURED = "bad_price", "not_measured", "below_measured"
ALREADY_SIGNED, BAD_MODE, BAD_TASK = "already_signed", "bad_mode", "bad_task"
EMPTY_NOTE, BAD_DATE = "empty_note", "bad_date"
BATCH_OPEN, CHECK_CHANGED, LOCKED = "batch_open", "check_changed", "locked"
NOT_REPO, COMMIT_REFUSED, WRITE_FAILED = "not_repo", "commit_refused", "write_failed"
SIGN_REFUSALS = (BAD_WHO, NOT_HUMAN_BY, BAD_VIA, NO_SUCH_RULE, NOT_SIGNABLE, LEDGER_UNREADABLE,
                 BAD_PRICE, NOT_MEASURED, BELOW_MEASURED, ALREADY_SIGNED, BAD_MODE, BAD_TASK,
                 EMPTY_NOTE, BAD_DATE, BATCH_OPEN, CHECK_CHANGED, LOCKED, NOT_REPO,
                 COMMIT_REFUSED, WRITE_FAILED)


def _list_write():
    """shared/channel_list_write.py (CF-0726): `who`, `refusal`, `file_lock`,
    `runlog()`, the plain atomic write - loaded by path, only when signing."""
    import importlib.util
    mod = sys.modules.get("_channel_list_write_for_gate_price")
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            "_channel_list_write_for_gate_price", ROOT / "shared" / "channel_list_write.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return mod


def ledger_path(root=None):
    return Path(root) / LEDGER.relative_to(ROOT) if root else LEDGER


def ledger_sha256(root=None):
    """The `base_sha256` the center passes back: the ledger's sha256 now (None: no file)."""
    return _list_write().sha256_of(ledger_path(root))


def ledger_lock(path=None, wait=None):
    """The ledger's exclusive lock: `.gate-prices.lock` beside the ledger file.
    Taken by `sign` / `decide` and by `write_ledger`."""
    clw = _list_write()
    p = Path(path or LEDGER)
    return clw.file_lock(p.with_name(f".{p.stem}.lock"),
                         clw.LOCK_WAIT if wait is None else wait, "the gate-price ledger")


def _covers(sig, measured):
    return (isinstance(sig, dict) and _num(sig.get("price")) is not None
            and measured is not None and sig["price"] >= measured)


def _measured_price(row):
    m = row.get("measured")
    return _num(m.get("price")) if isinstance(m, dict) else None


def _date_of(date, now):
    if date is None:
        return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return date


def sign(rule, price, note, by, via, date=None, *, base_sha256, root=None, dry_run=False,
         commit=True, lock_wait=None, now=None, open_rows=None):
    """Write the user's signature under `rule`'s price (CF-0721): `signature =
    {"user": by, "date", "price", "note", "via"}`. Refused (besides the
    common refusals of `_write_block`): a score-model row (`not_signable` -
    those are signed with their table), a rule nothing measured
    (`not_measured`), a price that is not a number >= 0 (`bad_price`) or is
    under the measured price (`below_measured` - it would cover nothing), and a
    rule whose signature already covers the measured price (`already_signed`)."""
    def make(name, row, refs):      # -> the block's own fields; refusals into refs
        measured = _measured_price(row)
        if row.get("mode") in SCORE_MODES:
            refs.append(_ref(NOT_SIGNABLE, f"{name} is a score-model rule ({row.get('mode')}) - "
                                           f"it is signed with the score table, not here"))
        elif measured is None:
            refs.append(_ref(NOT_MEASURED, f"{name}: no measured price in the ledger - a "
                                           f"signature never covers a rule nothing measured"))
        if _num(price) is None or price < 0 or price != price:
            refs.append(_ref(BAD_PRICE, f"price={price!r}: a number of ready videos, 0 or more"))
        elif measured is not None and price < measured:
            refs.append(_ref(BELOW_MEASURED, f"{name}: price {price} is under the measured "
                                             f"{measured} - it would cover nothing"))
        if _covers(row.get("signature"), measured):
            s = row["signature"]
            refs.append(_ref(ALREADY_SIGNED, f"{name} is signed by {s.get('user')} on "
                                             f"{s.get('date')} at {s.get('price')}, which "
                                             f"covers the measured {measured}"))
        return {"price": price}
    return _write_block("signature", rule, make, note, date, base_sha256=base_sha256, by=by,
                        via=via, root=root, dry_run=dry_run, commit=commit,
                        lock_wait=lock_wait, now=now, open_rows=open_rows)


def decide(rule, mode, task, note, by, via, date=None, *, base_sha256, root=None,
           dry_run=False, commit=True, lock_wait=None, now=None, open_rows=None):
    """Write the user's decision on `rule` (CF-0721): `decision = {"user": by,
    "date", "mode", "task", "note", "via"}`. `mode` is one of CODE_MODES
    (`measure`, `warn`) - a decision never makes a refusal, only a signature
    does (`bad_mode` otherwise); `task` a task id like CF-0330 (`bad_task`).
    Refused for a score-model row (`not_signable`) and for a rule whose
    signature covers the measured price (`already_signed` - a decision does
    not un-sign a rule). A former decision is replaced."""
    def make(name, row, refs):      # -> the block's own fields; refusals into refs
        if row.get("mode") in SCORE_MODES:
            refs.append(_ref(NOT_SIGNABLE, f"{name} is a score-model rule ({row.get('mode')}) - "
                                           f"it is decided with the score table, not here"))
        if mode not in CODE_MODES:
            refs.append(_ref(BAD_MODE, f"mode={mode!r}: one of {list(CODE_MODES)} - a decision "
                                       f"never makes a refusal, only a signature does"))
        if not (isinstance(task, str) and TASK_RE.match(task)):
            refs.append(_ref(BAD_TASK, f"task={task!r}: a task id like CF-0330"))
        if _covers(row.get("signature"), _measured_price(row)):
            s = row["signature"]
            refs.append(_ref(ALREADY_SIGNED, f"{name} is signed by {s.get('user')} on "
                                             f"{s.get('date')} at {s.get('price')} - a decision "
                                             f"does not un-sign it"))
        return {"mode": mode, "task": task}
    return _write_block("decision", rule, make, note, date, base_sha256=base_sha256, by=by,
                        via=via, root=root, dry_run=dry_run, commit=commit,
                        lock_wait=lock_wait, now=now, open_rows=open_rows)


def _ref(code, line):
    return {"code": code, "line": line}


def _write_block(key, rule, make, note, date, *, base_sha256, by, via, root, dry_run, commit,
                 lock_wait, now, open_rows):
    """The one place a `signature` / `decision` is written, called by `sign` and
    `decide` only. In order: `by`/`via` (`bad_who`: a short single line, both
    required; `not_human`: `by` reads as a model/agent/script; `bad_via`: not
    the center), the note (`empty_note`) and date (`bad_date`, YYYY-MM-DD,
    default today), the row (`ledger_unreadable`, `no_such_rule`, `make`'s
    own), then - before the lock and again under it - no batch open anywhere
    (`batch_open`: shared/ is read by every batch; `runlog.open_batches`, the
    fresh rows) and the ledger as the caller read it (`check_changed`). Then
    the lock (`locked`), and the write: the ledger re-encoded as `write_ledger`
    does, with only rules.<rule>.<key> changed, committed alone through
    `git_commit.write_and_commit` (`not_repo`, `commit_refused`) or, with
    commit=False, a temp file and os.replace (`write_failed`). `dry_run`:
    the same checks, nothing written, no lock."""
    clw = _list_write()
    root = Path(root) if root else ROOT
    path = ledger_path(root)
    out = {"ok": False, "written": False, "dry_run": bool(dry_run), "task": SIGN_TASK,
           "rule": rule, "key": key, "path": LEDGER.relative_to(ROOT).as_posix(), "by": by,
           "via": via, "base_sha256": base_sha256, "sha256": None, "new_sha256": None,
           "commit": None, "block": None, "refusals": [], "lines": []}
    refs = out["refusals"]
    for value, what in ((by, "by"), (via, "via")):
        why = clw.who(value, what)
        if why:
            refs.append(_ref(BAD_WHO, why))
    if not refs:
        by, via = by.strip(), via.strip()
        out.update(by=by, via=via)
        if NOT_HUMAN.search(by):
            refs.append(_ref(NOT_HUMAN_BY, f"by={by!r} reads as a model, an agent or a script - "
                                           f"only the user signs, by pressing the button"))
        if via != SIGN_VIA:
            refs.append(_ref(BAD_VIA, f"via={via!r}: the user signs in the command center "
                                      f"(via={SIGN_VIA!r})"))
    note = note.strip() if isinstance(note, str) else ""
    if not note:
        refs.append(_ref(EMPTY_NOTE, "a signature or a decision needs the user's note"))
    date = _date_of(date, now)
    if not (isinstance(date, str) and DATE_RE.match(date)):
        refs.append(_ref(BAD_DATE, f"date={date!r}: YYYY-MM-DD"))

    def gate():
        got = []
        rows = open_rows if open_rows is not None else clw.runlog().open_batches(root, now=now)
        for row in rows:
            if row[2]:
                got.append(_ref(BATCH_OPEN, f"{clw._rel(row[0], root)} is open - the ledger is "
                                            f"not signed while a batch runs"))
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        out["sha256"] = None if raw is None else clw.sha256_bytes(raw)
        if out["sha256"] != base_sha256:
            got.append(_ref(CHECK_CHANGED, f"{out['path']}: sha256 {out['sha256']} on disk, "
                                           f"{base_sha256} read by the caller - read it again"))
        return got, raw

    got, raw = gate()
    try:
        ledger = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError as e:
        ledger = None
        refs.append(_ref(LEDGER_UNREADABLE, f"{out['path']}: {e}"))
    rules = ledger.get("rules") if isinstance(ledger, dict) else None
    row = rules.get(rule) if isinstance(rules, dict) else None
    if raw is None or (ledger is not None and not isinstance(rules, dict)):
        refs.append(_ref(LEDGER_UNREADABLE, f"{out['path']}: no ledger with a `rules` table"))
    elif isinstance(rules, dict) and not isinstance(row, dict):
        refs.append(_ref(NO_SUCH_RULE, f"{rule!r} is not a rule of the ledger"))
    if isinstance(row, dict):
        out["block"] = {"user": by, "date": date, **make(rule, row, refs), "note": note,
                        "via": via}
    refs.extend(got)
    if not refs and commit and not dry_run and not clw.git_commit().is_repo(root):
        refs.append(_ref(NOT_REPO, f"{root} is not a git repository - the ledger cannot be "
                                   f"committed (commit=False writes without a commit)"))
    if refs:
        out["block"] = None
        return out
    row[key] = out["block"]
    data = (json.dumps(ledger, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    out["new_sha256"] = clw.sha256_bytes(data)
    what = f"{rule} {key} by {by} via {via}"
    if dry_run:
        out.update(ok=True)
        out["lines"].append(f"{out['path']}: {what} - dry run, nothing written ({SIGN_TASK})")
        return out
    try:
        with ledger_lock(path, wait=lock_wait):
            again, _ = gate()
            if again:
                refs.extend(again)
                return out
            try:
                if commit:
                    out["commit"] = clw.git_commit().write_and_commit(
                        root, {path: data},
                        f"gate-prices: {what} ({SIGN_TASK})\n\n"
                        f"shared/runlog/gate_price.py {'sign' if key == 'signature' else 'decide'}"
                        f" {rule}\n")
                else:
                    clw._write_plain(path, data)
            except Exception as e:                              # noqa: BLE001
                gc = clw.git_commit()
                if isinstance(e, gc.CommitError):
                    refs.append(_ref(COMMIT_REFUSED, f"the commit was refused, the ledger put "
                                                     f"back as it was: {e} "
                                                     f"{' '.join(e.details)}".rstrip()))
                    return out
                if isinstance(e, OSError):
                    refs.append(_ref(WRITE_FAILED, f"{out['path']}: {type(e).__name__}: {e}"))
                    return out
                raise
    except clw.Locked as e:
        refs.append(_ref(LOCKED, str(e)))
        return out
    out.update(ok=True, written=True, sha256=out["new_sha256"])
    out["lines"].append(f"{out['path']}: {what}"
                        + (f", committed {out['commit'][:12]}" if out["commit"] else "")
                        + f" ({SIGN_TASK})")
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def headline(res):
    if res["price"] is None:
        return (f"GATE PRICE: {res['rule']} - not measurable on the last {res['of']} batch(es): "
                f"{res['why']} -> {res['verdict']}")
    return (f"GATE PRICE: {res['rule']} - {res['price']} of {res['ready']} ready video(s) "
            f"would have died across {res['measured_on']} of {res['of']} batch(es) "
            f"-> {res['verdict']}")


def render(res, level="##"):
    """The rule's measurement as markdown lines."""
    out = [f"{level} {res['rule']}", ""]
    if res.get("note"):
        out += [res["note"], ""]
    out += [headline(res).replace("GATE PRICE: ", ""), ""]
    if res.get("before"):
        out += [f"Window: the last {res['of']} batch(es) before `{res['before']}` - the window as "
                f"it stood when the rule went in.", ""]
    out += ["| batch | ready | basis | would have died |", "|---|---|---|---|"]
    for r in res["batches"]:
        if r["price"] is None:
            out.append(f"| `{r['batch']}` | {len(r['ready'])} | - no basis: {r['no_basis']} | - |")
            continue
        killed = ", ".join(f"`{k['slug'] or k['item']}`" for k in r["killed"]) or "-"
        out.append(f"| `{r['batch']}` | {len(r['ready'])} | {r['basis']} | {r['price']} ({killed}) |")
    out += ["", f"**verdict: {res['verdict']}** - {res['why']}"]
    if res["signature"]:
        s = res["signature"]
        out.append(f"Signature: {s.get('user', '?')}, {s.get('date', '?')}, "
                   f"price {s.get('price')}. {s.get('note', '')}".rstrip())
    else:
        out.append("Signature: none.")
    if res.get("decision"):
        out.append(decision_line(res["decision"]))
    return out


def render_unregistered(name, row, level="##"):
    """A ledger row with a user's decision and no replay in RULES (CF-0330):
    a gate priced by hand on a rebuild rather than over the frozen window. It
    is printed so the decision is on the page, and says plainly that no
    window measurement stands behind it."""
    out = [f"{level} {name}", ""]
    if row.get("note"):
        out += [row["note"], ""]
    m = row.get("measured")
    if isinstance(m, dict) and m.get("why"):
        out += [f"Measured by hand ({m.get('at', '?')}): {m['why']}", ""]
    out.append("Not replayed over the window: no rule of this name is registered in "
               "shared/runlog/gate_price.py, so `runlog gate-price` does not price it.")
    sig = row.get("signature")
    out.append(("Signature: " + f"{sig.get('user', '?')}, {sig.get('date', '?')}, "
                f"price {sig.get('price')}.") if isinstance(sig, dict) else "Signature: none.")
    if isinstance(row.get("decision"), dict):
        out.append(decision_line(row["decision"]))
    return out


# CF-0472: prices proposed for the user's signature, not in force. They live
# beside `rules`, never inside it: shared/score/score.py, the Editor's
# `_score.has_rule` and `held_motion.mode()` read `rules` only, so a proposal
# costs nothing and refuses nothing until the orchestrator moves it there with
# the user's signature. Nothing here writes a proposal's `signature` or moves a row.
# 2026-10-02 (CF-0490): the three CF-0472 rows were signed and moved to `rules`;
# the block is empty and the page prints no proposals section while it stays so.
PROPOSALS_KEY = "proposals"


def proposals(path=None):
    """`{name: row}` of the proposals block, or {}."""
    d = path if isinstance(path, dict) else read_ledger(path)
    rows = (d.get(PROPOSALS_KEY) or {}).get("rows") if isinstance(d.get(PROPOSALS_KEY), dict) else None
    return {n: r for n, r in (rows or {}).items() if isinstance(r, dict)}


def _proposal_task(row):
    """The task of a proposal: its `task`, or (a row in the shape of `rules`,
    CF-0646) the `CF-NNNN` its note opens with."""
    if row.get("task"):
        return row["task"]
    m = re.match(r"(CF-\d+)", row.get("note") or "")
    return m.group(1) if m else "?"


def _proposal_mode_until_signed(row):
    """`mode_until_signed`, or `warn` for a row in the shape of `rules` (CF-0646):
    an unsigned row is a warning wherever its code reads the table."""
    if row.get("mode_until_signed"):
        return row["mode_until_signed"]
    return "warn" if isinstance(row.get("penalty"), dict) and not row.get("signature") else "?"


def proposal_line(name, row):
    """One line for the user to sign: the rule, the price, what it costs the
    accepted and the rejected videos of the acceptance log. A proposal is
    either CF-0472's shape (`proposed`, `measured`) or, since CF-0646, the
    row of `rules` it will become (`penalty`, `note`, `signature: null`)."""
    pr = row.get("proposed") or row.get("penalty") or {}
    m = row.get("measured") or {}
    cap = f", cap {pr['cap']}" if pr.get("cap") is not None else ""
    allow = f" over {pr['allow_seconds']} s" if pr.get("allow_seconds") is not None else ""
    head = f"{name} ({_proposal_task(row)}): -{pr.get('price')} per {pr.get('per')}{allow}{cap}"
    if not m and row.get("note"):
        # a row in the shape of `rules` says what it costs in its note
        return f"{head}; {row['note']}"
    return (f"{head}; "
            f"accepted lose: {m.get('accepted_lose', '?')}; rejected lose: "
            f"{m.get('rejected_lose', '?')}")


def render_proposals(rows, level="##"):
    if not rows:
        return []
    out = [f"{level} Proposals awaiting the user's signature (CF-0472)", "",
           "Not in force: `shared/gate-prices.json#proposals` is read by no price and no "
           "refusal. Until signed each rule stands as its code leaves it "
           "(`mode_until_signed`).", ""]
    for name in sorted(rows):
        row = rows[name]
        out += [f"- **{name}** - {proposal_line(name, row).split(': ', 1)[1]} "
                f"(until signed: {_proposal_mode_until_signed(row)}). "
                f"{(row.get('measured') or {}).get('named_defect', '')}".rstrip()]
    return out


STATS_HEADER = """# Цена воротец (CF-0320)

<!-- Generated by `runlog gate-price --write`. Do not edit by hand: the numbers
     come from the frozen batch artifacts under pipeline/, and the signatures
     come from shared/gate-prices.json, which is the file a human edits. -->

A refusal that has never been priced is a refusal nobody agreed to. Every rule
below was replayed over the frozen artifacts of the batches named in its table,
and the number is how many **already-ready videos** it would have killed there.
`no basis` means the batch could not price the rule at all - most often because
it already ran under it - and it is not a price of zero.

The price table of the score model (`score.*` rows, CF-0432) is not priced here: its rules cost points (`penalty`) or sit on the hard list (`hard`). The user signed it as is on 2026-09-30 - «таблица цен модели очков подписана как есть, 2026-09-30» (`score.status: signed`, a `signature` on every `score.*` row of shared/gate-prices.json); see docs/score-model.md.

Fast cutting is an observation, not a price (CF-0743, the user's ruling of 2026-10-14: «CF-0743 - читать это быстрым монтажом без дефекта»). Under CF-0314 («быстрый монтаж — не дефект», 2026-09-22) two ways out of the explainer envelopes are read as fast cutting: the longest picture under the hold floor (the first case, 13.10: 2.46 s of 2.5 s) and the pace over the observed rate ceiling. Neither is a defect and neither is charged; the live monitor tests/test_pattern_vocabulary.py::test_baseline_envelope_covers_the_real_corpus prints them as observations naming the ruling (`RULINGS` there) and stays red on every other unpriced way out. The price proposed for the first one, score.picture_never_settles (-2 per started 0.5 s short of the floor, cap 10), was not signed and is out of `proposals`; its numbers stay in the proposals' note of shared/gate-prices.json.
"""


def render_stats(results, generated_at=None, ledger=None):
    at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = STATS_HEADER.splitlines() + ["", f"Замер: {at}.", ""]
    for res in results:
        out += render(res) + [""]
    seen = {res["rule"] for res in results}
    rows = read_ledger(ledger).get("rules") or {}
    for name in sorted(rows):
        if name not in seen and name not in RULES and isinstance(rows[name].get("decision"), dict):
            out += render_unregistered(name, rows[name]) + [""]
    out += render_proposals(proposals(ledger))
    return out


def write_stats(results, path=None, generated_at=None, ledger=None):
    p = Path(path or STATS)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(render_stats(results, generated_at, ledger)).rstrip() + "\n",
                 encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# the rules of the gates that already stand (CF-0320 item 4)
# --------------------------------------------------------------------------

def _two_source_gate(A):
    """`video_editor.two_source_gate` (CF-0118 -> CF-0129): a video whose
    footage comes from fewer than `required` independent canonical sources.

    The batch prices it only while the gate was in `measure`: that is the mode
    in which the Editor writes the verdict and renders anyway, so the artifact
    carries videos the gate would have refused. Under `enforce` the same field
    reads `passed: true` on every video that exists, because the ones it
    refused were never rendered - a survivorship record, not a price."""
    ve = A.get("05-video-editor.json")
    if not ve:
        return no_basis("no 05-video-editor.json: the batch rendered nothing")
    rows = [(v.get("script_id"), v.get("two_source_gate")) for v in ve.get("videos") or []]
    rows = [(s, g) for s, g in rows if s and isinstance(g, dict)]
    if not rows:
        return no_basis("no video carries a `two_source_gate` record")
    modes = {g.get("mode") for _, g in rows}
    if modes - {"measure"}:
        return no_basis(f"the gate already ran as {'/'.join(sorted(m or '?' for m in modes))} "
                        f"here, so the videos it refused were never rendered")
    refused = {}
    for sid, g in rows:
        if g.get("applies") and not g.get("passed"):
            refused[sid] = (f"{g.get('count')} independent source(s), "
                            f"{g.get('required')} required")
    return basis("the gate ran as `measure`: it recorded and rendered anyway", refused)


def _no_second_source(A):
    """`footage_indexer.no_second_source` (CF-0129 part 2): a topic whose pool
    holds fewer than `funnel.TWO_SOURCE_FLOOR` canonical sources is refused
    before the scenario, the TTS and the anchor resolve are paid for.

    Priced only on a batch whose indexer did not yet enforce it. The mark is
    `01b-footage-index.json` -> `two_source_floor`, which the stage began
    writing when it began refusing; before that it recorded `sources_by_topic`
    and carried the topic on regardless."""
    idx = A.get("01b-footage-index.json")
    if not idx:
        return no_basis("no 01b-footage-index.json: no source pool was recorded")
    sbt = idx.get("sources_by_topic")
    if not isinstance(sbt, dict):
        return no_basis("the indexer of this batch wrote no `sources_by_topic`")
    if idx.get("two_source_floor") is not None:
        return no_basis("the indexer already enforced the floor here "
                        "(`two_source_floor` is in the artifact)")
    refused = {t: f"{len(ids or [])} canonical source(s), {funnel.TWO_SOURCE_FLOOR} required"
               for t, ids in sbt.items() if len(ids or []) < funnel.TWO_SOURCE_FLOOR}
    return basis("the indexer recorded the pool and carried every topic on", refused)


def _stopcock(A):
    """`orchestrator.stopcock` (CF-0322): a batch whose Content Researcher wrote
    no script, and that has no reserve topic left to substitute, opens no
    further stage.

    The rule refuses no topic and no video - it declines to spend the stages
    after the Researcher - so its price is the number of ready videos it takes
    off a batch that had them, and `refused` is empty by construction. That is
    the honest answer and not a free pass, because of where the basis is drawn:

    * the Researcher wrote at least one script (`open`), or has a reserve topic
      left to spend (`refill`) -> the cock stays up, the batch runs to the end
      under the rule, and every ready video it made it would still have made.
      **Measured**, price 0.
    * the cock comes down -> the batch has 0 scripts, hence 0 ready videos, and
      counting its survivors would be the `no_basis` trap this module was
      written around: a 0 that means "measured nothing".
    * no `03` at all -> the Researcher never ran; nothing to judge."""
    if not isinstance(A.get(stopcock.RESEARCHER_FILE), dict):
        return no_basis(f"no {stopcock.RESEARCHER_FILE}: the Content Researcher did not run "
                        f"here, so the stop-cock had nothing to judge")
    v = stopcock.verdict(artifacts=A)
    if v["state"] in stopcock.STOPPED:
        return no_basis("the stop-cock comes down exactly when the Researcher wrote no script, "
                        "so this batch has no ready video for it to take - a price of 0 here "
                        "would mean `measured nothing`")
    return basis(f"the Researcher wrote {v['scripts']} script(s) and the cock stayed up "
                 f"(`{v['state']}`): the batch ran every stage it would have run anyway",
                 {})


# CF-0353 / CF-0357: the tail after the last anchor, as the Researcher froze it.
CADENCE_KEY = "anchor_cadence"      # `03-content-researcher.json#scripts[]`
TAIL_KEY = "tail"                   # the CF-0353 record inside it
TAIL_FLAT_KEY = "tail_deliverable"  # the same verdict, flattened beside it


def _cadence_records(A):
    """`[(item_id, anchor_cadence)]` - every cadence record this batch froze.

    The scripts the Researcher wrote carry theirs under their `script_id`; a
    `skipped` row carries a trimmed one and no script id, so it is keyed by its
    topic. A skipped topic never became a ready video and so can never be in
    `killed`; it is read anyway, because `refused` is every item the rule would
    have dropped, whether or not it ever became a video. None when the
    Researcher did not run here at all."""
    cr = A.get(stopcock.RESEARCHER_FILE)
    if not isinstance(cr, dict):
        return None
    out = []
    for key, rows in (("script_id", cr.get("scripts")), ("topic_id", cr.get("skipped"))):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ac, item = row.get(CADENCE_KEY), row.get("script_id") or row.get(key)
            if item and isinstance(ac, dict):
                out.append((item, ac))
    return out


def _tail_of(ac):
    """The tail record's verdict as a bool, or None when the batch did not read
    it - `deliverable: None` is the gate's own word for "not checked" (the
    Editor's layout was not built), and "not checked" is not a pass."""
    tail = ac.get(TAIL_KEY)
    tail = tail if isinstance(tail, dict) else {}
    for v in (tail.get("deliverable"), ac.get(TAIL_FLAT_KEY)):
        if isinstance(v, bool):
            return tail, v
    return tail, None


def _tail_reason(item, tail):
    worst = max((o for o in tail.get("over") or [] if isinstance(o, dict)),
                key=lambda o: o.get("excess_seconds") or 0.0, default={})
    where = (f"block {worst.get('block')} ({worst.get('role')}) runs "
             f"{worst.get('seconds')}s against its {worst.get('ceiling_seconds')}s ceiling"
             if worst else f"{tail.get('longest_block_seconds')}s in one block")
    return (f"the speech after {tail.get('last_anchor')} "
            f"({tail.get('speech_after_last_anchor_seconds')}s, "
            f"{tail.get('words_after_last_anchor')} word(s)) is laid out as "
            f"{tail.get('blocks')} block(s) and {where} - after the TTS the Editor "
            f"refuses that plan at `pattern_ceiling`, and there is no next block to "
            f"hand the remainder to")


def _tail_after_last_anchor(A):
    """`content_researcher.tail_after_last_anchor` (CF-0353): the speech after
    the last visual anchor is longer than the Editor can hand out in blocks
    inside the pattern's band, which the Editor answers at `pattern_ceiling`
    one wav too late (`everyday-sorcery-2`, 2026-09-15).

    Read, never recomputed: the reading lives in `check_anchor_cadence.py` of
    agents/content-researcher and its numbers come from the Editor's own layout
    (`plan_blocks.py`). What this module does is what it does with every other
    gate - read the record the stage froze into the batch:
    `03-content-researcher.json#scripts[].anchor_cadence.tail.deliverable`.

    The basis is the record's existence, and the shape is the `measure` mode of
    `two_source_gate`: this reading refuses nothing of its own (CF-0353 - the
    blocks it names are already failures of the `layout_block` / `estimate_margin`
    readings, and it spends no rewrite), so a batch that carries it is a batch
    that recorded the tail and wrote the script anyway. That is why the zero it
    reads is a measurement and not the survivorship this module exists to
    refuse: a ready video's script is in `scripts` with its own tail record, so
    every video the rule could take is on the page next to its verdict.

    No record - the batch ran before CF-0353, or before the Editor's layout was
    read at all (CF-0277) - is `no basis`, not a free pass."""
    recs = _cadence_records(A)
    if recs is None:
        return no_basis(f"no {stopcock.RESEARCHER_FILE}: the Content Researcher did not run "
                        f"here, so no tail was ever read")
    if not recs:
        return no_basis("no script carries an `anchor_cadence` record: the cadence gate had "
                        "not been written when this batch ran")
    read = [(item, *_tail_of(ac)) for item, ac in recs]
    read = [(item, tail, ok) for item, tail, ok in read if ok is not None]
    if not read:
        return no_basis("the cadence gate of this batch wrote no `tail` record (CF-0353, "
                        "2026-09-23): the tail after the last anchor was not read here")
    refused = {item: _tail_reason(item, tail) for item, tail, ok in read if not ok}
    return basis(f"the Researcher recorded the tail on {len(read)} script(s) and wrote them "
                 f"anyway: the reading names blocks the layout and margin readings already "
                 f"judged and refuses nothing of its own", refused)


# CF-0327: the inset panel the render delivered, as the Editor froze it.
PANEL_KEY = "panel_in_frame"      # `05-video-editor.json#videos[].qc`
PANEL_FAIL = "fail"               # the mode in which a cut panel refuses the render


def _panel_records(A):
    """`[(script_id, panel_in_frame)]` - every panel measurement this batch froze.

    A video whose record is absent, is not an object, or carries no `mode` is
    left out: those are the renders from before CF-0327 and the audio-only ones
    the gate never looked at, and "not measured" is not "measured and clean".
    None when the batch has no `05` at all."""
    ve = A.get("05-video-editor.json")
    if not isinstance(ve, dict):
        return None
    out = []
    for v in ve.get("videos") or []:
        if not isinstance(v, dict):
            continue
        qc = v.get("qc")
        rec = qc.get(PANEL_KEY) if isinstance(qc, dict) else None
        if v.get("script_id") and isinstance(rec, dict) and rec.get("mode"):
            out.append((v["script_id"], rec))
    return out


def _cut_blocks(rec):
    return [b for b in rec.get("cut_blocks") or [] if isinstance(b, dict)]


def _panel_reason(cut):
    """The sentence a reader gets for one refused video, out of `cut_blocks`."""
    idx = ", ".join(str(b.get("index")) for b in cut)
    why = next((b["reason"] for b in cut
                if isinstance(b.get("reason"), str) and b["reason"]), None)
    return f"block(s) {idx} deliver a cut-off inset panel" + (f": {why}" if why else "")


def _panel_in_frame(A):
    """`video_editor.panel_in_frame` (CF-0327): a block whose source carries an
    on-screen panel - a split screen, an article, a phone being read out - is
    framed so that a sliver of that panel arrives pressed against the edge of
    the frame and the rest of it is gone (`mormon-wives-comeback` at 29 s, the
    batch of 2026-09-23).

    Read, never recomputed. The measurement is the Editor's own
    (`agents/video-editor/scripts/{inset_panel,qc_render}.py`, which sample the
    source frame the way the subject gate samples it) and it is written on
    *every* video in every mode, the passed ones included - which is exactly
    what lets this be priced, because a price is a count of videos that were
    ready. This module reads `05-video-editor.json#videos[].qc.panel_in_frame`:
    `mode`, `blocks` (what was measured) and `cut_blocks` (what the gate
    refuses).

    The basis is the `measure` shape of `two_source_gate` once more: under
    `warn` and `off` the Editor records the cut panel and renders anyway, so
    the artifact carries the videos the gate would have taken. Under `fail` it
    does not - a cut-off panel is a failed render - and a batch whose every
    video ran under `fail` reads as no basis, because counting its survivors
    gives the 0 that means "measured nothing". No record at all - a batch from
    before CF-0327 - is no basis too, and not a price of zero."""
    recs = _panel_records(A)
    if recs is None:
        return no_basis("no 05-video-editor.json: the batch rendered nothing")
    if not recs:
        return no_basis("no video carries a `qc.panel_in_frame` record (CF-0327, "
                        "2026-09-24): the panel was never measured here")
    modes = sorted({str(rec.get("mode")) for _, rec in recs})
    if modes == [PANEL_FAIL]:
        return no_basis("the gate ran as `fail` on every video here, so a video with a "
                        "cut-off panel was never rendered - counting the survivors would "
                        "be a price of zero that measured nothing")
    refused = {}
    for sid, rec in recs:
        cut = _cut_blocks(rec)
        if cut:
            refused[sid] = _panel_reason(cut)
    measured = sum(len(rec.get("blocks") or []) for _, rec in recs)
    return basis(f"the gate ran as {'/'.join(modes)}: it measured {measured} block(s) "
                 f"carrying a panel across {len(recs)} video(s) and rendered them anyway",
                 refused)


# CF-0379: our own captions under a meme insert, as the render froze them.
MEME_BLOCKS = "meme_caption_blocks"        # blocks a meme stood on
MEME_BLANK = "meme_caption_blank_blocks"   # ... of which none of our words were drawn
MEME_MODE = "meme_caption_gate_mode"
MEME_FAIL = "fail"                         # the mode in which a blank block refuses


def _meme_caption_records(A):
    """`[(script_id, qc.measured)]` - every meme-caption measurement this batch
    froze.

    A video whose `qc.measured` carries no `meme_caption_gate_mode` is left
    out: those are the renders from before CF-0379 and the ones the gate never
    looked at, and "not measured" is not "measured and clean". None when the
    batch has no `05` at all."""
    ve = A.get("05-video-editor.json")
    if not isinstance(ve, dict):
        return None
    out = []
    for v in ve.get("videos") or []:
        if not isinstance(v, dict):
            continue
        qc = v.get("qc")
        m = qc.get("measured") if isinstance(qc, dict) else None
        if v.get("script_id") and isinstance(m, dict) and m.get(MEME_MODE):
            out.append((v["script_id"], m))
    return out


def _meme_count(m, key):
    n = m.get(key)
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def _meme_captions(A):
    """`video_editor.meme_captions` (CF-0379): a block that a meme insert holds
    while not one of our word-by-word captions is drawn on it, with the voice
    still speaking - the defect the user found on 2026-09-24, where the meme's
    whole span played as a silent picture with the narration unwritten.

    Read, never recomputed. The measurement is the Editor's own (it is taken at
    render QC and written on *every* video in every mode, the passed ones
    included - which is what lets this be priced, because a price is a count of
    videos that were ready). This module reads
    `05-video-editor.json#videos[].qc.measured`: `meme_caption_gate_mode`,
    `meme_caption_blocks` (what was measured) and `meme_caption_blank_blocks`
    (what the gate refuses).

    The basis is the `measure` shape of `two_source_gate` once more, and the
    same shape `panel_in_frame` (CF-0327) uses: under `warn` and `off` the
    Editor records the blank block and renders anyway, so the artifact carries
    the videos the gate would have taken. Under `fail` it does not - a meme
    with no captions under it is a failed render - and a batch whose every
    video ran under `fail` reads as no basis, because counting its survivors
    gives the 0 that means "measured nothing". No record at all - a batch from
    before CF-0379 - is no basis too, and not a price of zero."""
    recs = _meme_caption_records(A)
    if recs is None:
        return no_basis("no 05-video-editor.json: the batch rendered nothing")
    if not recs:
        return no_basis(f"no video carries a `qc.measured.{MEME_MODE}` record (CF-0379, "
                        f"2026-09-24): our captions under a meme were never measured here")
    modes = sorted({str(m.get(MEME_MODE)) for _, m in recs})
    if modes == [MEME_FAIL]:
        return no_basis("the gate ran as `fail` on every video here, so a video with a "
                        "caption-less meme was never rendered - counting the survivors "
                        "would be a price of zero that measured nothing")
    refused = {}
    for sid, m in recs:
        blank = _meme_count(m, MEME_BLANK)
        if blank:
            refused[sid] = (f"{blank} block(s) carry a meme with not one of our words "
                            f"drawn on them")
    measured = sum(_meme_count(m, MEME_BLOCKS) for _, m in recs)
    return basis(f"the gate ran as {'/'.join(modes)}: it measured {measured} block(s) "
                 f"carrying a meme across {len(recs)} video(s) and rendered them anyway",
                 refused)


# CF-0329: the safe area of the graphic layer against the player's own cut.
# The live gate is `agents/video-editor/scripts/safe_area.py#survives_the_cut`,
# which `qc_render` calls on the plan before it looks at a pixel; it is loaded
# here by path and never re-typed, so the price is the gate's own answer.
SAFE_AREA = ROOT / "agents" / "video-editor" / "scripts" / "safe_area.py"
SAFE_AREA_FAILURE = "inside the player's own cut"   # qc_render's own words
_safe_area_mod = []


def _safe_area_module():
    """The Editor's `safe_area` module, or None when this checkout has no
    Editor beside it (a root-only clone): then the rule has no basis, which is
    not a price of zero."""
    if not _safe_area_mod:
        mod = None
        if SAFE_AREA.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location("safe_area", SAFE_AREA)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        _safe_area_mod.append(mod)
    return _safe_area_mod[0]


def _plan_of(batch_dir, video):
    """The frozen render plan a video was rendered from, or None.

    The Editor writes it to `work/<slug>/plan.json` and names the video
    `videos/<slug>.mp4`, so the slug is the stem of `output_path`. A batch
    whose videos were named by script id (`legacy-film/2026-08-30T1759Z`)
    or whose `work/` was cleared (`example-film/2026-09-15T1034Z`) has no plan
    to find, and the video is left out rather than guessed at."""
    out = video.get("output_path")
    if not out:
        return None
    p = Path(batch_dir) / "work" / Path(out).stem / "plan.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _safe_area(A):
    """`video_editor.safe_area` (CF-0329): a plan whose stated left or right
    safe zone is narrower than what the player cuts off the side of a 9:16
    frame on the narrowest screen we render for - the defect the user found on
    the channel's first published Short, `outrider-doune-castle`, where
    "filmed" read as "ilmed" on a real phone. `qc_render` refuses such a plan
    before it looks at a pixel.

    Replayed, not read: the gate writes no record of its own onto a video, but
    the plan it judges is frozen beside the artifacts, and the gate is a pure
    function of `plan["safe_zones"]`. So every plan of every rendered video is
    run through the live `survives_the_cut` - the refused ones included, which
    is what keeps this off the survivorship trap: a plan the gate took is still
    on disk and is still replayed.

    The one case that is no basis is a batch the gate already refused a video
    in (its sentence is in `qc.failures`): that video was never ready, so
    whether the gate cost it cannot be read off the batch."""
    ve = A.get("05-video-editor.json")
    if not isinstance(ve, dict):
        return no_basis("no 05-video-editor.json: the batch rendered nothing")
    bd = A.get(BATCH_DIR_KEY)
    if bd is None:
        return no_basis("no batch directory was handed in: the render plans live under "
                        "`work/`, not in a stage artifact")
    sa = _safe_area_module()
    if sa is None:
        return no_basis("agents/video-editor/scripts/safe_area.py is not in this checkout, "
                        "so the live gate cannot be replayed")
    videos = [v for v in ve.get("videos") or [] if isinstance(v, dict) and v.get("script_id")]
    for v in videos:
        qc = v.get("qc") if isinstance(v.get("qc"), dict) else {}
        if any(SAFE_AREA_FAILURE in str(f) for f in qc.get("failures") or []):
            return no_basis("the gate already refused a video here, so that video was never "
                            "ready - the batch cannot say what the gate cost it")
    refused, plans = {}, 0
    for v in videos:
        plan = _plan_of(bd, v)
        if plan is None:
            continue
        plans += 1
        bad = sa.survives_the_cut(plan.get("safe_zones"))
        if bad:
            refused[v["script_id"]] = "; ".join(
                f"safe zone {side}={have} is inside the player's own cut of {need} per side"
                for side, have, need in bad)
    if not plans:
        return no_basis("no rendered video left its `work/<slug>/plan.json` behind: the plans "
                        "were cleared or named apart from the video")
    return basis(f"the live gate replayed over the frozen plans of {plans} of {len(videos)} "
                 f"rendered video(s)", refused)


# CF-0480 / CF-0472: "the pool does not hold this video", as the Editor froze it.
POOL_HOLDS_KEY = "pool_holds"       # `work/<slug>/plan.json#pool_holds`
POOL_HOLDS_SHORT = "short"          # still_share.POOL_SHORT


def _pool_holds(A):
    """`video_editor.pool_holds_video` (CF-0480 item 3): the one-frame blocks
    the resolver could not cut into 2-3 shots of their phrase
    (`stretch_split.short`) leave the video over the stretched line (pictures +
    stretched held frames over 50 %) - the pool's shortage, not the montage's
    choice. The Editor writes the verdict onto the plan
    (`plan["pool_holds"]`, built by `still_share.pool_holds`) and, being an
    unsigned new refusal, only a WARNING (`pool_too_thin`) - the plan is written.

    Read, never recomputed: `stretch_split` exists only on plans resolved by
    CF-0480's resolver, so a plan without `pool_holds` cannot say what the
    gate would have done - `no basis`, not a zero. Every rendered video with a
    plan is read, not only the survivors: the gate refuses nothing yet, so a
    `short` plan is still a rendered video next to its verdict."""
    ve = A.get("05-video-editor.json")
    if not isinstance(ve, dict):
        return no_basis("no 05-video-editor.json: the batch rendered nothing")
    bd = A.get(BATCH_DIR_KEY)
    if bd is None:
        return no_basis("no batch directory was handed in: the render plans live under "
                        "`work/`, not in a stage artifact")
    refused, read = {}, 0
    for v in ve.get("videos") or []:
        if not isinstance(v, dict) or not v.get("script_id"):
            continue
        plan = _plan_of(bd, v)
        rec = (plan or {}).get(POOL_HOLDS_KEY)
        if not isinstance(rec, dict) or not rec.get("verdict"):
            continue
        read += 1
        if rec["verdict"] == POOL_HOLDS_SHORT:
            n = len(rec.get("short_blocks") or [])
            refused[v["script_id"]] = (
                f"the pool does not hold the video: {rec.get('share')} of it stands still "
                f"(over {rec.get('from')}), {n} one-frame block(s) had no second shot of "
                f"their phrase - `pool_holds_video` (funnel `pool_too_thin`)")
    if not read:
        return no_basis("no rendered video's plan carries `pool_holds`: the plans were "
                        "built before CF-0480's stretch split (2026-10-01), so the gate "
                        "was never read here")
    return basis(f"the Editor recorded `pool_holds` on {read} plan(s) and rendered them: "
                 f"the gate warns and refuses nothing of its own", refused)


def _foreign_core(A):
    """`frame_judge.foreign_core` (CF-0539, WNL of example-film/2026-10-05T0701Z):
    a judged video with a `foreign` entry in the hook or `foreign` over
    `funnel.FOREIGN_SHARE_MAX` of the judged time - recomputed off the verdict
    rows of the frozen `06-frame-judge.json` by the same function the gate calls
    (`funnel.foreign_core`), so the replay and the gate cannot drift.

    A 06 that ran the rule as `fail` is priced too (CF-0767). The rule is the
    last word of the frame judge's gate (scripts/frame_judge_gate.py: an
    unfinished judgement, a hard footage defect and a score under N all answer
    first), and the judge records every video it judged with its verdict rows,
    the refused ones included. So a video refused as `judge_foreign_core` is a
    video every other check passed - exactly the ready video the rule took -
    and it is on the page next to its verdict, which is not the survivorship a
    Video Editor gate leaves (its victims are never rendered). The replay hands
    the batch back with those refusals taken back (`undone`), and the price is
    read off that. Without it a signed `fail` measures itself out of its own
    window: from example-tech/2026-10-16T0702Z every batch in the window had
    either run the rule as `fail` or judged nothing, and the triage filed the
    signed refusal as unpriced.

    `no basis` where the batch cannot say what the rule would have done: no
    06 (never judged); `frame-judge/1` (2026-09-20 .. 2026-09-29), which
    refused every `foreign` itself, so the rule would find only survivors; and
    a 06 with no complete judgement."""
    fj = A.get(funnel.FRAME_JUDGE_FILE)
    if not isinstance(fj, dict):
        return no_basis("no 06-frame-judge.json: the batch was never judged")
    if fj.get("schema") == funnel.FRAME_JUDGE_SCHEMA_V1:
        return no_basis("judged under frame-judge/1, which refused every `foreign` by itself - "
                        "the rule would read only the survivors")
    mode = ((fj.get("rule") or {}).get("foreign_core") or {}).get("mode")
    refused, read, took = {}, 0, []
    for v in fj.get("videos") or []:
        if not isinstance(v, dict) or not v.get("script_id"):
            continue
        if v.get("gate") == funnel.GATE_INCOMPLETE:
            continue
        read += 1
        fc = funnel.foreign_core(v.get("verdicts"))
        if fc["refuses"]:
            refused[v["script_id"]] = fc["why"]
        if v.get("gate") == funnel.GATE_REJECT and v.get("reason_code") == funnel.JUDGE_FOREIGN_CORE:
            took.append(v["script_id"])
    if not read:
        return no_basis("06-frame-judge.json carries no complete judgement")
    for sid in took:
        # the gate's own record says the rule refused it; the rows must agree
        refused.setdefault(sid, "refused as `judge_foreign_core` by the frame judge's gate")
    undone = {}
    if took:
        doc = dict(fj)
        doc["videos"] = [dict(v, gate=funnel.GATE_PASS, reason_code=None, reason=None)
                         if isinstance(v, dict) and v.get("script_id") in took else v
                         for v in fj.get("videos") or []]
        undone[funnel.FRAME_JUDGE_FILE] = doc
    if mode == funnel.FOREIGN_CORE_FAIL:
        how = (f"the rule ran as `fail` here and the judge recorded all {read} judged "
               f"video(s) with their rows; "
               + (f"the {len(took)} it refused are taken back and priced as the ready "
                  f"video(s) they would have been" if took else
                  "it refused none of them, so the batch ended as it would have without it"))
    else:
        how = (f"the frame judge's verdict rows of {read} judged video(s), replayed through "
               f"funnel.foreign_core (mode {mode or 'absent - judged before CF-0539'})")
    return basis(how, refused, undone)


RULES = {
    "frame_judge.foreign_core": Rule(
        "frame_judge.foreign_core", WHAT_VIDEO, _foreign_core,
        note="CF-0539 (WNL of example-film/2026-10-05T0701Z: an interview of the host on "
             "another talk show's set under the story's opening words, three `foreign` "
             "entries, -36, passed at E 64 over N 40): the frame judge's gate refuses a "
             "video at or over N when a `foreign` entry starts in the hook (< 5 s) or "
             "`foreign` covers 15 % of the judged time or more - funnel code "
             "`judge_foreign_core`. A new refusal, unsigned (CF-0320): `warn` in "
             "channels/example-film.json (`frame_judge.foreign_core.mode`) and in the code's "
             "default - `Rule.mode` warn (CF-0472). Over every judged batch on disk "
             "(2026-10-05) it refuses 0 videos the user accepted (their foreign share at "
             "most 6 %, never in the hook).",
        mode=CODE_WARN),
    "video_editor.pool_holds_video": Rule(
        "video_editor.pool_holds_video", WHAT_VIDEO, _pool_holds,
        note="CF-0480 item 3 (vanguards-doomsday 1313Z, refused by the user for stop-frames): "
             "the one-frame blocks the resolver could not cut into 2-3 shots of their "
             "phrase (`stretch_split.short`) leave the video over the stretched line - the "
             "plan says \"the pool does not hold this video\", gate `pool_holds_video`, "
             "funnel `pool_too_thin`, the topic's supplement request named. A new refusal, "
             "unsigned (CF-0320): the Editor writes a WARNING (`plan_refusal.warning`) and "
             "the plan is written - `Rule.mode` warn (CF-0472). The machine replay reads "
             "`no basis` until a batch renders on the 1.5 line: `plan.json#pool_holds` is "
             "younger than every frozen batch.",
        mode=CODE_WARN),
    "video_editor.safe_area": Rule(
        "video_editor.safe_area", WHAT_VIDEO, _safe_area,
        note="CF-0329: a plan whose stated left or right safe zone is inside the cut the "
             "player makes off the sides of a 9:16 frame on a 20:9 phone (0.10 per side) - "
             "the defect the user found on the channel's first published Short, "
             "`outrider-doune-castle`, where the proof card read \"ilmed\" for \"filmed\" "
             "and the watermark lost its first letters. `qc_render` refuses such a plan "
             "before the render, hard-wired, with no channel switch. Replayed by machine "
             "over the frozen `work/<slug>/plan.json` of every rendered video through the "
             "live `agents/video-editor/scripts/safe_area.py#survives_the_cut`. Every plan "
             "the planner wrote before 2026-09-23 carries left 0.04 and is refused; every "
             "plan since carries 0.116 and passes, so the gate can only ever refuse a stale "
             "plan, never a new one. Over every batch on disk (2026-09-26): 17 of 20 "
             "priceable ready videos, i.e. all 17 pre-fix ready videos whose plan survived, "
             "and none of the 3 after. Of the 5 videos the user accepted "
             "(publish/acceptance-log.json) it refuses 1 - `outrider-doune-castle`, which "
             "is the video that carries the defect; `american-dread-story`, `paper-dragon`, "
             "`you-can-see-everything` (example-film/2026-09-23T1722Z) and the published "
             "`widows-bay` (pipeline/rebuilds/2026-09-23T1053Z) were planned after the fix "
             "and pass. That 1 is the whole price over the window below."),
    "video_editor.panel_in_frame": Rule(
        "video_editor.panel_in_frame", WHAT_VIDEO, _panel_in_frame,
        note="CF-0327: a block that delivers a sliver of an on-screen panel pressed against "
             "the edge of the frame - the defect the user found on `mormon-wives-comeback` "
             "at 29 s. The planner now asks where the panel is (in the frame at >= 0.9, or "
             "out of it at <= 0.05; the middle is refused) and moves the window only when "
             "the subject survives the move. Priced by hand on 2026-09-24 by replaying the "
             "live gate over the frozen plans of the window: 6 videos, 64 blocks, a panel on "
             "4 of them, a cut-off one on 2 - both in `mormon-wives` of "
             "example-film/2026-09-23T1722Z, and the planner heals neither (every window it "
             "could shift takes the face under the subject floor). In `fail` the rule would "
             "have killed 1 ready video, which is why channels/example-film.json carries "
             "`video_editor.panel_in_frame.mode: warn`. The machine replay below reads `no "
             "basis`: the field is younger than every frozen batch in the window."),
    "video_editor.meme_captions": Rule(
        "video_editor.meme_captions", WHAT_VIDEO, _meme_captions,
        note="CF-0379: a block a meme insert holds while not one of our word-by-word "
             "captions is drawn on it - the defect the user found on 2026-09-24, watching "
             "the meme's whole span play as a silent picture with the narration unwritten. "
             "The silencing was never a decision about memes: render/src/Video.jsx keyed on "
             "`block.insert` alone and the meme inherited CF-0071's rule for the proof "
             "layer, where it is right and stays. So `inserts/meme.json` now says "
             "`composition.our_captions: shown`, the caption band lifts above the insert for "
             "its span instead of the meme moving, and the render QC counts the blocks where "
             "our words are still missing. The machine replay below reads `no basis`: the "
             "field `05-video-editor.json#videos[].qc.measured.meme_caption_blocks` is "
             "younger than every frozen batch of the window, and `no basis` is not a price "
             "of zero. Unpriced, the rule stands as a warning by ROADMAP `## Versioning`, "
             "which is why channels/example-film.json carries "
             "`video_editor.meme_captions.mode: warn` against the Editor's own `fail` "
             "default. Only the user's signature under a measured price turns it into a "
             "refusal."),
    "content_researcher.tail_after_last_anchor": Rule(
        "content_researcher.tail_after_last_anchor", WHAT_VIDEO, _tail_after_last_anchor,
        note="CF-0353: the speech after the last visual anchor, laid out in the Editor's own "
             "blocks - the refusal the Editor makes at `pattern_ceiling` after the TTS, read "
             "at the Researcher before the voice is paid for. Priced by hand in CF-0353 by "
             "replaying the live gate over each batch's frozen `03`: 0 of the 1 ready video "
             "of the last five batches, and 1 of the 5 in the window before CF-0277 - "
             "`everyday-sorcery-2`, the video the user pulled himself on 2026-09-23. "
             "CF-0472 (2026-10-02): the code refuses nothing since CF-0433/CF-0447 - the "
             "cadence gate prices the hold band (`anchor_cadence.verdict: priced`) and the "
             "tail spends no rewrite - so the registry states its mode as `measure` and the "
             "triage no longer reads it as hard-wired. Re-measured over the window to "
             "example-film/2026-10-01T2210Z: 1 of 12 ready videos, `coach-hale` of "
             "2026-10-01T1313Z - accepted by the user (84, B); its tail was over only the "
             "estimate's margin (2.49 s against 2.125 s, the band top 2.5 s) and its real "
             "last block ran 1.28 s. As a refusal the rule would kill an accepted video: it "
             "stays a reading. The defect it was written for (`everyday-sorcery-2`, a 13.52 s "
             "last block against `list`'s 2.5 s) is priced in the score model instead - "
             "`score.tail_over_band_top` (-6/s over the band top, cap 66), signed by the "
             "user 2026-10-02 and moved into `rules` (CF-0490).",
        mode=CODE_MEASURE),
    "orchestrator.stopcock": Rule(
        "orchestrator.stopcock", WHAT_VIDEO, _stopcock,
        note="CF-0322: 0 scripts out of the Content Researcher with nothing left to "
             "substitute closes the batch. It refuses no topic and no video - it only "
             "declines to spend the stages after a batch with no material - so on every "
             "batch that can price it the cost is 0 ready videos."),
    "video_editor.two_source_gate": Rule(
        "video_editor.two_source_gate", WHAT_VIDEO, _two_source_gate,
        note="CF-0118 measured it, CF-0129 switched it to `enforce` on 2026-09-16 - "
             "the flip the yield fell from 1.0 to 0.2 ready videos per batch across, "
             "and the reason this whole check exists."),
    "footage_indexer.no_second_source": Rule(
        "footage_indexer.no_second_source", WHAT_TOPIC, _no_second_source,
        note="CF-0129 part 2, the guarantee that made the flip above safe: a topic under "
             "the source floor is refused at the indexer instead of at the render."),
}


def rule(name):
    r = RULES.get(name)
    if r is None:
        raise KeyError(f"no such rule: {name} (have: {', '.join(sorted(RULES))})")
    return r


def measure_all(names=None, **kw):
    return [price(rule(n), **kw) for n in (names or sorted(RULES))]


# --------------------------------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog gate-price",
                                 description="what a refusal would have cost in ready "
                                             "videos (CF-0320)")
    ap.add_argument("--rule", action="append", default=None,
                    help=f"a registered rule; repeatable. Default: all of "
                         f"{', '.join(sorted(RULES))}")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--before", default=None,
                    help="price the rule over the window as it stood before this day "
                         "(YYYY-MM-DD) or batch id")
    ap.add_argument("--pool", default=None, help="the pipeline/ directory to read")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help=f"record the measurements in {LEDGER.name} and {STATS.name}")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        names = ns.rule or sorted(RULES)
        results = [price(rule(n), pool=ns.pool, window=ns.window, before=ns.before)
                   for n in names]
    except KeyError as e:
        sys.stderr.write(f"runlog gate-price: error: {e.args[0]}\n")
        return 2
    if ns.write:
        # The ledger and the statistics always carry every rule: a `--rule`
        # narrows what is printed, never what is on the record. Half a ledger
        # written by a narrowed call would read as "the other rule was not
        # measured", which is the one thing this module must never say by
        # accident.
        every = (results if names == sorted(RULES)
                 else measure_all(pool=ns.pool, window=ns.window, before=ns.before))
        write_ledger(every)
        write_stats(every)
    if ns.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        for res in results:
            print("\n".join(render(res)))
            print()
    # 1 when any rule may not land as a refusal - the exit code CF-0319's triage
    # script reads, so that a warning is a result and not a line of prose.
    return 0 if all(r["verdict"] in (ENFORCE, PENALTY) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
