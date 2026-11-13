#!/usr/bin/env python3
"""CF-0919: news or evergreen by the video's own fact - the real pile of 04.11,
its titles, descriptions and claims copied here (15 videos of the reserve, the
new percy-jackson from its script, ipad-mini). No live file is read.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "agents" / "publisher"))

from _tmproot import tmp_root   # noqa: E402

import fact_kind as fk          # noqa: E402

TMP = tmp_root("fact-kind-test-")

# slug: (accepted, headline, claims, kind)
PILE = {
    "doctor-who": ("2026-11-03", [
        "Doctor Who theme: Ron Grainer, Delia Derbyshire and a 1964 Decca single",
        "The original Doctor Who theme was composed by Ron Grainer and realised by Delia "
        "Derbyshire. It was released as a single on Decca F 11837 in 1964."], [], "evergreen"),
    "the-gilded-age": ("2026-11-03", [
        "The Gilded Age: Julian Fellowes Reported Working on a Downton Abbey Prequel",
        "In September 2012, Julian Fellowes was reported as saying he was working on a spin-off "
        "prequel of Downton Abbey."], [
        "NBC originally announced ten episodes, set to premiere in twenty nineteen.",
        "The series premiered in January twenty twenty-two, with nine episodes.",
        "In twenty sixteen, Fellowes had not yet written the script.",
        "Now the fourth season has premiered, on November first.",
        "Sept 2012: Fellowes reported working on Downton prequel"], "evergreen"),
    "palantir": ("2026-11-04", [
        "Palantir Disclosed Over $196 Million in Funding in September 2013",
        "In September 2013, Palantir disclosed over $196 million in funding."], [
        "Sept. 2013: over $196M funding disclosed",
        "Forbes $9 billion December 2013 Funding round value",
        "Palantir $1 billion Estimated contracts for 2014"], "evergreen"),
    "binance": ("2026-11-04", [
        "Binance and MiCA: Existing Firms May Operate Until 1 July 2026",
        "CASPs already operating under national law before 30 December 2024 may continue during "
        "a transitional period until 1 July 2026."], [
        "Existing firms could operate until July first 2026 or a licence ruling.",
        "Reuters expected Binance's Greek MiCA licence to be rejected.",
        "In May 2026, Binance was blocked in the EU.",
        "Binance allowed U.S. stock and ETF trading from June 2026.",
        "United States June 2026 Stocks trading started"], "evergreen"),
    "exponential-time-hypothesis": ("2026-10-28", [
        "Exponential Time Hypothesis: Anthropic Says Claude Model Disproved ETH",
        "Also on October 26, Anthropic announced that an internal Claude model on October 16 had "
        "disproved ETH and published the details on GitHub."], [
        "Second, on October twenty sixth, twenty twenty six, OpenAI published a preprint "
        "containing a claimed disproof, produced by an internal LLM.",
        "October 26, 2026", "October 16: Claude model disproved ETH"], "evergreen"),
    "homepod-mini-2": ("2026-11-01", [
        "HomePod Mini wireless: 802.11n Wi-Fi, Bluetooth 5 and ultra-wideband",
        "HomePod Mini's wireless capabilities include 802.11n Wi-Fi, Bluetooth 5, and an "
        "ultra-wideband chip."], [
        "HomePod Mini 2 started shipping on October thirtieth.",
        "In June, the price rose to a hundred twenty nine dollars.",
        "October 30", "June 2026: $129"], "evergreen"),
    "rivian-r2": ("2026-11-01", [
        "Rivian R2 announced March 7, 2024, alongside the smaller R3",
        "The Rivian R2 was announced on March 7, 2024. Production began in April, and customer "
        "deliveries began in June."], [
        "The fine print on the Rivian R2: it was announced in March two thousand twenty four, "
        "and the cars came later.",
        "Production began: April 2026", "Deliveries began: June"], "evergreen"),
    "pixel-11-pro-fold": ("2026-11-01", [
        "Pixel 11 Pro Fold: Titan M3 Adds Post-Quantum Cryptography",
        "The Pixel 11 Pro Fold keeps its shape."], [], "evergreen"),
    "klara-and-the-sun": ("2026-11-01", [
        "Klara and the Sun: Slated for 2,000+ Theaters, Scaled Back After Poor Reviews",
        "Klara and the Sun was initially slated for a wide release in more than 2,000 theaters, "
        "but was scaled back."], [], "evergreen"),
    "visionquest": ("2026-11-01", [
        "VisionQuest: Bettany Back as Vision, Announced With the May 2024 Redevelopment",
        "VisionQuest is a spin-off and premiered on Example+ on October 13."], [
        "He goes on the run with a mysterious teenager who may be his reincarnated son.",
        "Filming began by March twenty twenty-five and wrapped in July, at Pinewood Studios.",
        "VisionQuest premiered on Example Animation plus on October thirteenth."], "evergreen"),
    "apple-intelligence": ("2026-10-31", [
        "Apple Intelligence Not Yet Available on China-Bought iPhones (March 2026)",
        "As of March 2026, Apple Intelligence is not available yet on devices purchased in "
        "mainland China. For mainland China, the first wave is due in December."], [
        "Apple said a developer beta rollout starts on November fourth.",
        "First wave: December"], "news"),
    "windows-11": ("2026-10-31", [
        "Windows 11 SE Support Ends October 2026, Microsoft Says",
        "In July 2025, Microsoft announced support for Windows 11 SE ends in October 2026."],
        [], "news"),
    "percy-jackson-new": ("2026-11-04", [
        "In December 2023, Example Animation announced that 13.3 million viewers watched the premiere "
        "episode."], [
        "The third season of Percy Jackson and the Olympians is slated to premiere on November "
        "twentieth, twenty twenty-six."], "news"),
    "percy-jackson-old": ("2026-11-01", [
        "Percy Jackson and the Olympians: Riordan Expected No Creative Control (2018)"], [
        "Season three is slated to premiere on November twentieth.",
        "In November twenty eighteen, Rick Riordan stated that he believed he would have no "
        "creative control.",
        "The series first arrived on Example Animation Plus in December twenty twenty-three."], "news"),
    "ipad-mini": ("2026-11-03", [
        "iPad Mini: Announced Oct. 23, 2012, Released Nov. 2, 2012",
        "The eighth-generation iPad Mini was announced on October 26, 2026, and will be released "
        "on November 6, 2026."], [
        "The eighth-generation iPad Mini was announced on October twenty sixth and will be "
        "released on November sixth."], "news"),
    "pride-and-prejudice": ("2026-11-01", [
        "Pride and Prejudice (ExampleStream): Dolly Alderton Reported Adapting Austen in Oct 2024",
        "It is stated for release on the third of December."], [], "news"),
    "the-mosquito-bowl": ("2026-11-01", [
        "The Mosquito Bowl: Galitzine and Skarsgård Cast in Leading Roles",
        "In late April 2025, it was announced that the actors were cast."], [
        "Scenes were also shot for one day in November at Brown Stadium in Rhode Island.",
        "the film reaches ExampleStream on November twenty-fifth, after opening in U.S. theaters."],
        "news"),
}


def _day(s):
    return date.fromisoformat(s)


def test_the_real_pile_of_04_11_by_its_fact():
    got = {slug: fk.judge(h, c, _day(on))["feed_kind"] for slug, (on, h, c, _k) in PILE.items()}
    want = {slug: row[3] for slug, row in PILE.items()}
    assert got == want, {k: (got[k], want[k]) for k in got if got[k] != want[k]}


def test_what_a_news_says_and_the_date_it_goes_off_on():
    on, h, c, _ = PILE["apple-intelligence"]
    r = fk.judge(h, c, _day(on))
    assert r["news_why"] == "«is due»" and r["ahead"] == "2026-12-31", r
    on, h, c, _ = PILE["percy-jackson-new"]
    assert fk.judge(h, c, _day(on))["ahead"] == "2026-11-20"
    on, h, c, _ = PILE["ipad-mini"]
    assert fk.judge(h, c, _day(on))["ahead"] == "2026-11-06"
    on, h, c, _ = PILE["windows-11"]
    r = fk.judge(h, c, _day(on))
    assert r["fresh"] == "2026-10-31" and r["ahead"] is None and "October 2026" in r["news_why"], r
    on, h, c, _ = PILE["the-mosquito-bowl"]
    assert "November twenty-fifth" in fk.judge(h, c, _day(on))["news_why"]


def test_the_60_day_edge_of_a_named_date():
    h = ["The deal closed on September 5, 2026."]
    assert fk.judge(h, [], date(2026, 11, 4))["feed_kind"] == "news"       # 60 days
    assert fk.judge(h, [], date(2026, 11, 5))["feed_kind"] == "evergreen"  # 61 days
    # a fresh date only in a claim is the video's background, not its fact
    assert fk.judge(["A title"], h, date(2026, 11, 4))["feed_kind"] == "evergreen"
    # a date ahead counts wherever it is said, a year ahead too
    assert fk.judge(["A title"], ["It opens on March 5, 2027."], date(2026, 11, 4))["ahead"] \
        == "2027-03-05"
    assert fk.judge(["Support runs until 2028"], [], date(2026, 11, 4))["ahead"] == "2028-12-31"
    # with no year, ahead only when the sentence does not tell of the past
    assert fk.judge(["A title"], ["It was released on November 20."], date(2026, 11, 4))[
        "feed_kind"] == "evergreen"


def test_the_words_of_what_is_to_come():
    for s in ("The phone is due in March", "Doctor Who will return", "the upcoming film",
              "It is coming to ExampleStream", "Apple Will Release a New Phone", "it arrives next year",
              "The season is slated to premiere"):
        assert fk.FUTURE_RE.search(s), s
    for s in ("It was released in 2020", "Will Smith stars", "an argument about free will",
              "cut due to poor reviews", "a coming-of-age film", "coming to terms",
              "was slated to premiere", "initially slated for", "becoming a star"):
        assert not fk.FUTURE_RE.search(s), s


def test_dates_are_read_digit_and_spoken():
    on = date(2026, 11, 4)
    cases = {
        "October 26, 2026": "2026-10-26", "Oct. 23, 2012": "2012-10-23", "1 July 2026": "2026-07-01",
        "the third of December": "2026-12-03", "2026-11-20": "2026-11-20",
        "November twentieth, twenty twenty-six": "2026-11-20", "July first 2026": "2026-07-01",
        "October twenty sixth, twenty twenty six": "2026-10-26", "Sept 2012": "2012-09-01",
        "Nov. 2018": "2018-11-01", "March twenty twenty-five": "2025-03-01",
        "December twenty twenty-three": "2023-12-01", "In November twenty eighteen": "2018-11-01",
        "March two thousand twenty four": "2024-03-01", "in nineteen sixty four": None,
        "Existing Firms May Operate": None, "March on": None, "2,000 October": None,
    }
    for text, start in cases.items():
        found = fk.dates_in(text, on)
        assert (found[0]["start"].isoformat() if found else None) == start, (text, found)
    assert fk.dates_in("in December", on)[0]["end"] == date(2026, 12, 31)
    assert fk.dates_in("Release: December, iOS 27.3", on)[0]["year_named"] is False
    assert fk.dates_in("Support: November 31, 2026", on) == []


def test_the_note_is_read_without_the_source_line_quotes_and_the_publication():
    note = """# x

