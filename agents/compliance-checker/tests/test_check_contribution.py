#!/usr/bin/env python3
"""CF-0187: Compliance Checker's substance layer for the production fact.

Separate from the shape layer (`agents/content-researcher/scripts/
check_production_fact.py`, CF-0183, which catches a missing or malformed
field) and separate from this agent's own rights/risk verdict
(clear|caution|review). Takes over from CF-0066, whose comparison checks went
with the position CF-0181 cancelled.

The three acceptance criteria of the task are
`test_criterion_1_fact_rewritten_from_the_news_is_blocked`,
`test_criterion_2_a_general_phrase_instead_of_a_fact_is_blocked` and
`test_criterion_3_a_concrete_fact_with_a_working_link_passes`. They are built
on one fixture pair - LEAD and SCRIPT below - so that the only difference
between the three cases is the fact under test.

**Where the fixture comes from, and why it is frozen here.** The lead is the
real one from `pipeline/legacy-film/2026-09-09T2031Z`, topic
`lf-2026-09-09-001` (the Venice ovation): its two scene descriptions and
three of its nine source titles, copied verbatim on 2026-09-14. The facts
grafted onto it are written for these tests - no batch in the pipeline
carries a `production_fact` yet, because every batch was written before
CF-0183 and the source (CF-0184) is an open decision. So these are the
judge's own tests on data built for them, which is a legitimate test of a
judge and is not the same claim as "this ran on a real batch". What did run
on the real batch is recorded in the task file: five scripts, five
`not judged`, nothing blocked, because none of them carries a fact.

The fixture is frozen into this file rather than read from `pipeline/` on
purpose: `pipeline/` is gitignored in the root repo, so a test reading it
would SKIP on a fresh checkout, and a SKIP that counts as a pass is the
failure mode this repo's runner was written against (CF-0054). Nothing here
touches the network or the disk outside a temporary directory.

No pytest dependency - plain asserts, dual-mode (pytest can also collect the
test_* functions directly), matching this repo's other tests.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_contribution as cc  # noqa: E402

CHANNEL = "example-film"

# --- the fixture ------------------------------------------------------
#
# One topic as Trend Hunter writes it, and one script written from it. This
# is the whole world the judge gets to see at stage 03.

LEAD = {
    "topic_id": "lf-2026-09-09-001",
    "title_ref": {"name": "Bunker", "season": None, "rights_holder": None},
    "scenes": [
        {"scene_id": "lf-2026-09-09-001-s1",
         "description": "Paloma Cortes and Javier Barros, a real-life married "
                        "couple playing a married couple in crisis on screen "
                        "for the first time, received a 16-minute standing "
                        "ovation at the Venice premiere of 'Bunker' -- the "
                        "longest of the festival so far -- with Cruz breaking "
                        "into sobs and kissing Bardem during the applause.",
         "tags": ["emotional", "relationship_moments"]},
        {"scene_id": "lf-2026-09-09-001-s2",
         "description": "Critics split hard on 'Bunker': Deadline and The "
                        "Hollywood Reporter called Bardem and Cruz 'riveting' "
                        "and 'brilliant' in Florian Zeller's drama about an "
                        "architect who takes an ethically questionable "
                        "commission to build a survivalist bunker for a tech "
                        "billionaire, while Vulture's review called the film "
                        "'a crushing disappointment'.",
         "tags": ["controversial"]},
    ],
    "evidence": {
        "rss_links": [
            "https://deadline.com/2026/09/bunker-paloma-cortes-javier-barros-venice-ovation-1237070708/",
            "https://variety.com/2026/film/festivals/paloma-cortes-javier-barros-bunker-venice-premiere-1236844863/",
        ],
        "sources": [
            {"url": "https://deadline.com/2026/09/bunker-paloma-cortes-javier-barros-venice-ovation-1237070708/",
             "title": "'Bunker' Starring Paloma Cortes & Javier Barros Earns "
                      "16-Minute Venice Ovation, Longest Of Festival So Far",
             "publication": "Deadline"},
            {"url": "https://variety.com/2026/film/festivals/paloma-cortes-javier-barros-bunker-venice-premiere-1236844863/",
             "title": "Paloma Cortes Sobs and Kisses Javier Barros as 'Bunker' "
                      "Dazzles Venice With Record 15.5-Minute Ovation",
             "publication": "Variety"},
            {"url": "https://www.hollywoodreporter.com/movies/movie-reviews/bunker-review-1236687273/",
             "title": "'Bunker' Review: Paloma Cortes and Javier Barros Are "
                      "Riveting as a Marriage Comes Apart",
             "publication": "The Hollywood Reporter"},
        ],
    },
}

# The retelling, and the beat the fact is spoken in. `BEAT` is a verbatim
# contiguous substring of `commentary` - CF-0183's rule, and the reason the
# beat can be subtracted from the retelling before the fact is compared
# against it.
BEAT = ("Zeller had the whole bunker built inside a decommissioned shelter "
        "outside Madrid.")
COMMENTARY = (
    "Deadline and The Hollywood Reporter call the marriage drama riveting; "
    "Vulture calls the whole film a crushing disappointment. The ovation is "
    "the bigger story, and Venice has not clapped that long all festival. "
    + BEAT +
    " Nineteen days in the concrete, and you can hear the room in every line.")

SCRIPT = {
    "script_id": "lf-2026-09-09-001-script1",
    "topic_id": "lf-2026-09-09-001",
    "title_ref": {"name": "Bunker", "season": None, "rights_holder": None},
    "hook": "Venice clapped for sixteen minutes and Cruz cried through it.",
    "commentary": COMMENTARY,
    "payoff": "The longest ovation of the festival, and nobody in the room "
              "sat down.",
    "proofs": [{
        "proof_id": "p1",
        "verbatim_text": "Paloma Cortes Sobs and Kisses Javier Barros as "
                         "'Bunker' Dazzles Venice",
        "source": {
            "url": "https://variety.com/2026/film/festivals/paloma-cortes-javier-barros-bunker-venice-premiere-1236844863/",
            "publication": "Variety",
            "title": "Paloma Cortes Sobs and Kisses Javier Barros as 'Bunker' "
                     "Dazzles Venice With Record 15.5-Minute Ovation"},
    }],
}

GOOD_SOURCE = "https://example.org/bunker/production#filming"


def with_fact(text, *, source_url=GOOD_SOURCE, beat=BEAT, on_screen=None,
              script=None):
    """The fixture script carrying `text` as its production fact. The shape
    is always the one CF-0183's validator would accept, so that whatever
    these tests catch is substance and not shape."""
    s = copy.deepcopy(script or SCRIPT)
    s["production_fact"] = {"text": text, "beat_text": beat,
                            "source_url": source_url, "on_screen": on_screen}
    return s


# --- the primitives ---------------------------------------------------


def test_jaccard_word_overlap():
    """Sanity on the symmetric measure: disjoint vocabulary -> 0, identical
    text -> 1, and stopwords/short words don't count toward overlap."""
    assert cc.jaccard("", "anything") == 0.0
    assert cc.jaccard("the a of is", "the a of is") == 0.0, \
        "pure stopwords should not register as overlap"
    assert cc.jaccard("a lone dancer under blue light",
                      "a lone dancer under blue light") == 1.0
    assert 0.0 < cc.jaccard("husband massive trauma seventy-six seconds",
                            "husband trauma quote unrelated words here") < 1.0


