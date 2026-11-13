#!/usr/bin/env python3
"""CF-0673: a `scale` comparison's reference and familiar size stand on the
pages they were read from, as pieces of the topic's support text.

`shared/factrule/scale_support.py` reads each stand-in's `source_url` through
the channel's door and keeps the passage where its number is written; the
pieces go to the batch's `01-scale-support.json` and `claims.topics_of` puts
them after the topic's own. Before it, the pattern file's own Proxima Centauri
script lost its Sun and its grapefruit as `source_not_in_support_text`.

Stand-ins only: the pages are strings, the client is a stub, the channel's
list is a minimal copy - no network, no live channel data (CF-0609); files
under `_tmproot.tmp_root` (CF-0489).
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "patterns"))

from _tmproot import tmp_root  # noqa: E402
import validate_patterns as vp  # noqa: E402


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ss = _load("scale_support_cf0673_test", ROOT / "shared" / "factrule" / "scale_support.py")
cl = ss.claims
TMP = tmp_root("scale-support-test-")

SUN_URL = "https://en.wikipedia.org/wiki/Sun"
FRUIT_URL = "https://en.wikipedia.org/wiki/Grapefruit"
NASA_URL = "https://science.nasa.gov/sun/facts/"
PROXIMA_URL = "https://en.wikipedia.org/wiki/Proxima_Centauri"

PAGES = {
    SUN_URL: {"title": "Sun", "url": SUN_URL, "source": "wikipedia", "revision_id": 111,
              "revised_at": "2026-10-01T00:00:00Z",
              "text": "The Sun is the star at the centre of the Solar System.\n\n"
                      "== Characteristics ==\n"
                      "Its diameter is about "
                      "1,391,400 km (864,600 mi), around 109 times that of Earth. Its mass "
                      "is about 330,000 times that of Earth.\n"
                      "The Sun is a G-type main-sequence star."},
    FRUIT_URL: {"title": "Grapefruit", "url": FRUIT_URL, "source": "wikipedia",
                "revision_id": 222, "revised_at": "2026-09-20T00:00:00Z",
                "text": "The grapefruit is a subtropical citrus tree known for its sour fruit.\n"
                        "== Description ==\n"
                        "The evergreen tree grows to around 5-6 m tall. The fruit is yellow-"
                        "orange skinned and generally an oblate spheroid in shape; it ranges "
                        "in diameter from 10 to 15 cm.\n"
                        "== History ==\n"
                        "The grapefruit was first documented in 1750."},
}

def _policy(verdict, host):
    return {"verdict": verdict, "checked_on": "2026-10-10",
            "checks": [{"robots_url": f"https://{host}/robots.txt", "path": "/",
                        "status": 200, "any_agent": True, "anthropic_blocked": [],
                        "ai_agents_blocked": [], "verdict": verdict}]}


SOURCES = {   # a minimal fact-sources list in the shape of channels/<id>/fact-sources.json
    "tiers": {
        "1": [{"id": "nasa", "hosts": ["nasa.gov"], "use": "cite_only",
               "ai_policy": _policy("allowed", "nasa.gov")},
              {"id": "nature_journals", "hosts": ["nature.com"], "use": "cite_only",
               "ai_policy": _policy("forbidden", "nature.com")}],
        "2": [{"id": "wikipedia", "hosts": ["wikipedia.org", "api.wikimedia.org"],
               "use": "read_text", "ai_policy": _policy("allowed", "en.wikipedia.org")},
              {"id": "closed_reader", "hosts": ["closed.example"], "use": "read_text",
               "ai_policy": _policy("forbidden", "closed.example")}],
    },
    "do_not_take": [{"id": "fandom", "hosts": ["fandom.com"]}],
}

REQUESTS = [
    {"part": "reference", "name": "the Sun's diameter", "source_url": SUN_URL,
     "value": 1391400, "unit": "km"},
    {"part": "familiar", "name": "a grapefruit", "source_url": FRUIT_URL,
     "value": 10, "unit": "cm"},
]


class Reader:
    """read_page(url) over PAGES, counting what it was asked."""

    def __init__(self, pages=PAGES, fail=()):
        self.pages, self.fail, self.asked = pages, set(fail), []

    def __call__(self, url):
        self.asked.append(url)
        if url in self.fail:
            raise OSError("connection refused")
        page = self.pages.get(url.split("#")[0])
        return copy.deepcopy(page) if page else None


def gate():
    return ss.channel_gate(SOURCES)


# The pattern file's Proxima Centauri example (patterns/scale.json
# writing_instruction; tests/test_scale_footing.py GOOD), with the reference
# and the familiar size quoted from Wikipedia and declared in claims[].
TOPIC = {
    "topic_id": "proxima",
    "support_check": {"state": "ok"},
    "support_text": [{
        "id": "wikipedia:Proxima_Centauri", "kind": "work_article", "source": "wikipedia",
        "title": "Proxima Centauri", "url": PROXIMA_URL, "revision_id": 333,
        "revised_at": "2026-10-02T00:00:00Z",
        "text": "Proxima Centauri is a small red dwarf star. It is 4.24 light-years away "
                "from the Sun, the closest star to the Sun."}],
}
SCRIPT = {
    "script_id": "sci-proxima-001", "topic_id": "proxima",
    "pattern": {"pattern_id": "scale", "rhythm_id": "hold"},
    "hook": "Shrink the Sun to a grapefruit, and the nearest star is still past Moscow.",
    "commentary": "Proxima Centauri is 4.24 light-years away. Make the Sun a grapefruit on a "
                  "London street, and Proxima is another grapefruit about two thousand eight "
                  "hundred kilometres away - past Moscow.",
    "payoff": "And that is the nearest one.",
    "fact": {"text": "Proxima Centauri is 4.24 light-years away from the Sun.",
             "kind": "measurement", "source": "Wikipedia", "url": PROXIMA_URL,
             "quote": "It is 4.24 light-years away from the Sun"},
    "scale": {
        "quantity": {"value": 4.24, "unit": "light-year", "quote": "4.24 light-years away"},
        "reference": {"value": 1391400, "unit": "km", "source_url": SUN_URL,
                      "quote": "Its diameter is about 1,391,400 km"},
        "familiar": {"object": "grapefruit", "value": 10, "unit": "cm",
                     "source_url": FRUIT_URL,
                     "quote": "it ranges in diameter from 10 to 15 cm"},
        "result": {"value": 2800, "unit": "km",
                   "said_as": "about two thousand eight hundred kilometres"},
    },
    "claims": [{
        "claim_id": "proxima-past-moscow", "where": "commentary",
        "text": "Proxima is another grapefruit about two thousand eight hundred kilometres "
                "away",
        "support": [
            {"source": "wikipedia:Proxima_Centauri",
             "quote": "It is 4.24 light-years away from the Sun"},
            {"source": "scale:wikipedia:Sun",
             "quote": "Its diameter is about 1,391,400 km"},
            {"source": "scale:wikipedia:Grapefruit",
             "quote": "it ranges in diameter from 10 to 15 cm"},
        ]}],
}


def _batch(name):
    batch = TMP / name
    batch.mkdir(parents=True)
    (batch / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC]}))
    (batch / "03-content-researcher.json").write_text(json.dumps({"scripts": [SCRIPT]}))
    return batch


def _codes(batch):
    [(sid, report)] = cl.check_batch_file(batch / "03-content-researcher.json")
    return [v["code"] for v in report["violations"]]


# ------------------------------------------------------------------ tests
def test_without_the_step_the_proxima_script_loses_its_sun_and_grapefruit():
    """The defect as CF-0565's worker found it."""
    codes = _codes(_batch("before"))
    assert codes.count(cl.FAIL_SOURCE_UNKNOWN) == 2, codes


