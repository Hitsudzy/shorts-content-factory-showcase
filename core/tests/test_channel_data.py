#!/usr/bin/env python3
"""CF-0561: the contract of a channel's own lists (`shared/channel_data.py`).

Every case runs on a stand-in factory in a temp directory - two channels, one
of them renamed - so nothing here depends on what the live `channels/` holds
(docs/test-hygiene.md). The equivalence of example-film's moved lists with
what they were is `tests/test_channel_data_equivalence.py`.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "shared" / "channel_data.py"


def load(name="channel_data_under_test"):
    spec = importlib.util.spec_from_file_location(name, MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cd = load()


def make_root(tmp):
    root = Path(tmp)
    (root / "patterns").mkdir()
    (root / "patterns" / "validate_patterns.py").write_text("", encoding="utf-8")
    ch = root / "channels"
    (ch / "alpha").mkdir(parents=True)
    (ch / "beta").mkdir()
    (ch / "alpha.json").write_text(json.dumps({
        "channel_id": "alpha", "former_channel_ids": ["old-alpha"],
        "sources": {"rss": {"enabled": True, "house_ceil": 3}}}), encoding="utf-8")
    (ch / "beta.json").write_text(json.dumps({
        "channel_id": "beta", "sources": {"rss": {"enabled": True}}}), encoding="utf-8")
    (ch / "alpha" / "fact-sources.json").write_text(json.dumps({
        "kinds": ["discovery", "other"],
        "tiers": {"1": [{"id": "nature", "hosts": ["nature.com"], "major_outlet": True}]}}),
        encoding="utf-8")
    (ch / "alpha" / "rights-holder-blacklist.json").write_text(json.dumps({
        "entries": [{"rights_holder": "Acme", "medium": "film_tv", "risk_level": "high"}]}),
        encoding="utf-8")
    (ch / "beta" / "fact-sources.json").write_text(json.dumps({
        "tiers": {"1": [{"id": "x", "hosts": ["x.org"]}]}}), encoding="utf-8")
    return root


def refused(fn, *args, contains=None, **kw):
    try:
        fn(*args, **kw)
    except cd.ChannelDataError as exc:
        if contains:
            assert contains in str(exc), str(exc)
        return str(exc)
    raise AssertionError(f"{fn.__name__}{args} was not refused")


def test_a_list_is_read_for_the_named_channel():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        assert cd.fact_sources("alpha", root)["tiers"]["1"][0]["id"] == "nature"
        assert cd.fact_kinds("alpha", root) == ("discovery", "other")
        assert cd.rights_holders("alpha", root)["entries"][0]["rights_holder"] == "Acme"
        assert cd.rss_house_ceil("alpha", root) == 3
        assert cd.channel_list_path("beta", "rights-holders", root) == \
            root / "channels" / "beta" / "rights-holder-blacklist.json"


def test_no_channel_is_a_refusal_never_a_default():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        for nothing in (None, "", "   "):
            refused(cd.channel_list, nothing, "fact-sources", root, contains="no channel named")
            refused(cd.fact_kinds, nothing, root)


def test_a_former_id_reads_the_current_channel():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        assert cd.channel_id("old-alpha", root) == "alpha"
        assert cd.fact_kinds("old-alpha", root) == ("discovery", "other")
        assert cd.channel_list_path("old-alpha", "fact-sources", root).parent.name == "alpha"


def test_a_missing_list_is_refused_not_borrowed():
    """beta has no rights holders and no footage origin: the refusal names the
    file; alpha's list is not handed out instead."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        msg = refused(cd.rights_holders, "beta", root, contains="channels/beta/rights-holder-blacklist.json")
        assert "no common list" in msg
        refused(cd.footage_origin, "alpha", root, contains="footage-origin.json")
        refused(cd.fact_kinds, "beta", root, contains="`kinds`")
        refused(cd.rss_house_ceil, "beta", root, contains="house_ceil")


def test_unknown_channel_and_unknown_list_are_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        refused(cd.fact_sources, "gamma", root, contains="unknown channel")
        refused(cd.channel_list, "alpha", "box-office", root, contains="not a channel list")


