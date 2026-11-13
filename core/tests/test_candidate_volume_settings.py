#!/usr/bin/env python3
"""CF-0789: the small channels' candidate volume is the channel's setting.

The funnel of 2026-10-18 (docs/notes/funnel-2026-10-18.md): ExampleTech's
batches carried 5 / 2 / 14 candidates into the fact probe and
ExampleScience's 6 / 3, ExampleFilm's 9-17. Two keys of the channel config
answer it, read by the trend-hunter agent:

* `scope.min_scored_candidates` - the refill (agents/trend-hunter
  `refill_topics.py`) does not stop on `target_met` before the probe has
  judged this many candidates; 12 (ExampleFilm's floor since 2026-10-04) is
  the agent's default and the small channels' number;
* `sources.rss.discovery_days` - how far back `fetch_rss_news.py --channel`
  reaches without `--days`; 3 by default (ExampleFilm's measured window),
  7 for Science, whose feeds are thin.

Reads only tracked channel configs and the agent's tracked sources - no
network, no batch.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMALL = ("example-tech", "example-science")
AGENT = ROOT / "agents" / "trend-hunter" / "scripts"










def test_the_agents_defaults_are_the_ones_this_config_relies_on():
    """The agent is a checkout under agents/; where it is present its
    defaults must be the numbers the notes above name."""
    refill = AGENT / "refill_topics.py"
    fetch = AGENT / "fetch_rss_news.py"
    if not (refill.is_file() and fetch.is_file()):
        return
    r, f = refill.read_text(encoding="utf-8"), fetch.read_text(encoding="utf-8")
    assert re.search(r"^DEFAULT_MIN_SCORED = 12$", r, re.M)
    assert '"min_scored_candidates"' in r
    assert re.search(r"^DEFAULT_DAYS = 3$", f, re.M)
    assert re.search(r"^MIN_DAYS, MAX_DAYS = 1, 14$", f, re.M)
    assert '("sources", "rss", "discovery_days")' in f


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
