# News candidates of a fact: what dropping them costs (CF-0638, 2026-10-08)

The user's decision of 08.10 (CF-0557 Q1 variant b): the feeds are for choosing
topics; the writer gets no excerpt of them. `fact_search.news_candidates` made a
fact candidate out of a feed entry ("Variety reported ...", the entry's summary
as its text), so a feed's text reached the writer as a fact. Before closing
that path, `scripts/news_fact_measure.py` asked example-film's batches what it
costs (read-only, `pipeline/example-film/`, the production checkout, 2026-10-08).

    scripts/news_fact_measure.py --channel example-film

| | count |
|---|---|
| batches read | 24 (2026-09-15T1034Z .. 2026-10-05T0701Z) |
| batches with a recorded candidate list (CF-0438, since 2026-10-01T1313Z) | 6 |
| batches on 1.8 (since 2026-10-06) | 0 |
| selected topics in those 6 batches | 48 |
| ... with a passing news candidate | 11 |
| ... whose every passing candidate was a news one (would become `no_fact`) | **0 (0 %)** |
| reserve (`below_shortlist`) topics in the same position | 0 |
| scripts whose writer took a news candidate as its `fact` | 2 (`lf-2026-10-04-002`, `lf-2026-10-05-003`) |
| passing news candidates | 21, all 21 with the feed summary as their text |

The four batches 2026-10-01T1313Z .. 2026-10-02T1748Z are rebuilds over the same
topics, so the 11 topics are fewer distinct ones. Every topic that had a news
candidate also had a passing Wikipedia one; the two scripts that used a news
fact had a Wikipedia fact to fall back on. The threshold of the task (stop when
more than ~10 % of topics would be lost) is not reached - the change goes ahead.

**The summary of `evidence.sources[]`** (item 3). The one mechanical reader of
it is the fact-to-scene fit (the root's `fact_scene.world_texts`, CF-0548, run by
`check_scenes.py` here and by the Content Researcher's `production_facts.py`).
The same script replays the fit with every summary and every news candidate
gone: 31 sources carried a summary (2026-10-05T0701Z only - CF-0533 began
writing it that day), **no topic loses its fit**, and in 2 topics
(`lf-2026-10-04-003`, `lf-2026-10-05-005`) the first fitting candidate
changes - a Wikipedia sentence instead of a news one.

The earlier 18 batches predate the recorded candidate list and cannot be
replayed without the feeds and Wikipedia as they stood at the batch's hour.
