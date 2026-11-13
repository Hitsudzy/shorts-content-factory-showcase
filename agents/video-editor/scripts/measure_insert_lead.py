#!/usr/bin/env python3
"""CF-0143: where the meme layer's two floors come from.

`inserts/meme.json` shipped `selection.min_similarity: 0.2` with its own note
saying the number came from the model's usual range and not from this library.
On the library CF-0115 filled (101 entries) it refuses nothing: every query
this file measures, including thirty that no picture in the folder answers,
has a leader over 0.2. A layer that never says `no_asset` is a first rung of
the CF-0137 ladder that never passes the block on.

What this measures, and the only honest way to pick a number: run a set of
queries whose right answer is known against a set of queries that have no
right answer at all, and look at whether any statistic separates the two.

    HITS   30 queries describing one picture in the library, in the register
           CF-0115 established for `default_query` - the frame, not the
           feeling. The expected id (sometimes a near-duplicate pair) is
           written next to each. A query whose pick is not the expected
           picture counts as a *wrong* pick, not as a hit: the layer placing
           the wrong meme is the failure this measurement is about.
    MISSES 41 queries for pictures the library does not hold - a beekeeper,
           a courtroom, a jellyfish - plus near-misses in register ("a person
           crying alone in the rain", "a teacher at a chalkboard in an empty
           classroom") where a reaction library plausibly might have
           something and does not, and the two pictures it holds but cannot
           place (below).
    VOCAB  the eleven `default_query` strings, reported but not scored: what
           the shipped vocabulary does at the chosen numbers.

The pick is the walk's, not the raw leader (CF-0402): meme_layer's select()
steps over a leader the CF-0392 stretch gate refuses and offers the request
to the next rank, with that rank's own lead, provided the cut leader cleared
both floors. `stretch_cut()` computes that set from the files with
meme_layer's arithmetic - on 2026-10-04 laughing-leo (2.30x) and
bugs-bunny-communist (2.35x) against the 2.25x ceiling. They rank, they can
never be placed, so HITS may not expect them and MISSES asks for both.

What came out first (2026-09-08, 101 entries, 23 hits / 37 wrong picks):

    rule                                      right picks kept / wrong taken
    the shipped min_similarity 0.2, no lead                   1.00 / 0.84
    the leader's score alone, >= 0.26                         0.96 / 0.14
    the lead alone, >= 0.026 over the third place             0.91 / 0.16
    the lead measured over the *second* place instead         0.70 / 0.03
    both floors, 0.26 and 0.02 over the third                 0.96 / 0.05

and the numbers chosen then sat in the middle of a plateau: min_similarity
0.26 held 0.96 / 0.05 anywhere in 0.258-0.262, min_lead 0.02 anywhere in
0.018-0.024.

What comes out now (CF-0402, 2026-10-04, 28 entries after the user's
deletions of 24.09 and the CF-0466 pass, HITS and the new near-misses
rewritten for them; 27 right picks / 44 wrong ones):

    rule                                      right picks kept / wrong taken
    the shipped min_similarity 0.2, no lead                   1.00 / 0.66
    the leader's score alone, >= 0.26                         0.78 / 0.045
    the lead alone, >= 0.026 over the third place             0.78 / 0.14
    the lead measured over the *second* place instead         0.52 / 0.045
    both floors, 0.26 and 0.02 over the third                 0.78 / 0.045

The third place still earns its keep: spirerunner-pointing leads its twin by
0.004, hide-the-pain-harold the coffee-typing gif by 0.002,
leonardo-dicaprio-cheers the cut laughing-leo by 0.003 - against the second
place half the right picks are refused. The two wrong picks taken (a
grey-haired man with a mug -> jim-carrey-typing-coffee at 0.284, a man asleep
on a sofa -> facepalm-old-man at 0.269) clear both floors by a wide margin
and no number near the chosen pair refuses them.

The numbers do **not** reproduce as the middle of a plateau any more. The
wrong-taken count is flat (2/44) for min_similarity 0.255-0.269 at any
min_lead up to 0.028, but recall is not: surprised-pikachu's right pick
scores 0.259 and futurama-fry's 0.261, so 0.26 sits between two right picks,
and the best band - 0.81 / 0.045, one more right pick at no cost - is
0.255-0.259. On this set the lead floor refuses nothing the similarity floor
has not already refused (score alone = both floors), and 0.02 sits on the
upper edge of its flat band 0.000-0.021, one thousandth under futurama-fry's
lead. What the numbers in inserts/meme.json should be is the user's call
(CF-0320): this file reports, it does not move them. `--scan` prints the
band.

Not scored here, and worth saying: the eleven vocabulary defaults were the
weakest queries in the set on 2026-09-08 - five of them refused at these
numbers, three of those refusals losing a picture that was in fact the right
one, and two more (`confused`, `deadpan`) accepted onto a picture of a
different intent. That was a vocabulary problem (CF-0115 rewrote it once),
not a threshold one. CF-0147 (2026-09-15) rewrote six of the eleven against
this measurement; on 2026-10-04 ten of the eleven clear both floors onto the
picture `inserts/meme.json` records beside them as `expected_leader` (lowest
0.276) and `iceberg` records none. The VOCAB block reports that match and
still keeps the eleven out of the labelled set, so a vocabulary tuned against
this script can never flatter the thresholds it prints.

Usage:
    measure_insert_lead.py [--root <factory root>] [--scan] [--json <path>]

Needs the CLIP text encoder: run it with the main checkout's .venv, from the
factory root. About twenty seconds, most of it loading the model; the
stretch gate reads each file's size, so `--root` has to hold the files too.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

# (query, ids any one of which is the right answer). CF-0402 (2026-10-04):
# written against the 28-entry library after the CF-0466 pass, before the
# first run, and not reworded after it - a set tuned until it passes would
# measure the wording, not the floors. Twins are listed both ways round.
HITS = [
    ("a man with wild swept-up hair in a suit holding both hands out, palms up", ["ancient-aliens"]),
    ("a frantic man pointing at a corkboard of papers linked with red string",
     ["charlie-conspiracy"]),
    ("a bald spectator in a checked shirt and padded vest in the stands, hands on hips",
     ["disappointed-cricket-fan"]),
    ("a little girl with a sly smile while a house burns in the background", ["disaster-girl"]),
    ("a man on a street turning to check out a woman in red while his girlfriend looks appalled",
     ["distracted-boyfriend"]),
    ("two huge muscular arms locked together in a handshake", ["epic-handshake"]),
    ("an elderly man in a red jumper hiding his whole face behind his hand", ["facepalm-old-man"]),
    ("a bearded long-haired man in medieval costume rubbing his forehead with his eyes shut",
     ["frustrated-boromir"]),
    ("a cartoon young man with orange hair narrowing his eyes suspiciously", ["futurama-fry"]),
    ("an old lady staring at a laptop through her spread fingers", ["grandma-finds-the-internet"]),
    ("a smiling man in a black coat flashing a peace sign next to a grave",
     ["grant-gustin-over-grave"]),
    ("a schoolboy at a desk, face flushed red, jaw clenched, glaring to the side",
     ["guy-about-to-explode"]),
    ("a grey-haired man at a computer holding a coffee mug with a forced smile",
     ["hide-the-pain-harold"]),
    ("an old farmer in a baseball cap and overalls grinning in front of crops",
     ["honest-work-farmer"]),
    ("a pyramid with an eye in a shining triangle at its top, as on a banknote", ["illuminati-eye"]),
    ("a yellow square cartoon character making a rainbow between his hands",
     ["imagination-spongebob"]),
    ("a grinning man typing fast at an old computer with a coffee mug beside him",
     ["jim-carrey-typing-coffee", "jim-carrey-typing-fast"]),
    ("two hands hammering a keyboard so fast the fingers blur",
     ["jim-carrey-typing-fast", "jim-carrey-typing-coffee"]),
    ("a man in black tie lifting a glass of champagne in a toast", ["leonardo-dicaprio-cheers"]),
    ("an office worker in a shirt and tie covering his eyes with his hand and wincing",
     ["michael-scott-frustrated"]),
    ("a long-haired man at a council table holding up one finger as he explains",
     ["one-does-not-simply"]),
    ("a young man grinning and pointing at his own head", ["roll-safe"]),
    ("two men in the same red and blue costume pointing at each other",
     ["spirerunner-pointing", "spirerunner-triple"]),
    ("three people in identical superhero suits all pointing at one another",
     ["spirerunner-triple", "spirerunner-pointing"]),
    ("a yellow cartoon creature with red cheeks gaping, its mouth a small round O",
     ["surprised-pikachu"]),
    ("a man in a black shirt leaning towards the camera with a wide grin", ["yo-dawg-heard-you"]),
    ("a man covering his face with one hand in despair",
     ["facepalm-old-man", "michael-scott-frustrated", "frustrated-boromir"]),
    ("firefighters at a burning house with a child in the foreground", ["disaster-girl"]),
    ("an older man at a laptop smiling through obvious discomfort", ["hide-the-pain-harold"]),
    ("a cartoon delivery boy squinting, not sure what he is looking at", ["futurama-fry"]),
]

MISSES = [
    "a bowl of ramen with chopsticks resting on the rim",
    "a red sports car on a coastal highway at sunset",
    "a knitted wool scarf folded on a wooden chair",
    "a surgeon in scrubs operating under bright theatre lights",
    "a violinist playing on a concert stage",
    "a plate of sushi arranged on a black slate",
    "a snowy mountain range at dawn",
    "a beekeeper in a white suit lifting a honeycomb frame",
    "a submarine surfacing in open ocean",
    "a courtroom with a judge in a wig behind the bench",
    "a field of sunflowers in bright sun",
    "a mechanic working under a car on a garage lift",
    "a bride and groom cutting a wedding cake",
    "a chess grandmaster leaning over a board in a tournament hall",
    "a jellyfish drifting in dark water",
    "a bricklayer building a wall with mortar",
    "a hot air balloon over a river valley",
    "a bowl of blueberries on a kitchen counter",
    "a dentist examining a patient's teeth",
    "a lighthouse on a rocky shore in a storm",
    "a person crying alone in the rain on a city street",
    "a crowd of protesters holding placards in a square",
    "a baby taking its first steps across a carpet",
    "a nurse drawing blood from a patient's arm",
    "a hollow shaping a bowl on a spinning wheel",
    "a firefighter carrying a hose up a ladder",
    "a train platform crowded at rush hour",
    "a cat sleeping curled on a radiator",
    "an old typewriter on a desk beside a stack of paper",
    "a scuba diver swimming over a coral reef",
    # CF-0402: near-misses for what CF-0466 added (a farmer, a classroom, a
    # cartoon, a desk at a computer) - written blind with the HITS above;
    # "two businessmen shaking hands" was dropped as a label, since
    # epic-handshake is a fair answer to it.
    "a tractor ploughing a muddy field",
    "a teacher writing on a chalkboard in an empty classroom",
    "a cartoon cat chasing a mouse through a kitchen",
    "a woman laughing with friends at a dinner party",
    "a man in a suit giving a speech at a podium",
    "a toddler crying in a supermarket aisle",
    "a man asleep on a sofa with the television on",
    "a programmer at a desk with three monitors at night",
    "a cowboy riding a horse across a desert",
    # CF-0392: pictures the library holds and the stretch gate cuts - the
    # walk must place nothing here, not the next picture down.
    "a man in a period suit laughing and pointing at the camera with a drink",
    "a cartoon rabbit holding up a red flag with a hammer and sickle",
]


def load(root):
    """(entries, vocabulary) from the factory root, with that root's own
    scripts/index_inserts.py and shared/inserts/inserts_lib.py on the path."""
    root = Path(root)
    for rel in ("scripts", "shared/inserts"):
        sys.path.insert(0, str(root / rel))
    index = json.loads((root / "shared" / "inserts" / "memes" / "index.json").read_text())
    spec = json.loads((root / "inserts" / "meme.json").read_text())
    return index["entries"], spec["selection"]["intent_vocabulary"]


def rankings(entries, queries):
    """One sorted (score, id) list per query - rank_by_embedding's arithmetic,
    kept here so the measurement needs no library import beyond the encoder."""
    import index_inserts
    out = []
    for vec in index_inserts.embed_texts(queries):
        scored = [(round(sum(a * b for a, b in zip(e["embedding"], vec)), 4), e["id"])
                  for e in entries if e.get("embedding")]
        scored.sort(key=lambda p: (-p[0], p[1]))
        out.append(scored)
    return out


def lead(ranked, k, i=0):
    """The margin of rank `i` (0-based) over the rank `k - 1` places below it,
    missing ranks counting 0 - meme_layer.lead_over_field(ranked, i, k)."""
    if i >= len(ranked):
        return 0.0
    below = i + k - 1
    return round(ranked[i][0] - (ranked[below][0] if below < len(ranked) else 0.0), 4)


def stretch_cut(root, entries):
    """CF-0392: the ids whose file the asset gate refuses for stretch - fitted
    `contain` into the insert box they would be upscaled past
    `asset_floor.max_upscale_factor`. They still rank (their embeddings are
    in the index) but the walk can never place them, so they cannot be the
    right answer to anything. Computed from the files with meme_layer's own
    arithmetic, never listed by hand: a re-cut file changes the set."""
    import meme_layer
    root = Path(root)
    spec = json.loads((root / "inserts" / "meme.json").read_text())
    box, ceiling = meme_layer.meme_box(), meme_layer.max_upscale(spec)
    cut = set()
    for e in entries:
        path = root / "shared" / "inserts" / "memes" / e["file"]
        size = meme_layer.asset_dimensions(str(path)) if path.exists() else None
        if size and all(size) and meme_layer.upscale_factor(size, box) > ceiling + 1e-9:
            cut.add(e["id"])
    return cut


def pick(ranked, cut=frozenset()):
    """The rank the walk would place: the first candidate the stretch gate
    lets through (meme_layer's select() steps over a gated leader to the next
    rank). None when every candidate is cut."""
    return next((i for i, (_s, eid) in enumerate(ranked) if eid not in cut), None)


def accepts(ranked, min_sim, min_lead, lead_rank, cut=frozenset()):
    """meme_layer's CLIP walk, without the files: every rank down to the
    pick has to clear both floors - a stretch-cut leader that fails one ends
    the walk exactly as it does in select(), and one that passes hands the
    request to the next rank with that rank's own lead."""
    for i, (score, eid) in enumerate(ranked):
        if score < min_sim or lead(ranked, lead_rank, i) < min_lead:
            return False
        if eid not in cut:
            return True
    return False


