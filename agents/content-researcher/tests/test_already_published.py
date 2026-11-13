#!/usr/bin/env python3
"""CF-0865: the second step of `already_published` - after the fact is picked.

Pinned on a stand-in root (a temp tree with its own `publish/acceptance-log.json`
and `pipeline/<channel>/<batch>/` files), shaped on the real case: the ChatGPT
video of 16.10 (published 19.10) and the topic of 25.10 0834Z whose writer took
the sentence that closed the 16.10 commentary.

* the repeat is refused at step 2 (fact only) and after step 5 (the 03), with
  `reason_code: already_published` and the `publish/...mp4` it repeats;
* only videos accepted before the batch started count, and only the latest
  verdict of each video;
* a Wikipedia section is no "same source"; an unrelated sentence sharing a
  few words is no "same fact"; the text test needs `SHARED_6GRAMS`;
* a topic with no `same_work` mark is not compared at all.

NOTHING HERE TOUCHES THE NETWORK OR THE LIVE TREE.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489)
_TMP = tmp_root("cr-already-published-")

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
import already_published as ap  # noqa: E402
ap.VOLUMES_DIR = Path(_TMP) / "no-volumes"   # CF-0928: never the live /Volumes

CH = "example-tech"
OLD, NEW = "2026-10-16T0839Z", "2026-10-25T0834Z"

OLD_SCRIPT = {
    "script_id": "lf-2026-10-16-008-script1", "topic_id": "lf-2026-10-16-008",
    "title_ref": {"name": "ChatGPT"},
    "hook": "ChatGPT got plugins in March twenty twenty three, long before its own browser.",
    "commentary": ("In March twenty twenty three, OpenAI added support for plugins for ChatGPT. "
                   "Some were OpenAI's own, such as web browsing and code interpretation. "
                   "In October twenty twenty five, OpenAI launched ChatGPT Atlas, a browser. "
                   "In July twenty twenty six, ChatGPT apps were renamed to plugins."),
    "payoff": "So plugins are the old idea. Apps were just renamed plugins.",
    "fact": {"text": "In March 2023, OpenAI added support for plugins for ChatGPT.",
             "url": "https://en.wikipedia.org/wiki/ChatGPT#Features",
             "primary_url": "https://openai.com/blog/chatgpt-plugins"},
    "claims": [{"claim_id": "c1", "text": "x", "support": [
        {"quote": "In October 2025, OpenAI launched ChatGPT Work, an agent for connected apps."}]}],
}

NEW_SCRIPT = {
    "script_id": "lf-2026-10-25-003-script1", "topic_id": "lf-2026-10-25-003",
    "title_ref": {"name": "ChatGPT"},
    "hook": "ChatGPT's apps are plugins now.",
    "commentary": "ChatGPT apps were renamed to plugins in July 2026. Outside developers built plugins too.",
    "payoff": "So the name is the news.",
    "fact": {"text": "In July 2026, ChatGPT apps were renamed to plugins.",
             "url": "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins",
             "primary_url": "https://help.openai.com/en/articles/20001256-plugins"},
    "production_fact": {"text": "ChatGPT apps were renamed to plugins in July 2026.",
                        "source_url": "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins"},
}

MARK = {"slug": "chatgpt", "batch": OLD, "topic_id": "lf-2026-10-16-008",
        "relation": "same_work", "story": "different", "shared_sources": []}


def row(batch, verdict="accepted", recorded="2026-10-16T17:57:03Z", slug="chatgpt",
        topic="lf-2026-10-16-008", script_id="lf-2026-10-16-008-script1",
        path="publish/example-tech/2026-10-19/chatgpt.mp4"):
    return {"entry_id": f"{CH}/{batch}/{slug}", "slug": slug, "channel": CH, "batch_id": batch,
            "topic_id": topic, "verdict": verdict, "answered_at": recorded[:10],
            "recorded_at": recorded, "publish_path": path if verdict == "accepted" else None,
            "profile": {"script_id": script_id}}


def make_root(rows, old_script=OLD_SCRIPT, new_script=NEW_SCRIPT, marks=(MARK,), log=True,
              candidates=None):
    root = Path(tempfile.mkdtemp(dir=_TMP))
    if log:
        (root / "publish").mkdir()
        (root / ap.LOG_REL).write_text(json.dumps({"acceptances": rows}))
    old = root / "pipeline" / CH / OLD
    old.mkdir(parents=True)
    (old / ap.RESEARCHER_FILE).write_text(json.dumps({"scripts": [old_script]}))
    new = root / "pipeline" / CH / NEW
    new.mkdir(parents=True)
    topic = {"topic_id": new_script["topic_id"], "title_ref": {"name": "ChatGPT"}}
    if marks:
        topic["published_before"] = list(marks)
    if candidates is not None:
        topic["fact_candidates"] = candidates
    (new / ap.TREND_FILE).write_text(json.dumps({"topics": [topic]}))
    (new / ap.RESEARCHER_FILE).write_text(json.dumps(
        {"batch_id": NEW, "channel": CH, "scripts": [new_script], "skipped": []}))
    return root, new


def run(argv):
    lines = []
    code = ap.main(argv, out=lines.append)
    return code, "\n".join(lines)


def test_spoken_numbers_read_back_as_digits():
    assert ap.words("In July twenty twenty six") == ["in", "july", "2026"]
    assert ap.words("March twenty twenty-three") == ["march", "2023"]
    assert ap.words("nine hundred million users") == ["900000000", "users"]
    assert ap.words("900,000,000 users") == ["900000000", "users"]
    assert ap.words("two thousand and five") == ["2005"]
    assert ap.words("twenty-five, and two") == ["25", "and", "2"]
    # CF-0871: punctuation ends a spoken number (13T1411Z's claim c1 read 20222)
    assert ap.words("In July twenty twenty-two, two new Vanguards films") == \
        ["in", "july", "2022", "2", "new", "vanguards", "films"]
    assert ap.words("May 2, 2025") == ["may", "2", "2025"]


def test_the_written_repeat_is_refused_and_moved_to_skipped():
    root, new = make_root([row(OLD)])
    f = new / ap.RESEARCHER_FILE
    code, out = run([str(f)])
    assert code == ap.EXIT_REPEAT, out
    assert "publish/example-tech/2026-10-19/chatgpt.mp4" in out and "same_fact" in out, out
    assert json.loads(f.read_text())["scripts"], "without --write nothing is written"
    code, out = run([str(f), "--write"])
    assert code == ap.EXIT_REPEAT, out
    d = json.loads(f.read_text())
    assert d["scripts"] == [], d
    (sk,) = d["skipped"]
    assert sk["topic_id"] == "lf-2026-10-25-003"
    assert sk["reason_code"] == "already_published" == ap.SKIP_REASON_CODE
    assert sk["stage"] == "scripts"
    assert sk["published_video"] == "publish/example-tech/2026-10-19/chatgpt.mp4"
    assert "publish/example-tech/2026-10-19/chatgpt.mp4" in sk["reason"]
    assert sk["published_before"][0]["entry_id"] == f"{CH}/{OLD}/chatgpt"


def test_step_two_refuses_on_the_fact_alone_and_writes_nothing():
    root, new = make_root([row(OLD)])
    before = (new / ap.RESEARCHER_FILE).read_text()
    code, out = run([str(new), "--topic", "lf-2026-10-25-003",
                     "--fact-text", "In July 2026, ChatGPT apps were renamed to plugins.",
                     "--fact-url", "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins"])
    assert code == ap.EXIT_REPEAT and "REFUSE lf-2026-10-25-003" in out, out
    assert (new / ap.RESEARCHER_FILE).read_text() == before
    code, out = run([str(new), "--topic", "lf-2026-10-25-003",
                     "--fact-text", "In 2026, OpenAI opened a data centre in Norway with 100,000 GPUs."])
    assert code == ap.EXIT_OK, out
    code, _ = run([str(new), "--topic", "lf-2026-10-25-003"])
    assert code == ap.EXIT_USAGE


def test_only_videos_accepted_before_the_batch_started_count():
    # accepted later the same day the batch ran: not a past the writer knew
    late = row(OLD, recorded="2026-10-25T09:00:00Z")
    code, out = run([str(make_root([late])[1] / ap.RESEARCHER_FILE)])
    assert code == ap.EXIT_OK and "held against 0" in out, out
    # a day with no time: only an earlier day counts
    same_day = dict(row(OLD), recorded_at=None, answered_at="2026-10-25")
    assert run([str(make_root([same_day])[1] / ap.RESEARCHER_FILE)])[0] == ap.EXIT_OK
    day_before = dict(row(OLD), recorded_at=None, answered_at="2026-10-24")
    assert run([str(make_root([day_before])[1] / ap.RESEARCHER_FILE)])[0] == ap.EXIT_REPEAT
    assert not ap.accepted_before(row("2026-10-25T0934Z", recorded="2026-10-20T00:00:00Z"), NEW)


def test_the_latest_verdict_of_each_video_counts():
    rejected_later = [row(OLD), row(OLD, verdict="rejected", recorded="2026-10-17T10:00:00Z")]
    assert run([str(make_root(rejected_later)[1] / ap.RESEARCHER_FILE)])[0] == ap.EXIT_OK
    # a slug match finds an accepted video the mark does not name (mark w/o batch)
    other = dict(MARK, batch=None)
    root, new = make_root([row(OLD)], marks=(other,))
    assert run([str(new / ap.RESEARCHER_FILE)])[0] == ap.EXIT_REPEAT


def test_a_video_accepted_under_the_channels_former_id_still_counts():
    # CF-0197: a batch accepted before a rename names the channel by its
    # former id - in its log row, its entry_id and its pipeline directory.
    # Resolved at the door, it is the same channel's video and is held.
    FORMER = "old-tech"
    old_row = dict(row(OLD), channel=FORMER, entry_id=f"{FORMER}/{OLD}/chatgpt")
    root, new = make_root([old_row])
    (root / "channels").mkdir()
    (root / "channels" / f"{CH}.json").write_text(json.dumps({"former_channel_ids": [FORMER]}))
    (root / "pipeline" / FORMER).mkdir()
    (root / "pipeline" / CH / OLD).rename(root / "pipeline" / FORMER / OLD)
    code, out = run([str(new / ap.RESEARCHER_FILE)])
    assert code == ap.EXIT_REPEAT and "same_fact" in out, out
    # a mark naming the former id finds it by entry_id alone (no slug match)
    by_id = {"entry_id": f"{FORMER}/{OLD}/chatgpt", "relation": "same_work"}
    rows = ap.published_videos(root, CH, NEW, [by_id])
    assert [r["entry_id"] for r in rows] == [f"{FORMER}/{OLD}/chatgpt"], rows
    assert ap.canon_entry(f"{FORMER}/{OLD}/chatgpt", root) == f"{CH}/{OLD}/chatgpt"

def test_no_same_work_mark_no_comparison():
    root, new = make_root([row(OLD)], marks=())
    code, out = run([str(new / ap.RESEARCHER_FILE)])
    assert code == ap.EXIT_OK and "held against 0" in out, out
    franchise = dict(MARK, relation="same_franchise")
    assert run([str(make_root([row(OLD)], marks=(franchise,))[1]
                    / ap.RESEARCHER_FILE)])[0] == ap.EXIT_OK


def test_no_acceptance_log_is_nothing_published():
    root, new = make_root([], log=False)
    code, out = run([str(new / ap.RESEARCHER_FILE)])
    assert code == ap.EXIT_OK and "nothing accepted" in out, out


def test_a_wikipedia_section_is_not_the_same_source_an_article_is():
    old = dict(OLD_SCRIPT, commentary="Something else entirely about browsers.", hook="", payoff="",
               fact={"text": "OpenAI was founded in December 2015 in San Francisco.",
                     "url": "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins"}, claims=[])
    new = dict(NEW_SCRIPT, fact={"text": "Plugins shipped to every Plus user in May 2023.",
                                 "url": "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins"},
               production_fact={})
    assert run([str(make_root([row(OLD)], old, new)[1] / ap.RESEARCHER_FILE)])[0] == ap.EXIT_OK
    article = "https://www.theverge.com/2026/7/1/chatgpt-plugins/"
    old2 = dict(old, fact=dict(old["fact"], primary_url=article))
    new2 = dict(new, fact=dict(new["fact"], primary_url="https://theverge.com/2026/7/1/chatgpt-plugins"))
    code, out = run([str(make_root([row(OLD)], old2, new2)[1] / ap.RESEARCHER_FILE)])
    assert code == ap.EXIT_REPEAT and "same_source" in out, out


def test_an_unrelated_sentence_sharing_words_is_not_the_same_fact():
    """The measured near-miss: 0834Z's fact against 24T1528Z's ChatGPT Work quote
    - 0.67 of the words, 0.20 of the pairs."""
    old = dict(OLD_SCRIPT, commentary="", hook="", payoff="", fact={},
               claims=[{"support": [{"quote": "In July 2026, OpenAI launched ChatGPT Work, an "
                                              "AI agent that reads connected apps and files."}]}])
    cur = ap.current_side(NEW_SCRIPT)
    pub = {"urls": set(), "text": "", "statements": ap.statements(old)}
    assert ap.compare(cur, pub) == []
    pub["statements"].append("In July twenty twenty six, ChatGPT apps were renamed to plugins.")
    (why,) = ap.compare(cur, pub)
    assert why["test"] == "same_fact" and why["share"] == 1.0


def test_the_text_test_needs_n_shared_six_grams():
    body = ("The rollout reached every paying user across Europe and Asia within one quarter "
            "while the free tier waited for the larger model and its slower voice for months "
            "until a second launch in autumn brought image tools to schools hospitals and banks")
    toks = ap.words(body)
    assert len(ap.ngrams(toks)) >= ap.SHARED_6GRAMS
    cur = {"fact_texts": [], "urls": set(), "text": body}
    assert ap.compare(cur, {"urls": set(), "text": body, "statements": []})[0]["test"] == "same_text"
    short = " ".join(toks[:ap.NGRAM + ap.SHARED_6GRAMS - 2])      # N-1 6-grams
    assert ap.compare(cur, {"urls": set(), "text": short, "statements": []}) == []


def cand(text, url, passes=True, tier=2):
    return {"text": text, "kind": "other", "source": "Wikipedia", "url": url,
            "check": {"passes": passes, "failures": [], "kind": "other", "tier": tier}}


REPEAT_FACT = cand("In July 2026, ChatGPT apps were renamed to plugins.",
                   "https://en.wikipedia.org/wiki/ChatGPT#GPTs_and_plugins")
FRESH_FACT = cand("In 2026, OpenAI opened a data centre in Norway with 100,000 GPUs.",
                  "https://en.wikipedia.org/wiki/ChatGPT#Infrastructure")
OLD_FACT = cand("In March 2023, OpenAI added support for plugins for ChatGPT.",
                "https://en.wikipedia.org/wiki/ChatGPT#Features")


def test_a_repeated_fact_sends_the_writer_to_the_next_candidate():
    """The driver's decision of 2026-10-26: the fact is at fault, not the topic."""
    root, new = make_root([row(OLD)], candidates=[REPEAT_FACT, FRESH_FACT])
    code, out = run([str(new), "--topic", "lf-2026-10-25-003", "--candidates", "--json"])
    assert code == ap.EXIT_OK, out
    assert "REPEAT candidate 1" in out and "publish/example-tech/2026-10-19/chatgpt.mp4" in out, out
    assert "TAKE candidate 2" in out and "Norway" in out, out
    assert '"refused_as_repeat": [\n    0\n  ]' in out, out
    # a candidate that failed the fact rule is never tried
    root, new = make_root([row(OLD)], candidates=[
        cand("In 2026, OpenAI opened a data centre in Norway.", "https://x.example/a", passes=False),
        REPEAT_FACT])
    code, out = run([str(new), "--topic", "lf-2026-10-25-003", "--candidates"])
    assert code == ap.EXIT_REPEAT and "1 candidate(s)" in out, out


