#!/usr/bin/env python3
"""CF-0067: the reaction meme - plan the meme inserts for one video.

The contract is `inserts/meme.json` in the factory root and nothing else;
this file executes it and carries no paraphrase of it. In one line: the
writer names an *intent* on a *beat* of the commentary (`reactions[]` in
03-content-researcher.json), the editor chooses the *file* from the factory
library (shared/inserts/memes/index.json, or the channel's own bank named by
insert_layers.meme.bank - shared/inserts/memes-<channel>/, CF-0393) and applies the place rules, and
every request is answered in `meme_requested`/`meme_delivered` with one of
the closed outcomes - never with the least wrong picture.

What one request goes through, in order:

    layer_off        channels/<channel>.json insert_layers.meme.enabled is not true
    pattern_refused  patterns/<pattern_id>.json meme_layer.allowed is not true
    beat_missing_in_script
                     beat_text is not in the script's hook + commentary +
                     payoff either - the reaction is pinned to a sentence the
                     video never says, and no rung below can supply it
    beat_unmatched_in_alignment
                     the words are in the script and the forced alignment did
                     not give them back - ours to fix, so the answer carries
                     the evidence (CF-0235: one word used to answer both of
                     these, and the report could not tell them apart)
    beat_no_alignment
                     there is no words.json to look the beat up in at all
    no_block         M2: no block overlapping the beat's word span lasts
                     >= placement.min_block_seconds (3.0s) - a block already
                     carrying an insert (a proof, an earlier meme) is not a
                     candidate either - AND (CF-0811) no span of blocks from
                     the beat's first word can be built either (build_span();
                     the answer's `reason` says why, NO_BLOCK_REASONS)
    no_asset         every candidate failed the asset gate, the similarity
                     floor or the lead floor (M4), or the query could not be
                     embedded
    placed           block_index / asset_id / score / lead set

M1 decides *which* block among the candidates at the floor: a block the
resolver left without a picture (the plan's assetless rung - `asset.kind ==
"procedural"`, which is where resolve_anchors.py's unfilled blocks and a
--degrade-block drop both land) takes the meme first, then the block that
contains the beat's first word, then any other overlapping block at the
floor by its start. Never a block the beat does not overlap.

M4 (CF-0143) decides *whether there is an answer at all*, and it is the
thing that makes `no_asset` reachable: two floors, both measured on the
filled library, not one absolute constant.

    similarity floor   the candidate's own dot product, `selection.
                       min_similarity`
    lead floor         how far it stands above the field: its score minus the
                       score at rank `selection.lead_rank` places below it
                       (`selection.min_lead`)

Why both, and why the lead is measured to the *third* place rather than the
second: `scripts/measure_insert_lead.py` on the 101-entry library with 60
labelled queries. Neither floor alone separates a real answer from a wrong
one (the leader's score alone accepts 14 % of the wrong ones at 96 % recall,
the lead alone 16 %); together they accept 5 %. And the second place is the
wrong yardstick because the library deliberately holds near-duplicate pairs
- facepalm-man/facepalm-old-man, spirerunner-pointing/spirerunner-triple,
commons-tan-iceberg/wikipedia-iceberg - so a *correct* pick is routinely
0.005 above its own twin. The third place is the first rank that is not the
twin. A library shorter than `lead_rank` has no field to stand above, so the
missing places count as 0 and the similarity floor is the whole of M4 there.

The walk stops at the first candidate that fails either floor rather than
looking further down: below a level top the list is the field, and the next
picture down is the least wrong one this spec exists to refuse. That is the
`no_asset` the CF-0137 ladder needs - a rung that really does pass the block
on - and the same judgement CF-0138 will ask for before putting an insert in
a hole nobody asked for.

CF-0388: the tags go first
--------------------------
Before that walk a request's own words get a turn: `beat_text` (what is heard
where the meme lands) and the writer's `query` are matched against each
file's `tags`, and a file they name is tried first - most matched tags, then
CLIP's order - through the same asset gate. Its floor is not M4's but CLIP's
upper half for this query (tag_candidates()): a tag lifts a picture CLIP
thinks plausible, never one CLIP ranks among the wrong ones. It adds
candidates and takes nothing away - what it does not place goes to the walk
above unchanged, so no request that walk answered is refused because of a
tag, and no refusal of its own needs pricing. `matched_tags` on the answer,
the provenance record and the overlay says when a tag chose the file ([]
when CLIP did). The measurement behind the floor and the stop-words is at
TAG_FLOOR_RANK_FRACTION.

CF-0138: the insert that nobody asked for
-----------------------------------------
The walk above answers a *request*. After the requests are answered this
layer takes one more turn, over the blocks that have no picture at all -
rung 1 of the CF-0137 ladder, and the reason that ladder has a rung 1. There
is no `reactions[]` entry behind such an insert: the query is the block's
own `intent`, the storyboard's description of the frame the resolver failed
to find, and the same M4 floors decide whether the library answers it. Below
them there is no insert and the block goes on to rung 2 (the one emergency
shot repeat) - which is the ordinary outcome and the whole safeguard: a
picture that does not stand clear of the field is a random picture on a
wall, and CF-0123 refused exactly that.

The two are never counted as one. `origin` - `script_request` or
`hole_fill` - rides on every overlay and every provenance record, and
`plan["meme"]["hole_fill"]` says which blocks were holes, which were filled
and why the rest were not. A meme the writer asked for is a joke about the
meaning of a beat; a meme in a hole is footage that never arrived, and for
acceptance and for the Analyst (2.1) those are different facts. The requests
keep first claim on `placement.max_inserts_per_video`; the holes get what is
left, in block order.

The asset gate (composition.asset_gate in the spec) is not inspect_asset():
subject_present / roi_coverage / near_black / MIN_SHORT_SIDE are skipped by
name, because a meme is fitted whole on black and is a drawing as often as
a face. What it checks instead: similarity floor, distinct per video, file
present, a still or GIF (no audio track by format), the stretch it gets
contained into the insert box (CF-0394's box above the caption band, not the
frame) <= inserts/meme.json `asset_floor.max_upscale_factor` (CF-0392: that
factor is the whole size gate - the file's short side is not measured), and
M3's negative half - text recognised on the asset must not restate the
words spoken over the block.

M3 (`meaning_rule`) is "not verified" and is reported as such: the
negative half here is mechanical (Vision accurate-mode text on the asset
against words.json over the block span); the positive half - that the
reaction adds something the narration leaves unsaid - is the writer's and
is only answerable after publication. Nothing here measures it.

Degradation: a meme is an overlay on a block that is built exactly as it
would be without one. `apply_to_plan()` adds `insert` to the placed block
and touches nothing else - not the block's asset, length, rhythm fields or
captions - and a request that was not placed leaves every block identical.

Factory root: FACTORY_ROOT when set (the convention underlay.py set for
CF-0014, which is how a test points the layer at a temp library), else the
checkout found by walking up from this repo until shared/inserts/inserts_lib.py
is there - which works both from agents/video-editor and from a worktree
under it.

Test seam: MEME_QUERY_VECTORS=<json {query: [512 floats]}> (or
--query-vectors) replaces the CLIP text encoder, so the suite runs without
torch. Without it the query is embedded by the root's scripts/index_inserts.py
embed_texts() - in-process when torch is importable here, else through the
footage-indexer venv beside the main checkout of this repo.

Usage:
    meme_layer.py <plan.json> --script <03-content-researcher.json> --script-id <id>
        [--channel <id|path.json>] [--pattern <id>] [--root <factory root>]
        [--query-vectors <json>] [--write]
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

import repo_paths  # CF-0125: the sibling agent, beside the main checkout
import rhythm  # CF-0138: has_picture() - one definition of "this block shows
               # something", so the hole this layer fills and the hole the
               # CF-0137 gate refuses over are the same set of blocks.
import meme_captions  # CF-0392: insert_box() - the box a meme is drawn into
# The meme upscale ceiling is inserts/meme.json's
# `asset_floor.max_upscale_factor` (max_upscale below) and there is no
# short-side floor; common.py's dead CF-0067 MEME_* constants went in CF-0406,
# once both pool caches were keyed on reached code rather than whole files.
from common import (AGENT_ROOT, SIBLING_SCRIPT_TIMEOUT_SECONDS,
                    image_size, load_words, media_duration,
                    # CF-0132: the three children this layer starts - the
                    # indexer's CLIP, an ffprobe, a GIF transcode - under the
                    # helpers' ceilings.
                    ffmpeg, run_tool, stream_kinds)
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from _channel_data import channel_data, ChannelDataError  # noqa: E402 - CF-0630 the channel's lists

LAYER = "meme"
LIBRARY_KIND = "meme"
FACTORY_ROOT_ENV = "FACTORY_ROOT"
QUERY_VECTORS_ENV = "MEME_QUERY_VECTORS"
SPEC_REL = ("inserts", "meme.json")

OUTCOME_PLACED = "placed"
OUTCOME_LAYER_OFF = "layer_off"
OUTCOME_PATTERN_REFUSED = "pattern_refused"
# CF-0235: `beat_not_found` was one word for two unrelated faults here too -
# "the video never says this sentence" (the writer's, unfixable below) and
# "the video says it and our aligner lost it" (ours, and measurable). The
# three codes that replace it are beat_failure()'s, the ones CF-0193 gave the
# proof layer, because two layers answering one question in two vocabularies
# is the CF-0159 defect. This constant is kept for *reading* plans and batch
# records written before 2026-09-15; nothing writes it.
OUTCOME_BEAT_NOT_FOUND = "beat_not_found"
LEGACY_OUTCOMES = (OUTCOME_BEAT_NOT_FOUND,)
OUTCOME_NO_BLOCK = "no_block"
OUTCOME_NO_ASSET = "no_asset"
# OUTCOMES is assembled below, where the three beat codes are defined.

# Asset-gate skip reasons (composition.asset_gate.added, plus the two
# mechanical ones the walk needs). Closed list, same reasoning as the outcomes.
# CF-0236: the two selection floors are written too - on the one candidate
# each refusal stops the walk at, with its measured score and lead. Before
# 2026-09-26 the walk broke there without a record, and these two names
# existed in code and never in data.
SKIP_SIMILARITY = "similarity_floor"
SKIP_LEAD = "lead_floor"
SKIP_DISTINCT = "distinct_per_video"
SKIP_FILE_MISSING = "file_present"
SKIP_AUDIO = "no_audio_track"
# CF-0392: `short_side_floor` is kept for *reading* records written before
# 2026-09-26; nothing writes it - the stretch below is the only size gate.
SKIP_SHORT_SIDE = "short_side_floor"
SKIP_UPSCALE = "max_upscale_factor"
SKIP_MEANING = "meaning_negative_half"
SKIP_UNREADABLE = "unreadable"
# CF-0534: a still that still carries a template's blank caption panel - a
# band of one tone across the full width at the top or the bottom, at least
# inserts/meme.json `asset_floor.blank_band.min_share` of the height. Fitted
# `contain`, the panel lands in the frame as a white (or black) stripe over
# the picture (surprised-pikachu, WNL 0701Z). The desk cuts such a panel off
# on the way in (scripts/meme_desk.py add-image / trim-blank); this gate is
# for a file that got past the desk.
SKIP_BLANK_BAND = "blank_band"

# CF-0138: why this insert is on this block at all. Two different things, and
# the decision (CF-0123, grill 2026-09-07) is that they must never be counted
# as one: a meme the writer asked for is a joke about the meaning of a beat,
# and a meme in a hole nobody asked about is a picture standing in for footage
# that never arrived. They are accepted differently and the Analyst (2.1) has
# to be able to tell one from the other in `videos[].inserts[]` without
# re-deriving it, so every record and every overlay this layer writes carries
# `origin`. The pair is written the way CF-0137 wrote `emergency_reuse` and
# CF-0136 `picture`: a field on the record, not a second mechanism.
ORIGIN_REQUEST = "script_request"
ORIGIN_HOLE = "hole_fill"
ORIGINS = (ORIGIN_REQUEST, ORIGIN_HOLE)

# The fraction of the beat's words that have to line up with words.json for
# the beat to count as found. The narration is restructured for prosody
# before TTS (numbers spelled out, sentences cut), so an exact match is the
# exception; 0.6 of the words in the right order and position is a beat, and
# anything under it is a beat failure - beat_failure() below says which of
# the three, and on the evidence rather than on a guess.
BEAT_MATCH_MIN_RATIO = 0.6

# CF-0193's second pass - see _drift_match(). The floor above is reused as-is
# (one floor for "is this the beat", measured or not, beats two); these three
# say what counts as evidence for it when the two token lists are not the same
# length.
#
#   BEAT_MATCH_MIN_RUN      2    a single shared word is not evidence: `the`
#                                matches everywhere in a narration. Two in a
#                                row is the shortest run that means anything,
#                                and the corpus's four rescued beats match in
#                                runs of 10 to 31.
#   BEAT_MATCH_MAX_STRETCH  1.5  the located span may be half again as long as
#                                the beat and no longer, so function words
#                                scattered over the whole video cannot add up
#                                to one. The worst real drift measured is
#                                58 beat words over a 61-word span (1.05).
#   BEAT_EVIDENCE_CHARS     240  how much of the searched and the nearest text
#                                a record carries. Long enough to recognise
#                                the sentence, short enough to sit in a plan.
BEAT_MATCH_MIN_RUN = 2
BEAT_MATCH_MAX_STRETCH = 1.5
BEAT_EVIDENCE_CHARS = 240

# Which pass found the beat. On the record, because a beat rescued out of a
# length mismatch and a beat that lined up exactly are not the same news.
MATCH_WINDOW = "window"
MATCH_DRIFT = "drift"

# M4's two floors (CF-0143). The spec is the contract and these are only the
# values used when `inserts/meme.json` does not carry the key yet: the numbers
# come out of scripts/measure_insert_lead.py on the library CF-0115 filled
# (101 entries, 60 labelled queries), and the module must not be more
# permissive than the measurement while the spec is still being updated.
#
#   MIN_SIMILARITY   0.26  - leaders of a real answer measured 0.256-0.353,
#                            leaders of a wrong one 0.180-0.279; 0.26 is the
#                            middle of the plateau where recall stays 0.96
#   MIN_LEAD         0.02  - at LEAD_RANK 3, the plateau runs 0.018-0.024
#   LEAD_RANK        3     - the second place is a near-duplicate too often
#
# CF-0402 (2026-10-04): re-measured on the 28-entry library these give
# 0.78 / 0.045 and are no longer a plateau's middle - see the script's
# docstring; the spec's numbers change only with the user's sign-off.
#
# `inserts/meme.json` now carries these three numbers itself (CF-0143; before
# it, `selection.min_similarity` read 0.20 - a number the spec itself called
# "derived from the model's usual range, not measured on this library"). The
# larger-of-the-two rule below stays as a guard, not as a live correction: if
# the contract is ever loosened past the measurement again, the measured floor
# is the one applied and plan_memes() says so in its notes.
MIN_SIMILARITY_MEASURED = 0.26
MIN_LEAD_DEFAULT = 0.02
LEAD_RANK_DEFAULT = 3
# M3 negative half: a run of this many asset words spoken in order over the
# block is the asset restating the narration.
RESTATE_RUN_WORDS = 3

_TOKEN_RE = re.compile(r"[^\w']+", re.UNICODE)


# --------------------------------------------------------------------------
# root, spec, library
# --------------------------------------------------------------------------

def factory_root():
    override = os.environ.get(FACTORY_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    for cand in [AGENT_ROOT, *AGENT_ROOT.parents]:
        if (cand / "shared" / "inserts" / "inserts_lib.py").exists():
            return cand
    return repo_paths.FACTORY_ROOT


def _lib(root):
    """inserts_lib from the factory root (the CF-0114 library module)."""
    path = str(Path(root) / "shared" / "inserts")
    if path not in sys.path:
        sys.path.insert(0, path)
    import inserts_lib
    return inserts_lib


def load_spec(root):
    return json.loads((Path(root).joinpath(*SPEC_REL)).read_text())


def load_channel(channel, root):
    """channels/<id>.json under the root, or a path to a .json as given.
    None when there is no such file - which reads as the layer being off."""
    if not channel:
        return None
    path = Path(channel) if str(channel).endswith(".json") else Path(root) / "channels" / f"{channel}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_pattern(pattern_id, root):
    if not pattern_id:
        return None
    try:
        return json.loads((Path(root) / "patterns" / f"{pattern_id}.json").read_text())
    except (OSError, ValueError):
        return None


def layer_enabled(channel_cfg):
    """insert_layers.meme.enabled is exactly true - the same reading
    underlay.layer_switch() gives its own switch."""
    layers = (channel_cfg or {}).get("insert_layers") or {}
    switch = layers.get(LAYER) if isinstance(layers, dict) else None
    return isinstance(switch, dict) and switch.get("enabled") is True


def pattern_allows(pattern_cfg):
    """meme_layer.allowed is exactly true. A pattern file that is missing or
    silent refuses: the pattern has to say it tolerates the interruption."""
    block = (pattern_cfg or {}).get("meme_layer")
    return isinstance(block, dict) and block.get("allowed") is True


def library_folder(root, channel_cfg=None):
    """(bank, folder) the channel's memes come from (CF-0393): its own bank
    when `insert_layers.meme.bank` names one, the default
    shared/inserts/memes/ when it names none. A named bank that is not on
    disk raises inserts_lib.MemeBankError - never a fallback to the default
    (cinema) folder."""
    lib = _lib(root)
    return lib.meme_bank_folder(channel_cfg, Path(root) / "shared" / "inserts")


def load_library(root, channel_cfg=None):
    lib = _lib(root)
    bank, _ = library_folder(root, channel_cfg)
    return lib.load_index(LIBRARY_KIND, Path(root) / "shared" / "inserts", bank)


def channel_of(channel_cfg):
    """The channel a layer plans for: `channel_id` of the config it was given
    (`--channel` / `load_channel`). None when the config names none - there is
    no default channel (CF-0213), and `load_blacklist` refuses None."""
    cid = (channel_cfg or {}).get("channel_id") if isinstance(channel_cfg, dict) else None
    return cid.strip() if isinstance(cid, str) and cid.strip() else None


def load_blacklist(root, channel):
    """The rights-holder list of `channel` (`channels/<id>/rights-holder-
    blacklist.json` under `root`, CF-0561/CF-0630), read through the root's
    `shared/channel_data.py` (`scripts/_channel_data.py`) - the sound and
    proof layers import it from here. The meme layer itself never calls it
    since CF-0389 (inserts/POLICY.md, amendment 2026-09-24).

    The list is the channel's: a former id resolves to the same channel, and
    no other channel's list is ever substituted. When the channel has none -
    no channel named, a channel the root does not know, no file, a file that
    does not parse - this raises `ChannelDataError` and the caller decides
    what that means for its layer: the sound layer takes no sound (a file
    whose rights holder cannot be checked is not placed, and the plan's notes
    and `sound_delivered` say why), the proof layer records the check as not
    applied (it never gates on the list)."""
    return channel_data.rights_holders(channel, root)


# --------------------------------------------------------------------------
# the query vector
# --------------------------------------------------------------------------

def query_text(reaction, spec):
    """The text that is embedded: the writer's query when given, else the
    intent's default_query. Recorded verbatim in meme_requested."""
    q = reaction.get("query")
    if isinstance(q, str) and q.strip():
        return q.strip()
    vocab = spec["selection"]["intent_vocabulary"]
    entry = vocab.get(reaction.get("intent")) or {}
    return entry.get("default_query") or str(reaction.get("intent") or "")