## Название
A Title of 1964 #shorts

## Описание
The fact is old.

The fact in this video comes from: Wikipedia, x (will be read) · https://example.org/2026-12-01

#x #tech

## Утверждения
- **диктор:** «The theme was recorded.»
  → «It will be released on December 1, 2026.» — [Wikipedia](https://example.org)

## Публикация
Слот не назначен. **2026-12-01 01:00 МСК**
"""
    h, c = fk.from_note(note)
    assert h == ["A Title of 1964", "The fact is old."], h
    assert c == ["The theme was recorded."], c
    p = TMP / "note.md"
    p.write_text(note, encoding="utf-8")
    assert fk.of_video(p, None, None, date(2026, 11, 4))["feed_kind"] == "evergreen"


def test_with_no_card_or_claims_the_script_is_read():
    b = TMP / "batch"
    b.mkdir(parents=True, exist_ok=True)
    (b / "03-content-researcher.json").write_text(json.dumps({"scripts": [
        {"topic_id": "t1", "fact": {"text": "An old fact of 1964."},
         "claims": [{"text": "A later season is slated to premiere."}],
         "narration": {"words": 170, "action": "pass"}},
        {"topic_id": "t2", "fact": {"text": "An old fact of 1964."}, "claims": []}]}),
        encoding="utf-8")
    assert fk.of_video(None, b, "t1", date(2026, 11, 4))["feed_kind"] == "news"
    assert fk.of_video(None, b, "t2", date(2026, 11, 4))["feed_kind"] == "evergreen"
    assert fk.of_video(None, b, "no-such", date(2026, 11, 4))["feed_kind"] == "evergreen"
    assert fk.of_video(None, None, None, date(2026, 11, 4))["feed_kind"] == "evergreen"
    # a card with no claims: its headline, the claims of the script
    p = TMP / "card.md"
    p.write_text("# x\n\n## Название\nOnly a title\n\n## Описание\nOnly words.\n", encoding="utf-8")
    assert fk.of_video(p, b, "t1", date(2026, 11, 4))["feed_kind"] == "news"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
