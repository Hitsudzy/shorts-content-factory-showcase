#!/usr/bin/env python3
"""CF-0708: an RSS 1.0 / RDF feed (Nature's) dates its items with `dc:date`,
which feedparser files under `updated`; the fetch must read it, or every entry
of such a feed comes out undated and is unusable for a proof."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import fetch_rss_news as rss  # noqa: E402

FEED = "https://www.nature.com/nature.rss"

RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://www.nature.com/nature"><title>Nature</title>
<link>https://www.nature.com/nature</link></channel>
<item rdf:about="https://www.nature.com/articles/a1"><title>Artemis II</title>
<link>https://www.nature.com/articles/a1</link><dc:date>2026-10-12</dc:date></item>
<item rdf:about="https://www.nature.com/articles/a2"><title>Undated</title>
<link>https://www.nature.com/articles/a2</link></item>
</rdf:RDF>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
<entry><title>Both</title><link href="https://x.test/both"/><id>1</id>
<published>2026-10-10T08:00:00Z</published><updated>2026-10-12T09:00:00Z</updated></entry>
<entry><title>Updated only</title><link href="https://x.test/upd"/><id>2</id>
<updated>2026-10-11T07:30:00Z</updated></entry>
</feed>"""


def test_rdf_dc_date_becomes_published_at():
    title, entries = rss.parse_rss(RDF, FEED, 200)
    assert title == "Nature", title
    by = {e["title"]: e for e in entries}
    assert by["Artemis II"]["published_at"] == "2026-10-12T00:00:00+00:00", by["Artemis II"]
    assert by["Undated"]["published_at"] is None, by["Undated"]


def test_published_wins_over_updated_and_updated_is_the_fallback():
    _, entries = rss.parse_rss(ATOM, "https://x.test/feed", 200)
    by = {e["title"]: e for e in entries}
    assert by["Both"]["published_at"] == "2026-10-10T08:00:00+00:00", by["Both"]
    assert by["Updated only"]["published_at"] == "2026-10-11T07:30:00+00:00", by["Updated only"]


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