def measure(root, scan=False, out=print):
    entries, vocab = load(root)
    cut = stretch_cut(root, entries)
    bad = [eid for _q, ids in HITS for eid in ids if eid in cut]
    assert not bad, f"HITS expects pictures the stretch gate cuts: {sorted(set(bad))}"
    voc_names = list(vocab)
    # CF-0147: what the eleven are expected to lead onto, for the report only.
    # They are appended after the labelled queries and never reach `pos`/`neg`
    # below - the vocabulary is tuned against this script, so letting it score
    # would let a rewrite of meme.json move the thresholds it is judged by.
    recorded = {n: vocab[n].get("expected_leader") for n in voc_names}
    queries = ([q for q, _ in HITS] + list(MISSES)
               + [vocab[n]["default_query"] for n in voc_names])
    ranked = rankings(entries, queries)
    n_hit, n_miss = len(HITS), len(MISSES)

    def placed(r):
        i = pick(r, cut)
        return (None, 0.0, 0.0, 0.0) if i is None else (
            r[i][1], r[i][0], lead(r, 3, i), lead(r, 2, i))

    pos, neg, rows = [], [], []
    for i, r in enumerate(ranked):
        if i < n_hit:
            group = "hit" if placed(r)[0] in HITS[i][1] else "wrong"
            (pos if group == "hit" else neg).append(r)
        elif i < n_hit + n_miss:
            group = "wrong"
            neg.append(r)
        else:
            group = "vocab:" + voc_names[i - n_hit - n_miss]
        rows.append((group, queries[i], r))

    assert len(pos) + len(neg) == n_hit + n_miss, "the vocabulary stays out of the labels"

    out(f"library {len(entries)} entries ({len(cut)} cut by the stretch gate: "
        f"{', '.join(sorted(cut)) or 'none'}), {len(pos)} right picks, {len(neg)} wrong ones\n")
    out(f"{'group':14} {'s1':>6} {'lead3':>7} {'lead2':>7}  pick (after the stretch gate)")
    for group, query, r in rows:
        mark = ""
        eid, s1, l3, l2 = placed(r)
        if group.startswith("vocab:"):
            want = recorded[group[6:]]
            mark = (" " if eid == want or want is None
                    else f" WRONG, expected {want}")
        if r[0][1] in cut:
            mark += f" (leader {r[0][1]} cut)"
        out(f"{group[:14]:14} {s1:6.3f} {l3:+7.3f} {l2:+7.3f}  "
            f"{str(eid):26} {query[:44]}{mark}")

    voc = [(voc_names[i - n_hit - n_miss], r) for i, r in enumerate(ranked) if i >= n_hit + n_miss]
    ok_lead = sum(1 for n, r in voc if placed(r)[0] == recorded[n])
    ok_gate = sum(1 for n, r in voc
                  if accepts(r, 0.26, 0.02, 3, cut) and placed(r)[0] == recorded[n])
    out(f"\nvocabulary (not scored above): {ok_lead}/{len(voc)} lead onto the recorded picture, "
        f"{ok_gate}/{len(voc)} of those also clear 0.26 + 0.02 @ 3")

    def rate(rs, a, b, k):
        return round(sum(1 for r in rs if accepts(r, a, b, k, cut)) / len(rs), 3) if rs else 0.0

    out("\nrecall / wrong accepted")
    for label, args in (("shipped 0.2, no lead   ", (0.2, 0.0, 1)),
                        ("score only  >= 0.26    ", (0.26, 0.0, 1)),
                        ("lead only   >= 0.026@3 ", (0.0, 0.026, 3)),
                        ("lead to the second      ", (0.26, 0.02, 2)),
                        ("CHOSEN 0.26 + 0.02 @ 3 ", (0.26, 0.02, 3))):
        out(f"  {label} {rate(pos, *args):.2f} / {rate(neg, *args):.3f}")

    if scan:
        out("\nplateau (recall/wrong) around the chosen pair")
        for a in (0.250, 0.254, 0.255, 0.257, 0.259, 0.260, 0.262, 0.266, 0.270):
            cells = " ".join(f"{b:.3f}:{rate(pos, a, b, 3):.2f}/{rate(neg, a, b, 3):.3f}"
                             for b in (0.010, 0.014, 0.018, 0.020, 0.022, 0.028))
            out(f"  min_similarity {a:.3f}  min_lead {cells}")
        out("\nlead_rank (best min_lead per rank, at min_similarity 0.26)")
        for k in (2, 3, 4, 5, 6, 8, 10):
            best = max(((rate(pos, 0.26, b / 1000, k) - rate(neg, 0.26, b / 1000, k),
                         b / 1000, rate(pos, 0.26, b / 1000, k), rate(neg, 0.26, b / 1000, k))
                        for b in range(0, 90, 2)))
            out(f"  k={k:<3} min_lead {best[1]:.3f}  {best[2]:.2f} / {best[3]:.2f}")

    scores = {"library": len(entries), "stretch_cut": sorted(cut),
              "right": len(pos), "wrong": len(neg),
              "chosen": {"min_similarity": 0.26, "min_lead": 0.02, "lead_rank": 3,
                         "recall": rate(pos, 0.26, 0.02, 3),
                         "wrong_accepted": rate(neg, 0.26, 0.02, 3)},
              "vocabulary": {"leader_matches_record": ok_lead, "and_accepted": ok_gate,
                             "of": len(voc)},
              "rows": [{"group": g, "query": q, "s1": placed(r)[1], "leader": placed(r)[0],
                        "ranked_first": r[0][1],
                        "lead3": placed(r)[2], "lead2": placed(r)[3],
                        **({"expected_leader": recorded[g[6:]],
                            "accepted": accepts(r, 0.26, 0.02, 3, cut)}
                           if g.startswith("vocab:") else {})} for g, q, r in rows]}
    return scores


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(repo_paths.FACTORY_ROOT))
    ap.add_argument("--scan", action="store_true", help="print the threshold plateau")
    ap.add_argument("--json", help="write the whole measurement to this path")
    args = ap.parse_args(argv)
    result = measure(args.root, scan=args.scan)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