def test_containment_asks_how_much_of_the_fact_the_story_already_had():
    """The asymmetry is the point: a one-sentence fact copied out of a long
    lead is almost entirely contained in it, while the lead is barely
    contained in the fact. Jaccard cannot see that difference - it reports a
    small number for both - which is why the absence question is decided on
    containment and not on it."""
    fact = "Cruz broke into sobs during the sixteen-minute ovation"
    lead = " ".join(s["description"] for s in LEAD["scenes"])
    assert cc.containment(fact, lead) > 0.7
    assert cc.containment(lead, fact) < 0.2
    assert cc.jaccard(fact, lead) < 0.2, (
        "the symmetric measure would not have caught this, which is the "
        "reason containment exists here")
    assert cc.containment("", lead) == 0.0 and cc.containment(fact, "") == 0.0


def test_shared_phrase_finds_a_clause_lifted_out_of_the_lead():
    """A long fact that quotes one clause of the lead and pads it out scores
    low on containment and is still a copy, so a run of content words in the
    same order is checked separately."""
    lead = LEAD["scenes"][0]["description"]
    lifted = ("A crew member told us that Cruz breaking into sobs and kissing "
              "Bardem during the applause was the moment the producers knew "
              "they had the campaign, which is a thing that happens at these "
              "festivals more often than anybody admits on the record.")
    assert cc.containment(lifted, lead) < cc.CONTAINMENT_THRESHOLD, (
        "fixture no longer demonstrates what it is for - the padding is "
        "supposed to keep containment under the threshold")
    phrase = cc.shared_phrase(lifted, lead)
    assert phrase and "sobs" in phrase, phrase
    assert cc.shared_phrase("nothing here at all whatsoever, none of it", lead) is None
    assert cc.shared_phrase("too short", lead) is None


def test_anchors_are_numbers_names_and_quoted_phrases():
    """What "concrete" is reduced to: something countable, something named,
    something quoted. A sentence's first word is capitalized because it is
    first, so it is not read as a name."""
    assert "forty" in cc.anchors("Zeller ordered forty-one takes.")
    assert "1962" in cc.anchors("The shelter was poured in 1962.")
    assert "madrid" in cc.anchors("The set stood outside Madrid.")
    assert cc.anchors("Difficult days on that shoot.") == set(), (
        "a sentence-initial capital is not evidence of a name")
    assert "quiet" in cc.anchors('The script called it "a quiet catastrophe".')


# --- the definition is read, not hardcoded ----------------------------


def test_load_stance_reads_the_stance_file_not_a_hardcoded_position():
    """This check must reference the channel's stance document as the
    definition of a contribution, not hardcode one. What that means, and all
    it means: `load_stance` follows the `stance` pointer in
    channels/<channel>.json and returns whatever document it points at.

    What this deliberately does not assert is the document's `consumers`
    list. That list is the stance document's own record of which task owns
    each reader, and it legitimately changes - CF-0181 moved the Compliance
    Checker's entry from `CF-0066` to `CF-0187`. The consumption is alive
    (`evaluate_batch` loads this document on every batch) but the key naming
    it is not this file's subject, and pinning it made this test red for a
    change that had nothing to do with what it checks."""
    cfg_path = cc.REPO / "channels" / f"{CHANNEL}.json"
    assert cfg_path.is_file(), f"{cfg_path} - this test's subject is gone"
    pointer = json.loads(cfg_path.read_text()).get("stance")
    assert pointer, f"{cfg_path} has no `stance` pointer to follow"
    stance_path = cc.REPO / "channels" / pointer
    assert stance_path.is_file(), f"{stance_path} - the pointer leads nowhere"
    stance = cc.load_stance(CHANNEL, repo=cc.REPO)
    assert stance == json.loads(stance_path.read_text()), (
        "load_stance returned something other than the file it points at")
    assert stance["channel_id"] == CHANNEL
    # The two things this agent actually reads out of the document: the
    # position it judges against, and the task the verdict is traceable to
    # (`checked_against`, written on every result by evaluate_batch).
    assert isinstance(stance.get("position"), dict) and stance["position"]
    assert isinstance(stance.get("decided_by", {}).get("task"), str)

    # And the pointer is followed rather than a path being assumed: on a root
    # of this test's own the config points somewhere no real config does, and
    # that is the document that comes back.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "channels" / "elsewhere").mkdir(parents=True)
        invented = {"channel_id": CHANNEL,
                    "position": {"thesis": "invented for this test"},
                    "decided_by": {"task": "CF-XXXX"}}
        (root / "channels" / "elsewhere" / "stance.json").write_text(
            json.dumps(invented, ensure_ascii=False))
        cfg = root / "channels" / f"{CHANNEL}.json"
        cfg.write_text(json.dumps({"stance": "elsewhere/stance.json"}))
        assert cc.load_stance(CHANNEL, repo=root) == invented, (
            "the stance document is hardcoded somewhere, not read from the "
            "pointer")
        # A config with no pointer fails loudly - never a silent fallback to
        # a position carried inside this agent.
        cfg.write_text(json.dumps({}))
        try:
            cc.load_stance(CHANNEL, repo=root)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "a channel config with no `stance` field must raise, not "
                "return a position from somewhere else")


# --- the three acceptance criteria ------------------------------------


def test_criterion_1_fact_rewritten_from_the_news_is_blocked():
    """Acceptance criterion 1: a fact written out of the story itself is a
    retelling, not an addition. The text here says what the lead says, in
    other words - no clause is copied, so this is the ratio doing the work,
    not a string match."""
    script = with_fact(
        "Cruz and Bardem received a sixteen-minute standing ovation at the "
        "Venice premiere of Bunker, the longest of the festival so far, and "
        "Cruz broke into sobs during the applause.")
    result = cc.evaluate_script(script, LEAD)
    assert result["verdict"] == "block", result
    assert result["judged"] is True
    codes = {f["reason_code"] for f in result["failures"]}
    assert codes == {"fact_in_the_story"}, codes
    failure = result["failures"][0]
    assert failure["surface"] == "lead"
    assert failure["overlap"] >= cc.CONTAINMENT_THRESHOLD
    assert "not a fact added" in failure["detail"]
    # And the record says what it was measured against, so the verdict can be
    # read back later.
    assert any("01-trend-hunter.json" in label
               for label in result["compared_against"]), result


