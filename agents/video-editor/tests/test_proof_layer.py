#!/usr/bin/env python3
"""CF-0071: the screenshot proof layer, on a test config with the switch on.

Everything here is a temp factory root under FACTORY_ROOT with the real
spec, the real inserts_lib, a test pattern that allows the layer and a
channel config with `enabled: true, capture_method: headless_browser` (or
rendered_quote) and a two-site publisher pool. The temp root is the
convention this suite shares with the other layers, not a way around a
switch that is off somewhere: inserts/proof.json's exit criterion is proven
on a config these tests own, so that it keeps proving the same thing
whatever any real channel later does with its own switch. Real channel
configs are read, but only as data - see test_layer_off_when_disabled_or_
without_a_method_and_on_for_the_real_channel, which flips a *copy* of the
real switch block to get layer_off and asserts the real block as it stands. The browser is never started: capture_page.
HeadlessCapture takes an injected `fetch_page`/`fetch_robots`/`clock`/`sleep`;
Vision is an injected `text_regions` (in-process) or the PROOF_TEXT_REGIONS_
JSON seam (the build_render_plan.py subprocess). The rendered_quote card is
drawn for real (Pillow, deterministic).

What is checked:
  items 1-4 of the task (54e524b):
  - the proof gate is not inspect_asset(): a 1280x300 header capture passes
    without a subject, without a near-black check and without MIN_SHORT_SIDE
  - a capture that fails legibility is `illegible`, the block is byte-identical
    to the no-proof block, and no rendered_quote is substituted for it
  - the placed block carries contain-on-black with our captions shown (CF-0390;
    hidden under CF-0071), the card's size and its text box, and keeps its own
    asset
  the layer (this part):
  - layer_off on a copy of the real switch block turned off and on one with
    no capture_method, against the real block read back as it stands;
    pattern_refused, fact_not_found in its three causes (CF-0243), the two
    CF-0193 beat outcomes, too_long, no_block
    (3.0s floor and the len/12 rule), source_incomplete
  - the rendered_quote card shows the verbatim text, the outlet/handle and
    the date and nothing else (asserted on the renderer's own bookkeeping)
  - headless mocked: success -> placed by headless_browser; off-pool host,
    robots disallow, timeout, no h1, budget spent -> capture_failed_fell_back
    with telemetry; an X host is never fetched; the per-host rate is honoured
    on a mocked clock
  - provenance and the pair pass the root's check_proof_provenance /
    check_proof_pair; the batch record merges idempotently
  - the same through build_render_plan.py and write_batch_metadata.video_record
  the gating-lines refinement (inserts/proof.json legibility, 2026-09-06):
  - capture_page writes <capture>.proof_text.json {h1, standfirst} beside the
    PNG; the standfirst only on the article_header_with_standfirst region
  - a Variety-shaped header (headline 45-54px, furniture 17/19/23px on the
    delivered frame) is `placed` with a correct `legibility` record; the
    headline under the floor is `illegible` and never substituted; no line
    matching the h1 is `illegible` with gating_lines 0; a misread token
    still gates on the token fraction; a 3-char line never gates; max_lines
    counts gating lines; the standfirst gates only when captured
  - rendered_quote unchanged: every line gates, no furniture
  - every real pattern allows the layer (pattern_refused is a synthetic pattern)
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import copy
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import zlib
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import build_render_plan  # noqa: E402
import capture_page as cp  # noqa: E402
import meme_layer as ml  # noqa: E402
import proof_beat_gate
import proof_layer as pl  # noqa: E402
import render_quote as rq  # noqa: E402
import write_batch_metadata  # noqa: E402

RENDER_SRC = AGENT_ROOT / "render" / "src"
REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "inserts" / "proof.json").exists()), None)
assert REAL_ROOT is not None, "the factory root (inserts/proof.json) is not reachable"
SPEC = json.load(open(REAL_ROOT / "inserts" / "proof.json"))


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def png(path, w, h, rgb=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def channel_list(root, channel):
    """CF-0630: where a channel's rights-holder list lives in a stand-in root
    (`channels/<id>/rights-holder-blacklist.json`, the channel's own data -
    the layers read it through the root's shared/channel_data.py)."""
    d = Path(root) / "channels" / channel
    d.mkdir(parents=True, exist_ok=True)
    return d / "rights-holder-blacklist.json"


def make_root(tmp, capture_method="headless_browser"):
    """A factory root under tmp with the real spec and lib, the real
    patterns (all of which allow the layer since 9f11061), a synthetic
    `refuser` pattern that does not, and a channel with the switch on."""
    root = Path(tmp) / "factory"
    (root / "inserts").mkdir(parents=True)
    shutil.copy(REAL_ROOT / "inserts" / "proof.json", root / "inserts" / "proof.json")
    (root / "shared" / "inserts").mkdir(parents=True)
    shutil.copy(REAL_ROOT / "shared" / "inserts" / "inserts_lib.py",
                root / "shared" / "inserts" / "inserts_lib.py")
    shutil.copytree(REAL_ROOT / "patterns", root / "patterns")
    json.dump({"pattern_id": "refuser", "proof_layer": {"allowed": False, "reason": "test"}},
              open(root / "patterns" / "refuser.json", "w"))
    (root / "channels").mkdir()
    json.dump({"channel_id": "test", "display_name": "Test Channel", "theme": STAND_IN_THEME, "insert_layers": {"proof": {"enabled": True, "capture_method": capture_method,
                                           "reason": "CF-0071 test config"}},
               # CF-0137: the storyboards below are deliberately unfilled
               # blocks, and a block with no picture now refuses the plan
               # unless the channel allows the per-block assetless rung. Test
               # config only - the refusal is pinned in
               # tests/test_assetless_rung_gate.py.
               "assetless_block_rung": {"enabled": True,
                                        "reason": "CF-0137 test config"},
               # CF-0418: a short fixture of proof cards and memes is over half
               # pictures by construction; pinned in tests/test_still_share.py.
               "video_editor": {"max_still_share": 1.0},
               "sources": {"rss": {"feeds": [
                   {"url": "https://variety.com/feed/", "site": "variety.com", "house": "pmc"},
                   {"url": "https://deadline.com/feed/", "site": "deadline.com", "house": "pmc"}]}}},
              open(root / "channels" / "test.json", "w"))
    json.dump({"insert_layers": {"proof": {"enabled": True, "capture_method": None}},
               "assetless_block_rung": {"enabled": True,
                                        "reason": "CF-0137 test config"}},
              open(root / "channels" / "nomethod.json", "w"))
    json.dump({"schema_note": "test", "last_updated": "2026-09-01", "entries": [
        {"rights_holder": "Nintendo / The Pokemon Company", "medium": "games_ip",
         "risk_level": "high", "reason": "test"}]},
        open(channel_list(root, "test"), "w"))
    return root


# hook (3 words) + commentary (10) + payoff (3), one word per 0.5s.
HOOK = "The hook here"
COMMENTARY = "and then the commentary says this is absurd, frankly, again"
PAYOFF = "and the payoff"
WORDS = [{"word": w, "start": round(i * 0.5, 2), "end": round(i * 0.5 + 0.45, 2)}
         for i, w in enumerate((HOOK + " " + COMMENTARY + " " + PAYOFF).replace(",", "").split())]
# "this is absurd" is words 8..10 -> 4.0s..5.45s (blocks 1 and 2 below);
# "frankly, again" is 11..12 -> 5.5..6.45s (block 2 only).

URL = "https://variety.com/2026/tv/news/example-show-renewed-1236000000/"
TEXT = "Example Show renewed for a fifth season"                # 39 chars -> 3.25s
# CF-0243: the anchor is the script's one production fact, in the keys
# CF-0186 fixed. There is no second one and no id - a script carries exactly
# one fact, which is why the request lost `check_id` (CF-0223) and why the
# two proofs below both hang on this beat.
FACT = {"text": "Variety says the show was renewed",
        "beat_text": "this is absurd",
        "on_screen": "Renewed for a fifth season",
        "source_url": URL}
HEADLINE = {"url": URL, "publication": "Variety", "title": "Example Show renewed",
            "published_at": "2026-09-01T10:00:00Z", "handle": None}
POST = {"url": "https://x.com/showrunner/status/1", "publication": None, "title": None,
        "published_at": "2026-09-02", "handle": "@showrunner"}
P1 = {"proof_id": "p1", "verbatim_text": TEXT, "source": HEADLINE,
      "capture_method_hint": None}
P2 = {"proof_id": "p2", "verbatim_text": "again", "source": POST,
      "capture_method_hint": "rendered_quote"}


def script(proofs, fact=FACT):
    """`fact=None` is a script with no production fact at all - the state
    that answered every request `check_not_found` until CF-0243."""
    sc = {"script_id": "s1", "hook": HOOK, "commentary": COMMENTARY, "payoff": PAYOFF,
          "proofs": proofs}
    if fact is not None:
        sc["production_fact"] = dict(fact)
    return sc


def block(start, end, kind="clip", **extra):
    b = {"start": start, "end": end, "intent": f"{start}-{end}",
         "asset": {"kind": kind, **({"src": f"/nowhere/{start}.mp4"} if kind == "clip" else {})}}
    b.update(extra)
    return b


# Block 1 (2.0-5.3, clip) holds the beat's first word at 4.0s; block 2
# (5.3-10.0, procedural) overlaps its last word. Priority says 1 - no M1.
BLOCKS = [block(0.0, 2.0, "still"), block(2.0, 5.3, "clip"), block(5.3, 10.0, "procedural")]

# Heights are fractions of the capture; the mocked header capture is 1280x300,
# contained at 0.84 into 1080x1920: 0.16 x 300 x 0.84 = 40.5px, just over the
# 39px floor. On the 1080x1350 card the same fractions are far above it.
LEGIBLE = [{"text": "Example Show renewed", "height": 0.2}, {"text": "Variety", "height": 0.16}]
# The headline itself under the floor (0.004 x 300 x 0.84 = 1px). A tiny
# furniture line beside a legible headline is not illegible any more.
TINY = [{"text": "Example Show renewed", "height": 0.004}, {"text": "Variety", "height": 0.16}]
H1_TEXT = {"h1": "Example Show renewed", "standfirst": None}


def regions(table):
    return lambda path, level=0: list(table)


def page_ok(url, dest, region):
    png(dest, 1280, 300)
    return {"ok": True, "status": 200, "final_url": url, "h1_text": "Example Show renewed",
            "region": region, "width": 1280, "height": 300}


def capturer(root=None, fetch_page=page_ok, robots=None, clock=None, sleep=None, hosts=None):
    calls = {"pages": [], "sleeps": [], "t": [0.0]}
    hosts = hosts if hosts is not None else ["variety.com", "deadline.com"]

    def fp(url, dest, region):
        calls["pages"].append(url)
        return fetch_page(url, dest, region)

    def clk():
        return calls["t"][0]

    def slp(s):
        calls["sleeps"].append(round(s, 3))
        calls["t"][0] += s
    cap = cp.HeadlessCapture(hosts, fetch_page=fp, fetch_robots=robots or (lambda h: None),
                             clock=clock or clk, sleep=sleep or slp)
    cap.calls = calls
    return cap


def run(proofs, root, blocks=None, channel="test", pattern="explainer", cap=None,
        text_regions=regions(LEGIBLE), work_dir=None, **kw):
    blocks = copy.deepcopy(BLOCKS if blocks is None else blocks)
    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    chan = ml.load_channel(channel, root)
    cap = cap or capturer(root)
    res = pl.plan_proofs(script(proofs), WORDS, blocks, chan, ml.load_pattern(pattern, root),
                         root=root, work_dir=work_dir or Path(root).parent, capturer=cap,
                         text_regions=text_regions, now=lambda: "2026-09-06T12:00:00+00:00", **kw)
    pl.apply_to_blocks(blocks, res)
    res["_blocks"] = blocks
    res["_cap"] = cap
    return res


def outcomes(res):
    return [a["outcome"] for a in res["proof_delivered"]]


def record(res):
    v = {"script_id": "s1", "output_path": "videos/s1.mp4",
         "proof_requested": res["proof_requested"], "proof_delivered": res["proof_delivered"],
         "proofs": res["inserts"], "inserts": res["inserts"]}
    if res.get("telemetry") is not None:
        v["proof_capture_telemetry"] = res["telemetry"]
    return v


# --------------------------------------------------------------------------
# the root's own checks, imported when reachable
# --------------------------------------------------------------------------

def _root_checks():
    path = REAL_ROOT / "tests" / "test_pipeline_contracts.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("test_pipeline_contracts", path)
    mod = importlib.util.module_from_spec(spec)
    # CF-0482: the root file imports its own helpers (_tmproot, CF-0378)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


ROOT_CHECKS = _root_checks()


def check_proof(v, ctx):
    if ROOT_CHECKS is not None:
        ROOT_CHECKS.check_proof_pair(v, ctx)
        ROOT_CHECKS.check_proof_provenance(v, ctx)
        ROOT_CHECKS.check_insert_provenance(v, ctx)
        return
    # Replica for a checkout without tests/: pairs answered in order, placed
    # outcomes carry block/file/method and a record, others carry nothing.
    req, dlv = v["proof_requested"], v["proof_delivered"]
    assert len(req) == len(dlv)
    ids = {r["proof_id"] for r in v["proofs"]}
    for r, a in zip(req, dlv):
        assert a["proof_id"] == r["proof_id"] and a["outcome"] in SPEC["metadata"]["outcomes"]
        if a["outcome"] in SPEC["metadata"]["placed_outcomes"]:
            assert isinstance(a["block_index"], int) and a["file"] and a["proof_id"] in ids
        else:
            assert a["block_index"] is None and a["file"] is None and a["proof_id"] not in ids


# --------------------------------------------------------------------------
# items 1-4 (54e524b): the gate, the composition, the degradation
# --------------------------------------------------------------------------

def test_the_proof_gate_is_not_the_footage_gate():
    """A 1280x300 header capture: short side far under MIN_SHORT_SIDE,
    no subject, letterboxed almost entirely black once contained - passes,
    because none of those is a proof question. Width under 1080 fails, and
    the legibility floor is measured on the delivered framing."""
    with tempfile.TemporaryDirectory() as tmp:
        cap = Path(tmp) / "cap.png"
        png(cap, 1280, 300, (10, 10, 10))
        prov = {"author_or_outlet": "Variety", "source_platform": "publication"}
        gate = lambda *a, **kw: pl.check_proof_gates(*a, proof_text=H1_TEXT, **kw)  # noqa: E731
        ok, failures, leg = gate(cap, prov, text_regions=regions(LEGIBLE))
        assert ok, failures
        # 0.2 x 300 x 0.84375 = 50.6px headline; "Variety" is furniture at 40.5px.
        assert leg == {"gating_min_px": 50.62, "gating_lines": 1, "furniture_min_px": 40.5,
                       "lines_total": 2}, leg
        # 0.06 of 300px = 18px, x (1080/1280) = 15px delivered: under 39px.
        ok, failures, leg = gate(cap, prov, text_regions=regions(
            [{"text": "Example Show renewed", "height": 0.06}]))
        assert not ok and failures[0].startswith("legibility:"), failures
        assert leg["gating_min_px"] == 15.19 and leg["furniture_min_px"] is None, leg
        # The same line on a 1280x1000 capture: 60px x 0.84 = 50px, legible.
        png(cap, 1280, 1000)
        ok, failures, leg = gate(cap, prov, text_regions=regions(
            [{"text": "Example Show renewed", "height": 0.06}]))
        assert ok, failures
        png(cap, 1000, 1000)
        ok, failures, leg = gate(cap, prov, text_regions=regions(LEGIBLE))
        assert not ok and failures[0].startswith("no_upscale:"), failures
        png(cap, 1280, 1000)
        ok, failures, leg = gate(cap, prov, text_regions=regions([]))
        assert not ok and failures[0].startswith("text_present:"), failures
        assert leg == {"gating_min_px": None, "gating_lines": 0, "furniture_min_px": None,
                       "lines_total": 0}, leg
        ok, failures, leg = gate(cap, {"author_or_outlet": "", "source_platform": "x"},
                                 text_regions=regions(LEGIBLE))
        assert not ok and failures[0].startswith("attribution_visible:"), failures
        # An unreadable file measures nothing: no record at all.
        cap.write_bytes(b"not a png")
        ok, failures, leg = gate(cap, prov, text_regions=regions(LEGIBLE))
        assert not ok and leg is None
        # build_render_plan.py reads the same gate and the same numbers.
        assert build_render_plan.check_proof_gates is pl.check_proof_gates
        assert build_render_plan.PROOF_MIN_TEXT_HEIGHT_FRACTION == 39 / 1920


def test_illegible_capture_degrades_the_block_and_is_never_substituted():
    """The page came back and its text is too small: `illegible`, the last
    method named, no file, no rendered_quote tried in its place, and the
    block is byte-identical to the block with no proof at all."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        before = copy.deepcopy(BLOCKS)
        res = run([P1], root, text_regions=regions(TINY))
        assert outcomes(res) == ["illegible"], res["proof_delivered"]
        a = res["proof_delivered"][0]
        assert a["attempted"] == ["headless_browser"] and a["capture_method_used"] == "headless_browser"
        assert a["block_index"] is None and a["file"] is None
        assert res["inserts"] == [] and res["overlays"] == {}
        assert res["_blocks"] == before
        assert any("failed the gate" in n and "legibility" in n for n in res["notes"]), res["notes"]
        assert a["legibility"] == {"gating_min_px": 1.01, "gating_lines": 1,
                                   "furniture_min_px": 40.5, "lines_total": 2}, a
        check_proof(record(res), "illegible")
        # The rendered_quote card failing the gate on a rendered_quote channel: the same.
        root2 = make_root(Path(tmp) / "two", capture_method="rendered_quote")
        res2 = run([P1], root2, text_regions=regions(TINY))
        assert outcomes(res2) == ["illegible"]
        assert res2["proof_delivered"][0]["attempted"] == ["rendered_quote"]
        assert res2["_blocks"] == before


def test_placed_block_is_contain_on_black_with_captions_shown_and_its_asset_kept():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        before = copy.deepcopy(BLOCKS)
        res = run([P1], root)
        assert outcomes(res) == ["placed"], res["proof_delivered"]
        assert res["proof_delivered"][0]["block_index"] == 1, "the beat's first-word block, not M1's procedural one"
        ins = res["_blocks"][1]["insert"]
        assert ins["kind"] == "proof" and ins["fit"] == "contain" and ins["background"] == "black"
        # CF-0390: our captions stay on under the card, and the band needs to
        # know where the card's text is to keep clear of it.
        assert ins["captions"] == "shown" and Path(ins["capture_path"]).exists()
        # The stubbed Vision lines carry a height and no position, so where
        # the text is stays unknown - and unknown is null, never a guess
        # (since CF-0394 the band never reads it anyway). The
        # positioned case is test_text_box_is_the_union_of_the_recognised_lines.
        size = ins["source_size"]
        assert size["width"] > 0 and size["height"] > 0, size
        assert "text_box" in ins and ins["text_box"] is None, ins
        assert ins["capture_method"] == "headless_browser" and ins["source_url"] == URL
        assert ins["author_or_outlet"] == "Variety" and ins["posted_at"] == HEADLINE["published_at"]
        for i, b in enumerate(res["_blocks"]):
            stripped = {k: v for k, v in b.items() if k != "insert"}
            assert stripped == before[i], (i, b)
            assert (i == 1) == ("insert" in b)
        # Applying a result to a plan is idempotent and touches nothing else.
        plan = {"blocks": copy.deepcopy(BLOCKS), "words": WORDS}
        pl.apply_to_plan(plan, res)
        once = copy.deepcopy(plan)
        pl.apply_to_plan(plan, res)
        assert plan == once
        assert plan["proof"]["proof_delivered"] == res["proof_delivered"]
        assert plan["proof"]["proof_capture_telemetry"] == res["telemetry"]


# --------------------------------------------------------------------------
# the refusals decided before any capture
# --------------------------------------------------------------------------



def test_pattern_refused_on_a_pattern_that_does_not_allow_it_and_every_real_one_allows():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([P1], root, pattern="refuser")
        assert outcomes(res) == ["pattern_refused"]
        assert res["_cap"].calls["pages"] == []
        res = run([P1], root, pattern="no-such-pattern")
        assert outcomes(res) == ["pattern_refused"]
        check_proof(record(res), "refused")
        # 9f11061: every real pattern carries proof_layer.allowed: true with a
        # reason, so pattern_refused never happens on them - contrast included.
        real = sorted(p.stem for p in (REAL_ROOT / "patterns").glob("*.json")
                      if "proof_layer" in json.loads(p.read_text()))
        assert {"contrast", "explainer", "list", "moment-breakdown"} <= set(real), real
        for pid in real:
            cfg = ml.load_pattern(pid, root)
            assert pl.pattern_allows(cfg) and cfg["proof_layer"]["reason"], pid
            assert outcomes(run([P1], root, pattern=pid)) == ["placed"], pid


def test_fact_not_found_beat_outcomes_too_long_and_source_incomplete():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)

        def with_fact(fact, words=WORDS):
            return pl.plan_proofs(script([P1], fact=fact), words, copy.deepcopy(BLOCKS),
                                  ml.load_channel("test", root),
                                  ml.load_pattern("explainer", root),
                                  root=root, work_dir=tmp, capturer=capturer(),
                                  text_regions=regions(LEGIBLE))

        # CF-0243, the three ways the anchor is absent. One code, because the
        # question is one; the cause named on the record, because a refusal
        # that does not say what to fix is the silence CF-0193 was filed over.
        for fact, missing in ((None, "production_fact"),
                              ({k: v for k, v in FACT.items() if k != "source_url"}, "source_url"),
                              ({**FACT, "source_url": "  "}, "source_url"),
                              ({k: v for k, v in FACT.items() if k != "beat_text"}, "beat_text"),
                              ({**FACT, "beat_text": ""}, "beat_text")):
            res = with_fact(fact)
            assert outcomes(res) == ["fact_not_found"], (missing, res["proof_delivered"])
            ans = res["proof_delivered"][0]
            assert ans["evidence"]["missing"] == missing, ans
            assert ans["attempted"] == [] and ans["capture_method_used"] is None
            sf = res["proof_shortfalls"][0]
            assert sf["code"] == "fact_not_found" and sf["decision"] == pl.DECISION_REFUSE
            assert missing in sf["note"] and sf["note"].strip(), sf
            assert "check_id" not in sf, "CF-0223 deleted the id; nothing writes it back"
            assert proof_beat_gate.refusals(res["proof_shortfalls"]) == [sf]
        # And the one that matters most: a script with no fact is never filed
        # as a beat the video does not say (CF-0243 item 3). `beat_missing_
        # in_script` is a statement about the narration and there was no beat
        # to look for.
        assert outcomes(with_fact(None)) != ["beat_missing_in_script"]

        res = run([P1], root)  # sanity: the same request otherwise places
        assert outcomes(res) == ["placed"]
        # CF-0193: the fact exists and its beat cannot be located - and the
        # two reasons for that are not one outcome any more.
        def with_beat(beat, words=WORDS):
            fact = {**FACT, "beat_text": beat}
            return pl.plan_proofs(script([P1], fact=fact), words, copy.deepcopy(BLOCKS),
                                  ml.load_channel("test", root),
                                  ml.load_pattern("explainer", root),
                                  root=root, work_dir=tmp, capturer=capturer(),
                                  text_regions=regions(LEGIBLE))

        # (a) nothing in the script says this: nothing downstream can fix it.
        res = with_beat("words nobody spoke here")
        assert outcomes(res) == ["beat_missing_in_script"]
        sf = res["proof_shortfalls"]
        assert [s["code"] for s in sf] == ["beat_missing_in_script"]
        assert sf[0]["decision"] == pl.DECISION_REFUSE and sf[0]["proof_id"] == "p1"
        assert res["proof_not_delivered"] == "beat_missing_in_script"
        assert res["proof_delivered_fully"] is False

        # (b) the script says it word for word and the alignment does not have
        # it - ours, and the record has to carry enough to check that claim.
        res = with_beat("this is absurd", words=WORDS[:3])
        assert outcomes(res) == ["beat_unmatched_in_alignment"]
        ev = res["proof_delivered"][0]["evidence"]
        assert ev["in_script_coverage"] == 1.0
        assert ev["searched"].startswith("this is absurd")
        assert ev["nearest"]["text"], "a diagnosis with no nearest fragment is unverifiable"
        assert res["proof_shortfalls"][0]["decision"] == pl.DECISION_SHIP
        assert proof_beat_gate.refusals(res["proof_shortfalls"]) == []
        assert proof_beat_gate.judge(res["proof_requested"],
                                     res["proof_delivered"])["passed"] is True

        # (c) and a beat that IS located still leaves the three fields clean.
        ok = run([P1], root)
        assert ok["proof_delivered_fully"] is True and ok["proof_not_delivered"] is None
        assert ok["proof_shortfalls"] == []
        long = "x" * (SPEC["script_contract"]["max_verbatim_chars"] + 1)
        res = run([{**P1, "verbatim_text": long}], root)
        assert outcomes(res) == ["too_long"]
        res = run([{**P1, "source": {**HEADLINE, "publication": None}}], root)
        assert outcomes(res) == ["source_incomplete"]
        res = run([{**P1, "source": {**HEADLINE, "published_at": None}}], root)
        assert outcomes(res) == ["source_incomplete"]
        assert res["_cap"].calls["pages"] == [], "nothing was fetched for an unattributable proof"
        for a in res["proof_delivered"]:
            assert a["attempted"] == [] and a["capture_method_used"] is None
        check_proof(record(res), "incomplete")
        res = run([{**P1, "source": {**HEADLINE, "url": "not a url"}}], root)
        assert outcomes(res) == ["source_incomplete"]


def test_no_block_under_the_floor_and_under_the_reading_time_and_the_second_priority():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        # Every block under 3.0s: nowhere.
        short = [block(0, 2.0, "still"), block(2.0, 4.9), block(4.9, 7.8), block(7.8, 10.0)]
        res = run([P1], root, blocks=short)
        assert outcomes(res) == ["no_block"], res["proof_delivered"]
        # Block 1 (3.3s) holds the beat's first word and 39 chars need 3.25s: block 1.
        res = run([P1], root)
        assert res["proof_delivered"][0]["block_index"] == 1
        res = run([{**P1, "verbatim_text": TEXT + " and more, per sources say"}], root)  # 65 -> 5.42s
        assert outcomes(res) == ["no_block"], "block 2 (4.7s) is under 5.42s too"
        res = run([{**P1, "verbatim_text": TEXT + " at FX"}], root)  # 45 -> 3.75s
        assert res["proof_delivered"][0]["block_index"] == 2, "block 1 (3.3s) is under 3.75s, block 2 is not"
        assert res["_blocks"][2]["insert"]["placed_by"].startswith("fact's beat")
        # CF-0244: there is no rung under the beat. Block 0 lasts 3.9s and its
        # narration quotes the verbatim text exactly, and it is still not a
        # candidate - it is the hook, which `placement.priority` has always
        # refused, and the rung that used to reach for it put `widows-bay`'s
        # document on block 0, 26s before the fact is spoken and nowhere near
        # the fact's line: a full-frame capture with nothing under it, which
        # the QC gate read as a black screen.
        blocks = [block(0, 3.9, "still"), block(3.9, 5.0), block(5.0, 6.5, "procedural"),
                  block(6.5, 10.0, "procedural")]
        res = run([{**P1, "verbatim_text": "The hook here"}], root, blocks=blocks)
        assert outcomes(res) == ["no_block"], "a block that quotes the wording is not the beat's"
        assert all(b.get("insert") is None for b in res["_blocks"]), res["_blocks"]
        res = run([{**P1, "verbatim_text": "words nobody says"}], root, blocks=blocks)
        assert outcomes(res) == ["no_block"], "M1 does not apply: the long procedural block is not a candidate"
        # A block already carrying an insert is not a candidate either.
        taken = copy.deepcopy(BLOCKS)
        taken[1]["insert"] = {"kind": "meme"}
        res = run([P1], root, blocks=taken)
        assert res["proof_delivered"][0]["block_index"] == 2
        # The ceiling: two placed, a third request is not even requested.
        res = run([P1, P2, {**P1, "proof_id": "p3"}], root)
        assert len(res["proof_requested"]) == 2 and any("only the first 2" in n for n in res["notes"])


# --------------------------------------------------------------------------
# rendered_quote
# --------------------------------------------------------------------------

def test_rendered_quote_card_shows_the_attribution_and_nothing_else():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "card.png"
        info = rq.render_quote_card(TEXT, "Variety", "2026-09-01T10:00:00Z", out,
                                    theme=STAND_IN_THEME)
        roles = [ln["role"] for ln in info["lines"]]
        assert set(roles) == {"verbatim", "author_or_outlet", "posted_at"}, roles
        assert roles.count("author_or_outlet") == 1 and roles.count("posted_at") == 1
        drawn = " ".join(ln["text"] for ln in info["lines"] if ln["role"] == "verbatim")
        assert drawn == TEXT, "the quotation is drawn verbatim, unedited"
        assert [ln["text"] for ln in info["lines"] if ln["role"] == "author_or_outlet"] == ["Variety"]
        assert [ln["text"] for ln in info["lines"] if ln["role"] == "posted_at"] == ["2026-09-01"]
        assert info["width"] == 1080 and info["height"] == 1350
        # Sized for the gate as it measures: every line boxes above the floor.
        assert all(ln["box"][3] - ln["box"][1] >= pl.LEGIBILITY_FLOOR_PX for ln in info["lines"])
        assert len([ln for ln in info["lines"] if ln["role"] == "verbatim"]) <= SPEC["legibility"]["max_lines"]
        from PIL import Image
        im = Image.open(out)
        assert im.size == (1080, 1350)
        bg = tuple(int(info["theme"]["bg"][i:i + 2], 16) for i in (1, 3, 5))
        assert im.getpixel((5, 5)) == bg and im.getpixel((1074, 1344)) == bg, "our background, no frame"
        # CF-0572: the channel's theme, not a palette of the renderer's own.
        assert info["theme"]["accent"] == STAND_IN_THEME["accent"]
        assert info["theme"]["bg"] == STAND_IN_THEME["bg"]
        first = out.read_bytes()
        rq.render_quote_card(TEXT, "Variety", "2026-09-01T10:00:00Z", out, theme=STAND_IN_THEME)
        assert out.read_bytes() == first, "deterministic"
        # A post: the handle is the author line.
        info = rq.render_quote_card("again", "@showrunner", "2026-09-02", out,
                                    theme=STAND_IN_THEME)
        assert [ln["text"] for ln in info["lines"]] == ["again", "@showrunner", "2026-09-02"]
        for args, reason in ((("", "Variety", "2026-09-01"), "source_incomplete"),
                             ((TEXT, "", "2026-09-01"), "source_incomplete"),
                             ((TEXT, "Variety", None), "source_incomplete"),
                             (("x" * 73, "Variety", "2026-09-01"), "too_long")):
            try:
                rq.render_quote_card(*args, out, theme=STAND_IN_THEME)
            except rq.QuoteError as e:
                assert e.reason == reason, (args, e.reason)
            else:
                raise AssertionError(f"{args} rendered")
        # CF-0572: no theme, or half of one, is no card - never a default.
        for theme in (None, {"bg": "#000000", "text": "#FFFFFF"}):
            try:
                rq.render_quote_card(TEXT, "Variety", "2026-09-01", out, theme=theme)
            except rq.QuoteError as e:
                assert e.reason == "no_theme", e.reason
            else:
                raise AssertionError(f"a card was drawn with theme {theme!r}")


def test_rendered_quote_is_drawn_in_the_channels_theme():
    """CF-0572: the layer hands the renderer the theme of the channel it plans
    for (its config's `theme`, without picked/note); a channel config without
    one hands it None, which the real renderer refuses (no_theme) - no card in
    somebody else's colours."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, capture_method="rendered_quote")
        seen = []

        def renderer(text, author, posted, dest, theme=None):
            seen.append(theme)
            return rq.render_quote_card(text, author, posted, dest, theme=theme)

        res = run([P1], root, quote_renderer=renderer)
        assert outcomes(res) == ["placed"], res["proof_delivered"]
        assert seen == [STAND_IN_THEME], seen
        cfg_path = Path(root) / "channels" / "test.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["theme"] = {**cfg["theme"], "note": "kept out of the card", "picked": ["muted"]}
        cfg_path.write_text(json.dumps(cfg))
        seen.clear()
        run([P1], root, quote_renderer=renderer)
        assert seen == [STAND_IN_THEME], seen
        del cfg["theme"]
        cfg_path.write_text(json.dumps(cfg))
        seen.clear()
        res = run([P1], root, quote_renderer=renderer)
        assert seen == [None] and outcomes(res) != ["placed"], (seen, outcomes(res))
        assert any("theme" in n for n in res["notes"]), res["notes"]


def test_rendered_quote_channel_and_a_post_never_reach_the_browser():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, capture_method="rendered_quote")
        res = run([P1, P2], root)
        assert outcomes(res) == ["placed", "placed"], res["proof_delivered"]
        assert res["_cap"].calls["pages"] == [] and res["telemetry"] is None
        for a in res["proof_delivered"]:
            assert a["attempted"] == ["rendered_quote"] and a["capture_method_used"] == "rendered_quote"
        assert [a["block_index"] for a in res["proof_delivered"]] == [1, 2]
        recs = {r["proof_id"]: r for r in res["inserts"]}
        assert recs["p1"]["source_platform"] == "publication" and recs["p1"]["author_or_outlet"] == "Variety"
        assert recs["p2"]["source_platform"] == "x" and recs["p2"]["author_or_outlet"] == "@showrunner"
        assert recs["p2"]["rights_holder"] == "@showrunner" and recs["p2"]["still_live"] is True
        assert recs["p1"]["claim_supported"] == FACT["text"]
        assert recs["p1"]["captured_at"] == "2026-09-06T12:00:00+00:00"
        assert Path(root).parent.joinpath(recs["p1"]["file"]).exists()
        check_proof(record(res), "quote")
        # On the headless channel a post, or a writer's hint, enters at rendered_quote.
        root2 = make_root(Path(tmp) / "two")
        res = run([P2, {**P1, "capture_method_hint": "rendered_quote"}], root2)
        assert outcomes(res) == ["placed", "placed"]
        assert res["_cap"].calls["pages"] == []
        assert all(a["attempted"] == ["rendered_quote"] for a in res["proof_delivered"])
        check_proof(record(res), "hinted")


def test_the_author_is_checked_against_the_channels_own_list_and_never_gates():
    """CF-0630: the proof's author is checked against the rights-holder list
    of the channel the proof is planned for (`channels/<id>/rights-holder-
    blacklist.json`). The check is recorded and never gates - as before the
    list moved - so a channel with no list of its own still gets its proof,
    with a record saying the check was not applied and why; the old common
    path is not read."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([P1], root)
        chk = res["inserts"][0]["blacklist_check"]
        assert chk["applied"] is True and chk["blacklist_updated"] == "2026-09-01", chk
        channel_list(root, "test").unlink()
        json.dump({"schema_note": "test", "last_updated": "2026-01-01", "entries": []},
                  open(root / "shared" / "rights-holder-blacklist.json", "w"))
        res = run([P1], root)
        assert outcomes(res) == ["placed"]
        chk = res["inserts"][0]["blacklist_check"]
        assert chk["applied"] is False and chk["skip"] is False, chk
        assert "'test'" in chk["reason"] and "rights-holder-blacklist.json" in chk["reason"], chk

# --------------------------------------------------------------------------
# headless_browser, mocked
# --------------------------------------------------------------------------

def test_headless_success_is_placed_with_telemetry_and_the_records_pass_the_root_check():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([P1], root)
        assert outcomes(res) == ["placed"]
        a = res["proof_delivered"][0]
        assert a["capture_method_used"] == "headless_browser" and a["attempted"] == ["headless_browser"]
        assert a["file"] == "proof-p1-headless_browser.png"
        assert res["_cap"].calls["pages"] == [URL]
        assert res["telemetry"] == {"requests_by_host": {"variety.com": 1}, "fetch_failures": []}
        r = res["inserts"][0]
        for key in SPEC["provenance"]["required"]:
            assert key in r, key
        assert r["capture_method"] == "headless_browser" and r["still_live"] is True
        assert r["kind"] == "proof" and r["id"] == "p1" and r["licence"] is None and r["skipped"] is False
        assert r["blacklist_check"]["skip"] is False
        check_proof(record(res), "headless")


def test_fetch_failures_fall_back_to_rendered_quote_with_the_reason_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        cases = {
            "host_not_allowed": (P1 | {"source": HEADLINE | {"url": "https://hollywoodreporter.com/x/"}}, None, None),
            "robots_disallowed": (P1, None, lambda h: "User-agent: *\nDisallow: /2026/\n"),
            "timeout": (P1, lambda u, d, r: {"ok": False, "reason": "timeout"}, None),
            "no_h1": (P1, lambda u, d, r: {"ok": False, "reason": "no_h1", "status": 200}, None),
            "http_403": (P1, lambda u, d, r: {"ok": False, "reason": "http_403", "status": 403}, None),
            "redirect_off_pool": (P1, lambda u, d, r: page_ok(u, d, r) | {"final_url": "https://login.example.com/"}, None),
        }
        for reason, (proof, fp, robots) in cases.items():
            cap = capturer(fetch_page=fp or page_ok, robots=robots)
            res = run([proof], root, cap=cap)
            assert outcomes(res) == ["capture_failed_fell_back"], (reason, res["proof_delivered"])
            a = res["proof_delivered"][0]
            assert a["attempted"] == ["headless_browser", "rendered_quote"], reason
            assert a["capture_method_used"] == "rendered_quote" and a["file"] == "proof-p1-rendered_quote.png"
            tel = res["telemetry"]
            assert tel["fetch_failures"] == [{"url": proof["source"]["url"], "reason": reason}], (reason, tel)
            fetched = reason not in ("host_not_allowed", "robots_disallowed")
            assert (cap.calls["pages"] != []) == fetched, reason
            assert (tel["requests_by_host"] != {}) == fetched, reason
            assert res["inserts"][0]["capture_method"] == "rendered_quote"
            check_proof(record(res), reason)
        # Budget spent: the 21st request to one host is refused without a fetch.
        cap = capturer()
        cap.telemetry["requests_by_host"]["variety.com"] = SPEC["capture_methods"][0]["behaviour"]["max_requests_per_host_per_batch"]
        res = run([P1], root, cap=cap)
        assert outcomes(res) == ["capture_failed_fell_back"]
        assert res["telemetry"]["fetch_failures"][-1]["reason"] == "host_budget_spent"
        assert cap.calls["pages"] == []
        # A rendered_quote channel has no next method: a fetch failure there
        # cannot happen (nothing is fetched), and a card that cannot be built
        # is capture_failed with the method named.
        res = run([P1], root, cap=capturer(), quote_renderer=lambda *a, **k: (_ for _ in ()).throw(OSError("disk")),
                  text_regions=regions(LEGIBLE))
        # headless succeeded, so the renderer was never needed: placed.
        assert outcomes(res) == ["placed"]
        res = run([P1], root, cap=capturer(fetch_page=lambda u, d, r: {"ok": False, "reason": "timeout"}),
                  quote_renderer=lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
        assert outcomes(res) == ["capture_failed"]
        a = res["proof_delivered"][0]
        assert a["attempted"] == ["headless_browser", "rendered_quote"] and a["capture_method_used"] == "rendered_quote"
        check_proof(record(res), "failed")




def test_rate_limit_and_one_attempt_per_url_on_a_mocked_clock():
    with tempfile.TemporaryDirectory() as tmp:
        cap = capturer()
        gap = SPEC["capture_methods"][0]["behaviour"]["min_seconds_between_requests_per_host"]
        assert cap.capture(URL, Path(tmp) / "a.png").ok
        assert cap.calls["sleeps"] == []
        # Second request to the same host 0.5s later: waits the remaining 1.5s.
        cap.calls["t"][0] += 0.5
        r = cap.capture(URL.replace("1236000000", "1236000001"), Path(tmp) / "b.png")
        assert r.ok and cap.calls["sleeps"] == [round(gap - 0.5, 3)], cap.calls["sleeps"]
        # A different host waits for nothing.
        assert cap.capture("https://deadline.com/2026/x/", Path(tmp) / "c.png").ok
        assert len(cap.calls["sleeps"]) == 1
        assert cap.telemetry["requests_by_host"] == {"variety.com": 2, "deadline.com": 1}
        # The same URL again: one attempt per URL, no fetch, recorded.
        cap.calls["t"][0] += 10
        r = cap.capture(URL, Path(tmp) / "d.png")
        assert not r.ok and r.reason == "url_already_attempted" and len(cap.calls["pages"]) == 3
        # robots.txt is read once per host, under the honest UA's `*` rules.
        seen = []
        cap = capturer(robots=lambda h: seen.append(h) or "User-agent: *\nDisallow: /2026/tv/\n")
        assert cap.capture(URL, Path(tmp) / "e.png").reason == "robots_disallowed"
        assert cap.capture("https://variety.com/2025/film/x/", Path(tmp) / "f.png").ok
        assert seen == ["variety.com"]
        assert cp.PROOF_USER_AGENT.startswith("shorts-content-factory/") and "Mozilla" not in cp.PROOF_USER_AGENT


# --------------------------------------------------------------------------
# the plan and the batch record
# --------------------------------------------------------------------------

def _silent_wav(path, seconds=10.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


# CF-0244: the end-to-end fixture's fact and proof, sized so the card has a
# line to live under and the line leaves before the block does - the shape
# the window exists for.
#
# The arithmetic, because every number here is load-bearing. The beat is
# words 4..9 of the same script, 2.00-4.95s, so comparison_line.py mounts its
# line 1.62-5.19s (0.38s in, 0.24s out). The proof lands on block 1, 2.0-5.3s.
# The card is therefore up 2.00-5.19s - 3.19s, over the 3.00s floor that a
# 20-character verbatim asks for - and the block's own procedural asset has
# the frame back for its last 0.11s with our captions on top of it.
#
# `FACT`'s own beat is three words (4.00-5.45s), which no card could sit
# under; the unit fixtures above keep it, because there it is only ever a
# span to place a block against.
E2E_FACT = {**FACT, "beat_text": "then the commentary says this is"}
E2E_P1 = {**P1, "verbatim_text": "Example Show renewed"}   # 20 chars -> 1.67s


def test_build_render_plan_carries_the_proof_and_the_meme_yields_to_it(
        proofs=None, fact=E2E_FACT, expect_refusal=False):
    """Through the real script on a rendered_quote channel (no browser):
    the placed block keeps its own asset and gains `insert`; plan["proof"]
    carries the pair; stderr says PROOF p1: placed; a meme on the same beat
    lands on the other block. Vision is the PROOF_TEXT_REGIONS_JSON seam."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = make_root(tmp, capture_method="rendered_quote")
        # The meme layer needs its spec, lib folder and switch on the same root.
        shutil.copy(REAL_ROOT / "inserts" / "meme.json", root / "inserts" / "meme.json")
        (root / "shared" / "inserts" / "memes").mkdir(parents=True)
        json.dump({"schema_note": "test", "kind": "meme", "embedding_model": "fake", "entries": []},
                  open(root / "shared" / "inserts" / "memes" / "index.json", "w"))
        chan = json.load(open(root / "channels" / "test.json"))
        chan["insert_layers"]["meme"] = {"enabled": True, "reason": "test"}
        # CF-0164: the source badge names the publication behind the fact's
        # `source_url`, and a host it cannot name stops the plan rather than
        # inventing a name from the domain. The comparison line reads the same
        # `production_fact` the proof layer now does (CF-0243), so the channel
        # has to say what to call its host - the operator's answer to that
        # refusal, and the reason this block is here.
        chan.setdefault("video_editor", {})["comparison_line"] = {
            "publishers": {"variety.com": "Variety", "x.com": "X"}}
        json.dump(chan, open(root / "channels" / "test.json", "w"))
        pat = json.load(open(root / "patterns" / "explainer.json"))
        pat["meme_layer"] = {"allowed": True, "reason": "test"}
        json.dump(pat, open(root / "patterns" / "explainer.json", "w"))
        _silent_wav(tmp / "voice.wav")
        (tmp / "words.json").write_text(json.dumps(WORDS))
        sc = script(proofs or [E2E_P1], fact=fact)
        sc["reactions"] = [{"beat_id": "r1", "intent": "facepalm", "beat_text": "this is absurd",
                            "query": None}]
        (tmp / "03.json").write_text(json.dumps({"scripts": [sc]}))
        (tmp / "regions.json").write_text(json.dumps({"proof-p1-rendered_quote.png": LEGIBLE}))
        (tmp / "vectors.json").write_text(json.dumps({}))
        sb = [
            {"word_range": [0, 0], "intent": "count card", "asset_kind": "card",
             "card": {"kind": "count_card", "text": "3"}, "emphasis_words": [],
             "rhythm_role": "opening_card", "side": None, "shot": None, "held_frame": False,
             "_start": 0.0, "_end": 2.0},
            {"word_range": [4, 4], "intent": "step", "asset_kind": "typographic",
             "unfilled_reason": "no shot in any index", "emphasis_words": [],
             "rhythm_role": "beat", "side": None, "shot": None, "held_frame": False,
             "_start": 2.0, "_end": 5.3},
            {"word_range": [10, 10], "intent": "step", "asset_kind": "typographic",
             "unfilled_reason": "no shot in any index", "emphasis_words": [],
             "rhythm_role": "beat", "side": None, "shot": None, "held_frame": False,
             "_start": 5.3, "_end": 10.0},
        ]
        story = {"script_id": "s1", "style": "motion", "resolved_from_anchors": True,
                 "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "hold",
                            "rhythm_built": "hold",
                            "parameters": {"block_count": 3, "key_frame_hold_seconds": 4.0},
                            "opening_requested": "count_card", "opening_delivered": "count_card",
                            "anchor_count": 3},
                 "blocks": sb, "unresolved_anchors": [], "rejected_candidates": []}
        (tmp / "storyboard.json").write_text(json.dumps(story))
        out = tmp / "plan.json"
        env = dict(os.environ, FACTORY_ROOT=str(root), PROOF_TEXT_REGIONS_JSON=str(tmp / "regions.json"))
        cmd = [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
               str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
               "--style", "motion", "--target-duration", "1", "60",
               "--script", str(tmp / "03.json"), "--script-id", "s1",
               "--channel", str(root / "channels" / "test.json"),
               "--query-vectors", str(tmp / "vectors.json")]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp, env=env, timeout=120)
        if expect_refusal:
            # CF-0193 rung 4: the plan is not written, the reason is on stderr
            # in a closed code, and the deficit beside where the plan would
            # have been carries the same record for a reader who is not
            # parsing stderr (CF-0118 / CF-0137's move).
            assert result.returncode == 2, result.stderr[-2000:]
            assert not out.exists(), "a refused plan must not be written"
            assert "PROOF REQUEST POINTS AT NOTHING" in result.stderr, result.stderr[-1500:]
            deficit = json.loads((tmp / "plan.proof-beat.json").read_text())
            assert deficit["proof_delivered_fully"] is False
            assert deficit["proof_not_delivered"] == "beat_missing_in_script"
            sf = deficit["proof_shortfalls"]
            assert [x["code"] for x in sf] == ["beat_missing_in_script"]
            assert sf[0]["decision"] == "refuse" and sf[0]["attempted"] == []
            return None
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        # CF-0193: the three fields ride beside the pair on every plan, and a
        # video whose proof is on the screen says so with no code.
        assert plan["proof"]["proof_delivered_fully"] is True
        assert plan["proof"]["proof_not_delivered"] is None
        assert plan["proof"]["proof_shortfalls"] == []
        pair = plan["proof"]
        assert [a["outcome"] for a in pair["proof_delivered"]] == ["placed"], pair
        placed = pair["proof_delivered"][0]
        assert placed["block_index"] == 1 and placed["capture_method_used"] == "rendered_quote"
        assert placed["file"] == "proof-p1-rendered_quote.png" and (tmp / placed["file"]).exists()
        b = plan["blocks"][1]
        assert b["asset"] == {"kind": "procedural"}, "the block's own asset is untouched"
        assert b["insert"]["kind"] == "proof" and b["insert"]["captions"] == "shown"
        assert b["insert"]["capture_path"] == str((tmp / placed["file"]).resolve())
        # CF-0244: the card's window is on the plan, and it is the part of the
        # block the fact's line covers - not the block. The block runs to 5.3s
        # and the line leaves at 5.19s, so the card leaves with it.
        line = plan["comparison_lines"][0]
        assert b["insert"]["window_from"] == "fact line"
        assert b["insert"]["start_s"] == max(b["start"], line["start_s"])
        assert b["insert"]["end_s"] == min(b["end"], line["end_s"]) < b["end"], (
            b["insert"], line, b["end"])
        assert any("card up" in n and "CF-0244" in n for n in plan["proof"]["notes"])
        assert "insert" not in plan["blocks"][0]
        assert pair["proof_capture_telemetry"] is None and pair["storyboard_inserts"] == []
        assert "PROOF p1: placed - rendered_quote on block 1" in result.stderr, result.stderr[-800:]
        # The meme's beat is the same words; block 1 is taken, the library is
        # empty, so it answers no_asset rather than displacing the proof.
        assert [a["outcome"] for a in plan["meme"]["meme_delivered"]] == ["no_asset"], plan["meme"]
        check_proof({"proof_requested": pair["proof_requested"], "proof_delivered": pair["proof_delivered"],
                     "proofs": pair["proofs"], "inserts": pair["proofs"]}, "plan")
        # The same plan without --script: the empty pair, nothing else different.
        out2 = tmp / "plan2.json"
        # CF-0137: --channel has to survive the truncation. It is not part of
        # what this line drops (the script, which is what the proof layer
        # reads); it is what allows the unfilled blocks of this storyboard to
        # be planned at all.
        result = subprocess.run(
            cmd[:cmd.index("--script")]
            + ["--channel", str(root / "channels" / "test.json")],
            capture_output=True, text=True, cwd=tmp, env=env, timeout=120)
        assert result.returncode == 0, result.stderr[-2000:]
        plan2 = json.loads(out2.read_text()) if out2.exists() else json.loads(out.read_text())
        assert plan2["proof"]["proof_requested"] == [] and plan2["proof"]["proof_delivered"] == []
        assert plan2["proof"]["proofs"] == []
        stripped = [{k: v for k, v in blk.items() if k != "insert"} for blk in plan["blocks"]]
        assert stripped == plan2["blocks"]
        return plan


