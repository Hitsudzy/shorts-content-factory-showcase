#!/usr/bin/env python3
"""Find the shot that best matches a phrase.

This is what makes "show the cottage when he says cottage" mechanical instead of
a matter of my eye. Anchor descriptions are encoded with the same CLIP model as
the shots and compared by cosine similarity.

Scores are relative, not absolute: CLIP will always rank something first, even
when nothing in the source depicts the phrase. `--min-score` is what turns a
weak best match into an honest "no footage for this anchor", which the caller
records rather than papering over.

Usage:
    match_anchors.py --index <shots.json> [--index <shots.json> ...]
      "a wooden lake house" ["another phrase" ...] [--top 3] [--min-score 0.22] [--json]

Multiple --index files share one model load (CF-0009): resolve_anchors.py used
to spawn this once per index, paying for a fresh CLIP load each time.

Title/end cards are handled per phrase rather than per run (CF-0035) - see
`card_phrase()` and `--cards` below.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caption_cache  # noqa: E402 - the caption-band cache gate, see main()
import shot_schema  # noqa: E402 - the moment mark relayed to the cut (CF-0106)
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting

MODEL = "openai/clip-vit-base-patch32"

# CF-0035. Cards used to be dropped from every candidate pool, full stop
# ("trailers are full of these and they are never what a line of narration is
# about"). That is true of nearly every anchor and wrong for the few that ask
# for a graphic by name: "a purple Example Max streaming logo on screen" resolved
# to a wood-panelled staircase (0.240) while `ZZ_urA56pJE` shot 3, "purple Example Network
# Max logo splash screen", sat outside the pool at 0.390. CLIP was never the
# problem there - it ranks these cards first by a wide margin once they are
# allowed in at all.
#
# So the pool stays exactly as it is for an ordinary anchor, and the phrase
# itself decides: a phrase that names on-screen graphics gets the best few
# cards put in front of its ordinary candidates, and keeps every ordinary
# candidate it has today behind them.
#
# Measured against all 107 real anchor phrases in the repo's finished batches:
# these words fire on 6 phrases, and every one of the 6 genuinely asks for a
# card (the two Example Max/Wren Hollow logo phrases of CF-0034, a German-language
# headline overlay, and three Rapid & Reckless title-card phrases). "sign" and
# "letters" were tried and deliberately left out - they fire only on two real
# phrases ("huge red letters on a wall", "a hand written sign next to a man in
# a suit") and both of those are ordinary photographic shots, not cards.
#
# CF-0427 re-measured it on the 821 distinct phrases of every batch on disk
# on 2026-10-02 (fixture `tests/fixtures/card_phrase_corpus.json`). Four
# words were firing only on photographic shots and are gone:
#   "caption(s)", "subtitle(s)" - a burned-in lower third or subtitle on a
#     live shot ("two women standing in a wood-paneled room, name captions
#     reading Nora Kingsley and Sandra Birch", "a close-up ... caption
#     'currently employed?'"): the picture is the people, not a card, and a
#     promoted card would have gone in front of it;
#   "on screen"/"onscreen" - an inset photo beside a studio host, a cinema
#     screen seen from the seats; its one real card phrase ("a purple Example Network
#     Max streaming logo on screen") fires on "logo" anyway;
#   "graphic(s)" - "a t-shirt with a monster graphic" (Takashi Yamazaki at a
#     press event); the one real card ("a German-language headline graphic
#     overlay") fires on "headline"/"overlay" anyway.
# "logo" stays, except as a "wall logo" - a podcast set's physical backdrop.
# "black screen"/"black frame" are new: "a black screen reading 'from Robert
# Eggers'", "solid black frame with small centered white text" are the plain
# text cards the old words missed.
CARD_PHRASE_WORDS = (
    "logo", "wordmark", "title", "title card", "end card", "card",
    "overlay", "headline", "front page",
    "splash", "splash screen", "black screen", "black frame",
    "credits", "chyron", "typography",
)

# A word that names graphics in general but, in this context, a physical
# object in the shot - the hit is withdrawn (CF-0427).
NOT_CARD_CONTEXTS = {
    "logo": re.compile(r"\bwall logo\b"),
}

# How many cards a card-shaped phrase may put in front of its ordinary
# candidates. Measured on the same 6 real phrases: the genuinely relevant
# cards number one to three in every case, and the fourth-ranked card is
# already about something else (a "MovieMaker - you are invited" title card
# for an Example Max logo phrase; a theme-park building mis-flagged as a card for
# the Rapid & Reckless title phrase). Capping here is also what keeps the
# ordinary candidate list intact behind them.
MAX_PROMOTED_CARDS = 3


def card_phrase(phrase):
    """The CARD_PHRASE_WORDS this phrase uses, i.e. why it counts as asking
    for on-screen graphics. Returns a list so a caller can record the reason
    rather than an opaque boolean.

    CF-0779: no phrase, no graphics asked for - `[]`. A graphic anchor
    (CF-0689, `shared/own_graphic.py` ANCHOR_KEY: `graphic_id` set, `phrase`
    null - ExampleTech's own graphics) asks the pool nothing; the Video
    Editor's resolve_anchors.py never hands one to the matcher, but a reader
    of anchors.json that does must not die on `None.lower()`."""
    if not isinstance(phrase, str) or not phrase.strip():
        return []
    low = phrase.lower()
    hits = [w for w in CARD_PHRASE_WORDS
            if re.search(rf"\b{re.escape(w)}\b", low)]
    return [w for w in hits
            if not (w in NOT_CARD_CONTEXTS and NOT_CARD_CONTEXTS[w].search(low))]


def rank_phrase(phrase, shots, sims, top, min_score, min_margin, cards):
    """Rank one phrase's candidates. Pure ranking - no torch, no I/O - so it
    can be tested against real similarity numbers without loading CLIP.

    `cards` is the mode from --cards:
      drop     - cards never enter the pool (the behaviour before CF-0035)
      include  - cards are ordinary candidates, ranked on score alone
      auto     - cards enter only for a phrase that names on-screen graphics,
                 and there they go in front of the ordinary candidates

    In `auto`, a phrase that is not card-shaped gets byte-for-byte what it got
    before CF-0035, and a card-shaped one keeps its full ordinary list too -
    the promoted cards are prepended, never substituted. That is the whole
    safety argument for this change: no anchor can lose a candidate it has
    today.
    """
    hits = card_phrase(phrase) if cards == "auto" else []
    card_shots = [i for i, s in enumerate(shots) if s.get("is_card")]
    plain_shots = [i for i, s in enumerate(shots) if not s.get("is_card")]

    promoted = []
    if cards == "include":
        ordinary = sorted(range(len(shots)), key=lambda k: -sims[k])
    else:
        ordinary = sorted(plain_shots, key=lambda k: -sims[k])
        if hits:
            # Only cards that clear --min-score are worth putting first: a
            # card below it is no better than the "nothing here depicts this"
            # case the threshold exists to report.
            promoted = [k for k in sorted(card_shots, key=lambda k: -sims[k])
                        if sims[k] >= min_score][:MAX_PROMOTED_CARDS]

    ranked = promoted + ordinary[:top]

    # A phrase that names something present picks it out: the best shot
    # stands clear of the field. A phrase describing an idea rather than a
    # picture - "the rivalry was never the point" - resembles everything
    # equally badly, and the distribution stays flat. That flatness is the
    # signal, and it is available without any vocabulary of abstract words.
    #
    # Measured over whichever pool this phrase was actually allowed to draw
    # from, and against its highest *score* rather than whatever promotion put
    # first - so the advisory keeps meaning "does anything here depict this",
    # and an ordinary phrase's margin is unchanged from before CF-0035.
    pool = promoted + ordinary

    # CF-0083: the pool is empty when every shot this index offered is a
    # card (plain_shots empty) and this phrase is not card-shaped (promoted
    # empty too) - e.g. a compliance-filtered index down to one is_card shot,
    # or any source whose only shot is a screenshot/press card. That is not a
    # low-score match, it is *no* candidate: report it as such instead of
    # dividing by zero, and let the caller (resolve_anchors.py) record an
    # explicit unresolved anchor rather than crash the whole matcher.
    if not pool:
        return {
            "phrase": phrase,
            "card_phrase": hits,
            "found": False,
            "discriminative": False,
            "margin": None,
            "advice": "no candidates in this index - every offered shot is a "
                      "card and this phrase is not card-shaped",
            "matches": [],
        }

    mean = sum(sims[k] for k in pool) / len(pool)
    best = max(pool, key=lambda k: sims[k])
    margin = sims[best] - mean
    discriminative = margin >= min_margin

    return {
        "phrase": phrase,
        "card_phrase": hits,
        # Advisory, not a verdict: the boundary between a tight real match
        # and a flat one is narrow (measured 0.046 against 0.057 on real
        # phrases), so a low margin warns the writer without discarding a
        # match that scores well.
        "found": sims[best] >= min_score,
        "discriminative": discriminative,
        "margin": round(margin, 4),
        "advice": (None if discriminative else
                   "this phrase does not single out any shot - either nothing here "
                   "depicts it, or it describes an idea rather than a frame"),
        "matches": [{
            "shot": shots[k]["index"],
            "start": shots[k]["start"],
            "end": shots[k]["end"],
            "score": round(sims[k], 4),
            "card": bool(shots[k].get("is_card")),
            # The caller merges several indexes' matches into one list and
            # re-sorts them; without this it would sort the promotion away.
            "promoted": k in promoted,
            # CF-0106: the describer's mark of the moment the description is
            # about, when it is not the head - resolve_anchors builds the
            # clip window around it instead of from `start`. None (the
            # common case) means "cut from the head, as always". Read through
            # the schema so a mark outside its shot never reaches a cut.
            "moment_at": shot_schema.moment_at(shots[k]),
        } for k in ranked],
    }


def match_one(shots, phrases, text, top, min_score, min_margin, cards):
    import torch
    mat = torch.tensor([s["embedding"] for s in shots])
    results = []
    for i, phrase in enumerate(phrases):
        sims = (mat @ text[i]).tolist()
        results.append(rank_phrase(phrase, shots, sims, top, min_score,
                                   min_margin, cards))
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", action="append", required=True,
                   help="shots.json to match against; repeatable")
    p.add_argument("phrases", nargs="+")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--min-score", type=float, default=0.22)
    p.add_argument("--min-margin", type=float, default=0.050,
                   help="how far the best shot must stand above the field; a flat "
                        "distribution means the phrase describes an idea, not a picture")
    p.add_argument("--cards", choices=("auto", "drop", "include"), default="auto",
                   help="how title/end cards are treated (CF-0035): auto - only a phrase "
                        "that names on-screen graphics gets them, and gets them first; "
                        "drop - never (the pre-CF-0035 behaviour); include - always, "
                        "ranked on score alone")
    p.add_argument("--json", action="store_true")
    p.add_argument("--allow-stale-captions", action="store_true",
                   help="rank against an index whose cached caption crops were "
                        "measured by other code (CF-0055). For reading an index "
                        "by hand only - resolve_anchors.py never passes it, and "
                        "must not be taught to: the refusal exists because that "
                        "number cuts real clips")
    args = p.parse_args()
    cards = args.cards

    # CF-0055. Every index a montage will draw on passes through here, before
    # a single clip has been cut, and this is the footage-indexer entry point
    # resolve_anchors.py already runs first and already exits on - so a pool
    # whose `crop_bottom_cached` was measured by other code stops the run in
    # its first seconds with a command to fix it, instead of producing a video
    # full of clips cropped by a rule this checkout no longer applies. Ranking
    # itself does not read the caption cache; the check is here because this
    # is where the whole list of indexes is known and nothing has been spent
    # yet, and it is the only place footage-indexer can put it until the same
    # call is made in resolve_anchors.py beside the lookups it protects.
    if not args.allow_stale_captions:
        caption_cache.require_fresh(args.index)

    # CF-0106: a hand-written moment mark outside its shot stops the run
    # here too - with the shot named, before CLIP is loaded, and before the
    # number can reach a cut as "start this clip at a timecode that is not
    # even inside the shot".
    indexes = {}
    for idx in args.index:
        data = json.load(open(idx))
        try:
            shot_schema.require_valid(data, idx)
        except ValueError as e:
            sys.exit(str(e))
        indexes[idx] = data

    import warnings
    warnings.filterwarnings("ignore")
    import torch
    from transformers import CLIPModel, CLIPTokenizer

    # CF-0107: the model load and the phrase encoding are `clip` children of
    # this script's event - the CPU the whole call costs, separate from I/O.
    with runlog.child("clip", argv=["clip", "load", MODEL]):
        model = CLIPModel.from_pretrained(MODEL).eval()
        tok = CLIPTokenizer.from_pretrained(MODEL)
    with torch.no_grad(), runlog.child("clip", argv=["clip", "text", str(len(args.phrases))]):
        inputs = tok(args.phrases, padding=True, return_tensors="pt")
        text = model.get_text_features(**inputs)
        text = text / text.norm(dim=-1, keepdim=True)

    results_by_index = {}
    for idx, data in indexes.items():
        shots = [s for s in data["shots"] if s.get("embedding")]
        if cards == "drop":
            shots = [s for s in shots if not s.get("is_card")]
        if not shots:
            sys.exit(f"index has no embeddings: {idx}")
        results_by_index[idx] = match_one(
            shots, args.phrases, text, args.top, args.min_score, args.min_margin, cards)

    if args.json:
        json.dump({"indexes": args.index, "min_score": args.min_score,
                   "min_margin": args.min_margin, "cards": cards,
                   # The caller caps the merged promotion across indexes, and
                   # reads the cap from here so the number lives in one place.
                   "max_promoted_cards": MAX_PROMOTED_CARDS,
                   "results_by_index": results_by_index},
                  sys.stdout, indent=2)
        print()
    else:
        for idx, results in results_by_index.items():
            print(f"== {idx} ==")
            for r in results:
                flag = "  " if r["found"] else ("FLAT" if not r["discriminative"] else "NO")
                # CF-0227: the CF-0083 empty-pool record has no matches and a
                # `margin` of None - this printout used to index [0] and format
                # None as a float on it, so the human mode crashed on exactly
                # the index the JSON mode reports cleanly. Say what happened
                # and move on; `advice` below carries the reason.
                if not r["matches"]:
                    print(f"NO   {r['phrase'][:42]:42s} -> no candidate in this index")
                    print(f"       {r['advice']}")
                    continue
                top = r["matches"][0]
                mark = "CARD " if top.get("card") else ""
                print(f"{flag:4s} {r['phrase'][:42]:42s} -> {mark}shot {top['shot']:2d} "
                      f"({top['start']:5.1f}-{top['end']:5.1f}s) "
                      f"score {top['score']:.3f} margin {r['margin']:.3f}")
                if r["card_phrase"]:
                    print(f"       card-shaped phrase ({', '.join(r['card_phrase'])}) - "
                          f"{sum(1 for m in r['matches'] if m['promoted'])} card(s) put first")
                if r["advice"]:
                    print(f"       {r['advice']}")


@runlog.script("footage-indexer", "match", name="match_anchors.py")
def cli():
    """CF-0107: start/done|failed around main() - a stale-caption or bad-mark
    refusal (SystemExit with a message) is recorded as `failed`."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
