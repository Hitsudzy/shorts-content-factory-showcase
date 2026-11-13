#!/usr/bin/env python3
"""CF-0567: ExampleTech's footage origins and rights - the channel data
(`channels/example-tech/footage-origin.json`, `rights-holder-blacklist.json`)
and what the common rule (`shared/footage_licence.py`) gained for it.

* the footage-origin document is whole by `footage_origin_errors`: the
  `own_capture` origin (our own recording - no terms page of its own, the
  hosts' terms instead), the `vendor_official` origin of the proof quotes,
  every capture host with its robots.txt reads and its terms on record, the
  quote caps;
* the 08.10 source rule on the capture hosts: a `capture` host has robots
  `allowed`, terms `allowed` and no sign-in; unread or ambiguous terms close a
  host; `capture_allowed` refuses any host the list does not name;
* the kind is `own_capture`, never `screen_recording` (footage-indexer's
  cam-rip defect, priced hard in shared/gate-prices.json);
* licences: our recording, our own graphic (CF-0689) and an official upload
  taken, anyone else's
  upload refused;
* the official channels are the hunters' registry format, every one a
  `proof_quote`, and none of the vendors is on the rights-holder list;
* the rights-holder list matches the labels and studios, not the vendors.

Reads the tracked channel files as a contract (docs/test-hygiene.md); no
network, nothing written.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CH = "example-tech"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fl = _load("_footage_licence_tt", ROOT / "shared" / "footage_licence.py")
cd = _load("_channel_data_tt", ROOT / "shared" / "channel_data.py")
DOC = cd.footage_origin(CH, ROOT)
LIC = DOC["licences"]
VENDORS = ("OpenAI", "Google", "Google DeepMind", "Anthropic", "Meta", "AI at Meta", "Apple",
           "Microsoft", "Amazon Web Services", "NVIDIA", "Samsung", "Hugging Face")


def _copy():
    return json.loads(json.dumps(DOC))


def _host(doc, name):
    return next(h for h in doc["capture_hosts"] if h["host"] == name)


def test_the_document_is_whole():
    assert fl.footage_origin_errors(DOC) == []


def test_the_other_channels_are_judged_as_before():
    """The rule's additions bite only on `own_capture` and `proof_quote`."""
    sci = cd.footage_origin("example-science", ROOT)
    assert fl.footage_origin_errors(sci) == []
    assert "capture_hosts" not in sci and "proof_quotes" not in sci
    for doc in (sci, cd.footage_origin("example-film", ROOT)):
        assert all(e.get("role", "footage") == "footage" for e in doc["official_channels"])


def test_the_origins_the_grill_gave():
    """The grill's two (CF-0567), the user's own graphics of 12.10 (CF-0689) and
    the demo via API of 12.10 (CF-0690, tests/test_api_demo.py)."""
    by_id = {o["id"]: o for o in DOC["footage_origins"]}
    assert set(by_id) == {"own_capture", "own_graphic", "api_demo", "vendor_official"}
    api = by_id["api_demo"]
    assert api["licence"] == fl.API_DEMO == "api_demo"
    assert api["terms_url"] == "https://ai.google.dev/gemini-api/terms"
    assert [h["how"] for h in api["found_by"]] == ["api_call"]
    drawn = by_id["own_graphic"]
    assert drawn["licence"] == fl.OWN_GRAPHIC == "own_graphic"
    assert drawn["terms_url"] is None and [h["how"] for h in drawn["found_by"]] == ["drawn"]
    assert drawn["attribution"]["required"] is False and drawn["attribution"]["on_screen"] is False
    own = by_id["own_capture"]
    assert own["licence"] == fl.OWN_CAPTURE == "own_capture"
    assert own["terms_url"] is None and own["found_by"][0]["how"] == "screen_capture"
    assert own["attribution"]["required"] is False and own["attribution"]["on_screen"] is False
    off = by_id["vendor_official"]
    assert off["licence"] == "youtube_official_upload"
    assert off["terms_url"].startswith("https://")