def test_the_ladder_refuses_a_plan_whose_proof_points_at_nothing():
    """CF-0193 item 4, end to end. The fact is real, its beat is a sentence
    the video never says: no rung below can supply it, so build_render_plan.py
    refuses instead of shipping a video with `attempted: []` and a note."""
    # Rewriting the fact's beat is what makes it unfindable (CF-0243: the
    # fact is the anchor, so this is where an unsayable beat now comes from).
    bad = {**FACT, "beat_text": "a sentence this narration never says at all"}
    test_build_render_plan_carries_the_proof_and_the_meme_yields_to_it(
        fact=bad, expect_refusal=True)


def test_write_batch_metadata_writes_the_pair_and_merges_idempotently():
    plan = test_build_render_plan_carries_the_proof_and_the_meme_yields_to_it()
    qc = {"passed": True, "failures": [], "notes": []}
    v = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion")
    assert v["proof_requested"] == plan["proof"]["proof_requested"]
    assert v["proof_delivered"] == plan["proof"]["proof_delivered"]
    assert [r["proof_id"] for r in v["proofs"]] == ["p1"]
    assert "proof_capture_telemetry" not in v, "only when headless_browser was attempted"
    assert v["assets"][1]["insert"] == "proof"
    check_proof(v, "s1")
    # Idempotent: the record's own inserts fed back produce the same inserts.
    v2 = write_batch_metadata.video_record("s1", plan, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=v["inserts"])
    assert v2["inserts"] == v["inserts"]
    # Another layer's records survive (the meme layer replaces its own the
    # same way, and this plan placed no meme); a stale proof record does not.
    # CF-0127: the plan handed in for this one is this plan without its
    # `underlay` key - a plan that *ran* the underlay layer answers for it
    # and replaces its records, so only a plan that did not (every plan
    # before that wiring) makes an underlay record foreign provenance.
    other = {"kind": "loop", "id": "loop-1", "file": "l.mp4", "source_url": "https://x",
             "rights_holder": "y", "licence": None, "blacklist_check": {"skip": False},
             "skipped": False, "block": None, "layer": "underlay", "applied": True}
    meme = {**other, "kind": "meme", "id": "meme-1", "layer": "meme", "block": 2}
    stale = {**plan["proof"]["proofs"][0], "id": "stale", "proof_id": "stale"}
    no_underlay = {k: val for k, val in plan.items() if k != "underlay"}
    v3 = write_batch_metadata.video_record("s1", no_underlay, "/nowhere/s1.mp4", qc, "motion",
                                           existing_inserts=[other, stale, meme])
    ids = [(r["layer"], r["id"]) for r in v3["inserts"]]
    assert ids == [("underlay", "loop-1"), ("proof", "p1")], ids
    v3b = write_batch_metadata.video_record("s1", no_underlay, "/nowhere/s1.mp4", qc, "motion",
                                            existing_inserts=[other, stale, {**meme, "layer": "sound"}])
    assert [(r["layer"], r["id"]) for r in v3b["inserts"]] == [("underlay", "loop-1"), ("proof", "p1")]
    # With telemetry on the plan, the record carries it.
    with_tel = copy.deepcopy(plan)
    with_tel["proof"]["proof_capture_telemetry"] = {"requests_by_host": {"variety.com": 1},
                                                    "fetch_failures": []}
    v4 = write_batch_metadata.video_record("s1", with_tel, "/nowhere/s1.mp4", qc, "motion")
    assert v4["proof_capture_telemetry"] == with_tel["proof"]["proof_capture_telemetry"]
    check_proof(v4, "s1-tel")
    # A plan built before the layer existed (54e524b's counts): the empty pair.
    old = {k: val for k, val in plan.items() if k != "proof"}
    old["proof"] = {"proof_requested": 0, "proof_delivered": 0, "proofs": []}
    v5 = write_batch_metadata.video_record("s1", old, "/nowhere/s1.mp4", qc, "motion")
    assert v5["proof_requested"] == [] and v5["proof_delivered"] == [] and v5["proofs"] == []
    check_proof(v5, "s1-old")