def test_criterion_2_a_general_phrase_instead_of_a_fact_is_blocked():
    """Acceptance criterion 2: the stance's own example of what is not a
    fact - "the shoot was difficult". Nothing countable, nothing named,
    nothing quoted."""
    script = with_fact("The shoot was difficult and the cast found the "
                       "material emotionally demanding.")
    result = cc.evaluate_script(script, LEAD)
    assert result["verdict"] == "block", result
    codes = {f["reason_code"] for f in result["failures"]}
    assert codes == {"fact_not_concrete"}, codes
    assert "no number, no proper name" in result["failures"][0]["detail"]


def test_criterion_3_a_concrete_fact_with_a_working_link_passes():
    """Acceptance criterion 3: a number, a name, a source of its own, and
    nothing the story already said. Clean pass, no failures, and the result
    still says what it was compared against."""
    script = with_fact(
        "Zeller had the bunker interiors built inside a decommissioned Cold "
        "War shelter outside Madrid and shot there for nineteen days.",
        on_screen="Shot in a real 1960s shelter")
    result = cc.evaluate_script(script, LEAD)
    assert result["verdict"] == "pass", result
    assert result["failures"] == [] and result["reason"] is None
    assert result["judged"] is True and result["note"] is None
    assert len(result["compared_against"]) == 2, result["compared_against"]


# --- the rest of the net ----------------------------------------------


def test_a_placeholder_is_filler_not_a_fact():
    """The split the task brief draws: the validator catches the field being
    absent, the judge catches it being present and empty of content."""
    for stub in ("TBD", "Production fact to be added from the source.",
                 "placeholder - see source"):
        result = cc.evaluate_script(with_fact(stub), LEAD)
        assert result["verdict"] == "block", (stub, result)
        codes = {f["reason_code"] for f in result["failures"]}
        assert "fact_is_filler" in codes, (stub, codes)


def test_a_hedge_wrapped_around_the_storys_own_names_is_not_concrete():
    """The harder half of criterion 2: a general phrase that does name
    something, but only the film and the people the story already named. The
    anchor has to be new, or it is not the fact doing the work."""
    result = cc.evaluate_script(
        with_fact("Filming Bunker was reportedly very intense for Cruz."), LEAD)
    assert result["verdict"] == "block", result
    codes = {f["reason_code"] for f in result["failures"]}
    assert "fact_not_concrete" in codes, codes
    assert "already in the story" in [f["detail"] for f in result["failures"]][0]

    # The same hedge with a number the story did not have is a fact again.
    ok = cc.evaluate_script(
        with_fact("Filming Bunker was intense enough that Zeller cut the "
                  "schedule to nineteen days."), LEAD)
    assert ok["verdict"] == "pass", ok


def test_a_fact_sourced_to_the_storys_own_link_is_blocked():
    """The stance is explicit: the fact comes from a source of its own,
    never from the lead it is added to. A fact footnoted to the Variety piece
    the script is retelling is the lead, whatever it says."""
    concrete = ("Zeller had the bunker interiors built inside a decommissioned "
                "Cold War shelter outside Madrid and shot there for nineteen "
                "days.")
    for url in (LEAD["evidence"]["rss_links"][0],
                # same link, spelled differently - www., scheme and a trailing
                # slash are not a different source
                "http://www.deadline.com/2026/09/bunker-paloma-cortes-javier-"
                "bardem-venice-ovation-1237070708",
                # the link the script's own proof quotes. It is also the
                # topic's - this fixture's proof quotes the Variety piece the
                # lead is built from - so the block stands either way.
                SCRIPT["proofs"][0]["source"]["url"]):
        result = cc.evaluate_script(with_fact(concrete, source_url=url), LEAD)
        codes = {f["reason_code"] for f in result["failures"]}
        assert result["verdict"] == "block" and "source_is_the_story" in codes, \
            (url, result)


# --- CF-0242: the check after the proof stopped being the story -------
#
# CF-0223 and CF-0241 made `proofs[].source.url` *have to* be the fact's own
# `source_url`. The three tests below are the pair of halves that keeps that
# from turning the check into a tautology in one direction or a dead letter
# in the other: the fact's own proof link is spared (and only it), while a
# fact taken out of the news the script retells is caught exactly as before.


def sourced_from(url, *, text=None, script=None):
    """A script written the way CF-0223/CF-0241 require: the single proof
    shows the fact's own source, so `proofs[0].source.url` *is*
    `production_fact.source_url`. Every real script after those two tasks has
    this shape, which is why `story_links()` may not read that one link as
    the story's."""
    s = copy.deepcopy(script or SCRIPT)
    s["proofs"][0]["source"]["url"] = url
    return with_fact(
        text or ("Zeller had the bunker interiors built inside a "
                 "decommissioned Cold War shelter outside Madrid and shot "
                 "there for nineteen days."),
        source_url=url, script=s)


def test_a_fact_taken_from_the_story_is_still_caught_after_the_proof_is_spared():
    """**The test that keeps CF-0242 from being a switched-off check.**

    Sparing the proof link must not spare the case the check exists for: a
    fact footnoted to one of the topic's *own* sources - the very news the
    script is retelling - is self-sourcing and is a block. Here the script is
    written exactly as CF-0223/CF-0241 demand (the proof shows the fact's
    source, so the two links are the same string), and the link is
    `evidence.sources[2]` of the topic. That source is deliberately not in
    `rss_links`, so `evidence.sources[]` is the only place the judge can find
    it: if the sparing rule were written one level too wide, this passes, and
    it must not."""
    story_url = LEAD["evidence"]["sources"][2]["url"]
    assert story_url not in LEAD["evidence"]["rss_links"], \
        "fixture drifted: this case must rest on evidence.sources[], not rss_links"
    for url in (story_url,
                # and the same source spelled differently is the same source
                "http://WWW.hollywoodreporter.com/movies/movie-reviews/"
                "bunker-review-1236687273/"):
        result = cc.evaluate_script(sourced_from(url), LEAD)
        codes = {f["reason_code"] for f in result["failures"]}
        assert result["verdict"] == "block" and "source_is_the_story" in codes, \
            (url, result)
        assert cc._normalize_url(url) in cc.story_links(sourced_from(url), LEAD)


def test_the_facts_own_proof_link_is_not_read_as_the_story():
    """The other half: with the same shape and a source of the fact's own,
    the judge passes it by itself - no operator override. This is the live
    `example-film/2026-09-15T1034Z` shape, where all four facts sit on a
    source that appears nowhere in their topic's links and the gate blocked
    4 of 4 anyway."""
    own = "https://en.wikipedia.org/wiki/Bunker_(2026_film)#Filming"
    result = cc.evaluate_script(sourced_from(own), LEAD)
    assert result["verdict"] == "pass", result
    assert cc._normalize_url(own) not in cc.story_links(sourced_from(own), LEAD)