def test_the_topic_leaves_only_when_every_candidate_repeats():
    root, new = make_root([row(OLD)], candidates=[REPEAT_FACT, OLD_FACT])
    code, out = run([str(new), "--topic", "lf-2026-10-25-003", "--candidates", "--json"])
    assert code == ap.EXIT_REPEAT, out
    assert "REPEAT candidate 1" in out and "REPEAT candidate 2" in out, out
    entry = json.JSONDecoder().raw_decode(out[out.index("[\n"):])[0][0]
    assert entry["reason_code"] == "already_published" and entry["candidates_refused"] == 2
    assert entry["reason"].startswith("all 2 passing fact candidate(s) repeat"), entry["reason"]
    assert entry["published_video"] == "publish/example-tech/2026-10-19/chatgpt.mp4"
    # a file of candidates, tried in its own order
    f = new / "cands.json"
    f.write_text(json.dumps({"candidates": [{"fact": {"text": FRESH_FACT["text"],
                                                       "url": FRESH_FACT["url"]}}]}))
    code, out = run([str(new), "--topic", "lf-2026-10-25-003", "--candidates", str(f)])
    assert code == ap.EXIT_OK and "TAKE candidate 1" in out, out
    # nothing to try is a usage error, not a refusal
    root, new = make_root([row(OLD)], candidates=[])
    assert run([str(new), "--topic", "lf-2026-10-25-003", "--candidates"])[0] == ap.EXIT_USAGE