# --------------------------------------------------------------------------
# part 6: gating lines vs furniture (inserts/proof.json legibility, 2026-09-06)
# --------------------------------------------------------------------------

# A Variety-shaped header capture: 1280x1400 (behaviour's max height), contained
# at 0.84375 into 1080x1920. Heights below are delivered-frame pixels, the
# numbers the first real capture measured: headline 45-54px over the 39px
# floor, masthead furniture 17/19/23px under it.
HDR_W, HDR_H = 1280, 1400
HDR_SCALE = min(1080 / HDR_W, 1920 / HDR_H)
H1 = "Example Show Renewed for a Fifth Season: 'It\u2019s Back'"
STANDFIRST = "The network confirmed the order on Monday, sources say."
HEADLINE_LINES = [("Example Show Renewed for a", 54.0), ("Fifth Season: 'It's Back'", 45.0)]
FURNITURE = [("Subscribe", 17.0), ("TV > News", 19.0), ("Sep 1, 2026 10:00am PT", 23.0),
             ("By A Reporter", 23.0), ("Variety", 31.0)]


def hdr(lines):
    """Regions in the capture's own fractions from delivered-pixel heights."""
    return [{"text": t, "height": h / (HDR_H * HDR_SCALE)} for t, h in lines]


def page_header(standfirst=None):
    def fetch(url, dest, region):
        png(dest, HDR_W, HDR_H, (245, 245, 245))
        return {"ok": True, "status": 200, "final_url": url, "h1_text": H1,
                "standfirst_text": standfirst, "region": region, "width": HDR_W, "height": HDR_H}
    return fetch