def test_an_unparsable_list_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        (root / "channels" / "beta" / "rights-holder-blacklist.json").write_text("{", encoding="utf-8")
        refused(cd.rights_holders, "beta", root, contains="does not parse")


def test_channels_with_lists_who_carries_a_list():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        assert cd.channels_with("fact-sources", root) == ["alpha", "beta"]
        assert cd.channels_with("rights-holders", root) == ["alpha"]
        assert cd.channels_with("footage-origin", root) == []


TERMS = {"terms_url": "https://example.org/terms", "forbidden": [
    {"id": "according_to", "phrase": "according to Acme",
     "pattern": r"\baccording to acme\b", "why": "the terms' own example"},
    {"id": "acme_says", "phrase": "Acme says", "pattern": r"\bacme(?:'s)? (?:says|confirms)\b",
     "why": "the same attribution"}],
    "allowed": [{"what": "Source: Acme", "why": "a disclosure"}]}


def _with_terms(root, terms):
    p = root / "channels" / "alpha" / "fact-sources.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["tiers"]["1"][0]["ai_output_terms"] = terms
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_an_outlets_terms_for_ai_output_are_read_and_matched():
    """CF-0671: the bans live on the outlet's entry of the channel's list; one
    rule matches them - casefolded, curly apostrophes and dashes evened out,
    links taken out; a channel without the list has none."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        assert cd.attribution_terms("alpha", root) == []          # the entry has no terms
        _with_terms(root, TERMS)
        terms = cd.attribution_terms("old-alpha", root)
        assert [(t["outlet"], [f["id"] for f in t["forbidden"]]) for t in terms] == [
            ("nature", ["according_to", "acme_says"])]
        text = "It is 3 km wide, ACME\u2019s  says. According to\nAcme it grew."
        assert [(h["id"], h["match"]) for h in cd.attribution_hits(text, terms)] == [
            ("acme_says", "acme's says"), ("according_to", "according to acme")]
        for fine in ("Source: Acme https://acme.org/acme-says-x", "Acme launched it",
                     "Footage: Acme"):
            assert cd.attribution_hits(fine, terms) == [], fine
        # a channel with no fact-sources list has no terms; the unknown one is refused
        (root / "channels" / "beta" / "fact-sources.json").unlink()
        assert cd.attribution_terms("beta", root) == []
        refused(cd.attribution_terms, "gamma", root, contains="unknown channel")


def test_terms_that_cannot_be_matched_are_a_refusal_not_a_shorter_list():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        broken = dict(TERMS, forbidden=[dict(TERMS["forbidden"][0], pattern="(unclosed")])
        _with_terms(root, broken)
        refused(cd.attribution_terms, "alpha", root, contains="does not compile")
        _with_terms(root, dict(TERMS, terms_url=None))
        refused(cd.attribution_terms, "alpha", root, contains="terms_url")
        _with_terms(root, dict(TERMS, forbidden=[{"id": "x", "pattern": "x"}]))
        msg = refused(cd.attribution_terms, "alpha", root)
        assert "no `phrase`" in msg and "no `why`" in msg




def test_the_module_loads_by_path_with_nothing_of_the_checkout_on_sys_path():
    """The load an agent performs (CF-0231's form)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        probe = (
            "import importlib.util, sys\n"
            "from pathlib import Path\n"
            "checkout = str(Path(sys.argv[2]).resolve())\n"
            "sys.path[:] = [p for p in sys.path if p and not "
            "str(Path(p).resolve()).startswith(checkout)]\n"
            "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print(','.join(m.fact_kinds('old-alpha', sys.argv[3])))\n")
        proc = subprocess.run([sys.executable, "-c", probe, str(MODULE), str(ROOT), str(root)],
                              capture_output=True, text=True, cwd=tmp, timeout=120)
        assert proc.returncode == 0, proc.stderr.strip()[-400:]
        assert proc.stdout.strip() == "discovery,other", proc.stdout


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