def _stub_vectors(path=None):
    path = path or os.environ.get(QUERY_VECTORS_ENV)
    if not path:
        return None
    return json.loads(Path(path).read_text())


def make_embedder(root, query_vectors_path=None):
    """A callable text -> 512-d L2-normalised vector, or one that raises
    RuntimeError with the reason (reported in the plan's notes)."""
    stub = _stub_vectors(query_vectors_path)
    if stub is not None:
        def from_stub(text):
            if text not in stub:
                raise RuntimeError(f"no stub vector for query {text!r}")
            return stub[text]
        return from_stub

    scripts_dir = str(Path(root) / "scripts")

    def embed(text):
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        try:
            import index_inserts
            return index_inserts.embed_texts([text])[0]
        except ImportError:
            pass
        py = Path(repo_paths.INDEXER_PY)
        if not py.exists():
            raise RuntimeError("no CLIP available: torch/transformers not importable "
                               f"here and {py} does not exist")
        code = ("import json,sys; sys.path.insert(0, sys.argv[1]); import index_inserts; "
                "print(json.dumps(index_inserts.embed_texts([sys.argv[2]])[0]))")
        # SIBLING_SCRIPT_TIMEOUT_SECONDS, replacing a bare `timeout=600`:
        # the same work resolve_anchors.match() runs match_anchors.py for -
        # the footage-indexer's CLIP, loaded from scratch in its own
        # interpreter - so it is named by the same class rather than by two
        # different numbers that can drift. Looser than the 600 it replaces,
        # which was a literal with no measurement behind it, and in exchange a
        # wedged embed now raises ToolTimeout with CF-0077's sentence instead
        # of a bare TimeoutExpired traceback. The honest number for both wants
        # a measured CLIP load - see the task's `## Полный прогон`.
        out = run_tool([str(py), "-c", code, scripts_dir, text], tool="clip",
                       target=text, timeout=SIBLING_SCRIPT_TIMEOUT_SECONDS)
        if out.returncode != 0:
            raise RuntimeError("CLIP text embedding failed: " + out.stderr.strip()[-400:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    return embed


# --------------------------------------------------------------------------
# the beat in words.json
# --------------------------------------------------------------------------

def norm_tokens(text):
    return [t for t in (_TOKEN_RE.split((text or "").lower().replace("’", "'"))) if t.strip("'_")]


def alignment_tokens(words):
    """CF-0193: `words.json` flattened to comparable tokens, with the map back.

    Returns `(tokens, owner)`, `owner[k]` being the index in `words` the k-th
    token came from. Two things this does that the old one-token-per-word list
    did not, and the CF-0193 measurement says both of them were half the
    defect:

    * a word that normalises to **nothing** contributes nothing. An em dash
      spoken as a pause arrives in the alignment as its own entry; the old
      list kept it as an empty string, which matched no beat token and yet
      **occupied a position**, so everything after it was off by one. Three of
      the four unlocatable beats in the corpus were exactly this.
    * a word that normalises to **several** tokens contributes all of them.
      The old list took `t[0]`, so `twenty-seven` was `twenty` and
      `most-watched` was `most`: the beat's `seven` and `watched` were then
      "absent from the alignment", having been dropped by us.

    Two tokens of one word both map back to that word, so a span that starts
    or ends inside a compound still names a real entry with a real timing.
    """
    toks, owner = [], []
    for i, w in enumerate(words or []):
        for t in norm_tokens((w or {}).get("word", "")):
            toks.append(t)
            owner.append(i)
    return toks, owner


def _expected_position(beat_text, script, expected):
    commentary = (script or {}).get("commentary") or ""
    at = commentary.find(beat_text or "")
    if expected is None and at >= 0:
        expected = len(norm_tokens((script or {}).get("hook") or "")) + \
            len(norm_tokens(commentary[:at]))
    return expected


def _window_match(beat, wt, expected):
    """Pass 1, CF-0064's rule unchanged: the best equal-length window."""
    n = len(beat)
    best = None
    for s in range(0, max(0, len(wt) - n + 1)):
        matches = sum(1 for k in range(n) if beat[k] == wt[s + k])
        ratio = matches / n
        if ratio < BEAT_MATCH_MIN_RATIO:
            continue
        dist = abs(s - expected) if expected is not None else 0
        key = (-ratio, dist, s)
        if best is None or key < best[0]:
            best = (key, s, ratio)
    return None if best is None else (best[1], best[1] + n - 1, best[2])


def _drift_match(beat, wt):
    """Pass 2, CF-0193: the same words, a different number of them.

    Pass 1 compares position by position, so a single word inserted into or
    dropped from the alignment shifts every comparison after it and the ratio
    collapses - `clooney-venice-lion` says `THR` where the narration says
    `the Hollywood Reporter`, one token against three, and 55 of the beat's
    58 words line up in order while the window scores 0.43.

    So: the beat's words in order, allowing the gaps, and the same 0.6 floor
    applied to how much of the beat is covered by runs of at least
    BEAT_MATCH_MIN_RUN words. Runs shorter than that are not evidence - a lone
    `the` matches everywhere. BEAT_MATCH_MAX_STRETCH bounds the answer to a
    span of sane length, so scattered function words spread over the whole
    narration cannot add up to a beat.
    """
    n = len(beat)
    sm = difflib.SequenceMatcher(None, beat, wt, autojunk=False)
    runs = [b for b in sm.get_matching_blocks() if b.size >= BEAT_MATCH_MIN_RUN]
    if not runs:
        return None
    coverage = sum(b.size for b in runs) / n
    if coverage < BEAT_MATCH_MIN_RATIO:
        return None
    lo, hi = runs[0].b, runs[-1].b + runs[-1].size - 1
    if hi - lo + 1 > n * BEAT_MATCH_MAX_STRETCH:
        return None
    return lo, hi, coverage


def match_beat(beat_text, script, words, expected=None):
    """CF-0193: locate_beat() with its working shown, or None.

    `{first_word_index, last_word_index, how, coverage}` - `how` being
    MATCH_WINDOW or MATCH_DRIFT, so a plan can say which pass answered and a
    reader can tell a clean hit from one rescued out of a length mismatch.
    locate_beat() is this function's span-or-None face and every old caller
    keeps it.
    """
    beat = norm_tokens(beat_text)
    wt, owner = alignment_tokens(words)
    if not beat or not wt:
        return None
    expected = _expected_position(beat_text, script, expected)
    hit = _window_match(beat, wt, expected)
    how = MATCH_WINDOW
    if hit is None:
        hit = _drift_match(beat, wt)
        how = MATCH_DRIFT
    if hit is None:
        return None
    lo, hi, coverage = hit
    return {"first_word_index": owner[lo], "last_word_index": owner[hi],
            "how": how, "coverage": round(coverage, 3)}


def locate_beat(beat_text, script, words, expected=None):
    """(first_word_index, last_word_index) in words.json for a reaction's
    beat_text, or None.

    The script's hook + commentary + payoff were aligned in that order, so
    the beat's expected position is the word count of the hook plus the
    words of the commentary before the substring. The alignment is then
    searched for the window that matches the beat's words best; the expected
    position only breaks ties, because the narration was restructured for
    prosody before TTS and the counts drift.

    `expected` overrides that guess for a caller whose beat is not in the
    commentary (CF-0140: a `visual_anchors` beat may sit in the hook or the
    payoff, and a payoff is *required* to echo the hook's wording - so the
    tie between two identical windows has to be broken by the section the
    words were actually taken from, not by whichever comes first).

    CF-0193 added a second pass behind that one - see match_beat() - because
    the equal-length window cannot survive the alignment being one word longer
    than the beat. The first pass and its answers are untouched.
    """
    found = match_beat(beat_text, script, words, expected)
    if found is None:
        return None
    return found["first_word_index"], found["last_word_index"]


# --------------------------------------------------------------------------
# CF-0193: why a beat was not located - a diagnosis, not one word for two
# different faults.
# --------------------------------------------------------------------------

BEAT_MISSING_IN_SCRIPT = "beat_missing_in_script"
BEAT_UNMATCHED_IN_ALIGNMENT = "beat_unmatched_in_alignment"
BEAT_NO_ALIGNMENT = "beat_no_alignment"
BEAT_FAILURE_CODES = (BEAT_MISSING_IN_SCRIPT, BEAT_UNMATCHED_IN_ALIGNMENT, BEAT_NO_ALIGNMENT)

# The closed list `inserts/meme.json` publishes, in its order: the three beat
# codes stand where `beat_not_found` stood, and it trails them as the legacy
# value old records still carry (CF-0235).
OUTCOMES = ((OUTCOME_PLACED, OUTCOME_LAYER_OFF, OUTCOME_PATTERN_REFUSED)
            + BEAT_FAILURE_CODES + LEGACY_OUTCOMES
            + (OUTCOME_NO_BLOCK, OUTCOME_NO_ASSET))


def narration_text(script):
    """The three spoken sections, in the order they were aligned - which is
    also the exact text the voice reads (CF-0261).

    THE SEPARATOR IS PART OF THE MEASUREMENT. A single space makes this one
    line, and Kokoro synthesizes one chunk per line: every extra line pays its
    own phrase-final lengthening and its own padding. Joining the three
    sections with a blank line instead - a perfectly legitimate prosody
    decision, a breath between hook, commentary and payoff - slows the reading
    by about a quarter on the same words, and that is not a nuance of taste,
    it is the number every length in the pipeline hangs on. Measured on
    wren-hollow-christmas, 181 words, one voice, one speed, only the line
    breaks moved: 44.50 s on one line (4.07 w/s) against 58.92 s as five
    paragraphs (3.07 w/s).

    So `channels/<id>.json -> narration_budget.words_per_second` is a
    measurement of this voice AT THIS LAYOUT. Changing the separator
    INVALIDATES it exactly as changing the voice does, and silently: the
    scripts keep passing the word budget, the videos quietly change length,
    and it shows up as a DoD violation at the viewing (CF-0261: two batches,
    estimated at 50.3 s and 49.3 s of voice, came out at 38.55 s and 38.40 s,
    both finished videos under the 45 s floor). Whoever changes it re-measures
    the rate on a real batch - `scripts/measure_speaking_rate.py <batch-dir>
    --channel <id>` - and writes the new median into the channel config with
    its provenance, in the same commit.
    """
    s = script or {}
    return " ".join(x for x in (s.get("hook"), s.get("commentary"), s.get("payoff")) if x)


# The name this join carried while it was only the meme layer's haystack.
script_text = narration_text


def _coverage(beat, hay):
    if not beat or not hay:
        return 0.0
    sm = difflib.SequenceMatcher(None, beat, hay, autojunk=False)
    runs = [b for b in sm.get_matching_blocks() if b.size >= BEAT_MATCH_MIN_RUN]
    return sum(b.size for b in runs) / len(beat)


def beat_failure(beat_text, script, words):
    """Why match_beat() came back None, with the evidence to check it by.

    Two codes where there was one, because `beat_not_found` answered two
    unrelated questions with one word (CF-0193):

      beat_missing_in_script       the beat's words are not in the script
                                   either. Nobody downstream can fix that -
                                   the check names a sentence the video never
                                   says, and the ladder refuses over it.
      beat_unmatched_in_alignment  the words are in the script and the forced
                                   alignment did not give them back. A fault
                                   of ours, and the whole reason the record
                                   carries `searched` and `nearest`: a
                                   diagnosis nobody can check against the
                                   alignment is not a diagnosis.
      beat_no_alignment            there is no words.json to look in at all.

    Returns None when the beat *is* locatable - so a caller can use this as
    the answer to "and if not, why not" without asking twice.
    """
    beat = norm_tokens(beat_text)
    wt, _owner = alignment_tokens(words)
    if match_beat(beat_text, script, words) is not None:
        return None
    in_script = _coverage(beat, norm_tokens(narration_text(script)))
    if not beat:
        code = BEAT_MISSING_IN_SCRIPT
    elif not wt:
        code = BEAT_NO_ALIGNMENT
    elif in_script >= BEAT_MATCH_MIN_RATIO:
        code = BEAT_UNMATCHED_IN_ALIGNMENT
    else:
        code = BEAT_MISSING_IN_SCRIPT
    return {"code": code,
            "searched": (beat_text or "")[:BEAT_EVIDENCE_CHARS],
            "beat_words": len(beat),
            "alignment_words": len(wt),
            "in_script_coverage": round(in_script, 3),
            "alignment_coverage": round(_coverage(beat, wt), 3),
            "nearest": _nearest_fragment(beat, wt, _owner)}


def _nearest_fragment(beat, wt, owner):
    """The stretch of the alignment that came closest, as it was heard.

    Without it the record says only that something did not match something,
    and the next person has to rebuild the token lists by hand to find out
    whether the diagnosis is true.
    """
    n = len(beat)
    if not n or not wt:
        return None
    best = None
    for s in range(0, max(1, len(wt) - n + 1)):
        window = wt[s:s + n]
        m = sum(1 for k in range(len(window)) if beat[k] == window[k])
        if best is None or m > best[0]:
            best = (m, s)
    m, s = best
    return {"word_index": owner[s] if s < len(owner) else None,
            "ratio": round(m / n, 3),
            "text": " ".join(wt[s:s + n])[:BEAT_EVIDENCE_CHARS]}


# --------------------------------------------------------------------------
# the block (M1 / M2)
# --------------------------------------------------------------------------

def is_unresolved_block(block, index, plan_degraded=None):
    """A block the resolver left without a picture: nothing on screen, or
    recorded in degraded_blocks as unfilled. That is where an unresolved
    anchor lands in the plan (CF-0085), and M1 puts the meme there first.

    CF-0138 widened the first half from `asset.kind == "procedural"` to
    `not rhythm.has_picture()`: the same predicate the CF-0137 gate refuses
    over, so that a block this layer declines to fill is exactly a block that
    gate will refuse the plan for. `procedural` is the usual shape of the
    assetless rung, but a block with no `asset` key at all is the same hole
    to a viewer, and two definitions of one hole is one too many.
    """
    if not rhythm.has_picture(block):
        return True
    for d in plan_degraded or []:
        if d.get("index") == index and d.get("from") == "unfilled":
            return True
    return False


def candidate_blocks(blocks, beat_start, beat_end, min_seconds, taken, plan_degraded=None):
    """Blocks overlapping the beat's span, at the M2 floor, not already
    carrying an insert, in M1 order: unresolved first, then the block holding
    the beat's first word, then the rest by start. Returns [(index, reason)]."""
    overlapping = []
    for i, b in enumerate(blocks):
        if i in taken or b.get("insert"):
            continue
        if b["start"] < beat_end and b["end"] > beat_start:
            overlapping.append(i)
    at_floor = [i for i in overlapping
                if round(blocks[i]["end"] - blocks[i]["start"], 3) >= min_seconds]
    unresolved = [i for i in at_floor if is_unresolved_block(blocks[i], i, plan_degraded)]
    first_word = [i for i in at_floor
                  if blocks[i]["start"] <= beat_start < blocks[i]["end"] and i not in unresolved]
    rest = [i for i in at_floor if i not in unresolved and i not in first_word]
    return ([(i, "unresolved anchor (M1)") for i in unresolved]
            + [(i, "block containing the beat's first word") for i in first_word]
            + [(i, "overlapping block at the floor") for i in rest])


# --------------------------------------------------------------------------
# CF-0811 (part b): the block a requested meme is given when none is there
# --------------------------------------------------------------------------
#
# Before this, a request whose beat no block at the M2 floor overlapped was
# answered `no_block` - and on a pattern whose hold ceiling is under the floor
# (list: key_frame_hold_seconds 2.5 against min_block_seconds 3.0) that was
# every request, by construction. About half the memes ever asked for were
# lost there. The writer now guarantees (content-researcher CF-0811 part a)
# that from the beat's first word to the end of the commentary there are at
# least ceil(min_block_seconds x the script's words-per-second) words; this is
# the editor's half of that promise.
#
# The meme gets a *span*: from the beat's first word, over the consecutive
# blocks it needs, to the first block boundary at least `min_block_seconds`
# after that word. The blocks themselves are not cut or merged - every index
# the plan already wrote (degraded_blocks, the proof, rhythm, punches) stays
# true - the meme is laid over each of them as one insert (`insert.span` is
# the same on every block of it, and the renderer draws them as one picture:
# no dissolve inside it, one motion over its whole time - AssetLayer.jsx /
# Video.jsx). The first block keeps its own picture up to the beat's word
# (`insert.start_s`), unless that head is shorter than the shortest block the
# rhythm makes (rhythm.MIN_ORDERED_BLOCK_SECONDS) - a flash of a shot before
# the meme - in which case the meme takes the head too. The pattern's hold
# ceiling (`key_frame_hold_seconds`) is not asked: it was asked of the blocks
# above, and this span is one picture by design.
#
# It stays inside the commentary - it never starts in the hook and never
# reaches the payoff's first word - and never covers a block that is pinned:
# one already carrying an insert (a proof, an earlier meme) or drawn rather
# than shot (a card, an own graphic, the split opening). When that makes
# `min_block_seconds` impossible the answer stays `no_block`, with `reason`
# saying which of these it was - never a bare `no_block` again.

NO_BLOCK_MAX_INSERTS = "max_inserts_reached"
NO_BLOCK_NOT_AT_BEAT = "no_block_at_beat"
NO_BLOCK_OUTSIDE_COMMENTARY = "beat_outside_commentary"
NO_BLOCK_NO_ROOM = "no_room_before_payoff"
NO_BLOCK_PINNED = "pinned_block_in_span"
NO_BLOCK_REASONS = (NO_BLOCK_MAX_INSERTS, NO_BLOCK_NOT_AT_BEAT, NO_BLOCK_OUTSIDE_COMMENTARY,
                    NO_BLOCK_NO_ROOM, NO_BLOCK_PINNED)

# A block whose picture is drawn by the factory, not shot: AssetLayer.jsx
# returns for these before it reaches InsertLayer, and each carries something
# the viewer has to read (a card's text, a graphic's facts, the split's two
# sides). A meme span never covers one.
PINNED_ASSET_KINDS = ("card", "own_graphic", "split")
SPAN_PLACED_BY = "span built from the beat's first word (CF-0811)"
PLACEMENT_WHY_SPAN = "spans_blocks"
# How close to the payoff/hook a boundary has to be to count as on it.
_SPAN_EPS = 1e-3


def _token_time(words, index, edge):
    """`words[owner].start|end` for the alignment token at `index`, clamped."""
    wt, owner = alignment_tokens(words)
    if not owner:
        return None
    k = owner[max(0, min(index, len(owner) - 1))]
    return float(words[k][edge])


def commentary_bounds(script, words):
    """`(start_s, end_s)` of the commentary as it was heard: from the end of
    the hook's last word to the start of the payoff's first word.

    Each edge is the section's own words located in the alignment (the same
    match the beats are found by, with the section's own expected position),
    and only when that fails the word count of the sections before it - the
    narration is restructured for prosody before TTS, so the count is the
    fallback and not the rule. No hook: the video's first word; no payoff: the
    last word's end."""
    s = script or {}
    if not words:
        return None, None
    hook, commentary, payoff = s.get("hook") or "", s.get("commentary") or "", s.get("payoff") or ""
    n_hook, n_com = len(norm_tokens(hook)), len(norm_tokens(commentary))
    if norm_tokens(hook):
        hit = match_beat(hook, s, words, expected=0)
        start = (float(words[hit["last_word_index"]]["end"]) if hit
                 else _token_time(words, n_hook, "start"))
    else:
        start = float(words[0]["start"])
    if norm_tokens(payoff):
        hit = match_beat(payoff, s, words, expected=n_hook + n_com)
        if hit and float(words[hit["first_word_index"]]["start"]) >= start:
            end = float(words[hit["first_word_index"]]["start"])
        else:
            wt, _owner = alignment_tokens(words)
            end = (_token_time(words, n_hook + n_com, "start")
                   if n_hook + n_com < len(wt) else float(words[-1]["end"]))
    else:
        end = float(words[-1]["end"])
    return start, end


def pinned_reason(block, index, taken):
    """Why this block may not be covered by a meme span, or None."""
    if index in taken or block.get("insert"):
        kind = (block.get("insert") or {}).get("kind") or "insert"
        return f"block {index} already carries a {kind}"
    kind = (block.get("asset") or {}).get("kind")
    if kind in PINNED_ASSET_KINDS:
        return f"block {index} is a {kind}"
    return None


def build_span(blocks, beat_start, min_seconds, taken, bounds, max_seconds=None):
    """CF-0811: the span a requested meme is laid over when no single block
    at the floor overlaps its beat - see the section comment above.

    Returns `{"ok": True, "blocks": [i..k], "start_s", "end_s", "beat_start_s",
    "seconds"}` or `{"ok": False, "reason": NO_BLOCK_*, "note"}`. Pure."""
    c_start, c_end = bounds
    beat_start = float(beat_start)

    def refuse(reason, note):
        return {"ok": False, "reason": reason, "note": note}

    if c_start is not None and beat_start < c_start - _SPAN_EPS:
        return refuse(NO_BLOCK_OUTSIDE_COMMENTARY,
                      f"the beat's first word ({beat_start:.2f}s) is heard before the "
                      f"commentary starts ({c_start:.2f}s) - a meme never covers the hook")
    if c_end is not None and beat_start + min_seconds > c_end + _SPAN_EPS:
        return refuse(NO_BLOCK_NO_ROOM,
                      f"from the beat's first word ({beat_start:.2f}s) to the payoff "
                      f"({c_end:.2f}s) is {max(0.0, c_end - beat_start):.2f}s, under the "
                      f"{min_seconds}s floor (M2)")
    first = next((i for i, b in enumerate(blocks)
                  if b["start"] - _SPAN_EPS <= beat_start < b["end"]), None)
    if first is None:
        return refuse(NO_BLOCK_NOT_AT_BEAT,
                      f"no block is on screen at the beat's first word ({beat_start:.2f}s)")
    need = beat_start + min_seconds
    span, end = [], None
    for i in range(first, len(blocks)):
        b = blocks[i]
        if span and abs(b["start"] - blocks[span[-1]]["end"]) > 0.05:
            break  # a gap in the timeline - the span is consecutive or nothing
        why = pinned_reason(b, i, taken)
        if why:
            return refuse(NO_BLOCK_PINNED,
                          f"{why}, {b['start']:.2f}-{b['end']:.2f}s, inside the "
                          f"{min_seconds}s the meme needs from {beat_start:.2f}s")
        span.append(i)
        if b["end"] >= need - _SPAN_EPS:
            end = float(b["end"])
            break
    if end is None:
        return refuse(NO_BLOCK_NO_ROOM,
                      f"the blocks from {beat_start:.2f}s end before the {min_seconds}s "
                      f"floor (M2) is reached")
    if c_end is not None and end > c_end + _SPAN_EPS:
        end = round(c_end, 3)  # the last block's own picture carries the payoff
    head = beat_start - blocks[first]["start"]
    start = beat_start
    if head < rhythm.MIN_ORDERED_BLOCK_SECONDS and (
            c_start is None or blocks[first]["start"] >= c_start - _SPAN_EPS):
        start = float(blocks[first]["start"])
    if max_seconds and end - start > max_seconds and need <= start + max_seconds:
        end = round(start + max_seconds, 3)
    while len(span) > 1 and blocks[span[-1]]["start"] >= end - _SPAN_EPS:
        span.pop()
    return {"ok": True, "blocks": span, "start_s": round(start, 3), "end_s": round(end, 3),
            "beat_start_s": round(beat_start, 3), "seconds": round(end - start, 3)}


# --------------------------------------------------------------------------
# the hole nobody asked about (CF-0138, rung 1 of the CF-0137 ladder)
# --------------------------------------------------------------------------

HOLE_PLACED_BY = "unrequested hole (CF-0138, rung 1)"


def hole_blocks(blocks, plan_degraded=None, taken=()):
    """Every block with no picture that is free to take an insert.

    Free means: not already carrying one (a proof has one place and took it
    first - CF-0071 - and a meme placed for a request is already there) and
    not in `taken`. Returned in block order, which is also the order they are
    filled in: a hole earlier in the video is not more deserving than a later
    one, but the budget has to be spent in *some* order, and the timeline is
    the only one that is not arbitrary.
    """
    return [i for i, b in enumerate(blocks)
            if i not in taken and not b.get("insert")
            and is_unresolved_block(b, i, plan_degraded)]


def hole_query(block, words):
    """What is embedded for a hole: the block's `intent` - the storyboard's
    description of the frame this block was supposed to show - and the words
    spoken over it only when there is no intent.

    This is the whole of why the CF-0143 floors can be reused unchanged here
    rather than a second threshold being invented for the hole (which the
    task forbids and CF-0123 would refuse anyway). `intent` is already a
    description of a picture - "a bundle of newspapers tied with string
    sliding along the ground", off a real plan - which is the register
    CF-0115 rewrote the intent vocabulary's `default_query` into after
    measuring that CLIP ranks the library cross-modally against the *image*.
    So the question M4 answers is the same question in both directions: does
    a library picture show what this text describes, well clear of the field.
    The narration fallback is a worse query (a sentence of speech is not a
    description of a frame) and is a fallback for exactly that reason - it
    will usually fail the floor, and failing the floor is the correct answer
    when there is nothing to match on.
    """
    intent = (block.get("intent") or "").strip()
    if intent:
        return intent
    return spoken_over(words, block["start"], block["end"]).strip()


def hole_fill_feasible(blocks, channel_cfg, pattern_cfg, root=None, spec=None,
                       plan_degraded=None):
    """Could a library insert conceivably close *every* hole in this plan?

    The cheap half of CF-0138, and the reason build_render_plan.py can still
    refuse a doomed plan before it pays for a single vision call: this reads
    two config switches and the block lengths, and touches neither the
    library, nor CLIP, nor Vision. It answers the only question the CF-0137
    gate has to defer for - "is there any point running the layers at all" -
    and it answers it the permissive way on purpose. It says nothing about
    whether the *pictures exist*; that is M4's answer and it costs money, so
    it is given after the layer has run, not guessed at here.

    `feasible: False` means the plan is refused now, exactly where CF-0137
    refused it, with no layer paid for. `feasible: True` means the refusal is
    deferred until the meme layer has had its turn, and re-asked then.
    """
    root = Path(root) if root else factory_root()
    spec = spec if spec is not None else load_spec(root)
    min_seconds = float(spec["placement"]["min_block_seconds"])
    max_inserts = int(spec["placement"]["max_inserts_per_video"])
    holes = hole_blocks(blocks, plan_degraded)
    at_floor = [i for i in holes
                if round(blocks[i]["end"] - blocks[i]["start"], 3) >= min_seconds]
    rec = {"holes": holes, "at_floor": at_floor, "feasible": False, "reason": ""}
    if not holes:
        rec["feasible"] = True
        rec["reason"] = "no hole to fill"
        return rec
    if not layer_enabled(channel_cfg):
        rec["reason"] = ("the meme layer is off on this channel "
                         "(insert_layers.meme.enabled) - rung 1 does not exist here")
        return rec
    if not pattern_allows(pattern_cfg):
        rec["reason"] = ("this pattern refuses the meme layer "
                         "(meme_layer.allowed) - rung 1 does not exist here")
        return rec
    short = [i for i in holes if i not in at_floor]
    if short:
        rec["reason"] = (f"block(s) {short} last under the {min_seconds}s an insert "
                         f"needs (M2) - a block is not lengthened to fit one")
        return rec
    if len(holes) > max_inserts:
        rec["reason"] = (f"{len(holes)} holes against placement."
                         f"max_inserts_per_video={max_inserts} - a video that is "
                         f"mostly inserts is a compilation, not a video")
        return rec
    rec["feasible"] = True
    rec["reason"] = (f"{len(holes)} hole(s), all at the {min_seconds}s floor and "
                     f"within the insert budget - the library gets its turn")
    return rec


# --------------------------------------------------------------------------
# the asset gate
# --------------------------------------------------------------------------

def _header_size(path):
    """Width/height straight from a PNG IHDR or a GIF logical-screen header -
    no library needed for the two formats the test library is made of."""
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return struct.unpack(">II", head[16:24])
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    return None


def asset_dimensions(path):
    """(width, height) natively: the file's own header for PNG/GIF, Pillow
    for the rest, ffprobe when Pillow is not here or cannot read it."""
    size = _header_size(path)
    if size:
        return size
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        pass
    return image_size(path)


def _render_size(path, animated):
    """CF-0379: `{"width", "height"}` of what Remotion actually draws, or None
    when the file's size cannot be read (an unknown size is not guessed - the
    caption band then simply keeps its ordinary place).

    For a still that is the file. For a GIF it is the mp4 prepare_render_src()
    cut from it, and that filter is `scale=trunc(iw/2)*2:trunc(ih/2)*2` - one
    pixel narrower or shorter on an odd side, which is below anything the
    caption lift can notice but is what the frame will be."""
    size = asset_dimensions(path)
    if not size or not all(size):
        return None
    w, h = size
    if animated:
        w, h = (int(w) // 2) * 2, (int(h) // 2) * 2
    return {"width": int(w), "height": int(h)}


def has_audio_track(path):
    return "audio" in stream_kinds(path)


def asset_text(path):
    """Text Vision reads on the asset in accurate mode - detect_text_band's
    sample_text_regions, the same call the proof gate makes."""
    import detect_text_band
    regions = detect_text_band.sample_text_regions(path, level=0)
    return " ".join(r.get("text", "") for r in regions if r.get("text", "").strip())


def restates(asset_words, spoken_words, run=RESTATE_RUN_WORDS):
    """M3 negative half, mechanically: the asset's text is the narration when
    a run of `run` asset words is spoken in the same order over the block, or
    when the whole asset text (two words or more) is."""
    a = norm_tokens(asset_words)
    s = norm_tokens(spoken_words)
    if len(a) < 2 or not s:
        return False
    spoken = " ".join(s)
    if " ".join(a) in spoken:
        return True
    for k in range(0, len(a) - run + 1):
        if " ".join(a[k:k + run]) in spoken:
            return True
    return False


def spoken_over(words, start, end):
    return " ".join(w.get("word", "") for w in words
                    if w.get("start", 0) < end and w.get("end", 0) > start)


# CF-0392: the output a plan without its own `output` is rendered at.
DEFAULT_OUTPUT = (1080, 1920)


def meme_box(plan=None):
    """`(width, height)` of the box a meme is drawn `contain` into - the
    INSERT BOX: the block's main zone cut a gap above the caption band
    (CF-0394, meme_captions.insert_box, the mirror of captionBand.js
    insertBox). Full frame width - the player's safe area (CF-0329) narrows
    the caption band, not the picture - and, at 1080x1920 with safe_area.py's
    zones, 1080x1219. A CF-0380 cutout, once it exists, is fitted into its own
    box and passes that box to upscale_factor() instead."""
    plan = plan or {}
    out = plan.get("output") or {}
    w = out.get("width") or DEFAULT_OUTPUT[0]
    h = out.get("height") or DEFAULT_OUTPUT[1]
    _x, _y, bw, bh = meme_captions.insert_box({**plan, "output": {"width": w, "height": h}})
    return (bw, bh)


def upscale_factor(size, box):
    """How far a picture of `size` (w, h) is stretched when fitted `contain`
    into `box` (w, h): min(bw / w, bh / h). Under 1 it is shrunk. A landscape
    meme is bound by the box's width, a portrait one by its height - which is
    the geometry the short-side floor ignored (CF-0392)."""
    w, h = size
    bw, bh = box
    return min(bw / w, bh / h)


def max_upscale(spec):
    """inserts/meme.json `asset_floor.max_upscale_factor` - read, never
    copied (CF-0392). A contract without it is a broken contract: KeyError."""
    return float(spec["asset_floor"]["max_upscale_factor"])


# CF-0405: the motion a whole still meme gets inside the insert box. The
# numbers are inserts/meme.json `composition.motion`'s, read, never copied;
# a contract without that block is a layer that has not been given motion yet,
# and the meme is placed as it was before 2026-09-26 - still. The modes are a
# closed list, the same reasoning as the outcomes.
MOTION_PUSH_IN = "push_in"
MOTION_PAN = "pan"
MOTION_STATIC = "static"
MOTION_MODES = (MOTION_PUSH_IN, MOTION_PAN, MOTION_STATIC)
# Why a meme stood still - closed too, so the Analyst asks one key one question.
MOTION_WHY_NO_CONTRACT = "no_motion_in_contract"
MOTION_WHY_ANIMATED = "animated"
MOTION_WHY_NO_SIZE = "size_unknown"
MOTION_WHY_NO_ROOM = "no_headroom_no_slack"
MOTION_WHY_BAD_CONTRACT = "motion_contract_unreadable"
MOTION_WHY_NOT = (MOTION_WHY_NO_CONTRACT, MOTION_WHY_ANIMATED, MOTION_WHY_NO_SIZE,
                  MOTION_WHY_NO_ROOM, MOTION_WHY_BAD_CONTRACT)


def meme_motion(size, box, spec, animated=False, block_index=0):
    """CF-0405: `{"mode", ...}` for one placed meme - how it moves inside the
    insert box for its whole span, or why it does not (`why`).

    A GIF never moves on top of its own motion (`animated`). A still pushes in
    from the `contain` fit (zoom 1) to `push_in_zoom`, bounded by the file's
    headroom under the CF-0392 ceiling: the stretch at the end of the push,
    upscale_factor() x zoom, never exceeds `asset_floor.max_upscale_factor` -
    so a file already stretched near the ceiling gets no zoom at all. When the
    headroom leaves less than `min_zoom`, the picture slides instead, along the
    axis it does not fill (the letterbox is the room it has): `pan_fraction`
    of the box on that axis, at most the slack, centred - no stretch added.
    A picture that fills the box's shape and has no headroom stands still.
    Nothing here can refuse the block: every failure is `static`, the meme
    placed exactly as before (the refusal rule of CF-0380 item 5).

    The pan's `from`/`to` are fractions of the box on `axis`, so the renderer
    (render/src/components/AssetLayer.jsx InsertLayer) moves the picture by its
    own box, not by a pixel count that assumes this one."""
    comp = (spec or {}).get("composition") or {}
    cfg = comp.get("motion")
    if animated:
        return {"mode": MOTION_STATIC, "why": MOTION_WHY_ANIMATED}
    if not cfg:
        return {"mode": MOTION_STATIC, "why": MOTION_WHY_NO_CONTRACT}
    try:
        target = float(cfg["push_in_zoom"])
        min_zoom = float(cfg["min_zoom"])
        pan_fraction = float(cfg["pan_fraction"])
        min_pan_px = float(cfg["min_pan_px"])
        ceiling = max_upscale(spec)
    except (KeyError, TypeError, ValueError):
        return {"mode": MOTION_STATIC, "why": MOTION_WHY_BAD_CONTRACT}
    if not size or not all(size) or not box or not all(box):
        return {"mode": MOTION_STATIC, "why": MOTION_WHY_NO_SIZE}
    w, h = float(size[0]), float(size[1])
    bw, bh = float(box[0]), float(box[1])
    fit = upscale_factor((w, h), (bw, bh))
    zoom = min(target, ceiling / fit)
    if zoom >= min_zoom:
        zoom = round(zoom, 4)
        # Four places can round up by 5e-5; step back under the ceiling.
        while fit * zoom > ceiling + 1e-9:
            zoom = round(zoom - 1e-4, 4)
        return {"mode": MOTION_PUSH_IN, "zoom_from": 1.0, "zoom_to": zoom,
                "stretch_to": round(fit * zoom, 4), "ceiling": ceiling}
    # The axis the picture does not fill: its slack is the letterbox.
    slack_x, slack_y = bw - w * fit, bh - h * fit
    axis, slack, side = ("y", slack_y, bh) if slack_y >= slack_x else ("x", slack_x, bw)
    travel = min(pan_fraction * side, slack)
    if travel < min_pan_px:
        return {"mode": MOTION_STATIC, "why": MOTION_WHY_NO_ROOM}
    half = round(travel / 2.0 / side, 4)
    # Alternate the direction by block, as AssetLayer alternates Ken Burns.
    sign = 1 if (block_index or 0) % 2 == 0 else -1
    return {"mode": MOTION_PAN, "axis": axis, "from": -sign * half, "to": sign * half,
            "stretch_to": round(fit, 4), "ceiling": ceiling}


# CF-0404: where a meme with an accepted CF-0403 cutout goes - the user's
# third example of CF-0380 (the rage face laid on the judge's head in the real
# frame): the block's own shot keeps playing and the cut-out figure sits on the
# part of it the words are about. A closed list, like the motion modes:
#   cutout_on_subject  on the face the frame describer (smart_crop's verdict,
#                      the plan's `roi_source: faces` + `focus`) found in the
#                      shot under the beat
#   cutout_in_corner   no face there - a bottom corner of the insert box,
#                      inside the player's safe area, on the side away from
#                      the shot's own focus
#   whole              no accepted cutout, or nothing playing under it - the
#                      meme exactly as before CF-0404 (contained, CF-0405
#                      motion): the refusal rule of CF-0380 item 5, the block
#                      is never lost to a cutout
PLACEMENT_ON_SUBJECT = "cutout_on_subject"
PLACEMENT_IN_CORNER = "cutout_in_corner"
PLACEMENT_WHOLE = "whole"
PLACEMENTS = (PLACEMENT_ON_SUBJECT, PLACEMENT_IN_CORNER, PLACEMENT_WHOLE)
# Why not on the subject (corner) or not a cutout at all (whole) - closed too.
PLACEMENT_WHY_NO_CUTOUT = "no_cutout"
PLACEMENT_WHY_CUTOUT_MISSING = "cutout_file_missing"
PLACEMENT_WHY_NO_FOOTAGE = "no_footage_under"
PLACEMENT_WHY_TOO_SMALL = "cutout_too_small"
PLACEMENT_WHY_GEOMETRY = "geometry_unknown"
PLACEMENT_WHY_NO_FACE = "no_face_roi"
PLACEMENT_WHY_OUTSIDE = "subject_outside_box"
PLACEMENT_WHY = (PLACEMENT_WHY_NO_CUTOUT, PLACEMENT_WHY_CUTOUT_MISSING,
                 PLACEMENT_WHY_NO_FOOTAGE, PLACEMENT_WHY_TOO_SMALL, PLACEMENT_WHY_GEOMETRY,
                 PLACEMENT_WHY_NO_FACE, PLACEMENT_WHY_OUTSIDE, PLACEMENT_WHY_SPAN)
# A cutout does not move: it sits on a shot that already does (CF-0405's
# `applies_to` leaves it out), and its motion record says so by this name.
MOTION_WHY_CUTOUT = "cutout"
MOTION_WHY_NOT = MOTION_WHY_NOT + (MOTION_WHY_CUTOUT,)
# The place's box, as a share of the insert box's width: a square the cut-out
# figure is fitted `contain` into, never stretched past the CF-0392 ceiling.
# Half the width on a face - the figure covers the head and shoulders, not
# the frame (the user's examples keep the frame readable around it); a little
# less in a corner, where it is beside the subject rather than on it.
SUBJECT_BOX_FRACTION = 0.5
CORNER_BOX_FRACTION = 0.42
# Under this many px on its long side a figure is a sticker, not a reaction:
# the meme goes whole instead.
MIN_CUTOUT_PX = 240
# Asset kinds that show nothing a figure could stand on (rhythm.has_picture's
# negatives, plus the drawn card): a cutout on a blank ground is a smaller,
# worse whole meme.
# CF-0689: and the factory's own graphic - drawn text and bars, no figure ground.
NO_FOOTAGE_KINDS = ("procedural", "card", "own_graphic", None)


def accepted_cutout(entry, folder):
    """(path, cutout_asset) of the entry's CF-0403 cutout, or (None, why).
    Accepted = the library's `cutout_asset.file` is non-null (a refused cut
    carries null there) and the PNG is on this disk."""
    ca = (entry or {}).get("cutout_asset") or {}
    if not ca.get("file"):
        return None, PLACEMENT_WHY_NO_CUTOUT
    path = Path(folder) / ca["file"]
    if not path.exists():
        return None, PLACEMENT_WHY_CUTOUT_MISSING
    return path, ca


def shot_under(block, at=None):
    """The picture of `block` playing at absolute time `at` (the block's
    start when None): the sequence cut covering it, else the asset itself."""
    asset = (block or {}).get("asset") or {}
    if asset.get("kind") != "sequence" or not asset.get("cuts"):
        return asset
    t = (at if at is not None else block.get("start", 0)) - block.get("start", 0)
    cuts = asset["cuts"]
    for cut in cuts:
        f = cut.get("from_seconds") or 0
        if f <= t < f + (cut.get("seconds") or 0):
            return cut
    return cuts[-1] if t >= 0 else cuts[0]


def subject_point(shot, zone):
    """Output-px (x, y) of the face the describer found in `shot`, or None.
    A `cover` fit with `object-position: focus` (AssetLayer.jsx) maps the
    source's point at fraction (fx, fy) onto the zone's point at the same
    fraction - and the `zoom` is anchored there too - so the face lands at
    zone + focus x zone size, whatever the source's aspect."""
    if (shot or {}).get("roi_source") != "faces" or shot.get("fit", "cover") != "cover":
        return None
    focus = shot.get("focus") or {}
    try:
        fx, fy = float(focus["x"]), float(focus["y"])
    except (KeyError, TypeError, ValueError):
        return None
    zx, zy, zw, zh = zone
    return (zx + fx * zw, zy + fy * zh)


def cutout_placement(ca, cutout_path, block, geometry, spec, at=None):
    """CF-0404: `{"placement", "why", "cutout"}` for one meme whose library
    entry has an accepted cutout - where the cut-out figure is drawn over the
    block's own shot, or `whole` and why not.

    `geometry` is {"zone", "insert_box", "safe"} in output px (placement_
    geometry()). The figure's alpha bbox (`cutout_asset.bbox_px`, `[x, y,
    w, h]` in source px - shared/inserts/inserts_lib.py) is fitted `contain`
    into the place's square box, capped at the CF-0392 ceiling - so a small
    file is drawn smaller rather than stretched - and the box is kept inside
    the insert box (never the caption band or the gap above it) and inside
    the player's safe area. The cutout PNG is already cropped to that bbox
    (w x h), so `cutout.image` equals `cutout.rect`: the whole PNG is the
    drawn figure, in output px (CF-0880 - it was read as `[x0, y0, x1, y1]`
    and the PNG stretched to the source's size, showing a fifth of it)."""
    shot = shot_under(block, at)
    if shot.get("kind") in NO_FOOTAGE_KINDS:
        return {"placement": PLACEMENT_WHOLE, "why": PLACEMENT_WHY_NO_FOOTAGE, "cutout": None}
    try:
        ceiling = max_upscale(spec)
        _x, _y, bw, bh = (float(v) for v in ca["bbox_px"])
        ix, iy, iw, ih = geometry["insert_box"]
        safe = geometry["safe"]
        out_w = geometry["zone"][0] + geometry["zone"][2]
        left, right = ix + safe["left"], min(ix + iw, out_w - safe["right"])
        top, bottom = max(iy, safe["top"]), iy + ih
        if bw <= 0 or bh <= 0 or right <= left or bottom <= top:
            raise ValueError("empty box")
    except (KeyError, TypeError, ValueError):
        return {"placement": PLACEMENT_WHOLE, "why": PLACEMENT_WHY_GEOMETRY, "cutout": None}

    def clamp(v, lo, hi):
        return max(lo, min(v, hi))

    point = subject_point(shot, geometry["zone"])
    why = None
    if point is None:
        why = PLACEMENT_WHY_NO_FACE
    elif not (left <= point[0] <= right and top <= point[1] <= bottom):
        why = PLACEMENT_WHY_OUTSIDE
    if why is None:
        side = min(SUBJECT_BOX_FRACTION * iw, right - left, bottom - top)
        px = clamp(point[0] - side / 2, left, right - side)
        py = clamp(point[1] - side / 2, top, bottom - side)
        mode = PLACEMENT_ON_SUBJECT
    else:
        side = min(CORNER_BOX_FRACTION * iw, right - left, bottom - top)
        # the side away from the shot's own focus, so the figure does not sit
        # on whatever the framing centred on; bottom, next to the words
        fx = float(((shot.get("focus") or {}).get("x")) or 0.5)
        px = left if fx >= 0.5 else right - side
        py = bottom - side
        mode = PLACEMENT_IN_CORNER
    k = min(side / bw, side / bh, ceiling)
    dw, dh = bw * k, bh * k
    if max(dw, dh) < MIN_CUTOUT_PX:
        return {"placement": PLACEMENT_WHOLE, "why": PLACEMENT_WHY_TOO_SMALL, "cutout": None}
    if mode == PLACEMENT_ON_SUBJECT:
        rx, ry = px + (side - dw) / 2, py + (side - dh) / 2
    else:
        rx = px if px == left else px + side - dw
        ry = py + side - dh
    r = lambda v: round(v, 1)  # noqa: E731
    return {"placement": mode, "why": why, "cutout": {
        "render_src": str(Path(cutout_path).resolve()),
        "rect": {"x": r(rx), "y": r(ry), "width": r(dw), "height": r(dh)},
        # the PNG is the bbox crop (w x h), so it fills the rect exactly
        "image": {"x": r(rx), "y": r(ry), "width": r(dw), "height": r(dh)},
        "stretch": round(k, 4), "ceiling": ceiling,
        "subject": {"x": r(point[0]), "y": r(point[1])} if mode == PLACEMENT_ON_SUBJECT else None,
        "shot": shot.get("shot"), "roi_source": shot.get("roi_source")}}


def placement_geometry(plan=None):
    """{"zone", "insert_box", "safe"} in output px for cutout_placement(),
    from the plan's own output / layout / safe zones - meme_captions' mirror
    of the renderer's layout.js and captionBand.js, the same one meme_box()
    reads."""
    plan = dict(plan or {})
    out = plan.get("output") or {}
    plan["output"] = {"width": out.get("width") or DEFAULT_OUTPUT[0],
                      "height": out.get("height") or DEFAULT_OUTPUT[1]}
    return {"zone": meme_captions.main_zone(plan),
            "insert_box": meme_captions.insert_box(plan),
            "safe": meme_captions.safe_px(plan)}


def _band_rows(data, stride, rows, drop, noise):
    """How many rows from the start of `rows` are of one tone: at most `noise`
    of a row's bytes fall outside the tone (`drop` holds the tone's bytes,
    deleted by translate - what is left over is off-tone). The copy of
    scripts/meme_desk.py's rule - the agent does not import the root's
    scripts/, and tests/test_meme_layer.py holds the two equal on one file."""
    n = 0
    for y in rows:
        r = data[y * stride:(y + 1) * stride]
        if len(r.translate(None, drop)) > noise * len(r):
            break
        n += 1
    return n


def blank_band_share(path, band):
    """CF-0534: the larger of the top and the bottom blank band of a still, as
    a share of its height (0.0 .. 1.0) - rows of one tone across the full
    width, white (at most `noise_share` of the row's RGB bytes under
    `white_min`) or black (at most `noise_share` over `black_max`). `band` is
    inserts/meme.json `asset_floor.blank_band`, read, never copied. None when
    the file cannot be read by Pillow - the gate then says nothing."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.seek(0)
            rgb = im.convert("RGB")
    except Exception:
        return None
    w, h = rgb.size
    if not w or not h:
        return None
    data, stride = rgb.tobytes(), w * 3
    noise = float(band["noise_share"])
    tones = (bytes(range(int(band["white_min"]), 256)),
             bytes(range(0, int(band["black_max"]) + 1)))
    best = 0
    for rows in (range(h), range(h - 1, -1, -1)):
        for drop in tones:
            best = max(best, _band_rows(data, stride, rows, drop, noise))
    return best / h


def check_asset(path, spec, spoken, frame, text_reader=asset_text,
                band_reader=blank_band_share):
    """(ok, reason) for one candidate file against composition.asset_gate.
    `frame` is the box the meme is drawn into (meme_box()), not the output
    frame. `text_reader` is injectable so a test never touches Vision;
    `band_reader` (CF-0534) so a test can hand the gate a measured band."""
    floor = spec["asset_floor"]
    suffix = Path(path).suffix.lower()
    stills = set(floor["still_suffixes"])
    animated = set(floor["animated_suffixes"])
    if not Path(path).exists():
        return False, SKIP_FILE_MISSING
    if suffix not in stills | animated:
        # Anything else is a clip: a file with a sound track is CF-0068's,
        # and a silent clip is not a meme file kind either.
        if has_audio_track(path):
            return False, SKIP_AUDIO
        return False, SKIP_UNREADABLE
    size = asset_dimensions(path)
    if not size or not all(size):
        return False, SKIP_UNREADABLE
    # CF-0392: the stretch in the box is the size gate, whole. No short-side
    # floor before it: 800x450 is 1.35x across a 1080-wide box, not a thumbnail.
    if upscale_factor(size, frame) > max_upscale(spec) + 1e-9:
        return False, SKIP_UPSCALE
    # CF-0534: a still carrying a blank caption panel of at least
    # `blank_band.min_share` of its height is refused - the desk cuts the
    # panel off, the editor never draws it as a stripe. A GIF is not measured:
    # the desk does not cut one either, it only lists it. A contract without
    # `blank_band` has not been given this gate.
    band = floor.get("blank_band")
    if band and suffix in stills:
        share = band_reader(path, band)
        if share is not None and share >= float(band["min_share"]) - 1e-9:
            return False, SKIP_BLANK_BAND
    try:
        text = text_reader(path)
    except Exception:
        text = ""
    if text and restates(text, spoken):
        return False, SKIP_MEANING
    return True, None


def prepare_render_src(path, dest_dir):
    """What Remotion draws. A still is drawn as it is; a GIF is turned into
    a silent mp4 beside the plan (Remotion's <Img> holds a GIF on its first
    frame, and @remotion/gif is not a dependency of render/), looped by
    <Loop> to the block's span. Returns (render_src, animated, loop_seconds)
    or None when the GIF could not be converted."""
    src = Path(path)
    if src.suffix.lower() != ".gif":
        return str(src.resolve()), False, None
    dest = Path(dest_dir) / f"meme-{src.stem}.mp4"
    out = ffmpeg("-i", str(src), "-an",
                 "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(dest),
                 # A GIF is short by nature, but the ceiling is still derived
                 # from it rather than assumed: one probe on a path taken only
                 # for GIFs.
                 media_seconds=media_duration(src))
    if out.returncode != 0 or not dest.exists():
        return None
    seconds = media_duration(dest)
    if not seconds or seconds <= 0:
        return None
    return str(dest.resolve()), True, round(seconds, 3)


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def selection_floors(spec):
    """M4's three numbers for one spec (CF-0143): (min_similarity, min_lead,
    lead_rank, note).

    `note` is a string when the spec is looser than the measurement and the
    module held the line, else None - a fact for the plan's notes rather than
    a silent divergence between the contract file and what ran.
    """
    sel = spec["selection"]
    spec_sim = float(sel["min_similarity"])
    min_sim, note = spec_sim, None
    if spec_sim < MIN_SIMILARITY_MEASURED:
        min_sim = MIN_SIMILARITY_MEASURED
        note = (f"meme: inserts/meme.json selection.min_similarity is {spec_sim}, below the "
                f"{MIN_SIMILARITY_MEASURED} measured on the filled library (CF-0143); the "
                f"measured floor is the one applied")
    return (min_sim, float(sel.get("min_lead", MIN_LEAD_DEFAULT)),
            int(sel.get("lead_rank", LEAD_RANK_DEFAULT)), note)


def lead_over_field(ranked, i, lead_rank):
    """How far the candidate at rank `i` of `ranked` stands above the field:
    its score minus the score `lead_rank - 1` places below it (CF-0143).

    Ranks past the end of the list count as 0 - a library with fewer pictures
    than `lead_rank` has no field to stand above, and there the similarity
    floor is the whole of M4. `ranked` is inserts_lib.rank_by_embedding()'s
    output: (score, entry) pairs, best first.
    """
    if i >= len(ranked):
        return 0.0
    below = i + lead_rank - 1
    trailing = ranked[below][0] if below < len(ranked) else 0.0
    return round(ranked[i][0] - trailing, 4)


# --------------------------------------------------------------------------
# CF-0388: the library's `tags` in the selection
# --------------------------------------------------------------------------
# Until CF-0388 the ranking was CLIP alone - the picture's vector against the
# query's - and the ~20 tags per meme the user asked for in CF-0381 ("so that
# memes land on the keywords, more relevant and alive") were read by nobody
# but the validator. Now the words of the request are matched against them:
# `beat_text` (what is heard where the meme lands - its first word is the
# moment, as with the sound layer) and the writer's own `query` when there is
# one. The intent's `default_query` is not matched: it describes the expected
# leader's picture, and CLIP already ranks that picture first.
#
# How the two are combined - measured 2026-09-26 on the 22 memes left after
# CF-0381 and the 14 real reactions of pipeline/example-film/* (all with
# query: null):
#
#   * the tag route goes first. A candidate whose tags the request's words
#     match is tried before the CLIP walk, most matched tags first, then by
#     CLIP score. Through the same asset gate (size ceiling, OCR restate,
#     distinct per video): a tag never overrides a gate.
#   * it has a floor, but not M4's. Tag-matched pictures sit at 0.15-0.22
#     against the intent's query - the intent's query describes another
#     picture - so min_similarity 0.26 would admit none of them and the tags
#     would still change nothing. The floor is the candidate's place in the
#     library as CLIP ranks it for this query: the upper part
#     (TAG_FLOOR_RANK_FRACTION, the median). Below it CLIP says the picture
#     is the wrong one for what the writer asked, and the tag is not enough.
#     On the measurement it separates the hits: `underwhelming` ->
#     disappointed-cricket-fan 0.2154 >= disbelief's median 0.2113 is kept,
#     `fake` -> imagination-spongebob 0.180, `plan` -> roll-safe 0.172 and
#     `ended` (of "ended up") -> grant-gustin-over-grave 0.171 are not.
#   * a one-word tag that is a function word does not count (TAG_STOPWORDS):
#     `why` -> facepalm-old-man and `everyone` -> spirerunner-triple cleared the
#     median on the measurement (0.187 / 0.213) and are words every sentence
#     says. A multi-word tag ("not again", "i'm not saying") counts whole.
#   * nothing is refused on the tag route. Whatever it does not place goes to
#     the CLIP walk exactly as before, so a request CLIP answered is still
#     answered - the CF-0388 item 4 condition for not pricing a new refusal.
#
# Normalisation is the sound layer's (sound_layer.matched_tags): lowercase,
# norm_tokens(), a tag matched as a whole run of words, no stemming, no
# synonyms.
TAG_FLOOR_RANK_FRACTION = 0.5
TAG_STOPWORDS = frozenset("""
a about above after again against all also am an and any anyone anything are
as at be been being both but by can could did do does doing down during each
even ever every everybody everyone everything few for from further had has
have having he her here hers him his how i if in inside into is it its itself
just me more most my no nobody nor not nothing now of off on once one only or
other our ours out over own same she should so some somebody someone
something still such than that the their them then there these they this
those three through to too two under until up very was we were what when
where which while who whom why will with within would yet you your yours
really double
""".split())


def tag_floor_fraction(spec):
    """`selection.tag_match.floor_rank_fraction` when the contract carries it,
    else TAG_FLOOR_RANK_FRACTION."""
    tm = (spec.get("selection") or {}).get("tag_match") or {}
    return float(tm.get("floor_rank_fraction", TAG_FLOOR_RANK_FRACTION))


def request_tokens(reaction):
    """The words a request's tags are matched against: `beat_text` and the
    writer's own `query` (never the intent's default_query)."""
    parts = [reaction.get("beat_text")]
    q = reaction.get("query")
    if isinstance(q, str) and q.strip():
        parts.append(q)
    return norm_tokens(" ".join(p for p in parts if isinstance(p, str)))


def _phrase_in(phrase, tokens):
    n = len(phrase)
    return bool(n) and any(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))


def meme_matched_tags(entry, tokens):
    """The entry's tags heard in `tokens`, in the entry's own order: a tag's
    words as a whole run; a one-word tag that is a function word does not
    count (TAG_STOPWORDS)."""
    out = []
    for tag in entry.get("tags") or []:
        phrase = norm_tokens(str(tag))
        if not phrase or (len(phrase) == 1 and phrase[0] in TAG_STOPWORDS):
            continue
        t = str(tag).lower()  # as the library writes it, so a reader finds it there
        if t not in out and _phrase_in(phrase, tokens):
            out.append(t)
    return out


def tag_candidates(ranked, tokens, fraction=TAG_FLOOR_RANK_FRACTION):
    """[(rank, score, entry, matched_tags)] of `ranked` (rank_by_embedding's
    output, best first) whose tags `tokens` match and whose CLIP score is at
    or above the tag floor - the score at `fraction` of the way down the
    ranking - most matched tags first, then by rank."""
    if not ranked or not tokens:
        return []
    floor = ranked[min(len(ranked) - 1, int(len(ranked) * fraction))][0]
    out = []
    for i, (score, entry) in enumerate(ranked):
        if score < floor:
            break
        m = meme_matched_tags(entry, tokens)
        if m:
            out.append((i, score, entry, m))
    out.sort(key=lambda t: (-len(t[3]), t[0]))
    return out


def span_record(built):
    """CF-0811: what `meme_delivered[].span` and `insert.span` say about a
    meme laid over a span rather than one block."""
    return {"blocks": list(built["blocks"]), "start_s": built["start_s"],
            "end_s": built["end_s"], "seconds": built["seconds"],
            "beat_start_s": built["beat_start_s"]}


def _answer(beat_id, outcome, block_index=None, asset_id=None, score=None, evidence=None,
            reason=None):
    """`evidence` (CF-0235, the shape CF-0193 gave the proof layer) is written
    exactly when the outcome is one of the three beat diagnoses: which
    fragment was looked for, how much of it is in the script, how much in the
    alignment, and the stretch that came closest as it was actually heard.
    Without it `beat_unmatched_in_alignment` is one word replacing another and
    nobody downstream can tell whether it is true."""
    a = {"beat_id": beat_id, "outcome": outcome, "block_index": block_index,
         "asset_id": asset_id, "score": score}
    # CF-0811: a `no_block` always says which of NO_BLOCK_REASONS it was.
    if reason is not None:
        a["reason"] = reason
    if evidence is not None:
        a["evidence"] = evidence
    return a


def _record(lib, entry, check, block, beat_id, score, skip_reason=None, lead=None,
            origin=ORIGIN_REQUEST, matched_tags=None, motion=None, placement=None):
    rec = lib.provenance_record(entry, check, block=block)
    rec["layer"] = LAYER
    rec["beat_id"] = beat_id
    rec["score"] = score
    # CF-0143: M4's second number. CF-0236: `score` and `lead` are numbers on
    # every record this layer writes - since CF-0389 nothing cuts a meme before
    # the ranking, so every candidate recorded here was ranked. A null on
    # either is a record written before 2026-09-24.
    rec["lead"] = lead
    # CF-0388: the entry's tags the request's words matched - non-empty
    # exactly when the tag route tried this file, [] when CLIP alone did.
    rec["matched_tags"] = list(matched_tags or [])
    # CF-0138: which of the two things this is. `beat_id` is None on a hole
    # fill - there was no request - so `origin` is what a reader joins on
    # rather than the absence of another field.
    rec["origin"] = origin
    # CF-0236: the key is on every record, null on the placed file - so a
    # reader asks one question of one key, in this layer and in the sound
    # layer alike, and `skipped` is true exactly when it is not null.
    rec["skip_reason"] = skip_reason
    if skip_reason:
        rec["skipped"] = True
    # CF-0405: how the placed meme moves in its box - one of MOTION_MODES - on
    # every record, null on a skipped one (it was never drawn). The overlay's
    # `motion` carries the numbers; this is the name the Analyst counts by.
    rec["motion"] = motion
    # CF-0404: where the placed meme went - one of PLACEMENTS - null on a
    # skipped record, the same shape as `motion`.
    rec["placement"] = placement
    return rec


def plan_memes(script, words, blocks, channel_cfg, pattern_cfg, root=None,
               embed=None, text_reader=asset_text, frame=None,
               plan_degraded=None, work_dir=None, index=None,
               fill_holes=True, geometry=None):
    """The whole decision for one video.

    Returns {meme_requested, meme_delivered, inserts (provenance records,
    placed first), overlays {block_index: insert dict}, notes, hole_fill}.
    Pure with respect to `blocks` - apply_to_blocks() / apply_to_plan() are
    the only writers.

    `fill_holes` (CF-0138) is rung 1 of the CF-0137 ladder: after the
    script's requests are answered, a block that has no picture at all is
    offered the library too, with no request behind it. It is on by default
    because a hole is a defect of the plan whatever the script asked for, and
    the parameter exists so that a caller measuring the *requested* half
    alone can switch it off.
    """
    root = Path(root) if root else factory_root()
    spec = load_spec(root)
    frame = frame or meme_box()  # CF-0392: the insert box, not the frame
    geometry = geometry or placement_geometry()  # CF-0404: where a cutout may go
    reactions = script.get(spec["selection"]["script_field"]) or []
    requested, delivered, inserts_placed, inserts_skipped, overlays, notes = [], [], [], [], {}, []
    if not isinstance(reactions, list):
        reactions = []
    reactions = reactions[:spec["selection"]["max_reactions_per_script"]]
    for r in reactions:
        requested.append({"beat_id": r.get("beat_id"), "intent": r.get("intent"),
                          "query": query_text(r, spec)})

    enabled = layer_enabled(channel_cfg)
    allowed = pattern_allows(pattern_cfg)
    min_seconds = float(spec["placement"]["min_block_seconds"])
    min_sim, min_lead, lead_rank, floor_note = selection_floors(spec)
    tag_fraction = tag_floor_fraction(spec)  # CF-0388
    max_inserts = int(spec["placement"]["max_inserts_per_video"])
    max_span = spec["placement"].get("max_block_seconds")  # CF-0811: a span's ceiling

    # CF-0138: the holes as they stand before this layer touches anything -
    # every block that would make the CF-0137 gate refuse the plan. Recorded
    # whole even when nothing is filled, for the reason CF-0137 wrote
    # `emergency_reuse` on every plan: "this video had no hole" is the fact
    # the Analyst compares against when one does.
    holes = hole_blocks(blocks, plan_degraded) if fill_holes else []
    hole_fill = {"attempted": False, "holes": list(holes),
                 "at_floor": [i for i in holes
                              if round(blocks[i]["end"] - blocks[i]["start"], 3) >= min_seconds],
                 "filled": [], "refused": [], "note": ""}
    if not reactions and not holes:
        return {"meme_requested": [], "meme_delivered": [], "inserts": [],
                "overlays": {}, "notes": notes, "hole_fill": hole_fill}

    lib = index_entries = bank_dir = None
    if enabled and allowed:
        lib = _lib(root)
        # CF-0393: the channel's own bank, or the default folder; a named
        # bank that is missing raises here - the caller reports it, and no
        # meme is drawn from somebody else's bank in its place.
        bank, bank_dir = library_folder(root, channel_cfg)
        if bank:
            notes.append(f"meme bank: {bank}/ (insert_layers.meme.bank, CF-0393)")
        index = index if index is not None else lib.load_index(
            LIBRARY_KIND, Path(root) / "shared" / "inserts", bank)
        index_entries = index.get("entries", [])
        embed = embed or make_embedder(root)
        if floor_note:
            notes.append(floor_note)

    taken, placed_ids = set(), set()

    def attempt(bi, beat_id, origin, entry, score, lead, spoken, matched=None):
        """Distinct per video, the asset gate and the render source for one
        candidate: the chosen tuple, or None with the skip recorded."""
        check = lib.check_for(entry)
        if entry["id"] in placed_ids:
            inserts_skipped.append(_record(lib, entry, check, bi, beat_id, score,
                                           SKIP_DISTINCT, lead, origin, matched))
            return None
        path = bank_dir / entry["file"]
        ok, reason = check_asset(path, spec, spoken, frame, text_reader)
        if not ok:
            inserts_skipped.append(_record(lib, entry, check, bi, beat_id, score,
                                           reason, lead, origin, matched))
            return None
        prepared = prepare_render_src(path, work_dir or path.parent)
        if prepared is None:
            inserts_skipped.append(_record(lib, entry, check, bi, beat_id, score,
                                           SKIP_UNREADABLE, lead, origin, matched))
            return None
        return (score, entry, check, path, prepared, lead, list(matched or []))

    def select(bi, beat_id, origin, query, spoken, label, tokens=None):
        """M4 and the asset gate over the ranked library for one block.

        The same walk for both origins, and that is CF-0138's whole
        mechanism: the picture in a hole nobody asked for is admitted by the
        floors CF-0143 measured, not by a second number written for it. It
        returns the chosen candidate or None; the caller decides what a None
        means for the request (`no_asset`) or for the plan (the next rung of
        the CF-0137 ladder).

        CF-0388: `tokens` (a request's beat_text and own query) go first
        through the tag route - tag_candidates() over the same ranking, the
        same gate - and only what it does not place reaches the CLIP walk,
        which runs exactly as before. A hole has no request and no tokens.
        """
        try:
            vec = embed(query)
        except Exception as e:  # noqa: BLE001 - the reason goes into the notes
            notes.append(f"{label}: query not embedded - {e}")
            return None
        # CF-0389 (inserts/POLICY.md, amendment 2026-09-24): a meme has no
        # rights holder, so the whole library ranks - no blacklist check runs
        # here, and each record says so through lib.check_for() instead of
        # carrying a skip.
        ranked = lib.rank_by_embedding(index_entries, vec)
        tried = set()
        for i, score, entry, matched in tag_candidates(ranked, tokens or [], tag_fraction):
            got = attempt(bi, beat_id, origin, entry, score,
                          lead_over_field(ranked, i, lead_rank), spoken, matched)
            if got is not None:
                return got
            tried.add(entry["id"])
        if tried:
            notes.append(f"{label}: tag match(es) {sorted(tried)} did not pass the asset "
                         f"gate - the CLIP walk decides (CF-0388)")
        for i, (score, entry) in enumerate(ranked):
            # CF-0236: the candidate a floor stops the walk at is recorded -
            # measured `score` and `lead` beside the floor's name - so that
            # "the library had something, and this is how close it came" is
            # in the data and not only in a note. One record per refusal: the
            # walk still ends here, because under the similarity floor every
            # later rank scores lower still, and past a level top M4 answers
            # the request with no_asset rather than the next picture down.
            lead = lead_over_field(ranked, i, lead_rank)
            if score < min_sim:
                notes.append(f"{label}: best remaining candidate {entry['id']} scores "
                             f"{score} < {min_sim} (similarity floor)")
                inserts_skipped.append(_record(lib, entry, lib.check_for(entry), bi, beat_id,
                                               score, SKIP_SIMILARITY, lead, origin))
                break
            # M4 (CF-0143): a candidate answers only if it stands clear of the
            # field. Level with the pictures under it, it is the least wrong
            # one, and the request goes on to the CF-0137 ladder instead.
            if lead < min_lead:
                behind = ranked[i + lead_rank - 1][1]["id"] if i + lead_rank - 1 < len(ranked) else None
                notes.append(f"{label}: best remaining candidate {entry['id']} scores "
                             f"{score} but leads rank {i + lead_rank}"
                             + (f" ({behind})" if behind else "")
                             + f" by {lead} < {min_lead} (lead floor)")
                inserts_skipped.append(_record(lib, entry, lib.check_for(entry), bi, beat_id,
                                               score, SKIP_LEAD, lead, origin))
                break
            if entry["id"] in tried:
                continue  # the tag route already gated it and recorded the skip
            got = attempt(bi, beat_id, origin, entry, score, lead, spoken)
            if got is not None:
                return got
        return None

    def place(bi, chosen, beat_id, intent, query, origin, why, at=None, span=None):
        """The one writer of an overlay and of a placed provenance record.
        `at` is the time the words are heard (the beat's first word) - the
        shot under it is the one a cutout is laid on (CF-0404).

        `span` (CF-0811, build_span()) lays the one meme over several blocks:
        the overlay goes on each of them, windowed to the span, with the same
        `span` record - and it is always the whole meme, never a cutout (a
        figure on one shot cannot ride the next one's)."""
        score, entry, check, path, (render_src, animated, loop_seconds), lead, matched = chosen
        taken.add(bi)
        if span:
            taken.update(span["blocks"])
        placed_ids.add(entry["id"])
        source_size = _render_size(path, animated)
        # CF-0404: a meme with an accepted CF-0403 cutout is laid over the
        # block's shot - on its face, else in a corner; anything else, and
        # any failure, is the whole meme as before.
        placement = {"placement": PLACEMENT_WHOLE, "why": PLACEMENT_WHY_NO_CUTOUT, "cutout": None}
        if span:
            placement = {**placement, "why": PLACEMENT_WHY_SPAN}
        elif not animated:
            try:
                cut_path, ca = accepted_cutout(entry, path.parent)
                placement = (cutout_placement(ca, cut_path, blocks[bi], geometry, spec, at)
                             if cut_path else {**placement, "why": ca})
            except Exception:  # noqa: BLE001 - the refusal rule: placed whole
                placement = {"placement": PLACEMENT_WHOLE, "why": PLACEMENT_WHY_GEOMETRY,
                             "cutout": None}
        # CF-0405: the motion is decided on the pixels Remotion draws, in the
        # box the gate measured the stretch in. It can only ever say `static`
        # on a failure - the block is never lost to it.
        try:
            motion = ({"mode": MOTION_STATIC, "why": MOTION_WHY_CUTOUT}
                      if placement["placement"] != PLACEMENT_WHOLE else meme_motion(
                (source_size["width"], source_size["height"]) if source_size else None,
                frame, spec, animated=animated, block_index=bi))
        except Exception:  # noqa: BLE001 - the refusal rule: placed as before
            motion = {"mode": MOTION_STATIC, "why": MOTION_WHY_BAD_CONTRACT}
        inserts_placed.append(_record(lib, entry, check, bi, beat_id, score,
                                      lead=lead, origin=origin, matched_tags=matched,
                                      motion=motion["mode"],
                                      placement=placement["placement"]))
        overlays[bi] = {
            "kind": LAYER,
            "origin": origin,  # CF-0138: asked for, or standing in for footage
            "beat_id": beat_id,
            "intent": intent,
            "query": query,
            "asset_id": entry["id"],
            "file": str(path.resolve()),
            "render_src": render_src,
            "animated": animated,
            "loop_seconds": loop_seconds,
            # CF-0379: the file's own pixels. A meme is fitted `contain` into
            # the block's frame, so where its picture actually ends inside that
            # frame is a function of this ratio and of nothing in the plan -
            # and since CF-0379 our captions run *under* a meme (CF-0394: in
            # their fixed band, the meme fitted above it - the render QC
            # reads this to know where the picture lands,
            # render/src/lib/captionBand.js). A GIF is drawn from the silent
            # mp4 prepare_render_src() cut from it, whose dimensions are the
            # source's rounded down to even by the same ffmpeg scale filter.
            "source_size": source_size,
            # CF-0405: push_in / pan / static and its numbers - AssetLayer.jsx
            # InsertLayer draws it; `why` says why a still stood still.
            "motion": motion,
            # CF-0404: cutout_on_subject / cutout_in_corner / whole, why it is
            # not the first, and the cutout's drawn rect over the block's shot
            # (null when whole) - AssetLayer.jsx draws the shot under it.
            "placement": placement["placement"],
            "placement_why": placement["why"],
            "cutout": placement["cutout"],
            "score": score,
            "lead": lead,  # CF-0143: M4's margin over the field, for the Analyst
            "matched_tags": matched,  # CF-0388: why this file, when a tag chose it
            "fit": spec["composition"]["fit"],
            "background": spec["composition"]["background"],
            "captions": spec["composition"]["our_captions"],
            "placed_by": why,
        }
        if span:
            # CF-0811: the same meme on every block of the span, each windowed
            # to its own part of it (AssetLayer.jsx insertSpan) - the first
            # block keeps its picture up to `start_s`, the last after `end_s`.
            rec = span_record(span)
            base = overlays[bi]
            for j in span["blocks"]:
                b = blocks[j]
                overlays[j] = {**base, "span": rec,
                               "start_s": round(max(b["start"], span["start_s"]), 3),
                               "end_s": round(min(b["end"], span["end_s"]), 3)}
        return score, entry, lead, matched

    for req, r in zip(requested, reactions):
        beat_id = req["beat_id"]
        if not enabled:
            delivered.append(_answer(beat_id, OUTCOME_LAYER_OFF))
            continue
        if not allowed:
            delivered.append(_answer(beat_id, OUTCOME_PATTERN_REFUSED))
            continue
        span = locate_beat(r.get("beat_text"), script, words)
        if span is None:
            # CF-0235: which of the two, and the fragments to check it by.
            why = beat_failure(r.get("beat_text"), script, words)
            delivered.append(_answer(beat_id, why["code"], evidence=why))
            near = why.get("nearest") or {}
            notes.append(f"meme {beat_id}: {why['code']} - beat {why['searched']!r} "
                         f"({why['in_script_coverage']} of its words are in the script, "
                         f"{why['alignment_coverage']} in the alignment); nearest heard "
                         f"at word {near.get('word_index')}: {near.get('text')!r}")
            continue
        beat_start, beat_end = words[span[0]]["start"], words[span[1]]["end"]
        if len(placed_ids) >= max_inserts:
            delivered.append(_answer(beat_id, OUTCOME_NO_BLOCK, reason=NO_BLOCK_MAX_INSERTS))
            notes.append(f"meme {beat_id}: max_inserts_per_video reached")
            continue
        cands = candidate_blocks(blocks, beat_start, beat_end, min_seconds, taken, plan_degraded)
        built = None
        if cands:
            bi, why = cands[0]
            block = blocks[bi]
            spoken = spoken_over(words, block["start"], block["end"])
        else:
            # CF-0811: no block at the floor overlaps the beat - the meme is
            # given a span from the beat's first word instead of `no_block`.
            built = build_span(blocks, beat_start, min_seconds, taken,
                               commentary_bounds(script, words), max_span)
            if not built["ok"]:
                delivered.append(_answer(beat_id, OUTCOME_NO_BLOCK, reason=built["reason"]))
                notes.append(f"meme {beat_id}: no_block ({built['reason']}) - {built['note']}")
                continue
            bi, why = built["blocks"][0], SPAN_PLACED_BY
            spoken = spoken_over(words, built["start_s"], built["end_s"])
        chosen = select(bi, beat_id, ORIGIN_REQUEST, req["query"], spoken,
                        f"meme {beat_id}", tokens=request_tokens(r))
        if chosen is None:
            delivered.append(_answer(beat_id, OUTCOME_NO_ASSET))
            continue
        score, entry, lead, matched = place(bi, chosen, beat_id, req["intent"], req["query"],
                                            ORIGIN_REQUEST, why, at=beat_start, span=built)
        answer = _answer(beat_id, OUTCOME_PLACED, bi, entry["id"], score)
        answer["matched_tags"] = matched  # CF-0388: [] when CLIP alone chose it
        if built:
            answer["span"] = span_record(built)  # CF-0811
        delivered.append(answer)
        notes.append(f"meme {beat_id}: {entry['id']} on block {bi} ({why}"
                     + (f", blocks {built['blocks']} {built['start_s']:.2f}-"
                        f"{built['end_s']:.2f}s" if built else "")
                     + f", score {score}, lead {lead}"
                     + (f", tags {matched}" if matched else "") + ")")

    # ----------------------------------------------------------------------
    # CF-0138: the holes nobody asked about - rung 1 of the CF-0137 ladder.
    #
    # This runs after the requests and never before them: a reaction the
    # writer asked for is a joke about the meaning of a beat and it owns the
    # insert budget first, the same precedence CF-0071 gave a proof over a
    # meme. What is left over goes to the holes, in block order, and each one
    # has to earn its picture through the same M4 floors - which is the
    # ordinary case being *refused*, not an accident: a picture that does not
    # clear the floor in a hole is a random picture on a wall, which is the
    # thing CF-0123 said must not happen, and the block goes on to rung 2.
    # ----------------------------------------------------------------------
    if fill_holes and holes:
        hole_fill["attempted"] = True
        remaining = hole_blocks(blocks, plan_degraded, taken)
        if not enabled or not allowed:
            outcome = OUTCOME_LAYER_OFF if not enabled else OUTCOME_PATTERN_REFUSED
            for bi in remaining:
                hole_fill["refused"].append({
                    "block_index": bi, "outcome": outcome,
                    "note": ("the meme layer is off on this channel"
                             if not enabled else "this pattern refuses the meme layer")})
        else:
            for bi in remaining:
                block = blocks[bi]
                if len(placed_ids) >= max_inserts:
                    hole_fill["refused"].append({
                        "block_index": bi, "outcome": OUTCOME_NO_BLOCK,
                        "note": f"max_inserts_per_video ({max_inserts}) already spent"})
                    continue
                if round(block["end"] - block["start"], 3) < min_seconds:
                    hole_fill["refused"].append({
                        "block_index": bi, "outcome": OUTCOME_NO_BLOCK,
                        "note": f"block lasts under the {min_seconds}s floor (M2)"})
                    continue
                query = hole_query(block, words)
                spoken = spoken_over(words, block["start"], block["end"])
                if not query:
                    hole_fill["refused"].append({
                        "block_index": bi, "outcome": OUTCOME_NO_ASSET,
                        "note": "the block says nothing about what it wanted to show - "
                                "no intent and no words over it, so nothing to embed"})
                    continue
                chosen = select(bi, None, ORIGIN_HOLE, query, spoken, f"hole block {bi}")
                if chosen is None:
                    hole_fill["refused"].append({
                        "block_index": bi, "outcome": OUTCOME_NO_ASSET,
                        "note": f"nothing in the library answers {query!r} clear of the "
                                f"field (M4: {min_sim} / {min_lead} at rank {lead_rank})"})
                    continue
                score, entry, lead, _matched = place(bi, chosen, None, None, query,
                                                     ORIGIN_HOLE, HOLE_PLACED_BY)
                hole_fill["filled"].append({"block_index": bi, "asset_id": entry["id"],
                                            "score": score, "lead": lead, "query": query})
                notes.append(f"hole block {bi}: {entry['id']} stands in for footage that "
                             f"never arrived - nobody asked for this insert (score {score}, "
                             f"lead {lead}, CF-0138)")
        hole_fill["note"] = (
            f"{len(hole_fill['filled'])} of {len(holes)} hole(s) filled from the library "
            f"(CF-0138, rung 1 of the CF-0137 ladder); "
            f"{len(hole_fill['refused'])} went on to the next rung")

    return {"meme_requested": requested, "meme_delivered": delivered,
            "inserts": inserts_placed + inserts_skipped, "overlays": overlays,
            "notes": notes, "hole_fill": hole_fill}


def apply_to_blocks(blocks, result):
    """`insert` onto each placed block and nothing else, before the plan dict
    exists (CF-0138).

    proof_layer has had this since CF-0071, for the same reason it is needed
    here now: the CF-0137 assetless gate is re-asked between this layer and
    the sound layer, and it reads the blocks. A hole filled in `overlays` but
    not written onto the block is a hole the gate would still refuse the plan
    over. apply_to_plan() below writes the same dicts again and is safe to
    call after this.
    """
    for bi, overlay in (result.get("overlays") or {}).items():
        blocks[int(bi)]["insert"] = dict(overlay)
    return blocks


def apply_to_plan(plan, result):
    """Merge a plan_memes() result into a render plan in place: `insert` on
    each placed block (and nothing else on any block), and plan["meme"] with
    the pair and the provenance. Returns the plan."""
    apply_to_blocks(plan["blocks"], result)
    plan["meme"] = {
        "meme_requested": result["meme_requested"],
        "meme_delivered": result["meme_delivered"],
        "inserts": result["inserts"],
        # CF-0138: the holes this video had and what the library did about
        # them. Always present on a plan this layer ran, filled or not - the
        # record of a rung that was offered and declined is what tells a
        # refusal caused by an empty library apart from one caused by a
        # block too short to carry a picture.
        "hole_fill": result.get("hole_fill") or empty_hole_fill(),
        "notes": result["notes"],
    }
    return plan


def empty_hole_fill():
    return {"attempted": False, "holes": [], "at_floor": [], "filled": [],
            "refused": [], "note": "the layer did not run"}


def hole_fill_fields(plan):
    """`videos[].meme_hole_fill` for write_batch_metadata.py (CF-0138).

    Always a record, and a plan built before this rung existed says so rather
    than reading as a video that had no holes - the same promise
    assetless_rung.stage_fields() makes about its own gate, and for the same
    reason: absence must never have to be interpreted.
    """
    m = plan.get("meme") or {}
    rec = m.get("hole_fill")
    if isinstance(rec, dict):
        return rec
    return {**empty_hole_fill(), "attempted": None,
            "note": "plan predates the library-insert rung (CF-0138) - not offered"}


def stage_fields(plan):
    """What write_batch_metadata.py copies onto the videos[] record: the
    pair (always both, [] when the plan never ran the layer) and this
    layer's provenance records."""
    m = plan.get("meme") or {}
    return (list(m.get("meme_requested") or []),
            list(m.get("meme_delivered") or []),
            list(m.get("inserts") or []))


def merge_inserts(existing, records):
    """videos[].inserts[] with this layer's records replacing this layer's
    previous records and every other layer's left alone - the way
    underlay.write_stage_record() merges, so the two can run in any order."""
    kept = [r for r in (existing or []) if not (isinstance(r, dict) and r.get("layer") == LAYER)]
    return kept + list(records)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="plan the meme inserts for one render plan")
    ap.add_argument("plan")
    ap.add_argument("--script", required=True, help="03-content-researcher.json")
    ap.add_argument("--script-id", required=True)
    ap.add_argument("--channel", help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--pattern", help="pattern id; default: the plan's rhythm.pattern_requested")
    ap.add_argument("--root", help=f"factory root (default ${FACTORY_ROOT_ENV} or the checkout)")
    ap.add_argument("--words", help="words.json; default: the plan's own `words`")
    ap.add_argument("--query-vectors", help="json {query: vector} in place of CLIP (tests)")
    ap.add_argument("--write", action="store_true", help="merge the result into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else factory_root()
    plan = json.load(open(a.plan))
    batch = json.load(open(a.script))
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((s for s in scripts or [] if s.get("script_id") == a.script_id), None)
    if script is None:
        raise SystemExit(f"script {a.script_id!r} not in {a.script}")
    words = load_words(a.words) if a.words else plan.get("words") or []
    pattern_id = a.pattern or (plan.get("rhythm") or {}).get("pattern_requested")
    # CF-0394/CF-0392: a meme is drawn `contain` into the box above the
    # caption band, not into the whole frame - the upscale is judged on that box.
    result = plan_memes(
        script, words, plan["blocks"], load_channel(a.channel, root),
        load_pattern(pattern_id, root), root=root,
        embed=make_embedder(root, a.query_vectors),
        frame=meme_box(plan),
        geometry=placement_geometry(plan),  # CF-0404
        plan_degraded=plan.get("degraded_blocks"),
        work_dir=Path(a.plan).resolve().parent)
    if a.write:
        apply_to_plan(plan, result)
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps({k: result[k] for k in ("meme_requested", "meme_delivered", "notes")},
                     ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "meme", name="meme_layer.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