def test_the_skill_runs_the_check_after_step_two_and_the_code_is_a_constant():
    skill = (AGENT_ROOT / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    a, b = skill.index("\n2. **Take the fact"), skill.index("\n3. **Take the assigned pattern")
    step = skill[a:b]
    assert "already_published.py" in step and "--topic" in step and "--write" in step, \
        "step 2 ends with the post-fact check (both calls)"
    assert "--candidates" in step and "TAKE candidate" in step, "a repeat goes to the next candidate"
    assert "do not hunt for another fact" not in step
    assert '"reason_code": "already_published"' in step or "`already_published`" in step
    # the root's contract (tests/test_pipeline_contracts.py) reads this constant
    src = (AGENT_ROOT / "scripts" / "already_published.py").read_text()
    assert re.search(r'^SKIP_REASON_CODE\s*=\s*"already_published"', src, re.M)


# ---------------------------------------------------------------- CF-0871
# The live pair: example-film 2026-10-26T1514Z took a Wikipedia fact that holds
# the claim c1 of the Doomsday video 2026-10-13T1411Z (published 19.10) and
# adds SDCC, Feige and the 2025 dates - 0.40 of the fact's words were said
# before, 0.91 of the said sentence lies in the fact.
DOOM_FACT = ("At San Diego Comic-Con (SDCC) in July 2022, Zenith Studios president Kevin Feige "
             "announced the films Vanguards: The Kang Dynasty and Vanguards: Secret Wars, to be "
             "released on May 2, 2025, and November 7, 2025, respectively.")
DOOM_OLD = {
    "script_id": "lf-2026-10-13-007-script1", "topic_id": "lf-2026-10-13-007",
    "hook": "What do you really know about Vanguards: Doomsday? Start with this list.",
    "commentary": ("One. It did not start as Doomsday. In July twenty twenty-two, two new Vanguards "
                   "films were announced: The Kang Dynasty and Secret Wars. Two. It was first "
                   "scheduled for May twenty twenty-five. Four. The title Doomsday came in July "
                   "twenty twenty-four, with Downey as Doctor Doom and the Russo brothers back as "
                   "directors."),
    "payoff": "That is the count.",
    "fact": {"text": "Many cast members were announced as part of a nearly five-and-a-half-hour-long "
                     "livestream in March 2025, which became the most-viewed cross-platform "
                     "livestream stunt.",
             "url": "https://en.wikipedia.org/wiki/Vanguards:_Doomsday#Marketing"},
    "claims": [
        {"claim_id": "c1", "text": "In July twenty twenty-two, two new Vanguards films were "
                                   "announced: The Kang Dynasty and Secret Wars.",
         "support": [{"quote": "Two new Vanguards films, The Kang Dynasty and Secret Wars, were "
                               "announced in July 2022"}]},
        {"claim_id": "c6", "text": "The title Doomsday came in July twenty twenty-four.",
         "support": [{"quote": "The return of the Russo brothers as directors and McFeely as "
                               "co-writer, the casting of Downey as new villain Doctor Doom, and "
                               "the new subtitle Doomsday were all announced in July 2024."}]}],
}


def test_a_published_sentence_inside_a_longer_fact_is_the_same_fact():
    pub = {"urls": set(), "text": "", "statements": ap.statements(DOOM_OLD)}
    cur = ap.current_side(fact_text=DOOM_FACT,
                          fact_urls=["https://en.wikipedia.org/wiki/Vanguards:_Doomsday#Production"])
    (why,) = ap.compare(cur, pub)
    assert why["test"] == "same_fact" and why["contained"] is True, why
    assert "Kang Dynasty" in why["published"], why
    assert why["share"] >= ap.CONTAINED_SHARE and why["pair_share"] >= ap.CONTAINED_PAIR_SHARE, why
    # the other way round alone finds nothing: the fact is longer than anything said
    fw = ap.content(ap.words(DOOM_FACT))
    assert max(len(fw & ap.content(ap.words(s))) / len(fw) for s in pub["statements"]) < ap.FACT_SHARE


def test_the_doomsday_repeat_is_refused_at_step_two():
    old_row = row(OLD, slug="vanguards-doomsday", topic="lf-2026-10-13-007",
                  script_id="lf-2026-10-13-007-script1",
                  path="publish/example-tech/2026-10-19/vanguards-doomsday.mp4")
    mark = dict(MARK, slug="vanguards-doomsday", topic_id="lf-2026-10-13-007")
    root, new = make_root([old_row], old_script=DOOM_OLD, marks=(mark,))
    code, out = run([str(new), "--topic", "lf-2026-10-25-003", "--fact-text", DOOM_FACT,
                     "--fact-url", "https://en.wikipedia.org/wiki/Vanguards:_Doomsday#Production"])
    assert code == ap.EXIT_REPEAT, out
    assert "vanguards-doomsday.mp4" in out and "lies inside the fact" in out, out


def test_different_facts_of_one_franchise_are_not_contained():
    """User's rule: a franchise on hype is not limited - a repeat is the same
    fact, not the same work."""
    # live: the 08.10 Doomsday video (livestream stunts) against 1514Z's fact -
    # both "Comic-Con", "July", "announced", but another year and another event
    stunts = {"urls": set(), "text": "", "statements": [
        "Many cast members were announced in a nearly five-and-a-half-hour livestream.",
        "Marketing for Doomsday used several unique stunts.",
        "Those stunts followed the Comic-Con announcement in July twenty twenty four."]}
    assert ap.compare(ap.current_side(fact_text=DOOM_FACT), stunts) == []
    # live: 1514Z's other facts against everything 13T1411Z said
    pub = {"urls": set(), "text": "", "statements": ap.statements(DOOM_OLD)}
    for other in ("Filming took place from April to September 2025 at Pinewood Studios in England",
                  "In November 2023, Cretton departed, Waldron replaced Loveness as writer",
                  "Jonathan Majors was set to reprise his MCU role as the villain Kang the Conqueror"):
        assert ap.compare(ap.current_side(fact_text=other), pub) == [], other
    # the same sentence with another year is another fact
    other_year = {"urls": set(), "text": "", "statements": [
        "Two new Vanguards films, The Kang Dynasty and Secret Wars, were announced in July 2024"]}
    assert ap.compare(ap.current_side(fact_text=DOOM_FACT), other_year) == []


def test_a_short_published_sentence_does_not_swallow_a_fact():
    short = "It did not start as Doomsday."
    assert len(ap.content(ap.words(short))) < ap.CONTAINED_MIN_WORDS
    fact = ("It did not start as Doomsday: Zenith first announced the film in July 2022 as "
            "Vanguards: The Kang Dynasty, with Destin Daniel Cretton directing.")
    pub = {"urls": set(), "text": "", "statements": [short]}
    assert ap.compare(ap.current_side(fact_text=fact), pub) == []
    assert ap.contained(fact, [short]) is None


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