def test_the_reference_and_the_familiar_size_become_pieces_and_the_claim_stands():
    batch = _batch("after")
    reader = Reader()
    result = ss.gather(REQUESTS, reader, gate(), existing=TOPIC["support_text"])
    assert [r["state"] for r in result["requests"]] == ["ok", "ok"], result["requests"]
    ids = [p["id"] for p in result["pieces"]]
    assert ids == ["scale:wikipedia:Sun", "scale:wikipedia:Grapefruit"], ids
    sun = result["pieces"][0]
    assert sun["kind"] == ss.PIECE_KIND and sun["url"] == SUN_URL and sun["revision_id"] == 111
    # the passage, not the page: the paragraph where the number stands, with its heading
    assert "about 1,391,400 km" in sun["text"] and "== Characteristics ==" in sun["text"]
    assert "centre of the Solar System" not in sun["text"]
    fruit = result["pieces"][1]
    assert "from 10 to 15 cm" in fruit["text"] and "1750" not in fruit["text"]
    ss.attach(batch, "proxima", result)
    assert _codes(batch) == [], _codes(batch)
    # the arithmetic record of the same script holds too, said_as in words included
    assert vp.check_scale_footing(SCRIPT)["verdict"] == "ok"
    # the 01 itself is never rewritten
    assert len(json.loads((batch / "01-trend-hunter.json").read_text())
               ["topics"][0]["support_text"]) == 1


