"""CF-0317: the seven places this stage used to end in a person, and the code
each of them ends with now.

    from _no_waiting import EXIT_CANNOT_ANSWER, refuse

    print(refuse("researcher_missing_repo_asset", file="inserts/meme.json"),
          file=sys.stderr)
    return EXIT_CANNOT_ANSWER

**The defect.** `example-film/2026-09-19T0116Z` stood 6 h 19 m 36 s of a
39 h 42 m wall waiting for somebody to come back to the keyboard, and the
user's decision of 2026-09-22 (Q19) is general: in an autonomous run no stage
may block on a decision that needs a human. Everything that would have asked
becomes a recorded outcome and the run goes on; the person reads it afterwards.

**Why this file and not seven strings in five scripts.** The register lives at
the root (`shared/runlog/no_waiting.py`), and its codes are the vocabulary the
`waits` / `wait_codes` fields of the `pipeline/runs.jsonl` row and
`no_waiting.classify()` read. A second spelling of one of them does not fail
loudly - it files the record under nothing at all, which is exactly the state
this task exists to end. So the five checkers of this repo spell each code
**once**, here, and `tests/test_no_waiting.py` asserts every one of them
against the root's `no_waiting.CODES` letter for letter.

**Why the note matters as much as the code.** This stage has seven entries in
the register and one stage name, so `classify()` tells them apart by the words
of the `stage-done` note the wait began at (`no_waiting._HINTS`). `NOTES` below
is that contract: each template carries the word its own entry is recognised by
and none of the words of an entry listed before it. `tests/test_no_waiting.py`
runs every note of this file through the root's classifier and asserts it comes
back as its own point - which is the only way to keep a note that reads well
from quietly becoming a note that reads as another point.

**What this file is not.** It is not a policy. It decides nothing about a
script and it never repairs anything: it formats the one line a checker prints
before exiting 3, so that the code recorded is the one the script named and not
one the reader of a traceback chose. Every refusal to guess in this repo stays
exactly as it was - no invented verdicts, no invented shots, no invented
budget, and never a word count divided by `words_per_second` (`CF-0279`).
"""

# "this environment could not answer" - the code `check_anchor_cadence.py`,
# `check_anchor_coverage.py` and `check_narration_budget.py` already exit with
# for the same shape of event. Deliberately not 1: exit 1 tells the writer a
# script has to be rewritten, and none of the seven points below is about any
# script.
EXIT_CANNOT_ANSWER = 3

# point id -> the code its outcome records. The root register is the authority;
# these are asserted against it in tests/test_no_waiting.py.
CODES = {
    "researcher_empty_shortlist": "empty_shortlist_close",
    "researcher_missing_upstream": "missing_upstream_file_skip",
    "researcher_missing_repo_asset": "missing_repo_asset_skip",
    "researcher_stale_cache": "stale_cache_auto_remeasure_retry",
    "researcher_env_broken": "env_broken_skip",
    "researcher_missing_channel_config": "missing_channel_config_skip",
    "researcher_estimator_unavailable": "estimator_unavailable_skip",
}

# point id -> the `stage-done --note` the stage closes with. The wording is a
# contract with `no_waiting.classify()`, not prose: see the module docstring.
NOTES = {
    "researcher_empty_shortlist": "0 eligible topics, no scripts written",
    "researcher_missing_upstream": "{file} is missing, no scripts written",
    "researcher_missing_repo_asset": "{file} is missing, no scripts written",
    "researcher_stale_cache": "stale pool measurements, remeasured once and "
                              "retried, still refused",
    "researcher_env_broken": "anchor_coverage cannot answer: {cause}, nothing judged",
    # `what` is `narration_budget` or `channel config`; both are hint words of
    # this point, and both are the same fact - a channel that is not configured.
    "researcher_missing_channel_config": "no {what} for {channel}, nothing judged",
    "researcher_estimator_unavailable": "the narration estimator is unavailable, "
                                        "nothing judged",
}

# Blanks a template fills in for itself when the caller has nothing better.
DEFAULTS = {
    "researcher_missing_channel_config": {"what": "narration_budget"},
}

# The prefix of the line a checker prints. One spelling, because a reader - and
# the operator's grep - looks for exactly this.
PREFIX = "no-waiting"


class CannotAnswer(Exception):
    """A checker of this stage could not put its question, and says which
    register point that is instead of raising a traceback at a person.

    It is here rather than in each checker because the point and the fields
    that fill its note travel together with the message, and because a fourth
    private copy of this class is a fourth chance for one of them to be
    forgotten. `check_anchor_coverage.py` subclasses it to give `point` a
    default; the three insert checkers raise it directly.
    """

    def __init__(self, message, point, **fields):
        super().__init__(message)
        self.point = point
        self.fields = fields

    def note_fields(self):
        return dict(self.fields)


def note(point, **fields):
    """The `stage-done` note for this point, with its blanks filled in."""
    filled = dict(DEFAULTS.get(point) or {})
    filled.update(fields)
    fields = filled
    try:
        return NOTES[point].format(**fields)
    except KeyError as exc:
        raise KeyError(f"_no_waiting: {point!r} has no note, or no {exc} to fill it "
                       f"with") from None


def code(point):
    return CODES[point]


def refuse(point, why=None, **fields):
    """The line a checker prints on stderr immediately before returning
    `EXIT_CANNOT_ANSWER`. One line, three parts: the code to record, the note
    to close the stage with, and - when the caller has one - what actually
    happened.

    It is printed rather than raised because the checkers of this stage are
    read by a person and by an operator's grep in the same pass, and because
    the caller decides what else belongs on stderr around it.
    """
    line = (f"{PREFIX}: {code(point)} - close the stage with "
            f"`stage-done content-researcher --note \"{note(point, **fields)}\"` "
            f"and let the run go on (CF-0317)")
    return f"{line}\n  {why}" if why else line