def test_header_furniture_is_measured_and_never_gates():
    """The first real capture, replayed: the headline gates and clears the
    floor, the masthead furniture is under it and does not gate - `placed`
    by headless_browser, the sidecar beside the PNG, the record on the answer."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(FURNITURE + HEADLINE_LINES)))
        assert outcomes(res) == ["placed"], res["proof_delivered"]
        a = res["proof_delivered"][0]
        assert a["capture_method_used"] == "headless_browser" and a["attempted"] == ["headless_browser"]
        assert a["legibility"] == {"gating_min_px": 45.0, "gating_lines": 2,
                                   "furniture_min_px": 17.0, "lines_total": 7}, a["legibility"]
        assert not any("legibility" in n for n in res["notes"]), res["notes"]
        # The sidecar: <capture>.proof_text.json beside the PNG, {h1, standfirst}.
        cap = Path(root).parent / a["file"]
        side = cp.proof_text_path(cap)
        assert side.name == "proof-p1-headless_browser.proof_text.json" and side.exists()
        assert json.loads(side.read_text()) == {"h1": H1, "standfirst": None}
        assert res["_cap"].calls["pages"] == [URL], "the gate never re-fetched"
        r = res["inserts"][0]
        assert r["capture_method"] == "headless_browser" and r["file"] == a["file"]
        check_proof(record(res), "header")
        # A seam's capturer that writes no sidecar: the gate reads none, so
        # nothing gates and the capture is illegible rather than passed blind.
        class NoSidecar:
            telemetry = {"requests_by_host": {}, "fetch_failures": []}

            def capture(self, url, dest, region):
                png(dest, HDR_W, HDR_H)
                return cp.CaptureResult(ok=True, reason=None, file=str(dest), region=region)
        res = run([P1], root, cap=NoSidecar(), text_regions=regions(hdr(FURNITURE + HEADLINE_LINES)),
                  work_dir=Path(tmp) / "nosidecar")
        assert outcomes(res) == ["illegible"] and res["proof_delivered"][0]["legibility"]["gating_lines"] == 0


def test_headline_under_the_floor_is_illegible_and_never_substituted():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        before = copy.deepcopy(BLOCKS)
        small = [("Example Show Renewed for a", 38.0), ("Fifth Season: 'It's Back'", 30.0)]
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(FURNITURE + small)))
        assert outcomes(res) == ["illegible"], res["proof_delivered"]
        a = res["proof_delivered"][0]
        assert a["attempted"] == ["headless_browser"] and a["capture_method_used"] == "headless_browser"
        assert a["block_index"] is None and a["file"] is None
        assert a["legibility"] == {"gating_min_px": 30.0, "gating_lines": 2,
                                   "furniture_min_px": 17.0, "lines_total": 7}, a["legibility"]
        assert res["inserts"] == [] and res["_blocks"] == before
        assert any("smallest gating text line is 30.0px" in n for n in res["notes"]), res["notes"]
        check_proof(record(res), "illegible-headline")
        # Furniture the size of a headline changes nothing: still the headline's verdict.
        big_furniture = [(t, 60.0) for t, _ in FURNITURE]
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(big_furniture + small)), work_dir=Path(tmp) / "two")
        assert outcomes(res) == ["illegible"]
        assert res["proof_delivered"][0]["legibility"]["furniture_min_px"] == 60.0


def test_no_line_matching_the_h1_is_illegible_with_zero_gating_lines():
    """Vision read the furniture and not the headline: the machine did not
    read the proof text, so the claim that the viewer can is unsupported."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(FURNITURE)))
        assert outcomes(res) == ["illegible"], res["proof_delivered"]
        a = res["proof_delivered"][0]
        assert a["legibility"] == {"gating_min_px": None, "gating_lines": 0,
                                   "furniture_min_px": 17.0, "lines_total": 5}, a["legibility"]
        assert any("0 of 5 recognised lines match" in n for n in res["notes"]), res["notes"]
        assert res["inserts"] == []
        check_proof(record(res), "no-match")