def test_a_number_the_page_does_not_write_gets_no_piece():
    """«change the stand-in, never the number»: 12 cm is not on the page."""
    req = dict(REQUESTS[1], value=12)
    result = ss.gather([req], Reader(), gate())
    assert result["pieces"] == [] and result["requests"][0]["state"] == ss.STATE_NOT_ON_PAGE
    assert "never the number" in result["requests"][0]["detail"]


def test_a_quote_has_to_be_on_the_page_and_say_the_number():
    ok = dict(REQUESTS[0], quote="Its diameter is about 1,391,400 km")
    assert ss.gather([ok], Reader(), gate())["requests"][0]["state"] == ss.STATE_OK
    retyped = dict(ok, quote="The Sun is 1.4 million km wide")
    assert ss.gather([retyped], Reader(), gate())["requests"][0]["state"] == \
        ss.STATE_NOT_ON_PAGE
    wrong_number = dict(ok, value=1.5e6)
    assert ss.gather([wrong_number], Reader(), gate())["requests"][0]["state"] == \
        ss.STATE_NOT_ON_PAGE


def test_only_a_read_text_outlet_the_list_allows_is_read():
    reader = Reader()
    reqs = [dict(REQUESTS[0], source_url=NASA_URL),                         # cite_only
            dict(REQUESTS[0], source_url="https://www.nature.com/x"),       # cite_only, forbidden
            dict(REQUESTS[0], source_url="https://closed.example/sun"),     # read_text, forbidden
            dict(REQUESTS[0], source_url="https://x.fandom.com/wiki/Sun"),  # do_not_take
            dict(REQUESTS[0], source_url="https://unlisted.example/sun")]   # not listed
    result = ss.gather(reqs, reader, gate())
    assert [r["state"] for r in result["requests"]] == [ss.STATE_CLOSED] * 5, result
    assert reader.asked == [] and result["pieces"] == []
    assert "cite_only" in result["requests"][0]["detail"]
    assert "forbidden" in result["requests"][2]["detail"]


def test_the_door_says_why_an_empty_list_reads_nothing_and_takes_the_first_row_of_an_id():
    """The hunter's door had both before it asked the root (CF-0634): the
    empty-list refusal ends with `NO_LIST_TAIL`, and of two rows with one id in
    a tier the first one is the outlet."""
    why = ss.channel_gate({}).refusal(SUN_URL)
    assert why == (f"{SUN_URL}: no fact-sources list of the channel was given"
                   " - no outlet is readable without one"), why
    assert why.endswith(ss.NO_LIST_TAIL) and why.count(ss.NO_LIST_TAIL) == 1
    assert ss.channel_gate(None).refusal(SUN_URL) == why
    open_row = SOURCES["tiers"]["2"][0]
    closed_row = dict(open_row, ai_policy=_policy("forbidden", "en.wikipedia.org"))
    first_open = {"tiers": {"2": [open_row, closed_row]}}
    first_closed = {"tiers": {"2": [closed_row, open_row]}}
    assert ss.channel_gate(first_open).refusal(SUN_URL) is None
    assert "forbidden" in ss.channel_gate(first_closed).refusal(SUN_URL)