def test_the_kind_is_not_the_cam_rip_defect():
    """`screen_recording` is footage-indexer's cinema cam-rip, priced hard; our
    recording must never carry that name."""
    prices = json.loads((ROOT / "shared" / "gate-prices.json").read_text(encoding="utf-8"))
    assert "score.hard.screen_recording" in prices["rules"]
    blob = json.dumps({k: DOC[k] for k in ("licences", "footage_origins")})
    assert '"screen_recording"' not in blob
    assert all(o["id"] != "screen_recording" and o["licence"] != "screen_recording"
               for o in DOC["footage_origins"])


def test_a_broken_document_is_named():
    bad = _copy()
    next(o for o in bad["footage_origins"] if o["id"] == "own_capture")["terms_url"] = \
        "https://example.com/terms"
    hf = _host(bad, "hf.space")
    hf["sign_in"] = True
    hf["ai_policy"]["terms_verdict"] = "ambiguous"
    _host(bad, "openai.com").pop("why_closed")
    bad["official_channels"][0]["role"] = "base"
    bad["proof_quotes"]["never_the_base"] = False
    bad["proof_quotes"]["max_seconds_per_quote"] = 20.0
    errs = "\n".join(fl.footage_origin_errors(bad))
    for part in ("no `terms_url` of its own", "behind a sign-in", "an ambiguous clause is a ban",
                 "`closed` without `why_closed`", "role 'base'", "never_the_base",
                 "longer than all of them together"):
        assert part in errs, (part, errs)
    shut = _copy()
    _host(shut, "hf.space")["use"] = "closed"
    _host(shut, "hf.space")["why_closed"] = "test"
    assert any("no host is `capture`" in e for e in fl.footage_origin_errors(shut))
    gone = _copy()
    gone.pop("capture_hosts")
    assert any("no `capture_hosts`" in e for e in fl.footage_origin_errors(gone))
    gone = _copy()
    gone.pop("proof_quotes")
    assert any("`proof_quotes` missing" in e for e in fl.footage_origin_errors(gone))


def test_every_capture_host_has_its_robots_and_terms_on_record():
    for h in DOC["capture_hosts"]:
        pol = h["ai_policy"]
        assert pol["checked_on"] == "2026-10-11" and pol["checks"], h["host"]
        assert pol["terms_url"].startswith("https://"), h["host"]
        assert pol["terms_verdict"] in fl.TERMS_VERDICTS and pol["terms_note"], h["host"]
        assert all(c["verdict"] in ("allowed", "forbidden", "unknown") for c in pol["checks"])
        if h["use"] == "capture":
            assert pol["verdict"] == "allowed" and pol["terms_verdict"] == "allowed"
            assert h["sign_in"] is False
        else:
            assert h["why_closed"], h["host"]


def test_the_hosts_checked_and_the_one_open():
    hosts = {h["host"]: h for h in DOC["capture_hosts"]}
    for name in ("openai.com", "deepmind.google", "anthropic.com", "apple.com", "nvidia.com",
                 "microsoft.com", "meta.com", "github.com", "huggingface.co"):
        assert hosts[name]["use"] == "closed", name
    assert [n for n, h in hosts.items() if h["use"] == "capture"] == ["hf.space"]
    # unread is not permission
    assert hosts["meta.com"]["ai_policy"]["terms_verdict"] == "unread"
    # the Q23 reading of Google's clause holds here too
    assert hosts["deepmind.google"]["ai_policy"]["terms_verdict"] == "ambiguous"


def test_capture_allowed_reads_the_list_and_nothing_else():
    ok, host = fl.capture_allowed("https://some-lab-some-demo.hf.space/", DOC)
    assert ok and host["host"] == "hf.space"
    for url, why in (("https://huggingface.co/spaces/a/b", "closed"),
                     ("https://openai.com/index/x", "closed"),
                     ("https://www.apple.com/iphone/", "closed"),
                     ("http://some-lab-some-demo.hf.space/", "https"),
                     ("https://example.com/", "not on `capture_hosts`"),
                     ("https://nothf.space/", "not on `capture_hosts`"),
                     ("", "https")):
        ok, reason = fl.capture_allowed(url, DOC)
        assert not ok and why in reason, (url, reason)
    signed = _copy()
    _host(signed, "hf.space")["sign_in"] = True
    ok, reason = fl.capture_allowed("https://a-b.hf.space/", signed)
    assert not ok and "sign-in" in reason