def test_the_match_rule_substring_token_fraction_min_chars_and_order():
    """line_gates_proof_text: casefold / punctuation / quotes normalised on
    both sides; a substring gates; >= 0.6 of the tokens in order gate (a
    misread token drops that token only); under 4 chars never gates; out of
    order does not gate; the standfirst counts only when the sidecar has it."""
    pt = {"h1": H1, "standfirst": None}
    gates = pl.line_gates_proof_text
    assert gates("EXAMPLE SHOW RENEWED", pt) and gates("its back", pt) and gates("It's Back!", pt)
    assert gates("Example Shaw Renewed for a", pt), "4 of 5 tokens in order: 0.8 >= 0.6"
    assert gates("Fifth Seasan: Its Back", pt), "3 of 4: 0.75"
    assert not gates("Example Shaw Renwed fer a", pt), "2 of 5: 0.4"
    assert not gates("Back Show Example", pt), "in order means in order"
    assert not gates("Subscribe", pt) and not gates("Sep 1, 2026", pt) and not gates("TV > News", pt)
    assert not gates("for", pt) and not gates("TV", pt) and not gates("'a'", pt), "under 4 chars never gates"
    assert gates("Back", pt) and gates("Show", pt), "4 chars is the minimum, not above it"
    assert not gates("Example Show", None) and not gates("Example Show", {"h1": ""})
    assert pl.normalise_proof_text("  It\u2019s \u201cBack\u201d - fifth_season!  ") == "its back fifth season"
    # The standfirst gates only when the sidecar carries it.
    assert not gates("network confirmed the order", pt)
    assert gates("network confirmed the order", {"h1": H1, "standfirst": STANDFIRST})
    assert gates("The netwerk confirmed the order on Monday", {"h1": H1, "standfirst": STANDFIRST})