def test_no_gate_no_read():
    reader = Reader()
    result = ss.gather(REQUESTS, reader, None)
    assert {r["state"] for r in result["requests"]} == {ss.STATE_NO_GATE} and reader.asked == []


def test_an_unreachable_or_missing_page_and_a_malformed_request_are_named():
    reader = Reader(fail={SUN_URL})
    reqs = [REQUESTS[0],
            dict(REQUESTS[1], source_url="https://en.wikipedia.org/wiki/No_such_fruit"),
            {"part": "familiar", "name": "a grapefruit", "source_url": FRUIT_URL},
            {"part": "familiar", "value": 12, "unit": "cm"}]
    states = [r["state"] for r in ss.gather(reqs, reader, gate())["requests"]]
    assert states == [ss.STATE_UNREACHABLE, ss.STATE_NO_PAGE, ss.STATE_MALFORMED,
                      ss.STATE_MALFORMED], states


def test_a_page_already_in_the_topic_is_not_read_again():
    reader = Reader()
    req = {"part": "reference", "name": "Proxima's distance", "source_url": PROXIMA_URL,
           "value": 4.24, "unit": "light-year"}
    result = ss.gather([req], reader, gate(), existing=TOPIC["support_text"])
    assert result["requests"][0]["piece_id"] == "wikipedia:Proxima_Centauri"
    assert reader.asked == [] and result["pieces"] == []


def test_one_page_read_once_for_two_numbers_on_it():
    reader = Reader()
    reqs = [REQUESTS[0], {"part": "reference", "name": "Sun's mass vs Earth's",
                          "source_url": SUN_URL + "#Characteristics",
                          "quote": "Its mass is about 330,000 times that of Earth"}]
    result = ss.gather(reqs, reader, gate())
    assert reader.asked == [SUN_URL] and len(result["pieces"]) == 1


def test_a_number_written_in_words_on_the_page_is_found():
    pages = {FRUIT_URL: dict(PAGES[FRUIT_URL],
                             text="== Description ==\nThe fruit is about ten centimetres "
                                  "across.")}
    result = ss.gather([REQUESTS[1]], Reader(pages), gate())
    assert result["requests"][0]["state"] == ss.STATE_OK


def test_attach_replaces_a_piece_of_the_same_id_and_keeps_the_others():
    batch = TMP / "attach"
    first = ss.gather(REQUESTS, Reader(), gate())
    ss.attach(batch, "proxima", first)
    again = ss.gather(REQUESTS[:1], Reader(), gate())
    path = ss.attach(batch, "proxima", again)
    entry = ss.continuation_of(batch)["proxima"]
    assert [p["id"] for p in entry["support_text"]] == ["scale:wikipedia:Sun",
                                                         "scale:wikipedia:Grapefruit"]
    assert len(entry["requests"]) == 3 and path.name == cl.SCALE_SUPPORT_FILE
    merged = ss.merged_support(TOPIC, entry)
    assert [p["id"] for p in merged][0] == "wikipedia:Proxima_Centauri" and len(merged) == 3


def test_the_wikipedia_reader_goes_through_the_factorys_client():
    class Client:
        def __init__(self):
            self.titles = []

        def page(self, title):
            self.titles.append(title)
            if title != "Grapefruit":
                return None
            return {"title": "Grapefruit", "key": "Grapefruit", "url": FRUIT_URL,
                    "revision_id": 9, "revised_at": "2026-09-20T00:00:00Z",
                    "wikitext": "The fruit is about '''12 cm''' in diameter."}

    client = Client()
    read = ss.wikipedia_reader(client, lambda w: w.replace("'''", ""))
    page = read(FRUIT_URL + "#Description")
    assert client.titles == ["Grapefruit"] and page["text"] == \
        "The fruit is about 12 cm in diameter." and page["source"] == "wikipedia"
    assert read("https://de.wikipedia.org/wiki/Grapefruit") is None
    assert read(NASA_URL) is None and client.titles == ["Grapefruit"]
    assert ss.wikipedia_title("https://en.wikipedia.org/wiki/Proxima_Centauri") == \
        "Proxima Centauri"