def test_only_the_facts_own_proof_link_is_spared_not_the_others():
    """Exactly one link leaves the set: the one CF-0223/CF-0241 force into
    `proofs[]`. A proof quoting some other piece is quoted lead material like
    any other and stays in.

    Checked on `story_links()` rather than on a verdict, and that is not
    dodging: under the contract a fact's `source_url` *is* its proof's link,
    so no correctly shaped script can have its source be a proof link that is
    not the spared one. What a verdict could show here would be a shape the
    validator rejects; what the set shows is the rule itself."""
    s = copy.deepcopy(SCRIPT)
    other = "https://example.com/some-other-piece-the-script-quotes"
    s["proofs"].append({
        "proof_id": "p2",
        "verbatim_text": "a second quoted piece of the lead",
        "source": {"url": other, "publication": "Elsewhere",
                   "title": "A second quoted piece of the lead"},
    })
    own = "https://en.wikipedia.org/wiki/Bunker_(2026_film)#Filming"
    links = cc.story_links(sourced_from(own, script=s), LEAD)
    assert cc._normalize_url(own) not in links, links
    assert cc._normalize_url(other) in links, links
    # and with no fact to spare a link for, every proof link is the story
    bare = copy.deepcopy(s)
    bare.pop(cc.FIELD, None)
    bare["proofs"][0]["source"]["url"] = own
    assert cc._normalize_url(own) in cc.story_links(bare, LEAD)


def test_a_fact_with_no_usable_link_is_not_judged_backed():
    """No link, or something that is not one, means there is nothing holding
    the fact up but our word. The judge does not re-check the URL's *shape* -
    that is CF-0183's validator - it refuses to call a fact backed when there
    is nothing to be backed by."""
    concrete = "Zeller shot the kitchen argument forty-one times."
    for url in ("", "   ", None, "wikipedia.org/wiki/Bunker"):
        result = cc.evaluate_script(with_fact(concrete, source_url=url), LEAD)
        codes = {f["reason_code"] for f in result["failures"]}
        assert result["verdict"] == "block" and "fact_unsourced" in codes, \
            (url, result)


def test_no_host_is_privileged():
    """CF-0184 - where the facts come from - is an open decision, so the
    judge must not have learned one source's domain. The same fact behind
    four different hosts gets the same verdict."""
    concrete = "Zeller shot the kitchen argument forty-one times."
    verdicts = {
        host: cc.evaluate_script(
            with_fact(concrete, source_url=f"https://{host}/x"), LEAD)["verdict"]
        for host in ("en.wikipedia.org", "example.org", "afi.com",
                     "some-studio-press-site.test")}
    assert set(verdicts.values()) == {"pass"}, verdicts


def test_the_facts_own_beat_is_removed_before_the_retelling_is_compared():
    """The fact is spoken in the commentary, so without subtracting the beat
    every fact would be found inside the script's own retelling and blocked.
    `beat_text` is a verbatim substring of `commentary` (CF-0183), which is
    what makes the subtraction exact."""
    # The fact is word-for-word the beat, and the beat is word-for-word in
    # the commentary: the worst case for this.
    script = with_fact(BEAT)
    assert BEAT in script["commentary"]
    assert cc.containment(BEAT, script["commentary"]) == 1.0, (
        "fixture broken - the beat is supposed to be inside the commentary")
    told = cc.retelling(script)
    assert BEAT not in told and "Madrid" not in told, told
    result = cc.evaluate_script(script, LEAD)
    assert result["verdict"] == "pass", result


def test_a_script_with_no_production_fact_is_not_judged_and_not_blocked():
    """Absence is the validator's (CF-0183) and the refusal rule's (CF-0185,
    behind a switch). This module judges a fact that was written - and says
    in the record that it did not judge, rather than reporting a pass that
    looks like approval."""
    for script in ({}, {"production_fact": None}, {"production_fact": {}},
                   {"production_fact": "a string, not an object"}):
        result = cc.evaluate_script(dict(SCRIPT, **script), LEAD)
        assert result["verdict"] == "pass", (script, result)
        assert result["judged"] is False, (script, result)
        assert "CF-0185" in result["note"] and "CF-0183" in result["note"]


def test_the_cancelled_comparison_block_is_not_judged_here_any_more():
    """CF-0181 cancelled the position `comparison` served and CF-0183
    replaced the field; a script still carrying it is answered by the
    validator, by name. This module must not have kept a second opinion about
    it - the fact is the only thing it reads."""
    degraded = {"comparison": {"checks": [{
        "check_id": "c1",
        "claim": {"text": "the studio says the film has a shocking twist"},
        "frame": [{"video_id": "v1", "shot_index": 0,
                   "shows": "the film has a shocking twist, the studio says"}],
        "finding": "the film has a shocking twist, the studio says",
        "beat_text": "the film has a shocking twist, the studio says"}]}}
    script = with_fact("Zeller shot the kitchen argument forty-one times.")
    script.update(degraded)
    result = cc.evaluate_script(script, LEAD)
    assert result["verdict"] == "pass", (
        "the cancelled field must not be judged here - "
        f"got {result['reason']}")
    assert not hasattr(cc, "evaluate_check"), (
        "CF-0066's per-check comparison judge is still in this module")


def test_verdict_is_separate_from_the_rights_risk_enum():
    """The substance verdict is a separate verdict from the rights/risk one
    (clear|caution|review) this agent also writes - the two must not be
    mixed into one enum, and there is no `caution`-equivalent here."""
    result = cc.evaluate_script(with_fact("The shoot was difficult."), LEAD)
    assert result["verdict"] in ("pass", "block")
    assert result["verdict"] not in ("clear", "caution", "review")


# --- what the judge can and cannot see --------------------------------


def test_without_the_lead_the_judge_says_so_and_sees_less():
    """The limitation, pinned rather than described. With no
    `01-trend-hunter.json` and no lead text in the script, the only thing the
    fact can be checked against is the retelling - and a fact copied out of
    the lead's *other* sentences passes. The result says what it was
    compared against, which is how that is visible afterwards."""
    bare = copy.deepcopy(SCRIPT)
    bare.pop("proofs")
    copied = ("Critics split hard on Bunker: Deadline and The Hollywood "
              "Reporter called Bardem and Cruz riveting, while Vulture "
              "called the film a crushing disappointment.")
    with_lead = cc.evaluate_script(with_fact(copied, script=bare), LEAD)
    assert with_lead["verdict"] == "block", with_lead

    without_lead = cc.evaluate_script(with_fact(copied, script=bare), None)
    assert without_lead["verdict"] == "pass", (
        "if this now blocks, the judge got a second source of the story and "
        "this test should be rewritten rather than deleted")
    assert len(without_lead["compared_against"]) == 1, \
        without_lead["compared_against"]
    label = without_lead["compared_against"][0]
    assert "retelling" in label and "commentary" in label, label
    # and it says which parts of the script are not the story (CF-0273), so
    # a reader of the record knows the fact's own beats were kept out of it
    assert "beat" in label and "hook" in label and "payoff" in label, label