def test_licences_taken_and_refused():
    def lic(name):
        return fl.licence_of(name, LIC)
    assert lic("own capture")["accepted"] and lic("own capture")["attribution"] == "none"
    assert lic("own graphic")["accepted"] and lic("own graphic")["id"] == "own_graphic"
    assert lic("own graphic")["attribution"] == "none"
    assert lic("api demo")["accepted"] and lic("api demo")["id"] == "api_demo"
    assert lic("api demo")["attribution"] == "none"
    assert lic("YouTube official upload")["id"] == "youtube_official_upload"
    got = lic("youtube upload")
    assert not got["accepted"] and got["id"] == "third_party_upload", got
    for name, lid in (("CC BY-NC 4.0", "noncommercial"), ("CC BY-ND 4.0", "noderivatives"),
                      ("All rights reserved", "non_free")):
        got = lic(name)
        assert not got["accepted"] and got["id"] == lid, (name, got)
    for name in ("", None, "screen recording", "CC BY 4.0"):
        assert not lic(name)["accepted"], name


def test_the_quote_caps():
    pq = DOC["proof_quotes"]
    assert pq["never_the_base"] is True and pq["role"] == "proof_quote"
    assert pq["max_seconds_per_quote"] == 5.0
    assert pq["max_quotes_per_video"] == 2 and pq["max_seconds_per_video"] == 8.0
    demo = json.loads((ROOT / "patterns" / "demo.json").read_text(encoding="utf-8"))
    hold = demo["parameters"]["key_frame_hold_seconds"]
    assert pq["max_seconds_per_quote"] <= hold["max"], "a quote is never the longest picture"


def test_the_official_channels_are_the_hunters_registry_format():
    """What agents/trend-hunter/scripts/footage_origin.py load_config refuses
    a list for, checked on this one without loading the agent."""
    ids = set()
    for entry in DOC["official_channels"]:
        re.compile(entry["pattern"], re.I)
        assert entry.get("channels") and entry["origin"] == "vendor_official"
        assert entry["role"] == "proof_quote", entry["pattern"]
        assert not entry.get("general"), "a general entry is read deep for every topic"
        for ch in entry["channels"]:
            assert fl.CHANNEL_ID_RE.match(ch["id"]) and ch["id"] not in ids, ch
            ids.add(ch["id"])
            assert ch["resolved_by"] and ch["handle"].startswith("@")
    titles = {ch["title"] for e in DOC["official_channels"] for ch in e["channels"]}
    for vendor in ("OpenAI", "Google DeepMind", "Anthropic", "Meta", "Apple", "Microsoft",
                   "NVIDIA", "Hugging Face"):
        assert vendor in titles, vendor
    assert DOC.get("footage_kinds") == "tech", "the Trend Hunter's tech kind set (CF-0567 step 4)"


def test_the_rights_holders_are_labels_and_studios_not_the_vendors():
    il = _load("_inserts_lib_tt", ROOT / "shared" / "inserts" / "inserts_lib.py")
    bl = cd.rights_holders(CH, ROOT)
    assert all(e["evidence"] == "heuristic" for e in bl["entries"])
    assert len(bl["entries"]) <= 8, "kept short (CF-0567)"
    for holder in ("Example Music Group", "Example Music", "Warner Music Group", "Example Animation",
                   "Example Pictures", "Example Studios Group"):
        assert il.blacklist_check(holder, None, bl)["matched"], holder
    for holder in VENDORS:
        assert not il.blacklist_check(holder, None, bl)["matched"], holder
    titles = [ch["title"] for e in DOC["official_channels"] for ch in e["channels"]]
    for title in titles:
        assert not il.blacklist_check(title, None, bl)["matched"], (
            f"{title}: an official channel is a quote source, never a listed holder")


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
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