# The live articles' own wikitext of the two stand-ins (read by the driver on
# 10.10, kept here as strings): the numbers are inside templates.
SUN_WIKITEXT = (
    "{{Short description|Star at the centre of the Solar System}}\n"
    "{{Infobox star|name=Sun|radius={{val|696342|u=km}}}}\n"
    "The '''Sun''' is the [[star]] at the centre of the [[Solar System]].<ref>{{cite web"
    "|url=https://example.org|title=x}}</ref>\n\n"
    "== Characteristics ==\n"
    "The Sun is a [[G-type main-sequence star]]. [[Solar radius|Its diameter]] is about "
    "{{val|1391400|u=km|fmt=commas}} ({{val|864600|u=mi|fmt=commas}}), around 109 times "
    "that of Earth.<ref name=\"NASA\"/>\n\n"
    "== References ==\n{{reflist}}\n")
GRAPEFRUIT_WIKITEXT = (
    "The '''grapefruit''' (''Citrus'' × ''paradisi'') is a [[subtropical]] [[citrus]] "
    "tree known for its relatively large, sour to semi-sweet, somewhat bitter fruit.\n\n"
    "== Description ==\n"
    "[[File:Grapefruit tree.jpg|thumb|A [[grapefruit]] tree]]\n"
    "The evergreen grapefruit trees usually grow to around {{convert|4.5|–|6|m|ft|abbr=on}} "
    "tall, although they can reach {{convert|13.7|m|ft|abbr=on}}.<ref>{{cite book|t=y}}"
    "</ref>\n"
    "The fruit is yellow-orange skinned and generally an oblate spheroid in shape; it "
    "ranges in diameter from {{convert|10|to|15|cm|in|0|abbr=on}}.\n")


class WikiClient:
    """The factory client's `page(title)` over stored wikitext - no network."""

    def __init__(self, texts):
        self.texts, self.titles = texts, []

    def page(self, title):
        self.titles.append(title)
        text = self.texts.get(title)
        if text is None:
            return None
        key = title.replace(" ", "_")
        return {"title": title, "key": key, "url": "https://en.wikipedia.org/wiki/" + key,
                "revision_id": 7, "revised_at": "2026-10-10T00:00:00Z", "wikitext": text}


def test_plain_text_keeps_the_numbers_val_and_convert_write():
    wp = ss.wikipedia_api()
    sun = wp.plain_text(SUN_WIKITEXT)
    assert "Its diameter is about 1,391,400 km (864,600 mi), around 109 times" in sun, sun
    assert "== Characteristics ==" in sun and "References" not in sun
    assert "cite web" not in sun and "696342" not in sun and "{{" not in sun
    fruit = wp.plain_text(GRAPEFRUIT_WIKITEXT)
    assert "ranges in diameter from 10 to 15 cm." in fruit, fruit
    assert "around 4.5 to 6 m tall, although they can reach 13.7 m." in fruit, fruit
    assert "File:" not in fruit and "thumb" not in fruit and " in)" not in fruit
    # the page's own unit only, and an e-unit as a number a reader reads
    assert wp.plain_text("{{convert|1.39|e6km|e6mi|abbr=on}}") == "1390000 km"
    assert wp.plain_text("{{val|1.39|e=6|u=km}}") == "1390000 km"
    assert wp.plain_text("{{convert|2|-|3|kg}} and {{convert|5|and|6|m}}") == \
        "2 to 3 kg and 5 to 6 m"
    assert vp.numbers_in(wp.plain_text("{{convert|1.39|e6km|e6mi}}")) == [1.39e6]