def test_a_headline_split_across_two_lines_gates_on_the_token_fraction():
    """Vision misread a character in each half of the wrapped headline: both
    halves still gate, the floor is measured on them, the capture is placed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        misread = [("Exarnple Show Renewed for a", 54.0), ("Fifth Season: lt's Back", 45.0)]
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(FURNITURE + misread)))
        assert outcomes(res) == ["placed"], res["proof_delivered"]
        assert res["proof_delivered"][0]["legibility"]["gating_lines"] == 2
        # A three-character line - "for", a word of the h1 - never gates, even
        # at headline size: alone it is 0 gating lines and illegible.
        res = run([P1], root, cap=capturer(root, fetch_page=page_header()),
                  text_regions=regions(hdr(FURNITURE + [("for", 60.0)])), work_dir=Path(tmp) / "two")
        assert outcomes(res) == ["illegible"]
        assert res["proof_delivered"][0]["legibility"] == {
            "gating_min_px": None, "gating_lines": 0, "furniture_min_px": 17.0, "lines_total": 6}
        # max_lines counts gating lines: seven headline fragments is a thread.
        cap = Path(tmp) / "thread.png"
        png(cap, HDR_W, HDR_H)
        prov = {"author_or_outlet": "Variety", "source_platform": "publication"}
        seven = hdr([("Example Show", 50.0)] * 7 + FURNITURE)
        ok, failures, leg = pl.check_proof_gates(cap, prov, text_regions=regions(seven),
                                                 proof_text={"h1": H1, "standfirst": None})
        assert not ok and any("7 gating lines, more than 6" in f for f in failures), failures
        assert leg["gating_lines"] == 7 and leg["lines_total"] == 12
        six = hdr([("Example Show", 50.0)] * 6 + FURNITURE)
        ok, failures, leg = pl.check_proof_gates(cap, prov, text_regions=regions(six),
                                                 proof_text={"h1": H1, "standfirst": None})
        assert ok, failures


def test_the_standfirst_is_in_the_sidecar_only_on_its_own_region():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "a.png"
        cap = capturer(fetch_page=page_header(STANDFIRST))
        res = cap.capture(URL, dest, "article_header")
        assert res.ok and res.proof_text == {"h1": H1, "standfirst": None}
        assert cp.read_proof_text(dest) == {"h1": H1, "standfirst": None}
        res = cap.capture(URL.replace("1236000000", "1236000001"), Path(tmp) / "b.png",
                          "article_header_with_standfirst")
        assert res.ok and res.proof_text == {"h1": H1, "standfirst": STANDFIRST}
        assert json.loads(cp.proof_text_path(Path(tmp) / "b.png").read_text()) == res.proof_text
        assert cp.read_proof_text(Path(tmp) / "none.png") is None
        # Whitespace is collapsed on the way in; an h1 that is empty is no sidecar.
        assert cp.write_proof_text(Path(tmp) / "c.png", "  Two   words \n", None, "article_header") == {
            "h1": "Two words", "standfirst": None}
        assert cp.read_proof_text(Path(tmp) / "c.png") == {"h1": "Two words", "standfirst": None}
        cp.write_proof_text(Path(tmp) / "d.png", "", None, "article_header")
        assert cp.read_proof_text(Path(tmp) / "d.png") is None
        # A fetch failure writes no sidecar.
        cap2 = capturer(fetch_page=lambda u, d, r: {"ok": False, "reason": "no_h1", "status": 200})
        res = cap2.capture(URL, Path(tmp) / "e.png")
        assert not res.ok and res.proof_text is None and not cp.proof_text_path(Path(tmp) / "e.png").exists()


def test_rendered_quote_every_drawn_line_gates_and_there_is_no_furniture():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, capture_method="rendered_quote")
        # The card is 1080x1350, contained at 1.0: fractions x 1350.
        res = run([P1], root, text_regions=regions(
            [{"text": TEXT, "height": 0.05}, {"text": "Variety", "height": 0.04},
             {"text": "2026-09-01", "height": 0.03}]))
        assert outcomes(res) == ["placed"]
        a = res["proof_delivered"][0]
        assert a["capture_method_used"] == "rendered_quote"
        assert a["legibility"] == {"gating_min_px": 40.5, "gating_lines": 3,
                                   "furniture_min_px": None, "lines_total": 3}, a["legibility"]
        check_proof(record(res), "card")
        # The date line under the floor: on a card every line gates, so illegible.
        res = run([P1], root, text_regions=regions(
            [{"text": TEXT, "height": 0.05}, {"text": "Variety", "height": 0.04},
             {"text": "2026-09-01", "height": 0.02}]), work_dir=Path(tmp) / "two")
        assert outcomes(res) == ["illegible"]
        assert res["proof_delivered"][0]["legibility"] == {
            "gating_min_px": 27.0, "gating_lines": 3, "furniture_min_px": None, "lines_total": 3}
        check_proof(record(res), "card-illegible")
        # Fell back from a fetch failure: the record is on that answer too.
        root2 = make_root(Path(tmp) / "three")
        res = run([P1], root2, cap=capturer(root2, fetch_page=lambda u, d, r: {
            "ok": False, "reason": "timeout"}), text_regions=regions(LEGIBLE),
            work_dir=Path(tmp) / "three")
        assert outcomes(res) == ["capture_failed_fell_back"]
        assert res["proof_delivered"][0]["legibility"]["gating_lines"] == 2
        check_proof(record(res), "fell-back")


# --------------------------------------------------------------------------
# CF-0244: the card's window
# --------------------------------------------------------------------------

def carded(block_span, line_span, verbatim=TEXT, url=URL, line_url=None):
    """A plan with one placed card, one fact line, and nothing else that
    bind_to_lines() reads. The spans are the two this layer has to reconcile:
    the block the card sits on and the window the fact's line is mounted for."""
    b0, b1 = block_span
    blocks = [block(0.0, b0, "still"), block(b0, b1, "clip")]
    blocks[1]["insert"] = {"kind": "proof", "proof_id": "p1", "capture_path": "/nowhere/p1.png",
                           "capture_method": "rendered_quote", "fit": "contain",
                           "background": "black", "captions": "shown", "source_url": url,
                           "author_or_outlet": "Variety", "posted_at": "2026-09-01",
                           "placed_by": "fact's beat: block holding the beat's first word"}
    lines = ([] if line_span is None else
             [{"fact_id": "production_fact", "text": "Renewed for a fifth season",
               "start_s": line_span[0], "end_s": line_span[1], "block_index": 1,
               "source_url": url if line_url is None else line_url}])
    return {"blocks": blocks, "comparison_lines": lines,
            "proof": {"proof_requested": [{"proof_id": "p1", "verbatim_text": verbatim,
                                           "source_url": url, "capture_method_hint": None}],
                      "proof_delivered": [pl._answer("p1", pl.OUTCOME_PLACED, 1, "rendered_quote",
                                                     ["rendered_quote"], "proof-p1.png",
                                                     {"gating_lines": 3})],
                      "proofs": [{"kind": "proof", "id": "p1", "layer": "proof", "proof_id": "p1",
                                  "block": 1, "source_url": url}],
                      "proof_shortfalls": [], "proof_not_delivered": None,
                      "proof_delivered_fully": True, "notes": []}}