def test_a_script_carrying_its_own_lead_text_is_compared_against_it():
    """Even with no stage-01 file, `proofs[].verbatim_text` and the titles
    behind them are lead text the script carries itself - the judge uses
    them, and names them."""
    fact = ("Cruz sobs and kisses Bardem as Bunker dazzles Venice with a "
            "record ovation.")
    result = cc.evaluate_script(with_fact(fact), None)
    assert result["verdict"] == "block", result
    assert {f["reason_code"] for f in result["failures"]} == {"fact_in_the_story"}
    assert any("proofs[]" in label for label in result["compared_against"])


def test_evaluate_batch_labels_every_result_with_the_stance_file():
    """The whole batch, and the traceability the output owes a reader: which
    document the verdict was judged against, named with the task that wrote
    it. Run on a root of this test's own so the assertion is about the
    mechanism, not about today's stance file."""
    batch = {"channel": CHANNEL, "scripts": [
        with_fact("Zeller shot the kitchen argument forty-one times."),
        dict(with_fact("The shoot was difficult."),
             script_id="lf-2026-09-09-001-script2"),
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "channels" / "example-film").mkdir(parents=True)
        (root / "channels" / "example-film" / "stance.json").write_text(json.dumps(
            {"channel_id": CHANNEL, "position": {"thesis": "..."},
             "decided_by": {"task": "CF-0181"}}))
        (root / "channels" / f"{CHANNEL}.json").write_text(
            json.dumps({"stance": "example-film/stance.json"}))
        results = cc.evaluate_batch(
            batch, CHANNEL, repo=root,
            trend_hunter_json={"topics": [LEAD]})

    assert set(results) == {"lf-2026-09-09-001-script1",
                            "lf-2026-09-09-001-script2"}
    for r in results.values():
        assert r["checked_against"] == \
            "channels/example-film/stance.json (CF-0181)", r["checked_against"]
    assert results["lf-2026-09-09-001-script1"]["verdict"] == "pass"
    assert results["lf-2026-09-09-001-script2"]["verdict"] == "block"
    # The topic was matched to the script by topic_id, so the lead was in
    # play for both.
    assert any("01-trend-hunter.json" in label for label in
               results["lf-2026-09-09-001-script1"]["compared_against"])


def test_the_skill_describes_the_check_this_module_performs():
    """The agent's instructions and this module are one procedure in two
    places. A SKILL.md still telling the agent to judge `comparison.checks[]`
    against CF-0066's three failure modes is a live instruction to do the
    cancelled position's work by hand, whatever this file does."""
    skill = AGENT_ROOT / ".claude" / "skills" / "compliance-checker" / "SKILL.md"
    assert skill.is_file(), skill
    text = skill.read_text()
    assert "CF-0187" in text
    for code in ("fact_not_concrete", "fact_in_the_story", "fact_unsourced",
                 "fact_is_filler", "source_is_the_story"):
        assert code in text, f"SKILL.md does not name the `{code}` verdict"
    for gone in ("restates_footage", "shown_restates_caption", "unrelated_shots"):
        assert gone not in text, (
            f"SKILL.md still tells the agent to look for `{gone}`, which "
            f"belongs to the cancelled position")
    assert "production_fact" in text
    # CF-0273: the module stops measuring the fact against the beats the
    # channel makes it speak in, and the agent reading after it must not do
    # by hand what the module stopped doing.
    assert "CF-0273" in text, (
        "SKILL.md does not tell the agent that the fact's own beat, hook and "
        "payoff are not the story it is checked against")
    assert "beat_text" in text and "CF-0216" in text, text[:0]
    # CF-0439: a fact of any kind, judged per article, attribution for people
    assert "CF-0439" in text and "any kind" in text
    assert "how the thing was made" not in text.replace(
        'from "how the thing was made" to', ""), (
        "SKILL.md still asks for a fact about how the thing was made")
    assert "per **article**" in text and "attribution" in text




# --- CF-0242: a phrase the module made at its own seam ----------------


# The real script 001 of `example-film/2026-09-15T1034Z` and its topic, cut
# down to the fragments that produced the false `fact_in_the_story` and
# copied verbatim on 2026-09-15. Frozen here for the same reason LEAD is:
# `pipeline/` is gitignored, and a test that SKIPs is a test that passes.
SEAM_TOPIC = {
    "topic_id": "lf-2026-09-15-001",
    "title_ref": {"name": "Spire-Runner: Fresh Dawn", "season": None,
                  "rights_holder": None},
    "scenes": [
        {"scene_id": "lf-2026-09-15-001-s1",
         "description": "Spire-Runner: Fresh Dawn's six-week reign atop the "
                        "domestic box office, which had it nearing an "
                        "all-time record, ends as it's dethroned by Practical "
                        "Magic 2's opening weekend."},
    ],
    "evidence": {
        "rss_links": [
            "https://variety.com/2026/film/box-office/everyday-sorcery-2-uk-ireland-box-office-1236862589/",
            "https://variety.com/2026/awards/actors/zendaya-tom-holland-emmys-spire-runner-the-long-voyage-1236861849/",
            "https://www.hollywoodreporter.com/movies/movie-news/everyday-sorcery-2-box-office-spire-runner-domestic-record-1236698853/",
            "https://variety.com/2026/film/box-office/box-office-everyday-sorcery-2-spire-runner-fresh-dawn-1236856659/",
        ],
        "sources": [
            {"url": "https://variety.com/2026/film/box-office/everyday-sorcery-2-uk-ireland-box-office-1236862589/",
             "title": "\u2018Practical Magic 2\u2019 Casts a Spell Over U.K., "
                      "Ireland Box Office as Oasis Doc Rocks No. 2",
             "publication": "Variety"},
            {"url": "https://variety.com/2026/awards/actors/zendaya-tom-holland-emmys-spire-runner-the-long-voyage-1236861849/",
             "title": "Zendaya and Tom Holland Make Emmys Debut After Wedding",
             "publication": "Variety"},
            {"url": "https://www.hollywoodreporter.com/movies/movie-news/everyday-sorcery-2-box-office-spire-runner-domestic-record-1236698853/",
             "title": "\u2018Practical Magic 2\u2019 Summons $30M to End "
                      "Spire-Runner\u2019s Streak at No. 1",
             "publication": "The Hollywood Reporter"},
            {"url": "https://variety.com/2026/film/box-office/box-office-everyday-sorcery-2-spire-runner-fresh-dawn-1236856659/",
             "title": "Box Office: \u2018Practical Magic 2\u2019 Conjures Up "
                      "$13 Million on Friday as \u2018Spider-Man: Brand New "
                      "Day\u2019 Nears All-Time Domestic Box Office Record",
             "publication": "Variety"},
        ],
    },
}

SEAM_FACT = (
    "The production needed at least sixty-five takes to land a single fight "
    "beat in Spire-Runner: Fresh Dawn - Spire-Runner and the Hand's ninjas "
    "leaping at each other in mid-air - before it made the final cut; by "
    "contrast, Tom Holland got the film's comic-accurate Scorpion pose in "
    "just two or three tries.")
SEAM_BEAT = "One fight beat alone took over sixty-five takes to land."
SEAM_URL = "https://en.wikipedia.org/wiki/Spire-Runner:_Fresh_Dawn#Filming"

SEAM_SCRIPT = {
    "script_id": "lf-2026-09-15-001-script1",
    "topic_id": "lf-2026-09-15-001",
    "title_ref": {"name": "Spire-Runner: Fresh Dawn", "season": None,
                  "rights_holder": None},
    "hook": "Spire-Runner just lost the box office \u2014 but that wasn't the "
            "hard part of making it.",
    "commentary": (
        "Six straight weeks at number one, nearly an all-time record. Every "
        "one of those weeks got built take by take. Everyday Sorcery 2 finally "
        "ended that run this weekend. Trade headlines called it a box-office "
        "chase. That's the fight scene every trailer highlighted. "
        + SEAM_BEAT +
        " Not every shot on this film was that punishing, though. Holland "
        "landed the comic-accurate Scorpion pose in two or three. The chart "
        "only counts what audiences end up seeing. The call sheet counts what "
        "it took to get there. Six weeks running is the story every headline "
        "read. Sixty-five takes for one beat is the story nobody printed."),
    "payoff": "The box office number is easy to repeat. The sixty-five takes "
              "behind it \u2014 that was the hard part.",
    "proofs": [{
        "proof_id": "p1",
        "verbatim_text": "Spire-Runner: Fresh Dawn",
        "source": {"url": SEAM_URL, "publication": "Wikipedia",
                   "title": "Spire-Runner: Fresh Dawn",
                   "published_at": "2026-09-15T17:00:35Z", "handle": None},
        "capture_method_hint": None,
    }],
    "production_fact": {"text": SEAM_FACT, "beat_text": SEAM_BEAT,
                        "source_url": SEAM_URL,
                        "on_screen": "One fight beat needed 65+ takes to land"},
}


def test_a_phrase_that_only_exists_across_a_join_is_not_a_lifted_phrase():
    """The false `fact_in_the_story` on the live script 001, and why it was
    false **by construction rather than by data**.

    The judge reported the lifted phrase 'spire runner fresh dawn spider'.
    No headline, digest, proof or article contains it. It exists only where
    `lead_segments` puts one fragment after another: the topic's name ends
    '...Fresh Dawn' and the scene digest begins 'Spire-Runner: Brand New
    Day's ...', and the proof's verbatim text and its source title are the
    same string twice over since CF-0223/CF-0241 made the proof show the
    fact's own source. The fact names the film and then names Spire-Runner
    again, so it matches the seam.

    Note what the ratio said at the same moment: 19%, inside the 0.17-0.35
    band `CONTAINMENT_THRESHOLD`'s own calibration calls 'shares the film and
    the cast and nothing else', and nowhere near the 0.65 that means a
    retelling. Two measures, opposite answers, and the block came from the
    one measuring an artifact. Nothing here moves a threshold - the fix is
    that the window no longer runs over a join."""
    seam = "spire runner fresh dawn spider"
    joined = cc.lead_text(SEAM_SCRIPT, SEAM_TOPIC)
    assert seam in " ".join(cc._word_list(joined)), \
        "fixture drifted: the seam this test is about is gone"
    assert not any(seam in " ".join(cc._word_list(fragment))
                   for fragment in cc.lead_segments(SEAM_SCRIPT, SEAM_TOPIC)), \
        "the seam turned out to be inside one fragment, so it is a real phrase"

    surfaces = {s["surface"]: s for s in cc.story_surfaces(SEAM_SCRIPT, SEAM_TOPIC)}
    lead = surfaces["lead"]
    ratio = cc.containment(SEAM_FACT, lead["text"])
    assert 0.17 <= ratio <= 0.35, ratio
    assert ratio < cc.CONTAINMENT_THRESHOLD, ratio
    assert cc.shared_phrase_in_any(SEAM_FACT, lead["segments"]) is None
    # and the old way round still finds it, which is what made it a block
    assert cc.shared_phrase(SEAM_FACT, lead["text"]) == seam

    result = cc.evaluate_script(SEAM_SCRIPT, SEAM_TOPIC)
    codes = {f["reason_code"] for f in result["failures"]}
    assert "fact_in_the_story" not in codes, result
    assert result["verdict"] == "pass", result


def test_a_phrase_really_lifted_out_of_one_headline_is_still_caught():
    """The other side of the same change: per fragment is not weaker, it is
    exact. A fact that copies a clause out of a single source title is found
    in that title, where it actually is."""
    lifted = ("The crew shot forty-one takes on the day the Box Office: "
              "Everyday Sorcery 2 Conjures Up $13 Million on Friday headline "
              "went out.")
    assert cc.shared_phrase_in_any(
        lifted, cc.lead_segments(SEAM_SCRIPT, SEAM_TOPIC)) is not None
    result = cc.evaluate_script(
        with_fact(lifted, beat=SEAM_BEAT, script=SEAM_SCRIPT), SEAM_TOPIC)
    codes = {f["reason_code"] for f in result["failures"]}
    assert "fact_in_the_story" in codes, result


def test_the_beat_is_cut_out_of_the_retelling_not_blanked_over():
    """Removing the fact's beat must not stitch its neighbours together: the
    words on either side of a deleted sentence were never adjacent, and a
    phrase found across that gap would be one more artifact of this module's
    own bookkeeping (CF-0242)."""
    segments = cc.retelling_segments(SEAM_SCRIPT)
    assert SEAM_BEAT not in " ".join(segments)
    assert any(seg.strip().startswith("Six straight weeks") for seg in segments)
    assert any(seg.strip().startswith("Not every shot") for seg in segments)
    # the two halves of the commentary, welded at the hole the beat left
    across_the_gap = "scene every trailer highlighted every shot"
    assert across_the_gap in " ".join(cc._word_list(" ".join(segments))), \
        "fixture drifted: the gap this test is about is gone"
    assert not any(across_the_gap in " ".join(cc._word_list(seg))
                   for seg in segments)
    assert cc.shared_phrase_in_any(
        "The fight scene every trailer highlighted every shot of.",
        segments) is None


# --- CF-0273: the beats the channel makes the script speak the fact in ----


# The real script the check cost a video, and its topic, copied verbatim on
# 2026-09-21 from `example-film/2026-09-17T1901Z` (script
# `lf-2026-09-17-006-script1`, topic `lf-2026-09-17-006`, pattern
# `explainer`). The evidence is cut down to the titles and links; everything
# the judge reads is here. Frozen for the same reason LEAD and SEAM_TOPIC
# are: `pipeline/` is gitignored, and a test that SKIPs is a test that
# passes (CF-0054).
OWL_TOPIC = {
    "topic_id": "lf-2026-09-17-006",
    "title_ref": {"name": "Wren Hollow", "season": "2",
                  "network": "Example Max", "rights_holder": None},
    "scenes": [
        {"scene_id": "lf-2026-09-17-006-s1",
         "description": "Example Network's Wren Hollow series casts three new roles for "
                        "Season 2 - Arthur Weasley, Moaning Myrtle and Colin "
                        "Creevey.",
         "tags": ["casting"]},
        {"scene_id": "lf-2026-09-17-006-s2",
         "description": "Fans and critics argue over Example Network's casting choice for "
                        "Snape, debating whether the show can live up to the "
                        "films' version of the character.",
         "tags": ["controversial", "character_analysis"]},
    ],
    "evidence": {
        "rss_links": [
            "https://deadline.com/feature/wren-hollow-tv-show-season-2-news-updates-example network-1237104618/",
            "https://www.hollywoodreporter.com/tv/tv-news/wren-hollow-season-2-rafe-spall-arthur-weasley-1236702102/",
            "https://variety.com/2026/tv/news/wren-hollow-example network-cast-arthur-weasley-moaning-myrtle-1236862281/",
        ],
        "sources": [
            {"url": "https://deadline.com/feature/wren-hollow-tv-show-season-2-news-updates-example network-1237104618/",
             "title": "Everything We Know About Season 2 Of Example Network’s "
                      "‘Wren Hollow’ TV Series So Far",
             "publication": "Deadline"},
            {"url": "https://www.hollywoodreporter.com/tv/tv-news/wren-hollow-season-2-rafe-spall-arthur-weasley-1236702102/",
             "title": "Rafe Spall to Play Arthur Weasley in Season 2 of "
                      "Example Network’s ‘Wren Hollow’ Series",
             "publication": "The Hollywood Reporter"},
            {"url": "https://variety.com/2026/tv/news/wren-hollow-example network-cast-arthur-weasley-moaning-myrtle-1236862281/",
             "title": "‘Wren Hollow’ Example Network Series Casts Its Arthur "
                      "Weasley, Moaning Myrtle, Colin Creevey",
             "publication": "Variety"},
        ],
    },
}

OWL_FACT = (
    "The show's animal prototypes have been built using animatronics rather "
    "than CGI, including ten owls with thirty-six thousand feathers each and "
    "two rats built to play Scabbers.")
OWL_BEAT = (
    "The show's owl prototypes alone run to ten birds, each built with "
    "thirty-six thousand feathers. Even Scabbers is played by two animatronic "
    "rats, not CGI.")
OWL_URL = "https://en.wikipedia.org/wiki/Wren_Hollow_(TV_series)#Design"

OWL_SCRIPT = {
    "script_id": "lf-2026-09-17-006-script1",
    "topic_id": "lf-2026-09-17-006",
    "title_ref": {"name": "Wren Hollow", "season": "2",
                  "network": "Example Max", "rights_holder": None},
    "pattern": {"pattern_id": "explainer", "rhythm_id": "alternate"},
    # The hook names the fact because `explainer` tells the writer to: "The
    # hook names the specific fact, not the topic."
    "hook": "Ten robotic owls, thirty-six thousand feathers each — "
            "that's how Example Network built this world.",
    "commentary": (
        "Example Network just cast three new faces for Season Two — Arthur Weasley, "
        "Moaning Myrtle, and Colin Creevey. But behind every creature on this "
        "set sits real animatronics work most viewers never clock. "
        + OWL_BEAT +
        " That's the level of craft going into a set most people only judge "
        "by casting news. Fans are still arguing about the Snape casting "
        "choice, but nobody's debating the owls. So when a new actor joins "
        "this cast, they're stepping into a physically built world, feathers "
        "and all. The owls will still be blinking long after this week's "
        "casting news is forgotten."),
    # And the payoff closes the loop on the hook's wording, as the same
    # pattern tells it to.
    "payoff": "Thirty-six thousand feathers a bird — that's the world "
              "this new cast just joined.",
    "proofs": [{
        "proof_id": "p1",
        "verbatim_text": "Wren Hollow (TV series)",
        "source": {"url": OWL_URL, "publication": "Wikipedia",
                   "title": "Wren Hollow (TV series)",
                   "published_at": "2026-09-17T15:44:33Z", "handle": None},
        "capture_method_hint": None,
    }],
    "production_fact": {
        "text": OWL_FACT, "beat_text": OWL_BEAT, "source_url": OWL_URL,
        "on_screen": "Ten animatronic owls, 36,000 feathers each - not CGI"},
}


def test_the_frame_the_pattern_builds_on_the_fact_is_not_the_story():
    """The block that cost the video, and why it was the channel's own
    requirement coming back as a finding.

    The fact is the animatronic owls; the stance makes the script speak it
    (CF-0183) and `explainer` makes the hook name it and the payoff close on
    the hook's wording. So the feather count is in the hook and in the payoff
    by contract - and the judge, measuring the fact against the whole script,
    found it there and called the fact a retelling of the story. Against the
    story itself - the casting news - the same fact shares 5 % of its words:
    there is nothing of it in the lead at all."""
    assert cc.containment(OWL_FACT, cc.lead_text(OWL_SCRIPT, OWL_TOPIC)) < 0.10

    # What the old surface was: the frame carries the fact's own phrase, in
    # the hook, word for word.
    lifted = "owls thirty six thousand feathers each"
    assert cc.shared_phrase(OWL_FACT, OWL_SCRIPT["hook"]) == lifted
    old_surface = " ".join([OWL_SCRIPT["hook"], OWL_SCRIPT["payoff"]])
    assert cc.containment(OWL_FACT, old_surface) > 0.0

    # What it is now: the commentary the beat left behind, and nothing of the
    # frame in any segment of it.
    segments = cc.retelling_segments(OWL_SCRIPT)
    told = " ".join(segments)
    assert OWL_BEAT not in told
    assert OWL_SCRIPT["hook"] not in told and OWL_SCRIPT["payoff"] not in told
    assert "robotic" not in told and "just joined" not in told, told
    assert cc.shared_phrase_in_any(OWL_FACT, segments) is None

    result = cc.evaluate_script(OWL_SCRIPT, OWL_TOPIC)
    assert result["verdict"] == "pass", result
    assert result["failures"] == [], result
    # and the record still names both surfaces it was measured against
    assert len(result["compared_against"]) == 2, result["compared_against"]


def test_the_frame_is_kept_out_of_the_concreteness_question_too():
    """The same surfaces answer question 1's "are the specific things in this
    fact already in the story" (`fact_not_concrete`), so the frame has to be
    out of both or the fact would be hedging around numbers the script took
    from it. The feather count is new to the story; a hedge around the film
    and the network the lead already named is not."""
    story_words = set()
    for surface in cc.story_surfaces(OWL_SCRIPT, OWL_TOPIC):
        story_words |= cc._words(surface["text"])
    assert "thirty" not in story_words and "36" not in story_words
    assert "casting" in story_words, "the actual news must still be in there"

    hedged = cc.evaluate_script(
        with_fact("Building Example Network's Wren Hollow was reportedly very "
                  "demanding for the crew.",
                  beat=OWL_BEAT, source_url=OWL_URL, script=OWL_SCRIPT),
        OWL_TOPIC)
    assert hedged["verdict"] == "block", hedged
    assert "fact_not_concrete" in {f["reason_code"] for f in hedged["failures"]}


def test_a_fact_written_out_of_the_news_is_still_blocked():
    """The back-check, on the same real script: swap the owls for a "fact"
    that says what the casting story says and the block comes straight back,
    on the lead, which is the surface the question was always about. Nothing
    about the frame's removal touches this - the news is in the news."""
    retold = cc.evaluate_script(
        with_fact("Example Network cast three new roles for Season 2 of its Wren Hollow "
                  "series - Arthur Weasley, Moaning Myrtle and Colin "
                  "Creevey - and fans argue over the casting choice for "
                  "Snape.",
                  beat=OWL_BEAT, source_url=OWL_URL, script=OWL_SCRIPT),
        OWL_TOPIC)
    assert retold["verdict"] == "block", retold
    failures = [f for f in retold["failures"]
                if f["reason_code"] == "fact_in_the_story"]
    assert failures, retold
    assert failures[0]["surface"] == "lead", failures
    assert failures[0]["overlap"] >= cc.CONTAINMENT_THRESHOLD, failures


def test_a_fact_the_script_already_told_in_its_own_commentary_is_blocked():
    """And the retelling surface keeps its teeth: a fact that repeats what
    the script's commentary already said about the news is still caught
    there, with no lead file at hand at all. This is what the surface is for,
    and it is the reason the commentary stays a surface while the frame does
    not - the commentary is where the news is told."""
    result = cc.evaluate_script(
        with_fact("Season Two casts Arthur Weasley, Moaning Myrtle and Colin "
                  "Creevey, while fans keep arguing about the Snape casting "
                  "choice.",
                  beat=OWL_BEAT, source_url=OWL_URL, script=OWL_SCRIPT),
        None)
    assert result["verdict"] == "block", result
    failures = [f for f in result["failures"]
                if f["reason_code"] == "fact_in_the_story"]
    assert failures and failures[0]["surface"] == "retelling", result


def test_no_fixture_script_has_its_hook_or_payoff_read_as_the_story():
    """The rule, over every script fixture in this file rather than over the
    one that broke: whatever the pattern, the frame is never a segment of the
    story surface and the fact's beat is never inside one."""
    for script in (SCRIPT, SEAM_SCRIPT, OWL_SCRIPT):
        fact = script.get("production_fact") or {}
        segments = cc.retelling_segments(
            script if fact else with_fact("x", script=script))
        for segment in segments:
            assert segment not in (script["hook"], script["payoff"]), script[
                "script_id"]
            assert segment.strip() in script["commentary"], script["script_id"]
        joined = " ".join(segments)
        beat = fact.get("beat_text") or BEAT
        assert beat not in joined, script["script_id"]


# --- CF-0439: a fact of any kind, and a fact about a person -----------


def test_an_attributed_fact_about_a_person_is_not_read_as_a_hedge():
    """CF-0438/CF-0439 *require* a fact about a real person to be put as
    someone's statement - "Variety reported that...". The "reportedly" such
    a report carries is the attribution, not vagueness. The same words with
    no one named are still the hedge the stance refuses."""
    bare = "Cruz reportedly turned down Bunker first."
    blocked = cc.evaluate_script(with_fact(bare), LEAD)
    assert blocked["verdict"] == "block", blocked
    assert {f["reason_code"] for f in blocked["failures"]} == \
        {"fact_not_concrete"}, blocked

    # attributed in the script's own `fact.attribution` (CF-0439 shape)
    s = with_fact(bare)
    s["fact"] = {"text": bare, "kind": "casting",
                 "attribution": "Cruz, speaking to Variety"}
    ok = cc.evaluate_script(s, LEAD)
    assert ok["verdict"] == "pass", ok

    # attributed in the text itself, English and Russian
    for text in ("Variety reported that Cruz reportedly turned down Bunker "
                 "first.",
                 "According to Deadline, Cruz reportedly turned down Bunker "
                 "first.",
                 "Карвер сообщила, что reportedly turned down Bunker first."):
        assert cc.is_attributed(text), text
        r = cc.evaluate_script(with_fact(text), LEAD)
        assert not any(f["reason_code"] == "fact_not_concrete"
                       for f in r["failures"]), (text, r)

    # a reporting verb with no one named before it is not an attribution,
    # and only "reportedly" is forgiven - "allegedly" stays a hedge
    assert not cc.is_attributed("Cruz reportedly said it was hard.")
    assert cc.vague_hedge("Variety reported Cruz allegedly quit.",
                          attributed=True).group(0) == "allegedly"


def test_another_article_of_the_same_outlet_is_a_source_of_its_own():
    """Trade facts come from Variety/Deadline/THR, the same outlets the feed
    carries. The rule is per article, not per outlet: a different Variety
    URL from the one the story is retold from is the fact's own source; only
    the story's own link is `source_is_the_story`."""
    story_url = SCRIPT["proofs"][0]["source"]["url"]
    assert "variety.com" in story_url
    other = "https://variety.com/2026/film/box-office/bunker-budget-1236900001/"
    concrete = ("Bunker cost $38 million to make, the most Zeller has ever "
                "been given.")
    result = cc.evaluate_script(with_fact(concrete, source_url=other), LEAD)
    assert result["verdict"] == "pass", result
    same = cc.evaluate_script(with_fact(concrete, source_url=story_url), LEAD)
    assert "source_is_the_story" in {
        f["reason_code"] for f in same["failures"]}, same


def test_a_fact_that_is_not_about_the_set_is_not_refused_for_it():
    """The fact is of any kind now (CF-0439): box office, casting, release
    are as concrete as a take count, and nothing here asks where on the
    production the fact sits."""
    for kind, text in (
            ("box_office", "Bunker opened to $14.2 million in Spain, the "
                           "biggest Spanish opening of 2026."),
            ("casting", "Zeller first offered the lead to Antonio Banderas, "
                        "who passed over a scheduling clash."),
            ("release", "ExampleStream moved the Bunker release from November 7 "
                        "to December 12.")):
        s = with_fact(text)
        s["fact"] = {"text": text, "kind": kind}
        result = cc.evaluate_script(s, LEAD)
        assert result["verdict"] == "pass", (kind, result)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