def test_plain_text_keeps_the_word_templates_the_wrappers_used_to_unwrap():
    """The possessive, the non-breaking space and money are words, not markup:
    the hunter's `fact_search.plain_text` and the researcher's
    `production_facts.clean_wikitext` unwrapped them before the root's reading;
    the root's one reading keeps them now - the possessive right after italics
    included, where a bare `'` would join the `''` and go with them."""
    wp = ss.wikipedia_api()
    assert wp.plain_text("''Coach Hale''{{'s}} first season") == "Coach Hale's first season"
    assert wp.plain_text("''Coach Hale''{{'}}s first season") == "Coach Hale's first season"
    assert wp.plain_text("''Slow Hounds''{{'s}} cast") == "Slow Hounds's cast"
    assert wp.plain_text("the Joneses{{'}} house") == "the Joneses' house"
    assert wp.plain_text("a budget of {{US$|2 million}}") == "a budget of $2 million"
    assert wp.plain_text("grossed {{USD|2 million|link=yes}} worldwide") == \
        "grossed $2 million worldwide"
    assert wp.plain_text("about{{nbsp}}12{{nbsp}}cm") == "about 12 cm"
    # italics and bold still go as markup, the words around them stay
    assert wp.plain_text("'''Bold''' and ''italic'' and " + "'" * 5 + "both" + "'" * 5) == \
        "Bold and italic and both"
    assert wp.plain_text("== ''Coach Hale''{{'s}} reception ==\nText.") == \
        "== Coach Hale's reception ==\nText."
    assert "\x02" not in wp.plain_text("''A''{{'s}} {{'}}")


def test_gather_finds_the_live_articles_numbers_through_the_default_reader():
    client = WikiClient({"Sun": SUN_WIKITEXT, "Grapefruit": GRAPEFRUIT_WIKITEXT})
    read = ss.wikipedia_reader(client)
    reqs = [{"part": "reference", "name": "the Sun's diameter", "source_url": SUN_URL,
             "value": 1391400, "unit": "km"},
            {"part": "familiar", "name": "a grapefruit", "source_url": FRUIT_URL,
             "value": 15, "unit": "cm"},
            {"part": "familiar", "name": "a grapefruit", "source_url": FRUIT_URL,
             "value": 10, "unit": "cm"},
            {"part": "familiar", "name": "a grapefruit", "source_url": FRUIT_URL,
             "value": 12, "unit": "cm"}]
    result = ss.gather(reqs, read, gate())
    states = [r["state"] for r in result["requests"]]
    # 12 cm is nowhere on the page: the range is 10 to 15 cm
    assert states == ["ok", "ok", "ok", "not_on_page"], result["requests"]
    assert client.titles == ["Sun", "Grapefruit"]          # one read per page
    sun, fruit = result["pieces"]
    assert "about 1,391,400 km" in sun["text"] and sun["revision_id"] == 7
    assert "from 10 to 15 cm" in fruit["text"] and "13.7 m" not in fruit["text"]
    # and the writer's quote of that passage is good footing for the claim rule
    topic = {"support_check": {"state": "ok"}, "support_text": result["pieces"]}
    rec, code = cl.judge_quote({"source": "scale:wikipedia:Grapefruit",
                                "quote": "it ranges in diameter from 10 to 15 cm"},
                               cl.support_pieces(topic))
    assert code is None and rec["section"] == "Description", (code, rec)


def test_the_continuation_file_name_is_one_name():
    assert ss.CONTINUATION_FILE == cl.SCALE_SUPPORT_FILE



def test_cf0737_a_number_and_its_unit_are_not_parted_at_an_abbreviation():
    """«U.S.», «Bros.», an initial: their stop is not the end of the sentence,
    so the number before one and its unit after it stand in one sentence."""
    text = "The Sun is 1,391,400 across by the U.S. Naval Observatory's count, in km."
    assert len(ss._SENTENCE_RE.split(text)) == 2, "control: the bare boundary parts them"
    assert ss._number_stands(1391400, "km", text) is True
    assert ss._number_stands(110, "t", "Example Studios moved 110 t of set. The rest stayed.")
    # a decimal is never a stop, and a real stop still parts two sentences
    assert ss._number_stands(27.5, "m", "The ship is 27.5 m long.") is True
    assert ss._number_stands(27.5, "m", "It cost 27.5 million. The hull is 9 m long.") is False
    assert ss.sentences.split_at("Dr. J. Smith measured 9 km. Then he left.", ss._SENTENCE_RE) == [
        "Dr. J. Smith measured 9 km.", "Then he left."]


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {type(error).__name__}: {error}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