def test_the_card_is_up_for_the_part_of_its_block_the_fact_line_covers():
    """CF-0244. TEXT needs 3.25s to be read, so every window below is over
    the floor and the only question is where it starts and ends."""
    # everyday-sorcery-2's shape: the block outlives the line by 4.80s, which
    # is the 4.80s of measured black the QC gate failed the video for.
    plan = carded((25.58, 39.10), (25.55, 34.30))
    notes = pl.bind_to_lines(plan)
    ins = plan["blocks"][1]["insert"]
    assert (ins["start_s"], ins["end_s"]) == (25.58, 34.30), ins
    assert ins["window_from"] == "fact line" == pl.CARD_WINDOW_FROM
    assert plan["proof"]["proof_delivered_fully"] is True, "a clipped card is still delivered"
    assert any("card up 25.58-34.30s" in n for n in notes), notes
    assert plan["proof"]["notes"] == notes, "the plan keeps the layer's own account of it"
    # Idempotent: the same plan bound twice is the same plan.
    again = json.loads(json.dumps(plan))
    pl.bind_to_lines(again)
    assert again["blocks"] == plan["blocks"] and again["proof"]["proof_delivered"] == \
        plan["proof"]["proof_delivered"]
    # A line that comes up before the block and leaves after it: the card is
    # the whole block, and it says so rather than saying nothing.
    plan = carded((25.58, 30.00), (20.00, 34.30))
    pl.bind_to_lines(plan)
    ins = plan["blocks"][1]["insert"]
    assert (ins["start_s"], ins["end_s"]) == (25.58, 30.00), ins
    # A line that arrives after the block starts: the block's own asset opens
    # the block and the card comes up with the line.
    plan = carded((25.00, 34.00), (26.20, 33.00))
    pl.bind_to_lines(plan)
    assert (plan["blocks"][1]["insert"]["start_s"],
            plan["blocks"][1]["insert"]["end_s"]) == (26.20, 33.00)


def test_a_card_the_fact_line_never_reaches_is_pulled_and_recorded():
    """widows-bay's shape: the card on block 0 (0.00-5.94s) and the fact's
    line 26s away. Every frame of that block was a contained document on
    black with our captions hidden - 98.3% of pixels under blackdetect's
    threshold, and the whole block read as a black screen."""
    plan = carded((0.0, 5.94), (25.94, 32.51), verbatim="Widow's Bay")
    notes = pl.bind_to_lines(plan)
    assert "insert" not in plan["blocks"][1], "the card is off the block"
    pr = plan["proof"]
    assert [a["outcome"] for a in pr["proof_delivered"]] == ["no_line"]
    a = pr["proof_delivered"][0]
    assert a["block_index"] is None
    assert a["file"] == "proof-p1.png" and a["capture_method_used"] == "rendered_quote", (
        "the capture was fetched, measured and passed the gate - only the window is missing")
    assert a["evidence"]["covered_seconds"] == 0.0 and a["evidence"]["floor_seconds"] == 3.0
    assert pr["proofs"] == [], "and it is not claimed as provenance for a video it is not in"
    assert pr["proof_delivered_fully"] is False and pr["proof_not_delivered"] == "no_line"
    sf = pr["proof_shortfalls"]
    assert [x["code"] for x in sf] == ["no_line"]
    assert sf[0]["decision"] == "ship_without_proof", "rung 3, not a refusal"
    assert "0.0s" in sf[0]["note"] and "3.0s" in sf[0]["note"], sf[0]["note"]
    assert any("card pulled off block 1" in n for n in notes), notes
    # Covered, but not for long enough to read: pulled just the same, not
    # shortened to fit.
    plan = carded((25.00, 30.00), (28.00, 30.00))          # 2.0s against 3.25s
    pl.bind_to_lines(plan)
    assert "insert" not in plan["blocks"][1]
    assert plan["proof"]["proof_not_delivered"] == "no_line"


def test_text_box_is_the_union_of_the_recognised_lines():
    """CF-0390: what the caption band keeps clear of. paper-dragon's card, as
    Vision read it: four lines, title to date, in the middle of a 1080x1350
    capture."""
    regions = [{"top": 0.354, "bottom": 0.410, "left": 0.144, "width": 0.613, "height": 0.056,
                "text": "Paper Dragon (2026"},
               {"top": 0.427, "bottom": 0.480, "left": 0.139, "width": 0.161, "height": 0.053,
                "text": "film)"},
               {"top": 0.597, "bottom": 0.631, "left": 0.141, "width": 0.278, "height": 0.034,
                "text": "2026-09-22"}]
    assert pl.text_box_of(regions) == {"top": 0.354, "bottom": 0.631, "left": 0.139,
                                       "right": 0.757}
    assert pl.text_box_of([]) is None and pl.text_box_of(None) is None
    assert pl.source_size_of((1080, 1350)) == {"width": 1080, "height": 1350}
    assert pl.source_size_of(None) is None and pl.source_size_of((0, 10)) is None


def test_a_fact_with_no_line_of_its_own_has_no_card_either():
    """The two are one annotation in two halves. The strip says the fact and
    names the source; the card *is* the source, and it is the half that
    cannot stand on the frame alone."""
    for lines in (None, ):
        plan = carded((25.58, 39.10), lines)
        pl.bind_to_lines(plan)
        assert "insert" not in plan["blocks"][1]
        assert plan["proof"]["proof_not_delivered"] == "no_line"
        ev = plan["proof"]["proof_delivered"][0]["evidence"]
        assert ev["line"] is None and ev["covered_seconds"] is None
    # A line for some other fact is not this card's line either: CF-0243's
    # join is the url and nothing else.
    plan = carded((25.58, 39.10), (25.55, 34.30), line_url="https://example.com/other")
    pl.bind_to_lines(plan)
    assert "insert" not in plan["blocks"][1]


def test_binding_leaves_every_other_insert_alone():
    """A meme is a reaction to its block, not evidence for a sentence: it has
    no second element to agree with, so it keeps the block's whole span and
    gets no window here."""
    plan = carded((25.58, 39.10), (25.55, 34.30))
    plan["blocks"][0]["insert"] = {"kind": "meme", "render_src": "/nowhere/m.png",
                                   "captions": "hidden"}
    pl.bind_to_lines(plan)
    meme = plan["blocks"][0]["insert"]
    assert meme == {"kind": "meme", "render_src": "/nowhere/m.png", "captions": "hidden"}


def test_the_renderer_mounts_the_card_for_its_window_and_moves_captions_with_it():
    """The plan's half of CF-0244 is worth nothing if Remotion still paints
    the card for the block, so the two sides are pinned together here."""
    asset = (RENDER_SRC / "components" / "AssetLayer.jsx").read_text()
    video = (RENDER_SRC / "Video.jsx").read_text()
    # the window is read off the insert, in the block Sequence's own frames
    assert "insertSpan" in asset and "start_s" in asset and "end_s" in asset
    assert "mountFrom" in asset and "mountFrom={from}" in video
    # the card is a Sequence over the block's own asset, not instead of it
    # (CF-0811: the branch is guarded by `drawnOver` - the insert, and on a
    # sequence/procedural block only one with a picture behind it)
    body = asset.split("if (drawnOver) {")[1].split("\n  }")[0]
    assert "<Sequence" in body and "InsertLayer" in body and "<AssetLayer" in body
    # and whatever the captions do for the card - silent under CF-0071 for a
    # plan that still says so - they do it for the card's window, not for the
    # block
    hidden = video.split("hiddenCaptionRanges = ")[1].split(";")[0]
    assert "block.insert.start_s" in hidden and "block.insert.end_s" in hidden, hidden
    # CF-0394: the band does nothing else for the card - it no longer rises
    # over the card's window (CF-0390's rule); the card is fitted above it,
    # in the card's own Sequence, so it makes room exactly for its window
    assert "captionLiftRanges" not in video and "liftRanges" not in video
    layer = asset.split("const InsertLayer = ")[1].split("\n};")[0]
    assert "insertBox(zone, safeArea, height)" in layer, layer


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
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
